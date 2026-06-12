"""Crypto tax reporting helpers for Koinly exports."""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path
from typing import Final

from ..domain.exceptions import FileProcessingError
from ..infrastructure.config import DEFAULT_ZERO_BASIS_REVIEW_THRESHOLD, TaxJurisdictionConfig
from ..infrastructure.koinly_parser import (
    _find_and_parse_other_gains_file,
    contains_non_latin_characters,
    format_datetime,
    normalize_asset_ticker,
    normalize_platform_name,
    parse_koinly_datetime,
    parse_koinly_decimal,
    read_koinly_rows,
)
from .crypto.aggregation import (
    _aggregate_capital_entries,
    _filter_immaterial_entries,
)
from .crypto.chain_derivation import _derive_chain
from .crypto.classification import (
    _classify_reward_tax_status,
    _contains_popular_token,
    _get_all_fiat_currency_codes,
    _get_popular_crypto_tokens,
    _load_popular_crypto_tokens,
)
from .crypto.entities import (
    AggregatedRewardIncomeEntry,
    CapitalGainPeriodStats,
    CryptoCapitalGainEntry,
    CryptoCapitalGainStats,
    CryptoCompletePdfSummary,
    CryptoReconciliationSummary,
    CryptoReviewEntry,
    CryptoRewardIncomeEntry,
    CryptoSkippedZeroValueToken,
    CryptoTaxReport,
    HoldingsSnapshot,
    LoanActivityEntry,
    OperatorOrigin,
    RewardTaxClassification,
)
from .crypto.fifo_helpers import (
    _build_zero_basis_review_reason,
    _rebuild_fifo_for_loan_affected_assets,
)
from .crypto.loan_activity import _extract_loan_activity
from .crypto.ogr_handler import (
    _apply_ogr_direction_override,
    _apply_ogr_overrides,
    _build_ogr_index,
    _validate_capital_entries_have_valid_countries,
)
from .crypto.operator_origin import resolve_operator_origin
from .crypto.parsing import (
    _extract_tax_year,
    _find_report_file,
    _find_report_path,
    _parse_complete_tax_report_pdf,
    _register_skipped_zero_asset,
)
from .crypto.validation import (
    _is_temporally_valid,
    _parse_transaction_date,
)
from .crypto.constants import ZERO
from .crypto_fifo import (
    discover_loan_affected_assets,
)
from .token_origin import TokenOriginResolver


