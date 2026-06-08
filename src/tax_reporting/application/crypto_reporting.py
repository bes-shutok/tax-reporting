"""Crypto tax reporting helpers for Koinly exports."""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Final, TypedDict

import pycountry

from ..domain.constants import LOAN_STATUS_OVERPAID
from ..domain.crypto_fifo import AssetFifoResult, CryptoFifoRealization
from ..domain.exceptions import FileProcessingError
from ..infrastructure.config import DEFAULT_ZERO_BASIS_REVIEW_THRESHOLD, TaxJurisdictionConfig
from ..infrastructure.koinly_parser import (
    contains_non_latin_characters,
    format_datetime,
    normalize_asset_ticker,
    normalize_platform_name,
    parse_koinly_datetime,
    parse_koinly_decimal,
    read_koinly_rows,
)
from .crypto_fifo import (
    MergedAssetFifoResult,
    compute_fifo_for_asset,
    discover_loan_affected_assets,
    parse_th_for_loan_affected_assets,
    resolve_cross_asset_exchanges,
)
from .crypto_fifo.cross_asset import _build_cross_asset_order
from .crypto_fifo.transfer import _order_platforms_for_transfers, _resolve_intra_asset_transfers
from .token_origin import TokenOriginResolver

# Constants for decimal calculations
ZERO: Final = Decimal("0")
_MATERIALITY_THRESHOLD: Final = Decimal("1")


# Validation error display constants
_MAX_VALIDATION_ERROR_DISPLAY: Final = 5
# Ticker stripping constants
_MAX_TICKER_LENGTH: Final = 10
_SPLIT_PARTS_WITH_TICKER: Final = 2

# Constants for date validation
_MIN_VALID_YEAR: Final = 2009  # Bitcoin genesis, crypto didn't exist before
_MAX_VALID_YEAR: Final = 2100
_ISO_DATE_LENGTH: Final = 10
_ISO_DATE_PARTS: Final = 3  # YYYY-MM-DD has 3 parts
_YEAR_DIGITS: Final = 4
_MONTH_DAY_DIGITS: Final = 2

# Constants for time validation
_DATETIME_SPACE_PARTS: Final = 2  # Date and time separated by space
_TIME_COMPONENTS: Final = 3  # HH:MM:SS has 3 parts
_TIME_PART_DIGITS: Final = 2
_MAX_HOUR: Final = 23
_MAX_MINUTE_SECOND: Final = 59


def _validate_iso_date(date_str: str) -> str:
    """Validate an ISO date string (YYYY-MM-DD) and return it.

    Args:
        date_str: Date string in ISO format (YYYY-MM-DD).

    Returns:
        The validated date string.

    Raises:
        ValueError: If the date is invalid or out of reasonable range.
    """
    parts = date_str.split("-")
    if len(parts) != _ISO_DATE_PARTS:
        raise ValueError(f"Invalid date format '{date_str}': expected YYYY-MM-DD")
    year_str, month_str, day_str = parts

    # Verify zero-padding: YYYY-MM-DD requires exactly 4, 2, 2 digits
    if len(year_str) != _YEAR_DIGITS or len(month_str) != _MONTH_DAY_DIGITS or len(day_str) != _MONTH_DAY_DIGITS:
        raise ValueError(f"Invalid date format '{date_str}': zero-padding required (YYYY-MM-DD)")

    # Verify all parts are numeric
    if not (year_str.isdigit() and month_str.isdigit() and day_str.isdigit()):
        raise ValueError(f"Invalid date format '{date_str}': non-numeric characters")

    year, month, day = int(year_str), int(month_str), int(day_str)
    if year < _MIN_VALID_YEAR or year > _MAX_VALID_YEAR:
        raise ValueError(
            f"Invalid date '{date_str}': year {year} out of reasonable range "
            f"[{_MIN_VALID_YEAR}, {_MAX_VALID_YEAR}]"
        )
    try:
        date(year, month, day)  # Validates calendar date (rejects Feb 31, etc.)
        return date_str
    except ValueError as e:
        raise ValueError(f"Invalid date '{date_str}': {e}") from e


class RewardTaxClassification(Enum):
    """Tax classification status for crypto rewards per Portuguese law (CRG-001, CRG-002).

    taxable_now: Reward is immediately taxable as Category E income (remuneration not in crypto form).
    deferred_by_law: Reward received as cryptoassets, taxation deferred until disposal (CIRS art. 5(11)).
    """

    TAXABLE_NOW = "taxable_now"
    DEFERRED_BY_LAW = "deferred_by_law"


@dataclass(frozen=True)
class OperatorOrigin:
    """Operator and jurisdiction metadata for a wallet platform.

    Temporal validity tracking allows historical tax filings to reference the
    mapping that was in effect at the time of transaction, even if the mapping
    changes later (e.g., operator restructuring, legal domicile changes).

    Temporal Fields:
        service_start_date: When the platform actually started offering this service.
            Used for transaction date matching to avoid false positives on historical data.
        valid_from: When this specific mapping was verified from source documents.
            Used for audit trail and documentation purposes.
        valid_until: When this mapping expires (if applicable).

    Platform Assumptions:
        platform_assumption: Platform-level verification note (e.g., "verify account region").
            These are displayed in a separate Platform Assumptions sheet, not on individual rows.
        platform_review_required: Whether this platform requires manual review before filing.
            Displayed on the Platform Assumptions sheet. Distinct from row-level review_required,
            which is only set for per-transaction issues (temporal validity failures, unknown
            platforms). Set this True when the operator entity or jurisdiction is uncertain at
            the platform level regardless of the individual transaction.
    """

    platform: str
    service_scope: str
    operator_entity: str
    operator_country: str
    source_url: str
    source_checked_on: str
    confidence: str
    review_required: bool
    review_reason: str | None = None
    platform_assumption: str | None = None
    platform_review_required: bool = False
    service_start_date: str | None = None
    valid_from: str | None = None
    valid_until: str | None = None

    def __post_init__(self) -> None:
        """Validate temporal validity fields."""
        # Normalize empty strings to None for temporal fields
        normalized_service_start = (
            self.service_start_date.strip()
            if isinstance(self.service_start_date, str) and self.service_start_date.strip()
            else None
        )
        normalized_from = (
            self.valid_from.strip() if isinstance(self.valid_from, str) and self.valid_from.strip() else None
        )
        normalized_until = (
            self.valid_until.strip() if isinstance(self.valid_until, str) and self.valid_until.strip() else None
        )

        # Validate ISO date format for service_start_date if provided
        if normalized_service_start is not None:
            _validate_iso_date(normalized_service_start)

        # Validate ISO date format for valid_from if provided
        if normalized_from is not None:
            _validate_iso_date(normalized_from)

        # Validate ISO date format for valid_until if provided
        if normalized_until is not None:
            _validate_iso_date(normalized_until)

        # Validate that service_start_date <= valid_from if both are provided
        if normalized_service_start is not None and normalized_from is not None:
            service_date = datetime.fromisoformat(normalized_service_start).date()
            from_date = datetime.fromisoformat(normalized_from).date()
            if service_date > from_date:
                raise ValueError(
                    f"Invalid date range for {self.platform}: service_start_date ({normalized_service_start}) "
                    f"must be on or before valid_from ({normalized_from})"
                )

        # Validate that service_start_date <= valid_until if both are provided
        if normalized_service_start is not None and normalized_until is not None:
            service_date = datetime.fromisoformat(normalized_service_start).date()
            until_date = datetime.fromisoformat(normalized_until).date()
            if service_date > until_date:
                raise ValueError(
                    f"Invalid date range for {self.platform}: service_start_date ({normalized_service_start}) "
                    f"must be on or before valid_until ({normalized_until})"
                )

        # Validate that valid_until >= valid_from if both are provided
        if normalized_from is not None and normalized_until is not None:
            from_date = datetime.fromisoformat(normalized_from).date()
            until_date = datetime.fromisoformat(normalized_until).date()
            if until_date < from_date:
                raise ValueError(
                    f"Invalid date range for {self.platform}: valid_until ({normalized_until}) "
                    f"must be on or after valid_from ({normalized_from})"
                )

        # Validate review_reason is set when review_required is True
        if self.review_required and not self.review_reason:
            raise ValueError("review_reason must be set when review_required=True")

        # Assign normalized values back to frozen dataclass
        object.__setattr__(self, "service_start_date", normalized_service_start)
        object.__setattr__(self, "valid_from", normalized_from)
        object.__setattr__(self, "valid_until", normalized_until)


@dataclass(frozen=True)
class CapitalGainPeriodStats:
    """Per-holding-period capital gain statistics for the statistics section.

    Summarises count, cost, proceeds, and gain/loss for one holding-period bucket.
    Construct via ``from_entries()`` to aggregate from ``CryptoCapitalGainEntry`` rows.
    """

    count: int
    cost_total_eur: Decimal
    proceeds_total_eur: Decimal
    gain_loss_total_eur: Decimal

    @classmethod
    def from_entries(cls, entries: list[CryptoCapitalGainEntry]) -> CapitalGainPeriodStats:
        """Aggregate a list of capital gain entries into period statistics.

        Args:
            entries: Capital gain entries all belonging to the same holding period.

        Returns:
            CapitalGainPeriodStats with summed totals and entry count.
        """
        return cls(
            count=len(entries),
            cost_total_eur=sum((e.cost_eur for e in entries), start=ZERO),
            proceeds_total_eur=sum((e.proceeds_eur for e in entries), start=ZERO),
            gain_loss_total_eur=sum((e.gain_loss_eur for e in entries), start=ZERO),
        )


@dataclass(frozen=True)
class CryptoCapitalGainStats:
    """Aggregate capital gain statistics across all holding periods.

    Provides per-period breakdowns (short-term, long-term, mixed, unknown) and
    a grand total row for the CAPITAL GAINS STATISTICS Excel section.
    Construct via ``from_entries()`` to group ``CryptoCapitalGainEntry`` rows
    by holding period and delegate to ``CapitalGainPeriodStats.from_entries()``.
    """

    short_term: CapitalGainPeriodStats
    long_term: CapitalGainPeriodStats
    mixed: CapitalGainPeriodStats
    unknown: CapitalGainPeriodStats
    grand_total: CapitalGainPeriodStats

    @classmethod
    def from_entries(cls, entries: list[CryptoCapitalGainEntry]) -> CryptoCapitalGainStats:
        """Group entries by holding period and compute per-period plus grand-total stats.

        Args:
            entries: Capital gain entries (post-aggregation, post-materiality-filter).

        Returns:
            CryptoCapitalGainStats with per-period breakdowns and grand total.
        """
        short_term = [e for e in entries if e.holding_period.lower().startswith("short")]
        long_term = [e for e in entries if e.holding_period.lower().startswith("long")]
        mixed = [e for e in entries if e.holding_period.lower() == "mixed"]
        unknown = [e for e in entries if e.holding_period.lower() == "unknown"]

        logger = logging.getLogger(__name__)
        categorised_count = len(short_term) + len(long_term) + len(mixed) + len(unknown)
        if categorised_count != len(entries):
            unclassified = {
                e.holding_period
                for e in entries
                if not e.holding_period.lower().startswith(("short", "long"))
                and e.holding_period.lower() not in ("mixed", "unknown")
            }
            logger.warning(
                "Capital gain stats: %d entries but only %d categorised by holding period. "
                "Unrecognised values: %s",
                len(entries),
                categorised_count,
                sorted(unclassified),
            )

        st = CapitalGainPeriodStats.from_entries(short_term)
        lt = CapitalGainPeriodStats.from_entries(long_term)
        mx = CapitalGainPeriodStats.from_entries(mixed)
        uk = CapitalGainPeriodStats.from_entries(unknown)

        grand_total = CapitalGainPeriodStats(
            count=len(entries),
            cost_total_eur=sum((e.cost_eur for e in entries), start=ZERO),
            proceeds_total_eur=sum((e.proceeds_eur for e in entries), start=ZERO),
            gain_loss_total_eur=sum((e.gain_loss_eur for e in entries), start=ZERO),
        )

        return cls(short_term=st, long_term=lt, mixed=mx, unknown=uk, grand_total=grand_total)


