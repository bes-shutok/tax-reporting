# Plan: Fix CAPITAL GAINS table structure and add visual layout tests

## Review Amendments (2025-06-06)

**Round 1:** Applied fixes from plan review (docs/reviews/2025-06-06-plan-review-2025-06-06-fix-capital-gains-table-structure.md)
**Round 2:** Verified all amendments; review confirmed plan is ready (docs/reviews/2025-06-06-plan-review-2025-06-06-fix-capital-gains-table-structure-r2.md)

Applied fixes from plan review (docs/reviews/2025-06-06-plan-review-2025-06-06-fix-capital-gains-table-structure.md):
- **B1 fix**: `start_column` must stay at 2 (not change to 1). Column 1 is reserved for Country of Source (written by the separate country pass). Changing it to 1 would cause the country pass to overwrite sell_day data.
- **B2 fix**: Must also remove the corresponding empty element from `second_header` so both header arrays have 18 elements.
- **M1 fix**: Corrected cell merge ranges to cols 2-5 (SALE) and cols 6-9 (PURCHASE).
- **M2 fix**: Added explicit sub-tasks for all test classes that need updates (TestWriteIbReportingSheetHeaders, TestWriteIbReportingSheetCurrencyTable, TestWriteIbReportingSheetAutoWidth).
- **M3 fix**: Corrected visual test column assertions.
- **M4 fix**: Added regression test for country/sell_day column separation.

## Gist & Examples

The CAPITAL GAINS table in the Excel output has multiple visual formatting bugs:
1. **2-line gap** between title and headers instead of 1
2. **"Beneficiary" leftover column** at position 1 that shouldn't exist
3. **Column offset by 1** - "Country of Source" is at column 2 but should be column 1
4. **Missing cell merges** - "SALE" and "PURCHASE" headers should span 4 columns each but are written to individual cells
5. **No visual structure tests** - existing tests check individual cell values but don't verify table layout

**Current (buggy) layout:**
```
Row 1: CAPITAL GAINS
Row 2: [blank]
Row 3: [blank]
Row 4: Beneficiary | Country of Source | SALE | [empty] | [empty] | [empty] | PURCHASE | ...
Row 5: [empty] | [empty] | Day | Month | Year | Amount | Day | Month | Year | ...
Row 6+: [data starts at column 2]
```

**Expected (correct) layout:**
```
Row 1: CAPITAL GAINS
Row 2: [blank]
Row 3: Country of Source | SALE (merged cols 2-5) | PURCHASE (merged cols 6-9) | ...
Row 4: [empty] | Day | Month | Year | Amount | Day | Month | Year | Amount | ...
Row 5+: [data starts at column 2]
```

## Review Scope

**Production code; in scope:**
- `src/tax_reporting/application/persisting/ib_sheet.py`

**Tests; in scope:**
- `tests/unit/application/persisting/test_ib_sheet.py`

**Out of scope; reject all review feedback:**
- All other files (crypto_reporting.py, excel_utils.py, etc.), focus on capital gains table only

## Validation Commands

```bash
uv run pytest tests/unit/application/persisting/test_ib_sheet.py::TestWriteIbReportingSheetCapitalGains -x --tb=short
uv run pytest tests/unit/application/persisting/test_ib_sheet.py -x --tb=short
```

### Task 1: Remove "Beneficiary" leftover and fix line gap

Files:
- `src/tax_reporting/application/persisting/ib_sheet.py`

- [x] Remove "Beneficiary" from `first_header` array (line 61) -- first_header goes from 19 to 18 items
- [x] Remove the corresponding first empty-string element from `second_header` (line 82) -- second_header also goes from 19 to 18 items, keeping both arrays paired
- [x] Fix line gap: change `line_number += 2` to `line_number += 1` (line 55) -- leaves only 1 blank row after title
- [x] Update comment on line 55 to reflect the new behavior
- [x] Run → expect GREEN: `uv run pytest tests/unit/application/persisting/test_ib_sheet.py::TestWriteIbReportingSheetCapitalGains -x --tb=short`
- [x] Commit: `fix: remove Beneficiary column and fix capital gains table line gap`

**Implementation notes:**
```python
# Before (line 60-67):
first_header = [
    "Beneficiary",           # <- REMOVE THIS
    "Country of Source",
    "SALE",
    "",
    ...
]

# After:
first_header = [
    "Country of Source",
    "SALE",
    "",
    ...
]

# Before (line 81-83):
second_header = [
    "",       # <- REMOVE THIS (Beneficiary sub-header)
    "",
    "Day ",
    ...
]

# After:
second_header = [
    "",
    "Day ",
    ...
]

# Before (line 55):
line_number += 2  # Leave one blank row after section title

# After:
line_number += 1  # Leave one blank row after section title

# start_column stays at 2 -- column 1 is reserved for Country of Source
# (written by the separate country pass at lines 189-190).
# Changing start_column to 1 would cause the country pass to overwrite sell_day.
```

