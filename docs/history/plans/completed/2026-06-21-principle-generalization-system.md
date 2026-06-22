# Plan: Principle-Generalization System (catalog + generalize skill + corpus consolidation)

Cross-repo effort (ai-playbook + tax-reporting). Builds the infrastructure that lets lessons
transfer to *different-but-connected* future cases, then uses that infrastructure to deduplicate
the existing ~139-lesson corpus.

Branch: stays on current branches per user decision (tax-reporting `2026-06-21-crypto-payment-proceeds-refactor`;
ai-playbook `main`). Local-only repos: nothing is pushed.

Plan review: `docs/history/reviews/2026-06-21-plan-review-principle-generalization-system-r4.md` (latest, ready: Blocker=0 Medium=0) · r1/r2/r3 in same directory

## Terms

- **Principle family**: a canonical root-cause category (e.g. equivalence-class coverage, error-policy
  propagation). The authority is the new catalog (`coding_guidelines.md` #17+). ~8 families, curated by hand.
- **Shape trigger**: the situation that should make you suspect a given family (the *problem shape*),
  independent of file/module. This is what enables recall across modules, unlike today's location-keyed refs.
- **generalize skill**: a new skill with two modes. `map` (one incident/lesson to a family + shape trigger,
  used live by `learn`) and `audit` (cluster a whole corpus, surface duplicates, emit a consolidation +
  blind-spot report).
- **Blind-spot report**: the `audit` output: family to lesson-number map, duplicate/overlap clusters,
  over- and under-represented families. Lives at `docs/maintenance/principle-index.md` and doubles as
  the navigational index after consolidation.
- **Consolidation**: using the audit's duplicate map to merge truly-redundant lessons and tag the rest
  with a `**Principle:**` line, without renumbering.

## Gist & Examples

**What changes.** Today the lessons corpus is incident-anchored: it is recalled by *code location*
(instruction-file cross-refs like "See `development_lessons.md` #N") and *incident surface* (lesson
headlines), not by *problem shape*. Empirically, ~139 lessons re-derive only ~8 root-cause families; two
of them (equivalence-class coverage, and verify-the-real-thing) account for ~30%. So the corpus prevents
the *same bug in the same place* but under-helps on a *different case with the same root shape in a new
module* (no cross-ref there, headline does not match the new surface). This plan:

1. Authors a curated ~8-family **principle catalog** as new sections (`#17` onward) in shared
   `coding_guidelines.md`, each giving a one-line precept, a failure signature, a **shape trigger**,
   and a concrete witness example. (Ships as a *draft*; the audit finalizes anchors and may revise
   shape triggers.)
2. Adds a **`generalize` skill** (map + audit modes) modeled on `premortem`.
3. Strengthens `learn`'s *Generalization pass* so every newly captured lesson must name its family and
   write a shape trigger.
4. Resolves a pre-existing data-quality defect: lesson numbers `#15`, `#16`, `#17` each appear twice.
5. Runs `generalize audit` on the corpus to get the duplicate/overlap map and a **blind-spot report**,
   then re-commits the catalog as authoritative.
6. **Consolidates** the corpus (after a precision review gate on the duplicate map): merges
   truly-redundant lessons and tags the rest with `**Principle:**`, shrinking the bloat the user flagged.
7. Wires cross-refs so the catalog and the index are discoverable.

**Why needed.** The user observed the corpus "describes the issues of the past" and doubted it would
help the future. The fix is to re-anchor lessons to the underlying CS/SE principle and to remove the
duplicates that re-derive the same principle under different incident skins. Consolidation (the user's
redirect) is the payoff: fewer, sharper lessons, each reachable by problem shape.

**Example (coverage family).** "Equivalence-class coverage" = *a passing test pins one cell of an
N-dimensional space; fix the partition class, not the cell.* Generic witness: after extracting a shared
helper across N callers, a test is added for one caller's failure and the sibling callers (with a
different raise/degrade policy) still fail silently. In tax-reporting this surfaces as lessons #91, #111,
#117, #119, #125, #133, #136; in any other repo the same shape has different lesson numbers or none, so
the catalog witness must be the *generic sketch*, with the local numbers as an optional parenthetical.

**Draft taxonomy (authoritative after Task 5 re-commits the catalog).** One umbrella section + one
section per family. Anchor numbers are tax-reporting-local and illustrative; the audit finalizes the
full per-family set:

| # | Family | One-line precept | Illustrative anchors (audit finalizes) |
|---|--------|------------------|----------------------------------------|
| A | Equivalence-class coverage | A passing test pins one cell; fix the class, not the cell | #91, #111, #117, #119, #125, #133, #136 |
| B | Error-policy propagation | A centralized fallible op must carry each call site's raise/degrade policy | #9, #105, #124, #130, #135 |
| C | Representation: sentinel vs None vs exception | Each carries distinct recoverability; do not conflate | #28, #113, #114, #131 |
| D | Single source of truth | Two authoritative copies drift; one source, the rest views | #59, #75, #77, #85, #103 |
| E | Temporal / ordering invariants | Earlier events cannot consume later state; recompute preconditions after each input change | #106, #107, #108, #110, #132 |
| F | Layering / dependency direction | Dependencies point one way; logic lives at the layer that owns it | #49, #86, #87, #88, #121 |
| G | Data-loss observability | Unmatched/dropped records must surface; never silent discard | #40, #51, #73, #102, #126 |
| H | Verify the real thing, not the abstraction | Do not trust names, summaries, or mocks; trace actual data/behavior | #71, #72, #99, #100, #101, #116, #120, #123 |

**Excluded from principle treatment (stay as-is):** genuine tool-quirk lessons (one-off, not a recurring
shape) and domain-specific tax/crypto lessons whose value is the domain fact, not a transferable principle.

## Evaluation Criteria

**Quality dimensions:**
- Coverage (correctness): every non-excluded corpus lesson maps to exactly one family after the audit
  (no orphans). Verified by `principle-index.md` accounting.
- Integrity (correctness): no dangling LESSON cross-refs after consolidation. "Lesson cross-ref" means
  any `#N` on a line carrying a lesson-ref lead-in (`Lesson #N`, `lesson #N`, `Distinguishing from #N`,
  `development_lessons.md #N`, `Merged into #N`, `See also/see also #N`, including slash/comma list items);
  bare `#N` tokens on lines with no lead-in (issue IDs, PR numbers, years) are out of scope. Verified by
  command #5.
- Unique identity (correctness): every `## N.` heading number is unique. Verified by command #7
  (duplicate-heading gate must be empty).
- Cluster precision (correctness): the audit's true-duplicate list passes a review gate (human approval
  or a fresh-agent challenge) before consolidation mutates canonical docs, so no distinct-angle lesson is
  collapsed into a redirect.
- Recall-by-shape (maintainability/transfer): the catalog gives a shape trigger per family and a generic
  (repo-agnostic) witness; a synthetic incident in a fresh module recalls the right family.
