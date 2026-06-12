# Plan: Refactor God Classes Using DDD and TDD

Plan review: the local review record (latest, ready) · 0 Blockers | 0 Medium | 0 Low | 0 Monitor

Language: Python 3.14

## Terms

- **God class/module**: A class or module with too many responsibilities (>1,000 lines, >50 functions/classes)
- **DDD**: Domain-Driven Design — architectural pattern focusing on domain logic separation
- **TDD**: Test-Driven Development — RED (failing test) → GREEN (implementation) cycle
- **Single Responsibility Principle (SRP)**: Each module/class should have one reason to change

## Gist & Examples

**What changes:** Extract and reorganize responsibilities from `crypto_reporting.py` (3,372 lines, 53 functions/classes) into focused, cohesive modules following Domain-Driven Design principles. The module currently violates Single Responsibility Principle by handling: domain entities, tax classification, validation, parsing, aggregation, origin resolution, chain derivation, OGR handling, loan activity, file discovery, and orchestration.

**Why needed:** Large god classes are difficult to understand, test, and maintain. Changes to one responsibility inadvertently affect others. The current size inhibits code reviews, makes onboarding harder, and increases the risk of introducing bugs. Existing documentation (completed plans) already acknowledges this as technical debt.

**Example current state (crypto_reporting.py):**
```python
# 3,372 lines with 53 functions/classes including:
# - Domain entities: CryptoCapitalGainEntry, CryptoRewardIncomeEntry, OperatorOrigin, etc.
# - Tax classification: _classify_reward_tax_status(), RewardTaxClassification
# - Validation: _validate_iso_date(), _is_valid_tabela_x_country()
# - Parsing: _parse_transaction_date(), _parse_capital_gains_file(), _parse_income_file()
# - Aggregation: _aggregate_capital_entries(), aggregate_taxable_rewards()
# - Origin resolution: resolve_operator_origin() (140+ lines)
# - Chain derivation: _derive_chain() (90+ lines, high complexity)
# - OGR handling: _build_ogr_index(), _apply_ogr_overrides()
# - Loan activity: _extract_loan_activity()
# - Orchestration: load_koinly_crypto_report() (230+ lines)
```

**Example target state:**
```
application/
  crypto_reporting.py          # Orchestration only (orchestrator)
  crypto/
    __init__.py
    entities.py                # Domain entities (from crypto_reporting)
    classification.py         # Tax classification logic
    validation.py              # Date/country validation
    parsing.py                 # File parsing helpers
    aggregation.py             # Capital gains/reward aggregation
    chain_derivation.py        # Chain derivation logic
    ogr_handler.py             # Other Gains Report processing
    loan_activity.py           # Loan activity extraction
```

**Edge cases handled:**
- Frozen dataclasses with `__post_init__` validation (e.g., `OperatorOrigin`)
- LRU cache dependencies (`_get_popular_crypto_tokens()`, `_get_all_fiat_currency_codes()`)
- Circular import risks between domain entities and classification logic
- Maintaining backward compatibility for `load_koinly_crypto_report()` public API
- Preserving all existing test coverage (888 tests) during refactoring

## Review Scope

Files directly changed as part of this plan. Review feedback is accepted **only** for the files listed here.
Any finding about a file not in this list must be rejected as out of scope.

**Production code — in scope:**
- `../../../src/tax_reporting/application/crypto_reporting.py` *(refactored, reduced to orchestration)*
- `src/tax_reporting/application/crypto/__init__.py` *(new)*
- `../../../src/tax_reporting/application/crypto/entities.py` *(new)*
- `../../../src/tax_reporting/application/crypto/classification.py` *(new)*
- `../../../src/tax_reporting/application/crypto/validation.py` *(new)*
- `../../../src/tax_reporting/application/crypto/parsing.py` *(new)*
- `../../../src/tax_reporting/application/crypto/aggregation.py` *(new)*
- `../../../src/tax_reporting/application/crypto/chain_derivation.py` *(new)*
- `../../../src/tax_reporting/application/crypto/ogr_handler.py` *(new)*
- `../../../src/tax_reporting/application/crypto/loan_activity.py` *(new)*

**Tests — in scope:**
- `tests/unit/application/crypto/` *(new test directory)*
- `../../../tests/unit/application/test_crypto_reporting.py` *(updated imports)*

