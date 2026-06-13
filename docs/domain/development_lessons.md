# Development Lessons — Common Issues and Prevention Strategies

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
- Never use `Path(__file__).parent.parent` in tests — breaks when files move.
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
- The crypto sheet auto-width block has a missing `default=0` in `max()` that raises `ValueError` on empty columns — always provide `default=0` when calling `max()` on a generator.

## 16. Test Real Behavior, Not Implementation Details
- Verify that a feature works end-to-end, not just that it returns a certain value.
- Use realistic test data; check that integrated components produce correct outputs.

## 17. Test CSV Data Construction — Column Alignment

See `~/Projects/.ai-playbook/python_guidelines.md` #1 for full prevention rules.
Repo context: Koinly `_TH_HEADER` has 20 columns; hand-counting commas is the biggest source of wasted debug iterations.

## 15. Post-Extraction Cleanup

See `~/Projects/.ai-playbook/python_guidelines.md` #2 for full cleanup procedure.
Repo context: past extractions (crypto_reporting.py → token_origin.py + koinly_parser.py) left unused imports and dead code.

## 16. Aggregation Logic — Test Both Directions

See `~/Projects/.ai-playbook/agent_workflow_guidelines.md` #1.
Repo context: LP liquidity operations — fixing "in" direction broke "out" because liquidity out produces multiple outputs from one input.

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

When adding a computed field to a data class used in integration tests, update ALL construction sites to compute the field from actual test data—not from a zero-valued or empty placeholder. Using `CryptoCapitalGainStats.from_entries([])` while `capital_entries` has real data produces inconsistent output (statistics section shows all zeros next to non-zero capital gains). Search for all construction sites with `grep -n "DataClass("` before committing; each site must derive the new field from its own test data.

## 26. Atomic File Replacement — No Pre-Deletion

Never call `safe_remove_file(target)` before `temp_path.replace(target)`. On POSIX, `Path.replace()` atomically replaces the target file. The "remove then replace" sequence breaks atomicity: if `replace()` fails after the removal, the old report is permanently lost and the new file is stranded in `.tmp`. Correct pattern:

```python
# ✅ CORRECT — atomic on POSIX
workbook.save(temp_path)
temp_path.replace(target)  # replaces atomically; no pre-deletion needed

# ❌ WRONG — data loss window between these two lines
safe_remove_file(target)
temp_path.replace(target)
```

## 27. Default Value Assignment Before Derived Computation

Always apply defaults to source variables before computing derived values from them. Anti-pattern:

```python
# ❌ WRONG — log_file computed from None even when output_dir has a default
log_file = output_dir / "report.log" if output_dir else None
output_dir = output_dir or DEFAULT_OUTPUT_DIR

# ✅ CORRECT — apply default first, then compute derived values
output_dir = output_dir or DEFAULT_OUTPUT_DIR
log_file = output_dir / "report.log"
```

Any variable that depends on another must be computed after all defaults are applied to its source.

## 28. Don't Use `_private` Constants Across Module Boundaries

Constants prefixed with `_` are module-private by convention. When a constant is needed in another module (e.g., `crypto_reporting.py` needs `_DEFAULT_ZERO_BASIS_REVIEW_THRESHOLD` from `config.py`), rename it to a public name first. Importing private names across modules violates the API boundary and creates hidden coupling. Apply the same rule that lesson #5 states for tests.

## 29. AT Guidance May Cite Pre-Amendment Paragraph Numbers

See `docs/project-guidelines.md` #3 for the full rule.
Concrete instance: AT folheto 2026-01-12 (published after Lei n.º 31/2024) still cited CIRS art. 43 as "(n.º 6)(g)" and "(n.º 7)" — the old numbers before the June 2024 amendment renumbered them to n.8(g) and n.9 respectively. The stale numbers had silently propagated into `sources.md` and `platform-divergences.md`. The discrepancy was only caught by cross-checking the folheto against the consolidated CIRS PDF (which shows inline annotations like `(Anterior n.º 7 - Lei n.º 31/2024)`).

Prevention: whenever consulting AT guidance that cites a CIRS paragraph number, search for that legal text in the consolidated CIRS PDF and confirm the current paragraph number before recording citations.

---

## 33. Plan Edge Case Behavior Must Be Traced to Correctness Outcome

