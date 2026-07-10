"""Opt-in real-data end-to-end smoke for the Phase D production flip.

This module implements Phase D Task 10 (per
``docs/history/plans/2026-07-08-th-tx-view-phase-d.md``). It is the
release-gate test that proves the Phase D flip is behavior-preserving on
real Koinly data: when the opt-in environment variable
``TAX_REPORTING_PHASE_D_REAL_DATA_DIR`` points to a Koinly directory, the
test runs the full crypto pipeline twice - once with all six
``treatment_*_via_resolver`` flags ON (resolver authoritative), once with
all six OFF (legacy adapters) - and asserts the resulting reports agree
on row count and aggregate totals.

The test is SKIPPED by default (Invariant 6: opt-in personal-data tests
must not fail when the data is absent). It activates only when the
environment variable is set to a non-empty path. The committed expected-
diff file ``tests/end_to_end/phase_d_expected_diff.txt`` is the escape
hatch for documented acceptable divergences (empty body means byte-
identical expected).

Per CLAUDE.md's crypto-test rule and Family-G (verify the real thing):
this test NEVER reads gitignored data when the env var is absent. The
env var is the explicit consent mechanism.
"""

from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path

import pytest

from tax_reporting.application.crypto.entities import CryptoTaxReport
from tax_reporting.application.crypto_reporting import load_koinly_crypto_report
from tests.conftest import build_koinly_jurisdiction

pytestmark = pytest.mark.e2e

_ENV_VAR = "TAX_REPORTING_PHASE_D_REAL_DATA_DIR"

# The six per-treatment resolver flags (Phase D Task 2). Toggling all six
# OFF at once restores the full legacy identification path; ON delegates
# every treatment to ``resolve_treatment``.
_TREATMENT_FLAGS: tuple[str, ...] = (
    "treatment_spot_disposal_via_resolver",
    "treatment_payment_via_resolver",
    "treatment_loan_repayment_via_resolver",
    "treatment_derivatives_close_via_resolver",
    "treatment_reward_airdrop_lp_via_resolver",
    "treatment_other_via_resolver",
)

_EXPECTED_DIFF_FILE = Path(__file__).parent / "phase_d_expected_diff.txt"


def _resolve_koinly_dir() -> Path | None:
    """Return the opt-in Koinly directory, or None when the env var is unset/empty."""
    raw = os.environ.get(_ENV_VAR, "").strip()
    if not raw:
        return None
    return Path(raw)


def _build_jurisdiction(*, flags_on: bool) -> object:
    """Build a PT/2025 jurisdiction with the six treatment flags all ON or all OFF."""
    overrides: dict[str, object] = dict.fromkeys(_TREATMENT_FLAGS, flags_on)
    return build_koinly_jurisdiction(**overrides)


def _load_expected_diffs() -> set[str]:
    """Parse the committed expected-diff file into a set of non-comment lines.

    Lines starting with ``#`` and blank lines are ignored. The resulting set
    is the allow-list of DOCUMENTED acceptable divergences; an empty set
    means byte-identical output is expected (the default committed state).
    """
    if not _EXPECTED_DIFF_FILE.exists():
        return set()
    lines: set[str] = set()
    for raw in _EXPECTED_DIFF_FILE.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        lines.add(stripped)
    return lines


def _summarize(report: CryptoTaxReport) -> dict[str, object]:
    """Reduce a CryptoTaxReport to a row-count + aggregate-totals summary.

    The summary is the comparison key: two reports with identical summaries
    are behaviorally equivalent at the level Phase D's flip must preserve.
    Any divergence surfaces as a mismatched value in the returned dict.
    """
    capital = list(report.capital_entries)
    reward = list(report.reward_entries)
    derivatives = list(report.derivatives_entries)
    review = list(report.review_entries)
    loan = list(report.loan_activity)
    skipped = list(report.skipped_zero_value_tokens)
    zero = Decimal("0")
    return {
        "capital_rows": len(capital),
        "capital_proceeds_eur": sum((e.proceeds_eur for e in capital), start=zero),
        "capital_gain_loss_eur": sum((e.gain_loss_eur for e in capital), start=zero),
        "reward_rows": len(reward),
        "reward_value_eur": sum((e.value_eur for e in reward), start=zero),
        "derivatives_rows": len(derivatives),
        "derivatives_pnl_eur": sum((e.pnl_eur for e in derivatives), start=zero),
        "review_rows": len(review),
        "loan_activity_rows": len(loan),
        "skipped_zero_value_rows": len(skipped),
    }


