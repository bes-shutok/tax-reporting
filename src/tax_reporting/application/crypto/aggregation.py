"""Crypto aggregation functions for capital gains and rewards."""

from __future__ import annotations

import logging
from dataclasses import replace
from decimal import Decimal
from typing import TYPE_CHECKING, Final, TypedDict

from tax_reporting.domain.entities import OgrValidationResult
from tax_reporting.domain.exceptions import FileProcessingError

from .classification import (
    _is_valid_tabela_x_country,
    _resolve_income_code,
)
from .constants import ZERO

if TYPE_CHECKING:
    from tax_reporting.application.crypto.entities import (
        AggregatedRewardIncomeEntry,
        CryptoCapitalGainEntry,
        CryptoRewardIncomeEntry,
    )

else:
    # Runtime import for AggregatedRewardIncomeEntry to avoid circular dependency
    from tax_reporting.application.crypto.entities import AggregatedRewardIncomeEntry

# Constants for decimal calculations
_MATERIALITY_THRESHOLD: Final = Decimal("1")

# OGR validation threshold constants
_OGR_MAGNITUDE_DIFF_THRESHOLD: Final = 5




def aggregate_taxable_rewards(
    reward_entries: list[CryptoRewardIncomeEntry],
) -> list[AggregatedRewardIncomeEntry]:
    """Aggregate taxable_now reward entries by income_code + source_country for IRS filing.

    This function:
    1. Filters to only taxable_now rewards (deferred_by_law rewards are excluded)
    2. Groups by (income_code, source_country)
    3. Sums gross_income_eur and foreign_tax_eur within each group
    4. Preserves raw_row_count for reconciliation trail
    5. Validates that all mandatory IRS fields are present

    Args:
        reward_entries: All parsed reward entries from Koinly income report.

    Returns:
        List of aggregated reward entries ready for IRS filing.

    Raises:
        FileProcessingError: If a taxable_now row cannot be assigned valid Tabela X country.
    """
    logger = logging.getLogger(__name__)

    # Filter to only immediately taxable rewards
    taxable_entries = [e for e in reward_entries if e.tax_classification.value == "taxable_now"]

    if not taxable_entries:
        return []

    # Validate that all taxable entries have valid Tabela X country codes before aggregation.
    # This ensures the IRS-ready filing table never contains entries with missing mandatory fields.
    for entry in taxable_entries:
        source_country = entry.operator_origin.operator_country
        # Check for UNKNOWN country first (platform not mapped)
        if source_country == "UNKNOWN":
            raise FileProcessingError(
                f"Immediately taxable reward from wallet '{entry.wallet}' (asset: {entry.asset}, "
                f"value: {entry.value_eur} EUR) has an unresolved platform/operator. "
                f"The platform '{entry.platform}' is not mapped in resolve_operator_origin(). "
                f"Please add a platform mapping with operator_country to resolve this entry."
            )
        if not _is_valid_tabela_x_country(source_country):
            raise FileProcessingError(
                f"Immediately taxable reward from wallet '{entry.wallet}' (asset: {entry.asset}, "
                f"value: {entry.value_eur} EUR) cannot be assigned a valid Tabela X country code. "
                f"Resolved country: '{source_country}'. Please add a valid country mapping "
                f"for this platform/operator in resolve_operator_origin()."
            )

    # Aggregate by (income_code, source_country)
    class _RewardGroup(TypedDict):
        entries: list[CryptoRewardIncomeEntry]
        gross_income: Decimal
        foreign_tax: Decimal
        chains: set[str]

    groups: dict[tuple[str, str], _RewardGroup] = {}
    for entry in taxable_entries:
        income_code = _resolve_income_code(entry.source_type)
        source_country = entry.operator_origin.operator_country.upper()
        key = (income_code, source_country)

        if key not in groups:
            groups[key] = {
                "entries": [],
                "gross_income": ZERO,
                "foreign_tax": ZERO,
                "chains": set(),
            }

        groups[key]["entries"].append(entry)
        groups[key]["gross_income"] += entry.value_eur
        groups[key]["foreign_tax"] += entry.foreign_tax_eur
        groups[key]["chains"].add(entry.chain)

    # Build aggregated entries
    aggregated = []
    for (income_code, source_country), data in sorted(groups.items()):
        entries = data["entries"]
        chains_tuple = tuple(sorted(data["chains"]))
        aggregated.append(
            AggregatedRewardIncomeEntry(
                income_code=income_code,
                source_country=source_country,
                gross_income_eur=data["gross_income"],
                foreign_tax_eur=data["foreign_tax"],
                raw_row_count=len(entries),
                chains=chains_tuple,
                description=f"Income code {income_code} from {source_country}",
            )
        )

    logger.info(
        "Aggregated %d taxable-now reward rows into %d filing-ready entries (income_code + source_country)",
        len(taxable_entries),
        len(aggregated),
    )

    return aggregated


