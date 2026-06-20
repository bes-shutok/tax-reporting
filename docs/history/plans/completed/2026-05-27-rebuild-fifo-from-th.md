# Plan: Rebuild FIFO from Transaction History for Loan-Affected Assets

Based on: `../../domain/koinly-fifo-findings.md`
Plan review: `../../reviews/2026-05-27-plan-review-rebuild-fifo-from-th.md`

## Design Invariants (CR Guard)

- The FIFO rebuild is **jurisdiction-gated**: only activates when `TaxJurisdictionConfig.exclude_loan_repayment_gains=True` (currently Portugal). For all other countries, Koinly's CG file is used as-is for **all** assets including loan-affected ones.
- `LOAN_AFFECTED_ASSETS` is a named constant (`frozenset({"WBTC", "SUI", "LBTC"})`). These are the only assets where Koinly's CG is contaminated by loan transactions mixing in the FIFO pool.
- **FIFO scope is per-wallet/per-institution** (resolved in Task 0): CIRS art. 43 n.9 (consolidated numbering; n.7 in AT folheto numbering) mandates that when crypto-assets are deposited in more than one institution or service provider, FIFO is applied to each one individually. The AT folheto 2026-01-12 page 6 confirms: "quando os criptoativos estejam depositados em mais do que uma instituição financeira ou prestador de serviços, aplica-se a regra do FIFO a cada uma, individualmente." DP-004 corrected from global per-asset to per-wallet per-institution. This is a direct legal requirement, not a repository policy override. The FIFO engine must maintain separate pools per `(asset, platform)`.
- Crypto-to-crypto exchanges are **not taxable disposals** under Art. 10(20) / DP-002. The FIFO engine must model them as **non-taxable consumptions** that still consume FIFO lots and emit a carry-over acquisition cost for the received asset.
- Loan-tagged rows (`Tag="Loan"`, `Tag="Loan repayment"`, `Tag="Loan fee"`) are excluded from the FIFO pool entirely; they are invisible to capital gains per CIRS art. 10(20).
- `Type=transfer` rows do **not** reset holding period or create taxable principal disposals, but any fee-bearing transfer that consumes a loan-affected asset must still emit a **fee-only taxable consumption** per DP-006 / DP-007.
- Task 4 produces **intermediate FIFO realization results** plus carry-over-cost mappings. Task 5 converts those results into `CryptoCapitalGainEntry` only after populating `operator_origin`, `annex_hint`, `chain`, and `token_swap_history` via the existing crypto-reporting helpers.
- Cross-asset dependency: LBTC→WBTC / LBTC→SUI exchanges must be resolved using the TH transaction identifier (`TxHash`, with an explicit fallback composite key if absent), **never** by day-level date alone.

## Review Scope

Files directly changed as part of this plan. Review feedback is accepted **only** for the files listed here.
Any finding about a file not in this list must be rejected as out of scope.

**Production code; in scope:**
- `../../../src/shares_reporting/application/crypto_fifo.py` *(new)*
- `../../../src/shares_reporting/application/crypto_reporting.py`: `_parse_capital_gains_file()` asset exclusion + pipeline move; `load_koinly_crypto_report()` FIFO integration
- `../../../src/shares_reporting/application/persisting/crypto_gains_sheet.py`: remove `loan_repayment_review` rendering block

**Tests; in scope:**
- `../../../tests/unit/application/test_crypto_fifo.py` *(new)*
- `../../../tests/unit/application/test_crypto_reporting.py`: remove obsolete loan-filter tests; add asset exclusion / FIFO integration tests
- `../../../tests/unit/application/persisting/test_crypto_gains_sheet.py`: remove obsolete `loan_repayment_review` coverage

**Docs; in scope:**
- `../../../CLAUDE.md`: remove obsolete loan-filter constraints in Task 1; add FIFO rebuild constraints in Task 7
- `../../domain/koinly_guidelines.md`: add FIFO rebuild cross-reference
- `../../domain/crypto_implementation_guidelines.md`: add FIFO engine patterns and failure-path guidance
- `2026-05-25-filter-loan-repayment-gains.md`: add superseded-by note

