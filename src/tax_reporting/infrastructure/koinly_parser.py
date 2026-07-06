"""Koinly CSV parsing utilities.

Shared parsing functions for reading Koinly transaction history and capital gains exports.
Used by both crypto_reporting application logic and token_origin domain resolution.
"""

from __future__ import annotations

import csv
import logging
import re
import unicodedata
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Final
from zoneinfo import ZoneInfo

from ..application.crypto.entities import ParsedOgrRow
from ..domain.exceptions import FileProcessingError
from ..domain.transaction import TransactionHistoryRow

# File size limits for security (prevent DoS via large files)
_MAX_CSV_BYTES: Final = 50 * 1024 * 1024  # 50 MB limit for CSV files

__all__ = [
    "DATE_FORMATS",
    "read_koinly_rows",
    "parse_koinly_datetime",
    "format_datetime",
    "normalize_asset_ticker",
    "normalize_platform_name",
    "parse_koinly_decimal",
    "parse_th_row",
    "_extract_ogr_gain_loss",
    "_parse_other_gains_row",
    "_find_and_parse_other_gains_file",
]

DATE_FORMATS: Final = (
    "%d/%m/%Y %H:%M",
    "%Y-%m-%d %H:%M:%S UTC",
    "%Y-%m-%d %H:%M:%S",
    "%d/%m/%Y",
    "%Y-%m-%d",
)


def read_koinly_rows(path: Path) -> list[dict[str, str]]:
    """Read Koinly CSV file and return rows as dictionaries.

    Args:
        path: Path to the Koinly CSV file.

    Returns:
        List of row dictionaries with non-empty values.

    Raises:
        FileProcessingError: If file size exceeds limit or header cannot be detected.
    """
    if path.is_symlink():
        raise FileProcessingError(f"Refusing to read symlink {path}: resolve to a plain file before ingesting")
    file_size = path.stat().st_size
    if file_size > _MAX_CSV_BYTES:
        raise FileProcessingError(
            f"CSV file {path.name} exceeds size limit ({file_size} bytes, max {_MAX_CSV_BYTES} bytes)"
        )
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    header_index = _detect_header_index(lines, path)
    reader = csv.DictReader(lines[header_index:])

    rows: list[dict[str, str]] = []
    for row in reader:
        if all((value is None or str(value).strip() == "") for value in row.values()):
            continue
        rows.append({key: (value or "") for key, value in row.items() if key is not None})
    return rows


def _detect_header_index(lines: list[str], path: Path) -> int:
    """Detect the header row index in a Koinly CSV file.

    Args:
        lines: CSV file lines.
        path: File path for error reporting.

    Returns:
        Index of the header row.

    Raises:
        ValueError: If header cannot be detected.
    """
    header_markers = ("Date Sold", "Date Acquired", "Date,", "Asset,Quantity", "Currency,Wallet")
    for index, line in enumerate(lines):
        if "," not in line:
            continue
        if any(marker in line for marker in header_markers):
            return index
    raise ValueError(f"Unable to detect CSV header in Koinly export: {path}")


def _format_declares_utc(date_format: str) -> bool:
    """Return True when the matched format string declares UTC.

    Koinly Transaction History dates use the format ``%Y-%m-%d %H:%M:%S UTC``,
    where the `` UTC`` suffix is a literal in the format string (NOT a ``%z``
    directive). ``datetime.strptime`` therefore never sets ``tzinfo`` for TH
    dates, so the only reliable way to distinguish TH explicit-UTC dates from
    naive CG/OGR/Income dates is to inspect the matched format string itself.

    Args:
        date_format: One of the formats in :data:`DATE_FORMATS` that matched.

    Returns:
        True iff the format string ends with the `` UTC`` literal (the TH format
        token), so a future naive format cannot satisfy it by coincidence.
    """
    return date_format.endswith(" UTC")