When writing a plan's Gist & Examples section, trace every described "edge case" or "behavior change" outcome to its user-facing result and verify it satisfies the project's correctness requirements — not just that it differs from the previous behavior.

A common failure mode: comparing the new behavior to the old one ("better than X") without verifying the new behavior is itself correct. Example from this project: "TH absent → `frozenset()` → contaminated Koinly CG passes through" was initially described as an improvement over "TH absent → CG silently dropped". Both behaviors produce wrong tax figures. The correct behavior is to raise `FileProcessingError` immediately — the improvement is the explicit failure, not acceptance of contaminated data.

**Test:** For every edge case in a plan, ask "what does the user see in the output?" and verify that output is either correct, or flagged as requiring review with a specific reason. Contaminated financial data presented without a flag is never acceptable.

**Cross-check:** Verify that described edge case behavior is consistent with existing `CLAUDE.md` constraints (e.g. "Optional crypto ingestion must be non-blocking" does not mean wrong data should silently substitute for missing correct data).

---

## 30. Verify Warning/Guard Path Reachability Before Writing Tests

Before writing a test for an existing warning, guard, or defensive code path, verify that the path can actually be triggered with current production code. Trace every condition that must be true simultaneously for the code to reach that branch.

If the path is unreachable via real data (e.g., a placeholder mechanism always fires before the guard condition can be met), the test must either: (a) use a mock/patch to inject the edge case directly, or (b) first amend the implementation to make the path reachable.

Claiming "implementation is already complete" for an untested path without first proving it is reachable leads to tests that can never go RED → the TDD cycle is broken and the coverage is false.

## 31. Read Full Dataclass Definition Before Describing Fields in a Plan

When a plan task describes the fields of a dataclass (e.g., listing fields to be moved or created), always read the actual class definition in source code to obtain the complete, current field list — including fields with default values that are easy to miss.

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
Repo context: `_DECISION_POINTS_DIR = _REPO_ROOT / "docs/tax/decision_points"` in `config.py` is resolved at import time. Tests in `TestLoadTaxJurisdictionConfig` that called `_load_tax_jurisdiction_config()` without patching this constant silently read the real `2025.toml` from the working tree. They passed because the real file existed and had PT=True — any rename, move, or fiscal-year change would cause a cryptic `FileNotFoundError` rather than a meaningful test failure.
Fix: monkeypatch `_DECISION_POINTS_DIR` to a `tmp_path`-based directory with a minimal TOML fixture, identical to the pattern in `TestLoadDecisionPointsFlags`.

## 38. Decision Points TOML Missing Must Raise `ConfigurationError`, Not Bare `FileNotFoundError`

`_load_decision_points_flags()` must convert `FileNotFoundError` (missing TOML for the configured fiscal year) to `ConfigurationError` before it reaches `main.py`. The `main.py` exception handler has a separate `(FileNotFoundError, OSError)` branch for a missing `config.ini`, which logs "Config file not found; crypto pipeline will run without jurisdiction filters" and continues. If the TOML-not-found error reaches that branch, the pipeline silently proceeds with `exclude_loan_repayment_gains=False` — loan repayment disposals are incorrectly included in capital gains with no error raised.

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

When a defensive branch fires because a row cannot be fully processed (e.g. "both sides loan-affected"), always append the untracked item to `parse_failures_by_asset` — do not rely on a `logger.warning` alone. A logged warning is invisible to the workbook consumer; only items recorded in the failure-tracking structure surface as `review_required` flags in the output.

Example: in `_classify_th_row`, when both the sent and received currencies are loan-affected, the non-principal side was silently ignored. Fix: `parse_failures_by_asset.setdefault(untracked_currency, []).append(row_index)` in all four affected branches (sell, crypto_withdrawal, buy, crypto_deposit).

General principle: "Unmatched items must never be silently discarded" (see CLAUDE.md §1) applies to defensive-path items too — logging is necessary but insufficient when a failure-tracking collection exists.

## 41. Extracted Helpers Need Direct Unit Tests for Key Invariants

When refactoring extracts a private helper from a large orchestrator, add direct unit tests covering the key behavioral invariants (exact-match, partial consume, exhaustion, empty input, non-taxable path). Relying only on orchestrator-level coverage means a future regression in the helper requires tracing through the orchestrator before the failure is localized.

