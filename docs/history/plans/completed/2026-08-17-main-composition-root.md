# Plan: Decompose `_main` into a thin composition root + injectable `run_report` orchestrator

Promoted from backlog: `docs/history/backlog/2026-08-16-main-composition-root-decomposition.md`
(predecessor `2026-08-16-test-hermeticity-guards`, archived at
`docs/history/plans/completed/2026-08-16-test-hermeticity-guards.md`, landed as master `c6edbc6`;
its guards stay
untouched as regression tripwires). Language-specific testing traps: `docs/maintenance/python_guidelines.md`.

## Terms

- **Composition root**: the edge layer (`main()`/`_main()` in `src/tax_reporting/main.py`) that reads
  argv/env/`config.ini` exactly once each, builds collaborators, and delegates. It fails fast on
  config errors and contains no pipeline logic.
- **Functional Core / Imperative Shell**: the orchestrator (`run_report`) takes every collaborator
  (config object, on-chain fetch callable, logger) as a parameter and performs no environment reads.
- **DI-1 / DI-3 / DI-9**: repo design invariants. DI-1 broad `except Exception` degrade template
  (soft-fail for optional steps), DI-3 the env gate `os.getenv("BERA_CHAIN_API_KEY")` read at the
  edge exactly once, DI-9 defensive `None`-jurisdiction year resolution (no `AttributeError`).
- **M1 fail-loud boundary**: an opted-in wallet's on-chain TH parse failure raises
  `ReportGenerationError`; it is never swallowed by the collection-only soft-fail handler.
- **On-chain fetch**: the optional, non-blocking Etherscan V2 collection step (`run_on_chain_fetch`),
  distinct from the on-chain TH *substitution* path.
- **Skill-gate marker; Session key**: plans-skill write gate per
  `ai-playbook/agents/hooks/skill-gate/README.md`; session id via the shared
  `session_channel.py` subprocess (emptiness check first; empty → literal `no-session`, else
  `sha1(value)[:16]`). Refreshed before every plan-file write; fail-loud.

## Gist & Examples

`_main` (`src/tax_reporting/main.py:114-394`) is a ~280-line god-orchestrator carrying
`# noqa: PLR0912, PLR0915`. It owns config loading, the IB pipeline, the crypto pipeline (incl.
on-chain TH substitution), report writing, the DI-3 env gate, and the DI-1 degrade template. Every
test driving it must monkeypatch 5–6 internals (`load_configuration_from_file`,
`_resolve_koinly_directory`, `_infer_tax_year_hint_from_ib_data`, `load_contracts`,
`load_lp_snapshot`, `os.getenv`); `tests/end_to_end/test_on_chain_bera_opted_in.py` alone carries 30
monkeypatch lines. This was the structural root cause of the 2026-08-16 environment-leak incident:
tests patched every seam EXCEPT the env gate, so a shell exporting `BERA_CHAIN_API_KEY` made the
suite perform live Etherscan fetches at ~9s per test.

After this plan:

- `src/tax_reporting/application/run_report.py` *(new)* hosts `run_report(source_file, output_dir,
  app_config, on_chain_fetch, logger)` plus the pipeline helpers that only it
  uses (`_infer_tax_year_hint_from_ib_data`, `_extract_year`, `_detected_koinly_year`,
  `_is_koinly_year_mismatch`, `_load_crypto_tax_report`, `_resolve_koinly_directory`). The
  jurisdiction is derived INSIDE `run_report` (`tax_jurisdiction = app_config.tax_jurisdiction if
  app_config is not None else None`), so the impossible-state fixture (`app_config` present with a
  divergent embedded jurisdiction) cannot be constructed (r1 F4). It contains
  no `os.getenv`, no config-file reads, no argv parsing, and does not import `os`.
- `main.py` keeps `cli`, `main`, `_build_arg_parser`, `_validate_args`, and a reduced `_main` that:
  resolves defaults; pre-configures logging and loads config (audit-trail block moves verbatim);
  reads `BERA_CHAIN_API_KEY` ONCE. If set, it binds `on_chain_fetch = functools.partial(
  run_on_chain_fetch, api_key=key)`, else `None` with the existing "not set" WARNING at construction
  time; then calls `run_report(...)`.
