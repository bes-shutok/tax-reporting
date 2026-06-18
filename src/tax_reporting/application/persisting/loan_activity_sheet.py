"""Loan Activity sheet writer for the Excel tax report."""

from __future__ import annotations

from typing import TYPE_CHECKING

import openpyxl
from openpyxl.styles import PatternFill

if TYPE_CHECKING:
    from ..crypto_reporting import CryptoTaxReport

from ...domain.constants import LOAN_STATUS_OVERPAID
from .excel_utils import auto_column_width, safe_cell_value


def write_loan_activity_sheet(workbook: openpyxl.Workbook, crypto_tax_report: CryptoTaxReport) -> None:
    """Create and populate a 'Loan Activity' worksheet with per-asset loan summaries.

    Shows all loan receipts and repayments found in the Koinly transaction history
    regardless of filing year; the tab reflects all-history balances so that
    cross-year loan repayments are visible. Rows where the repaid amount exceeds
    the received amount (overpaid balance) are highlighted with a light-red fill
    to flag potential cross-year repayment scenarios for manual review.

    Args:
        workbook: The Excel workbook to add the sheet to.
        crypto_tax_report: The full crypto tax report; only its loan_activity field
            is used. Each LoanActivityEntry supplies per-asset received/repaid counts,
            amounts, EUR values, and a balance status string.
    """
    _header_row = 3
    _data_start_row = 4

    worksheet = workbook.create_sheet("Loan Activity")

    # Row 1: visible note so the reviewer understands balances are all-history.
    # This is intentional: cross-year loan repayments must be visible so the reviewer
    # can verify the outstanding balance. "Overpaid" flags repaid > received (likely a
    # prior-year loan being fully repaid in the filing year).
    note_cell = worksheet.cell(
        1,
        1,
        "Note: balances shown across ALL years in Transaction History, not filtered to the filing year.",
    )
    note_cell.font = openpyxl.styles.Font(italic=True)

    headers = [
        "Asset",
        "Received Count",
        "Received Amount",
        "Received Value (EUR)",
        "Repaid Count",
        "Repaid Amount",
        "Repaid Value (EUR)",
        "Balance Amount",
        "Balance Status",
    ]
    for idx, header in enumerate(headers, start=1):
        worksheet.cell(_header_row, idx, header)

    red_fill = PatternFill(start_color="FFFFCCCC", end_color="FFFFCCCC", fill_type="solid")

    for row_offset, entry in enumerate(crypto_tax_report.loan_activity, start=_data_start_row):
        worksheet.cell(row_offset, 1, safe_cell_value(entry.asset))
        worksheet.cell(row_offset, 2, entry.received_count)
        worksheet.cell(row_offset, 3, entry.received_amount)
        worksheet.cell(row_offset, 4, entry.received_value_eur)
        worksheet.cell(row_offset, 5, entry.repaid_count)
        worksheet.cell(row_offset, 6, entry.repaid_amount)
        worksheet.cell(row_offset, 7, entry.repaid_value_eur)
        worksheet.cell(row_offset, 8, entry.balance_amount)
        worksheet.cell(row_offset, 9, entry.balance_status)

        if entry.balance_status == LOAN_STATUS_OVERPAID:
            for col_idx in range(1, 10):
                worksheet.cell(row_offset, col_idx).fill = red_fill

    section_start = _data_start_row + len(crypto_tax_report.loan_activity) + 2
    scope_label_cell = worksheet.cell(section_start, 1, "FIFO Rebuild Scope")
    scope_label_cell.font = openpyxl.styles.Font(bold=True)
    note_text = (
        "Assets rebuilt from Transaction History instead of Koinly CG export "
        "(loan-affected under CIRS art. 10(20))"
    )
    worksheet.cell(section_start, 2, note_text).font = openpyxl.styles.Font(italic=True)
    if crypto_tax_report.fifo_rebuild_assets:
        for row_offset, asset in enumerate(sorted(crypto_tax_report.fifo_rebuild_assets), start=section_start + 1):
            worksheet.cell(row_offset, 1, asset)
            worksheet.cell(row_offset, 2, "Rebuilt from Transaction History")
    else:
        worksheet.cell(section_start + 1, 1, "None").font = openpyxl.styles.Font(italic=True)
        worksheet.cell(section_start + 1, 2, "FIFO rebuild not active or no loan-affected assets discovered")

    auto_column_width(worksheet)