Example: extracting `_consume_against_pool_inplace` from the FIFO orchestrator prompted adding six focused tests in `TestConsumeAgainstPoolInplace`, reducing the blast-radius of future regressions to a single function.

## 42. Failing Tests: Distinguish Stale Expectation from Production Bug

When a test fails, first determine whether the test expectation became stale (design changed) or whether production code regressed. Changing production code to make a stale test pass is the wrong fix — it re-introduces the removed behavior.

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
consumption — both share the same TxHash / `tx_key`. Deduplicating on `tx_key` alone drops
one of them. Correct granularity: `(tx_key, event_type)` for consumptions,
`(tx_key, source_type)` for acquisitions.

Test approach: write a fixture with a single transfer-with-fee row and assert that two
distinct consumption events are produced before assuming single-field dedup is safe.

## 46. Fiscal Year Filter in FIFO Pipeline Must Apply to Disposals Only, Post-FIFO

When filtering FIFO pipeline output to the reporting fiscal year, filter *only disposal /
realization records* — never the acquisition records. Prior-year acquisitions must remain
in the FIFO pool so cost-basis carry-over is correct; filtering them by year would produce
incorrect zero-cost gains for multi-year holds.

Correct position: filter `AssetFifoResult.realizations` after the FIFO engine produces
them, before converting to `CryptoCapitalGainEntry`. Do not pre-filter `acquisitions` or
`consumptions` inputs to the FIFO engine.

## 35. CSV Test Fixture Column Alignment Must Be Verified

When writing CSV test fixture rows for multi-column formats (e.g. Koinly TH rows), verify each value is at the correct column index by counting quoted fields as single units (quoted content containing commas counts as one field).

A misaligned column can make a test pass even with the bug it is designed to detect. Example: a test asserting `cost_basis_eur == 0` when `Sent Cost Basis` is empty will still pass if `Net Value (EUR)` is also empty — because an FMV-fallback bug would also produce 0. Place a non-zero value in `Net Value (EUR)` (col 14) to make the bug detectable.

Use `csv.DictReader([TH_HEADER, row])` or the test helper `_parse_row()` to verify field-to-column mapping before relying on a fixture row as a correctness check.

---

2. `uv run ruff check . --fix` — auto-fix linting
3. `uv run basedpyright src/ tests/` — type checking
4. `uv run ruff check . --select=E501` — line length
5. Confirm all imports have matching dependencies
6. `grep -r "Path(__file__)" tests/` — no fragile test paths
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

When a pipeline run produces different results depending on dynamically-discovered inputs (e.g. which assets are loan-affected, which platforms are active, which years are in scope), expose those inputs in the output report itself — as a dedicated worksheet section, a named range, or a metadata tab — rather than relegating them to log lines or ephemeral sidecar files.

Logs are consumed during a run and discarded; a sibling file adds surface area and may not be opened. The workbook is the primary artifact reviewed by the user. Embedding the run scope there lets the reviewer verify assumptions without cross-referencing external files, and makes the report self-documenting for future audits.

Example: `CryptoTaxReport.fifo_rebuild_assets` (which assets were rebuilt from Transaction History) is surfaced in the "FIFO Rebuild Scope" section of the Loan Activity tab, not just logged at INFO.

## 51. All-or-Nothing File Set Validation for External Exports