- Example: a crypto-pipeline test currently doing `monkeypatch.setattr(main, "_resolve_koinly_directory", ...)`
  instead calls `run_report(source_file=..., output_dir=..., app_config=<built Config>,
  on_chain_fetch=None, logger=...)` with a tmp_path
  Koinly layout; hermetic by construction, zero patching of `tax_reporting.main` module
  attributes. A wiring test's `_Recorder` becomes a plain injected callable:
  `recorded = []; run_report(..., on_chain_fetch=lambda year, out: recorded.append((year, out)))`.
- Patching policy after the refactor (r1 F2): tests may still patch collaborators that have NO
  injection seam (`load_koinly_crypto_report`, `OnChainThSubstituter`, `BerachainProcessor`,
  `load_contracts`, `load_lp_snapshot`); but at THEIR OWNING MODULE (e.g.
  `tax_reporting.application.run_report`, where the moved imports live), never on
  `tax_reporting.main`. Retargeted tests must not patch `tax_reporting.main` at all.
- `fetcher=None`/`on_chain_fetch=None` means "skip the on-chain fetch"; the single policy, testable
  without env tricks. `run_report` still emits the "No tax year resolved for on-chain fetch"
  WARNING when applicable (DI-9 path), and wraps the injected call in the broad
  `except Exception` soft-fail (DI-1).

No behavior changes: same log lines (level + message), same degrade semantics, same outputs
(`extract.xlsx` cell-identical, rollover CSV byte-identical on the example fixtures).

## Evaluation Criteria

**Quality dimensions:**
- Correctness (no behavior drift): full suite green before/after; example-fixture outputs identical
  pre/post refactor (xlsx compared cell-content-wise per repo precedent for timestamp-bearing xlsx;
  `shares-leftover.csv` byte-identical).
- Maintainability: `grep -n "getenv\|environ" src/tax_reporting/main.py` matches only inside the
  composition root; `src/tax_reporting/application/run_report.py` has zero `getenv`/`environ`/
  `configparser`/`argparse` references; `PLR0912`/`PLR0915` noqa removed from the orchestrator;
  `_main` and `run_report` each < ~120 lines; `main.py` and `run_report.py` each < 500 lines.
- Testability/hermeticity: retargeted pipeline tests use zero `monkeypatch.setattr` on
  `tax_reporting.main` module attributes for collaborators that are now parameters; hermeticity
  validation commands from `2026-08-16-test-hermeticity-guards` still pass (guards untouched).

**Done when:**
- All plan checkboxes `[x]`; Validation Commands block passes end-to-end on the branch.
- Backlog file moved to `docs/history/backlog/completed/`.

**Ship when:**
- None; local-only repo; nothing is deployed or handed to another team.

## Review Scope

**Explicit must-fix**; findings on these paths are always in scope (review and fix if valid):

**Production code:**
- `src/tax_reporting/application/run_report.py` *(new)*
- `src/tax_reporting/main.py`

**Tests:**
- `tests/unit/application/test_run_report.py` *(new)*
- `tests/unit/application/test_main_koinly_directory.py`
- `tests/unit/application/test_main_on_chain_wiring.py`
- `tests/unit/application/test_main_composition_root.py` *(new; env-gate/config-error tests relocated from the above as needed)*
- `tests/end_to_end/test_on_chain_bera_opted_in.py`
- `tests/unit/test_cli.py`

**Documentation:**
- `README.md` (architecture/entry-point description only)
- `AGENTS.md` (Testing section note pinning `BERA_CHAIN_API_KEY` in `main.py`; re-anchor to the
  composition root)
- `docs/history/backlog/2026-08-16-main-composition-root-decomposition.md` (move to `completed/`)

**Plan-related extension**; implementation and review may change files not listed above. Treat a
finding as in scope when it is **causally related to this plan**: it implements or completes a plan
task, fixes a regression introduced by plan work, closes wiring or docs implied by an explicit
must-fix change, or contradicts a contract the plan changed (e.g. a stale import of a helper moved
to `run_report.py`, or a conftest fixture that forwards `**overrides` into a changed constructor).
If the link to the plan is weak or speculative, drop as out of scope with a one-line reason.

**Out of scope; reject unless plan-related:**
- `tests/conftest.py` hermeticity guard fixtures (`_forbid_network`, env-pin autouse, audit hook):
  tripwires from the guards plan; only import/name adjustments caused by moved symbols are in scope.
- `src/tax_reporting/application/on_chain_th_substitution.py`; `maybe_substitute` was already
  decomposed; only its call-site move is in scope.
- `docs/maintenance/development_lessons.md`; no new lessons are authored by this plan.

## Design Invariants (CR Guard)

