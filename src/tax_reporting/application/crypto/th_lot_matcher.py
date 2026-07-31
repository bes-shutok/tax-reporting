"""Shared two-phase TH-event to CG-lot matcher.

Promotes the matching primitives previously inlined in
``derivatives_filter`` so sibling matchers (the fee filter; repo rule #119)
perform the same conceptual operation without diverging. The matcher reads
only ``event.timestamp`` / ``event.asset`` / ``event.wallet`` /
``event.amount`` and is generic over the concrete event type via the
:class:`ThEvent` protocol (a derivatives event carries an extra ``.label``,
a fee event carries extra ``.tagged``/``.tx_hash``/``.net_value_eur`` -
neither is read here).

Logging asymmetry (Design Invariant 2):
:func:`remove_matched_lots` logs the single removal summary INFO (demoted
from WARNING in the relocate-crypto-warnings plan) because it owns the
removal semantic and the caller-passed ``logger`` carries the caller's
module name. The per-row detail (removed/surplus/malformed) surfaces in the
user-facing extract via review rows the CALLER builds from the returned
:class:`MatcherResult` (M4: the matcher is domain-neutral and owns neither
review rows nor counts). :func:`match_lots` emits no logging: a match is
not intrinsically a removal (a caller may flag instead of remove), so each
caller owns its own summary and per-lot logging.

Design notes
------------
- Phase 1 (exact match): for each event, pop one lot from the per-key deque
  keyed by ``(timestamp, asset, wallet, amount_6dp)``.
- Phase 2 (contiguous-range fallback): for each unmatched event, scan a
  sliding window over lots at the same ``(timestamp, asset, wallet)`` for a
  contiguous range summing to the event amount within
  ``_RANGE_TOLERANCE_SCALE * range_size``. Tolerance is recomputed after
  every shrink and the shrink bound uses ``left < right``
  so a single-element window stays a candidate.
- Per-lot INFO logging is CALLER-owned: the matcher returns
  ``matched_metadata`` so each caller logs per-lot with its own wording.
"""

from __future__ import annotations

import dataclasses
import logging
from collections import deque
from collections.abc import Sequence
from decimal import Decimal
from typing import TYPE_CHECKING, Generic, Protocol, TypeVar

from .entities import CryptoCapitalGainEntry, CryptoDecisionCounts

if TYPE_CHECKING:
    from .entities import CryptoReviewEntry

# Per-lot rounding for the exact-match phase: both CG and TH amounts are
# quantized to 6 decimals before equality check, absorbing Koinly rounding
# differences without introducing a fuzzy tolerance window.
_EXACT_AMOUNT_QUANTUM = Decimal("0.000001")
# Per-range tolerance scale for the contiguous-range fallback. The tolerance
# is `_RANGE_TOLERANCE_SCALE * range_size` (10x the per-lot rounding error,
# absorbing accumulation when summing N independently-rounded lots).
_RANGE_TOLERANCE_SCALE = Decimal("0.00001")

# Maximum sample size for the (timestamp, asset, wallet, amount) and
# (timestamp, asset, amount) tuples printed in the summary INFO. Keeps
# the warning readable while still surfacing the offending keys.
_SUMMARY_SAMPLE_SIZE = 3


class ThEvent(Protocol):
    """Structural contract for Transaction-History events paired to CG lots.

    The matcher keys lots to events by ``(timestamp, asset, wallet, amount)``
    at minute precision. Concrete event types may carry additional fields
    (derivatives ``.label``, fee ``.tagged``/``.tx_hash``/``.net_value_eur``)
    that the matcher MUST NOT read - they are consumed only by the
    caller-owned per-lot logging.

    The four attributes are declared as read-only properties so frozen
    dataclasses (``DerivativesThEvent``, ``FeeThEvent``) satisfy the protocol
    structurally under basedpyright's protocol-mutability check: a frozen
    dataclass exposes read-only attributes, and a protocol with writable
    attributes is not satisfied by a read-only implementation.
    """

    @property
    def timestamp(self) -> str: ...

    @property
    def asset(self) -> str: ...

    @property
    def wallet(self) -> str: ...

    @property
    def amount(self) -> Decimal: ...


