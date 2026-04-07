# CLAUDE.md / AGENTS.md

This file provides guidance to coding agents when working with code in this repository.

## Instruction Synchronization

- `CLAUDE.md` and `AGENTS.md` must always stay synchronized.
- After each update to the instructions in either file, immediately apply the same update to the other file.

## Instruction Rules

### 1. Reusable Engineering Rules

- For numeric fields from external reports, detect thousands/decimal separators or fail clearly.
- Do not classify values with a leading zero integer part (for example `0,001` or `0.001`) as thousands-grouped numbers.
- Treat exactly one dot-grouped triplet (for example `1.234`) as ambiguous and raise a clear error. Only multi-group dot patterns (for example `1.234.567`) may be stripped as European thousands.
- Use f-strings in exception constructors; never pass multiple positional args to an exception constructor.
- Catch row-level parse errors per row (warn and skip). Do not let one bad row discard the whole dataset.
- When an optional CSV column is absent, use a safe sentinel (for example `"0"` for fees) rather than `""`.

### 2. Repository Style and Conventions

- Koinly source discovery must be year-agnostic (`koinly*`) and prefer a year matching parsed IB data when available.
- If an inferred IB tax year exists and the selected Koinly directory year differs, skip crypto loading for that run.
- Dividend aggregation must validate one currency per symbol; mismatches must raise `FileProcessingError`.
- `TradeDate` is a `NamedTuple(year, month, day)`. Do not call `.date()` on it; use it directly or call `.to_datetime()`.
- When classifying a dividend row as withholding tax, match only the literal string `"Withholding Tax"` — never match on bare `"Tax"`. Dividend descriptions routinely contain "Tax" as a word fragment (e.g. "Tax-Exempt Interest").
- In `docs/tax/.../official/`, keep only source-origin files. Derived notes and numbered guidance belong outside `official/`, and `sources.md` must record issuing dates.
- For external source archive provenance and freshness checks, see `docs/project-guidelines.md` #1.
- For tax/origin web sources, prefer authoritative PDFs or extracted Markdown/PDF over raw HTML, and reuse local mirrors.
- Under `docs/tax/`, use `*-tax` for tax-law archives and `*-origin` for chain/operator domicile archives.
- Share crypto `País da Fonte` resolution across rewards and capital gains. Never use taxpayer residence.
- Keep the `docs/tax/crypto-origin/` source manifest, registry, and decision log synchronized when changing crypto chain/operator mappings.
- Chain derivation must use deterministic normalization rules and validate against trusted sources in `docs/tax/crypto-origin/`.
- Wallet labels are discovery hints only; final chain/country mappings come from archived operator origin documents.
- When wallet labels don't allow reasonable chain derivation, use `Unknown` explicitly rather than guessing from asset symbols.
- When adding operator mappings with temporal validity: use `service_start_date` for when the platform started offering this service (used for transaction matching), use `valid_from` for when this specific mapping was verified from source documents (used for audit trail), set `service_start_date` before `valid_from` when both are known, and for platforms with unknown verification dates, set `service_start_date` and leave `valid_from` as null.

### 3. Repository Constraints

