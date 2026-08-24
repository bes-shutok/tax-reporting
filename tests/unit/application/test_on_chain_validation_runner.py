"""Unit tests for the on-chain TH validation runner (validation-harness Task 6).

Plan: ``docs/history/plans/2026-08-18-on-chain-validation-harness.md``
(Task 6). ``run_validation`` wires the harness end to end: wallet resolution
(``chains.json`` Berachain entries by default), the Task-1 production
projection (``OnChainThSubstituter.build_projection``), the Koinly TH baseline
(``_find_report_path`` + ``read_koinly_rows`` filtered by ``is_wallet_row``
and, when a window is set, by an inclusive date filter), then
compare -> cluster -> dispositions -> artifacts -> gate.

Hermeticity (plan Design Invariant 5): every test injects ``wallets`` except
the default-resolution test, which monkeypatches ``load_on_chain_wallets`` at
the CONSUMER module ``tax_reporting.application.on_chain_validation.runner``
(patching the source module is ineffective under from-import binding - the
documented ``run_report.py:31`` patch-seam convention). The substituter is
likewise patched with the committed ``example/`` registry paths so no
gitignored personal data is opened (the audit-hook guard covers this file via
its ``test_on_chain_*`` name).

All fixtures are synthetic (synthetic addresses/hashes only, PII rule): one
claim-shaped bera CSV row (BGT in-leg from the example-registry reward
distributor, tx fee 2100000000000 raw BERA = 0.0000021 BERA) projects to
exactly one ``crypto_deposit/Reward`` row whose carrier fee a matching Koinly
row mirrors via its ``Fee Amount`` cell, so a projection-equivalent Koinly
baseline yields a clean match (exit 0).
"""

from __future__ import annotations

import csv
import functools
import logging
from datetime import date
from pathlib import Path

import pytest

import tax_reporting.application.on_chain_validation.runner as runner_module
from tax_reporting.application.on_chain_th_substitution import OnChainThSubstituter
from tax_reporting.application.on_chain_validation.artifacts import (
    DIFF_CSV_FILENAME,
    MARKDOWN_REPORT_FILENAME,
)
from tax_reporting.application.on_chain_validation.runner import run_validation
from tax_reporting.domain.on_chain_config import OnChainWalletConfig

# Repo root (tests/unit/application/x.py -> parents[3]).
_REPO_ROOT = Path(__file__).resolve().parents[3]
_EXAMPLE_2025_DIR = _REPO_ROOT / "resources" / "source" / "example" / "2025"
_EXAMPLE_CONTRACTS = _EXAMPLE_2025_DIR / "berachain_contracts.json"
_EXAMPLE_SNAPSHOT = _EXAMPLE_2025_DIR / "berachain_lp_snapshot.json"
_EXAMPLE_POSITION_TOKENS = _EXAMPLE_2025_DIR / "bera_position_tokens.json"

_YEAR = 2025
# Synthetic wallet label + addresses (PII rule; never real mainnet). The
# reward distributor is registered in the committed example registry, so a
# single in-leg from it classifies as a Reward claim.
_WALLET_LABEL = "Ledger Berachain (BERA)"
_OTHER_WALLET_LABEL = "Metamask ETH"
_BERA_WALLET_ADDR = "0xabcabcabcabcabcabcabcabcabcabcabcabcabca"
_REWARD_DISTRIBUTOR = "0x000000000000000000000000000000000000beef"
_BGT_TOKEN = "0x000000000000000000000000000000000000b222"
#: Listed in the committed example LP snapshot (an ordinary-ticker claim leg
#: carrying THIS token address must sign ``lp=true`` - review r1 F1).
_EXAMPLE_LP_TOKEN = "0x000000000000000000000000000000000000dead"

# Real-SHAPE synthetic tx hashes (0x + 64 hex) so fixtures mirror production.
_MATCH_HASH = "0x" + f"{11:064x}"
_DIVERGENT_HASH = "0x" + f"{22:064x}"
_OTHER_WALLET_HASH = "0x" + f"{33:064x}"
_IN_WINDOW_HASH = "0x" + f"{44:064x}"
_OUT_WINDOW_HASH = "0x" + f"{55:064x}"

_DISPOSITIONS_FILENAME = "on_chain_th_dispositions.toml"

