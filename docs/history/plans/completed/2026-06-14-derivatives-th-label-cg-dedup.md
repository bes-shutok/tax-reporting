# Plan: Derivatives TH-Label CG Dedup

Reference: `docs/plans/completed/2026-06-13-derivatives-separation.md` (predecessor plan)
Investigation: the derivatives-separation test-failure investigation (local) and in-session data trace (2025-01-24 USDT ByBit case)
Related decision points: DP-012 (`separate_derivatives_reporting`) in `docs/tax/decision_points/2025.md`
Legal basis: CIRS art. 10(1)(e) (derivatives) vs art. 10(1)(k) (cryptoassets); AT Binding Ruling Processo 28298/2025
Scale note: this revision (2026-06-15) pulls Monitors 2, 4, 5 into scope after the user disclosed real transaction volume (tens of thousands to millions per year). At that scale, the original date-plus-amount matcher produces dozens of false negatives (FIFO-split lots) and false positives (same-date same-amount collisions) annually.
Plan review: the th-label-cg-dedup plan review (local) (r1, incorporated: B1-B3, M1-M5, L1-L4, Mo1-Mo2); the th-label-cg-dedup plan review (local) (r2, incorporated: B1-new, M1-new, M2-new, M3-new, L1-new, L2-new, L3-new; Mo1-Mo3 are implementer-verification items); the th-label-cg-dedup plan review (local) (r3, incorporated: B1-r3, M1-r3, L1-r3); the th-label-cg-dedup plan review (local) (r4, ready=YES, 0 Blocker, 0 Medium, 2 Low). Post-r4 additions (warning aggregation per Design Invariant 15, SRP audit per Design Invariant 16, sub-orchestrator extraction in Task 6, Monitor items 5-6) pending r5 review.

## Terms

- **OGR**: Koinly "Other Gains Report" - CSV with `Date,Asset,Amount,Value (EUR),Type,Wallet Name`. `Type` is `Profit` or `Loss`. Date is day-level (no time component).
- **CG**: Koinly "Capital Gains Report" - FIFO lot disposals. Date column is timestamp-level (`DD/MM/YYYY HH:MM`, minute precision, no seconds).
- **TH**: Koinly "Transaction History" - raw events with timestamp (`YYYY-MM-DD HH:MM:SS UTC`, second precision), Type (`crypto_withdrawal`, `crypto_deposit`, `exchange`, etc.), Label (`Funding fee`, `Futures fee`, `Realized gain`, `Reward`, etc.), and amounts.
- **Derivatives TH event**: A `crypto_withdrawal` TH row whose Label is in the configured derivatives label set (e.g., `Funding fee`, `Futures fee`, `Realized gain`). These events represent futures funding payments, futures trading commissions, and realized P&L on derivatives positions.
- **CG dedup**: The bug fixed by this plan. Koinly reports a single derivatives disposal in BOTH the CG report (with FIFO cost-basis trail) AND the OGR report (with realized P&L). When `separate_derivatives_reporting=True`, both surfaces land in the tax report, producing double-counting: the same disposal appears in Crypto Gains as a gain AND in Derivatives P&L as a loss.
- **Derivatives label config**: A JSON config file under `docs/tax/derivatives_labels/<provider>_<year>.json` that lists the TH Label strings identifying derivatives events for a given provider and year. Per data-source and per year because providers and years may use different Label vocabularies.
- **Match key**: The tuple `(timestamp, asset, wallet, amount)` used to pair a derivatives TH event to CG lots. `timestamp` is minute-precision (`YYYY-MM-DD HH:MM`, UTC), derived from both the CG `Date Sold` column (minute precision) and the TH `Date` column (second precision, truncated to minute). `amount` is quantized to 6 decimals via `Decimal.quantize(Decimal("0.000001"))`.
- **FIFO-split lot set**: Multiple CG lots at the same `(timestamp, asset, wallet)` whose individual amounts do not equal the TH event amount, but whose sum does (within tolerance). This happens when Koinly's FIFO engine splits a single disposal across multiple acquisition tranches. FIFO consumption is contiguous: a single disposal consumes a contiguous range of the acquisition queue sorted by acquisition_date, so the CG lots for one disposal form a contiguous block within the `(timestamp, asset, wallet)` group.
- **Contiguous-range fallback matching**: The phase-2 matcher. When a TH event has no exact `(timestamp, asset, wallet, amount)` match, scan unmatched CG lots at the same `(timestamp, asset, wallet)` sorted by acquisition_date and find a contiguous range (sliding window) whose sum equals the TH amount within tolerance `Decimal("0.00001") * range_size`. This matches FIFO semantics (a disposal consumes a contiguous tranche range) and is O(N) per event. Non-contiguous subset matching is NOT supported: it would risk false positives (coincidental sums of unrelated lots) and is NP-hard; a disposal that consumed non-contiguous tranches falls to the Ambiguous classifier.
- **Exact-match collision**: Multiple CG lots sharing the same `(timestamp, asset, wallet, amount)` key, matched to different TH events. At scale this is a genuine ambiguity (two equal-size disposals at the same minute) that the safety warning must surface.

## Gist & Examples

### What changes

The predecessor plan (`2026-06-13-derivatives-separation.md`) split OGR rows from CG entries at the index level. Its classifier decides per OGR row whether the row represents a derivatives event or a spot fee disposal by checking CG counterpart existence and proceeds-value matching. The plan shipped, but a real user case (2025-01-24 USDT ByBit) reveals a gap: Koinly emits the SAME disposal into BOTH the OGR report (as a Loss) AND the CG report (as a FIFO lot with cost basis). The classifier marks the OGR rows as `Ambiguous` (because the per-row aggregate-match check fails for 3 OGR rows paired 1:1 with 3 CG lots), routes them to `derivatives_entries` with `review_required=True`, AND leaves the CG lots untouched in `capital_entries`. Result: the same disposal is taxed twice, once as a positive Crypto Gains entry (+20.24 EUR) and once as a negative Derivatives P&L entry (-39.62 EUR).

The root cause is that the classifier's signal (OGR `Type` plus CG counterpart value matching) is insufficient. Koinly's TH file carries a richer signal that the predecessor plan deliberately ignored: the Label column on `crypto_withdrawal` rows (`Funding fee`, `Futures fee`, `Realized gain`) directly identifies derivatives events. Per the predecessor plan's r1 Blocker 2, TH labels were rejected as the primary classifier signal because `"Realized gain"` is used for many event types. That rejection was correct for the primary signal but wrong as a blanket exclusion: the TH Label is the right signal for the narrow task of identifying which CG lots to remove from `capital_entries` to prevent double-counting, because that decision is per-CG-lot, not per-OGR-row.

This plan introduces a CG-side filter that runs BEFORE the existing classifier. It loads the derivatives label set from a per-provider-per-year config, scans TH rows for events whose Label is in the set, and removes CG lots matching by `(timestamp, asset, wallet, amount)`. The match has two phases: exact key match first, then a contiguous-range fallback for FIFO-split lots (multiple CG lots forming a contiguous acquisition-date range whose combined amount equals one TH event). The existing OGR classifier then sees those OGR rows with no CG counterpart (`cg_matches == 0`) and classifies them as clean `Derivatives` (`"OGR Loss with no CG counterpart - derivatives realization"`), with no `review_required` flag. Crypto Gains no longer contains the duplicate disposal; Derivatives P&L retains the OGR rows as the single authoritative representation.

### Why

Concrete failure traced on the user's actual data (2025-01-24 USDT ByBit):

- TH rows (`koinly_2025_transaction_history_<ACCOUNT_TOKEN>.csv`):
  - `2025-01-24 20:00:00 UTC` `crypto_withdrawal` Label=`Funding fee` 0.088 USDT ByBit
  - `2025-01-24 23:40:53 UTC` `crypto_withdrawal` Label=`Futures fee` 0.414 USDT ByBit
  - `2025-01-24 23:40:53 UTC` `crypto_withdrawal` Label=`Realized gain` 40.755 USDT ByBit
- OGR rows (`koinly_2025_other_gains_report_<ACCOUNT_TOKEN>.csv` lines 42-44): all `Type=Loss` summing to -39.62 EUR (-0.08 + -0.40 + -39.14).
- CG rows (`koinly_2025_capital_gains_report_<ACCOUNT_TOKEN>.csv` lines 162, 164, 165): three lots with proceeds 0.08, 0.40, 39.14 EUR and gains 0.04, 0.20, 20.00 EUR.

Current pipeline output:
- Crypto Gains aggregated row: proceeds 39.62 EUR, gain +20.24 EUR (Short term, USDT, ByBit).
- Derivatives P&L aggregated row: pnl -39.62 EUR, LOSS, review_required=YES (three concatenated Ambiguous reasons).

Same underlying disposals, taxed in both tabs. The user is over-reporting both income (Crypto Gains +20.24 EUR taxable under art. 10(1)(k)) and loss (Derivatives P&L -39.62 EUR deductible under art. 10(1)(e)).

### Scale-driven expansion (2026-06-15 revision)

The original plan matched by `(date, asset, wallet, amount)` with day-level date. At the user's disclosed scale (tens of thousands to millions of transactions per year, implying thousands to tens of thousands of derivatives events), this matcher has two failure modes that produce silent double-counting or false-positive warnings:

1. **FIFO-split lots (Monitor 4, now in-scope).** When Koinly's FIFO engine splits a single derivatives disposal across multiple acquisition tranches, the per-lot amounts do not match the TH event amount. Estimate: at 1k-10k derivatives events per year with a 5-10 percent FIFO-split rate, expect 50-1000 cases per year. The original design's safety net (Ambiguous flag on the OGR row) points at the wrong tab (Derivatives P&L) while the lots needing removal sit in Crypto Gains. At scale, the user cannot manually reconcile hundreds of Ambiguous flags per year. This plan adds a contiguous-range fallback matcher.

2. **Same-timestamp same-amount collisions (Monitor 5, now in-scope).** With thousands of events over 365 days, multiple events share a date. Funding fees are paid at fixed times (00:00, 08:00, 16:00 UTC); multiple positions paying funding in the same minute is common. Two events at the same `(date, asset, wallet, amount)` cause a dict-key collision in the original matcher, losing attribution and triggering false-positive "matched count greater than 1" warnings. This plan adds a `disposal_timestamp` field (minute precision) to the match key, which narrows collisions to same-minute-same-amount (rare) and preserves all TH events per key (no collision-induced data loss).

3. **Sum comparison rounding (Monitor 2, now in-scope).** Summing N independently-rounded CG lots can drift from the TH amount in the 6th decimal (e.g., 3 lots of 33.333333 sum to 99.999999, not 100.000000). Strict 6-decimal equality on sums would silently fail for 50-500 cases per year. This plan uses a tolerance of `Decimal("0.00001") * range_size` for contiguous-range comparison (absorbs per-lot rounding accumulation) while keeping strict 6-decimal quantization for exact single-lot matching.

### Examples (before to after)

**Before (2025-01-24 USDT ByBit):**
- Crypto Gains: `2025-01-24 USDT ByBit gain=+20.24 EUR` (3 CG lots aggregated).
- Derivatives P&L: `2025-01-24 USDT ByBit LOSS pnl=-39.62 EUR review=YES`.

**After (2025-01-24 USDT ByBit):**
- Crypto Gains: no row for this key (all 3 CG lots removed because their TH events carry derivatives Labels).
- Derivatives P&L: `2025-01-24 USDT ByBit LOSS pnl=-39.62 EUR review=NO` (the 3 OGR rows now classify as clean Derivatives because their CG counterparts were removed; no review flag, no ambiguity).

