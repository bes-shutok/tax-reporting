"""Unit tests for ``TreatmentConfig`` (Task 2) and ``resolve_treatment`` (Task 3).

Task 2 covers the ``TreatmentConfig`` dataclass and its default tag sets.
Task 3 covers ``resolve_treatment``: the (Type, Tag) matrix, the disposal-shape
default branch, case-insensitive matching, the Invariant 6 precedence order,
and purity/totality.

Plan: ``docs/history/plans/2026-07-06-th-tx-view-phase-b.md`` (Tasks 2 + 3).
"""

from __future__ import annotations

import io
import logging
import sys
from dataclasses import FrozenInstanceError, asdict, fields
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from tax_reporting.application.crypto.treatment_resolver import (
    TreatmentConfig,
    resolve_treatment,
)
from tax_reporting.domain.transaction import (
    Transaction,
    TransactionHistoryRow,
    WalletKind,
)
from tax_reporting.domain.treatment import Treatment


class TestTreatmentConfigDefaults:
    """Defaults mirror existing precedent constants (Invariant 8 + 9)."""

    def test_payment_tags_match_payment_proceeds_precedent(self) -> None:
        # Invariant 8; matches the default ``TreatmentConfig.payment_tags`` set
        # (formerly ``_DEFAULT_PAYMENT_TAGS`` in payment_proceeds.py, deleted by
        # Phase E Task 3).
        config = TreatmentConfig()
        assert config.payment_tags == frozenset({"payment", "card payment"})

    def test_loan_repayment_tags_exclude_borrow_side(self) -> None:
        # Invariant 9: ``"loan"`` is the borrowing-side principal-creation tag,
        # NOT a repayment; default must exclude it.
        config = TreatmentConfig()
        assert config.loan_repayment_tags == frozenset({"loan repayment"})
        assert "loan" not in config.loan_repayment_tags

    def test_derivatives_tags_default_empty(self) -> None:
        # Invariant 5: derivatives labels are injected from the JSON; default
        # must be an empty frozenset.
        config = TreatmentConfig()
        assert config.derivatives_tags == frozenset()

    def test_reward_tags_match_token_origin_precedent(self) -> None:
        # Invariant 8; matches the reward-tag tuple in token_origin.py.
        config = TreatmentConfig()
        assert config.reward_tags == frozenset({"reward", "cashback", "realized gain"})

    def test_airdrop_tags_match_token_origin_precedent(self) -> None:
        # Invariant 8; matches the airdrop branch in token_origin.py.
        config = TreatmentConfig()
        assert config.airdrop_tags == frozenset({"airdrop"})

    def test_lp_tags_match_token_origin_precedent(self) -> None:
        # Invariant 8; matches the LP branches in token_origin.py.
        config = TreatmentConfig()
        assert config.lp_tags == frozenset({"liquidity in", "liquidity out"})


class TestTreatmentConfig:
    """``TreatmentConfig`` is a frozen dataclass with exactly six fields."""

    def test_frozen(self) -> None:
        # Family D: immutable config.
        config = TreatmentConfig()
        with pytest.raises(FrozenInstanceError, match="cannot assign to field"):
            config.payment_tags = frozenset({"nope"})  # type: ignore[misc]

    def test_field_set_exactly_six(self) -> None:
        expected = {
            "payment_tags",
            "loan_repayment_tags",
            "derivatives_tags",
            "reward_tags",
            "airdrop_tags",
            "lp_tags",
        }
        actual = {f.name for f in fields(TreatmentConfig)}
        assert actual == expected

    def test_accepts_user_supplied_derivatives_tags(self) -> None:
        # Invariant 5: production callers inject the JSON-loaded set.
        config = TreatmentConfig(derivatives_tags=frozenset({"Realized gain"}))
        assert config.derivatives_tags == frozenset({"Realized gain"})

    def test_list_input_coerced_to_frozenset(self) -> None:
        # Post-``__post_init__`` coercion: the constructor MUST NOT raise; it
        # coerces list inputs to frozenset so a careless caller still works.
        config = TreatmentConfig(payment_tags=["payment", "card payment"])
        assert isinstance(config.payment_tags, frozenset)
        assert config.payment_tags == frozenset({"payment", "card payment"})


