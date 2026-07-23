"""Tests for application logging configuration.

Houses the root-logger gating regression test (r5 finding #1) that guards the
``logging_config.py`` fix where the root logger must always be ``DEBUG`` so DEBUG
records reach the file handler (hardcoded DEBUG) regardless of the console level.
Mirrors the existing ``test_config.py`` <-> ``config.py`` test convention.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from tax_reporting.infrastructure.logging_config import configure_application_logging


@pytest.mark.unit
class TestLoggingConfig:
    """Tests for configure_application_logging root/handler level gating."""

    def test_file_handler_receives_debug_when_console_at_warning(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A ``logger.debug(...)`` call reaches the file but NOT the console at console=WARNING.

        Regression test for r5 finding #1 (root-logger gating bug, Blocker): the previous
        implementation set ``root_logger.setLevel(getattr(logging, level.upper()))`` which
        gates DEBUG records at the ROOT before they reach the file handler, making the file
        handler's ``setLevel(logging.DEBUG)`` inert whenever ``level != "DEBUG"``. With the
        fix (``root_logger.setLevel(logging.DEBUG)`` unconditional), DEBUG records reach the
        file regardless of the console threshold, while the per-handler ``setLevel`` on the
        console handler still filters DEBUG out at WARNING.
        """
        log_file = tmp_path / "out.log"

        # Reset root logger handlers/level to a known state before the test.
        root = logging.getLogger()
        original_level = root.level
        original_handlers = list(root.handlers)
        try:
            configure_application_logging(level="WARNING", log_file=log_file)

            logging.getLogger("regression.repro").debug("canary-debug-line")
            # Flush all handlers so the file content is materialized on disk and stdout
            # is flushed for capsys.
            for handler in root.handlers:
                handler.flush()

            file_contents = log_file.read_text(encoding="utf-8")
            assert "canary-debug-line" in file_contents, (
                "DEBUG did not reach file; the root-logger gating bug (r5 #1) is present: "
                "root_logger.setLevel(level) must be root_logger.setLevel(logging.DEBUG)."
            )

            # The console handler is a StreamHandler(sys.stdout) with level=WARNING; a DEBUG
            # record must NOT be written to stdout. capsys captures stdout writes.
            console_out = capsys.readouterr().out
            assert "canary-debug-line" not in console_out, (
                "DEBUG record leaked to console at console=WARNING; console handler level is wrong."
            )
        finally:
            # Restore root logger state so the test does not leak handlers into the rest of the suite.
            root.setLevel(original_level)
            root.handlers.clear()
            root.handlers.extend(original_handlers)
