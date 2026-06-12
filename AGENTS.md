# CLAUDE.md / AGENTS.md

This file provides guidance to coding agents when working with code in this repository.

## Instruction Rules

### 1. Reusable Engineering Rules

- For numeric fields from external reports, detect thousands/decimal separators or fail clearly.
- Do not classify values with a leading zero integer part (for example `0,001` or `0.001`) as thousands-grouped numbers.
- Treat exactly one dot-grouped triplet (for example `1.234`) as ambiguous and raise a clear error. Only multi-group dot patterns (for example `1.234.567`) may be stripped as European thousands.
- Use f-strings in exception constructors; never pass multiple positional args to an exception constructor.
- Catch row-level parse errors per row (warn and skip). Do not let one bad row discard the whole dataset.
- When an optional field from external input is absent, use a type-safe sentinel (e.g. `"0"` for numeric fields) rather than `""`. See `coding_guidelines.md` #4.
- Data-loss conditions (unmatched items, dropped records) must be logged at warning level or higher, never debug. See `coding_guidelines.md` #5.
- When a subsystem requires a complete set of N files from an external export, use all-or-nothing validation: none present → skip gracefully; partial set present → raise `FileProcessingError` listing missing files and export instructions; all present → proceed. See `development_lessons.md` #51.
- Validation that depends on complete state must run post-aggregation, not per-row. Mid-accumulation state can be temporarily invalid (e.g. reversal arrives before dividend).
- Unmatched items from matching algorithms must never be silently discarded — apply an explicit fallback and log a warning.
- Partial or uncertain results must carry an explicit indicator so the user cannot mistake them for complete resolution. Review flags must include specific actionable explanations, not bare booleans.
- User-facing output labels should use self-explanatory terminology, not terse names inherited from source formats. See `coding_guidelines.md` #6.

### 2. Repository Style and Conventions

- Use specific type annotations for generic collections (`list[Type] | None` instead of `list | None`). See `docs/domain/development_lessons.md #8`.
- Catch specific exception types (`FileProcessingError`, `ValueError`) instead of broad `Exception`. See `docs/domain/development_lessons.md #9`.
- Koinly source discovery must be year-agnostic (`koinly*`) and prefer a year matching parsed IB data when available.
- If an inferred IB tax year exists and the selected Koinly directory year differs, skip crypto loading for that run.
- Dividend aggregation must validate one currency per symbol; mismatches must raise `FileProcessingError`.
- `TradeDate` is a `NamedTuple(year, month, day)`. Do not call `.date()` on it; use it directly or call `.to_datetime()`.
- When classifying a dividend row as withholding tax, match only the literal string `"Withholding Tax"` — never match on bare `"Tax"`. Dividend descriptions routinely contain "Tax" as a word fragment (e.g. "Tax-Exempt Interest").
- In `docs/tax/.../official/`, keep only source-origin files. Derived notes and numbered guidance belong outside `official/`, and `sources.md` must record issuing dates, effective dates, and superseded dates. See `docs/project-guidelines.md` #1.
- For external source archive provenance and freshness checks, see `docs/project-guidelines.md` #1.
- For fiscal-year versioned tax decision points, see `docs/project-guidelines.md` #2.
- When consulting AT guidance (folheto, PIVs, ofícios circulados) that cites a CIRS paragraph number, verify the current number against the consolidated CIRS PDF — AT documents may predate renumbering amendments and use outdated paragraph references. See `docs/project-guidelines.md` #3.
- For tax/origin web sources, prefer authoritative PDFs or extracted Markdown/PDF over raw HTML, and reuse local mirrors.
- Under `docs/tax/`, use `laws/<jurisdiction>/crypto-tax/` for tax-law archives (e.g. `laws/pt/crypto-tax/`, `laws/eu/crypto-tax/`) and `crypto-origin/` for chain/operator domicile archives.
- When adding a new boolean flag to `docs/tax/decision_points/<year>.toml`, add the corresponding field to `TaxJurisdictionConfig` in `domain/jurisdiction.py`. The config system auto-discovers known flags from the dataclass's bool fields. See `development_lessons.md` #68.
- Share crypto `País da Fonte` resolution across rewards and capital gains. Never use taxpayer residence.
- Keep the `docs/tax/crypto-origin/` source manifest, registry, and decision log synchronized when changing crypto chain/operator mappings.
- Chain derivation must use deterministic normalization rules and validate against trusted sources in `docs/tax/crypto-origin/`.
- Wallet labels are discovery hints only; final chain/country mappings come from archived operator origin documents.
- When wallet labels don't allow reasonable chain derivation, use `Unknown` explicitly rather than guessing from asset symbols.
- When adding operator mappings with temporal validity: use `service_start_date` for when the platform started offering this service (used for transaction matching), use `valid_from` for when this specific mapping was verified from source documents (used for audit trail), set `service_start_date` before `valid_from` when both are known, and for platforms with unknown verification dates, set `service_start_date` and leave `valid_from` as null.
- When a module exceeds 1,000 lines or 50 functions/classes, extract cohesive responsibilities into separate modules under a subdirectory. See `development_lessons.md` #87, #88.
- Orchestration layers should be thin (~500 lines max). When coordination logic grows beyond this, consider extracting sub-orchestrators or moving domain logic to dedicated services. See `development_lessons.md` #87.

