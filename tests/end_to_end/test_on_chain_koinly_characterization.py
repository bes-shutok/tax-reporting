"""Characterization (golden/master) tests pinning the KOINLY-PATH consumer output.

These tests are the regression catch for the On-Chain Transaction Tagger plan
(``docs/history/plans/2026-08-02-on-chain-tx-tagger.md`` Task 1). They pin FOUR
consumer surfaces on the committed synthetic example data and MUST stay GREEN
after every amendment in that plan (Tasks 2-5 migrate ``event_id`` /
``tx_key`` / ``token_origin`` / ``fee_filter``; the Koinly path must remain
byte-identical throughout).

Per AGENTS.md crypto-tests rule, these read ONLY committed synthetic data under
``resources/source/example/2025/koinly/[<scenario>/]``; they NEVER reference the
gitignored personal data at ``resources/source/2025/koinly/``.

The ``on_chain_th_wallets`` flag does not exist yet (added in Task 11); today's
code path IS the all-Koinly path, so "unset" simply means the production call
sites below are exercised exactly as they run today.

Baselines were captured at task-start (Pass 1) by running the production entry
points on the synthetic example fixtures and recording the deterministic,
serializable observables below as inline literals. Each test compares the live
production output to its pinned literal byte-for-byte; any drift in a migrated
consumer fails loudly here.

Surfaces pinned:
- FIFO / capital gains (rebuild path on ``loan_affected_rebuild``):
  per-asset lot count + totals + the carry-over cost-basis outcome (the WBTC
  loan-repayment disposal is rebuilt-out per DP-001; only the ETH spot
  disposal survives).
- Reward income aggregation (``dust-partition``): the per-(income_code,
  source_country) aggregation of taxable-now rewards.
- Loan activity classification (``loan_affected_rebuild``): per-asset loan
  balance status.
- Fee filter (base ``2025/koinly``): the removed-fee set and the suspect set
  emitted by the production fee-filter scan.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tax_reporting.application.crypto.aggregation import aggregate_taxable_rewards
from tax_reporting.application.crypto.fee_filter import _identify_fee_and_suspect_events
from tax_reporting.application.crypto.loan_activity import _extract_loan_activity
from tax_reporting.application.crypto_reporting import load_koinly_crypto_report
from tests.conftest import build_koinly_jurisdiction

# Committed synthetic Koinly 2025 example fixture directories (AGENTS.md
# crypto-tests rule; never the gitignored ``resources/source/2025/koinly/``).
_KOINLY_2025_BASE = Path("resources", "source", "example", "2025", "koinly")
_KOINLY_2025_DUST_PARTITION = _KOINLY_2025_BASE / "dust-partition"
_KOINLY_2025_LOAN_REBUILD = _KOINLY_2025_BASE / "loan_affected_rebuild"
_KOINLY_2025_BASE_TH = _KOINLY_2025_BASE / "koinly_2025_transaction_history.csv"


class TestOnChainKoinlyCharacterization:
    """Pin the four Koinly-path consumer surfaces on synthetic example data.

    Each test exercises the PRODUCTION call site (not an adjacent derived
    value) and asserts byte-identical output against a task-start baseline.
    """

    # ------------------------------------------------------------------
    # 1. FIFO / capital gains
    # ------------------------------------------------------------------
    #: Pinned baseline for the FIFO-rebuilt capital-gains output on the
    #: ``loan_affected_rebuild`` scenario (``exclude_loan_repayment_gains=True``
    #: activates the FIFO rebuild for loan-affected assets). The WBTC
    #: loan-repayment disposal is rebuilt-out per DP-001 (CIRS art. 10(20)):
    #: it must NOT appear in ``capital_entries``. Only the ETH spot disposal
    #: survives. Each tuple is ``(asset, disposal_date, platform, holding_period,
    #: cost_eur, proceeds_eur, gain_loss_eur)``; costs/proceeds/gain are pinned
    #: as strings to avoid float/Decimal formatting drift (the carry-over cost
    #: basis observable is the rebuilt ETH lot's cost basis = 100.00 EUR).
    _PINNED_FIFO_CAPITAL_ENTRIES: tuple[tuple[str, str, str, str, str, str, str], ...] = (
        ("ETH", "2025-06-15", "ByBit", "Short term", "100.00", "150.00", "50.00"),
    )
    #: The set of loan-affected assets the FIFO rebuild ran for (the
    #: borrowing-side WBTC principal). Pinning this guards the B2 ``tx_key``
    #: migration from silently widening or narrowing the rebuild scope.
    _PINNED_FIFO_REBUILD_ASSETS: frozenset[str] = frozenset({"WBTC"})

    @pytest.mark.e2e
    def test_fifo_output_byte_identical(self) -> None:
        """FIFO/capital-gains output (lot count, per-asset totals, carry-over
        cost basis) is byte-identical to the task-start baseline on the
        ``loan_affected_rebuild`` synthetic Koinly scenario.

        Production call site: ``load_koinly_crypto_report`` with
        ``exclude_loan_repayment_gains=True`` exercises the FIFO rebuild path
        (``crypto_fifo`` parsing/matching/merge + ``fifo_helpers``) end-to-end,
        which is the surface the Task 3 ``tx_key -> (tx_hash, event_id)``
        migration touches. Koinly rows have ``event_id=None`` so the rebuilt
        output must remain unchanged.
        """
        jurisdiction = build_koinly_jurisdiction(exclude_loan_repayment_gains=True)
        crypto = load_koinly_crypto_report(_KOINLY_2025_LOAN_REBUILD, jurisdiction=jurisdiction)
        assert crypto is not None, "loan_affected_rebuild fixture must load"

        # Lot count per the pinned baseline (1 lot: the ETH spot disposal;
        # the WBTC loan-repayment disposal is rebuilt-out).
        assert len(crypto.capital_entries) == len(self._PINNED_FIFO_CAPITAL_ENTRIES), (
            f"FIFO lot count drifted: expected {len(self._PINNED_FIFO_CAPITAL_ENTRIES)}, "
            f"got {len(crypto.capital_entries)}"
        )

        live_lots = sorted(
            (
                e.asset,
                e.disposal_date,
                e.platform,
                e.holding_period,
                str(e.cost_eur),
                str(e.proceeds_eur),
                str(e.gain_loss_eur),
            )
            for e in crypto.capital_entries
        )
        assert live_lots == sorted(self._PINNED_FIFO_CAPITAL_ENTRIES), (
            f"FIFO capital-entries output drifted from baseline.\n"
            f"  expected: {sorted(self._PINNED_FIFO_CAPITAL_ENTRIES)}\n"
            f"  got:      {live_lots}"
        )

        # Carry-over cost-basis observable: the surviving ETH lot's cost basis
        # is the rebuilt acquisition cost (100.00 EUR). Pinning it guards the
        # cross-asset / matching carry-over dicts the Task 3 migration re-types.
        eth_lot = crypto.capital_entries[0]
        assert eth_lot.asset == "ETH"
        assert str(eth_lot.cost_eur) == "100.00", (
            f"Carry-over cost basis for the rebuilt ETH lot drifted: "
            f"expected 100.00, got {eth_lot.cost_eur}"
        )

        # Rebuild scope (loan-affected asset set) must not change.
        assert crypto.fifo_rebuild_assets == self._PINNED_FIFO_REBUILD_ASSETS, (
            f"FIFO rebuild asset set drifted: expected {sorted(self._PINNED_FIFO_REBUILD_ASSETS)}, "
            f"got {sorted(crypto.fifo_rebuild_assets)}"
        )

    # ------------------------------------------------------------------
    # 2. Reward income aggregation
    # ------------------------------------------------------------------
    #: Pinned baseline for reward-income aggregation on the ``dust-partition``
    #: scenario. Aggregated by ``(income_code, source_country)`` via the
    #: production ``aggregate_taxable_rewards`` (only taxable-now rewards).
    #: The 2 EUR + 1 USD Wirex interest rewards (country=GB) collapse to one
    #: E25/GB group (the EUR-denominated interest family under PT). The SOL
    #: staking reward (country=HR) is deferred_by_law and excluded.
    #: Each tuple is ``(income_code, source_country, gross_income_eur,
    #: foreign_tax_eur, raw_row_count)`` (Decimal values pinned as strings).
    _PINNED_REWARD_GROUPS: tuple[tuple[str, str, str, str, int], ...] = (
        ("E25", "GB", "3.00", "0", 3),
    )

    @pytest.mark.e2e
    def test_reward_output_byte_identical(self) -> None:
        """Reward-income aggregation (per asset, per income_code, per
        source_country) is byte-identical to the task-start baseline on the
        ``dust-partition`` synthetic Koinly scenario.

        The base ``2025/koinly`` scenario has only a single deferred USDT
        reward (country=UNKNOWN) which yields zero taxable-now groups, so it
        does not exercise the aggregation meaningfully. ``dust-partition``
        ships multiple fiat-denominated taxable-now interest rewards plus a
        deferred staking reward, exercising the per-(income_code,
        source_country) collapse that the consumer migrations must not shift.

        Production call site: ``load_koinly_crypto_report`` (parses the income
        report) followed by ``aggregate_taxable_rewards`` (the production
        aggregation step the IRS-ready filing table reads).
        """
        jurisdiction = build_koinly_jurisdiction(exclude_loan_repayment_gains=False)
        crypto = load_koinly_crypto_report(_KOINLY_2025_DUST_PARTITION, jurisdiction=jurisdiction)
        assert crypto is not None, "dust-partition fixture must load"

        aggregated = aggregate_taxable_rewards(
            crypto.reward_entries, jurisdiction.classify_rewards_with_income_codes
        )

        live_groups = sorted(
            (
                a.income_code,
                a.source_country,
                str(a.gross_income_eur),
                str(a.foreign_tax_eur),
                a.raw_row_count,
            )
            for a in aggregated
        )
        assert live_groups == sorted(self._PINNED_REWARD_GROUPS), (
            f"Reward aggregation drifted from baseline.\n"
            f"  expected: {sorted(self._PINNED_REWARD_GROUPS)}\n"
            f"  got:      {live_groups}"
        )

    # ------------------------------------------------------------------
    # 3. Loan activity classification
    # ------------------------------------------------------------------
    #: Pinned baseline for per-asset loan-activity classification on the
    #: ``loan_affected_rebuild`` scenario (the only 2025 example exercising
    #: loan activity). The base ``2025/koinly`` scenario has no loan rows.
    #: Each tuple is ``(asset, balance_status, received_count,
    #: received_amount, repaid_count, repaid_amount)`` with Decimal amounts
    #: pinned as strings. WBTC: 0.1 borrowed and 0.1 repaid => Settled.
    _PINNED_LOAN_ACTIVITY: tuple[tuple[str, str, int, str, int, str], ...] = (
        ("WBTC", "Settled", 1, "0.10000000", 1, "0.10000000"),
    )

    @pytest.mark.e2e
    def test_loan_activity_output_byte_identical(self) -> None:
        """Loan-activity classification (status per asset) is byte-identical to
        the task-start baseline on the ``loan_affected_rebuild`` synthetic
        Koinly scenario.

        The base ``2025/koinly`` TH carries no ``Loan``/``Loan repayment`` rows,
        so it yields an empty loan-activity list. The ``loan_affected_rebuild``
        scenario is the committed fixture that exercises this surface: one
        WBTC borrow + one WBTC repayment => status ``Settled``.

        Production call site: ``_extract_loan_activity`` is the production loan
        extractor invoked by ``load_koinly_crypto_report`` (and directly here).
        """
        loan_activity = _extract_loan_activity(
            _KOINLY_2025_LOAN_REBUILD / "koinly_2025_transaction_history.csv"
        )

        # Sanity: the base scenario has no loan activity (documents the gap;
        # the loan_affected_rebuild scenario is the sanctioned fixture for it).
        assert _extract_loan_activity(_KOINLY_2025_BASE_TH) == [], (
            "Base 2025 scenario must have no loan activity; if this changed, "
            "the loan-activity baseline scope must be re-evaluated."
        )

        live_activity = sorted(
            (
                la.asset,
                la.balance_status,
                la.received_count,
                str(la.received_amount),
                la.repaid_count,
                str(la.repaid_amount),
            )
            for la in loan_activity
        )
        assert live_activity == sorted(self._PINNED_LOAN_ACTIVITY), (
            f"Loan-activity classification drifted from baseline.\n"
            f"  expected: {sorted(self._PINNED_LOAN_ACTIVITY)}\n"
            f"  got:      {live_activity}"
        )

    # ------------------------------------------------------------------
    # 4. Fee filter behavior
    # ------------------------------------------------------------------
    #: Pinned baseline for the fee-filter scan on the base ``2025/koinly`` TH.
    #: Removed-fee set: empty (no ``Cost``/``Loan fee`` tagged withdrawals, and
    #: no untagged-whitelisted withdrawals under the default per-asset ceiling
    #: map). Suspect set: 12 EUR ``Demo Spot`` rows (all with empty ``TxHash``,
    #: amount 0.00, net_value 0) - surfaced for review, NOT removed.
    #: Each suspect tuple is ``(timestamp, asset, wallet, amount, tx_hash,
    #: net_value_eur)`` (Decimal values pinned as strings). The 12-tuple list
    #: is sorted for deterministic comparison (order is not load-bearing here;
    #: the SET membership is).
    _PINNED_FEE_REMOVED_COUNT: int = 0
    _PINNED_FEE_SUSPECTS: tuple[tuple[str, str, str, str, str, str], ...] = (
        ("2025-01-01 09:00", "EUR", "Demo Spot", "0.00", "", "0"),
        ("2025-01-01 09:00", "EUR", "Demo Spot", "0.00", "", "0"),
        ("2025-01-02 09:00", "EUR", "Demo Spot", "0.00", "", "0"),
        ("2025-01-03 09:00", "EUR", "Demo Spot", "0.00", "", "0"),
        ("2025-01-05 09:00", "EUR", "Demo Spot", "0.00", "", "0"),
        ("2025-01-20 09:00", "EUR", "Demo Spot", "0.00", "", "0"),
        ("2025-01-22 09:00", "EUR", "Demo Spot", "0.00", "", "0"),
        ("2025-01-23 09:00", "EUR", "Demo Spot", "0.00", "", "0"),
        ("2025-02-15 10:00", "EUR", "Demo Spot", "0.00", "", "0"),
        ("2025-02-15 11:00", "EUR", "Demo Spot", "0.00", "", "0"),
        ("2025-03-10 12:00", "EUR", "Demo Spot", "0.00", "", "0"),
        ("2025-03-10 13:00", "EUR", "Demo Spot", "0.00", "", "0"),
    )

    @pytest.mark.e2e
    def test_fee_filter_behavior_byte_identical(self) -> None:
        """The fee-filter's removed-fee set and suspect set are byte-identical
        to the task-start baseline on the base ``2025/koinly`` synthetic TH.

        Production call site: ``_identify_fee_and_suspect_events`` is the
        production fee/suspect scan invoked by ``remove_transaction_fees``
        (``fee_filter.py:503``); it is the single source for BOTH the
        removed-fee set and the suspect set. Task 5 re-scopes its
        co-occurrence guard to ``event_id``; for Koinly rows (event_id None)
        the guard must reduce to today's ``count >= 2`` semantics and the
        removed-fee/suspect sets must stay byte-identical.
        """
        jurisdiction = build_koinly_jurisdiction(exclude_loan_repayment_gains=False)
        fee_events, suspect_events = _identify_fee_and_suspect_events(
            _KOINLY_2025_BASE_TH, jurisdiction
        )

        # Removed-fee set: empty on the base scenario.
        assert len(fee_events) == self._PINNED_FEE_REMOVED_COUNT, (
            f"Removed-fee set drifted: expected {self._PINNED_FEE_REMOVED_COUNT} fee events, "
            f"got {len(fee_events)}"
        )

        # Suspect set: 12 EUR Demo Spot rows; pin as a sorted tuple list
        # (set membership is load-bearing, not iteration order).
        live_suspects = sorted(
            (
                s.timestamp,
                s.asset,
                s.wallet,
                str(s.amount),
                s.tx_hash,
                str(s.net_value_eur),
            )
            for s in suspect_events
        )
        assert live_suspects == sorted(self._PINNED_FEE_SUSPECTS), (
            f"Fee-filter suspect set drifted from baseline.\n"
            f"  expected ({len(self._PINNED_FEE_SUSPECTS)}): {sorted(self._PINNED_FEE_SUSPECTS)}\n"
            f"  got      ({len(live_suspects)}): {live_suspects}"
        )
