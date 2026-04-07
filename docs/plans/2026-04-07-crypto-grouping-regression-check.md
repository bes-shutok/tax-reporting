# Plan: Check Crypto Grouping Regression And Add Guardrail Tests

## Context
The reported example (`2024-07-27 11:03:00`) does not currently reproduce as a duplicate disposal row in the generated workbook. In `resources/result/extract.xlsx`, that timestamp appears in the `Acquisition date` column, not `Disposal date`, and current runtime inspection shows zero duplicate aggregation keys by `(disposal_date, asset, platform, holding_period)`. `master` and `remove-legacy-token-origin-and-add-safe-examples` are identical for `src/shares_reporting/application/crypto_reporting.py` and its aggregation tests, so the squash merge itself does not appear to have dropped grouping logic. The fix plan is therefore to lock the intended grouping invariants with regression tests first, then only change implementation if a same-key duplicate is reproduced by a RED test.

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

- [ ] Add a characterization test using the real `resources/source/koinly2025/` capital-gains fixture that asserts there are no duplicate rows after loading for the full aggregation key `(disposal_date, asset, platform, holding_period)`.
- [ ] Add a characterization test that documents the reported `2024-07-27 11:03:00` example as an `acquisition_date` repeated across multiple later disposals, so future debugging does not confuse acquisition-date repeats with lost disposal grouping.
- [ ] Add a focused test that proves repeated `disposal_date` values are still allowed when another preserved grouping dimension differs, such as `asset`, `platform`, or `holding_period`.
- [ ] Add or extend an integration-level workbook assertion so the `Crypto` sheet headers and row layout make the `Disposal date` vs `Acquisition date` distinction explicit in tests.

### Task 2: Reproduce A True Same-Key Duplicate Before Changing Code
Files:
- `src/shares_reporting/application/crypto_reporting.py`
- `tests/unit/application/test_crypto_reporting.py`

- [ ] Inspect any user-provided future example of “lost grouping” against the exact key `(disposal_date, asset, platform, holding_period)` and record which field differs before proposing a fix.
- [ ] If a RED test proves that two rows with the same full aggregation key survive `_aggregate_capital_entries()`, identify whether the split is introduced by parsing, platform normalization, holding-period assignment, or post-aggregation filtering.
- [ ] Compare the failing path against commit `f2e80f6` and commit `abb5a57` only after the RED test exists, so the implementation change is anchored to a reproduced regression rather than a merge suspicion.
- [ ] Implement the smallest fix only at the point where same-key rows diverge, and avoid changing the documented grouping dimensions unless the intended behavior itself is revised.

### Task 3: Add Long-Term Regression Guards
Files:
- `tests/unit/application/test_crypto_reporting.py`
- `docs/domain/crypto_implementation_guidelines.md`
- `docs/domain/crypto_rules.md`

- [ ] Add a durable regression test that fails whenever `_aggregate_capital_entries()` emits duplicate rows for the same `(disposal_date, asset, platform, holding_period)` key.
- [ ] Add a regression test for a mixed holding-period timestamp to confirm same-timestamp rows stay split when the holding period differs, because that split is intentional and legally significant.
- [ ] Document the distinction between “expected repeated timestamps” and “forbidden duplicate aggregation keys” in the crypto implementation guidance so future reviews use the same definition of a grouping regression.
- [ ] Update the relevant crypto rule/guidance reference only if the investigation changes the intended grouping contract, not merely its implementation.
