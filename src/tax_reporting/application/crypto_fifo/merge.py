"""Application-layer DTO for merged per-platform FIFO carry-over results."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from ...domain.crypto_fifo import TxKey


@dataclass(frozen=True)
class MergedAssetFifoResult:
    """Per-asset carry-over after merging per-platform FIFO results.

    Unlike AssetFifoResult (single-platform output keyed directly by ``tx_key``),
    this uses ``(tx_key, platform)`` tuple keys so downstream cross-asset
    resolution can identify which sender platform each carry-over cost originated
    from. NOTE (Plan 2026-08-02 Task 3 / review F2-r2): the OUTER key here is
    always a 2-tuple ``(tx_key, platform)``; ``TxKey`` is the INNER element
    (the ``tx_key``), NOT the outer key. Widening the outer annotation to
    ``dict[TxKey, Decimal]`` would be wrong; it stays ``dict[tuple[TxKey, str], Decimal]``.
    """

    carryover_cost_by_tx_key: dict[tuple[TxKey, str], Decimal]
    partial_carryover_tx_keys: frozenset[TxKey]
