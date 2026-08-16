"""Main entry point for the tax reporting application.

Processes Interactive Brokers and Koinly CSV exports to generate comprehensive tax reporting data
for capital gains, dividend income, and crypto rewards.
"""

from __future__ import annotations

import argparse
import configparser
import logging
import os
import re
import sys
from pathlib import Path

from .application.crypto.entities import OnChainReconciliationRecord
from .application.crypto_reporting import CryptoTaxReport, load_koinly_crypto_report
from .application.extraction import parse_ib_export_all
from .application.on_chain_fetcher import run_on_chain_fetch
from .application.on_chain_th_substitution import OnChainThSubstituter
from .application.persisting import export_rollover_file, generate_tax_report
from .application.transformation import calculate_fifo_gains
from .domain.collections import (
    CapitalGainLinesPerCompany,
    DividendIncomePerCompany,
    IBExportData,
    TradeCyclePerCompany,
)
from .domain.exceptions import (
    ConfigurationError,
    FileProcessingError,
    MissingDecisionPointsError,
    ReportGenerationError,
    SharesReportingError,
)
from .infrastructure.config import (
    DEFAULT_LOG_LEVEL,
    Config,
    ConversionRate,
    TaxJurisdictionConfig,
    load_configuration_from_file,
)
from .infrastructure.logging_config import configure_application_logging, create_module_logger
from .infrastructure.validation import validate_output_directory


def _build_arg_parser() -> argparse.ArgumentParser:
    """Build and return the CLI argument parser.

    Returns:
        ArgumentParser: Configured argument parser with all CLI options.
    """
    parser = argparse.ArgumentParser(
        prog="tax-reporting",
        description="Generate Portuguese tax reports from Interactive Brokers and Koinly exports.",
    )

    parser.add_argument(
        "--example",
        action="store_true",
        help="Use example data from resources/source/example/ and output to resources/result/example/",
    )

    parser.add_argument(
        "--source-file",
        type=str,
        metavar="PATH",
        help="Path to the source IB export CSV file (default: resources/source/ib_export.csv)",
    )

    parser.add_argument(
        "--output-dir",
        type=str,
        metavar="PATH",
        help="Directory for output files (default: resources/result)",
    )

    parser.add_argument(
        "--log-level",
        type=str,
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        metavar="LEVEL",
        help="Set console log level (overrides config.ini LOG_LEVEL; default: WARNING)",
    )

    return parser


