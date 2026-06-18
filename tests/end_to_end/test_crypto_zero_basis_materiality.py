"""End-to-end coverage for the zero-basis review flag materiality threshold.

Verifies that the ``zero_basis_review_min_proceeds`` threshold (DP-013,
default 10 EUR via ``ZERO_BASIS_REVIEW_MIN_PROCEEDS`` in ``config.ini``)
correctly suppresses the zero-basis review flag for FEE token disposals
and small rewards when the production ``koinly2025`` fixtures are run
through the full pipeline, and that the backward-compat escape hatch
(``min_proceeds=0``) restores the prior flag-everything behavior.

Per docs/plans/2026-06-15-zero-basis-review-materiality.md Task 5 and
development_lessons.md #72, #73: assertions are grounded in source data
rather than internal pipeline constants wherever possible.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from tax_reporting.application.crypto_reporting import load_koinly_crypto_report
from tax_reporting.infrastructure.config import TaxJurisdictionConfig

pytestmark = pytest.mark.e2e

_FIXTURE_DIR = Path("resources/source/koinly2025")
_ZERO_COST_REASON_MARKER = "Zero acquisition cost"
_MIN_PROCEEDS_DEFAULT = Decimal("10")

# Parameters for the synthetic zero-cost disposal fixture. The disposal carries
# cost_eur == 0 and proceeds well above both the min_proceeds gate (default 10 EUR)
# and the PT-C-028 |gain| >= 1 EUR materiality filter, so it survives the full
# pipeline and must carry the zero-basis review reason. See test
# test_larger_zero_cost_disposals_above_threshold_flagged.
_SYNTHETIC_ZERO_COST_PROCEEDS = Decimal("75")
_SYNTHETIC_ZERO_COST_ASSET = "ZBX"
_SYNTHETIC_ZERO_COST_WALLET = "Kraken"
_SYNTHETIC_ZERO_COST_DATE_SOLD = "15/06/2025 10:00"
_SYNTHETIC_ZERO_COST_DATE_ACQUIRED = "01/01/2024 00:00"


def _build_jurisdiction(*, min_proceeds: Decimal) -> TaxJurisdictionConfig:
    """Build a PT/2025 jurisdiction mirroring production decision-point flags.

    ``zero_basis_review_min_proceeds`` is the only knob varied between the
    default-threshold run and the backward-compat escape-hatch run.

    ``zero_basis_review_threshold`` is set to 500 EUR (ten times the production value of 50)
    to isolate the ``min_proceeds`` behavior from the gain/loss-magnitude flag. These two
    thresholds gate independent flags: ``zero_basis_review_threshold`` controls the Excel
    red-fill presentation flag triggered by gain/loss magnitude, while ``min_proceeds``
    controls the ``review_required`` field set at parse time. Raising the gain/loss
    threshold keeps the test population observable in ``capital_entries`` (the PT-C-028
    materiality filter would otherwise drop sub-50-EUR-gain entries before the assertions
    run) without coupling this test's pass/fail to the gain-magnitude flag's behavior.
    """
    return TaxJurisdictionConfig(
        country="PT",
        fiscal_year=2025,
        exclude_loan_repayment_gains=True,
        zero_basis_review_threshold=Decimal("500"),
        zero_basis_review_min_proceeds=min_proceeds,
        futures_derivatives_taxable=True,
        use_other_gains_report=True,
        separate_derivatives_reporting=True,
    )


def _skip_if_fixtures_missing() -> None:
    """Skip the calling test gracefully when the koinly2025 directory is absent."""
    if not _FIXTURE_DIR.exists() or not _FIXTURE_DIR.is_dir():
        pytest.skip(f"koinly2025 fixture directory not available at {_FIXTURE_DIR}")


def _load_report(*, min_proceeds: Decimal):
    report = load_koinly_crypto_report(
        _FIXTURE_DIR, jurisdiction=_build_jurisdiction(min_proceeds=min_proceeds)
    )
    if report is None:
        pytest.skip("load_koinly_crypto_report returned None for koinly2025 fixtures")
    return report


def _write_synthetic_zero_cost_fixture(dest_dir: Path) -> Path:
    """Write a minimal three-file Koinly export containing one zero-cost disposal.

    The production ``koinly2025`` fixtures contain no zero-cost disposal with
    proceeds >= 10 EUR (the condition under DP-013 that must trigger the
    zero-basis review flag). Rather than perturb the shared fixtures - which
    many other e2e tests assert on - this writes a tiny, self-contained
    directory into ``dest_dir`` containing exactly one such disposal plus the
    minimal income and transaction-history reports the pipeline requires.

    The disposal row:
    - ``Cost (EUR) == 0``  -> cost_eur == Decimal("0")
    - ``Proceeds (EUR) == 75`` -> above the 10 EUR min_proceeds gate
    - ``Gain / loss == 75``  -> |gain| >= 1 EUR, survives PT-C-028 materiality

    Returns the directory path.
    """
    proceeds = _SYNTHETIC_ZERO_COST_PROCEEDS
    capital_csv = (
        "Capital gains report 2025\n"
        "\n"
        "Date Sold,Date Acquired,Asset,Amount,Cost (EUR),Proceeds (EUR),Gain / loss,"
        "Notes,Wallet Name,Holding period\n"
        f"{_SYNTHETIC_ZERO_COST_DATE_SOLD},{_SYNTHETIC_ZERO_COST_DATE_ACQUIRED},"
        f"{_SYNTHETIC_ZERO_COST_ASSET},\"1,00000000\",0.0,{proceeds},{proceeds},"
        f"\"Airdrop\",{_SYNTHETIC_ZERO_COST_WALLET},Short term\n"
    )
    income_csv = (
        "Income report 2025\n"
        "\n"
        "Date,Asset,Amount,Value (EUR),Type,Description,Wallet Name\n"
    )
    transaction_history_csv = (
        "Transaction report 2025\n"
        "\n"
        "Date,Type,Tag,Sending Wallet,Sent Amount,Sent Currency,Sent Cost Basis,"
        "Receiving Wallet,Received Amount,Received Currency,Received Cost Basis,"
        "Fee Amount,Fee Currency,Gain (EUR),Net Value (EUR),Fee Value (EUR),"
        "TxSrc,TxDest,TxHash,Description\n"
    )
    (dest_dir / "koinly_2025_capital_gains_report_synth.csv").write_text(capital_csv, encoding="utf-8")
    (dest_dir / "koinly_2025_income_report_synth.csv").write_text(income_csv, encoding="utf-8")
    (dest_dir / "koinly_2025_transaction_history_synth.csv").write_text(
        transaction_history_csv, encoding="utf-8"
    )
    return dest_dir


def _load_synthetic_report(*, min_proceeds: Decimal, fixture_dir: Path):
    report = load_koinly_crypto_report(
        fixture_dir, jurisdiction=_build_jurisdiction(min_proceeds=min_proceeds)
    )
    if report is None:
        pytest.skip("load_koinly_crypto_report returned None for synthetic fixture")
    return report


class TestZeroBasisMaterialityE2E:
    """Covers the zero-basis materiality rule and the backward-compat escape hatch."""

    def setup_method(self) -> None:
        _skip_if_fixtures_missing()

    def test_fee_token_disposals_not_flagged(self) -> None:
        """Zero-cost zero-proceeds (FEE token) entries are never flagged under the default threshold.

        Either they are filtered out by the PT-C-028 1 EUR materiality filter (gain=0
        fails the |gain| >= 1 EUR gate), or, if any survive into ``capital_entries``,
        they must NOT carry the zero-basis review reason.
        """
        report = _load_report(min_proceeds=_MIN_PROCEEDS_DEFAULT)

        zero_zero_flagged = [
            e
            for e in report.capital_entries
            if e.cost_eur == Decimal("0")
            and e.proceeds_eur == Decimal("0")
            and e.review_required
            and _ZERO_COST_REASON_MARKER in (e.review_reason or "")
        ]
        assert not zero_zero_flagged, (
            "Zero-cost zero-proceeds entries must not carry the zero-basis review "
            "flag under the default min_proceeds threshold. Flagged entries: "
            f"{[(e.asset, e.platform, e.review_reason) for e in zero_zero_flagged]}"
        )

    def test_small_reward_disposals_below_threshold_not_flagged(self) -> None:
        """Zero-cost entries with proceeds below the threshold are not flagged for zero basis.

        Entries may still be flagged for OTHER reasons (e.g., ``Missing cost basis
        with tax impact``), but the zero-basis reason specifically must not appear.
        """
        report = _load_report(min_proceeds=_MIN_PROCEEDS_DEFAULT)

        small_rewards = [
            e
            for e in report.capital_entries
            if e.cost_eur == Decimal("0")
            and Decimal("0") < e.proceeds_eur < _MIN_PROCEEDS_DEFAULT
        ]
        if not small_rewards:
            pytest.skip("No zero-cost entries with 0 < proceeds < 10 EUR in koinly2025 fixtures")

        wrong_zero_basis = [
            e for e in small_rewards if _ZERO_COST_REASON_MARKER in (e.review_reason or "")
        ]
        assert not wrong_zero_basis, (
            "Zero-cost entries with proceeds below the threshold must not carry the "
            "zero-basis review reason. Offending entries: "
            f"{[(e.asset, e.platform, e.proceeds_eur, e.review_reason) for e in wrong_zero_basis]}"
        )

    def test_larger_zero_cost_disposals_above_threshold_flagged(self, tmp_path) -> None:
        """Zero-cost entries with proceeds >= threshold are flagged with the zero-basis reason.

        The production ``koinly2025`` fixtures contain no zero-cost disposal with
        proceeds >= 10 EUR, so this test drives a dedicated synthetic fixture (one
        such disposal, cost_eur == 0 and proceeds == 75 EUR) through the full
        pipeline. The disposal survives the PT-C-028 |gain| >= 1 EUR materiality
        filter (gain == 75 EUR) and MUST carry the zero-basis review reason.
        """
        fixture_dir = _write_synthetic_zero_cost_fixture(tmp_path)
        report = _load_synthetic_report(min_proceeds=_MIN_PROCEEDS_DEFAULT, fixture_dir=fixture_dir)

        larger = [
            e
            for e in report.capital_entries
            if e.cost_eur == Decimal("0") and e.proceeds_eur >= _MIN_PROCEEDS_DEFAULT
        ]
        assert larger, (
            "Synthetic fixture must produce at least one zero-cost entry with "
            "proceeds >= 10 EUR that survives the materiality filter"
        )

        # The synthetic disposal must be present and correctly flagged.
        synth_entries = [
            e for e in larger
            if e.asset == _SYNTHETIC_ZERO_COST_ASSET
            and e.proceeds_eur == _SYNTHETIC_ZERO_COST_PROCEEDS
        ]
        assert synth_entries, (
            f"Expected synthetic {_SYNTHETIC_ZERO_COST_ASSET} disposal "
            f"(proceeds={_SYNTHETIC_ZERO_COST_PROCEEDS}) in surviving entries; got "
            f"{[(e.asset, e.proceeds_eur) for e in larger]}"
        )
        synth = synth_entries[0]
        assert synth.cost_eur == Decimal("0"), (
            f"Synthetic disposal must have cost_eur == 0; got {synth.cost_eur}"
        )

        unflagged = [
            e
            for e in larger
            if not e.review_required or _ZERO_COST_REASON_MARKER not in (e.review_reason or "")
        ]
        assert not unflagged, (
            "Zero-cost entries with proceeds >= threshold must carry the zero-basis "
            "review reason. Unflagged entries: "
            f"{[(e.asset, e.platform, e.proceeds_eur, e.review_required, e.review_reason) for e in unflagged]}"
        )

    def test_backward_compat_min_proceeds_zero_flags_all(self) -> None:
        """Setting ``zero_basis_review_min_proceeds=0`` restores prior flag-everything behavior.

        Every zero-cost entry in ``capital_entries`` (which by construction has
        |gain| >= 1 EUR after the PT-C-028 materiality filter) must carry the
        zero-basis review reason. Zero-zero FEE token entries are filtered out
        by materiality (gain=0) and so are not observable in ``capital_entries``;
        this test therefore asserts on the post-materiality surviving set.
        """
        report = _load_report(min_proceeds=Decimal("0"))

        zero_cost = [
            e
            for e in report.capital_entries
            if e.cost_eur == Decimal("0") and e.proceeds_eur > Decimal("0")
        ]
        if not zero_cost:
            pytest.skip("No zero-cost entries with non-zero proceeds in koinly2025 fixtures")

        unflagged = [
            e
            for e in zero_cost
            if not e.review_required or _ZERO_COST_REASON_MARKER not in (e.review_reason or "")
        ]
        assert not unflagged, (
            "Under min_proceeds=0, every zero-cost entry must carry the zero-basis "
            "review reason. Unflagged entries: "
            f"{[(e.asset, e.platform, e.proceeds_eur, e.review_required, e.review_reason) for e in unflagged]}"
        )
