"""Logging configuration for the tax reporting application.

Provides centralized logging setup with appropriate log levels,
formatters, and handlers for different environments.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path


def configure_application_logging(level: str, log_file: Path | None = None, enable_console: bool = True) -> None:
    """Configure application logging with standardized formatting and output options.

    Args:
        level: Logging level for the CONSOLE handler (DEBUG, INFO, WARNING, ERROR, CRITICAL).
            Required; every caller passes an explicit level derived from config or CLI.
            The file handler always captures DEBUG regardless of this value.
        log_file: Optional path to log file for persistent logging
        enable_console: Whether to enable console output for real-time monitoring
    """
    # Root logger is ALWAYS DEBUG so DEBUG records reach the file handler (hardcoded DEBUG).
    # The per-handler setLevel calls below enforce the console threshold; the root level
    # must NOT gate DEBUG out before records reach the file handler (r5 finding #1).
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # Close existing handlers (release file descriptors on the double-configure path)
    # before clearing them (r2 review F5). ``clear()`` alone drops the references and
    # leaves the underlying FileHandler's FD held until GC; closing first releases it
    # promptly. Records are NOT lost: the second configure re-opens the same path in
    # append mode, so audit-trail continuity holds.
    for handler in root_logger.handlers:
        handler.close()
    root_logger.handlers.clear()

    # Create formatter
    formatter = logging.Formatter(
        fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Add console handler if enabled
    if enable_console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(getattr(logging, level.upper()))
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

    # Add file handler if specified
    if log_file:
        # Create log directory if it doesn't exist
        log_file.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.DEBUG)  # File gets all levels
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)


def create_module_logger(name: str) -> logging.Logger:
    """Create standardized logger for specific module with consistent configuration.

    Args:
        name: Logger name (typically __name__ for module-level logging)

    Returns:
        Configured logger instance ready for use
    """
    return logging.getLogger(name)
