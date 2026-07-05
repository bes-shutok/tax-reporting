# Plan: OGR Event-Level Application (Agree-Branch Multi-Lot Over-Count Fix)

Fixes the over-counting bug in the OGR direction override that the RFC
`docs/history/feature-notes/2026-06-20-th-anchored-transaction-state-machine.md` was un-shelved
to address. This is a **surgical fix**, not the RFC's full TH-anchored Transaction view. The
Transaction view (TH anchors, minute-precision identity, TxHash correlation) is deferred: prior
review rounds on the fuller scope showed its mechanisms (minute-precision keys across two
reports, raw-row threading past `_split_ogr_index`) generate edge cases the OGR fix does not
need. Revisit the Transaction view only when the payment-proceeds (Phase 2) or derivatives
routing (Phase 3) migration demands it.

Plan review: `docs/history/reviews/2026-07-04-plan-review-ogr-event-level-application-r1.md`
(r1 - not ready: 2 Blockers + 9 Medium; all addressed in this revision by adopting the
first-lot-absorbs distribution, which dissolves the largest-remainder / zero-cost / residue
findings, plus the two Blocker fixes).

## Terms

- **CG** - Koinly Capital Gains report. One CG row = one FIFO lot. A single disposal event
  produces N CG lots sharing a `(date, asset, wallet)` key.
- **OGR** - Koinly Other Gains Report. `_build_ogr_index` (`ogr_handler.py:147`) SUMS all OGR
  rows sharing `(date, asset, wallet)` into one `Decimal` "index entry". For the spot path,
  one `(date, asset, wallet)` key maps to one disposal event and one summed OGR entry.
- **`cg_event_gain`** - sum of an event's CG lot `gain_loss_eur` BEFORE the override.
- **`ogr_event_gain`** - the summed OGR entry value for the event (authoritative realization).
- **Agree branch vs conflict branch** - the legacy override has two paths (agree = CG and OGR
  same sign; conflict = opposite signs). The over-counting bug lives ONLY in the agree branch.
- **First-lot-absorbs** - the chosen distribution: write the full `ogr_event_gain` to the FIRST
  lot of the event (in input order) and zero to the rest. Because aggregation SUMS
  `gain_loss_eur` and `proceeds_eur` across the event's lots (`aggregation.py:327`), the
  aggregated row is `event_cost + ogr_event_gain` and `ogr_event_gain` byte-exactly, with no
  cost-share division and no rounding. Per-lot attribution is consumed nowhere user-facing.

## Gist & Examples

**Problem (agree-branch multi-lot only).** `_apply_ogr_direction_override`
(`src/tax_reporting/application/crypto/ogr_handler.py:441`) iterates each CG lot, looks it up
in the summed OGR `spot_index` by `(date, asset, wallet)`, and writes a per-lot
`final_gain_loss`:

- **Agree branch** (`ogr_handler.py:524-526`): `final_gain_loss = ogr_gain_loss` - the FULL OGR
  value is written to EVERY lot via `replace(entry, gain_loss_eur=final_gain_loss,
  proceeds_eur=entry.cost_eur + final_gain_loss)` (`ogr_handler.py:555-562`). For N lots,
  aggregation sums to **N x OGR_gain**. THIS is the over-counting.
- **Conflict branch** (`ogr_handler.py:511-514`): `final_gain_loss = ±abs(entry.gain_loss_eur)`
  - CG magnitude (per lot), OGR sign. Summed across lots this equals `±abs(total_cg)`. **Not
  over-counted.** The existing 109-lot fixture (`test_crypto_reporting.py:8757`, CG +500 /
  OGR -147.19) exercises this and is already correct.

The bug is latent in FY2025 production data (0 spot CG keys match any OGR index entry), but
multi-lot keys are common (226 of 473 CG keys are multi-lot, up to 121 lots), so the first
future export with an agree-branch multi-lot OGR match silently over-counts into an IRS filing.

