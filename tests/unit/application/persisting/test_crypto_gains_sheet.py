"""Tests for the crypto capital gains sheet writer."""

from decimal import Decimal

import openpyxl
import pytest
from openpyxl.styles import PatternFill

from tax_reporting.application.crypto_reporting import (
    CapitalGainPeriodStats,
    CryptoCapitalGainEntry,
    CryptoCapitalGainStats,
    CryptoReconciliationSummary,
    CryptoRewardIncomeEntry,
    CryptoTaxReport,
)
from tax_reporting.application.persisting.crypto_gains_sheet import write_crypto_gains_sheet
from tests.conftest import make_operator_origin


def _make_capital_entry(**overrides: object) -> CryptoCapitalGainEntry:
    defaults = {
        "disposal_date": "2025-06-15",
        "acquisition_date": "2025-01-10",
        "asset": "BTC",
        "amount": Decimal("0.5"),
        "cost_eur": Decimal("20000"),
        "proceeds_eur": Decimal("25000"),
        "gain_loss_eur": Decimal("5000"),
        "holding_period": "Short-term",
        "wallet": "Kraken",
        "platform": "Kraken",
        "chain": "Ethereum",
        "operator_origin": make_operator_origin(),
        "annex_hint": "J",
        "review_required": False,
        "notes": "",
    }
    defaults.update(overrides)
    return CryptoCapitalGainEntry(**defaults)  # type: ignore[arg-type]


def _make_stats() -> CryptoCapitalGainStats:
    short_term = CapitalGainPeriodStats(
        count=1,
        cost_total_eur=Decimal("20000"),
        proceeds_total_eur=Decimal("25000"),
        gain_loss_total_eur=Decimal("5000"),
    )
    empty = CapitalGainPeriodStats(
        count=0,
        cost_total_eur=Decimal("0"),
        proceeds_total_eur=Decimal("0"),
        gain_loss_total_eur=Decimal("0"),
    )
    grand_total = CapitalGainPeriodStats(
        count=1,
        cost_total_eur=Decimal("20000"),
        proceeds_total_eur=Decimal("25000"),
        gain_loss_total_eur=Decimal("5000"),
    )
    return CryptoCapitalGainStats(
        short_term=short_term, long_term=empty, mixed=empty, unknown=empty, grand_total=grand_total
    )


def _make_crypto_tax_report(  # noqa: PLR0913
    capital_entries: list[CryptoCapitalGainEntry] | None = None,
    stats: CryptoCapitalGainStats | None = None,
    reward_entries: list[CryptoRewardIncomeEntry] | None = None,
    pdf_summary: object = None,
    zero_basis_review_threshold: Decimal = Decimal("50"),
) -> CryptoTaxReport:

    entries = capital_entries if capital_entries is not None else [_make_capital_entry()]
    reconciliation = CryptoReconciliationSummary(
        capital_rows=len(entries),
        reward_rows=len(reward_entries) if reward_entries else 0,
        short_term_rows=sum(1 for e in entries if e.holding_period.lower().startswith("short")),
        long_term_rows=sum(1 for e in entries if e.holding_period.lower().startswith("long")),
        mixed_rows=sum(1 for e in entries if e.holding_period.lower() == "mixed"),
        unknown_rows=sum(1 for e in entries if e.holding_period.lower() == "unknown"),
        capital_cost_total_eur=sum((e.cost_eur for e in entries), start=Decimal("0")),
        capital_proceeds_total_eur=sum((e.proceeds_eur for e in entries), start=Decimal("0")),
        capital_gain_total_eur=sum((e.gain_loss_eur for e in entries), start=Decimal("0")),
        reward_total_eur=Decimal("0"),
        opening_holdings=None,
        closing_holdings=None,
    )
    return CryptoTaxReport(
        tax_year=2025,
        capital_entries=entries,
        reward_entries=reward_entries or [],
        reconciliation=reconciliation,
        capital_gain_stats=stats or _make_stats(),
        pdf_summary=pdf_summary,  # type: ignore[arg-type]
        zero_basis_review_threshold=zero_basis_review_threshold,
    )


