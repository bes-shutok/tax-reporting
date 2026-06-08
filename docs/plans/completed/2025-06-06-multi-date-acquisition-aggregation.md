# Plan: Multi-Date Acquisition Aggregation Enhancement

Related rule: PT-C-027 (aggregation by disposal date, asset, platform, holding_period)

Plan review: docs/reviews/2025-06-06-plan-review-multi-date-acquisition-r2.md (Round 2 — all blockers resolved)

## Gist & Examples

**What changes:** When multiple FIFO lots with different acquisition dates are aggregated into one capital gain line (per Portuguese tax requirements), the system will now (1) show all acquisition dates in the Notes field, and (2) apply blue color coding to visually distinguish these rows from single-date rows.

**Why needed:** Currently, when a sale consumes multiple lots bought on different dates, the aggregated line shows only the earliest acquisition date but the full summed quantity. This creates confusion during manual review — for example, seeing "Acquired: 2024-04-13" with "Quantity: 378.7092 SEI" when only 189.7173 SEI were bought on that date. The financial totals (cost, proceeds, gain) are correct, but the presentation is misleading. Portuguese tax law requires ONE acquisition date per line (Quadro 9.4 has a single "Data de aquisição" field), so we must keep one row but make the multi-lot nature explicit.

**Example input (FIFO lots from Koinly):**
```
Lot 1: acquired 2024-04-13, 189.7173 SEI, sold 2025-06-14
Lot 2: acquired 2024-04-19, 188.9919 SEI, sold 2025-06-14
```

**Example output (current):**
```
| Disposal Date | Acquisition Date | Asset     | Quantity   | Notes              |
|--------------|------------------|-----------|------------|--------------------|
| 2025-06-14   | 2024-04-13      | SEI       | 378.7092   | (empty)            |
```
*Confusing: the quantity doesn't match what was bought on 2024-04-13.*

**Example output (after fix):**
```
| Disposal Date | Acquisition Date | Asset     | Quantity   | Notes                                |
|--------------|------------------|-----------|------------|--------------------------------------|
| 2025-06-14   | 2024-04-13      | SEI       | 378.7092   | Acquired: 2024-04-13, 2024-04-19 (2 lots) |
```
*Clear: notes show the full picture while acquisition_date keeps the earliest date for tax form compliance.*

**Edge cases handled:**
- Single lot → no note added, no blue fill (current behavior preserved)
- Two lots with same acquisition date → note NOT added (treated as single date)
- Lots with empty/epoch acquisition dates → handled, empty dates filtered before aggregation
- Review-required rows → red fill takes precedence over blue (red highest priority)
- Three or more lots → note shows all unique sorted dates (e.g., "2024-01-01, 2024-04-13, 2024-04-19 (3 lots)")

## Review Scope

Files directly changed as part of this plan. Review feedback is accepted **only** for the files listed here.
Any finding about a file not in this list must be rejected as out of scope.

**Production code — in scope:**
- `src/tax_reporting/application/crypto_reporting.py` — `_aggregate_capital_entries()` function, add `multi_acquisition_dates` field to `CryptoCapitalGainEntry`
- `src/tax_reporting/application/persisting/crypto_gains_sheet.py` — `_render_capital_gain_row()` function to apply blue fill
- `src/tax_reporting/application/persisting/excel_utils.py` — add `MULTI_DATE_ROW_FILL` constant and `apply_multi_date_row_fill()` function
- `src/tax_reporting/application/persisting/assumptions_sheet.py` — rename function to `write_assumptions_and_methodology_sheet`, add methodology section
- `src/tax_reporting/application/persisting/workbook_builder.py` — update import and call to renamed function

**Tests — in scope:**
- `tests/unit/application/test_crypto_reporting.py` — add tests for multi-date aggregation
- `tests/unit/application/persisting/test_crypto_gains_sheet.py` — add tests for blue fill rendering
- `tests/unit/application/persisting/test_assumptions_sheet.py` — update tests for renamed sheet

**Documentation — scope-linked (not a closed file list):**
- `docs/domain/crypto_rules.md` — may update PT-C-027 if the implementation decision needs elaboration

**Out of scope — reject all review feedback:**
- FIFO matching logic in `src/tax_reporting/application/crypto_fifo/` — unchanged, aggregates after FIFO runs
- Koinly parsing in `src/tax_reporting/infrastructure/koinly_parser.py` — unchanged
- Token origin resolution — unchanged
- Other sheet writers (crypto_supplementary_sheet, crypto_reconciliation_sheet, etc.) — unchanged

## Validation Commands

```bash
# Run all tests
uv run pytest

# Run specific test module for faster iteration during development
uv run pytest tests/unit/application/test_crypto_reporting.py -k aggregate -v

# Run crypto reporting tests
uv run pytest tests/unit/application/test_crypto_reporting.py -v

# Run sheet rendering tests
uv run pytest tests/unit/application/persisting/test_crypto_gains_sheet.py -v
```

## Tasks

### Task 1: Add blue fill constant and function to excel_utils.py

Files:
- `src/tax_reporting/application/persisting/excel_utils.py`

