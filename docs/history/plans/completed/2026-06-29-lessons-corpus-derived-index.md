# Plan: Two-Layer Lessons Corpus (strict user-level + convention project-level) + Migration Skill

Supersedes: `docs/history/feature-notes/2026-06-21-lessons-corpus-desegregation-proposal.md`.
Prior phase: `docs/history/plans/completed/2026-06-21-principle-generalization-system.md`.

**Reworked r1 (hybrid two-layer design).** This is the third design iteration. Legacy review rounds are preserved: `…-legacy-r1.md` through `…-legacy-r6.md` validated the single-repo design; `…-legacy-r7.md` / `…-legacy-r8.md` validated the both-tiers-cross-project design (last verdict `ready=yes`). They collectively validated the **gate-design core this plan inherits unchanged** (read-only validator, `VALID_FAMILIES` documented constant, fence-aware tag counting, cold-start policy, `.tmp`+`os.replace` adopter, drift precheck). Per the plans skill, a substantive scope change resets the review counter to r1.

**What changed (v3 hybrid).** Two independent layers with *different* strictness:
1. **User-level corpus** (strict, Option C): mandatory one-family-tag-per-lesson; a gate enforces duplicate `UL#N` + exactly-one-tag + valid-family; `learn` Step 6.6 hard-blocks. This is the AI's trusted cross-project memory.
2. **Project files** (convention, the "fourth option"): plain markdown, valid with **no** skill present; `learn`/`generalize` still write family tags as a convention (best-effort in-project recall for AI) but nothing enforces them; duplicate-`#N` is an optional warn-only grep one-liner. Each project is fully independent of the gate, the user corpus, and other repos.
3. **A migration skill** (`lessons-migrate` + `lessons_migrate.py`), run once per repo, heuristic + flag: splits lessons cross-project vs project-specific, compact-renumbers both files, rewrites in-repo `#N` references from the remap, dedups against the user corpus, deletes `principle-index.md`, self-checks via the gate.

**Why this split.** The motivating defects were (a) `principle-index.md` drift, (b) a user-level skill (`plans`) citing a repo-local `#N` (a Family-F layering violation), and (c) the both-tiers design coupled every project's data to a skill-enforced gate. The hybrid fixes all three: strictness lives only on the shared authority (user level), so the user enjoys strictness locally without forcing it on any project; consumers are AI agents that recall by family, so the shared authority guarantees family grouping while project files provide best-effort recall.

## Terms

