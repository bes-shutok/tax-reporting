"""RED tests for ``correct_payment_proceeds`` (DP-014, Task 1).

These tests are EXPECTED TO FAIL at import: the production module
``src/tax_reporting/application/crypto/payment_proceeds.py`` does not exist yet
(it is built in Task 4). The collection-time ``ModuleNotFoundError`` is the
correct RED signal.

Task 1 covers the four proceeds-resolution tiers of ``correct_payment_proceeds``:
  1. priced payment uses Koinly Net Value (primary)
  2. unpriced EUR-stablecoin falls back to par (amount @ 1 EUR)
  3. Net Value takes precedence over the par fallback (fixed resolution order)
  4. gain is recomputed from (proceeds - cost), not left at the phantom -cost

All fixtures are SYNTHETIC (tickers/amounts invented for this test; no real
transaction data). The config object and the bounded ``peg_to_eur_rates`` dict
are built once at module top so the four cases stay DRY and hermetic (no
dependency on ``popular_crypto_tokens.json`` or ``config.ini``).
"""

from __future__ import annotations

import json
import logging
from decimal import Decimal
from pathlib import Path

import pytest

from tax_reporting.application.crypto.entities import (
    CryptoCapitalGainEntry,
    CryptoReviewEntry,
    OperatorOrigin,
)
from tax_reporting.application.crypto.payment_proceeds import (  # noqa: E402
    PaymentProceedsConfig,
    _derive_peg_to_eur_rates,
    _load_payment_proceeds_config_from_path,
    build_payment_tag_index,
    correct_payment_proceeds,
)
from tax_reporting.infrastructure.config import ConversionRate

# ---------------------------------------------------------------------------
# Shared hermetic fixtures (one config object + one bounded rates dict).
# ---------------------------------------------------------------------------

_CONFIG = PaymentProceedsConfig(
    payment_tags=["payment", "card payment"],
    stablecoins=frozenset({"EURST", "USDX"}),
    stablecoin_pegs={"EURST": "EUR", "USDX": "USD"},
)

# Synthetic USD->EUR rate: a round number deliberately != any plausible
# par/cost value so a peg-rate result is discriminating.
_PEG_TO_EUR_RATES = {"USD": Decimal("0.90")}

# A single reusable OperatorOrigin for the synthetic CG fixtures. None of the
# Task-1 cases exercise operator fields, so a minimal valid instance suffices.
_OPERATOR_ORIGIN = OperatorOrigin(
    platform="TestWallet",
    service_scope="crypto",
    operator_entity="TestWallet",
    operator_country="Unknown",
    source_url="",
    source_checked_on="2026-01-01",
    confidence="low",
    review_required=False,
    valid_from="2026-01-01",
)


def _make_cg_entry(  # noqa: PLR0913
    *,
    asset: str,
    amount: Decimal,
    cost_eur: Decimal,
    proceeds_eur: Decimal = Decimal("0"),
    gain_loss_eur: Decimal,
    disposal_date: str = "2025-06-15",
    wallet: str = "TestWallet",
    review_required: bool = False,
    review_reason: str = "",
) -> CryptoCapitalGainEntry:
    """Build a synthetic CryptoCapitalGainEntry for the payment-proceeds tests.

    Fields not under test use simple valid defaults. By default
    ``review_required`` is False on the INPUT entry (the feature flips it True
    on correction). The DP-013 reason-retention tests (Task 2) pass an entry
    that ALREADY carries the upstream ``_build_zero_basis_review_reason`` flag,
    so the builder accepts ``review_required`` + ``review_reason`` kwargs; the
    dataclass invariant requires ``review_reason`` when ``review_required`` is
    True.
    """
    return CryptoCapitalGainEntry(
        disposal_date=disposal_date,
        acquisition_date="2025-01-10",
        asset=asset,
        amount=amount,
        cost_eur=cost_eur,
        proceeds_eur=proceeds_eur,
        gain_loss_eur=gain_loss_eur,
        holding_period="Short term",
        wallet=wallet,
        platform=wallet,
        chain="Unknown",
        operator_origin=_OPERATOR_ORIGIN,
        annex_hint="G",
        review_required=review_required,
        review_reason=review_reason,
        notes="",
    )


def _make_th_payment_row(  # noqa: PLR0913
    *,
    sent_currency: str,
    sent_amount: str,
    net_value_eur: str,
    sending_wallet: str = "TestWallet",
    date: str = "2025-06-15 12:00:00 UTC",
    tag: str = "Payment",
) -> dict[str, str]:
    """Build a synthetic Koinly Transaction History row tagged ``Payment``.

    The matcher keys on (day, asset, platform, amount_6dp). The columns that
    feed the key are ``Date`` (calendar day), ``Sent Currency`` (asset),
    ``Sending Wallet`` (platform), ``Sent Amount`` (amount). ``Net Value (EUR)``
    is the tier-1 proceeds source parsed via ``parse_koinly_decimal``.
    """
    return {
        "Date": date,
        "Type": "trade",
        "Tag": tag,
        "Sending Wallet": sending_wallet,
        "Receiving Wallet": "",
        "Sent Amount": sent_amount,
        "Sent Currency": sent_currency,
        "Received Amount": "",
        "Received Currency": "",
        "Fee Amount": "",
        "Fee Currency": "",
        "Fee Value (EUR)": "",
        "Sent Cost Basis": "",
        "Net Value (EUR)": net_value_eur,
        "TxHash": "",
    }


