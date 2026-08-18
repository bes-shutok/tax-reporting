"""On-chain fetch wiring tests for the injectable ``run_report`` orchestrator.

Retargeted (Task 4) from the old composition-root monkeypatch pattern to plain
injected fetch callables: ``run_report`` receives ``on_chain_fetch`` as a
parameter (``None`` means skip), so these tests need NO patching of the
composition-root module at all, and no env-var tricks. The env-var gate itself
(the single legitimate env seam) is pinned separately in
``tests/unit/application/test_main_composition_root.py``.

Pinned wiring properties:

- **Injected fetch, keyword invocation:** the orchestrator calls
  ``on_chain_fetch(year=..., output_dir=...)`` (keyword-only contract of the
  real fetcher, whose ``api_key`` is bound at the composition root via a
  partial and therefore never appears in these calls).
- **Skip via None (DI-3 policy):** ``on_chain_fetch=None`` means "skip the
  on-chain fetch"; no fetch attempt, no fetch failure log, the report still
  generates.
- **Year-resolved defensively (DI-9):** ``on_chain_year`` falls back to the
  IB-inferred ``tax_year_hint`` when the jurisdiction is None, so a future
  relaxation of the upstream STRICT jurisdiction guard cannot raise
  ``AttributeError``.
- **Non-blocking (r1 F1):** the wiring catch is ``except Exception`` (broad),
  mirroring the optional-Koinly degrade template. Any exception from the
  fetcher (``FileProcessingError``, ``urllib.error.URLError``,
  ``json.JSONDecodeError``, plain ``Exception``) is logged as a WARNING and
  swallowed; the IB/Koinly report still generates. The fetcher never aborts
  the crypto/IB pipeline.
- **DI-6 single-WARNING ownership:** the REAL fetch orchestrator (injected as
  a partial, exactly as the composition root binds it) owns the single
  "No chains.json" WARNING when the wallet config is empty.

The tests run ``run_report`` end-to-end against the committed example data
(``resources/source/example/ib_export.csv``) so ``extract.xlsx`` actually
generates. Logging assertions use ``caplog`` (the orchestrator does not
reconfigure the root logger). The only patch is the owning-module wallet
loader (a collaborator without an injection seam) plus, for the
no-jurisdiction test, the Koinly directory resolver, so no network or
real-config dependency leaks in.
"""

from __future__ import annotations

import functools
import io
import json
import logging
import urllib.error
import zipfile
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from tax_reporting.application.on_chain_fetcher import run_on_chain_fetch
from tax_reporting.application.run_report import run_report

# Repo root (resolved relative to this test file:
# tests/unit/application/test_main_on_chain_wiring.py -> parents[3] = repo root).
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_EXAMPLE_SOURCE = _PROJECT_ROOT / "resources" / "source" / "example" / "ib_export.csv"

_LOGGER = logging.getLogger("test_main_on_chain_wiring")


def _pt_2025_config():
    """A Config carrying a PT/2025 jurisdiction with a resolved timezone."""
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


def _recording_fetch(calls: list[dict], *, return_value: Path | None = None, exc: BaseException | None = None):
    """Build a plain injected fetch callable recording ``{year, output_dir}`` per call.

    Mirrors the keyword-only invocation contract
    (``on_chain_fetch(year=..., output_dir=...)``). Optionally raises ``exc``
    after recording, or returns ``return_value``.
    """

    def _fetch(*, year: int, output_dir: Path) -> Path | None:
        calls.append({"year": year, "output_dir": output_dir})
        if exc is not None:
            raise exc
        return return_value

    return _fetch


