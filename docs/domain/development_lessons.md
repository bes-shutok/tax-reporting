# Development Lessons: Common Issues and Prevention Strategies

Canonical reference for recurring patterns observed during code fixes in this codebase.
Agents should read this alongside the main instruction rules in CLAUDE.md.

---

## 1. Code Quality and Duplication
- Always check for duplicate test methods or functions before adding new code.
- Command: `grep -n "def method_name" . -r`

## 2. Type Safety and Annotations
- Add `@override` to methods overriding base class methods.
- Annotate all class attributes with types unless class is marked `@final`.
- Prefix unused parameters with `_param`; use bare `_` for completely ignored params.

```python
class MyClass:
    attr1: Type1

    @override
    def method_name(self, _param: UnusedType) -> None:
        pass
```

## 3. String and Code Formatting
- Keep f-strings on single lines or use explicit parenthesised concatenation.
- Break long lines with `(...)` grouping:

```python
# Good
error_message = (
    f"Error in row {row_number}: "
    f"Expected format X, got Y"
)
```

## 4. Function and Method Design
- Use parameter names that match the interface being implemented.
  Example: `lambda optionstr: optionstr` not `lambda option: option` for ConfigParser.
- Required vs Optional: use required parameters for essential data; only use defaults when a sensible default exists.

## 5. Dependencies and Imports
- Check all imports against declared dependencies before submitting.
- Import from public `__all__` exports; avoid `_private` imports in tests unless necessary.
- Run tests early to catch missing imports.

## 6. Testing Best Practices
- 3-tier structure: unit (`tests/unit/`) → integration (`tests/integration/`) → e2e (`tests/end_to_end/`).
- Markers: `@pytest.mark.unit`, `@pytest.mark.integration`, `@pytest.mark.e2e`.
- Unit tests may access internal functions; integration/e2e use only public APIs.
- Edge case coverage: When testing string sanitization, validation, or parsing functions, explicitly test edge cases:
  - Empty strings and whitespace-only inputs
  - Multi-byte UTF-8 characters
  - Control characters (null, newline, carriage return)
  - Multi-character prefixes (e.g., `==`, `++` vs single `=`, `+`)
  - Padded inputs (leading/trailing whitespace)
- Error path coverage: Test double-failure scenarios where multiple error conditions occur together (e.g., aggregation fails AND workbook.close fails).

## 7. Excel Output Security
- All external data string fields (from any provider: Koinly, IB, etc.) must be wrapped with `safe_cell_value()` before writing to Excel cells. Formula injection vulnerabilities exist if even one field is unprotected.
- Check consistency: if most fields in a section use `safe_cell_value()`, any unprotected field is likely a bug.
- Common unprotected fields to watch: `review_reason`, `description`, chain names, wallet labels, platform names.

## 8. Type Annotation Specificity
- Use specific element types for generic collections: `list[Type] | None` instead of `list | None`.
- Specific types improve documentation, IDE autocomplete, and static analysis.
- When the type is imported only for annotations, keep it inside `TYPE_CHECKING` block.

## 9. Exception Handler Specificity
- Catch specific exception types (`FileProcessingError`, `ValueError`) instead of broad `Exception`.
- Broad exception handlers mask programming errors and make debugging harder.
- When a function documents raising a specific exception, catch that exact type in callers.

## 10. Refactoring and Maintenance
- Make small incremental changes and run `uv run pytest` after each one.
- Remove temporary scripts immediately after use.

## 11. Error Handling and Logging
- Always include row numbers and problematic data in error messages.
- Use `from e` exception chaining to preserve original context.
- Logging: parameterised format (`%s`). Exceptions: f-strings. See §1 Instruction Rules for full detail.

## 12. API Design for Production vs Testing
- Do not add features or parameters solely to satisfy tests; adjust tests to match production patterns instead.
- When tests need special handling, first try to make tests reflect real usage before adding complexity to production code.

## 13. Test Path and Fixture Management
- Never use `Path(__file__).parent.parent` in tests; it breaks when files move.
- Always use pytest fixtures (`tmp_path`, `tmp_path_factory`) for file operations:

```python
# ✅ GOOD
@pytest.fixture
def test_file(tmp_path: Path) -> Path:
    f = tmp_path / "test.csv"
    f.write_text("test,data")
    return f
```

## 14. Simplify Unnecessary Complexity (YAGNI)
- Remove parameters that always have the same value (e.g. `require_trades_section=True` → hardcode it).
- Do not add features "just in case".

## 15. Excel/openpyxl Column Width
- openpyxl stores formulas as strings; `cell.value` returns the raw formula (e.g., `"=USD EUR*(1234.56)"`), not the computed result.
- Auto-width logic must skip formula cells (`cell.data_type == "f"`) and size columns from headers + non-formula values only.
- The crypto sheet auto-width block has a missing `default=0` in `max()` that raises `ValueError` on empty columns; always provide `default=0` when calling `max()` on a generator.

## 16. Test Real Behavior, Not Implementation Details
- Verify that a feature works end-to-end, not just that it returns a certain value.
- Use realistic test data; check that integrated components produce correct outputs.

## 17. Test CSV Data Construction: Column Alignment

See `~/Projects/.ai-playbook/python_guidelines.md` #1 for full prevention rules.
Repo context: Koinly `_TH_HEADER` has 20 columns; hand-counting commas is the biggest source of wasted debug iterations.

## 15. Post-Extraction Cleanup

See `~/Projects/.ai-playbook/python_guidelines.md` #2 for full cleanup procedure.
Repo context: past extractions (crypto_reporting.py → token_origin.py + koinly_parser.py) left unused imports and dead code.

## 16. Aggregation Logic: Test Both Directions

See `~/Projects/.ai-playbook/agent_workflow_guidelines.md` #1.
Repo context: LP liquidity operations; fixing "in" direction broke "out" because liquidity out produces multiple outputs from one input.

## 17. Operator Mapping Field Semantics (`service_start_date` / `valid_from`)

See `~/Projects/.ai-playbook/agent_workflow_guidelines.md` #3 for the generic field-semantics lesson.
Repo-specific constraint: `valid_from` is audit-only (when the mapping was verified from source docs). `service_start_date` is for transaction matching (when the platform started offering this service). Never use `valid_from` as a matching gate. When both are known, `service_start_date <= valid_from`.

## 18. Review Agent False Positives

See `~/Projects/.ai-playbook/agent_workflow_guidelines.md` #2.

## 19. Descriptive Output Labels

See `~/Projects/.ai-playbook/coding_guidelines.md` #9 for the canonical rule.
Repo context: crypto gains sheet headers renamed from terse Koinly CSV names to self-explanatory terms (e.g. "Quantity" not "Amount", "Acquisition Cost (EUR)" not "Cost (EUR)").

## 20. Frozen Dataclass `__post_init__` Field Normalization

A frozen dataclass cannot assign to its own fields in `__post_init__`. Use `object.__setattr__(self, field, value)` to normalize fields (e.g. converting empty strings to `None`) during validation. Without this, the normalization is computed but silently discarded.

## 21. Date Comparison Must Use Date Objects, Not Strings

Comparing ISO date strings with `<` / `>=` works for same-length same-format strings but silently produces wrong results when formats differ (e.g. `"2025-3-5" < "2025-12-01"` is `True` but `"2025-3-5" < "2025-10-01"` is `False` because `"3"` > `"1"`). Always parse to `date` objects before comparison.

## 22. ISO Date Validation Must Enforce Zero-Padding

`map(int, "2025-3-5".split("-"))` succeeds, but `YYYY-MM-DD` requires two-digit month and day. Validate each component's string length: year 4 digits, month 2 digits, day 2 digits. Same applies to `HH:MM:SS` time components.

## 23. Three-Way Doc Sync: Code, Registry, Decision Log

When a feature uses both code-based mappings and canonical documentation (e.g. operator origin registry, mapping decision log), any field change must be applied to all three in the same commit. Code review consistently catches doc drift as a finding. Add a verification step to the plan: "grep for changed field names in registry and decision log."

## 24. Consult Decision Points Before Tax-Treatment Assumptions

Before discussing, proposing, or implementing any crypto tax treatment (cost-basis method, taxability of swaps, Koinly settings), check `docs/tax/decision_points/` first. In this session, incorrect assumptions about crypto-to-crypto swap taxation led to a wrong recommendation (turn FMV on) when the answer was already documented in DP-002 (carry-over mandated by CIRS Art. 10(20)). Decision points exist specifically to prevent re-litigating settled questions.

## 25. Integration Test Fixture Consistency for Computed Fields

When adding a computed field to a data class used in integration tests, update ALL construction sites to compute the field from actual test data, not from a zero-valued or empty placeholder. Using `CryptoCapitalGainStats.from_entries([])` while `capital_entries` has real data produces inconsistent output (statistics section shows all zeros next to non-zero capital gains). Search for all construction sites with `grep -n "DataClass("` before committing; each site must derive the new field from its own test data.

## 26. Atomic File Replacement: No Pre-Deletion

Never call `safe_remove_file(target)` before `temp_path.replace(target)`. On POSIX, `Path.replace()` atomically replaces the target file. The "remove then replace" sequence breaks atomicity: if `replace()` fails after the removal, the old report is permanently lost and the new file is stranded in `.tmp`. Correct pattern:

```python
# ✅ CORRECT: atomic on POSIX
workbook.save(temp_path)
temp_path.replace(target)  # replaces atomically; no pre-deletion needed

# ❌ WRONG: data loss window between these two lines
safe_remove_file(target)
temp_path.replace(target)
```

## 27. Default Value Assignment Before Derived Computation

Always apply defaults to source variables before computing derived values from them. Anti-pattern:

```python
# ❌ WRONG: log_file computed from None even when output_dir has a default
log_file = output_dir / "report.log" if output_dir else None
output_dir = output_dir or DEFAULT_OUTPUT_DIR

# ✅ CORRECT: apply default first, then compute derived values
output_dir = output_dir or DEFAULT_OUTPUT_DIR
log_file = output_dir / "report.log"
```

Any variable that depends on another must be computed after all defaults are applied to its source.

## 28. Don't Use `_private` Constants Across Module Boundaries

Constants prefixed with `_` are module-private by convention. When a constant is needed in another module (e.g., `crypto_reporting.py` needs `_DEFAULT_ZERO_BASIS_REVIEW_THRESHOLD` from `config.py`), rename it to a public name first. Importing private names across modules violates the API boundary and creates hidden coupling. Apply the same rule that lesson #5 states for tests.

## 29. AT Guidance May Cite Pre-Amendment Paragraph Numbers

See `docs/project-guidelines.md` #3 for the full rule.
Concrete instance: AT folheto 2026-01-12 (published after Lei n.º 31/2024) still cited CIRS art. 43 as "(n.º 6)(g)" and "(n.º 7)"; the old numbers before the June 2024 amendment renumbered them to n.8(g) and n.9 respectively. The stale numbers had silently propagated into `sources.md` and `platform-divergences.md`. The discrepancy was only caught by cross-checking the folheto against the consolidated CIRS PDF (which shows inline annotations like `(Anterior n.º 7 - Lei n.º 31/2024)`).

Prevention: whenever consulting AT guidance that cites a CIRS paragraph number, search for that legal text in the consolidated CIRS PDF and confirm the current paragraph number before recording citations.

---

## 33. Plan Edge Case Behavior Must Be Traced to Correctness Outcome

When writing a plan's Gist & Examples section, trace every described "edge case" or "behavior change" outcome to its user-facing result and verify it satisfies the project's correctness requirements, not just that it differs from the previous behavior.

A common failure mode: comparing the new behavior to the old one ("better than X") without verifying the new behavior is itself correct. Example from this project: "TH absent → `frozenset()` → contaminated Koinly CG passes through" was initially described as an improvement over "TH absent → CG silently dropped". Both behaviors produce wrong tax figures. The correct behavior is to raise `FileProcessingError` immediately; the improvement is the explicit failure, not acceptance of contaminated data.

**Test:** For every edge case in a plan, ask "what does the user see in the output?" and verify that output is either correct, or flagged as requiring review with a specific reason. Contaminated financial data presented without a flag is never acceptable.

**Cross-check:** Verify that described edge case behavior is consistent with existing `CLAUDE.md` constraints (e.g. "Optional crypto ingestion must be non-blocking" does not mean wrong data should silently substitute for missing correct data).

---

## 30. Verify Warning/Guard Path Reachability Before Writing Tests

Before writing a test for an existing warning, guard, or defensive code path, verify that the path can actually be triggered with current production code. Trace every condition that must be true simultaneously for the code to reach that branch.

If the path is unreachable via real data (e.g., a placeholder mechanism always fires before the guard condition can be met), the test must either: (a) use a mock/patch to inject the edge case directly, or (b) first amend the implementation to make the path reachable.

Claiming "implementation is already complete" for an untested path without first proving it is reachable leads to tests that can never go RED → the TDD cycle is broken and the coverage is false.

## 31. Read Full Dataclass Definition Before Describing Fields in a Plan

When a plan task describes the fields of a dataclass (e.g., listing fields to be moved or created), always read the actual class definition in source code to obtain the complete, current field list, including fields with default values that are easy to miss.

Omitting a field from a plan that is then used downstream (e.g., `partial_carryover_tx_keys` consumed by `resolve_cross_asset_exchanges`) silently changes behaviour and is not caught until runtime.

## 32. Distinguish Code Comments from Observed Data

When describing data behaviours (e.g., "this swap direction occurs"), explicitly distinguish between: (a) a behaviour observed in actual source data files, and (b) a behaviour described in a code comment or docstring.

Code comments reflect developer intent or known edge cases at the time of writing; they are not evidence that the behaviour has occurred in real data. For data-driven claims, check actual input files in `resources/source/` before asserting the behaviour is present.

## 34. Use `perl -i -pe` for Word-Boundary Replacements on macOS

macOS `sed` does not support `\b` word boundary anchors. Substitutions using `\b` appear to succeed (exit code 0) but make no substitutions, causing silent failures.

Use `perl -i -pe 's/\bold_name\b/new_name/g' file` for word-boundary renames on macOS. Verify with a grep after the substitution to confirm zero remaining occurrences.

## 36. Avoid `__getattr__` Delegation in Wrapper Dataclasses

See `~/Projects/.ai-playbook/python_guidelines.md` #3 for the canonical rule.
Repo context: `AcquisitionContext`/`ConsumptionContext` wrappers were introduced to attach `tx_key` and `source_row_index` to domain entities without modifying the domain layer. The `__getattr__` delegation made type checkers unable to verify delegated field access (`.date`, `.asset`, etc.), and the `with_acq()`/`with_con()` factory methods were called only twice combined. The correct fix is to add `tx_key` and `source_row_index` directly to `CryptoAcquisition` and `CryptoConsumption` in the domain layer.

## 37. Monkeypatch Module-Level Path Constants in Unit Tests

See `~/Projects/.ai-playbook/python_guidelines.md` #4 for the canonical rule.
Repo context: `_DECISION_POINTS_DIR = _REPO_ROOT / "docs/tax/decision_points"` in `config.py` is resolved at import time. Tests in `TestLoadTaxJurisdictionConfig` that called `_load_tax_jurisdiction_config()` without patching this constant silently read the real `2025.toml` from the working tree. They passed because the real file existed and had PT=True; any rename, move, or fiscal-year change would cause a cryptic `FileNotFoundError` rather than a meaningful test failure.
Fix: monkeypatch `_DECISION_POINTS_DIR` to a `tmp_path`-based directory with a minimal TOML fixture, identical to the pattern in `TestLoadDecisionPointsFlags`.

## 38. Decision Points TOML Missing Must Raise `ConfigurationError`, Not Bare `FileNotFoundError`

`_load_decision_points_flags()` must convert `FileNotFoundError` (missing TOML for the configured fiscal year) to `ConfigurationError` before it reaches `main.py`. The `main.py` exception handler has a separate `(FileNotFoundError, OSError)` branch for a missing `config.ini`, which logs "Config file not found; crypto pipeline will run without jurisdiction filters" and continues. If the TOML-not-found error reaches that branch, the pipeline silently proceeds with `exclude_loan_repayment_gains=False`; loan repayment disposals are incorrectly included in capital gains with no error raised.

Fix pattern in `_load_tax_jurisdiction_config`:
```python
try:
    flags = _load_decision_points_flags(country, fiscal_year, logger)
except FileNotFoundError as e:
    raise ConfigurationError(
        f"Decision points file missing for fiscal year {fiscal_year}; "
        f"create docs/tax/decision_points/{fiscal_year}.toml before running"
    ) from e
```

## 39. Resource-Release Flag Must Be Set After Successful Release Only

See `~/Projects/.ai-playbook/python_guidelines.md` #5 for the canonical rule.
Repo context: `workbook_builder.py` set `workbook_closed = True` unconditionally after a `try/except` that swallowed `workbook.close()` exceptions. The `finally` block then skipped the fallback `workbook.close()` call because the flag was already `True`, leaking the file handle whenever both the crypto sheet rendering and the subsequent close both raised.

## 40. Defensive Warnings Must Also Record Items in the Failure-Tracking Structure

When a defensive branch fires because a row cannot be fully processed (e.g. "both sides loan-affected"), always append the untracked item to `parse_failures_by_asset`; do not rely on a `logger.warning` alone. A logged warning is invisible to the workbook consumer; only items recorded in the failure-tracking structure surface as `review_required` flags in the output.

Example: in `_classify_th_row`, when both the sent and received currencies are loan-affected, the non-principal side was silently ignored. Fix: `parse_failures_by_asset.setdefault(untracked_currency, []).append(row_index)` in all four affected branches (sell, crypto_withdrawal, buy, crypto_deposit).

General principle: "Unmatched items must never be silently discarded" (see CLAUDE.md §1) applies to defensive-path items too; logging is necessary but insufficient when a failure-tracking collection exists.

## 41. Extracted Helpers Need Direct Unit Tests for Key Invariants

When refactoring extracts a private helper from a large orchestrator, add direct unit tests covering the key behavioral invariants (exact-match, partial consume, exhaustion, empty input, non-taxable path). Relying only on orchestrator-level coverage means a future regression in the helper requires tracing through the orchestrator before the failure is localized.

Example: extracting `_consume_against_pool_inplace` from the FIFO orchestrator prompted adding six focused tests in `TestConsumeAgainstPoolInplace`, reducing the blast-radius of future regressions to a single function.

## 42. Failing Tests: Distinguish Stale Expectation from Production Bug

When a test fails, first determine whether the test expectation became stale (design changed) or whether production code regressed. Changing production code to make a stale test pass is the wrong fix; it re-introduces the removed behavior.

Indicator: the test reads live state from the system under test (e.g. `review_required=bybit_origin.review_required`) instead of an explicit hardcoded fixture value. If the underlying mapping changed for valid reasons, the test silently tracks the wrong behavior.

Rule: tests that verify rendering or display behavior (e.g. "YES: ..." vs "NO" in an Excel cell) must use explicit hardcoded fixture values, not values delegated to `origin.some_field`. Hardcoding makes the test's intent clear and decouples it from unrelated mapping changes.

## 43. Two-Level Review Flags: Separate Platform-Level from Row-Level

When a dataclass field serves two semantically different purposes, introduce a second explicitly named field rather than overloading the first.

Example: `OperatorOrigin.review_required` was used for both (a) per-transaction issues (temporal validity failure, unknown platform) that should color transaction rows, and (b) platform-level concerns (e.g. account-region ambiguity) that should only appear on a summary tab. Adding `platform_review_required: bool = False` as a distinct field removed the conflation cleanly. See CRG-016.

## 44. Summary Sheets Should Be Complete Manifests, Not Filtered Lists

A summary/manifest sheet (e.g. Platform Assumptions) should list ALL items in the dataset with metadata columns, not only items that satisfy a filter condition. Filtering by flag omits clean items that a reviewer may still want to audit, and hides the total scope of the data.

Use flag columns (e.g. "Review Required = YES/NO", sort review-required first) to draw attention to items needing action, while preserving the complete manifest for auditability. Apply red row fill only to the flagged rows.

## 45. Deduplication Key Must Capture Minimum Sufficient Identity

When deduplicating domain events by a hash/key, verify that the chosen key uniquely
identifies each *distinct event*, not just each distinct source row. A single external row
can legitimately produce multiple events with the same primary key.

