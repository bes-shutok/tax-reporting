# Plan: Comparator combo-vocabulary extraction (module-size rule)

Backlog origin: `docs/history/backlog/2026-08-26-on-chain-review-followups.md` item 2
(review r2 overflow). Pure mechanical refactor; no behavior change.
Plan review: `docs/history/reviews/2026-08-26-plan-review-comparator-combo-extraction-r1.md` … `-r5.md` (all rounds).

## Terms

- **Combo vocabulary**: the adapter-derived `(Type, Tag)` vocabulary: the reverse
  combo map `_KOINLY_COMBO_TO_EVENT_TYPE`, its builder `_build_reverse_combo_map`
  (iterates the adapter's `EVENT_TYPE_TO_KOINLY` + `SUB_TYPE_TAG_OVERRIDES` and
  raises on a colliding combo), and the two lookup helpers `_event_type_of` /
  `_row_combo`.
- **Module-attribute read**: the builder reads `_adapter.EVENT_TYPE_TO_KOINLY` and
  `_adapter.SUB_TYPE_TAG_OVERRIDES` via the adapter MODULE attribute at call time;
  this is what lets tests monkeypatch `on_chain_th_adapter` and be seen; it must
  survive the move.
- **Module-size rule**: repo rule (AGENTS.md); modules over 1,000 lines extract
  cohesive responsibilities into separate modules.
- **Skill-gate marker / Session key**: see the Terms of
  `2026-08-26-on-chain-staleness-refusal.md` (same recipe: refresh
  `plans.<project>.<session>.marker` via `skill_gate.py --write-marker` before every
  Write/Edit to this plan file; FAIL-LOUD).

## Gist & Examples

`src/tax_reporting/application/on_chain_validation/comparator.py` is 1023 lines on
master (72ccf59), over the 1,000-line module rule. The combo-vocabulary block inside
it is a cohesive unit with a single collaborator (the adapter): the reverse-map
builder with its injectivity guard, the import-time `Final` map, and the two row
lookups (`_event_type_of` at :492, used at :682/:786/:833/:917; `_row_combo` at
:488, used at :787/:854).

This plan extracts that block into a new module
`src/tax_reporting/application/koinly_combo_map.py`; placed next to
`on_chain_th_adapter.py`, the module it reads; with public names:

- `build_reverse_combo_map` (was `_build_reverse_combo_map`)
- `KOINLY_COMBO_TO_EVENT_TYPE` (was `_KOINLY_COMBO_TO_EVENT_TYPE`)
- `event_type_of` (was `_event_type_of`)
- `row_combo` (was `_row_combo`)
- `koinly_text` (was comparator-private `_koinly_text`, :405) and
  `koinly_tag` (was `_koinly_tag`, :440); the row-field readers `row_combo`
  depends on; they move too because importing them back from `comparator` would
  be circular (comparator imports the new module). Comparator's OTHER uses of
  the two readers keep working via the import (r1-F1).

`comparator.py` imports the six names and updates its call sites. Behavior is
identical: the injectivity guard still raises at import naming the colliding
combo; the map is still derived automatically from the adapter vocabulary (no
manual registration); the builder still reads the adapter module attributes at
call time so the existing monkeypatch seam (tests patch `on_chain_th_adapter`,
e.g. `test_on_chain_validation_comparator.py:493-512`) keeps working. After the
move, comparator's `koinly_combo` import (:84) and `_adapter` alias (:81) become
unused and are removed (confirm with `ruff check` on the touched files).

Line math (r3-F1, measured): ~55-60 lines move out, ~6 come back as imports →
comparator lands ~970 lines, under the rule (the `wc -l < 1000` gate enforces it
regardless of the estimate). If still over 1,000 after the move, also move the
`#:` documentation blocks that document the moved symbols (the size rule is the
driver; do not move unrelated constants like `DISPLAY_TOLERANCE_PER_ROW` or the
`EVENT_COMPATIBILITY` table).

## Evaluation Criteria

**Quality dimensions:**
- Correctness/behavior identity: the collision + vocabulary-pin tests pass unchanged
  in behavior from the new module; full validation test files GREEN before and after.
- Maintainability: `comparator.py` < 1,000 lines; the extracted module owns exactly
  the combo vocabulary with its docs.
- Seam safety: no test needs to change WHAT it patches; only WHERE the moved names
  are imported from; the adapter monkeypatch sites are untouched.

**Done when:**
- `wc -l src/tax_reporting/application/on_chain_validation/comparator.py` < 1000.
- Import-resolution check passes (`uv run python -c "from tax_reporting.application.koinly_combo_map import ..."`).
- No stale imports of the moved private names from `comparator` anywhere in `src/` or
  `tests/` (fail-closed sweep below).
- Full `uv run pytest -q` suite green.

**Ship when:**
- None beyond the repository (pure refactor).

## Review Scope

**Explicit must-fix**; findings on these paths are always in scope (review and fix if valid):

