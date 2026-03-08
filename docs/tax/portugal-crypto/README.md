# Portugal Crypto Tax Reference (Local Archive)

This folder stores official references and implementation notes used by the `Crypto` sheet generation in `extract.xlsx`.

## Terminology

- Koinly source directory: any sibling folder matching `koinly*` that contains Koinly exports.
- Numeric separator ambiguity: values like `1,000` that can mean thousands grouping or decimal format depending on locale.
- Optional crypto dataset: crypto data is additive to IB reporting and may be unavailable for a run.

## Contents

- `official/`: downloaded official legal and tax guidance documents.
- `sources.md`: source manifest with retrieval date and intended use.
- `examples/`: Koinly export mapping notes and selected input formats.

## Report Mapping Used by the Code

- Capital gains section source: `koinly_*_capital_gains_report_*.csv`
  - Required fields: `Date Sold`, `Date Acquired`, `Asset`, `Amount`, `Cost (EUR)`, `Proceeds (EUR)`, `Gain / loss`, `Holding period`, `Wallet Name`.
- Rewards section source: `koinly_*_income_report_*.csv`
  - Required fields: `Date`, `Asset`, `Amount`, `Value (EUR)`, `Type`, `Description`, `Wallet Name`.
- Reconciliation source: beginning and end holdings exports.

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
- CEX mappings remain flagged for manual review because account-region legal entities can vary.