**Implementation steps:**
- Add `MULTI_DATE_ROW_FILL` constant using light blue color: `PatternFill(start_color="FFCCFFFF", end_color="FFCCFFFF", fill_type="solid")`
- Add `apply_multi_date_row_fill(worksheet, row_no, start_col, end_col)` function following the same pattern as `apply_review_row_fill()`

**Code pattern:**
```python
# After REVIEW_ROW_FILL (line 23):
MULTI_DATE_ROW_FILL = PatternFill(start_color="FFCCFFFF", end_color="FFCCFFFF", fill_type="solid")

# After apply_review_row_fill() function:
def apply_multi_date_row_fill(worksheet: Worksheet, row_no: int, start_col: int, end_col: int) -> None:
    """Apply the multi-date acquisition blue fill to a range of cells in a row.

    Use this for rows where the aggregated capital gain consumed lots from multiple
    acquisition dates, to visually distinguish them from single-date rows.
    This presentation enhancement supports PT-C-027 aggregation behavior by making
    multi-lot sales visually distinct.

    Args:
        worksheet: The worksheet containing the row.
        row_no: 1-based row index to fill.
        start_col: 1-based index of the first column to fill (inclusive).
        end_col: 1-based index of the last column to fill (inclusive).
    """
    for col_idx in range(start_col, end_col + 1):
        worksheet.cell(row_no, col_idx).fill = MULTI_DATE_ROW_FILL  # type: ignore[assignment]
```

**Edge cases handled:**
- None — this is a constant and a pure function with no branching

**Negative requirements:**
- DO NOT use red or any color that conflicts with review_required red fill
- DO NOT modify the existing REVIEW_ROW_FILL or apply_review_row_fill()

**Definition of Done:**
- [x] Constants and function added to excel_utils.py
- [x] Function signature matches apply_review_row_fill() pattern exactly
- [x] No existing code modified

---

### Task 2: Add multi_acquisition_dates field to CryptoCapitalGainEntry

Files:
- `src/tax_reporting/application/crypto_reporting.py`

**Implementation steps:**
- Add `multi_acquisition_dates: bool = False` field to the `CryptoCapitalGainEntry` dataclass (after `token_swap_history` field, before `__post_init__`)

**Code pattern:**
```python
@dataclass(frozen=True)
class CryptoCapitalGainEntry:
    # ... existing fields ...
    token_swap_history: str = ""
    # Set during aggregation when the entry combines FIFO lots from multiple
    # acquisition dates. Triggers blue fill in Excel output. See PT-C-027.
    multi_acquisition_dates: bool = False  # NEW FIELD

    def __post_init__(self) -> None:
        # ... existing validation ...
```

**Edge cases handled:**
- Default value is `False` for single-date rows (backwards compatible)

**Negative requirements:**
- DO NOT add validation for this field in __post_init__ — it's set programmatically during aggregation, not from user input
- DO NOT modify existing field order or types

**Definition of Done:**
- [x] Field added with default `False` and docstring comment
- [x] All existing tests still pass
- [x] No changes to existing fields
- [x] Lines 1822 and 2529 updated with `multi_acquisition_dates=False` (FIFO and Koinly CG instantiations)

---

### Task 3: Implement multi-date detection and note generation in _aggregate_capital_entries()

Files:
- `src/tax_reporting/application/crypto_reporting.py`

**Implementation steps:**
Modify `_aggregate_capital_entries()` function to:
1. Detect when a group has multiple acquisition dates
2. Build the note string `"Acquired: date1, date2 (N lots)"` when multiple dates exist
3. Set `multi_acquisition_dates=True` on the aggregated entry

**Code pattern:**
```python
def _aggregate_capital_entries(entries: list[CryptoCapitalGainEntry]) -> list[CryptoCapitalGainEntry]:
    # ... existing grouping logic ...
    for group in groups.values():
        first = group[0]
        non_empty_dates = [e.acquisition_date for e in group if e.acquisition_date]
        acquisition_date = min(non_empty_dates) if non_empty_dates else ""

        # NEW: Detect multiple acquisition dates
        unique_acquisition_dates = sorted(set(non_empty_dates)) if non_empty_dates else []
        has_multiple_dates = len(unique_acquisition_dates) > 1

        # NEW: Build multi-date note
        multi_date_note = ""
        if has_multiple_dates:
            dates_str = ", ".join(unique_acquisition_dates)
            multi_date_note = f"Acquired: {dates_str} ({len(group)} lot{'s' if len(group) != 1 else ''})"

        # NEW: Merge with existing notes
        existing_notes = [e.notes for e in group if e.notes]
        all_note_parts = list(dict.fromkeys(existing_notes))
        if multi_date_note:
            all_note_parts.insert(0, multi_date_note)  # Multi-date note first
        merged_notes = "; ".join(all_note_parts) or ""

        # ... existing aggregation logic ...

        result.append(
            CryptoCapitalGainEntry(
                # ... existing fields ...
                notes=merged_notes,  # UPDATED
                multi_acquisition_dates=has_multiple_dates,  # NEW
            )
        )
```