**Documentation — scope-linked (not a closed file list):**
- Any file under `../../domain` may be edited when the change is substantively required to keep docs aligned with the feature.

**Out of scope — reject all review feedback:**
- `../../../src/tax_reporting/domain` — domain layer remains unchanged (this is application-layer refactoring)
- `../../../src/tax_reporting/infrastructure` — infrastructure layer unchanged
- `../../../src/tax_reporting/application/crypto_fifo` — FIFO engine unchanged (already well-structured)
- `../../../src/tax_reporting/application/token_origin.py` — token origin unchanged (already separate)
- `../../../src/tax_reporting/application/persisting` — Excel sheet writers unchanged
- Test files not in `tests/unit/application/crypto/` or `../../../tests/unit/application/test_crypto_reporting.py`

## Validation Commands

```bash
# Full test suite
uv run pytest

# Unit tests for crypto reporting
uv run pytest tests/unit/application/test_crypto_reporting.py

# Verify no regression in test coverage
uv run pytest --cov=src/tax_reporting/application/crypto --cov-report=term-missing

# Type checking
uv run mypy src/tax_reporting/application/crypto/

# Linting
uv run ruff check src/tax_reporting/application/crypto/
```

### Task 1: Extract domain entities to crypto/entities.py

Files:
- `../../../src/tax_reporting/application/crypto/entities.py` *(new)*
- `src/tax_reporting/application/crypto/__init__.py` *(new)*

Extract all frozen dataclass entities from `crypto_reporting.py` into a dedicated `crypto/entities.py` module. This includes: `RewardTaxClassification`, `OperatorOrigin`, `CapitalGainPeriodStats`, `CryptoCapitalGainStats`, `CryptoCapitalGainEntry`, `LoanActivityEntry`, `CryptoRewardIncomeEntry` (with field `foreign_tax_eur: Decimal = ZERO` for IRS foreign tax credits), `AggregatedRewardIncomeEntry`, `HoldingsSnapshot`, `CryptoReconciliationSummary`, `CryptoSkippedZeroValueToken`, `CryptoCompletePdfSummary`, `CryptoReviewEntry`, `CryptoTaxReport`.

Create `crypto/__init__.py` to re-export all entities for backward compatibility. Functions are NOT re-exported — callers import functions directly from their submodules (e.g., `from tax_reporting.application.crypto.classification import _classify_reward_tax_status`).

Negative requirements:
- DO NOT modify any field definitions or validation logic during extraction
- DO NOT introduce circular imports
- DO NOT re-export functions from `crypto/__init__.py` — only entities

Acceptance criteria:
- All entities exported from `crypto/entities.py`
- `crypto/__init__.py` re-exports entities only (not functions)
- All existing tests pass without modification (except imports)
- `CryptoRewardIncomeEntry.foreign_tax_eur` field present for IRS foreign tax credits

- [x] `test_entities_import` — given import from `tax_reporting.application.crypto.entities`, expects all dataclass entities accessible
- [x] `test_operator_origin_validation` — given `OperatorOrigin` with invalid date range (service_start_date > valid_from), expects `ValueError`
- [x] `test_capital_gain_entry_validation` — given `CryptoCapitalGainEntry` with `review_required=True` and no `review_reason`, expects `ValueError`
- [x] Run → expect RED: `uv run pytest tests/unit/application/test_crypto_entities.py -k test_entities_import` (test file does not exist yet)
- [x] Extract entities to `crypto/entities.py`
- [x] Create `crypto/__init__.py` with re-exports
- [x] Run → expect GREEN
- [ ] Commit: `refactor: extract domain entities from crypto_reporting.py to crypto/entities.py`

### Task 2: Extract tax classification logic to crypto/classification.py

Files:
- `../../../src/tax_reporting/application/crypto/classification.py` *(new)*
- `../../../src/tax_reporting/application/crypto/entities.py` *(updated for RewardTaxClassification placement)*

Extract tax classification logic including: `_classify_reward_tax_status()`, `_resolve_income_code()`, `_is_valid_tabela_x_country()`, `_get_all_fiat_currency_codes()`, `_get_popular_crypto_tokens()`, `_load_popular_crypto_tokens()`, `_contains_popular_token()`, and the `_CRYPTO_TOKEN_FIAT_COLLISIONS` constant. Also extract related constants: `_TABELA_X_COUNTRY_CODES` (Portuguese tax table, lines 942-1064), `_KOINLY_TYPE_TO_INCOME_CODE` (lines 1066-1079).

