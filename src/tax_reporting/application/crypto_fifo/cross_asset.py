"""Cross-asset exchange resolution for deferred FIFO acquisitions.

Builds a topological processing order from cross-asset swap dependencies,
then resolves deferred acquisitions by looking up carry-over costs from
completed FIFO results of the sending asset.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from ._graph import topological_sort_with_fallback
from .contexts import ZERO, AcquisitionContext, ConsumptionContext
from .merge import MergedAssetFifoResult

logger = logging.getLogger(__name__)


def _build_cross_asset_order(
    acquisitions_by_asset: dict[str, list[AcquisitionContext]],
    consumptions_by_asset: dict[str, list[ConsumptionContext]],
) -> tuple[list[str], dict[str, list[str]]]:
    """Derive FIFO processing order from cross-asset swap dependencies."""
    all_assets = sorted(set(acquisitions_by_asset) | set(consumptions_by_asset))

    tx_key_to_sender: dict[str, list[str]] = {}
    for asset, cons in consumptions_by_asset.items():
        for c in cons:
            if not c.con.taxable and c.con.event_type == "exchange_out":
                senders = tx_key_to_sender.setdefault(c.tx_key, [])
                if asset not in senders:
                    senders.append(asset)

    forward_edges: dict[str, set[str]] = {a: set() for a in all_assets}
    for asset, acqs in acquisitions_by_asset.items():
        for acq in acqs:
            if acq.acq.source_type == "exchange_in_deferred":
                for sender in tx_key_to_sender.get(acq.tx_key, []):
                    if sender != asset:
                        forward_edges[sender].add(asset)

    ordered, cyclic = topological_sort_with_fallback(
        nodes=set(all_assets),
        forward_edges=forward_edges,
    )
    if cyclic:
        logger.warning(
            "Cyclic swap dependency detected between %s; deferred acquisitions for the "
            "later-processed asset will be unresolved (review_required=True)",
            cyclic,
        )
    return ordered + cyclic, tx_key_to_sender


def _has_carryover_for_tx_key(carryover: dict[tuple[str, str], Decimal], tx_key: str) -> bool:
    """Return True if the carryover dict contains any entry matching tx_key."""
    return any(key[0] == tx_key for key in carryover)


def _sum_carryover_for_tx_key(carryover: dict[tuple[str, str], Decimal], tx_key: str) -> Decimal:
    """Sum all carryover costs matching tx_key."""
    return sum((cost for key, cost in carryover.items() if key[0] == tx_key), ZERO)


def _lookup_carryover_cost(
    acq: AcquisitionContext,
    fifo_results_by_asset: dict[str, MergedAssetFifoResult],
    tx_key_to_sender: dict[str, list[str]],
) -> tuple[Decimal, bool, str | None]:
    """Look up the carry-over cost for a deferred acquisition."""
    expected_senders = tx_key_to_sender.get(acq.tx_key, [])
    matched_senders = [
        sender
        for sender in expected_senders
        if sender in fifo_results_by_asset
        and _has_carryover_for_tx_key(fifo_results_by_asset[sender].carryover_cost_by_tx_key, acq.tx_key)
    ]
    if not matched_senders:
        return ZERO, False, None

    total = ZERO
    for sender in matched_senders:
        total += _sum_carryover_for_tx_key(fifo_results_by_asset[sender].carryover_cost_by_tx_key, acq.tx_key)

    unprocessed_senders = [sender for sender in expected_senders if sender not in fifo_results_by_asset]
    if unprocessed_senders:
        ambiguity_reason = (
            f"Partial sender match for tx_key={acq.tx_key}: "
            f"matched senders ({', '.join(matched_senders)}) contributed {total} EUR, "
            f"but expected sender(s) ({', '.join(unprocessed_senders)}) were not yet "
            "processed when this acquisition was resolved (likely due to a dependency cycle "
            "in the cross-asset processing order). The reported cost basis may be understated. "
            "Verify that all expected senders' costs are accounted for."
        )
        return total, True, ambiguity_reason
    if len(matched_senders) > 1:
        ambiguity_reason = (
            f"Multiple source assets ({', '.join(matched_senders)}) carry over cost for "
            f"tx_key={acq.tx_key}; costs have been summed ({total} EUR) but this may be "
            "incorrect if these are separate economic operations sharing the same on-chain "
            "transaction hash. Verify that the reported cost basis reflects the true "
            "acquisition cost of this lot."
        )
        return total, True, ambiguity_reason
    return total, True, None


def _apply_receiver_proportional_split(
    acq: AcquisitionContext,
    cost: Decimal,
    tx_key_to_asset_totals: dict[str, dict[str, Decimal]],
    ambiguity_reason: str | None,
) -> tuple[Decimal, str | None]:
    """Apply proportional cost split when multiple deferred receivers share a tx_key."""
    asset_totals = tx_key_to_asset_totals.get(acq.tx_key)
    if not asset_totals:
        return cost, ambiguity_reason

    num_unique_assets = len(asset_totals)
    total_amount_this_asset = asset_totals.get(acq.acq.asset, acq.acq.amount)

    if num_unique_assets == 1:
        if total_amount_this_asset > acq.acq.amount and total_amount_this_asset > ZERO:
            cost = cost * acq.acq.amount / total_amount_this_asset
    else:
        original_cost = cost
        per_asset_cost = cost / Decimal(num_unique_assets)
        if total_amount_this_asset > ZERO:
            cost = per_asset_cost * acq.acq.amount / total_amount_this_asset
        else:
            cost = per_asset_cost
        cross_asset_reason = (
            f"Multiple different assets ({', '.join(sorted(asset_totals))}) share "
            f"tx_key={acq.tx_key}; carry-over cost ({original_cost} EUR) split equally by asset count "
            f"({num_unique_assets}) then proportionally by received amount. "
            "Verify the cost allocation reflects the true acquisition cost of this lot."
        )
        ambiguity_reason = "; ".join(filter(None, [ambiguity_reason, cross_asset_reason]))

    return cost, ambiguity_reason


def _resolve_single_acquisition(
    acq: AcquisitionContext,
    fifo_results_by_asset: dict[str, MergedAssetFifoResult],
    tx_key_to_sender: dict[str, list[str]],
    tx_key_to_asset_totals: dict[str, dict[str, Decimal]],
    flag_counts: dict[str, int] | None = None,
) -> AcquisitionContext:
    """Resolve a single deferred cross-asset acquisition from carry-over costs.

    ``flag_counts`` is an optional shared mutable dict (pattern J) threaded from
    ``_rebuild_fifo_for_loan_affected_assets`` so each per-row WARNING branch below can be
    downgraded to DEBUG (message text unchanged) while incrementing the matching cause key
    (``unresolved`` / ``multi_sender`` / ``zero_carryover`` / ``partial``). The caller emits
    ONE aggregate WARNING from the per-asset loop. ``None`` (default) preserves backward-
    compat with direct callers (e.g. unit tests via the in-test wrapper) that bypass the
    aggregate: those callers see only the DEBUG per-row emission and do not accumulate causes.

    The ``review_required``/``review_reason``/``cost_basis_eur`` assignments in every branch
    are UNCHANGED (Design Invariant #3): the audit signal stays on the data, not the log.
    """
    if acq.acq.source_type != "exchange_in_deferred":
        return acq

    cost, matched, ambiguity_reason = _lookup_carryover_cost(acq, fifo_results_by_asset, tx_key_to_sender)
    if matched:
        cost, ambiguity_reason = _apply_receiver_proportional_split(acq, cost, tx_key_to_asset_totals, ambiguity_reason)

    def _bump(cause_key: str) -> None:
        if flag_counts is not None:
            flag_counts[cause_key] = flag_counts.get(cause_key, 0) + 1

    if not matched:
        # Pattern J: per-row emission downgraded WARNING -> DEBUG (message text unchanged);
        # the audit signal is preserved via review_required/review_reason (Design Invariant
        # #3) plus ONE aggregate WARNING emitted by the per-asset loop driver.
        logger.debug(
            "Unresolved deferred acquisition for %s tx_key=%s: cost remains zero: "
            "the sending asset's FIFO produced no carry-over entry for this tx_key. "
            "Possible causes: tx_key mismatch between the exchange_out consumption and the "
            "exchange_in_deferred acquisition row, or a topological-sort cycle that placed "
            "the receiver before the sender. "
            "Capital gain is permanently overstated by the full original cost basis.",
            acq.acq.asset,
            acq.tx_key,
        )
        _bump("unresolved")
        return acq.with_acq(
            review_required=True,
            review_reason=(
                f"Deferred acquisition (tx_key={acq.tx_key}) could not be resolved: "
                "the sending asset's FIFO produced no carry-over entry for this tx_key. "
                "Possible causes: (a) tx_key mismatch between the EXCHANGE_OUT consumption "
                "and the EXCHANGE_IN row in the Transaction History, or (b) a dependency cycle "
                "in the processing order prevented the sender from being processed first. "
                "Cost basis is ZERO; the reported gain is overstated by the full original "
                "cost of the sent lot. "
                "Find the sending asset's realization for this tx_key and apply its "
                "cost_eur as the cost basis for this lot manually."
            ),
        )

    is_zero_carryover = cost == ZERO
    is_partial_carryover = any(
        acq.tx_key in result.partial_carryover_tx_keys for result in fifo_results_by_asset.values()
    )
    if ambiguity_reason:
        # Pattern J: per-row multi-sender emission WARNING -> DEBUG.
        logger.debug(
            "Multi-sender carry-over for %s tx_key=%s: %s",
            acq.acq.asset,
            acq.tx_key,
            ambiguity_reason,
        )
        _bump("multi_sender")
    needs_review = is_zero_carryover or is_partial_carryover or ambiguity_reason is not None
    if is_zero_carryover:
        # Pattern J: per-row zero-carryover emission WARNING -> DEBUG.
        logger.debug(
            "Resolved carry-over cost for %s tx_key=%s is zero; "
            "likely caused by FIFO pool exhaustion on the sending asset",
            acq.acq.asset,
            acq.tx_key,
        )
        _bump("zero_carryover")
    elif is_partial_carryover:
        # Pattern J: per-row partial-carryover emission WARNING -> DEBUG.
        logger.debug(
            "Resolved carry-over cost for %s tx_key=%s is partial; "
            "FIFO pool was partially exhausted on the sending asset: "
            "cost basis may be understated",
            acq.acq.asset,
            acq.tx_key,
        )
        _bump("partial")
    return acq.with_acq(
        cost_basis_eur=cost,
        source_type="exchange_in_resolved",
        review_required=acq.acq.review_required or needs_review,
        review_reason="; ".join(
            filter(
                None,
                [
                    (
                        f"Carry-over cost resolved to zero for {acq.acq.asset} "
                        f"from tx_key={acq.tx_key}; FIFO pool may have been exhausted "
                        "on the sending asset"
                    )
                    if is_zero_carryover
                    else None,
                    (
                        f"Carry-over cost for {acq.acq.asset} from tx_key={acq.tx_key} "
                        "is understated: FIFO pool was partially exhausted on the sending asset"
                    )
                    if is_partial_carryover and not is_zero_carryover
                    else None,
                    ambiguity_reason,
                    acq.acq.review_reason,
                ],
            )
        )
        or None,
    )


def resolve_cross_asset_exchanges(
    acquisitions_by_asset: dict[str, list[AcquisitionContext]],
    fifo_results_by_asset: dict[str, MergedAssetFifoResult],
    tx_key_to_sender: dict[str, list[str]],
    tx_key_to_asset_totals: dict[str, dict[str, Decimal]],
    flag_counts: dict[str, int] | None = None,
) -> dict[str, list[AcquisitionContext]]:
    """Resolve deferred cross-asset acquisitions from carry-over costs.

    ``flag_counts`` (pattern J) is threaded to ``_resolve_single_acquisition`` so each per-row
    DEBUG branch can increment its cause key. The aggregate WARNING is NOT emitted here (would
    fire once per asset-set); the caller (``_rebuild_fifo_for_loan_affected_assets``'s
    per-asset loop) owns the single aggregate emission.
    """
    return {
        asset: [
            _resolve_single_acquisition(
                acq,
                fifo_results_by_asset,
                tx_key_to_sender,
                tx_key_to_asset_totals,
                flag_counts=flag_counts,
            )
            for acq in acqs
        ]
        for asset, acqs in acquisitions_by_asset.items()
    }
