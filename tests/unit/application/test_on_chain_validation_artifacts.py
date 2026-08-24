"""Unit tests for validation artifact writers (validation-harness Task 5).

Plan: ``docs/history/plans/2026-08-18-on-chain-validation-harness.md``
(Task 5). The harness writes two REGENERATED (never appended) artifacts
under ``<output_dir>/<year>/`` (production: gitignored
``resources/result/<year>/``; these tests use a ``tmp_path`` stand-in):

- ``on_chain_th_validation.md``: run header (inputs, ``snapshot_as_of_block``,
  RPC on/off, wallet labels, validation window), summary counts
  (shared/Koinly-only/on-chain-only/match/divergent + per-cluster
  dispositioned-vs-NEW), and one section per discrepancy cluster with at
  most 5 side-by-side samples (tx hash + on-chain shape vs Koinly shape +
  amount diffs).
- ``on_chain_th_validation_diff.csv``: one row per divergent tx keyed by
  ``tx_hash``, with the cluster signature and a mismatch summary.

The artifacts deliberately CONTAIN real tx hashes: the PII rule is enforced
by LOCATION (only the gitignored result dir), not by omission (Design
Invariant 6; pinned here by ``test_real_hashes_allowed_only_under_result_dir``).

The records under test come from the PRODUCTION chain
(``project_on_chain_transactions`` -> ``compare_projection`` ->
``group_into_clusters``), so the writers are validated against exactly the
record shapes the harness will render. Registry and LP snapshot are
in-memory domain objects (synthetic addresses only - PII rule).

Pinned behaviors (each test names its plan bullet):

1. ``test_markdown_report_structure`` - run header (all six inputs; the
   validation window renders ``--from/--to`` dates AND "full year"), summary
   counts, per-cluster dispositioned-vs-NEW, one section per cluster, at
   most 5 samples with amount diffs and the "... and N more" truncation.
2. ``test_diff_csv_one_row_per_divergent_tx`` - 3 divergent txs in 2
   clusters yield exactly 3 CSV rows keyed by ``tx_hash`` with the cluster
   signature + mismatch summary columns.
3. ``test_artifacts_regenerated_not_appended`` - pre-existing (stale)
   artifact files are REPLACED by a rerun, never concatenated.
4. ``test_real_hashes_allowed_only_under_result_dir`` - artifacts land
   under ``<output_dir>/<year>/`` and contain the (real-shaped) tx hashes.
"""

from __future__ import annotations

import csv
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from tax_reporting.application.on_chain_th_adapter import project_on_chain_transactions
from tax_reporting.application.on_chain_validation.artifacts import (
    DIFF_CSV_FILENAME,
    MARKDOWN_REPORT_FILENAME,
    ValidationRunHeader,
    write_validation_artifacts,
)
from tax_reporting.application.on_chain_validation.clustering import group_into_clusters
from tax_reporting.application.on_chain_validation.comparator import (
    ComparisonResult,
    Presence,
    ThComparisonRecord,
    compare_projection,
)
from tax_reporting.application.on_chain_validation.dispositions import DispositionEntry
from tax_reporting.domain.on_chain_config import (
    ContractRegistry,
    LpSnapshot,
)
from tax_reporting.domain.on_chain_transaction import (
    Event,
    EventType,
    Gas,
    Leg,
    OnChainTransaction,
    SubType,
)

# Synthetic identifiers only (Design Invariant PII; never real mainnet values).
# Real-SHAPE tx hashes (0x + 64 hex chars) so the location-based PII rule is
# pinned against exactly what production artifacts will carry.
_DIVERGENT_HASHES = tuple(f"0x{index:064x}" for index in range(1, 8))  # 7 same-shape claims
_MATCHED_HASH = "0x" + f"{99:064x}"
_GAS_ONLY_HASH = "0x" + f"{98:064x}"
_NFT_HASH = "0x" + f"{97:064x}"
_WALLET_ADDRESS = "0xWallet0000000000000000000000000000000000a"
_COUNTERPARTY = "0xCounterParty00000000000000000000000000000b"
_BGT_TOKEN = "0xToken0000000000000000000000000000000001"
_WALLET_LABEL = "Ledger Berachain (BERA)"
_TIMESTAMP = datetime(2025, 3, 1, 12, 0, 0, tzinfo=UTC)
_DECIMALS = 18

# Run-header fixture values (the future runner passes these in verbatim).
_YEAR = 2025
_ON_CHAIN_CSV = "resources/source/2025/bera_transactions.csv"
_KOINLY_SOURCE = "resources/source/koinly2025"
_SNAPSHOT_AS_OF_BLOCK = 12_345