### 3. Repository Constraints

- Optional crypto ingestion must be non-blocking: when Koinly input is missing, mismatched-year, or unparseable, emit an explicit warning and continue IB report generation without crypto data.
- Partially-unmatched sells (FIFO exhausts all buys before all sells are consumed) must never be silently dropped. Apply the placeholder-buy mechanism to the remaining sell quantity, log at `logger.warning`, and include the resulting capital gain line in the report.
- When writing a partially-matched buy to the rollover CSV, the fee must be proportional: `proportional_fee = action.fee * (rolled_quantity / original_quantity)`.
- Dividend per-symbol validation must run after all rows for all symbols are accumulated, not after each row. Mid-accumulation state can be temporarily invalid (e.g. reversal arrives before dividend). Symbols that fail post-accumulation validation are skipped with `logger.warning`; they must not abort processing of other symbols.
- Aggregate crypto capital gains by `(disposal_date, asset, platform, holding_period)` before reporting. Do not remove or bypass `_aggregate_capital_entries()`.
- After aggregation, exclude entries where `|gain/loss| < 1 EUR`. Do not remove `_filter_immaterial_entries()` or parameterize `_MATERIALITY_THRESHOLD` without a `crypto_rules.md` update.
- Crypto reward income must be aggregated by `(income_code, source_country)` before inclusion in the IRS-ready filing table. Do not bypass or remove `aggregate_taxable_rewards()`.
- Reward classification into taxable_now vs deferred_by_law must use `_classify_reward_tax_status()` and cite CRG-001/CRG-002 rule IDs.
- Taxable-now crypto-origin fiat rewards must be validated and aggregated before inclusion in the `Reporting` capital investment income section under `OTHER CAPITAL INVESTMENT INCOME`. The `Crypto Supplementary` worksheet retains support detail (per-row trace data, classification, reconciliation) for both taxable-now and deferred rewards but is not a filing target. See SRG-008.
- The aggregation step must fail with `FileProcessingError` if any taxable-now row cannot be assigned all mandatory IRS fields (valid Tabela X country code).
- When `review_required=True` is set on `CryptoCapitalGainEntry` or `CryptoRewardIncomeEntry`, the `review_reason` field must contain a specific, actionable explanation. The Excel output shows "YES: \<reason\>" rather than a bare boolean. See PT-C-030.
- `OperatorOrigin` carries two separate review flags: `review_required` (row-level, triggers "YES: <reason>" and red fill on the transaction row) and `platform_review_required` (platform-level, controls the Platform Assumptions tab only — does NOT color transaction rows). Never conflate them. See CRG-016.
- The Platform Assumptions tab is a complete manifest of ALL platforms in the report. Do not filter it to only platforms with assumption text. Use `platform_review_required=True` (plus red fill, sorted first) to highlight platforms that need resolution; keep all other platforms visible for auditability.
- Tests that verify "YES:"/"NO" rendering in Excel output must set `review_required` / `review_reason` explicitly on the fixture entry — do not delegate to `origin.review_required`. Platform mappings change independently; delegating makes the rendering test silently track the wrong behavior. See lesson #42 in development_lessons.md.
- Crypto capital gains statistics must be computed via `CryptoCapitalGainStats.from_entries()` and rendered as the "1b. CAPITAL GAINS STATISTICS" Excel section. Do not remove or bypass this section. The grand total EUR amounts must be computed from the full entries list, not by summing per-period subtotals, so that unrecognized holding periods do not produce inconsistent statistics.
- Token origin resolution must use `TokenOriginResolver` and implicit `(date, asset, wallet)` correlation with the Koinly transaction history. The resolver never guesses; unmatched rows return `unknown` (blank in the workbook). Do not reintroduce same-day disposal-context matching.
- Token origin resolution supports LP (liquidity pool) operations and airdrops:
  - `AIRDROP` — tokens received via airdrop claims
  - `LIQUIDITY_WITHDRAWAL` — tokens received from removing liquidity from DEX pools
  - `LIQUIDITY_PROVISION` — LP tokens received from providing liquidity to DEX pools
  - `DIRECT_PURCHASE` — tokens acquired via a fiat-to-crypto `buy` transaction
