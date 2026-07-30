"""Standalone transaction and network fee filtering (DP-015).

Under jurisdictions like Portugal (CIRS Art. 10(1)(k)), a standalone
network/transaction fee is a non-taxable utility cost without received
consideration, so it is not an *alienacao onerosa* and Koinly's default
realization of gains on it must be filtered out of the capital gains
worksheets.

This module owns ONLY:

- the identification predicate (TxHash co-occurrence + tagged/untagged
  classification + per-token ``Net Value (EUR)`` ceiling + the empty-dict
  guard);
- the unlisted-asset *suspect* surfacing (a ``review_required`` flag on the
  correlated CG lot, a ``CryptoReviewEntry`` row in the Crypto Supplementary
  sheet, and a log INFO aggregate carrying the suspect count) - suspects are
  NEVER removed (over-taxing on uncertainty is the safe direction);
- per-caller per-lot INFO/WARNING logging.

The two-phase matching + removal + the single aggregate summary INFO are
reused from :mod:`th_lot_matcher` (repo rule #119: this module and
``derivatives_filter`` are sibling TH-event->CG-lot matchers performing the
same conceptual operation). Do NOT reimplement two-phase matching here.

Pipeline placement (Design Invariant 4, Option D split fee pass):
``dedup -> remove_transaction_fees (early) -> OGR ->
correct_payment_proceeds -> flag_fee_suspects (late) -> aggregation ->
materiality``. Fee removal runs early so removed lots are not summed in
aggregation; suspect flagging runs late so any proceeds corrections are
already complete and cannot clobber the suspect flag or produce
contradictory joined reasons.
"""

from __future__ import annotations

import dataclasses
import logging
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path

from ...domain.jurisdiction import TaxJurisdictionConfig
from ...infrastructure.json_loader import load_guarded_json
from ...infrastructure.koinly_parser import (
    contains_non_latin_characters,
    parse_koinly_datetime,
    parse_koinly_decimal,
    read_koinly_rows,
)
from .entities import CryptoCapitalGainEntry, CryptoDecisionCounts, CryptoReviewEntry
from .th_lot_matcher import (
    IndexedLot,
    _format_summary_warning,
    match_lots,
)

logger = logging.getLogger(__name__)

# TH row ``Type`` value that marks an outbound crypto movement. Only these
# rows carry the asset movement that matches a CG disposal lot.
_FEE_TH_TYPE = "crypto_withdrawal"

# Koinly tags that mark a row as a trusted fee (Cost or Loan fee). The tag is
# the authority: no EUR amount threshold is applied to the tagged path.
_TAGGED_FEE_LABELS: frozenset[str] = frozenset({"Cost", "Loan fee"})

# Minute-precision timestamp format used by the matcher (mirrors derivatives).
_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M"


def _on_error_empty(path: Path, msg: str, exc: str) -> object:
    logger.warning("Failed to load JSON whitelist %s: %s (%s)", path, msg, exc)
    return {}


def _load_layer_1_major_chains() -> set[str]:
    """Load layer_1_major_chains from the popular crypto tokens JSON."""
    json_path = Path("docs/maintenance/tax/popular_crypto_tokens.json")
    if not json_path.exists():
        return set()
    data = load_guarded_json(
        json_path, size_limit=1024 * 1024, on_error=_on_error_empty
    )
    if not isinstance(data, dict):
        return set()
    return set(data.get("tokens", {}).get("layer_1_major_chains", []))


