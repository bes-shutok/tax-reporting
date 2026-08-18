"""Koinly-directory discovery/selection behavior driven via ``run_report``.

Task 3 of the main-composition-root decomposition plan: the tests drive the
injectable orchestrator (``run_report``) with directly-constructed
``Config``/``TaxJurisdictionConfig`` objects and tmp_path Koinly layouts.
Collaborators with no injection seam (``parse_ib_export_all``,
``calculate_fifo_gains``, ``load_koinly_crypto_report``) are patched on
``tax_reporting.application.run_report``, the namespace the orchestrator calls
them through, per the plan's patching policy; nothing here patches the
composition-root module.

Config-LOADING behavior is not exercised here (these tests inject config
objects); loader-level cases live in ``test_main_composition_root.py``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from tax_reporting.application import run_report as run_report_module
from tax_reporting.application.run_report import run_report
from tax_reporting.domain.collections import IBExportData
from tax_reporting.domain.entities import QuantitatedTradeAction, TradeAction, TradeCycle
from tax_reporting.domain.value_objects import Company, Currency
from tax_reporting.infrastructure.config import Config, ConversionRate, TaxJurisdictionConfig

TEST_LOGGER_NAME = "test_main_koinly_directory"


def _pt_jurisdiction(fiscal_year: int = 2025, **overrides) -> TaxJurisdictionConfig:
    """A PT jurisdiction carrying a resolved timezone (Europe/Lisbon).

    Driving ``run_report`` with a Koinly directory present clears the STRICT
    localization guard inside ``_load_crypto_tax_report`` only when the timezone
    is resolved (PT auto-deduces Europe/Lisbon at config-file load; a
    directly-constructed object must pass it explicitly).
    """
    kwargs: dict = {
        "country": "PT",
        "fiscal_year": fiscal_year,
        "exclude_loan_repayment_gains": False,
        "zero_basis_review_threshold": Decimal("50"),
        "timezone": ZoneInfo("Europe/Lisbon"),
    }
    kwargs.update(overrides)
    return TaxJurisdictionConfig(**kwargs)


def _config(
    fiscal_year: int = 2025,
    jurisdiction: TaxJurisdictionConfig | None = None,
    rates: list[ConversionRate] | None = None,
) -> Config:
    return Config(
        base="EUR",
        rates=rates or [],
        tax_jurisdiction=jurisdiction if jurisdiction is not None else _pt_jurisdiction(fiscal_year),
        log_level="WARNING",
    )


def _ib_data_with_sold_year(year: int) -> IBExportData:
    """IB data whose sold trades infer ``year`` as the tax-year hint."""
    action = TradeAction(
        company=Company("ACME"),
        date_time=f"{year}-06-15, 12:00:00",
        currency=Currency("USD"),
        quantity="-1",
        price="100",
        fee="1",
    )
    cycle = TradeCycle()
    cycle.sold.append(QuantitatedTradeAction(Decimal("1"), action))
    return IBExportData({"ACME": cycle}, {})


def _run(  # noqa: PLR0913
    monkeypatch,
    tmp_path: Path,
    app_config: Config | None,
    ib_data: IBExportData,
    loader: Callable | None = None,
    caplog=None,
) -> Path:
    """Drive ``run_report`` with the IB parse/FIFO collaborators faked.

    The IB parse is faked to control the inferred tax-year hint deterministically;
    the FIFO calculation is a no-op so the synthetic hint-only trade cycle never
    reaches share-matching logic. Report generation, rollover export, and the
    crypto block (discovery, STRICT guard, loader dispatch) run for real.
    """
    source = tmp_path / "ib_export.csv"
    source.write_text("Statement,Header,Field Name,Field Value\n", encoding="utf-8")
    output_dir = tmp_path / "out"

    monkeypatch.setattr(run_report_module, "parse_ib_export_all", lambda _p: ib_data)
    monkeypatch.setattr(run_report_module, "calculate_fifo_gains", lambda *_args, **_kwargs: None)
    if loader is not None:
        monkeypatch.setattr(run_report_module, "load_koinly_crypto_report", loader)

    if caplog is not None:
        caplog.set_level(logging.INFO, logger=TEST_LOGGER_NAME)

    run_report(
        source_file=source,
        output_dir=output_dir,
        app_config=app_config,
        on_chain_fetch=None,
        logger=logging.getLogger(TEST_LOGGER_NAME),
    )
    return output_dir


def _detected_koinly_log(records: list[logging.LogRecord]) -> str | None:
    for record in records:
        if "Detected Koinly directory:" in record.message:
            return record.message.split("Detected Koinly directory: ", 1)[1]
    return None


def _noop_loader(_path, **_kwargs):
    return None


class TestKoinlyDirectoryDiscovery:
    def test_prefers_matching_year_hint(self, tmp_path, monkeypatch, caplog):
        """Legacy ``koinly<year>`` siblings resolve to the one matching the IB hint."""
        (tmp_path / "koinly2023").mkdir()
        (tmp_path / "koinly2024").mkdir()
        (tmp_path / "koinly2025").mkdir()

        _run(monkeypatch, tmp_path, _config(fiscal_year=2024), _ib_data_with_sold_year(2024),
             loader=_noop_loader, caplog=caplog)

        detected = _detected_koinly_log(caplog.records)
        assert detected is not None
        assert detected.endswith("koinly2024")

    def test_falls_back_to_latest_year_when_hint_matches_none(self, tmp_path, monkeypatch, caplog):
        """A hint matching no legacy sibling falls back to the latest directory.

        The latest-year fallback is observable end-to-end as: the latest dir is
        detected, then the year-mismatch guard skips crypto with the exact
        warning (the loader must not run on wrong-year data).
        """
        (tmp_path / "koinly2023").mkdir()
        (tmp_path / "koinly2025").mkdir()
        (tmp_path / "koinly2024").mkdir()
        called = False

        def _must_not_run(_path, **_kwargs):
            nonlocal called
            called = True

        # Hint 2022 matches no sibling -> legacy scan falls back to the latest.
        _run(monkeypatch, tmp_path, _config(fiscal_year=2022), _ib_data_with_sold_year(2022),
             loader=_must_not_run, caplog=caplog)

        detected = _detected_koinly_log(caplog.records)
        assert detected is not None
        assert detected.endswith("koinly2025")
        assert any(
            "Koinly directory year (2025) does not match inferred IB tax year (2022); "
            "skipping crypto data from:" in record.message
            for record in caplog.records
            if record.levelno == logging.WARNING
        )
        assert not called

    def test_year_mismatch_skips_crypto_with_exact_warning(self, tmp_path, monkeypatch, caplog):
        """Legacy layout: hint diverges from the detected directory year -> exact
        skip warning and the loader is never called."""
        (tmp_path / "koinly2024").mkdir()
        called = False

        def _must_not_run(_path, **_kwargs):
            nonlocal called
            called = True

        _run(monkeypatch, tmp_path, _config(fiscal_year=2025), _ib_data_with_sold_year(2025),
             loader=_must_not_run, caplog=caplog)

        assert any(
            "Koinly directory year (2024) does not match inferred IB tax year (2025); "
            "skipping crypto data from:" in record.message
            for record in caplog.records
            if record.levelno == logging.WARNING
        )
        assert not called

    def test_matching_year_loads_without_mismatch_warning(self, tmp_path, monkeypatch, caplog):
        """Legacy layout: detected year matches the hint -> no mismatch warning,
        loader called with the resolved directory."""
        (tmp_path / "koinly2024").mkdir()
        calls: list[Path] = []

        def _tracking_loader(path, **_kwargs):
            calls.append(path)

        _run(monkeypatch, tmp_path, _config(fiscal_year=2024), _ib_data_with_sold_year(2024),
             loader=_tracking_loader, caplog=caplog)

        assert not any(
            "does not match inferred IB tax year" in record.message
            for record in caplog.records
            if record.levelno == logging.WARNING
        )
        assert len(calls) == 1
        assert calls[0].name == "koinly2024"

    def test_year_mismatch_uses_parent_year_for_new_layout(self, tmp_path, monkeypatch, caplog):
        """The ``<year>/koinly`` layout has a bare ``koinly`` leaf, so mismatch
        detection falls back to the parent directory's year. Without this, a
        fiscal_year/IB-year divergence on the new layout would load wrong-year
        crypto data with no warning (removing the parent fallback leaves this RED)."""
        (tmp_path / "2024" / "koinly").mkdir(parents=True)
        called = False

        def _must_not_run(_path, **_kwargs):
            nonlocal called
            called = True

        # fiscal_year 2024 selects the 2024/koinly subdir; IB hint 2025 diverges.
        _run(monkeypatch, tmp_path, _config(fiscal_year=2024), _ib_data_with_sold_year(2025),
             loader=_must_not_run, caplog=caplog)

        assert any(
            "Koinly directory year (2024) does not match inferred IB tax year (2025); "
            "skipping crypto data from:" in record.message
            for record in caplog.records
            if record.levelno == logging.WARNING
        )
        assert not called

    def test_finds_year_subdir_layout(self, tmp_path, monkeypatch, caplog):
        """New personal-data layout: ``<base_dir>/<year>/koinly`` resolves by fiscal year.

        With no IB trades the fiscal-year fallback hint fires (exact INFO log)."""
        (tmp_path / "2025" / "koinly").mkdir(parents=True)

        _run(monkeypatch, tmp_path, _config(fiscal_year=2025), IBExportData({}, {}),
             loader=_noop_loader, caplog=caplog)

        detected = _detected_koinly_log(caplog.records)
        assert detected is not None
        assert detected.endswith(str(Path("2025") / "koinly"))
        assert any(
            "IB data has no current-year trades; using fiscal_year=2025 from config "
            "as Koinly year hint" in record.message
            for record in caplog.records
            if record.levelno == logging.INFO
        )

    def test_fiscal_year_drives_year_subdir(self, tmp_path, monkeypatch, caplog):
        """fiscal_year (config) selects the year subdir even when it differs from tax_year_hint.

        The fiscal year from config is the source of truth for which tax year is being
        filed; it must drive ``<year>/koinly`` resolution, not the IB-inferred hint.
        The IB-hint divergence then trips the mismatch skip (intended; see the
        year-mismatch repo rule)."""
        (tmp_path / "2025" / "koinly").mkdir(parents=True)
        (tmp_path / "2026" / "koinly").mkdir(parents=True)
        called = False

        def _must_not_run(_path, **_kwargs):
            nonlocal called
            called = True

        _run(monkeypatch, tmp_path, _config(fiscal_year=2025), _ib_data_with_sold_year(2026),
             loader=_must_not_run, caplog=caplog)

        detected = _detected_koinly_log(caplog.records)
        assert detected is not None
        assert detected.endswith(str(Path("2025") / "koinly"))
        assert any(
            "Koinly directory year (2025) does not match inferred IB tax year (2026); "
            "skipping crypto data from:" in record.message
            for record in caplog.records
            if record.levelno == logging.WARNING
        )
        assert not called

    def test_prefers_year_subdir_over_legacy_scan(self, tmp_path, monkeypatch, caplog):
        """The ``<year>/koinly`` layout wins over a legacy ``koinly<year>`` sibling."""
        (tmp_path / "2025" / "koinly").mkdir(parents=True)
        (tmp_path / "koinly2025").mkdir()  # legacy layout also present

        _run(monkeypatch, tmp_path, _config(fiscal_year=2025), _ib_data_with_sold_year(2025),
             loader=_noop_loader, caplog=caplog)

        detected = _detected_koinly_log(caplog.records)
        assert detected is not None
        assert detected.endswith(str(Path("2025") / "koinly"))

    def test_year_subdir_falls_back_to_hint_without_config_fiscal_year(self, tmp_path, monkeypatch, caplog):
        """Without a distinct fiscal-year signal, the (fiscal-backed) hint drives
        the ``<year>/koinly`` lookup."""
        (tmp_path / "2024" / "koinly").mkdir(parents=True)

        _run(monkeypatch, tmp_path, _config(fiscal_year=2024), _ib_data_with_sold_year(2024),
             loader=_noop_loader, caplog=caplog)

        detected = _detected_koinly_log(caplog.records)
        assert detected is not None
        assert detected.endswith(str(Path("2024") / "koinly"))

    def test_year_subdir_ignored_when_year_absent(self, tmp_path, monkeypatch, caplog):
        """A ``<year>/koinly`` for a non-matching year is not used; legacy scan takes over."""
        (tmp_path / "2024" / "koinly").mkdir(parents=True)
        (tmp_path / "koinly2025").mkdir()  # legacy fixture for the requested year
        calls: list[Path] = []

        def _tracking_loader(path, **_kwargs):
            calls.append(path)

        _run(monkeypatch, tmp_path, _config(fiscal_year=2025), _ib_data_with_sold_year(2025),
             loader=_tracking_loader, caplog=caplog)

        detected = _detected_koinly_log(caplog.records)
        assert detected is not None
        assert detected.endswith("koinly2025")
        # no mismatch: detected legacy year 2025 matches the hint -> loader runs
        assert len(calls) == 1
        assert calls[0].name == "koinly2025"

    def test_fiscal_year_fallback_prefers_fiscal_year_over_latest(self, tmp_path, monkeypatch, caplog):
        """fiscal_year-backed hint wins over a NEWER legacy directory; and when the
        hint matches no sibling, the latest-year fallback is selected (then skipped
        by the mismatch guard)."""
        (tmp_path / "koinly2024").mkdir()
        (tmp_path / "koinly2025").mkdir()

        _run(monkeypatch, tmp_path, _config(fiscal_year=2025), _ib_data_with_sold_year(2025),
             loader=_noop_loader, caplog=caplog)
        detected = _detected_koinly_log(caplog.records)
        assert detected is not None
        assert detected.endswith("koinly2025")

        # A newer directory exists; the fiscal-year hint still picks 2025.
        (tmp_path / "koinly2026").mkdir()
        caplog.clear()
        _run(monkeypatch, tmp_path, _config(fiscal_year=2025), _ib_data_with_sold_year(2025),
             loader=_noop_loader, caplog=caplog)
        detected = _detected_koinly_log(caplog.records)
        assert detected is not None
        assert detected.endswith("koinly2025")

        # Hint matching no sibling (2023) falls back to the latest (2026),
        # observable end-to-end as detection + mismatch skip.
        caplog.clear()
        called = False

        def _must_not_run(_path, **_kwargs):
            nonlocal called
            called = True

        _run(monkeypatch, tmp_path, _config(fiscal_year=2023), _ib_data_with_sold_year(2023),
             loader=_must_not_run, caplog=caplog)
        detected = _detected_koinly_log(caplog.records)
        assert detected is not None
        assert detected.endswith("koinly2026")
        assert any(
            "Koinly directory year (2026) does not match inferred IB tax year (2023); "
            "skipping crypto data from:" in record.message
            for record in caplog.records
            if record.levelno == logging.WARNING
        )
        assert not called


class TestCryptoLoadDegradeAndGuards:
    def test_handles_koinly_parse_error(self, tmp_path, monkeypatch, caplog):
        """A parse/data error from the loader degrades to "continue without crypto"."""
        (tmp_path / "koinly2025").mkdir()

        def _failing_loader(_path, **_kwargs):
            raise ValueError("broken koinly file")

        output_dir = _run(monkeypatch, tmp_path, _config(fiscal_year=2025),
                          _ib_data_with_sold_year(2025), loader=_failing_loader, caplog=caplog)

        # Degraded run still completes and writes the report.
        assert (output_dir / "extract.xlsx").exists()
        assert any(
            "Failed to load Koinly crypto dataset from" in record.message
            and "broken koinly file" in record.message
            and "Continuing without crypto data." in record.message
            for record in caplog.records
            if record.levelno == logging.ERROR
        )

    def test_propagates_configuration_error(self, tmp_path, monkeypatch):
        """A ConfigurationError raised by the loader must propagate, not be swallowed.

        ``run_report`` degrades parse/data errors to "continue without crypto"
        (see ``test_handles_koinly_parse_error``), but a ConfigurationError is a
        config problem that must fail the run (the discriminating pair).
        The STRICT guard at the top of the loader-dispatch helper raises BEFORE
        the try; this test additionally pins the defensive
        ``except ConfigurationError: raise`` clause so any future loader-side
        ConfigurationError is also propagated rather than silently swallowed.
        """
        from tax_reporting.domain.exceptions import ConfigurationError

        (tmp_path / "koinly2025").mkdir()

        def _config_error_loader(_path, **_kwargs):
            raise ConfigurationError("unresolved timezone")

        with pytest.raises(ConfigurationError, match="unresolved timezone"):
            _run(monkeypatch, tmp_path, _config(fiscal_year=2025),
                 _ib_data_with_sold_year(2025), loader=_config_error_loader)

    def test_fails_when_no_jurisdiction(self, tmp_path, monkeypatch):
        """STRICT: crypto present with no jurisdiction config fails fast, never silent UTC-stamp.

        With ``app_config=None`` the run reaches the crypto block with
        ``tax_jurisdiction=None``; the loader's no-zone path would then silently
        stamp naive CG/OGR/Income dates as UTC (the incorrect default this guard
        removes). The boundary raises ``ConfigurationError`` instead. The loader
        is faked to a sentinel that would FAIL the test if reached, proving the
        guard fires BEFORE the loader is called.
        """
        from tax_reporting.domain.exceptions import ConfigurationError

        (tmp_path / "koinly2025").mkdir()

        def _must_not_be_called(*_args, **_kwargs):
            raise AssertionError("STRICT guard must fail before the loader is called")

        with pytest.raises(ConfigurationError, match="no jurisdiction config"):
            _run(monkeypatch, tmp_path, None, _ib_data_with_sold_year(2025),
                 loader=_must_not_be_called)

    def test_fails_when_jurisdiction_timezone_unresolved(self, tmp_path, monkeypatch):
        """STRICT: a configured jurisdiction with no resolved timezone fails fast.

        A non-PT country without ``IANA_TIMEZONE`` resolves to ``timezone=None``
        at config load (PT auto-deduces ``Europe/Lisbon``). Crypto processing
        cannot localize naive dates without a zone; rather than silently
        stamping them as UTC, the boundary raises ``ConfigurationError`` naming
        ``IANA_TIMEZONE``. The loader is faked to a sentinel that would FAIL the
        test if reached, proving the guard fires BEFORE the loader is called.
        """
        from tax_reporting.domain.exceptions import ConfigurationError

        (tmp_path / "koinly2025").mkdir()

        def _must_not_be_called(*_args, **_kwargs):
            raise AssertionError("STRICT guard must fail before the loader is called")

        # Non-PT jurisdiction with no IANA_TIMEZONE: config leaves timezone None.
        jurisdiction = TaxJurisdictionConfig(
            country="DE",
            fiscal_year=2025,
            exclude_loan_repayment_gains=False,
            zero_basis_review_threshold=Decimal("50"),
        )

        with pytest.raises(ConfigurationError, match="IANA_TIMEZONE"):
            _run(monkeypatch, tmp_path, _config(jurisdiction=jurisdiction),
                 _ib_data_with_sold_year(2025), loader=_must_not_be_called)

    def test_passes_jurisdiction_to_loader(self, tmp_path, monkeypatch):
        """The injected config's jurisdiction is threaded to load_koinly_crypto_report."""
        (tmp_path / "koinly2025").mkdir()
        captured_kwargs: dict = {}

        def _capturing_loader(_path, **kwargs):
            captured_kwargs.update(kwargs)

        jurisdiction = _pt_jurisdiction(fiscal_year=2025, exclude_loan_repayment_gains=True)
        _run(monkeypatch, tmp_path, _config(jurisdiction=jurisdiction),
             _ib_data_with_sold_year(2025), loader=_capturing_loader)

        assert "jurisdiction" in captured_kwargs
        assert captured_kwargs["jurisdiction"] is jurisdiction

    def test_passes_rates_to_loader(self, tmp_path, monkeypatch):
        """The injected config's rates list is forwarded to load_koinly_crypto_report.

        Binds the inner-hop forward (Design Invariant 8 of DP-014): the pipeline
        MUST pass the config ``rates`` INTO the inner ``load_koinly_crypto_report``
        call. An implementer who threads the param through the orchestrator but
        leaves the inner call unchanged produces a plan-conformant result that
        silently drops ``rates`` (stays ``None``). Mirrors the jurisdiction
        discriminator above.
        """
        (tmp_path / "koinly2025").mkdir()
        captured_kwargs: dict = {}

        def _capturing_loader(_path, **kwargs):
            captured_kwargs.update(kwargs)

        rates = [ConversionRate(base="EUR", calculated="USD", rate=Decimal("0.90"))]
        _run(monkeypatch, tmp_path, _config(fiscal_year=2025, rates=rates),
             _ib_data_with_sold_year(2025), loader=_capturing_loader)

        assert "rates" in captured_kwargs, (
            "rates kwarg must be forwarded to load_koinly_crypto_report; "
            f"got captured_kwargs={captured_kwargs}"
        )
        assert captured_kwargs["rates"] is rates, (
            "The SAME rates list object from the injected config must reach "
            "load_koinly_crypto_report (inner-hop forward); got a different object."
        )
