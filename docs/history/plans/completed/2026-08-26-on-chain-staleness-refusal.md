# Plan: On-chain staleness auto-retry ladder, then hard refusal

Backlog origin: `docs/history/backlog/2026-08-26-on-chain-review-followups.md` item 1
(review r1 F6, extended r2 F5, hardened r3-r5). Contract decisions: 2026-08-26 the
user chose hard refusal mirroring M1; 2026-08-27 the user SUPERSEDED it with a
retry-first ladder (exponential backoff refetch: six attempts over 63 s of backoff
sleep plus fetch time) so refusal
is the last resort when the data cannot be re-fetched automatically. Rejected
alternatives across both decisions: immediate hard refusal only; in-artifact review
indicator; continue-without-crypto.
Plan review: `docs/history/reviews/2026-08-26-plan-review-on-chain-staleness-refusal-r1.md` … (all rounds).

## Terms

- **M1 fail-loud boundary**: the `try/except ReportGenerationError` wrap in
  `run_report.py` `_substitute_on_chain_th`; a parse failure on the opted-in path
  propagates and is never swallowed by the broad collection-fetch `except Exception`.
- **Fetch-failure marker**: `bera_transactions.csv.fetch-failed` written next to the
  bera CSV by `run_report.py` when a refresh soft-fails; deleting it is the
  documented manual clear.
- **Opted-in path**: `ON_CHAIN_TH_WALLETS` set and the fiscal-year bera CSV present;
  `OnChainThSubstituter.build_projection` is the shared builder for both the
  production substitution and the validation harness.
- **Staleness predicate**: one shared function `fetch_marker_is_stale(bera_csv, marker)`
  in `on_chain_th_substitution.py` encapsulating the landed mtime comparison plus the
  r4 TOCTOU arm; both the retry ladder and the refusal call it (single definition,
  no drift).
- **Retry ladder**: threaded through `run_report.py`, when the opted-in substitution detects a
  stale marker AND a fetch callable is injected, re-run the fetch with exponential
  backoff `_STALE_FETCH_RETRY_DELAYS_S = (1.0, 2.0, 4.0, 8.0, 16.0, 32.0)`: one
  attempt per delay, sleep BEFORE each attempt (the short initial delay avoids
  hammering an API that failed on a PRIOR run; the ladder runs before the
  collection-phase fetch at `run_report.py:148`, so the marker was necessarily
  written by an earlier run, and a mid-ladder recovery may duplicate that later
  fetch in the same run; harmless, both write the same CSV; r10-F2). Wall-clock
  budget is
  63 s of backoff sleep PLUS the six attempts' own transport time (typically a bit
  over a minute; r8-F5). A success rewrites the CSV newer than the marker (landed
  self-heal) and the run proceeds.
  Amendment (review r2 F2 / r3 F12): the ladder BODY lives in
  `on_chain_retry.py` (`retry_stale_on_chain_fetch`); the delays constant and
  the `_retry_sleep` seam remain in `run_report.py` per the frozen Validation
  Commands and are threaded in as `delays` / `sleep` on every call.
- **OnChainFetch seam**: the existing injected keyword-only fetch callable
  (`run_report.py` line 43); `None` (no API key wired in `main.py`) means no retry is
  possible and the refusal fires immediately.
  Amendment (review r5 F10): the Protocol's defining home is `on_chain_fetcher.py`;
  `run_report.py` imports it under `TYPE_CHECKING` for annotation only (no runtime
  re-export).
- **Sleep seam**: `run_report.py` module attribute `_retry_sleep = time.sleep`,
  called by the ladder; tests monkeypatch it (hermetic suite, per-test 120 s timeout;
  the ladder must never really sleep in tests).
- **TOCTOU guard (r4)**: a marker deleted between `is_file()` and `stat()` reads as
  absent and must NOT refuse (deletion is the manual clear).
- **Skill-gate marker**: before every Write/Edit to this plan file, refresh
  `plans.<project>.<session>.marker` under `~/.ai-playbook/runtime/skill-invoked/`
  via `python3 ~/.ai-playbook/scripts/skill_gate.py --write-marker` (FAIL-LOUD;
  ensure the dir exists; `FileExistsError` from a concurrent refresh is benign).
