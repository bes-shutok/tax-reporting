# Synthetic Koinly 2025 example - loan-affected rebuild

Committed, fully synthetic Koinly export fixture that exercises the loan-affected
rebuild pathway (DP-001 loan-repayment non-taxable treatment) from the
TH-anchored Transaction state machine rollout
(`docs/history/feature-notes/2026-06-20-th-anchored-transaction-state-machine.md`).
The scenario ships THREE Transaction History rows that together cover the
full loan lifecycle on a single asset (WBTC) plus a contrast spot disposal
on a non-loan asset (ETH):

- `crypto_deposit` with `Tag="Loan"` receiving `0,10000000` WBTC at ByBit
  (borrowing-side principal creation).
- `crypto_withdrawal` with `Tag="Loan Repayment"` sending `0,10000000` WBTC
  from ByBit (the DP-001 non-taxable repayment disposal).
- `crypto_exchange` with `Tag=""` sending `0,05000000` ETH from ByBit for
  `150,00` EUR (a plain spot disposal for contrast).

Backs `tests/unit/application/test_phase_c_corpus.py::test_corpus_scenario[loan_affected_rebuild]`,
the per-row `test_treatment_agrees_with_legacy_intent` cases for this
scenario, `test_loan_borrowing_row_is_other`, and
`test_loan_repayment_row_is_loan_repayment`.

## DP-001 loan-repayment non-taxable treatment in scope

Per `docs/maintenance/tax/decision_points/2025.md` DP-001, returning borrowed
crypto is NOT a taxable *alienação onerosa* under CIRS art. 10(20). The
production pipeline filters loan-repayment disposals out of the standard
capital-gains FIFO path and (when `exclude_loan_repayment_gains=True` on
`TaxJurisdictionConfig`) rebuilds the loan-affected asset's gain/loss from
the Transaction History so the repayment row is excluded from taxable
capital gains and the borrowing-side principal creation row is treated as
collateral deposit, not a realization event. This scenario reproduces the
minimal borrow-then-repay shape that the rebuild must distinguish: a
`Tag="Loan"` TH row (principal creation) paired with a `Tag="Loan Repayment"`
TH row (the repayment disposal), plus a non-loan spot disposal for control.

## Phase B Invariant 9 - borrowing is NOT repayment

Phase B Invariant 9 (`docs/history/plans/completed/2026-07-06-th-tx-view-phase-b.md`,
"loan (the borrowing tag) does NOT resolve to LOAN_REPAYMENT") pins the
discriminator:

- The `loan_repayment_tags` default in `TreatmentConfig` is exactly
  `frozenset({"loan repayment"})` - the borrowing-side `"loan"` tag is
  intentionally excluded because it represents collateral deposit, not a
  repayment disposal.
- A row tagged `"loan"` (without `"repayment"`) resolves to `OTHER`
  (acquisition or transfer of collateral), NOT `LOAN_REPAYMENT`.
- A row tagged `"loan repayment"` resolves to `LOAN_REPAYMENT` and falls
  under the DP-001 non-taxable scope.

This scenario's corpus-side verify and the corpus test both confirm the
divergence through the production reader chain
(`parse_th_row` -> `classify_platform` -> `build_transaction` ->
`resolve_treatment`).

## Files

