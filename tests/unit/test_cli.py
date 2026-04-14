"""Tests for CLI argument parsing in main.py.

Tests follow TDD pattern: failing tests written first, then implementation.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from shares_reporting.main import _build_arg_parser, cli


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
    from shares_reporting.main import _validate_args

    parser = _build_arg_parser()
    args = parser.parse_args(["--example", "--source-file", "/custom/path.csv"])

    with pytest.raises(SystemExit):
        _validate_args(args, parser)


def test_example_conflicts_with_output_dir():
    """--example with --output-dir is mutually exclusive."""
    from shares_reporting.main import _validate_args

    parser = _build_arg_parser()
    args = parser.parse_args(["--example", "--output-dir", "/custom/out"])

    with pytest.raises(SystemExit):
        _validate_args(args, parser)


@patch("shares_reporting.main.main")
def test_cli_passes_example_args_to_main(mock_main):
    """cli() with --example flag passes correct absolute paths to main()."""
    # Mock sys.argv to simulate --example flag
    with patch("sys.argv", ["tax-reporting", "--example"]):
        cli()
        # Verify main() was called with example paths as absolute Path objects
        # Paths are resolved relative to project root for consistent behavior from any working directory
        mock_main.assert_called_once_with(
            source_file=Path("/workspace/resources/source/example/ib_export.csv"),
            output_dir=Path("/workspace/resources/result/example"),
            log_level="INFO",
        )


@patch("shares_reporting.main.main")
def test_cli_passes_custom_paths_to_main(mock_main):
    """cli() with custom paths passes them to main()."""
    with patch("sys.argv", ["tax-reporting", "--source-file", "/custom/source.csv", "--output-dir", "/custom/out"]):
        cli()
        mock_main.assert_called_once_with(
            source_file=Path("/custom/source.csv"),
            output_dir=Path("/custom/out"),
            log_level="INFO",
        )


@patch("shares_reporting.main.main")
def test_cli_passes_log_level_to_main(mock_main):
    """cli() with --log-level passes it to main()."""
    with patch("sys.argv", ["tax-reporting", "--log-level", "DEBUG"]):
        cli()
        mock_main.assert_called_once_with(
            source_file=None,
            output_dir=None,
            log_level="DEBUG",
        )
