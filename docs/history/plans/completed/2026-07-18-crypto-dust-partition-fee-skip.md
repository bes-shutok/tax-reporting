# Plan: Crypto reward dust partition + FEE-token tracking-entry skip

Derived from `docs/history/feature-notes/2026-07-15-review-flag-deferred-findings.md` items #1 (FEE-token tracking entries) and #7 (Reward dust summary, original Task 2 of the predecessor plan, removed at r9). Carries forward the r8 test prescriptions and the r9 design correction (popular-token set is the wrong discriminator); the design synthesis is recorded in the **Design Provenance** appendix below (DP-1 through DP-4) so this plan is self-contained. Predecessor plan `2026-07-15-review-flag-aggregation-boundary.md` landed in commit `3b7f6b6`, so all "trigger: after Task 1 lands…" preconditions are satisfiable.

Plan review: `docs/history/reviews/2026-07-18-plan-review-crypto-dust-partition-fee-skip-r2-post-drop.md` (r2 post-drop, clean - 0 Blocker + 0 Medium + 0 Low + 0 Monitor; convergence confirmed, two consecutive clean rounds satisfied, plan ready for execution; every load-bearing Part 1 and Part 7 invariant re-verified against current source one more time, FEE absent from popular-token set, lookup-move inside `is_all_zero` safe (`is_suspicious` only at `:740, :753, :766`; `is_known_token` only at `:738`; `:788` homoglyph check independent), `_partition_taxable_now` signature resolves the `:236` local, e2e fixture naming matches `_find_report_path` glob, `TestPartitionTaxableNow` two cases pin both predicate branches; guard-drop re-swept clean, all 11 `drift`/`FileProcessingError`/`count-check` occurrences are historical/contextual/negation, zero active-mechanism orphans; all five Validation Commands re-checked for substance; Review Scope closure matrix complete) · r1 post-drop (`...-r1-post-drop.md`, clean - 0/0/0/0; first clean round after the substantive-revision reset) · r4 (`...-r4.md`, NOT ready - 0 Blocker + 1 Medium + 4 Advisory folded into the substantive revision that triggered this reset; r4 F4 = the guard drop itself, F1/F2/F3/F5 = stale-site/coverage/cross-ref folds) · r3 (`...-r3.md`, NOT ready - 2 Critical folded) · r2 (`...-r2.md`, NOT ready - 2 Critical + 1 Suggestion + 1 Advisory folded) · r1 (`...-r1.md`, NOT ready - 2 Critical + 7 Suggestion + 2 Advisory folded).

NOTE: per the plans-skill "substantive revision resets the review counter" rule, dropping the count-check guard is substantive (changes task structure). The next review round therefore restarts the counter as `...-r1.md` (the prior r4 artifact records the pre-drop state and stays on disk for traceability).

## Terms

