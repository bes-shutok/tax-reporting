# Plan: Fix column widths and restructure persisting layer

## Context
The Excel report has excessively wide columns caused by auto-width measuring raw formula text instead of rendered values. Additionally, the persisting module (`persisting.py`, 891 lines) mixes IB-specific and Koinly-specific sheet generation in two monolithic functions (357 and 354 lines). The user wants: (1) fix auto-width to skip formula cells, (2) split the single Crypto tab into three named tabs — Crypto Gains, Crypto Rewards, Crypto Reconciliation, (3) full DDD refactor extracting source-specific writers, (4) TDD approach.

## Validation Commands
```bash
uv run pytest
uv run pytest tests/unit/application/persisting/ -v
uv run tax-reporting  # then open result.xlsx in Numbers
```

### Task 1: Extract shared `auto_column_width()` with TDD

Files:
- `src/shares_reporting/application/persisting/excel_utils.py` (new)
- `tests/unit/application/persisting/test_excel_utils.py` (new)

- [x] Write failing tests: measures text/number cells, skips formula cells (`data_type == "f"`), handles empty columns, adds +2 padding
- [x] Implement `auto_column_width(worksheet)` — extract existing auto-width logic from `persisting.py` lines 412–425 and 823–832, with formula-cell skip
- [x] Also move `safe_remove_file()` into `excel_utils.py`

### Task 2: Extract `export_rollover_file()` with relocated tests

Files:
- `src/shares_reporting/application/persisting/rollover.py` (new)
- `tests/unit/application/persisting/test_rollover.py` (new — move from `test_persisting.py`)

- [x] Move `export_rollover_file()` from `persisting.py` lines 49–117 into `rollover.py`
- [x] Move the 2 existing rollover tests from `tests/unit/application/test_persisting.py` into `test_rollover.py`
- [x] Verify tests pass

### Task 3: Extract `write_ib_reporting_sheet()` with TDD

Files:
- `src/shares_reporting/application/persisting/ib_sheet.py` (new)
- `tests/unit/application/persisting/test_ib_sheet.py` (new)

- [x] Write failing tests: header rows, capital gain data rows, formula cells in expected columns, dividend section, auto-width called
- [x] Extract IB sheet logic from `generate_tax_report()` lines 152–425 (headers + capital gains loop + dividends + auto-width)
- [x] Move `create_currency_table()` into `ib_sheet.py` (only IB consumer)
- [x] Verify tests pass

### Task 4: Extract `write_crypto_gains_sheet()` with TDD

Files:
- `src/shares_reporting/application/persisting/crypto_gains_sheet.py` (new)
- `tests/unit/application/persisting/test_crypto_gains_sheet.py` (new)

- [x] Write failing tests: sheet named "Crypto Gains", title/tax year/PDF summary, capital gain entries in 17 columns, statistics section, auto-width
- [x] Extract sections 1 + 1b from `add_crypto_report_sheet()` lines 479–582
- [x] Verify tests pass

### Task 5: Extract `write_crypto_rewards_sheet()` with TDD

Files:
- `src/shares_reporting/application/persisting/crypto_rewards_sheet.py` (new)
- `tests/unit/application/persisting/test_crypto_rewards_sheet.py` (new)

- [x] Write failing tests: sheet named "Crypto Rewards", IRS filing summary, support detail for taxable-now and deferred, classification reconciliation, empty-data handling
- [x] Extract sections 2 + 2a2 + 2b + 2c from `add_crypto_report_sheet()` lines 584–760
- [x] Verify tests pass

### Task 6: Extract `write_crypto_reconciliation_sheet()` with TDD

Files:
- `src/shares_reporting/application/persisting/crypto_reconciliation_sheet.py` (new)
- `tests/unit/application/persisting/test_crypto_reconciliation_sheet.py` (new)

- [x] Write failing tests: sheet named "Crypto Reconciliation", key-value reconciliation rows, opening/closing holdings, skipped tokens table
- [x] Extract sections 3 + 4 from `add_crypto_report_sheet()` lines 762–821
- [x] Verify tests pass

### Task 7: Create orchestrator and update imports

Files:
- `src/shares_reporting/application/persisting/workbook_builder.py` (new)
- `src/shares_reporting/application/persisting/__init__.py` (new)
- `src/shares_reporting/main.py` (modify imports)
- All test files importing from `persisting` (update imports)

- [x] `workbook_builder.py` — `generate_tax_report()` becomes thin orchestrator: create workbook → write IB sheet → write crypto sheets → save → cleanup
- [x] `__init__.py` — re-exports `generate_tax_report`, `export_rollover_file`
- [x] Update `main.py` imports
- [x] Update all test imports (`from persisting import ...` → `from persisting import ...` same path, package resolves)
- [x] Run full test suite — all pass

### Task 8: Delete old `persisting.py`

Files:
- `src/shares_reporting/application/persisting.py` (delete)

- [x] Remove single file once package is complete and all tests pass
- [x] Final full test suite run
- [x] Generate report and verify in Numbers: Reporting tab columns fit content, three separate crypto tabs with correct names and sections