**Spot trade unaffected (e.g., 2025-01-13 USDT to SUI exchange):**
- TH row Label is empty or `Exchange` (not in the derivatives set).
- CG lot stays in `capital_entries`; Crypto Gains shows the spot disposal as before.

**FIFO-split disposal (scale-driven example, new):**
- TH event: `2025-01-24 23:40:53 UTC crypto_withdrawal Label=Realized gain 120.000000 USDT ByBit`.
- CG lots (FIFO-split across 2 contiguous tranches): lot A amount=70.000000 (acquired 2025-01-10), lot B amount=50.000000 (acquired 2025-01-12).
- Original matcher (date plus amount): no single CG lot has amount 120.0; both lots stay in Crypto Gains; OGR row flagged Ambiguous. Double-counting persists.
- New matcher: exact match fails (no lot at 120.0). Contiguous-range fallback finds range {A, B} (sorted by acquisition_date, contiguous, sum 120.0 within tolerance) and removes both. OGR row classifies as clean Derivatives. No double-counting.
- Note: if the lots were NOT contiguous in acquisition_date order (e.g., lot A acquired 2025-01-10, lot B acquired 2025-01-12, but an unrelated lot C acquired 2025-01-11 sits between them), the contiguous-range matcher would NOT match. This is intentional: non-contiguous consumption does not match FIFO semantics and falls to the Ambiguous classifier for manual resolution.

**Same-timestamp same-amount events (scale-driven example, new):**
- TH events: two `Funding fee` rows at `2025-01-24 08:00 UTC`, each 0.500000 USDT, ByBit (two positions, same funding period, same fee).
- CG lots: two lots at `(2025-01-24 08:00, USDT, ByBit, 0.500000)`.
- Original matcher: dict-key collision, only one TH event survives in the lookup. Both lots still get removed (membership check), but attribution is lost and a false-positive "matched count greater than 1" warning fires.
- New matcher: match key is `(timestamp, asset, wallet, amount)`. Both TH events and both CG lots share the same key. Each TH event consumes one lot from the key's deque (deterministic order). Both lots removed, both TH events attributed. No false-positive warning.

### Why config-driven labels

Per CLAUDE.md section 4, hardcoded constant sets must be flagged. The derivatives label set is provider-specific and year-specific: Koinly may change Label vocabulary across years (Koinly 2024 vs Koinly 2025), and a future data source (different tax-year provider for 2026+) may use entirely different terminology. The config lives under `docs/tax/derivatives_labels/<provider>_<year>.json` so a maintainer can add a new file without code changes. Missing config degrades gracefully (warning plus no removal; current behavior).

### Why match by timestamp + asset + wallet + amount

- **Timestamp (minute precision)** narrows the candidate set to disposals in the same minute. The CG `Date Sold` column is minute precision (`DD/MM/YYYY HH:MM`); TH `Date` is second precision (`YYYY-MM-DD HH:MM:SS UTC`) and is truncated to minute for matching. Both normalize to `%Y-%m-%d %H:%M` UTC via `parse_koinly_datetime` (which adds UTC when no tzinfo is present) then `strftime("%Y-%m-%d %H:%M")`. Minute precision is sufficient because two derivatives disposals in the same minute with the same amount is rare (requires two equal-size trades or funding fees in the same 60-second window). Second precision would require adding seconds to the CG parser, but the CG CSV does not carry seconds (column format is `DD/MM/YYYY HH:MM`).
- **Asset plus wallet** narrows to the disposal event on a specific platform. Wallet normalization is ByBit-specific (`normalize_platform_name` collapses `ByBit (2)` to `ByBit`; Kraken and Binance keep numbered suffixes). Extending to other platforms requires updating the normalizer, not the dedup logic.
- **Amount** disambiguates when multiple events share a timestamp. The 2025-01-24 case has two derivatives events at the same minute (Futures fee 0.414 USDT and Realized gain 40.755 USDT, both at 23:40) distinguished by amount. Amount comparison rounds both values to 6 decimals via `Decimal.quantize(Decimal("0.000001"))` before equality check (exact match phase). This absorbs Koinly rounding differences (TH amounts are raw chain amounts; CG amounts are FIFO-resolved and may differ in the last decimal) without introducing a fuzzy tolerance window for single-lot matching.
- **Determinism**: CG lots are sorted by `(timestamp, asset, wallet, amount, acquisition_date)` and TH events by `(timestamp, asset, wallet, amount)` before matching. The same input always produces the same output; no reliance on dict iteration order.

### Why contiguous-range fallback for FIFO-split lots

At scale, Koinly's FIFO engine splits a single derivatives disposal across multiple acquisition tranches when the disposed amount exceeds the first tranche. The per-lot amounts do not match the TH event amount, but their sum does. Without a fallback, these disposals stay in Crypto Gains (double-counting persists) and the OGR row flags as Ambiguous (pointing at the wrong tab).

The contiguous-range fallback runs after the exact-match phase. For each unmatched TH event, it scans unmatched CG lots at the same `(timestamp, asset, wallet)` sorted by acquisition_date and uses a sliding window to find a contiguous range whose sum equals the TH amount within tolerance `Decimal("0.00001") * range_size`. The tolerance scales with range length to absorb per-lot rounding accumulation (each lot is independently rounded to 6 decimals; summing N lots can drift by up to N times 0.0000005).

**Why contiguous, not subset-sum.** FIFO consumption is inherently contiguous: a single disposal consumes the oldest available acquisition tranches, which form a contiguous block when lots are sorted by acquisition_date. Matching this semantics directly (sliding window over sorted lots) is O(N) per event. General subset-sum would be NP-hard and would risk false positives: with 108 CG lots at one timestamp (the Case 2 fixture), coincidental non-contiguous subsets summing to any target are virtually guaranteed, leading to silent over-removal. The contiguous constraint eliminates this risk while correctly handling the realistic FIFO-split case.

When no contiguous range matches, the event is marked unmatched and falls through to the existing Ambiguous classifier on the OGR row. This covers the rare case of non-contiguous consumption (e.g., cross-asset transfer interleaving), which is not a FIFO pattern and warrants manual review.

**Determinism.** CG lots are sorted by `(timestamp, asset, wallet, acquisition_date, row_index)` before matching. The sliding window finds the first (lowest starting index) matching range. The same input always produces the same output.

### Why per-lot INFO and summary WARNING for logging

Per CLAUDE.md repository constraint, data-loss conditions must be logged at warning or higher. Removing a derivatives-flagged CG lot is intentional correction (the lot represents a derivatives disposal that belongs in Derivatives P&L, not Crypto Gains), not unintentional data loss. At scale (thousands of removals per year), per-lot WARNING lines flood the log and drown genuine warnings. This plan logs each removal at INFO level (audit-traceable in debug logs) and emits a single WARNING summary at the end with the total count, breakdown by match type (exact vs sum), and aggregate proceeds and gain removed. The summary preserves the data-loss audit signal required by CLAUDE.md without the noise.

The safety signal for exact-match collisions (multiple CG lots sharing the same key, matched to different TH events) and for malformed-input lots (zero or negative amounts) is AGGREGATED into the same summary WARNING, not emitted per-lot. At the user's disclosed scale, per-lot collision or data-quality WARNINGs would flood the log and train the user to ignore the warning level entirely; aggregating into the summary preserves the signal (the user sees "N surplus lots detected, review keys X, Y, Z" or "M malformed-input lots skipped, investigate the source export") without the noise.

### Edge cases motivating the design

1. **Multiple TH rows with the same derivatives Label on the same timestamp** (e.g., two realized-loss events closing two positions at the same minute): both become derivatives TH events; each matches its CG lot(s) by amount (exact or sum). Both sets of CG lots are removed.
2. **CG lot on a derivatives timestamp but different amount** (e.g., a spot disposal in the same minute as a derivatives disposal): only the CG lot(s) whose amount matches a TH event (exact or sum) are removed. The spot lot stays in Crypto Gains.
3. **Derivatives Label on a `crypto_deposit`** (not `crypto_withdrawal`): the config filters by Type=`crypto_withdrawal`; deposits with derivatives Labels are ignored. Realized P&L on ByBit is always a withdrawal in current Koinly exports.
4. **`separate_derivatives_reporting=False`**: the dedup is skipped entirely. Backward compatibility is preserved byte-identically (same flag, same default).
5. **Config file missing when flag is True**: warn at startup, run with empty derivatives label set. The pipeline degrades to the predecessor plan's behavior (current double-counting risk) but the warning surfaces the misconfiguration.
6. **Provider or year not yet supported** (no config file): same as missing config; warning plus no removal. Adding a provider requires dropping a new JSON file under `docs/tax/derivatives_labels/`; no code change.
7. **Malformed config file** (invalid JSON, missing keys): raise `FileProcessingError` at startup with the file path and the parse error. Fail fast; do not silently use an empty label set.
8. **FIFO-split disposal** (single TH event, multiple contiguous CG lots summing to the TH amount): contiguous-range fallback finds the range and removes all lots in it. Logged at INFO with match type "range" and range size.
9. **Multiple disposals at the same timestamp** (multiple TH events, multiple CG lots, all at the same `(timestamp, asset, wallet)`): exact-match phase processes each TH event against the key's deque (sorted by acquisition_date) deterministically. Remaining unmatched events use the contiguous-range fallback over the remaining unmatched lots. If no range matches, the event falls to Ambiguous.
10. **Exact-match collision** (multiple CG lots with identical amount at the same key): the matcher consumes one lot per TH event from the key's deque (deterministic order by acquisition_date). If there are more lots than events at the key, the surplus lots are collected and included in the summary WARNING's "surplus lots" section (count, total amount, sample of up to 3 keys) - no per-lot WARNING fires. If the deque at a key is empty when a TH event tries to consume, the event falls through to the contiguous-range fallback; if that also fails, the event is marked unmatched.
11. **Contiguous-range fallback fails** (no contiguous range of lots matches the TH amount within tolerance): the event is marked unmatched and falls to the Ambiguous classifier on the OGR row. The OGR row's `review_reason` is updated to hint at the Crypto Gains tab (not just Derivatives P&L).
12. **Non-contiguous consumption** (disposal consumed tranches that are not adjacent in acquisition_date order, e.g., due to cross-asset transfer interleaving): contiguous-range matcher correctly does NOT match. The event falls to Ambiguous. This is intentional: non-contiguous consumption violates FIFO semantics and warrants manual review.

## Evaluation Criteria

**Quality dimensions:**

