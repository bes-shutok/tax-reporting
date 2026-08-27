"""Retry ladder for a stale on-chain fetch marker (plan 2026-08-26).

Network-retry service extracted from ``run_report`` (the repo's orchestration
thin-layer ceiling, ~500 lines). Seam ownership is deliberate:

- The backoff schedule ``_STALE_FETCH_RETRY_DELAYS_S`` and the sleep seam
  ``_retry_sleep`` stay defined in ``run_report`` (the plan's Validation
  Commands pin them there, and tests monkeypatch ``run_report._retry_sleep``);
  they are passed in as ``delays`` / ``sleep`` on every call, so patching the
  seam in ``run_report`` still controls this ladder.
- The staleness predicate stays singly defined as
  :func:`on_chain_th_substitution.fetch_marker_is_stale` (no second mtime
  comparison may drift); the manual-clear clause stays singly defined as
  ``STALE_MARKER_MANUAL_CLEAR`` in the same module; the per-attempt fetcher
  narrative stays owned by the fetcher
  (``on_chain_fetcher.FETCH_ATTEMPT_NARRATIVE``; review r4 F7).

See :func:`retry_stale_on_chain_fetch` for the branch-by-branch contract.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from ..domain.exceptions import ReportGenerationError
from .on_chain_fetcher import (
    FETCH_ATTEMPT_NARRATIVE,
    OnChainFetch,
    bera_csv_path,
    fetch_failed_marker_path,
)
from .on_chain_th_substitution import STALE_MARKER_MANUAL_CLEAR, fetch_marker_is_stale


def retry_stale_on_chain_fetch(  # noqa: PLR0913 (delays/sleep seams stay owned by run_report; see module docstring)
    *,
    output_dir: Path,
    year: int,
    on_chain_fetch: OnChainFetch | None,
    logger: logging.Logger,
    delays: tuple[float, ...],
    sleep: Callable[[float], None],
) -> None:
    """Retry a known-stale on-chain fetch with exponential backoff.

    Entered ONLY when the shared staleness predicate
    (:func:`on_chain_th_substitution.fetch_marker_is_stale`) reports the
    fetch-failure marker newer than the bera CSV on the opted-in path. A
    healthy (or marker-less, or marker-deleted-mid-check TOCTOU) run never
    reaches the network from here (network dependency only in the broken
    state).

    Behavior:

    - ``on_chain_fetch is None`` (no API key wired): no refetch is possible;
      return so the immediate ``build_projection`` refusal fires (the ladder
      and its attempt count live HERE, not in the refusal).
    - Sleep BEFORE each attempt (the short initial delay avoids hammering an
      API that failed on a prior run), then attempt the fetch in its own
      broad ``except Exception`` (WARNING per failure; scoped to the attempt
      ONLY), then re-check the predicate.
    - Predicate false after an attempt (the fetch rewrote the CSV newer than
      the marker - the landed self-heal - or the marker was deleted
      mid-ladder, the documented manual clear, or the CSV vanished mid-check):
      log the state-neutral recovery INFO and return for a normal
      substitution.
    - Attempt returned a Path but the predicate is STILL True (clock skew, or
      a fetch that returns without rewriting the CSV): the ladder stops
      retrying (a healthy fetch must not be refuse-terminated with a
      failed-attempts message) and returns; the shared ``build_projection``
      staleness refusal makes the final call, keeping the two refusal causes
      discriminable (the attempt count stays exclusive to the exhaustion
      raise).
    - Exhaustion (every attempt raised or returned ``None``): log an ERROR and
      raise ``ReportGenerationError`` HERE, outside every per-attempt
      ``except`` so the M1 boundary propagates it. The ladder never deletes
      the marker (deletion is the documented manual clear).

    Args:
        output_dir: Base output directory (the bera CSV / marker live under it).
        year: The fiscal year (selects the per-year subdirectory).
        on_chain_fetch: The injected fetch callable; ``None`` means no refetch
            is possible (the immediate ``build_projection`` refusal fires).
        logger: Logger for the entry INFO, per-attempt WARNINGs, the recovery
            INFO, and the exhaustion ERROR.
        delays: Backoff schedule (seconds), one attempt per entry, sleep
            BEFORE each attempt. Owned by ``run_report``
            (``_STALE_FETCH_RETRY_DELAYS_S``).
        sleep: Sleep seam (``run_report._retry_sleep``; tests monkeypatch it
            there so no test sleeps the backoff window for real).

    Raises:
        ReportGenerationError: every scheduled attempt failed (raised or
            returned ``None``) and the marker is still newer than the CSV.
    """
    bera_csv = bera_csv_path(output_dir, year)
    marker = fetch_failed_marker_path(output_dir, year)
    if not fetch_marker_is_stale(bera_csv, marker):
        return
    if on_chain_fetch is None:
        return
    if not delays:
        # Empty schedule (review r4 F11): nothing can be attempted, so an
        # exhaustion raise claiming "0 ... attempts failed" would be false.
        # Return and let ``build_projection`` refuse, mirroring the
        # no-callable arm above.
        return
    logger.info(
        "Stale on-chain fetch marker detected (marker %s is newer than the bera CSV); "
        "retrying the fetch automatically with exponential backoff",
        marker.name,
    )
    for delay in delays:
        sleep(delay)
        fetch_result: Path | None = None
        try:
            fetch_result = on_chain_fetch(year=year, output_dir=output_dir)
        except Exception as exc:  # noqa: BLE001
            # Broad catch scoped to THIS attempt only; the ladder's own
            # exhaustion raise sits outside every except.
            logger.warning(
                "On-chain refetch attempt failed after %.1f s backoff: %s",
                delay,
                exc,
            )
        else:
            if fetch_result is None:
                # The fetcher's empty-wallet-config branch: no CSV rewrite, a
                # NEW marker written -> counts as a FAILED attempt; the
                # predicate re-check below keeps the outcome honest.
                logger.warning(
                    "On-chain refetch attempt after %.1f s backoff returned None "
                    "(no CSV rewritten; empty wallet config); treating it as a failed attempt",
                    delay,
                )
            else:
                logger.info(
                    "On-chain refetch attempt after %.1f s backoff returned %s; "
                    "re-checking marker freshness",
                    delay,
                    fetch_result,
                )
        if not fetch_marker_is_stale(bera_csv, marker):
            logger.info(
                "Recovered from a stale on-chain fetch condition: the marker %s is "
                "no longer newer than %s (refetched, manually cleared, or the CSV "
                "is absent); proceeding to the substitution stage",
                marker.name,
                bera_csv,
            )
            return
        if fetch_result is not None:
            # A Path-returning attempt that leaves the marker newer (e.g. a
            # forward-skewed marker clock) is TERMINAL for the ladder;
            # retrying cannot clear it, and the exhaustion raise must name
            # only actually-failed attempts. build_projection decides.
            logger.warning(
                "On-chain refetch attempt returned %s but the fetch-failure marker "
                "%s is still newer than the CSV (clock skew or a fetch that returns "
                "without rewriting); letting the substitution's staleness refusal decide",
                fetch_result,
                marker.name,
            )
            return
    logger.error(
        "On-chain fetch is stale and could not be refreshed for %s: %s attempts failed",
        bera_csv,
        len(delays),
    )
    raise ReportGenerationError(
        f"Stale on-chain fetch data: {len(delays)} automatic refetch "
        f"attempts failed for {bera_csv} (fetch-failure marker {marker.name} is newer "
        f"than the CSV). {STALE_MARKER_MANUAL_CLEAR.format(marker_name=marker.name)}"
    )


def describe_retry_consequence(delays: tuple[float, ...], marker_name: str) -> str:
    """Operator-facing consequence sentence for a fresh fetch-failure marker.

    Used by ``run_report``'s collection-fetch soft-fail WARNING: names what the
    next opted-in run will do under the retry-then-refuse contract (automatic
    refetch with this backoff schedule, refusal when the attempts cannot
    clear the stale marker - every attempt fails, no fetch callable is wired,
    or the marker stays newer than the CSV) and the manual clear. Lives here,
    next to the schedule knowledge it reads.
    """
    return (
        f"the next opted-in run will retry the fetch automatically "
        f"({len(delays)} attempts with exponential backoff: {sum(delays):.0f} s of "
        f"backoff sleep plus each attempt's own transfer time, so rate-limited "
        f"exhaustion can block for several minutes, since "
        f"{FETCH_ATTEMPT_NARRATIVE}) and will "
        f"refuse the run if the attempts cannot clear the stale marker "
        f"(every attempt fails, no fetch callable is wired on that next run, "
        f"or the marker stays newer than the CSV). "
        f"{STALE_MARKER_MANUAL_CLEAR.format(marker_name=marker_name)}"
    )
