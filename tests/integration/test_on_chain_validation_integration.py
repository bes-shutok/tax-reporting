"""Integration test: the full on-chain TH validation harness flow (Task 6).

Plan: ``docs/history/plans/2026-08-18-on-chain-validation-harness.md``
(Task 6). Drives the whole harness chain hermetically on synthetic inputs -
``run_validation`` (wallets injected, ``OnChainThSubstituter`` patched at the
consumer module with the committed ``example/`` registries) ->
``build_projection`` (production reader -> processor -> audit -> adapter) ->
Koinly TH via ``_find_report_path`` + ``read_koinly_rows`` + ``is_wallet_row``
-> ``compare_projection`` -> ``group_into_clusters`` -> dispositions append ->
``write_validation_artifacts`` -> exit gate.

First run (one matching + one divergent tx): exit 3 with a NEW template block
appended and a diff CSV row for the divergent tx. Then the user rules the
cluster ``acceptable_difference`` (an append-only hand edit of the
dispositions file), and a second run over the SAME inputs exits 0 without
appending a duplicate block - the user-owned feedback loop closes.

All fixtures are synthetic (synthetic addresses/hashes only; tmp dirs only),
so the audit-hook guard (which covers this file via its ``test_on_chain_*``
name) never sees a forbidden personal-data open.
"""

from __future__ import annotations

import csv
import functools
import logging
from datetime import date
from pathlib import Path

import tax_reporting.application.on_chain_validation.runner as runner_module
from tax_reporting.application.on_chain_th_substitution import OnChainThSubstituter
from tax_reporting.application.on_chain_validation.artifacts import (
    DIFF_CSV_FILENAME,
    MARKDOWN_REPORT_FILENAME,
)
from tax_reporting.application.on_chain_validation.runner import run_validation
from tax_reporting.domain.on_chain_config import OnChainWalletConfig

# Repo root (tests/integration/x.py -> parents[2]).
_REPO_ROOT = Path(__file__).resolve().parents[2]
_EXAMPLE_2025_DIR = _REPO_ROOT / "resources" / "source" / "example" / "2025"
_EXAMPLE_CONTRACTS = _EXAMPLE_2025_DIR / "berachain_contracts.json"
_EXAMPLE_SNAPSHOT = _EXAMPLE_2025_DIR / "berachain_lp_snapshot.json"
_EXAMPLE_POSITION_TOKENS = _EXAMPLE_2025_DIR / "bera_position_tokens.json"

_YEAR = 2025
_DISPOSITIONS_FILENAME = "on_chain_th_dispositions.toml"

# Synthetic wallet label + addresses (PII rule; never real mainnet). The
# reward distributor is registered in the committed example registry, so a
# single in-leg from it classifies as a Reward claim.
_WALLET_LABEL = "Ledger Berachain (BERA)"
_BERA_WALLET_ADDR = "0xabcabcabcabcabcabcabcabcabcabcabcabcabca"
_REWARD_DISTRIBUTOR = "0x000000000000000000000000000000000000beef"
_BGT_TOKEN = "0x000000000000000000000000000000000000b222"

# Real-SHAPE synthetic tx hashes (0x + 64 hex).
_MATCH_HASH = "0x" + f"{11:064x}"
_DIVERGENT_HASH = "0x" + f"{22:064x}"

_BERA_CSV_HEADER = (
    "tx_hash,block_number,timestamp_utc,chain,from_address,to_address,"
    "asset,token_address,amount_raw,amount_decimals,direction,fee_asset,"
    "fee_amount_raw,wallet_label,wallet_address"
)

_KOINLY_TH_HEADER = (
    "Date,Type,Tag,Sending Wallet,Sent Amount,Sent Currency,Sent Cost Basis,"
    "Receiving Wallet,Received Amount,Received Currency,Received Cost Basis,"
    "Fee Amount,Fee Currency,Gain (EUR),Net Value (EUR),Fee Value (EUR),"
    "TxSrc,TxDest,TxHash,Description"
)


def _claim_row(tx_hash: str, *, timestamp_utc: str, block_number: int) -> str:
    """One claim-shaped bera CSV row: a BGT in-leg (0.5) from the registered
    example reward distributor, with tx fee 2100000000000 raw BERA."""
    return (
        f"{tx_hash},{block_number},{timestamp_utc},Berachain,"
        f"{_REWARD_DISTRIBUTOR},{_BERA_WALLET_ADDR},BGT,{_BGT_TOKEN},"
        f"500000000000000000,18,in,BERA,2100000000000,{_WALLET_LABEL},{_BERA_WALLET_ADDR}"
    )


