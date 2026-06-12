"""Crypto domain entities for tax reporting.

Extracted from crypto_reporting.py (Task 1 of DDD refactoring).
All frozen dataclasses are domain entities representing core crypto tax concepts.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum

from ...domain.entities import OgrValidationResult
from ...infrastructure.config import DEFAULT_ZERO_BASIS_REVIEW_THRESHOLD

# Local import for validation function (required to avoid circular import)
from . import validation as _validation

from .constants import ZERO


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
        """Validate temporal validity fields and review_reason."""
        # Validate and normalize temporal fields
        normalized_service_start, normalized_from, normalized_until = (
            _validation._normalize_and_validate_temporal_fields(
                platform=self.platform,
                service_start_date=self.service_start_date,
                valid_from=self.valid_from,
                valid_until=self.valid_until,
            )
        )

        # Validate review_reason is set when review_required is True
        _validation._validate_review_reason(self.review_required, self.review_reason)

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
    # OGR validation result, populated when OGR comparison is performed.
    # This field is independent of entry-level review_required/review_reason.
    ogr_validation: OgrValidationResult | None = None

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