@dataclasses.dataclass(frozen=True)
class FeeThEvent:
    """A transaction/network fee event emitted from the Transaction History.

    Each event corresponds to one ``crypto_withdrawal`` row that is either
    explicitly tagged ``Cost``/``Loan fee`` (the ``tagged`` path, no EUR
    threshold) or an untagged whitelisted withdrawal whose ``Net Value (EUR)``
    is ``<=`` the per-token ceiling (the ``tagged=False`` path). Both paths
    are gated by the TxHash co-occurrence guard (the event's ``tx_hash``
    appears at least twice in the TH CSV).

    Satisfies the :class:`tax_reporting.application.crypto.th_lot_matcher.ThEvent`
    protocol via the four read-only fields ``timestamp``/``asset``/``wallet``/
    ``amount``. The extra fields are consumed only by this module's per-lot
    logging (the matcher MUST NOT read them).

    Attributes:
        timestamp: Minute-precision ``%Y-%m-%d %H:%M`` string computed from the
            TH ``Date`` column (seconds truncated).
        asset: Raw ``Sent Currency`` (not normalized - the CG lot's ``asset``
            is the raw ticker too).
        wallet: Raw, UN-NORMALIZED ``Sending Wallet`` string so it exactly
            matches the raw ``lot.entry.wallet`` of the CG lot (r6 M1).
        amount: ``Sent Amount`` parsed via ``parse_koinly_decimal``.
        tagged: True for the trusted ``Cost``/``Loan fee`` path; False for the
            untagged-whitelisted path. Drives the per-lot log LEVEL
            (INFO for trusted tagged removals, DEBUG for untagged-whitelisted
            removals which can be genuine dust disposals; the untagged-whitelisted
            aggregate is INFO).
        tx_hash: The TH ``TxHash`` value (carried for the per-lot log so a
            cross-transaction wrong-lot match is visible during the release-gate
            spot-check; Design Invariant 7).
        net_value_eur: ``Net Value (EUR)`` parsed via ``parse_koinly_decimal``.
            Defaults to ``Decimal("0")`` when the fiat cell is blank/corrupted
            on a tagged row (the tag is the authority, not the fiat value).
    """

    timestamp: str
    asset: str
    wallet: str
    amount: Decimal
    tagged: bool
    tx_hash: str
    net_value_eur: Decimal
    is_embedded: bool = False


@dataclasses.dataclass(frozen=True)
class SuspectThEvent:
    """An unlisted-asset fee *suspect* surfaced (NOT removed) for review.

    Each event corresponds to one untagged ``crypto_withdrawal`` row whose
    ``Sent Currency`` is NOT a key in
    ``exclude_transaction_fee_max_eur_per_asset``, whose ``Net Value (EUR)``
    is ``<= max(per_asset.values())``, gated by the TxHash co-occurrence guard.
    The suspect stays taxable: it is surfaced via a ``review_required`` flag on
    its correlated CG lot (when one exists), a ``CryptoReviewEntry`` row, and a
    log INFO aggregate (the per-suspect ``logger.debug`` plus one
    ``Surfaced %d suspect untagged network fees`` INFO summary) so a legitimate
    gas token missing from the config can be discovered and added without
    under-tax risk.

    Satisfies the :class:`ThEvent` protocol via the four read-only fields.

    Attributes:
        timestamp: Minute-precision ``%Y-%m-%d %H:%M`` string.
        asset: Raw ``Sent Currency``.
        wallet: Raw, UN-NORMALIZED ``Sending Wallet`` string.
        amount: ``Sent Amount`` parsed via ``parse_koinly_decimal``.
        tx_hash: The TH ``TxHash`` value (for the per-suspect log).
        net_value_eur: ``Net Value (EUR)`` parsed via ``parse_koinly_decimal``.
    """

    timestamp: str
    asset: str
    wallet: str
    amount: Decimal
    tx_hash: str
    net_value_eur: Decimal


def _suspect_reason(asset: str) -> str:
    """Build the human-readable suspect review reason for ``asset``."""
    return (
        f"Possible untagged fee for unlisted asset {asset}; verify and add to "
        f"exclude_transaction_fee_max_eur_per_asset if this is a fee"
    )