- **Reward dust** - a zero-EUR-value reward row on an asset Koinly *can* price (the asset has at least one `value_eur > 0` row in the same export). The zero is a 2-decimal export rounding artifact. Collapsed into a per-`(asset, wallet)` summary block on the Crypto Supplementary tab. New glossary entry.
- **Genuinely-unpriced reward** - a zero-EUR-value reward row on an asset Koinly has *no* price feed for (every row for that asset in this export is `value_eur == 0`). These keep their per-row `YES` flag so the author sees each row and can manually price it. OSBGT, PBERA, SWBERA, STBGT are the motivating examples.
- **Popular-token set** - the JSON at `docs/maintenance/tax/popular_crypto_tokens.json`. Consumed at three production sites in `crypto_reporting.py` (today at `:730, :955, :1012`; the `:730` site is the `is_known_token` lookup that Part 1 relocates inside the `is_all_zero` block per r3 Critical #2, so its line number shifts but the lookup itself is unchanged) to force per-row `YES` review for zero-value rewards on named tokens. NOT used by this plan's discriminator; do not prune it.
- **Has-any-priced-row discriminator** - the new rule: a zero-value reward is dust iff its asset has at least one `value_eur > 0` row somewhere in `crypto_tax_report.reward_entries`. Replaces the r8 popular-token-set discriminator, which misclassified illiquid wrappers (OSBGT etc.) as dust.
- **Koinly tracking token** - Koinly's internal accounting unit for fee accrual (`FEE`, extensible to `KFEE`, `BFXUSDF0`, etc. as observed). Never a user-held asset. Skipped at parse time when all-zero.
- **Presentation-layer only** (Part 7 invariant) - the dust partition is a VIEW over `crypto_tax_report.reward_entries`. It must not mutate the list, change totals, or affect any of the three popular-token consumers or the Reporting worksheet.

## Gist & Examples

**Part 1, FEE-token tracking entries pollute the Crypto Reconciliation skipped-tokens table.** The 2025 Koinly CG export contains 99 rows for the `FEE` asset (Koinly's internal fee-accrual unit), all with `Cost=Proceeds=Gain=0.0` and the placeholder acquisition date `25/04/2015 09:22`. (Premise corrected per plan-review r1 Blocker #1: the feature-notes §1 claim that they pollute `context.review_entries` and emit WARNINGs was factually wrong, `FEE` is not in the popular-token set and `_collect_known_asset_tickers` never adds it because all rows are all-zero, so today the rows take the else-branch at `crypto_reporting.py:764-767` and land in `skipped_zero_value_tokens` via `_register_skipped_zero_asset`. They do NOT reach `context.review_entries` and do NOT emit WARNINGs.)

The actual current cost is: (a) `FEE` appears as one row in the Crypto Reconciliation "Skipped Zero Value Tokens" table, mislabeled as a meaningful skipped token when it is actually Koinly's internal accounting unit; (b) 99 redundant `_get_popular_crypto_tokens` + `contains_non_latin_characters` lookups per run before the else-branch fires (`crypto_reporting.py:729-730`).

*Fix.* Move the `is_suspicious` / `is_known_token` lookups from `:729-730` INTO the `if is_all_zero:` block (they are only consumed there, verified), then add a short-circuit at the very top of the block that detects Koinly tracking entries (`asset in _KOINLY_TRACKING_TOKENS`) and `continue`s before the lookups run. The short-circuit also `continue`s before `_register_skipped_zero_asset` at `:766`, so FEE no longer appears in the skipped-tokens table. Emit a single summary INFO log after the parse pass.

*Before/after.*
| Row | Today | After |
|-----|-------|-------|
| `FEE`, all-zero (the 99-row pattern) | else-branch → `skipped_zero_value_tokens` row `(capital_gains, FEE, count=99)`; 99 redundant popular-token + non-latin lookups (run unconditionally at `:729-730` before the block) | short-circuit at top of block before the lookups (now moved inside); one summary INFO line; absent from `skipped_zero_value_tokens` |
| `FEE`, real disposal (non-zero values, hypothetical) | normal CG processing | **unchanged**, `is_all_zero` is False, block never entered |
| `BTC`, all-zero (popular token) | appended to `review_entries` with `"Zero EUR value for known crypto asset - likely Koinly tracking entry or data error"` | **unchanged**, BTC not in `_KOINLY_TRACKING_TOKENS`; the moved-inside-the-block lookups still run for it |
| Non-all-zero real disposal (any asset) | unconditional `is_suspicious` / `is_known_token` lookups at `:729-730` (results discarded, only the block consumes them) | **lookups no longer run** (moved inside the block, which non-all-zero rows never enter); the unconditional homoglyph check at `:788` still runs independently and is unaffected |

*Why `is_all_zero` is the right second clause (not the placeholder date).* The placeholder date is one signal but Koinly reuses it for any "unknown acquisition date" case, including real assets we want to keep flagged. `is_all_zero` is the *defining characteristic* of the tracking-entry pattern (no economic values), so it cleanly separates tracking entries from a hypothetical real FEE disposal without an arbitrary date match.

**Part 7, Reward dust partition (carries forward original Task 2 from the predecessor plan, with the r9 discriminator correction).** The original Task 2 used `r.asset in _get_popular_crypto_tokens() or _contains_popular_token(r.asset)` as the dust discriminator. The r9 review discovered this is wrong: the popular-token set exists to *force per-row YES review* for illiquid wrappers (OSBGT, PBERA, SWBERA, STBGT) Koinly cannot price, not to identify "Koinly can price this" tokens. Using it as the dust discriminator routes those tokens into a dust summary with the misleading hint "Re-export with higher precision to verify", which does nothing because Koinly has no price feed.

*Fix.* Replace the discriminator with **has-any-priced-row**: a zero-value reward is dust iff its asset has at least one `value_eur > 0` row somewhere in `crypto_tax_report.reward_entries`.

*Before/after on real fixture tokens.*
| Asset | Has any priced row in 2025 export? | Today (no dust partition) | After (has-any-priced-row) |
|-------|------------------------------------|---------------------------|----------------------------|
| BTC | yes | per-row entry, no dust summary | zero-value row → dust summary block ✓ |
| OSBGT | no | per-row YES (kept) | per-row YES (kept) ✓ |
| PBERA | no | per-row YES (kept) | per-row YES (kept) ✓ |
| BGT | yes (redeemable 1:1 BERA) | per-row entry | zero-value row → dust summary block ✓ |

*Where the dust block lives.* Inside Section 2 (TAXABLE-NOW SUPPORT DETAIL), as a sub-block below the detail table. Per-`(asset, wallet)` summary line, sorted `(asset, wallet)` ascending. Three-state empty-label logic for the all-dust / no-rows / mixed cases.

*Section 4 reconciliation split.* Replace `("Taxable-now rows (immediately taxable)", len(taxable_now_entries))` with two lines:
- `("Taxable-now detail rows", len(real_rows))`
- `("Taxable-now dust rows (suppressed from detail)", len(dust_rows))`

The discriminator-regression guard is the direct unit test `TestPartitionTaxableNow` (Task 3), which pins the predicate at the helper boundary. (A count-equality check on `len(real_rows) + len(dust_rows) == len(taxable_now_entries)` was considered and dropped per r4 Monitor #4: for the complementary-filter partition used here, the equality holds for any deterministic predicate by construction, so the check is tautological and its test would require monkeypatching to fire, over-engineering per the plans-skill convergence diagnostic.)

## Evaluation Criteria

**Quality dimensions:**
- **correctness** (tax output): `reward_entries`, `taxable_now_total_eur`, `deferred_total_eur`, and every other field read by `aggregate_taxable_rewards()` or the Reporting worksheet are byte-for-byte unchanged. Verified by reusing the production reader and asserting on the full reconciliation key-value set, not just the new split lines.
- **correctness** (dust discriminator): zero-value rows on assets with at least one priced row route to dust; zero-value rows on assets with no priced row anywhere keep per-row `YES`. Each case has a dedicated RED test asserting its own signal (BTC-priced, OSBGT-unpriced, BGT-priced).
- **correctness** (FEE skip): the 99-row `FEE` all-zero pattern is skipped at the top of the `is_all_zero` block before the popular-token/non-latin lookups (moved inside the block per r3 Critical #2) and before `_register_skipped_zero_asset`, so FEE is absent from `crypto_tax_report.skipped_zero_value_tokens` AND the redundant lookups do not run for FEE rows; a non-zero FEE row still flows through normal CG processing.
- **maintainability**: presentation-layer-only invariant is documented in CRG-021; the popular-token set's three consumers are explicitly out of scope and must not be touched; `_KOINLY_TRACKING_TOKENS` has per-token inline comments and a set-contents test.
- **observability**: Part 1 emits one summary INFO line (not 99 WARNINGs); Part 7's reconciliation split makes the dust flow auditable.
- **test coverage**: unit-tier synthetic fixtures for both parts; one e2e test pinning the Koinly → workbook pipeline; r8 test prescriptions reused.

**Release gates:**
- `uv run pytest tests/unit/application/persisting/test_crypto_supplementary_sheet.py tests/unit/application/test_crypto_reporting.py` GREEN.
- `uv run pytest tests/end_to_end/ -m e2e` GREEN.
- `uv run ruff check` clean on changed files.
- `TestPartitionTaxableNow` (Task 3) pins the dust discriminator at the helper boundary, this is the sole discriminator-regression guard (the count-equality check was dropped per r4 Monitor #4 as tautological).
- Doc-drift grep (see Validation Commands) returns only intended references.

## Review Scope

**Explicit must-fix; findings on these paths are always in scope (review and fix if valid):**

**Production code:**
- `src/tax_reporting/application/crypto_reporting.py` (Part 1: FEE skip in `_parse_capital_gains_file` all-zero branch at `:737`; new `_KOINLY_TRACKING_TOKENS` module constant)
- `src/tax_reporting/application/persisting/crypto_supplementary_sheet.py` (Part 7: dust partition + dust block + Section 4 reconciliation split; extracted helpers `_partition_taxable_now` and `_write_dust_summary_block`)

**Tests:**
- `tests/unit/application/test_crypto_reporting.py` (Part 1: FEE skip tests)
- `tests/unit/application/persisting/test_crypto_supplementary_sheet.py` (Part 7: dust summary, reconciliation split, `_write_reward_detail_rows` empty-label contract, direct helper unit tests)
- `tests/end_to_end/test_crypto_dust_partition.py` *(new)* (Part 7 e2e pipeline pin)
- `tests/end_to_end/test_example_report_generation.py` (extend `SYNTHETIC_KOINLY_2025_DIRS` to cover the new fixture, r1 Medium #5)

**Fixture data:**
- `resources/source/example/2025/koinly/dust-partition/` *(new)*, synthetic Koinly CG/TH/income CSVs with `SYNTHETIC_WALLET_ALLOWLIST` labels only

**Docs:**
- `docs/maintenance/crypto_reporting_guidelines.md` (new CRG-021)
- `docs/maintenance/crypto_implementation_guidelines.md` (dust-partition note + FEE-skip note)
- `docs/maintenance/glossary.md` (new "Reward dust" entry)
- `docs/history/feature-notes/2026-07-15-review-flag-deferred-findings.md` (strike items #1 and #7; record Part 5 dismissal)

**Plan-related extension; implementation and review may change files not listed above. Treat a finding as in scope when it is causally related to this plan:** it implements or completes a plan task, fixes a regression introduced by plan work, closes wiring or docs implied by an explicit must-fix change, or contradicts a contract the plan changed. If the link to the plan is weak or speculative, drop as out of scope with a one-line reason.

**Out of scope; reject unless plan-related:**
- `src/tax_reporting/application/crypto/aggregation.py`, CG aggregation; Part 7 is rewards-only and presentation-layer-only.
- `src/tax_reporting/application/persisting/crypto_reconciliation_sheet.py`, verified during planning to render only counts and a "Skipped Zero Value Tokens" table; never reads `review_reason`. Predecessor feature-notes item #5 dismissed on this basis.
- `docs/maintenance/tax/popular_crypto_tokens.json`, the JSON is NOT the defect; pruning it would defeat the author's original purpose at all three call sites.
- The three popular-token consumers at `crypto_reporting.py` (today `:730, :955, :1012`; the `:730` site relocates inside the `is_all_zero` block per r3 Critical #2, lookup unchanged, line number shifts), byte-for-byte unchanged per the Q6 presentation-layer-only invariant.
- Deferred-findings items #2 (reward FMV basis), #3 (homoglyph tokens), #4 (LBTC no-EUR-price), #6 (ADR), explicitly out of scope per Q1.

## Design Invariants (CR Guard)

These invariants must not be compromised during implementation or code review:

1. **Presentation-layer only (Part 7).** The dust partition lives entirely inside `write_crypto_supplementary_sheet`. It MUST NOT: mutate `crypto_tax_report.reward_entries`; change `taxable_now_total_eur` or `deferred_total_eur`; touch the popular-token set or its three consumers in `crypto_reporting.py` (today `:730, :955, :1012`; the `:730` `is_known_token` lookup relocates inside the `is_all_zero` block per r3 Critical #2, the lookup itself is unchanged, only its line number shifts); change what flows to the Reporting worksheet's OTHER CAPITAL INVESTMENT INCOME line. The totals reported on the Reporting worksheet stay identical regardless of how dust is displayed on the supplementary tab. *Rationale: Design Provenance DP-2 (three-call-sites rule); the popular-token set's three consumers depend on it being unchanged.*

2. **Has-any-priced-row discriminator (Part 7).** Dust-vs-detail splits on whether the asset has at least one `value_eur > 0` row anywhere in `crypto_tax_report.reward_entries`, NOT on popular-token-set membership. `value_eur` is `Decimal` (non-optional) on `CryptoRewardIncomeEntry` (`entities.py:419`), so `value_eur > 0` and `== 0` are type-safe. *Rationale: Design Provenance DP-3 (has-any-priced-row); matches the author's confirmed intent (BTC/ETH/USDT sub-cent rewards → dust; OSBGT/PBERA/SWBERA/STBGT genuinely-unpriced → per-row YES).*

3. **Popular-token set is not pruned.** Do not remove berachain/exchange tokens (OSBGT, PBERA, SWBERA, STBGT, BGT, …) from `popular_crypto_tokens.json` to "fix" the dust discriminator. The JSON is not the defect; the dust discriminator's use of it was. Pruning would re-introduce silent drops at three production sites. *Rationale: Design Provenance DP-2 (three-call-sites rule).*

4. **FEE skip targets the all-zero branch only (Part 1).** Discriminator is `asset in _KOINLY_TRACKING_TOKENS` evaluated at the TOP of the `if is_all_zero:` block, with the `is_suspicious` / `is_known_token` lookups (currently at `crypto_reporting.py:729-730`) **moved inside the block below the short-circuit** (so the lookup-avoidance is real, not just asserted, r3 Critical #2). The short-circuit `continue`s before `_register_skipped_zero_asset` at `:766` (so FEE no longer appears in `skipped_zero_value_tokens`). A non-zero FEE row (hypothetical real disposal) MUST flow through normal CG processing, `is_all_zero` is False so the block is never entered. There is no date check, the placeholder date `25/04/2015 09:22` is reused by Koinly for legitimate "unknown acquisition date" cases and would over-filter. *Rationale: B1 (premortem blocker) resolution; r1 Blocker #1 corrected the premise (FEE never reached `review_entries`); r3 Critical #2 corrected the placement (lookups moved inside the block); the `is_all_zero` clause is the defining characteristic of the tracking-entry pattern, the date is not.*

5. **No hardcoded asset tickers without a constant.** `_KOINLY_TRACKING_TOKENS` is a `frozenset[str]` module constant with per-token inline comments documenting *why* each is a tracking token, and a set-contents test pinning its exact membership. Adding a token is a conscious, visible diff. *Rationale: AGENTS.md "Never introduce a hardcoded value without first flagging it"; M2 (premortem monitor).*

6. **`safe_cell_value()` wrappers on dust-line interpolations.** The dust summary line wraps `asset` and `wallet` in `safe_cell_value()` to match the existing `_write_reward_detail_rows` pattern at `crypto_supplementary_sheet.py:72-77`. **Production contract is `str`, not `str | None`**: `CryptoRewardIncomeEntry.asset` and `.wallet` are both non-optional `str` fields on the frozen dataclass (`entities.py:417, 422`), and `safe_cell_value(value: str)` at `excel_utils.py:126` raises `TypeError` if passed `None` (it calls `strip_control_chars` which iterates the value). The empty-string case (`wallet=""`, reachable in production via `row.get("Wallet Name", "").strip()`) is the only degradation case the test must cover; `None` is not a reachable production state. *Rationale: r1 Blocker #2; verified empirically, `safe_cell_value(None)` raises `TypeError: 'NoneType' object is not iterable`.*

**Note on the dropped count-check guard (r4 Monitor #4).** An invariant `len(real_rows) + len(dust_rows) == len(taxable_now_entries)` enforced via `FileProcessingError` was considered and rejected: for the complementary-filter partition `_partition_taxable_now` uses (`dust = [P(e)], real = [not P(e)]` over the same list), the count equality holds for any deterministic predicate by construction, so the guard is tautological and its test would require monkeypatching to fire. The plans-skill convergence diagnostic flagged the three-round reframing arc (r2 "real drift detector" → r3 "defensive assert" → r4 acknowledgment) as over-engineering on this sub-mechanism. The sole discriminator-regression guard is `TestPartitionTaxableNow` (Task 3), which pins the predicate at the helper boundary where a real change is observable.

## Validation Commands

```bash
# Part 1 + Part 7 unit tests
uv run pytest tests/unit/application/test_crypto_reporting.py tests/unit/application/persisting/test_crypto_supplementary_sheet.py -v

# Part 7 e2e pipeline pin
uv run pytest tests/end_to_end/test_crypto_dust_partition.py -v -m e2e

# Full crypto test suite (regression guard)
uv run pytest tests/unit/application/test_crypto_reporting.py tests/unit/application/persisting/ tests/end_to_end/ -k "crypto or supplementary or reconciliation"

# Lint / format on changed files
uv run ruff check src/tax_reporting/application/crypto_reporting.py src/tax_reporting/application/persisting/crypto_supplementary_sheet.py tests/unit/application/test_crypto_reporting.py tests/unit/application/persisting/test_crypto_supplementary_sheet.py tests/end_to_end/test_crypto_dust_partition.py

# Doc-drift backstop: confirm no stale references to the old reconciliation line or
# the old popular-token discriminator in docs/maintenance (prose, not just identifiers)
grep -rn "Taxable-now rows (immediately taxable)\|reward dust\|has-any-priced-row" docs/maintenance/ docs/architecture/ README.md
grep -rn "popular_crypto_tokens\|_contains_popular_token" docs/maintenance/ | grep -i "dust\|discriminator"
```

### Task 1: Part 1 RED, FEE-token skip at parse (all-zero branch)

Files:
- `tests/unit/application/test_crypto_reporting.py`

- [x] `TestParseCapitalGainsFileFeeToken#test_fee_token_absent_from_skipped_zero_value_tokens`; given a CG CSV with 3 FEE all-zero rows, calls the production pipeline and expects NO entry in `crypto_tax_report.skipped_zero_value_tokens` with `asset=="FEE"` (today FEE appears as `(capital_gains, FEE, count=3)`; after the fix the short-circuit `continue`s before `_register_skipped_zero_asset`). Asserts on the *new* behavior, this test goes RED against unchanged production.
- [x] `TestParseCapitalGainsFileFeeToken#test_fee_token_summary_info_log`; given 3 FEE all-zero rows in one CG file, expects exactly one INFO log record whose `getMessage()` contains both `"Skipped 3 Koinly tracking entries"` AND `"FEE=3"`, AND exactly zero WARNING records mentioning FEE (regex-strength assertion per r1 Medium #6, pin the count and asset, not just shape).
- [x] `TestParseCapitalGainsFileFeeToken#test_real_fee_disposal_passes_through`; given a CG CSV row with `Asset=FEE` and non-zero `Cost (EUR)=10`, `Proceeds (EUR)=12`, `Gain / Loss=2`, expects the row flows through normal CG processing and appears in `capital_entries` (regression guard for Invariant 4; `is_all_zero` is False so the short-circuit does not fire).
- [x] `TestParseCapitalGainsFileFeeToken#test_popular_token_all_zero_still_flagged`; given a CG CSV row with `Asset=BTC`, all-zero values, expects the row is appended to `context.review_entries` with a `review_reason` containing the substring `"Zero EUR value for known crypto asset"` (use `pytest.raises`/substring `match=`, not full-string equality, the actual reason is `"Zero EUR value for known crypto asset - likely Koinly tracking entry or data error"` per `crypto_reporting.py:739`). This guards the popular-token code path (BTC), which is distinct from the FEE path (popular-token non-member). Test renamed per r1 Medium #8 to remove the "non_tracking_zero_token" ambiguity.
- [x] `TestKoinlyTrackingTokensSet#test_set_contents_pinned`; given the module constant `_KOINLY_TRACKING_TOKENS`, expects it equals `frozenset({"FEE"})` exactly (regression guard on Invariant 6; adding a token is a conscious, visible diff).
- [x] `TestParseCapitalGainsFileFeeToken#test_fee_token_skips_popular_token_and_non_latin_lookups`; given a CG CSV with one FEE all-zero row, monkeypatch `_get_popular_crypto_tokens`, `_contains_popular_token`, AND `contains_non_latin_characters` with counters (all three, `is_known_token` is `asset in _get_popular_crypto_tokens() or _contains_popular_token(asset)`, a short-circuit `or` over TWO lookups per r4 F3; patching only the first leaves the second unpinned), expects NONE of the three is called for the FEE row (the short-circuit fires before the lookups, which are now inside the `if is_all_zero:` block below the short-circuit, r3 Critical #2). This is the test that pins the lookup-avoidance Invariant 4 asserts; without it a future refactor that moves the lookups back to `:729-730` would silently defeat the avoidance while passing the other FEE tests.
- [x] Run → expect RED: `uv run pytest tests/unit/application/test_crypto_reporting.py::TestParseCapitalGainsFileFeeToken tests/unit/application/test_crypto_reporting.py::TestKoinlyTrackingTokensSet -v`
  - The `test_fee_token_absent_from_skipped_zero_value_tokens` test must fail RED against unchanged production: today `FEE` DOES appear in `skipped_zero_value_tokens`. If it passes against unchanged code, it is a fake test, revisit.

### Task 2: Part 1 GREEN, implement FEE-token skip

Files:
- `src/tax_reporting/application/crypto_reporting.py`

- [x] Add module constant near the other popular-token helpers (top-level, not function-local):
  ```python
  # Koinly internal accounting units for fee accrual. These are never assets the
  # user holds, buys, or sells; rows for them are tracking entries Koinly emits
  # to record fee accrual, with Cost=Proceeds=Gain=0.0. Skipped at parse time.
  # Add new tokens here ONLY after verifying they are Koinly-internal (not real
  # tradeable assets); the set-contents test (TestKoinlyTrackingTokensSet) will
  # fail until updated.
  _KOINLY_TRACKING_TOKENS: frozenset[str] = frozenset({"FEE"})
  ```
- [x] Add `skipped_koinly_tracking: Counter[str] = Counter()` to the function locals (alongside `skipped_loan_affected` and `skipped_parse_errors` at `crypto_reporting.py:704-705`).
- [x] Inside `_parse_capital_gains_file`, **move the `is_suspicious` and `is_known_token` lookups from `:729-730` INTO the `if is_all_zero:` block**, then place the FEE short-circuit at the very top of the block so it fires before the lookups run (r3 Critical #2, the prior placement inside the block but after `:729-730` did not achieve the lookup-avoidance Invariant 4 claims, because `:729-730` ran unconditionally before the block):
  ```python
  # BEFORE (current source):
  is_all_zero = cost_eur == ZERO and proceeds_eur == ZERO and gain_loss_eur == ZERO
  is_suspicious = contains_non_latin_characters(asset)            # runs on every row
  is_known_token = asset in _get_popular_crypto_tokens() or _contains_popular_token(asset)  # runs on every row
  ...
  if is_all_zero:
      ...

  # AFTER:
  is_all_zero = cost_eur == ZERO and proceeds_eur == ZERO and gain_loss_eur == ZERO
  if is_all_zero:
      if asset in _KOINLY_TRACKING_TOKENS:
          skipped_koinly_tracking[asset] += 1
          continue
      # lookups moved INSIDE the block, they are only consumed here
      # (is_known_token at the is_known_token/known_assets check below;
      #  is_suspicious at the homoglyph-suffix branch, the CryptoReviewEntry,
      #  and _register_skipped_zero_asset, all inside this block)
      is_suspicious = contains_non_latin_characters(asset)
      is_known_token = asset in _get_popular_crypto_tokens() or _contains_popular_token(asset)
      if is_known_token or (context.known_assets and asset in context.known_assets):
          # ... existing review-entries / WARNING / review_required=True branch unchanged ...
      else:
          # ... existing _register_skipped_zero_asset + continue unchanged ...
  ```
  **Verified safe (r3 Critical #2 analysis):** `is_known_token` is read only at the `is_known_token or known_assets` check (inside the block); `is_suspicious` is read only at the homoglyph-suffix branch, the `CryptoReviewEntry(is_suspicious=...)`, and `_register_skipped_zero_asset(..., is_suspicious)`, all inside the block. The unconditional homoglyph check at `:788` (`if contains_non_latin_characters(asset):`) does its own independent call and does NOT read `is_suspicious`, so moving `is_suspicious` inside the block does not affect it. Non-all-zero rows never consumed these lookups anyway (the only consumers are inside the block), so this move is behavior-preserving for every real disposal and is what actually delivers the lookup-avoidance Invariant 4 asserts.
- [x] After the parse loop (before the function returns), emit a single summary INFO log when `skipped_koinly_tracking` is non-empty:
  ```python
  if skipped_koinly_tracking:
      summary = ", ".join(f"{asset}={count}" for asset, count in sorted(skipped_koinly_tracking.items()))
      logger.info("Skipped %d Koinly tracking entries (assets: %s)", sum(skipped_koinly_tracking.values()), summary)
  ```
- [x] Run → expect GREEN: `uv run pytest tests/unit/application/test_crypto_reporting.py::TestParseCapitalGainsFileFeeToken tests/unit/application/test_crypto_reporting.py::TestKoinlyTrackingTokensSet -v`
- [x] Run full crypto_reporting regression: `uv run pytest tests/unit/application/test_crypto_reporting.py -v`
- [x] Commit: `feat(crypto): skip Koinly FEE-token tracking entries before popular-token lookup`

### Task 3: Part 7 RED, dust summary block + three-state empty-label

Files:
- `tests/unit/application/persisting/test_crypto_supplementary_sheet.py`

- [x] `TestCryptoSupplementarySheetDustSummary#test_btc_zero_collapses_to_dust`; given a `CryptoTaxReport` whose `reward_entries` contain one taxable-now BTC row with `value_eur=0` AND one taxable-now BTC row with `value_eur=Decimal("0.50")`, expects the zero-value row does NOT appear in the Section 2 detail table and a "Dust summary:" header followed by one summary line `r"BTC dust .*: 1 rows, summed Value EUR = 0\.00.*"` appears in Section 2
- [x] `TestCryptoSupplementarySheetDustSummary#test_osbgt_zero_keeps_per_row_yes`; given a `CryptoTaxReport` whose `reward_entries` contain ONLY a zero-value OSBGT taxable-now row (OSBGT has no priced row anywhere in the export), expects the OSBGT row DOES appear in the Section 2 detail table with its `Review flag` cell starting `YES:` (the r9 headline fix; FAILS under the popular-token discriminator because OSBGT *is* popular)
- [x] `TestCryptoSupplementarySheetDustSummary#test_bgt_zero_with_priced_row_collapses_to_dust`; given a `CryptoTaxReport` whose `reward_entries` contain one zero-value BGT taxable-now row AND one non-zero BGT row (BGT is popular AND priced → dust wins on priced), expects the zero-value BGT row collapses to dust (FAILS if discriminator is popular-set-only)
- [x] `TestCryptoSupplementarySheetDustSummary#test_mixed_dust_and_detail_both_render`; given a `CryptoTaxReport` with one priced BTC reward (detail), one zero-value BTC reward (dust), and one zero-value OSBGT reward (per-row YES detail), expects Section 2 renders the BTC priced row + OSBGT row in the detail table AND a dust summary block containing the zero-value BTC row
- [x] `TestCryptoSupplementarySheetDustSummary#test_all_dust_empty_label`; given a `CryptoTaxReport` where every taxable-now row is dust (all assets have a priced row elsewhere), expects the Section 2 detail table shows `"All taxable-now rows classified as dust - see summary below"` and a dust summary block renders below it
- [x] `TestCryptoSupplementarySheetDustSummary#test_no_rewards_empty_label_unchanged`; given a `CryptoTaxReport` with no taxable-now entries, expects the Section 2 detail table shows `"No taxable-now rewards"` (regression guard on existing behavior, verify against `TestCryptoSupplementarySheetTaxableNowDetail#test_no_taxable_now_entries_shows_note`)
- [x] `TestCryptoSupplementarySheetDustSummary#test_dust_line_empty_wallet_renders_explicitly`; given a zero-value BTC reward row whose `wallet=""` (the reachable production degradation, empty string via `row.get("Wallet Name", "").strip()`, NOT `None` which is non-reachable per the frozen dataclass's `wallet: str`), expects the dust summary line renders as `"BTC dust (): 1 rows, summed Value EUR = 0.00 ..."` with no `"None"` literal. (r1 Blocker #2: the original `wallet=None` prescription was unconstructable, `safe_cell_value(None)` raises `TypeError`; production contract is `str`.)
- [x] `TestCryptoSupplementarySheetDustSummary#test_dust_sorted_by_asset_wallet`; given dust rows for `(BTC, Demo Spot)`, `(BTC, Wirex)`, `(ETH, Demo Spot)` (synthetic wallet labels per `SYNTHETIC_WALLET_ALLOWLIST`, unit tests don't enforce the allowlist but using real exchange names is gratuitous), expects the summary lines appear in order `(BTC, Demo Spot)`, `(BTC, Wirex)`, `(ETH, Demo Spot)` (sort by `(asset, wallet)` ascending)
- [x] `TestRewardDetailRowsContract#test_empty_label_only_rendered_when_entries_empty`; given a non-empty `entries` list and `empty_label=""`, expects `_write_reward_detail_rows` does NOT render the empty label (the three-state logic in Task 4 depends on this, pin it as a direct unit test so a future refactor that inverts the `if not entries:` check at `crypto_supplementary_sheet.py:66-68` fails loudly). (r1 Advisory #11.)
- [x] `TestPartitionTaxableNow#test_priced_asset_zero_routes_to_dust`; given `taxable_now_entries` containing a zero-value BTC row AND `reward_entries` containing a non-zero BTC row, expects `_partition_taxable_now` returns `(real_rows=[], dust_rows=[<zero BTC>])`, direct unit test of the load-bearing r9 discriminator at the helper boundary (r2 Monitor #4; without this, a future change to the partition predicate could pass the worksheet-level tests while silently flipping the discriminator).
- [x] `TestPartitionTaxableNow#test_unpriced_asset_zero_stays_in_real_rows`; given `taxable_now_entries` containing a zero-value OSBGT row AND `reward_entries` with NO non-zero OSBGT row, expects `_partition_taxable_now` returns `(real_rows=[<OSBGT>], dust_rows=[])`, the r9 headline fix pinned at the helper boundary.
- [x] `TestWriteDustSummaryBlock#test_groups_by_asset_wallet_and_sorts`; given dust rows for `(BTC, Demo Spot)`, `(BTC, Wirex)`, `(ETH, Demo Spot)`, expects the rendered block has header `"Dust summary:"` followed by three summary lines in order `(BTC, Demo Spot)`, `(BTC, Wirex)`, `(ETH, Demo Spot)`, each with correct count and summed Value EUR, direct unit test of the extracted helper (r2 Monitor #4).
- [x] Run → expect RED: `uv run pytest tests/unit/application/persisting/test_crypto_supplementary_sheet.py::TestCryptoSupplementarySheetDustSummary tests/unit/application/persisting/test_crypto_supplementary_sheet.py::TestRewardDetailRowsContract tests/unit/application/persisting/test_crypto_supplementary_sheet.py::TestPartitionTaxableNow tests/unit/application/persisting/test_crypto_supplementary_sheet.py::TestWriteDustSummaryBlock -v`

### Task 4: Part 7 GREEN, implement dust partition + extracted helper

Files:
- `src/tax_reporting/application/persisting/crypto_supplementary_sheet.py`

- [x] Compute `priced_assets_in_export` and partition `taxable_now_entries` into `real_rows` and `dust_rows`. Extract as a module-level helper so it is directly unit-testable (r1 Medium #7). **The helper takes the already-built `taxable_now_entries` list, NOT `reward_entries`**, this keeps `taxable_now_entries` as the single source of truth for line 236 (`taxable_now_total_eur`) and resolves the r2 Blocker #2 `NameError`/double-computation at that site. The real discriminator guard is `TestPartitionTaxableNow` (Task 3).
  ```python
  def _partition_taxable_now(
      taxable_now_entries: list[CryptoRewardIncomeEntry],
      reward_entries: list[CryptoRewardIncomeEntry],
  ) -> tuple[list[CryptoRewardIncomeEntry], list[CryptoRewardIncomeEntry]]:
      """Split taxable-now entries into (real_rows, dust_rows).

      Dust = zero-value rows on assets that have at least one priced row elsewhere
      in the export (Koinly 2-decimal rounding artifact). Genuinely-unpriced assets
      (every row zero) keep per-row YES; they stay in real_rows.
      See CRG-021.

      ``taxable_now_entries`` is passed explicitly (not rebuilt from reward_entries)
      so the caller's local stays the single source of truth for line 236's
      taxable_now_total_eur (r2 Blocker #2). The discriminator guard is the direct
      unit test `TestPartitionTaxableNow` (Task 3), not a count-check on this list.
      """
      priced_assets_in_export = {e.asset for e in reward_entries if e.value_eur > 0}
      dust_rows = [e for e in taxable_now_entries if e.value_eur == 0 and e.asset in priced_assets_in_export]
      real_rows = [e for e in taxable_now_entries if not (e.value_eur == 0 and e.asset in priced_assets_in_export)]
      return real_rows, dust_rows
  ```
  Call site, keep the existing `taxable_now_entries` local at `crypto_supplementary_sheet.py:155-157` UNCHANGED, add the partition call immediately after:
  ```python
  taxable_now_entries = [
      e for e in crypto_tax_report.reward_entries if e.tax_classification == RewardTaxClassification.TAXABLE_NOW
  ]  # unchanged at :155-157
  real_rows, dust_rows = _partition_taxable_now(taxable_now_entries, crypto_tax_report.reward_entries)
  ```
  `deferred_entries` stays as-is (Part 7 is taxable-now only). Line 236 (`taxable_now_total_eur = sum(... for e in taxable_now_entries)`) continues to read the unchanged local, Invariant 1's byte-for-byte-identical total is preserved (r2 Blocker #2).
- [x] Re-scope the empty-label passed to `_write_reward_detail_rows` for Section 2 (`crypto_supplementary_sheet.py:211`) to the three-state logic:
  ```python
  if not real_rows and dust_rows:
      taxable_empty_label = "All taxable-now rows classified as dust - see summary below"
  elif not real_rows and not dust_rows:
      taxable_empty_label = "No taxable-now rewards"
  else:
      taxable_empty_label = ""  # mixed or all-real: headers render, no empty label
  row_no = _write_reward_detail_rows(worksheet, row_no, real_rows, taxable_empty_label)
  ```
  Note: `_write_reward_detail_rows` only writes `empty_label` when `entries` is empty (`crypto_supplementary_sheet.py:66-68`); passing `""` in the mixed/all-real case is safe because `real_rows` is non-empty there. (Pinned by `TestRewardDetailRowsContract#test_empty_label_only_rendered_when_entries_empty`.)
- [x] Extract the dust-block render as a module-level helper `_write_dust_summary_block` (r1 Medium #7, keeps the already-`# noqa: PLR0915` `write_crypto_supplementary_sheet` from growing further; gives the render a directly testable unit):
  ```python
  def _write_dust_summary_block(
      worksheet: openpyxl.worksheet.worksheet.Worksheet,
      row_no: int,
      dust_rows: list[CryptoRewardIncomeEntry],
  ) -> int:
      """Write the per-(asset, wallet) dust summary block; return the next free row."""
      worksheet.cell(row_no, 1, "Dust summary:").font = Font(bold=True)
      row_no += 1
      grouped: dict[tuple[str, str], list[CryptoRewardIncomeEntry]] = {}
      for entry in dust_rows:
          grouped.setdefault((entry.asset, entry.wallet), []).append(entry)
      for (asset, wallet), group in sorted(grouped.items()):
          summed = sum((entry.value_eur for entry in group), start=ZERO)
          line = (
              f"{safe_cell_value(asset)} dust ({safe_cell_value(wallet)}): "
              f"{len(group)} rows, summed Value EUR = {float(summed):.2f} "
              f"(Koinly 2-decimal export). Re-export with higher precision to verify."
          )
          worksheet.cell(row_no, 1, line)
          row_no += 1
      return row_no
  ```
  Note the `safe_cell_value()` wrappers on `asset` and `wallet` (Invariant 7). Production contract is `str` (non-optional on the dataclass); `wallet=""` degrades to `"BTC dust (): ..."`, `None` is not reachable.
- [x] Call site (after the Section 2 detail call at `:211`):
  ```python
  if dust_rows:
      row_no = _write_dust_summary_block(worksheet, row_no, dust_rows)
  ```
- [x] Run → expect GREEN: `uv run pytest tests/unit/application/persisting/test_crypto_supplementary_sheet.py::TestCryptoSupplementarySheetDustSummary tests/unit/application/persisting/test_crypto_supplementary_sheet.py::TestRewardDetailRowsContract tests/unit/application/persisting/test_crypto_supplementary_sheet.py::TestPartitionTaxableNow tests/unit/application/persisting/test_crypto_supplementary_sheet.py::TestWriteDustSummaryBlock -v`
- [x] Run full supplementary-sheet regression: `uv run pytest tests/unit/application/persisting/test_crypto_supplementary_sheet.py -v`
- [x] Commit: `feat(crypto): collapse sub-cent rewards into per-(asset,wallet) dust summary`

### Task 5: Part 7 RED, Section 4 reconciliation split

Files:
- `tests/unit/application/persisting/test_crypto_supplementary_sheet.py`

- [x] `TestCryptoSupplementarySheetClassificationReconciliation#test_section4_splits_detail_and_dust_counts`; given a `CryptoTaxReport` with 2 detail taxable-now rows and 3 dust taxable-now rows, expects Section 4 contains key-value rows `("Taxable-now detail rows", 2)` and `("Taxable-now dust rows (suppressed from detail)", 3)`, and does NOT contain the old `("Taxable-now rows (immediately taxable)", 5)` line
- [x] Re-scope `TestCryptoSupplementarySheetClassificationReconciliation#test_reconciliation_key_value_pairs`; given the existing fixture, expects the new split lines appear alongside the unchanged lines (`"Total reward rows (raw)"`, `"Deferred rows"`, holding-period counts, totals), and `("Taxable-now rows (immediately taxable)", ...)` is absent
- [x] Re-scope `TestCryptoSupplementarySheetClassificationReconciliation#test_reconciliation_empty_rewards`; given a `CryptoTaxReport` with no reward entries, expects Section 4 renders `("Taxable-now detail rows", 0)` and `("Taxable-now dust rows (suppressed from detail)", 0)` (regression guard on the empty path)
- [x] Run → expect RED: `uv run pytest tests/unit/application/persisting/test_crypto_supplementary_sheet.py::TestCryptoSupplementarySheetClassificationReconciliation -v`

### Task 6: Part 7 GREEN, implement reconciliation split

Files:
- `src/tax_reporting/application/persisting/crypto_supplementary_sheet.py`

- [x] Replace the reconciliation row at `crypto_supplementary_sheet.py:241`:
  ```python
  # before
  ("Taxable-now rows (immediately taxable)", len(taxable_now_entries)),
  # after
  ("Taxable-now detail rows", len(real_rows)),
  ("Taxable-now dust rows (suppressed from detail)", len(dust_rows)),
  ```
  (No `FileProcessingError` count-check guard is added, r4 Monitor #4 dropped it as tautological for the complementary-filter partition; `TestPartitionTaxableNow` is the sole discriminator guard. No new import is needed in this module.)
- [x] Run → expect GREEN: `uv run pytest tests/unit/application/persisting/test_crypto_supplementary_sheet.py::TestCryptoSupplementarySheetClassificationReconciliation -v`
- [x] Run full supplementary-sheet regression: `uv run pytest tests/unit/application/persisting/test_crypto_supplementary_sheet.py -v`
- [x] Commit: `feat(crypto): split Section 4 reconciliation into detail/dust counts`

### Task 7: Part 7 e2e, pipeline pin (Koinly → workbook → dust block visible)

Files:
- `tests/end_to_end/test_crypto_dust_partition.py` *(new)*
- `tests/end_to_end/test_example_report_generation.py` (extend `SYNTHETIC_KOINLY_2025_DIRS`)
- `resources/source/example/2025/koinly/dust-partition/` *(new fixture dir; koinly_<year>_<report>.csv naming, synthetic wallet labels only)*

- [x] Create the synthetic Koinly fixture dir `resources/source/example/2025/koinly/dust-partition/` with files named to match the production pipeline's `_find_report_path` markers (r2 Blocker #1, `load_koinly_crypto_report` at `crypto_reporting.py:204-206` globs `*capital_gains_report*`, `*income_report*`, `*transaction_history*` via `koinly_parser.py:419-431`; the existing `payment/` fixture confirms the exact names):
  - `koinly_2025_capital_gains_report.csv`
  - `koinly_2025_income_report.csv`
  - `koinly_2025_transaction_history.csv`
  Wallet labels MUST come from `SYNTHETIC_WALLET_ALLOWLIST = {"Demo Spot", "Demo Futures", "Demo Payment", "Wirex", ""}` (`test_example_report_generation.py:64`); do NOT use "Kraken"/"Binance"/"Bybit" (r1 Medium #5). All TxHash/TxSrc/TxDest cells empty (synthetic-data hygiene per `test_example_data_is_synthetic`). Mirror the `example/2025/koinly/payment/` shape exactly.
- [x] Add `EXAMPLE_DIR / "2025" / "koinly" / "dust-partition"` to `SYNTHETIC_KOINLY_2025_DIRS` at `test_example_report_generation.py:49` so the synthetic-data hygiene check covers the new fixture (r1 Medium #5, without this the hygiene check silently skips the new dir).
- [x] `TestCryptoDustPartitionE2E#test_priced_asset_zero_collapses_to_dust_via_full_pipeline`; given the synthetic fixture containing one priced BTC reward (value > 0) and one zero-value BTC reward, expects the generated workbook's Crypto Supplementary tab renders the dust summary block with one BTC line and the Section 4 reconciliation shows split counts
- [x] `TestCryptoDustPartitionE2E#test_unpriced_asset_zero_keeps_per_row_yes_via_full_pipeline`; given the same fixture extended with a zero-value OSBGT reward (no priced OSBGT row anywhere), expects the OSBGT row appears in the Section 2 detail table with `Review flag` starting `YES:` (full-pipeline version of the r9 headline fix)
- [x] `TestCryptoDustPartitionE2E#test_reward_entries_unchanged_by_partition`; given the fixture, expects `crypto_tax_report.reward_entries` length and the totals computed by the production pipeline match the expected values derived directly from the fixture (Invariant 1, presentation-layer only). Compute the expected `taxable_now_total_eur` by summing `value_eur` over taxable-now rows in the fixture; assert the pipeline's reconciliation `reward_total_eur` and `Taxable-now detail + dust` counts match. Do NOT compare against a "partition-disabled baseline" (there is no flag to disable it; the invariant is that the partition is a view).
- [x] Run → expect GREEN (e2e exercises the production pipeline, no RED phase): `uv run pytest tests/end_to_end/test_crypto_dust_partition.py tests/end_to_end/test_example_report_generation.py -v -m e2e`
- [x] Commit: `test(crypto): e2e pin for dust partition pipeline and presentation-layer invariant`

### Task 8: Docs, CRG-021, glossary, implementation notes, feature-notes strike-through

Files:
- `docs/maintenance/crypto_reporting_guidelines.md`
- `docs/maintenance/glossary.md`
- `docs/maintenance/crypto_implementation_guidelines.md`
- `docs/history/feature-notes/2026-07-15-review-flag-deferred-findings.md`

- [x] In `docs/maintenance/crypto_reporting_guidelines.md`, append **CRG-021** after the highest existing CRG ID (verified free per r1: highest is CRG-020, so CRG-021 is correct; re-verify with `grep -on "CRG-[0-9]*" docs/maintenance/crypto_reporting_guidelines.md | sort -t- -k2 -n -u | tail -3` before writing):
  > **CRG-021, Reward dust partition is presentation-layer and uses has-any-priced-row, not popular-token membership.** Zero-value taxable-now reward rows are split into a "Dust summary" block on the Crypto Supplementary tab (Section 2) iff the asset has at least one `value_eur > 0` row elsewhere in the export. Assets with no priced rows anywhere (e.g. OSBGT, PBERA, SWBERA, STBGT, illiquid wrappers Koinly cannot price) keep their per-row `YES` flag. The popular-token set (`popular_crypto_tokens.json`) is a separate concern with three consumers in `crypto_reporting.py` (today `:730, :955, :1012`; the `:730` site relocates inside the `is_all_zero` block under this plan, lookup unchanged, line number shifts); do not prune it to fix the dust discriminator. Dust partition does not mutate `reward_entries`, totals, or the Reporting worksheet, it is a view. Accepted risks: (A1) per-export "priced" proxy may misclassify a globally-priced asset whose every row in this export rounds to zero (cosmetic only, supplementary-tab noise, tax numbers unchanged); the discriminator is export-precision-coupled, if Koinly raises export precision above 2 decimals, assets whose rows previously all rounded to zero may flip into the "priced" set, so year-over-year dust-summary comparisons must account for export precision (the dust-line hint already suggests re-exporting at higher precision as the workaround); (A2) no runtime flag to disable Part 7, AGENTS.md rule 130 (backward-compat flag tests) does not apply because Part 7 is byte-for-byte presentation-layer only (Invariant 1: `reward_entries`, `taxable_now_total_eur`, `deferred_total_eur`, and the Reporting worksheet's OTHER CAPITAL INVESTMENT INCOME line are unchanged); the "disabled" state is the pre-Part-7 rendering, recoverable by reverting the partition, and no tax output depends on the partition so there is no behavior to preserve via a flag.
- [x] In `docs/maintenance/glossary.md`, add (English defining language; preserve non-English in italics per AGENTS.md):
  > **Reward dust**, A zero-EUR-value reward row on an asset Koinly *can* price (the asset has at least one `value_eur > 0` row in the same export); the zero is a 2-decimal export rounding artifact. Collapsed into a per-`(asset, wallet)` summary block on the Crypto Supplementary tab. Contrast with genuinely-unpriced rewards (per-row `YES` flag retained).
- [x] In `docs/maintenance/crypto_implementation_guidelines.md`, append a dust-partition companion note after the aggregation paragraph at `:415-421`:
  > **Reward dust partition (CRG-021).** The Crypto Supplementary sheet (Section 2) collapses zero-value taxable-now reward rows into a per-`(asset, wallet)` dust summary when the asset has at least one priced row in the export. The discriminator is `value_eur > 0` anywhere in `reward_entries`, NOT popular-token-set membership (the popular set has a different purpose; see CRG-021). The partition is presentation-layer only; it does not mutate `reward_entries` or change totals. Section 4 reconciliation splits into `("Taxable-now detail rows", N)` and `("Taxable-now dust rows (suppressed from detail)", M)`. The discriminator-regression guard is the direct unit test `TestPartitionTaxableNow` (no count-equality invariant, see plan's "dropped count-check guard" note).
- [x] In `docs/maintenance/crypto_implementation_guidelines.md` (parser section), add a FEE-skip note:
  > **Koinly tracking-token skip.** `_parse_capital_gains_file` skips rows whose asset is in `_KOINLY_TRACKING_TOKENS` (currently `{"FEE"}`) AND whose `Cost=Proceeds=Gain=0.0`. These are Koinly's internal fee-accrual tracking entries, not user-held assets. The `is_all_zero` clause is load-bearing, a hypothetical non-zero FEE row flows through normal CG processing. Adding a token requires updating the set-contents test (`TestKoinlyTrackingTokensSet#test_set_contents_pinned`).
- [x] In `docs/history/feature-notes/2026-07-15-review-flag-deferred-findings.md`:
  - Strike item #1 (FEE-token tracking entries) and prepend `**Status: Resolved by plan 2026-07-18-crypto-dust-partition-fee-skip (Tasks 1-2). Premise corrected during plan review (r1 Blocker #1): the original claim that FEE all-zero rows pollute context.review_entries and emit WARNINGs was factually wrong, FEE is not in the popular-token set, so the rows take the else-branch at crypto_reporting.py:764-767 and land in skipped_zero_value_tokens. The actual fix removes FEE from the reconciliation skipped-tokens table and skips the redundant popular-token/non-latin lookups before the else-branch.**`
  - Strike item #7 (Reward dust summary) and prepend `**Status: Resolved by plan 2026-07-18-crypto-dust-partition-fee-skip (Tasks 3-7), original r8 design reused, r9 discriminator correction applied.**`
  - Update item #5 (Crypto Reconciliation sheet): prepend `**Status: Investigated and dismissed 2026-07-18.** The reconciliation sheet (`crypto_reconciliation_sheet.py`) renders only counts and a "Skipped Zero Value Tokens" table; it never reads `review_reason` text. The trigger condition does not hold.`
- [x] Run doc-drift grep: `grep -rn "Taxable-now rows (immediately taxable)\|reward dust\|has-any-priced-row" docs/maintenance/ docs/architecture/ README.md`, expect only intended references.
- [x] Commit: `docs(crypto): CRG-021 reward dust partition + FEE-token skip notes; strike resolved feature-notes`

## Monitor

- **Export-precision coupling (r1 Advisory #10).** The Part 7 has-any-priced-row discriminator is per-export, not per-asset-lifetime: if Koinly raises export precision above 2 decimals, assets whose rows previously all rounded to zero may flip into the "priced" set, and year-over-year dust-summary comparisons become incomparable without accounting for export precision. Documented in CRG-021's accepted risk A1; the dust-line hint already suggests re-exporting at higher precision. Owner: CRG-021 (this plan). Re-evaluate if Koinly ever ships a higher-precision export.
- **`_write_reward_detail_rows` empty-label contract (r1 Advisory #11).** The three-state empty-label logic in Task 4 depends on the helper rendering `empty_label` ONLY when `entries` is empty (`crypto_supplementary_sheet.py:66-68`). Pinned by `TestRewardDetailRowsContract#test_empty_label_only_rendered_when_entries_empty` (added in Task 3) so a future refactor that inverts the `if not entries:` check fails loudly rather than silently rendering a stray empty-label row in the mixed/all-real case. Owner: this plan (Task 3 test).
- **Direct unit tests for the two extracted helpers (r2 Advisory #4).** `_partition_taxable_now` (the load-bearing r9 discriminator) and `_write_dust_summary_block` (the render) are now module-level per Task 4; without direct tests a future change to the partition predicate could pass the worksheet-level assertions while silently flipping the discriminator. Folded into Task 3 as `TestPartitionTaxableNow` (two cases) and `TestWriteDustSummaryBlock` (one case). Owner: this plan (Task 3 tests).

## Design Provenance (Part 7 reward-dust partition)

This appendix is the canonical home for the *synthesis* of the original Task 2 design (removed from the predecessor `2026-07-15-review-flag-aggregation-boundary` plan at r9), the r9 discriminator discovery, and the has-any-priced-row alternative this plan implements. Invariants 1-3 above cite it by section. It was relocated here from `docs/history/feature-notes/2026-07-15-review-flag-deferred-findings.md` §7 so the plan is self-contained and the feature-notes file could be reduced to a closure log. Verbatim test prescriptions and the line-level OSBGT discovery remain in the r8/r9 review staging docs (gitignored under `docs/history/reviews/`, retained locally for traceability).

### DP-1. The original r8 discriminator and why it was wrong

The predecessor plan's original Task 2 used `r.asset in _get_popular_crypto_tokens() or _contains_popular_token(r.asset)` as the dust discriminator, treating popular-token-set membership as equivalent to "Koinly can price this asset; a zero `Value (EUR)` is a 2-decimal sub-cent rounding artifact". That equivalence is false. The popular-token set is an explicit **don't-ignore allowlist**: tokens added to it (OSBGT, PBERA, SWBERA, STBGT, BGT, ...) are there precisely because their zero-value rewards should be **flagged for review (per-row `YES`)**, not silently summarized as dust. Per `docs/maintenance/tax/popular_crypto_tokens.json`:

> "If a reward for one of these tokens has zero value, it's likely a Koinly data error (missing price data, export issue) and should be flagged for review instead of skipped."

The author's confirmed mental model (2026-07-16): these berachain-ecosystem and exchange-platform tokens are **illiquid wrappers Koinly often cannot price**. They were added to the popular set so zero-value rewards would *surface*, not because Koinly was expected to price them. BGT is the exception (staking-derived, redeemable 1:1 for BERA); the rest (OSBGT, IBGT, LBGT, STBGT, IBERA, SWBERA, PBERA) are genuinely illiquid.

Under the original r8 discriminator all seven of OSBGT/XFATBERA/EWBERA-4/PBERA/SWBERA/BGT/STBGT route to `dust_rows` (all are `in_set=True` or `contains=True` via the "BERA" substring) and get the misleading hint "Re-export with higher precision to verify", which does nothing because Koinly has no price feed. The headline r8 test `test_niche_asset_zero_value_keeps_per_row_yes_flag` used OSBGT as its fixture and could not pass. This is the design-level defect that caused Task 2 to be removed at r9.

### DP-2. The three-call-sites rule: the popular-token JSON is not the defect

The popular-token set has three existing production call sites in `src/tax_reporting/application/crypto_reporting.py` (`:821` inside the `_parse_capital_gains_file` `is_all_zero` block, `:1072` and `:1129` in the two reward-entry zero-value branches). All three force per-row `YES` review for zero-value rewards on named tokens. **Pruning the berachain/exchange tokens from `popular_crypto_tokens.json` to "fix" the dust discriminator would defeat the author's original purpose at all three call sites**: those tokens would go back to being silently dropped. The JSON is not the defect; the r8 dust discriminator's use of it was.

### DP-3. The has-any-priced-row alternative (what this plan implements)

Dust-vs-detail splits on whether Koinly demonstrably has a price for the asset **in this export**, not on popular-set membership:

- **Dust case**: the asset has at least one `value_eur > 0` row somewhere in this export; this row's zero is a sub-cent rounding artifact. Summarize with the re-export hint.
- **Genuinely-unpriced case**: every row for this asset in this export is `value_eur == 0`. Koinly has no price feed. Keep the per-row `YES` flag so the author sees each row and can manually price it.

Implementation (this plan's `_partition_taxable_now`, Task 4):

```python
priced_assets_in_export = {e.asset for e in reward_entries if e.value_eur > 0}
dust_rows = [e for e in taxable_now_entries if e.value_eur == 0 and e.asset in priced_assets_in_export]
real_rows = [e for e in taxable_now_entries if not (e.value_eur == 0 and e.asset in priced_assets_in_export)]
```

This matches the author's intent: BTC/ETH/USDT sub-cent rewards become dust; OSBGT/PBERA/SWBERA/STBGT (genuinely unpriced) keep per-row `YES`.

### DP-4. Provenance pointers

- r8 staging doc: `docs/history/reviews/2026-07-16-plan-review-review-flag-aggregation-boundary-r8.md` (verbatim Task 2 test prescriptions: `TestCryptoSupplementarySheetDustSummary` six methods, the Section 4 reconciliation-split re-scopes, and the OSBGT-based `test_niche_asset_zero_value_keeps_per_row_yes_flag` that broke).
- r9 staging doc: `docs/history/reviews/2026-07-16-plan-review-review-flag-aggregation-boundary-r9.md` (finding #1, the OSBGT discovery with the full in_set/contains verification table).
- Popular-token JSON: `docs/maintenance/tax/popular_crypto_tokens.json` (do not prune without re-reading DP-2 above).
- Production helpers: `src/tax_reporting/application/crypto/classification.py:344-370` (`_get_popular_crypto_tokens`, `_contains_popular_token`).

### Task 9: Final validation

- [x] Run the full Validation Commands block.
- [x] `uv run pytest tests/unit/application/test_crypto_reporting.py tests/unit/application/persisting/test_crypto_supplementary_sheet.py tests/end_to_end/test_crypto_dust_partition.py -v`, all GREEN.
- [x] `uv run ruff check` clean on all changed files.
- [x] Confirm Invariant 1 (presentation-layer only) by inspecting that `test_reward_entries_unchanged_by_partition` passes, `reward_entries` length, `taxable_now_total_eur` (summed from fixture rows directly), and `Taxable-now detail + dust` counts match the values derived from the fixture. The partition is a view (Invariant 1 / CRG-021 A2): there is no runtime flag and therefore no "partition-disabled baseline" to compare against (r2 Medium #3, the prior "byte-for-byte identical to the partition-disabled baseline" wording contradicted Task 7's contract and Invariant 1; r4 F2 corrected the stale "Invariant 4" cross-references that lingered from the pre-renumber wording).
- [x] Confirm the popular-token set's three consumers (`crypto_reporting.py:821, 1072, 1129`) are untouched in their semantics: the lookup at `:821` (inside `_parse_capital_gains_file`'s `is_all_zero` block) was relocated there from its pre-plan `:729-730` position by Part 1, lookup unchanged; the two reward-branch consumers at `:1072` and `:1129` are byte-for-byte unchanged. `git diff <pre-plan-base>..HEAD -- src/tax_reporting/application/crypto_reporting.py` shows changes only in `_parse_capital_gains_file` (the FEE short-circuit + the `is_suspicious`/`is_known_token` lookup move into the `is_all_zero` block) and the new `_KOINLY_TRACKING_TOKENS` constant, not at the reward-branch sites.
