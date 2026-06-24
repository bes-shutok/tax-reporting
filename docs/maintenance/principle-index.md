# Principle Index: Family to Lessons Map

O(1) family lookup for the `generalize` skill's `map` mode. The eight root-cause
families (A to H) are defined authoritatively in `coding_guidelines.md` #18 through #25
(umbrella at #17). When mapping a new incident, read the family's `Lesson #N` list here
first, then scan those lessons for the closest shape before opening a new entry.

- Audit date: 2026-06-21.
- Corpus: `docs/maintenance/development_lessons.md`, 142 uniquely-numbered lessons
  (Task 4 of the principle-generalization-system plan resolved the #15/#16/#17 collisions;
  the `uniq -d` heading gate is empty).
- Each non-excluded lesson is assigned to exactly one family below. The union of the eight
  family lists plus the excluded set equals the full set {1..142} (verified by the
  accounting check at the end of each family section and in `## Precision gate`).

The catalog's illustrative anchors (`coding_guidelines.md` #18-#25) are a small witness
subset; this index is the complete per-repo map.

---

## Excluded lessons

Tool-quirk, pure-style, pure-process, and domain-specific lessons whose value is the local
fact or the one-off mechanic, not a transferable root-cause family. They carry no family
line and are not counted in the eight families. (A lesson that looks like a tool/domain
rule but whose load-bearing mechanism is a root-cause family is MAPPED, not excluded; see
for example #29 and #122, both assigned to Family H.)

- Lesson #2: pure style (type-annotation conventions).
- Lesson #3: pure style (f-string line formatting).
- Lesson #4: API/design convention (param names, required-vs-optional) -- style, not a
  root-cause family.
- Lesson #8: pure style (specific generic element types).
- Lesson #10: process hygiene (small incremental changes, remove temp scripts).
- Lesson #11: error-message style convention (row numbers, `from e`, parameterised
  logging); codified in CLAUDE.md.
- Lesson #13: test mechanics (use `tmp_path`, never `Path(__file__).parent.parent`).
- Lesson #14: design discipline (YAGNI; remove always-same params).
- Lesson #15: tool-quirk (openpyxl stores formulas as strings; auto-width mechanics).
- Lesson #17: test mechanics (CSV column counting); pointer to `python_guidelines.md` #1.
- Lesson #18: process rule (review-agent false positives); pointer to
  `agent_workflow_guidelines.md` #2.
- Lesson #20: language mechanics (frozen dataclass `__post_init__` / `object.__setattr__`).
- Lesson #24: domain-specific (consult PT crypto `decision_points/` before tax assumptions).
- Lesson #34: tool-quirk (macOS `sed` lacks `\b`; use `perl -i -pe`).
- Lesson #36: language/design mechanics (`__getattr__` delegation in wrapper dataclasses);
  pointer to `python_guidelines.md` #3.
- Lesson #47: process/agent-workflow (do not run tests while a background agent writes to
  shared modules).
- Lesson #52: domain-specific (homoglyph scam-token detection via Unicode ranges).
- Lesson #53: domain-specific (crypto zero-value flagging vs skipping policy).
- Lesson #54: domain-specific (Koinly token-variant substring matching).
- Lesson #57: cleanup hygiene (remove tests when removing their function).
- Lesson #60: documentation practice (document fuzzy-match tradeoffs in docstrings).
- Lesson #62: process/hygiene (review documents are temporary artifacts).
- Lesson #64: design idiom (context managers for resource cleanup).
- Lesson #65: design idiom (parameter objects for complex signatures).
- Lesson #67: domain-specific (PT futures/derivatives liquidation tax treatment).
- Lesson #76: process (TDD RED-then-GREEN discipline); referenced by many family lessons
  but is itself a workflow rule, not a root-cause family.
- Lesson #92: process/scope (fix in-scope refactoring findings in the same branch).
- Lesson #95: tool/skill usage (use the `resolve-vars` skill for path discovery).
- Lesson #137: cleanup hygiene (post-extraction unused-import/dead-code cleanup); pointer
  to `python_guidelines.md` #2.

Excluded count: 29.

---

## A. Equivalence-class coverage

A passing test pins one cell of an N-dimensional input space; the fix belongs at the
partition class (each caller, branch, value partition), not at the cell the test happened
to exercise. See `coding_guidelines.md` #18.

Lessons: Lesson #6, Lesson #7, Lesson #22, Lesson #41, Lesson #69, Lesson #70, Lesson #83,
Lesson #84, Lesson #90, Lesson #91, Lesson #111, Lesson #112, Lesson #117, Lesson #119,
Lesson #125, Lesson #133, Lesson #134, Lesson #136, Lesson #138. (19 lessons)

Clusters:

- Direct-unit-test coverage for extracted helpers: Lesson #41 (FIFO `_consume_against_pool`,
  key invariants: exact-match, partial consume, exhaustion) and Lesson #91 (FIFO
  `_apply_phantom_lot_flags`, categories: early returns, branches, boundaries, state
  mutation). See `## Duplicate clusters` for the true-duplicate candidate.