- **Correctness (double-counting elimination):** for the user's actual 2025-01-24 USDT ByBit case, the pipeline produces no Crypto Gains entry AND a clean Derivatives P&L entry (-39.62 EUR, no review flag). Verified by an end-to-end test that traces source CSV rows through to the final `CryptoTaxReport`.
- **Correctness (FIFO-split elimination):** for a synthetic fixture with 1 TH event and 2+ contiguous CG lots summing to the TH amount, the pipeline removes all lots in the matching range and produces no Crypto Gains entry. Verified by a unit test.
- **Correctness (spot trades preserved):** for CG lots whose TH row Label is NOT in the derivatives set (e.g., the 2025-01-13 USDT to SUI exchange), the CG lots stay in `capital_entries` and the Crypto Gains output is unchanged.
- **Backward compatibility (byte-identical):** with `separate_derivatives_reporting=False`, the generated output is byte-identical to the predecessor plan's output. The existing `TestOgrCharacterizationGolden` tests continue to pass.
- **Config-driven label set:** the derivatives label set is loaded from `docs/tax/derivatives_labels/<provider>_<year>.json`. Adding a new provider or year requires only a new JSON file.
- **No silent drops:** removed CG lots are logged at INFO (per-lot) and WARNING (summary) with disposal timestamp, asset, wallet, amount, matching TH Label, and match type (exact or sum). The user can audit removals in debug logs; the summary surfaces the aggregate at warning level.
- **Deterministic matching:** the same input produces the same output; CG lots and TH events are sorted by stable keys before matching. No reliance on dict iteration order.
- **Determinism under same-key collisions:** when multiple TH events share a `(timestamp, asset, wallet, amount)` key, each event consumes exactly one CG lot from the key's deque (sorted by acquisition date). No TH event is lost to dict overwrite.
- **Performance at scale:** for a fixture with 10,000 CG lots and 1,000 derivatives TH events, the dedup completes in under 2 seconds (exact match is O(N); contiguous-range fallback is O(N) per event via sliding window). Verified by a unit test with a large synthetic fixture including a worst-case single-event-500-lots scenario.
- **Logging signal-to-noise at scale:** per-lot removals log at INFO; exactly one WARNING summary is emitted per pipeline run with aggregate counts for ALL signal types (intentional removals, surplus lots from exact-match collisions, malformed-input lots with non-positive amounts). No per-lot WARNING lines (see Design Invariant 15).

**Release gates:**

- Tier 1 tests pass (see Validation Commands).
- Tier 2 full regression passes (`uv run pytest`, no marker filter, per Finding 6 of the derivatives-separation test-failure investigation (local)).
- New end-to-end data trace test with real ByBit fixtures confirms the 2025-01-24 fix.
- New unit tests confirm FIFO-split handling, same-timestamp collision handling, and performance at scale.
- `uv run ruff check src tests` clean (no new errors beyond the pre-existing baseline).
- Manual Excel check: 2025-01-24 USDT ByBit appears in Derivatives P&L only; Crypto Gains no longer shows this key.

## Review Scope

**Explicit must-fix** - findings on these paths are always in scope (review and fix if valid):

**Production code:**
- `docs/tax/derivatives_labels/koinly_2025.json` *(new)* - config file with the 3 ByBit derivatives labels
- `src/tax_reporting/application/crypto/derivatives_dedup.py` *(new)* - config loader, TH scanner, CG filter with exact and contiguous-range matching
- `src/tax_reporting/application/crypto/entities.py` - add `disposal_timestamp` field to `CryptoCapitalGainEntry`
- `src/tax_reporting/application/crypto/fifo_helpers.py` - propagate `disposal_timestamp` from `CryptoFifoRealization` to `CryptoCapitalGainEntry`
- `src/tax_reporting/application/crypto_fifo/contexts.py` - add `timestamp_str` to `ParsedTxRow`
- `src/tax_reporting/application/crypto_fifo/parsing.py` - populate `timestamp_str` from TH Date before `format_datetime` strips it; pass `disposal_timestamp` to 6 `CryptoConsumption` constructor sites (lines 404, 422, 465, 488, 658, 688)
- `src/tax_reporting/application/crypto_fifo/_emitters.py` - pass `disposal_timestamp` to 9 `CryptoConsumption` constructor sites (lines 73, 91, 129, 233, 251, 288, 353, 391, 425)
- `src/tax_reporting/application/crypto_fifo/matching.py` - propagate `disposal_timestamp` from `CryptoConsumption` to `CryptoFifoRealization` at 2 constructor sites (lines 167, 281)
- `src/tax_reporting/domain/crypto_fifo.py` - add `disposal_timestamp` to `CryptoConsumption` and `CryptoFifoRealization`
- `src/tax_reporting/application/crypto_reporting.py` - wire the new dedup step into the pipeline between validation and OGR split; gate on `separate_derivatives_reporting`; populate `disposal_timestamp` in the CG parser
- `src/tax_reporting/application/crypto/__init__.py` - export new public functions if needed
- `docs/domain/crypto_implementation_guidelines.md` - document the TH-label-driven dedup logic, timestamp matching, contiguous-range fallback, and per-provider-per-year config convention

**Tests:**
- `tests/unit/application/test_derivatives_dedup.py` *(new)* - unit tests for config loader, TH scanner, CG filter (exact and contiguous-range matching), edge cases, and performance at scale
- `tests/unit/application/test_fifo_helpers.py` *(or existing FIFO test file)* - verify `disposal_timestamp` propagation through the FIFO chain
- `tests/end_to_end/test_crypto_derivatives_separation.py` - extend with a Case 3 data trace test for the 2025-01-24 ByBit fix; update Case 1 and Case 2 for the new behavior

**Plan-related extension** - implementation and review may change files not listed above. Treat a finding as in scope when it is **causally related to this plan**: it implements or completes a plan task, fixes a regression introduced by plan work, closes wiring or docs implied by an explicit must-fix change, or contradicts a contract the plan changed. If the link to the plan is weak or speculative, drop as out of scope with a one-line reason.

**Out of scope - reject unless plan-related:**
- `src/tax_reporting/application/crypto/classification.py` - the OGR classifier is unchanged. Its branches still apply; with CG counterparts removed, more OGR rows fall into the clean `Derivatives` branch naturally. Do not change classifier logic.
- `src/tax_reporting/application/crypto/ogr_handler.py` - `_split_ogr_index` is unchanged. The dedup happens upstream (capital_entries is filtered before _split_ogr_index is called).
- `src/tax_reporting/application/persisting/derivatives_sheet.py` - Excel rendering unchanged.
- `docs/domain/crypto_rules.md` - no new rule; PT-C-034 still governs.
- `docs/tax/decision_points/2025.md` - no new decision point; DP-012 still governs.

## Design Invariants (CR Guard)

Prior-phase decisions and repository contracts that must not be compromised:

1. **Predecessor plan invariants preserved** (`docs/plans/completed/2026-06-13-derivatives-separation.md` Design Invariants 1-18): all 18 invariants from the predecessor plan remain in force. This plan adds a CG-side filter; it does not relax any prior invariant.
2. **Filter runs after FIFO rebuild and country validation** (predecessor Design Invariant 2 extended): the dedup step is inserted at `crypto_reporting.py` approximately line 205, immediately after `_validate_capital_entries_have_valid_countries` (line 200) and immediately before the OGR split block (line 210). This ensures the filter sees FIFO-rebuilt lots and validated country codes.
3. **Filter runs before `_split_ogr_index`**: by removing derivatives-flagged CG lots from `capital_entries` before the OGR classifier sees them, the classifier naturally categorizes the matching OGR rows as `Derivatives` (empty `cg_matches`) instead of `Ambiguous` (multiple `cg_matches`). The classifier itself is unchanged.
4. **Gating follows the existing flag**: the dedup runs only when `jurisdiction.separate_derivatives_reporting=True`. With the flag `False`, the dedup is a no-op (the existing pipeline produces byte-identical output to the predecessor plan).
5. **Config-driven label set** (per user direction): the derivatives Label set is loaded from `docs/tax/derivatives_labels/<provider>_<year>.json`. No hardcoded label strings in production code. The provider is currently always `koinly` (the only supported source); the year is the integer returned by `_extract_tax_year`. Adding a new provider or year requires only a new JSON file.
6. **Match key is `(timestamp, asset, wallet, amount)` with two-phase matching**: phase 1 is exact match on `(timestamp_minute, normalized_asset, normalized_wallet, amount_6dp)`. Phase 2 is contiguous-range fallback for unmatched TH events: sliding window over unmatched CG lots at the same `(timestamp, asset, wallet)` sorted by acquisition_date, first matching range preferred, tolerance `Decimal("0.00001") * range_size`. CG lots are sorted by `(timestamp, asset, wallet, acquisition_date, row_index)` and TH events by `(timestamp, asset, wallet, amount)` before matching for determinism. `disposal_timestamp` is minute precision (`%Y-%m-%d %H:%M` UTC), derived from the CG `Date Sold` column via `parse_koinly_datetime` then `strftime("%Y-%m-%d %H:%M")` BEFORE `format_datetime` strips the time. TH timestamps (second precision) are truncated to minute for matching. Wallet normalization is ByBit-specific (`normalize_platform_name` collapses `ByBit (2)` to `ByBit`); extending to other platforms requires updating the normalizer, not the dedup logic.
7. **`disposal_timestamp` field is optional, default None, threaded through the FIFO chain**: added to `CryptoCapitalGainEntry`, `CryptoFifoRealization`, and `CryptoConsumption` with default `None` to preserve backward compatibility for existing constructors. `ParsedTxRow` gets a new `timestamp_str` field. Populated from the CG parser (`crypto_reporting.py` line 398 region) and from the FIFO parsing chain (`parsing.py` line 184 region captures the datetime before `format_datetime`). FIFO-derived entries (loan-affected assets like WBTC, SUI, LBTC) carry the timestamp for consistency but are not derivatives assets; the dedup naturally skips them because no derivatives TH event matches their `(timestamp, asset, wallet)` (loan-affected assets do not appear in derivatives TH Label sets).
8. **No silent drops** (CLAUDE.md repository constraint, predecessor Design Invariant 4): every removed CG lot is logged at INFO (per-lot, audit-traceable) with disposal timestamp, asset, wallet, amount, matching TH Label, and match type (exact or sum). A single WARNING summary per pipeline run carries ALL aggregate signals: (a) removal counts and totals, (b) surplus lots from exact-match collisions, (c) malformed-input lots with non-positive amounts. No per-lot WARNING lines exist (see Design Invariant 15). This satisfies the CLAUDE.md data-loss-at-warning rule (the summary is WARNING) while keeping per-lot noise at INFO for readability at scale. The summary is the authoritative data-loss audit signal.
9. **Graceful degradation for missing config**: a missing config file logs a `logger.warning` and runs with an empty label set (no removal; current behavior). A malformed config file (invalid JSON, missing `derivatives_th_labels` key, wrong type) raises `FileProcessingError` at startup.
10. **Characterization test golden values unchanged for `separate_derivatives_reporting=False`**: the existing `TestOgrCharacterizationGolden` tests (Case 1=<MIXED_AGGREGATE_EUR>, Case 2=-<CG_LOTS_EUR>) continue to pass without modification because the dedup is gated off.
11. **Case 2 behavior may change for `separate_derivatives_reporting=True`**: the approximately 108 CG lots for 2025-01-13 USDT ByBit include 2 derivatives-flagged lots (Funding fee <FUNDING_FEE_USDT> USDT and Futures fee <FUTURES_FEE_USDT> USDT). The <REALIZED_GAIN_USDT> Realized gain OGR row has NO CG counterpart (the amount does not appear in the CG report; it is FIFO-split internally or synthetically treated by Koinly), so the existing classifier already routes it to `Derivatives` cleanly and the dedup does not change its routing. After dedup, the 2 matching CG lots are removed and the Crypto Gains aggregate is smaller than plus <CG_LOTS_EUR> EUR. The exact new value is computed by the implementation; the e2e test asserts the new value (whatever it is) and verifies the matching OGR rows still land in Derivatives P&L. The characterization test (Case 2 with flag=False) is unaffected.
12. **Contiguous-range fallback tolerance scales with range size**: exact single-lot match uses strict equality at 6-decimal quantization (both sides quantized to `Decimal("0.000001")`). Contiguous-range match uses tolerance `Decimal("0.00001") * range_size` (10x the per-lot rounding error, absorbing accumulation). No cap on range size is needed because the sliding window is O(N) per event regardless of range length.
13. **Safety warning differentiates exact-match collisions from FIFO splits**: the original design's "matched count greater than 1" warning fired for every FIFO split (false positive). The new design's safety warning fires ONLY for exact-match collisions (multiple CG lots sharing the same key, matched to different TH events), which is the genuine ambiguity case. FIFO splits are handled by the contiguous-range fallback without a warning.
14. **Pipeline gates the dedup on `jurisdiction is not None` AND `separate_derivatives_reporting` AND `use_other_gains_report` AND `transaction_history_file`**: the dedup runs only when all four gates hold. The `jurisdiction is not None` check is a defensive guard so a None caller fails at the gate rather than raising `AttributeError` deeper in the call chain; the other three are functional gates. If `separate_derivatives_reporting=True` but `use_other_gains_report=False`, the dedup is skipped because `_split_ogr_index` never runs and the removed CG lots would have no Derivatives P&L surface to land in (the OGR rows that would have represented them are never read). If `transaction_history_file` is None, the dedup is skipped because TH is the source of the derivatives Label signal. Gating on all four prevents a half-enabled state where CG lots are removed but the offsetting Derivatives entries are never created, and prevents NoneType attribute access when no jurisdiction context exists.
15. **Every WARNING must be actionable and non-noisy at scale** (signal-to-noise rule): no per-lot or per-event WARNING emissions. All warning-level signals are aggregated into the single summary WARNING (per Design Invariant 8). This rule applies EVEN to data-quality signals (malformed input, surplus lots): per-lot data-quality WARNINGs would flood the log at the user's disclosed scale (tens of thousands to millions of transactions per year) and train the user to ignore the warning level entirely, defeating the CLAUDE.md data-loss-at-warning rule. Data-quality issues are logged at INFO per-lot (audit-traceable) and counted in the summary WARNING (actionable in aggregate). The only valid per-occurrence WARNING is one that the user must act on individually AND that fires rarely (e.g., a critical security violation); no such case exists in this plan.
16. **Touched classes are audited for single responsibility** (SRP/DDD rule per CLAUDE.md): when a plan adds a field or method to an existing class, the class must have one reason to change. If the addition would give the class a second responsibility, extract first. For this plan: (a) the dedup wiring lives in `derivatives_dedup.py` (new module, single responsibility: derivatives CG dedup), NOT in `crypto_reporting.py` (which is already 753 lines, 50 percent over the CLAUDE.md ~500-line orchestration threshold); (b) the dedup is invoked from `crypto_reporting.py` via a single call to `apply_derivatives_dedup()` (see Task 6); (c) `ParsedTxRow` grows to 19 fields and `CryptoCapitalGainEntry` to 15 fields - these are data-clump smells monitored for extraction (see Monitor item 5), but splitting them is out of scope for this plan because the addition is one optional field that does not introduce a new responsibility.