- **Byte-identical outputs**: `extract.xlsx` cell-identical and rollover CSV byte-identical on the
  example fixtures, pre/post refactor. Full suite green before and after. Rationale: staged
  replacement per `plan_quality_guidelines.md`; the refactor rides on the characterization net.
- **DI-3 env gate**: `os.getenv("BERA_CHAIN_API_KEY")` is read exactly once, in the composition
  root, at construction time. `run_report` must not read env. The "not set" WARNING moves to the
  root and fires in the same runs it fires today (i.e. whenever the gate is evaluated and the var
  is absent; including runs where a tax year was resolved).
- **DI-1 degrade template preserved, scope intact**: the broad `except Exception` soft-fail covers
  ONLY the collection fetch call (`run_on_chain_fetch` / the injected callable), never the opted-in
  TH parse path. The `ConfigurationError` re-raise clause and the M1 fail-loud wrap
  (`isinstance(exc, (ReportGenerationError, ConfigurationError))` → re-raise; else wrap) move
  verbatim into `run_report`.
- **DI-9 defensive year resolution**: `tax_jurisdiction.fiscal_year if tax_jurisdiction is not
  None else tax_year_hint` (both the TH-substitution `on_chain_year_for_th` and the fetch
  `on_chain_year`) must survive the move; a `None` jurisdiction still cannot raise `AttributeError`.
- **Audit-trail logging block**: the pre-config → config-load → re-configure sequence with its
  comments (r1 review F1 rationale) stays in the composition root, byte-equivalent ordering.
  Design Invariant 9 (config FIRST, logging configured ONCE with the resolved level) holds.
- **STRICT timezone guard**: `_load_crypto_tax_report`'s jurisdiction/timezone fail-fast and its
  `ConfigurationError`-propagation / `FileProcessingError`-degrade contract move unchanged.
- **Guards plan tripwires unchanged**: no edits to the hermeticity guards, their validation
  commands, or `tests/unit/test_test_hermeticity.py` beyond mechanical import fixes.
- **Env-gate move is observable-equivalent**: today the "BERA_CHAIN_API_KEY not set" WARNING fires
  only when a tax year was resolved (it sits inside the `else` of the year check). Moving it to
  construction time changes WHICH runs emit it (it may now fire when no year is resolved too).
  This widening is accepted and must be pinned by a test; if review flags it as drift, the
  fallback is to keep the warning inside `run_report` on the `on_chain_fetch is None` branch
  instead; flag to the user before choosing.

## Validation Commands

```bash
# 0. Anchored to the repo root
REPO="$(git rev-parse --show-toplevel)"

# 1. Full suite (hermetic; the BERA env pin autouse fixture stays active)
( cd "$REPO" && BERA_CHAIN_API_KEY= uv run pytest )

# 2. Env reads live ONLY in the composition root; orchestrator is environment-free
( cd "$REPO" && grep -n "getenv\|environ" src/tax_reporting/main.py ) \
  && ! ( cd "$REPO" && grep -n "getenv\|environ\|configparser\|argparse" src/tax_reporting/application/run_report.py ) \
  || { echo "FAIL: env/config/argv reads outside the composition root"; exit 1; }

# 3. Complexity noqa removed from the orchestrator (presence of the noqa = fail)
if ( cd "$REPO" && grep -n "PLR0912\|PLR0915" src/tax_reporting/application/run_report.py ); then
  echo "FAIL: orchestrator still carries PLR0912/PLR0915 noqa"; exit 1
fi

# 4. Size gates: composition root + orchestrator under the AGENTS.md orchestration budget
( cd "$REPO" && uv run python - <<'EOF'
import ast, sys
for path, fn_name, limit in [
    ("src/tax_reporting/main.py", "_main", 120),
    ("src/tax_reporting/application/run_report.py", "run_report", 120),
]:
    tree = ast.parse(open(path).read())
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == fn_name)
    size = fn.end_lineno - fn.lineno + 1
    assert size <= limit, f"{path}:{fn_name} is {size} lines (limit {limit})"
    print(f"{path}:{fn_name} = {size} lines OK")
EOF
)

# 5. Retargeted tests no longer reference the tax_reporting.main module at all
#    (covers monkeypatch.setattr, mock.patch string form, and the two-arg
#    setattr(module_obj, "attr") idiom by banning the import itself; r2 F4).
#    setenv/delenv on the composition-root env seam remains allowed.
if ( cd "$REPO" && grep -rn "tax_reporting.main\|from tax_reporting import main" \
    tests/unit/application/test_main_koinly_directory.py \
    tests/unit/application/test_main_on_chain_wiring.py \
    tests/end_to_end/test_on_chain_bera_opted_in.py ); then
  echo "FAIL: tax_reporting.main references survive in retargeted tests"; exit 1
fi

# 6. Byte-identical outputs on the example fixtures (xlsx cell-wise, CSV byte-wise):
#    regenerate live outputs, then compare against the Task 1 baseline snapshot.
( cd "$REPO" && uv run tax-reporting --example \
  && uv run python docs/tmp/compare_example_outputs.py docs/tmp/baseline-main-decomposition )

# 7. Hermeticity guards from 2026-08-16-test-hermeticity-guards still pass
( cd "$REPO" && BERA_CHAIN_API_KEY= uv run pytest tests/unit/test_test_hermeticity.py -q )
```