# The FULL 15-column header the reader's OnChainTxRow contract requires (same
# shape as the e2e ``_bera_csv_rows`` header; missing columns make the reader
# warn-and-skip every data row).
_BERA_CSV_HEADER = (
    "tx_hash,block_number,timestamp_utc,chain,from_address,to_address,"
    "asset,token_address,amount_raw,amount_decimals,direction,fee_asset,"
    "fee_amount_raw,wallet_label,wallet_address"
)

# The Koinly TH CSV shape (preamble + header) ``read_koinly_rows`` parses.
_KOINLY_TH_HEADER = (
    "Date,Type,Tag,Sending Wallet,Sent Amount,Sent Currency,Sent Cost Basis,"
    "Receiving Wallet,Received Amount,Received Currency,Received Cost Basis,"
    "Fee Amount,Fee Currency,Gain (EUR),Net Value (EUR),Fee Value (EUR),"
    "TxSrc,TxDest,TxHash,Description"
)


# --------------------------------------------------------------------------- #
# Fixture builders (all synthetic; tmp dirs only - audit-guard safe)           #
# --------------------------------------------------------------------------- #


def _wallet(*, chain: str = "Berachain", label: str = _WALLET_LABEL) -> OnChainWalletConfig:
    """A synthetic wallet config (``chainid``/ticker per the chain registry)."""
    return OnChainWalletConfig(
        chain=chain,
        chainid=80094 if chain == "Berachain" else 1,
        label=label,
        address=_BERA_WALLET_ADDR,
        native_ticker="BERA" if chain == "Berachain" else "ETH",
        start_date=date(_YEAR, 1, 1),
        end_date=date(_YEAR, 12, 31),
    )


def _claim_row(
    tx_hash: str,
    *,
    timestamp_utc: str = "2025-02-26T10:00:00+00:00",
    block_number: int = 1000,
) -> str:
    """One claim-shaped bera CSV row: a BGT in-leg (0.5) from the registered
    example reward distributor, with tx fee 2100000000000 raw BERA."""
    return (
        f"{tx_hash},{block_number},{timestamp_utc},Berachain,"
        f"{_REWARD_DISTRIBUTOR},{_BERA_WALLET_ADDR},BGT,{_BGT_TOKEN},"
        f"500000000000000000,18,in,BERA,2100000000000,{_WALLET_LABEL},{_BERA_WALLET_ADDR}"
    )


def _write_bera_csv(output_dir: Path, data_rows: list[str]) -> Path:
    """Write a synthetic ``bera_transactions.csv`` under the full 15-column
    header into a tmp ``output_dir`` and return its path."""
    bera = output_dir / str(_YEAR) / "bera_transactions.csv"
    bera.parent.mkdir(parents=True, exist_ok=True)
    bera.write_text("\n".join([_BERA_CSV_HEADER, *data_rows, ""]), encoding="utf-8")
    return bera


def _koinly_reward_row(
    tx_hash: str,
    *,
    received: str = "0.5",
    date_utc: str = "2025-02-26 10:00:00 UTC",
    receiving_wallet: str = _WALLET_LABEL,
) -> str:
    """One Koinly TH row mirroring the claim projection: ``crypto_deposit`` /
    ``Reward`` receiving 0.5 BGT with the carrier fee in ``Fee Amount``.

    Column alignment: fields 4-7 (Sending Wallet, Sent Amount, Sent Currency,
    Sent Cost Basis) are empty, so the wallet label lands in field 8
    (``Receiving Wallet``).
    """
    return (
        f"{date_utc},crypto_deposit,Reward,,,,,{receiving_wallet},{received},BGT,,"
        f"0.0000021,BERA,,,,{_REWARD_DISTRIBUTOR},{_BERA_WALLET_ADDR},{tx_hash},"
    )


def _write_koinly_th(koinly_dir: Path, rows: list[str]) -> Path:
    """Write a synthetic Koinly TH CSV (preamble + header + rows) whose
    filename matches the ``*transaction_history*.csv`` discovery glob."""
    koinly_dir.mkdir(parents=True, exist_ok=True)
    th = koinly_dir / "koinly_transaction_history.csv"
    th.write_text(
        "\n".join(["Transaction report 2025", "", _KOINLY_TH_HEADER, *rows, ""]),
        encoding="utf-8",
    )
    return th


