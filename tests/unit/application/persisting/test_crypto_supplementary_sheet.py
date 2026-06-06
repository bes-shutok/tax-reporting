"""Tests for the crypto supplementary sheet writer."""

from decimal import Decimal

import openpyxl
import pytest

from tax_reporting.application.crypto_reporting import (
    AggregatedRewardIncomeEntry,
    CapitalGainPeriodStats,
    CryptoCapitalGainStats,
    CryptoReconciliationSummary,
    CryptoReviewEntry,
    CryptoRewardIncomeEntry,
    CryptoTaxReport,
    RewardTaxClassification,
)
from tax_reporting.application.persisting.crypto_supplementary_sheet import write_crypto_supplementary_sheet
# make_operator_origin is a module-level helper from conftest, not a pytest fixture
from tests.conftest import make_operator_origin


def _make_reward_entry(
    classification: RewardTaxClassification = RewardTaxClassification.TAXABLE_NOW,
    **overrides: object,
) -> CryptoRewardIncomeEntry:
    defaults = {
        "date": "2025-03-15",
        "asset": "ETH",
        "amount": Decimal("0.5"),
        "value_eur": Decimal("1500"),
        "income_label": "Staking Reward",
        "source_type": "staking",
        "wallet": "Kraken",
        "platform": "Kraken",
        "chain": "Ethereum",
        "operator_origin": make_operator_origin(),
        "annex_hint": "J",
        "review_required": False,
        "description": "Staking reward payout",
        "tax_classification": classification,
        "foreign_tax_eur": Decimal("0"),
    }
    defaults.update(overrides)
    return CryptoRewardIncomeEntry(**defaults)  # type: ignore[arg-type]


def _make_aggregated_reward(**overrides: object) -> AggregatedRewardIncomeEntry:
    defaults = {
        "income_code": "401",
        "source_country": "US",
        "gross_income_eur": Decimal("1500"),
        "foreign_tax_eur": Decimal("0"),
        "raw_row_count": 1,
        "chains": ("Ethereum",),
        "description": "Staking income",
    }
    defaults.update(overrides)
    return AggregatedRewardIncomeEntry(**defaults)  # type: ignore[arg-type]


def _make_crypto_tax_report(
    reward_entries: list[CryptoRewardIncomeEntry] | None = None,
    review_entries: list[CryptoReviewEntry] | None = None,
) -> CryptoTaxReport:
    entries = reward_entries if reward_entries is not None else [_make_reward_entry()]
    reconciliation = CryptoReconciliationSummary(
        capital_rows=0,
        reward_rows=len(entries),
        short_term_rows=0,
        long_term_rows=0,
        mixed_rows=0,
        unknown_rows=0,
        capital_cost_total_eur=Decimal("0"),
        capital_proceeds_total_eur=Decimal("0"),
        capital_gain_total_eur=Decimal("0"),
        reward_total_eur=sum((e.value_eur for e in entries), start=Decimal("0")),
        opening_holdings=None,
        closing_holdings=None,
    )
    empty_stats = CapitalGainPeriodStats(
        count=0, cost_total_eur=Decimal("0"), proceeds_total_eur=Decimal("0"), gain_loss_total_eur=Decimal("0")
    )
    capital_gain_stats = CryptoCapitalGainStats(
        short_term=empty_stats, long_term=empty_stats, mixed=empty_stats, unknown=empty_stats, grand_total=empty_stats
    )
    return CryptoTaxReport(
        tax_year=2025,
        capital_entries=[],
        reward_entries=entries,
        reconciliation=reconciliation,
        capital_gain_stats=capital_gain_stats,
        pdf_summary=None,
        review_entries=review_entries if review_entries is not None else [],
    )


@pytest.mark.unit
class TestCryptoSupplementarySheetName:
    """Tests that the sheet is created with the correct name."""

    def test_sheet_named_crypto_supplementary(self):
        wb = openpyxl.Workbook()
        report = _make_crypto_tax_report()
        write_crypto_supplementary_sheet(wb, report)
        assert "Crypto Supplementary" in wb.sheetnames