- Discriminating-test family (assert properties that FAIL under the wrong implementation):
  Lesson #125 (principle: N-guards-as-N-parametrized-cases; where-does-the-memo-attach),
  Lesson #133 (procedure: disable the guard, confirm RED), Lesson #134 (restore/undo
  variant: assert the intermediate mutation). Each is explicitly distinguished from the
  others in its body. Overlapping; cross-link all three.
- Coverage that crosses file/scope boundaries: Lesson #111 (grep ALL test files for stale
  assertions when data-flow semantics change) and Lesson #112 (a test's name must reflect
  its coverage scope within one file). Overlapping; distinct scope (cross-file vs
  within-file).
- Centralization / sibling-caller coverage: Lesson #117 (within one function, branch on
  the discriminator for a multi-cause flag), Lesson #119 (sibling aggregators in the same
  module must mirror byte-identical patterns), Lesson #136 (centralized helper across
  callers with divergent policies: pin EACH caller's policy arm). Overlapping; distinct
  unit of sibling-ness (causes, aggregators, callers).
- Validation/output-class coverage: Lesson #6 (string/parsing edge-case classes),
  Lesson #22 (zero-padded vs non-zero-padded date components), Lesson #90 (validation
  branches: format, range, calendar, time, whitespace), Lesson #83 (blank/None state for
  optional columns), Lesson #84 (disabled-flag backward-compat state), Lesson #138
  (aggregation tested in both directions). Overlapping.
- Structural/position coverage: Lesson #69 (Excel visual-structure tests), Lesson #70
  (verify every absolute-position site after a structural change), Lesson #7 (every
  external-data field must be wrapped; one unprotected field is a bug). Overlapping.

Accounting: 19 lessons.

---

## B. Error-policy propagation

A centralized fallible operation reused at new call sites must carry each site's
raise-vs-degrade policy; a single hard-coded policy in the shared code serves only the site
whose cost of silent failure happens to match. See `coding_guidelines.md` #19.

Lessons: Lesson #9, Lesson #38, Lesson #105, Lesson #124, Lesson #130, Lesson #135. (6
lessons)

Clusters:

- Broad-handler / specific-type escape: Lesson #9 (catch specific types, not broad
  `Exception` -- the write-side rule) and Lesson #38 (a specific type
  `FileNotFoundError` is swallowed by a broad handler meant for another case; convert it
  to `ConfigurationError` -- the escape-side rule). Overlapping; distinct facet.
- Reuse/centralization policy calibration: Lesson #105 (when reusing a validation/security
  pattern, inherit the guards but recalibrate degrade-vs-raise to the new call site's
  cost), Lesson #124 (in a per-row matching loop, run the fallible resolution before
  mutating the shared structure and make it RAISE, not return a sentinel), Lesson #135 (a
  fail-fast raise inside a degrade-to-None wrapper is swallowed unless explicitly
  propagated; trace it to `main()`). Overlapping; three distinct angles (calibration,
  ordering+raise-not-sentinel, propagation-through-wrappers).
- Degradation-path soundness: Lesson #130 (pre-bind every local referenced after a
  continue-style try whose except does not re-raise). Overlapping with Lesson #124 (both
  error-scope/degradation-path guards; #130 is name-resolution, #124 is value-policy).

Accounting: 6 lessons.

---

## C. Representation: sentinel vs None vs exception

The representation chosen for an absent/unknown/invalid value (a sentinel string, a
null/None, or a thrown exception) carries a distinct recoverability contract; conflating
them, or letting one leak across a boundary, produces wrong downstream behavior that looks
like a valid result. See `coding_guidelines.md` #20.

Lessons: Lesson #19, Lesson #43, Lesson #48, Lesson #79, Lesson #113, Lesson #114,
Lesson #131. (7 lessons)

Clusters:

- Sentinel/None leak into user-facing output: Lesson #113 (internal resolver sentinel
  string must not leak to display), Lesson #131 (f-string interpolating `str | None` must
  degrade explicitly for `None`, especially when `None` is reached via a warn-only drift
  path), Lesson #114 (default-empty cell assertions must accept both `None` and `""`).
  Overlapping; Lesson #131 explicitly distinguishes its root cause from Lesson #113
  (Python `None` value vs sentinel string), and Lesson #114 is the test-expectation facet
  of the same `None`/empty representation.
- Don't overload one field for two concepts: Lesson #43 (separate platform-level vs
  row-level review flags) and Lesson #79 (independent validation results vs entry-level
  review flags; keep them independent). Overlapping; Lesson #79 cites Lesson #43 and
  generalizes to the OGR-validation case.
- Boundary representation of display values: Lesson #19 (use self-explanatory output
  labels, not terse source names that leak across the internal-to-display boundary) and
  Lesson #48 (when a helper's internal representation changes dict to `defaultdict`,
  callers/tests passing the old form break). Overlapping; distinct boundary
  (source-name-to-display vs internal-data-structure-to-caller).

Accounting: 7 lessons.

---

## D. Single source of truth

When the same fact is authoritative in two (or more) places, the copies drift; designate
one source and make the rest views (or recompute), never a second independent authority.
See `coding_guidelines.md` #21.

