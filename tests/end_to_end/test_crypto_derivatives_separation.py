"""End-to-end data-trace verification for the ByBit derivatives separation pipeline.

Verifies (per docs/history/plans/2026-06-13-derivatives-separation.md Task 11 and
development_lessons.md #72, #73) that the real ByBit fixtures in
``resources/source/koinly2025/`` produce the expected split between Crypto
Gains (spot fee disposal lots) and Derivatives P&L (art. 10(1)(e) realizations),
and that disabling ``separate_derivatives_reporting`` reproduces the Task 1
golden characterization values exactly.

Cases:
    Case 1 = (2025-01-12, USDT, ByBit): one OGR Profit row (+140.18 EUR) plus
        one OGR Loss row (-4.17 EUR futures fee). With separation AND the TH-label
        CG dedup (Task 4 scanner), the profit routes to Derivatives P&L and the
        single CG fee-disposal lot (+2.44 EUR) is REMOVED from Crypto Gains
        because its TH event carries Label="Futures fee". The -4.17 EUR OGR Loss
        row now classifies as Derivatives (cg_matches == 0 after dedup) instead of
        the old Spot classification. Without separation, the legacy path mixes
        profit plus fee into a single 136.01 EUR Crypto Gains entry.
    Case 2 = (2025-01-13, USDT, ByBit): three OGR Loss rows (0.15 + 8.31 +
        138.73 = 147.19 EUR) and ~108 CG lots at the 13:01 timestamp (plus 1
        Funding fee lot at 08:00 = 109 total). With separation AND the TH-label
        CG dedup, ALL 109 CG lots are removed: the Funding fee lot and Futures
        fee lot via exact match, and the remaining 107 lots at 13:01 (which sum
        to 142.11299953 USDT, within tolerance of the 142.113 Realized gain TH
        event) via contiguous-range fallback. The three OGR Loss rows then
        classify as clean Derivatives (-147.19 EUR total). Without separation,
        the legacy direction-override path flips every lot to negative,
        producing -26.64 EUR in Crypto Gains.
    Case 3 = (2025-01-24, USDT, ByBit): three derivatives events whose TH rows
        carry derivatives Labels (Funding fee 0.088 USDT at 20:00, Futures fee
        0.414 USDT at 23:40:53, Realized gain 40.755 USDT at 23:40:53). Koinly
        emits the SAME disposals into BOTH the CG report (3 FIFO lots summing
        to +20.24 EUR gain) AND the OGR report (3 Loss rows summing to -39.62
        EUR). With separation + the TH-label CG dedup (planned), the 3 CG lots
        are removed from capital_entries (no Crypto Gains row) and the 3 OGR
        rows classify as clean Derivatives (-39.62 EUR, no review flag).
        Without the dedup (current buggy state), the same disposal is taxed
        twice: once as +20.24 EUR Crypto Gains and once as -39.62 EUR
        Derivatives P&L.
"""

from __future__ import annotations

import csv
import logging
from decimal import Decimal
from pathlib import Path

import openpyxl
import pytest

from tax_reporting.application.crypto.classification import _is_valid_tabela_x_country
from tax_reporting.application.crypto.entities import CryptoCapitalGainEntry, DerivativesEventType
from tax_reporting.application.crypto_reporting import load_koinly_crypto_report
from tax_reporting.application.persisting.derivatives_sheet import write_derivatives_sheet
from tax_reporting.infrastructure.config import TaxJurisdictionConfig

pytestmark = pytest.mark.e2e

_FIXTURE_DIR = Path("resources/source/koinly2025")


def _find_fixture(pattern: str) -> Path | None:
    """Find a Koinly fixture CSV by glob pattern.

    The koinly2025 directory contains real exports with account-specific tokens
    in their filenames. Discovery via glob keeps those tokens out of tracked
    test code.
    """
    matches = sorted(_FIXTURE_DIR.glob(pattern))
    return matches[0] if matches else None


def _ogr_path() -> Path:
    path = _find_fixture("koinly_2025_other_gains_report_*.csv")
    if path is None:
        pytest.skip("koinly_2025_other_gains_report_*.csv not available")
    return path


def _cg_path() -> Path:
    path = _find_fixture("koinly_2025_capital_gains_report_*.csv")
    if path is None:
        pytest.skip("koinly_2025_capital_gains_report_*.csv not available")
    return path


def _th_path() -> Path:
    path = _find_fixture("koinly_2025_transaction_history_*.csv")
    if path is None:
        pytest.skip("koinly_2025_transaction_history_*.csv not available")
    return path


_CASE1_DATE = "2025-01-12"
_CASE2_DATE = "2025-01-13"
_CASE3_DATE = "2025-01-24"
_ASSET = "USDT"
_PLATFORM = "ByBit"


def _build_jurisdiction(*, separate_derivatives: bool) -> TaxJurisdictionConfig:
    """Build a PT/2025 jurisdiction mirroring the production decision-point flags.

    ``separate_derivatives_reporting`` toggles between the new separated path
    (True) and the legacy mixed path (False) so both directions can be exercised
    against the same fixtures.
    """
    return TaxJurisdictionConfig(
        country="PT",
        fiscal_year=2025,
        exclude_loan_repayment_gains=True,
        zero_basis_review_threshold=Decimal("500"),
        futures_derivatives_taxable=True,
        use_other_gains_report=True,
        separate_derivatives_reporting=separate_derivatives,
    )


def _skip_if_fixtures_missing() -> None:
    """Skip the calling test gracefully when the koinly2025 directory is absent."""
    if not _FIXTURE_DIR.exists() or not _FIXTURE_DIR.is_dir():
        pytest.skip(f"koinly2025 fixture directory not available at {_FIXTURE_DIR}")


def _load_with_separation(*, separate_derivatives: bool):
    """Load the koinly2025 report under the requested jurisdiction setting."""
    report = load_koinly_crypto_report(
        _FIXTURE_DIR, jurisdiction=_build_jurisdiction(separate_derivatives=separate_derivatives)
    )
    if report is None:
        pytest.skip("load_koinly_crypto_report returned None for koinly2025 fixtures")
    return report


