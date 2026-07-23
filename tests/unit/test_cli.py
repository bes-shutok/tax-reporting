"""Tests for CLI argument parsing in main.py.

Tests follow TDD pattern: failing tests written first, then implementation.
"""

from __future__ import annotations

import contextlib
import logging
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest

from tax_reporting.domain.collections import IBExportData
from tax_reporting.domain.exceptions import ConfigurationError, MissingDecisionPointsError
from tax_reporting.main import _build_arg_parser, _main, cli


def test_build_arg_parser_returns_argument_parser():
    """Verify _build_arg_parser returns an ArgumentParser instance."""
    parser = _build_arg_parser()
    assert parser is not None
    assert parser.prog == "tax-reporting"


def test_no_arguments_all_values_none():
    """No arguments → all values None (defaults handled by main())."""
    parser = _build_arg_parser()
    args = parser.parse_args([])

    assert args.source_file is None
    assert args.output_dir is None
    assert args.example is False
    assert args.log_level is None


def test_example_flag_sets_example_source_and_output():
    """--example sets source to resources/source/example/ib_export.csv and output to resources/result/example/."""
    parser = _build_arg_parser()
    args = parser.parse_args(["--example"])

    assert args.example is True
    # When example=True, source_file and output_dir remain None here
    # main() will resolve them based on the example flag
    assert args.source_file is None
    assert args.output_dir is None


def test_source_file_accepts_explicit_path():
    """--source-file accepts explicit path."""
    parser = _build_arg_parser()
    args = parser.parse_args(["--source-file", "/custom/path/ib_export.csv"])

    assert args.source_file == "/custom/path/ib_export.csv"
    assert args.output_dir is None


def test_output_dir_accepts_explicit_path():
    """--output-dir accepts explicit path."""
    parser = _build_arg_parser()
    args = parser.parse_args(["--output-dir", "/custom/output"])

    assert args.output_dir == "/custom/output"
    assert args.source_file is None


def test_source_and_output_together():
    """--source-file and --output-dir can be specified together."""
    parser = _build_arg_parser()
    args = parser.parse_args(["--source-file", "/custom/source.csv", "--output-dir", "/custom/out"])

    assert args.source_file == "/custom/source.csv"
    assert args.output_dir == "/custom/out"


def test_log_level_accepts_valid_choices():
    """--log-level accepts only valid choices (DEBUG, INFO, WARNING, ERROR, CRITICAL)."""
    parser = _build_arg_parser()

    for valid_level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
        args = parser.parse_args(["--log-level", valid_level])
        assert args.log_level == valid_level


def test_log_level_invalid_choice_raises_error():
    """--log-level with invalid choice raises SystemExit."""
    parser = _build_arg_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["--log-level", "INVALID"])


def test_log_level_defaults_to_none():
    """--log-level defaults to None (main() will use 'INFO')."""
    parser = _build_arg_parser()
    args = parser.parse_args([])

    assert args.log_level is None


def test_example_with_log_level():
    """--example can be combined with --log-level."""
    parser = _build_arg_parser()
    args = parser.parse_args(["--example", "--log-level", "DEBUG"])

    assert args.example is True
    assert args.log_level == "DEBUG"


def test_example_conflicts_with_source_file():
    """--example with --source-file is mutually exclusive."""
    from tax_reporting.main import _validate_args

    parser = _build_arg_parser()
    args = parser.parse_args(["--example", "--source-file", "/custom/path.csv"])

    with pytest.raises(SystemExit):
        _validate_args(args, parser)


def test_example_conflicts_with_output_dir():
    """--example with --output-dir is mutually exclusive."""
    from tax_reporting.main import _validate_args

    parser = _build_arg_parser()
    args = parser.parse_args(["--example", "--output-dir", "/custom/out"])

    with pytest.raises(SystemExit):
        _validate_args(args, parser)


