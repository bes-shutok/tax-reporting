# Plan: Report Fiat Reward Income In Reporting

Plan review: `docs/reviews/2026-06-01-plan-review-report-fiat-reward-income.md`

## Gist & Examples

**What changes:** Move immediately taxable fiat reward income, such as Wirex EUR lending rewards, into the main `Reporting` worksheet under the existing capital investment income area. Keep the `Crypto Rewards` worksheet as the Koinly reward classification and audit-detail worksheet, but stop making it the only filing-facing location for taxable fiat rewards.

**Why needed:** The current workbook reports IB share dividends in `Reporting` under `CAPITAL INVESTMENT INCOME`, but Koinly fiat-denominated rewards are shown in the `Crypto Rewards` filing summary. For the user's current data, Wirex EUR X-Account rewards are exported by Koinly as `fiat_deposit` / `Lending interest` / `EUR`, so they are Category E capital income and fit the same filing area as share dividends. Keeping them only in `Crypto Rewards` makes the filing workflow look like crypto reward reporting even when the received income is EUR.

**Example input:** Koinly income row `07/01/2025 08:41, EUR, 27.75000000, 27.75, Lending interest, Wirex` plus IB dividend rows from Interactive Brokers.

**Example output:** The `Reporting` worksheet has one `CAPITAL INVESTMENT INCOME` section with explicit subsections:
- `SHARE DIVIDENDS`, containing rows whose income type is `Share dividends`.
- `OTHER CAPITAL INVESTMENT INCOME`, containing a Wirex row with income type `Income code 402`, source country `GB`, gross income `1195.79`, foreign tax `0`, net income `1195.79`, source detail `Wirex`, source system `Koinly`, and raw row count `50`.

**Edge cases handled:** Do not move crypto-denominated rewards such as BTC, WXT, USDT, USDC, or other stablecoins into the immediate filing section. Do not hardcode Wirex, GB, or income code `402` as special cases. Use existing reward classification and income-code resolution. Keep raw descriptions and per-row trace detail in `Crypto Rewards`; `Reporting` gets only filing fields plus minimal support pointers.

## Review Scope

Files directly changed as part of this plan. Review feedback is accepted **only** for the files listed here.
Any finding about a file not in this list must be rejected as out of scope.

**Production code - in scope:**
- `src/tax_reporting/application/persisting/ib_sheet.py` - add generic capital investment income rendering inside `write_ib_reporting_sheet`; freeze existing capital-gains row rendering except call-signature changes required by this plan.
- `src/tax_reporting/application/persisting/workbook_builder.py` - derive taxable-now reward aggregates before rendering `Reporting` and pass them to the sheet writer.
- `src/tax_reporting/application/persisting/crypto_rewards_sheet.py` - adjust filing-facing wording so the sheet is clearly support/detail once taxable-now aggregates are mirrored to `Reporting`.
- `src/tax_reporting/application/persisting/excel_utils.py` - add or extend safe string writing helper for Koinly-derived cell values if no suitable helper exists.

**Tests - in scope:**
- `tests/unit/application/persisting/test_ib_sheet.py`
- `tests/unit/application/persisting/test_crypto_rewards_sheet.py`
- `tests/unit/application/persisting/test_workbook_builder.py` *(new)*
- `tests/unit/application/persisting/test_excel_utils.py` *(new, only if safe string helper is added there)*
- `tests/integration/test_excel_generation_integration.py`
- `tests/end_to_end/test_example_report_generation.py`

**Documentation - in scope:**
- `AGENTS.md`
- `CLAUDE.md`
- `README.md`
- `docs/domain/crypto_reporting_guidelines.md`
- `docs/domain/tax_reporting_guidelines.md`
- `docs/presentation/project-walkthrough.md`

**Out of scope - reject all review feedback:**
- `src/tax_reporting/application/crypto_fifo/` - FIFO logic is unrelated to worksheet placement for fiat reward income.
- `src/tax_reporting/application/crypto_reporting.py` - reward parsing, classification, and aggregation are reused as-is; reject changes unless a test proves existing aggregate fields are insufficient.
- `docs/tax/laws/` - this plan changes workbook placement and labels, not the archived legal source set.
- `resources/source/` and `resources/result/` - generated and user input data must not be edited by this plan.

## Validation Commands

