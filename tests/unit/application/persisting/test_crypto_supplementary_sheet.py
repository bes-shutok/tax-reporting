"""Tests for the crypto supplementary sheet writer."""

import re
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
from tax_reporting.application.persisting.tax_constants import _INCOME_CODE_DESCRIPTIONS

# make_operator_origin is a module-level helper from conftest, not a pytest fixture
from tests.conftest import build_koinly_jurisdiction, make_operator_origin


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
        "income_code": "",
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
        write_crypto_supplementary_sheet(wb, report, build_koinly_jurisdiction())
        assert "Crypto Supplementary" in wb.sheetnames


@pytest.mark.unit
class TestCryptoSupplementarySheetIncomeCodes:
    """Tests for section 1: Income Codes reference."""

    def test_section_1_title_written(self):
        wb = openpyxl.Workbook()
        report = _make_crypto_tax_report()
        write_crypto_supplementary_sheet(wb, report, build_koinly_jurisdiction())
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
        write_crypto_supplementary_sheet(wb, report, build_koinly_jurisdiction())
        ws = wb["Crypto Supplementary"]
        for row in ws.iter_rows(min_row=1, max_row=ws.max_row, min_col=1, max_col=1):
            if row[0].value == "1. INCOME CODES REFERENCE":
                assert row[0].font.bold is True
                break

    def test_reference_note_is_italic(self):
        wb = openpyxl.Workbook()
        report = _make_crypto_tax_report()
        write_crypto_supplementary_sheet(wb, report, build_koinly_jurisdiction())
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
        write_crypto_supplementary_sheet(wb, report, build_koinly_jurisdiction())
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
        write_crypto_supplementary_sheet(wb, report, build_koinly_jurisdiction())
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
        write_crypto_supplementary_sheet(wb, report, build_koinly_jurisdiction())
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

        # Only the official Tabela V crypto code (E25) is rendered under PT.
        # The set is sourced from the consolidated owner, not a hardcoded literal,
        # so the assertion tracks the owner without duplicating its contents.
        assert set(codes_found) == set(_INCOME_CODE_DESCRIPTIONS.keys())

    def test_income_codes_sorted_alphabetically(self):
        wb = openpyxl.Workbook()
        report = _make_crypto_tax_report()
        write_crypto_supplementary_sheet(wb, report, build_koinly_jurisdiction())
        ws = wb["Crypto Supplementary"]
        header_row = None
        for r in range(1, ws.max_row + 1):
            if ws.cell(r, 1).value == "Country":
                header_row = r
                break
        assert header_row is not None

        codes = []
        for r in range(header_row + 1, ws.max_row + 1):
            first_cell = ws.cell(r, 1).value
            # Stop when we hit the next section
            if first_cell and isinstance(first_cell, str) and first_cell.startswith("2."):
                break
            code = ws.cell(r, 2).value
            if code and isinstance(code, str):
                codes.append(code)

        # Codes are rendered via sorted(_INCOME_CODE_DESCRIPTIONS.items())
        assert codes == sorted(codes)

    def test_income_code_table_renders_official_codes_under_pt(self):
        """Under PT the reference table lists the official E25 code with its
        official description, the Country column is sourced from the
        jurisdiction (not a hardcoded literal), and the code matches the
        consolidated owner."""
        wb = openpyxl.Workbook()
        report = _make_crypto_tax_report()
        write_crypto_supplementary_sheet(wb, report, build_koinly_jurisdiction())
        ws = wb["Crypto Supplementary"]
        header_row = None
        for r in range(1, ws.max_row + 1):
            if ws.cell(r, 1).value == "Country":
                header_row = r
                break
        assert header_row is not None

        # Single official code under PT
        assert ws.cell(header_row + 1, 1).value == "PT"
        assert ws.cell(header_row + 1, 2).value == "E25"
        assert ws.cell(header_row + 1, 3).value == _INCOME_CODE_DESCRIPTIONS["E25"]
        # No second code row before section 2
        assert ws.cell(header_row + 2, 1).value != "PT"

    def test_income_code_reference_omitted_when_classification_off(self):
        """When classify_rewards_with_income_codes is False the entire
        '1. INCOME CODES REFERENCE' section is omitted (structural absence,
        not field-blanked)."""
        wb = openpyxl.Workbook()
        report = _make_crypto_tax_report()
        write_crypto_supplementary_sheet(
            wb, report, build_koinly_jurisdiction(country="DE", classify_rewards_with_income_codes=False)
        )
        ws = wb["Crypto Supplementary"]

        for r in range(1, ws.max_row + 1):
            val = ws.cell(r, 1).value
            assert val != "1. INCOME CODES REFERENCE"
            assert val != "Country"
        # The first visible section is renumbered to "1." so the list does not
        # start at "2." (which would imply a missing predecessor).
        found_renumbered_first = False
        for r in range(1, ws.max_row + 1):
            if ws.cell(r, 1).value == "1. TAXABLE-NOW - SUPPORT DETAIL":
                found_renumbered_first = True
                break
        assert found_renumbered_first


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
        write_crypto_supplementary_sheet(wb, report, build_koinly_jurisdiction())
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
        write_crypto_supplementary_sheet(wb, report, build_koinly_jurisdiction())
        ws = wb["Crypto Supplementary"]
        for row in ws.iter_rows(min_row=1, max_row=ws.max_row, min_col=1, max_col=1):
            if row[0].value == "2. TAXABLE-NOW - SUPPORT DETAIL":
                assert row[0].font.bold is True
                break

    def test_taxable_note_mentions_reporting_worksheet(self):
        wb = openpyxl.Workbook()
        report = _make_crypto_tax_report()
        write_crypto_supplementary_sheet(wb, report, build_koinly_jurisdiction())
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
        write_crypto_supplementary_sheet(wb, report, build_koinly_jurisdiction())
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
        write_crypto_supplementary_sheet(wb, report, build_koinly_jurisdiction())
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
        write_crypto_supplementary_sheet(wb, report, build_koinly_jurisdiction())
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
        write_crypto_supplementary_sheet(wb, report, build_koinly_jurisdiction())
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
        write_crypto_supplementary_sheet(wb, report, build_koinly_jurisdiction())
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
        write_crypto_supplementary_sheet(wb, report, build_koinly_jurisdiction())
        ws = wb["Crypto Supplementary"]
        for row in ws.iter_rows(min_row=1, max_row=ws.max_row, min_col=1, max_col=1):
            if row[0].value == "3. DEFERRED BY LAW - SUPPORT DETAIL":
                assert row[0].font.bold is True
                break

    def test_deferred_note_is_italic(self):
        wb = openpyxl.Workbook()
        report = _make_crypto_tax_report()
        write_crypto_supplementary_sheet(wb, report, build_koinly_jurisdiction())
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
        write_crypto_supplementary_sheet(wb, report, build_koinly_jurisdiction())
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
        write_crypto_supplementary_sheet(wb, report, build_koinly_jurisdiction())
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
        write_crypto_supplementary_sheet(wb, report, build_koinly_jurisdiction())
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
        write_crypto_supplementary_sheet(wb, report, build_koinly_jurisdiction())
        ws = wb["Crypto Supplementary"]
        for row in ws.iter_rows(min_row=1, max_row=ws.max_row, min_col=1, max_col=1):
            if row[0].value == "4. REWARDS CLASSIFICATION RECONCILIATION":
                assert row[0].font.bold is True
                break

    def test_section4_splits_detail_and_dust_counts(self):
        """Section 4 reconciliation splits the taxable-now count into detail + dust.

        Given a CryptoTaxReport with 2 detail taxable-now rows (BTC priced) and
        3 dust taxable-now rows (BTC zero-value, priced elsewhere in the export),
        Section 4 must render the new split lines
        ``("Taxable-now detail rows", 2)`` and
        ``("Taxable-now dust rows (suppressed from detail)", 3)`` and must NOT
        render the old ``("Taxable-now rows (immediately taxable)", 5)`` line.

        RED for Task 5: the Section 4 reconciliation still emits the old single
        line; Task 6 flips it GREEN by replacing the single reconciliation row
        with the two split rows.
        """
        # Two priced BTC taxable-now rows -> detail (real_rows).
        btc_real_1 = _make_reward_entry(
            asset="BTC", value_eur=Decimal("0.50"), wallet="Demo Spot", platform="Demo Spot", chain="Bitcoin"
        )
        btc_real_2 = _make_reward_entry(
            asset="BTC", value_eur=Decimal("0.30"), wallet="Wirex", platform="Wirex", chain="Bitcoin"
        )
        # Three zero-value BTC taxable-now rows -> dust (BTC has priced rows above).
        btc_dust_1 = _make_reward_entry(
            asset="BTC", value_eur=Decimal("0"), wallet="Demo Spot", platform="Demo Spot", chain="Bitcoin"
        )
        btc_dust_2 = _make_reward_entry(
            asset="BTC", value_eur=Decimal("0"), wallet="Wirex", platform="Wirex", chain="Bitcoin"
        )
        btc_dust_3 = _make_reward_entry(
            asset="BTC", value_eur=Decimal("0"), wallet="Demo Spot", platform="Demo Spot", chain="Bitcoin"
        )
        report = _make_crypto_tax_report(
            reward_entries=[btc_real_1, btc_real_2, btc_dust_1, btc_dust_2, btc_dust_3]
        )
        wb = openpyxl.Workbook()
        write_crypto_supplementary_sheet(wb, report, build_koinly_jurisdiction())
        ws = wb["Crypto Supplementary"]
        keys = _section4_reconciliation_keys(ws)
        assert keys["Taxable-now detail rows"] == 2, (
            f"expected new 'Taxable-now detail rows' split line with value 2, got keys={keys}"
        )
        assert keys["Taxable-now dust rows (suppressed from detail)"] == 3, (
            f"expected new 'Taxable-now dust rows (suppressed from detail)' split line with value 3, "
            f"got keys={keys}"
        )
        # The old single-line reconciliation row must be absent after the split.
        assert "Taxable-now rows (immediately taxable)" not in keys, (
            f"old 'Taxable-now rows (immediately taxable)' line still present after split; keys={keys}"
        )

    def test_reconciliation_key_value_pairs(self):
        taxable = _make_reward_entry(classification=RewardTaxClassification.TAXABLE_NOW, value_eur=Decimal("100"))
        deferred = _make_reward_entry(
            classification=RewardTaxClassification.DEFERRED_BY_LAW, value_eur=Decimal("200"), asset="BTC"
        )
        report = _make_crypto_tax_report(reward_entries=[taxable, deferred])
        wb = openpyxl.Workbook()
        write_crypto_supplementary_sheet(wb, report, build_koinly_jurisdiction())
        ws = wb["Crypto Supplementary"]
        keys = _section4_reconciliation_keys(ws)
        # Unchanged reconciliation lines (preserved intent): the raw count,
        # deferred count, and EUR totals are still rendered.
        assert keys["Total reward rows (raw)"] == 2
        assert keys["Deferred-by-law rows (taxation deferred)"] == 1
        assert keys["Taxable-now total value (EUR)"] == float(Decimal("100"))
        assert keys["Deferred total value (EUR)"] == float(Decimal("200"))
        # New split lines replace the old single taxable-now count. The priced
        # ETH taxable-now row stays in detail (real_rows), and there are no
        # zero-value rows on a priced asset, so dust_rows is empty.
        assert keys["Taxable-now detail rows"] == 1, (
            f"expected new 'Taxable-now detail rows' split line with value 1, got keys={keys}"
        )
        assert keys["Taxable-now dust rows (suppressed from detail)"] == 0, (
            f"expected new 'Taxable-now dust rows (suppressed from detail)' split line with value 0, "
            f"got keys={keys}"
        )
        # The old single-line reconciliation row must be absent after the split.
        assert "Taxable-now rows (immediately taxable)" not in keys, (
            f"old 'Taxable-now rows (immediately taxable)' line still present after split; keys={keys}"
        )

    def test_reconciliation_empty_rewards(self):
        report = _make_crypto_tax_report(reward_entries=[])
        wb = openpyxl.Workbook()
        write_crypto_supplementary_sheet(wb, report, build_koinly_jurisdiction())
        ws = wb["Crypto Supplementary"]
        keys = _section4_reconciliation_keys(ws)
        # Empty-path regression guard: both new split lines render with 0,
        # replacing the old single ("Taxable-now rows (immediately taxable)", 0).
        assert keys["Taxable-now detail rows"] == 0, (
            f"expected 'Taxable-now detail rows' == 0 on empty path, got keys={keys}"
        )
        assert keys["Taxable-now dust rows (suppressed from detail)"] == 0, (
            f"expected 'Taxable-now dust rows (suppressed from detail)' == 0 on empty path, got keys={keys}"
        )
        assert "Taxable-now rows (immediately taxable)" not in keys, (
            f"old 'Taxable-now rows (immediately taxable)' line still present on empty path; keys={keys}"
        )