def parse_koinly_datetime(value: str, *, zone: ZoneInfo | None = None) -> datetime:
    """Parse a Koinly datetime string into a zone-aware datetime object.

    Naive Koinly dates (CG/OGR/Income, format ``DD/MM/YYYY HH:MM``) denote
    mainland-Portugal local time (WET/WEST), not UTC. When ``zone`` is provided
    the naive instant is stamped with that zone and converted to UTC, letting
    ``zoneinfo`` own DST transitions historically. TH dates (format
    ``YYYY-MM-DD HH:MM:SS UTC``) declare UTC via their format and are kept as
    UTC regardless of ``zone`` (the `` UTC`` suffix is a format literal, not a
    ``%z`` directive, so detection is on the matched format string, never on
    ``parsed.tzinfo``).

    Args:
        value: Datetime string from a Koinly CSV.
        zone: Optional jurisdiction ``ZoneInfo`` used to localize naive dates.
            When ``None`` (default), naive dates are stamped as UTC exactly as
            before this parameter existed, preserving backward compatibility.

    Returns:
        timezone-aware datetime in UTC. Empty strings yield the epoch sentinel
        ``datetime(1970, 1, 1, tzinfo=UTC)``.

    Raises:
        ValueError: If the date format is not supported.
    """
    text = value.strip()
    if not text:
        return datetime(1970, 1, 1, tzinfo=UTC)

    for date_format in DATE_FORMATS:
        try:
            parsed = datetime.strptime(text, date_format)  # noqa: DTZ007
        except ValueError:
            continue
        # strptime never sets tzinfo for any of our formats (TH's ` UTC` is a
        # literal, not a %z directive), so detection MUST be on the format
        # string, not on parsed.tzinfo.
        if _format_declares_utc(date_format):
            return parsed.replace(tzinfo=UTC)
        if zone is not None:
            return parsed.replace(tzinfo=zone).astimezone(UTC)
        return parsed.replace(tzinfo=UTC)
    raise ValueError(f"Unsupported Koinly date format: {value}")


def format_datetime(value: datetime) -> str:
    """Format a datetime object as ISO date string (YYYY-MM-DD).

    Args:
        value: datetime object.

    Returns:
        ISO date string.
    """
    return value.strftime("%Y-%m-%d")


def normalize_asset_ticker(asset: str) -> str:
    """Normalize asset ticker using Unicode canonical form.

    Applies NFKC normalization for compatibility but does NOT convert
    between scripts (no Cyrillic-to-Latin mapping). Non-Latin characters
    are preserved for security; they may indicate homoglyph scam tokens.

    Args:
        asset: The raw asset ticker from Koinly.

    Returns:
        Normalized asset ticker with Unicode NFKC normalization applied.
        Non-Latin script characters (Cyrillic, Greek, etc.) are preserved.
    """
    # Normalize unicode characters to canonical composed form
    asset = unicodedata.normalize("NFKC", asset)
    return asset.strip()


# Unicode codepoint bounds for the Latin script ranges used by the homoglyph
# security check in ``contains_non_latin_characters``. Anything outside these
# contiguous ranges is treated as non-Latin (potential homoglyph scam token).
_ASCII_MAX: Final = 0x7F  # End of Basic Latin (ASCII), U+0000 to U+007F
_LATIN1_SUPPLEMENT_MIN: Final = 0x80  # Start of Latin-1 Supplement (accented Latin)
_LATIN1_SUPPLEMENT_MAX: Final = 0xFF  # End of Latin-1 Supplement, U+0080 to U+00FF
_LATIN_EXTENDED_A_MIN: Final = 0x100  # Start of Latin Extended-A
_LATIN_EXTENDED_A_MAX: Final = 0x17F  # End of Latin Extended-A, U+0100 to U+017F
_LATIN_EXTENDED_B_MIN: Final = 0x180  # Start of Latin Extended-B
_LATIN_EXTENDED_B_MAX: Final = 0x24F  # End of Latin Extended-B, U+0180 to U+024F


