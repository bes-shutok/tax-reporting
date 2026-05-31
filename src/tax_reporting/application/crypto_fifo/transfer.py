"""Intra-asset transfer resolution for the crypto FIFO engine."""

from __future__ import annotations

import logging
from decimal import Decimal

from ._graph import topological_sort_with_fallback
from .contexts import ZERO, AcquisitionContext, ConsumptionContext

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

    tx_key_to_sender: dict[str, str] = {}
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
        logger.warning(
            "Cyclic transfer dependency detected between platforms %s; "
            "falling back to alphabetical order",
            cyclic,
        )
    return ordered + cyclic


def _resolve_intra_asset_transfers(  # noqa: PLR0912
    platform_acquisitions: list[AcquisitionContext],
    per_platform_carryover: dict[str, dict[str, Decimal]],
    per_platform_partial: dict[str, frozenset[str]] | None = None,
) -> list[AcquisitionContext]:
    """Resolve transfer_in_deferred acquisitions using sender-platform FIFO carry-over costs."""
    result: list[AcquisitionContext] = []
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
                    f"({sender_names}); costs have been summed ({resolved_cost}) — verify manually "
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
                logger.warning(
                    "Transfer carry-over for %s tx_key=%s requires review — %s",
                    acq.acq.asset,
                    acq.tx_key,
                    review_reason,
                )
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
            logger.warning(
                "Could not resolve transfer_in_deferred for %s tx_key=%s — "
                "sender platform carry-over not found; flagging for review.",
                acq.acq.asset,
                acq.tx_key,
            )
            result.append(
                acq.with_acq(
                    cost_basis_eur=ZERO,
                    source_type="transfer_in_deferred",
                    review_required=True,
                    review_reason=review_reason,
                )
            )

    return result