@dataclass(frozen=True)
class CryptoCapitalGainEntry:
    """Single taxable crypto disposal row for reporting."""

    disposal_date: str
    acquisition_date: str
    asset: str
    amount: Decimal
    cost_eur: Decimal
    proceeds_eur: Decimal
    gain_loss_eur: Decimal
    holding_period: str
    wallet: str
    platform: str
    chain: str
    operator_origin: OperatorOrigin
    annex_hint: str
    review_required: bool
    notes: str
    review_reason: str | None = None
    token_swap_history: str = ""
    # Set during aggregation when the entry combines FIFO lots from multiple
    # acquisition dates. Triggers blue fill in Excel output. See PT-C-027.
    multi_acquisition_dates: bool = False

    def __post_init__(self) -> None:
        """Validate review_reason is provided when review_required is True."""
        if self.review_required and not self.review_reason:
            raise ValueError("review_reason must be set when review_required=True")


@dataclass(frozen=True)
class LoanActivityEntry:
    """Per-asset loan activity summary for the Loan Activity sheet."""

    asset: str
    received_count: int
    received_amount: Decimal
    received_value_eur: Decimal
    repaid_count: int
    repaid_amount: Decimal
    repaid_value_eur: Decimal
    balance_amount: Decimal
    balance_status: str


@dataclass(frozen=True)
class CryptoRewardIncomeEntry:
    """Single crypto income/reward row for reporting."""

    date: str
    asset: str
    amount: Decimal
    value_eur: Decimal
    income_label: str
    source_type: str
    wallet: str
    platform: str
    chain: str
    operator_origin: OperatorOrigin
    annex_hint: str
    review_required: bool
    description: str
    review_reason: str | None = None
    tax_classification: RewardTaxClassification = RewardTaxClassification.DEFERRED_BY_LAW
    foreign_tax_eur: Decimal = ZERO

    def __post_init__(self) -> None:
        """Validate review_reason is provided when review_required is True."""
        if self.review_required and not self.review_reason:
            raise ValueError("review_reason must be set when review_required=True")


@dataclass(frozen=True)
class AggregatedRewardIncomeEntry:
    """Aggregated reward income for IRS filing (Anexo J Quadro 8A).

    Represents one line in the filing-ready rewards table after aggregation
    by income_code + source_country. Only includes rewards classified as taxable_now.

    Attributes:
        income_code: Tabela V income code for the reward type (e.g., "401" for crypto capital income).
        source_country: Tabela X country code where the income originated (from operator entity).
        gross_income_eur: Sum of all EUR values for this aggregation key.
        foreign_tax_eur: Sum of all foreign taxes paid (if any).
        raw_row_count: Number of original Koinly rows aggregated into this entry.
        chains: Sorted list of unique blockchain names contributing to this aggregated entry.
        description: Human-readable description of the aggregated income type.
    """

    income_code: str
    source_country: str
    gross_income_eur: Decimal
    foreign_tax_eur: Decimal
    raw_row_count: int
    chains: tuple[str, ...]
    description: str


@dataclass(frozen=True)
class HoldingsSnapshot:
    """Holdings totals for reconciliation."""

    asset_rows: int
    total_cost_eur: Decimal
    total_value_eur: Decimal


@dataclass(frozen=True)
class CryptoReconciliationSummary:
    """Control totals for capital and income sections.

    Note: capital_rows counts aggregated capital gain entries only.
    """

    capital_rows: int
    reward_rows: int
    short_term_rows: int
    long_term_rows: int
    mixed_rows: int
    unknown_rows: int
    capital_cost_total_eur: Decimal
    capital_proceeds_total_eur: Decimal
    capital_gain_total_eur: Decimal
    reward_total_eur: Decimal
    opening_holdings: HoldingsSnapshot | None
    closing_holdings: HoldingsSnapshot | None


@dataclass(frozen=True)
class CryptoSkippedZeroValueToken:
    """Asset skipped from report output because value is zero."""

    source_section: str
    asset: str
    count: int
    suspicious: bool = False  # True if asset contains non-Latin characters (potential homoglyph scam token)


@dataclass(frozen=True)
class CryptoCompletePdfSummary:
    """Extracted metadata from Koinly complete tax report PDF."""

    period: str | None
    timezone: str | None
    extracted_tokens: int


@dataclass
class CryptoReviewEntry:
    """Entry requiring manual review."""

    source_section: str  # "capital_gains" or "income"
    date: str
    asset: str
    platform: str
    review_reason: str
    is_suspicious: bool = False


@dataclass
class CryptoTaxReport:
    """Normalized crypto dataset ready for Excel rendering."""

    tax_year: int
    capital_entries: list[CryptoCapitalGainEntry]
    reward_entries: list[CryptoRewardIncomeEntry]
    reconciliation: CryptoReconciliationSummary
    capital_gain_stats: CryptoCapitalGainStats
    skipped_zero_value_tokens: list[CryptoSkippedZeroValueToken] = field(default_factory=list)
    loan_activity: list[LoanActivityEntry] = field(default_factory=list)
    fifo_rebuild_assets: frozenset[str] = field(default_factory=frozenset)
    zero_basis_review_threshold: Decimal = field(default_factory=lambda: DEFAULT_ZERO_BASIS_REVIEW_THRESHOLD)
    pdf_summary: CryptoCompletePdfSummary | None = None
    review_entries: list[CryptoReviewEntry] = field(default_factory=list)


# Crypto tokens that share tickers with ISO 4217 fiat currency codes.
# These are known cryptoassets that should be classified as deferred by law (CRG-001),
# even though their ticker collides with a fiat currency code.
_CRYPTO_TOKEN_FIAT_COLLISIONS: Final[frozenset[str]] = frozenset(
    (
        "GEL",  # Gelato Network token (fiat GEL = Georgian Lari)
        "MNT",  # Mantle token (fiat MNT = Mongolian tögrög)
    )
)

# Popular/known crypto tokens that should not have zero value in rewards.
# If a reward for one of these tokens has zero value, it's likely a Koinly data error
# (missing price data, export issue) and should be flagged for review instead of skipped.
# Loaded from docs/tax/popular_crypto_tokens.json to allow maintenance without code changes.
_POPULAR_CRYPTO_TOKENS_FILE = Path(__file__).parent.parent.parent / "docs" / "tax" / "popular_crypto_tokens.json"


@lru_cache(maxsize=1)
def _load_popular_crypto_tokens() -> frozenset[str]:
    """Load popular crypto tokens from the external JSON file.

    Returns:
        Frozenset of popular crypto asset tickers. Returns empty frozenset if file
        is not found (logs warning and degrades gracefully).

    The file is cached after first load.

    Raises:
        FileProcessingError: If file is a symlink, exceeds size limit, or has invalid structure.
    """
    tokens: set[str] = set()
    logger = logging.getLogger(__name__)

    # Security check: reject symlinks
    if _POPULAR_CRYPTO_TOKENS_FILE.is_symlink():
        raise FileProcessingError(
            f"Popular crypto tokens file at {_POPULAR_CRYPTO_TOKENS_FILE} is a symlink — "
            "only regular files are accepted for security"
        )

    if not _POPULAR_CRYPTO_TOKENS_FILE.exists():
        logger.warning(
            "Popular crypto tokens file not found at %s. Zero-value rewards for known assets "
            "may not be flagged for review. Using empty token set.",
            _POPULAR_CRYPTO_TOKENS_FILE,
        )
        return frozenset()

    # Security check: file size validation (max 1MB for token list JSON)
    max_token_file_size = 1 * 1024 * 1024  # 1MB
    try:
        file_size = _POPULAR_CRYPTO_TOKENS_FILE.stat().st_size
        if file_size > max_token_file_size:
            raise FileProcessingError(
                f"Popular crypto tokens file exceeds size limit ({file_size} bytes, "
                f"max {max_token_file_size} bytes): {_POPULAR_CRYPTO_TOKENS_FILE}"
            )
    except OSError as e:
        logger.warning(
            "Could not stat popular crypto tokens file %s: %s. Using empty token set.",
            _POPULAR_CRYPTO_TOKENS_FILE,
            e,
        )
        return frozenset()

    try:
        with open(_POPULAR_CRYPTO_TOKENS_FILE, encoding="utf-8") as f:
            data = json.load(f)

        # Validate JSON structure
        if not isinstance(data, dict):
            raise FileProcessingError(
                f"Popular crypto tokens file must contain a JSON object, got {type(data).__name__}: "
                f"{_POPULAR_CRYPTO_TOKENS_FILE}"
            )

        if "tokens" not in data:
            raise FileProcessingError(
                f"Popular crypto tokens file must contain a 'tokens' key: {_POPULAR_CRYPTO_TOKENS_FILE}"
            )

        tokens_obj = data["tokens"]
        if not isinstance(tokens_obj, dict):
            raise FileProcessingError(
                f"Popular crypto tokens 'tokens' value must be an object, got {type(tokens_obj).__name__}: "
                f"{_POPULAR_CRYPTO_TOKENS_FILE}"
            )

        for category_tokens in tokens_obj.values():
            if isinstance(category_tokens, list):
                tokens.update(category_tokens)

        logger.debug("Loaded %d popular crypto tokens from %s", len(tokens), _POPULAR_CRYPTO_TOKENS_FILE)
        return frozenset(tokens)
    except (json.JSONDecodeError, OSError, AttributeError) as e:
        logger.warning(
            "Failed to load popular crypto tokens from %s: %s. Using empty token set. "
            "Zero-value rewards for known assets may not be flagged for review.",
            _POPULAR_CRYPTO_TOKENS_FILE,
            e,
        )
        return frozenset()


# Cached accessor for popular tokens
def _get_popular_crypto_tokens() -> frozenset[str]:
    """Get the cached popular crypto tokens frozenset."""
    return _load_popular_crypto_tokens()


