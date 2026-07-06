"""Tests for ``TxCorrelationKeyResolver`` (Task 6, Phase A).

The resolver turns a ``Transaction`` into a ``(TxCorrelationKey, requires_review)``
pair. ``tx_id`` derives from ``row.tx_hash`` alone (Invariant 2 + 11); no
precedence chain through ``tx_src`` / ``tx_dest``. ``requires_review`` is True
iff ``tx_id is None and wallet_kind is DEX`` (Invariant 9: DEX-only flagging).

Plan Task 6 list, 11 cases. Each case pins one independent guard.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from tax_reporting.application.crypto import wallet_kind as wallet_kind_module
from tax_reporting.application.crypto.tx_correlation_key_resolver import (
    TxCorrelationKeyResolver,
)
from tax_reporting.domain.transaction import (
    Transaction,
    TransactionHistoryRow,
    TxCompositeKey,
    WalletKind,
)

_UTC_INSTANT = datetime(2025, 3, 14, 12, 30, 0, tzinfo=UTC)


def _row(  # noqa: PLR0913
    *,
    tx_hash: str | None = None,
    tx_src: str | None = None,
    tx_dest: str | None = None,
    sending_wallet: str = "",
    sending_amount: Decimal | None = None,
    sending_currency: str | None = None,
    receiving_wallet: str = "",
    receiving_amount: Decimal | None = None,
    receiving_currency: str | None = None,
    type_: str = "trade",
    row_index: int = 0,
) -> TransactionHistoryRow:
    """Build a ``TransactionHistoryRow`` with the test's identifying fields.

    Defaults to an empty identifying triple so each test pins exactly the
    field under test (composite side selection defaults to the sending side
    being populated).
    """
    return TransactionHistoryRow(
        utc_instant=_UTC_INSTANT,
        type=type_,
        tag="",
        sending_wallet=sending_wallet,
        sending_amount=sending_amount,
        sending_currency=sending_currency,
        receiving_wallet=receiving_wallet,
        receiving_amount=receiving_amount,
        receiving_currency=receiving_currency,
        tx_hash=tx_hash,
        tx_src=tx_src,
        tx_dest=tx_dest,
        row_index=row_index,
    )


def _transaction(
    *,
    wallet_kind: WalletKind,
    row: TransactionHistoryRow,
    is_unrecognized_wallet: bool = False,
) -> Transaction:
    """Build a ``Transaction`` directly with the test's wallet kind.

    The resolver reads ``wallet_kind`` and never calls the WalletKindResolver
    (Invariant 8). The ``is_unrecognized_wallet`` flag has a neutral default
    so tests that don't care about it stay focused.
    """
    return Transaction(
        row=row,
        wallet_kind=wallet_kind,
        is_unrecognized_wallet=is_unrecognized_wallet,
    )


class TestTxCorrelationKeyResolver:
    def test_dex_missing_tx_hash_requires_review(self) -> None:
        row = _row(tx_hash=None)
        txn = _transaction(wallet_kind=WalletKind.DEX, row=row)

        _, requires_review = TxCorrelationKeyResolver.resolve(txn)

        assert requires_review is True

    def test_cex_missing_tx_hash_no_review(self) -> None:
        row = _row(tx_hash=None)
        txn = _transaction(wallet_kind=WalletKind.CEX, row=row)

        _, requires_review = TxCorrelationKeyResolver.resolve(txn)

        assert requires_review is False

    def test_dex_with_tx_hash_no_review(self) -> None:
        row = _row(tx_hash="0xabc")
        txn = _transaction(wallet_kind=WalletKind.DEX, row=row)

        _, requires_review = TxCorrelationKeyResolver.resolve(txn)

        assert requires_review is False

    def test_cex_with_tx_hash_no_review(self) -> None:
        row = _row(tx_hash="0xabc")
        txn = _transaction(wallet_kind=WalletKind.CEX, row=row)

        _, requires_review = TxCorrelationKeyResolver.resolve(txn)

        assert requires_review is False

    def test_unknown_missing_tx_hash_no_review(self, caplog: object) -> None:
        row = _row(tx_hash=None)
        txn = _transaction(
            wallet_kind=WalletKind.UNKNOWN,
            row=row,
            is_unrecognized_wallet=True,
        )

        import logging

        with caplog.at_level(  # type: ignore[attr-defined]
            logging.WARNING, logger="tax_reporting"
        ):
            _, requires_review = TxCorrelationKeyResolver.resolve(txn)

        assert requires_review is False
        # Invariant 9: UNKNOWN with missing tx_hash emits no extra warning.
        resolver_warnings = [
            r
            for r in caplog.records  # type: ignore[attr-defined]
            if "TxCorrelationKeyResolver" in r.name
        ]
        assert resolver_warnings == []

    def test_returns_key_with_tx_id_sourced_from_tx_hash_when_present(self) -> None:
        row = _row(
            tx_hash="0xabc",
            sending_wallet="Ledger 1",
            sending_amount=Decimal("5.2"),
            sending_currency="BERA",
            row_index=7,
        )
        txn = _transaction(wallet_kind=WalletKind.DEX, row=row)

        key, _ = TxCorrelationKeyResolver.resolve(txn)

        assert key.tx_id == "0xabc"
        assert key.composite == TxCompositeKey(_UTC_INSTANT, "BERA", "Ledger 1", Decimal("5.2"), 7)

    def test_returns_key_with_none_when_tx_hash_absent(self) -> None:
        row = _row(
            tx_hash=None,
            sending_wallet="Ledger 1",
            sending_amount=Decimal("5.2"),
            sending_currency="BERA",
            row_index=9,
        )
        txn = _transaction(wallet_kind=WalletKind.CEX, row=row)

        key, _ = TxCorrelationKeyResolver.resolve(txn)

        assert key.tx_id is None
        assert key.composite == TxCompositeKey(_UTC_INSTANT, "BERA", "Ledger 1", Decimal("5.2"), 9)

    def test_tx_src_and_tx_dest_do_not_surface_as_tx_id(self) -> None:
        row = _row(
            tx_hash=None,
            tx_src="addrA",
            tx_dest="addrB",
            sending_wallet="Ledger 1",
            sending_amount=Decimal("1.0"),
            sending_currency="USDT",
        )
        txn = _transaction(wallet_kind=WalletKind.DEX, row=row)

        key, _ = TxCorrelationKeyResolver.resolve(txn)

        assert key.tx_id is None

    def test_composite_uses_sending_side_for_trade_disposal(self) -> None:
        row = _row(
            sending_wallet="Ledger 1",
            sending_amount=Decimal("5.2"),
            sending_currency="BERA",
            row_index=17,
        )
        txn = _transaction(wallet_kind=WalletKind.DEX, row=row)

        key, _ = TxCorrelationKeyResolver.resolve(txn)

        assert key.composite == TxCompositeKey(_UTC_INSTANT, "BERA", "Ledger 1", Decimal("5.2"), 17)

    def test_composite_uses_receiving_side_for_deposit(self) -> None:
        row = _row(
            sending_wallet="",
            sending_amount=None,
            sending_currency=None,
            receiving_wallet="Ledger 1",
            receiving_amount=Decimal("3.7"),
            receiving_currency="ETH",
            type_="crypto_deposit",
            row_index=21,
        )
        txn = _transaction(wallet_kind=WalletKind.DEX, row=row)

        key, _ = TxCorrelationKeyResolver.resolve(txn)

        assert key.composite == TxCompositeKey(_UTC_INSTANT, "ETH", "Ledger 1", Decimal("3.7"), 21)

    def test_resolver_does_not_call_wallet_kind_resolver_directly(self, monkeypatch: object) -> None:
        """Invariant 8: resolver reads ``Transaction.wallet_kind``; it does
        not invoke ``classify_platform`` itself. Patching the classifier to
        raise must NOT affect ``TxCorrelationKeyResolver.resolve``.
        """

        def _explode(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("resolver must not call classify_platform")

        monkeypatch.setattr(  # type: ignore[attr-defined]
            wallet_kind_module, "classify_platform", _explode
        )
        row = _row(tx_hash="0xabc")
        txn = _transaction(wallet_kind=WalletKind.DEX, row=row)

        # Must not raise: the resolver consumes the pre-resolved wallet_kind.
        key, requires_review = TxCorrelationKeyResolver.resolve(txn)

        assert key.tx_id == "0xabc"
        assert requires_review is False