def _identify_fee_and_suspect_events(
    transaction_history_file: Path, jurisdiction: TaxJurisdictionConfig
) -> tuple[list[FeeThEvent], list[SuspectThEvent]]:
    """Scan the TH CSV once to identify both fee and suspect events.

    Two passes over the materialized row list (``read_koinly_rows`` returns a
    ``list[dict[str, str]]``, so iterating twice is safe):

    - Pass 1: build a ``Counter`` of non-empty ``TxHash`` values for the
      co-occurrence guard.
    - Pass 2: iterate each ``crypto_withdrawal`` row, classifying it into the
      tagged-fee, untagged-whitelist-fee, or unlisted-suspect branch (or
      ignoring it). The body is wrapped in a specific ``try...except`` so a
      single malformed row is skipped with a warning rather than aborting the
      scan (repo Rule #9: catch specific exceptions, never broad ``Exception``).

    Args:
        transaction_history_file: Path to the Koinly transaction history CSV.
        jurisdiction: Tax jurisdiction config supplying the flag and the
            per-token ceiling map.

    Returns:
        Tuple of ``(fee_events, suspect_events)``. Both lists are empty when
        the flag is disabled or no rows match.
    """
    per_asset = jurisdiction.exclude_transaction_fee_max_eur_per_asset
    default_ceiling = jurisdiction.exclude_transaction_fee_default_max_eur
    layer_1_chains = _load_layer_1_major_chains()

    # Empty-dict WARNING (Medium M5): the flag is enabled but the whitelist is
    # empty. The tagged path is dict-INDEPENDENT and still filters; only the
    # untagged-whitelist and suspect branches are inert.
    if not per_asset and not layer_1_chains:
        logger.warning(
            "exclude_transaction_fees is enabled but "
            "exclude_transaction_fee_max_eur_per_asset and layer 1 chains are empty. Only tagged "
            "Cost/Loan fee withdrawals will be filtered; untagged whitelist "
            "and suspect checks are inert."
        )

    rows = read_koinly_rows(transaction_history_file)

    # Pass 1: TxHash frequency map for the co-occurrence guard.
    tx_hash_counts: Counter[str] = Counter(
        row.get("TxHash", "").strip()
        for row in rows
        if row.get("TxHash", "").strip()
    )

    # Compute the max ceiling ONCE. When per_asset is empty, default to 0 so
    # the suspect branch's ``<= max_ceiling`` predicate never fires (the
    # explicit ``if per_asset:`` guard below also short-circuits the branch,
    # but keeping a non-``max()``-on-empty-dict value is defense-in-depth).
    max_ceiling = max(per_asset.values()) if per_asset else Decimal("0")
    if layer_1_chains:
        max_ceiling = max(max_ceiling, default_ceiling)

    fee_events: list[FeeThEvent] = []
    suspect_events: list[SuspectThEvent] = []

    for row in rows:
        row_type = row.get("Type", "").strip()
        fee_amount_str = row.get("Fee Amount", "").strip()
        fee_currency = row.get("Fee Currency", "").strip()
        
        is_withdrawal = row_type == _FEE_TH_TYPE
        has_embedded_fee = bool(fee_amount_str) and bool(fee_currency)

        if not is_withdrawal and not has_embedded_fee:
            continue
        try:
            label = row.get("Tag", "").strip()
            tx_hash = row.get("TxHash", "").strip()
            # Co-occurrence guard applies to ALL three paths (tagged, untagged,
            # suspect): the event's TxHash must occur at least twice in TH.
            occurs_at_least_twice = bool(tx_hash) and tx_hash_counts[tx_hash] >= 2

            timestamp = parse_koinly_datetime(row["Date"]).strftime(_TIMESTAMP_FORMAT)
            wallet = row.get("Sending Wallet", "").strip()

            if is_withdrawal:
                sent_currency = row.get("Sent Currency", "").strip()
                amount = parse_koinly_decimal(row["Sent Amount"])
                
                if label in _TAGGED_FEE_LABELS:
                    # Tagged path: the explicit tag is the authority; no EUR
                    # threshold. Co-occurrence guard is relaxed for explicitly tagged Cost or Loan fee withdrawals.
                    # Parse Net Value (EUR) in a SEPARATE nested try/except so a
                    # corrupted fiat cell on a tagged row does NOT propagate
                    # into the outer try/except and drop the tagged row
                    # entirely. The tag is the authority, not the fiat value.
                    try:
                        net_value_eur = parse_koinly_decimal(
                            row.get("Net Value (EUR)", "")
                        )
                    except ValueError:
                        logger.warning(
                            "Tagged fee row has an unparseable Net Value (EUR) "
                            "cell; defaulting to 0 (the tag is the authority). "
                            "tx_hash=%s asset=%s",
                            tx_hash,
                            sent_currency,
                        )
                        net_value_eur = Decimal("0")
                    fee_events.append(
                        FeeThEvent(
                            timestamp=timestamp,
                            asset=sent_currency,
                            wallet=wallet,
                            amount=amount,
                            tagged=True,
                            tx_hash=tx_hash,
                            net_value_eur=net_value_eur,
                        )
                    )
                elif not label and (sent_currency in per_asset or sent_currency in layer_1_chains):
                    # Untagged-whitelist path: asset is a dict key or in L1 chains. Apply the
                    # "MISSING" fiat-string guard so an explicit "0"/"0.00" (a
                    # valid zero-priced fee) is NOT skipped, but a genuinely blank
                    # cell IS skipped.
                    raw_val = row.get("Net Value (EUR)", "MISSING").strip()
                    if not raw_val or raw_val == "MISSING":
                        continue
                    net_value_eur = parse_koinly_decimal(raw_val)
                    ceiling = per_asset.get(sent_currency, default_ceiling)
                    if net_value_eur <= ceiling and occurs_at_least_twice:
                        fee_events.append(
                            FeeThEvent(
                                timestamp=timestamp,
                                asset=sent_currency,
                                wallet=wallet,
                                amount=amount,
                                tagged=False,
                                tx_hash=tx_hash,
                                net_value_eur=net_value_eur,
                            )
                        )
                elif (
                    not label
                    and sent_currency not in per_asset
                    and sent_currency not in layer_1_chains
                    and occurs_at_least_twice
                    and (per_asset or layer_1_chains)
                ):
                    # Suspect path: unlisted asset, TxHash co-occurring
                    # non-empty. Apply the same "MISSING" guard; if Net Value (EUR)
                    # is <= the max ceiling, record a suspect (NOT removed).
                    raw_val = row.get("Net Value (EUR)", "MISSING").strip()
                    if not raw_val or raw_val == "MISSING":
                        continue
                    net_value_eur = parse_koinly_decimal(raw_val)
                    if net_value_eur <= max_ceiling:
                        suspect_events.append(
                            SuspectThEvent(
                                timestamp=timestamp,
                                asset=sent_currency,
                                wallet=wallet,
                                amount=amount,
                                tx_hash=tx_hash,
                                net_value_eur=net_value_eur,
                            )
                        )
            
            if has_embedded_fee:
                embedded_amount = parse_koinly_decimal(fee_amount_str)
                if fee_currency in per_asset or fee_currency in layer_1_chains:
                    fee_events.append(
                        FeeThEvent(
                            timestamp=timestamp,
                            asset=fee_currency,
                            wallet=wallet,
                            amount=embedded_amount,
                            tagged=False,
                            tx_hash=tx_hash,
                            net_value_eur=Decimal("0"),
                            is_embedded=True,
                        )
                    )
                elif per_asset or layer_1_chains:
                    if Decimal("0") <= max_ceiling:
                        suspect_events.append(
                            SuspectThEvent(
                                timestamp=timestamp,
                                asset=fee_currency,
                                wallet=wallet,
                                amount=embedded_amount,
                                tx_hash=tx_hash,
                                net_value_eur=Decimal("0"),
                            )
                        )
        except (ValueError, KeyError, InvalidOperation) as exc:
            # Skip a single malformed row with a warning (repo Rule #9: catch
            # specific exception types, never broad ``Exception`` which would
            # hide a logic error like NameError/AttributeError).
            logger.warning(
                "Skipping malformed TH row during fee/suspect scan: %s. row=%s",
                exc,
                {k: row.get(k) for k in ("Date", "Type", "Tag", "Sent Amount", "TxHash")},
            )

    return fee_events, suspect_events