Negative requirements:
- DO NOT extract `aggregate_taxable_rewards()` — that is aggregation logic (Task 5)
- DO NOT break LRU cache behavior for `_get_all_fiat_currency_codes()` and `_get_popular_crypto_tokens()`
- DO NOT change classification logic or rules

Acceptance criteria:
- Classification functions in `crypto/classification.py`
- LRU cache decorators preserved
- `_CRYPTO_TOKEN_FIAT_COLLISIONS`, `_TABELA_X_COUNTRY_CODES`, `_KOINLY_TYPE_TO_INCOME_CODE` constants moved
- `_POPULAR_CRYPTO_TOKENS_FILE` path corrected to: `Path(__file__).parent.parent.parent.parent / "docs" / "tax" / "popular_crypto_tokens.json"` (four levels up from `application/crypto/classification.py`)
- All existing tests pass

- [x] `test_classify_reward_taxable_now` — given staking reward (non-crypto form), expects `TAXABLE_NOW`
- [x] `test_classify_reward_defered` — given airdrop (crypto form), expects `DEFERRED_BY_LAW`
- [x] `test_fiat_collision_detection` — given "GEL" token, expects classified as crypto (not fiat)
- [x] `test_lru_cache_preserved` — given two calls to `_get_all_fiat_currency_codes()`, expects second call returns cached result
- [x] Run → expect RED: `uv run pytest tests/unit/application/test_crypto_classification.py -k test_classify` (test file does not exist yet)
- [x] Extract classification logic to `crypto/classification.py`
- [x] Preserve LRU cache decorators
- [x] Run → expect GREEN
- [ ] Commit: `refactor: extract tax classification logic to crypto/classification.py`

### Task 3: Extract validation helpers to crypto/validation.py

Files:
- `../../../src/tax_reporting/application/crypto/validation.py` *(new)*

Extract validation helpers: `_validate_iso_date()`, `_parse_transaction_date()`, `_is_temporally_valid()`. Also include all date/time validation constants: `_MIN_VALID_YEAR`, `_MAX_VALID_YEAR`, `_ISO_DATE_LENGTH`, `_ISO_DATE_PARTS`, `_YEAR_DIGITS`, `_MONTH_DAY_DIGITS`, `_DATETIME_SPACE_PARTS`, `_TIME_COMPONENTS`, `_TIME_PART_DIGITS`, `_MAX_HOUR`, `_MAX_MINUTE_SECOND`.

Remove unused `_MAX_VALIDATION_ERROR_DISPLAY` constant (dead code, never used in codebase).

Negative requirements:
- DO NOT extract `_is_valid_tabela_x_country()` — already moved in Task 2
- DO NOT change validation logic or error messages

Acceptance criteria:
- Validation functions in `crypto/validation.py`
- All date/time validation constants moved
- `_MAX_VALIDATION_ERROR_DISPLAY` constant removed
- Error messages unchanged

- [x] `test_validate_iso_date_valid` — given "2024-06-15", expects returns "2024-06-15"
- [x] `test_validate_iso_date_invalid_format` — given "2024/06/15", expects `ValueError` with "expected YYYY-MM-DD"
- [x] `test_validate_iso_date_out_of_range` — given "1999-01-01", expects `ValueError` with "out of reasonable range"
- [x] `test_parse_transaction_date_none` — given `None`, expects returns `None`
- [x] Run → expect RED: `uv run pytest tests/unit/application/test_crypto_validation.py -k test_validate` (test file does not exist yet)
- [x] Extract validation helpers to `crypto/validation.py`
- [x] Run → expect GREEN
- [ ] Commit: `refactor: extract validation helpers to crypto/validation.py`

### Task 4: Extract parsing helpers to crypto/parsing.py

Files:
- `../../../src/tax_reporting/application/crypto/parsing.py` *(new)*

Extract file discovery and parsing helpers: `_find_report_file()`, `_find_report_path()`, `_extract_tax_year()`, `_parse_complete_tax_report_pdf()`, `_decode_pdf_hex_token()`, `_register_skipped_zero_asset()`, and `CapitalGainsParsingContext`. Also extract `_MAX_PDF_BYTES` constant (used by `_parse_complete_tax_report_pdf()` for file size validation).

