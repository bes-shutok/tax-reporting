"""The sanctioned factory for ``Transaction`` (Phase A Task 5).

``build_transaction(row, classification)`` is the single sanctioned callsite
that pairs a ``TransactionHistoryRow`` with its resolved wallet
classification. It computes ``is_unrecognized_wallet`` per Invariant 8:

    is_unrecognized_wallet =
        (classification.source == "auto"
         and not classification.is_high_probability())
        OR classification.kind == WalletKind.UNKNOWN

Rationale: ``TxCorrelationKeyResolver.resolve`` reads
``Transaction.wallet_kind`` directly and MUST NOT call the resolver again
(Family G: data-loss observability - a downstream consumer that builds keys
must not silently lose the wallet-classification signal). Centralizing the
classification->flag derivation in this factory guarantees the flag rides
with the data, regardless of how many downstream consumers read the
``Transaction``.

The factory is a thin wrapper: it accepts a pre-computed
``WalletClassification`` (produced upstream by ``classify_platform``) and
does NOT call the classifier itself. The caller composes the two stages:

    evidence = aggregate_platform_evidence(rows)
    classification = classify_platform(platform, evidence.get(platform), registry)
    txn = build_transaction(row, classification)

Wallet-label attribution picks ``sending_wallet`` when non-empty, else
``receiving_wallet``. This mirrors ``_row_platform`` in
``application.crypto.wallet_kind`` and matches the production row shape: a
``crypto_deposit`` row has a blank sending side, so the receiving wallet is
the platform signal; the inverse holds for ``crypto_withdrawal`` rows.
"""

from __future__ import annotations

from tax_reporting.application.crypto.wallet_kind import WalletClassification
from tax_reporting.domain.transaction import Transaction, TransactionHistoryRow, WalletKind

__all__ = ["build_transaction"]


def build_transaction(
    row: TransactionHistoryRow,
    classification: WalletClassification,
) -> Transaction:
    """Pair a TH row with its wallet classification into a ``Transaction``.

    Derives ``is_unrecognized_wallet`` per Invariant 8 (amended 2026-07-06b):

        (classification.source == "auto"
         and not classification.is_high_probability())
        OR classification.kind == WalletKind.UNKNOWN

    The first clause flags auto-discovered platforms whose confidence is
    below the high-probability threshold (Invariants 7 + 12). Tier-1
    (registry) matches have ``confidence == 1.0`` and never trigger this
    clause. The second clause catches the explicit UNKNOWN case regardless
    of source (e.g. zero-evidence platforms return UNKNOWN at 0.0 confidence
    from the auto tier).

    Args:
        row: The typed ``TransactionHistoryRow`` this transaction is anchored on.
        classification: The pre-computed ``WalletClassification`` for the
            row's platform. Produced by ``classify_platform`` upstream; the
            factory does NOT re-classify.

    Returns:
        A frozen ``Transaction`` carrying the row, the wallet kind, and the
        derived ``is_unrecognized_wallet`` flag.
    """
    is_unrecognized_wallet = (
        classification.source == "auto" and not classification.is_high_probability()
    ) or classification.kind is WalletKind.UNKNOWN

    return Transaction(
        row=row,
        wallet_kind=classification.kind,
        is_unrecognized_wallet=is_unrecognized_wallet,
    )