Example: a Koinly transfer row emits both a `fee_disposal` and a `transfer_out`
consumption; both share the same TxHash / `tx_key`. Deduplicating on `tx_key` alone drops
one of them. Correct granularity: `(tx_key, event_type)` for consumptions,
`(tx_key, source_type)` for acquisitions.

Test approach: write a fixture with a single transfer-with-fee row and assert that two
distinct consumption events are produced before assuming single-field dedup is safe.

## 46. Fiscal Year Filter in FIFO Pipeline Must Apply to Disposals Only, Post-FIFO

When filtering FIFO pipeline output to the reporting fiscal year, filter *only disposal /
realization records*, never the acquisition records. Prior-year acquisitions must remain
in the FIFO pool so cost-basis carry-over is correct; filtering them by year would produce
incorrect zero-cost gains for multi-year holds.

Correct position: filter `AssetFifoResult.realizations` after the FIFO engine produces
them, before converting to `CryptoCapitalGainEntry`. Do not pre-filter `acquisitions` or
`consumptions` inputs to the FIFO engine.

## 35. CSV Test Fixture Column Alignment Must Be Verified

When writing CSV test fixture rows for multi-column formats (e.g. Koinly TH rows), verify each value is at the correct column index by counting quoted fields as single units (quoted content containing commas counts as one field).

A misaligned column can make a test pass even with the bug it is designed to detect. Example: a test asserting `cost_basis_eur == 0` when `Sent Cost Basis` is empty will still pass if `Net Value (EUR)` is also empty, because an FMV-fallback bug would also produce 0. Place a non-zero value in `Net Value (EUR)` (col 14) to make the bug detectable.

Use `csv.DictReader([TH_HEADER, row])` or the test helper `_parse_row()` to verify field-to-column mapping before relying on a fixture row as a correctness check.

---

2. `uv run ruff check . --fix`: auto-fix linting
3. `uv run basedpyright src/ tests/`: type checking
4. `uv run ruff check . --select=E501`: line length
5. Confirm all imports have matching dependencies
6. `grep -r "Path(__file__)" tests/`: no fragile test paths
7. Review new parameters: are any always constant? (remove them)
8. Do tests verify actual functionality or just return values?
9. Remove temporary files or scripts
10. Update relevant docs if API changed
11. If tests were added or removed, update test counts in CLAUDE.md and AGENTS.md (`uv run pytest --collect-only -q | tail -3`)

## 47. Background Agent Timing: Never Run Tests While Agent Is Writing to Shared Modules

When a background agent is actively writing to source modules, running tests against those modules produces transient failures from broken partial state (half-written files, incomplete imports). Always wait for the background agent to complete before running tests on the modified files.

## 48. Inlining Helpers That Use `defaultdict`: Update Tests That Pass Plain Dicts

When inlining a helper that switches internal state from `{}` to `defaultdict(list)`, any test that directly calls the helper with a plain dict `{}` will silently get a `KeyError` on first missing key. Update such tests to pass `defaultdict(list)` directly, or update the inlined code to use `.setdefault(key, [])` instead of relying on defaultdict auto-init so plain-dict callers still work.

## 49. `TaxJurisdictionConfig` Lives in `domain/jurisdiction.py`

`TaxJurisdictionConfig` was moved from `infrastructure/config.py` to `domain/jurisdiction.py`. `config.py` re-exports it for backward compat. All new code should import from `domain.jurisdiction` directly; infrastructure imports are for backward compat only.

## 50. Run-Determining Parameters Belong in the Output Artifact, Not in Logs

When a pipeline run produces different results depending on dynamically-discovered inputs (e.g. which assets are loan-affected, which platforms are active, which years are in scope), expose those inputs in the output report itself, as a dedicated worksheet section, a named range, or a metadata tab, rather than relegating them to log lines or ephemeral sidecar files.

Logs are consumed during a run and discarded; a sibling file adds surface area and may not be opened. The workbook is the primary artifact reviewed by the user. Embedding the run scope there lets the reviewer verify assumptions without cross-referencing external files, and makes the report self-documenting for future audits.

Example: `CryptoTaxReport.fifo_rebuild_assets` (which assets were rebuilt from Transaction History) is surfaced in the "FIFO Rebuild Scope" section of the Loan Activity tab, not just logged at INFO.

## 51. All-or-Nothing File Set Validation for External Exports

When a subsystem requires a complete set of N files from an external tool export (e.g. Koinly's capital gains, income, and transaction history), validate with all-or-nothing semantics:

- **None present** → skip gracefully (no-op mode; the external data source is simply not configured for this run).
- **Partial set present (1 of N or 2 of N)** → raise `FileProcessingError` with an explicit list of missing files and export instructions. Partial presence is worse than none: it silently produces an incomplete report that looks valid (e.g. rewards disappear but no error is raised).
- **All N present** → proceed normally.

The silent-data-loss case that triggered this lesson: `income_file = None` was handled as `reward_entries = []` with no warning or error, so Wirex EUR lending interest vanished from the Crypto Rewards tab without any indication. The user attributed the disappearance to a code change, but the actual cause was a missing export file. Fail-fast on partial sets eliminates this class of confusion.

## 52. Suspicious Asset Detection via Non-Latin Script Characters

Asset tickers that use non-Latin script characters (Cyrillic, Greek, etc.) are strong indicators of homoglyph scam tokens. Example: **UЅDT** (Latin USDT with Cyrillic Ѕ instead of S) or **WBТC** (Latin WBTC with Cyrillic Т instead of T).

**Detection rule**: Use Unicode codepoint ranges to identify non-Latin characters. Allow:
- Basic Latin (ASCII): U+0000–U+007F
- Latin-1 Supplement: U+0080–U+00FF (accented Latin like é, ñ, ö)
- Latin Extended-A/B: U+0100–U+024F

**Action**: Flag assets with characters outside these ranges as suspicious:
- In reward/gains parsing: set `review_required=True` with reason "Asset ticker '{asset}' contains non-Latin characters - potential homoglyph scam token"
- In skipped assets tracking: mark `suspicious=True` to highlight in reconciliation report
- Do NOT normalize these to Latin (preserving the scam characters makes them visible for investigation)

**Implementation**: `src/tax_reporting/infrastructure/koinly_parser.py:contains_non_latin_characters()`

## 53. Zero-Value Flagging vs Skipping

**Rewards**: Skip zero-value rows by default, but flag known/popular tokens for review instead of skipping.

**Capital gains**: Flag zero-cost or zero-proceeds entries with specific review reasons:
- Zero cost: "Zero acquisition cost - verify basis (airdrop, data error, or misclassification)"
- Zero proceeds: "Zero disposal proceeds - verify sale data (transfer error, data quality issue)"

**Known assets**: Use both:
- Hardcoded popular tokens list (`_POPULAR_CRYPTO_TOKENS` with ~100 tokens: BTC, ETH, SOL, USDT, etc.)
- Dynamic discovery: scan files first for assets with non-zero values, use that as `known_assets` set
- Substring matching: catch Koinly variants like TSTON (contains "TON"), TSUSDE (contains "USDE")

**Reporting**: Flagged entries appear with red fill and "YES: <reason>" in the Review column.

## 54. Substring Matching for Token Variants

Koinly uses prefixes/suffixes for tracked or staked tokens (e.g., **TSTON**, **TSUSDE**); these don't match exact popular token names but contain the base token as a substring.

**Implementation**: `_contains_popular_token()` checks if any popular token exists as a substring (case-insensitive) within the asset ticker.

**Use**: Zero-value flagging uses this to catch variants like:
- TSTON → contains "TON" → flagged
- TSUSDE → contains "USDE" → flagged
- USDT itself → exact match → flagged

## 55. Verify Staged Diff Matches Implementation Before Finalizing

When finalizing work for code review or commit, the staged diff (`git diff master...HEAD`) must match the actual implementation in the working directory. Untracked files that are part of the implementation create a discrepancy; reviewers evaluate stale code while the working directory has different logic.

**Check before finalizing**: Run `git status` and verify no files that are part of the implementation appear as untracked (`??`). If a new source file or test exists in the working directory but is not staged, add it with `git add <file>` before considering the work ready for review.

**Why**: Code reviews evaluate staged changes. If staged code differs from working directory, review findings may be obsolete or the review may miss issues that exist only in untracked files.

## 56. Try/Finally Resource-Cleanup Scope Must Cover All Raising Operations

When using try/finally for resource cleanup (e.g., `workbook.close()`, `file.close()`), ensure all operations that can raise exceptions before the finally block are covered by the same try block. If an operation outside the try/finally raises, the cleanup never runs.

**Fix by**: Either (1) start the try block early enough to cover all operations that can raise, or (2) wrap early operations in their own try/except with explicit cleanup before re-raising.

**Example**: In workbook_builder.py, `aggregate_taxable_rewards()` was called before the try/finally that closes the workbook. If aggregation raised, the workbook was never closed. Fixed by moving aggregation inside the try block so any exception triggers workbook cleanup.

## 57. When Removing Functions, Remove Their Tests

When removing or deleting a function from a module, check for and remove any tests that import or test that function. Leaving tests that import deleted functions causes `ImportError` during test collection.

**Check**: Use `grep -rn "<function_name>" tests/` to find test references before removing the function.

## 58. Update Documentation When Code Structure Changes

When restructuring code (changing sheet layouts, renaming components, merging or splitting modules), update all documentation that describes the structure in the same session. README files, walkthough documents, and project overviews that describe the old structure become misleading and cause confusion.

**Scope**: Check README.md, any walkthrough or presentation docs, and any architectural decision documents that mention the changed components.

## 59. Hardcoded Set Maintenance: Check Across All Sections for Duplicates

When maintaining multi-section hardcoded collections (like `_POPULAR_CRYPTO_TOKENS`, `_INCOME_CODE_DESCRIPTIONS`), items can legitimately belong to multiple categories. Before adding an item to one section, grep across all sections to verify it doesn't already exist elsewhere in the same collection.

**Problem**: Frozensets and dicts silently deduplicate, so duplicate entries don't cause runtime errors but create confusion for maintenance and can mislead readers about category boundaries.

**Check pattern**: `grep -n '"ITEM_NAME"' src/tax_reporting/application/crypto_reporting.py` before adding a new token.

**Example**: "ARB", "OP", "MATIC" appeared in both "Layer 1 / Major chains" and "Layer 2 / Scaling" sections; keep each token in its most appropriate category only.

## 60. Document Tradeoffs for Fuzzy Matching in Docstrings

When implementing fuzzy matching (substring matching, regex patterns, glob patterns, etc.) that could produce false positives, document the tradeoff explicitly in the docstring so future maintainers understand the design decision and don't "fix" what isn't broken.

**What to document**:
- What the fuzzy matching catches (intended targets)
- What false positives it may produce (collateral matches)
- Why the approach is acceptable despite its imperfections
- The consequence of a false positive (usually just flagging for review rather than skipping important data)

**Example** (from `_contains_popular_token`): "Tradeoff: Substring matching may cause false positives for tickers that coincidentally contain popular token names as substrings (e.g., 'MATICAL' matches 'MATIC'). This is acceptable because the consequence is merely flagging for review rather than incorrectly skipping a legitimate zero-value reward."

## 61. Add Logging to Silent Exception Handlers

When using `except Exception: continue` or similar graceful degradation patterns, add warning-level logging before continuing. Silent failures hide real issues (file corruption, permission problems, malformed data) and make debugging impossible.

**What to log**: At minimum, log the file path, exception type, and message so the degradation is observable in logs.

**Pattern**:
```python
# ❌ WRONG: silent failure hides the problem
try:
    rows = read_koinly_rows(file_path)
    # ... process rows ...
except Exception:
    continue  # No visibility into what failed

# ✅ CORRECT: observable degradation
try:
    rows = read_koinly_rows(file_path)
    # ... process rows ...
except Exception as e:
    logger.warning("Failed to scan %s: %s. Continuing with empty set.", file_path, e)
    continue
```

**Why**: When the function fails silently, you can't tell whether the empty result is correct (no data) or caused by a bug (file couldn't be read). Logging makes the difference visible.

## 62. Review Documents Are Temporary Artifacts

Code review documents in `docs/reviews/` are temporary staging artifacts for the review workflow, not permanent documentation. They serve as:
- Approval artifacts before posting review comments to a PR
- Persistent record of what was reviewed and what changed

**Lifecycle**:
1. Created during code review with findings marked as `pending`
2. Updated to `fixed` / `drop` / `post` as findings are addressed
3. After all findings are addressed: either delete the file or move to `docs/tmp/` if it has reference value

**Do not**: Accumulate stale review documents in `docs/reviews/`. After the branch is merged, these documents have no further purpose.

## 63. Fail Fast for Data-Completeness Operations

For scan/aggregation functions that populate lookup sets used for validation or classification, fail fast when ALL inputs fail rather than returning empty results that cause incorrect downstream behavior. Partial success with warning is acceptable; total failure should raise an error.

**Pattern**:
```python
# ❌ WRONG - Silent degradation causes incorrect behavior
def _collect_known_assets(files):
    known = set()
    for f in files:
        try:
            known.update(parse(f))
        except Exception:
            pass  # Silently return empty set if all files fail
    return frozenset(known)

# ✅ CORRECT - Fail fast when all inputs fail
def _collect_known_assets(files):
    known = set()
    failures = []
    for f in files:
        try:
            known.update(parse(f))
        except Exception as e:
            failures.append((f, e))

    if files and len(failures) == len(files):
        raise FileProcessingError(f"All files failed: {failures}")
    return frozenset(known)
```

**Why**: When the function returns empty due to total failure, downstream code incorrectly treats valid known assets as unknown, causing data loss. Raising an error surfaces the root cause (file format/parse errors) prominently.

## 64. Context Managers for Resource Cleanup

For resource cleanup with multiple exit paths (success, multiple failure types, nested try-except), use context managers for clarity and guaranteed cleanup.

**Pattern**:
```python
# ❌ WRONG - Complex nested structure, cleanup duplicated in except and finally
def process():
    resource = acquire()
    closed = False
    try:
        do_work(resource)
    except Exception:
        resource.close()
        closed = True
        raise
    finally:
        if not closed:
            resource.close()

# ✅ CORRECT - Context manager encapsulates lifecycle
@contextmanager
def _resource_lifecycle():
    resource = acquire()
    try:
        yield resource
    finally:
        resource.close()

def process():
    with _resource_lifecycle() as resource:
        do_work(resource)
```

**Why**: Context managers make the success path clearer (no flag tracking) and guarantee cleanup even for unexpected exceptions. The cleanup logic is defined once and reused.

## 65. Parameter Objects for Complex Signatures

When a function signature grows beyond ~5 parameters, especially when they represent shared parsing/accumulation state rather than primary inputs, group related parameters into a context/Parameter Object.

**Pattern**:
```python
# ❌ WRONG - Hard to track which parameters belong together
def _parse_file(path, skipped, resolver, reviews, known, assets, flags):
    pass

# ✅ CORRECT - Group related state into a context object
@dataclass(frozen=True)
class ParsingContext:
    skipped_assets: Counter
    origin_resolver: Resolver
    review_entries: list[Review]
    known_assets: frozenset[str]
    loan_affected_assets: frozenset[str]

def _parse_file(path, context: ParsingContext):
    pass
```

**When to use Parameter Objects**:
- Parameters are passed together to multiple functions
- Parameters represent shared state across a processing pipeline
- The set of parameters is growing over time
- Improves readability and testability

## 66. Externalize Frequently-Changing Lists

Hardcoded lists that change frequently (popular tokens, supported exchanges, asset tickers) should be externalized to data files, not embedded in source code. Use cached loading for performance.

**Pattern**:
```python
# ❌ WRONG - Requires code change for every new token
_POPULAR_TOKENS = frozenset(("BTC", "ETH", "SOL", ...))  # 70+ items

# ✅ CORRECT - External data file, cached in memory
@lru_cache(maxsize=1)
def _load_popular_tokens() -> frozenset[str]:
    with open("docs/tax/popular_crypto_tokens.json") as f:
        return frozenset(json.load(f)["tokens"])
```

**Why**: Lists representing external reality (crypto market, exchange support, regulatory lists) change independently of code. Externalizing allows updates without code changes and separates configuration from logic.

## 67. Futures/Derivatives Liquidation Mechanics

A leveraged futures position (e.g., SOL/USDT with USDT as collateral) creates a counterintuitive tax reporting outcome: even when the position is liquidated at a loss, the system reports a **disposal** of the collateral asset. This is correct behavior under Portuguese tax law, not an error.

**Why this happens:**
- A leveraged futures position has the collateral (e.g., USDT) as the underlying asset
- Liquidation is a forced closure where the exchange disposes of the collateral to cover the loss
- For tax purposes, this is an **alienação onerosa** (onerous disposal) under CIRS art. 10(1)(e): "instrumentos financeiros derivados"
- The disposal amount (e.g., "<COLLATERAL_USDT> USDT disposed") reflects the collateral being removed from the position
- The **negative capital gain** (the loss) appears in the gain/loss column and is deductible per PT-C-016 (5-year carry-forward for short-term)

**Key distinction:** A futures liquidation is NOT a withdrawal. A withdrawal (to your own wallet) is not a taxable event for the asset itself. A liquidation is a forced disposal by the exchange and IS taxable; the loss can offset future gains.

**Concrete example:** ByBit SOL/USDT position `<POSITION_ID>` liquidated on 19 Jan 2025, 11:28:53 PM. Koinly reported <-USD_LOSS> USD loss at 11:29:46 PM. The system correctly assessed disposal of <COLLATERAL_USDT> USDT (<COLLATERAL_EUR> EUR) as the collateral disposition, with the loss appearing as negative gain/loss.

**See also:** DP-010 in `docs/tax/decision_points/2025.md`, PT-C-031 and PT-C-032 in `docs/domain/crypto_rules.md`, lesson #73 (Cross-Report Validation), lesson #75 (OGR override timing)

## 68. Decision Point Flags Require TaxJurisdictionConfig Field

When adding a new boolean decision point flag to `docs/tax/decision_points/<year>.toml`,
you must also add the corresponding field to `TaxJurisdictionConfig` in `src/tax_reporting/domain/jurisdiction.py`.

**Why this is required:** The config validation system auto-discovers known decision point flags
via `_KNOWN_DECISION_FLAGS` in `config.py` (lines 44-51), which is derived from all bool fields
in `TaxJurisdictionConfig`. If a flag exists in TOML but has no corresponding field in the dataclass,
validation fails with "Unknown decision points flag" error and all config-dependent tests break.

**Pattern:**
1. Add bool field to `TaxJurisdictionConfig` (e.g., `futures_derivatives_taxable: bool = False`)
2. Add flag to `docs/tax/decision_points/<year>.toml` under `[countries.<CC>]` section
3. Run tests; config validation now recognizes the flag

**Example:** The `futures_derivatives_taxable` flag was added to `2025.toml` but the field was
missing from `TaxJurisdictionConfig`. This caused all integration tests to fail with config
validation error until the field was added to the domain model.

**See also:** `config.py` lines 44-51 (`_KNOWN_DECISION_FLAGS` derivation), `jurisdiction.py`

---

## 69. Excel Output Visual Structure Tests

When adding or modifying Excel report layouts, add visual structure tests to verify row placement, cell merging, blank rows, and header structure, not just data values. This prevents regressions where structural changes accidentally modify layout.

**What to test:**
- **Row placement**: Section title row, blank row count (exactly one vs double), header row positions, data start row
- **Cell coordinates**: Verify specific values at expected positions (e.g., "CAPITAL GAINS" at A1, "Day" at B4)
- **Cell merging**: Verify merged cell ranges using `sheet.merged_cells.ranges` (e.g., SALE header spans B3:E3)
- **Cell formatting**: Verify bold fonts, red fills, and other visual indicators
- **Column positions**: Regression guard against column index changes (e.g., Country of Source at col 1, sell_day at col 2)

**Pattern:**
```python
# Test section title placement and formatting
def test_section_title_at_row_1(self, sheet):
    assert sheet["A1"].value == "CAPITAL GAINS"
    assert sheet["A1"].font.bold

# Test blank row count (not double-spaced)
def test_single_blank_row_after_title(self, sheet):
    assert sheet["A2"].value is None  # Row 2 is blank
    assert sheet["A3"].value is not None  # Row 3 has header

# Test cell merging
def test_sale_header_merged_across_4_columns(self, sheet):
    assert "B3:E3" in {r.coord for r in sheet.merged_cells.ranges}
```

