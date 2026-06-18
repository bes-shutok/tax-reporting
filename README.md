# Tax Reporting Tool

## Overview

The tax reporting tool processes Interactive Brokers and Koinly CSV reports to generate tax reporting data for capital gains, dividend income, and crypto rewards calculations. It matches buy/sell transactions using FIFO methodology, processes dividend payments with tax information, aggregates crypto data by Portuguese tax rules, and generates comprehensive Excel reports with currency conversion.

**Current Capabilities:**
- ✅ **Share Trading**: Processes Interactive Brokers CSV reports for stock trading
- ✅ **Capital Gains Calculation**: FIFO-based matching of buy/sell transactions within daily buckets
- ✅ **Capital Gains Reporting**: Generates Excel reports with capital gains data for tax authority submission
- ✅ **Dividend Income Reporting**: Processes dividend data and generates detailed dividend income reports
- ✅ **Crypto Tax Reporting**: Processes Koinly CSV exports for cryptocurrency capital gains and rewards income with Portuguese IRS-compliant aggregation and filtering
- ✅ **Multi-Currency Support**: Handles multiple currencies with manual exchange rate configuration

**Future Vision:**
- 🚀 **Additional Investment Types**: Support for DeFi protocols, staking rewards, and other investment vehicles
- 🚀 **Multiple Data Sources**: Integration with crypto exchanges (Binance, Coinbase, Kraken), DeFi platforms, and other financial APIs
- 🚀 **Advanced Matching**: Sophisticated algorithms for different investment types and tax optimization strategies
- 🚀 **Automated Exchange Rates**: Real-time currency conversion from multiple financial data providers

## Prerequisites

## Development Environment

### Virtual Environment Setup

To ensure your editor's language server (e.g., ZED) can properly detect the project dependencies, configure Poetry to create the virtual environment in the project directory:

```bash
# Install dependencies
uv sync --extra dev
```

This will create a `.venv` folder in your project root that editors can detect automatically.



### Python Requirements

- **Python 3.14+ required** (Modern Python features, `datetime.UTC` alias)
- **UV for dependency management** (recommended approach)
- **Professional package structure** with `src/` layout
- **Clean Architecture** with Domain-Driven Design
- **Type hints extensively used** throughout codebase
- **pytest framework** with comprehensive unit and integration tests
- **Modern tooling**: Ruff linter/formatter, coverage reporting, professional packaging

### **Source Files Configuration**
- **Input Data**: Add your Interactive Brokers CSV export to the `/resources/source` folder. See `resources/source/example/ib_export.csv` for a fully synthetic example of the file format.
- **Crypto Tax Data (Optional)**: For Portuguese crypto tax reporting, place Koinly export files in a `koinly*` subdirectory within `/resources/source`. Of the ~13 exports Koinly can produce, only the following are read by this tool:

  | File pattern | Koinly report name | Used for | Required? |
  |---|---|---|---|
  | `koinly_<year>_capital_gains_report_*.csv` | Capital gains report | Crypto capital gains (disposals) | **Yes**: missing = no CG data; tool warns |
  | `koinly_<year>_income_report_*.csv` | Income report | Reward income: staking, lending interest, airdrops | **Yes**: missing = no rewards; tool warns |
  | `koinly_<year>_transaction_history_*.csv` | Transaction history | Token origin resolution + FIFO rebuild for loan-affected assets (PT default) | **Yes**: missing skips FIFO rebuild with an error |
  | `koinly_<year>_beginning_of_year_holdings_report_*.csv` | Beginning of year holdings | Reconciliation tab opening balance | Optional |
  | `koinly_<year>_end_of_year_holdings_report_*.csv` | End of year holdings | Reconciliation tab closing balance | Optional |
  | `koinly_<year>_complete_tax_report_*.pdf` | Complete tax report (PDF) | PDF cross-check summary | Optional |

  All other Koinly exports (`buy/sell report`, `expenses report`, `other gains report`, `gifts/donations/lost assets`, `highest balance report`, `ledger balance report`, `balances per wallet PDF`) are **not read** and can be ignored.

  The tool automatically aggregates FIFO lot rows by (disposal date, asset, platform, holding period) to reduce manual filing burden while preserving the taxable vs exempt breakdown required for Portuguese IRS (short-term gains are taxable, long-term gains are exempt). After aggregation, entries where |gain/loss| < 1 EUR are filtered as immaterial. See `docs/domain/crypto_rules.md` for Portuguese tax law details.

  Chain derivation: The tool automatically derives blockchain chain information from wallet labels using trusted archived sources in `docs/tax/crypto-origin/`. Chain is reported as a separate column (e.g., "Ethereum", "Solana", "Berachain") alongside wallet/platform. Wallet aliases are normalized (e.g., "ByBit (2)" -> "ByBit") before aggregation.

  Validation behavior: The tool validates that all taxable-now rewards and capital entries have valid Portuguese Tabela X country codes. If validation fails, report generation stops with a clear error indicating which platform/wallet needs a country mapping. Crypto loading is non-blocking: missing or malformed Koinly inputs emit warnings but allow IB report generation to continue.
