"""Shared CryptoReviewEntry construction helpers for the crypto dedup passes.

The derivatives and fee dedup filters build structurally identical surplus-lot
and malformed-input-lot review rows that differ only in a domain prefix
(r1 F1 prefix asymmetry: derivatives prepends nothing; fee prepends
``"Fee CG dedup: "``). Centralizing the construction here collapses the
duplication (W6/W7 surplus-malformed dedup) while keeping the removed-lot
blocks inline in each caller (they genuinely diverge - derivatives "removed lot
matched to OGR disposal" vs fee's branch-aware tagged/embedded/
untagged-whitelisted logic; NOT dedupable per INV-text).

INV-text: the reason text below is frozen byte-identical to the pre-refactor
inline wording in both callers; do not reword without a tracking change.
"""

from __future__ import annotations

from collections.abc import Sequence

from .entities import CryptoCapitalGainEntry, CryptoReviewEntry
from .th_lot_matcher import IndexedLot


def _append_surplus_and_malformed_review_rows(
    review_entries: list[CryptoReviewEntry],
    surplus_lots: Sequence[IndexedLot],
    malformed_lots: Sequence[CryptoCapitalGainEntry],
    *,
    surplus_prefix: str,
    malformed_prefix: str,
) -> None:
    """Append surplus-lot and malformed-input-lot review rows.

    Both row kinds are ``is_suspicious=True`` and sourced from the capital-gains
    section. The caller supplies the domain prefix (r1 F1 prefix asymmetry:
    derivatives passes ``""``; fee passes ``"Fee CG dedup: "``).

    Args:
        review_entries: The caller-owned list to append to (mutated in place).
        surplus_lots: Surplus lots wrapped in :class:`IndexedLot`
            (``lot.entry`` is the underlying :class:`CryptoCapitalGainEntry`).
        malformed_lots: Malformed-input lots, passed as bare
            :class:`CryptoCapitalGainEntry` instances (the matcher returns them
            without an index wrapper).
        surplus_prefix: Prefix prepended to the surplus-lot reason text.
        malformed_prefix: Prefix prepended to the malformed-input-lot reason
            text.
    """
    for lot in surplus_lots:
        entry = lot.entry
        review_entries.append(
            CryptoReviewEntry(
                source_section="capital_gains",
                date=entry.disposal_timestamp or entry.disposal_date,
                asset=entry.asset,
                platform=entry.wallet,
                review_reason=(
                    f"{surplus_prefix}Surplus lot - may indicate a missed FIFO "
                    f"split; review the listed key"
                ),
                is_suspicious=True,
            )
        )
    for entry in malformed_lots:
        review_entries.append(
            CryptoReviewEntry(
                source_section="capital_gains",
                date=entry.disposal_timestamp or entry.disposal_date,
                asset=entry.asset,
                platform=entry.wallet,
                review_reason=(
                    f"{malformed_prefix}Malformed-input lot (non-positive amount "
                    f"{entry.amount}); investigate the source export"
                ),
                is_suspicious=True,
            )
        )
