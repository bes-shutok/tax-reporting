# Tax Reporting Guidelines

Cross-cutting reporting guidelines for this repository outside the narrow tax-law rule set.

## Terminology

- `SRG-xxx`: Structure Reporting Guideline (historically Shares Reporting Guideline) - numbered tax-reporting guideline for this repository.
- Core report: the main Interactive Brokers capital-gains / dividend output.
- Auxiliary dataset: optional supporting input such as Koinly crypto exports.

## Reliability Guidance

**SRG-001**
Auxiliary datasets must not block generation of the core report. Missing or malformed Koinly input must warn clearly and allow the IB report to finish without crypto data.

**SRG-002**
When the repository already carries a specific jurisdiction mapping or documented override, the workbook should use that specific value instead of vague placeholders such as `Multiple jurisdictions`.

**SRG-003**
Normalized reporting helpers such as `platform`, `wallet`, `chain`, and operator-country fields must be rendered alongside the raw data they explain, not as hidden transformations.

## Documentation Guidance

**SRG-004**
Canonical implementation/reporting guidance belongs under `docs/maintenance/`. Tax-law source archives belong under `docs/maintenance/tax/...`.

**SRG-005**
In `docs/maintenance/tax/.../official/`, keep only origin representations of source material. Derived summaries and repository guidance belong outside `official/`.

**SRG-006**
When the source is HTML, prefer a readable extracted Markdown or authoritative PDF representation over storing raw HTML.

**SRG-007**
Under `docs/maintenance/tax/`, use `*-tax` folders for country-specific tax-law archives and `*-origin` folders for chain/operator domicile archives. Do not mix law and origin evidence in the same folder.

**SRG-008**
Immediately taxable non-IB Category E income from auxiliary datasets (for example, fiat-denominated lending or referral rewards sourced from Koinly) must be written to the `Reporting` worksheet's capital investment income section under `OTHER CAPITAL INVESTMENT INCOME`, not to the originating auxiliary worksheet's filing summary. The originating worksheet retains classification detail, per-row trace data, and reconciliation for auditability. This prevents the same taxable-now aggregate from appearing as a filing target in two locations and keeps the main Reporting sheet as the single filing-facing source for all Category E income.

## Excel Report Sections

The generated workbook contains the following sections. Detail lives here so `AGENTS.md` can stay compact.

### Capital Gains Section
- Detailed buy/sell transaction matching with FIFO methodology
- Automatic currency conversion with exchange rate tables
- Country of source detection from ISIN data

### Crypto Gains Section
- Crypto capital gains with FIFO lot matching, aggregated by `(date, asset, platform, holding period)`
- Zero-cost entries highlighted with red fill when gain/loss exceeds the configured `ZERO_BASIS_REVIEW_THRESHOLD`
- Loan repayment disposals excluded from capital gains when `TaxJurisdictionConfig.exclude_loan_repayment_gains` is `True` (PT default)

### Loan Activity Section
- Per-asset loan balance summary: received count/amount/value, repaid count/amount/value, balance status, and a sibling balance-detail column carrying the rendered overshoot percentage
- Each asset's balance status is one of FIVE loan-status sentinels (`LOAN_STATUS_SETTLED` / `LOAN_STATUS_OPEN_LOAN` / `LOAN_STATUS_IN_ASSET_INTEREST` / `LOAN_STATUS_NO_EUR_PRICE` / `LOAN_STATUS_OVERPAID_VERIFY`), rendered in column 9 verbatim as `Settled` / `Open loan` / `Likely in-asset interest` / `Cannot classify: no EUR price data` / `Overpaid (cross-year loan? verify)` respectively. The sheet's R1 note-cell legend abbreviates the last as `Overpaid (verify)`; the data cell carries the full sentinel
- Three fill colors across the five sentinels: `Settled`, `Open loan`, and `Likely in-asset interest` -> neutral (no fill); `Cannot classify: no EUR price data` -> yellow fill; `Overpaid (cross-year loan? verify)` -> light-red fill. The `Overpaid (cross-year loan? verify)` sentinel arises from two classifier branches (large overshoot and repayment-only) but maps to a single light-red fill
- Populated from Koinly loan transaction data
- "FIFO Rebuild Scope" section below the loan data lists which assets were rebuilt from Transaction History (loan-affected assets per CIRS art. 10(20)); shows "None" when FIFO rebuild was not active. `CryptoTaxReport.fifo_rebuild_assets` carries this frozenset.

### Dividend Income Section ("CAPITAL INVESTMENT INCOME")
- Complete dividend reporting with tax information
- Both converted and original currency amounts displayed
- Symbol, Currency, ISIN, and country information
- Gross amount, withholding tax, and net amount calculations

