# Deferred findings: review-flag aggregation-boundary investigation

Companion to `docs/history/plans/2026-07-15-review-flag-aggregation-boundary.md`. Captures findings surfaced during the investigation that are explicitly **out of scope** for the active plan but warrant follow-up. Each entry has a recommended trigger condition for re-opening.

## 1. FEE-token tracking entries pollute the per-lot review list

**Status: Resolved by plan 2026-07-18-crypto-dust-partition-fee-skip (Tasks 1-2). Premise corrected during plan review (r1 Blocker #1): the original claim that FEE all-zero rows pollute context.review_entries and emit WARNINGs was factually wrong, FEE is not in the popular-token set, so the rows take the else-branch at crypto_reporting.py:764-767 and land in skipped_zero_value_tokens. The actual fix removes FEE from the reconciliation skipped-tokens table and skips the redundant popular-token/non-latin lookups before the else-branch.**

**Finding.** The 2025 Koinly CG export contains 99 rows for the `FEE` asset (Koinly's internal accounting unit for trading fees), all with the Koinly placeholder acquisition date `25/04/2015 09:22`, wallet `Kraken`, and `Cost=Proceeds=Gain=0.0`. These are not real disposals; they are tracking entries Koinly emits to record fee accrual. They reach `_parse_capital_gains_file` and are appended to `context.review_entries` because they match the `is_all_zero + is_known_token` branch at `crypto_reporting.py:737-763`.

After the active plan's Task 1 lands, these entries no longer poison aggregated rows. They still:
- inflate `context.review_entries` by 99 entries per year;
- emit 99 WARNING log lines per run;
- cause 99 lookups in `_get_popular_crypto_tokens` / `contains_non_latin_characters`.

**Why deferred.** Filtering FEE-token tracking entries at the lot parser is a behavior change independent of the aggregation fix, and the right discriminator is non-obvious. The placeholder date `25/04/2015 09:22` is one signal but Koinly may use it for other "unknown acquisition date" cases too. A wallet+asset heuristic (`Kraken + FEE`) is too narrow; the user may have other Koinly-internal tokens (`KFEE`, `BFXUSDF0`, etc.) we have not seen.

**Trigger to re-open.** After Task 1 lands, count FEE-token (and similar) entries in `context.review_entries` for the user's next export. If the count is non-trivial (>50) and they all share the placeholder acquisition date, draft a focused plan with a clear discriminator and a RED test that asserts the tracking entry is skipped at parse time without affecting real disposals.

**Likely fix-point.** Extend the `is_all_zero` branch in `_parse_capital_gains_file` to detect "Koinly internal tracking entry": asset in a small constant set (`FEE`, plus future additions) AND acquisition date matches the placeholder. Skip silently (or log at INFO, not WARNING).

---

## 2. Reward-FMV-not-carried-into-basis detection (the Q1 domain question)

**Status: Investigated and dismissed 2026-07-21.** The trigger has NOT fired on the real 2025 export. After Task 1 of the active plan landed, every aggregated disposal row on the Crypto Gains sheet resolves to `Review flag = NO`. The reward-derived aggregated rows each carry substantial non-zero aggregated cost, confirming that at least one lot in each group has a real cost basis and the deferral's "every lot zero-basis" precondition does not hold for this dataset. The per-lot rows in Section 5 REVIEW REQUIRED fall into unrelated categories (zero-value-known-asset, untagged-fee, EUROC par-assumption); none route through the proposed reward-basis signal. The user's original framing ("rewards have 0 cost by default, so the flag is a false positive") holds for the 2025 dataset and the deferral was correct. Verification method: openpyxl read of the generated report workbook (specific lot/amount counts omitted from this record as personal portfolio data).

**Finding.** Under PT crypto tax, a reward is taxed at receipt (Category E/F) at fair-market value; that FMV becomes the acquisition cost basis for the token. When the taxpayer later disposes of the rewarded token, `Cost (EUR)` on the disposal row should equal the FMV-at-receipt. If Koinly shows `Cost (EUR) == 0` on a disposal whose acquisition traces back to a reward event, that is a genuine basis-tracking failure (gain overstated, tax understated), NOT a "reward with 0 cost is legitimate" case.

The original user framing ("rewards have 0 cost by default, so the flag is a false positive") is **incorrect** under PT law. The active plan's Task 1 does not validate this distinction; it simply trusts that aggregated disposals with non-zero cost/proceeds/gain are fine even if one underlying lot is reward-derived zero-basis.

**Why deferred.** We do not have evidence in the 2025 export that this is actually happening. The reward-derived aggregated rows the user pointed to all show non-zero aggregated `cost_eur`, which means *some* lot in each group has a real cost basis, but we cannot tell from the aggregated row alone whether other lots in the group are reward-derived with cost=0. Verifying requires tracing each lot back to its acquisition event in TH, which is a separate investigation. (Specific asset/wallet/lot identifiers are omitted here as personal portfolio data; they are in the underlying plan records for traceability.)

**Trigger to re-open.** After Task 1 lands:
1. Re-run the report and inspect any aggregated disposal row that still ends up with `review_required=True` *because every lot in the group is zero-basis* (Task 1 only drops the flag when the aggregated values are material; if the aggregated gain is also ~0 because all lots are zero-basis, the flag stays).
2. For each such row, trace the acquisition dates back to TH events and check whether the source event was a reward (`Tag=reward`, `Type=reward`) with `Net Value (EUR) > 0`. If yes → Koinly did not carry FMV into basis; the disposal's gain is overstated. Open a dedicated plan to surface a specific "reward basis not carried" flag.
3. If no such rows exist, the user's original framing holds for the current dataset and the deferral was correct.

**Likely fix-point (if triggered).** A new per-lot flag in `_rebuild_fifo_for_loan_affected_assets` / FIFO realizations: when `cost_eur == 0` AND `token_swap_history` contains "reward", emit `"Acquisition is reward-derived but basis is zero: verify Koinly carried reward FMV into cost"`. Keep at lot level (not aggregated) so it survives Task 1's re-evaluation.

---

## 3. Homoglyph-scam token silently aggregated into real disposals

**Finding.** The CG export contains several assets whose tickers use Cyrillic or lookalike Unicode characters that visually masquerade as legitimate tickers:

```
EТH      (Cyrillic Т)    3 rows, all-zero
WBТC     (Cyrillic Т)    2 rows, all-zero
UЅDТ     (Cyrillic S, Т) 1 row, all-zero
```

These currently trigger `contains_non_latin_characters` → "Asset ticker contains non-Latin characters - potential homoglyph scam token" (the all-zero branch at `crypto_reporting.py:740-744`). After Task 1 lands, if such a lot is aggregated into a disposal with other legitimate lots, the homoglyph reason would survive (it is not a zero-basis-family reason; Task 1's filter preserves it per the third RED test). But if the homoglyph lot is the only lot in its group, the aggregated row would correctly show the scam-token flag.

**Why deferred.** No evidence of a problem; the existing logic works. Documented here so a future reviewer investigating "why does this aggregated disposal have a homoglyph warning" can find the trail.

**Trigger to re-open.** Only if a real disposal of a major token (ETH, WBTC, USDT with Latin characters) is ever aggregated with a homoglyph lot of the "same" ticker. That would indicate Koinly's ticker normalization is letting visually-identical tickers pool into the same FIFO bucket, which is a data-integrity bug worth its own plan.

---

## 4. Loan "no-EUR-price" classification is a downstream symptom, not a fix

**Finding.** The active plan's Task 3 introduces a "Cannot classify: no EUR price data" bucket for loan assets where Koinly returned `Net Value (EUR) == 0` for every row (LBTC in the 2025 export). This is a *label*, not a *fix*. The underlying issue is that Koinly has no price feed for LBTC (a Liquid-network Bitcoin representation), so EUR-denominated gain/loss on LBTC loans cannot be computed from the export.

**Why deferred.** Fixing this requires either:
- manually maintaining a price file for unpriced loan assets under `docs/maintenance/tax/crypto-origin/`, or
- fetching prices from a second source (CoinGecko, CoinCap) at import time.

Both are larger than the active plan and the LBTC loan in the 2025 export is immaterial (€0 classified; the user can manually price and re-export).

**Trigger to re-open.** If the user acquires more loan activity in unpriced assets (LBTC, L-BTC, other Liquid-network tokens) and the cumulative EUR exposure exceeds the existing `_MATERIALITY_THRESHOLD` (€1) or any reasonable per-asset materiality (€10?), draft a plan to ingest an external price source for the unpriced loan assets only.

---

## 5. `Crypto Reconciliation` sheet may have related review-flag rendering

**Status: Investigated and dismissed 2026-07-18.** The reconciliation sheet (`crypto_reconciliation_sheet.py`) renders only counts and a "Skipped Zero Value Tokens" table; it never reads `review_reason` text. The trigger condition does not hold.

**Finding.** The 2025 export contains a `Crypto Reconciliation` sheet (337 rows × 4 cols). The investigation did not inspect it for review-flag text that depends on the same strings changed by Task 1 (`Zero EUR value…`, `Zero acquisition cost…`). If the reconciliation sheet surfaces review_reason text, it may need a parallel update.

**Why deferred.** The active plan's `grep -rn "Zero EUR value for known crypto asset" src/ tests/` validation command will surface any source-code reference to the changed strings; if `Crypto Reconciliation` rendering depends on those strings via a constant, the grep will catch it. The deferred nature is only about *whether* the reconciliation sheet exists as a separate review surface that needs the same aggregated-boundary treatment applied.

**Trigger to re-open.** If the post-implementation grep shows `Crypto Reconciliation` references the old strings, fold a Task 1.5 into a follow-up plan applying the same filter at its rendering boundary.

---

## 6. Cross-cutting: an "aggregated review flag" invariant worth an ADR?

The active plan's Task 5 evaluates whether to append an ADR for the aggregation-boundary re-evaluation rule. The three ADR criteria:

1. **Hard to reverse?** Mildly. Reverting would re-introduce the false-positive flag on the user's aggregated rows. Not catastrophic.
2. **Surprising without context?** Yes: a future maintainer seeing "review_reason is dropped at aggregation time" might assume a bug and re-add the join.
3. **Real trade-off?** Yes: we deliberately trade per-lot traceability on the user-visible row for a cleaner aggregated view; the per-lot signal is preserved in `context.review_entries` and logs.

Two of three criteria are clearly met; the "hard to reverse" criterion is weak. The active plan leaves the ADR optional. **Deferred decision:** revisit after the plan lands and the rule has been exercised on one real tax-year export; if the rule holds up, the third criterion (real trade-off proven by use) strengthens and an ADR becomes worth writing.

---

## 7. Reward dust summary on popular-asset zero-value rewards (entire Task 2 removed from active plan 2026-07-16)

**Status: Resolved by plan 2026-07-18-crypto-dust-partition-fee-skip (Tasks 3-7), original r8 design reused, r9 discriminator correction applied.**

**Status.** Originally Task 2 of the active plan. Removed wholesale at r9 review on 2026-07-16 after the panel surfaced a design-level defect (popular-token-set membership is the wrong discriminator for the dust-vs-detail split) and the author clarified the popular-token set's actual purpose. This entry preserves the full original design, the discovery, and the proposed alternative so a future focused plan can pick it up without re-deriving the context.

### 7.1 Original design (as it stood at r8)

**Problem.** Koinly's 2-decimal `Value (EUR)` export rounds sub-cent reward values to `0,00`. For rewards on popular assets (BTC, ETH, BNB, USDT, ...) a zero value is almost certainly a rounding artifact, not a missing price feed. The original Task 2 collapsed such rows into a per-`(asset, wallet)` dust summary on the Crypto Supplementary tab, suppressing them from the Section 2 detail table while keeping niche tokens' zero-value rows on per-row `YES` flag.

**Planned implementation.** In `src/tax_reporting/application/persisting/crypto_supplementary_sheet.py:write_crypto_supplementary_sheet`:

```python
from ..crypto.classification import _contains_popular_token, _get_popular_crypto_tokens

# Function-local partition (both Section 2 and Section 4 reference it)
dust_rows = [r for r in taxable_now_entries
             if r.value_eur == 0
             and (r.asset in _get_popular_crypto_tokens()
                  or _contains_popular_token(r.asset))]
real_rows = [r for r in taxable_now_entries
             if not (r.value_eur == 0
                     and (r.asset in _get_popular_crypto_tokens()
                          or _contains_popular_token(r.asset)))]

# Empty-label conditional at call site
if not real_rows and dust_rows:
    empty_label = "All taxable-now rows classified as dust - see summary below"
elif not real_rows and not dust_rows:
    empty_label = "No taxable-now rewards"
else:
    empty_label = None  # unused

# Render real_rows via existing _write_reward_detail_rows helper (signature unchanged).
# When dust_rows is non-empty, append a bold "Dust summary:" header at row_no,
# then one row per (asset, wallet) group sorted by (asset, wallet):
#   f"{safe_cell_value(asset)} dust ({safe_cell_value(wallet)}): {count} rows, "
#   f"summed Value EUR = {summed:.2f} (Koinly 2-decimal export). "
#   f"Re-export with higher precision to verify."
# When dust_rows is empty, skip the summary block entirely.
```

**Planned Section 4 reconciliation split.** Replace `("Taxable-now rows (immediately taxable)", len(taxable_now_entries))` with two rows:
- `("Taxable-now detail rows", len(real_rows))`
- `("Taxable-now dust rows (suppressed from detail)", len(dust_rows))`

Plus the invariant `detail_count + dust_count == len(taxable_now_entries)` to guard against silent data loss in the upstream classifier.

**Planned tests.** See r8 staging doc `docs/history/reviews/2026-07-16-plan-review-review-flag-aggregation-boundary-r8.md` Task 2 prescriptions: `TestCryptoSupplementarySheetDustSummary` (six methods), `TestCryptoSupplementarySheetReconciliation.test_section4_splits_detail_and_dust_counts`, plus re-scopes for `test_reconciliation_key_value_pairs` and `test_reconciliation_empty_rewards`. The OSBGT-based `test_niche_asset_zero_value_keeps_per_row_yes_flag` is the one that broke (see 7.2).

**Planned docs.** `docs/maintenance/crypto_implementation_guidelines.md:413-419` (aggregation paragraph) and `:1605-1610` (zero-value popular-token paragraph); `docs/maintenance/crypto_reporting_guidelines.md` (new CRG rule for aggregation-boundary re-evaluation); glossary entries for "Reward dust".

### 7.2 Why the design broke (r9 finding)

The discriminator `r.asset in _get_popular_crypto_tokens() or _contains_popular_token(r.asset)` was treated as equivalent to "Koinly can price this asset; a zero is a sub-cent rounding artifact". It is not. The popular-token set has a different purpose: it is an explicit allowlist of tokens whose zero-value rewards should be **flagged for review (per-row YES)**, not silently dropped as spam. The set was built by the author specifically to **prevent** tokens like OSBGT/PBERA/SWBERA/STBGT/BGT from being ignored. From `docs/maintenance/tax/popular_crypto_tokens.json`:

> "If a reward for one of these tokens has zero value, it's likely a Koinly data error (missing price data, export issue) and should be flagged for review instead of skipped."

The author's actual mental model (confirmed verbally 2026-07-16): these berachain-ecosystem and exchange-platform tokens are **illiquid wrappers that Koinly often cannot price**. They were added to the popular set so zero-value rewards in them would surface for manual review, NOT because Koinly was expected to price them. BGT is the exception (acquired via staking, redeemable 1:1 for BERA); the rest (OSBGT, IBGT, LBGT, STBGT, IBERA, SWBERA, PBERA) are genuinely illiquid.

Verification at r9:

```
OSBGT        in_set=True  contains=True    (explicitly listed in exchange_platform_tokens)
XFATBERA     in_set=False contains=True    (substring "BERA" match)
EWBERA-4     in_set=False contains=True    (substring "BERA" match)
PBERA        in_set=True  contains=True    (explicitly listed in berachain_ecosystem)
SWBERA       in_set=True  contains=True    (explicitly listed in exchange_platform_tokens)
BGT          in_set=True  contains=True    (explicitly listed in berachain_ecosystem)
STBGT        in_set=True  contains=True    (explicitly listed in exchange_platform_tokens)
```

Under the original Task 2 logic, all eight tokens route to `dust_rows` and get summarized with the misleading hint "Re-export with higher precision to verify." For OSBGT/PBERA/SWBERA/STBGT re-exporting does nothing because Koinly has no price feed. The headline test `test_niche_asset_zero_value_keeps_per_row_yes_flag` used OSBGT as its fixture and could not pass.

### 7.3 Popular-token set is consumed in three places; pruning is wrong

The set has three existing call sites in `src/tax_reporting/application/crypto_reporting.py:730, 955, 1012`. All three flag zero-value rewards for popular assets. **Pruning the berachain/exchange tokens from the JSON to fix the dust discriminator would defeat the author's original purpose at all three call sites**: those tokens would go back to being silently dropped. The JSON is not the defect; the dust discriminator's use of it is.

### 7.4 Proposed alternative discriminator for a future plan

**Has-any-priced-row.** Dust-vs-detail should split on whether Koinly demonstrably has a price for the asset in this export, not on popular-set membership:

- **Dust case**: the asset has at least one non-zero priced row somewhere in this export; this row's zero is a sub-cent rounding artifact. Summarize with the re-export hint.
- **Genuinely-unpriced case**: the asset has zero non-zero rows in this export (every row for this asset is `value_eur == 0`). Koinly has no price feed. Keep the per-row `YES` flag so the author sees each row and can manually price it.

Implementation sketch:

```python
priced_assets_in_export = {r.asset for r in all_reward_entries if r.value_eur > 0}

dust_rows = [r for r in taxable_now_entries
             if r.value_eur == 0
             and r.asset in priced_assets_in_export]
# real_rows = taxable_now_entries with dust_rows removed
# Zero-value rows on assets NOT in priced_assets_in_export stay on per-row YES.
```

This matches the author's intent: BTC/ETH/USDT sub-cent rewards become dust; OSBGT/PBERA/SWBERA/STBGT (genuinely unpriced) keep per-row YES.

### 7.5 What to re-open

**Trigger.** The active plan lands Task 1 (aggregated review flag re-evaluation) and Task 3 (five-sentinel loan classification). After running the next real export, inspect the Crypto Supplementary tab. If zero-value reward rows for popular-but-illiquid tokens (OSBGT, PBERA, SWBERA, STBGT, etc.) are noisy enough to warrant grouping, open a focused plan using the discriminator in 7.4.

**Carry-forward from the r1-r9 review corpus.** The full test prescription, reconciliation-split design, and docs updates from the original Task 2 are captured above and in the r8 staging doc. The r7 architecture concern (sheet writer as classification site, r7 #2) and the r8 architecture concerns (fill duplication r8 #9, prefix-tuple duplication r8 #10, three sheet-test methods r8 #11) all transferred with Task 2; do NOT carry them as open items for the active plan after the removal.

### 7.6 Pointers

- r8 staging doc: `docs/history/reviews/2026-07-16-plan-review-review-flag-aggregation-boundary-r8.md` (Task 2 prescriptions at full detail).
- r9 staging doc: `docs/history/reviews/2026-07-16-plan-review-review-flag-aggregation-boundary-r9.md` (finding #1, the OSBGT discovery; finding #4 missing imports for loan_activity_sheet / test files are unaffected by Task 2 removal and stay open against Task 3).
- Popular-token JSON: `docs/maintenance/tax/popular_crypto_tokens.json` (do not prune without re-reading 7.3 above).
- Production helpers: `src/tax_reporting/application/crypto/classification.py:344-370` (`_get_popular_crypto_tokens`, `_contains_popular_token`).
- Production consumers: `src/tax_reporting/application/crypto_reporting.py:730, 955, 1012`.

---

## 8. Deferred-side zero-value reward noise resolved by the deferred-reward-dust-skip plan

**Status: Resolved by plan `docs/history/plans/completed/2026-07-19-deferred-reward-dust-skip.md` (CRG-022).**

Item #7 above resolved the **taxable-now** half of the zero-value reward noise via the predecessor plan's CRG-021 presentation-layer partition. The **deferred** half - the much larger half on a crypto-heavy portfolio (zero-value deferred reward rows in the real 2025 export, split between dust candidates on priced assets and genuinely-unpriced rows on assets Koinly has no price feed for) - was explicitly out of scope for the predecessor plan: CRG-021 Invariant 1 forbade touching `deferred_entries`, and the predecessor's `taxable_now_entries` scope can only ever see the fiat-denominated rewards (all non-zero), so its partition caught 0 rows on the real export. This item records that the deferred-side noise is now resolved. (Specific portfolio counts are omitted here as personal data; see the underlying plan's real-data trace for the qualitative shape.)

The successor plan chose **D2 (parse-time skip)** rather than the predecessor's D1 (presentation-only) because the deferred reward rows feed no tax computation: `aggregate_taxable_rewards` filters to `taxable_now`; `reward_total_eur` sums `value_eur` (zeros contribute nothing); the FIFO/cost-basis pipeline reads neither `reward_entries` nor the new `skipped_zero_value_deferred_rewards` list (grep-clean across `crypto_fifo/`). Zero-value deferred rows are now relocated at parse time into `skipped_zero_value_deferred_rewards` (full-fidelity `CryptoRewardIncomeEntry` list, not count-only), and the Crypto Supplementary tab renders ONE "Suppressed zero-value deferred rewards" block from that list with a per-row reason column (dust vs. unpriced). The shared `_priced_assets_in_export` discriminator is reused by both CRG-021's `_partition_taxable_now` and the new `_partition_skipped_rewards` sibling. Section 4 reconciliation splits the deferred line into detail/dust/unpriced; the Crypto Reconciliation sheet carries a sibling audit line so the cross-sheet reward-row count stays reconciled.

The specific row counts are documented context from the plan's real-data trace, NOT code constants - AGENTS.md's no-hardcoded-value rule cuts against pinning them as fixed thresholds; the skip is data-driven on whatever zero-value deferred rows the export contains.

**Trigger to re-open.** If a future export surfaces a class of zero-value deferred reward rows that should NOT be suppressed (e.g. a future tax-law change taxing deferred rewards at receipt, or a new evidence type that makes the per-row `YES:` flag actionable for some sub-class), re-open CRG-022 to scope a narrower suppression. The `skipped_zero_value_deferred_rewards` list preserves full fidelity so any sub-class can be re-rendered in the detail table without re-parsing the source CSV.
