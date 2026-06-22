# Plan: Migrate crypto e2e/unit tests off local Koinly fixtures to committed synthetic example data

Plan review: `docs/history/reviews/2026-06-22-plan-review-crypto-tests-off-local-fixtures-r4.md` (latest, ready) · `docs/history/reviews/2026-06-22-plan-review-crypto-tests-off-local-fixtures-r3.md` (r3) · `docs/history/reviews/2026-06-22-plan-review-crypto-tests-off-local-fixtures-r2.md` (r2)

Related (prerequisite) plan: `docs/history/plans/2026-06-21-crypto-payment-proceeds-refactor.md` (review-approved, r4) - its remaining tasks unblock the suite this plan depends on.
Review source for the immediate breakage: the "Transfer fees" decision, commit `3a53e7e` (2026-06-22 10:18), documented in `docs/history/feature-notes/2026-06-21-transfer-fees-tax-treatment-proposal.md`.

## Terms

- **Local fixture dependence** - a test reads the gitignored, user-specific `resources/source/koinly2025/` export and `pytest.skip`s when it is absent. Such tests are inert in CI and break whenever the user re-exports Koinly with different settings.
- **Golden value** - an exact numeric assertion (e.g. `Decimal("136.01")`) derived from a specific fixture. Migrating off a fixture means recomputing these against the new committed synthetic data.
- **Data-trace test** - a test that grounds its assertions in source CSV contents (via `_assert_csv_contains_value` or direct CSV reads) rather than internal pipeline constants, so a fixture change surfaces as a clear failure.
- **Derivatives separation** - the `separate_derivatives_reporting` flag that splits ByBit futures fee/funding/realized-gain disposals (art. 10(1)(e)) out of Crypto Gains into a Derivatives P&L sheet, plus the TH-label CG dedup (`application/crypto/derivatives_dedup.py`).
- **OGR** - Koinly "Other Gains Report". Optional 4th file (loaded only when `use_other_gains_report=True`); required by the derivatives and payment-proceeds scenarios.

## Gist & Examples

**What changes:** ~31 crypto tests across four files (`test_crypto_derivatives_separation.py` ~20, `test_crypto_zero_basis_materiality.py` 3, `test_crypto_payment_proceeds.py` 2, `test_crypto_reporting.py` 6) currently read the gitignored `resources/source/koinly2025/` and `pytest.skip` when it is absent. They are migrated to read new **committed, isolated, and fully synthetic** example exports under `resources/source/example/` (`koinly2025/` for derivatives, `koinly2025_zero_basis/` for zero-basis materiality, and `koinly2025_payment/` for payment-proceeds). All golden values are recomputed against these synthetic fixtures. No production code changes behavior.

**Why needed:** Two failures exposed the fragility. (1) `TestByBitCase2Trace#test_spot_exchange_lots_preserved` broke because it hardcoded a `2025-01-26 SOL ByBit` entry (gain `1.95`) that vanished after the "Transfer fees" Koinly toggle (`Realize gains on transfer fees?` -> OFF) re-rendered it as gain `0.0` / "Missing cost basis" - dropped by the materiality filter. (2) These tests are inert in any environment without the user's personal export, so they verify nothing in CI and silently rot between re-exports. The repo already has the deterministic pattern (`resources/source/example/koinly2024/` + `test_example_report_generation.py`); this plan extends it to the scenarios those tests need.

**Example - before (test reads personal data):**
```python
_FIXTURE_DIR = Path("resources/source/koinly2025")   # gitignored; skips in CI
...
assert case1_matches[0].gain_loss_eur == Decimal("136.01")  # value from personal export
```

**Example - after (test reads committed synthetic data):**
```python
_FIXTURE_DIR = Path("resources/source/example/koinly2025")  # committed; always present
...
# golden value recomputed from the synthetic fixture (e.g. 130.00), pinned as the new contract
assert case1_matches[0].gain_loss_eur == Decimal("<recomputed>")
```