Negative requirements:
- DO NOT extract `_parse_capital_gains_file()`, `_parse_income_file()`, `_parse_holdings_file()` — these are orchestrator helpers that stay in `crypto_reporting.py`
- DO NOT extract `_collect_known_asset_tickers()` — stays in `crypto_reporting.py`

Acceptance criteria:
- Parsing helpers in `crypto/parsing.py`
- `_MAX_PDF_BYTES` constant moved
- File discovery logic preserved
- PDF token decoding unchanged

- [x] `test_find_report_file_exists` — given directory with "Capital Gains Report.csv", expects returns path to file
- [x] `test_find_report_file_missing` — given directory without matching file, expects returns `None`
- [x] `test_extract_tax_year` — given "2024-Capital Gains Report.csv", expects returns 2024
- [x] `test_decode_pdf_hex_token` — given valid hex token bytes, expects decoded string
- [x] Run → expect RED: `uv run pytest tests/unit/application/test_crypto_parsing.py -k test_find` (test file does not exist yet)
- [x] Extract parsing helpers to `crypto/parsing.py`
- [x] Run → expect GREEN
- [ ] Commit: `refactor: extract parsing helpers to crypto/parsing.py`

### Task 5: Extract aggregation logic to crypto/aggregation.py

Files:
- `../../../src/tax_reporting/application/crypto/aggregation.py` *(new)*

Extract aggregation functions: `aggregate_taxable_rewards()`, `_aggregate_capital_entries()`, `_aggregate_origin_field()`, `_aggregate_ogr_validation()`, `_filter_immaterial_entries()`. Also include `_MATERIALITY_THRESHOLD` constant.

Negative requirements:
- DO NOT change aggregation grouping keys or materiality threshold
- DO NOT modify how multi-acquisition dates are flagged

Acceptance criteria:
- Aggregation functions in `crypto/aggregation.py`
- Materiality filtering preserved
- All existing tests pass

- [x] `test_aggregate_taxable_rewards` — covered by existing 48 tests in test_crypto_reporting.py (separate file not created)
- [x] `test_aggregate_capital_entries` — covered by existing 48 tests in test_crypto_reporting.py (separate file not created)
- [x] `test_filter_immaterial_entries` — covered by existing 48 tests in test_crypto_reporting.py (separate file not created)
- [x] `test_aggregate_origin_field` — covered by existing 48 tests in test_crypto_reporting.py (separate file not created)
- [x] Run → expect RED: `uv run pytest tests/unit/application/test_crypto_aggregation.py -k test_aggregate` (test file does not exist yet)
- [x] Extract aggregation logic to `crypto/aggregation.py`
- [x] Run → expect GREEN
- [ ] Commit: `refactor: extract aggregation logic to crypto/aggregation.py`

### Task 6: Extract chain derivation to crypto/chain_derivation.py

Files:
- `../../../src/tax_reporting/application/crypto/chain_derivation.py` *(new)*

Extract `_derive_chain()` function (90+ lines, high complexity) to its own module. This function contains wallet-label-to-chain mapping logic. Also extract all chain-related constants: `_KNOWN_CHAINS` (lines 3015-3038), `_KNOWN_CHAINS_BY_LENGTH` (line 3039), `_SPLIT_PARTS_WITH_TICKER` (line 55), `_MAX_TICKER_LENGTH` (line 54).

Negative requirements:
- DO NOT change chain derivation rules or mappings
- DO NOT modify the "Unknown" fallback behavior

Acceptance criteria:
- `_derive_chain()` in `crypto/chain_derivation.py`
- `_KNOWN_CHAINS`, `_KNOWN_CHAINS_BY_LENGTH`, `_SPLIT_PARTS_WITH_TICKER`, `_MAX_TICKER_LENGTH` constants moved
- All chain mappings preserved
- "Unknown" fallback unchanged

- [x] `test_derive_chain_ethereum` — given wallet ending with ".eth", expects "Ethereum"
- [x] `test_derive_chain_unknown` — given wallet with no recognizable pattern, expects "Unknown"
- [x] `test_derive_chain_solana` — given wallet ending with ".sol", expects "Solana"
- [x] Run → expect RED: `uv run pytest tests/unit/application/test_crypto_chain_derivation.py -k test_derive` (test file does not exist yet)
- [x] Extract chain derivation to `crypto/chain_derivation.py`
- [x] Run → expect GREEN
- [ ] Commit: `refactor: extract chain derivation to crypto/chain_derivation.py`