def _make_transaction(
    *,
    tag: str,
    type_: str,
    sending_currency: str | None,
    receiving_currency: str | None = None,
    row_index: int = 0,
) -> Transaction:
    """Build a minimal ``Transaction`` fixture for resolver tests.

    The resolver reads ``row.tag``, ``row.type``, and ``row.sending_currency``
    only; the other ``TransactionHistoryRow`` fields are populated with neutral
    defaults so the Phase-A constructor accepts the row. Mirrors the
    ``_row`` helper in ``test_transaction_factory.py`` (Phase A), but
    parametrizes the three fields the resolver consults.
    """
    row = TransactionHistoryRow(
        utc_instant=datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC),
        type=type_,
        tag=tag,
        sending_wallet="Kraken" if sending_currency is not None else "",
        sending_amount=Decimal("1.0") if sending_currency is not None else None,
        sending_currency=sending_currency,
        receiving_wallet="" if receiving_currency is not None else "Kraken",
        receiving_amount=Decimal("1.0") if receiving_currency is not None else None,
        receiving_currency=receiving_currency,
        tx_hash=None,
        tx_src=None,
        tx_dest=None,
        row_index=row_index,
    )
    return Transaction(
        row=row,
        wallet_kind=WalletKind.CEX,
        is_unrecognized_wallet=False,
    )


# ---------------------------------------------------------------------------
# Task 3: ``resolve_treatment`` matrix, default branch, case-insensitivity,
# precedence, and purity. See plan Task 3 for the full grid + invariant text.
# ---------------------------------------------------------------------------


class TestTreatmentMatrix:
    """The (Type, Tag, sending-side) -> Treatment grid (Invariant 1 + 2)."""

    @pytest.mark.parametrize(
        ("sending_currency", "type_", "tag", "expected"),
        [
            # Cells from the plan's matrix table. ``tag`` is shown verbatim;
            # the resolver normalizes both sides (Invariant 4).
            ("ETH", "exchange", "Payment", Treatment.PAYMENT),
            ("ETH", "exchange", "Card Payment", Treatment.PAYMENT),
            ("ETH", "exchange", "loan repayment", Treatment.LOAN_REPAYMENT),
            # Tag overrides side: loan_repayment tag with NO sending side still
            # classifies as LOAN_REPAYMENT.
            (None, "exchange", "loan repayment", Treatment.LOAN_REPAYMENT),
            # Disposal-shaped row with empty tag falls through to SPOT_DISPOSAL
            # (the disposal default; Invariant 3).
            ("ETH", "crypto_withdrawal", "", Treatment.SPOT_DISPOSAL),
            # Reward / airdrop / lp / cashback / realized-gain map to
            # REWARD_AIRDROP_LP (default ``reward_tags`` includes these).
            ("ETH", "exchange", "reward", Treatment.REWARD_AIRDROP_LP),
            ("ETH", "crypto_deposit", "airdrop", Treatment.REWARD_AIRDROP_LP),
            ("ETH", "crypto_withdrawal", "liquidity out", Treatment.REWARD_AIRDROP_LP),
            # LP "liquidity in" with no sending side still classifies as
            # REWARD_AIRDROP_LP (tag overrides side).
            (None, "crypto_deposit", "liquidity in", Treatment.REWARD_AIRDROP_LP),
            ("ETH", "crypto_withdrawal", "cashback", Treatment.REWARD_AIRDROP_LP),
            # ``"realized gain"`` is in the default ``reward_tags`` AND in the
            # production koinly_2025 derivatives JSON. With the default empty
            # ``derivatives_tags`` it resolves to REWARD_AIRDROP_LP; the
            # precedence test below pins the production-overlap flip.
            ("ETH", "crypto_withdrawal", "realized gain", Treatment.REWARD_AIRDROP_LP),
        ],
    )
    def test_matrix_cell(
        self,
        sending_currency: str | None,
        type_: str,
        tag: str,
        expected: Treatment,
    ) -> None:
        # Invariant 1 + 2: every cell maps to exactly one Treatment member.
        tx = _make_transaction(
            tag=tag,
            type_=type_,
            sending_currency=sending_currency,
            receiving_currency=None if sending_currency is not None else "ETH",
        )
        assert resolve_treatment(tx, TreatmentConfig()) is expected

    def test_derivatives_close_requires_injected_tag(self) -> None:
        # Invariant 5: with empty default ``derivatives_tags``, "Realized gain"
        # falls through to REWARD_AIRDROP_LP. Only an injected set flips it.
        tx = _make_transaction(
            tag="Realized gain",
            type_="crypto_withdrawal",
            sending_currency="ETH",
        )
        assert resolve_treatment(tx, TreatmentConfig()) is Treatment.REWARD_AIRDROP_LP

        injected = TreatmentConfig(derivatives_tags=frozenset({"Realized gain"}))
        assert resolve_treatment(tx, injected) is Treatment.DERIVATIVES_CLOSE

    def test_derivatives_close_tag_case_insensitive(self) -> None:
        # Invariant 4 bidirectional: lower-case config value matches a
        # mixed-case row tag.
        tx = _make_transaction(
            tag="Realized Gain",
            type_="crypto_withdrawal",
            sending_currency="ETH",
        )
        config = TreatmentConfig(derivatives_tags=frozenset({"realized gain"}))
        assert resolve_treatment(tx, config) is Treatment.DERIVATIVES_CLOSE


