"""Tax jurisdiction configuration domain model."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class TaxJurisdictionConfig:
    """Country-specific tax jurisdiction configuration.

    Attributes:
        country: ISO 3166-1 alpha-2 country code (e.g., 'PT', 'US').
        fiscal_year: The fiscal year this configuration applies to.
        exclude_loan_repayment_gains: Whether loan repayment disposals are excluded
            from capital gains (e.g., True for PT per CIRS art. 10(20)).
        zero_basis_review_threshold: Entries with zero cost basis and gain/loss at or
            above this threshold are flagged for review in the report.
    """

    country: str
    fiscal_year: int
    exclude_loan_repayment_gains: bool
    zero_basis_review_threshold: Decimal