**Edge cases handled:**
- Empty acquisition dates (`""`) — filtered out before processing via `if e.acquisition_date`
- Epoch dates (`"1970-..."`) — included in unique dates (user can see the problem)
- Single lot — `has_multiple_dates=False`, no note added
- Multiple lots with same date — `len(unique_acquisition_dates) == 1`, no note added
- Existing notes — multi-date note inserted at the beginning (most prominent), separated with "; "

**Negative requirements:**
- DO NOT add the note when `len(unique_acquisition_dates) <= 1`
- DO NOT modify the aggregation key (disposal_date, asset, platform, holding_period) — this is purely a presentation enhancement
- DO NOT change how cost/proceeds/gain are calculated — sums remain correct

**Definition of Done:**
- [x] Multi-date detection works correctly
- [x] Note format matches `"Acquired: date1, date2 (N lots)"` exactly
- [x] Single-date rows have empty notes (no change in behavior)
- [x] Existing notes are preserved and merged correctly
- [x] All existing aggregation tests still pass

---

### Task 4: Apply blue fill in _render_capital_gain_row()

Files:
- `src/tax_reporting/application/persisting/crypto_gains_sheet.py`

**Implementation steps:**
Modify `_render_capital_gain_row()` function to:
1. Import `apply_multi_date_row_fill` from excel_utils
2. After the existing red fill logic, add blue fill for multi-date rows

**Code pattern:**
```python
from .excel_utils import apply_review_row_fill, apply_multi_date_row_fill, auto_column_width, safe_cell_value

def _render_capital_gain_row(
    worksheet: Worksheet,
    row_no: int,
    entry: CryptoCapitalGainEntry,
    threshold: Decimal,
) -> None:
    # ... existing cell writes ...

    needs_fill = entry.review_required or (entry.cost_eur == 0 and abs(entry.gain_loss_eur) >= threshold)
    if needs_fill:
        apply_review_row_fill(worksheet, row_no, 1, _CAPITAL_GAINS_NUM_COLS)
    elif entry.multi_acquisition_dates:  # NEW: blue fill for multi-date rows
        apply_multi_date_row_fill(worksheet, row_no, 1, _CAPITAL_GAINS_NUM_COLS)
```

**Edge cases handled:**
- Review-required rows get red fill regardless of multi_acquisition_dates (precedence via `elif`)
- Zero-basis rows get red fill regardless (existing logic preserved)
- Multi-date rows with no review flag get blue fill

**Negative requirements:**
- DO NOT apply blue fill when `review_required=True` — red must take precedence
- DO NOT modify the existing red fill logic
- DO NOT add blue fill to single-date rows

