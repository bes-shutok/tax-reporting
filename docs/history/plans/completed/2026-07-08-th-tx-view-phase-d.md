# Plan: TH-anchored Transaction view - Phase D (production flip per treatment)

RFC: [docs/history/feature-notes/completed/2026-06-20-th-anchored-transaction-state-machine.md](../../feature-notes/completed/2026-06-20-th-anchored-transaction-state-machine.md#rollout-plan-2026-07-05) (Phase D of the five-phase rollout; the four prior phases A/B/C and the OGR event-level fix (Phase 1) all landed on `master`).

Phase A plan: [completed/2026-07-05-th-tx-view-phase-a.md](completed/2026-07-05-th-tx-view-phase-a.md) (landed at `bb46bdd`).
Phase B plan: [completed/2026-07-06-th-tx-view-phase-b.md](completed/2026-07-06-th-tx-view-phase-b.md) (landed at `cdb10bf`).
Phase C plan: [completed/2026-07-07-th-tx-view-phase-c.md](completed/2026-07-07-th-tx-view-phase-c.md) (landed at `d158904`; feature-notes status references the squash commit `45171a5` - Task 11 reconciles the SHA).

Plan review: [r1](../reviews/2026-07-08-plan-review-th-tx-view-phase-d-r1.md) (4 Blockers + 6 Medium addressed in revision 2; 5 Low notes folded in; 4 Monitor items). [r2](../reviews/2026-07-08-plan-review-th-tx-view-phase-d-r2.md) (3 NEW Blockers + 4 Medium addressed in revision 3; 3 Low + 3 Monitor items). [r3](../reviews/2026-07-08-plan-review-th-tx-view-phase-d-r3.md) (0 Blockers + 1 NEW Medium (N1: bare em-dash-script invocation was a no-op) addressed in revision 4; 4 Low + 3 Monitor items). [r4](../reviews/2026-07-08-plan-review-th-tx-view-phase-d-r4.md) (0 Blockers + 1 NEW Medium (N1: Task 1 misnamed the production caller) addressed in revision 5; 3 Low + 3 Monitor items). [r5](../reviews/2026-07-08-plan-review-th-tx-view-phase-d-r5.md) (1 NEW Blocker (N1: Task 1 option-a behavior claim was false - `assumptions_sheet.py:111` gate skips classifier when `th_rows=None`) addressed in revision 6 by relaxing the gate condition). [r6](../reviews/2026-07-08-plan-review-th-tx-view-phase-d-r6.md) (0 Blockers + 0 Medium; Ready for execution: Yes; 1 Low + 3 Monitor items). [r7](../reviews/2026-07-08-plan-review-th-tx-view-phase-d-r7.md) (2 NEW Blockers + 7 NEW Medium + 5 Low + 4 Monitor items addressed in revision 8). [r8](../reviews/2026-07-08-plan-review-th-tx-view-phase-d-r8.md) (0 Blockers + 1 NEW Medium + 2 Low + 1 Monitor addressed in revision 9). [r9](../reviews/2026-07-08-plan-review-th-tx-view-phase-d-r9.md) (0 Blockers + 0 Medium + 1 Low + 1 Monitor addressed in revision 10; Ready for execution: Yes). r8's Medium #1 surfaced a plan-wide gap on verification: `load_koinly_crypto_report` has ZERO production `build_transaction` calls today (verified by `grep -rn "build_transaction" src/tax_reporting/` - only `transaction_factory.py` self-call and an `entities.py` re-export), so every per-treatment flip task (3, 4, 5, 6, 7) that says "identify each TH row's treatment via `resolve_treatment`" assumes a `list[Transaction]` that has no construction site. Revision 9 makes the construction pipeline explicit: Task 3 builds `transactions` once in `load_koinly_crypto_report`; Tasks 4/5/6/7 consume it. Revision 10 folds in r9's Low (Invariant 12 "CALLER" wording) and r9's Monitor (gate construction on `any()` of the six flags to skip wasted work under full rollback).

## Terms

- **Treatment** - the Phase-B closed enum (`domain/treatment.py`) with six
  values: `SPOT_DISPOSAL`, `PAYMENT`, `LOAN_REPAYMENT`, `DERIVATIVES_CLOSE`,
  `REWARD_AIRDROP_LP`, `OTHER`. Computed by
  `application/crypto/treatment_resolver.py::resolve_treatment(transaction,
  config)` (Phase B). Phase D wires this resolver into the production
  pipeline as the authoritative source for per-treatment identification,
  gated by six per-treatment flags.
- **Per-treatment flag** - six new boolean fields on `TaxJurisdictionConfig`
  (one per Treatment member): `treatment_spot_disposal_via_resolver`,
  `treatment_payment_via_resolver`, `treatment_loan_repayment_via_resolver`,
  `treatment_derivatives_close_via_resolver`,
  `treatment_reward_airdrop_lp_via_resolver`,
  `treatment_other_via_resolver`. All default to `True` (resolver is
  authoritative at landing). Setting one to `False` restores the legacy
  identification path for that treatment only.
- **Legacy adapter** - the per-treatment code path Phase D bypasses when
  the corresponding flag is on. Four legacy adapters exist:
  (a) `correct_payment_proceeds` (`payment_proceeds.py:540`) which
  contains BOTH the `_DEFAULT_PAYMENT_TAGS`-based `build_payment_tag_index`
  identification (line 595) AND the count-equality gate (line 629); the
  inline re-zero snapshot/restore block in `crypto_reporting.py` lines
  290-339 is a SEPARATE piece that captures `proceeds_eur == 0` indices
  and restores them post-OGR so the payment-proceeds correction fires
  (it does NOT do tag-based identification itself); (b)
  `_LOAN_PRINCIPAL_TAGS` membership check (defined in
  `crypto_fifo/contexts.py:24`, consumed in `crypto_fifo/parsing.py:72`
  inside `discover_loan_affected_assets`); (c) `apply_derivatives_dedup`
  in `derivatives_dedup.py` (the OGR-type derivatives classifier); (d)
  the inline reward/airdrop/lp tag literals in
  `application/token_origin.py` (NO `crypto/` segment; lines 243, 248,
  253 - Phase C Invariant 5 noted these are not module-level constants).
  Per the user decision (2026-07-08), Phase D BYPASSES these when the
  corresponding flag is on; Phase E deletes them.
- **Production WalletKind registry** - a new thin adapter module
  `application/crypto/wallet_kind_registry.py` (new in Phase D Task 1)
  implementing the Phase-A `RegistrySnapshot` Protocol. The CEX/DEX
  signal is sourced from a NEW `wallet_kind: WalletKind | None` field
  on `OperatorOrigin` (entities.py:198; per user decision 2026-07-08),
  populated by `resolve_operator_origin` from a per-platform mapping
  defined as a module-level constant in `operator_origin.py`. The
  adapter returns `WalletKind.CEX`, `WalletKind.DEX`, or `None` (for
  platforms not in the operator-origin registry); `None` triggers the
  tier-2 auto-discovery path in `classify_platform` which may return
  `WalletKind.UNKNOWN` (N5 fix). This amends Invariant 5 to permit the
  `entities.py` field addition. The adapter is the ONLY new module
  Phase D adds under `src/tax_reporting/application/crypto/`; the field
  addition to `entities.py` is the one exception. Resolves the Phase C
  shadow run gap that flagged 540 Binance `crypto_deposit` Reward/
  Airdrop rows as `requires_review=True`.
- **Opt-in real-data end-to-end smoke** - a new test in
  `tests/end_to_end/test_phase_d_real_data_smoke.py` that is SKIPPED by
  default and activates only when the environment variable
  `TAX_REPORTING_PHASE_D_REAL_DATA_DIR` points to a Koinly directory.
  When active, it runs the full pipeline twice - once with all six
  treatment flags ON, once with all six OFF - and asserts the resulting
  Excel output is byte-identical (or within a documented diff). Never
  runs in CI without the env var; never reads gitignored data when the
  env var is absent (per CLAUDE.md crypto-test rule + Family-G).
- **Phase C shadow script (local leftover)** - `docs/tmp/phase-c-shadow/shadow_run.py`
  exists on disk as a leftover from Phase C execution (the file is
  gitignored under `.gitignore:97 tmp/`, so it was NEVER committed and
  cannot be git-restored). Per user decision 2026-07-08, Task 9 uses the
  LOCAL LEFTOVER copy with an explicit guard: if the file exists, use
  it; if missing, HALT and ask the user (do NOT silently re-author or
  promote to a tracked location). Re-run after each per-treatment flip
  to confirm the flip introduced zero new divergence. Deleted again at
  end of Phase D.
- **Loan-affected discovery flag-on semantics (user decision
  2026-07-08)** - when `treatment_loan_repayment_via_resolver=True`,
  `discover_loan_affected_assets` consults BOTH `Treatment.LOAN_REPAYMENT`
  rows AND `Treatment.OTHER` rows whose tag is `"loan"` (the borrowing-
  side principal creation). This preserves the legacy asset set exactly
  (`_LOAN_PRINCIPAL_TAGS = {"loan", "loan repayment"}` covers both);
  without the extra clause, assets whose only 2025 loan activity is a
  borrow (no repayment) would drop out of the FIFO rebuild. The flag-on
  path is therefore NOT pure resolver-delegation for this one treatment;
  it adds an `OTHER + tag=loan` clause. See Task 5 and Invariant 11.

## Gist & Examples

### What changes

Phases A/B landed typed plumbing (`Transaction`, `TxCorrelationKey`,
`Treatment`, `resolve_treatment`) with no production caller beyond the
Phase-A Assumptions & Methodology Kind column. Phase C verified - via
the synthetic corpus and a one-shot shadow run on real data - that the
resolver agrees with the legacy per-treatment classifiers on every TH
row (0 treatment divergence). Phase D is the production flip: the
resolver becomes the authoritative identification source for each
treatment, gated per-treatment by a `TaxJurisdictionConfig` flag, and
the corresponding legacy adapter is BYPASSED (not deleted; deletion is
Phase E).

Phase D adds four things, all behavior-gated by per-treatment flags:

1. **Production WalletKind registry binding (Task 1).** A new module
   `application/crypto/wallet_kind_registry.py` adapts the existing
   operator-origin data to the Phase-A `RegistrySnapshot` Protocol. The
   Assumptions & Methodology Kind column (`assumptions_kind_column.py`)
   and the Phase-D per-treatment identification path both consume it.
   Resolves the 540-row Binance gap from Phase C.

2. **Six per-treatment flags (Task 2).** Six new boolean fields on
   `TaxJurisdictionConfig`, all defaulting to `True`. Wired through the
   config loader (`infrastructure/config.py`) and the decision-points
   TOML sidecar (`docs/maintenance/tax/decision_points/2025.toml`).

3. **Per-treatment flip wiring (Tasks 3-8).** For each treatment, the
   orchestration in `crypto_reporting.py::load_koinly_crypto_report`
   consults `resolve_treatment` for each TH row when the corresponding
   flag is on; the legacy adapter for that treatment is bypassed via an
   explicit `if not jurisdiction.treatment_X_via_resolver:` guard. Six
   treatments, six tasks, one commit each. Task 4 (PAYMENT) is the
   largest because it removes the count-equality gate AND the re-zero
   snapshot/restore block when the flag is on.

4. **Verification (Tasks 9-10).** Task 9 restores the Phase C shadow
   script and re-runs it after each flip. Task 10 adds the opt-in
   real-data end-to-end smoke that proves the post-flip Excel matches
   the pre-flip Excel on real data.

### What does NOT change

- The Phase-A/B typed symbols (`Transaction`, `TxCorrelationKey`,
  `Treatment`, `resolve_treatment`, `TreatmentConfig`) are NOT modified.
  Their semantics are frozen by Phase A/B invariants; Phase D only adds
  production callers.
- The legacy adapters are NOT deleted. They remain reachable when the
  corresponding flag is off. Phase E deletes them after a clean tax
  year closes.
- The `Treatment` enum membership is NOT extended. Six members, six
  flags.
- The Phase-C synthetic corpus under
  `resources/source/example/2025/koinly/<scenario>/` is NOT modified.
  Phase D adds tests under `tests/unit/application/test_phase_d_*.py`
  that consume the existing corpus.
- `config.ini` and `tests/config.ini` gain NO new key. The flags live
  in the decision-points TOML sidecar (per CLAUDE.md "Law-driven flags"
  rule) and the dataclass; the INI file is for user preferences only.
- The Excel report shape (sections, columns) does NOT change. A
  successful flip produces a byte-identical-or-documented-diff Excel.

### Concrete example

Given the existing `2025/koinly/payment_ogr_collision/` corpus scenario
(Phase C Task 2): a single EUROC disposal on Wirex with BOTH a CG lot
(proceeds=0, cost=20 EUR) AND an OGR Loss row (Value=15 EUR) on the
same legacy key `(2025-06-15, EUROC, Wirex)`, TH `Tag="Payment"`:

- **Today (all flags effectively off, legacy runs):** the count-equality
  gate in `correct_payment_proceeds` identifies the row as Payment via
  `_DEFAULT_PAYMENT_TAGS`; the re-zero snapshot/restore block captures
  the pre-OGR zero-proceeds index, the OGR override mutates it to
  non-zero, the restore block re-zeroes it so the payment-proceeds
  correction sees `proceeds==0` and fires.
- **Phase D, flag `treatment_payment_via_resolver=True`:** the
  orchestration calls `resolve_treatment(tx, cfg)` for the TH row,
  gets `Treatment.PAYMENT`, and routes directly to the payment-proceeds
  correction WITHOUT running the count-equality gate, WITHOUT running
  the OGR override on that row (so the re-zero block is also a no-op for
  that row). The OGR override still runs on rows whose treatment is
  `SPOT_DISPOSAL` (the gate is per-treatment, not per-pipeline-stage).
- **Phase D, flag `treatment_payment_via_resolver=False`:** the legacy
  count-equality gate + OGR override + re-zero block path runs exactly
  as today. Rollback path.

Given `2025/koinly/derivatives_close/` (Phase C Task 6): TH rows tagged
`Realized gain` and `Futures fee`:

- **Today:** `apply_derivatives_dedup` identifies these via the loaded
  JSON labels and routes them through the derivatives CG dedup pass.
- **Phase D, flag `treatment_derivatives_close_via_resolver=True`:** the
  orchestration calls `resolve_treatment` with `TreatmentConfig(
  derivatives_tags=<loaded JSON>)`, gets `DERIVATIVES_CLOSE` for both
  rows, and routes them through the same dedup pass - but the
  identification comes from the resolver, not from
  `apply_derivatives_dedup`'s internal classifier. The dedup pass
  itself still runs (it does lot-level work the resolver does not do).
- **Phase D, flag off:** legacy `apply_derivatives_dedup` identification.

### Why this chunk

Per the rollout table, Phase D is "Switch per treatment - Yes, gated per
treatment." Phase C produced the evidence (0 divergence on synthetic +
real data); Phase D consumes that evidence to flip each treatment. The
per-treatment flag strategy gives rollback granularity (one treatment
can be flipped back without unwinding the other five) and matches the
project precedent (`exclude_loan_repayment_gains` is a per-behavior flag,
not a code-path flag). Phase E (delete legacy) lands after a clean tax
year closes - the bypass-not-delete choice preserves a forensic rollback
path through the next filing cycle.