class TestCorrectPaymentProceedsTiers:
    """The four proceeds-resolution tiers for ``correct_payment_proceeds``."""

    def test_priced_payment_uses_koinly_net_value(self):
        """Given a priced Payment TH row, proceeds resolve to the Koinly
        ``Net Value (EUR)`` (European decimal comma), NOT to the disposal
        amount or the cost basis.

        - Input CG: asset ABC, cost 100, proceeds 0, amount 50,
          gain_loss_eur -100.00 (proceeds 0 -> phantom -cost).
        - TH ``Net Value (EUR)`` = "120,00" -> proceeds 120.00.
        - gain recomputed = 120 - 100 = 20.00 (NOT the input -100.00, so a
          "leave gain untouched" conflation fails).
        - review_required=True; review_reason names the asset ("ABC") and the
          proceeds source ("Net Value"); exactly one CryptoReviewEntry
          appended.
        """
        entry = _make_cg_entry(
            asset="ABC",
            amount=Decimal("50"),
            cost_eur=Decimal("100"),
            proceeds_eur=Decimal("0"),
            gain_loss_eur=Decimal("-100.00"),
        )
        th_rows = [
            _make_th_payment_row(
                sent_currency="ABC",
                sent_amount="50",
                net_value_eur="120,00",
            )
        ]
        review_entries: list[CryptoReviewEntry] = []

        result = correct_payment_proceeds(
            [entry],
            th_rows,
            config=_CONFIG,
            peg_to_eur_rates=_PEG_TO_EUR_RATES,
            loan_affected_assets=frozenset(),
            review_entries=review_entries,
        )

        assert len(result) == 1
        corrected = result[0]
        assert corrected.proceeds_eur == Decimal("120.00")
        assert corrected.gain_loss_eur == Decimal("20.00")
        assert corrected.review_required is True
        reason = corrected.review_reason or ""
        assert "ABC" in reason
        assert "Net Value" in reason
        assert len(review_entries) == 1
        assert review_entries[0].asset == "ABC"

    def test_unpriced_eur_stablecoin_falls_back_to_par(self):
        """Given an EUR-pegged stablecoin Payment whose ``Net Value (EUR)``
        is zero, proceeds fall back to par (amount @ 1 EUR).

        - Input CG: asset EURST (injected EUR-pegged stablecoin), cost 100,
          proceeds 0, amount 73, gain_loss_eur -100.00.
        - TH ``Net Value (EUR)`` = "0,0" -> no market rate -> par fallback.
        - proceeds = amount = 73.00 (amount 73 deliberately != cost 100 so a
          wrong ``return cost`` -> proceeds 100, gain 0 fails visibly; and a
          wrong ``return 0`` -> proceeds 0, gain -100 fails visibly).
        - gain = 73 - 100 = -27.00.
        - review_reason names the asset and "EUR par" / "no market rate".
        """
        entry = _make_cg_entry(
            asset="EURST",
            amount=Decimal("73"),
            cost_eur=Decimal("100"),
            proceeds_eur=Decimal("0"),
            gain_loss_eur=Decimal("-100.00"),
        )
        th_rows = [
            _make_th_payment_row(
                sent_currency="EURST",
                sent_amount="73",
                net_value_eur="0,0",
            )
        ]
        review_entries: list[CryptoReviewEntry] = []

        result = correct_payment_proceeds(
            [entry],
            th_rows,
            config=_CONFIG,
            peg_to_eur_rates=_PEG_TO_EUR_RATES,
            loan_affected_assets=frozenset(),
            review_entries=review_entries,
        )

        assert len(result) == 1
        corrected = result[0]
        assert corrected.proceeds_eur == Decimal("73.00")
        assert corrected.gain_loss_eur == Decimal("-27.00")
        assert corrected.review_required is True
        reason = corrected.review_reason or ""
        assert "EURST" in reason
        # Reason must indicate the par fallback / absence of a market rate.
        # AND not OR: the _eur_par_reason template emits BOTH "EUR par" and
        # "Koinly market rate", so an OR would mask a regression that dropped
        # one (the old OR passed only on "eur par"; "no market rate" was never
        # present - it is "no Koinly market rate").
        reason_lower = reason.lower()
        assert "eur par" in reason_lower
        assert "market rate" in reason_lower
        assert len(review_entries) == 1
        assert review_entries[0].asset == "EURST"

    def test_net_value_takes_precedence_over_par_fallback(self):
        """For an EUR-stablecoin Payment with a NON-ZERO ``Net Value (EUR)``,
        the Koinly Net Value wins over the par fallback. Binds the fixed
        resolution order: Net Value first, par only when Net Value == 0.

        - Input CG: asset EURST, amount 60, cost 100, gain_loss_eur -100.00.
        - TH ``Net Value (EUR)`` = "99,50" (non-zero).
        - proceeds = 99.50 (the Koinly value), NOT amount 60 and NOT cost 100.
          All three candidate values (99.50, 60, 100) are distinct so any
          wrong source fails.
        - gain = 99.50 - 100 = -0.50.
        """
        entry = _make_cg_entry(
            asset="EURST",
            amount=Decimal("60"),
            cost_eur=Decimal("100"),
            proceeds_eur=Decimal("0"),
            gain_loss_eur=Decimal("-100.00"),
        )
        th_rows = [
            _make_th_payment_row(
                sent_currency="EURST",
                sent_amount="60",
                net_value_eur="99,50",
            )
        ]
        review_entries: list[CryptoReviewEntry] = []

        result = correct_payment_proceeds(
            [entry],
            th_rows,
            config=_CONFIG,
            peg_to_eur_rates=_PEG_TO_EUR_RATES,
            loan_affected_assets=frozenset(),
            review_entries=review_entries,
        )

        assert len(result) == 1
        corrected = result[0]
        assert corrected.proceeds_eur == Decimal("99.50")
        assert corrected.gain_loss_eur == Decimal("-0.50")
        assert corrected.review_required is True

    def test_gain_recomputed_from_proceeds_minus_cost(self):
        """Given proceeds corrected to 120.00 and cost 100.00, the gain is
        recomputed as proceeds - cost = 20.00, NOT the phantom -100.00 that
        the input (proceeds 0) carried. Binds that gain is derived from the
        corrected proceeds, never left at the input value.
        """
        entry = _make_cg_entry(
            asset="ABC",
            amount=Decimal("50"),
            cost_eur=Decimal("100"),
            proceeds_eur=Decimal("0"),
            gain_loss_eur=Decimal("-100.00"),
        )
        th_rows = [
            _make_th_payment_row(
                sent_currency="ABC",
                sent_amount="50",
                net_value_eur="120,00",
            )
        ]
        review_entries: list[CryptoReviewEntry] = []

        result = correct_payment_proceeds(
            [entry],
            th_rows,
            config=_CONFIG,
            peg_to_eur_rates=_PEG_TO_EUR_RATES,
            loan_affected_assets=frozenset(),
            review_entries=review_entries,
        )

        corrected = result[0]
        # Explicit: gain must be proceeds (120.00) - cost (100.00) = 20.00,
        # never the input phantom -100.00 (proceeds 0 - cost 100).
        assert corrected.proceeds_eur == Decimal("120.00")
        assert corrected.cost_eur == Decimal("100.00")
        assert corrected.gain_loss_eur == Decimal("20.00")
        assert corrected.gain_loss_eur != Decimal("-100.00")


# The DP-013 reason the upstream ``_build_zero_basis_review_reason`` sets on a
# zero-proceeds row when ``cost > 0 AND proceeds == 0``. Task-2 reason-retention
# tests build CG entries that ALREADY carry this flag, so the feature must not
# clobber it when it leaves a row unchanged.
_DP013_REASON = (
    "Zero disposal proceeds: verify sale data (transfer error, data quality issue)"
)


