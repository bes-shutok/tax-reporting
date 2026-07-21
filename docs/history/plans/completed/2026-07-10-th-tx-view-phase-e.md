# Plan: TH-anchored Transaction view - Phase E (drop legacy)

RFC: [docs/history/context/2026-06-20-th-anchored-transaction-state-machine.md](../context/2026-06-20-th-anchored-transaction-state-machine.md#rollout-plan-2026-07-05) (Phase E, final phase of the five-phase rollout; Phases A-D all landed on `master`).

Prior phases (all on `master`):
- Phase A at `bb46bdd` - typed `Transaction` + `TxCorrelationKey` + `WalletKind`. Plan: [completed/2026-07-05-th-tx-view-phase-a.md](completed/2026-07-05-th-tx-view-phase-a.md).
- Phase B at `cdb10bf` - closed `Treatment` enum + `resolve_treatment`. Plan: [completed/2026-07-06-th-tx-view-phase-b.md](completed/2026-07-06-th-tx-view-phase-b.md).
- Phase C at `d158904` - synthetic corpus + one-shot shadow (0 treatment divergence). Plan: [completed/2026-07-07-th-tx-view-phase-c.md](completed/2026-07-07-th-tx-view-phase-c.md).
- Phase D at `0449a9b` (`d2065fa` post-realign) - six per-treatment flags default ON; legacy adapters bypassed not deleted. Plan: [completed/2026-07-08-th-tx-view-phase-d.md](completed/2026-07-08-th-tx-view-phase-d.md).

Phase E gate satisfied: the user confirmed (2026-07-10) that tax year 2025 - the only Koinly year present (`resources/source/koinly2025/`) - has closed clean under the resolver path, so the bypass-not-delete choice no longer needs the legacy fallback.

Plan review: [r1](../reviews/2026-07-10-plan-review-th-tx-view-phase-e-r1.md) (3 Blockers + 4 Medium addressed in revision 2). [r2](../reviews/2026-07-10-plan-review-th-tx-view-phase-e-r2.md) (2 NEW Medium addressed in revision 3). [r3](../reviews/2026-07-10-plan-review-th-tx-view-phase-e-r3.md) (3 NEW Medium addressed in revision 4). [r4](../reviews/2026-07-10-plan-review-th-tx-view-phase-e-r4.md) (1 NEW Blocker + 1 NEW Medium addressed in revision 5). [r5](../reviews/2026-07-10-plan-review-th-tx-view-phase-e-r5.md) - **verdict: ready=yes, Blocker=0, Medium=0, 4 Low + 3 Monitor (folded into Task 10 + ## Monitor)**. Latest ready review: r5.

## Terms

- **Treatment** - the Phase-B closed enum (`domain/treatment.py`) with six
  values (`SPOT_DISPOSAL`, `PAYMENT`, `LOAN_REPAYMENT`, `DERIVATIVES_CLOSE`,
  `REWARD_AIRDROP_LP`, `OTHER`) computed by
  `application/crypto/treatment_resolver.py::resolve_treatment`. Unchanged by
  Phase E.
- **Per-treatment flag** - the six boolean `treatment_*_via_resolver` fields
  on `TaxJurisdictionConfig` (`domain/jurisdiction.py:144-149`) added by
  Phase D, all defaulting to `True`. Phase E DELETES these fields, the
  required-presence loader guard in `infrastructure/config.py`, the flag
  lines in `docs/maintenance/tax/decision_points/2025.toml` (both country
  sections), and the DP-019 documentation in `2025.md`.
- **Legacy adapter** - one of the four Phase-D-bypassed code paths Phase E
  deletes:
  (a) `payment_proceeds.py` legacy scanner: `_DEFAULT_PAYMENT_TAGS`
  (`payment_proceeds.py:65`), `build_payment_tag_index` (line 297), the
  count-equality gate inside `correct_payment_proceeds` (lines ~640-660), and
  the `via_resolver` parameter on `correct_payment_proceeds`;
  (b) `crypto_fifo` legacy path: `_LOAN_PRINCIPAL_TAGS`
  (`crypto_fifo/contexts.py:24`) and the non-resolver branch in
  `discover_loan_affected_assets` (`crypto_fifo/parsing.py:87-127`);
  (c) `derivatives_dedup.py` legacy scanner: `find_derivatives_th_events`
  (lines 218-268) and the `via_resolver` legacy branch inside
  `apply_derivatives_dedup` (lines 527-532). The labels loader
  `_load_derivatives_labels_config*` (lines 104-159) and the
  `_DERIVATIVES_TH_TYPE` constant are NOT legacy - the resolver path
  consumes them (`_load_derivatives_labels_config` populates
  `TreatmentConfig.derivatives_tags` at `crypto_reporting.py:188`, read by
  `treatment_resolver.py:201`; `_DERIVATIVES_TH_TYPE` is read by
  `find_derivatives_th_events_from_transactions` at line 46). Phase E
  KEEPS both. Task 2 additionally refactors the labels-presence gate at
  `apply_derivatives_dedup:517-525` to read `config.derivatives_tags`
  (already injected by the caller) instead of re-loading via
  `_load_derivatives_labels_config`, eliminating the double-load; the
  empty-tags WARNING is preserved;
  (d) `token_origin.py` legacy tag literals: `_DEFAULT_REWARD_TAGS`,
  `_DEFAULT_AIRDROP_TAGS`, `_DEFAULT_LP_TAGS` (lines 47-49) and the
  `via_resolver` branch in `_index_row`, IF Task 4 verification confirms
  these constants are unused on the resolver path.
- **Re-zero snapshot/restore block** - the DP-014 residual-closing block in
  `crypto_reporting.py::load_koinly_crypto_report` (approximately lines
  383-500) that captures `proceeds_eur == 0` indices before the OGR override
  and restores them afterward. Phase D bypasses this block when BOTH
  `treatment_payment_via_resolver` and `treatment_spot_disposal_via_resolver`
  are on (lines ~408-409). Phase E deletes the block entirely; with both
  flags gone, the bypass condition is always true.
- **any_resolver_on gating** - the Phase-D optimization
  (`crypto_reporting.py:~171`) that skips `Transaction` construction when all
  six flags are off (full-rollback fast path). Phase E removes the gating;
  `Transaction` construction becomes unconditional whenever crypto data is
  loaded.
- **DerivativesThEvent** - the domain type produced by the derivatives TH
  scanner. Phase E relocates it with the surviving resolver-path functions
  when `derivatives_dedup.py` is renamed to `derivatives_filter.py`.
- **Phase-D all-flags-on baseline** - the Excel output captured by running
  the pipeline on `resources/source/koinly2025/` under the current Phase-D
  code (all six flags at their default `True`), before any Phase-E deletion.
  Phase E must produce byte-identical output to this baseline. Captured in
  Task 1; verified in Task 9.

## Gist & Examples

### What changes

Phase D (landed) flipped all six per-treatment classifiers to delegate to
`resolve_treatment`, gated by six `treatment_*_via_resolver` flags defaulting
to `True`. The legacy per-treatment adapters were BYPASSED, not deleted, to
preserve per-treatment rollback granularity during the 2025 tax year. Phase E
is pure deletion: tax year 2025 has closed clean under the resolver path, so
the legacy fallback is dead weight.

Concretely, Phase E removes four legacy adapters and the flag machinery:

1. **`payment_proceeds.py`** - `_DEFAULT_PAYMENT_TAGS`, the tag-index
   builder, the count-equality gate (review finding #14's root), and the
   `via_resolver` parameter. The surviving path is the resolver-delegating
   branch added in Phase D Task 4.
2. **`crypto_fifo/contexts.py` + `parsing.py`** - the `_LOAN_PRINCIPAL_TAGS`
   constant and the non-resolver branch of `discover_loan_affected_assets`.
   The surviving path is the resolver delegation with the Invariant 11
   `OTHER + tag=loan` clause (preserves borrow-only assets in the FIFO
   rebuild).
3. **`derivatives_dedup.py`** - renamed to `derivatives_filter.py`, drops the
   legacy `find_derivatives_th_events(path, labels)` scanner and the
   `via_resolver` branch inside `apply_derivatives_dedup`. Survives:
   `find_derivatives_th_events_from_transactions`, `remove_derivatives_flagged_lots`,
   `_log_removals_and_surplus`, `apply_derivatives_dedup` (resolver-only),
   `DerivativesThEvent`, the labels-config loader (`_load_derivatives_labels_config*`,
   which populates `TreatmentConfig.derivatives_tags` for the resolver), and
   the `_DERIVATIVES_TH_TYPE` constant (read by the resolver-path scanner).
   The labels-presence gate inside `apply_derivatives_dedup` (lines 517-525)
   is refactored to read `config.derivatives_tags` (already injected by the
   caller) instead of re-loading, preserving the empty-tags WARNING. The
   logger name `tax_reporting.application.crypto.derivatives_dedup` becomes
   `...derivatives_filter`; all log-assertion tests (including
   `test_th_lot_matcher.py`'s 5 logger-string references) update.
4. **`token_origin.py`** - the legacy tag-literal constants and `via_resolver`
   branch (Task 4 first verifies they are truly unused on the resolver path;
   `TreatmentConfig` supplies the resolver's own tag sets).
5. **`crypto_reporting.py` re-zero block** - the DP-014 snapshot/restore
   block becomes unreachable with both payment and spot-disposal flags gone;
   delete it. Also remove the `any_resolver_on` gating of `Transaction`
   construction (now unconditional) and every `via_resolver=` / `treatment_*_via_resolver`
   reference in the call sites.
6. **Flag machinery** - six fields from `domain/jurisdiction.py`, the
   required-presence loader guard from `infrastructure/config.py`, the flag
   lines from both PT and example sections of `2025.toml`, and the DP-019
   documentation from `2025.md`.

### Why

The bypass-not-delete choice (Phase D Invariant 1) was a deliberate hedge:
per-treatment rollback granularity during the 2025 tax year. With 2025 filed
clean under the resolver path, that hedge is no longer warranted. Carrying
the legacy code (and the six flags + their loader guard + their TOML lines +
the `via_resolver` plumbing at every call site) is now pure debt:
- `_DEFAULT_PAYMENT_TAGS`, `_LOAN_PRINCIPAL_TAGS`, and the derivatives
  labels loader are dead constants holding tag literals the resolver never
  consults.
- The count-equality gate (review finding #14's root) and the re-zero block
  (review findings #5/#10/#11) are structurally unreachable but still
  readable, which makes the pipeline harder to reason about.
- Six `via_resolver=` call sites and six flag fields are config surface that
  can never again take a useful value.

### Example (payment treatment)

Today (Phase D, all flags on):
- `correct_payment_proceeds(..., via_resolver=True)` consults
  `build_payment_tag_index` for the index (harmless: still built), but the
  count-equality gate is bypassed (Phase D Invariant 1 + 8).
- The re-zero snapshot/restore block in `crypto_reporting.py` is bypassed
  because both `treatment_payment_via_resolver` and
  `treatment_spot_disposal_via_resolver` are on.

After Phase E:
- `correct_payment_proceeds(...)` has no `via_resolver` parameter; the
  count-equality gate and `build_payment_tag_index` are deleted. The
  function identifies payment disposals purely from the TH `PAYMENT`-treatment
  rows supplied by the caller (which derives them via `resolve_treatment`).
- The re-zero block is gone; nothing captures or restores `proceeds_eur == 0`
  indices, because the resolver-keyed identification makes the OGR-mutates-a-
  payment-row residual structurally impossible (review findings #5/#10/#11
  are closed by construction, not by patch).

### Edge cases motivating the design

- **Borrow-only loan assets.** `discover_loan_affected_assets` under the
  resolver path needs the `OTHER + tag=loan` clause (Phase D Invariant 11)
  so assets whose only 2025 activity is a borrow (no repayment) stay in the
  FIFO rebuild. Phase E preserves this clause; only the legacy
  `_LOAN_PRINCIPAL_TAGS` membership check is deleted.
- **Logger rename ripple.** The derivatives WARNING summary and per-lot INFO
  records currently emit from logger `tax_reporting.application.crypto.derivatives_dedup`.
  Renaming the module renames the logger. Tests that assert these log
  records (e.g. `test_derivatives_dedup.py`, `test_phase_d_flip_derivatives_close.py`,
  `test_phase_c_corpus.py`) must update the asserted logger name. Task 2
  greps the test tree for the old logger string before the rename lands.
- **`fee_filter.py` sibling.** `fee_filter.py` imports from `th_lot_matcher`,
  not from `derivatives_dedup`; the rename touches `fee_filter.py` only via a
  docstring cross-reference (line 22). No structural change.
- **Byte-identical Excel guarantee.** Phase D proved the resolver path
  produces the SAME SUMMARY-LEVEL output as the legacy path on `koinly2025`
  (Phase C shadow: 0 treatment divergence; Phase D real-data smoke:
  matching row counts + aggregate totals). Phase E is the FIRST byte-level
  check: Task 1 captures the all-flags-on baseline; Task 9 verifies
  byte-identical output (per-file SHA256) via a throwaway script. A diff
  means a Phase-E deletion disturbed a resolver-path code path the
  summary-level checks could not detect (e.g. cell ordering, log output).

## Evaluation Criteria

**Quality dimensions:**
- **Correctness:** the crypto pipeline produces byte-identical Excel output
  vs. the Phase-D all-flags-on baseline captured in Task 1 (verified by a
  throwaway script in Task 9). The full test suite passes.
- **Maintainability:** zero references to `via_resolver` or
  `treatment_*_via_resolver` remain in `src/` or `tests/`. Zero references to
  the deleted constants (`_DEFAULT_PAYMENT_TAGS`, `_LOAN_PRINCIPAL_TAGS`,
  `_DEFAULT_REWARD_TAGS`/`_DEFAULT_AIRDROP_TAGS`/`_DEFAULT_LP_TAGS`, the
  derivatives labels loader). The orchestrator `crypto_reporting.py` stays
  under the ~500-line thin-orchestrator cap (CLAUDE.md). Em-dash check clean.
- **Regression coverage:** each surviving resolver-path behavior that had a
  Phase-D flip test is still asserted by a characterization test on the sole
  path (not deleted with the flag). The Phase-D flag/isolation/real-data-smoke
  tests are deleted entirely (they exist only to test the flag mechanism).
- **Config hygiene:** the six flags are absent from `jurisdiction.py`, the
  config loader, `2025.toml` (both sections), and `2025.md`; the
  required-presence loader guard is gone; a clean config load does not raise.

**Release gates:**
- Full test suite green (`uv run pytest`).
- Em-dash check passes (`check-no-em-dash.sh`).
- Throwaway real-data smoke (Task 9) reports byte-identical output when
  `TAX_REPORTING_PHASE_E_BASELINE_DIR` points at the captured baseline; the
  script is deleted after verification.
- No `via_resolver` / `treatment_*_via_resolver` grep hits in `src/` or
  `tests/`.

## Review Scope

**Explicit must-fix;** findings on these paths are always in scope (review
and fix if valid):

**Production code:**
- `src/tax_reporting/application/crypto/payment_proceeds.py`
- `src/tax_reporting/application/crypto_reporting.py`
- `src/tax_reporting/application/crypto_fifo/contexts.py`
- `src/tax_reporting/application/crypto_fifo/parsing.py`
- `src/tax_reporting/application/crypto/derivatives_dedup.py` *(renamed to `derivatives_filter.py`)*
- `src/tax_reporting/application/token_origin.py`
- `src/tax_reporting/domain/jurisdiction.py`
- `src/tax_reporting/infrastructure/config.py`

**Tests:**
- `tests/unit/application/test_phase_d_flags.py` *(deleted)*
- `tests/unit/application/test_phase_d_flag_isolation.py` *(deleted)*
- `tests/end_to_end/test_phase_d_real_data_smoke.py` *(deleted)*
- `tests/unit/application/test_phase_d_flip_payment.py` *(flag-mechanic assertions deleted; resolver-behavior assertions kept as characterization)*
- `tests/unit/application/test_phase_d_flip_spot_disposal.py` *(same)*
- `tests/unit/application/test_phase_d_flip_loan_repayment.py` *(same)*
- `tests/unit/application/test_phase_d_flip_derivatives_close.py` *(same; plus logger-name update)*
- `tests/unit/application/test_phase_d_flip_reward_airdrop_lp.py` *(same)*
- `tests/unit/application/test_phase_d_flip_other.py` *(same)*
- `tests/unit/application/test_derivatives_dedup.py` *(renamed to `test_derivatives_filter.py`; logger-name updates)*
- `tests/unit/application/test_th_lot_matcher.py` *(logger-name updates: 5 references to `tax_reporting.application.crypto.derivatives_dedup` at lines 236, 276, 298, 345, 383)*
- `tests/unit/application/test_payment_proceeds.py` *(via_resolver param removal)*
- `tests/unit/application/test_crypto_reporting.py` *(re-zero block assertions removed; via_resolver param removal; 22 flag references including `treatment_spot_disposal_via_resolver=False` kwarg at line 8770 and six-flag TOML literals at lines 8883-8888, 8939-8944, 8955-8960 - all must be removed or repointed; grep-driven sweep required)*
- `tests/unit/application/test_crypto_fifo.py` *(via_resolver param removal)*
- `tests/unit/application/test_phase_c_corpus.py` *(flag-mechanic assertions removed; logger-name update; behavior assertions kept; DIRECT IMPORTS of `_DEFAULT_PAYMENT_TAGS` (line 53), `_LOAN_PRINCIPAL_TAGS` (line 62), and the derivatives labels loader (line 52) must be repointed to `TreatmentConfig` fields or removed - these break at collection time once Tasks 2/3/4 land)*
- `tests/unit/application/test_treatment_resolver.py` *(no production change, but may reference flag constants)*
- `tests/unit/infrastructure/test_config.py` *(remove the required-presence-guard tests for the six flags)*
- `tests/end_to_end/test_crypto_derivatives_separation.py` *(via_resolver param removal; PLUS `derivatives_dedup` logger/module references at lines ~382, 426, 432, 601-602, 695, 698 must update to `derivatives_filter`; PLUS a stale `find_derivatives_th_events` docstring reference must update to `find_derivatives_th_events_from_transactions`)*

**Documentation / config:**
- `docs/history/context/2026-06-20-th-anchored-transaction-state-machine.md` *(Status + Rollout table: mark Phase E landed)*
- `docs/maintenance/tax/decision_points/2025.toml` *(remove six flag lines from both sections)*
- `docs/maintenance/tax/decision_points/2025.md` *(remove DP-019 documentation)*
- `CLAUDE.md` *(if any rule references the six flags; verify and update)*

**Plan-related extension;** implementation and review may change files not
listed above. Treat a finding as in scope when it is causally related to this
plan: it implements a Phase-E task, fixes a regression introduced by a
deletion here, closes wiring or docs implied by an explicit must-fix change,
or contradicts a contract this plan changed (e.g. the derivatives logger
rename ripples into any test that asserts the old logger name). If the link
is weak or speculative, drop as out of scope with a one-line reason.

**Out of scope; reject unless plan-related:**
- `src/tax_reporting/application/crypto/th_lot_matcher.py`; shared matching
  machinery, consumed by `fee_filter.py` too; Phase E changes only import
  paths if the derivatives rename moves a re-export, nothing structural.
- `src/tax_reporting/domain/transaction.py`, `domain/treatment.py`,
  `application/crypto/treatment_resolver.py`; Phase E changes nothing in the
  domain/resolver layer.
- `src/tax_reporting/application/crypto/fee_filter.py`; only a docstring
  cross-reference to the renamed derivatives module is in scope; no
  structural change.
- `src/tax_reporting/application/crypto/wallet_kind_registry.py`; Phase D
  addition, unchanged by Phase E.

## Design Invariants (CR Guard)

1. **Byte-identical Excel output vs. Phase-D all-flags-on baseline.** Phase E
   is pure deletion; the resolver was already authoritative at Phase D
   landing. CR guard: reject any task that changes resolver-path logic,
   `Transaction`/`Treatment`/`resolve_treatment` semantics, FIFO matching,
   or `th_lot_matcher` behavior. Task 9's byte-identical verification is the
   load-bearing check. Rationale: Phase C shadow + Phase D real-data smoke
   already proved equivalence; Phase E must not disturb it.
2. **`Transaction`/`TxCorrelationKey`/`Treatment`/`resolve_treatment` domain
   layer unchanged.** CR guard: reject any edit to `domain/transaction.py`,
   `domain/treatment.py`, or `application/crypto/treatment_resolver.py`.
3. **`th_lot_matcher.py` shared matching machinery unchanged.** Consumed by
   `fee_filter.py` (sibling matcher, repo rule #119). CR guard: reject
   structural changes to `th_lot_matcher.py`; only import paths may move
   with the derivatives rename. Rationale: a byte-identical non-regression
   on derivatives dedup depends on the shared matcher not drifting.
4. **Orchestrator `crypto_reporting.py` shrinks, not grows.** Phase E removes
   the re-zero block (~117 lines), the `any_resolver_on` gating, and all
   `via_resolver=` plumbing - a net reduction from the 1106-line pre-Phase-E
   baseline. The CLAUDE.md ~500-line thin-orchestrator cap is not achievable
   in this phase (the module was already 1106 lines at Phase D landing); the
   binding commitment is net reduction and no new inlined domain logic. CR
   guard: reject any task that inlines derivatives logic into the orchestrator
   or that leaves the orchestrator larger than 1106 lines post-Phase-E.
   Rationale: the rename-relocate choice for derivatives preserves downward
   pressure on orchestrator size; a future sub-orchestrator extraction (out
   of scope for Phase E) can pursue the ~500-line cap.
5. **Invariant 11 (`OTHER + tag=loan` clause) survives in
   `discover_loan_affected_assets`.** The resolver path needs this clause to
   keep borrow-only assets in the FIFO rebuild. CR guard: reject any task
   that removes the clause or reverts to pure `_LOAN_PRINCIPAL_TAGS`
   membership. Rationale: Phase D Invariant 11; without it, assets whose
   only 2025 loan activity is a borrow drop out of the FIFO rebuild.
6. **No new hardcoded values.** Phase E deletes tag literals; it must not
   introduce new ones. CR guard: reject any task that adds a magic string,
  threshold, or fixed ordering without flagging it and asking the user.
   Rationale: CLAUDE.md hard rule.
7. **Throwaway verification script is deleted at the end of its task.** The
   Task 9 baseline-diff script lives under `docs/tmp/` (gitignored) and is
   deleted after the byte-identical verification passes. CR guard: reject
   any task that promotes the script to a tracked location or leaves it on
   disk. Rationale: Phase C precedent + `feedback_throwaway_script_lifecycle`
   memory; the deletion task is load-bearing.
8. **Per-treatment classifier signatures lose `via_resolver` cleanly.** Each
   of `correct_payment_proceeds`, `discover_loan_affected_assets`,
   `apply_derivatives_dedup`, and the token_origin indexer drops the
   `via_resolver` parameter; callers stop passing it. CR guard: reject any
   task that leaves a `via_resolver` keyword at a call site or keeps a
   defaulted-to-True parameter "for future use". Rationale: dead parameters
   are the debt Phase E exists to remove.

## Validation Commands

```bash
# 1. Full test suite (the load-bearing gate).
uv run pytest

# 2. Zero residual references to the removed flag mechanism / params / constants.
#    NOTE: treatment_resolver.py defines SAME-NAMED surviving constants
#    (_DEFAULT_PAYMENT_TAGS, _DEFAULT_REWARD_TAGS, _DEFAULT_AIRDROP_TAGS,
#    _DEFAULT_LP_TAGS at lines 57/70/73/76) as TreatmentConfig defaults.
#    These are NOT deleted by Phase E. Scope the constant-grep to legacy homes.
! grep -rn "via_resolver\|treatment_.*_via_resolver" src/ tests/
! grep -nE "_DEFAULT_PAYMENT_TAGS|_LOAN_PRINCIPAL_TAGS" src/tax_reporting/application/crypto/payment_proceeds.py src/tax_reporting/application/crypto_fifo/contexts.py
! grep -nE "_DEFAULT_REWARD_TAGS|_DEFAULT_AIRDROP_TAGS|_DEFAULT_LP_TAGS" src/tax_reporting/application/token_origin.py
# 3b. Legacy derivatives scanner is gone (the resolver-path
#     find_derivatives_th_events_FROM_TRANSACTIONS survives).
! grep -rn "find_derivatives_th_events[^_]" src/ tests/   # legacy standalone gone
grep -rn "find_derivatives_th_events_from_transactions" src/ >/dev/null && echo "resolver scanner present"

# 3. Derivatives module rename consistency.
test -f src/tax_reporting/application/crypto/derivatives_filter.py
test ! -f src/tax_reporting/application/crypto/derivatives_dedup.py
grep -rn "derivatives_dedup" src/ tests/ | grep -v "derivatives_filter" || true   # expect empty

# 4. Config-side flag removal.
! grep -rn "treatment_.*_via_resolver" docs/maintenance/tax/decision_points/ src/tax_reporting/domain/jurisdiction.py src/tax_reporting/infrastructure/config.py

# 5. Orchestrator net-reduction (thin-orchestrator direction, not a hard cap).
#    Phase E removes the re-zero block (~117 lines) + any_resolver_on gating +
#    via_resolver plumbing; crypto_reporting.py must shrink, not grow.
#    Pre-Phase-E baseline: 1106 lines. Post-Phase-E must be <= 1106.
test "$(wc -l < src/tax_reporting/application/crypto_reporting.py)" -le 1106

# 6. Em-dash hygiene.
~/.ai-playbook/scripts/check-no-em-dash.sh

# 7. Throwaway real-data byte-identical verification (env-gated; script deleted after).
#    Run only when TAX_REPORTING_PHASE_E_BASELINE_DIR points at the Task 1 baseline.
if [ -n "${TAX_REPORTING_PHASE_E_BASELINE_DIR:-}" ]; then
  uv run python docs/tmp/phase-e-verify/verify_byte_identical.py "$TAX_REPORTING_PHASE_E_BASELINE_DIR"
fi
```

### Task 1: Capture Phase-D all-flags-on Excel baseline

Files:
- `docs/tmp/phase-e-verify/baseline/` *(new, gitignored; captured output + SHA256)*

- [x] Confirm the working tree is on branch `2026-07-10-th-tx-view-phase-e` at commit `d2065fa` (Phase D head); no Phase-E code change has landed yet.
- [x] Run the full crypto pipeline against `resources/source/koinly2025/` and write the resulting Excel + rollover CSV to `docs/tmp/phase-e-verify/baseline/` (use the existing `uv run tax-reporting` entry point with the production config).
- [x] Compute SHA256 of each output file; record the hashes in `docs/tmp/phase-e-verify/baseline/SHA256SUMS`.
- [x] Commit the `docs/tmp/phase-e-verify/` path to `.gitignore` verification (it is already covered by the `docs/tmp/` gitignore entry; confirm with `git check-ignore docs/tmp/phase-e-verify/baseline/SHA256SUMS`).
- [x] No commit (baseline is gitignored; this task produces no tracked artifact).

### Task 2: Rename `derivatives_dedup.py` to `derivatives_filter.py`; drop legacy scanner only

Files:
- `src/tax_reporting/application/crypto/derivatives_dedup.py` *(rename to `derivatives_filter.py`; delete ONLY `find_derivatives_th_events(path, labels)` and the `via_resolver` legacy branch of `apply_derivatives_dedup`. KEEP `_load_derivatives_labels_config*`, `_DERIVATIVES_TH_TYPE` - both are resolver-path.)*
- `src/tax_reporting/application/crypto_reporting.py` *(import rename; call-site kwargs: drop `year` and `via_resolver`; KEEP `transaction_history_file` - still used by the gate at line 513)*
- `src/tax_reporting/application/crypto/fee_filter.py` *(docstring cross-reference update only, line 22)*
- `src/tax_reporting/application/crypto/entities.py` *(docstring at line ~521 references `derivatives_dedup` module name - update to `derivatives_filter`)*
- `src/tax_reporting/application/crypto/th_lot_matcher.py` *(module docstring at line ~4 references `derivatives_dedup` - update to `derivatives_filter`)*
- `tests/unit/application/test_derivatives_dedup.py` *(rename to `test_derivatives_filter.py`; logger-name updates; delete legacy-scanner tests)*
- `tests/unit/application/test_th_lot_matcher.py` *(logger-name updates at 5 sites)*
- every test that asserts the logger name `derivatives_dedup` *(grep first, update all)*

- [x] `grep -rn "derivatives_dedup\|find_derivatives_th_events\b\|_load_derivatives_labels_config\|_DERIVATIVES_TH_TYPE" src/ tests/` to enumerate every reference (production + tests) before the rename.
- [x] VERIFY scope before editing: `find_derivatives_th_events_from_transactions` (resolver path) reads `_DERIVATIVES_TH_TYPE` at line 402 (absolute line in file; relative line 46 within the function body) - DO NOT delete the constant. `_load_derivatives_labels_config` populates `TreatmentConfig.derivatives_tags` at `crypto_reporting.py:188`, consumed by `treatment_resolver.py:201` - DO NOT delete the loader. Only `find_derivatives_th_events(path, labels)` (the standalone legacy CSV scanner, lines 218-268) is legacy.
- [x] `TestDerivativesFilter#test_resolver_path_produces_derivatives_events`; given a `list[Transaction]` whose treatment is `DERIVATIVES_CLOSE`, expects `find_derivatives_th_events_from_transactions` returns one `DerivativesThEvent` per matched transaction (characterization: must stay GREEN across the rename).
- [x] `TestDerivativesFilter#test_logger_name_after_rename`; given a derivatives-flagged CG lot matched and removed, expects the INFO/WARNING records emit from logger `tax_reporting.application.crypto.derivatives_filter` (NOT `...derivatives_dedup`).
- [x] `TestDerivativesFilter#test_empty_derivatives_tags_warns_via_injected_config`; given `TreatmentConfig(derivatives_tags=frozenset())` injected into `apply_derivatives_dedup`, expects the empty-tags WARNING fires and the input is returned unchanged (characterization for the B3 refactor: the labels-presence gate now reads `config.derivatives_tags`, not a re-load).
- [x] Run the characterization tests against the pre-rename module → expect GREEN (captures existing behavior).
- [x] `git mv src/tax_reporting/application/crypto/derivatives_dedup.py src/tax_reporting/application/crypto/derivatives_filter.py`; `git mv tests/unit/application/test_derivatives_dedup.py tests/unit/application/test_derivatives_filter.py`.
- [x] Inside the renamed module: delete `find_derivatives_th_events(path, labels)` (lines 218-268) and the `else` branch (`find_derivatives_th_events(transaction_history_file, labels)`) of `apply_derivatives_dedup` (lines 531-532). KEEP `_load_derivatives_labels_config*` and `_DERIVATIVES_TH_TYPE`. Drop the `via_resolver` parameter and the `year` parameter from `apply_derivatives_dedup` (the labels-presence gate no longer re-loads by year; it reads `config.derivatives_tags` instead). KEEP `transaction_history_file` (still used by the four-way gate at line 513). Rename the module logger `derivatives_dedup` to `derivatives_filter`.
- [x] Refactor the labels-presence gate (lines 517-525): replace `labels = _load_derivatives_labels_config(provider="koinly", year=year)` with reading `config.derivatives_tags` (already injected). The current WARNING (lines 519-524) interpolates `year` twice (`"...year %d;..." / "Add .../koinly_%d.json to enable.", year, year`); since Task 2 drops `year` from the signature, reword the WARNING to not interpolate `year` (e.g. "Derivatives tags empty in TreatmentConfig; CG dedup skipped. Populate docs/maintenance/tax/derivatives_labels/koinly_<year>.json for the active fiscal year.") OR thread `year` back through via a new keyword if the remediation hint's year-specificity is load-bearing. The empty-tags WARNING itself is preserved either way (characterization test pins it).
- [x] Update `crypto_reporting.py:46-48` import (`from .crypto.derivatives_filter import (...)`) and the call site at `crypto_reporting.py:~345` (drop `year` and `via_resolver` kwargs; KEEP `transaction_history_file`, `transactions`, `config`).
- [x] Update `fee_filter.py:22` docstring cross-reference.
- [x] Update every test's logger-name assertion from `derivatives_dedup` to `derivatives_filter` (including `test_th_lot_matcher.py` lines 236, 276, 298, 345, 383).
- [x] Delete legacy-scanner tests in `test_derivatives_filter.py` that exercised `find_derivatives_th_events(path, labels)` (no longer exists).
- [x] Run → expect GREEN (full suite).
- [x] Commit: `refactor(crypto): rename derivatives_dedup to derivatives_filter, drop legacy scanner`.

### Task 3: Delete legacy payment scanner + count-equality gate in `payment_proceeds.py`

Files:
- `src/tax_reporting/application/crypto/payment_proceeds.py`
- `src/tax_reporting/application/crypto_reporting.py` *(drop `payment_via_resolver` kwarg and the `payment_via_resolver = ... and jurisdiction.treatment_payment_via_resolver` guard at ~line 521)*
- `tests/unit/application/test_payment_proceeds.py`
- `tests/unit/application/test_phase_d_flip_payment.py` *(delete count-equality-gate tests; keep resolver-path behavior assertions as characterization)*

- [x] `grep -rn "_DEFAULT_PAYMENT_TAGS\|build_payment_tag_index\|count.equality\|count_equality\|via_resolver" src/ tests/` to enumerate references.
- [x] `TestPaymentProceeds#test_correct_payment_proceeds_identifies_via_resolver_only`; given a PAYMENT-treatment TH row + a zero-proceeds CG entry on the same key, expects the entry's proceeds corrected to the TH net value WITHOUT consulting `_DEFAULT_PAYMENT_TAGS` or the count-equality gate (characterization of the surviving path).
- [x] Run the characterization test against the current Phase-D code with `via_resolver=True` → expect GREEN.
- [x] In `payment_proceeds.py`: delete `_DEFAULT_PAYMENT_TAGS` (line 65), `build_payment_tag_index` (line 297), the count-equality gate inside `correct_payment_proceeds` (lines ~640-660), and the `via_resolver` parameter (line 548). The function's surviving body identifies payment disposals purely from the `PAYMENT`-treatment rows supplied by the caller.
- [x] Audit `PaymentProceedsConfig.payment_tags` (populated from `_DEFAULT_PAYMENT_TAGS`): if no surviving code path reads it, remove the field and its loader. Also grep `docs/maintenance/tax/popular_crypto_tokens.json` and any other config file for a `payment_tags` key; if present and now-orphaned, remove it. Flag to user before removing if uncertain.
- [x] Drop the `payment_via_resolver` plumbing from `crypto_reporting.py:~521-547` (the `if payment_via_resolver:` branch collapses to the resolver-delegating call).
- [x] In tests: delete every assertion that references `_DEFAULT_PAYMENT_TAGS`, `build_payment_tag_index`, or the count-equality gate; keep resolver-path behavior assertions.
- [x] Run → expect GREEN.
- [x] Commit: `refactor(crypto): drop legacy payment scanner and count-equality gate`.

### Task 4: Delete `_LOAN_PRINCIPAL_TAGS` legacy path in `crypto_fifo`

Files:
- `src/tax_reporting/application/crypto_fifo/contexts.py`
- `src/tax_reporting/application/crypto_fifo/parsing.py`
- `src/tax_reporting/application/crypto_reporting.py` *(drop `via_resolver` kwarg at the `discover_loan_affected_assets` call site, ~line 255)*
- `tests/unit/application/test_phase_d_flip_loan_repayment.py` *(delete legacy-branch tests; keep resolver-path behavior assertions)*
- `tests/unit/application/test_crypto_fifo.py` *(via_resolver param removal)*

- [x] `grep -rn "_LOAN_PRINCIPAL_TAGS\|via_resolver" src/tax_reporting/application/crypto_fifo/ tests/` to enumerate references.
- [x] `TestCryptoFifo#test_discover_loan_affected_assets_resolver_path_includes_borrow_only`; given TH rows with an `OTHER`+`tag=loan` borrow (no repayment) and a `LOAN_REPAYMENT` row, expects `discover_loan_affected_assets` returns both assets (Invariant 11; characterization).
- [x] Run the characterization test against the current Phase-D code with `via_resolver=True` → expect GREEN.
- [x] In `contexts.py`: delete `_LOAN_PRINCIPAL_TAGS` (line 24).
- [x] In `parsing.py::discover_loan_affected_assets`: delete the non-resolver branch (lines ~87-127); keep the resolver-delegation path WITH the `OTHER + tag=loan` clause (Invariant 11/5). Drop the `via_resolver` parameter and the `_loan_config` fallback plumbing.
- [x] Drop the `via_resolver=` kwarg and the `_loan_config` fallback at the `discover_loan_affected_assets` call site in `crypto_reporting.py:~255`.
- [x] In tests: delete legacy-branch assertions; keep resolver-path characterization.
- [x] Run → expect GREEN.
- [x] Commit: `refactor(crypto): drop _LOAN_PRINCIPAL_TAGS legacy path in discover_loan_affected_assets`.

### Task 5: Delete legacy reward/airdrop/lp tag literals in `token_origin.py` (conditional on verification)

Files:
- `src/tax_reporting/application/token_origin.py`
- `src/tax_reporting/application/crypto_reporting.py` *(drop `via_resolver` kwarg at the token_origin call site, ~line 228)*
- `tests/unit/application/test_phase_d_flip_reward_airdrop_lp.py` *(delete legacy-branch tests; keep resolver-path behavior assertions)*

- [x] `grep -rn "_DEFAULT_REWARD_TAGS\|_DEFAULT_AIRDROP_TAGS\|_DEFAULT_LP_TAGS\|via_resolver" src/tax_reporting/application/token_origin.py tests/` to enumerate references.
- [x] VERIFY before deleting: trace whether the resolver path (via `TreatmentConfig`) consults these module-level constants, or whether they are read only by the `via_resolver=False` legacy branch. If the resolver path reads them, STOP and flag to the user (this task's deletion is conditional on the constants being legacy-only).
- [x] `TestTokenOrigin#test_reward_airdrop_lp_identification_resolver_path`; given a `REWARD_AIRDROP_LP`-treatment transaction, expects the indexer resolves origin without consulting `_DEFAULT_REWARD_TAGS`/`_DEFAULT_AIRDROP_TAGS`/`_DEFAULT_LP_TAGS` (characterization of the surviving path).
- [x] Run the characterization test against the current Phase-D code with `via_resolver=True` → expect GREEN.
- [x] In `token_origin.py`: delete `_DEFAULT_REWARD_TAGS`, `_DEFAULT_AIRDROP_TAGS`, `_DEFAULT_LP_TAGS` (lines 47-49) and the `via_resolver=False` branch in `_index_row` (resolver path stays). Drop the `via_resolver` parameter.
- [x] Drop the `via_resolver=` kwarg at the token_origin call site in `crypto_reporting.py:~228`.
- [x] In tests: delete legacy-branch assertions; keep resolver-path characterization.
- [x] Run → expect GREEN.
- [x] Commit: `refactor(crypto): drop legacy reward/airdrop/lp tag literals in token_origin`.

### Task 6: Remove the six `treatment_*_via_resolver` flags from the domain + config

This task runs BEFORE Task 7 (re-zero block deletion) because the re-zero
block's bypass condition reads two of these flags; only with both flags gone
is the re-zero block provably unreachable.

Files:
- `src/tax_reporting/domain/jurisdiction.py` *(remove six fields + docstrings, lines 106-149)*
- `src/tax_reporting/infrastructure/config.py` *(remove the required-presence loader guard for the six flags; remove the now-orphaned `_countries_table_for` helper at lines 177-204 IF it is unused after the guard is gone)*
- `docs/maintenance/tax/decision_points/2025.toml` *(remove the six flag lines from both PT and example sections)*
- `docs/maintenance/tax/decision_points/2025.md` *(remove DP-019 documentation)*
- `src/tax_reporting/application/crypto_reporting.py` *(remove `any_resolver_on` gating; make `Transaction` construction unconditional; remove every `treatment_*_via_resolver` read at call sites)*
- `src/tax_reporting/application/crypto/ogr_event_level.py` *(docstring at line ~83 references `treatment_spot_disposal_via_resolver`; update to reflect post-Phase-E state)*
- `tests/unit/infrastructure/test_config.py` *(remove the required-presence-guard tests for the six flags)*

- [x] `grep -rn "treatment_.*_via_resolver\|any_resolver_on" src/ tests/ docs/` to enumerate every reference.
- [x] `TestConfig#test_decision_points_toml_loads_without_via_resolver_flags`; given the post-edit `2025.toml` (no `treatment_*_via_resolver` lines), expects `load_tax_jurisdiction_config` loads successfully without raising (characterization of the relaxed loader).
- [x] `TestCryptoReporting#test_transaction_construction_is_unconditional`; given crypto data is loaded, expects `build_transaction` runs regardless of any flag state (the `any_resolver_on` gate is gone). The construction runs whenever a `transaction_history_file` was located, even when `jurisdiction is None` (the resolver path does not require a jurisdiction; it requires only the TH rows and `TreatmentConfig`).
- [x] Run the tests against the pre-edit code → expect them to FAIL (the loader currently raises on missing flags; the gate currently exists). Capture the RED signal via `pytest.fail("Phase E Task 6 flips this GREEN")` if the tests do not naturally fail on the current code.
- [x] In `jurisdiction.py`: delete the six fields and their docstrings.
- [x] In `config.py`: delete the required-presence loader guard that raises `ConfigurationError` on a missing `treatment_*_via_resolver` flag. Audit whether the guard had shared structure with other required-presence checks; if so, leave the shared helper and remove only the six-flag-specific branch. Audit the `_countries_table_for` helper (lines 177-204) for orphaning; delete it if and only if it becomes unused.
- [x] In `2025.toml`: delete the six flag lines from both the `[countries.PT]` section and the example section (lines 114-119 and ~132-135).
- [x] In `2025.md`: delete the DP-019 section; renumber subsequent decision points if the doc's numbering scheme requires it (verify before renumbering; if DP IDs are referenced elsewhere, keep the IDs stable and mark DP-019 as REMOVED instead).
- [x] In `crypto_reporting.py`: replace `any_resolver_on = any(...)` + the conditional `Transaction`/`TreatmentConfig` construction with unconditional construction (always build `transactions` and `treatment_config` when a `transaction_history_file` was located, regardless of `jurisdiction`). Remove every `jurisdiction.treatment_*_via_resolver` read at the per-treatment call sites (the call sites were already conditioned on `jurisdiction is not None` in Phase D; with the flags gone, the condition collapses to `jurisdiction is not None`).
- [x] In `ogr_event_level.py:~83`: update the docstring that references `jurisdiction.treatment_spot_disposal_via_resolver`; the `spot_disposal_keys` parameter is still populated by the caller, but the gating flag is gone.
- [x] In `test_config.py`: delete the tests that asserted the loader raises on missing flags.
- [x] Run → expect GREEN.
- [x] Commit: `refactor(crypto): remove six treatment_*_via_resolver flags and loader guard`.

### Task 7: Delete the re-zero snapshot/restore block in `crypto_reporting.py`

Depends on Task 6 (both `treatment_payment_via_resolver` and
`treatment_spot_disposal_via_resolver` must be gone before the bypass
condition is unconditionally True).

Files:
- `src/tax_reporting/application/crypto_reporting.py`
- `tests/unit/application/test_crypto_reporting.py` *(delete re-zero assertions)*

- [x] `grep -rn "proceeds_eur == 0\|re.zero\|re_zero\|snapshot.*restore\|Payment row.*proceeds restored" src/ tests/` to enumerate references.
- [x] VERIFY before deleting: confirm Task 6 has landed (both payment and spot_disposal flags are removed from `jurisdiction.py` and the TOML). The re-zero block's bypass condition (`treatment_payment_via_resolver AND treatment_spot_disposal_via_resolver`, lines ~408-409) is now structurally unreachable - the flags it reads no longer exist, so any reference would be a `NameError` caught by the test suite. If the condition still compiles, Task 6 is incomplete; stop and finish Task 6 first.
- [x] In `crypto_reporting.py::load_koinly_crypto_report`: delete the snapshot capture (lines ~410-450), the restore loop (lines ~470-500), and the `if e.proceeds_eur == 0 and e.asset not in loan_affected_assets` predicate. The OGR override at the preceding step no longer needs its proceeds restored, because resolver-keyed identification makes the OGR-mutates-a-payment-row residual structurally impossible.
- [x] In `test_crypto_reporting.py`: delete every assertion that the re-zero restore fires or that `proceeds_eur == 0` is preserved post-OGR for originally-zero rows. Add (or confirm existing) characterization coverage that the resolver-path payment-proceeds correction still produces correct net proceeds.
- [x] Run → expect GREEN.
- [x] Commit: `refactor(crypto): delete unreachable re-zero snapshot/restore block`.

### Task 8: Delete Phase-D flag/flip/isolation/real-data-smoke tests; repin surviving behavior

Files:
- `tests/unit/application/test_phase_d_flags.py` *(deleted)*
- `tests/unit/application/test_phase_d_flag_isolation.py` *(deleted)*
- `tests/end_to_end/test_phase_d_real_data_smoke.py` *(deleted)*
- `tests/unit/application/test_phase_d_flip_payment.py` *(audit; keep resolver-behavior assertions, delete flag-mechanic assertions)*
- `tests/unit/application/test_phase_d_flip_spot_disposal.py` *(same)*
- `tests/unit/application/test_phase_d_flip_loan_repayment.py` *(same)*
- `tests/unit/application/test_phase_d_flip_derivatives_close.py` *(same)*
- `tests/unit/application/test_phase_d_flip_reward_airdrop_lp.py` *(same)*
- `tests/unit/application/test_phase_d_flip_other.py` *(same)*
- `tests/unit/application/test_phase_c_corpus.py` *(audit; keep resolver-behavior assertions, delete flag-mechanic assertions)*
- `tests/end_to_end/test_crypto_derivatives_separation.py` *(via_resolver param removal; PLUS `derivatives_dedup` logger/module references at lines ~382, 426, 432, 601-602, 695, 698 must update to `derivatives_filter`; PLUS a stale `find_derivatives_th_events` docstring reference must update to `find_derivatives_th_events_from_transactions`)*
- `tests/unit/application/test_treatment_resolver.py` *(audit for stale flag references)*

- [x] For each of the six `test_phase_d_flip_*.py` files: read the file and classify each test as (a) "flag mechanic" (asserts behavior differs between `via_resolver=True` and `via_resolver=False` - DELETE) or (b) "resolver behavior" (asserts the resolver-path identification is correct - KEEP as a characterization test). Rename the surviving file from `test_phase_d_flip_<treatment>.py` to `test_<treatment>_resolver_behavior.py` (drop the now-meaningless "flip" framing).
- [x] `git rm tests/unit/application/test_phase_d_flags.py tests/unit/application/test_phase_d_flag_isolation.py tests/end_to_end/test_phase_d_real_data_smoke.py`.
- [x] In `test_phase_c_corpus.py`: keep the corpus fixtures and the resolver-behavior assertions; delete any test that exercised the legacy branch or asserted flag-mechanic divergence. REPOINT imports with this precise distinction: line 52 (`_load_derivatives_labels_config`) SURVIVES Phase E - update only its module path (`derivatives_dedup` -> `derivatives_filter`); lines 53 (`_DEFAULT_PAYMENT_TAGS`) and 62 (`_LOAN_PRINCIPAL_TAGS`) are DELETED by Tasks 2/3/4 - repoint to the corresponding `TreatmentConfig` field or remove the import if the using-test is being deleted. Do NOT delete the line-52 import; doing so breaks the `derivatives_close` corpus scenario.
- [x] In `test_crypto_derivatives_separation.py`: this file has 30 `derivatives_dedup` references and direct `apply_derivatives_dedup` call sites - too many to enumerate reliably by line. Use a grep-driven sweep: (a) `grep -n "derivatives_dedup" tests/end_to_end/test_crypto_derivatives_separation.py` and update EVERY hit's module path/logger name to `derivatives_filter`; (b) drop `via_resolver=`, `year=` kwargs from every direct `apply_derivatives_dedup(...)` call (Task 2 drops these from the signature); (c) drop `treatment_spot_disposal_via_resolver=False` from the `build_koinly_jurisdiction(...)` call at line ~123 AND update the stale docstring at lines ~111-118 that documents it; (d) update any `find_derivatives_th_events` docstring reference to `find_derivatives_th_events_from_transactions`.
- [x] In `test_treatment_resolver.py`: audit for stale references to the six flags; the resolver itself is unchanged, so only fixture/config helpers that set the flags need updating.
- [x] GREP-DRIVEN BACKSTOP: run Validation Commands 2, 3, and 4 against `tests/`. EVERY hit in `tests/` must be resolved (repointed, removed, or updated) before this task can close. The enumerated lines above are a floor, not a ceiling; `test_crypto_reporting.py` alone has 22 flag references and `test_crypto_derivatives_separation.py` has 30 `derivatives_dedup` references. If any hit remains, the test suite will fail at collection or runtime.
- [x] Run → expect GREEN.
- [x] Commit: `test(crypto): delete Phase-D flag-mechanic tests, repin resolver-behavior assertions`.

### Task 9: Throwaway real-data byte-identical verification

Files:
- `docs/tmp/phase-e-verify/verify_byte_identical.py` *(new, gitignored; deleted at end of task)*

- [x] Write `docs/tmp/phase-e-verify/verify_byte_identical.py` that: (a) runs the crypto pipeline against `resources/source/koinly2025/`, (b) writes output to a tmp dir, (c) SHA256-hashes each output file, (d) compares against `docs/tmp/phase-e-verify/baseline/SHA256SUMS` from Task 1, (e) exits 0 on identical hashes, 1 on any diff (printing the diff).
- [x] Run the script: `uv run python docs/tmp/phase-e-verify/verify_byte_identical.py` → expect exit 0 (byte-identical).
- [x] If any hash differs: STOP. Investigate the diff before proceeding. A diff means a Phase-E deletion disturbed the resolver-path output, violating Invariant 1; root-cause and fix before this task can close.
- [x] Delete the script: `rm docs/tmp/phase-e-verify/verify_byte_identical.py`. (The `docs/tmp/phase-e-verify/baseline/` may stay for one session as forensic evidence; delete before session end per `feedback_throwaway_script_lifecycle`.)
- [x] No commit (script is gitignored; baseline is gitignored).

**Deviation disclosed (r5 LOW-2/Task 9):** the plan's literal "whole-file SHA256 of extract.xlsx must equal baseline" criterion is structurally unsatisfiable - openpyxl stamps fresh `<dcterms:created>`/`<dcterms:modified>` timestamps in `docProps/core.xml` at every `Workbook()` construction. Verified by two-run determinism check (identical code, identical input → different whole-file SHA, differing only in the two timestamp values). The verify script instead hashes every zip entry with the two timestamp attributes normalized to a fixed placeholder, which is the actual Phase-E-relevant invariant (content byte-identical). `shares-leftover.csv` was checked whole-file (no openpyxl involvement) and matches the Task 1 baseline exactly, providing a clean control. See `docs/tmp/execute-plan/2026-07-10-th-tx-view-phase-e/task-9-verify.log.md` for full reproduction.

### Task 10: Update feature-note Status + Rollout table; CLAUDE.md audit

Files:
- `docs/history/context/2026-06-20-th-anchored-transaction-state-machine.md`
- `CLAUDE.md` *(audit only; update only if a rule references the six flags)*
- `docs/maintenance/tax/decision_points/README.md` *(audit only)*

- [x] In the feature note's Status section: append a PHASE E LANDED line referencing the plan path, the landing commit (filled post-execution), the suite count, and the review rounds.
- [x] In the feature note's Rollout table: mark Phase E row as LANDED with a brief summary (legacy adapters deleted; six flags removed; byte-identical output verified).
- [x] `grep -rn "treatment_.*_via_resolver\|via_resolver\|DP-019\|derivatives_dedup" CLAUDE.md docs/maintenance/` to find any rule or doc that references the removed flags, DP-019, or the old module name. Update each reference to reflect the post-Phase-E state (the `via_resolver` rollback granularity is gone; identification is resolver-only). Specific known hits: `CLAUDE.md:97` (flag reference - keep the Invariant 11 `OTHER + tag=loan` note, drop the flag qualifier); `docs/maintenance/crypto_reporting_guidelines.md` CRG-019 (substantial rewrite needed - the flag-based rollback granularity section is obsolete); `docs/maintenance/tax/decision_points/2025.md` line ~119 changelog row (append a Phase E removal row - do NOT delete the append-only history); `src/tax_reporting/application/crypto_reporting.py:337` (stale comment referencing `find_derivatives_th_events`).
- [x] Commit: `docs(crypto): mark Phase E landed; update feature note and flag references`.

## Plan Quality Gate

Before declaring this plan ready, run the `review-plan` skill as a sub-agent
(minimum two rounds; iterate until the latest review reports Blocker=0 AND
Medium=0). Save reviews to `docs/history/reviews/2026-07-10-plan-review-th-tx-view-phase-e-r<N>.md`.
Quote the latest verdict line in the execution handoff summary. Substantive
revision (added/removed/reordered tasks, changed Design Invariants, changed
Review Scope) resets the review counter to r1.

## Monitor

- **`docs/maintenance/development_lessons.md` lessons #49-#52 reference the
  six `treatment_*_via_resolver` flags HISTORICALLY** (they document Phase D
  decisions and incidents). These are append-only history and MUST NOT be
  edited by Phase E. Owner: Task 10 grep must EXCLUDE
  `docs/maintenance/development_lessons.md` from any rewrite pass; the lessons
  stand as a record of why the flags existed and why they are now gone.
- **`test_crypto_derivatives_separation.py` intermediate-RED window (r5 LOW-1).**
  Between Task 2 (drops `year`/`via_resolver` from `apply_derivatives_dedup`)
  and Task 8 (fixes the direct call sites at lines ~885-893, ~935), the suite
  is RED at that one e2e test. Acceptable because each task commits
  independently and the final state is GREEN; if an executor wants suite-green
  at every commit, they can reorder to fix the e2e call sites inside Task 2.
  Owner: Task 2 / Task 8 executor's discretion.