| File | Mandatory | Purpose |
|------|-----------|---------|
| `koinly_2025_capital_gains_report_synth.csv` | yes | Two disposals: `0,10000000` WBTC on ByBit at `20/05/2025 14:00` (cost 4000 EUR, proceeds 5000 EUR, gain 1000 EUR - the loan repayment CG row that production rebuilds from TH and excludes under DP-001 when `exclude_loan_repayment_gains=True`), and `0,05000000` ETH on ByBit at `15/06/2025 11:00` (cost 100 EUR, proceeds 150 EUR, gain 50 EUR - the contrast spot disposal) |
| `koinly_2025_income_report_synth.csv` | yes | One synthetic cashback row (loader's all-or-nothing validation) |
| `koinly_2025_transaction_history_synth.csv` | yes | THREE rows: (a) `crypto_deposit` `Tag="Loan"` receiving `0,10000000` WBTC at ByBit at `2025-04-10 10:00:00 UTC`; (b) `crypto_withdrawal` `Tag="Loan Repayment"` sending `0,10000000` WBTC from ByBit at `2025-05-20 14:00:00 UTC`; (c) `crypto_exchange` `Tag=""` sending `0,05000000` ETH from ByBit for `150,00` EUR at `2025-06-15 11:00:00 UTC`. All `TxHash`, `TxSrc`, `TxDest` empty (CEX-style; ByBit is CEX in the stub registry) |

No `koinly_2025_other_gains_report_synth.csv` is shipped: OGR is optional
for this scenario (loader's all-or-nothing validation only requires
CG/Income/TH; the absence of an OGR file is permitted). The scenario's
purpose is the loan-tag-vs-repayment-tag resolver divergence, which is
observable purely on the TH side; no OGR collision is in scope.

## Scenario and the test it backs

### Loan-affected rebuild (`Tag="Loan"` vs `Tag="Loan Repayment"`)

- TH row (a): `crypto_deposit` at `2025-04-10 10:00:00 UTC`,
  `Tag="Loan"`, receiving `0,10000000` WBTC at `ByBit`, `TxHash=""`,
  `TxSrc=""`, `TxDest=""`. The receiving side is populated and the
  sending side is empty. With the stub registry classifying the platform
  as `WalletKind.CEX`, the resolver takes the disposal-default branch's
  non-disposal arm (`sending_currency is None`) and returns `OTHER`
  (Phase B Invariant 9: the borrowing tag is NOT `LOAN_REPAYMENT`; and
  the empty sending side is acquisition-shaped, not disposal-shaped).
- TH row (b): `crypto_withdrawal` at `2025-05-20 14:00:00 UTC`,
  `Tag="Loan Repayment"`, sending `0,10000000` WBTC from `ByBit`,
  `TxHash=""`, `TxSrc=""`, `TxDest=""`. With the stub registry
  classifying the platform as `WalletKind.CEX`, the resolver matches the
  tag against `loan_repayment_tags={"loan repayment"}` (Invariant 9 scope)
  and returns `LOAN_REPAYMENT` (DP-001 non-taxable scope).
- TH row (c): `crypto_exchange` at `2025-06-15 11:00:00 UTC`, `Tag=""`,
  sending `0,05000000` ETH from `ByBit` for `150,00` EUR. With the stub
  registry classifying the platform as `WalletKind.CEX`, the resolver
  hits the disposal default (`sending_currency` populated, no special
  tag) and returns `SPOT_DISPOSAL`.

**Phase C property under test (Phase B Invariant 9):** the `"loan"` tag
does NOT resolve to `LOAN_REPAYMENT` (it resolves to `OTHER`), while the
paired `"loan repayment"` tag DOES resolve to `LOAN_REPAYMENT`. The corpus
verify (replicated in this README's foundation test) confirms `'Loan' -> other`,
`'Loan Repayment' -> loan_repayment`, `'' -> spot_disposal` under the stub
registry. The corpus test `test_loan_borrowing_row_is_other` asserts row
(a) is `OTHER`, and `test_loan_repayment_row_is_loan_repayment` asserts
row (b) is `LOAN_REPAYMENT`.

**Treatment expectation:**

- Legacy intent for TH row (a): `Tag="Loan"`, sending side empty,
  receiving side populated. The `loan` tag IS in `_LOAN_PRINCIPAL_TAGS`
  from `crypto_fifo/contexts.py` (`frozenset({"loan", "loan repayment"})`),
  BUT Phase B Invariant 9 removes the borrowing-side `"loan"` from the
  repayment default, so legacy intent here mirrors the resolver:
  acquisition-shaped row -> `OTHER`.
- Legacy intent for TH row (b): `Tag="Loan Repayment"`, sending side
  populated. The `loan repayment` tag matches `_LOAN_PRINCIPAL_TAGS` AND
  Phase B's `loan_repayment_tags={"loan repayment"}` -> `LOAN_REPAYMENT`.
- Legacy intent for TH row (c): `Tag=""`, sending side populated, no
  loan/derivatives/reward tag -> `SPOT_DISPOSAL`.
- Resolver: `Treatment.OTHER` (a), `Treatment.LOAN_REPAYMENT` (b),
  `Treatment.SPOT_DISPOSAL` (c).
- `treatment_agree`: `yes` for all three rows.

- Backs: `tests/unit/application/test_phase_c_corpus.py::test_corpus_scenario[loan_affected_rebuild]`,
  the per-row `test_treatment_agrees_with_legacy_intent` cases for this
  scenario, `test_loan_borrowing_row_is_other`, and
  `test_loan_repayment_row_is_loan_repayment`.

## Synthetic-data invariant

Per Phase C Invariant 4: no real wallet addresses, no real tx hashes, no
amounts traceable to personal data. `TxHash`, `TxSrc`, and `TxDest` are
EMPTY (CEX-style; ByBit is CEX in the stub registry and the production
operator map, so the disposal resolves a valid WalletKind without a chain
id). `Sending Wallet` / `Receiving Wallet` / `Wallet Name` use only the
synthetic label `ByBit` (CEX stub entry, registered in the operator
platform map). Amounts (`0,10000000` WBTC, `0,05000000` ETH, 4000/5000 EUR
on the loan repayment, 100/150 EUR on the spot disposal, `0,01000000`
EUROC cashback) are round synthetic values chosen to make the
loan-vs-repayment divergence unambiguous. The borrowing-side principal
(4000 EUR) and the repayment disposal proceeds (5000 EUR) are
intentionally distinct so the rebuild pathway's "borrowed-then-repaid"
discriminator is unambiguous; the contrast spot disposal carries much
smaller amounts so it cannot be confused with either loan row.
