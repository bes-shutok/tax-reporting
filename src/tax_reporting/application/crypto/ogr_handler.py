"""Other Gains Report (OGR) handling for crypto tax reporting."""

from __future__ import annotations

import logging
from dataclasses import replace
from decimal import Decimal
from typing import Final

from ...domain.entities import OgrValidationResult
from ...infrastructure.config import TaxJurisdictionConfig
from ...infrastructure.koinly_parser import (
    normalize_asset_ticker,
    normalize_platform_name,
)
from .aggregation import _is_valid_tabela_x_country
from .classification import classify_derivatives_event
from .entities import (
    CryptoCapitalGainEntry,
    DerivativesEventType,
    DerivativesPnLEntry,
    ParsedOgrRow,
)
from .operator_origin import resolve_operator_origin

# OGR validation threshold constants
_OGR_MAGNITUDE_DIFF_THRESHOLD: Final = 5  # Percent threshold for magnitude difference warnings


def _validate_capital_entries_have_valid_countries(
    entries: list[CryptoCapitalGainEntry],
    jurisdiction: TaxJurisdictionConfig,  # noqa: ARG001 (reserved for future validation)
) -> list[CryptoCapitalGainEntry]:
    """Validate that all capital entries have valid Tabela X country codes.

    Entries with invalid/unknown country codes are retained in the output but flagged
    with review_required=True and an actionable review_reason. This follows the
    "process with error indicators" principle: the report is never aborted due to a
    missing registry entry — the user is informed and can add the platform mapping.

    Args:
        entries: Parsed capital gain entries to validate.
        jurisdiction: Tax jurisdiction config (reserved for future validation rules).

    Returns:
        Entries with any invalid-country entries flagged for review.

    Raises:
        FileProcessingError: If any entry has an invalid country code.
    """
    logger = logging.getLogger(__name__)
    result: list[CryptoCapitalGainEntry] = []
    invalid_count = 0

    for entry in entries:
        country = entry.operator_origin.operator_country
        if not _is_valid_tabela_x_country(country):
            invalid_count += 1
            logger.error(
                "Capital entry for %s on %s has unresolvable country '%s' (platform=%s, wallet=%s); "
                "entry flagged for review — add platform mapping to resolve_operator_origin()",
                entry.asset,
                entry.disposal_date,
                country,
                entry.platform,
                entry.wallet,
            )
            new_reason = (
                f"Platform '{entry.platform}' has no registered country mapping; "
                f"resolved country '{country}' is not a valid Tabela X code — "
                "add this platform to resolve_operator_origin() before filing"
            )
            result.append(
                replace(
                    entry,
                    review_required=True,
                    review_reason="; ".join(filter(None, [new_reason, entry.review_reason])),
                )
            )
        else:
            result.append(entry)

    if invalid_count > 0:
        logger.error(
            "%d capital gain %s have unresolvable country codes and require manual review "
            "before IRS filing; see individual entry warnings above",
            invalid_count,
            "entry" if invalid_count == 1 else "entries",
        )
    else:
        logger.debug(
            "Validated %d capital entries: all have valid Tabela X country codes",
            len(entries),
        )

    return result


def _build_ogr_index(
    rows: list[ParsedOgrRow],
) -> dict[tuple[str, str, str], Decimal]:
    """Build an OGR lookup index from parsed OGR rows.

    Summing duplicate keys into a single ``Decimal`` value happens here; the
    parser (``_find_and_parse_other_gains_file``) intentionally returns one
    ``ParsedOgrRow`` per source CSV row so per-row consumers (the derivatives
    classifier) can see each row individually.

    Normalization of ``date``, ``asset``, and ``wallet`` already happened in
    ``_parse_other_gains_row``; this function is a pure summing loop and
    MUST NOT re-parse or re-normalize.

    Args:
        rows: List of ``ParsedOgrRow`` instances from
            ``_find_and_parse_other_gains_file``.

    Returns:
        Dictionary mapping ``(date, asset, wallet)`` to the summed
        ``gain_loss`` (negative for ``Loss``, positive for ``Profit``) across
        all rows sharing that key.
    """
    index: dict[tuple[str, str, str], Decimal] = {}

    for row in rows:
        key = (row.date, row.asset, row.wallet)
        index[key] = index.get(key, Decimal("0")) + row.gain_loss

    return index


