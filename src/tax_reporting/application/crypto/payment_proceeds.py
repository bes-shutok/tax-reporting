"""Payment-proceeds correction for crypto capital gains (DP-014).

A Koinly Payment disposal (TH rows tagged ``payment`` or ``card payment``)
may land in the Capital Gains report with ``proceeds_eur == 0`` because
Koinly did not price the disposed asset at disposal time. This module
recovers the realization proceeds from one of four tiers, in fixed order:

  1. the Koinly Transaction-History ``Net Value (EUR)`` for the matching
     payment disposal (primary - a priced market value);
  2. the disposal amount at par (1 EUR) for an EUR-pegged stablecoin whose
     Net Value is zero/missing;
  3. the disposal amount times the year-end peg->EUR rate for a non-EUR
     stablecoin whose Net Value is zero/missing and whose peg currency has
     a configured finite positive rate;
  4. otherwise no inference - the row is left unchanged with its existing
     DP-013 zero-proceeds review flag intact, and a specific review entry
     is appended so a human can supply the EUR realization value.

The matcher correlates a CG disposal to a payment-tagged TH row by
``(calendar day, normalized asset ticker, normalized platform,
amount at 6 decimal places)``. A count-equality gate on the candidate
population (zero-proceeds, non-loan-affected CG rows) versus the
payment-tagged TH rows on the same key blocks correction when the two
sides do not agree, so a collision never silently picks the wrong twin.

Config (payment tags, stablecoin set, stablecoin pegs) is loaded from
``docs/maintenance/tax/popular_crypto_tokens.json`` - the same file
``classification._load_popular_crypto_tokens`` reads. The loader here
DEGRADES (returns defaults, warns) on every failure mode, never raises,
so a corrupt token file never aborts report generation.
"""

from __future__ import annotations

import dataclasses
import logging
from collections import deque
from decimal import Decimal, InvalidOperation
from pathlib import Path

from ...infrastructure.config import ConversionRate
from ...infrastructure.json_loader import DEGRADED, load_guarded_json
from ...infrastructure.koinly_parser import (
    normalize_asset_ticker,
    normalize_platform_name,
    parse_koinly_decimal,
)
from ...infrastructure.text_sanitize import strip_control_chars
from .classification import _REPOSITORY_ROOT
from .entities import CryptoCapitalGainEntry, CryptoReviewEntry
from .th_lot_matcher import _quantize_amount_6dp

logger = logging.getLogger(__name__)

# Max size of the popular-crypto-tokens JSON accepted by the payment-proceeds
# loader (1 MiB). Mirrors classification._MAX_TOKEN_FILE_SIZE; the size guard
# bounds the JSON read. The payment-proceeds loader DEGRADES (never raises) on
# oversize, unlike the classification loader.
_MAX_TOKEN_FILE_SIZE = 1 * 1024 * 1024

# Defaults returned on every degrade path (missing/symlink/oversize/malformed/
# missing-keys/drift). Kept in sync with the test fixture
# ``_DEFAULT_PAYMENT_TAGS`` so a missing file produces predictable, safe
# behavior: no stablecoin set, no peg map, the canonical payment tag pair.
_DEFAULT_PAYMENT_TAGS: list[str] = ["payment", "card payment"]
_DEFAULT_STABLECOINS: frozenset[str] = frozenset()
_DEFAULT_STABLECOIN_PEGS: dict[str, str] = {}

# The reused config file path. Resolved from the imported repository root so
# the path is robust against module-structure changes (mirrors
# classification._POPULAR_CRYPTO_TOKENS_FILE).
_PAYMENT_PROCEEDS_CONFIG_FILE = _REPOSITORY_ROOT / "docs" / "maintenance" / "tax" / "popular_crypto_tokens.json"

# Review tab source section label for capital-gains review entries emitted by
# this module. Matches the convention used in crypto_reporting.py.
_CAPITAL_GAINS_SECTION = "capital_gains"


