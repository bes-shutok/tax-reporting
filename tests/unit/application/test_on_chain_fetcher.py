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

from tax_reporting.application.on_chain_config import OnChainWalletConfig
from tax_reporting.domain.exceptions import FileProcessingError

# Module path of the DI-3 HTTP seam (monkeypatched per-test).
_HTTP_SEAM = "tax_reporting.infrastructure.on_chain.etherscan_client._http_get_json"
# Module path of the config loader (monkeypatched to avoid repo-root files).
_LOADER = "tax_reporting.application.on_chain_fetcher.load_on_chain_wallets"


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


def _etherscan_payload(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Wrap raw rows in a status:"1" Etherscan V2 success response."""
    return {"status": "1", "message": "OK", "result": list(rows)}


def _install_fake_http(
    monkeypatch: pytest.MonkeyPatch, **canned: list[dict[str, Any]] | BaseException
) -> dict[str, int]:
    """Monkeypatch the DI-3 HTTP seam to return canned Etherscan payloads.

    Keyword args configure the fake (all optional):
        txlist_rows / tokentx_rows: default flat row lists for any address.
        txlist_rows_by_address / tokentx_rows_by_address: per-address maps.
        raise_exc: a BaseException to raise instead of returning a payload.

    Returns a call-counter dict ``{"calls": n}`` the test can inspect. The
    fake dispatches on the ``action`` query param (``txlist``/``tokentx``);
    per-address maps take precedence over the flat default lists.
    """
    txlist_by_addr = canned.get("txlist_rows_by_address", {})  # type: ignore[arg-type]
    tokentx_by_addr = canned.get("tokentx_rows_by_address", {})  # type: ignore[arg-type]
    default_txlist = canned.get("txlist_rows", [])  # type: ignore[arg-type]
    default_tokentx = canned.get("tokentx_rows", [])  # type: ignore[arg-type]
    raise_exc = canned.get("raise_exc")
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


class TestOnChainFetcher:
    """Tests for run_on_chain_fetch (orchestrator + CSV writer)."""

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
        )

        run_on_chain_fetch(year=2025, output_dir=tmp_path, api_key="k")

        csv_path = tmp_path / "2025" / "bera_transactions.csv"
        _, rows = _read_csv(csv_path)
        assert len(rows) == 2
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