- Optional crypto ingestion must be non-blocking: when Koinly input is missing, mismatched-year, or unparseable, emit an explicit warning and continue IB report generation without crypto data.
- Partially-unmatched sells (FIFO exhausts all buys before all sells are consumed) must never be silently dropped. Apply the placeholder-buy mechanism to the remaining sell quantity, emit `logger.warning`, and include the resulting capital gain line in the report.
- When the FIFO loop exits with remaining unmatched trades, use `logger.warning` (not `logger.debug`) so data-loss conditions are always visible in production logs.
- When writing a partially-matched buy to the rollover CSV, the fee must be proportional: `proportional_fee = action.fee * (rolled_quantity / original_quantity)`.
- Dividend per-symbol validation must run after all rows for all symbols are accumulated, not after each row. Mid-accumulation state can be temporarily invalid (e.g. reversal arrives before dividend). Symbols that fail post-accumulation validation are skipped with `logger.warning`; they must not abort processing of other symbols.
- Aggregate crypto capital gains by `(disposal_date, asset, platform, holding_period)` before reporting. Do not remove or bypass `_aggregate_capital_entries()`.
- After aggregation, exclude entries where `|gain/loss| < 1 EUR`. Do not remove `_filter_immaterial_entries()` or parameterize `_MATERIALITY_THRESHOLD` without a `crypto_rules.md` update.
- Crypto reward income must be aggregated by `(income_code, source_country)` before inclusion in the IRS-ready filing table. Do not bypass or remove `aggregate_taxable_rewards()`.
- Reward classification into taxable_now vs deferred_by_law must use `_classify_reward_tax_status()` and cite CRG-001/CRG-002 rule IDs.
- Crypto worksheet must present rewards in two sections: IRS-ready filing summary (taxable_now only) and support detail (both classifications).
- The aggregation step must fail with `FileProcessingError` if any taxable-now row cannot be assigned all mandatory IRS fields (valid Tabela X country code).
- When `review_required=True` is set on `CryptoCapitalGainEntry` or `CryptoRewardIncomeEntry`, the `review_reason` field must contain a specific, actionable explanation. The Excel output shows "YES: \<reason\>" rather than a bare boolean. See PT-C-030.

### 4. Agent Workflow Rules

- Examine existing source data files in the repository (e.g., `resources/source/koinly*/`) directly before asking the user to provide samples or examples. Use Glob and Read tools to find and analyze the actual data.
- Do not commit changes unless explicitly asked by the user.
- Never add `Co-Authored-By:` to commit messages.
- Always use `uv run pytest`, not `uvx pytest`.
- Write implementation plans to `docs/plans/` in the project repository, not external paths.

### 5. Domain Knowledge References

- Before changing crypto reporting logic, read `docs/domain/crypto_rules.md`, `docs/domain/crypto_reporting_guidelines.md`, and `docs/domain/crypto_implementation_guidelines.md`. Cite PT-C / CRG rule IDs for law-driven changes.
- Before implementing new crypto features, read `docs/domain/crypto_implementation_guidelines.md` for lessons learned and common pitfalls to avoid.
- Before changing cross-cutting report-generation behavior, read `docs/domain/shares_reporting_guidelines.md` and cite SRG rule IDs for repository-policy changes.
- Before writing implementation plans, read `docs/domain/plan_quality_guidelines.md` for patterns that minimize review iterations.
- Before writing or revising repository walkthroughs or presentation artifacts, read `docs/domain/plan_quality_guidelines.md` for presentation-artifact structure and placement.
- When a crypto presentation or walkthrough makes legal or filing claims, verify the current source set in `docs/tax/portugal-crypto-tax/sources.md` and cite the mirrored official documents.
- Use the authority level and source date in `crypto_rules.md` to check whether a rule may be stale for the current tax year.

## Project Overview

Tax reporting tool processes Interactive Brokers and Koinly exports into Portuguese tax-reporting outputs for capital gains, dividends, and crypto rewards.

## Quick Start

- Main entry point: `uv run tax-reporting`
- Alternative entry point: `uv run python ./src/shares_reporting/main.py`
- For broader setup and command reference, see `README.md`.

## Environment and Dependency Management

- Use `uv`; the project entry point is local, not a published PyPI package.
- Preferred test command: `uv run pytest`
- See `README.md` for setup, dependency management, and the full command catalog.

## Architecture

- Layered architecture:
  - Domain: `src/shares_reporting/domain/`
  - Application: `src/shares_reporting/application/`
  - Infrastructure: `src/shares_reporting/infrastructure/`
  - Presentation: `src/shares_reporting/main.py`
