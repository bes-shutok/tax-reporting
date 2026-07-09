# Synthetic Koinly 2025 example - payment proceeds

Committed, fully synthetic Koinly export fixture that reproduces the DP-014
payment-proceeds correction (`infer_payment_proceeds`; see
`application/crypto/payment_proceeds.py`) without any personal data. Backs
`tests/end_to_end/test_crypto_payment_proceeds.py` (migrated by plan Task 5).

All three files follow the canonical Koinly export naming (`koinly_<year>_<report>.csv`). `TxHash`, `TxSrc`, and `TxDest`
are empty for every Transaction History row. `Sending Wallet` / `Receiving Wallet`
use only the synthetic label `Wirex` (the operator the real motivating case uses;
`Wirex` IS registered in the operator platform map, so the disposal resolves a
valid country instead of the `UNKNOWN` sentinel). There is no Other Gains Report:
the loader's all-or-nothing validation only requires the three mandatory files
(CG, income, TH); OGR is optional.

## Files

| File | Mandatory | Purpose |
|------|-----------|---------|
| `koinly_2025_capital_gains_report.csv` | yes | One EUROC disposal with `proceeds=0, cost>0` |
| `koinly_2025_income_report.csv` | yes | One synthetic cashback row |
| `koinly_2025_transaction_history.csv` | yes | A `Payment`-tagged EUROC disposal with `Net Value (EUR) == 0` |

## Scenario and the tests it backs

### Payment-proceeds correction (`2025-06-15`, EUROC, Wirex)

- TH `crypto_withdrawal` row with `Tag="Payment"`, sending `100,00000000` EUROC from
  `Wirex`, with `Net Value (EUR) == "0,00"` (Koinly could not price the imported
  EUROC ticker).
- CG disposal of `100,00000000` EUROC with `Cost (EUR) = 100,00`,
  `Proceeds (EUR) = 0,0`, `Gain / loss = -100,00` (the phantom full-cost loss: the
  entire cost basis surfaces as a loss because Koinly assigned zero proceeds).
- EUROC is an EUR-pegged stablecoin (`stablecoin_pegs.EUROC = "EUR"` in
  `docs/maintenance/tax/popular_crypto_tokens.json`), so the correction applies the
  EUR-par fallback: `proceeds = amount @ 1 EUR = 100 EUR`, `gain = 100 - 100 = 0`.

**Pipeline behaviour**:

| Flag | Expected result |
|------|-----------------|
| `infer_payment_proceeds=True` | `proceeds` corrected to `100 EUR`; `gain = 0` (immaterial, filtered by the `|gain| >= 1` materiality filter); no phantom-loss survivor in `capital_entries`; a `CryptoReviewEntry` audit row names `"EUR par"` and references the fixture-derived proceeds `100.00000000`. |
| `infer_payment_proceeds=False` | Phantom full-cost loss survives unchanged: `proceeds=0, gain=-cost=-100, cost=100`. No correction-driven review entry. |

The CG `Wallet Name` and TH `Sending Wallet` are both `Wirex`, and both amounts are
`100,00000000`, so the `(calendar_day, asset, platform, amount_6dp)` correlation key
matches exactly (`2025-06-15`, `EUROC`, `Wirex`, `100.000000`). The count-equality
gate sees `cg_count == th_count == 1` on this key, so the correction fires.

- Backs: `TestPaymentProceedsE2E#test_payment_row_not_carrying_phantom_full_cost_loss`
  (flag on) and `TestPaymentProceedsE2E#test_no_correction_when_flag_off_preserves_phantom_loss`
  (flag off).
