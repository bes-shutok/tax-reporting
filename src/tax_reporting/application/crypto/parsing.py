"""Crypto file discovery and parsing helpers.

This module extracts low-level file discovery, parsing, and utility functions
from crypto_reporting.py to improve modularity and testability.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from tax_reporting.infrastructure.config import TaxJurisdictionConfig

from .entities import CryptoCompletePdfSummary

# PDF parsing size limit: 20 MB (increased from 10 MB due to growing Koinly report sizes)
_MAX_PDF_BYTES: Final = 20 * 1024 * 1024

# ASCII character code for max ASCII value (used in UTF-16BE detection)
_MAX_ASCII_CODE: Final = 128


def _extract_tax_year(
    koinly_dir: Path,
    capital_file: Path | None,
    income_file: Path | None,
    *,
    jurisdiction: TaxJurisdictionConfig | None = None,
) -> int:
    """Extract the tax year from Koinly file names or directory name.

    Tries multiple sources in order:
    1. Filename pattern: "koinly_YYYY_*" in capital or income files
    2. Jurisdiction fiscal_year (when provided)
    3. Directory name: YYYY pattern in koinly_dir name
    4. Fallback: current year

    Args:
        koinly_dir: Directory containing Koinly exports.
        capital_file: Optional capital gains report file path.
        income_file: Optional income report file path.
        jurisdiction: Optional tax jurisdiction config for fiscal year fallback.

    Returns:
        Extracted or inferred tax year as integer.
    """
    # Try to extract year from capital or income file names
    for candidate in [capital_file, income_file]:
        if candidate is None:
            continue
        match = re.search(r"koinly_(\d{4})_", candidate.name)
        if match:
            return int(match.group(1))

    # Try jurisdiction fiscal year
    if jurisdiction is not None:
        return jurisdiction.fiscal_year

    # Try directory name (e.g., "koinly_2022")
    fallback_match = re.search(r"(\d{4})", koinly_dir.name)
    if fallback_match:
        return int(fallback_match.group(1))

    # Fallback to current year
    return datetime.now(tz=UTC).year


def _parse_complete_tax_report_pdf(path: Path) -> CryptoCompletePdfSummary | None:
    """Parse Koinly complete tax report PDF for metadata.

    Extracts period and timezone information from embedded PDF tokens.
    Skips processing for symlinks (security), oversized files (> _MAX_PDF_BYTES),
    and files that cannot be read.

    Args:
        path: Path to the PDF file.

    Returns:
        CryptoCompletePdfSummary with extracted metadata, or None if parsing fails.
    """
    if path.is_symlink():
        logging.getLogger(__name__).warning(
            "PDF file %s is a symlink; skipping metadata extraction for security",
            path.name,
        )
        return None

    try:
        file_size = path.stat().st_size
    except OSError as exc:
        logging.getLogger(__name__).warning(
            "Could not stat PDF file %s: %s; skipping metadata extraction",
            path.name,
            exc,
        )
        return None

    if file_size > _MAX_PDF_BYTES:
        logging.getLogger(__name__).warning(
            "PDF file %s exceeds size limit (%d bytes, max %d bytes) - skipping metadata extraction",
            path.name,
            file_size,
            _MAX_PDF_BYTES,
        )
        return None

    try:
        content = path.read_bytes()
    except OSError as exc:
        logging.getLogger(__name__).warning(
            "Could not read PDF file %s: %s; skipping metadata extraction",
            path.name,
            exc,
        )
        return None

    hex_tokens = re.findall(rb"<([0-9A-Fa-f]{2,})>", content)
    decoded_tokens = [_decode_pdf_hex_token(token) for token in hex_tokens]
    cleaned_tokens = [token for token in decoded_tokens if token]

    if not cleaned_tokens:
        return None

    joined = " ".join(cleaned_tokens)
    period_match = re.search(r"\b\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}\s+to\s+\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}\b", joined)
    timezone_match = re.search(r"\b[A-Za-z]+/[A-Za-z_]+(?:/[A-Za-z_]+)?\b", joined)

    return CryptoCompletePdfSummary(
        period=period_match.group(0) if period_match else None,
        timezone=timezone_match.group(0) if timezone_match else None,
        extracted_tokens=len(cleaned_tokens),
    )


def _decode_pdf_hex_token(token: bytes) -> str:
    """Decode a hexadecimal token from PDF content.

    PDFs embed text as hexadecimal sequences. This function decodes those tokens,
    handling both UTF-8 and UTF-16BE encodings (detected by null byte presence).

    Args:
        token: Hex-encoded bytes (e.g., b"74657374" for "test").

    Returns:
        Decoded string with null bytes stripped, or empty string on failure.
    """
    if len(token) % 2 != 0:
        return ""

    try:
        raw = bytes.fromhex(token.decode("ascii"))
    except ValueError:
        return ""

    if not raw:
        return ""

    # Detect encoding: UTF-16BE has consistent null byte pattern (every other byte is null)
    # UTF-8 with embedded nulls is rare; check if the pattern looks like UTF-16BE
    # For UTF-16BE, bytes at even positions should be null for ASCII text
    has_null_bytes = b"\x00" in raw
    # Check if this looks like UTF-16BE (null bytes at regular intervals for ASCII range)
    looks_like_utf16be = has_null_bytes and all(raw[i] == 0 for i in range(0, len(raw), 2) if raw[i] < _MAX_ASCII_CODE)

    text = raw.decode("utf-16-be", errors="ignore") if looks_like_utf16be else raw.decode("utf-8", errors="ignore")
    text = text.replace("\x00", "").strip()
    return text if text else ""


def _register_skipped_zero_asset(
    skipped_assets: dict[tuple[str, str], dict], section: str, asset: str, suspicious: bool = False
) -> None:
    """Register a skipped zero-value asset.

    Tracks assets that were skipped due to zero value, organized by section
    (capital_gains, income, holdings_opening, holdings_closing) and asset ticker.

    Args:
        skipped_assets: Dict tracking (section, asset) -> {"count": int, "suspicious": bool}.
        section: Source section (e.g., "capital_gains", "income").
        asset: Asset ticker.
        suspicious: True if asset contains non-Latin characters (potential scam token).
    """
    cleaned_asset = asset or "UNKNOWN_ASSET"
    key = (section, cleaned_asset)
    if key not in skipped_assets:
        skipped_assets[key] = {"count": 0, "suspicious": suspicious}
    skipped_assets[key]["count"] += 1
    # If any instance of this asset is suspicious, mark the whole entry as suspicious
    if suspicious:
        skipped_assets[key]["suspicious"] = True