@pytest.mark.unit
class TestCryptoSupplementarySheetIncomeCodes:
    """Tests for section 1: Income Codes reference."""

    def test_section_1_title_written(self):
        wb = openpyxl.Workbook()
        report = _make_crypto_tax_report()
        write_crypto_supplementary_sheet(wb, report)
        ws = wb["Crypto Supplementary"]
        found = False
        for row in ws.iter_rows(min_row=1, max_row=ws.max_row, min_col=1, max_col=1):
            if row[0].value == "1. INCOME CODES REFERENCE":
                found = True
                break
        assert found

    def test_section_1_title_is_bold(self):
        wb = openpyxl.Workbook()
        report = _make_crypto_tax_report()
        write_crypto_supplementary_sheet(wb, report)
        ws = wb["Crypto Supplementary"]
        for row in ws.iter_rows(min_row=1, max_row=ws.max_row, min_col=1, max_col=1):
            if row[0].value == "1. INCOME CODES REFERENCE":
                assert row[0].font.bold is True
                break

    def test_reference_note_is_italic(self):
        wb = openpyxl.Workbook()
        report = _make_crypto_tax_report()
        write_crypto_supplementary_sheet(wb, report)
        ws = wb["Crypto Supplementary"]
        found = False
        for row in ws.iter_rows(min_row=1, max_row=ws.max_row, min_col=1, max_col=1):
            if row[0].value and "Tabela V" in str(row[0].value):
                assert row[0].font.italic is True
                found = True
                break
        assert found

    def test_income_codes_headers_written(self):
        wb = openpyxl.Workbook()
        report = _make_crypto_tax_report()
        write_crypto_supplementary_sheet(wb, report)
        ws = wb["Crypto Supplementary"]
        header_row = None
        for r in range(1, ws.max_row + 1):
            if ws.cell(r, 1).value == "Country":
                header_row = r
                break
        assert header_row is not None
        assert ws.cell(header_row, 1).value == "Country"
        assert ws.cell(header_row, 2).value == "Income Code"
        assert ws.cell(header_row, 3).value == "Description"

    def test_income_codes_headers_are_bold(self):
        wb = openpyxl.Workbook()
        report = _make_crypto_tax_report()
        write_crypto_supplementary_sheet(wb, report)
        ws = wb["Crypto Supplementary"]
        header_row = None
        for r in range(1, ws.max_row + 1):
            if ws.cell(r, 1).value == "Country":
                header_row = r
                break
        assert header_row is not None
        for idx in range(1, 4):
            assert ws.cell(header_row, idx).font.bold is True

    def test_all_income_codes_listed(self):
        wb = openpyxl.Workbook()
        report = _make_crypto_tax_report()
        write_crypto_supplementary_sheet(wb, report)
        ws = wb["Crypto Supplementary"]
        header_row = None
        for r in range(1, ws.max_row + 1):
            if ws.cell(r, 1).value == "Country":
                header_row = r
                break
        assert header_row is not None

        codes_found = []
        for r in range(header_row + 1, ws.max_row + 1):
            first_cell = ws.cell(r, 1).value
            # Stop when we hit the next section
            if first_cell and isinstance(first_cell, str) and first_cell.startswith("2."):
                break
            code = ws.cell(r, 2).value
            if code and isinstance(code, str):
                codes_found.append(code)

        # All codes from _INCOME_CODE_DESCRIPTIONS should be present
        expected_codes = {"401", "402", "403", "404", "405"}
        assert set(codes_found) == expected_codes

    def test_income_codes_sorted_alphabetically(self):
        wb = openpyxl.Workbook()
        report = _make_crypto_tax_report()
        write_crypto_supplementary_sheet(wb, report)
        ws = wb["Crypto Supplementary"]
        header_row = None
        for r in range(1, ws.max_row + 1):
            if ws.cell(r, 1).value == "Country":
                header_row = r
                break

        codes = []
        for r in range(header_row + 1, ws.max_row + 1):
            first_cell = ws.cell(r, 1).value
            # Stop when we hit the next section
            if first_cell and isinstance(first_cell, str) and first_cell.startswith("2."):
                break
            code = ws.cell(r, 2).value
            if code and isinstance(code, str):
                codes.append(code)

        # Should be sorted: 401, 402, 403, 404, 405
        assert codes == sorted(codes)


