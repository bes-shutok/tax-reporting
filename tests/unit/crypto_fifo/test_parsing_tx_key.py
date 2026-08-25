"""Tests for the ``crypto_fifo`` ``tx_key`` migration to ``(tx_hash, event_id)``.

Plan 2026-08-02 Task 3 (B2; folds review F1, F8). The FIFO dedup/correlation
system is the PARALLEL system to ``TxCorrelationKey`` (Task 2): both must key
on ``(tx_hash, event_id)`` for split Events so that two on-chain Events sharing
one ``tx_hash`` but differing in ``event_id`` are neither silently deduped
(W2 doubled-pool risk) nor cross-wired in the carry-over cost-basis join
(review F1: silent-zero-cost-basis corruption).

Koinly rows carry ``event_id=None`` (no ``event_id`` CSV column), so the Koinly
path stays byte-identical: ``tx_key`` remains the bare ``tx_hash`` string and
``_dedup_by_tx_key`` keeps collapsing duplicate-``TxHash`` rows exactly as today
(``test_koinly_rows_dedup_as_today`` pins this).

Construction change site: ``parsing.py`` ``_classify_rows_for_loan_affected_assets``
reads ``row["event_id"]``; when non-empty, ``tx_key`` becomes the tuple
``(tx_hash, event_id)`` (the on-chain adapter writes the column; Koinly CSVs do
not, so the value is empty/None on the Koinly path).
"""

from __future__ import annotations

import csv
from decimal import Decimal

from tax_reporting.application.crypto_fifo.matching import compute_fifo_for_asset
from tax_reporting.application.crypto_fifo.parsing import (
    _classify_rows_for_loan_affected_assets,
)
from tax_reporting.application.crypto_fifo.transfer import _resolve_intra_asset_transfers
from tax_reporting.domain.crypto_fifo import (
    CryptoAcquisition,
    CryptoConsumption,
)

# Koinly TH header shape (matches ``test_crypto_fifo.py``). The on-chain adapter
# (Task 10) appends an ``event_id`` column when it serializes its rows to a
# TH-shaped CSV; Koinly CSVs do NOT carry that column, so ``row.get("event_id")``
# returns "" -> treated as None on the Koinly path.
TH_HEADER = (
    "Date,Type,Tag,Sending Wallet,Sent Amount,Sent Currency,Sent Cost Basis,"
    "Receiving Wallet,Received Amount,Received Currency,Received Cost Basis,"
    "Fee Amount,Fee Currency,Gain (EUR),Net Value (EUR),Fee Value (EUR),"
    "TxSrc,TxDest,TxHash,event_id,Description"
)

_LOAN_AFFECTED = frozenset({"WBTC", "SUI", "LBTC"})


def _rows_from_csv(text_rows: list[str]) -> list[dict[str, str]]:
    """Parse TH rows into ``dict[str,str]`` exactly as ``read_koinly_rows`` does.

    Mirrors ``test_crypto_fifo._parse_row`` but returns a list so it can feed
    ``_classify_rows_for_loan_affected_assets`` directly.
    """
    reader = csv.DictReader([TH_HEADER, *text_rows])
    return [{k: (v or "") for k, v in row.items() if k is not None} for row in reader]