class TestCorrectPaymentProceedsGuardsAndFallbacks:
    """Task 2: evidence-gate, reason retention, and the non-EUR / non-stablecoin
    fallback branches of ``correct_payment_proceeds``.

    These tests bind (a) the proceeds==0 evidence gate and DP-013 reason
    retention, (b) tag-set normalization (Card Payment), (c) the tier-2
    non-EUR-stablecoin year-end-rate conversion and its precedence / no-rate /
    malformed-rate fall-throughs, and (d) the tier-3 non-stablecoin generic
    review reason.
    """

    def test_non_payment_tag_not_corrected_retains_dp013_reason(self):
        """A TH row tagged ``Reward`` (and an empty-tag variant) must NOT be
        treated as a payment disposal: the CG entry keeps proceeds=0, gain=-cost,
        its existing DP-013 ``review_required``/``review_reason`` survive
        verbatim (not clobbered), and no correction ``CryptoReviewEntry`` is
        appended. Binds that the TH tag index is built from payment-tagged rows
        ONLY (Invariant 1) - a non-payment tag never collides into a payment slot.
        """
        entry = _make_cg_entry(
            asset="ABC",
            amount=Decimal("50"),
            cost_eur=Decimal("100"),
            proceeds_eur=Decimal("0"),
            gain_loss_eur=Decimal("-100.00"),
            review_required=True,
            review_reason=_DP013_REASON,
        )
        th_rows = [
            _make_th_payment_row(
                sent_currency="ABC",
                sent_amount="50",
                net_value_eur="120,00",
                tag="Reward",
            ),
            _make_th_payment_row(
                sent_currency="ABC",
                sent_amount="50",
                net_value_eur="120,00",
                tag="",
            ),
        ]
        review_entries: list[CryptoReviewEntry] = []

        result = correct_payment_proceeds(
            [entry],
            th_rows,
            config=_CONFIG,
            peg_to_eur_rates=_PEG_TO_EUR_RATES,
            loan_affected_assets=frozenset(),
            review_entries=review_entries,
        )

        assert len(result) == 1
        unchanged = result[0]
        # Entry unchanged: proceeds still 0, gain still the phantom -cost.
        assert unchanged.proceeds_eur == Decimal("0")
        assert unchanged.gain_loss_eur == Decimal("-100.00")
        # DP-013 flag + reason survive verbatim (not clobbered to a payment
        # correction reason, not dropped).
        assert unchanged.review_required is True
        assert unchanged.review_reason == _DP013_REASON
        assert "Zero disposal proceeds" in (unchanged.review_reason or "")
        # No correction review entry: the row was never a payment disposal.
        assert review_entries == []

    def test_card_payment_tag_also_matched(self):
        """A TH row tagged ``Card Payment`` (mixed case ``Card payment``) IS a
        payment disposal (the configured tag set includes both). Binds tag-set
        normalization (case-insensitive) and that ``Card Payment`` is not
        silently dropped - future-proofing, no such rows exist in current data.
        """
        entry = _make_cg_entry(
            asset="ABC",
            amount=Decimal("50"),
            cost_eur=Decimal("100"),
            proceeds_eur=Decimal("0"),
            gain_loss_eur=Decimal("-100.00"),
        )
        th_rows = [
            _make_th_payment_row(
                sent_currency="ABC",
                sent_amount="50",
                net_value_eur="50,00",
                tag="Card payment",
            )
        ]
        review_entries: list[CryptoReviewEntry] = []

        result = correct_payment_proceeds(
            [entry],
            th_rows,
            config=_CONFIG,
            peg_to_eur_rates=_PEG_TO_EUR_RATES,
            loan_affected_assets=frozenset(),
            review_entries=review_entries,
        )

        assert len(result) == 1
        corrected = result[0]
        assert corrected.proceeds_eur == Decimal("50.00")
        assert corrected.gain_loss_eur == Decimal("-50.00")
        assert corrected.review_required is True
        assert len(review_entries) == 1

    def test_non_eur_stablecoin_unpriced_converted_via_year_end_rate(self):
        """An unpriced (``Net Value (EUR)`` = "0,0") Payment of a USD-pegged
        stablecoin "USDX" converts at the year-end USD->EUR rate.

        - amount=80, cost_eur=100, ``peg_to_eur_rates={"USD": Decimal("0.90")}``.
        - proceeds = amount * rate = 80 * 0.90 = 72.00 (NOT amount 80, NOT cost
          100, NOT 0; and NOT amount / rate = 88.89 - the [EXCHANGE RATES] value
          is EUR-per-unit-of-calculated-currency, matching ib_sheet.py
          ``rate * amount``).
        - gain = 72 - 100 = -28.00.
        - review_required=True; reason names the asset AND "USD" AND "0.90" AND
          "year-end rate, verify"; one CryptoReviewEntry appended.
        """
        entry = _make_cg_entry(
            asset="USDX",
            amount=Decimal("80"),
            cost_eur=Decimal("100"),
            proceeds_eur=Decimal("0"),
            gain_loss_eur=Decimal("-100.00"),
        )
        th_rows = [
            _make_th_payment_row(
                sent_currency="USDX",
                sent_amount="80",
                net_value_eur="0,0",
            )
        ]
        review_entries: list[CryptoReviewEntry] = []

        result = correct_payment_proceeds(
            [entry],
            th_rows,
            config=_CONFIG,
            peg_to_eur_rates=_PEG_TO_EUR_RATES,
            loan_affected_assets=frozenset(),
            review_entries=review_entries,
        )

        assert len(result) == 1
        corrected = result[0]
        assert corrected.proceeds_eur == Decimal("72.00")
        assert corrected.gain_loss_eur == Decimal("-28.00")
        assert corrected.review_required is True
        reason = corrected.review_reason or ""
        assert "USDX" in reason
        assert "USD" in reason
        assert "0.90" in reason
        reason_lower = reason.lower()
        assert "year-end rate" in reason_lower
        assert "verify" in reason_lower
        assert len(review_entries) == 1
        assert review_entries[0].asset == "USDX"

    def test_net_value_precedence_holds_for_non_eur_peg(self):
        """For a USD-pegged stablecoin Payment with a NON-ZERO ``Net Value (EUR)``
        ("99,50"), the Koinly Net Value wins over the year-end peg-rate product.

        - amount=80, cost=100, ``peg_to_eur_rates={"USD": Decimal("0.90")}``:
          the peg-rate product would be 72.00.
        - proceeds = 99.50 (the Koinly value), NOT 72.00, NOT 80, NOT 100.
        - gain = 99.50 - 100 = -0.50.

        Symmetric guard for the non-EUR-pegged branch (the EUR-pegged precedence
        test in Task 1 does not cover it): a regression that checks peg_rate
        BEFORE net_value (or applies ``amount*rate`` whenever the asset is a
        stablecoin regardless of Net Value) converts at 72.00 and fails here.
        """
        entry = _make_cg_entry(
            asset="USDX",
            amount=Decimal("80"),
            cost_eur=Decimal("100"),
            proceeds_eur=Decimal("0"),
            gain_loss_eur=Decimal("-100.00"),
        )
        th_rows = [
            _make_th_payment_row(
                sent_currency="USDX",
                sent_amount="80",
                net_value_eur="99,50",
            )
        ]
        review_entries: list[CryptoReviewEntry] = []

        result = correct_payment_proceeds(
            [entry],
            th_rows,
            config=_CONFIG,
            peg_to_eur_rates=_PEG_TO_EUR_RATES,
            loan_affected_assets=frozenset(),
            review_entries=review_entries,
        )

        assert len(result) == 1
        corrected = result[0]
        assert corrected.proceeds_eur == Decimal("99.50")
        assert corrected.gain_loss_eur == Decimal("-0.50")

    def test_non_eur_stablecoin_no_config_rate_reviewed(self):
        """An unpriced Payment of a GBP-pegged stablecoin "GBPX" whose peg
        currency has NO entry in ``peg_to_eur_rates`` falls to a review flag,
        NOT a wrong/zeroed conversion.

        - proceeds stays 0; gain stays -cost; DP-013 reason intact.
        - A CryptoReviewEntry is appended whose reason names the asset AND
          "GBP-pegged" AND the missing-rate condition - distinct from the
          generic non-stablecoin ticker-check reason.
        """
        # Per-test config: GBPX is a known stablecoin pegged to GBP. The shared
        # _PEG_TO_EUR_RATES has no "GBP" entry (USD only).
        config_no_gbp_rate = PaymentProceedsConfig(
            payment_tags=["payment", "card payment"],
            stablecoins=frozenset({"GBPX"}),
            stablecoin_pegs={"GBPX": "GBP"},
        )
        entry = _make_cg_entry(
            asset="GBPX",
            amount=Decimal("80"),
            cost_eur=Decimal("100"),
            proceeds_eur=Decimal("0"),
            gain_loss_eur=Decimal("-100.00"),
            review_required=True,
            review_reason=_DP013_REASON,
        )
        th_rows = [
            _make_th_payment_row(
                sent_currency="GBPX",
                sent_amount="80",
                net_value_eur="0,0",
            )
        ]
        review_entries: list[CryptoReviewEntry] = []

        result = correct_payment_proceeds(
            [entry],
            th_rows,
            config=config_no_gbp_rate,
            peg_to_eur_rates=_PEG_TO_EUR_RATES,
            loan_affected_assets=frozenset(),
            review_entries=review_entries,
        )

        assert len(result) == 1
        unchanged = result[0]
        # No inference: proceeds stays 0, gain stays -cost.
        assert unchanged.proceeds_eur == Decimal("0")
        assert unchanged.gain_loss_eur == Decimal("-100.00")
        # DP-013 reason intact.
        assert unchanged.review_required is True
        assert unchanged.review_reason == _DP013_REASON
        # A specific review entry is appended naming the asset, the GBP peg, and
        # the missing-rate condition.
        assert len(review_entries) == 1
        review_reason = review_entries[0].review_reason
        assert "GBPX" in review_reason
        assert "GBP-pegged" in review_reason
        reason_lower = review_reason.lower()
        assert "no" in reason_lower
        assert "rate" in reason_lower

    def test_drift_stablecoin_missing_peg_does_not_emit_none_literal(self):
        """Config drift: an asset listed in ``stablecoins`` but ABSENT from
        ``stablecoin_pegs`` (the loader warns but does not refuse - see
        ``_load_payment_proceeds_config`` drift guard) reaches the tier-4
        review path with ``peg=None``. The emitted review reason must NOT
        contain the literal substring ``"None"`` (which the unguarded f-string
        ``f"no {peg}->EUR rate in config"`` would produce - nonsensical and
        unactionable), and must remain specific/actionable: it names the asset
        (GBPX) and tells the operator what to do (supply the EUR realization
        value / configure the peg).

        Discriminating: under the buggy code the reason is
        ``"... no None->EUR rate in config - ..."`` so the ``"None"`` assertion
        FAILS; the fixed code degrades the rate phrase for ``peg is None``.
        """
        # Drift config: GBPX is a stablecoin but has NO peg entry.
        config_drift = PaymentProceedsConfig(
            payment_tags=["payment", "card payment"],
            stablecoins=frozenset({"GBPX"}),
            stablecoin_pegs={},
        )
        entry = _make_cg_entry(
            asset="GBPX",
            amount=Decimal("80"),
            cost_eur=Decimal("100"),
            proceeds_eur=Decimal("0"),
            gain_loss_eur=Decimal("-100.00"),
            review_required=True,
            review_reason=_DP013_REASON,
        )
        th_rows = [
            _make_th_payment_row(
                sent_currency="GBPX",
                sent_amount="80",
                net_value_eur="0,0",
            )
        ]
        review_entries: list[CryptoReviewEntry] = []

        result = correct_payment_proceeds(
            [entry],
            th_rows,
            config=config_drift,
            peg_to_eur_rates=_PEG_TO_EUR_RATES,
            loan_affected_assets=frozenset(),
            review_entries=review_entries,
        )

        assert len(result) == 1
        unchanged = result[0]
        # No inference: proceeds stays 0, DP-013 reason intact.
        assert unchanged.proceeds_eur == Decimal("0")
        assert unchanged.review_reason == _DP013_REASON
        # A tier-4 review entry is appended.
        assert len(review_entries) == 1
        review_reason = review_entries[0].review_reason
        # Discriminating assertion: the buggy f-string emits "no None->EUR rate".
        assert "None" not in review_reason
        # Specific/actionable: names the asset and tells the operator what to do.
        assert "GBPX" in review_reason
        reason_lower = review_reason.lower()
        assert "rate" in reason_lower or "realization" in reason_lower
        assert "supply" in reason_lower or "verify" in reason_lower

    @pytest.mark.parametrize(
        "bad_rate",
        [
            pytest.param(Decimal("0"), id="zero_rate"),
            pytest.param(Decimal("-0.85"), id="negative_rate"),
            pytest.param(Decimal("NaN"), id="nan_rate"),
            pytest.param(Decimal("Infinity"), id="infinite_rate"),
        ],
    )
    def test_non_eur_stablecoin_non_positive_or_non_finite_rate_routed_to_review(
        self, bad_rate: Decimal
    ):
        """A USDX Payment whose USD peg rate is non-positive or non-finite is
        routed to review, never silently converted.

        Four parametrized cases: (a) 0, (b) -0.85, (c) NaN, (d) Infinity. In
        EVERY case: proceeds stays 0, gain stays -cost, the DP-013 reason is
        intact, AND a CryptoReviewEntry is appended for the no-rate / malformed-
        rate condition. Binds BOTH halves of the ``rate.is_finite() and rate > 0``
        guard in ``_resolve_proceeds`` AND the operand ordering (``is_finite()``
        does not raise on NaN/inf, unlike ``>``):
          - case (a) 0: a missing ``> 0`` half would ship proceeds=0 silently
            (resurrecting the phantom full-cost loss).
          - case (b) -0.85: would ship negative proceeds.
          - case (c) NaN: a flipped predicate ``rate > 0 and rate.is_finite()``
            RAISES under the default context (``Decimal("NaN") > 0``).
          - case (d) Infinity: a ``> 0``-only regression that DROPS
            ``is_finite()`` would admit inf and ship ``amount * inf``.
        """
        config_usdx = PaymentProceedsConfig(
            payment_tags=["payment", "card payment"],
            stablecoins=frozenset({"USDX"}),
            stablecoin_pegs={"USDX": "USD"},
        )
        rates = {"USD": bad_rate}
        entry = _make_cg_entry(
            asset="USDX",
            amount=Decimal("80"),
            cost_eur=Decimal("100"),
            proceeds_eur=Decimal("0"),
            gain_loss_eur=Decimal("-100.00"),
            review_required=True,
            review_reason=_DP013_REASON,
        )
        th_rows = [
            _make_th_payment_row(
                sent_currency="USDX",
                sent_amount="80",
                net_value_eur="0,0",
            )
        ]
        review_entries: list[CryptoReviewEntry] = []

        result = correct_payment_proceeds(
            [entry],
            th_rows,
            config=config_usdx,
            peg_to_eur_rates=rates,
            loan_affected_assets=frozenset(),
            review_entries=review_entries,
        )

        assert len(result) == 1
        unchanged = result[0]
        # No conversion in ANY case.
        assert unchanged.proceeds_eur == Decimal("0")
        assert unchanged.gain_loss_eur == Decimal("-100.00")
        # DP-013 reason intact.
        assert unchanged.review_required is True
        assert unchanged.review_reason == _DP013_REASON
        # A review entry is appended for the no-rate / malformed-rate condition.
        assert len(review_entries) == 1
        assert review_entries[0].asset == "USDX"
        # Reason names the no-rate / malformed-rate condition (mirrors the GBPX
        # sibling test), not just the asset: a generic or empty reason fails.
        no_rate_reason = review_entries[0].review_reason
        assert "USDX" in no_rate_reason
        assert "USD-pegged" in no_rate_reason
        no_rate_lower = no_rate_reason.lower()
        assert "no" in no_rate_lower
        assert "rate" in no_rate_lower

    def test_non_stablecoin_unpriced_reviewed_with_generic_reason(self):
        """An unpriced Payment of a volatile asset "VOLX" (absent from
        ``stablecoins``) gets NO proceeds inference: the entry is unchanged with
        its DP-013 reason intact, AND a CryptoReviewEntry is appended whose
        reason advises checking the asset's ticker mapping in Koinly (generic -
        does NOT mention a peg).
        """
        # VOLX is NOT in stablecoins.
        config_no_volx = PaymentProceedsConfig(
            payment_tags=["payment", "card payment"],
            stablecoins=frozenset(),
            stablecoin_pegs={},
        )
        entry = _make_cg_entry(
            asset="VOLX",
            amount=Decimal("50"),
            cost_eur=Decimal("100"),
            proceeds_eur=Decimal("0"),
            gain_loss_eur=Decimal("-100.00"),
            review_required=True,
            review_reason=_DP013_REASON,
        )
        th_rows = [
            _make_th_payment_row(
                sent_currency="VOLX",
                sent_amount="50",
                net_value_eur="0,0",
            )
        ]
        review_entries: list[CryptoReviewEntry] = []

        result = correct_payment_proceeds(
            [entry],
            th_rows,
            config=config_no_volx,
            peg_to_eur_rates=_PEG_TO_EUR_RATES,
            loan_affected_assets=frozenset(),
            review_entries=review_entries,
        )

        assert len(result) == 1
        unchanged = result[0]
        # No inference.
        assert unchanged.proceeds_eur == Decimal("0")
        assert unchanged.gain_loss_eur == Decimal("-100.00")
        # DP-013 reason intact.
        assert unchanged.review_required is True
        assert unchanged.review_reason == _DP013_REASON
        # Generic ticker-check review entry appended; does NOT mention a peg.
        assert len(review_entries) == 1
        review_reason = review_entries[0].review_reason
        assert "VOLX" in review_reason
        reason_lower = review_reason.lower()
        assert "ticker" in reason_lower or "koinly" in reason_lower
        assert "peg" not in reason_lower

    def test_proceeds_already_nonzero_not_corrected(self):
        """A Payment CG row whose proceeds is ALREADY non-zero (5.00) is not
        touched: the correction targets ``proceeds == 0`` only. Binds the
        evidence gate's proceeds==0 precondition (Invariant 1).
        """
        entry = _make_cg_entry(
            asset="ABC",
            amount=Decimal("50"),
            cost_eur=Decimal("100"),
            proceeds_eur=Decimal("5.00"),
            gain_loss_eur=Decimal("-95.00"),
        )
        th_rows = [
            _make_th_payment_row(
                sent_currency="ABC",
                sent_amount="50",
                net_value_eur="120,00",
            )
        ]
        review_entries: list[CryptoReviewEntry] = []

        result = correct_payment_proceeds(
            [entry],
            th_rows,
            config=_CONFIG,
            peg_to_eur_rates=_PEG_TO_EUR_RATES,
            loan_affected_assets=frozenset(),
            review_entries=review_entries,
        )

        assert len(result) == 1
        unchanged = result[0]
        # No change: proceeds not 0 -> not a correction candidate.
        assert unchanged.proceeds_eur == Decimal("5.00")
        assert unchanged.gain_loss_eur == Decimal("-95.00")
        assert review_entries == []

    def test_unmatched_cg_row_not_corrected(self):
        """A zero-proceeds CG row with NO matching payment-tagged TH row is left
        unchanged: no blanket exclusion, the DP-013 reason survives, and NO
        ticker-check review entry is appended (unmatched != no-market-rate).
        Binds the "no TH row -> leave unchanged, no review entry" branch.
        """
        entry = _make_cg_entry(
            asset="ABC",
            amount=Decimal("50"),
            cost_eur=Decimal("100"),
            proceeds_eur=Decimal("0"),
            gain_loss_eur=Decimal("-100.00"),
            review_required=True,
            review_reason=_DP013_REASON,
        )
        # No TH rows at all -> no payment-tagged match.
        th_rows: list[dict[str, str]] = []
        review_entries: list[CryptoReviewEntry] = []

        result = correct_payment_proceeds(
            [entry],
            th_rows,
            config=_CONFIG,
            peg_to_eur_rates=_PEG_TO_EUR_RATES,
            loan_affected_assets=frozenset(),
            review_entries=review_entries,
        )

        assert len(result) == 1
        unchanged = result[0]
        # Unchanged: proceeds 0, gain -cost.
        assert unchanged.proceeds_eur == Decimal("0")
        assert unchanged.gain_loss_eur == Decimal("-100.00")
        # DP-013 reason survives.
        assert unchanged.review_required is True
        assert unchanged.review_reason == _DP013_REASON
        # No review entry: unmatched != no-market-rate.
        assert review_entries == []