def _aggregate_origin_field(group: list[CryptoCapitalGainEntry]) -> str:
    """Derive the aggregated Token origin string from a group of FIFO lot rows.

    If all lots share the same origin string, return it. Otherwise concatenate
    unique, non-empty origins (preserving insertion order) with '; ' separator.
    When some lots have unknown origin, an indicator is appended so the user
    cannot mistake a partial result for full resolution.
    """
    unique_origins = list(dict.fromkeys(e.token_swap_history for e in group if e.token_swap_history))
    unknown_count = sum(1 for e in group if not e.token_swap_history)
    if not unique_origins:
        return ""
    parts = list(unique_origins)
    if unknown_count > 0:
        parts.append(f"{unknown_count} lot{'s' if unknown_count != 1 else ''} unresolved")
    if len(parts) == 1:
        return parts[0]
    return "; ".join(parts)


def _aggregate_ogr_validation(group: list[CryptoCapitalGainEntry]) -> OgrValidationResult | None:
    """Aggregate OGR validation results across FIFO lots in a group.

    All lots in a group share the same OGR value because they share the same
    (date, asset, wallet) lookup key. This function combines validation results:

    - ogr_gain_loss: taken from the first entry with a non-None value (all lots have the same OGR value)
    - calculated_gain_loss: summed across all lots
    - direction_conflict: True if ANY lot has direction_conflict=True
    - magnitude_diff_percent: maximum value across all lots
    - review_required: True if ANY lot has review_required=True
    - review_reason: unique reasons joined with "; "

    Returns None if all entries have ogr_validation=None.
    """
    # Filter to entries with OGR validation
    with_ogr = [e for e in group if e.ogr_validation is not None]
    if not with_ogr:
        return None

    # Take OGR gain/loss from first entry (all lots share the same OGR value per lookup key)
    first_ogr = with_ogr[0].ogr_validation
    ogr_gain_loss = first_ogr.ogr_gain_loss

    # Sum calculated gain/loss across all lots
    calculated_gain_loss = sum((e.ogr_validation.calculated_gain_loss for e in with_ogr), start=ZERO)

    # Recalculate direction_conflict using AGGREGATED calculated_gain_loss
    # Individual lots may not have conflicts, but the aggregated result might
    direction_conflict = (ogr_gain_loss < 0) != (calculated_gain_loss < 0)

    # Recalculate magnitude_diff_percent using AGGREGATED calculated_gain_loss
    # Individual lots have tiny values leading to misleading percentages (e.g., 5474%)
    # After aggregation, the comparison is meaningful
    magnitude_diff_percent = None
    if calculated_gain_loss != 0:
        magnitude_diff_percent = abs((ogr_gain_loss - calculated_gain_loss) / calculated_gain_loss * 100)

    # Determine review_required based on AGGREGATED values
    review_required = False
    if direction_conflict:
        # Direction override: require review if both magnitudes are significant
        if abs(ogr_gain_loss) > Decimal("1") and abs(calculated_gain_loss) > Decimal("1"):
            review_required = True
    elif magnitude_diff_percent and magnitude_diff_percent > _OGR_MAGNITUDE_DIFF_THRESHOLD:
        # Magnitude difference: require review if diff > 5% AND absolute diff > 1 EUR
        magnitude_diff = abs(ogr_gain_loss - calculated_gain_loss)
        if magnitude_diff > Decimal("1"):
            review_required = True

    # Build review_reason from aggregated state
    review_reason = None
    if review_required:
        if direction_conflict:
            review_reason = f"OGR direction override: CG indicated {'loss' if calculated_gain_loss < 0 else 'gain'}"
        elif magnitude_diff_percent and magnitude_diff_percent > _OGR_MAGNITUDE_DIFF_THRESHOLD:
            review_reason = f"OGR magnitude differs from CG by {magnitude_diff_percent:.1f}%"

    return OgrValidationResult(
        ogr_gain_loss=ogr_gain_loss,
        calculated_gain_loss=calculated_gain_loss,
        direction_conflict=direction_conflict,
        magnitude_diff_percent=magnitude_diff_percent,
        review_required=review_required,
        review_reason=review_reason,
    )