@pytest.mark.unit
class TestCryptoSupplementarySheetAutoWidth:
    """Tests that auto_column_width is called."""

    def test_auto_width_adjusts_columns(self):
        wb = openpyxl.Workbook()
        report = _make_crypto_tax_report()
        write_crypto_supplementary_sheet(wb, report, build_koinly_jurisdiction())
        ws = wb["Crypto Supplementary"]
        assert ws.column_dimensions["A"].width > 0

    def test_column_widths_respect_max_cell_width_cap(self):
        """Verify no column exceeds MAX_CELL_WIDTH + 2 even with long notes."""
        from tax_reporting.application.persisting.excel_utils import MAX_CELL_WIDTH

        wb = openpyxl.Workbook()
        report = _make_crypto_tax_report()
        write_crypto_supplementary_sheet(wb, report, build_koinly_jurisdiction())
        ws = wb["Crypto Supplementary"]

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
        write_crypto_supplementary_sheet(wb, report, build_koinly_jurisdiction())
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
        write_crypto_supplementary_sheet(wb, report, build_koinly_jurisdiction())
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
        write_crypto_supplementary_sheet(wb, report, build_koinly_jurisdiction())
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
        write_crypto_supplementary_sheet(wb, report, build_koinly_jurisdiction())
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
        write_crypto_supplementary_sheet(wb, report, build_koinly_jurisdiction())
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
        write_crypto_supplementary_sheet(wb, report, build_koinly_jurisdiction())
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


