"""Tests for Koinly CSV parsing utilities."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from tax_reporting.infrastructure.koinly_parser import (
    _extract_ogr_gain_loss,
    _find_and_parse_other_gains_file,
    _parse_other_gains_row,
    parse_koinly_datetime,
)


class TestKoinlyParser:
    """Test suite for Koinly parser utilities."""

    def test_parse_other_gains_row(self) -> None:
        """Test parsing a standard Other Gains Report row.

        Given OGR row with Date,Asset,Amount,Value (EUR),Type,Wallet,
        expects parsed ParsedOgrRow with date, asset, gain_loss, row_type, wallet.
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
        assert result.date == "2025-01-15"
        assert result.asset == "BTC"
        assert result.gain_loss == Decimal("25000.00")
        assert result.row_type == "Profit"
        assert result.wallet == "Binance"

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
        assert result.row_type == "Loss"
        assert result.gain_loss == Decimal("-2000.00")

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
        assert result.row_type == "Profit"
        assert result.gain_loss == Decimal("1500.00")

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
        """Test that the OGR pipeline sums values for duplicate (date, asset, wallet) keys.

        Given multiple OGR rows with the same date, asset, and wallet (e.g., funding fee,
        futures fee, and realized P&L for a derivatives position on the same day),
        the composed pipeline (_find_and_parse_other_gains_file -> _build_ogr_index)
        should sum all values instead of storing only the last one.

        This is a regression test for a bug where duplicate keys would overwrite
        previous values, causing incorrect tax calculations when multiple CG entries
        were overridden with the same OGR value and then aggregated.

        Real-world example: ByBit USDT on 2025-01-13 had three separate loss entries
        (funding fee, futures fee, realized P&L) that should sum to -147.19 EUR,
        not just store the last value of -138.73 EUR.
        """
        import csv

        from tax_reporting.application.crypto.ogr_handler import _build_ogr_index

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

        # Step 1: parse returns one ParsedOgrRow per source row (no summing yet).
        rows = _find_and_parse_other_gains_file(tmp_path)
        assert isinstance(rows, list)
        assert len(rows) == 4

        # Step 2: summing happens in _build_ogr_index.
        index = _build_ogr_index(rows)

        # Verify that duplicate keys are summed
        key_2025_01_13 = ("2025-01-13", "USDT", "ByBit")
        assert key_2025_01_13 in index

        # The three entries should sum to: -0.15 + -8.31 + -138.73 = -147.19 EUR
        expected_sum = Decimal("-147.19")
        actual_value = index[key_2025_01_13]
        assert actual_value == expected_sum, (
            f"Expected OGR index to sum duplicate keys to {expected_sum} EUR, "
            f"but got {actual_value} EUR. "
            f"This indicates duplicate keys are being overwritten instead of summed."
        )

        # Verify the different entry is stored correctly
        key_2025_01_14 = ("2025-01-14", "USDT", "ByBit")
        assert key_2025_01_14 in index
        assert index[key_2025_01_14] == Decimal("-10.00")


_LISBON = ZoneInfo("Europe/Lisbon")


class TestParseKoinlyDatetimeZone:
    """Zone-awareness tests for ``parse_koinly_datetime``.

    Naive Koinly dates (CG/OGR/Income) denote mainland-Portugal local time
    (WET in winter, WEST in summer). The parser must localize them to the
    jurisdiction zone and convert to UTC, while leaving TH explicit-UTC dates
    exactly as declared. See the crypto-timezone-normalization plan.
    """

    def test_summer_naive_local_to_utc(self) -> None:
        """Summer naive local midnight maps to the previous UTC day.

        Given ``15/06/2025 00:30`` (WEST, UTC+1) with ``zone=Europe/Lisbon``,
        expects ``2025-06-14 23:30 UTC``. Before the fix the naive value was
        stamped as UTC (``2025-06-15 00:30 UTC``), placing the disposal on the
        wrong UTC day for every cross-report match key.
        """
        result = parse_koinly_datetime("15/06/2025 00:30", zone=_LISBON)
        assert result == datetime(2025, 6, 14, 23, 30, tzinfo=UTC)

    def test_winter_naive_local_unchanged(self) -> None:
        """Winter naive local stays numerically identical (WET == UTC).

        Given ``13/01/2025 13:01`` with ``zone=Europe/Lisbon``, expects
        ``2025-01-13 13:01 UTC``. WET equals UTC, so every January fixture in
        the suite stays GREEN unchanged.
        """
        result = parse_koinly_datetime("13/01/2025 13:01", zone=_LISBON)
        assert result == datetime(2025, 1, 13, 13, 1, tzinfo=UTC)

    def test_explicit_utc_unaffected_by_zone(self) -> None:
        """A TH explicit-UTC date stays UTC regardless of the zone argument.

        Given ``2025-06-14 23:30:00 UTC`` (the TH format) with
        ``zone=Europe/Lisbon``, expects ``2025-06-14 23:30 UTC``. Detection is
        on the matched format string literally containing ``UTC``, NOT on
        ``parsed.tzinfo`` (strptime never sets tzinfo for the `` UTC`` literal).
        """
        result = parse_koinly_datetime("2025-06-14 23:30:00 UTC", zone=_LISBON)
        assert result == datetime(2025, 6, 14, 23, 30, tzinfo=UTC)

    def test_zone_none_backward_compatible(self) -> None:
        """No ``zone`` argument preserves the legacy UTC-stamp behavior.

        Given ``15/06/2025 00:30`` with no ``zone``, expects
        ``2025-06-15 00:30 UTC`` exactly as today. ``zone`` defaults to ``None``
        and ``None`` means stamp naive dates as UTC.
        """
        result = parse_koinly_datetime("15/06/2025 00:30")
        assert result == datetime(2025, 6, 15, 0, 30, tzinfo=UTC)

    def test_empty_string_epoch_sentinel(self) -> None:
        """Empty string returns the epoch sentinel unchanged by ``zone``.

        Given ``""`` with ``zone=Europe/Lisbon``, expects
        ``datetime(1970, 1, 1, tzinfo=UTC)``. The empty-string branch is
        upstream of zone handling and must not be relocalized.
        """
        result = parse_koinly_datetime("", zone=_LISBON)
        assert result == datetime(1970, 1, 1, tzinfo=UTC)

    def test_spring_forward_gap_fold_zero(self) -> None:
        """Spring-forward gap (02:00->03:00 WEST) characterized at fold=0.

        Given ``30/03/2025 02:30`` (the nonexistent local hour) with
        ``zone=Europe/Lisbon``, fold defaults to 0. ``zoneinfo`` resolves the
        gap deterministically: at fold=0 the instant is treated as the
        pre-transition WET (UTC+0) reading, yielding ``2025-03-30 01:30 UTC``.
        """
        result = parse_koinly_datetime("30/03/2025 02:30", zone=_LISBON)
        assert result == datetime(2025, 3, 30, 1, 30, tzinfo=UTC)

    def test_fall_back_ambiguity_fold_zero(self) -> None:
        """Fall-back repeated hour characterized at fold=0 (first occurrence).

        Given ``26/10/2025 01:30`` (the ambiguous WEST->WET hour) with
        ``zone=Europe/Lisbon``, fold defaults to 0, which selects the first
        occurrence under WEST (UTC+1), yielding ``2025-10-26 00:30 UTC``.
        """
        result = parse_koinly_datetime("26/10/2025 01:30", zone=_LISBON)
        assert result == datetime(2025, 10, 26, 0, 30, tzinfo=UTC)