**Security consideration:**
- Wrap the notes field with `safe_cell_value()` when writing to Excel to prevent formula injection (per development_lessons.md #7)

**Definition of Done:**
- [x] Blue fill applied only to multi-date rows without review flags
- [x] Red fill takes precedence for review-required rows
- [x] All existing rendering tests still pass

---

### Task 5: Add tests for multi-date aggregation

Files:
- `tests/unit/application/test_crypto_reporting.py`

**Tests to add:**

```python
def test_aggregate_multi_date_acquisition_adds_note_and_flag():
    """Given multiple lots with different acquisition dates, expects note with all dates and multi_acquisition_dates=True."""
    # Arrange: two lots with different acquisition dates, same sale date/asset/platform/holding_period
    entries = [
        CryptoCapitalGainEntry(
            disposal_date="2025-06-14",
            acquisition_date="2024-04-13",
            asset="SEI",
            amount=Decimal("189.7173"),
            cost_eur=Decimal("100"),
            proceeds_eur=Decimal("200"),
            gain_loss_eur=Decimal("100"),
            holding_period="Short term",
            wallet="ByBit",
            platform="ByBit",
            chain="ETH",
            operator_origin=OperatorOrigin(
                platform="ByBit", service_scope="crypto", operator_entity="Test", operator_country="AE",
                source_url="", source_checked_on="", confidence="low", review_required=False
            ),
            annex_hint="J",
            review_required=False,
            notes="",
            token_swap_history="",
        ),
        CryptoCapitalGainEntry(
            disposal_date="2025-06-14",
            acquisition_date="2024-04-19",
            asset="SEI",
            amount=Decimal("188.9919"),
            cost_eur=Decimal("100"),
            proceeds_eur=Decimal("200"),
            gain_loss_eur=Decimal("100"),
            holding_period="Short term",
            wallet="ByBit",
            platform="ByBit",
            chain="ETH",
            operator_origin=OperatorOrigin(
                platform="ByBit", service_scope="crypto", operator_entity="Test", operator_country="AE",
                source_url="", source_checked_on="", confidence="low", review_required=False
            ),
            annex_hint="J",
            review_required=False,
            notes="",
            token_swap_history="",
        ),
    ]

    # Act
    result = _aggregate_capital_entries(entries)

    # Assert
    assert len(result) == 1
    aggregated = result[0]
    assert aggregated.acquisition_date == "2024-04-13"  # Earliest date preserved
    assert aggregated.amount == Decimal("378.7092")  # Sum of both lots
    assert aggregated.multi_acquisition_dates is True
    assert aggregated.notes == "Acquired: 2024-04-13, 2024-04-19 (2 lots)"

def test_aggregate_single_date_no_note_or_flag():
    """Given multiple lots with the same acquisition date, expects no note and multi_acquisition_dates=False."""
    entries = [
        CryptoCapitalGainEntry(
            disposal_date="2025-06-14",
            acquisition_date="2024-04-13",  # SAME date for both
            asset="SEI",
            amount=Decimal("189.7173"),
            cost_eur=Decimal("100"),
            proceeds_eur=Decimal("200"),
            gain_loss_eur=Decimal("100"),
            holding_period="Short term",
            wallet="ByBit",
            platform="ByBit",
            chain="ETH",
            operator_origin=OperatorOrigin(
                platform="ByBit", service_scope="crypto", operator_entity="Test", operator_country="AE",
                source_url="", source_checked_on="", confidence="low", review_required=False
            ),
            annex_hint="J",
            review_required=False,
            notes="",
            token_swap_history="",
        ),
        CryptoCapitalGainEntry(
            disposal_date="2025-06-14",
            acquisition_date="2024-04-13",  # SAME date
            asset="SEI",
            amount=Decimal("188.9919"),
            cost_eur=Decimal("100"),
            proceeds_eur=Decimal("200"),
            gain_loss_eur=Decimal("100"),
            holding_period="Short term",
            wallet="ByBit",
            platform="ByBit",
            chain="ETH",
            operator_origin=OperatorOrigin(
                platform="ByBit", service_scope="crypto", operator_entity="Test", operator_country="AE",
                source_url="", source_checked_on="", confidence="low", review_required=False
            ),
            annex_hint="J",
            review_required=False,
            notes="",
            token_swap_history="",
        ),
    ]

    result = _aggregate_capital_entries(entries)

    assert len(result) == 1
    aggregated = result[0]
    assert aggregated.multi_acquisition_dates is False
    assert aggregated.notes == ""

def test_aggregate_multi_date_with_existing_notes_merges():
    """Given lots with different dates and existing notes, expects multi-date note prepended to existing notes."""
    entries = [
        CryptoCapitalGainEntry(
            disposal_date="2025-06-14",
            acquisition_date="2024-04-13",
            asset="SEI",
            amount=Decimal("189.7173"),
            cost_eur=Decimal("100"),
            proceeds_eur=Decimal("200"),
            gain_loss_eur=Decimal("100"),
            holding_period="Short term",
            wallet="ByBit",
            platform="ByBit",
            chain="ETH",
            operator_origin=OperatorOrigin(
                platform="ByBit", service_scope="crypto", operator_entity="Test", operator_country="AE",
                source_url="", source_checked_on="", confidence="low", review_required=False
            ),
            annex_hint="J",
            review_required=False,
            notes="Existing note about fee",  # Existing note
            token_swap_history="",
        ),
        CryptoCapitalGainEntry(
            disposal_date="2025-06-14",
            acquisition_date="2024-04-19",
            asset="SEI",
            amount=Decimal("188.9919"),
            cost_eur=Decimal("100"),
            proceeds_eur=Decimal("200"),
            gain_loss_eur=Decimal("100"),
            holding_period="Short term",
            wallet="ByBit",
            platform="ByBit",
            chain="ETH",
            operator_origin=OperatorOrigin(
                platform="ByBit", service_scope="crypto", operator_entity="Test", operator_country="AE",
                source_url="", source_checked_on="", confidence="low", review_required=False
            ),
            annex_hint="J",
            review_required=False,
            notes="Another existing note",  # Different existing note
            token_swap_history="",
        ),
    ]

    result = _aggregate_capital_entries(entries)

    assert len(result) == 1
    aggregated = result[0]
    assert aggregated.multi_acquisition_dates is True
    # Multi-date note first, then existing notes de-duplicated and joined
    assert aggregated.notes == "Acquired: 2024-04-13, 2024-04-19 (2 lots); Another existing note; Existing note about fee"

def test_aggregate_multi_date_three_lots_shows_all_dates():
    """Given three lots with three different dates, expects all dates in note."""
    entries = [
        CryptoCapitalGainEntry(
            disposal_date="2025-06-14",
            acquisition_date="2024-01-01",
            asset="SEI",
            amount=Decimal("100"),
            cost_eur=Decimal("50"),
            proceeds_eur=Decimal("100"),
            gain_loss_eur=Decimal("50"),
            holding_period="Short term",
            wallet="ByBit",
            platform="ByBit",
            chain="ETH",
            operator_origin=OperatorOrigin(
                platform="ByBit", service_scope="crypto", operator_entity="Test", operator_country="AE",
                source_url="", source_checked_on="", confidence="low", review_required=False
            ),
            annex_hint="J",
            review_required=False,
            notes="",
            token_swap_history="",
        ),
        CryptoCapitalGainEntry(
            disposal_date="2025-06-14",
            acquisition_date="2024-04-13",
            asset="SEI",
            amount=Decimal("100"),
            cost_eur=Decimal("50"),
            proceeds_eur=Decimal("100"),
            gain_loss_eur=Decimal("50"),
            holding_period="Short term",
            wallet="ByBit",
            platform="ByBit",
            chain="ETH",
            operator_origin=OperatorOrigin(
                platform="ByBit", service_scope="crypto", operator_entity="Test", operator_country="AE",
                source_url="", source_checked_on="", confidence="low", review_required=False
            ),
            annex_hint="J",
            review_required=False,
            notes="",
            token_swap_history="",
        ),
        CryptoCapitalGainEntry(
            disposal_date="2025-06-14",
            acquisition_date="2024-04-19",
            asset="SEI",
            amount=Decimal("100"),
            cost_eur=Decimal("50"),
            proceeds_eur=Decimal("100"),
            gain_loss_eur=Decimal("50"),
            holding_period="Short term",
            wallet="ByBit",
            platform="ByBit",
            chain="ETH",
            operator_origin=OperatorOrigin(
                platform="ByBit", service_scope="crypto", operator_entity="Test", operator_country="AE",
                source_url="", source_checked_on="", confidence="low", review_required=False
            ),
            annex_hint="J",
            review_required=False,
            notes="",
            token_swap_history="",
        ),
    ]

    result = _aggregate_capital_entries(entries)

    assert len(result) == 1
    aggregated = result[0]
    assert aggregated.multi_acquisition_dates is True
    assert aggregated.notes == "Acquired: 2024-01-01, 2024-04-13, 2024-04-19 (3 lots)"

def test_aggregate_multi_date_with_review_required_preserves_review_flag():
    """Given multi-date entry with review_required=True, expects review_required preserved in aggregation (rendering tested separately in Task 6)."""
    entries = [
        CryptoCapitalGainEntry(
            disposal_date="2025-06-14",
            acquisition_date="2024-04-13",
            asset="SEI",
            amount=Decimal("189.7173"),
            cost_eur=Decimal("100"),
            proceeds_eur=Decimal("200"),
            gain_loss_eur=Decimal("100"),
            holding_period="Short term",
            wallet="ByBit",
            platform="ByBit",
            chain="ETH",
            operator_origin=OperatorOrigin(
                platform="ByBit", service_scope="crypto", operator_entity="Test", operator_country="AE",
                source_url="", source_checked_on="", confidence="low", review_required=False
            ),
            annex_hint="J",
            review_required=True,  # REVIEW REQUIRED
            review_reason="Test review reason",
            notes="",
            token_swap_history="",
        ),
        CryptoCapitalGainEntry(
            disposal_date="2025-06-14",
            acquisition_date="2024-04-19",
            asset="SEI",
            amount=Decimal("188.9919"),
            cost_eur=Decimal("100"),
            proceeds_eur=Decimal("200"),
            gain_loss_eur=Decimal("100"),
            holding_period="Short term",
            wallet="ByBit",
            platform="ByBit",
            chain="ETH",
            operator_origin=OperatorOrigin(
                platform="ByBit", service_scope="crypto", operator_entity="Test", operator_country="AE",
                source_url="", source_checked_on="", confidence="low", review_required=False
            ),
            annex_hint="J",
            review_required=False,
            notes="",
            token_swap_history="",
        ),
    ]

    result = _aggregate_capital_entries(entries)

    assert len(result) == 1
    aggregated = result[0]
    assert aggregated.multi_acquisition_dates is True  # Still set
    assert aggregated.review_required is True  # Takes precedence via OR logic
    assert aggregated.notes == "Acquired: 2024-04-13, 2024-04-19 (2 lots); Test review reason"
```

**Edge cases covered:**
- Two lots with different dates (primary happy path)
- Two lots with same date (should not trigger multi-date logic)
- Three lots with three dates (verify sorting and all dates shown)
- Existing notes preserved and merged
- Review-required rows with multi-dates (red precedence)

**Additional edge case tests (from review feedback):**
- All lots with empty dates → `multi_acquisition_dates=False`, no note
- Mixed empty and valid dates → only valid dates counted
- Single lot → `multi_acquisition_dates=False`

**Negative requirements:**
- DO NOT add note when dates are identical
- DO NOT lose existing notes during merge
- DO NOT clear review_required when aggregating multi-date rows

**Definition of Done:**
- [x] All new tests pass
- [x] All existing aggregation tests still pass
- [x] Coverage for multi-date aggregation is complete
- [x] Edge case tests added for empty/mixed/single date scenarios

---

### Task 6: Add rendering tests for blue fill

Files:
- `tests/unit/application/persisting/test_crypto_gains_sheet.py`

**Tests to add:**

```python
def test_render_capital_gain_row_blue_fill_for_multi_date():
    """Given entry with multi_acquisition_dates=True and review_required=False, expects blue fill."""
    # Arrange
    workbook = Workbook()
    worksheet = workbook.active
    entry = CryptoCapitalGainEntry(
        disposal_date="2025-06-14",
        acquisition_date="2024-04-13",
        asset="SEI",
        amount=Decimal("378.7092"),
        cost_eur=Decimal("200"),
        proceeds_eur=Decimal("400"),
        gain_loss_eur=Decimal("200"),
        holding_period="Short term",
        wallet="ByBit",
        platform="ByBit",
        chain="ETH",
        operator_origin=OperatorOrigin(
            platform="ByBit", service_scope="crypto", operator_entity="Test", operator_country="AE",
            source_url="", source_checked_on="", confidence="low", review_required=False
        ),
        annex_hint="J",
        review_required=False,  # No review flag
        notes="Acquired: 2024-04-13, 2024-04-19 (2 lots)",
        multi_acquisition_dates=True,  # Multi-date flag
    )
    threshold = Decimal("10")

    # Act
    _render_capital_gain_row(worksheet, 1, entry, threshold)

    # Assert: check fill color for cells in the row
    # Using openpyxl's fill property
    from openpyxl.styles import PatternFill
    for col_idx in range(1, 18):  # _CAPITAL_GAINS_NUM_COLS = 17
        cell_fill = worksheet.cell(1, col_idx).fill
        assert isinstance(cell_fill, PatternFill)
        assert cell_fill.start_color == "FFCCFFFF"  # Light blue
        assert cell_fill.end_color == "FFCCFFFF"
        assert cell_fill.fill_type == "solid"

def test_render_capital_gain_row_red_takes_precedence_over_blue():
    """Given entry with multi_acquisition_dates=True and review_required=True, expects red fill."""
    workbook = Workbook()
    worksheet = workbook.active
    entry = CryptoCapitalGainEntry(
        disposal_date="2025-06-14",
        acquisition_date="2024-04-13",
        asset="SEI",
        amount=Decimal("378.7092"),
        cost_eur=Decimal("200"),
        proceeds_eur=Decimal("400"),
        gain_loss_eur=Decimal("200"),
        holding_period="Short term",
        wallet="ByBit",
        platform="ByBit",
        chain="ETH",
        operator_origin=OperatorOrigin(
            platform="ByBit", service_scope="crypto", operator_entity="Test", operator_country="AE",
            source_url="", source_checked_on="", confidence="low", review_required=False
        ),
        annex_hint="J",
        review_required=True,  # REVIEW REQUIRED
        review_reason="Test reason",
        notes="",
        multi_acquisition_dates=True,  # Multi-date flag
    )
    threshold = Decimal("10")

    _render_capital_gain_row(worksheet, 1, entry, threshold)

    # Assert: RED fill, not blue
    from openpyxl.styles import PatternFill
    for col_idx in range(1, 18):
        cell_fill = worksheet.cell(1, col_idx).fill
        assert isinstance(cell_fill, PatternFill)
        assert cell_fill.start_color == "FFFF0000"  # RED
        assert cell_fill.end_color == "FFFF0000"

def test_render_capital_gain_row_no_fill_for_single_date():
    """Given entry with multi_acquisition_dates=False, expects no fill."""
    workbook = Workbook()
    worksheet = workbook.active
    entry = CryptoCapitalGainEntry(
        disposal_date="2025-06-14",
        acquisition_date="2024-04-13",
        asset="SEI",
        amount=Decimal("189.7173"),
        cost_eur=Decimal("100"),
        proceeds_eur=Decimal("200"),
        gain_loss_eur=Decimal("100"),
        holding_period="Short term",
        wallet="ByBit",
        platform="ByBit",
        chain="ETH",
        operator_origin=OperatorOrigin(
            platform="ByBit", service_scope="crypto", operator_entity="Test", operator_country="AE",
            source_url="", source_checked_on="", confidence="low", review_required=False
        ),
        annex_hint="J",
        review_required=False,
        notes="",
        multi_acquisition_dates=False,  # Single date
    )
    threshold = Decimal("10")

    _render_capital_gain_row(worksheet, 1, entry, threshold)

    # Assert: NO fill (default is no PatternFill)
    for col_idx in range(1, 18):
        cell = worksheet.cell(1, col_idx)
        # Default openpyxl cells have no fill set (or an empty one)
        # We check that it's not our custom fills
        if cell.fill and cell.fill.start_color:
            assert cell.fill.start_color not in ["FFCCFFFF", "FFFF0000"]
```

**Edge cases covered:**
- Multi-date without review → blue fill
- Multi-date with review → red fill (precedence)
- Single date → no fill

**Definition of Done:**
- [x] All new rendering tests pass
- [x] All existing rendering tests still pass
- [x] Color precedence verified

---

### Task 7: End-to-end integration test

Files:
- `tests/end_to_end/test_end_to_end.py` (or appropriate e2e test file)

**Purpose:** Verify the full pipeline from Koinly parsing → aggregation → rendering produces the correct Excel output with multi-date notes and blue fill.

**Implementation approach:**
- Create a minimal Koinly capital gains CSV fixture with rows that will aggregate to a multi-date entry
- Run the full pipeline
- Verify the output Excel file has:
  1. One aggregated row (not multiple)
  2. Correct notes field with multi-date information
  3. Blue fill on the row

**Note:** This test requires checking if e2e tests already exist and what the fixture structure looks like.

**Definition of Done:**
- [ ] Integration test passes
- [ ] Excel output verified manually if needed

---

### Task 8: Update documentation (if needed)

Files:
- `docs/domain/crypto_rules.md` (PT-C-027 section)

**Implementation:**
Review PT-C-027 to see if it needs updating to document the multi-date note and blue fill behavior.

**What to check:**
- Does PT-C-027 describe the acquisition_date behavior?
- Should we document the multi-date note format?

**Specific update to add if missing:**
If PT-C-027 doesn't describe multi-date note and blue fill presentation, add a sentence:
"When aggregated rows consume lots from multiple acquisition dates, the Notes field
shows all acquisition dates and the row is highlighted with blue fill."

**Definition of Done:**
- [ ] PT-C-027 updated with multi-date note/blue fill description if missing
- [ ] Decision documented in commit message if no update needed

---

### Task 9: Final validation

Run the full test suite and verify:
- All tests pass
- Manual check of Excel output if needed

**Validation commands:**
```bash
uv run pytest
```

**Definition of Done:**
- [x] All tests pass
- [x] No regressions in existing functionality
- [x] Ready for commit

---

### Task 10: Rename and expand Platform Assumptions tab to "Assumptions & Methodology"

Files:
- `src/tax_reporting/application/persisting/assumptions_sheet.py` — rename and restructure
- Any imports/references to "Platform Assumptions" sheet name

**Purpose:** Add transparency about the methodology and legal basis for reporting decisions. The expanded tab will document why aggregation is legal, FIFO methodology, materiality rules, and other assumptions used in generating the report.

**Implementation steps:**

1. **Rename sheet:** Change "Platform Assumptions" to "Assumptions & Methodology"
2. **Add Section 2: Methodology Assumptions** after platform data with these subsections:

**Methodology Assumptions content:**

| Subsection | Content |
|------------|---------|
| **Aggregation Approach** | Why we merge FIFO lots into one line per sale:<br>• Legal basis: Quadro 9.4 (Anexo J) has ONE "Data de aquisição" field per line<br>• PT-C-025: "Multiple FIFO lots matched to the same sale event can reasonably be reported as one aggregated line"<br>• The multi-date note in Notes column preserves full lot information<br>• Multi-lot sales show full acquisition date detail in Notes ("Acquired: date1, date2 (N lots)") and are highlighted with blue fill |
| **FIFO Methodology** | Why FIFO is used:<br>• PT-C-008: FIFO is mandatory per CIRS art. 43 n.6 al.g<br>• Applied per wallet/exchange independently per CIRS art. 43 n.7 |
| **Holding Period Classification** | How we determine short vs long term:<br>• PT-C-011: ≥365 days = exempt (long-term), <365 days = taxable (short-term)<br>• Calendar-year arithmetic used to avoid leap-year boundary issues |
| **Materiality Threshold** | Why sub-1 EUR gains are filtered:<br>• PT-C-028: Lines where \|gain/loss\| < 1 EUR excluded from report<br>• No material tax impact; reduces manual filing burden |
| **Data Sources** | What data we rely on:<br>• Interactive Brokers reports (dividends, capital gains)<br>• Koinly exports (crypto capital gains, rewards, transaction history)<br>• Config.ini for exchange rates |

**Code pattern:**
```python
def write_assumptions_and_methodology_sheet(
    workbook: openpyxl.Workbook,
    capital_entries: list[CryptoCapitalGainEntry] | None = None,
    reward_entries: list[CryptoRewardIncomeEntry] | None = None,
) -> None:
    """Create and populate an 'Assumptions & Methodology' worksheet.

    Contains two sections:
    1. Platform Assumptions — complete manifest of platforms with operator metadata
    2. Methodology Assumptions — legal basis and rationale for reporting decisions
    """
    summaries = _collect_platform_summaries(capital_entries, reward_entries)

    worksheet = workbook.create_sheet("Assumptions & Methodology")  # RENAMED
    row_no = 1

    # Title
    worksheet.cell(row_no, 1, "Assumptions & Methodology")
    worksheet.cell(row_no, 1).font = openpyxl.styles.Font(bold=True, size=14)
    row_no += 2

    # ... [existing platform data section code] ...

    # After platform data section, add methodology section
    row_no += 2
    worksheet.cell(row_no, 1, "Methodology Assumptions")
    worksheet.cell(row_no, 1).font = openpyxl.styles.Font(bold=True, size=12)
    row_no += 2

    methodology_items = [
        (
            "Aggregation Approach",
            "FIFO lots from the same sale event are aggregated into one line. "
            "Legal basis: Quadro 9.4 (Anexo J) has one 'Data de aquisição' field per line. "
            "Multiple FIFO lots matched to the same sale event can reasonably be reported "
            "as one aggregated line (PT-C-025). Multi-lot sales show full acquisition date "
            "detail in the Notes column ('Acquired: date1, date2 (N lots)') and are "
            "highlighted with blue fill for easy identification. "
            "See PT-C-025 and PT-C-027 in docs/domain/crypto_rules.md."
        ),
        (
            "FIFO Methodology",
            "First-In-First-Out is mandatory per CIRS art. 43 n.6 al.g. "
            "Applied per wallet/exchange independently per CIRS art. 43 n.7. "
            "See PT-C-008 and PT-C-009 in docs/domain/crypto_rules.md."
        ),
        (
            "Holding Period Classification",
            "Short-term (<365 days) = taxable, Long-term (≥365 days) = exempt. "
            "Calendar-year arithmetic used (2024-02-29 + 365 days = 2025-03-01, not 2025-02-28). "
            "See PT-C-011 in docs/domain/crypto_rules.md."
        ),
        (
            "Materiality Threshold",
            "Lines where |gain/loss| < 1 EUR are excluded from the report. "
            "These have no material tax impact and reduce manual filing burden. "
            "See PT-C-028 in docs/domain/crypto_rules.md."
        ),
        (
            "Data Sources",
            "Interactive Brokers (dividends, capital gains), Koinly (crypto), "
            "config.ini (exchange rates). See README.md for data requirements."
        ),
    ]

    for label, description in methodology_items:
        worksheet.cell(row_no, 1, label)
        worksheet.cell(row_no, 1).font = openpyxl.styles.Font(bold=True)
        worksheet.cell(row_no, 2, description)
        row_no += 1

    auto_column_width(worksheet)
```

**Edge cases handled:**
- No platform data — still show methodology section
- Empty capital/reward entries — methodology section still relevant

**Negative requirements:**
- DO NOT modify the actual reporting logic — this is purely documentation
- DO NOT make the methodology section conditionally hide based on data
- DO NOT include platform-specific assumptions in methodology section (those belong in Section 1)

**Definition of Done:**
- [x] Sheet renamed to "Assumptions & Methodology"
- [x] Platform data section preserved exactly as-is
- [x] Methodology section added with all 5 subsections
- [x] References to PT-C rules and docs are accurate
- [x] Function renamed to `write_assumptions_and_methodology_sheet`
- [x] `workbook_builder.py` import updated to new function name
- [x] `workbook_builder.py` function call updated
- [x] `workbook_builder.py` line 176 error handler list updated to "Assumptions & Methodology"
- [x] All existing tests for assumptions_sheet.py updated for new sheet name and function name
- [x] Manual review of Excel output confirms layout is readable

---

### Task 11: Update tests for renamed assumptions sheet

Files:
- `tests/unit/application/persisting/test_assumptions_sheet.py` (or equivalent test file)

**Implementation:**
Search for all references to "Platform Assumptions" in tests and update to "Assumptions & Methodology".

**Code pattern:**
```python
def test_write_platform_assumptions_sheet():
    # Before:
    # assert "Platform Assumptions" in workbook.sheetnames
    # After:
    assert "Assumptions & Methodology" in workbook.sheetnames
```

**Definition of Done:**
- [x] All tests updated for new sheet name
- [x] `tests/unit/application/persisting/test_workbook_builder.py` line 217 updated to "Assumptions & Methodology"
- [x] All tests pass
- [x] No hardcoded "Platform Assumptions" strings remain in tests

---

### Task 12: Final validation after methodology expansion

Run the full test suite and verify:
- All tests pass
- Excel output has both sections correctly formatted
- Documentation references are accurate

**Validation commands:**
```bash
uv run pytest

# Quick check for sheet name in output
uv run tax-reporting --example && \
  unzip -l resources/result/*.xlsx | grep "Assumptions"
```

**Definition of Done:**
- [x] All tests pass
- [x] Excel output contains "Assumptions & Methodology" sheet
- [x] Platform and methodology sections both visible
- [x] Ready for commit

---

## Optional Mitigations (from review)

The following mitigations were suggested during plan review but are not required for implementation. Consider them if issues arise:

### Testing improvements
- **Use _NUM_CAPITAL_COLUMNS constant**: Task 6 hard-codes `range(1, 18)` instead of using the test file's `_NUM_CAPITAL_COLUMNS` constant.
- **Use existing _is_red_fill pattern**: Task 6 should import constants from `excel_utils.py` or use a helper function following the existing `_is_red_fill` pattern.
- **Test notes order with prefix checks**: Task 5's exact string assertion for notes is fragile; use `.startswith("Acquired:")` and `in` checks instead.

### Scope considerations
- **Consider splitting Tasks 10-11**: The methodology expansion (Tasks 10-11) is a separate concern from multi-date acquisition. Could be a separate plan for smaller, focused changes.
- **Consider removing Task 7**: The E2E test may be unnecessary given the comprehensive unit tests in Tasks 5 and 6.

### Code simplifications
- **Simplify note merging**: The position-sensitive insertion in Task 3 could be simplified to match the existing pattern at line 2200.

### Documentation maintenance
- **Add comment about content coupling**: Consider adding a comment in `assumptions_sheet.py` noting that methodology_items references should be audited when `crypto_rules.md` changes.

### Breaking change communication
- **Document sheet name change**: The rename from "Platform Assumptions" to "Assumptions & Methodology" is a breaking change for external references. Consider adding a release note or README entry.
