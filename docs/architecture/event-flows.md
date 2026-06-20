# Event Flows

This service has **no asynchronous events, messaging, or webhooks**. Processing is a synchronous batch pipeline driven from `main()`. This page records the end-to-end processing flow.

## Steady-state flow

1. **Load config** - `config.ini` + decision-points TOML for the configured `FISCAL_YEAR`; startup fails fast (`ConfigurationError`/`MissingDecisionPointsError`) on invalid jurisdiction or missing TOML.
2. **Ingest IB** - parse CSVs (currency conversion, ISIN mapping), build trades; merge `shares-leftover.csv` when present.
3. **Ingest crypto (optional)** - discover Koinly directory (`koinly*`, preferring the year matching IB data). If the inferred IB tax year differs from the selected Koinly year, skip crypto for that run. Missing/unparseable Koinly input warns and continues.
4. **Compute** - FIFO matching (per-wallet per-institution; derivatives separated from spot with OGR/CG dedup), aggregation (by `(date, asset, platform, holding_period)` for crypto CG; by `(income_code, source_country)` for rewards), materiality filtering, review-flag attachment.
5. **Render** - assemble the Excel workbook and write the rollover CSV to `resources/result/`.

## Law-driven branches

Tax-year decision points (`docs/maintenance/tax/decision_points/<year>.toml`) gate behavior at compute time - e.g. `exclude_loan_repayment_gains` diverts loan-affected assets to the TH-rebuild FIFO path. See `docs/maintenance/project-decisions.md` and `docs/maintenance/tax/decision_points/<year>.md` for the enumeration of branches (counts and cases must match implemented code).

## Pointers

- Reporting structure and worksheet layout: `docs/maintenance/tax_reporting_guidelines.md`.
- FIFO and loan-repayment details: `docs/maintenance/loan_repayment_audit_methodology.md`, `docs/maintenance/koinly-fifo-findings.md`.