def _contains_popular_token(asset: str) -> bool:
    """Check if an asset ticker contains a popular crypto token as a substring.

    This catches Koinly-specific naming variants like:
    - TSTON (contains "TON")
    - TSUSDE (contains "USDE")
    - STAKED_* (if wrapped around a popular token)

    Tradeoff: Substring matching may cause false positives for tickers that
    coincidentally contain popular token names as substrings (e.g., "MATICAL"
    matches "MATIC", "SOLANA" matches "SOL"). This is acceptable because the
    consequence is merely flagging for review rather than incorrectly skipping
    a legitimate zero-value reward.

    Args:
        asset: The asset ticker to check.

    Returns:
        True if the asset contains any popular token as a substring (case-insensitive).
    """
    asset_upper = asset.upper()
    for token in _get_popular_crypto_tokens():
        if token in asset_upper:
            return True
    return False


def _parse_transaction_date(transaction_date: str | None) -> str | None:
    """Parse transaction date to ISO date format (YYYY-MM-DD) for temporal validity checks.

    Args:
        transaction_date: Transaction date string in one of the following formats:
            - "YYYY-MM-DD HH:MM:SS" (Koinly format)
            - "YYYY-MM-DD" (ISO date)

    Returns:
        ISO date string (YYYY-MM-DD) or None if input is empty/None.

    Raises:
        ValueError: If the date format is invalid.
    """
    if not transaction_date:
        return None

    # Strip leading/trailing whitespace
    transaction_date = transaction_date.strip()

    # Handle Koinly format: "YYYY-MM-DD HH:MM:SS"
    if " " in transaction_date:
        parts = transaction_date.split(" ")
        if len(parts) != _DATETIME_SPACE_PARTS:
            raise ValueError(f"Unsupported transaction date format: {transaction_date}")
        date_part, time_part = parts
        # Validate time part matches HH:MM:SS pattern with valid ranges
        time_components = time_part.split(":")
        if len(time_components) != _TIME_COMPONENTS:
            raise ValueError(f"Unsupported transaction date format: {transaction_date}")
        # Verify all time parts are digits AND zero-padded (exactly 2 digits each)
        if not all(cp.isdigit() and len(cp) == _TIME_PART_DIGITS for cp in time_components):
            raise ValueError(f"Unsupported transaction date format: {transaction_date}")
        # Validate time ranges: hour (0-23), minute (0-59), second (0-59)
        hour, minute, second = map(int, time_components)
        if not (0 <= hour <= _MAX_HOUR and 0 <= minute <= _MAX_MINUTE_SECOND and 0 <= second <= _MAX_MINUTE_SECOND):
            raise ValueError(f"Unsupported transaction date format: {transaction_date}")
        return _validate_iso_date(date_part)

    # Already in YYYY-MM-DD format
    if len(transaction_date) == _ISO_DATE_LENGTH and transaction_date[4] == "-" and transaction_date[7] == "-":
        return _validate_iso_date(transaction_date)

    raise ValueError(f"Unsupported transaction date format: {transaction_date}")


def _is_temporally_valid(service_start_date: str | None, valid_until: str | None, transaction_date: str) -> bool:
    """Check if a mapping is valid for a given transaction date.

    Args:
        service_start_date: ISO date when the platform service started (YYYY-MM-DD).
            Used for transaction matching, not verification date.
        valid_until: ISO date when mapping expires (YYYY-MM-DD), or None if still valid.
        transaction_date: ISO transaction date to check (YYYY-MM-DD).

    Returns:
        True if the mapping was valid on the transaction date.

    Note:
        This function uses service_start_date for transaction date matching to avoid
        false positives on historical data. The valid_from field is preserved for
        audit trail but NOT used for temporal validation (it represents verification
        date, not service availability).
    """
    # Parse transaction date once for comparison
    # Date is already validated by _parse_transaction_date, so fromisoformat is safe
    tx_date = datetime.fromisoformat(transaction_date).date()

    # If service_start_date is specified (and not empty), check if transaction is on or after it
    if service_start_date:
        from_date = datetime.fromisoformat(service_start_date).date()
        if tx_date < from_date:
            return False

    # If valid_until is specified (and not empty), check if transaction is on or before it
    if valid_until:
        until_date = datetime.fromisoformat(valid_until).date()
        if tx_date > until_date:
            return False

    # No constraints violated, or no constraints at all
    return True


@lru_cache(maxsize=1)
def _get_all_fiat_currency_codes() -> frozenset[str]:
    """Get all ISO 4217 fiat currency codes using pycountry.

    Returns:
        A frozenset of all ISO 4217 currency alphabetic codes.

    This function uses pycountry to retrieve the complete list of official
    fiat currency codes, ensuring comprehensive coverage rather than relying
    on a hand-maintained allowlist. The result is cached for performance.

    Note: Excludes ISO 4217 codes that are NOT fiat currencies for tax purposes:
    - Commodities: XAG (Silver), XAU (Gold), XPD (Palladium), XPT (Platinum)
    - Special units: XBA, XBB, XBC, XBD (bond market units), XDR (SDR),
      XSU (Sucre), XUA (ADB Unit of Account)
    - Placeholders: XXX (no currency), XTS (testing)
    Only actual government-issued fiat currencies are included.
    """
    # ISO 4217 codes that are NOT fiat currencies for tax purposes.
    # These are commodities, special drawing rights, testing codes, or fund/unit codes.
    # Per CRG-002, only fiat-denominated rewards are immediately taxable.
    non_fiat_iso_codes = frozenset(
        {
            # Commodities
            "XAG",  # Silver (commodity)
            "XAU",  # Gold (commodity)
            "XPD",  # Palladium (commodity)
            "XPT",  # Platinum (commodity)
            # Bond market units and special drawing rights
            "XBA",  # Bond Markets Unit European Composite Unit
            "XBB",  # Bond Markets Unit European Monetary Unit
            "XBC",  # Bond Markets Unit European Unit of Account 9
            "XBD",  # Bond Markets Unit European Unit of Account 17
            "XDR",  # SDR (Special Drawing Right)
            "XSU",  # Sucre
            "XUA",  # ADB Unit of Account
            # Testing and placeholder codes
            "XTS",  # Testing code
            "XXX",  # No currency involved
            # Fund and unit codes (not ordinary government-issued fiat)
            "BOV",  # Bolivian Mvdol (funds code)
            "CHE",  # WIR Euro (complementary currency, issued by WIR Bank)
            "CHW",  # WIR Franc (complementary currency, issued by WIR Bank)
            "CLF",  # Unidad de Fomento (unit of account)
            "COU",  # Unidad de Valor Real (UVR) (funds code)
            "MXV",  # Mexican Unidad de Inversion (UDI) (unit of account)
            "USN",  # United States dollar (next day) (funds code)
            "UYI",  # Uruguay Peso en Unidades Indexadas (UI) (indexed unit)
            "UYW",  # Unidad previsional (indexed unit)
        }
    )

    return frozenset(c.alpha_3 for c in pycountry.currencies if c.alpha_3 not in non_fiat_iso_codes)


def _classify_reward_tax_status(asset: str) -> RewardTaxClassification:
    """Classify a crypto reward as taxable now or deferred by law (CRG-001, CRG-002).

    Classification rules:
    - Fiat-denominated rewards (asset is a fiat currency code) are immediately taxable as
      Category E income because the remuneration does not assume the form of cryptoassets.
    - Crypto-denominated rewards (all other assets) are deferred until disposal under
      CIRS art. 5(11) for non-securities and deferral rules for crypto-to-crypto swaps.

    Ticker collision handling: Some crypto tokens share tickers with ISO 4217 fiat currency
    codes (e.g., GEL = Gelato token vs Georgian Lari fiat). Known collisions are checked
    first to ensure correct tax treatment per CRG-001.

    Args:
        asset: The asset ticker from the reward row (e.g., "USDT", "EUR", "BTC", "GEL").

    Returns:
        RewardTaxClassification.TAXABLE_NOW for fiat-denominated rewards.
        RewardTaxClassification.DEFERRED_BY_LAW for crypto-denominated rewards.
    """
    asset_upper = asset.strip().upper()

    # Known crypto tokens that collide with fiat codes are always deferred (CRG-001)
    if asset_upper in _CRYPTO_TOKEN_FIAT_COLLISIONS:
        return RewardTaxClassification.DEFERRED_BY_LAW

    # Fiat currency rewards are immediately taxable (CRG-002)
    # Use pycountry to get all ISO 4217 codes, ensuring comprehensive coverage
    if asset_upper in _get_all_fiat_currency_codes():
        return RewardTaxClassification.TAXABLE_NOW

    # All crypto-denominated rewards are deferred by law (CRG-001)
    # This includes stablecoins like USDT, USDC which are treated as cryptoassets per PT-C-003
    return RewardTaxClassification.DEFERRED_BY_LAW


def _resolve_income_code(koinly_type: str) -> str:
    """Map Koinly income type to Portuguese Tabela V income code for Anexo J filing.

    Args:
        koinly_type: The type field from Koinly income report (e.g., "staking", "airdrop").

    Returns:
        Tabela V income code (e.g., "401" for crypto capital income).
        Defaults to "401" for unknown types (crypto capital income catch-all).
    """
    normalized_type = koinly_type.strip().lower()
    return _KOINLY_TYPE_TO_INCOME_CODE.get(normalized_type, "401")


def _is_valid_tabela_x_country(country: str) -> bool:
    """Check if a country code is a valid Portuguese Tabela X country code.

    Args:
        country: Country code to validate (e.g., "US", "IE", "MT").

    Returns:
        True if the country code is in the official Tabela X list.
    """
    return country.upper() in _TABELA_X_COUNTRY_CODES


