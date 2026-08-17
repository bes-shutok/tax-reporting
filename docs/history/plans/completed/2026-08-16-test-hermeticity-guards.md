# Plan: Test-Suite Hermeticity Guards (env / network / personal-data)

Audit source: in-session audit 2026-08-16 (`docs/tmp/plan-requirements-test-hermeticity-guards.md`).

Plan review: docs/history/reviews/2026-08-16-plan-review-test-hermeticity-guards-r4.md (latest, ready) · r3 · r2 · r1

## Terms

- **DI-3 env gate**: the deliberate production design where `main.py` reads `os.getenv("BERA_CHAIN_API_KEY")` to enable the optional on-chain fetch. Correct for production; the hazard is tests inheriting it from the developer's shell.
- **Audit-hook path guard**: `tests/unit/test_on_chain_tests_no_personal_data.py`, spawns ONE subprocess that installs a `sys.addaudithook` open-monitor and runs guarded test modules, failing if any opens `resources/{source,result}/<segment != example>/...`.
- **Env-pin fixture**: a function-scoped autouse fixture in `tests/conftest.py` that deletes `BERA_CHAIN_API_KEY` before every test.
- **Network guard**: an autouse fixture that raises `AssertionError` on any outbound DNS resolution or socket connect during a test, unless the test is marked `@pytest.mark.network`.
- **Guarded modules**: the module set the audit-hook path guard runs inside its probe subprocess.

## Gist & Examples

**What changes:** The pytest suite becomes environment-invariant. Three test-infrastructure guards are added (production code is untouched): (1) an autouse fixture deletes `BERA_CHAIN_API_KEY` before every test so the DI-3 env gate inside `_main` never activates during tests; (2) an autouse socket guard turns any outbound DNS lookup or TCP connect into a loud `AssertionError` unless the test opts in with `@pytest.mark.network`; (3) the existing audit-hook path guard is promoted from opt-in (`RUN_AUDIT_GUARD=1`) to always-on, and its guarded-module set is extended with the two `_main`-calling test files its globs currently miss (`tests/unit/test_cli.py`, `tests/unit/application/test_crypto_reporting.py`, the opted-in e2e file already matches the `test_*bera*` glob).

**Why needed:** The user's `.zshrc` exports `BERA_CHAIN_API_KEY`. Every test that calls `_main()` without pinning the env (3 files: `tests/unit/test_cli.py`, `tests/unit/application/test_crypto_reporting.py`, `tests/end_to_end/test_on_chain_bera_opted_in.py`, the last fakes `getenv` in only one of its call sites) then performs a live Etherscan V2 fetch, reads the gitignored real wallet registry `resources/source/<year>/chains.json`, burns API quota, and takes ~9s per test at ~5% CPU, while the same suite runs green and fast in the agent shell (no key), which is also why five code-review rounds and the opt-in path guard never saw it. (`tests/unit/application/test_main_koinly_directory.py` was initially suspected but verified NOT to call `_main`, an early grep matched `via_main(`.)

**Example input:** `zsh -i -c 'uv run pytest tests/unit/test_cli.py -q'` (interactive shell, real key present), before: 3 tests / ~18s wall, live HTTP to Etherscan, real `chains.json` opened.

**Example output:** same command after this plan, 3 tests / <1s, zero outbound sockets, `chains.json` never opened, identical PASS result.

**Edge cases handled:**
- `_main` wraps the fetch in a broad `except Exception` (DI-1 degrade template), so a socket-guard `AssertionError` inside `_main` would be *swallowed into a warning*, the env-pin fixture is the primary gate; the socket guard is a tripwire for paths without a broad except.
- Tests that legitimately need the key set it via `monkeypatch.setenv` in the test body, which runs after the autouse fixture and therefore wins.
- The audit guard must not recurse into itself (already excluded) and its probe subprocess also loads `tests/conftest.py`, so both new guards apply inside the probe consistently.
- `--strict-markers` requires the `network` marker registered in `pyproject.toml` before first use.

## Evaluation Criteria

**Quality dimensions:**
- correctness (hermeticity): deterministic RED→GREEN tests for each of the three guards; full suite green with `BERA_CHAIN_API_KEY=dummy` exported.
- performance: default full suite within ~+1.5s of the measured baseline (2108 passed, 1 skipped in 2.70s at plan time; the promoted audit-guard subprocess costs ~1.2–1.5s).
- maintainability: `network` marker registered and described in `pyproject.toml`; lesson recorded in `development_lessons.md`; AGENTS.md Testing section states the hermeticity contract.

