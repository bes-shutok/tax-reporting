"""Two-tier platform-level WalletKind resolver (Phase A Task 4).

Classifies a crypto platform as CEX (centralized/off-chain) or DEX
(decentralized/on-chain) at the **platform** level, not per wallet address,
because one CEX platform owns many rotating wallet addresses.

Tier 1 - registry (authoritative):
    A platform already mapped in the crypto-origin registry inherits its kind
    from the registry. Confidence is 1.0; source is ``"registry"``. The
    registry contract is the ``RegistrySnapshot`` Protocol defined below; the
    operator_origin layer does not currently classify CEX vs DEX, so callers
    pass ``registry=None`` until Task 7 populates it.

Tier 2 - auto-discovery (fallback):
    For platforms NOT in the registry, classify from per-platform TH row
    evidence:

    - on-chain vote: ``Type in {crypto_deposit, crypto_withdrawal}`` OR
      ``tx_hash`` matches any on-chain shape regex (EVM/BTC/Solana; see
      Invariant 13 and ``docs/tmp/phase-a-tx-id-semantics.md`` Q2).
    - off-chain vote: ``Type in {buy, sell, fiat_deposit, fiat_withdrawal}``
      OR ``tx_hash`` is non-None but does NOT match any on-chain shape.
    - confidence: ``majority_votes / total_votes`` where majority is
      ``max(on_chain, off_chain)``. When ``total == 0``, returns UNKNOWN at
      confidence 0.0.
    - kind: DEX if ``on_chain > off_chain``; CEX if ``off_chain > on_chain``;
      UNKNOWN on tie or zero total. (Tie behavior is documented here; the
      plan has no discriminating tie test, so this is the conservative pick.)

No hardcoded wallet labels appear in this module (CLAUDE.md rule + Invariant
7). The seed-list approach was explicitly rejected during plan amendment
2026-07-06b.

The high-probability threshold is the named module-level constant
``HIGH_PROBABILITY_THRESHOLD``. Inline numeric literals are forbidden
elsewhere (Invariant 12). The boundary direction is ``>=``: a platform at
exactly the threshold is NOT red-flagged.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal, Protocol

from tax_reporting.domain.transaction import TransactionHistoryRow, WalletKind

# ---------------------------------------------------------------------------
# Named constants (Invariant 12 + Invariant 13)
# ---------------------------------------------------------------------------

HIGH_PROBABILITY_THRESHOLD: float = 0.95
"""Boundary above which a platform's kind classification is treated as
high-probability. Comparison is ``>=``: a platform at exactly the threshold
is NOT red-flagged. Inline numeric literals for this threshold elsewhere are
forbidden."""

# On-chain TxHash shape facts (Invariant 13). Sourced from
# docs/tmp/phase-a-tx-id-semantics.md Q2.
EVM_TXHASH_REGEX: re.Pattern[str] = re.compile(r"^0x[0-9a-fA-F]{64}$")
"""EVM transaction hash: 66 chars total, ``0x`` prefix followed by 64 hex."""

BTC_TXHASH_REGEX: re.Pattern[str] = re.compile(r"^[0-9a-fA-F]{64}$")
"""Bitcoin transaction hash: 64 hex chars, no prefix."""

SOL_TXHASH_REGEX: re.Pattern[str] = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{88}$")
"""Solana transaction signature: 88 base58 chars (no 0/O/I/l)."""

_ON_CHAIN_TXHASH_REGEXES: tuple[re.Pattern[str], ...] = (
    EVM_TXHASH_REGEX,
    BTC_TXHASH_REGEX,
    SOL_TXHASH_REGEX,
)

_ON_CHAIN_TYPES: frozenset[str] = frozenset({"crypto_deposit", "crypto_withdrawal"})
_OFF_CHAIN_TYPES: frozenset[str] = frozenset({"buy", "sell", "fiat_deposit", "fiat_withdrawal"})


# ---------------------------------------------------------------------------
# RegistrySnapshot Protocol (tier-1 contract)
# ---------------------------------------------------------------------------


class RegistrySnapshot(Protocol):
    """Read-only contract over the crypto-origin registry for tier-1 classification.

    The existing ``operator_origin`` layer does NOT currently classify CEX vs
    DEX (it resolves chain/country only). Phase A introduces this Protocol so
    that Task 7 (Assumptions & Methodology Kind column) can adapt the
    registry data to the ``classify(platform)`` shape without a schema change
    to ``operator_origin`` (per plan amendment 2026-07-06b).

    Implementations may be a thin wrapper that maps each registry platform to
    its kind (CEX for off-chain operators, DEX for on-chain protocols). Phase
    A callers pass ``None`` to defer to tier 2.
    """

    def classify(self, platform: str) -> WalletKind | None:
        """Return the registry's WalletKind for ``platform``, or None if unmapped.

        Returning None signals "platform not in registry" so the caller falls
        through to tier-2 auto-discovery.
        """
        ...


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PlatformEvidence:
    """Per-platform tally of on-chain vs off-chain TH row evidence.

    Attributes:
        on_chain_votes: Rows whose Type is on-chain (crypto_deposit /
            crypto_withdrawal) OR whose tx_hash matches any on-chain shape.
        off_chain_votes: Rows whose Type is off-chain (buy / sell /
            fiat_deposit / fiat_withdrawal) OR whose tx_hash is non-None but
            does NOT match any on-chain shape.
        total: Sum of the two vote counts.
    """

    on_chain_votes: int
    off_chain_votes: int
    total: int


@dataclass(frozen=True)
class WalletClassification:
    """The result of classifying one platform.

    Attributes:
        kind: CEX, DEX, or UNKNOWN.
        confidence: ``majority_votes / total_votes`` for tier 2; 1.0 for
            tier 1 (registry) and 0.0 for "no rows".
        reason: Human-readable explanation naming the evidence counts or the
            registry source. Surfaced in the Assumptions & Methodology Note
            column when below threshold.
        source: ``"registry"`` for tier 1; ``"auto"`` for tier 2.
    """

    kind: WalletKind
    confidence: float
    reason: str
    source: Literal["registry", "auto"]

    def is_high_probability(self) -> bool:
        """Return True iff ``confidence >= HIGH_PROBABILITY_THRESHOLD``.

        Boundary direction is ``>=`` (Invariant 12): a platform at exactly
        the threshold value is high-probability (NOT red-flagged).
        """
        return self.confidence >= HIGH_PROBABILITY_THRESHOLD


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def _row_platform(row: TransactionHistoryRow) -> str | None:
    """Attribute a row to a single platform name.

    Prefer the sending wallet; if it is empty/Unknown, use the receiving
    wallet; if both are empty/Unknown, return None (the row carries no
    platform signal and is skipped).
    """
    sending = row.sending_wallet.strip() if row.sending_wallet else ""
    if sending and sending.lower() != "unknown":
        return row.sending_wallet
    receiving = row.receiving_wallet.strip() if row.receiving_wallet else ""
    if receiving and receiving.lower() != "unknown":
        return row.receiving_wallet
    return None


def _is_on_chain_hash(tx_hash: str | None) -> bool:
    """Return True iff tx_hash matches any of the on-chain shape regexes."""
    if not tx_hash:
        return False
    return any(regex.match(tx_hash) is not None for regex in _ON_CHAIN_TXHASH_REGEXES)


def _vote(row: TransactionHistoryRow) -> Literal["on_chain", "off_chain"] | None:
    """Return one row's platform-evidence vote, or None if it carries no signal.

    - on-chain vote: ``Type in {crypto_deposit, crypto_withdrawal}`` OR
      ``tx_hash`` matches any on-chain shape.
    - off-chain vote: ``Type in {buy, sell, fiat_deposit, fiat_withdrawal}``
      OR ``tx_hash`` is non-None but does NOT match any on-chain shape.
    - Rows with no Type match AND no tx_hash carry no signal (return None).
    """
    if row.type in _ON_CHAIN_TYPES:
        return "on_chain"
    if row.type in _OFF_CHAIN_TYPES:
        return "off_chain"
    # Type did not match either set; fall back to the tx_hash shape.
    if row.tx_hash is None:
        return None
    return "off_chain" if not _is_on_chain_hash(row.tx_hash) else "on_chain"


def aggregate_platform_evidence(
    rows: Iterable[TransactionHistoryRow],
) -> dict[str, PlatformEvidence]:
    """Aggregate per-platform on-chain vs off-chain row-evidence tallies.

    Each row is attributed to ONE platform (sending_wallet if non-empty /
    non-Unknown, else receiving_wallet). Rows where both wallets are empty /
    Unknown are skipped (no platform signal).

    Args:
        rows: Iterable of ``TransactionHistoryRow`` (typically the full TH).

    Returns:
        Dict mapping platform name to ``PlatformEvidence``. Platforms with
        zero voting rows are absent from the dict; the caller treats absence
        as "no evidence" when classifying.
    """
    on_chain: dict[str, int] = {}
    off_chain: dict[str, int] = {}
    for row in rows:
        platform = _row_platform(row)
        if platform is None:
            continue
        v = _vote(row)
        if v == "on_chain":
            on_chain[platform] = on_chain.get(platform, 0) + 1
        elif v == "off_chain":
            off_chain[platform] = off_chain.get(platform, 0) + 1
        # else: row carries no Type/tx_hash signal; skip silently.

    platforms = set(on_chain) | set(off_chain)
    return {
        p: PlatformEvidence(
            on_chain_votes=on_chain.get(p, 0),
            off_chain_votes=off_chain.get(p, 0),
            total=on_chain.get(p, 0) + off_chain.get(p, 0),
        )
        for p in platforms
    }


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def classify_platform(
    platform: str,
    evidence: PlatformEvidence | None,
    registry: RegistrySnapshot | None,
) -> WalletClassification:
    """Classify ``platform`` via the two-tier resolver.

    Tier 1 (registry) is authoritative: when the registry returns a kind,
    confidence is 1.0 and source is ``"registry"``, regardless of row
    evidence. Tier 2 (auto-discovery) classifies from the per-platform
    evidence majority; source is ``"auto"``.

    Args:
        platform: Platform name (already normalized; this function does not
            re-normalize).
        evidence: Per-platform ``PlatformEvidence`` from
            ``aggregate_platform_evidence``, or None when the platform had
            zero voting rows. Ignored if the registry matches.
        registry: Optional ``RegistrySnapshot`` for tier-1 lookup, or None.

    Returns:
        ``WalletClassification`` with ``kind``, ``confidence``, ``reason``,
        and ``source`` populated per the rules above.
    """
    # Tier 1: registry.
    if registry is not None:
        kind = registry.classify(platform)
        if kind is not None:
            return WalletClassification(
                kind=kind,
                confidence=1.0,
                reason="registry match",
                source="registry",
            )

    # Tier 2: auto-discovery.
    if evidence is None or evidence.total == 0:
        return WalletClassification(
            kind=WalletKind.UNKNOWN,
            confidence=0.0,
            reason="no rows",
            source="auto",
        )

    on_chain = evidence.on_chain_votes
    off_chain = evidence.off_chain_votes
    if on_chain > off_chain:
        kind = WalletKind.DEX
        majority = on_chain
    elif off_chain > on_chain:
        kind = WalletKind.CEX
        majority = off_chain
    else:
        # Tie (and total > 0): UNKNOWN. majority_votes for the confidence
        # formula is on_chain (== off_chain); confidence is therefore 0.5
        # at best, always below HIGH_PROBABILITY_THRESHOLD. Documented in
        # the module docstring.
        kind = WalletKind.UNKNOWN
        majority = on_chain

    confidence = majority / evidence.total
    reason = f"{on_chain} on-chain / {off_chain} off-chain"
    return WalletClassification(
        kind=kind,
        confidence=confidence,
        reason=reason,
        source="auto",
    )


__all__ = [
    "BTC_TXHASH_REGEX",
    "EVM_TXHASH_REGEX",
    "HIGH_PROBABILITY_THRESHOLD",
    "PlatformEvidence",
    "RegistrySnapshot",
    "SOL_TXHASH_REGEX",
    "WalletClassification",
    "WalletKind",
    "aggregate_platform_evidence",
    "classify_platform",
]