Lessons: Lesson #1, Lesson #23, Lesson #25, Lesson #50, Lesson #58, Lesson #59, Lesson #66,
Lesson #68, Lesson #75, Lesson #77, Lesson #78, Lesson #80, Lesson #82, Lesson #85,
Lesson #94, Lesson #103, Lesson #115, Lesson #139. (18 lessons)

Clusters:

- Synchronization across authorities (manual + automated): Lesson #23 (three-way sync of
  code, registry, decision log), Lesson #58 (docs vs code structure), Lesson #68 (TOML
  decision-point flag vs `TaxJurisdictionConfig` dataclass field), Lesson #94 (verification
  TEST enforcing canonical-source to derived-output sync). Overlapping; Lesson #94 is the
  test-enforced variant of Lesson #23's manual grep.
- Duplicate detection before adding: Lesson #1 (grep for duplicate test methods before
  adding), Lesson #59 (grep across all sections of a hardcoded set before adding an item).
  Overlapping; near-duplicate (general duplication-check seed vs frozenset-specific). See
  `## Duplicate clusters`.
- Duplicate-key handling: Lesson #77 (build an index by summing on duplicate keys, never
  silent overwrite). Overlapping with the detection cluster (handling vs detecting).
- Two authorities for different aspects of one disposal: Lesson #75 (authoritative-source
  overrides must precede aggregation), Lesson #78 (OGR provides direction, CG provides
  magnitude -- split authority by aspect), Lesson #85 (recalculate validation metrics from
  aggregated values, not individual rows). Overlapping; three distinct angles of the
  OGR/CG authority problem.
- Field semantics determine the authoritative handling: Lesson #80 (aggregation strategy
  per field type) and Lesson #139 (`service_start_date` is the matching authority,
  `valid_from` is audit-only; never conflate). Overlapping; distinct facet
  (aggregation-strategy vs field-identity).
- One authoritative home for a fact: Lesson #50 (run-determining params in the output
  artifact, not logs), Lesson #82 (column count coupled across multiple constants),
  Lesson #66 (externalize frequently-changing lists to one data source), Lesson #25 (every
  construction site of a computed field must derive from real data, not a zero
  placeholder). Overlapping.
- Reuse the production authority in tests: Lesson #115 (reuse the production validator for
  a domain-validity predicate; do not duplicate the valid-set inline). Overlapping with
  Lesson #25 (both about not creating a second drifting authority).
- Cross-report structural authority: Lesson #103 (audit for shared identifiers across
  reports when separating a previously-merged tax category -- both reports individually
  authoritative without dedup yields double-counting). Overlapping; distinct from #73
  (Family G: cross-report contradiction).

Accounting: 18 lessons.

---

## E. Temporal / ordering invariants

An earlier event cannot consume state that only a later event establishes; when inputs
change the preconditions, recompute them after each change rather than once at the start.
See `coding_guidelines.md` #22.

Lessons: Lesson #26, Lesson #27, Lesson #39, Lesson #56, Lesson #81, Lesson #93,
Lesson #106, Lesson #107, Lesson #108, Lesson #110. (10 lessons)

Clusters:

- Matcher temporal invariants: Lesson #107 (ordered queue per non-unique key; pop one
  target per event), Lesson #108 (recompute window-relative tolerance after every shrink
  in a two-pointer sliding-window matcher), Lesson #110 (re-run phase-N feasibility on the
  post-phase-(N-1) state, not the original input set). Overlapping; each explicitly
  distinguishes from the others.
- Error-scope / operation ordering: Lesson #56 (try/finally scope must cover all raising
  operations so cleanup runs) and Lesson #106 (reuse the parsed value inside the existing
  try block; do not re-invoke the fallible parser outside it). Overlapping; Lesson #106
  distinguishes from Lesson #56 (leaked resources vs uncaught exception).
- Operation-sequence / state-flag ordering: Lesson #26 (atomic file replacement: no
  pre-deletion -- the remove-then-replace sequence opens a lost-file window), Lesson #27
  (apply defaults to source variables before computing derived values), Lesson #39
  (resource-release flag set after successful release only). Overlapping; three distinct
  ordering rules.
- Control-flow ordering: Lesson #93 (an early return in an optional-data branch can skip a
  mandatory section; use if/else) and Lesson #81 (conditional-formatting priority: check
  order determines which fill wins). Overlapping; distinct facet (mandatory-section
  guarantee vs selection determinism).

Accounting: 10 lessons.

Note: #132 (literal timezone token in `strptime` does not populate `tzinfo`) was moved to
Family H during this audit; see `## Catalog changes applied`.

---

## F. Layering / dependency direction

Dependencies point one way; logic that depends on a lower layer's detail does not belong at
a higher layer, and a lower layer must not reach up for a constant or reach into another
module's private internals. See `coding_guidelines.md` #23.

Lessons: Lesson #5, Lesson #28, Lesson #49, Lesson #86, Lesson #87, Lesson #88,
Lesson #121. (7 lessons)

Clusters:

- Public API boundary / private internals: Lesson #5 (import from public `__all__`; avoid
  `_private` imports in tests) and Lesson #28 (do not use `_private` constants across
  module boundaries; rename to public first -- importing privates violates the API
  boundary). Overlapping; near-duplicate (Lesson #5 is the broad import-hygiene seed,
  Lesson #28 is the focused private-boundary principle with the rename remediation). See
  `## Duplicate clusters`.
- Module extraction / responsibility: Lesson #86 (avoid circular dependencies during
  extraction; move shared constants downward), Lesson #87 (module and class size limits),
  Lesson #88 (single responsibility principle for modules). Overlapping; the
  crypto_reporting refactor cluster.
- Layer ownership + API-surface preservation: Lesson #49 (`TaxJurisdictionConfig` lives in
  `domain/jurisdiction.py`; infrastructure re-export is backward-compat only) and
  Lesson #121 (do not run `ruff check --fix` on modules that re-export for backward compat
  -- the re-export is the API surface). Overlapping; distinct facet (type ownership vs
  tooling that deletes the surface).

Accounting: 7 lessons.

Note: Lesson #28 was moved into Family F during this audit (the catalog draft had listed it
under Family C); see `## Catalog changes applied`.

---

## G. Data-loss observability

When a matching, aggregation, dedup, transformation, or filtering step drops or fails to
match a record, the drop must surface visibly at warning or higher; a silent discard is a
data-loss bug even when the program exits zero. Guards that read a manifest must fail
closed when it is absent. See `coding_guidelines.md` #24.

Lessons: Lesson #40, Lesson #44, Lesson #45, Lesson #46, Lesson #51, Lesson #61,
Lesson #63, Lesson #73, Lesson #102, Lesson #118, Lesson #126, Lesson #127. (12 lessons)

Clusters:

- Make the silent drop observable: Lesson #40 (defensive warnings must ALSO record items
  in the failure-tracking structure; logging alone is invisible to the consumer) and
  Lesson #61 (add logging to silent exception handlers). Overlapping; Lesson #40 is the
  stronger structure-recording variant, Lesson #61 is the baseline log-it rule.
- Fail fast on total / partial data-completeness failure: Lesson #63 (fail fast when ALL
  inputs fail; do not silently return empty) and Lesson #51 (all-or-nothing file-set
  validation: none skips, partial raises, all proceeds). Overlapping; distinct surface
  (scan/aggregation vs file set).
- Guard correctness + guard coverage: Lesson #126 (a verification guard that reads a
  manifest must fail closed when the manifest is absent -- a missing grep target exits
  non-zero and a naive `cmd && BAD || GOOD` reports GOOD) and Lesson #127 (static guards
  must cover code paths skipped in CI -- a `pytest.skip` test has no runtime backstop).
  Overlapping; distinct facet (guard-fail-closed vs guard-scan-coverage).
- Silent omission from output: Lesson #44 (summary sheets must be complete manifests, not
  filtered lists) and Lesson #46 (fiscal-year filter must apply to disposals only,
  post-FIFO; pre-filtering acquisitions silently removes them from the pool). Overlapping.
- Silent-data-issue observability in matchers/aggregators: Lesson #45 (dedup key must
  capture minimum sufficient identity; a too-coarse key silently drops distinct events),
  Lesson #102 (count-matched-items-per-event safety check; warn when one event matches
  more than one target), Lesson #118 (guard "take from first entry" fields against silent
  heterogeneity). Overlapping.
- Cross-report contradiction: Lesson #73 (cross-report validation for multi-report
  systems; verify classifications match across ALL reports). Standalone-ish; distinct from
  #103 (Family D: structural double-counting where reports agree).

Accounting: 12 lessons.

---

## H. Verify the real thing, not the abstraction

Do not trust names, summaries, mocks, docstrings, plan pseudocode, format literals, or
field-name conflation; trace the actual data from source to output and confirm the behavior
against the real implementation. See `coding_guidelines.md` #25.

Lessons: Lesson #12, Lesson #16, Lesson #21, Lesson #29, Lesson #30, Lesson #31,
Lesson #32, Lesson #33, Lesson #35, Lesson #37, Lesson #42, Lesson #55, Lesson #71,
Lesson #72, Lesson #74, Lesson #89, Lesson #96, Lesson #97, Lesson #98, Lesson #99,
Lesson #100, Lesson #101, Lesson #104, Lesson #109, Lesson #116, Lesson #120, Lesson #122,
Lesson #123, Lesson #128, Lesson #129, Lesson #132, Lesson #140, Lesson #141, Lesson #149,
Lesson #158. (35 lessons)

This is the over-represented family (~30% of mapped lessons, 35/113). Consolidation yields the most recall
value here, but most of these lessons are genuinely distinct angles (the corpus author
explicitly "Distinguishes from" siblings in the body); the value is in cross-linking, not
collapsing.

Clusters:

- Investigation / "is X handled correctly?": Lesson #71 (validation-first investigation
  pattern: verification tasks before implementation), Lesson #72 (data-trace verification
  requirement: code inspection alone is insufficient), Lesson #97 (characterization tests
  reveal plan-assumption errors between related quantities). Overlapping; Lesson #72
  extends Lesson #71, Lesson #97 is the characterization-test instance.