**Out of scope; reject all review feedback:**
- `../../../src/shares_reporting/infrastructure/config.py`: `TaxJurisdictionConfig` unchanged from prior work
- `../../../src/shares_reporting/application/persisting/loan_activity_sheet.py`: Loan Activity sheet unchanged
- `../../../src/shares_reporting/domain/token_origin.py`: no structural changes needed
- `../../../tests/unit/application/persisting/test_loan_activity_sheet.py`: loan activity tests unchanged

## Validation Commands

```bash
uv run pytest tests/unit/application/test_crypto_fifo.py -v
uv run pytest tests/unit/application/test_crypto_reporting.py -v
uv run pytest tests/unit/application/persisting/test_crypto_gains_sheet.py -v
uv run pytest tests/unit/ -v
uv run pytest -m e2e
```

---

### Task 0: Resolve FIFO scope authority before coding

Files:
- `docs/plans/2026-05-27-rebuild-fifo-from-th.md`
- `../../tax/decision_points/2025.md`
- `../../domain/crypto_rules.md`

- [x] Re-read the mirrored official source behind PT-C-009 / DP-004 and decide whether the implementation must be **per-wallet** or **global per-asset**.
- [x] Update this plan's Design Invariants to state the chosen scope precisely as either (a) repository policy override with rationale, or (b) direct legal requirement.
- [x] If the scope decision changes the implementation shape, update Tasks 3-6 before writing any code.
- [x] Do **not** start FIFO implementation work until this contradiction is resolved in the plan.

### Task 1: Remove obsolete loan repayment filter functions and move the downstream pipeline

Files:
- `../../../src/shares_reporting/application/crypto_reporting.py`
- `../../../src/shares_reporting/application/persisting/crypto_gains_sheet.py`
- `../../../tests/unit/application/test_crypto_reporting.py`
- `../../../tests/unit/application/persisting/test_crypto_gains_sheet.py`
- `../../../CLAUDE.md`

- [x] Delete `_extract_loan_repayment_fingerprints()`.
- [x] Delete `_filter_loan_repayment_lots()`.
- [x] Delete `_flag_colocated_entries()`.
- [x] Delete `_select_review_candidates()`.
- [x] Change `_parse_capital_gains_file()` to return **raw CG rows only** as `list[CryptoCapitalGainEntry]`; remove the `transaction_history_path` parameter and all loan-filter-specific behavior.
- [x] Move `_validate_capital_entries_have_valid_countries()`, `_aggregate_capital_entries()`, and `_filter_immaterial_entries()` out of `_parse_capital_gains_file()` and into `load_koinly_crypto_report()` so they run on the **post-merge** list (CG rows + FIFO-rebuilt rows).
- [x] Remove `loan_repayment_review` from `CryptoTaxReport`.
- [x] Update `load_koinly_crypto_report()` to stop creating / assigning `loan_repayment_review`.
- [x] Remove the `loan_repayment_review` rendering block in `crypto_gains_sheet.py` (current block spans lines 106-116, not 106-114).
- [x] Update `test_crypto_gains_sheet.py`: remove the obsolete helper parameter and delete `test_render_loan_repayment_review_row_has_red_background`.
- [x] Delete **all** loan-filter-specific tests in `test_crypto_reporting.py` by function name pattern, including the late wiring test `test_load_koinly_crypto_report_populates_loan_repayment_review_and_loan_activity`; do not rely on a stale line range.
- [x] Remove the obsolete loan-filter pipeline constraints from `../../../CLAUDE.md` in the same task so the repository guidance stays consistent with the code after this refactor.
- [x] Run → expect GREEN: `uv run pytest tests/unit/application/test_crypto_reporting.py -v`
- [x] Run → expect GREEN: `uv run pytest tests/unit/application/persisting/test_crypto_gains_sheet.py -v`
- [x] Commit: `refactor: remove obsolete loan repayment filter pipeline`

