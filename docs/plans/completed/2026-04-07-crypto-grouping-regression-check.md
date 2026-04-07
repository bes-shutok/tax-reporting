# Plan: Check Crypto Grouping Regression And Add Guardrail Tests

**Status: Complete** — All tasks done. Task 2 deferred (no same-key duplicate reproducible).

## Context
The reported example (`2024-07-27 11:03:00`) does not currently reproduce as a duplicate disposal row in the generated workbook. In `resources/result/extract.xlsx`, that timestamp appears in the `Acquisition date` column, not `Disposal date`, and current runtime inspection shows zero duplicate aggregation keys by `(disposal_date, asset, platform, holding_period)`. `master` and `remove-legacy-token-origin-and-add-safe-examples` are identical for `src/shares_reporting/application/crypto_reporting.py` and its aggregation tests, so the squash merge itself does not appear to have dropped grouping logic. The fix plan is therefore to lock the intended grouping invariants with regression tests first, then only change implementation if a same-key duplicate is reproduced by a RED test.

## Line-Count And Timestamp-Precision Investigation (2026-04-07)

The user observed output increasing from ~100 lines to ~138 lines in Capital Gains and suspected the seconds-precision change in `_format_datetime` (commit `253f55c`, "reduce crypto capital gains lines") might be responsible.

### Findings

1. **Koinly source data is minute-precision only.** The `Date Sold` column in `koinly_2025_capital_gains_report_*.csv` uses format `DD/MM/YYYY HH:MM` with no seconds. Verified across all 3,368 data rows.

2. **The seconds-precision change has zero effect.** Commit `253f55c` changed `_format_datetime` from `%Y-%m-%d %H:%M` to `%Y-%m-%d %H:%M:%S`. Since Koinly never provides seconds, all parsed datetimes have `second=0`, producing `HH:MM:00` strings that group identically to `HH:MM`. Confirmed: 138 unique keys at second-precision = 138 unique keys at minute-precision.

3. **The holding_period dimension adds only 2 rows.** Without `holding_period` in the key, there would be 136 groups; with it, 138 (2 groups have mixed short-term/long-term lots).

4. **The 94-line estimate in the original plan (`reduce-crypto-capital-gains-lines.md`) was from a different data analysis snapshot**, not from the current dataset. The actual pipeline produces: 3,368 raw rows → skip 1,580 zero-value → 1,788 rows → aggregation collapses to 138 → materiality filter removes 0 (all have |gain/loss| ≥ 1 EUR) → **138 final rows**.

5. **Official form requires day-level precision only, no time-of-day.** Verified from the current Anexo J Quadro 9.4 form (`modelo3_anexo_j_2025.pdf`, in force January 2026, approved by Portaria 104/2026 dated 2026-03-05): the disposal and acquisition date columns are **Ano, Mês, Dia** (Year, Month, Day). No time-of-day field exists. The same applies to Anexo G Quadro 18A and Anexo G1 Quadro 7. No override found in Ofício Circulado 20278/2025 (dated 2025-03-17) or Portaria 104/2026 (dated 2026-03-05). Updated PT-C-020 and PT-C-027 in `docs/domain/crypto_rules.md` with this constraint.

6. **Aggregation granularity floor is day-level.** Per PT-C-020, the form captures dates as Ano/Mês/Dia. Aggregation coarser than day-level (e.g. per month or per year) would merge distinct disposal events and is not acceptable. The current minute-level grouping is stricter than legally required; day-level would also be correct.

7. **The `_format_datetime` seconds change was introduced to prevent a theoretical collision** (e.g. `13:01:05` vs `13:01:55` merging at minute level) described in the plan's "Post-Implementation Fixes — Issue 1". This collision cannot occur with Koinly's actual minute-precision source data, but the change is harmless and defensive if future data sources include seconds.

## Validation Commands
```bash
uv run python - <<'PY'
from collections import Counter
from pathlib import Path
from shares_reporting.application.crypto_reporting import load_koinly_crypto_report

report = load_koinly_crypto_report(Path("resources/source/koinly2025"))
keys = [(e.disposal_date, e.asset, e.platform, e.holding_period) for e in report.capital_entries]
dups = [(k, c) for k, c in Counter(keys).items() if c > 1]
print("duplicate_aggregation_keys", dups)
PY
```

```bash
uv run pytest tests/unit/application/test_crypto_reporting.py -k "aggregate or grouping" -v
```

```bash
uv run pytest tests/integration/test_excel_generation_integration.py -k "crypto" -v
```

### Task 1: Capture The Current Failure Mode Precisely
Files:
- `tests/unit/application/test_crypto_reporting.py`
- `tests/integration/test_excel_generation_integration.py`

- [x] Add a characterization test using the real `resources/source/koinly2025/` capital-gains fixture that asserts there are no duplicate rows after loading for the full aggregation key `(disposal_date, asset, platform, holding_period)`.
- [x] Add a characterization test that documents the reported `2024-07-27 11:03:00` example as an `acquisition_date` repeated across multiple later disposals, so future debugging does not confuse acquisition-date repeats with lost disposal grouping.
- [x] Add a focused test that proves repeated `disposal_date` values are still allowed when another preserved grouping dimension differs, such as `asset`, `platform`, or `holding_period`.
- [x] Add or extend an integration-level workbook assertion so the `Crypto` sheet headers and row layout make the `Disposal date` vs `Acquisition date` distinction explicit in tests.