When a subsystem requires a complete set of N files from an external tool export (e.g. Koinly's capital gains, income, and transaction history), validate with all-or-nothing semantics:

- **None present** → skip gracefully (no-op mode — the external data source is simply not configured for this run).
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

Koinly uses prefixes/suffixes for tracked or staked tokens (e.g., **TSTON**, **TSUSDE**) — these don't match exact popular token names but contain the base token as a substring.

**Implementation**: `_contains_popular_token()` checks if any popular token exists as a substring (case-insensitive) within the asset ticker.

**Use**: Zero-value flagging uses this to catch variants like:
- TSTON → contains "TON" → flagged
- TSUSDE → contains "USDE" → flagged
- USDT itself → exact match → flagged

## 55. Verify Staged Diff Matches Implementation Before Finalizing

When finalizing work for code review or commit, the staged diff (`git diff master...HEAD`) must match the actual implementation in the working directory. Untracked files that are part of the implementation create a discrepancy — reviewers evaluate stale code while the working directory has different logic.

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

## 59. Hardcoded Set Maintenance — Check Across All Sections for Duplicates

When maintaining multi-section hardcoded collections (like `_POPULAR_CRYPTO_TOKENS`, `_INCOME_CODE_DESCRIPTIONS`), items can legitimately belong to multiple categories. Before adding an item to one section, grep across all sections to verify it doesn't already exist elsewhere in the same collection.

**Problem**: Frozensets and dicts silently deduplicate, so duplicate entries don't cause runtime errors but create confusion for maintenance and can mislead readers about category boundaries.

**Check pattern**: `grep -n '"ITEM_NAME"' src/tax_reporting/application/crypto_reporting.py` before adding a new token.

**Example**: "ARB", "OP", "MATIC" appeared in both "Layer 1 / Major chains" and "Layer 2 / Scaling" sections — keep each token in its most appropriate category only.

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
# ❌ WRONG — silent failure hides the problem
try:
    rows = read_koinly_rows(file_path)
    # ... process rows ...
except Exception:
    continue  # No visibility into what failed

# ✅ CORRECT — observable degradation
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
- For tax purposes, this is an **alienação onerosa** (onerous disposal) under CIRS art. 10(1)(e) — "instrumentos financeiros derivados"
- The disposal amount (e.g., "280.36 USDT disposed") reflects the collateral being removed from the position
- The **negative capital gain** (the loss) appears in the gain/loss column and is deductible per PT-C-016 (5-year carry-forward for short-term)

**Key distinction:** A futures liquidation is NOT a withdrawal. A withdrawal (to your own wallet) is not a taxable event for the asset itself. A liquidation is a forced disposal by the exchange and IS taxable — the loss can offset future gains.

**Concrete example:** ByBit SOL/USDT position `<POSITION_ID>` liquidated on 19 Jan 2025, 11:28:53 PM. Koinly reported -42.26 USD loss at 11:29:46 PM. The system correctly assessed disposal of 280.36 USDT (271.79 EUR) as the collateral disposition, with the loss appearing as negative gain/loss.

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
3. Run tests — config validation now recognizes the flag

**Example:** The `futures_derivatives_taxable` flag was added to `2025.toml` but the field was
missing from `TaxJurisdictionConfig`. This caused all integration tests to fail with config
validation error until the field was added to the domain model.

**See also:** `config.py` lines 44-51 (`_KNOWN_DECISION_FLAGS` derivation), `jurisdiction.py`

---

## 69. Excel Output Visual Structure Tests

When adding or modifying Excel report layouts, add visual structure tests to verify row placement, cell merging, blank rows, and header structure — not just data values. This prevents regressions where structural changes accidentally modify layout.

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

- **Absolute-position code** (writes to specific column numbers) — needs manual verification after structural changes
- **Offset-based code** (uses `start_column + N`) — may auto-adjust but still needs verification

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

**Example:** The 2026-06-07 futures/derivatives loss treatment plan used Tasks 1, 3, 5, 7, 8 for verification (code inspection, source archiving, docs review, Koinly investigation, test execution) and skipped Tasks 2, 4, 6 (country-specific config, tests, guidance) because verification confirmed the existing implementation was correct. See `docs/tmp/futures_loss_treatment_summary.md` for the investigation record and `docs/plans/2026-06-07-futures-derivatives-loss-treatment.md` for the full plan.

**See also:** plan_quality_guidelines.md for plan structure guidance on verification-before-implementation task ordering.

## 72. Data Trace Verification Requirement

When a plan investigates "is X handled correctly?" or "does the system correctly handle Y?", code inspection alone is INSUFFICIENT. The investigation must include ACTUAL data trace verification:

1. **Trace the user's specific case:** For the exact reported scenario, verify data flows from source CSV through to final output. Do not rely on code inspection alone.
2. **Verify output matches source classification:** If the source report shows "Loss" and the output shows "Gain", the investigation is incomplete regardless of whether code CAN handle negatives.
3. **Command pattern:** `grep "specific_value" source.csv` → compare with actual Excel output cell value
4. **Failure consequence:** An investigation that concludes "no code changes needed" without performing data trace verification is INCOMPLETE and must be redone.

**Example:** The 2026-06-07 futures/derivatives loss treatment investigation concluded "no code changes needed" based on code inspection alone. However, data trace verification revealed that Koinly's Other Gains Report classified entries as "Loss" while the Excel output showed them as "Gain" — a clear discrepancy that code inspection missed.

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
1. Parse calculated source (CG) — produces individual lot entries
2. Parse authoritative source (OGR) — produces event-level totals
3. Match and override lot entries with authoritative values
4. Aggregate overridden lots — preserves lot-level trail in output

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

**Status:** Completed — see `docs/plans/2026-06-10-ogr-validation-design.md`

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
- **Entry-level review flags** — domain-specific validations that apply to the entry itself
- **Independent validation results** — cross-report or cross-system validations that have their own review criteria

**Pattern:**
- Add validation results as optional nested dataclass fields (e.g., `ogr_validation: OgrValidationResult | None = None`)
- Do NOT integrate validation-result `review_required` into entry-level `__post_init__` validation
- Keep the two review mechanisms independent — validation result carries its own `review_required`/`review_reason`
- Tests that verify "YES:"/"NO" rendering must set the nested field explicitly, not delegate to origin fields

**Why:** Entry-level validation enforces that `review_reason` is set when `review_required=True`. Independent validations have their own lifecycle and should not trigger entry-level validation. Tests must verify independence explicitly.

**Example:** In Task 1 of the OGR validation design, `ogr_validation` was added to `CryptoCapitalGainEntry` as an optional field. The `__post_init__` validation only checks entry-level `review_reason`, not `ogr_validation.review_reason`. The test `test_ogr_validation_attached_to_entry` verifies this independence.

**See also:** Lesson #43 (Two-Level Review Flags), CRG-016 in crypto_rules.md

## 80. Field Aggregation Strategy Depends on Semantics

When aggregating grouped entries (e.g., FIFO lots into sale events), field aggregation strategy depends on field semantics — not all fields should be summed.

**Pattern:** For each field in the aggregated result, choose the strategy based on what the field represents:
- **Lookup value fields** — Take from first entry (all entries in group share the same lookup key, so the value is identical across entries). Example: `ogr_gain_loss` from OGR lookup by (date, asset, wallet)
- **Per-lot contribution fields** — Sum across all entries. Example: `calculated_gain_loss` where each lot contributes to the total
- **Boolean flags** — Use OR logic (True if ANY entry has True). Example: `direction_conflict`, `review_required`
- **Severity indicator fields** — Use maximum value. Example: `magnitude_diff_percent` to show worst deviation
- **Narrative text fields** — Join unique values with delimiter and deduplicate. Example: `review_reason` joined with "; "

**Implementation:** `_aggregate_ogr_validation()` in Task 3 of OGR validation design demonstrates all five patterns.

**Why:** Assuming "sum" for all numeric fields is incorrect — some numeric fields represent a shared lookup value that must NOT be summed, while others represent independent contributions that must be summed. Mixing these semantics produces incorrect results (e.g., summing `ogr_gain_loss` would multiply the OGR value by the number of lots, which is wrong).

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

**Why:** These constants are coupled — they all represent "how many columns exist." Missing one causes bugs that only appear at runtime or in specific test scenarios.

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

When adding a new feature controlled by a boolean flag (like `use_other_gains_report`), create dedicated backward compatibility tests that verify the "disabled" state preserves existing behavior — not just that the "enabled" state works correctly.

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
- Single lot CG: 1.72 EUR vs OGR total: 137.73 EUR → "differs by 5474%" ❌ (noise)
- Aggregated CG: ~137 EUR vs OGR: 137.73 EUR → "differs by ~0.5%" ✅ (signal)

**Pattern:**
1. Apply corrections (e.g., direction override) to individual lots before aggregation if needed for correct totals
2. During/after aggregation, recalculate all validation metrics from aggregated values:
   - `direction_conflict` = sign(agr_OGR) ≠ sign(agr_CG)
   - `magnitude_diff_percent` = |(agr_OGR - agr_CG) / agr_CG| × 100
   - `review_required` = based on aggregated thresholds
   - `review_reason` = built from aggregated state
3. Don't inherit/OR individual lot flags — they reflect pre-aggregation noise

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

**Correct pattern — identify by structure:**
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
