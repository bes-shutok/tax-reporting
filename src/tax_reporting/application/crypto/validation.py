"""Validation helpers for crypto reporting."""

from __future__ import annotations

from datetime import date, datetime

# Constants for date validation
_MIN_VALID_YEAR: int = 2009  # Bitcoin genesis, crypto didn't exist before
_MAX_VALID_YEAR: int = 2100
_ISO_DATE_LENGTH: int = 10
_ISO_DATE_PARTS: int = 3  # YYYY-MM-DD has 3 parts
_YEAR_DIGITS: int = 4
_MONTH_DAY_DIGITS: int = 2

# Constants for time validation
_DATETIME_SPACE_PARTS: int = 2  # Date and time separated by space
_TIME_COMPONENTS: int = 3  # HH:MM:SS has 3 parts
_TIME_PART_DIGITS: int = 2
_MAX_HOUR: int = 23
_MAX_MINUTE_SECOND: int = 59


def _validate_iso_date(date_str: str) -> str:
    """Validate an ISO date string (YYYY-MM-DD) and return it.

    Args:
        date_str: Date string in ISO format (YYYY-MM-DD).

    Returns:
        The validated date string.

    Raises:
        ValueError: If the date is invalid or out of reasonable range.
    """
    parts = date_str.split("-")
    if len(parts) != _ISO_DATE_PARTS:
        raise ValueError(f"Invalid date format '{date_str}': expected YYYY-MM-DD")
    year_str, month_str, day_str = parts

    # Verify zero-padding: YYYY-MM-DD requires exactly 4, 2, 2 digits
    if len(year_str) != _YEAR_DIGITS or len(month_str) != _MONTH_DAY_DIGITS or len(day_str) != _MONTH_DAY_DIGITS:
        raise ValueError(f"Invalid date format '{date_str}': zero-padding required (YYYY-MM-DD)")

    # Verify all parts are numeric
    if not (year_str.isdigit() and month_str.isdigit() and day_str.isdigit()):
        raise ValueError(f"Invalid date format '{date_str}': non-numeric characters")

    year, month, day = int(year_str), int(month_str), int(day_str)
    if year < _MIN_VALID_YEAR or year > _MAX_VALID_YEAR:
        raise ValueError(
            f"Invalid date '{date_str}': year {year} out of reasonable range "
            f"[{_MIN_VALID_YEAR}, {_MAX_VALID_YEAR}]"
        )
    try:
        date(year, month, day)  # Validates calendar date (rejects Feb 31, etc.)
        return date_str
    except ValueError as e:
        raise ValueError(f"Invalid date '{date_str}': {e}") from e


def _parse_transaction_date(transaction_date: str | None) -> str | None:
    """Parse transaction date to ISO date format (YYYY-MM-DD) for temporal validity checks.

    Args:
        transaction_date: Transaction date string in one of the following formats:
            - "YYYY-MM-DD HH:MM:SS" (Koinly format)
            - "YYYY-MM-DD" (ISO date)

    Returns:
        ISO date string (YYYY-MM-DD) or None if input is empty/None.

    Raises:
        ValueError: If the date format is invalid.
    """
    if not transaction_date:
        return None

    # Strip leading/trailing whitespace
    transaction_date = transaction_date.strip()

    # Handle Koinly format: "YYYY-MM-DD HH:MM:SS"
    if " " in transaction_date:
        parts = transaction_date.split(" ")
        if len(parts) != _DATETIME_SPACE_PARTS:
            raise ValueError(f"Unsupported transaction date format: {transaction_date}")
        date_part, time_part = parts
        # Validate time part matches HH:MM:SS pattern with valid ranges
        time_components = time_part.split(":")
        if len(time_components) != _TIME_COMPONENTS:
            raise ValueError(f"Unsupported transaction date format: {transaction_date}")
        # Verify all time parts are digits AND zero-padded (exactly 2 digits each)
        if not all(cp.isdigit() and len(cp) == _TIME_PART_DIGITS for cp in time_components):
            raise ValueError(f"Unsupported transaction date format: {transaction_date}")
        # Validate time ranges: hour (0-23), minute (0-59), second (0-59)
        hour, minute, second = map(int, time_components)
        if not (0 <= hour <= _MAX_HOUR and 0 <= minute <= _MAX_MINUTE_SECOND and 0 <= second <= _MAX_MINUTE_SECOND):
            raise ValueError(f"Unsupported transaction date format: {transaction_date}")
        return _validate_iso_date(date_part)

    # Already in YYYY-MM-DD format
    if len(transaction_date) == _ISO_DATE_LENGTH and transaction_date[4] == "-" and transaction_date[7] == "-":
        return _validate_iso_date(transaction_date)

    raise ValueError(f"Unsupported transaction date format: {transaction_date}")