def load_koinly_crypto_report(  # noqa: PLR0912, PLR0915
    koinly_dir: Path, jurisdiction: TaxJurisdictionConfig | None = None
) -> CryptoTaxReport | None:
    """Load Koinly exports from a directory and normalize for tax reporting.

    Args:
        koinly_dir: Directory containing Koinly CSV exports (capital gains, income,
            and optionally transaction history reports).
        jurisdiction: Optional tax jurisdiction config.  When provided and
            ``exclude_loan_repayment_gains`` is True, the FIFO rebuild path is
            activated for loan-affected assets.

    Returns:
        A populated ``CryptoTaxReport`` on success, or ``None`` when the directory
        does not exist, contains no recognised report files, or the transaction
        history required for FIFO rebuild is absent.
    """
    if not koinly_dir.exists() or not koinly_dir.is_dir():
        return None

    capital_file = _find_report_file(koinly_dir, "capital_gains_report")
    income_file = _find_report_file(koinly_dir, "income_report")
    transaction_history_file = _find_report_file(koinly_dir, "transaction_history")

    _required = {
        "capital_gains_report (Capital gains report)": capital_file,
        "income_report (Income report)": income_file,
        "transaction_history (Transaction history)": transaction_history_file,
    }
    _present = {name for name, f in _required.items() if f is not None}
    _missing = {name for name, f in _required.items() if f is None}

    if not _present:
        # No Koinly exports at all — crypto reporting simply not available for this run.
        return None

    if _missing:
        raise FileProcessingError(
            f"Incomplete Koinly export in {koinly_dir}: {len(_missing)} of 3 required files are missing. "
            f"Missing: {sorted(_missing)}. "
            f"Present: {sorted(_present)}. "
            "Export all three required reports from Koinly (Capital gains report, Income report, "
            "Transaction history) and place them in the same directory."
        )

    year = _extract_tax_year(koinly_dir, capital_file, income_file, jurisdiction=jurisdiction)
    skipped_assets: dict[tuple[str, str], dict] = {}
    review_entries: list[CryptoReviewEntry] = []

    origin_resolver = TokenOriginResolver(transaction_history_file)

    # Collect known asset tickers from both files BEFORE parsing
    # This allows zero-value entries for known tokens to be flagged for review
    known_assets = _collect_known_asset_tickers(capital_file, income_file)

    # FIFO rebuild for loan-affected assets when PT gate is active
    _fifo_logger = logging.getLogger(__name__)
    fifo_rebuild_active = jurisdiction is not None and jurisdiction.exclude_loan_repayment_gains

    loan_affected_assets: frozenset[str] = frozenset()
    if fifo_rebuild_active:
        loan_affected_assets = discover_loan_affected_assets(
            transaction_history_file, fiat_currency_codes=_get_all_fiat_currency_codes()
        )
        if not loan_affected_assets:
            _fifo_logger.warning(
                "FIFO rebuild active (jurisdiction=%s) but no loan-affected assets discovered. "
                "This may indicate missing or incorrect 'loan'/'loan repayment' tags in Koinly. "
                "Verify your Koinly transaction history has the expected loan tags.",
                jurisdiction.country if jurisdiction else "unknown",
            )

    if capital_file:
        capital_entries, raw_loan_fallback = _parse_capital_gains_file(
            capital_file,
            CapitalGainsParsingContext(
                skipped_assets=skipped_assets,
                origin_resolver=origin_resolver,
                review_entries=review_entries,
                known_assets=known_assets,
                loan_affected_assets=loan_affected_assets,
            ),
        )
    else:
        capital_entries = []
        raw_loan_fallback = []

    if fifo_rebuild_active and loan_affected_assets:
        fifo_entries: list[CryptoCapitalGainEntry] = []
        th_assets: frozenset[str] = frozenset()
        try:
            fifo_entries, th_assets = _rebuild_fifo_for_loan_affected_assets(
                transaction_history_file, origin_resolver, loan_affected_assets, fiscal_year=year,
            )
            capital_entries.extend(fifo_entries)
            assets_with_fifo = {e.asset for e in fifo_entries}
            for asset in loan_affected_assets & th_assets:
                if asset not in assets_with_fifo:
                    _fifo_logger.warning(
                        "FIFO rebuild: %s has zero FIFO entries after rebuild; "
                        "capital gains for this asset will be missing",
                        asset,
                    )
        except (FileProcessingError, ValueError) as fifo_exc:
            _fifo_logger.error(
                "FIFO rebuild failed for loan-affected assets %s: %s. "
                "Falling back to raw Koinly CG rows for these assets — capital gains may include "
                "loan repayment disposals. Fix the Transaction History file and re-run.",
                sorted(loan_affected_assets),
                fifo_exc,
            )
            capital_entries.extend(raw_loan_fallback)

    reward_entries = _parse_income_file(income_file, skipped_assets, known_assets) if income_file else []

    capital_entries = _validate_capital_entries_have_valid_countries(capital_entries, jurisdiction)

    # CRITICAL: OGR override must happen BEFORE _aggregate_capital_entries
    # because CG rows are individual FIFO lots that get summed in aggregation.
    # OGR contains the correct total gain/loss for the disposal event.
    # Overriding after aggregation would lose the lot-level trail.
    if jurisdiction and jurisdiction.use_other_gains_report:
        ogr_index = _find_and_parse_other_gains_file(koinly_dir)
        if ogr_index:
            logging.getLogger(__name__).info(
                "Applying OGR directional authority: %d entries in OGR index",
                len(ogr_index),
            )
            capital_entries = _apply_ogr_direction_override(
                capital_entries, ogr_index, jurisdiction
            )

    capital_entries = _aggregate_capital_entries(capital_entries)
    pre_filter_count = len(capital_entries)
    capital_entries = _filter_immaterial_entries(capital_entries)
    dropped = pre_filter_count - len(capital_entries)
    if dropped > 0:
        logging.getLogger(__name__).warning(
            "Filtered %d sub-1-EUR capital gain entries (PT-C-028); %d entries retained",
            dropped,
            len(capital_entries),
        )

    opening = _parse_holdings_file(
        _find_report_file(koinly_dir, "beginning_of_year_holdings_report"),
        "holdings_opening",
        skipped_assets,
    )
    closing = _parse_holdings_file(
        _find_report_file(koinly_dir, "end_of_year_holdings_report"),
        "holdings_closing",
        skipped_assets,
    )

    short_term_rows = sum(1 for row in capital_entries if row.holding_period.lower().startswith("short"))
    long_term_rows = sum(1 for row in capital_entries if row.holding_period.lower().startswith("long"))
    mixed_rows = sum(1 for row in capital_entries if row.holding_period.lower() == "mixed")
    unknown_rows = sum(1 for row in capital_entries if row.holding_period.lower() == "unknown")

    _recon_logger = logging.getLogger(__name__)
    categorised = short_term_rows + long_term_rows + mixed_rows + unknown_rows
    if categorised != len(capital_entries):
        unclassified = [
            row.holding_period
            for row in capital_entries
            if not row.holding_period.lower().startswith(("short", "long"))
            and row.holding_period.lower() not in ("mixed", "unknown")
        ]
        _recon_logger.warning(
            "Reconciliation mismatch: %d capital entries but only %d categorised by holding period. "
            "Unrecognised holding_period values: %s",
            len(capital_entries),
            categorised,
            sorted(set(unclassified)),
        )

    reconciliation = CryptoReconciliationSummary(
        capital_rows=len(capital_entries),
        reward_rows=len(reward_entries),
        short_term_rows=short_term_rows,
        long_term_rows=long_term_rows,
        mixed_rows=mixed_rows,
        unknown_rows=unknown_rows,
        capital_cost_total_eur=sum((row.cost_eur for row in capital_entries), start=ZERO),
        capital_proceeds_total_eur=sum((row.proceeds_eur for row in capital_entries), start=ZERO),
        capital_gain_total_eur=sum((row.gain_loss_eur for row in capital_entries), start=ZERO),
        reward_total_eur=sum((row.value_eur for row in reward_entries), start=ZERO),
        opening_holdings=opening,
        closing_holdings=closing,
    )

    skipped_zero_value_tokens = [
        CryptoSkippedZeroValueToken(
            source_section=section,
            asset=asset,
            count=data["count"],
            suspicious=data["suspicious"],
        )
        for (section, asset), data in sorted(skipped_assets.items())
    ]

    complete_tax_report_file = _find_report_path(koinly_dir, "complete_tax_report", ".pdf")
    pdf_summary = _parse_complete_tax_report_pdf(complete_tax_report_file) if complete_tax_report_file else None

    capital_gain_stats = CryptoCapitalGainStats.from_entries(capital_entries)
    try:
        loan_activity = _extract_loan_activity(transaction_history_file)
    except (FileProcessingError, ValueError) as exc:
        _logger = logging.getLogger(__name__)
        _logger.warning(
            "Failed to extract loan activity from %s: %s. Continuing without loan data.",
            transaction_history_file,
            exc,
        )
        loan_activity = []

    return CryptoTaxReport(
        tax_year=year,
        capital_entries=capital_entries,
        reward_entries=reward_entries,
        reconciliation=reconciliation,
        capital_gain_stats=capital_gain_stats,
        skipped_zero_value_tokens=skipped_zero_value_tokens,
        loan_activity=loan_activity,
        fifo_rebuild_assets=loan_affected_assets,
        review_entries=review_entries,
        zero_basis_review_threshold=(
            jurisdiction.zero_basis_review_threshold
            if jurisdiction
            else DEFAULT_ZERO_BASIS_REVIEW_THRESHOLD
        ),
        pdf_summary=pdf_summary,
 )