**Production code:**
- `src/tax_reporting/application/koinly_combo_map.py` *(new)*
- `src/tax_reporting/application/on_chain_validation/comparator.py`

**Tests:**
- `tests/unit/application/test_koinly_combo_map.py` *(new; collision + vocabulary-pin tests moved/extended here)*
- `tests/unit/application/test_on_chain_validation_comparator.py`

**Plan-related extension**; implementation and review may change files not listed above.
Treat a finding as in scope when it is causally related to this plan: it implements or
completes a plan task, fixes a regression introduced by plan work, closes wiring or docs
implied by an explicit must-fix change, or contradicts a contract the plan changed.
If the link to the plan is weak or speculative, drop as out of scope with a one-line reason.

**Out of scope; reject unless plan-related:**
- `src/tax_reporting/application/on_chain_th_adapter.py`; the vocabulary source does
  not move and gains no members.
- `src/tax_reporting/application/on_chain_validation/clustering.py`, `artifacts.py`,
  `dispositions.py`, `runner.py`; they import only non-moved comparator names
  (`ThComparisonRecord`, `compare_projection`, `ComparisonResult`, `Presence`).

## Design Invariants (CR Guard)

- **Injectivity guard unchanged**: `build_reverse_combo_map` raises at import on any
  colliding `(type, tag)` combo, naming the colliding pair and both source dicts;
  same message text, same trigger.
- **Automatic derivation**: the reverse map stays derived from the adapter's
  `EVENT_TYPE_TO_KOINLY` + `SUB_TYPE_TAG_OVERRIDES` at import; no manual
  registration step appears.
- **Module-attribute reads preserved**: the builder reads the adapter attributes via
  the module object (not `from`-imports of the dicts); the documented test-patch
  visibility seam.
- **Acyclic by construction (r1-F1)**: `koinly_combo_map` imports only
  `on_chain_th_adapter` and the domain enum; `comparator` imports from
  `koinly_combo_map`; nothing imports back into `koinly_combo_map`.
- **No vocabulary change**: `SUB_TYPE_TAG_OVERRIDES` keeps exactly one entry
  (`(Reward, bridge) -> "Bridge"`); `EVENT_TYPE_TO_KOINLY` is untouched.
- **No frozen-contract drift**: the `EVENT_COMPATIBILITY` table and
  `DISPLAY_TOLERANCE_PER_ROW` stay in `comparator.py` untouched.

## Validation Commands

```bash
test -f src/tax_reporting/application/koinly_combo_map.py \
  || { echo "koinly_combo_map.py missing"; exit 1; }
[ "$(wc -l < src/tax_reporting/application/on_chain_validation/comparator.py)" -lt 1000 ] \
  || { echo "comparator.py still >= 1000 lines"; exit 1; }
uv run python -c "from tax_reporting.application.koinly_combo_map import KOINLY_COMBO_TO_EVENT_TYPE, build_reverse_combo_map, event_type_of, row_combo, koinly_text, koinly_tag" \
  || { echo "import resolution failed"; exit 1; }

# No stale imports of the moved private names from the comparator module:
if grep -rn "on_chain_validation.comparator import" src/ tests/ | grep -e "_build_reverse_combo_map" -e "_KOINLY_COMBO_TO_EVENT_TYPE" -e "_event_type_of" -e "_row_combo" -e "_koinly_text" -e "_koinly_tag"; then
  echo "stale comparator imports of moved names"; exit 1
fi
# No lingering string-form/attr patches on the moved names at the old home:
if grep -rn "comparator\._event_type_of\|comparator\._row_combo\|comparator\._build_reverse_combo_map\|comparator\._KOINLY_COMBO\|comparator\._koinly_text\|comparator\._koinly_tag" src/ tests/; then
  echo "stale patch/attribute references at old home"; exit 1
fi
# No stale moved-name mentions in the maintenance doc (doc-drift rule; r1-F4;
# test -f keeps the sweep fail-closed if the doc is ever absent; r4-F1):
test -f docs/maintenance/on_chain_validation.md || { echo "missing maintenance doc"; exit 1; }
if grep -n "_build_reverse_combo_map\|_event_type_of\|_row_combo\|_KOINLY_COMBO_TO_EVENT_TYPE\|_koinly_text\|_koinly_tag" docs/maintenance/on_chain_validation.md; then
  echo "stale moved-name mention in on_chain_validation.md"; exit 1
fi

uv run pytest tests/unit/application/test_koinly_combo_map.py \
  tests/unit/application/test_on_chain_validation_comparator.py \
  tests/unit/application/test_on_chain_validation_clustering.py \
  tests/unit/application/test_on_chain_validation_artifacts.py -q
uv run pytest -q
```

(The stale-name sweeps are negated greps: `if grep ...; then exit 1`; a match is a
failure. They do not sweep this plan file, whose mention of the names is the checker
literal itself.)

### Task 1: characterization baseline