```bash
uv run pytest tests/unit/application/persisting/test_ib_sheet.py tests/unit/application/persisting/test_crypto_rewards_sheet.py -m unit
uv run pytest tests/integration/test_excel_generation_integration.py -m integration
uv run pytest tests/end_to_end/test_example_report_generation.py -m e2e
uv run pytest
```

### Task 1: Add Reporting Tests For Mixed Capital Investment Income

Files:
- `tests/unit/application/persisting/test_ib_sheet.py`

- [ ] `TestWriteIbReportingSheetCapitalInvestmentIncome#test_share_dividends_use_explicit_share_dividend_label` - given one IB dividend entry, expects the `Reporting` section title to be `CAPITAL INVESTMENT INCOME`, a subsection label `SHARE DIVIDENDS`, and row income type `Share dividends` instead of bare `Dividends`.
- [ ] `TestWriteIbReportingSheetCapitalInvestmentIncome#test_taxable_fiat_reward_aggregate_is_written_under_capital_investment_income` - given no IB dividends and one already-aggregated taxable fiat reward entry with chain/source detail `Wirex`, expects a `CAPITAL INVESTMENT INCOME` section, subsection `OTHER CAPITAL INVESTMENT INCOME`, source country `GB`, income type `Income code 402`, gross `1195.79`, foreign tax `0`, net `1195.79`, source detail `Wirex`, source system `Koinly`, and raw rows `50`.
- [ ] `TestWriteIbReportingSheetCapitalInvestmentIncome#test_non_wirex_taxable_fiat_reward_uses_derived_source_fields` - given an already-aggregated taxable fiat reward entry with chain/source detail `Kraken` and source country `IE`, expects country `IE`, source detail `Kraken`, and amounts from the entry rather than Wirex/GB constants.
- [ ] `TestWriteIbReportingSheetCapitalInvestmentIncome#test_foreign_tax_is_summed_and_net_is_gross_minus_tax` - given an already-aggregated taxable fiat reward entry with gross `100`, foreign tax `15`, and raw rows `2`, expects Reporting gross `100`, tax `15`, net `85`, and raw rows `2`.
- [ ] `TestWriteIbReportingSheetCapitalInvestmentIncome#test_empty_other_capital_income_list_does_not_write_other_income_subsection` - given no dividends and an empty already-filtered non-IB income list, expects no `OTHER CAPITAL INVESTMENT INCOME` rows.
- [ ] `TestWriteIbReportingSheetCapitalInvestmentIncome#test_no_capital_investment_section_when_no_dividends_and_no_taxable_rewards` - given no dividends and no taxable fiat reward aggregates, expects no capital investment income section.
- [ ] `TestWriteIbReportingSheetCapitalInvestmentIncome#test_koinly_source_strings_are_safe_for_excel_cells` - given a source-detail label beginning with `=`, `+`, `-`, or `@`, expects the written cell to be neutralized as text, not a formula.
- [ ] Run -> expect RED: `uv run pytest tests/unit/application/persisting/test_ib_sheet.py -m unit`
- [ ] Do not commit after RED; Task 2 makes these tests pass and commits the coherent change.

### Task 2: Render Taxable Fiat Rewards In Reporting

Files:
- `src/tax_reporting/application/persisting/ib_sheet.py`
- `src/tax_reporting/application/persisting/workbook_builder.py`
- `src/tax_reporting/application/persisting/excel_utils.py`
- `tests/unit/application/persisting/test_workbook_builder.py` *(new)*

