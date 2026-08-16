"""Thin pre-classification reader for ``bera_transactions.csv`` (Task 7).

This module parses the Etherscan-derived on-chain transactions CSV into a flat
list of :class:`OnChainTxRow` records. It performs NO classification:

- It does NOT group rows by ``tx_hash`` into ``OnChainTransaction`` objects.
- It does NOT infer ``Event``/``EventType`` shapes or ``Leg`` grouping.
- It does NOT lift row-level gas to a parent transaction.

Those responsibilities belong to the processor
(:mod:`tax_reporting.infrastructure.on_chain.berachain_processor`, Task 9),
which classifies these rows into the domain
``OnChainTransaction``/``Event``/``Leg`` model (:mod:`tax_reporting.domain.on_chain_transaction`,
Task 6). Gas lives at the CSV-row level here (``fee_asset`` / ``fee_amount_raw``)
and is lifted to parent-tx level (``OnChainTransaction.gas``) by the processor.

The :class:`OnChainTxRow` defined HERE is the reader's OUTPUT type: a thin
pre-classification row with parsed/typed fields. It is intentionally distinct
from the CSV-write-oriented ``OnChainTxRow`` in :mod:`bera_decoder` (which
carries string-typed fields for CSV serialization).

Hygiene patterns (mirrored from :mod:`tax_reporting.infrastructure.koinly_parser`):
symlink refusal, size cap, ``utf-8-sig`` decoding (handles BOM), blank-row drop,
per-row parse errors caught and warned (one bad row never discards the dataset -
AGENTS.md rule).

Attacker F5 mitigation: ``amount_decimals`` is clamped to ``[0, 36]`` before the
row is emitted. Out-of-range values (an attacker could write an EVM-decoder
metadata file feeding this CSV) would otherwise let a downstream consumer
compute ``10 ** 77`` and exhaust memory. On clamp the row is still emitted, but
carries ``review_flag="decimal_clamped"`` and a specific, actionable
``review_reason`` (AGENTS.md: partial/uncertain results must carry an explicit
indicator; never silently dropped).
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Final, Literal

from tax_reporting.domain.exceptions import FileProcessingError

_LOGGER = logging.getLogger(__name__)

# File size guard (mirrors koinly_parser). Prevents DoS via an oversized CSV.
_MAX_CSV_BYTES: Final = 50 * 1024 * 1024  # 50 MB

# Attacker F5 mitigation: clamp decimals into the EVM-realistic range. EVM
# tokens use at most 36 decimals (the widest known standard); anything outside
# [0, 36] is treated as attacker-controlled metadata and clamped, never trusted
# (a downstream consumer computing 10 ** decimals would OOM on 10 ** 77).
_MIN_DECIMALS: Final = 0
_MAX_DECIMALS: Final = 36

# Allowed direction values. An unexpected value is coerced to "unknown" with a
# review flag (never silently dropped, never silently mislabeled).
_DIRECTIONS: Final[frozenset[str]] = frozenset({"in", "out", "unknown"})

Direction = Literal["in", "out", "unknown"]


@dataclass(frozen=True)
class OnChainTxRow:
    """One parsed row of ``bera_transactions.csv`` (pre-classification).

    All 15 CSV columns map to typed fields. Empty optional fields normalize to
    ``None``. Numeric fields parse as ``int`` (NEVER ``float`` - EVM values are
    big integers and float coercion silently loses precision).

    ``review_flag`` / ``review_reason`` are populated when the reader had to
    coerce a value (e.g. clamp decimals, coerce an unexpected direction) so the
    consumer cannot mistake the row for a clean parse (AGENTS.md).
    """

    tx_hash: str
    block_number: int
    timestamp_utc: datetime
    chain: str
    from_address: str
    to_address: str
    asset: str
    token_address: str | None
    amount_raw: int
    amount_decimals: int
    direction: Direction
    fee_asset: str | None
    fee_amount_raw: int | None
    wallet_label: str
    wallet_address: str
    review_flag: str | None = None
    review_reason: str | None = None


def _optional_str(value: str | None) -> str | None:
    """Normalize an optional CSV cell: stripped value or None when empty."""
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def read_on_chain_rows(path: Path) -> list[OnChainTxRow]:
    """Read ``bera_transactions.csv`` and return parsed :class:`OnChainTxRow` records.

    Args:
        path: Path to the on-chain transactions CSV file.

    Returns:
        List of successfully-parsed :class:`OnChainTxRow` records, in source
        CSV order. Blank rows are dropped; rows that fail to parse are skipped
        after a WARNING (one bad row never discards the dataset).

    Raises:
        FileProcessingError: If the path is a symlink (refused), the file
            exceeds the size cap, or the CSV header cannot be detected.
    """
    # Hygiene guards (mirror koinly_parser.read_koinly_rows).
    if path.is_symlink():
        raise FileProcessingError(
            f"Refusing to read symlink {path}: resolve to a plain file before ingesting"
        )
    file_size = path.stat().st_size
    if file_size > _MAX_CSV_BYTES:
        raise FileProcessingError(
            f"CSV file {path.name} exceeds size limit ({file_size} bytes, max {_MAX_CSV_BYTES} bytes)"
        )
    # utf-8-sig transparently strips a leading BOM if present.
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    reader = csv.DictReader(lines)

    rows: list[OnChainTxRow] = []
    for index, raw in enumerate(reader, start=1):
        # Drop blank rows (all-None / all-empty), as DictReader yields them for
        # trailing blank lines.
        if all((value is None or str(value).strip() == "") for value in raw.values()):
            continue
        parsed = _parse_row(raw, row_index=index)
        if parsed is not None:
            rows.append(parsed)
    return rows


def _parse_row(raw: dict[str, str | None], *, row_index: int) -> OnChainTxRow | None:
    """Parse one CSV row dict into an :class:`OnChainTxRow`, or skip with a WARNING.

    Per-row parse errors are caught by the outer handler (AGENTS.md: one bad
    row never discards the dataset); ``fee_amount_raw`` additionally has a
    nested try/except for row-context-specific reporting.
    """
    try:
        tx_hash = (raw.get("tx_hash") or "").strip()
        chain = (raw.get("chain") or "").strip()
        from_address = (raw.get("from_address") or "").strip()
        to_address = (raw.get("to_address") or "").strip()
        asset = (raw.get("asset") or "").strip()
        wallet_label = (raw.get("wallet_label") or "").strip()
        wallet_address = (raw.get("wallet_address") or "").strip()

        token_address = _optional_str(raw.get("token_address"))
        fee_asset = _optional_str(raw.get("fee_asset"))

        timestamp_utc = datetime.fromisoformat((raw.get("timestamp_utc") or "").strip())

        # amount_raw is a big integer string (e.g. 10**18). Parse as int, NEVER
        # float. Python ints are arbitrary precision; the defensive except tuple
        # (MemoryError/OverflowError) is included per the plan for a maliciously
        # huge value, though in practice int() on a str raises ValueError first.
        amount_raw = int((raw.get("amount_raw") or "").strip())
        fee_amount_raw_raw = _optional_str(raw.get("fee_amount_raw"))
        fee_amount_raw: int | None
        try:
            fee_amount_raw = int(fee_amount_raw_raw) if fee_amount_raw_raw is not None else None
        except (ValueError, TypeError, MemoryError, OverflowError) as exc:
            _LOGGER.warning(
                "Skipping on-chain CSV row %d (tx_hash=%s): unparseable fee_amount_raw=%r: %s",
                row_index,
                tx_hash,
                raw.get("fee_amount_raw"),
                exc,
            )
            return None

        block_number = int((raw.get("block_number") or "").strip())

        # Decimal clamp (Attacker F5). Clamp BEFORE any consumer can compute
        # 10 ** decimals. The original value is recorded in the review_reason.
        original_decimals = int((raw.get("amount_decimals") or "").strip())
        amount_decimals, decimals_review = _clamp_decimals(original_decimals)

        # Direction validation. An unexpected value is coerced to "unknown"
        # with a review flag (never silently dropped, never silently mislabeled).
        raw_direction = (raw.get("direction") or "").strip()
        if raw_direction in _DIRECTIONS:
            direction: Direction = raw_direction  # type: ignore[assignment]
            direction_review: tuple[str, str] | None = None
        else:
            direction = "unknown"
            direction_review = (
                "direction_coerced",
                f"direction {raw_direction!r} not in {{in,out,unknown}}; coerced to 'unknown'",
            )

        # Merge review indicators (decimals + direction may both trip).
        review_flag, review_reason = _merge_reviews(decimals_review, direction_review)

        return OnChainTxRow(
            tx_hash=tx_hash,
            block_number=block_number,
            timestamp_utc=timestamp_utc,
            chain=chain,
            from_address=from_address,
            to_address=to_address,
            asset=asset,
            token_address=token_address,
            amount_raw=amount_raw,
            amount_decimals=amount_decimals,
            direction=direction,
            fee_asset=fee_asset,
            fee_amount_raw=fee_amount_raw,
            wallet_label=wallet_label,
            wallet_address=wallet_address,
            review_flag=review_flag,
            review_reason=review_reason,
        )
    except (ValueError, TypeError, KeyError, MemoryError, OverflowError) as exc:
        _LOGGER.warning(
            "Skipping malformed on-chain CSV row %d (tx_hash=%s): %s",
            row_index,
            raw.get("tx_hash"),
            exc,
        )
        return None


def _clamp_decimals(value: int) -> tuple[int, tuple[str, str] | None]:
    """Clamp ``value`` into ``[_MIN_DECIMALS, _MAX_DECIMALS]``.

    Returns the clamped value and, when clamping fired, a ``(flag, reason)``
    tuple. The reason names the original value and the clamp range so it is
    specific and actionable (AGENTS.md: review flags must include specific
    actionable explanations, not bare booleans).
    """
    if value < _MIN_DECIMALS:
        clamped = _MIN_DECIMALS
    elif value > _MAX_DECIMALS:
        clamped = _MAX_DECIMALS
    else:
        return value, None
    reason = (
        f"amount_decimals {value} outside valid range "
        f"[{_MIN_DECIMALS},{_MAX_DECIMALS}]; clamped to {clamped}"
    )
    _LOGGER.warning(
        "amount_decimals=%d outside [%d,%d]; clamped to %d (Attacker F5 guard).",
        value,
        _MIN_DECIMALS,
        _MAX_DECIMALS,
        clamped,
    )
    return clamped, ("decimal_clamped", reason)


def _merge_reviews(
    *reviews: tuple[str, str] | None,
) -> tuple[str | None, str | None]:
    """Merge multiple ``(flag, reason)`` review indicators into one.

    If multiple trips fire, the flag is joined by ``+`` and the reasons by ``; ``
    so the consumer sees every cause (AGENTS.md: never collapse multiple causes
    into one, branch on the discriminator each upstream sets).
    """
    flags = [review[0] for review in reviews if review is not None]
    reasons = [review[1] for review in reviews if review is not None]
    if not flags:
        return None, None
    return "+".join(flags), "; ".join(reasons)