# A single TypeVar parameterizes BOTH the events input and the MatcherResult
# generic, so basedpyright infers the concrete event type from the caller's
# `events: list[DerivativesThEvent]` (resp. `list[FeeThEvent]`) and the
# caller's access to event-specific fields (e.g. `event.label`) type-checks
# with no local annotation (r7 L8 / r6 M2).
E = TypeVar("E", bound=ThEvent)


def _quantize_amount_6dp(amount: Decimal) -> Decimal:
    """Quantize a Decimal amount to 6 decimal places for exact-match keys.

    Args:
        amount: Raw amount from a CG lot or TH event.

    Returns:
        Amount quantized to 6 decimal places using ROUND_HALF_EVEN (Python's
        default for ``Decimal.quantize`` without an explicit context).
    """
    return amount.quantize(_EXACT_AMOUNT_QUANTUM)


@dataclasses.dataclass(frozen=True)
class IndexedLot:
    """A CryptoCapitalGainEntry paired with its original list index.

    The matcher tracks removals by index in a set; this wrapper keeps the
    association stable across sorting and filtering. ``index`` is the
    positional index INTO the original ``capital_entries`` list.
    """

    index: int
    entry: CryptoCapitalGainEntry


def _find_contiguous_range(
    candidates: Sequence[IndexedLot], target: Decimal
) -> list[IndexedLot] | None:
    """Sliding-window search for a contiguous range summing to ``target``.

    Lots in ``candidates`` are already sorted by ``(acquisition_date, index)``
    so a contiguous window in this list corresponds to a contiguous block in
    FIFO acquisition order, which is what a single disposal consumes. Returns
    the first (lowest starting index) matching range, or ``None`` if no window
    sums to ``target`` within ``_RANGE_TOLERANCE_SCALE * range_size``.

    Args:
        candidates: Unmatched CG lots at the same
            ``(timestamp, asset, wallet)`` key, sorted by acquisition_date.
        target: Target amount (the TH event's amount).

    Returns:
        The matching contiguous range (list of :class:`IndexedLot`), or
        ``None``.
    """
    n = len(candidates)
    if n == 0:
        return None

    left = 0
    running_sum = Decimal("0")
    for right in range(n):
        running_sum += candidates[right].entry.amount
        range_size = right - left + 1
        tolerance = _RANGE_TOLERANCE_SCALE * Decimal(range_size)
        # Shrink the window from the left while the running sum exceeds the
        # target plus tolerance and the window has more than one lot.
        while running_sum > target + tolerance and left < right:
            running_sum -= candidates[left].entry.amount
            left += 1
            range_size = right - left + 1
            tolerance = _RANGE_TOLERANCE_SCALE * Decimal(range_size)
        # Check if the current window matches the target within tolerance.
        if abs(running_sum - target) <= tolerance:
            return list(candidates[left : right + 1])

    return None


def _build_candidates(
    capital_entries: Sequence[CryptoCapitalGainEntry],
) -> tuple[list[IndexedLot], list[CryptoCapitalGainEntry]]:
    """Build the sorted candidate list and the malformed-input skip list.

    Entries without ``disposal_timestamp`` are silently skipped (they predate
    the timestamp-field introduction or come from non-FIFO sources). Entries
    with non-positive ``amount`` are collected into the malformed-input list
    for inclusion in the summary INFO. Surviving candidates are sorted by
    ``(timestamp, asset, wallet, acquisition_date, index)`` for determinism.
    """
    candidates: list[IndexedLot] = []
    malformed: list[CryptoCapitalGainEntry] = []
    for index, entry in enumerate(capital_entries):
        if entry.disposal_timestamp is None:
            continue
        if entry.amount <= 0:
            malformed.append(entry)
            continue
        candidates.append(IndexedLot(index=index, entry=entry))

    candidates.sort(
        key=lambda lot: (
            lot.entry.disposal_timestamp or "",
            lot.entry.asset,
            lot.entry.wallet,
            lot.entry.acquisition_date,
            lot.index,
        )
    )
    return candidates, malformed


def _exact_match_key(lot_entry: CryptoCapitalGainEntry) -> tuple[str, str, str, Decimal]:
    """Build the exact-match key ``(timestamp, asset, wallet, amount_6dp)``."""
    return (
        lot_entry.disposal_timestamp or "",
        lot_entry.asset,
        lot_entry.wallet,
        _quantize_amount_6dp(lot_entry.amount),
    )


