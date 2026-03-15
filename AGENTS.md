# CLAUDE.md / AGENTS.md

This file provides guidance to coding agents when working with code in this repository.

## Instruction Synchronization

- `CLAUDE.md` and `AGENTS.md` must always stay synchronized.
- After each update to the instructions in either file, immediately apply the same update to the other file.

## Instruction Rules

### 1. Reusable Engineering Rules

- For numeric fields from external reports, do not assume one locale. Detect thousands/decimal separators or fail with a clear error.
- Do not classify values with a leading zero integer part (for example `0,001` or `0.001`) as thousands-grouped numbers.
- A value with exactly one dot-grouped triplet (e.g. `1.234`) is ambiguous between decimal point and thousands separator — raise a clear error, do not guess. Only multi-group dot patterns (e.g. `1.234.567`) are unambiguously European thousands and may have dots stripped.
- Always use f-strings in exception constructors: `raise SomeError(f"Row {n}: bad value {v}")`. Never pass multiple positional args to an exception constructor — `SomeError("msg %s", value)` stores a raw tuple and produces unreadable output.
- When parsing files row-by-row, catch errors per-row (log a warning and skip the row). Do not let a single bad row propagate to a broad outer `except` that silently discards the entire dataset.
- When an optional column is absent from a parsed CSV header, default the extracted value to a safe sentinel (e.g. `"0"` for fees) rather than empty string — downstream code such as `Decimal("")` will crash.

### 2. Repository Style and Conventions

- Koinly source discovery must be year-agnostic (`koinly*`) and prefer a year matching parsed IB data when available.
- If an inferred IB tax year exists and the selected Koinly directory year differs, skip crypto loading for that run.
- Dividend aggregation must validate that all rows for a symbol share the same currency; a mismatch is invalid data and must raise `FileProcessingError` immediately (fail fast).
- `TradeDate` is a `NamedTuple(year, month, day)` — do not call `.date()` on it (no such method). Use it directly in comparisons and log messages, or call `.to_datetime()` to get a `datetime`.
- When classifying a dividend row as withholding tax, match only the literal string `"Withholding Tax"` — never match on bare `"Tax"`. Dividend descriptions routinely contain "Tax" as a word fragment (e.g. "Tax-Exempt Interest").

### 3. Repository Constraints

- Optional crypto ingestion must be non-blocking: when Koinly input is missing, mismatched-year, or unparseable, emit an explicit warning and continue IB report generation without crypto data.
- Partially-unmatched sells (FIFO exhausts all buys before all sells are consumed) must never be silently dropped. Apply the placeholder-buy mechanism to the remaining sell quantity, emit `logger.warning`, and include the resulting capital gain line in the report.
- When the FIFO loop exits with remaining unmatched trades, use `logger.warning` (not `logger.debug`) so data-loss conditions are always visible in production logs.
- When writing a partially-matched buy to the rollover CSV, the fee must be proportional: `proportional_fee = action.fee * (rolled_quantity / original_quantity)`.
- Dividend per-symbol validation must run after all rows for all symbols are accumulated, not after each row. Mid-accumulation state can be temporarily invalid (e.g. reversal arrives before dividend). Symbols that fail post-accumulation validation are skipped with `logger.warning`; they must not abort processing of other symbols.
- Crypto capital gain entries must be aggregated by (exact disposal timestamp, asset, wallet, holding_period) before writing to the report — one line per sale event per holding period, not one per FIFO lot (PT-C-027). Do not remove or bypass `_aggregate_capital_entries()`. The holding_period is included in the aggregation key to preserve the taxable vs exempt breakdown needed for correct filing (PT-C-011: short-term gains are taxable, long-term gains are exempt).
- After aggregation, entries where |gain/loss| < 1 EUR are excluded (PT-C-028). Do not remove or bypass `_filter_immaterial_entries()`. The threshold constant `_MATERIALITY_THRESHOLD` is intentionally a module-level `Final` — do not make it a parameter without a corresponding `crypto_rules.md` update.