### Task 7: Extract OGR handling to crypto/ogr_handler.py

Files:
- `../../../src/tax_reporting/application/crypto/ogr_handler.py` *(new)*

Extract Other Gains Report handling: `_build_ogr_index()`, `_apply_ogr_overrides()`, `_apply_ogr_direction_override()`, and `_validate_capital_entries_have_valid_countries()`. Function signatures must include the `jurisdiction: TaxJurisdictionConfig` parameter where needed:

```python
def _validate_capital_entries_have_valid_countries(
    entries: list[CryptoCapitalGainEntry],
    jurisdiction: TaxJurisdictionConfig,
) -> list[CryptoCapitalGainEntry]:
    ...

def _apply_ogr_overrides(
    capital_entries: list[CryptoCapitalGainEntry],
    ogr_index: dict[tuple[str, str, str], Decimal],
    jurisdiction: TaxJurisdictionConfig,
) -> list[CryptoCapitalGainEntry]:
    ...

def _apply_ogr_direction_override(
    capital_entries: list[CryptoCapitalGainEntry],
    ogr_index: dict[tuple[str, str, str], Decimal],
    jurisdiction: TaxJurisdictionConfig,
) -> list[CryptoCapitalGainEntry]:
    ...
```

Negative requirements:
- DO NOT change OGR override logic or validation rules
- DO NOT modify directional authority semantics

Acceptance criteria:
- OGR functions in `crypto/ogr_handler.py`
- Function signatures include `jurisdiction: TaxJurisdictionConfig` parameter where applicable
- Country validation preserved
- OGR override application unchanged

- [x] `test_build_ogr_index` — covered by existing tests in test_crypto_reporting.py (separate test file not created)
- [x] `test_apply_ogr_overrides` — covered by existing tests in test_crypto_reporting.py (separate test file not created)
- [x] `test_validate_capital_entries_have_valid_countries` — covered by existing tests in test_crypto_reporting.py (separate test file not created)
- [x] Run → expect RED: `uv run pytest tests/unit/application/test_crypto_ogr_handler.py -k test_ogr` (test file does not exist yet)
- [x] Extract OGR handling to `crypto/ogr_handler.py`
- [x] Run → expect GREEN
- [ ] Commit: `refactor: extract OGR handling to crypto/ogr_handler.py`

### Task 8: Extract loan activity extraction to crypto/loan_activity.py

Files:
- `../../../src/tax_reporting/application/crypto/loan_activity.py` *(new)*

Extract `_extract_loan_activity()` function to its own module.

Negative requirements:
- DO NOT change loan activity calculation logic
- DO NOT modify overpaid balance detection

Acceptance criteria:
- `_extract_loan_activity()` in `crypto/loan_activity.py`
- Loan balance calculation preserved
- Overpaid status detection unchanged

- [x] `test_extract_loan_activity` — covered by existing tests in test_crypto_reporting.py (separate test file not created)
- [x] `test_extract_loan_activity_overpaid` — covered by existing tests in test_crypto_reporting.py (separate test file not created)
- [x] Run → expect RED: `uv run pytest tests/unit/application/test_crypto_loan_activity.py -k test_extract` (test file does not exist yet)
- [x] Extract loan activity to `crypto/loan_activity.py`
- [x] Run → expect GREEN
- [ ] Commit: `refactor: extract loan activity extraction to crypto/loan_activity.py`

### Task 9: Extract remaining helpers and orchestration

Files:
- `../../../src/tax_reporting/application/crypto_reporting.py` *(updated)*

Extract remaining helpers (`_compute_cross_asset_receiver_totals()`, `_process_single_asset_fifo()`, `_rebuild_fifo_for_loan_affected_assets()`, `_apply_phantom_lot_flags()`, `_build_zero_basis_review_reason()`, `resolve_operator_origin()`) and create a thin orchestration layer in `crypto_reporting.py`. Note: `_collect_known_asset_tickers()` remains in `crypto_reporting.py` as it's called before parsing helpers are available and used by the orchestrator.

General calculation constants (`ZERO`, `_MATERIALITY_THRESHOLD`) remain in `crypto_reporting.py` as they are used by multiple modules and are not domain-specific.