def _event_type_from_row_type(row_type: str) -> DerivativesEventType:
    """Map an OGR ``Type`` string to a ``DerivativesEventType``.

    Only ``"Profit"`` and ``"Loss"`` are produced by the current Koinly OGR
    export. The ``FEE`` variant is deferred until a Koinly export produces an
    OGR row whose description or TH counterpart explicitly identifies a futures
    fee distinct from realized P&L (see the plan's Monitor section, item 1).

    Args:
        row_type: The raw ``Type`` column value from the OGR CSV.

    Returns:
        ``DerivativesEventType.PROFIT`` for ``"Profit"``, ``LOSS`` for ``"Loss"``.

    Raises:
        ValueError: If ``row_type`` is neither ``"Profit"`` nor ``"Loss"``. The
            parser filters unknown types upstream, so this is a defensive
            failure that surfaces new platform-specific Type values loudly
            rather than silently mis-routing the row.
    """
    if row_type == "Profit":
        return DerivativesEventType.PROFIT
    if row_type == "Loss":
        return DerivativesEventType.LOSS
    raise ValueError(
        f"Unrecognized OGR row_type={row_type!r}; only 'Profit' and 'Loss' are supported"
    )


def _split_ogr_index(
    ogr_rows: list[ParsedOgrRow],
    capital_entries: list[CryptoCapitalGainEntry],
    jurisdiction: TaxJurisdictionConfig,
) -> tuple[dict[tuple[str, str, str], Decimal], list[DerivativesPnLEntry]]:
    """Split OGR rows into a spot index and a derivatives P&L entry list.

    Per-row routing (Task 7 of the derivatives-separation plan). Each
    ``ParsedOgrRow`` is classified independently by ``classify_derivatives_event``
    and routed to one of two outputs:

    - ``Derivatives`` variant → appended to ``derivatives_entries`` as a
      ``DerivativesPnLEntry`` under CIRS art. 10(1)(e). The row is excluded
      from ``spot_index`` so the downstream direction override cannot see it.
    - ``Ambiguous`` variant → routed to ``derivatives_entries`` with
      ``review_required=True`` and the classifier's reason cited (sealed-class
      sentinel pattern: never reuse the success variant for bypass).
    - ``Spot`` variant → the row's ``gain_loss`` is summed into
      ``spot_index[(date, asset, wallet)]`` and the downstream
      ``_apply_ogr_direction_override`` may consume it.

    Backward compatibility (``separate_derivatives_reporting=False``): the
    function returns ``(_build_ogr_index(ogr_rows), [])`` — i.e., the combined
    summed index with no derivatives split, byte-identical to the pre-Task-7
    pipeline. The downstream ``_apply_ogr_direction_override`` receives the
    combined index and behaves as before.

    Safety net (r1 Medium #7): when ``separate_derivatives_reporting=True`` and
    classification returns ``Derivatives`` while ``len(cg_matches) == 0``, a
    ``logger.warning`` is emitted so ambiguous platform cases (no CG counterpart
    to confirm spot vs derivatives classification) are surfaced. The row is
    still routed to ``derivatives_entries`` because the OGR ``Type`` column is
    the authoritative signal — Profit rows are always derivatives, and Loss
    rows with no CG counterpart have no spot anchor.

    Args:
        ogr_rows: Parsed OGR rows from ``_find_and_parse_other_gains_file``.
        capital_entries: Pre-aggregation CG entries used to find spot
            counterparts via the ``(date, asset, wallet)`` key.
        jurisdiction: Tax jurisdiction config. The
            ``separate_derivatives_reporting`` flag toggles the split.

    Returns:
        Tuple ``(spot_index, derivatives_entries)``. When
        ``separate_derivatives_reporting`` is ``False``, ``derivatives_entries``
        is always empty and ``spot_index`` is the combined summed index.
    """
    logger = logging.getLogger(__name__)

    if not jurisdiction.separate_derivatives_reporting:
        return _build_ogr_index(ogr_rows), []

    spot_index: dict[tuple[str, str, str], Decimal] = {}
    derivatives_entries: list[DerivativesPnLEntry] = []

    for row in ogr_rows:
        cg_matches = [
            entry
            for entry in capital_entries
            if (
                entry.disposal_date,
                normalize_asset_ticker(entry.asset),
                normalize_platform_name(entry.wallet),
            )
            == (row.date, row.asset, row.wallet)
        ]
        classification = classify_derivatives_event(row, cg_matches)

        if classification.kind == "spot":
            key = (row.date, row.asset, row.wallet)
            spot_index[key] = spot_index.get(key, Decimal("0")) + row.gain_loss
            continue

        # Derivatives or Ambiguous → route to derivatives_entries. Resolve the
        # operator origin so each row carries the Quadro 13 "País da contraparte"
        # fields. The OGR ``Type`` column is authoritative for routing; operator
        # resolution decorates rows the classifier already sent here, never
        # reclassifies (Design Invariant 2).
        operator_origin = resolve_operator_origin(row.wallet, transaction_date=row.date)

        # Surface the resolver's specific reason for temporal-validity and
        # date-parse failures (operator_entity is the real mapped entity and
        # review_reason carries the specific diagnostic). For the truly-unknown
        # platform case, the resolver sets operator_entity to the internal
        # sentinel "UNKNOWN_OPERATOR_REVIEW_REQUIRED"; synthesise the actionable
        # fix-path message that cites resolve_operator_origin() (Design
        # Invariant 3; mirrors ogr_handler.py:67-71).
        if operator_origin.review_required:
            if operator_origin.operator_entity == "UNKNOWN_OPERATOR_REVIEW_REQUIRED":
                operator_origin_reason = (
                    f"Unknown platform '{row.wallet}', add this platform to "
                    "resolve_operator_origin() before filing"
                )
            elif operator_origin.review_reason:
                operator_origin_reason = operator_origin.review_reason
            else:
                operator_origin_reason = "Operator origin review required"
        else:
            operator_origin_reason = ""

        classification_reason = classification.reason if classification.kind == "ambiguous" else ""
        # Platform reason first so the blocking action is visible before the
        # classification context (Design Invariant 3; matches ogr_handler.py:76).
        combined_reason = "; ".join(filter(None, [operator_origin_reason, classification_reason]))

        derivatives_entries.append(
            DerivativesPnLEntry(
                date=row.date,
                asset=row.asset,
                platform=row.wallet,
                pnl_eur=row.gain_loss,
                event_type=_event_type_from_row_type(row.row_type),
                source_ref=f"OGR:{row.date}:{row.asset}",
                review_required=classification.kind == "ambiguous" or operator_origin.review_required,
                review_reason=combined_reason,
                # operator_entity is the raw wallet name (user-facing):
                # operator_origin.operator_entity may be the internal sentinel
                # "UNKNOWN_OPERATOR_REVIEW_REQUIRED" for unmapped platforms,
                # which would leak into Excel (Design Invariant 6).
                operator_entity=row.wallet,
                operator_country=operator_origin.operator_country,
            )
        )

        if classification.kind == "derivatives" and len(cg_matches) == 0:
            logger.warning(
                "OGR row at (%s, %s, %s) routed to derivatives by row type; "
                "no CG counterpart to confirm spot vs derivatives classification",
                row.date,
                row.asset,
                row.wallet,
            )

    return spot_index, derivatives_entries


