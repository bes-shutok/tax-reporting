# Glossary

Terms used across this repository. Tax/legal terms reflect Portuguese (PT) rules unless noted; see `docs/maintenance/crypto_rules.md` for authority levels and `docs/maintenance/tax/decision_points/` for per-year rulings.

## Tax bodies and instruments

- **AT** - Autoridade Tributária e Aduaneira (Portuguese tax authority). Issues Ofícios Circulados and PIVs.
- **CIRS** - Código do IRS (Portuguese personal income tax code). Consolidated text in `docs/maintenance/tax/laws/pt/crypto-tax/official/cirs_2025-07_code_consolidated.pdf`.
- **IRS** - Portuguese personal income tax return (Modelo 3), not the U.S. IRS.
- **Modelo 3 / Anexo** - Portuguese return form and its schedules (Anexo E, G, G1, J, Quadro 13).
- **DAC8 / MiCA** - EU directives/regulation under `docs/maintenance/tax/laws/eu/crypto-tax/`.

## Reporting concepts

- **FIFO** - First-in-first-out lot matching, applied per-wallet per-institution per CIRS art. 43 n.9.
- **CG** - Capital gains (crypto disposals). Report rows from the Koinly Capital Gains export.
- **OGR** - Other Gains Report (Koinly). Holds disposal totals used to override per-lot sums when `use_other_gains_report=True`.
- **TH** - Transaction History (Koinly). Source of truth for FIFO rebuild and cross-asset carry-over.
- **Holding period** - Short-term (< 365 days, taxable) vs long-term (exempt) per CIRS art. 10 n.6.
- **País da Fonte** - Source country for crypto rewards/capital gains; resolved from operator origin, never from taxpayer residence.
- **Materiality threshold** - Entries with `|gain/loss| < 1 EUR` are filtered post-aggregation (see `crypto_rules.md`).
- **Zero-basis review** - Zero-cost disposals flagged for manual review when proceeds meet `ZERO_BASIS_REVIEW_MIN_PROCEEDS`.

## Asset/instrument types

- **LP** - Liquidity provision / pool tokens (add/remove liquidity).
- **Derivatives** - Futures/perpetuals; losses on liquidation are disposals of collateral (alienação onerosa). Routed to Anexo G Quadro 13, operation code G51.
- **Stablecoin / payment token** - Fiat-pegged asset (e.g. EURC, USDC); proceeds classification per `docs/maintenance/tax/decision_points/`.

## Internal identifiers

- **CRG / SRG / PT-C** - Crypto Reporting Guideline / Structure Reporting Guideline / PT-Crypto rule IDs cited in `docs/maintenance/crypto_rules.md` and `docs/maintenance/crypto_reporting_guidelines.md`.
- **CMD** - Crypto Mapping Decision (operator origin) in `docs/maintenance/tax/crypto-origin/mapping_decision_log.md`.
- **DP** - Decision Point in `docs/maintenance/tax/decision_points/<year>.md`.
