"""Task 6: ``main.py`` wiring of the on-chain fetcher as a non-blocking step.

TDD RED -> GREEN. These tests pin the wiring of :func:`run_on_chain_fetch`
into the crypto ``try`` block of :func:`tax_reporting.main._main`, AFTER
``generate_tax_report(...)`` and BEFORE the ``except ConfigurationError``
clause. The wiring must be:

- **Env-var gated in main.py (DI-3):** the ``BERA_CHAIN_API_KEY`` gate lives
  HERE, not inside the fetcher. When the env var is unset the fetcher is
  never called and the IB/Koinly report still generates.
- **Year-resolved defensively (DI-9):** ``on_chain_year`` falls back to the
  IB-inferred ``tax_year_hint`` when ``tax_jurisdiction is None``, so a
  future relaxation of the upstream STRICT jurisdiction guard cannot raise
  ``AttributeError``.
- **Non-blocking (r1 F1):** the wiring catch is ``except Exception`` (broad),
  mirroring the optional-Koinly degrade template at the helper below. Any
  exception from the fetcher (``FileProcessingError``,
  ``urllib.error.URLError``, ``json.JSONDecodeError``, plain ``Exception``)
  is logged as a WARNING and swallowed; the IB/Koinly report still
  generates. The fetcher never aborts the crypto/IB pipeline.

The tests drive ``_main`` end-to-end against the committed example data
(``resources/source/example/ib_export.csv``) so ``extract.xlsx`` actually
generates. Logging assertions read the on-disk audit trail
(``logs/tax-reporting.log``) rather than ``caplog``, because
``_main`` reconfigures the root logger (clearing handlers) which would
detach pytest's caplog handler mid-run. The on-chain seams (the fetcher
symbol, the ``BERA_CHAIN_API_KEY`` env var via ``os.getenv`` on the
``main`` module, and ``load_on_chain_wallets`` to control config presence)
are monkeypatched so no network or real-config dependency leaks in.
"""

from __future__ import annotations

import json
import urllib.error
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from tax_reporting.domain.exceptions import ReportGenerationError
from tax_reporting.main import _main

# Repo root (resolved relative to this test file:
# tests/unit/application/test_main_on_chain_wiring.py -> parents[3] = repo root).
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_EXAMPLE_SOURCE = _PROJECT_ROOT / "resources" / "source" / "example" / "ib_export.csv"


def _pt_2025_config():
    """A Config carrying a PT/2025 jurisdiction with a resolved timezone.

    Passed to ``_main`` via ``load_configuration_from_file`` so the crypto
    STRICT localization guard clears and the run reaches
    ``generate_tax_report``.
    """
    from tax_reporting.domain.jurisdiction import TaxJurisdictionConfig
    from tax_reporting.infrastructure.config import Config

    return Config(
        base="EUR",
        rates=[],
        tax_jurisdiction=TaxJurisdictionConfig(
            country="PT",
            fiscal_year=2025,
            exclude_loan_repayment_gains=True,
            zero_basis_review_threshold=Decimal("50"),
            timezone=ZoneInfo("Europe/Lisbon"),
        ),
        log_level="WARNING",
    )


def _no_jurisdiction_config():
    """A Config with ``tax_jurisdiction=None`` (the no-config-but-not-raised case)."""
    from tax_reporting.infrastructure.config import Config

    return Config(
        base="EUR",
        rates=[],
        tax_jurisdiction=None,
        log_level="WARNING",
    )


def _make_getenv(env_value: str | None):
    """Return an ``os.getenv`` substitute that returns ``env_value`` for the on-chain key.

    For every OTHER key it delegates to the real ``os.getenv`` so unrelated
    reads keep working. ``env_value`` may be ``None`` (unset) or a non-empty
    string (set).
    """
    import os

    real_getenv = os.getenv

    def _getenv(key: str, default=None):  # type: ignore[no-untyped-def]
        if key == "BERA_CHAIN_API_KEY":
            return env_value if env_value is not None else default
        return real_getenv(key, default)

    return _getenv


