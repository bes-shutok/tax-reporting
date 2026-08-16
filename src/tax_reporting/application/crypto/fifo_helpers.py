"""FIFO processing helpers for crypto tax reporting."""

from __future__ import annotations

import logging
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

from ...domain.crypto_fifo import AssetFifoResult, CryptoFifoRealization, TxKey
from ..crypto_fifo import (
    MergedAssetFifoResult,
    compute_fifo_for_asset,
    parse_th_for_loan_affected_assets,
    resolve_cross_asset_exchanges,
)
from ..crypto_fifo.cross_asset import _build_cross_asset_order
from ..crypto_fifo.transfer import _order_platforms_for_transfers, _resolve_intra_asset_transfers
from ..token_origin import TokenOriginResolver
from .chain_derivation import _derive_chain
from .constants import ZERO
from .entities import CryptoCapitalGainEntry, CryptoReviewEntry
from .operator_origin import resolve_operator_origin

_ZERO_COST_REASON: str = (
    "Zero acquisition cost: verify basis (airdrop, data error, or misclassification)"
)
_ZERO_PROCEEDS_REASON: str = (
    "Zero disposal proceeds: verify sale data (transfer error, data quality issue)"
)
_ZERO_COST_NEGATIVE_PROCEEDS_REASON: str = (
    "Zero acquisition cost with negative disposal proceeds: "
    "verify basis and sale data (fee-heavy liquidation or data anomaly)"
)


def _apply_phantom_lot_flags(
    result: AssetFifoResult,
    asset: str,
    platform: str,
    phantom_transfers: frozenset[tuple[str, str, str]],
) -> AssetFifoResult:
    """Flag FIFO realizations on a sending platform that may have consumed phantom lots.

    When a loan-affected asset is transferred cross-platform, the FIFO pool on the
    sending platform retains the lot (the transfer is not tracked as a consumption).
    Any subsequent disposal on that platform consumes an incorrect phantom lot.
    Per CLAUDE.md: partial or uncertain results must carry an explicit indicator.

    Args:
        result: FIFO result for (asset, platform).
        asset: Asset ticker.
        platform: Platform name.
        phantom_transfers: Set of (asset, platform, date) cross-platform transfer markers.

    Returns:
        Updated AssetFifoResult with review_required=True on affected realizations,
        or the original result unchanged if no phantom transfers apply.
    """
    phantom_dates = [date for (a, p, date) in phantom_transfers if a == asset and p == platform]
    if not phantom_dates:
        return result

    earliest_phantom = min(phantom_dates)
    phantom_reason = (
        f"Phantom lot: {asset} was transferred cross-platform on {earliest_phantom}; "
        "this platform's FIFO pool retains the lot after the transfer "
        "(CIRS art. 43 n.9 per-wallet scope limitation). "
        "Cost basis for this realization may be overstated: verify against "
        "the sending wallet's transaction records."
    )
    flagged: list[CryptoFifoRealization] = []
    for r in result.realizations:
        if r.disposal_date >= earliest_phantom:
            if r.review_required and r.review_reason:
                flagged.append(replace(r, review_reason=f"{r.review_reason}; {phantom_reason}"))
            else:
                flagged.append(replace(r, review_required=True, review_reason=phantom_reason))
        else:
            flagged.append(r)
    # Use ``dataclasses.replace`` instead of rebuilding the dataclass field-by-field
    # so future ``AssetFifoResult`` fields (e.g. ``unmatched_taxable_count`` and any
    # later additions) are auto-forwarded instead of silently dropped.
    return replace(result, realizations=flagged)


def _compute_cross_asset_receiver_totals(
    acquisitions_by_asset: dict[str, list],
) -> dict[str, dict[str, Decimal]]:
    """Pre-compute the total deferred-acquisition amount per (tx_key, asset) pair.

    Called once before the per-asset FIFO loop so that cross-asset receivers
    sharing the same tx_key each receive only their proportional share of the
    carry-over cost rather than the full amount.

    Args:
        acquisitions_by_asset: Parsed acquisition contexts keyed by asset ticker.

    Returns:
        Mapping of tx_key → {asset → total_amount} for all exchange_in_deferred rows.
    """
    totals: dict[TxKey, dict[str, Decimal]] = {}
    for asset, acqs in acquisitions_by_asset.items():
        for acq in acqs:
            if acq.acq.source_type == "exchange_in_deferred":
                at = totals.setdefault(acq.tx_key, {})
                at[asset] = at.get(asset, ZERO) + acq.acq.amount
    return totals