### Report Structure
- **Column Headers**: Clear, descriptive headers with line breaks for readability
- **Currency Conversion**: Automatic conversion using configured exchange rates
- **Security**: All external data string fields are wrapped with `safe_cell_value()` to prevent Excel formula injection.
- **Formulas**: Excel formulas for dynamic calculations
- **Auto-sizing**: Column widths automatically adjusted for content with `MAX_CELL_WIDTH=50` cap and `MIN_DATA_WIDTH=12` floor (see `excel_utils.py`)
- **Conditional Formatting**: Priority-based fill ordering for validation issues.
- **Column Additions**: When adding columns, update all related constants.
- **Multi-section Rendering**: When rendering multiple independent sections, avoid early returns in optional-data branches that would skip mandatory sections. Use if/else blocks instead.

### Derivatives P&L Section
- Per-row derivative realizations (futures, perpetual swaps, options) with operator/counterparty, event count, and net P&L.
- Columns 1 through 10 hold the original reporting fields; **Annex** (column 11) and **Código** (column 12) are appended after **Review** (column 10) to carry the per-row Modelo 3 routing derived from counterparty residency. The sheet grew from 10 to 12 columns.
- The `Annex` column renders `DerivativesPnLEntry.annex_hint` and the `Código` column renders `operation_code`. When `TaxJurisdictionConfig.route_derivatives_by_counterparty_residency` is on, `ogr_handler._derivatives_route(country, operator_country, route_via_residency)` resolves these per row; when the flag is off both columns render blank.
- When `route_derivatives_by_counterparty_residency` is on the sheet warns (logger.warning) when any rendered `Annex` is blank, since a blank route means the residency dispatch failed to resolve.