def _is_temporally_valid(service_start_date: str | None, valid_until: str | None, transaction_date: str) -> bool:
    """Check if a mapping is valid for a given transaction date.

    Args:
        service_start_date: ISO date when the platform service started (YYYY-MM-DD).
            Used for transaction matching, not verification date.
        valid_until: ISO date when mapping expires (YYYY-MM-DD), or None if still valid.
        transaction_date: ISO transaction date to check (YYYY-MM-DD).

    Returns:
        True if the mapping was valid on the transaction date.

    Note:
        This function uses service_start_date for transaction date matching to avoid
        false positives on historical data. The valid_from field is preserved for
        audit trail but NOT used for temporal validation (it represents verification
        date, not service availability).
    """
    # Parse transaction date once for comparison
    # Date is already validated by _parse_transaction_date, so fromisoformat is safe
    tx_date = datetime.fromisoformat(transaction_date).date()

    # If service_start_date is specified (and not empty), check if transaction is on or after it
    if service_start_date:
        from_date = datetime.fromisoformat(service_start_date).date()
        if tx_date < from_date:
            return False

    # If valid_until is specified (and not empty), check if transaction is on or before it
    if valid_until:
        until_date = datetime.fromisoformat(valid_until).date()
        if tx_date > until_date:
            return False

    # No constraints violated, or no constraints at all
    return True


def _normalize_and_validate_temporal_fields(
    platform: str,
    service_start_date: str | None,
    valid_from: str | None,
    valid_until: str | None,
) -> tuple[str | None, str | None, str | None]:
    """Normalize and validate temporal validity fields for OperatorOrigin.

    Args:
        platform: Platform name for error messages.
        service_start_date: Service start date (YYYY-MM-DD) or empty string.
        valid_from: Verification start date (YYYY-MM-DD) or empty string.
        valid_until: Verification end date (YYYY-MM-DD) or empty string.

    Returns:
        Tuple of (normalized_service_start, normalized_from, normalized_until).
        Empty strings are converted to None.

    Raises:
        ValueError: If date format is invalid, date ranges are inconsistent,
            or other validation fails.
    """
    # Normalize empty strings to None for temporal fields
    normalized_service_start = (
        service_start_date.strip()
        if isinstance(service_start_date, str) and service_start_date.strip()
        else None
    )
    normalized_from = (
        valid_from.strip() if isinstance(valid_from, str) and valid_from.strip() else None
    )
    normalized_until = (
        valid_until.strip() if isinstance(valid_until, str) and valid_until.strip() else None
    )

    # Validate ISO date format for service_start_date if provided
    if normalized_service_start is not None:
        _validate_iso_date(normalized_service_start)

    # Validate ISO date format for valid_from if provided
    if normalized_from is not None:
        _validate_iso_date(normalized_from)

    # Validate ISO date format for valid_until if provided
    if normalized_until is not None:
        _validate_iso_date(normalized_until)

    # Validate that service_start_date <= valid_from if both are provided
    if normalized_service_start is not None and normalized_from is not None:
        service_date = datetime.fromisoformat(normalized_service_start).date()
        from_date = datetime.fromisoformat(normalized_from).date()
        if service_date > from_date:
            raise ValueError(
                f"Invalid date range for {platform}: service_start_date ({normalized_service_start}) "
                f"must be on or before valid_from ({normalized_from})"
            )

    # Validate that service_start_date <= valid_until if both are provided
    if normalized_service_start is not None and normalized_until is not None:
        service_date = datetime.fromisoformat(normalized_service_start).date()
        until_date = datetime.fromisoformat(normalized_until).date()
        if service_date > until_date:
            raise ValueError(
                f"Invalid date range for {platform}: service_start_date ({normalized_service_start}) "
                f"must be on or before valid_until ({normalized_until})"
            )

    # Validate that valid_until >= valid_from if both are provided
    if normalized_from is not None and normalized_until is not None:
        from_date = datetime.fromisoformat(normalized_from).date()
        until_date = datetime.fromisoformat(normalized_until).date()
        if until_date < from_date:
            raise ValueError(
                f"Invalid date range for {platform}: valid_until ({normalized_until}) "
                f"must be on or after valid_from ({normalized_from})"
            )

    return normalized_service_start, normalized_from, normalized_until


def _validate_review_reason(review_required: bool, review_reason: str | None) -> None:
    """Validate that review_reason is set when review_required is True.

    Args:
        review_required: Whether review is required.
        review_reason: The reason for review.

    Raises:
        ValueError: If review_required is True but review_reason is not set.
    """
    if review_required and not review_reason:
        raise ValueError("review_reason must be set when review_required=True")
