"""Tests for IB reporting sheet writer and currency table."""

from decimal import Decimal

import openpyxl
import pytest

from shares_reporting.application.persisting.ib_sheet import (
    create_currency_table,
    write_ib_reporting_sheet,
)
from shares_reporting.domain.collections import CapitalGainLinesPerCompany, DividendIncomePerCompany
from shares_reporting.domain.constants import EXCEL_HEADER_ROW_1, EXCEL_HEADER_ROW_2, EXCEL_START_ROW
from shares_reporting.domain.entities import (
    CapitalGainLine,
    CurrencyCompany,
    DividendIncomePerSecurity,
)
from shares_reporting.domain.value_objects import Company, Currency, TradeDate
from shares_reporting.infrastructure.config import Config, ConversionRate


def _make_capital_gain_line(  # noqa: PLR0913
    sell_date: TradeDate | None = None,
    buy_date: TradeDate | None = None,
    currency: Currency | None = None,
    sell_quantities: list[Decimal] | None = None,
    buy_quantities: list[Decimal] | None = None,
    sell_prices: list[Decimal] | None = None,
    buy_prices: list[Decimal] | None = None,
    sell_fees: list[Decimal] | None = None,
    buy_fees: list[Decimal] | None = None,
) -> CapitalGainLine:
    """Helper to create a CapitalGainLine with minimal setup."""
    from shares_reporting.domain.entities import TradeAction

    _sell_date = sell_date or TradeDate(2025, 6, 15)
    _buy_date = buy_date or TradeDate(2024, 3, 10)
    _currency = currency or Currency("USD")
    sq = sell_quantities or [Decimal("10")]
    bq = buy_quantities or [Decimal("10")]
    sp = sell_prices or [Decimal("100")]
    bp = buy_prices or [Decimal("80")]
    sf = sell_fees or [Decimal("1")]
    bf = buy_fees or [Decimal("1")]

    sell_trades = []
    for p, f in zip(sp, sf, strict=True):
        sell_trades.append(
            TradeAction(
                company=Company("AAPL"),
                date_time="2025-06-15, 10:00:00",
                currency=_currency,
                quantity="-10",
                price=str(p),
                fee=str(f),
            )
        )

    buy_trades = []
    for p, f in zip(bp, bf, strict=True):
        buy_trades.append(
            TradeAction(
                company=Company("AAPL"),
                date_time="2024-03-10, 10:00:00",
                currency=_currency,
                quantity="10",
                price=str(p),
                fee=str(f),
            )
        )

    return CapitalGainLine(
        ticker="AAPL",
        currency=_currency,
        sell_date=_sell_date,
        sell_quantities=sq,
        sell_trades=sell_trades,
        buy_date=_buy_date,
        buy_quantities=bq,
        buy_trades=buy_trades,
    )


def _make_config() -> Config:
    """Create a test config with USD/EUR rate."""
    return Config(
        base="EUR",
        rates=[ConversionRate(base="EUR", calculated="USD", rate=Decimal("1.10"))],
    )