# --------------------------------------------------------------------------- #
# Fixture builders (on-chain side through the PRODUCTION adapter)              #
# --------------------------------------------------------------------------- #


def _to_raw(amount: Decimal, decimals: int = _DECIMALS) -> int:
    """Exact integer smallest-units for a clean decimal ``amount``."""
    return int(amount.scaleb(decimals))


def _in_leg(*, asset: str, amount: Decimal, token_address: str | None, source: str = _COUNTERPARTY) -> Leg:
    """An inflow leg from ``source`` into the tracked wallet."""
    return Leg(
        asset=asset,
        token_address=token_address,
        amount_raw=_to_raw(amount),
        amount_decimals=_DECIMALS,
        direction="in",
        from_address=source,
        to_address=_WALLET_ADDRESS,
    )


def _out_leg(*, asset: str, amount: Decimal, token_address: str | None) -> Leg:
    """An outflow leg from the tracked wallet to the counterparty."""
    return Leg(
        asset=asset,
        token_address=token_address,
        amount_raw=_to_raw(amount),
        amount_decimals=_DECIMALS,
        direction="out",
        from_address=_WALLET_ADDRESS,
        to_address=_COUNTERPARTY,
    )


def _tx(tx_hash: str, events: list[Event], *, gas: Gas | None = None) -> OnChainTransaction:
    """Wrap events into an ``OnChainTransaction`` (single wallet)."""
    return OnChainTransaction(
        tx_hash=tx_hash,
        block_number=1_000,
        timestamp_utc=_TIMESTAMP,
        chain="Berachain",
        wallet_label=_WALLET_LABEL,
        wallet_address=_WALLET_ADDRESS,
        gas=gas,
        events=tuple(events),
    )


def _reward_tx(tx_hash: str, amount: Decimal) -> OnChainTransaction:
    """A single-Event Reward claim (no tx gas - no fee surface)."""
    event = Event(
        event_id=f"{tx_hash}#1",
        event_type=EventType.Reward,
        sub_type=SubType.staking,
        legs=(_in_leg(asset="BGT", amount=amount, token_address=_BGT_TOKEN),),
        parent_tx_hash=tx_hash,
    )
    return _tx(tx_hash, [event])


def _gasburn_tx(tx_hash: str, gas_amount: Decimal) -> OnChainTransaction:
    """A gas-only tx: one zero-value native out-leg, gas at the tx level."""
    event = Event(
        event_id=f"{tx_hash}#1",
        event_type=EventType.GasBurn,
        sub_type=SubType.cost_gas,
        legs=(_out_leg(asset="BERA", amount=Decimal("0"), token_address=None),),
        parent_tx_hash=tx_hash,
    )
    return _tx(
        tx_hash,
        [event],
        gas=Gas(asset="BERA", amount_raw=_to_raw(gas_amount), decimals=_DECIMALS),
    )


def _koinly_row(  # noqa: PLR0913
    *,
    tx_hash: str,
    type_: str,
    tag: str = "",
    sent: str = "",
    sent_cur: str = "",
    recv: str = "",
    recv_cur: str = "",
) -> dict[str, str]:
    """One raw Koinly TH row dict in the exact ``read_koinly_rows`` shape."""
    return {
        "Date": "2025-03-01 12:00:00 UTC",
        "Type": type_,
        "Tag": tag,
        "Sending Wallet": _WALLET_LABEL,
        "Sent Amount": sent,
        "Sent Currency": sent_cur,
        "Receiving Wallet": _WALLET_LABEL,
        "Received Amount": recv,
        "Received Currency": recv_cur,
        "Fee Amount": "",
        "Fee Currency": "",
        "TxSrc": _COUNTERPARTY,
        "TxDest": _WALLET_ADDRESS,
        "TxHash": tx_hash,
    }


def _registry() -> ContractRegistry:
    """An empty in-memory registry (every counterparty unregistered)."""
    return ContractRegistry(chain="Berachain", contracts={}, source="<inline-test>")


def _snapshot() -> LpSnapshot:
    """An empty in-memory LP snapshot (no LP tokens)."""
    return LpSnapshot(
        subgraph=None,
        subgraph_version="test",
        snapshot_as_of_block=_SNAPSHOT_AS_OF_BLOCK,
        snapshot_as_of_date="2025-12-31",
        tokens={},
        source="<inline-test>",
    )


