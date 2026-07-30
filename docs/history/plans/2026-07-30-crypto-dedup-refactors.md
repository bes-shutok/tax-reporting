# Plan: Crypto dedup/refactor — collapse duplicated review-row + A&M-suffix construction

Three independent refactors surfaced as deferred optional-debt findings across the
`2026-07-25-relocate-crypto-warnings-to-extract` plan's 8-round review + a standalone
review-loop round. None has a live bug or invariant violation; all are
readability/maintainability improvements. This plan addresses them in isolation so the
warning-relocation branch stays a clean single-concern feature branch.

Predecessor: `docs/history/plans/completed/2026-07-25-relocate-crypto-warnings-to-extract.md`
(deferred-findings records in its r1-r8 review staging docs + the standalone
`2026-07-30-branch-review-...-r1.md`).

Plan review: `docs/history/reviews/2026-07-30-plan-review-crypto-dedup-refactors-r1.md` (latest, NOT ready — F1 blocking)

Language-guidance links for implementers:
- `docs/maintenance/python_guidelines.md` (PT011/PT018 caplog guards, F401 re-exports)
- `docs/maintenance/crypto_implementation_guidelines.md` (pipeline pitfalls)
- `docs/maintenance/project-guidelines.md` rule #7 (warning-grouping taxonomy)

## Terms

- **M4 (matcher cohesion)**: `th_lot_matcher.remove_matched_lots` is documented as a
  domain-generic TH-event→CG-lot matcher (`domain_label` arg, generic `events:
  Sequence[E]`) but hardcodes derivatives-specific `CryptoReviewEntry` reason strings
  and unconditionally writes `decision_counts.derivatives_dedup_removed`. The fee filter
  had to bypass it (`match_lots` + inline summary) to avoid inheriting derivatives text.
  This refactor makes the matcher domain-neutral by moving caller-specific reasons +
  count-field ownership into the callers (mirroring the fee path).
- **A&M suffix dedup**: two back-to-back nested-loop blocks in
  `assumptions_sheet.write_assumptions_and_methodology_sheet` walk `methodology_items`
  with identical shape, differing only in the matched label + suffix string.
- **W6/W7 surplus-malformed dedup**: the surplus-lot and malformed-input-lot
  `CryptoReviewEntry` append loops are structurally identical across
  `th_lot_matcher.remove_matched_lots` and `fee_filter.remove_transaction_fees`, but
  **differ in their reason prefix** (r1 F1 correction): the fee filter prepends
  `"Fee CG dedup: "` to BOTH surplus and malformed, while the derivatives matcher
  prepends NOTHING to these two sub-lists (the surplus reason is the bare
  `"Surplus lot - ..."`; the malformed reason is the bare
  `"Malformed-input lot (non-positive amount ...); investigate the source export"`).
  Only the REMOVED-lot derivatives row carries a `"Derivatives CG dedup: "` prefix.
  (The removed-lot blocks genuinely diverge and are NOT dedupable — derivatives
  "removed lot matched to OGR disposal" vs fee's branch-aware
  tagged/embedded/untagged-whitelisted logic.) The shared helper MUST therefore accept
  a per-sub-list prefix and the derivatives caller MUST pass `""` so the byte-identical
  guarantee holds (INV-text).

## Gist & Examples

**What changes.** Three mechanical refactors that reduce duplication and restore the
generic matcher's domain-neutrality, with NO behavior change (characterization tests stay
green; the rendered Excel output is byte-identical):

1. **M4 — make `remove_matched_lots` domain-neutral.** Move the derivatives-specific
   review-row appends + the `derivatives_dedup_removed` count-set OUT of the matcher and
   INTO `derivatives_filter.remove_derivatives_flagged_lots` (which already calls
   `_log_removals_and_surplus` over the same three lists). The matcher returns to
   match-only + summary-INFO emit (no review rows, no count). This mirrors how
   `fee_filter.remove_transaction_fees` already works (it calls `match_lots` match-only,
   then builds its own review rows + sets `fee_dedup_removed` inline).

   Before:
   ```
   crypto_reporting → apply_derivatives_dedup → remove_derivatives_flagged_lots
     → remove_matched_lots(..., review_entries=, decision_counts=)
       # matcher appends "Derivatives CG dedup: removed lot..." rows + sets count
   ```
   After:
   ```
   crypto_reporting → apply_derivatives_dedup → remove_derivatives_flagged_lots
     → remove_matched_lots(..., review_entries=None, decision_counts=None)  # match-only
     # remove_derivatives_flagged_lots appends the derivatives rows + sets count
   ```

