# Synthetic Koinly 2025 example - Payment / OGR collision

Committed, fully synthetic Koinly export fixture that reproduces RFC weakness
#5 (Payment / OGR collision) from the TH-anchored Transaction state machine
rollout (`docs/history/feature-notes/2026-06-20-th-anchored-transaction-state-machine.md`).
ONE Payment disposal on `(2025-06-15, EUROC, Wirex)` has BOTH a CG lot
(`proceeds=0, cost=20 EUR` - the unpriced-EUROC phantom-loss shape) AND a
matching OGR Loss row (`Value (EUR)=15, Type=Loss`) under the same legacy
per-key join. The collision is the contested premise the re-zero block was
added to defend against: a single Payment disposal whose legacy
`(local_date, asset, wallet)` key collides with an OGR Loss row would, under
the live per-key join, double-count the loss surface.

Backs `tests/unit/application/test_phase_c_corpus.py::test_corpus_scenario[payment_ogr_collision]`.

**Scope note.** This scenario reproduces the latent collision so the corpus
exercises it; Phase C verifies the resolver STILL classifies the TH row as
`Treatment.PAYMENT` (`treatment_agree=yes` with the legacy intent derived from
`payment_proceeds.py::_DEFAULT_PAYMENT_TAGS`). The re-zero block is NOT the
subject of Phase C; Phase D owns its removal (per the design invariant that
Phase C touches zero production code). The re-zero block lives in
`src/tax_reporting/application/crypto_reporting.py` (DP-014 snapshot+restore
pair at the inline-comment markers `Re-zero snapshot` and `Re-zero restore`),
NOT in `crypto_fifo/`; the agree-branch over-count defense (commit `7f9b8b8`,
`feat(crypto): apply OGR P&L at event level`) lives in
`src/tax_reporting/application/crypto/ogr_event_level.py::apply_ogr_event_level`
(`_apply_agree_first_lot` first-lot-absorbs distribution). Phase D's
removal targets those sites.

All four files follow the canonical Koinly export naming (`koinly_<year>_<report>.csv`). The TH `TxHash`, `TxSrc`,
and `TxDest` are EMPTY - the established CEX convention from
`2025/koinly/payment/` (no real hash shape, no `0x` prefix, no 64-hex run, so
the Phase C Invariant 4 regex
`(0x[0-9a-fA-F]{40,})|([0-9a-fA-F]{64})` cannot trip). No real wallet
addresses or on-chain identifiers appear anywhere. `Sending Wallet` /
`Receiving Wallet` / `Wallet Name` use only the synthetic label `Wirex`
(registered in the operator platform map, so the disposal resolves a valid
country instead of `UNKNOWN`). Income CSV carries one synthetic cashback row
to satisfy the loader's all-or-nothing validation; the Other Gains Report is
mandatory for this scenario because the OGR Loss row is the contested join
target.

## Files

| File | Mandatory | Purpose |
|------|-----------|---------|
| `koinly_2025_capital_gains_report.csv` | yes | One EUROC disposal on `(2025-06-15, EUROC, Wirex)` with `proceeds=0, cost=20 EUR` (phantom-loss shape; Koinly could not price EUROC) |
| `koinly_2025_income_report.csv` | yes | One synthetic cashback row (loader's all-or-nothing validation) |
| `koinly_2025_other_gains_report.csv` | yes | One OGR Loss row matching the same key (`Value (EUR)=15,00`, `Type=Loss`) |
| `koinly_2025_transaction_history.csv` | yes | A `crypto_withdrawal` of `100,00000000` EUROC from `Wirex` with `Tag="Payment"`, `Net Value (EUR) == "0,00"`, and empty `TxHash` (CEX, falls back silently per Phase A policy) |

## Scenario and the test it backs

### Payment / OGR collision (`2025-06-15`, EUROC, Wirex)

- TH `crypto_withdrawal` row at `2025-06-15 12:00:00 UTC`, `Tag="Payment"`,
  sending `100,00000000` EUROC from `Wirex` with `Net Value (EUR) == "0,00"`
  (Koinly could not price the imported EUROC ticker) and empty `TxHash`,
  `TxSrc`, `TxDest` (CEX convention; Phase A silently falls back to the
  composite key with `requires_review=False`).
- CG has ONE row on the same `(2025-06-15, EUROC, Wirex)` legacy key: 100
  EUROC, cost 20 EUR, proceeds 0, gain -20 EUR (the phantom full-cost loss
  the DP-014 `infer_payment_proceeds` correction targets).
- OGR has ONE Loss row on the same key with `Value (EUR) = 15,00`,
  `Type = Loss` (the contested join target).

**Phase C property under test (RFC weakness #5):** the legacy per-key join
sees the same `(2025-06-15, EUROC, Wirex)` tuple for the Payment disposal AND
the OGR Loss row; the new typed path's per-`Transaction` grouping must
attribute the disposal to ONE `TxCorrelationKey` anchored on the TH row
identity (composite fallback because `TxHash` is empty), NOT collapse the CG
lot and the OGR row into a single legacy-key identity. Phase C verifies the
resolver STILL classifies the row as `Treatment.PAYMENT` (`treatment_agree=yes`
vs. the legacy intent derived from `_DEFAULT_PAYMENT_TAGS`); the re-zero
block is NOT removed in Phase C.

**Treatment expectation:**

- Legacy intent for the TH row: `Tag="Payment"`, sending side populated, no
  loan/derivatives/reward tag -> matches `payment_proceeds.py` payment
  frozenset -> `PAYMENT`.
- Resolver: `Treatment.PAYMENT`.
- `treatment_agree`: `yes`.

- Backs: `tests/unit/application/test_phase_c_corpus.py::test_corpus_scenario[payment_ogr_collision]`
  and the per-row `test_treatment_agrees_with_legacy_intent` case for this
  scenario.

## Synthetic-data invariant

Per Phase C Invariant 4: no real wallet addresses, no real tx hashes, no
amounts traceable to personal data. `TxHash`, `TxSrc`, and `TxDest` are
EMPTY (the established CEX convention from `2025/koinly/payment/`; passes the
`test_no_real_data_in_fixtures` regex
`(0x[0-9a-fA-F]{40,})|([0-9a-fA-F]{64})` trivially because no `0x`-prefixed
or 64-hex string appears anywhere). Amounts (100 EUROC, 20 EUR cost, 0
proceeds, 15 EUR OGR loss) are round synthetic values chosen to make the
collision shape unambiguous: the CG lot and the OGR Loss row share the same
`(2025-06-15, EUROC, Wirex)` legacy key but are NOT the same economic event.
