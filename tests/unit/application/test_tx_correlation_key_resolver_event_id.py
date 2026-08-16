"""Tests for ``TxCorrelationKeyResolver`` threading ``event_id`` (Task 2).

On-Chain Transaction Tagger plan, Task 2 (review F3: the sole constructor at
``tx_correlation_key_resolver.resolve`` must read ``row.event_id``, not silently
default it).

NOTE: a same-named ``TestTxCorrelationKeyResolver`` class lives in
``tests/unit/application/test_tx_correlation_key_resolver.py``. pytest
collects classes per-module, so the duplicate name across distinct modules
does not collide.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from tax_reporting.application.crypto.tx_correlation_key_resolver import (
    TxCorrelationKeyResolver,
)
from tax_reporting.domain.transaction import (
    Transaction,
    TransactionHistoryRow,
    WalletKind,
)

_UTC_INSTANT = datetime(2025, 3, 14, 12, 30, 0, tzinfo=UTC)


def _row(*, tx_hash: str | None, event_id: str | None) -> TransactionHistoryRow:
    return TransactionHistoryRow(
        utc_instant=_UTC_INSTANT,
        type="crypto_deposit",
        tag="reward",
        sending_wallet="",
        sending_amount=None,
        sending_currency=None,
        receiving_wallet="Ledger 1",
        receiving_amount=Decimal("3.7"),
        receiving_currency="ETH",
        tx_hash=tx_hash,
        tx_src="addrA",
        tx_dest="addrB",
        row_index=0,
        event_id=event_id,
    )


def _transaction(row: TransactionHistoryRow) -> Transaction:
    return Transaction(
        row=row,
        wallet_kind=WalletKind.DEX,
        is_unrecognized_wallet=False,
    )


class TestTxCorrelationKeyResolver:
    """The resolver reads ``row.event_id`` and threads it onto the key (F3)."""

    def test_resolver_passes_event_id_through(self) -> None:
        """Given a row with event_id='evt2', expects resolve produces a key
        carrying event_id='evt2'.

        Review F3: the sole ``TxCorrelationKey`` constructor site must read
        ``row.event_id`` and pass it to the constructor, not silently default
        it. Without this, the amendment is dead code.
        """
        row = _row(tx_hash="0xhash", event_id="evt2")
        txn = _transaction(row)

        key, _ = TxCorrelationKeyResolver.resolve(txn)

        assert key.event_id == "evt2"

    def test_koinly_row_resolves_event_id_none(self) -> None:
        """Given a Koinly row (event_id=None), expects resolve produces a key
        with event_id=None (today's behavior preserved)."""
        row = _row(tx_hash="0xhash", event_id=None)
        txn = _transaction(row)

        key, _ = TxCorrelationKeyResolver.resolve(txn)

        assert key.event_id is None