### Task 2: Add loan-affected asset exclusion from CG file (PT-only gate)

Files:
- `../../../src/shares_reporting/application/crypto_reporting.py`
- `../../../tests/unit/application/test_crypto_reporting.py`

- [x] Write failing test: `test_parse_capital_gains_file_excludes_loan_affected_assets_when_pt`: CG file with WBTC + ETH rows, jurisdiction with `exclude_loan_repayment_gains=True`, assert only ETH rows are returned.
- [x] Write failing test: `test_parse_capital_gains_file_includes_loan_affected_assets_when_non_pt`: same CG file, jurisdiction with `exclude_loan_repayment_gains=False`, assert both WBTC + ETH rows are returned.
- [x] Write failing test: `test_parse_capital_gains_file_includes_loan_affected_assets_when_no_jurisdiction`: `jurisdiction=None`, assert all rows are returned.
- [x] Run → expect RED: `uv run pytest tests/unit/application/test_crypto_reporting.py -v -k "loan_affected_assets"`
- [x] Add constant: `LOAN_AFFECTED_ASSETS: Final[frozenset[str]] = frozenset({"WBTC", "SUI", "LBTC"})`.
- [x] In `_parse_capital_gains_file()`: when `jurisdiction is not None and jurisdiction.exclude_loan_repayment_gains` and `asset in LOAN_AFFECTED_ASSETS`, skip the CG row and increment a per-asset counter.
- [x] Log at **WARNING** (not INFO): `"FIFO rebuild active: skipped %d CG row(s) for loan-affected assets %s"`.
- [x] Return the remaining raw CG rows unchanged; aggregation/materiality now happens later in `load_koinly_crypto_report()`.
- [x] Run → expect GREEN: `uv run pytest tests/unit/application/test_crypto_reporting.py -v -k "loan_affected_assets"`
- [x] Commit: `feat: exclude loan-affected assets from CG parsing when PT FIFO rebuild active`

### Task 3: Implement TH row parser and classifier for loan-affected assets

Files:
- `../../../src/shares_reporting/application/crypto_fifo.py` *(new)*
- `../../../tests/unit/application/test_crypto_fifo.py` *(new)*

- [x] Write failing tests for TH row classification:
  - `test_classify_exchange_both_sides_loan_affected`: LBTC→WBTC exchange produces a **non-taxable** LBTC consumption plus a deferred WBTC acquisition sharing the same `tx_key`.
  - `test_classify_exchange_only_received_loan_affected`: BTC→WBTC produces a WBTC acquisition using `Sent Cost Basis` when present.
  - `test_classify_exchange_only_sent_loan_affected`: WBTC→BTC produces a non-taxable WBTC consumption only.
  - `test_classify_exchange_empty_sent_cost_basis_marks_review_required`: do **not** fall back to FMV carry-over; keep zero cost, log warning, set review metadata.
  - `test_classify_loan_deposit_skipped`: `Tag="Loan"` crypto_deposit excluded.
  - `test_classify_loan_repayment_skipped`: `Tag="Loan repayment"` crypto_withdrawal excluded.
  - `test_classify_transfer_skipped`: transfer principal excluded.
  - `test_classify_transfer_with_fee_emits_fee_disposal`: transfer with fee in a loan-affected asset emits a fee-only taxable consumption.
  - `test_classify_sell_as_taxable_consumption`: `Type=sell` produces taxable consumption with `Net Value (EUR)` as proceeds.
  - `test_classify_crypto_withdrawal_non_loan_as_taxable_consumption`: `crypto_withdrawal` (no loan tag) produces taxable consumption.
  - `test_classify_gas_fee_as_taxable_consumption`: `crypto_withdrawal` `Tag="Cost"` produces taxable consumption.
