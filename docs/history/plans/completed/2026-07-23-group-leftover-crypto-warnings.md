# Plan: Group leftover crypto per-row warnings (phase 2)

Plan review: `docs/history/reviews/2026-07-23-plan-review-group-leftover-crypto-warnings-r1.md` (r1: 0 Blocker + 2 Medium + 1 Monitor folded) · `…-r2.md` (r2: 3/3 r1 folds verified landed; 0 Blocker + 0 Medium + 1 Low + 1 Monitor folded; **ready=yes**).

Predecessor: `docs/history/plans/completed/2026-07-21-configurable-log-level-and-warning-grouping.md` shipped Part A (configurable `LOG_LEVEL`) + Part B patterns A–H, taking console WARNINGs from 1514 → 113 on real data. This plan converts the **4 per-row patterns the predecessor left at WARNING** (91 of the remaining 113 lines), targeting ~22 → single-digit aggregate WARNINGs.

## Terms

- **Per-row warning**: a WARNING-level log line emitted inside a per-input-row loop. The predecessor converted 8 patterns (A–H); this plan handles the 4 remaining (I, J, K, L).
- **Review-list surface**: a user-facing Excel cell that already carries the per-row's detail. For crypto this is the Crypto Gains "Review" column, rendered as `"YES: <review_reason>"` (`application/persisting/crypto_gains_sheet.py:45`) when a `CryptoFifoRealization` / `CryptoCapitalGainEntry` has `review_required=True`. A warning that duplicates a review-list surface is safe to downgrade (per-row → DEBUG + one aggregate WARNING).
- **Group-collapse (distinct from downgrade)**: for a per-row WARNING with NO review-list surface, the per-row detail cannot be dropped from the console audit trail, but N identical lines can be collapsed into ONE WARNING naming the count + breakdown. The per-tx_hash detail moves to DEBUG; the single WARNING stays loud.
- **Single-cell mutable counter**: the predecessor's pattern-F mechanism (`total_unmatched_taxable: list[int] = [0]` threaded through `_process_single_asset_fifo`, emitted once at the end of `_rebuild_fifo_for_loan_affected_assets` at `crypto/fifo_helpers.py:306-311`). Used when the per-row loop is nested inside a per-asset / per-platform caller loop, so the aggregate cannot be emitted inside the leaf function (it would fire N times).

## Gist & Examples

### Problem

A real production run (`uv run tax-reporting`, `LOG_LEVEL=WARNING`) still emits **113 WARNING lines**. 91 of them are 4 per-row patterns the predecessor plan deliberately deferred or mis-classified. Breakdown (counts from a live run, grouped by message-prefix):

| # | Count | Pattern | Source | Has Excel review surface? |
|---|------|---------|--------|---------------------------|
| **I** | 39 | "Removed untagged-whitelisted fee disposal for X (Net Value N EUR, tx_hash=…)" | `crypto/fee_filter.py:411` (`_log_fee_removals`) | ❌ **No** - removal returns `capital_entries` minus the lot; nothing appended to `review_entries`. The log line IS the only audit trail. |
| **J** | 32 | "Unresolved deferred acquisition…" (`:159`) / "Resolved carry-over cost… is zero" (`:197`) / "…is partial" (`:204`) / "Multi-sender carry-over…" (`:189`) | `crypto_fifo/cross_asset.py` (`_resolve_single_acquisition`) | ✅ **Yes** - every branch returns `acq.with_acq(review_required=True, review_reason=<detailed paragraph>)` (`:169-182`, `:211-220`); flows to Crypto Gains "YES:" cell. |
| **K** | 14 | "Could not resolve transfer_in_deferred…" (`:123`) / "Transfer carry-over… requires review" (`:104`) | `crypto_fifo/transfer.py` (`_resolve_intra_asset_transfers`) | ✅ **Yes** - same path as J (`review_required=True` + `review_reason` → "YES:" cell). |
| **L** | 6 | "Aggregated entry for 'X' sold Y has no acquisition date…" (`:346`) + epoch-sentinel sibling (`:353`) | `crypto/aggregation.py` (`_aggregate_capital_entries`) | ✅ **Yes** - the lot's `review_reason` (set by predecessor pattern F) already says "no acquisition at or before the disposal date (pool exhausted)"; the aggregated entry inherits it → "YES:" cell. Pattern L is a pure duplicate of an already-converted pattern. |

The remaining ~22 WARNINGs (cyclic-dependency notices, the 8 predecessor aggregate summaries, dedup summaries, "Filtered N sub-1-EUR entries", "Surfaced N suspect untagged network fees") are **legitimate single-emission lines** and are out of scope.

### What changes

The predecessor's `project-guidelines.md` rule #7 forbids downgrading J, K, and I, claiming *"the log line IS the only audit surface."* **That claim is factually wrong for J and K** (verified by code trace: both set `review_required=True` + a detailed `review_reason` that renders as `"YES: <reason>"` in the Crypto Gains sheet). It is correct only for I. This plan:

1. **Corrects rule #7** to match reality: lift the downgrade prohibition for J and K (they have a review surface), keep it for I (no surface), and add L to the "has a surface" list.
2. **Pattern I - group-collapse (stays WARNING).** Per-row detail (asset + Net Value + tx_hash) moves to DEBUG; ONE aggregate WARNING carries the count + per-asset breakdown. Stays loud because there is no Excel surface - the WARNING is the audit trail.
3. **Patterns J, K, L - downgrade per-row → DEBUG + one aggregate WARNING.** Mirrors the predecessor's patterns A–H. The per-cause breakdown (unresolved / zero / partial / multi-sender for J; unmatched / requires-review for K; empty / epoch for L) is preserved in each aggregate so the signal stays actionable.

J and K are **not** the predecessor's "EASY" patterns: their leaf functions (`resolve_cross_asset_exchanges`, `_resolve_intra_asset_transfers`) are called inside `_process_single_asset_fifo`, which runs **per-asset** (K also per-platform). Emitting the aggregate inside the leaf would fire N times. They must use the predecessor's pattern-F mechanism: a single-cell mutable counter threaded up to `_rebuild_fifo_for_loan_affected_assets` and emitted once.

### Before / after

```
# BEFORE (current, LOG_LEVEL=WARNING): 113 WARNING lines, 91 from 4 per-row patterns
$ uv run tax-reporting 2>&1 | grep -c WARNING
113

# AFTER: ~4 new aggregate WARNINGs replace the 91 per-row lines; total single-digit
$ uv run tax-reporting 2>&1 | grep -c WARNING
~26   # (22 legitimate single-emission + 4 new aggregates)

# Per-row detail still reachable in the file at DEBUG (predecessor Design Invariant #3, verified by existing regression test)
$ uv run tax-reporting --log-level DEBUG 2>&1 | grep -c "untagged-whitelisted fee disposal\|carry-over cost\|transfer_in_deferred\|no acquisition date"
# matches the 91-row baseline
```

### Edge cases / motivation