- **Automatic Leftover Integration**: The tool automatically integrates data from previous tax cycles:
  - If `shares-leftover.csv` exists in `/resources/source`, it will be automatically merged with the current year's export data
  - Leftover trades (older) are placed before current year trades to maintain FIFO order
  - Security information (ISIN, country) from the export file enriches the leftover data
  - If no leftover file exists, only the current export file is processed (backward compatible)
- **Currency Rates**: Update `config.ini` with all required currency exchange pairs.
  - E.g. you can use the exchange rates from the last day of the year from your national central bank or financial institution.
  - The config file also includes security validation settings (file size limits, allowed extensions, etc.)
  - The `[TAX JURISDICTION]` section controls country-specific tax behavior: `TAX_COUNTRY` (ISO 3166-1 alpha-2, defaults to `PT`), `FISCAL_YEAR` (defaults to 2025), `ZERO_BASIS_REVIEW_THRESHOLD` (entries with zero cost basis and gain/loss at or above this EUR value are flagged for review, defaults to 50), and `ZERO_BASIS_REVIEW_MIN_PROCEEDS` (zero-cost disposals with proceeds below this EUR value are not flagged for review, defaults to 10; set to 0 to restore prior flag-everything behavior). Law-driven flags such as whether loan repayment disposals are excluded from capital gains are read from `docs/tax/decision_points/<fiscal_year>.toml` (not from `config.ini`); see that file for per-country decisions. If you change `FISCAL_YEAR` to a year that has no corresponding `docs/tax/decision_points/<year>.toml`, the tool will fail at startup with a `ConfigurationError`. Copy `docs/tax/decision_points/2025.toml` as a template and update `[meta].fiscal_year` and the `[countries.XX]` flag values. `FISCAL_YEAR` is also used as the fallback Koinly directory year hint when the IB export contains no current-year trades (e.g., crypto-only reporting runs where no IB activity occurred that year).
- **Missing Buy History**: If securities are sold without corresponding buy transactions in the IB export, the tool automatically creates placeholder buy transactions (date: 1000-01-01, price: 0) to allow capital gains calculation. These entries are highlighted in red in the Excel report for manual review.

## Installation & Usage

### **Using UV (Recommended)**

```bash
# Install dependencies
cd tax-reporting
uv sync --extra dev

# Run the application (default: processes resources/source/ib_export.csv)
uv run tax-reporting

# Run with example data (uses resources/source/example/ and outputs to resources/result/example/)
uv run tax-reporting --example

# Run with custom paths
uv run tax-reporting --source-file /path/to/export.csv --output-dir /path/to/output

# Set logging level
uv run tax-reporting --log-level DEBUG
```

### Testing

```bash
# Using UV (recommended)
uv run pytest                       # Run all tests
uv run pytest -k <keyword>          # Run tests matching keyword
uv run pytest -vvl                 # Verbose output with all variables
uv run pytest --cov=.              # Run with coverage
```

### Code Quality and Linting

```bash
# Run Ruff linter (checks code quality)
uvx ruff check .                    # Check all files
uvx ruff check . --fix              # Auto-fix issues
uvx ruff check . --statistics       # Show issue statistics
uvx ruff check src/ tests/          # Check specific directories

# Run Ruff formatter (formats code)
uvx ruff format .                   # Format all files
uvx ruff format --check .           # Check if formatting is needed

# Combined workflow
uvx ruff check . --fix && uvx ruff format .  # Fix and format
```