- [x] Run → expect RED: `uv run pytest tests/unit/application/test_crypto_fifo.py -v -k "classify"`
- [x] Create `../../../src/shares_reporting/application/crypto_fifo.py` with:
  - `CryptoAcquisition` dataclass `(date, asset, amount, cost_basis_eur, fee_eur, source_type, wallet, platform, tx_key, source_row_index, review_required, review_reason)`.
  - `CryptoConsumption` dataclass `(date, asset, amount, proceeds_eur, fee_eur, event_type, taxable, wallet, platform, tx_key, source_row_index, notes, review_required, review_reason)`.
  - `CryptoFifoRealization` dataclass `(disposal_date, acquisition_date, asset, amount, cost_eur, proceeds_eur, gain_loss_eur, holding_period, wallet, platform, notes, review_required, review_reason, tx_key)`.
  - `parse_th_for_loan_affected_assets(transaction_history_path: Path) -> tuple[dict[str, list[CryptoAcquisition]], dict[str, list[CryptoConsumption]]]`.
  - Classification logic per TH row `Type` / `Tag` combination, preserving source-row order for same-datetime events. The returned dicts are keyed by asset; platform is a field on each entry for per-wallet grouping at FIFO time.
  - For exchanges with both sides loan-affected: create a deferred acquisition with `cost_basis_eur=ZERO`, `source_type="exchange_in_deferred"`, and a matching non-taxable consumption sharing the same `tx_key`.
  - For exchanges with only received-side loan-affected: use `Sent Cost Basis` when present; when empty, keep `cost_basis_eur=ZERO`, set `review_required=True`, set a specific `review_reason`, and `logger.warning(...)`: **do not** substitute `Net Value (EUR)` as carry-over cost.
  - For transfer rows: ignore principal movement but emit fee-only taxable consumptions when `Fee Amount` / `Fee Currency` consume a loan-affected asset.
- [x] Run → expect GREEN: `uv run pytest tests/unit/application/test_crypto_fifo.py -v -k "classify"`
- [x] Commit: `feat: add TH row parser and classifier for crypto FIFO rebuild`

### Task 4: Implement per-wallet FIFO matching and carry-over resolution

Files:
- `../../../src/shares_reporting/application/crypto_fifo.py`
- `../../../tests/unit/application/test_crypto_fifo.py`

- [x] Write failing tests for FIFO matching:
  - `test_fifo_simple_buy_then_sell`: one acquisition, one taxable consumption → correct gain.
  - `test_fifo_partial_lot_consumption`: acquisition of 10, taxable consumptions of 3 then 7 → two realizations.
  - `test_fifo_multiple_lots_for_one_consumption`: one taxable consumption consumes multiple acquisition lots.
  - `test_fifo_holding_period_short_term`: holding period label is exact current string `"Short term"`.
  - `test_fifo_holding_period_long_term`: holding period label is exact current string `"Long term"`.
  - `test_fifo_placeholder_when_pool_exhausted`: no remaining lots → zero-cost placeholder, `review_required=True`, warning logged.
  - `test_fifo_fee_proportional_on_partial_lot`: acquisition fee allocated proportionally when lot is split.
  - `test_fifo_cross_asset_lbtc_to_wbtc`: LBTC carry-over cost becomes WBTC acquisition cost.
  - `test_fifo_two_same_day_lbtc_to_wbtc_exchanges_match_by_tx_key`: same-day exchanges do not cross-wire costs.
  - `test_resolve_cross_asset_unmatched_deferred_sets_review_required`: unresolved deferred acquisition is warned + flagged, not left silently zero-cost.
