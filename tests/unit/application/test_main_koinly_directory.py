from __future__ import annotations

import logging

from shares_reporting.main import (
    _is_koinly_year_mismatch,
    _load_crypto_tax_report,
    _resolve_koinly_directory,
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

    monkeypatch.setattr("shares_reporting.main.load_koinly_crypto_report", _fake_loader)

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

    def _failing_loader(_path):
        raise ValueError("broken koinly file")

    monkeypatch.setattr("shares_reporting.main.load_koinly_crypto_report", _failing_loader)

    result = _load_crypto_tax_report(
        koinly_dir=koinly_dir,
        tax_year_hint=2025,
        logger=logging.getLogger("test_load_crypto_tax_report_handles_koinly_parse_error"),
    )

    assert result is None