def aggregate_taxable_rewards(
    reward_entries: list[CryptoRewardIncomeEntry],
) -> list[AggregatedRewardIncomeEntry]:
    """Aggregate taxable_now reward entries by income_code + source_country for IRS filing.

    This function:
    1. Filters to only taxable_now rewards (deferred_by_law rewards are excluded)
    2. Groups by (income_code, source_country)
    3. Sums gross_income_eur and foreign_tax_eur within each group
    4. Preserves raw_row_count for reconciliation trail
    5. Validates that all mandatory IRS fields are present

    Args:
        reward_entries: All parsed reward entries from Koinly income report.

    Returns:
        List of aggregated reward entries ready for IRS filing.

    Raises:
        FileProcessingError: If a taxable_now row cannot be assigned valid Tabela X country.
    """
    logger = logging.getLogger(__name__)

    # Filter to only immediately taxable rewards
    taxable_entries = [e for e in reward_entries if e.tax_classification == RewardTaxClassification.TAXABLE_NOW]

    if not taxable_entries:
        return []

    # Validate that all taxable entries have valid Tabela X country codes before aggregation.
    # This ensures the IRS-ready filing table never contains entries with missing mandatory fields.
    for entry in taxable_entries:
        source_country = entry.operator_origin.operator_country
        # Check for UNKNOWN country first (platform not mapped)
        if source_country == "UNKNOWN":
            raise FileProcessingError(
                f"Immediately taxable reward from wallet '{entry.wallet}' (asset: {entry.asset}, "
                f"value: {entry.value_eur} EUR) has an unresolved platform/operator. "
                f"The platform '{entry.platform}' is not mapped in resolve_operator_origin(). "
                f"Please add a platform mapping with operator_country to resolve this entry."
            )
        if not _is_valid_tabela_x_country(source_country):
            raise FileProcessingError(
                f"Immediately taxable reward from wallet '{entry.wallet}' (asset: {entry.asset}, "
                f"value: {entry.value_eur} EUR) cannot be assigned a valid Tabela X country code. "
                f"Resolved country: '{source_country}'. Please add a valid country mapping "
                f"for this platform/operator in resolve_operator_origin()."
            )

    # Aggregate by (income_code, source_country)
    class _RewardGroup(TypedDict):
        entries: list[CryptoRewardIncomeEntry]
        gross_income: Decimal
        foreign_tax: Decimal
        chains: set[str]

    groups: dict[tuple[str, str], _RewardGroup] = {}
    for entry in taxable_entries:
        income_code = _resolve_income_code(entry.source_type)
        source_country = entry.operator_origin.operator_country.upper()
        key = (income_code, source_country)

        if key not in groups:
            groups[key] = {
                "entries": [],
                "gross_income": ZERO,
                "foreign_tax": ZERO,
                "chains": set(),
            }

        groups[key]["entries"].append(entry)
        groups[key]["gross_income"] += entry.value_eur
        groups[key]["foreign_tax"] += entry.foreign_tax_eur
        groups[key]["chains"].add(entry.chain)

    # Build aggregated entries
    aggregated = []
    for (income_code, source_country), data in sorted(groups.items()):
        entries = data["entries"]
        chains_tuple = tuple(sorted(data["chains"]))
        aggregated.append(
            AggregatedRewardIncomeEntry(
                income_code=income_code,
                source_country=source_country,
                gross_income_eur=data["gross_income"],
                foreign_tax_eur=data["foreign_tax"],
                raw_row_count=len(entries),
                chains=chains_tuple,
                description=f"Income code {income_code} from {source_country}",
            )
        )

    logger.info(
        "Aggregated %d taxable-now reward rows into %d filing-ready entries (income_code + source_country)",
        len(taxable_entries),
        len(aggregated),
    )

    return aggregated


# Portuguese Tabela X country codes for IRS filing (ISO 3166-1 alpha-2)
_TABELA_X_COUNTRY_CODES: Final = frozenset(
    {
        "AT",
        "BE",
        "BG",
        "CY",
        "CZ",
        "DE",
        "DK",
        "EE",
        "ES",
        "FI",
        "FR",
        "GR",
        "HR",
        "HU",
        "IE",
        "IS",
        "IT",
        "LI",
        "LT",
        "LU",
        "LV",
        "MT",
        "NL",
        "NO",
        "PL",
        "PT",
        "RO",
        "SE",
        "SI",
        "SK",
        "CH",
        "GB",
        "US",
        "AE",
        "AU",
        "CA",
        "JP",
        "SG",
        "IN",
        "BR",
        "MX",
        "ZA",
        "KR",
        "IL",
        "CN",
        "HK",
        "NZ",
        "RU",
        "TR",
        "BS",
        "KY",
        "VG",
        "BZ",
        "PA",
        "JE",
        "GG",
        "IM",
        "BM",
        "BV",
        "AG",
        "DM",
        "GD",
        "KN",
        "LC",
        "VC",
        "BB",
        "JM",
        "TT",
        "GY",
        "SR",
        "GL",
        "PM",
        "WF",
        "PF",
        "NC",
        "AS",
        "GU",
        "MP",
        "PR",
        "VI",
        "UM",
        "MH",
        "FM",
        "PW",
        "KI",
        "NR",
        "TV",
        "TO",
        "WS",
        "SB",
        "VU",
        "FJ",
        "CK",
        "NU",
        "TK",
        "PG",
        "SL",
        "ML",
        "NE",
        "TD",
        "SD",
        "ER",
        "DJ",
        "SO",
        "CI",
        "LR",
        "GH",
        "TG",
        "BJ",
        "NG",
        "CM",
        "CF",
        "AO",
        "CD",
        "CG",
        "GA",
        "GQ",
        "ST",
    }
)

# Koinly income type to Tabela V income code mapping for Portuguese IRS
_KOINLY_TYPE_TO_INCOME_CODE: Final[dict[str, str]] = {
    # Crypto capital income codes (Tabela V for Anexo J)
    "staking": "401",  # Rendimentos de capitais - criptoativos
    "reward": "401",
    "airdrop": "401",
    "interest": "402",  # Juros de criptoativos
    "lending": "402",
    "lending interest": "402",
    "mining": "403",  # Rendimentos da atividade de mineração
    "fork": "404",  # Rendimentos de forks
    "dividend": "405",  # Dividendos de criptoativos
    # Default fallback for unknown types
}

_MAX_PDF_BYTES: Final = (
    20 * 1024 * 1024
)  # 20 MB limit for PDF parsing (increased from 10 MB due to growing Koinly report sizes)