@pytest.fixture()
def example_run(tmp_path):
    """Return a helper that runs ``run_report`` against the committed example data.

    The helper accepts the injected fetch callable and the ``app_config`` to
    pass, runs the orchestrator to completion with a real logger, and returns
    the expected ``extract.xlsx`` path. ``resolve_koinly_none`` forces the
    Koinly directory resolver to return None so the crypto block skips cleanly
    (used by the no-jurisdiction test to reach the on-chain wiring without
    tripping the STRICT guard).
    """
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    extract_path = out_dir / "extract.xlsx"

    import contextlib

    def run(*, on_chain_fetch, config, resolve_koinly_none: bool = False):
        with contextlib.ExitStack() as stack:
            if resolve_koinly_none:
                stack.enter_context(
                    patch(
                        "tax_reporting.application.run_report._resolve_koinly_directory",
                        return_value=None,
                    )
                )
            run_report(
                source_file=_EXAMPLE_SOURCE,
                output_dir=out_dir,
                app_config=config,
                on_chain_fetch=on_chain_fetch,
                logger=_LOGGER,
            )
        return extract_path

    return run


# Fixed zip entry timestamp used by _normalized_xlsx(). 1980-01-01 is the
# earliest representable MS-DOS zip timestamp, so it can never collide with a
# real wall-clock save time.
_FIXED_ZIP_DATE_TIME = (1980, 1, 1, 0, 0, 0)

# Content-level timestamps embedded in docProps/core.xml (<dcterms:created> and
# <dcterms:modified>, sourced from wb.properties.created which defaults to
# wall-clock now) are NOT part of the equality under test: the invariant is
# that the report CONTENT is unaffected by the on-chain fetch, not that the
# workbook metadata timestamps match. Exclude that entry from the normalized
# comparison rather than rewriting its XML.
_CORE_PROPERTIES_ENTRY = "docProps/core.xml"


def _normalized_xlsx(xlsx_path: Path) -> bytes:
    """Return a timestamp-insensitive canonical byte form of an xlsx file.

    openpyxl output embeds wall-clock timestamps two ways: (1) each zip entry's
    ``date_time`` field, and (2) ``docProps/core.xml`` content via
    ``wb.properties.created`` (defaults to now). When two saves straddle a
    wall-clock second boundary the raw bytes differ nondeterministically. This
    helper rewrites every entry into a fresh in-memory zip with a fixed entry
    timestamp, sorted entry order, and fixed compression, excluding the
    core-properties entry (content-level timestamps, see
    ``_CORE_PROPERTIES_ENTRY``), so equal workbook content yields equal bytes.
    """
    normalized = io.BytesIO()
    with zipfile.ZipFile(xlsx_path, "r") as src, zipfile.ZipFile(
        normalized, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
    ) as dst:
        for info in sorted(src.infolist(), key=lambda i: i.filename):
            if info.filename == _CORE_PROPERTIES_ENTRY:
                continue
            dst.writestr(
                zipfile.ZipInfo(info.filename, date_time=_FIXED_ZIP_DATE_TIME),
                src.read(info.filename),
                compress_type=zipfile.ZIP_DEFLATED,
                compresslevel=6,
            )
    return normalized.getvalue()


