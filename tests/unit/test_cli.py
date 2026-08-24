"""Tests for CLI argument parsing in main.py.

Tests follow TDD pattern: failing tests written first, then implementation.
"""

from __future__ import annotations

import contextlib
import logging
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import ANY, patch

import pytest

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


def test_validate_flag_parsed(tmp_path, monkeypatch):
    """--validate-on-chain-th YEAR parses (int) and dispatches to the runner.

    Mirrors the existing ``@patch("tax_reporting.main.main")`` dispatch tests:
    ``run_validation`` is patched at ``tax_reporting.main.run_validation``
    (the consumer-module binding), the cwd is a tmp dir (the tolerant
    missing-config branch keeps the dispatch hermetic - no repo files read,
    and the validation log file lands in the tmp dir), and ``cli()`` must exit
    with the runner's status via ``sys.exit``.
    """
    parser = _build_arg_parser()
    args = parser.parse_args(["--validate-on-chain-th", "2025"])

    assert args.validate_on_chain_th == 2025
    assert args.date_from is None
    assert args.date_to is None

    monkeypatch.chdir(tmp_path)
    with (
        patch("tax_reporting.main.run_validation", return_value=0) as mock_run_validation,
        patch("sys.argv", ["tax-reporting", "--validate-on-chain-th", "2025"]),
        pytest.raises(SystemExit) as exit_info,
    ):
        cli()

    assert exit_info.value.code == 0
    mock_run_validation.assert_called_once_with(
        year=2025,
        output_dir=Path("resources/result"),
        koinly_dir=None,
        wallets=None,
        rpc_url=None,
        date_from=None,
        date_to=None,
        logger=ANY,
    )


def test_validate_flag_conflicts_rejected():
    """--validate-on-chain-th cannot be combined with --example, --source-file,
    or --output-dir (review r1 F21: the validation artifacts carry real tx
    hashes whose PII rule is enforced by location under gitignored
    ``resources/result/<year>/`` only - a shared --output-dir would move them
    outside that surface, so the contract is enforced, not just documented)."""
    from tax_reporting.main import _validate_args

    parser = _build_arg_parser()
    for argv in (
        ["--validate-on-chain-th", "2025", "--example"],
        ["--validate-on-chain-th", "2025", "--source-file", "/custom/path.csv"],
        ["--validate-on-chain-th", "2025", "--output-dir", "/elsewhere"],
    ):
        args = parser.parse_args(argv)
        with pytest.raises(SystemExit):
            _validate_args(args, parser)


# --------------------------------------------------------------------------- #
# ON_CHAIN_TH_WALLETS precedence arm (review r1 F3): the composition root's
# only enforcement of Design Invariant 9's precedence half - it activates
# exactly when the user flips the production flag after validation passes.
# --------------------------------------------------------------------------- #


def _precedence_wallet(chain: str, label: str):
    """A synthetic ``OnChainWalletConfig`` for the precedence-arm tests."""
    from tax_reporting.domain.on_chain_config import OnChainWalletConfig

    return OnChainWalletConfig(
        chain=chain,
        chainid=80094 if chain == "Berachain" else 1,
        label=label,
        address=f"0x{abs(hash(label)) % 16**40:040x}",
        native_ticker="BERA" if chain == "Berachain" else "ETH",
        start_date=date(2025, 1, 1),
        end_date=date(2025, 12, 31),
    )