## Validation Commands

**Tier 1 - must-fix scope (must pass for plan completion):**

```bash
# Config loader unit tests
uv run pytest tests/unit/application/test_derivatives_dedup.py -v

# FIFO chain timestamp propagation
uv run pytest tests/unit/application/test_fifo_helpers.py -v

# Existing classifier tests still pass (no regression)
uv run pytest tests/unit/application/test_crypto_classification.py -v

# Existing OGR split tests still pass
uv run pytest tests/unit/application/test_crypto_reporting.py -k "OgrSplit or ogr or Ogr" -v

# Existing characterization tests still pass (flag=False path unchanged)
uv run pytest tests/unit/application/test_crypto_reporting.py::TestOgrCharacterizationGolden -v

# End-to-end data trace with the new Case 3 fixture (2025-01-24 ByBit)
uv run pytest tests/end_to_end/test_crypto_derivatives_separation.py -v

# Lint clean (no new errors)
uv run ruff check src tests

# Config file present and well-formed
test -f docs/tax/derivatives_labels/koinly_2025.json
python -c "import json; json.load(open('docs/tax/derivatives_labels/koinly_2025.json'))"

# Search for stale references to old hardcoded labels (none should exist in production code)
grep -rE --include="*.py" "Funding fee|Futures fee|Realized gain" src/tax_reporting/ | grep -v "derivatives_dedup" || echo "No hardcoded derivatives labels in production code"

# Verify disposal_timestamp field exists on CryptoCapitalGainEntry
python -c "from tax_reporting.application.crypto.entities import CryptoCapitalGainEntry; import dataclasses; assert 'disposal_timestamp' in {f.name for f in dataclasses.fields(CryptoCapitalGainEntry)}"

# Verify disposal_timestamp propagated through FIFO chain
python -c "from tax_reporting.domain.crypto_fifo import CryptoConsumption, CryptoFifoRealization; import dataclasses; assert all('disposal_timestamp' in {f.name for f in dataclasses.fields(c)} for c in [CryptoConsumption, CryptoFifoRealization])"
```

**Tier 2 - full regression (per Finding 6 of the post-archive review, run without marker filter):**

```bash
uv run pytest
```

**Manual Excel check:**

The Koinly directory is auto-discovered based on the IB export's location. Run from the repository root so the auto-discovery path resolves correctly. Ensure `resources/source/koinly2025/` exists alongside `resources/source/ib_export.csv` (matching the existing fixture layout) so the crypto pipeline runs.

```bash
uv run tax-reporting --source-file resources/source/ib_export.csv --output-dir /tmp/derivatives-dedup-check
# Open the Excel and verify:
# - 2025-01-24 USDT ByBit appears in Derivatives P&L only (not in Crypto Gains)
# - Derivatives P&L row has review=NO (clean Derivatives classification, no Ambiguous flag)
# - Crypto Gains tab still shows other ByBit spot activity (e.g., 2025-01-13 USDT->SUI exchange)
# - Log shows exactly one WARNING summary line for the dedup (covering removals, surplus lots, and malformed-input lots in one aggregate line; no per-lot WARNINGs)
```

## Monitor

Deferred risks with named triggers and owners. Each item has a specific condition that, when observed, prompts a follow-up plan or task.

1. **Provider detection beyond Koinly** - the current pipeline detects provider implicitly (always Koinly via the directory name `koinly<year>`). The config loader hardcodes provider=`koinly` for now. **Trigger to add provider detection:** when a second data source is introduced (e.g., a different tax-year provider for 2026+), extend `_load_derivatives_labels_config` to accept the provider explicitly and update the pipeline caller to detect it from the source directory structure. Owner: future contributor adding the first non-Koinly source.

2. **Case 2 expected Crypto Gains value** - the new Crypto Gains aggregate for 2025-01-13 USDT ByBit depends on how many of the approximately 108 CG lots match derivatives TH events (currently 2: Funding fee plus Futures fee). The implementation computes the exact value; the e2e test asserts it. If a future Koinly export changes TH Labels for 2025-01-13 events (e.g., capitalizes differently), the dedup may remove more or fewer lots, changing the asserted value. **Trigger to refresh:** when a new Koinly 2025 export is provided, re-run the e2e test and update the expected value with a comment explaining the delta. Owner: this plan's implementer (Task 7).

3. **Non-contiguous FIFO consumption** - the contiguous-range matcher requires lots consumed by a single disposal to be adjacent in acquisition_date order. If a real case emerges where Koinly's FIFO engine consumed non-contiguous tranches for a single disposal (e.g., due to cross-asset transfer interleaving or a Koinly internal quirk), the matcher will not find a match and the event falls to Ambiguous. **Trigger to add non-contiguous matching:** when a real case of non-contiguous consumption is confirmed via manual trace, add a secondary fallback that allows non-contiguous subsets with a stricter tolerance and an explicit WARNING (the coincidental-collision risk is higher for non-contiguous matching). Owner: future contributor reviewing dedup matching.

4. **Second-precision timestamp collisions** - the match key uses minute precision because the CG `Date Sold` column is minute precision (`DD/MM/YYYY HH:MM`). Two derivatives disposals in the same minute with the same amount would collide. **Trigger to add second-precision matching:** when a real case emerges with two derivatives events in the same minute with the same amount (e.g., two API-placed trades executed in the same second), investigate whether the CG CSV can be re-exported with second precision, or add a cross-reference from CG row to TH row via a Koinly-internal transaction ID (if Koinly exposes one). Owner: future contributor reviewing dedup matching.

5. **`crypto_reporting.py` orchestration thinness** - the module is 753 lines at this plan's start (already 50 percent over the CLAUDE.md ~500-line orchestration threshold). This plan avoids adding orchestration logic to it (the dedup wiring lives in `derivatives_dedup.apply_derivatives_dedup()`, invoked via a single call - see Task 6 and Design Invariant 16), but the pre-existing bloat remains. **Trigger to extract sub-orchestrators:** when a future plan adds orchestration logic to `crypto_reporting.py`, first extract cohesive responsibility groups into sub-orchestrator modules (e.g., `_validate_and_normalize_entries()`, `_run_fifo_rebuild()`, `_split_capital_and_derivatives()`). The threshold for action is "any plan that adds more than 20 lines to `crypto_reporting.py`". Owner: future contributor whose plan touches `crypto_reporting.py`.

6. **`ParsedTxRow` and `CryptoCapitalGainEntry` field-count growth** - this plan adds one optional field to each (`ParsedTxRow` to 19 fields, `CryptoCapitalGainEntry` to 15 fields). Both are data classes accumulating multiple responsibilities (row data plus review flags plus origin info plus validation metadata). The addition does not introduce a new responsibility (it extends an existing timestamp concern), so extraction is deferred. **Trigger to extract value objects:** when a future plan adds another field to either class, first extract cohesive field groups into value objects (e.g., `ReviewInfo(review_required, review_reason)`, `OriginInfo(chain, operator_origin, annex_hint)`, `TimestampInfo(date, timestamp)`). The extraction is a prerequisite for the next addition, not a follow-up. Owner: future contributor adding the next field to either class.

### Task 1: Capture Case 3 characterization (RED, documents the bug)

Files:
- `tests/end_to_end/test_crypto_derivatives_separation.py` *(extend existing file)*

This task captures the current buggy behavior for the 2025-01-24 USDT ByBit case. The test will fail RED initially (the dedup logic does not exist yet) and pass GREEN after Task 6 wires the fix. The expected post-fix values are documented in the test docstring.

- [x] `TestByBitCase3Trace#derivatives_th_events_identified` - given the real TH fixture, expects the parser to identify 3 derivatives events on 2025-01-24 (Funding fee 0.088 USDT at 20:00, Futures fee 0.414 USDT at 23:40:53, Realized gain 40.755 USDT at 23:40:53) using the config-driven label set
- [x] `TestByBitCase3Trace#no_capital_entries_for_2025_01_24_after_dedup` - given the real CG/OGR/TH fixtures with `separate_derivatives_reporting=True`, expects `CryptoTaxReport.capital_entries` to contain NO entry with disposal_date=`2025-01-24` AND asset=USDT AND wallet=ByBit (all 3 derivatives CG lots removed)
- [x] `TestByBitCase3Trace#derivatives_entries_clean_for_2025_01_24` - given the same fixtures, expects `CryptoTaxReport.derivatives_entries` to contain the 3 OGR rows aggregated by `(date, asset, platform, event_type)` with `review_required=False` (no Ambiguous flag) and total pnl `-39.62` EUR
- [x] `TestByBitCase3Trace#removal_logged` - given the same fixtures, expects INFO-level per-lot removal logs plus a single WARNING summary with the disposal date, asset, wallet, amount, and matching TH Label
- [x] Run → expect RED: `uv run pytest tests/end_to_end/test_crypto_derivatives_separation.py::TestByBitCase3Trace -v` - fails because no dedup logic exists; the 3 CG lots are still in capital_entries
- [x] Commit: `test(e2e): capture Case 3 (2025-01-24 ByBit) characterization for derivatives CG dedup`