class TestTreatmentDefaultBranch:
    """The disposal-shape default (Invariant 3).

    ``row.sending_currency is not None`` -> ``SPOT_DISPOSAL`` default.
    ``None`` -> ``OTHER`` default. Special tags override regardless of side.
    The default branch keys off the sending side, NOT off ``Type`` and NOT off
    ``receiving_currency``.
    """

    def test_disposal_default_is_spot(self) -> None:
        tx = _make_transaction(
            tag="",
            type_="exchange",
            sending_currency="ETH",
        )
        assert resolve_treatment(tx, TreatmentConfig()) is Treatment.SPOT_DISPOSAL

    def test_nondisposal_default_is_other(self) -> None:
        tx = _make_transaction(
            tag="",
            type_="crypto_deposit",
            sending_currency=None,
            receiving_currency="ETH",
        )
        assert resolve_treatment(tx, TreatmentConfig()) is Treatment.OTHER

    def test_unknown_tag_on_disposal_defaults_to_spot(self) -> None:
        # Invariant 3: unknown tag does not change the disposal default.
        tx = _make_transaction(
            tag="something unknown",
            type_="exchange",
            sending_currency="ETH",
        )
        assert resolve_treatment(tx, TreatmentConfig()) is Treatment.SPOT_DISPOSAL

    def test_unknown_tag_on_nondisposal_defaults_to_other(self) -> None:
        tx = _make_transaction(
            tag="something unknown",
            type_="crypto_deposit",
            sending_currency=None,
            receiving_currency="ETH",
        )
        assert resolve_treatment(tx, TreatmentConfig()) is Treatment.OTHER

    def test_loan_borrowing_tag_falls_through_to_disposal_default(self) -> None:
        # Invariant 9: ``"loan"`` (the borrowing-side principal tag, NOT
        # repayment) is intentionally absent from ``loan_repayment_tags``, so
        # it does NOT match LOAN_REPAYMENT. The populated sending side then
        # triggers the SPOT_DISPOSAL default. This is the loud signal that the
        # borrowing tag is not classified as a repayment.
        tx = _make_transaction(
            tag="loan",
            type_="exchange",
            sending_currency="WBTC",
        )
        assert resolve_treatment(tx, TreatmentConfig()) is Treatment.SPOT_DISPOSAL


