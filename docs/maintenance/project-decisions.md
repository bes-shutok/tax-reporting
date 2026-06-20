# Project Decisions

Architecture and reporting decisions for this repository. Law-driven decisions are sourced per fiscal year in `docs/maintenance/tax/decision_points/`; this file records the stable engineering and reporting choices that do not change year to year.

## PD-001: Layered architecture

Domain-driven layering: `domain` -> `application` -> `infrastructure` -> `presentation`. Orchestration layers stay thin (about 500 lines); domain logic lives in dedicated services. See `README.md` for the full walkthrough.

## PD-002: FIFO per-wallet per-institution (CIRS art. 43 n.9)

Cost basis is matched first-in-first-out scoped per wallet and per institution, not globally. Engine lives in `crypto_fifo/`. Cross-asset FIFO carry-over matches by Transaction History identifier, never by day-level date alone.

## PD-003: Loan repayment gains excluded for PT

When `exclude_loan_repayment_gains=True`, loan-affected assets are excluded from Koinly CG parsing and rebuilt from Transaction History. Loan-affected assets are discovered from `"loan"` / `"loan repayment"` tags only (not `"loan fee"`).

## PD-004: Derivatives separated from spot

Derivatives/futures are split from spot into their own pipeline with an explicit OGR-vs-CG dedup step, then aggregated by `(disposal_date, asset, platform, holding_period)`. PT derivatives route to Anexo G Quadro 13, operation code G51.

## PD-005: Materiality and review gating

Post-aggregation, entries with `|gain/loss| < 1 EUR` are excluded. Zero-basis disposals are flagged for review only above `ZERO_BASIS_REVIEW_MIN_PROCEEDS` (default 10 EUR) and `ZERO_BASIS_REVIEW_THRESHOLD` (default 50). Partially-matched sells are never silently dropped; the placeholder-buy mechanism applies to the remaining quantity.

## PD-006: Optional crypto ingestion is non-blocking

Missing, mismatched-year, or unparseable Koinly input emits a warning and continues IB report generation without crypto data.

## PD-007: Law-driven flags in decision points TOML, not config.ini

`config.ini` holds only user preferences; law-driven flags (e.g. `exclude_loan_repayment_gains`) live in `docs/maintenance/tax/decision_points/<fiscal_year>.toml`, mirrored in the `.md` sidecar. A missing TOML for the configured `FISCAL_YEAR` fails fast at startup.