def _run_phase1_exact_match(
    candidates: list[IndexedLot],
    sorted_events: Sequence[E],
) -> tuple[
    list[tuple[IndexedLot, E]],
    list[E],
    dict[tuple[str, str, str, Decimal], deque[IndexedLot]],
]:
    """Phase 1: pop one lot per event from per-key deques.

    Returns the (matched_pairs, unmatched_events, exact_match_deques) tuple.
    The deques are returned so the caller can detect surplus lots.
    """
    deques: dict[tuple[str, str, str, Decimal], deque[IndexedLot]] = {}
    for lot in candidates:
        deques.setdefault(_exact_match_key(lot.entry), deque()).append(lot)

    matched: list[tuple[IndexedLot, E]] = []
    unmatched: list[E] = []
    for event in sorted_events:
        key = (
            event.timestamp,
            event.asset,
            event.wallet,
            _quantize_amount_6dp(event.amount),
        )
        bucket = deques.get(key)
        if bucket:
            matched.append((bucket.popleft(), event))
        else:
            unmatched.append(event)
    return matched, unmatched, deques


def _run_phase2_contiguous_range(
    candidates: list[IndexedLot],
    unmatched_events: Sequence[E],
    matched_indices: set[int],
) -> list[tuple[IndexedLot, E]]:
    """Phase 2: sliding-window fallback for unmatched events.

    For each unmatched event, scan the available lots at the same
    ``(timestamp, asset, wallet)`` (sorted by acquisition_date) for a
    contiguous range summing to the event amount within tolerance.
    """
    group_key_to_lots: dict[tuple[str, str, str], list[IndexedLot]] = {}
    for lot in candidates:
        if lot.index in matched_indices:
            continue
        group_key = (
            lot.entry.disposal_timestamp or "",
            lot.entry.asset,
            lot.entry.wallet,
        )
        group_key_to_lots.setdefault(group_key, []).append(lot)

    range_matched: list[tuple[IndexedLot, E]] = []
    for event in unmatched_events:
        group_key = (event.timestamp, event.asset, event.wallet)
        group_lots = group_key_to_lots.get(group_key, [])
        available = [lot for lot in group_lots if lot.index not in matched_indices]
        if not available:
            continue
        match_range = _find_contiguous_range(available, event.amount)
        if match_range is None:
            continue
        for lot in match_range:
            matched_indices.add(lot.index)
            range_matched.append((lot, event))
    return range_matched


def _collect_surplus_lots(
    deques: dict[tuple[str, str, str, Decimal], deque[IndexedLot]],
    matched_indices: set[int],
) -> list[IndexedLot]:
    """Surplus = leftover lots at any exact-match key after all events consumed."""
    surplus: list[IndexedLot] = []
    for bucket in deques.values():
        for lot in bucket:
            if lot.index not in matched_indices:
                surplus.append(lot)
    return surplus


@dataclasses.dataclass
class MatcherResult(Generic[E]):
    """Outcome of a matcher pass, generic over the event type.

    Attributes:
        remaining_entries: ``capital_entries`` after the operation. For
            :func:`match_lots` this equals ``capital_entries`` unchanged
            (match-only). For :func:`remove_matched_lots` the matched lots
            are removed in original order.
        matched_metadata: Triples ``(lot, match_type, event)`` for each lot
            consumed by an event, where ``match_type`` is ``"exact"`` or
            ``"range"``. Each caller logs per-lot with its own wording.
        surplus_lots: Lots left at an exact-match key after all events were
            consumed (a count-mismatch / collision signal).
        malformed_input_lots: CG entries skipped for having a non-positive
            amount (surfaced in the removal summary INFO).
        unmatched_events: Events that found no CG lot. ``remove_matched_lots``
            does NOT warn for these; the caller owns that decision (fees may
            legitimately be unmatched).
    """

    remaining_entries: list[CryptoCapitalGainEntry]
    matched_metadata: list[tuple[IndexedLot, str, E]]
    surplus_lots: list[IndexedLot]
    malformed_input_lots: list[CryptoCapitalGainEntry]
    unmatched_events: list[E]


