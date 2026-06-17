"""Crypto derivatives capital-gains deduplication.

This module holds the per-disposal deduplication logic that removes
capital-gains lots corresponding to derivatives events already accounted for
in the Other Gains Report. Task 2 introduced the per-provider-per-year
label config loader; Task 4 introduces the TH scanner that emits one
``DerivativesThEvent`` per matching ``crypto_withdrawal`` row so the matcher
(Task 5) can pair events with CG lots at minute precision.

Design notes
------------
- The label set is small and stable per (provider, year). It is stored as
  JSON under `docs/tax/derivatives_labels/<provider>_<year>.json` so the
  labels can be updated without code changes.
- A *missing* config file degrades gracefully (warning plus empty set): the
  caller skips deduplication and the legacy behaviour is preserved. This is
  the only graceful-degradation path here.
- A *malformed* config file is a correctness hazard: silently skipping would
  leave double-counting in place. Invalid JSON, a missing
  ``derivatives_th_labels`` key, or a wrong value type all raise
  ``FileProcessingError`` so the user sees the problem immediately.
- The TH scanner does NOT deduplicate events: when two positions accrue the
  same funding fee at the same minute, both events are returned. The
  downstream matcher handles collisions deterministically.
- The CG lot removal uses two-phase matching (exact + contiguous-range
  fallback). Per-lot removals log at INFO; exactly one WARNING summary per
  call carries all aggregate signals (removals, surplus lots, malformed-input
  lots) per Design Invariant 15.
"""

from __future__ import annotations

import dataclasses
import json
import logging
from collections import deque
from decimal import Decimal
from pathlib import Path

from ...domain.exceptions import FileProcessingError
from ...domain.jurisdiction import TaxJurisdictionConfig
from ...infrastructure.koinly_parser import (
    normalize_asset_ticker,
    normalize_platform_name,
    parse_koinly_datetime,
    parse_koinly_decimal,
    read_koinly_rows,
)
from .classification import _REPOSITORY_ROOT
from .entities import CryptoCapitalGainEntry

logger = logging.getLogger(__name__)

# Max size of a derivatives-labels config file (1 MiB). Mirrors the size guard
# in classification._load_popular_crypto_tokens to bound the JSON read.
_MAX_LABELS_FILE_SIZE = 1 * 1024 * 1024


def _load_derivatives_labels_config_from_path(path: Path) -> frozenset[str]:
    """Load and validate a derivatives-labels config file at ``path``.

    Args:
        path: Absolute path to the JSON config file.

    Returns:
        Frozenset of TH Label strings that mark derivatives events.

    Raises:
        FileProcessingError: If the path is a symlink, the file exceeds the
            size limit, the JSON is malformed, the ``derivatives_th_labels``
            key is missing, or its value is not a list of strings.
    """
    # Security check: reject symlinks (mirrors classification._load_popular_crypto_tokens).
    if path.is_symlink():
        raise FileProcessingError(
            f"Derivatives labels config at {path} is a symlink - "
            "only regular files are accepted for security"
        )

    if not path.exists():
        # Silent return; the apply_derivatives_dedup caller emits a single
        # WARNING with the actionable remediation hint when labels is empty.
        # Logging here would double-warn for the same condition.
        return frozenset()

    # Security check: size validation, mirrors classification._load_popular_crypto_tokens.
    try:
        file_size = path.stat().st_size
        if file_size > _MAX_LABELS_FILE_SIZE:
            raise FileProcessingError(
                f"Derivatives labels config exceeds size limit ({file_size} bytes, "
                f"max {_MAX_LABELS_FILE_SIZE} bytes): {path}"
            )
    except OSError as e:
        raise FileProcessingError(
            f"Could not stat derivatives labels config {path}: {e}"
        ) from e

    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise FileProcessingError(
            f"Derivatives labels config {path} contains invalid JSON: {e}"
        ) from e

    if not isinstance(data, dict):
        raise FileProcessingError(
            f"Derivatives labels config must contain a JSON object, got "
            f"{type(data).__name__}: {path}"
        )

    if "derivatives_th_labels" not in data:
        raise FileProcessingError(
            f"Derivatives labels config must contain a 'derivatives_th_labels' key: {path}"
        )

    labels_value = data["derivatives_th_labels"]
    if not isinstance(labels_value, list) or not all(
        isinstance(label, str) for label in labels_value
    ):
        raise FileProcessingError(
            f"Derivatives labels config 'derivatives_th_labels' must be a list of strings, "
            f"got {type(labels_value).__name__}: {path}"
        )

    labels = frozenset(labels_value)
    logger.debug(
        "Loaded %d derivatives TH labels from %s", len(labels), path
    )
    return labels


