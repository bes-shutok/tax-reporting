"""Consolidated transaction-domain types for the Phase A Transaction View.

This module hosts the typed value objects that the Phase A work introduces:

- ``TransactionHistoryRow`` (Task 2): a frozen dataclass mirroring a single
  Koinly Transaction History CSV row, with the three identifying fields
  ``tx_hash``, ``tx_src``, ``tx_dest`` preserved *separately*.
- ``WalletKind`` (Task 3): enum driving the missing-tx-id review-flag policy.
- ``Transaction`` (Task 3): frozen dataclass wrapping a row plus resolved
  ``WalletKind`` and an ``is_unrecognized_wallet`` flag.
- ``TxCompositeKey`` (Task 3): NamedTuple with ``row_index`` so two distinct
  TH rows never silently merge.
- ``TxCorrelationKey`` (Task 3): frozen dataclass with two-tier equality.

Why three separate fields instead of a single collapsed ``tx_id``
--------------------------------------------------------------

The Phase A Task 1 semantics study
([docs/tmp/phase-a-tx-id-semantics.md](../../../docs/tmp/phase-a-tx-id-semantics.md))
measured the real meaning of the three candidate Koinly columns on 125,468
production rows plus 34 committed synthetic rows. The findings (Invariant 2 +
Invariant 11, amended 2026-07-06):

- ``TxHash`` carries the on-chain transaction identifier (66-char EVM hash,
  64-hex BTC hash, 44-char Solana signature; or a short exchange-internal id
  for off-chain Types like ``buy`` / ``sell`` / ``fiat_deposit``). It is by far
  the strongest cross-row grouping key.
- ``TxSrc`` and ``TxDest`` carry *wallet addresses*, not hashes (dominated by
  42-char EVM addresses, with smaller populations of BTC/Solana addresses).
  They never hold the same value as ``TxHash`` on the same row.

Storing the three fields separately on the row lets later Phase B-D work
(transfer-leg correlation, LP-provenance migration, fee-filter hardening) use
the address fields for leg-direction reasoning without re-parsing the raw CSV.
The downstream ``TxCorrelationKey`` (built in a later task) keys on ``tx_hash``
alone, since the two legs of an A->B transfer share the same on-chain hash but
have *mirrored* addresses; collapsing the three into a single composite string
would fragment the transfer-leg clusters instead of strengthening them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import NamedTuple


class WalletKind(Enum):
    """Classification of a wallet label, used by the DEX-aware review-flag policy.

    Values:
        CEX: centralized exchange (e.g. Kraken, ByBit, Wirex). CEX routinely
            omit ``TxHash`` for internal movements; missing tx-id is expected
            and does NOT raise ``requires_review``.
        DEX: decentralized on-chain wallet (e.g. Ledger, SUI wallet). Should
            carry ``TxHash``; missing tx-id DOES raise ``requires_review``.
        UNKNOWN: label did not match the resolver's seed list. Treated as
            non-DEX for the review-flag policy; the loud signal is the
            ``is_unrecognized_wallet`` flag on ``Transaction``.
    """

    CEX = "cex"
    DEX = "dex"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class TransactionHistoryRow:
    """A single Koinly Transaction History row, normalized into typed fields.

    The row is built by ``parse_th_row`` in ``infrastructure.koinly_parser`` and
    is the single typed entry point into Phase A's transaction view. All
    normalization (date parsing, European-decimal parsing, platform-name
    normalization, empty/whitespace handling of the identifying fields) happens
    in the parser, not on the dataclass.

    Attributes:
        utc_instant: Timezone-aware datetime at UTC (Invariant 4). Koinly TH
            dates declare UTC via their ``YYYY-MM-DD HH:MM:SS UTC`` format.
        type: Raw ``Type`` column value (e.g. ``crypto_deposit``, ``exchange``).
        tag: Raw ``Tag`` column value (may be empty).
        sending_wallet: Normalized sending wallet name (``normalize_platform_name``).
        sending_amount: Decimal sent amount, or None when the row has no
            sending side (e.g. ``crypto_deposit`` rows).
        sending_currency: Sent currency ticker, or None when no sending side.
        receiving_wallet: Normalized receiving wallet name.
        receiving_amount: Decimal received amount, or None when the row has no
            receiving side.
        receiving_currency: Received currency ticker, or None when no receiving
            side.
        tx_hash: Stripped ``TxHash`` value, or None when empty/whitespace-only
            (Invariant 3). Carries the on-chain transaction identifier.
        tx_src: Stripped ``TxSrc`` value, or None when empty/whitespace-only.
            Carries a wallet address (not a hash).
        tx_dest: Stripped ``TxDest`` value, or None when empty/whitespace-only.
            Carries a wallet address (not a hash).
        row_index: 0-based source CSV row index, supplied by the parser call.
            Used by ``TxCompositeKey`` to guarantee two empty-tx-id rows never
            collide (Invariant 5).
    """

    utc_instant: datetime
    type: str
    tag: str
    sending_wallet: str
    sending_amount: Decimal | None
    sending_currency: str | None
    receiving_wallet: str
    receiving_amount: Decimal | None
    receiving_currency: str | None
    tx_hash: str | None
    tx_src: str | None
    tx_dest: str | None
    row_index: int


@dataclass(frozen=True)
class Transaction:
    """A ``TransactionHistoryRow`` paired with its resolved wallet classification.

    The sanctioned construction path is ``build_transaction`` in
    ``application.crypto.transaction_factory``, which calls the WalletKind
    resolver (``classify_platform`` from
    ``tax_reporting.application.crypto.wallet_kind``) once per row and derives
    ``is_unrecognized_wallet`` from the resulting ``WalletClassification``
    (see the factory's Invariant-8 rule). Direct constructor use is
    permitted but bypasses the UNKNOWN-warning signal (Invariant 8); see
    the factory's docstring.

    Attributes:
        row: The typed ``TransactionHistoryRow`` this transaction is anchored on.
        wallet_kind: Resolved wallet classification. NO default - the
            classification signal must be carried with the data, never silently
            defaulted (Invariant 8).
        is_unrecognized_wallet: True when the factory classified the row as
            ``UNKNOWN``, OR when the classification came from the auto tier
            with confidence below the high-probability threshold (0.95). The
            latter catches low-confidence auto-discovered kinds (CEX/DEX) that
            the registry has not yet authoritatively mapped. This is the loud
            signal for unseen labels; the DEX-aware review flag in
            ``TxCorrelationKeyResolver`` does NOT re-emit it.
    """

    row: TransactionHistoryRow
    wallet_kind: WalletKind
    is_unrecognized_wallet: bool


class TxCompositeKey(NamedTuple):
    """Tuple of (utc_instant, asset, wallet, amount, row_index).

    The ``row_index`` field makes the composite unique per TH row, so two
    distinct rows that coincide on the other four fields never collide when
    ``TxCorrelationKey.tx_id`` is None (Blocker 2 fix, Invariant 5).
    """

    utc_instant: datetime
    asset: str
    wallet: str
    amount: Decimal
    row_index: int


@dataclass(frozen=True)
class TxCorrelationKey:
    """Cross-report correlation key with two-tier equality (Invariant 5).

    Two keys are equal iff they share a non-None ``tx_id``, OR both have
    ``tx_id=None`` and byte-equal composites (including ``row_index``). The
    ``row_index`` field makes the composite unique per TH row, so distinct
    rows never collide. Consumers that previously indexed by
    ``(date, asset, wallet)`` tuples MUST NOT reuse those keys against
    ``TxCorrelationKey`` - the equality semantics differ. ``tx_id`` is
    sourced from ``TransactionHistoryRow.tx_hash`` (Invariant 2, amended
    2026-07-06); TxSrc/TxDest are wallet addresses and are NOT used to
    derive tx_id.

    Attributes:
        tx_id: ``tx_hash`` from the underlying row, or None when the row
            had no on-chain identifier. NEVER populated from ``tx_src`` or
            ``tx_dest`` (Invariant 2 + 11).
        composite: ``(utc_instant, asset, wallet, amount, row_index)`` tuple.
            Always carries ``row_index`` so two None-tx_id rows never silently
            merge.
    """

    tx_id: str | None
    composite: TxCompositeKey

    def __eq__(self, other: object) -> bool:
        """Two-tier equality per Invariant 5.

        Equal iff both have non-None matching tx_id, OR both have tx_id=None
        and byte-equal composites. Mixed None/non-None pairs are never equal.
        """
        if not isinstance(other, TxCorrelationKey):
            return NotImplemented
        if self.tx_id is not None and other.tx_id is not None:
            return self.tx_id == other.tx_id
        if self.tx_id is None and other.tx_id is None:
            return self.composite == other.composite
        return False

    def __hash__(self) -> int:
        """Hash consistent with __eq__: tx_id-only when present, else composite hash."""
        if self.tx_id is not None:
            return hash(self.tx_id)
        return hash(self.composite)