- Core pipeline: extract IB/Koinly data, transform into tax calculations, then persist workbook and rollover outputs.
- For the fuller architectural walkthrough, see `README.md` and the source tree.

## Configuration Management

- Uses Python's `configparser` for INI file handling
- Configuration files: `config.ini` (production) and `tests/config.ini` (testing)
- Both configs have identical structure with three sections:
  - **[COMMON]**: Target currency specification
  - **[EXCHANGE RATES]**: Currency conversion rates (different values for prod/test)
  - **[SECURITY]**: Validation limits (file size, ticker length, allowed extensions, etc.)
- Exchange rates should be updated annually (e.g., from your national central bank)
- Security settings use defaults from code if missing from config file

## Excel Report Features

The application generates professional Excel reports with:

### Capital Gains Section
- Detailed buy/sell transaction matching with FIFO methodology
- Automatic currency conversion with exchange rate tables
- Country of source detection from ISIN data

### Dividend Income Section ("CAPITAL INVESTMENT INCOME")
- Complete dividend reporting with tax information
- Both converted and original currency amounts displayed
- Symbol, Currency, ISIN, and country information
- Gross amount, withholding tax, and net amount calculations

### Report Structure
- **Column Headers**: Clear, descriptive headers with line breaks for readability
- **Currency Conversion**: Automatic conversion using configured exchange rates
- **Formulas**: Excel formulas for dynamic calculations
- **Auto-sizing**: Column widths automatically adjusted for content

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

### Comprehensive Test Suite Overview
The project follows **professional testing best practices** with a **3-tier test architecture** and comprehensive coverage:

### Test Structure
```
tests/
├── unit/          # 156 unit tests - Fast component tests
│   ├── domain/    # Domain layer unit tests
│   ├── infrastructure/  # Infrastructure layer unit tests
│   └── application/ # Application layer unit tests
├── integration/   # 48 integration tests - Component interaction tests
└── end_to_end/    # 6 e2e tests - Full workflow tests
```

### Testing Commands
```bash
# Run all tests
uv run pytest

# Run tests by tier using markers
uv run pytest -m unit         # Unit tests only (fast)
uv run pytest -m integration  # Integration tests only
uv run pytest -m e2e          # End-to-end tests only

# Run tests by directory
uv run pytest tests/unit/             # All unit tests
uv run pytest tests/unit/domain/      # Domain layer tests
uv run pytest tests/unit/infrastructure/  # Infrastructure tests
uv run pytest tests/unit/application/     # Application layer tests
uv run pytest tests/integration/      # Integration tests
uv run pytest tests/end_to_end/       # End-to-end tests

# Run with coverage
uv run pytest --cov=src --cov-report=html

# Run specific test patterns
uv run pytest -k "test_specific"     # Run tests matching pattern
uv run pytest tests/unit/domain/test_value_objects.py  # Specific test file

# Development workflow
uv run pytest -m unit -x            # Run unit tests, stop on first failure
uv run pytest -m unit --tb=short    # Short traceback for faster debugging
```

### Testing Guidelines

#### Core Testing Principles
- **Unit Tests**: Test individual components in isolation
- **Integration Tests**: Test component interactions
- **Edge Cases**: Comprehensive error handling and boundary conditions
- **Test Coverage**: High coverage of business logic and validation
- **Descriptive Naming**: Clear test names that document behavior
- **Debugging**: Use `breakpoint()` or `import pdb; pdb.set_trace()`

#### Pytest Best Practices

**Critical Rule**: Do not import pytest fixtures - they are injected automatically by name.

**Available Fixtures Without Import**:
- `tmp_path` - Filesystem operations (pathlib.Path)
- `capsys` - Capture stdout/stderr
- `caplog` - Capture logging output
- `monkeypatch` - Patch environment/attributes
- `request` - Test context and metadata