class TestTreatmentCaseInsensitive:
    """Tag matching is case-insensitive and whitespace-stripped (Invariant 4)."""

    @pytest.mark.parametrize("tag", ["Payment", "PAYMENT", " payment ", "PaYmEnT"])
    def test_payment_tag_case_variants(self, tag: str) -> None:
        tx = _make_transaction(
            tag=tag,
            type_="exchange",
            sending_currency="ETH",
        )
        assert resolve_treatment(tx, TreatmentConfig()) is Treatment.PAYMENT

    @pytest.mark.parametrize("tag", ["Reward", "REWARD", " reward "])
    def test_reward_tag_case_variants(self, tag: str) -> None:
        tx = _make_transaction(
            tag=tag,
            type_="exchange",
            sending_currency="ETH",
        )
        assert resolve_treatment(tx, TreatmentConfig()) is Treatment.REWARD_AIRDROP_LP

    def test_config_tag_case_insensitive_match(self) -> None:
        # Invariant 4 bidirectional: mixed-case value in the CONFIG also
        # matches a lower-case row tag.
        config = TreatmentConfig(payment_tags=frozenset({"PaYmEnT"}))
        tx = _make_transaction(
            tag="payment",
            type_="exchange",
            sending_currency="ETH",
        )
        assert resolve_treatment(tx, config) is Treatment.PAYMENT


class TestTreatmentPrecedence:
    """The Invariant 6 precedence order is fixed in code and asserted.

    Highest first:
        ``LOAN_REPAYMENT`` > ``PAYMENT`` > ``DERIVATIVES_CLOSE`` >
        ``REWARD_AIRDROP_LP`` > ``SPOT_DISPOSAL`` (default for
        disposal-shaped) > ``OTHER``.
    """

    def test_loan_repayment_trumps_payment(self) -> None:
        # Defensive: a tag configured to match BOTH sets resolves to
        # LOAN_REPAYMENT (higher precedence).
        config = TreatmentConfig(
            payment_tags=frozenset({"loan repayment"}),
            loan_repayment_tags=frozenset({"loan repayment"}),
        )
        tx = _make_transaction(
            tag="loan repayment",
            type_="exchange",
            sending_currency="ETH",
        )
        assert resolve_treatment(tx, config) is Treatment.LOAN_REPAYMENT

    def test_payment_trumps_derivatives_close(self) -> None:
        config = TreatmentConfig(
            derivatives_tags=frozenset({"payment"}),
            payment_tags=frozenset({"payment"}),
        )
        tx = _make_transaction(
            tag="payment",
            type_="exchange",
            sending_currency="ETH",
        )
        assert resolve_treatment(tx, config) is Treatment.PAYMENT

    def test_derivatives_close_trumps_reward(self) -> None:
        config = TreatmentConfig(
            derivatives_tags=frozenset({"reward"}),
            reward_tags=frozenset({"reward"}),
        )
        tx = _make_transaction(
            tag="reward",
            type_="exchange",
            sending_currency="ETH",
        )
        assert resolve_treatment(tx, config) is Treatment.DERIVATIVES_CLOSE

    def test_realized_gain_label_trumps_reward_tag(self) -> None:
        # Production-overlap point (Invariant 6 + plan Monitor). The default
        # ``reward_tags`` includes "realized gain"; the production koinly_2025
        # derivatives JSON injects "Realized gain". The precedence pins the
        # row to DERIVATIVES_CLOSE.
        config = TreatmentConfig(derivatives_tags=frozenset({"Realized gain"}))
        tx = _make_transaction(
            tag="Realized gain",
            type_="crypto_withdrawal",
            sending_currency="ETH",
        )
        assert resolve_treatment(tx, config) is Treatment.DERIVATIVES_CLOSE

    def test_reward_trumps_spot_default(self) -> None:
        # Covered by matrix but stated explicitly: a reward tag on a
        # disposal-shaped row resolves to REWARD_AIRDROP_LP, not the
        # SPOT_DISPOSAL default.
        tx = _make_transaction(
            tag="reward",
            type_="crypto_withdrawal",
            sending_currency="ETH",
        )
        assert resolve_treatment(tx, TreatmentConfig()) is Treatment.REWARD_AIRDROP_LP


