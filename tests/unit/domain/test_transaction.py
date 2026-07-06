"""Tests for the consolidated transaction domain module.

Covers ``TransactionHistoryRow`` (Task 2) plus ``Transaction``,
``TxCompositeKey``, ``TxCorrelationKey`` (Task 3). The ``parse_th_row`` parser
tests live in ``tests/unit/infrastructure/test_koinly_parser_th_row.py``; this
file holds the row-type invariants (field shape, normalization) by calling the
parser as a fixture-of-state.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from tax_reporting.domain.transaction import (
    Transaction,
    TransactionHistoryRow,
    TxCompositeKey,
    TxCorrelationKey,
    WalletKind,
)
from tax_reporting.infrastructure.koinly_parser import parse_th_row


def _base_row() -> dict[str, str]:
    """Return a minimal valid TH row dict that exercises no edge cases."""
    return {
        "Date": "2025-06-14 12:33:01 UTC",
        "Type": "crypto_deposit",
        "Tag": "reward",
        "Sending Wallet": "",
        "Sent Amount": "",
        "Sent Currency": "",
        "Receiving Wallet": "Kraken",
        "Received Amount": "1,25000000",
        "Received Currency": "ETH",
        "TxHash": "0xh",
        "TxSrc": "addrA",
        "TxDest": "addrB",
    }


class TestTransactionHistoryRow:
    """Tests for the frozen ``TransactionHistoryRow`` dataclass."""

    def test_frozen(self) -> None:
        """Given a constructed row, attribute assignment raises FrozenInstanceError."""
        row = parse_th_row(_base_row(), row_index=0)
        with pytest.raises(dataclasses.FrozenInstanceError):
            row.type = "exchange"  # type: ignore[misc]

    def test_stores_tx_hash_tx_src_tx_dest_separately(self) -> None:
        """Given distinct TxHash/TxSrc/TxDest values, expects three distinct fields."""
        parsed = parse_th_row(_base_row(), row_index=0)
        assert parsed.tx_hash == "0xh"
        assert parsed.tx_src == "addrA"
        assert parsed.tx_dest == "addrB"

    def test_no_derived_tx_id_field_on_row(self) -> None:
        """Given the dataclass fields, expects tx_hash/tx_src/tx_dest but NOT tx_id."""
        field_names = {f.name for f in dataclasses.fields(TransactionHistoryRow)}
        assert "tx_hash" in field_names
        assert "tx_src" in field_names
        assert "tx_dest" in field_names
        assert "tx_id" not in field_names

    def test_tx_hash_normalizes_empty_to_none(self) -> None:
        """Given TxHash="", expects tx_hash is None."""
        row = _base_row()
        row["TxHash"] = ""
        parsed = parse_th_row(row, row_index=0)
        assert parsed.tx_hash is None

    def test_tx_src_normalizes_empty_to_none(self) -> None:
        """Given TxSrc whitespace-only, expects tx_src is None."""
        row = _base_row()
        row["TxSrc"] = "   "
        parsed = parse_th_row(row, row_index=0)
        assert parsed.tx_src is None

    def test_tx_dest_normalizes_empty_to_none(self) -> None:
        """Given TxDest="", expects tx_dest is None."""
        row = _base_row()
        row["TxDest"] = ""
        parsed = parse_th_row(row, row_index=0)
        assert parsed.tx_dest is None

    def test_tx_hash_strips_whitespace(self) -> None:
        """Given TxHash with surrounding whitespace, expects the stripped value."""
        row = _base_row()
        row["TxHash"] = "  0xhash123  "
        parsed = parse_th_row(row, row_index=0)
        assert parsed.tx_hash == "0xhash123"

    def test_utc_instant_is_timezone_aware_utc(self) -> None:
        """Given a TH Date string, expects utc_instant to be timezone-aware at UTC."""
        parsed = parse_th_row(_base_row(), row_index=0)
        assert parsed.utc_instant.tzinfo is UTC
        assert parsed.utc_instant.utcoffset() == timedelta(0)

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("143,75200000", Decimal("143.75200000")),
            ("5.131,00000000", Decimal("5131.00000000")),
        ],
    )
    def test_amounts_parsed_via_parse_koinly_decimal_european_thousands(self, raw: str, expected: Decimal) -> None:
        """Given European-format decimals, expects parse_koinly_decimal delegation."""
        row = _base_row()
        row["Received Amount"] = raw
        parsed = parse_th_row(row, row_index=0)
        assert parsed.receiving_amount == expected

    def test_amounts_blank_when_row_has_no_sending_side(self) -> None:
        """Given a crypto_deposit row with no sending side, expects None for both."""
        parsed = parse_th_row(_base_row(), row_index=0)
        assert parsed.sending_amount is None
        assert parsed.sending_currency is None

    def test_row_index_assigned_from_parser_arg(self) -> None:
        """Given parse_th_row(row, row_index=42), expects parsed.row_index == 42."""
        parsed = parse_th_row(_base_row(), row_index=42)
        assert parsed.row_index == 42


def _make_row(row_index: int = 0) -> TransactionHistoryRow:
    """Build a minimal valid TransactionHistoryRow for Transaction tests."""
    return parse_th_row(_base_row(), row_index=row_index)


class TestTransaction:
    """Tests for the frozen ``Transaction`` domain object."""

    def test_frozen(self) -> None:
        """Given a constructed Transaction, attribute assignment raises FrozenInstanceError."""
        txn = Transaction(
            row=_make_row(),
            wallet_kind=WalletKind.CEX,
            is_unrecognized_wallet=False,
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            txn.is_unrecognized_wallet = True  # type: ignore[misc]

    def test_carries_typed_row_wallet_kind_and_unrecognized_flag(self) -> None:
        """Given a row plus wallet_kind and flag, expects field access returns those values."""
        row = _make_row(row_index=7)
        txn = Transaction(
            row=row,
            wallet_kind=WalletKind.CEX,
            is_unrecognized_wallet=False,
        )
        assert txn.row is row
        assert txn.wallet_kind is WalletKind.CEX
        assert txn.is_unrecognized_wallet is False

    def test_wallet_kind_and_flag_required_no_default(self) -> None:
        """Given a Transaction built without wallet_kind or flag, expects TypeError. (Invariant 8.)"""
        row = _make_row()
        with pytest.raises(TypeError):
            Transaction(row=row)  # type: ignore[call-arg]
        with pytest.raises(TypeError):
            Transaction(row=row, wallet_kind=WalletKind.CEX)  # type: ignore[call-arg]
        with pytest.raises(TypeError):
            Transaction(row=row, is_unrecognized_wallet=False)  # type: ignore[call-arg]

    def test_field_set_exactly_three(self) -> None:
        """Given the dataclass fields, expects exactly {row, wallet_kind, is_unrecognized_wallet}."""
        field_names = {f.name for f in dataclasses.fields(Transaction)}
        assert field_names == {"row", "wallet_kind", "is_unrecognized_wallet"}


class TestTxCompositeKey:
    """Tests for the ``TxCompositeKey`` NamedTuple (Blocker 2 fix: row_index)."""

    def test_includes_row_index(self) -> None:
        """Given identical (utc, asset, wallet, amount) but row_index=3 vs 4, expects unequal and different hashes."""
        utc = datetime(2025, 6, 14, 12, 33, 1, tzinfo=UTC)
        common = (utc, "ETH", "Kraken", Decimal("1.25"))
        key_a = TxCompositeKey(*common, row_index=3)
        key_b = TxCompositeKey(*common, row_index=4)
        assert key_a != key_b
        assert hash(key_a) != hash(key_b)


class TestTxCorrelationKey:
    """Tests for the ``TxCorrelationKey`` frozen dataclass (Invariant 5: two-tier equality)."""

    def test_frozen(self) -> None:
        """Given a constructed TxCorrelationKey, attribute assignment raises FrozenInstanceError."""
        utc = datetime(2025, 6, 14, 12, 33, 1, tzinfo=UTC)
        key = TxCorrelationKey(
            tx_id="0x1",
            composite=TxCompositeKey(utc, "ETH", "Kraken", Decimal("1.25"), 0),
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            key.tx_id = "0x2"  # type: ignore[misc]

    def test_equal_when_tx_id_matches_composite_differs(self) -> None:
        """Given A and B with same tx_id but different composites, expects A == B and hash(A) == hash(B)."""
        utc = datetime(2025, 6, 14, 12, 33, 1, tzinfo=UTC)
        composite_x = TxCompositeKey(utc, "ETH", "Kraken", Decimal("1.25"), 0)
        composite_y = TxCompositeKey(utc, "BTC", "Ledger", Decimal("0.5"), 1)
        assert composite_x != composite_y
        a = TxCorrelationKey(tx_id="0x1", composite=composite_x)
        b = TxCorrelationKey(tx_id="0x1", composite=composite_y)
        assert a == b
        assert hash(a) == hash(b)

    def test_equal_when_both_none_and_composite_byte_equal(self) -> None:
        """Given two keys with tx_id=None and byte-equal composites, expects A == B and hash(A) == hash(B)."""
        utc = datetime(2025, 6, 14, 12, 33, 1, tzinfo=UTC)
        composite_a = TxCompositeKey(utc, "ETH", "Kraken", Decimal("1.25"), 5)
        composite_b = TxCompositeKey(utc, "ETH", "Kraken", Decimal("1.25"), 5)
        a = TxCorrelationKey(tx_id=None, composite=composite_a)
        b = TxCorrelationKey(tx_id=None, composite=composite_b)
        assert a == b
        assert hash(a) == hash(b)

    def test_unequal_when_both_none_and_composite_differs(self) -> None:
        """Given two keys with tx_id=None and composites that differ in row_index only, expects A != B."""
        utc = datetime(2025, 6, 14, 12, 33, 1, tzinfo=UTC)
        composite_a = TxCompositeKey(utc, "ETH", "Kraken", Decimal("1.25"), 3)
        composite_b = TxCompositeKey(utc, "ETH", "Kraken", Decimal("1.25"), 4)
        a = TxCorrelationKey(tx_id=None, composite=composite_a)
        b = TxCorrelationKey(tx_id=None, composite=composite_b)
        assert a != b

    def test_unequal_when_one_none_one_set(self) -> None:
        """Given A with tx_id=None, B with tx_id='0x1' (same composite), expects A != B."""
        utc = datetime(2025, 6, 14, 12, 33, 1, tzinfo=UTC)
        composite = TxCompositeKey(utc, "ETH", "Kraken", Decimal("1.25"), 0)
        a = TxCorrelationKey(tx_id=None, composite=composite)
        b = TxCorrelationKey(tx_id="0x1", composite=composite)
        assert a != b

    @pytest.mark.parametrize(
        "label",
        ["equal-both-id", "equal-both-none", "unequal-both-none", "unequal-mixed"],
    )
    def test_hash_algorithm_parametrized(self, label: str) -> None:
        """For every Invariant-5 case, A == B implies hash(A) == hash(B). (Medium 7.)"""
        utc = datetime(2025, 6, 14, 12, 33, 1, tzinfo=UTC)
        c0 = TxCompositeKey(utc, "ETH", "Kraken", Decimal("1.25"), 0)
        c1 = TxCompositeKey(utc, "ETH", "Kraken", Decimal("1.25"), 1)
        if label == "equal-both-id":
            a = TxCorrelationKey(tx_id="0x1", composite=c0)
            b = TxCorrelationKey(tx_id="0x1", composite=c1)
        elif label == "equal-both-none":
            a = TxCorrelationKey(tx_id=None, composite=c0)
            b = TxCorrelationKey(tx_id=None, composite=c0)
        elif label == "unequal-both-none":
            a = TxCorrelationKey(tx_id=None, composite=c0)
            b = TxCorrelationKey(tx_id=None, composite=c1)
        else:  # unequal-mixed
            a = TxCorrelationKey(tx_id=None, composite=c0)
            b = TxCorrelationKey(tx_id="0x1", composite=c0)

        if a == b:
            assert hash(a) == hash(b)
        else:
            # Equal hashes for unequal objects is allowed by Python's eq/hash contract;
            # the test's discriminating assertion for unequal cases lives in the
            # case-specific tests above. Here we only verify the contract direction
            # that equal-implies-equal-hash holds.
            assert hash(a) == hash(a)

    def test_hash_not_degenerate_for_unequal_keys(self) -> None:
        """Given two unequal keys with different tx_ids and composites, expects hash(A) != hash(B). (Monitor 3.)"""
        utc = datetime(2025, 6, 14, 12, 33, 1, tzinfo=UTC)
        a = TxCorrelationKey(
            tx_id="0xaaa",
            composite=TxCompositeKey(utc, "ETH", "Kraken", Decimal("1.25"), 0),
        )
        b = TxCorrelationKey(
            tx_id="0xbbb",
            composite=TxCompositeKey(utc, "BTC", "Ledger", Decimal("0.5"), 1),
        )
        assert a != b
        assert hash(a) != hash(b)