**Fix (first-lot-absorbs).** Replace the per-lot override with `apply_ogr_event_level`, which
groups CG lots into events by `(date, asset, wallet)`, decides direction/magnitude ONCE on
event totals, and writes the result to the FIRST lot only:
- **Agree branch:** the first lot gets `gain_loss_eur = ogr_event_gain`,
  `proceeds_eur = first_lot.cost_eur + ogr_event_gain`; the remaining lots get
  `gain_loss_eur = 0`, `proceeds_eur = lot.cost_eur`. `sum(gain_loss_eur) == ogr_event_gain`
  and `sum(proceeds_eur) == event_cost + ogr_event_gain` byte-exactly (no division).
- **Conflict branch:** UNCHANGED - each lot keeps `±abs(lot.gain_loss_eur)` with OGR sign,
  which already sums to `±abs(cg_event_gain)`.
- **Single-lot events (both branches):** there is no "rest", so agree reduces to
  `gain_loss_eur == ogr_event_gain` and conflict is untouched - byte-identical to legacy.

**Example (agree branch).** A `USDT / ByBit` disposal on `2025-02-01` spans 110 lots, combined
cost `100.00 EUR`, combined CG gain `+5.00`; an OGR entry reports `+4.50` (agree).
- Legacy: each lot gets `4.50` -> aggregated gain `495.00` (over-counted ~110x).
- Phase 1: lot 0 gets `gain_loss_eur = 4.50`, lots 1..109 get `0.00` -> aggregated gain
  `4.50` (correct, byte-exact, no rounding).

**Cross-holding-period is a real taxable change, not reduction-to-legacy.** A multi-lot event
whose lots span short and long holding periods is split across two aggregation groups
(`aggregation.py:278` keys on `holding_period`). Legacy over-counted EACH group
(`|group| x ogr_gain_loss`); Phase 1 puts the whole `ogr_event_gain` on lot 0, so the
short-vs-long taxable split (PT-C-011: short-term taxable, long-term exempt) shifts to wherever
lot 0 lands. This is a deliberate, documented delta (the legacy per-group numbers were wrong
anyway), surfaced in tests and in the PT-C-037 rule - NOT a "reduction-to-legacy" claim.

**Regression bar.** Current-data Excel is byte-identical (0 OGR matches). Agree-branch
multi-lot synthetic fixtures change to the correct number and are asserted in tests.
Conflict-branch fixtures (the 109-lot test) and all single-lot fixtures stay byte-identical.

## Evaluation Criteria

**Quality dimensions:**
- Correctness: a multi-lot AGREE-branch disposal with an OGR match reports `ogr_event_gain`
  exactly once - `sum(lot.gain_loss_eur) == ogr_event_gain` byte-exactly (first-lot-absorbs) -
  with the full gain on the first lot and zero on the rest.
- Reduction-to-legacy: single-lot events (both branches) and CONFLICT-branch multi-lot events
  are byte-identical to the pre-Phase-1 baseline.
- No-silent-drop / order preservation: `len(out) == len(in)` and `out[i]` corresponds to
  `in[i]` on the full base identity `(disposal_date, acquisition_date, cost_eur,
  holding_period, disposal_timestamp, pre_OGR_proceeds_eur, pre_OGR_gain_loss_eur)` (the re-zero
  snapshot/restore at `crypto_reporting.py:288-340` consumes output by index).
- Aggregation fidelity: each lot's `OgrValidationResult.ogr_gain_loss == ogr_event_gain` (FULL
  event value on every lot, because `_aggregate_ogr_validation` reads it from the first lot at
  `aggregation.py:217-218`) and `calculated_gain_loss == lot's PRE-distribution CG`, so the
  re-derived direction/magnitude against `cg_event_gain` is correct.
- Zero-cost safety: a zero-`event_cost` event never raises (first-lot-absorbs does not divide).
- Documented delta: the cross-holding-period taxable split shift on agree-branch multi-lot
  events is asserted in a test and cited to PT-C-011.

**Release gates:**
- `uv run pytest` green (full suite).
- Current-data Excel baseline unchanged (documented-delta exception only for synthetic
  agree-branch multi-lot fixtures, each asserted).
- No new hardcoded constants without a decision-point citation.

## Review Scope

**Explicit must-fix**; findings on these paths are always in scope (review and fix if valid):