@pytest.mark.unit
class TestCryptoGainsSheetName:
    """Tests that the sheet is created with the correct name."""

    def test_sheet_named_crypto_gains(self):
        wb = openpyxl.Workbook()
        report = _make_crypto_tax_report()
        write_crypto_gains_sheet(wb, report)
        assert "Crypto Gains" in wb.sheetnames


@pytest.mark.unit
class TestCryptoGainsSheetTitleAndMetadata:
    """Tests that the sheet writes title, tax year, and PDF summary."""

    def test_title_row_present(self):
        wb = openpyxl.Workbook()
        report = _make_crypto_tax_report()
        write_crypto_gains_sheet(wb, report)
        ws = wb["Crypto Gains"]
        assert ws.cell(1, 1).value == "CRYPTO TAX REPORT - PORTUGAL"

    def test_title_is_bold(self):
        wb = openpyxl.Workbook()
        report = _make_crypto_tax_report()
        write_crypto_gains_sheet(wb, report)
        ws = wb["Crypto Gains"]
        assert ws.cell(1, 1).font.bold is True

    def test_tax_year_written(self):
        wb = openpyxl.Workbook()
        report = _make_crypto_tax_report()
        write_crypto_gains_sheet(wb, report)
        ws = wb["Crypto Gains"]
        assert ws.cell(2, 1).value == "Tax year"
        assert ws.cell(2, 2).value == 2025

    def test_pdf_summary_written_when_present(self):
        from tax_reporting.application.crypto_reporting import CryptoCompletePdfSummary

        pdf = CryptoCompletePdfSummary(
            period="01 Jan 2025 to 31 Dec 2025", timezone="Europe/Lisbon", extracted_tokens=42
        )
        report = _make_crypto_tax_report(pdf_summary=pdf)
        wb = openpyxl.Workbook()
        write_crypto_gains_sheet(wb, report)
        ws = wb["Crypto Gains"]
        assert ws.cell(3, 1).value == "PDF period"
        assert ws.cell(3, 2).value == "01 Jan 2025 to 31 Dec 2025"
        assert ws.cell(3, 3).value == "PDF timezone"
        assert ws.cell(3, 4).value == "Europe/Lisbon"

    def test_pdf_summary_absent_no_pdf_row(self):
        report = _make_crypto_tax_report()
        wb = openpyxl.Workbook()
        write_crypto_gains_sheet(wb, report)
        ws = wb["Crypto Gains"]
        assert ws.cell(3, 1).value is None


