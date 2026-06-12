"""Other Gains Report (OGR) handling for crypto tax reporting."""

from __future__ import annotations

import logging
from dataclasses import replace
from decimal import Decimal
from typing import Final

from ...domain.entities import OgrValidationResult
from ...infrastructure.config import TaxJurisdictionConfig
from ...infrastructure.koinly_parser import (
    _extract_ogr_gain_loss,
    format_datetime,
    normalize_asset_ticker,
    normalize_platform_name,
    parse_koinly_datetime,
)
from .aggregation import _is_valid_tabela_x_country
from .entities import CryptoCapitalGainEntry

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


def _build_ogr_index(ogr_rows: list[dict]) -> dict[tuple[str, str, str], Decimal]:
    """Build index for efficient CG entry lookup.

    Args:
        ogr_rows: List of parsed OGR row dictionaries from Other Gains Report CSV.

    Returns:
        Dictionary mapping (date_only, asset_normalized, wallet_normalized) to gain_loss_eur.
        - date_only: ISO format YYYY-MM-DD (time stripped from Date field)
        - asset_normalized: Via normalize_asset_ticker()
        - wallet_normalized: Via normalize_platform_name()
        - gain_loss_eur: Negative for Loss, positive for Profit

    Rows with zero value or unknown type are skipped.
    """
    index: dict[tuple[str, str, str], Decimal] = {}

    for row in ogr_rows:
        date_str = parse_koinly_datetime(row["Date"])
        date_only = format_datetime(date_str)  # YYYY-MM-DD, time stripped
        asset = normalize_asset_ticker(row["Asset"])
        wallet = normalize_platform_name(row["Wallet Name"])
        gain_loss = _extract_ogr_gain_loss(row)

        if gain_loss is not None:
            index[(date_only, asset, wallet)] = gain_loss

    return index


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
    ogr_index: dict[tuple[str, str, str], Decimal],
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
        ogr_index: Index built by _build_ogr_index mapping (date, asset, wallet) to gain_loss_eur.
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

        ogr_gain_loss = ogr_index.get(lookup_key)

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