## Documentation Impact Assessment

- `README.md`: architecture/entry-point prose mentions the pipeline living in `main.py`; update to
  name `run_report.py` and the composition-root split (architecture section only; no new config).
- `AGENTS.md` Testing section: the hermeticity note references the `BERA_CHAIN_API_KEY`
  production gate in `main.py`; re-anchor it to the composition-root split (grep the section
  first for the current wording; do not assume a line-number anchor exists; r2 F2)
- No new config properties, metrics, or workflow steps; no runbook content.
- Backlog file moves to `docs/history/backlog/completed/` on completion (its own stated workflow).

### Task 1: Baseline characterization snapshot + comparison helper

Files:
- `docs/tmp/compare_example_outputs.py` *(new; gitignored scratch, not committed)*

- [x] Author `compare_example_outputs.py` with an explicit two-path contract (r1 F6):
  `compare_example_outputs.py <snapshot_dir>` compares the GIVEN snapshot dir against the LIVE
  `resources/result/example/` outputs; `shares-leftover.csv` byte-wise, `extract.xlsx` via
  openpyxl cell-content iteration over all sheets/cells (timestamps excluded; repo precedent from
  the on-chain plan's byte-identical checks). It must fail if either path is missing or empty
  (no self-comparison, no always-pass), and exits non-zero on any difference with a per-sheet diff
  summary.
- [x] On master checkout (before any edit), run `uv run tax-reporting --example`, then copy
  `resources/result/example/` into `docs/tmp/baseline-main-decomposition/`; immediately verify the
  helper by tampering one snapshot cell and confirming it exits non-zero (guard against a
  false-pass gate), then restore; record suite result: `BERA_CHAIN_API_KEY= uv run pytest`
  → expect GREEN (2117 tests).
- [x] Commit: `chore: baseline snapshot for main composition-root decomposition` *(docs/tmp is
  gitignored; nothing to commit; just record the baseline exists before editing src/)*

### Task 2: Extract `run_report` into `application/run_report.py`; `_main` becomes the composition root

Files:
- `src/tax_reporting/application/run_report.py` *(new)*
- `src/tax_reporting/main.py`
- `tests/unit/application/test_run_report.py` *(new)*

Pure refactor (no behavior change); characterization-first. KNOWN-BREAKING SEAM (r1 F1): moving
the pipeline body orphans every `tax_reporting.main` patch site in the existing suite
(`parse_ib_export_all`, `calculate_fifo_gains`, `export_rollover_file`, `generate_tax_report`,
`load_koinly_crypto_report`, `_resolve_koinly_directory`, `_infer_tax_year_hint_from_ib_data`).
An un-retargeted patch does not fail loudly; it silently stops intercepting and lets the real
loader run inside the characterization net. Therefore Task 2 MUST retarget those patch sites in
the SAME commit as the extraction, and the "suite GREEN" gate below is conditional on that
retargeting.

- [x] `TestRunReport#test_no_env_reads_is_static`; given the imported `run_report` module's source
  (via `inspect.getsource`), expects no `getenv`, `environ`, or `import os` occurrence; a
  static boundary check (r1 F7; the runtime global-`os.getenv`-sabotage variant is brittle because
  unrelated third-party getenv calls would false-fail)
- [x] `TestRunReport#test_injected_fetch_called`; given a non-None `on_chain_fetch` callable and a
  config whose fiscal year resolves, expects the callable is invoked exactly once with
  `(fiscal_year, output_dir)` and its result is discarded
- [x] `TestRunReport#test_injected_fetch_soft_fail`; given an `on_chain_fetch` callable raising
  `RuntimeError("boom")`, expects a WARNING log "On-chain fetch failed: boom..." and the run still
  completes and writes `extract.xlsx` (DI-1 preserved at the new call site)
- [x] `TestRunReport#test_fetch_skipped_when_none`; given `on_chain_fetch=None` and caplog at
  WARNING, expects no "On-chain fetch failed" log and no fetch-attempt log; completes normally
- [x] `TestRunReport#test_no_tax_year_warning`; given a tmp source directory with NO Koinly
  subdirectory, a synthetic IB CSV containing dividend rows ONLY (no trades →
  `tax_year_hint` None), and `app_config=None`, expects the "No tax year resolved for on-chain
  fetch" WARNING (DI-9) and successful completion (r1 F3: with a Koinly directory present the
  STRICT timezone guard would raise `ConfigurationError` before the year check; the fixture must
  be Koinly-free)