**Done when:**
- All new guard tests pass; `uv run pytest -q` is green with **0 skipped** (the audit-guard skip disappears).
- `BERA_CHAIN_API_KEY=dummy uv run pytest -q` is green (the old live path is provably dead in tests).
- `git diff master..HEAD --stat` shows no changes under `src/`.

**Ship when:**
- User re-times `uv run pytest` in their own interactive terminal (the only environment with the real key) and confirms the ~9s/test behavior is gone.
- ai-playbook review-panel hermeticity addition lands as the immediate follow-up in this session (not a task of this plan).

## Review Scope

**Explicit must-fix**; findings on these paths are always in scope (review and fix if valid):

**Production code:** none (guards are test infrastructure; `src/` is frozen).

**Config:**
- `pyproject.toml` (marker registration only)

**Tests:**
- `tests/conftest.py`
- `tests/unit/test_test_hermeticity.py` *(new)*
- `tests/unit/test_on_chain_tests_no_personal_data.py`

**Documentation:**
- `docs/maintenance/development_lessons.md`
- `AGENTS.md`

**Plan-related extension**; implementation and review may change files not listed above. Treat a finding as in scope when it is **causally related to this plan**: it implements or completes a plan task, fixes a regression introduced by plan work, closes wiring or docs implied by an explicit must-fix change, or contradicts a contract the plan changed. If the link to the plan is weak or speculative, drop as out of scope with a one-line reason.

**Out of scope; reject unless plan-related:**
- `src/tax_reporting/**`; the DI-3 env gate and fetch behavior are production design (deliberate) and must not change.
- `tests/unit/application/test_main_on_chain_wiring.py`, `tests/unit/application/test_on_chain_fetcher.py`, `tests/integration/test_on_chain_fetch_integration.py`, `tests/unit/infrastructure/test_rpc_client.py`; already hermetic via seams, verify they still pass, do not refactor them.
- ai-playbook skill files (`review-panel-selection.md` etc.); handled as a separate follow-up change in this session.

## Design Invariants (CR Guard)

1. **Production frozen.** No file under `src/` changes; `main.py:358` env-gate semantics are exactly preserved (guards live under `tests/` plus the `pyproject.toml` markers list).
2. **Env-pin is primary, socket guard is tripwire.** Because `_main` swallows exceptions from the fetch path (DI-1), only the env-pin actually prevents the fetch; the socket guard must not be treated as the fix for that path (it cannot fail the test through the broad except).
3. **Fail-closed guard promotion.** The audit-hook path guard runs by default; the only opt-out is an explicit `SKIP_AUDIT_GUARD=1` (mirrors `-m "not slow"` explicit deselection, not a silent default).
4. **Opt-in network only via marker.** No env-var bypass for the socket guard; `network` marker is registered (strict-markers) and documented in the markers list.
5. **Existing hermetic tests unchanged.** Wiring tests faking `os.getenv` and seam-patched client tests must pass without edits; any need to edit them is a defect of the guards, not of those tests.
6. **Suite summary change is expected.** Default run goes from "N passed, 1 skipped" to "N passed, 0 skipped" (the skip was the opt-in audit guard itself).

## Validation Commands

```bash
# 1. Full suite green (exit code checked), audit guard no longer skipped (fail-closed block)
uv run pytest -q > /tmp/suite.txt 2>&1 || { tail -5 /tmp/suite.txt; echo "BAD: suite not green"; exit 1; }
tail -1 /tmp/suite.txt
if grep -q "skipped" /tmp/suite.txt; then echo "BAD: audit guard still skipped"; exit 1; fi

# 2. Env simulation: suite must be green with the key exported (old live path dead)
BERA_CHAIN_API_KEY=dummy uv run pytest -q || exit 1

# 3. User-shell simulation: interactive zsh env no longer pays the fetch (was ~9s/test; unbounded zsh -i hang is an accepted, visible risk)
T0=$SECONDS; zsh -i -c 'uv run pytest tests/unit/test_cli.py tests/end_to_end/test_on_chain_bera_opted_in.py -q' || exit 1
ELAPSED=$((SECONDS - T0)); echo "elapsed=${ELAPSED}s"; [ "$ELAPSED" -lt 15 ] || { echo "BAD: interactive-shell run still slow"; exit 1; }

# 4. Network marker registered (strict-markers contract)
uv run pytest --markers 2>/dev/null | grep -F "network:" || { echo "BAD: network marker missing"; exit 1; }

# 5. Production frozen vs master (fail-closed: a missing ref or git error must not read as GOOD)
BASE_DIFF=$(git diff master...HEAD --name-only); GIT_RC=$?
if [ "$GIT_RC" -ne 0 ]; then echo "BAD: git diff failed (missing ref?)"; exit 1; fi
if printf '%s\n' "$BASE_DIFF" | grep -F "src/"; then echo "BAD: src/ touched"; exit 1; else echo "GOOD: src/ untouched"; fi

# 6. No stray env-pin/socket-guard references outside conftest + guard tests (single source; conftest holds the pin fixture by design)
if grep -rln "BERA_CHAIN_API_KEY" tests/ | grep -v "conftest\|test_test_hermeticity\|test_main_on_chain_wiring\|test_on_chain_bera_opted_in\|test_on_chain_tests_no_personal_data"; then echo "BAD: unexpected pin site"; exit 1; else echo "GOOD: pin sites as planned"; fi
```