- Plan-authoring claims about production code: Lesson #100 (verify plan-time claims before
  writing tasks), Lesson #99 (trace the fixture when plan pseudocode compares same-unit
  fields by name), Lesson #101 (trace each affected OGR row to its originating TH Type).
  Overlapping; Lesson #99 and Lesson #101 are specific witnesses of Lesson #100's general
  rule. Lesson #158 (a refactor clause instructing net-new behavior conflicts with the same
  plan's byte-identical non-regression criterion) is a plan-vs-existing-behavior witness of
  the same family.
- Don't trust the test surface / mock / name: Lesson #30 (verify warning/guard path
  reachability before writing the test), Lesson #33 (trace plan edge-case behavior to a
  correctness outcome, not just "differs from before"), Lesson #42 (distinguish stale
  expectation from production bug; use hardcoded fixtures, not live state), Lesson #12 (do
  not add test-only parameters; tests must reflect real production usage), Lesson #16 (test
  real behavior, not implementation details), Lesson #89 (read the implementation before
  writing test expectations), Lesson #96 (structural identification for Excel tests, not
  hardcoded value exclusions). Overlapping.
- Verify claims/data against the real source: Lesson #31 (read the full dataclass
  definition before describing fields in a plan), Lesson #32 (distinguish code comments
  from observed data), Lesson #74 (cross-module function dependencies require complete
  imports -- run the real import), Lesson #35 (verify CSV test-fixture column alignment),
  Lesson #37 (monkeypatch module-level path constants or tests silently read real files).
  Overlapping.
- Verify external references against the authoritative source: Lesson #29 (AT guidance may
  cite pre-amendment CIRS paragraph numbers; verify against the consolidated PDF),
  Lesson #98 (probe the canonical URL before assuming an official source is unavailable).
  Overlapping.
- Verify real git / file state (don't trust a summary, gate, or stash): Lesson #55 (verify
  the staged diff matches the implementation), Lesson #116 (check prior same-session
  commits before reporting a verification-time scope violation), Lesson #122 (do not
  `git stash` for baseline comparisons in the docs-branch state; compare the committed
  blob), Lesson #128 (`git mv` nests when dest exists; the doc-hierarchy gate does not
  catch intra-tree nesting), Lesson #129 (translate stale doc paths in plans authored
  before a doc-hierarchy migration), Lesson #141 (a bulk text-replacement whose search
  string is a substring of a larger token matches at the wrong offset; verify with a
  byte-level diff, not a match count). Overlapping; the git/docs-state verification cluster.
- Plan pseudocode vs tests vs invariants consistency: Lesson #104 (trace ALL branches of a
  multi-branch conditional; include a trace table), Lesson #120 (reconcile plan pseudocode
  against plan tests and design invariants before GREEN), Lesson #109 (re-read RED test
  assertions against revised design invariants before flipping to GREEN). Overlapping.
- Branch-count / enumeration accuracy: Lesson #123 (decision-point doc prose enumerations
  must match implemented code branches) and Lesson #104 (above). Overlapping.
- Don't trust the datetime representation / format literal: Lesson #21 (date comparison
  must use date objects, not strings -- lexicographic compare silently wrong), Lesson #132
  (a literal timezone token in a `strptime` format does not populate `tzinfo`; naive
  datetimes from external reports are LOCAL time, not UTC). Overlapping.
- Doc cross-ref disambiguation: Lesson #140 (when renumbering a colliding numeric ID,
  disambiguate each cross-ref by context, not by the number alone). Standalone-ish.

Accounting: 35 lessons.

---

## Duplicate clusters

Every same-family cluster of two or more lessons, classified. Per the `generalize` skill's
rule, when in doubt a cluster is classified OVERLAPPING (same family, distinct angle), not
true-duplicate. A separate fresh-agent challenge (see `## Precision gate`) independently
reviews each true-duplicate candidate before any consolidation (Task 6).

### Phase 4b atom-level pass (formal validation)

A read-only formal run of the `generalize` skill's Phase 4b (added in plan Task 5b) on the
140-lesson corpus at audit time: each of the ~111 mapped lessons then present is decomposed
into its atomic principle(s) (1-3 per lesson; most yield one), then deduplicated
family-agnostically across the WHOLE corpus (not within-family) under the sharp bar (same
actionable rule; a different incident or a different family is NOT sufficient). The corpus
is near-atomic: the shared-atom ratio (atoms appearing in 2+ lessons) is roughly 3.6% (a
handful of shared atoms across ~111 lessons), so this phase is a safety net, not the primary
dedup lever. Note this
3.6% counts shared atoms FOUND; most are intra-family overlaps that Phase 4 already
classified as OVERLAPPING (kept, not trimmed), so the net cross-family extraction is 1
(documented below), not ~4. The two figures measure different things and do not contradict.

**Validation verdict: YES.** Phase 4b caught a shared atom that family-clustering was
structurally blind to: lesson #81 (Family E, temporal / ordering invariants) bundles a
column-coupling bullet ("When adding columns, update the column count constant AND the
conditional formatting loop range") that verbatim-restates lesson #82 (Family D, single
source of truth). Because #81 and #82 sit in different families, Phase 4 (within-family)
never compared them; only the family-agnostic atom pass surfaced the share. This is the
case the family-clustered-only audit misses by construction, and it is the witness cited in
the `generalize` skill's Phase 4b and its "Family-clustered-only audit misses cross-family
shared atoms" Anti-Pattern.

