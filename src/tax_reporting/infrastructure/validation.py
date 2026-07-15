"""Input validation and file path sanitization utilities.

Provides secure validation functions for file operations and user input.
"""

from __future__ import annotations

from pathlib import Path

from ..infrastructure.logging_config import create_module_logger

logger = create_module_logger(__name__)


class ValidationError(Exception):
    """Raised when input validation fails."""


def sanitize_directory_path(directory_path: str | Path) -> Path:
    """Sanitize and validate directory paths to prevent directory traversal attacks.

    Args:
        directory_path: The directory path to validate

    Returns:
        Sanitized absolute Path object
    """
    try:
        # Convert to Path object if it's a string
        path_obj = Path(directory_path)

        # Convert to absolute path
        abs_path = path_obj.resolve()

        return abs_path

    except (OSError, ValueError) as e:
        raise ValidationError(f"Invalid directory path {directory_path}: {str(e)}") from e


def validate_output_directory(output_path: str | Path) -> Path:
    """Validate and create output directory if needed.

    Args:
        output_path: Path to output directory

    Returns:
        Sanitized Path object
    """
    # Sanitize directory path (not file path)
    safe_path = sanitize_directory_path(output_path)

    try:
        # Create directory if it doesn't exist
        safe_path.mkdir(parents=True, exist_ok=True)

        # Check if we can write to the directory
        test_file = safe_path / ".write_test"
        test_file.touch()
        test_file.unlink()

        logger.info("Validated output directory: %s", safe_path)
        return safe_path

    except PermissionError as e:
        raise ValidationError(f"Permission denied creating/writing directory: {safe_path}") from e
    except OSError as e:
        raise ValidationError(f"Error creating directory {safe_path}: {str(e)}") from e