def _log_fee_removals(
    matched_metadata: list[tuple[IndexedLot[CryptoCapitalGainEntry], str, FeeThEvent]],
) -> None:
    """Per-lot INFO/DEBUG logs for fee-matched CG lot removals + ONE aggregate INFO.

    Trusted tagged-fee removals log at INFO. Embedded-fee removals log at INFO.
    Untagged-whitelisted removals log the per-tx_hash detail at DEBUG (asset +
    ``Net Value (EUR)`` + TxHash), then ONE aggregate INFO collapses them into
    a count + per-asset breakdown. The aggregate is a PURE INFO demotion (Task
    5 / r2 Finding 2): the untagged-whitelisted subset is STRICTLY CONTAINED in
    ``filtered_metadata`` (the W7 iterate), so the per-row "verify network fee"
    signal is carried by W7's branch-aware reason (Task 7) on the single review
    row the lot already gets from W7 - W8 owns NO review surface. The per-tx_hash
    detail moves to DEBUG; the single aggregate moves to INFO. This is a
    group-collapse (pattern I), DISTINCT from the J/K/L downgrade: the single
    aggregate now sits at INFO while the per-row lines stay at DEBUG.

    Reads lot fields THROUGH ``lot.entry`` (r8 M1): ``lot`` is the
    :class:`IndexedLot` wrapper, not the bare entry; the date field is
    ``disposal_timestamp``, not ``date``.

    Called once per run from :func:`remove_transaction_fees` after the existing
    dedup-summary INFO (W7); this aggregate is an INFO emit from this call (W8).
    The dedup summary covers ALL removals; this aggregate covers only the
    untagged-whitelisted subset that needs per-row verification.
    """
    untagged_whitelisted_by_asset: Counter[str] = Counter()
    for lot, _match_type, event in matched_metadata:
        if event.tagged:
            logger.info(
                "Removed fee-matched CG lot: timestamp=%s asset=%s wallet=%s "
                "amount=%s tx_hash=%s tagged=%s",
                lot.entry.disposal_timestamp,
                lot.entry.asset,
                lot.entry.wallet,
                lot.entry.amount,
                event.tx_hash,
                event.tagged,
            )
        elif getattr(event, "is_embedded", False):
            logger.info(
                "Removed embedded fee disposal for %s (tx_hash=%s)",
                event.asset,
                event.tx_hash,
            )
        else:
            logger.debug(
                "Removed untagged-whitelisted fee disposal for %s (Net Value "
                "%s EUR, tx_hash=%s) - verify this is a network fee, not a "
                "real disposal",
                event.asset,
                event.net_value_eur,
                event.tx_hash,
            )
            untagged_whitelisted_by_asset[event.asset] += 1

    if untagged_whitelisted_by_asset:
        total = sum(untagged_whitelisted_by_asset.values())
        logger.info(
            "Removed %d untagged-whitelisted fee disposal(s) (%s); "
            "per-tx_hash detail at DEBUG; verify each is a network fee, not a "
            "real disposal",
            total,
            ", ".join(
                f"{asset}: {count}"
                for asset, count in sorted(untagged_whitelisted_by_asset.items())
            ),
        )


