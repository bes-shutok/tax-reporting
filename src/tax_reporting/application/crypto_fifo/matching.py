"""FIFO matching engine for a single (asset, platform) pair.

Computes capital gains realizations by consuming acquisition lots in FIFO order.
"""

from __future__ import annotations

import logging
from collections import deque
from datetime import datetime
from decimal import Decimal

from ...domain.crypto_fifo import AssetFifoResult, CryptoFifoRealization, TxKey
from .contexts import ZERO, AcquisitionContext, ConsumptionContext

logger = logging.getLogger(__name__)


def compute_fifo_for_asset(
    acquisitions: list[AcquisitionContext],
    consumptions: list[ConsumptionContext],
    asset: str,
    platform: str,
) -> AssetFifoResult:
    """Run FIFO matching for a single (asset, platform) pair.

    Per-wallet scope per CIRS art. 43 n.9. The caller must pre-filter to one
    (asset, platform) pair; this function validates that invariant.

    Args:
        acquisitions: Acquisition lots (sorted by date, then source_row_index).
        consumptions: Consumption events (sorted by date, then source_row_index).
        asset: Asset ticker (for validation and output).
        platform: Platform name (for validation and output).

    Returns:
        AssetFifoResult with realizations and carry-over cost map.
    """
    for acq in acquisitions:
        if acq.acq.asset != asset or acq.acq.platform != platform:
            raise ValueError(
                f"Acquisition mismatch: expected ({asset}, {platform}), "
                f"got ({acq.acq.asset}, {acq.acq.platform})"
            )
    for con in consumptions:
        if con.con.asset != asset or con.con.platform != platform:
            raise ValueError(
                f"Consumption mismatch: expected ({asset}, {platform}), "
                f"got ({con.con.asset}, {con.con.platform})"
            )

    sorted_acqs = sorted(acquisitions, key=lambda a: (a.acq.date, a.source_row_index))
    sorted_cons = sorted(consumptions, key=lambda c: (c.con.date, c.source_row_index))

    pool: deque[tuple[AcquisitionContext, Decimal]] = deque()
    # Bucket C (silent data loss, no Excel surface): count of acquisitions with
    # amount <= 0 skipped during pool construction. Per-row emission is DEBUG;
    # the count is returned on AssetFifoResult.non_positive_acq_count and summed
    # by _rebuild_fifo_for_loan_affected_assets into ONE aggregate WARNING (Invariant #7).
    non_positive_acq_count = 0
    for a in sorted_acqs:
        if a.acq.amount <= ZERO:
            logger.debug(
                "Skipping non-positive acquisition for %s at %s (amount=%s, source row %d)",
                asset,
                a.acq.date,
                a.acq.amount,
                a.source_row_index,
            )
            non_positive_acq_count += 1
            continue
        pool.append((a, a.acq.amount))
    realizations: list[CryptoFifoRealization] = []
    carryover_cost_by_tx_key: dict[TxKey, Decimal] = {}
    partial_tx_keys: set[TxKey] = set()
    # Single-cell mutable counter accumulated across consumption events; the value
    # is the number of taxable disposals that had no matching acquisition at or
    # before the disposal date (pattern F). Threaded into ``_consume_against_pool_inplace``
    # alongside the other mutable accumulators (``carryover_cost_by_tx_key``, ``partial_tx_keys``).
    unmatched_taxable_counter: list[int] = [0]
    # Single-cell mutable counter for negative-amount consumption events skipped by
    # the ``remaining < ZERO`` early-return guard (Bucket C). Threaded alongside
    # ``unmatched_taxable_counter``; summed onto ``AssetFifoResult.negative_consumption_count``.
    negative_consumption_counter: list[int] = [0]
    # Single-cell mutable counters for Bucket-B realization-time annotations emitted
    # by ``_build_taxable_realization`` (the leaf with no ``AssetFifoResult`` handle).
    # Threaded through ``_consume_against_pool_inplace`` alongside the existing
    # mutable accumulators and summed onto ``AssetFifoResult.epoch_date_count`` /
    # ``AssetFifoResult.deferred_consumed_count`` for ONE aggregate INFO emission by
    # ``_rebuild_fifo_for_loan_affected_assets`` (Invariant #7 r2 F1: leaf-threading).
    epoch_counter: list[int] = [0]
    deferred_consumed_counter: list[int] = [0]

    for con in sorted_cons:
        realizations.extend(
            _consume_against_pool_inplace(
                con,
                pool,
                asset,
                platform,
                carryover_cost_by_tx_key,
                partial_tx_keys,
                unmatched_taxable_counter,
                negative_consumption_counter,
                epoch_counter,
                deferred_consumed_counter,
            )
        )

    if partial_tx_keys:
        logger.info(
            "FIFO pool exhausted for %d non-taxable %s consumption(s) on %s; "
            "carry-over cost understated; see DEBUG log for per-row detail",
            len(partial_tx_keys),
            asset,
            platform,
        )

    return AssetFifoResult(
        realizations=realizations,
        carryover_cost_by_tx_key=carryover_cost_by_tx_key,
        partial_carryover_tx_keys=frozenset(partial_tx_keys),
        unmatched_taxable_count=unmatched_taxable_counter[0],
        non_positive_acq_count=non_positive_acq_count,
        negative_consumption_count=negative_consumption_counter[0],
        epoch_date_count=epoch_counter[0],
        deferred_consumed_count=deferred_consumed_counter[0],
    )