def _run_header(
    *,
    rpc_enabled: bool = False,
    date_from: date | None = date(2025, 1, 1),
    date_to: date | None = date(2025, 6, 30),
) -> ValidationRunHeader:
    """The run header used across the artifact tests (RPC/window overridable)."""
    return ValidationRunHeader(
        year=_YEAR,
        on_chain_csv=_ON_CHAIN_CSV,
        koinly_source=_KOINLY_SOURCE,
        snapshot_as_of_block=_SNAPSHOT_AS_OF_BLOCK,
        rpc_enabled=rpc_enabled,
        wallet_labels=(_WALLET_LABEL,),
        date_from=date_from,
        date_to=date_to,
    )


def _finished_comparison() -> tuple[ComparisonResult, dict[str, list[ThComparisonRecord]]]:
    """A finished comparison: 7 same-shape divergent claims (one cluster,
    forcing the sample cap), 1 matched claim, 1 on-chain-only gas burn, and
    1 Koinly-only NFT mint (3 clusters total)."""
    divergent_txs = [_reward_tx(tx_hash, Decimal("1.5")) for tx_hash in _DIVERGENT_HASHES]
    projected = project_on_chain_transactions(
        [
            *divergent_txs,
            _reward_tx(_MATCHED_HASH, Decimal("1.5")),
            _gasburn_tx(_GAS_ONLY_HASH, Decimal("0.0001")),
        ]
    )
    koinly_rows = [
        *(
            _koinly_row(tx_hash=tx_hash, type_="crypto_deposit", tag="Reward", recv="1.4", recv_cur="BGT")
            for tx_hash in _DIVERGENT_HASHES
        ),
        _koinly_row(tx_hash=_MATCHED_HASH, type_="crypto_deposit", tag="Reward", recv="1.5", recv_cur="BGT"),
        _koinly_row(tx_hash=_NFT_HASH, type_="crypto_deposit", tag="NFT", recv="1", recv_cur="NFT"),
    ]
    result = compare_projection(koinly_rows, projected)
    clusters = group_into_clusters(result, registry=_registry(), lp_snapshot=_snapshot())
    return result, clusters


def _read_csv_rows(path: Path) -> list[list[str]]:
    """Read the diff CSV via ``csv.reader`` (never DictReader - UL #45)."""
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.reader(handle))