### 4. Agent Workflow Rules

- Do not commit changes unless explicitly asked by the user.
- Never add `Co-Authored-By:` to commit messages.
- Always use `uv run pytest` (not `uvx pytest`) — `uvx` runs pytest in an isolated environment without the local `shares_reporting` package installed, causing import failures.
- Write implementation plans to `docs/plans/` in the project repository (not to `~/.claude/plans/` or other external paths).

### 5. Domain Knowledge References

- **Before changing any crypto reporting logic** (Koinly parsing, capital gains aggregation, holding period classification, form field mapping, filtering thresholds), read `docs/domain/crypto_rules.md`. It contains numbered Portuguese tax rules (PT-C-001 … PT-C-029) derived from official AT documents with publication dates. Reference rule numbers in commit messages and code comments when a decision is law-driven (e.g. `# PT-C-008: FIFO mandatory`).
- Each rule in that document carries its source authority level (`[OFFICIAL]` vs `[SECONDARY]`) and the source document date, so you can identify potentially outdated rules when the tax year changes.

## Project Overview

Shares reporting tool is a financial application that processes Interactive Brokers CSV reports to generate tax reporting data for capital gains and dividend income calculations. It matches buy/sell transactions within the same day to calculate capital gains, processes dividend payments with tax information, and generates comprehensive Excel reports with currency conversion.

## Quick Start

```bash
# Using UV (recommended)
uv run shares-reporting

# Direct execution (alternative)
uv run python ./src/shares_reporting/main.py

# Ensure config.ini has all required currency exchange pairs
# Update source files in /resources/source folder
```

## Environment and Dependency Management

### Environment Setup
```bash
# Install UV (one-time setup)
See https://docs.astral.sh/uv/getting-started/installation/

# Install all dependencies (production + development)
uv sync --extra dev

# Install only production dependencies
uv sync

# Activate virtual environment
source .venv/bin/activate

# Exit virtual environment
exit
```

### Development Commands Reference

#### Setup and Dependency Management
```bash
# Add new dependency
uv add <package_name>

# Add development dependency
uv add --dev <package_name>

# Update dependencies
uv lock --upgrade

# Show dependency tree
uv tree

# Check for outdated dependencies
uv pip list --outdated
```

#### Development Workflow
```bash
# Quick development cycle
uv run pytest                     # Run tests (fast)
uvx ruff check . --fix && uvx ruff format .  # Lint and format (fast)
uv run shares-reporting       # Run the application
```

#### Quality Assurance
```bash
# Run all tests
uv run pytest

# Run with coverage
uv run pytest --cov=src --cov-report=html

# Linting and formatting
uvx ruff check .
uvx ruff format .
uv run basedpyright src/ tests/  # Type checking
```