@dataclasses.dataclass(frozen=True)
class PaymentProceedsConfig:
    """Payment-proceeds correction configuration.

    Frozen so a config object can be safely cached and injected. The
    ``stablecoin_pegs`` keys MUST be a subset of ``stablecoins``; the loader
    warns (never raises) on drift.

    Attributes:
        payment_tags: Lower-cased, stripped TH Tag values that identify a
            payment disposal (e.g. ``["payment", "card payment"]``).
        stablecoins: Set of stablecoin tickers eligible for par / peg-rate
            proceeds inference.
        stablecoin_pegs: Map from stablecoin ticker to its peg fiat currency
            code (e.g. ``{"USDT": "USD", "EURC": "EUR"}``).
    """

    payment_tags: list[str]
    stablecoins: frozenset[str]
    stablecoin_pegs: dict[str, str]


def _default_config() -> PaymentProceedsConfig:
    """Build a fresh defaults config (immutable but new containers)."""
    return PaymentProceedsConfig(
        payment_tags=list(_DEFAULT_PAYMENT_TAGS),
        stablecoins=_DEFAULT_STABLECOINS,
        stablecoin_pegs=dict(_DEFAULT_STABLECOIN_PEGS),
    )


def _load_payment_proceeds_config_from_path(path: Path) -> PaymentProceedsConfig:  # noqa: PLR0911 - one degrade return per schema/drift branch is clearer than collapsing
    """Load ``PaymentProceedsConfig`` from ``path`` (testable path-arg reader).

    Delegates the mechanical file guards (symlink rejection, existence check,
    1 MiB size cap, ``json.load``) to
    :func:`tax_reporting.infrastructure.json_loader.load_guarded_json`. The
    helper recalibrates exception handling to DEGRADE never raise (lesson #105):
    a corrupt token file must never abort report generation. On any failure
    mode (missing, symlink, oversize, malformed JSON, missing keys, drift) the
    loader logs a WARNING naming the path and the specific failure, then
    returns the defaults. Schema validation (``tokens.stablecoins``,
    ``stablecoin_pegs``, ``payment_tags``) and the peg/tokens drift guard stay
    caller-side here.

    Args:
        path: Absolute path to ``popular_crypto_tokens.json``.

    Returns:
        A ``PaymentProceedsConfig``. Either the parsed config or, on any
        failure, the defaults (empty stablecoin set, default payment tags).
    """

    def _on_error(failed_path: Path, kind: str, detail: str) -> object:
        """Log the existing-style WARNING for a loader failure, then degrade.

        The human phrase ("symlink" / "not found" / "could not stat" /
        "exceeds size limit" / "invalid JSON") is embedded in the WARNING
        format string itself (NOT only in ``detail``), because for
        ``invalid_json`` ``detail`` is ``str(exc)`` and for ``oversize`` it is
        the byte f-string - neither contains the phrase - and the
        characterization tests grep the captured messages for those substrings.
        """
        if kind == "symlink":
            logger.warning(
                "Payment proceeds config at %s is a symlink - only regular files "
                "are accepted for security (%s). Using defaults (no stablecoin pegs).",
                failed_path,
                detail,
            )
        elif kind == "missing":
            logger.warning(
                "Payment proceeds config not found at %s - using defaults (no stablecoin pegs).",
                failed_path,
            )
        elif kind == "stat_error":
            logger.warning(
                "Could not stat payment proceeds config %s: %s - using defaults.",
                failed_path,
                detail,
            )
        elif kind == "oversize":
            logger.warning(
                "Payment proceeds config exceeds size limit (%s): %s - using defaults.",
                detail,
                failed_path,
            )
        elif kind == "invalid_json":
            logger.warning(
                "Payment proceeds config %s contains invalid JSON: %s - using defaults.",
                failed_path,
                detail,
            )
        return DEGRADED

    data = load_guarded_json(path, size_limit=_MAX_TOKEN_FILE_SIZE, on_error=_on_error)
    if data is DEGRADED:
        return _default_config()

    if not isinstance(data, dict):
        logger.warning(
            "Payment proceeds config must contain a JSON object, got %s: %s - using defaults.",
            type(data).__name__,
            path,
        )
        return _default_config()

    # Required keys: tokens.stablecoins, stablecoin_pegs, payment_tags. Missing
    # any -> degrade (do NOT raise). The classification loader reads only
    # data["tokens"], so adding sibling top-level keys is safe for it.
    tokens_obj = data.get("tokens")
    if not isinstance(tokens_obj, dict) or "stablecoins" not in tokens_obj:
        logger.warning(
            "Payment proceeds config missing 'tokens.stablecoins' key: %s - using defaults.",
            path,
        )
        return _default_config()

    stablecoins_value = tokens_obj["stablecoins"]
    if not isinstance(stablecoins_value, list) or not all(isinstance(t, str) for t in stablecoins_value):
        logger.warning(
            "Payment proceeds config 'tokens.stablecoins' must be a list of strings: %s - using defaults.",
            path,
        )
        return _default_config()

    stablecoin_pegs_value = data.get("stablecoin_pegs")
    if not isinstance(stablecoin_pegs_value, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in stablecoin_pegs_value.items()
    ):
        logger.warning(
            "Payment proceeds config 'stablecoin_pegs' must be a string->string map: %s - using defaults.",
            path,
        )
        return _default_config()

    payment_tags_value = data.get("payment_tags")
    if not isinstance(payment_tags_value, list) or not all(isinstance(t, str) for t in payment_tags_value):
        logger.warning(
            "Payment proceeds config 'payment_tags' must be a list of strings: %s - using defaults.",
            path,
        )
        return _default_config()

    stablecoins = frozenset(stablecoins_value)
    stablecoin_pegs = dict(stablecoin_pegs_value)
    payment_tags = list(payment_tags_value)

    # Consistency guard: stablecoin_pegs keys MUST be a subset of the
    # stablecoins membership. Drift (a peg for a ticker absent from
    # tokens.stablecoins) warns naming the offending tickers; never raises.
    peg_keys = set(stablecoin_pegs)
    stablecoin_set = set(stablecoins)
    if peg_keys != stablecoin_set:
        only_in_pegs = peg_keys - stablecoin_set
        only_in_tokens = stablecoin_set - peg_keys
        drift_parts: list[str] = []
        if only_in_pegs:
            drift_parts.append(f"in stablecoin_pegs but not tokens.stablecoins: {sorted(only_in_pegs)}")
        if only_in_tokens:
            drift_parts.append(f"in tokens.stablecoins but not stablecoin_pegs: {sorted(only_in_tokens)}")
        logger.warning(
            "stablecoin_pegs drift detected in %s - %s. Proceeds inference may mis-route "
            "stablecoins whose peg is unset. Config still loaded.",
            path,
            "; ".join(drift_parts),
        )

    logger.debug(
        "Loaded payment proceeds config from %s (%d stablecoins, %d pegs, %d payment tags)",
        path,
        len(stablecoins),
        len(stablecoin_pegs),
        len(payment_tags),
    )
    return PaymentProceedsConfig(
        payment_tags=payment_tags,
        stablecoins=stablecoins,
        stablecoin_pegs=stablecoin_pegs,
    )


