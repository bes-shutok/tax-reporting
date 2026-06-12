"""Tests for crypto/validation.py validation helpers."""

from __future__ import annotations

import pytest
from tax_reporting.application.crypto.validation import (
    _is_temporally_valid,
    _parse_transaction_date,
    _validate_iso_date,
)


class TestValidateIsoDate:
    """Tests for _validate_iso_date function."""

    def test_validate_iso_date_valid(self) -> None:
        """Given a valid ISO date, returns the date string unchanged."""
        result = _validate_iso_date("2024-06-15")
        assert result == "2024-06-15"

    def test_validate_iso_date_invalid_format(self) -> None:
        """Given date with slashes instead of dashes, raises ValueError with expected message."""
        with pytest.raises(ValueError, match="expected YYYY-MM-DD"):
            _validate_iso_date("2024/06/15")

    def test_validate_iso_date_out_of_range(self) -> None:
        """Given date before reasonable range, raises ValueError with out-of-range message."""
        with pytest.raises(ValueError, match="out of reasonable range"):
            _validate_iso_date("1999-01-01")

    def test_validate_iso_date_missing_zero_padding_month(self) -> None:
        """Given date with unpadded month, raises ValueError."""
        with pytest.raises(ValueError, match="zero-padding required"):
            _validate_iso_date("2024-1-01")

    def test_validate_iso_date_missing_zero_padding_day(self) -> None:
        """Given date with unpadded day, raises ValueError."""
        with pytest.raises(ValueError, match="zero-padding required"):
            _validate_iso_date("2024-01-1")

    def test_validate_iso_date_missing_zero_padding_both(self) -> None:
        """Given date with unpadded month and day, raises ValueError."""
        with pytest.raises(ValueError, match="zero-padding required"):
            _validate_iso_date("2024-1-1")

    def test_validate_iso_date_extra_padding_month(self) -> None:
        """Given date with over-padded month, raises ValueError."""
        with pytest.raises(ValueError, match="zero-padding required"):
            _validate_iso_date("2024-001-01")

    def test_validate_iso_date_non_numeric_parts(self) -> None:
        """Given date with non-numeric characters, raises ValueError."""
        with pytest.raises(ValueError, match="non-numeric characters"):
            _validate_iso_date("2024-ab-cd")

    def test_validate_iso_date_invalid_calendar_date_february_30(self) -> None:
        """Given Feb 30 (invalid calendar date), raises ValueError."""
        with pytest.raises(ValueError, match="Invalid date"):
            _validate_iso_date("2024-02-30")

    def test_validate_iso_date_invalid_calendar_date_april_31(self) -> None:
        """Given Apr 31 (invalid calendar date), raises ValueError."""
        with pytest.raises(ValueError, match="Invalid date"):
            _validate_iso_date("2024-04-31")

    def test_validate_iso_date_leap_year_feb_29_valid(self) -> None:
        """Given Feb 29 in a leap year, succeeds."""
        result = _validate_iso_date("2024-02-29")
        assert result == "2024-02-29"

    def test_validate_iso_date_non_leap_year_feb_29_invalid(self) -> None:
        """Given Feb 29 in a non-leap year, raises ValueError."""
        with pytest.raises(ValueError, match="Invalid date"):
            _validate_iso_date("2023-02-29")

    def test_validate_iso_date_year_after_max(self) -> None:
        """Given year after max valid year, raises ValueError."""
        with pytest.raises(ValueError, match="out of reasonable range"):
            _validate_iso_date("2101-01-01")

    def test_validate_iso_date_empty_string(self) -> None:
        """Given empty string, raises ValueError."""
        with pytest.raises(ValueError, match="expected YYYY-MM-DD"):
            _validate_iso_date("")

    def test_validate_iso_date_only_year(self) -> None:
        """Given only year part, raises ValueError."""
        with pytest.raises(ValueError, match="expected YYYY-MM-DD"):
            _validate_iso_date("2024")

    def test_validate_iso_date_year_month_only(self) -> None:
        """Given year-month only, raises ValueError."""
        with pytest.raises(ValueError, match="expected YYYY-MM-DD"):
            _validate_iso_date("2024-06")

    def test_validate_iso_date_too_many_parts(self) -> None:
        """Given date with too many parts, raises ValueError."""
        with pytest.raises(ValueError, match="expected YYYY-MM-DD"):
            _validate_iso_date("2024-06-15-extra")


