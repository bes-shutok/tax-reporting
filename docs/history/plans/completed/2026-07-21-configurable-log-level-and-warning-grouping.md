# Plan: Configurable log level + warning grouping

Plan review: `docs/history/reviews/2026-07-21-plan-review-configurable-log-level-and-warning-grouping-r1.md` (r1: 3 Blocker + 5 Medium folded) · `…-r2.md` (r2: 9/9 r1 Fixed; 0 Blocker + 1 Medium + 3 Low folded) · `…-r3.md` (r3: 4/4 r2 Fixed; 0 Blocker + 1 Medium + 1 Low folded) · `…-r4.md` (r4: 2/2 r3 Fixed; 0 Blocker + 1 Medium folded) · `…-r5.md` (r5: **1 Blocker** root-logger gating + 1 Medium + 1 Low folded) · `…-r6.md` (r6: 3/3 r5 Fixed; 0 Blocker + 0 Medium + 1 Low folded; **ready=yes**).

## Terms

- **Console handler**: the `StreamHandler(sys.stdout)` attached in `configure_application_logging` (`src/tax_reporting/infrastructure/logging_config.py:38`); ephemeral UX output.
- **File handler**: the `FileHandler(logs/tax-reporting.log)` attached at `logging_config.py:48`; the permanent audit trail, hardcoded to `logging.DEBUG`.
- **Per-row warning**: a WARNING-level log line emitted inside a per-input-row loop (8 distinct patterns identified; ~1514 emissions on a real production run).
- **Aggregate summary warning**: a single WARNING emitted after a loop completes, naming the total count and distinct-key breakdown. Established pattern: `ogr_handler.py:130-136`, `crypto_reporting.py:887-892`.
- **Review list**: the user-facing Excel surface (`CryptoReviewEntry`, `CryptoFifoRealization(review_required=True)`, `DerivativesPnLEntry`). Many per-row warnings duplicate what the review list already shows.

## Gist & Examples

### Problem

Two connected issues with logging today:

1. **Hardcoded default.** The console log level is `"INFO"` in 5 separate code sites (`main.py:105`, `main.py:257`, `main.py:454`, `logging_config.py:15`, plus an orphaned `domain/constants.py:16 DEFAULT_LOG_LEVEL` that no code imports). The user cannot change verbosity without editing source or passing `--log-level` on every run. This plan consolidates all five into a single `DEFAULT_LOG_LEVEL` constant in `config.py`, used as the parser fallback, the `Config.log_level` dataclass default, and the `main.py` failure-path fallback.

2. **WARNING level is useless.** A real production run produces **1514 WARNING-level lines** from 8 repeating patterns. The top 4 patterns account for 92% of the noise:

| # | Count | Pattern | Source |
|---|---|---|---|
| A | 601 | "Capital gains row N for X has all-zero values. Added to review list..." | `crypto_reporting.py:802` |
| B | 322 | "Origin records disagree for X at X on N-N-N; returning unknown" | `token_origin.py:435` |
| C | 142 | "Duplicate tx_key X / source_type X for asset X acquisitions..." | `crypto_fifo/parsing.py:303` (+ consumptions `:324`) |
| D | 110 | "Possible untagged fee for unlisted asset X (Net Value N EUR)..." | `crypto/fee_filter.py:607` |
| E | 73 | "Row N: crypto_deposit of X has zero Net Value (EUR)..." | `crypto_fifo/parsing.py:622` |
| F | 71 | "No acquisition available at or before disposal date for X..." | `crypto_fifo/matching.py:272` |
| G | 28 | "FIFO pool exhausted for non-taxable X consumption..." | `crypto_fifo/matching.py:301` |
| H | 43 | "OGR row at (...) routed to derivatives by row type; no CG counterpart..." | `crypto/ogr_handler.py:346` |

Every one of these patterns ALSO writes a `CryptoReviewEntry` / `CryptoFifoRealization(review_required=True)` / `DerivativesPnLEntry` to the Excel review list, so the per-row WARNING duplicates what the report already says, ~1500 times.

### What changes

**Part A: Configurable log level (single source of truth):**

A new `log_level` key in the `[COMMON]` section of `config.ini`:

```ini
[COMMON]
TARGET CURRENCY = EUR
LOG_LEVEL = WARNING   ; console handler minimum; file always captures DEBUG
```