- **Session key**: `SID="$(python3 ~/.ai-playbook/scripts/session_channel.py)"`;
  empty SID → omit `--session-id` (core keys the literal `no-session`); otherwise
  pass `--session-id "$SID"` (marker session = `sha1(value)[:16]`).

## Gist & Examples

Amendment (review r5 F12): pre-execution line anchors in this plan (e.g. `lines
393-414`, `run_report.py:374-385`, `run_report.py:148`, `run_report.py` line 43)
reflect the master baseline; the r2/r3 module extractions shifted line numbers in
the shipped files.

Today a failed on-chain refresh writes the marker next to the previous run's bera
CSV, and the opted-in TH substitution (`src/tax_reporting/application/on_chain_th_substitution.py`,
`build_projection`, lines 393-414) logs a loud ERROR and **proceeds with the stale
CSV**. After the `ON_CHAIN_TH_WALLETS` flip that projection feeds report generation,
so a stale projection under-reports on-chain activity in a filing artifact.

This plan changes the contract to a retry-first ladder whose last rung is a hard
refusal mirroring M1:

- Marker newer than CSV (refresh failed after the CSV's last successful write) and a
  fetch callable is injected → the run FIRST retries the fetch automatically: six
  attempts, sleeping 1 s, 2 s, 4 s, 8 s, 16 s, 32 s BEFORE each attempt. Each attempt
  failure is logged at WARNING; the ladder re-checks the shared staleness predicate
  after every attempt.
  - Any attempt succeeds → the CSV is rewritten newer than the marker (landed
    self-heal), an INFO names the recovery, and the run proceeds normally.
  - All attempts fail → the ladder (body in `on_chain_retry.retry_stale_on_chain_fetch`,
    threaded from `_substitute_on_chain_th` in `run_report.py`; r4-F1 amendment) raises
    `ReportGenerationError` itself (r8-F2: the attempt count lives in the ladder, not
    in `build_projection`),
    naming the CSV path, the marker name, "6 automatic refetch attempts failed", and
    the manual clear ("delete the marker to proceed with the stale CSV for review
    only"); `maybe_substitute` is never reached.
- Marker newer than CSV and NO fetch callable (`None`; API key absent so a refetch
  is impossible) → the ladder is skipped and `build_projection` raises
  `ReportGenerationError` immediately (message states no automatic refetch was
  possible; nothing to retry; true last resort).
  Amendment (review r5 F9): the shipped refusal message is the widened
  three-disjunct wording (review r2 F1) - the automatic refetch attempts failed,
  were unavailable (no fetch callable), or could not clear the stale marker (a
  Path-returning attempt left the marker newer than the CSV); it does not carry a
  "nothing to retry" clause. Task 2 and `docs/maintenance/on_chain_validation.md`
  match the code.
- Marker older than CSV (a later successful fetch rewrote the CSV; self-heal) →
  proceeds, unchanged; the ladder is not entered.
- No marker → proceeds, unchanged; the ladder is not entered.
- Marker deleted mid-check (TOCTOU) → reads as absent → proceeds, unchanged.
- Bera CSV absent entirely → unchanged DI-1 behavior: WARNING, no projection, run
  continues on Koinly data (the collection fetch stays non-blocking; only the
  opted-in *substitution* refuses on known-stale data it could not refresh).

Example: CSV fetched 2026-08-20; the 2026-08-25 refresh fails → marker written
2026-08-25. The next opted-in run detects the stale marker and retries the fetch six
times (sleeping 1 s before the first retry, 2 s before the second, … 32 s before the
sixth). If the API was down for quota and recovers, attempt 3 succeeds, the CSV is
rewritten, and the user sees only an INFO about the recovery. If all six attempts
fail, the run refuses with a message naming `bera_transactions.csv`,
`bera_transactions.csv.fetch-failed`, "6 automatic refetch attempts failed", and the
manual clear.

Because the validation harness shares `build_projection`
(`on_chain_validation/runner.py` imports `OnChainThSubstituter`), `--validate-on-chain-th`
on a stale marker refuses the same way; the harness has no fetch seam, so it never
retries (documented). The harness refusal propagates uncaught out of
`on_chain_validation/runner.py` and surfaces as `EXIT_VALIDATION_CRASH` (exit 2 with
traceback) rather than a clean `EXIT_VALIDATION_FAILED` enumeration: presentation
only; fail-loud intent and the actionable message are preserved, so this is
documented rather than changed (r10-F1). Fail-loud, documented in the maintenance doc.

## Evaluation Criteria

**Quality dimensions:**
- Correctness: all four marker states covered by tests (newer→retry ladder then raise
  with actionable message; older/absent/race→proceed); the raise propagates out of
  `maybe_substitute` (no new try/except swallows it) through the M1 boundary; the
  retry ladder covers success-mid-ladder, exhaustion, and no-fetch-callable paths.
- Contract/docs: `docs/maintenance/on_chain_validation.md` states the retry-then-refuse
  contract; the old "does NOT refuse" prose and the "(not a refusal: ...)" code
  comment are gone; backlog item 1 and the umbrella P2-candidate line updated.
- Maintainability: the r1-r5 hardening (empty-config marker, TOCTOU guard,
  unrecognized-type raise) is preserved verbatim in behavior; staleness is defined by
  exactly one predicate shared by the ladder and the refusal.
- Hermeticity: tests monkeypatch the sleep seam; no test really sleeps the backoff
  window (per-test 120 s timeout; a real 63 s ladder would nearly hit it).

**Done when:**
- `uv run pytest tests/unit/application/test_on_chain_th_substitution.py
  tests/unit/application/test_run_report.py -q` passes with the rewritten tests; full
  `uv run pytest -q` suite green.
- Validation Commands block passes, including the fail-closed stale-prose sweeps.

**Ship when:**
- None beyond the repository: the contract takes effect on the next opted-in run.

## Review Scope

**Explicit must-fix**; findings on these paths are always in scope (review and fix if valid):

**Production code:**
- `src/tax_reporting/application/on_chain_th_substitution.py`
- `src/tax_reporting/application/run_report.py` *(retry ladder + soft-fail message)*
- `docs/maintenance/on_chain_validation.md`

**Tests:**
- `tests/unit/application/test_on_chain_th_substitution.py`
- `tests/unit/application/test_run_report.py`

**Plan-related extension**; implementation and review may change files not listed above.
Treat a finding as in scope when it is causally related to this plan: it implements or
completes a plan task, fixes a regression introduced by plan work, closes wiring or docs
implied by an explicit must-fix change, or contradicts a contract the plan changed.
If the link to the plan is weak or speculative, drop as out of scope with a one-line reason.

**Out of scope; reject unless plan-related:**
- `src/tax_reporting/application/on_chain_fetcher.py`; marker write mechanics, CSV
  write, and self-heal stay exactly as landed. The ladder CALLS the injected fetch
  callable; it must not modify fetcher internals.
- `src/tax_reporting/main.py` and everything else; not touched by this contract
  (the existing `on_chain_fetch` injection already threads through).

## Design Invariants (CR Guard)

- **M1 boundary unchanged** (`run_report.py` `_substitute_on_chain_th`): both refusal
  raises (the ladder's exhaustion raise and `build_projection`'s stale raise) must
  propagate through it; do not widen any `except` to swallow
  `ReportGenerationError` on this path. The retry ladder's per-attempt `except
  Exception` covers ONLY the fetch call inside the ladder, never the substitution,
  and never the ladder's own exhaustion raise.
- **DI-1 non-blocking collection preserved**: the fetch-side soft fail (marker write +
  WARNING at `run_report.py:374-385`) still does not abort the run; only the opted-in
  substitution refuses. A CSV-less opted-in run still warns and continues on Koinly.
- **Network-dependency only in the broken state**: a healthy run (no stale marker)
  never invokes the fetch from the substitution path; only a stale-marker opted-in
  run with an injected fetch callable does. `on_chain_fetch=None` skips straight to
  the refusal.
- **TOCTOU guard (r4)**: `FileNotFoundError` on `marker.stat()` still reads as
  marker-absent → proceed. Deletion is the documented manual clear. The extracted
  predicate preserves this arm; deleting it must fail the race test.
- **Marker self-heal**: a later successful fetch (including a successful ladder
  attempt) rewrites the CSV newer than the marker and runs proceed without cleanup;
  no new cleanup path is introduced. The ladder must not delete the marker itself.
- **Single staleness definition**: the ladder and the refusal both call
  `fetch_marker_is_stale`; no second mtime comparison may be introduced.
- **Hermetic retry tests**: backoff sleeps go through the `_retry_sleep` module
  attribute; tests patch it and assert the exact delay sequence, never sleeping for
  real.
- **User decision provenance**: the 2026-08-27 retry-first supersession is the user's
  call (immediate hard refusal demoted to last resort); the replaced r1-F6 code
  comment must cite it, not re-litigate it.

## Validation Commands

```bash
uv run pytest tests/unit/application/test_on_chain_th_substitution.py tests/unit/application/test_run_report.py -q

# New contract prose present + old contract gone (fail-closed, per-rule sweeps):
test -f docs/maintenance/on_chain_validation.md || { echo "missing maintenance doc"; exit 1; }
grep -q "refuses the run" docs/maintenance/on_chain_validation.md \
  || { echo "new staleness refusal contract missing from on_chain_validation.md"; exit 1; }
grep -q "automatic refetch" docs/maintenance/on_chain_validation.md \
  || { echo "retry-ladder contract missing from on_chain_validation.md"; exit 1; }
if grep -rq "By design this does NOT refuse" docs/maintenance/ docs/history/backlog/; then
  echo "stale staleness contract prose remains"; exit 1
fi
# r2-F1: the phrase is LINE-WRAPPED in the doc today ("does\nNOT refuse"), so the
# plain grep above alone can never fire; the flattened per-file check is the real
# backstop:
for f in docs/maintenance/on_chain_validation.md docs/history/backlog/2026-08-26-on-chain-review-followups.md; do
  test -f "$f" || { echo "missing $f"; exit 1; }
  if tr '\n' ' ' < "$f" | grep -q "By design this does NOT refuse"; then
    echo "stale staleness contract prose remains in $f"; exit 1
  fi
done
if grep -q "not a refusal" src/tax_reporting/application/on_chain_th_substitution.py; then
  echo "stale r1-F6 code comment remains"; exit 1
fi
grep -q "refuse" src/tax_reporting/application/run_report.py \
  || { echo "soft-fail message does not name the refusal"; exit 1; }
if grep -q "will log an error" src/tax_reporting/application/run_report.py; then
  echo "soft-fail message still claims a later ERROR log"; exit 1
fi
# Retry ladder wiring: the delays constant, the sleep seam, and the shared predicate
# each get a dedicated probe (rule 7); missing any one fails its own check.
grep -q "STALE_FETCH_RETRY_DELAYS_S.*= (1.0, 2.0, 4.0, 8.0, 16.0, 32.0)" src/tax_reporting/application/run_report.py \
  || { echo "retry delays constant missing from run_report.py"; exit 1; }
grep -q "_retry_sleep" src/tax_reporting/application/run_report.py \
  || { echo "sleep seam missing from run_report.py"; exit 1; }
grep -q "def fetch_marker_is_stale" src/tax_reporting/application/on_chain_th_substitution.py \
  || { echo "shared staleness predicate missing from on_chain_th_substitution.py"; exit 1; }
grep -q "fetch_marker_is_stale" src/tax_reporting/application/run_report.py \
  || { echo "retry ladder does not use the shared staleness predicate"; exit 1; }
# r4-F2 amendment: since the r2/r3 extraction the LADDER BODY lives in
# on_chain_retry.py, where the actual predicate call sites are; the run_report.py
# probe above is retained for the plan freeze but is comment-satisfied there, so
# the OWNING probe below is the real backstop (fail-closed on the module that
# branches on staleness; pins BOTH call sites, entry gate + post-attempt re-check).
test "$(grep -c "fetch_marker_is_stale" src/tax_reporting/application/on_chain_retry.py)" -ge 2 \
  || { echo "retry ladder does not use the shared staleness predicate"; exit 1; }

uv run pytest -q
```

(The sweeps intentionally do not cover `docs/history/plans/`; this plan file quotes
the old phrases as checker literals.)

### Task 1: RED; staleness refusal + retry ladder tests

Files:
- `tests/unit/application/test_on_chain_th_substitution.py`
- `tests/unit/application/test_run_report.py`

- [x] DELETE the superseded old-contract test `TestOnChainThSubstitution#test_build_projection_warns_on_stale_fetch_marker` (line 325: asserts the projection BUILDS plus an ERROR log on a stale marker); the refusal test below replaces it, and its three control scenarios become the retained-control tests below (r1-F1)
- [x] `TestOnChainThSubstitution#test_build_projection_refuses_on_stale_fetch_marker`; given the bera CSV present and a `.fetch-failed` marker written after it (marker mtime newer), expects `build_projection` to raise `ReportGenerationError` whose message names the CSV path, the marker filename, states that any automatic refetch attempts have failed or were unavailable (the ladder, when it ran, lives upstream in `run_report`; r8-F2), and the clear paths (delete the marker to proceed with the stale CSV for review only)
- [x] `TestOnChainThSubstitution#test_build_projection_proceeds_when_marker_older_than_csv`; given a marker older than the CSV (self-heal state), expects the projection to build and no exception (retain the existing r2-F1 control)
- [x] `TestOnChainThSubstitution#test_build_projection_proceeds_when_marker_absent`; given no marker file, expects the projection to build (retain the existing control)
- [x] `TestOnChainThSubstitution#test_build_projection_marker_deletion_race_proceeds`; given the marker vanishing mid-check; monkeypatch `Path.is_file` to return True while `Path.stat` raises `FileNotFoundError`, so the `except FileNotFoundError` arm on `marker.stat()` is actually reached (`is_file()` alone swallows the error internally; deleting that arm must fail this test; r1-F3); scope BOTH patches to the marker path only; a class-wide `Path.stat` patch breaks `find_repository_root()` (:419) and later path checks (r5-F1; a miss fails loudly in RED/GREEN, so this is authoring guidance, not a behavior risk); expects the build to proceed without refusal
- [x] `TestOnChainThSubstitution#test_maybe_substitute_propagates_staleness_refusal`; given the stale-marker state, expects `maybe_substitute` (the production entry) to raise the same `ReportGenerationError` uncaught
- [x] `TestOnChainThSubstitution#test_fetch_marker_is_stale_shared_predicate`; given (newer marker → True; older marker → False; absent marker → False; marker path whose `stat` raises `FileNotFoundError` after `is_file` True → False), expects the predicate to return exactly these values (direct unit coverage of the extracted helper, TOCTOU arm included)
- [x] `TestRunReportStalenessRetry#test_retry_ladder_recovers_mid_way`; given a stale marker and an injected fake fetch callable that fails twice then rewrites the bera CSV newer, expects `_substitute_on_chain_th` (with `on_chain_fetch` threaded) to proceed to a successful substitution, three fetch invocations, two WARNING logs, one recovery INFO, and `_retry_sleep` called with the sleep BEFORE each of the three attempts (1.0, 2.0, 4.0; r8-F1)
- [x] `TestRunReportStalenessRetry#test_retry_ladder_exhaustion_refuses`; given a stale marker and a fake fetch that always raises, expects the LADDER in `_substitute_on_chain_th` to raise the M1-boundary `ReportGenerationError` itself (r8-F2: the raise happens in `run_report`, before `maybe_substitute` is called) naming "6 automatic refetch attempts failed", exactly six fetch invocations, and `_retry_sleep` called with the full sequence (1.0, 2.0, 4.0, 8.0, 16.0, 32.0)
- [x] `TestRunReportStalenessRetry#test_no_fetch_callable_refuses_immediately`; given a stale marker and `on_chain_fetch=None`, expects the `build_projection` `ReportGenerationError` (no attempt count in the message; it must NOT contain "6 automatic refetch attempts failed"; the two refusal causes stay discriminable; r9-F1) to propagate out of `_substitute_on_chain_th`, with zero fetch invocations and zero `_retry_sleep` calls
- [x] `TestRunReportStalenessRetry#test_healthy_state_skips_ladder`; given no marker (or marker older than CSV) and an injected fake fetch, expects the substitution to proceed with ZERO fetch invocations (the ladder is entered only on a stale marker)
- [x] `TestRunReportStalenessRetry#test_retry_ladder_does_not_delete_marker`; given exhaustion, expects the marker file to still exist after the refusal (no new cleanup path; invariant)
- [x] `TestRunReportStalenessRetry#test_retry_ladder_treats_none_return_as_failed_attempt`; given a stale marker and a fake fetch that always returns `None` (the empty-wallet-config branch: rewrites nothing), expects six attempts each with a WARNING naming the None return, then the exhaustion `ReportGenerationError`, and no CSV rewrite (r11-F1)
- [x] All `TestRunReportStalenessRetry` tests monkeypatch `run_report._retry_sleep` to a recording fake; no test sleeps for real
- [x] Run → expect RED: `uv run pytest tests/unit/application/test_on_chain_th_substitution.py tests/unit/application/test_run_report.py -q`
- [x] Commit: `test(on-chain): staleness retry-then-refuse RED (ladder + M1 mirror refusal)`

### Task 2: GREEN; shared predicate + the refusal

Files:
- `src/tax_reporting/application/on_chain_th_substitution.py`

- [x] Extract the lines 398-404 mtime+TOCTOU check into module-level `fetch_marker_is_stale(bera_csv: Path, marker: Path) -> bool` (r4 race arm preserved verbatim); `build_projection` calls it
- [x] In `build_projection` (lines 393-414): replace the `logger.error` branch with a raise; `ReportGenerationError` (already imported at line 42) whose f-string message names `bera_csv`, `marker.name`, and the manual clear; the message states that automatic refetch attempts have failed or were unavailable (no attempt count: the ladder and its count live in `run_report`; r8-F2)
- [x] Replace the r1-F6 "(not a refusal: ...)" comment with the new contract + user-decision provenance (2026-08-27 retry-first supersession over the 2026-08-26 hard refusal; backlog item 1); keep citing r4 for the race arm
- [x] Run → expect GREEN for the substitution-module tests: `uv run pytest tests/unit/application/test_on_chain_th_substitution.py -q`
- [x] Grep-verify both callers share `build_projection` (no second staleness site): `grep -rn "build_projection" src/`
- [x] Commit: `feat(on-chain): refuse the opted-in TH substitution on a stale fetch marker (M1 mirror)`

### Task 3: GREEN; the retry ladder in run_report

Files:
- `src/tax_reporting/application/run_report.py`

- [x] Add module constants: `_STALE_FETCH_RETRY_DELAYS_S: tuple[float, ...] = (1.0, 2.0, 4.0, 8.0, 16.0, 32.0)` and the sleep seam `_retry_sleep = time.sleep` (import `time`)
- [x] Plumb the fetch callable down (r8-F3): `_substitute_on_chain_th` (called at line 242 inside `_resolve_koinly_stage`, def line 205) gains `on_chain_fetch: OnChainFetch | None`; `_resolve_koinly_stage` gains the same parameter and passes it through; the `run_report` caller (line 121) passes its existing `on_chain_fetch` argument. Grep-verify every `_resolve_koinly_stage` and `_substitute_on_chain_th` call site passes the new argument: `grep -rn "_resolve_koinly_stage\|_substitute_on_chain_th" src/ tests/`
- [x] Implement the ladder as a dedicated helper `_retry_stale_on_chain_fetch(...)` in `run_report.py`
  Amendment (review r2 F2 / r3 F12 / r4 F1): the ladder shipped as the module-level
  function `retry_stale_on_chain_fetch` in `src/tax_reporting/application/on_chain_retry.py`
  (orchestration thin-layer ceiling); `_substitute_on_chain_th` calls it with the
  delays constant and the `_retry_sleep` seam, which stay in `run_report.py` per the
  frozen Validation Commands.
  Original body text (delays, sleep seam, per-attempt catch, predicate re-check, recovery INFO, exhaustion ERROR + raise; r10-overflow: keeps `_substitute_on_chain_th` small and gives the ladder a direct seam), called from `_substitute_on_chain_th` before the `maybe_substitute` call: resolve `bera_csv`/marker via `bera_csv_path`/`fetch_failed_marker_path` and the shared `fetch_marker_is_stale` predicate; if stale AND `on_chain_fetch is not None`, run the ladder: for each delay in `_STALE_FETCH_RETRY_DELAYS_S`: `_retry_sleep(delay)` FIRST (the short initial delay avoids hammering an API that failed on a prior run; r10-F2), then attempt `on_chain_fetch(year=year, output_dir=output_dir)` in its own `try/except Exception` (WARNING per failure, DI-1-style broad catch scoped to the attempt only), then re-check the predicate; predicate false → log the recovery INFO and fall through to a normal substitution. If the ladder exhausts all six attempts, log an ERROR and raise `ReportGenerationError` inside the helper `_retry_stale_on_chain_fetch` (r11-F2: the raise lives in the HELPER, which `_substitute_on_chain_th` calls before `maybe_substitute`; r8-F2: `maybe_substitute` is never reached in this case) whose f-string names `bera_csv`, the marker name, "6 automatic refetch attempts failed" (len(_STALE_FETCH_RETRY_DELAYS_S)), and the manual clear; the raise must sit OUTSIDE every per-attempt `except` so the M1 boundary propagates it. An attempt whose callable returns `None` (the fetcher's empty-wallet-config branch: no CSV rewrite, a NEW marker written) counts as a FAILED attempt with its own WARNING naming the None return (r11-F1); the post-attempt predicate re-check keeps the outcome honest either way. If stale and `on_chain_fetch is None`, fall through to `maybe_substitute` directly (immediate `build_projection` refusal). Not stale → no ladder
- [x] Run → expect GREEN: `uv run pytest tests/unit/application/test_on_chain_th_substitution.py tests/unit/application/test_run_report.py -q`
- [x] Commit: `feat(on-chain): auto-retry stale on-chain fetch with exponential backoff before refusing`

### Task 4: fetch soft-fail message points at the ladder + refusal

Files:
- `src/tax_reporting/application/run_report.py`
- `tests/unit/application/test_run_report.py`

- [x] Grep `tests/` for assertions pinning the current soft-fail message text (`grep -rn "STALE" tests/`); if pinned, extend the assertion, else add a caplog assertion
- [x] REWRITE (not extend) the soft-fail log at `run_report.py:374-385` (r4-F1: the `logger.warning` statement spans 379-385; the cited range covers it plus the marker-write call, and the stale clause sits on line 383): drop any clause claiming a later ERROR log (false under the new contract; r1-F2); the message must state the consequence; the next opted-in run will retry the fetch automatically (63 s of backoff sleep plus each attempt's own transfer time: rate-limited exhaustion can block for several minutes, since each attempt drives per-wallet Etherscan calls with their own internal retries; r12-F2) and refuse if every attempt fails (or the marker is deleted for review-only use)
- [x] Run → expect GREEN: `uv run pytest tests/unit/application/test_run_report.py -q`
- [x] Commit: `feat(on-chain): fetch soft-fail message names the retry ladder and refusal`

### Task 5: documentation + backlog promotion

Files:
- `docs/maintenance/on_chain_validation.md`
- `docs/history/backlog/2026-08-26-on-chain-review-followups.md`
- `docs/history/backlog/2026-08-18-koinly-cancellation-program.md`

- [x] Rewrite the "Fetch-failure staleness marker (2026-08-26)" section (line 330): the opted-in substitution first retries the fetch automatically (six attempts, exponential backoff, 63 s of backoff sleep plus fetch time) and then refuses the run; deletion remains the manual clear; the validation harness refuses identically but never retries (no fetch seam) and its refusal surfaces as `EXIT_VALIDATION_CRASH` (exit 2, fail-loud with traceback; r10-F1); record the user's 2026-08-27 contract decision superseding the 2026-08-26 hard refusal. The rewrite must contain the literal phrases "refuses the run" and "automatic refetch" (the Validation Commands probe them; r2-F3)
- [x] Mark backlog item 1 promoted (link this plan); do not archive the backlog doc yet (items 2-3 have their own plans)
- [x] Update the umbrella backlog line 201 P2-candidate mention of "staleness hard-refusal" to point at this plan
- [x] Commit: `docs(on-chain): staleness retry-then-refuse contract; backlog item 1 promoted`

### Task 6: full validation

- [x] Run the Validation Commands block end-to-end; all green
- [x] `uv run pytest -q` full suite green