**Example Usage**:
```python
# ✅ GOOD - Use directly without imports
def test_something(tmp_path):
    test_file = tmp_path / "test.txt"
    test_file.write_text("content")

# ❌ AVOID - Unnecessary Path import
from pathlib import Path
def test_with_file(tmp_path):
    file_path = Path(tmp_path) / "test.txt"  # tmp_path is already Path
```

**Import Cleanliness Rules**:
- **Remove unused imports**: If Ruff reports F401, delete the import unless justified
- **Assume Ruff is correct**: Fix the code, not the linter, unless proven false positive
- **Only import when used**:
  - ✅ When instantiating: `Path("some/path")`
  - ✅ When used in type annotations: `def func(file_path: Path) -> None`
  - ❌ When using injected fixtures: `def test(tmp_path):` (no import needed)

#### Test Value Assessment
Ask these questions for every test:
1. **Does it test meaningful business logic** that could break in production?
2. **Does it test real edge cases** from actual data/usage?
3. **Is it testing something not already covered** by other tests?
4. **Would a failure provide actionable information** for debugging?

**High-Value Test Patterns to Include**:
- Complex IB CSV description formats
- Missing data scenarios with error indicators  
- Tax calculation and matching logic
- Integration flows between components
- Error handling and validation paths
- Performance with realistic datasets
- Real edge cases from actual exports

**Low-Value Test Patterns to Avoid**:
- Testing zero amounts (if positives work, zeros work too)
- Testing basic string parsing that should work anyway
- Testing simple symbol matching (AAPL/MSFT basics)
- Testing very small decimal amounts without business meaning
- Testing trivial cases that would be caught by other tests

## Development Best Practices

### Incremental Development with Testing
**Test-driven approach for complex changes**:
1. **Write failing tests first** to understand expected behavior
2. **Implement changes** with comprehensive test coverage
3. **Run the full test suite** to ensure no regressions
4. **Review and clean up** low-value tests after functionality works

### API Design Consistency
**Maintain consistent patterns across similar functions**:
```python
# ✅ GOOD - Consistent parameter patterns across context methods
def process_header(self, row: list[str], row_number: int) -> None:
def process_data_row(self, row: list[str], row_number: int) -> None:

# ✅ GOOD - Consistent error message patterns (f-string, not %d/%s tuple args)
raise FileProcessingError(f"Row {row_number}: Invalid {section_name} format")
```

### Code Review Checklist
**Before considering code complete, verify**:
- [ ] All required parameters are truly required (no misleading defaults)
- [ ] Error messages include sufficient context (row numbers, problematic data)
- [ ] Exception chaining preserves original error information  
- [ ] Logging uses parameterized format consistently
- [ ] Fail fast logic is applied appropriately (missing vs invalid data)
- [ ] Tests provide real value and test meaningful edge cases
- [ ] API usage is correct (high-level vs low-level functions)
- [ ] No pytest fixture imports (tmp_path, capsys, caplog, monkeypatch, request)
- [ ] No unused imports (fix Ruff F401 errors unless proven false positive)
- [ ] Path imports only when actually needed (not for injected fixtures)

### Documentation Maintenance
**Keep documentation current with code changes**:
- Update CLAUDE.md when new patterns emerge
- Include examples of both good and bad practices
- Document decision rationale for architectural choices
- Maintain clear separation between testing vs script guidelines

## Code Quality Standards

### Linting and Formatting
- **Ruff** is the primary linter and formatter (configured in `pyproject.toml`)
- **Target**: Python 3.13 (`target-version = "py313"`)
- **Line length**: 120 characters maximum
- **Enabled rulesets**: `E`, `F`, `UP`, `B`, `SIM`, `I`, `N`, `ARG`, `FA`, `DTZ`, `PTH`, `TD`, `FIX`, `RSE`, `S`, `C4`, `PT`, `D`, `PL`
- **Docstring convention**: Google-style (`pydocstyle`)

### Documentation Best Practices