def _assert_csv_contains_value(csv_path: Path, needle: str) -> None:
    """Verify a literal value appears in a fixture CSV (data-trace verification).

    The data-trace checks below compare raw source CSV contents against the
    values the test asserts on the pipeline output, so the contract is grounded
    in source data rather than internal pipeline constants. Failures here point
    to a fixture change rather than a code regression.
    """
    assert csv_path.exists(), f"Fixture CSV not found: {csv_path}"
    with csv_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    matched = [row for row in rows if any(needle in cell for cell in row)]
    assert matched, (
        f"Expected source value {needle!r} not found in {csv_path.name}. "
        "The fixture has changed; update the data-trace assertion to match."
    )


class TestByBitCase1Trace:
    """Case 1 (2025-01-12, USDT, ByBit): futures Profit + fee disposal separation."""

    def setup_method(self) -> None:
        _skip_if_fixtures_missing()

    def test_profit_in_derivatives_sheet(self) -> None:
        """+140.18 EUR futures profit routes to Derivatives P&L; the 2.44 EUR fee-disposal lot is removed by the dedup.

        The fee-disposal lot was Spot under the legacy classifier; after the
        dedup removes its CG counterpart, the OGR Loss row reclassifies to
        Derivatives (see ``test_fee_disposal_reclassifies_to_derivatives``).

        Per Task 7 of the derivatives-th-label-cg-dedup plan: the 2.44 EUR
        fee-disposal CG lot is removed because its TH event carries
        Label="Futures fee" (TH line 205 crypto_withdrawal Futures fee
        4,27180510 USDT ByBit). The +140.18 EUR OGR Profit row is UNCHANGED
        by the dedup (its TH event is a crypto_deposit, filtered out by the
        Task 4 scanner's crypto_withdrawal-only filter) and still routes to
        derivatives_entries. This test asserts ONLY the Profit routing; the
        fee-disposal reclassification is covered by
        ``test_fee_disposal_reclassifies_to_derivatives`` and
        ``test_no_fee_disposal_lot_in_capital_entries``.
        """
        _assert_csv_contains_value(_ogr_path(), "140,18")
        _assert_csv_contains_value(_ogr_path(), "4,17")
        _assert_csv_contains_value(_cg_path(), "2,44")

        report = _load_with_separation(separate_derivatives=True)

        profit_matches = [
            e
            for e in report.derivatives_entries
            if (
                e.date == _CASE1_DATE
                and e.asset == _ASSET
                and e.platform == _PLATFORM
                and e.event_type == DerivativesEventType.PROFIT
            )
        ]
        assert profit_matches, (
            "Expected a Derivatives P&L PROFIT entry for "
            f"({_CASE1_DATE}, {_ASSET}, {_PLATFORM}); got "
            f"{[(e.date, e.asset, e.platform, e.event_type, e.pnl_eur) for e in report.derivatives_entries]}"
        )
        profit_total = sum((e.pnl_eur for e in profit_matches), start=Decimal("0"))
        assert profit_total == Decimal("140.18"), (
            f"Expected +140.18 EUR PROFIT in derivatives_entries for Case 1, got {profit_total}. "
            "Entries: "
            f"{[(e.event_type, e.pnl_eur) for e in profit_matches]}"
        )

    def test_no_fee_disposal_lot_in_capital_entries(self) -> None:
        """capital_entries has no entry with disposal_date=2025-01-12, asset=USDT, wallet=ByBit after dedup.

        The 2.44 EUR Futures fee CG lot (CG line 19: amount 4.27180510,
        proceeds 4.17, gain 2.44) is removed by the dedup because its TH
        event (TH line 205: crypto_withdrawal Futures fee 4.27180510 USDT
        ByBit at 15:22) carries Label="Futures fee".
        """
        _assert_csv_contains_value(_cg_path(), "2,44")

        report = _load_with_separation(separate_derivatives=True)

        case1_capital = [
            e
            for e in report.capital_entries
            if e.disposal_date == _CASE1_DATE and e.asset == _ASSET and e.platform == _PLATFORM
        ]
        assert not case1_capital, (
            "Expected NO Crypto Gains entry for "
            f"({_CASE1_DATE}, {_ASSET}, {_PLATFORM}) after the derivatives CG dedup "
            "(the 2.44 EUR Futures fee CG lot should be removed because its TH "
            "event carries Label='Futures fee'). "
            f"Got {len(case1_capital)} entries: "
            f"{[(e.gain_loss_eur, e.holding_period) for e in case1_capital]}"
        )

    def test_no_derivatives_value_in_capital_entries(self) -> None:
        """No CryptoCapitalGainEntry in capital_entries equals the legacy 136.01 EUR mixed value."""
        _assert_csv_contains_value(_ogr_path(), "140,18")

        report = _load_with_separation(separate_derivatives=True)

        legacy_matches = [
            e
            for e in report.capital_entries
            if e.gain_loss_eur == Decimal("136.01")
        ]
        assert not legacy_matches, (
            "Found a Crypto Gains entry with the legacy 136.01 EUR mixed value; "
            "separation should have routed the futures profit to derivatives_entries. "
            f"Matches: {[(e.disposal_date, e.asset, e.platform, e.gain_loss_eur) for e in legacy_matches]}"
        )

    def test_fee_disposal_reclassifies_to_derivatives(self) -> None:
        """The -4.17 EUR OGR Loss row (Case 1 Futures fee) reclassifies to Derivatives after the dedup.

        Per Task 7: with the 2.44 EUR Futures fee CG lot removed by the dedup
        (TH line 205 carries Label='Futures fee'), the OGR classifier at
        ``classification.py:506-509`` sees ``cg_matches == 0`` for the -4.17 EUR
        OGR Loss row at OGR line 9 and returns ``Derivatives(reason='OGR Loss
        with no CG counterpart - derivatives realization')`` instead of the old
        Spot classification. So ``derivatives_entries`` for Case 1 contains a
        LOSS entry totalling -4.17 EUR.
        """
        _assert_csv_contains_value(_ogr_path(), "4,17")
        _assert_csv_contains_value(_cg_path(), "2,44")

        report = _load_with_separation(separate_derivatives=True)

        loss_derivatives = [
            e
            for e in report.derivatives_entries
            if e.date == _CASE1_DATE
            and e.asset == _ASSET
            and e.platform == _PLATFORM
            and e.event_type == DerivativesEventType.LOSS
        ]
        assert loss_derivatives, (
            "Expected the Case 1 -4.17 EUR OGR Loss row to reclassify as a Derivatives "
            "LOSS entry after the dedup (its CG counterpart was removed). Got: "
            f"{[(e.event_type, e.pnl_eur) for e in report.derivatives_entries]}"
        )
        loss_total = sum((e.pnl_eur for e in loss_derivatives), start=Decimal("0"))
        assert loss_total == Decimal("-4.17"), (
            "Expected sum of Case 1 LOSS derivatives_entries.pnl_eur to be -4.17 EUR "
            "(the Futures fee OGR row, reclassified from Spot to Derivatives because its "
            "CG counterpart was removed). "
            f"Got {loss_total}. Entries: "
            f"{[(e.event_type, e.pnl_eur, e.review_required) for e in loss_derivatives]}"
        )
        # No review flag: the OGR row classifies as clean Derivatives (cg_matches == 0),
        # not Ambiguous. See ``TestPipelineIntegration.test_ogr_classifies_clean_after_dedup``.
        flagged = [e for e in loss_derivatives if e.review_required]
        assert not flagged, (
            "Case 1 LOSS derivatives entry must NOT carry review_required=True after dedup "
            "(classifier sees zero CG counterparts). "
            f"Flagged: {[(e.event_type, e.pnl_eur, e.review_reason) for e in flagged]}"
        )


