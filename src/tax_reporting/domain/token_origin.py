"""Token origin resolution domain types.

Provides pure domain types for representing how a token was acquired.
The application-layer resolver (``TokenOriginResolver``) lives in
``tax_reporting.application.token_origin``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AcquisitionMethod(Enum):
    """Method by which a token was acquired, derived from Koinly transaction history."""

    DIRECT_PURCHASE = "direct_purchase"
    SWAP_CONVERSION = "swap_conversion"
    BRIDGE_TRANSFER = "bridge_transfer"
    DEFI_YIELD = "defi_yield"
    REWARD = "reward"
    AIRDROP = "airdrop"
    LIQUIDITY_WITHDRAWAL = "liquidity_withdrawal"
    LIQUIDITY_PROVISION = "liquidity_provision"
    TRANSFER = "transfer"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class TokenOrigin:
    """Deterministic origin of a token acquired via Koinly-tracked transactions.

    Populated from implicit (date, asset, wallet) correlation between the capital
    gains report and transaction history. This is NOT a direct foreign-key link;
    confidence reflects the strength of the correlation.
    """

    acquired_from_asset: str
    acquired_from_platform: str
    acquisition_method: AcquisitionMethod
    confidence: str

    @classmethod
    def unknown(cls) -> TokenOrigin:
        """Return the canonical unknown-origin sentinel."""
        return cls(
            acquired_from_asset="Unknown",
            acquired_from_platform="Unknown",
            acquisition_method=AcquisitionMethod.UNKNOWN,
            confidence="low",
        )

    def __str__(self) -> str:
        """Format origin as 'FROM_ASSET (method, confidence confidence)' or blank for unknown."""
        if self.acquisition_method == AcquisitionMethod.UNKNOWN:
            return ""
        return f"{self.acquired_from_asset} ({self.acquisition_method.value}, {self.confidence} confidence)"
