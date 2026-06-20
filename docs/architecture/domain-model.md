# Domain Model

The domain is Portuguese personal income-tax reporting from brokerage and crypto exports. Three taxable categories flow through the pipeline; authoritative rule definitions live in Layer 2 maintenance docs (not duplicated here).

## Categories

- **Capital gains (IB securities)** - FIFO-matched disposals from IB CSVs. Aggregated per disposal event; reported in the Capital Gains Excel section.
- **Dividends** - per-symbol accumulation, withholding-tax detection (literal `"Withholding Tax"` only), one-currency-per-symbol validation. Reported in Dividend Income.
- **Crypto** - rewards income and capital gains from Koinly exports. See `docs/maintenance/crypto_rules.md` for the rule set (PT-C / CRG / SRG IDs) and `docs/maintenance/crypto_reporting_guidelines.md` for rendering.

## Key invariants

- **FIFO scope** is per-wallet per-institution (CIRS art. 43 n.9); cross-asset carry-over matches by Transaction History identifier, not day-level date.
- **Aggregation precedes validation.** Validation that depends on complete state (e.g. one currency per dividend symbol) runs post-aggregation, never per-row.
- **Materiality:** crypto capital-gain entries with `|gain/loss| < 1 EUR` are excluded after aggregation; see `docs/maintenance/crypto_rules.md`.
- **Review flags carry specific reasons.** `review_required=True` must include an actionable `review_reason` ("YES: <reason>", never a bare boolean).
- **Partial matches are never dropped.** Partially-matched sells use the placeholder-buy mechanism; unmatched items log at warning+ with an explicit fallback.

## Law-driven behavior

Law-driven flags (e.g. `exclude_loan_repayment_gains`) are resolved per fiscal year from `docs/maintenance/tax/decision_points/<year>.toml`, not `config.ini`. Derivatives separation, zero-basis review gating, and source-country (`País da Fonte`) resolution are documented there and in `docs/maintenance/project-decisions.md`.

## Pointers

- Rules and authority levels: `docs/maintenance/crypto_rules.md`.
- Implementation pitfalls: `docs/maintenance/crypto_implementation_guidelines.md`.
- Koinly ingestion: `docs/maintenance/koinly_guidelines.md`.
- Lessons learned: `docs/maintenance/development_lessons.md`.