### Task 2: Reproduce A True Same-Key Duplicate Before Changing Code
Files:
- `src/shares_reporting/application/crypto_reporting.py`
- `tests/unit/application/test_crypto_reporting.py`

- [x] Inspect any user-provided future example of “lost grouping” against the exact key `(disposal_date, asset, platform, holding_period)` and record which field differs before proposing a fix. (skipped - no user-provided example reproduces duplicates; Task 1 confirmed 138 entries / 138 unique keys / zero duplicates with current data)
- [x] If a RED test proves that two rows with the same full aggregation key survive `_aggregate_capital_entries()`, identify whether the split is introduced by parsing, platform normalization, holding-period assignment, or post-aggregation filtering. (skipped - no RED test can be produced; aggregation correctly collapses same-key entries)
- [x] Compare the failing path against commit `f2e80f6` and commit `abb5a57` only after the RED test exists, so the implementation change is anchored to a reproduced regression rather than a merge suspicion. (skipped - deferred per plan logic; comparison only warranted after a RED test reproduces the regression)
- [x] Implement the smallest fix only at the point where same-key rows diverge, and avoid changing the documented grouping dimensions unless the intended behavior itself is revised. (skipped - no same-key divergence found; no implementation change warranted)

### Task 3: Add Long-Term Regression Guards
Files:
- `tests/unit/application/test_crypto_reporting.py`
- `docs/domain/crypto_implementation_guidelines.md`
- `docs/domain/crypto_rules.md`

- [x] Add a durable regression test that fails whenever `_aggregate_capital_entries()` emits duplicate rows for the same `(disposal_date, asset, platform, holding_period)` key.
- [x] Add a regression test for a mixed holding-period timestamp to confirm same-timestamp rows stay split when the holding period differs, because that split is intentional and legally significant.
- [x] Document the distinction between “expected repeated timestamps” and “forbidden duplicate aggregation keys” in the crypto implementation guidance so future reviews use the same definition of a grouping regression.
- [x] Update the relevant crypto rule/guidance reference only if the investigation changes the intended grouping contract, not merely its implementation. (no update needed — investigation confirmed the grouping contract is correct and unchanged)

## Follow-On Investigation
The grouping investigation above remains valid and is preserved unchanged. Additional debugging after that work surfaced a separate likely bug in reward classification, plus a clarification about the `Fee` note concern:

- `MNT` rewards from the current ByBit/Koinly dataset are currently exposed to the ISO-fiat classifier even though the asset in context is Mantle token, not Mongolian tögrög.
- Rows with `Notes = Fee` were not reproduced as a reward-parsing bug; they appear to remain in capital gains rather than leaking into reward entries.
- The squash merge from `remove-legacy-token-origin-and-add-safe-examples` still does not appear to be the cause of the grouping concern.

### Task 4: Prove Or Reject The Reward Ticker-Collision Bug Before Fixing It
Files:
- `src/shares_reporting/application/crypto_reporting.py`
- `tests/unit/application/test_crypto_reporting.py`
- `docs/domain/crypto_implementation_guidelines.md`

- [x] Add a RED unit test for known reward ticker collisions that asserts `MNT` is classified as `DEFERRED_BY_LAW`, alongside the existing `GEL` collision behavior.
- [x] Add a parser-level regression test using a minimal Koinly income fixture that proves a reward row with `Asset = MNT` stays deferred after `load_koinly_crypto_report()`.
- [x] Confirm whether the fix should remain a curated collision list or move to a more explicit repository policy for reward-only ticker overrides, based on what other real Koinly reward assets collide with ISO fiat codes.
- [x] Implement the smallest fix only after the RED tests exist, and update the implementation guideline collision examples if the allowed collision set changes.

### Task 5: Guard The Boundary Between Reward Entries And Capital-Gains Rows
Files:
- `tests/unit/application/test_crypto_reporting.py`
- `src/shares_reporting/application/crypto_reporting.py`

- [x] Add a regression test showing that a capital-gains row with `Notes = Fee` does not create or alter reward entries when both capital-gains and income reports are loaded together.
- [x] Confirm in tests that reward parsing depends only on the income report input, not on `Notes` values from the capital-gains export.
- [x] Only change production parsing code if a RED test shows capital-gains metadata can currently contaminate the reward path.

### Task 6: Re-check The Merge Hypothesis Only If A RED Test Exists
Files:
- `src/shares_reporting/application/crypto_reporting.py`
- `tests/unit/application/test_crypto_reporting.py`

- [x] Compare the failing path against `remove-legacy-token-origin-and-add-safe-examples` only if a RED test reproduces a regression on `master`. (skipped - no RED test reproduced a regression; `git diff master..remove-legacy-token-origin-and-add-safe-examples -- crypto_reporting.py` shows zero diff)
- [x] Keep the squash-merge theory out of the root-cause narrative unless code or test evidence shows a behavior difference between the branch and `master`. (confirmed - no behavioral difference exists between branches; theory excluded from narrative)