def _section2_bounds(ws) -> tuple[int, int]:
    """Return the (start_row, end_row_exclusive) for Section 2.

    ``end_row_exclusive`` is the row of the next section title (3. DEFERRED
    BY LAW) or ``ws.max_row + 1`` if not found, so callers can iterate
    Section 2 with ``range(start, end)``.
    """
    start = None
    for r in range(1, ws.max_row + 1):
        if ws.cell(r, 1).value == "2. TAXABLE-NOW - SUPPORT DETAIL":
            start = r
            break
    assert start is not None, "Section 2 title not rendered"
    end = ws.max_row + 1
    for r in range(start + 1, ws.max_row + 1):
        val = ws.cell(r, 1).value
        if isinstance(val, str) and val.startswith("3."):
            end = r
            break
    return start, end


def _section2_strings(ws) -> list[str]:
    """Collect all column-A string cell values rendered inside Section 2."""
    start, end = _section2_bounds(ws)
    out: list[str] = []
    for r in range(start, end):
        val = ws.cell(r, 1).value
        if isinstance(val, str):
            out.append(val)
    return out


def _section2_reward_detail_rows(ws) -> list[dict[int, object]]:
    """Return Section 2 detail data rows (skipping the header row, labels, and the dust block).

    A row is treated as a detail row iff column 2 (Asset) is populated AND
    column 4 (Income type) is populated AND column 1 is not the header row's
    ``"Date"`` and not a label/dust line. Column 4 (``source_type``) is the
    cleanest discriminator: it is empty on title/note/label/dust rows and on
    the header row's empty trailing cells, but populated on every real detail
    row produced by ``_write_reward_detail_rows``.
    """
    start, end = _section2_bounds(ws)
    rows: list[dict[int, object]] = []
    skip_prefixes = ("Dust summary:", "No taxable-now", "All taxable-now")
    for r in range(start, end):
        c1 = ws.cell(r, 1).value
        c2 = ws.cell(r, 2).value
        c4 = ws.cell(r, 4).value
        if c2 in (None, ""):
            continue
        if c4 in (None, ""):
            continue
        if isinstance(c1, str) and (c1 == "Date" or c1.startswith(skip_prefixes)):
            continue
        row: dict[int, object] = {}
        for col in range(1, 12):
            row[col] = ws.cell(r, col).value
        rows.append(row)
    return rows


