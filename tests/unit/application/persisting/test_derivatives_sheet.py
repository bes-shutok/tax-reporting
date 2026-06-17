"""Tests for the Derivatives P&L sheet writer (CIRS art. 10(1)(e))."""

from decimal import Decimal

import openpyxl
import pytest

from tax_reporting.application.crypto.entities import DerivativesEventType, DerivativesPnLEntry
from tax_reporting.application.crypto_reporting import (
    CapitalGainPeriodStats,
    CryptoCapitalGainStats,
    CryptoReconciliationSummary,
    CryptoTaxReport,
)
from tax_reporting.application.persisting.derivatives_sheet import write_derivatives_sheet

_SHEET_NAME = "Derivatives P&L"
_HEADER_TITLE = "DERIVATIVES P&L (Financial Derivatives: CIRS art. 10(1)(e))"
_COLUMN_HEADERS = [
    "Date",
    "Asset",
    "Platform",
    "Event Type",
    "P&L (EUR)",
    "Operator entity",
    "Operator country",
    "Event count",
    "Notes",
    "Review",
]
_NUM_COLUMNS = len(_COLUMN_HEADERS)
_EMPTY_STATE_MESSAGE = "No derivatives activity for this jurisdiction"
_LOSS_FOOTNOTE = "Losses are deductible against other Category G gains; carry-forward 5 years per PT-C-016"


def _make_derivatives_entry(**overrides: object) -> DerivativesPnLEntry:
    defaults: dict[str, object] = {
        "date": "2025-01-12",
        "asset": "USDT",
        "platform": "ByBit",
        "pnl_eur": Decimal("140.18"),
        "event_type": DerivativesEventType.PROFIT,
        "source_ref": "OGR:2025-01-12:USDT",
        "legal_category": "CIRS art. 10(1)(e)",
        "review_required": False,
        "review_reason": "",
    }
    defaults.update(overrides)
    return DerivativesPnLEntry(**defaults)  # type: ignore[arg-type]


def _make_crypto_tax_report(derivatives_entries: list[DerivativesPnLEntry] | None = None) -> CryptoTaxReport:
    empty_period = CapitalGainPeriodStats(
        count=0, cost_total_eur=Decimal("0"), proceeds_total_eur=Decimal("0"), gain_loss_total_eur=Decimal("0")
    )
    stats = CryptoCapitalGainStats(
        short_term=empty_period,
        long_term=empty_period,
        mixed=empty_period,
        unknown=empty_period,
        grand_total=empty_period,
    )
    reconciliation = CryptoReconciliationSummary(
        capital_rows=0,
        reward_rows=0,
        short_term_rows=0,
        long_term_rows=0,
        mixed_rows=0,
        unknown_rows=0,
        capital_cost_total_eur=Decimal("0"),
        capital_proceeds_total_eur=Decimal("0"),
        capital_gain_total_eur=Decimal("0"),
        reward_total_eur=Decimal("0"),
        opening_holdings=None,
        closing_holdings=None,
    )
    return CryptoTaxReport(
        tax_year=2025,
        capital_entries=[],
        reward_entries=[],
        reconciliation=reconciliation,
        capital_gain_stats=stats,
        derivatives_entries=derivatives_entries or [],
    )


def _find_row_with_value(ws: openpyxl.worksheet.worksheet.Worksheet, value: str, max_row: int = 50) -> int:
    """Find the first row whose first column equals value. Returns 1-based row index."""
    for r in range(1, min(ws.max_row, max_row) + 1):
        if ws.cell(r, 1).value == value:
            return r
    raise AssertionError(f"Row with value '{value}' not found in column 1")


def _find_row_containing(ws: openpyxl.worksheet.worksheet.Worksheet, substring: str, max_row: int = 60) -> int:
    """Find the first row where any cell value contains substring. Returns 1-based row index."""
    for r in range(1, min(ws.max_row, max_row) + 1):
        for c in range(1, ws.max_column + 1):
            cell_val = ws.cell(r, c).value
            if cell_val is not None and substring in str(cell_val):
                return r
    raise AssertionError(f"Row containing '{substring}' not found")