### Task 1: Env-pin autouse fixture (RED → GREEN)

Files:
- `tests/unit/test_test_hermeticity.py` *(new)*
- `tests/conftest.py`

- [x] `TestEnvPin#test_import_time_api_key_removed_by_fixture`; given `BERA_CHAIN_API_KEY` set at module import time (simulating the user's shell) and restored at module teardown, expects `os.environ` does NOT contain the key inside the test body
- [x] `TestEnvPin#test_explicit_setenv_in_body_wins`; given a test body calling `monkeypatch.setenv("BERA_CHAIN_API_KEY", "opt-in")` after the autouse fixture ran, expects `os.environ["BERA_CHAIN_API_KEY"] == "opt-in"` (ordering guarantee: explicit opt-in still possible)
- [x] `TestEnvPin#test_env_pin_fixture_registered_autouse`; given `tests/conftest.py`, expects a fixture named `_pin_hermetic_env` with `autouse=True` and `monkeypatch.delenv("BERA_CHAIN_API_KEY", raising=False)` (structural pin so the fixture cannot be silently disconnected; assert via source inspection of the conftest path)
- [x] Run → expect RED: `uv run pytest tests/unit/test_test_hermeticity.py -q` (fixture absent → import-time key survives → first test fails)
- [x] Write minimal implementation: autouse fixture `_pin_hermetic_env(monkeypatch)` in `tests/conftest.py`, docstring citing the 2026-08-16 incident and the DI-3 env gate
- [x] Run → expect GREEN
- [x] Commit: `test: pin BERA_CHAIN_API_KEY off via autouse env fixture`

### Task 2: Network guard + registered `network` marker (RED → GREEN)

Files:
- `tests/unit/test_test_hermeticity.py`
- `tests/conftest.py`
- `pyproject.toml`

- [x] `TestNetworkGuard#test_unmarked_dns_resolution_blocked`; given a test without `@pytest.mark.network`, expects `socket.getaddrinfo("example.com", 443)` raises `AssertionError` matching `network` (guard fires before any syscall)
- [x] `TestNetworkGuard#test_unmarked_legacy_dns_blocked`; given `socket.gethostbyname("example.com")` and `socket.gethostbyname_ex("example.com")` without the marker, expects both raise `AssertionError` (legacy resolvers guarded too, not just `getaddrinfo`)
- [x] `TestNetworkGuard#test_unmarked_socket_connect_blocked`; given `socket.socket().connect(("127.0.0.1", 1))` without the marker, expects `AssertionError` naming the address (no real connect attempted)
- [x] `TestNetworkGuard#test_network_marker_opts_out`; given a test marked `@pytest.mark.network` connecting to `127.0.0.1:1`, expects the original `OSError` (connection refused) and NOT `AssertionError` (marker disables the guard; loopback connect is deterministic and external-network-free)
- [x] Register in `pyproject.toml` markers: `network: allows outbound network for deliberately-live tests (guard disabled)`
- [x] Run → expect RED (guard absent → DNS/connect succeed or raise non-AssertionError)
- [x] Write minimal implementation: autouse fixture `_forbid_network(request, monkeypatch)` in `tests/conftest.py`, returns early when `"network" in request.keywords`; otherwise monkeypatches `socket.getaddrinfo`, `socket.gethostbyname`, `socket.gethostbyname_ex`, and `socket.socket.connect` to raise `AssertionError(f"test attempted outbound network to {address}; mark @pytest.mark.network to allow")`
- [x] Run → expect GREEN; then full suite → expect GREEN (proves no existing test does outbound network)
- [x] Commit: `test: fail outbound network in tests unless marked network`

### Task 3: Promote audit-hook path guard to always-on; extend guarded modules

Files:
- `tests/unit/test_on_chain_tests_no_personal_data.py`

Test-infra change (concise action items, no production behavior):

- [x] Invert the gate: the audit probe test runs by default; `RUN_AUDIT_GUARD=1` remains accepted as a no-op alias (back-compat for documented CI invocation); add the only opt-out as `SKIP_AUDIT_GUARD=1` with a docstring note mirroring `-m "not slow"` explicit deselection (fail-closed preserved: absent env ⇒ guard runs)
- [x] Rewrite the guard module docstring: the "runs only when RUN_AUDIT_GUARD=1 … default run not slowed" paragraph becomes false after promotion, replace with the always-on contract + `SKIP_AUDIT_GUARD=1` opt-out
- [x] Also rewrite the audit test's METHOD docstring (the `Opt-in: skipped unless RUN_AUDIT_GUARD=1 … CI / pre-commit run it explicitly` contract text near `tests/unit/test_on_chain_tests_no_personal_data.py:178`) to the same always-on contract, a stale opt-in contract at either docstring site contradicts Design Invariant 3
- [x] Extend `_ON_CHAIN_TEST_PATHS` with explicit strings `tests/unit/test_cli.py` and `tests/unit/application/test_crypto_reporting.py` (the verified `_main` callers not matched by the `test_*on_chain*`/`test_*bera*` globs), with a comment naming the incident that motivated the extension. `tests/unit/application/test_main_koinly_directory.py` is deliberately NOT added: verified not to call `_main` (grep matched `via_main(` only).
- [x] `TestOnChainTestsNoPersonalData#test_synthetic_forbidden_open_detected`; given the guard test writing a tiny synthetic module to `tmp_path` at RUNTIME (module body calls `open("resources/source/2099/synthetic.json")`) and the probe subprocess running it via its absolute `tmp_path` argument, expects the probe reports the path in `AUDIT_HITS`. The open need not succeed, the audit event fires on the attempt, and the probe's `AUDIT_RC` will be NONZERO (2: the module-body open failure surfaces as a pytest collection error), so the assertion targets `AUDIT_HITS` only, never `rc == 0`. The module must NEVER be committed under `tests/` (it would pollute default collection, and a glob-matching name would make the always-on probe permanently flag its own synthetic violation, a permanently red suite)
- [x] Run → expect GREEN with `uv run pytest tests/unit/test_on_chain_tests_no_personal_data.py -q` showing the audit test PASSED (not skipped); verify `SKIP_AUDIT_GUARD=1` still skips explicitly
- [x] Commit: `test: audit guard always-on, guarded set covers _main callers`

### Task 4: Documentation

Files:
- `docs/maintenance/development_lessons.md`
- `AGENTS.md`

- [x] Before editing the lessons corpus, refresh the learn-class marker: `python3 ~/.ai-playbook/scripts/skill_gate.py --write-marker learn` (fail-loud; abort if it errors)
- [x] Add `development_lessons.md` entry: root cause (agent shell ≠ user shell; DI-3 env gate inherited by `_main`-calling tests, `test_cli.py`, `test_crypto_reporting.py`, `test_on_chain_bera_opted_in.py`, → live API + gitignored `chains.json` + ~9s/test at ~5% CPU; note the initial `via_main(` grep false-positive on `test_main_koinly_directory.py` as a methodology caution), the corrected diagnostic ladder (CPU-%-of-wall first → `zsh -i -c` reproduction → `env` diff + `grep -rn getenv src/` → both-direction causal proof), and the fix contract (env-pin primary; socket guard tripwire; always-on audit guard)
- [x] AGENTS.md Testing section: add one rule, the suite is hermetic: no ambient env vars, no outbound network (guard; `@pytest.mark.network` opt-in), no gitignored-data opens (always-on audit guard; `SKIP_AUDIT_GUARD=1` is the only opt-out)
- [x] Commit: `docs: hermeticity contract + env-dependent-test lesson`

### Task 5: Final validation (all guards together)

- [x] Run Validation Commands block 1–6 in order; all must pass
- [x] Confirm suite summary: "N passed, 0 skipped" with N ≥ 2108 (baseline before plan: 2108 passed, 1 skipped in 2.70s)
- [x] Commit (if anything drifted): `test: final hermeticity validation`, otherwise no-op

## Pre-computation bug pattern checks

- Temporal gating: env-pin (function-scoped, before body) must run BEFORE anything in the test body reads the env, guaranteed by fixture ordering (autouse setup precedes body); explicit `setenv` in body wins (later). No mid-test window where a body-read can see the import-time value.
- Error scope: the socket guard raises inside the attempted call, not asynchronously; `_main`'s broad except swallows it (Documented in invariants, tripwire only).
- Boundary: loopback `127.0.0.1:1` connect in the opt-out test is refused deterministically (port 1 unlistened), no external dependency, no flake.
- Empty/absent: `delenv(..., raising=False)` handles both "never set" (agent shell) and "set" (user shell) paths.