def _load_derivatives_labels_config(provider: str, year: int) -> frozenset[str]:
    """Load the derivatives TH labels for ``(provider, year)``.

    Args:
        provider: Lower-case provider identifier (e.g. ``"koinly"``).
        year: Four-digit fiscal year (e.g. ``2025``).

    Returns:
        Frozenset of TH Label strings that mark derivatives events.

    Raises:
        FileProcessingError: If the resolved config file is malformed (see
            :func:`_load_derivatives_labels_config_from_path`).
    """
    path = (
        _REPOSITORY_ROOT
        / "docs"
        / "tax"
        / "derivatives_labels"
        / f"{provider}_{year}.json"
    )
    return _load_derivatives_labels_config_from_path(path)


@dataclasses.dataclass(frozen=True)
class DerivativesThEvent:
    """A derivatives event emitted from the Transaction History report.

    Each event corresponds to one TH ``crypto_withdrawal`` row whose Label
    is in the configured derivatives-labels set. The matcher pairs events
    with CG lots by ``(timestamp, asset, wallet, amount)`` — minute
    precision is required because CG rows on the same day may originate
    from different TH events.

    Attributes:
        timestamp: Minute-precision ``%Y-%m-%d %H:%M`` string (seconds
            truncated) computed from the TH Date column. The matcher and
            logger use this; no separate day-level ``date`` field is needed.
        asset: Normalized asset ticker (``normalize_asset_ticker``).
        wallet: Normalized platform name (``normalize_platform_name``).
        amount: Sent Amount parsed via ``parse_koinly_decimal``.
        label: Raw Label string from the TH row (case-sensitive).
    """

    timestamp: str
    asset: str
    wallet: str
    amount: Decimal
    label: str


# TH row Type value that marks derivatives funding/fee/realized-gain outflows.
# Rewards and deposits use ``crypto_deposit``; fiat settlements use
# ``fiat_withdrawal``. Only ``crypto_withdrawal`` rows carry the asset movement
# that matches a CG disposal lot.
_DERIVATIVES_TH_TYPE = "crypto_withdrawal"


def find_derivatives_th_events(
    transaction_history_path: Path, labels: frozenset[str]
) -> list[DerivativesThEvent]:
    """Scan a Koinly Transaction History CSV for derivatives events.

    Args:
        transaction_history_path: Path to the Koinly transaction history
            CSV file. The file has a multi-line preamble (line 1 = title,
            line 2 = blank, line 3 = header) handled by
            ``read_koinly_rows`` via ``_detect_header_index``.
        labels: Frozenset of TH Label strings that mark derivatives events.
            An empty set (e.g. missing config degraded) causes the scanner
            to return zero events without raising.

    Returns:
        List of :class:`DerivativesThEvent` instances, one per
        ``crypto_withdrawal`` row whose Label (case-sensitive exact match)
        is in ``labels``. The scanner does NOT deduplicate events: two
        positions accruing the same funding fee at the same minute produce
        two events with identical ``(timestamp, asset, wallet, amount)``
        keys; the downstream matcher handles collisions.
    """
    if not labels:
        return []

    rows = read_koinly_rows(transaction_history_path)

    events: list[DerivativesThEvent] = []
    for row in rows:
        if row.get("Type") != _DERIVATIVES_TH_TYPE:
            continue
        label = row.get("Tag", "")
        if label not in labels:
            continue

        timestamp = parse_koinly_datetime(row["Date"]).strftime("%Y-%m-%d %H:%M")
        asset = normalize_asset_ticker(row["Sent Currency"])
        wallet = normalize_platform_name(row["Sending Wallet"])
        amount = parse_koinly_decimal(row["Sent Amount"])

        events.append(
            DerivativesThEvent(
                timestamp=timestamp,
                asset=asset,
                wallet=wallet,
                amount=amount,
                label=label,
            )
        )

    return events