### Task 2: Add cell merging for SALE and PURCHASE headers

Files:
- `src/tax_reporting/application/persisting/ib_sheet.py`

- [x] Add cell merge for "SALE" across cols 2-5 (SALE at col 2, plus 3 empty sub-headers)
- [x] Add cell merge for "PURCHASE" across cols 6-9 (PURCHASE at col 6, plus 3 empty sub-headers)
- [x] Add cell merge for "WITHOLDING TAX" across cols 10-11 if applicable
- [x] Run → expect GREEN: `uv run pytest tests/unit/application/persisting/test_ib_sheet.py::TestWriteIbReportingSheetCapitalGains -x --tb=short`
- [x] Commit: `fix: add cell merging for SALE and PURCHASE headers in capital gains table`

**Implementation notes:**
Add after line 109 (after second_header loop):
```python
header_row_1 = line_number + 1
# Merge SALE header across 4 columns (cols 2-5: SALE + 3 empty)
worksheet.merge_cells(start_row=header_row_1, start_column=2, end_row=header_row_1, end_column=5)
# Merge PURCHASE header across 4 columns (cols 6-9: PURCHASE + 3 empty)
worksheet.merge_cells(start_row=header_row_1, start_column=6, end_row=header_row_1, end_column=9)
```

Column 1 (Country of Source) is NOT part of the SALE group and must not be included in the merge.

### Task 3: Update existing tests for correct row positions

Files:
- `tests/unit/application/persisting/test_ib_sheet.py`

**TestWriteIbReportingSheetCapitalGains (row numbers shift from 6 to 5, columns unchanged):**
- [x] Update `test_writes_sell_day_for_capital_gain_line`: change `ws.cell(6, 2)` to `ws.cell(5, 2)`
- [x] Update `test_writes_sell_month_name`: change `ws.cell(6, 3)` to `ws.cell(5, 3)`
- [x] Update `test_writes_sell_year`: change `ws.cell(6, 4)` to `ws.cell(5, 4)`
- [x] Update `test_buy_day_for_capital_gain_line`: change `ws.cell(6, 6)` to `ws.cell(5, 6)`
- [x] Update `test_sell_amount_is_formula`: change `ws.cell(6, 5)` to `ws.cell(5, 5)`
- [x] Update `test_buy_amount_is_formula`: change `ws.cell(6, 9)` to `ws.cell(5, 9)`
- [x] Update `test_expense_cell_is_formula`: change `ws.cell(6, 12)` to `ws.cell(5, 12)`
- [x] Update `test_country_of_source_populated`: change `ws.cell(6, 1)` to `ws.cell(5, 1)` and `ws.cell(6, 10)` to `ws.cell(5, 10)`
- [x] Update `test_symbol_and_currency_written`: change `ws.cell(6, 14)` to `ws.cell(5, 14)` and `ws.cell(6, 15)` to `ws.cell(5, 15)`
- [x] Update `test_multiple_lines_write_on_separate_rows`: change `ws.cell(6, 2)` to `ws.cell(5, 2)` and `ws.cell(7, 2)` to `ws.cell(6, 2)`
- [x] Update `test_placeholder_buy_row_has_red_fill`: change `ws.cell(6, 2)` to `ws.cell(5, 2)`

**TestWriteIbReportingSheetHeaders (column positions shift due to Beneficiary removal):**
- [x] Update `test_writes_first_header_row`: change `ws.cell(1, 1) == "Beneficiary"` to `ws.cell(1, 1) == "Country of Source"` and `ws.cell(1, 2) == "Country of Source"` to `ws.cell(1, 2) == "SALE"`
- [x] Update `test_writes_second_header_row`: change `ws.cell(2, 3)` to `ws.cell(2, 2)` (Day moves from col 3 to col 2)

**TestWriteIbReportingSheetCurrencyTable:**
- [x] Update `test_currency_table_present_in_sheet`: change column 21 to column 20 in the iter_rows search (last_column drops from 19 to 18)

**TestWriteIbReportingSheetAutoWidth:**
- [x] Update `test_formula_heavy_columns_get_reasonable_widths`: remap column letters after 1-column shift: M(13) -> L(12) for "Expenses incurred...", Q(17) -> P(16) for "Sale amount", R(18) -> Q(17) for "Buy amount", S(19) -> R(18) for "Expenses amount". Columns E and I stay the same.

- [x] Run → expect GREEN: `uv run pytest tests/unit/application/persisting/test_ib_sheet.py -x --tb=short`
- [x] Commit: `fix: update capital gains tests for correct row and column positions` (done in Task 1)

### Task 4: Add visual structure tests for CAPITAL GAINS table