def _get_payment_proceeds_config() -> PaymentProceedsConfig:
    """Resolve the ``PaymentProceedsConfig`` from the repository file.

    The reader ``_load_payment_proceeds_config_from_path`` takes an explicit
    path, so unit tests can drive it with distinct ``tmp_path`` fixtures and
    get fresh reads. This wrapper has a single caller that runs once per
    process, so it is intentionally uncached; re-adding memoization is a
    one-line change if a hot-loop caller ever appears.

    Returns:
        The parsed ``PaymentProceedsConfig``, or the defaults on any failure.
    """
    return _load_payment_proceeds_config_from_path(_PAYMENT_PROCEEDS_CONFIG_FILE)


def _calendar_day(date_str: str) -> str:
    """Extract the calendar day (``YYYY-MM-DD``) from a Koinly/CG date string.

    Both the CG ``disposal_date`` (``"2025-06-15"``) and the TH ``Date``
    (``"2025-06-15 12:00:00 UTC"``) collapse onto the same 10-character
    calendar day, making the match robust to sub-day wall-clock offsets
    between a CG row and its TH twin.

    Args:
        date_str: A date or datetime string whose first 10 chars are
            ``YYYY-MM-DD``.

    Returns:
        The first 10 characters of ``date_str``.
    """
    return date_str[:_CALENDAR_DAY_LEN]