@pytest.mark.unit
class TestCryptoGainsSheetCapitalEntries:
    """Tests that capital gain entries are written in 17 columns."""

    CAPITAL_HEADERS = [
        "Disposal date",
        "Acquisition date",
        "Asset",
        "Quantity",
        "Acquisition Cost (EUR)",
        "Disposal Proceeds (EUR)",
        "Gain/Loss (EUR)",
        "Holding period",
        "Wallet",
        "Platform",
        "Disposal chain",
        "Operator entity",
        "Operator country",
        "Annex hint",
        "Review flag",
        "Notes",
        "Token origin",
    ]

    def test_section_1_title_written(self):
        wb = openpyxl.Workbook()
        report = _make_crypto_tax_report()
        write_crypto_gains_sheet(wb, report)
        ws = wb["Crypto Gains"]
        found = False
        for row in ws.iter_rows(min_row=1, max_row=ws.max_row, min_col=1, max_col=1):
            if row[0].value == "1. CAPITAL GAINS":
                found = True
                break
        assert found

    def test_section_1_title_is_bold(self):
        wb = openpyxl.Workbook()
        report = _make_crypto_tax_report()
        write_crypto_gains_sheet(wb, report)
        ws = wb["Crypto Gains"]
        for row in ws.iter_rows(min_row=1, max_row=ws.max_row, min_col=1, max_col=1):
            if row[0].value == "1. CAPITAL GAINS":
                assert row[0].font.bold is True
                break

    def test_capital_headers_written(self):
        wb = openpyxl.Workbook()
        report = _make_crypto_tax_report()
        write_crypto_gains_sheet(wb, report)
        ws = wb["Crypto Gains"]
        header_row = None
        for r in range(1, ws.max_row + 1):
            if ws.cell(r, 1).value == "Disposal date":
                header_row = r
                break
        assert header_row is not None
        for idx, expected in enumerate(self.CAPITAL_HEADERS, start=1):
            assert ws.cell(header_row, idx).value == expected

    def test_capital_entry_values(self):
        entry = _make_capital_entry()
        report = _make_crypto_tax_report(capital_entries=[entry])
        wb = openpyxl.Workbook()
        write_crypto_gains_sheet(wb, report)
        ws = wb["Crypto Gains"]
        header_row = None
        for r in range(1, ws.max_row + 1):
            if ws.cell(r, 1).value == "Disposal date":
                header_row = r
                break
        assert header_row is not None
        data_row = header_row + 1
        assert ws.cell(data_row, 1).value == "2025-06-15"
        assert ws.cell(data_row, 2).value == "2025-01-10"
        assert ws.cell(data_row, 3).value == "BTC"
        assert ws.cell(data_row, 4).value == Decimal("0.5")
        assert ws.cell(data_row, 5).value == Decimal("20000")
        assert ws.cell(data_row, 6).value == Decimal("25000")
        assert ws.cell(data_row, 7).value == Decimal("5000")
        assert ws.cell(data_row, 8).value == "Short-term"
        assert ws.cell(data_row, 9).value == "Kraken"
        assert ws.cell(data_row, 10).value == "Kraken"
        assert ws.cell(data_row, 11).value == "Ethereum"
        assert ws.cell(data_row, 12).value == "Test Entity"
        assert ws.cell(data_row, 13).value == "US"
        assert ws.cell(data_row, 14).value == "J"
        assert ws.cell(data_row, 15).value == "NO"
        assert ws.cell(data_row, 16).value == ""
        assert ws.cell(data_row, 17).value == ""

    def test_capital_entry_review_flag_yes_with_reason(self):
        entry = _make_capital_entry(review_required=True, review_reason="Missing cost basis")
        report = _make_crypto_tax_report(capital_entries=[entry])
        wb = openpyxl.Workbook()
        write_crypto_gains_sheet(wb, report)
        ws = wb["Crypto Gains"]
        header_row = None
        for r in range(1, ws.max_row + 1):
            if ws.cell(r, 1).value == "Disposal date":
                header_row = r
                break
        data_row = header_row + 1
        assert ws.cell(data_row, 15).value == "YES: Missing cost basis"

    def test_token_origin_written(self):
        entry = _make_capital_entry(token_swap_history="ETH (swap_conversion, high confidence)")
        report = _make_crypto_tax_report(capital_entries=[entry])
        wb = openpyxl.Workbook()
        write_crypto_gains_sheet(wb, report)
        ws = wb["Crypto Gains"]
        header_row = None
        for r in range(1, ws.max_row + 1):
            if ws.cell(r, 1).value == "Disposal date":
                header_row = r
                break
        data_row = header_row + 1
        assert ws.cell(data_row, 17).value == "ETH (swap_conversion, high confidence)"

    def test_multiple_entries_on_separate_rows(self):
        entry1 = _make_capital_entry(asset="BTC", disposal_date="2025-01-15")
        entry2 = _make_capital_entry(asset="ETH", disposal_date="2025-02-20")
        report = _make_crypto_tax_report(capital_entries=[entry1, entry2])
        wb = openpyxl.Workbook()
        write_crypto_gains_sheet(wb, report)
        ws = wb["Crypto Gains"]
        header_row = None
        for r in range(1, ws.max_row + 1):
            if ws.cell(r, 1).value == "Disposal date":
                header_row = r
                break
        assert ws.cell(header_row + 1, 3).value == "BTC"
        assert ws.cell(header_row + 2, 3).value == "ETH"