def match_lots(
    capital_entries: Sequence[CryptoCapitalGainEntry],
    events: Sequence[E],
) -> MatcherResult[E]:
    """Pure two-phase matching algorithm (no removal, no logging).

    Runs phase 1 (exact match) then phase 2 (contiguous-range fallback) over
    ``capital_entries`` paired against ``events``. ``remaining_entries`` is
    returned UNCHANGED (equal to ``capital_entries``); callers that need
    removal use :func:`remove_matched_lots`, callers that need match-only
    (e.g. suspect flagging) consume ``matched_metadata`` directly.

    Args:
        capital_entries: Capital-gains entries (FIFO lots). Entries without a
            ``disposal_timestamp`` or with non-positive amount are skipped
            from matching (the latter land in ``malformed_input_lots``).
        events: Transaction-history events. Empty list returns the input
            unchanged with empty match metadata.

    Returns:
        A :class:`MatcherResult` with ``remaining_entries == capital_entries``.
    """
    candidates, malformed_input_lots = _build_candidates(capital_entries)

    sorted_events = sorted(
        events,
        key=lambda ev: (ev.timestamp, ev.asset, ev.wallet, ev.amount),
    )

    matched_indices: set[int] = set()
    phase1_matched, unmatched_events, exact_match_deques = _run_phase1_exact_match(
        candidates, sorted_events
    )
    for lot, _event in phase1_matched:
        matched_indices.add(lot.index)

    phase2_matched = _run_phase2_contiguous_range(
        candidates, unmatched_events, matched_indices
    )

    matched_metadata: list[tuple[IndexedLot, str, E]] = [
        *((lot, "exact", event) for lot, event in phase1_matched),
        *((lot, "range", event) for lot, event in phase2_matched),
    ]

    surplus_lots = _collect_surplus_lots(exact_match_deques, matched_indices)

    # match_lots does NOT remove lots: callers that need removal use
    # remove_matched_lots; callers that need match-only read matched_metadata.
    return MatcherResult(
        remaining_entries=list(capital_entries),
        matched_metadata=matched_metadata,
        surplus_lots=surplus_lots,
        malformed_input_lots=malformed_input_lots,
        unmatched_events=unmatched_events,
    )


def _format_summary_warning(  # noqa: PLR0913
    *,
    domain_label: str,
    total_removed: int,
    exact_count: int,
    range_count: int,
    total_proceeds: Decimal,
    total_gain: Decimal,
    surplus_lots: list[IndexedLot],
    surplus_total_amount: Decimal,
    malformed_input_lots: list[CryptoCapitalGainEntry],
) -> str:
    """Assemble the single WARNING summary string covering all signal types.

    ``domain_label`` parameterizes the title: ``f"{domain_label.title()} CG
    dedup summary"`` so ``domain_label="derivatives"`` reproduces the exact
    historical title literal and
    ``domain_label="fee"`` yields ``"Fee CG dedup summary"``.
    """
    parts: list[str] = [
        f"{domain_label.title()} CG dedup summary: removed {total_removed} lots "
        f"(exact={exact_count}, range={range_count}, "
        f"aggregate_proceeds_eur={total_proceeds}, "
        f"aggregate_gain_eur={total_gain})",
        f"{len(surplus_lots)} surplus lots (total_amount={surplus_total_amount})",
    ]
    if surplus_lots:
        surplus_sample = sorted(
            {
                (
                    lot.entry.disposal_timestamp,
                    lot.entry.asset,
                    lot.entry.wallet,
                    lot.entry.amount,
                )
                for lot in surplus_lots
            }
        )[:_SUMMARY_SAMPLE_SIZE]
        parts.append(
            "surplus lots may indicate a missed FIFO split - review the listed keys: "
            + "; ".join(str(tpl) for tpl in surplus_sample)
        )
    parts.append(f"{len(malformed_input_lots)} malformed-input lots")
    if malformed_input_lots:
        malformed_sample = sorted(
            {
                (entry.disposal_timestamp, entry.asset, entry.amount)
                for entry in malformed_input_lots
                if entry.disposal_timestamp is not None
            }
        )[:_SUMMARY_SAMPLE_SIZE]
        parts.append(
            "malformed-input lots have non-positive amounts - investigate the source export: "
            + "; ".join(str(tpl) for tpl in malformed_sample)
        )
    return ". ".join(parts)


