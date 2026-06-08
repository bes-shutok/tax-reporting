"""Tests for the Assumptions & Methodology sheet writer."""

from decimal import Decimal

import openpyxl
import pytest

from tax_reporting.application.crypto_reporting import (
    CapitalGainPeriodStats,
    CryptoCapitalGainEntry,
    CryptoCapitalGainStats,
    CryptoReconciliationSummary,
    CryptoRewardIncomeEntry,
    CryptoTaxReport,
    RewardTaxClassification,
)
from tax_reporting.application.persisting.assumptions_sheet import write_assumptions_and_methodology_sheet
from tests.conftest import make_operator_origin


def _make_origin(platform: str, assumption: str | None = None, platform_review_required: bool = False):
    """Create an OperatorOrigin for the given platform."""
    return make_operator_origin(
        platform=platform,
        operator_entity=f"{platform} Entity",
        operator_country="US",
        review_required=False,
        platform_assumption=assumption,
        platform_review_required=platform_review_required,
    )


def _make_capital_entry(
    platform: str = "Kraken",
    operator_assumption: str | None = None,
    platform_review_required: bool = False,
) -> CryptoCapitalGainEntry:
    """Create a capital gain entry with optional platform assumption/review flag."""
    origin = _make_origin(platform, operator_assumption, platform_review_required)
    return CryptoCapitalGainEntry(
        disposal_date="2025-06-15",
        acquisition_date="2025-01-10",
        asset="BTC",
        amount=Decimal("0.5"),
        cost_eur=Decimal("20000"),
        proceeds_eur=Decimal("25000"),
        gain_loss_eur=Decimal("5000"),
        holding_period="Short-term",
        wallet="kraken-wallet",
        platform=platform,
        chain="Ethereum",
        operator_origin=origin,
        annex_hint="J",
        review_required=False,
        notes="",
    )


def _make_reward_entry(
    platform: str = "Kraken",
    operator_assumption: str | None = None,
    platform_review_required: bool = False,
) -> CryptoRewardIncomeEntry:
    """Create a reward entry with optional platform assumption/review flag."""
    origin = _make_origin(platform, operator_assumption, platform_review_required)
    return CryptoRewardIncomeEntry(
        date="2025-01-15",
        asset="ETH",
        amount=Decimal("1"),
        value_eur=Decimal("100"),
        income_label="Staking",
        source_type="staking",
        wallet="kraken-wallet",
        platform=platform,
        chain="Ethereum",
        operator_origin=origin,
        annex_hint="J",
        foreign_tax_eur=Decimal("0"),
        tax_classification=RewardTaxClassification.TAXABLE_NOW,
        review_required=False,
        description="Staking reward",
    )


def _make_stats() -> CryptoCapitalGainStats:
    """Create empty stats for test reports."""
    empty = CapitalGainPeriodStats(
        count=0,
        cost_total_eur=Decimal("0"),
        proceeds_total_eur=Decimal("0"),
        gain_loss_total_eur=Decimal("0"),
    )
    return CryptoCapitalGainStats(
        short_term=empty,
        long_term=empty,
        mixed=empty,
        unknown=empty,
        grand_total=empty,
    )


def _make_crypto_tax_report(
    capital_entries: list[CryptoCapitalGainEntry] | None = None,
    reward_entries: list[CryptoRewardIncomeEntry] | None = None,
) -> CryptoTaxReport:
    """Create a test crypto tax report."""
    entries = capital_entries or []
    rewards = reward_entries or []
    reconciliation = CryptoReconciliationSummary(
        capital_rows=len(entries),
        reward_rows=len(rewards),
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
        capital_entries=entries,
        reward_entries=rewards,
        reconciliation=reconciliation,
        capital_gain_stats=_make_stats(),
        pdf_summary=None,
        zero_basis_review_threshold=Decimal("50"),
    )


@pytest.mark.unit
class TestAssumptionsAndMethodologySheetName:
    """Tests that the sheet is created with the correct name."""

    def test_sheet_named_assumptions_and_methodology(self):
        wb = openpyxl.Workbook()
        write_assumptions_and_methodology_sheet(wb)
        assert "Assumptions & Methodology" in wb.sheetnames