def resolve_operator_origin(  # noqa: PLR0911, PLR0912
    platform: str,
    transaction_type: str | None = None,
    transaction_date: str | None = None,
) -> OperatorOrigin:
    """Resolve operator metadata from platform brand, transaction type, and optional transaction date.

    Source-country resolution hierarchy for DeFi:
    1. Interface legal entity (the exposed contracting party)
    2. Protocol / foundation / sponsoring legal entity
    3. Validator operator (when identifiable)

    IMPORTANT: This function NEVER defaults to the taxpayer's residence country.
    The source country must be derived from the paying entity / platform / protocol
    legal-entity domicile, not from where the taxpayer performed the activity.

    Temporal Validity:
    When transaction_date is provided, this function performs temporal validity checks
    against the mapping's service_start_date/valid_until dates. If a transaction predates
    service_start_date, a warning is logged and the earliest known mapping is returned
    (for historical data recovery scenarios).

    Args:
        platform: Wallet or platform name (e.g., "Ledger Berachain", "ByBit").
        transaction_type: Optional hint for service scope (e.g., "crypto_disposal", "fiat_deposit").
        transaction_date: Optional transaction date for historical mapping lookup.
            Accepts formats like "2025-03-15" or "2025-03-15 14:30:00".

    Returns:
        OperatorOrigin with the resolved operator entity and country.
        Returns operator_country="UNKNOWN" and review_required=True for unrecognized platforms.
    """
    logger = logging.getLogger(__name__)

    # Parse transaction date for temporal validity checks
    parsed_date: str | None = None
    date_parse_failed = False
    if transaction_date:
        try:
            parsed_date = _parse_transaction_date(transaction_date)
        except ValueError:
            logger.error(
                "Invalid transaction_date format '%s' for platform '%s': "
                "temporal validity check skipped. Expected format: 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM:SS'. "
                "Marking for manual review to ensure correct tax reporting.",
                transaction_date,
                platform,
            )
            date_parse_failed = True

    normalized = platform.lower()
    transaction_type_normalized = (transaction_type or "").lower()

    def _return_with_temporal_check(origin: OperatorOrigin) -> OperatorOrigin:
        """Return operator origin after performing temporal validity check.

        Logs a warning if the transaction date is outside the mapping's validity period.
        When out of validity, returns a modified origin with review_required=True to
        surface the ambiguity in the workbook's manual-review flag.

        Args:
            origin: The operator origin to validate.

        Returns:
            The origin, potentially with review_required=True if outside validity period
            or if date parsing failed.
        """
        # If date parsing failed, mark for review to ensure correct tax reporting
        if date_parse_failed:
            reason = "Transaction date format could not be parsed; temporal validity check skipped"
            combined = f"{origin.review_reason}; {reason}" if origin.review_reason else reason
            return replace(
                origin,
                review_required=True,
                review_reason=combined,
            )

        # Use service_start_date only for transaction matching (valid_from is for audit trail only)
        # When service_start_date is None, skip lower-bound check to avoid false positives
        # on long-running mappings that only have verification dates (e.g., Ethereum, Arbitrum)
        lower_bound = origin.service_start_date
        is_valid = parsed_date is None or _is_temporally_valid(lower_bound, origin.valid_until, parsed_date)
        if not is_valid:
            logger.warning(
                "Transaction date %s for platform '%s' (service_scope: %s) is outside "
                "the service period [%s, %s]. Marking for manual review. "
                "Please verify the operator origin is correct for this historical transaction.",
                parsed_date,
                origin.platform,
                origin.service_scope,
                lower_bound or "unknown",
                origin.valid_until or "present",
            )
            # Return a modified origin with review_required=True to surface in the workbook
            reason = (
                f"Transaction date {parsed_date} is outside known service period "
                f"[{lower_bound or 'unknown'}, {origin.valid_until or 'present'}] for {origin.platform}"
            )
            combined = f"{origin.review_reason}; {reason}" if origin.review_reason else reason
            return replace(
                origin,
                review_required=True,
                review_reason=combined,
            )

        return origin

    if "wirex" in normalized:
        if transaction_type_normalized.startswith("fiat"):
            return _return_with_temporal_check(
                OperatorOrigin(
                    platform="Wirex",
                    service_scope="fiat",
                    operator_entity="Wirex Limited",
                    operator_country="GB",
                    source_url="https://wirexapp.com/legal",
                    source_checked_on="2026-03-08",
                    confidence="medium",
                    review_required=False,
                    service_start_date="2015-01-01",  # Approximate founding date (Wirex Ltd incorporated 2014)
                    valid_from="2026-03-08",  # GB/HR split-scope verification date (audit trail)
                )
            )
        return _return_with_temporal_check(
            OperatorOrigin(
                platform="Wirex",
                service_scope="crypto",
                operator_entity="Wirex Digital (crypto operator, verify account terms)",
                operator_country="HR",
                source_url="https://wirexapp.com/legal",
                source_checked_on="2026-03-08",
                confidence="medium",
                review_required=False,
                service_start_date="2015-01-01",  # Approximate founding date (Wirex Ltd incorporated 2014)
                valid_from="2026-03-08",  # GB/HR split-scope verification date (audit trail)
            )
        )

    if "bybit" in normalized:
        return _return_with_temporal_check(
            OperatorOrigin(
                platform="Bybit",
                service_scope="crypto",
                operator_entity="Bybit group entity (account-region specific)",
                operator_country="AE",
                source_url="https://www.bybit.com/en/legal/terms-of-service/terms-of-service",
                source_checked_on="2026-03-08",
                confidence="low",
                review_required=False,
                platform_assumption=(
                    "Bybit uses account-region specific entities; "
                    "verify your account region matches the operator entity"
                ),
                platform_review_required=True,
                valid_from=None,  # Historical operator, exact start date unknown
            )
        )

    if "berachain" in normalized:
        return _return_with_temporal_check(
            OperatorOrigin(
                platform="Berachain",
                service_scope="crypto",
                operator_entity="BERA Chain Foundation",
                operator_country="VG",
                source_url="https://www.berachain.com/terms-of-service",
                source_checked_on="2026-03-15",
                confidence="high",
                review_required=False,
                service_start_date="2025-02-05",
                valid_from="2025-02-05",
            )
        )

    if "starknet" in normalized:
        return _return_with_temporal_check(
            OperatorOrigin(
                platform="Starknet",
                service_scope="crypto",
                operator_entity="Starknet Foundation",
                operator_country="KY",
                source_url="https://www.starknet.io/privacy-policy/",
                source_checked_on="2026-03-15",
                confidence="medium",
                review_required=False,
                service_start_date="2021-11-16",  # Starknet mainnet-alpha launch
                valid_from=None,
            )
        )

    if "zksync" in normalized:
        return _return_with_temporal_check(
            OperatorOrigin(
                platform="zkSync",
                service_scope="crypto",
                operator_entity="Matter Labs",
                operator_country="KY",
                source_url="https://zksync.io/terms",
                source_checked_on="2026-03-15",
                confidence="high",
                review_required=False,
                valid_from=None,  # Historical operator, exact start date unknown
            )
        )

    if "solana" in normalized:
        return _return_with_temporal_check(
            OperatorOrigin(
                platform="Solana",
                service_scope="crypto",
                operator_entity="Solana Foundation",
                operator_country="CH",
                source_url="https://solana.org/",
                source_checked_on="2026-03-15",
                confidence="medium",
                review_required=False,
                valid_from=None,  # Historical operator, exact start date unknown
            )
        )

    # Handle both correct "Tonkeeper" and common typo "Tonkeper" from Koinly exports
    if "tonkeeper" in normalized or "tonkeper" in normalized:
        return _return_with_temporal_check(
            OperatorOrigin(
                platform="Tonkeeper",
                service_scope="crypto",
                operator_entity="Ton Apps UK Ltd.",
                operator_country="GB",
                source_url="https://tonkeeper.com/terms",
                source_checked_on="2026-03-15",
                confidence="high",
                review_required=False,
                valid_from=None,  # Historical operator with unknown exact start date
            )
        )

    if re.search(r"\bton\b", normalized) and "tonkeeper" not in normalized and "tonkeper" not in normalized:
        return _return_with_temporal_check(
            OperatorOrigin(
                platform="TON",
                service_scope="crypto",
                operator_entity="TON Foundation",
                operator_country="CH",
                source_url="https://ton.foundation/",
                source_checked_on="2026-03-15",
                confidence="high",
                review_required=False,
                valid_from=None,  # Historical operator, exact start date unknown
            )
        )

    if "ethereum" in normalized:
        return _return_with_temporal_check(
            OperatorOrigin(
                platform="Ethereum",
                service_scope="crypto",
                operator_entity="Ethereum Foundation",
                operator_country="CH",
                source_url="https://blog.ethereum.org/2024/05/08/ethereum-foundation-report-2024",
                source_checked_on="2026-03-15",
                confidence="high",
                review_required=False,
                service_start_date="2015-07-30",  # Ethereum mainnet launch
                valid_from="2026-03-15",  # Source verification date
            )
        )

    if "aptos" in normalized:
        return _return_with_temporal_check(
            OperatorOrigin(
                platform="Aptos",
                service_scope="crypto",
                operator_entity="Aptos Foundation",
                operator_country="KY",
                source_url="https://aptosfoundation.org/terms",
                source_checked_on="2026-03-15",
                confidence="high",
                review_required=False,
                service_start_date="2022-10-17",  # Aptos mainnet launch
                valid_from="2026-03-15",  # Source verification date
            )
        )

    if re.search(r"\bsui\b", normalized):
        return _return_with_temporal_check(
            OperatorOrigin(
                platform="Sui",
                service_scope="crypto",
                operator_entity="Sui Foundation",
                operator_country="KY",
                source_url="https://www.sui.io/terms",
                source_checked_on="2026-03-15",
                confidence="medium",
                review_required=False,
                service_start_date="2023-05-03",  # Sui mainnet launch
                valid_from=None,
            )
        )

    if "arbitrum" in normalized:
        return _return_with_temporal_check(
            OperatorOrigin(
                platform="Arbitrum",
                service_scope="crypto",
                operator_entity="The Arbitrum Foundation",
                operator_country="KY",
                source_url="https://docs.arbitrum.foundation/assets/files/The%20Arbitrum%20Foundation%20M%26A%20-%2020%20July%202023-6e264ee4c38da73a3aa4c8581c5f751f.pdf",
                source_checked_on="2026-03-15",
                confidence="high",
                review_required=False,
                service_start_date="2021-08-31",  # Arbitrum One mainnet launch
                valid_from="2026-03-15",  # Source verification date
            )
        )

    if re.search(r"\bmantle\b", normalized):
        return _return_with_temporal_check(
            OperatorOrigin(
                platform="Mantle",
                service_scope="crypto",
                operator_entity="Mantle Foundation S.A.",
                operator_country="VG",
                source_url="https://www.ipd.gov.hk/hkipjournal/15032024/PUBLICATION_TYPE_TRADE_MARK_REGISTERED.pdf",
                source_checked_on="2026-03-15",
                confidence="medium",
                review_required=False,
                platform_assumption=(
                    "Mantle Foundation operator entity based on trademark registration; verify current entity structure"
                ),
                platform_review_required=True,
                service_start_date="2023-07-17",  # Mantle mainnet launch
                valid_from="2024-03-15",
            )
        )

    if "polygon" in normalized:
        return _return_with_temporal_check(
            OperatorOrigin(
                platform="Polygon",
                service_scope="crypto",
                operator_entity="Polygon Labs UI (Cayman) Ltd.",
                operator_country="KY",
                source_url="https://polygon.technology/terms-of-use",
                source_checked_on="2026-03-15",
                confidence="high",
                review_required=False,
                service_start_date="2020-05-28",  # Polygon mainnet launch
                valid_from="2026-03-15",  # Source verification date
            )
        )

    if re.search(r"\bbase\b", normalized) and "coinbase" not in normalized:
        return _return_with_temporal_check(
            OperatorOrigin(
                platform="BASE",
                service_scope="crypto",
                operator_entity="Coinbase Technologies, Inc.",
                operator_country="US",
                source_url="https://docs.base.org/terms-of-service",
                source_checked_on="2026-03-15",
                confidence="medium",
                review_required=False,
                service_start_date="2023-08-09",  # BASE mainnet launch
                valid_from="2026-03-15",  # Source verification date
            )
        )

    if "filecoin" in normalized:
        return _return_with_temporal_check(
            OperatorOrigin(
                platform="Filecoin",
                service_scope="crypto",
                operator_entity="Filecoin Foundation",
                operator_country="US",
                source_url="https://careers.fil.org/privacy-policy",
                source_checked_on="2026-03-15",
                confidence="medium",
                review_required=False,
                service_start_date="2020-10-15",  # Filecoin mainnet launch
                valid_from="2024-04-01",
            )
        )

    if "binance" in normalized:
        return _return_with_temporal_check(
            OperatorOrigin(
                platform="Binance",
                service_scope="crypto",
                operator_entity="Binance Spain, S.L. (Europe override for filing output)",
                operator_country="ES",
                source_url="https://www.binance.com/es/about-legal/local-terms",
                source_checked_on="2026-03-15",
                confidence="medium",
                review_required=False,
                valid_from=None,  # Europe override verified 2026-03-15; exact entity change date unknown
            )
        )

    if "gate.io" in normalized or normalized == "gate":
        return _return_with_temporal_check(
            OperatorOrigin(
                platform="Gate.io",
                service_scope="crypto",
                operator_entity="Gate Technology Ltd",
                operator_country="MT",
                source_url="https://www.gate.com/en-eu/about-us",
                source_checked_on="2026-03-15",
                confidence="high",
                review_required=False,
                valid_from=None,  # Historical operator, exact start date unknown
            )
        )

    if "kraken" in normalized:
        return _return_with_temporal_check(
            OperatorOrigin(
                platform="Kraken",
                service_scope="crypto",
                operator_entity="Payward Ireland Limited / Payward Europe Solutions Limited",
                operator_country="IE",
                source_url="https://support.kraken.com/articles/where-is-kraken-licensed-or-regulated",
                source_checked_on="2026-03-15",
                confidence="high",
                review_required=False,
                valid_from=None,  # Historical operator, exact start date unknown
            )
        )

    return _return_with_temporal_check(
        OperatorOrigin(
            platform=platform,
            service_scope="crypto",
            operator_entity="UNKNOWN_OPERATOR_REVIEW_REQUIRED",
            operator_country="UNKNOWN",
            source_url="",
            source_checked_on="2026-03-08",
            confidence="low",
            review_required=True,
            review_reason="Unknown platform - operator origin could not be determined automatically",
            valid_from="2026-03-08",  # Unknown platform - use source check date as valid_from
        )
    )


def _apply_phantom_lot_flags(
    result: AssetFifoResult,
    asset: str,
    platform: str,
    phantom_transfers: frozenset[tuple[str, str, str]],
) -> AssetFifoResult:
    """Flag FIFO realizations on a sending platform that may have consumed phantom lots.

    When a loan-affected asset is transferred cross-platform, the FIFO pool on the
    sending platform retains the lot (the transfer is not tracked as a consumption).
    Any subsequent disposal on that platform consumes an incorrect phantom lot.
    Per CLAUDE.md: partial or uncertain results must carry an explicit indicator.

    Args:
        result: FIFO result for (asset, platform).
        asset: Asset ticker.
        platform: Platform name.
        phantom_transfers: Set of (asset, platform, date) cross-platform transfer markers.

    Returns:
        Updated AssetFifoResult with review_required=True on affected realizations,
        or the original result unchanged if no phantom transfers apply.
    """
    phantom_dates = [date for (a, p, date) in phantom_transfers if a == asset and p == platform]
    if not phantom_dates:
        return result

    earliest_phantom = min(phantom_dates)
    phantom_reason = (
        f"Phantom lot: {asset} was transferred cross-platform on {earliest_phantom}; "
        "this platform's FIFO pool retains the lot after the transfer "
        "(CIRS art. 43 n.9 per-wallet scope limitation). "
        "Cost basis for this realization may be overstated — verify against "
        "the sending wallet's transaction records."
    )
    flagged: list[CryptoFifoRealization] = []
    for r in result.realizations:
        if r.disposal_date >= earliest_phantom:
            if r.review_required and r.review_reason:
                flagged.append(replace(r, review_reason=f"{r.review_reason}; {phantom_reason}"))
            else:
                flagged.append(replace(r, review_required=True, review_reason=phantom_reason))
        else:
            flagged.append(r)
    return AssetFifoResult(
        realizations=flagged,
        carryover_cost_by_tx_key=result.carryover_cost_by_tx_key,
        partial_carryover_tx_keys=result.partial_carryover_tx_keys,
    )


