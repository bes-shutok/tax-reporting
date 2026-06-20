# Troubleshooting

Common failure modes and their causes. All startup configuration errors propagate from `main()` unwrapped so callers can distinguish config problems from data problems.

## Startup errors

- **`MissingDecisionPointsError`** - no `docs/maintenance/tax/decision_points/<FISCAL_YEAR>.toml`. Copy `2025.toml` as a template and set `[meta].fiscal_year`.
- **`ConfigurationError`** (invalid `[TAX JURISDICTION]`) - unknown `TAX_COUNTRY` or malformed section.

## Crypto ingestion (non-blocking warnings)

- **No Koinly directory found** - crypto loading skipped; IB reports still generate.
- **Koinly year mismatch** - the inferred IB tax year differs from the selected Koinly directory year; crypto skipped for that run.
- **Unparseable Koinly input** - row-level parse errors are warned and skipped per row; one bad row never discards the dataset.

## Matching/output anomalies

- **Partially-matched sells** - FIFO exhausts buys before sells are consumed. The placeholder-buy mechanism applies to the remaining quantity and a capital-gain line is still produced (logged at warning+). These are never silently dropped.
- **Unmatched items** - always carry an explicit fallback and a warning; never silently discarded.
- **Loan fee rows mistaken for loan principal** - `discover_loan_affected_assets()` uses only `"loan"` and `"loan repayment"` tags, not `"loan fee"` (whose Sent Currency is the gas asset).

## Expected (not errors)

- **Derivative liquidation losses** are disposals of collateral (alienação onerosa) and are reported as such - this is correct tax treatment, not a bug.
- **Sub-1-EUR crypto gains filtered** post-aggregation is by design (`docs/maintenance/crypto_rules.md`).

## Pointers

- Lessons and pitfalls: `docs/maintenance/development_lessons.md`.
- Koinly-specific gotchas: `docs/maintenance/koinly_guidelines.md`.
- Platform divergences (Koinly vs CIRS): `docs/maintenance/tax/laws/pt/crypto-tax/platform-divergences.md`.
