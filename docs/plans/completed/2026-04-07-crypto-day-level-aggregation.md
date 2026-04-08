# Switch Crypto Capital Gains Aggregation to Day-Level Precision

## Overview

Change the crypto capital gains aggregation from minute-level to day-level precision, matching the official Anexo J Quadro 9.4 form which only captures dates as Ano/Mes/Dia (PT-C-020). This reduces output rows by merging same-day disposals that differ only by time-of-day.

## Context

- Files involved:
  - `src/shares_reporting/application/crypto_reporting.py` — `_format_datetime()`, `_aggregate_capital_entries()`, `_parse_capital_gains_file()`, `_parse_income_file()`
  - `tests/unit/application/test_crypto_reporting.py` — 17 tests referencing `_aggregate_capital_entries`, 1 referencing `_format_datetime`
  - `tests/integration/test_excel_generation_integration.py` — integration tests with hardcoded timestamp strings
  - `docs/domain/crypto_rules.md` — PT-C-027 update
  - `docs/domain/crypto_implementation_guidelines.md` — aggregation invariant docs
- Related patterns: The existing `_aggregate_capital_entries` already groups by `(disposal_date, asset, platform, holding_period)` — we just change `disposal_date` from `"YYYY-MM-DD HH:MM:SS"` to `"YYYY-MM-DD"`.
- Dependencies: None external.
- Key constraint: `acquisition_date` is also formatted by `_format_datetime` and used in the aggregation output's `min()` calculation. It should also become day-level per PT-C-020 (the form has no time field for acquisition either). Reward income dates should also switch to day-level.

## Development Approach

- Testing approach: TDD — write/update failing tests first, then change production code.
- Complete each task fully before moving to the next.
- **CRITICAL: every task MUST include new/updated tests**
- **CRITICAL: all tests must pass before starting next task**

## Implementation Steps

### Task 1: Update `_format_datetime()` and its direct tests

**Files:**
- Modify: `src/shares_reporting/application/crypto_reporting.py`
- Modify: `tests/unit/application/test_crypto_reporting.py`

- [x] Change `_format_datetime()` to return `"%Y-%m-%d"` (date only, no time-of-day).
- [x] Add a dedicated unit test `test_format_datetime_returns_date_only` that asserts `_format_datetime(datetime(2025, 1, 13, 13, 1, 0, tzinfo=UTC)) == "2025-01-13"`.
- [x] Add test `test_format_datetime_epoch_sentinel_returns_1970_01_01` confirming the epoch sentinel for missing dates still formats correctly.
- [x] Run: `uv run pytest tests/unit/application/test_crypto_reporting.py -k "format_datetime" -v`

### Task 2: Update `_aggregate_capital_entries()` tests for day-level grouping

**Files:**
- Modify: `tests/unit/application/test_crypto_reporting.py`

- [x] Update `test_aggregate_different_timestamps_stay_separate` — change the two entries to use different dates (not just different times on the same day) so they remain separate; add a new assertion that same-day-different-time entries DO collapse.
- [x] Update `test_aggregate_different_wallet_aliases_with_different_timestamps_stay_separate` — use different calendar dates instead of different times.
- [x] Update `test_aggregate_same_timestamp_collapses_to_one_row` — confirm entries with identical day-level dates still collapse (no behavior change expected since the input dates already match at day level in this test).
- [x] Add `test_aggregate_same_day_different_times_collapses_to_one_row` — two entries with disposal dates `"2025-03-15 09:00:00"` and `"2025-03-15 14:30:00"` must now collapse into one row after the format change.
- [x] Update `test_same_timestamp_different_holding_period_stays_split` — use same-date entries (time-of-day is no longer in the string, but the intent — same disposal, different holding period — is unchanged).
- [x] Update `test_same_disposal_date_allowed_when_other_grouping_dims_differ` — update any hardcoded timestamp strings to date-only format.
- [x] Update all other aggregation tests that construct `CryptoCapitalGainEntry` objects with `"YYYY-MM-DD HH:MM:SS"` formatted `disposal_date`/`acquisition_date` to use `"YYYY-MM-DD"` format instead.
- [x] Update `test_aggregate_never_emits_duplicate_keys` to use date-only formatted keys.
- [x] Update `test_real_koinly_fixture_has_no_duplicate_aggregation_keys` — the assertion on key format should expect `"YYYY-MM-DD"` not `"YYYY-MM-DD HH:MM:SS"`.
- [x] Run: `uv run pytest tests/unit/application/test_crypto_reporting.py -k "aggregate or grouping or format_datetime" -v`

### Task 3: Update integration tests

**Files:**
- Modify: `tests/integration/test_excel_generation_integration.py`

- [x] Update `test_crypto_sheet_capital_headers_distinguish_disposal_vs_acquisition_date` — change the `CryptoCapitalGainEntry` disposal_date from `"2025-01-13 13:01:00"` to `"2025-01-13"` and acquisition_date from `"2024-07-27 11:03:00"` to `"2024-07-27"`. Update the data-row assertion to match `"2025-01-13"` and `"2024-07-27"`.
- [x] Search for all other integration tests that construct `CryptoCapitalGainEntry` or `CryptoRewardIncomeEntry` with timestamp-format dates and update to date-only format.
- [x] Run: `uv run pytest tests/integration/test_excel_generation_integration.py -k "crypto" -v`

### Task 4: Update `transaction_date` passing and verify end-to-end

**Files:**
- Modify: `src/shares_reporting/application/crypto_reporting.py` (already modified in Task 1)

- [x] Verify that `_parse_capital_gains_file()` still passes the formatted `disposal_date` (now `"YYYY-MM-DD"`) to `resolve_operator_origin()` via `transaction_date`. Confirm `_parse_transaction_date()` accepts `"YYYY-MM-DD"` format (it already does — this is a pre-existing path).
- [x] Verify that `_parse_income_file()` still passes the formatted `date` (now `"YYYY-MM-DD"`) to `resolve_operator_origin()`. Confirm this format is accepted.
- [x] Run full unit test suite: `uv run pytest tests/unit/ -v`
- [x] Run full integration test suite: `uv run pytest tests/integration/ -v`
- [x] Run full e2e test suite: `uv run pytest tests/end_to_end/ -v`

### Task 5: Verify acceptance criteria

- [x] Run full test suite: `uv run pytest`
- [x] Run linter: `uv run ruff check src/ tests/`
- [x] Verify test coverage meets 80%+: `uv run pytest --cov=src --cov-report=term-missing`

### Task 6: Update documentation

- [x] Update PT-C-027 in `docs/domain/crypto_rules.md` — change "uses Koinly's minute-level timestamps internally for grouping" to "uses day-level dates internally for grouping, matching the Anexo J form's Ano/Mes/Dia precision (PT-C-020)".
- [x] Update `docs/domain/crypto_implementation_guidelines.md` — in the "Aggregation Grouping Invariants" section, update example timestamps from `"2024-07-27 11:03:00"` to `"2024-07-27"` format. Update the diagnostic guidance to reflect day-level keys.
- [x] Move this plan to `docs/plans/completed/`.