@dataclass(frozen=True)
class CapitalGainsParsingContext:
    """Shared context for capital gains file parsing.

    Groups together the parsing state and dependencies needed by
    _parse_capital_gains_file to improve readability and testability.

    Attributes:
        skipped_assets: Counter for tracking skipped assets by section and ticker.
        origin_resolver: Token origin resolver for acquisition origin annotation.
        review_entries: List to collect review-required entries for the Excel sheet.
        known_assets: Set of asset tickers seen in non-zero rows across all files.
        loan_affected_assets: Set of asset tickers affected by loans (for FIFO rebuild).
    """

    skipped_assets: dict[tuple[str, str], dict]
    origin_resolver: TokenOriginResolver
    review_entries: list[CryptoReviewEntry]
    known_assets: frozenset[str] | None = None
    loan_affected_assets: frozenset[str] = frozenset()


def _parse_capital_gains_file(  # noqa: PLR0912, PLR0915
    path: Path,
    context: CapitalGainsParsingContext,
) -> tuple[list[CryptoCapitalGainEntry], list[CryptoCapitalGainEntry]]:
    """Parse the Koinly capital gains report CSV.

    Returns a tuple of (normal_entries, raw_loan_fallback). normal_entries excludes
    rows for loan-affected assets; raw_loan_fallback contains those rows fully parsed
    with review_required=True. The caller should use raw_loan_fallback only when the
    FIFO rebuild fails, as a degraded-mode substitute for the FIFO-derived entries.

    Args:
        path: Path to the Koinly capital gains report CSV file.
        context: Parsing context with shared state and dependencies.

    Returns:
        Tuple of (normal_entries, raw_loan_fallback).
    """
    rows = read_koinly_rows(path)
    capital_entries: list[CryptoCapitalGainEntry] = []
    raw_loan_fallback: list[CryptoCapitalGainEntry] = []

    logger = logging.getLogger(__name__)
    skipped_loan_affected: Counter[str] = Counter()
    skipped_parse_errors: int = 0

    for row_number, row in enumerate(rows, start=1):
        asset = normalize_asset_ticker(row.get("Asset", ""))
        is_loan_affected = asset in context.loan_affected_assets
        if is_loan_affected:
            skipped_loan_affected[asset] += 1
        try:
            cost_eur = parse_koinly_decimal(row.get("Cost (EUR)", ""))
            proceeds_eur = parse_koinly_decimal(row.get("Proceeds (EUR)", ""))
            gain_loss_eur = parse_koinly_decimal(row.get("Gain / loss", ""))
            amount = parse_koinly_decimal(row.get("Amount", ""))
            disposal_date = format_datetime(parse_koinly_datetime(row.get("Date Sold", "")))
            acquisition_date = format_datetime(parse_koinly_datetime(row.get("Date Acquired", "")))
        except ValueError as exc:
            logger.warning("Skipping capital gains row %d for %r: ambiguous decimal value: %s", row_number, asset, exc)
            skipped_parse_errors += 1
            continue

        # Check for all-zero values (no taxable event)
        # For popular tokens, flag for review instead of skipping - likely Koinly data issue
        is_all_zero = cost_eur == ZERO and proceeds_eur == ZERO and gain_loss_eur == ZERO
        is_suspicious = contains_non_latin_characters(asset)
        is_known_token = asset in _get_popular_crypto_tokens() or _contains_popular_token(asset)

        review_required: bool = False
        review_reason: str = ""
        wallet = row.get("Wallet Name", "").strip()
        platform = normalize_platform_name(wallet)

        if is_all_zero:
            if is_known_token or (context.known_assets and asset in context.known_assets):
                review_reason = "Zero EUR value for known crypto asset - likely Koinly tracking entry or data error"
                if is_suspicious:
                    review_reason = f"{review_reason}; Asset ticker contains non-Latin characters - potential homoglyph scam token"

                context.review_entries.append(
                    CryptoReviewEntry(
                        source_section="capital_gains",
                        date=disposal_date,
                        asset=asset,
                        platform=platform,
                        review_reason=review_reason,
                        is_suspicious=is_suspicious,
                    )
                )
                logger.warning(
                    "Capital gains row %d for %r has all-zero values. Added to review list - "
                    "this may be a Koinly tracking entry or data error.",
                    row_number,
                    asset,
                )
                # Continue to create entry with review_required=True below for traceability
                review_required = True
            else:
                # Unknown token with all-zero values - skip entirely
                _register_skipped_zero_asset(context.skipped_assets, "capital_gains", asset, is_suspicious)
                continue
        operator_origin = resolve_operator_origin(
            platform,
            transaction_type="crypto_disposal",
            transaction_date=disposal_date,
        )
        notes = row.get("Notes", "").strip()
        missing_cost_with_impact = "missing cost basis" in notes.lower()
        review_required = review_required or operator_origin.review_required or missing_cost_with_impact

        review_reason = review_reason or operator_origin.review_reason
        if missing_cost_with_impact:
            cost_basis_reason = "Missing cost basis with tax impact - verify cost calculation"
            review_reason = f"{review_reason}; {cost_basis_reason}" if review_reason else cost_basis_reason

        review_required, review_reason = _build_zero_basis_review_reason(
            cost_eur, proceeds_eur, review_required, review_reason
        )

        # Flag assets with non-Latin characters as potential scam tokens (homoglyph detection)
        if contains_non_latin_characters(asset):
            review_required = True
            scam_reason = f"Asset ticker '{asset}' contains non-Latin characters - potential homoglyph scam token"
            review_reason = f"{review_reason}; {scam_reason}" if review_reason else scam_reason

        holding_period = row.get("Holding period", "").strip() or "Unknown"
        annex_hint = "G1" if holding_period.lower().startswith("long") else "J"

        origin = context.origin_resolver.resolve(acquisition_date, asset, wallet, notes)
        token_origin_str = str(origin)

        entry = CryptoCapitalGainEntry(
            disposal_date=disposal_date,
            acquisition_date=acquisition_date,
            asset=asset,
            amount=amount,
            cost_eur=cost_eur,
            proceeds_eur=proceeds_eur,
            gain_loss_eur=gain_loss_eur,
            holding_period=holding_period,
            wallet=wallet,
            platform=platform,
            chain=_derive_chain(wallet),
            operator_origin=operator_origin,
            annex_hint=annex_hint,
            review_required=review_required,
            review_reason=review_reason,
            notes=notes,
            token_swap_history=token_origin_str,
            multi_acquisition_dates=False,
        )

        if is_loan_affected:
            # Buffer as fallback for when the FIFO rebuild fails.  These rows may
            # include loan repayment disposals and must not reach the report unless
            # the FIFO rebuild is unavailable.
            fallback_reason = (
                "Raw Koinly CG row for loan-affected asset — FIFO rebuild failed; "
                "may include loan repayment disposals. Fix Transaction History and re-run."
            )
            combined_reason = f"{review_reason}; {fallback_reason}" if review_reason else fallback_reason
            raw_loan_fallback.append(replace(entry, review_required=True, review_reason=combined_reason))
        else:
            capital_entries.append(entry)

    if skipped_loan_affected:
        skipped_summary = ", ".join(f"{asset}: {count}" for asset, count in sorted(skipped_loan_affected.items()))
        logger.warning(
            "FIFO rebuild active: buffered %d raw CG row(s) for loan-affected assets %s as FIFO fallback",
            sum(skipped_loan_affected.values()),
            skipped_summary,
        )

    if skipped_parse_errors:
        logger.warning(
            "Skipped %d capital gains row(s) due to ambiguous decimal values; "
            "these disposals are excluded from the report. Check the warnings above for details.",
            skipped_parse_errors,
        )

    return capital_entries, raw_loan_fallback