@pytest.mark.unit
class TestCryptoGainsSheetStatistics:
    """Tests for the 1b. CAPITAL GAINS STATISTICS section."""

    STATS_HEADERS = [
        "Holding Period",
        "Count",
        "Acquisition Cost Total (EUR)",
        "Disposal Proceeds Total (EUR)",
        "Gain/Loss Total (EUR)",
    ]

    def test_statistics_section_title_written(self):
        wb = openpyxl.Workbook()
        report = _make_crypto_tax_report()
        write_crypto_gains_sheet(wb, report)
        ws = wb["Crypto Gains"]
        found = False
        for row in ws.iter_rows(min_row=1, max_row=ws.max_row, min_col=1, max_col=1):
            if row[0].value == "1b. CAPITAL GAINS STATISTICS":
                found = True
                break
        assert found

    def test_statistics_section_title_is_bold(self):
        wb = openpyxl.Workbook()
        report = _make_crypto_tax_report()
        write_crypto_gains_sheet(wb, report)
        ws = wb["Crypto Gains"]
        for row in ws.iter_rows(min_row=1, max_row=ws.max_row, min_col=1, max_col=1):
            if row[0].value == "1b. CAPITAL GAINS STATISTICS":
                assert row[0].font.bold is True
                break

    def test_statistics_headers_written(self):
        wb = openpyxl.Workbook()
        report = _make_crypto_tax_report()
        write_crypto_gains_sheet(wb, report)
        ws = wb["Crypto Gains"]
        stats_title_row = None
        for r in range(1, ws.max_row + 1):
            if ws.cell(r, 1).value == "1b. CAPITAL GAINS STATISTICS":
                stats_title_row = r
                break
        assert stats_title_row is not None
        header_row = stats_title_row + 1
        for idx, expected in enumerate(self.STATS_HEADERS, start=1):
            assert ws.cell(header_row, idx).value == expected

    def test_statistics_headers_are_bold(self):
        wb = openpyxl.Workbook()
        report = _make_crypto_tax_report()
        write_crypto_gains_sheet(wb, report)
        ws = wb["Crypto Gains"]
        stats_title_row = None
        for r in range(1, ws.max_row + 1):
            if ws.cell(r, 1).value == "1b. CAPITAL GAINS STATISTICS":
                stats_title_row = r
                break
        header_row = stats_title_row + 1
        for idx in range(1, len(self.STATS_HEADERS) + 1):
            assert ws.cell(header_row, idx).font.bold is True

    def test_statistics_period_rows(self):
        wb = openpyxl.Workbook()
        report = _make_crypto_tax_report()
        write_crypto_gains_sheet(wb, report)
        ws = wb["Crypto Gains"]
        stats_title_row = None
        for r in range(1, ws.max_row + 1):
            if ws.cell(r, 1).value == "1b. CAPITAL GAINS STATISTICS":
                stats_title_row = r
                break
        data_start = stats_title_row + 2
        assert ws.cell(data_start, 1).value == "Short-term"
        assert ws.cell(data_start, 2).value == 1
        assert ws.cell(data_start + 1, 1).value == "Long-term"
        assert ws.cell(data_start + 1, 2).value == 0
        assert ws.cell(data_start + 2, 1).value == "Mixed"
        assert ws.cell(data_start + 3, 1).value == "Unknown"
        assert ws.cell(data_start + 4, 1).value == "Grand Total"

    def test_statistics_values_match_report(self):
        wb = openpyxl.Workbook()
        report = _make_crypto_tax_report()
        write_crypto_gains_sheet(wb, report)
        ws = wb["Crypto Gains"]
        stats_title_row = None
        for r in range(1, ws.max_row + 1):
            if ws.cell(r, 1).value == "1b. CAPITAL GAINS STATISTICS":
                stats_title_row = r
                break
        data_start = stats_title_row + 2
        assert ws.cell(data_start, 3).value == Decimal("20000")
        assert ws.cell(data_start, 4).value == Decimal("25000")
        assert ws.cell(data_start, 5).value == Decimal("5000")