def remove_transaction_fees(  # noqa: PLR0912, PLR0915
    *,
    capital_entries: list[CryptoCapitalGainEntry],
    transaction_history_file: Path | None,
    jurisdiction: TaxJurisdictionConfig | None,
    review_entries: list[CryptoReviewEntry] | None = None,
    decision_counts: CryptoDecisionCounts | None = None,
) -> tuple[list[CryptoCapitalGainEntry], list[SuspectThEvent]]:
    """Remove tagged/untagged-whitelist fee-matched CG lots (early pass).

    Gate: returns ``(capital_entries, [])`` unchanged when ``jurisdiction`` is
    ``None``, the flag ``exclude_transaction_fees`` is False, or
    ``transaction_history_file`` is None (Design Invariant 6).

    Scans the TH CSV via :func:`_identify_fee_and_suspect_events`, then removes
    the fee-matched CG lots via the shared matcher
    (:func:`th_lot_matcher.remove_matched_lots`, ``domain_label="fee"``) and
    runs the fee module's own per-lot log over the matched metadata. The
    suspect events are returned (NOT consumed here) for the late
    :func:`flag_fee_suspects` pass.

    Args:
        capital_entries: Capital-gains entries (FIFO lots) AFTER derivatives
            dedup. Fee removal must precede OGR/aggregation.
        transaction_history_file: Path to the Koinly transaction history CSV,
            or ``None``.
        jurisdiction: Tax jurisdiction config supplying the gating flag and the
            per-token ceiling map.
        review_entries: Optional list to receive one :class:`CryptoReviewEntry`
            per removed/surplus/malformed lot (INV-3 default ``None`` so the ~30
            existing test callers stay green). The removed-lot reason is
            BRANCH-AWARE on the matched :class:`FeeThEvent` (tagged/embedded/
            untagged-whitelisted); the untagged-whitelisted branch carries the
            W8 "verify network fee" suffix (r2 Finding 2: the W8 signal is merged
            onto the single W7 row, avoiding the double-count).
        decision_counts: Optional mutable accumulator whose
            ``fee_dedup_removed`` field is SET (not incremented) to
            ``len(filtered_metadata)`` once per call (INV-4a: each field is
            owned by exactly one pass; NEVER set in :func:`_log_fee_removals`).

    Returns:
        Tuple of ``(remaining_entries, suspect_events)``. ``remaining_entries``
        preserves original order minus the removed fee lots.
    """
    if (
        jurisdiction is None
        or not jurisdiction.exclude_transaction_fees
        or transaction_history_file is None
    ):
        return capital_entries, []

    fee_events, suspect_events = _identify_fee_and_suspect_events(
        transaction_history_file, jurisdiction
    )

    if not fee_events:
        return capital_entries, suspect_events

    result = match_lots(capital_entries, fee_events)

    per_asset = jurisdiction.exclude_transaction_fee_max_eur_per_asset
    default_ceiling = jurisdiction.exclude_transaction_fee_default_max_eur
    layer_1_chains = _load_layer_1_major_chains()
    matched_metadata_by_index = {
        m[0].index: m for m in result.matched_metadata
    }

    embedded_event_proceeds: dict[int, Decimal] = {}
    for match in result.matched_metadata:
        lot, _match_type, event = match
        if event.is_embedded:
            event_id = id(event)
            embedded_event_proceeds[event_id] = embedded_event_proceeds.get(event_id, Decimal("0")) + lot.entry.proceeds_eur

    remaining_entries: list[CryptoCapitalGainEntry] = []
    filtered_metadata: list[tuple[IndexedLot[CryptoCapitalGainEntry], str, FeeThEvent]] = []

    for index, entry in enumerate(capital_entries):
        if index not in matched_metadata_by_index:
            remaining_entries.append(entry)
            continue

        match = matched_metadata_by_index[index]
        _lot, _match_type, event = match

        if event.is_embedded:
            ceiling = per_asset.get(event.asset, default_ceiling if event.asset in layer_1_chains else Decimal("0"))
            if embedded_event_proceeds[id(event)] > ceiling:
                remaining_entries.append(entry)
            else:
                filtered_metadata.append(match)
        else:
            filtered_metadata.append(match)

    exact_count = 0
    range_count = 0
    total_proceeds = Decimal("0")
    total_gain = Decimal("0")
    for lot, match_type, _event in filtered_metadata:
        if match_type == "exact":
            exact_count += 1
        else:
            range_count += 1
        total_proceeds += lot.entry.proceeds_eur
        total_gain += lot.entry.gain_loss_eur

    surplus_total = Decimal("0")
    for lot in result.surplus_lots:
        surplus_total += lot.entry.amount

    summary = _format_summary_warning(
        domain_label="fee",
        total_removed=len(filtered_metadata),
        exact_count=exact_count,
        range_count=range_count,
        total_proceeds=total_proceeds,
        total_gain=total_gain,
        surplus_lots=result.surplus_lots,
        surplus_total_amount=surplus_total,
        malformed_input_lots=result.malformed_input_lots,
    )
    # Demoted from WARNING -> INFO (Task 7): the per-row detail now surfaces in
    # the user-facing extract via the threaded ``review_entries`` list (INV-1 no
    # signal loss). The per-row DEBUG audit trail is preserved in
    # :func:`_log_fee_removals`.
    logger.info(summary)

    # Surface the per-row detail in the user-facing extract (INV-1 no signal
    # loss). INV-3: guarded so the ~30 existing test callers that omit
    # ``review_entries`` stay green. Removed-lot reasons are BRANCH-AWARE on the
    # matched ``FeeThEvent`` (tagged -> embedded -> untagged-whitelisted, in that
    # order). The untagged-whitelisted branch carries the W8 "verify network
    # fee" suffix and sets ``is_suspicious=True`` (r2 Finding 2: the W8 signal is
    # merged onto the single W7 row the lot already gets, avoiding the
    # double-count; the untagged-whitelisted subset is STRICTLY CONTAINED in
    # ``filtered_metadata``).
    if review_entries is not None:
        for lot, _match_type, event in filtered_metadata:
            if event.tagged:
                removed_reason = (
                    f"Fee CG dedup: removed lot (tagged {event.tagged})"
                )
                removed_suspicious = False
            elif event.is_embedded:
                removed_reason = "Fee CG dedup: removed lot (embedded fee)"
                removed_suspicious = False
            else:
                removed_reason = (
                    f"Fee CG dedup: removed untagged-whitelisted fee disposal "
                    f"(Net Value {event.net_value_eur} EUR, tx_hash={event.tx_hash}) "
                    f"- verify network fee, not real disposal"
                )
                removed_suspicious = True
            review_entries.append(
                CryptoReviewEntry(
                    source_section="capital_gains",
                    date=lot.entry.disposal_timestamp or lot.entry.disposal_date,
                    asset=lot.entry.asset,
                    platform=lot.entry.wallet,
                    review_reason=removed_reason,
                    is_suspicious=removed_suspicious,
                )
            )
        for lot in result.surplus_lots:
            review_entries.append(
                CryptoReviewEntry(
                    source_section="capital_gains",
                    date=lot.entry.disposal_timestamp or lot.entry.disposal_date,
                    asset=lot.entry.asset,
                    platform=lot.entry.wallet,
                    review_reason=(
                        "Fee CG dedup: Surplus lot - may indicate a missed FIFO "
                        "split; review the listed key"
                    ),
                    is_suspicious=True,
                )
            )
        for entry in result.malformed_input_lots:
            review_entries.append(
                CryptoReviewEntry(
                    source_section="capital_gains",
                    date=entry.disposal_timestamp or entry.disposal_date,
                    asset=entry.asset,
                    platform=entry.wallet,
                    review_reason=(
                        f"Fee CG dedup: Malformed-input lot (non-positive amount "
                        f"{entry.amount}); investigate the source export"
                    ),
                    is_suspicious=True,
                )
            )

    # INV-4a: set-not-increment; this pass owns fee_dedup_removed. NEVER set in
    # :func:`_log_fee_removals` (W8 is a pure INFO demotion that owns NO review
    # surface and NO count).
    if decision_counts is not None:
        decision_counts.fee_dedup_removed = len(filtered_metadata)

    _log_fee_removals(filtered_metadata)

    return remaining_entries, suspect_events


