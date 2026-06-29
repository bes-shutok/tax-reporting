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
- Per-asset loan balance summary: received count/amount/value, repaid count/amount/value, and balance status
- Overpaid balances (cross-year loan repayment) highlighted with light-red fill
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
- **Security**: All external data string fields are wrapped with `safe_cell_value()` to prevent Excel formula injection. See `docs/maintenance/development_lessons.md` #7.
- **Formulas**: Excel formulas for dynamic calculations
- **Auto-sizing**: Column widths automatically adjusted for content with `MAX_CELL_WIDTH=50` cap and `MIN_DATA_WIDTH=12` floor (see `excel_utils.py`)
- **Conditional Formatting**: Priority-based fill ordering for validation issues. See `development_lessons.md` #81.
- **Column Additions**: When adding columns, update all related constants. See `development_lessons.md` #82, #83.
- **Multi-section Rendering**: When rendering multiple independent sections, avoid early returns in optional-data branches that would skip mandatory sections. Use if/else blocks instead. See `development_lessons.md` #93.

### Derivatives P&L Section
- Per-row derivative realizations (futures, perpetual swaps, options) with operator/counterparty, event count, and net P&L.
- Columns 1 through 10 hold the original reporting fields; **Annex** (column 11) and **Código** (column 12) are appended after **Review** (column 10) to carry the per-row Modelo 3 routing derived from counterparty residency. The sheet grew from 10 to 12 columns.
- The `Annex` column renders `DerivativesPnLEntry.annex_hint` and the `Código` column renders `operation_code`. When `TaxJurisdictionConfig.route_derivatives_by_counterparty_residency` is on, `ogr_handler._derivatives_route(country, operator_country, route_via_residency)` resolves these per row; when the flag is off both columns render blank.
- When `route_derivatives_by_counterparty_residency` is on the sheet warns (logger.warning) when any rendered `Annex` is blank, since a blank route means the residency dispatch failed to resolve.

### Crypto Supplementary Section
- The "1. INCOME CODES REFERENCE" numbered section renders ONLY when `TaxJurisdictionConfig.classify_rewards_with_income_codes` is on. When the flag is off the ENTIRE numbered section (header, the code/description/Country table, and its surrounding separator) is OMITTED from the sheet, not merely field-blanked. This is a user-visible structural change distinct from leaving individual fields empty.
- The reference table's Country column is sourced from `TaxJurisdictionConfig.country`, not a hardcoded literal. When income-code classification is on it lists only the official codes the crypto reward pipeline can actually emit (currently `E25`).

**SRG-009**
The Crypto Supplementary "Review required" section displays warning rows for transactions flagged for manual review. Sourced rows may originate from "Capital Gains" (FIFO realization issues), "Income" (rewards/yield), or "Transaction History" (suspected untagged transaction fees for unlisted assets).

**SRG-010**
PT-IRS-specific Modelo 3 fields (crypto reward income codes and derivatives Annex/Código routing) are resolved at the resolution layer and gated on decision-point flags, never emitted unconditionally nor on a country literal. Crypto reward income codes are gated on `TaxJurisdictionConfig.classify_rewards_with_income_codes`: when on, `interest`/`lending`/`lending interest` resolve to `E25` (Tabela V, Categoria E); staking/reward/airdrop/mining/fork/dividend and unknown types resolve to `""` (no Tabela V code exists for them); when off every crypto reward income code resolves to `""`. Derivatives routing is gated on `TaxJurisdictionConfig.route_derivatives_by_counterparty_residency`: when on, a resident operator -> Anexo G Quadro 13 (`G51`); a non-resident, empty, or `UNKNOWN` operator -> Anexo J Quadro 9.2.B (`G30`); when off both `annex_hint` and `operation_code` resolve to `""`. Entity field defaults are the blank route. See PT-C-031 for the counterparty-residency rule and SRG-008 for the taxable-now income placement.
