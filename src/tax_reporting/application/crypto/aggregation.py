"""Crypto aggregation functions for capital gains and rewards."""

from __future__ import annotations

import logging
from collections import Counter
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
    # AggregatedRewardIncomeEntry needs a runtime import to avoid a circular
    # dependency with entities.py. DerivativesEventType and DerivativesPnLEntry
    # do not have that cycle (entities.py does not import aggregation.py) but
    # ride along in the same else block to keep all entities imports co-located.
    from tax_reporting.application.crypto.entities import (
        AggregatedRewardIncomeEntry,
        DerivativesEventType,
        DerivativesPnLEntry,
    )

# Constants for decimal calculations
_MATERIALITY_THRESHOLD: Final = Decimal("1")

# OGR validation threshold constants
_OGR_MAGNITUDE_DIFF_THRESHOLD: Final = 5

# Zero-basis review reason prefixes stripped from aggregated rows whose values
# are non-zero and material. Matched via ``startswith`` against the split parts
# so minor upstream-prose edits (e.g. rewording the trailing "likely Koinly
# tracking entry or data error" tail) do not silently break the strip set.
# Per-lot signals stay in ``context.review_entries`` and the WARNING log; this
# filter only re-derives the user-visible aggregated row's flag.
#
# The cost/proceeds prefixes include the trailing ": " so the more-severe
# "_ZERO_COST_NEGATIVE_PROCEEDS_REASON" ("Zero acquisition cost with negative
# disposal proceeds: ...") is NOT stripped: it flags a distinct fee-heavy
# liquidation / data anomaly whose guidance must survive aggregation.
_ZERO_BASIS_REASON_PREFIXES: Final[tuple[str, ...]] = (
    "Zero EUR value for known crypto asset",
    "Zero acquisition cost: ",
    "Zero disposal proceeds: ",
)