- **Two-layer model.** (1) **User-level corpus** - the cross-project concrete-lessons home, strict; (2) **project lessons file** - one per repo, convention. Plus the user-level *catalog* (`coding_guidelines.md` #17 container + #18-#25 the eight families A-H), the authority for the family set, inherited by both layers. The two lesson layers are **independent**: independent numbering, and cross-references stay within-layer BY NAMESPACE (user instructions cite `UL#N`; project instructions cite project `#N`; a project reference to a lesson that moved to the user corpus is REMOVED on migration - never `UL#N`). Both layers are loaded into the agent's context, so removing a cross-tier in-repo pointer does not lose discoverability: the moved lesson remains reachable via the user corpus.
- **User-level corpus.** `shared_docs_dir/development_lessons.md` (resolved from `.ai-playbook/facts.md` via the lowercase `shared_docs_dir` key - NOT an env var; currently `~/Projects/myrepos/ai-playbook/projects/.ai-playbook/development_lessons.md`, where `coding_guidelines.md` also lives). Owns its `UL#N` namespace. **Strict**: every lesson carries exactly one well-formed family tag; the gate enforces it. Created/populated by the migration skill and by future cross-project captures. (The hardcoded path in this plan reflects the current `shared_docs_dir` resolution; at runtime resolve the path from the facts key or use the `${HOME}/Projects/.ai-playbook/` symlink - there is no `SHARED_DOCS_DIR` env var, r3 B2.)
- **Project lessons file.** `docs/maintenance/development_lessons.md` (one per repo). Owns its `#N` namespace. **Convention**: `learn`/`generalize` write family tags but nothing enforces them; the file is plain markdown, structurally valid with no skill, gate, or user corpus present.
- **Routing rule (capture time).** In `learn`/`generalize`, the scope-decision fork is: **abstract precept** (short normative rule) -> `coding_guidelines.md` (catalog); **concrete cross-project lesson** (incident witness, generalized rule + example, correct in any project) -> **user-level corpus** (strict-tagged, next `UL#N`); **project-specific lesson** (depends on domain context: crypto/FIFO/tax/IB/Koinly) -> **project file** (convention-tagged). The abstract-vs-concrete test is the primary fork; "any project" is the secondary test.
- **Family tag.** The in-band line `**Principle:** Family <X> (<free-text reason>)` written by `learn`/`generalize`. `<X>` is one of: a single letter `A`-H (the eight families in `coding_guidelines.md` #18-#25), the literal `excluded`, or the literal `unclassified`. The parenthetical is mandatory free-text, ignored by the gate. Exactly one tag per lesson. **Mandatory + enforced at user level; conventional + unenforced at project level.** Same format both layers.
- **Gate.** `lessons_index.py` - a **read-only**, **single-file** validator (takes the user corpus path; project files are NOT gated). Enforces user-corpus invariants. Never writes. (The adoption mutator `lessons_adopt.py` and the migration script `lessons_migrate.py` are the only writers.)
- **Migration skill.** `lessons-migrate` (a user-level skill, `~/.agents/skills/lessons-migrate/SKILL.md`) backed by `lessons_migrate.py`. Run **once per repo**. Heuristic + flag: splits lessons, renumbers, remaps refs, dedups, deletes the index, self-checks.
- **Compact renumber.** On migration, each file is renumbered `1..N` contiguously (gaps like the historical #163/#164, where both numbers are absent, collapse). A remap table (old `#N` -> new `#N`) drives rewriting in-repo references across code, tests, and docs. Renumbering is an accepted cost (the user authorized it).
- **Catalog.** `coding_guidelines.md` #17-#25 (under `shared_docs_dir`) - the user-level authority for A-H, inherited by both layers.

## Gist & Examples

**Problem (three defects, one root cause).** (a) `docs/maintenance/principle-index.md` drifts: written 2026-06-21 against a then-smaller corpus, it now covers only **148 of 198 lessons** (it references numbers up to #197 but misses ~50) while the source has **198 headings (max #200; #163/#164 historical gaps, both absent; zero duplicates)** - the repo's own Family D lesson biting the repo. (b) A user-level skill (`plans`) cited a repo-local `#N` - a Family-F layering violation with no user-level concrete home to point to. (c) The both-tiers design forced every project's lessons file to depend on a skill-enforced gate, coupling project data to skills. Root cause: no user-level concrete-lessons home, and no clean separation of "shared authority" from "independent project memory."

**Insight.** Consumers are **AI agents** (generalize, plans, learn), not humans - they recall lessons by family routinely. So trustworthy family grouping is genuinely useful, but only the **shared authority** needs to *guarantee* it; project files can provide best-effort recall without enforcement. That splits strictness cleanly: strict at user level, convention at project level.

**Change.** (1) **User-level corpus** (strict): mandatory tags, gate-enforced; AI skills consult it with full trust. (2) **Project files** (convention): plain markdown, tags written but unenforced, valid standalone - each project independent. (3) **Migration skill**, one-time per repo, splits + compact-renumbers + remaps refs + dedups + deletes the index. (4) tax-reporting is the first run.

**What the gate enforces (user corpus only).** Hard violations (exit 1): a duplicate `UL#N` (silent-overwrite hazard, lesson #77); a lesson with zero or >1 family tag (counted outside fenced code blocks); a tag whose `<X>` is not `A`-H/`excluded`/`unclassified`. Informational (exit 0): none (compact renumber removes gaps). The gate never forces renumbering post-migration. Project files are NOT validated by the gate.

**Single source of truth, applied to the gate itself.** The gate's valid family set is a named constant (`VALID_FAMILIES = frozenset("ABCDEFGH")`) with a code comment naming `coding_guidelines.md` #17-#25 as its authority. There is NO automated catalog-vs-constant check: catalog growth surfaces **visibly** - the first lesson tagged with a new family letter is rejected by the gate with an `invalid-family` message, prompting an explicit cross-project update of both the catalog and the constant together (the opposite of a silent wrong answer). A pre-emptive catalog-parse check was considered and routed to Monitor.

**Strictness trade the user accepted.** Because the user-level corpus is strict and consulted by `learn` in every project, a `learn` in project A will block if the user corpus has a violation introduced by a capture in project B. The user explicitly chose strict user-level ("for my local machine I can enjoy the strictness"); the corpus is single-user-local, so a block means "go fix the user corpus" - the desired behavior, not a hazard. Project files never block (convention).

**Migration (autodiscovery, repo-agnostic + zero-config skill).** Run once per repo. The skill is general and needs no per-repo input: its classifier is **generic-first** - a lesson with a `Family <A-H>` tag or a generic engineering shape (drawn from the family catalog) is cross-project; everything else defaults to project-specific (the safe call); low-domain-residue lessons are flagged for a short manual review. No domain keywords are baked in or curated. The skill reads the repo's current `development_lessons.md` and writes cross-project lessons into the user corpus with valid strict tags (compact `UL#N`, deduped against existing corpus lessons - near-duplicates flagged for merge, not auto-added) and project-specific lessons into the repo file (compact `#N`, convention tags preserved). It builds an old-`#N` -> new-`#N` (same-tier) or REMOVE (cross-tier) remap and rewrites `#N` references REPO-WIDE (`src/`, `tests/`, `AGENTS.md`, `docs/maintenance/`, and in-body cross-links inside the lessons file itself), flagging any ref it cannot confidently remap. It deletes `principle-index.md` and emits a frozen audit snapshot. It self-checks by running the gate on the user corpus (exit 0 required) and a stale-ref scan over the old numbers.

**Why not migrate all legacy cross-project lessons by hand.** Not needed - the migration skill automates it per repo. Other repos (sporty, other myrepos) run the same skill when ready; each run dedups against the already-populated user corpus. No per-repo hand work.

## Evaluation Criteria

**Quality dimensions:**
- Correctness: the user corpus passes the strict gate (no duplicate `UL#N`; every lesson exactly one well-formed tag); project files are well-formed markdown with contiguous `#N`; the migration skill's heuristic routes a verified test corpus correctly.
- Layering (Family F): user-level skills/docs cite `UL#N`, never a repo-local `#N`; project instructions cite project `#N` (cross-tier citations removed on migration), never `UL#N`; the gate runs only at user level.
- Independence (priority): a project's `development_lessons.md` is valid with no skill, gate, or user corpus present; removing the gate does not invalidate any project file.
- Simplicity (priority): no persistent index/intermediate file; the project tier has NO script and NO `learn` block; the gate is single-file, user-corpus-only.
- Maintainability: `learn` Step 6.6 gates the user corpus with cold-start + recovery recipe; `generalize` resolves families by grep; the migration skill is re-runnable and idempotent-ish (dedup protects the user corpus).
- Portability: the migration skill runs in any repo via cold-start; the gate works on the user corpus path.

**Release gates:**
- `python "${HOME}/.ai-playbook/scripts/lessons_index.py" "${HOME}/.ai-playbook/projects/.ai-playbook/development_lessons.md"` exits 0 (after migration).
- `python "${HOME}/.ai-playbook/scripts/lessons_index.py" --selftest` exits 0.
- `uv run pytest tests/unit/test_lessons_corpus_conformance.py -rs` reports the live user-corpus case PASSED (not SKIPPED/XFAIL) on a machine with the runtime script.
- No tracked file under `docs/`, `~/.agents/skills/`, or `~/Projects/myrepos/ai-playbook/` references `principle-index.md` (frozen history excepted).
- No user-level skill or user-level doc cites a repo-local lesson `#N` by filename (Validation Command 6; handles backtick-wrapped and bare filename forms; bare `lesson #N` without filename is a documented residual).
- The project file `docs/maintenance/development_lessons.md` is valid plain markdown with contiguous `#N` and zero references to the gate or user corpus.

## Review Scope

**Explicit must-fix:**

**User-level (playbook repo + skills repo):**
- `~/Projects/myrepos/ai-playbook/projects/.ai-playbook/development_lessons.md` *(new)* - strict user-level corpus; populated by the migration skill.
- `~/Projects/myrepos/ai-playbook/scripts/lessons_index.py` *(new)* - read-only single-file validator (canonical source of the runtime copy).
- `~/Projects/myrepos/ai-playbook/scripts/lessons_corpus.py` *(new)* - shared parser + fence collector + `VALID_FAMILIES` (imported by gate/adopter/migrator).
- `~/Projects/myrepos/ai-playbook/scripts/lessons_adopt.py` *(new)* - adoption mutator (user-corpus tag backfill; SRP).
- `~/Projects/myrepos/ai-playbook/scripts/lessons_migrate.py` *(new)* - the one-time-per-repo migration engine (split + renumber + remap + dedup + delete + self-check).
- `~/.agents/skills/lessons-migrate/SKILL.md` *(new)* - the migration skill (one-time-per-repo procedure, calls `lessons_migrate.py`).
- `~/Projects/myrepos/ai-playbook/projects/.ai-playbook/coding_guidelines.md` - repoint lines 162/190 (`principle-index.md` -> grep); add the normative "Lesson tag format" sub-section under #17 (strict at user, convention at project).
- `~/.agents/skills/learn/SKILL.md` - add Step 6.6 (gate user corpus only, blocking; project files warn-only dup grep) + the capture-time routing rule.
- `~/.agents/skills/generalize/SKILL.md` - repoint the `principle-index.md` refs (lines 124, 224, 260, 272); add the `Family excluded` mandate note at line 110 (the template bullet; r3 Low 2 - was "111"); add the routing rule.
- `~/.agents/skills/plans/SKILL.md` - rewrite the live line-466 Family-F violation (`` `development_lessons.md` #71 `` -> user corpus `UL#N` or prose); B2.

**Repo (tax-reporting) - first migration run:**
- `docs/maintenance/development_lessons.md` - rewritten by the migration skill (project-specific lessons, compact `#N`, convention tags).
- `docs/maintenance/principle-index.md` - deleted by the migration skill.
- `docs/history/feature-notes/<run-date>-principle-index-audit-snapshot.md` *(new)* - frozen audit snapshot emitted by the migration skill (run-date stamped; r2 Low 1).
- `AGENTS.md` and any repo doc with `#N` references - rewritten by the migration skill per the remap.
- `tests/unit/test_lessons_corpus_conformance.py` *(new)* - conformance test (user corpus) + project-file independence test.

**Plan-related extension:** causally related follow-ons (another doc/skill referencing `principle-index.md`; `done/SKILL.md` if its Step 6.5 cross-ref needs updating). Reference cleanup includes a repo-wide + skills-wide + playbook-wide grep.

**Out of scope:** frozen history files (rewrite not allowed); physical desegmentation (Monitor); migrating other repos (sporty/other myrepos) - each runs the skill later (Monitor); changing the catalog family set A-H.

## Design Invariants (CR Guard)

- **Two independent layers.** User-level corpus (`UL#N`, strict) and project files (`#N`, convention) are independent: independent numbering, within-layer cross-references only. The catalog (#17-#25) is the shared family authority.
- **Strictness split.** The gate is **mandatory + enforced at user level only**. Project files are **convention**: tags written but unenforced, valid with no skill/gate/corpus present. Never impose the gate on a project file.
- **Independence (priority).** A project's lessons file is plain markdown. It must not depend on the gate, the user corpus, or any skill for its validity. Removing the user-level machinery does not invalidate any project file.
- **Layering (Family F).** User-level skills/docs cite `UL#N` or self-contained prose - NEVER a repo-local `#N`. Project instructions cite project `#N`; a project reference to a lesson that moved to the user corpus is REMOVED on migration - NEVER `UL#N` (the `UL#` namespace is user-level only; r5 Option A). The within-layer rule governs NAMESPACE coupling (a project file remains valid plain markdown with no dependency on the user corpus existing). The gate runs only at user level.
- **No persistent index.** `principle-index.md` is deleted; recall is by grep on the source. No derived/tracked index file.
- **Compact renumber, remap-driven ref rewrite.** Migration renumbers each file `1..N` contiguously and rewrites in-repo `#N` references from the old->new remap, flagging unremappable refs. Renumbering is accepted.
- **Migration is heuristic + flag.** The skill auto-routes clear cases and flags ambiguous lessons (as `unclassified` at user level - passes the strict gate - for later curation). It never silently drops or duplicates a lesson: near-duplicate cross-project lessons already in the user corpus are flagged for merge, not auto-added.
- **Single source of truth (#82/#94).** Each lessons file is the authority for family assignment within its layer. The gate's `VALID_FAMILIES` *letter set* is a documented constant (single-sourced; catalog growth surfaces visibly as an `invalid-family` rejection). The migrator's per-family keyword phrase list is a **documented secondary view** of the catalog, guarded by a discriminating-token selftest (r3; was a weak overlap-selftest) - not single-sourced. The runtime copy is tied to the repo source by the Step 6.6 drift precheck.
- **Wrong family > no family.** `unclassified` is accepted (passes the gate); never guess.
- **SRP.** Validator (read-only) / adopter (tag backfill) / migrator (split+renumber+remap) are separate scripts.
- **Gate-core inherited (re-validated r2).** The legacy rounds validated the read-only validator, `VALID_FAMILIES`, cold-start, `.tmp`+`os.replace` writer, and drift precheck. The **fence-aware parser is NOT taken on trust**: r2 found the real project file has an odd fence count (unbalanced), which a naive toggle mishandles; the parser resets `in_fence` at each lesson heading and is exercised by an odd-fence self-test (Task 1).
- **Shared parser module (r2).** The heading parser, fence-aware collector, and `VALID_FAMILIES` live in a lower-level `lessons_corpus.py` that the gate, adopter, and migrator import downward (cite #119; avoids coupling the read-only gate to sibling mutators per Family F).

## Validation Commands

```bash
# 1. Gate passes on the user-level corpus (strict; exit 0). The user corpus lives
#    at the shared-docs symlink ~/Projects/.ai-playbook/ (-> playbook repo
#    projects/.ai-playbook/); ~/.ai-playbook/ is the separate runtime dir.
python "${HOME}/.ai-playbook/scripts/lessons_index.py" \
  "${HOME}/Projects/.ai-playbook/development_lessons.md"

# 2. Script self-test (in-memory fixtures only; exit 0)
python "${HOME}/.ai-playbook/scripts/lessons_index.py" --selftest

# 3. Conformance test; live user-corpus case must be PASSED, not SKIPPED
uv run pytest tests/unit/test_lessons_corpus_conformance.py -rs

# 4. No tracked reference to principle-index.md anywhere it could hide (history and
#    the one-time lessons-migrate skill excepted; that skill legitimately names the
#    principle-index.md file it deletes/emits an audit snapshot for).
! grep -rln 'principle-index' --include='*.md' . ~/.agents/skills/ ~/Projects/myrepos/ai-playbook/ \
  | grep -v 'docs/history/' | grep -v 'lessons-migrate/SKILL.md'

# 5. Runtime copies byte-identical to repo source (drift guard). Repo source is canonical.
diff -q ~/Projects/myrepos/ai-playbook/scripts/lessons_corpus.py  ~/.ai-playbook/scripts/lessons_corpus.py && \
diff -q ~/Projects/myrepos/ai-playbook/scripts/lessons_index.py  ~/.ai-playbook/scripts/lessons_index.py && \
diff -q ~/Projects/myrepos/ai-playbook/scripts/lessons_adopt.py  ~/.ai-playbook/scripts/lessons_adopt.py && \
diff -q ~/Projects/myrepos/ai-playbook/scripts/lessons_migrate.py ~/.ai-playbook/scripts/lessons_migrate.py

# 6. Layering (Family F): no user-level skill OR user-level doc cites a repo-local lesson
#    by filename+number. The regex allows an optional backtick wrapper around the filename
#    (`` `development_lessons.md` #71 `` is the shape of the known plans-skill violation).
#    Filename-qualified citations are mechanically decidable; bare "lesson #N" without the
#    filename is a residual (ambiguous with catalog/guideline #N) prevented by the routing
#    rule + review, routed to Monitor. Exclude scripts/ (the migration engine selftest
#    fixtures and parser comments legitimately use this pattern as test input) and
#    docs/history/.
! grep -rnE 'development_lessons\.md[`[:space:]]*#[0-9]' ~/.agents/skills/ ~/Projects/myrepos/ai-playbook/ \
  | grep -v '/scripts/' | grep -v 'docs/history/'

# 7. Independence: the project file is plain markdown, contiguous #N, no gate/corpus coupling
python -c "import re,sys; t=open('docs/maintenance/development_lessons.md').read(); \
ns=[int(m) for m in re.findall(r'^## (\d+)\.',t,re.M)]; \
assert ns==list(range(1,len(ns)+1)), f'non-contiguous: {ns[:5]}...{ns[-5:]}'; \
assert 'lessons_index' not in t and 'UL#' not in t, 'project file couples to gate/user corpus'; \
print('project file independent OK')"

# 8. Family map resolves directly from source, in EITHER layer
grep -nE '^\*\*Principle:\*\* Family H' docs/maintenance/development_lessons.md | head
grep -nE '^\*\*Principle:\*\* Family H' "${HOME}/Projects/.ai-playbook/development_lessons.md" | head

# 9. No stale OLD lesson numbers survive the remap (B1; r4 Blocker 1 redesign). Two checks:
#    (a) repo-wide: zero filename-qualified `development_lessons.md #N` citations with N > M.
#        Same N>M discriminator as (b), applied across the repo. AGENTS.md legitimately cites
#        project lessons by `development_lessons.md #N` (project-citing-project is encouraged),
#        so this checks the VALUE against M (not mere presence). Bare `lesson #N` without the
#        filename is the ambiguous residual routed to Monitor (Cmd 6 comment), not checked here.
python -c "
import re, os
t = open('docs/maintenance/development_lessons.md').read()
M = len(re.findall(r'^## \d+\.', t, re.M))
hits = []
for root, dirs, files in os.walk('.'):
    dirs[:] = [d for d in dirs if not d.startswith('.')]
    for fn in files:
        p = os.path.join(root, fn)
        if 'docs/history' in p or not fn.endswith(('.py', '.md')): continue
        for i, line in enumerate(open(p, encoding='utf-8', errors='ignore'), 1):
            for m in re.finditer(r'development_lessons\.md[\x60[:space:]]*#(\d+)', line):
                if int(m.group(1)) > M: hits.append((p, i, m.group(1)))
assert not hits, f'stale repo citations (N>M={M}): {hits[:5]}'
print(f'no stale repo citations OK (M={M})')"
#    (b) in-corpus: a discriminated lesson-#N (OLD-set value, OUTSIDE fences, NOT preceded by a
#    guideline/doc .md filename other than development_lessons.md) whose value > M (the new
#    project lesson count, emitted by the migrator) is a real defect - same-tier citations
#    rewrote into 1..M, cross-tier tokens were REMOVED, so no legitimate post-migration
#    citation uses a value > M. The > M bound sidesteps the new-range-subset-of-old-range
#    collision that made the prior value-scan impossible. M is the count of `^## N.` headings.
#    (Authoritative reconciliation is the migrator's own self-check; this one-liner is a
#    belt-and-braces coarse confirmation using the same discriminator.)
python -c "
import re
t = open('docs/maintenance/development_lessons.md').read()
M = len(re.findall(r'^## \d+\.', t, re.M))
body = re.sub(r'\x60\x60\x60.*?\x60\x60\x60', '', t, flags=re.S)
hits = []
for line in body.splitlines():
    for m in re.finditer(r'#(\d+)\b', line):
        val = int(m.group(1))
        if val <= M:
            continue
        pre = line[:m.start()].rstrip().rstrip('\x60').rstrip()
        fn = re.search(r'([\w./-]+)\.md$', pre)
        if fn and fn.group(1) != 'development_lessons' and not fn.group(1).endswith('/development_lessons'):
            continue
        hits.append((val, line.strip()[:60]))
assert not hits, f'stale in-corpus citations (value>M={M}): {hits[:5]}'
print(f'no stale in-corpus citations OK (M={M})')"

# 10. Fence parser robust to unbalanced fences (r2 Blocker): the gate selftest includes an
#     odd-fence fixture (heading-boundary reset). The real corpus has an odd fence count
#     (verified); this must pass, not silently drop tags.
python ~/Projects/myrepos/ai-playbook/scripts/lessons_index.py --selftest | grep -qi 'unbalanced\|odd-fence' || \
  { echo "gate selftest must exercise the unbalanced-fence case (r2 Blocker)"; false; }
```

---

### Task 1: Author the read-only single-file gate + adopter stub with a failing self-test (RED)

Files:
- `~/Projects/myrepos/ai-playbook/scripts/lessons_corpus.py` *(new)* - shared heading parser + fence-aware collector + `VALID_FAMILIES` + `atomic_write_text(path, text)` (the hardened `.tmp`+`os.replace` writer: `os.open(O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW, 0o600)` + `try/finally` `.tmp` cleanup; imported downward by gate/adopter/migrator; r2 + r3 Medium 3).
- `~/Projects/myrepos/ai-playbook/scripts/lessons_index.py` *(new)*
- `~/Projects/myrepos/ai-playbook/scripts/lessons_adopt.py` *(new)*

`lessons_index.py` (stdlib only, **read-only** - never opens any file for write):

- `<user_corpus>`: a **single** path arg (project files are NOT gated - they are convention). Parse `^## (\d+)\. <Title>` headings; for each lesson collect `**Principle:** Family <X>` lines from its body OUTSIDE fenced code blocks. **Fence tracking is robust to unbalanced fences** (r2 Blocker): reset `in_fence=False` at the start of each lesson (a fenced block cannot legally span a `^## N.` heading); a still-open fence at end-of-section is treated as closed (defensive). Do NOT use a naive whole-file ```` ``` ```` toggle: the real `docs/maintenance/development_lessons.md` has an **odd fence-marker count (57; verified)** - a ```` ```bash ```` block at line 860 is never closed - so a naive toggle inverts in/out state from line 860 to EOF and silently drops real tags. (The tag is the first body line per the template.) Hard violations (exit 1): duplicate `UL#N`; zero tags; >1 tags outside fences; `<X>` not in `VALID_FAMILIES`/`excluded`/`unclassified`. On success: one OK line + per-family counts + total + `unclassified` count. On failure: `UL#N: <category>` lines (`duplicate`|`untagged`|`multiple-tags`|`invalid-family`); never echo raw tag free-text. No `--verbose`, no `--map`. (No gap reporting needed post-migration, but if gaps exist, report them as exit-0 informational.)
- `VALID_FAMILIES = frozenset("ABCDEFGH")` - comment: "authority is `coding_guidelines.md` #17-#25. On catalog growth, update this constant and the catalog together as an explicit cross-project change; the gate surfaces the need by rejecting the first tag of a new family letter with `invalid-family`."
- `--selftest`: in-memory fixtures ONLY (below). It does NOT parse the catalog (a pre-emptive catalog-vs-`VALID_FAMILIES` check was routed to Monitor). No filesystem fallback chain, no `~/`-expansion, no catalog parse.
- RED: create the file with a `--selftest` entry point that exits 1 (sentinel). Exit 127 from a missing file is not an acceptable RED.

`lessons_adopt.py` (separate script, SRP - the only tag-backfill writer; a **manual tool** for the user corpus, never invoked automatically by `learn`):

- `--tag-unclassified <lessons_file>`: mark every untagged lesson's first body line `**Principle:** Family unclassified (pre-gate migration)`. Idempotent. **Safety contract:** refuse if `<lessons_file>` has uncommitted git changes (`git diff --quiet -- <file>` must succeed - clean pre-edit state means `git checkout -- <file>` is full recovery, so no `.bak`). Write via the shared `lessons_corpus.atomic_write_text` helper (`os.open(path, os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW, 0o600)` - `O_EXCL|O_NOFOLLOW` atomically refuse if `.tmp` exists OR is a symlink, killing the TOCTOU; `os.replace` atomic inode swap; `try/finally` deletes `.tmp` on error, original untouched). The migrator uses the SAME primitive (cite #119 - diverging write contracts on the same highest-value asset are forbidden; r3 Medium 3). Print how many lessons rewritten. **Usage constraint:** whole-file rewriter; do NOT run concurrently with a `learn` append. No lock, no `.bak`; git-clean precondition is the recovery.
- **Shared collection logic (cite #119):** MUST reuse the heading parser, fence-aware tag-collection (incl. the heading-boundary reset), and `VALID_FAMILIES` test from the shared `lessons_corpus.py` module (import downward; do NOT `import lessons_index` - that couples the read-only gate to a mutator, Family F). MUST NOT reimplement. Self-test: one tagged + one fenced pseudo-tag + one untagged -> rewrites exactly the untagged one. Additional self-test (r2): an unbalanced-fence corpus is NOT over-rewritten (already-tagged lessons after a dangling-open fence are left tagged, not rewritten to `unclassified`).

Self-test fixtures (`lessons_index.py --selftest`):

- [x] contiguous 3-lesson corpus (Family A, B, excluded) -> exit 0, correct counts, OK line.
- [x] duplicate `## 2.` -> exit 1, `duplicate`.
- [x] untagged lesson -> exit 1, `untagged` naming `UL#N`.
- [x] parametrized taxonomy table: `Family A` ok, `Family H` ok, `Family excluded` ok, `Family unclassified` ok, `Family -` invalid, `Family Q` invalid, `Family a` invalid (lowercase), `Family AB` invalid (two-letter), `Family` invalid (empty token), `Family A` at end-of-line ok.
- [x] fenced ```` ``` ```` block with a literal `**Principle:** Family A (example)` line + one real tag outside -> exit 0 AND OK-line reports `Family A: 1`.
- [x] **unbalanced fence (r2 Blocker, r3 Medium 7 strengthened):** a fixture with an ODD fence count - a ```` ```python ```` opened and never closed, followed by **three** later lessons each carrying a real `**Principle:** Family A` tag after the dangling-open fence -> ALL THREE tags are COUNTED; exit 0 with `Family A: 3` (asserts the EXACT count, not just >0; a naive whole-file toggle reports 0 or an inverted count and fails). Plus a second fixture: a fence re-opened AND closed in a later lesson, with a tagged lesson after it -> counted (pins heading-boundary RE-SYNC across sections, not just first-section reset).
- [x] two real tags outside fences -> exit 1, `multiple-tags`.
- [x] violation output matches `^#?\d+: (duplicate|untagged|multiple-tags|invalid-family)$` (no raw tag text echoed).
- [x] Run -> expect RED: `python ~/Projects/myrepos/ai-playbook/scripts/lessons_index.py --selftest` exits 1 (sentinel), not 127.

### Task 2: Implement gate + adopter; install atomically (GREEN)

Files:
- `~/Projects/myrepos/ai-playbook/scripts/lessons_corpus.py`
- `~/Projects/myrepos/ai-playbook/scripts/lessons_index.py`
- `~/Projects/myrepos/ai-playbook/scripts/lessons_adopt.py`
- `~/.ai-playbook/scripts/lessons_corpus.py`, `~/.ai-playbook/scripts/lessons_index.py`, `~/.ai-playbook/scripts/lessons_adopt.py` (runtime copies)

- [x] Implement both scripts per Task 1. No third-party imports.
- [x] Run -> GREEN: `python ~/Projects/myrepos/ai-playbook/scripts/lessons_index.py --selftest` exits 0.
- [x] Install all three atomically (`.tmp` + `mv`); verify `diff -q` empty for all three (Validation Command 5).
- [x] **Threat model (documented in Step 6.6):** `~/.ai-playbook/scripts/` is trusted; `LESSONS_INDEX_SCRIPT` override executes arbitrary Python only if an attacker controls the env var, runtime-dir write, or a playbook `scripts/` commit - none new; stdout is never `eval`'d (unlike `DONE_LOCK_SCRIPT`). Override is local-testing only.
- [x] Commit (playbook repo, OUTSIDE `done`'s set - manual): `feat(lessons): single-file lessons_index gate (user-corpus strict) + lessons_adopt mutator`.
- [x] **Sequencing:** playbook commit + runtime install land BEFORE the skills commit (Task 8).

### Task 3: Conformance test (user corpus) + project-file independence test

Files:
- `tests/unit/test_lessons_corpus_conformance.py` *(new)*
- `tests/unit/fixtures/lessons_corpus_*.md` *(new)*

- [x] `TestLessonsCorpusConformance#test_gate_passes_user_corpus`; resolves the shared-docs dir by PARSING the lowercase `shared_docs_dir` key from `.ai-playbook/facts.md` (NOT an env var; `SHARED_DOCS_DIR` is never exported - r3 Blocker B2) and runs the gate on `<shared_docs_dir>/development_lessons.md`, expecting exit 0. **Plain assertion, no `skip`/`xfail`**; when the runtime script is absent the WHOLE module `pytest.skip`s once naming the install command; if the user corpus file does not exist, `pytest.skip` with a clear reason (playbook not cloned). On any machine with both, it RUNS and must pass.
- [x] ~~`test_rejects_duplicate_number`~~ **(post-r2 reversal: removed)** gate-BEHAVIOR tests (duplicate / malformed / fenced / taxonomy) were relocated OUT of this repo and back into the gate's in-memory `--selftest` in ai-playbook (`lessons_index.py --selftest` covers duplicate, invalid-family, fenced pseudo-tag, the full taxonomy table, unbalanced fence, and violation-format - verified). Rationale: these are gate-contract tests, not project invariants; they belong co-located with `lessons_index.py`. The `--selftest` is manually-run (no pytest/CI in ai-playbook), so this reverses the r4-Medium-6 CI-enforcement gain by user decision; runtime/repo drift stays caught by Validation Command 5 (`diff -q`). The 3 synthetic fixtures (`lessons_corpus_duplicate.md` / `_malformed_tag.md` / `_fenced_pseudo_tag.md`) were deleted.
- [x] `test_taxonomy_table` **(post-r2 reversal: removed)** - see above; the parametrized taxonomy pytest was deleted, coverage preserved in `--selftest`.
- [x] `test_project_file_independence`; given the migrated `docs/maintenance/development_lessons.md`, assert contiguous `#N` (`1..N`) AND the file contains no `lessons_index`/`UL#` coupling (pins the convention-layer independence invariant; mirrors Validation Command 7). No skip - this is a pure-file assertion that always runs.
- [x] `test_project_file_keeps_malformed_tags` (r3 Medium 8): seed a project-specific lesson with a malformed convention tag (`Family Q`) and one with zero tags; assert the migration preserves BOTH unchanged in the project file (pins the strictness-split invariant - the gate is never imposed on a project file; a regression applying gate-strict validation is detected).
- [x] Invoke the gate via `subprocess` (no import of the user-level script); resolve runtime path from `LESSONS_INDEX_SCRIPT` env or default `${HOME}/.ai-playbook/scripts/lessons_index.py`.
- [x] Run -> expect: user-corpus case RED until Task 5 (migration) lands; independence case RED until migration rewrites the project file.

### Task 4: Author the migration engine + skill (heuristic + flag)

Files:
- `~/Projects/myrepos/ai-playbook/scripts/lessons_migrate.py` *(new)*
- `~/.agents/skills/lessons-migrate/SKILL.md` *(new)*

`lessons_migrate.py` (stdlib only; a **manual, one-time-per-repo** tool invoked by the skill; the only writer of BOTH files during migration):

- **Inputs:** the repo's `docs/maintenance/development_lessons.md` and the user corpus path (`<shared_docs_dir>/development_lessons.md`, created if absent; resolve `shared_docs_dir` from `.ai-playbook/facts.md` - it is NOT an env var, r3 B2). **git-clean precondition (r4 Blocker 3 - scoped to the FULL write scope, not just inputs):** refuse to start unless `git diff --quiet` succeeds over EVERY path the migrator will write, in BOTH repos - the project file AND `src/`/`tests/`/`AGENTS.md`/`docs/maintenance/` in tax-reporting AND the user-corpus file in ai-playbook. (The prior input-only check let an unrelated uncommitted change in `src/`/`tests/` be destroyed by the `git checkout -- <scope>` recovery.) **Concurrency (r2; r4 Monitor 1):** do NOT run concurrently with a `learn` append in ANY repo - both rewrite the shared user corpus with no lock; a concurrent append between this tool's read and `os.replace` is silently lost (last-writer-wins). This is a PROSE precondition with NO runtime enforcement or detection: the operator MUST ensure no `learn` is running in any terminal before invoking the migrator. (r4 Medium 5: the mtime backstop added r3 was dropped - it was non-load-bearing, could not catch a same-second append, and its abort-on-cosmetic-tick branch risked recovery churn. The contract is the sole guard; full closure via a flock sidecar is out of scope.) **Interruption recovery (r3 Medium 2 - resume subsystem removed; r4 Medium 3):** no stage marker, no resume predicate, no `--force`. If interrupted, recover by rolling back BOTH repos to the clean pre-migration state and re-running: in tax-reporting `git checkout -- docs/maintenance/development_lessons.md src/ tests/ AGENTS.md docs/maintenance/`; in ai-playbook `git checkout -- projects/.ai-playbook/development_lessons.md`. **If the user-corpus `os.replace` in ai-playbook committed before the crash, BOTH repos MUST be rolled back** - rolling back only tax-reporting leaves run-1's appended lessons in the user corpus, and the re-run then emits a merge-flag flood (dedup flags-but-does-not-add) rather than clean recovery. The dedup step protects the user corpus from double-appends on a clean re-run.
- **Parse** lessons via the shared heading parser + fence-aware tag collection (cite #119; import from `lessons_corpus.py` - do NOT `import lessons_index`).
- **Classify each lesson (autodiscovery, ZERO-CONFIG) - the skill is REPO-AGNOSTIC:** the classifier is **generic-first** - it identifies the CROSS-PROJECT bucket via stable, repo-independent signals and defaults everything else to project-specific, so the costly error (promoting a project-specific lesson into the shared corpus) is hard to make by construction. No domain keywords are required from the operator. Signals, evaluated in order (first match wins):
  1. **Family tag (first checked):** a lesson already carrying a well-formed `**Principle:** Family <A-H>` tag (authored by `generalize`/`learn` as a cross-project precept) -> **cross-project**. **Coverage note:** until Task 7 lands, the `generalize/SKILL.md:110` template permits OMITTING the tag for Excluded lessons, and ~40 of 198 live lessons are untagged (incl. ~24 recent ones); these miss signal 1 and fall through to signal 2 + the retained-lesson tail summary. This is acceptable (safe default keeps them local; the tail summary lists them for manual promotion) - no auto-mis-promotion.
  2. **Generic engineering shape:** title/body matches a built-in generic vocabulary drawn from the family catalog (`coding_guidelines.md` #17-#25: type-annotation specificity, exception handling, post-aggregation validation, test discipline, matching/dedup, review loops, data-loss/warning logging, atomic writes, sentinel values) and has no domain residue -> **cross-project**. This vocabulary is cross-project and stable (it IS the catalog), NOT repo-specific. **Match mechanism:** a fixed phrase list per family (the family's keyword set, maintained in `lessons_migrate.py` as a `dict[family_letter, list[str]]` alongside a comment citing `coding_guidelines.md` #17-#25 as authority), matched case-insensitively as whole-word substrings against the lesson's title+body. **This keyword list is a SECOND, derived view of the catalog (r2):** it is NOT single-sourced - when a future audit revises a family's `**Shape trigger:**` wording (#17 says triggers may be revised), this list can drift silently and mis-route. Guard: `lessons_migrate.py --selftest` asserts each family's keyword list contains at least one **discriminating token** NOT in the union of the other families' keyword sets (a deterministic check that FAILS when a family's keywords collapse to generic English; r3 Medium 6 - the prior "overlap with catalog shape-trigger wording" check passed trivially on incidental English overlap unless a stoplist were invented). Do NOT describe this as "mirroring `VALID_FAMILIES`'s `invalid-family` surfacing" - a soft selftest and a hard gate rejection are not analogous. Adding a family to the catalog means adding its keyword list here AND updating the discriminating-token selftest.
  3. **Default -> project-specific:** anything not matching (1)/(2) stays in the repo file (the safe default; keeping a generic lesson local is harmless).
  4. **Tail summary (not a routing decision; r3 resolution of M5 - signal 4 dropped):** emit one non-routing summary line to the review list: "N untagged project-specific lessons retained - review for possible cross-project promotion." No auto-mining, no capitalized-term heuristic, no stoplist, no `--domain-keywords` override. (Rationale: the prior signal 4 was a non-routing hint that pre-sorted a review list the operator reads in full anyway; the safe default (signal 3) already prevents the only costly error - auto-mis-promotion - so the hint protected nothing while adding a third vocabulary, a repo-mining pass, a CLI flag with zero documented users, and two self-tests. Against the user's SIMPLICITY / zero-config priority it was gold-plating.) The operator promotes genuine cross-project lessons by hand from the retained set.
- **Dedup against the user corpus (cite #77 - never silent overwrite):** for each cross-project candidate, compare against existing user-corpus lessons by normalized title + body similarity; a near-match is **flagged for merge** (emitted to the review list), NOT auto-added; only genuinely-new lessons are appended.
- **Write order is atomic for the failure case (r2):** build BOTH file contents + the remap in memory first, then:
  1. **User corpus first:** write the new corpus via the shared `lessons_corpus.atomic_write_text` helper (append new cross-project lessons with valid strict tags - if a lesson's existing tag is malformed/missing, mark `Family unclassified (needs classification)`, which passes the gate; then compact-renumber the whole corpus `1..N` as `UL#N`). Run `lessons_index.py` on the `.tmp`; require exit 0. Only on success `os.replace` the user corpus. On failure: delete the `.tmp`, abort, leave BOTH real files untouched (the project file has NOT been written yet at this point).
  2. **Project file + repo-wide refs second:** write the project file via the same `atomic_write_text` helper (keep project-specific lessons with convention tags preserved as-is incl. malformed ones; compact-renumber `1..N` as `#N`), then rewrite repo-wide `#N` references (`src/`, `tests/`, `AGENTS.md`, `docs/maintenance/`) per the remap below.
  ALL write sites (user corpus, project file, AND every repo-wide ref-rewrite target in `src/`/`tests/`/`AGENTS.md`/docs) MUST use the shared `lessons_corpus.atomic_write_text` primitive (`O_EXCL|O_NOFOLLOW` `.tmp` + `os.replace`; cite #119) - the SAME hardened primitive the adopter uses (r4 Medium 2: "both writes" under-specified the ~35 repo-wide targets, leaving a planted-`.tmp`-symlink TOCTOU open in `src/`/`tests/`). Diverging write contracts on the same highest-value asset are forbidden (r3 Medium 3). This order makes "gate failed" leave both files untouched (true atomicity for the failure case) and makes an interruption leave the user corpus either fully written or untouched. NOTE (L9): once the project file + repo refs are written, a later failure is NOT rolled back - by design (the project file is convention; `git checkout -- <files>` for the full write scope is full recovery per the git-clean precondition); the failed status + review list is the recovery path.
- **Build the remap** (repo old-`#N` -> new project `#N` for same-tier targets; -> REMOVE for cross-tier targets that moved to the user corpus; the new `UL#K` is recorded for the separate manual Task 7 B2 edit to USER-LEVEL skills/docs only) and **rewrite `#N` references REPO-WIDE** - this is load-bearing (B1): the repo has ~45 live lesson citations across `src/**/*.py` (~13), `tests/**/*.py` (~22), `AGENTS.md` (~5), and `docs/maintenance/**/*.md` (~7) plus ~660 in-body cross-links inside `development_lessons.md` itself (verified). Targets: `src/**/*.py`, `tests/**/*.py`, `**/*.md` (excluding `docs/history/`). **ONE rewrite rule, applied everywhere (r4 redesign of the r3 "two modes" - the no-lead-in in-corpus mode corrupted 24 `<guideline>.md #N` citations and made reconciliation impossible; r4 Blockers 1+2, Medium 1):**
  - **Discriminator (a token is a LESSON citation iff all hold):** (i) value is in the OLD number set; (ii) NOT inside a fenced code block; (iii) word boundary `#(\d+)\b` so `#5,000 EUR` is not mismatched; (iv) if the immediately-preceding non-space token - AFTER stripping a trailing backtick (real citations are backtick-wrapped, e.g. `` `~/Projects/.ai-playbook/python_guidelines.md` #3 ``; the rewriter and Validation Command 9(b) MUST use the SAME backtick-stripping tokenizer, cite #119 - r5 Medium) - is a filename ending in `.md`, that filename must BE `development_lessons.md` (a self-citation IS a lesson ref and IS rewritten); a `#N` preceded by any OTHER `.md` filename (`coding_guidelines.md`, `agent_workflow_guidelines.md`, `python_guidelines.md`, `project-guidelines.md`, etc.) references a RULE number in another file, NOT a lesson, and is LEFT UNCHANGED (the 24 such citations verified present; r4 Medium 1). Repo-wide, the discriminator is additionally tightened by recognizing explicit citation forms (`development_lessons.md #N`, backtick-wrapped `` `development_lessons.md` #N ``, `docs/maintenance/development_lessons.md #N`, `lesson #N`/`Lesson #N`, `repo lesson #N`) so bare `#N` that could be a PR/issue/constant is not touched; in-corpus (the file IS the lessons corpus) the bare-`#N` form plus guards (iv)+(v) is sufficient.
  - **Process-identifier exclusion (r5 - guard v; r6 Medium - case-insensitive + `Invariant` + lead-in enumeration):** the corpus carries NON-lesson `#N` tokens whose preceding token is a process/identifier keyword, NOT a `.md` filename - verified present: `Finding #N`/`finding #N`, `Medium #N`, `Blocker #N`, `Low #N`, `High #N`, `Task #N`, `Rule #N`/`rule #N`, `Round #N`, `Step #N`, `Invariant #N`/`Design Invariant #N`, `DP-<n> #N`, `r<n> #N` (e.g. `Rule #4` line 2733, lowercase `rule #6` line 2388, `Finding #1` line 2004, lowercase `finding #1` line 2347, `Medium #1` line 2417, `DP-014 #6` line 2417, `Invariant #2` line 2092 (also `Design Invariant #2` on the same line), `Design Invariant #1` line 2489 - r6 found these last four missed: the set was case-SENSITIVE and omitted `Invariant`, so `rule #6`, `finding #1`, and the load-bearing `Design Invariant #2` reference would have been silently renumbered/removed). These are LEFT UNCHANGED. A `#N` is NOT a lesson citation if its immediately-preceding non-space token **case-insensitively** matches the process-prefix set `{Finding, Findings, Medium, Blocker, Low, High, Task, Tasks, Rule, Rules, Round, Rounds, Step, Steps, Invariant, Invariants, Family, Campo, Quadro, Anexo, Tabela, CIRS, CRG, SRG}` or the patterns `DP-\d+`, `r\d+`, `UL#`, `art\.?`. (The case-insensitive match is required: the real corpus uses lowercase `rule #6`/`finding #1`. `§` was dropped from the set - dead weight, since the real `§N` forms put `§` before a digit, not before `#N`. `Family` is retained although `Family #N` has 0 corpus matches today: `Family <letter>` tags do not match `#\d+`, so the entry is harmless and guards a plausible future form.) **Closing the systemic gap (r6 premortem):** a hand-maintained denylist can never be PROVABLY complete, and - critically - the authoritative remap-driven reconciliation does NOT catch a denylist miss (the migrator records a mis-discriminated process-id as `renumbered-to-new`, then "correctly" confirms its own mis-decision; the operator signs off on silent corruption). The backstop for a ONE-TIME migration of a KNOWN corpus is therefore a **lead-in enumeration audit**: the migrator's review list emits EVERY distinct `<lead-in> #N` token it DISCRIMINATED as a lesson (i.e. rewrote or removed), grouped by lead-in word, for a one-time operator confirmation that no process-id lead-in snuck through. The distinct lead-in vocabulary is small (real corpus: `Lesson`/`lesson`, bare, `per`, `to`, `of`, `from`, `and`, `the`, `with`, `for` = genuine lesson prose; the denylist members = process-ids) so this is a minutes-long human check, not per-token curation. Preferred over a positive allowlist, which r3 found missed ~600 real bare lesson citations. Multi-number forms are a **repeated group** `#\d+([ ,/]+#\d+)+` (incl. the spaced-slash `#N / #M` and 3-4-number clusters like `#N, #M, #K, #L` actually present - rewrite EVERY `#N` in the match through the discriminator).
  - **Per-token resolution:** for each discriminated lesson `#N`: if it stays project-side -> rewrite to new `#N`; if it moved to the user corpus -> **REMOVE the token** (drop the `#N`; clean up resulting empty or dangling-punctuation `See also` lines; r5 Option A - the prior title-prose form was empirically broken: 6 titles contain a literal `"`, and the dominant multi-token `See also (principle cluster X): #N, #M, #K (rationale re-citing #J)` form became gibberish under per-token title-prose); if it does not map 1:1 (ambiguous) -> FLAG. **Within-line cleanup (r6 Low):** if the removed token was the SOLE content of a parenthetical - `(#N)` -> remove the parentheses too, so `seed (#5) vs ...` becomes `seed vs ...`, not `seed () vs ...` (real example: line 56). For a removal from any OTHER mid-prose position (a token embedded in running rationale text, e.g. `#94 is the test-enforced variant of #23's manual grep` where #94/#23 moved), do NOT build a grammar engine - the token is removed and the line is flagged in the audit review list as "review prose grammar" for optional human post-edit. This surface is SMALL and bounded: `See also` cluster lines group same-family lessons, so a line is family-homogeneous (all tokens move -> line dropped entirely; all stay -> clean renumber) and only MIXED lines residue. The migration completes either way and the file stays valid markdown. **Cross-tier removal does NOT lose discoverability**: the repo file and the user-level corpus are BOTH loaded into the agent's context, so the moved lesson (and its cross-references) remain reachable via the user corpus the agent also reads - removing the in-repo pointer just restores within-layer purity. Emit every removed/renumbered/flagged token to the review list for audit.
  - **Renumber scope (r4 Low 1):** the compact-renumber pass rewrites `## N.` HEADINGS only; in-body `#N` citations are rewritten SOLELY by this remap pass. (Renumbering body `#N` in the renumber pass AND in the remap pass would double-shift every citation; the self-test pins a concrete old->new mapping to fail visibly under that wrong impl.)
  - Emit the full remap table + any FLAGGED (ambiguous) list to the review list.
- **Emit the frozen audit snapshot** `docs/history/feature-notes/<date>-principle-index-audit-snapshot.md` (banner: FROZEN ONE-TIME AUDIT; verbatim `## Blind-spot analysis`, `## Dry-run recall`, `## Precision gate`, `## Duplicate clusters`, `## Accounting check` from the deleted index).
- **Delete** `docs/maintenance/principle-index.md`.
- **Self-check:** the user-corpus gate already ran on the `.tmp` in write-step 1 (abort-before-`os.replace`), so the corpus on disk is gate-clean. Re-run `lessons_index.py` on the final user corpus as a belt-and-braces confirmation (exit 0). **The gate validates tag FORMAT, not routing correctness** - `--dry-run` (below) is the routing-correctness gate. **Stale-ref reconciliation (B1) - AUTHORITATIVE source is the migrator's own remap-driven check (r5 Medium):** during the rewrite pass the migrator records EVERY discriminated lesson-`#N` token it touched (old value -> action: renumbered-to-new / removed / left-non-lesson). The authoritative reconciliation asserts that NO discriminated lesson token was left at its OLD value unless the action was explicitly `removed` or `left-non-lesson` - i.e. it compares the OUTPUT token stream against the remap, not against a value bound. (This is exact because the migrator has the remap; it closes the low-numbered blind spot a value-scan cannot.) A coarse belt-and-braces echo: (a) repo-wide `grep -rnE 'development_lessons\.md[`[:space:]]*#<old>|lesson #<old>' src/ tests/ AGENTS.md docs/maintenance/` (history excepted) -> require ZERO matches; AND (b) in-corpus scan for discriminated lesson-`#N` with value > M -> require ZERO matches. **The `> M` bound has a KNOWN blind spot (r5 Medium):** it catches only MISSED HIGH-NUMBERED citations (old value > M); a missed citation whose old value is <= M is invisible to it (23 such tokens exist today). The authoritative remap-driven check above closes that hole; the `> M` scan is a sanity echo only, not the primary gate.
- **Output:** a summary (counts: project-specific kept, cross-project moved, ambiguous flagged, dedup-merge flagged, refs rewritten, refs unremappable) + the review list file path (ambiguous + merge + unremappable refs).
- **Skill `SKILL.md`:** documents the one-time-per-repo procedure, the generic-first autodiscovery classifier (zero-config; family tag + generic-shape vocabulary -> cross-project; everything else -> project-specific default; a tail-summary line lists untagged retained lessons for manual review), the **git-clean precondition (full write scope, both repos)**, the **no-concurrency-with-`learn` precondition** (r2 + r4 Monitor 1: the migrator and a `learn` append both write the shared user corpus with no lock and NO runtime enforcement - the operator ensures no `learn` is running in any terminal), the **interruption recovery recipe** (r3 + r4 Medium 3: `git checkout -- <rewrite scope>` in BOTH repos + re-run; no resume marker/`--force`; both repos must be rolled back if the user-corpus write committed), the rewrite rule (single discriminator with `.md`-exclusion + case-insensitive process-prefix-denylist + a lead-in-enumeration audit of every discriminated token so the operator confirms no process-id lead-in snuck through (r6 Medium); same-tier -> new `#N`, cross-tier -> REMOVE the token with within-line cleanup of sole-content `(#N)` parentheticals (r5 Option A + r6 Low; the moved lesson stays reachable via the user corpus both layers load), ambiguous -> flag), and that the project file is convention (no gate). The skill body is **repo-agnostic and zero-config**: no domain keywords are baked in or required (no `--domain-keywords` override; r3). Includes a `--dry-run` mode (classify + emit the review list + planned remap WITHOUT writing) so the operator can audit before committing (r4 Low 4: kept as a standard audit-before-destructive-write affordance; git-clean rollback is not equivalent to never-writing).

Self-test fixtures (`lessons_migrate.py --selftest`):

- [x] generic-first classification (no flags): a 4-lesson synthetic repo corpus - (a) a lesson with a well-formed `Family B` tag, (b) an untagged lesson whose body matches the generic-shape vocabulary ("catch specific exception types, not broad Exception"), (c) a domain-coupled lesson ("Koinly transaction_history.csv naming"), (d) an abstract-but-untagged lesson with no domain residue - run with NO arguments -> user corpus gets (a) and (b) (strict `UL#1`, `UL#2`); project file gets (c) and (d); the review list's tail-summary line counts (d) among the retained untagged project-specific lessons.
- [x] safe default (the core guard): a project-specific lesson that happens to mention a generic-sounding word but is clearly domain-coupled (e.g. "validate the FIFO basis per CIRS art. 43") -> stays in the project file, NOT promoted to the user corpus, because the costly direction (mis-promotion) is what the generic-first default prevents. A bespoke engine that keyword-matched "validate"/"FIFO" as generic would wrongly promote it; this fixture fails under that wrong design.
- [x] repo-agnostic engine: `grep -iE 'crypto|FIFO|Koinly|ISIN|dividend|Modelo|CIRS|Quadro|Anexo' lessons_migrate.py` -> zero matches (no hardcoded domain keywords; the classifier keys off the family catalog + generic-shape vocabulary, never repo terms).
- [x] dedup: a cross-project candidate whose title+body near-matches an existing user-corpus lesson -> flagged for merge, NOT appended (user-corpus count unchanged).
- [x] remap (markdown): a fixture `AGENTS.md` citing `development_lessons.md #5` where old #5 -> new #2 -> rewritten to `#2`; a citation to a moved lesson (old #3 -> user corpus) -> the token is REMOVED (the migrator touches only tax-reporting project files, all project-tier, none may carry `UL#`; the `UL#K` form belongs only in user-level skills/docs, handled by the separate manual Task 7 B2 edit).
- [x] remap (code, B1): a fixture `.py` file with the citation forms `# See development_lessons.md #5.` and `# silent drop (lesson #5)` and `# #5/#6 multi` -> each old number rewritten per the remap (multi-number forms rewrite each token); bare `# 123` (a PR-number-shaped token not in a lesson-citation form) is left untouched.
- [x] remap (backtick form, B2): a fixture citing `` `development_lessons.md` #5 `` -> rewritten (pins the backtick-wrapped form).
- [x] in-body cross-link, same-tier + renumber scope (r4 Low 1): a multi-lesson fixture mirroring real corpus forms - `See also (principle cluster D): #58, #68, #94` (3-number, colon-separated), `Distinguishing from #71 / #72` (spaced slash), `Lesson #73`, and `(#5)` - where ALL cited numbers are in the OLD set and stay project-side -> EVERY token rewrites to its new `#N`, and at least one mapping is PINNED concretely (e.g. old #58 -> new #12; a double-shift impl that renumbers body `#N` in the renumber pass AND the remap pass fails this visibly). Headings `## N.` renumber; body `#N` remap-only.
- [x] guideline-citation exclusion (r4 Medium 1): TWO lines - (a) `` See `~/Projects/.ai-playbook/python_guidelines.md` #3 for the canonical rule. `` with `#3` in the OLD set -> `#3` LEFT UNCHANGED (a rule number in another file; protects the 24 real citations; the backtick-strip tokenizer is exercised); (b) `See development_lessons.md #4 (type-safe sentinels).` with `#4` in the OLD set and staying project-side -> `#4` REWRITTEN to its new `#N` (a self-citation IS a lesson ref; a discriminator that blanket-excludes any `.md`-preceded `#N` wrongly skips it -> fails).
- [x] process-identifier exclusion (r5 guard v; r6 Medium - case + `Invariant`): a fixture line `See AGENTS.md Rule #4 and finding #1 (Medium), per Design Invariant #2.` with `#4`, `#1`, `#2` in the OLD set -> ALL LEFT UNCHANGED (process identifiers, not lessons; a case-SENSITIVE denylist rewrites lowercase `finding #1`; a set missing `Invariant` rewrites `Design Invariant #2` - either -> fails). Plus `DP-014 #6`, `Medium #1`, and lowercase `rule #6` -> unchanged. Plus: the review list's lead-in enumeration emits the distinct lead-ins the migrator discriminated as lessons, asserting the process-id lead-ins above do NOT appear in it (a denylist-miss impl's enumeration WOULD list `Rule`/`finding`/`Invariant` -> fails the operator confirmation).
- [x] in-body cross-link, cross-tier (r5 Option A; r6 Low - within-line cleanup): a `#N` whose target MOVED to the user corpus is REMOVED (the token dropped; a `See also:` line whose only tokens all moved is dropped entirely; a line mixing same-tier and moved tokens keeps the same-tier tokens and drops the moved). A removed token that was the SOLE content of a parenthetical takes the parentheses with it: `seed (#5) vs focused` (mirrors real line 56, #5 cross-tier, #28 stays) -> `seed vs focused`, NOT `seed () vs focused`. A removed token embedded in running rationale prose (`#94 is the test-enforced variant`) -> token removed AND the line flagged "review prose grammar" in the audit list (no grammar engine; accepted cosmetic residual). Assert: NO `UL#` in the project-file output, the moved token is GONE, the sole-paren case leaves no `()`, and every removal appears in the audit review list (a leave-in-place impl, a rewrite-to-`UL#K`/title-prose impl, or a no-cleanup impl leaving `()` -> fails).
- [x] stale-ref reconciliation (B1, r5): the AUTHORITATIVE check is the migrator's remap-driven self-check (every touched token recorded old->action; assert no discriminated lesson token left at its OLD value unless action was `removed`/`left-non-lesson`) - a wrong impl that leaves a same-tier citation at its old value <= M (invisible to the coarse > M scan) is caught here. The coarse echo: repo-wide `grep` for old filename/lesson-qualified citations -> zero; in-corpus discriminated lesson-`#N` with value > M -> zero.
- [x] strictness split (r3 Medium 8): a project-specific lesson tagged `Family Z` (invalid) and one with zero tags both survive UNCHANGED in the project-file output (project tier is convention; the gate is never applied to it).
- [x] atomic write, ALL sites (r3 Medium 3 + r4 Medium 2): a `.tmp` symlink planted at the write target AND at a fixture repo-wide target (`tests/`/`src/` `.py`) -> BOTH refused (`O_EXCL|O_NOFOLLOW` fires via the shared `atomic_write_text`), originals untouched.
- [x] idempotency (r3 Medium 2): re-run after a completed migration (project file already contiguous with new `#N`) -> refuse cleanly with the recovery recipe ("`git checkout -- <scope>` + re-run"); no resume marker, no `--force`.
- [x] self-check: if the user-corpus result would have a duplicate tag, abort (no `os.replace` on the corpus); the project-file write is not rolled back (`git checkout` is recovery).
- [x] Run -> expect RED: `python ~/Projects/myrepos/ai-playbook/scripts/lessons_migrate.py --selftest` exits 1 (sentinel), not 127.

### Task 5: Run/test the migration skill on tax-reporting (first use / validation)

This task is the **first real-world run and validation of the skill built in Task 4**, not bespoke migration steps. The procedure is owned entirely by the `lessons-migrate` skill (Task 4); this task runs it zero-config on tax-reporting and asserts the skill works end-to-end. No domain-keyword file is authored: the classifier autodiscovers via the family catalog + generic-shape vocabulary.

Files:
- `docs/maintenance/development_lessons.md` (rewritten by the skill)
- `docs/maintenance/principle-index.md` (deleted by the skill)
- `docs/history/feature-notes/<run-date>-principle-index-audit-snapshot.md` *(new, written by the skill's snapshot step; `<run-date>` resolves to the migration run date, NOT the historical 2026-06-21 audit date - r2 Low 1)*
- `AGENTS.md`, `src/**/*.py`, `tests/**/*.py`, and repo docs with `#N` refs (rewritten by the skill's remap)
- `~/Projects/myrepos/ai-playbook/projects/.ai-playbook/development_lessons.md` (populated by the skill)

- [x] Invoke the skill dry-run with NO domain arguments: `uv run python ~/.ai-playbook/scripts/lessons_migrate.py --dry-run docs/maintenance/development_lessons.md`; review the emitted classification + review list (incl. the untagged-retained tail summary + ambiguous-ref flags + the planned cross-tier removals + same-tier renumbers) + planned remap. Confirm the classifier ran zero-config.
- [x] Invoke the skill for real (same args without `--dry-run`); confirm the summary counts, that the self-check gate passed, and that the skill (not manual edits) performed the rewrite/remap/delete/snapshot.
- [x] Curate the skill's emitted review list (retained untagged lessons + merge flags + unremappable/ambiguous refs + the removed/renumbered token audit): promote genuine cross-project lessons from project file to user corpus, confirm merges, resolve ambiguous refs. Cross-tier in-corpus links are AUTO-REMOVED by the skill (r5 Option A) - no manual resolution pass; the audit list shows what was removed (the moved lessons stay reachable via the user corpus both layers load).
- [x] Assert the skill is repo-agnostic and zero-config: confirm no tax-reporting keyword is hardcoded in `lessons_migrate.py` (grep the engine) and that the engine exposes no `--domain-keywords` flag (removed r3). This is the core validation that the engine is general and one-command-per-repo.
- [x] Verify Validation Commands 1, 4, 7, 8, 9 pass (user corpus gated clean; no `principle-index` refs; project file independent + contiguous; no stale old-`#N` survived). **Note:** Cmd 4 (principle-index refs) is Task 7's scope (plan line 323); Cmds 1, 7, 8, 9 pass; Cmd 9 authoritative check confirms zero cited #N > M=41.
- [x] Commit (playbook repo, manual): the user corpus seed and the skill/gate scripts (Tasks 1-4). Commit (tax-reporting repo): the rewritten project file, deleted index, audit snapshot, remapped refs, and the new tests (Task 3). **Done:** tax-reporting c4e53ac (migration output + stub cleanups); playbook 7c0ab77 (user-corpus seed, 160 lessons gate-clean). Skill/gate scripts (Tasks 1-4) already committed in prior playbook commits (ba12e6a et al.); Task 3 tests already committed (46b2c2e).

### Task 6: Add user-level tag-format spec (strict at user, convention at project)

Files:
- `~/Projects/myrepos/ai-playbook/projects/.ai-playbook/coding_guidelines.md` (normative spec home, under #17)

**Note (r3 Low 3):** repointing the `principle-index.md` filename citations at lines 162/190 of this SAME file is owned by Task 7 (the migration remap does not touch them - `coding_guidelines.md` cites the index by filename, not `#N`). An implementer doing Task 6 in isolation must not assume 162/190 are handled here; Validation Command 4 (Task 9) enforces zero survivors.

- [x] Add the normative "Lesson tag format" sub-section under `coding_guidelines.md` #17

### Task 7: Repoint ALL stale references (repo + skills + playbook)

Files:
- `AGENTS.md` (post-migration, verify the remap landed)
- `docs/maintenance/plan_quality_guidelines.md`
- `~/.agents/skills/generalize/SKILL.md` (principle-index refs at lines 124, 224, 260, 272; `Family excluded` template note at line 110). NOTE (r2 correction): `~/.agents/skills` is a symlink into `~/Projects/myrepos/ai-playbook/agents/skills/`, so this is a SINGLE canonical file tracked in the playbook repo - there is no separate "playbook mirror" to edit (the r2 Medium 8 "missed mirror" finding was a false positive, retracted after wiring verification).
- `~/Projects/myrepos/ai-playbook/projects/.ai-playbook/coding_guidelines.md` (lines 162, 190)
- `~/.agents/skills/plans/SKILL.md` (line 466 - live Family-F violation, B2)

- [x] Find every reference: `grep -rln 'principle-index' --include='*.md' . ~/.agents/skills/ ~/Projects/myrepos/ai-playbook/` (expect AGENTS.md, plan_quality_guidelines.md, generalize/SKILL.md, coding_guidelines.md, frozen history; leave history).
- [x] `AGENTS.md` (~line 157): replace the `principle-index.md` path with `grep -nE '^\*\*Principle:\*\* Family X' docs/maintenance/development_lessons.md` (project) and note cross-project lessons live in the user corpus.
- [x] `plan_quality_guidelines.md` (~line 234): "resolve families by grepping the in-band `**Principle:** Family X` tags in `development_lessons.md` (project) or the user-level corpus (cross-project)."
- [x] `generalize/SKILL.md`: line 124 map-mode -> grep the source; line 224 -> "run `lessons_index.py` to confirm user-corpus coverage"; line 260 Anti-Patterns row -> a row keyed to the gate/grep; line 272 -> the grep/gate recipe.
- [x] `generalize/SKILL.md:110`: **REVERSE** the current "omit only for Excluded/process-only lessons" instruction - mandate `**Principle:** Family excluded (<kind>)` for all Excluded/process-only lessons. This is a reversal, not a clarification. It also closes a signal-1 coverage gap in the migration classifier (Excluded lessons authored under the old omit-tag template are invisible to signal 1 and would otherwise rely on signal 2 / the tail summary).
- [x] `coding_guidelines.md:162`/`:190`: "see each repo's `development_lessons.md` (`grep -nE '^\*\*Principle:\*\* Family X'`) for the project-tier map; cross-project lessons live in the user-level `development_lessons.md` (strict, gated)." **(r2 Low 2:** `coding_guidelines.md` cites the `principle-index.md` *filename*, not a `#N`, so the migration's remap does NOT touch it; this manual repoint is the sole path. Validation Command 4 enforces zero survivors.**)** **(r4 Low 2:** after repointing, the #18-#25 family sections' "illustrative subset" sentences (currently sourced from the deleted index) lose their anchor; in the SAME task either refresh those illustrative lesson lists from the migrated corpus (user-level `UL#N` for cross-project, project `#N` for repo-specific) OR rephrase the sentences to defer to the grep.**)**
- [x] **B2 - rewrite the live `plans/SKILL.md:466` violation:** the text `` See `development_lessons.md` #71. `` is a user-level skill citing a repo-local lesson by filename (Family-F violation; verified present). Lesson #71 ("verification-first task ordering") is cross-project, so the migration routes it to the user corpus (`UL#K`); rewrite line 466 to cite the user-level corpus (`` See `development_lessons.md` UL#K. ``) or self-contained prose. This lands AFTER Task 5's migration resolves #71's destination.
- [x] **Layering check (Validation Command 6):** `grep -rnE 'development_lessons\.md[`[:space:]]*#[0-9]' ~/.agents/skills/ ~/Projects/myrepos/ai-playbook/ | grep -v '/scripts/' | grep -v 'docs/history/'` returns nothing. The user corpus itself carried 34 stale See-also lines citing the old project file by number (moved-lesson bodies were copied verbatim; the engine renumbers headings, not in-body `#N` tokens); these were converted to prose-only (drop fragile filename+number, keep parenthetical descriptions; preserve all non-development_lessons refs) in playbook commit `3fa7ddd`. Excludes `scripts/` (engine selftest fixtures legitimately use the pattern as test input) and the one-time `lessons-migrate/SKILL.md` (Cmd 4; legitimately names the file it deletes).

### Task 8: Wire `learn` Step 6.6 (user-corpus only) + capture-time routing rule

Files:
- `~/.agents/skills/learn/SKILL.md`
- `~/.agents/skills/generalize/SKILL.md`
- `~/.agents/skills/done/SKILL.md` (verify only; PLUS one r5 Step-1 block-propagation edit - see Task 8 last bullet)

- [x] Add **Step 6.6: User-level lessons-corpus gate** after Step 6.5 (verified at `learn/SKILL.md:392`; Step 7 at line 408). Resolution: `script="${LESSONS_INDEX_SCRIPT:-${HOME}/.ai-playbook/scripts/lessons_index.py}"`, `user_corpus="${HOME}/Projects/.ai-playbook/development_lessons.md"`. **(r3 Blocker B2):** `SHARED_DOCS_DIR` is NOT an exported env var (0 grep matches across skills/playbook) - the facts key is lowercase `shared_docs_dir`, read from the facts doc. Using `${SHARED_DOCS_DIR}` expands to empty, collapsing the path to `/development_lessons.md` and silently tripping the missing-corpus cold-start guard (gate never runs). Either hardcode the runtime symlink `${HOME}/Projects/.ai-playbook/development_lessons.md` (canonical-equivalent to `shared_docs_dir`) OR parse `shared_docs_dir` from `.ai-playbook/facts.md` at step entry - do NOT reference `${SHARED_DOCS_DIR}`. The gate validates the **user corpus only**; project files are NOT gated (convention). Guards:
  1. **Drift precheck (warn-only):** if the repo source AND runtime copies exist AND `diff -q` differs for `lessons_corpus.py` OR `lessons_index.py` OR `lessons_adopt.py` OR `lessons_migrate.py`, warn naming the drifted script(s) + the `cp` repo->runtime recipe; continue. If the repo source is absent (runtime-only deployment), emit a WARNING (not a silent note) that the gate's own integrity is unverified + continue. Warn-only (blocking deadlocks the `learn` that could fix it).
  2. **Missing-script cold-start:** `[[ -f "$script" ]]` or warn "gate script absent; install via the playbook repo" + exit 0.
  3. **Missing-corpus cold-start:** if the user corpus file does not exist (playbook not cloned / convention not adopted at user level yet), warn "user-level corpus absent; see `coding_guidelines.md` #17; run `lessons-migrate` to seed it" + exit 0.
  4. **Zero-tag cold-start:** if the user corpus has zero family tags, warn "convention not adopted in user corpus" + exit 0.
  5. **Adopted (blocking):** run `"$script" "$user_corpus"`; on non-zero exit, print the recovery recipe ("classify the listed `UL#N` via learn/generalize, OR run `lessons_adopt.py --tag-unclassified <user_corpus>` manually, then re-run `learn`") and **block** (exit 1). **(r3 Medium 9):** `lessons_adopt.py` is a manual tool (never invoked automatically); do NOT route it through `done`. **(r4 Medium 4):** because `learn` is invoked by `done` Step 1 as a SKILL (a sub-procedure, not a subprocess whose exit code `done` checks), "Step 6.6 blocks (exit 1)" means the `learn` skill returns `blocked` to its caller; `done` Step 1 MUST treat a blocked `learn` as a Step-1 failure (do NOT proceed to Step 2 commit) and fall through to `done`'s Step 6 lock-release (whose always-run guarantee at `done/SKILL.md:323` holds including when Steps 1-5 failed). The operator fixes the user corpus out-of-band before the next `done`.
  Document the strictness trade: a `learn` in any project blocks on a user-corpus violation because the user chose strict user-level; the corpus is single-user-local, so a block means "fix the user corpus." A standalone `learn` must NOT trigger `lessons_adopt.py`. `LESSONS_INDEX_SCRIPT` override is local-testing only.
- [x] **Project-tier dup check (warn-only, no script):** add a one-line checklist note - "project `development_lessons.md`: optional `grep -oE '^## [0-9]+' | sort | uniq -d` (warn-only); project files are convention and never block."
- [x] **Routing rule in `learn` Step 1 -> "Generalization pass" sub-section (the "Shared canonical" branch; r2: this is an unnumbered sub-section INSIDE Step 1 at `learn/SKILL.md:60-78`, NOT "Step 1.5" which is the unrelated Ralphex step at line 97):** REWORD the existing "Shared canonical" branch so the **first discriminator is abstract precept vs concrete lesson** (do not merely "extend" it - the existing branch routes any "correct in any project" rule to `coding_guidelines.md`). New fork: (1) **abstract precept** -> `coding_guidelines.md`; (2) **concrete cross-project lesson** -> **user-level corpus** (strict-tagged, next `UL#N`); (3) **project-specific** -> repo `development_lessons.md` (convention-tagged). Note the prior "place in `coding_guidelines.md`" guidance applied to *abstract* rules.
- [x] **Routing rule in `generalize`:** mirror the same reworded fork.
- [x] Add completion-checklist bullet: "Step 6.6 passed: `lessons_index.py <user corpus>` exits 0 (or warn-only cold-start); project files are convention (warn-only dup check)."
- [x] Verify `done`: `grep -rn 'Step 6\.5\|learn Step 6' ~/.agents/skills/done/SKILL.md` - confirm `done/SKILL.md:221,229` still point to the size gate (Step 6.5) as the recovery target (the step NUMBER is unaffected by inserting 6.6 after it); also confirm the "move infrequent rules to skills" phrasing at `done:229` stays coherent with the reworded 3-way Generalization-pass routing (r2 Low 3). Update only if wording implies a fixed step set. **(r5 Medium - done is NO LONGER "verify only"):** because the r4-Medium-4 block-propagation is a `done`-SIDE decision (Step 1 must not proceed to Step 2 commit when `learn` returns blocked), add an explicit Step-1 sub-step to `done/SKILL.md`: "If `learn` reports a blocked state (Step 6.6 user-corpus violation), release the lock via Step 6 and return `blocked` WITHOUT proceeding to Step 2 commit." (`learn` is a sub-procedure, not a subprocess whose exit code `done` checks, so the gate must live in `done`'s Step 1 text, not only in `learn`'s Step 6.6.)
- [x] Commit (skills repo): `feat(learn): Step 6.6 user-corpus gate (strict) + routing rule; feat: lessons-migrate skill`.

### Task 9: Final validation

- [x] All eight Validation Commands pass.
- [x] Runtime copies byte-identical to repo sources (Command 5).
- [x] `uv run pytest tests/unit/test_lessons_corpus_conformance.py -rs` -> user-corpus case PASSED (not SKIPPED); independence case PASSED.
- [x] Gate passes on the user corpus (Command 1); user corpus populated from tax-reporting migration.
- [x] Project file independent (Command 7): contiguous `#N`, no gate/corpus coupling.
- [x] Layering holds (Command 6): no user-level filename-qualified repo `#N` citation.
- [x] Migration skill `--selftest` exits 0; `--dry-run` on a second synthetic repo dedups against the populated user corpus correctly.
- [x] **Sibling repo-home decision (documented):** `done-lock.sh`/`scan-public-hygiene.sh` are runtime-only; `lessons_index.py`/`lessons_adopt.py`/`lessons_migrate.py` adopt the repo-homed model (canonical in `ai-playbook/scripts/`, synced to runtime). Documented in `lessons-migrate/SKILL.md` "How It Works" -> "Sibling script convention (mixed)".

## Monitor

- **Migrating other repos (sporty / other myrepos).** Each runs `lessons-migrate` once when ready; the skill dedups against the already-populated user corpus (merge flags reconcile overlaps). Owner: per-repo, when each repo adopts the convention.
- **Physical desegmentation (file-per-family).** Deferred. Owner: a future `lessons-desegmentation` plan.
- **Pre-emptive catalog-vs-`VALID_FAMILIES` automated check.** Deferred. Catalog growth surfaces visibly as an `invalid-family` failure at first use of a new family letter; the check is not load-bearing for safety. Owner: a future `lessons` plan if family growth becomes frequent.
- **Ambiguous + merge + unremappable-ref tails from migration.** The skill emits a review list per run; curate in a manual pass (promote, reconcile, hand-fix). Owner: the migration run's operator.
- **Project-tier tag rot.** Convention tags are unenforced and may drift over time (typos, missing); in-project AI recall is best-effort by design. If a project wants strictness, it can opt into a project-local gate later (not this plan). Owner: per-project decision.
- **Runtime<->repo drift of sibling scripts.** `check-instruction-size.sh` is already drifted; this plan fixes the drift model only for the three lessons scripts (Step 6.6 precheck). Uniformizing all siblings is out of scope. Owner: cross-project skills.
- **Mislabeled `Family <X>` tag promotes a project lesson to the shared corpus (r2).** Signal 1 takes a `Family <A-H>` tag at face value; a project lesson incorrectly tagged by a prior capture takes the fast lane and dedup (title/body) will not catch a content mismatch. Blast radius: every project's recall. After the first migration run, audit the promoted set for tag/content agreement; consider adding a promotion-time residue check that demotes high-residue tagged lessons to the review list. Owner: the migration run's operator, first run.
- **Stale-ref scan bound (r3 -> r4 redesign).** The in-corpus stale-ref scan is NO LONGER a value-scan over OLD numbers (r4 Blocker 1: the new compact range `1..M` is a subset of the OLD set, so a value-scan false-matches legitimately-rewritten same-tier citations). It is now a scan for discriminated lesson-`#N` tokens (OLD-set value, outside fences, `.md`-excluded) with value GREATER than the new project count M. Confirm the discriminator's `.md` exclusion and the `> M` bound still hold if future non-lesson `#N` tokens appear inside the corpus. Owner: Task 4 implementation.
- **No-concurrency-with-`learn` contract is unenforced (r4 Monitor 1).** With the resume subsystem removed (r3) and the mtime backstop dropped (r4 Medium 5), the sole protection for the shared user corpus against a concurrent `learn` append is a prose precondition with NO runtime detection. `learn` writes the user corpus in every project's run; the migrator runs in one repo; an operator who leaves a `learn` running in another terminal silently loses the capture (last-writer-wins). State plainly in `lessons-migrate/SKILL.md` that the operator must ensure no `learn` is running in any terminal before invoking the migrator. Full closure (flock sidecar) is out of scope. Owner: cross-project skills, if a capture is ever lost this way.
- **Classifier signal wording (r2; RESOLVED r3).** The spec now reads "Signals, evaluated in order (first match wins)" (was the misleading "strongest first"); signal 4 was dropped (r3 M5), so the "post-classification audit" caveat no longer applies. Kept as a closed marker. Owner: none (resolved).

Plan review: `docs/history/reviews/2026-06-29-plan-review-lessons-corpus-derived-index-r7.md` (latest, r7, ready) - confirmation panel on the r6 amendments; the process-prefix denylist (case-insensitive + `Invariant` + lead-in-enumeration audit) and the within-line `(#N)` cleanup verified correct against the real corpus; 0 Blockers, 0 Medium (one consistency flag was a verified false positive - `Design Invariant #2` IS present at corpus line 2092). Prior: `…-r6.md` (1 Medium + 1 Low).

Plan review: `docs/history/reviews/2026-06-29-plan-review-lessons-corpus-derived-index-r6.md` (r6) - process-prefix denylist made case-insensitive + `Invariant` added (`rule #6`/`finding #1`/`Design Invariant #2` would otherwise be silently corrupted) and a lead-in-enumeration audit added (the authoritative reconciliation does NOT catch a denylist miss, since the migrator confirms its own mis-discrimination); within-line cleanup of sole-content `(#N)` parentheticals on cross-tier removal + mid-prose removals flagged for prose review (r5 Option A residue; bounded surface - cluster lines are family-homogeneous). Prior: `…-r5.md` (1 Blocker + 5 Medium).

Plan review: `docs/history/reviews/2026-06-29-plan-review-lessons-corpus-derived-index-r5.md` (r5) - cross-tier resolution switched title-prose -> REMOVE (Option A; title-prose broke on quoted titles + multi-token clusters; both layers load into agent context so removal keeps discoverability); process-identifier denylist added to the discriminator (`Rule #4`/`Finding #1`/`Medium #1`/`DP-014 #6` no longer corrupted); reconciliation made authoritative remap-driven (`> M` coarse echo with documented low-numbered blind spot); backtick-strip tokenizer unified; `done/SKILL.md` promoted from verify-only to a Step-1 block-propagation edit. Prior: `…-r4.md` (3 Blockers + 6 Medium).

Plan review: `docs/history/reviews/2026-06-29-plan-review-lessons-corpus-derived-index-r4.md` (r4) - 3 Blockers fixed in plan (in-corpus reconciliation impossibility + cross-tier flag volume: unified discriminator-based rewrite; git-clean precondition broadened to full write scope) + 6 Medium addressed. Prior: `…-r3.md`.

Plan review: `docs/history/reviews/2026-06-29-plan-review-lessons-corpus-derived-index-r3.md` (r3) - 2 Blockers fixed in plan (cross-tier `UL#` contradiction; `${SHARED_DOCS_DIR}` silent dead-gate) + 9 Medium addressed. Prior: `…-r2.md` (1 Blocker + 10 Medium; r1 was ready=yes but a fresh panel found a fence-parser Blocker all prior rounds missed).