def contains_non_latin_characters(asset: str) -> bool:
    """Check if an asset ticker contains non-Latin script characters.

    This is a security check to detect potential homoglyph scam tokens.
    Scammers use visually similar characters from other scripts (Cyrillic, Greek, etc.)
    to create fake tokens that look like legitimate ones (e.g., UЅDT vs USDT).

    Args:
        asset: The asset ticker to check.

    Returns:
        True if the asset contains characters from non-Latin scripts.
    """
    for char in asset:
        if char in {" ", "-", "_", "."}:
            continue  # Skip common separators
        codepoint = ord(char)
        # Basic Latin (ASCII): U+0000 to U+007F
        if 0x00 <= codepoint <= _ASCII_MAX:
            continue
        # Latin-1 Supplement: U+0080 to U+00FF (includes accented Latin characters)
        if _LATIN1_SUPPLEMENT_MIN <= codepoint <= _LATIN1_SUPPLEMENT_MAX:
            continue
        # Latin Extended-A: U+0100 to U+017F
        if _LATIN_EXTENDED_A_MIN <= codepoint <= _LATIN_EXTENDED_A_MAX:
            continue
        # Latin Extended-B: U+0180 to U+024F
        if _LATIN_EXTENDED_B_MIN <= codepoint <= _LATIN_EXTENDED_B_MAX:
            continue
        # Anything else is non-Latin (Cyrillic U+0400-U+04FF, Greek U+0370-U+03FF, etc.)
        return True
    return False


def normalize_platform_name(wallet: str) -> str:
    """Normalize a Koinly wallet label for downstream processing.

    Performs whitespace trimming only; no platform-specific normalization is
    applied. Platform consolidation is handled by the platform-level resolver
    (see Phase A Invariant 4). Returns ``"Unknown"`` for empty inputs so that
    downstream operator resolution can flag missing wallet labels.

    Args:
        wallet: The raw wallet name from Koinly.

    Returns:
        The trimmed wallet name, or ``"Unknown"`` for empty inputs.
    """
    cleaned = wallet.strip()
    if not cleaned:
        return "Unknown"

    return cleaned


def _normalize_koinly_decimal_text(text: str) -> str:
    """Normalize Koinly decimal text to standard Python Decimal format.

    Args:
        text: Preprocessed decimal string (whitespace stripped, quotes removed, dashes handled).

    Returns:
        String representation suitable for passing to Decimal().

    Raises:
        ValueError: If the format is ambiguous (single dot-grouped triplet).
    """
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            return text.replace(".", "").replace(",", ".")
        return text.replace(",", "")

    if "," in text:
        # Comma-grouped single-triplet (e.g. "8,400") is treated as thousands, not decimal.
        # Koinly always quotes decimal-comma values (e.g. '"8,40000000"'), so an unquoted bare
        # "8,400" is unambiguously a large integer. This is intentionally asymmetric with the
        # dot case below, where a single-group dot (e.g. "1.234") is raised as ambiguous.
        if re.fullmatch(r"[+-]?[1-9]\d{0,2}(,\d{3})+", text):
            return text.replace(",", "")
        return text.replace(",", ".")

    if "." in text and re.fullmatch(r"[+-]?[1-9]\d{0,2}(\.\d{3}){2,}", text):
        return text.replace(".", "")

    if "." in text and re.fullmatch(r"[+-]?[1-9]\d{0,2}\.\d{3}", text):
        raise ValueError(f"Ambiguous decimal format: {text!r}: dot could be thousands separator or decimal point")

    return text


def parse_koinly_decimal(value: str) -> Decimal:
    """Parse a Koinly decimal string into a Python Decimal.

    Handles European number formats, quoted values, and Koinly-specific
    encoding quirks (non-breaking spaces, em-dashes).

    Args:
        value: Raw string value from a Koinly CSV cell.

    Returns:
        Decimal representation of the value; Decimal("0") for empty/missing values.

    Raises:
        ValueError: If the decimal format is unsupported or ambiguous.
    """
    text = value.strip().replace("\u00a0", "").replace(" ", "")
    if not text:
        return Decimal("0")
    if text.startswith('"') and text.endswith('"'):
        text = text[1:-1]
    if text in {"", "-"}:
        return Decimal("0")
    text = _normalize_koinly_decimal_text(text)
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"Unsupported Koinly decimal format: {value}") from exc


def _extract_ogr_gain_loss(ogr_row: dict[str, str]) -> Decimal | None:
    """Extract gain/loss value from OGR row based on Type field.

    OGR format: Date,Asset,Amount,Value (EUR),Type,Wallet Name
    - Amount is negative for Loss (quantity, not EUR)
    - Value (EUR) is positive magnitude for both Loss and Profit
    - Type indicates direction: "Loss" = negative, "Profit" = positive

    Args:
        ogr_row: Row dictionary from Other Gains Report CSV.

    Returns:
        Negative Decimal for Loss, positive for Profit, None for invalid/zero values.
    """
    value_str = ogr_row.get("Value (EUR)", "")
    value_eur = parse_koinly_decimal(value_str)

    # Skip zero-value rows (fee tokens, dust)
    if value_eur == 0:
        return None

    row_type = ogr_row.get("Type", "").strip().lower()

    if row_type == "loss":
        return -value_eur
    elif row_type == "profit":
        return value_eur
    else:
        # Unknown type - log warning and skip
        return None