@patch("tax_reporting.main.main")
def test_cli_passes_example_args_to_main(mock_main):
    """cli() with --example flag passes correct absolute paths to main()."""
    import tax_reporting.main as main_module

    project_root = Path(main_module.__file__).parent.parent.parent
    with patch("sys.argv", ["tax-reporting", "--example"]):
        cli()
        mock_main.assert_called_once_with(
            source_file=project_root / "resources/source/example/ib_export.csv",
            output_dir=project_root / "resources/result/example",
            log_level=None,
        )


@patch("tax_reporting.main.main")
def test_cli_passes_custom_paths_to_main(mock_main):
    """cli() with custom paths passes them to main()."""
    with patch("sys.argv", ["tax-reporting", "--source-file", "/custom/source.csv", "--output-dir", "/custom/out"]):
        cli()
        mock_main.assert_called_once_with(
            source_file=Path("/custom/source.csv"),
            output_dir=Path("/custom/out"),
            log_level=None,
        )


@patch("tax_reporting.main.main")
def test_cli_passes_log_level_to_main(mock_main):
    """cli() with --log-level passes it to main()."""
    with patch("sys.argv", ["tax-reporting", "--log-level", "DEBUG"]):
        cli()
        mock_main.assert_called_once_with(
            source_file=None,
            output_dir=None,
            log_level="DEBUG",
        )