class TestValidateWalletPrecedence:
    """``ON_CHAIN_TH_WALLETS`` precedence (main.py ``_run_validation_from_cli``)."""

    def test_configured_labels_filter_berachain_wallets(self, tmp_path, monkeypatch):
        """A configured ``on_chain_th_wallets`` selects the wallets under
        validation: chains.json is filtered to Berachain AND to the configured
        labels, matched through ``normalize_wallet_label`` (case/whitespace-insensitive).
        A differently-cased configured label still matches; a non-Berachain
        wallet and a non-configured Berachain wallet are both excluded."""
        from types import SimpleNamespace

        bera_configured = _precedence_wallet("Berachain", "Ledger Berachain (BERA)")
        bera_other = _precedence_wallet("Berachain", "Rabby Other")
        eth_wallet = _precedence_wallet("Ethereum", "Metamask ETH")
        monkeypatch.chdir(tmp_path)
        with (
            patch(
                "tax_reporting.main.load_configuration_from_file",
                return_value=SimpleNamespace(
                    tax_jurisdiction=SimpleNamespace(
                        on_chain_rpc_url=None,
                        on_chain_th_wallets=("  LEDGER BERACHAIN (BERA)  ",),
                    )
                ),
            ) as mock_config,
            patch(
                "tax_reporting.main.load_on_chain_wallets",
                return_value=[eth_wallet, bera_other, bera_configured],
            ) as mock_load_wallets,
            patch("tax_reporting.main.run_validation", return_value=0) as mock_run_validation,
            patch("sys.argv", ["tax-reporting", "--validate-on-chain-th", "2025"]),
            pytest.raises(SystemExit) as exit_info,
        ):
            cli()

        assert exit_info.value.code == 0
        mock_config.assert_called_once()
        mock_load_wallets.assert_called_once_with(2025)
        assert mock_run_validation.call_args.kwargs["wallets"] == [bera_configured], (
            "only the configured Berachain label may be under validation"
        )

    def test_configured_label_matching_nothing_passes_empty_list(self, tmp_path, monkeypatch):
        """A configured label matching no Berachain wallet resolves to an
        EMPTY list (documented behavior) - which reaches ``run_validation``
        verbatim so the runner fails loud on it, never silently widening the
        scope back to all Berachain wallets."""
        from types import SimpleNamespace

        monkeypatch.chdir(tmp_path)
        with (
            patch(
                "tax_reporting.main.load_configuration_from_file",
                return_value=SimpleNamespace(
                    tax_jurisdiction=SimpleNamespace(on_chain_rpc_url=None, on_chain_th_wallets=("No Such Wallet",))
                ),
            ),
            patch(
                "tax_reporting.main.load_on_chain_wallets",
                return_value=[_precedence_wallet("Berachain", "Ledger Berachain (BERA)")],
            ),
            patch("tax_reporting.main.run_validation", return_value=1) as mock_run_validation,
            patch("sys.argv", ["tax-reporting", "--validate-on-chain-th", "2025"]),
            pytest.raises(SystemExit) as exit_info,
        ):
            cli()

        assert exit_info.value.code == 1
        assert mock_run_validation.call_args.kwargs["wallets"] == []

    def test_invalid_config_raises_configuration_error(self, tmp_path, monkeypatch):
        """A present-but-invalid config (``ValueError`` from the loader) fails
        loud as ``ConfigurationError`` before any validation runs."""
        monkeypatch.chdir(tmp_path)
        with (
            patch("tax_reporting.main.load_configuration_from_file", side_effect=ValueError("bad setting")),
            patch("tax_reporting.main.run_validation", return_value=0) as mock_run_validation,
            patch("sys.argv", ["tax-reporting", "--validate-on-chain-th", "2025"]),
            pytest.raises(ConfigurationError, match="invalid settings"),
        ):
            cli()

        mock_run_validation.assert_not_called()

    def test_missing_decision_points_propagates(self, tmp_path, monkeypatch):
        """``MissingDecisionPointsError`` re-raises unchanged (the dedicated
        fail-fast, never wrapped in ``ConfigurationError``)."""
        monkeypatch.chdir(tmp_path)
        with (
            patch(
                "tax_reporting.main.load_configuration_from_file",
                side_effect=MissingDecisionPointsError("missing decision points"),
            ),
            patch("tax_reporting.main.run_validation", return_value=0) as mock_run_validation,
            patch("sys.argv", ["tax-reporting", "--validate-on-chain-th", "2025"]),
            pytest.raises(MissingDecisionPointsError),
        ):
            cli()

        mock_run_validation.assert_not_called()