**Why**: Data-value tests alone cannot detect layout regressions. A structural change like modifying `start_column` from 2 to 1 would misalign data columns without breaking data-value assertions. Visual structure tests catch these regressions by explicitly verifying the expected layout geometry.

**See also**: `tests/unit/application/persisting/test_ib_sheet.py::TestWriteIbReportingSheetCapitalGains` for example visual structure tests

## 70. Structural Change Verification for Absolute-Position Code

When modifying table structures (adding/removing columns), verify that all downstream code using those positions is correct. Distinguish between:

- **Absolute-position code** (writes to specific column numbers): needs manual verification after structural changes
- **Offset-based code** (uses `start_column + N`): may auto-adjust but still needs verification

**Pattern:** After removing/adding columns, grep for all code that writes to specific column indices and verify correctness. For the IB sheet, the country pass writes to absolute positions (col 1 and col 10) and was unaffected by Beneficiary removal because it uses direct column indices rather than offsets from `start_column`.

**Verification step:** Add a verification task to the plan when structural changes affect column positions. Run the relevant tests to confirm no regression.

**Example:** After removing the Beneficiary column from the CAPITAL GAINS table, verify that the country pass (lines 196-197 of `ib_sheet.py`) still writes to the correct columns: column 1 (Country of Source) and column 10 (WITHOLDING TAX/Country).

## Quality Assurance Commands

```bash
uv run ruff check . --select=E501     # Line length
uv run ruff check . --select=F401     # Unused imports
uv run ruff check . --select=PL       # Pylint rules

grep -r "Path(__file__)" tests/ || echo "No fragile test paths"
grep -r "= True" src/ --include="*.py" | grep -v "def " | head -10

uv run pytest -m unit          # Fast feedback during development
uv run pytest -m integration   # Before committing

## 71. Validation-First Investigation Pattern

When a plan investigates "is X handled correctly?" or "does the system correctly handle Y?", structure the plan with verification tasks before implementation tasks:

1. **Start with verification:** Code inspection, test execution, and documentation review
2. **Then decide on implementation:** Skip implementation tasks if verification shows correctness
3. **Document findings:** Create investigation artifacts under `docs/tmp/` (or promote to canonical docs if reusable)

This pattern prevents unnecessary work when the current implementation is already correct. It applies to any "is this handled correctly?" question, regardless of domain.

**Example:** The 2026-06-07 futures/derivatives loss treatment plan used Tasks 1, 3, 5, 7, 8 for verification (code inspection, source archiving, docs review, Koinly investigation, test execution) and skipped Tasks 2, 4, 6 (country-specific config, tests, guidance) because verification confirmed the existing implementation was correct. See the futures-loss investigation record (local) for the investigation record and `docs/plans/2026-06-07-futures-derivatives-loss-treatment.md` for the full plan.

**See also:** plan_quality_guidelines.md for plan structure guidance on verification-before-implementation task ordering.

## 72. Data Trace Verification Requirement

When a plan investigates "is X handled correctly?" or "does the system correctly handle Y?", code inspection alone is INSUFFICIENT. The investigation must include ACTUAL data trace verification:

1. **Trace the user's specific case:** For the exact reported scenario, verify data flows from source CSV through to final output. Do not rely on code inspection alone.
2. **Verify output matches source classification:** If the source report shows "Loss" and the output shows "Gain", the investigation is incomplete regardless of whether code CAN handle negatives.
3. **Command pattern:** `grep "specific_value" source.csv` → compare with actual Excel output cell value
4. **Failure consequence:** An investigation that concludes "no code changes needed" without performing data trace verification is INCOMPLETE and must be redone.

**Example:** The 2026-06-07 futures/derivatives loss treatment investigation concluded "no code changes needed" based on code inspection alone. However, data trace verification revealed that Koinly's Other Gains Report classified entries as "Loss" while the Excel output showed them as "Gain", a clear discrepancy that code inspection missed.

## 73. Cross-Report Validation for Multi-Report Systems

When investigating systems that process data from multiple source reports (e.g., Koinly Transaction History, Capital Gains Report, Other Gains Report), verify classifications match across ALL reports before concluding correctness:

1. **Identify all source reports:** List every CSV/report the system processes
2. **Cross-reference classifications:** If one report shows Type="Loss" and another shows Gain/Loss=positive, investigate which report drives the final output
3. **Verify final output reflects the correct classification:** The Excel/final output must match the economically correct classification, not just the mechanically calculated one
4. **Document which report is authoritative:** When source reports disagree, state which report's classification is correct and why

**Example:** Koinly's Other Gains Report correctly classified futures liquidations as "Loss" with negative amounts, while the Capital Gains Report calculated positive gains based on collateral proceeds. The system only processes Capital Gains Report, so losses appeared as gains in the final output. Cross-report validation would have caught this discrepancy.

**See also:** Lesson #75 (Authoritative Source Overrides Must Precede Aggregation)

## 74. Cross-Module Function Dependencies Require Complete Imports

When adding a function in one module that calls a function from another module, verify the import is complete. Unit tests that don't exercise the full code path (e.g., only test helper functions but not the file-discovery wrapper) can miss import errors that would cause runtime `NameError`.

**Verification:** After adding cross-module function calls, run `uv run python -c "from module import function"` to verify imports resolve at import time, not just at call time.

**Example:** `_find_and_parse_other_gains_file()` in `koinly_parser.py` called `_find_report_path()` from `crypto_reporting.py` without importing it. Unit tests for the helper functions (`_extract_ogr_gain_loss`, `_parse_other_gains_row`) passed because they didn't call the file-discovery function. A full import check would have revealed the missing dependency before runtime.

## 75. Authoritative Source Overrides Must Precede Aggregation

When applying overrides from an authoritative source (e.g., OGR) to calculated data (e.g., CG), the override must happen BEFORE aggregation when working with lot-level entries.

**Why this matters:** CG rows are individual FIFO lots that get summed in aggregation. The authoritative source (OGR) contains the correct total gain/loss for the disposal event. Overriding after aggregation would lose the lot-level trail and make reconciliation impossible.

**Pattern:**
1. Parse calculated source (CG): produces individual lot entries
2. Parse authoritative source (OGR): produces event-level totals
3. Match and override lot entries with authoritative values
4. Aggregate overridden lots: preserves lot-level trail in output

**Example:** In `crypto_reporting.py`, `_apply_ogr_overrides()` is called after `_parse_capital_gains_file` but BEFORE `_aggregate_capital_entries()`. This ensures that when OGR reports an authoritative per-disposal loss, each individual FIFO lot for that disposal is overridden with that authoritative value before being summed. If aggregation happened first, the lot-level detail would be lost and the override could not be traced back to specific lots.

**See also:** Lesson #73 (Cross-Report Validation), AGENTS.md constraint on OGR override timing

## 76. TDD for Bug Fixes

When investigating and fixing bugs, follow the TDD approach: create a failing test first (RED stage), then implement the fix (GREEN stage). Do not skip the test creation step even if the fix seems obvious.

**Why this matters:** Creating a failing test first:
- Documents the bug with a concrete example
- Prevents regression
- Forces understanding of the issue before implementing
- Makes the fix verifiable

**Pattern:**
1. Write test that reproduces the bug (RED)
2. Run test to confirm it fails
3. Implement minimal fix (GREEN)
4. Run test to confirm it passes
5. Run full test suite to ensure no regressions

**Example:** For the OGR duplicate-key bug, `test_ogr_index_sums_duplicate_keys` was created first to demonstrate that entries with the same key were being overwritten instead of summed. Only after the test failed (showing only the last per-row value instead of the summed aggregate across all rows for the key) was the fix implemented.

**See also:** Lesson #77 (Duplicate Key Handling in Index Building)

## 77. Duplicate Key Handling in Index Building

When building an index from source data where multiple entries may share the same key, handle duplicate keys explicitly by summing (or another appropriate aggregation). Never silently overwrite previous entries with new ones.

**Why this matters:** Silent data loss occurs when duplicate keys overwrite previous values. This is especially dangerous when the index is used for authoritative values in calculations.

**Verification:** After building an index, if the sum of all indexed values should equal a known total, verify this invariant holds.

**Pattern:**
```python
# Wrong: silent overwrite
result[key] = value  # Last value wins, previous values lost

# Correct: explicit summation
result[key] = result.get(key, ZERO) + value  # All values summed
```

**Example:** In `_find_and_parse_other_gains_file()`, the OGR file contained three entries for the same platform+asset+date key (a funding fee, a futures fee, and a realized P&L). The buggy code `result[key] = gain_loss` stored only the last value. The fix `result[key] = result.get(key, ZERO) + gain_loss` correctly sums all values for the key.

**See also:** Lesson #76 (TDD for Bug Fixes), Lesson #78 (OGR Validation vs Replacement Design)

## 78. OGR Directional Authority vs Wholesale Replacement (Completed)

**Status:** Completed; see `docs/plans/2026-06-10-ogr-validation-design.md`

The OGR (Other Gains Report) feature uses **directional authority semantics**, not wholesale replacement. OGR provides authoritative DIRECTION (gain vs loss) while CG (Capital Gains) provides MAGNITUDE via standard FIFO calculation.

**Directional authority logic:**
- **Direction conflict (OGR sign != CG sign):** Use OGR direction with CG magnitude
  - Example: CG=+100 (gain), OGR=-147 (loss) → final = -100 (loss with CG magnitude)
  - Flag with review_required=True, reason="OGR direction override"
- **Directions agree (same sign):** Use OGR magnitude (more accurate for derivatives)
  - Example: CG=-100, OGR=-105 → final = -105 (use OGR magnitude)
  - Flag with review_required=True only if magnitude diff > 5% AND absolute diff > 1 EUR

**Implementation details:**
- Applied per-lot before aggregation via `_apply_ogr_direction_override()`
- Creates `OgrValidationResult` attached to each entry with comparison metadata
- Absolute threshold (1 EUR) prevents noise on near-zero values for both direction conflicts and magnitude diffs
- Multiple lots for same disposal each get ogr_validation attached; aggregation combines them

**See also:** Lesson #75 (Authoritative Source Overrides Timing), Lesson #79 (Independent Validation Fields), CRG-017 in crypto_reporting_guidelines.md

## 79. Independent Validation Fields vs Entry-Level Review Flags

When adding validation-related fields to a dataclass that already has `review_required`/`review_reason` fields, distinguish between:
- **Entry-level review flags**: domain-specific validations that apply to the entry itself
- **Independent validation results**: cross-report or cross-system validations that have their own review criteria

**Pattern:**
- Add validation results as optional nested dataclass fields (e.g., `ogr_validation: OgrValidationResult | None = None`)
- Do NOT integrate validation-result `review_required` into entry-level `__post_init__` validation
- Keep the two review mechanisms independent; validation result carries its own `review_required`/`review_reason`
- Tests that verify "YES:"/"NO" rendering must set the nested field explicitly, not delegate to origin fields

**Why:** Entry-level validation enforces that `review_reason` is set when `review_required=True`. Independent validations have their own lifecycle and should not trigger entry-level validation. Tests must verify independence explicitly.

**Example:** In Task 1 of the OGR validation design, `ogr_validation` was added to `CryptoCapitalGainEntry` as an optional field. The `__post_init__` validation only checks entry-level `review_reason`, not `ogr_validation.review_reason`. The test `test_ogr_validation_attached_to_entry` verifies this independence.

**See also:** Lesson #43 (Two-Level Review Flags), CRG-016 in crypto_rules.md

## 80. Field Aggregation Strategy Depends on Semantics

When aggregating grouped entries (e.g., FIFO lots into sale events), field aggregation strategy depends on field semantics, not all fields should be summed.

**Pattern:** For each field in the aggregated result, choose the strategy based on what the field represents:
- **Lookup value fields**: Take from first entry (all entries in group share the same lookup key, so the value is identical across entries). Example: `ogr_gain_loss` from OGR lookup by (date, asset, wallet)
- **Per-lot contribution fields**: Sum across all entries. Example: `calculated_gain_loss` where each lot contributes to the total
- **Boolean flags**: Use OR logic (True if ANY entry has True). Example: `direction_conflict`, `review_required`
- **Severity indicator fields**: Use maximum value. Example: `magnitude_diff_percent` to show worst deviation
- **Narrative text fields**: Join unique values with delimiter and deduplicate. Example: `review_reason` joined with "; "

**Implementation:** `_aggregate_ogr_validation()` in Task 3 of OGR validation design demonstrates all five patterns.

**Why:** Assuming "sum" for all numeric fields is incorrect; some numeric fields represent a shared lookup value that must NOT be summed, while others represent independent contributions that must be summed. Mixing these semantics produces incorrect results (e.g., summing `ogr_gain_loss` would multiply the OGR value by the number of lots, which is wrong).

**Example:** In crypto capital gains aggregation, `ogr_gain_loss` comes from the first entry because all FIFO lots for the same disposal share the same OGR lookup value. But `calculated_gain_loss` is summed because each lot contributes its own gain/loss to the total.

**See also:** Lesson #75 (Authoritative Source Overrides Timing)

## 81. Excel Conditional Formatting Priority Matters

When applying multiple conditional fill conditions to Excel rows, implement explicit priority ordering. Highest-priority conditions should be checked first and return early, preventing lower-priority conditions from masking important issues.

**Pattern:**
1. Create a dedicated conditional formatting function (e.g., `_apply_conditional_formatting`) that documents the priority order in its docstring
2. Check conditions in priority order and return early after applying the highest-priority fill
3. Use early returns to prevent fallthrough to lower-priority conditions

**Priority example (highest to lowest):**
1. RED fill for critical issues (e.g., OGR direction conflict indicating sign disagreement between authoritative source and calculation)
2. YELLOW fill for warnings (e.g., magnitude differences exceeding threshold)
3. RED fill for entry-level review requirements (e.g., zero-cost gains above threshold)
4. BLUE fill for informational highlights (e.g., multi-acquisition dates)
5. No fill (default)

**Why:** Without explicit priority, the last condition checked wins regardless of severity. A critical issue could be masked by a less severe condition that happens to apply first.

**Example:** In Task 4 of the OGR validation design, `_apply_conditional_formatting()` checks OGR conditions before entry-level review conditions. An OGR direction override (critical) gets RED fill even if the entry also has `review_required=True` (less severe). If the order were reversed, the entry-level RED fill would be applied first and the critical direction conflict would be masked.

**Implementation notes:**
- Fill colors should be defined as module-level constants for consistency and to avoid repeating color codes
- When adding columns, update the column count constant AND the conditional formatting loop range
- Add helper functions for fill assertions (e.g., `_is_yellow_fill()`) to keep tests consistent

**See also:** Lesson #7 (Excel Output Security), Lesson #15 (Excel Column Width), Lesson #69 (Excel Output Visual Structure Tests)

## 82. Adding Excel Columns Requires Constant Updates

When adding new columns to an Excel sheet output, update all related constants and ranges in the same commit. A single new column typically requires updates in multiple places.

**Required updates when adding columns:**
1. Column count constant (e.g., `_CAPITAL_GAINS_NUM_COLS`)
2. Headers list (add new header string)
3. Data row rendering (write new cell value or blank/None)
4. Conditional formatting range (loop bound must match new column count)
5. Test constants (e.g., `_NUM_CAPITAL_COLUMNS`)
6. Auto-width tests (loop bound for column iteration)

**Verification:** Run tests after adding columns. Common failures:
- `IndexError` from loops using old column count
- Misaligned headers vs data columns
- Conditional formatting not covering new columns

**Why:** These constants are coupled; they all represent "how many columns exist." Missing one causes bugs that only appear at runtime or in specific test scenarios.

**Example:** In Task 4 of the OGR validation design, three new OGR validation columns were added (18, 19, 20). The implementation updated:
- `_CAPITAL_GAINS_NUM_COLS` from 17 to 20
- `capital_headers` list with three new header strings
- `_render_capital_gain_row()` to write OGR values (or None when absent)
- `_apply_conditional_formatting()` to loop through all 20 columns
- Test `_NUM_CAPITAL_COLUMNS` from 17 to 20
- Auto-width test to check 21 columns (headers + 1 blank)

**Pattern:** When adding multiple columns at once, consider using a local constant or calculated offset to avoid off-by-one errors. For example, `FIRST_OGR_COL = 18` and `NUM_OGR_COLS = 3` makes the range explicit.

**See also:** Lesson #81 (Excel Conditional Formatting Priority)

## 83. Test Blank/Null Handling Explicitly for New Optional Columns

When adding columns that can be blank/None (e.g., when validation data is absent), add dedicated tests for that state. Do not assume "no data" works correctly based on "with data" tests.

**Pattern:**
1. Add a test specifically for the blank/None state (e.g., `test_ogr_validation_columns_blank_when_ogr_validation_none`)
2. Verify the column cells are `None` (not empty string, not zero, not default value)
3. Verify conditional formatting does NOT apply for blank state (no fill when no data)

**Why:** "With data" tests only exercise the populated path. The blank/None path has different code branches (skipped assignments, no formatting applied) and is a common source of bugs.

**Example:** In Task 4 of the OGR validation design, the test `test_ogr_validation_columns_blank_when_ogr_validation_none` verifies that when `entry.ogr_validation` is `None`, the OGR columns (18, 19, 20) are explicitly `None` rather than containing leftover data or default values.

**See also:** Lesson #81 (Excel Conditional Formatting Priority), Lesson #82 (Adding Excel Columns Requires Constant Updates)

## 84. Backward Compatibility Testing for Flag-Controlled Features

When adding a new feature controlled by a boolean flag (like `use_other_gains_report`), create dedicated backward compatibility tests that verify the "disabled" state preserves existing behavior, not just that the "enabled" state works correctly.

**Pattern:**
1. Create a dedicated test class for backward compatibility (e.g., `TestOgrDisabledBackwardCompatibility`)
2. Test that the disabled state yields the same results as before the feature existed
3. Verify that flag-specific fields are None/blank when disabled
4. Verify that core values (gain/loss, proceeds, cost) remain unchanged from original input

**Why:** Tests for the "enabled" state only verify the new behavior works. Without explicit tests for the "disabled" state, you may silently break existing users who have the flag disabled.

**Example:** In Task 6 of the OGR validation design, the test `test_ogr_disabled_entries_have_no_ogr_validation` verifies that when `use_other_gains_report=False`, all entries have `ogr_validation=None` and gain/loss values match the original CG values exactly.

**Implementation trade-off note:** When a plan specifies a cosmetic constraint (e.g., "Excel has no OGR columns when disabled"), but the implementation uses a fixed column structure with blank cells, prefer verifying behavioral correctness over cosmetic compliance. A consistent column structure is often a reasonable engineering trade-off.

## 85. Recalculate Validation Metrics from Aggregated Values

When validating aggregated data against an external source (OGR, statements, etc.), compute validation metrics from the **aggregated totals**, not from individual pre-aggregation rows.

**Problem:** Comparing individual rows to aggregated totals produces misleading percentages:
- Single lot CG: <COST_BASIS_EUR> EUR vs OGR total: 137.73 EUR → "differs by 5474%" ❌ (noise)
- Aggregated CG: ~137 EUR vs OGR: 137.73 EUR → "differs by ~0.5%" ✅ (signal)

**Pattern:**
1. Apply corrections (e.g., direction override) to individual lots before aggregation if needed for correct totals
2. During/after aggregation, recalculate all validation metrics from aggregated values:
   - `direction_conflict` = sign(agr_OGR) ≠ sign(agr_CG)
   - `magnitude_diff_percent` = |(agr_OGR - agr_CG) / agr_CG| × 100
   - `review_required` = based on aggregated thresholds
   - `review_reason` = built from aggregated state
3. Don't inherit/OR individual lot flags; they reflect pre-aggregation noise

**Why:** Pre-aggregation rows are accounting artifacts, not the reportable event. The tax return reports the aggregated sale, so only aggregated-level validation is meaningful to the reviewer.

**Example:** In `_aggregate_ogr_validation`, the function recalculates `direction_conflict`, `magnitude_diff_percent`, and `review_required` from the summed `calculated_gain_loss` and the shared `ogr_gain_loss`, rather than taking max/OR from individual lots.

**See also:** CRG-017 (Other Gains Report Validation), Lesson #78 (OGR Directional Authority vs Wholesale Replacement)

## 86. Avoid Circular Dependencies During Module Extraction

When extracting a function to a new module, check what constants and functions it references from the source module. Circular imports occur when the new module imports from the source, and the source still needs to import from the new module.

**Resolution options:**
- Move shared constants to a lower-level module that both can import
- Inline simple literals (like `Decimal('0')`) locally in the new module
- Redesign to eliminate the cross-dependency

**Example from Task 8:** Extracting `_extract_loan_activity()` from `crypto_reporting.py` to `crypto/loan_activity.py` required handling the `ZERO` constant. Defining `ZERO = Decimal('0')` locally in the new module avoided a circular import, since the constant is only used for loan balance calculations.

## 87. Module and Class Size Limits

Large modules and classes become difficult to understand, test, and maintain. They accumulate unrelated responsibilities over time ("god class" or "god object" anti-pattern).

**Guidelines:**
- When a module exceeds 1,000 lines or contains 50+ functions/classes, consider extraction
- When a class exceeds 500 lines, evaluate whether it has multiple responsibilities
- Aim for focused modules: 200-600 lines is a practical target for most application code
- Orchestration layers should be thin: ~500 lines max for top-level coordination

**Extraction signals:**
- Module name describes multiple unrelated concepts
- Functions can be grouped into cohesive subsystems (e.g., parsing, validation, aggregation)
- Changes to one area of the module require understanding many unrelated sections
- Testing requires extensive fixture setup due to cross-cutting dependencies

**Example from crypto_reporting refactor:** The original `crypto_reporting.py` was 3,372 lines with 40+ functions handling parsing, validation, classification, aggregation, FIFO processing, and orchestration. After DDD-based extraction into focused modules (`crypto/entities.py`, `crypto/classification.py`, `crypto/validation.py`, `crypto/parsing.py`, `crypto/aggregation.py`, `crypto/ogr_handler.py`, `crypto/loan_activity.py`, `crypto/chain_derivation.py`, `crypto/operator_origin.py`, `crypto/fifo_helpers.py`), the orchestration layer reduced to 757 lines (~65% reduction), with each specialized module under 500 lines.

## 88. Single Responsibility Principle for Modules

Each module should have one clear reason to change. When a module's name or purpose cannot be described succinctly, or when it contains multiple independent subsystems, extraction is needed.

**Module cohesion indicators:**
- All functions serve the same domain concept (e.g., "crypto reward classification")
- Functions can be organized around a single abstraction or entity
- Changes to business requirements affect a predictable subset of functions
- Module has a clear, narrow public API

**Module cohesion anti-patterns:**
- "Utility" modules that mix unrelated helpers (parsing, validation, transformation)
- "Manager" classes that orchestrate unrelated workflows
- Modules where functions reference different domain layers without clear hierarchy

**Extraction approach:**
1. Group functions by domain responsibility (parsing, validation, aggregation, etc.)
2. Identify shared abstractions (entities, value objects)
3. Create cohesive modules with clear names (`crypto/classification.py`, not `crypto/utils.py`)
4. Maintain backward compatibility via package `__init__.py` re-exports
5. Use domain-driven design: entities → services → orchestration

**Example from crypto_reporting refactor:** Functions were grouped by responsibility into domain-aligned modules:
- `crypto/entities.py`: 13 domain entities (OperatorOrigin, CryptoCapitalGainEntry, etc.)
- `crypto/classification.py`: Tax classification logic with LRU-cached helper data
- `crypto/validation.py`: Date/time validation with clear ISO format rules
- `crypto/aggregation.py`: Capital gains and reward aggregation with materiality filtering
- `crypto/ogr_handler.py`: Other Gains Report override logic
- `crypto/loan_activity.py`: Loan activity extraction and balance calculation
- `crypto/operator_origin.py`: Platform-to-operator-country resolution with temporal validity
- `crypto/fifo_helpers.py`: FIFO processing for loan-affected assets
- `crypto/parsing.py`: File discovery and PDF parsing
- `crypto/chain_derivation.py`: Wallet-label-to-chain resolution

Each module has a single, clear responsibility and can be understood independently.

## 89. Read Implementation Before Writing Test Expectations

When adding edge case tests for existing functions, read the actual implementation first to understand what patterns it supports before writing expected results.

**Anti-pattern:** Writing test expectations based on function name, documentation, or assumptions about what the function "should" do, then debugging failures when expectations don't match reality.

**Correct approach:**
1. Read the function implementation completely
2. Identify all conditional branches, special cases, and return paths
3. Write test expectations that match the actual behavior
4. Add tests for genuine edge cases, not imagined patterns

**Example from chain derivation tests:** Initial tests expected "Ledger Nano X (SOL)" → "Solana" and "0x1234...abcd.eth" → "Ethereum", but the actual `_derive_chain` implementation returns "Unknown" for both patterns. Reading the implementation first would have revealed: the function only matches chains in a predefined `_KNOWN_CHAINS` set after normalization, it doesn't guess from ticker suffixes or address patterns.

## 90. Edge Case Coverage for Validation Functions

Validation functions with conditional logic need comprehensive edge case coverage for all validation branches.

**Required coverage for date/time validation:**
- Format checks: correct vs incorrect separators, missing components, extra components
- Zero-padding: required vs missing vs over-padded (e.g., "2024-1-1", "2024-001-01")
- Numeric ranges: non-numeric characters, out-of-range values (year < 2009, > 2100, month > 12, day > 31, hour > 23, minute > 59, second > 59)
- Calendar validity: Feb 30, Apr 31, leap year Feb 29 (2024 vs 2023)
- Time components: missing seconds, zero-padding, boundary values (00:00:00, 23:59:59)
- Whitespace handling: leading/trailing whitespace, multiple spaces, empty strings
- Boundary conditions: exact match on lower/upper bounds, before/after thresholds

**Required coverage for string validation:**
- Empty strings, whitespace-only strings, single-character inputs
- Multi-byte characters, control characters
- Multi-character prefixes, padded inputs
- Case insensitivity when applicable

**Example from date validation tests:** Added 57 edge case tests for `_validate_iso_date` and `_parse_transaction_date` covering zero-padding validation (2024-1-1 rejected), calendar dates (Feb 30 rejected), leap years (Feb 29 2024 accepted, Feb 29 2023 rejected), time boundaries (00:00:00 accepted, 24:00:00 rejected), and whitespace handling.

## 91. Direct Unit Testing for Extracted Helper Functions

When a complex function is extracted into a helper, add direct unit tests for the helper rather than relying only on indirect testing through integration tests.

**What to test directly:**
- Early return conditions (empty inputs, no matches)
- Conditional branches (different input paths)
- Boundary conditions (exact threshold values)
- State mutation or concatenation (appending reasons, preserving carryover)
- Edge cases (multiple items requiring min/max selection)

**Example from FIFO helpers:** `_apply_phantom_lot_flags` was extracted but initially only tested indirectly through FIFO integration. Added direct unit tests covering: empty phantom_transfers (early return), mismatching asset/platform (no effect), realizations before vs after earliest_phantom date (conditional flagging), appending phantom reason to existing review_reason (concatenation), and preserving carryover/partial tx keys (state preservation).

## 92. Fix In-Scope Refactoring Findings in the Same Branch

When a branch is created for refactoring, any code review findings that result from or relate to that refactoring must be addressed in the same branch.

**What counts as "in-scope":**
- Findings that touch files already changed on the branch
- Findings that address technical debt exposed by the refactoring (e.g., validation complexity in extracted modules)
- Findings for missing test coverage on newly extracted functions
- Findings for duplicate code created during extraction

**What can be deferred:**
- Findings in unrelated parts of the codebase not touched by this branch
- Findings that would require substantial architectural changes beyond the refactoring scope
- Findings for pre-existing technical debt unrelated to this change

**Rationale:** Refactoring branches improve code quality and maintainability. Leaving related findings (especially Medium/High severity) creates a "half-refactored" state where the new structure exists but old problems remain in the same files. This forces reviewers to track another follow-up ticket and risks the findings never being addressed.

**Example from god class refactor:** The refactoring extracted `crypto_reporting.py` into 12 modules. Code review found Medium-severity issues in the extracted modules (validation complexity in `__post_init__`, missing edge case tests). These were in-scope because they touched files created by the refactoring and addressed test coverage gaps exposed by the extraction. All were fixed in the same branch.

## 93. Early Returns Can Skip Mandatory Sections

When a function renders multiple independent sections (e.g., Excel sheet writers with platform data + methodology documentation), an early return in an optional-data branch can skip mandatory sections that must always render.

**Pattern to avoid:**
```python
if not optional_data:
    render_no_data_message()
    return  # ❌ Skips mandatory methodology section