_CALENDAR_DAY_LEN = 10


def build_payment_tag_index(
    th_rows: list[dict[str, str]],
    payment_tags: list[str],
) -> dict[tuple[str, str, str, Decimal], deque[int]]:
    """Index payment-tagged TH rows by their correlation key.

    The correlation key is ``(calendar day, normalized asset ticker,
    normalized platform, amount at 6 decimal places)``. A TH row is indexed
    only when its normalized ``Tag`` is in the (case-insensitive)
    ``payment_tags`` set. Non-payment rows (Reward, empty, etc.) are skipped
    so they never collide into a payment slot.

    Args:
        th_rows: Koinly Transaction History rows (dicts keyed by column name).
        payment_tags: Configured payment tag strings (case-insensitive).

    Returns:
        Dict mapping correlation key to a ``deque`` of TH row indices (in
        insertion order). Rows sharing a key collapse onto the same deque.
    """
    normalized_tags = {t.strip().lower() for t in payment_tags}
    index: dict[tuple[str, str, str, Decimal], deque[int]] = {}
    for idx, row in enumerate(th_rows):
        tag = (row.get("Tag") or "").strip().lower()
        if tag not in normalized_tags:
            continue
        sent_currency = row.get("Sent Currency") or ""
        sending_wallet = row.get("Sending Wallet") or ""
        sent_amount_raw = row.get("Sent Amount") or ""
        date_raw = row.get("Date") or ""
        try:
            amount = parse_koinly_decimal(sent_amount_raw)
        except (ValueError, InvalidOperation):
            logger.warning(
                "TH row %d has unparseable Sent Amount %r - skipping from payment tag index.",
                idx,
                sent_amount_raw,
            )
            continue
        key = (
            _calendar_day(date_raw),
            normalize_asset_ticker(sent_currency),
            normalize_platform_name(sending_wallet),
            _quantize_amount_6dp(amount),
        )
        index.setdefault(key, deque()).append(idx)
    return index


def _entry_key(entry: CryptoCapitalGainEntry) -> tuple[str, str, str, Decimal]:
    """Build the correlation key for a CG entry."""
    return (
        _calendar_day(entry.disposal_date),
        normalize_asset_ticker(entry.asset),
        normalize_platform_name(entry.platform),
        _quantize_amount_6dp(entry.amount),
    )


def _match_payment_disposal(
    entry: CryptoCapitalGainEntry,
    tag_index: dict[tuple[str, str, str, Decimal], deque[int]],
) -> deque[int] | None:
    """Return the payment-tagged TH bucket for ``entry``, or ``None``.

    Pure lookup; does NOT pop. Returns the live deque so the orchestrator
    can ``popleft`` once a correction commits (lesson #124: mutate the
    shared deque only AFTER the fallible parse+replace succeeds).

    Args:
        entry: A CG capital-gain entry.
        tag_index: The index built by :func:`build_payment_tag_index`.

    Returns:
        The bucket deque for the entry's key, or ``None`` when no
        payment-tagged TH row shares the key.
    """
    return tag_index.get(_entry_key(entry))