- [ ] Run → expect GREEN (characterization: captures existing behavior before the
  refactor): `uv run pytest tests/unit/application/test_on_chain_validation_comparator.py tests/unit/application/test_on_chain_validation_clustering.py tests/unit/application/test_on_chain_validation_artifacts.py -q`

### Task 2: extract the module

Files:
- `src/tax_reporting/application/koinly_combo_map.py` *(new)*
- `src/tax_reporting/application/on_chain_validation/comparator.py`

- [ ] Create `koinly_combo_map.py` with the moved block: the reverse-map `#:` docs,
  `build_reverse_combo_map`, `KOINLY_COMBO_TO_EVENT_TYPE` (import-time `Final` built
  via `build_reverse_combo_map()`), `event_type_of`, `row_combo`, and the row-field
  readers `koinly_text`/`koinly_tag` it depends on; public names, module docstring
  stating the adapter is the single vocabulary source and that the builder
  deliberately reads the adapter module attributes at call time (test-patch
  visibility)
- [ ] In `comparator.py`: import the six names from the new module and update all
  call sites (`event_type_of` :682/:786/:833/:917; `row_combo` :787/:854; the other
  `koinly_text`/`koinly_tag` uses stay via the import); remove the moved definitions
  and the now-unused `koinly_combo` import + `_adapter` alias (verify with
  `git show HEAD:src/tax_reporting/application/on_chain_validation/comparator.py | ruff check -` first, per repo ruff rule); keep everything else byte-identical
- [ ] Verify the import graph is acyclic (new module imports only
  `on_chain_th_adapter` + the domain enum): `uv run python -c "from tax_reporting.application.koinly_combo_map import KOINLY_COMBO_TO_EVENT_TYPE, build_reverse_combo_map, event_type_of, row_combo, koinly_text, koinly_tag"`
- [ ] Run → expect GREEN (characterization still passes):
  `uv run pytest tests/unit/application/test_on_chain_validation_comparator.py tests/unit/application/test_on_chain_validation_clustering.py tests/unit/application/test_on_chain_validation_artifacts.py -q`
- [ ] Commit: `refactor(on-chain): extract the Koinly combo vocabulary into koinly_combo_map`

### Task 3: retarget the collision + vocabulary-pin tests

Files:
- `tests/unit/application/test_koinly_combo_map.py` *(new)*
- `tests/unit/application/test_on_chain_validation_comparator.py`

- [ ] Move the collision tests; the WHOLE tests including their
  `@pytest.mark.parametrize` decorators and params (~`test_on_chain_validation_comparator.py:478-512`,
  the two `_build_reverse_combo_map` imports); into `test_koinly_combo_map.py` AS
  `TestKoinlyComboMap#test_reverse_map_collision_raises` (given a patched
  `SUB_TYPE_TAG_OVERRIDES` producing a duplicate `(type, tag)` combo, expects the
  builder to raise naming the colliding combo) and
  `TestKoinlyComboMap#test_reverse_map_bad_forward_map_raises` (given a patched
  `EVENT_TYPE_TO_KOINLY` whose inversion is not injective, expects the builder to
  raise naming the base map), importing `build_reverse_combo_map` /
  `KOINLY_COMBO_TO_EVENT_TYPE` from the new module; the adapter
  `monkeypatch.setattr` sites stay pointed at `on_chain_th_adapter` (r1-F3: the
  move unit is whole tests, not statements; r2-F1: these two names DESCRIBE the
  moved tests; do not also add fresh duplicates)
- [ ] ADD the one net-new vocabulary-pin test (r1-F2; none exists today):
  `TestKoinlyComboMap#test_reverse_map_tracks_adapter_vocabulary`; given the real
  adapter vocabulary, expects every override combo in `KOINLY_COMBO_TO_EVENT_TYPE`
  to invert `koinly_combo()` exactly
- [ ] Symbol-move patch audit: `grep -rn "_event_type_of\|_row_combo\|_build_reverse_combo_map\|_KOINLY_COMBO_TO_EVENT_TYPE\|_koinly_text\|_koinly_tag" src/ tests/`; every remaining hit is either the renamed old-name reference being updated or an unrelated string; list each in the task log (r2-F2: the audit covers the two reader names too)
- [ ] Run → expect GREEN: `uv run pytest tests/unit/application/test_koinly_combo_map.py tests/unit/application/test_on_chain_validation_comparator.py -q`
- [ ] Commit: `test(on-chain): collision + vocabulary-pin tests move to koinly_combo_map home`

### Task 4: size rule + docs + full validation

Files:
- `docs/maintenance/on_chain_validation.md`

- [ ] Update the moved-name mention in `on_chain_validation.md` (~:358 names
  `_build_reverse_combo_map` and the comparator as owner) to the new public name and
  the `koinly_combo_map` owner (r1-F4; repo doc-drift rule)
- [ ] Run the Validation Commands block end-to-end; all green (incl. `wc -l` < 1000
  and both fail-closed stale-name sweeps)
- [ ] `uv run pytest -q` full suite green