render_mandatory_section()
```

**Correct pattern:**
```python
if not optional_data:
    render_no_data_message()
    # Continue to mandatory section
else:
    render_optional_data()
render_mandatory_section()  # Always executes
```

**Why this matters:** Early returns are easy to miss during refactoring. When a section is mandatory (e.g., legal documentation, audit trail), control flow must guarantee it renders regardless of upstream data availability. Use if/else blocks instead of early returns, and test with empty inputs to verify the mandatory section appears.

**Example from assumptions_sheet.py:** The methodology section (legal documentation) must render even when crypto data is empty. Original code had `if not summaries: return` which skipped methodology entirely. Fixed by restructuring to if/else so methodology renders in both branches.

---

## 94. Verification Tests for Canonical Source Synchronization

When a system has a canonical source of truth (decision points document, feature flags config, etc.) that must be reflected in derived output (Excel methodology, UI text, API responses), add a verification test that enforces synchronization between the source and the output.

**Pattern:**
1. Define the expected set of items from the canonical source (e.g., all decision point IDs from `decision_points/2025.md`)
2. Scan the derived output for those items (e.g., regex search for DP-XXX patterns in Excel methodology descriptions)
3. Assert two conditions: (a) no expected items are missing, (b) no unexpected items are present

**Implementation example:**
```python
def test_all_decision_points_documented(self):
    """All decision points from canonical doc are documented in output."""
    expected = {"DP-001", "DP-002", ..., "DP-011"}  # From decision_points/2025.md
    found = set()
    for description in output_descriptions:
        found.update(re.findall(r"DP-\d{3}", description))
    missing = expected - found
    assert not missing, f"Missing: {sorted(missing)}"
    extra = found - expected
    assert not extra, f"Unexpected: {sorted(extra)}"
```

**Why this matters:** Without verification tests, documentation drifts silently. A decision point added to the canonical document may never be added to the Excel output, or a removed decision point may remain as dead text. The test enforces consistency and catches drift immediately.

**Example from Task 4:** The `test_all_decision_points_documented` test verifies that all 11 decision points (DP-001 through DP-011) from the canonical `decision_points/2025.md` are present in the Excel methodology section. If a decision point is added to the TOML but not to the methodology text, the test fails.

**See also:** `docs/tax/decision_points/2025.md` (canonical source), `tests/unit/application/persisting/test_assumptions_sheet.py::TestMethodologyAssumptionsSection::test_all_decision_points_documented`

---

## 95. Use the resolve-vars Utility Skill for Path Discovery

Skills that need project-specific paths (reviews, plans, tmp, etc.) should use the `resolve-vars` utility skill rather than implementing their own discovery logic or guessing from system context.

**How resolve-vars works:**
1. Reads project instructions to find `facts.md` location
2. Returns cached value if already in `facts.md`
3. Runs discovery using glob hints if not cached
4. Persists discovered value to `facts.md` for future calls

**Usage in other skills:**
```python
reviews_dir = resolve_var("reviews_dir", ["**/reviews/", "docs/history/reviews", "docs/reviews"])
plans_dir = resolve_var("plans_dir", ["**/plans/", "docs/history/plans", "docs/plans"])
tmp_dir = resolve_var("tmp_dir", ["**/tmp/", "docs/tmp"])
```

**What went wrong:** During code review, I saw a path in system context (`.../memory/docs/reviews/`) and used it without calling `resolve-vars`. The correct approach would have been to call `resolve_var("reviews_dir", ...)` which would have discovered the project's actual `docs/reviews/` folder by reading project instructions and running glob discovery.

**Why this matters:** System context contains irrelevant paths from other sessions or tools. The `resolve-vars` utility exists to discover the correct path for the current project and persist it locally. Guessing from context leads to wrong output locations.

---

## 96. Structural Identification for Excel Output Tests

When testing Excel output, identify data items by their structural properties (column population, font attributes) rather than hardcoded value exclusions. Tests using hardcoded values from test fixtures break when fixture defaults change.

**Pattern to avoid:**
```python
exclusion_set = {
    "Section Header 1",
    "Section Header 2",
    "Kraken",  # ❌ From test fixture default
    "NO",      # ❌ From test fixture default
}
if cell_value not in exclusion_set:
    items.append(cell_value)
```

**Correct pattern, identify by structure:**
```python
for row_idx in range(1, 200):
    label = ws.cell(row_idx, 1).value
    description = ws.cell(row_idx, 2).value
    column_3 = ws.cell(row_idx, 3).value

    # Methodology items: label + description present, column 3 empty
    if label and description and not column_3:
        items.append((label, description))
