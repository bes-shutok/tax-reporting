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
from datetime import date
from pathlib import Path

from .application.on_chain_config import BERACHAIN_CHAIN, load_on_chain_wallets
from .application.on_chain_fetcher import run_on_chain_fetch
from .application.on_chain_th_substitution import normalize_wallet_label
from .application.on_chain_validation.dispositions import EXIT_VALIDATION_CRASH
from .application.on_chain_validation.runner import run_validation
from .application.run_report import run_report
from .domain.exceptions import (
    ConfigurationError,
    MissingDecisionPointsError,
    SharesReportingError,
)
from .domain.on_chain_config import OnChainWalletConfig
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

    parser.add_argument(
        "--validate-on-chain-th",
        type=int,
        metavar="YEAR",
        help=(
            "Run the read-only on-chain Transaction-History validation harness for YEAR "
            "(diffs the production on-chain projection against the Koinly TH baseline; "
            "artifacts land under resources/result/<YEAR>/). Exits 0 when validated, "
            "1 when misconfigured, 3 while discrepancy clusters lack dispositions."
        ),
    )

    parser.add_argument(
        "--from",
        dest="date_from",
        type=date.fromisoformat,
        metavar="DATE",
        help="Inclusive start of the validation window (ISO YYYY-MM-DD; requires --validate-on-chain-th)",
    )

    parser.add_argument(
        "--to",
        dest="date_to",
        type=date.fromisoformat,
        metavar="DATE",
        help="Inclusive end of the validation window (ISO YYYY-MM-DD; requires --validate-on-chain-th)",
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

    # Validation-harness flags (plan Task 6): the validate path is a separate,
    # read-only dispatch - it shares no inputs with the report path.
    if args.validate_on_chain_th is not None and args.example:
        parser.error("--validate-on-chain-th cannot be used with --example")

    if args.validate_on_chain_th is not None and args.source_file is not None:
        parser.error("--validate-on-chain-th cannot be used with --source-file")

    # The validation artifacts deliberately carry real tx hashes: the PII rule
    # (Design Invariant 6) is enforced by LOCATION - only the gitignored
    # ``resources/result/<year>/`` surface. A shared --output-dir would move
    # them (and the bera-CSV read) outside that surface (review r1 F21), so
    # the documented contract is enforced, not just documented.
    if args.validate_on_chain_th is not None and args.output_dir is not None:
        parser.error("--validate-on-chain-th cannot be used with --output-dir")

    if args.validate_on_chain_th is None and (args.date_from is not None or args.date_to is not None):
        parser.error("--from/--to require --validate-on-chain-th")

    if args.date_from is not None and args.date_to is not None and args.date_from > args.date_to:
        parser.error("--from must not be later than --to")

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


def _run_validation_from_cli(args: argparse.Namespace) -> int:
    """Composition root for the on-chain TH validation harness (plan Task 6).

    Owns every config/env read the validation path needs (DI discipline):
    ``ON_CHAIN_RPC_URL`` (RPC enrichment) and the ``ON_CHAIN_TH_WALLETS``
    precedence (Design Invariant 9: when the user has explicitly configured
    the on-chain TH wallets, THOSE labels select the wallets under validation;
    the runner itself never requires the flag and otherwise derives them from
    the ``chains.json`` Berachain entries). An absent config.ini is tolerated
    (the harness is jurisdiction-independent); a present-but-invalid one fails
    loud, mirroring ``_main``'s exception structure.

    Returns:
        The harness exit status (0 passed / 1 misconfigured / 3 incomplete),
        which ``cli()`` passes to ``sys.exit``.
    """
    log_file = Path("logs", "tax-reporting.log")
    resolved_level = args.log_level if args.log_level is not None else DEFAULT_LOG_LEVEL
    configure_application_logging(level=resolved_level, log_file=log_file)
    logger = create_module_logger(__name__)

    rpc_url: str | None = None
    wallets: list[OnChainWalletConfig] | None = None
    try:
        app_config = load_configuration_from_file()
    except MissingDecisionPointsError:
        raise
    except (FileNotFoundError, OSError):
        logger.warning("Config file not found; running on-chain TH validation with RPC enrichment disabled.")
    except (ValueError, KeyError, configparser.Error) as exc:
        raise ConfigurationError(f"Config file has invalid settings. Correct config.ini and retry: {exc}") from exc
    else:
        jurisdiction = app_config.tax_jurisdiction
        rpc_url = jurisdiction.on_chain_rpc_url
        if jurisdiction.on_chain_th_wallets:
            # ON_CHAIN_TH_WALLETS precedence (Design Invariant 9): filter the
            # chains.json Berachain wallets to the explicitly configured
            # labels (normalized match, the same ``normalize_wallet_label`` semantics the
            # TH merge uses). A configured label matching no Berachain wallet
            # resolves to an empty list, which the runner fails loud on.
            configured = {normalize_wallet_label(label) for label in jurisdiction.on_chain_th_wallets}
            wallets = [
                wallet
                for wallet in load_on_chain_wallets(args.validate_on_chain_th)
                if wallet.chain == BERACHAIN_CHAIN and normalize_wallet_label(wallet.label) in configured
            ]

    # Review r1 F21: ``--output-dir`` combined with ``--validate-on-chain-th``
    # is rejected by ``_validate_args``, so the validation artifacts always
    # land in the gitignored default surface - state the same contract the
    # guard enforces (no dead fallback branch).
    output_dir = Path("resources/result")
    return run_validation(
        year=args.validate_on_chain_th,
        output_dir=output_dir,
        koinly_dir=None,
        wallets=wallets,
        rpc_url=rpc_url,
        date_from=args.date_from,
        date_to=args.date_to,
        logger=logger,
    )


def cli() -> None:
    """CLI entry point that parses arguments and calls main()."""
    parser = _build_arg_parser()
    args = parser.parse_args()

    # Validate argument combinations
    _validate_args(args, parser)

    # Validation-harness dispatch (plan Task 6): a separate, read-only path.
    # The normal report path (main/_main) below is untouched by this branch.
    if args.validate_on_chain_th is not None:
        # Crash wrapper (mirrors main()'s catch-Exception structure, but exits
        # EXIT_VALIDATION_CRASH so acceptance scripts can tell an unexpected
        # crash (code 2) from a misconfigured run (code 1)). Config errors
        # keep propagating as their own type.
        try:
            sys.exit(_run_validation_from_cli(args))
        except (ConfigurationError, MissingDecisionPointsError):
            raise
        except Exception as e:
            logger = logging.getLogger(__name__)
            logger.exception("Unexpected error during on-chain TH validation: %s", e)
            print("On-chain TH validation crashed unexpectedly. Check logs for detailed information")
            sys.exit(EXIT_VALIDATION_CRASH)

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
