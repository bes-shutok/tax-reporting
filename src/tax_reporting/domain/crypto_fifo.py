"""Domain entities for the FIFO engine for crypto capital gains.

These types represent the core domain concepts for FIFO matching of loan-affected
crypto assets under Portuguese tax law (CIRS art. 10(20)).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

__all__ = ["CryptoAcquisition", "CryptoConsumption", "CryptoFifoRealization", "AssetFifoResult"]


@dataclass(frozen=True)
class CryptoAcquisition:
    """Acquisition of a loan-affected asset from a non-loan TH event."""

    date: str
    asset: str
    amount: Decimal
    cost_basis_eur: Decimal
    fee_eur: Decimal
    source_type: str
    wallet: str
    platform: str
    review_required: bool
    review_reason: str | None = None

    def __post_init__(self) -> None:
        """Enforce review_reason invariant."""
        if self.review_required and not self.review_reason:
            raise ValueError(
                f"CryptoAcquisition review_reason must be set when review_required=True"
                f" (asset={self.asset}, date={self.date})"
            )


@dataclass(frozen=True)
class CryptoConsumption:
    """Consumption (disposal or exchange-out) of a loan-affected asset."""

    date: str
    asset: str
    amount: Decimal
    proceeds_eur: Decimal
    event_type: str
    taxable: bool
    wallet: str
    platform: str
    notes: str
    review_required: bool
    review_reason: str | None = None
    # Minute-precision ISO timestamp (YYYY-MM-DD HH:MM) of the disposal event.
    # Propagated through CryptoFifoRealization into CryptoCapitalGainEntry so the
    # derivatives CG/TH deduplication filter can match same-day disposals.
    disposal_timestamp: str | None = None

    def __post_init__(self) -> None:
        """Enforce review_reason invariant."""
        if self.review_required and not self.review_reason:
            raise ValueError(
                f"CryptoConsumption review_reason must be set when review_required=True"
                f" (asset={self.asset}, date={self.date})"
            )


@dataclass(frozen=True)
class CryptoFifoRealization:
    """Single FIFO-matched realization row produced by the FIFO engine."""

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
    notes: str
    review_required: bool
    review_reason: str | None = None
    # Minute-precision ISO timestamp (YYYY-MM-DD HH:MM) of the disposal event,
    # propagated from the originating CryptoConsumption. Used by the derivatives
    # CG/TH deduplication filter for same-day disposal matching.
    disposal_timestamp: str | None = None

    def __post_init__(self) -> None:
        """Enforce review_reason invariant."""
        if self.review_required and not self.review_reason:
            raise ValueError(
                f"CryptoFifoRealization review_reason must be set when review_required=True"
                f" (asset={self.asset}, disposal_date={self.disposal_date})"
            )


@dataclass(frozen=True)
class AssetFifoResult:
    """FIFO matching result for a single (asset, platform) pair."""

    realizations: list[CryptoFifoRealization]
    carryover_cost_by_tx_key: dict[str, Decimal]
    partial_carryover_tx_keys: frozenset[str] = field(default_factory=frozenset)
    # Count of taxable disposals that had no matching acquisition at or before the
    # disposal date (pool exhausted OR earliest available lot is after disposal).
    # Pattern F: summed across all (asset, platform) results in
    # ``_rebuild_fifo_for_loan_affected_assets`` to emit ONE aggregate INFO.
    unmatched_taxable_count: int = 0
    # Count of acquisitions with amount <= 0 skipped during FIFO pool construction
    # (``compute_fifo_for_asset`` pool-construction branch, per-row DEBUG
    # ``"Skipping non-positive acquisition for"``; Bucket C). Pattern F
    # count-only shape: summed across all (asset, platform) results in
    # ``_rebuild_fifo_for_loan_affected_assets`` to emit ONE aggregate WARNING.
    # STAYS WARNING (silent data loss, no Excel surface).
    non_positive_acq_count: int = 0
    # Count of negative-amount consumption events skipped by the ``remaining < ZERO``
    # early-return guard in ``_consume_against_pool_inplace`` (per-row DEBUG
    # ``"Negative consumption amount"``; Bucket C). Same Pattern F shape: threaded
    # via ``negative_consumption_counter`` alongside ``unmatched_taxable_counter``,
    # summed across all (asset, platform) results and emitted as ONE aggregate
    # WARNING. STAYS WARNING (silent data loss).
    negative_consumption_count: int = 0
    # Count of taxable realizations whose acquisition and/or disposal date carried an
    # epoch sentinel (empty or ``1970-`` date) at ``_build_taxable_realization``
    # (the ``is_epoch_acq``/``is_epoch_con`` detection, per-row DEBUG
    # ``"Empty or epoch acquisition date"`` / ``"Empty or epoch disposal date"``;
    # Bucket B). Threaded via ``epoch_counter`` through the leaf ->
    # ``_consume_against_pool_inplace`` -> here, summed across all (asset, platform)
    # results and emitted as ONE aggregate INFO. The realization's
    # ``review_required`` (set via ``or is_epoch_acq``/``or is_epoch_con``) is the
    # canonical Excel audit surface; the aggregate INFO is a console nicety.
    epoch_date_count: int = 0
    # Count of taxable realizations that consumed an UNRESOLVED deferred acquisition
    # (``source_type="exchange_in_deferred"`` retained via the unresolved branch of
    # ``cross_asset._resolve_single_acquisition``) at ``_build_taxable_realization``
    # (the ``is_deferred_acq`` branch, per-row DEBUG ``"uses unresolved deferred
    # acquisition"``; Bucket B -- realization-time consequence, NOT a double-count of
    # Pattern J which names resolution-time causes). Threaded via
    # ``deferred_consumed_counter`` alongside ``epoch_counter``, summed across all
    # (asset, platform) results and emitted as ONE aggregate INFO with wording DISTINCT
    # from Pattern J's "cross-asset deferred acquisition(s) flagged".
    deferred_consumed_count: int = 0