- [ ] Extend `write_ib_reporting_sheet` to accept `other_capital_income_entries: list[AggregatedRewardIncomeEntry] | None`; do not pass raw `CryptoRewardIncomeEntry` objects into the sheet writer.
- [ ] Use this exact `OTHER CAPITAL INVESTMENT INCOME` column mapping: column 1 Beneficiary blank; column 2 income type `Income code <income_code>`; column 3 source country; column 4 blank identifier; column 5 gross EUR; column 6 foreign tax EUR; column 7 Portuguese withholding blank; column 8 income code; column 9 source detail from sorted `chains` joined with `, `; column 10 currency `EUR`; column 11 original gross EUR; column 12 original foreign tax EUR; column 13 net EUR; column 14 source system `Koinly`; column 15 raw row count.
- [ ] Keep raw Koinly descriptions, wallet notes, and per-row trace metadata out of `Reporting`; they remain in `Crypto Rewards` support detail.
- [ ] Derive Reporting rows from existing `aggregate_taxable_rewards()` output only; do not reclassify rewards in the sheet writer and do not reconstruct aggregate labels by joining back to the first raw reward row.
- [ ] Preserve `aggregate_taxable_rewards()` as the validation gate for taxable-now mandatory fields; invalid source countries must still raise `FileProcessingError` before workbook save.
- [ ] Extract `_write_capital_investment_income_section(...)` with separate helper paths for `SHARE DIVIDENDS` and `OTHER CAPITAL INVESTMENT INCOME`; keep `write_ib_reporting_sheet` as orchestration.
- [ ] Render share dividends and taxable fiat rewards in the same `CAPITAL INVESTMENT INCOME` section with separate subsections and explicit row labels.
- [ ] Add or reuse a safe string helper for Koinly-derived strings written to cells; neutralize formula prefixes `=`, `+`, `-`, `@` and strip or replace control/newline characters.
- [ ] Keep `workbook_builder.py` limited to sequencing: call `aggregate_taxable_rewards()` once, pass the aggregate to `write_ib_reporting_sheet`, and pass the same aggregate to `write_crypto_rewards_sheet`.
- [ ] Add workbook-builder error-path coverage for invalid taxable-now source country after the aggregate call moves earlier: workbook is closed, no stale output is left, and the original `FileProcessingError` propagates.
- [ ] Do not hardcode Wirex, GB, or `402`; fixture data may use those values, production code must derive them from existing operator-origin and income-code logic.
- [ ] Run -> expect GREEN: `uv run pytest tests/unit/application/persisting/test_ib_sheet.py tests/unit/application/persisting/test_workbook_builder.py -m unit`
- [ ] Commit: `feat: report fiat reward income in reporting sheet`

### Task 3: Keep Crypto Rewards As Support Detail Without Duplicate Filing Instructions

Files:
- `src/tax_reporting/application/persisting/crypto_rewards_sheet.py`
- `tests/unit/application/persisting/test_crypto_rewards_sheet.py`

- [ ] `TestCryptoRewardsSheetSummary#test_taxable_now_summary_is_labelled_as_reporting_support` - given aggregated taxable-now rewards, expects the top section wording to say the filing-facing rows are reported on the `Reporting` worksheet and this sheet is support detail.
- [ ] `TestCryptoRewardsSheetSummary#test_deferred_rewards_wording_still_states_deferred_until_disposal` - given deferred BTC/WXT rewards, expects section `2b. DEFERRED BY LAW - SUPPORT DETAIL` to remain and state they are not included in immediate filing rows.
- [ ] Update `Crypto Rewards` headings and notes to avoid presenting the same taxable-now aggregate as a second filing target.
- [ ] Keep taxable-now detail rows and reconciliation totals in `Crypto Rewards` so users can trace Reporting aggregates back to Koinly source rows.
- [ ] Run -> expect RED before text/code changes: `uv run pytest tests/unit/application/persisting/test_crypto_rewards_sheet.py -m unit`
- [ ] Run -> expect GREEN after implementation: `uv run pytest tests/unit/application/persisting/test_crypto_rewards_sheet.py -m unit`
- [ ] Commit: `feat: clarify crypto rewards support wording`

### Task 4: Verify End-To-End Workbook Placement

Files:
- `tests/integration/test_excel_generation_integration.py`
- `tests/end_to_end/test_example_report_generation.py`

- [ ] `TestExcelGenerationIntegration#test_taxable_fiat_rewards_appear_in_reporting_capital_investment_income` - given a crypto tax report with one EUR lending-interest reward and no IB dividends, expects `Reporting` to include the capital investment income section and a taxable reward row, and expects `Crypto Rewards` to retain support detail.
- [ ] `TestExcelGenerationIntegration#test_taxable_fiat_rewards_are_aggregated_before_reporting` - given two taxable-now EUR rewards sharing income code and source country, expects exactly one `OTHER CAPITAL INVESTMENT INCOME` row with gross equal to summed `value_eur`, foreign tax equal to summed `foreign_tax_eur`, net equal to gross minus tax, and raw rows equal to the taxable-now entry count.
- [ ] `TestExcelGenerationIntegration#test_deferred_crypto_rewards_do_not_create_reporting_income_rows` - given BTC, WXT, and USDT reward entries classified as deferred, expects no `OTHER CAPITAL INVESTMENT INCOME` row for those entries.
- [ ] `test_example_report_generation#test_example_taxable_now_rewards_are_reported_on_reporting_sheet` - given the example report data, expects immediately taxable fiat rewards to be visible on `Reporting` as aggregate rows with exact gross, tax, net, and raw-row-count values, and still traceable on `Crypto Rewards`.
- [ ] Run -> expect RED: `uv run pytest tests/integration/test_excel_generation_integration.py -m integration`
- [ ] Run -> expect GREEN after implementation: `uv run pytest tests/integration/test_excel_generation_integration.py -m integration`
- [ ] Run -> expect GREEN: `uv run pytest tests/end_to_end/test_example_report_generation.py -m e2e`
- [ ] Commit: `test: verify fiat rewards in reporting workbook`