def _process_single_asset_fifo(  # noqa: PLR0913
    asset: str,
    acquisitions_by_asset: dict[str, list],
    consumptions_by_asset: dict[str, list],
    fifo_by_asset: dict[str, MergedAssetFifoResult],
    tx_key_to_sender: dict[TxKey, list[str]],
    all_asset_totals: dict[TxKey, dict[str, Decimal]],
    phantom_transfers: dict,
    logger: logging.Logger,
    total_unmatched_taxable: list[int],
    cross_asset_flag_counts: dict[str, int],
    transfer_flag_counts: dict[str, int],
    non_positive_acq_counts: dict[str, int] | None = None,
    negative_consumption_counts: dict[str, int] | None = None,
    epoch_date_counts: dict[str, int] | None = None,
    deferred_consumed_counts: dict[str, int] | None = None,
) -> list[CryptoFifoRealization]:
    """Run FIFO for a single asset across all its platforms and return realizations.

    Resolves deferred cross-asset acquisitions, orders platforms by intra-asset
    transfer dependencies, runs per-platform FIFO, and stores the merged carry-over
    result in ``fifo_by_asset[asset]`` so subsequent assets can consume it.

    Args:
        asset: Asset ticker to process.
        acquisitions_by_asset: All parsed acquisitions keyed by asset.
        consumptions_by_asset: All parsed consumptions keyed by asset.
        fifo_by_asset: Accumulator of per-asset FIFO results; mutated in-place with
            the carry-over result for ``asset``.
        tx_key_to_sender: Maps tx_key → list of sender asset tickers for cross-asset
            carry-over scoping.
        all_asset_totals: Pre-computed receiver totals from
            ``_compute_cross_asset_receiver_totals``; used for proportional cost splits.
        phantom_transfers: Set of (asset, tx_key) pairs flagged as phantom transfers.
        logger: Logger for diagnostics.
        total_unmatched_taxable: Single-cell mutable counter (``[int]``) accumulating
            the number of taxable disposals with no matching acquisition at or before
            the disposal date (pattern F) across all (asset, platform) results. Summed
            by the caller to emit ONE aggregate INFO.
        cross_asset_flag_counts: Shared mutable dict (pattern J) keyed by cross-asset
            deferred-acquisition cause (``unresolved`` / ``multi_sender`` /
            ``zero_carryover`` / ``partial``), threaded into ``resolve_cross_asset_exchanges``
            so each per-row DEBUG branch increments its cause. The caller sums the values
            to emit ONE aggregate INFO after the per-asset loop (HAS_EXCEL_SURFACE:
            per-row sets ``review_required=True`` on a realized entry).
        transfer_flag_counts: Shared mutable dict (pattern K) keyed by transfer carry-over
            cause (``requires_review`` / ``unresolved``), threaded into
            ``_resolve_intra_asset_transfers`` (the per-platform transfer-resolution loop
            below) so each per-row DEBUG branch increments its cause. The caller sums the
            values to emit ONE aggregate INFO after the per-asset loop (HAS_EXCEL_SURFACE:
            per-row sets ``review_required=True`` on a realized entry).
        non_positive_acq_counts: Shared mutable dict (Bucket C) keyed by asset ticker,
            accumulating the count of acquisitions with ``amount <= 0`` skipped during
            FIFO pool construction (``compute_fifo_for_asset`` in ``crypto_fifo/matching.py``,
            the ``Skipping non-positive acquisition`` DEBUG branch) across all (asset,
            platform) results. Populated from ``AssetFifoResult.non_positive_acq_count`` below and
            emitted as ONE aggregate WARNING by the caller. ``None`` is tolerated for
            callers that do not need the count.
        negative_consumption_counts: Shared mutable dict (Bucket C) keyed by asset
            ticker, accumulating the count of negative-amount consumption events
            skipped by the ``remaining < ZERO`` early-return guard in
            ``_consume_against_pool_inplace`` (in ``crypto_fifo/matching.py``) across all
            (asset, platform) results. Populated from
            ``AssetFifoResult.negative_consumption_count`` below and emitted as ONE
            aggregate WARNING by the caller. ``None`` is tolerated for callers that do
            not need the count.
        epoch_date_counts: Shared mutable dict (Bucket B) keyed by asset ticker,
            accumulating the count of taxable realizations whose acquisition and/or
            disposal date carried an epoch sentinel (``_build_taxable_realization`` in
            ``crypto_fifo/matching.py``, the ``is_epoch_acq`` / ``is_epoch_con`` branches)
            across all (asset, platform) results. Populated from
            ``AssetFifoResult.epoch_date_count`` below and emitted as ONE aggregate
            INFO by the caller. ``None`` is tolerated for callers that do not need
            the count.
        deferred_consumed_counts: Shared mutable dict (Bucket B) keyed by asset
            ticker, accumulating the count of taxable realizations that consumed an
            UNRESOLVED deferred acquisition (``_build_taxable_realization`` in
            ``crypto_fifo/matching.py``, the ``is_deferred_acq`` branch --
            realization-time consequence, distinct from Pattern J's resolution-time cause)
            across all (asset, platform) results. Populated from
            ``AssetFifoResult.deferred_consumed_count`` below and emitted as ONE
            aggregate INFO by the caller. ``None`` is tolerated for callers that do
            not need the count.

    Returns:
        All realizations produced for this asset across all platforms.
    """
    raw_acqs = acquisitions_by_asset.get(asset, [])
    resolved = resolve_cross_asset_exchanges(
        {asset: raw_acqs},
        fifo_by_asset,
        tx_key_to_sender=tx_key_to_sender,
        tx_key_to_asset_totals=all_asset_totals,
        flag_counts=cross_asset_flag_counts,
    )
    acqs = resolved.get(asset, raw_acqs)

    cons = consumptions_by_asset.get(asset, [])
    platforms = {a.acq.platform for a in acqs} | {c.con.platform for c in cons}
    merged_carryover: dict[tuple[TxKey, str], Decimal] = {}
    merged_partial_tx_keys: set[TxKey] = set()

    per_platform_carryover: dict[str, dict[TxKey, Decimal]] = {}
    per_platform_partial_map: dict[str, frozenset[TxKey]] = {}

    platform_order = _order_platforms_for_transfers(acqs, cons)
    ordered = list(platform_order)
    for p in sorted(platforms):
        if p not in set(ordered):
            ordered.append(p)

    asset_realizations: list[CryptoFifoRealization] = []
    for platform in ordered:
        if platform not in platforms:
            continue
        p_acqs = [a for a in acqs if a.acq.platform == platform]
        p_cons = [c for c in cons if c.con.platform == platform]
        p_acqs = _resolve_intra_asset_transfers(
            p_acqs, per_platform_carryover, per_platform_partial_map, flag_counts=transfer_flag_counts
        )
        if p_acqs or p_cons:
            result = compute_fifo_for_asset(p_acqs, p_cons, asset, platform)
            result = _apply_phantom_lot_flags(result, asset, platform, phantom_transfers)
            asset_realizations.extend(result.realizations)
            per_platform_carryover[platform] = dict(result.carryover_cost_by_tx_key)
            per_platform_partial_map[platform] = result.partial_carryover_tx_keys
            total_unmatched_taxable[0] += result.unmatched_taxable_count
            # Bucket C: accumulate non-positive-acquisition skips per asset
            # (AssetFifoResult.non_positive_acq_count) into the shared per-asset
            # dict, emitted as ONE aggregate WARNING after the per-asset loop.
            if non_positive_acq_counts is not None and result.non_positive_acq_count:
                non_positive_acq_counts[asset] = (
                    non_positive_acq_counts.get(asset, 0) + result.non_positive_acq_count
                )
            # Bucket C: accumulate negative-consumption skips per asset
            # (AssetFifoResult.negative_consumption_count) into the shared per-asset
            # dict, emitted as ONE aggregate WARNING after the per-asset loop.
            if negative_consumption_counts is not None and result.negative_consumption_count:
                negative_consumption_counts[asset] = (
                    negative_consumption_counts.get(asset, 0) + result.negative_consumption_count
                )
            # Bucket B (epoch dates): accumulate epoch-sentinel-date realization counts
            # (AssetFifoResult.epoch_date_count) into the shared per-asset dict, emitted
            # as ONE aggregate INFO after the per-asset loop.
            if epoch_date_counts is not None and result.epoch_date_count:
                epoch_date_counts[asset] = (
                    epoch_date_counts.get(asset, 0) + result.epoch_date_count
                )
            # Bucket B (deferred-acquisition consumed): accumulate counts of realizations
            # that consumed an UNRESOLVED deferred acquisition
            # (AssetFifoResult.deferred_consumed_count) into the shared per-asset dict,
            # emitted as ONE aggregate INFO with wording DISTINCT from Pattern J.
            if deferred_consumed_counts is not None and result.deferred_consumed_count:
                deferred_consumed_counts[asset] = (
                    deferred_consumed_counts.get(asset, 0) + result.deferred_consumed_count
                )
            for key, cost in result.carryover_cost_by_tx_key.items():
                platform_key = (key, platform)
                if platform_key in merged_carryover:
                    logger.info(
                        "%s carry-over key %r for platform %r already present; costs summed",
                        asset,
                        key,
                        platform,
                    )
                merged_carryover[platform_key] = merged_carryover.get(platform_key, ZERO) + cost
            merged_partial_tx_keys.update(result.partial_carryover_tx_keys)

    fifo_by_asset[asset] = MergedAssetFifoResult(
        carryover_cost_by_tx_key=merged_carryover,
        partial_carryover_tx_keys=frozenset(merged_partial_tx_keys),
    )
    return asset_realizations