def _section4_reconciliation_keys(ws) -> dict[str, object]:
    """Return the Section 4 key-value pairs as a dict keyed by column-A label.

    Iterates from the ``4. REWARDS CLASSIFICATION RECONCILIATION`` title row
    through the next section title (or end of sheet), collecting every row
    whose column-A cell is a non-empty string into ``{key: col_b_value}``.
    Robust to the post-Task-6 split (the title is followed by N key/value rows
    rather than a fixed count), so callers can assert on individual keys
    without pinning row offsets.
    """
    start = None
    for r in range(1, ws.max_row + 1):
        if ws.cell(r, 1).value == "4. REWARDS CLASSIFICATION RECONCILIATION":
            start = r
            break
    assert start is not None, "Section 4 title not rendered"
    keys: dict[str, object] = {}
    for r in range(start + 1, ws.max_row + 1):
        key = ws.cell(r, 1).value
        if isinstance(key, str) and re.match(r"^\d+\.\s", key):
            # Hit the next numbered section title (e.g. "5. REVIEW REQUIRED").
            break
        if isinstance(key, str) and key:
            keys[key] = ws.cell(r, 2).value
    return keys


@pytest.mark.unit
class TestCryptoSupplementarySheetDustSummary:
    """Worksheet-level tests for the Section 2 dust partition (Part 7).

    RED for Task 3: ``write_crypto_supplementary_sheet`` does not yet partition
    taxable-now rows into (real, dust), does not render a "Dust summary:" block,
    and uses the old two-state empty label. These tests fail via assertion
    against the unchanged render; Task 4 (GREEN) adds the partition + helpers.
    """

    def test_btc_zero_collapses_to_dust(self):
        """A zero-value BTC row whose asset has a priced row collapses to dust."""
        btc_priced = _make_reward_entry(
            asset="BTC", value_eur=Decimal("0.50"), wallet="Demo Spot", platform="Demo Spot", chain="Bitcoin"
        )
        btc_zero = _make_reward_entry(
            asset="BTC", value_eur=Decimal("0"), wallet="Demo Spot", platform="Demo Spot", chain="Bitcoin"
        )
        report = _make_crypto_tax_report(reward_entries=[btc_priced, btc_zero])
        wb = openpyxl.Workbook()
        write_crypto_supplementary_sheet(wb, report, build_koinly_jurisdiction())
        ws = wb["Crypto Supplementary"]

        # The zero-value BTC row must NOT appear in the Section 2 detail table.
        for row in _section2_reward_detail_rows(ws):
            assert not (
                str(row.get(2, "")) == "BTC" and float(row.get(3, -1)) == 0.0
            ), "zero-value BTC row leaked into Section 2 detail table"

        # A dust summary block with a BTC line for 1 row summed to 0.00 must render.
        section_strs = _section2_strings(ws)
        assert any(s == "Dust summary:" for s in section_strs), "Dust summary header missing"
        btc_line_present = any(
            re.search(r"BTC dust .*: 1 rows, summed Value EUR = 0\.00", s) for s in section_strs
        )
        assert btc_line_present, f"BTC dust line missing in {section_strs}"

    def test_osbgt_zero_keeps_per_row_yes(self):
        """OSBGT (no priced row anywhere) keeps per-row YES (the r9 headline fix).

        Fails under a popular-token discriminator because OSBGT *is* popular;
        the has-any-priced-row discriminator keeps it in detail.
        """
        osbgt = _make_reward_entry(
            asset="OSBGT",
            value_eur=Decimal("0"),
            wallet="Demo Spot",
            platform="Demo Spot",
            chain="Berachain",
            review_required=True,
            review_reason="Unpriced wrapper token - manual pricing required",
        )
        report = _make_crypto_tax_report(reward_entries=[osbgt])
        wb = openpyxl.Workbook()
        write_crypto_supplementary_sheet(wb, report, build_koinly_jurisdiction())
        ws = wb["Crypto Supplementary"]

        detail = _section2_reward_detail_rows(ws)
        osbgt_rows = [r for r in detail if str(r.get(2, "")) == "OSBGT"]
        assert osbgt_rows, "OSBGT row should appear in Section 2 detail table"
        review_flag = str(osbgt_rows[0].get(10, ""))
        assert review_flag.startswith("YES:"), (
            f"OSBGT review flag must start 'YES:' (r9 headline fix); got {review_flag!r}"
        )

        # No dust summary block should be rendered (nothing routed to dust).
        section_strs = _section2_strings(ws)
        assert not any(s == "Dust summary:" for s in section_strs), (
            "Dust summary rendered when no row routed to dust"
        )

    def test_bgt_zero_with_priced_row_collapses_to_dust(self):
        """BGT (popular AND priced) zero row collapses to dust.

        Fails if the discriminator is popular-set-only (which would keep BGT
        in detail because BGT is in the popular set).
        """
        bgt_priced = _make_reward_entry(
            asset="BGT", value_eur=Decimal("10"), wallet="Demo Spot", platform="Demo Spot", chain="Berachain"
        )
        bgt_zero = _make_reward_entry(
            asset="BGT", value_eur=Decimal("0"), wallet="Demo Spot", platform="Demo Spot", chain="Berachain"
        )
        report = _make_crypto_tax_report(reward_entries=[bgt_priced, bgt_zero])
        wb = openpyxl.Workbook()
        write_crypto_supplementary_sheet(wb, report, build_koinly_jurisdiction())
        ws = wb["Crypto Supplementary"]

        # The zero-value BGT row must NOT appear in Section 2 detail table.
        for row in _section2_reward_detail_rows(ws):
            assert not (
                str(row.get(2, "")) == "BGT" and float(row.get(3, -1)) == 0.0
            ), "zero-value BGT row leaked into Section 2 detail table (popular-set discriminator?)"

        section_strs = _section2_strings(ws)
        assert any(s == "Dust summary:" for s in section_strs), "Dust summary header missing"
        bgt_line_present = any(
            re.search(r"BGT dust .*: 1 rows, summed Value EUR = 0\.00", s) for s in section_strs
        )
        assert bgt_line_present, f"BGT dust line missing in {section_strs}"

    def test_mixed_dust_and_detail_both_render(self):
        """A mix: priced BTC detail row, zero BTC dust row, zero OSBGT YES detail row."""
        btc_priced = _make_reward_entry(
            asset="BTC", value_eur=Decimal("0.50"), wallet="Demo Spot", platform="Demo Spot", chain="Bitcoin"
        )
        btc_zero = _make_reward_entry(
            asset="BTC", value_eur=Decimal("0"), wallet="Demo Spot", platform="Demo Spot", chain="Bitcoin"
        )
        osbgt_zero = _make_reward_entry(
            asset="OSBGT",
            value_eur=Decimal("0"),
            wallet="Demo Spot",
            platform="Demo Spot",
            chain="Berachain",
            review_required=True,
            review_reason="Unpriced wrapper token - manual pricing required",
        )
        report = _make_crypto_tax_report(reward_entries=[btc_priced, btc_zero, osbgt_zero])
        wb = openpyxl.Workbook()
        write_crypto_supplementary_sheet(wb, report, build_koinly_jurisdiction())
        ws = wb["Crypto Supplementary"]

        detail_assets = [str(r.get(2, "")) for r in _section2_reward_detail_rows(ws)]
        assert "BTC" in detail_assets, "priced BTC reward should appear in detail table"
        assert "OSBGT" in detail_assets, "zero-value OSBGT should appear in detail table"
        # Only the priced BTC row should appear (not the zero-value BTC).
        btc_rows_in_detail = [r for r in _section2_reward_detail_rows(ws) if str(r.get(2, "")) == "BTC"]
        assert all(float(r.get(3, -1)) != 0.0 for r in btc_rows_in_detail), (
            "zero-value BTC row leaked into detail in mixed scenario"
        )

        section_strs = _section2_strings(ws)
        assert any(s == "Dust summary:" for s in section_strs), "Dust summary header missing"
        btc_dust_present = any(
            re.search(r"BTC dust .*: 1 rows, summed Value EUR = 0\.00", s) for s in section_strs
        )
        assert btc_dust_present, "BTC dust line missing in mixed scenario"

    def test_all_dust_empty_label(self):
        """All taxable-now rows are dust: detail table shows the all-dust label and a dust block renders."""
        # Two BTC wallets each with a priced row, plus a zero-value row per asset,
        # so every taxable-now row is dust. The priced rows are classified
        # DEFERRED_BY_LAW so they stay in reward_entries as discriminator evidence
        # (proving BTC/ETH are priced assets) without entering taxable_now_entries
        # (which would make them non-dust real_rows and defeat the all-dust case).
        btc_priced = _make_reward_entry(
            asset="BTC",
            value_eur=Decimal("1"),
            wallet="Demo Spot",
            platform="Demo Spot",
            chain="Bitcoin",
            classification=RewardTaxClassification.DEFERRED_BY_LAW,
        )
        btc_zero = _make_reward_entry(
            asset="BTC", value_eur=Decimal("0"), wallet="Demo Spot", platform="Demo Spot", chain="Bitcoin"
        )
        eth_priced = _make_reward_entry(
            asset="ETH",
            value_eur=Decimal("2"),
            wallet="Demo Spot",
            platform="Demo Spot",
            chain="Ethereum",
            classification=RewardTaxClassification.DEFERRED_BY_LAW,
        )
        eth_zero = _make_reward_entry(
            asset="ETH", value_eur=Decimal("0"), wallet="Demo Spot", platform="Demo Spot", chain="Ethereum"
        )
        report = _make_crypto_tax_report(reward_entries=[btc_priced, btc_zero, eth_priced, eth_zero])
        wb = openpyxl.Workbook()
        write_crypto_supplementary_sheet(wb, report, build_koinly_jurisdiction())
        ws = wb["Crypto Supplementary"]

        section_strs = _section2_strings(ws)
        assert any(
            s == "All taxable-now rows classified as dust - see summary below" for s in section_strs
        ), f"all-dust empty label missing in {section_strs}"
        assert any(s == "Dust summary:" for s in section_strs), "dust summary header missing in all-dust case"

    def test_no_rewards_empty_label_unchanged(self):
        """Regression guard: with no taxable-now entries, Section 2 still shows 'No taxable-now rewards'."""
        deferred = _make_reward_entry(classification=RewardTaxClassification.DEFERRED_BY_LAW)
        report = _make_crypto_tax_report(reward_entries=[deferred])
        wb = openpyxl.Workbook()
        write_crypto_supplementary_sheet(wb, report, build_koinly_jurisdiction())
        ws = wb["Crypto Supplementary"]

        section_strs = _section2_strings(ws)
        assert any(s == "No taxable-now rewards" for s in section_strs), (
            f"'No taxable-now rewards' label missing in {section_strs}"
        )
        # And no dust summary block should render.
        assert not any(s == "Dust summary:" for s in section_strs), (
            "dust summary rendered when there are no taxable-now entries"
        )

    def test_dust_line_empty_wallet_renders_explicitly(self):
        """Empty-string wallet (reachable production degradation) renders as ``BTC dust ():`` with no 'None' literal."""
        btc_priced = _make_reward_entry(
            asset="BTC", value_eur=Decimal("0.50"), wallet="Demo Spot", platform="Demo Spot", chain="Bitcoin"
        )
        btc_zero = _make_reward_entry(
            asset="BTC", value_eur=Decimal("0"), wallet="", platform="Demo Spot", chain="Bitcoin"
        )
        report = _make_crypto_tax_report(reward_entries=[btc_priced, btc_zero])
        wb = openpyxl.Workbook()
        write_crypto_supplementary_sheet(wb, report, build_koinly_jurisdiction())
        ws = wb["Crypto Supplementary"]

        section_strs = _section2_strings(ws)
        empty_wallet_lines = [
            s for s in section_strs if s.startswith("BTC dust ()") and "1 rows, summed Value EUR = 0.00" in s
        ]
        assert empty_wallet_lines, (
            f"expected an explicit 'BTC dust (): ...' line, got {section_strs}"
        )
        # No 'None' literal may appear anywhere in the rendered Section 2 strings.
        assert not any("None" in s for s in section_strs), (
            f"'None' literal leaked into Section 2 output: {section_strs}"
        )

    def test_dust_sorted_by_asset_wallet(self):
        """Dust rows are sorted by (asset, wallet) ascending across multiple keys."""
        btc_priced = _make_reward_entry(
            asset="BTC", value_eur=Decimal("0.50"), wallet="Demo Spot", platform="Demo Spot", chain="Bitcoin"
        )
        btc_zero_demo = _make_reward_entry(
            asset="BTC", value_eur=Decimal("0"), wallet="Demo Spot", platform="Demo Spot", chain="Bitcoin"
        )
        btc_zero_wirex = _make_reward_entry(
            asset="BTC", value_eur=Decimal("0"), wallet="Wirex", platform="Wirex", chain="Bitcoin"
        )
        eth_priced = _make_reward_entry(
            asset="ETH", value_eur=Decimal("0.30"), wallet="Demo Spot", platform="Demo Spot", chain="Ethereum"
        )
        eth_zero_demo = _make_reward_entry(
            asset="ETH", value_eur=Decimal("0"), wallet="Demo Spot", platform="Demo Spot", chain="Ethereum"
        )
        report = _make_crypto_tax_report(
            reward_entries=[btc_priced, btc_zero_demo, btc_zero_wirex, eth_priced, eth_zero_demo]
        )
        wb = openpyxl.Workbook()
        write_crypto_supplementary_sheet(wb, report, build_koinly_jurisdiction())
        ws = wb["Crypto Supplementary"]

        section_strs = _section2_strings(ws)
        # Collect the dust summary lines (the lines after the "Dust summary:" header).
        try:
            header_idx = section_strs.index("Dust summary:")
        except ValueError as exc:  # pragma: no cover - RED until Task 4
            raise AssertionError(f"Dust summary header missing in {section_strs}") from exc
        dust_lines: list[str] = []
        for s in section_strs[header_idx + 1 :]:
            if s.startswith(("BTC dust", "ETH dust", "OSBGT dust", "BGT dust")):
                dust_lines.append(s)

        # Each (asset, wallet) group appears in the expected ascending order.
        # The expected order is (BTC, Demo Spot), (BTC, Wirex), (ETH, Demo Spot).
        expected_order = [
            ("BTC", "Demo Spot"),
            ("BTC", "Wirex"),
            ("ETH", "Demo Spot"),
        ]
        assert len(dust_lines) == len(expected_order), (
            f"expected {len(expected_order)} dust lines, got {dust_lines}"
        )
        for line, (asset, wallet) in zip(dust_lines, expected_order, strict=True):
            assert line.startswith(f"{asset} dust ({wallet}):"), (
                f"expected dust line to start with '{asset} dust ({wallet}):', got {line!r}"
            )