### Task 5: Update Reporting Documentation

Files:
- `AGENTS.md`
- `CLAUDE.md`
- `README.md`
- `docs/domain/crypto_reporting_guidelines.md`
- `docs/domain/tax_reporting_guidelines.md`
- `docs/presentation/project-walkthrough.md`

- [ ] Add an `SRG` rule stating that immediately taxable non-IB Category E income from auxiliary datasets belongs in the `Reporting` worksheet's capital investment income section, while the originating auxiliary worksheet remains support detail.
- [ ] Update `AGENTS.md` and `CLAUDE.md` byte-for-byte so they no longer require `Crypto Rewards` to present the IRS-ready filing summary; the rule should say taxable-now crypto-origin fiat rewards are validated and aggregated before inclusion in the `Reporting` capital investment income section, while `Crypto Rewards` keeps support detail and reconciliation.
- [ ] Update `docs/domain/crypto_reporting_guidelines.md` CRG-007 so "IRS-ready" applies to the Reporting projection for taxable-now rewards, and `Crypto Rewards` is described as support detail plus classification reconciliation.
- [ ] Update `README.md` report-feature text to say taxable fiat rewards appear in `Reporting` under capital investment income, with `Crypto Rewards` used for classification, traceability, and deferred crypto-denominated rewards.
- [ ] Update the project walkthrough so fiat-denominated rewards are described as reported on `Reporting`, with `Crypto Rewards` used for classification detail and deferred crypto-denominated rewards.
- [ ] Do not add legal-source summaries to `docs/tax/laws/`; this plan relies on existing archived legal sources and changes repository output placement only.
- [ ] Commit: `docs: document category e reporting placement`

### Task 6: Final Validation

Files:
- `src/tax_reporting/application/persisting/ib_sheet.py`
- `src/tax_reporting/application/persisting/workbook_builder.py`
- `src/tax_reporting/application/persisting/crypto_rewards_sheet.py`
- `src/tax_reporting/application/persisting/excel_utils.py`
- `tests/unit/application/persisting/test_ib_sheet.py`
- `tests/unit/application/persisting/test_crypto_rewards_sheet.py`
- `tests/unit/application/persisting/test_workbook_builder.py`
- `tests/unit/application/persisting/test_excel_utils.py`
- `tests/integration/test_excel_generation_integration.py`
- `tests/end_to_end/test_example_report_generation.py`
- `AGENTS.md`
- `CLAUDE.md`
- `README.md`
- `docs/domain/crypto_reporting_guidelines.md`
- `docs/domain/tax_reporting_guidelines.md`
- `docs/presentation/project-walkthrough.md`

- [ ] Run `uv run pytest tests/unit/application/persisting/test_ib_sheet.py tests/unit/application/persisting/test_crypto_rewards_sheet.py -m unit`.
- [ ] Run `uv run pytest tests/integration/test_excel_generation_integration.py -m integration`.
- [ ] Run `uv run pytest tests/end_to_end/test_example_report_generation.py -m e2e`.
- [ ] Run `uv run pytest`.
- [ ] Generate a workbook from current `resources/source/` and manually verify Wirex EUR lending interest appears in `Reporting` under `OTHER CAPITAL INVESTMENT INCOME`.
- [ ] Verify Wirex BTC and WXT rewards remain only in `Crypto Rewards` deferred support detail until later disposal.
- [ ] Verify a stablecoin reward such as USDT/USDC remains out of `Reporting` and in deferred support detail.
