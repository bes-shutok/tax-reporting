"""``TxCorrelationKeyResolver`` (Phase A Task 6).

Turns a ``Transaction`` into a ``(TxCorrelationKey, requires_review)`` pair.

Two responsibilities, each isolated by an Invariant:

- **tx_id (Invariant 2 + 11).** ``tx_id = transaction.row.tx_hash``. There is
  no precedence chain through ``tx_src`` / ``tx_dest``: those fields carry
  wallet addresses, not transaction identifiers. ``tx_hash`` is already
  normalized to ``None`` when empty by ``parse_th_row`` (Invariant 3), so the
  resolver does not re-normalize.

- **DEX-aware review flag (Invariant 9).** ``requires_review`` is True iff
  ``tx_id is None and wallet_kind is DEX``. CEX rows with missing tx-id are
  silent (CEX routinely issue internal ids). UNKNOWN rows with missing tx-id
  are also silent; the loud signal for UNKNOWN is the
  ``Transaction.is_unrecognized_wallet`` flag set by ``build_transaction``.

The resolver reads ``Transaction.wallet_kind`` directly and MUST NOT call
the WalletKind resolver (``aggregate_platform_evidence`` /
``classify_platform``) itself (Invariant 8: data-loss observability - a
downstream consumer that builds keys must not silently lose the
wallet-classification signal).

Composite side-selection
------------------------

``TxCompositeKey`` is ``(utc_instant, asset, wallet, amount, row_index)``.
The resolver picks the side (sending vs receiving) that is non-blank on the
underlying row:

- Use the sending side when ``sending_wallet`` is non-empty AND
  ``sending_amount`` is not None AND ``sending_currency`` is not None.
  This is the disposal / trade / withdrawal shape.
- Otherwise use the receiving side (``receiving_wallet``,
  ``receiving_amount``, ``receiving_currency``). This is the
  ``crypto_deposit`` shape, where the sending side is blank by Koinly
  convention.

``row_index`` is sourced from ``transaction.row.row_index`` so the composite
is unique per TH row (Invariant 5).
"""

from __future__ import annotations

from decimal import Decimal

from tax_reporting.domain.transaction import (
    Transaction,
    TxCompositeKey,
    TxCorrelationKey,
    WalletKind,
)

__all__ = ["TxCorrelationKeyResolver"]

# Amount returned when the receiving-side branch is taken but the row's
# ``receiving_amount`` is somehow None. ``TxCompositeKey.amount`` is typed
# ``Decimal`` (not ``Decimal | None``), so the resolver cannot propagate None.
# The receiving branch is only chosen when the sending side is blank (i.e.
# ``crypto_deposit`` rows); a None ``receiving_amount`` on such a row is a
# data-quality oddity, surfaced as a zero rather than silently dropped.
_RECEIVING_SIDE_BLANK_AMOUNT = Decimal("0")


class TxCorrelationKeyResolver:
    """Builds a ``TxCorrelationKey`` plus DEX-aware review flag from a ``Transaction``.

    The resolver is stateless; ``resolve`` is exposed as a static method so
    callers can invoke ``TxCorrelationKeyResolver.resolve(txn)`` without
    instantiating the class. This matches the Phase A ergonomic in the plan
    (Task 6: "one method ``resolve(transaction)``") and the smoke chain in
    Task 9, which calls ``TxCorrelationKeyResolver.resolve(...)`` directly.
    """

    @staticmethod
    def resolve(transaction: Transaction) -> tuple[TxCorrelationKey, bool]:
        """Return ``(TxCorrelationKey, requires_review)`` for one ``Transaction``.

        Args:
            transaction: A ``Transaction`` whose ``wallet_kind`` has already
                been resolved upstream by the sanctioned ``build_transaction``
                factory. The resolver does NOT re-classify.

        Returns:
            A 2-tuple ``(key, requires_review)``. ``key.tx_id`` is
            ``row.tx_hash`` (possibly ``None``); ``key.composite`` is
            populated from the non-blank side of the row.
            ``requires_review`` is True iff the row has no ``tx_hash`` AND
            ``wallet_kind is DEX`` (Invariant 9).
        """
        row = transaction.row
        tx_id = row.tx_hash

        if row.sending_wallet and row.sending_amount is not None and row.sending_currency is not None:
            asset = row.sending_currency
            wallet = row.sending_wallet
            amount = row.sending_amount
        else:
            asset = row.receiving_currency if row.receiving_currency is not None else ""
            wallet = row.receiving_wallet
            amount = row.receiving_amount if row.receiving_amount is not None else _RECEIVING_SIDE_BLANK_AMOUNT

        composite = TxCompositeKey(
            utc_instant=row.utc_instant,
            asset=asset,
            wallet=wallet,
            amount=amount,
            row_index=row.row_index,
        )
        key = TxCorrelationKey(tx_id=tx_id, composite=composite)

        requires_review = tx_id is None and transaction.wallet_kind is WalletKind.DEX
        return key, requires_review
