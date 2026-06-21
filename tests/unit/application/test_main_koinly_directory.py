from __future__ import annotations

import logging

import pytest

from tax_reporting.main import (
    _is_koinly_year_mismatch,
    _load_crypto_tax_report,
    _resolve_koinly_directory,
)


def _pt_jurisdiction_with_timezone():
    """A PT/2025 jurisdiction carrying a resolved timezone (Europe/Lisbon).

    Helper-level tests that must reach the (monkeypatched) loader pass this so they
    clear the STRICT localization guard at the top of ``_load_crypto_tax_report``.
    See the STRICT RED tests below for the two failure cases this exists to bypass.
    """
    from decimal import Decimal
    from zoneinfo import ZoneInfo

    from tax_reporting.infrastructure.config import TaxJurisdictionConfig

    return TaxJurisdictionConfig(
        country="PT",
        fiscal_year=2025,
        exclude_loan_repayment_gains=False,
        zero_basis_review_threshold=Decimal("50"),
        timezone=ZoneInfo("Europe/Lisbon"),
    )


def test_resolve_koinly_directory_prefers_matching_year_hint(tmp_path):
    (tmp_path / "koinly2024").mkdir()
    (tmp_path / "koinly2025").mkdir()

    resolved = _resolve_koinly_directory(tmp_path, tax_year_hint=2024)

    assert resolved is not None
    assert resolved.name == "koinly2024"


def test_resolve_koinly_directory_falls_back_to_latest_year(tmp_path):
    (tmp_path / "koinly2023").mkdir()
    (tmp_path / "koinly2025").mkdir()
    (tmp_path / "koinly2024").mkdir()

    resolved = _resolve_koinly_directory(tmp_path, tax_year_hint=None)

    assert resolved is not None
    assert resolved.name == "koinly2025"


def test_is_koinly_year_mismatch_detects_fallback_year_mismatch(tmp_path):
    koinly_dir = tmp_path / "koinly2024"
    koinly_dir.mkdir()

    assert _is_koinly_year_mismatch(koinly_dir, tax_year_hint=2025)
    assert not _is_koinly_year_mismatch(koinly_dir, tax_year_hint=2024)


def test_load_crypto_tax_report_skips_year_mismatch(tmp_path, monkeypatch):
    koinly_dir = tmp_path / "koinly2024"
    koinly_dir.mkdir()
    called = False

    def _fake_loader(_path):
        nonlocal called
        called = True

    monkeypatch.setattr("tax_reporting.main.load_koinly_crypto_report", _fake_loader)

    result = _load_crypto_tax_report(
        koinly_dir=koinly_dir,
        tax_year_hint=2025,
        logger=logging.getLogger("test_load_crypto_tax_report_skips_year_mismatch"),
    )

    assert result is None
    assert not called


def test_load_crypto_tax_report_handles_koinly_parse_error(tmp_path, monkeypatch):
    koinly_dir = tmp_path / "koinly2025"
    koinly_dir.mkdir()

    def _failing_loader(_path, **_kwargs):
        raise ValueError("broken koinly file")

    monkeypatch.setattr("tax_reporting.main.load_koinly_crypto_report", _failing_loader)

    result = _load_crypto_tax_report(
        koinly_dir=koinly_dir,
        tax_year_hint=2025,
        tax_jurisdiction=_pt_jurisdiction_with_timezone(),
        logger=logging.getLogger("test_load_crypto_tax_report_handles_koinly_parse_error"),
    )

    assert result is None