def _compute_cross_asset_receiver_totals(
    acquisitions_by_asset: dict[str, list],
) -> dict[str, dict[str, Decimal]]:
    """Pre-compute the total deferred-acquisition amount per (tx_key, asset) pair.

    Called once before the per-asset FIFO loop so that cross-asset receivers
    sharing the same tx_key each receive only their proportional share of the
    carry-over cost rather than the full amount.

    Args:
        acquisitions_by_asset: Parsed acquisition contexts keyed by asset ticker.

    Returns:
        Mapping of tx_key → {asset → total_amount} for all exchange_in_deferred rows.
    """
    totals: dict[str, dict[str, Decimal]] = {}
    for asset, acqs in acquisitions_by_asset.items():
        for acq in acqs:
            if acq.acq.source_type == "exchange_in_deferred":
                at = totals.setdefault(acq.tx_key, {})
                at[asset] = at.get(asset, ZERO) + acq.acq.amount
    return totals


def _process_single_asset_fifo(  # noqa: PLR0913
    asset: str,
    acquisitions_by_asset: dict[str, list],
    consumptions_by_asset: dict[str, list],
    fifo_by_asset: dict[str, MergedAssetFifoResult],
    tx_key_to_sender: dict[str, list[str]],
    all_asset_totals: dict[str, dict[str, Decimal]],
    phantom_transfers: dict,
    logger: logging.Logger,
) -> list[CryptoFifoRealization]:
    """Run FIFO for a single asset across all its platforms and return realizations.

    Resolves deferred cross-asset acquisitions, orders platforms by intra-asset
    transfer dependencies, runs per-platform FIFO, and stores the merged carry-over
    result in ``fifo_by_asset[asset]`` so subsequent assets can consume it.

    Args:
        asset: Asset ticker to process.
        acquisitions_by_asset: All parsed acquisitions keyed by asset.
        consumptions_by_asset: All parsed consumptions keyed by asset.
        fifo_by_asset: Accumulator of per-asset FIFO results; mutated in-place with
            the carry-over result for ``asset``.
        tx_key_to_sender: Maps tx_key → list of sender asset tickers for cross-asset
            carry-over scoping.
        all_asset_totals: Pre-computed receiver totals from
            ``_compute_cross_asset_receiver_totals``; used for proportional cost splits.
        phantom_transfers: Set of (asset, tx_key) pairs flagged as phantom transfers.
        logger: Logger for diagnostics.

    Returns:
        All realizations produced for this asset across all platforms.
    """
    raw_acqs = acquisitions_by_asset.get(asset, [])
    resolved = resolve_cross_asset_exchanges(
        {asset: raw_acqs},
        fifo_by_asset,
        tx_key_to_sender=tx_key_to_sender,
        tx_key_to_asset_totals=all_asset_totals,
    )
    acqs = resolved.get(asset, raw_acqs)

    cons = consumptions_by_asset.get(asset, [])
    platforms = {a.acq.platform for a in acqs} | {c.con.platform for c in cons}
    merged_carryover: dict[tuple[str, str], Decimal] = {}
    merged_partial_tx_keys: set[str] = set()

    per_platform_carryover: dict[str, dict[str, Decimal]] = {}
    per_platform_partial_map: dict[str, frozenset[str]] = {}

    platform_order = _order_platforms_for_transfers(acqs, cons)
    ordered = list(platform_order)
    for p in sorted(platforms):
        if p not in set(ordered):
            ordered.append(p)

    asset_realizations: list[CryptoFifoRealization] = []
    for platform in ordered:
        if platform not in platforms:
            continue
        p_acqs = [a for a in acqs if a.acq.platform == platform]
        p_cons = [c for c in cons if c.con.platform == platform]
        p_acqs = _resolve_intra_asset_transfers(p_acqs, per_platform_carryover, per_platform_partial_map)
        if p_acqs or p_cons:
            result = compute_fifo_for_asset(p_acqs, p_cons, asset, platform)
            result = _apply_phantom_lot_flags(result, asset, platform, phantom_transfers)
            asset_realizations.extend(result.realizations)
            per_platform_carryover[platform] = dict(result.carryover_cost_by_tx_key)
            per_platform_partial_map[platform] = result.partial_carryover_tx_keys
            for key, cost in result.carryover_cost_by_tx_key.items():
                platform_key = (key, platform)
                if platform_key in merged_carryover:
                    logger.info(
                        "%s carry-over key %r for platform %r already present; costs summed",
                        asset,
                        key,
                        platform,
                    )
                merged_carryover[platform_key] = merged_carryover.get(platform_key, ZERO) + cost
            merged_partial_tx_keys.update(result.partial_carryover_tx_keys)

    fifo_by_asset[asset] = MergedAssetFifoResult(
        carryover_cost_by_tx_key=merged_carryover,
        partial_carryover_tx_keys=frozenset(merged_partial_tx_keys),
    )
    return asset_realizations


def _rebuild_fifo_for_loan_affected_assets(
    transaction_history_file: Path,
    origin_resolver: TokenOriginResolver,
    loan_affected_assets: frozenset[str],
    *,
    fiscal_year: int | None = None,
) -> tuple[list[CryptoCapitalGainEntry], frozenset[str]]:
    """Rebuild FIFO for loan-affected assets from Transaction History.

    Processes assets with cross-asset carry-over resolution, ordered
    by swap dependencies, per (asset, platform) pair.

    Only realizations whose disposal date falls in ``fiscal_year`` are converted
    to ``CryptoCapitalGainEntry`` objects.  Acquisitions from prior years are
    still allowed into the FIFO pool so that cost-basis carry-over is correct;
    only the final reporting step is gated.

    Args:
        transaction_history_file: Path to the Koinly Transaction History CSV.
        origin_resolver: Token origin resolver for annotating gain entries.
        loan_affected_assets: Set of asset tickers to rebuild via FIFO.
        fiscal_year: If provided, only include realizations from this tax year in
            the output. Pass ``None`` to include all years (useful in testing).

    Returns:
        Tuple of (fifo_entries, th_assets) where th_assets is the set of
        loan-affected asset tickers that appeared in the Transaction History.
    """
    acquisitions_by_asset, consumptions_by_asset, phantom_transfers, parse_failures = parse_th_for_loan_affected_assets(
        transaction_history_file,
        loan_affected_assets=loan_affected_assets,
    )

    # th_assets tracks only assets with taxable consumption events:
    # - Acquisition-only assets (never disposed this year) legitimately produce zero FIFO realizations.
    # - Assets with only non-taxable consumptions (e.g. all disposals were crypto-to-crypto swaps
    #   under PT art. 10(20)) also legitimately produce zero taxable realizations.
    # Only assets with at least one taxable consumption should trigger the "gains missing" warning.
    th_assets = frozenset(
        asset for asset, cons in consumptions_by_asset.items()
        if any(c.con.taxable for c in cons)
    )

    if not acquisitions_by_asset and not consumptions_by_asset:
        return [], th_assets

    logger = logging.getLogger(__name__)
    all_realizations: list[CryptoFifoRealization] = []
    fifo_by_asset: dict[str, MergedAssetFifoResult] = {}

    # Derive processing order from cross-asset swap dependencies.
    # Assets that send in cross-asset swaps are processed before receiving assets
    # so their carry-over cost basis is available when deferred acquisitions are resolved.
    # tx_key_to_sender scopes carryover lookups to the correct source asset, preventing
    # ambiguity when multiple loan-affected assets share the same on-chain tx_hash.
    processing_order, tx_key_to_sender = _build_cross_asset_order(
        acquisitions_by_asset, consumptions_by_asset
    )

    # Pre-compute receiver totals across ALL assets before the per-asset loop.
    # Without the full cross-asset totals, each per-asset call would see only itself
    # (num_unique_assets == 1) and incorrectly claim the full carry-over cost —
    # duplicating cost basis when two receiver assets share the same tx_key.
    all_asset_totals = _compute_cross_asset_receiver_totals(acquisitions_by_asset)

    for asset in processing_order:
        all_realizations.extend(
            _process_single_asset_fifo(
                asset,
                acquisitions_by_asset,
                consumptions_by_asset,
                fifo_by_asset,
                tx_key_to_sender,
                all_asset_totals,
                phantom_transfers,
                logger,
            )
        )

    # Flag realizations for assets with TH parse errors.
    if parse_failures:
        updated: list[CryptoFifoRealization] = []
        for r in all_realizations:
            failed_rows = parse_failures.get(r.asset)
            if failed_rows:
                rows_str = ", ".join(str(i) for i in sorted(failed_rows))
                parse_error_reason = (
                    f"TH parse error on row(s) {rows_str}: FIFO pool for {r.asset} "
                    "may be incomplete — verify all acquisitions/disposals are present"
                )
                updated.append(replace(
                    r,
                    review_required=True,
                    review_reason="; ".join(filter(None, [r.review_reason, parse_error_reason])),
                ))
            else:
                updated.append(r)
        all_realizations = updated

    # Step 4: Filter to fiscal year (disposal-date gate only; acquisitions from prior years
    # must remain in the FIFO pool above so cost-basis carry-over is correct).
    if fiscal_year is not None:
        fiscal_year_prefix = str(fiscal_year)
        excluded_count = sum(
            1 for r in all_realizations if not r.disposal_date.startswith(fiscal_year_prefix)
        )
        if excluded_count:
            logger.warning(
                "FIFO rebuild: excluding %d realization(s) with disposal dates outside fiscal year %d "
                "(these belong to a different tax year and must not appear in this report)",
                excluded_count,
                fiscal_year,
            )
        all_realizations = [r for r in all_realizations if r.disposal_date.startswith(fiscal_year_prefix)]

    # Step 5: Convert realizations to CryptoCapitalGainEntry
    fifo_entries: list[CryptoCapitalGainEntry] = []
    for r in all_realizations:
        operator_origin = resolve_operator_origin(
            r.platform, transaction_type="crypto_disposal", transaction_date=r.disposal_date,
        )
        annex_hint = "G1" if r.holding_period.lower().startswith("long") else "J"
        chain = _derive_chain(r.wallet)
        origin = origin_resolver.resolve(r.acquisition_date, r.asset, r.wallet, r.notes or "")
        combined_review_required = r.review_required or operator_origin.review_required
        combined_review_reason = (
            "; ".join(filter(None, [r.review_reason, operator_origin.review_reason])) or None
        )
        # Defensive guard: review_required=True must always have a reason.
        # This should be guaranteed by upstream __post_init__ validators, but guard explicitly
        # to prevent a silent ValueError if any upstream invariant is bypassed (e.g. via replace()).
        if combined_review_required and not combined_review_reason:
            combined_review_reason = "Review required (reason not propagated from FIFO or origin resolver)"

        combined_review_required, combined_review_reason = _build_zero_basis_review_reason(
            r.cost_eur, r.proceeds_eur, combined_review_required, combined_review_reason or ""
        )

        fifo_entries.append(
            CryptoCapitalGainEntry(
                disposal_date=r.disposal_date,
                acquisition_date=r.acquisition_date,
                asset=r.asset,
                amount=r.amount,
                cost_eur=r.cost_eur,
                proceeds_eur=r.proceeds_eur,
                gain_loss_eur=r.gain_loss_eur,
                holding_period=r.holding_period,
                wallet=r.wallet,
                platform=r.platform,
                chain=chain,
                operator_origin=operator_origin,
                annex_hint=annex_hint,
                review_required=combined_review_required,
                notes=r.notes or "",
                review_reason=combined_review_reason,
                token_swap_history=str(origin),
                multi_acquisition_dates=False,
            )
        )

    return fifo_entries, th_assets