def _apply_ogr_overrides(
    capital_entries: list[CryptoCapitalGainEntry],
    ogr_index: dict[tuple[str, str, str], Decimal],
    jurisdiction: TaxJurisdictionConfig,
) -> list[CryptoCapitalGainEntry]:
    """Apply OGR gain/loss overrides to capital gains entries.

    When jurisdiction.use_other_gains_report is enabled, this function overrides
    the gain/loss values from Koinly Capital Gains report with the authoritative
    values from the Other Gains Report. This is necessary for futures/derivatives
    where the CG report may not correctly reflect the true gain/loss.

    CRITICAL: This override must happen BEFORE _aggregate_capital_entries
    because CG rows are individual FIFO lots that get summed in aggregation.
    OGR contains the correct total gain/loss for the disposal event.
    Overriding after aggregation would lose the lot-level trail.

    Args:
        capital_entries: List of capital gain entries from CG parsing.
        ogr_index: Index built by _build_ogr_index mapping (date, asset, wallet) to gain_loss_eur.
        jurisdiction: Tax jurisdiction config with use_other_gains_report flag.

    Returns:
        List of capital gain entries with OGR overrides applied. Entries without
        OGR matches are returned unchanged.
    """
    # If jurisdiction doesn't use OGR, return entries unchanged
    if not jurisdiction.use_other_gains_report:
        return capital_entries

    logger = logging.getLogger(__name__)
    result: list[CryptoCapitalGainEntry] = []

    for entry in capital_entries:
        # Build lookup key: (date, asset_normalized, wallet_normalized)
        lookup_key = (
            entry.disposal_date,
            normalize_asset_ticker(entry.asset),
            normalize_platform_name(entry.wallet),
        )

        ogr_gain_loss = ogr_index.get(lookup_key)

        if ogr_gain_loss is not None:
            # OGR has a value for this entry - override gain/loss and proceeds
            # Cost basis stays the same; only gain/loss and proceeds are adjusted
            new_proceeds = entry.cost_eur + ogr_gain_loss

            # Build note documenting the override
            override_note = (
                f"OGR override: gain/loss adjusted from {entry.gain_loss_eur} EUR "
                f"to {ogr_gain_loss} EUR per Other Gains Report"
            )
            merged_notes = f"{override_note}; {entry.notes}" if entry.notes else override_note

            logger.info(
                "OGR override applied: %s on %s: gain/loss changed from %s EUR to %s EUR",
                entry.asset,
                entry.disposal_date,
                entry.gain_loss_eur,
                ogr_gain_loss,
            )

            result.append(
                replace(
                    entry,
                    gain_loss_eur=ogr_gain_loss,
                    proceeds_eur=new_proceeds,
                    notes=merged_notes,
                )
            )
        else:
            # No OGR match - keep original entry
            logger.debug(
                "No OGR match for CG entry: %s on %s at %s",
                entry.asset,
                entry.disposal_date,
                entry.wallet,
            )
            result.append(entry)

    return result