def _collect_known_asset_tickers(
    capital_file: Path | None, income_file: Path | None
) -> frozenset[str]:
    """Scan Koinly files to collect all asset tickers from non-zero rows.

    Used to identify legitimate crypto assets that have zero-value rewards (likely Koinly data errors).
    Zero-value rewards for known assets are flagged for review instead of being skipped.

    Args:
        capital_file: Koinly capital gains CSV file path.
        income_file: Koinly income CSV file path.

    Returns:
        Frozenset of asset tickers that appear in non-zero rows across both files.

    Raises:
        FileProcessingError: If all provided files fail to parse, preventing silent degradation
            where zero-value rewards for legitimate assets would be incorrectly skipped.
    """
    known_assets: set[str] = set()
    files_to_scan = [f for f in [capital_file, income_file] if f is not None and f.exists()]
    scan_failures: list[tuple[Path, Exception]] = []

    for file_path in files_to_scan:
        try:
            rows = read_koinly_rows(file_path)
            for row in rows:
                asset = normalize_asset_ticker(row.get("Asset", ""))
                if not asset:
                    continue

                # Check if this row has non-zero value (proceeds for gains, value for income)
                if "Proceeds (EUR)" in row:
                    try:
                        proceeds = parse_koinly_decimal(row.get("Proceeds (EUR)", ""))
                        if proceeds > ZERO:
                            known_assets.add(asset)
                    except ValueError:
                        pass  # Skip unparseable rows
                elif "Value (EUR)" in row:
                    try:
                        value = parse_koinly_decimal(row.get("Value (EUR)", ""))
                        if value > ZERO:
                            known_assets.add(asset)
                    except ValueError:
                        pass  # Skip unparseable rows
        except Exception as e:
            scan_failures.append((file_path, e))

    # Fail fast if all provided files failed - silent degradation would skip legitimate zero-value rewards
    if files_to_scan and scan_failures and len(scan_failures) == len(files_to_scan):
        _scan_logger = logging.getLogger(__name__)
        file_list = ", ".join(str(f) for f, _ in scan_failures)
        errors = "; ".join(str(e) for _, e in scan_failures)
        _scan_logger.error(
            "All Koinly files failed to scan for known assets: %s. Errors: %s",
            file_list,
            errors,
        )
        raise FileProcessingError(
            f"Failed to scan all Koinly files for known assets: {file_list}. "
            f"Errors: {errors}. Zero-value rewards for legitimate assets may be incorrectly skipped. "
            "Check file format and content."
        )

    if scan_failures:
        _scan_logger = logging.getLogger(__name__)
        for file_path, error in scan_failures:
            _scan_logger.warning(
                "Failed to scan known assets from %s: %s. Continuing with partial results.",
                file_path,
                error,
            )

    return frozenset(known_assets)