class _Recorder:
    """Records calls to ``run_on_chain_fetch`` and optionally raises."""

    def __init__(self, *, return_value: Path | None = None, exc: BaseException | None = None):
        self.calls: list[dict] = []
        self._return_value = return_value
        self._exc = exc

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        if self._exc is not None:
            raise self._exc
        return self._return_value


def _artificial_wallet():
    """A non-real OnChainWalletConfig (no chain-identity literals in this file)."""
    from datetime import date

    from tax_reporting.application.on_chain_config import OnChainWalletConfig

    return OnChainWalletConfig(
        chain="Examplechain",
        chainid=99999,
        label="Example Wallet (EXM)",
        address="0x0000000000000000000000000000000000001111",
        native_ticker="EXM",
        start_date=date(2025, 2, 6),
        end_date=date(2025, 12, 31),
    )


@pytest.fixture()
def example_run(tmp_path, monkeypatch):
    """Return a helper that drives ``_main`` against the committed example data.

    The helper accepts the on-chain seams (fetcher recorder, env value,
    config to inject via ``load_configuration_from_file``) and runs ``_main``
    to completion. It returns a tuple ``(extract_path, log_text)`` where
    ``log_text`` is the on-disk audit trail content (the reliable capture
    mechanism, since ``_main`` reconfigures the root logger and detaches
    caplog mid-run).

    ``patch_fetcher`` controls whether ``run_on_chain_fetch`` is replaced by
    the recorder (True) or left as the real symbol (False). When left real,
    ``load_on_chain_wallets`` is still patched so no real config/network is
    touched; this lets the config-absent test exercise the real orchestrator
    WARNING (DI-6 single-WARNING ownership).

    ``resolve_koinly_none`` forces ``_resolve_koinly_directory`` to return
    None so the crypto block skips cleanly (used by the no-jurisdiction test
    to reach the on-chain wiring without tripping the STRICT guard).
    """
    # The crypto/IB pipeline re-reads ``config.ini`` from the CWD independently
    # of ``load_configuration_from_file`` (for exchange rates), so do NOT chdir
    # away from the repo root: keep the committed ``config.ini`` resolvable.
    # The on-disk audit trail is captured by redirecting the file handler: patch
    # ``configure_application_logging`` to forward to the real implementation but
    # with ``log_file`` pointed at a tmp path (so logs land there instead of the
    # repo-root ``logs/`` dir). This is the reliable capture mechanism because
    # ``_main`` reconfigures the root logger and detaches pytest's caplog mid-run.
    tmp_log = tmp_path / "audit.log"
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    extract_path = out_dir / "extract.xlsx"

    from tax_reporting.infrastructure import logging_config as _logging_config

    _real_configure = _logging_config.configure_application_logging

    def _redirecting_configure(*args, **kwargs):  # type: ignore[no-untyped-def]
        kwargs["log_file"] = tmp_log
        return _real_configure(*args, **kwargs)

    def run(
        *,
        fetcher,
        env_value,
        config,
        wallets,
        flags: dict[str, bool] | None = None,
    ):
        import contextlib

        opts = flags or {}
        patch_fetcher = opts.get("patch_fetcher", True)
        resolve_koinly_none = opts.get("resolve_koinly_none", False)

        monkeypatch.setattr(
            "tax_reporting.application.on_chain_fetcher.load_on_chain_wallets",
            lambda _year, **_kw: list(wallets),
        )
        if patch_fetcher:
            monkeypatch.setattr("tax_reporting.main.run_on_chain_fetch", fetcher)
        monkeypatch.setattr("tax_reporting.main.os.getenv", _make_getenv(env_value))
        monkeypatch.setattr(
            "tax_reporting.main.configure_application_logging", _redirecting_configure
        )

        with contextlib.ExitStack() as stack:
            stack.enter_context(
                patch("tax_reporting.main.load_configuration_from_file", return_value=config)
            )
            if resolve_koinly_none:
                stack.enter_context(
                    patch("tax_reporting.main._resolve_koinly_directory", return_value=None)
                )
            _main(source_file=_EXAMPLE_SOURCE, output_dir=out_dir, log_level="WARNING")

        log_text = tmp_log.read_text(encoding="utf-8") if tmp_log.exists() else ""
        return extract_path, log_text

    return run