@pytest.mark.unit
class TestCreateCurrencyTable:
    """Tests for create_currency_table."""

    def test_writes_title_in_first_cell(self):
        wb = openpyxl.Workbook()
        ws = wb.active
        config = _make_config()
        create_currency_table(ws, column_no=1, row_no=1, config=config)
        assert ws.cell(1, 1).value == "Currency exchange rate"

    def test_writes_headers_in_row_below_title(self):
        wb = openpyxl.Workbook()
        ws = wb.active
        config = _make_config()
        create_currency_table(ws, column_no=1, row_no=1, config=config)
        assert ws.cell(2, 1).value == "Base/target"
        assert ws.cell(2, 2).value == "Rate"

    def test_returns_coordinate_map_with_base_currency(self):
        wb = openpyxl.Workbook()
        ws = wb.active
        config = _make_config()
        result = create_currency_table(ws, column_no=1, row_no=1, config=config)
        assert "USD" in result
        assert "EUR" in result

    def test_writes_rate_value_in_cell(self):
        wb = openpyxl.Workbook()
        ws = wb.active
        config = _make_config()
        create_currency_table(ws, column_no=1, row_no=1, config=config)
        rate_cell = ws.cell(3, 2)
        assert rate_cell.value == "1.10"

    def test_writes_base_self_rate_as_one(self):
        wb = openpyxl.Workbook()
        ws = wb.active
        config = _make_config()
        create_currency_table(ws, column_no=1, row_no=1, config=config)
        base_cell = ws.cell(4, 2)
        assert base_cell.value == "1"

    def test_offsets_correctly_with_nonzero_start(self):
        wb = openpyxl.Workbook()
        ws = wb.active
        config = _make_config()
        result = create_currency_table(ws, column_no=5, row_no=10, config=config)
        assert ws.cell(10, 5).value == "Currency exchange rate"
        assert ws.cell(11, 5).value == "Base/target"
        assert ws.cell(11, 6).value == "Rate"
        assert "USD" in result

    def test_both_headers_in_separate_columns(self):
        wb = openpyxl.Workbook()
        ws = wb.active
        config = _make_config()
        create_currency_table(ws, column_no=3, row_no=1, config=config)
        assert ws.cell(2, 3).value == "Base/target"
        assert ws.cell(2, 4).value == "Rate"


@pytest.mark.unit
class TestWriteIbReportingSheetHeaders:
    """Tests that write_ib_reporting_sheet writes correct header rows."""

    def test_writes_first_header_row(self):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Reporting"
        config = _make_config()
        lines: CapitalGainLinesPerCompany = {}
        write_ib_reporting_sheet(ws, config, lines)
        assert ws.cell(EXCEL_HEADER_ROW_1, 1).value == "Beneficiary"
        assert ws.cell(EXCEL_HEADER_ROW_1, 3).value == "SALE"

    def test_writes_second_header_row(self):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Reporting"
        config = _make_config()
        lines: CapitalGainLinesPerCompany = {}
        write_ib_reporting_sheet(ws, config, lines)
        assert ws.cell(EXCEL_HEADER_ROW_2, 3).value == "Day "


