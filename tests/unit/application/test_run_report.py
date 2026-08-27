"""Characterization tests for the injectable ``run_report`` orchestrator.

Task 2 of the main-composition-root decomposition plan: ``run_report`` hosts the
pipeline body moved verbatim out of ``_main``. It takes every collaborator
(config object, on-chain fetch callable, logger) as a parameter and performs no
environment reads (DI-3), keeps the broad ``except Exception`` soft-fail scoped
to the injected fetch call only (DI-1), and resolves the on-chain year
defensively for a ``None`` jurisdiction (DI-9).
"""

from __future__ import annotations

import ast
import importlib
import inspect
import logging
import os
import pkgutil
import re
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from tax_reporting.application import run_report as run_report_module
from tax_reporting.application.on_chain_fetcher import bera_csv_path, fetch_failed_marker_path
from tax_reporting.application.run_report import run_report
from tax_reporting.domain.collections import IBExportData
from tax_reporting.domain.exceptions import ReportGenerationError
from tax_reporting.infrastructure.config import Config, TaxJurisdictionConfig
from tests.unit.application.conftest import (  # shared plain helpers (review r2 F10)
    BERA_CSV_HEADER as _BERA_CSV_HEADER,
)
from tests.unit.application.conftest import (
    stale_marker_state,
)


def _pt_config(fiscal_year: int = 2025) -> Config:
    """A minimal PT Config whose fiscal year resolves (drives the fetch year)."""
    return Config(
        base="EUR",
        rates=[],
        tax_jurisdiction=TaxJurisdictionConfig(
            country="PT",
            fiscal_year=fiscal_year,
            exclude_loan_repayment_gains=False,
            zero_basis_review_threshold=Decimal("50"),
        ),
        log_level="WARNING",
    )


@pytest.fixture()
def empty_source(tmp_path: Path) -> Path:
    """A source CSV plus patches making the IB pipeline a deterministic no-op.

    Mirrors the characterization pattern in ``tests/unit/test_cli.py``: the
    loader/orchestrator collaborators are patched on
    ``tax_reporting.application.run_report``, the namespace the orchestrator
    calls them through; never on ``tax_reporting.main``.
    """
    source = tmp_path / "ib_export.csv"
    source.write_text("Statement,Header,Field Name,Field Value\n", encoding="utf-8")
    return source