2. **A&M suffix dedup.** Extract a helper
   `_append_run_suffix(methodology_items, label, suffix)` that does the nested-loop
   label-match + tuple-rebuild once; the two call sites (PT-C-028 materiality, dedup)
   become one-line calls under a single `if decision_counts is not None:` guard.

3. **W6/W7 surplus-malformed dedup.** Extract a module-private helper (in `entities.py`
   or a shared `crypto/review_rows.py` — TBD by implementer) that builds the surplus +
   malformed `CryptoReviewEntry` rows from a lot list + a reason prefix. The two call
   sites (derivatives_filter after M4, fee_filter) call it with their respective prefixes
   (`"Derivatives CG dedup: "` / `"Fee CG dedup: "`).

**Why.** Each refactor was flagged by ≥4 consecutive review rounds as a
readability/cohesion smell. M4 is the most consequential: a "generic" matcher that
hardcodes caller-specific knowledge is an OCP violation that forces the second caller
(fee) to duplicate ~60 lines of review-row construction to avoid inheriting the wrong
text. Collapsing the duplication + restoring domain-neutrality makes the matcher safe to
reuse for future dedup domains.

**Edge cases motivating the design:**
- M4 moves the count-set out of the matcher; the INV-4a "set-not-increment, each field
  owned by exactly one pass" property MUST be preserved (the derivatives pass still owns
  `derivatives_dedup_removed`; the fee pass still owns `fee_dedup_removed`; no pass
  touches the other's field).
- The A&M suffix helper must handle the immutable-tuple rebuild identically (the
  methodology_items structure is `list[tuple[str, list[tuple[str, str, str]]]]`; tuples
  are immutable, so the helper reassigns the inner-list slot).
- The W6/W7 surplus-malformed helper must preserve `is_suspicious=True` for both sub-lists
  and the exact reason text the two-emission-guard tests assert on.

## Evaluation Criteria

**Quality dimensions:**
- Correctness: `uv run pytest` green (1881 existing tests). NO change to any rendered
  review row, A&M suffix text, or `CryptoDecisionCounts` field value (the Excel output is
  byte-identical).
- Signal preservation: the two-emission guards (caplog INFO + extract surface) stay green
  for all 10 demoted W1-W10 sites; the INV-4a set-not-increment property is unchanged.
- Backward compat: every `review_entries`/`decision_counts` param still defaults to
  `None`; existing callers that omit them stay green.
- Cohesion (M4): after the refactor, `remove_matched_lots` contains NO
  derivatives-specific reason text and NO `derivatives_dedup_removed` write; the matcher's
  docstring no longer says "called ONLY by the derivatives filter" (it becomes truly
  reusable, OR the docstring is updated to reflect the new match-only contract).
- Duplication reduction (A&M + W6/W7): the helper extractions collapse the duplicated
  blocks; line count drops; no new duplication introduced.

**Release gates:**
- `uv run pytest` green.
- The 10-substring `logger.warning` grep still returns 0 hits (no demotion regressed).
- `uv run ruff check --select I001,D417,N806 src/tax_reporting/application/` clean.

## Review Scope

**Explicit must-fix**; findings on these paths are always in scope:

**Production code:**
- `src/tax_reporting/application/crypto/th_lot_matcher.py` (M4: remove derivatives-specific reasons + count from `remove_matched_lots`; restore match-only contract)
- `src/tax_reporting/application/crypto/derivatives_filter.py` (M4: `remove_derivatives_flagged_lots` owns the derivatives review-row appends + `derivatives_dedup_removed` count-set)
- `src/tax_reporting/application/persisting/assumptions_sheet.py` (A&M suffix dedup: extract `_append_run_suffix` helper)
- `src/tax_reporting/application/crypto/fee_filter.py` (W6/W7 surplus-malformed dedup: use the shared helper)
- `src/tax_reporting/application/crypto/entities.py` *(touched only if INV-3/Task-1 param disposition removes `review_entries`/`decision_counts` from the `CryptoDecisionCounts`-adjacent signature; see Task 1)* OR a new `src/tax_reporting/application/crypto/review_rows.py` *(new — the W6/W7 shared helper module; r1 F4 decided)*

