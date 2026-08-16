"""Crypto domain entities for tax reporting.

Extracted from crypto_reporting.py (Task 1 of DDD refactoring).
All frozen dataclasses are domain entities representing core crypto tax concepts.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Literal

from ...domain.entities import OgrValidationResult
from ...domain.transaction import (  # noqa: F401  (re-export; do not strip)
    Transaction,
    TransactionHistoryRow,
    TxCompositeKey,
    TxCorrelationKey,
    WalletKind,
)
from ...domain.treatment import Treatment  # noqa: F401  (re-export; do not strip)
from ...infrastructure.config import DEFAULT_ZERO_BASIS_REVIEW_THRESHOLD

# Local import for validation function (required to avoid circular import)
from . import validation as _validation
from .constants import ZERO
from .transaction_factory import build_transaction  # noqa: F401  (re-export; do not strip)
from .treatment_resolver import (  # noqa: F401  (re-export; do not strip)
    TreatmentConfig,
    resolve_treatment,
)
from .tx_correlation_key_resolver import TxCorrelationKeyResolver  # noqa: F401  (re-export; do not strip)
from .wallet_kind import WalletClassification  # noqa: F401  (re-export; do not strip)


class RewardTaxClassification(Enum):
    """Tax classification status for crypto rewards per Portuguese law (CRG-001, CRG-002).

    taxable_now: Reward is immediately taxable as Category E income (remuneration not in crypto form).
    deferred_by_law: Reward received as cryptoassets, taxation deferred until disposal (CIRS art. 5(11)).
    """

    TAXABLE_NOW = "taxable_now"
    DEFERRED_BY_LAW = "deferred_by_law"


class DerivativesEventType(Enum):
    """Event type for a derivatives P&L realization under CIRS art. 10(1)(e).

    PROFIT: Realized gain from a derivatives contract (futures/perpetuals/options).
    LOSS: Realized loss from a derivatives contract.

    Note: ``FEE`` is deferred until a Koinly export produces an OGR row whose description
    or TH counterpart explicitly identifies a futures fee distinct from realized P&L.
    See the plan's Monitor section (item 1).
    """

    PROFIT = "profit"
    LOSS = "loss"


@dataclass(frozen=True)
class ParsedOgrRow:
    """Single normalized row from the Koinly Other Gains Report (OGR) CSV.

    Produced by ``_parse_other_gains_row`` (Task 6) and consumed by
    ``classify_derivatives_event`` (Task 5) and ``_build_ogr_index`` (Task 6).
    The OGR CSV columns are ``Date,Asset,Amount,Value (EUR),Type,Wallet Name``;
    this dataclass carries the parsed, normalized fields downstream consumers
    need, so neither the classifier nor the index builder re-parse the raw row.

    Attributes:
        date: ISO-format realization date (``YYYY-MM-DD``), produced by
            ``format_datetime`` at parse time so downstream consumers receive a
            normalized string key directly.
        asset: Normalized asset ticker (e.g., "USDT"), produced by
            ``normalize_asset_ticker`` at parse time.
        gain_loss: The OGR ``Value (EUR)`` column. For ``Loss`` rows this is the
            disposal proceeds (a positive EUR value, but parsed with the sign
            from the ``Amount`` column so it is typically negative for
            disposals); for ``Profit`` rows this is the realized P&L (positive).
            The classifier compares ``abs(gain_loss)`` against CG
            ``proceeds_eur`` because both quantities describe the disposal
            value, not the realized gain.
        row_type: Literal ``"Profit"`` or ``"Loss"`` from the OGR ``Type``
            column. Drives the classifier's primary branch.
        wallet: Normalized platform/wallet name (e.g., "ByBit"), produced by
            ``normalize_platform_name`` at parse time.
    """

    date: str
    asset: str
    gain_loss: Decimal
    row_type: str
    wallet: str


@dataclass(frozen=True)
class DerivativesClassification:
    """Sealed classification result for a single OGR row.

    Variants are produced via the class-method constructors ``Derivatives()``, ``Spot()``,
    and ``Ambiguous()``. Each variant carries a ``kind`` discriminator and a human-readable
    ``reason``. The classifier (``classify_derivatives_event``) returns one of these three
    variants; downstream code routes by ``kind`` so spot and derivatives rows are never
    conflated (sealed-class sentinel pattern).

    Note: ``holding_period`` is intentionally absent because art. 10(1)(e) derivatives have
    no 365-day exemption (unlike art. 10(1)(k) cryptoassets); all derivatives realizations
    are taxed regardless of holding duration.
    """

    kind: str
    reason: str

    @classmethod
    def Derivatives(cls, reason: str) -> DerivativesClassification:  # noqa: N802
        """Construct the Derivatives variant: OGR row is a derivatives realization."""
        return cls(kind="derivatives", reason=reason)

    @classmethod
    def Spot(cls, reason: str) -> DerivativesClassification:  # noqa: N802
        """Construct the Spot variant: OGR row is a spot fee disposal with a CG counterpart."""
        return cls(kind="spot", reason=reason)

    @classmethod
    def Ambiguous(cls, reason: str) -> DerivativesClassification:  # noqa: N802
        """Construct the Ambiguous variant: OGR/CG mismatch, requires manual review."""
        return cls(kind="ambiguous", reason=reason)


@dataclass(frozen=True)
class DerivativesPnLEntry:
    """Single realized P&L row from a derivatives contract, reported under CIRS art. 10(1)(e).

    Note: ``holding_period`` is intentionally absent because art. 10(1)(e) derivatives have
    no 365-day exemption (unlike art. 10(1)(k) cryptoassets); all derivatives realizations
    are taxed regardless of holding duration.

    Attributes:
        date: ISO-formatted realization date (YYYY-MM-DD).
        asset: Normalized asset ticker (e.g., "USDT").
        platform: Normalized platform/wallet name (e.g., "ByBit").
        pnl_eur: Realized profit (positive) or loss (negative) in EUR.
        event_type: PROFIT or LOSS, used as part of the aggregation key so a profit and a
            fee on the same day do not collapse into a misleading net.
        source_ref: Audit reference back to the source row (e.g., "OGR:2025-01-12:USDT").
        legal_category: Legal basis citation; defaults to art. 10(1)(e). Retained for
            audit/programmatic access; not currently rendered to the workbook (the
            per-sheet detail line that rendered it was removed when routing moved to
            the per-row Annex/Codigo columns).
        review_required: True when classification was ambiguous; triggers "YES: <reason>".
        review_reason: Specific actionable reason when review_required is True.
        annex_hint: IRS Anexo routing hint. Resolved per (taxpayer jurisdiction,
            counterparty residency) by the OGR handler: PT + PT-resident operator ->
            ``"G/Q13"``; PT + any other operator -> ``"J/Q9.2.B"``; non-PT -> blank.
            Defaults to the neutral blank (no PT hint without a PT jurisdiction).
        operation_code: Operation code from Tabela de Códigos. Resolved alongside
            ``annex_hint``: PT resident -> ``G51`` (instrumentos financeiros derivados);
            PT non-resident -> ``G30``; non-PT -> blank. Defaults to blank.
        operator_entity: Operator entity from ``resolve_operator_origin()``; empty until
            the OGR handler populates it. Raw wallet name is used for unmapped platforms.
        operator_country: Resolved counterparty country code (Tabela X); ``"UNKNOWN"`` for
            unmapped platforms. Empty until the OGR handler populates it.
        event_count: Number of underlying OGR rows aggregated into this entry; ``1`` for
            non-aggregated entries. Summed during aggregation.
        notes: Free-form user-annotation column (classification reason for ambiguous rows;
            blank otherwise). The pipeline does NOT auto-populate notes.
    """

    date: str
    asset: str
    platform: str
    pnl_eur: Decimal
    event_type: DerivativesEventType
    source_ref: str
    legal_category: str = "CIRS art. 10(1)(e)"
    review_required: bool = False
    review_reason: str = ""
    # IRS Anexo routing hint. Resolved per (country, counterparty residency) by the OGR
    # handler; defaults to the neutral blank (no PT hint without a PT jurisdiction).
    annex_hint: str = ""
    # Operation code from Tabela de Códigos. Resolved alongside annex_hint by the OGR
    # handler; defaults to the neutral blank.
    operation_code: str = ""
    # Operator entity/country from resolve_operator_origin(); empty until OGR handler populates.
    operator_entity: str = ""
    operator_country: str = ""
    # Number of underlying OGR rows aggregated into this entry; 1 for non-aggregated.
    event_count: int = 1
    # Free-form notes (classification reason for ambiguous rows; blank otherwise).
    notes: str = ""


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
    # Platform-level WalletKind (CEX/DEX) sourced from the per-platform
    # _PLATFORM_KIND mapping in operator_origin.py. Default None so existing
    # constructors do not break; consumed by the production WalletKind
    # registry adapter (Phase D Task 1).
    wallet_kind: WalletKind | None = None

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


@dataclass
class CryptoDecisionCounts:
    """Mutable accumulator of run-specific crypto-pipeline decision counts.

    Carries per-run counts of methodology decisions (sub-1-EUR materiality
    filter drops; derivatives/fee dedup removals) from the pipeline passes to
    the Assumptions & Methodology sheet writer. Created once at the top of
    ``load_koinly_crypto_report`` (INV-4a: NON-frozen so the dedup passes can
    set their own field in-pass before the ``CryptoTaxReport`` is constructed).
    Each field is set by EXACTLY ONE pass (set-not-increment; auditable).

    Fields:
        sub_1_eur_filtered: Capital-gain lines dropped by the PT-C-028 sub-1-EUR
            materiality filter (set by ``load_koinly_crypto_report`` at the W10 site).
        sub_1_eur_retained: Capital-gain lines retained after the sub-1-EUR filter
            (set alongside ``sub_1_eur_filtered`` at the W10 site).
        derivatives_dedup_removed: Lots removed by the derivatives CG dedup pass
            (set by ``th_lot_matcher.remove_matched_lots`` via W6; Task 6).
        fee_dedup_removed: Lots removed by the fee CG dedup pass
            (set by ``fee_filter.remove_transaction_fees`` via W7; Task 7).
    """

    sub_1_eur_filtered: int = 0
    sub_1_eur_retained: int = 0
    derivatives_dedup_removed: int = 0
    fee_dedup_removed: int = 0


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
    # Minute-precision ISO timestamp (YYYY-MM-DD HH:MM) of the disposal event.
    # Used by the derivatives CG/TH deduplication filter to match CG lots to TH
    # events when multiple same-day disposals occur. Optional with default None
    # for backward compatibility; day-level disposal_date is retained as-is.
    disposal_timestamp: str | None = None

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
    balance_detail: str | None = None


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
        income_code: Official Modelo 3 income code for the reward type (e.g., "E25"
            for the PT interest family under PT jurisdiction; "" when no code applies).
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
class WalletSourceProvenance:
    """Per-wallet source provenance for the Crypto Reconciliation sheet.

    One row per wallet that contributed to the run's merged Transaction
    History, recording whether that wallet's rows came from Koinly (the
    ``Aggregator`` source) or the on-chain-native path (``OnChainExplorer``,
    Plan Task 11). Populated only when ``on_chain_th_wallets`` lists at least
    one wallet; the Koinly-only path leaves ``per_wallet_source_provenance``
    empty so today's reconciliation sheet is byte-identical.

    Attributes:
        wallet_label: The wallet label (matched against Koinly TH
            ``Sending Wallet`` / ``Receiving Wallet`` and the on-chain CSV
            ``wallet_label``).
        source_kind: ``"koinly"`` (Aggregator) or ``"on_chain"``
            (OnChainExplorer). Closed literal set; the reconciliation sheet
            renders this verbatim.
        row_count: Number of Transaction-History rows this source contributed
            for this wallet in this run.
    """

    wallet_label: str
    source_kind: Literal["koinly", "on_chain"]
    row_count: int


@dataclass(frozen=True)
class OnChainDeltaBlock:
    """Koinly-vs-on-chain reconciliation delta for the opted-in wallets.

    Rendered as a delta block on the Crypto Reconciliation sheet when
    ``on_chain_th_wallets`` is set (Plan Task 12 / M3). Carries the counts of
    rows the on-chain path reclassified or added vs the Koinly baseline plus a
    small sample of on-chain tx hashes for audit drill-down. Populated only on
    the opted-in path; ``on_chain_delta`` is ``None`` on the Koinly-only path.

    Attributes:
        rows_reclassified: Rows the on-chain path substituted for Koinly TH
            rows on the opted-in wallet(s) (the Koinly rows dropped by the
            merge in ``_merge_on_chain_into_koinly_th``).
        rewards_added: On-chain Reward Events with no Koinly counterpart (e.g.
            gas-only claims Koinly collapsed/dropped; multi-token reward
            claims split per asset).
        gas_added: On-chain gas legs surfaced (Koinly drops gas for shared
            txs; the native model emits ``GasBurn`` Events so PT-deductible
            gas isn't lost).
        lp_reclassified: LP-token rows reclassified Koinly->on-chain (the
            adapter projects LiquidityDeposit/Withdraw Events the lossy
            Koinly shape collapsed).
        sample_hashes: A small, order-preserving sample of on-chain tx hashes
            involved in the delta, for manual drill-down. Bounded (not the
            full set) to keep the sheet readable.
    """

    rows_reclassified: int
    rewards_added: int
    gas_added: int
    lp_reclassified: int
    sample_hashes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class OnChainReconciliationRecord:
    """Handoff record from the on-chain TH substitution path to the crypto loader.

    Plan Task 12: produced by ``_maybe_substitute_on_chain_th`` /
    ``_merge_on_chain_into_koinly_th`` and consumed by
    ``load_koinly_crypto_report``.

    Carries the per-wallet source provenance and the Koinly-vs-on-chain delta
    block produced by ``_maybe_substitute_on_chain_th`` /
    ``_merge_on_chain_into_koinly_th``. ``load_koinly_crypto_report`` threads
    this onto ``CryptoReconciliationSummary.per_wallet_source_provenance`` and
    ``.on_chain_delta`` so the Crypto Reconciliation sheet can render the new
    sections.

    A ``None`` handoff (the Koinly-only path) leaves both new fields at their
    defaults (empty list / None), so today's sheet is byte-identical.
    """

    per_wallet_source_provenance: list[WalletSourceProvenance]
    on_chain_delta: OnChainDeltaBlock | None



@dataclass(frozen=True)
class CryptoReconciliationSummary:
    """Control totals for capital and income sections.

    Note: capital_rows counts aggregated capital gain entries only.

    The two on-chain fields (Plan Task 12) are LAST and DEFAULT to their empty
    values so today's Koinly-only construction sites keep working and the
    reconciliation sheet is byte-identical when ``on_chain_th_wallets`` is
    unset (Task 1 characterization stays GREEN). They are populated only on
    the opted-in path (main.py -> ``load_koinly_crypto_report`` -> here).
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
    # Per-wallet source provenance (Plan Task 12 / M3). Empty on the Koinly-only
    # path; populated with one ``WalletSourceProvenance`` per wallet when
    # ``on_chain_th_wallets`` lists at least one wallet.
    per_wallet_source_provenance: list[WalletSourceProvenance] = field(default_factory=list)
    # Koinly-vs-on-chain delta block (Plan Task 12 / M3). ``None`` on the
    # Koinly-only path; populated when ``on_chain_th_wallets`` is set.
    on_chain_delta: OnChainDeltaBlock | None = None


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
    """Entry requiring manual review.

    Attributes:
        source_section: The report section that produced the review row. One of
            ``"capital_gains"`` (produced by ``correct_payment_proceeds`` and
            ``derivatives_filter`` for CG-side review, and by
            ``fee_filter.flag_fee_suspects`` when a suspect correlates to a CG
            lot), ``"income"`` (produced by reward-income side review rows), or
            ``"transaction_history"`` (produced by
            ``fee_filter.flag_fee_suspects`` when a suspect has no CG line, so
            it is surfaced from the Transaction History side).
        date: ISO-format date (``YYYY-MM-DD``) or minute-precision timestamp.
        asset: Asset ticker.
        platform: Platform/wallet name.
        review_reason: Human-readable, actionable review reason.
        is_suspicious: True only when the asset contains non-Latin characters
            (homoglyph scam-token detection via
            ``contains_non_latin_characters``); applying it to an
            unlisted-asset fee suspect conflates missing configuration with
            scam detection and triggers alarming red/bold formatting.
    """

    source_section: Literal[
        "capital_gains", "income", "transaction_history", "derivatives"
    ]
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
    decision_counts: CryptoDecisionCounts = field(default_factory=CryptoDecisionCounts)
    skipped_zero_value_tokens: list[CryptoSkippedZeroValueToken] = field(default_factory=list)
    # Authoritative audit trail of zero-value DEFERRED_BY_LAW reward rows removed from
    # ``reward_entries`` at parse time (CRG-022). Full ``CryptoRewardIncomeEntry`` objects
    # (NOT count-only) per Invariant 1 (list preservation): the Section 3 suppressed-rewards
    # block renders per-``(asset, wallet)`` from this list. Distinct from
    # ``skipped_zero_value_tokens`` above, which is count-only and fed by the ``is_known``
    # gate's else-branch (unknown-asset zero-value rows); this list is fed by the
    # deferred + zero-value branch and retains every skipped row with full fidelity.
    skipped_zero_value_deferred_rewards: list[CryptoRewardIncomeEntry] = field(default_factory=list)
    loan_activity: list[LoanActivityEntry] = field(default_factory=list)
    fifo_rebuild_assets: frozenset[str] = field(default_factory=frozenset)
    zero_basis_review_threshold: Decimal = field(default_factory=lambda: DEFAULT_ZERO_BASIS_REVIEW_THRESHOLD)
    pdf_summary: CryptoCompletePdfSummary | None = None
    review_entries: list[CryptoReviewEntry] = field(default_factory=list)
    derivatives_entries: list[DerivativesPnLEntry] = field(default_factory=list)