```

**Why this matters:** Hardcoded exclusions couple tests to implementation details of test fixtures (`_make_capital_entry(platform="Kraken")`). When fixture defaults change, tests fail despite the Excel structure being correct. Structural identification decouples tests from data values and verifies the actual output format.

**Verification approach:** Before writing the test, inspect the actual Excel rendering to understand structural properties:
- Which columns are populated for each row type?
- Are labels bold or regular?
- What distinguishes section headers from data rows?

**Example from test_assumptions_sheet.py:** The original `test_methodology_items_have_legal_citations` excluded `"Kraken"` and `"NO"` (values from `_make_capital_entry` defaults). Fixed by checking that methodology items have column 1 (label) + column 2 (description) populated, with column 3 empty (platform data has multiple columns).

## 97. Characterization Tests Can Reveal Plan-Assumption Errors Between Related Quantities

When a characterization (golden-value) test captures the actual current behavior and the captured value disagrees with the plan's stated expected value, the disagreement is itself a finding. Investigate the root cause before any implementation task proceeds, because downstream tasks often depend on the incorrect assumed value.

**Why this happens:** Plan authors writing expected values for characterization tests may conflate two related but distinct quantities when one is a downstream authoritative total and the other is the post-transformation output. The override/transformation in question may apply directional authority (sign) while preserving the other quantity's magnitude, so the expected value the author wrote (the authoritative total) is NOT the value the pipeline actually emits.

**Required response when characterization disagrees with the plan:**
1. Capture the REAL current output as the golden value (never the plan's assumed value); the whole point of a characterization test is to lock in actual behavior.
2. Trace WHY they differ using raw source inspection (read source CSVs directly, sum lots, identify which quantity the plan's number actually represents).
3. Reconcile the plan narrative so downstream tasks and the user see the corrected value with rationale.
4. Flag the discrepancy to the orchestrator/user so dependent tasks are aware.

**Do NOT** weaken the characterization assertion to match the plan's incorrect value; that defeats the test's purpose and hides a real bug or real behavior.

**Example:** The 2026-06-13 derivatives-separation plan (Task 1) stated the Case 2 expected Crypto Gains output was `<-OGR_NET_EUR> EUR` (the Other Gains Report total for that disposal), but the actual override output is `-<CG_LOTS_EUR> EUR`. The `_apply_ogr_direction_override` function uses OGR for DIRECTION only and preserves CG MAGNITUDE: the 109 CG lots sum to `+<CG_LOTS_EUR>` pre-override, and flipping the sign of each yields `-<CG_LOTS_EUR>` post-override. The `<-OGR_NET_EUR>` is the OGR-row total, a different quantity from the post-override aggregated output. The characterization test captured `-<CG_LOTS_EUR>` and the plan narrative was reconciled. See the characterization golden fixture (local) and lesson #78 (OGR directional authority runtime semantics).

**See also:** Lesson #71 (validation-first investigation), Lesson #72 (data trace verification), Lesson #78 (OGR directional authority semantics), `docs/domain/plan_quality_guidelines.md`.

---

## 98. Probe the Canonical URL Before Assuming an Official Source Is Unavailable

When a plan or task assumes an authoritative document (statute amendment, binding ruling, official circular) is "not publicly indexed", "request-specific", or otherwise unreachable, do NOT treat that assumption as ground truth. Probe the issuing authority's canonical URL pattern directly (HTTP HEAD or ranged GET) before falling back to secondary sources or skipping archival.

**Why this matters:** Plans encode assumptions about source availability that may be outdated or simply wrong. The cost of a probe is one HTTP request; the cost of skipping archival is a weakened source corpus where the authoritative document is absent and downstream analysis leans on secondary sources that paraphrase it. Several issuing authorities publish binding rulings and circulars in public indexes even when they are nominally request-specific.

**Required behavior:**
1. Construct the canonical URL from the issuing authority's documented naming convention (e.g. AT vinculativa rulings follow `info.portaldasfinancas.gov.pt/.../informacoes_vinculativas/.../Documents/PIV_<numero>.pdf`).
2. Issue a HEAD request (or a small ranged GET) to check status, content-type, and content-length.
3. On HTTP 200 with the expected media type, download and archive the document to `docs/tax/.../official/` and add the provenance entry to `sources.md`.
4. Only when the probe definitively fails (404, 403, or a login redirect) should you fall back to secondary sources or document the source as unavailable.
5. Record the probe outcome (success or the specific failure) in the implement log so the assumption-vs-reality gap is visible.

**Anti-pattern:** Reading a plan task that says "the ruling is request-specific, so we will rely on the secondary advisory page" and proceeding straight to secondary-source archival without probing the primary URL.

**Example:** The 2026-06-13 derivatives-separation plan (Task 2) stated AT binding ruling PIV 28298/2025 was expected to be request-specific and not in the public vinculativa index. A HEAD probe of the canonical `Documents/PIV_28298.pdf` URL returned HTTP 200, `application/pdf`, 64,788 bytes. The ruling IS published in the public CIRS vinculativa list and was downloaded directly to `docs/tax/laws/pt/crypto-tax/official/at_piv_28298_2025.pdf`, making the secondary-source-only fallback unnecessary. The ruling body also yielded the precise filing targets (Anexo G Quadro 13 code G51 for resident-source derivatives gains; Anexo J Quadro 9.2.B code G30 for non-resident) that no secondary source stated as explicitly.

**See also:** `docs/project-guidelines.md` #1 (external source archive provenance and freshness), CLAUDE.md source-archival rules, Lesson #94 (verification for canonical source synchronization).

---

## 99. Trace the Fixture When Plan Pseudocode Compares Same-Unit Fields by Name

When plan pseudocode compares two fields by name and those fields share a unit (EUR, count, timestamp) but live on different domain objects or different fields of the same dataclass, do not translate the pseudocode literally. Trace the fixture first to confirm the two fields represent the same economic quantity. Field names like `gain_loss_eur` suggest "the EUR value" but the field's actual semantic may be a derived quantity (realized gain = proceeds − cost) that is structurally different from another EUR field (disposal proceeds) even though both live on the same dataclass.

**Why this happens:** Plan authors writing pseudocode for a comparison operation may pick the field whose name sounds closest to the intent ("gain_loss_eur" sounds like the EUR magnitude), without checking whether the field's actual semantic matches the quantity the comparison requires. When multiple EUR-denominated fields coexist on the same dataclass with distinct economic meanings (proceeds, cost, realized gain, fee), the field-name conflation is invisible until the comparison runs against real numbers.

**Required behavior:**
1. When the pseudocode references a field by name on a domain object, especially for a magnitude or equality comparison, identify which other same-unit fields exist on that dataclass.
2. For each candidate field, trace the fixture to confirm what economic quantity the field actually carries (read the dataclass docstring; verify against a real source row).
3. Construct the RED-phase test fixture so that the candidate fields are set to DIFFERENT but realistic values, not the same value; this forces the test to discriminate between them. If the fixture sets `proceeds_eur=<FEE_PROCEEDS_EUR>` and `gain_loss_eur=<FEE_GAIN_EUR>`, a pseudocode comparison against `gain_loss_eur` will fail visibly (|<FEE_PROCEEDS_EUR> − <FEE_GAIN_EUR>| = <TOLERANCE_DELTA_EUR> > tolerance), exposing the field-name error before production code ships.
4. If the fixture trace shows the pseudocode field is wrong, correct the pseudocode field reference in the plan, document the correction as a DESIGN CORRECTION note, and update the constant's comment to prevent a future maintainer from reintroducing the bug.

**Distinguishing from #97:** Lesson #97 covers characterization tests that capture a value disagreeing with the plan's stated expected value (magnitude vs direction conflation in captured output). This lesson covers plan pseudocode referencing the wrong field by name; the comparison never runs against production data until RED-phase fixture construction exposes the field-name error. Both are verification rules but they have distinct triggers (golden-value disagreement vs fixture-driven field selection) and distinct fixes (reconcile narrative vs rewrite pseudocode field reference).

**Anti-pattern:** Reading pseudocode that says `abs(cg_matches[0].gain_loss_eur - abs(ogr_row.gain_loss)) <= TOLERANCE` and implementing it verbatim, without checking whether `gain_loss_eur` (realized gain) and `ogr_row.gain_loss` (disposal proceeds) describe the same economic quantity. The comparison would silently classify correct cases as `Ambiguous` and break the entire downstream pipeline.

**Example:** The 2026-06-13 derivatives-separation plan (Task 5) pseudocode compared OGR `Value (EUR)` (disposal proceeds for Loss rows) against CG `gain_loss_eur` (realized gain, cost-subtracted). These are different quantities: OGR `Value (EUR)` is disposal proceeds and the correct CG counterpart is `proceeds_eur`. The Case 1 fixture sets `proceeds_eur=<FEE_PROCEEDS_EUR>, gain_loss_eur=<FEE_GAIN_EUR>` against OGR=<FEE_PROCEEDS_EUR>, so the comparison only succeeds against `proceeds_eur` (|<FEE_PROCEEDS_EUR> − <FEE_PROCEEDS_EUR>| = 0 ≤ tolerance); comparing against `gain_loss_eur` gives |<FEE_GAIN_EUR> − <FEE_PROCEEDS_EUR>| = <TOLERANCE_DELTA_EUR> > tolerance and would wrongly route the row to `Ambiguous`. The fixture-driven trace exposed the field-name error during RED phase, and the constant's comment (`_TOLERANCE_OGR_CG` in `classification.py`) plus the `ParsedOgrRow` dataclass docstring document the correct field so a future maintainer cannot reintroduce the bug. See the implementation log (local).

**See also:** Lesson #97 (characterization tests revealing magnitude-vs-direction conflation), Lesson #72 (data trace verification), Lesson #89 (read implementation before writing edge-case tests), CLAUDE.md §4 Agent Workflow Rules (verification-first task ordering).

## 100. Verify Plan-Time Claims About Production Code Before Writing Tasks

When a plan task, design invariant, or gist example makes a claim about production code (field semantics, file paths, line numbers, function behavior, return shape), the plan author must verify the claim against the actual source BEFORE writing plan tasks that depend on it. A single Read call per claim eliminates an entire class of plan-review Blockers.

**Why this matters:** Plan review sub-agents will catch these defects, but every Blocker found in review is a defect the author could have caught with one Read call. Each Blocker forces a revision cycle (re-write the plan, re-launch review, re-verify), costing more rounds than the original verification would have. Plans that ship with N unverifiable claims typically absorb N+ Blockers across the first two review rounds.

**Required behavior:**
1. Before writing any plan task that references a production-code fact (field name, line number, file path, function signature, return type), open the source file and confirm the fact.
2. Field-semantics claims are the highest-risk category: a plan that says "field X carries minute-precision timestamp" must be verified by reading the parser that populates field X. If the parser strips the time component, the claim is wrong and downstream matching logic built on it will fail.
3. Line-number claims drift as the file evolves; cite line numbers only after reading the file at plan time, and prefer function-name anchors over line numbers when the surrounding code is stable.
4. When a user-facing design preference (e.g., "match by timestamp + asset + wallet + amount") implies a code capability (timestamp precision on a domain field), verify the capability exists before accepting the preference. If it does not, surface the trade-off explicitly in the plan's Monitor section rather than silently substituting an alternative.

**Distinguishing from #71 / #72:** Lesson #71 covers investigation tasks ("is X handled correctly?") and mandates verification-first task ordering. Lesson #72 extends that to data trace verification. This lesson covers **plan-time claims** about code structure (what a field carries, what a function returns, what line N does) and mandates source verification during plan authoring, before any task is written. The trigger is the author writing a code-reality claim, not the author investigating an existing behavior.

**Anti-pattern:** Writing "the match key is (timestamp, asset, wallet, amount) with minute-precision timestamp" in a plan without checking whether `CryptoCapitalGainEntry.disposal_date` actually carries minute precision. The field is day-level (`format_datetime` at `koinly_parser.py:123-132` strips the time), so the entire matching strategy must be reworked in revision, costing a full review round.

**Example:** The 2026-06-14 derivatives-th-label-cg-dedup plan claimed minute-precision timestamp matching in its Gist, Design Invariant 6, Task 4 test names, and Task 4 implementation note. The r1 plan review caught the field-shape error as Blocker 1 across 4 plan locations. The revision dropped timestamp from the match key and adopted (date, asset, wallet, amount) with strict-equality at 6-decimal rounding, but the cost was one full review round. A single Read of `koinly_parser.py:123-132` during plan authoring would have prevented the Blocker entirely.

**See also:** Lesson #71 (verification-first task ordering), Lesson #72 (data trace verification), Lesson #99 (trace fixture when comparing same-unit fields by name), CLAUDE.md §4 Agent Workflow Rules.

## 101. Trace Each Affected OGR Row to Its Originating TH Type Before Designing a Type-Filtered Scanner

When designing a scanner that filters TH rows by Type (e.g., `crypto_withdrawal` only), trace each OGR row on the affected date back to its originating TH source row and confirm which Type that TH row carries. OGR rows on the same date, same asset, same wallet may originate from different TH Types; only the OGR rows sourced from matching TH Types are affected by the scanner.

**Why this happens:** Koinly emits one OGR row per disposal event but the disposal may be sourced from either a `crypto_deposit` (e.g., realized gain paid out) or a `crypto_withdrawal` (e.g., fee deducted). When the plan's narrative groups OGR rows by date, the author may assume all rows on that date share the same behavior change, but the scanner's Type filter means only some rows are actually affected. The unfiltered rows keep their original routing; only the filtered rows reclassify.

**Required behavior:**
1. When the plan describes a behavior change for "OGR rows on date D," identify each individual OGR row on D and trace it to its source TH row (match by timestamp, asset, wallet, amount).
2. For each traced OGR row, record the TH Type. Mark the OGR row as affected (Type matches the scanner filter) or unaffected (Type does not match).
3. Write test expectations that distinguish the two: affected rows reclassify, unaffected rows keep their routing. Do not write a single test name like `test_ogr_routes_to_derivatives` that implies all OGR rows on the date behave the same way.
4. Update existing tests that assert the OLD routing of now-affected rows; do not just add new tests for the new routing.

**Anti-pattern:** Reading an OGR file that shows "Profit +<PROFIT_EUR>, Loss <-FEE_PROCEEDS_EUR>" on 2025-01-12 and writing a plan that says "the +<PROFIT_EUR> Profit OGR row routes to derivatives_entries after the dedup" when the +<PROFIT_EUR> Profit row is sourced from a `crypto_deposit` (filtered out by the scanner) and is therefore unaffected. The <-FEE_PROCEEDS_EUR> Loss row, sourced from a `crypto_withdrawal` with Label=Futures fee, is the one that actually reclassifies. The plan ships with a misleading test name and a missing assertion; a follow-on plan review round is needed to catch the confusion.

**Example:** The 2026-06-14 derivatives-th-label-cg-dedup plan's Task 6 described Case 1 (2025-01-12) as "the +<PROFIT_EUR> Profit OGR row still routes to derivatives_entries" with test name `test_profit_ogr_routes_to_derivatives`. The r2 plan review caught the confusion: TH line 204 (`crypto_deposit` Realized gain 143.752 USDT) sources the +<PROFIT_EUR> Profit OGR row and is filtered out by the scanner's `crypto_withdrawal` filter; TH line 205 (`crypto_withdrawal` Futures fee <FEE_PROCEEDS_USDT> USDT) sources the <-FEE_PROCEEDS_EUR> Loss OGR row and is the row that actually reclassifies. The revision rewrote Task 6 to distinguish the two rows and added `test_fee_disposal_reclassifies_to_derivatives` for the actual behavior change. See the th-label-cg-dedup plan review r2 (local) Blocker 1.

**See also:** Lesson #72 (data trace verification), Lesson #99 (trace fixture when comparing same-unit fields by name), CLAUDE.md §3 Repository Constraints (derivatives separation).

## 102. Add a Count-Matched-Items-Per-Event Safety Check When Matching by Non-Unique Keys

When a dedup or matching algorithm uses a key tuple that does not include a globally unique identifier (e.g., `(date, asset, wallet, amount)` without a transaction hash or row ID), add a count-matched-target-items-per-source-event safety check that logs a warning when one source event matches more than one target item. The warning surfaces two distinct cases for review: legitimate FIFO splits (one disposal split into N lots, all expected to match) and coincidental amount collisions (two unrelated events on the same date with the same amount, an over-removal risk).

**Why this matters:** Without a unique identifier, the matcher cannot distinguish "N target items are FIFO splits of one source event" from "N target items are unrelated events that happen to share the key." The first case is correct (remove all N); the second is a silent over-removal that corrupts downstream aggregates. The warning does not block removal (the FIFO-split case is more common in practice) but it makes the coincidental-collision case observable in logs so the user can audit.

**Required behavior:**
1. After the matching pass, group removed target items by their originating source event.
2. For each source event with `matched_count > 1`, log a warning naming the source event (date, label, amount) and the matched count.
3. Phrase the warning to surface both interpretations: "possible FIFO split or coincidental amount collision."
4. Add a unit test that constructs the coincidental-collision case (two target items with the same amount as one source event but unrelated to it) and asserts the warning fires.

**Distinguishing from a strict matcher:** A strict matcher (match at most one target per source event, warn on overflow) is tempting but wrong for FIFO-split cases: a single disposal may legitimately produce 50+ target lots, all of which should be removed. The count-based warning preserves correct behavior for the common case while making the rare over-removal case visible.

**Anti-pattern:** Matching by (date, asset, wallet, amount) with no post-pass check, assuming amount disambiguation is sufficient. On a fixture with 108 target lots at one timestamp (FIFO splits of one disposal) plus 2 unrelated derivatives events with amounts that coincidentally match 2 of the 108 lots, the matcher silently removes those 2 unrelated lots along with the legitimate matches, corrupting the aggregate. The user sees an unexpected Crypto Gains total with no warning to explain it.

**Example:** The 2026-06-14 derivatives-th-label-cg-dedup plan's Task 4 added `warns_when_one_th_event_matches_multiple_cg_lots` after the r2 review flagged the silent-overremoval risk. The implementation builds a `dict[derivatives_event_key, list[matched_cg_lots]]`, removes all matched lots, and logs a WARNING per source event whose matched count > 1. The 2025-01-13 fixture has 108 CG lots at the 13:01 timestamp; if any lot's amount coincidentally matches the Futures fee TH event (<FUTURES_FEE_USDT> USDT), the warning surfaces the collision for review. See the th-label-cg-dedup plan review r2 (local) Medium 2.

**See also:** CLAUDE.md §3 Repository Constraints (no silent drops), CLAUDE.md §1 Instruction Rules (data-loss at warning+).

## 103. Audit for Shared Identifiers Across Reports When Separating a Previously-Merged Tax Category

When introducing a separation between two tax categories that previously shared a single pipeline (e.g., splitting a unified crypto-gains flow into spot vs derivatives), audit whether the same disposal event appears in **both** source reports that feed the separated paths. Without an explicit deduplication step removing the now-derivatives-classified items from the spot path, those items are double-counted: once in the new derivatives aggregate, once in the legacy spot aggregate. The trigger for the audit is the **introduction of the separation itself**, not a later data-quality or cross-report validation check.

**Why this happens:** Koinly (and similar exporters) emit one row per disposal event in each report that references it. A derivatives Futures-fee disposal appears both as an OGR `Loss` row (because it has no cost basis, so Koinly routes it to Other Gains) and as a CG lot (because Koinly also records it as a disposal of the fee asset against its acquisition lot). Before the separation, only the CG path was read, so the duplication was invisible. The moment a plan introduces a derivatives path that reads OGR, both paths light up for the same disposal, and the spot CG total silently inflates.

**Required behavior:**
1. When a plan introduces a new classification path that consumes a previously-unused source report (OGR, rewards, etc.), enumerate every other report the existing pipeline already reads (CG, TH).
2. For each disposal event in the new report, check whether the same `(date, asset, wallet, amount)` (or whatever identity tuple applies) also appears in the existing reports.
3. If overlap exists, write an explicit dedup step in the plan that removes the overlapping items from the legacy path. Do not rely on the new path's downstream classifier to "handle" the overlap; the legacy path aggregates independently.
4. Add a reconciliation test that asserts the union of (spot aggregate, derivatives aggregate) matches the pre-separation total. A drift in this union after the separation is the symptom of a missing dedup step.

**Distinguishing from #73 (Cross-Report Validation):** Lesson #73 catches **data corruption** where one report contradicts another (e.g., OGR says Loss while CG says Gain on the same disposal). This lesson catches **structural double-counting** where both reports agree and are individually correct, but the pipeline reads both without dedup. The failure mode for #73 is wrong totals; the failure mode here is inflated totals with no inconsistency between reports.

**Anti-pattern:** A separation plan that says "OGR rows of Type Loss route to `derivatives_entries`; CG rows remain in spot" without checking whether the same disposal is present in both. The spot CG total silently includes the derivatives-classified lots, the derivatives total includes the OGR Loss, and the sum is greater than the pre-separation total. The error surfaces only at tax-filing time when the IRS-ready total is too high.

**Example:** The 2026-06-13 derivatives-separation plan split OGR into derivatives_entries vs spot but did not dedup the corresponding CG lots from the spot table. ByBit USDT Futures-fee and Funding-fee disposals on 2025-01-13 and 2025-01-24 appeared in both: as OGR Loss rows (routed to derivatives) and as CG lots (left in spot). The fix required the entire 2026-06-14 derivatives-th-label-cg-dedup follow-up plan to scan TH for `crypto_withdrawal` events labeled Funding fee / Futures fee / Realized gain, match them against CG lots by `(date, asset, wallet, amount)`, and remove the matched lots from the spot index before the spot/derivatives classifier runs. A 5-minute audit at 2026-06-13 plan time ("does any disposal appear in both OGR and CG?") would have caught the gap and avoided the follow-up plan entirely. See `docs/plans/2026-06-14-derivatives-th-label-cg-dedup.md`.

**See also:** Lesson #45 (deduplication key identity), Lesson #73 (cross-report validation), Lesson #101 (trace OGR→TH source Type), CLAUDE.md §3 Repository Constraints (derivatives separation), PT-C-034 in `docs/domain/crypto_rules.md`.

## 104. Trace ALL Branches of a Multi-Branch Conditional When Implementing a Tiered Rule

When a plan modifies a multi-branch conditional (e.g., an `if cost == 0: ... if proceeds == 0: ...` block) to implement a new tiered rule, the plan author MUST trace every input combination through ALL branches before finalizing the implementation steps. A common failure mode: changing one branch's condition to suppress an input, while leaving the sibling branch unchanged, which still fires on that same input and contradicts the stated design invariant.

**Why this happens:** When reading a conditional like `if cost == 0: flag_A()` followed by `if proceeds == 0: flag_B()`, the author focuses on the branch they intend to modify (the cost branch) and overlooks that the sibling branch (proceeds branch) has no guard against the same input. For the input `cost=0, proceeds=0`, both branches evaluate True and both fire. The plan's design invariant ("zero-zero never flags") is then unachievable as written.

**Required behavior:**
1. Enumerate the full input domain (all combinations of the branching variables).
2. For each combination, trace through EVERY branch in order, not just the branch being modified.
3. If any combination produces an outcome that contradicts a stated design invariant, the plan MUST modify every branch that contributes to that outcome, not just the "obvious" one.
4. Include a trace table in the plan showing input -> expected branch outcomes -> expected final result. The trace is part of the plan, not just a verification step for review.

**Example:** The 2026-06-15 zero-basis-review-materiality plan (r1) proposed gating only the cost branch (`if cost == 0 and proceeds >= min_proceeds:`) while leaving the proceeds branch (`if proceeds == 0:`) unchanged. The design invariant stated "zero-zero entries never flag". But for input `cost=0, proceeds=0`: the cost branch evaluates `0 >= 10` = False (correctly suppressed); the unchanged proceeds branch evaluates `0 == 0` = True (INCORRECTLY fires). The 779 FEE-token entries the plan intended to suppress would still flag. r1 Blocker 1 caught this; the fix required adding `and cost > 0` to the proceeds branch so zero-zero inputs fail both conditions.

**Distinguishing from #100 (verify claims against source):** Lesson #100 verifies that file paths, line numbers, and function signatures match reality. This lesson verifies that the proposed CODE CHANGE produces the stated BEHAVIOR across the full input domain. A plan can have perfectly accurate citations and still specify a code change that contradicts its own design invariants.

**Anti-pattern:** A plan that says "modify branch X to handle case Z; leave branch Y unchanged" without tracing case Z through branch Y. The trace must be explicit: "for input Z, branch X evaluates to <result>, branch Y evaluates to <result>, combined outcome is <result>, which matches/falsifies the design invariant."

**See also:** Lesson #100 (verify plan claims against source), CLAUDE.md §4 Agent Workflow Rules (TDD approach), the r1 Blocker 1 trace in the zero-basis plan review r1 (local).

## 105. Calibrate Exception Handling Strategy to the Cost of Silent Failure When Reusing a Helper Pattern

When reusing a security/validation pattern from another module (symlink rejection, size limit, JSON parsing), do NOT blindly inherit the source module's exception-handling strategy. The right behavior for malformed input depends on the cost of silent failure at the NEW call site, not at the source. A non-critical feature may gracefully degrade (return empty on malformed input); a correctness-critical feature MUST raise.

**Why this happens:** When a plan says "reuse the security patterns from `classification._load_popular_crypto_tokens`," the implementer reads the source function and copies both the validation guards AND the exception handling. The validation guards (symlink rejection, size cap) are universally correct. The exception handling (`except json.JSONDecodeError: return frozenset()`) is a per-feature decision based on what "empty" means downstream. Copying it without checking the new feature's failure cost produces a silent-correctness-bug class.

**Required behavior:**
1. Distinguish "validation guards" (security, format) from "exception handling strategy" (degrade vs raise) when reading the source pattern. Only the guards are universally reusable.
2. For the new call site, ask: what happens downstream if this function returns empty on malformed input?
   - If empty means "skip a non-critical enrichment" (e.g., popular-token detection, cosmetic annotation) -> graceful degradation with WARNING log is correct.
   - If empty means "skip a correctness-critical step" (e.g., deduplication, required validation, aggregation) -> raising `FileProcessingError` is mandatory. Silent empty leaves wrong data in the output.
3. Only the MISSING-file case is uniformly safe to degrade (Design Invariant 8 pattern); malformed-content (bad JSON, wrong shape, wrong types) must raise when correctness is at stake.

**Example:** `classification._load_popular_crypto_tokens` swallows `json.JSONDecodeError` and returns `frozenset()` because popular-token detection is a non-critical enrichment, and an empty set means "no extra annotation," which is harmless. The 2026-06-14 derivatives-th-label-cg-dedup plan's Task 2 reused the symlink rejection and size limit from that function but intentionally DIVERGED on exception handling: `_load_derivatives_labels_config` raises `FileProcessingError` on malformed JSON, missing `derivatives_th_labels` key, or wrong value type. Silently returning `frozenset()` would skip derivatives CG deduplication, leaving the spot capital-gains total inflated by the double-counted derivatives lots (the exact bug the plan exists to fix). Only the missing-file branch degrades (WARNING plus empty set), per Design Invariant 8.

**Distinguishing from #61 (logging for silent handlers):** Lesson #61 says "if you DO degrade, log it." This lesson says "decide whether to degrade or raise in the first place, based on downstream cost." A correctly logged silent degradation is still wrong if the feature is correctness-critical.

**Anti-pattern:** A plan that says "mirror the error handling of `<source function>`" without checking whether the source function's degrade-vs-raise choice fits the new call site. The implementer copies `except JSONDecodeError: return frozenset()`, the new feature silently no-ops on malformed config, and the user sees a wrong tax total with no error to explain it.

**See also:** Lesson #61 (log silent exception handlers), Lesson #51 (all-or-nothing validation for file sets), CLAUDE.md §1 Instruction Rules (data-loss at warning+, fail clearly), CLAUDE.md §3 Repository Constraints (no silent drops).

## 106. Reuse the Parsed Value Inside the Existing Try Block When Extracting a Second Derived Value

When a plan asks you to compute a second derived value from an input that is already parsed inside a `try ... except ValueError` block (for example, adding a minute-precision `timestamp_str` alongside an existing day-level `date_str`, both derived from the same source date string), reuse the already-parsed object inside the SAME try block. Do NOT re-invoke the parser outside the block to compute the second value.

**Why:** The existing try block exists because the parser (`parse_koinly_datetime`, `parse_koinly_decimal`, etc.) raises `ValueError` on malformed input, and the surrounding code expects that exception to be caught and handled (typically: warn and skip the row, or log an error and continue). Re-invoking the parser outside the block produces an UNCAUGHT `ValueError` that aborts the entire batch, contradicting the row-level error-handling contract (CLAUDE.md §1: catch row-level parse errors per row).

**Required behavior:**
1. Identify the value already being parsed inside the try block (`parsed_dt = parse_koinly_datetime(date_raw)`).
2. Compute both derived strings from that one parsed object, inside the same block:
   ```python
   parsed_dt = parse_koinly_datetime(date_raw)
   date_str = format_datetime(parsed_dt)            # existing day-level string
   timestamp_str = parsed_dt.strftime("%Y-%m-%d %H:%M")  # new minute-precision string
   ```
3. Do NOT write `timestamp_str = parse_koinly_datetime(date_raw).strftime(...)` as a separate statement outside the block. A malformed `date_raw` raises `ValueError` that nothing catches.

**General form:** Whenever N derived values must be computed from one fallible parse, parse once inside the error-handling scope and derive all N from the parsed object. This holds for any parser-with-exceptions pattern, not just datetime parsing.

**Distinguishing from #56 (try/finally resource-cleanup scope):** Lesson #56 is about ensuring all raising operations are inside a try/finally so cleanup runs. This lesson is about not re-invoking a fallible operation outside a try/except that was set up to catch its first invocation. Both are error-scope guards but address different failure modes: #56 prevents leaked resources; this one prevents uncaught exceptions that bypass row-level error handling.

**Example:** Task 3 of the 2026-06-14 derivatives-th-label-cg-dedup plan added `timestamp_str` to `ParsedTxRow` and `disposal_timestamp` to `CryptoCapitalGainEntry`. Both `_classify_rows_for_loan_affected_assets` (parsing.py) and `_parse_capital_gains_file` (crypto_reporting.py) already parsed the date inside a try block to compute `date_str`/`disposal_date`. The implementation captured `parsed_dt`/`disposal_dt` first, then derived both strings from it inside the same block, rather than re-calling `parse_koinly_datetime` outside. See the implementation log (local).

## 107. Use an Ordered Queue Per Non-Unique Key When Multiple Source Events May Share a Key With Multiple Target Items

When a matching algorithm pairs N source events against M target items by a key tuple that is NOT globally unique (e.g., `(timestamp, asset, wallet, amount)` without a transaction hash or row ID), and multiple source events can share the same key with multiple target items, build a `dict[key] -> deque[target_items]` (or any FIFO queue) and pop exactly one item per source event. Do NOT use `dict[key] = item` assignment, which silently overwrites earlier items when two targets share a key, and do NOT use `dict[key] = item` followed by `del dict[key]`, which loses the second target if a second event arrives for the same key.

**Why this matters:** Without a queue per key, a same-key collision is no longer deterministic. With a dict-of-scalars, the second target item overwrites the first and the first source event matches nothing. With a dict-of-lists plus naive indexing, the matching order depends on iteration order, which is not the acquisition order the algorithm intends. A per-key deque (a) preserves target order (the order items were appended, typically acquisition-date-sorted), (b) ensures each source event consumes exactly one target, and (c) makes "items left over after all events consumed" observable as a separate surplus signal.

**Required behavior:**
1. Sort target items by their intended match order (typically `(key, acquisition_date, row_index)`) before building the index, so the deque order is deterministic.
2. Build `dict[key] -> deque()` and append each target item to its key's deque.
3. For each source event (in source-sorted order), pop one target from the head of its key's deque. If the deque is empty, the event falls through to the next matching phase (or is recorded as unmatched).
4. After all source events are processed, any non-empty deque holds surplus target items that no source event claimed. Surface these in a single summary WARNING (not per-item) so the user can audit whether the surplus is a missed FIFO split, a stale lot from a prior year, or a coincidental key collision.

**Distinguishing from #102 (count-matched-items-per-event warning):** Lesson #102 addresses the one-source-event-to-many-targets case (one derivatives disposal split into N FIFO lots). This lesson addresses the many-source-events-to-many-targets case (multiple derivatives events on the same timestamp with the same amount). Both can occur in the same matcher; #102's per-event count check and this lesson's per-key queue are complementary guards against different silent-loss modes.

**Distinguishing from #45 (deduplication key identity):** Lesson #45 is about CHOOSING the right key tuple (which fields uniquely identify an item). This lesson assumes the key is already chosen and is non-unique by design (because no globally unique identifier is available in the source data), and prescribes the data structure that prevents silent loss under that constraint.

**Anti-pattern:** Building `matched = {key: target for target in targets}` and then `for event in events: matched.pop(key(event), None)`. When two targets share a key, the second assignment overwrites the first; the first source event finds the second target and removes it; the second source event finds nothing. The first target is silently retained in the output (the opposite of the intended dedup), and no warning fires because the per-key deque length was never observed.

**Example:** Task 5 of the 2026-06-14 derivatives-th-label-cg-dedup plan implemented `remove_derivatives_flagged_lots` phase 1 (exact match) with `dict[tuple[str, str, str, Decimal], deque[_IndexedLot]]`. Each derivatives event pops one lot from the head of its key's deque; if the deque is empty, the event falls through to phase 2 (contiguous-range fallback). After both phases, `_collect_surplus_lots(deques, matched_indices)` walks the non-empty deques to report leftover lots in the summary WARNING. The 2025-01-13 fixture has 108 CG lots at the 13:01 timestamp; if two derivatives events on that timestamp have the same amount as two of those lots, the deque ensures each event consumes its own lot rather than the second event finding an empty bucket. See the implementation log (local).

**See also:** Lesson #45 (deduplication key identity), Lesson #102 (count-matched-items-per-event warning), CLAUDE.md §3 Repository Constraints (no silent drops).

## 108. Recompute Window-Relative Tolerance After Every Shrink Step in a Two-Pointer Sliding-Window Matcher

When implementing a two-pointer sliding-window matcher that finds a contiguous range of items whose summed amount equals a target within tolerance, and the tolerance scales with the window size (`tolerance = scale * range_size`), recompute the tolerance after every shrink step. Use `left < right` (not `left <= right`) as the shrink-loop bound so the single-item window is preserved as a candidate match.

**Why this matters:** Two correctness traps hide in this algorithm:

1. **Stale tolerance after shrink.** If the tolerance is computed once before the shrink loop, the shrink condition `running_sum > target + tolerance` uses the tolerance for the ORIGINAL window size, not the shrunken window. After shrinking, `range_size` is smaller and the tolerance should be tighter; using the stale (larger) tolerance admits windows that should have been rejected, and the matching condition `abs(running_sum - target) <= tolerance` then accepts a sum that is outside the correct tolerance for the current window. The fix is to recompute `range_size` and `tolerance` inside the shrink loop after each `left += 1`.

2. **Single-element window collapse.** If the shrink condition uses `left <= right`, the loop shrinks past the single-element window (`left == right + 1`), leaving an empty window. The single-element window is the ONLY candidate when `range_size == 1`, and it may match the target within tolerance. Collapsing it discards that candidate. The fix is `left < right`: the loop stops when `left == right`, preserving the one-element window for the matching check.

**Required behavior (canonical two-pointer form):**
```python
left = 0
running_sum = ZERO
for right in range(n):
    running_sum += items[right].amount
    range_size = right - left + 1
    tolerance = scale * range_size
    while running_sum > target + tolerance and left < right:
        running_sum -= items[left].amount
        left += 1
        range_size = right - left + 1
        tolerance = scale * range_size   # recompute after shrink
    if abs(running_sum - target) <= tolerance:
        return items[left:right + 1]
