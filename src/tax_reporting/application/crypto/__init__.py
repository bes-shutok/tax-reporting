"""Crypto reporting package - domain entities for backward compatibility.

This package is organized following Domain-Driven Design principles.
Domain entities are re-exported from here for convenience.

Functions and helpers are available directly from their submodules:
- tax_reporting.application.crypto.aggregation
- tax_reporting.application.crypto.classification
- tax_reporting.application.crypto.validation
- tax_reporting.application.crypto.parsing
- tax_reporting.application.crypto.ogr_handler
- tax_reporting.application.crypto.loan_activity
- tax_reporting.application.crypto.operator_origin
- tax_reporting.application.crypto.fifo_helpers
- tax_reporting.application.crypto.chain_derivation
"""

from tax_reporting.application.crypto.entities import (
    AggregatedRewardIncomeEntry,
    CapitalGainPeriodStats,
    CryptoCapitalGainEntry,
    CryptoCapitalGainStats,
    CryptoCompletePdfSummary,
    CryptoReconciliationSummary,
    CryptoReviewEntry,
    CryptoRewardIncomeEntry,
    CryptoSkippedZeroValueToken,
    CryptoTaxReport,
    HoldingsSnapshot,
    LoanActivityEntry,
    OperatorOrigin,
    RewardTaxClassification,
)

__all__ = [
    "RewardTaxClassification",
    "OperatorOrigin",
    "CapitalGainPeriodStats",
    "CryptoCapitalGainStats",
    "CryptoCapitalGainEntry",
    "LoanActivityEntry",
    "CryptoRewardIncomeEntry",
    "AggregatedRewardIncomeEntry",
    "HoldingsSnapshot",
    "CryptoReconciliationSummary",
    "CryptoSkippedZeroValueToken",
    "CryptoCompletePdfSummary",
    "CryptoReviewEntry",
    "CryptoTaxReport",
]