@pytest.mark.unit
class TestCryptoGainsSheetAutoWidth:
    """Tests that auto_column_width is called."""

    def test_auto_width_adjusts_columns(self):
        wb = openpyxl.Workbook()
        report = _make_crypto_tax_report()
        write_crypto_gains_sheet(wb, report)
        ws = wb["Crypto Gains"]
        assert ws.column_dimensions["A"].width > 0

    def test_column_widths_respect_max_cell_width_cap(self):
        """Verify no column exceeds MAX_CELL_WIDTH + 2 even with long token origins."""
        from tax_reporting.application.persisting.excel_utils import MAX_CELL_WIDTH

        wb = openpyxl.Workbook()
        report = _make_crypto_tax_report()
        write_crypto_gains_sheet(wb, report)
        ws = wb["Crypto Gains"]

        # All column widths should be capped at MAX_CELL_WIDTH + 2
        max_allowed = MAX_CELL_WIDTH + 2
        for col_letter, col_dim in ws.column_dimensions.items():
            if col_dim.width is not None:
                assert (
                    col_dim.width <= max_allowed
                ), f"Column {col_letter} width {col_dim.width} exceeds cap {max_allowed}"

    def test_all_columns_have_reasonable_widths(self):
        """Verify no column is collapsed: all have width >= MIN_DATA_WIDTH floor."""
        wb = openpyxl.Workbook()
        report = _make_crypto_tax_report()
        write_crypto_gains_sheet(wb, report)
        ws = wb["Crypto Gains"]

        for col_idx in range(1, 18):  # Columns A through Q
            col_letter = openpyxl.utils.get_column_letter(col_idx)
            width = ws.column_dimensions[col_letter].width
            assert width is not None, f"Column {col_letter} should have a width set"
            assert width >= 4, f"Column {col_letter} width {width} is too small"


@pytest.mark.unit
class TestCryptoGainsSheetEmptyEntries:
    """Tests handling of empty capital entries list."""

    def test_empty_entries_writes_headers_no_data(self):
        report = _make_crypto_tax_report(capital_entries=[])
        wb = openpyxl.Workbook()
        write_crypto_gains_sheet(wb, report)
        ws = wb["Crypto Gains"]
        header_row = None
        for r in range(1, ws.max_row + 1):
            if ws.cell(r, 1).value == "Disposal date":
                header_row = r
                break
        assert header_row is not None
        next_value = ws.cell(header_row + 1, 1).value
        assert next_value is None or "1b. CAPITAL GAINS STATISTICS" in str(next_value)


_RED_FILL = PatternFill(start_color="FFFF0000", end_color="FFFF0000", fill_type="solid")
_NUM_CAPITAL_COLUMNS = 17


def _find_header_row(ws: openpyxl.worksheet.worksheet.Worksheet) -> int:
    for r in range(1, ws.max_row + 1):
        if ws.cell(r, 1).value == "Disposal date":
            return r
    raise AssertionError("Header row not found")


def _is_red_fill(cell: openpyxl.cell.cell.Cell) -> bool:
    fill = cell.fill
    return (
        fill.start_color.rgb == "FFFF0000"
        and fill.end_color.rgb == "FFFF0000"
        and fill.fill_type == "solid"
    )