- [x] Run new tests → expect RED: `uv run pytest tests/unit/application/test_run_report.py`
- [x] Create `run_report.py` with `run_report(source_file, output_dir, app_config,
  on_chain_fetch, logger) -> None` (jurisdiction derived inside; r1 F4) containing the
  verbatim-moved pipeline body
  (validation, IB parse, FIFO, rollover export, crypto block incl. TH substitution and its M1
  wrap, `generate_tax_report`, injected-fetch block, final logging + `print`). Move the private
  helpers listed in the Gist. `OnChainThSubstituter` construction stays inside `run_report`
  (its rpc-url input arrives via the injected `app_config.tax_jurisdiction`).
- [x] Reduce `_main` to: defaults, audit-trail logging block (verbatim), config load + error
  mapping (verbatim), single `os.getenv("BERA_CHAIN_API_KEY")` read binding
  `functools.partial(run_on_chain_fetch, api_key=key)` or `None` (+ the "not set" WARNING at
  construction time; see CR Guard on the accepted widening), then `run_report(...)`.
- [x] Retarget every existing patch site on a moved symbol in `tests/`; both
  `monkeypatch.setattr(<main module>, ...)` AND `unittest.mock.patch("tax_reporting.main.<sym>")`
  (test_cli.py uses the latter form; r2 F1); to `tax_reporting.application.run_report` in the
  SAME commit (grep first:
  `grep -rnE "setattr|patch\(" tests/ | grep -E "parse_ib_export_all|calculate_fifo_gains|export_rollover_file|generate_tax_report|load_koinly_crypto_report|_resolve_koinly_directory|_infer_tax_year_hint"`;
  each hit must be retargeted or the test rewritten to injection; this includes the 15
  `patch("tax_reporting.main.<sym>")` sites in `tests/unit/test_cli.py`, which cannot wait for
  Task 6 because they fail loudly the moment the symbols move)
- [x] Run new tests → expect GREEN; full suite → expect GREEN **only after** the seam
  retargeting above (before it, the moved-symbol tests are expected RED/silently-unpatched.
  that intermediate state must not be committed)
- [x] Run Task 1 comparison helper → outputs identical to baseline
- [x] Commit: `refactor: extract injectable run_report orchestrator; _main becomes composition root`

### Task 3: Retarget Koinly-directory unit tests to `run_report`

Files:
- `tests/unit/application/test_main_koinly_directory.py`

- [x] Rewrite the 17 tests to call `run_report` with directly-constructed
  `Config`/`TaxJurisdictionConfig` objects and tmp_path Koinly layouts; year-mismatch,
  fiscal-year-hint, and legacy-layout assertions keep their exact log-message and skip/return
  expectations (behavior assertions unchanged; only the driving seam changes)
- [x] Any test that specifically exercises config-LOADING behavior (not pipeline behavior) moves to
  `tests/unit/application/test_main_composition_root.py` *(new)* driving `_main` with a real
  tmp config.ini; no loader patching
- [x] Run → expect GREEN; grep confirms zero `monkeypatch.setattr` on `tax_reporting.main`
  attributes in this file
- [x] Commit: `test: drive Koinly-directory cases via run_report with injected config`

### Task 4: Retarget on-chain wiring tests to the injected fetch callable

Files:
- `tests/unit/application/test_main_on_chain_wiring.py`
- `tests/unit/application/test_main_composition_root.py` *(new)*

- [x] Replace the `_Recorder` + `monkeypatch.setattr(main, "run_on_chain_fetch", ...)` pattern with
  a plain injected callable recording `(year, output_dir)`; gate-on/gate-off wiring assertions
  (fetch called iff key present) become composition-root tests in
  `test_main_composition_root.py` driving `_main` with `monkeypatch.setenv`/`delenv` (the one
  legitimate env seam)
