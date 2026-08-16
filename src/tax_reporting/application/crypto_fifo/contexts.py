"""Context types for the crypto FIFO engine.

AcquisitionContext and ConsumptionContext wrap domain-layer types with Koinly
correlation metadata (tx_key, source_row_index). ParsedTxRow is an immutable
carrier for the read-only fields parsed from a single TH CSV row.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Final

from ...domain.crypto_fifo import CryptoAcquisition, CryptoConsumption, TxKey

ZERO: Final = Decimal("0")

LOAN_TAGS: Final[frozenset[str]] = frozenset({"loan", "loan repayment", "loan fee"})

#: ``TxKey`` is re-exported here (imported from the domain layer) so the
#: application-layer FIFO modules annotate with one canonical alias. The
#: canonical definition lives in ``domain/crypto_fifo.py`` so the domain layer
#: can annotate with it without reversing the domain -> application dependency
#: direction. See its docstring there.


@dataclass(frozen=True)
class AcquisitionContext:
    """Application-layer wrapper for CryptoAcquisition with Koinly correlation metadata.

    Carries tx_key and source_row_index for FIFO correlation lookups.
    """

    acq: CryptoAcquisition
    tx_key: TxKey
    source_row_index: int

    def with_acq(self, **kwargs) -> AcquisitionContext:
        """Return new AcquisitionContext with inner acq fields updated."""
        return AcquisitionContext(
            acq=replace(self.acq, **kwargs),
            tx_key=self.tx_key,
            source_row_index=self.source_row_index,
        )


@dataclass(frozen=True)
class ConsumptionContext:
    """Application-layer wrapper for CryptoConsumption with Koinly correlation metadata."""

    con: CryptoConsumption
    tx_key: TxKey
    source_row_index: int

    def with_con(self, **kwargs) -> ConsumptionContext:
        """Return new ConsumptionContext with inner con fields updated."""
        return ConsumptionContext(
            con=replace(self.con, **kwargs),
            tx_key=self.tx_key,
            source_row_index=self.source_row_index,
        )


@dataclass(frozen=True)
class ParsedTxRow:
    """Immutable carrier for the 18 read-only fields parsed from a single TH CSV row.

    Grouped to collapse wide keyword-only signatures in _classify_th_row,
    _handle_exchange, _emit_*, and _handle_transfer.
    """

    row: dict[str, str]
    row_index: int
    date_str: str
    tx_key: TxKey
    row_type: str
    sent_currency: str
    received_currency: str
    fee_currency: str
    sent_amount: Decimal
    received_amount: Decimal
    sent_cost_basis: Decimal
    net_value: Decimal
    fee_amount: Decimal
    fee_value: Decimal
    sent_affected: bool
    received_affected: bool
    fee_affected: bool
    loan_affected_assets: frozenset[str]
    # Minute-precision ISO timestamp (YYYY-MM-DD HH:MM) parsed from the TH Date.
    # Carries through to CryptoConsumption.disposal_timestamp for FIFO-derived
    # CG entries so the derivatives CG/TH deduplication filter can match same-day
    # disposals at minute precision. Seconds are truncated.
    timestamp_str: str | None = None