**Production code:**
- `src/tax_reporting/application/crypto/ogr_event_level.py` *(new)*
- `src/tax_reporting/application/crypto/ogr_handler.py`
- `src/tax_reporting/application/crypto_reporting.py`

**Tests:**
- `tests/unit/application/test_crypto_reporting.py`

**Plan-related extension**; implementation and review may change files not listed above.
Treat a finding as in scope when it is causally related to this plan: it implements or
completes a plan task, fixes a regression introduced by plan work, closes wiring or docs
implied by an explicit must-fix change, or contradicts a contract the plan changed. If the
link to the plan is weak or speculative, drop as out of scope with a one-line reason.

**Out of scope; reject unless plan-related:**
- `src/tax_reporting/application/crypto/payment_proceeds.py`; Phase 2.
- `src/tax_reporting/application/crypto/derivatives_dedup.py`; Phase 3. Phase 1 must NOT alter
  derivatives dedup behavior or the spot/derivatives split in `_split_ogr_index`.
- `src/tax_reporting/application/crypto/fee_filter.py`, `crypto_fifo.py`; unchanged.
- `src/tax_reporting/application/crypto/aggregation.py`; unchanged (Phase 1 must preserve the
  `calculated_gain_loss` and `ogr_gain_loss` contracts `_aggregate_ogr_validation` reads).

## Design Invariants (CR Guard)

1. **Branch-aware; agree branch is first-lot-absorbs.**
   - Agree branch: write `ogr_event_gain` to the FIRST lot of the event (input order) as
     `gain_loss_eur`, with `proceeds_eur = first_lot.cost_eur + ogr_event_gain`; write
     `gain_loss_eur = 0` and `proceeds_eur = lot.cost_eur` to the remaining lots. The per-lot
     values are consumed nowhere user-facing; aggregation sums them to the byte-exact event
     total. Rationale (simplification): cost-share distribution buys per-lot attribution no
     consumer reads and introduces largest-remainder rounding, a zero-`event_cost` division
     crash, and (for the FIRST lot) a residue-on-Payment-lot re-zero interaction - none of which
     first-lot-absorbs has for lot 0. A NON-first Payment lot can still be flipped by the re-zero
     restore (see Monitor: Re-zero / payment-proceeds interaction, owner Phase 2); the
     residue-free guarantee is scoped to lot 0.
   - Conflict branch: UNCHANGED from legacy - each lot keeps `±abs(lot.gain_loss_eur)` with
     OGR sign. The existing 109-lot conflict fixture pins byte-identity.
   - Single-lot events (both branches) reduce exactly to legacy output.
2. **Event identity is the existing `(date, asset, wallet)` key.** CG lots are grouped by the
   same key the OGR `spot_index` uses. NOTE (not a no-collision proof): two genuinely distinct
   same-day spot disposals that share this key pool into one event under both legacy and Phase
   1; Phase 1 additionally pools their cost bases for the first-lot write. This is a pre-existing
   key collapse documented in Monitor, not resolved here; current FY data has 0 OGR matches so
   the pooling is unobservable today. No TH anchors, no minute precision, no TxHash in Phase 1.
3. **`OgrValidationResult` per-lot contract.** Each lot in an OGR-matched event carries
   `ogr_validation` with: `ogr_gain_loss == ogr_event_gain` (the FULL event value on EVERY lot,
   because `_aggregate_ogr_validation` reads it from the first lot at `aggregation.py:217-218`
   and must see the full value), and `calculated_gain_loss == lot's PRE-distribution CG gain`
   (so aggregation's sum reconstructs `cg_event_gain` and the re-derived direction/magnitude is
   correct). Copying the legacy `calculated_gain_loss=entry.gain_loss_eur` pattern AFTER the
   override would put distributed values here and silently suppress every aggregated flag.
4. **Cross-holding-period is a deliberate taxable delta.** Phase 1 places the whole
   `ogr_event_gain` on lot 0, so an event spanning two holding periods shifts the short-vs-long
   taxable split (PT-C-011) vs legacy's per-group over-count. This is asserted in a test and
   documented in PT-C-037; it is NOT reduction-to-legacy.
