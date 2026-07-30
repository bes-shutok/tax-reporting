# Plan: Relocate crypto-pipeline WARNINGs into the user-facing extract

Governing principle (user): console WARNINGs reserved for *project/processing*
problems only; every *data issue* and every *methodology decision* lives in the
user-facing Excel extract (Crypto Supplementary review rows + Assumptions &
Methodology counts). End-state: personal-run console WARNING count **11 → 0**.

Plan review: `docs/history/reviews/2026-07-25-plan-review-relocate-crypto-warnings-r1.md` (r1 revised: B0/M5) · `docs/history/reviews/2026-07-25-plan-review-relocate-crypto-warnings-r2.md` (r2: B0/M2; backward-compat `= None` defaults + W7/W8 double-count fix incorporated; W8 is now pure demotion, W7 owns the branch-aware review row) · `docs/history/reviews/2026-07-25-plan-review-relocate-crypto-warnings-r3.md` (r3: B0/M0, ready; r2 fixes verified against source, 1 Low + 1 Monitor only)

Language-guidance links for implementers:
- `docs/maintenance/python_guidelines.md` (PT011/PT018 caplog guards, F401 re-exports)
- `docs/maintenance/crypto_implementation_guidelines.md` (pipeline pitfalls)
- `docs/maintenance/project-guidelines.md` rule #7 (warning-grouping taxonomy)

Predecessor plan: `docs/history/plans/completed/2026-07-24-silence-expected-and-excel-surfaced-warnings.md`
(this plan extends its rule #7 taxonomy with a 4th class, EXTRACT_SURFACED, and
fixes one missed demotion discovered when running the predecessor against real
data: W4 below).

## Terms

- **W1-W10**: the 10 console WARNING sites this plan demotes (W1 and W5 share
  one emitter at two call scopes). Numbering matches the operator's real-run
  log in `docs/tmp/handoff/2026-07-25-silence-warnings-postmerge-handoff.md`.
- **CryptoReviewEntry**: `application/crypto/entities.py:515` dataclass
  (`source_section: Literal["capital_gains","income","transaction_history"]`,
  `date`, `asset`, `platform`, `review_reason`, `is_suspicious=False`). Rendered
  by `_write_review_rows` (`persisting/crypto_supplementary_sheet.py:111`) as a
  5-col `[Source, Date, Asset, Platform, Review reason]` table. The carrier is
  `CryptoTaxReport.review_entries` (`entities.py:569`).
- **A&M**: the `Assumptions & Methodology` sheet (`persisting/assumptions_sheet.py:142`).
  Its methodology section renders static `(label, rule_ids, description)` tuples;
  PT-C-028 "Materiality Threshold" is at `:527-538`.
- **CryptoDecisionCounts**: a new (non-frozen) mutable dataclass this plan
  introduces to carry run-specific decision counts to the A&M writer. It is
  created at the top of `load_koinly_crypto_report` next to `review_entries`
  (`crypto_reporting.py:241`), threaded into the dedup passes that run BEFORE
  the `CryptoTaxReport` is constructed (`:657`), and attached to the report at
  `:657`. Mutation uses set-not-increment semantics (each pass sets its own
  field once).
- **EXTRACT_SURFACED**: a new rule #7 target class (per-row DEBUG + aggregate
  INFO + rows in Crypto Supplementary OR a count cell in A&M). Distinct from
  HAS_EXCEL_SURFACE (where the per-row entry already owns a rendered review
  cell, so no new rows are added: only the console aggregate drops to INFO).

## Gist & Examples

**What changes.** Ten crypto-pipeline aggregate WARNINGs become INFO. For nine
of them, the per-row detail they counted: which today lives only in the
file-handler DEBUG log: becomes visible in the extract:

- Per-row **data issues** (W1/W2/W3/W5/W8/W9, plus the surplus and malformed
  sub-lists of W6/W7) become `CryptoReviewEntry` rows in Crypto Supplementary's
  existing "Review required" section. Each row carries the asset/date/platform
  and a specific actionable reason; surplus + malformed rows set
  `is_suspicious=True` (rendered as a red bold asset cell).
- **Methodology decisions with counts** (W10 sub-1-EUR filter; the removed-lots
  dedup counts of W6/W7) become a runtime count suffix on existing A&M
  methodology items, e.g. the PT-C-028 line renders:
  `... [This run: filtered 173 entries, 8 retained.]`.
- **W4** (pool-exhausted taxable disposal) is a pure demotion: each per-row
  item already creates a `CryptoFifoRealization(review_required=True,
  review_reason="FIFO pool exhausted: ...")` (`crypto_fifo/matching.py:368-404`) that
  renders as a "YES:" cell in Crypto Gains. The non-taxable sibling
  (`crypto_fifo/matching.py:111`) was already demoted to INFO in the predecessor plan; the
  taxable aggregate at `fifo_helpers.py:503` was missed (line drifted 378→503
  across the session and the taxable task fell through).

**Why.** The operator ran the predecessor plan against real data and got 11
WARNINGs on the console, most of which describe either correct methodology
decisions (dedup, materiality filter) or per-row data anomalies already
attributable to source-export quirks rather than pipeline bugs. The console is
for *something is wrong with the project or the way it processes data*; the
extract is for the user to see every data issue and every decision applied to
their records.

**Before/after (console, personal run):**

```
# BEFORE (11 WARNING lines)
WARNING - token_origin - ... 252 origin-resolution disagreement(s) ... returning unknown     # W1
WARNING - crypto_fifo.parsing - Dropped 142 duplicate-tx_key acquisition(s) ...              # W2
WARNING - crypto_fifo.parsing - Flagged 73 zero-Net-Value crypto_deposit(s) for review ...   # W3
WARNING - crypto.fifo_helpers - 72 taxable disposal(s) had no acquisition ... (pool exhausted)# W4
WARNING - token_origin - ... 70 origin-resolution disagreement(s) [FIFO rebuild] ...          # W5
WARNING - crypto.derivatives_filter - Derivatives CG dedup summary: removed/surplus/malformed # W6
WARNING - crypto.fee_filter - Fee CG dedup summary: removed/surplus/malformed ...             # W7
WARNING - crypto.fee_filter - Removed 39 untagged-whitelisted fee disposal(s) ...             # W8
WARNING - crypto.ogr_handler - 44 OGR row(s) routed to derivatives ... no CG counterpart ...  # W9
WARNING - crypto_reporting - Filtered 173 sub-1-EUR capital gain entries (PT-C-028) ...       # W10

# AFTER (0 WARNING lines; same info in the extract)
```

