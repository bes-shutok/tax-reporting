"""Unit tests for the on-chain fetcher orchestrator + CSV writer (Task 5).

TDD RED -> GREEN. These tests cover :func:`run_on_chain_fetch`, the
orchestration step of the optional on-chain transaction fetcher. The
fetcher loads the per-year wallet config, drives the Etherscan V2 client
for each wallet, decodes raw rows, and writes a single consolidated CSV.

Network-free (DI-3): the HTTP transport is the module-level
:func:`tax_reporting.infrastructure.on_chain.etherscan_client._http_get_json`
seam; tests monkeypatch THAT name, never the low-level transport module.

Config-free (DI-8): :func:`load_on_chain_wallets` is monkeypatched to
return an artificial wallet list so the tests do not depend on a real
``resources/source/<year>/chains.json``.
"""

from __future__ import annotations

import csv
import logging
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from tax_reporting.application.on_chain_config import (
    OnChainWalletConfig,
    load_position_token_registry_for_year,
)
from tax_reporting.application.on_chain_fetcher import run_on_chain_fetch
from tax_reporting.application.paths import resolve_registry_path
from tax_reporting.domain.exceptions import FileProcessingError

# Module path of the DI-3 HTTP seam (monkeypatched per-test).
_HTTP_SEAM = "tax_reporting.infrastructure.on_chain.etherscan_client._http_get_json"
# Module path of the config loader (monkeypatched to avoid repo-root files).
_LOADER = "tax_reporting.application.on_chain_fetcher.load_on_chain_wallets"
# Module path of the per-year position-token registry loader (monkeypatched
# per-test so the fetcher tests never read repo-root / gitignored registry
# files). Review r4 F7: the loader is the shared facade imported into the
# fetcher namespace.
_REGISTRY_LOADER = (
    "tax_reporting.application.on_chain_fetcher.load_position_token_registry_for_year"
)

# Synthetic position-token-registry member contract (hermetic; clearly fake).
_POS_CONTRACT = "0x0000000000000000000000000000000000007777"
_NON_MEMBER_CONTRACT = "0x0000000000000000000000000000000000008888"


def _wallet(
    *,
    chain: str = "Examplechain",
    chainid: int = 99999,
    label: str = "Example Wallet (EXM)",
    address: str = "0x0000000000000000000000000000000000001111",
    native_ticker: str = "EXM",
) -> OnChainWalletConfig:
    """Return an artificial OnChainWalletConfig (no real chain identity)."""
    return OnChainWalletConfig(
        chain=chain,
        chainid=chainid,
        label=label,
        address=address,
        native_ticker=native_ticker,
        start_date=date(2025, 2, 6),
        end_date=date(2025, 12, 31),
    )


def _txlist_row(**overrides: Any) -> dict[str, Any]:
    """Return one artificial txlist (native transfer) raw row.

    Any field can be overridden via keyword, e.g. ``_txlist_row(hash="0xab")``.
    """
    row: dict[str, Any] = {
        "hash": "0xaaa",
        "blockNumber": "100",
        "timeStamp": "1739000000",
        "from": "0x0000000000000000000000000000000000001111",
        "to": "0x0000000000000000000000000000000000002222",
        "value": "1000000000000000000",
        "gasUsed": "21000",
        "gasPrice": "1000000000",
    }
    row.update(overrides)
    return row


def _tokentx_row(**overrides: Any) -> dict[str, Any]:
    """Return one artificial tokentx (ERC-20 transfer) raw row.

    Any field can be overridden via keyword.
    """
    row: dict[str, Any] = {
        "hash": "0xbbb",
        "blockNumber": "200",
        "timeStamp": "1739000100",
        "from": "0x0000000000000000000000000000000000003333",
        "to": "0x0000000000000000000000000000000000001111",
        "value": "5000000",
        "tokenSymbol": "USDC",
        "tokenDecimal": "6",
        "contractAddress": "0xtoken",
    }
    row.update(overrides)
    return row