@pytest.mark.unit
class TestRunReport:
    def test_no_env_reads_is_static(self) -> None:
        """DI-3 boundary: the orchestrator layer contains no env reads at all.

        The module set is DERIVED from the package (every module of
        ``tax_reporting.application``, including subpackage modules such as
        ``crypto/``, ``crypto_fifo/``, ``extraction/``, and ``persisting/``),
        so a future split/added orchestrator module cannot silently escape
        the guard.

        Static AST check (immune to prose). DI-3 bans env READS, not ``import
        os`` itself (``on_chain_th_substitution`` legitimately imports ``os``
        for ``os.fsync``), so the guard catches:

        - attribute access (``os.getenv`` / ``os.environ``) regardless of
          import style, and
        - ``from os import getenv`` / ``from os import environ`` alias forms:
          the ImportFrom node itself (only when the alias is getenv/environ -
          harmless ``from os import PathLike`` etc. must not trip), plus bare
          ``Name`` calls of the aliased names (``getenv(...)`` /
          ``environ[...]``).

        A prose edit (e.g. the word "environment" in a docstring) cannot
        false-fail.
        """
        application_pkg = importlib.import_module("tax_reporting.application")
        # Seed with the package module itself: walk_packages yields only children,
        # never the root package, so ``application/__init__.py`` must be added
        # explicitly to stay inside the guard.
        module_names = [application_pkg.__name__]
        skipped: list[str] = []
        traversal_errors: list[str] = []

        def _onerror(name: str) -> None:
            traversal_errors.append(name)

        module_names += [
            name
            for _, name, _ in pkgutil.walk_packages(
                application_pkg.__path__, prefix=f"{application_pkg.__name__}.", onerror=_onerror
            )
        ]
        modules = []
        for name in module_names:
            try:
                modules.append(importlib.import_module(name))
            except ImportError:
                skipped.append(name)
        assert not skipped, f"unimportable application module(s) escape the DI-3 guard: {skipped}"
        assert not traversal_errors, f"pkgutil traversal error(s) escaped the DI-3 guard: {traversal_errors}"
        assert run_report_module in modules, "run_report must be an application module"

        for module in modules:
            source = inspect.getsource(module)
            tree = ast.parse(source)
            violations: list[ast.AST] = [
                node
                for node in ast.walk(tree)
                if isinstance(node, ast.Attribute) and node.attr in {"getenv", "environ"}
            ]
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and (
                    (node.module == "os" and any(alias.name in {"getenv", "environ"} for alias in node.names))
                    or (node.module == "os.environ")
                ):
                    violations.append(node)
                if isinstance(node, ast.Name) and node.id in {"getenv", "environ"}:
                    violations.append(node)
            assert not violations, f"{module.__name__} must not read the environment (DI-3): {violations}"

    def test_injected_fetch_called(self, empty_source: Path, tmp_path: Path, monkeypatch, caplog) -> None:
        """A non-None fetch callable is invoked exactly once with (year, output_dir)."""
        monkeypatch.setattr(run_report_module, "parse_ib_export_all", lambda _p: IBExportData({}, {}))
        output_dir = tmp_path / "out"
        calls: list[tuple[object, object]] = []

        def _fetch(*, year: int, output_dir: Path) -> str:
            calls.append((year, output_dir))
            return "discarded-result"

        with caplog.at_level(logging.WARNING):
            run_report(
                source_file=empty_source,
                output_dir=output_dir,
                app_config=_pt_config(fiscal_year=2025),
                on_chain_fetch=_fetch,
                logger=logging.getLogger("test_run_report"),
            )

        assert calls == [(2025, output_dir)]

    def test_injected_fetch_soft_fail(self, empty_source: Path, tmp_path: Path, monkeypatch, caplog) -> None:
        """DI-1 at the new call site: a raising fetch only WARNINGs; the run completes.

        The broad ``except Exception`` soft-fail must cover ONLY the injected
        collection fetch call; the report is still generated.
        """
        monkeypatch.setattr(run_report_module, "parse_ib_export_all", lambda _p: IBExportData({}, {}))
        output_dir = tmp_path / "out"

        def _boom(*, year: int, output_dir: Path) -> None:
            raise RuntimeError("boom")

        with caplog.at_level(logging.WARNING):
            run_report(
                source_file=empty_source,
                output_dir=output_dir,
                app_config=_pt_config(fiscal_year=2025),
                on_chain_fetch=_boom,
                logger=logging.getLogger("test_run_report"),
            )

        assert any(
            "On-chain fetch failed: boom" in record.message
            for record in caplog.records
            if record.levelno == logging.WARNING
        ), f"expected soft-fail WARNING, got: {[r.message for r in caplog.records]}"
        assert (output_dir / "extract.xlsx").exists()
        # Review r1 F6: the soft-fail must also write the staleness marker
        # next to where the CSV would live and name the stale-CSV
        # consequence in the WARNING text.
        from tax_reporting.application.on_chain_fetcher import fetch_failed_marker_path

        marker = fetch_failed_marker_path(output_dir, 2025)
        assert marker.is_file(), f"expected fetch-failure marker at {marker}"
        assert "On-chain fetch failed: boom" in marker.read_text(encoding="utf-8")
        assert any(
            "STALE" in record.getMessage() for record in caplog.records
        ), "expected the WARNING to name the stale-CSV consequence"
        # Task 4 (retry-ladder plan): the soft-fail message must name the
        # consequence under the retry-then-refuse contract - the next opted-in
        # run retries the fetch automatically and refuses if every attempt
        # fails - and must NOT claim a later ERROR log (false under the new
        # contract; review r1 F2).
        soft_fail_messages = [
            record.getMessage()
            for record in caplog.records
            if "On-chain fetch failed: boom" in record.getMessage()
        ]
        assert soft_fail_messages, "expected the soft-fail WARNING record"
        assert any("refuse" in message for message in soft_fail_messages), (
            "expected the soft-fail WARNING to name the refusal consequence"
        )
        assert not any("will log an error" in message for message in soft_fail_messages), (
            "soft-fail WARNING must not claim a later ERROR log"
        )

    def test_fetch_skipped_when_none(self, empty_source: Path, tmp_path: Path, monkeypatch, caplog) -> None:
        """``on_chain_fetch=None`` means skip: no fetch attempt, no failure log."""
        monkeypatch.setattr(run_report_module, "parse_ib_export_all", lambda _p: IBExportData({}, {}))
        output_dir = tmp_path / "out"

        with caplog.at_level(logging.WARNING):
            run_report(
                source_file=empty_source,
                output_dir=output_dir,
                app_config=_pt_config(fiscal_year=2025),
                on_chain_fetch=None,
                logger=logging.getLogger("test_run_report"),
            )

        assert not any("On-chain fetch failed" in record.message for record in caplog.records)
        assert not any("No tax year resolved" in record.message for record in caplog.records)
        assert (output_dir / "extract.xlsx").exists()

    def test_no_tax_year_warning(self, tmp_path: Path, caplog) -> None:
        """DI-9: no year resolvable -> WARNING, run still completes (r1 F3).

        The source directory must be Koinly-free: with a Koinly directory present
        the STRICT timezone guard would raise ``ConfigurationError`` (no
        jurisdiction via ``app_config=None``) before the year check.
        """
        source = tmp_path / "ib_export.csv"
        fi_header = (
            "Financial Instrument Information,Header,Asset Category,Symbol,Description,"
            "Conid,Security ID,Underlying,Listing Exch,Multiplier,Type,Code"
        )
        fi_row = (
            "Financial Instrument Information,Data,Stocks,ACME,ACME CORPORATION,"
            "10000001,US0000000001,ACME,NYSE,1,COMMON,"
        )
        trades_header = (
            "Trades,Header,DataDiscriminator,Asset Category,Currency,Symbol,Date/Time,"
            "Quantity,T. Price,C. Price,Proceeds,Comm/Fee,Basis,Realized P/L,MTM P/L,Code"
        )
        dividend_row = (
            "Dividends,Data,EUR,2024-06-01,ACME(US0000000001) Cash Dividend EUR 0.50 per "
            "Share (Ordinary Dividend),25.00"
        )
        source.write_text(
            "\n".join(
                [
                    "Statement,Header,Field Name,Field Value",
                    fi_header,
                    fi_row,
                    trades_header,
                    "Dividends,Header,Currency,Date,Description,Amount",
                    dividend_row,
                    "",
                ]
            ),
            encoding="utf-8",
        )

        with caplog.at_level(logging.WARNING):
            run_report(
                source_file=source,
                output_dir=tmp_path / "out",
                app_config=None,
                on_chain_fetch=lambda **_kw: pytest.fail("fetch must not run without a resolved year"),
                logger=logging.getLogger("test_run_report"),
            )

        assert any(
            "No tax year resolved for on-chain fetch" in record.message
            for record in caplog.records
            if record.levelno == logging.WARNING
        ), f"expected no-tax-year WARNING, got: {[r.message for r in caplog.records]}"
        assert (tmp_path / "out" / "extract.xlsx").exists()