def test_load_crypto_tax_report_propagates_configuration_error(tmp_path, monkeypatch):
    """A ConfigurationError raised by the loader must propagate, not be swallowed.

    ``_load_crypto_tax_report`` degrades parse/data errors to "continue without
    crypto" (returns None), but a ConfigurationError is a config problem that must
    fail the run. The STRICT guard at the top of the helper raises BEFORE the try;
    this test additionally pins the defensive ``except ConfigurationError: raise``
    clause so any future loader-side ConfigurationError is also propagated rather
    than silently swallowed. A valid PT jurisdiction is passed so the STRICT guard
    is cleared and the monkeypatched loader is reached.
    Contrast with ``test_load_crypto_tax_report_handles_koinly_parse_error`` above,
    which confirms a plain ValueError IS swallowed (the discriminating pair).
    """
    from tax_reporting.domain.exceptions import ConfigurationError

    koinly_dir = tmp_path / "koinly2025"
    koinly_dir.mkdir()

    def _config_error_loader(_path, **_kwargs):
        raise ConfigurationError("unresolved timezone")

    monkeypatch.setattr("tax_reporting.main.load_koinly_crypto_report", _config_error_loader)

    with pytest.raises(ConfigurationError, match="unresolved timezone"):
        _load_crypto_tax_report(
            koinly_dir=koinly_dir,
            tax_year_hint=2025,
            tax_jurisdiction=_pt_jurisdiction_with_timezone(),
            logger=logging.getLogger("test_propagates_configuration_error"),
        )


def test_load_crypto_tax_report_fails_when_no_jurisdiction(tmp_path, monkeypatch):
    """STRICT: crypto present with no jurisdiction config fails fast, never silent UTC-stamp.

    When ``config.ini`` is absent/unreadable the orchestration in ``main.py`` runs the
    crypto pipeline with ``tax_jurisdiction=None``. The loader's no-zone path would
    then silently stamp naive CG/OGR/Income dates as UTC (the incorrect default this
    guard removes). ``_load_crypto_tax_report`` must raise ``ConfigurationError`` at
    the application boundary instead. The loader is monkeypatched to a sentinel that
    would FAIL the test if reached, proving the guard fires BEFORE the loader is called.
    """
    from tax_reporting.domain.exceptions import ConfigurationError

    koinly_dir = tmp_path / "koinly2025"
    koinly_dir.mkdir()

    def _must_not_be_called(*_args, **_kwargs):
        raise AssertionError("STRICT guard must fail before the loader is called")

    monkeypatch.setattr("tax_reporting.main.load_koinly_crypto_report", _must_not_be_called)

    with pytest.raises(ConfigurationError, match="no jurisdiction config"):
        _load_crypto_tax_report(
            koinly_dir=koinly_dir,
            tax_year_hint=2025,
            tax_jurisdiction=None,
            logger=logging.getLogger("test_fails_when_no_jurisdiction"),
        )


def test_load_crypto_tax_report_fails_when_jurisdiction_timezone_unresolved(tmp_path, monkeypatch):
    """STRICT: a configured jurisdiction with no resolved timezone fails fast.

    A non-PT country without ``IANA_TIMEZONE`` resolves to ``timezone=None`` at config
    load (PT auto-deduces ``Europe/Lisbon``). Crypto processing cannot localize naive
    dates without a zone; rather than silently stamping them as UTC,
    ``_load_crypto_tax_report`` raises ``ConfigurationError`` naming ``IANA_TIMEZONE``.
    The loader is monkeypatched to a sentinel that would FAIL the test if reached,
    proving the guard fires BEFORE the loader is called.
    """
    from decimal import Decimal

    from tax_reporting.domain.exceptions import ConfigurationError
    from tax_reporting.infrastructure.config import TaxJurisdictionConfig

    koinly_dir = tmp_path / "koinly2025"
    koinly_dir.mkdir()

    def _must_not_be_called(*_args, **_kwargs):
        raise AssertionError("STRICT guard must fail before the loader is called")

    monkeypatch.setattr("tax_reporting.main.load_koinly_crypto_report", _must_not_be_called)

    # Non-PT jurisdiction with no IANA_TIMEZONE: config leaves timezone None.
    jurisdiction = TaxJurisdictionConfig(
        country="DE",
        fiscal_year=2025,
        exclude_loan_repayment_gains=False,
        zero_basis_review_threshold=Decimal("50"),
    )

    with pytest.raises(ConfigurationError, match="IANA_TIMEZONE"):
        _load_crypto_tax_report(
            koinly_dir=koinly_dir,
            tax_year_hint=2025,
            tax_jurisdiction=jurisdiction,
            logger=logging.getLogger("test_fails_when_timezone_unresolved"),
        )