# ---------------------------------------------------------------------------
# Task 3: collision-safety, count-equality, malformed Net Value, injection
# sanitization, tz-robust matching, reused-config loader robustness, EURC/EUROC
# alias, and direct coverage of the extracted index/derive helpers.
# ---------------------------------------------------------------------------

# Default PaymentProceedsConfig used by the loader tests: the SAME defaults the
# loader returns on any degrade path. Kept inline so a future change to the
# module-level default does not silently relax the "missing file -> defaults"
# assertions.
_DEFAULT_PAYMENT_TAGS = ["payment", "card payment"]


def _config(tickers: frozenset[str] = frozenset(), pegs: dict[str, str] | None = None) -> PaymentProceedsConfig:
    """Build a synthetic PaymentProceedsConfig for the Task-3 cases.

    Keeps the same payment-tag set as ``_CONFIG`` but lets each test vary the
    stablecoin membership / peg map without touching the shared module-level
    fixture.
    """
    return PaymentProceedsConfig(
        payment_tags=list(_DEFAULT_PAYMENT_TAGS),
        stablecoins=tickers,
        stablecoin_pegs=pegs or {},
    )


class TestCorrectPaymentProceedsCollisionSafety:
    """The count-equality rule, the one-review-per-key guard, the loan-affected
    candidate-population invariant, malformed/non-finite Net Value, and
    formula-injection sanitization for ``correct_payment_proceeds``.
    """

    def test_collision_blocks_correction_and_appends_review(self, caplog: pytest.LogCaptureFixture):
        """TWO payment-tagged TH rows sharing the same (day, asset, platform,
        amount) key but only ONE matching zero-proceeds CG row (counts 1 != 2):
        the CG row is left UNCHANGED (DP-013 proceeds==0 flag intact) and
        exactly ONE CryptoReviewEntry is appended for the KEY naming the count
        mismatch, with a WARNING. Binds the count-equality rule (mismatch in
        EITHER direction blocks) and the one-review-per-key guard (r6 L3).
        """
        entry = _make_cg_entry(
            asset="ABC",
            amount=Decimal("50"),
            cost_eur=Decimal("100"),
            proceeds_eur=Decimal("0"),
            gain_loss_eur=Decimal("-100.00"),
            review_required=True,
            review_reason=_DP013_REASON,
        )
        th_rows = [
            _make_th_payment_row(sent_currency="ABC", sent_amount="50", net_value_eur="120,00"),
            _make_th_payment_row(sent_currency="ABC", sent_amount="50", net_value_eur="80,00"),
        ]
        review_entries: list[CryptoReviewEntry] = []

        with caplog.at_level(logging.WARNING):
            result = correct_payment_proceeds(
                [entry],
                th_rows,
                config=_config(),
                peg_to_eur_rates=_PEG_TO_EUR_RATES,
                loan_affected_assets=frozenset(),
                review_entries=review_entries,
            )

        # No correction: the single CG row keeps its DP-013 flag.
        assert len(result) == 1
        unchanged = result[0]
        assert unchanged.proceeds_eur == Decimal("0")
        assert unchanged.gain_loss_eur == Decimal("-100.00")
        assert unchanged.review_required is True
        assert unchanged.review_reason == _DP013_REASON
        # Exactly ONE review entry for the KEY (not two - one per TH row).
        assert len(review_entries) == 1
        review_reason = review_entries[0].review_reason
        # Specific count fragment (not bare digits) so a reorder/drop of the
        # count words fails; a bare "1"/"2" would match any figure in the reason.
        assert "1 CG rows vs 2 Payment events" in review_reason
        reason_lower = review_reason.lower()
        assert "ambiguous" in reason_lower
        assert "ABC" in review_reason
        # A WARNING was logged.
        assert any(rec.levelno >= logging.WARNING for rec in caplog.records)

    def test_surplus_cg_not_corrected(self, caplog: pytest.LogCaptureFixture):
        """The SYMMETRIC mismatch: TWO zero-proceeds CG rows + ONE payment-tagged
        TH row on the same key (counts 2 != 1). BOTH CG rows are left unchanged
        AND exactly ONE CryptoReviewEntry is appended for the KEY (NOT one per
        CG row). Symmetric to the 1 CG + 2 TH case so a one-directional guard
        fails.
        """
        entries = [
            _make_cg_entry(
                asset="ABC",
                amount=Decimal("50"),
                cost_eur=Decimal("100"),
                proceeds_eur=Decimal("0"),
                gain_loss_eur=Decimal("-100.00"),
                review_required=True,
                review_reason=_DP013_REASON,
            ),
            _make_cg_entry(
                asset="ABC",
                amount=Decimal("50"),
                cost_eur=Decimal("100"),
                proceeds_eur=Decimal("0"),
                gain_loss_eur=Decimal("-100.00"),
                review_required=True,
                review_reason=_DP013_REASON,
            ),
        ]
        th_rows = [
            _make_th_payment_row(sent_currency="ABC", sent_amount="50", net_value_eur="120,00"),
        ]
        review_entries: list[CryptoReviewEntry] = []

        with caplog.at_level(logging.WARNING):
            result = correct_payment_proceeds(
                entries,
                th_rows,
                config=_config(),
                peg_to_eur_rates=_PEG_TO_EUR_RATES,
                loan_affected_assets=frozenset(),
                review_entries=review_entries,
            )

        # BOTH CG rows unchanged.
        assert len(result) == 2
        for unchanged in result:
            assert unchanged.proceeds_eur == Decimal("0")
            assert unchanged.gain_loss_eur == Decimal("-100.00")
            assert unchanged.review_required is True
            assert unchanged.review_reason == _DP013_REASON
        # Exactly ONE review entry for the KEY (not one per CG row).
        assert len(review_entries) == 1
        review_reason = review_entries[0].review_reason
        assert "2 CG rows vs 1 Payment events" in review_reason
        assert "ABC" in review_reason
        assert any(rec.levelno >= logging.WARNING for rec in caplog.records)

    def test_second_cg_row_consumes_leftover_in_order(self):
        """TWO zero-proceeds CG rows + TWO payment-tagged TH rows on the same key
        (counts 2 == 2), BOTH TH rows priced (Net Value "120,00" and "80,00").
        BOTH CG rows are corrected (deque order, one pop each) AND exactly TWO
        CryptoReviewEntry audit rows are appended (one per-lot success audit).

        This case is IMPOSSIBLE under a ">1 remaining" guard, so it binds the
        count-equality rule specifically. It also binds (r12 Monitor) that the
        success-path per-lot audit is per-ROW and deliberately NOT guarded by
        ``reviewed_keys`` (a future 'normalize all three append sites under one
        per-key guard' refactor would drop one audit here and fail
        ``len == 2``).
        """
        entries = [
            _make_cg_entry(
                asset="ABC",
                amount=Decimal("50"),
                cost_eur=Decimal("100"),
                proceeds_eur=Decimal("0"),
                gain_loss_eur=Decimal("-100.00"),
            ),
            _make_cg_entry(
                asset="ABC",
                amount=Decimal("50"),
                cost_eur=Decimal("100"),
                proceeds_eur=Decimal("0"),
                gain_loss_eur=Decimal("-100.00"),
            ),
        ]
        th_rows = [
            _make_th_payment_row(sent_currency="ABC", sent_amount="50", net_value_eur="120,00"),
            _make_th_payment_row(sent_currency="ABC", sent_amount="50", net_value_eur="80,00"),
        ]
        review_entries: list[CryptoReviewEntry] = []

        result = correct_payment_proceeds(
            entries,
            th_rows,
            config=_config(),
            peg_to_eur_rates=_PEG_TO_EUR_RATES,
            loan_affected_assets=frozenset(),
            review_entries=review_entries,
        )

        assert len(result) == 2
        # Insertion order (CG entry order == deque front-first pop order), NOT
        # sorted: the first CG candidate consumes the FRONT TH twin (120.00), the
        # second consumes 80.00. A LIFO (pop()) regression would flip these; a
        # sorted assertion would hide it (a discriminating test: the failure
        # must not survive a wrong implementation).
        assert result[0].proceeds_eur == Decimal("120.00")
        assert result[1].proceeds_eur == Decimal("80.00")
        # Gain recomputed from each corrected proceeds (insertion order).
        assert result[0].gain_loss_eur == Decimal("20.00")
        assert result[1].gain_loss_eur == Decimal("-20.00")
        for corrected in result:
            assert corrected.review_required is True
        # Exactly TWO per-lot success-audit review entries (one per corrected
        # row), NOT one per key.
        assert len(review_entries) == 2

    def test_no_rate_review_emits_one_per_key_for_equal_counts(self):
        """TWO zero-proceeds CG rows + TWO payment-tagged TH rows on the same key
        where the asset is a NON-stablecoin ("VOLX") and BOTH matched TH rows
        have Net Value "0,0" (counts 2 == 2, both candidates resolve to
        ``proceeds is None`` via the ``not_stablecoin`` outcome). Expects
        exactly ONE CryptoReviewEntry appended for the KEY (NOT two) AND both
        CG rows left unchanged with their DP-013 reasons intact.

        Binds the SYMMETRIC ``reviewed_keys`` guard on the ``proceeds is None``
        branch (r11 quality Medium): the ``not_stablecoin`` reason names only
        the asset, so two same-key candidates produce a LITERALLY IDENTICAL
        reason - under an unguarded append ``len == 2``; the guard yields
        ``len == 1``. Discriminates the multi-candidate
        cardinality that the single-candidate no-rate tests do not bind.
        """
        entries = [
            _make_cg_entry(
                asset="VOLX",
                amount=Decimal("50"),
                cost_eur=Decimal("100"),
                proceeds_eur=Decimal("0"),
                gain_loss_eur=Decimal("-100.00"),
                review_required=True,
                review_reason=_DP013_REASON,
            ),
            _make_cg_entry(
                asset="VOLX",
                amount=Decimal("50"),
                cost_eur=Decimal("100"),
                proceeds_eur=Decimal("0"),
                gain_loss_eur=Decimal("-100.00"),
                review_required=True,
                review_reason=_DP013_REASON,
            ),
        ]
        th_rows = [
            _make_th_payment_row(sent_currency="VOLX", sent_amount="50", net_value_eur="0,0"),
            _make_th_payment_row(sent_currency="VOLX", sent_amount="50", net_value_eur="0,0"),
        ]
        review_entries: list[CryptoReviewEntry] = []

        result = correct_payment_proceeds(
            entries,
            th_rows,
            config=_config(),  # VOLX is NOT a known stablecoin
            peg_to_eur_rates=_PEG_TO_EUR_RATES,
            loan_affected_assets=frozenset(),
            review_entries=review_entries,
        )

        assert len(result) == 2
        for unchanged in result:
            assert unchanged.proceeds_eur == Decimal("0")
            assert unchanged.gain_loss_eur == Decimal("-100.00")
            assert unchanged.review_required is True
            assert unchanged.review_reason == _DP013_REASON
        # Exactly ONE review entry for the KEY (NOT two near-duplicates).
        assert len(review_entries) == 1
        assert "VOLX" in review_entries[0].review_reason

    def test_loan_affected_sibling_does_not_inflate_count(self):
        """ONE non-loan zero-proceeds Payment CG + ONE loan-affected
        zero-proceeds CG (asset in ``loan_affected_assets``) + ONE payment-tagged
        TH row, all sharing the key. The NON-LOAN entry IS corrected (candidate
        count is 1 == 1 TH) and the loan-affected entry is SKIPPED with NO
        review entry. Binds that ``cg_count`` is computed over the candidate
        population (proceeds==0 AND non-loan), so a loan-affected zero-proceeds
        sibling does not falsely trip the count-mismatch branch (Medium 4 / r6).
        """
        loan_asset = "LOANX"
        entries = [
            _make_cg_entry(
                asset="ABC",
                amount=Decimal("50"),
                cost_eur=Decimal("100"),
                proceeds_eur=Decimal("0"),
                gain_loss_eur=Decimal("-100.00"),
            ),
            _make_cg_entry(
                asset=loan_asset,
                amount=Decimal("50"),
                cost_eur=Decimal("100"),
                proceeds_eur=Decimal("0"),
                gain_loss_eur=Decimal("-100.00"),
                review_required=True,
                review_reason=_DP013_REASON,
            ),
        ]
        th_rows = [
            _make_th_payment_row(sent_currency="ABC", sent_amount="50", net_value_eur="120,00"),
        ]
        review_entries: list[CryptoReviewEntry] = []

        result = correct_payment_proceeds(
            entries,
            th_rows,
            config=_config(),
            peg_to_eur_rates=_PEG_TO_EUR_RATES,
            loan_affected_assets=frozenset({loan_asset}),
            review_entries=review_entries,
        )

        assert len(result) == 2
        # Find each entry by asset (order preserved, but assert by identity).
        by_asset = {e.asset: e for e in result}
        # Non-loan candidate was corrected.
        assert by_asset["ABC"].proceeds_eur == Decimal("120.00")
        assert by_asset["ABC"].review_required is True
        # Loan-affected sibling left unchanged, no review entry for it.
        assert by_asset[loan_asset].proceeds_eur == Decimal("0")
        assert by_asset[loan_asset].review_required is True
        assert by_asset[loan_asset].review_reason == _DP013_REASON
        # Exactly ONE success-audit review entry for the corrected row.
        assert len(review_entries) == 1
        assert review_entries[0].asset == "ABC"

    def test_malformed_net_value_blocks_one_row_only(self, caplog: pytest.LogCaptureFixture):
        """TWO priced Payment CG rows + TWO payment-tagged TH rows on the same key
        (counts equal, both candidates) where ONE matched TH row has a
        non-numeric Net Value (EUR) ("N/A"). That row is left UNCHANGED
        (proceeds=0, DP-013 reason intact) with a WARNING, NO exception escapes
        the per-entry boundary, AND the SIBLING row IS still corrected.

        TH-insertion-order precondition (r10): the GOOD TH row is inserted
        FIRST (front of the deque, consumed+popped by the first candidate) and
        the MALFORMED row SECOND (back, read by the second candidate) - the
        success path pops the front, so only this order lets the sibling be
        corrected.

        A SECOND sub-assertion feeds a European-comma value ("120,00") on the
        sibling to prove the parse goes through ``parse_koinly_decimal`` (NOT
        bare ``Decimal()``), which normalizes European commas - bare
        ``Decimal("120,00")`` would raise.

        A THIRD sub-assertion (r9 security Medium) feeds a NON-FINITE Net Value
        ("Infinity" and "NaN") on the matched TH row of a NON-stablecoin
        candidate; ``parse_koinly_decimal`` accepts these as valid Decimals, so
        WITHOUT the ``net_value.is_finite()`` tier-1 guard the row would ship
        ``proceeds = Infinity`` (``inf > 0 == True``) / raise on ``nan > 0``.
        Asserts the row is left UNCHANGED with a WARNING naming "non-finite Net
        Value" and NO infinite proceeds.
        """
        # --- Sub-assertion 1 + 2: malformed sibling + European-comma sibling ---
        entries = [
            _make_cg_entry(
                asset="ABC",
                amount=Decimal("50"),
                cost_eur=Decimal("100"),
                proceeds_eur=Decimal("0"),
                gain_loss_eur=Decimal("-100.00"),
                review_required=True,
                review_reason=_DP013_REASON,
            ),
            _make_cg_entry(
                asset="ABC",
                amount=Decimal("50"),
                cost_eur=Decimal("100"),
                proceeds_eur=Decimal("0"),
                gain_loss_eur=Decimal("-100.00"),
                review_required=True,
                review_reason=_DP013_REASON,
            ),
        ]
        # GOOD (priced, European comma) FIRST, MALFORMED SECOND.
        th_rows = [
            _make_th_payment_row(sent_currency="ABC", sent_amount="50", net_value_eur="120,00"),
            _make_th_payment_row(sent_currency="ABC", sent_amount="50", net_value_eur="N/A"),
        ]
        review_entries: list[CryptoReviewEntry] = []

        with caplog.at_level(logging.WARNING):
            result = correct_payment_proceeds(
                entries,
                th_rows,
                config=_config(),
                peg_to_eur_rates=_PEG_TO_EUR_RATES,
                loan_affected_assets=frozenset(),
                review_entries=review_entries,
            )

        assert len(result) == 2
        # Exactly one was corrected (the sibling, whose TH Net Value was the
        # European-comma "120,00" -> 120.00, proving the parse_koinly_decimal
        # path is exercised - bare Decimal("120,00") would have raised).
        corrected = [e for e in result if e.proceeds_eur != Decimal("0")]
        unchanged = [e for e in result if e.proceeds_eur == Decimal("0")]
        assert len(corrected) == 1
        assert len(unchanged) == 1
        assert corrected[0].proceeds_eur == Decimal("120.00")
        assert corrected[0].gain_loss_eur == Decimal("20.00")
        # The malformed row retains its DP-013 flag.
        assert unchanged[0].proceeds_eur == Decimal("0")
        assert unchanged[0].gain_loss_eur == Decimal("-100.00")
        assert unchanged[0].review_reason == _DP013_REASON
        # A WARNING named the malformed Net Value.
        assert any("N/A" in rec.message or "Net Value" in rec.message for rec in caplog.records)

    @pytest.mark.parametrize(
        "asset",
        [
            pytest.param("VOLX", id="non_stablecoin"),
            pytest.param("EURST", id="eur_pegged_stablecoin"),
        ],
    )
    @pytest.mark.parametrize(
        "non_finite",
        [
            pytest.param("Infinity", id="infinity"),
            pytest.param("NaN", id="nan"),
        ],
    )
    def test_non_finite_net_value_treated_as_malformed(
        self, non_finite: str, asset: str, caplog: pytest.LogCaptureFixture
    ):
        """A NON-FINITE ``Net Value`` (inf / nan) on the matched TH row leaves
        the CG row UNCHANGED. ``parse_koinly_decimal`` accepts inf/nan as valid
        Decimals, so the non-finite guard (payment_proceeds.py non-finite
        branch) is what stops the row proceeding.

        Parametrized over the asset type because the guard is load-bearing only
        for a STABLECOIN: for a non-stablecoin (VOLX) the row is left flagged
        anyway (``_resolve_proceeds`` returns ``not_stablecoin``), so removing
        the guard changes nothing observable. For an EUR-pegged stablecoin
        (EURST) WITHOUT the guard the non-finite Net Value fails tier-1 and the
        row falls through to the EUR-par fallback, silently correcting
        ``proceeds`` from 0 to the par amount (50) - exactly the regression this
        case binds. Single-CG/single-TH fixture sidesteps the multi-row ordering
        question.
        """
        entry = _make_cg_entry(
            asset=asset,
            amount=Decimal("50"),
            cost_eur=Decimal("100"),
            proceeds_eur=Decimal("0"),
            gain_loss_eur=Decimal("-100.00"),
            review_required=True,
            review_reason=_DP013_REASON,
        )
        th_rows = [
            _make_th_payment_row(sent_currency=asset, sent_amount="50", net_value_eur=non_finite),
        ]
        review_entries: list[CryptoReviewEntry] = []
        # EURST is an EUR-pegged stablecoin in _CONFIG - the load-bearing case,
        # since without the guard a non-finite Net Value falls through to the
        # EUR-par fallback. VOLX is not a stablecoin, so _config()'s empty
        # stablecoin set matches the original VOLX-only behavior.
        config = _CONFIG if asset == "EURST" else _config()

        with caplog.at_level(logging.WARNING):
            result = correct_payment_proceeds(
                [entry],
                th_rows,
                config=config,
                peg_to_eur_rates=_PEG_TO_EUR_RATES,
                loan_affected_assets=frozenset(),
                review_entries=review_entries,
            )

        assert len(result) == 1
        unchanged = result[0]
        # Row left UNCHANGED: no infinite/nan proceeds shipped.
        assert unchanged.proceeds_eur == Decimal("0")
        assert unchanged.gain_loss_eur == Decimal("-100.00")
        assert unchanged.review_required is True
        assert unchanged.review_reason == _DP013_REASON
        # A WARNING names the non-finite Net Value condition.
        assert any("non-finite" in rec.message.lower() for rec in caplog.records)
        assert any("Net Value" in rec.message for rec in caplog.records)

    @pytest.mark.parametrize(
        "evil_asset",
        [
            pytest.param('=HYPERLINK("https://evil")', id="equals_hyperlink"),
            pytest.param("-cmd|/c calc!A0", id="dash_pipe"),
        ],
    )
    def test_formula_injection_in_review_reasons_neutralized(self, evil_asset: str):
        """A payment disposal whose ASSET string begins with a formula sigil
        (``=HYPERLINK(...)`` or ``-cmd|...``) must NOT ship a live spreadsheet
        formula. BOTH the corrected capital entry's ``review_reason`` AND every
        appended ``CryptoReviewEntry.review_reason`` (which renders RAW in the
        Excel review tab) are neutralized: a leading ``= + - @`` is defused by
        a leading-space prefix (the sigil is preserved but offset, via
        ``safe_cell_value``) and control chars are removed. Binds that
        sanitization covers ALL emitted reasons + log lines, not just the
        capital-entry reason (Medium 3).
        """
        entry = _make_cg_entry(
            asset=evil_asset,
            amount=Decimal("50"),
            cost_eur=Decimal("100"),
            proceeds_eur=Decimal("0"),
            gain_loss_eur=Decimal("-100.00"),
        )
        th_rows = [
            _make_th_payment_row(sent_currency=evil_asset, sent_amount="50", net_value_eur="120,00"),
        ]
        review_entries: list[CryptoReviewEntry] = []

        result = correct_payment_proceeds(
            [entry],
            th_rows,
            config=_config(),
            peg_to_eur_rates=_PEG_TO_EUR_RATES,
            loan_affected_assets=frozenset(),
            review_entries=review_entries,
        )

        assert len(result) == 1
        corrected = result[0]
        # Corrected (proceeds recovered from Net Value).
        assert corrected.proceeds_eur == Decimal("120.00")
        assert corrected.review_required is True
        # The capital-entry reason must not START with a formula sigil.
        cap_reason = corrected.review_reason or ""
        assert cap_reason[:1] not in {"=", "+", "-", "@"}
        # The evil-asset sigil is embedded in the reason (present) but offset
        # past the prose prefix (not at position 0) - the actual property
        # sanitization guarantees. The previous isalpha() / == "(" assertion was
        # tautological (the prose prefix always starts with a letter).
        sigil = evil_asset[:1]
        assert sigil in cap_reason
        assert cap_reason.index(sigil) > 0
        # Every appended CryptoReviewEntry (renders RAW in Excel) is also
        # neutralized.
        assert len(review_entries) >= 1
        for rev in review_entries:
            rr = rev.review_reason
            assert rr[:1] not in {"=", "+", "-", "@"}


