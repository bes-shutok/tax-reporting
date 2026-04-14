"""Workbook builder orchestrator for the Excel tax report."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import openpyxl

if TYPE_CHECKING:
    from os import PathLike

    from ..crypto_reporting import CryptoTaxReport

from ...domain.collections import (
    CapitalGainLinesPerCompany,
    DividendIncomePerCompany,
)
from ...domain.exceptions import ReportGenerationError
from ...infrastructure.config import Config, load_configuration_from_file
from ...infrastructure.logging_config import create_module_logger
from ..crypto_reporting import aggregate_taxable_rewards
from .crypto_gains_sheet import write_crypto_gains_sheet
from .crypto_reconciliation_sheet import write_crypto_reconciliation_sheet
from .crypto_rewards_sheet import write_crypto_rewards_sheet
from .ib_sheet import write_ib_reporting_sheet


def generate_tax_report(  # noqa: PLR0915
    extract: str | PathLike[str],
    capital_gain_lines_per_company: CapitalGainLinesPerCompany,
    dividend_income_per_company: DividendIncomePerCompany | None = None,
    crypto_tax_report: CryptoTaxReport | None = None,
) -> bool:
    """Generate comprehensive Excel tax report with capital gains and dividend income.

    This function creates a professional Excel report containing all tax-relevant
    information for capital gains and dividend income reporting, including currency
    exchange rate tables and proper formatting for submission to tax authorities.

    Args:
        extract: Output file path for the Excel tax report
        capital_gain_lines_per_company: Calculated capital gains grouped by company
        dividend_income_per_company: Dividend income data grouped by company (optional)
        crypto_tax_report: Crypto tax data parsed from Koinly exports (optional)

    Returns:
        True if the Crypto sheets were successfully created, False when
        crypto_tax_report is None. Failures during crypto rendering raise
        an exception rather than returning False.
    """
    logger = create_module_logger(__name__)
    logger.info("Generating capital gains report: %s", Path(extract).name)

    total_gain_lines = sum(len(lines) for lines in capital_gain_lines_per_company.values())
    logger.debug(
        "Processing %s capital gain lines across %s companies",
        total_gain_lines,
        len(capital_gain_lines_per_company),
    )

    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    if worksheet is None:
        raise ReportGenerationError("Failed to create worksheet in workbook")
    worksheet.title = "Reporting"

    try:
        config: Config = load_configuration_from_file()
    except Exception as e:
        raise ReportGenerationError(f"Failed to read configuration for currency exchange: {e}") from e

    write_ib_reporting_sheet(worksheet, config, capital_gain_lines_per_company, dividend_income_per_company)

    crypto_sheet_created = False
    workbook_closed = False
    if crypto_tax_report:
        logger.info(
            "Adding Crypto worksheets with %s capital and %s reward rows",
            len(crypto_tax_report.capital_entries),
            len(crypto_tax_report.reward_entries),
        )
        try:
            aggregated_rewards = aggregate_taxable_rewards(crypto_tax_report.reward_entries)
            write_crypto_gains_sheet(workbook, crypto_tax_report)
            write_crypto_rewards_sheet(workbook, crypto_tax_report, aggregated_rewards)
            write_crypto_reconciliation_sheet(workbook, crypto_tax_report)
            crypto_sheet_created = True
        except Exception as e:
            logger.error("Failed to generate crypto sheets: %s", e)
            for name in ("Crypto Gains", "Crypto Rewards", "Crypto Reconciliation"):
                if name in workbook.sheetnames:
                    workbook.remove(workbook[name])
            try:
                workbook.close()
            except Exception as close_error:
                logger.error("Error closing workbook after crypto sheet failure: %s", close_error)
            workbook_closed = True
            raise

    try:
        # Write to temporary file first, then atomic replace overwrites target
        extract_path = Path(extract)
        temp_path = extract_path.with_suffix(extract_path.suffix + ".tmp")
        workbook.save(temp_path)

        # Atomic replace: on POSIX this overwrites atomically without explicit removal
        temp_path.replace(extract)

        report_type = "capital gains and dividend income" if dividend_income_per_company else "capital gains"
        logger.info("Successfully generated %s report with %s capital gain lines", report_type, total_gain_lines)
    except Exception as e:
        # Clean up temp file on failure
        if temp_path.exists():
            try:
                temp_path.unlink()
            except Exception:
                logger.warning("Failed to clean up temporary file: %s", temp_path)
        raise ReportGenerationError(f"Failed to save Excel report: {e}") from e
    finally:
        if not workbook_closed:
            workbook.close()

    return crypto_sheet_created