@pytest.mark.unit
class TestCryptoSupplementarySheetTaxableNowDetail:
    """Tests for section 2: Taxable-now support detail."""

    DETAIL_HEADERS = [
        "Date",
        "Asset",
        "Value (EUR)",
        "Income type",
        "Wallet",
        "Platform",
        "Reward chain",
        "Country",
        "Foreign tax (EUR)",
        "Review flag",
        "Description",
    ]

    def test_section_2_title_written(self):
        wb = openpyxl.Workbook()
        report = _make_crypto_tax_report()
        write_crypto_supplementary_sheet(wb, report)
        ws = wb["Crypto Supplementary"]
        found = False
        for row in ws.iter_rows(min_row=1, max_row=ws.max_row, min_col=1, max_col=1):
            if row[0].value == "2. TAXABLE-NOW - SUPPORT DETAIL":
                found = True
                break
        assert found

    def test_section_2_title_is_bold(self):
        wb = openpyxl.Workbook()
        report = _make_crypto_tax_report()
        write_crypto_supplementary_sheet(wb, report)
        ws = wb["Crypto Supplementary"]
        for row in ws.iter_rows(min_row=1, max_row=ws.max_row, min_col=1, max_col=1):
            if row[0].value == "2. TAXABLE-NOW - SUPPORT DETAIL":
                assert row[0].font.bold is True
                break

    def test_taxable_note_mentions_reporting_worksheet(self):
        wb = openpyxl.Workbook()
        report = _make_crypto_tax_report()
        write_crypto_supplementary_sheet(wb, report)
        ws = wb["Crypto Supplementary"]
        found = False
        for row in ws.iter_rows(min_row=1, max_row=ws.max_row, min_col=1, max_col=1):
            val = row[0].value
            if val and "Reporting worksheet" in str(val) and "OTHER CAPITAL INVESTMENT INCOME" in str(val):
                found = True
                break
        assert found, "Expected note to mention Reporting worksheet and OTHER CAPITAL INVESTMENT INCOME"

    def test_detail_headers_written(self):
        wb = openpyxl.Workbook()
        report = _make_crypto_tax_report(reward_entries=[_make_reward_entry()])
        write_crypto_supplementary_sheet(wb, report)
        ws = wb["Crypto Supplementary"]
        section_row = None
        for r in range(1, ws.max_row + 1):
            if ws.cell(r, 1).value == "2. TAXABLE-NOW - SUPPORT DETAIL":
                section_row = r
                break
        assert section_row is not None
        header_row = None
        for r in range(section_row, ws.max_row + 1):
            if ws.cell(r, 1).value == "Date":
                header_row = r
                break
        assert header_row is not None
        for idx, expected in enumerate(self.DETAIL_HEADERS, start=1):
            assert ws.cell(header_row, idx).value == expected

    def test_taxable_now_entry_values(self):
        entry = _make_reward_entry(
            date="2025-03-15",
            asset="ETH",
            value_eur=Decimal("1500"),
            source_type="staking",
            wallet="Kraken",
            platform="Kraken",
            chain="Ethereum",
        )
        report = _make_crypto_tax_report(reward_entries=[entry])
        wb = openpyxl.Workbook()
        write_crypto_supplementary_sheet(wb, report)
        ws = wb["Crypto Supplementary"]
        header_row = None
        for r in range(1, ws.max_row + 1):
            if ws.cell(r, 1).value == "Date" and ws.cell(r, 4).value == "Income type":
                header_row = r
                break
        assert header_row is not None
        data_row = header_row + 1
        assert ws.cell(data_row, 1).value == "2025-03-15"
        assert ws.cell(data_row, 2).value == "ETH"
        assert ws.cell(data_row, 3).value == float(Decimal("1500"))
        assert ws.cell(data_row, 4).value == "staking"
        assert ws.cell(data_row, 5).value == "Kraken"
        assert ws.cell(data_row, 6).value == "Kraken"
        assert ws.cell(data_row, 7).value == "Ethereum"
        assert ws.cell(data_row, 8).value == "US"
        assert ws.cell(data_row, 9).value == float(Decimal("0"))
        assert ws.cell(data_row, 10).value == "NO"
        assert ws.cell(data_row, 11).value == "Staking reward payout"

    def test_taxable_now_review_flag_yes_with_reason(self):
        entry = _make_reward_entry(review_required=True, review_reason="Missing cost basis")
        report = _make_crypto_tax_report(reward_entries=[entry])
        wb = openpyxl.Workbook()
        write_crypto_supplementary_sheet(wb, report)
        ws = wb["Crypto Supplementary"]
        header_row = None
        for r in range(1, ws.max_row + 1):
            if ws.cell(r, 1).value == "Date" and ws.cell(r, 4).value == "Income type":
                header_row = r
                break
        data_row = header_row + 1
        assert ws.cell(data_row, 10).value == "YES: Missing cost basis"

    def test_no_taxable_now_entries_shows_note(self):
        deferred = _make_reward_entry(classification=RewardTaxClassification.DEFERRED_BY_LAW)
        report = _make_crypto_tax_report(reward_entries=[deferred])
        wb = openpyxl.Workbook()
        write_crypto_supplementary_sheet(wb, report)
        ws = wb["Crypto Supplementary"]
        found = False
        section_start = None
        for r in range(1, ws.max_row + 1):
            if ws.cell(r, 1).value == "2. TAXABLE-NOW - SUPPORT DETAIL":
                section_start = r
                break
        assert section_start is not None
        for r in range(section_start, ws.max_row + 1):
            val = ws.cell(r, 1).value
            if val and "No taxable-now rewards" in str(val):
                found = True
                break
        assert found


