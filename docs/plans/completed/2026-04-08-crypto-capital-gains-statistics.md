# Plan: Crypto Capital Gains Statistics Section

## Overview

Add a dedicated "CAPITAL GAINS STATISTICS" section to the Crypto Excel sheet, with per-holding-period breakdowns (short-term, long-term, mixed, unknown) showing count, cost total, proceeds total, and gain/loss total, plus a grand total row. This mirrors the existing "REWARDS CLASSIFICATION RECONCILIATION" section pattern.

## Context

- Files involved:
  - `src/shares_reporting/application/crypto_reporting.py` - data models and computation
  - `src/shares_reporting/application/persisting.py` - Excel output
  - `tests/unit/application/test_crypto_reporting.py` - unit tests
  - `tests/integration/test_excel_generation_integration.py` - integration tests
- Related patterns: rewards Section 2c "REWARDS CLASSIFICATION RECONCILIATION" in `persisting.py`; `CryptoReconciliationSummary` dataclass
- The existing `CryptoReconciliationSummary` already has row counts per holding period and overall EUR totals, but no per-period EUR totals
- DDD alignment: stats value objects will be frozen dataclasses with a `from_entries()` factory method (factory on the aggregate type, pure construction on the per-period type), following the project convention of `frozen=True` dataclasses for immutable value-semantic types
- All crypto reporting types (`CryptoReconciliationSummary`, `HoldingsSnapshot`, `AggregatedRewardIncomeEntry`) live in the application layer; stats classes follow the same placement

## Development Approach

- Testing approach: TDD (write failing tests first, then implement to make them pass)
- Complete each task fully before moving to the next
- CRITICAL: every task MUST include tests written BEFORE implementation
- CRITICAL: all tests must pass before starting next task

## Validation Commands

```bash
uv run pytest tests/unit/application/test_crypto_reporting.py
uv run pytest tests/unit/
uv run pytest tests/integration/test_excel_generation_integration.py
uv run pytest
uv run ruff check src/ tests/
```

## Implementation Steps

### Task 1: Add CapitalGainPeriodStats value object (TDD)

Files:
- Modify: `src/shares_reporting/application/crypto_reporting.py`
- Modify: `tests/unit/application/test_crypto_reporting.py`

- [x] Write failing test: `test_capital_gain_period_stats_zero()` verifying construction with zero values and correct property access
- [x] Write failing test: `test_capital_gain_period_stats_from_entries()` verifying that `from_entries()` correctly sums cost, proceeds, gain/loss and counts entries for a list of `CryptoCapitalGainEntry` instances with the same holding period
- [x] Write failing test: `test_capital_gain_period_stats_from_empty_entries()` verifying zero-stats from empty list
- [x] Implement `CapitalGainPeriodStats` frozen dataclass with fields: `count: int`, `cost_total_eur: Decimal`, `proceeds_total_eur: Decimal`, `gain_loss_total_eur: Decimal`, plus a `from_entries(entries: list[CryptoCapitalGainEntry]) -> CapitalGainPeriodStats` classmethod
- [x] Run `uv run pytest tests/unit/application/test_crypto_reporting.py` - all period-stats tests must pass

### Task 2: Add CryptoCapitalGainStats aggregate value object and compute function (TDD)

Files:
- Modify: `src/shares_reporting/application/crypto_reporting.py`
- Modify: `tests/unit/application/test_crypto_reporting.py`

- [x] Write failing test: `test_compute_capital_gain_stats_all_periods()` verifying stats computed across all four holding periods with correct per-period and grand-total values
- [x] Write failing test: `test_compute_capital_gain_stats_single_period()` verifying only one period has non-zero stats, others are zero
- [x] Write failing test: `test_compute_capital_gain_stats_empty()` verifying all periods and grand total are zero-stats
- [x] Write failing test: `test_compute_capital_gain_stats_mixed_gains()` verifying correct aggregation of positive and negative gains within a period
- [x] Implement `CryptoCapitalGainStats` frozen dataclass with fields: `short_term: CapitalGainPeriodStats`, `long_term: CapitalGainPeriodStats`, `mixed: CapitalGainPeriodStats`, `unknown: CapitalGainPeriodStats`, `grand_total: CapitalGainPeriodStats`, plus a `from_entries(entries: list[CryptoCapitalGainEntry]) -> CryptoCapitalGainStats` classmethod that groups by `holding_period` and delegates to `CapitalGainPeriodStats.from_entries()`
- [x] Run `uv run pytest tests/unit/application/test_crypto_reporting.py` - all stats tests must pass

### Task 3: Integrate stats into CryptoTaxReport (TDD)

Files:
- Modify: `src/shares_reporting/application/crypto_reporting.py`
- Modify: `tests/unit/application/test_crypto_reporting.py`

- [x] Write failing test: `test_crypto_tax_report_includes_capital_gain_stats()` verifying that `CryptoTaxReport` has a `capital_gain_stats` field of type `CryptoCapitalGainStats`
- [x] Add `capital_gain_stats: CryptoCapitalGainStats` field to `CryptoTaxReport` dataclass
- [x] In `load_koinly_crypto_report()`, call `CryptoCapitalGainStats.from_entries()` after aggregation and immaterial filtering, pass result to `CryptoTaxReport` constructor
- [x] Update all existing `CryptoTaxReport` construction sites to include the new field
- [x] Update existing tests that construct `CryptoTaxReport` to include the new field with appropriate defaults
- [x] Run `uv run pytest tests/unit/` - must pass

### Task 4: Add CAPITAL GAINS STATISTICS Excel section (TDD)

Files:
- Modify: `src/shares_reporting/application/persisting.py`
- Modify: `tests/integration/test_excel_generation_integration.py`

- [x] Write failing test: `test_crypto_sheet_contains_capital_gains_statistics_header()` verifying the "CAPITAL GAINS STATISTICS" section header appears in the crypto sheet after the capital gains detail rows
- [x] Write failing test: `test_crypto_sheet_capital_gains_statistics_values()` verifying per-period rows (Short-term, Long-term, Mixed, Unknown) and Grand Total row contain correct values
- [x] Implement the "CAPITAL GAINS STATISTICS" section in `persisting.py`, positioned between capital gains detail rows (Section 1) and rewards section (Section 2)
- [x] Render table with columns: Holding Period, Count, Cost Total (EUR), Proceeds Total (EUR), Gain/Loss Total (EUR)
- [x] Add rows for each holding period (zero-stats for absent periods) and Grand Total, following the same formatting style as the rewards classification reconciliation section
- [x] Run `uv run pytest tests/integration/test_excel_generation_integration.py` - must pass

### Task 5: Verify acceptance criteria

- [x] Run `uv run pytest` - all tests pass (462 passed)
- [x] Run `uv run ruff check src/ tests/` - no lint errors
- [x] Verify test coverage for new code meets 80%+ (crypto_reporting.py: 92%, overall: 85%)

### Task 6: Update documentation

- [x] Update CLAUDE.md and AGENTS.md if internal patterns changed (no updates needed - all new code follows existing patterns)
- [x] Move this plan to `docs/plans/completed/`