def _koinly_reward_row(tx_hash: str, *, received: str, date_utc: str) -> str:
    """One Koinly TH row mirroring the claim projection (``crypto_deposit`` /
    ``Reward``, 0.5 BGT in, carrier fee in ``Fee Amount``).

    Column alignment: fields 4-7 (Sending Wallet, Sent Amount, Sent Currency,
    Sent Cost Basis) are empty, so the wallet label lands in field 8
    (``Receiving Wallet``).
    """
    return (
        f"{date_utc},crypto_deposit,Reward,,,,,{_WALLET_LABEL},{received},BGT,,"
        f"0.0000021,BERA,,,,{_REWARD_DISTRIBUTOR},{_BERA_WALLET_ADDR},{tx_hash},"
    )


class TestOnChainValidationIntegration:
    """Full harness chain on synthetic example-registry inputs."""

    def test_end_to_end_hermetic_flow(self, tmp_path: Path, monkeypatch) -> None:
        """Load -> compare -> cluster -> dispositions -> artifacts -> exit 3,
        then exit 0 on the re-run after the user dispositions the cluster."""
        # Hermetic collaborators: example registries + injected wallet.
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
        wallets = [
            OnChainWalletConfig(
                chain="Berachain",
                chainid=80094,
                label=_WALLET_LABEL,
                address=_BERA_WALLET_ADDR,
                native_ticker="BERA",
                start_date=date(_YEAR, 1, 1),
                end_date=date(_YEAR, 12, 31),
            )
        ]

        # One matching tx + one divergent tx (Koinly Received Amount 0.4 vs
        # on-chain 0.5 - an amount mismatch far beyond the display tolerance).
        bera = tmp_path / str(_YEAR) / "bera_transactions.csv"
        bera.parent.mkdir(parents=True, exist_ok=True)
        bera.write_text(
            "\n".join(
                [
                    _BERA_CSV_HEADER,
                    _claim_row(_MATCH_HASH, timestamp_utc="2025-02-26T10:00:00+00:00", block_number=1000),
                    _claim_row(_DIVERGENT_HASH, timestamp_utc="2025-02-27T11:00:00+00:00", block_number=1001),
                    "",
                ]
            ),
            encoding="utf-8",
        )
        koinly_dir = tmp_path / "koinly"
        koinly_dir.mkdir()
        (koinly_dir / "koinly_transaction_history.csv").write_text(
            "\n".join(
                [
                    "Transaction report 2025",
                    "",
                    _KOINLY_TH_HEADER,
                    _koinly_reward_row(_MATCH_HASH, received="0.5", date_utc="2025-02-26 10:00:00 UTC"),
                    _koinly_reward_row(_DIVERGENT_HASH, received="0.4", date_utc="2025-02-27 11:00:00 UTC"),
                    "",
                ]
            ),
            encoding="utf-8",
        )

        def _run() -> int:
            return run_validation(
                year=_YEAR,
                output_dir=tmp_path,
                koinly_dir=koinly_dir,
                wallets=wallets,
                logger=logging.getLogger(__name__),
            )

        # First run: the divergent cluster is NEW -> exit 3, artifacts written.
        assert _run() == 3

        year_dir = tmp_path / str(_YEAR)
        assert (year_dir / MARKDOWN_REPORT_FILENAME).is_file()
        with (year_dir / DIFF_CSV_FILENAME).open(encoding="utf-8", newline="") as handle:
            diff_rows = list(csv.reader(handle))
        assert diff_rows[0] == ["Tx Hash", "Cluster Signature", "Disposition", "Mismatch Summary"]
        assert [row[0] for row in diff_rows[1:]] == [_DIVERGENT_HASH]
        assert all(row[2] == "NEW" for row in diff_rows[1:])

        dispositions = year_dir / _DISPOSITIONS_FILENAME
        first_text = dispositions.read_text(encoding="utf-8")
        # The header comment mentions "[[clusters]]" inline; an actual BLOCK
        # always starts on its own line - count blocks, not comment mentions.
        assert first_text.count("\n[[clusters]]\n") == 1

        # The user rules the cluster acceptable_difference (append-only edit).
        ruled_text = first_text.replace('disposition = ""', 'disposition = "acceptable_difference"')
        assert ruled_text != first_text, "the NEW block must carry an empty disposition to fill"
        dispositions.write_text(ruled_text, encoding="utf-8")

        # Second run over the SAME inputs: the cluster still occurs but no
        # longer blocks -> exit 0, and no duplicate block was appended.
        assert _run() == 0
        final_text = dispositions.read_text(encoding="utf-8")
        assert final_text.count("\n[[clusters]]\n") == 1
        with (year_dir / DIFF_CSV_FILENAME).open(encoding="utf-8", newline="") as handle:
            rerun_rows = list(csv.reader(handle))
        assert [row[0] for row in rerun_rows[1:]] == [_DIVERGENT_HASH]
        assert all(row[2] == "acceptable_difference" for row in rerun_rows[1:])