@pytest.mark.unit
class TestCryptoSupplementarySheetDeferredDetail:
    """Tests for section 3: Deferred by law support detail."""

    def test_section_3_title_written(self):
        wb = openpyxl.Workbook()
        report = _make_crypto_tax_report()
        write_crypto_supplementary_sheet(wb, report)
        ws = wb["Crypto Supplementary"]
        found = False
        for row in ws.iter_rows(min_row=1, max_row=ws.max_row, min_col=1, max_col=1):
            if row[0].value == "3. DEFERRED BY LAW - SUPPORT DETAIL":
                found = True
                break
        assert found

    def test_section_3_title_is_bold(self):
        wb = openpyxl.Workbook()
        report = _make_crypto_tax_report()
        write_crypto_supplementary_sheet(wb, report)
        ws = wb["Crypto Supplementary"]
        for row in ws.iter_rows(min_row=1, max_row=ws.max_row, min_col=1, max_col=1):
            if row[0].value == "3. DEFERRED BY LAW - SUPPORT DETAIL":
                assert row[0].font.bold is True
                break

    def test_deferred_note_is_italic(self):
        wb = openpyxl.Workbook()
        report = _make_crypto_tax_report()
        write_crypto_supplementary_sheet(wb, report)
        ws = wb["Crypto Supplementary"]
        found = False
        section_start = None
        for r in range(1, ws.max_row + 1):
            if ws.cell(r, 1).value == "3. DEFERRED BY LAW - SUPPORT DETAIL":
                section_start = r
                break
        assert section_start is not None
        for r in range(section_start, ws.max_row + 1):
            val = ws.cell(r, 1).value
            if val and "deferred until disposal" in str(val):
                assert ws.cell(r, 1).font.italic is True
                found = True
                break
        assert found

    def test_deferred_entry_values(self):
        deferred = _make_reward_entry(
            classification=RewardTaxClassification.DEFERRED_BY_LAW,
            date="2025-04-01",
            asset="BTC",
            value_eur=Decimal("500"),
            source_type="mining",
            wallet="Ledger",
            platform="Ledger",
            chain="Bitcoin",
            description="Mining payout",
        )
        report = _make_crypto_tax_report(reward_entries=[deferred])
        wb = openpyxl.Workbook()
        write_crypto_supplementary_sheet(wb, report)
        ws = wb["Crypto Supplementary"]
        section_start = None
        for r in range(1, ws.max_row + 1):
            if ws.cell(r, 1).value == "3. DEFERRED BY LAW - SUPPORT DETAIL":
                section_start = r
                break
        assert section_start is not None
        header_row = None
        for r in range(section_start, ws.max_row + 1):
            if ws.cell(r, 1).value == "Date" and ws.cell(r, 2).value == "Asset":
                header_row = r
                break
        assert header_row is not None
        data_row = header_row + 1
        assert ws.cell(data_row, 1).value == "2025-04-01"
        assert ws.cell(data_row, 2).value == "BTC"
        assert ws.cell(data_row, 3).value == float(Decimal("500"))
        assert ws.cell(data_row, 4).value == "mining"
        assert ws.cell(data_row, 10).value == "NO"
        assert ws.cell(data_row, 11).value == "Mining payout"

    def test_no_deferred_entries_shows_note(self):
        taxable = _make_reward_entry(classification=RewardTaxClassification.TAXABLE_NOW)
        report = _make_crypto_tax_report(reward_entries=[taxable])
        wb = openpyxl.Workbook()
        write_crypto_supplementary_sheet(wb, report)
        ws = wb["Crypto Supplementary"]
        section_start = None
        for r in range(1, ws.max_row + 1):
            if ws.cell(r, 1).value == "3. DEFERRED BY LAW - SUPPORT DETAIL":
                section_start = r
                break
        assert section_start is not None
        found = False
        for r in range(section_start, ws.max_row + 1):
            val = ws.cell(r, 1).value
            if val and "No deferred rewards" in str(val):
                found = True
                break
        assert found


