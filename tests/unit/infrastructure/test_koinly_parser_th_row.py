"""Tests for ``parse_th_row`` parser delegation to existing koinly helpers.

Covers Invariant 6: ``parse_th_row`` MUST reuse ``parse_koinly_datetime``,
``parse_koinly_decimal`` and ``normalize_platform_name`` rather than
re-implementing their behavior.
"""

from __future__ import annotations

import pytest

from tax_reporting.infrastructure.koinly_parser import (
    normalize_platform_name,
    parse_th_row,
)


def _base_row() -> dict[str, str]:
    """Return a minimal valid TH row dict that exercises no edge cases."""
    return {
        "Date": "2025-06-14 12:33:01 UTC",
        "Type": "crypto_deposit",
        "Tag": "reward",
        "Sending Wallet": "",
        "Sent Amount": "",
        "Sent Currency": "",
        "Receiving Wallet": "Kraken",
        "Received Amount": "1,25000000",
        "Received Currency": "ETH",
        "TxHash": "0xh",
        "TxSrc": "addrA",
        "TxDest": "addrB",
    }


class TestParseThRowDelegation:
    """Tests that parse_th_row delegates to existing koinly_parser helpers."""

    def test_delegates_to_parse_koinly_datetime(self) -> None:
        """Given a garbage Date, expects the ValueError from parse_koinly_datetime."""
        row = _base_row()
        row["Date"] = "not-a-date"
        with pytest.raises(ValueError, match="Unsupported Koinly date format"):
            parse_th_row(row, row_index=0)

    def test_delegates_to_parse_koinly_decimal(self) -> None:
        """Given a garbage Sent Amount, expects ValueError from parse_koinly_decimal."""
        row = _base_row()
        row["Sent Amount"] = "not-a-number"
        with pytest.raises(ValueError, match="Unsupported Koinly decimal format"):
            parse_th_row(row, row_index=0)

    def test_delegates_to_normalize_platform_name(self) -> None:
        """Given Receiving Wallet='Kraken', expects normalize_platform_name applied."""
        row = _base_row()
        row["Receiving Wallet"] = "Kraken"
        parsed = parse_th_row(row, row_index=0)
        assert parsed.receiving_wallet == normalize_platform_name("Kraken")
