"""Main entry point for the shares reporting application.

Processes Interactive Brokers CSV exports to generate tax reporting data for capital gains calculations.
"""

from __future__ import annotations

import logging
import re
import sys
from pathlib import Path

from .application.crypto_reporting import CryptoTaxReport, load_koinly_crypto_report
from .application.extraction import parse_ib_export_all
from .application.persisting import export_rollover_file, generate_tax_report
from .application.transformation import calculate_fifo_gains
from .domain.collections import (
    CapitalGainLinesPerCompany,
    DividendIncomePerCompany,
    IBExportData,
    TradeCyclePerCompany,
)
from .domain.exceptions import FileProcessingError, ReportGenerationError, SharesReportingError
from .infrastructure.logging_config import configure_application_logging, create_module_logger
from .infrastructure.validation import validate_output_directory


def main(  # noqa: PLR0912, PLR0915
    source_file: Path | None = None, output_dir: Path | None = None, log_level: str = "INFO"
) -> None:
    """Main application entry point.

    Args:
        source_file: Path to the source IB export CSV file
        output_dir: Directory for output files
        log_level: Logging level
    """
    # Set up logging
    log_file = Path("logs", "shares-reporting.log") if output_dir else None
    configure_application_logging(level=log_level, log_file=log_file)
    logger = create_module_logger(__name__)

    try:
        final_report_type = "capital gains"
        # Default paths
        if source_file is None:
            source_file = Path("resources/source", "ib_export.csv")

        if output_dir is None:
            output_dir = Path("resources/result")

        extract_path = output_dir / "extract.xlsx"
        leftover_path = output_dir / "shares-leftover.csv"

        logger.info("Starting shares reporting application")
        logger.info("Source file: %s", source_file)
        logger.info("Output directory: %s", output_dir)

        # Validate input file path
        try:
            validated_source = Path(source_file)
            if not validated_source.exists():
                raise FileNotFoundError(f"Source file not found: {validated_source}")
            if not validated_source.is_file():
                raise FileProcessingError(f"Source path is not a file: {validated_source}")
        except Exception as e:
            raise FileProcessingError(f"Invalid source file: {e}") from e

        # Validate output directory
        try:
            validated_output_dir = validate_output_directory(output_dir)
        except Exception as e:
            raise ReportGenerationError(f"Invalid output directory: {e}") from e

        # Update paths with validated paths
        extract_path = validated_output_dir / "extract.xlsx"
        leftover_path = validated_output_dir / "shares-leftover.csv"

        logger.info("Processing file: %s", validated_source.name)
        logger.info("Output files will be: %s and %s", extract_path.name, leftover_path.name)

        # Extract comprehensive data from IB export
        try:
            ib_data: IBExportData = parse_ib_export_all(validated_source)
            trade_lines_per_company: TradeCyclePerCompany = ib_data.trade_cycles
            dividend_income_per_company: DividendIncomePerCompany = ib_data.dividend_income
            logger.info(
                "Parsed %d trade cycles and %d dividend entries",
                len(trade_lines_per_company),
                len(dividend_income_per_company),
            )
        except Exception as e:
            raise FileProcessingError(f"Failed to parse source file: {e}") from e

        # Calculate capital gains using FIFO matching algorithm
        try:
            leftover_trades: TradeCyclePerCompany = {}
            capital_gains: CapitalGainLinesPerCompany = {}
            calculate_fifo_gains(trade_lines_per_company, leftover_trades, capital_gains)
            logger.info(
                "Calculated %d capital gain lines",
                sum(len(gains) for gains in capital_gains.values()),
            )
        except Exception as e:
            raise SharesReportingError(f"Failed to calculate capital gains: {e}") from e

        # Export unmatched securities rollover file
        try:
            export_rollover_file(leftover_path, leftover_trades)
            logger.info("Generated unmatched securities rollover file: %s", leftover_path)
        except Exception as e:
            raise ReportGenerationError(f"Failed to generate unmatched securities rollover file: {e}") from e

        # Generate comprehensive tax report
        try:
            crypto_tax_report: CryptoTaxReport | None = None
            tax_year_hint = _infer_tax_year_hint_from_ib_data(ib_data)
            koinly_dir = _resolve_koinly_directory(validated_source.parent, tax_year_hint=tax_year_hint)

            if koinly_dir:
                logger.info("Detected Koinly directory: %s", koinly_dir)
                crypto_tax_report = _load_crypto_tax_report(
                    koinly_dir=koinly_dir,
                    tax_year_hint=tax_year_hint,
                    logger=logger,
                )
            else:
                logger.warning(
                    "No Koinly directory found under %s; continuing without crypto data",
                    validated_source.parent,
                )

            generate_tax_report(
                extract_path,
                capital_gains,
                dividend_income_per_company,
                crypto_tax_report=crypto_tax_report,
            )
            final_report_type = (
                "capital gains + dividends + crypto"
                if crypto_tax_report
                else "capital gains and dividend income"
            )
            if not dividend_income_per_company:
                final_report_type = "capital gains + crypto" if crypto_tax_report else "capital gains"
            logger.info("Generated %s report: %s", final_report_type, extract_path)
        except Exception as e:
            raise ReportGenerationError(f"Failed to generate report: {e}") from e

        logger.info("Application completed successfully")
        logger.info("Output directory: %s", validated_output_dir.name)
        logger.info("Generated %s report: %s", final_report_type, extract_path.name)
        logger.info("Leftover shares report: %s", leftover_path.name)
        logger.info(
            "Processed %d trade cycles and %d dividend entries",
            len(trade_lines_per_company),
            len(dividend_income_per_company),
        )
        print("Processing completed successfully!")

    except SharesReportingError as e:
        logger.error("Application error: %s", e)
        print(f"Error: {e}")
        sys.exit(1)
    except Exception as e:
        logger.exception("Unexpected error: %s", e)
        print(f"Unexpected error: {e}")
        print("Check logs for detailed information")
        sys.exit(1)


