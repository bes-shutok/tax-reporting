"""Tests for ``event_id`` on ``TransactionHistoryRow`` and ``TxCorrelationKey``.

On-Chain Transaction Tagger plan, Task 2 (Invariant 2; folds review F3, F7).

``event_id`` discriminates split Events within a single on-chain tx:
``None`` for Koinly rows (today's semantics preserved) and non-``None`` for
on-chain-derived split rows. The Koinly-path test exercises the production
``parse_th_row`` call site; the on-chain-path test constructs the dataclass
directly (the on-chain adapter lands in Task 10).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from tax_reporting.domain.transaction import (
    TransactionHistoryRow,
    TxCompositeKey,
    TxCorrelationKey,
)
from tax_reporting.infrastructure.koinly_parser import parse_th_row

_UTC_INSTANT = datetime(2025, 6, 14, 12, 33, 1, tzinfo=UTC)


def _koinly_th_row() -> dict[str, str]:
    """Minimal Koinly TH row dict (exercises the production parser path)."""
    return {
        "Date": "2025-06-14 12:33:01 UTC",
        "Type": "crypto_deposit",
        "Tag": "reward",
        "Sending Wallet": "",
        "Sent Amount": "",
        "Sent Currency": "",
        "Receiving Wallet": "Ledger 1",
        "Received Amount": "1,25000000",
        "Received Currency": "ETH",
        "TxHash": "0xhash",
        "TxSrc": "addrA",
        "TxDest": "addrB",
    }


class TestTransactionEventId:
    """``TransactionHistoryRow.event_id`` defaults and on-chain propagation."""

    def test_koinly_row_has_none_event_id(self) -> None:
        """Given a row built by the Koinly parser, expects event_id is None.

        ``parse_th_row`` does not set ``event_id``; the dataclass default None
        applies. This preserves today's Koinly semantics (Invariant 2).
        """
        row = parse_th_row(_koinly_th_row(), row_index=0)
        assert row.event_id is None

    def test_onchain_row_carries_event_id(self) -> None:
        """Given an on-chain-derived row, expects event_id is the Event identifier.

        The on-chain adapter (Task 10) sets ``event_id``; until it lands this
        test constructs the dataclass directly to pin the field's existence.
        """
        row = TransactionHistoryRow(
            utc_instant=_UTC_INSTANT,
            type="crypto_deposit",
            tag="reward",
            sending_wallet="",
            sending_amount=None,
            sending_currency=None,
            receiving_wallet="Ledger 1",
            receiving_amount=Decimal("1.25"),
            receiving_currency="ETH",
            tx_hash="0xhash",
            tx_src="addrA",
            tx_dest="addrB",
            row_index=0,
            event_id="evt1",
        )
        assert row.event_id == "evt1"


class TestTxCorrelationKey:
    """``TxCorrelationKey`` equality/hash incorporate ``event_id`` (review F7)."""

    @staticmethod
    def _key(*, tx_id: str | None, event_id: str | None = None, row_index: int = 0) -> TxCorrelationKey:
        return TxCorrelationKey(
            tx_id=tx_id,
            event_id=event_id,
            composite=TxCompositeKey(_UTC_INSTANT, "ETH", "Ledger 1", Decimal("1.25"), row_index),
        )

    def test_two_rows_same_hash_different_event_id_not_equal(self) -> None:
        """Given same tx_hash but different event_id, expects __eq__ returns False.

        Two on-chain split rows sharing a tx_hash but with different event_id
        must NOT collapse: equality keys on (tx_hash, event_id) when both
        non-None.
        """
        a = self._key(tx_id="0xhash", event_id="evt1")
        b = self._key(tx_id="0xhash", event_id="evt2")
        assert a != b

    def test_koinly_rows_same_hash_still_equal(self) -> None:
        """Given two Koinly rows (event_id=None) sharing tx_hash, expects equal.

        Koinly semantics preserved: when both event_id are None, equality
        reduces to today's tx_id-only match.
        """
        a = self._key(tx_id="0xhash", event_id=None, row_index=0)
        b = self._key(tx_id="0xhash", event_id=None, row_index=1)
        assert a == b

    def test_hash_incorporates_event_id(self) -> None:
        """Given same tx_id but different event_id, expects unequal AND both
        survive set insertion (review F7: ``hash((tx_id, event_id))`` when both
        present, else today's behavior).
        """
        a = self._key(tx_id="0xhash", event_id="evt1")
        b = self._key(tx_id="0xhash", event_id="evt2")
        assert a != b
        bucket = {a, b}
        assert len(bucket) == 2
        assert a in bucket
        assert b in bucket

    def test_mixed_event_id_none_and_set_not_equal(self) -> None:
        """Given one Koinly-style key (event_id=None) and one split key sharing
        the tx_hash, expects they are NOT equal (a split row must not collapse
        onto a Koinly-style row sharing the hash).
        """
        koinly = self._key(tx_id="0xhash", event_id=None)
        split = self._key(tx_id="0xhash", event_id="evt1")
        assert koinly != split

    def test_equal_onchain_keys_hash_equal(self) -> None:
        """Given two equal on-chain keys (same tx_id AND event_id), expects
        hash equality (review F7: hash/eq consistency contract)."""
        a = self._key(tx_id="0xhash", event_id="evt1", row_index=0)
        b = self._key(tx_id="0xhash", event_id="evt1", row_index=1)
        assert a == b
        assert hash(a) == hash(b)