### Crypto Supplementary Section
- The "1. INCOME CODES REFERENCE" numbered section renders ONLY when `TaxJurisdictionConfig.classify_rewards_with_income_codes` is on. When the flag is off the ENTIRE numbered section (header, the code/description/Country table, and its surrounding separator) is OMITTED from the sheet, not merely field-blanked. This is a user-visible structural change distinct from leaving individual fields empty.
- The reference table's Country column is sourced from `TaxJurisdictionConfig.country`, not a hardcoded literal. When income-code classification is on it lists only the official codes the crypto reward pipeline can actually emit (currently `E25`).
- **Section 3 "Suppressed zero-value deferred rewards" block** (CRG-022): zero-value `DEFERRED_BY_LAW` reward rows are skipped at parse time into `skipped_zero_value_deferred_rewards` and rendered here as an outer-header block: a blank spacer row, then a bold outer header `"Suppressed zero-value deferred rewards"`, followed by TWO conditional sub-headers each with its own 5-column table (Asset | Wallet | Rows | Summed amount | Category) sorted per-`(asset, wallet)` - `"Deferred dust (priced-asset rounding)"` (only when dust rows exist; Category=`"dust"`) and `"Deferred unpriced (no Koinly price feed)"` (only when unpriced rows exist; Category=`"unpriced"`). Summed amount is the native-unit `entry.amount` formatted `:.8f`. The block is rendered only when the skipped list is non-empty; the rows do NOT appear in the deferred detail table. The user-facing `Total reward rows (raw)` count drops accordingly because the zero-value deferred rows have left `reward_entries`.
- **Section 4 deferred reconciliation split** (CRG-022): the legacy single line `("Deferred-by-law rows (taxation deferred)", N)` is replaced by three lines - `("Deferred detail rows", N)`, `("Deferred dust rows (suppressed from detail)", M)`, `("Deferred unpriced rows (suppressed from detail)", K)` - so the suppressed counts are auditable alongside the detail count. The Crypto Reconciliation sheet carries a sibling `("Skipped zero-value deferred rewards (audit)", len(skipped_zero_value_deferred_rewards))` so the cross-sheet reward-row count stays reconciled. Cross-reference: CRG-022, glossary "Deferred dust" / "Unpriced deferred reward" (mirrors SRG-009's cross-reference pattern to CRG).

**SRG-009**
The Crypto Supplementary "Review required" section displays warning rows for transactions flagged for manual review. Sourced rows may originate from "Capital Gains" (FIFO realization issues), "Income" (rewards/yield), "Transaction History" (suspected untagged transaction fees for unlisted assets), or "derivatives" (OGR rows routed to derivatives with no capital-gains counterpart). In addition to the original anomaly sources, the section now also surfaces crypto-pipeline **data issues** so every per-row anomaly attributable to the source export or pipeline edge case is visible in the extract (per rule #7 EXTRACT_SURFACED class): duplicate-`tx_key` acquisition drops (W2), zero-Net-Value `crypto_deposit` rows flagged for review (W3), dedup surplus lots ("may indicate a missed FIFO split") and malformed-input lots ("investigate the source export") from the derivatives (W6) and fee (W7) CG dedup passes, untagged-whitelisted fee removals when they carry their own review signal (W7 branch-aware reason), OGR no-CG-counterpart rows (W9, `source_section="derivatives"`), and `token_origin` origin-resolution disagreements (W1 capital-gains scope and W5 FIFO-rebuild scope). Surplus and malformed dedup lots render with `is_suspicious=True` (red bold asset cell) since they indicate data-quality rather than a processing decision. The aggregate console WARNINGs that previously announced each count are demoted to `logger.info(...)` - the review rows ARE the audit surface; the console is reserved for project/processing problems only.

**SRG-010**
PT-IRS-specific Modelo 3 fields (crypto reward income codes and derivatives Annex/Código routing) are resolved at the resolution layer and gated on decision-point flags, never emitted unconditionally nor on a country literal. Crypto reward income codes are gated on `TaxJurisdictionConfig.classify_rewards_with_income_codes`: when on, `interest`/`lending`/`lending interest` resolve to `E25` (Tabela V, Categoria E); staking/reward/airdrop/mining/fork/dividend and unknown types resolve to `""` (no Tabela V code exists for them); when off every crypto reward income code resolves to `""`. Derivatives routing is gated on `TaxJurisdictionConfig.route_derivatives_by_counterparty_residency`: when on, a resident operator -> Anexo G Quadro 13 (`G51`); a non-resident, empty, or `UNKNOWN` operator -> Anexo J Quadro 9.2.B (`G30`); when off both `annex_hint` and `operation_code` resolve to `""`. Entity field defaults are the blank route. See PT-C-031 for the counterparty-residency rule and SRG-008 for the taxable-now income placement.

**SRG-011**
The Assumptions & Methodology (A&M) sheet carries run-specific count suffixes on its methodology items so every methodology decision applied to the user's records is visible in the extract (per rule #7 EXTRACT_SURFACED class). The PT-C-028 "Materiality Threshold" item renders a `[This run: filtered N entries, M retained.]` suffix naming how many sub-1-EUR capital-gain entries the materiality filter (W10) discarded and how many it retained. The dedup methodology item (derivatives CG dedup W6 and fee CG dedup W7) likewise renders a run-specific count of removed lots sourced from `CryptoDecisionCounts.derivatives_dedup_removed` / `fee_dedup_removed`. Counts are populated from the `CryptoTaxReport.decision_counts` accumulator and default to 0 / absent on IB-only runs and tests that do not construct `CryptoDecisionCounts`.

**SRG-012**
Koinly is the default *Transaction Source* (`Aggregator` / `Koinly`; see glossary) for the crypto transaction-history (TH) layer, but it is no longer the only one. The on-chain-native transaction path (`OnChainExplorer` / `Etherscan-<chain>`) is an opt-in, per-wallet alternative selected by the `ON_CHAIN_TH_WALLETS` config field in `[TAX JURISDICTION]`: a wallet label listed there uses the on-chain-derived TH (built from `bera_transactions.csv` via the CSV reader -> per-chain processor -> Koinly-compat adapter) INSTEAD of the Koinly TH, while unlisted wallets keep Koinly. The default (empty list) leaves the on-chain substitution inactive (unlisted wallets keep the Koinly TH), so the on-chain path is skipped. (Note: a separate unconditional Koinly-path change - the `token_origin` TxSrc->TxHash migration from Task 4 of the prior plan `2026-08-02-on-chain-tx-tagger` - affects multi-LP-withdrawal wallets regardless of this flag; the byte-identical scope here is only the on-chain substitution itself.) When the flag is on, the Crypto Reconciliation sheet renders per-wallet source provenance (`source_kind` per wallet) plus an on-chain delta block so the Koinly-vs-on-chain divergence (gas surfaced, spam/airdrop included, multi-leg compression differs) is auditable in the extract. A parse failure for an opted-in wallet raises `ReportGenerationError` (fail-loud, M1); the on-chain path is NOT a silent skip. The Income and Capital Gains reports stay Koinly-sourced regardless (the on-chain layer has no EUR price oracle; see design record §9.3). See `docs/maintenance/crypto_implementation_guidelines.md` "On-chain transaction source", `docs/maintenance/koinly_guidelines.md` "Section 6 -- Koinly is one of multiple Transaction Sources", and the design record `docs/architecture/on-chain-tx-design.md`.

**SRG-012 loan-activity divergence:** the on-chain adapter's `EVENT_TYPE_TO_KOINLY` mapping (in `src/tax_reporting/application/on_chain_th_adapter.py`) emits only Reward/Cost/Liquidity in/Liquidity out/empty tags - there is no `Loan`/`Loan repayment`/`Loan fee` `EventType` in the on-chain vocabulary. A wallet opted into the on-chain TH path therefore produces no loan-activity rows, so `loan_activity.py` classification and the loan-affected FIFO rebuild that feeds the `exclude_loan_repayment_gains` path are both lost for that wallet. If an opted-in wallet has loan activity recorded in Koinly, do not opt it into the on-chain TH path until a `Loan` `EventType` is added to the on-chain adapter.