# Per-lot rounding for the exact-match phase: both CG and TH amounts are
# quantized to 6 decimals before equality check, absorbing Koinly rounding
# differences without introducing a fuzzy tolerance window.
_EXACT_AMOUNT_QUANTUM = Decimal("0.000001")
# Per-range tolerance scale for the contiguous-range fallback. The tolerance
# is `Decimal("0.00001") * range_size` (10x the per-lot rounding error,
# absorbing accumulation when summing N independently-rounded lots).
_RANGE_TOLERANCE_SCALE = Decimal("0.00001")

# Maximum sample size for the (timestamp, asset, wallet, amount) and
# (timestamp, asset, amount) tuples printed in the summary WARNING. Keeps
# the warning readable while still surfacing the offending keys.
_SUMMARY_SAMPLE_SIZE = 3


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
class _IndexedLot:
    """A CryptoCapitalGainEntry paired with its original list index.

    The matcher tracks removals by index in a set; this wrapper keeps the
    association stable across sorting and filtering.
    """

    index: int
    entry: CryptoCapitalGainEntry


def _find_contiguous_range(
    candidates: list[_IndexedLot], target: Decimal
) -> list[_IndexedLot] | None:
    """Sliding-window search for a contiguous range summing to ``target``.

    Lots in ``candidates`` are already sorted by ``(acquisition_date, index)``
    so a contiguous window in this list corresponds to a contiguous block in
    FIFO acquisition order, which is what a single disposal consumes. Returns
    the first (lowest starting index) matching range, or ``None`` if no window
    sums to ``target`` within ``Decimal("0.00001") * range_size``.

    Args:
        candidates: Unmatched CG lots at the same
            ``(timestamp, asset, wallet)`` key, sorted by acquisition_date.
        target: Target amount (the TH event's amount).

    Returns:
        The matching contiguous range (list of ``_IndexedLot``), or ``None``.
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
            return candidates[left : right + 1]

    return None


def _build_candidates(
    capital_entries: list[CryptoCapitalGainEntry],
) -> tuple[list[_IndexedLot], list[CryptoCapitalGainEntry]]:
    """Build the sorted candidate list and the malformed-input skip list.

    Entries without ``disposal_timestamp`` are silently skipped (they predate
    the timestamp-field introduction or come from non-FIFO sources). Entries
    with non-positive ``amount`` are collected into the malformed-input list
    for inclusion in the summary WARNING. Surviving candidates are sorted by
    ``(timestamp, asset, wallet, acquisition_date, index)`` for determinism.
    """
    candidates: list[_IndexedLot] = []
    malformed: list[CryptoCapitalGainEntry] = []
    for index, entry in enumerate(capital_entries):
        if entry.disposal_timestamp is None:
            continue
        if entry.amount <= 0:
            malformed.append(entry)
            continue
        candidates.append(_IndexedLot(index=index, entry=entry))

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
    candidates: list[_IndexedLot],
    sorted_events: list[DerivativesThEvent],
) -> tuple[
    list[tuple[_IndexedLot, DerivativesThEvent]],
    list[DerivativesThEvent],
    dict[tuple[str, str, str, Decimal], deque[_IndexedLot]],
]:
    """Phase 1: pop one lot per event from per-key deques.

    Returns the (matched_pairs, unmatched_events, exact_match_deques) tuple.
    The deques are returned so the caller can detect surplus lots.
    """
    deques: dict[tuple[str, str, str, Decimal], deque[_IndexedLot]] = {}
    for lot in candidates:
        deques.setdefault(_exact_match_key(lot.entry), deque()).append(lot)

    matched: list[tuple[_IndexedLot, DerivativesThEvent]] = []
    unmatched: list[DerivativesThEvent] = []
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
    candidates: list[_IndexedLot],
    unmatched_events: list[DerivativesThEvent],
    matched_indices: set[int],
) -> list[tuple[_IndexedLot, DerivativesThEvent]]:
    """Phase 2: sliding-window fallback for unmatched events.

    For each unmatched event, scan the available lots at the same
    ``(timestamp, asset, wallet)`` (sorted by acquisition_date) for a
    contiguous range summing to the event amount within tolerance.
    """
    group_key_to_lots: dict[tuple[str, str, str], list[_IndexedLot]] = {}
    for lot in candidates:
        if lot.index in matched_indices:
            continue
        group_key = (
            lot.entry.disposal_timestamp or "",
            lot.entry.asset,
            lot.entry.wallet,
        )
        group_key_to_lots.setdefault(group_key, []).append(lot)

    range_matched: list[tuple[_IndexedLot, DerivativesThEvent]] = []
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
    deques: dict[tuple[str, str, str, Decimal], deque[_IndexedLot]],
    matched_indices: set[int],
) -> list[_IndexedLot]:
    """Surplus = leftover lots at any exact-match key after all events consumed."""
    surplus: list[_IndexedLot] = []
    for bucket in deques.values():
        for lot in bucket:
            if lot.index not in matched_indices:
                surplus.append(lot)
    return surplus


def _log_removals_and_surplus(
    matched_metadata: list[tuple[_IndexedLot, str, DerivativesThEvent]],
    surplus_lots: list[_IndexedLot],
) -> tuple[int, int, Decimal, Decimal, Decimal]:
    """Per-lot INFO logs for removals and surplus lots.

    Returns ``(exact_count, range_count, total_proceeds_removed,
    total_gain_removed, surplus_total_amount)`` for the summary WARNING.
    """
    exact_count = 0
    range_count = 0
    total_proceeds = Decimal("0")
    total_gain = Decimal("0")
    for lot, match_type, event in matched_metadata:
        if match_type == "exact":
            exact_count += 1
        else:
            range_count += 1
        total_proceeds += lot.entry.proceeds_eur
        total_gain += lot.entry.gain_loss_eur
        logger.info(
            "Removed derivatives-flagged CG lot: match_type=%s timestamp=%s "
            "asset=%s wallet=%s amount=%s proceeds_eur=%s gain_eur=%s th_label=%s",
            match_type,
            lot.entry.disposal_timestamp,
            lot.entry.asset,
            lot.entry.wallet,
            lot.entry.amount,
            lot.entry.proceeds_eur,
            lot.entry.gain_loss_eur,
            event.label,
        )
    surplus_total = Decimal("0")
    for lot in surplus_lots:
        surplus_total += lot.entry.amount
        logger.info(
            "Surplus CG lot detected after derivatives exact-match phase: "
            "timestamp=%s asset=%s wallet=%s amount=%s",
            lot.entry.disposal_timestamp,
            lot.entry.asset,
            lot.entry.wallet,
            lot.entry.amount,
        )
    return exact_count, range_count, total_proceeds, total_gain, surplus_total


def _format_summary_warning(  # noqa: PLR0913
    *,
    total_removed: int,
    exact_count: int,
    range_count: int,
    total_proceeds: Decimal,
    total_gain: Decimal,
    surplus_lots: list[_IndexedLot],
    surplus_total_amount: Decimal,
    malformed_input_lots: list[CryptoCapitalGainEntry],
) -> str:
    """Assemble the single WARNING summary string covering all signal types."""
    parts: list[str] = [
        f"Derivatives CG dedup summary: removed {total_removed} lots "
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


def remove_derivatives_flagged_lots(
    capital_entries: list[CryptoCapitalGainEntry],
    derivatives_events: list[DerivativesThEvent],
) -> tuple[list[CryptoCapitalGainEntry], int]:
    """Remove derivatives-flagged CG lots via two-phase matching.

    Phase 1 (exact match): for each derivatives event, pop one lot from the
    deque at ``(timestamp, asset, wallet, amount_6dp)``. Phase 2 (contiguous-
    range fallback): for each unmatched event, find a contiguous range of
    unmatched lots at the same ``(timestamp, asset, wallet)`` whose sum equals
    the event amount within tolerance ``Decimal("0.00001") * range_size``.

    Per-lot removals log at INFO. Exactly one WARNING summary is emitted per
    call covering removals (count, breakdown by match type, aggregate proceeds
    and gain removed), surplus lots (from exact-match key collisions), and
    malformed-input lots (zero/negative amounts).

    Args:
        capital_entries: Capital-gains entries (FIFO lots). Entries without a
            ``disposal_timestamp`` or with non-positive amount are skipped
            from matching.
        derivatives_events: Derivatives events from the TH scanner. Empty list
            short-circuits and returns the input unchanged.

    Returns:
        Tuple of (filtered list of entries, removed count). The filtered
        list preserves original order minus removed lots.
    """
    if not derivatives_events:
        return capital_entries, 0

    candidates, malformed_input_lots = _build_candidates(capital_entries)

    sorted_events = sorted(
        derivatives_events,
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

    matched_metadata: list[tuple[_IndexedLot, str, DerivativesThEvent]] = [
        *((lot, "exact", event) for lot, event in phase1_matched),
        *((lot, "range", event) for lot, event in phase2_matched),
    ]

    surplus_lots = _collect_surplus_lots(exact_match_deques, matched_indices)

    (
        exact_count,
        range_count,
        total_proceeds,
        total_gain,
        surplus_total,
    ) = _log_removals_and_surplus(matched_metadata, surplus_lots)

    summary = _format_summary_warning(
        total_removed=len(matched_metadata),
        exact_count=exact_count,
        range_count=range_count,
        total_proceeds=total_proceeds,
        total_gain=total_gain,
        surplus_lots=surplus_lots,
        surplus_total_amount=surplus_total,
        malformed_input_lots=malformed_input_lots,
    )
    logger.warning(summary)

    filtered = [
        entry
        for index, entry in enumerate(capital_entries)
        if index not in matched_indices
    ]
    return filtered, len(matched_indices)


def apply_derivatives_dedup(
    *,
    capital_entries: list[CryptoCapitalGainEntry],
    jurisdiction: TaxJurisdictionConfig | None,
    transaction_history_file: Path | None,
    year: int,
) -> list[CryptoCapitalGainEntry]:
    """Pipeline entry point for the derivatives TH-label CG dedup.

    Encapsulates the full gate-check-config-scan-filter sequence so
    ``crypto_reporting.load_koinly_crypto_report`` stays thin (Design
    Invariant 16). The dedup runs only when all four gates hold:

      - ``jurisdiction`` is not None (the caller may pass None when no
        jurisdiction context exists)
      - ``jurisdiction.separate_derivatives_reporting`` is True
      - ``jurisdiction.use_other_gains_report`` is True (without OGR there
        is no Derivatives P&L surface for removed CG lots to land in -
        see Design Invariant 14)
      - ``transaction_history_file`` is provided (TH is the source of the
        derivatives Label signal)

    If any gate fails, the input is returned unchanged (no-op). If the
    label config is missing or empty, exactly one WARNING is emitted and
    the input is returned unchanged. If the TH scan finds no derivatives
    events, the input is returned unchanged (no WARNING, because nothing
    was removed). All per-lot removal INFO logs and the single aggregate
    WARNING summary live inside :func:`remove_derivatives_flagged_lots`
    (Task 5); this function emits only the missing-config WARNING (1x per
    run, non-aggregatable because it has a single remediation action: add
    the config file).

    Args:
        capital_entries: Capital-gains entries (CG lots) AFTER country
            validation and FIFO rebuild. The dedup filters this list
            in place by reassigning the caller's ``capital_entries``
            binding.
        jurisdiction: Tax jurisdiction config supplying the two gating
            flags. ``None`` is treated as a no-op gate failure (the
            pipeline allows this when no jurisdiction context exists).
        transaction_history_file: Path to the Koinly transaction history
            CSV, or ``None`` when the caller did not locate one.
        year: Four-digit fiscal year. Used to resolve the per-provider-
            per-year label config file.

    Returns:
        The filtered list (input unchanged if any gate failed or no
        events matched).
    """
    if not (
        jurisdiction is not None
        and jurisdiction.separate_derivatives_reporting
        and jurisdiction.use_other_gains_report
        and transaction_history_file
    ):
        return capital_entries

    labels = _load_derivatives_labels_config(provider="koinly", year=year)
    if not labels:
        logger.warning(
            "Derivatives TH-label config missing for koinly year %d; CG dedup skipped. "
            "Add docs/tax/derivatives_labels/koinly_%d.json to enable.",
            year,
            year,
        )
        return capital_entries

    derivatives_events = find_derivatives_th_events(transaction_history_file, labels)
    if not derivatives_events:
        return capital_entries

    filtered, _removed_count = remove_derivatives_flagged_lots(
        capital_entries, derivatives_events
    )
    return filtered