def _apply_ogr_direction_override(
    capital_entries: list[CryptoCapitalGainEntry],
    spot_index: dict[tuple[str, str, str], Decimal],
    jurisdiction: TaxJurisdictionConfig,
) -> list[CryptoCapitalGainEntry]:
    """Apply OGR directional authority to capital gains entries.

    When jurisdiction.use_other_gains_report is enabled, this function uses OGR
    values for DIRECTIONAL authority (loss vs gain) while preserving CG-calculated
    magnitude. This is necessary for futures/derivatives where OGR correctly
    reports the overall gain/loss direction but CG provides the per-lot FIFO
    allocation.

    CRITICAL: This override must happen BEFORE _aggregate_capital_entries
    because CG rows are individual FIFO lots that get summed in aggregation.
    OGR contains the correct total gain/loss for the disposal event.
    Overriding after aggregation would lose the lot-level trail.

    Directional Authority Semantics:
    - OGR is AUTHORITATIVE for DIRECTION (loss vs gain)
    - CG provides MAGNITUDE via standard FIFO calculation
    - When OGR and CG agree on direction, use OGR magnitude (more accurate for derivatives)
    - Magnitude differences > 5% → YELLOW flag (review recommended, not blocking)
    - Absolute threshold of 1 EUR to avoid noise on near-zero gains

    Args:
        capital_entries: List of capital gain entries from CG parsing.
        spot_index: Spot-slice OGR index produced by ``_split_ogr_index`` when
            ``separate_derivatives_reporting`` is enabled, or the combined
            summed index produced by ``_build_ogr_index`` when the flag is
            disabled (backward-compat path). The function body does NOT branch
            on the flag — it consumes whatever index the caller passes. When
            the split is active, derivatives rows never reach this function.
        jurisdiction: Tax jurisdiction config with use_other_gains_report flag.

    Returns:
        List of capital gain entries with OGR direction override applied.
        Entries without OGR matches are returned unchanged (ogr_validation=None).
    """
    # If jurisdiction doesn't use OGR, return entries unchanged
    if not jurisdiction.use_other_gains_report:
        return capital_entries

    logger = logging.getLogger(__name__)
    result: list[CryptoCapitalGainEntry] = []

    for entry in capital_entries:
        # Build lookup key: (date, asset_normalized, wallet_normalized)
        lookup_key = (
            entry.disposal_date,
            normalize_asset_ticker(entry.asset),
            normalize_platform_name(entry.wallet),
        )

        ogr_gain_loss = spot_index.get(lookup_key)

        if ogr_gain_loss is not None:
            # OGR has a value for this entry - apply directional authority
            direction_conflict = (ogr_gain_loss < 0) != (entry.gain_loss_eur < 0)
            magnitude_diff_percent = (
                abs((ogr_gain_loss - entry.gain_loss_eur) / entry.gain_loss_eur * 100)
                if entry.gain_loss_eur != 0
                else None
            )

            # Determine final gain/loss value and validation result
            final_gain_loss = entry.gain_loss_eur
            review_required = False
            review_reason = None

            if direction_conflict:
                # OGR is authoritative for direction: use OGR sign with CG magnitude
                final_gain_loss = (
                    -abs(entry.gain_loss_eur) if ogr_gain_loss < 0 else abs(entry.gain_loss_eur)
                )
                # Only require review if both magnitudes are significant
                # This avoids flagging noise on near-zero values
                if abs(ogr_gain_loss) > Decimal("1") and abs(entry.gain_loss_eur) > Decimal("1"):
                    review_required = True
                    review_reason = (
                        f"OGR direction override: CG indicated "
                        f"{'loss' if entry.gain_loss_eur < 0 else 'gain'}"
                    )
            else:
                # Directions agree - use OGR magnitude (more accurate for derivatives)
                final_gain_loss = ogr_gain_loss

                # Check if magnitude difference is significant
                if magnitude_diff_percent and magnitude_diff_percent > _OGR_MAGNITUDE_DIFF_THRESHOLD:
                    # Also require absolute difference > 1 EUR to avoid noise on near-zero gains
                    magnitude_diff = abs(ogr_gain_loss - entry.gain_loss_eur)
                    if magnitude_diff > Decimal("1"):
                        review_required = True
                        review_reason = (
                            f"OGR magnitude differs from CG by {magnitude_diff_percent:.1f}%"
                        )

            validation = OgrValidationResult(
                ogr_gain_loss=ogr_gain_loss,
                calculated_gain_loss=entry.gain_loss_eur,
                direction_conflict=direction_conflict,
                magnitude_diff_percent=magnitude_diff_percent,
                review_required=review_required,
                review_reason=review_reason,
            )

            logger.info(
                "OGR direction override applied: %s on %s: gain/loss changed from %s EUR to %s EUR",
                entry.asset,
                entry.disposal_date,
                entry.gain_loss_eur,
                final_gain_loss,
            )

            result.append(
                replace(
                    entry,
                    gain_loss_eur=final_gain_loss,
                    proceeds_eur=entry.cost_eur + final_gain_loss,
                    ogr_validation=validation,
                )
            )
        else:
            # No OGR match - keep original entry without validation
            logger.debug(
                "No OGR match for CG entry: %s on %s at %s",
                entry.asset,
                entry.disposal_date,
                entry.wallet,
            )
            result.append(entry)

    return result