- **Rule #7 self-contradiction.** The predecessor wrote a rule whose stated rationale is false for J/K. Correcting it is part of this plan, not a follow-up - leaving a known-false rule invites the next contributor to "honor" it and re-introduce the noise.
- **Aggregate wording collisions with negative tests.** Predecessor lesson (pattern D): a new aggregate substring that an existing negative test greps for will silently break that test. Anti-collision grep at planning time found `"transfer_in_deferred acquisition"` already in `test_crypto_fifo.py:436`; K's aggregate wording is chosen to avoid it. A Validation Command gate re-runs the check.
- **Pre-existing J caplog test.** `TestResolveCrossAssetUnmatchedDeferredSetsReviewRequired#test_unmatched_deferred_flagged` (`test_crypto_fifo.py:917-951`) asserts at WARNING on `"unresolved"`/`"deferred"` substrings. Downgrading J breaks it; must be rewritten to assert the new aggregate at WARNING OR the per-row at DEBUG. (Discovered during planning, not accounted for in the predecessor's Q5(a).)
- **Pattern I is group-collapse, NOT downgrade.** Distinct from J/K/L. The single aggregate stays WARNING; only the per-tx_hash lines move to DEBUG. Getting this backwards (downgrading I to DEBUG-only) would delete the only audit trail for those removals.
- **J sub-branch distinctness.** J has 4 distinct per-row emissions (unresolved / zero / partial / multi-sender) with different actionable meanings. The aggregate must preserve the per-cause breakdown, not collapse to a bare count, or the user loses the ability to tell "permanently overstated gain" (unresolved) from "understated cost" (partial).

## Evaluation Criteria

**Quality dimensions:**

- **Signal-to-noise**: on the user's real data (113 WARNING baseline), a default `LOG_LEVEL=WARNING` run drops to single-digit new-aggregate count for the 4 patterns; total console WARNINGs fall from 113 to ~26 (the ~22 legitimate single-emission lines + 4 new aggregates).
- **Audit-trail integrity**: per-row detail (asset, Net Value/tx_hash/carry-over reason) remains reachable at DEBUG in `logs/tax-reporting.log` for all 4 patterns; the Excel review column for J/K/L is unchanged in content (review_required/review_reason untouched).
- **Correctness**: full test suite (1802+ predecessor baseline + this plan's new tests) green. The 3 rewritten caplog tests assert meaningful behavior (aggregate fires at WARNING; per-row reachable at DEBUG).
- **Rule consistency**: after the rule #7 edit, the rule text matches the code (J/K have a surface; I does not; L added). No remaining prose in `docs/maintenance/` or `README.md` claims I/J/K/L lack a review surface.
- **No silent test breakage**: the anti-collision grep (Validation Command) returns zero matches for every new aggregate leading-phrase against the negative-assertion sites.

**Release gates:**

- Full suite green: `uv run pytest tests/`
- Real-data spot check: `uv run tax-reporting 2>&1 | grep -c WARNING` single-digit reduction on the 4 patterns.
- `--log-level DEBUG` run still shows all 91 per-row lines (predecessor Design Invariant #3 holds).
- Manual Excel spot check: Crypto Gains review column for J/K/L rows unchanged.
- `review-plan` gate: latest review artifact `ready=yes`, Blocker=0, Medium=0.

## Review Scope

**Explicit must-fix**; findings on these paths are always in scope (review and fix if valid):

**Production code:**
- `src/tax_reporting/application/crypto/fee_filter.py` *(pattern I: `_log_fee_removals` per-row → DEBUG + group-collapse aggregate)*
- `src/tax_reporting/application/crypto_fifo/cross_asset.py` *(pattern J: 4 per-row WARNINGs → DEBUG; counter threaded through `resolve_cross_asset_exchanges`)*
- `src/tax_reporting/application/crypto_fifo/transfer.py` *(pattern K: 2 per-row WARNINGs → DEBUG; counter returned to caller)*
- `src/tax_reporting/application/crypto/aggregation.py` *(pattern L: 2 per-row WARNINGs → DEBUG + post-loop aggregate)*
- `src/tax_reporting/application/crypto/fifo_helpers.py` *(thread J/K counters through `_process_single_asset_fifo`; emit aggregates in `_rebuild_fifo_for_loan_affected_assets`)*

**Tests:**
- `tests/unit/application/test_fee_filter.py` *(rewrite 2 pattern-I caplog tests)*
- `tests/unit/application/test_crypto_fifo.py` *(rewrite `TestResolveCrossAssetUnmatchedDeferredSetsReviewRequired`; add aggregate tests for J, K)*
- `tests/unit/application/test_crypto_reporting.py` *(add L aggregate test; verify pattern-K transfer review-reason assertion at `:7867` still holds)*

**Docs:**
- `docs/maintenance/project-guidelines.md` *(correct rule #7)*

**Plan-related extension**; implementation and review may change files not listed above. Treat a finding as in scope when it is **causally related to this plan**: it implements or completes a plan task, fixes a regression introduced by plan work, closes wiring or docs implied by an explicit must-fix change, or contradicts a contract the plan changed. If the link to the plan is weak or speculative, drop as out of scope with a one-line reason.

**Out of scope; reject unless plan-related:**
- `cross_asset.py:48` ("Cyclic swap dependency detected") and `transfer.py:48` ("Cyclic transfer dependency detected between platforms"): single-emission per run, genuine invariant signal, NOT per-row noise. Stay WARNING.
- `aggregation.py:459`: the derivatives/fee dedup-summary WARNINGs and "Filtered N sub-1-EUR entries" / "Surfaced N suspect untagged network fees" - already aggregate summaries from the predecessor. Stay WARNING.
- Any DATA_DROPPED / PARSE_ERROR / INVARIANT_VIOLATION site not in the 4 patterns above.
- The file-handler level (`logging_config.py` stays `logging.DEBUG`).
- Crypto data-flow / FIFO correctness - this plan changes logging only; `review_required` / `review_reason` / `cost_basis_eur` values are untouched.

## Design Invariants (CR Guard)

1. **Pattern I stays WARNING.** The single collapsed aggregate for untagged-whitelisted fee removals is emitted at `logger.warning(...)`, NOT DEBUG. Rationale: no Excel review surface exists for these removals; the WARNING is the only audit trail. Only the per-tx_hash detail moves to DEBUG. Getting this backwards deletes the audit trail. (Predecessor rule #7's correct core.)
2. **J/K/L per-row detail preserved at DEBUG.** The conversion lowers the level, never deletes the emission. Rationale: predecessor Design Invariant #3; the file handler (`logs/tax-reporting.log`, hardcoded DEBUG) is where the per-row context (tx_key, carry-over reason, asset, date) remains retrievable. Verified by the predecessor's existing regression test `test_file_handler_receives_debug_when_console_at_warning`.
3. **Excel review column unchanged for J/K/L.** `review_required` / `review_reason` / `cost_basis_eur` on the resolved acquisition / aggregated entry are NOT modified by this plan. The conversion touches logging only. Rationale: the review surface is what justifies the downgrade; altering it would change the user-facing output and break the justification.
4. **J/K aggregates emitted ONCE per run, not per-asset.** Because `resolve_cross_asset_exchanges` and `_resolve_intra_asset_transfers` are called inside the per-asset (`_process_single_asset_fifo`) and per-platform loops, the aggregate cannot be emitted inside the leaf function. It must use the predecessor pattern-F single-cell mutable counter mechanism threaded to `_rebuild_fifo_for_loan_affected_assets` and emitted once after the per-asset loop. Rationale: emitting inside the leaf fires N times (one per asset/platform), re-introducing the noise at a different layer.
5. **J aggregate preserves per-cause breakdown.** The single J aggregate names all 4 sub-causes (unresolved / zero-carryover / partial / multi-sender) with per-cause counts, not a bare total. Rationale: the 4 branches have different actionable meanings ("permanently overstated gain" vs "understated cost"); collapsing to one number destroys the signal the predecessor's per-row lines carried.
6. **Aggregate wording distinct from every negative-test substring.** Each new aggregate's leading phrase must not appear in any `assert not any(... in r.getMessage())` site. Rationale: predecessor pattern-D lesson - a colliding substring silently breaks the negative test. K's wording avoids the existing `"transfer_in_deferred acquisition"` at `test_crypto_fifo.py:436`. A Validation Command re-verifies at execution time.
7. **Rule #7 correction is scoped, not rewritten wholesale.** The edit lifts the downgrade prohibition for J/K only, keeps I forbidden, and adds L to the "has a surface" list. It must NOT lift the prohibition for I or weaken the general "data-loss conditions must be logged at warning+" principle. Rationale: I genuinely lacks a surface; over-broadly relaxing the rule would license future unsafe downgrades.
8. **Predecessor Design Invariants carry over unchanged.** Console-only control of `LOG_LEVEL`, CLI-overrides-config, invalid-value fails fast, case-insensitive parsing - all predecessor invariants remain in force; this plan adds no new config and changes no wiring in `logging_config.py` / `config.py` / `main.py`.

## Validation Commands

```bash
# Anti-collision gate: each new aggregate leading-phrase must NOT appear in any test
# (zero matches expected for all 5 phrases)
for phrase in \
  "Removed N untagged-whitelisted fee disposal" \
  "N cross-asset deferred acquisition(s) flagged" \
  "N transfer carry-over acquisition(s) flagged" \
  "N aggregated capital-gains entry(ies) with" ; do
  echo "=== $phrase ==="
  grep -rn "$phrase" tests/ && echo "COLLISION (must fix wording)" || echo "OK (no collision)"
done

# Pattern I: per-row moved to DEBUG (single site expected, was WARNING)
grep -n "Removed untagged-whitelisted fee disposal" src/tax_reporting/application/crypto/fee_filter.py
# Expect: 1 match, inside a logger.debug(...) call

# Patterns J/K/L: per-row WARNINGs downgraded to DEBUG
grep -n "logger.debug" src/tax_reporting/application/crypto_fifo/cross_asset.py \
  src/tax_reporting/application/crypto_fifo/transfer.py \
  src/tax_reporting/application/crypto/aggregation.py | \
  grep -E "carry-over|deferred acquisition|transfer_in_deferred|no acquisition date|epoch sentinel"

# Rule #7 correction: J/K no longer listed as "no surface"; I still is
grep -n "cross-asset FIFO unresolved-deferred-acquisition\|transfer carry-over review\|untagged-whitelist fee removal" docs/maintenance/project-guidelines.md
# Expect: untagged-whitelist prohibition REMAINS; cross-asset/transfer prohibition REMOVED (now permitted with surface)

# Single source of truth still holds (predecessor Task 1; this plan does not touch it)
grep -n '"INFO"\|"WARNING"' src/tax_reporting/main.py src/tax_reporting/infrastructure/logging_config.py src/tax_reporting/domain/constants.py | grep -v 'choices=\['
# Expect: zero matches

# Full suite
uv run pytest tests/

# Real-data signal-to-noise: the 4 patterns collapse from 91 per-row lines to ~4 aggregates
uv run tax-reporting 2>&1 | grep -c WARNING
# Expect: ~26 (down from 113); the 4 new aggregates account for the difference vs the ~22 legitimate lines

# Audit-trail preservation: per-row detail still in file at DEBUG
uv run tax-reporting --log-level DEBUG 2>&1 | grep -cE "untagged-whitelisted fee disposal|carry-over cost|transfer_in_deferred|no acquisition date"
# Expect: counts match the 91-row baseline for these patterns
```

### Task 1: Pattern I - group-collapse untagged-whitelisted fee removals (RED→GREEN)

**Scope reminder:** I is **group-collapse at WARNING**, NOT a downgrade. The single aggregate stays WARNING; only the per-tx_hash lines move to DEBUG. Distinct from J/K/L.

Files:
- `src/tax_reporting/application/crypto/fee_filter.py`
- `tests/unit/application/test_fee_filter.py`

- [x] `TestFeeRemovalLogging#test_untagged_whitelisted_per_row_at_debug_and_one_aggregate_warning` (rewrite of the assertion at `test_fee_filter.py:886-906`); given one untagged-whitelisted withdrawal matched to a CG lot, expects: the per-tx_hash detail ("Removed untagged-whitelisted fee disposal for SOL", "0.3", "0xAAA") is captured at **DEBUG** (caplog at DEBUG), AND exactly ONE WARNING-level record matching the new aggregate leading-phrase `"Removed N untagged-whitelisted fee disposal"` carrying the count and per-asset breakdown. The aggregate wording MUST contain `"disposal(s)"` (pluralizable) to distinguish from the per-row singular `"disposal for"`.
- [x] `TestFeeRemovalLogging#test_tagged_removal_does_not_emit_untagged_aggregate` (rewrite of the negative assertion at `test_fee_filter.py:943-947`); given a tagged `Cost` removal, expects NO WARNING-level record matching the new aggregate leading-phrase `"Removed N untagged-whitelisted fee disposal"` AND no DEBUG record containing `"Removed untagged-whitelisted fee disposal for"`. Verifies the aggregate wording does not collide with the tagged path. **Wording discipline (r1 finding #3):** the aggregate string `"Removed %d untagged-whitelisted fee disposal(s) (%s); ..."` contains the per-row prefix `"Removed untagged-whitelisted fee disposal"` as a substring; the `not any(...)` predicate MUST key on the aggregate-distinguishing tail (`"disposal(s) ("` or `"verify each is a network fee"`), NOT on the shared `"Removed untagged-whitelisted fee disposal"` prefix alone, otherwise a mixed tagged+untagged fixture would let the aggregate trip the negative check. The Task 1 grep-gate (count of `"Removed untagged-whitelisted fee disposal for"` == 1) is the load-bearing invariant; the negative-test assertion mirrors it.
- [x] Run → expect RED: `uv run pytest tests/unit/application/test_fee_filter.py -k "untagged_whitelisted_per_row_at_debug or tagged_removal_does_not_emit_untagged_aggregate"`
- [x] In `_log_fee_removals` (`fee_filter.py:378`): change the `else:` branch emission at `:411` from `logger.warning(...)` to `logger.debug(...)`. Keep the message text identical (asset, Net Value, tx_hash). The `if event.tagged:` INFO branch (`:394`) and `elif is_embedded:` INFO branch (`:404`) are UNCHANGED.
- [x] Because `_log_fee_removals` receives `matched_metadata` (the full list) and iterates it once, accumulate the per-row breakdown INSIDE the existing loop and emit ONE aggregate at the end of `_log_fee_removals`: build a `Counter[str]` keyed by `event.asset` incremented in the `else:` branch; after the loop, when non-empty emit `logger.warning("Removed %d untagged-whitelisted fee disposal(s) (%s); per-tx_hash detail at DEBUG; verify each is a network fee, not a real disposal", total, ", ".join(f"{a}: {n}" for a, n in sorted(counter.items())))`. NOTE: `_log_fee_removals` is called once per run from `remove_transaction_fees` (`:531`), after the existing dedup-summary WARNING at `:529`; the new aggregate is a second WARNING from this call. This is correct - the dedup summary covers ALL removals; this aggregate covers only the untagged-whitelisted subset that needs per-row verification.
- [x] Grep-gate: `grep -c "Removed untagged-whitelisted fee disposal for" src/tax_reporting/application/crypto/fee_filter.py` returns exactly 1 (the DEBUG per-row); the aggregate uses `"disposal(s) ("` and must NOT contain `"disposal for"`.
- [x] Run → expect GREEN: `uv run pytest tests/unit/application/test_fee_filter.py`
- [x] Commit: `refactor(crypto): group-collapse untagged-whitelisted fee removal warnings (pattern I)`

### Task 2: Pattern J - cross-asset deferred-acquisition per-row → DEBUG + threaded aggregate (RED→GREEN)

Files:
- `src/tax_reporting/application/crypto_fifo/cross_asset.py`
- `src/tax_reporting/application/crypto/fifo_helpers.py`
- `tests/unit/application/test_crypto_fifo.py`

**Context:** J has 4 per-row WARNING sites in `_resolve_single_acquisition` (`cross_asset.py:159` unresolved, `:189` multi-sender, `:197` zero-carryover, `:204` partial). `_resolve_single_acquisition` is called from `resolve_cross_asset_exchanges` (`:241`, a dict comprehension over `acquisitions_by_asset`), which is called from `_process_single_asset_fifo` (`fifo_helpers.py:149`), which runs per-asset inside `_rebuild_fifo_for_loan_affected_assets`. The aggregate must fire ONCE - use the predecessor pattern-F single-cell mutable counter threaded to `_rebuild_fifo_for_loan_affected_assets`.

**Test-wrapper note (r2 finding #1):** the in-test wrapper `resolve_cross_asset_exchanges` at `tests/unit/application/test_crypto_fifo.py:102` does NOT forward `flag_counts`; leave it UNCHANGED so direct-call tests see `flag_counts=None` (default) and the aggregate is not exercised by those tests. Only the production caller in `fifo_helpers._process_single_asset_fifo` threads the counter.

- [x] `TestResolveCrossAssetUnmatchedDeferredSetsReviewRequired#test_unmatched_deferred_flagged` (REWRITE, `test_crypto_fifo.py:917-951`); the existing assertion at `:951` `assert any("unresolved" in rec.message.lower() or "deferred" in rec.message.lower() for rec in caplog.records)` is at WARNING and breaks when the per-row moves to DEBUG. Rewrite to: keep the `review_required is True` / `review_reason` / `cost_basis_eur == 0` field assertions (`:945-950`, substantive, unchanged); replace the caplog line with an assertion that the per-row detail is reachable at DEBUG: `with caplog.at_level(logging.DEBUG): ... ; assert any("unresolved" in r.getMessage().lower() for r in caplog.records if r.levelno == logging.DEBUG)`. NOTE: this test calls `resolve_cross_asset_exchanges` directly (not via `_rebuild_fifo_for_loan_affected_assets`), so it bypasses the aggregate emission - the rewrite asserts the DEBUG per-row, not the aggregate. The aggregate is covered by the new test below.
- [x] `TestResolveCrossAssetAggregateSummary#test_j_aggregate_emits_once_with_per_cause_breakdown` (NEW class + test); given 2 assets each producing 1 unresolved + 1 zero-carryover deferred acquisition, called via `_rebuild_fifo_for_loan_affected_assets` (or a thin harness that drives the per-asset loop), expects exactly ONE WARNING matching `"N cross-asset deferred acquisition(s) flagged"` that names all present sub-causes (unresolved, zero-carryover) with counts, AND the per-row detail reachable at DEBUG. Each resolved acquisition still has `review_required=True` + `review_reason` (unchanged).
- [x] **REWRITE two sibling J caplog tests that assert at WARNING on the multi-sender (`:189`) and partial (`:204`) emissions Task 2 downgrades to DEBUG (r1 finding #1).** Both use `caplog.at_level(logging.WARNING, logger="tax_reporting.application.crypto_fifo")` so DEBUG records are not captured and the `any(... in caplog.records)` assertions fail (RED, not silently green):
    - `TestResolveCrossAssetMultiSenderAmbiguity#test_multi_sender_sums_costs_and_sets_review_required` (`test_crypto_fifo.py:960`, caplog at `:982`, asserts `"multi-sender"`/`"multiple source"` at `:993-996`): keep the `review_required`/`review_reason`/`cost_basis_eur` field assertions (`:987-992`); drop or switch the caplog assertion at `:993-996` to assert the per-row detail at DEBUG (`with caplog.at_level(logging.DEBUG, logger="tax_reporting.application.crypto_fifo"): ... ; assert any("multi-sender" in r.getMessage().lower() for r in caplog.records if r.levelno == logging.DEBUG)`).
    - `test_partial_sender_match_flags_review_when_expected_sender_unprocessed` (`test_crypto_fifo.py:1023`, caplog at `:1048`, asserts `"partial"`/`"unprocessed"` at `:1059-1060`): keep the field assertions (`:1052-1058`); drop or switch the caplog assertion at `:1059-1060` to the DEBUG per-row form.
- [x] Run → expect RED: `uv run pytest tests/unit/application/test_crypto_fifo.py -k "test_unmatched_deferred_flagged or j_aggregate_emits_once_with_per_cause_breakdown or test_multi_sender_sums_costs_and_sets_review_required or test_partial_sender_match_flags_review_when_expected_sender_unprocessed"`
- [x] In `_resolve_single_acquisition` (`cross_asset.py:144`): add a `flag_counts: dict[str, int] | None = None` parameter (default `None` for backward-compat with direct callers like the rewritten test above). In each of the 4 WARNING branches (`:159`, `:189`, `:197`, `:204`), downgrade `logger.warning(...)` → `logger.debug(...)` (message text unchanged); when `flag_counts is not None`, increment `flag_counts[cause_key] = flag_counts.get(cause_key, 0) + 1` with `cause_key` in `{"unresolved", "multi_sender", "zero_carryover", "partial"}`. The `review_required`/`review_reason`/`cost_basis_eur` assignments in each branch are UNCHANGED (Design Invariant 3).
- [x] In `resolve_cross_asset_exchanges` (`cross_asset.py:241`): add `flag_counts: dict[str, int] | None = None` parameter; pass it through to `_resolve_single_acquisition` in the comprehension. Do NOT emit here (would fire once per asset-set; the caller loop is the right site).
- [x] In `_process_single_asset_fifo` (`fifo_helpers.py:111`): add a `cross_asset_flag_counts: dict[str, int]` parameter (threaded mutable dict, single shared instance); pass it to `resolve_cross_asset_exchanges` at `:149`. Model on the existing `total_unmatched_taxable: list[int]` threading at `:120`/`:184`.
- [x] In `_rebuild_fifo_for_loan_affected_assets` (`fifo_helpers.py:204`): declare `cross_asset_flag_counts: dict[str, int] = {}` alongside `total_unmatched_taxable` at `:278`; pass it to `_process_single_asset_fifo` at `:291`; after the per-asset loop (next to the pattern-F aggregate at `:306`), when non-empty emit ONE WARNING: `logger.warning("%d cross-asset deferred acquisition(s) flagged (%s); see DEBUG log and Crypto Gains review column for per-row detail", total, ", ".join(f"{k}: {v}" for k, v in sorted(cross_asset_flag_counts.items())))` where `total = sum(cross_asset_flag_counts.values())`.
- [x] Run → expect GREEN: `uv run pytest tests/unit/application/test_crypto_fifo.py`
- [x] Commit: `refactor(crypto): group cross-asset deferred-acquisition warnings via threaded counter (pattern J)`

### Task 3: Pattern K - transfer carry-over per-row → DEBUG + threaded aggregate (RED→GREEN)

Files:
- `src/tax_reporting/application/crypto_fifo/transfer.py`
- `src/tax_reporting/application/crypto/fifo_helpers.py`
- `tests/unit/application/test_crypto_fifo.py`

**Context:** K has 2 per-row WARNING sites in `_resolve_intra_asset_transfers` (`transfer.py:104` requires-review, `:123` could-not-resolve). This function is called per-platform inside the per-asset loop in `_process_single_asset_fifo` (`fifo_helpers.py:177`). Same threading shape as Task 2. Anti-collision: the existing comment at `test_crypto_fifo.py:436` contains `"transfer_in_deferred acquisition"`; the aggregate wording uses `"transfer carry-over acquisition(s) flagged"` to avoid it.

- [x] `TestResolveIntraAssetTransfersAggregateSummary#test_k_aggregate_emits_once_after_all_platforms` (NEW class + test); given 2 platforms each producing 1 unresolved transfer_in_deferred, called via the per-platform loop, expects exactly ONE WARNING matching `"N transfer carry-over acquisition(s) flagged"` AND per-row detail at DEBUG. Each resolved acquisition keeps `review_required=True` + `review_reason` (unchanged). Verify the existing assertion at `test_crypto_reporting.py:7867` (`"Transfer carry-over should be available. Got: {bybit_entry.review_reason}"`) still holds - it asserts on the review_reason field, not caplog, so it must remain green.
- [x] **REWRITE the existing K caplog test that asserts at WARNING on the `transfer.py:123` "Could not resolve transfer_in_deferred ... carry-over not found" emission Task 3 downgrades to DEBUG (r1 finding #2).** `TestHandleTransferNoUnresolvedCarryover#test_unresolved_transfer_gets_zero_cost_and_review` (`test_crypto_fifo.py:2861`) opens `caplog.at_level(logging.WARNING)` at `:2873` and asserts at `:2881` `any("carry-over not found" in r.message.lower() for r in caplog.records)`; after the downgrade the DEBUG record is not captured and this fails (RED). Keep the field assertions (`cost_basis_eur == 0`, `review_required`, `review_reason is not None`, `"carry-over not available" in review_reason` at `:2876-2880`); drop or switch the caplog assertion at `:2881` to the DEBUG per-row form (`with caplog.at_level(logging.DEBUG): ... ; assert any("carry-over not found" in r.getMessage().lower() for r in caplog.records if r.levelno == logging.DEBUG)`).
- [x] Run → expect RED: `uv run pytest tests/unit/application/test_crypto_fifo.py -k "k_aggregate_emits_once_after_all_platforms or test_unresolved_transfer_gets_zero_cost_and_review"`
- [x] In `_resolve_intra_asset_transfers` (`transfer.py:56`): add a `flag_counts: dict[str, int] | None = None` parameter; in the 2 WARNING branches (`:104` requires-review, `:123` could-not-resolve) downgrade `logger.warning(...)` → `logger.debug(...)`; when `flag_counts is not None`, increment with `cause_key` in `{"requires_review", "unresolved"}`. The `review_required`/`review_reason`/`cost_basis_eur` assignments are UNCHANGED.
- [x] In `_process_single_asset_fifo` (`fifo_helpers.py:111`): add `transfer_flag_counts: dict[str, int]` parameter; pass it to `_resolve_intra_asset_transfers` at `:177`.
- [x] In `_rebuild_fifo_for_loan_affected_assets` (`fifo_helpers.py:204`): declare `transfer_flag_counts: dict[str, int] = {}`; pass to `_process_single_asset_fifo` at `:291`; after the per-asset loop, when non-empty emit ONE WARNING: `logger.warning("%d transfer carry-over acquisition(s) flagged (%s); see DEBUG log and Crypto Gains review column for per-row detail", total, ", ".join(f"{k}: {v}" for k, v in sorted(transfer_flag_counts.items())))`.
- [x] Grep-gate (anti-collision): `grep -rn "transfer carry-over acquisition(s) flagged" tests/` returns zero (wording is distinct from `"transfer_in_deferred acquisition"` at `:436`).
- [x] Run → expect GREEN: `uv run pytest tests/unit/application/test_crypto_fifo.py`
- [x] Commit: `refactor(crypto): group transfer carry-over warnings via threaded counter (pattern K)`

### Task 4: Pattern L - aggregation no-acquisition-date per-row → DEBUG + post-loop aggregate (RED→GREEN)

Files:
- `src/tax_reporting/application/crypto/aggregation.py`
- `tests/unit/application/test_crypto_reporting.py`

**Context:** L has 2 per-row WARNING sites in `_aggregate_capital_entries` (`aggregation.py:346` no-acquisition-date, `:353` epoch-sentinel). Unlike J/K, this function is NOT called inside a per-asset loop - it's called once from `crypto_reporting.py:562`. So the counter + post-loop aggregate fits directly inside `_aggregate_capital_entries` (the predecessor's "EASY" pattern-A shape). The `:459` derivatives/fee dedup-summary WARNING is a DIFFERENT function (`_aggregate_capital_entries`'s sibling) and is out of scope.

- [x] `TestAggregateCapitalEntries#test_l_aggregate_collapses_no_acquisition_date_warnings` (NEW class + test, add to `test_crypto_reporting.py`); given 3 aggregated entries each with an empty acquisition date (pool-exhausted placeholder lots), expects exactly ONE WARNING matching `"N aggregated capital-gains entry(ies) with"` that names the affected assets, AND per-row detail at DEBUG. The aggregated entries still carry `review_required=True` + the inherited pool-exhausted `review_reason` (unchanged - verify via field assertion, since this is what surfaces in the Excel "YES:" cell).
- [x] Run → expect RED: `uv run pytest tests/unit/application/test_crypto_reporting.py -k "l_aggregate_collapses_no_acquisition_date_warnings"`
- [x] In `_aggregate_capital_entries` (`aggregation.py:321`): declare `no_date_entries: Counter[str] = Counter()` before the `for group in groups.values():` loop. In the `if not acquisition_date:` branch (`:346`) downgrade `logger.warning(...)` → `logger.debug(...)`; `no_date_entries[first.asset] += 1`. In the `elif acquisition_date.startswith("1970-"):` branch (`:353`) do the same with a separate `epoch_entries: Counter[str]` (or a combined counter keyed by cause). After the loop, when either counter is non-empty emit ONE WARNING: `logger.warning("%d aggregated capital-gains entry(ies) with missing/epoch acquisition dates from pool-exhausted placeholders (%s); see DEBUG log and Crypto Gains review column for details", total, ", ".join(f"{a}: {n}" for a, n in sorted(combined.items())))`.
- [x] Run → expect GREEN: `uv run pytest tests/unit/application/test_crypto_reporting.py`
- [x] Commit: `refactor(crypto): group aggregation no-acquisition-date warnings into single summary (pattern L)`

### Task 5: Correct project-guidelines rule #7

Files:
- `docs/maintenance/project-guidelines.md`

- [x] Edit rule #7 (`docs/maintenance/project-guidelines.md:53`): in the "Do NOT downgrade sites that have NO review-list surface" sentence, REMOVE "cross-asset FIFO unresolved-deferred-acquisition" and "transfer carry-over review" from the forbidden list (they DO have a surface via `review_required=True` → Crypto Gains "YES:" cell). KEEP "untagged-whitelist fee removals" (pattern I - genuinely no surface, stays per-row-DEBUG-collapsed-to-one-WARNING per Task 1). ADD a clarifying clause: "cross-asset deferred-acquisition and transfer carry-over resolution DO set `review_required=True` + `review_reason` that surfaces as the Crypto Gains 'YES:' cell, so they follow the per-row-DEBUG + aggregate-WARNING convention (patterns J, K); aggregated entries with pool-exhausted placeholder acquisition dates likewise (pattern L)." Do NOT weaken the general "data-loss conditions must be logged at warning+" principle (Design Invariant 7).
- [x] Grep-gate: `grep -n "untagged-whitelist fee removal" docs/maintenance/project-guidelines.md` returns the prohibition still present; `grep -n "cross-asset FIFO unresolved-deferred-acquisition" docs/maintenance/project-guidelines.md` returns zero (removed) or the corrected clarifying clause.
- [x] Commit: `docs: correct project-guidelines rule #7 (J/K/L have a review surface; I does not)`

### Task 6: Full-suite verification

Files: (no edits; verification only)

- [x] Run: `uv run pytest tests/` → expect all green (predecessor baseline + this plan's new/rewritten tests), zero failures.
- [x] Run (r1 finding #1/#2 gate): `uv run pytest tests/unit/application/test_crypto_fifo.py -k "test_multi_sender_sums_costs_and_sets_review_required or test_partial_sender_match_flags_review_when_expected_sender_unprocessed or test_unresolved_transfer_gets_zero_cost_and_review"` → expect GREEN, confirming the three sibling caplog tests rewritten in Tasks 2/3 pass after the J/K downgrade.
- [x] Run: `uv run tax-reporting 2>&1 | grep -c WARNING` → expect ~26 (down from 113); the 4 new aggregates (I/J/K/L) replace 91 per-row lines.
- [x] Run: `uv run tax-reporting --log-level DEBUG 2>&1 | grep -cE "untagged-whitelisted fee disposal|carry-over cost|transfer_in_deferred|no acquisition date"` → expect counts matching the 91-row baseline (audit trail preserved at DEBUG).
- [x] Run anti-collision gate (Validation Commands block): all 4 new aggregate phrases return zero matches in `tests/`.
- [x] Manual: open `resources/result/extract.xlsx` Crypto Gains sheet; spot-check that review-column "YES:" rows for J/K/L patterns are unchanged in count and content vs a pre-change baseline run (conversion is logging-only; Design Invariant 3).

## Monitor

- **Pattern I aggregate wording shares the per-row substring** (r1 finding #3, consistency). The aggregate `"Removed N untagged-whitelisted fee disposal(s)"` contains the per-row prefix `"Removed untagged-whitelisted fee disposal"`. The plan's Validation Command anti-collision gate greps the full phrase with the count placeholder and reports OK; the load-bearing Task 1 grep-gate (`"disposal for"` count == 1) holds. Risk is limited to the rewritten negative test `test_tagged_removal_does_not_emit_untagged_aggregate`: its `not any(...)` predicate must key on the aggregate tail (`"disposal(s) ("`), not the shared prefix, or a future mixed tagged+untagged fixture could mask the distinction. Mitigated by the wording-discipline note folded into Task 1; monitor at execution time that the negative assertion does not regress to the broad prefix. Owner: plan executor (Task 1).
- **Pattern I count-invariant is load-bearing** (r2 finding #2, consistency). The new aggregate's `if counter:` guard must emit ONLY when the `else:` (untagged-whitelisted) branch accumulated entries, so the tagged-removal test (`test_fee_filter.py:1561`) and the disabled-flag no-op test (`:1604`, `assert not caplog.records`) never see it. The plan already states "when non-empty emit" and "the tagged/embedded INFO paths are UNCHANGED" (Task 1). Execution-time verification: confirm the `Counter[str]` is incremented solely inside the `else:` branch and the guard is `if counter:` (not unconditional). Owner: plan executor (Task 1).
- **Pattern I's group-collapse pushes per-tx_hash detail off-console** (plan creation). If a future workflow relies on `grep WARNING` on the console to find a specific suspicious tx_hash, it must grep `logs/tax-reporting.log` at DEBUG instead. Documented in Gist; no owner action unless that workflow is discovered.