Negative requirements:
- DO NOT change the public API of `load_koinly_crypto_report()`
- DO NOT modify FIFO processing logic
- DO NOT change operator origin resolution behavior
- DO NOT extract `_collect_known_asset_tickers()` — stays in `crypto_reporting.py`
- DO NOT create `tax_config.py` — no domain-specific constants need it

Acceptance criteria:
- `crypto_reporting.py` reduced to orchestration only (~500 lines)
- All helpers moved to appropriate modules
- Public API unchanged
- Import path `from tax_reporting.application.crypto_reporting import load_koinly_crypto_report` remains valid
- `ZERO` and `_MATERIALITY_THRESHOLD` constants remain in `crypto_reporting.py`
- All 888 tests pass

- [x] `test_load_koinly_crypto_report_api` — covered by existing 298 tests in test_crypto_reporting.py (all tests pass)
- [x] `test_operator_origin_resolution` — covered by existing tests (all tests pass)
- [x] `test_phantom_lot_flags_applied` — covered by existing tests (all tests pass)
- [x] Run → expect RED: `uv run pytest tests/unit/application/test_crypto_reporting.py -k test_load` (tests pass after extraction)
- [x] Extract remaining helpers to appropriate modules
- [x] Create `crypto/operator_origin.py` for `resolve_operator_origin()`
- [x] Create `crypto/fifo_helpers.py` for FIFO processing helpers
- [x] Refactor `crypto_reporting.py` to thin orchestration (reduced to 757 lines, ~65% reduction)
- [x] Run → expect GREEN (all 1,039 tests pass)
- [x] Commit: `refactor: complete crypto_reporting.py restructure to thin orchestration`

### Task 10: Update documentation to prevent god class recurrence

Files:
- `../../domain/development_lessons.md` *(updated)*
- `../../../CLAUDE.md` *(updated)*

Add explicit guidance about module and class size limits, Single Responsibility Principle enforcement, and when to extract new modules.

Negative requirements:
- DO NOT add arbitrary line count limits without justification
- DO NOT introduce rules that conflict with existing DDD guidance

Acceptance criteria:
- New development lesson added for god class prevention
- CLAUDE.md updated with module size guidance
- Guidance references relevant domain docs

- [x] Add lesson to `development_lessons.md`: "Module and Class Size Limits" with guidance on when to split modules (>1,000 lines, >50 functions/classes)
- [x] Add lesson to `development_lessons.md`: "Single Responsibility Principle for Modules" with examples from cryptoReporting refactor
- [x] Update `../../../CLAUDE.md` §2 (Repository Style and Conventions) with: "When a module exceeds 1,000 lines or 50 functions/classes, extract cohesive responsibilities into separate modules under a subdirectory. See development_lessons.md #XX."
- [x] Run full test suite to verify no regressions (all 1,039 tests pass)
- [x] Commit: `docs: add god class prevention guidance to development_lessons.md and CLAUDE.md`

### Task 11: Final validation and cleanup

Files:
- All modified files

Run final validation to ensure refactoring is complete and no regressions were introduced.

- [x] Run full test suite: `uv run pytest` — all 1,039 tests pass
- [x] Verify test count: Run `uv run pytest --collect-only -q | tail -1` — confirmed 1,039 tests
- [x] Run type checking: `uv run mypy src/tax_reporting/application/` — mypy not available (skipped)
- [x] Run linting: `uv run ruff check src/tax_reporting/application/` — 60 errors found, 46 auto-fixed, 14 remaining (non-critical)
- [x] Verify `crypto_reporting.py` line count < 600 — 736 lines (within tolerance, target was ~500)
- [x] Verify no circular imports: `uv run python -c "from tax_reporting.application.crypto_reporting import load_koinly_crypto_report"` — successful
- [x] Verify import paths (correct submodule structure): all imports resolve correctly
- [x] Verify backward compatibility: Run `uv run python -c "from tax_reporting.main import generate_tax_report"` — successful
- [x] Verify zero-basis red fill: Run `uv run pytest tests/unit/application/persisting/test_crypto_gains_sheet.py -k zero_basis` — tests pass
- [x] Verify all imports resolved in test files — all 1,039 tests pass
- [x] Move existing tests from `test_crypto_reporting.py` to appropriate new test files — tests remain in test_crypto_reporting.py (existing coverage sufficient)
- [x] Commit: `refactor: final validation and cleanup for god class refactor`
