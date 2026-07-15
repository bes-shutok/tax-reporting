"""Crypto derivatives capital-gains deduplication.

This module holds the per-disposal deduplication logic that removes
capital-gains lots corresponding to derivatives events already accounted for
in the Other Gains Report. A per-provider-per-year label config loader
supplies the derivatives Tag set (injected upstream into
``TreatmentConfig.derivatives_tags``),
:func:`find_derivatives_th_events_from_transactions` emits one
``DerivativesThEvent`` per ``crypto_withdrawal`` row whose resolver treatment
is ``DERIVATIVES_CLOSE``, and the shared two-phase matcher in
:mod:`th_lot_matcher` (extracted from this module; repo rule #119) pairs
events with CG lots at minute precision.

Design notes
------------
- The label set is small and stable per (provider, year). It is stored as
  JSON under `docs/maintenance/tax/derivatives_labels/<provider>_<year>.json` so the
  labels can be updated without code changes.
- A *missing* config file degrades gracefully (warning plus empty set): the
  caller skips deduplication. This is the only graceful-degradation path here.
- A *malformed* config file is a correctness hazard: silently skipping would
  leave double-counting in place. Invalid JSON, a missing
  ``derivatives_th_labels`` key, or a wrong value type all raise
  ``FileProcessingError`` so the user sees the problem immediately.
- The event builder does NOT deduplicate events: when two positions accrue
  the same funding fee at the same minute, both events are returned. The
  downstream matcher handles collisions deterministically.
- The CG lot removal delegates to :func:`th_lot_matcher.remove_matched_lots`
  (two-phase matching: exact + contiguous-range fallback). The matcher owns
  the single WARNING summary; this module owns the per-lot INFO logs (each
  removal names the matched ``th_label``) via
  :func:`_log_removals_and_surplus`.
"""

from __future__ import annotations

import dataclasses
import logging
from decimal import Decimal
from pathlib import Path

from ...domain.exceptions import FileProcessingError
from ...domain.jurisdiction import TaxJurisdictionConfig
from ...domain.transaction import Transaction
from ...domain.treatment import Treatment
from ...infrastructure.json_loader import DEGRADED, load_guarded_json
from ...infrastructure.koinly_parser import normalize_asset_ticker
from .classification import _REPOSITORY_ROOT
from .entities import CryptoCapitalGainEntry
from .th_lot_matcher import IndexedLot, remove_matched_lots
from .treatment_resolver import TreatmentConfig, resolve_treatment

logger = logging.getLogger(__name__)

# Max size of a derivatives-labels config file (1 MiB). Bound for the JSON read
# performed by infrastructure.json_loader.load_guarded_json.
_MAX_LABELS_FILE_SIZE = 1 * 1024 * 1024


def _on_error(failed_path: Path, kind: str, detail: str) -> object:
    """Policy callback for :func:`load_guarded_json`.

    Mirrors the degrade-vs-raise policy that previously lived inline in
    ``_load_derivatives_labels_config_from_path`` (inherit the
    guards, recalibrate exception handling to the cost of silent failure). A
    *missing* config degrades silently (the caller owns the single WARNING); a
    *malformed* config is a correctness hazard (silent skip leaves
    double-counting in place), so every other kind raises
    :class:`FileProcessingError` embedding the path.

    Note: ``load_guarded_json`` catches ``OSError``/``json.JSONDecodeError``
    internally and passes ``str(exc)`` as ``detail``; the original exception is
    not available here, so the ``stat_error`` and ``invalid_json`` arms embed
    ``detail`` (the str) in the message rather than chaining ``from e``.
    """
    if kind == "missing":
        return DEGRADED
    if kind == "symlink":
        raise FileProcessingError(
            f"Derivatives labels config at {failed_path} is a symlink - "
            "only regular files are accepted for security"
        )
    if kind == "oversize":
        raise FileProcessingError(
            f"Derivatives labels config exceeds size limit ({detail}): {failed_path}"
        )
    if kind == "stat_error":
        raise FileProcessingError(
            f"Could not stat derivatives labels config {failed_path}: {detail}"
        )
    if kind == "invalid_json":
        raise FileProcessingError(
            f"Derivatives labels config {failed_path} contains invalid JSON: {detail}"
        )
    # Defensive: unknown kind token from the helper is itself a config hazard.
    raise FileProcessingError(
        f"Derivatives labels config {failed_path} failed to load ({kind}): {detail}"
    )


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
    # Symlink / existence / size / json.load guards live in the shared helper;
    # _on_error owns the degrade-vs-raise policy (missing -> DEGRADED silent,
    # all other kinds -> raise). No path.exists() pre-check here: the helper
    # checks symlink before missing so a dangling symlink still raises.
    data = load_guarded_json(
        path, size_limit=_MAX_LABELS_FILE_SIZE, on_error=_on_error
    )

    if data is DEGRADED:
        # Silent return; the apply_derivatives_dedup caller emits a single
        # WARNING with the actionable remediation hint when labels is empty.
        # Logging here would double-warn for the same condition.
        return frozenset()

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
        / "maintenance"
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
    with CG lots by ``(timestamp, asset, wallet, amount)``. Minute
    precision is required because CG rows on the same day may originate
    from different TH events.

    Attributes:
        timestamp: Minute-precision ``%Y-%m-%d %H:%M`` string (seconds
            truncated) computed from the TH Date column. The matcher and
            logger use this; no separate day-level ``date`` field is needed.
        asset: Normalized asset ticker (``normalize_asset_ticker``).
        wallet: Raw, un-normalized ``Sending Wallet`` string.
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