def _emit_flagged_summary(
    counts: dict[str, int],
    noun: str,
    logger: logging.Logger,
    *,
    level: int = logging.WARNING,
) -> None:
    """Emit ONE aggregate log record summarizing a dict-counter of flagged causes.

    Shared emitter for patterns J (cross-asset deferred-acquisition) and K (transfer
    carry-over): each per-row WARNING branch in ``_resolve_single_acquisition`` /
    ``_resolve_intra_asset_transfers`` was downgraded to DEBUG and increments its cause
    key in a threaded mutable dict. This collapses the N per-row emissions into ONE
    record (at ``level``, default WARNING) naming the total count and a per-cause
    breakdown (sorted by cause key), pointing reviewers at the DEBUG log and the Crypto
    Gains review column for the actionable per-row detail (Design Invariants #3, #5).
    The J and K call sites pass ``level=logging.INFO`` (Bucket B: the Excel review cell
    is the canonical audit surface, so the console aggregate is a nicety at INFO).

    Pattern F (``total_unmatched_taxable``) is a single-cell ``list[int]`` with a
    different message shape and stays inline at its emission site -- NOT routed here.

    Args:
        counts: Shared mutable dict ``{cause_key: count}``. No-op when empty.
        noun: Aggregated noun phrase used in the message (e.g. ``"cross-asset deferred
            acquisition(s)"``); interpolated as ``"<total> <noun> flagged (<breakdown>)"``.
        logger: Logger to emit the WARNING on (the ``fifo_helpers`` module logger owns
            the post-loop emission per Design Invariant #4).
        level: Logging level for the aggregate emission. Defaults to ``WARNING``;
            callers whose flagged rows are already surfaced in the Crypto Gains review
            column (Patterns J/K) pass ``logging.INFO`` so the console is not noisy.
    """
    if not counts:
        return
    total = sum(counts.values())
    logger.log(
        level,
        "%d %s flagged (%s); see DEBUG log and Crypto Gains review column for per-row detail",
        total,
        noun,
        ", ".join(f"{k}: {v}" for k, v in sorted(counts.items())),
    )


