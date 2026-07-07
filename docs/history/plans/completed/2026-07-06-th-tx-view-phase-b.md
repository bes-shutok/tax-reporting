# Plan: TH-anchored Transaction view - Phase B (treatment resolver)

RFC: [docs/history/feature-notes/2026-06-20-th-anchored-transaction-state-machine.md](../feature-notes/2026-06-20-th-anchored-transaction-state-machine.md#rollout-plan-2026-07-05) (un-shelved 2026-07-05; this is Phase B of the five-phase rollout recorded there).

Phase A plan: [2026-07-05-th-tx-view-phase-a.md](completed/2026-07-05-th-tx-view-phase-a.md) (landed on master at commit `bb46bdd`).

Plan review: [r1](../reviews/2026-07-06-plan-review-th-tx-view-phase-b-r1.md) (0 Blockers + 7 Medium + 6 Low addressed in revision 2) -> [r2](../reviews/2026-07-06-plan-review-th-tx-view-phase-b-r2.md) (latest, ready: Blocker=0, Medium=0; 3 residual Low prose nits + 3 Monitor items the plan already owns).

## Terms

- **TH** - Transaction History, the Koinly report whose columns include `Date`
  (explicit UTC), `Type`, `Tag` (sometimes shown as "Label" in Koinly UI), and
  the per-side wallet/amount/currency fields. The only report with a
  transaction id (`TxHash`) and a Type/Tag.
- **Treatment** - new enum (this phase) classifying what a TH row *is* for tax
  purposes. Six values: `SPOT_DISPOSAL`, `PAYMENT`, `LOAN_REPAYMENT`,
  `DERIVATIVES_CLOSE`, `REWARD_AIRDROP_LP`, `OTHER`. Closed enumeration; no
  member is added without amending Invariant 1 and updating the matrix test.
- **TreatmentConfig** - new frozen dataclass (this phase) bundling the
  case-folded tag frozensets the resolver consults. Fields:
  `payment_tags`, `loan_repayment_tags`, `derivatives_tags`, `reward_tags`,
  `airdrop_tags`, `lp_tags`. Defaults are baked in for the five tag sets whose
  values are protocol facts (matching the existing `payment_proceeds.py`
  precedent); `derivatives_tags` defaults to empty because its authoritative
  source is the JSON at
  `docs/maintenance/tax/derivatives_labels/<provider>_<year>.json` (loaded by
  `_load_derivatives_labels_config` in `derivatives_dedup.py`; the JSON key is
  `derivatives_th_labels` but the values are matched against the TH **Tag**
  column, so the field is named `derivatives_tags` for consistency with the
  other five frozenset fields - single source of truth, never hardcoded in
  code). The production JSON for koinly 2025 is
  `["Funding fee", "Futures fee", "Realized gain"]`; note `"Realized gain"`
  also appears in `reward_tags` (mirroring `token_origin.py`), so the
  production-injected set creates a real precedence decision the resolver
  resolves to `DERIVATIVES_CLOSE` (Invariant 6).
- **TreatmentResolver** - new (this phase). A pure free function
  `resolve_treatment(transaction, config) -> Treatment`. No I/O, no logging,
  no side effects. Hangs off the Phase-A `Transaction` object.
- **Disposal signal** - a TH row is *disposal-shaped* iff its sending side is
  populated (`row.sending_currency is not None` per the Phase-A typed row).
  Disposal-shaped rows without a recognized tag default to `SPOT_DISPOSAL`;
  non-disposal rows without a recognized tag default to `OTHER`. Special tags
  override the default regardless of side.
- **Precedence** - resolver checks treatments in a fixed order
  (Invariant 6). The order encodes legal priority and disambiguates a row that
  could match two tag sets (defensive: defaults do not overlap today, but the
  resolver must still be deterministic if a user adds an overlapping custom
  tag).

## Gist & Examples

### What changes

Phase A landed a typed `Transaction` anchored on TH plus a `TxCorrelationKey`
and a platform-level `WalletKind` classifier. Nothing in the live pipeline
consumes the typed view yet (Phase A's only production caller is the
Assumptions & Methodology Kind column).

Phase B introduces two new pure-logic artifacts alongside the Phase-A types:

1. `Treatment` enum in a new `domain/treatment.py` module. Six values, closed.
2. `TreatmentConfig` + `resolve_treatment` in a new
   `application/crypto/treatment_resolver.py` module. The function takes a
   `Transaction` and a `TreatmentConfig` and returns a `Treatment`. No other
   inputs. No side effects. The full tag/label matrix is unit-tested with
   parametrized cases so every cell is covered.

The mapping encodes the existing treatment-like classifications that today
live scattered across `payment_proceeds.py` (`payment_tags` config),
`crypto_fifo/parsing.py` (`_LOAN_PRINCIPAL_TAGS`), `derivatives_dedup.py`
(`_DERIVATIVES_TH_TYPE` + injected `labels`), and `token_origin.py` (reward /
airdrop / lp / lending tag branches). Phase B consolidates them into one
table; Phase D flips each legacy branch to call the resolver per treatment.

### What does NOT change

- The live crypto pipeline (`crypto_reporting.py`, `ogr_handler.py`,
  `payment_proceeds.py`, `derivatives_dedup.py`, `loan_activity.py`,
  `fee_filter.py`, `crypto_fifo/`, `token_origin.py`) keeps its current
  per-treatment classifiers. Phase B adds the resolver alongside, not in
  place of. Per the RFC: Phase B has no behavior change.
- Phase A's `Transaction`, `TransactionHistoryRow`, `TxCorrelationKey`,
  `WalletKind`, `WalletKindResolver`, `TxCorrelationKeyResolver`,
  `build_transaction` are reused unchanged. No new field is added to them.
- No new public CLI flags, no new config keys in `config.ini`, no new Excel
  tabs, no new columns. Phase B is invisible to the user.
- The derivatives labels JSON under
  `docs/maintenance/tax/derivatives_labels/<provider>_<year>.json` keeps its
  current shape and loader; Phase B only types the place where the loaded
  frozenset gets consumed.
- No change to `docs/maintenance/crypto_rules.md`, `crypto_reporting_guidelines.md`,
  or any other Layer 2 doc. Phase B has no rule or filing-output change.

### Concrete example

Given a Phase-A `Transaction` built from a TH row whose `Tag="Card Payment"`
and `Type="exchange"` (a row that today would route through
`payment_proceeds.py`), Phase B produces:

```python
config = TreatmentConfig()  # defaults: payment_tags includes "card payment"

resolve_treatment(transaction, config)
# -> Treatment.PAYMENT
```

Given a `crypto_withdrawal` row whose `Tag="Realized gain"` (one of the three
strings in the production `koinly_2025.json` derivatives labels file), Phase B
produces:

```python
config = TreatmentConfig(
    derivatives_tags=frozenset({"Realized gain"}),
)

resolve_treatment(transaction, config)
# -> Treatment.DERIVATIVES_CLOSE
```

Note that `"Realized gain"` also appears in the default `reward_tags` set.
With an empty `derivatives_tags` (the default), the same row resolves to
`REWARD_AIRDROP_LP`; once the JSON-loaded set is injected, Invariant 6
precedence (`DERIVATIVES_CLOSE > REWARD_AIRDROP_LP`) flips the classification.
The precedence test pins this production-overlap case explicitly.

Given a `crypto_deposit` row with no special tag (a plain acquisition),
Phase B produces:

```python
config = TreatmentConfig()

resolve_treatment(transaction, config)
# -> Treatment.OTHER   # non-disposal-shaped, no recognized tag
```

### Why this chunk

The user's directive (2026-07-05, reaffirmed 2026-07-06): proactive
structural migration in digestible chunks. Phase B lands the canonical
treatment table before Phase C (synthetic corpus + one-shot shadow) and
Phase D (per-treatment flip) consume it. Keeping Phase B pure-logic lets
review focus on whether the tag/label matrix and the precedence order are
right before any output depends on them.

## Evaluation Criteria

**Quality dimensions:**

- **No behavior change (correctness floor):** the existing crypto test suite
  passes byte-identical before and after Phase B for every Excel tab. Test
  COUNT under
  `uv run pytest tests/unit/application/ tests/unit/domain/ tests/end_to_end/`
  must increase by exactly the number of new test functions Phase B adds; no
  existing test may disappear, become `xfail`, or skip.
- **Resolver purity:** `resolve_treatment` performs no I/O, emits no logs,
  mutates no global state, and raises no exception on any input that satisfies
  the Phase-A `Transaction` constructor. Verified by a property-style test
  that constructs `Transaction` fixtures across the Type/Tag grid and asserts
  the resolver returns a `Treatment` member without raising.
- **Total classification (Invariant 2):** every `Transaction` resolves to
  exactly one `Treatment` member. There is no "unclassified" return path.
  Verified by a parametrized test covering every (Type, Tag) cell listed in
  the matrix below plus explicit "unknown tag" and "empty tag" cases.
- **Tag-matrix coverage (Invariant 1):** every cell in the matrix maps to the
  treatment named by the matrix, and the test fails if any cell is changed.
  Verified by `TestTreatmentMatrix#test_matrix_cell` parametrized over the
  full grid.
- **Precedence determinism (Invariant 6):** a row whose tag matches two
  configured tag sets resolves to the higher-precedence treatment. The
  precedence order is fixed in code and asserted. Verified by
  `TestTreatmentPrecedence` parametrized over each precedence pair.
- **Case-insensitive matching (Invariant 4):** tag comparison is
  case-insensitive and whitespace-stripped, matching the existing
  `payment_proceeds.py` and `crypto_fifo/parsing.py` precedent. Verified by
  tests that pass `"Payment"`, `"PAYMENT"`, `" payment "`,
  `"Card Payment"` and assert `Treatment.PAYMENT`.
- **Config injection (Invariant 5):** `derivatives_tags` defaults to an
  empty frozenset; production callers inject the JSON-loaded set. No hardcoded
  derivatives label strings appear in the resolver module. Verified by a grep
  test (`TestTreatmentConfigDefaults#test_no_hardcoded_derivatives_tags`).
- **Disposal-shape default (Invariant 3):** a row whose sending side is
  populated resolves to `SPOT_DISPOSAL` when no tag matches; a row whose
  sending side is empty resolves to `OTHER` when no tag matches. Verified by
  `TestTreatmentDefaultBranch#test_disposal_default_is_spot` and
  `#test_nondisposal_default_is_other`.
- **Type safety:** `Treatment` is an `Enum`; `TreatmentConfig` is a
  `@dataclass(frozen=True)`; all six config fields are `frozenset[str]`.
- **Reuse, not re-implementation:** the resolver reads `transaction.row.tag`
  and `transaction.row.type` from the Phase-A typed row; it does NOT re-parse
  the raw CSV. Disposal-shape detection reuses `row.sending_currency is not
  None`, matching the typed-row contract.

**Release gates:**

- All existing crypto tests pass unchanged.
- All new Phase B unit tests pass (no skips, no `xfail`).
- `uv run ruff check src/tax_reporting/ tests/` clean.
- `~/.ai-playbook/scripts/check-no-em-dash.sh` clean on changed files.
- No public-API addition outside the two new modules (`domain/treatment.py`,
  `application/crypto/treatment_resolver.py`) and the re-exports appended to
  `application/crypto/entities.py`.
- Validation grep (see `## Validation Commands`) reports
  `GOOD: no production caller`.

## Review Scope

**Explicit must-fix**; findings on these paths are always in scope (review and
fix if valid):

**Production code (new modules):**

- `src/tax_reporting/domain/treatment.py` *(new)* - hosts the `Treatment` enum.
- `src/tax_reporting/application/crypto/treatment_resolver.py` *(new)* - hosts
  `TreatmentConfig`, `resolve_treatment`, and the
  `_DEFAULT_PAYMENT_TAGS` / `_DEFAULT_LOAN_REPAYMENT_TAGS` /
  `_DEFAULT_REWARD_TAGS` / `_DEFAULT_AIRDROP_TAGS` / `_DEFAULT_LP_TAGS`
  constants.

**Production code (touched, additive only):**

- `src/tax_reporting/application/crypto/entities.py` - re-export of `Treatment`,
  `TreatmentConfig`, and `resolve_treatment` for ergonomic single-package
  imports. No field changes to existing classes. Method-level scope: the
  re-export block only.

**Tests (new files, flat layout per existing convention):**

- `tests/unit/domain/test_treatment.py` *(new)* - covers the `Treatment` enum
  (membership, closed-ness, value uniqueness).
- `tests/unit/application/test_treatment_resolver.py` *(new)* - covers
  `TreatmentConfig` defaults, `resolve_treatment` matrix, precedence,
  case-insensitivity, disposal-default branch, purity/totality.

**Plan-related extension**; Phase B is pure plumbing. Treat a finding as in
scope when it is causally related to introducing the new types: e.g. a name
collision with an existing `Treatment` symbol elsewhere in the codebase, an
import cycle the new modules create, a normalization rule
(case-insensitive tag matching, empty-tag handling, disposal-side detection)
the new resolver violates, or a missing matrix cell the existing
per-treatment classifiers already handle. Drop anything else as out of scope
with a one-line reason.

**Out of scope; reject unless plan-related:**

- `src/tax_reporting/application/crypto_reporting.py`; Phase B adds no callers
  in this file. Phase D will edit it.
- `src/tax_reporting/application/crypto/ogr_handler.py`,
  `payment_proceeds.py`, `derivatives_dedup.py`, `loan_activity.py`,
  `fee_filter.py`, `token_origin.py`, `crypto_fifo/`; untouched in Phase B.
  Findings on these are out of scope unless the new types introduce a contract
  violation they already depend on (none expected).
- `docs/maintenance/crypto_rules.md`, `crypto_reporting_guidelines.md`,
  `crypto_implementation_guidelines.md`; Phase B has no rule or filing-output
  change. Phase D (treatment flip) will edit them.
- Replacing the existing per-treatment classifiers in `payment_proceeds.py` /
  `crypto_fifo/parsing.py` / `derivatives_dedup.py` / `token_origin.py` with
  calls to the new resolver; that is Phase D per-treatment flip work.

## Design Invariants (CR Guard)

1. **`Treatment` is a closed enum; values are stable references.** The six
   values (`SPOT_DISPOSAL`, `PAYMENT`, `LOAN_REPAYMENT`, `DERIVATIVES_CLOSE`,
   `REWARD_AIRDROP_LP`, `OTHER`) are stable IDs. Adding a value requires
   amending this invariant AND updating the matrix test. CR guard: reject
   string-typed treatment return values, sentinel integers, or `Optional`
   returns. Rationale: CRG-style stable references (matches the existing
   CRG-/PT-C-/DP- ID discipline).

2. **Resolver is total.** `resolve_treatment(transaction, config)` returns a
   `Treatment` member for every `Transaction` whose underlying row satisfies
   the Phase-A constructor. No `None`, no exception on real Koinly data, no
   silent fall-through to a non-enum value. The `OTHER` value exists
   specifically so unmatched rows have a loud, observable landing. CR guard:
   reject any code path that returns `None`, raises on an unmatched tag, or
   introduces a third return type.

3. **Default branch keys off disposal shape.** A row whose
   `row.sending_currency is not None` resolves to `SPOT_DISPOSAL` when no
   configured tag matches; a row whose sending side is empty resolves to
   `OTHER`. Special tags (payment/loan_repayment/derivatives/reward/airdrop/lp)
   override regardless of side. CR guard: reject a default branch that uses
   `Type` alone, or that uses `receiving_currency` for the disposal signal,
   or that returns `OTHER` for a populated sending-side row with no special
   tag. Rationale: `Type` values like `crypto_withdrawal` are ambiguous
   (transfer vs disposal); the sending-side signal is the row-shape
   invariant.

4. **Tag matching is case-insensitive and whitespace-stripped.** Both the
   row's `tag` value and every member of every `TreatmentConfig` frozenset
   are normalized by `value.strip().lower()` before comparison. CR guard:
   reject `==` comparisons against raw user input, or `.lower()` applied to
   only one side. Rationale: matches the existing `payment_proceeds.py`
   (line 317) and `crypto_fifo/parsing.py` (line 71) precedent; diverging
   patterns silently drop matches (CLAUDE.md "Sibling aggregators ... must
   use byte-identical patterns or a shared helper").

5. **`derivatives_tags` is injected, never hardcoded.** The
   `TreatmentConfig.derivatives_tags` field defaults to an empty
   frozenset; production callers inject the JSON-loaded set. The resolver
   module MUST NOT contain any string literal that is a known derivatives
   tag from the production JSON (`"Funding fee"`, `"Futures fee"`,
   `"Realized gain"`). CR guard: reject any literal in
   `treatment_resolver.py` that matches a JSON value, OR any move of the
   labels JSON contents into code. Rationale: CLAUDE.md "Never introduce a
   hardcoded value ... without first flagging it" + Family D (single source
   of truth - the JSON is authoritative).

6. **Precedence is fixed in code and asserted.** When a tag matches two
   configured tag sets, the resolver applies this precedence order
   (highest first): `LOAN_REPAYMENT` > `PAYMENT` > `DERIVATIVES_CLOSE` >
   `REWARD_AIRDROP_LP` > `SPOT_DISPOSAL` (default for disposal-shaped) >
   `OTHER`. CR guard: reject a resolver that consults tag sets in any order
   not equivalent to the above, or that picks "first match" without
   documenting which set is checked first. Rationale: legal priority
   (DP-001 non-taxable trumps DP-014 payment correction; both trump the
   default spot treatment). Defaults do not overlap among the five
   non-derivatives sets, but `"Realized gain"` (in the production JSON and
   in `_DEFAULT_REWARD_TAGS`) overlaps once `derivatives_tags` is injected;
   the precedence pins that production case to `DERIVATIVES_CLOSE`.

7. **No production caller in Phase B.** Mirrors Phase A Invariant 1 (original
   form). The new `Treatment`, `TreatmentConfig`, and `resolve_treatment`
   symbols appear ONLY in the new modules and in `entities.py` re-exports.
   CR guard: reject any change that wires the new symbols into
   `crypto_reporting.py`, `ogr_handler.py`, `payment_proceeds.py`,
   `derivatives_dedup.py`, `loan_activity.py`, `fee_filter.py`,
   `token_origin.py`, or `crypto_fifo/`. Phase D lifts this invariant
   per-treatment.

8. **`TreatmentConfig` defaults match existing constants.** `payment_tags`
   defaults to `{"payment", "card payment"}` (matches
   `_DEFAULT_PAYMENT_TAGS` in `payment_proceeds.py`);
   `loan_repayment_tags` defaults to `{"loan repayment"}` (matches
   `_LOAN_PRINCIPAL_TAGS` in `crypto_fifo/contexts.py` minus `"loan"`, which
   is the borrowing side, not a disposal); `reward_tags` defaults to
   `{"reward", "cashback", "realized gain"}` (matches the reward-tag tuple
   in `token_origin.py`); `airdrop_tags` defaults to `{"airdrop"}` (matches
   the airdrop branch in `token_origin.py`); `lp_tags` defaults to
   `{"liquidity in", "liquidity out"}` (matches the LP branches in
   `token_origin.py`). CR guard: reject defaults that drift from these
   constants without an amendment to this invariant naming the reason.

9. **`loan` (the borrowing tag) does NOT resolve to `LOAN_REPAYMENT`.** Tag
   `"loan"` (without `"repayment"`) is the borrowing-side principal creation;
   the RFC `LOAN_REPAYMENT` treatment covers only the repayment disposal. A
   row tagged `"loan"` resolves to `OTHER` (acquisition or transfer of
   collateral), NOT `LOAN_REPAYMENT`. CR guard: reject a config default that
   includes `"loan"` in `loan_repayment_tags`, or a resolver branch that
   treats `"loan"` as repayment. Rationale: DP-001 non-taxable scope is the
   repayment action (CIRS art. 10(20)); the borrowing action is a
   collateral deposit, not a realization event.

10. **No backward-compat shim.** `entities.py` re-exports the new symbols for
    ergonomic imports, but no legacy `dict[str, str]` consumer is migrated
    or shimmed. CR guard: reject `cast()` / adapter shims that paper over
    the typed-vs-dict boundary inside the new modules. (Same form as Phase A
    Invariant 10.)

## Validation Commands

```bash
# Phase B floor: no behavior change in the existing crypto pipeline
# Capture baseline test count BEFORE Phase B work begins (Task 0);
# the post-Phase-B count must equal baseline + (new test functions added).
uv run pytest tests/unit/application/ tests/unit/domain/ tests/end_to_end/ \
  --collect-only -q | tail -3

# New types and resolver are fully covered (no skips)
uv run pytest \
  tests/unit/domain/test_treatment.py \
  tests/unit/application/test_treatment_resolver.py -q

# Re-exports present
uv run pytest tests/unit/application/test_crypto_entities.py -q

# Lint and format
uv run ruff check src/tax_reporting/ tests/
uv run ruff format --check src/tax_reporting/ tests/

# No em dash in changed files
~/.ai-playbook/scripts/check-no-em-dash.sh

# Confirm the only production caller of the new types is entities.py (re-export)
# and the new modules themselves. Use a SYMBOL-name grep (production code uses
# relative imports, so module-path patterns miss).
grep -rnE '\b(Treatment|TreatmentConfig|resolve_treatment)\b' \
  src/tax_reporting/application/crypto_reporting.py \
  src/tax_reporting/application/crypto/ogr_handler.py \
  src/tax_reporting/application/crypto/payment_proceeds.py \
  src/tax_reporting/application/crypto/derivatives_dedup.py \
  src/tax_reporting/application/crypto/loan_activity.py \
  src/tax_reporting/application/crypto/fee_filter.py \
  src/tax_reporting/application/token_origin.py \
  src/tax_reporting/application/crypto_fifo/ \
  | grep -vE '^\s*#' \
  && echo "BAD: forbidden production caller wired" || echo "GOOD: no forbidden production caller"

# Confirm no hardcoded derivatives tag literals in the resolver module
# (Invariant 5). Literal-list grep over the production JSON contents is the
# authoritative check; a generated regex would be theatre. Add new labels
# here as the JSON grows.
grep -nE '"(Funding fee|Futures fee|Realized gain)"' \
  src/tax_reporting/application/crypto/treatment_resolver.py \
  && echo "BAD: hardcoded derivatives tag literal found" \
  || echo "GOOD: no hardcoded derivatives tag literals"
```

The first grep is contract-removal-style: Phase B Invariant 7 forbids
production callers, so any non-comment match in the listed files is a
violation. The second grep is a sanity check; if it flags a false positive
(e.g. a docstring example), the implementer records the resolution in the
task-implement log.

## Documentation Impact Assessment

Phase B adds internal types only. No user-visible Excel change, no config
key, no CLI flag.

- `docs/maintenance/crypto_rules.md` - no change. Phase D will edit it.
- `docs/maintenance/crypto_reporting_guidelines.md` - no change.
- `docs/maintenance/crypto_implementation_guidelines.md` - no change.
- `README.md` - no change.

Phase B adds a brief mention of the `Treatment` enum and `TreatmentConfig`
shape to the docstring of each new module; that is the canonical reference
until Phase D wires them into the live pipeline.

## Monitor

- **`Treatment` enum may grow.** Phase D wiring or future tax-law changes
  may need new treatments (e.g. `SALARY` for crypto-denominated salary, or
  `GIFT` for crypto gifts). Adding a value requires amending Invariant 1
  and extending the matrix test. Owner: Phase D plan must list any new
  value explicitly and update this plan's Monitor section to retire the
  gap.
- **Precedence order is asserted, not derived.** The order in Invariant 6
  reflects current legal priority but is not auto-checked against the
  decision_points TOML. If a future DP adds a treatment whose priority
  falls between two existing ones, the precedence test must be updated.
  Owner: Phase D plan.
- **Tag set drift.** The default tag sets in Invariant 8 mirror existing
  constants; if `payment_proceeds.py` or `token_origin.py` adds a tag,
  `TreatmentConfig` defaults should be updated in the same change. Between
  Phase B and Phase D, any change to `_DEFAULT_PAYMENT_TAGS` in
  `payment_proceeds.py`, `_LOAN_PRINCIPAL_TAGS` in `crypto_fifo/contexts.py`,
  or the reward / airdrop / lp tag tuples in `token_origin.py` MUST be
  mirrored in `TreatmentConfig` defaults in the same commit. Phase B
  includes no automated guard for this; the Phase D plan owns the first
  consistency check. Owner: Phase D plan (or any refactor touching those
  files).
- **`"Realized gain"` is a deliberate overlap point.** The string
  `"Realized gain"` (and its case variants) appears in BOTH the koinly_2025
  derivatives labels JSON AND in `_DEFAULT_REWARD_TAGS` (mirroring
  `token_origin.py`). With the JSON injected into `derivatives_tags`,
  Invariant 6 precedence routes the row to `DERIVATIVES_CLOSE`; without it,
  the row resolves to `REWARD_AIRDROP_LP`. Phase D wiring MUST inject the
  JSON set before flipping reward classification to the resolver, otherwise
  `"Realized gain"` reward rows silently switch treatment. Owner: Phase D
  plan.
- **Resolver does not classify rewards from the Income CSV.** Crypto reward
  income today is parsed from the Koinly Income CSV (`_parse_income_file`
  in `crypto_reporting.py`), not from TH. The `REWARD_AIRDROP_LP` treatment
  classifies *TH rows whose Tag is reward/airdrop/lp*, which is a different
  signal from the income CSV's asset-based classification. The two
  classifications must not be conflated in Phase D wiring. Owner: Phase D
  plan.
- **No production caller in Phase B (Invariant 7).** The new types ship
  without exercise beyond unit tests. Phase C's one-shot shadow script is
  the first time the resolver sees real data; that script lives under
  `docs/tmp/` and is deleted after verification per the RFC. Owner:
  Phase C plan.

### Task 0: Baseline test count (before any code change)

Files:
- (no file changes; baseline-capture only)

- [x] Run: `uv run pytest tests/unit/application/ tests/unit/domain/ tests/end_to_end/ --collect-only -q | tail -3` and record the test count. Save to `docs/tmp/phase-b-baseline-count.txt`. **Expected baseline: 1438 tests collected (per Phase A Task 9).** Captured: 1438 tests collected.
- [x] Run: `git status` to confirm a clean working tree (only the plan file and the scratch baseline file should be new). Halt and ask the user if unexpected changes appear. Confirmed: only the plan file appears untracked; baseline file under gitignored `docs/tmp/`.
- [x] Commit: none. Baseline is recorded for the Task 4 count-diff check.

### Task 1: `Treatment` enum in a new domain module

Files:
- `src/tax_reporting/domain/treatment.py` *(new)*.
- `tests/unit/domain/test_treatment.py` *(new)*.

- [x] `TestTreatment#test_six_members_exactly`; given the `Treatment` enum class, expects `set(Treatment) == {SPOT_DISPOSAL, PAYMENT, LOAN_REPAYMENT, DERIVATIVES_CLOSE, REWARD_AIRDROP_LP, OTHER}`. (Invariant 1; closed enum.)
- [x] `TestTreatment#test_member_values_are_unique_stable_strings`; given each member's `.value`, expects unique snake-case strings (`"spot_disposal"`, `"payment"`, `"loan_repayment"`, `"derivatives_close"`, `"reward_airdrop_lp"`, `"other"`). (Invariant 1; stable references; matches `WalletKind.CEX = "cex"` snake-case convention.)
- [x] `TestTreatment#test_enum_lookup_by_value_round_trip`; given `Treatment("payment")`, expects `Treatment.PAYMENT` and that `Treatment.PAYMENT.value == "payment"`.
- [x] `TestTreatment#test_unknown_value_raises_value_error`; given `Treatment("nonsense")`, expects `ValueError`. (Invariant 1.)
- [x] `TestTreatment#test_no_optional_no_sentinel_members`; given the enum source, expects no `NONE`/`UNKNOWN`/`UNCLASSIFIED` member collides with `OTHER`'s role. Specifically assert there is no member named `UNCLASSIFIED` or `NONE`.
- [x] Run RED: `uv run pytest tests/unit/domain/test_treatment.py -q` -> fails (module missing).
- [x] Write `domain/treatment.py` containing `class Treatment(Enum)` with the six members above. Module docstring cites this plan, the RFC, and the DP/PT-C IDs each non-OTHER value maps to (DP-014 PAYMENT, DP-001 LOAN_REPAYMENT, DP-010/DP-012 DERIVATIVES_CLOSE, DP-005/PT-C-005 REWARD_AIRDROP_LP, art. 10(1)(k) SPOT_DISPOSAL). The docstring explicitly notes `OTHER` covers non-disposal rows (acquisitions, transfers, loan-creation) and any unrecognized tag.
- [x] Run GREEN.
- [x] Commit: `feat(crypto): add Treatment enum (six values; closed) for Phase B state machine` (commit `2400cd5`)

### Task 2: `TreatmentConfig` with default tag sets

Files:
- `src/tax_reporting/application/crypto/treatment_resolver.py` *(new)* - first
  addition: `TreatmentConfig` only (resolver comes in Task 3).
- `tests/unit/application/test_treatment_resolver.py` *(new)* - first
  addition: `TestTreatmentConfig` only.

- [x] `TestTreatmentConfigDefaults#test_payment_tags_match_payment_proceeds_precedent`; given `TreatmentConfig()`, expects `payment_tags == frozenset({"payment", "card payment"})`. (Invariant 8; matches `_DEFAULT_PAYMENT_TAGS` in `payment_proceeds.py`.)
- [x] `TestTreatmentConfigDefaults#test_loan_repayment_tags_exclude_borrow_side`; given `TreatmentConfig()`, expects `loan_repayment_tags == frozenset({"loan repayment"})` AND `"loan" not in loan_repayment_tags`. (Invariant 9.)
- [x] `TestTreatmentConfigDefaults#test_derivatives_tags_default_empty`; given `TreatmentConfig()`, expects `derivatives_tags == frozenset()`. (Invariant 5.)
- [x] `TestTreatmentConfigDefaults#test_reward_tags_match_token_origin_precedent`; given `TreatmentConfig()`, expects `reward_tags == frozenset({"reward", "cashback", "realized gain"})`. (Invariant 8; matches the reward-tag tuple in `token_origin.py`.)
- [x] `TestTreatmentConfigDefaults#test_airdrop_tags_match_token_origin_precedent`; given `TreatmentConfig()`, expects `airdrop_tags == frozenset({"airdrop"})`. (Invariant 8.)
- [x] `TestTreatmentConfigDefaults#test_lp_tags_match_token_origin_precedent`; given `TreatmentConfig()`, expects `lp_tags == frozenset({"liquidity in", "liquidity out"})`. (Invariant 8.)
- [x] `TestTreatmentConfig#test_frozen`; given a constructed `TreatmentConfig`, expects assignment to raise `FrozenInstanceError`. (Family D: immutable config.)
- [x] `TestTreatmentConfig#test_field_set_exactly_six`; given the dataclass fields, expects exactly `{payment_tags, loan_repayment_tags, derivatives_tags, reward_tags, airdrop_tags, lp_tags}`.
- [x] `TestTreatmentConfig#test_accepts_user_supplied_derivatives_tags`; given `TreatmentConfig(derivatives_tags=frozenset({"Realized gain"}))`, expects the field set as-is. (Invariant 5.)
- [x] `TestTreatmentConfig#test_list_input_coerced_to_frozenset`; given `TreatmentConfig(payment_tags=["payment", "card payment"])`, expects `isinstance(config.payment_tags, frozenset)` AND `config.payment_tags == frozenset({"payment", "card payment"})`. (Post-`__post_init__` coercion; the constructor MUST NOT raise - it coerces. Rationale: matches the "accept and normalize" pattern of `payment_proceeds.py` and lets a careless caller pass a list without breaking.)
- [x] Run RED.
- [x] Write the top of `treatment_resolver.py`: imports; module docstring (cites this plan and the RFC); five `_DEFAULT_*_TAGS` module-level frozenset constants with comments naming the existing precedent they mirror; `@dataclass(frozen=True) class TreatmentConfig` with the six `frozenset[str]` fields and the documented defaults. Use `field(default_factory=...)` because the dataclass machinery rejects shared default objects for collection-typed fields (mutable-default rule); `frozen=True` is unrelated to this requirement. Add `__post_init__` that coerces each field via `object.__setattr__(self, "<field>", frozenset(value))` so list inputs are accepted and normalized (Invariant: coercion, not rejection).
- [x] Run GREEN.
- [x] Commit: `feat(crypto): add TreatmentConfig (frozen; five default tag sets + injected derivatives labels)` (commit `2b19cf4`)

### Task 3: `resolve_treatment` matrix (parametrized over the full grid)

Files:
- `src/tax_reporting/application/crypto/treatment_resolver.py` - extend with
  `resolve_treatment`.
- `tests/unit/application/test_treatment_resolver.py` - extend with
  `TestTreatmentMatrix`, `TestTreatmentDefaultBranch`,
  `TestTreatmentCaseInsensitive`, `TestTreatmentPrecedence`,
  `TestTreatmentPurity`.

- [x] `TestTreatmentMatrix#test_matrix_cell`; parametrized over the table
  below, given a synthetic `Transaction` whose `row.tag` and
  `row.sending_currency` are set per the case, expects
  `resolve_treatment(tx, TreatmentConfig())` returns the named `Treatment`.
  Cells (tag is shown lower-case; resolver must also accept mixed case per
  Task 3 case-insensitivity tests):
  | sending_currency set? | type | tag | expected |
  |---|---|---|---|
  | yes | `exchange` | `Payment` | `PAYMENT` |
  | yes | `exchange` | `Card Payment` | `PAYMENT` |
  | yes | `exchange` | `loan repayment` | `LOAN_REPAYMENT` |
  | no  | `exchange` | `loan repayment` | `LOAN_REPAYMENT` (tag overrides side) |
  | yes | `crypto_withdrawal` | (empty) | `SPOT_DISPOSAL` |
  | yes | `exchange` | `reward` | `REWARD_AIRDROP_LP` |
  | yes | `crypto_deposit` | `airdrop` | `REWARD_AIRDROP_LP` |
  | yes | `crypto_withdrawal` | `liquidity out` | `REWARD_AIRDROP_LP` |
  | no  | `crypto_deposit` | `liquidity in` | `REWARD_AIRDROP_LP` |
  | yes | `crypto_withdrawal` | `cashback` | `REWARD_AIRDROP_LP` |
  | yes | `crypto_withdrawal` | `realized gain` | `REWARD_AIRDROP_LP` |
- [x] `TestTreatmentMatrix#test_derivatives_close_requires_injected_tag`; given a `Transaction` whose `row.tag="Realized gain"` and `row.sending_currency` is set, AND a `TreatmentConfig(derivatives_tags=frozenset({"Realized gain"}))`, expects `DERIVATIVES_CLOSE`. With the default empty `derivatives_tags`, the same row resolves to `REWARD_AIRDROP_LP` (because `"realized gain"` is in `reward_tags`); the precedence test below pins that flip. (Invariant 5.)
- [x] `TestTreatmentMatrix#test_derivatives_close_tag_case_insensitive`; given a config with `derivatives_tags=frozenset({"realized gain"})` (lower-case) and a row tag `"Realized Gain"`, expects `DERIVATIVES_CLOSE`. (Invariant 4.)
- [x] `TestTreatmentDefaultBranch#test_disposal_default_is_spot`; given a `Transaction` with `row.sending_currency="ETH"`, `row.type="exchange"`, `row.tag=""`, expects `SPOT_DISPOSAL`. (Invariant 3.)
- [x] `TestTreatmentDefaultBranch#test_nondisposal_default_is_other`; given a `Transaction` with `row.sending_currency=None`, `row.receiving_currency="ETH"`, `row.type="crypto_deposit"`, `row.tag=""`, expects `OTHER`. (Invariant 3.)
- [x] `TestTreatmentDefaultBranch#test_unknown_tag_on_disposal_defaults_to_spot`; given a `Transaction` with `row.sending_currency="ETH"` and `row.tag="something unknown"`, expects `SPOT_DISPOSAL`. (Invariant 3: unknown tag does not change the disposal default.)
- [x] `TestTreatmentDefaultBranch#test_unknown_tag_on_nondisposal_defaults_to_other`; given a `Transaction` with `row.sending_currency=None`, `row.receiving_currency="ETH"` and `row.tag="something unknown"`, expects `OTHER`.
- [x] `TestTreatmentDefaultBranch#test_loan_borrowing_tag_falls_through_to_disposal_default`; given a `Transaction` with `row.sending_currency="WBTC"`, `row.tag="loan"` (the borrowing-side principal tag, NOT repayment), expects `SPOT_DISPOSAL`. (Invariant 9: `"loan"` is intentionally absent from `loan_repayment_tags`, so it does NOT match `LOAN_REPAYMENT`; the populated sending side then triggers the `SPOT_DISPOSAL` default. This is the loud signal that the borrowing tag is not classified as a repayment.)
- [x] `TestTreatmentCaseInsensitive#test_payment_tag_case_variants`; parametrized over `"Payment"`, `"PAYMENT"`, `" payment "`, `"PaYmEnT"`, given each as `row.tag`, expects `Treatment.PAYMENT`. (Invariant 4.)
- [x] `TestTreatmentCaseInsensitive#test_reward_tag_case_variants`; parametrized over `"Reward"`, `"REWARD"`, `" reward "`, given each as `row.tag` with a populated sending side, expects `Treatment.REWARD_AIRDROP_LP`.
- [x] `TestTreatmentCaseInsensitive#test_config_tag_case_insensitive_match`; given a `TreatmentConfig(payment_tags=frozenset({"PaYmEnT"}))` (mixed case in the CONFIG, not just the row), and a row tag `"payment"`, expects `Treatment.PAYMENT`. (Invariant 4 bidirectional: both sides normalized.)
- [x] `TestTreatmentPrecedence#test_loan_repayment_trumps_payment`; given a `TreatmentConfig` where `payment_tags={"payment"}` AND `loan_repayment_tags={"loan repayment"}`, and a row whose tag matches BOTH (e.g. set `payment_tags={"loan repayment"}` artificially), expects `LOAN_REPAYMENT`. (Invariant 6; defensive.)
- [x] `TestTreatmentPrecedence#test_payment_trumps_derivatives_close`; given a `TreatmentConfig` where `derivatives_tags={"payment"}` AND `payment_tags={"payment"}`, and a row tag `"payment"`, expects `PAYMENT`. (Invariant 6.)
- [x] `TestTreatmentPrecedence#test_derivatives_close_trumps_reward`; given a `TreatmentConfig` where `derivatives_tags={"reward"}` AND `reward_tags={"reward"}`, and a row tag `"reward"`, expects `DERIVATIVES_CLOSE`. (Invariant 6.)
- [x] `TestTreatmentPrecedence#test_realized_gain_label_trumps_reward_tag`; given a `TreatmentConfig` with default `reward_tags` (which includes `"realized gain"`) AND `derivatives_tags=frozenset({"Realized gain"})` (the production koinly_2025.json value), and a row with `tag="Realized gain"` and populated sending side, expects `DERIVATIVES_CLOSE`. (Invariant 6 at the production-overlap point; without this test, a Phase D caller may be surprised that flipping the resolver in changes reward classification for `"Realized gain"` rows.)
- [x] `TestTreatmentPrecedence#test_reward_trumps_spot_default`; given a row tag `"reward"` with sending side populated, expects `REWARD_AIRDROP_LP` (not the spot default). (Invariant 6; covered by matrix but stated explicitly.)
- [x] `TestTreatmentPurity#test_no_io_no_logging`; given a `Transaction` fixture, replace `sys.stdout` and `sys.stderr` with `io.StringIO()` instances, install a `logging.NullHandler` (or capture via `caplog`), then call `resolve_treatment(tx, TreatmentConfig())`; expects `stdout.getvalue() == ""`, `stderr.getvalue() == ""`, and `caplog.records == []` post-call. (Invariant: pure function.)
- [x] `TestTreatmentPurity#test_no_mutation_of_inputs`; given a `Transaction` and a `TreatmentConfig`, snapshot both before the call (use `dataclasses.asdict` / `repr`), call `resolve_treatment`, and assert the snapshots are byte-equal post-call. (Family C: no silent mutation.)
- [x] `TestTreatmentPurity#test_returns_enum_member_for_every_grid_cell`; given the parametrized grid from `TestTreatmentMatrix#test_matrix_cell` plus six "weird" cells (empty tag with disposal side; empty tag with no disposal side; whitespace-only tag `"   "` with disposal side; whitespace-only tag `"   "` with no disposal side; tag with control characters; tag with non-ASCII), expects each call returns a `Treatment` member (no `None`, no exception). (Invariant 2: total; whitespace-only collapses to the default branch per Invariant 4.)
- [x] `TestTreatmentPurity#test_returns_treatment_member_not_value`; given any call, expects `isinstance(result, Treatment)`. (Invariant 1.)
- [x] Run RED.
- [x] Write `resolve_treatment(transaction: Transaction, config: TreatmentConfig) -> Treatment` in `treatment_resolver.py`. Implementation: define `_normalize_tag(value: str | None) -> str` at module level as the SOLE normalization point (`value.strip().lower()` if value else `""`); apply it to both `transaction.row.tag` and every member of every config frozenset via a small helper that builds a normalized frozenset per field on each call (or memoize on `TreatmentConfig` if profiling warrants - Phase B does not memoize). Consult treatments in the Invariant 6 precedence order; default branch keys off `transaction.row.sending_currency is not None` -> `SPOT_DISPOSAL` else `OTHER`. No I/O, no logging, no mutation. Docstring cites Invariants 2, 3, 4, 5, 6 and includes the precedence list verbatim. CLAUDE.md "byte-identical patterns or a shared helper" - the helper IS the single normalization point; do not inline `.strip().lower()` at multiple call sites.
- [x] Run GREEN.
- [x] Commit: `feat(crypto): add resolve_treatment (total; tag matrix + precedence; pure logic)`

### Task 4: Re-exports and end-to-end smoke (Phase A -> Phase B chain)

Files:
- `src/tax_reporting/application/crypto/entities.py` - re-exports.
- `tests/unit/application/test_crypto_entities.py` - append re-export
  assertions.
- `tests/unit/application/test_crypto_phase_b_smoke.py` *(new)*.

- [x] `TestCryptoPhaseBSmoke#test_full_chain_payment_row`; given a synthetic TH row dict with `Tag="Payment"`, `Type="exchange"`, and a populated sending side, `row_index=7`, and a `WalletClassification` fixture built as `WalletClassification(kind=WalletKind.CEX, confidence=1.0, reason="fixture", source="registry")` (literal construction - no registry or evidence wiring needed), expects `parse_th_row -> build_transaction -> resolve_treatment(tx, TreatmentConfig())` returns `Treatment.PAYMENT` AND `tx.row.row_index == 7`. (Phase A + Phase B chain; Monitor 1 in Phase A plan.)
- [x] `TestCryptoPhaseBSmoke#test_full_chain_derivatives_close_with_injected_tags`; given a synthetic TH row dict with `Tag="Realized gain"`, `Type="crypto_withdrawal"`, populated sending side, and a `TreatmentConfig(derivatives_tags=frozenset({"Realized gain"}))` (the production koinly_2025.json value), expects `resolve_treatment(...)` returns `DERIVATIVES_CLOSE`. Uses the same literal `WalletClassification` fixture pattern as the payment test.
- [x] `TestCryptoPhaseBSmoke#test_full_chain_other_for_plain_deposit`; given a synthetic TH row dict with `Type="crypto_deposit"`, no sending side, no tag, expects `resolve_treatment(...)` returns `OTHER`.
- [x] `TestCryptoPhaseBSmoke#test_full_chain_loan_repayment_trumps_disposal_side`; given a TH row dict with `Tag="Loan Repayment"` AND a populated sending side, expects `LOAN_REPAYMENT` (tag overrides the disposal default).
- [x] `TestCryptoEntitiesReExports#test_treatment_re_exported`; given `from tax_reporting.application.crypto.entities import Treatment`, expects the import succeeds and refers to `tax_reporting.domain.treatment.Treatment`.
- [x] `TestCryptoEntitiesReExports#test_treatment_config_re_exported`; same for `TreatmentConfig`.
- [x] `TestCryptoEntitiesReExports#test_resolve_treatment_re_exported`; same for `resolve_treatment`.
- [x] Append the three new imports (`Treatment`, `TreatmentConfig`, `resolve_treatment`) to the existing re-export block in `entities.py` with `# noqa: F401` per the existing convention (Phase A uses the same pattern at lines 28 and 30). Do NOT introduce `__all__` in this file in Phase B. Do NOT run `ruff check --fix` on `entities.py` (F401 will strip the re-exports).
- [x] Run new tests: `uv run pytest tests/unit/application/test_crypto_phase_b_smoke.py tests/unit/application/test_crypto_entities.py -q` -> GREEN.
- [x] Run characterization suite: `uv run pytest tests/unit/application/ tests/unit/domain/ tests/end_to_end/ -q` -> GREEN.
- [x] Run count diff: `uv run pytest tests/unit/application/ tests/unit/domain/ tests/end_to_end/ --collect-only -q | tail -3`. Compare with the Task 0 baseline. Expect delta equals exactly the number of new test functions added by Tasks 1-4 (record the expected delta inline in the commit message).
- [x] Run: `uv run ruff check src/tax_reporting/ tests/ && uv run ruff format --check src/tax_reporting/ tests/`. Fix any new errors Phase B introduces (do NOT fix pre-existing errors outside Phase B's touched files).
- [x] Run: `~/.ai-playbook/scripts/check-no-em-dash.sh`.
- [x] Run: validation grep from `## Validation Commands` -> expects `GOOD: no forbidden production caller` and `GOOD: no hardcoded label literals`.
- [x] Commit: `feat(crypto): re-export Phase B symbols and add end-to-end smoke (Phase A -> resolve_treatment)`