### Task 2: Add derivatives label config file and loader

Files:
- `docs/tax/derivatives_labels/koinly_2025.json` *(new)*
- `src/tax_reporting/application/crypto/derivatives_dedup.py` *(new)*
- `tests/unit/application/test_derivatives_dedup.py` *(new)*

This task creates the config file and the loader. The loader is pure: it reads JSON, validates the shape, and returns a frozenset of labels. It does not touch the pipeline yet.

- [x] `TestDerivativesLabelsConfig#loads_koinly_2025_labels` - given the file `docs/tax/derivatives_labels/koinly_2025.json` with `{"derivatives_th_labels": ["Funding fee", "Futures fee", "Realized gain"]}`, expects `_load_derivatives_labels_config(provider="koinly", year=2025)` to return `frozenset({"Funding fee", "Futures fee", "Realized gain"})`
- [x] `TestDerivativesLabelsConfig#missing_file_returns_empty_with_warning` - given no config file for `(provider, year)`, expects `_load_derivatives_labels_config` to return `frozenset()` and emit a `logger.warning` naming the missing file
- [x] `TestDerivativesLabelsConfig#malformed_json_raises` - given a config file with invalid JSON, expects `_load_derivatives_labels_config` to raise `FileProcessingError` with the file path and the parse error
- [x] `TestDerivativesLabelsConfig#missing_derivatives_th_labels_key_raises` - given a config file with valid JSON but no `derivatives_th_labels` key, expects `_load_derivatives_labels_config` to raise `FileProcessingError`
- [x] `TestDerivativesLabelsConfig#labels_value_wrong_type_raises` - given a config file where `derivatives_th_labels` is not a list of strings (e.g., a number or nested object), expects `_load_derivatives_labels_config` to raise `FileProcessingError`
- [x] `TestDerivativesLabelsConfig#rejects_symlink_config` - given a config file that is a symlink (security check matching the pattern in `classification.py:_load_popular_crypto_tokens` at lines 221-226: `if _POPULAR_CRYPTO_TOKENS_FILE.is_symlink(): raise FileProcessingError(...)`), expects `_load_derivatives_labels_config` to raise `FileProcessingError`
- [x] Run → expect RED: `uv run pytest tests/unit/application/test_derivatives_dedup.py::TestDerivativesLabelsConfig -v` - ImportError (module does not exist)
- [x] Create directory `docs/tax/derivatives_labels/` if it does not exist (`mkdir -p docs/tax/derivatives_labels`) and create `docs/tax/derivatives_labels/koinly_2025.json` with content `{"derivatives_th_labels": ["Funding fee", "Futures fee", "Realized gain"]}`
- [x] Implement `_load_derivatives_labels_config(provider: str, year: int) -> frozenset[str]` in `derivatives_dedup.py`. Reuse ONLY the security patterns from `classification.py:_load_popular_crypto_tokens` (symlink rejection at lines 221-226: `if _POPULAR_CRYPTO_TOKENS_FILE.is_symlink(): raise FileProcessingError(...)`; file size limit at lines 236-244). Do NOT reuse its exception handling for JSON parse errors: `_load_popular_crypto_tokens` catches `json.JSONDecodeError` at lines 282-289 and returns an empty frozenset (graceful degradation for a non-critical feature). For derivatives labels, a malformed config means the dedup silently skips, leaving double-counting in place - this is a correctness issue, so invalid JSON, missing `derivatives_th_labels` key, or wrong value type MUST raise `FileProcessingError` (import from `tax_reporting.domain.exceptions`) with the file path and the parse error. Only a MISSING file degrades gracefully (warning plus empty set, per Design Invariant 8). Import `_REPOSITORY_ROOT` from `classification.py` rather than redeclaring it; path resolution is `_REPOSITORY_ROOT / "docs" / "tax" / "derivatives_labels" / f"{provider}_{year}.json"`.
- [x] Run → expect GREEN: `uv run pytest tests/unit/application/test_derivatives_dedup.py::TestDerivativesLabelsConfig -v`
- [x] Commit: `feat(derivatives_dedup): add per-provider-per-year label config and loader`

### Task 3: Add `disposal_timestamp` field and thread through FIFO chain

Files:
- `src/tax_reporting/application/crypto/entities.py`
- `src/tax_reporting/domain/crypto_fifo.py`
- `src/tax_reporting/application/crypto_fifo/contexts.py`
- `src/tax_reporting/application/crypto_fifo/parsing.py`
- `src/tax_reporting/application/crypto_fifo/_emitters.py`
- `src/tax_reporting/application/crypto_fifo/matching.py`
- `src/tax_reporting/application/crypto/fifo_helpers.py`
- `src/tax_reporting/application/crypto_reporting.py`
- `tests/unit/application/test_derivatives_dedup.py`

This task adds the `disposal_timestamp` field (minute precision, optional, default None) to `CryptoCapitalGainEntry` and threads it through the FIFO chain so both CG-parser-derived and FIFO-derived entries carry the timestamp. The field is optional with default None to preserve backward compatibility for existing constructors and tests.

Verified constructor call sites (15 total): 6 `CryptoConsumption` constructors in `parsing.py` (lines 404, 422, 465, 488, 658, 688) plus 9 in `_emitters.py` (lines 73, 91, 129, 233, 251, 288, 353, 391, 425); 2 `CryptoFifoRealization` constructors in `matching.py` (lines 167, 281); 1 `CryptoCapitalGainEntry` constructor in `fifo_helpers.py` (line 328); 1 `CryptoCapitalGainEntry` constructor in `crypto_reporting.py` (line 474).

- [x] `TestDisposalTimestamp#crypto_capital_gain_entry_has_field` - given the `CryptoCapitalGainEntry` dataclass, expects a field named `disposal_timestamp` with default None (verified via `dataclasses.fields`)
- [x] `TestDisposalTimestamp#crypto_consumption_has_field` - given the `CryptoConsumption` dataclass, expects a field named `disposal_timestamp` with default None
- [x] `TestDisposalTimestamp#crypto_fifo_realization_has_field` - given the `CryptoFifoRealization` dataclass, expects a field named `disposal_timestamp` with default None
- [x] `TestDisposalTimestamp#parsed_tx_row_has_field` - given the `ParsedTxRow` dataclass, expects a field named `timestamp_str` with default None
- [x] `TestDisposalTimestamp#cg_parser_populates_timestamp` - given a CG row with `Date Sold` = `24/01/2025 23:40`, expects the resulting `CryptoCapitalGainEntry.disposal_timestamp` to equal `2025-01-24 23:40` and `disposal_date` to remain `2025-01-24` (day-level, unchanged for backward compatibility)
- [x] `TestDisposalTimestamp#fifo_parser_populates_timestamp` - given a TH row with `Date` = `2025-01-24 23:40:53 UTC`, expects the resulting `ParsedTxRow.timestamp_str` to equal `2025-01-24 23:40` (seconds truncated) and `date_str` to remain `2025-01-24` (day-level)
- [x] `TestDisposalTimestamp#fifo_chain_propagates_timestamp` - given a TH row feeding the FIFO engine, expects the resulting `CryptoCapitalGainEntry.disposal_timestamp` (via `CryptoConsumption` then `CryptoFifoRealization` then `fifo_helpers`) to equal the minute-precision timestamp from the TH Date
- [x] `TestDisposalTimestamp#fifo_emitters_propagate_timestamp` - given a cross-asset exchange TH row (routed through `_emitters.py`), expects the resulting `CryptoConsumption.disposal_timestamp` to equal the minute-precision timestamp from the TH Date (verifies all 9 `_emitters.py` constructor sites propagate the field)
- [x] `TestDisposalTimestamp#existing_constructors_backward_compat` - given existing code that constructs `CryptoCapitalGainEntry`, `CryptoConsumption`, or `CryptoFifoRealization` without passing `disposal_timestamp`, expects no error (default None applies) and all existing tests pass
- [x] Run → expect RED: `uv run pytest tests/unit/application/test_derivatives_dedup.py::TestDisposalTimestamp -v` - AttributeError (fields do not exist)
- [x] Add `disposal_timestamp: str | None = None` to `CryptoCapitalGainEntry` in `entities.py` AT THE END of the field list (after `ogr_validation`, the last field with a default). Do NOT insert it after `disposal_date`: that field is followed by 13 non-default fields (`acquisition_date`, `asset`, `amount`, `cost_eur`, `proceeds_eur`, `gain_loss_eur`, `holding_period`, `wallet`, `platform`, `chain`, `operator_origin`, `annex_hint`, `review_required`, `notes`), and inserting a default field before them raises `TypeError: non-default argument follows default argument` at class definition time, breaking every constructor call and every test fixture. The field is optional with default None; the `__post_init__` validator is unchanged (no new validation for None). Same placement rule as `CryptoConsumption` and `CryptoFifoRealization` below: fields with defaults must follow fields without defaults.
- [x] Add `disposal_timestamp: str | None = None` to `CryptoConsumption` and `CryptoFifoRealization` in `domain/crypto_fifo.py`. Both are optional with default None; add at the END of each dataclass field list (after the existing `review_reason` / last field) to avoid disrupting existing positional argument patterns and to satisfy the Python dataclass rule that fields with defaults must follow fields without defaults.
- [x] Add `timestamp_str: str | None = None` to `ParsedTxRow` in `contexts.py` at the END of the field list (field 19, after all 18 existing fields without defaults). Do NOT insert between existing fields: `ParsedTxRow` has 18 non-default fields, and inserting a default field before them would violate the Python dataclass rule.
- [x] In `parsing.py` line 184 region, capture the datetime before `format_datetime` strips it. The existing code at line 177-184 already parses the date inside a `try ... except ValueError` block. Reuse the already-parsed datetime object (`parse_koinly_datetime` result) to compute both `date_str` and `timestamp_str` in the same try-block; do NOT re-parse or re-invoke `parse_koinly_datetime` outside the block (a malformed date would raise an uncaught ValueError). The code shape is:
  ```python
  # Inside the existing try block at line 177-184:
  date_raw = parsed_row.row.get("Date", "").strip()
  parsed_dt = parse_koinly_datetime(date_raw)
  date_str = format_datetime(parsed_dt)
  timestamp_str = parsed_dt.strftime("%Y-%m-%d %H:%M")
  ```
  Then pass `timestamp_str=timestamp_str` to the `ParsedTxRow` constructor at line 216.
- [x] In `parsing.py`, pass `disposal_timestamp=parsed_row.timestamp_str` to all 6 `CryptoConsumption` constructor call sites (lines 404, 422, 465, 488, 658, 688). Each currently takes `date=parsed_row.date_str`; add the timestamp alongside. Lines 532 and 593 are `CryptoAcquisition` constructors, NOT `CryptoConsumption` - do NOT add `disposal_timestamp` there (acquisitions do not have a disposal timestamp).
- [x] In `_emitters.py`, pass `disposal_timestamp=<source timestamp>` to all 9 `CryptoConsumption` constructor call sites (lines 73, 91, 129, 233, 251, 288, 353, 391, 425). Each constructor currently takes a `date=` argument from a `ParsedTxRow` or derived value; add `disposal_timestamp=` from the same source's `timestamp_str` field. If the source is a `ParsedTxRow`, use `parsed_row.timestamp_str`; if derived, propagate from the originating parsed row.
- [x] In `matching.py`, pass `disposal_timestamp=con.con.disposal_timestamp` to both `CryptoFifoRealization` constructor call sites (lines 167 and 281). Each currently takes `disposal_date=con.con.date`; add the timestamp alongside.
- [x] In `fifo_helpers.py` line 328, pass `disposal_timestamp=r.disposal_timestamp` to the `CryptoCapitalGainEntry` constructor.
- [x] In `crypto_reporting.py` line 398 region, capture the datetime before `format_datetime`. The existing code is inside a `try ... except ValueError` block (line 393-403). Compute `disposal_timestamp` from the same `parse_koinly_datetime` result:
  ```python
  # Inside the existing try block at line 393-403:
  parsed_dt = parse_koinly_datetime(row.get("Date Sold", ""))
  disposal_date = format_datetime(parsed_dt)
  disposal_timestamp = parsed_dt.strftime("%Y-%m-%d %H:%M")
  ```
  Then pass `disposal_timestamp=disposal_timestamp` to the `CryptoCapitalGainEntry` constructor at line 474.
