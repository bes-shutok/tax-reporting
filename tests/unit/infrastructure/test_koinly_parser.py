"""Tests for Koinly CSV parsing utilities."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from tax_reporting.infrastructure.koinly_parser import (
    _extract_ogr_gain_loss,
    _find_and_parse_other_gains_file,
    _parse_other_gains_row,
    format_datetime,
    normalize_asset_ticker,
    normalize_platform_name,
    parse_koinly_datetime,
    parse_koinly_decimal,
)


class TestKoinlyParser:
    """Test suite for Koinly parser utilities."""

    def test_parse_other_gains_row(self) -> None:
        """Test parsing a standard Other Gains Report row.

        Given OGR row with Date,Asset,Amount,Value (EUR),Type,Wallet,
        expects parsed tuple with (date, asset, amount_eur, type, wallet).
        """
        row = {
            "Date": "15/01/2025 12:30",
            "Asset": "BTC",
            "Amount": "0.5",
            "Value (EUR)": "25000.00",
            "Type": "Profit",
            "Wallet Name": "Binance",
        }
        result = _parse_other_gains_row(row)
        assert result is not None
        date, asset, amount_eur, row_type, wallet = result
        assert date == datetime(2025, 1, 15, 12, 30, tzinfo=UTC)
        assert asset == "BTC"
        assert amount_eur == Decimal("25000.00")
        assert row_type == "Profit"
        assert wallet == "Binance"

    def test_parse_other_gains_loss_type(self) -> None:
        """Test parsing OGR row with Loss type.

        Given row with Type="Loss", expects type parsed as "Loss".
        """
        row = {
            "Date": "15/01/2025 12:30",
            "Asset": "ETH",
            "Amount": "-1.0",
            "Value (EUR)": "2000.00",
            "Type": "Loss",
            "Wallet Name": "Kraken",
        }
        result = _parse_other_gains_row(row)
        assert result is not None
        date, asset, amount_eur, row_type, wallet = result
        assert row_type == "Loss"
        # Loss should return negative value
        assert amount_eur == Decimal("-2000.00")

    def test_parse_other_gains_profit_type(self) -> None:
        """Test parsing OGR row with Profit type.

        Given row with Type="Profit", expects type parsed as "Profit".
        """
        row = {
            "Date": "15/01/2025 12:30",
            "Asset": "SOL",
            "Amount": "10.0",
            "Value (EUR)": "1500.00",
            "Type": "Profit",
            "Wallet Name": "ByBit",
        }
        result = _parse_other_gains_row(row)
        assert result is not None
        date, asset, amount_eur, row_type, wallet = result
        assert row_type == "Profit"
        # Profit should return positive value
        assert amount_eur == Decimal("1500.00")

    def test_parse_other_gains_skips_fee_tokens(self) -> None:
        """Test that rows with zero Value are skipped.

        Given row with Value="0.0", expects row is skipped (not capital gain).
        """
        row = {
            "Date": "15/01/2025 12:30",
            "Asset": "USDT",
            "Amount": "0.0001",
            "Value (EUR)": "0.0",
            "Type": "Profit",
            "Wallet Name": "Unknown",
        }
        result = _extract_ogr_gain_loss(row)
        assert result is None

    def test_parse_other_gains_case_insensitive_type(self) -> None:
        """Test case-insensitive Type matching.

        Given row with Type="loss" (lowercase), expects type parsed correctly.
        """
        row = {
            "Date": "15/01/2025 12:30",
            "Asset": "DOGE",
            "Amount": "-100.0",
            "Value (EUR)": "50.00",
            "Type": "loss",  # lowercase
            "Wallet Name": "Coinbase",
        }
        result = _extract_ogr_gain_loss(row)
        assert result == Decimal("-50.00")

    def test_extract_ogr_gain_loss_uppercase_loss(self) -> None:
        """Test case-insensitive Type matching with uppercase LOSS."""
        row = {
            "Date": "15/01/2025 12:30",
            "Asset": "ADA",
            "Amount": "-500.0",
            "Value (EUR)": "100.00",
            "Type": "LOSS",  # uppercase
            "Wallet Name": "Binance",
        }
        result = _extract_ogr_gain_loss(row)
        assert result == Decimal("-100.00")

    def test_extract_ogr_gain_loss_mixed_case_profit(self) -> None:
        """Test case-insensitive Type matching with mixed case PrOfIt."""
        row = {
            "Date": "15/01/2025 12:30",
            "Asset": "DOT",
            "Amount": "50.0",
            "Value (EUR)": "500.00",
            "Type": "PrOfIt",  # mixed case
            "Wallet Name": "Kraken",
        }
        result = _extract_ogr_gain_loss(row)
        assert result == Decimal("500.00")

    def test_extract_ogr_gain_loss_unknown_type_returns_none(self) -> None:
        """Test that unknown Type returns None."""
        row = {
            "Date": "15/01/2025 12:30",
            "Asset": "XRP",
            "Amount": "100.0",
            "Value (EUR)": "200.00",
            "Type": "UnknownType",
            "Wallet Name": "Coinbase",
        }
        result = _extract_ogr_gain_loss(row)
        assert result is None

    def test_ogr_index_sums_duplicate_keys(self, tmp_path) -> None:
        """Test that OGR index sums values for duplicate (date, asset, wallet) keys.

        Given multiple OGR rows with the same date, asset, and wallet (e.g., funding fee,
        futures fee, and realized P&L for a derivatives position on the same day),
        the index should sum all values instead of storing only the last one.

        This is a regression test for a bug where duplicate keys would overwrite
        previous values, causing incorrect tax calculations when multiple CG entries
        were overridden with the same OGR value and then aggregated.

        Real-world example: ByBit USDT on 2025-01-13 had three separate loss entries
        (funding fee, futures fee, realized P&L) that should sum to -147.19 EUR,
        not just store the last value of -138.73 EUR.
        """
        import csv

        # Create a mock OGR file with multiple entries for the same key
        ogr_file = tmp_path / "test_other_gains_report.csv"
        with ogr_file.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Date", "Asset", "Amount", "Value (EUR)", "Type", "Wallet Name"])
            # Three entries with same (date, asset, wallet) key
            writer.writerow(["13/01/2025 08:00", "USDT", "-0,15390924", "0,15", "Loss", "ByBit"])
            writer.writerow(["13/01/2025 13:01", "USDT", "-8,51539785", "8,31", "Loss", "ByBit"])
            writer.writerow(["13/01/2025 13:01", "USDT", "-142,11300000", "138,73", "Loss", "ByBit"])
            # One different entry (different date)
            writer.writerow(["14/01/2025 10:00", "USDT", "-10,00", "10,00", "Loss", "ByBit"])

        # Parse the OGR file
        result = _find_and_parse_other_gains_file(tmp_path)

        # Verify that duplicate keys are summed
        key_2025_01_13 = ("2025-01-13", "USDT", "ByBit")
        assert key_2025_01_13 in result

        # The three entries should sum to: -0.15 + -8.31 + -138.73 = -147.19 EUR
        expected_sum = Decimal("-147.19")
        actual_value = result[key_2025_01_13]
        assert actual_value == expected_sum, (
            f"Expected OGR index to sum duplicate keys to {expected_sum} EUR, "
            f"but got {actual_value} EUR. "
            f"This indicates duplicate keys are being overwritten instead of summed."
        )

        # Verify the different entry is stored correctly
        key_2025_01_14 = ("2025-01-14", "USDT", "ByBit")
        assert key_2025_01_14 in result
        assert result[key_2025_01_14] == Decimal("-10.00")
