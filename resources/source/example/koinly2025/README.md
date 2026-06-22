# Synthetic Koinly 2025 example - derivatives separation

Committed, fully synthetic Koinly export fixture that reproduces the derivatives
separation code paths (`separate_derivatives_reporting` + `use_other_gains_report`
+ the TH-label CG dedup in `application/crypto/derivatives_dedup.py`) without any
personal data. Backs `tests/end_to_end/test_crypto_derivatives_separation.py` and
the six real-data tests in `tests/unit/application/test_crypto_reporting.py`
(migrated by plan Tasks 3 and 6).

All four files use the `_synth.csv` filename token. `TxHash`, `TxSrc`, and `TxDest`
are empty for every Transaction History row. `Sending Wallet` / `Receiving Wallet`
use only the synthetic labels `Demo Spot` and `Demo Futures` (never real exchange
names).

## Files

| File | Mandatory | Purpose |
|------|-----------|---------|
| `koinly_2025_capital_gains_report_synth.csv` | yes | CG disposal lots |
| `koinly_2025_income_report_synth.csv` | yes | One synthetic reward row |
| `koinly_2025_transaction_history_synth.csv` | yes | Derivatives-label events + spot purchases |
| `koinly_2025_other_gains_report_synth.csv` | yes (OGR path) | Profit + Loss rows for the derivatives P&L split |

## Scenarios and the tests they back

### Case A - futures Profit + fee disposal separation (`2025-01-12`, USDT, Demo Futures)

- OGR `Profit` row `+140.18 EUR` and OGR `Loss` row `4.17 EUR` (proceeds).
- One CG fee-disposal lot: amount `4.27180510` USDT, cost `1.73`, proceeds `4.17`,
  gain `2.44`, with a matching TH `crypto_withdrawal` row carrying `Tag="Futures fee"`
  at `2025-01-12 15:22 UTC`.
- Flag ON: the `Profit` routes to `derivatives_entries` (+140.18 PROFIT); the dedup
  removes the `2.44 EUR` fee-disposal CG lot (TH-label exact match); the `-4.17`
  OGR `Loss` row reclassifies to Derivatives (cg_matches == 0 after dedup).
- Flag OFF (legacy): the direction override mixes Profit + fee into a single
  `136.01 EUR` Crypto Gains entry (140.18 + -4.17 = 136.01).
- Backs: `TestByBitCase1Trace`, `TestBackwardCompatTrace#test_flag_off_matches_golden_values`,
  and the Case-1 backward-compat guard in `test_crypto_reporting.py`.

### Case B - multi-lot contiguous-range fallback (`2025-01-13`, USDT, Demo Futures)

- One TH `Funding fee` event at `2025-01-13 08:00 UTC`, amount `0.50000000` USDT.
- One TH `Realized gain` event at `2025-01-13 13:01 UTC`, amount `5.00000000` USDT.
- Four CG lots at `(2025-01-13, USDT, Demo Futures)`:
  - exact-match lot: amount `0.50000000`, `Date Sold` `13/01/2025 08:00` (matches
    the Funding-fee event at `2025-01-13 08:00`).
  - three contiguous-range lots, all `Date Sold` `13/01/2025 13:01`, sorted by
    acquisition date `01/01`, `02/01`, `03/01`:
    - lot 1: amount `1.50000000`
    - lot 2: amount `1.50000000`
    - lot 3: amount `2.00002500`
- Three OGR `Loss` rows at `(2025-01-13, USDT, Demo Futures)` totalling `-8.00 EUR`
  (1.50 + 2.50 + 4.00).