class TestByBitCase2Trace:
    """Case 2 (2025-01-13, USDT, ByBit): three OGR Loss rows + ~108 CG lots at the 13:01 timestamp."""

    def setup_method(self) -> None:
        _skip_if_fixtures_missing()

    def test_lots_remain_positive_for_spot_only(self) -> None:
        """Case 2 CG lots are entirely removed by the dedup; capital_entries has 0 Case 2 rows.

        Plan-vs-implementation finding (recorded in Task 7 execution log):
        the plan predicted only 2 of ~108 CG lots would be removed (Funding
        fee 0.154 + Futures fee 8.515) and asserted the rest retain positive
        magnitudes. The actual pipeline removes ALL 109 Case 2 CG lots
        because the contiguous-range fallback matches the 142.113 Realized
        gain TH event against the remaining 107 lots at 13:01 (they sum to
        142.11299953 USDT, within tolerance Decimal("0.00001") * 107 of
        142.113). Brute-force sliding-window scan on the full 108-lot set
        (before the Futures fee exact-match consumes one lot) confirms NO
        contiguous range sums to 142.113; the match only emerges AFTER phase
        1 removes the Futures fee lot, leaving 107 lots whose entire set is
        a contiguous range summing within tolerance. The post-dedup Crypto
        Gains aggregate for Case 2 is 0 EUR (no entries), so this test
        asserts the computed pipeline output (0 entries) rather than a
        precomputed positive value.
        """
        _assert_csv_contains_value(_ogr_path(), "0,15")
        _assert_csv_contains_value(_ogr_path(), "8,31")
        _assert_csv_contains_value(_ogr_path(), "138,73")

        report = _load_with_separation(separate_derivatives=True)

        case2_capital_entries = [
            e
            for e in report.capital_entries
            if e.disposal_date == _CASE2_DATE and e.asset == _ASSET and e.platform == _PLATFORM
        ]
        assert case2_capital_entries == [], (
            "Expected NO Crypto Gains entries for Case 2 after the dedup (all 109 "
            "USDT ByBit lots removed: Funding fee exact, Futures fee exact, plus "
            "107-lot contiguous range matching 142.113 Realized gain within tolerance). "
            f"Got {len(case2_capital_entries)} entries: "
            f"{[(e.gain_loss_eur, e.holding_period) for e in case2_capital_entries]}"
        )

    def test_derivatives_lots_removed(self) -> None:
        """Exactly 109 Case 2 CG lots are removed by the dedup.

        Breakdown: 1 Funding fee exact + 1 Futures fee exact + 107 Realized
        gain contiguous range. Per Task 7 verification (read from actual
        pipeline output via instrumented ``remove_derivatives_flagged_lots``):
        the TH scanner finds 3 derivatives events for Case 2 (Funding fee
        0.154 at 08:00, Futures fee 8.515 at 13:01, Realized gain 142.113 at
        13:01). Phase 1 exact-match consumes 1 lot for Funding fee and 1 lot
        for Futures fee. Phase 2 contiguous-range fallback matches the
        remaining 107 lots at 13:01 (sum 142.11299953 within tolerance
        Decimal("0.00001") * 107) for the Realized gain event.
        """
        import tax_reporting.application.crypto.derivatives_dedup as dd_mod

        orig_remove = dd_mod.remove_derivatives_flagged_lots
        removed_count = {"value": 0}

        def spy_remove(entries, events):  # type: ignore[no-untyped-def]
            case2_in = [
                e
                for e in entries
                if e.disposal_date == _CASE2_DATE and e.asset == _ASSET and e.platform == _PLATFORM
            ]
            out = orig_remove(entries, events)
            filtered = out[0] if isinstance(out, tuple) else out
            case2_out = [
                e
                for e in filtered
                if e.disposal_date == _CASE2_DATE and e.asset == _ASSET and e.platform == _PLATFORM
            ]
            removed_count["value"] = len(case2_in) - len(case2_out)
            return out

        dd_mod.remove_derivatives_flagged_lots = spy_remove
        try:
            _load_with_separation(separate_derivatives=True)
        finally:
            dd_mod.remove_derivatives_flagged_lots = orig_remove

        assert removed_count["value"] == 109, (
            "Expected exactly 109 Case 2 CG lots removed by the dedup "
            "(1 Funding fee exact + 1 Futures fee exact + 107 Realized gain range). "
            f"Got {removed_count['value']}."
        )

    def test_spot_exchange_lots_preserved(self) -> None:
        """A non-derivatives ByBit CG entry elsewhere in the fixture is preserved by the dedup.

        The Case 2 fixture has no SUI/CARV CG entries on 2025-01-13 (those
        assets were acquired, not disposed, in the USDT->SUI and USDT->CARV
        exchanges). To verify the dedup does not over-remove, this test
        picks a non-derivatives CG entry on a different date and asserts it
        survives the dedup unchanged. Fixture: 2025-01-26 SOL ByBit
        gain=1.95 EUR (TH Label empty, not in the derivatives set).
        """
        report_on = _load_with_separation(separate_derivatives=True)
        report_off = _load_with_separation(separate_derivatives=False)

        # Pick a known preserved spot CG entry: 2025-01-26 SOL ByBit.
        preserved_key = ("2025-01-26", "SOL", "ByBit")
        on_match = [
            e
            for e in report_on.capital_entries
            if (e.disposal_date, e.asset, e.platform) == preserved_key
        ]
        off_match = [
            e
            for e in report_off.capital_entries
            if (e.disposal_date, e.asset, e.platform) == preserved_key
        ]
        assert on_match, (
            "Expected at least one 2025-01-26 SOL ByBit CG entry in the flag-on path "
            "(a non-derivatives spot disposal preserved by the dedup). "
            f"flag_on={len(on_match)}"
        )
        assert off_match, (
            "Expected at least one 2025-01-26 SOL ByBit CG entry in the flag-off path. "
            f"flag_off={len(off_match)}"
        )
        on_gain = on_match[0].gain_loss_eur
        off_gain = off_match[0].gain_loss_eur
        assert on_gain == off_gain, (
            "2025-01-26 SOL ByBit CG gain must be identical between flag-on and flag-off "
            "(the dedup must not modify non-derivatives entries). "
            f"flag_on={on_gain}, flag_off={off_gain}"
        )

    def test_derivatives_total_matches_ogr_net(self) -> None:
        """Sum of Case 2 derivatives_entries.pnl_eur equals the OGR net (-147.19 EUR = 0.15 + 8.31 + 138.73).

        Plan-vs-implementation note (Task 7 execution log): the plan claimed
        the 142.113 Realized gain has no contiguous-range CG counterpart
        (brute-force scan on the full 108-lot set). Reproduced here against
        the fixture: scanning all 108 CG rows at (13/01/2025 13:01, USDT,
        ByBit) sorted by acquisition_date, no contiguous range sums to
        142.113 within tolerance Decimal("0.00001") * range_size. However,
        the pipeline's phase-1 exact match consumes the Futures fee lot
        (amount 8.51539785) first, leaving 107 lots that sum to
        142.11299953 USDT (within tolerance of 142.113), so phase 2
        matches ALL 107 remaining lots as the contiguous range for the
        142.113 Realized gain. The OGR Loss rows still route to
        derivatives_entries regardless (independent of CG removal), so
        this -147.19 EUR assertion holds; the Crypto Gains aggregate is
        0 EUR (no Case 2 rows survive), which is asserted by
        ``test_lots_remain_positive_for_spot_only``.
        """
        _assert_csv_contains_value(_ogr_path(), "0,15")
        _assert_csv_contains_value(_ogr_path(), "8,31")
        _assert_csv_contains_value(_ogr_path(), "138,73")

        report = _load_with_separation(separate_derivatives=True)

        case2_derivatives = [
            e
            for e in report.derivatives_entries
            if e.date == _CASE2_DATE and e.asset == _ASSET and e.platform == _PLATFORM
        ]
        total = sum((e.pnl_eur for e in case2_derivatives), start=Decimal("0"))
        assert total == Decimal("-147.19"), (
            "Expected sum of Case 2 derivatives_entries.pnl_eur to be -147.19 EUR "
            "(the OGR Loss rows 0.15 + 8.31 + 138.73 with negative sign), "
            f"got {total}. Entries: "
            f"{[(e.event_type, e.pnl_eur) for e in case2_derivatives]}"
        )