- [x] Run → expect RED: `uv run pytest tests/unit/application/test_crypto_fifo.py -v -k "fifo"`
- [x] Implement `AssetFifoResult` dataclass with `realizations: list[CryptoFifoRealization]` and `carryover_cost_by_tx_key: dict[str, Decimal]`.
- [x] Implement `compute_fifo_for_asset(acquisitions, consumptions, asset, platform) -> AssetFifoResult`:
  - Per-wallet scope (CIRS art. 43 n.9): the caller must pre-filter acquisitions and consumptions to a single `(asset, platform)` pair before calling; the function validates this invariant.
  - Sort acquisitions and consumptions by `(date, source_row_index)`.
  - For each **taxable** consumption: consume FIFO lots, compute `gain = proceeds - cost - fees`, and emit `CryptoFifoRealization` rows.
  - For each **non-taxable exchange** consumption: consume FIFO lots, record the consumed carry-over cost in `carryover_cost_by_tx_key`, and emit **no** capital-gain row.
  - Holding period labels must remain current Koinly-compatible strings: `"Short term"` / `"Long term"`.
  - When the FIFO pool is exhausted: create a zero-cost placeholder realization with `review_required=True`, a specific `review_reason`, and `logger.warning(...)`.
  - Allocate acquisition fees proportionally: `lot_fee = acquisition.fee_eur * (consumed_qty / lot_total_qty)`.
- [x] Implement `resolve_cross_asset_exchanges(acquisitions_by_asset, fifo_results_by_asset) -> dict[str, list[CryptoAcquisition]]`:
  - Process LBTC first, then resolve WBTC / SUI deferred acquisitions from LBTC carry-over maps.
  - Match deferred acquisitions by `tx_key`, not by date.
  - If a deferred acquisition cannot be resolved, leave cost at zero **and** set `review_required=True`, set a specific `review_reason`, and log `logger.warning(...)`.
- [x] Run → expect GREEN: `uv run pytest tests/unit/application/test_crypto_fifo.py -v -k "fifo"`
- [x] Commit: `feat: implement per-wallet FIFO matching engine for crypto`

### Task 5: Integrate FIFO engine into the crypto reporting pipeline

Files:
- `../../../src/shares_reporting/application/crypto_reporting.py`
- `../../../tests/unit/application/test_crypto_reporting.py`

- [x] Write failing test: `test_load_koinly_crypto_report_uses_fifo_for_loan_affected_assets`: provide CG file (non-loan assets only) + TH file (with WBTC buy + sell), PT gate enabled, assert WBTC capital entry is present with FIFO-computed gain.
- [x] Write failing test: `test_load_koinly_crypto_report_skips_fifo_when_non_pt`: same files, PT gate disabled, assert loan-affected assets come only from CG parsing.
- [x] Write failing test: `test_load_koinly_crypto_report_warns_when_th_missing_for_fifo`: PT gate enabled but TH missing, assert warning logged and report still loads.
- [x] Write failing test: `test_load_koinly_crypto_report_warns_when_excluded_asset_has_no_fifo_output`: PT gate enabled, CG rows excluded, TH present but FIFO produces zero rows for an excluded asset, assert warning logged.
- [x] Write failing test: `test_load_koinly_crypto_report_populates_fifo_entry_metadata`: FIFO-derived row gets `operator_origin`, `annex_hint`, `chain`, and `token_swap_history` via the existing helpers.
- [x] Run → expect RED: `uv run pytest tests/unit/application/test_crypto_reporting.py -v -k "fifo"`
- [x] In `load_koinly_crypto_report()`:
  - Call the simplified `_parse_capital_gains_file()` first to get raw CG rows.
  - When `jurisdiction.exclude_loan_repayment_gains` is True **and** `transaction_history_file` exists:
    - Call `parse_th_for_loan_affected_assets(transaction_history_file)`.
    - Group acquisitions and consumptions by `(asset, platform)` to respect per-wallet FIFO scope (CIRS art. 43 n.9).
    - Run LBTC FIFO per platform first, then resolve deferred WBTC / SUI acquisition costs by `tx_key`, then run FIFO for WBTC / SUI per platform.
    - Convert `CryptoFifoRealization` into `CryptoCapitalGainEntry` using the existing helpers: `resolve_operator_origin(...)`, `_derive_chain(...)`, `annex_hint = 'G1' if holding_period.lower().startswith('long') else 'J'`, and `origin_resolver.resolve(acquisition_date, asset, wallet, notes='')` for `token_swap_history`.
    - Merge FIFO-derived entries into the raw CG rows list.
    - If any asset was excluded in Task 2 but contributes zero merged rows after FIFO rebuild, `logger.warning(...)` explicitly.
  - When the gate is False or `jurisdiction is None`: do not rebuild FIFO.
  - When the gate is True but TH file is missing: `logger.warning(...)` and proceed without loan-affected entries.