@pytest.mark.unit
class TestCryptoSupplementarySheetClassificationReconciliation:
    """Tests for section 4: Rewards classification reconciliation."""

    def test_section_4_title_written(self):
        wb = openpyxl.Workbook()
        report = _make_crypto_tax_report()
        write_crypto_supplementary_sheet(wb, report)
        ws = wb["Crypto Supplementary"]
        found = False
        for row in ws.iter_rows(min_row=1, max_row=ws.max_row, min_col=1, max_col=1):
            if row[0].value == "4. REWARDS CLASSIFICATION RECONCILIATION":
                found = True
                break
        assert found

    def test_section_4_title_is_bold(self):
        wb = openpyxl.Workbook()
        report = _make_crypto_tax_report()
        write_crypto_supplementary_sheet(wb, report)
        ws = wb["Crypto Supplementary"]
        for row in ws.iter_rows(min_row=1, max_row=ws.max_row, min_col=1, max_col=1):
            if row[0].value == "4. REWARDS CLASSIFICATION RECONCILIATION":
                assert row[0].font.bold is True
                break

    def test_reconciliation_key_value_pairs(self):
        taxable = _make_reward_entry(classification=RewardTaxClassification.TAXABLE_NOW, value_eur=Decimal("100"))
        deferred = _make_reward_entry(
            classification=RewardTaxClassification.DEFERRED_BY_LAW, value_eur=Decimal("200"), asset="BTC"
        )
        report = _make_crypto_tax_report(reward_entries=[taxable, deferred])
        wb = openpyxl.Workbook()
        write_crypto_supplementary_sheet(wb, report)
        ws = wb["Crypto Supplementary"]
        section_start = None
        for r in range(1, ws.max_row + 1):
            if ws.cell(r, 1).value == "4. REWARDS CLASSIFICATION RECONCILIATION":
                section_start = r
                break
        assert section_start is not None
        data_start = section_start + 1
        keys = {}
        for r in range(data_start, data_start + 6):
            key = ws.cell(r, 1).value
            value = ws.cell(r, 2).value
            if key:
                keys[key] = value
        assert keys["Total reward rows (raw)"] == 2
        assert keys["Taxable-now rows (immediately taxable)"] == 1
        assert keys["Deferred-by-law rows (taxation deferred)"] == 1
        assert keys["Taxable-now total value (EUR)"] == float(Decimal("100"))
        assert keys["Deferred total value (EUR)"] == float(Decimal("200"))

    def test_reconciliation_empty_rewards(self):
        report = _make_crypto_tax_report(reward_entries=[])
        wb = openpyxl.Workbook()
        write_crypto_supplementary_sheet(wb, report)
        ws = wb["Crypto Supplementary"]
        section_start = None
        for r in range(1, ws.max_row + 1):
            if ws.cell(r, 1).value == "4. REWARDS CLASSIFICATION RECONCILIATION":
                section_start = r
                break
        assert section_start is not None
        data_start = section_start + 1
        assert ws.cell(data_start, 2).value == 0
        assert ws.cell(data_start + 1, 2).value == 0
        assert ws.cell(data_start + 2, 2).value == 0


