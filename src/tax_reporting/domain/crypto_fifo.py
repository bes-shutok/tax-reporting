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
