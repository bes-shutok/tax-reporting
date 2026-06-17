"""Tests for crypto/parsing.py — file discovery and parsing helpers."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from tax_reporting.application.crypto.entities import ParsedOgrRow
from tax_reporting.application.crypto.ogr_handler import _build_ogr_index
from tax_reporting.application.crypto.parsing import (
    _MAX_PDF_BYTES,
    _decode_pdf_hex_token,
    _extract_tax_year,
    _find_report_file,
    _find_report_path,
)
from tax_reporting.infrastructure.koinly_parser import (
    _find_and_parse_other_gains_file,
)


class TestFindReportFile:
    """Tests for _find_report_file()."""

    def test_find_report_file_exists(self, tmp_path: Path) -> None:
        """Given directory with '*capital_gains_report*.csv', returns path to file."""
        # Arrange: create directory with matching file (marker in filename)
        report_file = tmp_path / "koinly_2024_capital_gains_report.csv"
        report_file.write_text("header\nrow1\nrow2\n")

        # Act
        result = _find_report_file(tmp_path, "capital_gains_report")

        # Assert
        assert result == report_file

    def test_find_report_file_missing(self, tmp_path: Path) -> None:
        """Given directory without matching file, returns None."""
        # Arrange: empty directory
        assert not list(tmp_path.iterdir())

        # Act
        result = _find_report_file(tmp_path, "capital_gains_report")

        # Assert
        assert result is None


class TestFindReportPath:
    """Tests for _find_report_path()."""

    def test_find_report_path_csv(self, tmp_path: Path) -> None:
        """Given directory with '*marker*.csv' file, returns path to file."""
        # Arrange
        report_file = tmp_path / "koinly_2024_income_report.csv"
        report_file.write_text("data\n")

        # Act
        result = _find_report_path(tmp_path, "income_report", ".csv")

        # Assert
        assert result == report_file

    def test_find_report_path_pdf(self, tmp_path: Path) -> None:
        """Given directory with '*complete_tax_report*.pdf' file, returns path to file."""
        # Arrange: marker must be in filename
        report_file = tmp_path / "koinly_complete_tax_report.pdf"
        report_file.write_bytes(b"%PDF-1.4\n")

        # Act
        result = _find_report_path(tmp_path, "complete_tax_report", ".pdf")

        # Assert
        assert result == report_file

    def test_find_report_path_missing(self, tmp_path: Path) -> None:
        """Given directory without matching file, returns None."""
        # Act
        result = _find_report_path(tmp_path, "missing_marker", ".csv")

        # Assert
        assert result is None

    def test_find_report_path_multiple_matches(self, tmp_path: Path) -> None:
        """Given directory with multiple matching files, returns first sorted match."""
        # Arrange: create multiple matching files
        (tmp_path / "B-File.csv").write_text("b\n")
        (tmp_path / "A-File.csv").write_text("a\n")
        (tmp_path / "C-File.csv").write_text("c\n")

        # Act
        result = _find_report_path(tmp_path, "File", ".csv")

        # Assert: should return "A-File.csv" (alphabetically first)
        assert result == tmp_path / "A-File.csv"


class TestExtractTaxYear:
    """Tests for _extract_tax_year()."""

    def test_extract_tax_year_from_capital_file(self, tmp_path: Path) -> None:
        """Given '2024-Capital Gains Report.csv', returns 2024."""
        # Arrange
        capital_file = tmp_path / "koinly_2024_capital_gains_report.csv"
        capital_file.write_text("data\n")

        # Act
        result = _extract_tax_year(tmp_path, capital_file, None)

        # Assert
        assert result == 2024

    def test_extract_tax_year_from_income_file(self, tmp_path: Path) -> None:
        """Given '2023-Income Report.csv', returns 2023."""
        # Arrange
        income_file = tmp_path / "koinly_2023_income_report.csv"
        income_file.write_text("data\n")

        # Act
        result = _extract_tax_year(tmp_path, None, income_file)

        # Assert
        assert result == 2023

    def test_extract_tax_year_fallback_to_jurisdiction(self, tmp_path: Path, monkeypatch) -> None:
        """Given files without year, returns jurisdiction.fiscal_year."""
        # Arrange: mock jurisdiction
        class MockJurisdiction:
            fiscal_year = 2025

        capital_file = tmp_path / "Capital_Gains_Report.csv"
        capital_file.write_text("data\n")

        # Act
        result = _extract_tax_year(tmp_path, capital_file, None, jurisdiction=MockJurisdiction())

        # Assert
        assert result == 2025

    def test_extract_tax_year_fallback_to_directory_name(self, tmp_path: Path) -> None:
        """Given no year in files and no jurisdiction, extracts from directory name."""
        # Arrange: create subdirectory with year in name
        year_dir = tmp_path / "koinly_2022"
        year_dir.mkdir()
        capital_file = year_dir / "Capital_Gains_Report.csv"
        capital_file.write_text("data\n")

        # Act
        result = _extract_tax_year(year_dir, capital_file, None)

        # Assert
        assert result == 2022

    def test_extract_tax_year_fallback_to_current_year(self, tmp_path: Path, monkeypatch) -> None:
        """Given no year anywhere, returns current year."""
        # Arrange: create directory without year patterns
        capital_file = tmp_path / "report.csv"
        capital_file.write_text("data\n")

        # Mock datetime.now() to return a fixed year for predictable testing
        import datetime
        fixed_date = datetime.datetime(2026, 6, 11, tzinfo=datetime.UTC)
        monkeypatch.setattr("tax_reporting.application.crypto.parsing.datetime", type("MockDatetime", (), {"now": lambda tz: fixed_date}))

        # Act
        result = _extract_tax_year(tmp_path, capital_file, None)

        # Assert
        assert result == 2026


class TestDecodePdfHexToken:
    """Tests for _decode_pdf_hex_token()."""

    def test_decode_pdf_hex_token_valid_utf8(self) -> None:
        """Given valid hex token bytes, returns decoded string."""
        # Arrange: "test" in hex
        token = b"74657374"

        # Act
        result = _decode_pdf_hex_token(token)

        # Assert
        assert result == "test"

    def test_decode_pdf_hex_token_valid_utf16_be(self) -> None:
        """Given valid UTF-16BE hex token with null bytes, returns decoded string."""
        # Arrange: "AB" in UTF-16BE hex (00 41 00 42)
        token = b"00410042"

        # Act
        result = _decode_pdf_hex_token(token)

        # Assert
        assert result == "AB"

    def test_decode_pdf_hex_token_invalid_length(self) -> None:
        """Given hex token with odd length, returns empty string."""
        # Arrange: odd-length hex string
        token = b"746"

        # Act
        result = _decode_pdf_hex_token(token)

        # Assert
        assert result == ""

    def test_decode_pdf_hex_token_invalid_hex(self) -> None:
        """Given invalid hex characters, returns empty string."""
        # Arrange: invalid hex
        token = b"GGHH"

        # Act
        result = _decode_pdf_hex_token(token)

        # Assert
        assert result == ""

    def test_decode_pdf_hex_token_empty_after_decode(self) -> None:
        """Given hex that decodes to empty/null bytes, returns empty string."""
        # Arrange: hex for "00 00" (null bytes)
        token = b"0000"

        # Act
        result = _decode_pdf_hex_token(token)

        # Assert
        assert result == ""

    def test_decode_pdf_hex_token_with_null_bytes(self) -> None:
        """Given UTF-16BE token, strips null bytes and returns text."""
        # Arrange: "AB" in UTF-16BE hex (00 41 00 42)
        token = b"00410042"

        # Act
        result = _decode_pdf_hex_token(token)

        # Assert
        assert result == "AB"


class TestMaxPdfBytes:
    """Tests for _MAX_PDF_BYTES constant."""

    def test_max_pdf_bytes_is_defined(self) -> None:
        """_MAX_PDF_BYTES constant is defined."""
        # Assert: constant exists and is a positive int
        assert isinstance(_MAX_PDF_BYTES, int)
        assert _MAX_PDF_BYTES > 0

    def test_max_pdf_bytes_value(self) -> None:
        """_MAX_PDF_BYTES is set to 20 MB."""
        # Assert: 20 MB = 20 * 1024 * 1024 bytes
        expected = 20 * 1024 * 1024
        assert _MAX_PDF_BYTES == expected


# =============================================================================
# Tests for _find_and_parse_other_gains_file (Task 6: list[ParsedOgrRow] return)
# =============================================================================

_OTHER_GAINS_CSV_HEADER = "Date,Asset,Amount,Value (EUR),Type,Wallet Name\n"


def _write_other_gains_csv(directory: Path, rows: list[dict[str, str]]) -> Path:
    """Write a minimal Other Gains Report CSV into ``directory`` and return its path."""
    import csv as _csv

    path = directory / "koinly_2025_other_gains_report.csv"
    fieldnames = ["Date", "Asset", "Amount", "Value (EUR)", "Type", "Wallet Name"]
    with path.open("w", newline="") as fh:
        writer = _csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return path


class TestOtherGainsParse:
    """Task 6 RED tests: _find_and_parse_other_gains_file returns list[ParsedOgrRow]."""

    def test_returns_list_of_parsed_rows(self, tmp_path: Path) -> None:
        """Given an OGR CSV with 3 rows, returns list[ParsedOgrRow] length 3.

        Each row carries (date, asset, gain_loss, row_type, wallet). The parser
        returns a list of typed rows, NOT a pre-summed dict.
        """
        _write_other_gains_csv(
            tmp_path,
            [
                {
                    "Date": "13/01/2025 13:01",
                    "Asset": "USDT",
                    "Amount": "-142,11",
                    "Value (EUR)": "138,73",
                    "Type": "Loss",
                    "Wallet Name": "ByBit",
                },
                {
                    "Date": "14/01/2025 10:30",
                    "Asset": "BTC",
                    "Amount": "0,5",
                    "Value (EUR)": "500,00",
                    "Type": "Profit",
                    "Wallet Name": "Kraken",
                },
                {
                    "Date": "15/01/2025 09:00",
                    "Asset": "ETH",
                    "Amount": "1,0",
                    "Value (EUR)": "250,00",
                    "Type": "Profit",
                    "Wallet Name": "Gate.io",
                },
            ],
        )

        result = _find_and_parse_other_gains_file(tmp_path)

        # The parser must return a list of ParsedOgrRow, NOT a pre-summed dict.
        assert isinstance(result, list)
        assert len(result) == 3
        assert all(isinstance(row, ParsedOgrRow) for row in result)

        # Each row carries the parsed fields.
        by_key = {(r.date, r.asset, r.wallet): r for r in result}
        assert ("2025-01-13", "USDT", "ByBit") in by_key
        assert by_key[("2025-01-13", "USDT", "ByBit")].gain_loss == Decimal("-138.73")
        assert by_key[("2025-01-13", "USDT", "ByBit")].row_type == "Loss"

        assert ("2025-01-14", "BTC", "Kraken") in by_key
        assert by_key[("2025-01-14", "BTC", "Kraken")].gain_loss == Decimal("500.00")
        assert by_key[("2025-01-14", "BTC", "Kraken")].row_type == "Profit"

        assert ("2025-01-15", "ETH", "Gate.io") in by_key
        assert by_key[("2025-01-15", "ETH", "Gate.io")].gain_loss == Decimal("250.00")

    def test_preserves_per_row_type(self, tmp_path: Path) -> None:
        """Two OGR rows on the same key with different Type appear separately.

        Rows share the same (date, asset, wallet) key but have different Type
        (Profit and Loss). Both appear separately with original Type preserved,
        no summing at parse time.
        """
        _write_other_gains_csv(
            tmp_path,
            [
                {
                    "Date": "13/01/2025 13:01",
                    "Asset": "USDT",
                    "Amount": "-4,17",
                    "Value (EUR)": "4,17",
                    "Type": "Loss",
                    "Wallet Name": "ByBit",
                },
                {
                    "Date": "13/01/2025 13:01",
                    "Asset": "USDT",
                    "Amount": "140,18",
                    "Value (EUR)": "140,18",
                    "Type": "Profit",
                    "Wallet Name": "ByBit",
                },
            ],
        )

        result = _find_and_parse_other_gains_file(tmp_path)

        # The parser must NOT pre-sum: both rows appear separately with original Type.
        assert isinstance(result, list)
        assert len(result) == 2

        row_types = {r.row_type for r in result}
        assert row_types == {"Loss", "Profit"}

        losses = [r for r in result if r.row_type == "Loss"]
        profits = [r for r in result if r.row_type == "Profit"]
        assert len(losses) == 1
        assert len(profits) == 1
        assert losses[0].gain_loss == Decimal("-4.17")
        assert profits[0].gain_loss == Decimal("140.18")


class TestBuildOgrIndex:
    """Task 6 RED tests: _build_ogr_index(rows: list[ParsedOgrRow]) sums into dict."""

    def test_sums_into_dict(self) -> None:
        """Given list[ParsedOgrRow] with duplicate keys, _build_ogr_index sums values.

        Returns dict[(date, asset, wallet), Decimal] with values summed across
        rows sharing the same key.
        """
        rows = [
            ParsedOgrRow(
                date="2025-01-13",
                asset="USDT",
                gain_loss=Decimal("-4.17"),
                row_type="Loss",
                wallet="ByBit",
            ),
            ParsedOgrRow(
                date="2025-01-13",
                asset="USDT",
                gain_loss=Decimal("140.18"),
                row_type="Profit",
                wallet="ByBit",
            ),
        ]

        index = _build_ogr_index(rows)

        assert isinstance(index, dict)
        # Duplicate keys are summed into a single Decimal value.
        assert index[("2025-01-13", "USDT", "ByBit")] == Decimal("136.01")

    def test_backward_compat_matches_old_behavior(self, tmp_path: Path) -> None:
        """Composed pipeline produces the same dict the old single call produced.

        Given ByBit Case 1 fixtures, _build_ogr_index(_find_and_parse_other_gains_file(
        koinly_dir)) produces the same dict the old _find_and_parse_other_gains_file
        produced. The old function returned dict[(date, asset, wallet), Decimal] with
        summed values. The new pipeline is _find_and_parse_other_gains_file ->
        list[ParsedOgrRow] followed by _build_ogr_index summing into the same dict.
        This test guards backward compatibility: the composed output must equal the
        old single-call output shape.
        """
        _write_other_gains_csv(
            tmp_path,
            [
                {
                    "Date": "13/01/2025 13:01",
                    "Asset": "USDT",
                    "Amount": "-4,17",
                    "Value (EUR)": "4,17",
                    "Type": "Loss",
                    "Wallet Name": "ByBit",
                },
                {
                    "Date": "13/01/2025 13:01",
                    "Asset": "USDT",
                    "Amount": "140,18",
                    "Value (EUR)": "140,18",
                    "Type": "Profit",
                    "Wallet Name": "ByBit",
                },
            ],
        )

        rows = _find_and_parse_other_gains_file(tmp_path)
        index = _build_ogr_index(rows)

        # The composed pipeline must produce the old single-call shape.
        assert isinstance(index, dict)
        # Old behavior summed the two rows: -4.17 + 140.18 = 136.01
        assert index[("2025-01-13", "USDT", "ByBit")] == Decimal("136.01")