class TestParseTransactionDate:
    """Tests for _parse_transaction_date function."""

    def test_parse_transaction_date_none(self) -> None:
        """Given None, returns None."""
        result = _parse_transaction_date(None)
        assert result is None

    def test_parse_transaction_date_empty_string(self) -> None:
        """Given empty string, returns None."""
        result = _parse_transaction_date("")
        assert result is None

    def test_parse_transaction_date_koinly_format(self) -> None:
        """Given Koinly datetime format, returns ISO date part."""
        result = _parse_transaction_date("2024-06-15 14:30:45")
        assert result == "2024-06-15"

    def test_parse_transaction_date_iso_format(self) -> None:
        """Given ISO date format, returns it unchanged."""
        result = _parse_transaction_date("2024-06-15")
        assert result == "2024-06-15"

    def test_parse_transaction_date_invalid_koinly_format(self) -> None:
        """Given invalid datetime format, raises ValueError."""
        with pytest.raises(ValueError, match="Unsupported transaction date format"):
            _parse_transaction_date("2024-06-15 14:30")  # Missing seconds

    def test_parse_transaction_date_invalid_time_range(self) -> None:
        """Given time component with invalid hour, raises ValueError."""
        with pytest.raises(ValueError, match="Unsupported transaction date format"):
            _parse_transaction_date("2024-06-15 24:00:00")  # Hour > 23

    def test_parse_transaction_date_leading_trailing_whitespace(self) -> None:
        """Given date with leading/trailing whitespace, strips and parses."""
        result = _parse_transaction_date("  2024-06-15  ")
        assert result == "2024-06-15"

    def test_parse_transaction_date_koinly_with_whitespace(self) -> None:
        """Given Koinly datetime with surrounding whitespace, strips and parses."""
        result = _parse_transaction_date("  2024-06-15 14:30:45  ")
        assert result == "2024-06-15"

    def test_parse_transaction_date_invalid_minute(self) -> None:
        """Given time component with invalid minute, raises ValueError."""
        with pytest.raises(ValueError, match="Unsupported transaction date format"):
            _parse_transaction_date("2024-06-15 14:60:00")  # Minute > 59

    def test_parse_transaction_date_invalid_second(self) -> None:
        """Given time component with invalid second, raises ValueError."""
        with pytest.raises(ValueError, match="Unsupported transaction date format"):
            _parse_transaction_date("2024-06-15 14:30:60")  # Second > 59

    def test_parse_transaction_date_time_missing_zero_padding(self) -> None:
        """Given time without zero-padding, raises ValueError."""
        with pytest.raises(ValueError, match="Unsupported transaction date format"):
            _parse_transaction_date("2024-06-15 14:5:45")  # Minute not zero-padded

    def test_parse_transaction_date_extra_spaces(self) -> None:
        """Given datetime with extra spaces, raises ValueError."""
        with pytest.raises(ValueError, match="Unsupported transaction date format"):
            _parse_transaction_date("2024-06-15  14:30:45")  # Extra space

    def test_parse_transaction_date_non_iso_separator(self) -> None:
        """Given date with slash separator, raises ValueError."""
        with pytest.raises(ValueError, match="Unsupported transaction date format"):
            _parse_transaction_date("2024/06/15")

    def test_parse_transaction_date_time_non_numeric(self) -> None:
        """Given time with non-numeric parts, raises ValueError."""
        with pytest.raises(ValueError, match="Unsupported transaction date format"):
            _parse_transaction_date("2024-06-15 14:30:SS")

    def test_parse_transaction_date_only_time(self) -> None:
        """Given only time part, raises ValueError."""
        with pytest.raises(ValueError, match="Unsupported transaction date format"):
            _parse_transaction_date("14:30:45")

    def test_parse_transaction_date_invalid_date_in_datetime(self) -> None:
        """Given datetime with invalid date part, raises ValueError."""
        with pytest.raises(ValueError, match="Invalid date"):
            _parse_transaction_date("2024-02-30 14:30:45")  # Feb 30 invalid

    def test_parse_transaction_date_zero_hour_valid(self) -> None:
        """Given datetime with zero hour, succeeds."""
        result = _parse_transaction_date("2024-06-15 00:00:00")
        assert result == "2024-06-15"

    def test_parse_transaction_date_max_hour_valid(self) -> None:
        """Given datetime with max valid hour (23), succeeds."""
        result = _parse_transaction_date("2024-06-15 23:59:59")
        assert result == "2024-06-15"

    def test_parse_transaction_date_negative_time_component(self) -> None:
        """Given datetime with negative time component, raises ValueError."""
        with pytest.raises(ValueError, match="Unsupported transaction date format"):
            _parse_transaction_date("2024-06-15 -1:30:45")

    def test_parse_transaction_date_three_spaces(self) -> None:
        """Given datetime with three space-separated parts, raises ValueError."""
        with pytest.raises(ValueError, match="Unsupported transaction date format"):
            _parse_transaction_date("2024-06-15 14:30:45 extra")


