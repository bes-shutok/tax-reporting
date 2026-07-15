# API Contracts

This service exposes **no HTTP API**. It is a CLI tool (`uv run tax-reporting`) that reads CSV files and writes Excel/CSV. This page documents the data "contracts" the tool depends on: input file schemas and the decision-points TOML schema.

## Input CSV schemas (consumed)

- **IB exports** - brokerage CSV with thousands/decimal-separator ambiguity. The parser detects separators or fails clearly; it never classifies a leading-zero integer part (e.g. `0,001`) as thousands-grouped, and treats a single dot-grouped triplet (e.g. `1.234`) as ambiguous. See `docs/maintenance/development_lessons.md`.
- **Koinly** - Transaction History (`*transaction_history*.csv`), Capital Gains, and Other Gains Report. Required Koinly settings and per-field handling in `docs/maintenance/koinly_guidelines.md`.

## Decision-points TOML schema

`docs/maintenance/tax/decision_points/<fiscal_year>.toml`:

- `[meta]` - integer `fiscal_year`, optional `source_decision_file`, `last_verified`.
- `[countries.XX]` - law-driven decision-point values. Each value may be a **boolean** flag (e.g. `exclude_loan_repayment_gains`) or a **`dict[str, Decimal]`** subtable (e.g. `exclude_transaction_fee_max_eur_per_asset`; DP-015 is the first non-boolean field type). The loader type-dispatches over `get_type_hints(TaxJurisdictionConfig)`: `hint is bool` -> boolean validation; `get_args(hint) == (str, Decimal)` -> dict validation + `Decimal(str(value))` conversion (the `str()` round-trip avoids binary-float noise). A `dict[str, Decimal]` field is declared as a TOML subtable `[countries.XX.<field_name>]` whose keys are the eligibility set and values are per-asset ceilings.

Adding a flag (bool or `dict[str, Decimal]`) to the `.md` requires the corresponding field on `TaxJurisdictionConfig` (`domain/jurisdiction.py`). A missing TOML for the configured `FISCAL_YEAR` raises `MissingDecisionPointsError` at startup; the `.md` and `.toml` sidecars are updated together.

## config.ini schema

Three sections: `[COMMON]`, `[EXCHANGE RATES]`, `[TAX JURISDICTION]` (`TAX_COUNTRY`, `FISCAL_YEAR`, `ZERO_BASIS_REVIEW_THRESHOLD`, `ZERO_BASIS_REVIEW_MIN_PROCEEDS`, `IANA_TIMEZONE` (optional for `TAX_COUNTRY=PT`, which auto-deduces `Europe/Lisbon`; for any other country it is REQUIRED when crypto data is present - crypto processing fails fast with `ConfigurationError` when it cannot resolve a timezone, whether because a configured jurisdiction lacks `IANA_TIMEZONE` or because `config.ini` is absent entirely, rather than silently stamping naive Koinly CG/OGR/Income dates as UTC)); the four scalar fields default to PT/2025/50/10, and `IANA_TIMEZONE` defaults to Europe/Lisbon for PT and None otherwise). User preferences only - law-driven flags stay in decision-points TOML.

## Output

Excel workbook (Capital Gains, Crypto Gains, Loan Activity, Dividend Income, Report Structure sections - see `docs/maintenance/tax_reporting_guidelines.md`) plus the `shares-leftover.csv` rollover in `resources/result/`.

## Pointers

- Missing-vs-invalid data handling: `docs/maintenance/project-guidelines.md`.
- Error handling conventions: repo root `AGENTS.md`.