def _resolve_proceeds(  # noqa: PLR0913
    asset: str,
    amount: Decimal,
    net_value: Decimal | None,
    stablecoins: frozenset[str],
    stablecoin_pegs: dict[str, str],
    peg_to_eur_rates: dict[str, Decimal],
) -> tuple[Decimal | None, str]:
    """Resolve the EUR proceeds for a payment disposal (pure, fixed order).

    Fixed resolution order (Net Value first, then par, then peg-rate, then
    none):

      1. ``net_value`` is finite and positive -> ``(net_value, "net_value")``.
      2. EUR-pegged stablecoin -> ``(amount, "eur_par")``.
      3. Non-EUR stablecoin whose peg has a finite positive rate ->
         ``(amount * rate, "peg_rate")``.
      4. Stablecoin with no resolvable rate -> ``(None, "non_eur_stablecoin_no_rate")``.
      5. Non-stablecoin -> ``(None, "not_stablecoin")``.

    The ``is_finite()`` guards are required because ``parse_koinly_decimal``
    accepts ``inf``/``nan`` (``Decimal("inf") > 0`` is ``True``).

    Args:
        asset: Normalized asset ticker.
        amount: Disposal amount.
        net_value: Parsed Koinly ``Net Value (EUR)`` (may be ``None`` or
            non-finite).
        stablecoins: Stablecoin membership set.
        stablecoin_pegs: Stablecoin -> peg fiat code map.
        peg_to_eur_rates: Peg fiat code -> finite positive EUR rate map.

    Returns:
        ``(proceeds, outcome)`` where ``proceeds`` is the resolved EUR value
        or ``None`` (no inference), and ``outcome`` names the tier reached.
    """
    if net_value is not None and net_value.is_finite() and net_value > 0:
        return net_value, "net_value"
    if asset in stablecoins:
        peg = stablecoin_pegs.get(asset)
        if peg == "EUR":
            return amount, "eur_par"
        if (
            peg is not None
            and peg in peg_to_eur_rates
            and peg_to_eur_rates[peg].is_finite()
            and peg_to_eur_rates[peg] > 0
        ):
            return amount * peg_to_eur_rates[peg], "peg_rate"
        return None, "non_eur_stablecoin_no_rate"
    return None, "not_stablecoin"


def _derive_peg_to_eur_rates(
    rates: list[ConversionRate],
    stablecoin_pegs: dict[str, str],
    target_currency: str = "EUR",
) -> dict[str, Decimal]:
    """Derive a peg-currency -> EUR rate map from configured ConversionRates.

    One entry per peg currency ``p`` (drawn from ``set(stablecoin_pegs.values())``,
    excluding the target currency) that has a
    ``ConversionRate(base=target_currency, calculated=p)`` with a finite,
    positive rate. Non-positive or non-finite rates are SKIPPED with a
    WARNING naming the peg and the offending rate value (the FIRST layer of
    defense; ``_resolve_proceeds`` re-checks at use time).

    Args:
        rates: Configured currency conversion rates.
        stablecoin_pegs: Stablecoin -> peg fiat code map (drives the peg set).
        target_currency: The reporting base currency (default ``"EUR"``).

    Returns:
        Map from peg currency code to finite positive EUR rate.
    """
    needed_pegs = {p for p in stablecoin_pegs.values() if p != target_currency}
    derived: dict[str, Decimal] = {}
    for rate in rates:
        if rate.base != target_currency:
            continue
        peg = rate.calculated
        if peg not in needed_pegs:
            continue
        if not rate.rate.is_finite() or not rate.rate > 0:
            logger.warning(
                "Skipping non-positive or non-finite %s->%s peg rate %s - "
                "stablecoins pegged to %s will route to review.",
                target_currency,
                peg,
                rate.rate,
                peg,
            )
            continue
        derived[peg] = rate.rate
    return derived


def _sanitize_substring(value: str) -> str:
    """Sanitize an external-derived substring for embedding in reasons/logs.

    Routes the value through :func:`strip_control_chars` to strip control
    characters (NUL, BEL, newline, ...). Used for EVERY external-derived
    substring (asset, wallet) embedded in a review reason or warning message
    so embedded control characters cannot corrupt cell rendering or log
    output. Formula-sigil defusal is the Excel layer's responsibility and is
    applied separately when the reason is written to a worksheet cell.
    """
    return strip_control_chars(value)