@pytest.mark.unit
class TestOnChainValidationArtifacts:
    """Artifact-writer pins for the on-chain TH validation harness."""

    def test_markdown_report_structure(self, tmp_path: Path) -> None:
        # Given - a finished comparison (7 divergent claims in one cluster,
        # 1 matched, 1 on-chain-only gas burn, 1 Koinly-only NFT mint) and a
        # disposition ruling the NFT cluster acceptable_difference.
        result, clusters = _finished_comparison()
        assert len(clusters) == 3
        nft_signature = next(
            signature for signature, records in clusters.items() if records[0].presence is Presence.KOINLY_ONLY
        )
        entries = [
            DispositionEntry(
                signature=nft_signature,
                first_seen="2026-08-18",
                disposition="acceptable_difference",
                root_cause="NFT mints are outside the on-chain parser scope",
                action="Accepted per the 2026-08-18 backlog ruling",
            )
        ]

        markdown_path, _ = write_validation_artifacts(
            output_dir=tmp_path,
            run=_run_header(),
            result=result,
            clusters=clusters,
            dispositions=entries,
        )
        text = markdown_path.read_text(encoding="utf-8")

        # Then - the run header records every input passed by the runner.
        assert f"# On-chain TH validation - {_YEAR}" in text
        assert f"On-chain CSV: {_ON_CHAIN_CSV}" in text
        assert f"Koinly source: {_KOINLY_SOURCE}" in text
        assert f"LP snapshot as of block: {_SNAPSHOT_AS_OF_BLOCK}" in text
        assert "RPC enrichment: disabled" in text
        assert f"Wallets under validation: {_WALLET_LABEL}" in text
        assert "Validation window: 2025-01-01 to 2025-06-30 (inclusive)" in text

        # And - the summary carries the five counts + per-cluster status.
        assert "Shared transaction hashes: 8" in text
        assert "Matched (semantically equivalent): 1" in text
        assert "Divergent: 7" in text
        assert "On-chain only: 1" in text
        assert "Koinly only: 1" in text
        assert "Discrepancy clusters: 3 (1 dispositioned, 2 NEW)" in text

        # And - one section per cluster, headed by its signature, with the
        # dispositioned-vs-NEW status; sections come after the summary.
        assert text.count("## Cluster: ") == 3
        for signature in clusters:
            assert f"## Cluster: {signature}" in text
        assert "Disposition: acceptable_difference" in text
        assert "Disposition: NEW" in text
        assert text.index("## Summary") < text.index("## Cluster: ")

        # And - the reward cluster shows at most 5 side-by-side samples with
        # the amount diff; the remaining occurrences are counted, not listed.
        assert f"| `{_DIVERGENT_HASHES[0]}` | crypto_deposit/Reward | crypto_deposit/Reward" in text
        assert "BGT/in: on-chain 1.5 vs Koinly 1.4 (tolerance 0.00000001)" in text
        assert f"`{_DIVERGENT_HASHES[4]}`" in text
        assert f"`{_DIVERGENT_HASHES[5]}`" not in text
        assert f"`{_DIVERGENT_HASHES[6]}`" not in text
        assert "… and 2 more occurrence(s) not shown" in text

        # And - a full-year rerun (no --from/--to) renders the full-year
        # window, and the RPC-enabled flag renders as enabled.
        full_year_path, _ = write_validation_artifacts(
            output_dir=tmp_path,
            run=_run_header(rpc_enabled=True, date_from=None, date_to=None),
            result=result,
            clusters=clusters,
            dispositions=entries,
        )
        full_year_text = full_year_path.read_text(encoding="utf-8")
        assert "Validation window: full year" in full_year_text
        assert "RPC enrichment: enabled" in full_year_text

    def test_diff_csv_one_row_per_divergent_tx(self, tmp_path: Path) -> None:
        # Given - 3 divergent txs across 2 clusters: two same-shape reward
        # claims (amount mismatch) and one claim Koinly rendered as an
        # exchange row (type mismatch; different cluster signature).
        hashes = ("0x" + f"{51:064x}", "0x" + f"{52:064x}", "0x" + f"{53:064x}")
        projected = project_on_chain_transactions([_reward_tx(tx_hash, Decimal("1.5")) for tx_hash in hashes])
        koinly_rows = [
            _koinly_row(tx_hash=hashes[0], type_="crypto_deposit", tag="Reward", recv="1.4", recv_cur="BGT"),
            _koinly_row(tx_hash=hashes[1], type_="crypto_deposit", tag="Reward", recv="1.4", recv_cur="BGT"),
            _koinly_row(tx_hash=hashes[2], type_="exchange", sent="1", sent_cur="BERA", recv="1.5", recv_cur="BGT"),
        ]
        result = compare_projection(koinly_rows, projected)
        clusters = group_into_clusters(result, registry=_registry(), lp_snapshot=_snapshot())
        assert len(clusters) == 2
        assert sum(len(records) for records in clusters.values()) == 3

        _, csv_path = write_validation_artifacts(
            output_dir=tmp_path,
            run=_run_header(),
            result=result,
            clusters=clusters,
            dispositions=[],
        )

        # Then - a header row plus EXACTLY one row per divergent tx, keyed by
        # tx_hash, each carrying its cluster signature and a mismatch summary.
        rows = _read_csv_rows(csv_path)
        assert rows[0] == ["Tx Hash", "Cluster Signature", "Disposition", "Mismatch Summary"]
        assert len(rows) == 4
        by_hash = {row[0]: row for row in rows[1:]}
        assert set(by_hash) == set(hashes)
        expected_signature = {
            record.tx_hash: signature for signature, records in clusters.items() for record in records
        }
        for tx_hash in hashes:
            row = by_hash[tx_hash]
            assert row[1] == expected_signature[tx_hash]
            assert row[2] == "NEW"
            assert row[3]
        assert "BGT/in: on-chain 1.5 vs Koinly 1.4 (tolerance 0.00000001)" in by_hash[hashes[0]][3]
        assert "type:" in by_hash[hashes[2]][3]
        assert "exchange/" in by_hash[hashes[2]][3]

    def test_artifacts_regenerated_not_appended(self, tmp_path: Path) -> None:
        # Given - pre-existing (stale) artifact files under the year dir, and
        # a small comparison rerun TWICE through the writers.
        year_dir = tmp_path / str(_YEAR)
        year_dir.mkdir(parents=True)
        stale_markdown = year_dir / MARKDOWN_REPORT_FILENAME
        stale_csv = year_dir / DIFF_CSV_FILENAME
        stale_markdown.write_text("STALE MARKER\n# On-chain TH validation - 2024\n", encoding="utf-8")
        stale_csv.write_text("STALE,COLUMNS\n", encoding="utf-8")

        projected = project_on_chain_transactions([_reward_tx(_DIVERGENT_HASHES[0], Decimal("1.5"))])
        koinly_rows = [
            _koinly_row(tx_hash=_DIVERGENT_HASHES[0], type_="crypto_deposit", tag="Reward", recv="1.4", recv_cur="BGT"),
            _koinly_row(tx_hash=_NFT_HASH, type_="crypto_deposit", tag="NFT", recv="1", recv_cur="NFT"),
        ]
        result = compare_projection(koinly_rows, projected)
        clusters = group_into_clusters(result, registry=_registry(), lp_snapshot=_snapshot())
        assert len(clusters) == 2

        for _ in range(2):
            markdown_path, csv_path = write_validation_artifacts(
                output_dir=tmp_path,
                run=_run_header(),
                result=result,
                clusters=clusters,
                dispositions=[],
            )

        # Then - both artifacts are REPLACED, never appended: the stale
        # content is gone and no section/row from the first run duplicates.
        markdown_text = markdown_path.read_text(encoding="utf-8")
        assert "STALE" not in markdown_text
        assert markdown_text.count(f"# On-chain TH validation - {_YEAR}") == 1
        assert markdown_text.count("## Cluster: ") == 2
        csv_text = csv_path.read_text(encoding="utf-8")
        assert "STALE" not in csv_text
        assert len(_read_csv_rows(csv_path)) == 3  # header + 2 records, not 5

    def test_diff_csv_neutralizes_formula_shaped_cells(self, tmp_path: Path) -> None:
        # Given - a corrupted/adversarial Koinly export whose Received
        # Currency cell is formula-shaped: the external value reaches the
        # amount-mismatch bucket ASSET key, and the sorted bucket order puts
        # it FIRST, so the raw Mismatch Summary would START with "=" and
        # execute when the personal diff CSV is opened in a spreadsheet
        # (review r1 F22).
        evil_currency = '=HYPERLINK("http://x","evil")'
        hashes = ("0x" + f"{61:064x}", "0x" + f"{62:064x}")
        projected = project_on_chain_transactions([_reward_tx(tx_hash, Decimal("1.5")) for tx_hash in hashes])
        koinly_rows = [
            _koinly_row(tx_hash=hashes[0], type_="crypto_deposit", tag="Reward", recv="1.4", recv_cur=evil_currency),
            _koinly_row(tx_hash=hashes[1], type_="crypto_deposit", tag="Reward", recv="1.4", recv_cur="BGT"),
        ]
        result = compare_projection(koinly_rows, projected)
        clusters = group_into_clusters(result, registry=_registry(), lp_snapshot=_snapshot())

        _, csv_path = write_validation_artifacts(
            output_dir=tmp_path,
            run=_run_header(),
            result=result,
            clusters=clusters,
            dispositions=[],
        )

        # Then - the formula-shaped Mismatch Summary is NEUTRALIZED by a
        # leading single quote (standard spreadsheet escape), keeping the
        # value visible while preventing execution; non-trigger cells (the
        # 0x hashes, the events=... signatures) pass through verbatim. The
        # asset key is case-folded (_norm_asset), so the rendered value is
        # the UPPERCASED form; the '=' first character survives the fold.
        rows = _read_csv_rows(csv_path)
        by_hash = {row[0]: row for row in rows[1:]}
        assert by_hash[hashes[0]][3].startswith(f"'{evil_currency.upper()}"), (
            "a formula-shaped mismatch summary must be quote-prefixed, never verbatim"
        )
        assert not by_hash[hashes[1]][3].startswith("'"), "ordinary summaries pass through unchanged"
        assert by_hash[hashes[0]][0] == hashes[0], "the 0x hash never gains a prefix"

    def test_real_hashes_allowed_only_under_result_dir(self, tmp_path: Path) -> None:
        # Given - records carrying real-shaped tx hashes, written into a tmp
        # stand-in for the gitignored production result dir.
        result, clusters = _finished_comparison()

        markdown_path, csv_path = write_validation_artifacts(
            output_dir=tmp_path,
            run=_run_header(),
            result=result,
            clusters=clusters,
            dispositions=[],
        )

        # Then - the artifacts land under <output_dir>/<year>/ and DO contain
        # the real hashes (PII rule enforced by location, not by omission).
        assert markdown_path == tmp_path / str(_YEAR) / MARKDOWN_REPORT_FILENAME
        assert csv_path == tmp_path / str(_YEAR) / DIFF_CSV_FILENAME
        assert _DIVERGENT_HASHES[0] in markdown_path.read_text(encoding="utf-8")
        assert _DIVERGENT_HASHES[0] in csv_path.read_text(encoding="utf-8")
