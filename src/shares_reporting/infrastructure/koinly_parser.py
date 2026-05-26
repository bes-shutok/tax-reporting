"""Koinly CSV parsing utilities.

Shared parsing functions for reading Koinly transaction history and capital gains exports.
Used by both crypto_reporting application logic and token_origin domain resolution.
"""

from __future__ import annotations

import csv
import re
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from ..domain.exceptions import FileProcessingError

# File size limits for security (prevent DoS via large files)
_MAX_CSV_BYTES: Final = 50 * 1024 * 1024  # 50 MB limit for CSV files

DATE_FORMATS: Final = (
    "%d/%m/%Y %H:%M",
    "%Y-%m-%d %H:%M:%S UTC",
    "%Y-%m-%d %H:%M:%S",
    "%d/%m/%Y",
    "%Y-%m-%d",
)


def _read_koinly_rows(path: Path) -> list[dict[str, str]]:
    """Read Koinly CSV file and return rows as dictionaries.

    Args:
        path: Path to the Koinly CSV file.

    Returns:
        List of row dictionaries with non-empty values.

    Raises:
        FileProcessingError: If file size exceeds limit or header cannot be detected.
    """
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


def _parse_koinly_datetime(value: str) -> datetime:
    """Parse a Koinly datetime string into a datetime object.

    Args:
        value: Datetime string from Koinly CSV.

    Returns:
        datetime object with UTC timezone if specified, or epoch datetime for empty strings.

    Raises:
        ValueError: If the date format is not supported.
    """
    text = value.strip()
    if not text:
        return datetime(1970, 1, 1, tzinfo=UTC)

    for date_format in DATE_FORMATS:
        try:
            parsed = datetime.strptime(text, date_format)  # noqa: DTZ007
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError:
            continue
    raise ValueError(f"Unsupported Koinly date format: {value}")


def _format_datetime(value: datetime) -> str:
    """Format a datetime object as ISO date string (YYYY-MM-DD).

    Args:
        value: datetime object.

    Returns:
        ISO date string.
    """
    return value.strftime("%Y-%m-%d")


def _normalize_asset_ticker(asset: str) -> str:
    """Normalize common character encoding issues in asset tickers.

    Fixes known encoding issues such as:
    - Cyrillic 'Т' (U+0422) instead of Latin 'T' in WBТC
    - Cyrillic 'Е' (U+0415) instead of Latin 'E'
    - Other visually similar Cyrillic-Latin character pairs

    Args:
        asset: The raw asset ticker from Koinly.

    Returns:
        Normalized asset ticker with known character substitutions applied.
    """
    # Replace commonly confused Cyrillic characters with Latin equivalents
    cyrillic_to_latin = {
        "Т": "T",  # U+0422 Cyrillic Te -> Latin T
        "Е": "E",  # U+0415 Cyrillic Ie -> Latin E
        "О": "O",  # U+041E Cyrillic O -> Latin O (same visual, different codepoint)
        "Р": "P",  # U+0420 Cyrillic Er -> Latin P
        "А": "A",  # U+0410 Cyrillic A -> Latin A
        "Н": "H",  # U+041D Cyrillic En -> Latin H
        "К": "K",  # U+041A Cyrillic Ka -> Latin K
        "М": "M",  # U+041C Cyrillic Em -> Latin M
        "С": "C",  # U+0421 Cyrillic Es -> Latin C
        "В": "B",  # U+0412 Cyrillic Ve -> Latin B
        "Х": "X",  # U+0425 Cyrillic Ha -> Latin X
        "у": "y",  # U+0443 Cyrillic U -> Latin y (lowercase)
        "е": "e",  # U+0435 Cyrillic ie -> Latin e (lowercase)
        "о": "o",  # U+043E Cyrillic o -> Latin o (lowercase)
        "р": "p",  # U+0440 Cyrillic er -> Latin p (lowercase)
        "а": "a",  # U+0430 Cyrillic a -> Latin a (lowercase)
    }
    for cyrillic, latin in cyrillic_to_latin.items():
        asset = asset.replace(cyrillic, latin)
    # Normalize unicode characters to canonical composed form
    asset = unicodedata.normalize("NFKC", asset)
    return asset.strip()


def _normalize_platform_name(wallet: str) -> str:
    """Normalize platform aliases for consistent operator resolution and aggregation.

    This function normalizes only the ByBit platform alias (e.g., "ByBit (2)" -> "ByBit")
    where the suffix represents a duplicate account in Koinly, not a distinct wallet.
    This is a repository-specific normalization per CRG-008.

    For all other wallets, including distinct numbered wallets like "Kraken (2)",
    the full wallet name is preserved to prevent incorrect aggregation of separate
    disposal events. Koinly may use numbered suffixes for genuinely distinct wallets
    on the same platform.

    Args:
        wallet: The raw wallet name from Koinly.

    Returns:
        Normalized platform name for ByBit aliases, or the original wallet name.
        Returns "Unknown" for empty wallets.
    """
    cleaned = wallet.strip()
    if not cleaned:
        return "Unknown"

    # Normalize only ByBit numbered aliases (repository-specific rule per CRG-008)
    # "ByBit (2)", "ByBit (3)", etc. -> "ByBit"
    # This must NOT match other ByBit-prefixed wallets like "ByBit Earn (2)"
    if re.match(r"^ByBit \(\d+\)$", cleaned):
        return "ByBit"

    return cleaned