#### When to Write Docstrings
- **Always document**:
  - Public modules (`__init__.py`, top-level modules)
  - Public classes and their `__init__` methods
  - Public functions and methods with complex logic or non-obvious behavior
  - Functions with multiple parameters or return values

- **Skip docstrings for**:
  - Self-explanatory property getters/setters (e.g., `def get_currency(self): return self.currency`)
  - Trivial magic methods like `__repr__` when the implementation is obvious
  - Private methods (`_method_name`) when the name and implementation are clear
  - Test functions (docstrings optional in tests per `pyproject.toml`)

#### Docstring Style (Google Convention)
```python
def complex_function(param1: str, param2: int) -> dict:
    """Brief one-line summary ending with a period.

    Extended description if needed. Explain the purpose, algorithm,
    or any non-obvious behavior.

    Args:
        param1: Description of param1.
        param2: Description of param2.

    Returns:
        Description of return value.

    Raises:
        ValueError: When validation fails.
    """
```

#### Package `__init__.py` Docstrings
Use multi-line format with summary + description:
```python
"""Package name for specific purpose.

Extended description explaining what the package contains,
its responsibilities, and key modules or functionality.
"""
```

### Code Style Guidelines
- **Type hints**: Use modern syntax (`X | Y` instead of `Union[X, Y]`) with `from __future__ import annotations`
- **Imports**: Sorted automatically by Ruff (isort)
- **Magic numbers**: Replace with named constants (except in tests)
- **Datetime**: Use `datetime.UTC` instead of `timezone.utc` (Python 3.11+)
- **Path handling**: Use `pathlib.Path` instead of `os.path`
- **Logging**: Use lazy formatting (`logger.info("Message: %s", value)` not f-strings)
- **Error Messages**: Use f-strings for exception messages (`raise ValueError(f"Invalid value: {value}")`)

#### Method Parameter Design Principles
**Required vs Optional Parameters**: 
- **Required**: Use when data is essential for correct operation (e.g., `row_number` for error context)
- **Optional**: Use only when a sensible default exists and doesn't compromise functionality
- **Avoid defaults of 0** for identifiers/indices that need real values

```python
# ✅ GOOD - Required parameter for essential data
def process_data_row(self, row: list[str], row_number: int) -> None:

# ❌ AVOID - Default value for essential context
def process_data_row(self, row: list[str], row_number: int = 0) -> None:
```

### Complexity Management
- Functions with high complexity (`PLR0912`, `PLR0915`) should be refactored when possible
- If refactoring is too risky, use explicit `# noqa: PLR0912, PLR0915` with a comment explaining why
- Avoid deeply nested logic; extract helper functions

## Data Handling Principles

### Missing Data: Process with Error Indicators
**Rule**: When data is missing but can be added manually later, process with clear error indicators.

**Examples of Missing Data**:
- Missing ISIN for a known symbol
- Missing country information
- Missing security details that can be manually researched

**Required Actions**:
1. **Always log an ERROR** (not just warning) with actionable guidance
2. **Include the data in output** with clear error indicators 
3. **Make problems visible** to users (Excel highlighting, warning messages)
4. **Preserve financial amounts** - never lose monetary data due to missing supplementary info
5. **Use clear identifiers** like "MISSING_ISIN_REQUIRES_ATTENTION" in output

**Code Pattern**:
```python
# ✅ GOOD - Process missing ISIN with error indicators
if not isin:
    logger.error("Missing security information for symbol %s - including dividend data but requires manual review. Please add this security to your IB account or verify the symbol.", symbol)
    isin = "MISSING_ISIN_REQUIRES_ATTENTION"
    country = "UNKNOWN_COUNTRY"
    # Continue processing with marked data
```

### Invalid Data: Fail Fast
**Rule**: When data is invalid, corrupted, or incorrectly formatted, stop processing immediately with detailed error information.