def _surface_suspects(
    capital_entries: list[CryptoCapitalGainEntry],
    suspect_events: list[SuspectThEvent],
    review_entries: list[CryptoReviewEntry],
) -> list[CryptoCapitalGainEntry]:
    """Match suspects to CG lots (no removal), flag matches, append review rows.

    Calls :func:`match_lots` (match-only; the matcher emits NO summary here).
    Builds ``matched_indices`` from the positional ``IndexedLot.index`` (r7 M6)
    and rebuilds the entries via a LIST COMPREHENSION (r9 impl - a conditional
    expression used as a statement is invalid Python AND would silently drop
    the replaced entry, defeating flag propagation).

    For every suspect event (matched or not):
    - appends a ``CryptoReviewEntry`` (``source_section="capital_gains"`` when
      it matched a CG lot, else the new ``"transaction_history"``) to the
      threaded ``review_entries`` list in place;
    - logs a ``logger.debug`` naming the asset + ``Net Value (EUR)`` (pattern D:
      per-row detail preserved at DEBUG in the file; the in-loop WARNING was
      downgraded to avoid ~110 duplicate console warnings whose content is
      already shown in the Excel review list).

    Suspects are NOT removed (Design Invariant 3). A separate aggregate
    suspect INFO is emitted to satisfy the plan.

    Args:
        capital_entries: Capital-gains entries AFTER payment-proceeds (the late
            pass runs after proceeds corrections are complete).
        suspect_events: Suspect events captured by the early
            :func:`remove_transaction_fees` pass.
        review_entries: The threaded Crypto Supplementary review list (mutated
            in place).

    Returns:
        A rebuilt list with ``review_required=True`` and the suspect reason on
        every CG-matched suspect lot. Unmatched entries are returned unchanged.
    """
    result = match_lots(capital_entries, suspect_events)

    matched_indices = {ml.index for ml, _mt, _ev in result.matched_metadata}
    # Map each suspect event to whether it matched a CG lot, keyed by identity
    # (a suspect can match multiple lots; one row per event is appended).
    matched_event_ids = {id(ev) for _ml, _mt, ev in result.matched_metadata}

    flagged = [
        (
            dataclasses.replace(
                entry,
                review_required=True,
                review_reason=(
                    f"{entry.review_reason}; {_suspect_reason(entry.asset)}"
                    if entry.review_reason
                    else _suspect_reason(entry.asset)
                ),
            )
            if i in matched_indices
            else entry
        )
        for i, entry in enumerate(capital_entries)
    ]

    for suspect in suspect_events:
        matched = id(suspect) in matched_event_ids
        review_entries.append(
            CryptoReviewEntry(
                source_section="capital_gains" if matched else "transaction_history",
                date=suspect.timestamp,
                asset=suspect.asset,
                platform=suspect.wallet,
                review_reason=_suspect_reason(suspect.asset),
                is_suspicious=contains_non_latin_characters(suspect.asset),
            )
        )
        logger.debug(
            "Possible untagged fee for unlisted asset %s (Net Value %s EUR); "
            "not filtered. Add to exclude_transaction_fee_max_eur_per_asset if "
            "this is a fee.",
            suspect.asset,
            suspect.net_value_eur,
        )

    if suspect_events:
        logger.info("Surfaced %d suspect untagged network fees for manual review", len(suspect_events))

    return flagged


def flag_fee_suspects(
    *,
    capital_entries: list[CryptoCapitalGainEntry],
    suspect_events: list[SuspectThEvent],
    review_entries: list[CryptoReviewEntry],
) -> list[CryptoCapitalGainEntry]:
    """Flag CG-matched fee suspects and append review rows (late pass).

    Gate: returns ``capital_entries`` unchanged when ``suspect_events`` is
    empty. Runs AFTER ``correct_payment_proceeds`` and BEFORE aggregation
    (Design Invariant 4, Option D) so any proceeds corrections are complete
    and cannot clobber the suspect flag or produce contradictory joined
    reasons.

    Args:
        capital_entries: Capital-gains entries AFTER payment proceeds.
        suspect_events: Suspect events captured by the early
            :func:`remove_transaction_fees` pass.
        review_entries: The threaded Crypto Supplementary review list (mutated
            in place by :func:`_surface_suspects`).

    Returns:
        The (possibly rebuilt) capital entries list with suspect flags applied.
    """
    if not suspect_events:
        return capital_entries

    return _surface_suspects(capital_entries, suspect_events, review_entries)
