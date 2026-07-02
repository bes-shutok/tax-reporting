# 2026-07-01-principle-index-audit-snapshot

> FROZEN ONE-TIME AUDIT. This file is a verbatim snapshot of the deleted
> `docs/maintenance/principle-index.md`, captured by `lessons_migrate.py` at
> migration time. It is NOT maintained; recall is by grep on
> `docs/maintenance/development_lessons.md` (project) and the user-level corpus
> (cross-project). Do not edit.

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