def _validate_args(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    """Validate parsed CLI arguments.

    Args:
        args: Parsed arguments from argparse.
        parser: The argument parser (used for error reporting).

    Raises:
        SystemExit: If argument validation fails.
    """
    if args.example and args.source_file is not None:
        parser.error("--example cannot be used with --source-file")

    if args.example and args.output_dir is not None:
        parser.error("--example cannot be used with --output-dir")

    # Validate example files exist when --example is used
    if args.example:
        project_root = Path(__file__).parent.parent.parent
        example_source = project_root / "resources/source/example/ib_export.csv"
        if not example_source.exists():
            parser.error(f"Example source file not found: {example_source}")


def _main(  # noqa: PLR0912, PLR0915
    source_file: Path | None = None, output_dir: Path | None = None, log_level: str | None = None
) -> None:
    """Main application implementation that raises domain exceptions."""
    if source_file is None:
        source_file = Path("resources/source", "ib_export.csv")
    if output_dir is None:
        output_dir = Path("resources/result")

    log_file = Path("logs", "tax-reporting.log")

    # Design Invariant 9: load config FIRST, configure logging ONCE with the resolved
    # level, then run the IB/FIFO block.
    #
    # Audit-trail integrity guard (r1 review F1): ``load_configuration_from_file`` emits
    # ~10 diagnostic lines during the parse AND the load-bearing
    # ``logger.error("Configuration parsing error: %s", ...)`` at config.py on the
    # ``(KeyError, ValueError)`` failure path. If logging is configured only AFTER config
    # load succeeds, those emissions run on an unconfigured root logger and never reach
    # ``logs/tax-reporting.log`` (the audit trail). The pre-config call below establishes
    # file logging at the conservative DEFAULT_LOG_LEVEL BEFORE config loads;
    # ``configure_application_logging`` clears existing handlers, so the post-load
    # RE-configure with the config-derived ``resolved_level`` is safe and simply replaces
    # the pre-config handlers. The FileNotFoundError and ValueError paths are both covered
    # by this pre-config call, so no per-branch configure call is needed for audit-trail
    # integrity; the FileNotFoundError WARNING below is already guaranteed a file handler.
    configure_application_logging(level=DEFAULT_LOG_LEVEL, log_file=log_file)

    # Hoisted before the config-load try block: every branch below (success,
    # FileNotFoundError, ValueError) shares this logger, and ``create_module_logger``
    # is just ``logging.getLogger(name)`` (idempotent), so a single assignment suffices
    # and no per-branch assignment is needed.
    logger = create_module_logger(__name__)

    tax_jurisdiction = None
    app_config: Config | None = None
    try:
        app_config = load_configuration_from_file()
        tax_jurisdiction = app_config.tax_jurisdiction
        resolved_level = log_level if log_level is not None else app_config.log_level
        # RE-configure (handlers cleared by configure_application_logging) with the
        # config-derived level now that config load succeeded.
        configure_application_logging(level=resolved_level, log_file=log_file)
    except MissingDecisionPointsError:
        raise
    except (FileNotFoundError, OSError):
        # Logging was pre-configured at DEFAULT_LOG_LEVEL above; emit the not-found
        # WARNING so the audit trail records why jurisdiction config is absent.
        logger.warning(
            "Config file not found; no jurisdiction config loaded. Crypto processing will "
            "fail fast if a Koinly directory is present (naive Koinly dates need a zone to localize)"
        )
    except (ValueError, KeyError, configparser.Error) as exc:
        raise ConfigurationError(f"Config file has invalid settings. Correct config.ini and retry: {exc}") from exc

    final_report_type = "capital gains"

    extract_path = output_dir / "extract.xlsx"
    leftover_path = output_dir / "shares-leftover.csv"

    logger.info("Starting tax reporting application")
    logger.info("Source file: %s", source_file)
    logger.info("Output directory: %s", output_dir)

    try:
        validated_source = Path(source_file)
        if not validated_source.exists():
            raise FileNotFoundError(f"Source file not found: {validated_source}")
        if not validated_source.is_file():
            raise FileProcessingError(f"Source path is not a file: {validated_source}")
    except Exception as e:
        raise FileProcessingError(f"Invalid source file: {e}") from e

    try:
        validated_output_dir = validate_output_directory(output_dir)
    except Exception as e:
        raise ReportGenerationError(f"Invalid output directory: {e}") from e

    extract_path = validated_output_dir / "extract.xlsx"
    leftover_path = validated_output_dir / "shares-leftover.csv"

    logger.info("Processing file: %s", validated_source.name)
    logger.info("Output files will be: %s and %s", extract_path.name, leftover_path.name)

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

    try:
        export_rollover_file(leftover_path, leftover_trades)
        logger.info("Generated unmatched securities rollover file: %s", leftover_path)
    except Exception as e:
        raise ReportGenerationError(f"Failed to generate unmatched securities rollover file: {e}") from e

    try:
        crypto_tax_report: CryptoTaxReport | None = None
        tax_year_hint = _infer_tax_year_hint_from_ib_data(ib_data)
        if tax_year_hint is None and tax_jurisdiction is not None:
            tax_year_hint = tax_jurisdiction.fiscal_year
            logger.info(
                "IB data has no current-year trades; using fiscal_year=%d from config as Koinly year hint",
                tax_year_hint,
            )
        koinly_dir = _resolve_koinly_directory(
            validated_source.parent,
            tax_year_hint=tax_year_hint,
            fiscal_year=tax_jurisdiction.fiscal_year if tax_jurisdiction is not None else None,
        )

        if koinly_dir:
            logger.info("Detected Koinly directory: %s", koinly_dir)
            # --- On-chain TH substitution for opted-in wallets (Plan Task 11) ---
            #
            # When ``on_chain_th_wallets`` lists a wallet AND the on-chain CSV
            # (``bera_transactions.csv``) is present, run the on-chain parse path
            # (CSV reader -> Berachain processor -> adapter) and SUBSTITUTE the
            # projected rows for that wallet's Koinly TH rows (bridge option (a):
            # serialize to a TH-shaped CSV with ``event_id`` written where the
            # pipeline reads TH from).
            #
            # FAIL-LOUD BOUNDARY (M1): this on-chain PARSING/processing path is
            # wrapped in its OWN ``try/except ReportGenerationError``. A parse
            # failure for an opted-in wallet propagates ``ReportGenerationError``
            # and is NEVER swallowed by the broad ``except Exception`` at the
            # collection-only ``run_on_chain_fetch`` block below. The broad
            # ``except Exception`` stays ONLY around ``run_on_chain_fetch``
            # (collection soft-fail); it does NOT cover this parse path.
            on_chain_year_for_th = (
                tax_jurisdiction.fiscal_year if tax_jurisdiction is not None else tax_year_hint
            )
            opted_in_wallets = (
                tax_jurisdiction.on_chain_th_wallets if tax_jurisdiction is not None else []
            )
            # Plan Task 12: the on-chain TH substitution returns a
            # reconciliation record (per-wallet provenance + delta block) when
            # it substitutes rows; ``None`` (no bera CSV, or flag unset) leaves
            # the new ``CryptoReconciliationSummary`` fields at their defaults
            # so the Koinly-only sheet is byte-identical.
            on_chain_reconciliation: OnChainReconciliationRecord | None = None
            # F1/F7: the merged TH lives at a NON-globbing path
            # (``on_chain_merged_th.csv``); the pipeline reads it via the explicit
            # ``transaction_history_override`` threaded through
            # ``load_koinly_crypto_report`` instead of re-globbing ``koinly_dir``.
            # ``None`` (no bera CSV / flag unset) preserves the glob (flag-off path
            # byte-identical).
            transaction_history_override: Path | None = None
            if opted_in_wallets and on_chain_year_for_th is not None:
                try:
                    # F4+F9 wiring seam: thread the config-derived ON_CHAIN_RPC_URL
                    # to the OnChainThSubstituter ctor (the FIRST pair of parens),
                    # NOT to maybe_substitute. F2 assumption: ``tax_jurisdiction``
                    # is guaranteed non-None here because this gate requires
                    # ``opted_in_wallets`` (set above), which is only non-empty when
                    # ``tax_jurisdiction is not None`` (the line 264 comprehension
                    # returns [] otherwise). So ``.on_chain_rpc_url`` is safe.
                    substitution = OnChainThSubstituter(
                        on_chain_rpc_url=tax_jurisdiction.on_chain_rpc_url
                    ).maybe_substitute(
                        koinly_dir=koinly_dir,
                        output_dir=validated_output_dir,
                        year=on_chain_year_for_th,
                        opted_in_wallets=opted_in_wallets,
                        logger=logger,
                    )
                    if substitution is not None:
                        on_chain_reconciliation = substitution.reconciliation
                        transaction_history_override = substitution.merged_th_path
                except Exception as exc:
                    # Fail-loud (M1): an opted-in wallet's parse failure must
                    # surface, not be silently skipped. ``ReportGenerationError``
                    # and ``ConfigurationError`` are re-raised unchanged (the
                    # former would otherwise be double-wrapped here, since
                    # ``except Exception`` matches subclasses); any other failure
                    # is wrapped into a fail-loud ``ReportGenerationError`` (NOT a
                    # soft-fail), because an opted-in wallet has explicitly
                    # requested on-chain data, so silently falling back to Koinly
                    # would hide the divergence.
                    if isinstance(exc, (ReportGenerationError, ConfigurationError)):
                        raise
                    raise ReportGenerationError(
                        f"On-chain TH substitution failed for opted-in wallet(s) "
                        f"{opted_in_wallets}: {exc}. The opted-in path fails loud (M1); "
                        f"remove the wallet from ON_CHAIN_TH_WALLETS or fix the on-chain CSV."
                    ) from exc
            crypto_tax_report = _load_crypto_tax_report(
                koinly_dir=koinly_dir,
                tax_year_hint=tax_year_hint,
                tax_jurisdiction=tax_jurisdiction,
                logger=logger,
                rates=app_config.rates if app_config is not None else None,
                on_chain_reconciliation=on_chain_reconciliation,
                transaction_history_override=transaction_history_override,
            )
        else:
            logger.warning(
                "No Koinly directory found under %s; continuing without crypto data",
                validated_source.parent,
            )

        crypto_sheet_created = generate_tax_report(
            extract_path,
            capital_gains,
            dividend_income_per_company,
            crypto_tax_report=crypto_tax_report,
        )
        final_report_type = (
            "capital gains + dividends + crypto" if crypto_sheet_created else "capital gains and dividend income"
        )
        if not dividend_income_per_company:
            final_report_type = "capital gains + crypto" if crypto_sheet_created else "capital gains"
        logger.info("Generated %s report: %s", final_report_type, extract_path)

        # --- Optional, non-blocking on-chain transaction fetch (Task 6) ---
        # This is a parallel, year-scoped collection step that is INDEPENDENT of
        # the Koinly-based crypto pipeline above. It must NEVER abort the IB/Koinly
        # report: the env-var gate lives here in main.py (DI-3), the year is
        # resolved defensively so a None jurisdiction cannot raise AttributeError
        # (DI-9), and the catch is the broad ``except Exception`` mirroring the
        # optional-Koinly degrade template at the helper below (DI-1/r1 F1).
        on_chain_year = tax_jurisdiction.fiscal_year if tax_jurisdiction is not None else tax_year_hint
        if on_chain_year is None:
            logger.warning(
                "No tax year resolved for on-chain fetch; continuing without on-chain transaction data."
            )
        else:
            on_chain_api_key = os.getenv("BERA_CHAIN_API_KEY")
            if not on_chain_api_key:
                logger.warning(
                    "BERA_CHAIN_API_KEY not set; continuing without on-chain transaction data."
                )
            else:
                try:
                    run_on_chain_fetch(
                        year=on_chain_year,
                        output_dir=validated_output_dir,
                        api_key=on_chain_api_key,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "On-chain fetch failed: %s. Continuing without on-chain transaction data.",
                        exc,
                    )
    except ConfigurationError:
        # A config problem (e.g. crypto data present but the jurisdiction timezone
        # cannot be resolved) must surface as a ConfigurationError, not be wrapped
        # into a ReportGenerationError, so callers can distinguish config problems
        # from data/generation problems. Mirrors the unwrapped-propagation contract
        # of the config-loading block above.
        raise
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


def main(source_file: Path | None = None, output_dir: Path | None = None, log_level: str | None = None) -> None:
    """Main application entry point."""
    try:
        _main(source_file=source_file, output_dir=output_dir, log_level=log_level)
    except SharesReportingError as e:
        logger = logging.getLogger(__name__)
        logger.error("Application error: %s", e)
        print(f"Error: {e}")
        sys.exit(1)
    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.exception("Unexpected error: %s", e)
        print(f"Unexpected error: {e}")
        print("Check logs for detailed information")
        sys.exit(1)


def _infer_tax_year_hint_from_ib_data(ib_data: IBExportData) -> int | None:
    sold_years = [trade.action.date_time.year for cycle in ib_data.trade_cycles.values() for trade in cycle.sold]
    if sold_years:
        return max(sold_years)

    buy_years = [trade.action.date_time.year for cycle in ib_data.trade_cycles.values() for trade in cycle.bought]
    if buy_years:
        return max(buy_years)

    return None


def _extract_year(value: str) -> int | None:
    match = re.search(r"(?<!\d)(\d{4})(?!\d)", value)
    if not match:
        return None
    return int(match.group(1))


def _detected_koinly_year(koinly_dir: Path) -> int | None:
    # The legacy layout embeds the year in the directory name (``koinly2025``).
    # The newer ``<year>/koinly`` layout has a bare ``koinly`` leaf, so fall back
    # to the parent directory's year when the leaf carries none. Without this,
    # a fiscal_year/IB-year divergence on the new layout would load wrong-year
    # crypto data with no mismatch warning.
    detected_year = _extract_year(koinly_dir.name)
    if detected_year is None:
        detected_year = _extract_year(koinly_dir.parent.name)
    return detected_year


def _is_koinly_year_mismatch(koinly_dir: Path, tax_year_hint: int | None) -> bool:
    # A None hint is only reachable without config, which fails fast before any Koinly
    # row loads, so this branch cannot let wrong-year data through.
    if tax_year_hint is None:
        return False
    detected_year = _detected_koinly_year(koinly_dir)
    return detected_year is not None and detected_year != tax_year_hint


def _load_crypto_tax_report(  # noqa: PLR0913
    koinly_dir: Path,
    tax_year_hint: int | None,
    logger: logging.Logger,
    tax_jurisdiction: TaxJurisdictionConfig | None = None,
    rates: list[ConversionRate] | None = None,
    on_chain_reconciliation: OnChainReconciliationRecord | None = None,
    transaction_history_override: Path | None = None,
) -> CryptoTaxReport | None:
    if _is_koinly_year_mismatch(koinly_dir, tax_year_hint):
        logger.warning(
            "Koinly directory year (%s) does not match inferred IB tax year (%s); skipping crypto data from: %s",
            _detected_koinly_year(koinly_dir),
            tax_year_hint,
            koinly_dir,
        )
        return None

    # STRICT localization contract: crypto data is present and the year matched, so
    # naive CG/OGR/Income dates WILL be parsed and localized. Without a resolved
    # jurisdiction timezone there is no correct way to localize them - the loader's
    # no-zone path silently stamps naive dates as UTC, putting every cross-report
    # match key (DP-014 payment match, derivatives dedup, OGR override) on the wrong
    # calendar day. Fail fast instead of silently producing a wrong-day report. Both
    # ``tax_jurisdiction is None`` (no config loaded at all) and
    # ``tax_jurisdiction.timezone is None`` (configured but no IANA_TIMEZONE, and not
    # PT which auto-deduces Europe/Lisbon at config load) fail here. The loader
    # itself stays a pure parser (unit-testable with jurisdiction=None); this is the
    # application boundary that enforces it.
    if tax_jurisdiction is None or tax_jurisdiction.timezone is None:
        reason = (
            "no jurisdiction config loaded (config.ini absent or unreadable)"
            if tax_jurisdiction is None
            else (
                f"jurisdiction {tax_jurisdiction.country!r} has no resolved timezone "
                "(set IANA_TIMEZONE in [TAX JURISDICTION]; TAX_COUNTRY=PT auto-deduces Europe/Lisbon)"
            )
        )
        raise ConfigurationError(
            f"Cannot process crypto data from {koinly_dir}: {reason}. Naive Koinly "
            "CG/OGR/Income dates are jurisdiction-local and cannot be localized "
            "without a zone; refusing to silently treat them as UTC."
        )

    try:
        crypto_tax_report = load_koinly_crypto_report(
            koinly_dir,
            jurisdiction=tax_jurisdiction,
            rates=rates,
            on_chain_reconciliation=on_chain_reconciliation,
            transaction_history_override=transaction_history_override,
        )
    except ConfigurationError:
        # A configuration problem raised by the loader must fail the run. It must NOT
        # be degraded to "continue without crypto" like a parse/data error. (The
        # STRICT guard above raises before this try; this clause keeps any future
        # loader-side ConfigurationError from being silently swallowed too.)
        raise
    except FileProcessingError as exc:
        logger.error(
            "Koinly data in %s is malformed and cannot be parsed: %s. "
            "Continuing without crypto data: fix the Koinly export and re-run.",
            koinly_dir,
            exc,
        )
        return None
    except Exception as exc:  # noqa: BLE001
        logger.error(
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


def _resolve_koinly_directory(base_dir: Path, tax_year_hint: int | None, fiscal_year: int | None = None) -> Path | None:
    # New personal-data layout: ``<base_dir>/<year>/koinly`` (e.g.
    # ``resources/source/2025/koinly``), where ``<year>`` is the configured fiscal
    # year. The fiscal_year from config is preferred (the source of truth for which
    # tax year is being filed); fall back to the IB-inferred tax_year_hint.
    # Note: selecting the directory by fiscal_year does NOT bypass the year-mismatch
    # guard in _load_crypto_tax_report, which compares the directory's detected year
    # against the IB-inferred tax_year_hint and skips crypto on divergence. That is
    # intentional (see the repo rule on Koinly year mismatch): if the IB export's
    # year disagrees with the configured fiscal_year, loading crypto is unsafe, so
    # the run skips it with a warning rather than risk wrong-year data.
    year = fiscal_year if fiscal_year is not None else tax_year_hint
    if year is not None:
        year_subdir = base_dir / str(year) / "koinly"
        if year_subdir.is_dir():
            return year_subdir

    # Legacy personal layout fallback: ``base_dir`` itself is a ``koinly<year>`` dir.
    # Modern layouts (real data and committed synthetic fixtures) resolve via the
    # ``<year>/koinly`` subdir lookup above; this glob only catches the legacy flat form.
    candidates = [path for path in base_dir.iterdir() if path.is_dir() and path.name.lower().startswith("koinly")]
    if not candidates:
        return None

    if tax_year_hint is not None:
        for candidate in candidates:
            if _extract_year(candidate.name) == tax_year_hint:
                return candidate

    return max(candidates, key=lambda path: (_extract_year(path.name) or -1, path.name.lower()))


def cli() -> None:
    """CLI entry point that parses arguments and calls main()."""
    parser = _build_arg_parser()
    args = parser.parse_args()

    # Validate argument combinations
    _validate_args(args, parser)

    # Resolve example flag paths
    source_file = args.source_file
    output_dir = args.output_dir
    if args.example:
        # Resolve paths relative to project root for consistent behavior from any working directory
        project_root = Path(__file__).parent.parent.parent
        source_file = str(project_root / "resources/source/example/ib_export.csv")
        output_dir = str(project_root / "resources/result/example")

    # Convert string paths to Path objects (or None)
    source_file_path = Path(source_file) if source_file is not None else None
    output_dir_path = Path(output_dir) if output_dir is not None else None

    # Apply default log level if not specified
    log_level = args.log_level  # may be None; _main resolves the default from config

    main(source_file=source_file_path, output_dir=output_dir_path, log_level=log_level)


if __name__ == "__main__":
    cli()
