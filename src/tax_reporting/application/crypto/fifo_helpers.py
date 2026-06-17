"""FIFO processing helpers for crypto tax reporting."""

from __future__ import annotations

import logging
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Final

from ...domain.crypto_fifo import AssetFifoResult, CryptoFifoRealization
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
from .entities import CryptoCapitalGainEntry
from .operator_origin import resolve_operator_origin


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
        "Cost basis for this realization may be overstated — verify against "
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
    return AssetFifoResult(
        realizations=flagged,
        carryover_cost_by_tx_key=result.carryover_cost_by_tx_key,
        partial_carryover_tx_keys=result.partial_carryover_tx_keys,
    )


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
    totals: dict[str, dict[str, Decimal]] = {}
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
    tx_key_to_sender: dict[str, list[str]],
    all_asset_totals: dict[str, dict[str, Decimal]],
    phantom_transfers: dict,
    logger: logging.Logger,
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

    Returns:
        All realizations produced for this asset across all platforms.
    """
    raw_acqs = acquisitions_by_asset.get(asset, [])
    resolved = resolve_cross_asset_exchanges(
        {asset: raw_acqs},
        fifo_by_asset,
        tx_key_to_sender=tx_key_to_sender,
        tx_key_to_asset_totals=all_asset_totals,
    )
    acqs = resolved.get(asset, raw_acqs)

    cons = consumptions_by_asset.get(asset, [])
    platforms = {a.acq.platform for a in acqs} | {c.con.platform for c in cons}
    merged_carryover: dict[tuple[str, str], Decimal] = {}
    merged_partial_tx_keys: set[str] = set()

    per_platform_carryover: dict[str, dict[str, Decimal]] = {}
    per_platform_partial_map: dict[str, frozenset[str]] = {}

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
        p_acqs = _resolve_intra_asset_transfers(p_acqs, per_platform_carryover, per_platform_partial_map)
        if p_acqs or p_cons:
            result = compute_fifo_for_asset(p_acqs, p_cons, asset, platform)
            result = _apply_phantom_lot_flags(result, asset, platform, phantom_transfers)
            asset_realizations.extend(result.realizations)
            per_platform_carryover[platform] = dict(result.carryover_cost_by_tx_key)
            per_platform_partial_map[platform] = result.partial_carryover_tx_keys
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


def _rebuild_fifo_for_loan_affected_assets(
    transaction_history_file: Path,
    origin_resolver: TokenOriginResolver,
    loan_affected_assets: frozenset[str],
    *,
    fiscal_year: int | None = None,
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

    Returns:
        Tuple of (fifo_entries, th_assets) where th_assets is the set of
        loan-affected asset tickers that appeared in the Transaction History.
    """
    acquisitions_by_asset, consumptions_by_asset, phantom_transfers, parse_failures = parse_th_for_loan_affected_assets(
        transaction_history_file,
        loan_affected_assets=loan_affected_assets,
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
    # (num_unique_assets == 1) and incorrectly claim the full carry-over cost —
    # duplicating cost basis when two receiver assets share the same tx_key.
    all_asset_totals = _compute_cross_asset_receiver_totals(acquisitions_by_asset)

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
            )
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
                    "may be incomplete — verify all acquisitions/disposals are present"
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
            r.cost_eur, r.proceeds_eur, combined_review_required, combined_review_reason or ""
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

    return fifo_entries, th_assets


def _build_zero_basis_review_reason(
    cost_eur: Decimal,
    proceeds_eur: Decimal,
    review_required: bool,
    review_reason: str,
) -> tuple[bool, str]:
    """Build review reason for zero-cost or zero-proceeds entries.

    Args:
        cost_eur: Acquisition cost in EUR.
        proceeds_eur: Disposal proceeds in EUR.
        review_required: Current review_required flag value.
        review_reason: Current review_reason text.

    Returns:
        Tuple of (updated_review_required, updated_review_reason) with zero-basis
        flags added if applicable.
    """
    if cost_eur == ZERO:
        review_required = True
        zero_cost_reason = "Zero acquisition cost - verify basis (airdrop, data error, or misclassification)"
        review_reason = f"{review_reason}; {zero_cost_reason}" if review_reason else zero_cost_reason

    if proceeds_eur == ZERO:
        review_required = True
        zero_proceeds_reason = "Zero disposal proceeds - verify sale data (transfer error, data quality issue)"
        review_reason = f"{review_reason}; {zero_proceeds_reason}" if review_reason else zero_proceeds_reason

    return review_required, review_reason