**Edge cases motivating the design:**
- W3 zero-NV deposits set `review_reason` on an *intermediate*
  `AcquisitionContext` that may never be realized (a deposit held to year-end),
  so the predecessor plan correctly ruled it NOT HAS_EXCEL_SURFACE. This plan
  instead emits an explicit `CryptoReviewEntry` per flagged deposit, so the
  surface no longer depends on later realization.
- W6/W7 surplus lots ("may indicate a missed FIFO split") and malformed-input
  lots ("investigate the source export") are treated as *data issues* per the
  governing principle (move to extract, `is_suspicious=True`), not project bugs.
  Confirmed with the operator.
- W9 OGR rows have no fitting `source_section` value (the Literal has no
  "derivatives"); the Literal is extended and the label map updated.

## Evaluation Criteria

**Quality dimensions:**
- Correctness: `uv run pytest` green (1853+ existing tests plus new tests). No
  change to any realized gain, aggregation total, or FIFO outcome
  (`resources/result/` workbook + `shares-leftover.csv` byte-identical except
  for the new review rows / A&M count cells).
- Signal preservation (two-emission guard, one per site): a caplog assertion
  that the aggregate emits at INFO (not WARNING) AND an assertion that the
  corresponding extract surface (review rows or A&M count) is populated.
- Coverage: each of the 10 signature substrings (see Validation Commands)
  appears 0 times as a `logger.warning` in `src/tax_reporting/application/`.
- Backward compatibility: IB-only runs (no crypto) and existing tests that do
  not construct `CryptoDecisionCounts` stay green (default 0 / Optional).

**Release gates:**
- `uv run pytest` green.
- The 10-substring `logger.warning` grep returns 0 hits.
- `review-plan` quality gate: Blocker=0 AND Medium=0 (minimum 2 rounds).
- Operator step (documented if data unavailable): `uv run tax-reporting` on the
  personal dataset emits 0 console WARNING lines.

## Review Scope

**Explicit must-fix**; findings on these paths are always in scope:

**Production code:**
- `src/tax_reporting/application/crypto/fifo_helpers.py` (W4 demotion; W2/W3 `review_entries` threading through `_rebuild_fifo_for_loan_affected_assets`)
- `src/tax_reporting/application/crypto_fifo/parsing.py` (W2, W3)
- `src/tax_reporting/application/crypto/fee_filter.py` (W7, W8)
- `src/tax_reporting/application/crypto/th_lot_matcher.py` (W6 dedup emit + threading)
- `src/tax_reporting/application/crypto/derivatives_filter.py` (W6 caller threading)
- `src/tax_reporting/application/crypto/ogr_handler.py` (W9)
- `src/tax_reporting/application/token_origin.py` (W1, W5)
- `src/tax_reporting/application/crypto_reporting.py` (W10; `review_entries` + `decision_counts` creation at `:241`; threading into `:425`/`:441`/`:361-368`; attach at `:657`)
- `src/tax_reporting/application/crypto/entities.py` (`CryptoDecisionCounts` *(new, non-frozen)*; `CryptoReviewEntry.source_section` Literal extension; `CryptoTaxReport.decision_counts` field)
- `src/tax_reporting/application/persisting/assumptions_sheet.py` (PT-C-028 count suffix + new dedup methodology item)
- `src/tax_reporting/application/persisting/workbook_builder.py` (thread `CryptoDecisionCounts`)
- `src/tax_reporting/application/persisting/crypto_supplementary_sheet.py` (`_write_review_rows` label map + exhaustiveness guard)

**Tests:**
- `tests/unit/application/test_crypto_fifo.py` (W4)
- `tests/unit/application/test_crypto_parsing.py` (W2, W3)
- `tests/unit/application/test_fee_filter.py` (W7, W8)
- `tests/unit/application/test_th_lot_matcher.py` (W6 dedup)
- `tests/unit/application/test_derivatives_filter.py` (W6 caller)
- `tests/unit/application/test_crypto_reporting.py` (W10; W2/W3 negative-path gate test; end-to-end review_entries)
- `tests/unit/application/test_crypto_origin_resolver.py` (W1, W5)
- `tests/unit/application/persisting/test_assumptions_sheet_materiality_count.py` *(new)* (W10 A&M count)
- `tests/unit/application/persisting/test_assumptions_sheet_dedup_count.py` *(new)* (W6/W7 A&M count)
- `tests/unit/application/persisting/test_crypto_supplementary_sheet_derivatives_label.py` *(new)* (W9 label map)