def remove_matched_lots(  # noqa: PLR0913
    capital_entries: Sequence[CryptoCapitalGainEntry],
    events: Sequence[E],
    *,
    domain_label: str,
    logger: logging.Logger,
    review_entries: list[CryptoReviewEntry] | None = None,
    decision_counts: CryptoDecisionCounts | None = None,
) -> MatcherResult[E]:
    """Match events to CG lots, remove the matched lots, emit one summary INFO.

    Domain-neutral (M4): the matcher owns ONLY the match + the single summary
    INFO emit. It does NOT append review-entry rows and does NOT write any
    ``decision_counts.*dedup`` field - those are caller-owned. Each
    caller owns its own review rows and count (mirroring how
    ``fee_filter.remove_transaction_fees`` owns the fee rows + the
    ``fee_dedup_removed`` count): the derivatives caller
    (:func:`derivatives_filter.remove_derivatives_flagged_lots`) appends the
    removed/surplus/malformed review rows and sets its dedup-removed count
    from the returned ``MatcherResult``.

    Built on :func:`match_lots`. Removes the matched lots from
    ``remaining_entries`` (original order preserved) and emits exactly ONE
    summary INFO via the caller-passed ``logger`` (so the record's
    ``r.name`` is the caller's module logger, not this module's). The summary
    title is parameterized by ``domain_label`` (``f"{domain_label.title()} CG
    dedup summary"``).

    The summary was previously a WARNING; it was demoted to INFO because the
    per-row detail now surfaces in the user-facing extract (via the caller's
    review rows).

    Does NOT warn for unmatched events: the caller owns that decision (fees
    may legitimately be unmatched; derivatives always warn). The matcher
    returns the unmatched events in ``MatcherResult.unmatched_events``.

    Args:
        capital_entries: Capital-gains entries (FIFO lots).
        events: Transaction-history events. Empty list returns the input
            unchanged with NO summary INFO.
        domain_label: Lower-case domain identifier (e.g. ``"derivatives"``,
            ``"fee"``) parameterizing the summary title.
        logger: The CALLER's module logger; the summary INFO record carries
            ``logger.name`` so the caller's logger-name assertions hold.
        review_entries: Backward-compat no-op (INV-3 default ``None``). The
            matcher appends nothing; callers own their review rows.
        decision_counts: Backward-compat no-op (INV-3 default ``None``). The
            matcher writes no count field; callers own their counts.

    Returns:
        A :class:`MatcherResult` with matched lots removed from
        ``remaining_entries`` and carrying the ``matched_metadata`` /
        ``surplus_lots`` / ``malformed_input_lots`` lists the caller uses to
        build its own review rows + count.
    """
    result = match_lots(capital_entries, events)

    matched_metadata = result.matched_metadata
    surplus_lots = result.surplus_lots
    malformed_input_lots = result.malformed_input_lots

    if not events:
        # No events: no removals, no summary (callers pass an empty list as a
        # gate-failure no-op; a summary here would be a spurious warning).
        return result

    exact_count = 0
    range_count = 0
    total_proceeds = Decimal("0")
    total_gain = Decimal("0")
    for lot, match_type, _event in matched_metadata:
        if match_type == "exact":
            exact_count += 1
        else:
            range_count += 1
        total_proceeds += lot.entry.proceeds_eur
        total_gain += lot.entry.gain_loss_eur
    surplus_total = Decimal("0")
    for lot in surplus_lots:
        surplus_total += lot.entry.amount

    matched_indices = {lot.index for lot, _mt, _ev in matched_metadata}

    summary = _format_summary_warning(
        domain_label=domain_label,
        total_removed=len(matched_metadata),
        exact_count=exact_count,
        range_count=range_count,
        total_proceeds=total_proceeds,
        total_gain=total_gain,
        surplus_lots=surplus_lots,
        surplus_total_amount=surplus_total,
        malformed_input_lots=malformed_input_lots,
    )
    logger.info(summary)

    filtered = [
        entry
        for index, entry in enumerate(capital_entries)
        if index not in matched_indices
    ]

    return dataclasses.replace(
        result,
        remaining_entries=filtered,
    )