@pytest.mark.unit
class TestDerivativesSheet:
    """Behavioral coverage for the Derivatives P&L sheet."""

    def test_renders_header_with_legal_basis(self):
        report = _make_crypto_tax_report(derivatives_entries=[_make_derivatives_entry()])
        wb = openpyxl.Workbook()
        write_derivatives_sheet(wb, report)

        assert _SHEET_NAME in wb.sheetnames
        ws = wb[_SHEET_NAME]
        assert ws.cell(1, 1).value == _HEADER_TITLE

    def test_renders_one_row_per_aggregated_entry(self):
        entries = [
            _make_derivatives_entry(date="2025-01-12", asset="USDT", platform="ByBit"),
            _make_derivatives_entry(date="2025-01-13", asset="USDT", platform="ByBit"),
        ]
        report = _make_crypto_tax_report(derivatives_entries=entries)
        wb = openpyxl.Workbook()
        write_derivatives_sheet(wb, report)

        ws = wb[_SHEET_NAME]

        header_row = _find_row_with_value(ws, "Date")

        for idx, expected_header in enumerate(_COLUMN_HEADERS, start=1):
            assert ws.cell(header_row, idx).value == expected_header, (
                f"Column {idx} header: expected '{expected_header}', got '{ws.cell(header_row, idx).value}'"
            )

        data_row_1 = header_row + 1
        data_row_2 = header_row + 2

        assert ws.cell(data_row_1, 1).value == "2025-01-12"
        assert ws.cell(data_row_1, 2).value == "USDT"
        assert ws.cell(data_row_1, 3).value == "ByBit"
        assert ws.cell(data_row_1, 4).value == "profit"
        # Legal Category, Annex hint, and Operation code are constants across all
        # derivatives rows today; they appear on the row-2 detail line, not as columns.

        assert ws.cell(data_row_2, 1).value == "2025-01-13"
        assert ws.cell(data_row_2, 2).value == "USDT"
        assert ws.cell(data_row_2, 3).value == "ByBit"

    def test_totals_row(self):
        entries = [
            _make_derivatives_entry(date="2025-01-12", pnl_eur=Decimal("140.18")),
            _make_derivatives_entry(date="2025-01-13", pnl_eur=Decimal("-4.17"), event_type=DerivativesEventType.LOSS),
        ]
        report = _make_crypto_tax_report(derivatives_entries=entries)
        wb = openpyxl.Workbook()
        write_derivatives_sheet(wb, report)

        ws = wb[_SHEET_NAME]
        totals_row = _find_row_containing(ws, "Total")
        pnl_cell_val = ws.cell(totals_row, 5).value
        assert pnl_cell_val is not None
        assert Decimal(str(pnl_cell_val)) == Decimal("136.01"), (
            f"Expected totals row net P&L = 136.01, got {pnl_cell_val}"
        )

    def test_empty_state_when_no_entries(self):
        report = _make_crypto_tax_report(derivatives_entries=[])
        wb = openpyxl.Workbook()
        write_derivatives_sheet(wb, report)

        ws = wb[_SHEET_NAME]
        header_row = _find_row_with_value(ws, "Date")
        for idx, expected_header in enumerate(_COLUMN_HEADERS, start=1):
            assert ws.cell(header_row, idx).value == expected_header

        empty_row = _find_row_containing(ws, _EMPTY_STATE_MESSAGE)
        assert empty_row > header_row, "Empty-state row should appear after column headers"

    def test_review_reason_renders_as_yes_with_reason(self):
        entries = [
            _make_derivatives_entry(
                review_required=True,
                review_reason="Ambiguous OGR/CG value mismatch",
            ),
        ]
        report = _make_crypto_tax_report(derivatives_entries=entries)
        wb = openpyxl.Workbook()
        write_derivatives_sheet(wb, report)

        ws = wb[_SHEET_NAME]
        header_row = _find_row_with_value(ws, "Date")
        data_row = header_row + 1
        # Review lives in the last column (column 10 under the 10-column layout)
        review_cell = ws.cell(data_row, 10).value
        assert review_cell == "YES: Ambiguous OGR/CG value mismatch", (
            f"Review cell must render 'YES: <reason>', got '{review_cell}'"
        )

    def test_loss_deductibility_footnote(self):
        entries = [
            _make_derivatives_entry(date="2025-01-13", pnl_eur=Decimal("-4.17"), event_type=DerivativesEventType.LOSS),
        ]
        report = _make_crypto_tax_report(derivatives_entries=entries)
        wb = openpyxl.Workbook()
        write_derivatives_sheet(wb, report)

        ws = wb[_SHEET_NAME]
        footnote_row = _find_row_containing(ws, "Losses are deductible")
        cell_text = ""
        for c in range(1, ws.max_column + 1):
            v = ws.cell(footnote_row, c).value
            if v is not None and "Losses are deductible" in str(v):
                cell_text = str(v)
                break
        assert cell_text == _LOSS_FOOTNOTE, f"Footnote text must match exactly, got '{cell_text}'"

    def test_loss_deductibility_footnote_absent_when_no_loss(self):
        entries = [
            _make_derivatives_entry(
                date="2025-01-12",
                pnl_eur=Decimal("140.18"),
                event_type=DerivativesEventType.PROFIT,
            ),
        ]
        report = _make_crypto_tax_report(derivatives_entries=entries)
        wb = openpyxl.Workbook()
        write_derivatives_sheet(wb, report)

        ws = wb[_SHEET_NAME]
        found = False
        for r in range(1, ws.max_row + 1):
            for c in range(1, ws.max_column + 1):
                v = ws.cell(r, c).value
                if v is not None and "Losses are deductible" in str(v):
                    found = True
                    break
            if found:
                break
        assert not found, "Footnote should NOT appear when there are no loss entries"

    def test_review_row_gets_red_fill(self):
        entries = [
            _make_derivatives_entry(review_required=True, review_reason="Ambiguous OGR/CG value mismatch"),
        ]
        report = _make_crypto_tax_report(derivatives_entries=entries)
        wb = openpyxl.Workbook()
        write_derivatives_sheet(wb, report)

        ws = wb[_SHEET_NAME]
        header_row = _find_row_with_value(ws, "Date")
        data_row = header_row + 1
        for col in range(1, len(_COLUMN_HEADERS) + 1):
            cell = ws.cell(data_row, col)
            assert cell.fill.patternType == "solid", f"Col {col} should have solid fill, got {cell.fill.patternType}"
            assert cell.fill.fgColor.rgb == "FFFF0000", (
                f"Col {col} should have red fill (FFFF0000), got {cell.fill.fgColor.rgb}"
            )

    # --- 10-column layout with detail line (Annex hint, Operation code, Legal
    #     Category are constants; rendered once on row 2, not as columns) ---

    def test_header_has_ten_columns(self):
        report = _make_crypto_tax_report(derivatives_entries=[_make_derivatives_entry()])
        wb = openpyxl.Workbook()
        write_derivatives_sheet(wb, report)

        ws = wb[_SHEET_NAME]
        header_row = 3
        populated = [
            (c, ws.cell(header_row, c).value)
            for c in range(1, 50)
            if ws.cell(header_row, c).value is not None
        ]
        assert len(populated) == 10, (
            f"Header row should have exactly 10 populated cells, got {len(populated)}: {populated}"
        )
        last_col, last_value = populated[-1]
        assert last_col == 10, f"Last header cell should be at column 10, got column {last_col}"
        assert last_value == "Review", f"Last header cell should be 'Review', got '{last_value}'"

    def test_header_columns_include_operator_event_count_notes(self):
        report = _make_crypto_tax_report(derivatives_entries=[_make_derivatives_entry()])
        wb = openpyxl.Workbook()
        write_derivatives_sheet(wb, report)

        ws = wb[_SHEET_NAME]
        header_row = _find_row_with_value(ws, "Date")
        header_values = {
            ws.cell(header_row, c).value
            for c in range(1, 50)
            if ws.cell(header_row, c).value is not None
        }
        for required in ["Operator entity", "Operator country", "Event count", "Notes"]:
            assert required in header_values, (
                f"Header row missing required column '{required}'. Headers seen: {sorted(map(str, header_values))}"
            )
        # Constants collapsed to the detail line must NOT appear as columns.
        for dropped in ["Annex hint", "Operation code", "Legal Category"]:
            assert dropped not in header_values, (
                f"'{dropped}' should be on the detail line, not a column. "
                f"Headers seen: {sorted(map(str, header_values))}"
            )

    def test_detail_line_above_header_shows_annex_code_and_legal_basis(self):
        entries = [
            _make_derivatives_entry(
                annex_hint="G/Q13",
                operation_code="G51",
                legal_category="CIRS art. 10(1)(e)",
            ),
        ]
        report = _make_crypto_tax_report(derivatives_entries=entries)
        wb = openpyxl.Workbook()
        write_derivatives_sheet(wb, report)

        ws = wb[_SHEET_NAME]
        detail_value = ws.cell(2, 1).value
        assert detail_value is not None, "Row 2 column 1 should contain the detail line"
        detail_text = str(detail_value)
        assert "Annex: G/Q13" in detail_text, (
            f"Detail line should mention 'Annex: G/Q13', got '{detail_text}'"
        )
        assert "Código: G51" in detail_text, (
            f"Detail line should mention 'Código: G51', got '{detail_text}'"
        )
        assert "Legal basis: CIRS art. 10(1)(e)" in detail_text, (
            f"Detail line should mention 'Legal basis: CIRS art. 10(1)(e)', got '{detail_text}'"
        )

    def test_detail_line_reads_values_from_first_entry(self):
        entries = [
            _make_derivatives_entry(
                annex_hint="G/Q13",
                operation_code="G51",
                legal_category="CIRS art. 10(1)(e)",
            ),
            _make_derivatives_entry(date="2025-02-01"),
        ]
        report = _make_crypto_tax_report(derivatives_entries=entries)
        wb = openpyxl.Workbook()
        write_derivatives_sheet(wb, report)

        ws = wb[_SHEET_NAME]
        detail_text = str(ws.cell(2, 1).value)
        # The detail line reads from the first entry; if a future edge case varies
        # these fields across rows, the sheet owner must extend the rendering.
        assert "Annex: G/Q13" in detail_text

    def test_detail_line_warns_when_entries_disagree_on_constant_fields(self, caplog):
        """Heterogeneous (annex_hint, operation_code, legal_category) must surface a warning.

        Today the three fields are constants across all derivatives rows, so the
        detail line is safe to render once from entries[0]. But that invariant is
        enforced by data inspection alone. If a future change (e.g. introduction of
        G52/G53/G54 per-row routing) ever produces heterogeneous values, the sheet
        must warn loudly rather than silently taking entries[0]. See review r1 Medium 1
        and development_lessons.md #77 (silent-overwrite hazard).
        """
        entries = [
            _make_derivatives_entry(
                annex_hint="G/Q13",
                operation_code="G51",
                legal_category="CIRS art. 10(1)(e)",
            ),
            _make_derivatives_entry(
                date="2025-02-01",
                annex_hint="G/Q14",
                operation_code="G52",
                legal_category="CIRS art. 10(1)(f)",
            ),
        ]
        report = _make_crypto_tax_report(derivatives_entries=entries)

        with caplog.at_level("WARNING", logger="tax_reporting.application.persisting.derivatives_sheet"):
            wb = openpyxl.Workbook()
            write_derivatives_sheet(wb, report)

        joined = " | ".join(rec.message for rec in caplog.records)
        assert "Derivatives P&L detail-line fields are heterogeneous" in joined, (
            f"Expected a warning surfacing heterogeneous detail fields, got: {joined!r}"
        )

    def test_detail_line_no_warning_when_entries_agree_on_constant_fields(self, caplog):
        """Homogeneous (annex_hint, operation_code, legal_category) must NOT warn."""
        entries = [
            _make_derivatives_entry(
                annex_hint="G/Q13",
                operation_code="G51",
                legal_category="CIRS art. 10(1)(e)",
            ),
            _make_derivatives_entry(date="2025-02-01"),
        ]
        report = _make_crypto_tax_report(derivatives_entries=entries)

        with caplog.at_level("WARNING", logger="tax_reporting.application.persisting.derivatives_sheet"):
            wb = openpyxl.Workbook()
            write_derivatives_sheet(wb, report)

        heterogeneity_warnings = [
            rec for rec in caplog.records if "heterogeneous" in rec.message.lower()
        ]
        assert not heterogeneity_warnings, (
            f"Expected no heterogeneity warning when entries agree, got: {[r.message for r in heterogeneity_warnings]}"
        )

    def test_detail_line_strips_control_chars_via_safe_cell_value(self):
        """Detail-line fields must pass through safe_cell_value before the cell write.

        The template prefix "Annex: " structurally prevents formula injection at the
        cell-start position, but control characters (newlines, carriage returns) in
        user-overridable fields would still corrupt cell rendering. Wrapping the
        formatted string also matches the per-row write convention in the same module
        (every user-overridable string field on the row path goes through
        safe_cell_value). See review r2 Low 1 and development_lessons.md #7.
        """
        entries = [
            _make_derivatives_entry(annex_hint="G/Q13\nG/Q14"),
        ]
        report = _make_crypto_tax_report(derivatives_entries=entries)
        wb = openpyxl.Workbook()
        write_derivatives_sheet(wb, report)

        ws = wb[_SHEET_NAME]
        detail_text = str(ws.cell(2, 1).value)
        assert "\n" not in detail_text, (
            f"Control char in annex_hint must be stripped by safe_cell_value; got {detail_text!r}"
        )
        assert "G/Q13" in detail_text, (
            f"Stripped detail line should still mention 'G/Q13'; got {detail_text!r}"
        )
        assert "G/Q14" in detail_text, (
            f"Stripped detail line should still mention 'G/Q14'; got {detail_text!r}"
        )

    def test_detail_line_omitted_when_no_entries(self):
        report = _make_crypto_tax_report(derivatives_entries=[])
        wb = openpyxl.Workbook()
        write_derivatives_sheet(wb, report)

        ws = wb[_SHEET_NAME]
        assert ws.cell(2, 1).value is None, (
            f"Detail line should be omitted when there are no entries; got '{ws.cell(2, 1).value}'"
        )

    def test_row_writes_operator_entity_and_country_in_columns_6_and_7(self):
        entries = [_make_derivatives_entry(operator_entity="ByBit", operator_country="AE")]
        report = _make_crypto_tax_report(derivatives_entries=entries)
        wb = openpyxl.Workbook()
        write_derivatives_sheet(wb, report)

        ws = wb[_SHEET_NAME]
        header_row = _find_row_with_value(ws, "Date")
        data_row = header_row + 1
        assert ws.cell(data_row, 6).value == "ByBit", (
            f"Column 6 should contain operator_entity 'ByBit', got '{ws.cell(data_row, 6).value}'"
        )
        assert ws.cell(data_row, 7).value == "AE", (
            f"Column 7 should contain operator_country 'AE', got '{ws.cell(data_row, 7).value}'"
        )

    def test_row_writes_event_count_in_column_8(self):
        entries = [_make_derivatives_entry(event_count=3)]
        report = _make_crypto_tax_report(derivatives_entries=entries)
        wb = openpyxl.Workbook()
        write_derivatives_sheet(wb, report)

        ws = wb[_SHEET_NAME]
        header_row = _find_row_with_value(ws, "Date")
        data_row = header_row + 1
        assert ws.cell(data_row, 8).value == 3, (
            f"Column 8 should contain event_count=3, got '{ws.cell(data_row, 8).value}'"
        )

    def test_row_writes_notes_in_column_9_when_set(self):
        entries = [_make_derivatives_entry(notes="manual annotation")]
        report = _make_crypto_tax_report(derivatives_entries=entries)
        wb = openpyxl.Workbook()
        write_derivatives_sheet(wb, report)

        ws = wb[_SHEET_NAME]
        header_row = _find_row_with_value(ws, "Date")
        data_row = header_row + 1
        assert ws.cell(data_row, 9).value == "manual annotation", (
            f"Column 9 should contain notes 'manual annotation', got '{ws.cell(data_row, 9).value}'"
        )

    def test_row_writes_notes_in_column_9_default_empty(self):
        report = _make_crypto_tax_report(derivatives_entries=[_make_derivatives_entry()])
        wb = openpyxl.Workbook()
        write_derivatives_sheet(wb, report)

        ws = wb[_SHEET_NAME]
        header_row = _find_row_with_value(ws, "Date")
        data_row = header_row + 1
        val = ws.cell(data_row, 9).value
        assert val is None or val == "", (
            f"Column 9 should be empty when notes is unset; got '{val!r}'"
        )

    def test_row_writes_review_in_column_10(self):
        entries = [
            _make_derivatives_entry(
                review_required=True,
                review_reason="missing platform mapping",
            ),
        ]
        report = _make_crypto_tax_report(derivatives_entries=entries)
        wb = openpyxl.Workbook()
        write_derivatives_sheet(wb, report)

        ws = wb[_SHEET_NAME]
        header_row = _find_row_with_value(ws, "Date")
        data_row = header_row + 1
        assert ws.cell(data_row, 10).value == "YES: missing platform mapping", (
            f"Column 10 should render 'YES: <reason>', got '{ws.cell(data_row, 10).value}'"
        )

    def test_review_fill_spans_all_ten_columns(self):
        entries = [
            _make_derivatives_entry(review_required=True, review_reason="missing platform mapping"),
        ]
        report = _make_crypto_tax_report(derivatives_entries=entries)
        wb = openpyxl.Workbook()
        write_derivatives_sheet(wb, report)

        ws = wb[_SHEET_NAME]
        header_row = _find_row_with_value(ws, "Date")
        data_row = header_row + 1
        for col in range(1, 11):
            cell = ws.cell(data_row, col)
            assert cell.fill.patternType == "solid", (
                f"Col {col} should have solid fill, got {cell.fill.patternType}"
            )
            assert cell.fill.fgColor.rgb == "FFFF0000", (
                f"Col {col} should have red fill (FFFF0000), got {cell.fill.fgColor.rgb}"
            )

    def test_total_row_pnl_in_column_5(self):
        entries = [
            _make_derivatives_entry(date="2025-01-12", pnl_eur=Decimal("140.18")),
            _make_derivatives_entry(date="2025-01-13", pnl_eur=Decimal("60.00")),
        ]
        report = _make_crypto_tax_report(derivatives_entries=entries)
        wb = openpyxl.Workbook()
        write_derivatives_sheet(wb, report)

        ws = wb[_SHEET_NAME]
        total_row = _find_row_with_value(ws, "Total")
        # Total row label stays at column 1; total P&L value stays at column 5 (unchanged)
        assert ws.cell(total_row, 1).value == "Total", (
            f"Total row label should be in column 1, got '{ws.cell(total_row, 1).value}'"
        )
        pnl_value = ws.cell(total_row, 5).value
        assert pnl_value is not None, "Total row should have a numeric value in column 5"
        assert Decimal(str(pnl_value)) == Decimal("200.18"), (
            f"Total row P&L should be 200.18 in column 5, got {pnl_value}"
        )

    def test_loss_footnote_still_rendered_when_loss_present(self):
        entries = [
            _make_derivatives_entry(
                date="2025-01-13",
                pnl_eur=Decimal("-271.79"),
                event_type=DerivativesEventType.LOSS,
            ),
        ]
        report = _make_crypto_tax_report(derivatives_entries=entries)
        wb = openpyxl.Workbook()
        write_derivatives_sheet(wb, report)

        ws = wb[_SHEET_NAME]
        total_row = _find_row_with_value(ws, "Total")
        # Footnote must appear AFTER the total row
        footnote_row = _find_row_containing(ws, "Losses are deductible")
        assert footnote_row > total_row, (
            f"Loss footnote (row {footnote_row}) should appear after total row (row {total_row})"
        )