**Documentation (explicit):**
- `docs/maintenance/project-guidelines.md` (rule #7: add EXTRACT_SURFACED; update pattern table; fix pattern-H doc bug)
- `docs/maintenance/tax_reporting_guidelines.md` (Excel sections: review rows now include pipeline data issues; A&M items carry run counts)
- `docs/maintenance/development_lessons.md` (principle + missed-demotion root cause)

**Plan-related extension**; implementation and review may change files not
listed above when causally related to a plan task (e.g. an import the new
dataclass needs, a conftest helper that must filter a new field, a
backward-compat test). Assess each finding; do not auto-drop.

**Out of scope; reject unless plan-related:**
- `AGENTS.md` (4-line prose diff carried onto this branch from master; unrelated)
- Ruff baseline cleanup on `master` (pre-existing tech debt; Flag #3 of predecessor handoff)
- FIFO/aggregation/materiality math in `aggregation.py` (frozen unless a plan task must touch `_filter_immaterial_entries`'s return)

## Design Invariants (CR Guard)

- **INV-1 (no signal loss).** Every demoted WARNING surfaces the same
  information in the extract: per-row items as `CryptoReviewEntry` rows OR a
  decision count in A&M. The per-row `logger.debug(...)` at every site is
  preserved unchanged (the file handler at `logs/tax-reporting.log` keeps the
  per-row audit trail).
- **INV-2 (no number changes).** This plan only ADDS review rows and A&M
  text/count cells. It changes no realized gain, no aggregation, no FIFO
  outcome. Characterization tests stay green; `resources/result/` is
  byte-identical except for the added review rows / count cells.
- **INV-3 (backward compat).** `CryptoDecisionCounts` defaults to 0 and is
  passed as `Optional` to the A&M writer; IB-only runs and existing tests that
  do not construct it stay green. **Every new `review_entries` parameter added
  by this plan defaults to `None`** (`review_entries: list[CryptoReviewEntry] | None = None`),
  matching `decision_counts: CryptoDecisionCounts | None = None`; each function
  guards `if review_entries is not None: ... append(...)`. This preserves the
  ~50 existing test call sites (30× `remove_transaction_fees`, 10×
  `remove_matched_lots`, 15× `remove_derivatives_flagged_lots`, 6×
  `_rebuild_fifo_for_loan_affected_assets`, plus `TokenOriginResolver` and
  `log_and_reset_disagreements` callers) that pass only the old kwargs: they
  must NOT `TypeError`. The `source_section` Literal extension adds a value
  (no removal), and the label map + every `source_section=` construction site
  are updated.
- **INV-4a (mutable accumulator lifecycle).** `CryptoDecisionCounts` is a
  NON-frozen mutable accumulator created at the top of
  `load_koinly_crypto_report` (`crypto_reporting.py:241`, next to
  `review_entries`): NOT frozen, because the dedup passes at `:425`
  (`apply_derivatives_dedup`) and `:441` (`remove_transaction_fees`) run BEFORE
  the `CryptoTaxReport` is constructed at `:657` and must set fields on it
  in-pass. Each pass sets its own field once (set-not-increment). The report
  construction at `:657` attaches the already-populated instance. The writer
  receives it as `Optional` (None for IB-only runs, where `load_koinly_crypto_report`
  returns None at `:226` so the writer is never called with crypto counts).
  Each field is set by EXACTLY ONE pass (auditable set-not-increment property):

  | Field | Set by | Site | Never set by |
  |-------|--------|------|--------------|
  | `sub_1_eur_filtered` | `load_koinly_crypto_report` (W10) | `crypto_reporting.py:562-571` |: |
  | `sub_1_eur_retained` | `load_koinly_crypto_report` (W10) | `crypto_reporting.py:562-571` |: |
  | `derivatives_dedup_removed` | `th_lot_matcher.remove_matched_lots` (W6) | `:510` (via `derivatives_filter` → `apply_derivatives_dedup:425`) | any other pass |
  | `fee_dedup_removed` | `fee_filter.remove_transaction_fees` (W7) | `:554` | `_log_fee_removals` (W8 helper writes ONLY to `review_entries`, never `decision_counts`) |
- **INV-4b (clear-AFTER-emit ordering preserved).** W1/W5 appends to
  `review_entries` MUST occur BEFORE `self._disagreements.clear()` inside
  `token_origin.log_and_reset_disagreements` (`:491`). The clear stays AFTER
  emit (predecessor plan invariant #10). Mirrors the same ordering rule applied
  to the new review-row appends.
- **INV-4 (two-emission test guard).** Each demoted site has a caplog
  assertion at INFO (not WARNING) AND an extract assertion (review rows or A&M
  count). Mirrors predecessor plan Invariant #4.
- **INV-5 (rule #7 doc sync).** Rule #7 gains the EXTRACT_SURFACED class and
  the pattern table is updated for every demoted site; the pattern-H doc bug
  (label said HAS_EXCEL_SURFACE but W9 had no surface) is fixed by Task 9
  adding the surface, so the label becomes correct.
- **INV-6 (CRG/SRG compliance unchanged).** No change to reward classification,
  capital-gains aggregation, materiality threshold value (`PT-C-028`), or
  review_reason specificity (`PT-C-030`). The materiality filter is unchanged;
  only its aggregate log level and an A&M count cell are added.

## Validation Commands

```bash
# Full suite (correctness gate).
uv run pytest

# All 10 demoted substrings must appear 0 times as a logger.warning.
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

# Confirm the source_section Literal and label map both carry "derivatives".
grep -n '"derivatives"' src/tax_reporting/application/crypto/entities.py src/tax_reporting/application/persisting/crypto_supplementary_sheet.py

# Confirm CryptoDecisionCounts is threaded end-to-end.
grep -rn "CryptoDecisionCounts" src/tax_reporting/

# Optional operator step on personal data (document if unavailable):
#   uv run tax-reporting 2>&1 | grep -c WARNING   # expect 0
```

## Tasks

### Task 1: W4: pool-exhausted taxable aggregate → INFO (missed demotion)

Files:
- `src/tax_reporting/application/crypto/fifo_helpers.py`
- `tests/unit/application/test_crypto_fifo.py`

- [x] `TestCryptoFifo#taxable_pool_exhausted_emits_info_not_warning`; given a taxable disposal whose FIFO pool is fully exhausted (no acquisition at or before the disposal date), expects ONE aggregate log record at INFO level containing "taxable disposal(s) had no acquisition", and ZERO records at WARNING level containing that substring
- [x] `TestCryptoFifo#taxable_pool_exhausted_still_creates_review_realization`; given the same scenario, expects a `CryptoFifoRealization` with `review_required=True` and `review_reason` containing "FIFO pool exhausted" (characterization: this surface already exists and must remain). NOTE: the per-row surface covers TWO review_reason variants (`matching.py:368-369` "FIFO pool exhausted: ... zero cost basis" for pool-truly-exhausted; `:381-385` "No acquisition available at or before disposal date ..." for earliest-future-lot): both set `review_required=True`, so both are in the Crypto Gains "YES:" surface; the test should assert the substring "FIFO pool exhausted" OR document that the second variant also surfaces.
- [x] Run → expect RED: `uv run pytest tests/unit/application/test_crypto_fifo.py -k "taxable_pool_exhausted_emits_info_not_warning"`
- [x] Change `fifo_helpers.py:503` `logger.warning(...)` → `logger.info(...)` (the surrounding block comment at `:491-502` stays valid; only the call level changes)
- [x] Update the existing assertions at `tests/unit/application/test_crypto_fifo.py:3083-3091` and `:3178-3185` from WARNING to INFO: change the `rec.levelno == logging.WARNING` predicate to `rec.levelno == logging.INFO`, and ensure `caplog.at_level(logging.INFO)` (or `set_level`) so INFO records are captured (predecessor lesson #69: demotion to INFO silently empties a WARNING-filtered caplog). The message substring text is unchanged.
- [x] Run → expect GREEN: `uv run pytest tests/unit/application/test_crypto_fifo.py -k "pool_exhausted"`
- [x] Commit: `refactor(crypto): demote pool-exhausted taxable aggregate to INFO (W4)`

### Task 2: Introduce `CryptoDecisionCounts` (mutable accumulator) + W10 sub-1-EUR → INFO + A&M count

Files:
- `src/tax_reporting/application/crypto/entities.py`
- `src/tax_reporting/application/crypto_reporting.py`
- `src/tax_reporting/application/persisting/assumptions_sheet.py`
- `src/tax_reporting/application/persisting/workbook_builder.py`
- `tests/unit/application/test_crypto_reporting.py`
- `tests/unit/application/persisting/test_assumptions_sheet_materiality_count.py` *(new)*

- [x] `TestCryptoDecisionCounts#defaults_to_zero`; given construction with no args, expects `sub_1_eur_filtered == 0`, `sub_1_eur_retained == 0`, `derivatives_dedup_removed == 0`, `fee_dedup_removed == 0`
- [x] `TestCryptoDecisionCounts#fields_are_mutable`; given an instance, expects `decision_counts.derivatives_dedup_removed = 5` to succeed (NOT frozen: passes mutate it in-pass)
- [x] `TestSubOneEurFilter#aggregate_emits_info_with_counts`; given `pre_filter_count=175` and post-filter `len=2` (173 dropped), expects ONE INFO record "Filtered 173 sub-1-EUR capital gain entries (PT-C-028); 2 entries retained" and ZERO WARNING records with that substring
- [x] `TestAssumptionsSheetMaterialityCount#ptc028_line_carries_run_count`; given `CryptoDecisionCounts(sub_1_eur_filtered=173, sub_1_eur_retained=8)` threaded into `write_assumptions_and_methodology_sheet`, expects the PT-C-028 "Materiality Threshold" cell text to contain "[This run: filtered 173 entries, 8 retained.]"
- [x] `TestAssumptionsSheetMaterialityCount#ptc028_line_omits_suffix_when_counts_absent`; given `decision_counts=None` (IB-only run), expects the PT-C-028 line to render the static description with NO suffix (backward compat)
- [x] Run → expect RED: `uv run pytest tests/unit/application/test_crypto_reporting.py tests/unit/application/persisting/test_assumptions_sheet_materiality_count.py`
- [x] Add a NON-frozen (mutable) dataclass `CryptoDecisionCounts` to `entities.py` (next to `CryptoCapitalGainStats`, `:294`): fields `sub_1_eur_filtered: int = 0`, `sub_1_eur_retained: int = 0`, `derivatives_dedup_removed: int = 0`, `fee_dedup_removed: int = 0`. NO `frozen=True` (passes set fields in-pass: see INV-4a).
- [x] Add field `decision_counts: CryptoDecisionCounts = field(default_factory=CryptoDecisionCounts)` to `CryptoTaxReport` (`entities.py:555`, next to `capital_gain_stats`)
- [x] In `crypto_reporting.py`: create `decision_counts = CryptoDecisionCounts()` at the top of `load_koinly_crypto_report` next to `review_entries` (`:241`). At the W10 site (`:562-571`), set `decision_counts.sub_1_eur_filtered = dropped` and `decision_counts.sub_1_eur_retained = len(capital_entries)` (the count vars already exist at `:563-565`: no new computation); change `logging.getLogger(__name__).warning(...)` → `.info(...)`. Attach `decision_counts=decision_counts` at the `CryptoTaxReport(...)` construction at `:657` (alongside `review_entries=review_entries`).
- [x] Extend `write_assumptions_and_methodology_sheet` signature with `decision_counts: CryptoDecisionCounts | None = None`; in the PT-C-028 item render (`assumptions_sheet.py:528-538`), append the suffix `f" [This run: filtered {decision_counts.sub_1_eur_filtered} entries, {decision_counts.sub_1_eur_retained} retained.]"` when `decision_counts` is not None
- [x] Thread `decision_counts=crypto_tax_report.decision_counts` from `workbook_builder.py:170-175`
- [x] Run → expect GREEN: `uv run pytest tests/unit/application/test_crypto_reporting.py tests/unit/application/persisting/test_assumptions_sheet_materiality_count.py`
- [x] Commit: `feat(crypto): CryptoDecisionCounts accumulator + W10 sub-1-EUR filter → INFO + PT-C-028 run-count in A&M`

### Task 3: W2: duplicate-tx_key drops → INFO + CryptoReviewEntry rows

Files:
- `src/tax_reporting/application/crypto_fifo/parsing.py` (`_dedup_by_tx_key`)
- `src/tax_reporting/application/crypto/fifo_helpers.py` (`_rebuild_fifo_for_loan_affected_assets`: passes `review_entries` through to parsing)
- `src/tax_reporting/application/crypto_reporting.py` (create `review_entries` at `:241`; thread into `_rebuild_fifo_for_loan_affected_assets` at `:361-368`)
- `tests/unit/application/test_crypto_parsing.py`

- [x] `TestCryptoParsing#duplicate_txkey_drops_emit_info_and_review_rows`; given two acquisitions sharing a tx_key plus one duplicate consumption (unit test calling `_dedup_by_tx_key` directly with a threaded `review_entries` list), expects ONE INFO record "Dropped N duplicate-tx_key acquisition(s) and M consumption(s)", ZERO WARNING records, and `N+M` `CryptoReviewEntry` rows with `source_section="capital_gains"` and reasons distinguishing acquisition vs consumption and naming the tx_key
- [x] `TestCryptoReporting#w2_w3_skipped_when_fifo_rebuild_inactive`; given a crypto run driven end-to-end through `load_koinly_crypto_report` where `fifo_rebuild_active and loan_affected_assets` is False at `crypto_reporting.py:357` (e.g. a non-PT jurisdiction or no loan-affected assets), expects ZERO INFO records matching "duplicate-tx_key" or "zero-Net-Value" and ZERO new `CryptoReviewEntry` rows from those sites. This test MUST drive through `load_koinly_crypto_report` (the `:357` gate is in the orchestrator, not the leaf): calling `_dedup_by_tx_key` directly would bypass the gate and make the assertion meaningless (negative path: the emit sites are unreachable without the rebuild gate).
- [x] Run → expect RED: `uv run pytest tests/unit/application/test_crypto_parsing.py -k "duplicate_txkey_drops_emit_info_and_review_rows"`
- [x] Thread `review_entries: list[CryptoReviewEntry]` through the three-layer chain: `crypto_reporting._rebuild_fifo_for_loan_affected_assets` call (`:361-368`) → `fifo_helpers._rebuild_fifo_for_loan_affected_assets` signature → `parsing._dedup_by_tx_key` (mirror how `fee_filter.flag_fee_suspects` threads `review_entries`). Inside both drop loops (`parsing.py:338-355` acquisitions, `:358-379` consumptions), append one `CryptoReviewEntry(source_section="capital_gains", date=acq.acq.date, asset=..., platform=..., review_reason=f"Duplicate tx_key dropped to prevent doubled FIFO pool ({'acquisition'|'consumption'}; tx_key={...})")` per dropped row. Keep the existing per-row `logger.debug`.
- [x] Demote `parsing.py:386` `logger.warning` → `logger.info`
- [x] Run → expect GREEN: `uv run pytest tests/unit/application/test_crypto_parsing.py -k "duplicate_txkey"`
- [x] Commit: `feat(crypto-fifo): W2 duplicate-tx_key drops → INFO + review rows`

### Task 4: W3: zero-Net-Value crypto_deposit → INFO + CryptoReviewEntry rows

Files:
- `src/tax_reporting/application/crypto_fifo/parsing.py` (`_classify_deposit_row`, the aggregate emit at `:307`)
- `src/tax_reporting/application/crypto/fifo_helpers.py` (same threading chain as Task 3: `review_entries` now flows through)
- `tests/unit/application/test_crypto_parsing.py`

- [x] `TestCryptoParsing#zero_nv_deposit_emits_info_and_review_row`; given a `crypto_deposit` TH row with `Net Value == 0` (unit test at the `_classify_deposit_row` layer with a threaded `review_entries` list), expects ONE INFO record "Flagged N zero-Net-Value crypto_deposit(s) for review", ZERO WARNING records, and a `CryptoReviewEntry(source_section="transaction_history", ...)` whose reason names the missing-cost-basis concern
- [x] Run → expect RED
- [x] Reuse the Task 3 threading (the `review_entries` list now reaches `parsing`). Thread a `review_entries` reference alongside the existing `zero_net_deposits` Counter (it already threads through the call chain at `:296/:402/:446`). In `_classify_deposit_row` (`:685-706`) on the zero-NV branch (`:700`), append a `CryptoReviewEntry(source_section="transaction_history", date=parsed_row.date_str, asset=parsed_row.received_currency, platform=parsed_row.receiving_wallet, review_reason="Zero-Net-Value crypto_deposit flagged for review (possible missing cost basis)")`
- [x] Demote `parsing.py:307` `logger.warning` → `logger.info`
- [x] Run → expect GREEN
- [x] Commit: `feat(crypto-fifo): W3 zero-NV deposits → INFO + review rows`

### Task 5: W8: untagged-whitelisted fee removal → pure INFO demotion (no review rows)

Per r2 Finding 2: the untagged-whitelisted subset is STRICTLY CONTAINED in `filtered_metadata` (the W7 iterate). To avoid one lot getting two review rows (one W7 "Fee CG dedup: removed lot" + one W8 "untagged-whitelisted"), W8 becomes a PURE console demotion: the per-row "verify network fee" signal is carried by W7's branch-aware reason (Task 7) instead. W8 keeps its per-row DEBUG audit trail.

Files:
- `src/tax_reporting/application/crypto/fee_filter.py` (demote `_log_fee_removals:434`)
- `tests/unit/application/test_fee_filter.py`

- [x] `TestFeeFilter#untagged_whitelisted_removal_emits_info`; given matched_metadata containing 2 untagged-whitelisted fee events (calling `_log_fee_removals` directly), expects ONE INFO record "Removed N untagged-whitelisted fee disposal(s)", ZERO WARNING records, and ZERO new `CryptoReviewEntry` rows (W8 no longer appends: W7 owns the row via Task 7's branch-aware reason)
- [x] Run → expect RED
- [x] Demote `fee_filter.py:434` `logger.warning` → `logger.info`. NO signature change, NO review_entries threading, NO append. The per-row `logger.debug` at `:422-429` stays.
- [x] Run → expect GREEN
- [x] Commit: `refactor(crypto): W8 untagged-whitelisted fee removal → INFO (pure demotion; W7 owns the review row)`

### Task 6: W6: derivatives dedup → INFO + review rows (3 sub-lists) + A&M count

The W6 summary WARNING is emitted INSIDE `th_lot_matcher.remove_matched_lots` at `:510` (it uses the caller-passed `logger`, so the record surfaces under `derivatives_filter`). Call chain: `crypto_reporting.py:425` `apply_derivatives_dedup` → `derivatives_filter.remove_derivatives_flagged_lots:288` → `th_lot_matcher.remove_matched_lots:438` (emits at `:510`). The per-row lists (`matched_metadata`, `surplus_lots`, `malformed_input_lots`) are all in scope at `:510`.

Files:
- `src/tax_reporting/application/crypto/th_lot_matcher.py` (`remove_matched_lots`: add `review_entries` + `decision_counts` params; demote `:510`)
- `src/tax_reporting/application/crypto/derivatives_filter.py` (`remove_derivatives_flagged_lots:288` and `apply_derivatives_dedup:373`: thread both params through)
- `src/tax_reporting/application/crypto_reporting.py` (thread `review_entries` + `decision_counts` into the `apply_derivatives_dedup` call at `:425`)
- `tests/unit/application/test_th_lot_matcher.py`
- `tests/unit/application/test_derivatives_filter.py`

- [x] `TestThLotMatcher#derivatives_dedup_removed_lots_become_review_rows`; given a `remove_matched_lots` call (domain_label="derivatives") with 3 matched lots, expects 3 `CryptoReviewEntry` rows with `source_section="capital_gains"`, reasons prefixed "Derivatives CG dedup: removed lot matched to OGR disposal"
- [x] `TestThLotMatcher#derivatives_dedup_surplus_lots_become_suspicious_review_rows`; given surplus lots, expects `CryptoReviewEntry` rows with `is_suspicious=True`, reasons "Surplus lot - may indicate a missed FIFO split; review the listed key"
- [x] `TestThLotMatcher#derivatives_dedup_malformed_lots_become_suspicious_review_rows`; given lots with non-positive amount, expects `CryptoReviewEntry` rows with `is_suspicious=True`, reasons "Malformed-input lot (non-positive amount {amount}); investigate the source export"
- [x] `TestThLotMatcher#derivatives_dedup_summary_emits_info`; given any non-empty derivatives dedup, expects ONE INFO record containing "Derivatives CG dedup summary", ZERO WARNING records
- [x] `TestDerivativesFilter#derivatives_dedup_removed_count_set_on_decision_counts`; given 3 removed lots threaded through `apply_derivatives_dedup` with a `CryptoDecisionCounts` instance, expects `decision_counts.derivatives_dedup_removed == 3` (set once, not incremented)
- [x] Run → expect RED
- [x] Add `review_entries: list[CryptoReviewEntry] | None = None` and `decision_counts: CryptoDecisionCounts | None = None` params to `th_lot_matcher.remove_matched_lots` (`:438`). At `:510`, before/after the summary emit, for each of the three local lists append the corresponding `CryptoReviewEntry` rows (guarded `if review_entries is not None`) with the discriminating reasons above (surplus + malformed → `is_suspicious=True`); if `decision_counts` is not None, set `decision_counts.derivatives_dedup_removed = len(matched_metadata)` (SET, not increment). Change `logger.warning(summary)` → `logger.info(summary)`. Keep per-row DEBUG.
- [x] Thread both params through `derivatives_filter.remove_derivatives_flagged_lots:288` → `apply_derivatives_dedup:373` (accept and forward; `apply_derivatives_dedup` receives them from `crypto_reporting.py:425`).
- [x] Thread `review_entries=review_entries, decision_counts=decision_counts` into the `apply_derivatives_dedup(...)` call at `crypto_reporting.py:425-431`.
- [x] ATOMICITY: the three-hop signature change (`remove_matched_lots` → `remove_derivatives_flagged_lots` → `apply_derivatives_dedup` → `crypto_reporting` call site) is backward-compatible because every new param defaults to `None` (INV-3): so the intermediate commits compile and existing tests pass at each hop. The same `= None` default applies to Tasks 3/5/7/8/9. Tasks 3 and 8 are ALSO multi-hop (`crypto_reporting → fifo_helpers → parsing` for W2/W3; `crypto_reporting → TokenOriginResolver` for W1/W5) and must follow the same default-None + atomic-commit discipline.
- [x] Run → expect GREEN
- [ ] Commit: `feat(crypto): W6 derivatives dedup → INFO + review rows + decision count`

### Task 7: W7: fee dedup → INFO + review rows + A&M count

W7's emit path is DIFFERENT from W6 (NOT a shared wrapper). `remove_transaction_fees` calls `match_lots` (`:491`, match-only: the matcher emits NO summary for fee), then builds `summary = _format_summary_warning(...)` INLINE at `:543` and emits at `:554` (`logger.warning`). The removed-lots list is `filtered_metadata` (`:545`, `:556`); surplus/malformed come from `result.surplus_lots` (`:540`/`:550`) and `result.malformed_input_lots` (`:552`). All in scope at `:554`.

Files:
- `src/tax_reporting/application/crypto/fee_filter.py` (`remove_transaction_fees:446`: add `review_entries` + `decision_counts` params, both `| None = None`; branch-aware append at `:554`; demote `:554`)
- `src/tax_reporting/application/crypto_reporting.py` (thread `review_entries=review_entries, decision_counts=decision_counts` into the `remove_transaction_fees(...)` call at `:441`)
- `src/tax_reporting/application/persisting/assumptions_sheet.py` (new A&M methodology item for the OGR-vs-CG / fee lot dedup decision, under "Implementation" `:523-572`; render the dedup run-count suffix)
- `tests/unit/application/test_fee_filter.py`
- `tests/unit/application/persisting/test_assumptions_sheet_dedup_count.py` *(new)*

- [x] `TestFeeFilter#fee_dedup_removed_lots_become_review_rows`; given a fee dedup run with 2 matched lots, expects 2 `CryptoReviewEntry` rows with reasons prefixed "Fee CG dedup: removed lot". For lots whose `event.tagged` is False and `event.is_embedded` is False (the untagged-whitelisted subset), the reason MUST additionally carry the W8 "verify network fee, not real disposal" suffix and set `is_suspicious=True` (merges the W8 signal onto the W7 row: avoids the r2 double-count). Tagged and embedded lots get `is_suspicious=False`.
- [x] `TestFeeFilter#fee_dedup_tagged_and_embedded_reasons`; given a tagged fee lot and an embedded fee lot, expects the 2 review rows' reasons to carry the tagged/embedded discriminator and `is_suspicious=False` (verifies the branch-aware reason logic uses `event.tagged` and `event.is_embedded`, both available on `FeeThEvent`)
- [x] `TestFeeFilter#fee_dedup_surplus_and_malformed_become_suspicious_review_rows`; given surplus + malformed lots, expects `is_suspicious=True` rows (same reason bodies as Task 6, "Fee CG dedup" prefix)
- [x] `TestFeeFilter#fee_dedup_summary_emits_info`; given any non-empty fee dedup, expects ONE INFO record "Fee CG dedup summary", ZERO WARNING records
- [x] `TestFeeFilter#fee_dedup_removed_count_set_on_decision_counts`; given `filtered_metadata` with 2 removed lots, expects `decision_counts.fee_dedup_removed == 2` (set once, at `remove_transaction_fees`: `_log_fee_removals` does NOT touch `decision_counts`)
- [x] `TestAssumptionsSheetDedupCount#dedup_lines_carry_run_counts`; given `CryptoDecisionCounts(derivatives_dedup_removed=123, fee_dedup_removed=763)` threaded into `write_assumptions_and_methodology_sheet`, expects the A&M dedup methodology item to render "[This run: derivatives removed 123; fee removed 763.]"
- [x] `TestAssumptionsSheetDedupCount#dedup_lines_omit_suffix_when_counts_absent`; given `decision_counts=None`, expects the dedup item to render its static description with NO suffix (backward compat)
- [x] Run → expect RED
- [x] Add `review_entries: list[CryptoReviewEntry] | None = None` and `decision_counts: CryptoDecisionCounts | None = None` params to `remove_transaction_fees:446`. At `:554`, for the three lists append `CryptoReviewEntry` rows (guarded `if review_entries is not None`): iterate `filtered_metadata` (each `(lot, match_type, event)` tuple) for removed rows; `result.surplus_lots` for surplus; `result.malformed_input_lots` for malformed. Removed-row reason is BRANCH-AWARE on the `event` (a `FeeThEvent`): tagged → "Fee CG dedup: removed lot (tagged {event.tagged})"; embedded → "Fee CG dedup: removed lot (embedded fee)"; untagged-whitelisted (`not event.tagged and not event.is_embedded`) → "Fee CG dedup: removed untagged-whitelisted fee disposal (Net Value {event.net_value_eur} EUR, tx_hash={event.tx_hash}) - verify network fee, not real disposal" with `is_suspicious=True`. Surplus + malformed → `is_suspicious=True`, "Fee CG dedup:" prefix. Field mapping for the CryptoReviewEntry: `date=lot.entry.disposal_timestamp`, `asset=lot.entry.asset`, `platform=lot.entry.wallet` (the CG lot's fields; `FeeThEvent` has no `date`/`platform`: use `event.timestamp`/`event.wallet` only if the lot is absent). Set `decision_counts.fee_dedup_removed = len(filtered_metadata)` ONCE here (NOT in `_log_fee_removals`). Change `logger.warning(summary)` → `logger.info(summary)`. Keep per-row DEBUG.
- [x] Forward the two new params from `crypto_reporting.py:441` `remove_transaction_fees(...)` call site.
- [x] Add an A&M methodology item under "Implementation" (`assumptions_sheet.py:523-572`) for the OGR-vs-CG lot dedup decision (derivatives + fee), citing the relevant rule ID; append the run-count suffix `f" [This run: derivatives removed {decision_counts.derivatives_dedup_removed}; fee removed {decision_counts.fee_dedup_removed}.]"` when `decision_counts` is not None.
- [x] Run → expect GREEN
- [x] Commit: `feat(crypto): W7 fee dedup → INFO + review rows + decision count + A&M item`

### Task 8: W1/W5: token_origin disagreements → INFO + CryptoReviewEntry rows

Files:
- `src/tax_reporting/application/token_origin.py`
- `src/tax_reporting/application/crypto_reporting.py` (thread `review_entries` into the resolver)
- `tests/unit/application/test_crypto_origin_resolver.py`

- [x] `TestTokenOriginResolver#disagreements_emit_info_and_one_review_row_per_key`; given 3 distinct (asset, wallet, date) keys disagreeing across 5 total records, expects ONE INFO record per scope ("capital gains parse", "FIFO rebuild") containing "N origin-resolution disagreement(s) across M distinct", ZERO WARNING records, and 3 `CryptoReviewEntry` rows with `source_section="transaction_history"`, reasons naming the scope and the per-key record count
- [x] Run → expect RED
- [x] Thread `review_entries: list[CryptoReviewEntry]` into `TokenOriginResolver` (constructor or method param), set per caller scope. In `log_and_reset_disagreements` (`token_origin.py:464-491`), before `.clear()`, iterate the `self._disagreements` Counter and append one `CryptoReviewEntry(source_section="transaction_history", date=key[2], asset=key[0], platform=key[1], review_reason=f"Token origin resolution disagreement ({scope}); {count} conflicting record(s); returned unknown")` per key. (Conflicting `_AcquisitionRecord` detail is not retained today: out of scope; key + count is the actionable signal.)
- [x] Demote the WARNING at `:484` → INFO
- [x] Run → expect GREEN
- [x] Commit: `feat(crypto): W1/W5 token_origin disagreements → INFO + review rows`

### Task 9: W9: OGR no-CG-counterpart → INFO + CryptoReviewEntry rows + Literal extension

Files:
- `src/tax_reporting/application/crypto/entities.py` (`source_section` Literal)
- `src/tax_reporting/application/crypto/ogr_handler.py`
- `src/tax_reporting/application/persisting/crypto_supplementary_sheet.py` (label map)
- `src/tax_reporting/application/crypto_reporting.py` (thread `review_entries`)
- `tests/unit/application/test_crypto_reporting.py` (or the OGR handler's test module)
- `tests/unit/application/persisting/test_crypto_supplementary_sheet_derivatives_label.py` *(new)*

- [x] `TestOgrHandler#no_cg_counterpart_emits_info_and_review_rows`; given an OGR row classified `kind="derivatives"` with zero CG matches, expects ONE INFO record "N OGR row(s) routed to derivatives ... no CG counterpart", ZERO WARNING records, and a `CryptoReviewEntry(source_section="derivatives", ...)` whose reason names the spot-vs-derivatives ambiguity
- [x] `TestWriteReviewRows#derivatives_source_label`; given a `CryptoReviewEntry(source_section="derivatives")`, expects col 1 to render "Derivatives"
- [x] Run → expect RED
- [x] Extend the `source_section` Literal in `entities.py:515` to add `"derivatives"`. Add `"derivatives": "Derivatives"` to the label map at `crypto_supplementary_sheet.py:132-135`. The current map uses a silent `.get(entry.source_section, "Income")` fallback: after adding `"derivatives"`, add an assertion (or switch to an explicit `if/elif` covering all Literal values) so a future new Literal value fails loudly instead of silently rendering as "Income". Grep every `source_section=` construction site and the literal map to confirm coverage.
- [x] Thread `review_entries` into the OGR handler. Inside the `if classification.kind == "derivatives" and len(cg_matches) == 0:` block (`ogr_handler.py:351-358`), append `CryptoReviewEntry(source_section="derivatives", date=row.date, asset=row.asset, platform=row.wallet, review_reason="OGR row routed to derivatives by row type; no CG counterpart to confirm spot vs derivatives classification")`. Keep the per-row DEBUG.
- [x] Demote `ogr_handler.py:362` `logger.warning` → INFO
- [x] Run → expect GREEN
- [x] Commit: `feat(crypto): W9 OGR no-CG-counterpart → INFO + review rows (source_section="derivatives")`

### Task 10: Rule #7 + docs sync

Files:
- `docs/maintenance/project-guidelines.md`
- `docs/maintenance/tax_reporting_guidelines.md`
- `docs/maintenance/development_lessons.md`

- [x] `project-guidelines.md` rule #7: add a 4th target class **EXTRACT_SURFACED** (per-row DEBUG + aggregate INFO + rows in Crypto Supplementary OR a count cell in A&M), distinct from HAS_EXCEL_SURFACE; add a paragraph stating the governing principle (console WARNINGs reserved for project/processing problems; data issues and decisions live in the extract)
- [x] `project-guidelines.md` rule #7 pattern table: add rows for W2/W3/W6/W7/W8/W9/W10/W1/W5 classed EXTRACT_SURFACED; mark W4 as already-HAS_EXCEL_SURFACE (no new rows, pure INFO demotion). **r4 amendment:** the original Task 10 wording said "confirm pattern H (W9) is now correctly HAS_EXCEL_SURFACE because Task 9 added the surface." r4's rule #7 consolidation (rule #7 lookup table, r4 commit a5ea9bf) reached the OPPOSITE, operator-confirmed end state: H/W9 is **EXTRACT_SURFACED** (per-row DEBUG + aggregate INFO + a new `CryptoReviewEntry` row in Crypto Supplementary, added by Task 9), the predecessor's `HAS_EXCEL_SURFACE` label was the doc bug (W9 had NO surface until Task 9 added one), and pattern H was dropped from the table as a now-duplicate of the W9 EXTRACT_SURFACED row. The canonical rule #7 (r4) is the source of truth; the original Task 10 wording above was the bug.
- [x] `tax_reporting_guidelines.md` "Excel Report Sections": document that Crypto Supplementary's "Review required" section now includes crypto-pipeline data issues (duplicate-tx_key drops, zero-NV deposits, dedup removed/surplus/malformed lots, untagged-whitelisted fee removals, OGR no-CG-counterpart rows, token_origin disagreements), and that A&M methodology items (PT-C-028, dedup) now carry run-specific count suffixes
- [x] `development_lessons.md`: add an entry capturing (a) the governing principle, and (b) the missed-demotion root cause: W4's taxable aggregate escaped the predecessor plan because line numbers drifted 378→503 across the session and the demotion task was pinned to a line number, not a stable signature substring; lesson: pin demotion/grep tasks to a signature substring, not a line number
- [x] Commit: `docs(crypto): rule #7 EXTRACT_SURFACED class + W1-W10 pattern sync + lesson`

### Task 11: Verification

Files: (none: verification only)

- [x] `uv run pytest`: full suite green (1853+ existing + all new tests)
- [x] Run the Validation Commands block: every one of the 10 substrings reports 0 warning-sites; `"derivatives"` present in both the Literal and the label map; `CryptoDecisionCounts` threaded end-to-end
- [x] Confirm no report-number regression: re-run `uv run tax-reporting` (or the e2e fixture equivalent) and diff `resources/result/` against a pre-run copy: changes must be limited to added review rows in Crypto Supplementary and added count cells in A&M
- [x] Operator step (document in handoff if personal data unavailable): `uv run tax-reporting 2>&1 | grep -c WARNING` → expect 0
- [x] Commit (if any fixups): `test: verification pass for relocate-crypto-warnings`

## Sequencing notes

- Task 1 first (isolated quick win; fixes predecessor's missed demotion).
- Task 2 second (introduces `CryptoDecisionCounts` + A&M threading that Tasks 6/7 reuse).
- Tasks 3, 4, 5, 8, 9 are independent per-row-review-row conversions.
- Task 6 then Task 7 (shared dedup wrapper; both depend on Task 2's `CryptoDecisionCounts`).
- Task 10 after all code tasks (docs reflect final state).
- Task 11 last.

## Monitor

- **INV-3 guard re-statement at append sites (Tasks 3/4/8/9): execution readability.**
  Round 3 (r3 Finding 2): Tasks 6 and 7 explicitly write "guarded `if
  review_entries is not None`" at the append bullet, but Tasks 3, 4, 8, 9 say
  only "append one `CryptoReviewEntry(...)`" without re-stating the guard. The
  guard is mandated by INV-3 and reinforced by the Task 6 ATOMICITY note
  (`= None` default applies to Tasks 3/5/7/8/9), so the plan is internally
  consistent: but an implementer working task-by-task who skips the invariant
  could write `review_entries.append(...)` unconditionally and hit
  `AttributeError: 'NoneType' object has no attribute 'append'` from any of the
  ~78 existing test callers that omit the param. Failure mode is LOUD (existing
  tests fail at the GREEN step) and self-correcting. During execution, prepend
  each append bullet in Tasks 3/4/8/9 with "Inside `if review_entries is not
  None:` (INV-3)". No correctness impact; no plan-text change required for r3
  to clear the gate. Owner: this plan (execution-time note).

- **Pattern-H reclassification (W9): operator-confirmed.** Round 1 flagged as
  Monitor: reclassifying predecessor rule #7 pattern H from "no Excel surface"
  to "HAS_EXCEL_SURFACE" (because Task 9 adds the surface) is a doc change to a
  prior plan's invariant. Operator explicitly confirmed "all 10 → INFO" at
  plan-creation time, which authorizes the W9 demotion and the surface addition.
  No further sign-off needed; documented here for traceability. Owner: this plan
  (Task 9 + Task 10). **r4 amendment:** r4's rule #7 consolidation
  (operator-confirmed) refined the end state to **EXTRACT_SURFACED**, not
  HAS_EXCEL_SURFACE. The predecessor's `HAS_EXCEL_SURFACE` label for H was the
  doc bug (H had no surface until Task 9 added the W9 `CryptoReviewEntry` row);
  once Task 9 added the surface, H became a now-duplicate of the W9
  EXTRACT_SURFACED row and was dropped from rule #7's pattern table. The
  original premortem wording ("to HAS_EXCEL_SURFACE") reflected the plan's
  initial framing; the operator-confirmed canonical end state is
  EXTRACT_SURFACED.

## Out of scope

- Capturing conflicting `_AcquisitionRecord` detail in W1/W5 (key + count only).
- Per-row rows for W10's sub-1-EUR drops (materiality rule intentionally discards them; A&M count is the correct surface).
- Any FIFO/aggregation/materiality math change.
- Ruff baseline cleanup (pre-existing tech debt).