def _format_diffs(on: dict[str, object], off: dict[str, object]) -> list[str]:
    """Return a list of human-readable divergence lines for mismatched keys."""
    diffs: list[str] = []
    for key in sorted(set(on) | set(off)):
        if on.get(key) != off.get(key):
            diffs.append(f"{key}: flags_on={on.get(key)!r} flags_off={off.get(key)!r}")
    return diffs


class TestPhaseDRealDataSmoke:
    """Opt-in real-data end-to-end smoke for the Phase D flip."""

    def test_skipped_without_env_var(self) -> None:
        """Without ``TAX_REPORTING_PHASE_D_REAL_DATA_DIR`` the smoke is SKIPPED.

        Pins Invariant 6: personal-data tests must be opt-in and must not
        fail when the data is absent. The skip reason names the env var so
        the user knows how to activate the smoke.
        """
        koinly_dir = _resolve_koinly_dir()
        if koinly_dir is None:
            pytest.skip(f"set {_ENV_VAR} to activate")
        # When the env var IS set, this test delegates to the equivalence
        # check below; we re-use the same body so the activation path is
        # exercised through whichever test the runner selects.
        self._assert_equivalence(koinly_dir)

    def test_all_flags_on_matches_all_flags_off(self) -> None:
        """All six flags ON produces a report whose row counts and aggregate totals match all flags OFF.

        Pins the Phase D equivalence guarantee: the resolver-authoritative
        path (all six ``treatment_*_via_resolver=True``) must agree with
        the full legacy-adapter path (all six False) on every output list
        length and every aggregate total. Any diff must be DOCUMENTED in
        ``tests/end_to_end/phase_d_expected_diff.txt``; undocumented
        divergences fail the test.
        """
        koinly_dir = _resolve_koinly_dir()
        if koinly_dir is None:
            pytest.skip(f"set {_ENV_VAR} to activate")
        self._assert_equivalence(koinly_dir)

    def _assert_equivalence(self, koinly_dir: Path) -> None:
        """Run the pipeline both ways and compare summaries; honor expected diffs."""
        if not koinly_dir.exists() or not koinly_dir.is_dir():
            pytest.fail(
                f"{_ENV_VAR}={koinly_dir} does not exist or is not a directory; "
                "unset the env var to skip, or point it at a valid Koinly export directory."
            )

        report_on = load_koinly_crypto_report(koinly_dir, jurisdiction=_build_jurisdiction(flags_on=True))
        report_off = load_koinly_crypto_report(koinly_dir, jurisdiction=_build_jurisdiction(flags_off=False))
        assert report_on is not None, (
            f"load_koinly_crypto_report returned None with all flags ON for {koinly_dir}; "
            "the directory must contain the required Koinly CSVs."
        )
        assert report_off is not None, (
            f"load_koinly_crypto_report returned None with all flags OFF for {koinly_dir}; "
            "the directory must contain the required Koinly CSVs."
        )

        on_summary = _summarize(report_on)
        off_summary = _summarize(report_off)
        if on_summary == off_summary:
            return

        actual_diffs = _format_diffs(on_summary, off_summary)
        expected_diffs = _load_expected_diffs()
        if expected_diffs:
            undocumented = [d for d in actual_diffs if d not in expected_diffs]
            if not undocumented:
                # Every observed divergence is documented in the allow-list.
                return
            failure_lines = undocumented
        else:
            failure_lines = actual_diffs
        pytest.fail(
            "Phase D real-data smoke detected undocumented divergence(s) between "
            "all-flags-ON and all-flags-OFF:\n  - "
            + "\n  - ".join(failure_lines)
            + "\nIf the divergence is acceptable, document it in "
            f"{_EXPECTED_DIFF_FILE} (one line per divergence, format: "
            "<asset> <flag-state> <description>)."
        )