class TestIsTemporallyValid:
    """Tests for _is_temporally_valid function."""

    def test_is_temporally_valid_no_constraints(self) -> None:
        """Given no date constraints, returns True."""
        result = _is_temporally_valid(None, None, "2024-06-15")
        assert result is True

    def test_is_temporally_valid_after_service_start(self) -> None:
        """Given transaction after service start date, returns True."""
        result = _is_temporally_valid("2024-01-01", None, "2024-06-15")
        assert result is True

    def test_is_temporally_valid_before_service_start(self) -> None:
        """Given transaction before service start date, returns False."""
        result = _is_temporally_valid("2024-06-01", None, "2024-05-15")
        assert result is False

    def test_is_temporally_valid_before_valid_until(self) -> None:
        """Given transaction before expiration date, returns True."""
        result = _is_temporally_valid(None, "2024-12-31", "2024-06-15")
        assert result is True

    def test_is_temporally_valid_after_valid_until(self) -> None:
        """Given transaction after expiration date, returns False."""
        result = _is_temporally_valid(None, "2024-06-01", "2024-06-15")
        assert result is False

    def test_is_temporally_valid_in_range(self) -> None:
        """Given transaction within valid range, returns True."""
        result = _is_temporally_valid("2024-01-01", "2024-12-31", "2024-06-15")
        assert result is True

    def test_is_temporally_valid_outside_range(self) -> None:
        """Given transaction outside valid range, returns False."""
        result = _is_temporally_valid("2024-06-01", "2024-06-30", "2024-05-15")
        assert result is False

    def test_is_temporally_valid_on_start_bound(self) -> None:
        """Given transaction exactly on service start date, returns True."""
        result = _is_temporally_valid("2024-06-15", None, "2024-06-15")
        assert result is True

    def test_is_temporally_valid_on_end_bound(self) -> None:
        """Given transaction exactly on expiration date, returns True."""
        result = _is_temporally_valid(None, "2024-06-15", "2024-06-15")
        assert result is True


class TestNormalizeAndValidateTemporalFields:
    """Tests for _normalize_and_validate_temporal_fields function."""

    def test_normalize_and_validate_all_none(self) -> None:
        """Given all None values, returns all None."""
        from tax_reporting.application.crypto.validation import _normalize_and_validate_temporal_fields

        result = _normalize_and_validate_temporal_fields("Binance", None, None, None)
        assert result == (None, None, None)

    def test_normalize_and_validate_empty_strings(self) -> None:
        """Given empty strings, normalizes to None."""
        from tax_reporting.application.crypto.validation import _normalize_and_validate_temporal_fields

        result = _normalize_and_validate_temporal_fields(
            "Binance", "", "", ""
        )
        assert result == (None, None, None)

    def test_normalize_and_validate_whitespace_strings(self) -> None:
        """Given whitespace strings, normalizes to None."""
        from tax_reporting.application.crypto.validation import _normalize_and_validate_temporal_fields

        result = _normalize_and_validate_temporal_fields(
            "Binance", "  ", "  ", "  "
        )
        assert result == (None, None, None)

    def test_normalize_and_validate_valid_dates(self) -> None:
        """Given valid dates, returns normalized values."""
        from tax_reporting.application.crypto.validation import _normalize_and_validate_temporal_fields

        result = _normalize_and_validate_temporal_fields(
            "Binance", "2020-01-01", "2020-06-01", "2025-12-31"
        )
        assert result == ("2020-01-01", "2020-06-01", "2025-12-31")

    def test_normalize_and_validate_service_after_from_raises(self) -> None:
        """Given service_start after valid_from, raises ValueError."""
        from tax_reporting.application.crypto.validation import _normalize_and_validate_temporal_fields

        with pytest.raises(ValueError, match="service_start_date.*must be on or before valid_from"):
            _normalize_and_validate_temporal_fields(
                "Binance", "2021-01-01", "2020-06-01", None
            )

    def test_normalize_and_validate_service_after_until_raises(self) -> None:
        """Given service_start after valid_until, raises ValueError."""
        from tax_reporting.application.crypto.validation import _normalize_and_validate_temporal_fields

        with pytest.raises(ValueError, match="service_start_date.*must be on or before valid_until"):
            _normalize_and_validate_temporal_fields(
                "Binance", "2021-01-01", None, "2020-12-31"
            )

    def test_normalize_and_validate_until_before_from_raises(self) -> None:
        """Given valid_until before valid_from, raises ValueError."""
        from tax_reporting.application.crypto.validation import _normalize_and_validate_temporal_fields

        with pytest.raises(ValueError, match="valid_until.*must be on or after valid_from"):
            _normalize_and_validate_temporal_fields(
                "Binance", None, "2021-01-01", "2020-12-31"
            )

    def test_normalize_and_validate_invalid_date_format_raises(self) -> None:
        """Given invalid date format, raises ValueError."""
        from tax_reporting.application.crypto.validation import _normalize_and_validate_temporal_fields

        with pytest.raises(ValueError, match="expected YYYY-MM-DD"):
            _normalize_and_validate_temporal_fields(
                "Binance", "2020/01/01", None, None
            )


class TestValidateReviewReason:
    """Tests for _validate_review_reason function."""

    def test_validate_review_reason_not_required_no_reason(self) -> None:
        """Given review_required=False with no reason, succeeds."""
        from tax_reporting.application.crypto.validation import _validate_review_reason

        _validate_review_reason(False, None)  # Should not raise

    def test_validate_review_reason_required_with_reason(self) -> None:
        """Given review_required=True with reason, succeeds."""
        from tax_reporting.application.crypto.validation import _validate_review_reason

        _validate_review_reason(True, "Platform not mapped")  # Should not raise

    def test_validate_review_reason_required_without_reason_raises(self) -> None:
        """Given review_required=True without reason, raises ValueError."""
        from tax_reporting.application.crypto.validation import _validate_review_reason

        with pytest.raises(ValueError, match="review_reason must be set"):
            _validate_review_reason(True, None)