def _build_taxable_realization(  # noqa: PLR0913
    acq: AcquisitionContext,
    con: ConsumptionContext,
    consumed: Decimal,
    proportional_cost: Decimal,
    proportional_acq_fee: Decimal,
    proportional_proceeds: Decimal,
    asset: str,
    platform: str,
    epoch_counter: list[int] | None = None,
    deferred_consumed_counter: list[int] | None = None,
) -> CryptoFifoRealization:
    """Build a CryptoFifoRealization for a single taxable lot match.

    Handles epoch-sentinel date detection, holding-period calculation, and deferred
    acquisition annotation. Called from _consume_against_pool_inplace for each lot
    consumed by a taxable disposal.

    Args:
        acq: The acquisition lot being consumed.
        con: The consumption event driving this realization.
        consumed: The amount consumed from this lot.
        proportional_cost: Proportional cost basis for the consumed amount.
        proportional_acq_fee: Proportional acquisition fee for the consumed amount.
        proportional_proceeds: Proportional disposal proceeds for the consumed amount.
        asset: Asset ticker (for logging and realization fields).
        platform: Platform name for the realization.
        epoch_counter: Optional single-cell mutable accumulator (``[int]``) incremented
            once per realization with an epoch-sentinel acquisition and/or disposal date
            (Bucket B). Threaded up to ``compute_fifo_for_asset`` -> ``AssetFifoResult``
            so the top-level caller emits ONE aggregate INFO. ``None`` tolerated for
            direct callers that do not need the count.
        deferred_consumed_counter: Optional single-cell mutable accumulator (``[int]``)
            incremented once per realization consuming an UNRESOLVED deferred
            acquisition (Bucket B; realization-time consequence, distinct from Pattern
            J's resolution-time cause). Threaded alongside ``epoch_counter``.

    Returns:
        A fully-constructed CryptoFifoRealization for this taxable lot match.
    """
    logger = logging.getLogger(__name__)
    is_epoch_acq = not acq.acq.date or acq.acq.date.startswith("1970-")
    is_epoch_con = not con.con.date or con.con.date.startswith("1970-")
    is_deferred_acq = acq.acq.source_type == "exchange_in_deferred"
    if is_epoch_acq:
        logger.debug(
            "Empty or epoch acquisition date for %s at source_row_index=%d; "
            "holding period unknown, defaulting to Short term",
            asset,
            acq.source_row_index,
        )
    if is_epoch_con:
        logger.debug(
            "Empty or epoch disposal date for %s at source_row_index=%d; "
            "holding period unknown, defaulting to Short term",
            asset,
            con.source_row_index,
        )
    # Bucket B (epoch dates): count ONE per realization whose acquisition and/or
    # disposal date carries an epoch sentinel, to match the aggregate wording
    # "N realization(s) with epoch-sentinel dates". ``None`` is tolerated for direct
    # callers that do not surface the count.
    if (is_epoch_acq or is_epoch_con) and epoch_counter is not None:
        epoch_counter[0] += 1
    holding_period = (
        "Short term" if is_epoch_acq or is_epoch_con else _compute_holding_period(acq.acq.date, con.con.date)
    )
    epoch_parts = []
    if is_epoch_acq:
        epoch_parts.append(
            f"Epoch sentinel acquisition date for {asset}; "
            "missing Date field in TH row: holding period unknown, Short term"
        )
    if is_epoch_con:
        epoch_parts.append(
            f"Epoch sentinel disposal date for {asset} at row {con.source_row_index}; "
            "missing Date field in TH row: holding period unknown, Short term"
        )
    epoch_reason: str | None = "; ".join(epoch_parts) or None
    deferred_reason: str | None = (
        f"Deferred acquisition for {asset} (tx_key={acq.tx_key}): "
        "cross-asset carry-over cost cannot be resolved in the current single-pass FIFO engine: "
        "the sending asset's FIFO runs after this asset's, so the cost basis "
        "is permanently ZERO in the automated report (this is not a transient state; "
        "re-running will not fix it). "
        "The reported capital gain is overstated by the full original cost basis. "
        "To correct: find the sending-asset's FIFO realization for tx_key above, "
        "read its cost_eur, and apply that as the cost basis for this lot manually."
        if is_deferred_acq
        else None
    )
    if is_deferred_acq:
        logger.debug(
            "FIFO: %s disposal on %s uses unresolved deferred acquisition (tx_key=%s); "
            "cost basis is zero: capital gain is overstated. "
            "Review required: %s",
            asset,
            con.con.date,
            acq.tx_key,
            deferred_reason,
        )
        # Bucket B (deferred-acquisition consumed): count ONE per realization that
        # consumed an UNRESOLVED deferred acquisition (realization-time consequence,
        # distinct from Pattern J's resolution-time cause). ``None`` tolerated.
        if deferred_consumed_counter is not None:
            deferred_consumed_counter[0] += 1
    return CryptoFifoRealization(
        disposal_date=con.con.date,
        acquisition_date=acq.acq.date,
        asset=asset,
        amount=consumed,
        cost_eur=proportional_cost + proportional_acq_fee,
        proceeds_eur=proportional_proceeds,
        gain_loss_eur=(
            proportional_proceeds - proportional_cost - proportional_acq_fee
        ),
        holding_period=holding_period,
        wallet=con.con.wallet,
        platform=platform,
        notes=con.con.notes,
        review_required=(
            con.con.review_required
            or acq.acq.review_required
            or is_epoch_acq
            or is_epoch_con
            or is_deferred_acq
        ),
        review_reason="; ".join(
            filter(None, [epoch_reason, deferred_reason, con.con.review_reason, acq.acq.review_reason])
        )
        or None,
        disposal_timestamp=con.con.disposal_timestamp,
    )