**Tests:**
- `tests/unit/application/test_th_lot_matcher.py` (M4: the derivatives review-row tests move to the caller layer; matcher tests verify match-only)
- `tests/unit/application/test_derivatives_filter.py` (M4: the derivatives review-row + count assertions move here)
- `tests/unit/application/test_fee_filter.py` (W6/W7: the fee surplus-malformed tests verify the shared helper is used)
- `tests/unit/application/persisting/test_assumptions_sheet_materiality_count.py` (A&M: characterization — suffix text unchanged)
- `tests/unit/application/persisting/test_assumptions_sheet_dedup_count.py` (A&M: characterization — suffix text unchanged)

**Plan-related extension**; implementation and review may change files not listed above
when causally related (e.g. an import the helper needs, a docstring update in
`crypto_reporting.py` if the call-site threading changes). Assess each finding; do not
auto-drop.

**Out of scope; reject unless plan-related:**
- The 10 WARNING→INFO demotions themselves (frozen; completed in the predecessor plan).
- FIFO/aggregation/materiality math in `aggregation.py` / `crypto_fifo/matching.py`.
- The `review_reason` f-string TEXT (frozen; the two-emission-guard tests assert on exact
  substrings — the refactors must preserve the text byte-identical, not rewrite it).

## Design Invariants (CR Guard)

- **INV-1 (no signal loss).** The refactors preserve every `CryptoReviewEntry` row and
  every A&M suffix cell. The helper extractions are mechanical; the rendered output is
  byte-identical. The matcher becoming match-only does NOT remove the derivatives rows —
  they move to the caller (`remove_derivatives_flagged_lots`), which already iterates the
  same three lists.
- **INV-2 (no number changes).** No `CryptoDecisionCounts` field value changes. The
  derivatives count is still `len(matched_metadata)` (set by the derivatives pass, just at
  a different call site). No FIFO/aggregation/materiality math touched.
- **INV-3 (backward compat).** Every `review_entries`/`decision_counts` param still
  defaults to `None`. After M4, `remove_matched_lots` no longer NEEDS those params (it's
  match-only), but removing them from the signature would break the fee path if it ever
  migrated to `remove_matched_lots` — keep them as `= None` defaults with no-op behavior
  (or remove them if the fee path is confirmed to never migrate; the implementer decides,
  but existing callers that pass them must not TypeError).
- **INV-4a (set-not-increment).** The derivatives pass still owns
  `derivatives_dedup_removed`; the fee pass still owns `fee_dedup_removed`. No pass
  touches the other's field. Moving the derivatives count-set from the matcher to
  `remove_derivatives_flagged_lots` does not change ownership (the derivatives pass is the
  owner; the matcher was its delegate).
- **INV-text (reason text frozen).** The `CryptoReviewEntry.review_reason` strings are
  asserted verbatim by the two-emission-guard tests. The helper extractions must preserve
  the exact text (including the `"Fee CG dedup: "` / `"Derivatives CG dedup: "` prefixes,
  the surplus/malformed bodies, and the branch-aware tagged/embedded/untagged-whitelisted
  logic in the fee removed-lot path — which is NOT dedupable and stays inline).
  **Prefix asymmetry (r1 F1):** the derivatives surplus/malformed rows carry NO domain
  prefix today (`test_th_lot_matcher.py:498` asserts the exact bare string
  `"Surplus lot - may indicate a missed FIFO split; review the listed key"`; `:538`
  asserts `startswith("Malformed-input")` with no prefix), while the fee filter prepends
  `"Fee CG dedup: "` to BOTH (`test_fee_filter.py:2301`, `:2311`). The W6/W7 helper MUST
  accept a per-sub-list prefix (`surplus_prefix`, `malformed_prefix`); the derivatives
  caller passes `""` for both and the fee caller passes `"Fee CG dedup: "` for both.