return None
```

**Why `left < right` and not `left <= right`:** The shrink loop's purpose is to discard items from the left while the sum is too large. When `left == right`, the window is the single item at index `right`; shrinking further would empty the window. The single item may itself match the target within tolerance (the `range_size == 1` case), so it must be tested by the matching condition below the shrink loop, not discarded by the shrink loop.

**Why the tolerance must scale with window size:** When items are FIFO lots whose individual amounts carry rounding error from upstream currency conversion, the cumulative rounding error grows with the number of lots summed. A fixed tolerance is too tight for large windows (rejecting valid 50-lot sums) and too loose for small windows (admitting invalid 2-lot sums). Scaling tolerance by `range_size` keeps the acceptance probability approximately constant across window sizes.

**Performance:** This is O(N) per event (each item enters the window once and leaves at most once). For N events against the same candidate list, pre-sort the candidates once and re-scan per event; the total is O(N * M) worst case but typically much faster because most events fail fast.

**Distinguishing from #107 (per-key deques):** Lesson #107 addresses exact one-to-one matching with non-unique keys. This lesson addresses the FALLBACK phase that runs when no exact match exists: the source event's amount must equal the SUM of a contiguous range of target items. The two phases are complementary: exact match first (cheap, deterministic), contiguous-range fallback second (handles the FIFO-split case where one event's amount is split across N adjacent lots).

**Anti-pattern:** Computing `tolerance = scale * n` once before the for-loop, then using that constant tolerance inside the shrink loop and the matching check. For a 500-item candidate list with `scale = 0.00001`, the constant tolerance is `0.005`. After shrinking to a 3-item window, the correct tolerance is `0.00003`; the stale `0.005` admits sums up to `target + 0.005`, a 166x loosening. A window summing to `target + 0.004` is accepted when it should be rejected, silently removing 3 lots that did not actually correspond to the source event.

**Example:** Task 5 of the 2026-06-14 derivatives-th-label-cg-dedup plan implemented `_find_contiguous_range(candidates, target)` with `_RANGE_TOLERANCE_SCALE = Decimal("0.00001")`. The shrink loop recomputes `range_size` and `tolerance` after every `left += 1`. The shrink bound is `left < right`. The 10,000-lot performance test completes in about 30 ms (well under the 2 s budget); the 500-lot worst case completes in under 1 ms. See the implementation log (local).

**See also:** Lesson #107 (per-key deques for exact match), Lesson #102 (count-matched-items-per-event warning), CLAUDE.md §3 Repository Constraints (no silent drops).

## 109. Re-Read RED Test Assertions Against Revised Design Invariants Before Flipping to GREEN

When an implementation plan is revised between the RED phase (writing the failing test) and the GREEN phase (implementing the fix), the RED test may still assert the pre-revision contract. Flipping it GREEN without re-reading it against the current design invariants lets a stale assertion pass against the wrong implementation, or forces the implement sub-agent to patch the test silently during the GREEN flip without flagging that the contract changed.

**Failure mode:** The RED test was written when Design Invariant N specified "per-lot WARNING logs". A plan revision (r1 → r2) changed the invariant to "per-lot INFO plus one aggregate WARNING". The GREEN implementation follows the new invariant, but the RED test still asserts the old one. The implement sub-agent must either update the test (silently changing what was supposed to be a characterization of correctness) or leave it asserting the wrong contract and watch it fail for the wrong reason.

**Required behavior at GREEN flip:**

1. Before running the GREEN validation command, re-read every RED test that this task is supposed to flip, against the **current** design invariants in the revised plan.
2. If the RED test asserts a contract that the revision changed, update the test to assert the new contract as part of the GREEN flip. Do not leave the stale assertion in place.
3. Call out in the implement log that the RED test was updated at GREEN-flip time, citing the design invariant number and the revision that changed it. This makes the contract change auditable rather than a silent edit.

**Why this matters:** A RED test is supposed to characterize the desired behavior. When the plan is revised, the characterization must be revised too. An implement sub-agent that silently rewrites a RED test to match its GREEN implementation (without citing the revision) destroys the characterization value and hides a contract change from reviewers.

**Distinguishing from #76 (TDD RED-then-GREEN):** Lesson #76 requires creating a failing test before implementing the fix. This lesson addresses the case where the plan was revised AFTER the RED test was written, so the RED test's assertions may no longer match the revised contract. Lesson #76 is about process ordering; this lesson is about keeping the test characterization in sync with a revised spec.

**Example:** Task 1 of the 2026-06-14 derivatives-th-label-cg-dedup plan wrote `TestByBitCase3Trace#test_removal_logged` as a RED test asserting 3 per-lot WARNING logs. The r2 revision introduced Design Invariant 15 requiring per-lot INFO plus a single aggregate WARNING. Task 6's GREEN flip had to update the test's `caplog.at_level` from WARNING to INFO and change the assertion from "3 WARNINGs" to "3 INFOs + 1 WARNING mentioning `removed` and `lots`". The implement log records the contract change against Design Invariant 15. See the implementation log (local).

**See also:** Lesson #76 (TDD RED-then-GREEN ordering), Lesson #100 (verify plan-time claims before writing tasks, the plan-authoring counterpart), Lesson #120 (reconcile plan pseudocode against tests and design invariants before GREEN).

## 110. Re-Run Phase-N Feasibility Scans on the Post-Phase-(N-1) State, Not the Original Input Set

When a multi-phase matching (or removal) algorithm runs phase 1 (e.g., exact-match consumption) before phase 2 (e.g., contiguous-range fallback), any brute-force feasibility scan the plan author runs to predict phase-2 behavior MUST run against the POST-phase-1 input set, not the original full input set. Phase 1 consumes target items, which changes both the candidate count and the candidate sum seen by phase 2. A "no contiguous range sums to X" claim derived from the full set does not survive phase-1 consumption and will be falsified by the implementation.

**Why this matters:** Plan authors routinely run brute-force scans (in a REPL, a gist, or a throwaway script) to justify design claims like "phase 2 will only remove 2 lots, not 108." Those scans are cheap and persuasive, which is exactly why they are dangerous when run against the wrong input set. The scan produces a true statement about the full set ("no subset sums to X") that is silently false about the post-phase-1 state. The plan ships with a prediction the implementation cannot match, forcing a revision cycle (re-trace, re-write test expectations, re-explain the divergence to reviewers).

**Failure mode:** Phase 1 removes N target items via exact match. The remaining M items have a sum that is within tolerance of a phase-2 target (often BECAUSE the removed items carried the excess). Phase 2's contiguous-range scan then matches the ENTIRE remaining M-item set as a single contiguous range. The plan, having scanned the full N+M set and found no match, predicted phase 2 would remove 0 or 2 items; the implementation removes all M.

**Required behavior:**
1. Before writing a plan claim that depends on phase-N behavior ("phase 2 matches k items"), identify every prior phase that consumes or filters the input set.
2. Replay the prior phases' consumption on the actual fixture (or a representative sample) to derive the post-phase-(N-1) input set.
3. Run the feasibility scan against THAT set, not the original full set.
4. If the prior phases' consumption is data-dependent (depends on which items match exactly), run the scan for each plausible consumption branch and record which branch the prediction assumes.
5. When the consumption is too complex to replay by hand, instrument the actual implementation (a debug print of the post-phase-1 candidate list) and run the scan against that output. Do not substitute a hand-wave for the replay.

**General form:** Whenever a multi-stage algorithm's stage N feasibility depends on the output of stage N-1 (consumption, filtering, transformation), predictions about stage N must be grounded in the stage-(N-1) output, not the stage-1 input. This holds for matchers, aggregators, pipeline stages, and any sequential transformation where an early stage alters the input seen by a later stage.

**Distinguishing from #100 (verify plan-time claims against source):** Lesson #100 verifies STATIC facts about production code (field semantics, line numbers, return shapes). This lesson verifies DYNAMIC algorithm state transitions: the input set a later phase sees after an earlier phase has consumed items. A plan can have perfectly accurate code citations and still produce a wrong phase-N prediction because the feasibility scan ran against the wrong input set.

**Distinguishing from #108 (sliding-window tolerance recomputation):** Lesson #108 addresses correctness of the sliding-window mechanic itself (recompute tolerance per shrink step). This lesson addresses correctness of the PLAN-TIME prediction of what the sliding window will match: the candidate list fed to the window is not the original full list when an earlier phase has consumed items.

**Anti-pattern:** A plan author runs `brute_force_sum_scan(full_lot_list, target=<REALIZED_GAIN_USDT>)` in a REPL, observes "no contiguous range sums to <REALIZED_GAIN_USDT>," and writes in the plan: "phase 2 matches at most 2 lots." The implementation runs phase 1 first, which removes the Futures fee lot (<FUTURES_FEE_USDT>), leaving 107 lots whose sum is <REALIZED_GAIN_USDT> within tolerance. Phase 2 matches all 107. The implementer must either patch the test to assert 109 removals (silently contradicting the plan) or flag the divergence and request a revision.

**Example:** Task 7 of the 2026-06-14 derivatives-th-label-cg-dedup plan updated Case 2 (2025-01-13 USDT ByBit) expectations. The plan predicted 2 CG lots removed (1 Funding fee exact + 1 Futures fee exact) and ~106 remaining. The actual pipeline removed all 109 lots: phase 1 removed the 2 exact-match lots (Funding fee <FUNDING_FEE_USDT> + Futures fee <FUTURES_FEE_USDT>), then phase 2's contiguous-range scan ran against the remaining 107 lots whose sum (<TOTAL_USDT> - <FUTURES_FEE_USDT> = <REALIZED_GAIN_USDT>) was within tolerance of the Realized gain TH event (<REALIZED_GAIN_USDT>). Phase 2 matched the entire 107-lot set as a single contiguous range. The plan's brute-force scan had correctly found "no contiguous range in the FULL 108-lot set sums to <REALIZED_GAIN_USDT>," but that scan did not account for phase-1 removing the Futures fee lot first. The test asserts the ACTUAL output (109 removed, 0 remaining) with a docstring explaining the divergence. See the implementation log (local).

**See also:** Lesson #100 (verify plan-time claims about production code), Lesson #108 (sliding-window tolerance recomputation), Lesson #109 (re-read RED tests against revised invariants), CLAUDE.md §4 Agent Workflow Rules.

## 111. Grep Across ALL Test Files for Stale Assertions When a Task Changes Data Flow Semantics

When a task changes data flow semantics (adds a filter that removes items, adds a dedup step, changes a transformation output, splits one pipeline into two), assertions on the affected data may exist in multiple test files at different test tiers (unit, integration, e2e). Each task's "update affected tests" scope must include a grep across ALL test files for assertions that reference the changed data, not just the tests the task author listed as in-scope. A stale assertion in a sibling test file survives a focused update of the task's listed files and only surfaces during full regression, by which point the implement sub-agent has already moved on, forcing a cleanup commit.

**Why this happens:** A feature is initially implemented with tests in both the unit tier (testing the integration point with real fixtures) and the e2e tier (testing the final Excel output). When a follow-on plan changes the data flow, the plan author typically lists only the tests they remember writing or the tests in the file they are editing. The sibling test in a different tier that also references the same data is forgotten. The focused test run passes because it runs only the listed files; the failure only appears when the full `uv run pytest` is run at the end of the plan, often by a later validation task rather than the task that introduced the change.

**Required behavior:**
1. Before marking a task that changes data flow as complete, identify the identity tuple of the affected data (e.g., `(date, asset, platform)` for a capital-gains entry, or `(field_name, expected_value)` for a transformation output).
2. Grep across the ENTIRE test tree (`tests/`) for assertions referencing that identity: `grep -rn "<date>.*<asset>.*<platform>" tests/`, `grep -rn "<field_name>" tests/`, or `grep -rn "<expected_value>" tests/`.
3. For each hit, re-read the assertion against the new contract. If the assertion encodes the old behavior, update it as part of THIS task; do not defer to a later validation task.
4. When a plan describes "update test expectations for the new behavior," the plan's task list should explicitly include "grep all test files for assertions on the affected identity tuple and update stale ones" as a sub-step, not just "update tests/test_X.py".

