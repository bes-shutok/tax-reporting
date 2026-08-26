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
import pkgutil
from decimal import Decimal
from pathlib import Path

import pytest

from tax_reporting.application import run_report as run_report_module
from tax_reporting.application.run_report import run_report
from tax_reporting.domain.collections import IBExportData
from tax_reporting.infrastructure.config import Config, TaxJurisdictionConfig


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
