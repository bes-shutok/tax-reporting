"""Crypto FIFO engine package.

Re-exports public symbols so that external callers (``crypto_reporting.py``, tests)
can import the stable public API from ``tax_reporting.application.crypto_fifo``.
Private helpers live in their respective submodules and must be imported directly
from those modules (e.g. ``from .crypto_fifo.parsing import _build_composite_tx_key``).
"""

from .contexts import AcquisitionContext, ConsumptionContext, ParsedTxRow
from .cross_asset import resolve_cross_asset_exchanges
from .matching import compute_fifo_for_asset
from .merge import MergedAssetFifoResult
from .parsing import discover_loan_affected_assets, parse_th_for_loan_affected_assets

__all__ = [
    "AcquisitionContext",
    "ConsumptionContext",
    "ParsedTxRow",
    "compute_fifo_for_asset",
    "discover_loan_affected_assets",
    "parse_th_for_loan_affected_assets",
    "resolve_cross_asset_exchanges",
    "MergedAssetFifoResult",
]