@pytest.mark.unit
class TestCryptoGainsSheetZeroCostRedBackground:
    """Tests for red background rendering on zero-cost entries above threshold."""

    def test_render_zero_cost_entry_has_red_background(self):
        entry = _make_capital_entry(cost_eur=Decimal("0"), gain_loss_eur=Decimal("500"))
        report = _make_crypto_tax_report(capital_entries=[entry])
        wb = openpyxl.Workbook()
        write_crypto_gains_sheet(wb, report)
        ws = wb["Crypto Gains"]
        data_row = _find_header_row(ws) + 1
        for col in range(1, _NUM_CAPITAL_COLUMNS + 1):
            assert _is_red_fill(ws.cell(data_row, col)), f"Column {col} should have red fill"

    def test_render_zero_cost_below_threshold_no_red_background(self):
        entry = _make_capital_entry(cost_eur=Decimal("0"), gain_loss_eur=Decimal("0.5"))
        report = _make_crypto_tax_report(capital_entries=[entry])
        wb = openpyxl.Workbook()
        write_crypto_gains_sheet(wb, report)
        ws = wb["Crypto Gains"]
        data_row = _find_header_row(ws) + 1
        for col in range(1, _NUM_CAPITAL_COLUMNS + 1):
            assert not _is_red_fill(ws.cell(data_row, col)), f"Column {col} should NOT have red fill"

    def test_render_nonzero_cost_no_red_background(self):
        entry = _make_capital_entry(cost_eur=Decimal("100"), gain_loss_eur=Decimal("5000"))
        report = _make_crypto_tax_report(capital_entries=[entry])
        wb = openpyxl.Workbook()
        write_crypto_gains_sheet(wb, report)
        ws = wb["Crypto Gains"]
        data_row = _find_header_row(ws) + 1
        for col in range(1, _NUM_CAPITAL_COLUMNS + 1):
            assert not _is_red_fill(ws.cell(data_row, col)), f"Column {col} should NOT have red fill"

    def test_render_normal_row_no_red_background(self):
        entry = _make_capital_entry(cost_eur=Decimal("20000"), gain_loss_eur=Decimal("5000"))
        report = _make_crypto_tax_report(capital_entries=[entry])
        wb = openpyxl.Workbook()
        write_crypto_gains_sheet(wb, report)
        ws = wb["Crypto Gains"]
        data_row = _find_header_row(ws) + 1
        for col in range(1, _NUM_CAPITAL_COLUMNS + 1):
            assert not _is_red_fill(ws.cell(data_row, col)), f"Column {col} should NOT have red fill"

    def test_render_zero_cost_at_exact_threshold_has_red_background(self):
        """Gain/loss exactly equal to threshold must trigger red fill (>= boundary)."""
        entry = _make_capital_entry(cost_eur=Decimal("0"), gain_loss_eur=Decimal("50"))
        report = _make_crypto_tax_report(
            capital_entries=[entry], zero_basis_review_threshold=Decimal("50")
        )
        wb = openpyxl.Workbook()
        write_crypto_gains_sheet(wb, report)
        ws = wb["Crypto Gains"]
        data_row = _find_header_row(ws) + 1
        for col in range(1, _NUM_CAPITAL_COLUMNS + 1):
            assert _is_red_fill(ws.cell(data_row, col)), f"Column {col} should have red fill at threshold"

    def test_render_zero_cost_just_below_threshold_no_red_background(self):
        """Gain/loss just below threshold must NOT trigger red fill."""
        entry = _make_capital_entry(cost_eur=Decimal("0"), gain_loss_eur=Decimal("49.99"))
        report = _make_crypto_tax_report(
            capital_entries=[entry], zero_basis_review_threshold=Decimal("50")
        )
        wb = openpyxl.Workbook()
        write_crypto_gains_sheet(wb, report)
        ws = wb["Crypto Gains"]
        data_row = _find_header_row(ws) + 1
        for col in range(1, _NUM_CAPITAL_COLUMNS + 1):
            assert not _is_red_fill(ws.cell(data_row, col)), f"Column {col} should NOT have red fill below threshold"


