"""On-chain TH validation harness (PD-009/PD-010).

Read-only instrument that runs the PRODUCTION on-chain path (registry load ->
reader -> processor -> adapter projection), projects it against the real
Koinly transaction-history baseline, and applies the PD-010
semantic-equivalence rules. Divergences are grouped into PII-free discrepancy
clusters resolved via an append-only, user-owned dispositions file; the
acceptance gate for flipping ``ON_CHAIN_TH_WALLETS`` is a zero-exit run on the
2025 validation dataset (the only Koinly baseline that will ever exist).

Submodules (all landed with plan Tasks 2-6):

- ``comparator`` (Task 2): per-``tx_hash`` semantic equivalence - the display
  tolerance, the fixed compatibility table, and the gas-surface comparison.
- ``clustering`` (Task 3), ``dispositions`` (Task 4), ``artifacts`` (Task 5),
  and ``runner`` (Task 6): signature clustering, the append-only dispositions
  feedback loop, the regenerated artifacts, and the end-to-end validation
  runner behind ``--validate-on-chain-th``.

Plan: ``docs/history/plans/2026-08-18-on-chain-validation-harness.md``.
"""

from tax_reporting.application.on_chain_validation.comparator import (
    DISPLAY_TOLERANCE_PER_ROW,
    EVENT_COMPATIBILITY,
    AmountMismatch,
    ComparisonResult,
    KoinlyFeeSurface,
    Presence,
    Surface,
    ThComparisonRecord,
    TypeMismatch,
    compare_projection,
)

__all__ = [
    "DISPLAY_TOLERANCE_PER_ROW",
    "EVENT_COMPATIBILITY",
    "AmountMismatch",
    "ComparisonResult",
    "KoinlyFeeSurface",
    "Presence",
    "Surface",
    "ThComparisonRecord",
    "TypeMismatch",
    "compare_projection",
]