def _rebuild_fifo_for_loan_affected_assets(  # noqa: PLR0912, PLR0913, PLR0915
    transaction_history_file: Path,
    origin_resolver: TokenOriginResolver,
    loan_affected_assets: frozenset[str],
    *,
    fiscal_year: int | None = None,
    zero_basis_review_min_proceeds: Decimal = ZERO,
    review_entries: list[CryptoReviewEntry] | None = None,
) -> tuple[list[CryptoCapitalGainEntry], frozenset[str]]:
    """Rebuild FIFO for loan-affected assets from Transaction History.

    Processes assets with cross-asset carry-over resolution, ordered
    by swap dependencies, per (asset, platform) pair.

    Only realizations whose disposal date falls in ``fiscal_year`` are converted
    to ``CryptoCapitalGainEntry`` objects.  Acquisitions from prior years are
    still allowed into the FIFO pool so that cost-basis carry-over is correct;
    only the final reporting step is gated.

    Args:
        transaction_history_file: Path to the Koinly Transaction History CSV.
        origin_resolver: Token origin resolver for annotating gain entries.
        loan_affected_assets: Set of asset tickers to rebuild via FIFO.
        fiscal_year: If provided, only include realizations from this tax year in
            the output. Pass ``None`` to include all years (useful in testing).
        zero_basis_review_min_proceeds: Minimum proceeds (EUR) required to flag a
            zero-cost entry for review. Defaults to ZERO (preserve prior behavior).
        review_entries: Optional threaded Crypto Supplementary review list forwarded
            to ``parse_th_for_loan_affected_assets`` so ``_dedup_by_tx_key`` can
            append one ``CryptoReviewEntry`` per dropped duplicate-tx_key row (Plan
            2026-07-25 Task 3 / W2). ``None`` (the default) preserves existing test
            callers that omit the param (INV-3 backward compat).

    Returns:
        Tuple of (fifo_entries, th_assets) where th_assets is the set of
        loan-affected asset tickers that appeared in the Transaction History.
    """
    # Bucket B (empty Sent Cost Basis): single-cell mutable counter threaded down through
    # the parsing path (parse_th_for_loan_affected_assets -> _classify_th_row ->
    # _classify_exchange_row -> _handle_exchange -> _emit_received_only_exchange) where
    # each per-row DEBUG branch increments it. Emitted as ONE aggregate INFO below so the
    # console shows a single summary while per-row detail stays at DEBUG (Invariant #7).
    # Pattern-F count-only shape: NOT routed through _emit_flagged_summary (that helper
    # is reserved for the J/K cause-breakdown dict aggregates).
    empty_cost_basis_counter: list[int] = [0]
    acquisitions_by_asset, consumptions_by_asset, phantom_transfers, parse_failures = parse_th_for_loan_affected_assets(
        transaction_history_file,
        loan_affected_assets=loan_affected_assets,
        empty_cost_basis_counter=empty_cost_basis_counter,
        review_entries=review_entries,
    )

    # th_assets tracks only assets with taxable consumption events:
    # - Acquisition-only assets (never disposed this year) legitimately produce zero FIFO realizations.
    # - Assets with only non-taxable consumptions (e.g. all disposals were crypto-to-crypto swaps
    #   under PT art. 10(20)) also legitimately produce zero taxable realizations.
    # Only assets with at least one taxable consumption should trigger the "gains missing" warning.
    th_assets = frozenset(
        asset for asset, cons in consumptions_by_asset.items()
        if any(c.con.taxable for c in cons)
    )

    if not acquisitions_by_asset and not consumptions_by_asset:
        return [], th_assets

    logger = logging.getLogger(__name__)
    # Bucket B aggregate INFO (empty Sent Cost Basis): per-row emissions in
    # ``_emit_received_only_exchange`` (``_emitters.py``) were demoted to DEBUG; this
    # single summary preserves an INFO-level console signal without N per-row WARNING
    # lines. The acquisition's ``review_required``/``review_reason`` are UNCHANGED
    # (Invariant #3); the Excel review cell is the canonical audit surface.
    if empty_cost_basis_counter[0] > 0:
        logger.info(
            "%d exchange(s) with empty Sent Cost Basis; kept zero cost and flagged for review; "
            "see DEBUG log for per-row detail",
            empty_cost_basis_counter[0],
        )
    all_realizations: list[CryptoFifoRealization] = []
    fifo_by_asset: dict[str, MergedAssetFifoResult] = {}

    # Derive processing order from cross-asset swap dependencies.
    # Assets that send in cross-asset swaps are processed before receiving assets
    # so their carry-over cost basis is available when deferred acquisitions are resolved.
    # tx_key_to_sender scopes carryover lookups to the correct source asset, preventing
    # ambiguity when multiple loan-affected assets share the same on-chain tx_hash.
    processing_order, tx_key_to_sender = _build_cross_asset_order(
        acquisitions_by_asset, consumptions_by_asset
    )

    # Pre-compute receiver totals across ALL assets before the per-asset loop.
    # Without the full cross-asset totals, each per-asset call would see only itself
    # (num_unique_assets == 1) and incorrectly claim the full carry-over cost,
    # duplicating cost basis when two receiver assets share the same tx_key.
    all_asset_totals = _compute_cross_asset_receiver_totals(acquisitions_by_asset)

    # Pattern F: single-cell mutable counter accumulating the number of taxable
    # disposals with no matching acquisition at or before the disposal date across
    # all (asset, platform) results. Emitted as ONE aggregate INFO after the
    # per-asset loop so the console shows a single summary while per-row detail
    # stays at DEBUG (Design Invariant #3) and the review_reason field carries the
    # actionable per-row context (Design Invariant #4).
    total_unmatched_taxable: list[int] = [0]
    # Pattern J: shared mutable dict accumulating cross-asset deferred-acquisition
    # causes (unresolved / multi_sender / zero_carryover / partial) across all assets.
    # Threaded into ``_process_single_asset_fifo`` -> ``resolve_cross_asset_exchanges``
    # -> ``_resolve_single_acquisition``, where each per-row WARNING branch was
    # downgraded to DEBUG (message text unchanged) and increments its cause key. Emitted
    # as ONE aggregate INFO after the per-asset loop (Design Invariant #5: per-cause
    # breakdown preserved). ``review_required``/``review_reason`` on each resolved
    # acquisition are the UNCHANGED audit signal (Design Invariant #3); the per-row
    # entry's rendered "YES:" cell is the canonical audit surface (rule #7
    # HAS_EXCEL_SURFACE), so the aggregate demotes to INFO.
    cross_asset_flag_counts: dict[str, int] = {}
    # Pattern K: shared mutable dict accumulating transfer carry-over causes
    # (requires_review / unresolved) across all (asset, platform) transfer resolutions.
    # Threaded into ``_process_single_asset_fifo`` (per-platform loop) ->
    # ``_resolve_intra_asset_transfers``, where each per-row WARNING branch was
    # downgraded to DEBUG (message text unchanged) and increments its cause key. Emitted
    # as ONE aggregate INFO after the per-asset loop (same HAS_EXCEL_SURFACE rule as
    # Pattern J: the per-row "YES:" cell is the audit surface). ``review_required`` /
    # ``review_reason`` / ``cost_basis_eur`` on each resolved acquisition are the
    # UNCHANGED audit signal (Design Invariant #3).
    transfer_flag_counts: dict[str, int] = {}
    # Bucket C (non-positive acquisition): shared mutable dict keyed by asset ticker
    # accumulating the count of acquisitions with amount <= 0 skipped during FIFO pool
    # construction (compute_fifo_for_asset in crypto_fifo/matching.py, the ``Skipping
    # non-positive acquisition`` DEBUG branch) across all (asset, platform) results.
    # Populated from AssetFifoResult.non_positive_acq_count via _process_single_asset_fifo
    # and emitted as ONE aggregate WARNING after the per-asset loop. STAYS WARNING
    # (silent data loss, no Excel surface). Per-row detail is at DEBUG in matching.py.
    non_positive_acq_counts: dict[str, int] = {}
    # Bucket C (negative consumption): shared mutable dict keyed by asset ticker
    # accumulating the count of negative-amount consumption events skipped by the
    # ``remaining < ZERO`` early-return guard in ``_consume_against_pool_inplace``
    # (crypto_fifo/matching.py) across all (asset, platform) results. Populated from
    # AssetFifoResult.negative_consumption_count via _process_single_asset_fifo and emitted
    # as ONE aggregate WARNING after the per-asset loop. STAYS WARNING (silent data loss,
    # no Excel surface). Per-row detail is at DEBUG in matching.py.
    negative_consumption_counts: dict[str, int] = {}
    # Bucket B (epoch dates): shared mutable dict keyed by asset ticker accumulating
    # the count of taxable realizations whose acquisition and/or disposal date carried
    # an epoch sentinel (``_build_taxable_realization`` in crypto_fifo/matching.py, the
    # ``is_epoch_acq`` / ``is_epoch_con`` branches) across all (asset, platform) results.
    # Populated from AssetFifoResult.epoch_date_count via _process_single_asset_fifo
    # and emitted as ONE aggregate INFO after the per-asset loop. The realization's
    # review_required (set via ``or is_epoch_acq``/``or is_epoch_con``) is the
    # canonical Excel audit surface; the aggregate INFO is a console nicety.
    epoch_date_counts: dict[str, int] = {}
    # Bucket B (deferred-acquisition consumed): shared mutable dict keyed by asset
    # ticker accumulating the count of taxable realizations that consumed an UNRESOLVED
    # deferred acquisition (``_build_taxable_realization`` in crypto_fifo/matching.py,
    # the ``is_deferred_acq`` branch) across all (asset, platform) results. Populated
    # from AssetFifoResult.deferred_consumed_count via _process_single_asset_fifo and
    # emitted as ONE aggregate INFO after the per-asset loop with wording DISTINCT from
    # Pattern J (Invariant #2: realization-time consequence vs resolution-time cause).
    deferred_consumed_counts: dict[str, int] = {}

    for asset in processing_order:
        all_realizations.extend(
            _process_single_asset_fifo(
                asset,
                acquisitions_by_asset,
                consumptions_by_asset,
                fifo_by_asset,
                tx_key_to_sender,
                all_asset_totals,
                phantom_transfers,
                logger,
                total_unmatched_taxable=total_unmatched_taxable,
                cross_asset_flag_counts=cross_asset_flag_counts,
                transfer_flag_counts=transfer_flag_counts,
                non_positive_acq_counts=non_positive_acq_counts,
                negative_consumption_counts=negative_consumption_counts,
                epoch_date_counts=epoch_date_counts,
                deferred_consumed_counts=deferred_consumed_counts,
            )
        )

    # Pattern F aggregate INFO: emitted BEFORE the fiscal_year filter.
    # ``total_unmatched_taxable[0]`` counts every unmatched-taxable disposal seen
    # during FIFO computation across ALL processed years (not just ``fiscal_year``).
    # The fiscal_year filter below then drops out-of-year realizations from
    # ``all_realizations`` (the report list), but this INFO honestly reports the
    # FIFO-computation total across all processed years. The accumulator is
    # structurally correct -- it is incremented only inside ``matching.py``'s
    # actual unmatched-taxable branches (via ``unmatched_taxable_counter``), so it
    # does NOT count matched disposals whose acquisition carries a partial-transfer
    # "pool exhausted" review_reason (that reason would be a substring-collision
    # false positive if the count were re-derived from review_reason text).
    if total_unmatched_taxable[0] > 0:
        logger.info(
            "%d taxable disposal(s) had no acquisition at or before the disposal date "
            "(pool exhausted) across all processed years; flagged for review with zero "
            "cost basis; see DEBUG log and realization review_reason for details",
            total_unmatched_taxable[0],
        )

    # Bucket C aggregate WARNING (non-positive acquisition): per-row emissions in
    # ``compute_fifo_for_asset`` (the ``Skipping non-positive acquisition`` DEBUG branch)
    # were downgraded to DEBUG; this single summary preserves the WARNING-level audit
    # signal with a per-asset breakdown so the console is not flooded. STAYS WARNING
    # (silent data loss, no Excel surface). The acquisition is still dropped from the
    # FIFO pool (the ``continue`` is unchanged).
    if non_positive_acq_counts:
        total_skipped = sum(non_positive_acq_counts.values())
        logger.warning(
            "Skipped %d non-positive acquisition(s) (%s); see DEBUG log for per-row detail",
            total_skipped,
            ", ".join(f"{a}: {n}" for a, n in sorted(non_positive_acq_counts.items())),
        )

    # Bucket C aggregate WARNING (negative consumption): per-row emissions in
    # ``_consume_against_pool_inplace`` (the ``remaining < ZERO`` early-return guard)
    # were downgraded to DEBUG; this single summary preserves the WARNING-level audit
    # signal with a per-asset breakdown so the console is not flooded. STAYS WARNING
    # (silent data loss, no Excel surface). The consumption is still dropped
    # (the early ``return`` is unchanged).
    if negative_consumption_counts:
        total_neg = sum(negative_consumption_counts.values())
        logger.warning(
            "Skipped %d negative-consumption event(s) (%s); see DEBUG log for per-row detail",
            total_neg,
            ", ".join(f"{a}: {n}" for a, n in sorted(negative_consumption_counts.items())),
        )

    # Bucket B aggregate INFO (epoch dates): per-row emissions in
    # ``_build_taxable_realization`` (the ``is_epoch_acq`` / ``is_epoch_con`` branches)
    # were downgraded to DEBUG; this single summary preserves an INFO-level console
    # signal without N per-row WARNING lines. The realization's ``review_required`` (set
    # via ``or is_epoch_acq``/``or is_epoch_con``) is the canonical Excel audit surface
    # (Invariant #3); this INFO is a console nicety reachable at LOG_LEVEL=INFO.
    if epoch_date_counts:
        total_epoch = sum(epoch_date_counts.values())
        logger.info(
            "%d realization(s) with epoch-sentinel dates (%s); see DEBUG log for per-row detail",
            total_epoch,
            ", ".join(f"{a}: {n}" for a, n in sorted(epoch_date_counts.items())),
        )

    # Bucket B aggregate INFO (deferred-acquisition consumed): per-row emission at
    # ``_build_taxable_realization`` (the ``is_deferred_acq`` branch) was downgraded to
    # DEBUG; this single summary preserves the INFO-level console signal. The wording is
    # DISTINCT from Pattern J's "cross-asset deferred acquisition(s) flagged" (Invariant #2:
    # this names the realization-time consequence -- a deferred lot consumed with zero
    # cost basis -- while Pattern J names resolution-time causes at acquisition time).
    if deferred_consumed_counts:
        total_def = sum(deferred_consumed_counts.values())
        logger.info(
            "%d realization(s) consumed an unresolved deferred-acquisition lot "
            "(cost basis zero; gain overstated) (%s); see DEBUG log for per-row detail",
            total_def,
            ", ".join(f"{a}: {n}" for a, n in sorted(deferred_consumed_counts.items())),
        )

    # Pattern J aggregate INFO (Bucket B): cross-asset deferred-acquisition per-row
    # emissions were downgraded to DEBUG in ``_resolve_single_acquisition``; this single
    # summary preserves the audit signal at INFO with a per-cause breakdown (Design
    # Invariant #5). Each resolved acquisition still carries
    # ``review_required``/``review_reason`` (Design Invariant #3, unchanged), which is the
    # actionable per-row surface (the Crypto Gains review column).
    _emit_flagged_summary(
        cross_asset_flag_counts, "cross-asset deferred acquisition(s)", logger, level=logging.INFO
    )

    # Pattern K aggregate INFO (Bucket B): transfer carry-over per-row emissions were
    # downgraded to DEBUG in ``_resolve_intra_asset_transfers``; this single summary
    # preserves the audit signal at INFO with a per-cause breakdown (requires_review /
    # unresolved). Each resolved acquisition still carries
    # ``review_required``/``review_reason`` (Design Invariant #3, unchanged), which is the
    # actionable per-row surface.
    _emit_flagged_summary(
        transfer_flag_counts, "transfer carry-over acquisition(s)", logger, level=logging.INFO
    )

    # Flag realizations for assets with TH parse errors.
    if parse_failures:
        updated: list[CryptoFifoRealization] = []
        for r in all_realizations:
            failed_rows = parse_failures.get(r.asset)
            if failed_rows:
                rows_str = ", ".join(str(i) for i in sorted(failed_rows))
                parse_error_reason = (
                    f"TH parse error on row(s) {rows_str}: FIFO pool for {r.asset} "
                    "may be incomplete: verify all acquisitions/disposals are present"
                )
                updated.append(replace(
                    r,
                    review_required=True,
                    review_reason="; ".join(filter(None, [r.review_reason, parse_error_reason])),
                ))
            else:
                updated.append(r)
        all_realizations = updated

    # Step 4: Filter to fiscal year (disposal-date gate only; acquisitions from prior years
    # must remain in the FIFO pool above so cost-basis carry-over is correct).
    if fiscal_year is not None:
        fiscal_year_prefix = str(fiscal_year)
        excluded_count = sum(
            1 for r in all_realizations if not r.disposal_date.startswith(fiscal_year_prefix)
        )
        if excluded_count:
            logger.warning(
                "FIFO rebuild: excluding %d realization(s) with disposal dates outside fiscal year %d "
                "(these belong to a different tax year and must not appear in this report)",
                excluded_count,
                fiscal_year,
            )
        all_realizations = [r for r in all_realizations if r.disposal_date.startswith(fiscal_year_prefix)]

    # Step 5: Convert realizations to CryptoCapitalGainEntry
    fifo_entries: list[CryptoCapitalGainEntry] = []
    try:
        for r in all_realizations:
            operator_origin = resolve_operator_origin(
                r.platform, transaction_type="crypto_disposal", transaction_date=r.disposal_date,
            )
            annex_hint = "G1" if r.holding_period.lower().startswith("long") else "J"
            chain = _derive_chain(r.wallet)
            origin = origin_resolver.resolve(r.acquisition_date, r.asset, r.wallet, r.notes or "")
            combined_review_required = r.review_required or operator_origin.review_required
            combined_review_reason = (
                "; ".join(filter(None, [r.review_reason, operator_origin.review_reason])) or None
            )
            # Defensive guard: review_required=True must always have a reason.
            # This should be guaranteed by upstream __post_init__ validators, but guard explicitly
            # to prevent a silent ValueError if any upstream invariant is bypassed (e.g. via replace()).
            if combined_review_required and not combined_review_reason:
                combined_review_reason = "Review required (reason not propagated from FIFO or origin resolver)"

            combined_review_required, combined_review_reason = _build_zero_basis_review_reason(
                r.cost_eur, r.proceeds_eur, combined_review_required, combined_review_reason or "",
                min_proceeds=zero_basis_review_min_proceeds,
            )

            fifo_entries.append(
                CryptoCapitalGainEntry(
                    disposal_date=r.disposal_date,
                    acquisition_date=r.acquisition_date,
                    asset=r.asset,
                    amount=r.amount,
                    cost_eur=r.cost_eur,
                    proceeds_eur=r.proceeds_eur,
                    gain_loss_eur=r.gain_loss_eur,
                    holding_period=r.holding_period,
                    wallet=r.wallet,
                    platform=r.platform,
                    chain=chain,
                    operator_origin=operator_origin,
                    annex_hint=annex_hint,
                    review_required=combined_review_required,
                    notes=r.notes or "",
                    review_reason=combined_review_reason,
                    token_swap_history=str(origin),
                    multi_acquisition_dates=False,
                    disposal_timestamp=r.disposal_timestamp,
                )
            )
    finally:
        # Pattern B flush: emit ONE aggregate INFO for any token_origin
        # disagreements accumulated during this FIFO-rebuild pass, then clear the
        # shared resolver Counter. The CG-parse flush already ran upstream inside
        # ``_parse_capital_gains_file`` (call site ordering: ``crypto_reporting.py:337``
        # runs before this function at ``:361`` per Design Invariant #10), so
        # this flush sees only FIFO-rebuild-stage disagreements.
        #
        # MUST run in a ``finally`` (r2 review F6): ``origin_resolver.resolve(...)``
        # accumulates disagreements inside the loop, and ``CryptoCapitalGainEntry``'s
        # ``__post_init__`` validators can raise ``ValueError`` mid-loop. Without the
        # finally, an exception propagates before the flush, silently dropping the
        # FIFO-rebuild-stage aggregate INFO and leaving the shared Counter with
        # unflushed state (Design Invariant #10's named load-bearing condition).
        # The flush is also needed on the success path, which ``finally`` guarantees.
        origin_resolver.log_and_reset_disagreements(scope="FIFO rebuild")

    return fifo_entries, th_assets


