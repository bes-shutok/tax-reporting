"""Tests for dividend Excel persisting functionality."""

from decimal import Decimal

import pytest

from shares_reporting.application.crypto_reporting import (
    CryptoCapitalGainEntry,
    CryptoCompletePdfSummary,
    CryptoReconciliationSummary,
    CryptoRewardIncomeEntry,
    CryptoSkippedZeroValueToken,
    CryptoTaxReport,
    HoldingsSnapshot,
    resolve_operator_origin,
)
from shares_reporting.application.persisting import generate_tax_report
from shares_reporting.domain.collections import DividendIncomePerCompany
from shares_reporting.domain.entities import DividendIncomePerSecurity
from shares_reporting.domain.value_objects import parse_currency


class TestDividendExcelPersisting:
    """Test dividend Excel report generation."""

    def test_generate_tax_report_with_dividends(self, tmp_path):
        """Test generating Excel report with dividend income section."""
        dividend_income = DividendIncomePerCompany(
            {
                "AAPL": DividendIncomePerSecurity(
                    symbol="AAPL",
                    isin="US0378331005",
                    country="United States",
                    gross_amount=Decimal("100.00"),
                    total_taxes=Decimal("15.00"),
                    currency=parse_currency("USD"),
                ),
                "MSFT": DividendIncomePerSecurity(
                    symbol="MSFT",
                    isin="US5949181045",
                    country="United States",
                    gross_amount=Decimal("200.00"),
                    total_taxes=Decimal("30.00"),
                    currency=parse_currency("USD"),
                ),
                "ASML": DividendIncomePerSecurity(
                    symbol="ASML",
                    isin="NL0010273215",
                    country="Netherlands",
                    gross_amount=Decimal("150.00"),
                    total_taxes=Decimal("0.00"),
                    currency=parse_currency("EUR"),
                ),
            }
        )

        # Generate report
        report_path = tmp_path / "dividend_report.xlsx"
        generate_tax_report(
            extract=report_path,
            capital_gain_lines_per_company={},
            dividend_income_per_company=dividend_income,
        )

        # Verify file was created
        assert report_path.exists()

        # Read and verify the Excel file
        import openpyxl

        workbook = openpyxl.load_workbook(report_path)
        worksheet = workbook.active
        assert worksheet is not None, "Workbook should have an active worksheet"

        # Find the dividend section
        found_dividend_section = False
        dividend_row_count = 0

        for _row_idx, row in enumerate(worksheet.iter_rows(values_only=True), 1):
            if row and isinstance(row[0], str) and "CAPITAL INVESTMENT INCOME" in row[0]:
                found_dividend_section = True
                # Next row should be empty
                continue

            if found_dividend_section and row and len(row) > 0:
                # Check for header row
                if isinstance(row[0], str) and "Beneficiary" in row[0]:
                    continue

                # Count data rows
                if dividend_row_count < 3 and row[1] == "Dividends":
                    dividend_row_count += 1
                    # Verify data integrity
                    symbol = row[8] if len(row) > 8 else None
                    country = row[2] if len(row) > 2 else None
                    isin = row[3] if len(row) > 3 else None
                    original_gross = row[10] if len(row) > 10 else None
                    original_tax = row[11] if len(row) > 11 else None
                    net_amount = row[12] if len(row) > 12 else None

                    # Verify expected values based on symbol
                    if symbol == "AAPL":
                        assert country == "United States"
                        assert isin == "US0378331005"
                        assert original_gross == "100.00"
                        assert original_tax == "15.00"
                        assert net_amount == "85.00"
                    elif symbol == "MSFT":
                        assert country == "United States"
                        assert isin == "US5949181045"
                        assert original_gross == "200.00"
                        assert original_tax == "30.00"
                        assert net_amount == "170.00"
                    elif symbol == "ASML":
                        assert country == "Netherlands"
                        assert isin == "NL0010273215"
                        assert original_gross == "150.00"
                        assert original_tax == "0.00"
                        assert net_amount == "150.00"

        assert found_dividend_section, "Dividend section not found in report"
        assert dividend_row_count == 3, f"Expected 3 dividend rows, found {dividend_row_count}"

        workbook.close()

    def test_generate_tax_report_without_dividends(self, tmp_path):
        """Test generating Excel report without dividend income section."""
        report_path = tmp_path / "no_dividend_report.xlsx"
        generate_tax_report(
            extract=report_path,
            capital_gain_lines_per_company={},
            dividend_income_per_company={},  # Empty dividend data
        )

        assert report_path.exists()

        # Read and verify no dividend section
        import openpyxl

        workbook = openpyxl.load_workbook(report_path)
        worksheet = workbook.active
        assert worksheet is not None, "Workbook should have an active worksheet"

        # Should not have dividend section
        found_dividend_section = False
        for row in worksheet.iter_rows(values_only=True):
            if row and isinstance(row[0], str) and "CAPITAL INVESTMENT INCOME" in row[0]:
                found_dividend_section = True
                break

        assert not found_dividend_section, "Dividend section should not be present"
        workbook.close()

    def test_generate_tax_report_with_dividend_formulas(self, tmp_path):
        """Test that dividend Excel report contains proper currency conversion formulas."""
        dividend_income = DividendIncomePerCompany(
            {
                "AAPL": DividendIncomePerSecurity(
                    symbol="AAPL",
                    isin="US0378331005",
                    country="United States",
                    gross_amount=Decimal("100.50"),
                    total_taxes=Decimal("15.25"),
                    currency=parse_currency("USD"),
                ),
            }
        )

        report_path = tmp_path / "dividend_formulas_report.xlsx"
        generate_tax_report(
            extract=report_path,
            capital_gain_lines_per_company={},
            dividend_income_per_company=dividend_income,
        )

        # Read and verify formulas
        import openpyxl

        workbook = openpyxl.load_workbook(report_path)
        worksheet = workbook.active
        assert worksheet is not None, "Workbook should have an active worksheet"

        # Find dividend row and check formulas
        dividend_row = None
        for row_idx, row in enumerate(worksheet.iter_rows(values_only=False), 1):
            if row and len(row) > 1 and row[1].value == "Dividends":
                dividend_row = row_idx
                break

        assert dividend_row is not None, "Dividend row not found"

        # Check converted gross amount formula (column 5, index 4)
        gross_amount_cell = worksheet.cell(row=dividend_row, column=5)
        assert gross_amount_cell.data_type == "f"  # Formula cell
        assert "=V" in str(gross_amount_cell.value)  # Contains reference to exchange rate
        assert "100.5" in str(gross_amount_cell.value)  # Contains original amount

        # Check converted tax amount formula (column 6, index 5)
        tax_amount_cell = worksheet.cell(row=dividend_row, column=6)
        assert tax_amount_cell.data_type == "f"  # Formula cell
        assert "=V" in str(tax_amount_cell.value)  # Contains reference to exchange rate
        assert "15.25" in str(tax_amount_cell.value)  # Contains original amount

        # Check original amounts (should be string values)
        original_gross_cell = worksheet.cell(row=dividend_row, column=11)
        assert original_gross_cell.data_type == "s"  # String value
        assert original_gross_cell.value == "100.50"

        original_tax_cell = worksheet.cell(row=dividend_row, column=12)
        assert original_tax_cell.data_type == "s"  # String value
        assert original_tax_cell.value == "15.25"

        net_amount_cell = worksheet.cell(row=dividend_row, column=13)
        assert net_amount_cell.data_type == "s"  # String value
        assert net_amount_cell.value == "85.25"  # 100.50 - 15.25

        workbook.close()

    def test_generate_tax_report_with_multiple_currencies(self, tmp_path):
        """Test generating Excel report with multiple dividend currencies."""
        dividend_income = DividendIncomePerCompany(
            {
                "AAPL": DividendIncomePerSecurity(
                    symbol="AAPL",
                    isin="US0378331005",
                    country="United States",
                    gross_amount=Decimal("100.00"),
                    total_taxes=Decimal("15.00"),
                    currency=parse_currency("USD"),
                ),
                "ASML": DividendIncomePerSecurity(
                    symbol="ASML",
                    isin="NL0010273215",
                    country="Netherlands",
                    gross_amount=Decimal("200.00"),
                    total_taxes=Decimal("25.00"),
                    currency=parse_currency("EUR"),
                ),
                "TSLA": DividendIncomePerSecurity(
                    symbol="TSLA",
                    isin="US88160R1014",
                    country="United States",
                    gross_amount=Decimal("50.00"),
                    total_taxes=Decimal("0.00"),
                    currency=parse_currency("CAD"),
                ),
            }
        )

        report_path = tmp_path / "multi_currency_dividend_report.xlsx"
        generate_tax_report(
            extract=report_path,
            capital_gain_lines_per_company={},
            dividend_income_per_company=dividend_income,
        )

        # Read and verify multiple currencies
        import openpyxl

        workbook = openpyxl.load_workbook(report_path)
        worksheet = workbook.active
        assert worksheet is not None, "Workbook should have an active worksheet"

        # Find dividend rows and check currency columns
        dividend_currencies = []
        for _row_idx, row in enumerate(worksheet.iter_rows(values_only=True), 1):
            if row and len(row) > 1 and row[1] == "Dividends":
                currency = row[9] if len(row) > 9 else None  # Currency column
                if currency:
                    dividend_currencies.append(currency)

        assert len(dividend_currencies) == 3
        assert "USD" in dividend_currencies
        assert "EUR" in dividend_currencies
        assert "CAD" in dividend_currencies
        workbook.close()

    def test_generate_tax_report_with_crypto_sheet(self, tmp_path):
        """Test generating Excel report with additional crypto worksheet."""
        bybit_origin = resolve_operator_origin("ByBit")
        wirex_origin = resolve_operator_origin("Wirex", transaction_type="crypto_deposit")

        crypto_report = CryptoTaxReport(
            tax_year=2025,
            capital_entries=[
                CryptoCapitalGainEntry(
                    disposal_date="2025-01-13 13:01:00",
                    acquisition_date="2024-11-18 00:15:00",
                    asset="USDT",
                    amount=Decimal("1.5"),
                    cost_eur=Decimal("1.25"),
                    proceeds_eur=Decimal("1.35"),
                    gain_loss_eur=Decimal("0.10"),
                    holding_period="Short term",
                    wallet="ByBit (2)",
                    platform="ByBit",
                    chain="ByBit",
                    operator_origin=bybit_origin,
                    annex_hint="J",
                    review_required=bybit_origin.review_required,
                    review_reason=bybit_origin.review_reason,
                    notes="",
                    token_swap_history="",
                )
            ],
            reward_entries=[
                CryptoRewardIncomeEntry(
                    date="2025-01-01 00:01:00",
                    asset="WXT",
                    amount=Decimal("5"),
                    value_eur=Decimal("17.10"),
                    income_label="Reward",
                    source_type="Reward",
                    wallet="Wirex",
                    platform="Wirex",
                    chain="Wirex",
                    operator_origin=wirex_origin,
                    annex_hint="J",
                    review_required=wirex_origin.review_required,
                    review_reason=wirex_origin.review_reason,
                    description="",
                )
            ],
            reconciliation=CryptoReconciliationSummary(
                capital_rows=1,
                reward_rows=1,
                short_term_rows=1,
                long_term_rows=0,
                mixed_rows=0,
                unknown_rows=0,
                capital_cost_total_eur=Decimal("1.25"),
                capital_proceeds_total_eur=Decimal("1.35"),
                capital_gain_total_eur=Decimal("0.10"),
                reward_total_eur=Decimal("17.10"),
                opening_holdings=HoldingsSnapshot(
                    asset_rows=1,
                    total_cost_eur=Decimal("100.00"),
                    total_value_eur=Decimal("120.00"),
                ),
                closing_holdings=HoldingsSnapshot(
                    asset_rows=1,
                    total_cost_eur=Decimal("130.00"),
                    total_value_eur=Decimal("150.00"),
                ),
            ),
            skipped_zero_value_tokens=[
                CryptoSkippedZeroValueToken(source_section="capital_gains", asset="FEE", count=3),
                CryptoSkippedZeroValueToken(source_section="income", asset="AAA", count=2),
            ],
            pdf_summary=CryptoCompletePdfSummary(
                period="1 Jan 2025 to 31 Dec 2025",
                timezone="Europe/Lisbon",
                extracted_tokens=12,
            ),
        )

        report_path = tmp_path / "crypto_report.xlsx"
        generate_tax_report(
            extract=report_path,
            capital_gain_lines_per_company={},
            dividend_income_per_company={},
            crypto_tax_report=crypto_report,
        )

        assert report_path.exists()

        import openpyxl

        workbook = openpyxl.load_workbook(report_path)
        assert "Crypto" in workbook.sheetnames
        crypto_sheet = workbook["Crypto"]
        assert crypto_sheet["A1"].value == "CRYPTO TAX REPORT - PORTUGAL"

        labels = set()
        for row in crypto_sheet.iter_rows(values_only=True):
            first_cell = row[0] if row else None
            if isinstance(first_cell, str):
                labels.add(first_cell)

        assert "1. CAPITAL GAINS" in labels
        assert "2. REWARDS INCOME - IRS-READY FILING SUMMARY" in labels
        assert "2b. DEFERRED BY LAW - SUPPORT DETAIL" in labels
        assert "2c. REWARDS CLASSIFICATION RECONCILIATION" in labels
        assert "3. RECONCILIATION" in labels
        assert "4. SKIPPED ZERO VALUE TOKENS" in labels
        assert "PDF period" in labels
        workbook.close()

    def test_crypto_sheet_contains_chain_column(self, tmp_path):
        """Assert the Crypto worksheet contains chain headers and writes the normalized values."""
        bybit_origin = resolve_operator_origin("ByBit")
        wirex_origin = resolve_operator_origin("Wirex", transaction_type="crypto_deposit")

        crypto_report = CryptoTaxReport(
            tax_year=2025,
            capital_entries=[
                CryptoCapitalGainEntry(
                    disposal_date="2025-01-13 13:01:00",
                    acquisition_date="2024-11-18 00:15:00",
                    asset="USDT",
                    amount=Decimal("1.5"),
                    cost_eur=Decimal("1.25"),
                    proceeds_eur=Decimal("1.35"),
                    gain_loss_eur=Decimal("0.10"),
                    holding_period="Short term",
                    wallet="ByBit (2)",
                    platform="ByBit",
                    chain="ByBit",
                    operator_origin=bybit_origin,
                    annex_hint="J",
                    review_required=bybit_origin.review_required,
                    review_reason=bybit_origin.review_reason,
                    notes="",
                    token_swap_history="",
                )
            ],
            reward_entries=[
                CryptoRewardIncomeEntry(
                    date="2025-01-01 00:01:00",
                    asset="WXT",
                    amount=Decimal("5"),
                    value_eur=Decimal("17.10"),
                    income_label="Reward",
                    source_type="Reward",
                    wallet="Wirex",
                    platform="Wirex",
                    chain="Wirex",
                    operator_origin=wirex_origin,
                    annex_hint="J",
                    review_required=wirex_origin.review_required,
                    review_reason=wirex_origin.review_reason,
                    description="",
                )
            ],
            reconciliation=CryptoReconciliationSummary(
                capital_rows=1,
                reward_rows=1,
                short_term_rows=1,
                long_term_rows=0,
                mixed_rows=0,
                unknown_rows=0,
                capital_cost_total_eur=Decimal("1.25"),
                capital_proceeds_total_eur=Decimal("1.35"),
                capital_gain_total_eur=Decimal("0.10"),
                reward_total_eur=Decimal("17.10"),
                opening_holdings=None,
                closing_holdings=None,
            ),
            skipped_zero_value_tokens=[],
            pdf_summary=None,
        )

        report_path = tmp_path / "crypto_chain_report.xlsx"
        generate_tax_report(
            extract=report_path,
            capital_gain_lines_per_company={},
            dividend_income_per_company={},
            crypto_tax_report=crypto_report,
        )

        assert report_path.exists()

        import openpyxl

        workbook = openpyxl.load_workbook(report_path)
        crypto_sheet = workbook["Crypto"]

        # Find the capital gains header row and check for chain column
        capital_headers_found = False
        capital_chain_col_idx = None
        reward_headers_found = False
        reward_chain_col_idx = None

        for row in crypto_sheet.iter_rows(values_only=True):
            if row and "Disposal date" in str(row[0] if row[0] else ""):
                # Found capital gains headers
                capital_headers_found = True
                # Find the "Disposal chain" column index
                for col_idx, cell_value in enumerate(row):
                    if cell_value == "Disposal chain":
                        capital_chain_col_idx = col_idx + 1
                        break
            elif row and "Date" in str(row[0] if row[0] else "") and "Asset" in str(row[1] if len(row) > 1 else ""):
                # Found rewards headers
                reward_headers_found = True
                # Find the "Reward chain" column index
                for col_idx, cell_value in enumerate(row):
                    if cell_value == "Reward chain":
                        reward_chain_col_idx = col_idx + 1
                        break

        # Verify headers were found
        assert capital_headers_found, "Capital gains headers not found"
        assert reward_headers_found, "Reward headers not found"
        assert capital_chain_col_idx is not None, "Disposal chain column not found in capital gains headers"
        assert reward_chain_col_idx is not None, "Reward chain column not found in rewards headers"

        # Verify the chain values are written in the data rows
        capital_data_row = None
        reward_data_row = None

        for row in crypto_sheet.iter_rows(values_only=True):
            if row and row[0] == "2025-01-13 13:01:00":
                capital_data_row = row
            elif row and row[0] == "2025-01-01 00:01:00":
                reward_data_row = row

        assert capital_data_row is not None, "Capital data row not found"
        assert reward_data_row is not None, "Reward data row not found"

        # Check chain values in data rows (using 1-based column index)
        capital_chain = capital_data_row[capital_chain_col_idx - 1]
        assert capital_chain == "ByBit", f"Expected 'ByBit' chain in capital data, got {capital_chain}"
        reward_chain = reward_data_row[reward_chain_col_idx - 1]
        assert reward_chain == "Wirex", f"Expected 'Wirex' chain in reward data, got {reward_chain}"

        workbook.close()

    def test_crypto_sheet_contains_token_origin_column(self, tmp_path):
        """Assert the Crypto worksheet contains Token origin column with blank value after legacy removal."""
        bybit_origin = resolve_operator_origin("ByBit")

        crypto_report = CryptoTaxReport(
            tax_year=2025,
            capital_entries=[
                CryptoCapitalGainEntry(
                    disposal_date="2025-02-16 12:00:00",
                    acquisition_date="2025-02-16 10:00:00",
                    asset="HASUI",
                    amount=Decimal("29.83"),
                    cost_eur=Decimal("10.00"),
                    proceeds_eur=Decimal("15.00"),
                    gain_loss_eur=Decimal("5.00"),
                    holding_period="Short term",
                    wallet="Ledger SUI",
                    platform="Ledger",
                    chain="Sui",
                    operator_origin=bybit_origin,
                    annex_hint="J",
                    review_required=False,
                    notes="",
                    token_swap_history="",
                )
            ],
            reward_entries=[],
            reconciliation=CryptoReconciliationSummary(
                capital_rows=1,
                reward_rows=0,
                short_term_rows=1,
                long_term_rows=0,
                mixed_rows=0,
                unknown_rows=0,
                capital_cost_total_eur=Decimal("10.00"),
                capital_proceeds_total_eur=Decimal("15.00"),
                capital_gain_total_eur=Decimal("5.00"),
                reward_total_eur=Decimal("0"),
                opening_holdings=None,
                closing_holdings=None,
            ),
            skipped_zero_value_tokens=[],
            pdf_summary=None,
        )

        report_path = tmp_path / "crypto_token_origin_report.xlsx"
        generate_tax_report(
            extract=report_path,
            capital_gain_lines_per_company={},
            dividend_income_per_company={},
            crypto_tax_report=crypto_report,
        )

        assert report_path.exists()

        import openpyxl

        workbook = openpyxl.load_workbook(report_path)
        crypto_sheet = workbook["Crypto"]

        capital_headers_found = False
        token_origin_col_idx = None

        for row in crypto_sheet.iter_rows(values_only=True):
            if row and "Disposal date" in str(row[0] if row[0] else ""):
                capital_headers_found = True
                for col_idx, cell_value in enumerate(row):
                    if cell_value == "Token origin":
                        token_origin_col_idx = col_idx + 1
                        break
                break

        assert capital_headers_found, "Capital gains headers not found"
        assert token_origin_col_idx is not None, "Token origin column not found in capital gains headers"

        capital_data_row = None

        for row in crypto_sheet.iter_rows(values_only=True):
            if row and row[0] == "2025-02-16 12:00:00":
                capital_data_row = row
                break

        assert capital_data_row is not None, "Capital data row not found"

        token_origin_value = capital_data_row[token_origin_col_idx - 1]
        assert token_origin_value in ("", None), f"Expected blank Token origin, got {token_origin_value!r}"

        workbook.close()

    def test_crypto_sheet_review_reason_in_excel_output(self, tmp_path):
        """Assert review_reason appears in Excel cells as 'YES: <reason>' when review_required."""
        bybit_origin = resolve_operator_origin("ByBit")
        wirex_origin = resolve_operator_origin("Wirex", transaction_type="crypto_deposit")

        crypto_report = CryptoTaxReport(
            tax_year=2025,
            capital_entries=[
                CryptoCapitalGainEntry(
                    disposal_date="2025-01-13 13:01:00",
                    acquisition_date="2024-11-18 00:15:00",
                    asset="USDT",
                    amount=Decimal("1.5"),
                    cost_eur=Decimal("1.25"),
                    proceeds_eur=Decimal("1.35"),
                    gain_loss_eur=Decimal("0.10"),
                    holding_period="Short term",
                    wallet="ByBit (2)",
                    platform="ByBit",
                    chain="ByBit",
                    operator_origin=bybit_origin,
                    annex_hint="J",
                    review_required=bybit_origin.review_required,
                    review_reason=bybit_origin.review_reason,
                    notes="",
                    token_swap_history="",
                )
            ],
            reward_entries=[
                CryptoRewardIncomeEntry(
                    date="2025-01-01 00:01:00",
                    asset="WXT",
                    amount=Decimal("5"),
                    value_eur=Decimal("17.10"),
                    income_label="Reward",
                    source_type="Reward",
                    wallet="Wirex",
                    platform="Wirex",
                    chain="Wirex",
                    operator_origin=wirex_origin,
                    annex_hint="J",
                    review_required=False,
                    description="",
                )
            ],
            reconciliation=CryptoReconciliationSummary(
                capital_rows=1,
                reward_rows=1,
                short_term_rows=1,
                long_term_rows=0,
                mixed_rows=0,
                unknown_rows=0,
                capital_cost_total_eur=Decimal("1.25"),
                capital_proceeds_total_eur=Decimal("1.35"),
                capital_gain_total_eur=Decimal("0.10"),
                reward_total_eur=Decimal("17.10"),
                opening_holdings=None,
                closing_holdings=None,
            ),
            skipped_zero_value_tokens=[],
            pdf_summary=None,
        )

        report_path = tmp_path / "crypto_review_reason_report.xlsx"
        generate_tax_report(
            extract=report_path,
            capital_gain_lines_per_company={},
            dividend_income_per_company={},
            crypto_tax_report=crypto_report,
        )

        assert report_path.exists()

        import openpyxl

        workbook = openpyxl.load_workbook(report_path)
        crypto_sheet = workbook["Crypto"]

        # Find capital gains data row and reward row in support detail section
        capital_review_cell = None
        reward_review_cell = None
        found_capital_review = False
        found_reward_review = False
        in_deferred = False
        for row in crypto_sheet.iter_rows(values_only=True):
            if row and isinstance(row[0], str) and "DEFERRED BY LAW" in row[0]:
                in_deferred = True
            if in_deferred and row and row[0] == "2025-01-01 00:01:00":
                reward_review_cell = row[9] if len(row) > 9 else None
                found_reward_review = True
                break
            if row and row[0] == "2025-01-13 13:01:00":
                capital_review_cell = row[14] if len(row) > 14 else None
                found_capital_review = True

        assert found_capital_review, "Capital data row not found"
        assert capital_review_cell is not None
        assert isinstance(capital_review_cell, str)
        assert capital_review_cell.startswith("YES:"), f"Expected 'YES: ...' but got '{capital_review_cell}'"
        assert "account-region" in capital_review_cell.lower(), (
            f"Expected account-region in review reason, got '{capital_review_cell}'"
        )

        assert found_reward_review, "Reward row not found in deferred support detail section"
        assert reward_review_cell is not None
        assert reward_review_cell == "NO", f"Expected 'NO' for non-review reward, got '{reward_review_cell}'"

        workbook.close()

    def test_generate_tax_report_with_single_dividend_entry(self, tmp_path):
        """Test that report generation works with a single valid dividend entry."""
        dividend_income = DividendIncomePerCompany(
            {
                "VALID": DividendIncomePerSecurity(
                    symbol="VALID",
                    isin="US1234567890",
                    country="United States",
                    gross_amount=Decimal("100.00"),  # Valid positive amount
                    total_taxes=Decimal("15.00"),
                    currency=parse_currency("USD"),
                ),
            }
        )

        report_path = tmp_path / "valid_dividend_report.xlsx"

        # Should generate successfully
        generate_tax_report(
            extract=report_path,
            capital_gain_lines_per_company={},
            dividend_income_per_company=dividend_income,
        )

        assert report_path.exists()

    def test_generate_tax_report_mixed_capital_gains_and_dividends(self, tmp_path):
        """Test generating Excel report with both capital gains and dividend sections."""
        # Create simple dividend data
        dividend_income = DividendIncomePerCompany(
            {
                "AAPL": DividendIncomePerSecurity(
                    symbol="AAPL",
                    isin="US0378331005",
                    country="United States",
                    gross_amount=Decimal("100.00"),
                    total_taxes=Decimal("15.00"),
                    currency=parse_currency("USD"),
                ),
            }
        )

        report_path = tmp_path / "mixed_report.xlsx"
        generate_tax_report(
            extract=report_path,
            capital_gain_lines_per_company={},  # Empty capital gains
            dividend_income_per_company=dividend_income,
        )

        assert report_path.exists()

        # Read and verify both sections exist
        import openpyxl

        workbook = openpyxl.load_workbook(report_path)
        worksheet = workbook.active
        assert worksheet is not None, "Workbook should have an active worksheet"

        # Find dividend section
        found_dividends = False

        for row in worksheet.iter_rows(values_only=True):
            if row and isinstance(row[0], str):
                if "CAPITAL GAINS" in row[0] or "DISPONIBILIZAÇÕES" in row[0]:
                    pass  # Found capital gains section
                elif "CAPITAL INVESTMENT INCOME" in row[0]:
                    found_dividends = True

        assert found_dividends, "Dividend section not found in mixed report"
        workbook.close()

    def test_dividend_excel_cell_formatting(self, tmp_path):
        """Test that dividend Excel cells have proper number formatting."""
        dividend_income = DividendIncomePerCompany(
            {
                "AAPL": DividendIncomePerSecurity(
                    symbol="AAPL",
                    isin="US0378331005",
                    country="United States",
                    gross_amount=Decimal("100.12345"),
                    total_taxes=Decimal("15.67890"),
                    currency=parse_currency("USD"),
                ),
            }
        )

        report_path = tmp_path / "formatted_dividend_report.xlsx"
        generate_tax_report(
            extract=report_path,
            capital_gain_lines_per_company={},
            dividend_income_per_company=dividend_income,
        )

        # Read and verify cell formatting
        import openpyxl

        workbook = openpyxl.load_workbook(report_path)
        worksheet = workbook.active
        assert worksheet is not None, "Workbook should have an active worksheet"

        # Find dividend row and check formatting
        dividend_row = None
        for row_idx, row in enumerate(worksheet.iter_rows(values_only=False), 1):
            if row and len(row) > 1 and row[1].value == "Dividends":
                dividend_row = row_idx
                break

        assert dividend_row is not None

        # Check number format for original amounts
        original_gross_cell = worksheet.cell(row=dividend_row, column=11)
        assert original_gross_cell.number_format == "0.00"

        original_tax_cell = worksheet.cell(row=dividend_row, column=12)
        assert original_tax_cell.number_format == "0.00"

        net_amount_cell = worksheet.cell(row=dividend_row, column=13)
        assert net_amount_cell.number_format == "0.00"

        # Check values are stored as strings with full precision
        assert original_gross_cell.value == "100.12345"
        assert original_tax_cell.value == "15.67890"
        assert net_amount_cell.value == "84.44455"  # 100.12345 - 15.67890

        workbook.close()

    def test_crypto_sheet_generation_error_fails_report_generation(self, tmp_path):
        """Test that crypto sheet generation errors fail the entire report generation.

        Per plan requirement (Task 2), report generation must fail with a clear error
        when a taxable-now row cannot be assigned all mandatory IRS fields.
        """
        from unittest.mock import patch

        from shares_reporting.domain.exceptions import FileProcessingError

        # Create a simple crypto report
        crypto_report = CryptoTaxReport(
            tax_year=2025,
            capital_entries=[
                CryptoCapitalGainEntry(
                    disposal_date="2025-01-13 13:01:00",
                    acquisition_date="2024-11-18 00:15:00",
                    asset="ETH",
                    amount=Decimal("1"),
                    cost_eur=Decimal("1000"),
                    proceeds_eur=Decimal("1200"),
                    gain_loss_eur=Decimal("200"),
                    holding_period="Short term",
                    wallet="Ledger ETH",
                    platform="Ledger ETH",
                    chain="Ethereum",
                    operator_origin=resolve_operator_origin("Ledger ETH"),
                    annex_hint="J",
                    review_required=False,
                    notes="",
                    token_swap_history="",
                ),
            ],
            reward_entries=[],
            reconciliation=CryptoReconciliationSummary(
                capital_rows=1,
                reward_rows=0,
                short_term_rows=1,
                long_term_rows=0,
                mixed_rows=0,
                unknown_rows=0,
                capital_cost_total_eur=Decimal("1000"),
                capital_proceeds_total_eur=Decimal("1200"),
                capital_gain_total_eur=Decimal("200"),
                reward_total_eur=Decimal("0"),
                opening_holdings=None,
                closing_holdings=None,
            ),
            skipped_zero_value_tokens=[],
            pdf_summary=None,
        )

        report_path = tmp_path / "crypto_error_test.xlsx"

        # Mock add_crypto_report_sheet to raise a FileProcessingError
        with (
            patch(
                "shares_reporting.application.persisting.add_crypto_report_sheet",
                side_effect=FileProcessingError("Simulated validation failure for testing"),
            ),
            pytest.raises(FileProcessingError, match="Simulated validation failure for testing"),
        ):
            generate_tax_report(
                extract=report_path,
                capital_gain_lines_per_company={},
                dividend_income_per_company={},
                crypto_tax_report=crypto_report,
            )

        # Verify the report was NOT created because generation failed
        assert not report_path.exists()

    def test_crypto_sheet_removed_on_partial_write_error(self, tmp_path):
        """Test that partial Crypto sheet is removed when error occurs during writing.

        Per plan requirement (Task 2), report generation must fail with a clear error
        when a taxable-now row cannot be assigned all mandatory IRS fields. The error
        propagates and fails the entire report generation.
        """
        from unittest.mock import patch

        from shares_reporting.application.persisting import generate_tax_report
        from shares_reporting.domain.exceptions import FileProcessingError

        crypto_report = CryptoTaxReport(
            tax_year=2025,
            capital_entries=[
                CryptoCapitalGainEntry(
                    disposal_date="2025-01-15",
                    acquisition_date="2024-06-01",
                    asset="BTC",
                    amount=Decimal("0.5"),
                    cost_eur=Decimal("10000"),
                    proceeds_eur=Decimal("12000"),
                    gain_loss_eur=Decimal("2000"),
                    holding_period="Short term",
                    wallet="TestWallet",
                    platform="TestPlatform",
                    chain="Bitcoin",
                    operator_origin=resolve_operator_origin("TestPlatform", "crypto_disposal"),
                    annex_hint="G",
                    review_required=False,
                    notes="",
                    token_swap_history="",
                ),
            ],
            reward_entries=[],
            reconciliation=CryptoReconciliationSummary(
                capital_rows=1,
                reward_rows=0,
                short_term_rows=1,
                long_term_rows=0,
                mixed_rows=0,
                unknown_rows=0,
                capital_cost_total_eur=Decimal("10000"),
                capital_proceeds_total_eur=Decimal("12000"),
                capital_gain_total_eur=Decimal("2000"),
                reward_total_eur=Decimal("0"),
                opening_holdings=None,
                closing_holdings=None,
            ),
            skipped_zero_value_tokens=[],
            pdf_summary=None,
        )

        report_path = tmp_path / "crypto_partial_error_test.xlsx"

        # Mock add_crypto_report_sheet to create the sheet but fail during writing
        def mock_add_crypto_that_fails_partial(workbook, crypto_tax_report, aggregated_rewards):
            # First create the sheet (this adds it to workbook.sheetnames)
            crypto_ws = workbook.create_sheet("Crypto")
            # Write some initial content
            crypto_ws.cell(1, 1, "CRYPTO TAX REPORT - PORTUGAL")
            crypto_ws.cell(2, 1, "Tax year")
            crypto_ws.cell(2, 2, crypto_tax_report.tax_year)
            # Now simulate an error during writing
            raise FileProcessingError("Simulated write error during crypto sheet generation")

        with (
            patch(
                "shares_reporting.application.persisting.add_crypto_report_sheet",
                side_effect=mock_add_crypto_that_fails_partial,
            ),
            pytest.raises(FileProcessingError, match="Simulated write error during crypto sheet generation"),
        ):
            generate_tax_report(
                extract=report_path,
                capital_gain_lines_per_company={},
                dividend_income_per_company={},
                crypto_tax_report=crypto_report,
            )

        # Verify the report was NOT created because generation failed
        assert not report_path.exists()