## Validation Commands

```bash
# Full suite (correctness gate).
uv run pytest

# All 10 demoted substrings must appear 0 times as a logger.warning (no demotion regressed).
for s in \
  "origin-resolution disagreement" \
  "duplicate-tx_key" \
  "zero-Net-Value crypto_deposit" \
  "taxable disposal(s) had no acquisition" \
  "Derivatives CG dedup summary" \
  "Fee CG dedup summary" \
  "untagged-whitelisted fee disposal" \
  "OGR row(s) routed to derivatives" \
  "Filtered" "sub-1-EUR capital gain entries" ; do
  hits=$(grep -rn "$s" src/tax_reporting/application/ | grep "logger.warning\|logging.getLogger.*warning\|\.warning(" | wc -l | tr -d ' ')
  echo "$s: $hits warning-site(s) (expect 0)"
done

# M4: remove_matched_lots contains NO derivatives-specific text after the refactor.
grep -c "Derivatives CG dedup" src/tax_reporting/application/crypto/th_lot_matcher.py
# expect: 0

# M4 (r1 F4): the matcher body contains zero writes to decision_counts.*dedup and zero
# CryptoReviewEntry appends (the params stay as = None no-op defaults, but the body is clean).
! grep -n "derivatives_dedup_removed\|CryptoReviewEntry" src/tax_reporting/application/crypto/th_lot_matcher.py
# expect: no matches (exit 1 from grep = pass)

# M4: derivatives_filter now owns the review-row appends + count.
grep -c "derivatives_dedup_removed" src/tax_reporting/application/crypto/derivatives_filter.py
# expect: >= 1

# A&M suffix dedup: the helper exists.
grep -n "_append_run_suffix" src/tax_reporting/application/persisting/assumptions_sheet.py
# expect: the helper def + 2 call sites

# ruff clean on touched files.
uv run ruff check --select I001,D417,N806 src/tax_reporting/application/
```

## Tasks

### Task 1: M4 — make `remove_matched_lots` domain-neutral (move derivatives reasons + count to caller)

This is the highest-leverage refactor. It restores the matcher's generic contract and
removes the OCP violation that forced the fee filter to duplicate review-row construction.

Files:
- `src/tax_reporting/application/crypto/th_lot_matcher.py` (`remove_matched_lots`: remove the derivatives-specific review-row appends + `derivatives_dedup_removed` set; restore match-only + summary-INFO emit contract)
- `src/tax_reporting/application/crypto/derivatives_filter.py` (`remove_derivatives_flagged_lots`: own the derivatives review-row appends for the three lists + the `derivatives_dedup_removed` count-set, mirroring how `fee_filter.remove_transaction_fees` owns the fee rows + count)
- `tests/unit/application/test_th_lot_matcher.py` (move the derivatives review-row tests to the caller layer; the matcher tests verify match-only behavior)
- `tests/unit/application/test_derivatives_filter.py` (the derivatives review-row + count assertions move here)