# --- Plan 2026-08-26 Task 1: staleness retry-then-refuse ladder (RED) ---

_TEST_WALLET_LABEL = "bera-test-wallet"


def _stale_on_chain_jurisdiction() -> TaxJurisdictionConfig:
    """A PT jurisdiction with ONE opted-in on-chain TH wallet."""
    return TaxJurisdictionConfig(
        country="PT",
        fiscal_year=2025,
        exclude_loan_repayment_gains=False,
        zero_basis_review_threshold=Decimal("50"),
        on_chain_th_wallets=[_TEST_WALLET_LABEL],
    )


class _FakeSubstituter:
    """Recording stand-in for ``OnChainThSubstituter`` on the run_report patch
    seam; ``maybe_substitute`` succeeds and records its kwargs."""

    calls: list[dict[str, Any]] = []

    def __init__(self, *, on_chain_rpc_url: str | None = None) -> None:
        self._on_chain_rpc_url = on_chain_rpc_url

    def maybe_substitute(self, **kwargs) -> SimpleNamespace:
        type(self).calls.append(kwargs)
        return SimpleNamespace(reconciliation="RECON", merged_th_path=Path("on_chain_merged_th.csv"))


def _stale_on_chain_jurisdiction_with_tz() -> TaxJurisdictionConfig:
    """Opted-in PT jurisdiction with a resolved timezone (full-run tests)."""
    return TaxJurisdictionConfig(
        country="PT",
        fiscal_year=2025,
        exclude_loan_repayment_gains=False,
        zero_basis_review_threshold=Decimal("50"),
        on_chain_th_wallets=[_TEST_WALLET_LABEL],
        timezone=ZoneInfo("Europe/Lisbon"),
    )