@pytest.mark.unit
class TestMainOnChainWiring:
    """Pin the on-chain fetcher wiring in ``main.py`` (Task 6)."""

    def test_skips_when_env_var_absent(self, example_run):
        """Env-var gate lives in main.py (DI-3/DI-9): BERA_CHAIN_API_KEY unset -> no fetch call.

        ``chains.json`` is "present" (loader returns a wallet) but the env var
        is None. The fetcher must NOT be called, a WARNING mentioning the env
        var is logged, and ``extract.xlsx`` still generates.
        """
        recorder = _Recorder(return_value=Path("/fake/bera_transactions.csv"))
        extract_path, log_text = example_run(
            fetcher=recorder,
            env_value=None,
            config=_pt_2025_config(),
            wallets=[_artificial_wallet()],
        )

        assert recorder.calls == [], "fetcher must not be called when env var is absent"
        assert extract_path.exists(), "extract.xlsx must still generate"
        assert "BERA_CHAIN_API_KEY" in log_text, (
            "a WARNING mentioning BERA_CHAIN_API_KEY must reach the audit trail"
        )

    def test_skips_when_config_absent(self, example_run):
        """Config-absent: loader returns [] silently; orchestrator WARNING fires ONCE (DI-6).

        The env var is set but ``load_on_chain_wallets`` returns ``[]`` (no
        chains.json for the year). The fetcher symbol is left as the REAL
        orchestrator (the recorder is installed but the orchestrator returns
        None on empty wallets before any network). The orchestrator owns the
        SINGLE WARNING; the loader stays silent. extract.xlsx generates. This
        guards the r1 F5 double-WARNING regression: assert EXACTLY one
        WARNING record for the config-absent condition.
        """
        recorder = _Recorder()
        extract_path, log_text = example_run(
            fetcher=recorder,
            env_value="some-key",
            config=_pt_2025_config(),
            wallets=[],  # config absent for the year
            flags={"patch_fetcher": False},  # let the real orchestrator run + emit its WARNING
        )

        # No network fetch happened (empty wallets -> orchestrator returns None
        # before touching any client). The recorder was NOT installed, so it
        # records nothing.
        assert recorder.calls == []
        assert extract_path.exists()
        # The single orchestrator WARNING for the empty-config condition.
        count = log_text.count("No chains.json for year")
        assert count == 1, (
            "exactly ONE WARNING for the config-absent condition (DI-6 single-WARNING "
            f"ownership); got {count} occurrence(s) in the audit trail"
        )

    def test_skips_when_no_jurisdiction(self, example_run):
        """No jurisdiction (tax_jurisdiction is None) + config present + env set -> no fetch, no AttributeError (DI-9).

        Defends against the upstream STRICT jurisdiction guard being relaxed:
        with ``tax_jurisdiction is None`` and the Koinly directory forced to be
        absent (so the crypto STRICT guard does not fire), the year must
        resolve defensively (to ``tax_year_hint``) and the run must not raise
        ``AttributeError``. The fetcher IS reached but here the env-var gate
        proves the path is exercised; we assert no AttributeError escapes and
        extract.xlsx generates.
        """
        recorder = _Recorder(return_value=Path("/fake/bera_transactions.csv"))
        extract_path, _ = example_run(
            fetcher=recorder,
            env_value="some-key",
            config=_no_jurisdiction_config(),
            wallets=[_artificial_wallet()],
            flags={"resolve_koinly_none": True},  # skip crypto STRICT guard, reach the wiring
        )

        # With no jurisdiction, on_chain_year falls back to the IB tax_year_hint
        # (DI-9). The example IB data resolves a year, so the fetcher is called
        # once with the defensively-resolved year (NOT a None that would crash).
        assert len(recorder.calls) == 1, "fetcher reached once with the defensively-resolved year"
        assert recorder.calls[0]["year"] is not None
        assert extract_path.exists()

    def test_runs_when_both_present(self, example_run):
        """Both config + env var present -> fetcher called once with correct year + output_dir (DI-9)."""
        fake_csv = Path("/fake/bera_transactions.csv")
        recorder = _Recorder(return_value=fake_csv)
        extract_path, _ = example_run(
            fetcher=recorder,
            env_value="some-key",
            config=_pt_2025_config(),
            wallets=[_artificial_wallet()],
        )

        assert len(recorder.calls) == 1, "fetcher must be called exactly once"
        call = recorder.calls[0]
        assert call["year"] == 2025, (
            "year must be resolved defensively from the jurisdiction fiscal_year (DI-9)"
        )
        # output_dir is the validated absolute output dir for the run.
        assert call["output_dir"].name == extract_path.parent.name
        assert call["api_key"] == "some-key"
        assert extract_path.exists(), "extract.xlsx must still generate"

    def test_fetch_failure_non_fileprocessingerror_is_non_blocking(self, example_run):
        """r1 F1 guard: a URLError from the fetcher is swallowed (broad except), report still generates."""
        recorder = _Recorder(exc=urllib.error.URLError("boom"))
        extract_path, log_text = example_run(
            fetcher=recorder,
            env_value="some-key",
            config=_pt_2025_config(),
            wallets=[_artificial_wallet()],
        )

        assert extract_path.exists(), "extract.xlsx must generate despite the fetch failure"
        assert len(recorder.calls) == 1, "fetcher must have been invoked"
        assert "Continuing without on-chain transaction data" in log_text, (
            "a WARNING containing 'Continuing without on-chain transaction data' must reach "
            "the audit trail"
        )

    @pytest.mark.parametrize(
        "exc",
        [
            urllib.error.URLError("boom"),
            json.JSONDecodeError("Expecting value", "<doc>", 0),
            RuntimeError("plain exception"),
        ],
        ids=["URLError", "JSONDecodeError", "Exception"],
    )
    def test_fetch_failure_parametrized_is_non_blocking(self, exc, example_run):
        """Parametrized r1 F1 guard: URLError, JSONDecodeError, plain Exception are all non-blocking."""
        recorder = _Recorder(exc=exc)
        try:
            extract_path, log_text = example_run(
                fetcher=recorder,
                env_value="some-key",
                config=_pt_2025_config(),
                wallets=[_artificial_wallet()],
            )
        except ReportGenerationError:
            pytest.fail("broad except must swallow the exception, not let ReportGenerationError escape")

        assert extract_path.exists(), "extract.xlsx must generate despite the fetch failure"
        assert "Continuing without on-chain transaction data" in log_text, (
            "a WARNING containing 'Continuing without on-chain transaction data' must reach "
            "the audit trail"
        )

    def test_extract_report_unaffected_by_fetch(self, example_run):
        """Frozen-pipeline invariant: the fetcher never touches the IB/Koinly extract content.

        Runs the full happy path twice against the same example data: once
        with the fetcher returning a fake Path, once with the env var unset
        (fetcher disabled). The generated ``extract.xlsx`` is byte-identical
        between the two runs, proving the on-chain step is a read-only
        parallel collection that never mutates the report.
        """
        out_a, _ = example_run(
            fetcher=_Recorder(return_value=Path("/fake/bera_transactions.csv")),
            env_value="some-key",
            config=_pt_2025_config(),
            wallets=[_artificial_wallet()],
        )
        bytes_a = out_a.read_bytes()

        out_b, _ = example_run(
            fetcher=_Recorder(),
            env_value=None,
            config=_pt_2025_config(),
            wallets=[_artificial_wallet()],
        )
        bytes_b = out_b.read_bytes()

        assert bytes_a == bytes_b, (
            "extract.xlsx must be byte-identical whether or not the on-chain fetcher runs"
        )
