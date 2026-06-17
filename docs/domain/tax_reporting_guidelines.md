# Shares Reporting Guidelines

Cross-cutting reporting guidelines for this repository outside the narrow tax-law rule set.

## Terminology

- `SRG-xxx`: numbered tax-reporting guideline for this repository.
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
Canonical implementation/reporting guidance belongs under `docs/domain/`. Tax-law source archives belong under `docs/tax/...`.

**SRG-005**
In `docs/tax/.../official/`, keep only origin representations of source material. Derived summaries and repository guidance belong outside `official/`.

**SRG-006**
When the source is HTML, prefer a readable extracted Markdown or authoritative PDF representation over storing raw HTML.

**SRG-007**
Under `docs/tax/`, use `*-tax` folders for country-specific tax-law archives and `*-origin` folders for chain/operator domicile archives. Do not mix law and origin evidence in the same folder.

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
- **Security**: All external data string fields are wrapped with `safe_cell_value()` to prevent Excel formula injection. See `docs/domain/development_lessons.md` #7.
- **Formulas**: Excel formulas for dynamic calculations
- **Auto-sizing**: Column widths automatically adjusted for content with `MAX_CELL_WIDTH=50` cap and `MIN_DATA_WIDTH=12` floor (see `excel_utils.py`)
- **Conditional Formatting**: Priority-based fill ordering for validation issues. See `development_lessons.md` #81.
- **Column Additions**: When adding columns, update all related constants. See `development_lessons.md` #82, #83.
- **Multi-section Rendering**: When rendering multiple independent sections, avoid early returns in optional-data branches that would skip mandatory sections. Use if/else blocks instead. See `development_lessons.md` #93.