def aggregate_taxable_rewards(
    reward_entries: list[CryptoRewardIncomeEntry],
    classify_rewards_with_income_codes: bool,
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
        classify_rewards_with_income_codes: Whether to classify reward types into
            official Tabela V income codes, threaded to :func:`_resolve_income_code`.

    Returns:
        List of aggregated reward entries ready for IRS filing.

    Raises:
        FileProcessingError: If a taxable_now row cannot be assigned a valid Tabela X
            country code, or if (when income-code classification is enabled) a
            taxable_now group resolves to no official Tabela V income code -- the
            income type is a mandatory Quadro 8A field, so an incomplete filing row is
            never emitted.
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
        income_code = _resolve_income_code(entry.source_type, classify_rewards_with_income_codes)
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
        if income_code:
            description = f"Income code {income_code} from {source_country}"
        else:
            description = f"Reward income from {source_country}"
            # The income type (Tabela V code) is a mandatory Quadro 8A field, just
            # like the Tabela X country code that is fail-closed above. Mirror that
            # contract: when income-code classification is enabled, a taxable-now
            # (fiat-denominated) reward whose source_type resolves to no official
            # Tabela V code must fail closed rather than emit an incomplete filing row
            # that a filer could transcribe as-is. (When classification is disabled,
            # every type resolves to "" and is expected/valid; not raised.)
            if classify_rewards_with_income_codes:
                source_types = sorted({e.source_type for e in entries if e.source_type})
                sample = entries[0]
                raise FileProcessingError(
                    f"Immediately taxable reward from wallet '{sample.wallet}' "
                    f"(asset: {sample.asset}, value: {data['gross_income']} EUR, "
                    f"source_type(s): {', '.join(source_types) or 'unknown'}, "
                    f"source_country={source_country}) has no official Tabela V income "
                    f"code. Verify the correct Modelo 3 income type (Quadro 8A) and add "
                    f"the source_type -> code mapping in _resolve_income_code() before filing."
                )
        aggregated.append(
            AggregatedRewardIncomeEntry(
                income_code=income_code,
                source_country=source_country,
                gross_income_eur=data["gross_income"],
                foreign_tax_eur=data["foreign_tax"],
                raw_row_count=len(entries),
                chains=chains_tuple,
                description=description,
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


def _re_evaluate_aggregated_review(
    entry: CryptoCapitalGainEntry,
) -> tuple[bool, str | None]:
    """Re-evaluate the aggregated disposal row's review flag from aggregated values.

    Per-lot zero-basis signals stay in ``context.review_entries`` and the WARNING
    log; this filter only re-derives the user-visible aggregated row's flag so a
    single noisy lot inside a material disposal does not poison the aggregated
    row.

    Gate (all three must hold): ``cost_eur > 0 AND proceeds_eur > 0 AND
    abs(gain_loss_eur) >= _MATERIALITY_THRESHOLD``. When the gate holds, split
    the joined reason on ``"; "``, drop parts whose prefix matches a zero-basis
    reason, and return ``(False, None)`` if no parts survive, else
    ``(True, "; ".join(surviving))``. Otherwise return the entry's flag
    unchanged.

    The None guard on the first line is load-bearing: the default clean-disposal
    production path produces ``review_reason=None`` via ``"; ".join(...) or None``
    in :func:`_aggregate_capital_entries`, and without the guard the materiality
    gate would dereference ``None.split("; ")`` and crash.
    """
    if entry.review_reason is None:
        return entry.review_required, entry.review_reason
    if (
        entry.cost_eur > 0
        and entry.proceeds_eur > 0
        and abs(entry.gain_loss_eur) >= _MATERIALITY_THRESHOLD
    ):
        surviving = [
            part
            for part in entry.review_reason.split("; ")
            if not part.startswith(_ZERO_BASIS_REASON_PREFIXES)
        ]
        if not surviving:
            return False, None
        return True, "; ".join(surviving)
    return entry.review_required, entry.review_reason


def _aggregate_capital_entries(entries: list[CryptoCapitalGainEntry]) -> list[CryptoCapitalGainEntry]:
    """Aggregate FIFO lot rows into one line per sale event (same date + asset + platform + holding_period).

    Rationale: the sale transaction is the reportable alienação in Portuguese IRS Quadro 9.4.
    FIFO lot allocation is an accounting method, not a separate disposal event (PT-C-025, PT-C-027).

    The holding_period is included in the aggregation key to preserve the taxable vs exempt breakdown
    needed for correct filing (PT-C-011: short-term gains are taxable, long-term gains are exempt).

    Uses the platform field in the aggregation key so wallets that share a
    platform consolidate (platform consolidation is handled by the
    platform-level resolver; see Phase A Invariant 4).
    """
    groups: dict[tuple[str, str, str, str], list[CryptoCapitalGainEntry]] = {}
    for entry in entries:
        key = (entry.disposal_date, entry.asset, entry.platform, entry.holding_period)
        groups.setdefault(key, []).append(entry)

    logger = logging.getLogger(__name__)
    result = []
    # Pattern L (per-row -> DEBUG + post-loop aggregate): this function is called once
    # per run from crypto_reporting.py (NOT inside a per-asset loop), so the counter +
    # aggregate live directly here -- the predecessor's "EASY" pattern-A shape. The
    # audit signal stays on the data: the aggregated entry inherits the lot's
    # review_required/review_reason set by predecessor pattern F, which surfaces in the
    # Crypto Gains "YES:" cell. The aggregate just collapses N identical WARNINGs into
    # one naming the affected assets.
    no_date_entries: Counter[str] = Counter()
    epoch_entries: Counter[str] = Counter()
    for group in groups.values():
        first = group[0]
        non_empty_dates = [e.acquisition_date for e in group if e.acquisition_date]
        acquisition_date = min(non_empty_dates) if non_empty_dates else ""
        if not acquisition_date:
            logger.debug(
                "Aggregated entry for %r sold %s has no acquisition date; "
                "one or more lots had a pool-exhausted placeholder with empty acquisition date",
                first.asset,
                first.disposal_date,
            )
            no_date_entries[first.asset] += 1
        elif acquisition_date.startswith("1970-"):
            logger.debug(
                "Aggregated entry for %r sold %s has epoch sentinel acquisition date; "
                "one or more lots had missing Date Acquired in Koinly export",
                first.asset,
                first.disposal_date,
            )
            epoch_entries[first.asset] += 1
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

        aggregated_entry = replace(
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
        # Re-evaluate the aggregated row's review flag from the aggregated
        # values (Invariant 2): a single noisy lot inside a material disposal
        # must not poison the user-visible row. Apply BOTH fields in a single
        # ``replace`` call -- ``CryptoCapitalGainEntry.__post_init__`` rejects
        # ``review_required=True AND review_reason=None``.
        review_required, review_reason = _re_evaluate_aggregated_review(aggregated_entry)
        result.append(
            replace(aggregated_entry, review_required=review_required, review_reason=review_reason)
        )
    result.sort(key=lambda e: (e.disposal_date, e.asset, e.platform, e.holding_period))
    # Pattern L: emit ONE aggregate WARNING when any aggregated entry had a missing or
    # epoch-sentinel acquisition date from a pool-exhausted placeholder lot. The per-row
    # detail (asset + disposal date + cause) is reachable at DEBUG above; the Excel Crypto
    # Gains "YES:" review column carries the inherited pool-exhausted review_reason. The
    # breakdown is keyed by asset with a SUMMED count across both causes (no-date and epoch
    # are added per-asset via Counter addition), so the summary names the total and the
    # affected assets without distinguishing the per-cause split.
    if no_date_entries or epoch_entries:
        combined: Counter[str] = no_date_entries + epoch_entries
        total = sum(combined.values())
        logger.warning(
            "%d aggregated capital-gains entry(ies) with missing/epoch acquisition dates "
            "from pool-exhausted placeholders (%s); see DEBUG log and Crypto Gains review "
            "column for details",
            total,
            ", ".join(f"{a}: {n}" for a, n in sorted(combined.items())),
        )
    return result


def _filter_immaterial_entries(entries: list[CryptoCapitalGainEntry]) -> list[CryptoCapitalGainEntry]:
    """Drop lines where |gain/loss| < 1 EUR after aggregation (PT-C-028).

    Sub-1-EUR lines have no material tax impact and AT portal requires manual entry per line.
    The absolute-value test means small losses (between -1 and 0) are also excluded.
    """
    return [e for e in entries if abs(e.gain_loss_eur) >= _MATERIALITY_THRESHOLD]


def aggregate_derivatives_entries(
    entries: list[DerivativesPnLEntry],
) -> list[DerivativesPnLEntry]:
    """Aggregate derivatives P&L rows by (date, asset, platform, event_type).

    Mirrors :func:`_aggregate_capital_entries`: builds a ``dict[group_key, list[entry]]``
    and emits one aggregated entry per group with summed ``pnl_eur``.

    The ``event_type`` is part of the aggregation key so that a realized profit and a
    realized loss on the same day for the same asset/platform do not collapse into a
    misleading net. Each variant represents a distinct economic event under
    CIRS art. 10(1)(e).

    Args:
        entries: Raw derivatives P&L entries produced by the OGR classifier.

    Returns:
        Aggregated derivatives entries sorted by (date, asset, platform, event_type).
    """
    groups: dict[tuple[str, str, str, DerivativesEventType], list[DerivativesPnLEntry]] = {}
    for entry in entries:
        key = (entry.date, entry.asset, entry.platform, entry.event_type)
        groups.setdefault(key, []).append(entry)

    logger = logging.getLogger(__name__)

    result = []
    for group in groups.values():
        first = group[0]
        unique_refs = list(dict.fromkeys(e.source_ref for e in group if e.source_ref))
        # Merge notes across group members with the same pattern as _aggregate_capital_entries
        # (aggregation.py:283-287): join unique non-empty notes with "; ". Mirrors the
        # established codebase pattern so non-first members' notes survive aggregation
        # instead of being silently dropped.
        merged_notes = "; ".join(dict.fromkeys(e.notes for e in group if e.notes)) or ""
        # annex_hint/operation_code are taken from `first` below. Before this branch
        # they were group-constants (every row carried G/Q13 + G51); Feature A's
        # counterparty-residency routing made them per-row variable, so a mixed-route
        # group would silently drop non-first members' routes. Safe today because
        # operator_country is resolved deterministically per platform and platform is
        # part of the group key, but surface heterogeneity at warning+ so the latent
        # gap is observable if that invariant ever changes.
        routes = {(e.annex_hint, e.operation_code) for e in group}
        if len(routes) > 1:
            logger.warning(
                "Derivatives group (date=%s asset=%s platform=%s event=%s) has mixed "
                "annex routes %s; rendering route from the first member.",
                first.date,
                first.asset,
                first.platform,
                first.event_type.value,
                sorted(routes),
            )
        result.append(
            replace(
                first,
                pnl_eur=sum((e.pnl_eur for e in group), start=ZERO),
                source_ref="; ".join(unique_refs),
                review_required=any(e.review_required for e in group),
                review_reason="; ".join(
                    dict.fromkeys(e.review_reason for e in group if e.review_reason)
                ),
                event_count=len(group),
                operator_entity=first.operator_entity,
                operator_country=first.operator_country,
                annex_hint=first.annex_hint,
                operation_code=first.operation_code,
                notes=merged_notes,
            )
        )
    result.sort(key=lambda e: (e.date, e.asset, e.platform, e.event_type.value))
    return result