def _nft_row(**overrides: Any) -> dict[str, Any]:
    """Return one artificial nfttx (ERC-721 transfer) raw row."""
    row: dict[str, Any] = {
        "hash": "0xccc",
        "blockNumber": "300",
        "timeStamp": "1739000200",
        "from": "0x0000000000000000000000000000000000003333",
        "to": "0x0000000000000000000000000000000000001111",
        "contractAddress": _POS_CONTRACT,
        "tokenSymbol": "ALGB-POS",
        "tokenID": "26874",
    }
    row.update(overrides)
    return row


def _position_registry(member_contracts: list[str]):
    """Build a synthetic position-token registry (hermetic, inline)."""
    from tax_reporting.infrastructure.on_chain.position_token_registry import (
        build_position_token_registry,
    )

    return build_position_token_registry(
        {
            "tokens": [
                {
                    "token_address": addr,
                    "label": "ALGB-POS",
                    "kind": "position_nft",
                }
                for addr in member_contracts
            ]
        },
        source="<inline-test>",
    )


def _etherscan_payload(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Wrap raw rows in a status:"1" Etherscan V2 success response."""
    return {"status": "1", "message": "OK", "result": list(rows)}


def _install_fake_http(
    monkeypatch: pytest.MonkeyPatch, **canned: Any
) -> dict[str, int]:
    """Monkeypatch the DI-3 HTTP seam + registry loader (hermetic defaults).

    Keyword args configure the fake (all optional):
        txlist_rows / tokentx_rows / nfttx_rows: default flat row lists.
        txlist_rows_by_address / tokentx_rows_by_address /
        nfttx_rows_by_address: per-address maps.
        position_registry: registry returned by the patched loader (defaults
            to an EMPTY registry, so no test reads repo-root files).
        raise_exc: a BaseException to raise instead of returning a payload.

    Returns a call-counter dict ``{"calls": n}`` the test can inspect. The
    fake dispatches on the ``action`` query param
    (``txlist``/``tokentx``/``nfttx``); per-address maps take precedence over
    the flat default lists.
    """
    txlist_by_addr = canned.get("txlist_rows_by_address", {})  # type: ignore[arg-type]
    tokentx_by_addr = canned.get("tokentx_rows_by_address", {})  # type: ignore[arg-type]
    nfttx_by_addr = canned.get("nfttx_rows_by_address", {})  # type: ignore[arg-type]
    default_txlist = canned.get("txlist_rows", [])  # type: ignore[arg-type]
    default_tokentx = canned.get("tokentx_rows", [])  # type: ignore[arg-type]
    default_nfttx = canned.get("nfttx_rows", [])  # type: ignore[arg-type]
    raise_exc = canned.get("raise_exc")
    monkeypatch.setattr(
        _REGISTRY_LOADER,
        lambda _year, _override=None, _repo_root=None: canned.get("position_registry")
        or _position_registry([]),
    )
    counter = {"calls": 0}

    def fake_http(url: str, params: dict[str, str | int]) -> dict[str, Any]:
        counter["calls"] += 1
        if isinstance(raise_exc, BaseException):
            raise raise_exc
        action = str(params.get("action"))
        address = str(params.get("address"))
        if action == "txlist":
            rows = txlist_by_addr.get(address, default_txlist)
        elif action == "tokentx":
            rows = tokentx_by_addr.get(address, default_tokentx)
        elif action == "tokennfttx":
            rows = nfttx_by_addr.get(address, default_nfttx)
        else:
            rows = []
        return _etherscan_payload(rows)

    monkeypatch.setattr(_HTTP_SEAM, fake_http)
    return counter


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    """Return (header fieldnames, list of row dicts) from a CSV at ``path``."""
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        fieldnames = list(reader.fieldnames or [])
        rows = [dict(r) for r in reader]
    return fieldnames, rows


class TestEmptyConfigMarker:
    """Review r3 (risk): an empty wallet config with a prior CSV writes the
    staleness marker, so a config regression cannot silently leave the TH
    substitution on a stale CSV with no signal."""

    def test_empty_wallets_with_prior_csv_writes_marker(self, monkeypatch, tmp_path):
        from tax_reporting.application import on_chain_fetcher as fetcher_module
        from tax_reporting.application.on_chain_fetcher import (
            fetch_failed_marker_path,
            run_on_chain_fetch,
        )

        monkeypatch.setattr(fetcher_module, "load_on_chain_wallets", lambda _year: [])
        csv = tmp_path / "2025" / "bera_transactions.csv"
        csv.parent.mkdir(parents=True)
        csv.write_text("tx_hash\n", encoding="utf-8")

        result = run_on_chain_fetch(year=2025, output_dir=tmp_path, api_key="k")

        assert result is None
        marker = fetch_failed_marker_path(tmp_path, 2025)
        assert marker.is_file()
        assert "empty wallet config" in marker.read_text(encoding="utf-8")

    def test_empty_wallets_without_prior_csv_writes_no_marker(self, monkeypatch, tmp_path):
        from tax_reporting.application import on_chain_fetcher as fetcher_module
        from tax_reporting.application.on_chain_fetcher import (
            fetch_failed_marker_path,
            run_on_chain_fetch,
        )

        monkeypatch.setattr(fetcher_module, "load_on_chain_wallets", lambda _year: [])

        result = run_on_chain_fetch(year=2025, output_dir=tmp_path, api_key="k")

        assert result is None
        assert not fetch_failed_marker_path(tmp_path, 2025).exists()


class TestWriteFetchFailedMarker:
    """Review r2 F2: the marker write is best-effort by contract."""

    def test_os_error_swallowed_with_warning(self, monkeypatch, tmp_path, caplog) -> None:
        from pathlib import Path as _Path

        from tax_reporting.application.on_chain_fetcher import write_fetch_failed_marker

        def boom(self, content, encoding=None):
            raise OSError("disk full")

        monkeypatch.setattr(_Path, "write_text", boom)
        with caplog.at_level(logging.WARNING, logger="tax_reporting.application.on_chain_fetcher"):
            write_fetch_failed_marker(tmp_path, 2025, "On-chain fetch failed: x")

        assert any(
            "fetch-failure marker" in rec.getMessage() for rec in caplog.records
        ), "expected the best-effort WARNING"

    def test_writes_message_next_to_csv(self, tmp_path) -> None:
        from tax_reporting.application.on_chain_fetcher import (
            fetch_failed_marker_path,
            write_fetch_failed_marker,
        )

        write_fetch_failed_marker(tmp_path, 2025, "On-chain fetch failed: y")
        marker = fetch_failed_marker_path(tmp_path, 2025)
        assert marker.is_file()
        assert "On-chain fetch failed: y" in marker.read_text(encoding="utf-8")


class TestBeraCsvPath:
    """Tests for the bera-CSV path helper (fetcher-owned single literal)."""

    def test_bera_csv_path_value(self, tmp_path: Path):
        """Given ``output_dir`` and ``year``, expects ``bera_csv_path`` to
        return ``output_dir / str(year) / "bera_transactions.csv"``.

        Characterization (Task 3 consolidation): pins the path value around
        the helper's move into the fetcher module.
        """
        from tax_reporting.application.on_chain_fetcher import bera_csv_path

        assert bera_csv_path(tmp_path, 2025) == (
            tmp_path / "2025" / "bera_transactions.csv"
        )


class TestResolveRegistryPath:
    """Direct tests for ``resolve_registry_path``'s three branches (r1 F4)."""

    def _resolve(self, repo_root: Path, override: Path | None) -> Path:
        return resolve_registry_path(2025, "reg.json", override, repo_root)

    def test_override_wins(self, tmp_path: Path):
        """Given an explicit override, expects it returned verbatim."""
        override = tmp_path / "override.json"
        override.write_text("{}", encoding="utf-8")

        assert self._resolve(tmp_path, override) == override

    def test_primary_per_user_file_wins_info_by_default(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ):
        """Given an existing per-user primary file (and an example fallback
        also present), expects the PRIMARY returned. Review r4 F1: the
        DEFAULT (non-data-loss registries - contracts, LP snapshot,
        position tokens, whose committed example is a template and whose
        per-user file is the designed production source) logs INFO naming
        the file, NEVER a WARNING: the r3 F8 data-loss WARNING was
        over-broad and carried wrong copy-and-append advice on the
        expected path.
        """
        primary = tmp_path / "resources" / "source" / "2025" / "reg.json"
        primary.parent.mkdir(parents=True)
        primary.write_text("{}", encoding="utf-8")
        fallback = tmp_path / "resources" / "source" / "example" / "2025" / "reg.json"
        fallback.parent.mkdir(parents=True)
        fallback.write_text("{}", encoding="utf-8")

        with caplog.at_level(logging.INFO, logger="tax_reporting.application.paths"):
            assert self._resolve(tmp_path, None) == primary

        assert any(
            "reg.json" in record.getMessage()
            for record in caplog.records
            if record.levelno == logging.INFO
        ), "expected an INFO naming the per-user registry"
        assert not [
            record for record in caplog.records if record.levelno >= logging.WARNING
        ], "the default per-user leg must not log WARNING (r4 F1: expected path, not data loss)"

    def test_primary_per_user_file_warning_when_shadow_is_data_loss(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ):
        """Given an existing per-user primary file AND
        ``shadow_is_data_loss=True`` (the bridged-asset registry, whose
        committed file is canonical), expects a WARNING naming the file,
        its replace-not-merge semantics, and the copy-and-append hint
        (reviews r2 F2 + r3 F8; scope narrowed by r4 F1 to the flagged leg
        only).
        """
        primary = tmp_path / "resources" / "source" / "2025" / "reg.json"
        primary.parent.mkdir(parents=True)
        primary.write_text("{}", encoding="utf-8")

        with caplog.at_level(logging.INFO, logger="tax_reporting.application.paths"):
            assert (
                resolve_registry_path(
                    2025, "reg.json", None, tmp_path, shadow_is_data_loss=True
                )
                == primary
            )

        assert any(
            "reg.json" in record.getMessage()
            and "fully replaces the committed registry" in record.getMessage()
            and "copy the committed file and append" in record.getMessage()
            for record in caplog.records
            if record.levelno == logging.WARNING
        ), "expected a WARNING naming the per-user registry, its replace semantics, and the copy-and-append hint"

    def test_absent_primary_returns_example_fallback(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ):
        """Given NO per-user primary, expects the committed-example fallback
        path returned (whether or not it exists - existence is the loader's
        concern; it degrades with a WARNING). Review r5 overflow (post-exit
        polish): the fallback leg is the out-of-the-box default for every
        registry, so it must stay WARNING-free on BOTH the default and the
        ``shadow_is_data_loss=True`` leg (a fallback-leg WARNING regression
        would spam every default run).
        """
        expected_fallback = (
            tmp_path / "resources" / "source" / "example" / "2025" / "reg.json"
        )

        with caplog.at_level(logging.INFO, logger="tax_reporting.application.paths"):
            assert resolve_registry_path(2025, "reg.json", None, tmp_path) == (
                expected_fallback
            )
            assert (
                resolve_registry_path(
                    2025, "reg.json", None, tmp_path, shadow_is_data_loss=True
                )
                == expected_fallback
            )

        assert not [
            record for record in caplog.records if record.levelno >= logging.WARNING
        ], "the fallback leg must not log WARNING (expected default path, not data loss)"


class TestLoadPositionRegistryWiring:
    """Wiring tests for the fetcher's registry resolution (review r1 F4).

    These pin the REAL per-year loader chain (resolution -> loader); every
    ``run_on_chain_fetch`` test monkeypatches the loader, so without these
    the resolution path is untested. Review r4 F7: the chain lives in the
    shared facade :func:`load_position_token_registry_for_year`
    (``application.on_chain_config``); the fetcher and the TH substituter
    both call it. Hermeticity: the repo-root-pinned case uses a year with
    NO per-user (gitignored) and NO example registry file, so no personal
    data is ever opened; the example-resolution case pins the root to a
    synthetic tree.
    """

    def test_load_position_registry_resolves_example_fallback(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Given a root whose per-user file is absent but whose committed
        example exists, expects the registry loaded FROM the example path.
        """
        example = (
            tmp_path
            / "resources"
            / "source"
            / "example"
            / "2025"
            / "bera_position_tokens.json"
        )
        example.parent.mkdir(parents=True)
        example.write_text(
            '{"tokens": [{"token_address": '
            '"0x0000000000000000000000000000000000007777", '
            '"label": "ALGB-POS", "kind": "position_nft"}]}',
            encoding="utf-8",
        )

        registry = load_position_token_registry_for_year(2025, repo_root=tmp_path)

        assert registry.source.endswith(
            "resources/source/example/2025/bera_position_tokens.json"
        )
        assert registry.is_position_token(
            "0x0000000000000000000000000000000000007777"
        )

    def test_load_position_registry_for_year_defaults_root_to_repo(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """The facade's ``repo_root=None`` fallback arm (the fetcher's only
        production path): the root resolves via
        ``on_chain_config.find_repository_root`` when the caller does not
        supply one (review r5 F2; mirrors the e2e pattern of patching the
        imported name). Without this pin, a regression re-rooting the
        fallback would degrade silently to an empty registry.
        """
        example = (
            tmp_path
            / "resources"
            / "source"
            / "example"
            / "2025"
            / "bera_position_tokens.json"
        )
        example.parent.mkdir(parents=True)
        example.write_text(
            '{"tokens": [{"token_address": "0xabc", "kind": "position_nft"}]}',
            encoding="utf-8",
        )
        monkeypatch.setattr(
            "tax_reporting.application.on_chain_config.find_repository_root",
            lambda: tmp_path,
        )

        registry = load_position_token_registry_for_year(2025)

        assert registry.source.endswith(
            "resources/source/example/2025/bera_position_tokens.json"
        )

    def test_load_position_registry_degrades_with_warning(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ):
        """Given an EMPTY tmp root (no per-user and no example registry file
        for the year; review r2 F2: pinned to tmp_path, never the REAL repo
        root - the per-user ``resources/source/<year>/`` tree is gitignored
        and machine-dependent, so the real root makes the test
        non-hermetic), expects an EMPTY registry and a WARNING naming the
        resolved file (the degrade path).
        """
        with caplog.at_level(logging.WARNING):
            registry = load_position_token_registry_for_year(2024, repo_root=tmp_path)

        assert registry.tokens == {}
        warning_text = "\n".join(rec.message for rec in caplog.records)
        assert "No position-token registry" in warning_text
        assert "bera_position_tokens.json" in warning_text


class TestOnChainFetcher:
    """Tests for run_on_chain_fetch (orchestrator + CSV writer)."""

    def test_fetch_passes_fiscal_year_to_registry_loader(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Review r5 F3: pin the year plumbing - the fetcher must pass the
        # fiscal year to load_position_token_registry_for_year (a hardcoded
        # year regression would silently load the wrong per-year registry
        # while every fake loader swallows the argument).
        seen_years: list[int] = []

        def _spy_loader(year, _override=None, _repo_root=None):
            seen_years.append(year)
            return _position_registry([])

        monkeypatch.setattr(_LOADER, lambda _year: [_wallet()])
        _install_fake_http(monkeypatch)
        # AFTER _install_fake_http: it patches _REGISTRY_LOADER with its
        # hermetic default, so the spy must be installed on top of it.
        monkeypatch.setattr(_REGISTRY_LOADER, _spy_loader)

        run_on_chain_fetch(year=2024, output_dir=tmp_path, api_key="k")

        assert seen_years == [2024]

    def test_run_writes_csv_for_single_wallet(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Given a config with one artificial wallet and a mocked HTTP seam
        returning 2 txlist + 1 tokentx rows, expects
        ``output_dir/<year>/bera_transactions.csv`` written with a header
        plus 3 data rows, sorted by ``block_number``.

        The CSV is sorted by block_number ascending (txlist rows at lower
        blocks precede the tokentx row at a higher block). Python's stable
        sort preserves decode order for rows sharing a block.
        """
        from tax_reporting.application.on_chain_fetcher import run_on_chain_fetch

        wallet = _wallet()
        monkeypatch.setattr(_LOADER, lambda _year: [wallet])
        _install_fake_http(
            monkeypatch,
            txlist_rows=[
                _txlist_row(hash="0xa1", blockNumber="100"),
                _txlist_row(hash="0xa2", blockNumber="150"),
            ],
            tokentx_rows=[_tokentx_row(hash="0xb1", blockNumber="200")],
        )

        result = run_on_chain_fetch(
            year=2025, output_dir=tmp_path, api_key="test-key"
        )

        assert result is not None
        csv_path = tmp_path / "2025" / "bera_transactions.csv"
        assert csv_path == result
        fieldnames, rows = _read_csv(csv_path)
        # Header carries the OnChainTxRow fields.
        assert "tx_hash" in fieldnames
        assert "wallet_label" in fieldnames
        assert len(rows) == 3
        # Sorted by block_number ascending (stable: decode order within a block).
        block_numbers = [int(r["block_number"]) for r in rows]
        assert block_numbers == sorted(block_numbers)
        # The three distinct hashes are all present.
        hashes = {r["tx_hash"] for r in rows}
        assert hashes == {"0xa1", "0xa2", "0xb1"}

    def test_run_creates_year_subdir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Given an ``output_dir`` WITHOUT a ``<year>/`` subdir, expects the
        fetcher to create ``output_dir / str(year) /`` before writing.
        """
        from tax_reporting.application.on_chain_fetcher import run_on_chain_fetch

        wallet = _wallet()
        monkeypatch.setattr(_LOADER, lambda _year: [wallet])
        _install_fake_http(
            monkeypatch, txlist_rows=[_txlist_row()], tokentx_rows=[]
        )

        year_dir = tmp_path / "2025"
        assert not year_dir.exists()

        run_on_chain_fetch(year=2025, output_dir=tmp_path, api_key="k")

        assert year_dir.is_dir()
        assert (year_dir / "bera_transactions.csv").is_file()

    def test_empty_result_writes_header_only(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Given a mocked HTTP seam returning NO rows, expects a header-only
        CSV (the file EXISTS with zero data rows - this distinguishes "no
        transactions" from "fetch failed").
        """
        from tax_reporting.application.on_chain_fetcher import run_on_chain_fetch

        wallet = _wallet()
        monkeypatch.setattr(_LOADER, lambda _year: [wallet])
        _install_fake_http(monkeypatch, txlist_rows=[], tokentx_rows=[])

        result = run_on_chain_fetch(
            year=2025, output_dir=tmp_path, api_key="k"
        )

        assert result is not None
        csv_path = tmp_path / "2025" / "bera_transactions.csv"
        assert csv_path.is_file()
        fieldnames, rows = _read_csv(csv_path)
        assert len(fieldnames) > 0
        assert rows == []

    def test_uses_safe_remove_file_before_write(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Given a pre-existing ``bera_transactions.csv`` with stale content,
        expects the fetcher to remove it before writing so the new content
        fully replaces the old (reuses ``safe_remove_file``).
        """
        from tax_reporting.application.on_chain_fetcher import run_on_chain_fetch

        wallet = _wallet()
        monkeypatch.setattr(_LOADER, lambda _year: [wallet])
        _install_fake_http(
            monkeypatch, txlist_rows=[_txlist_row(hash="0xfresh")],
            tokentx_rows=[],
        )

        year_dir = tmp_path / "2025"
        year_dir.mkdir(parents=True)
        csv_path = year_dir / "bera_transactions.csv"
        csv_path.write_text("STALE,CONTENT\nold,old\n", encoding="utf-8")

        run_on_chain_fetch(year=2025, output_dir=tmp_path, api_key="k")

        fieldnames, rows = _read_csv(csv_path)
        # Stale content gone; exactly one fresh data row present.
        assert all("STALE" not in f for f in fieldnames)
        assert len(rows) == 1
        assert rows[0]["tx_hash"] == "0xfresh"

    def test_api_failure_raises_fileprocessingerror(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Given a mocked HTTP seam whose client call raises
        FileProcessingError, expects the orchestrator to PROPAGATE it (NOT
        swallow). The caller in main.py owns the broad ``except Exception``
        catch (DI-1); the fetcher must not pre-empt it.
        """
        from tax_reporting.application.on_chain_fetcher import run_on_chain_fetch

        wallet = _wallet()
        monkeypatch.setattr(_LOADER, lambda _year: [wallet])
        boom = FileProcessingError("boom: simulated transport failure")
        _install_fake_http(monkeypatch, raise_exc=boom)

        with pytest.raises(FileProcessingError, match="boom"):
            run_on_chain_fetch(
                year=2025, output_dir=tmp_path, api_key="k"
            )

    def test_multiple_wallets_independent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Given a config with TWO wallet entries (two distinct chains),
        expects rows for BOTH wallets in the consolidated CSV, each tagged
        with its own ``wallet_label`` / ``wallet_address`` / ``chain``.
        """
        from tax_reporting.application.on_chain_fetcher import run_on_chain_fetch

        wallet_a = _wallet(
            chain="Examplechain",
            chainid=99999,
            label="Wallet A",
            address="0x0000000000000000000000000000000000001111",
        )
        wallet_b = _wallet(
            chain="Otherchain",
            chainid=88888,
            label="Wallet B",
            address="0x0000000000000000000000000000000000009999",
            native_ticker="OTH",
        )
        monkeypatch.setattr(_LOADER, lambda _year: [wallet_a, wallet_b])
        # Review r4 F5: wallet B also gets an nfttx row (address-keyed per
        # wallet) so the multi-wallet x nfttx combination is covered: the
        # consolidated CSV row must carry wallet B's address/label and the
        # SYMBOL#tokenID asset.
        wallet_b_nft = _nft_row(
            hash="0xwn",
            blockNumber="30",
            to=wallet_b.address,  # the receiving wallet drives direction
        )
        _install_fake_http(
            monkeypatch,
            txlist_rows_by_address={
                wallet_a.address: [_txlist_row(hash="0xwa", blockNumber="10")],
                wallet_b.address: [_txlist_row(hash="0xwb", blockNumber="20")],
            },
            tokentx_rows_by_address={
                wallet_a.address: [],
                wallet_b.address: [],
            },
            nfttx_rows_by_address={
                wallet_a.address: [],
                wallet_b.address: [wallet_b_nft],
            },
            position_registry=_position_registry([_POS_CONTRACT]),
        )

        run_on_chain_fetch(year=2025, output_dir=tmp_path, api_key="k")

        csv_path = tmp_path / "2025" / "bera_transactions.csv"
        _, rows = _read_csv(csv_path)
        assert len(rows) == 3
        rows_by_hash = {r["tx_hash"]: r for r in rows}
        labels = {r["wallet_label"] for r in rows}
        addresses = {r["wallet_address"] for r in rows}
        chains = {r["chain"] for r in rows}
        assert labels == {"Wallet A", "Wallet B"}
        assert addresses == {wallet_a.address, wallet_b.address}
        assert chains == {"Examplechain", "Otherchain"}
        # Each wallet's row carries its own address tag.
        for row in rows:
            if row["tx_hash"] == "0xwa":
                assert row["wallet_address"] == wallet_a.address
                assert row["chain"] == "Examplechain"
            elif row["tx_hash"] == "0xwb":
                assert row["wallet_address"] == wallet_b.address
                assert row["chain"] == "Otherchain"
        # Review r4 F5: wallet B's nfttx row lands in the consolidated CSV
        # tagged with wallet B's address/label and the SYMBOL#tokenID asset.
        assert rows_by_hash["0xwn"]["wallet_address"] == wallet_b.address
        assert rows_by_hash["0xwn"]["wallet_label"] == "Wallet B"
        assert rows_by_hash["0xwn"]["asset"] == "ALGB-POS#26874"

    def test_empty_config_returns_none_and_warns_once(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ):
        """Given an empty wallet config (no chains.json for the year),
        expects the orchestrator to return ``None`` and emit EXACTLY ONE
        WARNING owned at this layer (DI-6: the loader stays silent).
        """
        from tax_reporting.application.on_chain_fetcher import run_on_chain_fetch

        monkeypatch.setattr(_LOADER, lambda _year: [])

        with caplog.at_level(
            logging.WARNING, logger="tax_reporting.application.on_chain_fetcher"
        ):
            result = run_on_chain_fetch(
                year=2025, output_dir=tmp_path, api_key="k"
            )

        assert result is None
        warnings = [
            r for r in caplog.records if r.levelno == logging.WARNING
        ]
        assert len(warnings) == 1, (
            "Orchestrator must own exactly one WARNING for an empty config (DI-6)."
        )
        assert "No chains.json" in warnings[0].getMessage()

    def test_fetch_writes_nft_rows_to_csv(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Given a stubbed client returning txlist + tokentx + nfttx rows for
        a registry-member contract, expects the written
        ``bera_transactions.csv`` to contain the ``ALGB-POS#26874`` row with
        the existing 15-column schema unchanged (gains rows, not columns).
        """
        from tax_reporting.application.on_chain_fetcher import run_on_chain_fetch

        wallet = _wallet()
        monkeypatch.setattr(_LOADER, lambda _year: [wallet])
        _install_fake_http(
            monkeypatch,
            txlist_rows=[_txlist_row(hash="0xaaa", blockNumber="100")],
            tokentx_rows=[_tokentx_row(hash="0xbbb", blockNumber="200")],
            nfttx_rows=[_nft_row(hash="0xccc", blockNumber="300")],
            position_registry=_position_registry([_POS_CONTRACT]),
        )

        result = run_on_chain_fetch(year=2025, output_dir=tmp_path, api_key="k")

        assert result is not None
        fieldnames, rows = _read_csv(result)
        # Review r1 overflow: the header is pinned to the FULL OnChainTxRow
        # field order (a column rename would fail here, not just a count
        # change).
        import dataclasses

        from tax_reporting.infrastructure.on_chain.bera_decoder import OnChainTxRow

        assert fieldnames == [f.name for f in dataclasses.fields(OnChainTxRow)]
        assert len(fieldnames) == 15
        nft_rows = [r for r in rows if r["asset"] == "ALGB-POS#26874"]
        assert len(nft_rows) == 1
        assert nft_rows[0]["tx_hash"] == "0xccc"
        assert nft_rows[0]["token_address"] == _POS_CONTRACT
        assert nft_rows[0]["amount_raw"] == "1"
        assert nft_rows[0]["amount_decimals"] == "0"
        assert nft_rows[0]["direction"] == "in"

    def test_fetch_skips_non_registry_nft_contracts(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ):
        """Given a stubbed client whose nfttx page mixes one registry-member
        and one non-member transfer, expects only the member row written and
        a WARNING carrying the skipped count (C8 membership gating).
        """
        from tax_reporting.application.on_chain_fetcher import run_on_chain_fetch

        wallet = _wallet()
        monkeypatch.setattr(_LOADER, lambda _year: [wallet])
        _install_fake_http(
            monkeypatch,
            txlist_rows=[],
            tokentx_rows=[],
            nfttx_rows=[
                _nft_row(hash="0xmember", blockNumber="300"),
                _nft_row(
                    hash="0xspam",
                    blockNumber="301",
                    contractAddress=_NON_MEMBER_CONTRACT,
                    tokenSymbol="BERA777",
                ),
            ],
            position_registry=_position_registry([_POS_CONTRACT]),
        )

        with caplog.at_level(
            logging.WARNING,
            logger="tax_reporting.infrastructure.on_chain.bera_decoder",
        ):
            result = run_on_chain_fetch(year=2025, output_dir=tmp_path, api_key="k")

        assert result is not None
        _, rows = _read_csv(result)
        assert len(rows) == 1
        assert rows[0]["tx_hash"] == "0xmember"
        # Review r2 F5: pin the exact count record, not a digit-substring
        # over the joined text (blockNumber "301" also contains "1").
        skip_warnings = [
            rec
            for rec in caplog.records
            if "not position_nft-kind registry members" in rec.getMessage()
        ]
        assert len(skip_warnings) == 1
        assert "Skipped 1 nfttx row" in skip_warnings[0].getMessage()