def test_window_flags_validation():
    """--from/--to require --validate-on-chain-th, must be ordered, and bind dates."""
    from tax_reporting.main import _validate_args

    parser = _build_arg_parser()

    # Window flags without the validate path are rejected.
    for argv in (["--from", "2025-01-01"], ["--to", "2025-06-30"]):
        args = parser.parse_args(argv)
        with pytest.raises(SystemExit):
            _validate_args(args, parser)

    # An inverted window (--from after --to) is rejected.
    args = parser.parse_args(["--validate-on-chain-th", "2025", "--from", "2025-07-01", "--to", "2025-01-01"])
    with pytest.raises(SystemExit):
        _validate_args(args, parser)

    # A valid window parses with the two date values bound.
    args = parser.parse_args(["--validate-on-chain-th", "2025", "--from", "2025-01-01", "--to", "2025-06-30"])
    _validate_args(args, parser)
    assert args.date_from == date(2025, 1, 1)
    assert args.date_to == date(2025, 6, 30)


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
        conditional configure call. Patches the single ``run_report`` seam on
        ``main`` (this file's driven surface) so ``_main`` runs to completion.
        """
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
                patch("tax_reporting.main.run_report"),
                patch("tax_reporting.main.load_configuration_from_file", return_value=app_config),
            ):
                _main(source_file=source_file, output_dir=tmp_path, log_level=None)

            # log_level=None -> resolved_level = app_config.log_level = "ERROR".
            self._assert_console_handler_level(logging.ERROR)
        finally:
            # Close ONLY the handlers this run added, then re-attach the snapshotted
            # originals (guarded, so a pre-configure failure cannot duplicate them).
            # Production ``configure_application_logging`` CLOSES the originals while
            # reconfiguring; they are re-attached regardless so root never ends the
            # test with zero handlers (matches TestMainCompositionRoot._drive).
            for h in list(root.handlers):
                if h not in original_handlers:
                    h.close()
                    root.handlers.remove(h)
            for h in original_handlers:
                if h not in root.handlers:
                    root.handlers.append(h)
            root.setLevel(original_level)

    def test_cli_log_level_overrides_config_on_console_handler(self, tmp_path, monkeypatch) -> None:
        """CLI ``--log-level`` wins over the config-derived level on the console handler.

        Mutation-pins the CLI-override-wins branch of ``resolved_level`` (r2 review F1
        variant 2): when ``log_level`` is passed explicitly, it must override
        ``app_config.log_level``. Deleting the ``log_level if log_level is not None else ...``
        branch (so resolved always falls to app_config) leaves this test RED: the handler
        would be at ERROR (from config), not DEBUG (from CLI).
        """
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
                patch("tax_reporting.main.run_report"),
                patch("tax_reporting.main.load_configuration_from_file", return_value=app_config),
            ):
                # Explicit CLI log_level=DEBUG must override config's ERROR.
                _main(source_file=source_file, output_dir=tmp_path, log_level="DEBUG")

            self._assert_console_handler_level(logging.DEBUG)
        finally:
            # Close ONLY the handlers this run added, then re-attach the snapshotted
            # originals (guarded, so a pre-configure failure cannot duplicate them).
            # Production ``configure_application_logging`` CLOSES the originals while
            # reconfiguring; they are re-attached regardless so root never ends the
            # test with zero handlers (matches TestMainCompositionRoot._drive).
            for h in list(root.handlers):
                if h not in original_handlers:
                    h.close()
                    root.handlers.remove(h)
            for h in original_handlers:
                if h not in root.handlers:
                    root.handlers.append(h)
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
        implementation approach. Patches the single ``run_report`` seam on ``main`` so
        _main() runs to completion on the FileNotFoundError path.
        """
        from tax_reporting.infrastructure.config import DEFAULT_LOG_LEVEL

        source_file = tmp_path / "ib_export.csv"
        source_file.write_text("header\n", encoding="utf-8")
        # _main() hardcodes log_file = Path("logs", "tax-reporting.log") relative to cwd,
        # so chdir into tmp_path to land the audit file there for inspection.
        monkeypatch.chdir(tmp_path)
        log_file = tmp_path / "logs" / "tax-reporting.log"

        with (
            patch("tax_reporting.main.run_report"),
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


class TestCli:
    """cli() validation-path crash wrapper and exit-code contract."""

    def test_validation_crash_exits_2(self, tmp_path, monkeypatch, capsys):
        """An unexpected crash inside the validation path exits 2, prints a
        friendly one-line message, and routes the traceback through
        ``logger.exception`` into the file audit trail - never a bare
        unhandled traceback propagating out of ``cli()``."""
        monkeypatch.chdir(tmp_path)
        with (
            patch("tax_reporting.main.run_validation", side_effect=RuntimeError("boom")),
            patch("sys.argv", ["tax-reporting", "--validate-on-chain-th", "2025"]),
            pytest.raises(SystemExit) as exit_info,
        ):
            cli()

        assert exit_info.value.code == 2
        out = capsys.readouterr().out
        assert "crashed unexpectedly" in out
        # logger.exception record: the full traceback lands in the file audit trail
        # (caplog's handler is replaced by configure_application_logging, so the
        # log file is the durable logging surface to assert on).
        log_text = (tmp_path / "logs" / "tax-reporting.log").read_text(encoding="utf-8")
        assert "Unexpected error during on-chain TH validation" in log_text
        assert "RuntimeError: boom" in log_text

    @pytest.mark.parametrize("code", [0, 1, 3])
    def test_validation_exit_codes_passthrough(self, code, tmp_path, monkeypatch):
        """run_validation return values 0/1/3 reach ``sys.exit`` unchanged
        (backward compat: exit 1 stays misconfiguration-only)."""
        monkeypatch.chdir(tmp_path)
        with (
            patch("tax_reporting.main.run_validation", return_value=code),
            patch("sys.argv", ["tax-reporting", "--validate-on-chain-th", "2025"]),
            pytest.raises(SystemExit) as exit_info,
        ):
            cli()

        assert exit_info.value.code == code

    @pytest.mark.parametrize(
        ("exc_type", "message"),
        [
            (ConfigurationError, "invalid settings"),
            (MissingDecisionPointsError, "missing decision points"),
        ],
    )
    def test_validation_config_error_not_swallowed(self, exc_type, message, tmp_path, monkeypatch):
        """ConfigurationError / MissingDecisionPointsError propagate out of
        ``cli()`` as their own type - never converted to SystemExit(2) nor
        swallowed into the friendly crash message."""
        monkeypatch.chdir(tmp_path)
        with (
            patch("tax_reporting.main._run_validation_from_cli", side_effect=exc_type(message)),
            patch("sys.argv", ["tax-reporting", "--validate-on-chain-th", "2025"]),
            pytest.raises(exc_type, match=message),
        ):
            cli()


def test_main_raises_configuration_error_for_missing_decision_points(tmp_path):
    """_main() propagates configuration errors for missing decision points TOML."""
    source_file = tmp_path / "ib_export.csv"
    source_file.write_text("header\n", encoding="utf-8")

    with (
        patch("tax_reporting.main.run_report"),
        patch(
            "tax_reporting.main.load_configuration_from_file",
            side_effect=MissingDecisionPointsError("missing toml"),
        ),
        pytest.raises(ConfigurationError, match="missing toml"),
    ):
        _main(source_file=source_file, output_dir=tmp_path)