def _net_value_reason(asset_safe: str, proceeds: Decimal) -> str:
    """Reason for the tier-1 (Koinly Net Value) success path."""
    return (
        f"Payment disposal proceeds recovered from Koinly Net Value for asset "
        f"{asset_safe}: proceeds EUR {proceeds}. Verify the disposal realization value."
    )


def _eur_par_reason(asset_safe: str, proceeds: Decimal) -> str:
    """Reason for the tier-2 (EUR-pegged par) success path."""
    return (
        f"Payment disposal for EUR-pegged stablecoin {asset_safe}: no Koinly market rate, "
        f"proceeds set to EUR par (amount @ 1 EUR) = EUR {proceeds}. Verify the par assumption."
    )


def _peg_rate_reason(asset_safe: str, peg: str, rate: Decimal, proceeds: Decimal) -> str:
    """Reason for the tier-3 (non-EUR peg year-end rate) success path."""
    peg_safe = _sanitize_substring(peg)
    return (
        f"Payment disposal for {peg_safe}-pegged stablecoin {asset_safe}: no Koinly market rate, "
        f"proceeds set via {peg_safe} at year-end rate {rate} = EUR {proceeds}. "
        f"Verify the year-end rate."
    )


def _non_eur_stablecoin_no_rate_reason(asset_safe: str, peg: str | None) -> str:
    """Reason for the tier-4 (stablecoin, no resolvable rate) review path.

    ``peg`` is ``None`` in the config-drift case (asset in ``stablecoins`` but
    absent from ``stablecoin_pegs``); the rate phrase must degrade for
    ``peg is None`` just like ``peg_phrase`` does, otherwise the f-string
    emits the nonsensical literal ``"no None->EUR rate in config"``. ``peg`` is
    sanitized like ``asset`` so a corrupt config value cannot ship a control
    char into the reason.
    """
    peg_safe = _sanitize_substring(peg) if peg else None
    peg_phrase = f"{peg_safe}-pegged stablecoin" if peg else "stablecoin"
    rate_phrase = f"no {peg_safe}->EUR rate in config" if peg else "no EUR realization rate configured"
    return (
        f"Matched Payment for {asset_safe} ({peg_phrase}) but Koinly reported no market rate "
        f"AND {rate_phrase} - supply the EUR realization value."
    )


def _not_stablecoin_reason(asset_safe: str) -> str:
    """Reason for the tier-5 (non-stablecoin) review path."""
    return (
        f"Matched Payment but Koinly reported no market rate for {asset_safe} - "
        f"check the asset's ticker mapping in Koinly."
    )