@pytest.mark.unit
class TestCryptoSupplementarySheetAutoWidth:
    """Tests that auto_column_width is called."""

    def test_auto_width_adjusts_columns(self):
        wb = openpyxl.Workbook()
        report = _make_crypto_tax_report()
        write_crypto_supplementary_sheet(wb, report)
        ws = wb["Crypto Supplementary"]
        assert ws.column_dimensions["A"].width > 0

    def test_column_widths_respect_max_cell_width_cap(self):
        """Verify no column exceeds MAX_CELL_WIDTH + 2 even with long notes."""
        from tax_reporting.application.persisting.excel_utils import MAX_CELL_WIDTH

        wb = openpyxl.Workbook()
        report = _make_crypto_tax_report()
        write_crypto_supplementary_sheet(wb, report)
        ws = wb["Crypto Supplementary"]

        # All column widths should be capped at MAX_CELL_WIDTH + 2
        max_allowed = MAX_CELL_WIDTH + 2
        for col_letter, col_dim in ws.column_dimensions.items():
            if col_dim.width is not None:
                assert (
                    col_dim.width <= max_allowed
                ), f"Column {col_letter} width {col_dim.width} exceeds cap {max_allowed}"

    def test_all_columns_have_reasonable_widths(self):
        """Verify no column is collapsed — all have width >= MIN_DATA_WIDTH floor."""

        wb = openpyxl.Workbook()
        report = _make_crypto_tax_report()
        write_crypto_supplementary_sheet(wb, report)
        ws = wb["Crypto Supplementary"]

        for col_idx in range(1, 12):  # Columns A through K
            col_letter = openpyxl.utils.get_column_letter(col_idx)
            width = ws.column_dimensions[col_letter].width
            assert width is not None, f"Column {col_letter} should have a width set"
            assert width >= 4, f"Column {col_letter} width {width} is too small"