### Quick Start With Example Data

The repository ships fully synthetic example data in `resources/source/example/` that exercises every major feature without requiring real tax files. All names, account numbers, and wallet identifiers are fictional; this data is not tax advice.

**Example files:**
- `resources/source/example/ib_export.csv` - Fake IB export with shares trades and dividends
- `resources/source/example/shares-leftover.csv` - Leftover trades from a prior year for rollover integration
- `resources/source/example/koinly2024/` - Fake Koinly exports for crypto capital gains, rewards, and transaction history (for token origin resolution)

**Features demonstrated:**
- Shares capital gains (FIFO buy/sell matching)
- Dividend income with withholding tax
- Leftover/rollover integration from a previous tax cycle
- Crypto capital gains aggregation (high-volume: 900+ raw disposal rows collapse to 4 report lines)
- Crypto rewards income (160 reward rows: SOL staking, ETH rewards, and ADA airdrops classified as deferred-by-law, plus EUR referral rewards classified as taxable-now)
- Token origin column populated with confidence levels for rows where acquisition-side correlation matches the transaction history

**High-volume aggregation demonstration:** The example Koinly CSVs contain over 1000 synthetic crypto rows. The capital gains pipeline aggregates them by (sale date, asset, platform, holding period), then filters immaterial entries (|gain/loss| < 1 EUR), producing a compact report with only a handful of filing-facing lines. This demonstrates the core value of the tool: converting verbose exchange exports into concise Portuguese-reporting-ready output.

**Run the example pipeline:**

```bash
# Run all example e2e tests to see the full pipeline in action
uv run pytest tests/end_to_end/test_example_report_generation.py -v
```

The tests parse the example inputs, run FIFO matching and crypto aggregation, then write an `extract.xlsx` workbook to a temporary directory and verify its contents. The high-volume tests specifically check that 1000+ raw crypto rows produce a small, structured set of report lines. You can also run the application with the example data from Python:

```bash
uv run python -c "
from pathlib import Path
from tax_reporting.main import main
main(Path('resources/source/example/ib_export.csv'), Path('resources/result/example'))
"
```

This writes `resources/result/example/extract.xlsx` containing the Reporting sheet (capital gains, dividends) and, when Koinly data is available, six Crypto sheets: Crypto Gains, Derivatives P&L (when `separate_derivatives_reporting` is on, per DP-012), Crypto Supplementary, Crypto Reconciliation, Loan Activity, and Platform Assumptions. The `main()` function accepts a `source_file` parameter to override the default input path; see `src/tax_reporting/main.py` for the full API.

**Token origin column:** The Crypto Gains sheet includes a `Token origin` column that shows the acquisition origin of disposed tokens where the resolver could correlate them to a transaction history event. Origins are resolved by implicit `(date, asset, wallet)` correlation between the capital gains report and the Koinly transaction history CSV. Each resolved origin shows the source asset, acquisition method (e.g., `swap_conversion`, `bridge_transfer`, `direct_purchase`, `airdrop`, `liquidity_withdrawal`, `liquidity_provision`), and a confidence level (`high` = on-chain hash present, `medium` = correlated only, `low` = ambiguous or missing cost basis). Rows where no match is found remain blank. LP operations without paired withdrawal records show `LP position` as the source asset. Origin values are best-effort correlation from Koinly export data and should be reviewed against source documents before filing.