class TestParsingTxKey:
    """Plan 2026-08-02 Task 3: ``tx_key`` construction + dedup + carry-over join."""

    # ------------------------------------------------------------------
    # Sub-task 3b test 1 (could equally be 3a; pinned here per plan):
    # Koinly rows (event_id None) dedup exactly as today.
    # ------------------------------------------------------------------
    def test_koinly_rows_dedup_as_today(self) -> None:
        """Two Koinly TH acquisition rows sharing ``tx_hash`` (no ``event_id``
        column -> ``event_id`` None) are deduped by ``_dedup_by_tx_key``: the
        first is kept, the second dropped. Byte-identical to today's behavior
        (the safety net for the Task 3 migration on the Koinly path)."""
        # Two WBTC acquisitions on the same platform sharing one TxHash and the
        # same source_type (buy). No event_id column value -> Koinly path.
        # Two WBTC acquisitions sharing one TxHash, no event_id (Koinly path).
        # Columns: Date,Type,Tag,Sending Wallet,Sent Amount,Sent Currency,
        # Sent Cost Basis,Receiving Wallet,Received Amount,Received Currency,
        # Received Cost Basis,Fee Amount,Fee Currency,Gain,Net Value,Fee Value,
        # TxSrc,TxDest,TxHash,event_id,Description
        rows = _rows_from_csv(
            [
                "2025-01-10 10:00:00 UTC,exchange,,Kraken,1000,EUR,1000,"
                "Kraken,1.0,WBTC,1000,,,0,1000,,src,dst,tx_dup,,",
                "2025-01-10 10:05:00 UTC,exchange,,Kraken,1000,EUR,1000,"
                "Kraken,1.0,WBTC,1000,,,0,1000,,src,dst,tx_dup,,",
            ]
        )
        acqs, cons, _phantom, _failures = _classify_rows_for_loan_affected_assets(
            rows, loan_affected_assets=_LOAN_AFFECTED
        )

        wbtc_acqs = acqs.get("WBTC", [])
        assert len(wbtc_acqs) == 1, (
            f"Koinly duplicate-tx_hash acquisitions must dedup to 1; got {len(wbtc_acqs)}. "
            "The Koinly path (event_id None) must stay byte-identical to today."
        )
        # The kept acquisition's tx_key is the bare tx_hash string (not a tuple).
        assert wbtc_acqs[0].tx_key == "tx_dup", (
            f"Koinly tx_key must be the bare tx_hash string; got {wbtc_acqs[0].tx_key!r}"
        )

    # ------------------------------------------------------------------
    # Sub-task 3b test 2: on-chain split rows are NOT deduped.
    # ------------------------------------------------------------------
    def test_onchain_split_rows_not_deduped(self) -> None:
        """Two on-chain TH acquisition rows sharing ``tx_hash`` but with
        DIFFERENT ``event_id`` are BOTH kept by ``_dedup_by_tx_key``. This is
        the B2 fix: multi-token reward claims and multi-leg LP deposits
        (distinct Events within one tx) are no longer silently dropped."""
        rows = _rows_from_csv(
            [
                "2025-01-10 10:00:00 UTC,exchange,,Kraken,1000,EUR,1000,"
                "Kraken,1.0,WBTC,1000,,,0,1000,,src,dst,tx_split,evt_A,",
                "2025-01-10 10:05:00 UTC,exchange,,Kraken,1000,EUR,1000,"
                "Kraken,1.0,WBTC,1000,,,0,1000,,src,dst,tx_split,evt_B,",
            ]
        )
        acqs, _cons, _phantom, _failures = _classify_rows_for_loan_affected_assets(
            rows, loan_affected_assets=_LOAN_AFFECTED
        )

        wbtc_acqs = acqs.get("WBTC", [])
        assert len(wbtc_acqs) == 2, (
            f"On-chain split Events (same tx_hash, distinct event_id) must BOTH survive "
            f"dedup; got {len(wbtc_acqs)}. Without the (tx_hash, event_id) key these would "
            "be silently collapsed, doubling or halving the FIFO pool."
        )
        keys = sorted(repr(a.tx_key) for a in wbtc_acqs)
        assert keys == ["('tx_split', 'evt_A')", "('tx_split', 'evt_B')"], (
            f"On-chain tx_keys must be (tx_hash, event_id) tuples; got {keys}"
        )

    # ------------------------------------------------------------------
    # Sub-task 3b test 3: cross-asset carry-over join keys on event_id.
    # ------------------------------------------------------------------
    def test_cross_asset_carryover_uses_event_id(self) -> None:
        """A cross-asset swap tx with TWO Events (event_id A, B) sharing one
        ``tx_hash`` produces carry-over cost basis keyed by ``(tx_hash, event_id)``:
        each deferred acquisition resolves to its OWN sender's cost and the two
        Events do NOT merge. Exercises the tuple key through the carry-over dict
        join (``cross_asset._lookup_carryover_cost`` reads
        ``MergedAssetFifoResult.carryover_cost_by_tx_key`` whose outer key is
        ``(tx_key, platform)`` with ``tx_key`` itself the ``(tx_hash, event_id)``
        tuple)."""
        from tax_reporting.application.crypto_fifo.contexts import (
            AcquisitionContext,
            ConsumptionContext,
        )
        from tax_reporting.application.crypto_fifo.cross_asset import resolve_cross_asset_exchanges
        from tax_reporting.application.crypto_fifo.merge import MergedAssetFifoResult

        tx_hash = "tx_swap"
        # Two independent cross-asset swaps sharing the same on-chain tx_hash
        # but distinct event_ids (split Events). Each Event's sender (LBTC)
        # carries over its own cost to its own receiver.
        key_a: tuple[str, str] = (tx_hash, "evt_A")
        key_b: tuple[str, str] = (tx_hash, "evt_B")

        # Sender LBTC side: two non-taxable exchange_out consumptions, one per
        # Event, each producing its own carry-over cost entry.
        lbtc_acq = CryptoAcquisition(
            date="2025-01-01 12:00:00",
            asset="LBTC",
            amount=Decimal("2"),
            cost_basis_eur=Decimal("1000"),
            fee_eur=Decimal("0"),
            source_type="exchange_in",
            wallet="Kraken",
            platform="Kraken",
            review_required=False,
            review_reason=None,
        )
        lbtc_cons_a = CryptoConsumption(
            date="2025-06-01 12:00:00",
            asset="LBTC",
            amount=Decimal("1"),
            proceeds_eur=Decimal("0"),
            event_type="exchange_out",
            taxable=False,
            wallet="Kraken",
            platform="Kraken",
            notes="",
            review_required=False,
            review_reason=None,
        )
        lbtc_cons_b = CryptoConsumption(
            date="2025-06-01 12:00:00",
            asset="LBTC",
            amount=Decimal("1"),
            proceeds_eur=Decimal("0"),
            event_type="exchange_out",
            taxable=False,
            wallet="Kraken",
            platform="Kraken",
            notes="",
            review_required=False,
            review_reason=None,
        )
        lbtc_acqs_ctx = [AcquisitionContext(acq=lbtc_acq, tx_key="tx_lbtc_buy", source_row_index=1)]
        lbtc_cons_ctx = [
            ConsumptionContext(con=lbtc_cons_a, tx_key=key_a, source_row_index=10),
            ConsumptionContext(con=lbtc_cons_b, tx_key=key_b, source_row_index=11),
        ]
        lbtc_result = compute_fifo_for_asset(lbtc_acqs_ctx, lbtc_cons_ctx, asset="LBTC", platform="Kraken")
        lbtc_merged = MergedAssetFifoResult(
            carryover_cost_by_tx_key={(k, "Kraken"): v for k, v in lbtc_result.carryover_cost_by_tx_key.items()},
            partial_carryover_tx_keys=lbtc_result.partial_carryover_tx_keys,
        )

        # Two deferred receivers, one per Event, each keyed by its own tuple.
        wbtc_deferred_a = AcquisitionContext(
            acq=CryptoAcquisition(
                date="2025-06-01 12:00:00",
                asset="WBTC",
                amount=Decimal("1"),
                cost_basis_eur=Decimal("0"),
                fee_eur=Decimal("0"),
                source_type="exchange_in_deferred",
                wallet="Kraken",
                platform="Kraken",
                review_required=False,
                review_reason=None,
            ),
            tx_key=key_a,
            source_row_index=10,
        )
        wbtc_deferred_b = AcquisitionContext(
            acq=CryptoAcquisition(
                date="2025-06-01 12:00:00",
                asset="WBTC",
                amount=Decimal("1"),
                cost_basis_eur=Decimal("0"),
                fee_eur=Decimal("0"),
                source_type="exchange_in_deferred",
                wallet="Kraken",
                platform="Kraken",
                review_required=False,
                review_reason=None,
            ),
            tx_key=key_b,
            source_row_index=11,
        )

        # tx_key_to_sender: each consumption tx_key -> [sender asset] (LBTC).
        # tx_key_to_asset_totals: each deferred tx_key -> {receiver asset -> amount}.
        # Both keyed by the SAME tuple tx_key so the join does not merge Events.
        tx_key_to_sender: dict[str | tuple[str, str], list[str]] = {
            key_a: ["LBTC"],
            key_b: ["LBTC"],
        }
        tx_key_to_asset_totals: dict[str | tuple[str, str], dict[str, Decimal]] = {
            key_a: {"WBTC": Decimal("1")},
            key_b: {"WBTC": Decimal("1")},
        }

        resolved = resolve_cross_asset_exchanges(
            {"WBTC": [wbtc_deferred_a, wbtc_deferred_b]},
            {"LBTC": lbtc_merged},
            tx_key_to_sender=tx_key_to_sender,
            tx_key_to_asset_totals=tx_key_to_asset_totals,
        )

        resolved_by_key = {a.tx_key: a for a in resolved["WBTC"]}
        assert set(resolved_by_key) == {key_a, key_b}, (
            f"Both split-Event deferred acquisitions must resolve; got {set(resolved_by_key)}"
        )
        # Each receiver got its OWN sender's cost (500 each, not 1000 merged).
        assert resolved_by_key[key_a].acq.cost_basis_eur == Decimal("500"), (
            f"Event A carry-over must be 500 (its own sender cost); "
            f"got {resolved_by_key[key_a].acq.cost_basis_eur}. If this is 1000, the two "
            "Events were merged by tx_hash alone (the F1 corruption)."
        )
        assert resolved_by_key[key_b].acq.cost_basis_eur == Decimal("500"), (
            f"Event B carry-over must be 500 (its own sender cost); "
            f"got {resolved_by_key[key_b].acq.cost_basis_eur}. If this is 0, the tuple key "
            "did not join through the carry-over dict (the F1 silent-zero case)."
        )

    # ------------------------------------------------------------------
    # Sub-task 3b test 4 (review F1): on-chain deferred transfer resolves to
    # NON-zero cost via the (tx_hash, event_id) tuple key through the dict join.
    # ------------------------------------------------------------------
    def test_onchain_deferred_transfer_resolves_nonzero_cost(self) -> None:
        """An on-chain ``transfer_in_deferred`` acquisition and a ``transfer_out``
        consumption sharing a ``(tx_hash, event_id)`` tuple key resolve the
        carry-over cost to NON-zero through the dict join in
        ``_resolve_intra_asset_transfers`` (``transfer.py:96-97``).

        This is the review F1 silent-zero-cost-basis corruption case for
        ``matching.py:74`` (carry-over accumulator) and ``transfer.py:30``
        (``tx_key_to_sender``): pre-migration the tuple key would not match the
        ``transfer_out``'s carry-over entry and the receiver cost basis would
        silently resolve to 0. The test exercises the tuple key through the
        PRODUCTION dict join (``acq.tx_key in carryover_dict``), not just the type."""
        from tax_reporting.application.crypto_fifo.contexts import (
            AcquisitionContext,
            ConsumptionContext,
        )

        tx_key: tuple[str, str] = ("tx_transfer", "evt_x")

        # Sender platform has a non-taxable transfer_out consumption that
        # produces a carry-over cost entry keyed by the SAME tuple tx_key.
        sender_acq = AcquisitionContext(
            acq=CryptoAcquisition(
                date="2025-01-01 12:00:00",
                asset="WBTC",
                amount=Decimal("1"),
                cost_basis_eur=Decimal("100"),
                fee_eur=Decimal("0"),
                source_type="exchange_in",
                wallet="ByBit",
                platform="ByBit",
                review_required=False,
                review_reason=None,
            ),
            tx_key="tx_buy_bybit",
            source_row_index=1,
        )
        transfer_out = ConsumptionContext(
            con=CryptoConsumption(
                date="2025-06-01 12:00:00",
                asset="WBTC",
                amount=Decimal("1"),
                proceeds_eur=Decimal("0"),
                event_type="transfer_out",
                taxable=False,
                wallet="ByBit",
                platform="ByBit",
                notes="",
                review_required=False,
                review_reason=None,
            ),
            tx_key=tx_key,
            source_row_index=10,
        )
        sender_result = compute_fifo_for_asset(
            [sender_acq], [transfer_out], asset="WBTC", platform="ByBit"
        )
        # The carry-over dict is keyed by the tuple tx_key (production path).
        per_platform_carryover = {"ByBit": dict(sender_result.carryover_cost_by_tx_key)}
        assert tx_key in per_platform_carryover["ByBit"], (
            "transfer_out must produce a carry-over entry keyed by the tuple tx_key; "
            "without it the receiver cost basis silently resolves to 0 (F1)."
        )
        assert per_platform_carryover["ByBit"][tx_key] == Decimal("100"), (
            f"Carry-over cost must be 100; got {per_platform_carryover['ByBit'][tx_key]}"
        )

        # Receiver platform: a transfer_in_deferred acquisition carrying the
        # SAME tuple tx_key. ``_resolve_intra_asset_transfers`` joins via
        # ``acq.tx_key in carryover_dict`` (transfer.py:96).
        deferred = AcquisitionContext(
            acq=CryptoAcquisition(
                date="2025-06-01 12:00:00",
                asset="WBTC",
                amount=Decimal("1"),
                cost_basis_eur=Decimal("0"),
                fee_eur=Decimal("0"),
                source_type="transfer_in_deferred",
                wallet="Kraken",
                platform="Kraken",
                review_required=False,
                review_reason=None,
            ),
            tx_key=tx_key,
            source_row_index=10,
        )
        resolved = _resolve_intra_asset_transfers([deferred], per_platform_carryover)
        assert len(resolved) == 1
        receiver = resolved[0]
        assert receiver.acq.cost_basis_eur == Decimal("100"), (
            f"On-chain deferred transfer must resolve to NON-zero cost (100) via the "
            f"(tx_hash, event_id) tuple key; got {receiver.acq.cost_basis_eur}. "
            "A zero here is the F1 silent-zero-cost-basis corruption."
        )
        assert receiver.acq.source_type == "transfer_in_resolved"
        assert receiver.acq.review_required is False, (
            "A fully-resolved transfer must not be flagged for review."
        )

    # ------------------------------------------------------------------
    # Plan 2026-08-24 Task 2: the multi-leg per-row event ids (".{k}"
    # suffixes from the on-chain adapter's per-leg-pair projection) must
    # BOTH survive `_dedup_by_tx_key`; a GENUINE duplicate (same
    # (tx_hash, event_id) twice) must still drop the second with a review
    # entry. This PINS the dedup consumer against the adapter's per-row
    # event-id design (parsing.py is not modified by the plan).
    # ------------------------------------------------------------------
    def test_dedup_keeps_same_event_leg_pair_rows(self) -> None:
        """Two TH consumption rows sharing tx_hash AND asset (the iBERA
        worked example: two iBERA out legs of one Swap, event_ids ``h#5`` and
        ``h#5.2``) are BOTH retained after ``_dedup_by_tx_key``; a genuine
        duplicate (same tx_hash AND same event_id twice) drops the second
        with a review entry (existing behavior pinned)."""
        from tax_reporting.application.crypto.entities import CryptoReviewEntry

        tx_hash = "0xdupleg000000000000000000000000000000000000000000000000000001"
        # Columns: Date,Type,Tag,Sending Wallet,Sent Amount,Sent Currency,
        # Sent Cost Basis,Receiving Wallet,Received Amount,Received Currency,
        # Received Cost Basis,Fee Amount,Fee Currency,Gain,Net Value,Fee Value,
        # TxSrc,TxDest,TxHash,event_id,Description
        leg_pair_rows = _rows_from_csv(
            [
                "2025-06-01 12:00:00 UTC,exchange,,Koinly Wallet,8.467888513983386625,IBERA,"
                "0,Koinly Wallet,9.96222178,BERA,0,,,0,9.96,,src,dst,"
                f"{tx_hash},{tx_hash}#5,",
                "2025-06-01 12:00:05 UTC,exchange,,Koinly Wallet,1.494333267173538816,IBERA,"
                "0,Koinly Wallet,0.1,BERA,0,,,0,0.1,,src,dst,"
                f"{tx_hash},{tx_hash}#5.2,",
            ]
        )
        review_entries: list[CryptoReviewEntry] = []
        _acqs, cons, _phantom, failures = _classify_rows_for_loan_affected_assets(
            leg_pair_rows,
            loan_affected_assets=frozenset({"IBERA"}),
            review_entries=review_entries,
        )

        ibera_cons = cons.get("IBERA", [])
        assert len(ibera_cons) == 2, (
            f"Same-event leg-pair rows (distinct event_id via the .{{k}} suffix) must "
            f"BOTH survive _dedup_by_tx_key; got {len(ibera_cons)}. Dropping one would "
            "silently lose that leg's disposal proceeds."
        )
        assert sorted(repr(c.tx_key) for c in ibera_cons) == sorted(
            repr(k) for k in [(tx_hash, f"{tx_hash}#5"), (tx_hash, f"{tx_hash}#5.2")]
        )
        # No rows dropped -> no review entries, no parse failures.
        assert review_entries == []
        assert failures == {}

        # Genuine duplicate: same tx_hash AND same event_id twice -> the
        # second consumption is dropped with a review entry (pin the existing
        # keep-first-per-key behavior).
        duplicate_rows = _rows_from_csv(
            [
                "2025-06-01 12:00:00 UTC,exchange,,Koinly Wallet,8.46,IBERA,"
                "0,Koinly Wallet,9.96,BERA,0,,,0,9.96,,src,dst,"
                f"{tx_hash},{tx_hash}#5,",
                "2025-06-01 12:00:05 UTC,exchange,,Koinly Wallet,8.46,IBERA,"
                "0,Koinly Wallet,9.96,BERA,0,,,0,9.96,,src,dst,"
                f"{tx_hash},{tx_hash}#5,",
            ]
        )
        dup_review: list[CryptoReviewEntry] = []
        _acqs2, cons2, _phantom2, failures2 = _classify_rows_for_loan_affected_assets(
            duplicate_rows,
            loan_affected_assets=frozenset({"IBERA"}),
            review_entries=dup_review,
        )
        dup_cons = cons2.get("IBERA", [])
        assert len(dup_cons) == 1, (
            f"A genuine duplicate (same tx_hash AND same event_id) must drop the "
            f"second consumption; got {len(dup_cons)}."
        )
        assert dup_cons[0].tx_key == (tx_hash, f"{tx_hash}#5")
        assert len(dup_review) == 1
        assert "Duplicate tx_key dropped" in dup_review[0].review_reason
        assert failures2 == {"IBERA": [2]}