### Common Mistakes to Avoid
- `uvx shares-reporting` - ❌ Won't work (project is not published to PyPI)
- `uvx run shares-reporting` - ❌ Installs 'run' package, not what you want
- `uv run shares-reporting` - ✅ Correct way to run the local application
- `uvx pytest` - ❌ Runs pytest in an isolated env without the local package; `shares_reporting` import will fail
- `uv run pytest` - ✅ Correct way to run tests (uses project's venv with local package installed)

**Key point**: This project uses a local entry point defined in `pyproject.toml`, not a published PyPI package.

## Architecture

The project follows **professional layered architecture** with **Domain-Driven Design** principles:

### Layered Architecture
- **Domain Layer** (`src/shares_reporting/domain/`): Core business entities and rules
  - `value_objects.py` - TradeDate, Currency, Company, TradeType
  - `entities.py` - TradeAction, TradeCycle, CapitalGainLine
  - `accumulators.py` - CapitalGainLineAccumulator, TradePartsWithinDay
  - `collections.py` - Type aliases and collections
  - `constants.py` - Domain constants
  - `exceptions.py` - Domain exceptions
- **Application Layer** (`src/shares_reporting/application/`): Business logic and orchestration
  - `extraction/` - CSV data parsing package
    - `models.py` - Data structures
    - `contexts.py` - Parsing contexts
    - `state_machine.py` - Parsing state machine
    - `processing.py` - Core processing logic
  - `transformation.py` - Capital gains calculation and trade matching
  - `persisting.py` - Excel report generation with formulas (capital gains + dividend income)
- **Infrastructure Layer** (`src/shares_reporting/infrastructure/`): External concerns
  - `config.py` - Configuration management and currency exchange rates
  - `isin_country.py` - ISIN to country resolution
  - `logging_config.py` - Logging configuration
  - `validation.py` - Input validation
- **Presentation Layer** (`src/shares_reporting/main.py`): Application entry point and orchestration

### Core Business Logic Pipeline

#### Data Processing Flow
The system processes data through a sophisticated tax-compliant pipeline:
1. **Extraction**: `parse_ib_export_all()` parses Interactive Brokers CSV files into domain objects (trades + dividends + security info)
2. **Transformation**: `calculate_fifo_gains()` implements the core capital gains algorithm
3. **Persistence**: `generate_tax_report()` creates Excel reports + `export_rollover_file()` for inventory rollover

#### CSV Extraction Architecture

The `extraction` package uses a **State Machine** pattern to parse complex Interactive Brokers CSV files:

**Components:**
- **`IBCsvStateMachine`**: Orchestrates the parsing process, transitioning between file sections. Supports optional Financial Instrument section validation for different file types.
- **Contexts** (`contexts.py`): Specialized handlers for each CSV section:
  - `FinancialInstrumentContext`: Extracts security info (ISIN, Country).
  - `TradesContext`: Parses trade executions. Trades section is always required for real CSV files.
  - `DividendsContext`: Extracts dividend records.
  - `WithholdingTaxContext`: Parses tax records.
- **Models** (`models.py`): Data structures for raw extracted data (`IBCsvData`, `IBCsvSection`).

**Flow:**
1. `IBCsvStateMachine` reads the CSV row by row.
2. Detects section headers (e.g., "Financial Instrument Information", "Trades").
3. Delegates row processing to the active `BaseSectionContext` subclass.
4. Aggregates results into `IBCsvData` for downstream processing.

**Configuration:**
- **Export files**: Require both Trades and Financial Instrument sections (default behavior)
- **Leftover files**: Require Trades section but Financial Instrument section is optional (for processing legacy trade data without security info)

#### FIFO Algorithm Deep Dive

The `calculate_fifo_gains()` function implements sophisticated capital gains calculation:

**State Machine Design:**
- **Company-Level Processing**: Each company/currency processed independently
- **Daily Bucketing**: `split_by_days()` ensures tax compliance by date grouping
- **FIFO Matching**: `capital_gains_for_company()` with `TradePartsWithinDay` queues
- **Partial Matching**: `allocate_to_gain_line()` handles quantity differences
- **Leftover Management**: `redistribute_unmatched_trades()` for inventory rollover to next year

**Key Components:**
- **`CapitalGainLineAccumulator`**: Builder pattern for capital gain calculations
- **`TradePartsWithinDay`**: FIFO queue ensuring chronological trade matching
- **State Transitions**: Each accumulator tracks buy/sell completion states
- **Validation Rules**: Ensures quantities match and business constraints are met

### Domain Model Details

Rich domain models with proper separation of concerns:
- **Value Objects** (Immutable): TradeDate, Currency, Company, TradeType with validation
- **Entities** (Rich): TradeAction, TradeCycle, CapitalGainLine with business behavior
- **Accumulators**: CapitalGainLineAccumulator, TradePartsWithinDay for complex calculations
- **Collections**: Type aliases for trades, capital gains, and dividend income data structures

**TradeDate key facts**: `TradeDate` is a `NamedTuple(year, month, day)` — it has **no `.date()` method**. Supports `>` / `<` / `==` comparison via tuple ordering. Use it directly in log messages (has `__repr__`) and comparisons. To convert to `datetime`, call `.to_datetime()`.

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
shares-reporting/
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