- When aggregating capital entries, the `token_swap_history` field is derived via `_aggregate_origin_field()`: if all lots in a group share the same origin, it is used; otherwise unique non-empty origins are joined with '; '; when some lots have unknown origin, an "N lot(s) unresolved" indicator is appended so the user cannot mistake a partial result for full resolution.
- Koinly transaction history files use the naming pattern `*transaction_history*.csv` (matching the real Koinly export convention), not `*transactions_report*.csv`.
- When `TaxJurisdictionConfig.exclude_loan_repayment_gains` is True, loan-affected assets (dynamically discovered from loan-tagged TH rows via `discover_loan_affected_assets()`; WBTC, SUI, LBTC are historical examples for the current user's data, not a fixed constant) are excluded from CG parsing and rebuilt from Transaction History; non-loan assets continue to use Koinly CG. The FIFO engine lives in the `crypto_fifo/` package and is per-wallet per-institution per CIRS art. 43 n.9.
- `discover_loan_affected_assets()` uses only `"loan"` and `"loan repayment"` tags (not `"loan fee"`) to identify loan principal assets; `"loan fee"` rows are intentionally excluded from discovery because their Sent Currency is the gas/service fee asset (not the loan principal).
- When IB data has no current-year trades (`tax_year_hint` is None), the Koinly directory year hint falls back to `TaxJurisdictionConfig.fiscal_year` from config. This means the configured `FISCAL_YEAR` drives Koinly directory selection when no IB trades are present (e.g., crypto-only reporting runs).
- Run `_validate_capital_entries_have_valid_countries()`, `_aggregate_capital_entries()`, and `_filter_immaterial_entries()` only after FIFO-derived entries are merged with raw CG rows.
- OGR overrides must be applied BEFORE `_aggregate_capital_entries()` when `jurisdiction.use_other_gains_report=True`. CG rows are individual FIFO lots that get summed in aggregation; OGR contains the correct total gain/loss for the disposal event. Overriding after aggregation would lose the lot-level trail. See `development_lessons.md` #75, #78 (directional authority semantics), #80 (aggregation field semantics), #85 (recalculate validation from aggregated values).
- Cross-asset FIFO carry-over must match by TH transaction identifier, never by day-level date alone.
- Any excluded asset that yields zero FIFO output must log at warning level or higher.
- When processing crypto derivatives/futures liquidations that report losses, understand that leveraged positions report as disposals of collateral even when liquidating at a loss — this is correct tax treatment (alienação onerosa), not an error. See `development_lessons.md` #67.

### 4. Agent Workflow Rules

- When investigating and fixing bugs, follow TDD approach: create failing test first (RED), then implement fix (GREEN). See `development_lessons.md` #76.
- When building an index from source data, handle duplicate keys explicitly by summing. Never silently overwrite. See `development_lessons.md` #77.
- When testing string sanitization, validation, or parsing functions, explicitly test edge cases (empty strings, whitespace-only, multi-byte, control chars, multi-char prefixes, padded inputs). See `docs/domain/development_lessons.md #6`.
- Test error path coverage including double-failure scenarios (e.g., aggregation fails AND workbook.close fails). See `docs/domain/development_lessons.md #6`.
- Examine existing source data files in the repository (e.g., `resources/source/koinly*/`) directly before asking the user to provide samples or examples. Use Glob and Read tools to find and analyze the actual data.
- Do not commit changes unless explicitly asked by the user.
- Always use `uv run pytest`, not `uvx pytest`.
- `valid_from` = audit-only; `service_start_date` = matching. See `development_lessons.md` #17.
- Never write files to `docs/review/` (singular). The project convention is `docs/reviews/` (plural) for all code review and plan review output.
- **Never introduce a hardcoded value (asset ticker, constant set, threshold, magic string, fixed ordering) without first flagging it to the user and asking whether they want it hardcoded or derived dynamically.** This applies to plans, implementation, and code review. If you notice an existing hardcoded value while working on related code, flag it immediately before proceeding.
- When a plan investigates "is X handled correctly?", use verification-first task ordering: code inspection, test execution, and documentation review before implementation tasks. Skip implementation if verification shows correctness. See `development_lessons.md` #71.
- **CRITICAL:** When investigating "is X handled correctly?", code inspection alone is INSUFFICIENT. You must perform data trace verification: trace the user's specific case from source CSV through to final output, verify output matches source classifications, and validate across ALL source reports (TH, CG, Other Gains). See `development_lessons.md` #72, #73.
- When adding functions that call cross-module utilities, verify imports are complete. Run `uv run python -c "from module import function"` to verify imports resolve. See `development_lessons.md` #74.
- When adding a new feature controlled by a boolean flag (like `use_other_gains_report`), create dedicated backward compatibility tests that verify the "disabled" state preserves existing behavior — not just that the "enabled" state works correctly. See `development_lessons.md` #84.
- When extracting a function to a new module, check for dependencies on constants from the source module to avoid circular imports. See `development_lessons.md` #86.
- When addressing code review findings on a refactoring branch, fix all in-scope findings in the same branch: findings that touch files changed by the refactoring or address technical debt exposed by the extraction must be resolved now, not deferred. See `development_lessons.md` #92.
- When adding edge case tests, read the function implementation first to understand what patterns it actually supports before writing expected results. Do not assume behavior based on function name or documentation. See `development_lessons.md` #89.
- Validation functions with conditional logic need comprehensive edge case coverage: format checks, zero-padding, numeric ranges, calendar validity, time components, boundary conditions, and whitespace handling. See `development_lessons.md` #90.
- Helper functions extracted from larger modules need direct unit test coverage, not just indirect integration tests. Verify early returns, conditional branches, boundary conditions, state mutation, and edge cases. See `development_lessons.md` #91.

### 5. Domain Knowledge References

- Before changing crypto reporting logic, read `docs/domain/crypto_rules.md`, `docs/domain/crypto_reporting_guidelines.md`, and `docs/domain/crypto_implementation_guidelines.md`. Cite PT-C / CRG rule IDs for law-driven changes.
- Before implementing new crypto features, read `docs/domain/crypto_implementation_guidelines.md` for lessons learned and common pitfalls to avoid.
- Before processing Koinly exports or changing Koinly-related code, read `docs/domain/koinly_guidelines.md` for known Koinly behaviors and defects that affect Portuguese reporting (loan repayment disposal treatment, wrapped-asset repair workflow, Other Gains Report relevance, required settings).
- Before discussing crypto tax treatment, proposing architecture changes, or advising on Koinly settings, check `docs/tax/decision_points/` first — answers to cost-basis methodology, taxability of swaps, and tool settings are pre-decided there.
- Before changing cross-cutting report-generation behavior, read `docs/domain/tax_reporting_guidelines.md` and cite SRG rule IDs for repository-policy changes.
- Before writing implementation plans, read `docs/domain/plan_quality_guidelines.md` for patterns that minimize review iterations.
- Before writing or revising repository walkthroughs or presentation artifacts, read `docs/domain/plan_quality_guidelines.md` for presentation-artifact structure and placement.
- When a crypto presentation or walkthrough makes legal or filing claims, verify the current source set in `docs/tax/laws/pt/crypto-tax/sources.md` and cite the mirrored official documents.
- Use the authority level and source date in `crypto_rules.md` to check whether a rule may be stale for the current tax year.
- For country-specific tax decision points (e.g., loan repayment exclusion, holding period thresholds), see `docs/tax/decision_points/`.
- For tax/origin web sources, prefer authoritative PDFs or extracted Markdown/PDF over raw HTML, and reuse local mirrors.
- For private personal tax context supplied by the user, read `docs/personal/facts.md`. The `docs/personal/` tree is gitignored from this repository and may keep its own independent git history; do not copy its personal facts into tracked docs unless explicitly requested.

## Project Overview

Tax reporting tool processes Interactive Brokers and Koinly exports into Portuguese tax-reporting outputs for capital gains, dividends, and crypto rewards.

## Quick Start

- Main entry point: `uv run tax-reporting`
- CLI flags: `--example` (use example data), `--source-file PATH`, `--output-dir PATH`, `--log-level LEVEL`
- Alternative entry point: `uv run python ./src/tax_reporting/main.py`
- For broader setup and command reference, see `README.md`.

## Environment and Dependency Management

- Use `uv`; the project entry point is local, not a published PyPI package.
- Preferred test command: `uv run pytest`
- See `README.md` for setup, dependency management, and the full command catalog.

## Architecture

- Layered architecture:
  - Domain: `src/tax_reporting/domain/`
    - `token_origin.py` — Token acquisition origin resolution domain types
    - `crypto_fifo.py` — Domain types for the FIFO engine (CryptoAcquisition, CryptoConsumption, CryptoFifoRealization, AssetFifoResult)
    - `jurisdiction.py` — `TaxJurisdictionConfig` (fiscal year, country code, law-driven flags)
  - Application: `src/tax_reporting/application/`
    - `crypto_reporting.py` — Crypto tax reporting and Koinly parsing
    - `token_origin.py` — `TokenOriginResolver` application service (domain types in `domain/token_origin.py`)
    - `crypto_fifo/` — FIFO engine package for loan-affected assets (contexts.py, parsing.py, _emitters.py, matching.py, cross_asset.py, transfer.py, merge.py, _graph.py)
  - Infrastructure: `src/tax_reporting/infrastructure/`
    - `koinly_parser.py` — Shared Koinly CSV parsing utilities
    - `config.py` — Configuration management (re-exports `TaxJurisdictionConfig` from domain)
    - `isin_country.py` — ISIN to country resolution
    - `logging_config.py` — Logging configuration
    - `validation.py` — Input validation
  - Presentation: `src/tax_reporting/main.py`
- Core pipeline: extract IB/Koinly data, transform into tax calculations, then persist workbook and rollover outputs.
- For the fuller architectural walkthrough, see `README.md` and the source tree.

## Configuration Management

- Uses Python's `configparser` for INI file handling
- Configuration files: `config.ini` (production) and `tests/config.ini` (testing)
- Both configs have identical structure with four sections:
  - **[COMMON]**: Target currency specification
  - **[EXCHANGE RATES]**: Currency conversion rates (different values for prod/test)
  - **[SECURITY]**: Validation limits (file size, ticker length, allowed extensions, etc.)
  - **[TAX JURISDICTION]**: Country-specific tax settings (`TAX_COUNTRY`, `FISCAL_YEAR`, `ZERO_BASIS_REVIEW_THRESHOLD`); defaults to PT/2025 when absent
- Exchange rates should be updated annually (e.g., from your national central bank)
- Security settings use defaults from code if missing from config file
- Law-driven flags (e.g. `exclude_loan_repayment_gains`) are read from `docs/tax/decision_points/<fiscal_year>.toml`, not from `config.ini`. Both the `.md` and the `.toml` sidecar must be updated together when a decision point changes. `config.ini` contains only user-preference settings.
- Decision points TOML schema: must contain `[meta]` with `fiscal_year` (integer), and `[countries.XX]` tables of boolean flags only. Example: `[countries.PT]\nexclude_loan_repayment_gains = true`. Copy `docs/tax/decision_points/2025.toml` when adding a new fiscal year. If `FISCAL_YEAR` is set to a year without a corresponding TOML file, the tool raises `ConfigurationError` at startup.
- `ConfigurationError` is raised before pipeline execution in two cases: (a) `config.ini` has an invalid `[TAX JURISDICTION]` value (message: "correct config.ini"), (b) the decision points TOML is missing or malformed (raises `MissingDecisionPointsError`, a `ConfigurationError` subclass, with message: "create `docs/tax/decision_points/<year>.toml`"). It propagates from `main()` without wrapping so callers can distinguish configuration problems from data problems (`FileProcessingError`/`ReportGenerationError`).

## Excel Report Features

The application generates professional Excel reports with:

### Capital Gains Section
- Detailed buy/sell transaction matching with FIFO methodology
- Automatic currency conversion with exchange rate tables
- Country of source detection from ISIN data

### Crypto Gains Section
- Crypto capital gains with FIFO lot matching, aggregated by (date, asset, platform, holding period)
- Zero-cost entries highlighted with red fill when gain/loss exceeds the configured `ZERO_BASIS_REVIEW_THRESHOLD`
- Loan repayment disposals excluded from capital gains when `TaxJurisdictionConfig.exclude_loan_repayment_gains` is `True` (PT default)

### Loan Activity Section
- Per-asset loan balance summary: received count/amount/value, repaid count/amount/value, and balance status
- Overpaid balances (cross-year loan repayment) highlighted with light-red fill
- Populated from Koinly loan transaction data
- "FIFO Rebuild Scope" section below the loan data lists which assets were rebuilt from Transaction History (loan-affected assets per CIRS art. 10(20)); shows "None" when FIFO rebuild was not active. `CryptoTaxReport.fifo_rebuild_assets` carries this frozenset.

### Dividend Income Section ("CAPITAL INVESTMENT INCOME")
- Complete dividend reporting with tax information
- Both converted and original currency amounts displayed
- Symbol, Currency, ISIN, and country information
- Gross amount, withholding tax, and net amount calculations

### Report Structure
- **Column Headers**: Clear, descriptive headers with line breaks for readability
- **Currency Conversion**: Automatic conversion using configured exchange rates
- **Security**: All external data string fields are wrapped with `safe_cell_value()` to prevent Excel formula injection. See `docs/domain/development_lessons.md #7`.
- **Formulas**: Excel formulas for dynamic calculations
- **Auto-sizing**: Column widths automatically adjusted for content with `MAX_CELL_WIDTH=50` cap and `MIN_DATA_WIDTH=12` floor (see `excel_utils.py`)
- **Conditional Formatting**: Priority-based fill ordering for validation issues. See `development_lessons.md` #81.
- **Column Additions**: When adding columns, update all related constants. See `development_lessons.md` #82, #83.

## Data Flow

**Input**: Interactive Brokers CSV reports placed in `/resources/source/`
**Processing**: Domain-driven transformation pipeline with currency conversion and ISIN mapping
**Output**: Comprehensive Excel reports with capital gains, dividend income, and currency conversion tables in `/resources/result/` + unmatched securities rollover file for next year's calculations

### Automatic Leftover Integration

The system automatically integrates data from previous tax cycles:

**Feature Overview:**
- **Automatic Detection**: If `shares-leftover.csv` exists in the same directory as an export file, it's automatically integrated
- **Data Enrichment**: Leftover trades are enriched with security information (ISIN, country) from the current export file
- **FIFO Preservation**: Leftover trades (older) are placed before current year trades to maintain proper chronological ordering
- **Backward Compatibility**: If no leftover file exists, processes normally without any changes

**Integration Process:**
1. **Security Info Extraction**: Extracts security mapping from current export file
2. **Trade Combination**: Merges leftover trades + current export trades
3. **Processing**: Runs unified trade processing with complete security context
4. **Reporting**: Generates comprehensive capital gains calculations across all time periods

**File Formats:**
- **Export file** (`ib_export.csv`): Contains complete data with all sections
- **Leftover file** (`shares-leftover.csv`): Contains unmatched trades from previous cycle with extended columns (Basis, Realized P/L)
- **Output rollover**: Updated each year with new unmatched trades for next cycle

## Testing Strategy

### Test Structure
3-tier architecture: `tests/unit/` (401 unit-marked tests), `tests/integration/` (10 integration-marked tests), `tests/e2e/` (26 e2e-marked tests), plus 451 tests without explicit markers (total 888).

### Testing Commands
```bash
uv run pytest                        # All tests
uv run pytest -m unit                # Unit tests only (fast)
uv run pytest -m unit -x --tb=short  # Dev workflow: stop on first failure
uv run pytest --cov=src --cov-report=html  # Coverage
```

### Testing Guidelines

**Critical Rule**: Do not import pytest fixtures — they are injected automatically by name (`tmp_path`, `capsys`, `caplog`, `monkeypatch`, `request`).

**Import Cleanliness**: Remove unused imports (Ruff F401). Only import `Path` when instantiating or type-annotating, never for injected fixtures.

**Test Value Assessment**: test meaningful business logic, real edge cases, avoid duplicating coverage. High-value: complex IB CSV formats, tax calculations, error handling. Low-value: zero amounts, trivial parsing, cases already covered.

**Excel Output Tests**: When adding or modifying Excel report layouts, add visual structure tests to verify row placement, cell merging, blank rows, and header structure — not just data values. See development_lessons.md #69, #81 (conditional formatting priority), #82 (constant updates), #83 (blank/null handling). For structural changes (adding/removing columns), verify that absolute-position code (writes to specific column numbers) is still correct. See development_lessons.md #70.

## Development Best Practices

### Incremental Development with Testing
Test-driven approach: write failing tests → implement → run full suite → clean up low-value tests.

### Code Review Checklist
Before considering code complete, verify: required params are truly required, error messages have context (row numbers), exception chaining preserves originals, logging uses parameterized format, fail-fast vs missing-data distinction is correct, no pytest fixture imports, no unused imports.

## Code Quality Standards

### Linting and Formatting
- **Ruff** is the primary linter and formatter (configured in `pyproject.toml`)
- **Target**: Python 3.14, line length 120, Google-style docstrings
- **Enabled rulesets**: `E`, `F`, `UP`, `B`, `SIM`, `I`, `N`, `ARG`, `FA`, `DTZ`, `PTH`, `TD`, `FIX`, `RSE`, `S`, `C4`, `PT`, `D`, `PL`

### Documentation Best Practices
- **Always document**: Public modules, classes, `__init__` methods, complex functions
- **Skip docstrings for**: Trivial getters/setters, obvious `__repr__`, clear private methods, test functions
- **Style**: Google convention — one-line summary + optional extended description + Args/Returns/Raises sections

### Code Style Guidelines
- **Type hints**: Modern syntax (`X | Y`) with `from __future__ import annotations`
- **Imports**: Sorted by Ruff (isort); replace unused imports (F401)
- **Magic numbers**: Named constants (except in tests)
- **Datetime**: `datetime.UTC` (not `timezone.utc`)
- **Path handling**: `pathlib.Path` (not `os.path`)
- **Logging**: Lazy formatting (`logger.info("Message: %s", value)`)
- **Error Messages**: f-strings in exceptions (`raise ValueError(f"Invalid: {value}")`)
- **Required params**: Never default to 0 for essential identifiers/indices
- **Complexity**: Refactor high-complexity functions; use `# noqa: PLR0912` with comment if too risky

## Data Handling Principles

See `docs/project-guidelines.md` #5 for the full missing-vs-invalid data handling rules and code patterns.

## Error Handling Patterns

- Always include row number, symbol, and specific issue in error messages.
- Use `from e` exception chaining to preserve original context.
- **Logging**: parameterised format `logger.error("Row %d: bad value %s", row, val)`.
- **Exceptions**: f-strings `raise ValueError(f"Row {row}: bad value {val}")` — see §1 Instruction Rules.

## Project Structure

```
tax-reporting/
├── src/                     # Source code (src layout)
│   └── tax_reporting/
│       ├── __init__.py        # Package exports
│       ├── main.py           # Application entry point
│       ├── domain/           # Domain layer
│       │   ├── __init__.py
│       │   ├── value_objects.py   # TradeDate, Currency, Company, TradeType
│       │   ├── entities.py      # TradeAction, TradeCycle, CapitalGainLine
│       │   ├── accumulators.py   # CapitalGainLineAccumulator, TradePartsWithinDay
│       │   ├── collections.py    # Type aliases and utilities
│       │   ├── constants.py      # Domain constants
│       │   ├── exceptions.py     # Domain exceptions
│       │   ├── token_origin.py   # Token acquisition origin resolution domain types
│       │   ├── jurisdiction.py   # TaxJurisdictionConfig (fiscal year, country, law-driven flags)
│       │   └── crypto_fifo.py    # Domain types for FIFO engine (CryptoAcquisition, CryptoConsumption, CryptoFifoRealization, AssetFifoResult)
│       ├── application/      # Application layer
│       │   ├── __init__.py
│       │   ├── extraction/      # CSV data parsing package
│       │   │   ├── __init__.py
│       │   │   ├── models.py
│       │   │   ├── contexts.py
│       │   │   ├── state_machine.py
│       │   │   └── processing.py
│       │   ├── crypto/          # Crypto tax reporting package (refactored from god class, ~65% reduction)
│       │   │   ├── __init__.py        # Package exports
│       │   │   ├── aggregation.py     # Capital gains and rewards aggregation functions
│       │   │   ├── chain_derivation.py # Chain derivation from wallet names
│       │   │   ├── classification.py  # Tax classification logic (reward tax status, income codes)
│       │   │   ├── entities.py        # Domain entities for crypto reporting
│       │   │   ├── fifo_helpers.py    # FIFO engine helper functions
│       │   │   ├── loan_activity.py   # Loan activity extraction
│       │   │   ├── ogr_handler.py     # Other Gains Report handling
│       │   │   ├── operator_origin.py # Operator/platform origin resolution
│       │   │   ├── parsing.py         # Koinly report parsing functions
│       │   │   └── validation.py      # Crypto-specific validation functions
│       │   ├── crypto_reporting.py # Thin orchestration layer for crypto reporting
│       │   ├── token_origin.py      # TokenOriginResolver application service
│       │   ├── crypto_fifo/          # FIFO engine package (per CIRS art. 43 n.9)
│       │   │   ├── __init__.py        # public re-exports
│       │   │   ├── _emitters.py       # action emitters: exchange/transfer/fee AcquisitionContext and ConsumptionContext builders
│       │   │   ├── _graph.py          # topological_sort_with_fallback → returns (ordered, cyclic) tuple; callers log their own cycle warnings
│       │   │   ├── contexts.py        # AcquisitionContext, ConsumptionContext, ParsedTxRow
│       │   │   ├── cross_asset.py     # cross-asset exchange resolution
│       │   │   ├── matching.py        # FIFO lot matching
│       │   │   ├── merge.py           # MergedAssetFifoResult (multi-platform carry-over DTO)
│       │   │   ├── parsing.py         # TH loading, discovery, row classification dispatch (imports emitters from _emitters.py)
│       │   │   └── transfer.py        # intra-asset transfer resolution (_order_platforms_for_transfers, _resolve_intra_asset_transfers)
│       │   ├── transformation.py # Capital gains calculation
│       │   └── persisting/     # Excel/CSV generation package
│       │       ├── __init__.py
│       │       ├── excel_utils.py        # auto_column_width (skips formulas), safe_remove_file
│       │       ├── ib_sheet.py           # IB Reporting sheet (capital gains + dividends)
│       │       ├── rollover.py           # Rollover CSV export
│       │       ├── workbook_builder.py   # Orchestrator: creates workbook, delegates to sheet writers
│       │       ├── crypto_gains_sheet.py       # Crypto Gains tab
│       │       ├── crypto_supplementary_sheet.py  # Crypto Supplementary tab
│       │       ├── crypto_reconciliation_sheet.py  # Crypto Reconciliation tab
│       │       ├── loan_activity_sheet.py      # Loan Activity tab (per-asset balances)
│       │       └── assumptions_sheet.py        # Platform Assumptions tab (operator manifest)
│       └── infrastructure/    # Infrastructure layer
│           ├── __init__.py
│           ├── config.py        # Configuration management
│           ├── isin_country.py  # ISIN to country resolution
│           ├── koinly_parser.py # Shared Koinly CSV parsing utilities
│           ├── logging_config.py # Logging configuration
│           └── validation.py    # Input validation
├── tests/                  # Test suite
│   ├── unit/               # Unit tests (401 unit-marked tests)
│   │   ├── domain/         # Domain layer unit tests
│   │   ├── infrastructure/ # Infrastructure layer unit tests
│   │   └── application/    # Application layer unit tests
│   │       └── persisting/ # Persisting module unit tests
│   ├── integration/        # Integration tests (10 integration-marked tests)
│   ├── end_to_end/         # End-to-end tests (26 e2e-marked tests)
│   └── conftest.py         # Pytest configuration and fixtures
├── resources/              # Data directories
│   ├── source/             # Input CSV files
│   └── result/             # Generated reports
├── pyproject.toml          # Project configuration, dependencies, and CLI entry point
├── config.ini              # Application configuration
├── README.md               # Project documentation
└── CLAUDE.md              # This file - Claude Code guidance
```

## Lessons Learned

See full details, pre-commit checklist, and QA commands in `docs/domain/development_lessons.md`.
