"""FIFO matching engine for a single (asset, platform) pair.

Computes capital gains realizations by consuming acquisition lots in FIFO order.
"""

from __future__ import annotations

import logging
from collections import deque
from datetime import datetime
from decimal import Decimal

from ...domain.crypto_fifo import AssetFifoResult, CryptoFifoRealization
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
    for a in sorted_acqs:
        if a.acq.amount <= ZERO:
            logger.warning(
                "Skipping non-positive acquisition for %s at %s (amount=%s, source row %d)",
                asset,
                a.acq.date,
                a.acq.amount,
                a.source_row_index,
            )
            continue
        pool.append((a, a.acq.amount))
    realizations: list[CryptoFifoRealization] = []
    carryover_cost_by_tx_key: dict[str, Decimal] = {}
    partial_tx_keys: set[str] = set()

    for con in sorted_cons:
        realizations.extend(
            _consume_against_pool_inplace(con, pool, asset, platform, carryover_cost_by_tx_key, partial_tx_keys)
        )

    return AssetFifoResult(
        realizations=realizations,
        carryover_cost_by_tx_key=carryover_cost_by_tx_key,
        partial_carryover_tx_keys=frozenset(partial_tx_keys),
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

    Returns:
        A fully-constructed CryptoFifoRealization for this taxable lot match.
    """
    logger = logging.getLogger(__name__)
    is_epoch_acq = not acq.acq.date or acq.acq.date.startswith("1970-")
    is_epoch_con = not con.con.date or con.con.date.startswith("1970-")
    is_deferred_acq = acq.acq.source_type == "exchange_in_deferred"
    if is_epoch_acq:
        logger.warning(
            "Empty or epoch acquisition date for %s at source_row_index=%d; "
            "holding period unknown, defaulting to Short term",
            asset,
            acq.source_row_index,
        )
    if is_epoch_con:
        logger.warning(
            "Empty or epoch disposal date for %s at source_row_index=%d; "
            "holding period unknown, defaulting to Short term",
            asset,
            con.source_row_index,
        )
    holding_period = (
        "Short term" if is_epoch_acq or is_epoch_con else _compute_holding_period(acq.acq.date, con.con.date)
    )
    epoch_parts = []
    if is_epoch_acq:
        epoch_parts.append(
            f"Epoch sentinel acquisition date for {asset}; "
            "missing Date field in TH row — holding period unknown, Short term"
        )
    if is_epoch_con:
        epoch_parts.append(
            f"Epoch sentinel disposal date for {asset} at row {con.source_row_index}; "
            "missing Date field in TH row — holding period unknown, Short term"
        )
    epoch_reason: str | None = "; ".join(epoch_parts) or None
    deferred_reason: str | None = (
        f"Deferred acquisition for {asset} (tx_key={acq.tx_key}): "
        "cross-asset carry-over cost cannot be resolved in the current single-pass FIFO engine — "
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
        logger.warning(
            "FIFO: %s disposal on %s uses unresolved deferred acquisition (tx_key=%s); "
            "cost basis is zero — capital gain is overstated. "
            "Review required: %s",
            asset,
            con.con.date,
            acq.tx_key,
            deferred_reason,
        )
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
    )


def _consume_against_pool_inplace(  # noqa: PLR0912, PLR0913, PLR0915
    con: ConsumptionContext,
    pool: deque[tuple[AcquisitionContext, Decimal]],
    asset: str,
    platform: str,
    carryover_cost_by_tx_key: dict[str, Decimal],
    partial_tx_keys: set[str],
) -> list[CryptoFifoRealization]:
    """Consume a single disposal event against the FIFO pool, mutating pool and accumulators.

    Mutates ``pool`` (lots consumed in FIFO order), ``carryover_cost_by_tx_key`` (records
    deferred cost for non-taxable events), and ``partial_tx_keys`` (marks transactions
    with incomplete carryover). Taxable lot matches are delegated to
    ``_build_taxable_realization``.

    Returns the realizations generated for this consumption event.
    """
    realizations: list[CryptoFifoRealization] = []
    remaining = con.con.amount
    con_proceeds = con.con.proceeds_eur

    if remaining == ZERO:
        return realizations

    if remaining < ZERO:
        logger.warning(
            "Negative consumption amount %.8f for %s at %s (source_row_index=%d); skipping",
            remaining,
            con.con.asset,
            con.con.date,
            con.source_row_index,
        )
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
                    acq, con, consumed, proportional_cost, proportional_acq_fee, proportional_proceeds, asset, platform
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
                fifo_warning = (
                    "FIFO pool exhausted for %s on %s: %.8f units with no matching acquisition"
                )
                review_reason = (
                    f"FIFO pool exhausted: {remaining.normalize()} {asset} disposed with zero cost basis"
                )
            else:
                earliest_future = pool[0][0].acq.date
                fifo_warning = (
                    "No acquisition available at or before disposal date for %s on %s: "
                    "%.8f units unmatched; earliest available lot is after the disposal date"
                )
                review_reason = (
                    f"No acquisition available at or before disposal date {con.con.date}: "
                    f"{remaining.normalize()} {asset} unmatched; "
                    f"earliest available lot is {earliest_future}"
                )
            logger.warning(fifo_warning, asset, con.con.date, remaining)
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
                )
            )
        else:
            logger.warning(
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