5. **Pipeline ordering and 1:1 in-order output.** OGR event-level application still runs BEFORE
   `_aggregate_capital_entries`. The re-zero snapshot/restore *code*
   (`crypto_reporting.py:288-340`, gated by `infer_payment_proceeds_active`) is NOT edited, but
   the function whose output it snapshots IS replaced; `apply_ogr_event_level` MUST return lots
   in original input order with `len(out) == len(in)` and per-index identity, pinned by test.
6. **Derivatives excluded.** When `separate_derivatives_reporting` is active, derivatives rows
   are routed out of `spot_index` by `_split_ogr_index` before the override sees it. Phase 1
   consumes `spot_index` exactly as today; only the per-lot-vs-per-event math changes.

## Validation Commands

```bash
# Full suite (Phase 1 must be green; current-data baseline unchanged)
uv run pytest

# Targeted: OGR override + aggregation interaction + re-zero interaction
uv run pytest tests/unit/application/test_crypto_reporting.py -v -k "ogr or OGR or override or aggregate_ogr or rezero or re_zero"

# Terminal state: legacy symbols gone. Zero call/import sites for both the per-lot override
# and the dead _apply_ogr_overrides helper (docstring PROSE mentions documenting the legacy
# behavior are expected and tolerated; the Pre-GREEN triage classifies them as PROSE, not calls).
! grep -rn "_apply_ogr_direction_override(\|_apply_ogr_overrides(" src/ tests/

# Confirm out-of-scope freeze: derivatives split + aggregation signatures unchanged
grep -rn "def _split_ogr_index\|def _aggregate_ogr_validation" src/tax_reporting/application/crypto/

# Re-export wiring: apply_ogr_event_level is exported via crypto_reporting; legacy symbols are not
grep -n "apply_ogr_event_level\|_apply_ogr_direction_override\|_apply_ogr_overrides" src/tax_reporting/application/crypto_reporting.py

# Pre-GREEN triage: enumerate every OGR fixture before changing assertions
grep -rn "_apply_ogr_direction_override\|spot_index\|apply_ogr_event_level\|_apply_ogr_overrides" tests/
```

### Task 1: `apply_ogr_event_level` - branch-aware, first-lot-absorbs, in-order

Files:
- `src/tax_reporting/application/crypto/ogr_event_level.py` *(new - extracted; `ogr_handler.py`
  is at the orchestration ceiling and this keeps the new logic in a focused module)*
- `src/tax_reporting/application/crypto/ogr_handler.py`
- `src/tax_reporting/application/crypto_reporting.py`
- `tests/unit/application/test_crypto_reporting.py`

- [x] `TestApplyOgrEventLevel#agree_multi_lot_first_lot_absorbs`; given 3 lots (distinct
  `acquisition_date` so the base identity is unique; costs 10/30/60; single holding period)
  with `cg_event_gain +3.00` and OGR `+9.00` (agree), expects by INPUT INDEX:
  `result[0].gain_loss_eur == 9.00 AND result[0].proceeds_eur == result[0].cost_eur + 9.00`;
  `result[1].gain_loss_eur == 0 AND result[1].proceeds_eur == result[1].cost_eur`; same for
  `result[2]`; `sum(gain_loss_eur) == Decimal("9.00")` byte-exactly
- [x] `TestApplyOgrEventLevel#agree_multi_lot_ogr_gain_loss_full_on_every_lot`; for the same
  event, expects `result[0].ogr_validation.ogr_gain_loss == 9.00` AND
  `result[1].ogr_validation.ogr_gain_loss == 9.00` AND `result[2].ogr_validation.ogr_gain_loss
  == 9.00` (FULL event value on every lot), and each `calculated_gain_loss == that lot's
  PRE-distribution CG gain`
- [x] `TestApplyOgrEventLevel#conflict_multi_lot_byte_identical_to_legacy`; given the existing
  109-lot fixture (CG `+500`, OGR `-147.19`), expects each lot keeps
  `gain_loss_eur == -abs(per_lot_gain)` and `proceeds_eur == cost - abs(per_lot_gain)`
