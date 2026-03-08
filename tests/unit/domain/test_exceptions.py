"""Tests for domain exception formatting."""

import pytest

from shares_reporting.domain.exceptions import FileProcessingError


@pytest.mark.unit
class TestFileProcessingErrorFormatting:
    """FileProcessingError must produce a readable string, not a raw arg tuple."""

    def test_str_with_single_arg_is_readable(self):
        err = FileProcessingError("Something went wrong")
        assert str(err) == "Something went wrong"

    def test_str_with_f_string_is_readable(self):
        row = 42
        err = FileProcessingError(f"Row {row}: Bad format")
        assert str(err) == "Row 42: Bad format"

    def test_str_does_not_produce_raw_tuple(self):
        """Regression: raising with multiple positional args produced ('Row %d: ...', 42)."""
        row = 42
        err = FileProcessingError(f"Row {row}: Invalid column")
        result = str(err)
        assert "Row 42" in result
        assert result[0] != "("  # must not look like a tuple