@pytest.mark.unit
class TestRunReportStalenessRetry:
    """Retry ladder entered from ``run_report._substitute_on_chain_th`` (body
    in ``on_chain_retry``; plan Task 1 RED).

    All tests monkeypatch ``run_report._retry_sleep`` to a recording fake; no
    test sleeps for real (hermetic; per-test 120 s timeout).
    """

    LOGGER_NAME = "test_run_report_staleness_retry"

    @pytest.fixture(autouse=True)
    def _reset_fake_substituter_calls(self):
        """Review r1 F6: reset the shared class-level recording state per test,
        so a future test reaching the fake without ``_patch_common`` cannot
        inherit prior invocations."""
        _FakeSubstituter.calls = []
        yield
        _FakeSubstituter.calls = []

    def _patch_common(self, monkeypatch) -> list:
        """Patch the sleep seam (recording) and the substituter; return events.

        ``_FakeSubstituter.calls`` is reset solely by the autouse fixture
        (single reset point; review r3 F16)."""
        events: list = []

        def _record_sleep(delay: float) -> None:
            events.append(("sleep", delay))

        monkeypatch.setattr(run_report_module, "_retry_sleep", _record_sleep)
        monkeypatch.setattr(run_report_module, "OnChainThSubstituter", _FakeSubstituter)
        return events

    def _run_substitution(self, tmp_path, monkeypatch, on_chain_fetch, logger):
        return run_report_module._substitute_on_chain_th(
            koinly_dir=tmp_path / "koinly",
            output_dir=tmp_path,
            year=2025,
            tax_jurisdiction=_stale_on_chain_jurisdiction(),
            logger=logger,
            on_chain_fetch=on_chain_fetch,
        )

    def test_retry_ladder_recovers_mid_way(self, tmp_path, monkeypatch, caplog) -> None:
        """A stale marker + injected fetch that fails twice then rewrites the
        CSV newer: three attempts (sleeps 1.0/2.0/4.0 BEFORE each), two
        WARNINGs, one recovery INFO, and a successful substitution (r8-F1)."""
        events = self._patch_common(monkeypatch)
        bera, marker = stale_marker_state(tmp_path, year=2025)
        fetch_calls: list[int] = []

        def _flaky_fetch(*, year: int, output_dir: Path) -> Path:
            fetch_calls.append(len(fetch_calls) + 1)
            events.append(("fetch", len(fetch_calls)))
            if len(fetch_calls) < 3:
                raise RuntimeError("quota exhausted")
            # Success: rewrite the CSV NEWER than the marker (landed self-heal).
            bera.write_text(_BERA_CSV_HEADER + "\n,recovered\n", encoding="utf-8")
            csv_new = marker.stat().st_mtime + 10
            os.utime(bera, (csv_new, csv_new))
            return bera

        logger = logging.getLogger(self.LOGGER_NAME)
        with caplog.at_level(logging.INFO, logger=self.LOGGER_NAME):
            reconciliation, override = self._run_substitution(
                tmp_path, monkeypatch, _flaky_fetch, logger
            )

        # Successful substitution: the (fake) maybe_substitute ran and its
        # result was threaded through.
        assert len(_FakeSubstituter.calls) == 1
        assert reconciliation == "RECON"
        assert override == Path("on_chain_merged_th.csv")
        assert len(fetch_calls) == 3
        # Sleep BEFORE each of the three attempts (r8-F1).
        assert events == [
            ("sleep", 1.0), ("fetch", 1),
            ("sleep", 2.0), ("fetch", 2),
            ("sleep", 4.0), ("fetch", 3),
        ]
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 2, (
            f"expected 2 per-attempt WARNINGs, got: {[r.getMessage() for r in warnings]}"
        )
        assert all("quota exhausted" in r.getMessage() for r in warnings)
        # Review r1 F7: pin the backoff delay in the per-attempt WARNING text
        # (a delay-free or wrong-delay message must fail the suite).
        assert "after 1.0 s backoff" in warnings[0].getMessage()
        assert "after 2.0 s backoff" in warnings[1].getMessage()
        assert sum(
            1
            for r in caplog.records
            if r.levelno == logging.INFO
            and "recovered from a stale on-chain fetch condition" in r.getMessage().lower()
        ) == 1, f"expected one recovery INFO, got: {[r.getMessage() for r in caplog.records]}"

    def test_retry_ladder_exhaustion_refuses(self, tmp_path, monkeypatch, caplog) -> None:
        """All six attempts fail: the LADDER raises the M1-boundary
        ``ReportGenerationError`` itself (before ``maybe_substitute`` is ever
        called; r8-F2) naming "6 automatic refetch attempts failed", with the
        full backoff sequence (1.0 .. 32.0)."""
        events = self._patch_common(monkeypatch)
        _bera, marker = stale_marker_state(tmp_path, year=2025)
        fetch_calls: list[int] = []

        def _always_fails(*, year: int, output_dir: Path) -> Path:
            fetch_calls.append(len(fetch_calls) + 1)
            events.append(("fetch", len(fetch_calls)))
            raise RuntimeError("api down")

        logger = logging.getLogger(self.LOGGER_NAME)
        with (
            caplog.at_level(logging.INFO, logger=self.LOGGER_NAME),
            pytest.raises(ReportGenerationError, match=r"6 automatic refetch attempts failed") as excinfo,
        ):
            self._run_substitution(tmp_path, monkeypatch, _always_fails, logger)

        assert len(fetch_calls) == 6
        assert [d for kind, d in events if kind == "sleep"] == [1.0, 2.0, 4.0, 8.0, 16.0, 32.0]
        assert [k for k, _ in events if k == "fetch"] == ["fetch"] * 6
        # maybe_substitute is NEVER reached (r8-F2).
        assert _FakeSubstituter.calls == []
        # Review r2 F6: the primary user-facing refusal message must carry the
        # manual-clear clause and name the marker (dropping either must fail).
        message = str(excinfo.value)
        assert marker.name in message, f"exhaustion refusal must name the marker; got: {message}"
        assert "delete the marker" in message.lower(), (
            f"exhaustion refusal must give the manual clear; got: {message}"
        )
        # Review r2 F5: the two exhaustion-path log records are pinned (the
        # entry INFO and the terminal ERROR are the operator's only pre-exception
        # signal of the multi-minute blocking retry window).
        infos = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
        errors = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
        assert any("retrying the fetch automatically" in m for m in infos), (
            f"expected the ladder entry INFO; got: {infos}"
        )
        assert any("could not be refreshed" in m for m in errors), (
            f"expected the terminal exhaustion ERROR; got: {errors}"
        )

    def test_no_fetch_callable_refuses_immediately(self, tmp_path, monkeypatch, caplog) -> None:
        """``on_chain_fetch=None`` (no API key wired): no ladder, no sleeps,
        and the ``build_projection`` refusal propagates out of
        ``_substitute_on_chain_th`` (r9-F1: its message must carry NO attempt
        count - the two refusal causes stay discriminable).

        Uses the REAL ``OnChainThSubstituter`` so the raise comes from the
        production ``build_projection`` staleness check, not a fake."""
        events: list = []

        def _record_sleep(delay: float) -> None:
            events.append(("sleep", delay))

        monkeypatch.setattr(run_report_module, "_retry_sleep", _record_sleep)
        bera, marker = stale_marker_state(tmp_path, year=2025)
        fetch_calls: list[int] = []

        def _must_not_run(**_kwargs) -> None:
            fetch_calls.append(1)
            pytest.fail("fetch must not run without an injected fetch callable")

        logger = logging.getLogger(self.LOGGER_NAME)
        with (
            caplog.at_level(logging.INFO, logger=self.LOGGER_NAME),
            pytest.raises(ReportGenerationError, match=r"fetch-failed") as excinfo,
        ):
            self._run_substitution(tmp_path, monkeypatch, None, logger)

        message = str(excinfo.value)
        assert str(bera) in message
        assert marker.name in message
        # Count-agnostic discriminator (r3 F5): the no-callable refusal must
        # carry NO exhaustion-attempts clause regardless of the schedule size.
        assert not re.search(r"\d+ automatic refetch attempts failed", message)
        assert fetch_calls == []
        assert events == []

    def test_healthy_state_skips_ladder(self, tmp_path, monkeypatch) -> None:
        """No marker: the substitution proceeds with ZERO fetch invocations
        (the ladder is entered only on a stale marker)."""
        events = self._patch_common(monkeypatch)
        bera = bera_csv_path(tmp_path, 2025)
        bera.parent.mkdir(parents=True, exist_ok=True)
        bera.write_text(_BERA_CSV_HEADER + "\n", encoding="utf-8")
        assert not fetch_failed_marker_path(tmp_path, 2025).exists()
        fetch_calls: list[int] = []

        def _must_not_run(**_kwargs) -> None:
            fetch_calls.append(1)
            pytest.fail("healthy state must not enter the retry ladder")

        reconciliation, override = self._run_substitution(
            tmp_path, monkeypatch, _must_not_run, logging.getLogger(self.LOGGER_NAME)
        )

        assert len(_FakeSubstituter.calls) == 1
        assert reconciliation == "RECON"
        assert override == Path("on_chain_merged_th.csv")
        assert fetch_calls == []
        assert events == []

    def test_retry_ladder_does_not_delete_marker(self, tmp_path, monkeypatch) -> None:
        """Exhaustion leaves the marker on disk (deletion is the USER's manual
        clear; the ladder introduces no cleanup path - design invariant)."""
        self._patch_common(monkeypatch)
        bera, marker = stale_marker_state(tmp_path, year=2025)

        def _always_fails(*, year: int, output_dir: Path) -> Path:
            raise RuntimeError("api down")

        with pytest.raises(ReportGenerationError, match=r"6 automatic refetch attempts failed"):
            self._run_substitution(
                tmp_path, monkeypatch, _always_fails, logging.getLogger(self.LOGGER_NAME)
            )

        assert marker.is_file(), "the ladder must not delete the marker"

    def test_retry_ladder_treats_none_return_as_failed_attempt(
        self, tmp_path, monkeypatch, caplog
    ) -> None:
        """A fetch returning ``None`` (the empty-wallet-config branch:
        rewrites nothing) counts as a FAILED attempt: six attempts, each with
        a WARNING naming the None return, then the exhaustion refusal, and no
        CSV rewrite (r11-F1)."""
        events = self._patch_common(monkeypatch)
        bera, _marker = stale_marker_state(tmp_path, year=2025)
        content_before = bera.read_text(encoding="utf-8")
        mtime_before = bera.stat().st_mtime
        fetch_calls: list[int] = []

        def _returns_none(*, year: int, output_dir: Path) -> None:
            fetch_calls.append(len(fetch_calls) + 1)

        logger = logging.getLogger(self.LOGGER_NAME)
        with (
            caplog.at_level(logging.INFO, logger=self.LOGGER_NAME),
            pytest.raises(ReportGenerationError, match=r"6 automatic refetch attempts failed"),
        ):
            self._run_substitution(tmp_path, monkeypatch, _returns_none, logger)

        assert len(fetch_calls) == 6
        assert [d for kind, d in events if kind == "sleep"] == [1.0, 2.0, 4.0, 8.0, 16.0, 32.0]
        # Review r2 F7: match the production None-return anchor ("returned
        # none"), not the bare word "none"; pin the first/last backoff delays.
        none_warnings = [
            r
            for r in caplog.records
            if r.levelno == logging.WARNING and "returned none" in r.getMessage().lower()
        ]
        assert len(none_warnings) == 6, (
            f"expected 6 None-return WARNINGs, got: {[r.getMessage() for r in caplog.records]}"
        )
        assert "after 1.0 s backoff" in none_warnings[0].getMessage()
        assert "after 32.0 s backoff" in none_warnings[-1].getMessage()
        # No CSV rewrite (the None branch rewrites nothing).
        assert bera.read_text(encoding="utf-8") == content_before
        assert bera.stat().st_mtime == mtime_before

    def test_retry_ladder_path_return_but_still_stale_lets_refusal_decide(
        self, tmp_path, monkeypatch, caplog
    ) -> None:
        """Review r1 F3 (with the r1 F1 fix): a fetch that returns a Path but
        leaves the CSV stale (up-to-date short-circuit, partial write, clock
        skew) terminates the ladder after ONE attempt - a healthy refetch must
        not burn six attempts and be refuse-labelled "attempts failed" - and
        the REAL ``build_projection`` staleness refusal decides (r8-F2's
        outcome honesty; the message carries NO attempt count, r9-F1
        discriminability)."""
        events: list = []

        def _record_sleep(delay: float) -> None:
            events.append(("sleep", delay))

        monkeypatch.setattr(run_report_module, "_retry_sleep", _record_sleep)
        bera, marker = stale_marker_state(tmp_path, year=2025)
        fetch_calls: list[int] = []

        def _returns_stale_path(*, year: int, output_dir: Path) -> Path:
            fetch_calls.append(len(fetch_calls) + 1)
            return bera

        logger = logging.getLogger(self.LOGGER_NAME)
        with (
            caplog.at_level(logging.INFO, logger=self.LOGGER_NAME),
            pytest.raises(ReportGenerationError, match=r"fetch-failed") as excinfo,
        ):
            self._run_substitution(tmp_path, monkeypatch, _returns_stale_path, logger)

        message = str(excinfo.value)
        assert marker.name in message
        assert not re.search(r"\d+ automatic refetch attempts failed", message)
        # Review r2 F1: in THIS branch the terminal cause is the marker staying
        # newer (attempts neither failed nor were unavailable) - the refusal
        # message must enumerate it, not misdiagnose a fetch failure.
        assert "stayed newer" in message.lower(), (
            f"terminal-cause refusal must state the marker stayed newer; got: {message}"
        )
        assert len(fetch_calls) == 1, "a Path-returning attempt is terminal for the ladder"
        assert [d for kind, d in events if kind == "sleep"] == [1.0]
        assert any(
            r.levelno == logging.WARNING and "still newer" in r.getMessage()
            for r in caplog.records
        ), f"expected a still-stale WARNING, got: {[r.getMessage() for r in caplog.records]}"

    def test_retry_ladder_recovers_when_marker_deleted_mid_ladder(
        self, tmp_path, monkeypatch, caplog
    ) -> None:
        """Review r2 F4: the recovery check must ALSO fire after an attempt
        that RAISED (not only after a successful CSV rewrite): the user
        deletes the marker mid-ladder (the documented manual clear), the
        always-raising fetch never rewrites anything, and the predicate flip
        alone must end the ladder and proceed to the substitution. Guards
        against a regression moving the recovery check inside the
        success-only arm."""
        events: list = []

        def _record_sleep(delay: float) -> None:
            events.append(("sleep", delay))
            sleeps = [d for kind, d in events if kind == "sleep"]
            if len(sleeps) == 2:
                # Manual clear after the second sleep, before attempt 2.
                marker.unlink()

        monkeypatch.setattr(run_report_module, "_retry_sleep", _record_sleep)
        monkeypatch.setattr(run_report_module, "OnChainThSubstituter", _FakeSubstituter)
        _bera, marker = stale_marker_state(tmp_path, year=2025)
        fetch_calls: list[int] = []

        def _always_raises(*, year: int, output_dir: Path) -> Path:
            fetch_calls.append(len(fetch_calls) + 1)
            events.append(("fetch", len(fetch_calls)))
            raise RuntimeError("api down")

        logger = logging.getLogger(self.LOGGER_NAME)
        with caplog.at_level(logging.INFO, logger=self.LOGGER_NAME):
            reconciliation, override = self._run_substitution(
                tmp_path, monkeypatch, _always_raises, logger
            )

        # Exactly two attempts ran; the second attempt's predicate re-check
        # saw the cleared state and recovered.
        assert len(fetch_calls) == 2, f"expected 2 attempts, got: {fetch_calls}"
        assert events == [("sleep", 1.0), ("fetch", 1), ("sleep", 2.0), ("fetch", 2)]
        recovery_infos = [
            r.getMessage()
            for r in caplog.records
            if r.levelno == logging.INFO and "no longer newer" in r.getMessage()
        ]
        assert len(recovery_infos) == 1, (
            f"expected one recovery INFO naming the cleared condition, got: "
            f"{[r.getMessage() for r in caplog.records]}"
        )
        assert "manually cleared" in recovery_infos[0]
        # The substitution completed.
        assert len(_FakeSubstituter.calls) == 1
        assert reconciliation == "RECON"
        assert override == Path("on_chain_merged_th.csv")

    def test_run_report_staleness_ladder_end_to_end(
        self, empty_source: Path, tmp_path: Path, monkeypatch, caplog
    ) -> None:
        """Review r2 F8: one full ``run_report`` traversal - entry point ->
        Koinly stage -> opted-in gate -> retry ladder -> substitution - on a
        stale marker that recovers mid-ladder. The direct-drive ladder tests
        and the spy-based wiring test leave a structural bypass (e.g. a
        stage-level skip) invisible; this closes that loop (lesson #46)."""
        monkeypatch.setattr(run_report_module, "parse_ib_export_all", lambda _p: IBExportData({}, {}))
        (tmp_path / "2025" / "koinly").mkdir(parents=True)
        output_dir = tmp_path / "out"
        bera, marker = stale_marker_state(output_dir, year=2025)
        events: list = []

        def _record_sleep(delay: float) -> None:
            events.append(("sleep", delay))

        monkeypatch.setattr(run_report_module, "_retry_sleep", _record_sleep)
        monkeypatch.setattr(run_report_module, "OnChainThSubstituter", _FakeSubstituter)
        fetch_calls: list[int] = []

        def _flaky_fetch(*, year: int, output_dir: Path) -> Path:
            fetch_calls.append(len(fetch_calls) + 1)
            if len(fetch_calls) < 3:
                raise RuntimeError("quota exhausted")
            # Success: rewrite the CSV NEWER than the marker (landed self-heal).
            bera.write_text(_BERA_CSV_HEADER + "\n,recovered\n", encoding="utf-8")
            csv_new = marker.stat().st_mtime + 10
            os.utime(bera, (csv_new, csv_new))
            return bera

        with caplog.at_level(logging.INFO, logger=self.LOGGER_NAME):
            run_report(
                source_file=empty_source,
                output_dir=output_dir,
                app_config=Config(
                    base="EUR",
                    rates=[],
                    tax_jurisdiction=TaxJurisdictionConfig(
                        country="PT",
                        fiscal_year=2025,
                        exclude_loan_repayment_gains=False,
                        zero_basis_review_threshold=Decimal("50"),
                        on_chain_th_wallets=[_TEST_WALLET_LABEL],
                        timezone=ZoneInfo("Europe/Lisbon"),
                    ),
                    log_level="WARNING",
                ),
                on_chain_fetch=_flaky_fetch,
                logger=logging.getLogger(self.LOGGER_NAME),
            )

        # The run COMPLETED (the report artifact exists; the run was not
        # refused) and the ladder actually ran inside the full traversal
        # (three sleeps then recovery) with exactly one substitution.
        assert (output_dir / "extract.xlsx").exists(), (
            "the run must complete after the mid-ladder recovery"
        )
        assert [d for kind, d in events if kind == "sleep"] == [1.0, 2.0, 4.0]
        assert len(fetch_calls) == 4, (
            "3 ladder attempts plus the post-report collection-stage fetch"
        )
        assert len(_FakeSubstituter.calls) == 1, (
            "the full run must reach the on-chain TH substitution exactly once"
        )

    def test_run_report_exhaustion_refusal_not_double_wrapped(
        self, empty_source: Path, tmp_path: Path, monkeypatch, caplog
    ) -> None:
        """Review r4 F12: at the FULL ``run_report`` tier, the ladder's
        exhaustion refusal must surface WITHOUT the broad re-wrap's
        "Failed to generate report:" prefix (the carve-out ahead of the broad
        ``except Exception`` propagates ``ReportGenerationError`` verbatim,
        mirroring the ``ConfigurationError`` arm; M1 boundary)."""
        monkeypatch.setattr(run_report_module, "parse_ib_export_all", lambda _p: IBExportData({}, {}))
        (tmp_path / "2025" / "koinly").mkdir(parents=True)
        output_dir = tmp_path / "out"
        _bera, _marker = stale_marker_state(output_dir, year=2025)

        def _record_sleep(_delay: float) -> None:
            return None

        monkeypatch.setattr(run_report_module, "_retry_sleep", _record_sleep)

        def _always_fails(*, year: int, output_dir: Path) -> Path:
            raise RuntimeError("api down")

        with (
            caplog.at_level(logging.INFO, logger=self.LOGGER_NAME),
            pytest.raises(ReportGenerationError, match=r"6 automatic refetch attempts failed") as excinfo,
        ):
            run_report(
                source_file=empty_source,
                output_dir=output_dir,
                app_config=Config(
                    base="EUR",
                    rates=[],
                    tax_jurisdiction=_stale_on_chain_jurisdiction_with_tz(),
                    log_level="WARNING",
                ),
                on_chain_fetch=_always_fails,
                logger=logging.getLogger(self.LOGGER_NAME),
            )

        message = str(excinfo.value)
        assert "Failed to generate report:" not in message, (
            f"the refusal must surface verbatim, not double-wrapped; got: {message}"
        )
        assert message.startswith("Stale on-chain fetch data:"), (
            f"expected the ladder's own refusal text; got: {message}"
        )

    def test_non_staleness_report_generation_error_not_double_wrapped(
        self, empty_source: Path, tmp_path: Path, monkeypatch
    ) -> None:
        """Review r5 F1: the carve-out is WIDER than the staleness refusals -
        a non-staleness ``ReportGenerationError`` from the Koinly-stage block
        (here: a simulated Excel-save failure) also propagates verbatim,
        WITHOUT the broad re-wrap's "Failed to generate report:" prefix. This
        pins the widened contract as intentional."""
        monkeypatch.setattr(run_report_module, "parse_ib_export_all", lambda _p: IBExportData({}, {}))
        output_dir = tmp_path / "out"

        def _excel_save_fails(*_args, **_kwargs) -> None:
            raise ReportGenerationError("simulated Excel save failure")

        monkeypatch.setattr(run_report_module, "generate_tax_report", _excel_save_fails)

        with pytest.raises(ReportGenerationError, match=r"simulated Excel save failure") as excinfo:
            run_report(
                source_file=empty_source,
                output_dir=output_dir,
                app_config=_pt_config(),
                on_chain_fetch=None,
                logger=logging.getLogger(self.LOGGER_NAME),
            )

        message = str(excinfo.value)
        assert "Failed to generate report:" not in message, (
            f"a non-staleness ReportGenerationError must also surface verbatim; got: {message}"
        )
        assert message == "simulated Excel save failure", (
            f"expected the stage's own message unchanged; got: {message}"
        )

    def test_stale_marker_flag_off_never_enters_ladder(self, tmp_path, monkeypatch) -> None:
        """Backward-compat disabled state (r3 F1): empty ``on_chain_th_wallets``
        + a stale marker -> the wallets gate in ``_resolve_koinly_stage``
        keeps the run out of the ladder and the substitution entirely (zero
        sleeps, zero fetches, zero substitutions)."""
        self._patch_common(monkeypatch)
        stale_marker_state(tmp_path, year=2025)
        (tmp_path / "2025" / "koinly").mkdir(parents=True)
        jurisdiction = replace(_stale_on_chain_jurisdiction(), on_chain_th_wallets=[])

        def _must_not_run(**_kwargs) -> None:
            pytest.fail("flag-off runs must never sleep or fetch")

        stage = run_report_module._resolve_koinly_stage(
            koinly_base_dir=tmp_path,
            output_dir=tmp_path,
            tax_year_hint=2025,
            tax_jurisdiction=jurisdiction,
            logger=logging.getLogger(self.LOGGER_NAME),
            on_chain_fetch=_must_not_run,
        )

        assert stage.koinly_dir == (tmp_path / "2025" / "koinly"), (
            "the Koinly directory is still resolved; only the on-chain stage is off"
        )
        assert stage.on_chain_reconciliation is None
        assert stage.transaction_history_override is None

        # Review r5 F6: a fail-loud spy on the ladder entry point (mirroring
        # the fetch sentinel) instead of the vacuous ``events == []`` - the
        # events list is only ever appended inside the ladder this gate keeps
        # the run out of.
        def _must_not_enter_ladder(**_kwargs) -> None:
            pytest.fail("flag-off runs must never enter the retry ladder")

        monkeypatch.setattr(run_report_module, "retry_stale_on_chain_fetch", _must_not_enter_ladder)
        stage = run_report_module._resolve_koinly_stage(
            koinly_base_dir=tmp_path,
            output_dir=tmp_path,
            tax_year_hint=2025,
            tax_jurisdiction=jurisdiction,
            logger=logging.getLogger(self.LOGGER_NAME),
            on_chain_fetch=_must_not_run,
        )
        assert _FakeSubstituter.calls == []

    def test_on_chain_fetch_wiring_reaches_substitution(
        self, empty_source: Path, tmp_path: Path, monkeypatch, caplog
    ) -> None:
        """Review r1 F2: the injected fetch callable must survive BOTH
        hand-written pass-through hops (``run_report`` ->
        ``_resolve_koinly_stage`` -> ``_substitute_on_chain_th``); dropping the
        kwarg at either hop silently downgrades production to the no-callable
        immediate refusal while every direct-drive ladder test stays green
        (development_lessons.md #46: guard the production call site)."""
        monkeypatch.setattr(run_report_module, "parse_ib_export_all", lambda _p: IBExportData({}, {}))
        # Koinly directory in the new layout (<year>/koinly) so the opted-in
        # jurisdiction actually reaches the substitution stage.
        (tmp_path / "2025" / "koinly").mkdir(parents=True)
        seen: dict[str, object] = {}

        def _spy(*args, **kwargs):
            seen["fetch"] = kwargs["on_chain_fetch"] if "on_chain_fetch" in kwargs else args[5]
            return (None, None)

        monkeypatch.setattr(run_report_module, "_substitute_on_chain_th", _spy)

        def _sentinel_fetch(*, year: int, output_dir: Path) -> None:
            return None

        with caplog.at_level(logging.WARNING):
            run_report(
                source_file=empty_source,
                output_dir=tmp_path / "out",
                app_config=Config(
                    base="EUR",
                    rates=[],
                    tax_jurisdiction=TaxJurisdictionConfig(
                        country="PT",
                        fiscal_year=2025,
                        exclude_loan_repayment_gains=False,
                        zero_basis_review_threshold=Decimal("50"),
                        on_chain_th_wallets=[_TEST_WALLET_LABEL],
                        timezone=ZoneInfo("Europe/Lisbon"),
                    ),
                    log_level="WARNING",
                ),
                on_chain_fetch=_sentinel_fetch,
                logger=logging.getLogger(self.LOGGER_NAME),
            )

        assert seen.get("fetch") is _sentinel_fetch, (
            "run_report must thread its on_chain_fetch argument through "
            "_resolve_koinly_stage into _substitute_on_chain_th"
        )
