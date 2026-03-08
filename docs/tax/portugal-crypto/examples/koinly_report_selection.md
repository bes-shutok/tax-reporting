# Koinly Report Selection (2025 sample)

This note records which Koinly exports are used to build the `Crypto` sheet and their header format.

## Terminology

- Canonical mapping: active file-pattern rules documented in `../README.md`.
- Sample file list: concrete 2025 filenames used as a real reference example.

## Selection Rule

- Runtime selection is year-agnostic (`koinly*` folder discovery); this file is an example snapshot, not a hardcoded rule.

## Capital gains
- File: `koinly_2025_capital_gains_report_83XZZVHpHa_1772907517.csv`
- Header: `Date Sold,Date Acquired,Asset,Amount,Cost (EUR),Proceeds (EUR),Gain / loss,Notes,Wallet Name,Holding period`

## Income (rewards)
- File: `koinly_2025_income_report_Fy5pWyAA5V_1772907520.csv`
- Header: `Date,Asset,Amount,Value (EUR),Type,Description,Wallet Name`

## Beginning holdings
- File: `koinly_2025_beginning_of_year_holdings_report_RrhrsRDxmz_1772907533.csv`
- Header: `Asset,Quantity,Cost (EUR),Value (EUR),Description`

## End holdings
- File: `koinly_2025_end_of_year_holdings_report_XHwjUYp47T_1772907537.csv`
- Header: `Asset,Quantity,Cost (EUR),Value (EUR),Description`

## Transaction history (fallback/reconciliation)
- File: `koinly_2025_transaction_history_MoPSnKvxo4_1772907562.csv`
- Header: `Date,Type,Tag,Sending Wallet,Sent Amount,Sent Currency,Sent Cost Basis,Receiving Wallet,Received Amount,Received Currency,Received Cost Basis,Fee Amount,Fee Currency,Gain (EUR),Net Value (EUR),Fee Value (EUR),TxSrc,TxDest,TxHash,Description`