- [x] `TestApplyOgrEventLevel#single_lot_agree_byte_identical`; given a 1-lot agree event,
  expects `gain_loss_eur == ogr_gain_loss`, `proceeds_eur == cost + ogr_gain_loss`
- [x] `TestApplyOgrEventLevel#single_lot_conflict_byte_identical`; given a 1-lot conflict event
  (CG `+4.00`, OGR `-1.00`), expects `gain_loss_eur == -4.00`,
  `proceeds_eur == cost - 4.00`
- [x] `TestApplyOgrEventLevel#calculated_gain_loss_reconstructs_cg_event_gain_after_aggregation`;
  the test MUST call `_aggregate_capital_entries(apply_ogr_event_level(...))` (or
  `_aggregate_ogr_validation` directly on one aggregated row's lots). Given a 3-lot agree event
  (CG lots `+1/+1/+1`, OGR `+9.00`), expects the AGGREGATED `OgrValidationResult`:
  `ogr_gain_loss == 9.00`, `calculated_gain_loss == 3.00`,
  `magnitude_diff_percent == Decimal("200.0")`, `review_required is True`. (A per-lot
  `magnitude_diff_percent` of 800% is expected and must NOT be the asserted value.)
- [x] `TestApplyOgrEventLevel#direction_conflict_event_level_decision`; given a multi-lot event
  where summed CG is a gain but OGR is a loss, expects the conflict path taken on the SIGN of
  EVENT totals (`cg_event_gain` vs `ogr_event_gain`); the `> 1 EUR` significance gate is
  review-only, not part of the branch decision (development_lessons.md #42)
- [x] `TestApplyOgrEventLevel#agree_multi_lot_zero_event_cost_no_raise`; given N zero-`cost_eur`
  lots sharing a key with an OGR row, expects NO exception and the event handled (first lot
  absorbs `ogr_event_gain`; no division by `event_cost`)
- [x] `TestApplyOgrEventLevel#no_ogr_match_unchanged`; given events with no OGR entry, expects
  lots pass through with `ogr_validation=None`
- [x] `TestApplyOgrEventLevel#output_length_and_order_preserved`; given mixed input where each
  lot has a UNIQUE base identity tuple `(disposal_date, acquisition_date, cost_eur,
  holding_period, disposal_timestamp, pre_OGR_proceeds_eur, pre_OGR_gain_loss_eur)` - unmatched
  lot, single-lot OGR event, multi-lot OGR event, zero-proceeds Payment lot - expects
  `len(out) == len(in)` and each `out[i]` matches `in[i]` on that tuple
- [x] `TestApplyOgrEventLevel#cross_holding_period_agree_event_taxable_split_delta`; given a
  multi-lot agree event whose lot 0 is short-term and another lot is long-term, OGR `+9.00`,
  run `apply_ogr_event_level` + `_aggregate_capital_entries`, and assert the SHORT-TERM
  aggregated group carries the full `+9.00` (because lot 0 is short-term) and the LONG-TERM
  group carries `0.00` from this event - documenting the PT-C-011 split shift vs legacy's
  per-group over-count. Pin this as the agreed delta, not a regression.
- [x] Run -> expect RED: `uv run pytest tests/unit/application/test_crypto_reporting.py -v -k "ogr or OGR or override or aggregate_ogr or rezero or re_zero"`
- [x] Pre-GREEN triage: run the Validation Command grep. For each hit, classify it as a CALL
  vs. PROSE (docstring) before rewriting. Enumerated call/import sites in
  `tests/unit/application/test_crypto_reporting.py`: import block lines 27-28 (covers
  `_apply_ogr_direction_override` and `_apply_ogr_overrides`); section header 8058; direct
  `_apply_ogr_overrides` calls at 8112, 8170, 8221, 8273, 8324; in-method imports of
  `_apply_ogr_direction_override` at 9661-9664 and 9725-9728; direct calls at ~8516, 8576,
  8636, 8693, 8747, 8813, 8882, 8967, 9662, 9699, 9726, 9762; the 109-lot fixture at 8757;
  docstring prose at ~9654 and 10856 (PROSE edits, not call rewrites). Mechanically rewrite
  each CALL site's setup (`spot_index = {(d,a,w): Decimal(X)}` stays - signature unchanged)
  and call (`_apply_ogr_direction_override(...)` -> `apply_ogr_event_level(...)`). Update
  assertions only for agree-multi-lot fixtures, with a `# Phase 1 event-level` comment.
- [x] Implement `apply_ogr_event_level(capital_entries, spot_index, jurisdiction)` in the NEW
  module `ogr_event_level.py`, with the SAME signature as the legacy function (`spot_index`
  stays the summed `dict[(date,asset,wallet), Decimal]`; no raw-row threading). Internally:
  group lots into events by `(date, asset, wallet)` preserving first-seen order; for each event
  with an OGR entry, decide agree vs conflict on `cg_event_gain` vs `ogr_event_gain` by SIGN on
  event totals (the `> 1 EUR` significance gate is review-only - it controls the per-lot/per-event
  review flag and is NOT part of the branch decision; see development_lessons.md #42); agree ->
  first-lot-absorbs (no division); conflict -> per-lot `±abs(lot.gain_loss_eur)` unchanged;
  write `ogr_validation` with `ogr_gain_loss == ogr_event_gain` (full, every lot) and
  `calculated_gain_loss == PRE-distribution CG`; return lots in original input order. Keep the
  orchestrator thin via named collaborators (`_decide_event_branch`, `_apply_agree_first_lot`,
  `_apply_conflict_unchanged`).
- [x] Wire: at `crypto_reporting.py:67-73` replace the imported `_apply_ogr_direction_override`
  with `apply_ogr_event_level` (re-export the new public name); update the call at
  `crypto_reporting.py:313`. DELETE `_apply_ogr_direction_override` from `ogr_handler.py`.
- [x] Run -> expect GREEN
- [x] Commit: `feat(crypto): apply OGR P&L at event level, first-lot-absorbs (agree-branch fix)`

### Task 2: Remove dead `_apply_ogr_overrides` and migrate its tests

Files:
- `src/tax_reporting/application/crypto/ogr_handler.py`
- `src/tax_reporting/application/crypto_reporting.py`
- `tests/unit/application/test_crypto_reporting.py`

`_apply_ogr_overrides` (`ogr_handler.py:357`, 134 lines) has ZERO production callers - it is
re-exported with `# noqa: F401` only and exercised solely by tests at
`test_crypto_reporting.py:8058-8324` (the older pre-split override). It predates the
`_apply_ogr_direction_override` split and is dead.

- [x] `TestApplyOgrEventLevel#migrated_loss_override_applies`; migrate `test_ogr_loss_override_applied`
  (8112) onto `apply_ogr_event_level`, asserting the single-lot loss override still applies
- [x] `TestApplyOgrEventLevel#migrated_no_override_when_disabled`; migrate
  `test_ogr_no_override_when_disabled` (8221), asserting disabled-jurisdiction lots are unchanged
- [x] `TestApplyOgrEventLevel#migrated_skips_fee_tokens`; migrate `test_ogr_skips_fee_tokens`
  (8324), asserting fee-token rows remain excluded
- [x] (Migrate or delete the remaining two - `test_ogr_profit_override_applied` 8170,
  `test_ogr_no_override_when_no_match` 8273 - onto `apply_ogr_event_level`; delete only if their
  behavior is already covered by Task 1's `no_ogr_match_unchanged` / single-lot tests)
- [x] DELETE `_apply_ogr_overrides` from `ogr_handler.py`; remove its re-export at
  `crypto_reporting.py:69` and the import at `test_crypto_reporting.py:28`
- [x] Run -> expect GREEN; verify `! grep -rn "_apply_ogr_overrides" src/ tests/` is empty
- [x] Commit: `refactor(crypto): remove dead _apply_ogr_overrides; migrate tests to event-level`

### Task 3: Documentation and pitfall note

Files:
- `docs/maintenance/crypto_rules.md`
- `docs/maintenance/crypto_implementation_guidelines.md`
- `docs/history/feature-notes/2026-06-20-th-anchored-transaction-state-machine.md`

- [x] Add rule **PT-C-037** `[IMPLEMENTATION DECISION | 2026-07-04]` to `crypto_rules.md`
  Section 10 (Implementation Decisions): OGR spot P&L is applied at the disposal-event level;
  the agree branch uses first-lot-absorbs (the full `ogr_event_gain` on the first lot, zero on
  the rest), fixing the legacy `N x` over-count; the conflict branch is unchanged. Note the
  cross-holding-period taxable-split shift on agree-branch multi-lot events vs legacy's
  per-group over-count, citing PT-C-011. `> Source:` citing the RFC feature-note and this plan;
  cross-reference PT-C-035 (OGR-as-authoritative-source) and PT-C-030 (review-flag
  specificity). No new decision-point flag or `TaxJurisdictionConfig` field (no
  `decision_points/` edit).
- [x] Append as **Pitfall 5** under `## Common Implementation Pitfalls` in
  `crypto_implementation_guidelines.md` (NOT the `### Common Pitfalls` table under Operator
  Origin Resolution): "OGR `calculated_gain_loss` must hold PRE-distribution CG and
  `ogr_gain_loss` must hold the FULL event value" - because `_aggregate_ogr_validation` sums
  `calculated_gain_loss` to re-derive direction/magnitude and reads `ogr_gain_loss` from the
  first lot; copying the legacy `entry.gain_loss_eur` pattern after distribution silently
  suppresses every aggregated multi-lot flag (exit 0, wrong filing). Cross-reference PT-C-037
  and Design Invariant 3.
- [x] Update the RFC feature-note Status line from SHELVED to "PHASE 1 (OGR over-count fix)
  LANDED as a surgical event-level patch (first-lot-absorbs); the full TH-anchored Transaction
  view remains deferred - prior review rounds showed its minute-precision / raw-row mechanisms
  generate edge cases the OGR fix does not need. Weakness #2 (agree-branch multi-lot
  over-counting) structurally fixed; #1/#5 and the cross-holding-period allocation are deferred
  to the Transaction view."
- [x] Commit: `docs(crypto): record PT-C-037, pitfall 5, and OGR event-level invariant`

## Monitor

- **Same-day `(date, asset, wallet)` key collapse (pre-existing; owner: Transaction-view
  phase).** Two genuinely distinct spot disposals sharing this key pool into one event under
  both legacy and Phase 1; Phase 1 additionally concentrates the OGR gain on the pooled first
  lot. Current FY data has 0 OGR matches, so the pooling is unobservable today. Resolving it
  requires transaction identity (TxHash / minute-precision) - i.e. the deferred Transaction
  view. Invariant 2 states this explicitly rather than claiming "no collision ambiguity."
- **Re-zero / payment-proceeds interaction (owner: Phase 2).** The re-zero snapshot/restore
  (`crypto_reporting.py:288-340`) and `correct_payment_proceeds` still key on
  `(date, asset, wallet)`. Phase 1 preserves their contracts (pinned by
  `output_length_and_order_preserved`). An OGR row landing on a zero-proceeds Payment key
  remains the contested "NECESSARILY spurious" premise (RFC weakness #5); Phase 2 dissolves it.
  First-lot-absorbs keeps the sum invariant intact ONLY when lot 0 is the (sole) Payment lot:
  the OGR write flips lot 0 to non-zero and the restore firing on it matches legacy intent.
  A NON-first Payment lot in the same event is set to `proceeds_eur = lot.cost_eur` by the
  agree branch, which the restore then re-zeroes (`proceeds_eur=0, gain_loss_eur=-cost`),
  corrupting the agree event total. This multi-Payment-lot case is out of scope for Phase 1
  (the path is gated by `infer_payment_proceeds_active`, currently off) and is owned by Phase 2;
  Invariant 1's residue-free claim is scoped to lot 0 accordingly.
- **Public-name asymmetry.** `apply_ogr_event_level` is intentionally public (no `_` prefix)
  because the Validation Command treats the rename as load-bearing and it is re-exported via
  `crypto_reporting`; siblings (`_build_ogr_index`, `_split_ogr_index`) stay private. This is
  deliberate, not an oversight.