@pytest.mark.unit
class TestRewardDetailRowsContract:
    """Pins the ``_write_reward_detail_rows`` empty-label contract (r1 Advisory #11).

    The three-state empty-label logic in Task 4 depends on the helper rendering
    ``empty_label`` ONLY when ``entries`` is empty (guard at
    ``crypto_supplementary_sheet.py:66-68``). This test pins that contract so a
    future refactor that inverts the guard fails loudly rather than silently
    rendering a stray empty-label row in the mixed / all-real case.
    """

    def test_empty_label_only_rendered_when_entries_empty(self):
        from tax_reporting.application.persisting.crypto_supplementary_sheet import _write_reward_detail_rows

        entry = _make_reward_entry(asset="BTC", value_eur=Decimal("1"))
        wb = openpyxl.Workbook()
        ws = wb.create_sheet("probe")
        # Place the call at row 1; with non-empty entries and empty_label="" the
        # empty label must NOT render.
        next_row = _write_reward_detail_rows(ws, 1, [entry], empty_label="")
        for r in range(1, next_row):
            assert ws.cell(r, 1).value != "", (
                f"empty_label leaked into row {r} when entries is non-empty "
                f"(cell value={ws.cell(r, 1).value!r})"
            )


@pytest.mark.unit
class TestPartitionTaxableNow:
    """Direct unit test of the load-bearing r9 discriminator at the helper boundary.

    The helper ``_partition_taxable_now`` does not exist yet (Task 4 adds it).
    Per AGENTS.md rule 113 a committed RED test that is itself the deliverable
    must fail via ``pytest.fail(<message>)`` naming the resolving task, never an
    unhandled exception. We use a guarded import.
    """

    def test_priced_asset_zero_routes_to_dust(self):
        try:
            from tax_reporting.application.persisting.crypto_supplementary_sheet import _partition_taxable_now
        except ImportError:
            pytest.fail("Task 4 must add _partition_taxable_now helper")

        btc_zero = _make_reward_entry(
            asset="BTC", value_eur=Decimal("0"), wallet="Demo Spot", platform="Demo Spot", chain="Bitcoin"
        )
        btc_priced = _make_reward_entry(
            asset="BTC", value_eur=Decimal("0.50"), wallet="Demo Spot", platform="Demo Spot", chain="Bitcoin"
        )
        taxable_now_entries = [btc_zero]
        reward_entries = [btc_zero, btc_priced]
        real_rows, dust_rows = _partition_taxable_now(taxable_now_entries, reward_entries)
        assert real_rows == []
        assert dust_rows == [btc_zero]

    def test_unpriced_asset_zero_stays_in_real_rows(self):
        try:
            from tax_reporting.application.persisting.crypto_supplementary_sheet import _partition_taxable_now
        except ImportError:
            pytest.fail("Task 4 must add _partition_taxable_now helper")

        osbgt = _make_reward_entry(
            asset="OSBGT",
            value_eur=Decimal("0"),
            wallet="Demo Spot",
            platform="Demo Spot",
            chain="Berachain",
            review_required=True,
            review_reason="Unpriced wrapper token - manual pricing required",
        )
        taxable_now_entries = [osbgt]
        reward_entries = [osbgt]  # no non-zero OSBGT row anywhere in the export
        real_rows, dust_rows = _partition_taxable_now(taxable_now_entries, reward_entries)
        assert real_rows == [osbgt]
        assert dust_rows == []