**Examples of Invalid Data**:
- Invalid CSV file format or structure
- Invalid monetary amounts (non-numeric values)
- Invalid date formats
- Missing required columns in CSV sections
- Corrupted data that cannot be reasonably processed
- Invalid row formats that break processing logic

**Required Actions**:
1. **Stop processing immediately** - do not continue with invalid data
2. **Provide detailed error information** including row numbers and specific issues
3. **Use proper exception chaining** to preserve stack traces
4. **Include contextual information** (symbol, row number, expected format)

**Code Pattern**:
```python
# ✅ GOOD - Fail fast on invalid data
try:
    amount = Decimal(amount_str)
except ValueError as e:
    raise FileProcessingError("Row %d: Invalid monetary amount '%s' for symbol %s - expected decimal number", row_number, amount_str, symbol) from e

# ✅ GOOD - Fail fast on structural issues
if len(row) < MIN_REQUIRED_COLUMNS:
    raise FileProcessingError("Row %d: Invalid row format - expected at least %d columns, got %d: %s", row_number, MIN_REQUIRED_COLUMNS, len(row), row)
```

### Key Principles
- **Never silently skip expected data** - either mark it clearly or fail fast
- **Preserve financial integrity** - monetary amounts should never be lost due to processing issues
- **Clear user communication** - errors must be visible and actionable
- **Distinguish missing vs invalid** - missing data can be processed with warnings, invalid data requires immediate failure

## Error Handling Patterns

- Always include row number, symbol, and specific issue in error messages.
- Use `from e` exception chaining to preserve original context.
- **Logging**: parameterised format `logger.error("Row %d: bad value %s", row, val)`.
- **Exceptions**: f-strings `raise ValueError(f"Row {row}: bad value {val}")` — see §1 Instruction Rules.

## Project Structure

```
tax-reporting/
├── src/                     # Source code (src layout)
│   └── shares_reporting/
│       ├── __init__.py        # Package exports
│       ├── main.py           # Application entry point
│       ├── domain/           # Domain layer
│       │   ├── __init__.py
│       │   ├── value_objects.py   # TradeDate, Currency, Company, TradeType
│       │   ├── entities.py      # TradeAction, TradeCycle, CapitalGainLine
│       │   ├── accumulators.py   # CapitalGainLineAccumulator, TradePartsWithinDay
│       │   ├── collections.py    # Type aliases and utilities
│       │   ├── constants.py      # Domain constants
│       │   └── exceptions.py     # Domain exceptions
│       ├── application/      # Application layer
│       │   ├── __init__.py
│       │   ├── extraction/      # CSV data parsing package
│       │   │   ├── __init__.py
│       │   │   ├── models.py
│       │   │   ├── contexts.py
│       │   │   ├── state_machine.py
│       │   │   └── processing.py
│       │   ├── transformation.py # Capital gains calculation
│       │   └── persisting.py    # Excel/CSV generation
│       └── infrastructure/    # Infrastructure layer
│           ├── __init__.py
│           ├── config.py        # Configuration management
│           ├── isin_country.py  # ISIN to country resolution
│           ├── logging_config.py # Logging configuration
│           └── validation.py    # Input validation
├── tests/                  # Test suite
│   ├── unit/               # Unit tests (156 tests)
│   │   ├── domain/         # Domain layer unit tests
│   │   ├── infrastructure/ # Infrastructure layer unit tests
│   │   └── application/    # Application layer unit tests
│   ├── integration/        # Integration tests (48 tests)
│   ├── end_to_end/         # End-to-end tests (6 tests)
│   └── conftest.py         # Pytest configuration and fixtures
├── resources/              # Data directories
│   ├── source/             # Input CSV files
│   └── result/             # Generated reports
├── pyproject.toml          # Poetry configuration and dependencies
├── config.ini              # Application configuration
├── README.md               # Project documentation
└── CLAUDE.md              # This file - Claude Code guidance
```

## Lessons Learned

See full details, pre-commit checklist, and QA commands in `docs/domain/development_lessons.md`.
