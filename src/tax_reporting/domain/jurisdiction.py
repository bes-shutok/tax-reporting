"""Tax jurisdiction configuration domain model."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from zoneinfo import ZoneInfo

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
        infer_payment_proceeds: Whether to correct the realization value (valor de
            realização) of Koinly-tagged ``Payment``/``Card Payment`` disposals whose
            CG ``proceeds_eur == 0`` because Koinly's price DB had no match for the
            imported ticker. Legal basis: PT-C-004 (a goods/services purchase paid in
            crypto is a taxable alienação onerosa - the disposal stays taxable) and
            PT-C-007 (the realization value equals the fair market value of the crypto
            spent). Resolution is three-tier: (1) primary - trust Koinly's own TH
            ``Net Value (EUR)`` when present (works for any asset Koinly prices,
            including USD-pegged stablecoins); (2) stablecoin fallback when
            ``Net Value == 0`` - EUR par for configured EUR-pegged stablecoins
            (e.g. EURC/EUROC/EURT), or the fiscal year-end peg->EUR rate conversion
            for non-EUR-pegged stablecoins whose peg currency has an
            ``[EXCHANGE RATES]`` rate (the same source shares/dividends use); both
            fallbacks are ``review_required=True`` approximations of the disposal-date
            FMV; (3) review flag for non-EUR stablecoins whose peg has no config rate
            and for non-stablecoins. See decision point DP-014.
        timezone: Resolved IANA timezone (``ZoneInfo``) of the jurisdiction, used to localize
            naive Koinly dates (CG/OGR/Income, which are mainland-Portugal local time per
            WET/WEST) to a true-UTC instant at ingestion so cross-report match keys agree.
            Defaults to ``Europe/Lisbon`` for PT when ``IANA_TIMEZONE`` is absent from
            ``config.ini``; ``None`` for non-PT countries without an explicit key (naive dates
            then keep the legacy UTC-stamp behavior). Resolved exactly once at config-load and
            passed to the parser as a value object; never re-constructed at call sites.
    """

    country: str
    fiscal_year: int
    exclude_loan_repayment_gains: bool
    zero_basis_review_threshold: Decimal
    zero_basis_review_min_proceeds: Decimal = DEFAULT_ZERO_BASIS_REVIEW_MIN_PROCEEDS
    futures_derivatives_taxable: bool = False
    use_other_gains_report: bool = False
    separate_derivatives_reporting: bool = False
    infer_payment_proceeds: bool = False
    timezone: ZoneInfo | None = None
