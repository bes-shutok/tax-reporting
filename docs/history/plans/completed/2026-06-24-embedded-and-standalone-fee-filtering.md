# Plan: Embedded and Standalone Fee Filtering Gaps

[Optional: Feature Note 2026-06-24]

## Gist & Examples
Exclude embedded fees (`exchange` and `transfer` transaction rows containing `Fee Amount`) and single-TxHash standalone `Cost` / `Loan fee` tagged rows from capital gains. Refactor token fee configuration to deduplicate L1 chains using `popular_crypto_tokens.json` and explicit overrides in `2025.toml`.

Examples:
- **Embedded Fee (BNB):** An `exchange` row with a fee is parsed as an embedded fee. Its threshold is evaluated against the matched Capital Gain lot's `proceeds_eur` (not the TH `Net Value (EUR)` which represents the trade principal). It is removed if `proceeds_eur <= 0.5`.
- **Standalone Tagged Fee (ETH):** A `crypto_withdrawal` row tagged `Cost` with a single unique `TxHash` is now correctly filtered out of capital gains (co-occurrence guard relaxed for explicitly tagged fees).
- **Missing Token Config (TON):** Because `TON` is an L1 chain in `popular_crypto_tokens.json`, it now successfully uses the default 0.5 EUR ceiling rather than failing into the taxable "suspect" bucket.

## Evaluation Criteria

**Quality dimensions:**
- Correctness: Existing tests in `test_fee_filter.py` continue to pass. New tests for embedded fees verify that the threshold is evaluated against the CG lot's `proceeds_eur`, bypassing the TH row's `Net Value (EUR)`. Tagged standalone fee tests verify co-occurrence relaxation.
- Maintainability: Token fee configuration is deduplicated, using `popular_crypto_tokens.json` loaded directly by `fee_filter.py` for major chains, and `2025.toml` for explicit thresholds.

**Release gates:**
- Code review approval
- CI passing (`pytest`)

## Review Scope

**Explicit must-fix** — findings on these paths are always in scope (review and fix if valid):

**Production code:**
- `docs/maintenance/tax/popular_crypto_tokens.json`
- `docs/maintenance/tax/decision_points/2025.toml`
- `src/tax_reporting/domain/jurisdiction.py`
- `src/tax_reporting/infrastructure/config.py`
- `src/tax_reporting/application/crypto/fee_filter.py`

**Tests:**
- `tests/unit/application/test_fee_filter.py`
- `tests/unit/infrastructure/test_config.py`

**Plan-related extension** — implementation and review may change files not listed above. Treat a finding as in scope when it is **causally related to this plan**: it implements or completes a plan task, fixes a regression introduced by plan work, closes wiring or docs implied by an explicit must-fix change, or contradicts a contract the plan changed. If the link to the plan is weak or speculative, drop as out of scope with a one-line reason.

**Out of scope — reject unless plan-related:**
- Unrelated crypto filtering logic

## Validation Commands

```bash
uv run pytest tests/unit/application/test_fee_filter.py
```

### Task 1: Refactor Token Config

Files:
- `docs/maintenance/tax/popular_crypto_tokens.json`
- `docs/maintenance/tax/decision_points/2025.toml`
- `src/tax_reporting/domain/jurisdiction.py`
- `src/tax_reporting/infrastructure/config.py`

