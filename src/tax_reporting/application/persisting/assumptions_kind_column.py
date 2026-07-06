"""Kind-column wiring for the Assumptions & Methodology tab (Phase A Task 7).

This module wraps the two-tier WalletKind resolver
(``aggregate_platform_evidence`` + ``classify_platform`` from
``tax_reporting.application.crypto.wallet_kind``) so the Assumptions &
Methodology writer can render one ``Kind`` column per platform row and OR the
kind-low-confidence signal into the existing ``platform_review_required`` flag.

Per Phase A Design Invariant 1, this is the ONLY production call site permitted
to consume the new typed ``TransactionHistoryRow`` / ``WalletClassification``
plumbing. The writer remains the production caller; nothing else is wired.

Phase A defers the registry adapter (``operator_origin`` does NOT classify
CEX/DEX today), so callers pass ``registry=None`` and every platform falls
through to tier-2 auto-discovery. Platforms absent from row evidence classify
as UNKNOWN at confidence 0.0 and surface the registry gap via the red Review
Required + reason text per Invariant 12 and the plan's ``## Monitor`` section.
"""

from __future__ import annotations

from collections.abc import Iterable

from tax_reporting.application.crypto.wallet_kind import (
    RegistrySnapshot,
    WalletClassification,
    aggregate_platform_evidence,
    classify_platform,
)
from tax_reporting.domain.transaction import TransactionHistoryRow

__all__ = ["classify_platforms_for_summaries"]


def classify_platforms_for_summaries(
    platforms: Iterable[str],
    th_rows: Iterable[TransactionHistoryRow],
    registry: RegistrySnapshot | None = None,
) -> dict[str, WalletClassification]:
    """Classify every ``platform`` against the two-tier resolver.

    Args:
        platforms: Iterable of platform names discovered in the report (the
            set of platforms the writer must render). Each is classified
            independently; absence from ``th_rows`` evidence yields UNKNOWN
            at confidence 0.0.
        th_rows: Iterable of ``TransactionHistoryRow`` used to build the
            per-platform evidence tallies. Empty iterable is allowed (every
            platform classifies as UNKNOWN).
        registry: Optional ``RegistrySnapshot`` for tier-1 lookup. ``None``
            in Phase A because ``operator_origin`` does not classify CEX/DEX.

    Returns:
        Dict mapping each platform name to its ``WalletClassification``. The
        writer renders ``classification.kind.name`` in the new Kind column
        and ORs ``not classification.is_high_probability()`` into the
        existing ``platform_review_required`` flag.
    """
    evidence_by_platform = aggregate_platform_evidence(th_rows)
    classifications: dict[str, WalletClassification] = {}
    for platform in platforms:
        evidence = evidence_by_platform.get(platform)
        classifications[platform] = classify_platform(platform, evidence, registry)
    return classifications