- [x] Run → expect GREEN: `uv run pytest tests/unit/application/test_derivatives_dedup.py::TestDisposalTimestamp -v`
- [x] Run → expect GREEN (backward compat): `uv run pytest` (full suite; no existing tests should break)
- [x] Commit: `feat(crypto): add disposal_timestamp field (minute precision) to CryptoCapitalGainEntry and FIFO chain`

### Task 4: Implement TH derivatives event scanner with timestamp

Files:
- `src/tax_reporting/application/crypto/derivatives_dedup.py`
- `tests/unit/application/test_derivatives_dedup.py`

This task adds a function that scans a TH CSV file and returns a list of derivatives events (one per `crypto_withdrawal` row whose Label is in the configured set). Each event carries a minute-precision timestamp for matching.

- [x] `TestDerivativesThScanner#finds_funding_fee_event_with_timestamp` - given a TH CSV row `2025-01-24 20:00:00 UTC,crypto_withdrawal,Funding fee,ByBit,"0,08838575",USDT,...` and labels `{"Funding fee", "Futures fee", "Realized gain"}`, expects the scanner to return one event with `timestamp="2025-01-24 20:00"`, `asset="USDT"`, `wallet="ByBit"`, `amount=Decimal("0.08838575")`, `label="Funding fee"`
- [x] `TestDerivativesThScanner#truncates_seconds_from_timestamp` - given a TH CSV row `2025-01-24 23:40:53 UTC,crypto_withdrawal,Realized gain,...`, expects the event's `timestamp` to equal `2025-01-24 23:40` (seconds truncated to minute precision for CG matching)
- [x] `TestDerivativesThScanner#ignores_non_withdrawal_type` - given a TH CSV row `2025-01-24 00:15:03 UTC,crypto_deposit,Funding fee,ByBit,...` with Label=`Funding fee` (in set) but Type=`crypto_deposit`, expects the scanner to return zero events (Type filter rejects the deposit even though Label matches)
- [x] `TestDerivativesThScanner#ignores_non_derivatives_labels` - given a TH CSV row `2025-01-13 03:45:30 UTC,exchange,"",ByBit,...` (an exchange row with empty Label), expects the scanner to return zero events
- [x] `TestDerivativesThScanner#ignores_reward_label` - given a TH CSV row `2025-01-24 00:15:03 UTC,crypto_withdrawal,Reward,ByBit,...` with Type=`crypto_withdrawal` but Label=`Reward` (not in derivatives set), expects the scanner to return zero events
- [x] `TestDerivativesThScanner#multiple_events_at_same_timestamp` - given two TH rows at `2025-01-24 23:40:53 UTC` with different Labels (`Futures fee` 0.414 USDT and `Realized gain` 40.755 USDT), expects the scanner to return two distinct events at timestamp `2025-01-24 23:40` distinguished by amount
- [x] `TestDerivativesThScanner#multiple_events_at_same_timestamp_same_amount` - given two TH rows at `2025-01-24 08:00:00 UTC` both with Label `Funding fee` and amount 0.5 USDT (two positions, same funding period), expects the scanner to return two events with identical `(timestamp, asset, wallet, amount)` keys; the downstream matcher handles the collision deterministically
- [x] `TestDerivativesThScanner#empty_label_set_returns_empty` - given labels=`frozenset()` (e.g., missing config degraded), expects the scanner to return zero events without raising
- [x] Run → expect RED: `uv run pytest tests/unit/application/test_derivatives_dedup.py::TestDerivativesThScanner -v`
- [x] Implement `find_derivatives_th_events(transaction_history_path: Path, labels: frozenset[str]) -> list[DerivativesThEvent]` in `derivatives_dedup.py`. Define `DerivativesThEvent` as a frozen dataclass with fields `timestamp: str` (minute precision `%Y-%m-%d %H:%M`, computed via `parse_koinly_datetime(row["Date"]).strftime("%Y-%m-%d %H:%M")` to truncate seconds), `asset: str` (normalized via `normalize_asset_ticker`), `wallet: str` (normalized via `normalize_platform_name`), `amount: Decimal` (parsed via `parse_koinly_decimal`), `label: str` (the raw Label string from the TH row). Do NOT add a `date` field: no downstream caller uses it (the matcher uses only `(timestamp, asset, wallet, amount)`, the logger uses `timestamp` and `label`, and the OGR classifier already has its own day-level date from OGR row parsing). Filter: only `crypto_withdrawal` rows whose Label (case-sensitive, exact match) is in `labels`. **Parse the TH CSV with `read_koinly_rows(transaction_history_path)` from `tax_reporting.infrastructure.koinly_parser`** (not raw `csv.DictReader`): the TH CSV has a multi-line preamble (line 1 = `Transaction report 2025`, line 2 = blank, line 3 = header, line 4+ = data) that `read_koinly_rows` handles via `_detect_header_index`; a naive reader would treat line 1 as the header.
- [x] Run → expect GREEN: `uv run pytest tests/unit/application/test_derivatives_dedup.py::TestDerivativesThScanner -v`
- [x] Commit: `feat(derivatives_dedup): scan TH for derivatives events with minute-precision timestamp`

### Task 5: Implement CG lot removal with two-phase matching (exact plus contiguous-range fallback)

Files:
- `src/tax_reporting/application/crypto/derivatives_dedup.py`
- `tests/unit/application/test_derivatives_dedup.py`

This task adds the function that filters `capital_entries`. Phase 1 is exact match on `(timestamp, asset, wallet, amount_6dp)`. Phase 2 is contiguous-range fallback for unmatched TH events: sliding window over unmatched CG lots at the same `(timestamp, asset, wallet)` sorted by acquisition_date, tolerance `Decimal("0.00001") * range_size`.