**Distinguishing from #109 (re-read RED tests against revised invariants):** Lesson #109 addresses stale assertions in the RED test that THIS task is supposed to flip; the test is in scope but its assertions were written against a superseded invariant. This lesson addresses stale assertions in tests OUTSIDE this task's listed scope; the tests are in sibling files the task author forgot to grep. The failure mode for #109 is caught at GREEN-flip time (the implement sub-agent sees the test fail and patches it); the failure mode here is caught only at full-regression time (the focused run never executed the sibling test).

**Distinguishing from #92 (fix in-scope findings in the same branch):** Lesson #92 addresses refactoring findings in files the task touched. This lesson addresses test-staleness that crosses file boundaries: the task touched `derivatives_dedup.py` and updated `test_derivatives_dedup.py`, but a stale assertion in `test_crypto_reporting.py::TestPipelineIntegration` (a different file the task never opened) encodes the old contract.

**Anti-pattern:** A task implements a dedup step that removes a CG lot for `(2025-01-12, USDT, ByBit)` from `capital_entries`. The task updates the e2e test that asserts the lot is absent from the Excel output (`test_no_fee_disposal_lot_in_capital_entries`) but does not grep `tests/` for other references. A unit test in a different file (`TestPipelineIntegration::test_capital_entries_excludes_derivatives_when_flag_on`) still asserts the OLD contract (`len(case1_matches) == 1` with `gain == -<FEE_GAIN_EUR> EUR`). The focused test run passes; the full regression at task 9 fails. The cleanup commit then has to explain why a stale test survived three task boundaries.

**Example:** Task 7 of the 2026-06-14 derivatives-th-label-cg-dedup plan updated Case 1 and Case 2 e2e expectations in `tests/end_to_end/test_crypto_derivatives_separation.py`. The plan did not list `tests/unit/application/test_crypto_reporting.py::TestPipelineIntegration::test_capital_entries_excludes_derivatives_when_flag_on`, which had been written in an earlier task (the initial derivatives separation) and still asserted `-<FEE_GAIN_EUR> EUR` for the 2025-01-12 USDT ByBit Futures fee lot. The dedup correctly removed that lot (TH line 205 carries Label="Futures fee"), so the unit test failed at task 9's full regression. A grep for `2025-01-12.*USDT.*ByBit` or `case1_matches` across `tests/` at task 7 time would have surfaced the stale assertion and let task 7 update it in the same commit as the e2e expectations. See the implementation log (local).

**See also:** Lesson #92 (fix in-scope refactoring findings in the same branch), Lesson #109 (re-read RED tests against revised invariants), CLAUDE.md §4 Agent Workflow Rules.

## 112. Test Method Names Must Reflect Their Actual Coverage Scope

When a test method's name implies coverage of N pathways (e.g., `test_*_propagate_timestamp` for a function with 5 emitter sites, or `test_all_branches_handle_*` for a 4-branch conditional) but the body exercises only 1, reviewers reading the test list will assume the implied coverage exists. A later refactor that breaks an unexercised pathway will pass the existing test suite because the suite never tested that pathway; the misleading name delayed the discovery.

**Why this matters:** Test method names are a discovery surface during code review and refactor risk-assessment. A reviewer deciding whether a change is safe to merge will scan test names to estimate coverage; a name that overstates coverage produces a false-confidence green light. The test passes for the wrong reason, not because the contract holds across all pathways, but because only one pathway was ever asserted.

**Required behavior:**
1. When writing a test for a function with multiple dispatch pathways (multiple emitter sites, multiple branches, multiple subclasses, multiple strategies), either:
   - Name the test after the SPECIFIC pathway it covers (e.g., `test_cross_asset_exchange_emitter_propagates_timestamp`), OR
   - Parameterize the test across ALL pathways and keep the general name (e.g., `@pytest.mark.parametrize("emitter", ALL_EMITTERS)`).
2. Never use a general name like `test_emitters_propagate_timestamp` for a test that covers only one emitter, hoping to add the rest later. The hope rarely survives the next refactor.
3. When inheriting or reviewing a test with a general name and a narrow body, either rename the test to reflect its scope or expand the body (or parameterize) to cover what the name claims. Do not leave the gap.

**General form:** A test's name is a contract with future readers about what the test verifies. If the name claims a category, the body must verify the category. If the body verifies a single instance, the name must name the instance.

**Distinguishing from #91 (helper functions need direct unit test coverage):** Lesson #91 requires direct unit tests for extracted helpers (versus only indirect integration coverage). This lesson addresses the narrower problem of a test that DOES exist but whose name overstates the scope of what it verifies. Lesson #91 is "the test does not exist at the right level"; this lesson is "the test exists but its name lies about what it covers."

**Distinguishing from #111 (grep all test files for stale assertions):** Lesson #111 addresses stale assertions across multiple test files when data flow changes. This lesson addresses the gap between a test's name and its body WITHIN a single test file, regardless of whether data flow changed.

**Anti-pattern:** A function `_emit_cross_asset_exchange` is one of 9 emitter sites that should all propagate `disposal_timestamp`. The implementer writes `test_fifo_emitters_propagate_timestamp` (plural noun suggesting all emitters) that constructs a single cross-asset exchange context and asserts the timestamp is set. The other 8 emitters are never exercised. A later change to `_emit_intra_asset_transfer` drops the timestamp assignment; the test suite stays green because that emitter was never covered. The misleading name hid the gap from the reviewer who approved the change.

**Example:** The 2026-06-14 derivatives-th-label-cg-dedup plan's Task 3 added `disposal_timestamp` propagation to 15 constructor sites across `parsing.py`, `_emitters.py`, `matching.py`, `fifo_helpers.py`, and `crypto_reporting.py`. The unit test `test_fifo_emitters_propagate_timestamp` in `tests/unit/application/test_crypto_fifo_emitters.py` constructs one cross-asset exchange AcquisitionContext and ConsumptionContext and asserts the timestamp is forwarded. The other 8 emitter sites (cross-asset transfer, fee, intra-asset exchange, intra-asset transfer, etc.) are not parameterized into the test. A later refactor that drops the timestamp from `_emit_fee_acquisition` would pass the test suite. See the implementation log (local) Finding 3.

**See also:** Lesson #91 (helpers need direct unit tests), Lesson #111 (grep all test files for stale assertions), CLAUDE.md §4 Agent Workflow Rules.

## 113. Internal Placeholder Sentinels From Resolution Functions Must Not Leak to User-Facing Output Fields

When a resolution/lookup function (operator-origin resolver, ISIN resolver, country resolver) returns an internal placeholder sentinel as one of its fields (e.g., `operator_entity="UNKNOWN_OPERATOR_REVIEW_REQUIRED"`, indicating "data could not be resolved automatically"), callers must NOT propagate that sentinel value directly into user-facing output fields (Excel cells, report columns, API responses). The sentinel is a programmatic "data missing, review required" marker intended for internal branching and review-flag logic, not for display. Propagating it verbatim produces output like `UNKNOWN_OPERATOR_REVIEW_REQUIRED` in a taxpayer-facing Excel cell, confusing, unactionable, and indistinguishable from a real operator name to a non-technical reviewer.

**Why this matters:** User-facing output must use self-explanatory terminology (see `coding_guidelines.md` #6). Internal sentinels are terse programmatic identifiers designed for code-side `if` checks, not for humans. The two concerns, "signal missing data to the code" and "display something useful to the human", require different values at the same call site. Reusing the internal sentinel for display collapses them into one bad value.

**Distinguishing from user-visible sentinels (`MISSING_ISIN_REQUIRES_ATTENTION`, `UNKNOWN_COUNTRY`):** Those sentinels ARE designed for user display; their terse, ALL_CAPS form is intentional and the project convention is that they should appear in Excel cells with highlighting to draw the reviewer's attention. This lesson addresses the opposite case: a sentinel like `UNKNOWN_OPERATOR_REVIEW_REQUIRED` whose name reads as an instruction to the developer ("review required"), not as a value the user should see. When in doubt, check whether the sentinel's name reads as a value (OK to display) or as an instruction/status (must NOT display).

**Required behavior:**
1. When consuming a resolution function's result, identify which fields may carry an internal placeholder (typically: the field the resolver returns when it cannot resolve, often paired with `review_required=True`).
2. For user-facing output, substitute the original raw input value (e.g., `row.wallet`, the raw wallet name the user provided) rather than the resolver's placeholder. The raw input is what the user entered and what they will recognize when reviewing.
3. Keep the `review_required` flag and a specific actionable `review_reason` (citing the resolver function name) so the missing data is still surfaced for review, just not via leaking the sentinel into a data cell.
4. Test the unmapped/unknown case explicitly: assert the user-facing field equals the raw input, NOT the internal sentinel.

**General form:** Any time a downstream field is populated from a resolver/lookup result, audit whether that result carries an internal placeholder for the unresolved case. If it does, the user-facing output must use the original input value, not the placeholder. The placeholder is for code logic; the raw input is for display.

**Example:** Task 2 of the 2026-06-15 derivatives-pnl-columns plan populated `operator_entity` on `DerivativesPnLEntry` rows built from OGR data. `resolve_operator_origin()` returns `OperatorOrigin(operator_entity="UNKNOWN_OPERATOR_REVIEW_REQUIRED", review_required=True)` for unmapped platforms. Using `operator_origin.operator_entity` directly would leak `UNKNOWN_OPERATOR_REVIEW_REQUIRED` into the Excel cell. The implementation uses `operator_entity=row.wallet` (the raw wallet name the user provided) and synthesizes an actionable `review_reason` citing `resolve_operator_origin()` instead. See the implementation log (local).

**See also:** `coding_guidelines.md` #6 (user-facing labels use self-explanatory terminology), CRG-016 (review flag conflation), CLAUDE.md "Data Handling" (visible sentinels vs internal placeholders).

## 114. Default-Empty Excel Cell Assertions Must Accept Both None and Empty String

When a test asserts that an Excel cell is "empty by default" (e.g., an optional field like `notes` that was never set on the entry, written via `safe_cell_value(entry.notes)` where `entry.notes` resolves to `""`), the read-back value from openpyxl may be EITHER `None` OR `""`. openpyxl normalizes empty-string writes to `None` in some code paths and preserves the empty string in others, depending on whether the cell had prior content, the write went through `Worksheet.cell()` vs direct attribute assignment, and the version of openpyxl in use.

**Why this matters:** A brittle assertion like `assert cell.value == ""` or `assert cell.value is None` will pass on one openpyxl version and fail on another, or pass for one field and fail for its sibling field written the same way. The test then appears flaky and gets disabled, or the implementer papers over the failure with a hack that masks a real bug.

**Required behavior:**
1. For default-empty cell assertions, accept BOTH representations: `assert cell.value in (None, "")` (or `assert cell.value is None or cell.value == ""`).
2. Do NOT assert a single value unless the production code under test GUARANTEES that value (e.g., the field is always initialized to a non-empty sentinel).
3. When the production write uses `safe_cell_value(x)` where `x` may be `None`, the empty-state assertion must accept `None`, `""`, or both; never assert one exclusively.

**Distinguishing from lesson at section "When adding columns that can be blank/None" (around line 957):** That rule says to ADD a dedicated test for the blank/None state and verify the cells are `None` (not empty string, not zero, not default value); its concern is detecting leftover data from prior rows. This lesson #114 addresses the opposite problem: when the expected state IS empty and the write went through `safe_cell_value("")`, the read-back may normalize to `None`. The two rules compose: add a dedicated empty-state test (per the earlier rule), and in that test accept both `None` and `""` (per this lesson #114).

**General form:** Any Excel cell assertion about an empty/default value must account for openpyxl's dual representation of "empty". The set `{None, ""}` is the correct expected-empty set for cells written via `safe_cell_value()`.

**Example:** Task 4 of the 2026-06-15 derivatives-pnl-columns plan added `test_row_writes_notes_default_empty` for the new `Notes` column (column 12) on the Derivatives P&L sheet. The entry was constructed without `notes`, so `entry.notes` defaulted to `""`. The production write is `worksheet.cell(row, 12, safe_cell_value(entry.notes))`. The test asserts `cell.value in (None, "")` because openpyxl may read back either value. A brittle `== ""` assertion would fail when openpyxl normalizes the empty string to `None`. See the implementation log (local) Decision 3.

**See also:** Lesson around line 957 (add dedicated blank/None tests), `coding_guidelines.md` #4 (type-safe sentinels for absent optional fields), CLAUDE.md "Data Handling".

## 115. Reuse the Production Validator When a Test Asserts Against a Domain-Validity Predicate

When a test asserts that an output value satisfies a domain-validity predicate (a fixed enumeration of valid codes, a country list, a regex pattern, or any "is this value one of the allowed values?" check) where the valid set is defined in production code, the test MUST import and reuse the production validator rather than duplicate the valid-set list inline in the test.

**Why this matters:** A duplicated valid-set list in the test silently desyncs from production when the production list changes. Example failure mode: production adds a new country code to its Tabela X list (say, after a CIRS amendment), the test still asserts against the old list, and a row carrying the new valid code fails the test even though the pipeline correctly emits it. The test then appears to "discover" a regression that is actually a stale test, and a maintainer may "fix" the pipeline to match the stale test.

**Pattern to avoid:**
```python
VALID_TABELA_X_CODES = {"PT", "US", "AE", "DE", "FR", ...}  # stale copy
assert country in VALID_TABELA_X_CODES or country == "UNKNOWN"
```

**Correct pattern: reuse the production validator:**
```python
from tax_reporting.application.crypto.classification import _is_valid_tabela_x_country
assert country == "UNKNOWN" or _is_valid_tabela_x_country(country)
```

**Qualification gate (when to apply this rule):**
- The predicate is defined in production code (a function, a module-level constant, or a dataclass field).
- The valid set is non-trivial (a list of dozens of country codes, a regex, an enum) such that manual duplication is error-prone.
- The test's intent is to verify the value is "valid per the domain", NOT to verify the production list itself contains a specific entry (in which case the test legitimately pins specific entries).

**When NOT to apply:** Tests that pin the production list's membership ("Tabela X must include Portugal") should NOT delegate to the production validator; that would be tautological. Those tests hold their own inline list as a contract anchor.

**Distinguishing from #96 (Structural Identification for Excel Output Tests):** Lesson #96 is about identifying which cells to inspect via structural properties (column population, font) rather than hardcoded value exclusions; it concerns test data selection, not validity predicates. This lesson #115 concerns the validity check applied to the values once selected: even when a test correctly identifies rows structurally, it may still duplicate a domain list to validate the cell's value, which is the drift risk this rule addresses. The two compose: identify rows structurally (per #96), then validate values by reusing the production predicate (per #115).

**General form:** Whenever the test could be written as `value in SOME_SET_DEFINED_IN_PRODUCTION` or `value matches PRODUCTION_REGEX`, replace the inline duplicate with an import of the production function/constant. The test asserts the contract ("value is valid per the domain"), and the production code is the single source of truth for what "valid" means.

**Example:** Task 5 of the 2026-06-15 derivatives-pnl-columns plan added `test_derivatives_rows_operator_country_is_valid_or_unknown`, which asserts every derivatives row's `operator_country` is either a valid Tabela X country code or the literal `"UNKNOWN"` sentinel. The test imports `_is_valid_tabela_x_country` from `tax_reporting.application.crypto.classification`, the same validator the pipeline uses to validate reportable country codes, rather than re-listing the ISO 3166-1 alpha-2 codes inline. A future CIRS amendment that adds a country to the production list propagates to the test automatically. See the implementation log (local) Decision 3.

**See also:** Lesson #96 (structural identification for test data selection), CLAUDE.md "Code Quality" (no duplicated constants), `coding_guidelines.md` (single source of truth for domain predicates).

## 116. Check Prior Same-Session Commits Before Reporting a Verification-Time Scope Violation

When a verification-only task (e.g., a regression sweep, a "diff scope" check, a Phase 2 final validation) asserts that the cumulative diff should contain a specific file but `git diff <base>..HEAD -- <file>` shows the file is NOT in the diff, first check whether a prior same-session commit already applied the planned change to that file before reporting a scope violation.

**Why this matters:** Execute-plan sessions commit after each completed task. When a plan lists a source file as expected-modified and an earlier task's commit already included the edit (because the edit was naturally bundled with that task's primary change), the file will NOT appear in a later task's incremental diff even though the work was done. Reporting this as a "scope violation" or "missing change" is a false positive; the change exists in the cumulative history, just not in the latest task's incremental slice.

**Required behavior:**
1. When a verification task's "expected files in diff" list does not match `git diff --name-only <base>..HEAD`, run `git log --oneline <base>..HEAD -- <missing-file>` to check whether an earlier commit in the session already touched it.
2. If yes, confirm the change matches the plan's intent by reading the file at HEAD (`git show HEAD:<file>` or Read tool), then mark the verification item as satisfied; the work landed earlier, just not in the most recent task's commit.
3. Only report a scope violation when the file is absent from the entire `<base>..HEAD` range AND the planned change is genuinely missing from the working tree.

**Distinguishing from #100 (plan-time claims):** Lesson #100 covers verifying claims about production code at plan-authoring time. This lesson covers verifying scope at verification/commit time, when the diff inspection happens after multiple commits. The trigger is a mismatch between an expected-files list and an observed cumulative diff, not a plan-authoring claim.

**General form:** Verification tasks that inspect `git diff <base>..HEAD` must interpret "file X is missing from the diff" as "file X was not touched in this session", which requires checking the per-commit history, not just the aggregate diff stat. A file absent from the cumulative diff is genuinely missing; a file absent from the latest task's incremental commit may simply have landed earlier.

**Example:** Task 6 of the 2026-06-15 derivatives-pnl-columns plan listed `docs/domain/crypto_rules.md` as an expected file in the diff scope check. The diff `d2eda71..HEAD` did not show `crypto_rules.md`. Investigation showed the prior same-session commit `6083cf1 docs(crypto): extend PT-C-031 with Anexo G Quadro 13 filing routing for derivatives` had already extended PT-C-031 with the Anexo G Quadro 13 routing the plan depended on, so no further `crypto_rules.md` edit was required by this plan. The verification item was satisfied by the earlier commit, not violated. See the implementation log (local) Decision: crypto_rules.md.

**See also:** Lesson #100 (verify plan-time claims about production code), `execute-plan` skill (Phase 2 final validation), CLAUDE.md §4 Agent Workflow Rules.

## 117. Branch on the Discriminator When Synthesising a Reason for a Multi-Cause Flag

When a downstream consumer observes a boolean flag (e.g., `review_required=True`) that MULTIPLE distinct upstream cases can set, and the consumer synthesises a single human-facing reason/message from that flag, the consumer MUST branch on the discriminator (a sentinel, enum, category field, or secondary attribute) the upstream sets to distinguish which case fired, rather than collapsing all cases into one message.

**Why this matters:** A flag with multiple upstream causes carries no information about WHICH cause fired. Collapsing all causes into one synthesised message produces output that is misleading for the cases that did NOT fire. The reviewer reads "Unknown platform" when the platform IS mapped but the transaction date predates the service window; the reviewer then chases the wrong fix path. The discriminator the upstream sets exists precisely to disambiguate; ignoring it throws away the disambiguation the upstream already paid for.

