# Synthetic Koinly 2025 example - DEX vs CEX tx-id absence

Committed, fully synthetic Koinly export fixture that exercises Phase A's
"Tx-id fallback policy (2026-07-05)" (RFC, TH-anchored Transaction state
machine rollout,
`docs/history/feature-notes/2026-06-20-th-anchored-transaction-state-machine.md`):
when `TxHash` is empty, a DEX disposal sets `requires_review=True` while a
CEX disposal silently falls back to the composite correlation key. The
scenario ships TWO `crypto_withdrawal` rows whose `TxHash` is the empty
string so the new typed path's `TxCorrelationKeyResolver.resolve` produces
the documented divergence:

- Ledger Berachain (BERA) DEX withdrawal of `0,50000000` BERA -> DEX branch,
  `requires_review=True`.
- Kraken CEX withdrawal of `0,50000000` ETH -> CEX branch, composite
  fallback, `requires_review=False`.

Backs `tests/unit/application/test_phase_c_corpus.py::test_corpus_scenario[dex_cex_tx_id_absence]`
and the per-row `test_treatment_agrees_with_legacy_intent` case for this
scenario. This scenario confirms the discrepancy CSV's `requires_review`
column correctly differentiates the two rows when both lack a `TxHash`.

## Tx-id fallback policy in scope

The Phase-A policy (RFC "Tx-id fallback policy (2026-07-05)"):

- `TxCorrelationKey.tx_id` derives from `TxHash` alone (never from
  `TxSrc`/`TxDest`; see `development_lessons.md` #43).
- When `TxHash` is empty, the resolver falls back to a composite
  `(UTC instant, asset, wallet, amount)` key. Whether the fallback sets
  `requires_review=True` depends on the wallet kind:
  - DEX wallet (no off-chain ledger identity): an on-chain movement without
    `TxHash` is a data-quality defect that cannot be silently attributed to
    a chain id, so `requires_review=True` and the discrepancy CSV surfaces
    the row for manual review.
  - CEX wallet (off-chain ledger identity held by the operator): a missing
    `TxHash` is the normal state for CEX withdrawals (the exchange holds the
    internal ledger id, not a chain id), so the resolver silently uses the
    composite key and `requires_review=False`.

The wallet-kind classification used by the resolver is normally bound to the
production operator registry; Phase C defers that wiring to a later task.
This scenario's corpus-side verify and the corpus test both inject a STUB
REGISTRY returning `WalletKind.CEX` for `{"Kraken", "ByBit", "Wirex"}` and
`WalletKind.DEX` for `{"Ledger Berachain (BERA)", "SUI", "Ledger"}` (mirrors
`tests/unit/application/test_crypto_phase_a_smoke.py::_KrakenRegistry`). The
stub is the corpus-side substitute for the production binding; the
classification policy under test (DEX-flag vs CEX-silent) is unchanged.

## Files

| File | Mandatory | Purpose |
|------|-----------|---------|
| `koinly_2025_capital_gains_report.csv` | yes | Two disposals: `0,50000000` BERA on Ledger Berachain (BERA) at `10/03/2025 12:00` (cost 100 EUR, proceeds 150 EUR, gain 50 EUR) and `0,50000000` ETH on Kraken at `12/03/2025 12:00` (cost 400 EUR, proceeds 500 EUR, gain 100 EUR) |
| `koinly_2025_income_report.csv` | yes | One synthetic cashback row (loader's all-or-nothing validation) |
| `koinly_2025_transaction_history.csv` | yes | TWO `crypto_withdrawal` rows: `0,50000000` BERA from `Ledger Berachain (BERA)` at `2025-03-10 12:00:00 UTC` with EMPTY `TxHash` (DEX branch); `0,50000000` ETH from `Kraken` at `2025-03-12 12:00:00 UTC` with EMPTY `TxHash` (CEX branch); both `Tag=""` |

No `koinly_2025_other_gains_report.csv` is shipped: OGR is optional
for this scenario (loader's all-or-nothing validation only requires
CG/Income/TH; the absence of an OGR file is permitted). The scenario's
purpose is the tx-id-fallback policy divergence, which is observable purely
on the TH side; no OGR collision is in scope.

## Scenario and the test it backs

### DEX/CEX tx-id absence divergence

- TH row (a): `crypto_withdrawal` at `2025-03-10 12:00:00 UTC`, `Tag=""`,
  sending `0,50000000` BERA from `Ledger Berachain (BERA)`, `TxHash=""`,
  `TxSrc=""`, `TxDest=""`. With the stub registry classifying the platform
  as `WalletKind.DEX`, the resolver takes the DEX branch and sets
  `requires_review=True` (on-chain movement without a chain id).
- TH row (b): `crypto_withdrawal` at `2025-03-12 12:00:00 UTC`, `Tag=""`,
  sending `0,50000000` ETH from `Kraken`, `TxHash=""`, `TxSrc=""`,
  `TxDest=""`. With the stub registry classifying the platform as
  `WalletKind.CEX`, the resolver takes the CEX branch and silently falls
  back to the composite key (`requires_review=False`).

**Phase C property under test (tx-id fallback policy):** both rows have an
empty `TxHash`, yet the discrepancy CSV's `requires_review` column must
differentiate them. The corpus verify (replicated in this README's
foundation test) confirms `Ledger Berachain (BERA) flag= True` and
`Kraken flag= False` under the stub registry. The corpus test
`test_corpus_scenario[dex_cex_tx_id_absence]` asserts the same per-row
`requires_review` divergence through the production reader chain
(`parse_th_row` -> `classify_platform` -> `build_transaction` ->
`TxCorrelationKeyResolver.resolve`).

**Treatment expectation:**

- Legacy intent for both TH rows: `Tag=""`, sending side populated, no
  loan/derivatives/reward tag -> `SPOT_DISPOSAL`.
- Resolver: `Treatment.SPOT_DISPOSAL` for both rows.
- `treatment_agree`: `yes` for both rows (the divergence is on the
  correlation key shape, NOT the treatment).

- Backs: `tests/unit/application/test_phase_c_corpus.py::test_corpus_scenario[dex_cex_tx_id_absence]`
  and the per-row `test_treatment_agrees_with_legacy_intent` case for this
  scenario.

## Synthetic-data invariant

Per Phase C Invariant 4: no real wallet addresses, no real tx hashes, no
amounts traceable to personal data. `TxHash`, `TxSrc`, and `TxDest` are
EMPTY (the scenario's defining property). `Sending Wallet` / `Wallet Name`
use only the synthetic labels `Ledger Berachain (BERA)` (DEX stub entry) and
`Kraken` (CEX stub entry). Amounts (`0,50000000` BERA, `0,50000000` ETH,
100/150/400/500 EUR) are round synthetic values chosen to make the
tx-id-absence divergence unambiguous.