@pytest.mark.unit
class TestWriteDustSummaryBlock:
    """Direct unit test of the extracted dust-block render helper.

    The helper ``_write_dust_summary_block`` does not exist yet (Task 4 adds it).
    Per AGENTS.md rule 113 the RED test fails via ``pytest.fail`` naming the
    resolving task through a guarded import.
    """

    def test_groups_by_asset_wallet_and_sorts(self):
        try:
            from tax_reporting.application.persisting.crypto_supplementary_sheet import _write_dust_summary_block
        except ImportError:
            pytest.fail("Task 4 must add _write_dust_summary_block helper")

        btc_demo_1 = _make_reward_entry(
            asset="BTC", value_eur=Decimal("0"), wallet="Demo Spot", platform="Demo Spot", chain="Bitcoin"
        )
        btc_demo_2 = _make_reward_entry(
            asset="BTC", value_eur=Decimal("0"), wallet="Demo Spot", platform="Demo Spot", chain="Bitcoin"
        )
        btc_wirex = _make_reward_entry(
            asset="BTC", value_eur=Decimal("0"), wallet="Wirex", platform="Wirex", chain="Bitcoin"
        )
        eth_demo = _make_reward_entry(
            asset="ETH", value_eur=Decimal("0"), wallet="Demo Spot", platform="Demo Spot", chain="Ethereum"
        )
        # Deliberately out of (asset, wallet) order to exercise the sort.
        dust_rows = [eth_demo, btc_wirex, btc_demo_1, btc_demo_2]

        wb = openpyxl.Workbook()
        ws = wb.create_sheet("dust")
        start_row = 1
        next_row = _write_dust_summary_block(ws, start_row, dust_rows)

        lines: list[str] = []
        for r in range(start_row, next_row):
            val = ws.cell(r, 1).value
            if isinstance(val, str):
                lines.append(val)

        assert lines[0] == "Dust summary:", f"header wrong: {lines[0]!r}"
        body = lines[1:]
        assert len(body) == 3, f"expected 3 summary lines, got {body!r}"

        # (BTC, Demo Spot) group sums two zero rows.
        assert re.match(
            r"BTC dust \(Demo Spot\): 2 rows, summed Value EUR = 0\.00", body[0]
        ), f"first line wrong: {body[0]!r}"
        # (BTC, Wirex) and (ETH, Demo Spot) each sum one zero row.
        assert re.match(
            r"BTC dust \(Wirex\): 1 rows, summed Value EUR = 0\.00", body[1]
        ), f"second line wrong: {body[1]!r}"
        assert re.match(
            r"ETH dust \(Demo Spot\): 1 rows, summed Value EUR = 0\.00", body[2]
        ), f"third line wrong: {body[2]!r}"
