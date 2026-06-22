"""End-to-end data-trace verification for the DP-014 payment-proceeds correction.

Verifies (per docs/history/plans/2026-06-18-crypto-payment-proceeds.md Task 6 and
development_lessons.md #72, #73) that the committed synthetic example case in
``resources/source/example/koinly2025_payment/`` - a Koinly Payment disposal of
an EUR-pegged stablecoin (EUROC) whose CG ``Proceeds (EUR) == 0`` because Koinly's
price DB had no match for the imported ticker - no longer carries a phantom
full-cost loss after the correction is wired into ``load_koinly_crypto_report``.

Asserts STRUCTURAL properties (no phantom full-cost loss on the matched row; a
correction review entry exists), never hardcoded real disposal amounts/wallets.
The expected proceeds (amount at par) and the resulting immaterial gain are
derived at runtime from the parsed fixture so the test anchors to source data, not
literals.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from tax_reporting.application.crypto_reporting import load_koinly_crypto_report
from tests.conftest import KOINLY_2025_PAYMENT_EXAMPLE_DIR, build_koinly_jurisdiction

pytestmark = pytest.mark.e2e

_FIXTURE_DIR = KOINLY_2025_PAYMENT_EXAMPLE_DIR


def _find_fixture(pattern: str) -> Path:
    """Find a synthetic Koinly fixture CSV by glob pattern.

    The committed synthetic example directory uses the fixed ``_synth.csv``
    filename token, so glob discovery resolves exactly one file per pattern.
    """
    matches = sorted(_FIXTURE_DIR.glob(pattern))
    assert matches, f"Expected exactly one synthetic fixture matching {pattern!r} under {_FIXTURE_DIR}"
    return matches[0]


def _require_payment_pair() -> tuple[Path, Path, dict[str, str]]:
    """Return (cg_path, th_path, payment_th_row) for the synthetic Payment disposal.

    Discovers the synthetic CG and TH CSVs via glob and locates the ``Payment``-tagged
    TH disposal row. Returns the matched TH row as a dict so the test can derive
    expected values at runtime.
    """
    from tax_reporting.infrastructure.koinly_parser import read_koinly_rows

    cg_path = _find_fixture("koinly_2025_capital_gains_report_*.csv")
    th_path = _find_fixture("koinly_2025_transaction_history_*.csv")

    # Locate the Payment-tagged TH disposal row (the motivating case).
    th_rows = read_koinly_rows(th_path)
    payment_rows = [row for row in th_rows if (row.get("Tag") or "").strip().lower() == "payment"]
    assert payment_rows, f"No Payment-tagged TH row found in {th_path}"
    return cg_path, th_path, payment_rows[0]


def test_synthetic_fixture_contains_payment_scenarios() -> None:
    """Guard against fixture content drift: assert the synthetic CSVs carry the payment scenarios.

    Parses the committed example CSVs and asserts the payment scenario is
    present.
    """
    cg_path = _FIXTURE_DIR / "koinly_2025_capital_gains_report_synth.csv"
    assert cg_path.exists(), f"Payment CG report not found: {cg_path}"
    with cg_path.open(encoding="utf-8") as f:
        content = f.read()
    # Check for EUROC
    assert "EUROC" in content, "EUROC token entry missing from payment synthetic CG report"
    assert "Wirex" in content, "Wirex wallet missing from payment synthetic CG report"


class TestPaymentProceedsE2E:
    """E2E data-trace for the DP-014 payment-proceeds correction on synthetic fixtures."""

    def test_payment_row_not_carrying_phantom_full_cost_loss(self) -> None:
        """The matched Payment disposal no longer carries a phantom full-cost loss.

        Before the correction: CG proceeds=0, gain = -cost (the full cost basis
        surfaces as a phantom loss). After the correction: proceeds is recovered
        from the TH Net Value (primary) or the EUR-par fallback (for an unpriced
        EUR-pegged stablecoin), and gain = proceeds - cost. For the synthetic
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
        assert phantom_cg_rows, f"No zero-proceeds CG row for asset {asset} in the fixture"

        jurisdiction = build_koinly_jurisdiction(infer_payment_proceeds=True)
        report = load_koinly_crypto_report(_FIXTURE_DIR, jurisdiction=jurisdiction)
        assert report is not None, "load_koinly_crypto_report returned None for synthetic payment fixtures"

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
        assert phantom_cg_rows, f"No zero-proceeds CG row for asset {asset} in the fixture"

        jurisdiction = build_koinly_jurisdiction(infer_payment_proceeds=False)
        report = load_koinly_crypto_report(_FIXTURE_DIR, jurisdiction=jurisdiction)
        assert report is not None, "load_koinly_crypto_report returned None for synthetic payment fixtures"

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