def _infer_tax_year_hint_from_ib_data(ib_data: IBExportData) -> int | None:
    sold_years = [
        trade.action.date_time.year
        for cycle in ib_data.trade_cycles.values()
        for trade in cycle.sold
    ]
    if sold_years:
        return max(sold_years)

    buy_years = [
        trade.action.date_time.year
        for cycle in ib_data.trade_cycles.values()
        for trade in cycle.bought
    ]
    if buy_years:
        return max(buy_years)

    return None


def _extract_year(value: str) -> int | None:
    match = re.search(r"(?<!\d)(\d{4})(?!\d)", value)
    if not match:
        return None
    return int(match.group(1))


def _is_koinly_year_mismatch(koinly_dir: Path, tax_year_hint: int | None) -> bool:
    if tax_year_hint is None:
        return False
    detected_year = _extract_year(koinly_dir.name)
    return detected_year is not None and detected_year != tax_year_hint


def _load_crypto_tax_report(
    koinly_dir: Path,
    tax_year_hint: int | None,
    logger: logging.Logger,
) -> CryptoTaxReport | None:
    if _is_koinly_year_mismatch(koinly_dir, tax_year_hint):
        logger.warning(
            "Koinly directory year (%s) does not match inferred IB tax year (%s); "
            "skipping crypto data from: %s",
            _extract_year(koinly_dir.name),
            tax_year_hint,
            koinly_dir,
        )
        return None

    try:
        crypto_tax_report = load_koinly_crypto_report(koinly_dir)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Failed to load Koinly crypto dataset from %s: %s. Continuing without crypto data.",
            koinly_dir,
            exc,
        )
        return None

    if crypto_tax_report:
        logger.info(
            "Loaded Koinly crypto dataset: %s capital rows, %s reward rows",
            len(crypto_tax_report.capital_entries),
            len(crypto_tax_report.reward_entries),
        )
    else:
        logger.warning(
            "Koinly directory exists but no parseable capital or income report was found: %s",
            koinly_dir,
        )

    return crypto_tax_report


def _resolve_koinly_directory(base_dir: Path, tax_year_hint: int | None) -> Path | None:
    candidates = [path for path in base_dir.iterdir() if path.is_dir() and path.name.lower().startswith("koinly")]
    if not candidates:
        return None

    if tax_year_hint is not None:
        for candidate in candidates:
            if _extract_year(candidate.name) == tax_year_hint:
                return candidate

    return max(candidates, key=lambda path: (_extract_year(path.name) or -1, path.name.lower()))


if __name__ == "__main__":
    main()
