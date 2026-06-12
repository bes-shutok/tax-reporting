"""Tests for crypto/parsing.py — file discovery and parsing helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from tax_reporting.application.crypto.parsing import (
    _decode_pdf_hex_token,
    _extract_tax_year,
    _find_report_file,
    _find_report_path,
    _MAX_PDF_BYTES,
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