class TestTreatmentPurity:
    """``resolve_treatment`` is a pure total function (Invariant 2 + family C).

    No I/O, no logging, no mutation of inputs, returns a ``Treatment`` member
    for every grid cell including whitespace-only and control-char tags.
    """

    def test_no_io_no_logging(
        self,
        caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        tx = _make_transaction(
            tag="Payment",
            type_="exchange",
            sending_currency="ETH",
        )
        stdout = io.StringIO()
        stderr = io.StringIO()
        monkeypatch.setattr(sys, "stdout", stdout)
        monkeypatch.setattr(sys, "stderr", stderr)

        with caplog.at_level(logging.DEBUG):
            result = resolve_treatment(tx, TreatmentConfig())

        assert isinstance(result, Treatment)
        assert stdout.getvalue() == ""
        assert stderr.getvalue() == ""
        assert caplog.records == []

    def test_no_mutation_of_inputs(self) -> None:
        tx = _make_transaction(
            tag="Payment",
            type_="exchange",
            sending_currency="ETH",
        )
        config = TreatmentConfig()
        tx_before = asdict(tx.row)
        config_before = {f.name: getattr(config, f.name) for f in fields(config)}
        tag_before = tx.row.tag
        sending_before = tx.row.sending_currency

        resolve_treatment(tx, config)

        assert asdict(tx.row) == tx_before
        assert {f.name: getattr(config, f.name) for f in fields(config)} == config_before
        assert tx.row.tag == tag_before
        assert tx.row.sending_currency == sending_before

    @pytest.mark.parametrize(
        ("tag", "type_", "sending_currency", "receiving_currency"),
        [
            # From the matrix grid (a sampling that exercises every treatment
            # value plus the default branches).
            ("Payment", "exchange", "ETH", None),
            ("Card Payment", "exchange", "ETH", None),
            ("loan repayment", "exchange", "ETH", None),
            ("loan repayment", "exchange", None, "ETH"),
            ("", "crypto_withdrawal", "ETH", None),
            ("reward", "exchange", "ETH", None),
            ("airdrop", "crypto_deposit", "ETH", None),
            ("liquidity out", "crypto_withdrawal", "ETH", None),
            ("liquidity in", "crypto_deposit", None, "ETH"),
            ("cashback", "crypto_withdrawal", "ETH", None),
            ("realized gain", "crypto_withdrawal", "ETH", None),
            # "Weird" cells: empty / whitespace-only / control chars / non-ASCII.
            # The ("", "crypto_withdrawal", "ETH", None) row is already covered
            # above as a matrix representative; do not duplicate it here.
            ("", "crypto_deposit", None, "ETH"),  # empty tag with no disposal side
            ("   ", "crypto_withdrawal", "ETH", None),  # whitespace-only + disposal
            ("   ", "crypto_deposit", None, "ETH"),  # whitespace-only + no disposal
            ("tag\twith\ncontrol", "exchange", "ETH", None),  # control chars
            ("pagaménto", "exchange", "ETH", None),  # non-ASCII tag
        ],
    )
    def test_returns_treatment_member_for_every_grid_cell(
        self,
        tag: str,
        type_: str,
        sending_currency: str | None,
        receiving_currency: str | None,
    ) -> None:
        # Invariant 2 (totality): every input returns a Treatment member; no
        # None, no exception. Whitespace-only tags collapse to the default
        # branch per Invariant 4 (``"   ".strip().lower() == ""``).
        tx = _make_transaction(
            tag=tag,
            type_=type_,
            sending_currency=sending_currency,
            receiving_currency=receiving_currency,
        )
        result = resolve_treatment(tx, TreatmentConfig())
        assert isinstance(result, Treatment)

    def test_returns_treatment_member_not_value(self) -> None:
        # Invariant 1: the result is a Treatment member, not the raw value.
        tx = _make_transaction(
            tag="Payment",
            type_="exchange",
            sending_currency="ETH",
        )
        result = resolve_treatment(tx, TreatmentConfig())
        assert isinstance(result, Treatment)
        assert result is Treatment.PAYMENT
        assert result == Treatment.PAYMENT  # value-equal too
        assert result != "payment"  # NOT equal to the raw string value
