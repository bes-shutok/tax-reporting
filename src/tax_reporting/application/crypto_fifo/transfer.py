"""Intra-asset transfer resolution for the crypto FIFO engine."""

from __future__ import annotations

import logging
from decimal import Decimal

from ._graph import topological_sort_with_fallback
from .contexts import ZERO, AcquisitionContext, ConsumptionContext, TxKey

logger = logging.getLogger(__name__)


def _order_platforms_for_transfers(
    acquisitions: list[AcquisitionContext],
    consumptions: list[ConsumptionContext],
) -> list[str]:
    """Return platforms in topological order based on transfer_out → transfer_in_deferred dependencies."""
    all_platforms: set[str] = set()
    for acq in acquisitions:
        if acq.acq.platform:
            all_platforms.add(acq.acq.platform)
    for con in consumptions:
        if con.con.platform:
            all_platforms.add(con.con.platform)

    if not all_platforms:
        return []

    tx_key_to_sender: dict[TxKey, str] = {}
    for con in consumptions:
        if con.con.event_type == "transfer_out" and con.tx_key:
            tx_key_to_sender[con.tx_key] = con.con.platform

    forward_edges: dict[str, set[str]] = {p: set() for p in all_platforms}
    for acq in acquisitions:
        if acq.acq.source_type == "transfer_in_deferred" and acq.tx_key:
            sender = tx_key_to_sender.get(acq.tx_key)
            receiver = acq.acq.platform
            if sender and receiver and sender != receiver and receiver not in forward_edges.get(sender, set()):
                forward_edges[sender].add(receiver)

    ordered, cyclic = topological_sort_with_fallback(
        nodes=all_platforms,
        forward_edges=forward_edges,
    )
    if cyclic:
        logger.info(
            "Cyclic transfer dependency detected between platforms %s; "
            "falling back to alphabetical order",
            cyclic,
        )
    return ordered + cyclic


def _resolve_intra_asset_transfers(  # noqa: PLR0912
    platform_acquisitions: list[AcquisitionContext],
    per_platform_carryover: dict[str, dict[TxKey, Decimal]],
    per_platform_partial: dict[str, frozenset[TxKey]] | None = None,
    flag_counts: dict[str, int] | None = None,
) -> list[AcquisitionContext]:
    """Resolve transfer_in_deferred acquisitions using sender-platform FIFO carry-over costs.

    Args:
        platform_acquisitions: Per-platform acquisition contexts for the current asset.
        per_platform_carryover: Sender-platform FIFO carry-over costs keyed by tx_key.
        per_platform_partial: Per-platform sets of tx_keys whose carry-over was partial.
        flag_counts: Pattern K shared mutable dict keyed by transfer carry-over cause
            (``requires_review`` / ``unresolved``). When provided, each per-row WARNING
            branch (downgraded to DEBUG) increments its cause key so the caller emits ONE
            aggregate INFO after the per-asset / per-platform loop. ``None`` keeps the
            per-row DEBUG emission without counting (backward-compat for direct callers).
            The ``review_required``/``review_reason``/``cost_basis_eur`` assignments are
            UNCHANGED in every branch (Design Invariant #3).
    """
    result: list[AcquisitionContext] = []

    def _bump(cause_key: str) -> None:
        """Increment ``flag_counts[cause_key]`` (pattern K) when threaded; no-op when ``None``.

        Mirrors the ``_bump`` closure in ``cross_asset._resolve_single_acquisition`` (pattern
        J) so the two sibling files share the same guard shape at every per-row branch.
        """
        if flag_counts is not None:
            flag_counts[cause_key] = flag_counts.get(cause_key, 0) + 1

    for acq in platform_acquisitions:
        if acq.acq.source_type != "transfer_in_deferred":
            result.append(acq)
            continue

        resolved_cost: Decimal | None = None
        is_partial = False
        matching_senders: list[tuple[str, Decimal]] = []
        for sender_platform, carryover_dict in per_platform_carryover.items():
            if acq.tx_key in carryover_dict:
                matching_senders.append((sender_platform, carryover_dict[acq.tx_key]))
                if per_platform_partial and acq.tx_key in per_platform_partial.get(sender_platform, frozenset()):
                    is_partial = True

        if matching_senders:
            resolved_cost = sum(cost for _, cost in matching_senders)
        ambiguous = len(matching_senders) > 1

        if resolved_cost is not None:
            review_required = resolved_cost == ZERO or is_partial or ambiguous
            if ambiguous:
                sender_names = ", ".join(p for p, _ in matching_senders)
                review_reason = (
                    f"tx_key={acq.tx_key} matched {len(matching_senders)} sender platforms "
                    f"({sender_names}); costs have been summed ({resolved_cost}): verify manually "
                    "that these represent a single economic transfer and not separate operations"
                )
            elif resolved_cost == ZERO:
                review_reason = (
                    f"Transfer carry-over cost resolved to zero for {acq.acq.asset} "
                    f"from tx_key={acq.tx_key}; FIFO pool may have been exhausted on sender platform."
                )
            elif is_partial:
                review_reason = (
                    f"Transfer carry-over for {acq.acq.asset} tx_key={acq.tx_key} was partially matched "
                    f"on the sender platform (FIFO pool exhausted mid-transfer); "
                    f"receiver cost basis may be understated."
                )
            else:
                review_reason = None
            if review_required:
                # Pattern K: per-row emission downgraded to DEBUG (message text unchanged).
                # When ``flag_counts`` is threaded, increment ``requires_review`` so the
                # caller emits ONE aggregate INFO; the audit signal stays on the
                # ``review_required``/``review_reason`` fields (Design Invariant #3).
                logger.debug(
                    "Transfer carry-over for %s tx_key=%s requires review: %s",
                    acq.acq.asset,
                    acq.tx_key,
                    review_reason,
                )
                _bump("requires_review")
            result.append(
                acq.with_acq(
                    cost_basis_eur=resolved_cost,
                    source_type="transfer_in_resolved",
                    review_required=review_required,
                    review_reason=review_reason if review_required else None,
                )
            )
        else:
            review_reason = (
                f"transfer_in_deferred (tx_key={acq.tx_key}) could not be resolved: "
                f"sender platform FIFO carry-over not available."
            )
            # Pattern K: per-row emission downgraded to DEBUG (message text unchanged).
            # When ``flag_counts`` is threaded, increment ``unresolved`` so the caller
            # emits ONE aggregate INFO; the audit signal stays on the
            # ``review_required=True``/``review_reason`` fields (Design Invariant #3).
            logger.debug(
                "Could not resolve transfer_in_deferred for %s tx_key=%s: "
                "sender platform carry-over not found; flagging for review.",
                acq.acq.asset,
                acq.tx_key,
            )
            _bump("unresolved")
            result.append(
                acq.with_acq(
                    cost_basis_eur=ZERO,
                    source_type="transfer_in_deferred",
                    review_required=True,
                    review_reason=review_reason,
                )
            )

    return result
