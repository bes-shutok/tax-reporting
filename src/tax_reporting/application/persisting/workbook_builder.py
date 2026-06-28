"""Workbook builder orchestrator for the Excel tax report."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

import openpyxl

if TYPE_CHECKING:
    from os import PathLike

    from ..crypto_reporting import AggregatedRewardIncomeEntry, CryptoTaxReport

from ...domain.collections import (
    CapitalGainLinesPerCompany,
    DividendIncomePerCompany,
)
from ...domain.exceptions import ConfigurationError, ReportGenerationError
from ...infrastructure.config import Config, load_configuration_from_file
from ...infrastructure.logging_config import create_module_logger
from ..crypto.aggregation import aggregate_taxable_rewards
from .assumptions_sheet import write_assumptions_and_methodology_sheet
from .crypto_gains_sheet import write_crypto_gains_sheet
from .crypto_reconciliation_sheet import write_crypto_reconciliation_sheet
from .crypto_supplementary_sheet import write_crypto_supplementary_sheet
from .derivatives_sheet import write_derivatives_sheet
from .ib_sheet import write_ib_reporting_sheet
from .loan_activity_sheet import write_loan_activity_sheet


@contextmanager
def _workbook_lifecycle():
    """Context manager for workbook lifecycle with guaranteed cleanup.

    Yields a (workbook, worksheet, close_callback) tuple where:
    - workbook: The openpyxl Workbook object
    - worksheet: The active worksheet (titled "Reporting")
    - close_callback: Function to call when workbook should be closed (handles errors)

    The workbook is automatically closed on exit via the close_callback if not already closed.
    This ensures cleanup even if an exception propagates through context manager boundaries.

    Example:
        with _workbook_lifecycle() as (workbook, worksheet, close):
            # ... use workbook ...
            close()  # Explicit close before success path
        # Workbook already closed if close() was called, or closed automatically on exit
    """
    logger = create_module_logger(__name__)
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    if worksheet is None:
        raise ReportGenerationError("Failed to create worksheet in workbook")
    worksheet.title = "Reporting"

    closed = False

    def close_on_success() -> None:
        """Close the workbook on the success path.

        This should be called explicitly after workbook.save() succeeds.
        Idempotent - safe to call multiple times.
        """
        nonlocal closed
        if not closed:
            workbook.close()
            closed = True

    def close_on_failure() -> None:
        """Close the workbook on the failure path.

        Logs errors during close but does not raise - the original exception
        should propagate.

        Idempotent - safe to call multiple times.
        """
        nonlocal closed
        if not closed:
            try:
                workbook.close()
            except Exception as close_error:
                logger.error("Error closing workbook after failure: %s", close_error)
            closed = True

    try:
        yield workbook, worksheet, close_on_success
    except Exception:
        close_on_failure()
        raise
    finally:
        close_on_success()



def generate_tax_report(  # noqa: PLR0912, PLR0915
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

    # Load configuration before workbook lifecycle - config errors should fail fast
    try:
        config: Config = load_configuration_from_file()
    except ConfigurationError:
        raise
    except Exception as e:
        raise ReportGenerationError(f"Failed to read configuration for currency exchange: {e}") from e

    aggregated_rewards: list[AggregatedRewardIncomeEntry] | None = None
    crypto_sheet_created = False

    with _workbook_lifecycle() as (workbook, worksheet, close_workbook):
        if crypto_tax_report:
            logger.info(
                "Adding Crypto worksheets with %s capital and %s reward rows",
                len(crypto_tax_report.capital_entries),
                len(crypto_tax_report.reward_entries),
            )
            aggregated_rewards = aggregate_taxable_rewards(
                crypto_tax_report.reward_entries,
                config.tax_jurisdiction.country,
            )

        write_ib_reporting_sheet(
            worksheet,
            config,
            capital_gain_lines_per_company,
            dividend_income_per_company,
            other_capital_income_entries=aggregated_rewards,
        )

        if crypto_tax_report:
            try:
                write_crypto_gains_sheet(workbook, crypto_tax_report)
                if config.tax_jurisdiction.separate_derivatives_reporting:
                    write_derivatives_sheet(workbook, crypto_tax_report, config.tax_jurisdiction)
                write_crypto_supplementary_sheet(workbook, crypto_tax_report, config.tax_jurisdiction)
                write_crypto_reconciliation_sheet(workbook, crypto_tax_report)
                write_loan_activity_sheet(workbook, crypto_tax_report)
                write_assumptions_and_methodology_sheet(
                    workbook,
                    capital_entries=crypto_tax_report.capital_entries,
                    reward_entries=crypto_tax_report.reward_entries,
                )
                crypto_sheet_created = True
            except Exception as e:
                logger.error("Failed to generate crypto sheets: %s", e)
                for name in (
                    "Crypto Gains",
                    "Derivatives P&L",
                    "Crypto Supplementary",
                    "Crypto Reconciliation",
                    "Loan Activity",
                    "Assumptions & Methodology",
                ):
                    if name in workbook.sheetnames:
                        workbook.remove(workbook[name])
                raise

        temp_path: Path | None = None
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
            if temp_path is not None and temp_path.exists():
                try:
                    temp_path.unlink()
                except Exception:
                    logger.warning("Failed to clean up temporary file: %s", temp_path)
            raise ReportGenerationError(f"Failed to save Excel report: {e}") from e

        # Explicitly close workbook on success path after save completes
        close_workbook()

    return crypto_sheet_created
