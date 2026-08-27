"""Injectable report orchestrator (functional core).

Extracted from ``tax_reporting.main._main`` into staged helpers. Contains no
env reads (DI-3): the env gate lives in the composition root, which injects
the fetch callable.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

from ..domain.collections import (
    CapitalGainLinesPerCompany,
    DividendIncomePerCompany,
    IBExportData,
    TradeCyclePerCompany,
)
from ..domain.exceptions import (
    ConfigurationError,
    FileProcessingError,
    ReportGenerationError,
    SharesReportingError,
)
from ..infrastructure.config import Config, ConversionRate, TaxJurisdictionConfig
from ..infrastructure.validation import validate_output_directory
from .crypto.entities import OnChainReconciliationRecord
from .crypto_reporting import CryptoTaxReport, load_koinly_crypto_report
from .extraction import parse_ib_export_all
from .koinly_directory import (  # tests patch _resolve_koinly_directory on THIS module (patch seam)
    _detected_koinly_year,
    _is_koinly_year_mismatch,
    _resolve_koinly_directory,
)
from .on_chain_fetcher import fetch_failed_marker_path, write_fetch_failed_marker
from .on_chain_retry import describe_retry_consequence, retry_stale_on_chain_fetch

if TYPE_CHECKING:
    # Annotation-only; defining home is on_chain_fetcher.
    from .on_chain_fetcher import OnChainFetch
from .on_chain_th_substitution import OnChainThSubstituter
from .persisting import export_rollover_file, generate_tax_report
from .transformation import calculate_fifo_gains

#: Retry ladder backoff delays (plan 2026-08-26, user decision 2026-08-27):
#: when the opted-in TH substitution detects a stale fetch-failure marker AND a
#: fetch callable is injected, sleep FIRST (the short initial delay avoids
#: hammering an API that failed on a PRIOR run; r10-F2), then re-attempt the
#: fetch, once per delay. Six attempts = 63 s of backoff sleep plus each
#: attempt's own transfer time.
_STALE_FETCH_RETRY_DELAYS_S: tuple[float, ...] = (1.0, 2.0, 4.0, 8.0, 16.0, 32.0)

#: Sleep seam for the retry ladder: tests monkeypatch this module attribute so
#: no test sleeps the backoff window for real (hermetic suite, per-test 120 s
#: timeout).
_retry_sleep = time.sleep


class KoinlyStage(NamedTuple):
    """Result of the Koinly/on-chain stage: named fields instead of a bare tuple."""

    koinly_dir: Path | None
    on_chain_reconciliation: OnChainReconciliationRecord | None
    transaction_history_override: Path | None


def run_report(
    source_file: Path,
    output_dir: Path,
    app_config: Config | None,
    on_chain_fetch: OnChainFetch | None,
    logger: logging.Logger,
) -> None:
    """Run the full IB/Koinly report pipeline with injected collaborators.

    The jurisdiction is derived INSIDE from ``app_config``; the on-chain
    fetch is an injected callable (None means skip), wrapped in the broad
    ``except Exception`` soft-fail (DI-1) that covers ONLY that call.
    """
    tax_jurisdiction = app_config.tax_jurisdiction if app_config is not None else None

    logger.info("Starting tax reporting application")
    logger.info("Source file: %s", source_file)
    logger.info("Output directory: %s", output_dir)

    validated_source = _validated_source_path(source_file)

    try:
        validated_output_dir = validate_output_directory(output_dir)
    except Exception as e:
        raise ReportGenerationError(f"Invalid output directory: {e}") from e

    extract_path, leftover_path = (
        validated_output_dir / "extract.xlsx",
        validated_output_dir / "shares-leftover.csv",
    )

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
        tax_year_hint = _resolve_tax_year_hint(ib_data, tax_jurisdiction, logger)
        koinly_dir, on_chain_reconciliation, transaction_history_override = _resolve_koinly_stage(
            koinly_base_dir=validated_source.parent,
            output_dir=validated_output_dir,
            tax_year_hint=tax_year_hint,
            tax_jurisdiction=tax_jurisdiction,
            logger=logger,
            on_chain_fetch=on_chain_fetch,
        )
        crypto_tax_report: CryptoTaxReport | None = None
        if koinly_dir is not None:
            crypto_tax_report = _load_crypto_tax_report(
                koinly_dir=koinly_dir,
                tax_year_hint=tax_year_hint,
                tax_jurisdiction=tax_jurisdiction,
                logger=logger,
                rates=app_config.rates if app_config is not None else None,
                on_chain_reconciliation=on_chain_reconciliation,
                transaction_history_override=transaction_history_override,
            )

        final_report_type = _write_tax_report(
            extract_path,
            capital_gains,
            dividend_income_per_company,
            crypto_tax_report=crypto_tax_report,
            logger=logger,
        )

        _run_optional_on_chain_fetch(
            tax_jurisdiction=tax_jurisdiction,
            tax_year_hint=tax_year_hint,
            on_chain_fetch=on_chain_fetch,
            validated_output_dir=validated_output_dir,
            logger=logger,
        )
    except (ConfigurationError, ReportGenerationError):
        # Config problems (e.g. an unresolvable jurisdiction timezone) must
        # surface unwrapped so callers distinguish them from generation
        # problems (mirrors the composition root's contract). By design ALL
        # self-explanatory ReportGenerationErrors in this block - the M1
        # staleness refusals, rollover/crypto/Excel failures - propagate
        # verbatim; re-wrapping would double-prefix
        # "Failed to generate report:" over actionable text.
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


def _validated_source_path(source_file: Path) -> Path:
    """Validate the source path, wrapping failures into ``FileProcessingError``."""
    try:
        validated_source = Path(source_file)
        if not validated_source.exists():
            raise FileNotFoundError(f"Source file not found: {validated_source}")
        if not validated_source.is_file():
            raise FileProcessingError(f"Source path is not a file: {validated_source}")
    except Exception as e:
        raise FileProcessingError(f"Invalid source file: {e}") from e
    return validated_source


def _resolve_tax_year_hint(
    ib_data: IBExportData,
    tax_jurisdiction: TaxJurisdictionConfig | None,
    logger: logging.Logger,
) -> int | None:
    """Resolve the Koinly year hint: IB-inferred first, config fiscal_year fallback."""
    tax_year_hint = _infer_tax_year_hint_from_ib_data(ib_data)
    if tax_year_hint is None and tax_jurisdiction is not None:
        tax_year_hint = tax_jurisdiction.fiscal_year
        logger.info(
            "IB data has no current-year trades; using fiscal_year=%d from config as Koinly year hint",
            tax_year_hint,
        )
    return tax_year_hint


def _resolve_koinly_stage(  # noqa: PLR0913 (new arg from retry-ladder plan; refactor out of scope)
    koinly_base_dir: Path,
    output_dir: Path,
    tax_year_hint: int | None,
    tax_jurisdiction: TaxJurisdictionConfig | None,
    logger: logging.Logger,
    on_chain_fetch: OnChainFetch | None,
) -> KoinlyStage:
    """Resolve the Koinly directory and run the on-chain TH substitution (config-decided block).

    Returns a ``KoinlyStage`` (``koinly_dir``, ``on_chain_reconciliation``,
    ``transaction_history_override``); all-``None`` when no Koinly directory is
    found. The report loading
    itself is a separate call from ``run_report`` (jurisdiction and rates passed
    explicitly). The on-chain TH substitution carries its own M1
    fail-loud wrap.
    """
    koinly_dir = _resolve_koinly_directory(
        koinly_base_dir,
        tax_year_hint=tax_year_hint,
        fiscal_year=tax_jurisdiction.fiscal_year if tax_jurisdiction is not None else None,
    )

    if not koinly_dir:
        logger.warning(
            "No Koinly directory found under %s; continuing without crypto data",
            koinly_base_dir,
        )
        return KoinlyStage(None, None, None)

    logger.info("Detected Koinly directory: %s", koinly_dir)
    on_chain_reconciliation: OnChainReconciliationRecord | None = None
    transaction_history_override: Path | None = None
    on_chain_year_for_th = tax_jurisdiction.fiscal_year if tax_jurisdiction is not None else tax_year_hint
    # ``opted_in_wallets`` non-empty implies ``tax_jurisdiction is not None`` (the
    # helper derives the wallets from the jurisdiction), so the jurisdiction
    # clause below narrows the type for the helper call.
    if tax_jurisdiction is not None and tax_jurisdiction.on_chain_th_wallets and on_chain_year_for_th is not None:
        on_chain_reconciliation, transaction_history_override = _substitute_on_chain_th(
            koinly_dir,
            output_dir,
            on_chain_year_for_th,
            tax_jurisdiction,
            logger,
            on_chain_fetch,
        )
    return KoinlyStage(koinly_dir, on_chain_reconciliation, transaction_history_override)


def _substitute_on_chain_th(  # noqa: PLR0913 (new arg from retry-ladder plan; refactor out of scope)
    koinly_dir: Path,
    output_dir: Path,
    year: int,
    tax_jurisdiction: TaxJurisdictionConfig,
    logger: logging.Logger,
    on_chain_fetch: OnChainFetch | None,
) -> tuple[OnChainReconciliationRecord | None, Path | None]:
    """Run the on-chain TH substitution for opted-in wallets.

    Returns ``(reconciliation, transaction_history_override)``; ``(None, None)``
    means no substitution happened (no bera CSV / flag unset).
    """
    # --- On-chain TH substitution for opted-in wallets ---
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
    # collection-only on-chain fetch block. The broad ``except Exception``
    # stays ONLY around the injected fetch call (collection soft-fail); it
    # does NOT cover this parse path.
    opted_in_wallets = tax_jurisdiction.on_chain_th_wallets
    # The on-chain TH substitution returns a
    # reconciliation record (per-wallet provenance + delta block) when
    # it substitutes rows; ``None`` (no bera CSV, or flag unset) leaves
    # the new ``CryptoReconciliationSummary`` fields at their defaults
    # so the Koinly-only sheet is byte-identical.
    on_chain_reconciliation: OnChainReconciliationRecord | None = None
    # The merged TH lives at a NON-globbing path
    # (``on_chain_merged_th.csv``); the pipeline reads it via the explicit
    # ``transaction_history_override`` threaded through
    # ``load_koinly_crypto_report`` instead of re-globbing ``koinly_dir``.
    # ``None`` (no bera CSV / flag unset) preserves the glob (flag-off path
    # byte-identical).
    transaction_history_override: Path | None = None
    # Retry ladder (plan 2026-08-26): runs BEFORE ``maybe_substitute`` so
    # known-stale data never reaches the substitution unchecked. The backoff
    # schedule and the sleep seam stay HERE (plan freeze; tests patch
    # ``run_report._retry_sleep``); the contract (staleness decided by the
    # shared ``fetch_marker_is_stale`` predicate) lives in
    # ``on_chain_retry.retry_stale_on_chain_fetch``.
    retry_stale_on_chain_fetch(
        output_dir=output_dir,
        year=year,
        on_chain_fetch=on_chain_fetch,
        logger=logger,
        delays=_STALE_FETCH_RETRY_DELAYS_S,
        sleep=_retry_sleep,
    )
    try:
        # Wiring seam: thread the config-derived ON_CHAIN_RPC_URL
        # to the OnChainThSubstituter ctor (the FIRST pair of parens),
        # NOT to maybe_substitute.
        substitution = OnChainThSubstituter(on_chain_rpc_url=tax_jurisdiction.on_chain_rpc_url).maybe_substitute(
            koinly_dir=koinly_dir,
            output_dir=output_dir,
            year=year,
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
    return on_chain_reconciliation, transaction_history_override


def _write_tax_report(
    extract_path: Path,
    capital_gains: CapitalGainLinesPerCompany,
    dividend_income_per_company: DividendIncomePerCompany,
    crypto_tax_report: CryptoTaxReport | None,
    logger: logging.Logger,
) -> str:
    """Generate the Excel report and return the final report-type label."""
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
    return final_report_type


def _run_optional_on_chain_fetch(
    tax_jurisdiction: TaxJurisdictionConfig | None,
    tax_year_hint: int | None,
    on_chain_fetch: OnChainFetch | None,
    validated_output_dir: Path,
    logger: logging.Logger,
) -> None:
    """Run the optional, non-blocking on-chain transaction fetch (injected callable).

    None means skip; the year is resolved defensively (DI-9); the broad
    ``except Exception`` soft-fail (DI-1) covers ONLY this collection fetch
    call. On failure the WARNING names the retry-then-refuse consequence of
    the fresh marker (the next opted-in run retries and refuses the run when
    the attempts cannot clear the stale marker; the message body lives in
    :func:`on_chain_retry.describe_retry_consequence`).
    """
    on_chain_year = tax_jurisdiction.fiscal_year if tax_jurisdiction is not None else tax_year_hint
    if on_chain_year is None:
        logger.warning("No tax year resolved for on-chain fetch; continuing without on-chain transaction data.")
    elif on_chain_fetch is not None:
        try:
            on_chain_fetch(year=on_chain_year, output_dir=validated_output_dir)
        except Exception as exc:  # noqa: BLE001
            # Review r1 F6: a failed refresh leaves the PREVIOUS run's
            # bera_transactions.csv in place; write the staleness marker next
            # to it so the TH substitution stage (and the user) cannot mistake
            # the old CSV for fresh data once ON_CHAIN_TH_WALLETS is flipped.
            write_fetch_failed_marker(
                validated_output_dir,
                on_chain_year,
                f"On-chain fetch failed: {exc}",
            )
            logger.warning(
                "On-chain fetch failed: %s. Continuing without on-chain "
                "transaction data; the previous bera_transactions.csv (if "
                "any) is now STALE - a .fetch-failed marker was written "
                "next to it. Consequence: %s",
                exc,
                describe_retry_consequence(
                    _STALE_FETCH_RETRY_DELAYS_S,
                    fetch_failed_marker_path(validated_output_dir, on_chain_year).name,
                ),
            )


def _infer_tax_year_hint_from_ib_data(ib_data: IBExportData) -> int | None:
    sold_years = [trade.action.date_time.year for cycle in ib_data.trade_cycles.values() for trade in cycle.sold]
    if sold_years:
        return max(sold_years)

    buy_years = [trade.action.date_time.year for cycle in ib_data.trade_cycles.values() for trade in cycle.bought]
    if buy_years:
        return max(buy_years)

    return None


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