def _consume_against_pool_inplace(  # noqa: PLR0912, PLR0913, PLR0915
    con: ConsumptionContext,
    pool: deque[tuple[AcquisitionContext, Decimal]],
    asset: str,
    platform: str,
    carryover_cost_by_tx_key: dict[TxKey, Decimal],
    partial_tx_keys: set[TxKey],
    unmatched_taxable_counter: list[int] | None = None,
    negative_consumption_counter: list[int] | None = None,
    epoch_counter: list[int] | None = None,
    deferred_consumed_counter: list[int] | None = None,
) -> list[CryptoFifoRealization]:
    """Consume a single disposal event against the FIFO pool, mutating pool and accumulators.

    Mutates ``pool`` (lots consumed in FIFO order), ``carryover_cost_by_tx_key`` (records
    deferred cost for non-taxable events), ``partial_tx_keys`` (marks transactions
    with incomplete carryover), ``unmatched_taxable_counter`` (increments by one for
    each taxable disposal that had no matching acquisition at or before the disposal date,
    pattern F), and ``negative_consumption_counter`` (increments by one for each
    negative-amount consumption skipped by the early-return guard, Bucket C). Taxable
    lot matches are delegated to ``_build_taxable_realization``, which also receives
    ``epoch_counter`` and ``deferred_consumed_counter`` (Bucket B: epoch-sentinel dates
    and unresolved-deferred-acquisition consumption) so their counts thread up to
    ``compute_fifo_for_asset`` -> ``AssetFifoResult`` for ONE aggregate INFO emission.

    ``unmatched_taxable_counter``, ``negative_consumption_counter``, ``epoch_counter``,
    and ``deferred_consumed_counter`` are single-cell mutable lists (``[int]``)
    following the existing mutable-accumulator convention (``carryover_cost_by_tx_key``,
    ``partial_tx_keys``); ``None`` is tolerated for direct callers that do not need
    the counts.

    Returns the realizations generated for this consumption event.
    """
    realizations: list[CryptoFifoRealization] = []
    remaining = con.con.amount
    con_proceeds = con.con.proceeds_eur

    if remaining == ZERO:
        return realizations

    if remaining < ZERO:
        # Bucket C (silent data loss, no Excel surface): per-row emission demoted to
        # DEBUG; the count is threaded via negative_consumption_counter up to
        # _rebuild_fifo_for_loan_affected_assets (summed onto
        # AssetFifoResult.negative_consumption_count) and emitted as ONE aggregate
        # WARNING there. The consumption is still dropped (early return unchanged).
        logger.debug(
            "Negative consumption amount %.8f for %s at %s (source_row_index=%d); skipping",
            remaining,
            con.con.asset,
            con.con.date,
            con.source_row_index,
        )
        if negative_consumption_counter is not None:
            negative_consumption_counter[0] += 1
        return realizations

    while remaining > ZERO and pool:
        acq, lot_remaining = pool[0]
        if (acq.acq.date, acq.source_row_index) > (con.con.date, con.source_row_index):
            break
        consumed = min(remaining, lot_remaining)
        proportional_cost = acq.acq.cost_basis_eur * consumed / acq.acq.amount
        proportional_acq_fee = acq.acq.fee_eur * consumed / acq.acq.amount
        proportional_proceeds = con_proceeds * consumed / con.con.amount if con.con.amount > ZERO else ZERO

        if con.con.taxable:
            realizations.append(
                _build_taxable_realization(
                    acq, con, consumed, proportional_cost, proportional_acq_fee, proportional_proceeds, asset, platform,
                    epoch_counter=epoch_counter,
                    deferred_consumed_counter=deferred_consumed_counter,
                )
            )
        else:
            existing = carryover_cost_by_tx_key.get(con.tx_key, ZERO)
            carryover_cost_by_tx_key[con.tx_key] = (
                existing + proportional_cost + proportional_acq_fee
            )

        new_lot_remaining = lot_remaining - consumed
        if new_lot_remaining > ZERO:
            pool[0] = (acq, new_lot_remaining)
        else:
            pool.popleft()
        remaining -= consumed

    if remaining > ZERO:
        proportional_proceeds = con.con.proceeds_eur * remaining / con.con.amount if con.con.amount > ZERO else ZERO
        if con.con.taxable:
            pool_truly_exhausted = not pool
            if pool_truly_exhausted:
                # Pattern F (pool-exhausted sub-branch): per-row emission is DEBUG;
                # the audit signal is preserved via the placeholder realization's
                # review_reason + ONE aggregate INFO emitted by
                # _rebuild_fifo_for_loan_affected_assets (sums unmatched_taxable_count).
                logger.debug(
                    "FIFO pool exhausted for %s on %s: %.8f units with no matching acquisition",
                    asset,
                    con.con.date,
                    remaining,
                )
                review_reason = (
                    f"FIFO pool exhausted: {remaining.normalize()} {asset} disposed with zero cost basis"
                )
            else:
                earliest_future = pool[0][0].acq.date
                # Pattern F (no-acquisition-at-date sub-branch): per-row emission is DEBUG.
                logger.debug(
                    "No acquisition available at or before disposal date for %s on %s: "
                    "%.8f units unmatched; earliest available lot is after the disposal date",
                    asset,
                    con.con.date,
                    remaining,
                )
                review_reason = (
                    f"No acquisition available at or before disposal date {con.con.date}: "
                    f"{remaining.normalize()} {asset} unmatched; "
                    f"earliest available lot is {earliest_future}"
                )
            if unmatched_taxable_counter is not None:
                unmatched_taxable_counter[0] += 1
            realizations.append(
                CryptoFifoRealization(
                    disposal_date=con.con.date,
                    acquisition_date="",
                    asset=asset,
                    amount=remaining,
                    cost_eur=ZERO,
                    proceeds_eur=proportional_proceeds,
                    gain_loss_eur=proportional_proceeds,
                    holding_period="Short term",
                    wallet=con.con.wallet,
                    platform=platform,
                    notes=con.con.notes,
                    review_required=True,
                    review_reason=review_reason,
                    disposal_timestamp=con.con.disposal_timestamp,
                )
            )
        else:
            logger.debug(
                "FIFO pool exhausted for non-taxable %s consumption on %s: "
                "%.8f units unmatched; carry-over cost will be understated",
                asset,
                con.con.date,
                remaining,
            )
            if con.tx_key not in carryover_cost_by_tx_key:
                carryover_cost_by_tx_key[con.tx_key] = ZERO
            partial_tx_keys.add(con.tx_key)

    return realizations


def _compute_holding_period(acquisition_date: str, disposal_date: str) -> str:
    """Compute holding period label from acquisition and disposal date strings.

    Uses calendar-year arithmetic (not day count) to avoid misclassifying
    the leap-year boundary: e.g. acquired 2023-03-01, sold 2024-02-29 is
    365 days but the 1-year anniversary (2024-03-01) has not yet passed,
    so it is Short term.
    """
    acq_dt = datetime.fromisoformat(acquisition_date)
    disp_dt = datetime.fromisoformat(disposal_date)
    acq_date = acq_dt.date()
    disp_date = disp_dt.date()
    try:
        one_year_anniversary = acq_date.replace(year=acq_date.year + 1)
    except ValueError:
        # Feb 29 in a leap year → anniversary is Mar 1 (conservative: not long-term until Mar 1)
        one_year_anniversary = acq_date.replace(year=acq_date.year + 1, month=3, day=1)
    return "Long term" if disp_date >= one_year_anniversary else "Short term"