def _build_zero_basis_review_reason(
    cost_eur: Decimal,
    proceeds_eur: Decimal,
    review_required: bool,
    review_reason: str,
    min_proceeds: Decimal = ZERO,
) -> tuple[bool, str]:
    """Build review reason for zero-cost or zero-proceeds entries.

    Applies the zero-basis materiality rule (four flagging branches plus the
    small-reward suppression between them):

    - cost=0 AND proceeds=0: not flagged when ``min_proceeds > 0`` (FEE token noise);
      flagged with both zero-cost and zero-proceeds reasons when ``min_proceeds == 0``
      (legacy flag-everything escape hatch).
    - cost=0 AND 0 < proceeds < min_proceeds (small reward): no flag.
    - cost=0 AND proceeds >= min_proceeds: flag with zero-cost reason.
    - cost=0 AND proceeds < 0: always flag with the negative-proceeds reason
      (fee-heavy liquidation or data anomaly; independent of ``min_proceeds``).
    - cost>0 AND proceeds=0: flag with zero-proceeds reason (legitimate data-quality concern).

    Args:
        cost_eur: Acquisition cost in EUR.
        proceeds_eur: Disposal proceeds in EUR.
        review_required: Current review_required flag value.
        review_reason: Current review_reason text.
        min_proceeds: Minimum proceeds (EUR) required to flag a zero-cost entry.
            Defaults to ZERO (preserve prior behavior; flag every zero-cost entry).

    Returns:
        Tuple of (updated_review_required, updated_review_reason) with zero-basis
        flags added if applicable.
    """
    if cost_eur == ZERO and proceeds_eur > ZERO and proceeds_eur >= min_proceeds:
        review_required = True
        review_reason = (
            f"{review_reason}; {_ZERO_COST_REASON}" if review_reason else _ZERO_COST_REASON
        )

    if proceeds_eur == ZERO and cost_eur > ZERO:
        review_required = True
        review_reason = (
            f"{review_reason}; {_ZERO_PROCEEDS_REASON}" if review_reason else _ZERO_PROCEEDS_REASON
        )

    if cost_eur == ZERO and proceeds_eur == ZERO and min_proceeds == ZERO:
        review_required = True
        parts = [_ZERO_COST_REASON, _ZERO_PROCEEDS_REASON]
        review_reason = f"{review_reason}; " + "; ".join(parts) if review_reason else "; ".join(parts)

    if cost_eur == ZERO and proceeds_eur < ZERO:
        review_required = True
        review_reason = (
            f"{review_reason}; {_ZERO_COST_NEGATIVE_PROCEEDS_REASON}"
            if review_reason
            else _ZERO_COST_NEGATIVE_PROCEEDS_REASON
        )

    return review_required, review_reason