**Load-bearing tolerance arithmetic** (Design Invariant #2):

```
range_size      = 3 lots
tolerance       = Decimal("0.00001") * range_size = Decimal("0.00003")
lot sum S       = 1.50000000 + 1.50000000 + 2.00002500 = Decimal("5.00002500")
TH Realized T   = Decimal("5.00000000")
delta |S - T|   = Decimal("0.00002500")
within tol?     0.00002500 <= 0.00003000  -> YES
exact equal?    5.00002500 != 5.00000000  -> NO (tolerance window is load-bearing)
```

A lot set summing exactly to `T` would defeat the test: phase-2 would match
without engaging the tolerance window. The `2.000025` lot guarantees the delta
falls strictly inside `(0, tolerance]`.

- Phase 1 exact match consumes the `0.50000000` Funding-fee lot (1 removal).
- Phase 2 contiguous-range consumes the three remaining lots as one window
  (3 removals). Exactly 3 lots survive into phase-2 (>= 3 required).
- All 4 Case B CG lots are removed, so the three OGR `Loss` rows see cg_matches == 0
  and classify as clean Derivatives (-8.00 EUR total).
- No residual lot's `amount_6dp` collides with another derivatives-event amount at
  the same `(timestamp, asset, wallet)`: range-lot 6dp keys are `1.500000`,
  `1.500000`, `2.000025`; derivatives-event amounts at the same key are
  `0.500000` (Funding fee) and `5.000000` (Realized gain) - no collision.
- Backs: `TestByBitCase2Trace` (including `test_derivatives_lots_removed`,
  asserting exact=1 + range=3 = 4 removals for Case B).

### Case C - derivatives-label CG dedup (`2025-01-24`, USDT, Demo Futures)

- Three TH derivatives events: `Funding fee` `0.08838575` USDT at `20:00`,
  `Futures fee` `0.41424953` USDT at `23:40`, `Realized gain` `40.75540000` USDT
  at `23:40`.
- Three CG lots with matching amounts/proceeds (all gain 0.00).
- Three OGR `Loss` rows totalling `-39.62 EUR` (0.08 + 0.40 + 39.14).
- Flag ON: all three CG lots removed by exact-match dedup; the three OGR `Loss`
  rows classify as clean Derivatives (-39.62 EUR, review_required=False).
- Backs: `TestByBitCase3Trace`, `TestPipelineIntegration#test_ogr_classifies_clean_after_dedup`.

### Preserved non-derivatives spot entries (`2025-03-10`, Demo Spot)

- BTC disposal: amount `0.00500000`, cost `10.00`, proceeds `12.00`, gain `2.00`.
- ETH disposal: amount `0.00300000`, cost `6.00`, proceeds `9.50`, gain `3.50`.
- Both have no derivatives label in TH and `|gain| >= 1 EUR`, so they survive the
  materiality filter and the dedup unchanged in both flag-on and flag-off paths.
- These replace the volatile `2025-01-26 SOL ByBit` entry that broke under the
  "Transfer fees" Koinly toggle.
- Backs: `TestByBitCase2Trace#test_spot_exchange_lots_preserved`.

## Pipeline behaviour (worked example, flag ON)

```
Dedup summary: removed 8 lots (exact=5, range=3)
  Case A: 1 exact (Futures fee)
  Case B: 1 exact (Funding fee) + 3 range (Realized gain)
  Case C: 3 exact (Funding fee + Futures fee + Realized gain)
capital_entries: 2 preserved spot entries (BTC +2.00, ETH +3.50)
derivatives_entries:
  (2025-01-12, USDT, Demo Futures) LOSS -4.17, PROFIT +140.18
  (2025-01-13, USDT, Demo Futures) LOSS -8.00
  (2025-01-24, USDT, Demo Futures) LOSS -39.62
```

The `Demo Spot` / `Demo Futures` wallets are deliberately NOT in the operator
platform map, so `operator_country` resolves to the `UNKNOWN` sentinel and the
rows carry `review_required=True`. `TestDerivativesE2E#test_derivatives_rows_operator_country_is_valid_or_unknown`
covers this structural property (`UNKNOWN` is a valid sentinel, and `UNKNOWN`
rows surface `YES:` in the Review column).