_BLUE_FILL = PatternFill(start_color="FFCCFFFF", end_color="FFCCFFFF", fill_type="solid")


def _is_blue_fill(cell: openpyxl.cell.cell.Cell) -> bool:
    fill = cell.fill
    return (
        fill.start_color.rgb == "FFCCFFFF"
        and fill.end_color.rgb == "FFCCFFFF"
        and fill.fill_type == "solid"
    )


@pytest.mark.unit
class TestCryptoGainsSheetMultiDateBlueBackground:
    """Tests for blue background rendering on multi-acquisition-date entries."""

    def test_render_multi_date_entry_has_blue_background(self):
        """Entry with multi_acquisition_dates=True and review_required=False gets blue fill."""
        entry = _make_capital_entry(
            multi_acquisition_dates=True,
            notes="Acquired: 2024-04-13, 2024-04-19 (2 lots)",
        )
        report = _make_crypto_tax_report(capital_entries=[entry])
        wb = openpyxl.Workbook()
        write_crypto_gains_sheet(wb, report)
        ws = wb["Crypto Gains"]
        data_row = _find_header_row(ws) + 1
        for col in range(1, _NUM_CAPITAL_COLUMNS + 1):
            assert _is_blue_fill(ws.cell(data_row, col)), f"Column {col} should have blue fill"

    def test_render_review_required_takes_precedence_over_blue(self):
        """Entry with multi_acquisition_dates=True and review_required=True gets red fill, not blue."""
        entry = _make_capital_entry(
            multi_acquisition_dates=True,
            review_required=True,
            review_reason="Test reason",
            notes="",
        )
        report = _make_crypto_tax_report(capital_entries=[entry])
        wb = openpyxl.Workbook()
        write_crypto_gains_sheet(wb, report)
        ws = wb["Crypto Gains"]
        data_row = _find_header_row(ws) + 1
        for col in range(1, _NUM_CAPITAL_COLUMNS + 1):
            assert _is_red_fill(ws.cell(data_row, col)), f"Column {col} should have red fill (precedence)"
            assert not _is_blue_fill(ws.cell(data_row, col)), f"Column {col} should NOT have blue fill"

    def test_render_single_date_entry_no_background(self):
        """Entry with multi_acquisition_dates=False has no fill (default)."""
        entry = _make_capital_entry(multi_acquisition_dates=False)
        report = _make_crypto_tax_report(capital_entries=[entry])
        wb = openpyxl.Workbook()
        write_crypto_gains_sheet(wb, report)
        ws = wb["Crypto Gains"]
        data_row = _find_header_row(ws) + 1
        for col in range(1, _NUM_CAPITAL_COLUMNS + 1):
            cell = ws.cell(data_row, col)
            assert not _is_red_fill(cell), f"Column {col} should NOT have red fill"
            assert not _is_blue_fill(cell), f"Column {col} should NOT have blue fill"

    def test_render_zero_cost_red_takes_precedence_over_blue(self):
        """Zero-cost entry above threshold gets red fill even with multi_acquisition_dates=True."""
        entry = _make_capital_entry(
            cost_eur=Decimal("0"),
            gain_loss_eur=Decimal("100"),
            multi_acquisition_dates=True,
        )
        report = _make_crypto_tax_report(capital_entries=[entry])
        wb = openpyxl.Workbook()
        write_crypto_gains_sheet(wb, report)
        ws = wb["Crypto Gains"]
        data_row = _find_header_row(ws) + 1
        for col in range(1, _NUM_CAPITAL_COLUMNS + 1):
            assert _is_red_fill(ws.cell(data_row, col)), f"Column {col} should have red fill (zero-cost)"
            assert not _is_blue_fill(ws.cell(data_row, col)), f"Column {col} should NOT have blue fill"
