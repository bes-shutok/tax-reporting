# Plan: TH-anchored Transaction view - Phase C (synthetic corpus + one-shot shadow)

RFC: [docs/history/feature-notes/completed/2026-06-20-th-anchored-transaction-state-machine.md](../../feature-notes/completed/2026-06-20-th-anchored-transaction-state-machine.md#rollout-plan-2026-07-05) (un-shelved 2026-07-05; this is Phase C of the five-phase rollout recorded there).

Phase A plan: [2026-07-05-th-tx-view-phase-a.md](completed/2026-07-05-th-tx-view-phase-a.md) (landed at `bb46bdd`).
Phase B plan: [2026-07-06-th-tx-view-phase-b.md](completed/2026-07-06-th-tx-view-phase-b.md) (landed at `cdb10bf`).

Plan review: [r1](../reviews/2026-07-07-plan-review-th-tx-view-phase-c-r1.md) (2 Blockers + 5 Medium addressed in revision 2; 4 Low notes + 4 Monitor items).

## Terms

- **TH** - Transaction History, the Koinly report whose columns include `Date`
  (explicit UTC), `Type`, `Tag`, per-side wallet/amount/currency fields, and
  the only report with a transaction id (`TxHash`/`TxSrc`/`TxDest`).
- **Treatment** - the Phase-B closed enum (`domain/treatment.py`) with six
  values: `SPOT_DISPOSAL`, `PAYMENT`, `LOAN_REPAYMENT`, `DERIVATIVES_CLOSE`,
  `REWARD_AIRDROP_LP`, `OTHER`. Computed by
  `application/crypto/treatment_resolver.py::resolve_treatment(transaction, config)`.
- **Legacy intent** - the classification each per-treatment legacy classifier
  would assign to a TH row today, derived by re-applying the same tag set each
  legacy module already matches against. Three of the four sources are
  importable module-level constants:
  `payment_proceeds.py::_DEFAULT_PAYMENT_TAGS` (PAYMENT; typed `list[str]` so
  the helper normalizes both sides to lowercase frozensets before any
  membership test, mirroring `treatment_resolver.py::_normalize_tag`),
  `crypto_fifo/contexts.py::_LOAN_PRINCIPAL_TAGS` (LOAN_REPAYMENT; the
  repayment subset is `{"loan repayment"}` because the borrowing-side
  `"loan"` tag is principal creation, excluded per Phase B Invariant 9), and
  the loaded JSON labels at
  `docs/maintenance/tax/derivatives_labels/<provider>_<year>.json`
  (DERIVATIVES_CLOSE). The fourth source - the reward/airdrop/lp tags in
  `token_origin.py` - exists ONLY as inline string literals (lines 243, 248,
  253; no module-level constants today), so the legacy-intent helper
  REPLICATES those literals inline (`{"reward", "cashback", "realized gain"}`
  for reward, `{"airdrop"}` for airdrop, `{"liquidity in", "liquidity out"}`
  for LP) and applies the same case-fold normalization. The inline
  replication is documented as an explicit exception to Invariant 5; a
  Phase D follow-up extracts those literals to module-level constants in
  `token_origin.py` so Phase C's helper can import them. Default:
  disposal-shaped (sending side populated) and no special tag matches ->
  SPOT_DISPOSAL; else OTHER.
- **Correlation key (new path)** - the Phase-A `TxCorrelationKey` returned by
  `TxCorrelationKeyResolver.resolve(transaction)`, anchored on tx-id with a
  `(UTC instant, asset, wallet, amount)` composite fallback (DEX-aware missing-
  id flagging).
- **Correlation key (legacy path)** - the `(local_date, asset, wallet)` tuple
  the live CG/OGR/payment join uses today, where `local_date` is the
  jurisdiction-local calendar day of the disposal (post-timezone-normalization;
  see Phase 1 weakness #3 resolution).
- **One-shot shadow script** - a verification-only Python script under
  `docs/tmp/phase-c-shadow/` that loads a Koinly source directory, runs BOTH
  paths (legacy intent + Phase-A/B new path) on every TH row, and emits a
  per-row discrepancy CSV plus WARNING logs. Not a pipeline stage; never
  imported by production code; never installed as a CLI entry. The script and
  its helpers are DELETED at the end of Phase C per the RFC ("deleted after
  per-phase verification"), with a re-run provision for Phase D documented in
  Monitor.
- **Scenario corpus** - six committed synthetic Koinly fixture directories
  under `resources/source/example/koinly2025_<scenario>/`, one per latent
  failure mode the RFC names. Each contains the 3-4 synthetic CSVs (CG, OGR
  where applicable, income, TH) plus a README. Per CLAUDE.md crypto-test rule,
  scenario directory names use the `koinly<year>_<scenario>` convention
  matching the existing `koinly2025_payment/` and `koinly2025_zero_basis/`
  precedent.
- **Discrepancy CSV** - the script's primary output artifact at
  `docs/tmp/phase-c-shadow/discrepancies.csv` with columns:
  `row_index,type,tag,sending_wallet,sending_currency,sending_amount,
  legacy_intent,resolver_treatment,treatment_agree,legacy_correlation_key,
  new_correlation_key,key_agree,requires_review,notes`. One row per TH row.
  `treatment_agree=yes` for every row is the success criterion; `key_agree`
  is informational because the two key shapes are not directly comparable as
  strings.

## Gist & Examples

### What changes

Phase A landed the typed `Transaction` + `TxCorrelationKey`; Phase B landed
`Treatment` + `resolve_treatment`. Neither has a production caller. Phase C
is verification only - it builds the safety net the RFC names as the primary
regression backstop and produces the evidence Phase D's per-treatment flip
gates on.

Phase C adds three things, all verification-only:

1. **Synthetic corpus.** Six committed Koinly fixture directories under
   `resources/source/example/`, one per RFC scenario:
   `koinly2025_multi_lot_ogr/` (CG key with multiple lots + OGR P&L row on the
   same key - latent weakness #2), `koinly2025_payment_ogr_collision/`
   (Payment disposal + OGR P&L row on the same key - latent weakness #5),
   `koinly2025_summer_time_drift/` (a 00:30 WEST disposal that maps to the
   prior UTC day - weakness #3), `koinly2025_dex_cex_tx_id_absence/` (a
   Ledger DEX row missing `TxHash` and a Kraken CEX row missing `TxHash` -
   Phase A's DEX-flag vs CEX-silent policy), `koinly2025_loan_affected_rebuild/`
   (a loan-tagged asset whose CG is rebuilt from TH - DP-001), and
   `koinly2025_derivatives_close/` (TH rows tagged `Realized gain`/`Futures
   fee` that route through OGR - DP-010/DP-012).

2. **Corpus characterization tests.** A new test module
   `tests/unit/application/test_phase_c_corpus.py` that loads each scenario
   directory, parses every TH row via the Phase-A sanctioned chain
   (`parse_th_row` -> `classify_platform` -> `build_transaction` ->
   `TxCorrelationKeyResolver.resolve` -> `resolve_treatment`), and asserts
   (a) every row produces a `Treatment` member, (b) every row's
   `legacy_intent` (computed by a small corpus-side helper) agrees with the
   resolver, and (c) every disposal row's correlation key has the documented
   shape (tx-id-anchored for DEX with `requires_review=False`; composite for
   CEX).

3. **One-shot shadow script.** A new directory `docs/tmp/phase-c-shadow/`
   (gitignored per the `tmp_dir` policy) containing `shadow_run.py` plus
   `legacy_intent.py`. The script takes one positional argument - the source
   directory to verify - and emits `discrepancies.csv` + WARNING logs. It is
   invoked twice in Phase C: once on the synthetic corpus (smoke + correctness
   of the script itself) and once on the user-supplied real Koinly export
   path (the unknown-unknowns pass). After the second run, the script and
   its helpers are deleted in the same Phase C task that records the run
   summary; Phase D re-creates the script from git history if a re-run is
   needed (Monitor).

### What does NOT change

- No production code in `src/tax_reporting/` changes. Phase C touches
  `application/crypto/`, `application/crypto_fifo/`, `domain/`,
  `infrastructure/`, and `presentation/` NOT AT ALL. The Phase-A and Phase-B
  symbols are exercised by the new tests and the script, but their source
  files are byte-identical before and after Phase C.
- The production CLI `uv run tax-reporting` gains no flag, no argument, no
  behavior change. The `--source-dir` flag exists only on the throwaway
  `docs/tmp/phase-c-shadow/shadow_run.py` (positional argument, in fact - not
  even a flag) and is deleted with the script.
- No new public exports in `application/crypto/entities.py`. Phase C does
  not re-export anything new.
- No change to `docs/maintenance/crypto_rules.md`,
  `crypto_reporting_guidelines.md`, `crypto_implementation_guidelines.md`,
  `koinly_guidelines.md`, or any decision-point TOML. Phase C has no rule
  or filing-output change.
- No change to `config.ini` or `tests/config.ini`. The script reads the
  derivatives labels JSON via the existing production loader
  (`derivatives_dedup.py::_load_derivatives_labels_config`) to guarantee the
  injected `derivatives_tags` matches production; no new config key.
- The feature-notes RFC file gains a status update only (Phase C plan
  reference and "landed at <commit>" line after execution; populated when
  Phase C lands).

### Concrete example

Given `koinly2025_payment_ogr_collision/` - a synthetic 2025 export where a
single EUROC disposal on Wirex has BOTH a CG lot (proceeds=0, cost=20 EUR)
AND an OGR Profit/Loss row (Value=-15 EUR) under the same legacy key
`(2025-06-15, EUROC, Wirex)`:

- **Legacy intent** for the TH row: `Tag="Payment"`, sending side populated,
  no loan/derivatives/reward tag -> matches `payment_proceeds.py` payment
  frozenset -> `PAYMENT`.
- **Resolver** for the same TH row: `resolve_treatment(tx, TreatmentConfig())`
  -> `Treatment.PAYMENT`.
- **`treatment_agree`**: `yes`.
- **`legacy_correlation_key`**: `(2025-06-15, EUROC, Wirex)`.
- **`new_correlation_key`**: tx-id-anchored (Wirex is CEX, no `requires_review`
  flag even if `TxHash` is empty per Phase-A policy) or composite - whatever
  Phase A produces; the discrepancy row records which.
- **`key_agree`**: `n/a` if the new key is tx-id-anchored (the keys are not
  comparable as strings); the script records both for inspection, not for
  pass/fail. Only `treatment_agree` is the success gate for this scenario.

Given `koinly2025_multi_lot_ogr/` - a synthetic 2025 export where one CG key
`(2025-03-10, ETH, Kraken)` has two FIFO lots AND one OGR Profit row matches
the same key (the latent over-count case from weakness #2):

- **Legacy intent** for the TH row: `Tag=""`, sending side populated, no
  special tag -> SPOT_DISPOSAL.
- **Resolver**: `Treatment.SPOT_DISPOSAL`.
- **`treatment_agree`**: `yes`.
- The scenario's purpose is structural: it confirms the new path's
  per-Transaction grouping (one event -> N lots) does not collapse the two
  CG lots into the OGR row's identity. The corpus test asserts the TH row's
  correlation key has shape `tx_id=<hash>, composite=(...)` regardless of
  how many CG lots join it - the structural property Phase D needs before
  flipping the OGR override.

Given `koinly2025_summer_time_drift/` - a synthetic 2025 export with a
`2025-07-15 00:30:00 WEST` (= `2025-07-14 23:30:00 UTC`) disposal:

- **Legacy intent** for the TH row: `Tag=""`, sending side populated ->
  SPOT_DISPOSAL. Legacy key uses local_date `2025-07-15`.
- **Resolver**: `Treatment.SPOT_DISPOSAL`.
- **`new_correlation_key`**: composite anchored on the UTC instant
  `2025-07-14T23:30:00Z` (or tx-id if `TxHash` is populated).
- The corpus test asserts the TH row's composite key uses the UTC instant,
  NOT the local calendar day, confirming the timezone fix from weakness #3
  is preserved by the new path.

### Why this chunk

Per the rollout table, Phase C is "verification only - no behavior change."
The synthetic corpus is the primary regression backstop (per the 2026-07-05
safety-net choice in the RFC), and the one-shot shadow script is the
unknown-unknowns probe that surfaces divergences between the new typed path
and the legacy per-treatment classifiers BEFORE any production caller flips.
Phase D's per-treatment flip gates on the evidence Phase C produces: a
treatment flips only when its corpus scenario AND its real-data shadow run
show `treatment_agree=yes` for every row.

## Evaluation Criteria

**Quality dimensions:**

- **No production code change (correctness floor):** `git diff master..HEAD
  --name-only -- src/tax_reporting/` is empty. Phase C touches only
  `resources/source/example/`, `tests/unit/application/`, and
  `docs/tmp/phase-c-shadow/` (the last gitignored). Verified by a `git diff`
  invocation in the final task.
- **Resolver agrees with legacy intent on every TH row in the corpus:**
  every row in every scenario directory has `treatment_agree=yes` in the
  discrepancy CSV. Verified by `test_phase_c_corpus.py` parametrized over
  (scenario, row_index) and by the shadow script's exit code (0 iff zero
  disagreements).
- **Resolver totality on real data:** the shadow run on the user-supplied
  Koinly directory completes without raising and emits one CSV row per TH
  row, no row dropped (TH row count == CSV row count). Verified by a
  count-equality assertion in the script's post-run summary log.
- **Correlation key shape per scenario:** each scenario's disposal rows
  produce a key whose shape matches the documented expectation
  (DEX-without-txid -> `requires_review=True`; CEX-without-txid ->
  `requires_review=False` with composite fallback; DEX-with-txid ->
  `requires_review=False` with tx-id primary). Verified by per-scenario
  assertions in `test_phase_c_corpus.py`.
- **Throwaway discipline:** no `src/tax_reporting/` module imports anything
  from `docs/tmp/phase-c-shadow/`. Verified by a grep in the validation
  block. The script and its helper are deleted in the final task; only the
  run-summary artifact survives (under `docs/tmp/`, gitignored).
- **No new public API:** `application/crypto/entities.py` is unchanged.
  Verified by `git diff master..HEAD -- src/tax_reporting/application/crypto/entities.py`
  being empty.
- **No new CLI flag:** `src/tax_reporting/main.py` is unchanged. Verified
  by `git diff master..HEAD -- src/tax_reporting/main.py` being empty.
- **Corpus fixture hygiene:** every CSV in every scenario uses the
  `_synth.csv` filename token (matching the existing `koinly2025_payment/`
  precedent) and contains no real wallet addresses, no real tx hashes, no
  real amounts traceable to personal data. Wallet labels use synthetic
  platforms already registered in the operator map (Wirex, Kraken, ByBit,
  Ledger Berachain (BERA), SUI) so the WalletKindResolver resolves valid
  kinds.

**Release gates:**

- All existing crypto tests pass unchanged (count diff vs Phase B baseline
  = +new test functions only).
- `uv run pytest tests/unit/application/test_phase_c_corpus.py -q` GREEN,
  no skips, no xfails.
- `uv run ruff check src/tax_reporting/ tests/` clean (no new lint errors).
- `~/.ai-playbook/scripts/check-no-em-dash.sh` clean on changed files.
- Shadow script run on synthetic corpus: exit 0, `discrepancies.csv` row
  count == total TH row count across all six scenarios, every row
  `treatment_agree=yes`.
- Shadow script run on user-supplied real Koinly export: exit 0, row count
  matches TH row count; any `treatment_agree=no` row is recorded in the
  run-summary artifact for Phase D triage (does NOT block Phase C closure;
  the divergence IS the Phase D input).
- `docs/tmp/phase-c-shadow/shadow_run.py` and `legacy_intent.py` are
  deleted in the final task; the run-summary artifact survives at
  `docs/tmp/phase-c-shadow/RUN_SUMMARY.md` (gitignored) and is referenced
  in the feature-notes status update.

## Review Scope

**Explicit must-fix**; findings on these paths are always in scope (review
and fix if valid):

**Production code:** NONE. Phase C touches no file under `src/tax_reporting/`.

**Tests (new files):**

- `tests/unit/application/test_phase_c_corpus.py` *(new)* - parametrized
  per-scenario loader and assertions.

**Test fixtures (new directories under `resources/source/example/`):**

- `resources/source/example/koinly2025_multi_lot_ogr/` *(new)* - README +
  CG/Income/TH/OGR CSVs (this scenario INCLUDES OGR so income must also be
  present per the loader contract).
- `resources/source/example/koinly2025_payment_ogr_collision/` *(new)* -
  README + CG/Income/TH/OGR.
- `resources/source/example/koinly2025_summer_time_drift/` *(new)* - README
  + CG/Income/TH.
- `resources/source/example/koinly2025_dex_cex_tx_id_absence/` *(new)* -
  README + CG/Income/TH. Two TH rows: one Ledger DEX, one Kraken CEX.
- `resources/source/example/koinly2025_loan_affected_rebuild/` *(new)* -
  README + CG/Income/TH. TH row with `Tag="Loan"` (borrowing) and a paired
  `Tag="Loan Repayment"` disposal row.
- `resources/source/example/koinly2025_derivatives_close/` *(new)* - README
  + CG/Income/TH/OGR. TH rows tagged `Realized gain` and `Futures fee`.

**Throwaway verification artifacts (new, gitignored under `docs/tmp/`):**

- `docs/tmp/phase-c-shadow/shadow_run.py` *(new; deleted in final task)*
- `docs/tmp/phase-c-shadow/legacy_intent.py` *(new; deleted in final task)*
- `docs/tmp/phase-c-shadow/discrepancies.csv` *(output artifact; gitignored)*
- `docs/tmp/phase-c-shadow/RUN_SUMMARY.md` *(output artifact; gitignored)*

**Plan-related extension;** Phase C is verification only. Treat a finding as
in scope when it is causally related to either the corpus design or the
shadow script's verification contract: a scenario that fails to exhibit the
latent failure mode it is named for, a corpus fixture whose wallet label is
not registered in the operator-origin registry (would surface a
`WalletKind.UNKNOWN` review flag that masks the property under test), a
discrepancy CSV column whose semantics drift from the Terms definition, an
assert in `test_phase_c_corpus.py` that passes for the wrong reason (e.g.
asserts totality but not agreement), or a script path that the production
loader would auto-discover (it must NOT be on any production import path).

**Out of scope; reject unless plan-related:**

- `src/tax_reporting/**`; Phase C makes no production code change. Any
  finding that requires editing production code is by definition out of
  scope for Phase C and routes to Phase D.
- `docs/maintenance/crypto_rules.md`,
  `crypto_reporting_guidelines.md`, `crypto_implementation_guidelines.md`,
  `koinly_guidelines.md`; Phase C has no rule or filing-output change.
- `config.ini`, `tests/config.ini`; Phase C adds no config key.
- Migrating any production caller from the legacy per-treatment classifiers
  to `resolve_treatment`; that is Phase D per-treatment flip work.
- Running the shadow script in CI or as a pre-commit hook; the script is
  deleted at end of Phase C and is not a permanent pipeline stage.

## Design Invariants (CR Guard)

1. **Phase C touches zero production code.** `src/tax_reporting/` is
   byte-identical before and after Phase C. CR guard: reject any change to
   `src/tax_reporting/**`. Rationale: the RFC names Phase C as
   "verification only - no behavior change"; mixing production edits into
   verification violates the rollout-phase contract and forces review to
   reason about behavior change AND verification at once.

2. **The shadow script is throwaway; it has no production footprint.** No
   file under `src/tax_reporting/` imports from `docs/tmp/phase-c-shadow/`.
   The script is never registered as an entry point in `pyproject.toml`;
   it is invoked by absolute path only (`uv run python
   docs/tmp/phase-c-shadow/shadow_run.py <source_dir>`). CR guard: reject
   any `[project.scripts]` entry, any `src/tax_reporting/` import of the
   script, or any test that imports the script's helpers as a permanent
   dependency (the corpus characterization tests must NOT import
   `legacy_intent.py`; they replicate the legacy intent inline so they
   survive the script's deletion). Rationale: per the user directive
   (2026-07-07), the script-located positional argument is acceptable ONLY
   because it lives on a throwaway script; production gains no flag.

3. **The script is deleted at end of Phase C; Phase D re-creates from git
   history if needed.** The Phase C final task removes
   `docs/tmp/phase-c-shadow/shadow_run.py` and `legacy_intent.py`. The
   `RUN_SUMMARY.md` artifact survives (gitignored) as Phase D's reference
   for what the script proved. CR guard: reject any task that "keeps the
   script for Phase D" by leaving it on disk; the RFC is explicit that
   the script is deleted after per-phase verification. Rationale: the
   user's 2026-07-07 confirmation - the script's lifecycle ends with the
   feature; Phase E deletes any remaining artifacts. Phase D, if it needs
   a re-run, restores the script from `git show <phase-c-commit>:docs/tmp/...`
   (the file is gitignored so this requires a manual restore - intentional
   friction to prevent silent persistence).

4. **Scenario fixtures use committed synthetic data only.** Every CSV in
   `resources/source/example/koinly2025_<scenario>/` is fully synthetic
   (no real wallet addresses, no real tx hashes, no amounts traceable to
   personal data) and uses the `_synth.csv` filename token. CR guard:
   reject any fixture whose CSV contains a 0x-prefixed 40+ hex wallet
   address, a 64-hex tx hash, or an amount that matches a value known to
   appear in `resources/source/koinly*` (the gitignored personal data).
   Rationale: CLAUDE.md crypto-test rule ("Crypto tests MUST read committed
   synthetic data ... never reference gitignored personal data") +
   Family-G (verify the real thing: a test against personal data is not a
   test).

5. **The legacy intent is computed by re-using the production tag sources,
   not by re-implementing them.** The corpus tests and the shadow helper
   import `_DEFAULT_PAYMENT_TAGS` from `payment_proceeds.py` (typed
   `list[str]`; the helper normalizes both sides to lowercase frozensets
   before any membership test, mirroring `treatment_resolver.py::_normalize_tag`),
   `_LOAN_PRINCIPAL_TAGS` from `crypto_fifo/contexts.py`, and call
   `_load_derivatives_labels_config("koinly", 2025)` for the derivatives
   set. The reward/airdrop/lp tag literals from `token_origin.py` are
   REPLICATED INLINE because that module exposes them only as inline
   string literals (lines 243, 248, 253; no module-level constants today);
   a Phase D follow-up extracts those literals to module-level constants
   so Phase C's helper can import them. CR guard: reject any code path
   in the corpus tests or the shadow helper that hardcodes a tag string
   the production modules already export as a module-level constant
   (i.e. `_DEFAULT_PAYMENT_TAGS`, `_LOAN_PRINCIPAL_TAGS`, and the
   derivatives JSON). Rationale: CLAUDE.md "Never introduce a hardcoded
   value ... without first flagging it" + Family D (single source of
   truth; if the production tag set drifts, the corpus tests MUST see
   the drift, not paper over it).

6. **Treatment comparison is row-by-row, not aggregate.** The success
   criterion is `treatment_agree=yes` for EVERY TH row, not "majority
   agree" or "aggregate totals match." CR guard: reject any assertion or
   script output that aggregates disagreements into a single metric
   without per-row visibility. Rationale: Family-G (data-loss
   observability); an aggregate "98% agree" hides the 2% that Phase D
   needs to triage.

7. **The script's exit code is the gate.** Exit 0 iff zero
   `treatment_agree=no` rows AND the discrepancy CSV row count equals the
   TH row count. Any other condition exits non-zero. CR guard: reject
   `sys.exit(0)` on a path that recorded a disagreement. Rationale: the
   script is the Phase D input; a clean exit must mean "no Phase D
   blockers from this run."

8. **`requires_review` is recorded, not gated.** A DEX row missing a
   tx-id sets `requires_review=True` per Phase A; the script records this
   in the discrepancy CSV's `requires_review` column. It is NOT a
   disagreement (treatment agreement can still be `yes`). CR guard: reject
   any code that treats `requires_review=True` as a script failure.
   Rationale: the flag is informational; Phase A made the policy choice
   (DEX-flag, CEX-silent) and Phase C records it, not second-guesses it.

9. **The real-data shadow run is user-initiated, never auto-discovered.**
   The script takes one positional argument: the source directory. It
   does NOT glob `resources/source/koinly*` or any other personal-data
   root. It does NOT read `config.ini`. CR guard: reject any glob over
   `resources/source/koinly*` or any other personal-data root, any
   `os.environ` read of a personal-data path in the script. Globbing
   WITHIN the user-supplied positional `<source_dir>` is the sanctioned
   filename-discovery pattern (Task 9 bullet a). Rationale: per the
   user's 2026-07-07 answer, the script refuses to auto-discover
   gitignored personal data; the user supplies the path explicitly per
   run. This is the explicit consent mechanism.

10. **No em dash in any new file.** Per the project's em-dash rule
    (CLAUDE.md hard rule), `shadow_run.py`, `legacy_intent.py`, every
    scenario README, and `test_phase_c_corpus.py` use ASCII `-` (hyphen)
    or ` - ` (space-hyphen-space) instead of U+2014. The
    `check-no-em-dash.sh` script gates this. CR guard: reject any U+2014
    in changed files.

## Validation Commands

```bash
# Phase C floor: NO production code change
git diff master..HEAD --name-only -- src/tax_reporting/ \
  && echo "BAD: production code touched" \
  || echo "GOOD: no production code change"

# No new public API or CLI flag
git diff master..HEAD --name-only \
  -- src/tax_reporting/main.py \
     src/tax_reporting/application/crypto/entities.py \
  && echo "BAD: CLI or entities touched" \
  || echo "GOOD: CLI and entities unchanged"

# New corpus characterization tests pass (no skips)
uv run pytest tests/unit/application/test_phase_c_corpus.py -q

# Existing crypto suite still GREEN with count diff = +new tests only
uv run pytest tests/unit/application/ tests/unit/domain/ tests/end_to_end/ \
  --collect-only -q | tail -3

# Lint clean on changed files
uv run ruff check tests/unit/application/test_phase_c_corpus.py
uv run ruff format --check tests/unit/application/test_phase_c_corpus.py

# Em dash check on changed files
~/.ai-playbook/scripts/check-no-em-dash.sh

# Throwaway discipline: no production import of the shadow script
grep -rnE 'phase-c-shadow|shadow_run|legacy_intent' src/tax_reporting/ \
  && echo "BAD: production imports shadow script" \
  || echo "GOOD: shadow script is throwaway"

# No [project.scripts] entry for the shadow script
grep -nE 'shadow_run|phase-c-shadow' pyproject.toml \
  && echo "BAD: shadow script registered as entry point" \
  || echo "GOOD: no entry point for shadow script"

# Shadow script smoke run on synthetic corpus
uv run python docs/tmp/phase-c-shadow/shadow_run.py \
  resources/source/example/koinly2025_multi_lot_ogr \
  && echo "GOOD: smoke run exit 0" \
  || echo "BAD: smoke run failed"

# After final task: shadow script and helper deleted
test ! -f docs/tmp/phase-c-shadow/shadow_run.py \
  && test ! -f docs/tmp/phase-c-shadow/legacy_intent.py \
  && echo "GOOD: throwaway script deleted" \
  || echo "BAD: throwaway script persists"
```

The first three checks are contract-removal-style: any non-empty diff or
non-comment match is a violation. The smoke-run check is the canonical
executable artifact (per Validation Commands authoring rule #2: exercise the
labeled script-to-run, not an illustrative snippet). The final check
enforces Invariant 3 (throwaway discipline). NOTE: these checks run on the
Phase C branch pre-merge; they become no-ops once Phase C lands on master
and are not re-runnable as written.

## Documentation Impact Assessment

Phase C adds verification-only artifacts. No user-visible Excel change, no
config key, no CLI flag.

- `docs/maintenance/crypto_rules.md` - no change. Phase D will edit it when
  the per-treatment flip lands.
- `docs/maintenance/crypto_reporting_guidelines.md` - no change.
- `docs/maintenance/crypto_implementation_guidelines.md` - no change.
- `README.md` - no change.
- `docs/history/feature-notes/completed/2026-06-20-th-anchored-transaction-state-machine.md`
  - status update only (Phase C plan reference, "landed at <commit>" line
  populated when Phase C lands).

The scenario READMEs (one per fixture directory) are the canonical
description of each latent failure mode the corpus exercises; they cite the
RFC weakness number (#1-#5) and the DP/PT-C ID where applicable.

## Monitor

- **Phase D re-run provision.** Phase D may need to re-run the shadow script
  after flipping a treatment to confirm the flip did not introduce a new
  divergence. The script is deleted at end of Phase C; Phase D restores it
  from the Phase C commit (via `git show <commit>:docs/tmp/phase-c-shadow/shadow_run.py
  > docs/tmp/phase-c-shadow/shadow_run.py`) OR re-implements a smaller
  per-treatment verifier. Owner: Phase D plan must declare which approach
  it takes and list any new scenario fixtures it adds to the corpus.
- **Real-data divergence handling.** If the real-data shadow run surfaces
  `treatment_agree=no` rows, those rows are the Phase D input. Phase C
  records them in `docs/tmp/phase-c-shadow/RUN_SUMMARY.md` (gitignored,
  survives the script deletion) and in the feature-notes status update.
  Phase D triages each divergence per treatment. Owner: Phase D plan.
- **Scenario corpus may grow.** A future Koinly export may exhibit a latent
  failure mode not covered by the six Phase C scenarios (e.g. a
  wrapped-asset repair case). Adding a scenario requires a new
  `koinly2025_<scenario>/` directory, a new README, a parametrized case in
  `test_phase_c_corpus.py`, and a one-line amendment to this plan's
  Invariant 4 list. Owner: Phase D plan (or any future plan that extends
  the corpus).
- **Derivatives labels JSON may grow.** If the production koinly_2025
  labels JSON gains a new tag, the `derivatives_close` scenario must add a
  TH row with that tag. The corpus test asserts the scenario exercises
  every tag in the JSON. Owner: Phase D plan (or any plan that updates the
  JSON).
- **Loan-affected rebuild scenario coverage.** The
  `koinly2025_loan_affected_rebuild/` scenario covers the borrow-then-repay
  flow for ONE asset. Phase D's loan-affected flip may need a richer
  scenario (cross-asset carry-over, multi-repayment). Owner: Phase D plan.

### Task 0: Baseline test count and clean-tree confirmation

Files:
- (no file changes; baseline-capture only)

- [x] Run: `uv run pytest tests/unit/application/ tests/unit/domain/ tests/end_to_end/ --collect-only -q | tail -3` and record the test count. Save to `docs/tmp/phase-c-baseline-count.txt`. **Expected baseline: 1510 tests collected (per Phase B Task 4 final count).** Halt and ask the user if the actual baseline differs from 1510.
- [x] Run: `git status` to confirm the working tree is clean except for the plan file (committed by the gate step) and the scratch baseline file (under gitignored `docs/tmp/`). Halt and ask the user if unexpected changes appear.
- [x] Commit: none. Baseline is recorded for the Task 8 count-diff check.

### Task 1: Scenario corpus - `koinly2025_multi_lot_ogr/`

Files:
- `resources/source/example/koinly2025_multi_lot_ogr/README.md` *(new)*
- `resources/source/example/koinly2025_multi_lot_ogr/koinly_2025_capital_gains_report_synth.csv` *(new)*
- `resources/source/example/koinly2025_multi_lot_ogr/koinly_2025_income_report_synth.csv` *(new)*
- `resources/source/example/koinly2025_multi_lot_ogr/koinly_2025_other_gains_report_synth.csv` *(new)*
- `resources/source/example/koinly2025_multi_lot_ogr/koinly_2025_transaction_history_synth.csv` *(new)*

- [x] Author the four CSVs with this scenario shape: ONE CG key `(2025-03-10, ETH, Kraken)` containing TWO FIFO lots (e.g. 0.5 ETH cost 800 EUR + 0.5 ETH cost 850 EUR, both sold for total proceeds 2000 EUR), ONE OGR Profit row matching the same key (`Value (EUR)=+1000`, `Type=Profit`), and ONE TH `crypto_withdrawal` row for the same disposal (sending 1.0 ETH from Kraken, `Tag=""`, populated `TxHash`). Income CSV has one synthetic cashback row to satisfy the loader's all-or-nothing validation. No real wallet addresses or tx hashes; use placeholder `0x` + 64 zeros for `TxHash`.
- [x] Author the README citing: the scenario name, the RFC weakness #2 (multi-lot OGR over-count), the synthetic data invariant, the file list with mandatory/optional flags, and the test that backs it (`test_phase_c_corpus.py::test_corpus_scenario[multi_lot_ogr]`). Mirror the structure of `resources/source/example/koinly2025_payment/README.md`.
- [x] Verify: `uv run python -c "from tax_reporting.infrastructure.koinly_parser import parse_th_row; import csv; rows=list(csv.DictReader(open('resources/source/example/koinly2025_multi_lot_ogr/koinly_2025_transaction_history_synth.csv'))); [parse_th_row(r, row_index=i) for i,r in enumerate(rows)]; print('parse OK', len(rows))"` -> expect `parse OK 1`.
- [x] Commit: `test(crypto): add multi_lot_ogr synthetic corpus fixture (Phase C Task 1)`

### Task 2: Scenario corpus - `koinly2025_payment_ogr_collision/`

Files:
- `resources/source/example/koinly2025_payment_ogr_collision/README.md` *(new)*
- `resources/source/example/koinly2025_payment_ogr_collision/koinly_2025_capital_gains_report_synth.csv` *(new)*
- `resources/source/example/koinly2025_payment_ogr_collision/koinly_2025_income_report_synth.csv` *(new)*
- `resources/source/example/koinly2025_payment_ogr_collision/koinly_2025_other_gains_report_synth.csv` *(new)*
- `resources/source/example/koinly2025_payment_ogr_collision/koinly_2025_transaction_history_synth.csv` *(new)*

- [x] Author the four CSVs with this scenario shape: ONE CG row `(2025-06-15, EUROC, Wirex)` with `proceeds=0, cost=20 EUR`; ONE OGR Loss row matching the same key (`Value (EUR)=15, Type=Loss`); ONE TH `crypto_withdrawal` row for the disposal with `Tag="Payment"`, sending 100 EUROC from Wirex, `Net Value (EUR)=0,00`. Income CSV has one synthetic cashback row. Wallet label is `Wirex` (registered). No `TxHash` (CEX, falls back silently per Phase A policy).
- [x] Author the README citing: scenario name, RFC weakness #5 (Payment/OGR collision - the re-zero block's contested premise), synthetic-data invariant, file list, backing test. Note explicitly: the scenario reproduces the latent collision; Phase C verifies the resolver still classifies the row as `PAYMENT` (the re-zero block is not the subject of Phase C; Phase D owns its removal).
- [x] Verify: `uv run python -c "from tax_reporting.infrastructure.koinly_parser import parse_th_row; import csv; rows=list(csv.DictReader(open('resources/source/example/koinly2025_payment_ogr_collision/koinly_2025_transaction_history_synth.csv'))); [parse_th_row(r, row_index=i) for i,r in enumerate(rows)]; print('parse OK', len(rows))"` -> expect `parse OK 1`.
- [x] Commit: `test(crypto): add payment_ogr_collision synthetic corpus fixture (Phase C Task 2)`

### Task 3: Scenario corpus - `koinly2025_summer_time_drift/`

Files:
- `resources/source/example/koinly2025_summer_time_drift/README.md` *(new)*
- `resources/source/example/koinly2025_summer_time_drift/koinly_2025_capital_gains_report_synth.csv` *(new)*
- `resources/source/example/koinly2025_summer_time_drift/koinly_2025_income_report_synth.csv` *(new)*
- `resources/source/example/koinly2025_summer_time_drift/koinly_2025_transaction_history_synth.csv` *(new)*

- [x] Author the three CSVs with this scenario shape: ONE CG row `Date Sold = 15/07/2025 00:30` (WEST summer time = `2025-07-14T23:30:00Z` UTC), asset ETH, wallet Kraken, `proceeds=300, cost=200`; ONE TH `crypto_withdrawal` row with `Date = 2025-07-14 23:30:00 UTC`, sending 1.0 ETH from Kraken, `Tag=""`. Income CSV has one synthetic cashback row. No OGR (loader's all-or-nothing requires CG/Income/TH; OGR optional).
- [x] Author the README citing: scenario name, RFC weakness #3 (timezone drift in summer 00:00-01:00 local window), the timezone fix from the crypto-timezone-normalization plan, the synthetic-data invariant, the file list, the backing test. Note: this scenario confirms the new path's composite correlation key uses the UTC instant (`2025-07-14T23:30:00Z`), NOT the local calendar day (`2025-07-15`).
- [x] Verify parse: `uv run python -c "from tax_reporting.infrastructure.koinly_parser import parse_th_row; import csv; rows=list(csv.DictReader(open('resources/source/example/koinly2025_summer_time_drift/koinly_2025_transaction_history_synth.csv'))); r=parse_th_row(rows[0], row_index=0); print(r.date)"` -> expect an aware datetime at `2025-07-14 23:30:00+00:00`.
- [x] Commit: `test(crypto): add summer_time_drift synthetic corpus fixture (Phase C Task 3)`

### Task 4: Scenario corpus - `koinly2025_dex_cex_tx_id_absence/`

Files:
- `resources/source/example/koinly2025_dex_cex_tx_id_absence/README.md` *(new)*
- `resources/source/example/koinly2025_dex_cex_tx_id_absence/koinly_2025_capital_gains_report_synth.csv` *(new)*
- `resources/source/example/koinly2025_dex_cex_tx_id_absence/koinly_2025_income_report_synth.csv` *(new)*
- `resources/source/example/koinly2025_dex_cex_tx_id_absence/koinly_2025_transaction_history_synth.csv` *(new)*

- [x] Author the three CSVs with this scenario shape: TWO TH rows - (a) a Ledger DEX `crypto_withdrawal` sending 0.5 BERA from `Ledger Berachain (BERA)` with `TxHash=""` (DEX missing tx-id - Phase A sets `requires_review=True`), and (b) a Kraken CEX `crypto_withdrawal` sending 0.5 ETH from Kraken with `TxHash=""` (CEX missing tx-id - Phase A silently falls back to composite). Two CG rows, one per disposal. Income CSV has one synthetic cashback row.
- [x] Author the README citing: scenario name, Phase A's DEX-flag vs CEX-silent tx-id policy (RFC "Tx-id fallback policy (2026-07-05)"), the synthetic-data invariant, the file list, the backing test. Note: this scenario confirms the discrepancy CSV's `requires_review` column correctly differentiates the two rows.
- [x] Verify parse: the inline Python must construct a STUB REGISTRY (mirroring `tests/unit/application/test_crypto_phase_a_smoke.py::_KrakenRegistry`) returning `WalletKind.CEX` for `{"Kraken", "ByBit", "Wirex"}` and `WalletKind.DEX` for `{"Ledger Berachain (BERA)", "SUI", "Ledger"}`. The corpus tests cannot rely on the evidence path alone: a single `crypto_withdrawal` row votes "on_chain" regardless of platform name (see `wallet_kind.py:_vote`), so without the stub both Kraken and Wirex resolve to DEX and `requires_review=True` for both rows, contradicting Phase A's CEX-silent policy. The stub is the corpus-side substitute for the production registry binding that Phase A defers to a later task.
  ```bash
  uv run python -c "
  import csv
  from tax_reporting.application.crypto.wallet_kind import WalletKind, classify_platform, aggregate_platform_evidence
  from tax_reporting.application.crypto.transaction_factory import build_transaction
  from tax_reporting.application.crypto.tx_correlation_key_resolver import TxCorrelationKeyResolver
  from tax_reporting.infrastructure.koinly_parser import parse_th_row

  class _StubRegistry:
      _CEX = {'Kraken', 'ByBit', 'Wirex'}
      _DEX = {'Ledger Berachain (BERA)', 'SUI', 'Ledger'}
      def classify(self, platform):
          if platform in self._CEX: return WalletKind.CEX
          if platform in self._DEX: return WalletKind.DEX
          return None

  rows=list(csv.DictReader(open('resources/source/example/koinly2025_dex_cex_tx_id_absence/koinly_2025_transaction_history_synth.csv')))
  for i,r in enumerate(rows):
      tr=parse_th_row(r, row_index=i)
      ev=aggregate_platform_evidence([tr])
      p = tr.sending_wallet or tr.receiving_wallet
      cl=classify_platform(p, ev.get(p), _StubRegistry())
      tx=build_transaction(tr, cl)
      k,flag=TxCorrelationKeyResolver.resolve(tx)
      print(p, 'flag=', flag)
  "
  ```
  Expect `Ledger Berachain (BERA) flag= True` and `Kraken flag= False`.
- [x] Commit: `test(crypto): add dex_cex_tx_id_absence synthetic corpus fixture (Phase C Task 4)`

### Task 5: Scenario corpus - `koinly2025_loan_affected_rebuild/`

Files:
- `resources/source/example/koinly2025_loan_affected_rebuild/README.md` *(new)*
- `resources/source/example/koinly2025_loan_affected_rebuild/koinly_2025_capital_gains_report_synth.csv` *(new)*
- `resources/source/example/koinly2025_loan_affected_rebuild/koinly_2025_income_report_synth.csv` *(new)*
- `resources/source/example/koinly2025_loan_affected_rebuild/koinly_2025_transaction_history_synth.csv` *(new)*

- [x] Author the three CSVs with this scenario shape: TH has THREE rows - (a) a `crypto_deposit` with `Tag="Loan"` (borrowing-side principal creation), receiving 0.1 WBTC to ByBit, (b) a `crypto_withdrawal` with `Tag="Loan Repayment"` (the disposal-repayment), sending 0.1 WBTC from ByBit, and (c) a `crypto_exchange` plain spot disposal of 0.05 ETH for contrast. CG rows for the loan repayment (rebuilt from TH in production via DP-001) and the spot disposal. Income CSV has one synthetic cashback row. Note in README: Phase C verifies the resolver classifies the `Tag="Loan"` row as `OTHER` (Invariant 9 from Phase B - borrowing is not repayment) and the `Tag="Loan Repayment"` row as `LOAN_REPAYMENT`.
- [x] Author the README citing: scenario name, DP-001 loan-repayment non-taxable treatment, Phase B Invariant 9 (`"loan"` borrowing tag does NOT resolve to `LOAN_REPAYMENT`), the synthetic-data invariant, the file list, the backing test.
- [ ] Verify parse + resolver: same stub-registry pattern as Task 4 (ByBit is CEX in the stub). The treatment-resolver does NOT consult the registry (it reads `transaction.row.tag` and `transaction.row.sending_currency` only), so this verify is robust to the registry; the stub is required only for `build_transaction` to construct a non-UNKNOWN `Transaction`.
  ```bash
  uv run python -c "
  import csv
  from tax_reporting.infrastructure.koinly_parser import parse_th_row
  from tax_reporting.application.crypto.wallet_kind import WalletKind, classify_platform, aggregate_platform_evidence
  from tax_reporting.application.crypto.transaction_factory import build_transaction
  from tax_reporting.application.crypto.treatment_resolver import resolve_treatment, TreatmentConfig

  class _StubRegistry:
      def classify(self, platform):
          if platform in {'Kraken','ByBit','Wirex'}: return WalletKind.CEX
          if platform in {'Ledger Berachain (BERA)','SUI','Ledger'}: return WalletKind.DEX
          return None

  rows=list(csv.DictReader(open('resources/source/example/koinly2025_loan_affected_rebuild/koinly_2025_transaction_history_synth.csv')))
  for i,r in enumerate(rows):
      tr=parse_th_row(r, row_index=i)
      ev=aggregate_platform_evidence([tr])
      p = tr.sending_wallet or tr.receiving_wallet
      cl=classify_platform(p, ev.get(p), _StubRegistry())
      tx=build_transaction(tr, cl)
      print(repr(tr.tag), '->', resolve_treatment(tx, TreatmentConfig()).value)
  "
  ```
  Expect `'loan'` -> `other`, `'loan repayment'` -> `loan_repayment`, `''` -> `spot_disposal` (or `other` for the deposit).
- [x] Commit: `test(crypto): add loan_affected_rebuild synthetic corpus fixture (Phase C Task 5)`

### Task 6: Scenario corpus - `koinly2025_derivatives_close/`

Files:
- `resources/source/example/koinly2025_derivatives_close/README.md` *(new)*
- `resources/source/example/koinly2025_derivatives_close/koinly_2025_capital_gains_report_synth.csv` *(new)*
- `resources/source/example/koinly2025_derivatives_close/koinly_2025_income_report_synth.csv` *(new)*
- `resources/source/example/koinly2025_derivatives_close/koinly_2025_other_gains_report_synth.csv` *(new)*
- `resources/source/example/koinly2025_derivatives_close/koinly_2025_transaction_history_synth.csv` *(new)*

- [x] Author the four CSVs with this scenario shape: TWO TH rows - (a) `Tag="Realized gain"` `crypto_withdrawal` sending 0.001 ETH from ByBit (matches the production koinly_2025.json derivatives label), (b) `Tag="Futures fee"` `crypto_exchange` sending 0.0001 ETH from ByBit (matches the same JSON). TWO OGR rows (one Profit, one Loss) matching the same dates. CG rows that the production pipeline would mark for derivatives routing. Income CSV has one synthetic cashback row. Note in README: this scenario exercises Phase B Invariant 5/6 - with `derivatives_tags` injected from the JSON, both TH rows resolve to `DERIVATIVES_CLOSE`; without injection, the `"Realized gain"` row would resolve to `REWARD_AIRDROP_LP` (precedence test).
- [x] Author the README citing: scenario name, DP-010/DP-012 derivatives Quadro 13 routing, Phase B Invariant 5 (derivatives_tags injected from JSON), Invariant 6 (precedence: `DERIVATIVES_CLOSE > REWARD_AIRDROP_LP` at the `"Realized gain"` overlap), the synthetic-data invariant, the file list, the backing test.
- [x] Verify parse + resolver: same stub-registry pattern as Task 5 (ByBit is CEX). Inject the FULL production derivatives JSON set via the production loader (not a hardcoded subset), so the corpus exercises every tag in the JSON:
  ```bash
  uv run python -c "
  import csv
  from tax_reporting.application.crypto.derivatives_dedup import _load_derivatives_labels_config
  from tax_reporting.application.crypto.treatment_resolver import TreatmentConfig, resolve_treatment
  from tax_reporting.application.crypto.transaction_factory import build_transaction
  from tax_reporting.application.crypto.wallet_kind import WalletKind, classify_platform, aggregate_platform_evidence
  from tax_reporting.infrastructure.koinly_parser import parse_th_row

  class _StubRegistry:
      def classify(self, platform):
          if platform in {'Kraken','ByBit','Wirex'}: return WalletKind.CEX
          if platform in {'Ledger Berachain (BERA)','SUI','Ledger'}: return WalletKind.DEX
          return None

  deriv_tags = _load_derivatives_labels_config('koinly', 2025)
  assert deriv_tags == frozenset({'Funding fee','Futures fee','Realized gain'}), deriv_tags
  cfg = TreatmentConfig(derivatives_tags=deriv_tags)
  rows=list(csv.DictReader(open('resources/source/example/koinly2025_derivatives_close/koinly_2025_transaction_history_synth.csv')))
  for i,r in enumerate(rows):
      tr=parse_th_row(r, row_index=i)
      ev=aggregate_platform_evidence([tr])
      p = tr.sending_wallet or tr.receiving_wallet
      cl=classify_platform(p, ev.get(p), _StubRegistry())
      tx=build_transaction(tr, cl)
      print(repr(tr.tag), '->', resolve_treatment(tx, cfg).value)
  "
  ```
  Expect both `Realized gain` and `Futures fee` rows to resolve to `derivatives_close`.
- [x] Commit: `test(crypto): add derivatives_close synthetic corpus fixture (Phase C Task 6)`

### Task 7: Corpus characterization tests

Files:
- `tests/unit/application/test_phase_c_corpus.py` *(new)*

- [x] `TestPhaseCCorpus#test_corpus_scenario`; parametrized over the six scenario names (`multi_lot_ogr`, `payment_ogr_collision`, `summer_time_drift`, `dex_cex_tx_id_absence`, `loan_affected_rebuild`, `derivatives_close`), given the corresponding `resources/source/example/koinly2025_<scenario>/` directory, expects every TH row parses via `parse_th_row`, classifies via `classify_platform` (using the shared stub registry described in Task 4 - corpus tests cannot rely on the auto-discovery path because production has no live registry binding today), builds via `build_transaction`, and resolves to a `Treatment` member (no `None`, no exception).
- [x] `TestPhaseCCorpus#test_treatment_agrees_with_legacy_intent`; parametrized over (scenario, row_index), given each TH row in each scenario, expects `resolve_treatment(tx, TreatmentConfig())` (or `TreatmentConfig(derivatives_tags=<loaded JSON>)` for the derivatives scenario) agrees with the legacy intent computed inline (see Terms "Legacy intent": import `_DEFAULT_PAYMENT_TAGS` from `payment_proceeds.py`, `_LOAN_PRINCIPAL_TAGS` from `crypto_fifo/contexts.py`, the derivatives JSON via `_load_derivatives_labels_config("koinly", 2025)`, and replicate the reward/airdrop/lp tag literals from `token_origin.py` inline because that module exposes them only as inline string literals). Assert per row: `resolver_treatment == legacy_intent` (Invariant 6).
- [x] `TestPhaseCCorpus#test_loan_borrowing_row_is_other`; given the `koinly2025_loan_affected_rebuild/` TH row with `Tag="Loan"`, expects `resolve_treatment` returns `OTHER` (Phase B Invariant 9 - the borrowing tag is NOT loan_repayment).
- [x] `TestPhaseCCorpus#test_loan_repayment_row_is_loan_repayment`; given the `koinly2025_loan_affected_rebuild/` TH row with `Tag="Loan Repayment"`, expects `LOAN_REPAYMENT`.
- [x] `TestPhaseCCorpus#test_derivatives_scenario_requires_injected_tags`; given the `koinly2025_derivatives_close/` TH rows, expects the `Tag="Realized gain"` row resolves to `REWARD_AIRDROP_LP` under the default empty `derivatives_tags`, AND to `DERIVATIVES_CLOSE` under the injected JSON set. Pins Phase B Invariant 6 precedence.
- [x] `TestPhaseCCorpus#test_dex_missing_tx_id_sets_review_flag`; given the `koinly2025_dex_cex_tx_id_absence/` Ledger DEX row with empty `TxHash`, expects `TxCorrelationKeyResolver.resolve(tx)` returns `requires_review=True`. (Phase A policy.)
- [x] `TestPhaseCCorpus#test_cex_missing_tx_id_no_review_flag`; given the same scenario's Kraken CEX row with empty `TxHash`, expects `requires_review=False`. (Phase A policy.)
- [x] `TestPhaseCCorpus#test_summer_time_drift_uses_utc_instant`; given the `koinly2025_summer_time_drift/` TH row, expects the composite correlation key's UTC instant is `2025-07-14T23:30:00Z` (not `2025-07-15`). Assert by inspecting the `TxCorrelationKey.composite` field.
- [x] `TestPhaseCCorpus#test_multi_lot_ogr_one_event_many_lots`; given the `koinly2025_multi_lot_ogr/` TH row whose legacy key `(2025-03-10, ETH, Kraken)` joins to TWO CG lots, expects the TH row's `TxCorrelationKey` is stable (one Transaction identity) regardless of the CG lot count, and the key's `tx_id` is populated from the TH `TxHash`. This pins the structural property (correlate by tx-id, not by lot count) that Phase D needs before flipping the OGR override; without it the multi-lot scenario only verifies `SPOT_DISPOSAL == SPOT_DISPOSAL`, which is trivially true and does not prove the per-Transaction grouping the RFC names as weakness #2.
- [x] `TestPhaseCCorpus#test_no_real_data_in_fixtures`; given every CSV in every scenario directory, expects no line matches the regex `(0x[0-9a-fA-F]{40,})|([0-9a-fA-F]{64})` (no real wallet addresses or tx hashes). Invariant 4 synthetic-data floor.
- [x] Run RED: `uv run pytest tests/unit/application/test_phase_c_corpus.py -q` -> fails (module missing or scenarios not yet loadable).
- [x] Run GREEN once the scenarios from Tasks 1-6 land.
- [x] Commit: `test(crypto): add Phase C corpus characterization tests (six scenarios)`

### Task 8: Shadow script - `legacy_intent.py` helper

Files:
- `docs/tmp/phase-c-shadow/legacy_intent.py` *(new; deleted in Task 11)*

- [x] Author `legacy_intent.py` exposing one function: `legacy_intent(row: TransactionHistoryRow, derivatives_tags: frozenset[str]) -> Treatment`. Implementation imports `_DEFAULT_PAYMENT_TAGS` from `tax_reporting.application.crypto.payment_proceeds` (normalize the `list[str]` to a lowercase `frozenset` once at module load), `_LOAN_PRINCIPAL_TAGS` from `tax_reporting.application.crypto_fifo.contexts`, and REPLICATES the reward/airdrop/lp tag literals from `token_origin.py` inline (those literals are not module-level constants; see Terms "Legacy intent" and Invariant 5). Applies the same precedence as Phase B Invariant 6 (`LOAN_REPAYMENT > PAYMENT > DERIVATIVES_CLOSE > REWARD_AIRDROP_LP > SPOT_DISPOSAL default > OTHER`). NO I/O, NO logging. Pure function. Module docstring cites Phase C Invariant 5 (reuse production frozensets where they exist; document the inline-replication exception for the `token_origin.py` reward/airdrop/lp literals).
- [x] Author a tiny inline smoke at the bottom of `shadow_run.py` Task 9 (NOT here); `legacy_intent.py` is exercised only via the sibling import from `shadow_run.py`. The hyphens in `docs/tmp/phase-c-shadow/` make direct module import invalid; load via `importlib.util.spec_from_file_location` from `shadow_run.py`.
- [x] Commit: `chore(crypto): add Phase C shadow legacy_intent helper (throwaway; docs/tmp/)`

### Task 9: Shadow script - `shadow_run.py` main entry

Files:
- `docs/tmp/phase-c-shadow/shadow_run.py` *(new; deleted in Task 11)*

- [x] Author `shadow_run.py` taking one positional argument `<source_dir>`. Implementation: (a) glob `<source_dir>/*transaction_history*.csv` per the production filename token (CLAUDE.md rule); if zero matches, exit non-zero with a "no TH file found in <source_dir>" hint; if more than one match, exit non-zero printing the matches and a hint to remove stale duplicates (intentional throwaway-script behavior, not a production-robust discovery); (b) parse every TH row via `parse_th_row`; (c) classify each via `aggregate_platform_evidence` + `classify_platform` (the script constructs the same stub registry documented in Task 4 because production has no live registry binding today; CEX set = `{Kraken, ByBit, Wirex}`, DEX set = `{Ledger Berachain (BERA), SUI, Ledger}`); (d) build each via `build_transaction`; (e) compute `legacy_intent` (sibling import via `importlib`) and `resolve_treatment` per row; (f) compute `TxCorrelationKeyResolver.resolve` per row; (g) write `docs/tmp/phase-c-shadow/discrepancies.csv` with the Terms columns; (h) write WARNING log per disagreement via `logging.warning` with row_index, type, tag, legacy_intent, resolver_treatment; (i) `sys.exit(1)` if any disagreement OR if CSV row count != TH row count, else `sys.exit(0)`. Module docstring cites Phase C Invariants 6, 7, 9. The script does NOT import `tax_reporting.main`; it imports only the typed-view symbols it needs.
- [x] Verify on synthetic scenario: `uv run python docs/tmp/phase-c-shadow/shadow_run.py resources/source/example/koinly2025_payment_ogr_collision` -> expect `discrepancies.csv` to have one row with `treatment_agree=yes`, exit code 0.
- [x] Verify on all six scenarios: loop the script over each scenario directory and confirm exit 0 for each. Record the per-scenario output in `docs/tmp/phase-c-shadow/RUN_SUMMARY.md` (markdown table with one row per scenario: row count, treatment_agree counts).
- [x] Commit: `chore(crypto): add Phase C shadow_run main entry (throwaway; docs/tmp/)`

### Task 10: User-initiated real-data shadow run

Files:
- `docs/tmp/phase-c-shadow/RUN_SUMMARY.md` *(output artifact; gitignored)*

- [x] Confirm with the user which personal Koinly directory to run against; the user supplies the path explicitly per run. Do NOT bake any default path into the plan or the script (the path is gitignored personal data; naming it in a tracked doc is a leak). Do NOT run without explicit user instruction.
- [x] Run: `uv run python docs/tmp/phase-c-shadow/shadow_run.py <user-supplied-path>` and capture stdout/stderr.
- [x] Record in `RUN_SUMMARY.md`: TH row count, discrepancy CSV row count, count of `treatment_agree=no` rows, list of disagreeing row indices with `(type, tag, legacy_intent, resolver_treatment, sending_wallet)` per row, count of `requires_review=True` rows (overall AND per-platform breakdown so Phase D triage can distinguish "many DEX rows missing tx-id" data-quality cases from "treatment divergence" algorithmic cases).
- [x] If any `treatment_agree=no` rows surface: do NOT attempt to fix in Phase C (production code is frozen per Invariant 1). Surface the divergences to the user as the Phase D input and continue to Task 11.
- [x] Commit: none (`docs/tmp/` is gitignored). The RUN_SUMMARY survives locally for Phase D reference.

### Task 11: Delete throwaway script and finalize

Files:
- `docs/tmp/phase-c-shadow/shadow_run.py` *(delete)*
- `docs/tmp/phase-c-shadow/legacy_intent.py` *(delete)*
- `docs/tmp/phase-c-shadow/discrepancies.csv` *(keep; gitignored)*
- `docs/tmp/phase-c-shadow/RUN_SUMMARY.md` *(keep; gitignored)*

- [x] Run: `rm docs/tmp/phase-c-shadow/shadow_run.py docs/tmp/phase-c-shadow/legacy_intent.py`.
- [x] Verify: `test ! -f docs/tmp/phase-c-shadow/shadow_run.py && test ! -f docs/tmp/phase-c-shadow/legacy_intent.py && echo GOOD || echo BAD`.
- [x] Verify: `grep -rnE 'phase-c-shadow|shadow_run|legacy_intent' src/tax_reporting/ tests/ && echo BAD || echo GOOD` (no surviving imports).
- [x] Run final suite: `uv run pytest tests/unit/application/ tests/unit/domain/ tests/end_to_end/ -q` -> GREEN.
- [x] Run count diff: `uv run pytest tests/unit/application/ tests/unit/domain/ tests/end_to_end/ --collect-only -q | tail -3`. Compare with Task 0 baseline. Expect delta equals exactly the number of new test functions added by Task 7 (record the expected delta inline in the commit message).
- [x] Run: `uv run ruff check src/tax_reporting/ tests/ && uv run ruff format --check src/tax_reporting/ tests/`.
- [x] Run: `~/.ai-playbook/scripts/check-no-em-dash.sh`.
- [x] Run: all validation commands from `## Validation Commands`. Expect every check `GOOD`.
- [x] Update the feature-notes status: change the Phase C "NEXT" line to "LANDED at <commit>; synthetic corpus + one-shot shadow run; X divergences surfaced (recorded in RUN_SUMMARY; Phase D input). Plan archived at `docs/history/plans/completed/2026-07-07-th-tx-view-phase-c.md`." Append the Phase C merge-commit SHA explicitly so Phase D can restore the throwaway script via `git show <sha>:docs/tmp/phase-c-shadow/shadow_run.py > docs/tmp/phase-c-shadow/shadow_run.py` (the file is gitignored, so this requires manual restore - intentional friction to prevent silent persistence per Invariant 3).
- [x] Move plan file: `git mv docs/history/plans/2026-07-07-th-tx-view-phase-c.md docs/history/plans/completed/`.
- [x] Commit: `chore(crypto): finalize Phase C - delete throwaway shadow script, archive plan, update feature-notes status`