def _aggregate_capital_entries(entries: list[CryptoCapitalGainEntry]) -> list[CryptoCapitalGainEntry]:
    """Aggregate FIFO lot rows into one line per sale event (same date + asset + platform + holding_period).

    Rationale: the sale transaction is the reportable alienação in Portuguese IRS Quadro 9.4.
    FIFO lot allocation is an accounting method, not a separate disposal event (PT-C-025, PT-C-027).

    The holding_period is included in the aggregation key to preserve the taxable vs exempt breakdown
    needed for correct filing (PT-C-011: short-term gains are taxable, long-term gains are exempt).

    Uses normalized platform name in aggregation key so wallet aliases (e.g., "ByBit" and "ByBit (2)")
    collapse into the same logical account.
    """
    groups: dict[tuple[str, str, str, str], list[CryptoCapitalGainEntry]] = {}
    for entry in entries:
        key = (entry.disposal_date, entry.asset, entry.platform, entry.holding_period)
        groups.setdefault(key, []).append(entry)

    logger = logging.getLogger(__name__)
    result = []
    for group in groups.values():
        first = group[0]
        non_empty_dates = [e.acquisition_date for e in group if e.acquisition_date]
        acquisition_date = min(non_empty_dates) if non_empty_dates else ""
        if not acquisition_date:
            logger.warning(
                "Aggregated entry for %r sold %s has no acquisition date; "
                "one or more lots had a pool-exhausted placeholder with empty acquisition date",
                first.asset,
                first.disposal_date,
            )
        elif acquisition_date.startswith("1970-"):
            logger.warning(
                "Aggregated entry for %r sold %s has epoch sentinel acquisition date; "
                "one or more lots had missing Date Acquired in Koinly export",
                first.asset,
                first.disposal_date,
            )
        # Detect multiple acquisition dates within the aggregated group
        unique_acquisition_dates = sorted(set(dict.fromkeys(non_empty_dates)))
        multi_acquisition_dates = len(unique_acquisition_dates) > 1

        # Build multi-date note when multiple acquisition dates exist
        multi_date_note = ""
        if multi_acquisition_dates:
            dates_str = ", ".join(unique_acquisition_dates)
            multi_date_note = f"Acquired: {dates_str} ({len(group)} lot{'s' if len(group) != 1 else ''})"

        # Merge existing notes with multi-date note (multi-date note first for prominence)
        existing_notes = list(dict.fromkeys(e.notes for e in group if e.notes))
        all_note_parts = list(dict.fromkeys(existing_notes))
        if multi_date_note:
            all_note_parts.insert(0, multi_date_note)
        merged_notes = "; ".join(all_note_parts) or ""

        # Aggregate OGR validation results across lots
        ogr_validation = _aggregate_ogr_validation(group)

        result.append(
            replace(
                first,
                amount=sum((e.amount for e in group), start=ZERO),
                cost_eur=sum((e.cost_eur for e in group), start=ZERO),
                proceeds_eur=sum((e.proceeds_eur for e in group), start=ZERO),
                gain_loss_eur=sum((e.gain_loss_eur for e in group), start=ZERO),
                acquisition_date=acquisition_date,
                review_required=any(e.review_required for e in group),
                review_reason="; ".join(dict.fromkeys(e.review_reason for e in group if e.review_reason)) or None,
                notes=merged_notes,
                token_swap_history=_aggregate_origin_field(group),
                multi_acquisition_dates=multi_acquisition_dates,
                ogr_validation=ogr_validation,
            )
        )
    result.sort(key=lambda e: (e.disposal_date, e.asset, e.platform, e.holding_period))
    return result


def _filter_immaterial_entries(entries: list[CryptoCapitalGainEntry]) -> list[CryptoCapitalGainEntry]:
    """Drop lines where |gain/loss| < 1 EUR after aggregation (PT-C-028).

    Sub-1-EUR lines have no material tax impact and AT portal requires manual entry per line.
    The absolute-value test means small losses (between -1 and 0) are also excluded.
    """
    return [e for e in entries if abs(e.gain_loss_eur) >= _MATERIALITY_THRESHOLD]