def _log_removals_and_surplus(
    matched_metadata: list[tuple[IndexedLot, str, DerivativesThEvent]],
    surplus_lots: list[IndexedLot],
) -> None:
    """Per-lot INFO logs for removals and surplus lots (derivatives-owned).

    Each per-lot removal names the matching TH ``th_label`` so the log record
    is byte-identical to the pre-extraction output. The summary WARNING
    itself is emitted by :func:`th_lot_matcher.remove_matched_lots`; this
    helper only logs the per-lot INFO records.
    """
    for lot, match_type, event in matched_metadata:
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
    for lot in surplus_lots:
        logger.info(
            "Surplus CG lot detected after derivatives exact-match phase: "
            "timestamp=%s asset=%s wallet=%s amount=%s",
            lot.entry.disposal_timestamp,
            lot.entry.asset,
            lot.entry.wallet,
            lot.entry.amount,
        )


def remove_derivatives_flagged_lots(
    capital_entries: list[CryptoCapitalGainEntry],
    derivatives_events: list[DerivativesThEvent],
) -> tuple[list[CryptoCapitalGainEntry], int]:
    """Remove derivatives-flagged CG lots via the shared two-phase matcher.

    Delegates to :func:`th_lot_matcher.remove_matched_lots`
    (``domain_label="derivatives"``), which runs phase 1 (exact match) and
    phase 2 (contiguous-range fallback) and emits exactly one WARNING summary
    whose title reproduces ``"Derivatives CG dedup summary"`` from this
    module's logger. This caller then runs :func:`_log_removals_and_surplus`
    over the returned ``matched_metadata``/``surplus_lots`` to emit the
    per-lot INFO records (each naming the matched ``th_label``). Unmatched
    events are returned by the matcher but, matching the historical
    behaviour, this caller does NOT warn for them: a derivatives event
    without a CG lot is the expected OGR-only outcome (the disposal lives in
    the Other Gains Report, not Capital Gains).

    Behavior is byte-identical to the pre-extraction implementation: the
    per-lot INFO records AND the summary WARNING both still emit from the
    ``tax_reporting.application.crypto.derivatives_filter`` logger with the
    exact ``"Removed derivatives-flagged CG lot"`` /
    ``"Derivatives CG dedup summary"`` text.

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

    result = remove_matched_lots(
        capital_entries,
        derivatives_events,
        domain_label="derivatives",
        logger=logger,
    )

    _log_removals_and_surplus(result.matched_metadata, result.surplus_lots)

    removed_count = len(capital_entries) - len(result.remaining_entries)
    return result.remaining_entries, removed_count


def find_derivatives_th_events_from_transactions(
    transactions: list[Transaction],
    config: TreatmentConfig,
) -> list[DerivativesThEvent]:
    """Build derivatives events from pre-built ``Transaction`` objects via the resolver.

    Phase E: identification always delegates to ``resolve_treatment`` over
    the pre-built ``transactions`` list. The dedup algorithm itself is
    unchanged - it consumes the same :class:`DerivativesThEvent` shape
    regardless of how the list was produced.

    Family D / F: this function consumes the ``list[Transaction]`` built
    ONCE by the production caller
    (:func:`crypto_reporting.load_koinly_crypto_report`, Task 3 wiring
    step). It does NOT construct ``Transaction`` objects and does NOT
    re-read the TH CSV - the resolver is a pure free function over a
    pre-built typed row.

    Args:
        transactions: Pre-built ``list[Transaction]`` from the production
            caller (Task 3 wiring step). Only rows whose
            ``resolve_treatment(tx, config) == Treatment.DERIVATIVES_CLOSE``
            AND whose Type is ``crypto_withdrawal`` are emitted (the
            matcher pairs events with CG lots by ``(timestamp, asset,
            wallet, amount)``; a non-withdrawal row has no asset movement
            to match a CG disposal lot).
        config: ``TreatmentConfig`` carrying the JSON-loaded
            ``derivatives_tags`` frozenset (Phase B Invariant 5: the
            resolver never hardcodes derivatives tags; production injects
            them from
            ``docs/maintenance/tax/derivatives_labels/<provider>_<year>.json``).

    Returns:
        List of :class:`DerivativesThEvent` instances, one per
        ``crypto_withdrawal`` TH row whose resolver treatment is
        ``DERIVATIVES_CLOSE``. The event list shape (same fields, same
        normalization) is preserved so the downstream matcher and logger
        behave identically to the deleted legacy scanner's output.
    """
    events: list[DerivativesThEvent] = []
    for tx in transactions:
        if tx.row.type != _DERIVATIVES_TH_TYPE:
            continue
        if resolve_treatment(tx, config) is not Treatment.DERIVATIVES_CLOSE:
            continue
        # A ``crypto_withdrawal`` row always carries a sending side (the asset
        # movement); ``sending_amount`` is therefore non-None for rows that
        # passed the Type guard. Defensive guard kept so a malformed row does
        # not silently emit an event with a None amount (Family G: data-loss
        # observability).
        if tx.row.sending_amount is None:
            logger.warning(
                "Skipping derivatives event with no Sent Amount: row_index=%d tag=%s",
                tx.row.row_index,
                tx.row.tag,
            )
            continue
        timestamp = tx.row.utc_instant.strftime("%Y-%m-%d %H:%M")
        asset = normalize_asset_ticker(tx.row.sending_currency or "")
        wallet = tx.row.sending_wallet.strip()
        events.append(
            DerivativesThEvent(
                timestamp=timestamp,
                asset=asset,
                wallet=wallet,
                amount=tx.row.sending_amount,
                label=tx.row.tag,
            )
        )
    return events


def apply_derivatives_dedup(  # noqa: PLR0913
    *,
    capital_entries: list[CryptoCapitalGainEntry],
    jurisdiction: TaxJurisdictionConfig | None,
    transaction_history_file: Path | None,
    transactions: list[Transaction],
    config: TreatmentConfig,
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
    (delegating matching to :mod:`th_lot_matcher`); this function emits
    only the empty-tags WARNING (1x per run, non-aggregatable because
    it has a single remediation action: populate the config file).

    Phase E: identification ALWAYS delegates to
    :func:`find_derivatives_th_events_from_transactions`, which calls
    ``resolve_treatment`` over the pre-built ``list[Transaction]``. The
    Phase-D ``via_resolver`` flag, the standalone ``year`` parameter,
    and the legacy internal tag classifier (formerly in the deleted
    :func:`find_derivatives_th_events`) are gone. The labels-presence
    gate now reads ``config.derivatives_tags`` (already injected by the
    caller) instead of re-loading via ``_load_derivatives_labels_config``,
    eliminating the double-load; the empty-tags WARNING is preserved.
    Family F layering: this function NEVER constructs ``Transaction``
    objects; the caller supplies them.

    Args:
        capital_entries: Capital-gains entries (CG lots) AFTER country
            validation and FIFO rebuild. The dedup filters this list
            in place by reassigning the caller's ``capital_entries``
            binding.
        jurisdiction: Tax jurisdiction config supplying the two gating
            flags. ``None`` is treated as a no-op gate failure (the
            pipeline allows this when no jurisdiction context exists).
        transaction_history_file: Path to the Koinly transaction history
            CSV, or ``None`` when the caller did not locate one. Retained
            as a gate input; no longer scanned directly.
        transactions: Pre-built ``list[Transaction]`` from the production
            caller. Consumed by
            :func:`find_derivatives_th_events_from_transactions`.
        config: ``TreatmentConfig`` for ``resolve_treatment``. Its
            ``derivatives_tags`` frozenset (populated upstream by
            :func:`_load_derivatives_labels_config`) is the source of the
            empty-tags WARNING gate.

    Returns:
        The filtered list (input unchanged if any gate failed or no
        events matched).
    """
    if (
        jurisdiction is None
        or not jurisdiction.derivatives_dedup_enabled
        or not transaction_history_file
    ):
        return capital_entries

    if not config.derivatives_tags:
        logger.warning(
            "Derivatives tags empty in TreatmentConfig; CG dedup skipped. "
            "Populate docs/maintenance/tax/derivatives_labels/koinly_<year>.json "
            "for the active fiscal year."
        )
        return capital_entries

    derivatives_events = find_derivatives_th_events_from_transactions(
        transactions, config
    )
    if not derivatives_events:
        return capital_entries

    filtered, _removed_count = remove_derivatives_flagged_lots(
        capital_entries, derivatives_events
    )
    return filtered