The same sharp bar refuted the prior empirical pass's candidate true-duplicates: #59/#1
(distinct actions: #1 build-collision error vs #59 silent data-member coalescence; they
share the grep TECHNIQUE, not the same ACTION) and #58/#23 (distinct actions: #23
field-level registry drift vs #58 structure-level module-layout drift) are
distinct-atom siblings, kept OVERLAPPING. #83/#84 (test-the-off-state) are likewise kept
OVERLAPPING (value-shape vs behavioral equivalence).

**Net result: 0 collapses; 1 cross-family extraction.** The #81 column-coupling bullet is
extracted to its canonical home #82 (the bullet is trimmed from #81 at Task 6); #81 (Family
E) survives with its primary priority-ordering atom (conditional-formatting priority: check
highest-priority conditions first, return early) fully intact. #82 is unchanged. No lesson
heading is deleted and no lesson is renumbered.

### true-duplicate candidates

**Outcome: ZERO confirmed true-duplicates.** One candidate was proposed by the
self-challenge pass and overturned by the independent fresh-agent challenge (see
`## Precision gate`). The proposal is documented below for the record.

The formal Phase 4b atom-level pass (above) independently confirms ZERO true-duplicates at
the atomic level too: the family-level verdict (all same-family pairs are OVERLAPPING)
holds when each lesson is decomposed to its atoms and compared family-agnostically. The
only atom-level action Phase 4b took was the cross-family extraction of #81's
column-coupling bullet to canonical #82, which is not a true-duplicate collapse (no heading
removed, no body redirected).

**Proposed then overturned: Canonical #41 <- collapse #91.** "Extracted helpers need direct
unit tests." Lesson #41 ("Extracted Helpers Need Direct Unit Tests for Key Invariants") and
Lesson #91 ("Direct Unit Testing for Extracted Helper Functions") state the same headline
rule: when a helper is extracted from an orchestrator, add direct unit tests rather than
relying only on indirect integration coverage. Both use a FIFO-helper witness
(`_consume_against_pool_inplace` vs `_apply_phantom_lot_flags`). Same family (A), same shape
trigger (extraction of a helper), same mechanism (indirect coverage does not bind the
helper's branches).

**Self-challenge (argue the opposing case):** Lesson #91's test-category taxonomy is more
general and transferable (early returns, conditional branches, boundary conditions, state
mutation, edge cases) than Lesson #41's FIFO-specific list (exact-match, partial consume,
exhaustion, empty input, non-taxable path). A reader extracting a NON-FIFO helper would
find Lesson #91's categories more directly applicable, so the two carry distinct value:
Lesson #41 is the incident-anchored witness, Lesson #91 is the generalized taxonomy.

**Fresh-agent challenge verdict: RECLASSIFY_OVERLAPPING.** The headline rule is shared, but
the actionable content (what to test) targets two non-subsumable facets: #41's categories
(exact-match / partial-consume / exhaustion / non-taxable-path) are FIFO consumption-math
invariants, while #91's (early-return / branch / boundary / state-mutation / min-max) are a
domain-neutral control-flow surface. The transferability gap is real: a non-FIFO helper
author reading only #41 loses the generic dispatchable checklist, and a FIFO-pool author
reading only #91 loses the consumption-math framing. Under the `generalize` skill's rule
("when in doubt, overlapping; distinct witness = overlapping"), collapsing #91 would
destroy the standalone non-FIFO-dispatchable checklist the tie-breaker protects. Canonical
= #91 (the better generalization); See-also #41. Catalog anchor #91 in
`coding_guidelines.md` #18 STAYS as-is (no re-point needed; no body is collapsed at Task 6).

(No other cluster was proposed as true-duplicate. All same-family pairs are classified
OVERLAPPING in `### overlapping clusters` and are NOT candidates for collapse.)

### overlapping clusters (keep both; cross-link)

- **cross-family, #81 (Family E) / #82 (Family D)** (extracted): the Phase 4b atom-level
  pass found that #81's `Implementation notes` carried a column-coupling bullet ("When
  adding columns, update the column count constant AND the conditional formatting loop
  range") that verbatim-restated #82 (the canonical single-source-of-truth home for "these
  constants are coupled; they all represent how many columns exist"). Family-clustering
  never compared them (different families). Action: the bullet is TRIMMED from #81; #81's
  primary priority-ordering atom (conditional-formatting priority) survives intact; #82 is
  unchanged. This is a cross-family extraction, not a same-family overlap; no heading is
  removed and no lesson is renumbered. #81 and #82 already cross-reference each other in
  their `See also` lines.
- **A, #41 / #91** (resolved): the audit's only true-duplicate candidate, overturned to
  OVERLAPPING by the fresh-agent challenge. Canonical = #91 (domain-neutral control-flow
  taxonomy), See-also #41 (incident-anchored FIFO witness). Full record in
  `### true-duplicate candidates` and `## Precision gate`.
