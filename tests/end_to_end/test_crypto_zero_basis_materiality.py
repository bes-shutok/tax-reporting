"""End-to-end coverage for the zero-basis review flag materiality threshold.

Verifies that the ``zero_basis_review_min_proceeds`` threshold (DP-013,
default 10 EUR via ``ZERO_BASIS_REVIEW_MIN_PROCEEDS`` in ``config.ini``)
correctly suppresses the zero-basis review flag for FEE token disposals
and small rewards when the committed synthetic ``koinly2025_zero_basis``
fixtures are run through the full pipeline, and that the backward-compat escape
hatch (``min_proceeds=0``) restores the prior flag-everything behavior.

Per docs/history/plans/2026-06-15-zero-basis-review-materiality.md Task 5 and
development_lessons.md #72, #73: assertions are grounded in source data
rather than internal pipeline constants wherever possible.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from tax_reporting.application.crypto_reporting import load_koinly_crypto_report
from tests.conftest import KOINLY_2025_ZERO_BASIS_EXAMPLE_DIR, build_koinly_jurisdiction

pytestmark = pytest.mark.e2e

_FIXTURE_DIR = KOINLY_2025_ZERO_BASIS_EXAMPLE_DIR
_ZERO_COST_REASON_MARKER = "Zero acquisition cost"
_MIN_PROCEEDS_DEFAULT = Decimal("10")

# Parameters for the synthetic zero-cost disposal fixture. The disposal carries
# cost_eur == 0 and proceeds well above both the min_proceeds gate (default 10 EUR)
# and the PT-C-028 |gain| >= 1 EUR materiality filter, so it survives the full
# pipeline and must carry the zero-basis review reason. See test
# test_larger_zero_cost_disposals_above_threshold_flagged.
_SYNTHETIC_ZERO_COST_PROCEEDS = Decimal("75")
_SYNTHETIC_ZERO_COST_ASSET = "ZBX"
_SYNTHETIC_ZERO_COST_WALLET = "Demo Spot"
_SYNTHETIC_ZERO_COST_DATE_SOLD = "10/08/2025 14:00"
_SYNTHETIC_ZERO_COST_DATE_ACQUIRED = "01/01/2024 00:00"


def _load_report(*, min_proceeds: Decimal):
    report = load_koinly_crypto_report(
        _FIXTURE_DIR,
        jurisdiction=build_koinly_jurisdiction(zero_basis_review_min_proceeds=min_proceeds)
    )
    assert report is not None, f"load_koinly_crypto_report returned None for synthetic fixture under {_FIXTURE_DIR}"
    return report


def test_synthetic_fixture_contains_zero_basis_scenarios() -> None:
    """Guard against fixture content drift: assert the synthetic CSVs carry the zero-basis scenarios.

    Parses the committed example CSVs and asserts each zero-basis scenario is
    present.
    """
    cg_path = _FIXTURE_DIR / "koinly_2025_capital_gains_report_synth.csv"
    assert cg_path.exists(), f"Zero-basis CG report not found: {cg_path}"
    with cg_path.open(encoding="utf-8") as f:
        content = f.read()
    # Check for FEE, RWD, ZBX
    assert "FEE" in content, "FEE token entry missing from zero-basis synthetic CG report"
    assert "RWD" in content, "RWD token entry missing from zero-basis synthetic CG report"
    assert "ZBX" in content, "ZBX token entry missing from zero-basis synthetic CG report"


class TestZeroBasisMaterialityE2E:
    """Covers the zero-basis materiality rule and the backward-compat escape hatch."""

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
        assert small_rewards, (
            f"Expected at least one zero-cost entry with 0 < proceeds < {_MIN_PROCEEDS_DEFAULT} "
            "in zero-basis fixture, got none"
        )

        wrong_zero_basis = [
            e for e in small_rewards if _ZERO_COST_REASON_MARKER in (e.review_reason or "")
        ]
        assert not wrong_zero_basis, (
            "Zero-cost entries with proceeds below the threshold must not carry the "
            "zero-basis review reason. Offending entries: "
            f"{[(e.asset, e.platform, e.proceeds_eur, e.review_reason) for e in wrong_zero_basis]}"
        )

    def test_larger_zero_cost_disposals_above_threshold_flagged(self) -> None:
        """Zero-cost entries with proceeds >= threshold are flagged with the zero-basis reason.

        Loads the committed synthetic zero-basis fixture. The ZBX disposal
        survives the PT-C-028 |gain| >= 1 EUR materiality filter (gain == 75 EUR)
        and MUST carry the zero-basis review reason.
        """
        report = _load_report(min_proceeds=_MIN_PROCEEDS_DEFAULT)

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
        assert zero_cost, (
            "Expected zero-cost entries with non-zero proceeds in zero-basis fixture, got none"
        )

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
