# Deferred findings: review-flag aggregation-boundary investigation

Companion to `docs/history/plans/2026-07-15-review-flag-aggregation-boundary.md`. Captures findings surfaced during the investigation that are explicitly **out of scope** for the active plan but warrant follow-up. Each entry has a recommended trigger condition for re-opening.

## 1. FEE-token tracking entries pollute the per-lot review list

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

**Finding.** Under PT crypto tax, a reward is taxed at receipt (Category E/F) at fair-market value; that FMV becomes the acquisition cost basis for the token. When the taxpayer later disposes of the rewarded token, `Cost (EUR)` on the disposal row should equal the FMV-at-receipt. If Koinly shows `Cost (EUR) == 0` on a disposal whose acquisition traces back to a reward event, that is a genuine basis-tracking failure (gain overstated, tax understated), NOT a "reward with 0 cost is legitimate" case.

The original user framing ("rewards have 0 cost by default, so the flag is a false positive") is **incorrect** under PT law. The active plan's Task 1 does not validate this distinction; it simply trusts that aggregated disposals with non-zero cost/proceeds/gain are fine even if one underlying lot is reward-derived zero-basis.

**Why deferred.** We do not have evidence in the 2025 export that this is actually happening. The aggregated rows the user pointed to (USDT ByBit 109-lot, USDT Wirex 2-lot, SEI Kraken 47-lot, TIA Kraken 53-lot) all show non-zero aggregated `cost_eur`, which means *some* lot in each group has a real cost basis, but we cannot tell from the aggregated row alone whether other lots in the group are reward-derived with cost=0. Verifying requires tracing each lot back to its acquisition event in TH, which is a separate investigation.

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
