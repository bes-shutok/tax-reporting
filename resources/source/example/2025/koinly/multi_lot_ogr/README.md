# Synthetic Koinly 2025 example - multi-lot OGR collision

Committed, fully synthetic Koinly export fixture that reproduces RFC weakness
#2 (multi-lot OGR over-count) from the TH-anchored Transaction state machine
rollout (`docs/history/context/2026-06-20-th-anchored-transaction-state-machine.md`).
One CG key `(2025-03-10, ETH, Kraken)` carries TWO FIFO lots AND a matching
OGR Profit row on the same legacy key. The scenario is the structural backstop
for the per-Transaction grouping the Phase D OGR override flip depends on.
Backs `tests/unit/application/test_phase_c_corpus.py::test_corpus_scenario[multi_lot_ogr]`.

All four files follow the canonical Koinly export naming (`koinly_<year>_<report>.csv`). The TH `TxHash` is the
synthetic identifier `synth-txhash-multilot-001` - deliberately NOT a real
hash shape (no `0x` prefix, no 64-hex run) so it cannot trip the Phase C
Invariant 4 regex; no real wallet addresses or on-chain identifiers appear
anywhere. `Sending Wallet` / `Receiving Wallet` / `Wallet Name` use only the
synthetic label `Kraken` (registered in the operator platform map, so the
disposal resolves a valid country instead of `UNKNOWN`). Income CSV carries
one synthetic cashback row to satisfy the loader's all-or-nothing validation;
the Other Gains Report is mandatory for this scenario because the OGR row is
the contested join target.

## Files

| File | Mandatory | Purpose |
|------|-----------|---------|
| `koinly_2025_capital_gains_report.csv` | yes | Two FIFO lots on the same `(2025-03-10, ETH, Kraken)` key (0.5 ETH cost 800 EUR + 0.5 ETH cost 850 EUR, total proceeds 2000 EUR) |
| `koinly_2025_income_report.csv` | yes | One synthetic cashback row (loader's all-or-nothing validation) |
| `koinly_2025_other_gains_report.csv` | yes | One OGR Profit row matching the same key (`Value (EUR)=1000`, `Type=Profit`) |
| `koinly_2025_transaction_history.csv` | yes | A `crypto_withdrawal` of 1.0 ETH from Kraken with empty `Tag` and the placeholder `TxHash` |

## Scenario and the test it backs

### Multi-lot OGR over-count (`2025-03-10`, ETH, Kraken)

- TH `crypto_withdrawal` row at `2025-03-10 12:00:00 UTC`, `Tag=""`, sending
  `1,00000000` ETH from `Kraken` with `TxHash = synth-txhash-multilot-001`
  (synthetic identifier; not a real hash shape).
- CG has TWO rows on the same `(2025-03-10, ETH, Kraken)` legacy key: a
  0.5 ETH lot (cost 800 EUR, proceeds 1000 EUR, gain 200 EUR) and a second
  0.5 ETH lot (cost 850 EUR, proceeds 1000 EUR, gain 150 EUR). Both share the
  same `Date Sold`.
- OGR has ONE Profit row on the same key with `Value (EUR) = 1000,00`,
  `Type = Profit`.

**Phase C property under test (RFC weakness #2):** the legacy per-key join
collapses the two CG lots into the OGR row's identity, which is the
over-count surface. The new typed path's per-`Transaction` grouping must
produce ONE `TxCorrelationKey` for the disposal (anchored on the TH `TxHash`),
regardless of how many CG lots join it. The corpus test asserts the TH row's
correlation key has shape `tx_id=<placeholder hash>, composite=(...)` and is
stable across the two-lot join - the structural property Phase D needs before
flipping the OGR override. Without it the multi-lot scenario only verifies
`SPOT_DISPOSAL == SPOT_DISPOSAL`, which is trivially true and does not prove
the per-Transaction grouping.

**Treatment expectation:**

- Legacy intent for the TH row: `Tag=""`, sending side populated, no
  loan/derivatives/reward tag -> `SPOT_DISPOSAL`.
- Resolver: `Treatment.SPOT_DISPOSAL`.
- `treatment_agree`: `yes`.

- Backs: `tests/unit/application/test_phase_c_corpus.py::test_corpus_scenario[multi_lot_ogr]`
  and `test_phase_c_corpus.py::test_multi_lot_ogr_one_event_many_lots`.

## Synthetic-data invariant

Per Phase C Invariant 4: no real wallet addresses, no real tx hashes, no
amounts traceable to personal data. `TxHash` is the synthetic identifier
`synth-txhash-multilot-001` (not a `0x`-prefixed hex string; passes the
`test_no_real_data_in_fixtures` regex `(0x[0-9a-fA-F]{40,})|([0-9a-fA-F]{64})`
because it contains neither a `0x` + 40+ hex prefix nor a 64-hex run).
`TxSrc` and `TxDest` are empty. Amounts (0.5 / 0.5 ETH, 800 / 850 EUR cost,
2000 EUR proceeds, 1000 EUR OGR profit) are round synthetic values chosen to
make the over-count shape unambiguous.