- Non-regression (maintainability): consolidation does not renumber lessons and does not lose a lesson's
  witness. Verified by diff review, the dangling-ref check (#5), and a witness-preservation grep.
- House style (quality): catalog uses no H3, no code fences, inline `**Example:**`/`**Exception:**`;
  every touched prose file is em-dash-free; `generalize` frontmatter valid and LICENSE present.

**Release gates:**
- `coding_guidelines.md` has the umbrella + 8 family sections (exactly 9 new `## 17` to `## 25`),
  style-valid and em-dash-free; re-committed authoritative after the audit.
- `generalize` skill is present, frontmatter valid, LICENSE present, Integration Points reference
  `learn`/`plans`/review-agents, shared docs resolved via the `shared_docs_dir` USER-facts key.
- `learn` Generalization pass requires naming the family + writing a shape trigger.
- Duplicate lesson numbers resolved (command #7 empty).
- Audit has run; `principle-index.md` exists with the family map, duplicate clusters, and blind-spot
  analysis; the true-duplicate list passed the precision review gate; consolidation merged/tagged per
  the map.

## Design Invariants (CR Guard)

1. **Unique lesson numbers are a precondition, not an assumption.** The corpus today has `#15`, `#16`,
   `#17` each appearing twice (139 headings, 136 unique). Task 4 resolves this BEFORE the audit. After
   Task 4, numbers are unique and stay unique: consolidation never renumbers. All `#N` cross-refs in
   `AGENTS.md`/`CLAUDE.md` (symlink), `plan_quality_guidelines.md`, and the lessons' own See-also/
   Distinguishing-from links depend on stable, unambiguous numbers.
2. **Consolidation merges without renumbering.** A *true duplicate's* body collapses to a redirect
   pointer that preserves its number; an *overlapping* lesson keeps its body and gains a `**Principle:**`
   line. A redirect preserves the heading so cross-refs still resolve.
3. **Catalog is curated by hand, not auto-generated.** ~8 families. The audit *maps* lessons to families;
   it does not invent families. The catalog ships draft in Task 1 and authoritative in Task 5.
4. **Tool-quirk and domain-specific lessons are excluded** from principle treatment (no family line).
5. **The incident stays a required witness**, demoted from the headline. A bare abstract precept with
   no concrete failure mode is "principle theater" and is unfalsifiable/forgettable. Catalog witnesses
   are GENERIC (repo-agnostic) sketches; local lesson numbers are an optional parenthetical.
6. **`learn` and `generalize` stay language- and agent-agnostic.** Reference shared docs via the
   `shared_docs_dir` USER-facts key (skills run under user context; this key is NOT present in per-repo
   facts); reference sibling skills via relative `../<skill>/SKILL.md`. Never hardcode machine paths.
7. **ai-playbook: stage only the named files.** The repo has pre-existing uncommitted changes to
   `docs/AGENTS.md` and `projects/.ai-playbook/agent_workflow_guidelines.md` that are NOT this work and
   must be preserved. Named-pathspec `git add <file>` stages only that path and never sweeps the
   pre-existing unstaged hunks in other files; still, never use `git add -A`/`git add .` in ai-playbook.
   Do not touch either pre-existing file.
8. **True duplicate vs overlapping.** The audit distinguishes fully-redundant lessons (collapse to a
   redirect) from same-family/distinct-angle lessons (keep body, add `**Principle:**`, cross-link). A
   precision review gate (Task 5) checks each true-duplicate cluster before consolidation (Task 6).
   Collapsing a lesson that carries a distinct angle loses information.

## Review Scope

**Explicit must-fix** (findings on these paths are always in scope):

**ai-playbook (shared docs + skills):**
- `projects/.ai-playbook/coding_guidelines.md` *(new sections #17+)*
- `agents/skills/generalize/SKILL.md` *(new)*
- `agents/skills/generalize/LICENSE.txt` *(new)*
- `agents/skills/learn/SKILL.md`

**tax-reporting (corpus + index + wiring):**
- `docs/maintenance/development_lessons.md`
- `docs/maintenance/principle-index.md` *(new)*
- `docs/maintenance/plan_quality_guidelines.md`
- `AGENTS.md` (and `CLAUDE.md` via symlink)

**Plan-related extension:** substantively required wiring is in scope even if not pre-listed (e.g. a
stale `#N` ref uncovered during duplicate-resolution or consolidation, a sibling doc that should point
at the index).

**Out of scope:**
- `projects/.ai-playbook/agent_workflow_guidelines.md` and `docs/AGENTS.md` (ai-playbook) have
  pre-existing uncommitted changes; do not touch. The existing `docs/AGENTS.md` line that indexes
  `coding_guidelines.md` already makes the new `#17+` sections discoverable, so no new index line is
  required there.
- The crypto-payment-proceeds refactor (separate plan `2026-06-21-crypto-payment-proceeds-refactor.md`).
- Renumbering lessons (other than the Task 4 collision fix) or rewriting legacy (#1 to ~#97) lesson
  bodies beyond adding a `**Principle:**` line / a redirect for true duplicates.

## Validation Commands

```bash
# 1. No em-dash in any touched prose (run per repo root):
"${CHECK_NO_EM_DASH_SCRIPT:-$HOME/.ai-playbook/scripts/check-no-em-dash.sh}" touched

# 2. Catalog structure: exactly 9 new headings (#17 umbrella + #18..#25 families); no H3/code-fences in range:
test "$(grep -cE '^## (1[7-9]|2[0-5])\.' ~/Projects/myrepos/ai-playbook/projects/.ai-playbook/coding_guidelines.md)" -eq 9
awk '/^## 17\./{f=1} f&&/^## /&&!/^## 17\./{f=0} f&&/^### |^```/{print NR": "$0}' ~/Projects/myrepos/ai-playbook/projects/.ai-playbook/coding_guidelines.md   # must print nothing

# 3. generalize skill frontmatter + LICENSE + Integration Points:
sed -n '1,12p' ~/Projects/myrepos/ai-playbook/agents/skills/generalize/SKILL.md
ls ~/Projects/myrepos/ai-playbook/agents/skills/generalize/LICENSE.txt
grep -nE '^## Integration Points|^### With (learn|plans)' ~/Projects/myrepos/ai-playbook/agents/skills/generalize/SKILL.md

# 4. learn tweak present (family + shape trigger required, points at catalog + generalize):
grep -nE 'shape trigger|principle family|coding_guidelines.md #17|generalize' ~/.agents/skills/learn/SKILL.md

# 5. No dangling LESSON cross-refs, across ALL of docs/maintenance/ + AGENTS.md (recursive). Extract every
#    #N on a line carrying a lesson-ref lead-in (Lesson #/lesson #, Distinguishing from #,
#    development_lessons.md #N, Merged into #, See also/see also #); this also catches slash/comma list
#    items (e.g. "Distinguishing from #71 / #72"). Lines with bare #N and NO lead-in (issue IDs, PR
#    numbers, years) are ignored. Assumption (verified clean: 84 unique numbers, max 136, zero DANGLING,
#    no over-max token on any lesson-ref line): no lesson-ref line co-carries an unrelated #N token.
#    Re-verify if a future edit adds issue/PR refs. principle-index.md (Task 5) must write its family
#    lesson lists as `Lesson #N` so this gate validates the index's own references too.
grep -rhE '(Lesson|lesson) #|Distinguishing from #|development_lessons\.md.{0,3}#|Merged into #|(See also|see also) #' \
  docs/maintenance/ AGENTS.md \
  | grep -oE '#[0-9]+' | grep -oE '[0-9]+' | sort -u > /tmp/refs.txt
for n in $(cat /tmp/refs.txt); do grep -q "^## $n\." docs/maintenance/development_lessons.md || echo "DANGLING #$n"; done

# 6. principle-index maps all 8 families and accounts for every non-excluded lesson:
grep -cE '^## [A-H]\.' docs/maintenance/principle-index.md   # expect 8

# 7. No duplicate lesson numbers (precondition after Task 4; MUST be empty):
grep -oE '^## [0-9]+\.' docs/maintenance/development_lessons.md | sort | uniq -d
```

## Phase A: Generalization infrastructure

### Task 1: Author the principle catalog in shared docs (DRAFT; Task 5 finalizes)

Files:
- `~/Projects/myrepos/ai-playbook/projects/.ai-playbook/coding_guidelines.md`

- [x] Add an umbrella section `## 17. Root-Cause Principle Catalog (Recall by Problem Shape)` directly
  after `## 16`. Content: why the catalog exists (recall by problem shape, not code location or incident
  surface); how to use it (when capturing or reviewing a lesson, name its family from #18 onward and
  write a shape trigger; see the `generalize` skill and `learn`'s Generalization pass); a one-line-per-family
  map (A to H) linking to #18 onward. Mark the catalog DRAFT here; the audit (Task 5) finalizes anchors
  and may revise shape triggers.
- [x] Add one section per family (`## 18` to `## 25`) in the order A to H from the draft taxonomy above.
  Each section contains: a one-line precept; a `**Failure signature:**` paragraph (what the bug looks
  like); a `**Shape trigger:**` paragraph (when to suspect this family); an `**Example:**` paragraph with
  a GENERIC repo-agnostic witness sketch (self-contained; no reliance on any repo's lesson numbers), plus
  an optional parenthetical of local anchors (e.g. "tax-reporting: #91, #111"); an `**Exception:**` note
  where the family does not apply.
- [x] Keep inline family anchors to the illustrative set in the draft taxonomy; write "see each repo's
  `principle-index.md` for the full lesson map per family" rather than enumerating all ~139 numbers inline.
- [x] House style: H2 sections only (no H3), no code fences, inline bold labels, cross-refs as
  `` `coding_guidelines.md` #N ``. Em-dash-free.
- [x] Verify: command #2 passes (exactly 9 new headings; no H3/fences in the range); command #1 clean.
- [x] Commit (ai-playbook): stage ONLY `projects/.ai-playbook/coding_guidelines.md` (never `git add -A`/`.`;
  preserve pre-existing changes to `docs/AGENTS.md` and `agent_workflow_guidelines.md`). Message:
  `docs: add root-cause principle catalog draft (#17-#25) for cross-incident recall`.

### Task 2: Create the `generalize` skill

Files:
- `~/Projects/myrepos/ai-playbook/agents/skills/generalize/SKILL.md` *(new)*
- `~/Projects/myrepos/ai-playbook/agents/skills/generalize/LICENSE.txt` *(new)*

- [x] Create `agents/skills/generalize/` modeled on `agents/skills/premortem/` (Core Concept, When to
  Use, phase-based Process, Integration Points, Anti-Patterns, Standalone Invocation).
- [x] Frontmatter: `name: generalize`; `description:` one paragraph covering both modes and the When-to-Use
  trigger (capturing/reviewing a lesson with `learn`, or auditing a bloated lessons corpus).
- [x] Core Concept: recall by problem shape; the catalog (`coding_guidelines.md` #17+) is the family
  authority; the incident is always kept as the witness.
- [x] `map` mode Process (one incident/lesson): (1) strip the incident-specific skin; (2) name the
  root-cause family from the catalog (or propose a new family, curated not auto); (3) write the shape
  trigger; (4) keep the concrete incident as witness; (5) check for an existing same-family lesson,
  resolving via the repo's `principle-index.md` when present (O(1) lookup) and falling back to a corpus
  scan only if the index is absent; prefer cross-ref over a new entry.
- [x] `audit` mode Process (a corpus): (1) require unique lesson numbers as a precondition (run the
  `uniq -d` gate; abort with guidance if duplicates exist); (2) map every lesson to a family; (3) cluster;
  (4) classify each cluster as true-duplicate (fully redundant) vs overlapping (same family, distinct
  angle); (5) emit a consolidation map (which lessons collapse to which canonical number, preserving
  numbers per invariant 2) and a blind-spot analysis (over- and under-represented families).
- [x] Integration Points: `### With learn` (learn's Generalization pass calls `map`; link
  `../learn/SKILL.md`); `### With plans` (a plan's pre-computation checks may name the family; link
  `../plans/SKILL.md`); `### With review-agents` (premortem/quality lenses may cite the family).
- [x] Anti-Patterns: principle theater (no witness); over-clustering (forcing distinct lessons together);
  renumbering during consolidation; auto-generating families; collapsing an overlapping-but-distinct lesson.
- [x] Resolve shared docs via the `shared_docs_dir` USER-facts key (skills run under user context; this
  key is NOT present in per-repo facts); never hardcode paths.
- [x] Copy `LICENSE.txt` from `agents/skills/plans/LICENSE.txt`.
- [x] Verify: command #3 passes (frontmatter, LICENSE, Integration Points); command #1 clean.
- [x] Commit: stage ONLY `agents/skills/generalize/` (never `git add -A`/`.`), or via
  `~/.agents/scripts/commit-skills.sh`. Message:
  `feat(skill): add generalize skill (map incident to principle family; audit corpus)`.

### Task 3: Strengthen the `learn` Generalization pass

Files:
- `~/Projects/myrepos/ai-playbook/agents/skills/learn/SKILL.md` (canonical; `~/.agents/skills/learn/SKILL.md`
  resolves to the same file via the `~/.agents` mount)

- [x] Confirm `~/.agents/skills/learn/SKILL.md` and the ai-playbook canonical are the same file (same
  inode) before editing. Edit at the canonical path.
- [x] In the `### Generalization pass` subsection (currently steps 1 to 6, lines ~60 to 76), insert a
  new requirement between current step 1 ("Identify the abstract principle") and step 2. Before:
  "1. **Identify the abstract principle** behind the specific incident. Ask: 'What is the underlying
  pattern, independent of this particular technology, file, or module?'"
  After: keep step 1, then add "1b. **Name the root-cause family and the shape trigger.** Identify which
  family in the principle catalog (`coding_guidelines.md` #17+) this incident belongs to, and write the
  *shape trigger*: the situation (independent of this file/module) that should make a future reader
  suspect this family. If no family fits, propose one to the catalog rather than leaving the lesson
  unanchored. See the `generalize` skill (`../generalize/SKILL.md`) for the map procedure."
- [x] Update the step-3 duplicate check ("Check whether the generalized rule already exists") to also
  say: check whether an existing same-family lesson already covers this shape; if so, add only the
  missing witness and cross-link rather than creating a near-duplicate.
- [x] Keep `learn` language- and agent-agnostic; no hardcoded paths.
- [x] Verify: command #4 passes (family + shape trigger + catalog + generalize refs present); command #1
  clean; the skill still loads (frontmatter intact).
- [x] Commit: via `~/.agents/scripts/commit-skills.sh` (or stage ONLY `agents/skills/learn/SKILL.md`;
  never `git add -A`/`.`). Message:
  `feat(skill): learn generalization pass must name principle family + shape trigger`.

## Phase B: Apply to the corpus (data-driven; gated on Tasks 2 and 4)

> Phase B sizes itself to the audit output. If the audit reveals a large or contentious merge set,
> split Tasks 5 to 7 into a dedicated follow-on plan after Phase A is committed (see ## Monitor).

### Task 4: Resolve duplicate lesson numbers (precondition for the audit)

Files:
- `docs/maintenance/development_lessons.md`

- [x] Run command #7 and confirm the only collisions are `#15`, `#16`, `#17`. These are DISTINCT lessons
  that reused an existing number, not duplicates of each other, so renumber (do not merge). The pairs
  (verified at lines ~105/110/114 first vs ~119/124/129 second) and the disambiguating keywords:

  | # | First occurrence (number stays) | Second occurrence (renumber to) | Keywords that mean the SECOND |
  |---|----------------------------------|---------------------------------|-------------------------------|
  | 15 | Excel/openpyxl Column Width | Post-Extraction Cleanup -> #137 | post-extraction, cleanup, orphan |
  | 16 | Test Real Behavior, Not Implementation Details | Aggregation Logic: Test Both Directions -> #138 | aggregation, both directions, ascending, descending |
  | 17 | Test CSV Data Construction: Column Alignment | Operator Mapping Field Semantics -> #139 | operator mapping, service_start_date, valid_from |

- [x] Renumber the second of each colliding pair to the next free numbers (`#137`, `#138`, `#139`),
  preserving the order above, so every `## N.` is unique.
- [x] Re-point cross-refs concretely (not "by context" alone): grep every `#15`, `#16`, `#17` ref in
  `development_lessons.md`, `plan_quality_guidelines.md`, `AGENTS.md`/`CLAUDE.md`, and `docs/maintenance/`
  guidelines. For each ref, decide FIRST vs SECOND using the keyword table above plus the lesson title:
  if the ref's surrounding text carries a second-occurrence keyword, re-point it to #137/#138/#139;
  otherwise it refers to the first occurrence and stays #15/#16/#17. Record the re-pointed-ref COUNT per
  number in the commit body so the change is auditable.
- [x] Verify: command #7 output is empty; command #5 reports no DANGLING.
- [x] Commit (tax-reporting): stage `docs/maintenance/development_lessons.md` (and any files whose refs
  were re-pointed). Message:
  `docs: resolve duplicate lesson numbers #15/#16/#17 (renumber second occurrences to #137-#139)`. Body:
  the re-pointed-ref count per number (e.g. "#17: 1 ref re-pointed to #139").
  *(Committed 071f59f; learn added #140 on cross-ref disambiguation; ai-playbook untouched.)*

### Task 5: Run `generalize audit`; finalize the catalog; produce the blind-spot report

Files:
- `docs/maintenance/principle-index.md` *(new)*
- `~/Projects/myrepos/ai-playbook/projects/.ai-playbook/coding_guidelines.md` (finalize)

- [x] Run the `generalize` skill's `audit` mode on `docs/maintenance/development_lessons.md` (unique
  numbers now guaranteed by Task 4).
- [x] Produce `principle-index.md` containing: (a) a family-to-lesson-numbers map for all 8 families,
  written as `Lesson #N` lists so command #5 validates the index's own references; (b) the excluded set
  (tool-quirk + domain-specific lessons) with one-line reasons; (c) duplicate clusters, each classified
  true-duplicate vs overlapping, with the recommended canonical number; (d) blind-spot analysis (over-
  and under-represented families).
- [x] Dry-run recall check (Evaluation: recall-by-shape): take 2 to 3 synthetic incidents in fresh
  modules and confirm the catalog's shape triggers recall the right family. If any trigger is too vague,
  tighten the catalog now (this is the allowed Task 1 revision).
- [x] Precision review gate on the consolidation map (Evaluation: cluster precision): the true-duplicate
  list gets a second pass (human approval or a fresh-agent challenge) confirming each cluster is genuinely
  fully redundant, not a distinct angle. Do NOT proceed to Task 6 until every true-duplicate cluster is
  confirmed. Record the gate result in `principle-index.md`.
- [x] Verify every non-excluded lesson maps to exactly one family (no orphans); command #6 passes.
- [x] Re-commit the catalog authoritative: apply any shape-trigger tightenings from the dry-run and
  finalize the family anchor sets in `coding_guidelines.md`; drop the DRAFT marker from the umbrella
  section. Commit (ai-playbook), staging ONLY that file. Message:
  `docs: finalize principle catalog (#17-#25) after generalize audit`.
  *(Committed a6be2e9; learn found no new lesson (precision-gate tie-breaker already in generalize skill); no anchor re-pointed; #41/#91 reclassified OVERLAPPING.)*
- [x] Commit (tax-reporting): stage `docs/maintenance/principle-index.md`. Message:
  `docs: add principle index + blind-spot report from generalize audit`.
  *(Committed 33eec23; learn found no new lesson (precision-gate tie-breaker already in generalize skill); docs-branch integrity gate PASS; file-scoped em-dash used because of pre-existing crypto-payment-proceeds WIP em-dashes.)*

### Task 5b: Upgrade `generalize` skill with atom-level cross-family dedup (inserted mid-run)

*Inserted during execution. After the precision gate (Task 5) and an atom-extraction re-audit
revealed a structural blind spot: `audit` Phase 3 clusters lessons BY FAMILY, so Phase 4 only
compares within-family and cannot see a shared atomic principle whose lessons have different
PRIMARY families. Witness: lesson #81 (Family E) bundles a column-coupling bullet that fully
restates lesson #82 (Family D); family-clustering never compared them. The atom-extraction pass
also confirmed the corpus is near-atomic (~2% shared-atom ratio; 3 shared atoms total). User
chose "upgrade the skill first" before the corpus collapses.*

Files:
- `~/Projects/myrepos/ai-playbook/agents/skills/generalize/SKILL.md`

- [x] Add a Phase 4b to `audit` mode: **atom-level, family-agnostic dedup.** Decompose each lesson
  into its atomic principle(s) (1-3 per lesson; most yield 1); dedupe across the WHOLE corpus (not
  within-family) using the sharp bar (same actionable rule; different incident or family is NOT
  sufficient); flag every atom stated in 2+ lessons, distinguishing intra-family shares (Phase 4
  should have caught them; if it classified them overlapping, reclassify as true-duplicate) from
  cross-family shares (Phase 4 structurally could not see them; extract the shared atom to one
  canonical home, trim each lesson to its distinct residue). Cite the #81/#82 witness. Note most
  corpora are near-atomic, so this is a safety net, not the primary lever; do not over-merge.
- [x] Refine Phase 4's classification to distinguish **overlapping** (different atoms in the same
  family; siblings, keep both) from **contrasting** (same family/topic, OPPOSITE prescriptions:
  e.g. "siblings must be byte-identical" vs "callers must intentionally diverge"; related but
  neither duplicate nor overlapping; cross-link with a "distinguishing from" note, not See-also).
- [x] Add an Anti-Pattern: "Family-clustered-only audit misses cross-family shared atoms": always
  run the atom-level family-agnostic pass after family-clustering.
- [x] Verify: skill structure intact (modes, phases, anti-patterns read coherently); em-dash clean
  (file-scoped gate). [verified: phases 1,2,3,4,4b,5 in order; both witnesses #81/#82 & #119/#136
  cited; anti-pattern row present; Core Concept bullet updated; `check-no-em-dash.sh file` exit 0]
- [x] Commit (ai-playbook), staging ONLY `generalize/SKILL.md`. Message:
  `feat(skill): generalize audit gains atom-level cross-family dedup (Phase 4b)`.
  [done: ai-playbook commit a8c7602; staged only the skill file; em-dash `file` gate exit 0;
  no trailer; not pushed]
- [x] Formally RUN the committed Phase 4b on the 140-lesson corpus (read-only audit sub-agent) to
  validate the phase and lock the authoritative duplicate set. [done; validation verdict YES: Phase 4b
  caught the #81(Family E)/#82(Family D) cross-family shared atom invisible to family-clustering.
  Refined the duplicate set to **0 collapses; 1 cross-family extraction** (#81 bullet -> #82): the
  audit applied the sharp bar and refuted the prior empirical pass's #59/#1 and #58/#23 as
  true-duplicates (distinct-atom siblings, kept overlapping); #83/#84 also kept overlapping. The
  principle-index.md documentation of this atom-level pass folds into Task 6's finalize clause
  (avoids a redundant second touch to the same file). Task 6 header + clauses revised accordingly.]

### Task 6: Consolidate the corpus (merge confirmed true duplicates; tag the rest)

*Revised twice mid-run. First revision (empirical atom-extraction) expected 3 true-duplicates
(#59 -> #1, #58 -> #23, #81's column-coupling bullet -> #82). Second revision (Task 5b formal
Phase 4b run, independent read-only audit applying the sharp bar "same ACTION, not same
technique") **refuted #59/#1 and #58/#23 as true-duplicates**: they share the grep / track-docs
TECHNIQUE but prescribe distinct actions (#1 build-collision error vs #59 silent data-member
coalescence; #23 field-level registry drift vs #58 structure-level module-layout drift). Both
stay OVERLAPPING. #83/#84 (test-the-off-state) also stay OVERLAPPING (value-shape vs behavioral
equivalence). Net confirmed set: **0 collapses; 1 cross-family extraction** (#81 Family E
column-coupling bullet verbatim-restates #82 Family D; the case family-clustering was
structurally blind to; trim the bullet from #81, leave #82 as canonical; #81's primary atom
priority-ordering survives). The "overlapping cluster" frame stands: most are
same-family-different-atom siblings (not partial-duplicates); #119/#136 are contrasting
(opposite prescriptions). Tag all non-excluded lessons.*

Files:
- `docs/maintenance/development_lessons.md`
- `docs/maintenance/principle-index.md` (finalize to post-consolidation state)

- [x] CROSS-FAMILY EXTRACTION (the one confirmed action from Task 5b formal Phase 4b): in #81
  (Family E), remove ONLY the "When adding columns, update the column count constant AND the
  conditional formatting loop range" bullet from its `Implementation notes` (it verbatim-restates
  #82 Family D). Leave #81's primary atom (conditional-formatting priority ordering) fully intact;
  leave #82 unchanged (it is the canonical home). Do NOT delete the #81 heading, do NOT renumber.
- [x] Sequence by family, dominant first (A coverage, then H verify-the-real-thing), then the rest.
- [x] For each TRUE-DUPLICATE cluster: keep the lowest-numbered lesson as canonical, add a
  `**Principle:** <Family>` line to it, and replace each duplicate's body with a redirect that
  PRESERVES its number (e.g. "Merged into #N (same principle: <Family>); see also #M."). Do not
  delete the heading or renumber. NOTE: the Task 5b formal Phase 4b run confirmed **0 true-duplicate
  clusters** (#59/#1, #58/#23, #83/#84 all reclassified OVERLAPPING (see header)), so this clause is
  expected to be vacuous this run; kept as the procedure in case the witness-preservation check below
  flips a pair.
- [x] Witness-preservation check (per cluster): before rewriting a duplicate's body, `grep -oE` its
  distinctive keywords and assert each appears in the canonical target's post-merge body. If a term
  appears ONLY in the duplicate, the cluster is NOT a true duplicate; reclassify it IN PLACE as
  OVERLAPPING (do not collapse it: keep its body, add a `**Principle:** <Family>` line and a See-also to
  the canonical lesson) and note the reclassification in the commit body.
- [x] For each OVERLAPPING lesson (same family, distinct angle): keep the body, add a
  `**Principle:** <Family>` line, and add a See-also cross-link to the cluster's canonical lesson.
- [x] For excluded (tool-quirk/domain) lessons: leave untouched.
- [x] Update every cross-ref that pointed to a collapsed duplicate to mention the canonical number too
  (in `development_lessons.md`, `plan_quality_guidelines.md`, `AGENTS.md`).
- [x] Finalize `principle-index.md`: relabel executed true-duplicate clusters as "merged to #N (redirect
  at #M)"; keep overlapping clusters listed with their See-also links; remove now-stale "recommended
  canonical" annotations. The index must describe post-merge state.
- [x] Verify: command #5 passes (no dangling LESSON ref); command #7 still empty; command #1 clean; diff
  review confirms no witness lost and no renumber.
- [x] Commit (tax-reporting): stage `docs/maintenance/development_lessons.md` and `principle-index.md`.
  Message: `docs: consolidate duplicate lessons and tag corpus with principle families`.
  [done (tax-reporting commit a1a7ba6 + the revised plan file; em-dash `file` gate exit 0 on all
  three; no trailer; not pushed; learn: no new lesson (candidates are skill-scope)]

### Task 7: Cross-reference wiring

Files:
- `docs/maintenance/plan_quality_guidelines.md`
- `AGENTS.md` (tax-reporting; `CLAUDE.md` is the symlink target)

- [x] In `plan_quality_guidelines.md`, add a short pointer to the principle catalog and the index (e.g.
  a line under "Pre-Computation Bug Pattern Checks" or a new short subsection) so plan authors can name
  a family when a pattern check fires.
- [x] In tax-reporting `AGENTS.md` (Domain Knowledge References area), add a pointer to
  `docs/maintenance/principle-index.md` and the catalog so agents discover the family map when touching
  crypto/reporting logic.
- [x] Keep both edits em-dash-free and style-matched.
- [x] Verify: command #1 clean; both new pointers resolve. [em-dash `file` gate exit 0 on both;
  principle-index.md exists; catalog referenced as coding_guidelines.md #17-#25; command #5
  0 dangling, max ref 140]
- [x] Commit (tax-reporting): stage the two files. Message:
  `docs: wire principle catalog + index from plan-quality and AGENTS references`.
  [done: tax-reporting commit c13c3e9, plus the plan file; a stray em-dash in the Task 6 annotation
  was scrubbed; em-dash `file` gate exit 0; no trailer; not pushed; learn: no new lesson]

## Monitor

- **Phase B may split.** Tasks 5 to 7 are data-driven by the audit and touch canonical docs heavily. If
  the audit reveals a large or contentious merge set (heightened by the Task 4 duplicate-resolution
  work), stop after Phase A (Tasks 1 to 3) plus Task 4 is committed and open a dedicated consolidation
  plan that references this plan's invariants. Owner: this plan (re-open or fork).
- **`docs/AGENTS.md` (ai-playbook) index line deferred.** The existing index entry for
  `coding_guidelines.md` already makes `#17+` discoverable; a more specific line is deferred to avoid
  entangling with the pre-existing uncommitted changes there. Owner: a future ai-playbook docs pass,
  coordinated when those pre-existing changes are resolved.
- **Catalog drift.** New families should be proposed through `generalize` (map mode, "propose a family")
  and curated, not appended ad hoc. Re-run `audit` periodically to catch new duplicates. Owner: the
  `learn`/`generalize` workflow itself.