@pytest.mark.unit
class TestWriteIbReportingSheetCapitalGains:
    """Tests that capital gain data rows are written correctly."""

    def test_writes_sell_day_for_capital_gain_line(self):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Reporting"
        config = _make_config()
        line = _make_capital_gain_line(sell_date=TradeDate(2025, 6, 15))
        cc = CurrencyCompany(Currency("USD"), Company("AAPL", country_of_issuance="US"))
        lines: CapitalGainLinesPerCompany = {cc: [line]}
        write_ib_reporting_sheet(ws, config, lines)
        assert ws.cell(EXCEL_START_ROW, 3).value == 15

    def test_writes_sell_month_name(self):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Reporting"
        config = _make_config()
        line = _make_capital_gain_line(sell_date=TradeDate(2025, 6, 15))
        cc = CurrencyCompany(Currency("USD"), Company("AAPL", country_of_issuance="US"))
        lines: CapitalGainLinesPerCompany = {cc: [line]}
        write_ib_reporting_sheet(ws, config, lines)
        assert ws.cell(EXCEL_START_ROW, 4).value == "June"

    def test_writes_sell_year(self):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Reporting"
        config = _make_config()
        line = _make_capital_gain_line(sell_date=TradeDate(2025, 6, 15))
        cc = CurrencyCompany(Currency("USD"), Company("AAPL", country_of_issuance="US"))
        lines: CapitalGainLinesPerCompany = {cc: [line]}
        write_ib_reporting_sheet(ws, config, lines)
        assert ws.cell(EXCEL_START_ROW, 5).value == 2025

    def test_sell_amount_is_formula(self):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Reporting"
        config = _make_config()
        line = _make_capital_gain_line()
        cc = CurrencyCompany(Currency("USD"), Company("AAPL", country_of_issuance="US"))
        lines: CapitalGainLinesPerCompany = {cc: [line]}
        write_ib_reporting_sheet(ws, config, lines)
        sell_amount_cell = ws.cell(EXCEL_START_ROW, 6)
        assert sell_amount_cell.data_type == "f"
        assert sell_amount_cell.value.startswith("=")

    def test_buy_day_for_capital_gain_line(self):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Reporting"
        config = _make_config()
        line = _make_capital_gain_line(buy_date=TradeDate(2024, 3, 10))
        cc = CurrencyCompany(Currency("USD"), Company("AAPL", country_of_issuance="US"))
        lines: CapitalGainLinesPerCompany = {cc: [line]}
        write_ib_reporting_sheet(ws, config, lines)
        assert ws.cell(EXCEL_START_ROW, 7).value == 10

    def test_buy_amount_is_formula(self):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Reporting"
        config = _make_config()
        line = _make_capital_gain_line()
        cc = CurrencyCompany(Currency("USD"), Company("AAPL", country_of_issuance="US"))
        lines: CapitalGainLinesPerCompany = {cc: [line]}
        write_ib_reporting_sheet(ws, config, lines)
        buy_amount_cell = ws.cell(EXCEL_START_ROW, 10)
        assert buy_amount_cell.data_type == "f"

    def test_expense_cell_is_formula(self):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Reporting"
        config = _make_config()
        line = _make_capital_gain_line()
        cc = CurrencyCompany(Currency("USD"), Company("AAPL", country_of_issuance="US"))
        lines: CapitalGainLinesPerCompany = {cc: [line]}
        write_ib_reporting_sheet(ws, config, lines)
        expense_cell = ws.cell(EXCEL_START_ROW, 13)
        assert expense_cell.data_type == "f"
        assert expense_cell.number_format == "0.00"

    def test_country_of_source_populated(self):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Reporting"
        config = _make_config()
        line = _make_capital_gain_line()
        cc = CurrencyCompany(Currency("USD"), Company("AAPL", country_of_issuance="US"))
        lines: CapitalGainLinesPerCompany = {cc: [line]}
        write_ib_reporting_sheet(ws, config, lines)
        assert ws.cell(EXCEL_START_ROW, 2).value == "US"
        assert ws.cell(EXCEL_START_ROW, 11).value == "US"

    def test_symbol_and_currency_written(self):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Reporting"
        config = _make_config()
        line = _make_capital_gain_line()
        cc = CurrencyCompany(Currency("USD"), Company("AAPL", country_of_issuance="US"))
        lines: CapitalGainLinesPerCompany = {cc: [line]}
        write_ib_reporting_sheet(ws, config, lines)
        assert ws.cell(EXCEL_START_ROW, 15).value == "AAPL"
        assert ws.cell(EXCEL_START_ROW, 16).value == "USD"

    def test_multiple_lines_write_on_separate_rows(self):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Reporting"
        config = _make_config()
        line1 = _make_capital_gain_line(sell_date=TradeDate(2025, 1, 5))
        line2 = _make_capital_gain_line(sell_date=TradeDate(2025, 2, 10))
        cc = CurrencyCompany(Currency("USD"), Company("AAPL", country_of_issuance="US"))
        lines: CapitalGainLinesPerCompany = {cc: [line1, line2]}
        write_ib_reporting_sheet(ws, config, lines)
        assert ws.cell(EXCEL_START_ROW, 3).value == 5
        assert ws.cell(EXCEL_START_ROW + 1, 3).value == 10

    def test_placeholder_buy_row_has_red_fill(self):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Reporting"
        config = _make_config()
        line = _make_capital_gain_line(buy_date=TradeDate(1000, 1, 1))
        cc = CurrencyCompany(Currency("USD"), Company("AAPL", country_of_issuance="US"))
        lines: CapitalGainLinesPerCompany = {cc: [line]}
        write_ib_reporting_sheet(ws, config, lines)
        cell = ws.cell(EXCEL_START_ROW, 3)
        assert cell.fill.start_color.rgb == "FFFF0000"


