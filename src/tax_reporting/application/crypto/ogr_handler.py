"""Other Gains Report (OGR) handling for crypto tax reporting."""

from __future__ import annotations

import logging
from dataclasses import replace
from decimal import Decimal
from typing import Final

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

# Derivatives routing constants (Modelo 3 / CIRS art. 10(1)(e) -> Anexo G Quadro 13 /
# Anexo J Quadro 9.2.B). The annex + operation codes form a closed AT enum and are
# paired per the routing rule below; they never mix. Codes stay PT-named (Invariant 3).
_PT_RESIDENT_ANNEX_HINT: Final = "G/Q13"
_PT_RESIDENT_OPERATION_CODE: Final = "G51"
_PT_NONRESIDENT_ANNEX_HINT: Final = "J/Q9.2.B"
_PT_NONRESIDENT_OPERATION_CODE: Final = "G30"


def _derivatives_route(
    country: str,
    operator_country: str,
    route_via_residency: bool,
) -> tuple[str, str]:
    """Resolve the Modelo 3 annex hint and operation code for a derivatives P&L row.

    Flag-gated routing (Invariant 2: jurisdiction-specific output must gate on a
    ``TaxJurisdictionConfig`` flag, never on a country literal or be unconditional):

    - Flag off -> ``("", "")``: when residency routing is disabled, no annex/code hint
      is emitted regardless of jurisdiction.
    - Flag on + counterparty resident in the taxpayer's jurisdiction -> ``("G/Q13", "G51")``:
      Anexo G Quadro 13 with operation code G51 ("instrumentos financeiros derivados").
    - Flag on + any other counterparty (including ``"UNKNOWN"`` and empty) ->
      ``("J/Q9.2.B", "G30")``: fail-safe to the non-resident annex. When operator origin
      cannot be resolved, route to the non-resident annex rather than silently claiming
      residence.

    The residency test is ``operator_country == country`` (country-agnostic; Invariant 2):
    the counterparty is a resident of the taxpayer's jurisdiction. The ``country`` argument
    is the taxpayer's jurisdiction; the ``operator_country`` argument is the counterparty's
    alpha-2 country code from ``resolve_operator_origin``.

    Args:
        country: Taxpayer jurisdiction alpha-2 code (``TaxJurisdictionConfig.country``).
        operator_country: Counterparty alpha-2 country code (or ``"UNKNOWN"``).
        route_via_residency: Whether to route by counterparty residency
            (``TaxJurisdictionConfig.route_derivatives_by_counterparty_residency``).

    Returns:
        Tuple ``(annex_hint, operation_code)`` per the routing rule above.
    """
    if not route_via_residency:
        return "", ""
    if operator_country.upper() == country.upper():
        return _PT_RESIDENT_ANNEX_HINT, _PT_RESIDENT_OPERATION_CODE
    return _PT_NONRESIDENT_ANNEX_HINT, _PT_NONRESIDENT_OPERATION_CODE


def _validate_capital_entries_have_valid_countries(
    entries: list[CryptoCapitalGainEntry],
    jurisdiction: TaxJurisdictionConfig,  # noqa: ARG001 (reserved for future validation)
) -> list[CryptoCapitalGainEntry]:
    """Validate that all capital entries have valid Tabela X country codes.

    Entries with invalid/unknown country codes are retained in the output but flagged
    with review_required=True and an actionable review_reason. This follows the
    "process with error indicators" principle: the report is never aborted due to a
    missing registry entry. The user is informed and can add the platform mapping.

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
                "entry flagged for review: add platform mapping to resolve_operator_origin()",
                entry.asset,
                entry.disposal_date,
                country,
                entry.platform,
                entry.wallet,
            )
            new_reason = (
                f"Platform '{entry.platform}' has no registered country mapping; "
                f"resolved country '{country}' is not a valid Tabela X code. "
                "Add this platform to resolve_operator_origin() before filing"
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
      ``apply_ogr_event_level`` may consume it.

    Backward compatibility (``separate_derivatives_reporting=False``): the
    function returns ``(_build_ogr_index(ogr_rows), [])`` (i.e., the combined
    summed index with no derivatives split, byte-identical to the pre-Task-7 pipeline).
    The downstream ``apply_ogr_event_level`` receives the
    combined index and behaves as before.

    Safety net (r1 Medium #7): when ``separate_derivatives_reporting=True`` and
    classification returns ``Derivatives`` while ``len(cg_matches) == 0``, a
    ``logger.warning`` is emitted so ambiguous platform cases (no CG counterpart
    to confirm spot vs derivatives classification) are surfaced. The row is
    still routed to ``derivatives_entries`` because the OGR ``Type`` column is
    the authoritative signal: Profit rows are always derivatives, and Loss
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

        # Resolve the Modelo 3 annex + operation code from the taxpayer's jurisdiction
        # and the counterparty's residency. Flag-gated: when residency routing is
        # disabled, no annex/code hint is emitted regardless of jurisdiction.
        route_annex_hint, route_operation_code = _derivatives_route(
            jurisdiction.country,
            operator_origin.operator_country,
            jurisdiction.route_derivatives_by_counterparty_residency,
        )

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
                # Resolved per (jurisdiction, counterparty residency) so the Modelo 3
                # routing reflects the operator origin, not a hardcoded resident default.
                annex_hint=route_annex_hint,
                operation_code=route_operation_code,
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