- [x] `TestRemoveDerivativesFlaggedLots#exact_match_removes_single_cg_lot` - given capital_entries with one lot at `(2025-01-24 20:00, USDT, ByBit, amount=0.08838575)` and derivatives_events with `(2025-01-24 20:00, USDT, ByBit, amount=0.08838575, label=Funding fee)`, expects the lot to be removed (exact match), count=1, match_type="exact"
- [x] `TestRemoveDerivativesFlaggedLots#keeps_non_matching_cg_lot` - given capital_entries with one lot at `(2025-01-13 03:45, USDT, ByBit, amount=108.335)` (spot exchange, no derivatives event) and a derivatives_events list that does not contain this key, expects the lot to be retained
- [x] `TestRemoveDerivativesFlaggedLots#amount_rounding_to_6_decimals_absorbs_koinly_drift` - given a CG lot with amount=0.08838575 and a derivatives_event with amount=0.08838580 (delta in 8th decimal), expects the lot to be removed (both round to 0.088386 at 6 decimals, exact match succeeds)
- [x] `TestRemoveDerivativesFlaggedLots#contiguous_range_fallback_removes_fifo_split_lots` - given a derivatives_event at `(2025-01-24 23:40, USDT, ByBit, amount=120.0)` and CG lots at the same `(timestamp, asset, wallet)` with amounts `[70.0, 50.0]` (contiguous in acquisition_date, no single lot matches 120.0), expects the contiguous-range fallback to find range {70.0, 50.0} (sum=120.0, within tolerance) and remove both lots; count=2, match_type="range"
- [x] `TestRemoveDerivativesFlaggedLots#contiguous_range_fallback_prefers_first_range` - given a derivatives_event at amount=70.0 and CG lots `[70.0, 50.0, 20.0]` (sorted by acquisition_date), expects the exact match phase to remove the single 70.0 lot before the contiguous-range fallback runs
- [x] `TestRemoveDerivativesFlaggedLots#range_tolerance_absorbs_rounding_accumulation` - given a derivatives_event at amount=100.0 and CG lots `[33.333333, 33.333333, 33.333334]` (sum=99.999999, delta=0.000001 within tolerance for range_size=3: tolerance = 0.00001 * 3 = 0.00003), expects all 3 lots removed
- [x] `TestRemoveDerivativesFlaggedLots#range_mismatch_keeps_lots` - given a derivatives_event at amount=100.0 and CG lots `[70.0, 50.0]` (sum=120.0, not within tolerance of 100.0), expects no lots removed and the event marked unmatched (falls to Ambiguous classifier)
- [x] `TestRemoveDerivativesFlaggedLots#non_contiguous_lots_do_not_match` - given a derivatives_event at amount=120.0 and CG lots sorted by acquisition_date as `[70.0, 30.0, 50.0]` where lots 70.0 and 50.0 are NOT adjacent (30.0 sits between them), expects NO match (contiguous constraint: the range [70.0, 30.0, 50.0] sums to 150.0, not 120.0; the sub-range [70.0, 30.0] sums to 100.0, not 120.0; the sub-range [30.0, 50.0] sums to 80.0, not 120.0); the event is marked unmatched. This is the critical test that prevents false-positive matches on coincidental non-contiguous subsets (addresses the <REALIZED_GAIN_USDT> USDT Realized-gain case in Case 2).
- [x] `TestRemoveDerivativesFlaggedLots#multiple_th_events_at_same_timestamp_consumed_in_order` - given 2 derivatives_events at `(2025-01-24 08:00, USDT, ByBit, amount=0.5)` and 2 CG lots at the same key, expects both events to consume one lot each (deterministic deque order by acquisition_date), count=2, and the summary WARNING's "surplus lots" section to be empty (no collision)
- [x] `TestRemoveDerivativesFlaggedLots#empty_deque_falls_to_range_fallback` - given a derivatives_event at amount=0.5 whose exact-match key deque is empty (drained by prior events), expects the event to fall through to the contiguous-range fallback; if the fallback also finds no match, the event is marked unmatched
- [x] `TestRemoveDerivativesFlaggedLots#exact_match_collision_aggregated_in_summary` - given 1 derivatives_event at amount=0.5 and 3 CG lots at `(2025-01-24 08:00, USDT, ByBit, 0.5)`, expects 1 lot removed (exact match, first in deque), 2 lots remaining, and the summary WARNING to include a "surplus lots" section naming the count (2), total amount (1.0 USDT), and sample of up to 3 `(timestamp, asset, wallet, amount)` tuples. No per-lot WARNING is emitted.
- [x] `TestRemoveDerivativesFlaggedLots#per_lot_removal_logged_at_info` - given a removal scenario, expects each removed lot to log at INFO level (not WARNING) with timestamp, asset, wallet, amount, match type, and matching TH Label (use `caplog` at INFO level)
- [x] `TestRemoveDerivativesFlaggedLots#summary_logged_at_warning_once` - given a removal scenario removing N lots, expects exactly one WARNING log summarizing: (a) removals (total count, exact count, range count, aggregate proceeds, aggregate gain removed); (b) surplus lots (count, total amount, sample of up to 3 keys) - empty if none; (c) malformed-input lots (count, sample of up to 3 `(timestamp, asset, amount)` tuples) - empty if none. The summary is the ONLY WARNING emitted by the function.
- [x] `TestRemoveDerivativesFlaggedLots#malformed_input_lots_aggregated_in_summary` - given 2 CG lots with amount <= 0 (e.g., 0 and -0.5), expects both to be skipped from matching, collected into the summary WARNING's "malformed-input lots" section (count=2, sample includes both `(timestamp, asset, amount)` tuples), and no per-lot WARNING emitted
- [x] `TestRemoveDerivativesFlaggedLots#range_match_does_not_trigger_collision_warning` - given 1 derivatives_event at amount=120.0 and 2 contiguous CG lots at amounts [70.0, 50.0] (range-matched, not exact-matched), expects the summary WARNING's "surplus lots" section to be empty (the warning is reserved for same-key exact-match collisions only)
- [x] `TestRemoveDerivativesFlaggedLots#empty_derivatives_events_returns_input_unchanged` - given capital_entries and an empty derivatives_events list, expects the function to return the input list unchanged with count 0 and no summary WARNING
- [x] `TestRemoveDerivativesFlaggedLots#performance_at_scale` - given 10,000 CG lots (9,000 non-derivatives at 100 distinct timestamps with 90 lots each, 1,000 derivatives-flagged across 100 timestamps with 10 lots each) and 1,000 derivatives_events, expects the function to complete in under 2 seconds. This exercises the worst case for the contiguous-range fallback: up to 90 candidate lots per unmatched event at a given timestamp (the sliding window is O(N) per event, so 90-window scans are fast).
- [x] `TestRemoveDerivativesFlaggedLots#performance_worst_case_single_event_many_lots` - given 1 derivatives_event and 500 CG lots at the same `(timestamp, asset, wallet)` (none matching exactly, contiguous-range fallback must scan all 500), expects the function to complete in under 500 milliseconds (O(N) sliding window, not exponential)
- [x] Run → expect RED: `uv run pytest tests/unit/application/test_derivatives_dedup.py::TestRemoveDerivativesFlaggedLots -v`
- [x] Implement `remove_derivatives_flagged_lots(capital_entries: list[CryptoCapitalGainEntry], derivatives_events: list[DerivativesThEvent]) -> tuple[list[CryptoCapitalGainEntry], int]` in `derivatives_dedup.py`. Algorithm:
  1. Sort CG lots by `(timestamp, asset, wallet, acquisition_date, row_index)` for determinism. Skip entries with `disposal_timestamp is None` (entries without a timestamp cannot be matched) AND skip entries with `amount <= 0` (zero-amount or negative-amount CG lots are not valid disposal quantities and would stall the sliding window shrink condition). Collect skipped zero-amount lots into a `malformed_input_lots` list for inclusion in the summary WARNING in step 8; do NOT emit a per-lot WARNING (at the user's scale, per-lot data-quality WARNINGs would flood the log - see Design Invariant 15). Both filters run in step 1 before any matching begins.
  2. Sort derivatives_events by `(timestamp, asset, wallet, amount)`.
  3. Build a dict from `(timestamp, asset, wallet, amount_6dp)` to a deque of CG lots (ordered by acquisition_date for deterministic consumption).
  4. Track matched lots in a set (by index in the original list).
  5. **Phase 1 (exact match):** for each derivatives_event, if the deque at the event's key is non-empty, pop the first lot and mark it matched (match_type="exact"). If the deque is empty, leave the event unmatched for phase 2. Track per-key surplus (lots remaining after all events at that key consumed theirs).
  6. **Phase 2 (contiguous-range fallback):** for each unmatched derivatives_event, get the list of unmatched CG lots at the same `(timestamp, asset, wallet)` sorted by acquisition_date. Run a sliding window: expand the right pointer while the running sum is below target minus tolerance; check if the running sum is within tolerance `Decimal("0.00001") * range_size` (where `range_size` equals the current window length; the term matches Design Invariant 12 and the Terms section); shrink the left pointer while the running sum exceeds target plus tolerance. If a matching window is found, mark all lots in the range as matched (match_type="range") and record the range. If no window matches, mark the event unmatched (falls to Ambiguous).
  7. After both phases, check each exact-match key's deque for surplus lots (lots remaining after all events at that key consumed theirs). Collect surplus lots into a `surplus_lots` list for inclusion in the summary WARNING in step 8; do NOT emit a per-lot WARNING (see Design Invariant 15: at scale, per-lot collision WARNINGs would train the user to ignore the warning level). Each surplus lot is still logged at INFO for audit traceability.
  8. Log each matched lot at INFO (match_type, timestamp, asset, wallet, amount, TH Label). Emit exactly one WARNING summary at the end covering all signal types: (a) removals - total count, exact count, range count, aggregate proceeds, aggregate gain removed; (b) surplus lots - count, total amount, sample of up to 3 `(timestamp, asset, wallet, amount)` tuples; (c) malformed-input lots - count, sample of up to 3 `(timestamp, asset, amount)` tuples. If any of (b) or (c) is non-empty, the summary names the condition and suggests the user action ("surplus lots may indicate a missed FIFO split - review the listed keys; malformed-input lots have non-positive amounts - investigate the source export").
  9. Return the filtered list (unmatched lots only) and the removed count.
- [x] Run → expect GREEN: `uv run pytest tests/unit/application/test_derivatives_dedup.py::TestRemoveDerivativesFlaggedLots -v`
- [x] Commit: `feat(derivatives_dedup): two-phase CG lot removal with timestamp matching and contiguous-range fallback`

### Task 6: Wire pipeline integration in `crypto_reporting.py`

Files:
- `src/tax_reporting/application/crypto_reporting.py`
- `tests/end_to_end/test_crypto_derivatives_separation.py`

This task wires the functions from Tasks 2, 4, and 5 into the pipeline at the integration point between validation and OGR split. The dedup runs only when `separate_derivatives_reporting=True`. Task 1 already established the RED state (the `TestByBitCase3Trace` test was committed as RED in Task 1); this task flips it GREEN by landing the wiring. No new RED gate here.

- [x]`TestPipelineIntegration#dedup_runs_after_validation_before_split` - given a fixture with a derivatives CG lot and a `separate_derivatives_reporting=True` config, expects the dedup to run AFTER `_validate_capital_entries_have_valid_countries` (so validated entries are filtered) and BEFORE `_split_ogr_index` (so the classifier sees the filtered list)
- [x]`TestPipelineIntegration#dedup_skipped_when_flag_false` - given `separate_derivatives_reporting=False`, expects the dedup to be a no-op (capital_entries unchanged; backward-compatible byte-identical output)
- [x]`TestPipelineIntegration#dedup_skipped_when_th_missing` - given `separate_derivatives_reporting=True` but no TH file path provided, expects the pipeline to skip the dedup with a `logger.warning` naming the missing TH file
- [x]`TestPipelineIntegration#dedup_skipped_when_config_missing` - given `separate_derivatives_reporting=True`, a valid TH file, but no `koinly_<year>.json` config file, expects the pipeline to skip the dedup with a `logger.warning` (from Task 2's missing-config warning) and continue with current behavior
- [x]`TestPipelineIntegration#ogr_classifies_clean_after_dedup` - given the user's 2025-01-24 case, expects the 3 OGR rows to classify as `Derivatives` (not `Ambiguous`) after their CG counterparts are removed, producing `derivatives_entries` with `review_required=False`
- [x]In `load_koinly_crypto_report`, insert a SINGLE-LINE call between line 200 (`_validate_capital_entries_have_valid_countries`) and line 209 (the `derivatives_entries` initialization):
  ```python
  capital_entries = apply_derivatives_dedup(
      capital_entries=capital_entries,
      jurisdiction=jurisdiction,
      transaction_history_file=transaction_history_file,
      year=year,
  )
  ```
  The `apply_derivatives_dedup` function lives in `derivatives_dedup.py` and encapsulates the full gate-check-config-scan-filter sequence. This keeps `crypto_reporting.py` (already 753 lines, 50 percent over the CLAUDE.md ~500-line orchestration threshold) from absorbing more orchestration logic - see Design Invariant 16. The function signature is `apply_derivatives_dedup(capital_entries: list[CryptoCapitalGainEntry], jurisdiction: TaxJurisdictionConfig, transaction_history_file: Path | None, year: int) -> list[CryptoCapitalGainEntry]`; it returns the filtered list (or the input unchanged if any gate fails). The `year` variable is already in scope at the insertion point (bound by `_extract_tax_year` near the top of `load_koinly_crypto_report`, line approximately 130); reuse it, do not rebind or shadow.
- [x]Implement `apply_derivatives_dedup()` in `derivatives_dedup.py`. The body encapsulates:
  ```python
  def apply_derivatives_dedup(*, capital_entries, jurisdiction, transaction_history_file, year):
      if not (
          jurisdiction.separate_derivatives_reporting
          and jurisdiction.use_other_gains_report
          and transaction_history_file
      ):
          return capital_entries  # gate failed: no-op (Design Invariant 14)
      labels = _load_derivatives_labels_config(provider="koinly", year=year)
      if not labels:
          logging.getLogger(__name__).warning(
              "Derivatives TH-label config missing for koinly year %d; CG dedup skipped. "
              "Add docs/tax/derivatives_labels/koinly_%d.json to enable.",
              year, year,
          )
          return capital_entries
      derivatives_events = find_derivatives_th_events(transaction_history_file, labels)
      if not derivatives_events:
          return capital_entries
      filtered, _removed_count = remove_derivatives_flagged_lots(capital_entries, derivatives_events)
      return filtered
  ```
  All WARNING and INFO logging happens inside `remove_derivatives_flagged_lots` (Task 5); `apply_derivatives_dedup` emits only the missing-config WARNING (1x per run, non-aggregatable because it has a single remediation action: add the config file).
- [x]Run the Task 1 characterization test → expect GREEN (the test that was RED in Task 1 now passes)
- [x]Run the predecessor characterization tests (`TestOgrCharacterizationGolden`) with `separate_derivatives_reporting=False` to confirm byte-identical output
- [x]Run → expect GREEN: `uv run pytest tests/end_to_end/test_crypto_derivatives_separation.py -v`
- [x]Commit: `feat(crypto_reporting): wire derivatives TH-label CG dedup into pipeline (gated on DP-012)`

### Task 7: Update Case 1 and Case 2 e2e expectations; verify spot trades preserved

Files:
- `tests/end_to_end/test_crypto_derivatives_separation.py`

This task updates two existing test classes after the dedup ships.

**Case 1 (`TestByBitCase1Trace`)**: Verified against the fixtures:
- TH line 204 (`<PROFIT_TIMESTAMP>,crypto_deposit,Realized gain,...,<PROFIT_USDT>,USDT,140,18,...`) is a **`crypto_deposit`** with Label=`Realized gain`. The Task 4 scanner filters to `crypto_withdrawal` only, so this row is never matched. The plus <PROFIT_EUR> EUR Profit OGR row at OGR line 8 (sourced from TH line 204) is therefore UNCHANGED by the dedup: it still routes to `derivatives_entries` as before.
- TH line 205 (`<PROFIT_TIMESTAMP>,crypto_withdrawal,Futures fee,...,<FEE_PROCEEDS_USDT>,USDT,...,<FEE_GAIN_EUR>,<FEE_PROCEEDS_EUR>,...`) is a **`crypto_withdrawal`** with Label=`Futures fee`. The Task 4 scanner matches this row. Its CG counterpart at CG line 19 (amount <FEE_PROCEEDS_USDT>, proceeds <FEE_PROCEEDS_EUR>, gain <FEE_GAIN_EUR>) is removed. With `cg_matches == 0` for the minus <FEE_PROCEEDS_EUR> EUR Loss OGR row at OGR line 9, the classifier (`classify_derivatives_event` at `classification.py:506-509`) now returns `Derivatives("OGR Loss with no CG counterpart - derivatives realization")` instead of the old Spot classification.

The existing tests need updating:
- `test_profit_in_derivatives_sheet` (lines 114-161): the plus <PROFIT_EUR> Profit assertion (line 133) still holds; the `cg_matches` assertion (line 144 `assert cg_matches`) and `cg_magnitude == Decimal("<FEE_GAIN_EUR>")` assertion (line 156) BOTH break because the <FEE_GAIN_EUR> lot was removed. Drop these two assertions and keep the Profit routing assertion.
- `test_fee_disposal_in_spot_index` (lines 180-199): asserts `not loss_derivatives` (line 195). After dedup, the minus <FEE_PROCEEDS_EUR> Loss reclassifies as Derivatives, so `loss_derivatives` becomes non-empty and the assertion fails. Replace this test with `test_fee_disposal_reclassifies_to_derivatives` asserting the inverse: `loss_derivatives` IS non-empty with total pnl equal to minus <FEE_PROCEEDS_EUR> EUR (or whatever the new aggregate value is).

Also: update class docstrings referencing approximately 109 CG lots to approximately 108 for precision.

**Case 2 (`TestByBitCase2Trace`)**: Verified - 2 of the approximately 108 CG lots for 2025-01-13 USDT ByBit are removed by the dedup (Funding fee <FUNDING_FEE_USDT> USDT at CG line 21, Futures fee <FUTURES_FEE_USDT> USDT at CG line 131). The <REALIZED_GAIN_USDT> Realized gain has NO CG counterpart (the amount is absent from the CG report; the existing classifier already routes the OGR row to clean Derivatives without dedup intervention). The new Crypto Gains aggregate is computed by the implementation; the test asserts the new value with a comment explaining the delta.

- [x]`TestByBitCase1Trace#test_profit_in_derivatives_sheet` (UPDATE, not replace) - drop the `assert cg_matches` and `cg_magnitude == Decimal("<FEE_GAIN_EUR>")` assertions; keep the plus <PROFIT_EUR> Profit routing assertion (`profit_total == Decimal("<PROFIT_EUR>")`). Docstring updates: "<FEE_GAIN_EUR> EUR fee-disposal lot stays in Crypto Gains" to "<FEE_GAIN_EUR> EUR fee-disposal lot is removed by the dedup (was Spot, now reclassifies to Derivatives)".
- [x]`TestByBitCase1Trace#test_fee_disposal_reclassifies_to_derivatives` (NEW, replaces `test_fee_disposal_in_spot_index`) - given Case 1 fixtures with `separate_derivatives_reporting=True`, expects `derivatives_entries` to contain a LOSS entry for `_CASE1_DATE` with total pnl `<-FEE_PROCEEDS_EUR>` EUR (the Futures fee OGR row reclassified from Spot to Derivatives because its CG counterpart was removed).
- [x]`TestByBitCase1Trace#test_no_fee_disposal_lot_in_capital_entries` (NEW) - given Case 1 fixtures with `separate_derivatives_reporting=True`, expects `capital_entries` to contain NO entry with disposal_date=`2025-01-12` AND asset=USDT AND wallet=ByBit (the <FEE_GAIN_EUR> EUR Futures fee CG lot was removed by the dedup).
- [x]`TestByBitCase1Trace#test_no_derivatives_value_in_capital_entries` (UNCHANGED) - the legacy <MIXED_AGGREGATE_EUR> EUR mixed value assertion still holds; the dedup does not introduce it. Inherited unchanged from the predecessor plan.
- [x]`TestByBitCase2Trace#lots_remain_positive_for_spot_only` - given Case 2 fixtures with `separate_derivatives_reporting=True`, expects the remaining CG lots (after derivatives-flagged lots are removed) to retain their original positive gain values; the new aggregate gain is asserted to equal the COMPUTED value (read it from the implementation after Task 6 lands)
- [x]`TestByBitCase2Trace#derivatives_lots_removed` - given Case 2 fixtures, expects exactly 2 CG lots to be removed (the Funding fee <FUNDING_FEE_USDT> USDT and Futures fee <FUTURES_FEE_USDT> USDT disposals on 2025-01-13). The <REALIZED_GAIN_USDT> Realized gain has no CG counterpart (the amount is absent from the CG report; the existing classifier already routes the OGR row to clean Derivatives without dedup intervention).
- [x]`TestByBitCase2Trace#derivatives_total_matches_ogr_net` - given Case 2 fixtures, expects the sum of `derivatives_entries.pnl_eur` to still equal `<-OGR_NET_EUR> EUR` (unchanged from predecessor plan; the OGR rows still route to derivatives_entries, now classified as clean Derivatives instead of Ambiguous). This assertion holds because the OGR rows route to Derivatives regardless of whether the <REALIZED_GAIN_USDT> USDT Realized-gain CG lots are removed: the <REALIZED_GAIN_USDT> amount does not appear as an exact match in the CG report, and the contiguous-range fallback does NOT find a contiguous range of the 108 CG lots at `(<LOSS_TIMESTAMP>, USDT, ByBit)` summing to <REALIZED_GAIN_USDT> (verified by brute-force sliding-window scan of the fixture: total sum of all 108 lots is <TOTAL_USDT> USDT, max single lot is 89.63 USDT, and no contiguous sub-range sums to <REALIZED_GAIN_USDT> within tolerance). The `non_contiguous_lots_do_not_match` unit test in Task 5 verifies the contiguous constraint works in general (non-contiguous subsets do not match); it does NOT verify that <REALIZED_GAIN_USDT> specifically has no CONTIGUOUS range. If a future Koinly export changes the lot distribution such that a contiguous range does sum to <REALIZED_GAIN_USDT> within tolerance, this assertion still holds (OGR routing is independent), but the Crypto Gains aggregate WILL change. Owner: this plan's implementer verifies after Task 6 lands by (a) re-running the brute-force scan on the then-current fixture to confirm no contiguous range sums to <REALIZED_GAIN_USDT>, and (b) re-reading the actual Crypto Gains aggregate and asserting it against the computed value (not just "the new value").
- [x]`TestByBitCase2Trace#spot_exchange_lots_preserved` - given Case 2 fixtures, expects the CG lots from the 2025-01-13 USDT to SUI and USDT to CARV exchanges (TH Label empty or "Exchange", not in derivatives set) to remain in capital_entries unchanged
- [x]Update `TestByBitCase2Trace` class docstring from "approximately 109 CG lots" to "approximately 108 CG lots at the 13:01 timestamp" for precision (verified via `grep -c "<LOSS_TIMESTAMP>" koinly_2025_capital_gains_report_<ACCOUNT_TOKEN>.csv` = 108).
- [x]`TestBackwardCompatTrace#flag_off_matches_golden_values` - given Case 2 fixtures with `separate_derivatives_reporting=False`, expects the Task 1 predecessor golden values (Case 2: -<CG_LOTS_EUR> EUR in Crypto Gains; Case 1: <MIXED_AGGREGATE_EUR> EUR) to reproduce exactly. NO CHANGE to this test from the predecessor plan.
- [x]Note on test method naming: the `#` separator in this plan denotes the test class to method relationship, not literal Python syntax. Translate to the existing `test_<descriptor>` convention used elsewhere in this file when implementing.
- [x]Run → expect GREEN for the backward-compat test; expect Case 2 with flag=True to assert the NEW aggregate value (re-read it from the actual pipeline output after Task 6)
- [x]Commit: `test(e2e): update Case 1 (fee disposal reclassifies to Derivatives) and Case 2 (2 lots removed) expectations after derivatives CG dedup`

### Task 8: Update domain documentation

Files:
- `docs/domain/crypto_implementation_guidelines.md`

Document the TH-label-driven dedup logic, timestamp matching, contiguous-range fallback, and the per-provider-per-year config convention. Do not add a new rule to `crypto_rules.md` (PT-C-034 still governs the legal classification); this is an implementation guideline only.

- [x]Add a section to `crypto_implementation_guidelines.md` titled "Derivatives CG Dedup via TH Labels" documenting: (a) why TH labels are needed in addition to the OGR classifier (Koinly double-reports derivatives disposals in both OGR and CG), (b) the per-provider-per-year config convention under `docs/tax/derivatives_labels/`, (c) the match key `(timestamp, asset, wallet, amount)` with minute-precision timestamp and the two-phase matching (exact plus contiguous-range fallback), (d) the 6-decimal rounding for exact match and the `Decimal("0.00001") * range_size` tolerance for contiguous-range match, plus why contiguous-range (not subset-sum) is used (FIFO semantics, false-positive avoidance), (e) the logging approach (per-lot INFO for removals; single aggregate WARNING summary covering removals, surplus lots, and malformed-input lots; NO per-lot WARNINGs - see Design Invariant 15), (f) the graceful-degradation behavior when the config is missing, (g) the orchestration thinness rule (dedup wiring lives in `derivatives_dedup.apply_derivatives_dedup()`, not in `crypto_reporting.py` - see Design Invariant 16), (h) the legal characterization inline (derivatives dispose under CIRS art. 10(1)(e); cryptoassets under art. 10(1)(k); the dedup exists to prevent the same disposal being taxed under both articles) - inline the relevant statement rather than cross-referencing PT-C-034 or the predecessor plan by path, per this repo's document self-containment convention
- [x]Commit: `docs(domain): document derivatives CG dedup logic, timestamp matching, and contiguous-range fallback`

### Task 9: Final validation and lint

- [x]Run Tier 1 validation commands (must all pass)
- [x]Run Tier 2 full regression: `uv run pytest` (no marker filter, per Finding 6 of the predecessor's post-archive review)
- [x]Run ruff: `uv run ruff check src tests` clean (no new errors beyond pre-existing baseline)
- [x]Manual Excel check: run the pipeline against the user's real data and verify (a) 2025-01-24 USDT ByBit appears ONLY in Derivatives P&L with review=NO, (b) Crypto Gains no longer shows 2025-01-24 USDT ByBit, (c) other spot activity (e.g., 2025-01-13 USDT to SUI exchange) still appears in Crypto Gains, (d) the log shows exactly one WARNING summary for the dedup covering removals, surplus lots, and malformed-input lots in one aggregate line (no per-lot WARNINGs)
- [x]Verify config file present and well-formed: `test -f docs/tax/derivatives_labels/koinly_2025.json && python -c "import json; json.load(open('docs/tax/derivatives_labels/koinly_2025.json'))"`
- [x]Verify disposal_timestamp field exists on CryptoCapitalGainEntry and FIFO chain types: `python -c "from tax_reporting.application.crypto.entities import CryptoCapitalGainEntry; from tax_reporting.domain.crypto_fifo import CryptoConsumption, CryptoFifoRealization; from tax_reporting.application.crypto_fifo.contexts import ParsedTxRow; import dataclasses; assert all('disposal_timestamp' in {f.name for f in dataclasses.fields(c)} for c in [CryptoCapitalGainEntry, CryptoConsumption, CryptoFifoRealization]); assert 'timestamp_str' in {f.name for f in dataclasses.fields(ParsedTxRow)}"`
- [x]Verify no hardcoded derivatives labels in production code: `grep -rE "Funding fee|Futures fee|Realized gain" src/tax_reporting/ | grep -v test_ | grep -v derivatives_dedup` returns no matches
- [x]Commit (if any cleanup needed): `chore: final validation pass for derivatives TH-label CG dedup`
