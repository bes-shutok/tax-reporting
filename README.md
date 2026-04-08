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
- **Crypto Tax Data (Optional)**: For Portuguese crypto tax reporting, place Koinly export files in a `koinly*` subdirectory within `/resources/source`:
  - `koinly_<year>_capital_gains_report_*.csv` - Capital gains from crypto disposals
  - `koinly_<year>_income_report_*.csv` - Staking rewards, airdrops, and other income
  - `koinly_<year>_beginning_of_year_holdings_report_*.csv` - Opening balance (optional)
  - `koinly_<year>_end_of_year_holdings_report_*.csv` - Closing balance (optional)
  - `koinly_<year>_complete_tax_report_*.pdf` - Period metadata (optional)

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
- **Missing Buy History**: If securities are sold without corresponding buy transactions in the IB export, the tool automatically creates placeholder buy transactions (date: 1000-01-01, price: 0) to allow capital gains calculation. These entries are highlighted in red in the Excel report for manual review.

## Installation & Usage

### **Using UV (Recommended)**

```bash
# Install dependencies
cd tax-reporting
uv sync --extra dev

# Run the application
uv run tax-reporting
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
- `resources/source/example/koinly2024/` - Fake Koinly exports for crypto capital gains and rewards

**Features demonstrated:**
- Shares capital gains (FIFO buy/sell matching)
- Dividend income with withholding tax
- Leftover/rollover integration from a previous tax cycle
- Crypto capital gains aggregation (high-volume: 900+ raw disposal rows collapse to 4 report lines)
- Crypto rewards income (160 reward rows: SOL staking, ETH rewards, and ADA airdrops classified as deferred-by-law, plus EUR referral rewards classified as taxable-now)
- Token origin column (blank, by design - see below)

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
from shares_reporting.main import main
main(Path('resources/source/example/ib_export.csv'), Path('resources/result/example'))
"
```

This writes `resources/result/example/extract.xlsx` containing both the Reporting sheet (capital gains, dividends) and the Crypto sheet (capital gains, rewards). The `main()` function accepts a `source_file` parameter to override the default input path; see `src/shares_reporting/main.py` for the full API.

**Token origin column:** The Crypto sheet includes a `Token origin` column that is currently blank. A previous version of the tool used a disposal-day guessing heuristic to infer swap origins, but that logic produced misleading results for some transaction types (for example, loan repayments matched to unrelated same-day events). The column now stays blank unless a deterministic, export-backed linkage is available. A future update will implement proper Koinly-first origin matching based on acquisition-side export fields.

### **Report Features**
The tool generates comprehensive Excel reports with:
- **Capital Gains Section**: Detailed buy/sell transaction matching with FIFO methodology
- **Dividend Income Section**: Complete dividend reporting with tax information and original currency amounts
- **Crypto Section** (if Koinly data provided):
  - Capital gains aggregated by sale event per holding period with sub-1-EUR immaterial entries filtered
  - Capital gains statistics summary with per-holding-period breakdown (short-term, long-term, mixed, unknown) showing count, cost, proceeds, and gain/loss totals
  - Rewards income classified into taxable-now (fiat-denominated) vs deferred-by-law (crypto-denominated) per Portuguese tax law
  - IRS-ready aggregated summary for immediate Category E filing (taxable-now rewards grouped by income code + source country)
  - Chain derivation for blockchain context (e.g., Ethereum, Solana, Berachain) alongside wallet/platform
  - Full support detail sections for auditability and reconciliation
- **Professional Formatting**: Currency display with 2 decimal places and proper Excel formulas
- **Multi-Currency Support**: Automatic currency conversion with exchange rate tables
- **ISIN Integration**: Automatic country of source detection from financial instrument data

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