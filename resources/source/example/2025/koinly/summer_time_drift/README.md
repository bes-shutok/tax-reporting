# Synthetic Koinly 2025 example - summer-time drift

Committed, fully synthetic Koinly export fixture that reproduces RFC weakness
#3 (timezone drift in the summer 00:00-01:00 local window) from the
TH-anchored Transaction state machine rollout
(`docs/history/feature-notes/2026-06-20-th-anchored-transaction-state-machine.md`).
A single disposal recorded at `15/07/2025 00:30` WEST (mainland-Portugal
summer time, UTC+1) corresponds to the UTC instant `2025-07-14T23:30:00Z`.
Under the legacy `(local_date, asset, wallet)` join, the CG row's local
calendar day is `2025-07-15` while the TH twin's UTC calendar day is
`2025-07-14` - the one-day drift the timezone fix was added to close.

Backs `tests/unit/application/test_phase_c_corpus.py::test_corpus_scenario[summer_time_drift]`
and `test_phase_c_corpus.py::test_summer_time_drift_uses_utc_instant`.

## Timezone fix in scope

The fix landed in the crypto-timezone-normalization plan
(`docs/history/plans/completed/2026-06-20-crypto-timezone-normalization.md`):
Koinly naive dates (CG `Date Sold`, OGR `Date`, Income `Date`) are
interpreted as the jurisdiction IANA zone (default `Europe/Lisbon` for PT)
and converted to UTC via `zoneinfo`, which owns DST transitions
historically. TH dates declare UTC via the format literal (`YYYY-MM-DD
HH:MM:SS UTC`) and are kept as-is. This scenario confirms the new typed
path's composite correlation key uses the UTC **instant**
(`2025-07-14T23:30:00Z`), NOT the local calendar day (`2025-07-15`). The
corpus test asserts this by inspecting `TxCorrelationKey.composite`.

## Files

| File | Mandatory | Purpose |
|------|-----------|---------|
| `koinly_2025_capital_gains_report.csv` | yes | One ETH disposal on `(2025-07-15 local = 2025-07-14 UTC, ETH, Kraken)` with `proceeds=300, cost=200 EUR` (summer-midnight drift shape) |
| `koinly_2025_income_report.csv` | yes | One synthetic cashback row (loader's all-or-nothing validation) |
| `koinly_2025_transaction_history.csv` | yes | A `crypto_withdrawal` of `1,00000000` ETH from `Kraken` at `2025-07-14 23:30:00 UTC`, `Tag=""`, with the placeholder `TxHash` |

No `koinly_2025_other_gains_report.csv` is shipped: OGR is optional
for this scenario (loader's all-or-nothing validation only requires
CG/Income/TH; the absence of an OGR file is permitted).

## Scenario and the test it backs

### Summer-time drift (`15/07/2025 00:30` WEST = `2025-07-14 23:30:00` UTC)

- TH `crypto_withdrawal` row at `2025-07-14 23:30:00 UTC`, `Tag=""`,
  sending `1,00000000` ETH from `Kraken` with `TxHash =
  synth-txhash-summer-drift-001` (synthetic identifier; not a real hash
  shape).
- CG has ONE row whose `Date Sold = 15/07/2025 00:30` (WEST summer time,
  UTC+1). Pre-fix the parser stamped the naive instant as UTC
  (`2025-07-15 00:30 UTC`); post-fix the parser localizes to
  `Europe/Lisbon` and converts to `2025-07-14 23:30 UTC`, matching the TH
  twin. `proceeds = 300,00`, `cost = 200,00`, `gain = 100,00`.

**Phase C property under test (RFC weakness #3):** the legacy per-key
join sees local_date `2025-07-15` for the CG row and UTC day `2025-07-14`
for the TH row - a one-day drift that silently misses the cross-report
twin. The new typed path's composite correlation key uses the UTC
**instant** (`2025-07-14T23:30:00Z`), so the TH row and the (post-fix)
localized CG row carry the same UTC instant (the join that consumes both
is Phase D work). The corpus test asserts BOTH halves of the fix: the TH
row's composite key embeds `2025-07-14T23:30` (NOT `2025-07-15`), AND
the CG row's naive `Date Sold` is localized by invoking the production
CG-date parsing function directly
(`_parse_capital_gains_file(cg_path, CapitalGainsParsingContext(zone=ZoneInfo("Europe/Lisbon")))`
from `crypto_reporting.py`), asserting the parsed CG entry's
`disposal_timestamp` equals that same UTC instant. Invoking the
production function (rather than calling `parse_koinly_datetime` with a
test-supplied zone) is load-bearing: it routes through the production
`zone=context.zone` wiring on line 557, so a regression that drops that
kwarg makes the assertion fail.

**Treatment expectation:**

- Legacy intent for the TH row: `Tag=""`, sending side populated, no
  loan/derivatives/reward tag -> `SPOT_DISPOSAL`.
- Resolver: `Treatment.SPOT_DISPOSAL`.
- `treatment_agree`: `yes`.

- Backs: `tests/unit/application/test_phase_c_corpus.py::test_corpus_scenario[summer_time_drift]`,
  the per-row `test_treatment_agrees_with_legacy_intent` case for this
  scenario, and
  `test_phase_c_corpus.py::test_summer_time_drift_uses_utc_instant`.

## Synthetic-data invariant

Per Phase C Invariant 4: no real wallet addresses, no real tx hashes, no
amounts traceable to personal data. `TxHash` is the synthetic identifier
`synth-txhash-summer-drift-001` (not a `0x`-prefixed hex string; passes
the `test_no_real_data_in_fixtures` regex
`(0x[0-9a-fA-F]{40,})|([0-9a-fA-F]{64})` because it contains neither a
`0x` + 40+ hex prefix nor a 64-hex run). `TxSrc` and `TxDest` are empty.
`Sending Wallet` / `Wallet Name` use only the synthetic label `Kraken`
(registered in the operator platform map, so the disposal resolves a
valid country instead of `UNKNOWN`). Amounts (1.0 ETH, 200 EUR cost, 300
EUR proceeds) are round synthetic values chosen to make the drift shape
unambiguous.
