"""Derivatives P&L Excel sheet for financial derivatives (CIRS art. 10(1)(e))."""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import TYPE_CHECKING

import openpyxl
from openpyxl.styles import Font, PatternFill

if TYPE_CHECKING:
    from ..crypto_reporting import CryptoTaxReport

from .excel_utils import auto_column_width, safe_cell_value

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
_EMPTY_STATE_MESSAGE = "No derivatives activity for this jurisdiction"
_LOSS_FOOTNOTE = "Losses are deductible against other Category G gains; carry-forward 5 years per PT-C-016"
_TOTAL_LABEL = "Total"
_NUM_COLUMNS = len(_COLUMN_HEADERS)
# Detail line shown above the column headers when the sheet has at least one row.
# The three fields are constants for derivatives today (annex routing never branches
# because derivatives have no 365-day exemption; Código G51 is the closed-enum value
# for all instrumentos financeiros derivados; legal basis is always art. 10(1)(e)).
# Render them once on a detail line rather than as repeating columns.
_DETAIL_LINE_TEMPLATE = "Annex: {annex_hint} | Código: {operation_code} | Legal basis: {legal_category}"

# Red fill for review rows (matches crypto_gains_sheet convention)
_REVIEW_FILL = PatternFill(start_color="FFFF0000", end_color="FFFF0000", fill_type="solid")


def write_derivatives_sheet(workbook: openpyxl.Workbook, crypto_tax_report: CryptoTaxReport) -> None:
    """Create and populate the 'Derivatives P&L' worksheet.

    Renders a single-tab P&L summary for derivatives realizations taxed under
    CIRS art. 10(1)(e). Each aggregated entry maps to one row; the totals row
    shows the net P&L; a loss-deductibility footnote appears whenever at least
    one entry is a loss.

    A detail line above the column headers records the annex routing, AT operation
    code, and legal basis. These are constants across all derivatives rows today,
    so they appear once on the detail line rather than as repeating columns.

    The sheet is always rendered, even when derivatives_entries is empty (per
    development_lessons.md #93): the headers and an explicit empty-state row are
    written so the reviewer can see the category was considered.

    Args:
        workbook: The Excel workbook to add the sheet to.
        crypto_tax_report: The crypto tax report; only derivatives_entries is used.
    """
    worksheet = workbook.create_sheet(_SHEET_NAME)

    title_cell = worksheet.cell(1, 1, _HEADER_TITLE)
    title_cell.font = Font(bold=True)

    entries = crypto_tax_report.derivatives_entries

    if entries:
        first = entries[0]
        # Design Invariant 4 of the 2026-06-15 derivatives P&L columns plan holds that
        # (annex_hint, operation_code, legal_category) are constants across all rows
        # today, so the detail line reads them from entries[0]. Surface heterogeneity
        # loudly (e.g. if a future change introduces G52/G53/G54 per-row routing) so the
        # wrong detail line is never rendered silently. See development_lessons.md #77.
        distinct_constant_tuples = {(e.annex_hint, e.operation_code, e.legal_category) for e in entries}
        if len(distinct_constant_tuples) > 1:
            logging.getLogger(__name__).warning(
                "Derivatives P&L detail-line fields are heterogeneous across entries: "
                "%d distinct (annex_hint, operation_code, legal_category) tuples %s; "
                "rendering detail line from entries[0] = annex=%s code=%s legal=%s",
                len(distinct_constant_tuples),
                sorted(distinct_constant_tuples),
                first.annex_hint,
                first.operation_code,
                first.legal_category,
            )
        detail_cell = worksheet.cell(
            2,
            1,
            safe_cell_value(
                _DETAIL_LINE_TEMPLATE.format(
                    annex_hint=first.annex_hint,
                    operation_code=first.operation_code,
                    legal_category=first.legal_category,
                )
            ),
        )
        detail_cell.font = Font(italic=True)

    header_row = 3
    for idx, header in enumerate(_COLUMN_HEADERS, start=1):
        header_cell = worksheet.cell(header_row, idx, header)
        header_cell.font = Font(bold=True)

    current_row = header_row + 1

    if not entries:
        empty_cell = worksheet.cell(current_row, 1, _EMPTY_STATE_MESSAGE)
        empty_cell.font = Font(italic=True)
        auto_column_width(worksheet)
        return

    for entry in entries:
        worksheet.cell(current_row, 1, safe_cell_value(entry.date))
        worksheet.cell(current_row, 2, safe_cell_value(entry.asset))
        worksheet.cell(current_row, 3, safe_cell_value(entry.platform))
        worksheet.cell(current_row, 4, entry.event_type.value)
        worksheet.cell(current_row, 5, entry.pnl_eur)
        worksheet.cell(current_row, 6, safe_cell_value(entry.operator_entity))
        worksheet.cell(current_row, 7, safe_cell_value(entry.operator_country))
        worksheet.cell(current_row, 8, entry.event_count)
        worksheet.cell(current_row, 9, safe_cell_value(entry.notes))
        review_display = (
            f"YES: {entry.review_reason}" if entry.review_required and entry.review_reason else
            "YES: (no reason propagated)" if entry.review_required else "NO"
        )
        worksheet.cell(current_row, 10, review_display)

        if entry.review_required:
            for col_idx in range(1, _NUM_COLUMNS + 1):
                worksheet.cell(current_row, col_idx).fill = _REVIEW_FILL

        current_row += 1

    current_row += 1
    total_label_cell = worksheet.cell(current_row, 1, _TOTAL_LABEL)
    total_label_cell.font = Font(bold=True)
    net_pnl = _sum_pnl_eur(entries)
    total_cell = worksheet.cell(current_row, 5, net_pnl)
    total_cell.font = Font(bold=True)

    if any(entry.pnl_eur < 0 for entry in entries):
        current_row += 1
        footnote_cell = worksheet.cell(current_row, 1, _LOSS_FOOTNOTE)
        footnote_cell.font = Font(italic=True)

    auto_column_width(worksheet)


def _sum_pnl_eur(entries: list) -> Decimal:  # type: ignore[type-arg]
    """Sum the pnl_eur field across entries.

    Args:
        entries: Iterable of DerivativesPnLEntry objects.

    Returns:
        Decimal total of pnl_eur across all entries.
    """
    return sum((entry.pnl_eur for entry in entries), start=Decimal("0"))