def correct_payment_proceeds(  # noqa: PLR0912, PLR0913, PLR0915, C901
    entries: list[CryptoCapitalGainEntry],
    th_rows: list[dict[str, str]],
    *,
    config: PaymentProceedsConfig,
    peg_to_eur_rates: dict[str, Decimal],
    loan_affected_assets: frozenset[str],
    review_entries: list[CryptoReviewEntry],
) -> list[CryptoCapitalGainEntry]:
    """Correct zero-proceeds payment disposals using TH Net Value / peg rates.

    Thin orchestrator. The config is INJECTED as one object (no internal
    ``_get_payment_proceeds_config()`` call) so callers control the source.

    Algorithm:

      1. Build the payment-tagged TH index.
      2. Pre-count BOTH static sides BEFORE the entry loop: ``cg_count[key]``
         over the candidate population (entries with ``proceeds_eur == 0``
         AND asset NOT in ``loan_affected_assets``); ``th_count[key]`` is the
         static size of each payment bucket (captured once, before any
         popleft).
      3. Iterate entries in order. Skip if ``proceeds_eur != 0`` or the asset
         is loan-affected. For a candidate, look up its bucket and apply the
         count-equality gate BEFORE the try (so popleft is only ever on a
         non-empty deque - lesson #124):
           - ``th_count[key] == 0``: leave unchanged, NO review entry
             (DP-013 flag intact).
           - ``cg_count[key] != th_count[key]``: leave ALL candidates on the
             key unchanged; append ONE ``CryptoReviewEntry`` for the key
             (guarded by ``reviewed_keys``) naming the count mismatch.
           - else (counts equal): per-entry try/except. Parse the bucket
             FRONT TH row ``Net Value (EUR)``; non-finite Net Value guard;
             resolve proceeds; on ``proceeds is None`` leave unchanged and
             append the outcome-specific review entry (per-key guarded); on
             success ``dataclasses.replace`` the entry, THEN ``popleft``
             (mutate only AFTER success), and append a per-ROW audit
             ``CryptoReviewEntry`` (NOT per-key guarded). On exception: warn,
             emit the entry unchanged, do NOT pop, no review entry.

    Args:
        entries: CG capital-gain entries (order preserved in the output).
        th_rows: Koinly Transaction History rows.
        config: Injected ``PaymentProceedsConfig``.
        peg_to_eur_rates: Peg currency -> finite positive EUR rate map
            (typically the output of :func:`_derive_peg_to_eur_rates`).
        loan_affected_assets: Assets excluded from the candidate population
            (rebuilt from TH by a separate pipeline).
        review_entries: List to append ``CryptoReviewEntry`` audit rows to
            (mutated in place).

    Returns:
        New list of entries (untouched/unmatched entries preserved in order;
        corrected entries replaced in place).
    """
    tag_index = build_payment_tag_index(th_rows, config.payment_tags)

    # Pre-count BOTH static sides BEFORE the entry loop. cg_count is over the
    # candidate population only (proceeds==0 AND non-loan); a loan-affected
    # zero-proceeds sibling must NOT inflate the count.
    cg_count: dict[tuple[str, str, str, Decimal], int] = {}
    for entry in entries:
        if entry.proceeds_eur != 0 or entry.asset in loan_affected_assets:
            continue
        key = _entry_key(entry)
        cg_count[key] = cg_count.get(key, 0) + 1

    # Static TH bucket sizes captured once, before any popleft.
    th_count: dict[tuple[str, str, str, Decimal], int] = {key: len(bucket) for key, bucket in tag_index.items()}

    reviewed_keys: set[tuple[str, str, str, Decimal]] = set()

    result: list[CryptoCapitalGainEntry] = []
    for entry in entries:
        # Skip non-candidates: already-priced, or loan-affected.
        if entry.proceeds_eur != 0 or entry.asset in loan_affected_assets:
            result.append(entry)
            continue

        key = _entry_key(entry)
        bucket = _match_payment_disposal(entry, tag_index)

        # No payment-tagged TH row for this key: leave unchanged, no review.
        if bucket is None or th_count.get(key, 0) == 0:
            result.append(entry)
            continue

        # Count-equality gate runs BEFORE the try (lesson #124). Mismatch in
        # EITHER direction blocks correction for ALL candidates on the key.
        if cg_count.get(key, 0) != th_count.get(key, 0):
            if key not in reviewed_keys:
                reviewed_keys.add(key)
                reason = (
                    f"Payment match ambiguous: {cg_count.get(key, 0)} CG rows vs "
                    f"{th_count.get(key, 0)} Payment events on "
                    f"(day, asset, platform, amount) for asset "
                    f"{_sanitize_substring(entry.asset)} - verify"
                )
                review_entries.append(
                    CryptoReviewEntry(
                        source_section=_CAPITAL_GAINS_SECTION,
                        date=entry.disposal_date,
                        asset=entry.asset,
                        platform=entry.platform,
                        review_reason=reason,
                    )
                )
                logger.warning(
                    "Payment match ambiguous for asset %s on %s: %s CG rows vs %s Payment events.",
                    _sanitize_substring(entry.asset),
                    entry.disposal_date,
                    cg_count.get(key, 0),
                    th_count.get(key, 0),
                )
            result.append(entry)
            continue

        # Counts equal: per-entry try/except. Parse the bucket FRONT TH row.
        try:
            front_idx = bucket[0]
            front_row = th_rows[front_idx]
            net_value_raw = front_row.get("Net Value (EUR)")
            net_value = parse_koinly_decimal(net_value_raw) if net_value_raw else None

            # Non-finite Net Value guard: parse_koinly_decimal accepts inf/nan
            # (inf > 0 is True). Leave UNCHANGED, do NOT pop, continue.
            if net_value is not None and not net_value.is_finite():
                logger.warning(
                    "Payment disposal for asset %s on %s: matched TH row %d has non-finite Net "
                    "Value %s - leaving row unchanged (proceeds 0).",
                    _sanitize_substring(entry.asset),
                    entry.disposal_date,
                    front_idx,
                    net_value,
                )
                result.append(entry)
                continue

            proceeds, outcome = _resolve_proceeds(
                entry.asset,
                entry.amount,
                net_value,
                config.stablecoins,
                config.stablecoin_pegs,
                peg_to_eur_rates,
            )

            if proceeds is None:
                # No inference: leave unchanged, do NOT pop. Per-key guarded
                # review entry (outcome-specific).
                if key not in reviewed_keys:
                    reviewed_keys.add(key)
                    asset_safe = _sanitize_substring(entry.asset)
                    peg = config.stablecoin_pegs.get(entry.asset)
                    if outcome == "non_eur_stablecoin_no_rate":
                        reason = _non_eur_stablecoin_no_rate_reason(asset_safe, peg)
                    else:
                        reason = _not_stablecoin_reason(asset_safe)
                    review_entries.append(
                        CryptoReviewEntry(
                            source_section=_CAPITAL_GAINS_SECTION,
                            date=entry.disposal_date,
                            asset=entry.asset,
                            platform=entry.platform,
                            review_reason=reason,
                        )
                    )
                    logger.warning(
                        "Payment disposal for asset %s on %s: matched TH row reported no usable "
                        "market rate (outcome=%s) - leaving row unchanged.",
                        asset_safe,
                        entry.disposal_date,
                        outcome,
                    )
                result.append(entry)
                continue

            # Success: compute gain, replace entry, THEN pop (lesson #124).
            gain = proceeds - entry.cost_eur
            asset_safe = _sanitize_substring(entry.asset)
            peg = config.stablecoin_pegs.get(entry.asset)
            if outcome == "net_value":
                reason = _net_value_reason(asset_safe, proceeds)
            elif outcome == "eur_par":
                reason = _eur_par_reason(asset_safe, proceeds)
            elif outcome == "peg_rate":
                rate = peg_to_eur_rates[peg] if peg in peg_to_eur_rates else Decimal("0")
                reason = _peg_rate_reason(asset_safe, peg, rate, proceeds)
            else:  # pragma: no cover - _resolve_proceeds returns only the three outcomes above
                raise AssertionError(
                    f"Unhandled outcome from _resolve_proceeds: {outcome!r}"
                )

            replaced = dataclasses.replace(
                entry,
                proceeds_eur=proceeds,
                gain_loss_eur=gain,
                review_required=True,
                review_reason=reason,
            )
            bucket.popleft()
            result.append(replaced)
            # Per-ROW success audit (deliberately NOT guarded by
            # reviewed_keys): two equal-count lots each append their own audit.
            review_entries.append(
                CryptoReviewEntry(
                    source_section=_CAPITAL_GAINS_SECTION,
                    date=replaced.disposal_date,
                    asset=replaced.asset,
                    platform=replaced.platform,
                    review_reason=reason,
                )
            )
        except (ValueError, KeyError, InvalidOperation, TypeError) as e:
            # Per-entry boundary: warn, emit the entry UNCHANGED with its
            # DP-013 flag intact, do NOT pop, NO review entry (deliberate
            # asymmetry - the row's existing in-place reason covers it).
            # TypeError is included so a contract-violating injected rate
            # (e.g. None passed as Decimal) degrades like any other failure
            # instead of aborting the whole crypto report.
            logger.warning(
                "Payment disposal correction failed for asset %s on %s: %s - leaving row unchanged (proceeds 0).",
                _sanitize_substring(entry.asset),
                entry.disposal_date,
                e,
            )
            result.append(entry)
            continue

    return result