class TestParseOtherGainsRowZone:
    """Zone-awareness tests for OGR (Other Gains Report) date parsing.

    Naive OGR dates denote mainland-Portugal local time (WET in winter, WEST in
    summer). The row parser and its loader must forward the jurisdiction zone so
    OGR index keys (date, asset, wallet) land on the true-UTC day and agree with
    the CG/TH keys (derivatives dedup, DP-014). See the crypto-timezone-
    normalization plan, Task 4.
    """

    def test_summer_date_true_utc_day(self) -> None:
        """Summer-midnight OGR Date localizes to the previous UTC day.

        Given Date ``15/06/2025 00:30`` (WEST, UTC+1) with ``zone=Europe/Lisbon``,
        expects ``ParsedOgrRow.date == "2025-06-14"``. Before the fix the naive
        value was stamped UTC and read ``2025-06-15``, desyncing the OGR index
        key from the CG/TH keys.
        """
        row = {
            "Date": "15/06/2025 00:30",
            "Asset": "USDT",
            "Amount": "143,75",
            "Value (EUR)": "140,18",
            "Type": "Profit",
            "Wallet Name": "ByBit",
        }
        result = _parse_other_gains_row(row, zone=_LISBON)
        assert result is not None
        assert result.date == "2025-06-14", (
            f"summer-midnight OGR date must map to the previous UTC day, got {result.date}"
        )

    def test_winter_date_unchanged(self) -> None:
        """Winter OGR Date is unchanged by the zone (WET == UTC).

        Given ``13/01/2025 13:01`` with ``zone=Europe/Lisbon``, expects
        ``ParsedOgrRow.date == "2025-01-13"``. Characterization protecting
        existing fixtures.
        """
        row = {
            "Date": "13/01/2025 13:01",
            "Asset": "USDT",
            "Amount": "143,75",
            "Value (EUR)": "140,18",
            "Type": "Profit",
            "Wallet Name": "ByBit",
        }
        result = _parse_other_gains_row(row, zone=_LISBON)
        assert result is not None
        assert result.date == "2025-01-13", f"winter OGR date must be unchanged, got {result.date}"

    def test_zone_forwarded_end_to_end(self, tmp_path: Path) -> None:
        """The loader forwards zone to the row parser (wiring/boundary).

        Given a temp dir with an ``*other_gains_report*.csv`` containing a
        summer-midnight row, calling
        ``_find_and_parse_other_gains_file(dir, zone=Europe/Lisbon)`` expects the
        parsed ``ParsedOgrRow.date == "2025-06-14"``. Proves the loader forwards
        ``zone`` to the row parser, not just that the leaf helper accepts it.
        """
        ogr_csv = tmp_path / "koinly_2025_other_gains_report.csv"
        ogr_csv.write_text(
            "\n".join(
                [
                    "Other gains report 2025",
                    "",
                    "Date,Asset,Amount,Value (EUR),Type,Wallet Name",
                    '15/06/2025 00:30,USDT,"143,75","140,18",Profit,ByBit',
                ]
            ),
            encoding="utf-8",
        )
        result = _find_and_parse_other_gains_file(tmp_path, zone=_LISBON)
        assert len(result) == 1, f"expected one parsed OGR row, got {len(result)}"
        assert result[0].date == "2025-06-14", (
            "loader must forward zone so the OGR date is the true-UTC day, "
            f"got {result[0].date}"
        )