@pytest.mark.unit
class TestCliMain:
    """Tests for main() / _main() boundary behavior."""

    def _assert_console_handler_level(self, expected_level: int) -> None:
        """Find the console StreamHandler on the root logger and assert its level."""
        # ``logging.FileHandler`` is a subclass of ``logging.StreamHandler``, so a plain
        # ``isinstance(h, StreamHandler)`` filter would also match the FileHandler
        # that ``configure_application_logging`` attaches on the ``_main`` path
        # (always, since ``_main`` passes ``log_file``). Filter to the console handler
        # only by excluding FileHandler instances.
        console_handlers = [
            h
            for h in logging.getLogger().handlers
            if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
        ]
        assert console_handlers, "Expected at least one console StreamHandler on the root logger"
        assert console_handlers[0].level == expected_level, (
            f"Console StreamHandler level is {console_handlers[0].level}; "
            f"expected {expected_level} ({logging.getLevelName(expected_level)})"
        )

    def test_config_log_level_applied_to_console_handler(self, tmp_path, monkeypatch) -> None:
        """Config-derived ``resolved_level`` is re-applied to the console handler.

        Mutation-pins the re-configure-with-``resolved_level`` call at ``main.py:146``
        (r2 review F1). On the happy path (config loads successfully), ``_main`` resolves
        the level from ``app_config.log_level`` when no ``--log-level`` is passed, then
        calls ``configure_application_logging(level=resolved_level, ...)`` so a user
        setting ``LOG_LEVEL = ERROR`` in config.ini gets ERROR console output. Deleting
        that re-configure call leaves this test RED: the console handler would stay at
        ``DEFAULT_LOG_LEVEL`` (WARNING), not ERROR.

        Asserts the FINAL handler state (not the call sequence), so it is robust to
        whether the implementation uses a pre-config + re-configure or a single
        conditional configure call. Patches downstream IB/FIFO/generate calls so
        ``_main`` runs to completion.
        """
        from tax_reporting.domain.collections import IBExportData
        from tax_reporting.domain.jurisdiction import TaxJurisdictionConfig
        from tax_reporting.infrastructure.config import Config

        # Build a Config whose log_level is ERROR (distinct from DEFAULT_LOG_LEVEL so a
        # missing re-configure call cannot accidentally pass).
        app_config = Config(
            base="EUR",
            rates=[],
            tax_jurisdiction=TaxJurisdictionConfig(
                country="PT",
                fiscal_year=2025,
                exclude_loan_repayment_gains=True,
                zero_basis_review_threshold=Decimal("50"),
            ),
            log_level="ERROR",
        )

        source_file = tmp_path / "ib_export.csv"
        source_file.write_text("header\n", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        # Snapshot root handlers so the test can restore them afterwards (the re-configure
        # call installs a fresh StreamHandler/FileHandler pair on the root logger).
        root = logging.getLogger()
        original_level = root.level
        original_handlers = list(root.handlers)
        try:
            with (
                patch("tax_reporting.main.parse_ib_export_all", return_value=IBExportData({}, {})),
                patch("tax_reporting.main.calculate_fifo_gains"),
                patch("tax_reporting.main.export_rollover_file"),
                patch("tax_reporting.main.generate_tax_report", return_value=False),
                patch("tax_reporting.main.load_configuration_from_file", return_value=app_config),
            ):
                _main(source_file=source_file, output_dir=tmp_path, log_level=None)

            # log_level=None -> resolved_level = app_config.log_level = "ERROR".
            self._assert_console_handler_level(logging.ERROR)
        finally:
            for h in root.handlers:
                h.close()
            root.handlers.clear()
            root.handlers.extend(original_handlers)
            root.setLevel(original_level)

    def test_cli_log_level_overrides_config_on_console_handler(self, tmp_path, monkeypatch) -> None:
        """CLI ``--log-level`` wins over the config-derived level on the console handler.

        Mutation-pins the CLI-override-wins branch of ``resolved_level`` (r2 review F1
        variant 2): when ``log_level`` is passed explicitly, it must override
        ``app_config.log_level``. Deleting the ``log_level if log_level is not None else ...``
        branch (so resolved always falls to app_config) leaves this test RED: the handler
        would be at ERROR (from config), not DEBUG (from CLI).
        """
        from tax_reporting.domain.collections import IBExportData
        from tax_reporting.domain.jurisdiction import TaxJurisdictionConfig
        from tax_reporting.infrastructure.config import Config

        app_config = Config(
            base="EUR",
            rates=[],
            tax_jurisdiction=TaxJurisdictionConfig(
                country="PT",
                fiscal_year=2025,
                exclude_loan_repayment_gains=True,
                zero_basis_review_threshold=Decimal("50"),
            ),
            log_level="ERROR",
        )

        source_file = tmp_path / "ib_export.csv"
        source_file.write_text("header\n", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        root = logging.getLogger()
        original_level = root.level
        original_handlers = list(root.handlers)
        try:
            with (
                patch("tax_reporting.main.parse_ib_export_all", return_value=IBExportData({}, {})),
                patch("tax_reporting.main.calculate_fifo_gains"),
                patch("tax_reporting.main.export_rollover_file"),
                patch("tax_reporting.main.generate_tax_report", return_value=False),
                patch("tax_reporting.main.load_configuration_from_file", return_value=app_config),
            ):
                # Explicit CLI log_level=DEBUG must override config's ERROR.
                _main(source_file=source_file, output_dir=tmp_path, log_level="DEBUG")

            self._assert_console_handler_level(logging.DEBUG)
        finally:
            for h in root.handlers:
                h.close()
            root.handlers.clear()
            root.handlers.extend(original_handlers)
            root.setLevel(original_level)

    def test_invalid_log_level_surfaces_as_configuration_error(self, tmp_path, monkeypatch) -> None:
        """A config.ini with LOG_LEVEL = VERBOSE raises ConfigurationError via main().

        Proves the main.py except-(ValueError, KeyError, configparser.Error) wrapper converts
        the ValueError raised inside config.py (per Design Invariant #6 / r1 finding #1) into
        a ConfigurationError that propagates out of main().
        """
        from tax_reporting.domain.exceptions import ConfigurationError

        (tmp_path / "config.ini").write_text(
            "[COMMON]\nTARGET CURRENCY = EUR\nLOG_LEVEL = VERBOSE\n[EXCHANGE RATES]\nEUR/USD = 1.0\n",
            encoding="utf-8",
        )
        monkeypatch.chdir(tmp_path)
        with pytest.raises(ConfigurationError, match="VERBOSE"):
            _main(source_file=tmp_path / "ib_export.csv", output_dir=tmp_path)


class TestMainWithMissingConfig:
    """Tests for main() behavior when config.ini is missing."""

    @patch("tax_reporting.main.main")
    @patch("sys.argv", ["tax-reporting", "--example"])
    def test_cli_calls_main_when_config_ini_missing(self, mock_main, tmp_path, monkeypatch) -> None:
        """cli() calls main() even when config.ini is not found."""
        import tax_reporting.main as main_module

        # Change to temp directory where config.ini doesn't exist
        monkeypatch.chdir(tmp_path)

        # Call cli() - should call main() even without config.ini
        main_module.cli()

        # Verify main() was called (processing continued despite missing config)
        mock_main.assert_called_once()

    @patch("configparser.ConfigParser.read")
    def test_config_loading_logs_error_when_file_missing(self, mock_read, tmp_path, monkeypatch, caplog) -> None:
        """load_configuration_from_file logs error when config.ini is not found."""
        from tax_reporting.infrastructure.config import load_configuration_from_file

        # Mock ConfigParser.read to simulate FileNotFoundError
        mock_read.return_value = []

        # Call load_configuration_from_file
        with caplog.at_level(logging.ERROR), contextlib.suppress(Exception):
            load_configuration_from_file()

        # Verify error was logged about missing config
        assert any(
            "Configuration file not found" in record.message or "Config file not found" in record.message
            for record in caplog.records
        )

    def test_main_file_not_found_configures_logging_and_warns_to_file(self, tmp_path, monkeypatch) -> None:
        """On the FileNotFoundError path, _main() configures logging at DEFAULT_LOG_LEVEL
        and the 'Config file not found' WARNING reaches the file audit trail.

        Design Invariant 9(c) / r1 review F2: the not-found WARNING must not be lost to an
        unconfigured root logger. Asserts the FINAL logging state (WARNING reaches the file)
        rather than the exact call sequence, so it is robust to the pre-config-vs-branch-call
        implementation approach. Patches the downstream IB/FIFO block so _main() runs to
        completion on the FileNotFoundError path.
        """
        from tax_reporting.domain.collections import IBExportData
        from tax_reporting.infrastructure.config import DEFAULT_LOG_LEVEL

        source_file = tmp_path / "ib_export.csv"
        source_file.write_text("header\n", encoding="utf-8")
        # _main() hardcodes log_file = Path("logs", "tax-reporting.log") relative to cwd,
        # so chdir into tmp_path to land the audit file there for inspection.
        monkeypatch.chdir(tmp_path)
        log_file = tmp_path / "logs" / "tax-reporting.log"

        with (
            patch("tax_reporting.main.parse_ib_export_all", return_value=IBExportData({}, {})),
            patch("tax_reporting.main.calculate_fifo_gains"),
            patch("tax_reporting.main.export_rollover_file"),
            patch("tax_reporting.main.generate_tax_report", return_value=False),
            patch("tax_reporting.main.load_configuration_from_file", side_effect=FileNotFoundError("no config")),
        ):
            _main(source_file=source_file, output_dir=tmp_path)

        # The WARNING is emitted by _main() on the FileNotFoundError path and must reach
        # the file audit trail. A regression that reorders logging configuration after the
        # warning, or drops the pre-config safety-net call, leaves this assertion failing.
        log_text = log_file.read_text(encoding="utf-8")
        assert "Config file not found" in log_text
        # Sanity: DEFAULT_LOG_LEVEL is the level used on this failure path (asserted to be a
        # valid level name, not a bare literal in the wiring).
        assert DEFAULT_LOG_LEVEL in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


def test_main_raises_configuration_error_for_missing_decision_points(tmp_path):
    """_main() propagates configuration errors for missing decision points TOML."""
    source_file = tmp_path / "ib_export.csv"
    source_file.write_text("header\n", encoding="utf-8")

    with (
        patch("tax_reporting.main.parse_ib_export_all", return_value=IBExportData({}, {})),
        patch("tax_reporting.main.calculate_fifo_gains"),
        patch("tax_reporting.main.export_rollover_file"),
        patch(
            "tax_reporting.main.load_configuration_from_file",
            side_effect=MissingDecisionPointsError("missing toml"),
        ),
        pytest.raises(ConfigurationError, match="missing toml"),
    ):
        _main(source_file=source_file, output_dir=tmp_path)