@pytest.mark.unit
class TestWriteIbReportingSheetDividends:
    """Tests that dividend section is written correctly."""

    def test_section_title_written_when_dividends_provided(self):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Reporting"
        config = _make_config()
        lines: CapitalGainLinesPerCompany = {}
        dividends: DividendIncomePerCompany = {
            "AAPL": DividendIncomePerSecurity(
                symbol="AAPL",
                isin="US0378331005",
                country="US",
                gross_amount=Decimal("100"),
                total_taxes=Decimal("15"),
                currency=Currency("USD"),
            )
        }
        write_ib_reporting_sheet(ws, config, lines, dividends)
        found = False
        for row in ws.iter_rows(min_row=1, max_row=ws.max_row, min_col=1, max_col=1):
            if row[0].value and "CAPITAL INVESTMENT INCOME" in str(row[0].value):
                found = True
                break
        assert found

    def test_dividend_data_row_values(self):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Reporting"
        config = _make_config()
        lines: CapitalGainLinesPerCompany = {}
        dividends: DividendIncomePerCompany = {
            "AAPL": DividendIncomePerSecurity(
                symbol="AAPL",
                isin="US0378331005",
                country="US",
                gross_amount=Decimal("100"),
                total_taxes=Decimal("15"),
                currency=Currency("USD"),
            )
        }
        write_ib_reporting_sheet(ws, config, lines, dividends)
        div_type_cell = None
        for row in ws.iter_rows(min_row=1, max_row=ws.max_row, min_col=1, max_col=13):
            if row[1].value == "Dividends":
                div_type_cell = row
                break
        assert div_type_cell is not None
        assert div_type_cell[2].value == "US"
        assert div_type_cell[3].value == "US0378331005"
        assert div_type_cell[8].value == "AAPL"
        assert div_type_cell[9].value == "USD"

    def test_dividend_gross_amount_is_formula(self):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Reporting"
        config = _make_config()
        lines: CapitalGainLinesPerCompany = {}
        dividends: DividendIncomePerCompany = {
            "AAPL": DividendIncomePerSecurity(
                symbol="AAPL",
                isin="US0378331005",
                country="US",
                gross_amount=Decimal("100"),
                total_taxes=Decimal("15"),
                currency=Currency("USD"),
            )
        }
        write_ib_reporting_sheet(ws, config, lines, dividends)
        gross_cell = None
        for row in ws.iter_rows(min_row=1, max_row=ws.max_row, min_col=1, max_col=13):
            if row[1].value == "Dividends":
                gross_cell = row[4]
                break
        assert gross_cell is not None
        assert gross_cell.data_type == "f"

    def test_missing_isin_shows_warning(self):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Reporting"
        config = _make_config()
        lines: CapitalGainLinesPerCompany = {}
        dividends: DividendIncomePerCompany = {
            "UNKNOWN": DividendIncomePerSecurity(
                symbol="UNKNOWN",
                isin="MISSING_ISIN_REQUIRES_ATTENTION",
                country="UNKNOWN_COUNTRY",
                gross_amount=Decimal("50"),
                total_taxes=Decimal("0"),
                currency=Currency("USD"),
            )
        }
        write_ib_reporting_sheet(ws, config, lines, dividends)
        warning_cell = None
        for row in ws.iter_rows(min_row=1, max_row=ws.max_row, min_col=1, max_col=13):
            if row[1].value == "Dividends":
                warning_cell = row[2]
                break
        assert warning_cell is not None
        assert "MISSING DATA" in str(warning_cell.value)

    def test_no_dividend_section_when_none_provided(self):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Reporting"
        config = _make_config()
        lines: CapitalGainLinesPerCompany = {}
        write_ib_reporting_sheet(ws, config, lines)
        for row in ws.iter_rows(min_row=1, max_row=ws.max_row, min_col=1, max_col=1):
            assert row[0].value is None or "CAPITAL INVESTMENT INCOME" not in str(row[0].value)