- [x] `TestMainCompositionRoot#test_env_key_binds_fetcher`; given `BERA_CHAIN_API_KEY=x` in env
  and `run_report` monkeypatched to capture kwargs, expects `on_chain_fetch` is a non-None partial
  over `run_on_chain_fetch` with `api_key="x"`
- [x] `TestMainCompositionRoot#test_no_env_key_yields_none_fetcher_and_warning`; given the var
  deleted, expects `on_chain_fetch is None` and the "BERA_CHAIN_API_KEY not set" WARNING
  (pins the CR-Guard-accepted construction-time widening)
- [x] Run → expect GREEN
- [x] Commit: `test: on-chain wiring via injected fetcher; env gate pinned at composition root`

### Task 5: Retarget the opted-in on-chain e2e suite

Files:
- `tests/end_to_end/test_on_chain_bera_opted_in.py`
- `tests/unit/application/test_main_composition_root.py` *(new; hosts the relocated `main()`-level e2e)*

- [x] Rewrite the 15 tests to drive `run_report` with synthetic fixtures under tmp_path (committed
  `resources/source/example/<year>/koinly/` scenarios where they exist; crypto tests MUST use
  committed synthetic data per AGENTS.md); collaborators with no injection seam
  (`load_contracts`, `load_lp_snapshot`, `load_koinly_crypto_report`,
  `OnChainThSubstituter`/`BerachainProcessor`) are patched at their OWNING module per the Gist
  patching policy (r2 F3; they are not `run_report` parameters); M1
  fail-loud assertions (opted-in parse failure → `ReportGenerationError`, message names the
  wallet and the removal remedy) keep their exact match strings
- [x] Keep one `main()`-level e2e with the env pinned; place it in
  `tests/unit/application/test_main_composition_root.py` (outside gate #5's file set, which bans
  `tax_reporting.main` imports entirely; guards tripwire overlap is intentional)
- [x] Run → expect GREEN; grep confirms zero `monkeypatch.setattr` targeting the
  `tax_reporting.main` module (owning-module patches for seam-less collaborators per the Gist
  patching policy are allowed; env pinning via setenv/delenv allowed)
- [x] Commit: `test: opted-in on-chain e2e driven by run_report with injected fakes`

### Task 6: Slim `test_cli.py` patching; keep composition-root coverage

Files:
- `tests/unit/test_cli.py`

- [x] Keep `cli()`/`main()` as the driven surface (it IS the composition root); replace
  loader/orchestrator monkeypatching with a single `run_report` seam patch where tests only need
  "main wired through"; argv/validation tests unchanged
- [x] Run → expect GREEN
- [x] Commit: `test: cli tests patch only the run_report seam`

### Task 7: Complexity budget, noqa removal, docs, backlog archival

Files:
- `src/tax_reporting/application/run_report.py`
- `src/tax_reporting/main.py`
- `README.md`
- `AGENTS.md`
- `docs/history/backlog/2026-08-16-main-composition-root-decomposition.md`

- [x] Confirm `PLR0912`/`PLR0915` noqa absent from `run_report.py`; if `run_report` still trips
  either lint, split cohesive stages (config-decided crypto block, report write) into private
  helpers in the same module; no behavior change, helper extraction follows the
  count-all-branches rule before writing each task-level split
- [x] Update `README.md` architecture prose: `run_report.py` orchestrator + thin `main.py`
  composition root; entry-point flags unchanged
- [x] Update `AGENTS.md` Testing note: the hermeticity description referencing the
  `BERA_CHAIN_API_KEY` production gate in `main.py` is re-anchored to the composition-root
  function name (grep the section first; do not assume a line-number anchor exists; r1 F5)
- [x] `git mv docs/history/backlog/2026-08-16-main-composition-root-decomposition.md
  docs/history/backlog/completed/`
- [x] Commit: `docs: main decomposition; architecture prose, AGENTS env-gate anchor, backlog archival`

### Task 8: Final validation

Files:
- (no edits; verification only)

- [x] Run the full Validation Commands block top-to-bottom (suite, env-read grep, noqa grep, size
  gates, patch grep, output comparison vs Task 1 baseline, hermeticity tripwires) → all pass
- [x] `git diff master..HEAD --stat` sanity: only Review Scope files touched; any extra file has a
  plan-related justification recorded in the commit message
- [x] Commit (if any fixups): `chore: final validation fixups for main decomposition`
