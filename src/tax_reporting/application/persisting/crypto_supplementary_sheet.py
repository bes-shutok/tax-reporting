"""Crypto supplementary sheet writer for the Excel tax report.

This sheet contains audit and support data for crypto transactions, including:
- Income code reference
- Taxable-now reward detail (per-row trace data)
- Deferred-by-law reward detail
- Rewards classification reconciliation
- Review required entries (for zero-value popular tokens)

Aggregated taxable-now rewards are reported on the Reporting worksheet under
OTHER CAPITAL INVESTMENT INCOME, not in this sheet. This sheet provides
classification support detail and traceability for auditability only.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import openpyxl
from openpyxl.styles import Font

if TYPE_CHECKING:
    from ..crypto_reporting import CryptoTaxReport

from ..crypto_reporting import ZERO, RewardTaxClassification
from .excel_utils import apply_review_row_fill, auto_column_width, safe_cell_value
from .tax_constants import _INCOME_CODE_DESCRIPTIONS

_REWARD_ROW_NUM_COLS = 11
_REVIEW_ROW_NUM_COLS = 5


def write_crypto_supplementary_sheet(
    workbook: openpyxl.Workbook,
    crypto_tax_report: CryptoTaxReport,
) -> None:
    """Create and populate a 'Crypto Supplementary' worksheet with audit data.

    Writes:
    - Section 1: Income Codes reference
    - Section 2: Taxable-now support detail (per-row trace data)
    - Section 3: Deferred-by-law support detail
    - Section 4: Rewards classification reconciliation
    - Section 5: Review required (zero-value popular tokens, suspicious entries)

    This sheet is for auditability only. Aggregated taxable-now rewards are
    reported on the Reporting worksheet under OTHER CAPITAL INVESTMENT INCOME
    per SRG-008.

    Args:
        workbook: The Excel workbook to add the sheet to.
        crypto_tax_report: The crypto tax report data.
    """
    worksheet = workbook.create_sheet("Crypto Supplementary")

    taxable_now_entries = [
        e for e in crypto_tax_report.reward_entries if e.tax_classification == RewardTaxClassification.TAXABLE_NOW
    ]
    deferred_entries = [
        e for e in crypto_tax_report.reward_entries if e.tax_classification == RewardTaxClassification.DEFERRED_BY_LAW
    ]

    row_no = 1

    # 1. INCOME CODES REFERENCE
    worksheet.cell(row_no, 1, "1. INCOME CODES REFERENCE").font = Font(bold=True)
    row_no += 1

    reference_note = worksheet.cell(
        row_no,
        1,
        "Portuguese Tabela V income codes used for crypto reward income classification. "
        "See https://www.gov.pt (search 'Tabela V' in IRS withholding tax tables) for official source.",
    )
    reference_note.font = Font(italic=True, size=9)
    row_no += 1

    worksheet.cell(row_no, 1, "Country").font = Font(bold=True)
    worksheet.cell(row_no, 2, "Income Code").font = Font(bold=True)
    worksheet.cell(row_no, 3, "Description").font = Font(bold=True)
    row_no += 1

    for code, description in sorted(_INCOME_CODE_DESCRIPTIONS.items()):
        worksheet.cell(row_no, 1, "PT")
        worksheet.cell(row_no, 2, code)
        worksheet.cell(row_no, 3, description)
        row_no += 1

    # 2. TAXABLE-NOW SUPPORT DETAIL
    row_no += 1
    worksheet.cell(row_no, 1, "2. TAXABLE-NOW - SUPPORT DETAIL").font = Font(bold=True)
    row_no += 1

    taxable_note = worksheet.cell(
        row_no,
        1,
        "Individual taxable-now reward rows. Aggregated totals are reported on the Reporting worksheet "
        "under OTHER CAPITAL INVESTMENT INCOME. Use this section to trace each aggregated line back to "
        "its source Koinly rows for audit purposes.",
    )
    taxable_note.font = Font(italic=True, size=9)
    row_no += 1

    taxable_detail_headers = [
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
    for idx, header in enumerate(taxable_detail_headers, start=1):
        header_cell = worksheet.cell(row_no, idx, header)
        header_cell.font = Font(bold=True)
    row_no += 1

    if taxable_now_entries:
        for entry in taxable_now_entries:
            worksheet.cell(row_no, 1, entry.date)
            worksheet.cell(row_no, 2, safe_cell_value(entry.asset))
            worksheet.cell(row_no, 3, float(entry.value_eur))
            worksheet.cell(row_no, 4, safe_cell_value(entry.source_type))
            worksheet.cell(row_no, 5, safe_cell_value(entry.wallet))
            worksheet.cell(row_no, 6, safe_cell_value(entry.platform))
            worksheet.cell(row_no, 7, safe_cell_value(entry.chain))
            worksheet.cell(row_no, 8, safe_cell_value(entry.operator_origin.operator_country))
            worksheet.cell(row_no, 9, float(entry.foreign_tax_eur))
            review_cell = f"YES: {safe_cell_value(entry.review_reason)}" if entry.review_required else "NO"
            worksheet.cell(row_no, 10, review_cell)
            worksheet.cell(row_no, 11, safe_cell_value(entry.description))
            if entry.review_required:
                apply_review_row_fill(worksheet, row_no, 1, _REWARD_ROW_NUM_COLS)
            row_no += 1
    else:
        worksheet.cell(row_no, 1, "No taxable-now rewards")
        row_no += 1

    # 3. DEFERRED BY LAW SUPPORT DETAIL
    row_no += 1
    worksheet.cell(row_no, 1, "3. DEFERRED BY LAW - SUPPORT DETAIL").font = Font(bold=True)
    row_no += 1

    deferred_note = worksheet.cell(
        row_no,
        1,
        "These rewards are crypto-denominated and taxation is deferred until disposal per CIRS art. 5(11). "
        "They are shown here for auditability but not included in immediate filing rows.",
    )
    deferred_note.font = Font(italic=True, size=9)
    row_no += 1

    deferred_headers = [
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
    for idx, header in enumerate(deferred_headers, start=1):
        header_cell = worksheet.cell(row_no, idx, header)
        header_cell.font = Font(bold=True)
    row_no += 1

    if deferred_entries:
        for entry in deferred_entries:
            worksheet.cell(row_no, 1, entry.date)
            worksheet.cell(row_no, 2, safe_cell_value(entry.asset))
            worksheet.cell(row_no, 3, float(entry.value_eur))
            worksheet.cell(row_no, 4, safe_cell_value(entry.source_type))
            worksheet.cell(row_no, 5, safe_cell_value(entry.wallet))
            worksheet.cell(row_no, 6, safe_cell_value(entry.platform))
            worksheet.cell(row_no, 7, safe_cell_value(entry.chain))
            worksheet.cell(row_no, 8, safe_cell_value(entry.operator_origin.operator_country))
            worksheet.cell(row_no, 9, float(entry.foreign_tax_eur))
            review_cell = f"YES: {safe_cell_value(entry.review_reason)}" if entry.review_required else "NO"
            worksheet.cell(row_no, 10, review_cell)
            worksheet.cell(row_no, 11, safe_cell_value(entry.description))
            if entry.review_required:
                apply_review_row_fill(worksheet, row_no, 1, _REWARD_ROW_NUM_COLS)
            row_no += 1
    else:
        worksheet.cell(row_no, 1, "No deferred rewards")
        row_no += 1

    # 4. REWARDS CLASSIFICATION RECONCILIATION
    row_no += 1
    worksheet.cell(row_no, 1, "4. REWARDS CLASSIFICATION RECONCILIATION").font = Font(bold=True)
    row_no += 1

    taxable_now_total_eur = sum((e.value_eur for e in taxable_now_entries), start=ZERO)
    deferred_total_eur = sum((e.value_eur for e in deferred_entries), start=ZERO)

    reconciliation_rewards_rows = [
        ("Total reward rows (raw)", len(crypto_tax_report.reward_entries)),
        ("Taxable-now rows (immediately taxable)", len(taxable_now_entries)),
        ("Deferred-by-law rows (taxation deferred)", len(deferred_entries)),
        ("Taxable-now total value (EUR)", float(taxable_now_total_eur)),
        ("Deferred total value (EUR)", float(deferred_total_eur)),
    ]

    for key, value in reconciliation_rewards_rows:
        worksheet.cell(row_no, 1, key)
        worksheet.cell(row_no, 2, value)
        row_no += 1

    # 5. REVIEW REQUIRED
    row_no += 1
    worksheet.cell(row_no, 1, "5. REVIEW REQUIRED").font = Font(bold=True)
    row_no += 1

    review_note = worksheet.cell(
        row_no,
        1,
        "Entries requiring manual review. These are excluded from the main report to avoid clutter. "
        "Review each item and verify the underlying Koinly data before including in your tax filing.",
    )
    review_note.font = Font(italic=True, size=9)
    row_no += 1

    review_headers = ["Source", "Date", "Asset", "Platform", "Review reason"]
    for idx, header in enumerate(review_headers, start=1):
        header_cell = worksheet.cell(row_no, idx, header)
        header_cell.font = Font(bold=True)
    row_no += 1

    if crypto_tax_report.review_entries:
        for entry in crypto_tax_report.review_entries:
            source_label = "Capital Gains" if entry.source_section == "capital_gains" else "Income"
            worksheet.cell(row_no, 1, source_label)
            worksheet.cell(row_no, 2, entry.date)
            asset_cell = worksheet.cell(row_no, 3, safe_cell_value(entry.asset))
            worksheet.cell(row_no, 4, safe_cell_value(entry.platform))
            worksheet.cell(row_no, 5, entry.review_reason)
            if entry.is_suspicious:
                asset_cell.font = Font(color="FF0000", bold=True)
            row_no += 1
    else:
        worksheet.cell(row_no, 1, "No review items")
        row_no += 1

    auto_column_width(worksheet)