def _parse_other_gains_row(
    ogr_row: dict[str, str],
    *,
    zone: ZoneInfo | None = None,
) -> ParsedOgrRow | None:
    """Parse a single Other Gains Report row into a typed ``ParsedOgrRow``.

    All normalization happens here so downstream consumers (the derivatives
    classifier and ``_build_ogr_index``) receive ready-to-use fields and never
    re-parse the raw row:

    - ``date`` is formatted to ISO ``YYYY-MM-DD`` via ``format_datetime``. Naive
      OGR dates denote mainland-Portugal local time (WET/WEST); when ``zone`` is
      provided the date is localized to that zone and converted to UTC so the
      OGR index key lands on the same true-UTC day as the CG/TH keys.
    - ``asset`` is normalized via ``normalize_asset_ticker``
    - ``wallet`` is normalized via ``normalize_platform_name`` (whitespace
      trimming only; empty values become ``"Unknown"``)
    - ``gain_loss`` carries the signed EUR value (negative for ``Loss``,
      positive for ``Profit``) from ``_extract_ogr_gain_loss``

    Args:
        ogr_row: Row dictionary from Other Gains Report CSV.
        zone: Optional jurisdiction ``ZoneInfo`` used to localize naive dates.
            ``None`` (default) preserves the legacy UTC-stamp behavior.

    Returns:
        ``ParsedOgrRow`` with normalized fields, or ``None`` if the row has a
        zero/unknown value or cannot be parsed.
    """
    try:
        date_str = ogr_row.get("Date", "")
        date = parse_koinly_datetime(date_str, zone=zone)

        asset = normalize_asset_ticker(ogr_row.get("Asset", ""))

        gain_loss = _extract_ogr_gain_loss(ogr_row)
        if gain_loss is None:
            return None

        row_type = ogr_row.get("Type", "").strip()
        # Wallet normalization MUST happen here (not in _build_ogr_index) so the
        # rewritten index builder can be a pure summing loop. The wallet label
        # is trimmed (and empties mapped to "Unknown") at parse time; platform
        # consolidation is handled downstream by the platform-level resolver.
        wallet = normalize_platform_name(ogr_row.get("Wallet Name", ""))

        return ParsedOgrRow(
            date=format_datetime(date),
            asset=asset,
            gain_loss=gain_loss,
            row_type=row_type,
            wallet=wallet,
        )
    except ValueError:
        # Skip rows with parsing errors
        return None


def _find_report_path(koinly_dir: Path, marker: str, suffix: str) -> Path | None:
    """Find a Koinly report file by marker and suffix.

    Args:
        koinly_dir: Directory containing Koinly export files.
        marker: String marker in filename (e.g., "other_gains_report").
        suffix: File suffix (e.g., ".csv").

    Returns:
        Path to the first matching file, or None if no matches.
    """
    matches = sorted(koinly_dir.glob(f"*{marker}*{suffix}"))
    return matches[0] if matches else None


def _find_and_parse_other_gains_file(
    koinly_dir: Path,
    *,
    zone: ZoneInfo | None = None,
) -> list[ParsedOgrRow]:
    """Find and parse the Other Gains Report CSV file.

    Each CSV row is parsed by ``_parse_other_gains_row`` into a typed
    ``ParsedOgrRow`` carrying the normalized ``(date, asset, gain_loss,
    row_type, wallet)`` fields. Summing duplicate keys is intentionally NOT
    done here; that responsibility moved to ``_build_ogr_index`` so callers
    that need per-row granularity (the derivatives classifier) can consume
    the list directly.

    Args:
        koinly_dir: Directory containing Koinly export files.
        zone: Optional jurisdiction ``ZoneInfo`` forwarded to
            ``_parse_other_gains_row`` to localize naive OGR dates to UTC.
            ``None`` (default) preserves the legacy UTC-stamp behavior.

    Returns:
        List of ``ParsedOgrRow`` instances, one per non-skipped OGR row, in
        source CSV order. Empty list if the OGR file is missing.
    """
    logger = logging.getLogger(__name__)

    other_gains_file = _find_report_path(koinly_dir, "other_gains_report", ".csv")
    if other_gains_file is None:
        return []

    logger.info("Parsing Other Gains Report: %s", other_gains_file)
    rows = read_koinly_rows(other_gains_file)

    result: list[ParsedOgrRow] = []
    for row in rows:
        parsed = _parse_other_gains_row(row, zone=zone)
        if parsed is None:
            continue
        result.append(parsed)

    return result


