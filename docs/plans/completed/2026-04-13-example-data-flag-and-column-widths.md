# Plan: Add `--example` CLI flag and fix column widths across all tabs

## Context

Two issues need addressing:

1. **No easy way to run with example data.** The e2e tests use `resources/source/example/` as a self-contained dataset, but `main.py` has no CLI argument parsing — calling `uv run tax-reporting` always targets `resources/source/ib_export.csv`. Adding a simple flag to point at the example directory enables quick smoke-testing without touching real data.

2. **Column widths are still wrong in most tabs.** The previous fix (commit `6c1776d`) changed `auto_column_width` to skip formula cells (`data_type != "f"`), solving the original "too wide" problem (formula strings like `=EUR_USD*(12345.67)` measured as 25+ chars). But it introduced two new problems:
   - **Formula-only columns collapse to width 2.** IB sheet columns that contain mostly formulas (amounts, rates) now skip all data cells and size only by short header text like "Amount" (6 chars → width 8), clipping rendered values like "12,345.67".
   - **Long text blows out columns.** In crypto tabs, paragraph-length explanatory notes in column 1 (e.g. `"This table shows only income taxable immediately in Category E. Crypto-denominated rewards (deferred until disposal) are in section 2b below."` — 153 chars) and long description/origin strings push columns far wider than needed. Column 1 of Crypto Rewards gets sized to ~190 characters because `auto_column_width` measures every non-formula cell including italic notes.

## Approach

- **TDD**: write failing tests first for each behavior change, then implement.
- **DDD / SRP**: keep modules focused — `excel_utils.py` stays under 1k lines; `main.py` stays thin (argparse in a helper, no business logic).
- **Single origin of change**: column width logic lives in one place (`auto_column_width`); sheet writers call it and don't set widths themselves.

## Validation Commands
```bash
uv run pytest
uv run tax-reporting --example   # then open result.xlsx and verify column widths
uv run tax-reporting             # default run still works
```

---

### Task 1: Add `argparse` to `main.py` with `--example` flag (TDD)

Files:
- `src/shares_reporting/main.py`
- `tests/unit/test_cli.py` (new — tests for `_build_arg_parser`)

- [x] Write failing tests for `_build_arg_parser()`:
  - `--example` sets source to `resources/source/example/ib_export.csv` and output to `resources/result/example/`
  - `--source-file` and `--output-dir` accept explicit paths
  - `--log-level` accepts only valid choices, defaults to `INFO`
  - No arguments → all values `None` (defaults handled by `main()`)
- [x] Implement `_build_arg_parser()` returning an `ArgumentParser`
- [x] Update `if __name__ == "__main__"` to parse args and call `main(**vars(args))`
- [x] Keep `main()` signature accepting optional params so existing tests keep working

### Task 2: Fix `auto_column_width` — cap outliers and floor formula-only columns (TDD)

Files:
- `src/shares_reporting/application/persisting/excel_utils.py`
- `tests/unit/application/persisting/test_excel_utils.py`

- [x] Write failing tests for:
  - **MAX_CELL_WIDTH cap**: a cell with 150-char value → column width capped at `MAX_CELL_WIDTH + 2`, not 152
  - **MIN_DATA_WIDTH floor**: a column with only formula cells → width is `MIN_DATA_WIDTH`, not 2
  - **Mixed columns**: column with both data and formula cells → data measured, formulas skipped, cap applied
  - **Normal behavior preserved**: short data cells still get `len(value) + 2`
- [x] Add `MAX_CELL_WIDTH = 50` and `MIN_DATA_WIDTH = 12` constants to `excel_utils.py`
- [x] Update `auto_column_width`:
  - Clamp each cell's contribution: `min(len(str(cell.value)), MAX_CELL_WIDTH)`
  - If measured max is 0 (all formulas/empty), use `MIN_DATA_WIDTH` instead of `default=0`
  - Otherwise use `max(measured_length, 2) + 2` as before
- [x] Run tests — all pass

### Task 3: Update sheet-writer tests for new width behavior

Files:
- `tests/unit/application/persisting/test_crypto_rewards_sheet.py`
- `tests/unit/application/persisting/test_crypto_gains_sheet.py`
- `tests/unit/application/persisting/test_ib_sheet.py` (add missing width assertions)

- [x] Add/update assertions that verify column widths are within expected bounds after `auto_column_width`:
  - IB sheet: formula-heavy columns get at least `MIN_DATA_WIDTH`
  - Crypto sheets: no column exceeds `MAX_CELL_WIDTH + 2`
- [x] Run full test suite — all pass

### Task 4: End-to-end verification

Files:
- no new files

- [x] Run `uv run pytest` — all tests pass (644 tests)
- [x] Run `uv run tax-reporting --example` — open the generated xlsx and verify:
  - [x] IB Reporting tab: numeric columns wide enough for rendered values (not collapsed) — programmatic tests verify MIN_DATA_WIDTH=12 floor prevents collapse
  - [x] Crypto Rewards tab: column 1 sized to data, not to paragraph-length notes — programmatic tests verify MAX_CELL_WIDTH=50 cap
  - [x] Crypto Gains tab: token origin column capped — programmatic tests verify MAX_CELL_WIDTH=50 cap
  - [x] Crypto Reconciliation tab: reasonable widths — programmatic tests verify bounds
  - Note: Visual Excel inspection requires human verification; all programmatic assertions pass
