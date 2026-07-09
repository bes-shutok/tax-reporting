# Synthetic Koinly 2025 example - derivatives close (DP-010/DP-012 routing)

Committed, fully synthetic Koinly export fixture that exercises the
derivatives-close treatment routing (DP-010/DP-012 Quadro 13 routing) from the
TH-anchored Transaction state machine rollout
(`docs/history/feature-notes/2026-06-20-th-anchored-transaction-state-machine.md`).
The scenario ships TWO Transaction History rows that together cover the full
set of derivatives TH labels registered for Koinly 2025 - one row tagged
`Realized gain` and one row tagged `Futures fee` (both at ByBit) - plus a
paired OGR Profit row and OGR Loss row on the same dates, and the CG rows
that the production pipeline would route through the derivatives branch when
`use_other_gains_report=True`.

Backs `tests/unit/application/test_phase_c_corpus.py::test_corpus_scenario[derivatives_close]`,
the per-row `test_treatment_agrees_with_legacy_intent` cases for this
scenario, and `test_derivatives_scenario_requires_injected_tags`.

## DP-010/DP-012 derivatives Quadro 13 routing in scope

Per `docs/maintenance/tax/decision_points/2025.md` DP-010 and DP-012, crypto
derivatives disposals (futures/permabash collateral liquidations, funding-fee
settlements, realized-PnL closes) are reported on Anexo G Quadro 13 with
operation code `G51` rather than through the standard capital-gains FIFO
pathway. The production pipeline routes any disposal whose Koinly `Tag`
matches the derivatives TH labels file
(`docs/maintenance/tax/derivatives_labels/koinly_2025.json`) through the
Other Gains Report when `TaxJurisdictionConfig.use_other_gains_report=True`,
so the OGR row is the authoritative P&L carrier and the matching CG rows are
demoted to support detail (per CLAUDE.md OGR overrides apply BEFORE
`_aggregate_capital_entries()`).

This scenario reproduces the minimal two-row shape that the routing must
distinguish:

- `crypto_withdrawal` `Tag="Realized gain"` sending `0,00100000` ETH from
  ByBit (a realized-PnL close).
- `crypto_exchange` `Tag="Futures fee"` sending `0,00010000` ETH from ByBit
  for `0,25` EUR (a futures-fee settlement).

Both tags are exercised because the production JSON labels set
`{"Funding fee", "Futures fee", "Realized gain"}` is the authoritative
discriminator, and the corpus must surface every tag in the JSON
(see Monitor: "Derivatives labels JSON may grow").

## Phase B Invariant 5 - derivatives_tags injected from JSON

Phase B Invariant 5 (`docs/history/plans/completed/2026-07-06-th-tx-view-phase-b.md`,
"No hardcoded derivatives tags") pins the source:

- The `derivatives_tags` default in `TreatmentConfig` is the EMPTY
  `frozenset()` - the resolver never ships a hardcoded derivatives tag set.
- The production loader
  `application/crypto/derivatives_dedup.py::_load_derivatives_labels_config("koinly", 2025)`
  reads `docs/maintenance/tax/derivatives_labels/koinly_2025.json` and returns
  `frozenset({"Funding fee", "Futures fee", "Realized gain"})` - this is the
  single source of truth for what counts as a derivatives TH label.
- A corpus test that exercises this scenario MUST inject the full loaded
  frozenset via `TreatmentConfig(derivatives_tags=<loaded JSON>)`; calling
  `TreatmentConfig()` with no override leaves `derivatives_tags` empty and
  the routing does not fire.

The verify one-liner in this task and the corpus test both load the JSON via
the production loader (no hardcoded subset), so the corpus exercises every
tag the production pipeline ships.

## Phase B Invariant 6 - precedence at the `Realized gain` overlap

Phase B Invariant 6 (`docs/history/plans/completed/2026-07-06-th-tx-view-phase-b.md`)
pins the resolver precedence:

```
LOAN_REPAYMENT > PAYMENT > DERIVATIVES_CLOSE > REWARD_AIRDROP_LP > SPOT_DISPOSAL (default) > OTHER
```

The `"Realized gain"` tag is the precedence discriminator:

- Without `derivatives_tags` injected (default `TreatmentConfig()`), the
  resolver falls through `derivatives_tags` (empty) and matches
  `"Realized gain"` against `_DEFAULT_REWARD_TAGS` (Phase B ships
  reward/airdrop/lp literals inline) -> `Treatment.REWARD_AIRDROP_LP`.
- With `derivatives_tags` injected from the JSON, the resolver matches
  `"Realized gain"` against the derivatives set FIRST (precedence) ->
  `Treatment.DERIVATIVES_CLOSE`.

