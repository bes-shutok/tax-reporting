"""Shared plain-helper fixtures for the on-chain staleness tests (review r2 F10).

These are PLAIN FUNCTIONS (not pytest fixtures; the repo forbids importing
pytest fixtures across modules). Shared by
``test_on_chain_th_substitution.py`` and ``test_run_report.py`` so the two
modules' stale-state construction and marker-vanishes TOCTOU patches cannot
drift apart.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from tax_reporting.application.on_chain_fetcher import fetch_failed_marker_path

#: The FULL 15-column bera CSV header the reader's ``OnChainTxRow`` contract
#: requires (missing columns make the reader warn-and-skip every data row).
BERA_CSV_HEADER = (
    "tx_hash,block_number,timestamp_utc,chain,from_address,to_address,"
    "asset,token_address,amount_raw,amount_decimals,direction,fee_asset,"
    "fee_amount_raw,wallet_label,wallet_address"
)


def backdate(path: Path, seconds_ago: float) -> None:
    """Set a file's atime/mtime to ``now - seconds_ago`` (mtime control)."""
    t = time.time() - seconds_ago
    os.utime(path, (t, t))


def stale_marker_state(
    output_dir: Path, year: int = 2025, data_rows: list[str] | None = None
) -> tuple[Path, Path]:
    """Create the known-stale state under ``output_dir``: a bera CSV (header
    plus optional ``data_rows``) backdated one hour plus a ``.fetch-failed``
    marker written NOW (marker mtime newer).

    Returns ``(bera_csv, marker)``. ``output_dir`` MUST be a tmp_path so the
    audit guard never sees a forbidden personal-data path open.
    """
    bera = output_dir / str(year) / "bera_transactions.csv"
    bera.parent.mkdir(parents=True, exist_ok=True)
    rows = data_rows if data_rows is not None else []
    bera.write_text("\n".join([BERA_CSV_HEADER, *rows, ""]), encoding="utf-8")
    backdate(bera, seconds_ago=3600)
    marker = fetch_failed_marker_path(output_dir, year)
    marker.write_text("On-chain fetch failed: simulated\n", encoding="utf-8")
    return bera, marker


def patch_marker_vanishes(monkeypatch, marker: Path) -> None:
    """Patch ``Path.is_file``/``Path.stat`` so ``marker`` vanishes mid-check.

    The TOCTOU pair used by both the predicate unit test and the
    ``build_projection`` race test: ``is_file`` returns True for the marker
    while ``stat`` raises ``FileNotFoundError`` (deleted between the two
    calls). BOTH patches are scoped to the marker path ONLY - a class-wide
    ``Path.stat`` patch breaks ``find_repository_root()`` and later path
    checks (r5-F1).
    """
    real_is_file = Path.is_file
    real_stat = Path.stat

    def is_file_true_for_marker(self: Path) -> bool:
        if self == marker:
            return True
        return real_is_file(self)

    def stat_vanishes_for_marker(self: Path, *args, **kwargs):
        if self == marker:
            raise FileNotFoundError("marker deleted between is_file() and stat()")
        return real_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "is_file", is_file_true_for_marker)
    monkeypatch.setattr(Path, "stat", stat_vanishes_for_marker)