@pytest.mark.unit
class TestWriteIbReportingSheetCurrencyTable:
    """Tests that currency table is embedded in the IB sheet."""

    def test_currency_table_present_in_sheet(self):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Reporting"
        config = _make_config()
        lines: CapitalGainLinesPerCompany = {}
        write_ib_reporting_sheet(ws, config, lines)
        found = False
        for row in ws.iter_rows(min_row=1, max_row=ws.max_row, min_col=21, max_col=21):
            if row[0].value == "Currency exchange rate":
                found = True
                break
        assert found

    def test_returns_none(self):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Reporting"
        config = _make_config()
        lines: CapitalGainLinesPerCompany = {}
        result = write_ib_reporting_sheet(ws, config, lines)
        assert result is None


@pytest.mark.unit
class TestWriteIbReportingSheetAutoWidth:
    """Tests that auto_column_width is called and respects bounds."""

    def test_auto_width_adjusts_columns(self):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Reporting"
        config = _make_config()
        line = _make_capital_gain_line()
        cc = CurrencyCompany(Currency("USD"), Company("AAPL", country_of_issuance="US"))
        lines: CapitalGainLinesPerCompany = {cc: [line]}
        write_ib_reporting_sheet(ws, config, lines)
        assert ws.column_dimensions["A"].width > 0

    def test_formula_heavy_columns_get_reasonable_widths(self):
        """Verify formula-heavy columns preserve header width with MIN_DATA_WIDTH as floor."""
        from shares_reporting.application.persisting.excel_utils import MIN_DATA_WIDTH

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Reporting"
        config = _make_config()
        # Add multiple lines to trigger formula-heavy detection (formulas > non-formula cells)
        line1 = _make_capital_gain_line()
        line2 = _make_capital_gain_line(sell_date=TradeDate(2025, 7, 20))
        line3 = _make_capital_gain_line(sell_date=TradeDate(2025, 8, 10))
        cc = CurrencyCompany(Currency("USD"), Company("AAPL", country_of_issuance="US"))
        lines: CapitalGainLinesPerCompany = {cc: [line1, line2, line3]}
        write_ib_reporting_sheet(ws, config, lines)

        # Expected widths for headers: M=45 (longest), Q=11, R=10, S=15, F=6, J=6
        # All formula-heavy columns should use measured header length with MIN_DATA_WIDTH as floor
        expected_widths = {
            "F": 6,    # "Amount"
            "J": 6,    # "Amount"
            "M": 45,   # "Expenses incurred with obtaining the capital gains"
            "Q": 11,   # "Sale amount"
            "R": 10,   # "Buy amount"
            "S": 15,   # "Expenses amount"
        }

        for col_letter, expected_header_len in expected_widths.items():
            width = ws.column_dimensions[col_letter].width
            assert width is not None, f"Column {col_letter} should have a width set"
            # Formula-heavy columns get max(header_length, MIN_DATA_WIDTH), not MIN_DATA_WIDTH alone
            expected_min = max(expected_header_len, MIN_DATA_WIDTH)
            assert width >= expected_min, (
                f"Column {col_letter} width {width} is too small; "
                f"expected at least {expected_min} (header={expected_header_len}, MIN_DATA_WIDTH={MIN_DATA_WIDTH})"
            )

    def test_empty_column_gets_min_data_width(self):
        """Verify a column with only formulas/empty cells gets MIN_DATA_WIDTH."""
        from shares_reporting.application.persisting.excel_utils import MIN_DATA_WIDTH, auto_column_width

        # Create a worksheet with one column that has only formulas
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Test"

        # Column A: only a formula
        ws["A1"] = "=SUM(B1:B10)"

        auto_column_width(ws)

        # Column A should get MIN_DATA_WIDTH since it has no data cells
        width = ws.column_dimensions["A"].width
        msg = f"Column with only formulas should get MIN_DATA_WIDTH ({MIN_DATA_WIDTH}), got {width}"
        assert width == MIN_DATA_WIDTH, msg