**Qualification gate (when this rule applies):**
- The observed flag can be set True by two or more distinct upstream code paths (e.g., unknown-platform default path AND temporal-validity failure path both set `review_required=True`).
- The consumer synthesises a message FROM the flag (not from the upstream's own reason field).
- The upstream provides a discriminator (a sentinel value on a sibling field, a distinct enum/category, or a non-empty `review_reason` for at least one case) that lets the consumer tell the cases apart.

**Required behavior:**
1. Before synthesising a message from a multi-cause flag, enumerate the upstream cases that set the flag True.
2. For each case, identify what field/value the upstream uses to signal it (sentinel string, enum variant, presence of a specific `reason` text).
3. Branch on that discriminator in the consumer and emit a case-specific message. Surface the upstream's own `reason` verbatim when it carries specific diagnostic detail (dates, parsed values, identifiers) rather than a generic instruction.
4. Provide a final fallback string only for the theoretical case where `flag=True` with no discriminator and no reason.
5. The RED-phase test must exercise EACH distinct upstream case (not just one) and assert the case-specific message appears while the OTHER case's message does NOT.

**Distinguishing from #113 (sentinel leak into display fields):** Lesson #113 is about the VALUE of a field that reaches the display (an internal placeholder must not appear in a user-facing cell). This lesson #117 is about WHICH MESSAGE a consumer synthesises when the same flag has multiple causes; the value is always user-facing by design (a reason string), but the message content must match the actual cause. #113 says "do not display the sentinel"; #117 says "do not collapse multiple causes into one message; branch on the discriminator".

**General form:** Any time a consumer turns a multi-cause boolean into prose, the prose must be selected per-cause using the discriminator the upstream sets. The boolean tells you THAT review is needed; the discriminator tells you WHY; the WHY is what the reviewer needs to read.

**Example:** Finding #1 (Medium) of the 2026-06-16 derivatives-pnl-columns code review r1 found that `_split_ogr_index` in `src/tax_reporting/application/crypto/ogr_handler.py` synthesised an "Unknown platform" message (with wording like `add this platform to resolve_operator_origin() before filing`) whenever `operator_origin.review_required` was True. But `resolve_operator_origin()` sets `review_required=True` for TWO distinct cases: (a) truly-unknown platform (sets `operator_entity="UNKNOWN_OPERATOR_REVIEW_REQUIRED"`), and (b) temporal-validity failure, a known platform whose `service_start_date` postdates the transaction (keeps the real mapped `operator_entity` and sets a specific `review_reason` mentioning the date and service period). The synthesised message misled reviewers for case (b): the platform IS mapped, but the message told them to add it. The fix branches on the `UNKNOWN_OPERATOR_REVIEW_REQUIRED` sentinel: for the truly-unknown case it synthesises the actionable fix-path message; for the temporal-validity case it surfaces `operator_origin.review_reason` verbatim (which carries the specific date and "service period" wording the reviewer needs). The new RED test `test_derivatives_entry_for_known_platform_outside_service_period_carries_temporal_reason` exercises case (b) explicitly and asserts the temporal reason is present while the "Unknown platform" message is absent. See the derivatives-pnl-columns code review r1 (local) Finding #1 and the implementation log (local).

**See also:** Lesson #113 (internal sentinels must not leak to display fields), Lesson #112 (test names must reflect their coverage scope; the missing temporal-validity test is a #112 instance), CLAUDE.md §1 "Partial or uncertain results must carry an explicit indicator" and "Review flags must include specific actionable explanations, not bare booleans".

## 118. Guard "Take From First Entry" Fields Against Silent Heterogeneity

Lesson #80 documents the "lookup value fields - take from first entry" aggregation strategy, premised on the assumption that all entries in the group share an identical value for the field. That assumption is a design invariant, not a guaranteed runtime property. When the assumption silently fails (e.g., a future code path lets two group members carry different `annex_hint` / `operation_code` / `legal_category` values for the same disposal group), the renderer or aggregator that takes `entries[0]` will silently pick one value and discard the others, with no log or warning to flag the drift. The output looks correct (it has a value) but is wrong (it has the wrong value).

**Required behavior:**
1. Whenever an aggregator, renderer, or detail-line builder takes `entries[0]` (or `first`) for a field that is ASSUMED constant across the group, add a programmatic heterogeneity guard that emits a `logger.warning` when the assumption is violated.
2. The guard should build the set of distinct values (or distinct tuples, for multi-field constants like `(annex_hint, operation_code, legal_category)`) and warn when `len(distinct) > 1`. Include the count, the distinct values, and which row was actually rendered so a future maintainer can audit.
3. Do NOT raise; the first entry's value is still the best available. The warning makes the drift observable so a reviewer can decide whether the assumption needs strengthening or the data needs correcting.
4. Pair the guard with a RED test that constructs a group with heterogeneous values and asserts the warning fires, plus a negative control asserting no warning fires when values agree.

**Qualification gate (when this rule applies):**
- The field is read from `entries[0]` / `first` rather than aggregated (summed, OR-ed, joined).
- The field's correctness depends on all group members sharing the same value (a design invariant, not enforced by upstream).
- A silent violation would produce user-facing output that looks valid but is wrong.

**Distinguishing from #80 (aggregation strategy per field type):** Lesson #80 catalogs WHICH strategy to use per field type ("lookup value → take first"). This lesson #118 catalogs the GUARD that must accompany the "take first" strategy when the "all members share the value" assumption is a design invariant that could silently fail. #80 says "use this strategy"; #118 says "when you use the 'take first' strategy for an assumed-constant field, add a heterogeneity guard".

**General form:** Any time production code reads from the first element of a group for a field whose group-wide constancy is an assumption rather than a guarantee, the assumption must be checked at runtime and a warning emitted on violation. Silent assumption drift is worse than a logged warning because the output looks correct.

**Example:** Finding #1 (Medium) of the 2026-06-16 derivatives-pnl-columns code review r1 found that the derivatives-sheet detail-line renderer took `entries[0].annex_hint`, `entries[0].operation_code`, and `entries[0].legal_category` without verifying the other group members agreed. The current fixture set is homogeneous by construction (every group comes from a single disposal event), so the bug is latent. The fix added a guard in `derivatives_sheet.py` that builds `distinct_constant_tuples = {(e.annex_hint, e.operation_code, e.legal_category) for e in entries}` and emits `logger.warning("Derivatives P&L detail-line fields are heterogeneous ...", ...)` when `len(distinct_constant_tuples) > 1`. The RED tests `test_detail_line_warns_when_entries_disagree_on_constant_fields` and `test_detail_line_no_warning_when_entries_agree_on_constant_fields` exercise both branches. See the derivatives-pnl-columns branch review r1 (local) Finding #1 and the implementation log (local) Medium 1.

**See also:** Lesson #80 (field aggregation strategy per field type), Lesson #117 (branch on discriminator for multi-cause flags), CLAUDE.md §1 "Partial or uncertain results must carry an explicit indicator" and "Data-loss conditions (unmatched items, dropped records) must be logged at warning+".

## 119. Mirror Byte-Identical Aggregation Patterns Across Aggregators in the Same Module

When two aggregation functions in the same module perform the same conceptual operation on different domain types (e.g., `aggregate_capital_entries` and `aggregate_derivatives_entries` both merging per-group narrative text fields), they MUST use byte-identical merge patterns. Diverging patterns (one takes `first.notes`, the other joins unique notes with `"; "`) silently drops data in the diverging aggregator: notes that should have been preserved across group members disappear from the output with no error or warning.

**Why this matters:** Aggregators in the same module are read together by reviewers comparing behavior. A divergence between them is invisible at the diff level (both look like reasonable implementations) but produces inconsistent output for the same kind of operation. The capital-entries aggregator preserves all notes; the derivatives-entries aggregator that takes only `first.notes` discards every other member's notes. The bug surfaces only when a fixture has two group members with distinct notes AND the reviewer notices the discrepancy.

**Required behavior:**
1. When adding a new aggregator that performs an operation already implemented by a sibling aggregator in the same module (merge narrative fields, OR booleans, sum numerics, take-first for lookup values), copy the sibling's pattern byte-for-byte. Do not paraphrase, simplify, or "improve" it.
2. If you cannot copy byte-for-byte because the domain types differ, factor the shared pattern into a helper and call it from both aggregators.
3. The RED test must drive the new aggregator with multiple group members carrying distinct values for the merged field, and assert all values survive (deduped and order-preserved when the pattern dedupes).
4. Add a negative control asserting empty input produces the pattern's empty sentinel (e.g., `""` for the notes-merge pattern).

**Qualification gate (when this rule applies):**
- Two or more functions in the same module perform the same conceptual aggregation (join-and-dedupe, sum, OR, take-first, max).
- The implementations diverge in a way that produces different output for the same input shape.
- A reviewer would reasonably expect the implementations to agree.

**Pattern (notes merge, byte-identical reference):**
```python
merged_notes = "; ".join(dict.fromkeys(e.notes for e in group if e.notes)) or ""
```
The `dict.fromkeys(...)` preserves insertion order while deduping; the `if e.notes` filters empty/None; the `or ""` ensures empty input yields an empty string rather than `None`.

**Distinguishing from #80 (aggregation strategy per field type):** Lesson #80 catalogs WHICH strategy to use per field type ("narrative text fields - join unique values with delimiter and deduplicate"). This lesson #119 says: when that strategy is implemented in two aggregators in the same module, the implementations must agree byte-for-byte. #80 says "use the join-dedupe strategy"; #119 says "use the SAME join-dedupe implementation as the sibling aggregator".

**General form:** Sibling aggregators that perform the same operation must use the same implementation. Diverging implementations silently produce inconsistent output. The fix is byte-identical mirroring or extraction to a shared helper.

**Example:** Finding #2 (Medium) of the 2026-06-16 derivatives-pnl-columns code review r1 found that `aggregate_derivatives_entries` in `src/tax_reporting/application/crypto/aggregation.py` set `notes=first.notes` while the sibling `aggregate_capital_entries` (same module, lines 283-287) used the `"; ".join(dict.fromkeys(...)) or ""` pattern. For a group with two members carrying notes "manual annotation A" and "manual annotation B", the derivatives aggregator silently dropped "manual annotation B". The fix replaced `first.notes` with `merged_notes = "; ".join(dict.fromkeys(e.notes for e in group if e.notes)) or ""` (byte-identical to the capital-entries pattern). The RED tests `test_aggregate_derivatives_merges_notes_across_group_members`, `test_aggregate_derivatives_notes_empty_when_no_member_has_notes`, and `test_aggregate_derivatives_notes_deduped_and_order_preserved` exercise the merge, empty-input, and dedupe+ordering cases. See the derivatives-pnl-columns branch review r1 (local) Finding #2 and the implementation log (local) Medium 2.

**See also:** Lesson #80 (field aggregation strategy per field type), Lesson #77 (handle duplicate keys by summing, not silent overwrite), CLAUDE.md §1 "Data-loss conditions must be logged at warning+, never debug".

## 120. Reconcile Plan Pseudocode Against Plan Tests and Design Invariants Before GREEN

When a plan body contains both executable pseudocode AND RED-test expectations that purport to verify that pseudocode, the author must trace each pseudocode branch against the test inputs and the design invariants BEFORE handing the plan to the implementer. The pseudocode and the tests must agree on every input combination. If they disagree, the implementer will either (a) follow the pseudocode and fail a RED test that encodes the invariant, or (b) silently extend the logic beyond the pseudocode to satisfy the tests, producing a defensible but undocumented deviation.

**Why this matters:** Lesson #100 covers verifying plan-time CLAIMS ABOUT PRODUCTION CODE (field semantics, line numbers, return shapes) by reading the source. This lesson covers verifying the plan's INTERNAL CONSISTENCY (pseudocode vs tests vs invariants) by reading the plan itself. The two failure modes share a symptom (the implementer hits a contradiction) but have different triggers: #100 fires when the author makes a claim about reality; this lesson fires when the author's own deliverable is self-contradictory. A self-consistency trace before GREEN eliminates the "implementer added an undocumented third branch to satisfy the invariant" outcome, which is defensible but obscures the actual rule.

**Required behavior:**
1. Before declaring the plan ready for implementation, build the full decision table from the pseudocode (every branch condition -> every input combination -> expected flag/output).
2. For each RED test, look up its inputs in the decision table and confirm the pseudocode-predicted output matches the test-asserted output. Any mismatch is a plan defect; fix the pseudocode (or the test, or the invariant) before implementation.
3. Pay special attention to backward-compat invariants (e.g., "threshold=0 preserves prior flag-everything behavior"); these are easy to violate with two-branch "guard the new case" logic that inadvertently suppresses the old case.
4. If the implementer reports adding a branch not in the pseudocode to satisfy a test/invariant, treat it as a plan-authoring defect (the pseudocode was incomplete), not just an implementer deviation. Capture the missing branch in the plan's implementation note so the rule is discoverable.

**Anti-pattern:** Writing two-branch pseudocode ("if A then X; if B then Y") when a third input combination (A=false, B=false, threshold=0) must also fire per the backward-compat invariant. The implementer correctly adds a third branch (`A=false AND B=false AND threshold=0 -> fire`) to satisfy the RED test, but the branch is undocumented in the plan body, leaving the rule discoverable only by reading the implementation.

**Example:** The 2026-06-15 zero-basis-review-materiality plan Task 2 specified two-branch pseudocode for `_build_zero_basis_review_reason`:
- tier 3: `cost_eur == 0 AND proceeds_eur > 0 AND proceeds_eur >= min_proceeds`
- tier 4: `proceeds_eur == 0 AND cost_eur > 0`

Design Invariant 4 required "when min_proceeds=0, prior flag-everything behavior is preserved", and a RED test `test_min_proceeds_zero_flags_all_zero_cost` asserted `cost=0, proceeds=0, min_proceeds=0 -> review_required=True`. Neither branch matches that input (tier 3 requires `proceeds_eur > 0`; tier 4 requires `cost_eur > 0`), so the implementer added a third branch (`cost_eur == 0 AND proceeds_eur == 0 AND min_proceeds == 0 -> fire`) to satisfy the invariant. The deviation is correct; the plan pseudocode was simply incomplete. A pre-GREEN decision-table trace would have caught the gap and folded the third branch into the plan body.

**See also:** Lesson #100 (verify plan-time claims about production code), Lesson #109 (re-read RED tests against revised invariants after plan revision), CLAUDE.md §4 Agent Workflow Rules.

## 121. Do Not Run `ruff check --fix` on Modules That Re-Export for Backward Compat

When a module deliberately re-exports symbols (via plain `from X import Y` without `__all__` gating, or via an `__all__` that `ruff` cannot fully see) for backward-compat consumers, including tests that import from the re-export module rather than the canonical source; do not run `ruff check --fix` on the whole module. The unused-import heuristic (`F401`) frequently flags and removes re-exported names, silently breaking downstream imports. Apply targeted manual edits to the import block instead.

**Why this matters:** `ruff check --fix` is the default cleanup command in this repo, and on a normal module it is safe and expected. On a re-export module (typically `application/<feature>_reporting.py` or a package `__init__.py`), the same command silently deletes public API surface that tests rely on. The failure surfaces as `ImportError` during test collection, but only after the agent has already moved on to the next command. Recovery is straightforward (`git checkout`), but the time cost compounds when the agent re-runs the fix to "clean up" the next round.

**Required behavior:**
1. Before running `ruff check --fix` on a module, check whether it re-exports symbols consumed elsewhere. Signals: a long `from X import Y, Z, ...` block at the top of the file where some names are not referenced in the file body; an `__all__` declaration; module docstrings describing "re-exports for backward compat".
2. For re-export modules, prefer targeted manual edits to the import block (add or remove specific names explicitly). Do not run `--fix` on the whole file.
3. If you must run `--fix`, restrict the rule set to exclude `F401` (e.g., `ruff check --fix --select=E,F-minus-F401` is not directly supported; instead run `ruff check --select=<specific-rules>` without `--fix`, review the diagnostics, and apply only the safe ones manually).
4. After any ruff run on a re-export module, run the test suite for that module's consumers before declaring the cleanup complete. `ImportError` at collection is the failure signal.

**Anti-pattern:** Running `uv run ruff check --fix src/tax_reporting/application/crypto_reporting.py` after adding a new import, then discovering the auto-fix removed `OperatorOrigin`, `AggregatedRewardIncomeEntry`, `CapitalGainPeriodStats`, `CryptoCompletePdfSummary`, `LoanActivityEntry`, `_load_popular_crypto_tokens`, `apply_derivatives_dedup`, etc., which tests import from this module. The fix is `git checkout` of the file and a targeted manual edit adding only the new name, but the cycle costs a full ruff+test iteration.

**Example:** The 2026-06-15 zero-basis-review-materiality plan Task 2 implementation added `DEFAULT_ZERO_BASIS_REVIEW_MIN_PROCEEDS` to an import block in `crypto_reporting.py`. An initial `ruff check --fix` run aggressively removed re-exported names that `tests/unit/application/test_crypto_reporting.py` imports from this module. The implementer reverted via `git checkout` and applied only the targeted one-line edit. Lesson #4 already documents that backward-compat re-exports live in such modules; this lesson extends it to "do not auto-fix the import block".

**See also:** Lesson #4 (backward-compat via `__init__.py` re-exports), CLAUDE.md "Code Quality" (Ruff primary linter/formatter).

## 122. Do Not `git stash` for Baseline Comparisons in the docs-branch State

This repo carries a docs/orphan-branch workflow (`docs-branch` skill) and at times a working tree with staged deletions (files marked `D` in the index but still present on disk). In that combined state, using `git stash` to get a transient clean tree for a baseline tool comparison is unsafe: the stash records the staged deletions and the subsequent `git stash pop` did not restore the on-disk content, leaving all affected tracked files missing from the working tree.

**What happened (2026-06-17):** During the zero-basis-review-materiality review-fix session, three `git stash` / `git stash pop` cycles were used to compare `ruff` diagnostics on the edited tree versus the committed baseline. The working tree had 10 tracked files staged as deletions (`D`) but present on disk. The stash cycles dropped all 10 files from the working tree. Recovery was via `git fsck --lost-found` to locate the dangling commit from the last dropped stash, then `git checkout <sha> -- <files>` and `git reset HEAD -- <files>` to unstage. All edits were recovered intact because the stash had captured them before being dropped.

**Required behavior:**
1. For any "compare tool output against the committed baseline" task in this repo, read the committed blob non-destructively: `git show HEAD:<path> | uv run ruff check -` per file. Do NOT stash.
2. If a fully clean checkout is genuinely required, use `git worktree add <tmp> <base>` into a temporary path and remove it afterward. Never `git stash`.
3. Before any `git stash` in this repo, audit `git status` for staged deletions (`D`) and gitignored paths overlapping tracked files; if present, do not stash.

**Related (shell recovery):** The recovery command `git checkout <sha> -- $FILES` failed under zsh because zsh does not word-split unquoted variables (the whole string was treated as one pathspec, "pathspec did not match"). Multi-path git operations must use a quoted array: `files=(...); git checkout <sha> -- "${files[@]}"`.

**General form:** See shared `agent_workflow_guidelines.md` #55 (Non-Destructive Baseline Comparisons). The repo-specific aggravator is the docs-branch orphan-branch workflow combined with staged deletions, which makes the stash/pop failure mode both more likely and more damaging here than in a plain repo.

**See also:** `docs-branch` skill, shared `agent_workflow_guidelines.md` #55, CLAUDE.md/AGENTS.md git-safety bullets.

## 123. Decision-Point Doc Prose Enumerations Must Match Implemented Code Branches

When a decision-point record (or any spec doc) describes a rule as an enumerated list, "N-tier rule", "N-step", or cases (1)-(N), every enumerated item must map to a code branch and every code branch must appear in the enumeration. Count mismatches and missing cases survive code review because each individual bullet reads plausibly in isolation; only a branch-by-branch cross-check catches the drift.

**What happened (2026-06-17):** `DP-013` in `docs/tax/decision_points/2025.md` described the zero-basis review gate as a "Three-tier rule" and stated `cost=0 AND proceeds=0` "never flags" unconditionally. But `_build_zero_basis_review_reason` in `src/tax_reporting/application/crypto/fifo_helpers.py` implements four flagging branches, including a `cost=0 AND proceeds < 0` always-flag tier (independent of the threshold), and flags the zero-zero case when the threshold is 0. The fourth tier and the escape-hatch qualifier were both absent from the doc. The omission was found by the documentation review sub-agent, not by the implementer, the plan, or the earlier review rounds.

**Required behavior:**
1. When adding or changing a conditional branch in a rule that a decision-point doc enumerates, update the doc's enumeration (both the count and the cases) in the same change.
2. When reviewing such a change, cross-check each doc bullet against a code branch and each code branch against a doc bullet. Do not trust a "three-tier"/"four-tier" heading or a per-bullet read; count the branches.
3. Apply the same check to test class docstrings that summarize a gated rule (the `TestBuildZeroBasisReviewReason` summary had the same stale "three-tier" wording).

**Why this is distinct from #68:** #68 covers field/flag sync (a TOML boolean needs a dataclass field). This lesson covers prose-enumeration accuracy (the `.md` rule description must list every implemented branch). Both can hold simultaneously: the `.md` and `.toml` sidecars were in sync with the dataclass, yet the `.md` prose was still wrong about the branch count.

**See also:** CLAUDE.md/AGENTS.md decision_points rule (`development_lessons.md` #68), `docs/tax/decision_points/2025.md` DP-013.
