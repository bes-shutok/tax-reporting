"""End-to-end data-trace verification for the DP-014 payment-proceeds correction.

Verifies (per docs/history/plans/2026-06-18-crypto-payment-proceeds.md Task 6 and
development_lessons.md #72, #73) that the real motivating case in
``resources/source/koinly2025/`` - a Koinly Payment disposal of an EUR-pegged
stablecoin (EUROC) whose CG ``Proceeds (EUR) == 0`` because Koinly's price DB had
no match for the imported ticker - no longer carries a phantom full-cost loss
after the correction is wired into ``load_koinly_crypto_report``.

Real motivating case (discovered via glob, never hardcoded here):
  - CG: a Payment disposal of EUROC on Wirex with proceeds=0, cost>0,
    amount>0, gain = -cost (the phantom full-cost loss).
  - TH: a matching ``Payment``-tagged row with ``Net Value (EUR) == 0``
    (Koinly could not price the imported EUROC ticker).
  - EUROC is an EUR-pegged stablecoin (Circle; renamed from EUROC to EURC in
    2024), so the correction sets proceeds = amount at par (1:1 EUR).

Assertions are STRUCTURAL (no phantom full-cost loss on the matched row; a
correction review entry exists), never hardcoded real disposal amounts/wallets,
per the personal-data hygiene rule. The expected proceeds (amount at par) and
the resulting immaterial gain are DERIVED at runtime from the parsed fixture so
the test anchors to source data, not literals.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from tax_reporting.application.crypto_reporting import load_koinly_crypto_report
from tax_reporting.infrastructure.config import TaxJurisdictionConfig

pytestmark = pytest.mark.e2e

_FIXTURE_DIR = Path("resources/source/koinly2025")


def _find_fixture(pattern: str) -> Path | None:
    """Find a Koinly fixture CSV by glob pattern.

    The koinly2025 directory contains real exports with account-specific tokens
    in their filenames. Discovery via glob keeps those tokens out of tracked
    test code (personal-data hygiene).
    """
    matches = sorted(_FIXTURE_DIR.glob(pattern))
    return matches[0] if matches else None


def _skip_if_fixtures_missing() -> None:
    """Skip the calling test gracefully when the koinly2025 directory is absent."""
    if not _FIXTURE_DIR.exists() or not _FIXTURE_DIR.is_dir():
        pytest.skip(f"koinly2025 fixture directory not available at {_FIXTURE_DIR}")


def _require_payment_pair() -> tuple[Path, Path, dict[str, str]]:
    """Return (cg_path, th_path, payment_th_row) for the real Payment disposal.

    Discovers the real CG and TH CSVs via glob and locates the ``Payment``-tagged
    TH disposal row. Returns the matched TH row as a dict so the test can derive
    expected values at runtime. Skips when any fixture is absent or no Payment
    row exists in TH. Uses ``read_koinly_rows`` so the Koinly title/blanks are
    handled (raw ``csv.DictReader`` would treat the title as the header).
    """
    from tax_reporting.infrastructure.koinly_parser import read_koinly_rows

    cg_path = _find_fixture("koinly_2025_capital_gains_report_*.csv")
    th_path = _find_fixture("koinly_2025_transaction_history_*.csv")
    if cg_path is None or th_path is None:
        pytest.skip("koinly2025 CG or TH fixture not available")

    # Locate the Payment-tagged TH disposal row (the motivating case).
    th_rows = read_koinly_rows(th_path)
    payment_rows = [row for row in th_rows if (row.get("Tag") or "").strip().lower() == "payment"]
    if not payment_rows:
        pytest.skip("No Payment-tagged TH row in the koinly2025 fixture; cannot exercise the correction")
    return cg_path, th_path, payment_rows[0]


class TestPaymentProceedsE2E:
    """E2E data-trace for the DP-014 payment-proceeds correction on real fixtures."""

    def setup_method(self) -> None:
        _skip_if_fixtures_missing()

    def test_payment_row_not_carrying_phantom_full_cost_loss(self) -> None:
        """The matched Payment disposal no longer carries a phantom full-cost loss.

        Before the correction: CG proceeds=0, gain = -cost (the full cost basis
        surfaces as a phantom loss). After the correction: proceeds is recovered
        from the TH Net Value (primary) or the EUR-par fallback (for an unpriced
        EUR-pegged stablecoin), and gain = proceeds - cost. For the real
        EUROC/Wirex case the TH Net Value is 0 and EUROC is EUR-pegged, so
        proceeds = amount at par and gain = amount - cost (sub-EUR, filtered by
        the materiality filter, so the row is absent from capital_entries).

        This test asserts the STRUCTURAL property (no phantom full-cost loss
        survives) by checking that NO capital_entries row for the Payment asset
        retains proceeds==0 with gain==-cost. It derives the expected corrected
        proceeds at runtime from the parsed fixture.
        """
        from tax_reporting.infrastructure.koinly_parser import (
            normalize_asset_ticker,
            parse_koinly_decimal,
            read_koinly_rows,
        )

        cg_path, _th_path, payment_row = _require_payment_pair()
        asset = normalize_asset_ticker(payment_row.get("Sent Currency", ""))
        amount = parse_koinly_decimal(payment_row.get("Sent Amount", "0"))
        # Verify the source fixture actually contains the phantom-loss CG row
        # (data-trace precondition: the CG row exists with proceeds=0).
        cg_rows = read_koinly_rows(cg_path)
        phantom_cg_rows = [
            row
            for row in cg_rows
            if normalize_asset_ticker(row.get("Asset", "")) == asset
            and parse_koinly_decimal(row.get("Proceeds (EUR)", "0")) == Decimal("0")
        ]
        if not phantom_cg_rows:
            pytest.skip(
                f"No zero-proceeds CG row for asset {asset} in the fixture; "
                "the motivating case is absent."
            )

        jurisdiction = TaxJurisdictionConfig(
            country="PT",
            fiscal_year=2025,
            exclude_loan_repayment_gains=True,
            zero_basis_review_threshold=Decimal("500"),
            infer_payment_proceeds=True,
        )
        report = load_koinly_crypto_report(_FIXTURE_DIR, jurisdiction=jurisdiction)
        if report is None:
            pytest.skip("load_koinly_crypto_report returned None for koinly2025 fixtures")

        # STRUCTURAL assertion: no surviving capital_entries row for the Payment
        # asset carries the phantom full-cost loss (proceeds==0 AND gain==-cost).
        phantom_survivors = [
            e
            for e in report.capital_entries
            if e.asset == asset and e.proceeds_eur == Decimal("0") and e.gain_loss_eur == -e.cost_eur
        ]
        assert not phantom_survivors, (
            f"Phantom full-cost loss survived for the Payment asset {asset}: "
            f"{[(e.proceeds_eur, e.gain_loss_eur, e.cost_eur) for e in phantom_survivors]}"
        )

        # The corrected row: EUROC is EUR-pegged, so proceeds = amount at par.
        # gain = amount - cost. If |gain| < 1 EUR the row is materiality-filtered
        # (absent from capital_entries), but a CryptoReviewEntry audit must remain.
        expected_proceeds = amount  # EUR par (1:1)
        # A correction-driven review entry for this asset must exist.
        correction_reviews = [
            r for r in report.review_entries if r.asset == asset and "EUR par" in (r.review_reason or "")
        ]
        assert correction_reviews, (
            f"Expected a CryptoReviewEntry audit row for the corrected Payment asset {asset} "
            f"naming 'EUR par'; review_entries: "
            f"{[(r.asset, r.review_reason) for r in report.review_entries if r.asset == asset]}"
        )
        # The review reason must reference the expected at-par proceeds magnitude
        # derived from the fixture (anchors the reason to source data, not a literal).
        review_text = correction_reviews[0].review_reason or ""
        # The always-true "EUR" disjunct is dropped: _eur_par_reason always
        # contains "EUR", so it masked a regression that dropped the numeric
        # magnitude. The reason must now carry the fixture-derived amount.
        mentions_proceeds = (
            str(expected_proceeds) in review_text
            or f"{expected_proceeds:.2f}" in review_text
        )
        assert mentions_proceeds, (
            f"The correction review reason should reference the at-par proceeds; got {review_text!r}"
        )

    def test_no_correction_when_flag_off_preserves_phantom_loss(self) -> None:
        """Flag off preserves today's behavior: the phantom full-cost loss survives.

        Backward-compat (lesson #84): with ``infer_payment_proceeds=False``, the
        correction block is skipped entirely, so the zero-proceeds Payment CG row
        keeps proceeds==0 and gain==-cost exactly as today. This is the structural
        negative-control for the positive test above.
        """
        from tax_reporting.infrastructure.koinly_parser import (
            normalize_asset_ticker,
            parse_koinly_decimal,
            read_koinly_rows,
        )

        cg_path, _th_path, payment_row = _require_payment_pair()
        asset = normalize_asset_ticker(payment_row.get("Sent Currency", ""))

        cg_rows = read_koinly_rows(cg_path)
        phantom_cg_rows = [
            row
            for row in cg_rows
            if normalize_asset_ticker(row.get("Asset", "")) == asset
            and parse_koinly_decimal(row.get("Proceeds (EUR)", "0")) == Decimal("0")
        ]
        if not phantom_cg_rows:
            pytest.skip(
                f"No zero-proceeds CG row for asset {asset} in the fixture; "
                "the motivating case is absent."
            )

        jurisdiction = TaxJurisdictionConfig(
            country="PT",
            fiscal_year=2025,
            exclude_loan_repayment_gains=True,
            zero_basis_review_threshold=Decimal("500"),
            infer_payment_proceeds=False,
        )
        report = load_koinly_crypto_report(_FIXTURE_DIR, jurisdiction=jurisdiction)
        if report is None:
            pytest.skip("load_koinly_crypto_report returned None for koinly2025 fixtures")

        # The phantom-loss row must survive with flag off (proceeds==0, gain==-cost).
        phantom_survivors = [
            e
            for e in report.capital_entries
            if e.asset == asset and e.proceeds_eur == Decimal("0") and e.gain_loss_eur == -e.cost_eur
        ]
        assert phantom_survivors, (
            f"With infer_payment_proceeds=False the phantom full-cost loss for {asset} "
            "must survive (today's behavior). Expected at least one row with proceeds==0."
        )
        # And NO correction-driven review entry for this asset.
        assert not any(
            r.asset == asset and "EUR par" in (r.review_reason or "") for r in report.review_entries
        ), "Flag off must NOT append payment-proceeds correction review entries"