### **Report Features**
The tool generates comprehensive Excel reports with:
- **Capital Gains Section**: Detailed buy/sell transaction matching with FIFO methodology
- **Dividend Income Section** ("CAPITAL INVESTMENT INCOME"): Share dividends and other capital investment income (e.g., fiat-denominated lending or referral rewards from crypto platforms), with taxable fiat rewards aggregated by income code and source country under `OTHER CAPITAL INVESTMENT INCOME`, alongside complete IB dividend reporting with tax information and original currency amounts
- **Crypto Sheets** (if Koinly data provided, six separate tabs):
  - **Crypto Gains**: Capital gains aggregated by sale event per holding period with sub-1-EUR immaterial entries filtered, plus statistics summary with per-holding-period breakdown (short-term, long-term, mixed, unknown) showing count, cost, proceeds, and gain/loss totals. When `exclude_loan_repayment_gains=True` (PT default), loan-affected assets are dynamically discovered from Koinly transaction history and their capital gains are rebuilt using a per-wallet FIFO engine per CIRS art. 43 n.9 rather than taken from Koinly's pre-computed capital gains report.
  - **Derivatives P&L**: Realized P&L from crypto futures and perpetuals (financial derivatives under CIRS art. 10(1)(e)), including funding fees and futures fees, aggregated by (date, asset, platform, event_type). Rendered only when the `separate_derivatives_reporting` flag is on (decision point DP-012). Spot crypto capital gains remain on the Crypto Gains tab under CIRS art. 10(1)(k), including the 365-day holding-period exemption; derivatives have no such exemption. Losses on derivatives are deductible against other Category G gains and may be carried forward 5 years per PT-C-016.
  - **Crypto Supplementary**: Audit support data including Income Codes reference (Portuguese Tabela V codes), taxable-now reward detail rows (traces each aggregated line back to source Koinly rows), deferred-by-law reward detail, rewards classification reconciliation, and review-required entries (zero-value popular tokens, suspicious entries)
  - **Crypto Reconciliation**: Key-value reconciliation of capital/reward totals, opening/closing holdings, and skipped zero-value tokens
  - **Loan Activity**: Per-asset loan receipt and repayment summary with balance and status; overpaid balances (cross-year loan repayments) are highlighted with red fill for manual review
  - **Platform Assumptions**: Complete manifest of all platforms appearing in the report with their operator entity, country, confidence level, and verification source URL; platforms requiring review are highlighted in red and sorted to the top for easy identification
- **Professional Formatting**: Currency display with 2 decimal places, proper Excel formulas, and auto-sized columns with intelligent width handling (formula-only columns receive minimum width, long text is capped to prevent excessive width)
- **Multi-Currency Support**: Automatic currency conversion with exchange rate tables
- **ISIN Integration**: Automatic country of source detection from financial instrument data

### Derivatives P&L Section
The Derivatives P&L tab separates realized derivatives results from spot crypto capital gains to match how Portuguese law characterizes each category:

- **Legal basis**: financial derivatives (futures, perpetuals, options on crypto) are Category G income under **CIRS art. 10(1)(e)**. Spot cryptoasset disposals remain under **CIRS art. 10(1)(k)** on the Crypto Gains tab, including the 365-day holding-period exemption; derivatives have no such exemption.
- **What it contains**: realized P&L from closed futures/perpetuals positions, funding fees, and futures (trading) fees, aggregated by `(disposal_date, asset, platform, event_type)` so each event type is reported on its own line.
- **Controlling decision point**: DP-012 (`separate_derivatives_reporting`). When the flag is `True`, the report renders the Derivatives P&L tab and keeps derivatives out of the Crypto Gains tab. When `False`, derivatives stay folded into Crypto Gains under art. 10(1)(e) (no behavior change for prior tax years).
- **Source values**: where Koinly produces an Other Gains Report (OGR), OGR values override Capital Gains Report values for derivatives (DP-011). OGR has explicit Type classification and better collateral flow handling.
- **Loss treatment**: derivatives losses are Category G losses and are deductible against other Category G gains; they may be carried forward for 5 years under PT-C-016 when the taxpayer opts for `englobamento`.

## Project Walkthrough

For a detailed slide-by-slide walkthrough explaining what the project does, why it exists, and how the example data demonstrates its value, see `docs/presentation/project-walkthrough.md`. The walkthrough covers the problem statement, the legal basis for aggregation, concrete before/after examples from the synthetic dataset, and the recommended next steps.

## Roadmap & Future Development

### **Planned Investment Type Support**
- **Earnings**: Various forms of investment earnings and rewards
- **Fixed Income**: Bond interest payments and maturity tracking

### **Planned Data Source Integration**
- **Crypto Exchanges**: Direct API integration with major cryptocurrency exchanges
- **DeFi Platforms**: Support for decentralized finance protocols and platforms
- **Additional Brokers**: Support for other traditional broker CSV formats

### **Potential Future Enhancements (Low Priority)**
- **Trade Matching Strategies**: Support for LIFO (Last In, First Out) and HIFO (Highest In, First Out) strategies for users in jurisdictions with different tax regulations

## Feedback
Please create issues to provide feedback!