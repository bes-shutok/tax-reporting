"""Event-level OGR gain/loss application for crypto capital gains.

Phase 1 of the OGR over-count fix (see
``docs/history/plans/2026-07-04-ogr-event-level-application.md``).

The legacy per-lot ``_apply_ogr_direction_override`` wrote the FULL OGR
event value to EVERY CG lot of an agree-branch disposal event, so
aggregating the N lots produced ``N x ogr_event_gain``. This module
applies OGR authority at the disposal-EVENT level instead:

- **Agree branch** (CG and OGR same sign): the full ``ogr_event_gain``
  is written to the FIRST lot of the event (in input order); the
  remaining lots get zero. ``sum(gain_loss_eur) == ogr_event_gain``
  byte-exactly because aggregation sums ``gain_loss_eur``.
- **Conflict branch** (opposite signs): UNCHANGED from legacy - each
  lot keeps ``±abs(lot.gain_loss_eur)`` with the OGR sign. The lots sum
  to ``±sum(abs(lot.gain_loss_eur))``, which equals
  ``±abs(cg_event_gain)`` ONLY when every lot shares the event's CG
  sign; a mixed-sign event sums absolute magnitudes (matching the
  legacy per-lot write, which is unchanged here).

Single-lot events (both branches) reduce exactly to the legacy output.

Per-lot ``OgrValidationResult`` contract (Design Invariant 3):

- ``ogr_gain_loss == ogr_event_gain`` (FULL event value on EVERY lot,
  because ``_aggregate_ogr_validation`` reads it from the first lot at
  ``aggregation.py:217-218`` and must see the full value).
- ``calculated_gain_loss == lot's PRE-distribution CG gain`` so
  aggregation's sum reconstructs ``cg_event_gain`` and the re-derived
  direction/magnitude is correct.
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from dataclasses import replace
from decimal import Decimal
from typing import Final

from ...domain.entities import OgrValidationResult
from ...infrastructure.config import TaxJurisdictionConfig
from ...infrastructure.koinly_parser import (
    normalize_asset_ticker,
    normalize_platform_name,
)
from .entities import CryptoCapitalGainEntry
from .ogr_handler import _OGR_MAGNITUDE_DIFF_THRESHOLD

# Absolute threshold (EUR) above which an OGR-vs-CG magnitude or direction
# difference is material enough to flag for review. Reused from the legacy
# per-lot override so the event-level gate matches the prior noise filter.
# NOTE (single source of truth): the post-aggregation event-level review gate
# in ``aggregation.py`` (``_aggregate_ogr_validation``) inlines this same
# ``Decimal("1")`` floor at its own call sites. ``aggregation.py`` is FROZEN
# for Phase 1 (out of scope), so the two cannot yet share one constant; a
# future calibration MUST update both. This per-lot flag is advisory only -
# aggregation re-derives the authoritative flag from event totals - so any
# transient drift is surfaced (not silently applied) downstream.
_OGR_ABSOLUTE_DIFF_THRESHOLD: Final = Decimal("1")

logger = logging.getLogger(__name__)


def apply_ogr_event_level(
    capital_entries: list[CryptoCapitalGainEntry],
    spot_index: dict[tuple[str, str, str], Decimal],
    jurisdiction: TaxJurisdictionConfig,
) -> list[CryptoCapitalGainEntry]:
    """Apply OGR gain/loss authority at the disposal-event level.

    Groups CG lots into events by ``(date, asset, wallet)`` (the same key
    the OGR ``spot_index`` uses), decides direction/magnitude ONCE on event
    totals, and writes the result so aggregation reconstructs the
    byte-exact event total. Same signature as the legacy
    ``_apply_ogr_direction_override`` so it is a drop-in replacement at the
    call site (``crypto_reporting.py``).

    Args:
        capital_entries: Pre-aggregation CG lots (one CG row = one FIFO lot).
        spot_index: Summed OGR index keyed by ``(date, asset, wallet)``
            produced by ``_split_ogr_index`` (or ``_build_ogr_index`` on
            the backward-compat path). Not threaded with raw OGR rows.
        jurisdiction: Tax jurisdiction config. When
            ``use_other_gains_report`` is ``False``, entries are returned
            unchanged.

    Returns:
        Lots in original input order with ``len(out) == len(in)``. Each
        OGR-matched lot carries an ``ogr_validation`` per the contract
        above; unmatched lots pass through with ``ogr_validation=None``.
    """
    if not jurisdiction.use_other_gains_report:
        return capital_entries

    # Group lots into events by (date, asset, wallet), preserving first-seen
    # order so the first lot of each event is stable in input order.
    events: OrderedDict[tuple[str, str, str], list[int]] = OrderedDict()
    for i, entry in enumerate(capital_entries):
        key = (
            entry.disposal_date,
            normalize_asset_ticker(entry.asset),
            normalize_platform_name(entry.wallet),
        )
        events.setdefault(key, []).append(i)

    # Build the result by applying each event's decision to its lots, then
    # reassemble in original input order.
    indexed_result: dict[int, CryptoCapitalGainEntry] = {}
    for key, indices in events.items():
        ogr_event_gain = spot_index.get(key)
        if ogr_event_gain is None:
            # No OGR match - lots pass through unchanged (ogr_validation stays None).
            for i in indices:
                indexed_result[i] = capital_entries[i]
            continue

        event_lots = [capital_entries[i] for i in indices]
        cg_event_gain = sum((lot.gain_loss_eur for lot in event_lots), start=Decimal("0"))

        branch = _decide_event_branch(cg_event_gain, ogr_event_gain)
        if branch == "agree":
            updated = _apply_agree_first_lot(event_lots, ogr_event_gain, cg_event_gain)
        else:
            updated = _apply_conflict_unchanged(event_lots, ogr_event_gain, cg_event_gain)

        for i, lot in zip(indices, updated, strict=True):
            indexed_result[i] = lot

    return [indexed_result[i] for i in range(len(capital_entries))]


def _decide_event_branch(cg_event_gain: Decimal, ogr_event_gain: Decimal) -> str:
    """Decide whether an event's CG and OGR agree on direction.

    The decision is made on EVENT totals (sign only), matching the legacy
    per-lot override's ``direction_conflict`` test (``(ogr < 0) != (cg < 0)``).
    The ``> 1 EUR`` significance gate is applied ONLY to the per-lot review
    flag (see ``_conflict_review_state``), NOT to the branch decision, so a
    direction conflict is always resolved with OGR authority even when one
    side is below the noise floor.

    Args:
        cg_event_gain: Sum of the event's CG lot ``gain_loss_eur``.
        ogr_event_gain: The summed OGR entry value for the event.

    Returns:
        ``"agree"`` if the signs match; ``"conflict"`` if they differ.
    """
    cg_negative = cg_event_gain < 0
    ogr_negative = ogr_event_gain < 0
    if cg_negative != ogr_negative:
        return "conflict"
    return "agree"


def _apply_agree_first_lot(
    event_lots: list[CryptoCapitalGainEntry],
    ogr_event_gain: Decimal,
    cg_event_gain: Decimal,
) -> list[CryptoCapitalGainEntry]:
    """Apply the agree branch using first-lot-absorbs distribution.

    The first lot (input order) absorbs the full ``ogr_event_gain``; the
    remaining lots get ``gain_loss_eur = 0`` and
    ``proceeds_eur = lot.cost_eur``. Because aggregation sums
    ``gain_loss_eur`` and ``proceeds_eur`` across the event's lots, the
    aggregated row carries ``event_cost + ogr_event_gain`` and
    ``ogr_event_gain`` byte-exactly with no division and no rounding.

    Per-lot ``ogr_validation`` carries the FULL ``ogr_event_gain`` on every
    lot and the lot's PRE-distribution CG gain as ``calculated_gain_loss``
    (Design Invariant 3).

    Args:
        event_lots: CG lots for one event, in input order.
        ogr_event_gain: Summed OGR entry value for the event.
        cg_event_gain: Sum of the lots' PRE-distribution CG gains (kept
            for symmetry with the conflict branch; not used in the
            distribution math).

    Returns:
        Updated lots in input order.
    """
    updated: list[CryptoCapitalGainEntry] = []
    first = True
    for lot in event_lots:
        magnitude_diff_percent = (
            abs((ogr_event_gain - lot.gain_loss_eur) / lot.gain_loss_eur * 100)
            if lot.gain_loss_eur != 0
            else None
        )
        review_required, review_reason = _agree_review_state(
            magnitude_diff_percent, ogr_event_gain, lot.gain_loss_eur
        )
        validation = OgrValidationResult(
            ogr_gain_loss=ogr_event_gain,
            calculated_gain_loss=lot.gain_loss_eur,
            direction_conflict=False,
            magnitude_diff_percent=magnitude_diff_percent,
            review_required=review_required,
            review_reason=review_reason,
        )
        if first:
            new_lot = replace(
                lot,
                gain_loss_eur=ogr_event_gain,
                proceeds_eur=lot.cost_eur + ogr_event_gain,
                ogr_validation=validation,
            )
            first = False
        else:
            new_lot = replace(
                lot,
                gain_loss_eur=Decimal("0"),
                proceeds_eur=lot.cost_eur,
                ogr_validation=validation,
            )
        updated.append(new_lot)
    return updated


def _apply_conflict_unchanged(
    event_lots: list[CryptoCapitalGainEntry],
    ogr_event_gain: Decimal,
    cg_event_gain: Decimal,  # noqa: ARG001 (kept for symmetry with _apply_agree_first_lot)
) -> list[CryptoCapitalGainEntry]:
    """Apply the conflict branch: per-lot ``±abs(lot.gain_loss_eur)`` with OGR sign.

    UNCHANGED from the legacy per-lot override: each lot keeps its CG
    magnitude with the OGR sign. The lots sum to
    ``±sum(abs(lot.gain_loss_eur))``, which equals ``±abs(cg_event_gain)``
    only when every lot shares the event's CG sign; a mixed-sign event
    sums absolute magnitudes (this matches the legacy per-lot write, which
    is unchanged here, so it is not a Phase 1 regression). The existing
    109-lot conflict fixture pins byte-identity for the same-sign case.

    Per-lot ``ogr_validation`` carries the FULL ``ogr_event_gain`` on every
    lot and the lot's PRE-distribution CG gain as ``calculated_gain_loss``
    (Design Invariant 3).

    Args:
        event_lots: CG lots for one event, in input order.
        ogr_event_gain: Summed OGR entry value for the event (provides sign).
        cg_event_gain: Sum of the lots' PRE-distribution CG gains (unused;
            kept for symmetry with the agree branch).

    Returns:
        Updated lots in input order.
    """
    updated: list[CryptoCapitalGainEntry] = []
    for lot in event_lots:
        final_gain_loss = (
            -abs(lot.gain_loss_eur) if ogr_event_gain < 0 else abs(lot.gain_loss_eur)
        )
        magnitude_diff_percent = (
            abs((ogr_event_gain - lot.gain_loss_eur) / lot.gain_loss_eur * 100)
            if lot.gain_loss_eur != 0
            else None
        )
        # Per-lot direction_conflict mirrors the legacy per-lot test
        # (``(ogr < 0) != (lot_cg < 0)``); aggregation re-derives it from
        # event totals, so this only affects the pre-aggregation lot state.
        lot_direction_conflict = (ogr_event_gain < 0) != (lot.gain_loss_eur < 0)
        review_required, review_reason = _conflict_review_state(
            ogr_event_gain, lot.gain_loss_eur, lot_direction_conflict
        )
        validation = OgrValidationResult(
            ogr_gain_loss=ogr_event_gain,
            calculated_gain_loss=lot.gain_loss_eur,
            direction_conflict=lot_direction_conflict,
            magnitude_diff_percent=magnitude_diff_percent,
            review_required=review_required,
            review_reason=review_reason,
        )
        updated.append(
            replace(
                lot,
                gain_loss_eur=final_gain_loss,
                proceeds_eur=lot.cost_eur + final_gain_loss,
                ogr_validation=validation,
            )
        )
    return updated


def _agree_review_state(
    magnitude_diff_percent: Decimal | None,
    ogr_event_gain: Decimal,
    lot_gain_loss: Decimal,
) -> tuple[bool, str | None]:
    """Compute the per-lot review flag for the agree branch.

    Mirrors the legacy per-lot ``> 5%`` and ``> 1 EUR`` gates so the
    per-lot flag stays comparable, while aggregation re-derives the
    authoritative flag from event totals.
    """
    if magnitude_diff_percent and magnitude_diff_percent > _OGR_MAGNITUDE_DIFF_THRESHOLD:
        magnitude_diff = abs(ogr_event_gain - lot_gain_loss)
        if magnitude_diff > _OGR_ABSOLUTE_DIFF_THRESHOLD:
            return True, f"OGR magnitude differs from CG by {magnitude_diff_percent:.1f}%"
    return False, None


def _conflict_review_state(
    ogr_event_gain: Decimal, lot_gain_loss: Decimal, lot_direction_conflict: bool
) -> tuple[bool, str | None]:
    """Compute the per-lot review flag for the conflict branch.

    Mirrors the legacy ``> 1 EUR`` significance gate on both magnitudes.
    Only flags when this lot actually conflicts with OGR direction (a
    lot whose sign already matches OGR is not flagged).
    """
    if not lot_direction_conflict:
        return False, None
    if abs(ogr_event_gain) > _OGR_ABSOLUTE_DIFF_THRESHOLD and abs(lot_gain_loss) > _OGR_ABSOLUTE_DIFF_THRESHOLD:
        cg_indicated = "loss" if lot_gain_loss < 0 else "gain"
        return True, f"OGR direction override: CG indicated {cg_indicated}"
    return False, None