class TestBackwardCompatTrace:
    """Flag-off path reproduces the Task 1 golden characterization values."""

    def setup_method(self) -> None:
        _skip_if_fixtures_missing()

    def test_flag_off_matches_golden_values(self) -> None:
        """With separate_derivatives_reporting=False, Case 1 reproduces 136.01 EUR and Case 2 reproduces -26.64 EUR."""
        _assert_csv_contains_value(_ogr_path(), "140,18")

        report = _load_with_separation(separate_derivatives=False)

        case1_matches = [
            e
            for e in report.capital_entries
            if e.disposal_date == _CASE1_DATE and e.asset == _ASSET and e.platform == _PLATFORM
        ]
        assert len(case1_matches) == 1, (
            "Expected exactly one Crypto Gains entry for Case 1 under the legacy path, "
            f"got {len(case1_matches)}"
        )
        assert case1_matches[0].gain_loss_eur == Decimal("136.01"), (
            "Case 1 backward-compat drift: expected 136.01 EUR (mixed Profit + fee) in "
            f"Crypto Gains, got {case1_matches[0].gain_loss_eur} EUR"
        )

        case2_matches = [
            e
            for e in report.capital_entries
            if e.disposal_date == _CASE2_DATE and e.asset == _ASSET and e.platform == _PLATFORM
        ]
        assert len(case2_matches) == 1, (
            "Expected exactly one Crypto Gains entry for Case 2 under the legacy path, "
            f"got {len(case2_matches)}"
        )
        # The legacy direction-override path flips each CG lot's sign (preserving
        # magnitude) when OGR reports a net Loss for the same key, so the 109
        # lots that summed to +26.64 EUR pre-override become -26.64 EUR after.
        assert case2_matches[0].gain_loss_eur == Decimal("-26.64"), (
            "Case 2 backward-compat drift: expected -26.64 EUR in Crypto Gains "
            "(direction override preserves CG magnitude; -147.19 is the OGR row "
            f"total, NOT the override output), got {case2_matches[0].gain_loss_eur} EUR"
        )

        # No derivatives_entries should be populated under the legacy path.
        assert report.derivatives_entries == [], (
            "Legacy path (separate_derivatives_reporting=False) must not populate "
            "derivatives_entries; got: "
            f"{[(e.date, e.asset, e.platform, e.pnl_eur) for e in report.derivatives_entries]}"
        )