@pytest.mark.unit
class TestAssumptionsAndMethodologySheetTitle:
    """Tests that the sheet writes the title correctly."""

    def test_title_row_present(self):
        wb = openpyxl.Workbook()
        write_assumptions_and_methodology_sheet(wb)
        ws = wb["Assumptions & Methodology"]
        assert ws.cell(1, 1).value == "Assumptions & Methodology"

    def test_title_is_bold(self):
        wb = openpyxl.Workbook()
        write_assumptions_and_methodology_sheet(wb)
        ws = wb["Assumptions & Methodology"]
        assert ws.cell(1, 1).font.bold is True


@pytest.mark.unit
class TestPlatformAssumptionsSection:
    """Tests that the Platform Assumptions section (section 1) works correctly."""

    def test_no_entries_shows_message(self):
        wb = openpyxl.Workbook()
        write_assumptions_and_methodology_sheet(wb)
        ws = wb["Assumptions & Methodology"]
        assert "No platform data found" in ws.cell(5, 1).value

    def test_all_platforms_appear_even_without_assumption(self):
        """Every platform from the data should appear, not just ones with assumption text."""
        wb = openpyxl.Workbook()
        entry = _make_capital_entry(platform="Kraken", operator_assumption=None)
        report = _make_crypto_tax_report(capital_entries=[entry])
        write_assumptions_and_methodology_sheet(wb, capital_entries=report.capital_entries)
        ws = wb["Assumptions & Methodology"]
        # Row 6 should contain Kraken (headers at row 5)
        assert ws.cell(6, 1).value == "Kraken"

    def test_platform_review_required_shows_yes(self):
        """Platforms with platform_review_required=True show YES in column 5."""
        wb = openpyxl.Workbook()
        entry = _make_capital_entry(
            platform="Bybit",
            operator_assumption="verify account region",
            platform_review_required=True,
        )
        report = _make_crypto_tax_report(capital_entries=[entry])
        write_assumptions_and_methodology_sheet(wb, capital_entries=report.capital_entries)
        ws = wb["Assumptions & Methodology"]
        # New layout: Platform | Operator Entity | Country | Confidence | Review Required | Assumption | Count
        assert ws.cell(6, 1).value == "Bybit"
        assert ws.cell(6, 5).value == "YES"

    def test_platform_no_review_shows_no(self):
        """Platforms without platform_review_required show NO in column 5."""
        wb = openpyxl.Workbook()
        entry = _make_capital_entry(platform="Kraken", platform_review_required=False)
        report = _make_crypto_tax_report(capital_entries=[entry])
        write_assumptions_and_methodology_sheet(wb, capital_entries=report.capital_entries)
        ws = wb["Assumptions & Methodology"]
        assert ws.cell(6, 5).value == "NO"


    def test_row_review_flag_does_not_trigger_platform_review(self):
        """Row-level review_required must not bleed into platform review column/fill."""
        wb = openpyxl.Workbook()
        origin = make_operator_origin(
            platform="Kraken",
            operator_entity="Kraken Entity",
            operator_country="US",
            review_required=True,
            review_reason="Origin row needs review",
            platform_review_required=False,
        )
        entry = CryptoCapitalGainEntry(
            disposal_date="2025-06-15",
            acquisition_date="2025-01-10",
            asset="BTC",
            amount=Decimal("0.5"),
            cost_eur=Decimal("20000"),
            proceeds_eur=Decimal("25000"),
            gain_loss_eur=Decimal("5000"),
            holding_period="Short-term",
            wallet="kraken-wallet",
            platform="Kraken",
            chain="Ethereum",
            operator_origin=origin,
            annex_hint="J",
            review_required=True,
            review_reason="Row needs manual review",
            notes="",
        )
        report = _make_crypto_tax_report(capital_entries=[entry])
        write_assumptions_and_methodology_sheet(wb, capital_entries=report.capital_entries)
        ws = wb["Assumptions & Methodology"]

        assert ws.cell(6, 5).value == "NO"
        assert ws.cell(6, 1).fill.fill_type is None

    def test_assumption_text_in_column_6(self):
        """Assumption text appears in column 6."""
        wb = openpyxl.Workbook()
        entry = _make_capital_entry(
            platform="Bybit",
            operator_assumption="Bybit uses account-region specific entities; verify your account region",
        )
        report = _make_crypto_tax_report(capital_entries=[entry])
        write_assumptions_and_methodology_sheet(wb, capital_entries=report.capital_entries)
        ws = wb["Assumptions & Methodology"]
        assert "account-region" in ws.cell(6, 6).value

    def test_transaction_count_in_column_7(self):
        """Transaction count appears in column 7."""
        wb = openpyxl.Workbook()
        bybit_entries = [_make_capital_entry(platform="Bybit") for _ in range(3)]
        report = _make_crypto_tax_report(capital_entries=bybit_entries)
        write_assumptions_and_methodology_sheet(wb, capital_entries=report.capital_entries)
        ws = wb["Assumptions & Methodology"]
        assert ws.cell(6, 7).value == 3

    def test_multiple_platforms_all_listed(self):
        """Multiple platforms from capital and reward entries all appear."""
        wb = openpyxl.Workbook()
        bybit_entry = _make_capital_entry(platform="Bybit", platform_review_required=True)
        mantle_reward = _make_reward_entry(platform="Mantle")
        kraken_entry = _make_capital_entry(platform="Kraken")
        report = _make_crypto_tax_report(
            capital_entries=[bybit_entry, kraken_entry],
            reward_entries=[mantle_reward],
        )
        write_assumptions_and_methodology_sheet(
            wb,
            capital_entries=report.capital_entries,
            reward_entries=report.reward_entries,
        )
        ws = wb["Assumptions & Methodology"]
        platforms = [ws.cell(r, 1).value for r in range(6, 10) if ws.cell(r, 1).value]
        assert "Bybit" in platforms
        assert "Mantle" in platforms
        assert "Kraken" in platforms

    def test_review_required_platforms_sorted_first(self):
        """Platforms with platform_review_required=True appear before non-review platforms."""
        wb = openpyxl.Workbook()
        kraken_entry = _make_capital_entry(platform="Kraken", platform_review_required=False)
        bybit_entry = _make_capital_entry(platform="Bybit", platform_review_required=True)
        report = _make_crypto_tax_report(capital_entries=[kraken_entry, bybit_entry])
        write_assumptions_and_methodology_sheet(wb, capital_entries=report.capital_entries)
        ws = wb["Assumptions & Methodology"]
        # Bybit (review_required) must appear before Kraken (no review)
        platforms = [ws.cell(r, 1).value for r in range(6, 9) if ws.cell(r, 1).value]
        assert platforms[0] == "Bybit"
        assert platforms[1] == "Kraken"


