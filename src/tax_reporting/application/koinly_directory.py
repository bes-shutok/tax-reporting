"""Koinly directory discovery and year detection.

Extracted from ``application/run_report.py`` for module-size headroom. Patch
seam: patch only ``_resolve_koinly_directory`` on
``tax_reporting.application.run_report`` (the calling namespace); this module's
own helpers are called through that import, so patching them here does not
affect the orchestrator.
"""

from __future__ import annotations

import re
from pathlib import Path


def _extract_year(value: str) -> int | None:
    match = re.search(r"(?<!\d)(\d{4})(?!\d)", value)
    if not match:
        return None
    return int(match.group(1))


def _detected_koinly_year(koinly_dir: Path) -> int | None:
    # The legacy layout embeds the year in the directory name (``koinly2025``).
    # The newer ``<year>/koinly`` layout has a bare ``koinly`` leaf, so fall back
    # to the parent directory's year when the leaf carries none. Without this,
    # a fiscal_year/IB-year divergence on the new layout would load wrong-year
    # crypto data with no mismatch warning.
    detected_year = _extract_year(koinly_dir.name)
    if detected_year is None:
        detected_year = _extract_year(koinly_dir.parent.name)
    return detected_year


def _is_koinly_year_mismatch(koinly_dir: Path, tax_year_hint: int | None) -> bool:
    # A None hint is only reachable without config, which fails fast before any Koinly
    # row loads, so this branch cannot let wrong-year data through.
    if tax_year_hint is None:
        return False
    detected_year = _detected_koinly_year(koinly_dir)
    return detected_year is not None and detected_year != tax_year_hint


def _resolve_koinly_directory(base_dir: Path, tax_year_hint: int | None, fiscal_year: int | None = None) -> Path | None:
    # New personal-data layout: ``<base_dir>/<year>/koinly`` (e.g.
    # ``resources/source/2025/koinly``), where ``<year>`` is the configured fiscal
    # year. The fiscal_year from config is preferred (the source of truth for which
    # tax year is being filed); fall back to the IB-inferred tax_year_hint.
    # Note: selecting the directory by fiscal_year does NOT bypass the year-mismatch
    # guard in _load_crypto_tax_report, which compares the directory's detected year
    # against the IB-inferred tax_year_hint and skips crypto on divergence. That is
    # intentional (see the repo rule on Koinly year mismatch): if the IB export's
    # year disagrees with the configured fiscal_year, loading crypto is unsafe, so
    # the run skips it with a warning rather than risk wrong-year data.
    year = fiscal_year if fiscal_year is not None else tax_year_hint
    if year is not None:
        year_subdir = base_dir / str(year) / "koinly"
        if year_subdir.is_dir():
            return year_subdir

    # Legacy personal layout fallback: ``base_dir`` itself is a ``koinly<year>`` dir.
    # Modern layouts (real data and committed synthetic fixtures) resolve via the
    # ``<year>/koinly`` subdir lookup above; this glob only catches the legacy flat form.
    candidates = [path for path in base_dir.iterdir() if path.is_dir() and path.name.lower().startswith("koinly")]
    if not candidates:
        return None

    if tax_year_hint is not None:
        for candidate in candidates:
            if _extract_year(candidate.name) == tax_year_hint:
                return candidate

    return max(candidates, key=lambda path: (_extract_year(path.name) or -1, path.name.lower()))
