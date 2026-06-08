"""Assumptions & Methodology sheet writer for platform-level verification notes.

This sheet provides:
1. A complete manifest of every platform seen in the tax report, showing operator
   entity, country, confidence level, any verification assumption, and whether
   the platform requires manual review before filing.
2. Methodology assumptions documenting the legal basis and rationale for reporting
   decisions (aggregation approach, FIFO methodology, holding period classification,
   materiality threshold, data sources).

Platforms with platform_review_required=True are highlighted in red and sorted
to the top so they are immediately visible.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import openpyxl

if TYPE_CHECKING:
    from ..crypto_reporting import CryptoCapitalGainEntry, CryptoRewardIncomeEntry

from .excel_utils import REVIEW_ROW_FILL, auto_column_width, safe_cell_value


@dataclass
class _PlatformSummary:
    """Aggregated per-platform data for the Assumptions & Methodology sheet."""

    platform: str
    operator_entity: str
    operator_country: str
    confidence: str
    platform_review_required: bool
    assumption: str | None
    transaction_count: int


def _collect_platform_summaries(
    capital_entries: list[CryptoCapitalGainEntry] | None = None,
    reward_entries: list[CryptoRewardIncomeEntry] | None = None,
) -> list[_PlatformSummary]:
    """Collect one summary row per unique platform seen in the data.

    Aggregates counts and unions review flags across all entries for the same platform.
    If any entry for a platform has platform_review_required=True, the summary row
    is marked as requiring review.
    """
    summaries: dict[tuple[str, str], _PlatformSummary] = {}

    def _accumulate(entry: CryptoCapitalGainEntry | CryptoRewardIncomeEntry) -> None:
        origin = entry.operator_origin
        key = (origin.platform, origin.operator_entity)
        if key in summaries:
            s = summaries[key]
            s.transaction_count += 1
            if origin.platform_review_required:
                s.platform_review_required = True
            if origin.platform_assumption and not s.assumption:
                s.assumption = origin.platform_assumption
        else:
            summaries[key] = _PlatformSummary(
                platform=origin.platform,
                operator_entity=origin.operator_entity,
                operator_country=origin.operator_country,
                confidence=origin.confidence,
                platform_review_required=origin.platform_review_required,
                assumption=origin.platform_assumption,
                transaction_count=1,
            )

    for entry in capital_entries or []:
        _accumulate(entry)
    for entry in reward_entries or []:
        _accumulate(entry)

    return list(summaries.values())


def write_assumptions_and_methodology_sheet(
    workbook: openpyxl.Workbook,
    capital_entries: list[CryptoCapitalGainEntry] | None = None,
    reward_entries: list[CryptoRewardIncomeEntry] | None = None,
) -> None:
    """Create and populate an 'Assumptions & Methodology' worksheet.

    Contains two sections:
    1. Platform Assumptions — complete manifest of platforms with operator metadata
    2. Methodology Assumptions — legal basis and rationale for reporting decisions

    Args:
        workbook: The Excel workbook to add the sheet to.
        capital_entries: Capital gain entries used to discover platform metadata.
            Each entry's operator_origin is inspected for platform name, entity,
            country, confidence, and review flags.
        reward_entries: Reward income entries used to discover platform metadata.
            Combined with capital_entries to build the complete platform manifest.
    """
    summaries = _collect_platform_summaries(capital_entries, reward_entries)

    worksheet = workbook.create_sheet("Assumptions & Methodology")
    row_no = 1

    # Title
    worksheet.cell(row_no, 1, "Assumptions & Methodology")
    worksheet.cell(row_no, 1).font = openpyxl.styles.Font(bold=True, size=14)
    row_no += 2

    # Description
    description = (
        "Complete manifest of all platforms in this report. "
        "Red rows (Review Required = YES) must be resolved before submitting the tax return. "
        "Informational assumptions are shown in the last column for all platforms."
    )
    worksheet.cell(row_no, 1, description)
    worksheet.cell(row_no, 1).font = openpyxl.styles.Font(italic=True, size=10)
    row_no += 2

    if not summaries:
        worksheet.cell(row_no, 1, "No platform data found.")
        auto_column_width(worksheet)
        return

    # Headers for Platform Assumptions section
    headers = [
        "Platform",
        "Operator Entity",
        "Country",
        "Confidence",
        "Review Required",
        "Assumption / Verification Note",
        "Transaction Count",
    ]
    for col_idx, header in enumerate(headers, 1):
        cell = worksheet.cell(row_no, col_idx, header)
        cell.font = openpyxl.styles.Font(bold=True)
    row_no += 1

    # Sort: review-required first, then alphabetical by platform name
    sorted_summaries = sorted(summaries, key=lambda s: (not s.platform_review_required, s.platform.lower()))

    for s in sorted_summaries:
        worksheet.cell(row_no, 1, safe_cell_value(s.platform))
        worksheet.cell(row_no, 2, safe_cell_value(s.operator_entity))
        worksheet.cell(row_no, 3, safe_cell_value(s.operator_country))
        worksheet.cell(row_no, 4, safe_cell_value(s.confidence))
        worksheet.cell(row_no, 5, "YES" if s.platform_review_required else "NO")
        worksheet.cell(row_no, 6, safe_cell_value(s.assumption or ""))
        worksheet.cell(row_no, 7, s.transaction_count)
        if s.platform_review_required:
            for col_idx in range(1, 8):
                worksheet.cell(row_no, col_idx).fill = REVIEW_ROW_FILL  # type: ignore[assignment]
        row_no += 1

    # After platform data section, add methodology section
    row_no += 2
    worksheet.cell(row_no, 1, "Methodology Assumptions")
    worksheet.cell(row_no, 1).font = openpyxl.styles.Font(bold=True, size=12)
    row_no += 2

    methodology_items = [
        (
            "Aggregation Approach",
            "FIFO lots from the same sale event are aggregated into one line. "
            "Legal basis: Quadro 9.4 (Anexo J) has one 'Data de aquisição' field per line. "
            "Multiple FIFO lots matched to the same sale event can reasonably be reported "
            "as one aggregated line (PT-C-025). Multi-lot sales show full acquisition date "
            "detail in the Notes column ('Acquired: date1, date2 (N lots)') and are "
            "highlighted with blue fill for easy identification. "
            "See PT-C-025 and PT-C-027 in docs/domain/crypto_rules.md.",
        ),
        (
            "FIFO Methodology",
            "First-In-First-Out is mandatory per CIRS art. 43 n.6 al.g. "
            "Applied per wallet/exchange independently per CIRS art. 43 n.7. "
            "See PT-C-008 and PT-C-009 in docs/domain/crypto_rules.md.",
        ),
        (
            "Holding Period Classification",
            "Short-term (<365 days) = taxable, Long-term (≥365 days) = exempt. "
            "Calendar-year arithmetic used (2024-02-29 + 365 days = 2025-03-01, not 2025-02-28). "
            "See PT-C-011 in docs/domain/crypto_rules.md.",
        ),
        (
            "Materiality Threshold",
            "Lines where |gain/loss| < 1 EUR are excluded from the report. "
            "These have no material tax impact and reduce manual filing burden. "
            "See PT-C-028 in docs/domain/crypto_rules.md.",
        ),
        (
            "Data Sources",
            "Interactive Brokers (dividends, capital gains), Koinly (crypto), "
            "config.ini (exchange rates). See README.md for data requirements.",
        ),
    ]

    for label, description in methodology_items:
        worksheet.cell(row_no, 1, label)
        worksheet.cell(row_no, 1).font = openpyxl.styles.Font(bold=True)
        worksheet.cell(row_no, 2, description)
        row_no += 1

    auto_column_width(worksheet)
