"""Direct unit tests for the extracted retry-ladder module (review r3 F3/F6).

Pin ``retry_stale_on_chain_fetch``'s parameter contract INDEPENDENT of the
``run_report`` wrapper seam: tiny injected ``delays``, a recording ``sleep``
callable, and a real (``time.sleep``-free) run, so a future direct caller or
an import-time capture of the sleep seam fails loudly here instead of
sleeping the backoff window for real.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import pytest

from tax_reporting.application.on_chain_retry import (
    describe_retry_consequence,
    retry_stale_on_chain_fetch,
)
from tax_reporting.domain.exceptions import ReportGenerationError
from tests.unit.application.conftest import BERA_CSV_HEADER as _BERA_CSV_HEADER
from tests.unit.application.conftest import stale_marker_state


@pytest.mark.unit
class TestRetryStaleOnChainFetch:
    LOGGER_NAME = "test_on_chain_retry"

    def test_exhaustion_raises_after_every_injected_delay(self, tmp_path: Path) -> None:
        """Every attempt raises: the ladder sleeps BEFORE each of the injected
        delays, then raises naming the injected attempt count (not the
        production schedule's 6)."""
        _bera, marker = stale_marker_state(tmp_path, year=2025)
        sleeps: list[float] = []
        attempts: list[int] = []

        def _always_fails(*, year: int, output_dir: Path) -> Path:
            attempts.append(len(attempts) + 1)
            raise RuntimeError("api down")

        with pytest.raises(
            ReportGenerationError,
            match=r"2 automatic refetch attempts failed",
        ) as excinfo:
            retry_stale_on_chain_fetch(
                output_dir=tmp_path,
                year=2025,
                on_chain_fetch=_always_fails,
                logger=logging.getLogger(self.LOGGER_NAME),
                delays=(0.5, 0.25),
                sleep=sleeps.append,
            )

        # The match= gate above already pins the attempt-count clause; assert
        # a DISTINCT property here (review r4 F8): the marker is named.
        assert marker.name in str(excinfo.value)
        assert len(attempts) == 2
        assert sleeps == [0.5, 0.25], "sleep must be the INJECTED callable, one per delay"

    def test_recovery_returns_after_csv_rewrite(self, tmp_path: Path) -> None:
        """A successful attempt that rewrites the CSV newer than the marker
        ends the ladder with a normal return (no raise) after one attempt."""
        bera, marker = stale_marker_state(tmp_path, year=2025)
        sleeps: list[float] = []

        def _heals(*, year: int, output_dir: Path) -> Path:
            bera.write_text("healed\n", encoding="utf-8")
            csv_new = marker.stat().st_mtime + 10
            os.utime(bera, (csv_new, csv_new))
            return bera

        retry_stale_on_chain_fetch(
            output_dir=tmp_path,
            year=2025,
            on_chain_fetch=_heals,
            logger=logging.getLogger(self.LOGGER_NAME),
            delays=(0.0, 0.0),
            sleep=sleeps.append,
        )

        assert sleeps == [0.0], "recovery after the FIRST attempt stops the ladder"

    def test_no_fetch_callable_returns_without_sleeping(self, tmp_path: Path) -> None:
        """Review r4 F3: the no-callable arm, DIRECT at this tier - a stale
        state plus ``on_chain_fetch=None`` returns immediately (no sleeps, no
        entry INFO), leaving the immediate ``build_projection`` refusal to
        fire in the caller."""
        stale_marker_state(tmp_path, year=2025)
        sleeps: list[float] = []

        retry_stale_on_chain_fetch(
            output_dir=tmp_path,
            year=2025,
            on_chain_fetch=None,
            logger=logging.getLogger(self.LOGGER_NAME),
            delays=(0.5, 0.25),
            sleep=sleeps.append,
        )

        assert sleeps == [], "the no-callable arm must not sleep"

    def test_healthy_state_returns_before_any_sleep_or_fetch(self, tmp_path: Path) -> None:
        """Review r5 F5: the healthy-entry arm DIRECT at this tier - a bera
        CSV with NO marker means the entry predicate is not stale, so the
        ladder returns before any sleep or fetch (fail-loud sentinels prove
        neither is reached; network dependency only in the broken state)."""
        bera = tmp_path / "2025" / "bera_transactions.csv"
        bera.parent.mkdir(parents=True)
        bera.write_text(_BERA_CSV_HEADER + "\n", encoding="utf-8")

        def _must_not_sleep(_delay: float) -> None:
            pytest.fail("a healthy (marker-less) state must not sleep the backoff window")

        def _must_not_fetch(*, year: int, output_dir: Path) -> Path:
            pytest.fail("a healthy (marker-less) state must not attempt the fetch")

        # A plain return (no exception) is the assertion: any sentinel firing
        # or any raise fails the test.
        retry_stale_on_chain_fetch(
            output_dir=tmp_path,
            year=2025,
            on_chain_fetch=_must_not_fetch,
            logger=logging.getLogger(self.LOGGER_NAME),
            delays=(0.5,),
            sleep=_must_not_sleep,
        )

    def test_empty_delays_returns_without_attempting(self, tmp_path: Path) -> None:
        """Review r4 F11: an empty injected schedule returns WITHOUT the
        dishonest exhaustion raise ("0 automatic refetch attempts failed"
        would be false - nothing was attempted); ``build_projection`` refuses
        instead, mirroring the no-callable arm."""
        stale_marker_state(tmp_path, year=2025)
        sleeps: list[float] = []
        attempts: list[int] = []

        def _must_not_run(*, year: int, output_dir: Path) -> Path:
            attempts.append(len(attempts) + 1)
            pytest.fail("an empty schedule must not attempt the fetch")

        retry_stale_on_chain_fetch(
            output_dir=tmp_path,
            year=2025,
            on_chain_fetch=_must_not_run,
            logger=logging.getLogger(self.LOGGER_NAME),
            delays=(),
            sleep=sleeps.append,
        )

        assert sleeps == []
        assert attempts == []

    def test_path_return_but_still_stale_terminates_after_one_attempt(
        self, tmp_path: Path, caplog
    ) -> None:
        """Review r4 F3: the Path-return-still-stale terminal arm, DIRECT at
        this tier - one attempt (one sleep), no raise from the ladder (the
        shared ``build_projection`` refusal decides), and the still-stale
        WARNING naming the marker."""
        bera, marker = stale_marker_state(tmp_path, year=2025)
        sleeps: list[float] = []
        attempts: list[int] = []

        def _returns_stale_path(*, year: int, output_dir: Path) -> Path:
            attempts.append(len(attempts) + 1)
            return bera

        with caplog.at_level(logging.WARNING, logger=self.LOGGER_NAME):
            retry_stale_on_chain_fetch(
                output_dir=tmp_path,
                year=2025,
                on_chain_fetch=_returns_stale_path,
                logger=logging.getLogger(self.LOGGER_NAME),
                delays=(0.5, 0.25),
                sleep=sleeps.append,
            )

        assert attempts == [1], "a Path-returning stale attempt is TERMINAL for the ladder"
        assert sleeps == [0.5], "exactly one sleep before the single terminal attempt"
        assert any(
            "still newer" in record.getMessage() for record in caplog.records
        ), f"expected the still-stale WARNING; got: {[r.getMessage() for r in caplog.records]}"


@pytest.mark.unit
class TestDescribeRetryConsequence:
    """Review r4 F4: pin the operator-facing consequence text content - the
    backoff total, the attempt count, the marker filename, and the manual-clear
    clause - so a wrong total or dropped clear ships noisily."""

    def test_consequence_names_total_attempts_marker_and_manual_clear(self) -> None:
        marker_name = "bera_transactions.csv.fetch-failed"
        message = describe_retry_consequence((1.0, 2.0, 4.0, 8.0, 16.0, 32.0), marker_name)

        assert "63 s of backoff sleep" in message
        assert "6 attempts" in message
        assert marker_name in message
        assert "delete the marker" in message.lower()
        assert "refuse the run" in message
        # Review r5 F2: the refusal clause must enumerate all three causes
        # (every attempt fails, no fetch callable wired, marker stays newer),
        # not just the exhaustion case.
        assert "cannot clear the stale marker" in message
        assert "every attempt fails" in message
        assert "no fetch callable is wired" in message
        assert "the marker stays newer than the CSV" in message