def _parse_income_file(
    path: Path,
    skipped_assets: Counter[tuple[str, str]],
    known_assets: frozenset[str] | None = None,
) -> list[CryptoRewardIncomeEntry]:
    rows = read_koinly_rows(path)
    reward_entries: list[CryptoRewardIncomeEntry] = []
    logger = logging.getLogger(__name__)

    for row_number, row in enumerate(rows, start=1):
        asset = normalize_asset_ticker(row.get("Asset", ""))
        try:
            value_eur = parse_koinly_decimal(row.get("Value (EUR)", ""))
            amount = parse_koinly_decimal(row.get("Amount", ""))
            date_str = format_datetime(parse_koinly_datetime(row.get("Date", "")))
        except ValueError as exc:
            logger.warning("Skipping income row %d for %r: ambiguous decimal value: %s", row_number, asset, exc)
            continue

        wallet = row.get("Wallet Name", "").strip()
        platform = normalize_platform_name(wallet)
        description = row.get("Description", "").strip()

        # Check for zero-value rewards
        if value_eur == ZERO:
            # Check if this is a known legitimate crypto asset with zero value (likely Koinly data error)
            # Uses both exact match and substring matching to catch variants like TSTON, TSUSDE
            is_known = (
                asset in _get_popular_crypto_tokens()
                or _contains_popular_token(asset)
                or (known_assets and asset in known_assets)
            )
            if is_known:
                # Flag for review instead of skipping — known assets shouldn't have zero value
                pass  # Continue to processing below with review flag set
            else:
                _register_skipped_zero_asset(skipped_assets, "income", asset, contains_non_latin_characters(asset))
                continue

        # Classify reward tax status based on asset type (CRG-001, CRG-002)
        # Must be done BEFORE operator origin resolution for platforms that split by fiat/crypto (e.g., Wirex)
        tax_classification = _classify_reward_tax_status(asset)

        # Determine transaction type for operator origin resolution based on asset classification
        # Platforms like Wirex have different operators for fiat vs crypto transactions
        if tax_classification == RewardTaxClassification.TAXABLE_NOW:
            transaction_type = "fiat_deposit"
        else:
            transaction_type = "crypto_deposit"

        operator_origin = resolve_operator_origin(
            platform, transaction_type=transaction_type, transaction_date=date_str
        )

        # Parse foreign tax if present in Koinly report (optional field)
        foreign_tax_eur = ZERO
        review_required = operator_origin.review_required
        review_reason = operator_origin.review_reason
        if "Tax (EUR)" in row or "Foreign Tax" in row:
            tax_field = row.get("Tax (EUR)", "") or row.get("Foreign Tax", "")
            try:
                foreign_tax_eur = parse_koinly_decimal(tax_field)
            except ValueError as exc:
                logger.warning(
                    "Row %d: Could not parse foreign tax for asset %r (value: %s EUR, field value: %r): %s. "
                    "Foreign tax credits will be omitted from this entry. Please verify the Koinly export.",
                    row_number,
                    asset,
                    value_eur,
                    tax_field or "(empty)",
                    exc,
                )
                review_required = True  # Flag for manual review since tax data was lost
                tax_parse_reason = "Foreign tax field could not be parsed - verify tax credit manually"
                review_reason = f"{review_reason}; {tax_parse_reason}" if review_reason else tax_parse_reason

        # Flag assets with non-Latin characters as potential scam tokens (homoglyph detection)
        if contains_non_latin_characters(asset):
            review_required = True
            scam_reason = f"Asset ticker '{asset}' contains non-Latin characters - potential homoglyph scam token"
            review_reason = f"{review_reason}; {scam_reason}" if review_reason else scam_reason

        # Flag zero-value rewards for known legitimate assets (likely Koinly data error)
        if value_eur == ZERO:
            is_known = (
                asset in _get_popular_crypto_tokens()
                or _contains_popular_token(asset)
                or (known_assets and asset in known_assets)
            )
            if is_known:
                review_required = True
                zero_value_reason = "Zero EUR value for known crypto asset - likely Koinly data error or missing price data"
                review_reason = f"{review_reason}; {zero_value_reason}" if review_reason else zero_value_reason

        reward_entries.append(
            CryptoRewardIncomeEntry(
                date=date_str,
                asset=asset,
                amount=amount,
                value_eur=value_eur,
                income_label="Reward",
                source_type=row.get("Type", "").strip(),
                wallet=wallet,
                platform=platform,
                chain=_derive_chain(wallet),
                operator_origin=operator_origin,
                annex_hint="J",
                review_required=review_required,
                review_reason=review_reason,
                description=description,
                tax_classification=tax_classification,
                foreign_tax_eur=foreign_tax_eur,
            )
        )

    return reward_entries


def _parse_holdings_file(
    path: Path | None, source_section: str, skipped_assets: Counter[tuple[str, str]]
) -> HoldingsSnapshot | None:
    if path is None:
        return None

    rows = read_koinly_rows(path)
    logger = logging.getLogger(__name__)
    asset_rows = 0
    total_cost_eur = ZERO
    total_value_eur = ZERO

    for row in rows:
        asset = normalize_asset_ticker(row.get("Asset", ""))
        try:
            value_eur = parse_koinly_decimal(row.get("Value (EUR)", ""))
            cost_eur = parse_koinly_decimal(row.get("Cost (EUR)", ""))
        except ValueError as exc:
            logger.warning("Skipping holdings row for %r: ambiguous decimal value: %s", asset, exc)
            continue
        if value_eur == ZERO:
            _register_skipped_zero_asset(skipped_assets, source_section, asset, contains_non_latin_characters(asset))
            continue
        asset_rows += 1
        total_cost_eur += cost_eur
        total_value_eur += value_eur

    return HoldingsSnapshot(
        asset_rows=asset_rows,
        total_cost_eur=total_cost_eur,
        total_value_eur=total_value_eur,
    )