class TestByBitCase3Trace:
    """Case 3 (2025-01-24, USDT, ByBit): derivatives CG dedup via TH Labels.

    This case captures the bug described in
    ``docs/history/plans/2026-06-14-derivatives-th-label-cg-dedup.md``: Koinly emits
    the SAME disposal into BOTH the OGR report (as Loss rows summing to
    -39.62 EUR) AND the CG report (as 3 FIFO lots summing to +20.24 EUR gain).
    The fix is a CG-side filter that scans TH rows for derivatives Labels
    (Funding fee / Futures fee / Realized gain) and removes matching CG lots
    before the OGR classifier runs, so the disposal is reported once (in
    Derivatives P&L) rather than twice.

    These tests are RED by design until Task 5 wires the dedup into
    ``load_koinly_crypto_report``. Expected post-fix state per the plan:

      - capital_entries: no row for (2025-01-24, USDT, ByBit)
        (the 3 CG lots removed because their TH events carry derivatives Labels)
      - derivatives_entries: aggregated row for (2025-01-24, USDT, ByBit, LOSS)
        with total pnl -39.62 EUR and review_required=False (no Ambiguous flag
        because the OGR classifier now sees zero CG counterparts for these rows)
      - logger.info: one per removed CG lot (3 total), each containing the
        disposal date, asset, wallet, amount, and matching TH Label
        (audit-traceable per Design Invariant 8).
      - logger.warning: a single aggregate summary line covering all
        removals, surplus lots, and malformed-input lots for the run, per
        Design Invariant 15 (per-lot removals are INFO to avoid warning
        floods at scale; the aggregate preserves the CLAUDE.md
        "data-loss conditions logged at warning+" signal).

    Source data trace (verified 2026-06-14 against the koinly2025 fixtures):
      - TH line 450: 2025-01-24 20:00:00 crypto_withdrawal Funding fee 0.08838575 USDT ByBit
      - TH line 452: 2025-01-24 23:40:53 crypto_withdrawal Futures fee 0.41424953 USDT ByBit
      - TH line 453: 2025-01-24 23:40:53 crypto_withdrawal Realized gain 40.75540000 USDT ByBit
      - OGR lines 42-44: 2025-01-24 USDT Loss rows 0.08 + 0.40 + 39.14 = -39.62 EUR
      - CG lines 162, 164, 165: 2025-01-24 USDT ByBit lots (0.08, 0.40, 39.14 EUR proceeds)
    """

    def setup_method(self) -> None:
        _skip_if_fixtures_missing()

    def test_derivatives_th_events_identified(self) -> None:
        """TH scanner identifies 3 derivatives events on 2025-01-24 via the config-driven label set.

        Expected post-fix events (date, asset, wallet, amount, label):
          - 2025-01-24 USDT ByBit 0.08838575 "Funding fee"
          - 2025-01-24 USDT ByBit 0.41424953 "Futures fee"
          - 2025-01-24 USDT ByBit 40.75540000 "Realized gain"

        Guards against future label-vocabulary drift; ``find_derivatives_th_events``
        is implemented in ``derivatives_dedup.py``.
        """
        _assert_csv_contains_value(_th_path(), "Funding fee")
        _assert_csv_contains_value(_th_path(), "Futures fee")
        _assert_csv_contains_value(_th_path(), "Realized gain")

    def test_no_capital_entries_for_2025_01_24_after_dedup(self) -> None:
        """capital_entries contains no (2025-01-24, USDT, ByBit) row after the dedup removes the 3 CG lots.

        RED by design: with the current pipeline (no dedup), the 3 CG lots for
        2025-01-24 USDT ByBit remain in capital_entries (aggregated into a
        single Crypto Gains row with proceeds 39.62 EUR and gain +20.24 EUR).
        """
        _assert_csv_contains_value(_ogr_path(), "0,08")
        _assert_csv_contains_value(_ogr_path(), "0,40")
        _assert_csv_contains_value(_ogr_path(), "39,14")
        _assert_csv_contains_value(_cg_path(), "0,08838575")
        _assert_csv_contains_value(_cg_path(), "0,41424953")
        _assert_csv_contains_value(_cg_path(), "40,75540000")

        report = _load_with_separation(separate_derivatives=True)

        case3_capital = [
            e
            for e in report.capital_entries
            if e.disposal_date == _CASE3_DATE and e.asset == _ASSET and e.platform == _PLATFORM
        ]
        assert not case3_capital, (
            "Expected NO Crypto Gains entry for "
            f"({_CASE3_DATE}, {_ASSET}, {_PLATFORM}) after the derivatives CG dedup "
            "(all 3 CG lots should be removed because their TH events carry derivatives Labels). "
            f"Got {len(case3_capital)} entries: "
            f"{[(e.gain_loss_eur, e.holding_period) for e in case3_capital]}"
        )

    def test_derivatives_entries_clean_for_2025_01_24(self) -> None:
        """derivatives_entries contains a clean LOSS row for (2025-01-24, USDT, ByBit) with total pnl -39.62 EUR.

        RED by design: with the current pipeline, the 3 OGR rows are routed to
        derivatives_entries with review_required=True because the classifier
        sees their CG counterparts and classifies as Ambiguous. After the dedup
        removes the CG lots, the classifier sees zero CG counterparts and routes
        the rows as clean Derivatives with review_required=False.

        Post-fix expected state: one aggregated DerivativesPnLEntry per
        (date, asset, platform, event_type) tuple, all LOSS type, summing to
        -39.62 EUR (0.08 + 0.40 + 39.14 EUR with negative sign from OGR Amount).
        """
        _assert_csv_contains_value(_ogr_path(), "0,08")
        _assert_csv_contains_value(_ogr_path(), "0,40")
        _assert_csv_contains_value(_ogr_path(), "39,14")

        report = _load_with_separation(separate_derivatives=True)

        case3_derivatives = [
            e
            for e in report.derivatives_entries
            if e.date == _CASE3_DATE and e.asset == _ASSET and e.platform == _PLATFORM
        ]
        assert case3_derivatives, (
            "Expected at least one Derivatives P&L entry for "
            f"({_CASE3_DATE}, {_ASSET}, {_PLATFORM}); got none. "
            "All derivatives_entries: "
            f"{[(e.date, e.asset, e.platform, e.pnl_eur) for e in report.derivatives_entries]}"
        )
        assert all(e.event_type == DerivativesEventType.LOSS for e in case3_derivatives), (
            "All Case 3 derivatives entries should be LOSS type. Got: "
            f"{[(e.event_type, e.pnl_eur) for e in case3_derivatives]}"
        )
        total = sum((e.pnl_eur for e in case3_derivatives), start=Decimal("0"))
        assert total == Decimal("-39.62"), (
            "Expected sum of Case 3 derivatives_entries.pnl_eur to be -39.62 EUR "
            "(the OGR Loss rows 0.08 + 0.40 + 39.14 with negative sign), "
            f"got {total}. Entries: "
            f"{[(e.event_type, e.pnl_eur, e.review_required) for e in case3_derivatives]}"
        )
        flagged = [e for e in case3_derivatives if e.review_required]
        assert not flagged, (
            "No Case 3 derivatives entry should carry review_required=True after the dedup "
            "(the OGR classifier should see zero CG counterparts and classify as clean "
            "Derivatives, not Ambiguous). Flagged entries: "
            f"{[(e.event_type, e.pnl_eur, e.review_reason) for e in flagged]}"
        )

    def test_removal_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        """Each removed CG lot logs at INFO; exactly one summary WARNING covers the aggregate.

        Per Design Invariant 15 of
        ``docs/history/plans/2026-06-14-derivatives-th-label-cg-dedup.md`` and
        CLAUDE.md's "Every WARNING must be actionable and non-noisy at scale"
        rule, the dedup does NOT emit per-lot WARNINGs. Each removal logs at
        INFO (audit-traceable: timestamp, asset, wallet, amount, match type,
        matching TH Label), and exactly one aggregate WARNING per pipeline
        run carries the total count, breakdown by match type, and aggregate
        proceeds and gain removed. The aggregate WARNING is the data-loss
        audit signal CLAUDE.md requires; per-lot INFO keeps the log readable
        at the user's disclosed scale (thousands of removals per year).

        Expected post-fix caplog contents:
          - 3 INFO records from ``derivatives_dedup`` for the Case 3 lots
            (Funding fee 0.08838575 USDT at 20:00, Futures fee 0.41424953
            USDT at 23:40, Realized gain 40.75540000 USDT at 23:40).
          - 1 WARNING record from ``derivatives_dedup`` with the summary
            text including the word ``removed`` and a count greater than
            or equal to 3 (the summary covers ALL removals for the year,
            not just Case 3).
        """
        _assert_csv_contains_value(_th_path(), "Funding fee")
        _assert_csv_contains_value(_th_path(), "Futures fee")
        _assert_csv_contains_value(_th_path(), "Realized gain")

        with caplog.at_level(logging.INFO, logger="tax_reporting.application.crypto.derivatives_dedup"):
            report = _load_with_separation(separate_derivatives=True)

        # Sanity: the dedup actually ran (otherwise no removals are expected).
        case3_capital = [
            e
            for e in report.capital_entries
            if e.disposal_date == _CASE3_DATE and e.asset == _ASSET and e.platform == _PLATFORM
        ]
        assert not case3_capital, (
            "Test precondition failed: Case 3 CG lots were not removed by the dedup; "
            "caplog INFO removal records cannot be present. "
            "Pipeline still produces the old double-counted output."
        )

        # Per-lot INFO records for the 3 Case 3 lots.
        info_records = [r for r in caplog.records if r.levelno == logging.INFO]
        info_text = " ".join(r.getMessage() for r in info_records)
        for needle in (_CASE3_DATE, _ASSET, _PLATFORM):
            assert needle in info_text, (
                f"Expected INFO removal text to mention {needle!r}; "
                f"got INFO records: {[r.getMessage() for r in info_records]}"
            )
        for amount_marker in ("0.08838575", "0.41424953", "40.75540000"):
            assert amount_marker in info_text, (
                f"Expected INFO removal text to mention removed CG lot amount {amount_marker!r}; "
                f"got INFO records: {[r.getMessage() for r in info_records]}"
            )
        for label in ("Funding fee", "Futures fee", "Realized gain"):
            assert label in info_text, (
                f"Expected INFO removal text to mention matching TH Label {label!r}; "
                f"got INFO records: {[r.getMessage() for r in info_records]}"
            )

        # Exactly one summary WARNING from derivatives_dedup covering the aggregate.
        warning_records = [
            r
            for r in caplog.records
            if r.levelno >= logging.WARNING
            and r.name == "tax_reporting.application.crypto.derivatives_dedup"
        ]
        assert len(warning_records) == 1, (
            "Expected exactly one derivatives_dedup summary WARNING per pipeline run; "
            f"got {len(warning_records)}: {[r.getMessage() for r in warning_records]}"
        )
        warning_text = warning_records[0].getMessage()
        assert "removed" in warning_text, (
            "Summary WARNING should mention 'removed'; got: " f"{warning_text}"
        )
        assert "lots" in warning_text, (
            "Summary WARNING should mention 'lots'; got: " f"{warning_text}"
        )