def _normalize_optional_id(value: str) -> str | None:
    """Strip whitespace and return None for empty/whitespace-only strings.

    Used for the three identifying TH columns (TxHash, TxSrc, TxDest) which
    Invariant 3 requires to normalize blanks to None rather than empty strings.
    """
    cleaned = value.strip()
    return cleaned or None


def _normalize_optional_amount(value: str) -> Decimal | None:
    """Parse a Koinly decimal and return None for blank sending/receiving sides.

    A TH row may have only a sending side (e.g. ``crypto_withdrawal``) or only a
    receiving side (e.g. ``crypto_deposit``); the blank side is normalized to
    None for both amount and currency. ``parse_koinly_decimal`` already returns
    ``Decimal("0")`` for empty input, so we map the empty-string case to None
    before delegating.
    """
    if value.strip() == "":
        return None
    return parse_koinly_decimal(value)


def _normalize_optional_currency(value: str) -> str | None:
    """Return the stripped currency ticker, or None when the side is absent."""
    cleaned = value.strip()
    return cleaned or None


def parse_th_row(row: dict[str, str], *, row_index: int) -> TransactionHistoryRow:
    """Parse a Koinly Transaction History CSV row into a ``TransactionHistoryRow``.

    Reuses the existing ``parse_koinly_datetime``, ``parse_koinly_decimal`` and
    ``normalize_platform_name`` helpers (Invariant 6) so date/decimal/platform
    normalization stays in one place. Empty or whitespace-only values for the
    identifying fields (TxHash, TxSrc, TxDest) and for an absent sending or
    receiving side normalize to None (Invariant 3).

    Args:
        row: Row dictionary from a Koinly Transaction History CSV (as produced
            by ``read_koinly_rows``).
        row_index: 0-based source CSV row index, stored on the dataclass so two
            empty-tx-id rows never collide downstream.

    Returns:
        Frozen ``TransactionHistoryRow`` with all normalization applied.

    Raises:
        ValueError: If ``Date`` or a present amount field cannot be parsed by
            the underlying ``parse_koinly_datetime`` / ``parse_koinly_decimal``
            helpers. The error is surfaced unchanged from the helper.
    """
    utc_instant = parse_koinly_datetime(row.get("Date", ""))

    sending_amount = _normalize_optional_amount(row.get("Sent Amount", ""))
    sending_currency = _normalize_optional_currency(row.get("Sent Currency", ""))
    receiving_amount = _normalize_optional_amount(row.get("Received Amount", ""))
    receiving_currency = _normalize_optional_currency(row.get("Received Currency", ""))

    sending_wallet = normalize_platform_name(row.get("Sending Wallet", ""))
    receiving_wallet = normalize_platform_name(row.get("Receiving Wallet", ""))

    tx_hash = _normalize_optional_id(row.get("TxHash", ""))
    tx_src = _normalize_optional_id(row.get("TxSrc", ""))
    tx_dest = _normalize_optional_id(row.get("TxDest", ""))

    return TransactionHistoryRow(
        utc_instant=utc_instant,
        type=row.get("Type", "").strip(),
        tag=row.get("Tag", "").strip(),
        sending_wallet=sending_wallet,
        sending_amount=sending_amount,
        sending_currency=sending_currency,
        receiving_wallet=receiving_wallet,
        receiving_amount=receiving_amount,
        receiving_currency=receiving_currency,
        tx_hash=tx_hash,
        tx_src=tx_src,
        tx_dest=tx_dest,
        row_index=row_index,
    )