@pytest.mark.unit
class TestMethodologyAssumptionsSection:
    """Tests that the Methodology Assumptions section (section 2) is rendered correctly."""

    def test_methodology_section_header_present(self):
        """The 'Methodology Assumptions' header should be present after platform data."""
        wb = openpyxl.Workbook()
        entry = _make_capital_entry(platform="Kraken")
        report = _make_crypto_tax_report(capital_entries=[entry])
        write_assumptions_and_methodology_sheet(wb, capital_entries=report.capital_entries)
        ws = wb["Assumptions & Methodology"]

        # Find the methodology header (after platform data)
        methodology_header_found = False
        for row_idx in range(1, 50):
            cell_value = ws.cell(row_idx, 1).value
            if cell_value == "Methodology Assumptions":
                methodology_header_found = True
                assert ws.cell(row_idx, 1).font.bold is True
                break

        assert methodology_header_found, "Methodology Assumptions header not found"

    def test_methodology_section_has_all_five_subsections(self):
        """All five methodology subsections should be present."""
        wb = openpyxl.Workbook()
        entry = _make_capital_entry(platform="Kraken")
        report = _make_crypto_tax_report(capital_entries=[entry])
        write_assumptions_and_methodology_sheet(wb, capital_entries=report.capital_entries)
        ws = wb["Assumptions & Methodology"]

        expected_labels = {
            "Aggregation Approach",
            "FIFO Methodology",
            "Holding Period Classification",
            "Materiality Threshold",
            "Data Sources",
        }

        found_labels = set()
        for row_idx in range(1, 100):
            cell_value = ws.cell(row_idx, 1).value
            if cell_value in expected_labels:
                found_labels.add(cell_value)

        assert found_labels == expected_labels, f"Expected {expected_labels}, found {found_labels}"

    def test_aggregation_approach_mentions_pt_c_025(self):
        """Aggregation Approach should reference PT-C-025."""
        wb = openpyxl.Workbook()
        entry = _make_capital_entry(platform="Kraken")
        report = _make_crypto_tax_report(capital_entries=[entry])
        write_assumptions_and_methodology_sheet(wb, capital_entries=report.capital_entries)
        ws = wb["Assumptions & Methodology"]

        # Find the Aggregation Approach row
        for row_idx in range(1, 100):
            if ws.cell(row_idx, 1).value == "Aggregation Approach":
                description = ws.cell(row_idx, 2).value
                assert "PT-C-025" in description
                assert "Quadro 9.4" in description
                assert "blue fill" in description
                break
        else:
            pytest.fail("Aggregation Approach row not found")

    def test_fifo_methodology_mentions_cirs_art_43(self):
        """FIFO Methodology should reference CIRS art. 43."""
        wb = openpyxl.Workbook()
        entry = _make_capital_entry(platform="Kraken")
        report = _make_crypto_tax_report(capital_entries=[entry])
        write_assumptions_and_methodology_sheet(wb, capital_entries=report.capital_entries)
        ws = wb["Assumptions & Methodology"]

        # Find the FIFO Methodology row
        for row_idx in range(1, 100):
            if ws.cell(row_idx, 1).value == "FIFO Methodology":
                description = ws.cell(row_idx, 2).value
                assert "CIRS art. 43" in description
                assert "PT-C-008" in description
                break
        else:
            pytest.fail("FIFO Methodology row not found")

    def test_holding_period_mentions_calendar_year_arithmetic(self):
        """Holding Period Classification should mention calendar-year arithmetic."""
        wb = openpyxl.Workbook()
        entry = _make_capital_entry(platform="Kraken")
        report = _make_crypto_tax_report(capital_entries=[entry])
        write_assumptions_and_methodology_sheet(wb, capital_entries=report.capital_entries)
        ws = wb["Assumptions & Methodology"]

        # Find the Holding Period Classification row
        for row_idx in range(1, 100):
            if ws.cell(row_idx, 1).value == "Holding Period Classification":
                description = ws.cell(row_idx, 2).value
                assert "Calendar-year arithmetic" in description
                assert "2024-02-29" in description
                assert "PT-C-011" in description
                break
        else:
            pytest.fail("Holding Period Classification row not found")

    def test_materiality_threshold_mentions_sub_1_eur(self):
        """Materiality Threshold should mention |gain/loss| < 1 EUR."""
        wb = openpyxl.Workbook()
        entry = _make_capital_entry(platform="Kraken")
        report = _make_crypto_tax_report(capital_entries=[entry])
        write_assumptions_and_methodology_sheet(wb, capital_entries=report.capital_entries)
        ws = wb["Assumptions & Methodology"]

        # Find the Materiality Threshold row
        for row_idx in range(1, 100):
            if ws.cell(row_idx, 1).value == "Materiality Threshold":
                description = ws.cell(row_idx, 2).value
                assert "< 1 EUR" in description
                assert "PT-C-028" in description
                break
        else:
            pytest.fail("Materiality Threshold row not found")

    def test_data_sources_mentions_ib_and_koinly(self):
        """Data Sources should mention Interactive Brokers and Koinly."""
        wb = openpyxl.Workbook()
        entry = _make_capital_entry(platform="Kraken")
        report = _make_crypto_tax_report(capital_entries=[entry])
        write_assumptions_and_methodology_sheet(wb, capital_entries=report.capital_entries)
        ws = wb["Assumptions & Methodology"]

        # Find the Data Sources row
        for row_idx in range(1, 100):
            if ws.cell(row_idx, 1).value == "Data Sources":
                description = ws.cell(row_idx, 2).value
                assert "Interactive Brokers" in description
                assert "Koinly" in description
                assert "config.ini" in description
                break
        else:
            pytest.fail("Data Sources row not found")
