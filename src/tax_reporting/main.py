"""Main entry point for the tax reporting application.

Processes Interactive Brokers and Koinly CSV exports to generate comprehensive tax reporting data
for capital gains, dividend income, and crypto rewards.
"""

from __future__ import annotations

import argparse
import configparser
import functools
import logging
import os
import sys
from pathlib import Path

from .application.on_chain_fetcher import run_on_chain_fetch
from .application.run_report import run_report
from .domain.exceptions import (
    ConfigurationError,
    MissingDecisionPointsError,
    SharesReportingError,
)
from .infrastructure.config import DEFAULT_LOG_LEVEL, load_configuration_from_file
from .infrastructure.logging_config import configure_application_logging, create_module_logger


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


def _main(
    source_file: Path | None = None, output_dir: Path | None = None, log_level: str | None = None
) -> None:
    """Composition root: resolve defaults, load config, gate the env var, delegate.

    Main application implementation that raises domain exceptions. The pipeline
    itself lives in ``application.run_report.run_report``.
    """
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

    app_config = None
    try:
        app_config = load_configuration_from_file()
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

    # DI-3: the env gate is read exactly once, here in the composition root, at
    # construction time. If set, bind the fetch callable (the pipeline calls it with
    # ``(year, output_dir)``); if absent, inject None (skip) with the "not set"
    # WARNING. Note the WARNING fires at construction time, i.e. whenever the gate
    # is evaluated and the var is absent (CR-Guard-accepted widening; pinned by a
    # composition-root test in Task 4).
    on_chain_api_key = os.getenv("BERA_CHAIN_API_KEY")
    if on_chain_api_key:
        on_chain_fetch = functools.partial(run_on_chain_fetch, api_key=on_chain_api_key)
    else:
        logger.warning("BERA_CHAIN_API_KEY not set; continuing without on-chain transaction data.")
        on_chain_fetch = None

    run_report(
        source_file=source_file,
        output_dir=output_dir,
        app_config=app_config,
        on_chain_fetch=on_chain_fetch,
        logger=logger,
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