- [x] `docs/maintenance/tax/popular_crypto_tokens.json`: remove `XSTRK` from `layer_1_major_chains`, add it to `restaking_lrt_depin`, and add `BERA` to `layer_1_major_chains`
- [x] `docs/maintenance/tax/decision_points/2025.toml`: introduce `exclude_transaction_fee_default_max_eur = 0.5` in `[countries.PT]`. Reduce `exclude_transaction_fee_max_eur_per_asset` to explicit overrides (only `ETH = 1.0` and `BERA = 0.1`). Update the DP-015 prose comments to document the default 0.5 fallback, the use of `layer_1_major_chains` whitelist, and the inclusion of embedded exchange/transfer fees exempted from TxHash co-occurrence.
- [x] `src/tax_reporting/domain/jurisdiction.py`: add `exclude_transaction_fee_default_max_eur: Decimal = Decimal("0.5")`
- [x] `src/tax_reporting/infrastructure/config.py`: Add support for parsing single `Decimal` types for `TaxJurisdictionConfig` by defining `_KNOWN_DECIMAL_POINTS` (explicitly excluding `zero_basis_review_threshold` and `zero_basis_review_min_proceeds` so they aren't incorrectly captured from TOML) and updating `_validate_and_convert_flag`
- [x] `tests/unit/infrastructure/test_config.py#test_loads_decimal_decision_points` — given a decimal decision point like `exclude_transaction_fee_default_max_eur = 0.5`, expects the `TaxJurisdictionConfig` field to be correctly parsed into a `Decimal`
- [x] Run → expect RED: `uv run pytest tests/unit/infrastructure/test_config.py`
- [x] Write minimal implementation
- [x] Run → expect GREEN
- [x] Commit: `feat: refactor token config for fee filtering`

### Task 2: Parse Embedded Fees & Evaluate Threshold Against CG Proceeds

Files:
- `src/tax_reporting/application/crypto/fee_filter.py`
- `tests/unit/application/test_fee_filter.py`

- [x] `tests/unit/application/test_fee_filter.py#test_parses_embedded_fees_and_evaluates_proceeds` — given an `exchange` row with an inflated `Net Value (EUR)` (e.g. 5000 EUR) and filled `Fee Amount`/`Fee Currency`, and a matching CG lot whose `proceeds_eur` is 0.4, expects the fee lot to be successfully removed because the embedded fee threshold evaluates `proceeds_eur <= 0.5` (not the TH trade principal)
- [x] `src/tax_reporting/application/crypto/fee_filter.py`: remove strict `crypto_withdrawal` check for fee candidates. Scan all TH rows for non-empty `Fee Amount` and `Fee Currency` to yield embedded fees as untagged fees. Exempt embedded fees from the TxHash co-occurrence guard
- [x] `src/tax_reporting/application/crypto/fee_filter.py`: add an `is_embedded` flag to `FeeThEvent`. Keep evaluating standalone untagged withdrawals against TH `Net Value (EUR)` during `_identify_fee_and_suspect_events`. For embedded fees, skip the TH `Net Value (EUR)` check entirely and yield them if they meet the whitelist
- [x] `src/tax_reporting/application/crypto/fee_filter.py`: in `remove_transaction_fees`, use `match_lots` instead of `remove_matched_lots`. Reconstruct `remaining_entries` by including all unmatched entries PLUS matched embedded fee entries that EXCEED their threshold. Discard (filter) standalone fee matches and embedded fee matches that PASS their threshold. Manually invoke `_log_fee_removals` and construct the aggregate summary warning for removed lots
- [x] Run → expect RED: `uv run pytest tests/unit/application/test_fee_filter.py`
- [x] Write minimal implementation
- [x] Run → expect GREEN
- [x] Commit: `feat: filter embedded fees and evaluate thresholds on proceeds`

### Task 3: Relax Tagged Co-occurrence & Load JSON Token Whitelist

Files:
- `src/tax_reporting/application/crypto/fee_filter.py`
- `tests/unit/application/test_fee_filter.py`

- [x] `tests/unit/application/test_fee_filter.py#test_retains_standalone_tagged_withdrawals_without_co_occurrence` — given a `crypto_withdrawal` explicitly tagged `Cost` or `Loan fee` with a TxHash appearing only once, expects it to be filtered (co-occurrence guard relaxed)
- [x] `src/tax_reporting/application/crypto/fee_filter.py`: declare a private loader to safely read `layer_1_major_chains` directly from `docs/maintenance/tax/popular_crypto_tokens.json` using `load_guarded_json` (returning empty on failure to prevent aborts). Allow untagged fees if their asset is in `layer_1_major_chains`. The threshold used should be the override from `2025.toml` if present, else `exclude_transaction_fee_default_max_eur`
- [x] `src/tax_reporting/application/crypto/fee_filter.py`: drop the TxHash co-occurrence requirement (`>= 2`) for explicitly tagged `Cost` or `Loan fee` withdrawals, ensuring they are removed even if the `TxHash` is completely empty. Preserve co-occurrence for untagged standalone withdrawals
- [x] Run → expect RED: `uv run pytest tests/unit/application/test_fee_filter.py`
- [x] Write minimal implementation
- [x] Run → expect GREEN
- [x] Commit: `feat: relax tagged fee co-occurrence and load whitelist from json`