- **A, #125 / #133 / #134** (discriminating tests): principle (#125) vs procedure (#133)
  vs restore/undo variant (#134). Each body distinguishes itself. Cross-link.
- **A, #111 / #112**: cross-file stale assertions (#111) vs within-file name-vs-body
  scope (#112). Cross-link.
- **A, #117 / #119 / #136**: multi-cause flag within one function (#117) vs sibling
  aggregators mirror patterns (#119) vs centralized helper across callers (#136). Each
  body distinguishes itself. Cross-link.
- **B, #9 / #38**: write-side (catch specific not broad, #9) vs escape-side (convert the
  specific type so it evades the broad handler, #38). Cross-link.
- **B, #105 / #124 / #135**: recalibrate policy on reuse (#105) vs raise-not-sentinel +
  ordering (#124) vs propagate through wrappers (#135). Cross-link.
- **C, #113 / #131 / #114**: sentinel string leak (#113) vs `None`-value interpolation
  (#131) vs test-expectation `None`/`""` (#114). Cross-link.
- **C, #43 / #79**: platform-vs-row flags (#43) vs independent-validation-vs-entry flags
  (#79, cites #43). Cross-link.
- **D, #1 / #59**: general duplicate-detection seed (#1) vs frozenset cross-section (#59).
  Cross-link.
- **D, #23 / #58 / #68 / #94**: multi-authority synchronization; #94 is the test-enforced
  variant of #23's manual grep. Cross-link.
- **D, #75 / #78 / #85**: OGR/CG authority -- override ordering (#75) vs split by aspect
  (#78) vs aggregate-then-validate (#85). Cross-link.
- **D, #80 / #139**: field-semantics determine strategy (#80) vs field-identity
  (#139). Cross-link.
- **E, #107 / #108 / #110**: the matcher temporal-invariant triple. Cross-link.
- **E, #56 / #106**: try/finally cleanup scope (#56) vs reuse-parsed-value-in-try (#106).
  Cross-link.
- **F, #5 / #28**: broad import-hygiene seed (#5) vs focused private-boundary principle
  with remediation (#28). Cross-link. (If the fresh-agent finds #5's other bullets
  irrelevant and only the private-import bullet matters, this could tighten to a
  true-duplicate; default is overlapping.)
- **G, #40 / #61**: structure-recording (#40) vs baseline log-it (#61). Cross-link.
- **G, #63 / #51**: total-failure fail-fast (#63) vs partial-file-set fail-fast (#51).
  Cross-link.
- **G, #126 / #127**: guard-fail-closed (#126) vs guard-scan-coverage (#127). Cross-link.
- **H, #71 / #72 / #97**: investigation pattern / data-trace / characterization-test.
  Cross-link.
- **H, #100 / #99 / #101**: general plan-claim rule (#100) and its two specific witnesses.
  Cross-link.
- **H, #55 / #116 / #122 / #128 / #129 / #141**: the git/docs-state verification cluster.
  Cross-link.
- **H, #104 / #120 / #109**: plan pseudocode vs tests vs invariants. Cross-link.
- **H, #21 / #132**: datetime representation traps. Cross-link.

---

## Blind-spot analysis

**Over-represented families.** Two families dominate. Family H (verify the real thing, not
the abstraction) carries 33 of 112 mapped lessons; Family A (equivalence-class coverage)
carries 19; Family D (single source of truth) carries 18. H and A together map to roughly
30% of the corpus; the audit finds H+A = 52/112, with D close behind. This is the
expected shape of a corpus that grew by capturing each verification and coverage failure as
a new lesson. Consolidation recall-value is highest in H, but the audit found that the H
lessons are mostly genuine distinct angles (the corpus author already wrote
"Distinguishing from #N" cross-refs into the later lessons), so the payoff is
cross-linking and a `**Principle:**` tag rather than wholesale collapse. Family A had the
audit's only true-duplicate candidate (#41/#91), but the fresh-agent challenge overturned
it to OVERLAPPING (distinct facets: FIFO consumption-math invariants vs domain-neutral
control-flow surface), so no Family A lesson is collapsed. Family D's 18 lessons span five
distinct sub-shapes (sync, detection, OGR-authority, field-semantics,
one-authoritative-home) and should be cross-linked by sub-shape.

**Under-represented families.** Family B (error-policy propagation) has 6 lessons and
Family F (layering / dependency direction) has 7; both are thin but healthy (each has a
clean cluster and a catalog anchor set). No family has zero or one lesson, so there is no
empty blind spot. The genuine blind spot is not an empty family but a thin one: Family B
is dominated by the OGR/crypto-payment-proceeds incident cluster (#105, #124, #135 all from
two recent plans); a future incident of "centralized fallible op with divergent caller
policies" outside crypto may not find a close witness, so the catalog's B shape trigger
(#19) is the primary recall surface and should stay sharp. Family C (7 lessons) is also
relatively thin and skews to the sentinel/None-display facet; the exception-vs-sentinel
facet is under-witnessed.

---

## Dry-run recall

Three synthetic incidents in fresh (non-tax-reporting) modules, used to check that the
catalog's shape triggers (#18-#25) recall the right family. None of the current triggers
was found too vague, so no shape-trigger tightening was applied (the rule is: only tighten
when the dry-run finds a trigger too vague; do not loosen).

1. **Shared `parse_amount` helper across three billing callers.** A billing service
   extracts `parse_amount` from an invoicing orchestrator. Three callers now invoke it:
   one that must reject the invoice (raise), one that must warn-and-skip, one that must
   default to zero. A test is added for the raising caller and passes; the warn-and-skip
   caller still silently drops the malformed amount. Target family: A (equivalence-class
   coverage), with a B see-also (the per-caller raise/degrade policy). Current #18 shape
   trigger ("you just added a test or guard after extracting a shared helper, centralizing
   a policy... is there a test that would fail if the implementation were wrong for that
   class specifically?") lands the reader on A. Verdict: recalls correctly; no tightening.

2. **Reused `validate_jwt` returns None on invalid tokens.** A new microservice reuses the
   auth service's `validate_jwt`, which returns `None` on an invalid token. The new caller
   uses the result unconditionally (`user = token["sub"]`) and raises an uncaught
   `TypeError`, because the helper's "return None on invalid" policy was right for the
   original caller (which checked) but wrong for the new one. Target family: B (error-policy
   propagation). Current #19 shape trigger ("you are centralizing a fallible op... that
   more than one caller now invokes, or reusing an existing validation/security pattern at
   a new location... what is the cost of a silent failure here, and does the centralized
   code's raise or degrade match that cost?") lands the reader on B. Verdict: recalls
   correctly; no tightening.

3. **`resolve_country` sentinel leaks into a report sentence.** A data pipeline's
   `resolve_country(phone_number)` returns the internal sentinel `"UNKNOWN_REGION"` when it
   cannot resolve. A downstream report interpolates it into a user-facing sentence
   ("Tax applied for region UNKNOWN_REGION."). Target family: C (representation: sentinel
   vs None vs exception). Current #20 shape trigger ("you are passing such a value across a
   boundary... is it distinguishable from a legitimate value (sentinel vs bare empty), and
   does it degrade explicitly when the field is reachable via a warn-only path?") lands the
   reader on C. Verdict: recalls correctly; no tightening.

All three incidents recall the intended family through the current shape triggers. No
shape-trigger text was tightened.

---

## Precision gate

Per-true-duplicate-cluster record. The self-challenge verdict is the first precision pass
(this audit); a separate read-only fresh-agent challenge is the independent second pass
before Task 6 consolidates any body.

| Candidate | Self-challenge verdict | Fresh-agent challenge verdict |
|---|---|---|
| #41 <- #91 | true-duplicate (opposing case: #91 is the more general taxonomy, #41 the incident-specific witness; self-challenge overrode it as "rule identical, difference is witness + phrasing only"). | **RECLASSIFY_OVERLAPPING.** Distinct facets survive: #41's categories (exact-match / partial-consume / exhaustion / non-taxable-path) are FIFO consumption-math invariants; #91's (early-return / branch / boundary / state-mutation / min-max) are a domain-neutral control-flow surface. A non-FIFO reader loses a dispatchable checklist if #91 collapses. Per the skill's "when in doubt, overlapping" tie-breaker, canonical = #91, See-also #41. **No body collapsed at Task 6.** |

**Gate result: ZERO true-duplicates confirmed.** The single candidate (#41 <- #91) was
overturned to OVERLAPPING by the independent fresh-agent challenge. Task 6 consolidation
performs NO destructive merges; it only adds `**Principle:**` tags and See-also cross-links.
All same-family pairs are classified OVERLAPPING in `## Duplicate clusters`.

---

## Accounting check

Union of all family `Lesson #N` lists plus the excluded set equals {1..142}:

- A: 19 (Lesson #6, #7, #22, #41, #69, #70, #83, #84, #90, #91, #111, #112, #117, #119,
  #125, #133, #134, #136, #138)
- B: 6 (Lesson #9, #38, #105, #124, #130, #135)
- C: 7 (Lesson #19, #43, #48, #79, #113, #114, #131)
- D: 18 (Lesson #1, #23, #25, #50, #58, #59, #66, #68, #75, #77, #78, #80, #82, #85, #94,
  #103, #115, #139)
- E: 10 (Lesson #26, #27, #39, #56, #81, #93, #106, #107, #108, #110)
- F: 7 (Lesson #5, #28, #49, #86, #87, #88, #121)
- G: 12 (Lesson #40, #44, #45, #46, #51, #61, #63, #73, #102, #118, #126, #127)
- H: 34 (Lesson #12, #16, #21, #29, #30, #31, #32, #33, #35, #37, #42, #55, #71, #72, #74,
  #89, #96, #97, #98, #99, #100, #101, #104, #109, #116, #120, #122, #123, #128, #129,
  #132, #140, #141, #149)
- Excluded: 29 (Lesson #2, #3, #4, #8, #10, #11, #13, #14, #15, #17, #18, #20, #24, #34,
  #36, #47, #52, #53, #54, #57, #60, #62, #64, #65, #67, #76, #92, #95, #137)

Total accounted: 19 + 6 + 7 + 18 + 10 + 7 + 12 + 34 + 29 = 142.
