"""Tax jurisdiction configuration domain model."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

DEFAULT_ZERO_BASIS_REVIEW_MIN_PROCEEDS: Decimal = Decimal("10")


@dataclass(frozen=True)
class TaxJurisdictionConfig:
    """Country-specific tax jurisdiction configuration.

    Attributes:
        country: ISO 3166-1 alpha-2 country code (e.g., 'PT', 'US').
        fiscal_year: The fiscal year this configuration applies to.
        exclude_loan_repayment_gains: Whether loan repayment disposals are excluded
            from capital gains (e.g., True for PT per CIRS art. 10(20)).
        zero_basis_review_threshold: Gain/loss magnitude gate (EUR). Presentation-layer
            control that triggers Excel red fill on the transaction row for zero-basis
            entries whose gain/loss magnitude meets this threshold. Set per
            jurisdiction via config.ini; the dataclass has no default (callers must
            decide). Distinct from ``zero_basis_review_min_proceeds``, which gates the
            ``review_required`` flag at parse time by proceeds magnitude.
        zero_basis_review_min_proceeds: Proceeds magnitude gate (EUR). Application-layer
            control that gates the ``review_required`` flag at parse time. Zero-cost
            entries with proceeds below this value are not flagged for review (FEE token
            noise, small rewards). Defaults to ``DEFAULT_ZERO_BASIS_REVIEW_MIN_PROCEEDS``
            (10 EUR) so direct dataclass construction matches the loaded config; set to
            ``Decimal("0")`` to restore prior flag-everything behavior.
        futures_derivatives_taxable: Whether futures and derivatives liquidations are
            treated as taxable disposals (e.g., True for PT per CIRS art. 10(1)(e)).
        use_other_gains_report: Whether the jurisdiction uses Koinly Other Gains Report
            classifications (e.g., True for certain futures/derivatives treatments).
        separate_derivatives_reporting: Whether derivatives P&L is reported separately
            from spot crypto (e.g., True for PT per DP-012; CIRS art. 10(1)(e) covers
            derivatives with no 365-day exemption, while spot retains art. 10(1)(k)).
    """

    country: str
    fiscal_year: int
    exclude_loan_repayment_gains: bool
    zero_basis_review_threshold: Decimal
    zero_basis_review_min_proceeds: Decimal = DEFAULT_ZERO_BASIS_REVIEW_MIN_PROCEEDS
    futures_derivatives_taxable: bool = False
    use_other_gains_report: bool = False
    separate_derivatives_reporting: bool = False