def test_load_crypto_tax_report_passes_jurisdiction_to_loader(tmp_path, monkeypatch):
    """Verify jurisdiction config is threaded through to load_koinly_crypto_report."""
    from decimal import Decimal
    from zoneinfo import ZoneInfo

    from tax_reporting.infrastructure.config import TaxJurisdictionConfig

    koinly_dir = tmp_path / "koinly2025"
    koinly_dir.mkdir()
    captured_kwargs = {}

    def _capturing_loader(_path, **kwargs):
        captured_kwargs.update(kwargs)

    monkeypatch.setattr("tax_reporting.main.load_koinly_crypto_report", _capturing_loader)

    jurisdiction = TaxJurisdictionConfig(
        country="PT",
        fiscal_year=2025,
        exclude_loan_repayment_gains=True,
        zero_basis_review_threshold=Decimal("50"),
        timezone=ZoneInfo("Europe/Lisbon"),
    )
    _load_crypto_tax_report(
        koinly_dir=koinly_dir,
        tax_year_hint=2025,
        tax_jurisdiction=jurisdiction,
        logger=logging.getLogger("test_passes_jurisdiction"),
    )

    assert "jurisdiction" in captured_kwargs
    assert captured_kwargs["jurisdiction"] is jurisdiction


def test_load_crypto_tax_report_passes_rates_to_loader(tmp_path, monkeypatch):
    """Verify the threaded rates list is forwarded to load_koinly_crypto_report.

    Binds the inner-hop forward (Design Invariant 8 of DP-014): ``_load_crypto_tax_report``
    MUST pass its ``rates`` kwarg INTO the inner ``load_koinly_crypto_report`` call. An
    implementer who adds the param to both signatures but leaves the inner call
    unchanged produces a plan-conformant result that passes the config-missing RED
    test yet silently drops ``rates`` (stays ``None``). Mirrors the existing
    ``test_load_crypto_tax_report_passes_jurisdiction_to_loader`` discriminator.
    """
    from tax_reporting.infrastructure.config import ConversionRate

    koinly_dir = tmp_path / "koinly2025"
    koinly_dir.mkdir()
    captured_kwargs = {}

    def _capturing_loader(_path, **kwargs):
        captured_kwargs.update(kwargs)

    monkeypatch.setattr("tax_reporting.main.load_koinly_crypto_report", _capturing_loader)

    rates = [ConversionRate(base="EUR", calculated="USD", rate=__import__("decimal").Decimal("0.90"))]
    _load_crypto_tax_report(
        koinly_dir=koinly_dir,
        tax_year_hint=2025,
        tax_jurisdiction=_pt_jurisdiction_with_timezone(),
        logger=logging.getLogger("test_passes_rates"),
        rates=rates,
    )

    assert "rates" in captured_kwargs, (
        "rates kwarg must be forwarded to load_koinly_crypto_report; "
        f"got captured_kwargs={captured_kwargs}"
    )
    assert captured_kwargs["rates"] is rates, (
        "The SAME rates list object passed into _load_crypto_tax_report must reach "
        "load_koinly_crypto_report (inner-hop forward); got a different object."
    )


def test_resolve_koinly_directory_fiscal_year_fallback_via_main(tmp_path, monkeypatch):
    """When IB data has no year hint, fiscal_year from config is used as fallback."""
    (tmp_path / "koinly2024").mkdir()
    (tmp_path / "koinly2025").mkdir()

    # Directly test _resolve_koinly_directory with the fiscal_year as hint
    resolved = _resolve_koinly_directory(tmp_path, tax_year_hint=2025)
    assert resolved is not None
    assert resolved.name == "koinly2025"

    # Without a hint, would fall back to latest (also 2025 in this case).
    # Real value is when there's a newer directory than the fiscal year:
    (tmp_path / "koinly2026").mkdir()
    resolved_no_hint = _resolve_koinly_directory(tmp_path, tax_year_hint=None)
    assert resolved_no_hint is not None
    assert resolved_no_hint.name == "koinly2026"

    # With fiscal_year=2025, correctly picks 2025 even when 2026 exists
    resolved_with_hint = _resolve_koinly_directory(tmp_path, tax_year_hint=2025)
    assert resolved_with_hint is not None
    assert resolved_with_hint.name == "koinly2025"