- Parsed in `load_configuration_from_file` next to `TARGET CURRENCY`; validated case-insensitively against `{DEBUG, INFO, WARNING, ERROR, CRITICAL}`; raises `ConfigurationError` on invalid value.
- Threads through `Config.log_level` → `_main()` → `configure_application_logging(level=...)`.
- CLI `--log-level` overrides when present; config value wins otherwise.
- Controls the **console handler only**. File handler stays hardcoded at `logging.DEBUG` (the audit trail). **Implementation-critical note (r5 finding #1):** the current `logging_config.py:26` sets the ROOT logger to `level`, which gates DEBUG at the root before it reaches the file handler, so the file handler's `setLevel(DEBUG)` is inert unless the root is also DEBUG. Task 1 must fix this by setting the root logger to `logging.DEBUG` unconditionally and letting the per-handler `setLevel` calls do the filtering. Without this fix, Part B's "per-row detail preserved at DEBUG in the file" promise is false at the new WARNING default.
- Removes the 5 hardcoded `"INFO"` literals + the orphaned `DEFAULT_LOG_LEVEL` constant; one source.

Before/after:
```
# BEFORE: user runs tax-reporting, gets 1514 WARNING lines on console, no way to persist a quieter setting
$ uv run tax-reporting
... 1514 WARNING lines ...

# AFTER: config.ini has LOG_LEVEL = WARNING; per-row detail moves to DEBUG (file only); console shows ~8 aggregate summaries
$ uv run tax-reporting
... ~8 WARNING summaries ...
# Full per-row detail still in logs/tax-reporting.log at DEBUG

# Override for one run:
$ uv run tax-reporting --log-level INFO
```

**Part B: Group 8 high-volume per-row warning patterns:**

For each pattern: downgrade the per-row emission to `logger.debug(...)` (preserved in the file at DEBUG), and add a single aggregate WARNING summary after the loop. Per-pattern approach:

- **A, C, H** (EASY): inline `Counter[str]` / counter declared above the loop; downgrade in-loop emission to DEBUG; emit one summary after the loop. Mirrors `ogr_handler.py:130-136` / `crypto_reporting.py:887-892`.
- **D** (fee_filter untagged fee): summary already exists at `fee_filter.py:619-620` (`"Surfaced %d suspect untagged network fees for manual review"`); just downgrade the per-row `fee_filter.py:607` to DEBUG.
- **G** (FIFO non-taxable exhausted): `partial_tx_keys` already accumulates these cases and is returned as `AssetFifoResult.partial_carryover_tx_keys`; emit a per-`(asset, platform)` summary at end of `compute_fifo_for_asset` when `partial_tx_keys` is non-empty.
- **E, F** (MEDIUM): thread a `Counter`/counter through one call layer (model on existing `parse_failures_by_asset`); downgrade in-loop emission to DEBUG; emit summary at the outer aggregator.
- **B** (HARD, 322 occurrences): `TokenOriginResolver.resolve()` is a leaf helper called from 2 unrelated loops (`crypto_reporting.py:841` and `fifo_helpers.py:325`). Add `self._disagreements: Counter[tuple[str, str, str]]` on the resolver; increment it instead of warning in the disagreement branch; add `log_and_reset_disagreements(scope)` method; each caller invokes it after its loop with a scope label (`"capital gains parse"` / `"FIFO rebuild"`).

The project rule "Data-loss conditions must be logged at warning+" is NOT violated: every affected row continues to be (a) logged at DEBUG in the file and (b) carried in the user-facing review list with full asset/date/row context. The aggregate WARNING preserves the warning-level audit signal on the console.

### Edge cases / motivation

- **Wiring order.** `configure_application_logging()` is currently called at `main.py:114` BEFORE `load_configuration_from_file()` at line 178. The plan must reorder: load config first (or call `configure_application_logging` a second time with the config-derived level after load). The chosen approach: reorder so config loads first, then logging configures once with the resolved level. A guard for the config-load failure path (`FileNotFoundError`/`OSError` at `main.py:182`) must still produce working logging at the default WARNING level.
- **Pattern B state leakage.** `TokenOriginResolver` instances are per-run, but the `Counter` must still be flushed by both callers, an unflushed non-empty counter is a bug. Defensive: `log_and_reset_disagreements` always clears.
- **Summary wording collisions with negative tests.** The aggregate summaries must NOT reuse per-row substrings that negative caplog tests grep for (esp. pattern D's "Possible untagged fee for unlisted asset"). Use distinct summary wording.
- **`AssetFifoResult` new field for pattern F** (`unmatched_taxable_count`). Any dataclass `**overrides` test helper must tolerate the new field.

## Evaluation Criteria

**Quality dimensions:**

- **Correctness**: existing test suite remains green (1802 tests at baseline). The 3 rewritten caplog tests still assert meaningful behavior (aggregate summary fires when expected, per-row detail reachable at DEBUG).
- **Single source of truth**: after the change, `grep -rn '"INFO"\|"WARNING"' src/tax_reporting/main.py src/tax_reporting/infrastructure/logging_config.py src/tax_reporting/domain/constants.py` returns NO hardcoded default level literals (the only acceptable occurrence is the validation set in config.py).
- **Configurability**: setting `LOG_LEVEL = ERROR` in config.ini silences all WARNING/INFO on console; CLI `--log-level DEBUG` overrides to show everything. Invalid value (`LOG_LEVEL = VERBOSE`) raises `ConfigurationError`.
- **Signal-to-noise**: on the user's real data (`tmp.txt` baseline = 1514 WARNING lines), a default run produces single-digit WARNING output (the 8 per-pattern summaries, only the ones whose count is non-zero).
- **Audit trail integrity**: per-row detail remains reachable in `logs/tax-reporting.log` at DEBUG for every converted pattern; the Excel review list for patterns A/D/E/F/H is unchanged in row count and content.
- **Maintainability**: a new project-guidelines rule documents the per-row-DEBUG + aggregate-WARNING convention so future contributors follow it.

**Release gates:**

- Full test suite green: `uv run pytest tests/`
- Real-data spot check: `uv run tax-reporting` produces < 10 WARNING lines on console (down from 1514); `--log-level DEBUG` run still shows all per-row detail.
- Manual Excel spot check: review list row counts for patterns A/D/E/F/H match baseline.
- `review-plan` gate: latest review artifact reports `ready=yes`, Blocker=0, Medium=0.

## Review Scope

**Explicit must-fix**; findings on these paths are always in scope (review and fix if valid):

**Production code:**
- `config.ini`
- `tests/config.ini`
- `src/tax_reporting/infrastructure/config.py`
- `src/tax_reporting/infrastructure/logging_config.py`
- `src/tax_reporting/domain/constants.py`
- `src/tax_reporting/domain/crypto_fifo.py`
- `src/tax_reporting/main.py`
- `src/tax_reporting/application/token_origin.py`
- `src/tax_reporting/application/crypto_reporting.py`
- `src/tax_reporting/application/crypto/fee_filter.py`
- `src/tax_reporting/application/crypto/ogr_handler.py`
- `src/tax_reporting/application/crypto/fifo_helpers.py`
- `src/tax_reporting/application/crypto_fifo/matching.py`
- `src/tax_reporting/application/crypto_fifo/parsing.py`

**Tests:**
- `tests/unit/infrastructure/test_config.py`
- `tests/unit/infrastructure/test_logging_config.py` *(new, houses the root-logger gating regression test from Task 1)*
- `tests/unit/test_cli.py`
- `tests/unit/application/test_fee_filter.py`
- `tests/unit/application/test_crypto_reporting.py`
- `tests/unit/application/test_crypto_fifo.py`
- `tests/unit/application/test_crypto_origin_resolver.py` *(add a new `TestTokenOriginResolverDisagreementCounter` class to this existing file, file already exists with substantial content; do NOT overwrite. r2 finding #2: there is NO existing `TestTokenOriginResolver` class; existing classes are `TestOriginResolverMultipleMatches`, `TestOriginResolverGracefulDegradation`, etc.)*
- `tests/unit/application/test_crypto_fifo.py` *(Pattern E/C parsing tests live in this file)*
- `tests/end_to_end/test_excel_report_generation.py`

**Docs:**
- `README.md`
- `docs/maintenance/project-guidelines.md`

**Plan-related extension**; implementation and review may change files not listed above. Treat a finding as in scope when it is **causally related to this plan**: it implements or completes a plan task, fixes a regression introduced by plan work, closes wiring or docs implied by an explicit must-fix change, or contradicts a contract the plan changed. If the link to the plan is weak or speculative, drop as out of scope with a one-line reason.

**Out of scope; reject unless plan-related:**
- Any DATA_DROPPED, PARSE_ERROR, INVARIANT_VIOLATION, or RECONCILIATION warning site NOT in the 8 patterns above. Those stay per-row WARNING.
- The file-handler level (`logging_config.py:49` stays `logging.DEBUG`).
- Any tax-law decision-point logic (`docs/maintenance/tax/decision_points/`).
- Crypto data-flow / FIFO correctness changes, this plan changes logging only.

## Design Invariants (CR Guard)

1. **Console-only control.** `LOG_LEVEL` controls the console handler only. The file handler remains hardcoded at `logging.DEBUG`. Rationale: the file is the project's permanent audit trail; the repo rules require data-loss conditions to be logged, and the file is where that record lives. Silencing the file would violate the spirit of the rule.
2. **CLI flag wins over config.** When `--log-level` is passed, it overrides the config-derived level. When absent, config wins. Rationale: CLI flags are for one-off overrides; config is the persistent preference.
3. **Per-row detail is preserved** at DEBUG in the file for every converted pattern. The conversion must never delete the per-row emission, only lower its level. Rationale: the aggregate summary is a count; the per-row context (asset, date, row index, reason) is the actual audit detail and must remain retrievable.
4. **Excel review list is unchanged.** The conversions only touch logging, not data flow. Patterns A/D/E/F/H/G write review entries/flags that must continue to appear in the user-facing output with identical content.
5. **`TokenOriginResolver.resolve()` return contract is unchanged.** It still returns `TokenOrigin`. The disagreement counter is instance state mutated as a side effect; `log_and_reset_disagreements(scope)` is the only way to observe and clear it. Rationale: changing the return type would ripple to every caller and test; instance state is the minimal disruption.
6. **Invalid `LOG_LEVEL` fails fast** with `ConfigurationError` at the `main.py` boundary. Rationale: matches existing pattern for `TAX_COUNTRY`/`IANA_TIMEZONE` (AGENTS.md: "invalid `[TAX JURISDICTION]` raises `ConfigurationError`"); silent degradation on a logging feature would be ironic. **Implementation note (r1 finding #1):** `config.py` does NOT import `ConfigurationError` and never has, its established convention is to raise plain `ValueError`/`KeyError`, which `main.py:187-190` already wraps via `except (ValueError, KeyError, configparser.Error) as exc: raise ConfigurationError(...)`. The `LOG_LEVEL` validation MUST follow this convention: raise `ValueError` inside `load_configuration_from_file`; the existing `main.py` wrapper produces the `ConfigurationError`. Do NOT add a `ConfigurationError` import to `config.py`.
7. **Case-insensitive value parsing.** `warning`, `Warning`, `WARNING` all valid; normalized to uppercase before use. Rationale: `configure_application_logging` already calls `.upper()` (`logging_config.py:26`); friendlier for hand-edited INI.
8. **`matching.py:280` is ONE shared emission for two taxable sub-branches** (pool-truly-exhausted at `:263` AND no-acquisition-at-date at `:271`). Patterns F and G cannot be downgraded independently by editing "the line 280 warning", the call must be SPLIT into two emissions, one per branch, before any level change. Rationale (r1 finding #3): verified by reading `matching.py:258-280`; the single `logger.warning(fifo_warning, asset, con.con.date, remaining)` is reached by both branch strings. Any plan task that says "downgrade the warning near `:280`" without first splitting the call will silently downgrade both branches.
9. **Wiring order: load config first, configure logging once, then run the IB/FIFO block.** Rationale (r1 finding #2): `main.py:114` (logging) precedes `main.py:178` (config) today, with 64 lines of `logger.info(...)` startup diagnostics between them (`:122-171`). Naively swapping the two loses those diagnostics. The reorder must be: (a) `load_configuration_from_file()` at the top of `_main()`; (b) on success, `configure_application_logging(resolved_level, log_file=log_file)` exactly once, then the existing IB/FIFO block; (c) on `(FileNotFoundError, OSError)`, `configure_application_logging("WARNING", log_file=log_file)` BEFORE the existing `logger.warning("Config file not found...")` so that warning is not lost; (d) on `(ValueError, KeyError, configparser.Error)` the existing `main.py:187-190` wrapper propagates `ConfigurationError` unconfigured (matches `_load_crypto_tax_report`'s pattern); (e) the `except MissingDecisionPointsError: raise` clause at `main.py:180-181` is PRESERVED (r2 finding #3, it's a separate re-raise and must not be dropped in the reorder; it propagates uncaught, which is correct).
10. **Pattern B flush ordering and clear-after-emit.** The shared `TokenOriginResolver` instance accumulates disagreements from BOTH call sites (`_parse_capital_gains_file` runs first at `crypto_reporting.py:337`, then `_rebuild_fifo_for_loan_affected_assets` at `:361`). The CG-parse flush MUST run before the FIFO-rebuild flush. `log_and_reset_disagreements` computes totals, emits WARNING, THEN clears, clear is unconditional but happens AFTER emit so a logging failure cannot lose state. Rationale (r1 finding #4).

## Validation Commands

```bash
# Single source of truth, no hardcoded default level literals in the wiring
# Exclude main.py:72 (the argparse choices=[...] list, which legitimately lists all 5 levels)
# and config.py (holds DEFAULT_LOG_LEVEL + the validation set, the ONE acceptable home).
grep -rn '"INFO"\|"WARNING"' src/tax_reporting/main.py src/tax_reporting/infrastructure/logging_config.py src/tax_reporting/domain/constants.py | grep -v 'choices=\['
# Expect: zero matches. The only acceptable occurrences in src/ are: (a) main.py:72 argparse
# choices list (excluded via grep -v), (b) config.py DEFAULT_LOG_LEVEL definition + validation set
# (excluded by not scoping the grep at config.py). After Task 1, main.py's failure-path call uses
# the imported DEFAULT_LOG_LEVEL constant, not a bare literal.

# Root-logger gating regression check (r5 finding #1), DEBUG must reach the file at any console level
uv run python -c "
import logging, tempfile
from pathlib import Path
from tax_reporting.infrastructure.logging_config import configure_application_logging
with tempfile.TemporaryDirectory() as td:
    logf = Path(td) / 'out.log'
    configure_application_logging(level='WARNING', log_file=logf)
    logging.getLogger('repro').debug('canary-debug-line')
    for h in logging.getLogger().handlers: h.flush()
    assert 'canary-debug-line' in logf.read_text(), 'DEBUG did not reach file, root-logger gating bug present'
    print('OK: DEBUG reaches file at console=WARNING')
"

# Config wiring, log_level threads from config.ini through to configure_application_logging
grep -n "log_level\|LOG_LEVEL" config.ini tests/config.ini src/tax_reporting/infrastructure/config.py src/tax_reporting/main.py

# Per-row emissions downgraded (sample one site per pattern)
grep -n "logger.debug" src/tax_reporting/application/crypto_reporting.py src/tax_reporting/application/token_origin.py src/tax_reporting/application/crypto_fifo/parsing.py src/tax_reporting/application/crypto_fifo/matching.py src/tax_reporting/application/crypto/fee_filter.py src/tax_reporting/application/crypto/ogr_handler.py | grep -E "all-zero|disagree|Duplicate tx_key|untagged fee|zero Net Value|No acquisition available|FIFO pool exhausted|routed to derivatives"

# Full test suite
uv run pytest tests/

# Real-data signal-to-noise check (console WARNING count)
uv run tax-reporting --log-level WARNING 2>&1 | grep -c WARNING
# Expect: single digits (down from 1514)

# Audit-trail preservation (per-row detail still in file at DEBUG)
uv run tax-reporting --log-level DEBUG 2>&1 | grep -c "all-zero values\|Origin records disagree\|Duplicate tx_key"
# Expect: counts match tmp.txt baseline for those patterns
```

### Task 1: Part A - Configurable log level wiring (RED→GREEN)

Files:
- `config.ini`
- `tests/config.ini`
- `src/tax_reporting/infrastructure/config.py`
- `src/tax_reporting/infrastructure/logging_config.py`
- `src/tax_reporting/domain/constants.py`
- `src/tax_reporting/main.py`

- [x] `TestConfigParsing#test_log_level_defaults_to_warning_when_absent`; given `config.ini` with no `LOG_LEVEL` key in `[COMMON]`, expects `Config.log_level == "WARNING"`.
- [x] `TestConfigParsing#test_log_level_reads_uppercase`; given `[COMMON] LOG_LEVEL = ERROR`, expects `Config.log_level == "ERROR"`.
- [x] `TestConfigParsing#test_log_level_normalizes_lowercase`; given `[COMMON] LOG_LEVEL = warning`, expects `Config.log_level == "WARNING"`.
- [x] `TestConfigParsing#test_log_level_invalid_raises_value_error`; given `[COMMON] LOG_LEVEL = VERBOSE`, expects `ValueError` (NOT `ConfigurationError`) with message naming `"VERBOSE"` and the 5 allowed levels. Rationale (r1 #1): `config.py` follows the convention of raising `ValueError`/`KeyError`; `main.py:187-190` wraps these into `ConfigurationError`. Verify end-to-end via a separate test that calls `main()` and asserts `ConfigurationError` propagates.
- [x] `TestConfigParsing#test_log_level_case_insensitive_invalid_still_raises`; given `[COMMON] LOG_LEVEL = verbose`, expects `ValueError` (case normalization happens before validation, but the value is still invalid).
- [x] `TestCliMain#test_invalid_log_level_surfaces_as_configuration_error`; given `config.ini` with `LOG_LEVEL = VERBOSE`, expects `main()` to raise `ConfigurationError` (proves the `main.py:187-190` wrapper converts the `ValueError` from `config.py`).
- [x] Run → expect RED: `uv run pytest tests/unit/infrastructure/test_config.py -k log_level`
- [x] Add `LOG_LEVEL = WARNING` to `[COMMON]` in `config.ini` and `tests/config.ini` (commented to explain "console handler minimum; file always captures DEBUG").
- [x] Add `log_level: str = "WARNING"` field to `Config` dataclass (`src/tax_reporting/infrastructure/config.py:75`).
- [x] Add a module-level constant `DEFAULT_LOG_LEVEL: Final[str] = "WARNING"` in `src/tax_reporting/infrastructure/config.py` (next to the `Config` dataclass), this is the SINGLE source for the default level. It is used both as the `Config.log_level` dataclass default AND as the parser fallback when `[COMMON] LOG_LEVEL` is absent AND as the failure-path fallback in `main.py` (see step 3 below). Rationale (r4 finding #1): without a named constant, step 3's failure-path `configure_application_logging("WARNING", ...)` would introduce a 6th hardcoded literal and the Validation Command grep would return non-zero; the constant consolidates all three uses to one symbol. Note (r5 #3): `Final` is not currently in `config.py`'s imports, add `from typing import Final` (already used in `domain/constants.py`). Verify with basedpyright before commit.
- [x] Parse `log_level` next to `TARGET CURRENCY` (`config.py:416`): `raw_level = config["COMMON"].get("LOG_LEVEL", DEFAULT_LOG_LEVEL)`; normalize via `raw_level.strip().upper()`; validate against `{"DEBUG","INFO","WARNING","ERROR","CRITICAL"}`; on mismatch raise `ValueError(f"Invalid LOG_LEVEL {raw_level!r} in [COMMON]; expected one of DEBUG, INFO, WARNING, ERROR, CRITICAL")` (NOT `ConfigurationError`, r1 finding #1; the existing `main.py:187-190` wrapper converts to `ConfigurationError`). Do NOT add a `ConfigurationError` import to `config.py`. Store the normalized uppercase value on `Config.log_level`.
- [x] Remove `DEFAULT_LOG_LEVEL = "INFO"` from `src/tax_reporting/domain/constants.py:16` (the constant is orphaned; Part A moves the single source to `config.py` as specified above).
- [x] Remove the default-arg literal `"INFO"` at `src/tax_reporting/infrastructure/logging_config.py:15`, change `def configure_application_logging(level: str = "INFO", ...)` to make `level` REQUIRED (`level: str` with no default). Rationale (r3 finding N1): after the Task 1 reorder, every caller passes an explicit `level` derived from config or CLI; the default is dead code and one of the 5 hardcoded sites the Gist names. All call sites (verified: `main.py:114` post-reorder) must pass `level=...` explicitly.
- [x] **FIX THE ROOT-LOGGER GATING BUG (r5 finding #1, Blocker):** `logging_config.py:26` currently sets `root_logger.setLevel(getattr(logging, level.upper()))`. This gates DEBUG records at the ROOT before they reach the file handler, so the file handler's `setLevel(logging.DEBUG)` at `:49` is inert whenever `level != "DEBUG"`. Empirically verified: with `level='WARNING'`, a `logger.debug(...)` call produces ZERO handler invocations and never reaches the file. This makes Design Invariant #3 and the entire Part B promise ("per-row detail preserved at DEBUG in the file") false under the new `LOG_LEVEL=WARNING` default. Fix: change line 26 to `root_logger.setLevel(logging.DEBUG)` (root always DEBUG); the per-handler `setLevel` calls at `:39` (console) and `:49` (file) are what actually enforce the threshold. The existing comment on `:49` ("File gets all levels") becomes true as written. This is a pre-existing bug that the INFO→WARNING default change makes severe. ADD a regression test: `TestLoggingConfig#test_file_handler_receives_debug_when_console_at_warning` in a NEW file `tests/unit/infrastructure/test_logging_config.py` (mirroring the existing `test_config.py ↔ config.py` convention); given `configure_application_logging(level='WARNING', log_file=tmp)`, expects a `logger.debug(...)` call to appear in the file contents AND NOT on the console. Add `tests/unit/infrastructure/test_logging_config.py` to the Review Scope Tests list (r6 Low).
- [x] Grep-gate (r3 N1 + r4 #1 + r5 #2): after all removals, BOTH of these must hold:
    - `grep -n '"INFO"' src/tax_reporting/main.py src/tax_reporting/infrastructure/logging_config.py src/tax_reporting/domain/constants.py | grep -v 'choices=\['` returns zero matches. (The argparse `choices=["DEBUG", "INFO", ...]` at `main.py:72` legitimately contains `"INFO"` and is filtered out.)
    - `grep -n '"WARNING"' src/tax_reporting/main.py src/tax_reporting/infrastructure/logging_config.py src/tax_reporting/domain/constants.py | grep -v 'choices=\['` returns zero matches. (The argparse `choices=[...]` at `main.py:72` also contains `"WARNING"`; `main.py`'s failure-path call uses the imported `DEFAULT_LOG_LEVEL` constant, not a bare literal.)
    The only acceptable `"WARNING"` literal anywhere in src/ is the ONE in `config.py` defining `DEFAULT_LOG_LEVEL`. The validation-set `{"DEBUG","INFO","WARNING","ERROR","CRITICAL"}` lives in `config.py` too, it's the validation literal, not a default, and is exempt.
- [x] Rewrite `_main()` (`main.py:104`) wiring per Design Invariant 9 (r1 finding #2): change signature to `log_level: str | None = None`. Import `DEFAULT_LOG_LEVEL` from `..infrastructure.config`. Reorder as follows:
    1. Move `load_configuration_from_file()` to the TOP of `_main()` (before any `logger.*` call that depends on configured logging).
    2. On success: compute `resolved_level = log_level if log_level is not None else app_config.log_level`; call `configure_application_logging(level=resolved_level, log_file=log_file)` EXACTLY ONCE.
    3. On `except (FileNotFoundError, OSError):` (the existing config-not-found path at `main.py:182`): call `configure_application_logging(level=DEFAULT_LOG_LEVEL, log_file=log_file)` BEFORE the existing `logger.warning("Config file not found; no jurisdiction config loaded...")` so that warning is not lost; then continue with `tax_jurisdiction = None`. Uses the named constant, not a bare `"WARNING"` literal (r4 #1).
    4. On `except (ValueError, KeyError, configparser.Error) as exc:` (the existing `main.py:187` wrapper): leave it to propagate as `ConfigurationError` unconfigured (matches the `_load_crypto_tax_report` `raise ConfigurationError` pattern that surfaces via `main()`'s outer try at `main.py:262-272`).
    5. Move the existing source-file validation / IB parse / FIFO gains / rollover-write block (`main.py:117-174`) to AFTER the unified `configure_application_logging` call, so the `logger.info(...)` startup diagnostics at `:122-171` execute with configured logging.
- [x] Update `main()` (`main.py:256`) signature to match (`log_level: str | None = None`).
- [x] Update CLI fallback (`main.py:454`): `log_level = args.log_level` (may be `None`; `_main` resolves the default from config).
- [x] REWRITE 2 existing CLI tests whose `assert_called_once_with(..., log_level="INFO")` will break when `log_level` becomes `None` (r2 finding #1):
    - `tests/unit/test_cli.py:134-145` (`test_cli_passes_example_args_to_main`): change `log_level="INFO"` to `log_level=None`.
    - `tests/unit/test_cli.py:149-157` (`test_cli_passes_custom_paths_to_main`): change `log_level="INFO"` to `log_level=None`.
- [x] DROP the proposed new `test_cli_passes_explicit_log_level_to_main` (r3 finding N2): the existing `test_cli_passes_log_level_to_main` at `tests/unit/test_cli.py:161-169` already asserts that `--log-level DEBUG` forwards `log_level="DEBUG"`. Do not add a duplicate.
- [x] Update `--log-level` help text (`main.py:74`) to: `"Set console log level (overrides config.ini LOG_LEVEL; default: WARNING)"`.
- [x] Run → expect GREEN: `uv run pytest tests/unit/infrastructure/test_config.py -k log_level`
- [x] Run → expect GREEN (no regression): `uv run pytest tests/unit/test_cli.py tests/unit/infrastructure/test_config.py`
- [x] Commit: `feat(config): add LOG_LEVEL to [COMMON]; single source for console log level`

### Task 2: Part B Pattern D - fee_filter untagged-fee per-row → DEBUG (RED→GREEN)

Files:
- `src/tax_reporting/application/crypto/fee_filter.py`
- `tests/unit/application/test_fee_filter.py`

- [x] `TestSuspects#test_warns_on_unlisted_suspected_fee` (rewrite, currently at `test_fee_filter.py:1001`); given a suspect unlisted-asset withdrawal, expects the per-row detail at DEBUG (caplog at DEBUG captures "Possible untagged fee for unlisted asset RUNE" + "0.3") AND one aggregate WARNING containing "Surfaced N suspect untagged network fees".
- [x] `TestUntaggedWhitelist#test_retains_untagged_non_whitelist_withdrawals` (verify still passes, currently `:569`); given the whitelist path, expects NO WARNING-level record containing "Possible untagged fee for unlisted asset" (the aggregate summary uses distinct "Surfaced N suspect" wording and must not collide with this negative assertion).
- [x] Run → expect RED: `uv run pytest tests/unit/application/test_fee_filter.py::TestSuspects::test_warns_on_unlisted_suspected_fee`
- [x] In `_surface_suspects` (`fee_filter.py:541`), downgrade the per-row `logger.warning(...)` at `:607` to `logger.debug(...)`. The existing aggregate at `:619-620` (`"Surfaced %d suspect untagged network fees for manual review"`) stays at WARNING.
- [x] Grep-gate (r1 #9): verify `grep -c 'Possible untagged fee for unlisted asset' src/tax_reporting/application/crypto/fee_filter.py` returns exactly 1 match (the DEBUG-level per-row at `:607`); the aggregate at `:615` uses distinct "Surfaced" wording and must NOT contain that substring, otherwise the negative test at `test_fee_filter.py:569` will silently go RED.
- [x] Run → expect GREEN: `uv run pytest tests/unit/application/test_fee_filter.py`
- [x] Commit: `refactor(crypto): downgrade fee_filter untagged-fee per-row warning to DEBUG`

### Task 3: Part B Pattern A - all-zero CG row grouping (RED→GREEN)

Files:
- `src/tax_reporting/application/crypto_reporting.py`
- `tests/unit/application/test_crypto_reporting.py`

- [x] `TestParseCapitalGainsFile#test_all_zero_rows_grouped_into_single_summary` (new); given 3 known-token CG rows with all-zero values, expects exactly ONE WARNING-level record matching `"Flagged %d all-zero capital gains row"` and 3 DEBUG-level per-row records. The 3 `CryptoReviewEntry` rows are still appended to `context.review_entries` (unchanged).
- [x] `TestParseCapitalGainsFile#test_parse_capital_gains_file_creates_review_entry_for_zero_value_known_assets` (existing, `~test_crypto_reporting.py:8519`); verify still passes, it asserts on `review_reason` field content, not caplog, so the per-row→DEBUG change must not affect it.
- [x] Run → expect RED: `uv run pytest tests/unit/application/test_crypto_reporting.py -k "all_zero_rows_grouped"`
- [x] In `_parse_capital_gains_file` (`crypto_reporting.py:711`): add `skipped_all_zero: Counter[str] = Counter()` next to `skipped_koinly_tracking` (~`:736`).
- [x] Downgrade the WARNING at `:802` to `logger.debug(...)`; immediately after, `skipped_all_zero[asset] += 1`.
- [x] After the row loop (alongside the existing post-loop summaries at `:879/887/894`), emit one summary when `skipped_all_zero` is non-empty: `logger.warning("Flagged %d all-zero capital gains row(s) for review (%s); see DEBUG log and review list for details", sum(skipped_all_zero.values()), ", ".join(f"{a}: {n}" for a, n in sorted(skipped_all_zero.items())))`.
- [x] Run → expect GREEN: `uv run pytest tests/unit/application/test_crypto_reporting.py -k "all_zero or zero_value_known"`
- [x] Commit: `refactor(crypto): group all-zero CG row warnings into single summary (pattern A)`

### Task 4: Part B Pattern C - duplicate tx_key grouping (RED→GREEN)

Files:
- `src/tax_reporting/application/crypto_fifo/parsing.py`
- `tests/unit/application/test_crypto_fifo.py`

- [x] `TestCryptoFifoParsing#test_duplicate_tx_key_emits_single_summary` (new); given 3 acquisition rows with the same `tx_key`/`source_type`, expects exactly ONE WARNING-level record matching `"Dropped %d duplicate-tx_key acquisition(s) and %d consumption(s)"` and 3 DEBUG records. `parse_failures_by_asset` still records all 3 row indices per asset (unchanged).
- [x] Run → expect RED: `uv run pytest tests/unit/application/test_crypto_fifo.py -k "duplicate_tx_key_emits_single_summary"`
- [x] In `_dedup_by_tx_key` (`crypto_fifo/parsing.py:281`): downgrade the WARNINGs at `:303` (acquisitions) and `:324` (consumptions) to `logger.debug(...)`.
- [x] Before the implicit return at end of `_dedup_by_tx_key`, compute `dropped_acqs` and `dropped_cons` from `parse_failures_by_asset` (or two new local counters incremented at the DEBUG sites), and when either is non-zero emit: `logger.warning("Dropped %d duplicate-tx_key acquisition(s) and %d consumption(s) across %d asset(s) to prevent doubled FIFO pool; see DEBUG log for per-row detail", dropped_acqs, dropped_cons, affected_assets)`.
- [x] Run → expect GREEN: `uv run pytest tests/unit/application/test_crypto_fifo.py`
- [x] Commit: `refactor(crypto): group duplicate-tx_key warnings into single summary (pattern C)`

### Task 5: Part B Pattern H - OGR no-CG-counterpart grouping (RED→GREEN)

Files:
- `src/tax_reporting/application/crypto/ogr_handler.py`
- `tests/unit/application/test_crypto_reporting.py`

- [x] `TestOgrSplit#test_no_cg_no_th_tag_safety_net` (rewrite, currently at `test_crypto_reporting.py:9899`); given an OGR derivatives row with no CG counterpart, expects ONE aggregate WARNING-level record matching `"routed to derivatives by row type"` and one DEBUG-level per-row record (caplog at DEBUG captures the "ByBit" platform-name detail). The `DerivativesPnLEntry` is still appended (unchanged).
- [x] Run → expect RED: `uv run pytest tests/unit/application/test_crypto_reporting.py::TestOgrSplit::test_no_cg_no_th_tag_safety_net`
- [x] In `_split_ogr_index` (`ogr_handler.py:207`): add `no_cg_counter: int = 0` next to `:346`. Downgrade the WARNING at `:346` to `logger.debug(...)`; `no_cg_counter += 1`.
- [x] Before `return` at `:353`, when `no_cg_counter > 0` emit: `logger.warning("%d OGR row(s) routed to derivatives by row type with no CG counterpart to confirm spot vs derivatives; see DEBUG log for per-row detail", no_cg_counter)`. Mirrors the existing summary at `ogr_handler.py:130-136` in the same file.
- [x] Run → expect GREEN: `uv run pytest tests/unit/application/test_crypto_reporting.py::TestOgrSplit`
- [x] Commit: `refactor(crypto): group OGR no-CG-counterpart warnings into single summary (pattern H)`

### Task 6: Part B Pattern G - FIFO non-taxable exhausted grouping (RED→GREEN)

Files:
- `src/tax_reporting/application/crypto_fifo/matching.py`
- `tests/unit/application/test_crypto_fifo.py`

**Context (r1 findings #3, #7):** `matching.py:280` is ONE shared `logger.warning(fifo_warning, ...)` reached by two taxable sub-branches (pool-truly-exhausted string at `:263` AND no-acquisition string at `:271`). Pattern G is the NON-TAXABLE branch at `matching.py:300-306` (separate emission). Downgrading `:300` breaks `test_crypto_fifo.py:2197` which asserts on that emission at WARNING level. The fix is to rewrite the test to assert on the aggregate (or drop the caplog check), since the per-row `partial_tx_keys` membership check at `:2195-2196` is the substantive assertion.

- [x] `TestConsumeAgainstPoolInplace#test_non_taxable_pool_exhausted_marks_partial_tx_key` (REWRITE, currently `:2181-2197`); given a non-taxable consumption that exhausts the pool, expects: `"tx_partial" in partial` AND `"tx_partial" in carryover` (these stay unchanged at `:2195-2196`); the existing caplog assertion `any("understated" in r.message.lower() or "exhausted" in r.message.lower() for r in caplog.records)` at `:2197` MUST be removed (the per-row emission is now DEBUG; calling `_consume_against_pool_inplace` directly bypasses the `compute_fifo_for_asset` aggregate). Rationale: the partial-set membership check is the substantive assertion; the caplog check was redundant. Optionally add a separate test that calls `compute_fifo_for_asset` and asserts the aggregate WARNING.
- [x] `TestConsumeAgainstPoolInplace#test_non_taxable_pool_exhausted_emits_aggregate_via_compute_fifo` (NEW); given a non-taxable consumption that exhausts the pool, called via `compute_fifo_for_asset`, expects ONE WARNING-level record matching `"FIFO pool exhausted for %d non-taxable"` and ONE DEBUG record (caplog at DEBUG captures the per-row emission).
- [x] Run → expect RED on the NEW aggregate test: `uv run pytest tests/unit/application/test_crypto_fifo.py -k "non_taxable_pool_exhausted_emits_aggregate"`
- [x] In `_consume_against_pool_inplace` (`matching.py:196`): downgrade the WARNING at `:300` to `logger.debug(...)`. Do NOT touch `:280` in this task (that's the taxable shared emission, handled in Task 7).
- [x] At end of `compute_fifo_for_asset` (`matching.py:19`, after the loop at `:74`), when `partial_tx_keys` is non-empty emit: `logger.warning("FIFO pool exhausted for %d non-taxable %s consumption(s) on %s; carry-over cost understated; see DEBUG log for per-row detail", len(partial_tx_keys), asset, platform)`.
- [x] Verify `:2197` rewrite passes (no caplog assertion); verify `:701`, `:748`, `:2120`, `:2161` are unchanged by THIS task (they target the taxable `:280` emission, which is still WARNING in this task, Task 7 handles it).
- [x] Run → expect GREEN: `uv run pytest tests/unit/application/test_crypto_fifo.py`
- [x] Commit: `refactor(crypto): group FIFO non-taxable exhausted warnings into per-asset summary (pattern G)`

### Task 7: Part B Pattern F - taxable no-acquisition / pool-exhausted grouping (MEDIUM) (RED→GREEN)

Files:
- `src/tax_reporting/domain/crypto_fifo.py`
- `src/tax_reporting/application/crypto_fifo/matching.py`
- `src/tax_reporting/application/crypto/fifo_helpers.py`
- `tests/unit/application/test_crypto_fifo.py`

**Context (r1 finding #3, critical):** `matching.py:280` is ONE `logger.warning(fifo_warning, asset, con.con.date, remaining)` reached by TWO taxable sub-branches: `pool_truly_exhausted` (string at `:263-265`, "FIFO pool exhausted for %s on %s") AND no-acquisition-at-date (string at `:271-273`, "No acquisition available at or before disposal date for %s on %s"). Pattern F covers BOTH (they are both taxable unmatched-disposal cases). Before any downgrade, the shared emission MUST be split into two independent `logger.debug(...)` calls, one inside each branch, so the level can be lowered without affecting the other branch's semantics. Four existing tests assert on these emissions at WARNING and must be rewritten.

- [x] Grep conftest helpers for `AssetFifoResult(**` or `**overrides` patterns; if found, verify they tolerate a new field. Reference: development_lessons.md #54. (r1 self-audit confirmed zero matches; re-verify at execution time.)
- [x] `TestFifoMatching#test_no_acquisition_summary_aggregates_across_platforms` (NEW); given 2 `(asset, platform)` pairs each producing 1 unmatched taxable disposal, expects the outer aggregation in `_rebuild_fifo_for_loan_affected_assets` to emit ONE WARNING matching `"%d taxable disposal(s) had no acquisition at or before the disposal date"` AND 2 DEBUG records. Each `CryptoFifoRealization(review_required=True)` still has its `review_reason` populated (unchanged).
- [x] Run → expect RED: `uv run pytest tests/unit/application/test_crypto_fifo.py -k "no_acquisition_summary_aggregates"`
- [x] Add `unmatched_taxable_count: int = 0` field to `AssetFifoResult` (`src/tax_reporting/domain/crypto_fifo.py:100`).
- [x] In `_consume_against_pool_inplace` (`matching.py:196`), FIRST split the shared emission at `:280` into two independent `logger.debug(...)` calls, one inside the `if pool_truly_exhausted:` branch (using the `:263` string) and one inside the `else:` branch (using the `:271` string). Delete the unified `:280` call. This split is a prerequisite refactor; both new calls start at DEBUG. **Preserve the `review_reason` assignments** at `:266-268` (pool-exhausted) and `:275-279` (no-acquisition), these are structurally separate from the logger call and feed `CryptoFifoRealization(...)` at `:281-298`; an over-broad reading of "split the shared emission" must not delete them (r2 finding #4).
- [x] Increment a local counter in each split branch; add it to `AssetFifoResult.unmatched_taxable_count` at construction.
- [x] In `_rebuild_fifo_for_loan_affected_assets` (`fifo_helpers.py:199`): sum `unmatched_taxable_count` across all `(asset, platform)` results; when non-zero emit ONE aggregate: `logger.warning("%d taxable disposal(s) had no acquisition at or before the disposal date (pool exhausted); flagged for review with zero cost basis; see DEBUG log and realization review_reason for details", total)`.
- [x] REWRITE 4 sibling tests whose `caplog.at_level(WARNING)` assertions on "exhausted"/"pool exhausted" substrings no longer hold (the per-row emissions are now DEBUG; calling `_consume_against_pool_inplace` directly bypasses the `_rebuild_fifo_for_loan_affected_assets` aggregate):
    - `test_crypto_fifo.py:701` (`TestFifoPlaceholderWhenPoolExhausted#test_zero_cost_placeholder_with_review`): drop the `assert any("pool exhausted" in rec.message.lower() for rec in caplog.records)` at `:701`; keep the `review_reason` field assertion at `:700` (that is the substantive check).
    - `test_crypto_fifo.py:748` (`TestFifoPartialSellPoolExhausted#test_buy_5_sell_8_produces_two_realizations_and_warning`): drop or rewrite the analogous caplog assertion. Keep the realization-count and proportional-proceeds assertions.
    - `test_crypto_fifo.py:2120` (`TestConsumeAgainstPoolInplace#test_empty_pool_produces_placeholder_realization`): drop `assert any("exhausted" in r.message.lower() for r in caplog.records)`; keep the realization assertions.
    - `test_crypto_fifo.py:2161` (`TestConsumeAgainstPoolInplace#test_partial_lot_match_buy5_sell8`): drop the caplog assertion at `:2161-2163`; keep the matched/placeholder realization assertions.
- [x] Optionally add ONE new test that calls `compute_fifo_for_asset` (or `_rebuild_fifo_for_loan_affected_assets`) end-to-end and asserts the aggregate WARNING fires, so the WARNING-level behavior is still covered at the right layer.
- [x] Run → expect GREEN: `uv run pytest tests/unit/application/test_crypto_fifo.py`
- [x] Commit: `refactor(crypto): split shared matching.py:280 emission; group taxable no-acquisition warnings (pattern F)`

### Task 8: Part B Pattern E - zero-Net-Value crypto_deposit (MEDIUM) (RED→GREEN)

Files:
- `src/tax_reporting/application/crypto_fifo/parsing.py`
- `tests/unit/application/test_crypto_fifo.py`

**Context (r1 findings #5, #6):** The call chain is `_classify_rows_for_loan_affected_assets` (`parsing.py:147`) → `_classify_th_row` (defined `:339`, called at `:249`) → `_classify_deposit_row` (defined `:601`, called at `:378`). The plan's original "mirror `parse_failures_by_asset`" template is misleading: `parse_failures_by_asset` is passed DIRECTLY from `_classify_rows_for_loan_affected_assets` to `_classify_deposit_row` (NOT via `_classify_th_row`); the new `zero_net_deposits` Counter must be added to BOTH `_classify_th_row` AND `_classify_deposit_row` signatures AND forwarded at the `:378` call site. r1 finding #6: the existing `:2322` test claims to assert on `review_reason` field only, VERIFY by reading the test body before declaring it safe; if it also inspects `caplog.records`, add a rewrite sub-task.

- [x] VERIFY (r1 #6): read `tests/unit/application/test_crypto_fifo.py:2310-2380` and paste the exact assertions for `test_zero_net_value_deposit_flagged_for_review`. If it asserts ONLY on `acq.acq.review_reason` (no `caplog.records` inspection), this task proceeds as written. If it ALSO inspects caplog, add a rewrite sub-task to switch the caplog assertion to DEBUG level or assert on the new aggregate WARNING.
- [x] `TestCryptoFifoParsing#test_zero_net_value_deposit_summary` (NEW); given 3 crypto_deposit rows with zero Net Value across 2 assets, expects ONE WARNING matching `"Flagged %d zero-Net-Value crypto_deposit(s) for review"` and 3 DEBUG records.
- [x] Run → expect RED on the new test.
- [x] Initialize `zero_net_deposits: Counter[str] = Counter()` in `_classify_rows_for_loan_affected_assets` (`parsing.py:147`) next to `parse_failures_by_asset` (verified location `:172`).
- [x] Add `zero_net_deposits: Counter[str]` parameter to `_classify_th_row` signature (`:339`) AND forward it at the call to `_classify_deposit_row` at `:378`. Update the call from `_classify_rows_for_loan_affected_assets` to `_classify_th_row` at `:249` to pass the Counter. (This intermediate pass is required because `_classify_th_row` is the actual caller of `_classify_deposit_row`, r1 finding #5.)
- [x] Add `zero_net_deposits: Counter[str]` parameter to `_classify_deposit_row` signature (`:601`).
- [x] In `_classify_deposit_row` (`:601`): downgrade the WARNING at `:622` to `logger.debug(...)`; `zero_net_deposits[parsed_row.received_currency] += 1`. The `deposit_review_reason` field on the acquisition is UNCHANGED.
- [x] In `_classify_rows_for_loan_affected_assets`, before `return` at `:278` (next to the `_dedup_by_tx_key` call), when `zero_net_deposits` is non-empty emit: `logger.warning("Flagged %d zero-Net-Value crypto_deposit(s) for review (%s); see DEBUG log and review_reason field for details", sum(zero_net_deposits.values()), ", ".join(f"{a}: {n}" for a, n in sorted(zero_net_deposits.items())))`.
- [x] Run → expect GREEN: `uv run pytest tests/unit/application/test_crypto_fifo.py`
- [x] Commit: `refactor(crypto): group zero-Net-Value deposit warnings into single summary (pattern E)`

### Task 9: Part B Pattern B - token_origin records-disagree (HARD) (RED→GREEN)

Files:
- `src/tax_reporting/application/token_origin.py`
- `src/tax_reporting/application/crypto_reporting.py`
- `src/tax_reporting/application/crypto/fifo_helpers.py`
- `tests/unit/application/test_crypto_origin_resolver.py`

- [x] `TestTokenOriginResolverDisagreementCounter#test_disagreement_counter_accumulates` (new class in existing file, r2 #2); given 3 calls to `resolve()` that each hit the disagree branch, expects `resolver._disagreements` to have 3 entries (one per distinct `(asset, wallet, date)` key) and NO WARNING-level record emitted during the calls (the per-row emission is now DEBUG).
- [x] `TestTokenOriginResolverDisagreementCounter#test_log_and_reset_disagreements_emits_summary_and_clears` (new); given a resolver with 3 accumulated disagreements, calling `log_and_reset_disagreements(scope="capital gains parse")` expects ONE WARNING matching `"TokenOriginResolver (capital gains parse): %d origin-resolution disagreement(s) across %d distinct"` and `_disagreements` to be empty afterwards.
- [x] `TestTokenOriginResolverDisagreementCounter#test_log_and_reset_disagreements_noop_when_empty` (new); given a resolver with zero disagreements, calling `log_and_reset_disagreements(...)` expects NO WARNING record.
- [x] Run → expect RED: `uv run pytest tests/unit/application/test_crypto_origin_resolver.py -k "disagreement"`
- [x] In `TokenOriginResolver.__init__` (`token_origin.py:69`): add `self._disagreements: Counter[tuple[str, str, str]] = Counter()`.
- [x] In `resolve()` (`:369`), in the `if not agree:` branch (`:404`): downgrade the WARNING at `:435` to `logger.debug(...)`; `self._disagreements[(asset, normalized_wallet, acquisition_date)] += 1`. The return value (`TokenOrigin.unknown()`) is unchanged.
- [x] Add method `log_and_reset_disagreements(self, scope: str) -> None`: when `self._disagreements` is non-empty, emit ONE WARNING: `logger.warning("TokenOriginResolver (%s): %d origin-resolution disagreement(s) across %d distinct (asset, wallet, date) keys; returning unknown; see DEBUG log for details", scope, sum(self._disagreements.values()), len(self._disagreements))`; then `self._disagreements.clear()`. The clear happens AFTER the emit (never before) so a logging-handling failure cannot lose the accumulated state; clear is unconditional on both empty and non-empty paths (defensive).
- [x] VERIFY (r1 #4): confirm `_parse_capital_gains_file` is called BEFORE `_rebuild_fifo_for_loan_affected_assets` in `load_koinly_crypto_report` (verified by reviewer at `crypto_reporting.py:337` then `:361`); if not, reorder the flushes accordingly.
- [x] In `_parse_capital_gains_file` (`crypto_reporting.py:711`), after the row loop (alongside the post-loop summaries at `:879/887/894`): `context.origin_resolver.log_and_reset_disagreements(scope="capital gains parse")`.
- [x] In `_rebuild_fifo_for_loan_affected_assets` (`fifo_helpers.py:199`), AFTER the realization loop (and AFTER the CG-parse flush has run upstream): `origin_resolver.log_and_reset_disagreements(scope="FIFO rebuild")`. The flush ordering is load-bearing per Design Invariant #10 because the resolver instance is shared and accumulates from both call sites between flushes.
- [x] Run → expect GREEN: `uv run pytest tests/unit/application/test_crypto_origin_resolver.py`
- [x] Commit: `refactor(crypto): group token_origin disagreement warnings via resolver Counter + caller flush (pattern B)`

### Task 10: Full-suite verification

Files: (no edits; verification only)

- [x] Run: `uv run pytest tests/` → expect 1802+ passing (baseline) plus new tests, zero failures.
- [x] Run: `uv run tax-reporting --log-level WARNING 2>&1 | grep -c WARNING` → expect single digits (down from 1514 on real data; the `--example` dataset will show only the year-mismatch skip).
- [x] Run: `uv run tax-reporting --log-level DEBUG 2>&1 | grep -cE "all-zero values|Origin records disagree|Duplicate tx_key|untagged fee|zero Net Value|No acquisition available|FIFO pool exhausted|routed to derivatives"` → expect counts matching the `tmp.txt` baseline per pattern.
- [x] Manual: open `resources/result/extract.xlsx` (or whichever output the run produces) and spot-check that the review list for patterns A/D/E/F/H has the same row count as a baseline run (the conversion must be logging-only; data flow is unchanged).

### Task 11: Documentation

Files:
- `README.md`
- `docs/maintenance/project-guidelines.md`

- [x] `README.md` config section: add `LOG_LEVEL` to the `[COMMON]` keys list with the description "Console log level (DEBUG/INFO/WARNING/ERROR/CRITICAL); case-insensitive; default WARNING; CLI `--log-level` overrides. File handler always captures DEBUG."
- [x] `docs/maintenance/project-guidelines.md`: add a numbered rule (next available number) capturing the per-row-DEBUG + aggregate-WARNING convention: "High-volume per-row warnings whose detail is already surfaced in the Excel review list MUST be downgraded to DEBUG and grouped into one aggregate WARNING summary per scope (pattern: `ogr_handler.py:130-136`). Per-row detail stays reachable via the file handler (hardcoded DEBUG). Do NOT downgrade DATA_DROPPED/PARSE_ERROR/INVARIANT_VIOLATION sites that do NOT have a review-list surface, those stay per-row WARNING."
- [x] Grep `docs/maintenance/` and `README.md` for any prose claiming INFO is the default log level; update to WARNING.
- [x] Commit: `docs: document LOG_LEVEL config key + warning-grouping convention`

## Monitor

(None at plan creation; add here if review surfaces deferred risks with named owners.)
