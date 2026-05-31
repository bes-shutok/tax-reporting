"""Application-layer DTO for merged per-platform FIFO carry-over results."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class MergedAssetFifoResult:
    """Per-asset carry-over after merging per-platform FIFO results.

    Unlike AssetFifoResult (single-platform output with string tx_key keys),
    this uses (tx_key, platform) tuple keys so downstream cross-asset resolution
    can identify which sender platform each carry-over cost originated from.
    """

    carryover_cost_by_tx_key: dict[tuple[str, str], Decimal]
    partial_carryover_tx_keys: frozenset[str]