class TestBuildPaymentTagIndex:
    """Direct coverage of ``build_payment_tag_index`` (extracted helper):
    tag-set normalization (case-insensitive) and the
    same-calendar-day correlation key (tz-robust to sub-day offsets).
    """

    def test_payment_tag_case_insensitive(self):
        """TH Tag values ``Payment``, ``PAYMENT``, and ``Card Payment`` are ALL
        indexed as payment (case-insensitive match against the configured
        ``payment_tags`` set ``["payment", "card payment"]``). A ``Reward`` row
        is NOT indexed (non-payment tag).
        """
        rows = [
            _make_th_payment_row(sent_currency="ABC", sent_amount="1", net_value_eur="1,00", tag="Payment"),
            _make_th_payment_row(sent_currency="ABC", sent_amount="1", net_value_eur="1,00", tag="PAYMENT"),
            _make_th_payment_row(sent_currency="ABC", sent_amount="1", net_value_eur="1,00", tag="Card Payment"),
            _make_th_payment_row(sent_currency="XYZ", sent_amount="2", net_value_eur="2,00", tag="Reward"),
        ]
        index = build_payment_tag_index(rows, _DEFAULT_PAYMENT_TAGS)

        # The three payment-tagged rows are indexed; the Reward row is NOT.
        # The index maps a key tuple to a deque of TH row indices. Aggregate all
        # indexed TH indices.
        indexed_indices: set[int] = set()
        for bucket in index.values():
            indexed_indices.update(bucket)
        # The Reward row (index 3) must not appear.
        assert 3 not in indexed_indices
        # The three payment rows (indices 0, 1, 2) are all indexed.
        assert {0, 1, 2}.issubset(indexed_indices)

    def test_correlation_matches_across_sub_day_tz_offset(self):
        """A CG disposal date and a TH disposal on the SAME calendar day but at
        a DIFFERENT hour correlate (the key is calendar day + asset + platform +
        amount, NOT time-of-day). Binds the tz-robust matching: a sub-day wall-
        clock offset between the CG row and its TH twin must not break the match.
        """
        # The CG side is represented only implicitly (the matcher keys on the
        # entry's disposal_date day). Here we verify the TH index is keyed by
        # the calendar day alone: two TH rows at different hours on the same
        # day collapse onto the SAME key.
        same_day_a = _make_th_payment_row(
            sent_currency="ABC",
            sent_amount="50",
            net_value_eur="120,00",
            date="2025-06-15 08:00:00 UTC",
            tag="Payment",
        )
        same_day_b = _make_th_payment_row(
            sent_currency="ABC",
            sent_amount="50",
            net_value_eur="80,00",
            date="2025-06-15 22:00:00 UTC",
            tag="Payment",
        )
        index = build_payment_tag_index([same_day_a, same_day_b], _DEFAULT_PAYMENT_TAGS)

        # Exactly ONE key (day, asset, platform, amount) holds BOTH TH rows.
        assert len(index) == 1
        only_bucket = next(iter(index.values()))
        assert len(only_bucket) == 2