Files:
- `tests/unit/application/persisting/test_ib_sheet.py` *(new test class)*

- [x] Add `test_section_title_at_row_1` -- given capital gains data, expects "CAPITAL GAINS" at row 1 with bold font
- [x] Add `test_single_blank_row_after_title` -- given capital gains data, expects row 2 to be empty
- [x] Add `test_first_header_row_structure` -- given capital gains data, expects "Country of Source" at col 1, "SALE" at col 2, "PURCHASE" at col 6
- [x] Add `test_second_header_row_structure` -- given capital gains data, expects "Day" at col 2, "Month" at col 3, "Year" at col 4, "Amount" at col 5
- [x] Add `test_sale_header_merged_across_4_columns` -- given capital gains data, expects cells (2-5, header_row_1) are merged
- [x] Add `test_purchase_header_merged_across_4_columns` -- given capital gains data, expects cells (6-9, header_row_1) are merged
- [x] Add `test_data_starts_at_row_5` -- given capital gains data, expects first data row at row 5, col 2 has sell_day value
- [x] Add `test_country_and_sell_day_at_different_columns` -- given capital gains data with known country "US" and sell_day=15, verify ws.cell(5, 1) == "US" and ws.cell(5, 2) == 15 (regression guard against start_column=1)
- [x] Run → expect GREEN: `uv run pytest tests/unit/application/persisting/test_ib_sheet.py::TestWriteIbReportingSheetCapitalGains -x --tb=short`
- [x] Commit: `test: add visual structure tests for CAPITAL GAINS table layout`

**Test implementation pattern:**
```python
def test_section_title_at_row_1(self):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Reporting"
    config = _make_config()
    line = _make_capital_gain_line()
    cc = CurrencyCompany(Currency("USD"), Company("AAPL", country_of_issuance="US"))
    lines: CapitalGainLinesPerCompany = {cc: [line]}
    write_ib_reporting_sheet(ws, config, lines)

    assert ws.cell(1, 1).value == "CAPITAL GAINS"
    assert ws.cell(1, 1).font.bold == True

def test_single_blank_row_after_title(self):
    # ... verify row 2 is empty

def test_country_and_sell_day_at_different_columns(self):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Reporting"
    config = _make_config()
    line = _make_capital_gain_line(sell_date=TradeDate(2025, 6, 15))
    cc = CurrencyCompany(Currency("USD"), Company("AAPL", country_of_issuance="US"))
    lines: CapitalGainLinesPerCompany = {cc: [line]}
    write_ib_reporting_sheet(ws, config, lines)
    # Country at col 1, sell_day at col 2 -- must be different columns
    assert ws.cell(5, 1).value == "US"
    assert ws.cell(5, 2).value == 15
```

### Task 5: Verify country of source pass (no changes expected)

Files:
- `src/tax_reporting/application/persisting/ib_sheet.py`

- [x] Read lines 185-191 to verify country of source pass writes to col 1 (Country of Source) and col 10 (WT Country)
- [x] Since `start_column` stays at 2, the country pass column references (col 1 and col 10) should still be correct after removing the Beneficiary column
- [x] Run → expect GREEN: `uv run pytest tests/unit/application/persisting/test_ib_sheet.py::TestWriteIbReportingSheetCapitalGains -x --tb=short`
- [x] If no changes needed, skip commit for this task

**Note:** After removing Beneficiary from both headers, "Country of Source" is now at col 1 and "WITHOLDING TAX/Country" is at col 10. The country pass already writes to these exact columns. No code change is expected, but verification is required.

### Task 6: Final validation

Files:
- All modified files

- [x] Run full test suite: `uv run pytest -x --tb=short`
- [x] Run integration tests: `uv run pytest tests/integration/test_excel_generation_integration.py -x --tb=short`
- [x] Generate Excel output and visually verify table structure (manual check)
- [x] Commit: `fix: final validation for capital gains table structure fix`

## Design Considerations

**Why not extract to a new module:**
The table rendering logic is appropriately placed in `ib_sheet.py` (the IB sheet writer). Extracting header structure to a separate module would over-engineer this fix. The fix is localized to the capital gains section within `write_ib_reporting_sheet()`.

**No extension to crypto_reporting.py:**
This plan modifies only `ib_sheet.py` and its tests, avoiding the god class (crypto_reporting.py at 3011 lines). No new domain types or application services are created.

**Cell merge pattern:**
Use `worksheet.merge_cells(start_row, start_column, end_row, end_column)` from openpyxl to merge header cells. The merged cell takes the value from the top-left cell in the range.

**Test coverage strategy:**
1. Fix existing tests for correct column positions
2. Add new tests specifically for visual layout (merged cells, row positions, blank rows)
3. No tests for dividend section (out of scope for this fix)