@pytest.mark.unit
class TestRunReportOnChainWiring:
    """Pin the injected on-chain fetch wiring in ``run_report`` (Task 4 retarget)."""

    def test_fetch_not_invoked_when_none_injected(self, example_run, caplog):
        """Skip policy: ``on_chain_fetch=None`` -> no fetch attempt, no failure log, report generates."""
        with caplog.at_level(logging.WARNING):
            extract_path = example_run(on_chain_fetch=None, config=_pt_2025_config())

        assert extract_path.exists(), "extract.xlsx must still generate"
        assert not any("On-chain fetch failed" in r.message for r in caplog.records), (
            "no fetch failure WARNING may fire when the fetch is skipped"
        )

    def test_skips_when_config_absent(self, example_run, monkeypatch, caplog):
        """Config-absent: loader returns [] silently; orchestrator WARNING fires ONCE (DI-6).

        The REAL fetch orchestrator is injected as a partial (exactly as the
        composition root binds it when the env var is set); the wallet loader
        returns [] (no chains.json for the year). The orchestrator returns None
        on empty wallets before any network and owns the SINGLE WARNING; the
        loader stays silent. extract.xlsx generates. This guards the r1 F5
        double-WARNING regression: assert EXACTLY one WARNING record for the
        config-absent condition.
        """
        monkeypatch.setattr(
            "tax_reporting.application.on_chain_fetcher.load_on_chain_wallets",
            lambda _year, **_kw: [],
        )
        fetcher = functools.partial(run_on_chain_fetch, api_key="some-key")

        with caplog.at_level(logging.WARNING):
            extract_path = example_run(on_chain_fetch=fetcher, config=_pt_2025_config())

        assert extract_path.exists()
        count = sum(
            1
            for r in caplog.records
            if r.levelno == logging.WARNING and "No chains.json for year" in r.message
        )
        assert count == 1, (
            "exactly ONE WARNING for the config-absent condition (DI-6 single-WARNING "
            f"ownership); got {count} occurrence(s)"
        )

    def test_skips_when_no_jurisdiction(self, example_run, caplog):
        """No jurisdiction + config reachable -> no AttributeError (DI-9).

        Defends against the upstream STRICT jurisdiction guard being relaxed:
        with ``tax_jurisdiction=None`` and the Koinly directory forced to be
        absent (so the crypto STRICT guard does not fire), the year must
        resolve defensively (to ``tax_year_hint``) and the run must not raise
        ``AttributeError``. The fetcher IS reached and is called once with the
        defensively-resolved year (NOT a None that would crash).
        """
        calls: list[dict] = []
        with caplog.at_level(logging.WARNING):
            extract_path = example_run(
                on_chain_fetch=_recording_fetch(calls, return_value=Path("/fake/bera_transactions.csv")),
                config=_no_jurisdiction_config(),
                resolve_koinly_none=True,  # skip crypto STRICT guard, reach the wiring
            )

        assert len(calls) == 1, "fetcher reached once with the defensively-resolved year"
        assert calls[0]["year"] is not None
        assert extract_path.exists()

    def test_runs_when_fetch_injected(self, example_run, caplog):
        """Injected fetch present -> called once with the fiscal year + validated output dir (DI-9)."""
        # Raw-kwargs double: the dict under assertion is built from the
        # orchestrator's actual call, so the set equality below is discriminating.
        calls: list[dict] = []

        def _fetch(**kwargs):
            calls.append(kwargs)
            return Path("/fake/bera_transactions.csv")

        with caplog.at_level(logging.WARNING):
            extract_path = example_run(
                on_chain_fetch=_fetch,
                config=_pt_2025_config(),
            )

        assert len(calls) == 1, "fetcher must be called exactly once"
        call = calls[0]
        assert call["year"] == 2025, (
            "year must be resolved defensively from the jurisdiction fiscal_year (DI-9)"
        )
        # output_dir is the validated absolute output dir for the run.
        assert call["output_dir"].name == extract_path.parent.name
        # The injected call carries ONLY (year, output_dir): the api_key is
        # bound at the composition root (partial), never re-sent by the orchestrator.
        assert set(call) == {"year", "output_dir"}
        assert extract_path.exists(), "extract.xlsx must still generate"

    def test_fetch_failure_non_fileprocessingerror_is_non_blocking(self, example_run, caplog):
        """r1 F1 guard: a URLError from the fetcher is swallowed (broad except), report still generates."""
        calls: list[dict] = []
        with caplog.at_level(logging.WARNING):
            extract_path = example_run(
                on_chain_fetch=_recording_fetch(calls, exc=urllib.error.URLError("boom")),
                config=_pt_2025_config(),
            )

        assert extract_path.exists(), "extract.xlsx must generate despite the fetch failure"
        assert len(calls) == 1, "fetcher must have been invoked"
        assert any(
            "Continuing without on-chain transaction data" in r.message
            for r in caplog.records
            if r.levelno == logging.WARNING
        ), "a WARNING containing 'Continuing without on-chain transaction data' must fire"

    @pytest.mark.parametrize(
        "exc",
        [
            urllib.error.URLError("boom"),
            json.JSONDecodeError("Expecting value", "<doc>", 0),
            RuntimeError("plain exception"),
        ],
        ids=["URLError", "JSONDecodeError", "Exception"],
    )
    def test_fetch_failure_parametrized_is_non_blocking(self, exc, example_run, caplog):
        """Parametrized r1 F1 guard: URLError, JSONDecodeError, plain Exception are all non-blocking."""
        calls: list[dict] = []
        try:
            with caplog.at_level(logging.WARNING):
                extract_path = example_run(
                    on_chain_fetch=_recording_fetch(calls, exc=exc),
                    config=_pt_2025_config(),
                )
        except Exception as escaped:  # noqa: BLE001
            pytest.fail(f"broad except must swallow the exception, not let {escaped!r} escape")

        assert extract_path.exists(), "extract.xlsx must generate despite the fetch failure"
        assert any(
            "Continuing without on-chain transaction data" in r.message
            for r in caplog.records
            if r.levelno == logging.WARNING
        ), "a WARNING containing 'Continuing without on-chain transaction data' must fire"

    def test_extract_report_unaffected_by_fetch(self, example_run):
        """Frozen-pipeline invariant: the fetcher never touches the IB/Koinly extract content.

        Runs the full happy path twice against the same example data: once
        with the fetcher returning a fake Path, once with the fetch skipped
        (None injected). The generated ``extract.xlsx`` is byte-identical
        between the two runs, proving the on-chain step is a read-only
        parallel collection that never mutates the report.
        """
        out_a = example_run(
            on_chain_fetch=_recording_fetch([], return_value=Path("/fake/bera_transactions.csv")),
            config=_pt_2025_config(),
        )
        normalized_a = _normalized_xlsx(out_a)

        out_b = example_run(on_chain_fetch=None, config=_pt_2025_config())
        normalized_b = _normalized_xlsx(out_b)

        assert normalized_a == normalized_b, (
            "extract.xlsx content must be identical whether or not the on-chain fetcher runs"
        )

    def test_normalized_xlsx_ignores_wallclock_timestamps(self, tmp_path):
        """Guard for the normalization helper: forced timestamp drift must not break equality.

        Two openpyxl saves of the same content are made with deliberately
        different wall-clock inputs: different ``wb.properties.created`` (which
        lands in ``docProps/core.xml``) and different zip entry ``date_time``
        (achieved by saving, waiting past a second boundary, and saving again).
        Raw bytes differ (content-level and zip-metadata timestamps drift);
        normalized bytes must be equal.
        """
        from datetime import UTC, datetime, timedelta

        from openpyxl import Workbook

        def _save(path: Path, created: datetime) -> None:
            wb = Workbook()
            ws = wb.active
            ws.title = "Extract"
            ws["A1"] = "frozen content"
            wb.properties.created = created
            wb.properties.modified = created
            wb.save(path)

        path_a = tmp_path / "a.xlsx"
        path_b = tmp_path / "b.xlsx"
        _save(path_a, datetime(2026, 8, 17, 10, 0, 0, tzinfo=UTC))
        # Force a wall-clock second-boundary gap so the zip entry date_time
        # values differ between the two saves (the observed flake trigger).
        import time

        time.sleep(1.1)
        _save(path_b, datetime(2026, 8, 17, 12, 34, 56, tzinfo=UTC) + timedelta(days=7))

        assert path_a.read_bytes() != path_b.read_bytes(), (
            "precondition: forced timestamp drift must change the raw bytes"
        )
        assert _normalized_xlsx(path_a) == _normalized_xlsx(path_b), (
            "normalized form must be equal despite zip-metadata and core.xml timestamp drift"
        )