- [ ] `TestRemoveMatchedLots#matcher_emits_summary_info_but_no_review_rows`; given a `remove_matched_lots` call with matched/surplus/malformed lots, expects ONE summary INFO record but ZERO `CryptoReviewEntry` appends (the matcher is now match-only; review rows are the caller's responsibility). NOTE: this is a characterization change — the existing tests that assert review rows ARE appended via `remove_matched_lots` must move to the derivatives_filter test module.
- [ ] `TestDerivativesFilter#removed_lots_become_review_rows_at_caller`; given 3 matched lots through `remove_derivatives_flagged_lots`, expects 3 `CryptoReviewEntry` rows with `source_section="capital_gains"`, reasons prefixed "Derivatives CG dedup: removed lot matched to OGR disposal" (moved from the matcher to the caller; text byte-identical)
- [ ] `TestDerivativesFilter#surplus_and_malformed_become_suspicious_review_rows_at_caller`; given surplus + malformed lots, expects `is_suspicious=True` rows with the same reason bodies (moved from the matcher)
- [ ] `TestDerivativesFilter#test_derivatives_dedup_removed_count_set_on_decision_counts` (EXISTING test at `test_derivatives_filter.py:1927`; r2 F7: this test already drives the count end-to-end through `apply_derivatives_dedup` and asserts the observable count, so it stays GREEN after the matcher→caller move and already covers INV-4a — confirm it stays GREEN, do NOT write a redundant new test)
- [ ] Run → expect RED: `uv run pytest tests/unit/application/test_th_lot_matcher.py tests/unit/application/test_derivatives_filter.py`
- [ ] In `th_lot_matcher.remove_matched_lots`: remove the three review-row append blocks (removed/surplus/malformed) and the `decision_counts.derivatives_dedup_removed = len(matched_metadata)` set. Keep the summary INFO emit + the per-row DEBUG. Update the docstring to reflect the match-only contract (remove "called ONLY by the derivatives filter"; state the matcher is domain-neutral and emits the summary INFO only; callers own review rows + counts). KEEP both `review_entries`/`decision_counts` params as `= None` no-op defaults (INV-3 backward compat; r1 F4 decision: the "future fee migration" rationale is speculative but the no-op default is harmless and avoids re-threading `apply_derivatives_dedup` call sites). Add a validation grep asserting the matcher body contains zero writes to `decision_counts.*dedup` and zero `CryptoReviewEntry` appends (see Validation Commands).
- [ ] In `derivatives_filter.remove_derivatives_flagged_lots`: after the `remove_matched_lots` call, append the derivatives review rows for the three lists (`result.matched_metadata`, `result.surplus_lots`, `result.malformed_input_lots` — the matcher's `MatcherResult` return value carries all three; verified at `derivatives_filter.py:308-310`) with the exact reason text + `is_suspicious` flags; set `decision_counts.derivatives_dedup_removed = len(result.matched_metadata)` (INV-4a: the derivatives pass owns this field). The appends and the count-set MUST sit after the existing `if not derivatives_events: return capital_entries, 0` early-return guard at `derivatives_filter.py:296-297` (r1 F2: this matches the matcher's current `if not events: return result` short-circuit so the byte-identical contract holds for the empty-events path; placing them unconditionally before the result check would double-emit).
- [ ] Run → expect GREEN: `uv run pytest tests/unit/application/test_th_lot_matcher.py tests/unit/application/test_derivatives_filter.py`
- [ ] Run the full suite to confirm no regression: `uv run pytest`
- [ ] Commit: `refactor(crypto): make remove_matched_lots domain-neutral (M4 — derivatives reasons + count move to caller)`

### Task 2: A&M suffix dedup — extract `_append_run_suffix` helper

Files:
- `src/tax_reporting/application/persisting/assumptions_sheet.py`
- `tests/unit/application/persisting/test_assumptions_sheet_materiality_count.py`
- `tests/unit/application/persisting/test_assumptions_sheet_dedup_count.py`

- [ ] Run → expect GREEN (characterization): `uv run pytest tests/unit/application/persisting/test_assumptions_sheet_materiality_count.py tests/unit/application/persisting/test_assumptions_sheet_dedup_count.py` (captures existing suffix-rendering behavior before refactor; these tests must stay GREEN after)
- [ ] Extract `_append_run_suffix(methodology_items, label, suffix) -> bool` (returns whether the label was found; raises or warns if not — match the existing behavior). The two call sites become:
  ```python
  if decision_counts is not None:
      _append_run_suffix(methodology_items, "Materiality Threshold", materiality_suffix)
      _append_run_suffix(methodology_items, "OGR-vs-CG and Fee Lot Dedup", dedup_suffix)
  ```
- [ ] Run → expect GREEN (characterization tests unchanged): `uv run pytest tests/unit/application/persisting/test_assumptions_sheet_materiality_count.py tests/unit/application/persisting/test_assumptions_sheet_dedup_count.py`
- [ ] Run the full suite: `uv run pytest`
- [ ] Commit: `refactor(crypto): extract _append_run_suffix helper (A&M suffix dedup)`

### Task 3: W6/W7 surplus-malformed dedup — extract shared review-row helper

Files:
- `src/tax_reporting/application/crypto/fee_filter.py` (use the shared helper for surplus + malformed)
- `src/tax_reporting/application/crypto/derivatives_filter.py` (use the shared helper for surplus + malformed, after Task 1 moved them here)
- `src/tax_reporting/application/crypto/review_rows.py` (NEW — the shared helper module; r1 F4 decided `entities.py` is out because it is the frozen-dataclass domain-entities module)
- `tests/unit/application/test_fee_filter.py`
- `tests/unit/application/test_derivatives_filter.py`

- [ ] `TestReviewRowHelper#surplus_rows_built_with_prefix`; given a surplus lot list + a `"Fee CG dedup: "` prefix, expects `CryptoReviewEntry` rows with reason `"Fee CG dedup: Surplus lot - may indicate a missed FIFO split; review the listed key"` and `is_suspicious=True` (byte-identical to the current inline fee text). Also given a `""` prefix (the derivatives case), expects the bare reason `"Surplus lot - may indicate a missed FIFO split; review the listed key"` (byte-identical to the current inline derivatives text — r1 F1: derivatives has NO prefix on surplus).
- [ ] `TestReviewRowHelper#malformed_rows_built_with_prefix`; given a malformed lot list + a `"Fee CG dedup: "` prefix, expects rows with reason `"Fee CG dedup: Malformed-input lot (non-positive amount {amount}); investigate the source export"` and `is_suspicious=True`. Also given a `""` prefix (the derivatives case), expects the bare reason `"Malformed-input lot (non-positive amount {amount}); investigate the source export"` (byte-identical to the current derivatives text — r1 F1: derivatives has NO prefix on malformed).
- [ ] Run → expect RED: `uv run pytest tests/unit/application/test_fee_filter.py tests/unit/application/test_derivatives_filter.py -k "surplus_rows_built_with_prefix or malformed_rows_built_with_prefix"`
- [ ] Extract the helper: `_append_surplus_and_malformed_review_rows(review_entries, surplus_lots, malformed_lots, *, surplus_prefix: str, malformed_prefix: str)` (module-private; lives in a new `src/tax_reporting/application/crypto/review_rows.py` — chosen over `entities.py` because `entities.py` is the frozen-dataclass domain-entities module and a mutable-list helper does not belong there). The helper builds the surplus rows as `f"{surplus_prefix}Surplus lot - may indicate a missed FIFO split; review the listed key"` and the malformed rows as `f"{malformed_prefix}Malformed-input lot (non-positive amount {entry.amount}); investigate the source export"`, both with `is_suspicious=True`. The derivatives caller passes `surplus_prefix=""`, `malformed_prefix=""`; the fee caller passes `surplus_prefix="Fee CG dedup: "`, `malformed_prefix="Fee CG dedup: "` (INV-text prefix asymmetry, r1 F1). The removed-lot blocks stay inline (they genuinely diverge — derivatives "removed lot matched to OGR disposal" vs fee's branch-aware tagged/embedded/untagged-whitelisted logic; NOT dedupable per INV-text).
- [ ] Replace the inline surplus + malformed append blocks in both `derivatives_filter` (post-Task-1) and `fee_filter.remove_transaction_fees` with calls to the helper.
- [ ] Run → expect GREEN: `uv run pytest tests/unit/application/test_fee_filter.py tests/unit/application/test_derivatives_filter.py`
- [ ] Run the full suite: `uv run pytest`
- [ ] Commit: `refactor(crypto): extract surplus/malformed review-row helper (W6/W7 dedup)`

### Task 4: Verification

Files: (none: verification only)

- [ ] `uv run pytest`: full suite green (1881+ existing)
- [ ] Run the Validation Commands block: M4 grep confirms matcher has 0 derivatives-specific text; derivatives_filter owns the count; A&M helper exists; 10 substrings still 0 warning-sites; ruff clean
- [ ] Confirm no report-number regression: the Excel output is byte-identical (the refactors are mechanical; characterization tests + the two-emission guards confirm)
- [ ] Commit (if any fixups): `test: verification pass for crypto-dedup-refactors`

## Sequencing notes

- Task 1 first (M4 is the highest-leverage and unblocks Task 3's derivatives call site).
- Task 2 independent (A&M sheet; no dependency on Task 1).
- Task 3 after Task 1 (the derivatives surplus/malformed blocks must be in
  `derivatives_filter` before the shared helper can replace both call sites).
- Task 4 last.