- [x] After merging raw CG rows + FIFO rows, run the moved downstream pipeline in this exact order on the merged list:
  - `_validate_capital_entries_have_valid_countries(capital_entries)`
  - `capital_entries = _aggregate_capital_entries(capital_entries)`
  - `capital_entries = _filter_immaterial_entries(capital_entries)`
- [x] Run → expect GREEN: `uv run pytest tests/unit/application/test_crypto_reporting.py -v -k "fifo"`
- [x] Run full unit suite: `uv run pytest tests/unit/ -v`
- [x] Commit: `feat: integrate FIFO rebuild engine into crypto reporting pipeline`

### Task 6: Validation; compare the FIFO engine to Koinly CG for non-loan assets

Files:
- `../../../tests/unit/application/test_crypto_fifo.py`

- [x] Write test: `test_fifo_matches_koinly_cg_for_non_loan_asset`: use a small representative subset of real TH data for a non-loan asset (for example ETH or BTC with 5-10 CG rows), run the FIFO engine, and compare `cost_eur` / `proceeds_eur` to Koinly CG values with **strict** `<= 0.01 EUR` tolerance.
- [x] The test must **fail** on any divergence above `0.01 EUR`; do not paper over larger mismatches with comments.
- [x] If a harmless sub-cent rounding or timezone normalization note remains relevant after the assertions are green, document it as a code comment next to the fixture.
- [x] Run → expect GREEN: `uv run pytest tests/unit/application/test_crypto_fifo.py -v -k "matches_koinly_cg"`
- [x] Commit: `test: validate FIFO engine matches Koinly CG for non-loan assets`

### Task 7: Update documentation

Files:
- `../../../CLAUDE.md`
- `../../domain/koinly_guidelines.md`
- `../../domain/crypto_implementation_guidelines.md`
- `2026-05-25-filter-loan-repayment-gains.md`

- [x] In `../../../CLAUDE.md` Repository Constraints section, add the new FIFO rebuild guidance (the obsolete loan-filter wording was already removed in Task 1):
  - `When TaxJurisdictionConfig.exclude_loan_repayment_gains is True, loan-affected assets (WBTC, SUI, LBTC) are excluded from CG parsing and rebuilt from Transaction History; non-loan assets continue to use Koinly CG.`
  - `Run _validate_capital_entries_have_valid_countries(), _aggregate_capital_entries(), and _filter_immaterial_entries() only after FIFO-derived entries are merged with raw CG rows.`
  - `Cross-asset FIFO carry-over must match by TH transaction identifier, never by day-level date alone.`
  - `Any excluded asset that yields zero FIFO output must log at warning level or higher.`
- [x] In `../../domain/koinly_guidelines.md`: add section `FIFO Rebuild for Loan-Affected Assets` referencing `koinly-fifo-findings.md` and `crypto_fifo.py`.
- [x] In `../../domain/crypto_implementation_guidelines.md`: add section `FIFO Engine Patterns` covering non-taxable exchange consumptions, carry-over resolution by `tx_key`, transfer-fee handling, placeholder buys, and review-required failure paths.
- [x] Add a historical note to `2026-05-25-filter-loan-repayment-gains.md`: `Superseded by FIFO rebuild approach; see docs/domain/koinly-fifo-findings.md and docs/plans/2026-05-27-rebuild-fifo-from-th.md`.
- [x] Commit: `docs: update documentation for FIFO rebuild approach`
