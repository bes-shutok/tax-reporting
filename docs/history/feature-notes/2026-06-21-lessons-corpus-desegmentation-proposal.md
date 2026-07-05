# Proposal: Desegment the Lessons Corpus into Cohesive Per-Family Files

- **Status:** SUPERSEDED. The literal design proposed here (desegment into cohesive per-family files) was **not** adopted. A different approach shipped via plan [2026-06-29-lessons-corpus-derived-index.md](../plans/completed/2026-06-29-lessons-corpus-derived-index.md) (commit `fc2a136`): a two-layer corpus (cross-project lessons promoted to the user-level corpus, project-specific lessons retained in a single `development_lessons.md` with greppable in-band family tags) and the hand-maintained `principle-index.md` replaced by a source-derived grep index. Kept as a record of the design explored and rejected. (Original status: PROPOSAL / NOT YET ADOPTED, written after the principle-generalization-system run produced the family catalog, the `generalize` skill, and `principle-index.md`.)
- **Date:** 2026-06-21
- **Related:**
  - Plan: [2026-06-21-principle-generalization-system.md](../plans/completed/2026-06-21-principle-generalization-system.md)
  - Index: [principle-index.md](../../maintenance/principle-index.md)
  - Catalog: `coding_guidelines.md` #17-#25 (under `shared_docs_dir`)
  - Skill: `generalize` (audit/map modes; Phase 4b atom-level pass)

---

## 1. Executive Summary

`docs/maintenance/development_lessons.md` is a single 2,387-line file holding 140 lessons. The
principle-generalization-system run already mapped every non-excluded lesson to one of eight
root-cause families (A to H) in `principle-index.md` and tagged each lesson inline with its
family. Reading a whole family, however, still means jumping between scattered `#N` entries,
each carrying its own repeated setup and framing.

This proposal explores **desegmenting** the corpus: reorganizing the lessons into cohesive
per-family files so that all of Family A reads as one chapter, with shared framing hoisted into a
family intro and per-lesson repetition trimmed. The desegmentation goal is editorial (a tighter,
more readable corpus), **not** consolidation: the formal Phase 4b atom-level audit found the
corpus near-atomic with **zero** true-duplicates to merge, and the numbering is already clean
(1 to 140, contiguous, no gaps).

Two options are presented, differing only in **numbering**:

- **Option A: Desegment, keep `#N`.** Preserve the global lesson number as a stable anchor.
- **Option B: Desegment and renumber.** Renumber sequentially within each family file.

Section 4 gives each option's plusses and minuses; Section 5 is a side-by-side table; Section 6
recommends Option A.

---

## 2. Context and Motivation

### 2.1 The consolidation question is settled

The principle-generalization-system plan was motivated by a hypothesis that the corpus held many
under-generalized near-duplicates. Two audits settled this:

- **Family-clustered pass (Phase 3/4):** classified every same-family pair. A fresh-agent
  precision gate overturned the one true-duplicate candidate (#41/#91) to OVERLAPPING.
  Result: zero confirmed true-duplicates.
- **Atom-level pass (Phase 4b):** decomposed every mapped lesson into its atomic principle and
  deduped family-agnostically. It caught one cross-family shared atom (#81's column-coupling
  bullet restating #82) that family-clustering was blind to. Net: **zero collapses; one
  cross-family bullet extraction.**

The corpus is near-atomic (shared-atom ratio about 3.6%). The numbering is already correct:
1 to 140, contiguous, no duplicates (`uniq -d` empty). There is nothing left to "consolidate
with correct numbering."

### 2.2 The remaining value is editorial

What the tagging and index did **not** deliver is cohesion. Each lesson still stands alone with
its own project context, preamble, and restated framing. When a maintainer wants to learn, say,
all the "verify the real thing, not the abstraction" lessons (Family H, 32 lessons), they must
open 32 scattered entries and re-read overlapping setup prose. Desegmentation addresses exactly
this: hoist the shared framing into a family intro, trim the per-lesson repetition, and let each
family read as a flowing chapter.

---

## 3. Current State (measured)

- `development_lessons.md`: 2,387 lines, 140 lessons (111 mapped to families A to H; 29
  excluded as tool-quirk, style, process, or domain-specific).
- Family distribution: A 19, B 6, C 7, D 18, E 10, F 7, G 12, H 32.
- `principle-index.md` (662 lines) already holds the authoritative family-to-lessons map and the
  excluded set.
- Cross-reference load: **514 lesson-reference occurrences** across **8 files** (AGENTS.md,
  crypto_implementation_guidelines.md, crypto_reporting_guidelines.md,
  development_lessons.md, plan_quality_guidelines.md, principle-index.md, project-guidelines.md,
  tax_reporting_guidelines.md). These references use `#N` as the stable key.

---

## 4. The Two Options

Both options share the same editorial work: split into family files, write a family intro, hoist
shared framing, trim per-lesson repetition, preserve every witness (concrete incident/failure),
and keep cross-family links. They differ only in whether the lesson number stays global.

### 4.1 Option A: Desegment, keep `#N` (recommended)

**Structure.** A new directory `docs/maintenance/lessons/` with one file per family
(`a-equivalence-coverage.md` through `h-verify-the-real-thing.md`) plus `excluded.md` for the 29
tool/domain lessons. Each family file opens with a repo-specific intro (precept, failure
signature, shape trigger, adapted from `coding_guidelines.md` #18-#25), followed by an ordered
mini-TOC of that family's `#N` lessons, then the lessons themselves, each keeping its
`## N. Title` heading. `development_lessons.md` becomes a thin dispatcher; `principle-index.md`
gains the `#N -> file` mapping (it already lists each family's numbers, so it only needs the file
path added).

**Plusses.**

- The 514 cross-references stay valid untouched: `#N` remains the stable namespace that
  CLAUDE.md / AGENTS.md / the guidelines depend on.
- No renumber risk: no dangling pointers, no redirect map to maintain, no verification scramble.
- Full desegmentation benefit (hoisted framing, trimmed repetition, cohesive chapter-like read).
- The "view by family" desire is satisfied two ways without sequential numbering: each family
  file's intro carries an ordered mini-TOC, and `principle-index.md` lists every family's lessons
  in order.

**Minuses.**

- The `#N` values within a family file are not sequential (Family A reads #6, #7, #22, #41, ...).
  This is cosmetic; the mini-TOC and index make navigation trivial.
- A reader following a bare `#N` resolves it via `principle-index.md` (the dispatcher) rather than
  by grepping one file, a slightly more indirect resolution path.
- The minority of references that name the file explicitly (`development_lessons.md #42`) need
  repointing to the family file (or left to resolve via the dispatcher). Most references are bare
  `#N` and need no change.
- More files to maintain than one monolith (eight family files plus the excluded file).

### 4.2 Option B: Desegment and renumber

**Structure.** Same family-file layout as Option A, but each family's lessons are renumbered
sequentially (Family A becomes 1-19, Family B becomes 1-6, and so on), and the excluded lessons
get their own file/numbering. The global `#N` namespace is retired in favor of per-family
sequences (identified by file).

**Plusses.**

- Clean, sequential numbering within each family file: Family A reads 1, 2, 3, ..., 19 with no
  gaps and no scattered values. Maximally cohesive on the page.
- A fully self-contained per-family numbering scheme.

**Minuses.**

- Breaks all 514 cross-references across 8 files. Every `#N` in CLAUDE.md, AGENTS.md, the five
  guidelines, the corpus, and the index must be found and rewritten to the new per-family
  identifier. A single missed reference is a dangling pointer that silently misleads.
- Retires the stable `#N` namespace the repository's instruction files already depend on; future
  cross-references become file-relative, which is harder to write and to grep.
- Requires an old-to-new redirect map and a full re-verification pass (command #5 dangling-ref
  gate) across every referencing file, which is the highest-risk, highest-effort path.
- Not justified by consolidation: the audit found nothing to merge, so renumbering buys only the
  sequential-numbering cosmetics, not a cleaner consolidation.
- Cross-family references (a Family A lesson citing a Family D lesson) now span files and number
  spaces, adding resolution indirection anyway.

---

## 5. Side-by-Side Trade-Off

| Dimension | Option A: keep `#N` | Option B: renumber |
|---|---|---|
| Cross-reference breakage | None (514 refs untouched) | All 514 across 8 files |
| Stable namespace preserved | Yes | No (retired) |
| Desegmentation benefit (cohesion) | Full | Full |
| Sequential numbering in-file | No (cosmetic mini-TOC instead) | Yes |
| Redirect map needed | No | Yes |
| Verification burden | Low | High (re-verify all refs) |
| Risk of silent dangling refs | Low | High |
| Maintenance surface | 8 family files + index | 8 family files + index + redirect map |

---

## 6. Recommendation

**Option A (desegment, keep `#N`).** The desegmentation value (hoisted framing, trimmed
repetition, cohesive family chapters) is entirely editorial and is delivered identically by both
options. Only Option B pays the 514-reference cost, and it pays that cost for a purely cosmetic
gain (sequential numbers), with no consolidation to justify it. The stable `#N` namespace is an
asset worth preserving; sequential numbering within a family is already provided by the mini-TOC
and by `principle-index.md`. Option A is lower risk, lower effort, and equal benefit.

---

## 7. Open Design Questions (to resolve if adopted)

- **Trimming aggressiveness.** Conservative (hoist only clearly-shared framing such as the
  family precept, repeated project context, and restated shape triggers; never trim the witness)
  is the safe default. Aggressive (also tighten verbose per-lesson prose and merge near-duplicate
  explanations within a family) yields a tighter read but raises the risk of losing nuance and
  needs careful per-family diff review.
- **Family intro source.** Adapt from `coding_guidelines.md` #18-#25 (repo-agnostic precept,
  failure signature, shape trigger), localized to this repo's incidents. The catalog stays the
  cross-project authority; the family-file intro is the repo-specific view.
- **Dispatcher.** `development_lessons.md` becomes a thin index pointing to the family files
  (preserving the well-known path), while `principle-index.md` becomes the authoritative
  `#N -> file` resolver. Alternatively, retire `development_lessons.md` entirely and let
  `principle-index.md` be the single entry point.
- **Execution order.** Per-family sub-agent passes (eight), each reading one family's lessons and
  intro and writing one cohesive file, so context stays manageable and each family verifies
  before the next.
- **Excluded lessons.** The 29 tool/domain lessons go into `excluded.md`, grouped by kind
  (tool-quirk, style, process, domain), without family intros.
- **Verification.** Every `#N` from 1 to 140 present exactly once across the family files; no
  witness content lost (diff review per family against the pre-desegmentation file); command #5
  cross-refs resolve; em-dash gate clean; the inline `**Principle:**` tags are dropped (the file
  is the family).

---

## 8. Status and Next Steps

This is a proposal only; it has not been executed. The principle-generalization-system run
delivered the catalog, the `generalize` skill (with the Phase 4b atom-level pass), the
`learn` generalization tweak, the dedup audit, and the tagged, cross-linked corpus with
`principle-index.md`. Desegmentation is a separate, optional restructure to be adopted (as
Option A or B) in a dedicated follow-up plan if and when the cohesion benefit is worth the
editorial effort. The next step, if adopted, is to write a focused desegmentation plan with
per-family tasks and the validation commands above, then execute it.