@pytest.mark.unit
class TestCryptoSupplementarySheetReviewRequired:
    """Tests for Section 5: REVIEW REQUIRED."""

    def test_review_required_section_title(self):
        """Test that the Review Required section title is rendered correctly."""
        review_entries = [
            CryptoReviewEntry(
                source_section="capital_gains",
                date="2025-01-15",
                asset="BTC",
                platform="Kraken",
                review_reason="Zero cost basis",
            ),
        ]
        wb = openpyxl.Workbook()
        report = _make_crypto_tax_report(review_entries=review_entries)
        write_crypto_supplementary_sheet(wb, report)
        ws = wb["Crypto Supplementary"]

        # Find the section title
        section_row = None
        for r in range(1, ws.max_row + 1):
            if ws.cell(r, 1).value == "5. REVIEW REQUIRED":
                section_row = r
                break
        assert section_row is not None
        assert ws.cell(section_row, 1).font.bold is True

    def test_review_required_headers(self):
        """Test that Review Required section headers are rendered correctly."""
        review_entries = [
            CryptoReviewEntry(
                source_section="income",
                date="2025-01-15",
                asset="ETH",
                platform="ByBit",
                review_reason="Missing price data",
            ),
        ]
        wb = openpyxl.Workbook()
        report = _make_crypto_tax_report(review_entries=review_entries)
        write_crypto_supplementary_sheet(wb, report)
        ws = wb["Crypto Supplementary"]

        # Find the header row (after section title and note)
        header_row = None
        for r in range(1, ws.max_row + 1):
            if ws.cell(r, 1).value == "Source":
                header_row = r
                break
        assert header_row is not None
        assert ws.cell(header_row, 1).value == "Source"
        assert ws.cell(header_row, 2).value == "Date"
        assert ws.cell(header_row, 3).value == "Asset"
        assert ws.cell(header_row, 4).value == "Platform"
        assert ws.cell(header_row, 5).value == "Review reason"
        # Verify headers are bold
        for col in range(1, 6):
            assert ws.cell(header_row, col).font.bold is True

    def test_review_required_data_rows(self):
        """Test that review entry data rows are rendered correctly."""
        review_entries = [
            CryptoReviewEntry(
                source_section="capital_gains",
                date="2025-01-15",
                asset="BTC",
                platform="Kraken",
                review_reason="Zero cost basis",
            ),
            CryptoReviewEntry(
                source_section="income",
                date="2025-01-20",
                asset="ETH",
                platform="ByBit",
                review_reason="Missing price data",
            ),
        ]
        wb = openpyxl.Workbook()
        report = _make_crypto_tax_report(review_entries=review_entries)
        write_crypto_supplementary_sheet(wb, report)
        ws = wb["Crypto Supplementary"]

        # Find the data start row (after headers)
        header_row = None
        for r in range(1, ws.max_row + 1):
            if ws.cell(r, 1).value == "Source":
                header_row = r
                break
        assert header_row is not None

        # First data row
        data_row = header_row + 1
        assert ws.cell(data_row, 1).value == "Capital Gains"
        assert ws.cell(data_row, 2).value == "2025-01-15"
        assert ws.cell(data_row, 3).value == "BTC"
        assert ws.cell(data_row, 4).value == "Kraken"
        assert ws.cell(data_row, 5).value == "Zero cost basis"

        # Second data row
        data_row += 1
        assert ws.cell(data_row, 1).value == "Income"
        assert ws.cell(data_row, 2).value == "2025-01-20"
        assert ws.cell(data_row, 3).value == "ETH"
        assert ws.cell(data_row, 4).value == "ByBit"
        assert ws.cell(data_row, 5).value == "Missing price data"

    def test_review_required_suspicious_flag_formatting(self):
        """Test that suspicious assets are highlighted with red font."""
        review_entries = [
            CryptoReviewEntry(
                source_section="income",
                date="2025-01-15",
                asset="BTC",
                platform="Kraken",
                review_reason="Zero cost basis",
                is_suspicious=False,
            ),
            CryptoReviewEntry(
                source_section="capital_gains",
                date="2025-01-20",
                asset="РUB",
                platform="ByBit",
                review_reason="Non-Latin characters",
                is_suspicious=True,
            ),
        ]
        wb = openpyxl.Workbook()
        report = _make_crypto_tax_report(review_entries=review_entries)
        write_crypto_supplementary_sheet(wb, report)
        ws = wb["Crypto Supplementary"]

        # Find the data start row
        header_row = None
        for r in range(1, ws.max_row + 1):
            if ws.cell(r, 1).value == "Source":
                header_row = r
                break
        assert header_row is not None

        # First row - not suspicious, should have default formatting
        non_suspicious_row = header_row + 1
        asset_cell = ws.cell(non_suspicious_row, 3)
        assert asset_cell.value == "BTC"
        assert asset_cell.font.bold is False
        # Default color (None or theme color) - not the suspicious red
        assert asset_cell.font.color.rgb not in ("FFFF0000", "00FF0000")

        # Second row - suspicious, should have red bold formatting
        suspicious_row = header_row + 2
        asset_cell = ws.cell(suspicious_row, 3)
        assert asset_cell.value == "РUB"
        assert asset_cell.font.bold is True
        assert asset_cell.font.color.rgb in ("FFFF0000", "00FF0000")  # Red text (alpha may vary)

    def test_review_required_no_items_shows_message(self):
        """Test that 'No review items' message is shown when there are no review entries."""
        wb = openpyxl.Workbook()
        report = _make_crypto_tax_report(review_entries=[])
        write_crypto_supplementary_sheet(wb, report)
        ws = wb["Crypto Supplementary"]

        # Find the header row
        header_row = None
        for r in range(1, ws.max_row + 1):
            if ws.cell(r, 1).value == "Source":
                header_row = r
                break
        assert header_row is not None

        # Data row should show "No review items"
        data_row = header_row + 1
        assert ws.cell(data_row, 1).value == "No review items"