def _build_zero_basis_review_reason(
    cost_eur: Decimal,
    proceeds_eur: Decimal,
    review_required: bool,
    review_reason: str,
) -> tuple[bool, str]:
    """Build review reason for zero-cost or zero-proceeds entries.

    Args:
        cost_eur: Acquisition cost in EUR.
        proceeds_eur: Disposal proceeds in EUR.
        review_required: Current review_required flag value.
        review_reason: Current review_reason text.

    Returns:
        Tuple of (updated_review_required, updated_review_reason) with zero-basis
        flags added if applicable.
    """
    if cost_eur == ZERO:
        review_required = True
        zero_cost_reason = "Zero acquisition cost - verify basis (airdrop, data error, or misclassification)"
        review_reason = f"{review_reason}; {zero_cost_reason}" if review_reason else zero_cost_reason

    if proceeds_eur == ZERO:
        review_required = True
        zero_proceeds_reason = "Zero disposal proceeds - verify sale data (transfer error, data quality issue)"
        review_reason = f"{review_reason}; {zero_proceeds_reason}" if review_reason else zero_proceeds_reason

    return review_required, review_reason


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

    capital_entries = _validate_capital_entries_have_valid_countries(capital_entries)
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


def _find_report_file(koinly_dir: Path, marker: str) -> Path | None:
    return _find_report_path(koinly_dir, marker, ".csv")


def _find_report_path(koinly_dir: Path, marker: str, suffix: str) -> Path | None:
    matches = sorted(koinly_dir.glob(f"*{marker}*{suffix}"))
    return matches[0] if matches else None


def _extract_tax_year(
    koinly_dir: Path,
    capital_file: Path | None,
    income_file: Path | None,
    *,
    jurisdiction: TaxJurisdictionConfig | None = None,
) -> int:
    for candidate in [capital_file, income_file]:
        if candidate is None:
            continue
        match = re.search(r"koinly_(\d{4})_", candidate.name)
        if match:
            return int(match.group(1))
    if jurisdiction is not None:
        return jurisdiction.fiscal_year
    fallback_match = re.search(r"(\d{4})", koinly_dir.name)
    if fallback_match:
        return int(fallback_match.group(1))
    return datetime.now(tz=UTC).year


def _aggregate_origin_field(group: list[CryptoCapitalGainEntry]) -> str:
    """Derive the aggregated Token origin string from a group of FIFO lot rows.

    If all lots share the same origin string, return it. Otherwise concatenate
    unique, non-empty origins (preserving insertion order) with '; ' separator.
    When some lots have unknown origin, an indicator is appended so the user
    cannot mistake a partial result for full resolution.
    """
    unique_origins = list(dict.fromkeys(e.token_swap_history for e in group if e.token_swap_history))
    unknown_count = sum(1 for e in group if not e.token_swap_history)
    if not unique_origins:
        return ""
    parts = list(unique_origins)
    if unknown_count > 0:
        parts.append(f"{unknown_count} lot{'s' if unknown_count != 1 else ''} unresolved")
    if len(parts) == 1:
        return parts[0]
    return "; ".join(parts)


def _aggregate_capital_entries(entries: list[CryptoCapitalGainEntry]) -> list[CryptoCapitalGainEntry]:
    """Aggregate FIFO lot rows into one line per sale event (same date + asset + platform + holding_period).

    Rationale: the sale transaction is the reportable alienação in Portuguese IRS Quadro 9.4.
    FIFO lot allocation is an accounting method, not a separate disposal event (PT-C-025, PT-C-027).

    The holding_period is included in the aggregation key to preserve the taxable vs exempt breakdown
    needed for correct filing (PT-C-011: short-term gains are taxable, long-term gains are exempt).

    Uses normalized platform name in aggregation key so wallet aliases (e.g., "ByBit" and "ByBit (2)")
    collapse into the same logical account.
    """
    groups: dict[tuple[str, str, str, str], list[CryptoCapitalGainEntry]] = {}
    for entry in entries:
        key = (entry.disposal_date, entry.asset, entry.platform, entry.holding_period)
        groups.setdefault(key, []).append(entry)

    logger = logging.getLogger(__name__)
    result = []
    for group in groups.values():
        first = group[0]
        non_empty_dates = [e.acquisition_date for e in group if e.acquisition_date]
        acquisition_date = min(non_empty_dates) if non_empty_dates else ""
        if not acquisition_date:
            logger.warning(
                "Aggregated entry for %r sold %s has no acquisition date; "
                "one or more lots had a pool-exhausted placeholder with empty acquisition date",
                first.asset,
                first.disposal_date,
            )
        elif acquisition_date.startswith("1970-"):
            logger.warning(
                "Aggregated entry for %r sold %s has epoch sentinel acquisition date; "
                "one or more lots had missing Date Acquired in Koinly export",
                first.asset,
                first.disposal_date,
            )
        # Detect multiple acquisition dates within the aggregated group
        unique_acquisition_dates = sorted(set(dict.fromkeys(non_empty_dates)))
        multi_acquisition_dates = len(unique_acquisition_dates) > 1

        # Build multi-date note when multiple acquisition dates exist
        multi_date_note = ""
        if multi_acquisition_dates:
            dates_str = ", ".join(unique_acquisition_dates)
            multi_date_note = f"Acquired: {dates_str} ({len(group)} lot{'s' if len(group) != 1 else ''})"

        # Merge existing notes with multi-date note (multi-date note first for prominence)
        existing_notes = list(dict.fromkeys(e.notes for e in group if e.notes))
        all_note_parts = list(dict.fromkeys(existing_notes))
        if multi_date_note:
            all_note_parts.insert(0, multi_date_note)
        merged_notes = "; ".join(all_note_parts) or ""

        result.append(
            CryptoCapitalGainEntry(
                disposal_date=first.disposal_date,
                acquisition_date=acquisition_date,
                asset=first.asset,
                amount=sum((e.amount for e in group), start=ZERO),
                cost_eur=sum((e.cost_eur for e in group), start=ZERO),
                proceeds_eur=sum((e.proceeds_eur for e in group), start=ZERO),
                gain_loss_eur=sum((e.gain_loss_eur for e in group), start=ZERO),
                holding_period=first.holding_period,
                wallet=first.wallet,
                platform=first.platform,
                chain=first.chain,
                operator_origin=first.operator_origin,
                annex_hint=first.annex_hint,
                review_required=any(e.review_required for e in group),
                review_reason="; ".join(dict.fromkeys(e.review_reason for e in group if e.review_reason)) or None,
                notes=merged_notes,
                token_swap_history=_aggregate_origin_field(group),
                multi_acquisition_dates=multi_acquisition_dates,
            )
        )
    result.sort(key=lambda e: (e.disposal_date, e.asset, e.platform, e.holding_period))
    return result


def _filter_immaterial_entries(entries: list[CryptoCapitalGainEntry]) -> list[CryptoCapitalGainEntry]:
    """Drop lines where |gain/loss| < 1 EUR after aggregation (PT-C-028).

    Sub-1-EUR lines have no material tax impact and AT portal requires manual entry per line.
    The absolute-value test means small losses (between -1 and 0) are also excluded.
    """
    return [e for e in entries if abs(e.gain_loss_eur) >= _MATERIALITY_THRESHOLD]


def _validate_capital_entries_have_valid_countries(
    entries: list[CryptoCapitalGainEntry],
) -> list[CryptoCapitalGainEntry]:
    """Validate that all capital entries have valid Tabela X country codes.

    Entries with invalid/unknown country codes are retained in the output but flagged
    with review_required=True and an actionable review_reason. This follows the
    "process with error indicators" principle: the report is never aborted due to a
    missing registry entry — the user is informed and can add the platform mapping.

    Args:
        entries: Parsed capital gain entries to validate.

    Returns:
        Entries with any invalid-country entries flagged for review.
    """
    logger = logging.getLogger(__name__)
    result: list[CryptoCapitalGainEntry] = []
    invalid_count = 0

    for entry in entries:
        country = entry.operator_origin.operator_country
        if not _is_valid_tabela_x_country(country):
            invalid_count += 1
            logger.error(
                "Capital entry for %s on %s has unresolvable country '%s' (platform=%s, wallet=%s); "
                "entry flagged for review — add platform mapping to resolve_operator_origin()",
                entry.asset,
                entry.disposal_date,
                country,
                entry.platform,
                entry.wallet,
            )
            new_reason = (
                f"Platform '{entry.platform}' has no registered country mapping; "
                f"resolved country '{country}' is not a valid Tabela X code — "
                "add this platform to resolve_operator_origin() before filing"
            )
            result.append(
                replace(
                    entry,
                    review_required=True,
                    review_reason="; ".join(filter(None, [new_reason, entry.review_reason])),
                )
            )
        else:
            result.append(entry)

    if invalid_count > 0:
        logger.error(
            "%d capital gain %s have unresolvable country codes and require manual review "
            "before IRS filing; see individual entry warnings above",
            invalid_count,
            "entry" if invalid_count == 1 else "entries",
        )
    else:
        logger.debug(
            "Validated %d capital entries: all have valid Tabela X country codes",
            len(entries),
        )

    return result