## Evaluation Criteria

**Quality dimensions:**

- **Legacy-bypass correctness (correctness floor):** for each treatment,
  when the flag is ON, the legacy adapter is unreachable on any TH row
  whose resolver treatment matches; when the flag is OFF, the legacy
  adapter runs exactly as today. Verified by per-treatment flip tests
  (one ON-case + one OFF-case per treatment = 12 tests minimum) on the
  Phase-C synthetic corpus.
- **Resolver totality on real data:** the opt-in real-data end-to-end
  smoke runs the full pipeline with all six flags ON, completes without
  raising, and produces an Excel whose row count and aggregate totals
  match the all-flags-OFF baseline Excel (or any diff is documented in
  the test's expected-output file). Verified by the smoke test when
  `TAX_REPORTING_PHASE_D_REAL_DATA_DIR` is set.
- **No shadow divergence after each flip:** after each per-treatment
  flip commit, the restored Phase C shadow script is re-run on the
  Phase-C synthetic corpus AND (when the user supplies the path) on
  the real Koinly directory. Exit code 0; zero new
  `treatment_agree=no` rows compared to the Phase C baseline recorded
  in `docs/tmp/phase-c-shadow/RUN_SUMMARY.md`. Verified by Task 9.
- **Flag isolation:** flipping one treatment's flag does not change the
  behavior of the other five treatments' identification paths. Verified
  by a parametrized test that toggles each flag independently and
  asserts only the corresponding legacy adapter's reachability changes.
- **No new public API beyond the registry adapter:** `git diff
  master..HEAD -- src/tax_reporting/application/crypto/entities.py` shows
  ONLY the `wallet_kind` field addition on `OperatorOrigin` (Invariant 5
  exception #2; verified by hunk inspection - no other field/method/symbol
  added). Callers import the registry adapter from
  `wallet_kind_registry.py` directly; no other new public symbol anywhere
  in `src/tax_reporting/`. Verified in the final task.
- **CLI unchanged:** `git diff master..HEAD --name-only --
  src/tax_reporting/main.py` is empty. Verified in the final task.
- **Decision-points TOML stays in sync:** every new flag on
  `TaxJurisdictionConfig` has a corresponding entry in
  `docs/maintenance/tax/decision_points/2025.toml` with the same default
  (`true`); the loader's derived-fields loop in `infrastructure/config.py`
  picks them up automatically (no manual type-dispatch code).

**Release gates:**

- All existing crypto tests pass unchanged (count diff vs Phase C
  baseline = +new Phase D tests only).
- `uv run pytest tests/unit/application/test_phase_d_*.py -q` GREEN, no
  skips, no xfails.
- `uv run pytest tests/end_to_end/test_phase_d_real_data_smoke.py -q`
  SKIPPED when env var absent; GREEN when env var points to a Koinly
  directory.
- `uv run ruff check src/tax_reporting/ tests/` clean.
- `~/.ai-playbook/scripts/check-no-em-dash.sh touched` clean (N1/L1 fix: the script's `touched` subcommand scans unstaged + staged + untracked paths in the repo; this is the correct scope - changed files only. The bare invocation prints usage and exits 0 without scanning, which is a no-op false-pass. Do NOT use `git diff master..HEAD` because pre-existing em dashes in unchanged files are NOT a regression this plan introduces, but DO catch em dashes in any new or modified Phase D file).
- Shadow script re-run after each flip: exit 0 on the synthetic corpus
  AND on the user-supplied real Koinly directory (when supplied).
- Feature-notes status updated with Phase D landing commit, the
  per-treatment flag list, and the legacy-adapter-bypass-not-delete
  decision rationale; Phase E named as the deletion phase.

## Review Scope

**Explicit must-fix;** findings on these paths are always in scope
(review and fix if valid):

**Production code (new):**

- `src/tax_reporting/application/crypto/wallet_kind_registry.py` *(new)* -
  production WalletKind registry adapter.

**Production code (modified):**

- `src/tax_reporting/application/crypto/entities.py` - the ONE
  `OperatorOrigin.wallet_kind: WalletKind | None = None` field addition
  (Invariant 5 exception #2). No other symbol added.
- `src/tax_reporting/application/crypto/operator_origin.py` - the
  `_PLATFORM_KIND` module-level constant and `resolve_operator_origin`
  update that populates `wallet_kind` (Task 1; r7 Medium #7 adds a
  coverage-completeness test and a runtime warning for entity-chain-known
  platforms missing from `_PLATFORM_KIND`).
- `src/tax_reporting/domain/jurisdiction.py` - six new flag fields.
- `src/tax_reporting/infrastructure/config.py` - flag wiring (mostly
  automatic via the existing derived-fields loop; verify only).
- `src/tax_reporting/application/crypto_reporting.py` - per-treatment
  flip wiring in `load_koinly_crypto_report`; **r8 Medium #1 fix: this
  is the SINGLE production site that builds `list[Transaction]` ONCE
  (Task 3 wiring step); Tasks 4/5/6/7 consume the pre-built list.**
  The re-zero block (lines 290-339) gains a `treatment_payment_via_resolver`
  bypass guard.
- `src/tax_reporting/application/crypto/payment_proceeds.py` - the count-
  equality gate path gains a bypass when `treatment_payment_via_resolver`
  is on.
- `src/tax_reporting/application/crypto/ogr_event_level.py` - the OGR 1:1
  override (`apply_ogr_event_level` at line 66) gains a per-row treatment
  check when `treatment_spot_disposal_via_resolver` is on.
- `src/tax_reporting/application/crypto/derivatives_dedup.py` - the
  derivatives identification path delegates to `resolve_treatment` when
  `treatment_derivatives_close_via_resolver` is on.
- `src/tax_reporting/application/crypto_fifo/parsing.py` - **r8 Medium #1
  fix (Option A): `discover_loan_affected_assets` signature changes to
  `(transaction_history_path, fiat_currency_codes, *, transactions,
  config, via_resolver)`.** The `_LOAN_PRINCIPAL_TAGS` membership check
  (constant defined in `contexts.py:24`) delegates to `resolve_treatment`
  when `treatment_loan_repayment_via_resolver` is on (with the Invariant
  11 `OTHER + tag=loan` clause).
- `src/tax_reporting/application/token_origin.py` - the reward/
  airdrop/lp tag-literal identification delegates to `resolve_treatment`
  when `treatment_reward_airdrop_lp_via_resolver` is on. (Also extracts
  the inline literals to module-level constants per Phase C Invariant 5
  follow-up.)
- `src/tax_reporting/application/persisting/assumptions_kind_column.py`
  - passes the production registry adapter instead of `None`.
- `src/tax_reporting/application/persisting/assumptions_sheet.py` -
  the classification gate at line 111 widens from
  `if th_rows is not None:` to `if th_rows is not None or registry is not None:`
  so the registry-only call at workbook_builder.py:169 fires the classifier
  (r5 N1 fix - without this, the registry-only path is a silent no-op and
  the 540-row Binance gap cannot close).
- `src/tax_reporting/application/persisting/workbook_builder.py` - the
  call site at line 169 (`generate_tax_report` calling
  `write_assumptions_and_methodology_sheet`) gains the `registry=`
  kwarg passing the production adapter (r4 N1 fix - this is the actual
  production caller, NOT `crypto_reporting.py::load_koinly_crypto_report`).

**Tests (new):**

- `tests/unit/application/test_phase_d_registry.py` *(new)* - production
  registry adapter tests.
- `tests/unit/application/test_phase_d_flip_spot_disposal.py` *(new)*
- `tests/unit/application/test_phase_d_flip_payment.py` *(new)*
- `tests/unit/application/test_phase_d_flip_loan_repayment.py` *(new)*
- `tests/unit/application/test_phase_d_flip_derivatives_close.py` *(new)*
- `tests/unit/application/test_phase_d_flip_reward_airdrop_lp.py` *(new)*
- `tests/unit/application/test_phase_d_flip_other.py` *(new)*
- `tests/unit/application/test_phase_d_flag_isolation.py` *(new)* -
  parametrized toggle test.
- `tests/unit/application/test_phase_d_flags.py` *(new)* - flag-dataclass
  TOML sync tests.
- `tests/end_to_end/test_phase_d_real_data_smoke.py` *(new)* - opt-in
  real-data smoke.

**Configuration:**

- `docs/maintenance/tax/decision_points/2025.toml` *(modified)* - six
  new flag entries default `true`.
- `docs/maintenance/tax/decision_points/2025.md` *(modified)* - document
  the six flags.

**Throwaway verification artifacts (new, gitignored under `docs/tmp/`):**

- `docs/tmp/phase-c-shadow/shadow_run.py` *(restored from `d158904`;
  deleted in Task 11)*
- `docs/tmp/phase-c-shadow/legacy_intent.py` *(restored from `d158904`;
  deleted in Task 11)*
- `docs/tmp/phase-c-shadow/discrepancies.csv` *(output artifact; gitignored)*
- `docs/tmp/phase-d-flip-verifications/` *(new directory; per-flip shadow
  run summaries; gitignored)*

**Plan-related extension;** implementation and review may change files
not listed above. Treat a finding as in scope when it is **causally
related to this plan**: it implements or completes a per-treatment flip,
fixes a regression introduced by plan work, closes wiring or docs
implied by an explicit must-fix change, or contradicts a contract the
plan changed (e.g. the `Treatment` enum semantics frozen by Phase B, or
the Phase-A `RegistrySnapshot` Protocol). If the link to the plan is
weak or speculative, drop as out of scope with a one-line reason.

**Out of scope; reject unless plan-related:**

- Deleting any legacy adapter (`correct_payment_proceeds` count-equality
  gate, re-zero block, OGR 1:1 override, `_LOAN_PRINCIPAL_TAGS`
  membership, derivatives dedup internal classifier, reward/airdrop/lp
  tag literals). Deletion is Phase E.
- Extending the `Treatment` enum or modifying `resolve_treatment`
  semantics. Phase B froze both.
- Changing the Excel report shape (sections, columns).
- Migrating any production caller that is NOT a per-treatment
  identification path (e.g. the loan-affected FIFO rebuild, which
  already correlates by TH tx-id per Phase B Invariant 9).
- Personal-data ingestion in CI tests; the opt-in smoke never runs
  without an explicit env var.

## Design Invariants (CR Guard)

1. **Phase D does not delete any legacy adapter.** Per the user decision
   (2026-07-08), each legacy adapter remains reachable when its flag is
   off; deletion is Phase E. CR guard: reject any task that `git rm`s a
   legacy module or removes the legacy branch entirely. Bypass = `if
   not jurisdiction.treatment_X_via_resolver: <legacy path>`. Rationale:
   preserves a forensic rollback path through the next filing cycle; the
   RFC names Phase E as the deletion phase, gated on a clean tax year.

2. **Each flag is per-treatment, not per-pipeline-stage.** The six flags
   map 1:1 to the six `Treatment` members. A single pipeline stage that
   handles multiple treatments (e.g. `correct_payment_proceeds` handles
   PAYMENT; `apply_derivatives_dedup` handles DERIVATIVES_CLOSE) consults
   only its corresponding flag. CR guard: reject any "one flag for all
   treatments" or "one flag per pipeline stage" simplification.
   Rationale: the user's 2026-07-08 decision; matches the project
   precedent (`exclude_loan_repayment_gains` is per-behavior).

3. **Flags default to `True` at landing.** The Phase C shadow run showed
   0 treatment divergence on synthetic + real data; the resolver is
   verified-equivalent. The decision (2026-07-08) is that the resolver
   is authoritative at landing. CR guard: reject any default `False` or
   any "land dormant" pattern. Rationale: the user's 2026-07-08 decision;
   the evidence supports default-on.

4. **The Phase-A/B typed symbols are frozen.** Phase D does not modify
   `Transaction`, `TxCorrelationKey`, `Treatment`, `resolve_treatment`,
   or `TreatmentConfig`. CR guard: reject any edit to
   `src/tax_reporting/domain/treatment.py`,
   `src/tax_reporting/application/crypto/treatment_resolver.py`,
   `src/tax_reporting/application/crypto/tx_correlation_key_resolver.py`,
   or `src/tax_reporting/application/crypto/transaction_factory.py`.
   Rationale: Phase A/B invariants; a Phase D flip that requires
   changing resolver semantics is a Blocker (the resolver is wrong, not
   the flip).

5. **Three narrowly-scoped production-code changes are permitted.**
   (1) the new module `wallet_kind_registry.py` under
   `application/crypto/`; (2) the `wallet_kind: WalletKind | None` field
   on `OperatorOrigin` in `entities.py`; (3) relaxing the classification
   gate in `assumptions_sheet.py:111` from `if th_rows is not None:` to
   `if th_rows is not None or registry is not None:` so the registry-
   only call site (workbook_builder.py:169, which cannot pass
   `th_rows` because `CryptoTaxReport` has no such field) actually
   fires the classifier. No other new module and no other schema-level
   field addition. All other Phase D work is modification of existing
   modules. CR guard: reject any new module other than
   `wallet_kind_registry.py`, reject any field addition to
   `entities.py` beyond `wallet_kind`, and reject any change to
   `assumptions_sheet.py` other than the gate-condition widening.
   Rationale: surgical-edit discipline (CLAUDE.md); the registry is
   genuinely new (Phase A deferred it); the field addition is the
   minimum change needed to source the kind signal without a hardcoded
   table (CLAUDE.md forbids without flag-and-ask); the gate-relaxation
   is the minimum change needed so the registry-only path actually
   fires (verified: `assumptions_sheet.py:111` skips the block when
   `th_rows` is None, so `registry=` alone is a silent no-op without
   this fix - r5 N1). The bundling reflects this plan's narrow scope,
   not a general pattern (N2 fix).

6. **The opt-in real-data smoke never reads gitignored data without an
   explicit env var.** The test's `skipUnless(os.environ.get(
   "TAX_REPORTING_PHASE_D_REAL_DATA_DIR"))` is the gate. CR guard: reject
   any path in `test_phase_d_real_data_smoke.py` that reads
   `resources/source/koinly*` directly, or any test that activates the
   smoke without the env var. Rationale: CLAUDE.md crypto-test rule +
   Family-G (verify the real thing) does NOT override CLAUDE.md's
   gitignored-data rule; the env var is the explicit consent mechanism.

7. **The Phase C shadow script is used from the local leftover, re-run,
   and deleted within Phase D.** Task 9 uses the local-leftover copy at
   `docs/tmp/phase-c-shadow/shadow_run.py` with an explicit guard (the
   file is gitignored and was never committed; per user decision
   2026-07-08, no git-restore and no silent re-author - if the local
   copy is missing, halt and ask the user). Task 11 deletes it again.
   CR guard: reject any task that promotes the shadow script to a
   tracked location, any task that silently re-authors it from spec
   without user approval, or any task that leaves it on disk at end of
   Phase D. Rationale: Phase C Invariant 3 (throwaway discipline); the
   script is the verification probe, not the production path.

8. **The re-zero block bypass is structural, not deletion, and spans
   TWO edit sites.** When `treatment_payment_via_resolver=True` AND
   `treatment_spot_disposal_via_resolver=True`: (a) the re-zero
   snapshot/restore block in `crypto_reporting.py:290-339` gains a
   NESTED guard INSIDE the existing `if infer_payment_proceeds_active:`
   guard (the block runs when `infer_payment_proceeds_active AND NOT
   (treatment_payment_via_resolver AND treatment_spot_disposal_via_resolver)`
   - r7 Medium #2 fix); (b) the count-equality gate in
   `correct_payment_proceeds` (`payment_proceeds.py:629`) gains an early
   branch when the PAYMENT flag is on so the resolver-based
   identification bypasses the count check. Two files, two edits. CR
   guard: reject any task that removes the re-zero block or the count-
   equality gate; reject any task that bypasses the re-zero block when
   the SPOT_DISPOSAL flag is OFF (defeats the residual-closing logic
   when OGR still mutates PAYMENT rows); reject any task that treats the
   two sites as one. Rationale: Phase D bypasses; Phase E deletes; the
   guards are the bypass mechanism; the two pieces live in different
   files. The cross-flag dependency (PAYMENT re-zero bypass requires
   SPOT_DISPOSAL flag also ON) is documented as the ONE exception to
   Invariant 2's per-treatment independence; the alternative
   (config-time rejection of `(payment_on, spot_off)`) was rejected as
   more disruptive to rollback granularity.

9. **No em dash in any new or modified file.** Per the project's
   em-dash rule (CLAUDE.md hard rule), every changed file uses ASCII `-`
   or ` - ` instead of U+2014. CR guard: reject any U+2014 in changed
   files. The `check-no-em-dash.sh` script gates this.

10. **Decision-points TOML and the dataclass stay in sync, AND the
    loader rejects missing flags at runtime.** Every new flag on
    `TaxJurisdictionConfig` has a corresponding entry in
    `docs/maintenance/tax/decision_points/2025.toml` with the same
    default (`true`). ADDITIONALLY (r7 Medium #8 fix): the six new
    `treatment_*_via_resolver` flags MUST be present in every country
    section of every decision-points TOML - the loader's bool-default
    `setdefault(flag_name, False)` (`config.py:334-336`) silently
    reverts a treatment to legacy if its flag is absent from a
    future-year TOML. Add a required-presence guard analogous to the
    existing `exclude_loan_repayment_gains` check at `config.py:321-325`
    that raises `ConfigurationError` if any of the six flags is absent.
    CR guard: reject any flag that exists on the dataclass but not in
    the TOML, or vice versa; reject any loader change that drops the
    required-presence guard. Rationale: CLAUDE.md "Law-driven flags"
    rule + Family-D (single source of truth); the `False` default
    defeats the entire Phase D flip silently on annual TOML copy.

11. **Loan-affected discovery MUST preserve borrow-only assets under the
    flag-on path.** When `treatment_loan_repayment_via_resolver=True`,
    `discover_loan_affected_assets` consults BOTH `Treatment.LOAN_REPAYMENT`
    rows AND `Treatment.OTHER` rows whose NORMALIZED tag is `"loan"`
    (the borrowing-side principal creation). r7 Medium #1 fix: compare
    via `_normalize_tag(tx.row.tag) == "loan"` (the resolver's
    `.strip().lower()` normalization at `treatment_resolver.py:120-133`,
    Phase B Invariant 4 SOLE normalization point) - NOT the raw
    `tx.row.tag` literal, which fails on the corpus's capitalized
    `Tag="Loan"` casing. CR guard: reject any implementation that
    consults LOAN_REPAYMENT rows alone under the flag-on path; reject
    any implementation that silently drops the `"loan"` borrowing tag;
    reject any implementation that compares the raw tag value without
    normalization. Rationale: user decision 2026-07-08 (preserve legacy
    asset set); without this clause, assets whose only 2025 loan
    activity is a borrow would drop out of the FIFO rebuild, violating
    the byte-identical-or-documented-diff guarantee. The flag-on path
    is NOT pure resolver-delegation for this one treatment - the extra
    `OTHER + normalized-tag=loan` clause is the documented exception.

12. **SINGLE production `list[Transaction]` construction CALLER.** r8
    Medium #1 fix: `load_koinly_crypto_report` is the ONLY production
    caller of the Phase-A sanctioned `build_transaction(row,
    classification)` factory (`transaction_factory.py:40`; the factory
    itself remains the single SANCTIONED construction primitive per
    Phase A - Phase D does NOT add a competing factory, it adds the
    first production CALLER of it). Tasks 3/4/5/6/7 consume that
    pre-built list; NONE of them constructs `Transaction` objects
    internally. `discover_loan_affected_assets`
    (`crypto_fifo/parsing.py`) accepts `transactions` as a keyword-only
    kwarg under Option A rather than re-building from the CSV path
    (Family F layering: `crypto_fifo/ -> application/crypto/` is a
    reverse-direction reach). `correct_payment_proceeds`,
    `apply_ogr_event_level`, `apply_derivatives_dedup`, and the
    `token_origin` identification path likewise receive the pre-built
    list (or a treatment-filtered subset of it) from the caller. CR
    guard: reject any task that introduces a second production
    `build_transaction` CALLER; reject any task that pushes
    `Transaction` construction down into `crypto_fifo/` or
    `infrastructure/`. Rationale: Family D (single source of truth) +
    Family F (layering direction); avoids N divergent construction
    paths that drift on classification-registry wiring, fee handling,
    or row-typing edge cases.

## Validation Commands

```bash
# All checks assume master contains Phase A/B/C (commits bb46bdd, 5eb00e4,
# d158904). Re-run against the appropriate diff base if rebasing. Per r7
# Blocker #2: git diff --name-only exits 0 on empty output, so contract-
# removal checks MUST end in `grep .` (or use --exit-code) to flip the
# && BAD || GOOD branch correctly.

# Phase D floor: production code change is gated and isolated
git diff master..HEAD --name-only -- src/tax_reporting/ \
  | grep -vE 'wallet_kind_registry\.py$' \
  | grep -vE 'application/crypto_reporting\.py$' \
  | grep -vE 'application/crypto/(payment_proceeds|ogr_event_level|derivatives_dedup)\.py$' \
  | grep -vE 'application/token_origin\.py$' \
  | grep -vE 'application/crypto_fifo/parsing\.py$' \
  | grep -vE 'application/persisting/assumptions_kind_column\.py$' \
  | grep -vE 'application/persisting/assumptions_sheet\.py$' \
  | grep -vE 'application/persisting/workbook_builder\.py$' \
  | grep -vE 'application/crypto/entities\.py$' \
  | grep -vE 'application/crypto/operator_origin\.py$' \
  | grep -vE 'domain/jurisdiction\.py$' \
  | grep -vE 'infrastructure/config\.py$' \
  | grep . && echo "BAD: unexpected production file touched" \
           || echo "GOOD: production change is scoped to plan-listed files"

# CLI unchanged (entities.py exception: Invariant 5 #2 wallet_kind field on
# OperatorOrigin; operator_origin.py exception: _PLATFORM_KIND mapping).
git diff --exit-code master..HEAD --name-only -- src/tax_reporting/main.py \
  && echo "GOOD: CLI unchanged" \
  || echo "BAD: CLI touched"

# Phase A/B typed symbols frozen
git diff --exit-code master..HEAD --name-only \
  -- src/tax_reporting/domain/treatment.py \
     src/tax_reporting/application/crypto/treatment_resolver.py \
     src/tax_reporting/application/crypto/tx_correlation_key_resolver.py \
     src/tax_reporting/application/crypto/transaction_factory.py \
  && echo "GOOD: Phase A/B typed symbols frozen" \
  || echo "BAD: Phase A/B typed symbols modified"

# No legacy adapter deleted (Invariant 1)
git diff master..HEAD --name-only --diff-filter=D \
  | grep -E 'payment_proceeds\.py|ogr_handler\.py|derivatives_dedup\.py' \
  && echo "BAD: legacy adapter deleted" \
  || echo "GOOD: legacy adapters retained"

# New per-treatment flip tests pass (no skips)
uv run pytest tests/unit/application/test_phase_d_flip_spot_disposal.py \
              tests/unit/application/test_phase_d_flip_payment.py \
              tests/unit/application/test_phase_d_flip_loan_repayment.py \
              tests/unit/application/test_phase_d_flip_derivatives_close.py \
              tests/unit/application/test_phase_d_flip_reward_airdrop_lp.py \
              tests/unit/application/test_phase_d_flip_other.py \
              tests/unit/application/test_phase_d_flag_isolation.py \
              tests/unit/application/test_phase_d_flags.py \
              tests/unit/application/test_phase_d_registry.py -q

# Opt-in real-data smoke: skipped by default
TAX_REPORTING_PHASE_D_REAL_DATA_DIR="" \
  uv run pytest tests/end_to_end/test_phase_d_real_data_smoke.py -q \
  | grep -E 'skipped' && echo "GOOD: smoke skipped without env var"

# Shadow script deleted at end of Phase D
test -f docs/tmp/phase-c-shadow/shadow_run.py \
  && echo "BAD: shadow script not deleted at end of Phase D" \
  || echo "GOOD: shadow script deleted"

# Lint clean
uv run ruff check src/tax_reporting/ tests/

# Em dash check (touched = unstaged + staged + untracked paths)
~/.ai-playbook/scripts/check-no-em-dash.sh touched
```

The first four checks are contract-removal-style: any non-empty diff or
match is a violation. The opt-in-smoke check exercises the explicit
env-var gate (per Validation Commands authoring rule #2: exercise the
canonical executable artifact; the env var IS the gate). The shadow-
script-deleted check enforces Invariant 7. NOTE: these checks run on
the Phase D branch pre-merge; they become no-ops once Phase D lands on
master.

## Documentation Impact Assessment

Phase D lands production behavior change (resolver authoritative,
legacy bypassed per flag). Documentation must reflect this.

- `docs/maintenance/crypto_rules.md` - update to cite the resolver as
  the authoritative identification source for each treatment when the
  corresponding flag is on; cite the new flag fields by name.
- `docs/maintenance/crypto_reporting_guidelines.md` - update the
  pipeline-stage descriptions (payment-proceeds correction, OGR override,
  derivatives dedup) to note the per-flag bypass.
- `docs/maintenance/crypto_implementation_guidelines.md` - add a pitfall
  note: "when a per-treatment flag is on, the legacy adapter is
  unreachable; do not add new code that depends on the legacy path
  running."
- `docs/maintenance/tax/decision_points/2025.md` - document the six new
  flags, their defaults (`true`), and the rollback procedure (set one
  to `false`).
- `docs/maintenance/tax/decision_points/2025.toml` - six new entries.
- `docs/history/feature-notes/completed/2026-06-20-th-anchored-transaction-state-machine.md`
  - status update: Phase D LANDED at <commit>; per-treatment flags
  default on; legacy bypassed not deleted; Phase E owns deletion.
- `README.md` - no change (config schema is documented at the TOML
  sidecar level, not in README per the project's "Law-driven flags"
  rule).

## Monitor

- **Phase E deletion tracking.** Each of the six legacy adapters has a
  Phase E deletion task pending "a clean tax year closes." Owner: a new
  Phase E plan, to be authored when the user confirms the clean tax
  year (likely after filing season 2026 closes). Cross-reference: this
  plan's Invariant 1.
- **Opt-in smoke coverage gap.** The real-data smoke runs only when the
  user supplies `TAX_REPORTING_PHASE_D_REAL_DATA_DIR`; it does NOT run
  in CI. A future Koinly export that exercises a flip-path edge case
  may regress without CI catching it. Owner: a future plan to add a
  redacted fixture derived from the real export (similar to how
  `2025/koinly/payment/` was derived).
- **Registry adapter freshness.** The production WalletKind registry
  reads operator-origin data; if the operator-origin registry adds a
  new platform, the adapter picks it up automatically (no code change).
  But if operator-origin starts classifying CEX/DEX itself (currently
  out of scope per Phase A docstring), the adapter becomes redundant.
  Owner: a future plan to collapse the adapter into operator-origin if
  that happens.
- **Token-origin tag-literal extraction (Phase C Invariant 5
  follow-up).** Task 7 (REWARD_AIRDROP_LP flip) extracts the inline
  reward/airdrop/lp tag literals from `token_origin.py` to module-level
  constants. If new reward/airdrop/lp tags are added in the future,
  they go in the module-level constants AND the
  `_DEFAULT_REWARD_TAGS`/`_DEFAULT_AIRDROP_TAGS`/`_DEFAULT_LP_TAGS`
  sets in `treatment_resolver.py`. Owner: any future plan that adds a
  reward/airdrop/lp tag.
- **Feature-notes SHA reconciliation.** Phase C's feature-notes status
  references `45171a5` as the Phase C landing commit; the local master
  shows `d158904`. Task 11 reconciles this (likely `45171a5` is a
  squash-merge SHA on a remote that did not propagate to local master).
  Owner: Task 11.

### Task 0: Baseline test count and clean-tree confirmation

Files:
- (no file changes; baseline-capture only)

- [x] Run: `uv run pytest tests/ --collect-only -q | tail -3` and record the test count. Save to `docs/tmp/phase-d-baseline-count.txt`. **Expected baseline: 1698 tests collected (verified at plan creation); the RECORDED VALUE in this file is the authoritative baseline for Task 11's count-diff check, NOT the literal 1698.** Halt and ask the user if the actual baseline differs from 1698 (a parallel plan may have landed tests in the interim).
- [x] Run: `git status` to confirm the working tree is clean except for the plan file. Halt and ask the user if unexpected changes appear.
- [x] Commit: none. Baseline is recorded for the Task 11 count-diff check.

### Task 1: Production WalletKind registry binding

Files:
- `src/tax_reporting/application/crypto/wallet_kind_registry.py` *(new)*
- `src/tax_reporting/application/crypto/entities.py` *(add `wallet_kind:
  WalletKind | None` field to `OperatorOrigin`; the ONE entities.py
  exception per amended Invariant 5)*
- `src/tax_reporting/application/crypto/operator_origin.py` *(populate
  `wallet_kind` from a per-platform mapping defined as a module-level
  constant here; existing platforms get explicit kinds, unknown
  platforms get None)*
- `src/tax_reporting/application/persisting/assumptions_kind_column.py`
- `src/tax_reporting/application/persisting/assumptions_sheet.py`
  *(relax the gate at line 111 from `if th_rows is not None:` to
  `if th_rows is not None or registry is not None:` so the registry-
  only call at workbook_builder.py:169 actually fires the classifier;
  r5 N1 fix - the current gate silently skips the block when
  `th_rows` is None, making `registry=` alone a no-op)*
- `src/tax_reporting/application/persisting/workbook_builder.py` *(the
  production caller of `write_assumptions_and_methodology_sheet` at
  line 169 - NOT crypto_reporting.py::load_koinly_crypto_report; r4 N1
  fix)*
- `tests/unit/application/test_phase_d_registry.py` *(new)*

- [x] `TestPhaseDRegistry#test_classify_known_cex_platform`; given a registry adapter constructed over the production operator-origin data (or a stub mirroring its shape), expects `classify("Kraken") == WalletKind.CEX`, `classify("ByBit") == WalletKind.CEX`, `classify("Wirex") == WalletKind.CEX`. Pins the platforms the Phase C stub knew as CEX.
- [x] `TestPhaseDRegistry#test_classify_known_dex_platform`; given the same adapter, expects `classify("Ledger Berachain (BERA)") == WalletKind.DEX`, `classify("SUI") == WalletKind.DEX`, `classify("Ledger") == WalletKind.DEX`. Pins the platforms the Phase C stub knew as DEX.
- [x] `TestPhaseDRegistry#test_classify_binance_resolves_cex`; given the adapter, expects `classify("Binance") == WalletKind.CEX` explicitly. This is the 540-row gap from Phase C; the test pins CEX (Binance is a centralized exchange) so a future regression that drops the Binance mapping surfaces. The operator_origin.py platform mapping MUST classify Binance as CEX.
- [x] `TestPhaseDRegistry#test_classify_unmapped_returns_none`; given a platform NOT in the operator-origin registry (e.g. `"UnknownNewExchange"`), expects `classify(...) == None` so the caller falls through to tier-2 auto-discovery. Pins the RegistrySnapshot contract.
- [x] `TestPhaseDRegistry#test_assumptions_kind_column_consumes_registry`; given a small set of TH rows for a known CEX platform, expects `classify_platforms_for_summaries(...)` called with the new production registry returns `classification.kind == WalletKind.CEX` for that platform (not UNKNOWN). Pins the wiring change in `assumptions_kind_column.py`.
- [x] `TestPhaseDRegistry#test_registry_only_call_does_not_crash_on_none_th_rows`; given `write_assumptions_and_methodology_sheet(workbook, capital_entries=[<a Kraken CG entry>], reward_entries=[], registry=<adapter>)` with NO `th_rows` kwarg, expects no exception AND the Kraken Kind column renders `CEX`. Pins r7 Blocker #1: the production caller (`workbook_builder.py:169`) passes `th_rows=None`; if the relaxed gate forwards `None` to `aggregate_platform_evidence` (`wallet_kind.py:225` `for row in rows:`), the workbook build crashes with `TypeError`. This test FAILS today (TypeError on None) and flips GREEN only when the None-normalization lands.
- [x] `TestPhaseDRegistry#test_every_entity_chain_platform_has_kind`; given the set of platform brands the `resolve_operator_origin` entity chain recognizes (extracted into a shared `_KNOWN_PLATFORM_BRANDS` constant), expects `_PLATFORM_KIND` covers EVERY one with a non-`None` kind. Pins r7 Medium #7 coverage-completeness: prevents the silent misclassification drift the 540-row Binance gap exemplifies (a platform added to the entity chain but missing from `_PLATFORM_KIND`).
- [x] Run RED: `uv run pytest tests/unit/application/test_phase_d_registry.py -q` -> the first four tests fail because `wallet_kind_registry.py` does not exist; the fifth test (`test_assumptions_kind_column_consumes_registry`) fails because (a) the production caller (`workbook_builder.py:169`) does not pass `registry=` and (b) the gate at `assumptions_sheet.py:111` (`if th_rows is not None:`) skips the classifier block entirely when `th_rows` is None (the registry-only call case), so the Kind column stays BLANK. The sixth test (`test_registry_only_call_does_not_crash_on_none_th_rows`) fails with `TypeError: 'NoneType' object is not iterable` because the relaxed gate forwards `th_rows=None` to `aggregate_platform_evidence` which iterates it unconditionally. The seventh test (`test_every_entity_chain_platform_has_kind`) fails because `_PLATFORM_KIND` and `_KNOWN_PLATFORM_BRANDS` do not yet exist. Four distinct failure modes; all must flip GREEN.
- [x] Add `wallet_kind: WalletKind | None = None` field to `OperatorOrigin` in `entities.py:198` (the ONE exception per amended Invariant 5). Default `None` so existing constructors do not break.
- [x] Add a per-platform mapping (module-level constant, e.g. `_PLATFORM_KIND: dict[str, WalletKind]`) in `operator_origin.py` covering the production platforms (Kraken/Bybit/Wirex/Binance=CEX, Ledger/SUI/Berachain/BERA=DEX, etc.). ALSO extract the set of platform brands the entity chain recognizes into a shared module-level constant `_KNOWN_PLATFORM_BRANDS: frozenset[str]` in `operator_origin.py`, sourced from the same substring keys the entity chain matches on; the entity-chain branches AND `_PLATFORM_KIND` BOTH reference this constant (Family D: single source of truth for the platform set; r7 Medium #7 fix option (b)). **r8 Low #1 fix (scope clarification):** `_KNOWN_PLATFORM_BRANDS` captures the SIMPLE SUBSTRING match keys only (`wirex`, `bybit`, `berachain`, `ethereum`, `aptos`, `polygon`, `filecoin`, `binance`, `kraken`, plus the regex-keyed names `ton`, `sui`, `mantle`, `base`, `arbitrum`, `starknet`, `zksync`, `solana`, `tonkeeper`). Regex/conditional branches (e.g. `re.search(r"\bton\b", ...) and "tonkeeper" not in normalized`, `re.search(r"\bbase\b", ...) and "coinbase" not in normalized`, `"gate.io" in normalized or normalized == "gate"`) are documented as known-exclusions in a comment immediately above the constant - the frozenset holds plain strings and cannot mechanically encode word-boundary or exclusion logic. `test_every_entity_chain_platform_has_kind` iterates `_KNOWN_PLATFORM_BRANDS` (the simple set) and asserts each has a non-None kind. The runtime warning fires on entity-chain-matched platforms (any branch head that matches - simple or regex/conditional) whose `_PLATFORM_KIND` lookup returns None; re-running the entity chain at runtime is the source of truth, NOT `_KNOWN_PLATFORM_BRANDS` membership. Document the mapping as the explicit kind signal per CLAUDE.md "never introduce a hardcoded value without first flagging it and asking the user" - the user decision (2026-07-08, B2 option 1) is the flag-and-ask resolution. Binance=CEX per the operator-entity classification in `operator_origin.py:399-406` (N4 fix - cite the source: "Binance Spain, S.L." is a centralized exchange operator; the `_PLATFORM_KIND` mapping documents its source in a module docstring). Update `resolve_operator_origin` to populate `wallet_kind` from this mapping; unknown platforms get `None`. Add a runtime guard in `resolve_operator_origin`: when a platform matches the entity chain but `_PLATFORM_KIND` returns `None`, log at `logger.warning` (data-loss at warning+, per CLAUDE.md) with the platform name so a future addition forgotten in `_PLATFORM_KIND` surfaces loudly.
- [x] Author `wallet_kind_registry.py`: implement `RegistrySnapshot` Protocol by calling `resolve_operator_origin` per platform and returning `.wallet_kind`. Module docstring cites Phase A's deferred-registry note and Phase C's 540-row Binance gap as the motivation.
- [x] Wire `assumptions_kind_column.py` and its production caller chain (N1-r4 + N1-r5 fix + r7 Blocker #1 fix). The actual call site is `generate_tax_report` at `src/tax_reporting/application/persisting/workbook_builder.py:169` (NOT `crypto_reporting.py::load_koinly_crypto_report` - that function returns a `CryptoTaxReport` and never calls the sheet writer; verified by `grep -n "write_assumptions_and_methodology_sheet" src/tax_reporting/`). The call site at workbook_builder.py:169-173 currently passes ONLY `capital_entries` and `reward_entries`; it omits BOTH `th_rows` and `registry`. `CryptoTaxReport` (defined at `entities.py:542`) has NO `th_rows` field today. CRITICAL: the classification block in `assumptions_sheet.py:111` is gated by `if th_rows is not None:`, so passing `registry=<adapter>` alone does NOTHING (the block is skipped entirely; Kind column stays BLANK, not UNKNOWN, and the registry is never consulted - verified at `assumptions_sheet.py:111-113`). Pick scope option (ii): **relax the `assumptions_sheet.py:111` gate to fire when EITHER `th_rows` OR `registry` is non-None.** Construct the production registry adapter in `generate_tax_report` (Option A - construct in `generate_tax_report` itself, NOT receive from `main.py`; this avoids a signature change to `generate_tax_report` that would exceed Invariant 5's exception list, per r7 Low #1), pass `registry=<adapter>` at `workbook_builder.py:169`, and change the gate condition in `assumptions_sheet.py:111` from `if th_rows is not None:` to `if th_rows is not None or registry is not None:`. **r7 Blocker #1 fix:** INSIDE the relaxed-gate block, BEFORE calling `classify_platforms_for_summaries`, normalize `th_rows` to `()` when it is `None` (i.e. `effective_th_rows = th_rows or ()`). Do NOT forward `None` to `classify_platforms_for_summaries`; `aggregate_platform_evidence` (`wallet_kind.py:225`) iterates its argument unconditionally and crashes with `TypeError: 'NoneType' object is not iterable` on `None`. Verified empirically at r7. This keeps `CryptoTaxReport` unchanged (no `th_rows` field - no schema change beyond Invariant 5's `wallet_kind` exception) and makes the registry-only path actually fire the classifier AND complete without crashing. The 540-row Binance gap closes because Binance is in the registry (CEX), so the Kind column resolves to CEX (high confidence) instead of staying blank. Do NOT extend `CryptoTaxReport` with a `th_rows` field (option (i) would require a second schema change; Invariant 5's exception list covers `wallet_kind` and the gate-relaxation in `assumptions_sheet.py` only - see Invariant 5 amendment below). Also update the three Phase A docstrings (`_PlatformSummary.classification`, `_collect_platform_summaries`, `write_assumptions_and_methodology_sheet`) that become semantically stale for the registry-only path now that classification runs without `th_rows` (r6 Mo3 / r7 Mo1): replace "When omitted (Phase A production caller), the Kind column is left blank" with "When `th_rows` is omitted but `registry` is supplied, the Kind column resolves via tier-1 registry lookup; when BOTH are omitted, the Kind column is left blank".
- [x] Run GREEN.
- [x] **r8 Low #2 fix:** Re-read the three Phase A docstrings (`_PlatformSummary.classification` at `assumptions_sheet.py:58-60`, `_collect_platform_summaries` at `assumptions_sheet.py:75-82`, `write_assumptions_and_methodology_sheet` at `assumptions_sheet.py:155-163`) and confirm the registry-only-path clause from the wiring step above is reflected (the prior text "When omitted (Phase A production caller), the Kind column is left blank" must be GONE). If any docstring still carries the stale Phase A text, update it. The release gate `check-no-em-dash.sh touched` does NOT catch docstring drift; this GREEN step is the only verification.
- [x] Commit: `feat(crypto): bind production WalletKind registry (Phase D Task 1)`.

### Task 2: Six per-treatment flags on TaxJurisdictionConfig

Files:
- `src/tax_reporting/domain/jurisdiction.py`
- `src/tax_reporting/infrastructure/config.py`
- `docs/maintenance/tax/decision_points/2025.toml`
- `docs/maintenance/tax/decision_points/2025.md`
- `tests/unit/application/test_phase_d_flags.py` *(new)*

- [x] `TestPhaseDFlags#test_default_flags_all_true`; given a default-constructed `TaxJurisdictionConfig` (via the config loader with the 2025 TOML), expects all six `treatment_*_via_resolver` flags are `True`. Pins Invariant 3 (default ON at landing).
- [x] `TestPhaseDFlags#test_flag_per_treatment_field_exists`; given `dataclasses.fields(TaxJurisdictionConfig)`, expects all six flag names are present. Pins the 1:1 Treatment-to-flag mapping (Invariant 2).
- [x] `TestPhaseDFlags#test_toml_has_six_entries`; given the 2025 TOML file, expects six entries matching the six flag names with `true` values. Pins Invariant 10 (TOML-dataclass sync).
- [x] `TestPhaseDFlags#test_flag_false_restores_legacy`; given a config with one flag set to `False`, expects the loader returns a `TaxJurisdictionConfig` with that flag `False` and the other five `True`. Pins the rollback mechanism.
- [x] `TestPhaseDFlags#test_missing_treatment_flag_in_toml_raises`; given a TOML where one of the six `treatment_*_via_resolver` flags is absent from a country section, expects the loader raises `ConfigurationError` naming the missing flag. Pins r7 Medium #8 / Invariant 10: the loader's bool-default `setdefault(flag_name, False)` (`config.py:334-336`) would silently revert the treatment to legacy otherwise; the required-presence guard (analogous to `exclude_loan_repayment_gains` at `config.py:321-325`) must fail loudly.
- [x] Run RED.
- [x] Add six fields to `TaxJurisdictionConfig` with `= True` defaults. Add docstrings citing the Treatment member each gates.
- [x] Add six entries to `docs/maintenance/tax/decision_points/2025.toml` default `true`. Document in `2025.md`.
- [x] Verify the config loader's derived-fields loop picks them up automatically (no manual type-dispatch code); if not, add the necessary wiring to `infrastructure/config.py`.
- [x] Add a required-presence guard in `infrastructure/config.py` (analogous to the `exclude_loan_repayment_gains` check at `config.py:321-325`) that raises `ConfigurationError` if any of the six `treatment_*_via_resolver` flags is absent from any country section of the decision-points TOML. The guard runs AFTER `_KNOWN_BOOL_FLAGS` setdefault (`config.py:334-336`) so the False default does not mask the absence. r7 Medium #8 fix.
- [x] Run GREEN.
- [x] Commit: `feat(crypto): add six per-treatment resolver flags + required-presence loader guard (Phase D Task 2)`.

### Task 3: SPOT_DISPOSAL flip - OGR 1:1 override bypass

Files:
- `src/tax_reporting/application/crypto_reporting.py`
- `src/tax_reporting/application/crypto/ogr_event_level.py` *(NOT
  `ogr_handler.py`; `apply_ogr_event_level` is defined here at line 66,
  called from `crypto_reporting.py:312`; `ogr_handler.py` contains only
  `_split_ogr_index` and routing helpers)*
- `tests/unit/application/test_phase_d_flip_spot_disposal.py` *(new)*

- [x] `TestPhaseDFlipSpotDisposal#test_ogr_override_runs_when_flag_on`; given the `2025/koinly/multi_lot_ogr/` corpus scenario (one CG key with two lots + one OGR Profit row) and `treatment_spot_disposal_via_resolver=True`, expects the OGR override runs on the rows whose resolver treatment is `SPOT_DISPOSAL` and the override is applied once per event (not per lot). Pins the per-event application the OGR event-level fix (Phase 1) established.
- [x] `TestPhaseDFlipSpotDisposal#test_ogr_override_skipped_when_flag_off`; given the same scenario and `treatment_spot_disposal_via_resolver=False`, expects the legacy OGR override path runs (the per-row `_apply_ogr_direction_override` form) exactly as it does today. Pins the bypass (Invariant 8).
- [x] `TestPhaseDFlipSpotDisposal#test_resolver_identifies_spot_disposal`; given the same scenario's TH row (no special tag), expects `resolve_treatment(tx, cfg) == Treatment.SPOT_DISPOSAL`. Pins the identification source.
- [x] `TestPhaseDFlipSpotDisposal#test_ogr_override_skipped_on_non_spot_treatment`; given a synthetic fixture with TWO TH rows sharing the same `(date, asset, wallet)` key - one `SPOT_DISPOSAL` (no tag) and one `PAYMENT` (`Tag="Payment"`) - and an OGR Profit row on that key, with `treatment_spot_disposal_via_resolver=True`, expects the OGR override applies to the SPOT_DISPOSAL lot AND does NOT apply to the PAYMENT lot (PAYMENT lot's `gain_loss_eur` equals the pre-override CG value; its `ogr_validation` is None). Pins r7 Medium #6: the `multi_lot_ogr` corpus contains only SPOT_DISPOSAL rows, so the wiring's treatment filter is structurally untested in the positive case; this negative-case fixture fails if the implementation applies the override to every `(date, asset, wallet)`-matched entry regardless of treatment. The `payment_ogr_collision` corpus has a PAYMENT row but no SPOT_DISPOSAL row on the same key, so construct a new mixed-key synthetic fixture (or call `apply_ogr_event_level` directly with a treatment-filtered spot_index).
- [x] Run RED.
- [x] Wire `crypto_reporting.py::load_koinly_crypto_report`: when `jurisdiction.treatment_spot_disposal_via_resolver` is True, identify each TH row's treatment via `resolve_treatment` and gate the OGR override (`apply_ogr_event_level` at `crypto/ogr_event_level.py:66`, called from `crypto_reporting.py:312`) on the treatment being SPOT_DISPOSAL. When False, the legacy path runs unchanged. The treatment filter MUST be applied at the per-row key-matching level so a non-SPOT_DISPOSAL row sharing the same `(date, asset, wallet)` key is NOT overridden (r7 Medium #6). **r8 Medium #1 fix (plan-wide construction pipeline, anchored here because Task 3 is the first per-treatment flip):** `load_koinly_crypto_report` has ZERO production `build_transaction` calls today (verified: `grep -rn "build_transaction" src/tax_reporting/` returns only `transaction_factory.py` self-call + `entities.py` re-export). Phase D IS the wiring moment. Build `transactions: list[Transaction]` ONCE in `load_koinly_crypto_report` via the sanctioned Phase A path: (a) `rows = read_koinly_rows(transaction_history_file)`, (b) for each row, build a typed `TransactionHistoryRow` and a `WalletClassification` via `classify_platform(platform, evidence, registry)`, (c) `transactions = [build_transaction(row, classification) for row, classification in ...]`. Store `transactions` as a local in `load_koinly_crypto_report`. Tasks 4/5/6/7 consume this same list (do NOT re-build per task - Family D single-source-of-truth). The `TreatmentConfig` is built ONCE from `jurisdiction` + the JSON-loaded tag sets and passed to every `resolve_treatment` call. Do NOT push Transaction construction down into per-row CSV-reading helpers in `crypto_fifo/` (Family F layering: `crypto_fifo/ -> application/crypto/` is a reverse-direction reach; the caller owns it). Annotate the construction block with a comment naming this as the SINGLE production Transaction-construction site post-Phase D. **r9 Monitor #1 fix (gate on any flag):** GATE the construction on `any_resolver_on = any(getattr(jurisdiction, f"treatment_{t.name.lower()}_via_resolver", False) for t in Treatment)`. When `any_resolver_on` is False (full rollback), SKIP construction entirely and run every legacy adapter unchanged - the per-row cost of building `list[Transaction]` is wasted work under full rollback. When True, build once and let each per-treatment flag decide whether to consume it. Add a one-line comment naming the cost (thin factory + O(1) `classify_platform` per row; bounded by TH row count).
- [x] Run GREEN.
- [x] Commit: `feat(crypto): flip SPOT_DISPOSAL to resolver, bypass legacy OGR 1:1 (Phase D Task 3)`.
- [ ] Restore + re-run the Phase C shadow script (Task 9 step).

### Task 4: PAYMENT flip - count-equality gate + re-zero block bypass

Files:
- `src/tax_reporting/application/crypto_reporting.py`
- `src/tax_reporting/application/crypto/payment_proceeds.py`
- `tests/unit/application/test_phase_d_flip_payment.py` *(new)*

- [x] `TestPhaseDFlipPayment#test_count_gate_skipped_when_flag_on`; given the `2025/koinly/payment_ogr_collision/` corpus scenario and `treatment_payment_via_resolver=True`, expects the count-equality gate in `correct_payment_proceeds` is NOT consulted; the payment-proceeds correction fires on rows whose resolver treatment is `PAYMENT` regardless of CG-row count.
- [x] `TestPhaseDFlipPayment#test_rezero_block_skipped_when_flag_on`; given the same scenario and flag on, expects the re-zero snapshot/restore block (crypto_reporting.py lines 290-339) is a no-op for rows identified as PAYMENT by the resolver.
- [x] `TestPhaseDFlipPayment#test_count_gate_runs_when_flag_off`; given the same scenario and `treatment_payment_via_resolver=False`, expects the count-equality gate AND the re-zero block run exactly as today. Pins the bypass.
- [x] `TestPhaseDFlipPayment#test_resolver_identifies_payment`; given the scenario's TH row with `Tag="Payment"`, expects `resolve_treatment(tx, cfg) == Treatment.PAYMENT`.
- [x] `TestPhaseDFlipPayment#test_mixed_state_infer_off_resolver_on_is_documented_noop`; given `infer_payment_proceeds=False, treatment_payment_via_resolver=True`, expects the resolver still identifies PAYMENT rows but the payment-proceeds correction does NOT fire (because `infer_payment_proceeds_active` is False). Documents the mixed-state semantics: `treatment_payment_via_resolver` governs ONLY the identification path; `infer_payment_proceeds` governs whether the correction runs at all. The two flags are independent.
- [x] `TestPhaseDFlipPayment#test_payment_flip_with_spot_disposal_off_still_closes_residual`; given `treatment_spot_disposal_via_resolver=False, treatment_payment_via_resolver=True, infer_payment_proceeds=True`, and a `payment_ogr_collision`-shape fixture where an OGR override would mutate a PAYMENT row's `proceeds_eur` from 0 to non-zero, expects the re-zero snapshot/restore block STILL RUNS (Task 4 ON does NOT skip it when Task 3 is OFF), so `correct_payment_proceeds` sees `proceeds_eur == 0` after restore and the payment-proceeds correction fires. Pins r7 Medium #2: the PAYMENT flip's re-zero bypass depends on the SPOT_DISPOSAL flip also being ON (so OGR skips PAYMENT rows); under partial rollback `(spot_off, payment_on)`, the re-zero block must remain active to close the OGR-mutation residual that `payment_proceeds.py:615` would otherwise skip.
- [x] Run RED.
- [x] Wire `crypto_reporting.py`: NEST a new guard INSIDE the existing `if infer_payment_proceeds_active:` guard around the re-zero snapshot/restore block (Invariant 8 + r7 Medium #2 fix). The re-zero block runs when `infer_payment_proceeds_active AND NOT (treatment_payment_via_resolver AND treatment_spot_disposal_via_resolver)` - i.e., the block is bypassed ONLY when BOTH the PAYMENT and SPOT_DISPOSAL flags are ON (because under both-ON, OGR skips PAYMENT rows so the residual the re-zero block exists to close cannot occur). Under `(spot_off, payment_on)` partial rollback, the OGR override still mutates PAYMENT rows' proceeds (Task 3 OFF), so the re-zero block MUST still run. In `correct_payment_proceeds`, add an early branch: when the flag is on, identification comes from the resolver (the caller passes the set of PAYMENT-treatment TH rows); the count-equality gate code path is unreachable. Under flag-on, the resolver-based identification makes the count-equality gate unreachable, and the payment-proceeds correction still fires via `infer_payment_proceeds_active`. **r8 Medium #1 carry-forward:** the "set of PAYMENT-treatment TH rows" comes from the `transactions: list[Transaction]` built ONCE in Task 3's wiring step; filter `[tx for tx in transactions if resolve_treatment(tx, cfg) == Treatment.PAYMENT]` and pass the resulting list to `correct_payment_proceeds`. Do NOT re-build `Transaction` objects inside this task.
- [x] Run GREEN.
- [x] Commit: `feat(crypto): flip PAYMENT to resolver, bypass count-equality gate + re-zero block (Phase D Task 4)`.
- [ ] Restore + re-run the Phase C shadow script (Task 9 step).

### Task 5: LOAN_REPAYMENT flip - `_LOAN_PRINCIPAL_TAGS` membership bypass

Files:
- `src/tax_reporting/application/crypto_fifo/parsing.py` *(usage site at
  line 72, inside `discover_loan_affected_assets`; the constant
  `_LOAN_PRINCIPAL_TAGS` is DEFINED in `crypto_fifo/contexts.py:24` and
  imported into `parsing.py` - DO NOT edit the constant definition.
  **r8 Medium #1 fix (Option A):** `discover_loan_affected_assets` gains
  a `transactions: list[Transaction]` kwarg + a `config: TreatmentConfig`
  kwarg + a `via_resolver: bool` kwarg. Today's signature is
  `(transaction_history_path, fiat_currency_codes)`; new signature is
  `(transaction_history_path, fiat_currency_codes, *, transactions,
  config, via_resolver)`. The `transactions` list is pre-built ONCE by
  the caller in `load_koinly_crypto_report` (Task 3 wiring step) and
  passed through; the function does NOT construct `Transaction` objects
  internally (Family F layering: `crypto_fifo/ -> application/crypto/`
  would be a reverse-direction reach for the resolver/factory).)*
- `src/tax_reporting/application/crypto_reporting.py` *(caller mod: pass
  the pre-built `transactions` + `config` + `via_resolver` to
  `discover_loan_affected_assets` at the existing call site near line
  169; the `transactions` list is the same one Task 3's wiring step
  built.)*
- `tests/unit/application/test_phase_d_flip_loan_repayment.py` *(new)*
- `tests/unit/application/test_crypto_fifo.py` *(existing; update the
  five direct-call sites at lines 1392, 1406, 1427, 1453, 1468 to pass
  synthetic `transactions=[]` + `config=<minimal TreatmentConfig>` +
  `via_resolver=False` so the legacy path is exercised unchanged. r8
  Medium #1: a signature change to a function with existing direct test
  callers MUST update those callers in the same task; otherwise the
  legacy-path tests crash with `TypeError` on the new required kwargs.)*

- [x] `TestPhaseDFlipLoanRepayment#test_loan_principal_tags_skipped_when_flag_on`; given the `2025/koinly/loan_affected_rebuild/` corpus scenario and `treatment_loan_repayment_via_resolver=True`, expects `_LOAN_PRINCIPAL_TAGS` membership is NOT consulted; loan-affected asset discovery uses Treatment.LOAN_REPAYMENT rows AND Treatment.OTHER rows whose tag is `"loan"` (per Terms "Loan-affected discovery flag-on semantics" and Invariant 11).
- [x] `TestPhaseDFlipLoanRepayment#test_loan_principal_tags_runs_when_flag_off`; given the same scenario and flag off, expects `_LOAN_PRINCIPAL_TAGS` membership runs exactly as today (the borrowing-side `"loan"` tag still identifies principal creation via the legacy `{"loan", "loan repayment"}` set).
- [x] `TestPhaseDFlipLoanRepayment#test_resolver_distinguishes_borrowing_from_repayment`; given the scenario's `Tag="Loan"` row (borrowing), expects `resolve_treatment == OTHER`; given the `Tag="Loan Repayment"` row, expects `LOAN_REPAYMENT`. Pins Phase B Invariant 9.
- [x] `TestPhaseDFlipLoanRepayment#test_borrow_only_asset_still_in_loan_affected_under_flag`; given a synthetic TH with a `Tag="Loan"` crypto_deposit (receiving 0.1 WBTC to ByBit) and NO `Tag="Loan Repayment"` row in the tax year, expects `discover_loan_affected_assets(...)` with `treatment_loan_repayment_via_resolver=True` returns a set INCLUDING WBTC. This pins the user's "preserve" decision (2026-07-08): assets whose only 2025 loan activity is a borrow remain in the FIFO rebuild. The test FAILS under a pure resolver-delegation reading (which would miss the borrow row) - that is the point; it surfaces the Invariant 11 clause. **r7 Medium #1 fix:** parametrize over `["Loan", "loan", " LOAN ", "Loan  "]` to pin the tag-normalization contract (the corpus uses `Tag="Loan"` capitalized; legacy normalizes via `.strip().lower()`).
- [x] Run RED: `uv run pytest tests/unit/application/test_phase_d_flip_loan_repayment.py -q` -> the borrow-only test fails because the flag-on path is not yet wired to include OTHER+tag=loan rows; the parametrized casing variants additionally fail when the wiring compares the raw tag (`"Loan" == "loan"` is `False`).
- [x] Wire `crypto_fifo/parsing.py::discover_loan_affected_assets` per **r8 Medium #1 Option A**: the function gains keyword-only params `transactions: list[Transaction]`, `config: TreatmentConfig`, `via_resolver: bool`. When `via_resolver=True`, iterate `transactions` (NOT `read_koinly_rows(transaction_history_path)` - the caller pre-built the list); for each `tx`, include the asset if `resolve_treatment(tx, config) == Treatment.LOAN_REPAYMENT` OR (`resolve_treatment(tx, config) == Treatment.OTHER` AND `_normalize_tag(tx.row.tag) == "loan"`). When `via_resolver=False`, today's legacy path runs unchanged: `read_koinly_rows(transaction_history_path)` + `tag not in _LOAN_PRINCIPAL_TAGS` membership. **r7 Medium #1 fix:** reuse the resolver's `_normalize_tag` (`treatment_resolver.py:120-133`, `.strip().lower()`) - the SOLE normalization point per Phase B Invariant 4; do NOT compare the raw `tx.row.tag` literal, which fails on the corpus's capitalized `Tag="Loan"` casing (verified at `resources/source/example/2025/koinly/loan_affected_rebuild/koinly_2025_transaction_history.csv:4`). Import `_normalize_tag` from `treatment_resolver.py` (or expose it as a public helper if it is currently private). Field access verified: `TransactionHistoryRow.tag` at `domain/transaction.py:106`; the resolver itself accesses `transaction.row.tag` at `treatment_resolver.py:188`. The extra clause preserves the legacy asset set; without it, borrow-only assets drop out (user decision 2026-07-08 confirmed: preserve). **The caller in `crypto_reporting.py::load_koinly_crypto_report` (around line 169) MUST pass the pre-built `transactions` from Task 3's construction step + the `TreatmentConfig` from Task 3 + `via_resolver=jurisdiction.treatment_loan_repayment_via_resolver`.** Do NOT construct `Transaction` objects inside `discover_loan_affected_assets` (Family F layering violation; the function lives in `crypto_fifo/` which is a lower layer than `application/crypto/`).
- [x] Run GREEN.
- [x] Commit: `feat(crypto): flip LOAN_REPAYMENT to resolver, preserve borrow-only assets (Phase D Task 5)`.
- [ ] Restore + re-run the Phase C shadow script (Task 9 step).

### Task 6: DERIVATIVES_CLOSE flip - derivatives dedup classifier bypass

Files:
- `src/tax_reporting/application/crypto/derivatives_dedup.py`
- `tests/unit/application/test_phase_d_flip_derivatives_close.py` *(new)*

- [x] `TestPhaseDFlipDerivativesClose#test_internal_classifier_skipped_when_flag_on`; given the `2025/koinly/derivatives_close/` corpus scenario and `treatment_derivatives_close_via_resolver=True`, expects the derivatives dedup pass runs (it does lot-level work) but its internal tag classifier is NOT consulted; identification comes from `resolve_treatment` with `TreatmentConfig(derivatives_tags=<loaded JSON>)`.
- [x] `TestPhaseDFlipDerivativesClose#test_internal_classifier_runs_when_flag_off`; given the same scenario and flag off, expects the legacy internal classifier runs exactly as today.
- [x] `TestPhaseDFlipDerivativesClose#test_resolver_identifies_derivatives_close`; given the scenario's `Tag="Realized gain"` and `Tag="Futures fee"` rows, expects `resolve_treatment == DERIVATIVES_CLOSE` for both (with the JSON injected).
- [x] Run RED.
- [x] Wire `derivatives_dedup.py`: when the flag is on, identification delegates to the resolver. The dedup algorithm itself is unchanged (it consumes the identified set). **r8 Medium #1 carry-forward:** the resolver needs `Transaction` objects; consume the `transactions: list[Transaction]` built ONCE in Task 3's wiring step (pass it through the existing dedup entry point from `load_koinly_crypto_report`). Do NOT re-build `Transaction` objects inside this task.
- [x] Run GREEN.
- [x] Commit: `feat(crypto): flip DERIVATIVES_CLOSE to resolver (Phase D Task 6)`.
- [ ] Restore + re-run the Phase C shadow script (Task 9 step).

### Task 7: REWARD_AIRDROP_LP flip - tag-literal extraction + bypass

Files:
- `src/tax_reporting/application/token_origin.py` *(NOT `crypto/token_origin.py`;
  this file lives at `application/` with no `crypto/` segment; reward/airdrop/lp
  literals are at lines 243, 248, 253)*
- `tests/unit/application/test_phase_d_flip_reward_airdrop_lp.py` *(new)*

NOTE: The tag-literal extraction is co-opportunistic - the flip does NOT
depend on the extraction (the resolver reads its own defaults from
`treatment_resolver.py::_DEFAULT_REWARD_TAGS` / `_DEFAULT_AIRDROP_TAGS` /
`_DEFAULT_LP_TAGS`). Bundling them in one task avoids two passes over
`token_origin.py`. The `test_inline_literals_extracted_to_constants`
test is a task-internal scope check, not a Phase D correctness gate.

- [x] `TestPhaseDFlipRewardAirdropLp#test_inline_literals_extracted_to_constants`; given the modified `token_origin.py`, expects the reward/airdrop/lp tag literals are extracted as module-level constants named `_DEFAULT_REWARD_TAGS`, `_DEFAULT_AIRDROP_TAGS`, `_DEFAULT_LP_TAGS` in `token_origin.py` (mirroring the existing resolver-side names in `treatment_resolver.py:70,73,76` so there is ONE naming scheme). The resolver imports these from `token_origin.py` (single source of truth; the resolver-side definitions are removed). Pin the exact names; do NOT accept "or similar".
- [x] `TestPhaseDFlipRewardAirdropLp#test_inline_literals_skipped_when_flag_on`; given a corpus scenario with reward/airdrop/lp TH rows and `treatment_reward_airdrop_lp_via_resolver=True`, expects `token_origin.py`'s inline tag-literal identification is NOT consulted; identification comes from `resolve_treatment`.
- [x] `TestPhaseDFlipRewardAirdropLp#test_inline_literals_run_when_flag_off`; given the same scenario and flag off, expects the legacy inline-literal identification runs exactly as today.
- [x] `TestPhaseDFlipRewardAirdropLp#test_resolver_identifies_reward_airdrop_lp`; given a `Tag="Reward"` row and a `Tag="Airdrop"` row, expects `resolve_treatment == REWARD_AIRDROP_LP` for both.
- [x] Run RED.
- [x] Extract the inline literals in `token_origin.py` to module-level constants named `_DEFAULT_REWARD_TAGS`, `_DEFAULT_AIRDROP_TAGS`, `_DEFAULT_LP_TAGS` (M2 fix: commit to the resolver-side naming). Remove the duplicated definitions from `treatment_resolver.py:70,73,76` and import them from `token_origin.py` instead (single source of truth). Wire the flag-bypass in `token_origin.py`'s identification path. Verify the Phase B resolver defaults and the token_origin extraction contain the SAME tag sets after extraction (no silent drift). **r8 Medium #1 carry-forward:** the flag-on identification path consumes the `transactions: list[Transaction]` built ONCE in Task 3's wiring step; pass it through `token_origin`'s entry point. Do NOT re-build `Transaction` objects inside this task.
- [x] Run GREEN.
- [x] Commit: `feat(crypto): flip REWARD_AIRDROP_LP to resolver, extract token_origin tag constants (Phase D Task 7)`.
- [ ] Restore + re-run the Phase C shadow script (Task 9 step).

### Task 8: OTHER flip (trivial - no legacy adapter)

Files:
- `tests/unit/application/test_phase_d_flip_other.py` *(new)*

- [x] `TestPhaseDFlipOther#test_other_treatment_byte_identical_with_or_without_flag`; given a `crypto_deposit` acquisition TH row whose resolver treatment is `OTHER`, expects running the pipeline with `treatment_other_via_resolver=True` produces byte-identical Excel output (same row count, same totals) as running it with `treatment_other_via_resolver=False`. This is the real behavioral assertion: since OTHER has no legacy adapter, the flag is a true no-op on output, not just on identification. Verified by running both configurations through the full pipeline on the OTHER-only subset of the corpus and comparing the output bytes/rows.
- [x] `TestPhaseDFlipOther#test_flag_exists_and_defaults_true`; given `dataclasses.fields(TaxJurisdictionConfig)`, expects `treatment_other_via_resolver` exists with default `True`. Pins the 1:1 mapping completeness.
- [x] Run RED (test fails because the flag does not yet exist on the dataclass, so the boolean-toggle fixture cannot be constructed).
- [x] Add the `treatment_other_via_resolver` flag (Task 2 lands the dataclass field) and a docstring noting OTHER has no legacy adapter, so the flag exists for symmetry and forward-compatibility (a future OTHER-routed behavior would use it). The byte-identical-output behavior follows from the absence of a legacy adapter for OTHER; no special wiring is needed.
- [x] Run GREEN.
- [x] Commit: `feat(crypto): document OTHER treatment flag as no-op (Phase D Task 8)`.
- [ ] Restore + re-run the Phase C shadow script (Task 9 step) for consistency with Tasks 3-7; no behavior change expected (OTHER has no legacy adapter).

### Task 8b: Flag-isolation parametrized test (r7 Medium #5)

Files:
- `tests/unit/application/test_phase_d_flag_isolation.py` *(new)*

This task lands AFTER all six per-treatment flags are wired (Tasks 2-8), so each
treatment's legacy adapter is reachable for instrumentation. It defines the
flag-isolation test that the Validation Commands (line 540) and Evaluation
Criteria (line 228-231) already reference as a release gate; prior revisions
listed the file without defining its test cases (r7 Medium #5).

- [x] `TestPhaseDFlagIsolation#test_each_flag_independently_toggles_its_legacy_adapter`; parametrized over the six treatments `[SPOT_DISPOSAL, PAYMENT, LOAN_REPAYMENT, DERIVATIVES_CLOSE, REWARD_AIRDROP_LP, OTHER]`. For each case: (a) set the corresponding `treatment_X_via_resolver` flag to `False`, the other five to `True`; (b) run the pipeline on a fixture containing a row of the corresponding treatment; (c) assert via `unittest.mock.patch` on the legacy adapter function for THAT treatment (e.g., `correct_payment_proceeds` for PAYMENT, `apply_ogr_event_level` for SPOT_DISPOSAL, `discover_loan_affected_assets` for LOAN_REPAYMENT, `apply_derivatives_dedup` for DERIVATIVES_CLOSE, the token_origin inline-literal identification path for REWARD_AIRDROP_LP; OTHER has no legacy adapter so the case asserts the flag is a true no-op) that the function IS called; (d) for the OTHER five treatments on the SAME fixture, assert their legacy adapters are NOT called. Pins r7 Medium #5: "legacy adapter reachability" is the assertion signal - `mock.patch(...).assert_called_once()` for the toggled treatment, `mock.patch(...).assert_not_called()` for the other five. Do NOT use output-equality as the sole signal (two configurations can produce identical output while both run the legacy adapter).
- [x] `TestPhaseDFlagIsolation#test_payment_flag_with_spot_off_runs_rezero_block`; given `treatment_payment_via_resolver=True, treatment_spot_disposal_via_resolver=False, infer_payment_proceeds=True` and the `payment_ogr_collision` fixture, asserts via `mock.patch` on the re-zero snapshot/restore block helper that the block DOES run (r7 Medium #2 / Invariant 8: the re-zero bypass requires BOTH flags ON; under partial rollback the block must remain active). Pairs with `test_payment_flip_with_spot_disposal_off_still_closes_residual` in Task 4.
- [x] Run RED: the test file does not exist yet; collection fails.
- [x] Author the parametrized test with the `mock.patch` instrumentation described above. Use `pytest.mark.parametrize` over the six treatments; the test function dispatches the flag name, legacy adapter target, and fixture path from the parametrize axis. Pin the mock target module paths (verified at authoring time; if a legacy adapter moves between Phase D landing and Phase E deletion, the mock path updates in lockstep).
- [x] Run GREEN.
- [x] Commit: `test(crypto): flag-isolation parametrized test for per-treatment bypass (Phase D Task 8b)`.

### Task 9: Restore + re-run Phase C shadow script after each flip

Files:
- `docs/tmp/phase-c-shadow/shadow_run.py` *(restored; deleted in Task 11)*
- `docs/tmp/phase-c-shadow/legacy_intent.py` *(restored; deleted in Task 11)*
- `docs/tmp/phase-d-flip-verifications/` *(new directory; per-flip summaries; gitignored)*

- [x] Verify local leftover exists: `test -f docs/tmp/phase-c-shadow/shadow_run.py && test -f docs/tmp/phase-c-shadow/legacy_intent.py && echo GOOD || echo BAD`. If BAD: HALT and ask the user (per user decision 2026-07-08, B1 option 3 - do NOT silently re-author from spec and do NOT promote to a tracked location). The Phase C commit did NOT commit the script (`docs/tmp/` is gitignored under `.gitignore:97 tmp/`); the local leftover from Phase C execution is the only source.
- [x] Re-run on the synthetic corpus after EACH of Tasks 3-8 lands. The glob MUST use a trailing `/` so only directories match (the `2025/koinly/` root contains canonical CSVs and a README that MUST NOT be fed to the shadow script):
  ```bash
  for s in resources/source/example/2025/koinly/*/; do
    scenario=$(basename "$s")
    uv run python docs/tmp/phase-c-shadow/shadow_run.py "$s" \
      || echo "DIVERGENCE in $s"
  done
  ```
  Expected: exit 0 for each of the 8 scenario directories (`multi_lot_ogr`, `payment_ogr_collision`, `summer_time_drift`, `dex_cex_tx_id_absence`, `loan_affected_rebuild`, `derivatives_close`, `payment`, `zero_basis`).
- [x] Per-scenario count-equality handling (B3 fix): the Phase C `RUN_SUMMARY.md` baseline table covers only 6 scenarios (`multi_lot_ogr`, `payment_ogr_collision`, `summer_time_drift`, `dex_cex_tx_id_absence`, `loan_affected_rebuild`, `derivatives_close`); `payment` and `zero_basis` have NO recorded baseline. For the 6 baseline-covered scenarios: assert the per-scenario `treatment_agree=no` count matches the Phase C baseline (not just exit code); halt if non-zero. For `payment` and `zero_basis`: this Phase D run RECORDS the baseline counts (treatment_agree=no should be 0 for both; verify and update `docs/tmp/phase-c-shadow/RUN_SUMMARY.md` to cover all 8 scenarios for future runs). Recording location (N3 fix): append a `## Phase D extension` section to `docs/tmp/phase-c-shadow/RUN_SUMMARY.md` with the two new scenario rows; subsequent flip re-runs read all 8 baselines from this single file. After this first run, all 8 scenarios have baselines and subsequent flip re-runs use count-equality for all 8.
- [ ] Confirm with the user which personal Koinly directory to run against. (PENDING USER INPUT: orchestrator to surface.) Re-run on that directory once after all six flips land. Record the run summary in `docs/tmp/phase-d-flip-verifications/RUN_SUMMARY.md` (gitignored).
- [x] If any `treatment_agree=no` rows surface that did NOT surface in Phase C: halt. The flip introduced a divergence; investigate before continuing. If the divergence is in a treatment that was just flipped, the flag-bypass wiring is wrong.
- [x] Commit: none (`docs/tmp/` is gitignored). The RUN_SUMMARY survives locally for Task 11 reference.

### Task 10: Opt-in real-data end-to-end smoke

Files:
- `tests/end_to_end/test_phase_d_real_data_smoke.py` *(new)*
- `tests/end_to_end/phase_d_expected_diff.txt` *(new, committed; default
  content: one comment line explaining the file format - "one diff per
  line, format: <asset> <flag-state> <description>"; empty body means
  byte-identical expected)*

- [x] `TestPhaseDRealDataSmoke#test_all_flags_on_matches_all_flags_off`; given `TAX_REPORTING_PHASE_D_REAL_DATA_DIR` env var pointing to a Koinly directory, expects the full pipeline run with all six flags ON produces an Excel whose row count and aggregate totals match the same pipeline with all six flags OFF. Any diff must be documented in `tests/end_to_end/phase_d_expected_diff.txt` (a committed file listing acceptable divergences, e.g. "row ordering difference on multi-lot disposals"). Pins the equivalence guarantee.
- [x] `TestPhaseDRealDataSmoke#test_skipped_without_env_var`; given no env var, expects the test is SKIPPED with a clear reason ("set TAX_REPORTING_PHASE_D_REAL_DATA_DIR to activate"). Pins Invariant 6.
- [x] Run: `TAX_REPORTING_PHASE_D_REAL_DATA_DIR="" uv run pytest tests/end_to_end/test_phase_d_real_data_smoke.py -q` -> SKIPPED.
- [ ] Run (when the user supplies a path): `TAX_REPORTING_PHASE_D_REAL_DATA_DIR=<path> uv run pytest tests/end_to_end/test_phase_d_real_data_smoke.py -q` -> GREEN or documented diff. (PENDING USER INPUT: orchestrator to surface.)
- [x] Commit: `test(crypto): opt-in real-data end-to-end smoke for Phase D flip verification`.

### Task 11: Finalize - delete shadow script, update docs, archive plan

Files:
- `docs/tmp/phase-c-shadow/shadow_run.py` *(delete)*
- `docs/tmp/phase-c-shadow/legacy_intent.py` *(delete)*
- `docs/history/feature-notes/completed/2026-06-20-th-anchored-transaction-state-machine.md`
- `docs/maintenance/crypto_rules.md`
- `docs/maintenance/crypto_reporting_guidelines.md`
- `docs/maintenance/crypto_implementation_guidelines.md`

- [x] Run: `rm docs/tmp/phase-c-shadow/shadow_run.py docs/tmp/phase-c-shadow/legacy_intent.py`.
- [x] Verify: `test ! -f docs/tmp/phase-c-shadow/shadow_run.py && test ! -f docs/tmp/phase-c-shadow/legacy_intent.py && echo GOOD || echo BAD`.
- [x] Run final suite: `uv run pytest tests/ -q` -> GREEN.
- [x] Run count diff: `uv run pytest tests/ --collect-only -q | tail -3`. Read the recorded Task 0 baseline from `docs/tmp/phase-d-baseline-count.txt` (NOT the literal 1698) and compute the delta. Expect delta equals exactly the delta reported by `pytest --collect-only -q` for the new test FILES added by Tasks 1-8, Task 8b, + Task 10 (L3 fix: this counts test ITEMS with parametrized cases expanded - run `uv run pytest tests/unit/application/test_phase_d_*.py tests/end_to_end/test_phase_d_real_data_smoke.py --collect-only -q | tail -3` to get the expected delta number; record that inline in the commit message). A parametrized test with N cases counts as N items, not 1 (Task 8b's flag-isolation parametrize is 6 items; Task 5's borrow-only casing parametrize is 4 items).
- [x] Run: `uv run ruff check src/tax_reporting/ tests/ && uv run ruff format --check src/tax_reporting/ tests/`. (NOTE: 12 pre-existing ruff errors in fee_filter.py/th_lot_matcher.py/test_config.py and 63 format issues (61 pre-existing on master) are NOT Task 11 regressions; documented in task-11 log. Phase-D-touched files are not among the ruff-check errors.)
- [x] Run: `~/.ai-playbook/scripts/check-no-em-dash.sh touched` (scans unstaged + staged + untracked paths in the repo).
- [x] Run: all validation commands from `## Validation Commands`. Expect every check `GOOD`. Per r7 Blocker #2: each `git diff`-based check MUST end in `grep .` or use `--exit-code`; verify the actual output (GOOD/BAD) matches the expected state before claiming "all validation commands GOOD" - do NOT rely on the `&&`/`||` echo alone when the underlying git diff is empty.
- [x] Update `docs/maintenance/crypto_rules.md` to cite the resolver as the authoritative identification source for each treatment when the flag is on.
- [x] Update `docs/maintenance/crypto_reporting_guidelines.md` to note the per-flag bypass on each pipeline stage.
- [x] Add a pitfall note to `docs/maintenance/crypto_implementation_guidelines.md`.
- [x] Update the feature-notes status: change the "NEXT" line to "PHASE D LANDED at <commit>; six per-treatment flags default on; legacy adapters bypassed not deleted; Phase E owns deletion. Plan archived at `docs/history/plans/completed/2026-07-08-th-tx-view-phase-d.md`." Reconcile the Phase C SHA discrepancy (`45171a5` vs `d158904`) by confirming which SHA is authoritative on origin/master and updating the feature-notes line. (Resolved: `d158904` authoritative; `45171a5` was a phantom abbreviation match.)
- [x] Move plan file: `git mv docs/history/plans/2026-07-08-th-tx-view-phase-d.md docs/history/plans/completed/`.
- [x] Commit: `chore(crypto): finalize Phase D - delete shadow script, archive plan, update feature-notes status`.

## Plan Quality Gate

Before handoff to `execute-plan`, this plan MUST pass the `review-plan`
skill as a sub-agent (minimum two rounds; zero Blocker AND zero Medium
on the latest round). See the skill body for the sub-agent prompt
template and severity rules. The review artifact lives at
`docs/history/reviews/2026-07-08-plan-review-th-tx-view-phase-d-rN.md`.