The corpus verify (replicated in this README's foundation test) confirms
`'Realized gain' -> derivatives_close` AND `'Futures fee' -> derivatives_close`
under the injected config. The precedence test
`test_derivatives_scenario_requires_injected_tags` asserts the
default-config result for the same row is `REWARD_AIRDROP_LP`, pinning the
Phase B Invariant 6 precedence at the overlap.

## Files

| File | Mandatory | Purpose |
|------|-----------|---------|
| `koinly_2025_capital_gains_report.csv` | yes | Two disposals on ByBit: `0,00100000` ETH at `10/03/2025 12:00` (cost 3 EUR, proceeds 5 EUR, gain 2 EUR - the realized-PnL close CG row) and `0,00010000` ETH at `12/03/2025 12:00` (cost 0,30 EUR, proceeds 0,25 EUR, loss 0,05 EUR - the futures-fee settlement CG row). Production routes both through OGR when `use_other_gains_report=True`; the CG rows are support detail. |
| `koinly_2025_income_report.csv` | yes | One synthetic cashback row (loader's all-or-nothing validation) |
| `koinly_2025_other_gains_report.csv` | yes | TWO OGR rows: one Profit (`Value (EUR)=2,00`, `Type=Profit`) matching the realized-gain key, one Loss (`Value (EUR)=-0,05`, `Type=Loss`) matching the futures-fee key |
| `koinly_2025_transaction_history.csv` | yes | TWO rows: (a) `crypto_withdrawal` `Tag="Realized gain"` sending `0,00100000` ETH from ByBit at `2025-03-10 12:00:00 UTC`; (b) `crypto_exchange` `Tag="Futures fee"` sending `0,00010000` ETH from ByBit for `0,25` EUR at `2025-03-12 12:00:00 UTC`. All `TxHash`, `TxSrc`, `TxDest` empty (CEX-style; ByBit is CEX in the stub registry) |

`koinly_2025_other_gains_report.csv` is mandatory for this scenario:
the OGR rows are the production P&L carrier under DP-010/DP-012 Quadro 13
routing, and the loader's all-or-nothing validation requires OGR alongside
CG/Income/TH when any OGR row is present.

## Scenario and the test it backs

### Derivatives close (`Tag="Realized gain"` and `Tag="Futures fee"`)

- TH row (a): `crypto_withdrawal` at `2025-03-10 12:00:00 UTC`,
  `Tag="Realized gain"`, sending `0,00100000` ETH from `ByBit`,
  `TxHash=""`, `TxSrc=""`, `TxDest=""`. With the stub registry classifying
  the platform as `WalletKind.CEX` and the JSON-loaded
  `derivatives_tags={"Funding fee", "Futures fee", "Realized gain"}`
  injected via `TreatmentConfig`, the resolver matches `"realized gain"`
  against the derivatives set (Phase B Invariant 5/6) and returns
  `DERIVATIVES_CLOSE`.
- TH row (b): `crypto_exchange` at `2025-03-12 12:00:00 UTC`,
  `Tag="Futures fee"`, sending `0,00010000` ETH from `ByBit` for
  `0,25` EUR, `TxHash=""`, `TxSrc=""`, `TxDest=""`. Same stub and same
  injected config -> matches `"futures fee"` -> `DERIVATIVES_CLOSE`.
- OGR row (Profit) on key `(2025-03-10, ETH, ByBit)` with
  `Value (EUR) = 2,00`, `Type = Profit`.
- OGR row (Loss) on key `(2025-03-12, ETH, ByBit)` with
  `Value (EUR) = -0,05`, `Type = Loss`.

**Phase C property under test (Phase B Invariant 5/6):** both TH rows
resolve to `DERIVATIVES_CLOSE` ONLY when `derivatives_tags` is injected from
the production JSON; without injection the `"Realized gain"` row resolves to
`REWARD_AIRDROP_LP` (it falls into the reward-tag set) and the `"Futures fee"`
row resolves to `SPOT_DISPOSAL` (no special-tag match). The corpus verify
and the corpus test both confirm the divergence through the production
reader chain (`parse_th_row` -> `classify_platform` -> `build_transaction` ->
`resolve_treatment`).

**Treatment expectation:**

- Legacy intent for TH row (a) with injected JSON: `Tag="Realized gain"`,
  sending side populated, matches derivatives JSON set ->
  `DERIVATIVES_CLOSE`. (Without injection: matches reward literals ->
  `REWARD_AIRDROP_LP` - Phase B Invariant 6 precedence test.)
- Legacy intent for TH row (b) with injected JSON: `Tag="Futures fee"`,
  sending side populated, matches derivatives JSON set ->
  `DERIVATIVES_CLOSE`. (Without injection: no special tag ->
  `SPOT_DISPOSAL`.)
- Resolver under `TreatmentConfig(derivatives_tags=<loaded JSON>)`:
  `Treatment.DERIVATIVES_CLOSE` (a) and `Treatment.DERIVATIVES_CLOSE` (b).
- `treatment_agree`: `yes` for both rows when the JSON is injected (the
  corpus characterization test injects the JSON via the production loader).

- Backs: `tests/unit/application/test_phase_c_corpus.py::test_corpus_scenario[derivatives_close]`,
  the per-row `test_treatment_agrees_with_legacy_intent` cases for this
  scenario, and `test_derivatives_scenario_requires_injected_tags`.

## Synthetic-data invariant

Per Phase C Invariant 4: no real wallet addresses, no real tx hashes, no
amounts traceable to personal data. `TxHash`, `TxSrc`, and `TxDest` are
EMPTY (CEX-style; ByBit is CEX in the stub registry and the production
operator map, so the disposal resolves a valid WalletKind without a chain
id). `Sending Wallet` / `Receiving Wallet` / `Wallet Name` use only the
synthetic label `ByBit` (CEX stub entry, registered in the operator
platform map). Amounts (`0,00100000` ETH on the realized-gain close,
`0,00010000` ETH on the futures-fee settlement, 3/5 EUR and 0,30/0,25 EUR
on the paired CG rows, 2 EUR Profit and -0,05 EUR Loss on the OGR rows,
`0,01000000` EUROC cashback) are round synthetic values chosen to make the
derivatives-routing shape unambiguous and the Profit/Loss polarity obvious.