# Module-level helpers for the parametrized loader test (ordinary functions
# referenced from the @pytest.mark.parametrize list; defined BEFORE the loader
# test class so the names resolve at definition order - ruff F821).
def _write_tokens_helper(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "popular_crypto_tokens.json"
    path.write_text(body, encoding="utf-8")
    return path


def _make_symlink_target(tmp_path: Path, writer) -> Path:
    """Create a symlink whose target holds MALFORMED JSON.

    The symlink case must short-circuit BEFORE ``open()``/``read()`` runs, so
    the malformed body is never parsed and the symlink-specific warning fires
    (not the "invalid JSON" one).
    """
    target = tmp_path / "target_malformed.json"
    target.write_text("{ this is not valid json", encoding="utf-8")
    link = tmp_path / "popular_crypto_tokens.json"
    link.symlink_to(target)
    return link


class TestLoadPaymentProceedsConfigFromPath:
    """Direct coverage of the path-arg reader ``_load_payment_proceeds_config_from_path``
    (the reader is NOT memoized; the resolver is). Each test writes JSON via a
    ``tmp_path`` fixture and calls the reader directly.
    """

    @staticmethod
    def _write_tokens(tmp_path: Path, payload: dict) -> Path:
        path = tmp_path / "popular_crypto_tokens.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_reads_reused_popular_crypto_tokens_json(self, tmp_path: Path):
        """A ``popular_crypto_tokens.json`` mirroring the real shape (``meta``,
        ``tokens.stablecoins`` including BOTH ``EUROC`` and ``EURC``, sibling
        ``stablecoin_pegs`` and ``payment_tags``) yields a PaymentProceedsConfig
        whose ``stablecoins`` contains EUROC + EURC, ``stablecoin_pegs["EUROC"]
        == "EUR"``, and ``payment_tags == ["payment", "card payment"]``.

        Binds the EURC/EUROC token-rename alias (the same Circle stablecoin
        imported under its 2022 legacy ticker EUROC and its renamed EURC).
        """
        payload = {
            "meta": {
                "description": "Popular crypto tokens + stablecoin pegs + payment tags.",
                "last_updated": "2026-06-19",
            },
            "tokens": {
                "stablecoins": ["USDT", "USDC", "DAI", "EURC", "EUROC", "EURT"],
            },
            "stablecoin_pegs": {
                "USDT": "USD", "USDC": "USD", "DAI": "USD",
                "EURC": "EUR", "EUROC": "EUR", "EURT": "EUR",
            },
            "payment_tags": ["payment", "card payment"],
        }
        path = self._write_tokens(tmp_path, payload)

        config = _load_payment_proceeds_config_from_path(path)

        assert "EURC" in config.stablecoins
        assert "EUROC" in config.stablecoins
        assert config.stablecoin_pegs["EUROC"] == "EUR"
        assert config.stablecoin_pegs["EURC"] == "EUR"
        assert config.payment_tags == ["payment", "card payment"]

    def test_missing_file_returns_defaults(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ):
        """The JSON absent at the passed path -> the loader returns the defaults
        ``PaymentProceedsConfig(["payment", "card payment"], frozenset(), {})``
        and logs a WARNING. No proceeds inference occurs (empty stablecoin set).
        """
        missing = tmp_path / "does_not_exist.json"

        with caplog.at_level(logging.WARNING):
            config = _load_payment_proceeds_config_from_path(missing)

        assert config.payment_tags == ["payment", "card payment"]
        assert config.stablecoins == frozenset()
        assert config.stablecoin_pegs == {}
        assert any(rec.levelno >= logging.WARNING for rec in caplog.records)

    @pytest.mark.parametrize(
        ("kind", "make_path"),
        [
            pytest.param(
                "invalid JSON",
                lambda tmp_path, _make=_write_tokens_helper: _make(
                    tmp_path, "{ this is not valid json"
                ),
                id="malformed_json",
            ),
            pytest.param(
                "exceeds size limit",
                lambda tmp_path, _make=_write_tokens_helper: _make(
                    tmp_path, '{"pad": "' + "x" * (2 * 1024 * 1024) + '"}'
                ),
                id="oversize",
            ),
            pytest.param(
                "symlink",
                lambda tmp_path, _make=_write_tokens_helper: _make_symlink_target(
                    tmp_path, _make
                ),
                id="symlink",
            ),
        ],
    )
    def test_malformed_or_oversize_or_symlink_degrades(
        self, kind: str, make_path, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ):
        """THREE parametrized degrade cases (malformed JSON; an oversize file
        > 1 MiB; a symlinked path). EACH returns the defaults, raises NO
        exception, and logs a WARNING naming THAT specific failure ("invalid
        JSON" / "exceeds size limit" / "symlink"). The symlink case points at a
        target whose CONTENTS are malformed JSON and asserts the symlink warning
        fires AND the "invalid JSON" warning does NOT (proves open()/read()
        never ran - short-circuit before content is touched). The oversize case
        asserts the body is never parsed.
        """
        path = make_path(tmp_path)

        with caplog.at_level(logging.WARNING):
            config = _load_payment_proceeds_config_from_path(path)

        # (a) returns the defaults; (b) no exception raised.
        assert config.payment_tags == ["payment", "card payment"]
        assert config.stablecoins == frozenset()
        assert config.stablecoin_pegs == {}
        # (c) a WARNING names the specific failure.
        messages = [rec.message for rec in caplog.records]
        assert any(kind in m for m in messages), f"expected warning naming {kind!r}: {messages}"
        # The symlink short-circuits BEFORE content is touched: the malformed
        # target body never gets parsed, so the "invalid JSON" warning must NOT
        # fire for the symlink case.
        if kind == "symlink":
            assert not any("invalid JSON" in m for m in messages), messages

    def test_stablecoin_pegs_drift_from_tokens_warns(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ):
        """A config whose ``stablecoin_pegs`` keys DIVERGE from
        ``tokens.stablecoins`` (a stablecoin in one set but not the other) is
        still returned (never raises), but a WARNING names the drift. Binds the
        consistency guard that prevents silent mis-routing when the membership
        set and the peg map get out of sync.
        """
        payload = {
            "meta": {"description": "drift fixture", "last_updated": "2026-06-19"},
            "tokens": {"stablecoins": ["USDT", "USDC", "DAI"]},
            # EURC has a peg but is NOT in tokens.stablecoins (drift).
            "stablecoin_pegs": {"USDT": "USD", "USDC": "USD", "DAI": "USD", "EURC": "EUR"},
            "payment_tags": ["payment", "card payment"],
        }
        path = self._write_tokens(tmp_path, payload)

        with caplog.at_level(logging.WARNING):
            config = _load_payment_proceeds_config_from_path(path)

        # Loader still returns (never raises).
        assert config.payment_tags == ["payment", "card payment"]
        # A WARNING names the drift.
        messages = [rec.message for rec in caplog.records]
        assert any("drift" in m.lower() or "stablecoin_pegs" in m for m in messages), messages
        # The drift identifier (EURC) is surfaced so a maintainer can fix it.
        assert any("EURC" in m for m in messages), messages


class TestDerivePegToEurRates:
    """Direct coverage of ``_derive_peg_to_eur_rates`` (extracted helper):
    only peg currencies WITH a finite, positive rate appear; the
    skip+warn branch fires for non-positive / non-finite rates.
    """

    def test_maps_only_pegs_with_a_rate(self):
        """Given synthetic ConversionRates for USD (0.90) and CAD (0.62) but NOT
        GBP, and ``stablecoin_pegs={"USDX": "USD", "CADX": "CAD", "GBPX": "GBP"}``,
        the returned dict is ``{"USD": Decimal("0.90"), "CAD": Decimal("0.62")}``
        (GBP absent - no rate). EUR-pegged entries are excluded since
        ``p != target_currency``.
        """
        rates = [
            ConversionRate(base="EUR", calculated="USD", rate=Decimal("0.90")),
            ConversionRate(base="EUR", calculated="CAD", rate=Decimal("0.62")),
        ]
        stablecoin_pegs = {"USDX": "USD", "CADX": "CAD", "GBPX": "GBP"}

        derived = _derive_peg_to_eur_rates(rates, stablecoin_pegs)

        assert derived == {"USD": Decimal("0.90"), "CAD": Decimal("0.62")}
        assert "GBP" not in derived

    @pytest.mark.parametrize(
        "bad_rate",
        [
            pytest.param(Decimal("0"), id="zero_rate"),
            pytest.param(Decimal("-0.85"), id="negative_rate"),
            pytest.param(Decimal("NaN"), id="nan_rate"),
            pytest.param(Decimal("Infinity"), id="infinite_rate"),
        ],
    )
    def test_skips_non_positive_and_non_finite_rates_with_warning(
        self, bad_rate: Decimal, caplog: pytest.LogCaptureFixture
    ):
        """FOUR parametrized ConversionRate cases (0, -0.85, NaN, Infinity) for
        the USD peg. The returned dict OMITS "USD" in EVERY case AND a WARNING
        is logged naming the peg ("USD") AND the offending rate value. Binds
        the skip+warn branch directly (the FIRST layer, closest to the bad
        config data - the resolver guard at ``_resolve_proceeds`` is the
        SECOND). The NaN/inf cases bind ``rate.is_finite() and rate > 0``
        (an inf would pass ``>0``-only; a NaN would crash a flipped predicate).
        """
        rates = [ConversionRate(base="EUR", calculated="USD", rate=bad_rate)]
        stablecoin_pegs = {"USDX": "USD"}

        with caplog.at_level(logging.WARNING):
            derived = _derive_peg_to_eur_rates(rates, stablecoin_pegs)

        assert "USD" not in derived
        messages = [rec.message for rec in caplog.records]
        assert any("USD" in m for m in messages), messages
        # The offending rate value is named in the warning.
        assert any(str(bad_rate) in m for m in messages), messages