def _patch_example_registries(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch the runner module's ``OnChainThSubstituter`` (consumer-module seam)
    with a factory injecting the committed ``example/`` registry paths, so the
    projection never reads gitignored personal registries."""
    monkeypatch.setattr(
        runner_module,
        "OnChainThSubstituter",
        functools.partial(
            OnChainThSubstituter,
            contracts_path=_EXAMPLE_CONTRACTS,
            lp_snapshot_path=_EXAMPLE_SNAPSHOT,
            position_tokens_path=_EXAMPLE_POSITION_TOKENS,
        ),
    )


def _run(
    output_dir: Path,
    *,
    koinly_dir: Path | None,
    wallets: list[OnChainWalletConfig] | None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> int:
    """Invoke ``run_validation`` with the hermetic test logger."""
    return run_validation(
        year=_YEAR,
        output_dir=output_dir,
        koinly_dir=koinly_dir,
        wallets=wallets,
        date_from=date_from,
        date_to=date_to,
        logger=logging.getLogger(__name__),
    )


def _year_dir(output_dir: Path) -> Path:
    return output_dir / str(_YEAR)


def _read_diff_rows(year_dir: Path) -> list[list[str]]:
    with (year_dir / DIFF_CSV_FILENAME).open(encoding="utf-8", newline="") as handle:
        return list(csv.reader(handle))


@pytest.mark.unit
class TestOnChainValidationRunner:
    """Runner wiring: inputs -> compare -> cluster -> dispositions -> exit."""

    def test_match_case_exits_zero_and_writes_artifacts(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A projection-equivalent Koinly baseline exits 0 and writes all three
        files: both regenerated artifacts plus a header-only dispositions file
        (no NEW blocks - nothing diverged)."""
        _patch_example_registries(monkeypatch)
        _write_bera_csv(tmp_path, [_claim_row(_MATCH_HASH)])
        _write_koinly_th(tmp_path / "koinly", [_koinly_reward_row(_MATCH_HASH)])

        status = _run(tmp_path, koinly_dir=tmp_path / "koinly", wallets=[_wallet()])

        assert status == 0
        year_dir = _year_dir(tmp_path)
        assert (year_dir / MARKDOWN_REPORT_FILENAME).is_file()
        assert (year_dir / DIFF_CSV_FILENAME).is_file()
        dispositions_text = (year_dir / _DISPOSITIONS_FILENAME).read_text(encoding="utf-8")
        assert "APPEND-ONLY" in dispositions_text, "expected the explanatory header comment"
        # The header comment mentions "[[clusters]]" inline; an actual BLOCK
        # always starts on its own line - count blocks, not comment mentions.
        assert "\n[[clusters]]\n" not in dispositions_text, "no NEW blocks when nothing diverged"
        markdown = (year_dir / MARKDOWN_REPORT_FILENAME).read_text(encoding="utf-8")
        assert "Matched (semantically equivalent): 1" in markdown

    def test_divergent_case_exits_three_and_appends(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """One divergent cluster (Koinly Received Amount 0.4 vs on-chain 0.5)
        exits 3, appends one NEW template block, and lands a diff CSV row for
        the divergent tx only."""
        _patch_example_registries(monkeypatch)
        _write_bera_csv(
            tmp_path,
            [
                _claim_row(_MATCH_HASH),
                _claim_row(_DIVERGENT_HASH, timestamp_utc="2025-02-27T11:00:00+00:00", block_number=1001),
            ],
        )
        _write_koinly_th(
            tmp_path / "koinly",
            [
                _koinly_reward_row(_MATCH_HASH),
                _koinly_reward_row(_DIVERGENT_HASH, received="0.4", date_utc="2025-02-27 11:00:00 UTC"),
            ],
        )

        status = _run(tmp_path, koinly_dir=tmp_path / "koinly", wallets=[_wallet()])

        assert status == 3
        dispositions_text = (_year_dir(tmp_path) / _DISPOSITIONS_FILENAME).read_text(encoding="utf-8")
        assert dispositions_text.count("\n[[clusters]]\n") == 1, "exactly one NEW template block"
        assert 'disposition = ""' in dispositions_text
        diff_rows = _read_diff_rows(_year_dir(tmp_path))
        assert diff_rows[0] == ["Tx Hash", "Cluster Signature", "Disposition", "Mismatch Summary"]
        assert [row[0] for row in diff_rows[1:]] == [_DIVERGENT_HASH]

    def test_wallets_default_resolution_patched(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Default wallet resolution: ``load_on_chain_wallets`` (patched at the
        CONSUMER module - the ``run_report.py:31`` seam convention) returning
        synthetic Berachain + Ethereum wallets keeps ONLY the Berachain label
        under validation; the Ethereum wallet's Koinly row is filtered out
        (never a Koinly-only cluster)."""
        _patch_example_registries(monkeypatch)
        _write_bera_csv(tmp_path, [_claim_row(_MATCH_HASH)])
        _write_koinly_th(
            tmp_path / "koinly",
            [
                _koinly_reward_row(_MATCH_HASH),
                _koinly_reward_row(
                    _OTHER_WALLET_HASH,
                    receiving_wallet=_OTHER_WALLET_LABEL,
                    date_utc="2025-03-01 09:00:00 UTC",
                ),
            ],
        )
        monkeypatch.setattr(
            runner_module,
            "load_on_chain_wallets",
            lambda _year: [_wallet(), _wallet(chain="Ethereum", label=_OTHER_WALLET_LABEL)],
        )

        status = _run(tmp_path, koinly_dir=tmp_path / "koinly", wallets=None)

        assert status == 0, "the Ethereum wallet's row must not be under validation"
        markdown = (_year_dir(tmp_path) / MARKDOWN_REPORT_FILENAME).read_text(encoding="utf-8")
        assert _WALLET_LABEL in markdown
        assert _OTHER_WALLET_LABEL not in markdown
        assert "Koinly only: 0" in markdown
        assert _OTHER_WALLET_HASH not in (_year_dir(tmp_path) / DIFF_CSV_FILENAME).read_text(encoding="utf-8")

    @pytest.mark.parametrize(
        "resolved_wallets",
        [[], [_wallet(chain="Ethereum", label=_OTHER_WALLET_LABEL)]],
        ids=["empty-resolution", "no-berachain-entry"],
    )
    def test_no_berachain_wallets_fails_loud(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
        resolved_wallets: list[OnChainWalletConfig],
    ) -> None:
        """Empty wallet resolution (no wallets at all, or none on Berachain) is
        a clear error + exit 1 - never a silent exit 0."""
        _patch_example_registries(monkeypatch)
        monkeypatch.setattr(runner_module, "load_on_chain_wallets", lambda _year: resolved_wallets)

        with caplog.at_level(logging.ERROR):
            status = _run(tmp_path, koinly_dir=tmp_path / "koinly", wallets=None)

        assert status == 1
        assert any("Berachain" in record.message and "wallet" in record.message for record in caplog.records), (
            "the error must name the missing Berachain wallets"
        )
        assert not (_year_dir(tmp_path) / _DISPOSITIONS_FILENAME).exists()

    @pytest.mark.parametrize("missing_side", ["no-koinly-dir", "no-transaction-history-csv"])
    def test_missing_koinly_side_fails_loud_before_dispositions(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
        missing_side: str,
    ) -> None:
        """Either missing-Koinly-side source - (a) directory resolution returns
        ``None`` (patched at the consumer module; any post-2025 run hits this
        first since no 2026 exports exist), or (b) a resolved dir with no
        ``*transaction_history*.csv`` - is a clear error naming the missing
        input + exit 1, raised BEFORE any dispositions append."""
        _patch_example_registries(monkeypatch)
        _write_bera_csv(tmp_path, [_claim_row(_MATCH_HASH)])
        koinly_dir: Path | None = tmp_path / "koinly"
        if missing_side == "no-koinly-dir":
            monkeypatch.setattr(runner_module, "_resolve_koinly_directory", lambda *_args, **_kwargs: None)
            koinly_dir = None  # drive the (patched) default resolution
        else:
            empty_dir = tmp_path / "empty-koinly"
            empty_dir.mkdir()
            koinly_dir = empty_dir  # exists but carries no TH CSV

        with caplog.at_level(logging.ERROR):
            status = _run(tmp_path, koinly_dir=koinly_dir, wallets=[_wallet()])

        assert status == 1
        assert any("Koinly" in record.message for record in caplog.records), (
            "the error must name the missing Koinly input"
        )
        assert not (_year_dir(tmp_path) / _DISPOSITIONS_FILENAME).exists(), (
            "a misconfigured run must never write feedback-loop state"
        )

    def test_missing_bera_csv_fails_loud(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """An absent bera CSV (build_projection -> None) is a clear error +
        exit 1 - the runner must convert the None projection into the explicit
        "nothing validated" signal, never fall through to an empty comparison
        (review r1 F2; mirrors the two sibling fail-loud arms)."""
        _patch_example_registries(monkeypatch)
        # The Koinly TH fixture exists FIRST so the bera-CSV check is the one
        # exercised (not the Koinly-side enumeration).
        _write_koinly_th(tmp_path / "koinly", [_koinly_reward_row(_MATCH_HASH)])

        with caplog.at_level(logging.ERROR):
            status = _run(tmp_path, koinly_dir=tmp_path / "koinly", wallets=[_wallet()])

        assert status == 1
        assert any("bera_transactions.csv" in record.message for record in caplog.records), (
            "the error must name the missing on-chain CSV"
        )
        assert any("nothing was validated" in record.message for record in caplog.records)
        assert not (_year_dir(tmp_path) / _DISPOSITIONS_FILENAME).exists(), (
            "a misconfigured run must never write feedback-loop state"
        )

    def test_empty_comparison_fails_loud(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A run whose window filters BOTH sides to zero rows must exit 1,
        never a vacuous exit 0 (review r1 F5, blocking): exit 0 is the
        acceptance evidence for the production flag flip, and a run that
        compared zero transactions must not be readable as "validated"."""
        _patch_example_registries(monkeypatch)
        # Both sides carry the same tx, but the window excludes it everywhere.
        _write_bera_csv(tmp_path, [_claim_row(_MATCH_HASH)])
        _write_koinly_th(tmp_path / "koinly", [_koinly_reward_row(_MATCH_HASH)])

        with caplog.at_level(logging.ERROR):
            status = _run(
                tmp_path,
                koinly_dir=tmp_path / "koinly",
                wallets=[_wallet()],
                date_from=date(2025, 6, 1),
                date_to=date(2025, 6, 30),
            )

        assert status == 1, "an empty comparison is 'nothing validated', not a pass"
        assert any("nothing was validated" in record.message.lower() for record in caplog.records), (
            "the error must state explicitly that nothing was validated"
        )
        assert any("window" in record.message.lower() for record in caplog.records), (
            "the error must point at the likely cause (the --from/--to window)"
        )
        assert not (_year_dir(tmp_path) / _DISPOSITIONS_FILENAME).exists(), (
            "a nothing-validated run must never write feedback-loop state"
        )

    def test_lp_signature_resolves_from_on_chain_token_addresses(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The ``lp`` cluster-signature component resolves from the on-chain
        legs' token ADDRESSES on the runner path (review r1 F1): a divergent
        claim whose visible tickers are ordinary symbols on both sides but
        whose leg carries the snapshot-listed LP token address appends a
        block signed ``lp=true`` (the asset-identifier fallback cannot fire -
        no identifier on either side matches the snapshot's address keys)."""
        _patch_example_registries(monkeypatch)
        # The LP claim carries its own ticker (LPBGT): one folded ticker must
        # map to exactly one contract per dataset (the comparator's identity
        # guard), so reusing "BGT" for a second address would be rejected as
        # a collision - and would not model reality.
        lp_claim = _claim_row(
            _DIVERGENT_HASH,
            timestamp_utc="2025-02-27T11:00:00+00:00",
            block_number=1001,
        ).replace(f"BGT,{_BGT_TOKEN}", f"LPBGT,{_EXAMPLE_LP_TOKEN}")
        _write_bera_csv(tmp_path, [_claim_row(_MATCH_HASH), lp_claim])
        _write_koinly_th(
            tmp_path / "koinly",
            [
                _koinly_reward_row(_MATCH_HASH),
                _koinly_reward_row(_DIVERGENT_HASH, received="0.4", date_utc="2025-02-27 11:00:00 UTC"),
            ],
        )

        status = _run(tmp_path, koinly_dir=tmp_path / "koinly", wallets=[_wallet()])

        assert status == 3
        dispositions_text = (_year_dir(tmp_path) / _DISPOSITIONS_FILENAME).read_text(encoding="utf-8")
        assert dispositions_text.count("\n[[clusters]]\n") == 1, "exactly the LP-token divergent cluster appended"
        assert "|lp=true|" in dispositions_text, (
            "the LP-token claim must sign lp=true via the threaded token addresses"
        )

    def test_window_filters_both_sides_equally(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """The inclusive ``--from/--to`` window filters BOTH sides: the
        out-of-window tx appears NOWHERE in the comparison (not even as a
        one-sided on-chain-only / Koinly-only record), and the run header
        records the window."""
        _patch_example_registries(monkeypatch)
        _write_bera_csv(
            tmp_path,
            [
                _claim_row(_IN_WINDOW_HASH, timestamp_utc="2025-03-10T10:00:00+00:00", block_number=1000),
                _claim_row(_OUT_WINDOW_HASH, timestamp_utc="2025-09-15T10:00:00+00:00", block_number=1001),
            ],
        )
        _write_koinly_th(
            tmp_path / "koinly",
            [
                _koinly_reward_row(_IN_WINDOW_HASH, date_utc="2025-03-10 10:00:00 UTC"),
                _koinly_reward_row(_OUT_WINDOW_HASH, date_utc="2025-09-15 10:00:00 UTC"),
            ],
        )

        status = _run(
            tmp_path,
            koinly_dir=tmp_path / "koinly",
            wallets=[_wallet()],
            date_from=date(2025, 1, 1),
            date_to=date(2025, 6, 30),
        )

        assert status == 0, "both sides filtered equally: no one-sided out-of-window record may remain"
        year_dir = _year_dir(tmp_path)
        markdown = (year_dir / MARKDOWN_REPORT_FILENAME).read_text(encoding="utf-8")
        assert "Validation window: 2025-01-01 to 2025-06-30 (inclusive)" in markdown
        assert "Shared transaction hashes: 1" in markdown
        assert "On-chain only: 0" in markdown
        assert "Koinly only: 0" in markdown
        assert _OUT_WINDOW_HASH not in markdown
        assert _OUT_WINDOW_HASH not in (year_dir / DIFF_CSV_FILENAME).read_text(encoding="utf-8")

    def test_window_boundaries_inclusive_on_both_sides(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Transactions dated EXACTLY ``--from`` and EXACTLY ``--to`` stay in
        the comparison on BOTH sides (review r1 F11): the Koinly-side filter
        and the projection window are separately written predicates, so a
        ``<`` vs ``<=`` drift on either side must fail loudly here - as a
        one-sided boundary record or the F5 empty-comparison exit - never as
        a quietly narrowed window."""
        window_from_hash = "0x" + f"{66:064x}"
        window_to_hash = "0x" + f"{77:064x}"
        _patch_example_registries(monkeypatch)
        _write_bera_csv(
            tmp_path,
            [
                _claim_row(window_from_hash, timestamp_utc="2025-01-01T00:00:00+00:00", block_number=1000),
                _claim_row(window_to_hash, timestamp_utc="2025-06-30T23:59:59+00:00", block_number=1001),
            ],
        )
        _write_koinly_th(
            tmp_path / "koinly",
            [
                _koinly_reward_row(window_from_hash, date_utc="2025-01-01 00:00:00 UTC"),
                _koinly_reward_row(window_to_hash, date_utc="2025-06-30 23:59:59 UTC"),
            ],
        )

        status = _run(
            tmp_path,
            koinly_dir=tmp_path / "koinly",
            wallets=[_wallet()],
            date_from=date(2025, 1, 1),
            date_to=date(2025, 6, 30),
        )

        assert status == 0, "both boundary txs are inside the inclusive window on both sides"
        markdown = (_year_dir(tmp_path) / MARKDOWN_REPORT_FILENAME).read_text(encoding="utf-8")
        assert "Shared transaction hashes: 2" in markdown
        assert "On-chain only: 0" in markdown
        assert "Koinly only: 0" in markdown