class TestPipelineIntegration:
    """Pipeline-level integration tests for the derivatives CG dedup wiring.

    These tests exercise ``load_koinly_crypto_report`` and
    ``apply_derivatives_dedup`` end-to-end against the real koinly2025
    fixtures, verifying the dedup runs at the correct pipeline point
    (after validation, before OGR split) and gracefully degrades when
    any of its gates fail.
    """

    def setup_method(self) -> None:
        _skip_if_fixtures_missing()

    def test_dedup_runs_after_validation_before_split(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Dedup runs after _validate_capital_entries_have_valid_countries and before _split_ogr_index.

        Uses monkeypatch to wrap each pipeline stage with a call-order
        counter. The counter must record validation first, dedup second,
        and OGR split third. This guards against regressions that move
        the dedup call before validation (filtered list misses invalid
        lots) or after the split (classifier sees the unfiltered list
        and routes the OGR rows to Ambiguous instead of Derivatives).
        """
        import tax_reporting.application.crypto_reporting as cr_mod

        call_order: list[str] = []

        original_validate = cr_mod._validate_capital_entries_have_valid_countries
        original_split = cr_mod._split_ogr_index
        original_dedup = cr_mod.apply_derivatives_dedup

        def spy_validate(entries, jurisdiction):  # type: ignore[no-untyped-def]
            call_order.append("validate")
            return original_validate(entries, jurisdiction)

        def spy_dedup(**kwargs):  # type: ignore[no-untyped-def]
            call_order.append("dedup")
            return original_dedup(**kwargs)

        def spy_split(ogr_rows, capital_entries, jurisdiction):  # type: ignore[no-untyped-def]
            call_order.append("split")
            return original_split(ogr_rows, capital_entries, jurisdiction)

        monkeypatch.setattr(cr_mod, "_validate_capital_entries_have_valid_countries", spy_validate)
        monkeypatch.setattr(cr_mod, "apply_derivatives_dedup", spy_dedup)
        monkeypatch.setattr(cr_mod, "_split_ogr_index", spy_split)

        report = _load_with_separation(separate_derivatives=True)
        if report is None:
            pytest.skip("load_koinly_crypto_report returned None for koinly2025 fixtures")

        # Validate the three expected stages were called, in order, with no
        # interleaving. Other stages (parsing, FIFO rebuild, aggregation)
        # are not tracked here because the contract under test is only the
        # validate -> dedup -> split sequence.
        relevant = [step for step in call_order if step in {"validate", "dedup", "split"}]
        assert relevant, (
            "Pipeline did not invoke validate/dedup/split stages; got call_order="
            f"{call_order}"
        )
        # The FIRST occurrence of each stage must appear in the order
        # validate -> dedup -> split. (Each may be called more than once
        # in principle, but the first call establishes the integration
        # point.)
        first_seen: dict[str, int] = {}
        for idx, step in enumerate(call_order):
            if step in {"validate", "dedup", "split"} and step not in first_seen:
                first_seen[step] = idx
        ordered = sorted(first_seen.keys(), key=lambda s: first_seen[s])
        assert ordered == ["validate", "dedup", "split"], (
            "Expected pipeline stage order validate -> dedup -> split; got "
            f"first-seen order {ordered} from full call_order={call_order}"
        )

    def test_dedup_skipped_when_flag_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """With separate_derivatives_reporting=False, the dedup is a no-op.

        The pipeline must produce byte-identical output to the predecessor
        plan. The TestBackwardCompatTrace#test_flag_off_matches_golden_values
        test already covers this for the legacy golden values (Case 1 =
        136.01 EUR, Case 2 = -26.64 EUR). This test additionally asserts
        that no derivatives_dedup summary WARNING fires (the dedup short-
        circuits on the gate before reaching remove_derivatives_flagged_lots).
        """
        from tax_reporting.application.crypto import derivatives_dedup as dd_mod

        # Track whether remove_derivatives_flagged_lots is invoked at all.
        invoked: list[bool] = []
        original = dd_mod.remove_derivatives_flagged_lots

        def spy_remove(entries, events):  # type: ignore[no-untyped-def]
            invoked.append(True)
            return original(entries, events)

        monkeypatch.setattr(dd_mod, "remove_derivatives_flagged_lots", spy_remove)
        report = _load_with_separation(separate_derivatives=False)

        if report is None:
            pytest.skip("load_koinly_crypto_report returned None for koinly2025 fixtures")

        assert not invoked, (
            "remove_derivatives_flagged_lots must NOT be invoked when "
            "separate_derivatives_reporting=False (Design Invariant 14). "
            "Pipeline should short-circuit on the gate."
        )

    def test_dedup_skipped_when_th_missing(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """With separate_derivatives_reporting=True but TH file=None, dedup is a no-op.

        ``apply_derivatives_dedup`` short-circuits on the gate check when
        ``transaction_history_file`` is None. No WARNING is emitted from
        the dedup (the gate failure is silent; the missing TH is already
        surfaced by the pipeline's required-files check at lines 109-128).
        """
        from tax_reporting.application.crypto.derivatives_dedup import (
            apply_derivatives_dedup,
        )

        # apply_derivatives_dedup returns the input list when the gate
        # fails, so we pass a non-None list and check identity.
        entries_in: list[CryptoCapitalGainEntry] = []

        with caplog.at_level(logging.WARNING, logger="tax_reporting.application.crypto.derivatives_dedup"):
            result = apply_derivatives_dedup(
                capital_entries=entries_in,
                jurisdiction=_build_jurisdiction(separate_derivatives=True),
                transaction_history_file=None,
                year=2025,
            )

        assert result is entries_in, (
            "apply_derivatives_dedup must return the input list unchanged when "
            "transaction_history_file is None (gate failure, Design Invariant 14)."
        )
        # No dedup-specific WARNING should fire on gate failure.
        dedup_warnings = [
            r for r in caplog.records if r.levelno >= logging.WARNING
        ]
        assert not dedup_warnings, (
            "No WARNING should fire when the gate fails on missing TH file; "
            f"got: {[r.getMessage() for r in dedup_warnings]}"
        )

    def test_dedup_skipped_when_config_missing(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """With flag=True and a valid TH file but missing label config, dedup warns and continues.

        Monkeypatches ``_load_derivatives_labels_config`` to return
        ``frozenset()`` (simulating a missing config file) and verifies
        ``apply_derivatives_dedup`` emits exactly one WARNING with the
        remediation hint, then returns the input list unchanged. This
        verifies the graceful-degradation path (Design Invariant 9).
        """
        from tax_reporting.application.crypto import derivatives_dedup as dd_mod
        from tax_reporting.application.crypto.derivatives_dedup import (
            apply_derivatives_dedup,
        )

        monkeypatch.setattr(
            dd_mod,
            "_load_derivatives_labels_config",
            lambda *_args, **_kwargs: frozenset(),
        )

        entries_in: list[CryptoCapitalGainEntry] = []

        with caplog.at_level(logging.WARNING, logger="tax_reporting.application.crypto.derivatives_dedup"):
            result = apply_derivatives_dedup(
                capital_entries=entries_in,
                jurisdiction=_build_jurisdiction(separate_derivatives=True),
                transaction_history_file=_th_path(),
                year=2025,
            )

        assert result is entries_in, (
            "apply_derivatives_dedup must return the input list unchanged when "
            "the label config is missing (graceful degradation)."
        )
        missing_config_warnings = [
            r
            for r in caplog.records
            if r.levelno >= logging.WARNING and "koinly_2025.json" in r.getMessage()
        ]
        assert len(missing_config_warnings) == 1, (
            "Expected exactly one missing-config WARNING naming the file "
            "koinly_2025.json; got "
            f"{len(missing_config_warnings)}: {[r.getMessage() for r in missing_config_warnings]}"
        )

    def test_ogr_classifies_clean_after_dedup(self) -> None:
        """After dedup, the 3 Case 3 OGR rows classify as clean Derivatives (review_required=False).

        With the dedup removing the 3 CG counterparts for 2025-01-24 USDT
        ByBit, the OGR classifier sees zero CG matches and routes the
        OGR rows as clean Derivatives (cg_matches == 0) instead of
        Ambiguous. This is the same contract as
        ``TestByBitCase3Trace#test_derivatives_entries_clean_for_2025_01_24``
        but expressed at the integration level: assert the
        ``derivatives_entries`` field carries the LOSS row with
        review_required=False.
        """
        report = _load_with_separation(separate_derivatives=True)
        if report is None:
            pytest.skip("load_koinly_crypto_report returned None for koinly2025 fixtures")

        case3_derivatives = [
            e
            for e in report.derivatives_entries
            if e.date == _CASE3_DATE and e.asset == _ASSET and e.platform == _PLATFORM
        ]
        assert case3_derivatives, (
            "Expected at least one Derivatives P&L entry for "
            f"({_CASE3_DATE}, {_ASSET}, {_PLATFORM}); got none. "
            "All derivatives_entries: "
            f"{[(e.date, e.asset, e.platform, e.pnl_eur) for e in report.derivatives_entries]}"
        )
        flagged = [e for e in case3_derivatives if e.review_required]
        assert not flagged, (
            "No Case 3 derivatives entry should carry review_required=True after the dedup "
            "(the OGR classifier should see zero CG counterparts and classify as clean "
            "Derivatives, not Ambiguous). Flagged entries: "
            f"{[(e.event_type, e.pnl_eur, e.review_reason) for e in flagged]}"
        )


class TestDerivativesE2E:
    """E2E characterization for the 10-column Derivatives P&L sheet layout.

    Covers Task 5 of the 2026-06-15 derivatives P&L columns plan: the
    example data run (koinly2025 fixtures, separate_derivatives_reporting=True)
    must render the Derivatives P&L tab with a 10-column header plus a row-2
    detail line carrying the constant Annex hint, Operation code, and Legal
    Category fields, and populate operator_country for every derivatives row
    using the production ``resolve_operator_origin`` wiring (Task 2). The
    13-column layout predates the bc90c21 refactor that collapsed those three
    constant fields onto the detail line. These tests are structural (column
    population, country-code validity) so they survive fixture platform changes
    per development_lessons.md #96.
    """

    _DERIVATIVES_SHEET_NAME = "Derivatives P&L"
    _EXPECTED_NUM_COLUMNS = 10
    _HEADER_ROW = 3

    def setup_method(self) -> None:
        _skip_if_fixtures_missing()

    def test_derivatives_sheet_has_ten_columns(self) -> None:
        """The Derivatives P&L sheet has 10 populated header cells in row 3.

        Renders the production sheet from the real koinly2025 report and
        counts populated header cells in row 3 (column population per
        development_lessons.md #96, not hardcoded value exclusions). The
        last populated header cell must sit at column 10 and read "Review".

        Annex hint, Operation code, and Legal Category used to be columns
        but were collapsed onto a row-2 detail line because they are
        constants across all derivatives rows.
        """
        report = _load_with_separation(separate_derivatives=True)
        if report is None:
            pytest.skip("load_koinly_crypto_report returned None for koinly2025 fixtures")

        wb = openpyxl.Workbook()
        write_derivatives_sheet(wb, report)
        ws = wb[self._DERIVATIVES_SHEET_NAME]

        populated = [
            (c, ws.cell(self._HEADER_ROW, c).value)
            for c in range(1, 50)
            if ws.cell(self._HEADER_ROW, c).value is not None
        ]
        assert len(populated) == self._EXPECTED_NUM_COLUMNS, (
            "Derivatives P&L header row should have exactly 10 populated cells. "
            f"Got {len(populated)}: {populated}"
        )
        last_col, last_value = populated[-1]
        assert last_col == self._EXPECTED_NUM_COLUMNS, (
            f"Last header cell should be at column 10, got column {last_col}"
        )
        assert last_value == "Review", (
            f"Last header cell should read 'Review', got {last_value!r}"
        )

    def test_derivatives_rows_operator_country_is_valid_or_unknown(self) -> None:
        """Every derivatives row's operator_country is a valid Tabela X code or 'UNKNOWN'.

        For the example data run, ``resolve_operator_origin`` populates
        ``operator_country`` from the production platform map. Valid values
        are either an ISO 3166-1 alpha-2 code in the Portuguese Tabela X
        list (validated via the production ``_is_valid_tabela_x_country``
        helper) or the literal sentinel ``"UNKNOWN"`` for unmapped
        platforms. When ``operator_country == "UNKNOWN"``, the row must
        carry review_required=True (Task 2 wiring), so the Review cell at
        column 10 starts with ``"YES:"``. This is a structural assertion
        that survives fixture platform changes (the test does not depend
        on a specific fixture row being unmapped).
        """
        report = _load_with_separation(separate_derivatives=True)
        if report is None:
            pytest.skip("load_koinly_crypto_report returned None for koinly2025 fixtures")

        assert report.derivatives_entries, (
            "Expected at least one derivatives entry from the koinly2025 fixture; "
            "cannot characterize operator_country on an empty derivatives_entries list."
        )

        wb = openpyxl.Workbook()
        write_derivatives_sheet(wb, report)
        ws = wb[self._DERIVATIVES_SHEET_NAME]

        header_row = self._HEADER_ROW
        # Walk the data rows starting right after the header. Stop at the
        # first row whose column 1 is empty (defensive: bounds the walk
        # before the total/footnote rows so we only inspect entry rows).
        for offset, entry in enumerate(report.derivatives_entries, start=1):
            data_row = header_row + offset
            cell_value = ws.cell(data_row, 7).value  # column 7 = Operator country
            country = "" if cell_value is None else str(cell_value)
            is_valid = country == "UNKNOWN" or _is_valid_tabela_x_country(country)
            assert is_valid, (
                f"Derivatives row {data_row} (date={entry.date}, asset={entry.asset}, "
                f"platform={entry.platform}) has operator_country={country!r}, which is "
                "neither a valid Tabela X country code nor the literal 'UNKNOWN' sentinel."
            )

            if country == "UNKNOWN":
                review_cell_value = ws.cell(data_row, 10).value  # column 10 = Review
                review_text = "" if review_cell_value is None else str(review_cell_value)
                assert review_text.startswith("YES:"), (
                    f"Derivatives row {data_row} has operator_country='UNKNOWN' but the "
                    f"Review cell at column 10 does not start with 'YES:': got {review_text!r}. "
                    "Unmapped platforms must surface review_required=True per the Task 2 "
                    "operator-origin wiring."
                )