def _extract_loan_activity(transaction_history_path: Path | None) -> list[LoanActivityEntry]:  # noqa: PLR0912, PLR0915
    """Extract per-asset loan activity from the Koinly transaction history.

    Scans for loan receipts (Tag='Loan', deposit types) and loan repayments
    (Tag='Loan repayment', crypto_withdrawal). Aggregates per asset and
    computes balance with status classification.

    Args:
        transaction_history_path: Path to the Koinly transaction history CSV, or None.

    Returns:
        Sorted list of LoanActivityEntry, one per asset with loan activity.
    """
    if transaction_history_path is None or not transaction_history_path.exists():
        return []

    logger = logging.getLogger(__name__)

    @dataclass
    class _Accumulator:
        received_count: int = 0
        received_amount: Decimal = ZERO
        received_value_eur: Decimal = ZERO
        repaid_count: int = 0
        repaid_amount: Decimal = ZERO
        repaid_value_eur: Decimal = ZERO

    accs: dict[str, _Accumulator] = {}
    rows = read_koinly_rows(transaction_history_path)

    for row_number, row in enumerate(rows, start=1):
        tag = row.get("Tag", "").strip().lower()
        row_type = row.get("Type", "").strip().lower()

        if tag == "loan" and row_type in ("crypto_deposit", "deposit", "transfer"):
            received_currency = row.get("Received Currency", "").strip()
            if not received_currency:
                logger.warning("Skipping loan receipt row %d: blank Received Currency", row_number)
                continue
            asset = normalize_asset_ticker(received_currency)
            received_amount_str = row.get("Received Amount", "0").strip()
            net_value_str = row.get("Net Value (EUR)", "0").strip()
            try:
                received_amount = parse_koinly_decimal(received_amount_str)
                received_value = parse_koinly_decimal(net_value_str)
            except ValueError as exc:
                logger.warning("Skipping loan receipt row %d for %s: unparseable amount: %s", row_number, asset, exc)
                continue
            if asset not in accs:
                accs[asset] = _Accumulator()
            accs[asset].received_count += 1
            accs[asset].received_amount += received_amount
            accs[asset].received_value_eur += received_value

        elif tag == "loan repayment" and row_type in {"crypto_withdrawal", "exchange", "sell", "transfer"}:
            # Loan repayments are executed as withdrawals (most common), exchanges (DeFi repay-in-kind),
            # sells, or on-chain transfers. For all these row types, the repaid crypto is in Sent Currency.
            # Note: "buy" is excluded — buy rows represent fiat→crypto purchases where Sent Currency
            # is fiat, not the crypto being repaid.
            sent_currency = row.get("Sent Currency", "").strip()
            if not sent_currency:
                logger.warning("Skipping loan repayment row %d: blank Sent Currency", row_number)
                continue
            if row_type == "exchange" and normalize_asset_ticker(sent_currency) in _get_all_fiat_currency_codes():
                received_currency = row.get("Received Currency", "").strip()
                logger.warning(
                    "Skipping loan repayment row %d: exchange type with fiat Sent Currency %s "
                    "(Received Currency=%s); fiat-mediated repayments should be type 'buy', not 'exchange'",
                    row_number,
                    sent_currency,
                    received_currency,
                )
                continue
            asset = normalize_asset_ticker(sent_currency)
            sent_amount_str = row.get("Sent Amount", "0").strip()
            net_value_str = row.get("Net Value (EUR)", "0").strip()
            try:
                sent_amount = parse_koinly_decimal(sent_amount_str)
                repaid_value = parse_koinly_decimal(net_value_str)
            except ValueError as exc:
                logger.warning("Skipping loan repayment row %d for %s: unparseable amount: %s", row_number, asset, exc)
                continue
            if asset not in accs:
                accs[asset] = _Accumulator()
            accs[asset].repaid_count += 1
            accs[asset].repaid_amount += sent_amount
            accs[asset].repaid_value_eur += repaid_value

    entries: list[LoanActivityEntry] = []
    for asset in sorted(accs):
        a = accs[asset]
        balance = a.received_amount - a.repaid_amount
        if balance == ZERO:
            status = "Settled"
        elif balance < ZERO:
            status = LOAN_STATUS_OVERPAID
        else:
            status = "Open loan"
        entries.append(
            LoanActivityEntry(
                asset=asset,
                received_count=a.received_count,
                received_amount=a.received_amount,
                received_value_eur=a.received_value_eur,
                repaid_count=a.repaid_count,
                repaid_amount=a.repaid_amount,
                repaid_value_eur=a.repaid_value_eur,
                balance_amount=balance,
                balance_status=status,
            )
        )
    return entries


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


def _parse_complete_tax_report_pdf(path: Path) -> CryptoCompletePdfSummary | None:
    if path.is_symlink():
        logging.getLogger(__name__).warning(
            "PDF file %s is a symlink — skipping metadata extraction for security",
            path.name,
        )
        return None

    try:
        file_size = path.stat().st_size
    except OSError as exc:
        logging.getLogger(__name__).warning(
            "Could not stat PDF file %s: %s — skipping metadata extraction",
            path.name,
            exc,
        )
        return None
    if file_size > _MAX_PDF_BYTES:
        logging.getLogger(__name__).warning(
            "PDF file %s exceeds size limit (%d bytes, max %d bytes) - skipping metadata extraction",
            path.name,
            file_size,
            _MAX_PDF_BYTES,
        )
        return None
    try:
        content = path.read_bytes()
    except OSError as exc:
        logging.getLogger(__name__).warning(
            "Could not read PDF file %s: %s — skipping metadata extraction",
            path.name,
            exc,
        )
        return None
    hex_tokens = re.findall(rb"<([0-9A-Fa-f]{2,})>", content)
    decoded_tokens = [_decode_pdf_hex_token(token) for token in hex_tokens]
    cleaned_tokens = [token for token in decoded_tokens if token]

    if not cleaned_tokens:
        return None

    joined = " ".join(cleaned_tokens)
    period_match = re.search(r"\b\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}\s+to\s+\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}\b", joined)
    timezone_match = re.search(r"\b[A-Za-z]+/[A-Za-z_]+(?:/[A-Za-z_]+)?\b", joined)

    return CryptoCompletePdfSummary(
        period=period_match.group(0) if period_match else None,
        timezone=timezone_match.group(0) if timezone_match else None,
        extracted_tokens=len(cleaned_tokens),
    )


def _decode_pdf_hex_token(token: bytes) -> str:
    if len(token) % 2 != 0:
        return ""
    try:
        raw = bytes.fromhex(token.decode("ascii"))
    except ValueError:
        return ""
    if not raw:
        return ""
    text = raw.decode("utf-16-be", errors="ignore") if b"\x00" in raw else raw.decode("utf-8", errors="ignore")
    text = text.replace("\x00", "").strip()
    return text if text else ""


def _register_skipped_zero_asset(
    skipped_assets: dict[tuple[str, str], dict], section: str, asset: str, suspicious: bool = False
) -> None:
    """Register a skipped zero-value asset.

    Args:
        skipped_assets: Dict tracking (section, asset) -> {"count": int, "suspicious": bool}
        section: Source section (capital_gains, income, holdings_opening, etc.)
        asset: Asset ticker
        suspicious: True if asset contains non-Latin characters (potential scam token)
    """
    cleaned_asset = asset or "UNKNOWN_ASSET"
    key = (section, cleaned_asset)
    if key not in skipped_assets:
        skipped_assets[key] = {"count": 0, "suspicious": suspicious}
    skipped_assets[key]["count"] += 1
    # If any instance of this asset is suspicious, mark the whole entry as suspicious
    if suspicious:
        skipped_assets[key]["suspicious"] = True


# Chain names from docs/tax/crypto-origin/operator_chain_origin_registry.md
# These are the canonical chain identifiers used for reporting
_KNOWN_CHAINS: Final = frozenset(
    {
        "Berachain",
        "Starknet",
        "zkSync ERA",
        "Solana",
        "TON",
        "Ethereum",
        "Aptos",
        "Sui",
        "Arbitrum",
        "Mantle",
        "Polygon",
        "BASE",
        "Filecoin",
        "Binance Smart Chain",
        "ByBit",
        "Gate.io",
        "Kraken",
        "Binance",
        "Wirex",
        "Tonkeeper",
    }
)
_KNOWN_CHAINS_BY_LENGTH: Final = tuple(sorted(_KNOWN_CHAINS, key=len, reverse=True))


def _derive_chain(wallet: str) -> str:  # noqa: PLR0911, PLR0912
    """Derive the blockchain/chain identifier from a wallet label.

    Uses deterministic normalization rules to extract chain names from wallet labels.
    The wallet/platform name is only a discovery hint; final mappings come from
    trusted sources in docs/tax/crypto-origin/operator_chain_origin_registry.md.

    Normalization rules:
    - Strip platform aliases like "Ledger " prefix
    - Strip asset tickers in parentheses (e.g., "(ETH)", "(SOL)")
    - Strip address suffixes after " - " (e.g., " - 0x6ABd...")
    - Normalize platform aliases (e.g., "ByBit (2)" -> "ByBit")

    Args:
        wallet: The raw wallet name from Koinly (e.g., "Ledger Berachain (BERA)",
               "Ethereum (ETH) - 0x6ABd...", "ByBit (2)").

    Returns:
        The normalized chain name if matched against known chains,
        or "Unknown" if the wallet label does not allow reasonable derivation.
    """
    if not wallet or not wallet.strip():
        return "Unknown"

    normalized = wallet.strip()

    # Normalize wallet aliases (e.g., "ByBit (2)" -> "ByBit")
    normalized = normalize_platform_name(normalized)

    # Strip "Ledger " prefix if present (common Koinly pattern)
    if normalized.lower().startswith("ledger "):
        normalized = normalized[7:].strip()  # len("ledger ") == 7

    # Strip address suffixes after " - " (e.g., "Ethereum (ETH) - 0x6ABd...")
    if " - " in normalized:
        normalized = normalized.split(" - ", maxsplit=1)[0].strip()

    # Strip asset tickers in parentheses (e.g., "(ETH)", "(SOL)", "(BERA)")
    # Match pattern like "Ethereum (ETH)" or "Solana (SOL) - ..."
    if " (" in normalized and ")" in normalized:
        parts = normalized.split(" (", maxsplit=1)
        if len(parts) == _SPLIT_PARTS_WITH_TICKER and ")" in parts[1]:
            # Extract the base name before the ticker
            ticker_part = parts[1].split(")", maxsplit=1)
            # Only strip if it looks like a ticker (short, uppercase letters)
            if len(ticker_part[0]) <= _MAX_TICKER_LENGTH and ticker_part[0].isalpha():
                normalized = parts[0].strip()
            # else: keep the original if the parenthesized content isn't a simple ticker

    # Now match against known chains (case-insensitive)
    normalized_lower = normalized.lower()

    # Direct match against known chains
    for known_chain in _KNOWN_CHAINS:
        if normalized_lower == known_chain.lower():
            return known_chain

    # Check if the wallet name contains a known chain as a word
    # Sort by length descending to prefer more specific matches first
    for known_chain in _KNOWN_CHAINS_BY_LENGTH:
        chain_lower = known_chain.lower()
        # Match word boundaries for chain names
        if f" {chain_lower} " in f" {normalized_lower} ":
            return known_chain
        # Match at start
        if normalized_lower.startswith(chain_lower + " "):
            return known_chain
        # Match at end
        if normalized_lower.endswith(" " + chain_lower):
            return known_chain

    # Special case: "bnb" or "bsc" -> Binance Smart Chain
    if "bnb" in normalized_lower or "bsc" in normalized_lower:
        return "Binance Smart Chain"

    # Special case: "gate" (with or without .io) -> Gate.io
    # Match "gate", "gate ", or any wallet containing "gate" and ".io" (e.g., "Gate.io")
    is_gate_wallet = (
        normalized_lower == "gate"
        or normalized_lower.startswith("gate ")
        or ("gate" in normalized_lower and ".io" in normalized_lower)
    )
    if is_gate_wallet:
        return "Gate.io"

    # No match found - return Unknown instead of guessing
    return "Unknown"
