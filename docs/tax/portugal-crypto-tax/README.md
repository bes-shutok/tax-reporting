# Portugal Crypto Tax Law Archive

This folder stores official references and implementation notes used by the `Crypto` sheet generation in `extract.xlsx`.

## Terminology

- Koinly source directory: any sibling folder matching `koinly*` that contains Koinly exports.
- Numeric separator ambiguity: values like `1,000` that can mean thousands grouping or decimal format depending on locale.
- Optional crypto dataset: crypto data is additive to IB reporting and may be unavailable for a run.

## Contents

- `official/`: downloaded official legal and tax guidance documents only.
- `sources.md`: source manifest with retrieval date and intended use.
- `../crypto-origin/`: local archive of chain/operator origin source extracts used by the crypto workbook.
- `examples/`: Koinly export mapping notes and selected input formats.
- `../../domain/crypto_reporting_guidelines.md`: canonical numbered findings and implementation guidance for crypto reporting.

## Scope Boundary

- This folder is for Portugal-specific tax law, AT forms, circulars, and binding rulings.
- Chain/operator domicile evidence belongs in `../crypto-origin/`.

## Report Mapping Used by the Code

### Required to Load Crypto Data

- Capital gains section source: `koinly_*_capital_gains_report_*.csv`
  - Required fields: `Date Sold`, `Date Acquired`, `Asset`, `Amount`, `Cost (EUR)`, `Proceeds (EUR)`, `Gain / loss`, `Holding period`, `Wallet Name`.
- Rewards section source: `koinly_*_income_report_*.csv`
  - Required fields: `Date`, `Asset`, `Amount`, `Value (EUR)`, `Type`, `Description`, `Wallet Name`.

At least one of these two files must be present or the crypto dataset is skipped.

### Optional but Used When Present

- Swap-history / audit-trail source: `koinly_*_transaction_history_*.csv`
  - Used to recover both sides of `Exchange` rows and populate token swap history in the `Crypto` sheet.
  - Key fields: `Date`, `Type`, `Tag`, `Sending Wallet`, `Sent Amount`, `Sent Currency`, `Receiving Wallet`, `Received Amount`, `Received Currency`, `TxHash`, `Description`.
- Reconciliation source: `koinly_*_beginning_of_year_holdings_report_*.csv`
  - Used for opening holdings reconciliation.
- Reconciliation source: `koinly_*_end_of_year_holdings_report_*.csv`
  - Used for closing holdings reconciliation.

### Export Files Present but Not Loaded by the Crypto Workbook Builder

- `koinly_*_buysell_report_*.csv`
- `koinly_*_ledger_balance_report_*.csv`
- `koinly_*_highest_balance_report_*.csv`
- `koinly_*_expenses_report_*.csv`
- `koinly_*_other_gains_report_*.csv`
- `koinly_*_gifts_donations__lost_assets_*.csv`
- Koinly PDFs, except for separate metadata/debugging workflows outside the main row loader

## Implementation Safeguards (2026-03-08)

- Decimal parsing now disambiguates separator formats to avoid silent undercounting for values such as `1,000`.
- Decimal parsing does not treat leading-zero subunit values (for example `0,001` or `0.001`) as thousands-grouped numbers.
- Koinly directory lookup is year-agnostic and prefers a folder matching the detected IB tax year when possible.
- If the discovered Koinly directory year does not match inferred IB tax year, crypto loading is skipped for that run with a warning.
- Missing/unparseable Koinly inputs are logged with explicit warnings, and IB report generation continues without crypto data.

## Operator Origin Notes

- Wallet/operator mapping is done at operator level (not only brand level).
- Wirex is split by service scope:
  - crypto transactions -> Wirex crypto operator mapping
  - fiat/card transactions -> Wirex fiat operator mapping
- `ByBit` and `ByBit (2)` must be normalized to the same wallet before any country resolution or aggregation.
- `País da Fonte` must be determined from the payer / operator / protocol side, not from taxpayer residence.
- For DeFi rows, use the hierarchy `interface legal entity -> protocol / foundation / sponsor -> validator operator`.
- Known EEA-facing CeFi defaults collected so far:
  - `Kraken -> Ireland`
  - `Gate.io -> Malta`
- Numbered crypto-reporting implementation guidance now lives in `docs/domain/crypto_reporting_guidelines.md`.

## Wallet and Chain Derivation

- Wallet / platform labels from Koinly are **discovery hints only** for chain and country lookup.
- The final reported `chain` and `country` (País da Fonte) mapping comes from trusted archived sources under `docs/tax/crypto-origin/`.
- Chain derivation uses deterministic normalization rules:
  - Strip transport suffixes such as address tails (`- 0x...`, `- 5R39...`)
  - Strip asset tickers in parentheses when they are only wallet-label noise
  - Normalize wallet aliases (e.g., `ByBit (2)` -> `ByBit`)
  - Look up the candidate chain name against the trusted origin archive
- If the wallet label does not allow a reasonable derivation, `chain` is set to `Unknown` explicitly.
- The raw wallet name is preserved unchanged in the workbook; `chain` is an additional normalized field.

## Reward Classification and Aggregation

The Crypto sheet rewards section implements a two-tier classification system based on Portuguese tax law:

### Classification Rules

1. **Deferred by law (default)**: Crypto-denominated rewards are not taxed at receipt.
   - Under CIRS article 5(11) and AT PIV 22065, remuneration received in the form of cryptoassets moves to later taxation on disposal.
   - This includes staking rewards, liquidity mining, airdrops, and most DeFi income denominated in crypto.

2. **Taxable now**: Rewards that must be reported immediately in Category E (Anexo E).
   - Fiat-denominated rewards (EUR, USD, etc.) paid to a bank account.
   - Explicitly documented exception buckets where Portuguese law requires immediate taxation.
   - The code must positively identify an official exception bucket; otherwise, crypto-denominated rewards default to deferred.

### Aggregation Model

The workbook rewards section is split into two tables:

1. **Filing-Ready Summary (taxable_now)**: IRS-ready aggregated table for immediate Category E filing.
   - Aggregated by `(income_code, source_country)` to match Anexo J Quadro 8A requirements.
   - Shows total gross income and foreign tax per aggregated key.
   - Every row has all mandatory IRS fields: income code, source country (Tabela X), EUR amounts.

2. **Support Section (deferred_by_law)**: Reference section for rewards deferred until later disposal.
   - Shows all crypto-denominated rewards that are not immediately taxable.
   - Included for auditability and so nothing disappears from the workbook.

### Source Country Resolution

The `País da Fonte` for rewards follows the same hierarchy used for capital gains:
- **CeFi**: Use the EEA-facing legal entity country (e.g., Kraken -> Ireland, Gate.io -> Malta).
- **DeFi**: Use `interface entity -> protocol/foundation -> validator operator`.
- **Never** use taxpayer residence country merely because the activity happened in Portugal.

### Reconciliation

The Crypto sheet includes counts and EUR totals for:
- Number of rows in taxable-now section
- Number of rows in deferred-by-law section
- Total EUR amount in each section
- This provides a clear audit trail from raw Koinly data to final filing set.
