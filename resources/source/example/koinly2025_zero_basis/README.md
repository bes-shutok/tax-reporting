# Synthetic Koinly 2025 example - zero-basis materiality

Committed, fully synthetic Koinly export fixture that reproduces the zero-basis
review-flag materiality gate (`zero_basis_review_min_proceeds`, default 10 EUR;
see DP-013 and `_build_zero_basis_review_reason` in `application/crypto/fifo_helpers.py`)
without any personal data. Backs `tests/end_to_end/test_crypto_zero_basis_materiality.py`
(migrated by plan Task 4).

All three files use the `_synth.csv` filename token. `TxHash`, `TxSrc`, and `TxDest`
are empty for every Transaction History row. `Sending Wallet` / `Receiving Wallet`
use only the synthetic label `Demo Spot`. There is no Other Gains Report: the loader's
all-or-nothing validation only requires the three mandatory files (CG, income, TH);
OGR is optional.

## Files

| File | Mandatory | Purpose |
|------|-----------|---------|
| `koinly_2025_capital_gains_report_synth.csv` | yes | Three zero-cost disposal rows |
| `koinly_2025_income_report_synth.csv` | yes | The two reward acquisitions |
| `koinly_2025_transaction_history_synth.csv` | yes | Matching disposal events (no derivatives labels) |

## Test cases and the zero-basis rule they exercise

The zero-basis rule (`_build_zero_basis_review_reason`) has these branches under
the default `min_proceeds=10` threshold:

| Row | Asset | Cost | Proceeds | Gain | Behaviour under `min_proceeds=10` | Test |
|-----|-------|------|----------|------|------------------------------------|------|
| (a) | FEE | 0 | 0 | 0 | Filtered out by the `|gain| >= 1` materiality filter (PT-C-028); never reaches `capital_entries`. If one did survive, it must NOT carry the zero-basis reason. | `test_fee_token_disposals_not_flagged` |
| (b) | RWD | 0 | 5.00 | 5.00 | `0 < proceeds < min_proceeds`, so the zero-basis reason is suppressed (small-reward carve-out). Survives materiality. | `test_small_reward_disposals_below_threshold_not_flagged` |
| (c) | ZBX | 0 | 75.00 | 75.00 | `proceeds >= min_proceeds`, so the zero-basis reason fires. Survives materiality. | `test_larger_zero_cost_disposals_above_threshold_flagged` |

Under the backward-compat escape hatch (`min_proceeds=0`), rows (b) and (c) both
acquire the zero-basis reason (row (a) stays filtered by materiality because
`gain == 0`). This backs `test_backward_compat_min_proceeds_zero_flags_all`.

## Notes

- The rows are deliberately on `Demo Spot`, which is NOT in the operator platform
  map, so each surviving entry additionally carries an `UNKNOWN`-country review
  reason. The zero-basis assertions check specifically for the `"Zero acquisition
  cost"` marker substring, which is independent of the platform-UNKNOWN reason.
- No Transaction History row carries a derivatives label (`Funding fee` /
  `Futures fee` / `Realized gain`), so the derivatives CG dedup never runs against
  this directory even when `separate_derivatives_reporting=True`.