**Edge cases handled:**
- The derivatives cases hinge on multi-lot arithmetic (Case 2's contiguous-range fallback matching N lots against a TH "Realized gain" within tolerance). The synthetic fixture reproduces the *logic* with a smaller, controlled lot set; the asserted lot counts and totals change to the synthetic-derived values, but the dedup *phases* (exact-match then contiguous-range) are still exercised.
- The `test_real_koinly_fixture_has_no_duplicate_aggregation_keys` characterization test currently asserts a property of the personal fixture; migrated, it asserts the same property of the synthetic fixture.
- OGR is optional in the loader; the synthetic dir must still ship an OGR CSV so the derivatives/payment tests (which set `use_other_gains_report=True`) have data to consume.

## Evaluation Criteria

**Quality dimensions:**

- **No local-fixture dependence (primary):** after migration, `grep -rn "koinly2025" tests/` returns nothing except for documented allowlist matches (e.g. tmp_path test directories or resolved.name assertions), and the full suite is GREEN with `resources/source/koinly2025/` temporarily moved aside (proves nothing reads personal data and nothing `skip`s for its absence). The `mv ...aside` run is the authoritative gate.
- **Scenario coverage preserved:** the migrated tests still exercise the derivatives dedup phases (exact + contiguous-range), the zero-basis materiality gate (fee-token / small-reward / large-zero-cost / backward-compat), the payment-proceeds correction (on/off), and the duplicate-aggregation-key invariant. The code paths remain covered; only the data source and the exact pinned numbers change.
- **Synthetic-data hygiene:** the new `example/` files use synthetic wallet names and account tokens (no personal identifiers); an explicit hygiene assertion covers them alongside the existing `test_example_data_is_synthetic` by scanning cell contents to verify `TxHash` is empty for all transaction history rows, ensuring filenames end in `_synth.csv`, and validating that sending/receiving wallets are within a synthetic allowlist.
- **Data-trace integrity:** migrated tests keep grounding their assertions in the committed CSV contents (`_assert_csv_contains_value` / direct reads), so a synthetic-fixture edit surfaces a clear failure, not a silent number change.
- **No production behavior change:** production code under `src/` is untouched by this plan.

**Release gates:**
- `uv run pytest` full suite GREEN with `resources/source/koinly2025/` moved aside (using safe trap/finally restore).
- `uv run ruff check src/ tests/` clean.
- `grep -rn "koinly2025" tests/` is empty except for allowlisted items.
- Synthetic-hygiene assertions pass.

## Review Scope

**Explicit must-fix** - findings on these paths are always in scope (review and fix if valid):

**Production code:**
- (none - this plan changes tests and committed example data only)

**Committed example data (new):**
- `resources/source/example/koinly2025/koinly_2025_capital_gains_report_*.csv` *(new)*
- `resources/source/example/koinly2025/koinly_2025_income_report_*.csv` *(new)*
- `resources/source/example/koinly2025/koinly_2025_transaction_history_*.csv` *(new)*
- `resources/source/example/koinly2025/koinly_2025_other_gains_report_*.csv` *(new)*
- `resources/source/example/koinly2025/README.md` *(new)*
- `resources/source/example/koinly2025_zero_basis/koinly_2025_capital_gains_report_*.csv` *(new)*
- `resources/source/example/koinly2025_zero_basis/koinly_2025_income_report_*.csv` *(new)*
- `resources/source/example/koinly2025_zero_basis/koinly_2025_transaction_history_*.csv` *(new)*
- `resources/source/example/koinly2025_zero_basis/README.md` *(new)*
- `resources/source/example/koinly2025_payment/koinly_2025_capital_gains_report_*.csv` *(new)*
- `resources/source/example/koinly2025_payment/koinly_2025_income_report_*.csv` *(new)*
- `resources/source/example/koinly2025_payment/koinly_2025_transaction_history_*.csv` *(new)*
- `resources/source/example/koinly2025_payment/README.md` *(new)*

**Tests:**
- `tests/conftest.py` (for the shared `KOINLY_2025_*_DIR` paths and `build_koinly_jurisdiction` helper extraction)
- `tests/end_to_end/test_crypto_derivatives_separation.py`
- `tests/end_to_end/test_crypto_zero_basis_materiality.py`
- `tests/end_to_end/test_crypto_payment_proceeds.py`
- `tests/unit/application/test_crypto_reporting.py`
- `tests/end_to_end/test_example_report_generation.py` (synthetic-hygiene assertion extension)

**Plan-related extension** - implementation/review may also touch:
- `docs/maintenance/crypto_implementation_guidelines.md` (to update the renamed Aggregation Keys test reference)
- `CLAUDE.md` (to codify the regression prevention rule)
- `.gitignore` is **not** changed.

**Out of scope - reject unless plan-related:**
- `src/tax_reporting/**` production code - behavior is unchanged; the refactor (separate plan) owns production edits.
- `tests/unit/infrastructure/test_text_sanitize.py` and the JSON-loader extraction - owned by the prerequisite refactor plan.

## Design Invariants (CR Guard)

1. **Synthesis, not sanitization.** The committed example data is authored synthetic (fabricated wallets, tickers, amounts) - never a redacted copy of the personal export. This honors the existing `test_example_data_is_synthetic` hygiene contract and the repo's personal-data-hygiene rule. Real account tokens, real wallet names, and real transaction hashes must not appear. The synthetic `TxHash`, `TxSrc`, and `TxDest` columns must be empty for every row. `Sending Wallet`/`Receiving Wallet` must use only `Demo Spot`/`Demo Futures`/`Demo Payment` labels, never real exchange names. The filename token must be a single fixed, obviously-synthetic token (e.g. `synth`), not a 10-char mixed-case-alphanumeric string.
2. **Scenario logic preserved over exact values.** The synthetic fixtures must trigger the same *code paths and data shapes* (derivatives TH labels, multi-lot contiguous-range summation within tolerance, zero-basis rows, Payment-tagged zero-net-value disposals). Pinned golden values must be recomputed by independent CSV arithmetic (summing OGR rows, CG lots, and calculating gain = proceeds - cost), never copied from pipeline output, and the worked arithmetic must be recorded in the test docstring or comment. For Case B, the synthetic contiguous-range lots must sum within tolerance but NOT exactly equal the TH Realized gain (off by ~1e-6 to 1e-5) so the tolerance window is load-bearing; a lot set that sums exactly defeats the test.
3. **Tests stay data-trace.** Migrated tests continue to ground assertions in the committed CSV via `_assert_csv_contains_value` / direct reads. A future edit to the synthetic CSV must fail loudly at the data-trace check, not drift silently.
4. **Required-files contract honored.** The synthetic dirs ship the 3 mandatory files (`capital_gains_report`, `income_report`, `transaction_history`) plus the optional OGR where needed, so the all-or-nothing loader validation passes.
5. **No production behavior change.** This plan edits only `tests/` and `resources/source/example/`. Any test failure that seems to require a production fix is a signal to stop and reconsider, not an excuse to change `src/`.
6. **No new personal-data dependence introduced.** Nothing under `tests/` may regain a `koinly2025` reference except for documented allowlist entries (e.g. `tmp_path` synthetic tests or assertions verifying `resolved.name == "koinly2025"`). The `mv ...aside` full-suite run is the authoritative gate; the `koinly2025` grep is a quick sanity check.
7. **Required-files asymmetry.** `example/koinly2024/` ships 3 files (no-OGR path); `example/koinly2025/` ships 4 (OGR path) - intentional, do not normalize.
8. **Decoupled scenarios.** To prevent test fragility and shared fixture pollution, the derivatives separation, zero-basis materiality, and payment-proceeds scenarios are kept in three isolated directories under `resources/source/example/`.

## Validation Commands

```bash
# Prerequisite: suite collects and runs (refactor plan Tasks 2-10 done)
uv run pytest --tb=line -q 2>&1 | tail -15

# Per migrated file, as each task completes
uv run pytest tests/end_to_end/test_crypto_derivatives_separation.py -v
uv run pytest tests/end_to_end/test_crypto_zero_basis_materiality.py -v
uv run pytest tests/end_to_end/test_crypto_payment_proceeds.py -v
uv run pytest tests/unit/application/test_crypto_reporting.py -v

# No local-fixture references in tests (excluding allowlisted tmp_path / name checks)
grep -rn "koinly2025" tests/ && echo "STRAY REFERENCES MAY EXIST" || echo "clean"

# Proves no test reads or skips-on the personal export: move it aside with safe trap and pre-check
[ -e resources/source/koinly2025.aside ] && { echo "abort: aside already exists"; exit 1; }
trap 'mv resources/source/koinly2025.aside resources/source/koinly2025 2>/dev/null || true' EXIT INT TERM
mv resources/source/koinly2025 resources/source/koinly2025.aside
uv run pytest -q; STATUS=$?
mv resources/source/koinly2025.aside resources/source/koinly2025
test $STATUS -eq 0 && echo "no local-data dependence" || echo "DEPENDENCE REMAINS"

# Synthetic hygiene (positive validation: filename suffix, empty sensitive columns, wallet allowlist)
uv run pytest tests/end_to_end/test_example_report_generation.py::test_example_data_is_synthetic -v

# Positive filename check: all Koinly CSVs in example dirs must end in _synth.csv or _example.csv
# (Fails closed: absent dir or no CSVs is a pre-condition error, not "clean")
_synth_count=$(find resources/source/example/ -name "koinly_*.csv" 2>/dev/null | wc -l | tr -d ' ')
[ "$_synth_count" -eq 0 ] && { echo "PRECHECK FAILED: no koinly CSVs found in example/"; exit 1; }
find resources/source/example/ -name "koinly_*.csv" | grep -v -E "(_synth\.csv|_example\.csv)$" && echo "BAD FILENAME TOKEN" || echo "filename tokens ok ($_synth_count files checked)"

# Lint
uv run ruff check src/ tests/
```

## Monitor

### 1. Format-Drift Blindspot
- **Risk:** Stale synthetic data tests in CI might false-pass if Koinly changes its CSV output formats in the future.
- **Observability:** Track Koinly format changes by running the pipeline manually against new exports periodically using the tool's standard load command. The generation/maintenance workflow for example data templates is documented under `docs/maintenance/crypto_implementation_guidelines.md`.

### Task 0: Unblock the suite - finish the prerequisite refactor plan (prerequisite)

Files: owned entirely by `docs/history/plans/2026-06-21-crypto-payment-proceeds-refactor.md` (Tasks 2-10).

- [x] Execute Tasks 2-10 of the review-approved refactor plan on the current branch (`2026-06-21-crypto-payment-proceeds-refactor`): create `src/tax_reporting/infrastructure/text_sanitize.py` + `json_loader.py`, route the three callers (`payment_proceeds`, `derivatives_dedup`, `classification`), add characterization tests, lint, docs sync.
- [x] Run -> expect GREEN collection (no `ModuleNotFoundError`): `uv run pytest --co -q 2>&1 | tail -5` then `uv run pytest --tb=line -q 2>&1 | tail -15` (the suite now runs; only `test_spot_exchange_lots_preserved` should still fail - it is fixed in Task 3).
- [x] This task is tracked by the refactor plan, not here; it is listed only because every later task needs a runnable suite to verify. Do not duplicate its subtasks in this file.

### Task 1: Author the committed synthetic `koinly2025` example fixtures

Files:
- `resources/source/example/koinly2025/koinly_2025_capital_gains_report_synth.csv` *(new)*
- `resources/source/example/koinly2025/koinly_2025_income_report_synth.csv` *(new)*
- `resources/source/example/koinly2025/koinly_2025_transaction_history_synth.csv` *(new)*
- `resources/source/example/koinly2025/koinly_2025_other_gains_report_synth.csv` *(new)*
- `resources/source/example/koinly2025/README.md` *(new)*
- `resources/source/example/koinly2025_zero_basis/koinly_2025_capital_gains_report_synth.csv` *(new)*
- `resources/source/example/koinly2025_zero_basis/koinly_2025_income_report_synth.csv` *(new)*
- `resources/source/example/koinly2025_zero_basis/koinly_2025_transaction_history_synth.csv` *(new)*
- `resources/source/example/koinly2025_zero_basis/README.md` *(new)*
- `resources/source/example/koinly2025_payment/koinly_2025_capital_gains_report_synth.csv` *(new)*
- `resources/source/example/koinly2025_payment/koinly_2025_income_report_synth.csv` *(new)*
- `resources/source/example/koinly2025_payment/koinly_2025_transaction_history_synth.csv` *(new)*
- `resources/source/example/koinly2025_payment/README.md` *(new)*

Design the CSV files using the single fixed synthetic token `synth` in all filenames, with `TxHash`, `TxSrc`, `TxDest` columns empty for all rows, and `Sending Wallet`/`Receiving Wallet` using only `Demo Spot`/`Demo Futures`/`Demo Payment` (or `Wirex` for EUROC) labels:

- [x] **Derivatives Separation Fixtures (`example/koinly2025/`):**
  - **Derivatives Case A (spot fee disposal + profit):** one OGR Profit row and one CG fee-disposal lot whose TH event carries `Tag="Futures fee"`. With separation on, the profit routes to derivatives P&L and the fee lot is removed by the TH-label dedup; with separation off, the legacy path mixes them into one Crypto Gains entry.
  - **Derivatives Case B (multi-lot contiguous range):** several OGR Loss rows plus a set of CG lots at one timestamp where (i) one lot exact-matches a TH `Funding fee`/`Futures fee` event and (ii) the remaining lots form a contiguous range (by acquisition date) summing within `Decimal("0.00001") * range_size` of a TH `Realized gain` event.
    - Require >= 3 lots surviving into phase-2.
    - Ensure no residual lot's `amount_6dp` collides with any other derivatives-event amount at the same `(timestamp, asset, wallet)`.
    - Contiguous-range lots must sum within tolerance but NOT exactly equal the TH Realized gain (off by ~1e-6 to 1e-5) so the tolerance window is load-bearing.
  - **Derivatives Case C (derivatives-label CG dedup):** CG lots whose TH events carry derivatives labels (any of `Funding fee` / `Futures fee` / `Realized gain`) plus matching OGR Loss rows; the dedup removes the CG lots so the disposal reports once in Derivatives P&L.
  - **Preserved non-derivatives spot entries (prevent fake test):** at least two CG entries whose TH has no derivatives label on a *different* date from the cases above, both with `|gain| >= 1 EUR` so they survive the materiality filter (replaces the volatile `2025-01-26 SOL ByBit` entry).
  - **Manifest file:** Create `resources/source/example/koinly2025/README.md` listing each scenario and the tests it backs.
- [x] **Zero-Basis Fixtures (`example/koinly2025_zero_basis/`):**
  - **Zero-basis materiality rows:** (a) a fee-token disposal (not flagged), (b) a small-reward disposal with `0 < proceeds < min_proceeds` (not flagged), (c) a larger zero-cost disposal above the threshold (flagged). Sufficient for Task 4's gates.
  - **Manifest file:** Create `resources/source/example/koinly2025_zero_basis/README.md` listing zero-basis test cases.
- [x] **Payment Proceeds Fixtures (`example/koinly2025_payment/`):**
  - **Payment-proceeds case:** a `Payment`-tagged TH disposal with `Net Value (EUR) == 0` plus a matching CG disposal of an EUR-pegged stablecoin (reusing existing `EUROC`, NOT `DEUROC`) with `proceeds=0, cost>0`.
  - **Manifest file:** Create `resources/source/example/koinly2025_payment/README.md` listing payment-proceeds scenarios.
- [x] Verify the synthetic dirs load cleanly: `uv run python -c "from tax_reporting.application.crypto_reporting import load_koinly_crypto_report; from tax_reporting.infrastructure.config import TaxJurisdictionConfig; from decimal import Decimal; assert load_koinly_crypto_report(__import__('pathlib').Path('resources/source/example/koinly2025'), jurisdiction=TaxJurisdictionConfig(country='PT', fiscal_year=2025, exclude_loan_repayment_gains=True, futures_derivatives_taxable=True, use_other_gains_report=True, separate_derivatives_reporting=True, infer_payment_proceeds=False, zero_basis_review_threshold=Decimal('50'), zero_basis_review_min_proceeds=Decimal('10'))) is not None"`

### Task 1.5: Assert shape-parity between real and synthetic fixtures

Verify that the synthetic fixture has shape parity with the real fixture before recomputing golden values.

- [x] Write a temporary test (or run a script) that loads both the real `resources/source/koinly2025/` and synthetic `resources/source/example/koinly2025/` under identical configs, asserting:
  - Identical derivatives_entries and capital_entries counts per `(date, asset, platform)` case key.
  - At least one lot removed via exact-match phase AND at least one via contiguous-range phase against the synthetic fixture (verify via logs or temporary assertion).
- [x] Ensure that this shape-parity comparison is clean before proceeding with golden value update.

### Task 2: Extend synthetic-data hygiene to the new examples

Files:
- `tests/end_to_end/test_example_report_generation.py`

- [x] `test_example_data_is_synthetic` (extend) - given the new `example/` CSVs, expects they contain only synthetic wallet/token markers and contain none of the real account tokens/wallet names from the personal export.
  - **Filename constraint:** Enforce that Koinly CSV filenames under the example directory strictly use the suffix `_synth.csv` or `_example.csv`.
  - **Sensitive columns check:** Validate that columns containing potentially sensitive blockchain/personal details (`TxHash`, `TxSrc`, `TxDest`) are completely empty (empty string) for all rows in the synthetic CSVs.
  - **Wallet allowlist check:** Validate that `Sending Wallet` and `Receiving Wallet` only contain allowed values matching a small synthetic allowlist (e.g. `Demo Spot`, `Demo Futures`, `Demo Payment`, `Wirex` or empty).
- [x] Run -> expect GREEN: `uv run pytest tests/end_to_end/test_example_report_generation.py::test_example_data_is_synthetic -v`

### Task 3: Extract DRY fixture helpers and migrate `test_crypto_derivatives_separation.py`

Files:
- `tests/conftest.py`
- `tests/end_to_end/test_crypto_derivatives_separation.py`

- [x] **DRY Extraction:** Define the shared directories `KOINLY_2025_EXAMPLE_DIR = Path("resources/source/example/koinly2025")`, `KOINLY_2025_ZERO_BASIS_EXAMPLE_DIR = Path("resources/source/example/koinly2025_zero_basis")`, and `KOINLY_2025_PAYMENT_EXAMPLE_DIR = Path("resources/source/example/koinly2025_payment")` in `tests/conftest.py` along with a shared `build_koinly_jurisdiction(**overrides)` factory helper to consolidate `_build_jurisdiction` duplicates.
- [x] Repoint `_FIXTURE_DIR` reference to `KOINLY_2025_EXAMPLE_DIR`. Remove local `_skip_if_fixtures_missing` helper.
- [x] Add `test_synthetic_fixture_contains_derivatives_scenarios` to parse the example CSV and assert derivatives rows are present, failing loudly if absent (guards against fixture content drift).
- [x] Recompute every golden value against the synthetic fixture and update assertions: Case A profit/fee totals, Case C total, the backward-compat mixed values, and the derivatives-totals-match-OGR-net check.
  - Require each recomputed golden value to be derived by independent CSV calculations (summing OGR rows, CG lots, etc.) and record the arithmetic in the test comments.
- [x] For Case B, assert that the range match-type removal count is >= 2 (proves phase-2 is load-bearing) and that the recomputed losses sum within tolerance. Observe via `caplog` (the dedup logs match-type per removal) or a `removal_reason` field if exposed on the returned removed-lot entries; at least 2 removals must show `contiguous_range` in the log/field.
- [x] `TestByBitCase2Trace#test_spot_exchange_lots_preserved` - given the synthetic preserved non-derivatives entries from Task 1, expects they survive the dedup identically in flag-on and flag-off:
  - Assert BOTH survive in flag-on and flag-off with identical gains.
  - Assert the count of non-derivatives entries is unchanged between paths (`count_on == count_off == 2`).
- [x] Gate re-runnability of any remaining real-fixture characterization tests as `skipif(not real_fixture_exists)` (or move them to a separate skip block).
- [x] Run -> expect GREEN: `uv run pytest tests/end_to_end/test_crypto_derivatives_separation.py -v`

### Task 4: Migrate `test_crypto_zero_basis_materiality.py` off the local fixture

Files:
- `tests/end_to_end/test_crypto_zero_basis_materiality.py`

- [x] Repoint local dir references to `KOINLY_2025_ZERO_BASIS_EXAMPLE_DIR` and replace local jurisdiction setup with `build_koinly_jurisdiction`.
- [x] Add `test_synthetic_fixture_contains_zero_basis_scenarios` to parse the example CSV and assert zero-basis scenario presence, failing loudly on empty sets.
- [x] Recompute assertions in the three real-data tests (`test_fee_token_disposals_not_flagged`, `test_small_reward_disposals_below_threshold_not_flagged`, `test_backward_compat_min_proceeds_zero_flags_all`) against the synthetic zero-basis rows (derived via independent CSV arithmetic).
- [x] Drop the now-unreachable `pytest.skip("No zero-cost entries ...")` branches.
- [x] Run -> expect GREEN: `uv run pytest tests/end_to_end/test_crypto_zero_basis_materiality.py -v`

### Task 5: Migrate `test_crypto_payment_proceeds.py` off the local fixture

Files:
- `tests/end_to_end/test_crypto_payment_proceeds.py`

- [x] Repoint local dir references to `KOINLY_2025_PAYMENT_EXAMPLE_DIR` and replace local jurisdiction setup with `build_koinly_jurisdiction`.
- [x] Add `test_synthetic_fixture_contains_payment_scenarios` to parse the example CSV and assert payment scenario presence, failing loudly if absent.
- [x] Repoint `_require_payment_pair` to resolve the synthetic `Payment`-tagged TH row and CG disposal (reusing existing `EUROC`, no `popular_crypto_tokens.json` extension needed).
- [x] `TestPaymentProceedsE2E#test_payment_row_not_carrying_phantom_full_cost_loss` - given the synthetic Payment disposal, expects no surviving phantom full-cost-loss capital entry and a `CryptoReviewEntry` audit row whose reason mentions "proceeds".
- [x] `TestPaymentProceedsE2E#test_no_correction_when_flag_off_preserves_phantom_loss` - given `infer_payment_proceeds=False`, expects the phantom loss survives unchanged.
- [x] Run -> expect GREEN: `uv run pytest tests/end_to_end/test_crypto_payment_proceeds.py -v`

### Task 6: Migrate the six real-data tests in `test_crypto_reporting.py`

Files:
- `tests/unit/application/test_crypto_reporting.py`
- `docs/maintenance/crypto_implementation_guidelines.md`

- [x] Repoint the six `Path("resources/source/koinly2025")` references to `KOINLY_2025_EXAMPLE_DIR`; recompute golden values against synthetic data using independent CSV calculations.
- [x] `test_real_koinly_fixture_has_no_duplicate_aggregation_keys` - rename to `test_example_fixture_has_no_duplicate_aggregation_keys` and assert the no-duplicate-keys property against the example data.
- [x] Update `docs/maintenance/crypto_implementation_guidelines.md` line ~624 guard table: replace `test_real_koinly_fixture_has_no_duplicate_aggregation_keys` with `test_example_fixture_has_no_duplicate_aggregation_keys` and update description to refer to "Committed example koinly2025 fixture".
- [x] Backward compatibility assertion check:
  - Consolidate ONLY the two flag-on absence assertions (redundant copies).
  - **Forbid deleting the flag-off positive assertion.** `test_derivatives_entries_empty_when_flag_off` and its legacy 136.01/-26.64 assertions (recomputed against synthetic data) MUST survive as the sole positive backward-compatibility guard. Do not delete it.
- [x] Run -> expect GREEN: `uv run pytest tests/unit/application/test_crypto_reporting.py -v`

### Task 7: Verify zero local-data dependence and full suite green

Files: (verification only; no edits unless a stray reference is found)

- [x] Run the tightened check: `grep -rn "koinly2025" tests/` returns nothing except allowed test-only files or documented names.
- [x] Move the personal export aside, run the full suite, confirm GREEN with zero skips for missing fixtures, then restore:
  ```bash
  [ -e resources/source/koinly2025.aside ] && { echo "abort: aside already exists"; exit 1; }
  trap 'mv resources/source/koinly2025.aside resources/source/koinly2025 2>/dev/null || true' EXIT INT TERM
  mv resources/source/koinly2025 resources/source/koinly2025.aside
  uv run pytest -q; STATUS=$?
  mv resources/source/koinly2025.aside resources/source/koinly2025
  test $STATUS -eq 0 && echo "no local-data dependence" || echo "DEPENDENCE REMAINS"
  ```
- [x] Full suite green with the personal export present too: `uv run pytest --tb=short -q`.
- [x] Lint clean: `uv run ruff check src/ tests/`.
- [x] Commit (per task as they land): `test(crypto): migrate <area> tests off local koinly2025 fixture to committed synthetic example`.

### Task 8: Docs sync and Rule Codification

Files:
- `docs/maintenance/crypto_implementation_guidelines.md`
- `CLAUDE.md`
- this plan file (checkboxes)

- [x] Grep `docs/` for any guidance that presents reading `resources/source/koinly2025` in tests as the canonical pattern; repoint to the committed `resources/source/example/koinly2025/` and the no-local-data rule.
- [x] Broaden docs grep to check for the old test name: `grep -rn "test_real_koinly_fixture_has_no_duplicate_aggregation_keys" docs/` must return nothing post-migration.
- [x] Codify the rule in `CLAUDE.md` §2 or §4 (or `docs/maintenance/crypto_rules.md` / `crypto_implementation_guidelines.md`): "Crypto tests MUST read committed synthetic data under `resources/source/example/koinly<year>/`; never reference `resources/source/koinly<year>/` (gitignored, `skip`s in CI). Enforced by the `test_example_data_is_synthetic` hygiene assertion and the `mv ...aside` validation gate."
- [x] Document the synthetic template generation/maintenance workflow in `docs/maintenance/crypto_implementation_guidelines.md`.
- [x] Run `check-no-em-dash.sh` on changed docs.
- [ ] When all tasks are `[x]`, move this plan to `docs/history/plans/completed/`.
