# Development Lessons: Common Issues and Prevention Strategies

Canonical reference for recurring patterns observed during code fixes in this codebase.
Agents should read this alongside the main instruction rules in CLAUDE.md.

---

## 1. Code Quality and Duplication

**Principle:** Family D (Single source of truth)

- Always check for duplicate test methods or functions before adding new code.
- Command: `grep -n "def method_name" . -r`

**See also (principle cluster D):** #59 (same family, distinct angle: general duplicate-detection seed (#1) vs frozenset cross-section (#59)).

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

**Principle:** Family F (Layering / dependency direction)

- Check all imports against declared dependencies before submitting.
- Import from public `__all__` exports; avoid `_private` imports in tests unless necessary.
- Run tests early to catch missing imports.

**See also (principle cluster F):** #28 (same family, distinct angle: broad import-hygiene seed (#5) vs focused private-boundary principle with remediation (#28). Cross-link. (If the fresh-agent finds #5's other bullets irrelevant and only the private-import bullet matters, this could tighten to a true-duplicate; default is overlapping.)).

## 6. Testing Best Practices

**Principle:** Family A (Equivalence-class coverage)

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

**Principle:** Family A (Equivalence-class coverage)

- All external data string fields (from any provider: Koinly, IB, etc.) must be wrapped with `safe_cell_value()` before writing to Excel cells. Formula injection vulnerabilities exist if even one field is unprotected.
- Check consistency: if most fields in a section use `safe_cell_value()`, any unprotected field is likely a bug.
- Common unprotected fields to watch: `review_reason`, `description`, chain names, wallet labels, platform names.

## 8. Type Annotation Specificity
- Use specific element types for generic collections: `list[Type] | None` instead of `list | None`.
- Specific types improve documentation, IDE autocomplete, and static analysis.
- When the type is imported only for annotations, keep it inside `TYPE_CHECKING` block.

## 9. Exception Handler Specificity

**Principle:** Family B (Error-policy propagation)

- Catch specific exception types (`FileProcessingError`, `ValueError`) instead of broad `Exception`.
- Broad exception handlers mask programming errors and make debugging harder.
- When a function documents raising a specific exception, catch that exact type in callers.

**See also (principle cluster B):** #38 (same family, distinct angle: write-side (catch specific not broad, #9) vs escape-side (convert the specific type so it evades the broad handler, #38)).

## 10. Refactoring and Maintenance
- Make small incremental changes and run `uv run pytest` after each one.
- Remove temporary scripts immediately after use.

## 11. Error Handling and Logging
- Always include row numbers and problematic data in error messages.
- Use `from e` exception chaining to preserve original context.
- Logging: parameterised format (`%s`). Exceptions: f-strings. See §1 Instruction Rules for full detail.

## 12. API Design for Production vs Testing

**Principle:** Family H (Verify the real thing, not the abstraction)

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

**Principle:** Family H (Verify the real thing, not the abstraction)

- Verify that a feature works end-to-end, not just that it returns a certain value.
- Use realistic test data; check that integrated components produce correct outputs.

## 17. Test CSV Data Construction: Column Alignment

See `~/Projects/.ai-playbook/python_guidelines.md` #1 for full prevention rules.
Repo context: Koinly `_TH_HEADER` has 20 columns; hand-counting commas is the biggest source of wasted debug iterations.

## 137. Post-Extraction Cleanup

See `~/Projects/.ai-playbook/python_guidelines.md` #2 for full cleanup procedure.
Repo context: past extractions (crypto_reporting.py → token_origin.py + koinly_parser.py) left unused imports and dead code.

## 138. Aggregation Logic: Test Both Directions

**Principle:** Family A (Equivalence-class coverage)

See `~/Projects/.ai-playbook/agent_workflow_guidelines.md` #1.
Repo context: LP liquidity operations; fixing "in" direction broke "out" because liquidity out produces multiple outputs from one input.

## 139. Operator Mapping Field Semantics (`service_start_date` / `valid_from`)

**Principle:** Family D (Single source of truth)

See `~/Projects/.ai-playbook/agent_workflow_guidelines.md` #3 for the generic field-semantics lesson.
Repo-specific constraint: `valid_from` is audit-only (when the mapping was verified from source docs). `service_start_date` is for transaction matching (when the platform started offering this service). Never use `valid_from` as a matching gate. When both are known, `service_start_date <= valid_from`.

**See also (principle cluster D):** #80 (same family, distinct angle: field-semantics determine strategy (#80) vs field-identity (#139)).

## 18. Review Agent False Positives

See `~/Projects/.ai-playbook/agent_workflow_guidelines.md` #2.

## 19. Descriptive Output Labels

**Principle:** Family C (Representation: sentinel vs None vs exception)

See `~/Projects/.ai-playbook/coding_guidelines.md` #9 for the canonical rule.
Repo context: crypto gains sheet headers renamed from terse Koinly CSV names to self-explanatory terms (e.g. "Quantity" not "Amount", "Acquisition Cost (EUR)" not "Cost (EUR)").

## 20. Frozen Dataclass `__post_init__` Field Normalization

A frozen dataclass cannot assign to its own fields in `__post_init__`. Use `object.__setattr__(self, field, value)` to normalize fields (e.g. converting empty strings to `None`) during validation. Without this, the normalization is computed but silently discarded.

## 21. Date Comparison Must Use Date Objects, Not Strings

**Principle:** Family H (Verify the real thing, not the abstraction)

Comparing ISO date strings with `<` / `>=` works for same-length same-format strings but silently produces wrong results when formats differ (e.g. `"2025-3-5" < "2025-12-01"` is `True` but `"2025-3-5" < "2025-10-01"` is `False` because `"3"` > `"1"`). Always parse to `date` objects before comparison.

**See also (principle cluster H):** #132 (same family, distinct angle: datetime representation traps.).

## 22. ISO Date Validation Must Enforce Zero-Padding

**Principle:** Family A (Equivalence-class coverage)

`map(int, "2025-3-5".split("-"))` succeeds, but `YYYY-MM-DD` requires two-digit month and day. Validate each component's string length: year 4 digits, month 2 digits, day 2 digits. Same applies to `HH:MM:SS` time components.

## 23. Three-Way Doc Sync: Code, Registry, Decision Log

**Principle:** Family D (Single source of truth)

When a feature uses both code-based mappings and canonical documentation (e.g. operator origin registry, mapping decision log), any field change must be applied to all three in the same commit. Code review consistently catches doc drift as a finding. Add a verification step to the plan: "grep for changed field names in registry and decision log."

**See also (principle cluster D):** #58, #68, #94 (same family, distinct angle: multi-authority synchronization; #94 is the test-enforced variant of #23's manual grep.).

## 24. Consult Decision Points Before Tax-Treatment Assumptions

Before discussing, proposing, or implementing any crypto tax treatment (cost-basis method, taxability of swaps, Koinly settings), check `docs/maintenance/tax/decision_points/` first. In this session, incorrect assumptions about crypto-to-crypto swap taxation led to a wrong recommendation (turn FMV on) when the answer was already documented in DP-002 (carry-over mandated by CIRS Art. 10(20)). Decision points exist specifically to prevent re-litigating settled questions.

## 25. Integration Test Fixture Consistency for Computed Fields

**Principle:** Family D (Single source of truth)

When adding a computed field to a data class used in integration tests, update ALL construction sites to compute the field from actual test data, not from a zero-valued or empty placeholder. Using `CryptoCapitalGainStats.from_entries([])` while `capital_entries` has real data produces inconsistent output (statistics section shows all zeros next to non-zero capital gains). Search for all construction sites with `grep -n "DataClass("` before committing; each site must derive the new field from its own test data.

## 26. Atomic File Replacement: No Pre-Deletion

**Principle:** Family E (Temporal / ordering invariants)

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

**Principle:** Family E (Temporal / ordering invariants)

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

**Principle:** Family F (Layering / dependency direction)

Constants prefixed with `_` are module-private by convention. When a constant is needed in another module (e.g., `crypto_reporting.py` needs `_DEFAULT_ZERO_BASIS_REVIEW_THRESHOLD` from `config.py`), rename it to a public name first. Importing private names across modules violates the API boundary and creates hidden coupling. Apply the same rule that lesson #5 states for tests.

## 29. AT Guidance May Cite Pre-Amendment Paragraph Numbers

**Principle:** Family H (Verify the real thing, not the abstraction)

See `docs/maintenance/project-guidelines.md` #3 for the full rule.
Concrete instance: AT folheto 2026-01-12 (published after Lei n.º 31/2024) still cited CIRS art. 43 as "(n.º 6)(g)" and "(n.º 7)"; the old numbers before the June 2024 amendment renumbered them to n.8(g) and n.9 respectively. The stale numbers had silently propagated into `sources.md` and `platform-divergences.md`. The discrepancy was only caught by cross-checking the folheto against the consolidated CIRS PDF (which shows inline annotations like `(Anterior n.º 7 - Lei n.º 31/2024)`).

Prevention: whenever consulting AT guidance that cites a CIRS paragraph number, search for that legal text in the consolidated CIRS PDF and confirm the current paragraph number before recording citations.

---

## 33. Plan Edge Case Behavior Must Be Traced to Correctness Outcome

**Principle:** Family H (Verify the real thing, not the abstraction)

When writing a plan's Gist & Examples section, trace every described "edge case" or "behavior change" outcome to its user-facing result and verify it satisfies the project's correctness requirements, not just that it differs from the previous behavior.

A common failure mode: comparing the new behavior to the old one ("better than X") without verifying the new behavior is itself correct. Example from this project: "TH absent → `frozenset()` → contaminated Koinly CG passes through" was initially described as an improvement over "TH absent → CG silently dropped". Both behaviors produce wrong tax figures. The correct behavior is to raise `FileProcessingError` immediately; the improvement is the explicit failure, not acceptance of contaminated data.

**Test:** For every edge case in a plan, ask "what does the user see in the output?" and verify that output is either correct, or flagged as requiring review with a specific reason. Contaminated financial data presented without a flag is never acceptable.

**Cross-check:** Verify that described edge case behavior is consistent with existing `CLAUDE.md` constraints (e.g. "Optional crypto ingestion must be non-blocking" does not mean wrong data should silently substitute for missing correct data).

---

## 30. Verify Warning/Guard Path Reachability Before Writing Tests

**Principle:** Family H (Verify the real thing, not the abstraction)

Before writing a test for an existing warning, guard, or defensive code path, verify that the path can actually be triggered with current production code. Trace every condition that must be true simultaneously for the code to reach that branch.

If the path is unreachable via real data (e.g., a placeholder mechanism always fires before the guard condition can be met), the test must either: (a) use a mock/patch to inject the edge case directly, or (b) first amend the implementation to make the path reachable.

Claiming "implementation is already complete" for an untested path without first proving it is reachable leads to tests that can never go RED → the TDD cycle is broken and the coverage is false.

## 31. Read Full Dataclass Definition Before Describing Fields in a Plan

**Principle:** Family H (Verify the real thing, not the abstraction)

When a plan task describes the fields of a dataclass (e.g., listing fields to be moved or created), always read the actual class definition in source code to obtain the complete, current field list, including fields with default values that are easy to miss.

Omitting a field from a plan that is then used downstream (e.g., `partial_carryover_tx_keys` consumed by `resolve_cross_asset_exchanges`) silently changes behaviour and is not caught until runtime.

## 32. Distinguish Code Comments from Observed Data

**Principle:** Family H (Verify the real thing, not the abstraction)

When describing data behaviours (e.g., "this swap direction occurs"), explicitly distinguish between: (a) a behaviour observed in actual source data files, and (b) a behaviour described in a code comment or docstring.

Code comments reflect developer intent or known edge cases at the time of writing; they are not evidence that the behaviour has occurred in real data. For data-driven claims, check actual input files in `resources/source/` before asserting the behaviour is present.

## 34. Use `perl -i -pe` for Word-Boundary Replacements on macOS

macOS `sed` does not support `\b` word boundary anchors. Substitutions using `\b` appear to succeed (exit code 0) but make no substitutions, causing silent failures.

Use `perl -i -pe 's/\bold_name\b/new_name/g' file` for word-boundary renames on macOS. Verify with a grep after the substitution to confirm zero remaining occurrences.

## 36. Avoid `__getattr__` Delegation in Wrapper Dataclasses

See `~/Projects/.ai-playbook/python_guidelines.md` #3 for the canonical rule.
Repo context: `AcquisitionContext`/`ConsumptionContext` wrappers were introduced to attach `tx_key` and `source_row_index` to domain entities without modifying the domain layer. The `__getattr__` delegation made type checkers unable to verify delegated field access (`.date`, `.asset`, etc.), and the `with_acq()`/`with_con()` factory methods were called only twice combined. The correct fix is to add `tx_key` and `source_row_index` directly to `CryptoAcquisition` and `CryptoConsumption` in the domain layer.

## 37. Monkeypatch Module-Level Path Constants in Unit Tests

**Principle:** Family H (Verify the real thing, not the abstraction)

See `~/Projects/.ai-playbook/python_guidelines.md` #4 for the canonical rule.
Repo context: `_DECISION_POINTS_DIR = _REPO_ROOT / "docs/maintenance/tax/decision_points"` in `config.py` is resolved at import time. Tests in `TestLoadTaxJurisdictionConfig` that called `_load_tax_jurisdiction_config()` without patching this constant silently read the real `2025.toml` from the working tree. They passed because the real file existed and had PT=True; any rename, move, or fiscal-year change would cause a cryptic `FileNotFoundError` rather than a meaningful test failure.
Fix: monkeypatch `_DECISION_POINTS_DIR` to a `tmp_path`-based directory with a minimal TOML fixture, identical to the pattern in `TestLoadDecisionPointsFlags`.

## 38. Decision Points TOML Missing Must Raise `ConfigurationError`, Not Bare `FileNotFoundError`

**Principle:** Family B (Error-policy propagation)

`_load_decision_points_flags()` must convert `FileNotFoundError` (missing TOML for the configured fiscal year) to `ConfigurationError` before it reaches `main.py`. The `main.py` exception handler has a separate `(FileNotFoundError, OSError)` branch for a missing `config.ini`, which logs "Config file not found; crypto pipeline will run without jurisdiction filters" and continues. If the TOML-not-found error reaches that branch, the pipeline silently proceeds with `exclude_loan_repayment_gains=False`; loan repayment disposals are incorrectly included in capital gains with no error raised.

Fix pattern in `_load_tax_jurisdiction_config`:
```python
try:
    flags = _load_decision_points_flags(country, fiscal_year, logger)
except FileNotFoundError as e:
    raise ConfigurationError(
        f"Decision points file missing for fiscal year {fiscal_year}; "
        f"create docs/maintenance/tax/decision_points/{fiscal_year}.toml before running"
    ) from e
```

**See also (principle cluster B):** #9 (same family, distinct angle: write-side (catch specific not broad, #9) vs escape-side (convert the specific type so it evades the broad handler, #38)).

## 39. Resource-Release Flag Must Be Set After Successful Release Only

**Principle:** Family E (Temporal / ordering invariants)

See `~/Projects/.ai-playbook/python_guidelines.md` #5 for the canonical rule.
Repo context: `workbook_builder.py` set `workbook_closed = True` unconditionally after a `try/except` that swallowed `workbook.close()` exceptions. The `finally` block then skipped the fallback `workbook.close()` call because the flag was already `True`, leaking the file handle whenever both the crypto sheet rendering and the subsequent close both raised.

## 40. Defensive Warnings Must Also Record Items in the Failure-Tracking Structure

**Principle:** Family G (Data-loss observability)

When a defensive branch fires because a row cannot be fully processed (e.g. "both sides loan-affected"), always append the untracked item to `parse_failures_by_asset`; do not rely on a `logger.warning` alone. A logged warning is invisible to the workbook consumer; only items recorded in the failure-tracking structure surface as `review_required` flags in the output.

Example: in `_classify_th_row`, when both the sent and received currencies are loan-affected, the non-principal side was silently ignored. Fix: `parse_failures_by_asset.setdefault(untracked_currency, []).append(row_index)` in all four affected branches (sell, crypto_withdrawal, buy, crypto_deposit).

General principle: "Unmatched items must never be silently discarded" (see CLAUDE.md §1) applies to defensive-path items too; logging is necessary but insufficient when a failure-tracking collection exists.

**See also (principle cluster G):** #61 (same family, distinct angle: structure-recording (#40) vs baseline log-it (#61)).

## 41. Extracted Helpers Need Direct Unit Tests for Key Invariants

**Principle:** Family A (Equivalence-class coverage)

When refactoring extracts a private helper from a large orchestrator, add direct unit tests covering the key behavioral invariants (exact-match, partial consume, exhaustion, empty input, non-taxable path). Relying only on orchestrator-level coverage means a future regression in the helper requires tracing through the orchestrator before the failure is localized.

Example: extracting `_consume_against_pool_inplace` from the FIFO orchestrator prompted adding six focused tests in `TestConsumeAgainstPoolInplace`, reducing the blast-radius of future regressions to a single function.

**See also (principle cluster A):** #91 (same family, distinct angle: the audit's only true-duplicate candidate, overturned to OVERLAPPING by the fresh-agent challenge. Canonical = #91 (domain-neutral control-flow taxonomy), See-also #41 (incident-anchored FIFO witness). Full record in `### true-duplicate candidates` and `## Precision gate`.).

## 42. Failing Tests: Distinguish Stale Expectation from Production Bug

**Principle:** Family H (Verify the real thing, not the abstraction)

When a test fails, first determine whether the test expectation became stale (design changed) or whether production code regressed. Changing production code to make a stale test pass is the wrong fix; it re-introduces the removed behavior.

Indicator: the test reads live state from the system under test (e.g. `review_required=bybit_origin.review_required`) instead of an explicit hardcoded fixture value. If the underlying mapping changed for valid reasons, the test silently tracks the wrong behavior.

Rule: tests that verify rendering or display behavior (e.g. "YES: ..." vs "NO" in an Excel cell) must use explicit hardcoded fixture values, not values delegated to `origin.some_field`. Hardcoding makes the test's intent clear and decouples it from unrelated mapping changes.

## 43. Two-Level Review Flags: Separate Platform-Level from Row-Level

**Principle:** Family C (Representation: sentinel vs None vs exception)

When a dataclass field serves two semantically different purposes, introduce a second explicitly named field rather than overloading the first.

Example: `OperatorOrigin.review_required` was used for both (a) per-transaction issues (temporal validity failure, unknown platform) that should color transaction rows, and (b) platform-level concerns (e.g. account-region ambiguity) that should only appear on a summary tab. Adding `platform_review_required: bool = False` as a distinct field removed the conflation cleanly. See CRG-016.

**See also (principle cluster C):** #79 (same family, distinct angle: platform-vs-row flags (#43) vs independent-validation-vs-entry flags (#79, cites #43)).

## 44. Summary Sheets Should Be Complete Manifests, Not Filtered Lists

**Principle:** Family G (Data-loss observability)

A summary/manifest sheet (e.g. Platform Assumptions) should list ALL items in the dataset with metadata columns, not only items that satisfy a filter condition. Filtering by flag omits clean items that a reviewer may still want to audit, and hides the total scope of the data.

Use flag columns (e.g. "Review Required = YES/NO", sort review-required first) to draw attention to items needing action, while preserving the complete manifest for auditability. Apply red row fill only to the flagged rows.

## 45. Deduplication Key Must Capture Minimum Sufficient Identity

**Principle:** Family G (Data-loss observability)

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

**Principle:** Family G (Data-loss observability)

When filtering FIFO pipeline output to the reporting fiscal year, filter *only disposal /
realization records*, never the acquisition records. Prior-year acquisitions must remain
in the FIFO pool so cost-basis carry-over is correct; filtering them by year would produce
incorrect zero-cost gains for multi-year holds.

Correct position: filter `AssetFifoResult.realizations` after the FIFO engine produces
them, before converting to `CryptoCapitalGainEntry`. Do not pre-filter `acquisitions` or
`consumptions` inputs to the FIFO engine.

## 35. CSV Test Fixture Column Alignment Must Be Verified

**Principle:** Family H (Verify the real thing, not the abstraction)

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

**Principle:** Family C (Representation: sentinel vs None vs exception)

When inlining a helper that switches internal state from `{}` to `defaultdict(list)`, any test that directly calls the helper with a plain dict `{}` will silently get a `KeyError` on first missing key. Update such tests to pass `defaultdict(list)` directly, or update the inlined code to use `.setdefault(key, [])` instead of relying on defaultdict auto-init so plain-dict callers still work.

## 49. `TaxJurisdictionConfig` Lives in `domain/jurisdiction.py`

**Principle:** Family F (Layering / dependency direction)

`TaxJurisdictionConfig` was moved from `infrastructure/config.py` to `domain/jurisdiction.py`. `config.py` re-exports it for backward compat. All new code should import from `domain.jurisdiction` directly; infrastructure imports are for backward compat only.

## 50. Run-Determining Parameters Belong in the Output Artifact, Not in Logs

**Principle:** Family D (Single source of truth)

When a pipeline run produces different results depending on dynamically-discovered inputs (e.g. which assets are loan-affected, which platforms are active, which years are in scope), expose those inputs in the output report itself, as a dedicated worksheet section, a named range, or a metadata tab, rather than relegating them to log lines or ephemeral sidecar files.

Logs are consumed during a run and discarded; a sibling file adds surface area and may not be opened. The workbook is the primary artifact reviewed by the user. Embedding the run scope there lets the reviewer verify assumptions without cross-referencing external files, and makes the report self-documenting for future audits.

Example: `CryptoTaxReport.fifo_rebuild_assets` (which assets were rebuilt from Transaction History) is surfaced in the "FIFO Rebuild Scope" section of the Loan Activity tab, not just logged at INFO.

## 51. All-or-Nothing File Set Validation for External Exports

**Principle:** Family G (Data-loss observability)

When a subsystem requires a complete set of N files from an external tool export (e.g. Koinly's capital gains, income, and transaction history), validate with all-or-nothing semantics:

- **None present** → skip gracefully (no-op mode; the external data source is simply not configured for this run).
- **Partial set present (1 of N or 2 of N)** → raise `FileProcessingError` with an explicit list of missing files and export instructions. Partial presence is worse than none: it silently produces an incomplete report that looks valid (e.g. rewards disappear but no error is raised).
- **All N present** → proceed normally.

The silent-data-loss case that triggered this lesson: `income_file = None` was handled as `reward_entries = []` with no warning or error, so Wirex EUR lending interest vanished from the Crypto Rewards tab without any indication. The user attributed the disappearance to a code change, but the actual cause was a missing export file. Fail-fast on partial sets eliminates this class of confusion.

**See also (principle cluster G):** #63 (same family, distinct angle: total-failure fail-fast (#63) vs partial-file-set fail-fast (#51)).

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

**Principle:** Family H (Verify the real thing, not the abstraction)

When finalizing work for code review or commit, the staged diff (`git diff master...HEAD`) must match the actual implementation in the working directory. Untracked files that are part of the implementation create a discrepancy; reviewers evaluate stale code while the working directory has different logic.

**Check before finalizing**: Run `git status` and verify no files that are part of the implementation appear as untracked (`??`). If a new source file or test exists in the working directory but is not staged, add it with `git add <file>` before considering the work ready for review.

**Why**: Code reviews evaluate staged changes. If staged code differs from working directory, review findings may be obsolete or the review may miss issues that exist only in untracked files.

**See also (principle cluster H):** #116, #122, #128, #129 (same family, distinct angle: the git/docs-state verification cluster.).

## 56. Try/Finally Resource-Cleanup Scope Must Cover All Raising Operations

**Principle:** Family E (Temporal / ordering invariants)

When using try/finally for resource cleanup (e.g., `workbook.close()`, `file.close()`), ensure all operations that can raise exceptions before the finally block are covered by the same try block. If an operation outside the try/finally raises, the cleanup never runs.

**Fix by**: Either (1) start the try block early enough to cover all operations that can raise, or (2) wrap early operations in their own try/except with explicit cleanup before re-raising.

**Example**: In workbook_builder.py, `aggregate_taxable_rewards()` was called before the try/finally that closes the workbook. If aggregation raised, the workbook was never closed. Fixed by moving aggregation inside the try block so any exception triggers workbook cleanup.

**See also (principle cluster E):** #106 (same family, distinct angle: try/finally cleanup scope (#56) vs reuse-parsed-value-in-try (#106)).

## 57. When Removing Functions, Remove Their Tests

When removing or deleting a function from a module, check for and remove any tests that import or test that function. Leaving tests that import deleted functions causes `ImportError` during test collection.

**Check**: Use `grep -rn "<function_name>" tests/` to find test references before removing the function.

## 58. Update Documentation When Code Structure Changes

**Principle:** Family D (Single source of truth)

When restructuring code (changing sheet layouts, renaming components, merging or splitting modules), update all documentation that describes the structure in the same session. README files, walkthough documents, and project overviews that describe the old structure become misleading and cause confusion.

**Scope**: Check README.md, any walkthrough or presentation docs, and any architectural decision documents that mention the changed components.

**See also (principle cluster D):** #23, #68, #94 (same family, distinct angle: multi-authority synchronization; #94 is the test-enforced variant of #23's manual grep.).

## 59. Hardcoded Set Maintenance: Check Across All Sections for Duplicates

**Principle:** Family D (Single source of truth)

When maintaining multi-section hardcoded collections (like `_POPULAR_CRYPTO_TOKENS`, `_INCOME_CODE_DESCRIPTIONS`), items can legitimately belong to multiple categories. Before adding an item to one section, grep across all sections to verify it doesn't already exist elsewhere in the same collection.

**Problem**: Frozensets and dicts silently deduplicate, so duplicate entries don't cause runtime errors but create confusion for maintenance and can mislead readers about category boundaries.

**Check pattern**: `grep -n '"ITEM_NAME"' src/tax_reporting/application/crypto_reporting.py` before adding a new token.

**Example**: "ARB", "OP", "MATIC" appeared in both "Layer 1 / Major chains" and "Layer 2 / Scaling" sections; keep each token in its most appropriate category only.

**See also (principle cluster D):** #1 (same family, distinct angle: general duplicate-detection seed (#1) vs frozenset cross-section (#59)).

## 60. Document Tradeoffs for Fuzzy Matching in Docstrings

When implementing fuzzy matching (substring matching, regex patterns, glob patterns, etc.) that could produce false positives, document the tradeoff explicitly in the docstring so future maintainers understand the design decision and don't "fix" what isn't broken.

**What to document**:
- What the fuzzy matching catches (intended targets)
- What false positives it may produce (collateral matches)
- Why the approach is acceptable despite its imperfections
- The consequence of a false positive (usually just flagging for review rather than skipping important data)

**Example** (from `_contains_popular_token`): "Tradeoff: Substring matching may cause false positives for tickers that coincidentally contain popular token names as substrings (e.g., 'MATICAL' matches 'MATIC'). This is acceptable because the consequence is merely flagging for review rather than incorrectly skipping a legitimate zero-value reward."

## 61. Add Logging to Silent Exception Handlers

**Principle:** Family G (Data-loss observability)

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

**See also (principle cluster G):** #40 (same family, distinct angle: structure-recording (#40) vs baseline log-it (#61)).

## 62. Review Documents Are Temporary Artifacts

Code review documents in `docs/history/reviews/` are temporary staging artifacts for the review workflow, not permanent documentation. They serve as:
- Approval artifacts before posting review comments to a PR
- Persistent record of what was reviewed and what changed

**Lifecycle**:
1. Created during code review with findings marked as `pending`
2. Updated to `fixed` / `drop` / `post` as findings are addressed
3. After all findings are addressed: either delete the file or move to `docs/tmp/` if it has reference value

**Do not**: Accumulate stale review documents in `docs/history/reviews/`. After the branch is merged, these documents have no further purpose.

## 63. Fail Fast for Data-Completeness Operations

**Principle:** Family G (Data-loss observability)

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

**See also (principle cluster G):** #51 (same family, distinct angle: total-failure fail-fast (#63) vs partial-file-set fail-fast (#51)).

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

**Principle:** Family D (Single source of truth)

Hardcoded lists that change frequently (popular tokens, supported exchanges, asset tickers) should be externalized to data files, not embedded in source code. Use cached loading for performance.

**Pattern**:
```python
# ❌ WRONG - Requires code change for every new token
_POPULAR_TOKENS = frozenset(("BTC", "ETH", "SOL", ...))  # 70+ items

# ✅ CORRECT - External data file, cached in memory
@lru_cache(maxsize=1)
def _load_popular_tokens() -> frozenset[str]:
    with open("docs/maintenance/tax/popular_crypto_tokens.json") as f:
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

**See also:** DP-010 in `docs/maintenance/tax/decision_points/2025.md`, PT-C-031 and PT-C-032 in `docs/maintenance/crypto_rules.md`, lesson #73 (Cross-Report Validation), lesson #75 (OGR override timing)

## 68. Decision Point Flags Require TaxJurisdictionConfig Field

**Principle:** Family D (Single source of truth)

When adding a new boolean decision point flag to `docs/maintenance/tax/decision_points/<year>.toml`,
you must also add the corresponding field to `TaxJurisdictionConfig` in `src/tax_reporting/domain/jurisdiction.py`.

**Why this is required:** The config validation system auto-discovers known decision point flags
via `_KNOWN_DECISION_FLAGS` in `config.py` (lines 44-51), which is derived from all bool fields
in `TaxJurisdictionConfig`. If a flag exists in TOML but has no corresponding field in the dataclass,
validation fails with "Unknown decision points flag" error and all config-dependent tests break.

**Pattern:**
1. Add bool field to `TaxJurisdictionConfig` (e.g., `futures_derivatives_taxable: bool = False`)
2. Add flag to `docs/maintenance/tax/decision_points/<year>.toml` under `[countries.<CC>]` section
3. Run tests; config validation now recognizes the flag

**Example:** The `futures_derivatives_taxable` flag was added to `2025.toml` but the field was
missing from `TaxJurisdictionConfig`. This caused all integration tests to fail with config
validation error until the field was added to the domain model.

**See also:** `config.py` lines 44-51 (`_KNOWN_DECISION_FLAGS` derivation), `jurisdiction.py`

---

**See also (principle cluster D):** #23, #58, #94 (same family, distinct angle: multi-authority synchronization; #94 is the test-enforced variant of #23's manual grep.).

## 69. Excel Output Visual Structure Tests

**Principle:** Family A (Equivalence-class coverage)

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

**Principle:** Family A (Equivalence-class coverage)

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

**Principle:** Family H (Verify the real thing, not the abstraction)

When a plan investigates "is X handled correctly?" or "does the system correctly handle Y?", structure the plan with verification tasks before implementation tasks:

1. **Start with verification:** Code inspection, test execution, and documentation review
2. **Then decide on implementation:** Skip implementation tasks if verification shows correctness
3. **Document findings:** Create investigation artifacts under `docs/tmp/` (or promote to canonical docs if reusable)

This pattern prevents unnecessary work when the current implementation is already correct. It applies to any "is this handled correctly?" question, regardless of domain.

**Example:** The 2026-06-07 futures/derivatives loss treatment plan used Tasks 1, 3, 5, 7, 8 for verification (code inspection, source archiving, docs review, Koinly investigation, test execution) and skipped Tasks 2, 4, 6 (country-specific config, tests, guidance) because verification confirmed the existing implementation was correct. See the futures-loss investigation record (local) for the investigation record and `docs/history/plans/2026-06-07-futures-derivatives-loss-treatment.md` for the full plan.

**See also:** plan_quality_guidelines.md for plan structure guidance on verification-before-implementation task ordering.

**See also (principle cluster H):** #72, #97 (same family, distinct angle: investigation pattern / data-trace / characterization-test.).

## 72. Data Trace Verification Requirement

**Principle:** Family H (Verify the real thing, not the abstraction)

When a plan investigates "is X handled correctly?" or "does the system correctly handle Y?", code inspection alone is INSUFFICIENT. The investigation must include ACTUAL data trace verification:

1. **Trace the user's specific case:** For the exact reported scenario, verify data flows from source CSV through to final output. Do not rely on code inspection alone.
2. **Verify output matches source classification:** If the source report shows "Loss" and the output shows "Gain", the investigation is incomplete regardless of whether code CAN handle negatives.
3. **Command pattern:** `grep "specific_value" source.csv` → compare with actual Excel output cell value
4. **Failure consequence:** An investigation that concludes "no code changes needed" without performing data trace verification is INCOMPLETE and must be redone.

**Example:** The 2026-06-07 futures/derivatives loss treatment investigation concluded "no code changes needed" based on code inspection alone. However, data trace verification revealed that Koinly's Other Gains Report classified entries as "Loss" while the Excel output showed them as "Gain", a clear discrepancy that code inspection missed.

**See also (principle cluster H):** #71, #97 (same family, distinct angle: investigation pattern / data-trace / characterization-test.).

## 73. Cross-Report Validation for Multi-Report Systems

**Principle:** Family G (Data-loss observability)

When investigating systems that process data from multiple source reports (e.g., Koinly Transaction History, Capital Gains Report, Other Gains Report), verify classifications match across ALL reports before concluding correctness:

1. **Identify all source reports:** List every CSV/report the system processes
2. **Cross-reference classifications:** If one report shows Type="Loss" and another shows Gain/Loss=positive, investigate which report drives the final output
3. **Verify final output reflects the correct classification:** The Excel/final output must match the economically correct classification, not just the mechanically calculated one
4. **Document which report is authoritative:** When source reports disagree, state which report's classification is correct and why

**Example:** Koinly's Other Gains Report correctly classified futures liquidations as "Loss" with negative amounts, while the Capital Gains Report calculated positive gains based on collateral proceeds. The system only processes Capital Gains Report, so losses appeared as gains in the final output. Cross-report validation would have caught this discrepancy.

**See also:** Lesson #75 (Authoritative Source Overrides Must Precede Aggregation)

## 74. Cross-Module Function Dependencies Require Complete Imports

**Principle:** Family H (Verify the real thing, not the abstraction)

When adding a function in one module that calls a function from another module, verify the import is complete. Unit tests that don't exercise the full code path (e.g., only test helper functions but not the file-discovery wrapper) can miss import errors that would cause runtime `NameError`.

**Verification:** After adding cross-module function calls, run `uv run python -c "from module import function"` to verify imports resolve at import time, not just at call time.

**Example:** `_find_and_parse_other_gains_file()` in `koinly_parser.py` called `_find_report_path()` from `crypto_reporting.py` without importing it. Unit tests for the helper functions (`_extract_ogr_gain_loss`, `_parse_other_gains_row`) passed because they didn't call the file-discovery function. A full import check would have revealed the missing dependency before runtime.

## 75. Authoritative Source Overrides Must Precede Aggregation

**Principle:** Family D (Single source of truth)

When applying overrides from an authoritative source (e.g., OGR) to calculated data (e.g., CG), the override must happen BEFORE aggregation when working with lot-level entries.

**Why this matters:** CG rows are individual FIFO lots that get summed in aggregation. The authoritative source (OGR) contains the correct total gain/loss for the disposal event. Overriding after aggregation would lose the lot-level trail and make reconciliation impossible.

**Pattern:**
1. Parse calculated source (CG): produces individual lot entries
2. Parse authoritative source (OGR): produces event-level totals
3. Match and override lot entries with authoritative values
4. Aggregate overridden lots: preserves lot-level trail in output

**Example:** In `crypto_reporting.py`, `_apply_ogr_overrides()` is called after `_parse_capital_gains_file` but BEFORE `_aggregate_capital_entries()`. This ensures that when OGR reports an authoritative per-disposal loss, each individual FIFO lot for that disposal is overridden with that authoritative value before being summed. If aggregation happened first, the lot-level detail would be lost and the override could not be traced back to specific lots.

**See also:** Lesson #73 (Cross-Report Validation), AGENTS.md constraint on OGR override timing

**See also (principle cluster D):** #78, #85 (same family, distinct angle: OGR/CG authority -- override ordering (#75) vs split by aspect (#78) vs aggregate-then-validate (#85)).

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

**Principle:** Family D (Single source of truth)

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

**Principle:** Family D (Single source of truth)

**Status:** Completed; see `docs/history/plans/2026-06-10-ogr-validation-design.md`

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

**See also (principle cluster D):** #85 (same family, distinct angle: OGR/CG authority -- override ordering (#75) vs split by aspect (#78) vs aggregate-then-validate (#85)).

## 79. Independent Validation Fields vs Entry-Level Review Flags

**Principle:** Family C (Representation: sentinel vs None vs exception)

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

**Principle:** Family D (Single source of truth)

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

**See also (principle cluster D):** #139 (same family, distinct angle: field-semantics determine strategy (#80) vs field-identity (#139)).

## 81. Excel Conditional Formatting Priority Matters

**Principle:** Family E (Temporal / ordering invariants)

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
- Add helper functions for fill assertions (e.g., `_is_yellow_fill()`) to keep tests consistent

**See also:** Lesson #7 (Excel Output Security), Lesson #15 (Excel Column Width), Lesson #69 (Excel Output Visual Structure Tests), Lesson #82 (Adding Excel Columns Requires Constant Updates)

## 82. Adding Excel Columns Requires Constant Updates

**Principle:** Family D (Single source of truth)

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

**Principle:** Family A (Equivalence-class coverage)

When adding columns that can be blank/None (e.g., when validation data is absent), add dedicated tests for that state. Do not assume "no data" works correctly based on "with data" tests.

**Pattern:**
1. Add a test specifically for the blank/None state (e.g., `test_ogr_validation_columns_blank_when_ogr_validation_none`)
2. Verify the column cells are `None` (not empty string, not zero, not default value)
3. Verify conditional formatting does NOT apply for blank state (no fill when no data)

**Why:** "With data" tests only exercise the populated path. The blank/None path has different code branches (skipped assignments, no formatting applied) and is a common source of bugs.

**Example:** In Task 4 of the OGR validation design, the test `test_ogr_validation_columns_blank_when_ogr_validation_none` verifies that when `entry.ogr_validation` is `None`, the OGR columns (18, 19, 20) are explicitly `None` rather than containing leftover data or default values.

**See also:** Lesson #81 (Excel Conditional Formatting Priority), Lesson #82 (Adding Excel Columns Requires Constant Updates)

## 84. Backward Compatibility Testing for Flag-Controlled Features

**Principle:** Family A (Equivalence-class coverage)

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

**Principle:** Family D (Single source of truth)

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

**See also (principle cluster D):** #75 (same family, distinct angle: OGR/CG authority -- override ordering (#75) vs split by aspect (#78) vs aggregate-then-validate (#85)).

## 86. Avoid Circular Dependencies During Module Extraction

**Principle:** Family F (Layering / dependency direction)

When extracting a function to a new module, check what constants and functions it references from the source module. Circular imports occur when the new module imports from the source, and the source still needs to import from the new module.

**Resolution options:**
- Move shared constants to a lower-level module that both can import
- Inline simple literals (like `Decimal('0')`) locally in the new module
- Redesign to eliminate the cross-dependency

**Example from Task 8:** Extracting `_extract_loan_activity()` from `crypto_reporting.py` to `crypto/loan_activity.py` required handling the `ZERO` constant. Defining `ZERO = Decimal('0')` locally in the new module avoided a circular import, since the constant is only used for loan balance calculations.

## 87. Module and Class Size Limits

**Principle:** Family F (Layering / dependency direction)

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

**Principle:** Family F (Layering / dependency direction)

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

**Principle:** Family H (Verify the real thing, not the abstraction)

When adding edge case tests for existing functions, read the actual implementation first to understand what patterns it supports before writing expected results.

**Anti-pattern:** Writing test expectations based on function name, documentation, or assumptions about what the function "should" do, then debugging failures when expectations don't match reality.

**Correct approach:**
1. Read the function implementation completely
2. Identify all conditional branches, special cases, and return paths
3. Write test expectations that match the actual behavior
4. Add tests for genuine edge cases, not imagined patterns

**Example from chain derivation tests:** Initial tests expected "Ledger Nano X (SOL)" → "Solana" and "0x1234...abcd.eth" → "Ethereum", but the actual `_derive_chain` implementation returns "Unknown" for both patterns. Reading the implementation first would have revealed: the function only matches chains in a predefined `_KNOWN_CHAINS` set after normalization, it doesn't guess from ticker suffixes or address patterns.

## 90. Edge Case Coverage for Validation Functions

**Principle:** Family A (Equivalence-class coverage)

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

**Principle:** Family A (Equivalence-class coverage)

When a complex function is extracted into a helper, add direct unit tests for the helper rather than relying only on indirect testing through integration tests.

**What to test directly:**
- Early return conditions (empty inputs, no matches)
- Conditional branches (different input paths)
- Boundary conditions (exact threshold values)
- State mutation or concatenation (appending reasons, preserving carryover)
- Edge cases (multiple items requiring min/max selection)

**Example from FIFO helpers:** `_apply_phantom_lot_flags` was extracted but initially only tested indirectly through FIFO integration. Added direct unit tests covering: empty phantom_transfers (early return), mismatching asset/platform (no effect), realizations before vs after earliest_phantom date (conditional flagging), appending phantom reason to existing review_reason (concatenation), and preserving carryover/partial tx keys (state preservation).

**See also (principle cluster A):** #41 (same family, distinct angle: the audit's only true-duplicate candidate, overturned to OVERLAPPING by the fresh-agent challenge. Canonical = #91 (domain-neutral control-flow taxonomy), See-also #41 (incident-anchored FIFO witness). Full record in `### true-duplicate candidates` and `## Precision gate`.).

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

**Principle:** Family E (Temporal / ordering invariants)

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

**Principle:** Family D (Single source of truth)

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

**See also:** `docs/maintenance/tax/decision_points/2025.md` (canonical source), `tests/unit/application/persisting/test_assumptions_sheet.py::TestMethodologyAssumptionsSection::test_all_decision_points_documented`

---

**See also (principle cluster D):** #23, #58, #68 (same family, distinct angle: multi-authority synchronization; #94 is the test-enforced variant of #23's manual grep.).

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

**What went wrong:** During code review, I saw a path in system context (`.../memory/docs/history/reviews/`) and used it without calling `resolve-vars`. The correct approach would have been to call `resolve_var("reviews_dir", ...)` which would have discovered the project's actual `docs/history/reviews/` folder by reading project instructions and running glob discovery.

**Why this matters:** System context contains irrelevant paths from other sessions or tools. The `resolve-vars` utility exists to discover the correct path for the current project and persist it locally. Guessing from context leads to wrong output locations.

---

## 96. Structural Identification for Excel Output Tests

**Principle:** Family H (Verify the real thing, not the abstraction)

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

**Principle:** Family H (Verify the real thing, not the abstraction)

When a characterization (golden-value) test captures the actual current behavior and the captured value disagrees with the plan's stated expected value, the disagreement is itself a finding. Investigate the root cause before any implementation task proceeds, because downstream tasks often depend on the incorrect assumed value.

**Why this happens:** Plan authors writing expected values for characterization tests may conflate two related but distinct quantities when one is a downstream authoritative total and the other is the post-transformation output. The override/transformation in question may apply directional authority (sign) while preserving the other quantity's magnitude, so the expected value the author wrote (the authoritative total) is NOT the value the pipeline actually emits.

**Required response when characterization disagrees with the plan:**
1. Capture the REAL current output as the golden value (never the plan's assumed value); the whole point of a characterization test is to lock in actual behavior.
2. Trace WHY they differ using raw source inspection (read source CSVs directly, sum lots, identify which quantity the plan's number actually represents).
3. Reconcile the plan narrative so downstream tasks and the user see the corrected value with rationale.
4. Flag the discrepancy to the orchestrator/user so dependent tasks are aware.

**Do NOT** weaken the characterization assertion to match the plan's incorrect value; that defeats the test's purpose and hides a real bug or real behavior.

**Example:** The 2026-06-13 derivatives-separation plan (Task 1) stated the Case 2 expected Crypto Gains output was `<-OGR_NET_EUR> EUR` (the Other Gains Report total for that disposal), but the actual override output is `-<CG_LOTS_EUR> EUR`. The `_apply_ogr_direction_override` function uses OGR for DIRECTION only and preserves CG MAGNITUDE: the 109 CG lots sum to `+<CG_LOTS_EUR>` pre-override, and flipping the sign of each yields `-<CG_LOTS_EUR>` post-override. The `<-OGR_NET_EUR>` is the OGR-row total, a different quantity from the post-override aggregated output. The characterization test captured `-<CG_LOTS_EUR>` and the plan narrative was reconciled. See the characterization golden fixture (local) and lesson #78 (OGR directional authority runtime semantics).

**See also:** Lesson #71 (validation-first investigation), Lesson #72 (data trace verification), Lesson #78 (OGR directional authority semantics), `docs/maintenance/plan_quality_guidelines.md`.

---

## 98. Probe the Canonical URL Before Assuming an Official Source Is Unavailable

**Principle:** Family H (Verify the real thing, not the abstraction)

When a plan or task assumes an authoritative document (statute amendment, binding ruling, official circular) is "not publicly indexed", "request-specific", or otherwise unreachable, do NOT treat that assumption as ground truth. Probe the issuing authority's canonical URL pattern directly (HTTP HEAD or ranged GET) before falling back to secondary sources or skipping archival.

**Why this matters:** Plans encode assumptions about source availability that may be outdated or simply wrong. The cost of a probe is one HTTP request; the cost of skipping archival is a weakened source corpus where the authoritative document is absent and downstream analysis leans on secondary sources that paraphrase it. Several issuing authorities publish binding rulings and circulars in public indexes even when they are nominally request-specific.

**Required behavior:**
1. Construct the canonical URL from the issuing authority's documented naming convention (e.g. AT vinculativa rulings follow `info.portaldasfinancas.gov.pt/.../informacoes_vinculativas/.../Documents/PIV_<numero>.pdf`).
2. Issue a HEAD request (or a small ranged GET) to check status, content-type, and content-length.
3. On HTTP 200 with the expected media type, download and archive the document to `docs/maintenance/tax/.../official/` and add the provenance entry to `sources.md`.
4. Only when the probe definitively fails (404, 403, or a login redirect) should you fall back to secondary sources or document the source as unavailable.
5. Record the probe outcome (success or the specific failure) in the implement log so the assumption-vs-reality gap is visible.

**Anti-pattern:** Reading a plan task that says "the ruling is request-specific, so we will rely on the secondary advisory page" and proceeding straight to secondary-source archival without probing the primary URL.

**Example:** The 2026-06-13 derivatives-separation plan (Task 2) stated AT binding ruling PIV 28298/2025 was expected to be request-specific and not in the public vinculativa index. A HEAD probe of the canonical `Documents/PIV_28298.pdf` URL returned HTTP 200, `application/pdf`, 64,788 bytes. The ruling IS published in the public CIRS vinculativa list and was downloaded directly to `docs/maintenance/tax/laws/pt/crypto-tax/official/at_piv_28298_2025.pdf`, making the secondary-source-only fallback unnecessary. The ruling body also yielded the precise filing targets (Anexo G Quadro 13 code G51 for resident-source derivatives gains; Anexo J Quadro 9.2.B code G30 for non-resident) that no secondary source stated as explicitly.

**See also:** `docs/maintenance/project-guidelines.md` #1 (external source archive provenance and freshness), CLAUDE.md source-archival rules, Lesson #94 (verification for canonical source synchronization).

---

## 99. Trace the Fixture When Plan Pseudocode Compares Same-Unit Fields by Name

**Principle:** Family H (Verify the real thing, not the abstraction)

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

**See also (principle cluster H):** #100, #101 (same family, distinct angle: general plan-claim rule (#100) and its two specific witnesses.).

## 100. Verify Plan-Time Claims About Production Code Before Writing Tasks

**Principle:** Family H (Verify the real thing, not the abstraction)

When a plan task, design invariant, or gist example makes a claim about production code (field semantics, file paths, line numbers, function behavior, return shape), the plan author must verify the claim against the actual source BEFORE writing plan tasks that depend on it. A single Read call per claim eliminates an entire class of plan-review Blockers. The same duty applies when RECEIVING code review: a finding's diagnosis and its proposed remediation are themselves claims about production code (how many sites duplicate a pattern, which module a symbol lives in, what a function returns), and both must be verified against source before the finding is applied or routed.

**Why this matters:** Plan review sub-agents will catch these defects, but every Blocker found in review is a defect the author could have caught with one Read call. Each Blocker forces a revision cycle (re-write the plan, re-launch review, re-verify), costing more rounds than the original verification would have. Plans that ship with N unverifiable claims typically absorb N+ Blockers across the first two review rounds.

**Required behavior:**
1. Before writing any plan task that references a production-code fact (field name, line number, file path, function signature, return type), open the source file and confirm the fact.
2. Field-semantics claims are the highest-risk category: a plan that says "field X carries minute-precision timestamp" must be verified by reading the parser that populates field X. If the parser strips the time component, the claim is wrong and downstream matching logic built on it will fail.
3. Line-number claims drift as the file evolves; cite line numbers only after reading the file at plan time, and prefer function-name anchors over line numbers when the surrounding code is stable. The same applies to inline code comments: name the guarding symbol or feature (e.g. "the fail-fast in the crypto loader") rather than a `file.py:NNN` line, because any edit above the anchor shifts the number.
4. When a user-facing design preference (e.g., "match by timestamp + asset + wallet + amount") implies a code capability (timestamp precision on a domain field), verify the capability exists before accepting the preference. If it does not, surface the trade-off explicitly in the plan's Monitor section rather than silently substituting an alternative.
5. When acting on a code-review finding, verify the finding's OWN claims before applying or routing it: count the sites a "duplication" finding names (grep for the shared pattern across the package, not just the two the finding cites), and confirm any path/function the finding's proposed fix names actually exists and carries the responsibility claimed. A finding can understate scope or propose a wrong target; applying its proposed fix verbatim can write a second wrong path or leave the real duplication in place.

**Distinguishing from #71 / #72:** Lesson #71 covers investigation tasks ("is X handled correctly?") and mandates verification-first task ordering. Lesson #72 extends that to data trace verification. This lesson covers **plan-time claims** about code structure (what a field carries, what a function returns, what line N does) and mandates source verification during plan authoring, before any task is written. The trigger is the author writing a code-reality claim, not the author investigating an existing behavior.

**Anti-pattern:** Writing "the match key is (timestamp, asset, wallet, amount) with minute-precision timestamp" in a plan without checking whether `CryptoCapitalGainEntry.disposal_date` actually carries minute precision. The field is day-level (`format_datetime` at `koinly_parser.py:123-132` strips the time), so the entire matching strategy must be reworked in revision, costing a full review round.

**Example:** The 2026-06-14 derivatives-th-label-cg-dedup plan claimed minute-precision timestamp matching in its Gist, Design Invariant 6, Task 4 test names, and Task 4 implementation note. The r1 plan review caught the field-shape error as Blocker 1 across 4 plan locations. The revision dropped timestamp from the match key and adopted (date, asset, wallet, amount) with strict-equality at 6-decimal rounding, but the cost was one full review round. A single Read of `koinly_parser.py:123-132` during plan authoring would have prevented the Blocker entirely.

**Review-reception example (2026-06-20 branch review):** Two findings made production claims that verification corrected before they were applied. (a) Finding #6 framed a config-loading block as a TWO-way duplication with `classification._load_popular_crypto_tokens`; grepping the package revealed it is THREE-way (`classification.py`, `derivatives_dedup.py`, and `payment_proceeds.py` all mirror the same symlink/size guards over the same JSON), which shifted the right fix from "extract one module" to "share one secure loader." (b) Finding #20's proposed remediation named `src/tax_reporting/domain/crypto_fifo.py` as the FIFO engine; that path is the domain-entities module, not the engine (the engine is the `application/crypto_fifo/` package). Applying the finding's proposed path verbatim would have written a second wrong reference. In both cases a single grep/Read before acting prevented a wrong fix.

**See also:** Lesson #71 (verification-first task ordering), Lesson #72 (data trace verification), Lesson #99 (trace fixture when comparing same-unit fields by name), CLAUDE.md §4 Agent Workflow Rules.

**See also (principle cluster H):** #101 (same family, distinct angle: general plan-claim rule (#100) and its two specific witnesses.).

## 101. Trace Each Affected OGR Row to Its Originating TH Type Before Designing a Type-Filtered Scanner

**Principle:** Family H (Verify the real thing, not the abstraction)

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

**See also (principle cluster H):** #100 (same family, distinct angle: general plan-claim rule (#100) and its two specific witnesses.).

## 102. Add a Count-Matched-Items-Per-Event Safety Check When Matching by Non-Unique Keys

**Principle:** Family G (Data-loss observability)

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

**Principle:** Family D (Single source of truth)

When introducing a separation between two tax categories that previously shared a single pipeline (e.g., splitting a unified crypto-gains flow into spot vs derivatives), audit whether the same disposal event appears in **both** source reports that feed the separated paths. Without an explicit deduplication step removing the now-derivatives-classified items from the spot path, those items are double-counted: once in the new derivatives aggregate, once in the legacy spot aggregate. The trigger for the audit is the **introduction of the separation itself**, not a later data-quality or cross-report validation check.

**Why this happens:** Koinly (and similar exporters) emit one row per disposal event in each report that references it. A derivatives Futures-fee disposal appears both as an OGR `Loss` row (because it has no cost basis, so Koinly routes it to Other Gains) and as a CG lot (because Koinly also records it as a disposal of the fee asset against its acquisition lot). Before the separation, only the CG path was read, so the duplication was invisible. The moment a plan introduces a derivatives path that reads OGR, both paths light up for the same disposal, and the spot CG total silently inflates.

**Required behavior:**
1. When a plan introduces a new classification path that consumes a previously-unused source report (OGR, rewards, etc.), enumerate every other report the existing pipeline already reads (CG, TH).
2. For each disposal event in the new report, check whether the same `(date, asset, wallet, amount)` (or whatever identity tuple applies) also appears in the existing reports.
3. If overlap exists, write an explicit dedup step in the plan that removes the overlapping items from the legacy path. Do not rely on the new path's downstream classifier to "handle" the overlap; the legacy path aggregates independently.
4. Add a reconciliation test that asserts the union of (spot aggregate, derivatives aggregate) matches the pre-separation total. A drift in this union after the separation is the symptom of a missing dedup step.

**Distinguishing from #73 (Cross-Report Validation):** Lesson #73 catches **data corruption** where one report contradicts another (e.g., OGR says Loss while CG says Gain on the same disposal). This lesson catches **structural double-counting** where both reports agree and are individually correct, but the pipeline reads both without dedup. The failure mode for #73 is wrong totals; the failure mode here is inflated totals with no inconsistency between reports.

**Anti-pattern:** A separation plan that says "OGR rows of Type Loss route to `derivatives_entries`; CG rows remain in spot" without checking whether the same disposal is present in both. The spot CG total silently includes the derivatives-classified lots, the derivatives total includes the OGR Loss, and the sum is greater than the pre-separation total. The error surfaces only at tax-filing time when the IRS-ready total is too high.

**Example:** The 2026-06-13 derivatives-separation plan split OGR into derivatives_entries vs spot but did not dedup the corresponding CG lots from the spot table. ByBit USDT Futures-fee and Funding-fee disposals on 2025-01-13 and 2025-01-24 appeared in both: as OGR Loss rows (routed to derivatives) and as CG lots (left in spot). The fix required the entire 2026-06-14 derivatives-th-label-cg-dedup follow-up plan to scan TH for `crypto_withdrawal` events labeled Funding fee / Futures fee / Realized gain, match them against CG lots by `(date, asset, wallet, amount)`, and remove the matched lots from the spot index before the spot/derivatives classifier runs. A 5-minute audit at 2026-06-13 plan time ("does any disposal appear in both OGR and CG?") would have caught the gap and avoided the follow-up plan entirely. See `docs/history/plans/2026-06-14-derivatives-th-label-cg-dedup.md`.

**See also:** Lesson #45 (deduplication key identity), Lesson #73 (cross-report validation), Lesson #101 (trace OGR→TH source Type), CLAUDE.md §3 Repository Constraints (derivatives separation), PT-C-034 in `docs/maintenance/crypto_rules.md`.

## 104. Trace ALL Branches of a Multi-Branch Conditional When Implementing a Tiered Rule

**Principle:** Family H (Verify the real thing, not the abstraction)

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

**See also (principle cluster H):** #120, #109 (same family, distinct angle: plan pseudocode vs tests vs invariants.).

## 105. Calibrate Exception Handling Strategy to the Cost of Silent Failure When Reusing a Helper Pattern

**Principle:** Family B (Error-policy propagation)

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

**Canonical in-repo example:** `src/tax_reporting/infrastructure/json_loader.py::load_guarded_json` is the reference implementation of "inherit the guards, recalibrate exception handling." It centralizes the universally-reusable guards (symlink rejection, existence, strict size cap, `json.load`) but delegates EVERY failure to a caller-supplied `on_error(path, kind, detail)` callback and returns whatever that callback returns. The helper itself never decides degrade-vs-raise and never logs; each of the three callers (`classification._load_popular_crypto_tokens`, `derivatives_dedup._load_derivatives_labels_config_from_path`, `payment_proceeds._load_payment_proceeds_config_from_path`) owns its own `on_error` policy: classification and derivatives_dedup raise on malformed content, payment_proceeds degrades to defaults.

**Anti-pattern:** A plan that says "mirror the error handling of `<source function>`" without checking whether the source function's degrade-vs-raise choice fits the new call site. The implementer copies `except JSONDecodeError: return frozenset()`, the new feature silently no-ops on malformed config, and the user sees a wrong tax total with no error to explain it.

**See also:** Lesson #61 (log silent exception handlers), Lesson #51 (all-or-nothing validation for file sets), CLAUDE.md §1 Instruction Rules (data-loss at warning+, fail clearly), CLAUDE.md §3 Repository Constraints (no silent drops).

**See also (principle cluster B):** #124, #135 (same family, distinct angle: recalibrate policy on reuse (#105) vs raise-not-sentinel + ordering (#124) vs propagate through wrappers (#135)).

## 106. Reuse the Parsed Value Inside the Existing Try Block When Extracting a Second Derived Value

**Principle:** Family E (Temporal / ordering invariants)

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

**Principle:** Family E (Temporal / ordering invariants)

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

**See also (principle cluster E):** #108, #110 (same family, distinct angle: the matcher temporal-invariant triple.).

## 108. Recompute Window-Relative Tolerance After Every Shrink Step in a Two-Pointer Sliding-Window Matcher

**Principle:** Family E (Temporal / ordering invariants)

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

**See also (principle cluster E):** #110 (same family, distinct angle: the matcher temporal-invariant triple.).

## 109. Re-Read RED Test Assertions Against Revised Design Invariants Before Flipping to GREEN

**Principle:** Family H (Verify the real thing, not the abstraction)

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

**See also (principle cluster H):** #104 (same family, distinct angle: plan pseudocode vs tests vs invariants.).

## 110. Re-Run Phase-N Feasibility Scans on the Post-Phase-(N-1) State, Not the Original Input Set

**Principle:** Family E (Temporal / ordering invariants)

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

**See also (principle cluster E):** #107 (same family, distinct angle: the matcher temporal-invariant triple.).

## 111. Grep Across ALL Test Files for Stale Assertions When a Task Changes Data Flow Semantics

**Principle:** Family A (Equivalence-class coverage)

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

**See also (principle cluster A):** #112 (same family, distinct angle: cross-file stale assertions (#111) vs within-file name-vs-body scope (#112)).

## 112. Test Method Names Must Reflect Their Actual Coverage Scope

**Principle:** Family A (Equivalence-class coverage)

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

**Principle:** Family C (Representation: sentinel vs None vs exception)

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

**See also (principle cluster C):** #131, #114 (same family, distinct angle: sentinel string leak (#113) vs `None`-value interpolation (#131) vs test-expectation `None`/`""` (#114)).

## 114. Default-Empty Excel Cell Assertions Must Accept Both None and Empty String

**Principle:** Family C (Representation: sentinel vs None vs exception)

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

**See also (principle cluster C):** #113, #131 (same family, distinct angle: sentinel string leak (#113) vs `None`-value interpolation (#131) vs test-expectation `None`/`""` (#114)).

## 115. Reuse the Production Validator When a Test Asserts Against a Domain-Validity Predicate

**Principle:** Family D (Single source of truth)

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

**Principle:** Family H (Verify the real thing, not the abstraction)

When a verification-only task (e.g., a regression sweep, a "diff scope" check, a Phase 2 final validation) asserts that the cumulative diff should contain a specific file but `git diff <base>..HEAD -- <file>` shows the file is NOT in the diff, first check whether a prior same-session commit already applied the planned change to that file before reporting a scope violation.

**Why this matters:** Execute-plan sessions commit after each completed task. When a plan lists a source file as expected-modified and an earlier task's commit already included the edit (because the edit was naturally bundled with that task's primary change), the file will NOT appear in a later task's incremental diff even though the work was done. Reporting this as a "scope violation" or "missing change" is a false positive; the change exists in the cumulative history, just not in the latest task's incremental slice.

**Required behavior:**
1. When a verification task's "expected files in diff" list does not match `git diff --name-only <base>..HEAD`, run `git log --oneline <base>..HEAD -- <missing-file>` to check whether an earlier commit in the session already touched it.
2. If yes, confirm the change matches the plan's intent by reading the file at HEAD (`git show HEAD:<file>` or Read tool), then mark the verification item as satisfied; the work landed earlier, just not in the most recent task's commit.
3. Only report a scope violation when the file is absent from the entire `<base>..HEAD` range AND the planned change is genuinely missing from the working tree.

**Distinguishing from #100 (plan-time claims):** Lesson #100 covers verifying claims about production code at plan-authoring time. This lesson covers verifying scope at verification/commit time, when the diff inspection happens after multiple commits. The trigger is a mismatch between an expected-files list and an observed cumulative diff, not a plan-authoring claim.

**General form:** Verification tasks that inspect `git diff <base>..HEAD` must interpret "file X is missing from the diff" as "file X was not touched in this session", which requires checking the per-commit history, not just the aggregate diff stat. A file absent from the cumulative diff is genuinely missing; a file absent from the latest task's incremental commit may simply have landed earlier.

**Example:** Task 6 of the 2026-06-15 derivatives-pnl-columns plan listed `docs/maintenance/crypto_rules.md` as an expected file in the diff scope check. The diff `d2eda71..HEAD` did not show `crypto_rules.md`. Investigation showed the prior same-session commit `6083cf1 docs(crypto): extend PT-C-031 with Anexo G Quadro 13 filing routing for derivatives` had already extended PT-C-031 with the Anexo G Quadro 13 routing the plan depended on, so no further `crypto_rules.md` edit was required by this plan. The verification item was satisfied by the earlier commit, not violated. See the implementation log (local) Decision: crypto_rules.md.

**See also:** Lesson #100 (verify plan-time claims about production code), `execute-plan` skill (Phase 2 final validation), CLAUDE.md §4 Agent Workflow Rules.

**See also (principle cluster H):** #55, #122, #128, #129 (same family, distinct angle: the git/docs-state verification cluster.).

## 117. Branch on the Discriminator When Synthesising a Reason for a Multi-Cause Flag

**Principle:** Family A (Equivalence-class coverage)

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

**See also:** Lesson #113 (internal sentinels must not leak to display fields), Lesson #112 (test names must reflect their coverage scope; the missing temporal-validity test is a #112 instance), Lesson #119 (sibling aggregators mirror byte-identical patterns -- distinct sibling-ness unit: aggregators in one module), Lesson #136 (centralized helper across callers with divergent policies -- distinct sibling-ness unit: callers of one helper), CLAUDE.md §1 "Partial or uncertain results must carry an explicit indicator" and "Review flags must include specific actionable explanations, not bare booleans".

## 118. Guard "Take From First Entry" Fields Against Silent Heterogeneity

**Principle:** Family G (Data-loss observability)

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

**Principle:** Family A (Equivalence-class coverage)

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

**Distinguishing from #136 (centralized helper across callers with divergent policies):** Lesson #119 and Lesson #136 both govern sibling code, but address different units of sibling-ness with OPPOSITE prescriptions. #119 is about sibling IMPLEMENTATIONS that should produce the SAME output (two aggregators in one module): they must mirror byte-identical patterns; a divergence silently drops data. #136 is about sibling CALLERS of a centralized seam that have INTENTIONALLY DIVERGENT policies for the same failure kind (one raises, another degrades): each caller's policy arm must be pinned individually; mirroring one caller's policy into another is precisely the bug (it flips a required raise to a silent degrade). #119 says siblings must be identical; #136 says sibling callers must keep their distinct arms pinned and must NOT be copied wholesale.

**General form:** Sibling aggregators that perform the same operation must use the same implementation. Diverging implementations silently produce inconsistent output. The fix is byte-identical mirroring or extraction to a shared helper.

**Example:** Finding #2 (Medium) of the 2026-06-16 derivatives-pnl-columns code review r1 found that `aggregate_derivatives_entries` in `src/tax_reporting/application/crypto/aggregation.py` set `notes=first.notes` while the sibling `aggregate_capital_entries` (same module, lines 283-287) used the `"; ".join(dict.fromkeys(...)) or ""` pattern. For a group with two members carrying notes "manual annotation A" and "manual annotation B", the derivatives aggregator silently dropped "manual annotation B". The fix replaced `first.notes` with `merged_notes = "; ".join(dict.fromkeys(e.notes for e in group if e.notes)) or ""` (byte-identical to the capital-entries pattern). The RED tests `test_aggregate_derivatives_merges_notes_across_group_members`, `test_aggregate_derivatives_notes_empty_when_no_member_has_notes`, and `test_aggregate_derivatives_notes_deduped_and_order_preserved` exercise the merge, empty-input, and dedupe+ordering cases. See the derivatives-pnl-columns branch review r1 (local) Finding #2 and the implementation log (local) Medium 2.

**See also:** Lesson #80 (field aggregation strategy per field type), Lesson #77 (handle duplicate keys by summing, not silent overwrite), CLAUDE.md §1 "Data-loss conditions must be logged at warning+, never debug".

**See also (principle cluster A):** #117 (same family, distinct angle: multi-cause flag within one function (#117) vs sibling aggregators mirror patterns (#119) vs centralized helper across callers (#136). Each body distinguishes itself.).

## 120. Reconcile Plan Pseudocode Against Plan Tests and Design Invariants Before GREEN

**Principle:** Family H (Verify the real thing, not the abstraction)

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

**Second example (2026-06-22 crypto-tests-off-local-fixtures plan, Task 1.5 - literal instruction vs design invariant):** Task 1.5's literal bullet asserted "identical derivatives_entries and capital_entries counts per `(date, asset, platform)` case key" between the real and synthetic fixtures, but Design Invariant #2 stated the synthetic fixture is deliberately a smaller, controlled lot set. The literal bullet would false-fail (real=26 capital entries vs synth=2; no shared case keys by design). The task's HEADER ("shape parity") and Invariant #2 were authoritative; the implementer read the invariant's intent (code-path/dedup-phase + case-structure parity, not numeric count-equality) and recorded the reconciliation in the implement log rather than blocking or retro-editing the fixtures. Same family as the first example, distinct trigger: a literal assertion INSTRUCTION (no pseudocode branch table) whose wording contradicts a stated invariant. The fix is the same - reconcile to the invariant's intent and document - but the detection cue is "the task's literal bullet and its own design invariant cannot both be true," not "pseudocode branches miss an input combination."

**See also:** Lesson #100 (verify plan-time claims about production code), Lesson #109 (re-read RED tests against revised invariants after plan revision), CLAUDE.md §4 Agent Workflow Rules.

**See also (principle cluster H):** #104 (same family, distinct angle: plan pseudocode vs tests vs invariants.).

## 121. Do Not Run `ruff check --fix` on Modules That Re-Export for Backward Compat

**Principle:** Family F (Layering / dependency direction)

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

**Principle:** Family H (Verify the real thing, not the abstraction)

This repo carries a docs/orphan-branch workflow (`docs-branch` skill) and at times a working tree with staged deletions (files marked `D` in the index but still present on disk). In that combined state, using `git stash` to get a transient clean tree for a baseline tool comparison is unsafe: the stash records the staged deletions and the subsequent `git stash pop` did not restore the on-disk content, leaving all affected tracked files missing from the working tree.

**What happened (2026-06-17):** During the zero-basis-review-materiality review-fix session, three `git stash` / `git stash pop` cycles were used to compare `ruff` diagnostics on the edited tree versus the committed baseline. The working tree had 10 tracked files staged as deletions (`D`) but present on disk. The stash cycles dropped all 10 files from the working tree. Recovery was via `git fsck --lost-found` to locate the dangling commit from the last dropped stash, then `git checkout <sha> -- <files>` and `git reset HEAD -- <files>` to unstage. All edits were recovered intact because the stash had captured them before being dropped.

**Required behavior:**
1. For any "compare tool output against the committed baseline" task in this repo, read the committed blob non-destructively: `git show HEAD:<path> | uv run ruff check -` per file. Do NOT stash.
2. If a fully clean checkout is genuinely required, use `git worktree add <tmp> <base>` into a temporary path and remove it afterward. Never `git stash`.
3. Before any `git stash` in this repo, audit `git status` for staged deletions (`D`) and gitignored paths overlapping tracked files; if present, do not stash.

**Related (shell recovery):** The recovery command `git checkout <sha> -- $FILES` failed under zsh because zsh does not word-split unquoted variables (the whole string was treated as one pathspec, "pathspec did not match"). Multi-path git operations must use a quoted array: `files=(...); git checkout <sha> -- "${files[@]}"`.

**General form:** See shared `agent_workflow_guidelines.md` #55 (Non-Destructive Baseline Comparisons). The repo-specific aggravator is the docs-branch orphan-branch workflow combined with staged deletions, which makes the stash/pop failure mode both more likely and more damaging here than in a plain repo.

**See also:** `docs-branch` skill, shared `agent_workflow_guidelines.md` #55, CLAUDE.md/AGENTS.md git-safety bullets.

**See also (principle cluster H):** #116, #128, #129 (same family, distinct angle: the git/docs-state verification cluster.).

## 123. Decision-Point Doc Prose Enumerations Must Match Implemented Code Branches

**Principle:** Family H (Verify the real thing, not the abstraction)

When a decision-point record (or any spec doc) describes a rule as an enumerated list, "N-tier rule", "N-step", or cases (1)-(N), every enumerated item must map to a code branch and every code branch must appear in the enumeration. Count mismatches and missing cases survive code review because each individual bullet reads plausibly in isolation; only a branch-by-branch cross-check catches the drift.

**What happened (2026-06-17):** `DP-013` in `docs/maintenance/tax/decision_points/2025.md` described the zero-basis review gate as a "Three-tier rule" and stated `cost=0 AND proceeds=0` "never flags" unconditionally. But `_build_zero_basis_review_reason` in `src/tax_reporting/application/crypto/fifo_helpers.py` implements four flagging branches, including a `cost=0 AND proceeds < 0` always-flag tier (independent of the threshold), and flags the zero-zero case when the threshold is 0. The fourth tier and the escape-hatch qualifier were both absent from the doc. The omission was found by the documentation review sub-agent, not by the implementer, the plan, or the earlier review rounds.

**Required behavior:**
1. When adding or changing a conditional branch in a rule that a decision-point doc enumerates, update the doc's enumeration (both the count and the cases) in the same change.
2. When reviewing such a change, cross-check each doc bullet against a code branch and each code branch against a doc bullet. Do not trust a "three-tier"/"four-tier" heading or a per-bullet read; count the branches.
3. Apply the same check to test class docstrings that summarize a gated rule (the `TestBuildZeroBasisReviewReason` summary had the same stale "three-tier" wording).

**Why this is distinct from #68:** #68 covers field/flag sync (a TOML boolean needs a dataclass field). This lesson covers prose-enumeration accuracy (the `.md` rule description must list every implemented branch). Both can hold simultaneously: the `.md` and `.toml` sidecars were in sync with the dataclass, yet the `.md` prose was still wrong about the branch count.

**See also:** CLAUDE.md/AGENTS.md decision_points rule (`development_lessons.md` #68), `docs/maintenance/tax/decision_points/2025.md` DP-013.

## 124. In a Per-Row Matching/Correction Loop, Run the Fallible Resolution Before Mutating the Match Structure (and Make It Raise, Not Sentinel)

**Principle:** Family B (Error-policy propagation)

A per-row matching or correction loop typically does two things per row: resolve a fallible value (rate lookup, parse, derived field) and mutate a shared match structure (`deque.popleft`, index pop, counter decrement). If the mutation runs before the fallible resolution, or the resolution returns a sentinel instead of raising, a single bad row either corrupts shared state or escapes the per-row boundary, defeating the "one bad row must not abort the batch" guarantee from #6.

**What happened (2026-06-18):** In the crypto payment-proceeds plan (DP-014), `correct_payment_proceeds` matches each zero-proceeds CG row to a Payment-tagged TH row via a per-key `deque` and infers stablecoin-FMV proceeds through a caller-supplied `rate_fn`. The premortem review agent found that if `rate_fn` returned a sentinel (`None`) when a peg currency had no configured rate, `_infer_proceeds_fmv` would evaluate `amount * None`, raising `TypeError`, which is NOT in the orchestrator's per-row `except (ValueError, KeyError)`, so one missing rate would abort the entire correction loop and every later Payment row would silently keep its phantom loss. Separately, the quality agent verified the safe ordering requirement: the FMV must be computed BEFORE `popleft`, so a caught exception leaves the deque entry unconsumed.

**Required behavior:**
1. A caller-supplied resolution callable (rate function, resolver, lookup) that can fail must RAISE an exception type the per-row boundary already catches. Do not return a sentinel (`None`, empty) that downstream code multiplies, concatenates, or uses unconditionally; a forgotten guard turns `value * None` or `value + None` into an uncaught `TypeError` outside the boundary.
2. In the loop body, execute the fallible resolution BEFORE any irreversible mutation of the shared match structure (`deque.popleft`, index pop, set removal). Mutate only on the success branch. A per-row `try/except` that catches the exception is necessary but not sufficient: if the mutation already happened, the shared structure loses an entry (a matched TH row consumed with no correction applied), silently breaking subsequent 1:1 matches.
3. When designing or reviewing such a loop, write the per-row body in the order: look up the bucket -> resolve the fallible value (inside the try) -> on success, mutate the structure and emit the corrected row; on exception, warn with row identity and emit the row unchanged. Trace what shared state remains if the exception fires at each step.

**Why this is distinct from #6/#102/#107:** #6 says catch per row so one bad row does not discard the dataset; #102/#107 say use a `deque` + `popleft` (never `dict[key] = item`) for collision-safe matching. This lesson adds the within-iteration ordering and the raise-not-sentinel contract that make the per-row catch actually safe when the loop also mutates shared matching state.

**See also:** CLAUDE.md/AGENTS.md "Repository Constraints" (FIFO / partially-matched rules), `development_lessons.md` #6 (row-level catch), #102/#107 (deque matching), coding_guidelines.md sealed-class sentinel variants.

**See also (principle cluster B):** #105, #135 (same family, distinct angle: recalibrate policy on reuse (#105) vs raise-not-sentinel + ordering (#124) vs propagate through wrappers (#135)).

## 125. Discriminating Tests: Assert Properties That FAIL Under the Wrong Implementation

**Principle:** Family A (Equivalence-class coverage)

A RED test that passes against the intended implementation AND against a plausible wrong implementation does not discriminate; it gives a false GREEN. Two recurring shapes: (1) a behavioral property that holds regardless of WHERE a cross-cutting mechanism is attached, and (2) a single OR'd case that lets an implementer exercise one of several independent guards and skip the rest.

**What happened (2026-06-18):** During the r4 confirmation pass on the crypto payment-proceeds plan, the testing agent found two non-discriminating RED tests. (a) The memoization test for `_get_stablecoin_config` asserted only "returns the same `(pegs, payment_tag)` on repeated calls"; that property holds whether `@lru_cache` sits on the resolver or on the reader, and the sibling `_load_popular_crypto_tokens` in `classification.py` actually inverts the placement the plan forbids, yet would satisfy the assertion. (b) The loader degrade test read as one OR'd case ("given malformed JSON, an oversize file, OR a symlinked path"), so an implementer could test one guard (say malformed JSON) and ship without the symlink or oversize guard, including the security-critical symlink rejection.

**Required behavior:**
1. To test WHERE a mechanism attaches (memoization decorator, registration hook, cache), assert a property that only holds at the intended site: `hasattr(target, "cache_info")` and `not hasattr(other, "cache_info")`, or mutate the input between calls and assert the cached function returns stale while the uncached one returns fresh. "Same value on repeated calls" is not discriminating.
2. When a function has N independent guards (symlink, size, format, permission), write N parametrized cases, each asserting its own return value AND its own distinct signal (a WARNING or error message naming that specific failure). A single "A OR B OR C" case lets N-1 guards be absent silently.
3. Before declaring a RED test sufficient, ask: "Could I implement this wrong and still pass?" If yes, add the assertion that fails under the wrong implementation.

**Why this extends #6/#90/#91:** those lessons require edge-case and branch coverage; this lesson requires that each covered case actually binds the implementation to the intended design, not merely to a shape that happens to satisfy the assertion.

**See also:** CLAUDE.md/AGENTS.md "Agent Workflow Rules" and "Testing", `development_lessons.md` #6 (edge cases), #90 (validation coverage), #91 (extracted-helper coverage), #133 (empirically confirm a guard-binding test discriminates by disabling the guard and observing RED).

**See also (principle cluster A):** #134 (same family, distinct angle: principle (#125) vs procedure (#133) vs restore/undo variant (#134). Each body distinguishes itself.).

## 126. Verification Guards That Read a Manifest File Must Fail Closed When the Manifest Is Absent

**Principle:** Family G (Data-loss observability)

A guard command (leak detector, lint check, coverage gate) that reads an external manifest/patterns file and is written as `cmd && echo BAD || echo GOOD` reports GOOD when the manifest is missing. The command exits non-zero on a missing `-f` input (grep: exit 2 "cannot read patterns"), the `&&` branch is skipped, and the `|| GOOD` branch fires: a false pass exactly when the guard cannot run. When the manifest is gitignored (absent in fresh checkouts and CI), that missing-input state is the default outside the author's working tree.

**What happened (2026-06-19):** The crypto payment-proceeds plan's personal-data hygiene guard was `grep -rnf docs/maintenance/personal/personal_data_patterns.txt <tracked files> && echo "!!! LEAK !!!" || echo "clean"`. The patterns file is gitignored (it holds the user's real identifiers), so it is absent in any fresh checkout or CI run. Verified empirically: with a real leak planted and the patterns file absent, `grep -f <missing>` exits 2 and the guard printed "clean". A leak detector that reports success when its own input is missing is the worst failure mode, and the missing-input state is the norm outside one developer's tree.

**Required behavior:**
1. A guard whose input file may be absent MUST fail closed: assert the input exists and is non-empty before the check (`test -s "$PATTERNS" || { echo "CANNOT VERIFY: ..."; exit 1; }`), so a missing input is a loud failure, never a silent pass.
2. Prefer `if grep ...; then echo BAD; else echo GOOD; fi` over `grep ... && echo BAD || echo GOOD`, but note this alone does NOT fix the missing-input case (grep's exit 2 still routes to the else/"GOOD" branch). The `test -s` pre-check is what makes it fail-closed.
3. For any verification step that consumes a gitignored/local-only manifest, treat "the manifest is absent in CI" as the design's normal state and verify the missing-input path itself (a test that runs the guard with the manifest absent and asserts it fails, not passes).

**See also:** `development_lessons.md` #5 (data-loss at warning+, never silent), #113 (internal sentinels must not leak as user-facing values), #125 (discriminating tests).

**See also (principle cluster G):** #127 (same family, distinct angle: guard-fail-closed (#126) vs guard-scan-coverage (#127)).

## 127. Static Guards Must Cover Code Paths Skipped in CI (No Runtime Backstop)

**Principle:** Family G (Data-loss observability)

A test that `pytest.skip`s when its real fixture is absent (common when the fixture is gitignored personal data) is never executed in CI. A defect that would only surface by running that test, for example a hardcoded real identifier or magic value baked into the test, therefore has no runtime backstop in CI. The only thing that can catch it is a static guard (grep/scan), so the static guard's scan list MUST include those skipped test files. A guard that scans only the "obvious" doc/config files and omits the fixture-driven tests leaves the highest-risk files with no protection at all.

**What happened (2026-06-19):** The payment-proceeds plan's personal-data hygiene guard scanned the plan, one unit test, the JSON config, and the domain docs, but omitted the integration test, the capturing-loader test, and the new end-to-end test that the wiring task explicitly adds. Those are precisely the files where a hardcoded real disposal amount or an account-token-bearing filename would land, and the e2e test is skipped in CI (the real Koinly fixture is gitignored-absent), so running it never catches a leak there. The grep guard was the e2e test's only backstop, and the guard did not scan it.

**Required behavior:**
1. When designing a static hygiene/leak guard, enumerate the files where the protected value could realistically land, including test files that consume real fixtures, and put all of them in the scan list, not just the docs/config a reader would name first.
2. For any test that `skip`s when a fixture is absent, recognize it has zero CI runtime coverage and ensure a static guard or a dedicated assertion covers the leak class for that file.
3. Audit the scan list against the task that creates or edits files: every file a task touches that could carry the protected value should be in the guard's list.

**See also:** `development_lessons.md` #111 (grep ALL test files when a data-flow identity changes), #125 (discriminating tests), #126 (fail-closed guard input).

## 128. `git mv <src> <dest>` Nests When `<dest>` Exists; the doc-hierarchy `full` Gate Does Not Catch Intra-Tree Nesting

**Principle:** Family H (Verify the real thing, not the abstraction)

`git mv <src> <dest>` renames `src` to `dest` only when `dest` does not already exist. When `dest` is already a directory, git moves `src` **into** it, producing `dest/<src-basename>/` one level deeper than intended. The doc-hierarchy `full` verify gate does not catch this: its rogue-path scan flags only `docs/<not-allowed>/` top-level trees, so anything under an allowed tree (`docs/history/`, `docs/maintenance/`) passes regardless of how its internal directories are shaped. Files dropped at `docs/history/plans/plans/` instead of `docs/history/plans/` are invisible to the gate.

**What happened (2026-06-19):** During the doc-hierarchy migration, `git mv docs/plans docs/history/plans` ran after `docs/history/plans/` already existed, so all 31 plan files moved to `docs/history/plans/plans/...` (and `completed/` to `plans/plans/completed/`), with nothing at the intended top level. The `full` gate still passed because the nested path sits under the allowed `docs/history/` tree. The defect surfaced only when `bootstrap-ai-playbook` ran next: the hand-authored `plans_completed_dir = "docs/history/plans/completed/"` pointed at a path that did not exist, and bootstrap's on-disk check (does each `facts.md` key's target exist on disk?) rejected it. (The migration-map Step 2 special cases guard this for `reviews/` but not for `plans/` or other directory moves.)

**Required behavior:**
1. Before `git mv <src> <dest>` of a directory into a target tree, check whether `dest` already exists. If it does, move the **contents** into the target (`git mv src/* dest/`) or move then flatten, never the bare directory, or you get `dest/<src-basename>/`.
2. A passing `full` gate is necessary but not sufficient: it checks allowed top-level trees and rogue-path absence, not internal directory depth. After moving directories into an allowed tree, verify contents landed at the intended depth (e.g. `find docs/<tree> -maxdepth N -type f`).
3. Treat `bootstrap-ai-playbook` on-disk path-key validation as the backstop the gate cannot provide: run bootstrap rather than hand-authoring `.ai-playbook/facts.md`, because it fails on, and forces correction of, any key whose target does not exist.

**See also:** `development_lessons.md` #116 (verification-first: inspect actual git state before reporting), #122 (docs-branch / git working-tree hazards), #126 (verification guards must fail closed).

**See also (principle cluster H):** #55, #129 (same family, distinct angle: the git/docs-state verification cluster.).

## 129. Translate Stale Doc Paths in Plans Authored Before a doc-hierarchy Migration, Before execute-plan

**Principle:** Family H (Verify the real thing, not the abstraction)

A plan written before a doc-hierarchy migration keeps the pre-migration prefixes in three load-bearing places: task `Files:` lists, prose code-path literals (e.g. `_REPOSITORY_ROOT / "docs" / "tax" / ...`), and `## Validation Commands` grep targets. Executing such a plan untranslated produces two silent failure modes: sub-agents write to non-existent old locations (`docs/tax/popular_crypto_tokens.json`), and the plan's own validation commands grep against nothing - a false pass with no signal that the gate did not actually run against the migrated tree.

**What happened (2026-06-19):** The DP-014 (crypto payment-proceeds) plan was authored at `3f8e898`, before the three-layer doc-hierarchy migration (`5d085e5`) that moved all `docs/` content under `docs/maintenance/` (plus `docs/plans/` -> `docs/history/plans/`, `docs/reviews/` -> `docs/history/reviews/`). A pre-Phase-1 scan found 38 stale path references across five prefixes (`docs/tax/`, `docs/domain/`, `docs/plans/`, `docs/personal/`, `docs/reviews/`). The orchestrator translated them in a standalone prep commit (28 line swaps, zero logic change) before Task 1, so per-task commits stayed clean and validation targets resolved.

**Required behavior:**
1. Before Step 1.1 of `execute-plan`, when the repo has the migration-complete signal and the plan predates the migration, grep the plan body for the migration's moved prefixes (e.g. `grep -nE 'docs/(tax|domain|plans|personal|reviews)/' <plan>`) and translate every hit to its migrated location. This is `execute-plan` Step 0.4b.
2. Translate segmented code-path literals too (`"docs" / "tax"` -> `"docs" / "maintenance" / "tax"`), not just prose paths, so the literal matches the authoritative source path.
3. Run the plan's `## Validation Commands` once after translation to confirm grep/test targets resolve against the current tree (empty grep output is a false pass, not success).
4. Make the translation its own pre-Phase-1 commit so the per-task commits carry only task logic.

**See also:** `development_lessons.md` #100 (verify cited paths/line numbers against current source before depending on them), #116 (verification-first git-state inspection), #128 (sibling doc-hierarchy migration hazard: `git mv` nesting). Skill home: `execute-plan` Step 0.4b.

**See also (principle cluster H):** #55, #122 (same family, distinct angle: the git/docs-state verification cluster.).

## 130. Pre-Bind Every Local Referenced After a Try Whose Except Continues Rather Than Re-Raises

**Principle:** Family B (Error-policy propagation)

When a `try ... except` block logs and CONTINUES (warn-and-continue, graceful degradation) rather than re-raising, and code after the try reads a local that is assigned only inside the `try`, the local must be PRE-BOUND to a safe default BEFORE the try opens. Otherwise the except path runs to completion without binding the local, and the post-try reference raises `NameError` on exactly the failure path that the warn-and-continue was meant to survive.

**Failure mode:** the bug is latent. The happy path binds the local inside the try, so every test that exercises the success branch passes. The `NameError` fires only when the failure branch (`except`) runs AND control reaches the downstream read - the rare path, usually untested.

**What happened (2026-06-19, DP-014 Task 6):** `_main` in `main.py` had `tax_jurisdiction = None` pre-bound at the top of the function (the safe-default idiom for this warn-and-continue pattern), but the newly-added `app_config` local was NOT pre-bound. The config-load `except (FileNotFoundError, OSError)` branch logs "Config file not found; crypto pipeline will run without jurisdiction filters" and continues. A new downstream call site `rates=app_config.rates if app_config is not None else None` then `NameError`s on `app_config` on the config-missing + Koinly-present path - the very path the except exists to keep working. The fix was a one-line pre-bind `app_config: Config | None = None` next to the existing `tax_jurisdiction = None`.

**Required behavior:**
1. Audit every `try ... except` whose `except` body does NOT re-raise (i.e. logs/warns and falls through). For each, list every name assigned only inside the `try` and referenced after the block.
2. Pre-bind each such name to a safe default BEFORE the try opens, mirroring the existing pre-bind idiom (e.g. `tax_jurisdiction = None` in the same function). A guarded downstream read (`x.foo if x is not None else None`) is NOT sufficient on its own - the `NameError` fires before the `is not None` check.
3. Cover the failure path with at least one test that triggers the continue-branch `except` and then reaches the downstream read. A structural test (assert the call does not raise `NameError`) plus a behavioral test (assert the warn fires and the safe-default path runs) together bind the invariant.

**General form:** This holds for any continue-style exception handler, not just config loading. Whenever you add a new local that a warn-and-continue `try` assigns and post-try code reads, pre-bind it. The local need not be the thing the `try` was originally written to guard - any local added later inside the same try inherits the hazard.

**Distinguishing from #106 (reuse the parsed value inside the try):** Lesson #106 prevents an UNCAUGHT exception by re-invoking a fallible operation outside the try. This lesson prevents a `NameError` by ensuring a local assigned inside a continue-style try is bound on the except path too. Both are error-scope guards but address different failure modes: #106 keeps fallible ops inside the catch scope; this one keeps locals readable on the degradation path.

**Distinguishing from #61 (log silent exception handlers):** Lesson #61 says the degradation must be OBSERVABLE (log it). This lesson says the degradation must be SOUND (every downstream read resolves). A correctly logged warn-and-continue that then `NameError`s is still broken.

**See also:** `development_lessons.md` #61 (log silent exception handlers), #106 (reuse parsed value inside the try block), #105 (reusing a pattern: inherit the guards, recalibrate exception handling). `main.py` config-load block (the canonical pre-bind idiom: `tax_jurisdiction = None`, `app_config: Config | None = None`).

## 131. F-Strings Interpolating a `str | None` Into User-Facing Output Must Degrade Explicitly for `None` (Especially When `None` Is Reached via a Warn-Only Config-Drift Path)

**Principle:** Family C (Representation: sentinel vs None vs exception)

When an f-string interpolates a value typed `str | None` (or `Optional[str]`) into a user-facing string (review reason, Excel cell, log line addressed to the operator), and `None` is REACHABLE through a config-drift path the loader only warns about (does not refuse) - for example, an asset listed in `stablecoins` but absent from `stablecoin_pegs`, so the lookup returns `None` and execution continues to the reason builder - the f-string `f"...{peg}..."` emits the literal Python repr `"None"` into the output (`"no None->EUR rate in config"`), which is nonsensical, unactionable, and indistinguishable from a real value to a non-technical reviewer.

**Why this matters:** The bug is silent and ships correct-looking output. Happy-path tests (peg present) all pass; the `None` branch fires only under config drift, which the loader treats as non-fatal. No exception is raised, so per-row error handling does not catch it. The user sees a reason containing the word `None` and has no idea what to do.

**Required behavior:**
1. Audit every f-string that interpolates a `str | None` into user-facing text. If `None` is reachable (not provably impossible), the f-string MUST degrade explicitly: build a phrase conditional on `None` (e.g. `rate_phrase = f"no {peg}->EUR rate in config" if peg else "no EUR realization rate configured"`), mirroring any sibling phrase that already degrades for the same `None` (in this case `peg_phrase`).
2. When the `None` reachability comes from a warn-only config-drift path (loader logs a WARNING but does not raise), treat the drift case as a first-class code path, not an impossible state. Add a discriminating test that constructs the drift config (e.g. `stablecoins={"GBPX"}, stablecoin_pegs={}`) and asserts the literal substring `"None"` does NOT appear in the emitted reason (this assertion FAILS under the unguarded f-string; see #125).
3. Mirror existing degradation patterns within the same function. If a sibling phrase already handles `None` (`peg_phrase = f"{peg}-pegged stablecoin" if peg else "stablecoin"`), the new phrase built from the same value must degrade the same way; diverging patterns silently emit `None` in the diverging phrase.

**General form:** Any f-string interpolating an `Optional[str]` into output a human reads must not rely on the value being non-`None` unless the type system or an upstream guard proves it. When the value's `None` case is reachable through degradation (warn-only loader, partial config, best-effort lookup), the f-string must branch on `None` with an explicit human-readable phrase, and a test must assert `None` does not leak as a literal.

**Distinguishing from #113 (internal placeholder sentinels must not leak):** Lesson #113 addresses a sentinel STRING returned by a resolver (`UNKNOWN_OPERATOR_REVIEW_REQUIRED`) leaking into display; the value is a `str`, never `None`. This lesson addresses the Python `None` VALUE itself being interpolated via f-string into a string, producing the literal text `"None"`. Different value, different root cause (resolver design vs f-string + reachable `None`), same symptom class (nonsensical text in user output).

**Distinguishing from #130 (pre-bind locals for continue-style try):** Lesson #130 prevents a `NameError` on the degradation path by pre-binding locals. This lesson prevents a silent bad-value emission on the degradation path by branching the f-string. Both are "the degradation path must be SOUND" guards, but #130 is about name resolution and this one is about value rendering.

**What happened (2026-06-19, DP-014 review r1):** `_non_eur_stablecoin_no_rate_reason` in `src/tax_reporting/application/crypto/payment_proceeds.py` built the tier-4 review reason with `peg_phrase` that correctly degraded for `peg is None` (`"stablecoin"`), but the rate portion used a raw f-string `f"AND no {peg}->EUR rate in config"`. Under config drift (asset in `stablecoins`, absent from `stablecoin_pegs` - the loader warns but continues), `peg` is `None` and the reason shipped as `"... AND no None->EUR rate in config - supply the EUR realization value."`. The Medium review finding (r1) added `rate_phrase = f"no {peg}->EUR rate in config" if peg else "no EUR realization rate configured"` mirroring `peg_phrase`, plus the discriminating test `test_drift_stablecoin_missing_peg_does_not_emit_none_literal`. See the review-r1-address log (local).

**See also:** `development_lessons.md` #113 (internal sentinels must not leak), #125 (discriminating tests), #130 (pre-bind locals on degradation paths), #105 (inherit the guards when reusing a pattern). `payment_proceeds.py::_non_eur_stablecoin_no_rate_reason` (the mirrored-degradation idiom: `peg_phrase` and `rate_phrase` both branch on `None`).

**See also (principle cluster C):** #114 (same family, distinct angle: sentinel string leak (#113) vs `None`-value interpolation (#131) vs test-expectation `None`/`""` (#114)).

## 132. A Literal Timezone Token in a `strptime` Format Does Not Populate `tzinfo`; Naive Datetimes from External Reports Are LOCAL Time, Not UTC

**Principle:** Family H (Verify the real thing, not the abstraction)

`datetime.strptime(value, fmt)` sets `tzinfo` only when the format uses `%z`. A literal token in the format string, such as the text `UTC` in `%Y-%m-%d %H:%M:%S UTC`, is matched against the input but does NOT populate `tzinfo`; the result is `tzinfo=None` (naive) for that format too. Code that then unconditionally calls `.replace(tzinfo=UTC)` to "fill in the assumed zone" is correct ONLY for inputs whose format actually declares UTC; applying it to formats that carry a wall-clock LOCAL time stamps the wrong instant.

**Why this matters (latent and season-dependent):** Koinly's Capital Gains / Other Gains / Income reports print `Date Sold` / `Date` as `DD/MM/YYYY HH:MM` with no zone. They are Portuguese local time (WET = UTC+0 winter, WEST = UTC+1 summer), proven by the ~0h offset in winter and ~+1h in summer versus the explicit-UTC Transaction History twins (spring-forward and fall-back jumps both visible in the data). Stamping those dates as UTC means any summer disposal in the 00:00-01:00 local window maps to the PREVIOUS UTC day, drifting every calendar-day cross-report match key (DP-014 payment match, derivatives dedup, OGR override) by a day. Latent only because no live case sits in that window yet.

**Detection methodology (the preventive rule):**
1. When parsing an external date, distinguish EXPLICIT-UTC formats (the format text carries a zone literal like `UTC`, or uses `%z`) from NAIVE formats. `strptime` leaves `tzinfo=None` for both; only the explicit-UTC one MEANS UTC. Detection helper: `_format_declares_utc(fmt)` = the literal `UTC` appears in `fmt`.
2. For naive formats, do NOT assume UTC. Localize to the jurisdiction's IANA zone via `zoneinfo` (it handles DST transitions historically; never hand-code transition days), then convert to UTC for all cross-report match keys. Policy, per the user: a datetime with no explicit zone is LOCAL time even when it coincides with UTC.
3. Resolve the zone ONCE at config load into a `ZoneInfo` value object and thread it; do not re-construct `ZoneInfo` per call. An invalid IANA name fails fast at config load (`ValueError`, which `main()` converts to `ConfigurationError`), matching the surrounding `[TAX JURISDICTION]` validation convention.
4. Leave explicit-UTC formats unchanged; they are already the correct instant. TH parse sites are therefore zone-agnostic.

**General form:** Any external report whose timestamps lack `%z` or an explicit zone must be treated as wall-clock local time, localized to the source/jurisdiction zone, and converted to UTC before joining by date. Never infer a timezone from a literal token in the `strptime` format; it does not populate `tzinfo`.

**What happened (2026-06-20, crypto timezone plan):** `DATE_FORMATS` in `koinly_parser.py` includes `%Y-%m-%d %H:%M:%S UTC` (the only UTC-declaring format) among several naive formats. `parse_koinly_datetime` unconditionally did `parsed.replace(tzinfo=UTC)` at the stamp step, so naive CG/OGR/Income dates were mis-stamped as UTC. The fix (plan: `docs/history/plans/2026-06-20-crypto-timezone-normalization.md`, quality-gated ready) threads a jurisdiction `ZoneInfo` and branches: declared-UTC formats pass through; naive formats localize-then-convert; `zone=None` (default) preserves today's byte-for-byte behavior for backward compat. See the shelved RFC `docs/history/feature-notes/2026-06-20-th-anchored-transaction-state-machine.md` for the real-data DST evidence and the broader TH-anchored transaction design.

**See also:** `development_lessons.md` #105 (reusing a pattern: inherit the guards, recalibrate exception handling), #100 (verify plan claims against source before dependent tasks). `koinly_parser.py::parse_koinly_datetime` (the single normalization point). `docs/maintenance/koinly_guidelines.md` (Koinly export semantics).

**See also (principle cluster H):** #21 (same family, distinct angle: datetime representation traps.).

## 133. Confirm a Strengthened Guard-Binding Test Discriminates by Disabling the Guard and Confirming RED

**Principle:** Family A (Equivalence-class coverage)

When you STRENGTHEN (or add) a test that claims to bind a defensive guard (a non-finite check, a `None`-guard, a bounds/branch guard), the test passing against today's code is NOT proof it binds the guard. A guard's load-bearing case is often a narrow input (e.g. a stablecoin for a stablecoin-only fallback guard); if the strengthened test exercises only a non-load-bearing input, removing the guard changes nothing observable and the test passes either way. The test then gives false confidence - exactly the failure mode of a guard "covered" by a case it does not protect.

**Required behavior:**
1. After strengthening or adding a guard-binding test, temporarily NEUTRALIZE the guard (comment it out, force its condition to the non-guarding value), run the test, and confirm it FAILS (RED) with a symptom pointing at the guard's responsibility. Disable, then RED, is the proof.
2. If the test stays GREEN with the guard neutralized, it does not bind the guard: it is exercising a path where the guard is not load-bearing. Switch the fixture to the load-bearing input and repeat until disable -> RED.
3. Restore the guard and confirm GREEN. The disable/RED then restore/GREEN pair is the empirical proof of discrimination; reasoning alone ("the guard is obviously needed") is insufficient because the non-load-bearing case is not obvious until you remove the guard and watch the test stay green.
4. Prefer the neutralize-and-run check over adding more assertion text: a stronger assertion that still passes with the guard removed binds nothing extra.

**Distinguishing from #125 (discriminating tests):** #125 states the principle - a discriminating test must assert a property that FAILS under a wrong implementation, and asks "could I implement this wrong and still pass?" This lesson is the operational answer for the guard-binding sub-case: empirically DISABLE the guard to answer that question, rather than reasoning about whether the assertion shape discriminates. #125 is about assertion SHAPE (where a memo attaches, N-guards-as-N-cases); this is a verification PROCEDURE (neutralize, run, observe RED/GREEN).

**Distinguishing from #76 (TDD RED-first):** #76 writes a NEW failing test before the fix. This lesson covers STRENGTHENING an existing test that already passes (e.g. adding a parametrized case to widen coverage), where the risk is that the new case does not actually bind the property it claims to - it greens against both the correct and the regressed code.

**What happened (2026-06-20 branch review, finding #1):** The non-finite Net Value guard (`if net_value is not None and not net_value.is_finite():` in `payment_proceeds.py`) was tested only with a non-stablecoin asset. Removing the guard changed nothing for that fixture: `_resolve_proceeds` tier-1 is False for infinity regardless, and a non-stablecoin returns `None` ("not_stablecoin") whether or not the guard runs. The guard is load-bearing ONLY for a stablecoin, where without it a non-finite Net Value would skip tier-1 and route to the EUR-par fallback, silently correcting the row to par instead of leaving it flagged. After adding a stablecoin parametrized case, discrimination was confirmed by temporarily disabling the guard: the stablecoin case went RED (proceeds stayed `0` instead of being corrected to par), while the non-stablecoin case stayed GREEN either way - proving only the new case binds the guard.

**See also:** `development_lessons.md` #76 (TDD RED-first), #125 (discriminating tests), #109 (re-read RED tests against invariants before GREEN). CLAUDE.md §4 Agent Workflow Rules / Testing.

---

**See also (principle cluster A):** #134 (same family, distinct angle: principle (#125) vs procedure (#133) vs restore/undo variant (#134). Each body distinguishes itself.).

## 134. A Restore/Undo Final-State Test Cannot Distinguish "Fired Then Restored" from "Never Fired"; Assert the Intermediate Mutation

**Principle:** Family A (Equivalence-class coverage)

A test that verifies an undo/restore mechanism by asserting the FINAL state is back to its expected value gives a false GREEN when the mechanism never ran in the first place: the final state is identical whether (a) the mutation fired and was correctly restored, or (b) the mutation never fired at all. This is the restore/undo analogue of a guard-binding test that exercises a non-load-bearing input (#133): the assertion shape alone cannot tell you the mechanism is live.

**Root cause that makes it bite silently:** the mutation fires from a separate source whose malformation turns it into a no-op rather than a crash. Concretely (2026-06-20, DP-014 re-zero tests): the OGR override reads rows from an Other-Gains CSV the test built with a helper that wrote European-decimal values UNQUOTED (`-0,01`, `0,01`). Under `csv.DictReader` the decimal comma split each such value into two fields, shifting every subsequent column; `_extract_ogr_gain_loss` then read `Type` as garbage and returned `None`, so the override matched nothing and mutated no entry, silently inert, with no exception. The re-zero tests asserted the Payment row's proceeds were restored to the corrected value; that holds whether the override ran (and was restored) or never ran, so both tests passed for the wrong reason. The CSV-quoting root cause is #35; this lesson is the discrimination failure that root cause produced inside a restore/undo test.

**Detection (assert the intermediate mutation, not the restored final state):** to prove the override/restore mechanism is live, assert a signal that the mutation actually happened at the point of mutation, e.g. a LEGITIMATE (non-payment) row in the same run whose proceeds carry the OGR override (`proceeds = cost + final_gain_loss`), proving the override indexed and matched, separate from the Payment row's restored final state. A restore test that cannot show the mutation happened is binding nothing.

**Required behavior:**
1. Any test asserting a restore/undo final state must ALSO assert that the mutation it restores actually fired on some row in the same run (an intermediate signal), so "never fired" goes RED rather than silently GREEN.
2. Confirm discrimination empirically (#133): temporarily make the source-of-mutation inert (revert the override, or feed it a malformed row) and confirm the intermediate-signal assertion FAILS.
3. For CSV test fixtures carrying European-decimal values, quote them; real Koinly exports quote both amount and value (e.g. `...,USDT,"143,75","140,18",...`). Verify field-to-column mapping with `csv.DictReader` per #35 before relying on the row.

**See also:** `development_lessons.md` #35 (CSV fixture column alignment / quoting), #133 (disable-and-confirm-RED discrimination), #125 (discriminating-test assertion shape). CLAUDE.md §4 Agent Workflow Rules / Testing and §1 Reusable Engineering Rules (European decimal separators).

## 135. A Fail-Fast Exception Raised Inside a Degrade-to-None Wrapper Is Swallowed Unless Explicitly Propagated

**Principle:** Family B (Error-policy propagation)

A fail-fast guard that raises a specific exception (e.g. `ConfigurationError`) does NOT fail the run if the call site is wrapped by a tolerant handler that catches `Exception` (or a broad ancestor) and degrades to a safe default (logs "continuing without X", returns `None`). The degrading wrapper turns the fail-fast raise into a silent skip - the exact incorrect-by-default behavior the guard was added to prevent. The guard is only as strong as the narrowest handler between it and `main()`.

**Concrete incident (2026-06-20/21, crypto timezone fail-fast):** to stop silently treating naive Koinly CG/OGR/Income dates as UTC, the crypto-loading boundary `_load_crypto_tax_report` in `main.py` was given a STRICT guard that raises `ConfigurationError` when crypto data is present and the jurisdiction timezone cannot be resolved (a configured jurisdiction with `timezone is None`, OR no config loaded at all -> `jurisdiction is None`). The guard sits BEFORE the helper's own `try ... except FileProcessingError ... except Exception` (which degrades data/parse errors to "Continuing without crypto data" -> `None`), so it is not swallowed by THAT block. But `_load_crypto_tax_report` is itself called inside `_main`'s report-generation `try ... except Exception as e: raise ReportGenerationError(...) from e`, so without intervention the propagated `ConfigurationError` would be wrapped into a `ReportGenerationError` (wrong type; the contract says config problems surface as `ConfigurationError`). The fix is `except ConfigurationError: raise` clauses placed BEFORE every broader handler on the path: one in `_main`'s report-generation block (essential - stops the `ReportGenerationError` wrapping) and one defensively in `_load_crypto_tax_report` (so any future loader-side `ConfigurationError` is not degraded to a silent skip). Without the `_main` clause the guard still "fired" but the application surfaced a `ReportGenerationError`, masking the config cause; the lesson is that the guard must be traced to `main()`, not just to the nearest function boundary.

**Detection (RED must trace through the wrapper, not stop at the guard):** a guard test that asserts the guard raises (`pytest.raises(ConfigurationError)` against the helper directly) is GREEN regardless of whether an outer wrapper swallows or re-wraps it - it never exercises the wrapper. You need a SECOND test at each outer wrapper boundary that asserts the WRAPPER propagates the right type: here, a `_main`-level test (`test_payment_proceeds_config_missing_warns_then_fails_fast_via_main`) asserts a `ConfigurationError` escapes `_main` (not `None`, not `ReportGenerationError`, not `NameError`). Pair it with a discriminating sibling confirming a plain data error (`ValueError`/`FileProcessingError`) IS still swallowed/`None` - otherwise a "fix" that propagates everything would pass and re-break the tolerant path.

**Required behavior:**
1. When adding a fail-fast raise inside an existing tolerant wrapper, audit EVERY `except` clause on the FULL path from the raise to `main()` (not just the nearest one) and confirm none of them degrades or re-wraps the new exception type. Add an explicit `except <SpecificError>: raise` ahead of each broader handler that would catch it.
2. Prefer a typed exception (a `ConfigurationError`/domain subclass) over a bare `Exception`/`ValueError` for fail-fast conditions; bare types are indistinguishable from the data errors the wrapper is meant to tolerate.
3. Test the propagation at the OUTERMOST wrapper boundary (`_main`/`main`), not only at the guard or the nearest function - and pair it with the "still degrades ordinary errors" sibling so the contract is pinned from both sides.
4. Keep the low-level loader a pure function (testable in isolation with the invalid input) and enforce the application contract at the orchestration boundary; this avoids coupling every parser test to the configuration requirement while still failing the real run.

**See also:** `development_lessons.md` #76 (TDD RED-first; this guard's first RED traced only to the loader, masking the wrapper swallow), #9 (catch specific exceptions, not broad `Exception`), #126 (guards that fail closed when a dependency is absent), #109 (re-read RED tests against current invariants when the design is revised between RED and GREEN - this guard moved loader -> helper and targeted -> strict mid-stream). CLAUDE.md §3 Repository Constraints (optional crypto ingestion is non-blocking - that contract is for DATA errors, not config errors) and `docs/maintenance/project-guidelines.md` rule #6.

**See also (principle cluster B):** #105, #124 (same family, distinct angle: recalibrate policy on reuse (#105) vs raise-not-sentinel + ordering (#124) vs propagate through wrappers (#135)).

## 136. When Centralizing a Shared Helper Across Callers With Divergent Policies, Pin EACH Caller's Policy Arm for the Safety-Critical Kind (Coverage Fixes Are Symmetric)

**Principle:** Family A (Equivalence-class coverage)

When a refactor extracts a shared helper (e.g. a guarded-JSON loader: symlink reject + size cap + `json.load`) that N callers previously duplicated, and those callers have DIVERGENT policies for the same failure kind (one RAISES, another DEGRADES, a third has a mixed raise/degrade split), a characterization test that pins caller A's policy arm for a failure kind does NOT protect caller B's or C's copy of that arm. When a review (or your own audit) finds caller A lacks a characterization test for failure kind K, the same gap exists for B and C: fix it for all of them in the same pass, pinning the MOST SAFETY-CRITICAL kind first (the one whose silent wrong-policy corrupts an aggregate, e.g. a `stat_error` that DEGRADES to empty where the caller must RAISE, leaving a double-counted P&L).

**Why this matters:** centralization is the moment per-caller policies that used to live inline move behind a callback/strategy seam, and the implementer routinely copies one caller's `_on_error`/policy as the template for the next. If caller A's degrade-policy is the obvious template and caller B must raise for the same kind, an unguarded copy flips B's raise to a silent degrade, and EVERY characterization test for B still passes, because no test ever pinned B's raise arm. The bug is latent until the failure kind actually fires in production. Coverage gaps surfaced by centralization are symmetric across the sibling callers; a fix applied to only the caller a reviewer happened to spot leaves the siblings open.

**Qualification gate (when this rule applies):**
- A refactor extracts/centralizes a behavior (guard sequence, parse, validate) that 2+ callers previously duplicated.
- The callers do NOT share one policy: at least two differ on raise-vs-degrade (or raise-vs-skip, warn-vs-fail) for the SAME failure kind.
- At least one failure kind is "safety-critical" in some caller: its silent wrong-policy corrupts an aggregate or drops/double-counts records (not merely degrades a cosmetic default).

**Required behavior:**
1. Enumerate the failure kinds the shared helper can surface (e.g. `symlink`, `oversize`, `stat_error`, `invalid_json`, `bad_shape`, `missing`).
2. Build the caller x kind matrix; for EACH cell decide raise-or-degrade and add a characterization test pinning that arm, prioritizing the raise arm of the safety-critical kind in every caller that must raise.
3. When a review or audit finds a missing characterization test for one caller's kind, immediately check every SIBLING caller for the same kind before closing the finding. A coverage fix is symmetric, not local.
4. For the most safety-critical kind (silent corruption on wrong policy), prefer a test that asserts the raise happens in raise-callers, paired with a test that a degrade-caller yields its documented empty/default with no aggregate corruption, so a wrong-policy copy goes RED in the caller it would harm.

**Distinguishing from #119 (sibling aggregators mirror byte-identical patterns):** #119 is about sibling IMPLEMENTATIONS agreeing when they SHOULD produce the same output. This lesson is about sibling CALLERS of a centralized seam having INTENTIONALLY DIVERGENT policies, where the characterization-test plan must pin each one: here the callers must NOT be byte-identical, so mirroring the wrong one is precisely the bug.

**Distinguishing from #117 (branch on discriminator for a multi-cause flag):** #117 is multiple CAUSES within one function setting one flag. This is multiple CALLERS of one helper, each with its own raise/degrade policy for the same failure kind.

**General form:** Whenever a refactor moves a per-caller policy behind a shared seam, build the caller x failure-kind matrix and pin the raise/degrade arm for each cell, prioritizing the cell whose wrong policy silently corrupts output. A test gap is not a property of one caller: it is a property of the matrix, and the fix must cover the matrix.

**Example (2026-06-21 payment-proceeds refactor plan, DP-014 #6):** the plan centralizes a guarded-JSON loader used by three `application/crypto/` modules that previously each reimplemented the symlink/size/JSON guards, with DIVERGENT policies over the same failure kinds: `payment_proceeds` DEGRADES on every kind (warn + defaults); `derivatives_dedup` RAISES on every kind except `missing` (a silent empty on `stat_error` would leave derivatives P&L double-counted - the exact hazard the raise exists to prevent); `classification` has a mixed split (raises on symlink/oversize/invalid_json/bad_shape, degrades on `missing` and `stat_error`). Review r1 found `classification` lacked a `stat_error` characterization test and the plan was amended to add `test_stat_error_degrades_to_empty`, pinning classification's DEGRADE arm. But the SYMMETRIC gap on `derivatives_dedup` - whose `stat_error` arm is the MOST safety-critical (RAISE, nearest the double-counting hazard) - was missed until review r3 (Medium #1): no test pinned derivatives' `stat_error` raise, so an implementer copying classification's degrade-on-stat_error policy into derivatives' `_on_error` would flip the raise to a silent empty and every Task-6 test would stay green. The fix adds `TestDerivativesLabelsConfig#test_stat_error_raises` alongside classification's degrade test, pinning the arm of the most safety-critical kind in each caller. See the payment-proceeds refactor plan review r3 (local) Medium #1 and r1 Medium #2.

**See also:** `development_lessons.md` #91 (extracted helpers need direct unit tests, not just indirect), #119 (sibling aggregators mirror byte-identical patterns), #117 (branch on discriminator for a multi-cause flag), #111 (grep ALL test files when data-flow semantics change). `docs/maintenance/plan_quality_guidelines.md` Testing Requirements.

## 140. When Renumbering a Colliding Numeric ID in a Doc Corpus, Disambiguate Each Cross-Ref by Context, Not by the Number Alone

**Principle:** Family H (Verify the real thing, not the abstraction)

When a numeric heading (`## N.`) or ID is not unique (a collision: the same number appears on two headings), renumbering ONE of the occurrences is not the end of the work. Every cross-reference that names that number elsewhere (`See ... #N`, `development_lessons.md #N`, `Lesson #N (...)`) must be re-audited, and the audit must decide PER REF whether it intended the FIRST or the SECOND occurrence. The number alone is ambiguous under a collision; the deciding signal is the surrounding text (keywords in the referring sentence, a parenthetical that names a title verbatim, or field/term context).

**Why this matters:** after renumbering, a cross-ref left pointing at the old number is not necessarily DANGLING (the number still exists, on the FIRST occurrence), so a "no dangling refs" check passes clean. But the ref may now point at the WRONG lesson: the one whose keywords the referring text does NOT match. The ref silently re-targets to a lesson it never meant, and no automated check catches it, because the number is still valid. A reader who follows the ref lands on a topically-unrelated lesson and trusts it.

**Required behavior:**
1. Before renumbering, find the collisions: `grep -oE '^## [0-9]+\.' <file> | sort | uniq -d`.
2. For each colliding number N, grep the WHOLE corpus (all `docs/` + `AGENTS.md` + instruction files) for refs to `#N` (in multiple ref forms: `Lesson #N`, `see also #N`, `development_lessons.md #N`, `Merged into #N`, `Distinguishing from #N`, bare `#N` in prose).
3. For EACH ref, classify FIRST vs SECOND by inspecting the referring context: does the surrounding text name the SECOND-occurrence title, its keywords, or its domain terms? A parenthetical naming a title verbatim pins one occurrence. Keywords absent/present is the disambiguator.
4. Re-point only the refs classified as SECOND-occurrence; leave FIRST-occurrence refs untouched. Record the re-pointed COUNT per number.
5. After renumbering, run BOTH a no-duplicate check (`uniq -d` is empty) AND a no-dangling check (every referenced `#N` resolves to a heading). Neither check alone is sufficient: `uniq -d` empty proves uniqueness; no-dangling proves every number exists; NEITHER proves each ref points at the lesson its text intends. The per-ref disambiguation in step 3 is what makes the corpus semantically correct.

**Shape trigger (when to suspect this family):** a maintenance task says "renumber duplicate/relocating headings", "resolve ID collisions", or "deduplicate numbered anchors"; OR a grep for `uniq -d` on `## N.` headings is non-empty; OR a refactor splits/merges numbered guidance and cross-refs exist by number across files.

**General form:** Whenever a numbered or named anchor is not unique and you renumber/relocate one copy, the set of refs to that anchor is not a single homogeneous target. Each ref must be disambiguated against the surviving copies by the CONTEXT of the referring site, then re-pointed only where the context matches the moved copy. Uniqueness and no-dangling are necessary but not sufficient; semantic re-targeting is the actual fix.

**Example (2026-06-21 principle-generalization-system plan, Task 4):** `development_lessons.md` had `## 15.`, `## 16.`, `## 17.` each appearing TWICE (139 headings, 136 unique numbers). The SECOND occurrences were renumbered to #137/#138/#139. Two cross-refs to the colliding numbers existed: `AGENTS.md:109 "See development_lessons.md #17"` whose surrounding text cited `valid_from` audit-only and `service_start_date` matching (the SECOND-occurrence title's keywords) - re-pointed to #139; and `development_lessons.md:922 "Lesson #15 (Excel Column Width)"` whose parenthetical names the FIRST-occurrence title verbatim - left as #15. A no-dangling check passed either way; only the per-ref keyword audit (1 re-pointed, 1 left) made the refs semantically correct. No #16 refs existed. See the principle-generalization-system plan Task 4 implement log.

**See also:** `development_lessons.md` #122 (compare against committed blob, not a stashed transient tree), #111 (grep ALL test files when data-flow semantics change - the doc analog: grep ALL docs when a doc ID moves).

## 141. A Mechanical `str.replace`/`sed` Pass Whose Search String Is a Substring of a Larger Token Silently Corrupts at the Wrong Offset; Verify With a Byte-Level Diff, Not a Match Count

**Principle:** Family H (Verify the real thing, not the abstraction)

When you run a mechanical text-replacement pass (`str.replace`, `sed s/.../.../`, a regex `sub`) over many lines, and the SEARCH string is a SUBSTRING of a larger token that also appears in the text, the engine matches at the FIRST (wrong) occurrence inside the larger token, not at the boundary you intended. The replacement "succeeds" (the count of matches is nonzero, the target substring is gone from the line), but it produced a different string than you meant, silently corrupting data. A pass that counts matches changed, or asserts the search string no longer appears, reports success on a corrupt result.

**Why this matters:** the natural verification for a bulk text edit is "did the search string disappear / did the replacement appear N times". Both pass when the engine matched at the wrong offset, because the substring you searched for WAS consumed - just from the wrong position, leaving the real target intact and the surrounding token mangled. The corruption is invisible to any check that operates on substring presence rather than the exact resulting bytes. The only reliable verification is a byte-level (or line-level exact) diff of the changed lines against the intended result.

**Qualification gate (when this rule applies):**
- You are running a bulk text replacement (string method, sed, regex sub) over multiple sites.
- The search string is a substring of a LARGER token that also appears at the edit sites (e.g. the search is `).)` and the line contains `(#NN).).` where the inner `)` of `(#NN)` precedes the search).
- There is no word-boundary or suffix anchor forcing the match at the intended offset.

**Required behavior:**
1. Before trusting the result, anchor the search to a boundary that forces the intended offset: a line-end anchor (`s/pattern$/replacement/`, or match a SUFFIX of the line rather than an interior substring), a word boundary (`\b`), or a longer search string that is UNIQUE to the intended offset (match `).).$` as a suffix, not `).)` as a substring).
2. After the pass, do NOT verify by "search string count is zero" or "replacement string count is N". Verify with a byte-level / exact-line diff: for each changed line, confirm the resulting bytes equal the intended output (e.g. `od -c` of a representative line tail, or diff the line against a hand-computed expected form).
3. When the replacement is mass-applied and a wrong-offset corruption would compound across sites, sample-verify MORE than one site (the corruption is uniform, so one sample catches it, but confirm the sample is representative of the edit class, not the single site you happened to author the search for).
4. If the first attempt corrupts, revert (`git checkout`) before retrying - do not layer a "corrective" replacement on top of corrupted bytes, which itself can substring-alias.

**Shape trigger (when to suspect this family):** a bulk text edit is described as "normalize N trailing-punctuation sites", "strip a suffix from M lines", "collapse doubled characters"; the search string is short (1-4 chars) and a common punctuation/bracket run; the verification plan is a grep/count rather than a byte diff; the edit sites contain the search string embedded inside a larger token (parenthesized numbers, quoted strings, bracketed refs).

**General form:** Whenever a bulk replacement's search string is a substring of a larger recurring token, the match lands at the wrong offset and every presence/count-based check passes on the corrupt result. Anchor the search to a boundary (suffix, word-boundary, unique longer match) and verify the EXACT resulting bytes, not substring presence.

**Example (2026-06-21 principle-generalization-system plan, review r1 Step 3.3, Finding 5):** normalizing 23 `**See also**` lines that ended with doubled trailing punctuation `).).` (close-inner-paren, stray inner period, close-outer-paren, final period). The first attempt used `str.replace(").)", ")).")`. That search string `).)` matches starting at the inner `)` of the `(#NN)` citation, not at the trailing `).)` suffix, so each line became `(#NN))..` (citation closed early, then two trailing periods) rather than the intended `(#NN)).`. The "replacement happened on all 23 lines" check passed. The corruption was caught only by a byte-level `od -c` of a changed line tail showing `(#59))..` instead of `(#59)).`. Reverted via `git checkout`; the correct fix anchored to the SUFFIX `).).$ -> )).` (unique to the intended offset). See the principle-generalization-system plan review r1 receiving-code-review log, Finding 5.

**See also:** `development_lessons.md` #122 (compare against the committed blob via `git show`/worktree, not a transient stashed tree - the byte-diff analog: a stash-based presence check misleads the same way a match-count check does), #104 (plan pseudocode must be reconciled against plan tests, not the abstraction), #126 (a guard that reads a manifest must fail closed when absent - presence-based checks mislead in a different failure mode, same Family-H theme: verify the real thing), #61 (baseline log the structure - Family G data-loss observability, the observability counterpart to this verification rule).

## 142. A Validation Command That Scans a Shared Parent Directory to Enforce a NEW Convention Will False-Fail on Pre-Existing Legacy Entries; Scope the Assertion to New Work or Explicitly Accept the Legacy Pattern

**Principle:** Family H (Verify the real thing, not the abstraction)

When a plan introduces or tightens a convention (a filename-token suffix, a header shape, a naming pattern) and expresses its validation as a `find`/`grep` over a SHARED parent directory that already contains entries written under the OLD convention, the validator reports failures caused by the legacy entries, not by any defect in the new work. The validator's exit code does not distinguish "the new files violate the convention" from "old files that predate the convention still exist in the same tree." A broad-scope command that PASSES today becomes a FALSE failure the moment the convention is extended and old entries are deliberately left in place (out of scope for this plan).

**Why this matters:** the implementer of the new-convention task runs the plan's validation command, sees `BAD FILENAME TOKEN` (or the equivalent), and faces a false failure whose cause is pre-existing data outside the task's scope. Two wrong responses follow: (1) treat it as a real failure and block the task; (2) "fix" it by retro-editing the legacy entries to satisfy the new convention, silently expanding scope into files the plan declared out of scope. The correct response is to scope the assertion to the NEW entries (or to add an explicit accept-list for the legacy token), so the validator measures only what the task is responsible for.

**Required behavior:**
1. When authoring a plan task that introduces/tightens a convention over a shared directory, audit whether that directory already contains entries written under the prior convention (e.g. `ls` the parent, or `git log --oneline -- <parent>` to see which entries predate this plan).
2. If legacy entries exist and are explicitly out of scope, scope the validation command to the NEW entries: target the new subdirectory/path (e.g. `find resources/source/example/koinly2025* -name '*.csv'`) rather than the shared parent (`find resources/source/example/ -name '*.csv'`); OR extend the accept-pattern to include the legacy token (e.g. `grep -v -E '(_synth\.csv|_example\.csv|<legacy_token>\.csv)$'`).
3. State the scoping decision in the plan body so the implementer runs the NARROW command, not the broad one. A validation command is only authoritative for the task whose scope it matches.
4. If the broad command must remain (e.g. as a repo-wide guard), separate it from the per-task gate: the per-task task PASSES on the narrow scope; the broad command is a known-pre-existing-condition item tracked separately, not a blocker for the new-work task.

**Shape trigger (when to suspect this family):** a plan task says "add new fixtures/files under `<shared-dir>/` following convention X", "assert all `<shared-dir>/*.csv` match pattern Y", "run a hygiene check that files in `<shared-dir>` are synthetic"; AND `<shared-dir>` already contains sibling entries from earlier plans/years/exports that were authored before convention X existed. The trigger is the combination of a NEW convention + a SHARED directory + LEGACY siblings.

**General form:** Whenever a validator scans a container that mixes new-convention entries with legacy entries written under a prior convention, a blanket scan conflates the two populations. The validator must be scoped to the population it is meant to judge (the new entries), or must explicitly enumerate the legacy accept-set; an unscoped scan over the mixed container reports legacy as failure.

**Example (2026-06-22 crypto-tests-off-local-fixtures plan, Task 1 implement, finding flagged for Task 2):** Task 1 authors 10 new synthetic Koinly 2025 fixtures under `resources/source/example/koinly2025*/` with a `_synth.csv` filename-token suffix (Design Invariant #1: synthesis not sanitization). The plan's filename-token hygiene command runs `find resources/source/example/ -name 'koinly_*.csv' | grep -v -E '(_synth\.csv|_example\.csv)$'` across ALL of `example/`. This reports `BAD FILENAME TOKEN` because the pre-existing `resources/source/example/koinly2024/` files use a legacy 10-char token (`xY9kLm2pQr`, `aB3cDn5oEf`) - the exact pattern the new invariant forbids. koinly2024 is out of scope (an established pattern this plan extends), so all 10 NEW `koinly2025*` files pass the narrow `_synth.csv` check while the broad command false-fails on the legacy 2024 siblings. Task 2 must scope its hygiene assertion to the new dirs OR accept the koinly2024 legacy token. See the crypto-tests-off-local-fixtures plan Task 1 implement log, Findings to flag for downstream tasks #1.

**See also:** `development_lessons.md` #111 (grep ALL test files when data-flow semantics change - the inverse scoping hazard: there you must WIDEN scope to catch stale siblings; here you must NARROW scope to avoid false-failing on legacy siblings; both are Family-H "verify the real thing, at the right population"), #100 (verify plan claims against actual source before dependent tasks - the plan-time analog: the plan AUTHOR should catch the mixed-directory hazard before the implementer runs the broad command).

## 143. When Migrating a Test Off a Real Fixture to Synthetic Data, Narrow Assertions to the Behavior Under Test, Not Orthogonal Flags the Fixture's Synthetic Identifiers Incidentally Flip

**Principle:** Family H (Verify the real thing, not the abstraction)

When a test is migrated off a personal/gitignored fixture to committed synthetic data, the synthetic fixture uses deliberately unmapped or generic identifiers (fabricated wallet/platform names not in any operator map, placeholder tokens). Unmapped identifiers flip orthogonal downstream signals that the real-fixture version never exercised: a platform-mapping resolver returns `review_required=True` / `UNKNOWN_...` for every unmapped platform, so every row under the synthetic fixture carries a review flag that the real-fixture version (with mapped platforms like ByBit) set to `False`. If the migrated test keeps asserting the OLD flag value verbatim, it fails for a reason unrelated to what the test is verifying; if the implementer then "fixes" it by deleting the assertion entirely, the load-bearing invariant the assertion protected is lost.

The migrated assertion must be RE-SCOPED to the property the test actually exists to verify (the classification KIND, the routing path, the dedup phase), expressed in a form that is independent of the orthogonal signal the synthetic fixture flips. Assert the classification kind ("the row is routed as Derivatives, so the Ambiguous-classification reason text is absent from `review_reason`") rather than the unrelated flag ("`review_required` is False"). Record why the flag flips under synthetic data and why the re-scoped assertion still proves the original invariant, so a future reader does not mistake the relaxation for a weakened check.

**Qualification gate (when this rule applies):**
- You are migrating a test that read personal/real fixture data to committed synthetic data with deliberately unmapped or generic identifiers.
- The synthetic fixture causes a downstream signal (review flag, sentinel value, resolver status, validation warning) to flip relative to the real fixture because the identifiers are unmapped/placeholder.
- The pre-existing assertion checked that orthogonal signal as a side property, not as the test's primary purpose.

**Required behavior:**
1. Before copying an old assertion verbatim into the migrated test, identify which downstream signals the synthetic fixture's unmapped identifiers will flip (run the test once under the synthetic fixture and inspect every field the assertion reads).
2. For each flipped signal, decide: is this signal what the test is VERIFYING (keep, recompute against synthetic data), or an orthogonal side property (re-scope to the primary invariant, do not assert the flag value).
3. Express the re-scoped assertion on a discriminator that the primary behavior sets independently of the orthogonal flag (e.g. assert a classification-specific reason string is absent, or a routing-path log message fires, rather than asserting the review flag is False).
4. Document the re-scoping in a test comment: name the orthogonal signal, name the synthetic-identifier cause, and state the primary invariant the narrowed assertion still proves. A silent relaxation reads as a weakened check; a documented one reads as a correct migration.

**Shape trigger (when to suspect this family):** a test migration off a real/personal fixture to synthetic data; the synthetic data uses obviously-fabricated identifiers (wallet names like "Demo ...", placeholder tokens); an old assertion on a `review_required` / validation / resolver-status flag starts failing after the migration; the test's NAME or docstring describes a classification/routing/dedup behavior, not the flag itself.

**General form:** Whenever a fixture change causes an orthogonal downstream signal to flip and a test asserts that signal as a side property, the migrated assertion must be re-scoped to the primary behavior under test, not weakened by deletion. The discriminator the primary behavior sets (independent of the flipped signal) is the correct assertion target.

**Example (2026-06-22 crypto-tests-off-local-fixtures plan, Task 3):** `TestByBitCase2Trace` and sibling classes in `tests/end_to_end/test_crypto_derivatives_separation.py` asserted `review_required=False` (and absence of `"YES:"`) on derivatives rows, which held under the real fixture because `ByBit` is a mapped operator platform. The synthetic fixture uses `Demo Futures` / `Demo Spot` wallets, deliberately unmapped, so `resolve_operator_origin` returns `review_required=True` (the CRG-016 platform-mapping signal) for every row. The tests' PURPOSE is derivatives-vs-spot CLASSIFICATION (the OGR classifier routes as clean Derivatives, not Ambiguous), not the platform-mapping flag. The migration relaxed `assert not entry.review_required` to `assert "matches CG disposal" not in entry.review_reason` (the Ambiguous-classification reason text is absent), asserting the classification KIND without conflating it with the platform-mapping flag. The OGR-handler log message `"routed to derivatives by row type; no CG counterpart"` (fires only on clean Derivatives classification with `cg_matches == 0`) confirms the post-dedup state. No production change was needed. See the crypto-tests-off-local-fixtures plan Task 3 implement log, Decision A.

**See also:** `development_lessons.md` #117 (branch on the discriminator when a flag has multiple causes - the production-side analog: here the discriminator is used in the TEST assertion, there in production message synthesis), #113 (sentinel/`UNKNOWN_...` must not leak into display fields - the synthetic fixture flipping this signal is exactly the case #113 guards against in production; the test must not assert around it by hard-coding the flag), #42 (tests verifying "YES:"/"NO" rendering must set `review_required` / `review_reason` explicitly on the fixture entry - the fixture-authoring counterpart: when you DO want to assert the flag, set it explicitly rather than relying on the fixture's incidental value), #109 (re-read each RED test against current design invariants before flipping GREEN - the re-scoping decision belongs in that re-read pass).

## 144. check-no-em-dash.sh "touched" Only Checks Unstaged/Untracked Files; Verify Committed Files by Diffing Against the Target Branch

**Principle:** Family H (Verify the real thing, not the abstraction)

When using incremental check/lint scripts (such as `check-no-em-dash.sh` or local pre-commit checks) during code review or branch validation, invoking them with a `"touched"` mode (which typically queries git for unstaged, staged, or untracked changes) only scans files currently modified in the working tree or index. If files have already been committed to the feature branch, they are no longer considered "touched" by these commands. Running the check-in-touched mode on a clean working tree will result in a false green pass, silently skipping validation for all changes introduced in the branch's commits.

**Why this matters:** When a branch review or validation is performed on a clean branch, running a touched-only check runs on zero files, exiting with success. A reviewer or automated process might assume the branch is compliant, when in fact none of the branch's changes were scanned. This leads to style or formatting violations (like U+2014 em dashes) being merged into the target branch.

**Required behavior:**
1. When validating a branch that may have committed changes (especially in review or post-commit gates), do not rely on `"touched"` or `"unstaged"` filters.
2. Query git to get the list of all files changed relative to the target branch (e.g. `git diff --name-only master...HEAD` or relative to origin/master) and filter to the appropriate extensions.
3. Pass this list of files explicitly to the checker tool (e.g. `check-no-em-dash.sh file $(git diff --name-only master...HEAD)`).
4. For automated or final check tasks in a plan, ensure the plan specifies diffing against the base branch rather than relying on current working-tree state.

**General form:** Incremental checks that filter by working tree state must be widened to diff-against-target when running on committed branch histories. A validation check must run on the actual population of files changed on the branch, not the subset of files currently in flight in the index.

**Example (2026-06-22 crypto-tests-off-local-fixtures plan, review step):** The branch review flagged low-severity em-dash findings in several committed files. Running `check-no-em-dash.sh touched` reported no issues because the changes had already been committed. Explicitly running `check-no-em-dash.sh file $(git diff --name-only master...HEAD)` correctly scanned the committed files and surfaced the em dashes, allowing them to be replaced.

**See also:** `development_lessons.md` #111 (grep ALL test files when data flow changes), #122 (compare against committed blob, not stashed tree), #142 (scope assertions to new work). CLAUDE.md §4 Agent Workflow Rules / No em dash scan.

## 145. A Boundary/Limit Characterization Test Must Hold the Non-Tested Dimension Valid: Use a Fixture That Satisfies Every Orthogonal Invariant at the Exact Boundary Value

**Principle:** Family H (Verify the real thing, not the abstraction)

A boundary or limit characterization test exercises one dimension at its edge (a size cap of exactly `N` bytes that must PASS; a count of exactly `M` items that must be accepted; a string of exactly `L` characters at the length limit). The fixture's *value along the boundary dimension* is the point of the test, but the fixture must ALSO satisfy every OTHER invariant the production path enforces on the same input (parseability, schema validity, encoding, non-emptiness). When the RED-test author reaches for a degenerate filler to hit the exact boundary (`b"x" * N`, an empty/placeholder object repeated `M` times, a string of `L` spaces), that filler violates an orthogonal invariant, so the "passes at the boundary" assertion is unsatisfiable by ANY correct implementation: the boundary dimension says ACCEPT, but the orthogonal invariant says REJECT, and the implementation correctly rejects. The test fails at GREEN for the wrong reason and an implementer who does not recognize the contradiction will either weaken the assertion (destroying the characterization) or contort the implementation to accept invalid input (introducing a real bug).

The fixture content for a boundary test must be chosen so that it would PASS through every non-boundary invariant at that exact size/count/length. For a size boundary on a JSON loader, that means VALID JSON of exactly `N` bytes (e.g. `b"1234567890"` for a 10-byte limit, not `b"x" * 10`). For a count boundary on a list validator, that means `M` valid items, not `M` nulls. The boundary dimension and the orthogonal invariants must be decoupled: vary only the boundary dimension across the boundary-pair tests (at-limit vs over-limit), keeping the orthogonal-invariant satisfaction constant.

**Qualification gate (when this rule applies):**
- You are writing a boundary/limit characterization test: an input set to the EXACT boundary value (size == limit, count == limit, length == limit) where the expected behavior is ACCEPT/PASS.
- The production path enforces at least one OTHER invariant on the same input (must parse, must validate against a schema, must decode, must be non-empty).
- The RED-test fixture reaches for a mechanical filler to hit the exact boundary value (a repeated byte/char, a repeated placeholder object, whitespace padding) rather than content that satisfies the orthogonal invariant.

**Required behavior:**
1. Before writing the boundary-pass fixture, enumerate every invariant the production path enforces on the input (parse format, schema, encoding, non-emptiness, sign, range) in addition to the boundary dimension under test.
2. Choose fixture CONTENT that satisfies ALL of those orthogonal invariants at the exact boundary VALUE. For a JSON size boundary, write the smallest valid JSON of exactly `N` bytes (a bare integer literal, a short valid object) - never a repeated sentinel byte.
3. Keep the orthogonal-invariant satisfaction IDENTICAL across the boundary pair (the at-limit test and the over-limit test differ ONLY in the boundary dimension, not in whether the content is valid). This isolates pass/fail to the boundary check.
4. When a boundary-pass test fails at GREEN despite a correct implementation, FIRST suspect the fixture: trace whether the filler violates an orthogonal invariant the implementation correctly enforces. Do not weaken the assertion until you have confirmed the fixture satisfies every non-boundary invariant.

**Shape trigger (when to suspect this family):** a RED boundary/limit/at-limit test fails during GREEN; the test's fixture is built by repeating a single byte, character, or placeholder to reach the exact limit (`b"x" * N`, `[None] * M`, `" " * L`); the production path parses/validates/decodes the input; the test name or docstring says "at limit passes" or "boundary accepted".

**General form:** A characterization test that pins behavior at a boundary must hold the non-tested dimensions at values that satisfy every orthogonal invariant, so that a pass/fail attributes solely to the boundary check. A degenerate filler that hits the exact boundary value but violates an orthogonal invariant makes the "boundary accepts" assertion unsatisfiable by any correct implementation and forces the implementer to choose between weakening the test and corrupting the implementation.

**Example (2026-06-21 crypto-payment-proceeds-refactor plan, Task 4 GREEN):** `test_size_limit_boundary_at_limit_passes` in `tests/unit/infrastructure/test_json_loader.py` set `size_limit = 10` and wrote `path.write_bytes(b"x" * size_limit)` (10 `x` bytes), then asserted `recorder == []` and `result is not DEGRADED` (i.e. the loader parses the file and does not call `on_error`). But `b"xxxxxxxxxx"` is invalid JSON, so any correct `load_guarded_json` MUST call `on_error(path, "invalid_json", ...)` and return `DEGRADED` - the assertion is unsatisfiable. The boundary dimension (size == limit -> accept) and the orthogonal invariant (content must parse) were confounded by the filler. Resolution: change the FIXTURE ONLY to `b"1234567890"` (exactly 10 bytes, valid JSON parsing to integer 1234567890); no assertion changed. The at-limit test and the over-limit test now differ only in size, not in JSON validity. See the Task 4 implement log "Errors and retries" and lesson #105 (the loader being characterized).

**See also:** `development_lessons.md` #109 (re-read each RED test against current design invariants before flipping GREEN - the re-read pass is where this contradiction is caught), #120 (reconcile plan pseudocode against plan tests and design invariants - the sibling rule for pseudocode-vs-test contradictions, this lesson for fixture-content-vs-invariant contradictions), #143 (narrow assertions to the behavior under test when a fixture flips an orthogonal signal - the migration counterpart: there the fixture is correct and the assertion over-reaches; here the fixture under-reaches and the assertion is fine), #97 (characterization golden value disagreeing with the plan's expected value), #89 (read the implementation before writing edge-case tests). CLAUDE.md §4 Agent Workflow Rules (RED-then-GREEN TDD discipline).

## 146. An `lru_cache`-Decorated Function That Reads a Module Global at Call Time Needs an Autouse Fixture That Rewires the Global AND Calls `cache_clear()` in BOTH Setup and Teardown

**Principle:** Family H (Verify the real thing, not the abstraction)

When the function under test is decorated with `@lru_cache(maxsize=1)` AND reads a module-level global (e.g. `_SOME_CONFIG_FILE` resolved at call time, not at import time), a per-test `monkeypatch.setattr(module, "_SOME_CONFIG_FILE", tmp_path / "f.json")` alone is INSUFFICIENT: the cache holds the RESULT of the previous call (computed against the previous global value), so a stale cached return masks the monkeypatched global entirely. The test would pass against the OLD cached value regardless of what the test wrote to `tmp_path`, producing a characterization test that does not actually characterize the input under test.

The fix is an `@pytest.fixture(autouse=True)` scoped to the test class that performs THREE actions: (1) SETUP rewire the module global to the test's `tmp_path` via `monkeypatch.setattr`, (2) SETUP call `func.cache_clear()` so the call observes the new global, and (3) TEARDOWN (after `yield`) call `func.cache_clear()` AGAIN so a LATER test class or function (outside the autouse scope) can never read a cached value whose underlying global pointed at a `tmp_path` that pytest has already deleted. Without teardown `cache_clear()`, the cache survives the test session pointing at a now-deleted path; the next uncached caller hits `FileNotFoundError` or, worse, a sibling test that forgot its own isolation reads a stale value and silently passes.

**Qualification gate (when this rule applies):**
- The function under test is `@lru_cache`-decorated (any `maxsize`) OR memoized via an equivalent mechanism (`functools.cache`, a module-level dict cache).
- The function reads a module-level global (path, env var, config object) at CALL time, so the cached key does NOT capture the global's value (caching is keyed on the function's arguments, not on the global it transitively reads).
- You are writing tests that change the global's value (or the file it points at) per case to drive different code paths.

**Required behavior:**
1. Add `@pytest.fixture(autouse=True)` on the test class (or module). Use a leading-underscore name (e.g. `_isolate_config`) so Ruff PT019 does not require it as a parameter; do NOT yield a value from the fixture, or Ruff flags an unused injected parameter.
2. In SETUP: `monkeypatch.setattr(module, "_GLOBAL", tmp_path / "f.json")` THEN `module._cached_func.cache_clear()`. Order matters: clear AFTER rewiring is unnecessary (the call re-reads the global), but clearing in setup guarantees no prior cached value survives into the test.
3. In TEARDOWN (after `yield`): restore the original global (monkeypatch's automatic teardown handles this, but explicit restore documents intent) AND call `module._cached_func.cache_clear()` again. The teardown clear is the load-bearing guard against cross-test-class leakage.
4. Each test reconstructs `tmp_path / "f.json"` locally (the path is deterministic given `tmp_path`); do not rely on a yielded value from the autouse fixture.

**Shape trigger (when to suspect this family):** a test monkeypatches a module global and writes a file under `tmp_path`, but the assertion passes (or fails) against a value that does not match what the test wrote; the function is `lru_cache`-decorated; sibling test classes in the same file share the module and the cache.

**General form:** A cached function that reads a module global captures the global's value ONLY transitively (via the cache key, which is the function's arguments). Per-test mutation of the global therefore requires an explicit cache invalidation in BOTH setup and teardown; a single setup clear leaves the cache populated with a stale value for whatever runs next in the session.

**Example (2026-06-21 crypto-payment-proceeds-refactor plan, Task 7):** `_load_popular_crypto_tokens` in `tax_reporting/application/crypto/classification.py` is `@lru_cache(maxsize=1)` and reads the module global `_POPULAR_CRYPTO_TOKENS_FILE` at call time. `TestClassificationTokenLoader` added a `@pytest.fixture(autouse=True) _isolate_token_file` that, for every test in the class: SETUP monkeypatches `classification._POPULAR_CRYPTO_TOKENS_FILE` to `tmp_path / "tokens.json"` and calls `_load_popular_crypto_tokens.cache_clear()`; TEARDOWN restores the original global and calls `cache_clear()` again. Without this, `test_missing_degrades_to_empty` (no file written) could have returned a stale `frozenset({...})` cached by `TestPopularCryptoTokens.test_popular_tokens_cached` running earlier in the session, and the degrade branch would never have been exercised. See the Task 7 implement log "Key decisions / Autouse fixture mechanics".

**See also:** `development_lessons.md` #125 (discriminating tests - mutate the input between calls to confirm WHERE a memo attaches; this lesson is the isolation complement for CHARACTERIZATION tests that must defeat the cache entirely), #133 (confirm a strengthened guard-binding test discriminates by disabling the guard), #89 (read the implementation before writing edge-case tests - the `lru_cache` decorator and module-global read are visible in the function signature/source and must be read before authoring the fixture). CLAUDE.md §4 Agent Workflow Rules.

## 147. execute-plan `done` docs-branch step: use ONLY the canonical script; `git add -A` / `git checkout docs -- .` on the feature branch stages gitignored docs onto the feature commit

**Principle:** Family H (Verify the real thing, not the abstraction)

The `done` skill's docs-branch step backs up gitignored docs (`docs/tmp/`, `.ai-playbook/`, `docs/history/reviews/`) to the `docs` orphan branch. Those paths are gitignored on the FEATURE branch but tracked on the docs branch, so the two lines of history are intentionally disjoint. A `done` sub-agent that improvises the backup with `git add -A` or `git checkout docs -- .` on the feature branch crosses that boundary and corrupts the feature branch: `git add -A` stages every gitignored doc into the next feature commit (171 files in the incident below), and `git checkout docs -- .` overlays the orphan-branch tree onto the feature working tree. Both are silent until `git status` is read; a sub-agent that reports "nothing to commit" or "no gitignored content lost" without checking `git status` AND the on-disk `docs/tmp/` is not to be trusted.

**What happened (2026-06-22, DP-014 crypto-payment-proceeds-refactor execute-plan run):** The Task 8 `done` sub-agent ran a non-canonical sequence (`git checkout docs -- .` + `git add -A` + `git commit`) that committed 171 gitignored files onto the FEATURE branch (commit `7790ff3`). It detected the anomaly, hard-reset the feature branch to its clean Task 7 base (`80e5d66`), re-applied the two intended Task 8 files, and re-ran the canonical docs-branch script; the Task 8 commit itself was byte-correct. BUT the `git reset --hard 80e5d66` PURGED `docs/tmp/execute-plan/<PLAN_SLUG>/` from the working tree: the session logs had become tracked via the bad commit's index, and `80e5d66` does not track them, so the reset removed them from disk. The sub-agent reported "manifest does not exist / nothing to update" and "no gitignored content lost" - both wrong. The orchestrator recovered the session logs from git objects (`c73464c`, `b9cfe42`) via `git restore --source=<obj> --worktree -- <path>` (NOT `--staged`). The docs orphan branch tip was also truncated by the mishap (lost 47 files vs `c73464c`); it was repaired in an ISOLATED `git worktree add` on the docs branch so the feature working tree was never touched.

**Required behavior:**
1. An execute-plan `done` sub-agent (Step 1.4 / Step 3.4) must run the docs-branch step using ONLY the canonical script from the `done` / `docs-branch` skill, as a SINGLE shell invocation. Never `git add -A`, `git add .`, or `git checkout docs -- .` on the feature branch.
2. If gitignored docs are accidentally staged or committed onto the feature branch, recover in two stages: (a) hard-reset the feature branch to its pre-mishap base (this restores tracked files but PURGES any gitignored file the bad commit had tracked in its index), then (b) recover the working-tree gitignored files with `git restore --source=<obj> --worktree -- <path>` - NEVER `--staged`. `--staged` re-adds the gitignored files to the index, which is the exact hazard. Identify recovery objects via `git reflog` and the docs-branch history.
3. To repair the docs orphan branch itself (e.g. a truncated tip), use a SEPARATE `git worktree add <tmp> docs` and operate there; the feature working tree and index are never touched by orphan-branch repair. Remove the worktree afterward.
4. After any `done` docs-branch step, the orchestrator must verify (a) `git status` shows ONLY the intended task files on the feature branch (no `docs/tmp/`, no `.ai-playbook/`), (b) `docs/tmp/execute-plan/<PLAN_SLUG>/` still exists on disk with its session logs, and (c) the docs branch tip advanced. A sub-agent's "nothing to commit / nothing lost" claim does not satisfy this gate without the `git status` + on-disk check.

**Shape trigger (when to suspect this family):** an execute-plan `done` sub-agent reports a docs-branch result and the feature-branch `git status` shows gitignored paths (`docs/tmp/`, `.ai-playbook/`) as staged/modified, OR `docs/tmp/execute-plan/<PLAN_SLUG>/` is missing from disk after a `done` step that involved a reset.

**General form:** The docs orphan branch is a SEPARATE line of history whose tree is intentionally disjoint from the feature branch (gitignored on feature, tracked on docs). Any git operation that crosses the two - staging feature-gitignored paths onto the feature commit, or overlaying the docs tree onto the feature working tree - corrupts the feature branch. The canonical docs-branch script exists precisely to keep the two disjoint; improvising the crossing is the hazard.

**See also:** `development_lessons.md` #122 (docs-branch `git stash` hazard - same family, distinct angle: stash vs add-A/checkout), #128 (`git mv` nesting in the doc tree), #129 (stale plan paths after doc-hierarchy migration), #116 (verify actual git state before reporting - the "nothing lost" false report is a #116 failure). `docs-branch` skill, `done` skill, `execute-plan` anti-pattern table. CLAUDE.md "Gitignored docs safety".

## 148. Standalone Withdrawals Tagged Cost/Loan Fee Represent Taxable Disposals; Distinguish from Validator/Network Fees Using TxHash Co-occurrence

**Principle:** Family A (Equivalence-class coverage)

When implementing filters to exclude transaction/network fees (Koinly tag `Cost` or `Loan fee`) from capital gains reporting, be careful not to filter out standalone withdrawals that represent taxable disposals for service consideration (e.g. card subscriptions or service fee payments). Under jurisdictions like Portugal, while utility network/gas fees are non-taxable due to lack of direct consideration (CIRS Art. 10(1)(k)), spending crypto to purchase card services or subscriptions is a taxable *alienação onerosa* (PT-C-004) and must remain in the capital gains report.

**Required behavior:**
1. Do not filter out `Cost`/`Loan fee` rows blindly.
2. Build a frequency count of all non-empty transaction hashes (`TxHash`) from the Transaction History CSV.
3. A `Cost` or `Loan fee` withdrawal row is only classified as a utility network/gas fee if it has a non-empty `TxHash` that appears **at least twice** in the Transaction History CSV (co-occurring with a parent transaction, such as a trade, deposit, or transfer).
4. Standalone rows with unique or empty `TxHash` values must be kept as taxable disposals.

**Shape trigger (when to suspect this family):** filtering transaction fees based on cosmetic tags; the data contains both validator gas fees and service payments; some service payments are wrongly filtered out, creating under-reporting of capital gains.

**General form:** Filter logic targeting transaction costs based on broad tags must verify that the fee is a secondary utility charge co-occurring with a primary trade/transfer rather than a standalone payment. Using transaction ID/hash co-occurrence prevents broad tag matches from filtering taxable service purchases.

## 149. Never Proceed to Plan Execution or Make Code Changes Without Explicit User Approval in Planning Mode

**Principle:** Family H (Verify the real thing, not the abstraction)

In Planning Mode, once an implementation plan has been written and reviewed (even if it has zero blocker or medium findings and is marked "Ready for execution"), the agent MUST stop and wait for the user's explicit approval before making any code modifications or running execution commands.

**Why this matters:** Planning Mode is designed to align the agent and the user on the technical design and scope before any changes are committed or codebases modified. Assuming execution is authorized just because a plan is complete or marked ready (the abstraction) bypasses the user's control. Only the user's explicit command to proceed (the real instruction) authorizes execution. Bypassing the approval gate violates user intent and creates unwanted code churn or incorrect implementations that must be reverted.

**Required behavior:**
1. Once a plan has been written and its reviews complete with zero Blocker and Medium findings, present the execution handoff to the user.
2. Stop tool execution and wait for the user to explicitly say "proceed", "execute the plan", or similar.
3. Do not run any implementation tasks, write any product code, or modify production files until that explicit approval is received.
4. If code changes were made prematurely, immediately stash or revert them to return the repository to a clean state matching the approved design base.

**Shape trigger (when to suspect this family):** planning a task under Planning Mode; the plan file is written and reviewed; the next step in the workflow is execution; the user has not yet explicitly authorized execution.

**General form:** The completion of a planning phase (a green review, a ready status) is an abstraction representing preparedness, not an authorization to execute. Authorization requires verifying the real human intent (an explicit command to proceed). Executing code modifications based on the ready state alone violates the gating protocol and introduces code churn.

**Example (2026-06-23 filter-transaction-fees plan):** The agent was tasked with planning transaction fee filtering under Portugal rules. After the plan reviews finished with zero blockers/medium findings, the agent immediately proceeded to execute the tasks (updating config, creating config tests, implementing filtering) without waiting for user approval. The user corrected the agent, requesting that all premature changes be reverted or stashed and that no code changes be made until authorized. The agent stashed/reverted the changes to return HEAD to `5847e2a docs: update plan to reference r2 review` and halted for approval.

**See also:** `development_lessons.md` #116 (verify actual git state before reporting), `development_lessons.md` #100 (verify plan-time claims before writing tasks), `AGENTS.md` "Agent Workflow Rules".

## 150. Multi-Type Configuration Loading in Single-File Schema Requires Explicit Type-Dispatching and Scoped Default Fallbacks

**Principle:** Family D (Single source of truth)

When expanding a configuration loader (such as parsing a flat country-specific TOML config) to support non-boolean fields (e.g. subtable dictionaries `dict[str, Decimal]`), utilize explicit type-dispatching via `get_type_hints` and `get_origin` rather than assuming all values under a section share a single primitive type. Ensure default-value loops are strictly scoped to the matching type hint (e.g. only defaulting boolean fields to `False`) to avoid clobbering or type-checking crashes on missing optional fields.

**Why this is required:** If a config parser loop assumes all config values are booleans, adding a complex type (like a subtable dictionary) will cause the validation step to crash with a `ValueError` or `TypeError`. Furthermore, if the loader's fallback loop unconditionally defaults all absent keys to `False`, it will overwrite the class-level default factory (`default_factory=dict`) of the new dictionary field with `False`, breaking the configuration for any other entry that does not explicitly declare the new subtable.

**Required behavior:**
1. Retrieve type hints for the target config class using `get_type_hints(ConfigClass)` and determine type groups (e.g., bool-typed fields vs generic dict fields via `get_origin(hint) is dict`).
2. Rewrite the validation loop to branch explicitly on type groups, performing the correct validation and conversion for each group (e.g., converting dict floats/ints to `Decimal` using `Decimal(str(v))`).
3. Limit any default fallback logic (e.g., setting unset flags to `False`) strictly to the matching type group (e.g., only iterating over boolean-typed fields), allowing other complex fields to default via their standard dataclass defaults or factories.
4. Add config unit tests validating both the presence of the new type and its correct fallback to defaults when absent.

**Shape trigger (when to suspect this family):** introducing a non-boolean config flag to an existing flat configuration class that historically assumed all fields are boolean; the parser validation loop or defaults fallback crashes or incorrectly resolves the new field.

**Example (2026-06-23 filter-transaction-fees plan, Task 1):** The TOML config loader in `config.py` was generalized to accept `dict[str, Decimal]` for `exclude_transaction_fee_max_eur_per_asset`. Sibling fields were bools, and the existing validation loop crashed on the dict subtable. Additionally, the default-value loop originally set all missing keys to `False` by default, which collapsed the new dict field to `False` when missing in non-PT country configs. Dispatched bool-specific defaulting strictly to bool-typed fields, allowing dict fields to fall back to `default_factory=dict`.

**See also:** `development_lessons.md` #68 (Decision Point Flags Require TaxJurisdictionConfig Field), #74 (Verify imports on cross-module calls).

## 151. Use Type Parameterization (TypeVar) in Shared Generic Primitives to Preserve Subclass Field Visibility Under Static Analysis

**Principle:** Family B (Type-safe domain logic)

When extracting a shared utility or matcher that operates on polymorphic event models, parameterize input sequences and return structures with generic type variables (`TypeVar("E", bound=ParentProtocol)`) rather than generic parent types. This preserves concrete attribute visibility (like custom fields used only by specific callers) at caller sites under strict static analysis (basedpyright) without needing explicit type-casting or runtime checks.

**Why this is required:** If the shared matcher is typed to accept and return generic parent models (like `ThEvent`), the caller receives the generic type. If the caller then attempts to read subclass-specific fields on the returned results (like `event.label` in derivatives-dedup), the static type checker will raise diagnostic errors because `label` is not part of the generic parent. Using `TypeVar("E", bound=ThEvent)` forces the type checker to bind the return type to the concrete type passed by the caller.

**Required behavior:**
1. Define a generic type variable bound to the parent protocol/class (e.g., `E = TypeVar("E", bound=ThEvent)`).
2. Parameterize both the input events sequence (`events: Sequence[E]`) and the generic matcher result structure (`MatcherResult[E]`) with that type variable.
3. Expose matching functions using this generic parameterization so that basedpyright propagates type inference cleanly back to the caller.
4. Do not reference subclass-specific attributes (like `event.label`) inside the generic matcher; keep internal algorithms strictly scoped to the parent protocol.

**Shape trigger (when to suspect this family):** extracting a shared algorithm/matcher that processes different subclassed events; caller code reads custom attributes from the matched events; static analysis reports attribute-missing errors at the caller site after extraction.

**Example (2026-06-23 filter-transaction-fees plan, Task 2):** The fee-filter and derivatives-dedup matchers share the exact same two-phase matching algorithm. When extracting `th_lot_matcher.py`, the result structure `MatcherResult` was parameterized with `TypeVar("E", bound=ThEvent)`. This allowed the derivatives caller to access `event.label` (which is specific to `DerivativesThEvent` and absent from the base `ThEvent` protocol) on the returned matched metadata without raising basedpyright diagnostic errors.

**See also:** `development_lessons.md` #8 (Specific type annotations for generic collections), #86 (circular imports during helper extraction), #119 (shared matcher extraction constraint).

## 152. Decouple Pipeline Stages to Keep Correction Modules Single-Responsible and Prevent Flag Clobbering

**Principle:** Family A (Equivalence-class coverage)

In multi-stage data processing pipelines, run data corrections and value recovery (which can change properties like proceeds from zero to non-zero, making parse-time flags/reasons obsolete) *before* applying manual review or auditing flags. Do not introduce complex reason-merging hacks in early processing modules to preserve flags set upstream. Keep modules focused on their single responsibility and run flagging passes last in the pipeline.

**Why this is required:** If a flagging pass runs before a value-recovery pass, the recovery pass (e.g., resolving zero proceeds to non-zero) will either clobber the flag's review reason, or be forced to join it. Unconditionally joining reasons clobbers the clean output by preserving obsolete parse-time reasons (like "Zero disposal proceeds" on a row whose proceeds have now been corrected to a non-zero value), producing self-contradictory output (e.g., "Zero disposal proceeds; proceeds recovered EUR 5").

**Required behavior:**
1. Structure the processing pipeline so that all value corrections (such as OGR overrides and payment proceeds corrections) execute first.
2. Execute auditing, manual-review flagging, and suspect-identification passes last (before aggregation and materiality filtering).
3. This late-flagging approach guarantees that flags are set on clean, final data, eliminating the need to modify correction modules or construct fragile reason-joining strings.
4. Keep the correction modules strictly decoupled from upstream flagging concepts, preserving single responsibility.

**Shape trigger (when to suspect this family):** a pipeline correction step clobbers an upstream audit flag; you find yourself writing complex string-joining logic inside a value-correction module to preserve a reason set upstream; the joined reason text ends up stating contradictory facts (such as both zero proceeds and recovered non-zero proceeds).

**Example (2026-06-23 filter-transaction-fees plan, Task 4):** In the fee-filter design, running suspect-flagging early meant that `correct_payment_proceeds` (which resolves proceeds on zero-proceeds lots) would overwrite the review reason. An attempt to join reasons unconditionally preserved obsolete parse-time "Zero disposal proceeds" reasons on corrected rows, creating contradictory output. Splitting the pass so that fee removal is early, and suspect-flagging runs late (after `payment_proceeds`, right before aggregation), kept `payment_proceeds.py` completely decoupled from fee-filtering logic and avoided reason-joining entirely.

**See also:** `development_lessons.md` #103 (deduplication of spot vs derivatives), #101 (tracing TH rows to OGR).

## 153. Sentinel for `dict.get` Default Must Exclude All Valid Observed Data Values

**Principle:** Family C (Representation: sentinel vs None vs exception)

When using `dict.get(key, default)` to detect a missing key before passing the value to a parser, the default sentinel must be a value that **cannot appear as a valid, meaningful data value** in that CSV column. Using a value that the data source legitimately emits (e.g., `"0"` for a numeric column that may carry explicitly zero-priced data) conflates "key absent" with "key present with value zero", causing the guard `if raw == sentinel: continue` to incorrectly skip valid rows.

**Why this matters:** `"0"` as a sentinel for `"Net Value (EUR)"` worked at first glance because `parse_koinly_decimal("")` returns `Decimal("0")`. But an explicit CSV cell containing `"0"` or `"0.00"` (a genuine zero-priced gas fee that IS supposed to be filtered) is also `"0"`. The guard `if not raw_val or raw_val == "0": continue` incorrectly skips that valid row, silently retaining a taxable disposal that should have been removed. The string `"MISSING"` cannot appear in a numeric column, so using it as the default unambiguously identifies "key absent from dict" without masking `"0"`.

**Required pattern:**
```python
# WRONG: "0" is a valid observed value
raw_val = row.get("Net Value (EUR)", "0").strip()
if not raw_val or raw_val == "0":
    continue  # BUG: also skips genuine zero-priced fees

# CORRECT: "MISSING" cannot appear in a numeric CSV column
raw_val = row.get("Net Value (EUR)", "MISSING").strip()
if not raw_val or raw_val == "MISSING":
    continue  # only skips truly absent/empty cells
```

**Corollary to AGENTS.md Rule #4:** Rule #4 says "use a type-safe sentinel (e.g. `"0"` for numeric fields) rather than `""`". That rule applies to *output/domain fields* (e.g., `CryptoReviewEntry.proceeds_eur = "0"` when absent). For `dict.get` guards where you must distinguish "key absent" from "key present with value zero", the sentinel must be a *non-representable* value (e.g., `"MISSING"`), not a valid numeric string.

**Shape trigger:** a CSV parser uses `row.get(col, "0")` as a default and the column may contain a legitimate `"0"` value; a pre-parse guard checks `raw == "0"` to skip rows.

**See also:** `development_lessons.md` #4 (type-safe sentinels for absent optional fields), `coding_guidelines.md` #4.

## 154. Outer Row-Level Exception Block Must Not Prevent a Trusted-Branch Operation From Completing

**Principle:** Family B (Fail-safe direction and authority hierarchy)

When a row-processing loop uses an outer `try...except` block to catch per-row errors and skip malformed rows, any operation inside that block that is governed by a higher-authority signal (e.g., an explicit user tag that overrides the fiat value) must be wrapped in a **separate nested `try...except`** for its fallible sub-operations. If the trusted operation depends on a non-authoritative field (like a fiat price cell) that may be corrupted, a `ValueError` from that sub-operation will propagate into the outer except and skip the entire row, including the trusted operation that should have executed regardless.

**Required pattern:**
```python
for row in rows:
    try:
        label = row.get("Label", "")
        if label in TRUSTED_TAGS:
            # fiat value is NOT the authority -- use nested except so corruption
            # does not abort the trusted-branch FeeThEvent emission
            try:
                net_eur = parse_koinly_decimal(row.get("Net Value (EUR)", ""))
            except ValueError:
                logger.warning("Corrupted fiat on trusted-tag row %s; defaulting to 0", row)
                net_eur = Decimal("0")
            emit_fee_event(...)   # always emits, even if fiat was corrupted
        else:
            # non-trusted branch: parse fiat normally; ValueError propagates to outer
            raw_val = row.get("Net Value (EUR)", "MISSING").strip()
            if not raw_val or raw_val == "MISSING":
                continue
            net_eur = parse_koinly_decimal(raw_val)  # ValueError -> outer except -> skip row
            ...
    except (ValueError, KeyError, InvalidOperation):
        logger.warning("Skipping malformed row: %s", row)
```

**Shape trigger:** an outer row-level `try...except` exists; a branch inside that block has a "trusted" path (e.g., the tag is the authority) that must complete even if a secondary field raises; the plan says "corrupted data must still raise" but also "the trusted branch still emits the event" -- these two requirements are contradictory without a nested except.

**Why this matters:** Without the inner except, a corrupted fiat string on a tagged `Cost` row causes the outer except to skip the whole row, silently retaining a legitimately-tagged gas fee disposal in the capital gains output (silent over-tax error).

**See also:** `development_lessons.md` #9 (catch specific exception types), `coding_guidelines.md` #5 (warn-and-skip for row-level errors).

## 155. Use `get_args(hint)` Not `get_origin(hint)` for Precise Generic Type Dispatch in Config Loaders

**Principle:** Family D (Single source of truth / precision)

When a config loader needs to discriminate `dict[str, Decimal]` fields from `dict[str, str]` or other dict-typed fields using Python's `typing` reflection, `get_origin(hint) is dict` matches ANY `dict[K, V]` annotation regardless of its type arguments. If a future field of a different dict type (e.g., `dict[str, str]`) is added to the config dataclass, the loader will incorrectly attempt to convert its values to `Decimal`, crashing or silently producing wrong types.

**Use `get_args(hint) == (str, Decimal)` for exact type-argument matching:**
```python
from typing import get_args, get_type_hints
from decimal import Decimal

hints = get_type_hints(TaxJurisdictionConfig)
_KNOWN_DICT_POINTS = {
    name for name, hint in hints.items()
    if get_args(hint) == (str, Decimal)  # precise: only dict[str, Decimal]
}
# _KNOWN_BOOL_FLAGS uses: hint is bool
```

**Corollary:** When the conversion step stores the result back into the dict (which it must -- see lesson #156), explicitly overwrite with the converted values: `flags[flag_name] = {k: Decimal(str(v)) for k, v in flag_value.items()}`. Merely instantiating Decimals during validation without storing them leaves raw TOML floats in the dict.

**Shape trigger:** a config loader type-dispatches on `get_origin(hint) is dict`; a new `dict[K, V]` field with a different value type is added; the loader silently applies the wrong conversion.

**See also:** `development_lessons.md` #68 (decision-point config flag type dispatch), #150 (multi-type config loading requires explicit type-dispatching).

## 156. Matching Event Fields Must Mirror the Normalization Applied to Domain Entry Fields

**Principle:** Family D (Single source of truth / consistency)

When constructing "event" objects whose fields will be matched against "domain entry" objects via a tuple key (e.g., `(timestamp, asset, wallet, amount)`), every field in the event must use the **same normalization** as the corresponding field in the domain entry. Normalizing one side (e.g., stripping " (Spot)" from the wallet name to produce "ByBit") but not the other (which retains the raw "Bybit (Spot)") causes the exact-match key to never equal, silently failing ALL matching for platforms where the raw name differs from the normalized name.

**Required pattern:**
```python
# WRONG: normalize_platform_name strips suffixes the CG lot still carries
event = FeeThEvent(wallet=normalize_platform_name(row.get("Sending Wallet", "")), ...)

# CORRECT: use the raw string to match the CG lot's raw wallet
event = FeeThEvent(wallet=row.get("Sending Wallet", "").strip(), ...)
```

**Verification step:** when introducing a new event-vs-domain matcher, grep for how the domain entry's wallet field is populated; if it stores the raw CSV value, the event must too.

**Shape trigger:** a shared matcher is extracted that uses a tuple key to match events against domain entries; the event scanner applies a normalization function to one field; tests using simple fixture data pass because all wallets are plain strings, but production data (with e.g. Koinly's "(Spot)" suffix) silently fails to match.

**Why this matters:** The failure is silent: no error is raised, no warning is emitted, the CG lot simply remains in the output uncorrected. With a 100% miss rate for affected platforms, the over-tax impact is proportional to the number of fee disposals those platforms have.

**See also:** `development_lessons.md` #77 (duplicate key handling in index builders), #102 (collision safety checks in matchers).

## 157. Type Heterogeneous Validated Kwargs Dicts as `dict[str, Any]` to Feed `**`-Unpack Into a Dataclass Constructor Under basedpyright

**Principle:** Family B (Type-safe domain logic)

When a loader builds a kwargs dict whose values are heterogeneous (e.g., some `bool`, some `dict[str, Decimal]`) and then unpacks it into a dataclass constructor (`Config(**flag_kwargs)`), type the kwargs dict as `dict[str, Any]`, NOT as a union like `dict[str, bool | dict[str, Decimal]]`. Per-key type safety is guaranteed by the loader's type-dispatching validation, but basedpyright cannot propagate per-key narrowing through a `**`-splat; a union-typed kwargs dict produces one `reportArgumentType` error per constructor parameter (a value typed `bool | dict[...]` is not assignable to a param typed `bool`), while `dict[str, Any]` admits the splat cleanly.

**Why `Any` is honest here:** the values are validated at load time by the dispatching loader before being placed in the dict. The static element type of a `**`-unpacked mapping is genuinely opaque to the checker; `Any` reflects that opacity rather than hiding a real type hole. Prefer the small set of `reportAny` warnings (on the splat) over a cascade of `reportArgumentType` errors that mis-describe the situation.

**Required pattern:**
```python
from typing import Any

def _load_flags(...) -> dict[str, Any]:
    flag_kwargs: dict[str, Any] = {}
    for name, value in raw.items():
        # type-dispatching validation guarantees the per-key type here
        flag_kwargs[name] = _validate_and_convert_flag(name, value)
    return flag_kwargs

config = TaxJurisdictionConfig(**flag_kwargs)  # basedpyright: no ArgumentType errors
```

**When NOT to apply:** if the dict is consumed positionally (e.g., `config = TaxJurisdictionConfig(flags)` where the param itself is typed `dict[str, bool | dict[str, Decimal]]`), keep the precise union type; the splat is the only construct that defeats per-key narrowing.

**Shape trigger (when to suspect this family):** a loader validates heterogeneous values into a kwargs dict and splats them into a constructor; basedpyright emits one `reportArgumentType` per dataclass field; rewriting the dict annotation to a union does not silence them.

**Example (2026-06-23 filter-transaction-fees plan, Task 1):** `_load_decision_points_flags` returns validated bools and `dict[str, Decimal]` maps; the result is splatted into `TaxJurisdictionConfig(**flag_kwargs)`. Typing the dict as `dict[str, bool | dict[str, Decimal]]` produced 10 `reportArgumentType` errors; retyping to `dict[str, Any]` left only acceptable `reportAny` warnings on the splat while the per-key validation is unchanged.

**See also:** `development_lessons.md` #8 (specific type annotations for generic collections), #150 (multi-type config loading requires explicit type-dispatching).

## 158. A Refactor Plan Clause That Instructs a Net-New Behavior Addition Conflicts With the Same Plan's Byte-Identical Non-Regression Criterion; Verify Against Actual Pre-Refactor Behavior Before Implementing

**Principle:** Family H (Verify the real thing, not the abstraction)

When a plan frames its task as a refactor with an explicit "behavior must be byte-identical to the current implementation" non-regression criterion, ANY clause that instructs the implementer to ADD a net-new side effect (a new log line, a new warning, a new validation, a new field) that the current code does NOT emit is internally contradictory. Implementing the addition breaks characterization/non-regression tests; implementing the byte-identical behavior contradicts the clause. The resolution is mechanical: before implementing any clause that prescribes new observable behavior in a refactor task, grep/trace the pre-refactor source to confirm the behavior already exists. If it does not, the clause is in error: the new behavior belongs in a LATER task (a feature add, not this refactor) or the non-regression criterion must be explicitly relaxed for that one side effect. Do not silently add the behavior; do not silently drop the clause; document the discrepancy and route the behavior to its owning task.

**Why this happens:** Plan authors reasoning about an extraction often think "since the matcher's old home warned for X, the new caller must warn for X too" without confirming the old home actually warned. The shared-helper extraction makes the absence visible (the matcher no longer emits the warning), so the plan tries to restore it everywhere, but the original caller may have intentionally omitted it, or never had it. The extraction did not change behavior; the plan clause would.

**Shape trigger (when to suspect this family):** a refactor/extraction plan task states "behavior byte-identical" AND contains a clause instructing the new caller or new helper to emit a warning/log/validation/field that reads like a restoration ("since X was moved out of the shared matcher, the caller now owns X"). Trace the pre-refactor source for X before writing the loop that emits it.

**Required response when a refactor clause prescribes new observable behavior:**
1. Trace the pre-refactor source for the prescribed behavior (grep for the log message, the warning call, the validation).
2. If absent: the clause conflicts with the byte-identical criterion. Do NOT implement the addition in the refactor task.
3. Route the behavior to its owning task (usually the feature task that follows the refactor), or relax the non-regression criterion for that one side effect with an explicit doc note.
4. Document the discrepancy in the implementation log so reviewers see the deviation is intentional and not a missed clause.

**Example (2026-06-23 filter-transaction-fees plan, Task 2):** Clause 8 instructed the derivatives caller of the newly-extracted `remove_matched_lots` matcher to warn for each event in `unmatched_events`, "since this warning was moved out of the shared matcher." The pre-refactor `derivatives_dedup` emitted NO unmatched-event warning; a derivatives event with no corresponding CG lot is the expected OGR-only outcome. Adding the warning loop broke 3 tests (2 unit + 1 e2e logger-name/count assertions) and violated the byte-identical non-regression criterion. Resolution: the warning loop was removed; the docstring documents that an unmatched derivatives event is expected. The unmatched-event handling that clause 8 gestured at is owned by Task 3 (the fee filter), which has its own unmatched semantics.

**Distinguishing from #97:** Lesson #97 covers a characterization test whose captured golden value disagrees with the plan's STATED EXPECTED VALUE (a magnitude/direction conflation in captured output). This lesson covers a refactor clause that INSTRUCTS A NET-NEW BEHAVIOR ADDITION the same plan's non-regression criterion forbids. #97 is about a value mismatch in a test; #158 is about a behavior-addition instruction contradicting a non-regression constraint. Both are Family H verification rules but have distinct triggers (golden-value disagreement vs clause-vs-criterion contradiction) and distinct fixes (reconcile narrative vs route the behavior to its owning task).

**See also:** `development_lessons.md` #97 (characterization tests revealing magnitude-vs-direction conflation), #72 (data trace verification), #109 (re-read RED tests against current design invariants when a plan is revised between RED and GREEN), CLAUDE.md §4 Agent Workflow Rules (verification-first task ordering).

## 159. `git checkout -- <file>` Cannot Revert a RED-Phase Break on an Untracked (New) File; Edit It Directly

**Principle:** Family H (Verify the real thing, not the abstraction)

When a RED sanity check deliberately introduces a break in a NEW, untracked source file (e.g. appending `and False` to a guard so the test suite fails and proves the tests are discriminating), the revert cannot use `git checkout -- <file>` or `git restore <file>`. Those commands restore the working-tree copy from a tracked blob in the index or a commit; an untracked file has NO tracked blob in ANY commit yet, so the restore is a silent no-op (or "pathspec did not match" / "no such ref") and the deliberate break remains on disk. The agent then re-runs the test suite believing the revert succeeded, ships a still-broken file, or layers a "corrective" edit on top of the break.

**Required behavior:**
1. Before reverting a RED-phase break on a file, check `git status --short` for that path. If it shows as `??` (untracked), do NOT use `git checkout`/`git restore`; the file has no committed baseline.
2. Revert the break by editing the file directly: re-open it, locate the injected change (the appended `and False`, the swapped operator, the commented guard), and remove it with an Edit. If the entire file is the experiment, delete the file rather than `git checkout`-ing it.
3. After reverting, re-run the test suite and assert it returns to GREEN as the proof of a clean revert; do not trust the absence of an error from `git checkout`.

**Shape trigger (when to suspect this family):** an agent reports "I broke the tagged path with `and False`, ran `git checkout -- fee_filter.py` to revert, and re-ran the suite" but the suite still fails on the same path; OR `git checkout -- <file>` returns silently with no working-tree change on a file the agent knows it modified. In both cases the file is untracked and the checkout was a no-op.

**Example (2026-06-23 filter-transaction-fees plan, Task 3):** After writing `src/tax_reporting/application/crypto/fee_filter.py` and its test suite, the implementer confirmed the suite was discriminating by temporarily breaking the tagged-fee guard with `and False` (12 tests failed as expected). The attempted revert was `git checkout -- fee_filter.py`; because the file was new and untracked, the checkout could not restore it and the `and False` break remained. The break was removed via a direct Edit, and the suite returned to 42 passing. Existing lessons #121/#122/#147 cover `git checkout` recovery for TRACKED files (re-export modules, stash-pop failures, orphan-branch corruption); this lesson covers the distinct failure mode where there is no tracked blob to restore from at all.

**See also:** `development_lessons.md` #121 (ruff `--fix` recovery via `git checkout` on tracked re-export modules), #122 (`git stash` baseline-comparison hazard), #147 (docs-branch canonical-script-only rule), CLAUDE.md §4 Agent Workflow Rules (RED-before-GREEN TDD), shared `agent_workflow_guidelines.md` #6 (formatting-only commit diff inspection).

## 160. Do Not Explicitly Omit Plan-Prescribed Behavior Without Amending the Plan First

**Principle:** Family C (Plan adherence)

When a plan explicitly prescribes a behavior in its Gist or task steps (such as emitting an aggregate warning or summary after a loop), the implementer must not intentionally omit that behavior based on a local judgment call. If the implementer believes the behavior is redundant, harmful, or incorrect, they must halt and ask the user to amend the plan before proceeding. Explicitly skipping the step creates a contradiction between the plan's authorized design and the implementation, which will be caught in review as a plan-adherence failure.

**Why this matters:** The plan is the authoritative design contract. The reviewer verifies the implementation against that contract. An unauthorized omission forces the reviewer to flag it as a Blocker/High finding because the delivered code is structurally missing a required side effect. The time saved by skipping the step is lost to the subsequent review-and-fix cycle.

**Required behavior:**
1. Trace every prescribed side effect (logs, warnings, summaries, state mutations) from the plan's Gist and task body into the implementation.
2. If you intend to omit a prescribed step because you judge it incorrect, do not proceed silently. Surface the disagreement to the user and request a plan amendment.
3. If the plan remains unchanged, implement the step exactly as prescribed.

**Shape trigger (when to suspect this family):** A plan task instructs "emit an aggregate summary warning when the list is non-empty", but the implementation finishes the method without emitting it; the implementer leaves a comment or just skips it because "it seemed noisy".

**Example (2026-06-23 filter-transaction-fees plan):** The plan's Gist Step 7 required an aggregate summary warning after suspect fee events were surfaced. The implementer explicitly omitted it. The r1 code review caught the omission because it contradicted the plan, recording a High finding. The fix required adding the missing `logger.warning` loop at the end of `_surface_suspects`.

**See also:** `plan_quality_guidelines.md` (adherence to the plan).

---

## 161. Trace All Investigation Examples, Not Just the First One

**Principle:** Family A (Equivalence-class coverage)

When a user provides multiple examples to investigate (e.g., a list of missed transactions or false positives), trace and document **all** of them in the resulting analysis artifact. Do not stop after analyzing the first example.

**Why this matters:** A single example only represents one cell of an equivalence class. If the user provided multiple examples, they often belong to *different* equivalence classes with different root causes. Stopping at the first example assumes the others fail for the exact same reason, leaving the subsequent gaps undiscovered and unfixed until a future iteration.

**Required behavior:**
1. Read the user's prompt carefully to count how many examples were provided.
2. In the investigation document or feature note, create a section for each example.
3. Trace each example through the source data and identify its specific failure mode.
4. Ensure the proposed fix addresses all identified failure modes, not just the one from the first example.

**Shape trigger (when to suspect this family):** A user asks "why are these 3 transactions doing X?", the agent explains the mechanism for the first transaction, concludes the investigation, and the user responds "but what about the other two?"

**Example (2026-06-24 fee filtering gap):** The user provided three examples (ETH, BNB, TON) of transaction fees not being filtered. The initial investigation traced only the ETH example (an embedded fee in an exchange row) and concluded the analysis. The user had to point out that BNB and TON were missing. A full trace revealed BNB failed due to a co-occurrence guard (`tx_hash >= 2`), and TON failed due to a missing configuration key. All three were distinct gaps requiring different fixes.

**See also:** #72 (data trace verification).

---

## 162. Verify Aggregation Before Concluding Data is Missing

**Principle:** Family H (Verify the real thing, not the abstraction)

When verifying a user's claim that a specific numerical amount from an output report cannot be found in the source data, verify whether the output report row is an aggregation (e.g., a daily sum) before concluding the data is missing.

**Why this matters:** Searching the unaggregated source data for an exact aggregated sum will always fail. If the agent agrees with the user that the data is missing without checking for aggregation, the investigation chases a phantom bug instead of explaining the correct behavior of the report.

**Required behavior:**
1. When asked to locate an output amount in the source, first check the reporting pipeline to see if the output level aggregates multiple events (e.g., daily totals, grouped by asset/platform).
2. If the output is aggregated, do not grep the source for the exact sum.
3. Instead, find the component rows in the source that share the aggregation keys (date, asset, etc.) and demonstrate how their sum matches the output.

**Shape trigger (when to suspect this family):** A user points to a report output row with an amount (e.g., 1.10 EUR) and says "I don't see a single transaction matching this amount in the source data".

**Example (2026-06-24 fee filtering gap):** The user pointed out a row with 1.1 EUR and said "I don't see a single transaction matching this amount". The agent simply grepped the source for 1.1 and failed. In reality, the 1.1 EUR was a daily aggregate of two 0.55 EUR transactions. Breaking down the aggregate would have correctly explained the provenance of the number rather than falsely agreeing it was untraceable.

**See also:** #101 (trace affected OGR row back to TH source row).


## 165. Test Fixtures Must Reflect Domain Defaults to Avoid Masking Bugs

**Principle:** Family H (Verify the real thing, not the abstraction)

When logic depends on falling back to a default value for generic cases (e.g. `default_ceiling` for generic L1 chains), test fixtures must not provide explicit overrides for the items under test. Doing so bypasses the fallback logic in the test, masking bugs where the production code fails to apply the default correctly.

Test fixtures representing domain configuration should mirror the structural intent of the real configuration: if the real config defines explicit exceptions and relies on the default for everything else, the test fixture should do the same. Tests verifying the default behavior should use an implicit item, not a mock that explicitly overrides it.

## 166. False Positives in AI Code Review: Operator Precedence on Resolved Types

When reviewing for operator precedence bugs involving logical `or` and `and`, verify the exact syntax of the implemented code. A common false positive occurs when the reviewer assumes the code checks for both actual types and string forward references (e.g., `hint is Decimal or hint == "Decimal" and name not in (...)`) and claims missing parentheses cause a precedence bug. If the code relies on `typing.get_type_hints()` to resolve forward references, it likely only checks the actual type (`hint is Decimal and name not in (...)`), making the precedence concern invalid.

## 167. Distinguish Intentional vs Suspicious Ignored Items in Logging

**Principle:** Family G (Data-loss observability)

When a processing pipeline ignores or drops items, distinguish between *intentional/whitelisted* exclusions (e.g., explicitly tagged embedded fees) and *suspicious/unexpected* exclusions.
Log the intentional exclusions at `logger.info` and reserve `logger.warning` for items that fall outside known safe patterns.
Logging known, safe exclusions as warnings creates noise and misleads the user into thinking there is a data quality issue or missing data, whereas using `INFO` properly documents the expected behavior.

## 168. Aggregate Fragmented Lots Before Evaluating Ceilings

**Principle:** Family E (Match and aggregate first, calculate second)

When evaluating a value ceiling/threshold against an event that has been split into multiple fragmented lots (e.g., FIFO matching), checking the threshold against individual lot proceeds defeats the ceiling. Always group the matched lots by the underlying event and evaluate the sum of their proceeds against the ceiling, rather than evaluating lots independently.

## 169. Unlisted Exclusion Candidates Must Fall Back to Suspect Surfacing

**Principle:** Family G (Data-loss observability)

When extracting items to exclude them from main processing (e.g., fee filtering), items that fail the exclusion whitelist must not be silently dropped. If they are not processed as normal items and do not qualify for exclusion, they must be yielded as suspect items so the user can review them manually.

## 170. Avoid Brittle Type Hint Zipping in Dataclass Iteration

**Principle:** Family D (Typing and invariants)

Using `zip(..., strict=True)` to pair `dataclasses.fields()` with `typing.get_type_hints().values()` is brittle. `get_type_hints()` includes non-field annotations (like `@property` or other class-level descriptors), which breaks the 1:1 length and ordering assumptions of `zip`. Always use dictionary lookups (`hints.get(field.name)`) when mapping type hints to dataclass fields.

## 171. A Locally-Archived Official Source Outranks a Conflicting External Secondary Source

**Principle:** Family H (verify the real thing, not the abstraction)

When an external or secondary web source appears to CONFLICT with a value the repo already derives from a locally-mirrored official source (an archived AT form, circular, ruling, or statute PDF under `docs/maintenance/tax/.../official/`), the archived official source is authoritative. Do not escalate the discrepancy as a competing "repo conflict" or treat the unarchived secondary claim as a peer; resolve in favour of the official archive, and if the secondary claim was recorded anywhere in the repo, downgrade or remove it. The deeper error is granting a non-archived secondary source equal standing to an archived primary source.

**Example (2026-06-24 FY2025 self-filing walkthrough):** During research, an external web claim asserted that crypto gains held >=365 days (exempt) are reported on Anexo J Quadro 9.4. This contradicted the repo's own `Annex hint = G1`. Rather than weighting the external claim equally, verifying against the repo's archived `modelo3_anexo_g1_2025.pdf` confirmed the repo was correct: >=365-day exempt crypto goes to Anexo G1 Quadro 7, and only <365-day taxable crypto goes to Anexo J Quadro 9.4/9.4A. The "conflict" was a phantom created by trusting a secondary source over the local official archive.

**Distinguishing from #100 and the AGENTS.md source-preference rule:** Lesson #100 mandates verifying a plan-time claim (path, line, field, function shape) against actual source BEFORE depending on it. The AGENTS.md hard rule ("prefer authoritative PDFs over raw HTML; reuse local mirrors") governs what to FETCH and consult. This lesson covers the narrower conflict-resolution decision: what to do once a secondary source already DISAGREES with an archived official source. The fix is a source-authority judgment (official archive wins outright), not a verification step or a fetch preference.

**How to apply:** Before writing "the repo conflicts with source X" or "this is unresolved," check whether the repo already archives an official source for the claim. If it does, the official archive settles it; cite the archived file and form field, and do not record the secondary claim as a competing position.

---

## 172. Authoritative law portals render the CURRENT version; for a prior fiscal year, use the redação in force for that period, cross-checked against a year-specific secondary source.

**What happened (2026-06-24 FY2025 englobamento calc):** The AT portal page for CIRS art. 68 (IRS bracket table) renders the CURRENT law (OE2026, applies to 2026 income): first bracket 8,342 @ 12.5%. That is the wrong table for a 2025-income return filed in 2026. The 2025-income table (OE2025, first bracket 8,059 @ 13.0%) is the prior "redação em vigor até dezembro de 2025" version the page lists but does not render by default. A web-search LLM summary also mixed in 12.5% first-bracket figures, compounding the confusion. Using the current table would have changed the marginal bracket and the englobamento-vs-28% decision inputs. Resolved by cross-checking the OECD Tax and Benefit Policy Descriptions for Portugal 2025 (statutory schedule, reference date 1 Jan 2025) and PwC Guia Fiscal 2025, both of which confirmed the 8,059/13.0% 2025-income table.

**General rule:** When an authoritative source publishes versioned or time-series legal data (a tax code portal, a regulation page, an official form), the default page render is the CURRENT version, which may not be the version applicable to the reporting period you are working on. Before using any rate, threshold, bracket, or limit, confirm it is the redação/version in force for the specific date or fiscal year of the task. Do not treat a single web-search summary as confirmation; secondary summaries frequently conflate the current version with the period-specific one.

**Distinguishing from #171 (official archive wins over secondary) and #100 (verify claims against source):** #171 resolves conflicts between a secondary source and an ALREADY-ARCHIVED official source; #100 verifies plan-time claims against actual source. This lesson is the orthogonal version-selection step that must happen BEFORE either: the portal you consult is official and authoritative, but it is showing the wrong time slice. No archive conflict exists yet; the error is fetching the current redação when the task needs a prior one.

**How to apply:** For any year-sensitive tax figure, (1) identify the fiscal year/period the task targets and the law version in force for it ("redação em vigor até <date>"); (2) read the portal's version selector / "Redações anteriores" listing rather than the default render; (3) cross-check the period-specific value against at least one year-dated secondary source (e.g. OECD TaxBEN for that year, a Big-4 Guia Fiscal for that year) whose stated reference date matches the target period. Flag the version used in the artifact, per the no-hardcoding rule (CLAUDE.md §4).

---

## 173. "The code emits value X" only proves X is correct for the modeled subcase; a binding source can introduce a discriminator the code does not model.

**Principle:** Family H (verify the real thing, not the abstraction)

When verifying that a classification or routing the code produces is "correct," confirming the code path emits a given annex/code/value is NOT sufficient. The verifying authority (a binding ruling, law, form instructions) may condition the correct answer on a discriminator the code does not branch on at all. In that case the emitted value is correct only for the modeled subcase (or a default), and is wrong for every other value of the unmodeled dimension. The deeper error is equating "the pipeline emits X consistently" with "X is the correct filing value."

**What happened (2026-06-24 derivatives routing):** A doc-review round "confirmed" the derivatives annex routing against the source code: `DerivativesPnLEntry` emits `annex_hint="G/Q13"`, `operation_code="G51"`, and the live workbook header reads "Annex: G/Q13 | Código: G51", so the round declared the repo correct. But the AT binding ruling the routing rests on (Processo 28298/2025) splits the destination on a discriminator the code never reads, counterparty tax residency: resident counterparty -> Anexo G Q13 / G51; non-resident counterparty -> Anexo J Q9.2.B / G30. The filer's exchanges (ByBit/Binance/OKX) are non-resident, so the workbook's Q13/G51 is wrong for the actual case; the code emits it unconditionally because it does not model residency at all. Verifying "the code emits G51" proved only that the resident subcase is wired, not that G51 is the correct value.

**General rule:** When a review or verification cites a binding authority (ruling, statute, form instruction) as the basis for a value the code produces, check whether that authority conditions the answer on a dimension the code does NOT branch on (a property of the counterparty, the asset, the date range, the residency, the instrument subtype). If the authority adds a discriminator the code ignores, the emitted value is conditional, not authoritative, and must be reported as "correct only for the modeled subcase" until the code models the dimension. Do not let a green "the code emits X" check close a correctness question that the authority answers conditionally.

**Distinguishing from #72 and #100:** #72 requires tracing the user's specific case end-to-end through the pipeline (data-flow verification). #100 requires verifying a plan-time claim against actual source before depending on it. This lesson is the upstream failure: the verification correctly traced the code path AND read the authority, but stopped at "code emits X" without asking whether the authority makes X depend on something the code does not compute. The fix is a discriminator-coverage check against the cited authority, not a deeper data trace.

**How to apply:** Whenever a correctness verdict rests on "the code emits value V" plus "authority A says V is right," enumerate the conditions/branches A attaches to V (read the ruling/statute's full conditional, not its conclusion). For each condition, confirm the code actually computes and branches on that dimension. Any condition the code does not model downgrades the verdict to "V is correct only when <condition> = <modeled value>"; flag the unmodeled discriminator as a separate implementation decision (see #174 for propagating the corrected text across surfaces).

---

## 174. A corrected domain rule is often echoed in multiple rendered surfaces; grep the stale string across the corpus and fix every surface in one pass.

**Principle:** Family D (single source of truth)

A single domain rule (a tax-code scope limit, an annex-routing decision, a holding-period exclusion) is frequently rendered in more than one place: the emitted workbook assumptions/methodology text, the decision-point doc, the rules doc, and sometimes a constant in code. When a review finding flags the rule as stale in ONE location, the same stale wording typically survives in the sibling surfaces. Fixing only the named file leaves the corpus internally contradictory: the code/docs the user actually files from still state the old rule.

**What happened (2026-06-24 art. 10(19) derivatives exclusion):** A review finding flagged the stale "Anexo J Q9.4 / long-term (>=365 days) excluded" wording for derivatives in the `Assumptions & Methodology` sheet text (`assumptions_sheet.py`). The same stale claim also lived in `decision_points/2025.md` (the "Filing Guidelines" block, two lines) and in `crypto_rules.md` (PT-C-032, which applied the spot-crypto 365-day exclusion to derivatives). Correcting only the assumptions text would have left two authoritative docs still telling the filer to exclude long-term derivative losses and to use Anexo J Q9.4. The fix had to touch all three surfaces plus their tests, with the same corrected rule (no 365-day exemption for derivatives; art. 10(19) is scoped to alinea k spot criptoativos only).

**General rule:** When you correct or invalidate a domain rule in response to a finding, treat the stale string as a token to grep for across the whole corpus (source code, emitted-text constants, decision-point docs, rules docs, tests) and correct every surface in the same pass. A review finding names the site the reviewer happened to read; the rule almost certainly propagates beyond it. Do not close the finding until a corpus-wide grep for the stale wording returns nothing.

**Distinguishing from #111 and #1540:** #111 greps ALL test files for stale assertions after a data-flow semantics change (test-scope). #1540 greps the package to count the true scope of a code-review duplication finding before acting (review-reception scope). This lesson is the doc/surface-propagation analog: the trigger is correcting a RULE (not changing data flow or triaging a duplication), and the target is every rendered/doc surface that echoes the rule text, not just tests or code sites. The preventive action (corpus-wide grep for the stale token before closing) is the shared shape.

**How to apply:** After correcting a domain rule, run `grep -rn "<stale wording>" src/ docs/ tests/` (and any emitted-text constants). For each hit, either apply the same correction or confirm the hit legitimately still applies the old rule. Only close the finding when the grep is clean. Pair with #173: if the correction came from a binding authority, also confirm the corrected rule is not conditional on an unmodeled discriminator before propagating it.

---

## 175. DTA Suspension and NHR Blacklist Distinctions

**Principle:** Family H (Verify the real thing, not the abstraction)

When assessing NHR exemptions for foreign income, strictly rely on Portugal's domestic tax haven blacklist (Portaria n.º 150/2004) rather than international or EU non-cooperative lists.

**Trigger:** A Double Taxation Agreement (DTA) is suspended, or a country is added to an EU/international blacklist, and you need to determine if NHR exemption still applies.

**Rule:** 
- If a DTA is suspended, the Portuguese AT falls back to domestic law (CIRS Art. 81(5)). Foreign rental income remains exempt under NHR if it may be taxed in the source country under the OECD Model AND the source country is not on the Portuguese blacklist (Portaria n.º 150/2004).
- Do not assume an EU blacklist addition automatically nullifies Portuguese NHR exemptions; Portugal's domestic Portaria determines the legal status.

**Example (2026-06-25 Russia DTA suspension):** Russia was added to the EU non-cooperative list in 2023, and it suspended most DTA articles with Portugal. However, because Russia was not added to Portugal's domestic Portaria 150/2004 list, the NHR fallback rule (CIRS Art. 81(5)) still legally exempts Russian rental income in Portugal.

---

## 176. Multilingual Glossary: Separate Generic from Jurisdiction-Specific, English Defines

**Principle:** Documentation corpus structure (reference docs must be navigable and unambiguous in the project's working language).

**Trigger:** Extending a glossary, dictionary, or reference doc that mixes language-neutral engineering terms with jurisdiction- or domain-specific terms that originate in another language (e.g. Portuguese tax-form field names, operation codes, legal article titles).

**Rule:**
- **Scope-tag the sections.** Separate language-neutral/engineering terms (FIFO, OGR, holding period) from jurisdiction- or domain-specific terms (schedules, quadros, operation codes, legal concepts) into distinct, explicitly labeled sections. Do not interleave them in one flat list.
- **English is the defining language.** Write the definition in the project's primary language (English). Preserve the original non-English naming (the exact portal/form string) alongside, in *italics*, for identification, never as the definition. Example: "**G01** - *Alienação onerosa de ações / partes sociais* - taxable disposal of shares, art. 10(1)(b)." Not: "G01 - Alienação onerosa de ações (shares)..."
- **State the convention once at the top** of the doc (language convention + section layout) so future additions follow it without re-deriving the rule.

**What happened (2026-06-26 glossary extension):** The first revision of `docs/maintenance/glossary.md` added IRS filing codes (G01, G30, Anexos, Quadros) as undifferentiated bullets interleaved with generic reporting terms (CG, OGR, FIFO), and used Portuguese as the primary definition language. The user flagged two problems: (a) generic and PT-specific content were inconsistent in the same sections; (b) Portuguese led the definition. The fix restructured into four labeled sections (Generic data & reporting terms, PT tax-jurisdiction terms, EU terms, Internal identifiers) with a top-of-file language convention and English-primary definitions preserving native naming in italics.

**How to apply:** Before adding a term to `docs/maintenance/glossary.md`, decide which labeled section it belongs to (generic vs jurisdiction-tagged), write the English definition, and append the original-language name in italics if the term originates in a non-English source. When a new jurisdiction is introduced, add a new labeled section rather than mixing it into an existing one. The in-place canonical statement of this convention is the top of `glossary.md`; this lesson is the discoverable cross-reference.

## 177. Tax Treatment of Structured Products and Certificates

**Principle:** Domain knowledge / Legal representation.

**Trigger:** When classifying a new asset, specifically one ending in "Certificate", "Tracker", or "Note".

**Rule:** 
- Structured products (e.g. certificates) are classified as derivatives (Code G30 in Anexo J Q9.2B), not as shares (Code G01 in Q9.2A). 
- The "País da Fonte" (Country of Source) for structured products is strictly the legal domicile of the issuer entity, regardless of the ISIN prefix (e.g., `CH` for Switzerland) or the exchange where it trades.
- **Blacklist trap:** Under CIRS Art. 43(7), any capital loss resulting from an issuer domiciled in a blacklisted tax haven (e.g., the United Arab Emirates) is completely non-deductible. It cannot offset other gains or be carried forward.

**Example (2026-06-26 PSTEYV):** A "Tracker Certificate" (PSTEYV) traded on the Swiss exchange with a `CH` ISIN was initially misclassified as a share. Its true issuer was a Vontobel entity in the Dubai International Financial Centre (UAE). Because the UAE is on Portugal's blacklist (Portaria 150/2004), the resulting ~3,900 EUR loss was entirely non-deductible, significantly altering the net taxable base.

---

## 178. Never Write Temporary Artifacts to Tracked Folders

**Principle:** Repository hygiene.

**Trigger:** When creating a one-off scratch script or a temporary data file.

**Rule:** 
- Temporary artifacts (scratch files, throwaway scripts like `fix_data.py`) must never be placed in git-tracked folders like the project root.
- Use the dedicated git-ignored scratch folder (`{tmp_dir}`) or the system-provided scratch space.

**What happened (2026-06-26):** A temporary `fix_anexoj.py` script was created in the project root to perform bulk markdown edits, leaving untracked pollution in the git tree that required manual cleanup.

---

## 179. Anexo J Quadro 8A Has No Per-Payer Discriminator; Aggregate by (Código + País)

**Principle:** Domain knowledge / Filing mechanics (Modelo 3, Anexo J).

**Trigger:** When entering multiple Categoria E (capital income) lines in Anexo J Quadro 8 that share the same income code AND the same source country (e.g., several US dividends, all code E10 / country 840).

**Rule:**
- Quadro 8A (Rendimentos de Capitais, Categoria E) has **no ISIN field and no payer-NIF field** per line. Its columns are: Código do Rendimento, País da Fonte, Rendimento Bruto, and the Imposto Pago no Estrangeiro / Imposto Retido em Portugal sub-blocks.
- Because there is no per-payer discriminator, the portal's duplicate-line validation key collapses to **(Código + País da Fonte)**. Two lines with the same code AND same country are treated as a repeat and rejected with **error 159J "A linha está repetida"** - even when the gross and WHT amounts differ.
- **Fix:** aggregate all income lines that share (Código, País da Fonte) into **one row**, summing the gross and summing the withholding tax. The totals are preserved, so downstream englobamento / Anexo L exemption outcomes are unaffected.
- This applies broadly to any same-code/same-country Cat E grouping (multiple US dividends, multiple EU interest lines, etc.), not just dividends. If a genuine per-payer split is required for some other reason, it cannot be represented in Q8A.

**Example (2026-06-26):** Five US share dividends (code E10, country 840) entered as five separate Q8A rows triggered 159J. Resolved by aggregating them into a single E10/840 row (gross = sum of the five per-row EUR amounts; WHT = sum of the five withholding amounts), alongside the single CA dividend row and the Wirex interest row, for a final Q8 of 3 lines. The per-symbol/per-ISIN breakdown remains the source-of-truth in the reporting worksheet; it just cannot be transcribed one-row-per-line into Q8A.

**Distinguishing from #174 (stale-rule surface propagation):** #174 corrects a RULE echoed across rendered surfaces. This lesson captures a FORM-STRUCTURE constraint (no discriminator field exists) that forces an aggregation at entry time; the trigger is a validation error, not a rule correction.

---

## 180. When a Validator Rejects Input That Is Valid Under Your Assumed Model, Verify the Validator's Actual Key Before Hypothesizing Hidden Data

**Principle:** Family H (verify the real thing, not the abstraction) - model revision over evidence invention.

**Trigger:** An external system's validator/constraint (portal form, DB unique index, API dedup, build rule) rejects input that is valid under the model you have assumed for how that validator decides. The output looks correct to you, yet it is refused.

**Rule:**
- When observation contradicts your prediction, the bug is more often in your MODEL of the system than in an unseen extra record. Do not reconcile the contradiction by inventing hidden data ("there must be an 8th row I cannot see").
- First verify the validator's ACTUAL key/constraints: which fields the form exposes, its documented dedup/unique semantics, or the real index columns. Confirm the key composition from the system itself (field list, schema, docs) before reasoning about why rows collide.
- Prefer revising the model (the key is narrower than assumed) over revising the data (positing invisible duplicates). Only after the key is confirmed should you search for genuine duplicates that collide on the confirmed key.

**What happened (2026-06-26 Quadro 8 validation):** Portal validation rejected an Anexo J Quadro 8 entry with error 159J "A linha está repetida." I assumed the dedup key was (Codigo + Pais + Rendimento Bruto + Imposto), noted none of the visible rows collided on those four fields, and therefore told the user there must be a hidden 8th duplicate row, asking them to locate it. The real cause (found by the user): Q8A exposes NO per-payer field, so the actual dedup key is the narrower (Codigo + Pais da Fonte); the five same-code/same-country US dividend rows collide by design and must be aggregated (see #179). I should have questioned my assumed key the moment the visible rows did not collide on it, rather than positing invisible data.

**General rule:** "My model predicts no collision, but the validator reports one" is evidence that the model of the validator is wrong, not that extra records exist. Verify the validator's real key/constraints from the system before hypothesizing unseen inputs.

**Distinguishing from #173 and #100:** #173 is about the CODE's model missing a discriminator that a binding authority introduces. #100 is about verifying a plan-time claim against source before depending on it. This lesson is about the AGENT's model of an EXTERNAL validator being wrong, and the specific anti-pattern of inventing hidden evidence to preserve a mistaken model instead of confirming the validator's actual semantics and revising the model.

---

## 181. Prepare Portal-Entry Data Against the Official Form's Actual Field List and Title Qualifiers, Not an Assumed Shape

**Principle:** Family H (verify the real thing, not the abstraction) - transcribe against the authority, not a summary.

**Trigger:** When preparing worksheet data to enter into an official IRS annex/Quadro (e.g., Anexo G1 Quadro 7, Anexo J Q9.x/Q8), or when routing a row to an annex based on the annex's title.

**Rule:**
- **Mirror the form's full column set.** The official form PDF (mirrored under `docs/maintenance/tax/laws/pt/crypto-tax/official/`, e.g. `modelo3_anexo_g1_2025.pdf`) defines exactly which fields a Quadro exposes. Transcribe EVERY one of them per line - for Anexo G1 Q7 that is Titular, Entidade Gestora (NIF Portugues OR Pais), Realizacao (Ano/Mes/Dia/Valor), Aquisicao (Ano/Mes/Dia/Valor), Despesas e encargos, and Pais da contraparte. A net gain/loss aggregate is INSUFFICIENT where the form demands realization value, acquisition value, and expenses as separate fields; capture the gross components from the source workbook, not just the derived net.
- **Verify each title qualifier clause holds for the data.** An annex title is a conjunction of scope clauses, some negated or directional, and each must be satisfied before routing a row there. Anexo G1 Q7 admits only assets that are (a) criptoativos, (b) "que NAO constituam valores mobiliarios" (non-security tokens - security tokens / tokenized instruments are excluded and route to the securities regime), AND (c) "detidos por periodo SUPERIOR OU IGUAL a 365 dias" (>= 365 days). Negations ("nao") and direction words ("superior" vs "inferior") are easy to misread; parse them deliberately. Note PT inverts the usual intuition: >= 365-day crypto is FULLY EXEMPT (CIRS art. 10(19)), not merely favourably rated.
- Confirm both the field list and the title wording against the mirrored official PDF before declaring entry data portal-ready.

**What happened (2026-06-26 Anexo G1 Q7):** The filing entry-data worksheet for long-term crypto captured only the net gain/loss per lot (two negative values), but Q7 demands Valor de Realizacao, Valor de Aquisicao, and Despesas as separate fields. Preparing the portal entry required re-opening the personal IRS filing spreadsheet mid-task to pull the gross realization and acquisition values for each lot. Separately, the filer twice challenged the Q7 routing - first reading "Superior ou Igual a 365 Dias" as if it meant < 365 days, then flagging the "que nao constituam valores mobiliarios" qualifier as if it excluded the tokens. Both challenges were answerable (the lots were non-security utility tokens held >= 365 days, so every clause holds), but they showed the title's clauses had not been made explicit in the worksheet.

**General rule:** Entry-data worksheets and routing decisions must be grounded in the official form's actual field list and full title wording, verified against the mirrored PDF - not in an assumed aggregate shape or a keyword match on the title. Negated and directional qualifiers in a title are load-bearing and must be checked per row.

**Distinguishing from #179 and #180:** #179 is a domain fact (Q8A has no per-payer discriminator, so aggregate by Codigo + Pais). #180 is the anti-pattern of inventing hidden data to preserve a wrong model of a validator. This lesson is upstream of both: before any of those filing mechanics matter, the entry data itself must be transcribed against the form's real columns and the routing must satisfy every title clause. #162 ("verify whether a report output is an aggregation before concluding a value is missing") is the inverse direction (a value that looks missing because it was aggregated); this lesson is the forward direction (a form that demands components where only a net was captured).

---

## 182. Jurisdiction-Specific Tax Output Must Be Country-Gated, Never Fire Unconditionally

**Principle:** Family - configuration-driven jurisdiction dispatch (do not bake the primary use case's rules into the unconditional path).

**Trigger:** When adding or revising output that references a jurisdiction-specific tax construct: a national tax-form code table (e.g. Modelo 3 Tabela V income codes such as `E25`, Tabela de Codigos operation codes such as `G51`/`G30`), an annex/Quadro routing string, a country-only reference table or sheet section, or a hardcoded country label (e.g. a literal `"PT"`).

**Rule:**
- **Gate at the resolution layer, not the renderer.** The helper/resolver that computes the jurisdiction-specific value takes the reporting country (`TaxJurisdictionConfig.country`) as a parameter. Renderers read the already-resolved entry field; they do not branch on country themselves (the one exception is a sheet that emits a country-only reference section, which receives `jurisdiction` to decide whether to render at all).
- **Non-configured country leaves the field blank and omits country-only sections.** Never emit a synthetic placeholder code, and never hardcode the primary country's label. Unknown/missing inputs under the configured country also resolve to blank rather than a synthetic default.
- **Defaults are jurisdiction-neutral.** Entity/record field defaults are the blank/neutral route, so direct construction without a configured jurisdiction cannot emit the primary country's rules (fail safe).
- **The pipeline targets multiple reporting countries.** PT is the current main use case, not a baked-in assumption. Adding a second country later means adding its resolution branch, not refactoring an unconditional PT path.

**What happened (2026-06-26 modelo3-code-correctness plan):** The plan's first revision replaced synthetic internal income codes (`401`-`405`) with official PT Tabela V codes (e.g. `E25` for crypto interest) and added counterparty-residency derivatives routing (`G51`/`G30`, Quadro 13 / 9.2.B) - both wired to fire for every row, regardless of reporting country. The user corrected: these are PT/Modelo 3 rules and must fire only when PT is the reporting country, otherwise the system bakes PT into a pipeline meant to support multiple countries. The plan was redesigned around a "PT-Country Dispatch" invariant: the income-code resolver and the derivatives route helper both take `country`; under a non-PT country they return `""`, the PT-only "Income Codes Reference" sheet section is omitted, and the hardcoded `"PT"` country column derives from `jurisdiction.country` instead of a literal.

**General rule:** When a pipeline targets multiple jurisdictions, any output tied to one jurisdiction's tax forms must be resolved conditionally on the reporting-country config. The resolution layer takes the country; renderers read the resolved field; defaults are jurisdiction-neutral; the non-configured branch is blank, never synthetic.

**Distinguishing from #68 and #150:** #68 is the mechanism (a decision-point flag needs a corresponding `TaxJurisdictionConfig` field). #150 is type-dispatch on config type hints. This lesson is the architectural principle those mechanisms serve: jurisdiction-specific output must not ride the unconditional path at all - it is country-gated, with a blank non-jurisdiction fallback, so the primary use case never becomes a hardcoded default.

## 183. When a Plan Changes a Function Signature, Enumerate Callers Across ALL Test Tiers, Not Just the Dedicated Test File

**Principle:** Family A (Equivalence-class coverage) - the caller-side analog of #111.

**Trigger:** A plan task adds a REQUIRED parameter to an existing function (or removes/renames one), especially when flipping an optional parameter to required to make a forgotten call site fail loudly. The task's test-impact inventory lists the callers to update.

**Rule:** A function's dedicated test file (e.g. `test_derivatives_sheet.py` for `write_derivatives_sheet`) is NOT an exhaustive caller list. Functions with a dedicated unit-test file are frequently also called from e2e/integration tests that exercise the full workbook/report path. When a plan makes a parameter required, enumerate every caller across the ENTIRE test tree (`grep -rn "<func_name>(" tests/`), including `tests/unit/`, `tests/integration/`, and `tests/end_to_end/`. Each unlisted caller breaks with `TypeError` at execution and only surfaces in a tier the plan did not run.

**What happened (2026-06-26 modelo3-code-correctness plan, review round r5):** The plan made `jurisdiction` a REQUIRED param on `write_derivatives_sheet`. Its P0 test-impact inventory counted "~24 callers" - all in `test_derivatives_sheet.py` - and missed 2 production-shaped callers in `tests/end_to_end/test_crypto_derivatives_separation.py` (lines 1007, 1049). Those e2e callers were in a file the plan's A4 GREEN step explicitly runs, so they would have broken the GREEN run. The review caught it; the fix was to add the 2 e2e callers to P0's disposition (passing the existing `build_koinly_jurisdiction()` fixture the e2e file already imports).

**Why this happens:** The plan author grepped or recalled callers from the function's own test module, which holds the bulk of calls, and stopped there. The e2e tier calls the same function through the real workbook-building path but is mentally filed under "derivatives separation," not "derivatives sheet signature." A focused test run on the dedicated file passes; the missed caller only fails when the broader tier runs.

**Required behavior:**
1. When a plan task changes any existing function signature (new required param, removed/renamed param, optional-flipped-to-required), the test-impact step MUST include `grep -rn "<func_name>(" tests/` and group hits by tier.
2. Record the per-tier caller count in the inventory (e.g. "~24 unit + 2 e2e"), not a single total attributed to one file.
3. For e2e/integration callers, reuse the jurisdiction/fixture helper that tier already imports (e.g. `build_koinly_jurisdiction()`); verify the helper exists in that file before prescribing it.

**Distinguishing from #111:** #111 is the assertion-side grep (a data-flow change breaks assertions referencing a data identity tuple; grep all test files for those assertions). This lesson is the caller-side grep (a signature change breaks call sites; grep all test files for callers of the changed function). Same hazard shape - a sibling test in another tier is forgotten - different object (callers vs assertions) and different grep target (function name vs data identity).

## 184. A Pure-Helper Unit Test Going GREEN Does Not Prove the Production Caller Invokes It

**Principle:** Family H (Verify the real thing, not the abstraction) - the wiring-coverage analog of #91.

**Trigger:** A plan extracts a computation into a pure helper (e.g. `_derivatives_route(country, operator_country) -> (annex_hint, operation_code)`) and a production call site must be wired to invoke it, replacing a stale hardcoded default at that site. The plan's RED task writes helper-direct tests AND a separate construction-path test that drives the real producer; the GREEN task adds the helper and wires the site.

**Rule:** Direct unit tests for a pure helper prove only that the helper returns the right value. They do NOT prove the production caller invokes the helper. The caller can continue emitting a stale default (an unconditional `annex_hint="G/Q13"` / `operation_code="G51"` baked into the entity, or a constructor argument the caller still hardcodes) while every helper-direct test is GREEN. When the goal is "the production entry carries the resolved value," at least ONE test must drive the real production construction site (feed the caller's inputs and assert on the object the caller builds), not just call the helper. A suite with only helper-direct tests would go GREEN while construction still omits the routed fields - false GREEN.

**What happened (2026-06-26 modelo3-code-correctness plan, Task A1 RED):** The `TestDerivativesRouting` RED suite deliberately split coverage: three cases called the not-yet-existing pure helper `_derivatives_route(...)` directly (RED via `ImportError`), and one case (`test_nonresident_operator_gets_j_q92b_g30`) drove the real `_split_ogr_index(ogr_rows, capital_entries, jurisdiction)` construction site with a synthetic OGR row whose wallet resolved to a non-PT operator. The construction-path case was the single load-bearing guard: its RED was an `AssertionError` (`'G/Q13' == 'J/Q9.2.B'`), proving the construction RAN but emitted the hardcoded resident default - i.e. the helper is not the only thing that must change; the wiring must change too. If only the helper-direct cases existed, Task A2 could have added the helper and flipped all three to GREEN while `_split_ogr_index` still constructed `DerivativesPnLEntry` with the resident default, and the suite would pass for the wrong reason.

**Why this happens:** Helper-direct tests are cheaper to write (no fixture assembly, no jurisdiction wiring), so a plan author defaults to them. They fully cover the helper's branches but say nothing about the caller. The caller's stale default is usually a field default on the entity dataclass plus (optionally) an explicit constructor argument the caller still passes; both survive a helper-only GREEN. The failure mode is "all helper tests pass, production still wrong" - a false GREEN that the focused test run never challenges.

**Required behavior:**
1. When a plan extracts a value-resolving helper AND the goal is that a production caller emits the resolved value, the RED suite MUST include at least one construction-path test that drives the real producer and asserts on the object it builds, not only helper-direct tests.
2. The construction-path test must be capable of failing for the wiring-specific reason (stale default still present), not only for the helper-missing reason. An `AssertionError` (value mismatch at the built object) is the right RED signature for the wiring case; an `ImportError` is acceptable for the helper-direct cases.
3. Before declaring GREEN, confirm the construction-path case flipped from its wiring-specific RED (value mismatch) to GREEN - not just that the helper-direct cases pass.

**Distinguishing from #91:** #91 is "an extracted helper needs DIRECT unit tests, not only indirect integration coverage" (the helper itself is under-tested). This lesson is the inverse: "the helper IS unit-tested and passing, but the production caller's wiring is unproven" (the caller is under-tested). #91 says add helper tests; #184 says add a construction-site test alongside them. Both can apply to the same extraction; they protect opposite ends of the call.

## 185. When a Field's Aggregation Strategy Changes, Re-Scope the Guard That Observed the Old Strategy's Failure Mode

**Principle:** Family G (Data-loss observability) - the production-side analog of #143's test-side re-scoping rule, paired with #118's guard-adding rule.

**Trigger:** A plan task changes how a field is rendered/aggregated in a way that invalidates the trigger condition of an existing observability guard. Specifically: the field was previously ASSUMED constant across a group and read from `entries[0]` (or `first`), guarded by a #118-style heterogeneity check (`len(distinct) > 1`); the change moves the field to per-row rendering (each row carries its own value), so "heterogeneity across group members" is no longer a failure mode at all - it is the intended design. The old guard's trigger can never fire under the new design, so deleting it loses observability without replacing it.

**Rule:** When a refactor removes the `entries[0]` / `first` read for a field (because the field is now per-row), the #118 heterogeneity guard that protected that read is NOT simply deleted. Its observability must be re-scoped to the NEW failure mode the per-row design introduces: a row that failed to resolve the field and rendered blank (or a sentinel) under the jurisdiction where the field is required. The re-scoped guard fires when (a) the sheet runs under the jurisdiction that requires the field and (b) any rendered entry has a blank/unresolved value for that field. The old guard's positive/negative test pair is replaced by a new pair targeting the new condition (blank-under-required-jurisdiction warns; all-resolved or a non-requiring jurisdiction does not).

**What happened (2026-06-26 modelo3-code-correctness plan, Task A4 GREEN):** The derivatives P&L sheet previously rendered Annex / Código / Legal-category as a single row-2 detail line derived from `entries[0]`, guarded by a `distinct_constant_tuples` heterogeneity check (#118, from the 2026-06-16 review). A4 moved Annex and Código to per-row columns (each entry carries its own route), so "the group disagrees on the constant" became meaningless - disagreement is now the point. Deleting the `distinct_constant_tuples` guard outright would have left no observability for the new failure mode: a PT entry whose route failed to resolve and rendered an empty Annex cell. A4 re-scoped the guard to warn when the sheet renders under PT and any entry has `annex_hint == ""`, with a fresh positive/negative test pair (`test_blank_annex_under_pt_warns` / `test_no_blank_annex_warning_when_routes_resolved`).

**Why this happens:** The #118 guard and the field's aggregation strategy are coupled - the guard observes the strategy's specific failure mode ("the assumed-constant field disagrees across members"). When the strategy changes, the guard's trigger condition describes a state that can no longer occur. A refactor focused on the rendering change treats the guard as dead code and removes it; the new failure mode (unresolved/blank under the requiring jurisdiction) is only apparent if the author asks "what is the new shape of invalidity this field can take?"

**Required behavior:**
1. When a refactor removes an `entries[0]` / `first` read for a field (moving it to per-row or per-entry rendering), audit every guard whose trigger condition depended on the old strategy. A guard that checked `len(distinct_constant_tuples) > 1` (heterogeneity) cannot fire under per-row rendering and is dead.
2. Do NOT delete the dead guard without replacing its observability. Identify the new failure mode the per-row design introduces (typically: an entry that failed to resolve the field and rendered blank/sentinel under a jurisdiction that requires it).
3. Re-scope the guard to the new condition: fire on (jurisdiction-requires-field AND any-entry-blank), not on (group-members-disagree). Gate on the jurisdiction/country config so a non-requiring jurisdiction does not false-warn.
4. Replace the old guard's test pair with a new pair targeting the new condition: a positive test that constructs the new failure (blank-under-requiring-jurisdiction) and asserts the warning, plus a negative test (all-resolved OR non-requiring-jurisdiction) that asserts silence. The negative test defeats a trivial unconditional `logger.warning`.

**Distinguishing from #118 and #143:** #118 says ADD a heterogeneity guard when you take `entries[0]` for an assumed-constant field. This lesson #185 says RE-SCOPE that guard when the field stops being assumed-constant (the old trigger is dead; the observability must move to the new failure mode). #143 is the test-side analog (re-scope a TEST assertion when a fixture flips an orthogonal signal); this is the production-side analog (re-scope a PRODUCTION guard when the field's strategy changes).

## 186. Test Class Names Must Match pytest's `python_classes` Pattern, Else They Are Silently Deselected

**Principle:** Family A (Verify the real thing, not the abstraction) - the collection-configuration analog of #8's type-annotation specificity.

**Trigger:** A plan task prescribes a pytest test class by a specific name (e.g. `IncomeCodeTest`), or an author names a new test class without checking the project's `pyproject.toml` / `pytest.ini` collection config.

**Rule:** A pytest class is only collected if its name matches the configured `python_classes` pattern. This repo configures `python_classes = ["Test*"]` (verified at `pyproject.toml`), so `IncomeCodeTest` (suffix `Test`) is NOT collected - every case in it is silently deselected, and a RED run reports "0 failed" because the cases never executed. A class named `TestIncomeCode` (prefix `Test`) IS collected. Before writing or naming a new pytest class, read the `python_classes` setting; when a task body fixes a class name, conform to the configured pattern (rename to `Test*`) rather than the task's literal name, and record the deviation in the implement log. Confirm collection with `uv run pytest <file> --co -q | grep <ClassName>` or `-k <token>` returning the expected count before relying on RED output.

**What happened (2026-06-26 modelo3-code-correctness plan, Task B1 RED):** The B1 task body named the new class `IncomeCodeTest`. The repo's `pyproject.toml` restricts collection to `python_classes = ["Test*"]` (the existing sibling class `TestDerivativesRouting` conforms). `IncomeCodeTest` is deselected under that config: `uv run pytest -k IncomeCode` returned "363 deselected" with the 17 new cases never running, which would have produced a false "RED achieved" signal (no failures) if not caught. Renaming to `TestIncomeCode` made `-k IncomeCode` select all 17 cases, which then RED correctly on the real contract (`TypeError: ... got an unexpected keyword argument 'country'`).

**Why this happens:** The default pytest behavior collects any `Test*` class, so an author assumes any name containing "Test" is collected. A project that narrows `python_classes` to an exact prefix list silently excludes suffix and infix variants. The failure mode is invisible: the run reports deselection, not error, and a RED check that sees "0 failed" can be mistaken for "not yet broken" rather than "not collected."

**Required behavior:**
1. Before writing a new pytest class, read `python_classes` (and `python_files`, `python_functions`) in `pyproject.toml` / `pytest.ini`. Conform the class name to the configured pattern.
2. When a task body prescribes a class name that does NOT match the configured pattern, rename to the matching pattern (preserving the logical name and every assertion) and record the collection-mechanism adaptation in the implement log; do NOT change test intent.
3. After authoring, confirm collection: `uv run pytest <file> --co -q` reports the expected item count and `grep <ClassName>` (or `-k <token>`) matches the new cases. Never interpret "0 failed" as RED without first confirming the cases were collected.

**Distinguishing from #8:** #8 is about type annotations preserving static-analysis visibility. This lesson #186 is about pytest collection config preserving runtime visibility of test cases. Both are "the tool silently skips your work because of a configuration detail," but at different layers (type checker vs test runner).

## 187. When a Plan Changes Rendered Output Text, Grep All Test Tiers for Tests That Locate the Row by the Stale Label

**Principle:** Family A (Equivalence-class coverage) - the output-identity analog of #183 (signature-change caller grep) and #174 (stale-string echo across surfaces).

**Trigger:** A plan task changes the text a rendered report cell carries (e.g. a description/label column that previously held a synthetic internal label now carries an official code description, or vice versa). The task's test-impact inventory lists the test files to update, typically the unit and e2e tiers that exercise the renderer directly.

**Rule:** A plan that changes rendered output text must grep ALL test tiers (`grep -rn "<old label string>" tests/`) for tests that LOCATE a row by matching that cell's text, not only the renderer's dedicated unit tests. Integration tests frequently build a domain entity, render the full workbook, then find the resulting row on the report sheet by scanning for a hardcoded label string in a specific column. When the renderer starts emitting different text for that column (e.g. an official Tabela code description instead of a synthetic `"Crypto interest (lending, deposit interest)"` label), the row-locator match silently fails and the test errors or false-fails - but only in the integration tier the inventory did not list. The dedicated unit test for the renderer was already re-scoped; the integration test using a different identification strategy (positional scan by label) was never in the inventory.

**What happened (2026-06-26 modelo3-code-correctness plan, Phase-2 validation):** Tasks B2/B3 mapped crypto reward income codes to official Modelo 3 / Tabela V codes, which changed the description cell rendered by `_write_other_capital_income_subsection` from a synthetic `"Crypto interest (lending, deposit interest)"` / `"Crypto capital income (staking, rewards, airdrops)"` label to the official E25 Tabela V text (or blank for source types that do not resolve to a code). B3's test-impact inventory re-scoped the unit analog (`tests/unit/application/persisting/test_ib_sheet.py`) and the e2e analog. It MISSED three integration tests in `tests/integration/test_excel_generation_integration.py` that located the reward row by `row[0] == "Crypto interest (lending, deposit interest)"` or `row[0].startswith("Crypto")`. Those locators never matched the new official-text cell, so the integration tier failed in Phase-2 full-suite validation, after the plan tasks were already committed.

**Why this happens:** The integration tests use a different row-identification strategy than the unit tests. The unit test calls the renderer and asserts on the returned cell value directly; the integration test builds the entity, renders the whole workbook, then SCAN-locates the row by a hardcoded label string in a column. A plan author who re-scoped the unit tier (asserting the new cell value) does not automatically notice that a sibling integration test identifies the row by the OLD cell value. The grep target is the stale label string, not a function name, so a #183-style caller grep would not find it.

**Required behavior:**
1. When a plan task changes the text a rendered report cell carries, the test-impact step MUST include `grep -rn "<old label string>" tests/` across ALL tiers (unit, integration, e2e), in addition to any signature-based caller grep.
2. For each hit, distinguish a row-locator match (the test finds the row BY this string) from an incidental assertion (the test asserts the cell EQUALS this string). Both must be updated, but the row-locator case is the silent-failure hazard: the test does not assert the label, it USES it to find the row, so a mismatch produces a "row not found" error rather than a value-mismatch failure.
3. When re-scoping a row-locator, prefer STRUCTURAL identification (position relative to a subsection header, or a populated country cell) over a new label-string match, so the test no longer couples to a specific rendered string. If a string match is retained (e.g. to also cover description rendering), match a STABLE FRAGMENT of the official text (e.g. `"criptoativos"` for the E25 description) with a module-load drift guard (`assert fragment in get_income_code_description(code)`), not the full verbatim string.
4. Record the per-tier re-scope in the implement log: which tier used direct cell-value assertions (unit), which used structural row-location (integration after fix), and which used label-string row-location before the fix.

**Distinguishing from #183 and #174:** #183 greps for callers of a changed FUNCTION (grep target: function name); this lesson greps for tests that locate a row by a changed LABEL (grep target: the stale string). #174 is "a corrected domain rule is echoed in multiple rendered SURFACES; grep the stale string across the corpus" (production surfaces + tests together); this lesson is the test-only specialization where the stale string is a row-locator, not an asserted value - so the failure is "row not found" rather than "wrong value asserted." Same hazard family (a sibling in another tier/file is forgotten), different grep target and different failure signature.

## 188. When a Web/Search MCP Tool Quotas Out Mid-Task, Fall Back to Direct HTTP and Local Extraction

**Principle:** Source-verification discipline - the tool-outage sibling of #98 (probe the canonical URL before declaring a source absent) and #172 (cite the year-correct redação). The hazard is treating a TOOL outage as a SOURCE outage.

**Trigger:** During source verification, a web-search or web-reader MCP tool returns a quota-exhausted / rate-limit error (e.g. `-429 Weekly/Monthly Limit Exhausted, resets <date>`, HTTP 429) instead of the requested page or results. The task still needs the source content to verify a claim.

**Rule:** A quota or rate-limit error from an MCP/search tool is a TOOL-side outage, not evidence that the source is missing, unverifiable, or stale. Do not abandon the verification or soften the citation to "could not verify." Fall back to direct HTTP from the shell (`curl -sL <url> -o file`, with a browser User-Agent if needed) and extract locally: `pdftotext` for PDFs; an HTML tag-strip (`python3 -c "import re,sys;..."`, `pandoc -f html -t plain`, or `lynx -dump`) for HTML. GET the same canonical URL #98 tells you to HEAD-probe. Only if the direct GET also fails (non-2xx, DNS, connection refused) may you record the source as unavailable - and only after the #98 HEAD probe.

**What happened (2026-06-27 PT rent-deduction source verification):** While verifying Portaria 106/2025/1 (CLS) and the CIRS art. 78-E cap reconciliation for the FY2025 walkthrough, the web-search and web-reader MCP tools both returned `-429 Weekly/Monthly Limit Exhausted, resets 2026-07-09` for every request. The initial reaction was to treat the sources as not directly verifiable. Recovery was `curl -sL <dre files URL> -o portaria.pdf` + `pdftotext`, which retrieved the official PDF verbatim (9 pages, byte-count match), plus `curl` + HTML tag-strip for the consolidated CIRS article. All citations ended up primary-source-verified.

**Why this happens:** MCP/search tools sit behind shared monthly quotas independent of the underlying source's availability. A quota error carries zero information about whether `https://files.diariodarepublica.pt/...` resolves. Conflating the two produces filings or walkthroughs that cite a source as "unverified" when the official document was one `curl` away.

**Required behavior:**
1. When an MCP/search tool returns a quota/rate-limit error (429, "limit exhausted", "rate limited"), do NOT mark the source unverifiable. Switch transport to direct HTTP from the shell.
2. Direct-GET the canonical URL (`curl -sL [-A "<browser UA>"] <url> -o <file>`); for PDFs run `pdftotext <file> -`; for HTML strip tags.
3. Only if the direct GET itself fails (non-2xx after the #98 HEAD probe) may you record the source as unavailable.
4. Record the fallback method in the work log (curl + pdftotext vs MCP) so the verification chain is auditable.

**Distinguishing from #98 and #172:** #98 is "before declaring a source ABSENT, probe its canonical URL with HEAD" (the existence check). #188 is "when a verification TOOL errors out, switch transport rather than abandoning verification" (tool-outage vs source-outage). #172 is about WHICH version to cite (year-correct redação). All three guard source-verification integrity; #188 specifically prevents a tool quota from masquerading as a missing source.

## 189. Tests Must Not Depend on Gitignored Data

**Principle:** Test-fixture portability - the cross-project rule in `coding_guidelines.md` #26. A test that reads a gitignored data file is green only on the machine that happens to hold the file and fails at setup on every fresh clone and CI run.

**Trigger:** A test's `setup_method`, fixture loader, or body opens a data file (a golden snapshot, a scratch JSON, a personal-data CSV) whose path is gitignored.

**Rule:** Test data a test reads at runtime must be committed to the repo, inlined as a literal in the test, or generated deterministically at test time - never placed under a gitignored path. Before reading a file from a test, run `git check-ignore <path>`; if it returns the path, the test depends on data absent from a clean checkout. For characterization/golden-snapshot tests specifically, do NOT write the captured value to a gitignored file and read it back in `setup_method` with a `pytest.fail` when missing - inline the expected value as a literal instead.

**What happened (2026-06-27 derivatives characterization test):** `TestOgrCharacterizationGolden` read two aggregated gain values from `docs/tmp/derivatives-characterization-golden.json` (gitignored), and `_load_golden_snapshot()` called `pytest.fail` when the file was absent. The full suite showed `1492 passed, 2 errors` - the two errors were setup failures, not assertion failures. The file existed on the author's machine (written during the derivatives-separation plan's Task 1) but nowhere else. Fix: inline `Decimal("136.01")` and `Decimal("-1.00")` directly in the test methods, delete the snapshot file, and remove the `_load_golden_snapshot` / `_current_head_sha` / `setup_method` machinery. Now `1494 passed` on any checkout.

**Why this happens:** A plan captures "golden" pre-change output to guard a backward-compat contract, and the implementer parks the snapshot under `{tmp_dir}` (`docs/tmp/`, gitignored by design for scratch). That conflates a durable test contract with ephemeral scratch. The test then cannot travel - it is correct only where the scratch file survived.

**Required behavior:**
1. Any data file a test reads must be version-controlled, inlined, or deterministically generated. Run `git check-ignore` on the path before depending on it.
2. Characterization/golden values go inline in the test as literals, not into a gitignored snapshot read back at setup.
3. If a snapshot must be a file (large/many values), commit it under `tests/` resources, not under `{tmp_dir}`.

**Distinguishing from related lessons:** This is portability of the test's INPUT data. #127 is about hygiene/leak GUARDS scanning every file a protected value can reach (including skipped-in-CI tests) - that is guard coverage, not test input portability. The repo constraint "Crypto tests MUST read committed synthetic data under `resources/source/example/`" is the personal-data-specific instance of the same principle. See `coding_guidelines.md` #26 for the universal rule.

## 190. Mirror Consolidated Living-Code Statutes for Offline Cross-Reference; "It Will Be Outdated" Is Not a Reason to Skip Mirroring

**Principle:** Source-archiving discipline - the archiving sibling of #171 (a locally-archived official source wins outright vs a secondary), #172 (cite the year-correct redação), and #188 (curl fallback when a verification tool quotas out). The hazard is declining to mirror an authoritative source because it is a "living" text that "will be immediately outdated."

**Trigger:** Deciding whether to mirror an official source that is a large consolidated code amended by successive diplomas (e.g. the CIRS, CPPT, CIS consolidated compilations on the Portal das Finanças), versus consulting it online only.

**Rule:** Default to MIRRORING. "It is a large living code, so it will be outdated the moment it is persisted" is NOT sufficient grounds to skip mirroring. The Portal's consolidated rendering is itself just a snapshot at retrieval time; tagging the file with its "última atualização" diploma (and date-stamping the filename by that date) makes it a definite, citable redação - the operative text for a given fiscal year. Staleness is bounded the same way as any archived source: `sources.md` provenance (issuing authority, última atualização, effective/superseded, retrieved date, accessible mirror URL, provisions consulted) plus annual re-verification (re-download, diff the última-atualização tag, bump the dated filename and entry when it advances; for a prior fiscal year apply the redação in force then, incl. transitional norms - #172). Offline access is exactly the resilience path #188 reaches for when an MCP tool rate-limits, and the authoritative reference that corrects a secondary summary that returns the wrong article. So: mirror, date-stamp, record provenance, and cite the local mirror from derived notes.

**What happened (2026-06-27 CIRS/CPPT/CIS mirroring):** Earlier in the rent-deduction work the consolidated CIRS was deliberately NOT mirrored, with a `sources.md` caveat reading "Not mirrored (the consolidated CIRS is a large living code; consult online rather than snapshotting)." The user challenged that call ("can't we download and version it to allow local cross reference, or are you saying the documentation is outdated right after persisting it? If not, let's download and cross reference all relevant docs as we should always do"). The concession was correct: the very next verification needed the CPPT reclamação-graciosa prazo, a secondary LLM-search summary returned the wrong article ("art. 130, 2 years"), and only primary-source PDF verification (`pdftotext` on the downloaded CPPT) settled it at art. 70 n.º 1 = 120 dias. Mirroring CIRS, CPPT, and CIS (date-stamped by última atualização) with `sources.md` entries 4-6 and a staleness-management section made offline cross-reference permanent.

**Why this happens:** "Living code" reads as a reason to defer to the live portal, but the staleness objection applies to EVERY archived external source (which is why `sources.md` provenance and annual re-verification exist per project-guidelines #1/#2) - it is not unique to consolidated codes. Meanwhile the cost of NOT mirroring is concrete: when a verification tool quotas out (#188) or a secondary summary errs (#171), the agent has no local primary source to fall back to and must re-fetch under rate-limit pressure or accept "unverified."

**Required behavior:**
1. When you consult a consolidated statute (or any authoritative source) more than once, mirror it under the appropriate `official/` folder rather than consulting online each time.
2. Date-stamp the filename by the última-atualização date (e.g. `cirs_consolidado_2026-06-03.pdf`); record full provenance in `sources.md` (issuing authority, última atualização, effective/superseded, retrieved date, accessible mirror URL, provisions consulted).
3. Add a staleness-management note: re-verify annually, bump the dated filename + entry when the última atualização advances, and for a prior fiscal year apply the redação in force then (incl. transitional norms) rather than reading the consolidated base directly (#172, project-guidelines #3).
4. Cite the local mirror (not the live URL) from derived cross-reference notes once mirrored.

**Distinguishing from #171, #172, #188:** #171 = a locally-archived official source outranks a conflicting secondary. #172 = cite the redação in force for the target fiscal year. #188 = when a verification TOOL quotas out, switch transport (curl/pdftotext) rather than abandoning verification. #190 = the upstream decision to MIRROR the authoritative source in the first place so that #171/#188 have a local artifact to fall back to - "living code" does not excuse skipping it.

## 191. Wiring Discoverability for a Newly Mirrored Source When the Instruction Entrypoint Is at the Size Ceiling

**Principle:** Discoverability + instruction-size-budget discipline. The `done` Step 2.6 obligation ("new reference material must be discoverable from the instruction paths future agents read") has to hold even when `AGENTS.md` is at the 30,720-byte gate and a net-new bullet will not fit.

**Trigger:** The session mirrors new official sources (or adds reusable reference material) and needs to wire them into the always-loaded instruction entrypoint (`AGENTS.md`/`CLAUDE.md` §5 "Domain Knowledge References"), but the entrypoint has near-zero size headroom.

**Rule:** Two techniques, in priority order. (1) If the reference has a DISTINCT seeker path (a reason an agent would look for it that no existing bullet's trigger covers), it deserves a dedicated bullet: COMPACT duplicate or verbose §5 bullets to make room rather than skip it - merge two bullets citing the same doc, and drop parentheticals that duplicate the linked doc's own contents. (2) Only if compaction cannot free enough, or the reference is already reached by an existing bullet's trigger, surface it by NAME inside that existing bullet (cheap - rename "the X PDF" to "the X/Y/Z PDFs") and route the CONCRETE PATH through the size-ungated Layer-2 doc the bullet already points to (`project-guidelines.md` #N, folder `README.md`, or `sources.md`). In both cases put the full path, dated-filename pattern, `sources.md` entry numbers, and use-cases in the Layer-2 doc; keep the entrypoint bullet as the one-line pointer; and verify the chain resolves. Do NOT let the size budget be the reason a mirror stays undiscoverable, and do NOT overflow the gate.

**What happened (2026-06-27 CIRS/CPPT/CIS discoverability):** After mirroring the three consolidated codes, the high-traffic paths still described them abstractly - `AGENTS.md` §5 said "verify against the consolidated CIRS PDF" with no hint a local mirror existed, and `project-guidelines.md` #3 said "cross-check against the current consolidated CIRS PDF" with no path. `AGENTS.md` was at 30,703/30,720 bytes (17 bytes of headroom). First pass (technique 2): renamed the §5 bullet to "the consolidated CIRS/CPPT/CIS PDFs" (+10 bytes, within budget) and put the concrete `official/` folder path, the dated-filename pattern, the `sources.md` entry numbers (4/5/6), and the CPPT/CIS use-cases into `project-guidelines.md` #3. That left a residual gap: a prazo-only seeker (who never reads the CIRS-trigger bullet) would not discover the CPPT mirror. Second pass (technique 1): the CPPT reference HAS a distinct seeker path (reclamação/impugnação prazos), so it deserved its own bullet; merged the two duplicate `plan_quality_guidelines.md` bullets and trimmed the verbose root-cause-catalog parenthetical, freeing ~200 bytes, and added a dedicated "Before advising on an IRS reclamação/impugnação prazo, verify against the mirrored CPPT" bullet - still under the gate (30,715/30,720).

**Why this happens:** Discoverability cross-refs land last (after the mirror and provenance are written), by which point the entrypoint is often near its ceiling from the session's earlier instruction edits. The instinct to add a dedicated §5 bullet per new source then collides with the size gate.

**Required behavior:**
1. For every source mirrored or reference doc added this session, confirm a future agent can reach it from an always-loaded entrypoint (run the done Step 2.6 check explicitly - do not assume `learn` wired it).
2. If the entrypoint is at the size ceiling, surface the reference by NAME in an existing bullet and put the concrete path + use-cases in the size-ungated Layer-2 doc that bullet points to.
3. Verify the chain resolves: entrypoint name -> Layer-2 path -> file. Re-run the instruction-size gate (`check-instruction-size.sh gate`) after the entrypoint edit.

**Distinguishing from done Step 2.6 and #190:** done Step 2.6 states the discoverability OBLIGATION for new reference material. #190 is the decision to MIRROR the source at all. #191 is the TECHNIQUE for making the mirror discoverable when the entrypoint size budget blocks a dedicated bullet - route the path through the Layer-2 doc the existing bullet already names.

## 192. Verify Classification-Determined Reachability Claims Against Source Data; a Plan Hedge Is a Verify Prompt

**Principle:** Family H (Verify the real thing, not the abstraction) - the data-side sibling of #100 (code-reality claims) and #173 (data-trace verification).

**Trigger:** A plan, design note, or review finding justifies a narrow mapping or an "X never reaches code path Y" claim by appealing to a CLASSIFIER that routes by a data attribute (asset denomination, type field, tag). The justification often hedges ("likely", "probably", "should only reach", "in practice only").

**Rule:** When a reachability claim depends on a classifier that keys off a data attribute, trace that attribute across real source rows before trusting the claim. A single row whose attribute differs from the assumed norm (e.g. a `Type="Reward"` row that is fiat-denominated EUR, not crypto) reaches the supposedly-unreachable path and invalidates the assumption. Treat a hedge word in the justification as an explicit verify prompt, not a confidence statement: the author was unsure, so confirm it against source data.

**What happened (2026-06-28 modelo3 review, finding 1):** The 2026-06-26 modelo3-code-correctness plan narrowed `_resolve_income_code` so only the interest family maps to E25 under PT, leaving every other Koinly type blank. Its B0 research justified this with: "`_resolve_income_code` is called only inside `aggregate_taxable_rewards`, which filters to `taxable_now` (fiat rewards); crypto-denominated staking/reward/airdrop/mining/fork are `DEFERRED_BY_LAW` and never reach the resolver, so **likely** only `interest -> E25` is reachable." The hedge hid an unverified assumption: the `taxable_now` classifier keys off the ASSET being fiat (CRG-002), independent of the Koinly `Type`. A `Type="Reward"` row denominated in EUR is `taxable_now` AND not in the interest family, so it reaches the resolver and resolves to blank. The 2024 example income report (`koinly2024/...income_report...csv` lines 154-163) had exactly ten such EUR "Reward"/"Referral bonus" rows. They were invisible until a review finding proposed failing-closed on the blank code and the full suite hit them. Grepping the source data for a fiat-denominated non-interest reward at plan time (or at B0) would have surfaced the gap and forced an explicit decision about how those rows resolve before the mapping shipped.

**Why this happens:** Classification routing reads as a solid boundary ("crypto rewards are deferred, so they never reach the fiat resolver") because it IS solid for crypto-denominated assets. The hole is the cross-product the author did not enumerate: a type that is USUALLY crypto-denominated but CAN be fiat. The hedge word is the tell - it marks the spot the author stopped enumerating cases.

**Required behavior:**
1. When a mapping/resolver is narrowed with a "type X never reaches here" justification, identify the classifier that gates reachability and the data attribute it keys on.
2. Trace that attribute across committed source/example data (`resources/source/`, fixture CSVs) for rows of the excluded type. If any row's attribute would route it INTO the supposedly-excluded path, the narrowing is unsound until that row's resolution is decided explicitly.
3. Read hedge words ("likely", "probably", "should only", "in practice") as verify prompts: restate the claim without the hedge and check it against source data.
4. When the verified mapping is deliberately narrow pending a legal-judgment call (here: E25's broad "quaisquer formas de remuneração" wording plausibly covers exchange promotional rewards, but extending it was deferred), record the EXACT official wording of the mapped code at the mapping site so a future maintainer can reason about coverage without re-deriving it from the PDF - otherwise a "never guess" narrow mapping reads as "the law only covers interest" when it is really "the law is broad but only interest is verified so far."

**Distinguishing from #100 / #173 / #111:** #100 verifies plan claims about CODE structure; this lesson verifies claims whose truth depends on a classifier AND source DATA denomination. #173 is full data-trace verification across reports; this is the narrower trigger of a hedge-marked reachability assumption. #111 greps test files for stale assertions after a semantics change; the fixture-data grep in step 2 above is the input-side complement (the source data itself can encode the case that breaks the assumption).

## 193. Mandatory Fields on One Filing Record Share One Error Contract

**Principle:** Design consistency - the contract for "this field is mandatory for a complete filing" must be uniform across the mandatory fields of the same record, because the filer-facing consequence (an incomplete row that cannot be filed as-is) is identical regardless of which mandatory field is missing.

**Trigger:** A filing record (IRS quadro/field group, form row, declaration line) has more than one field that is mandatory for the record to be filable, and the pipeline handles a missing/invalid value for each field differently - one fail-closed (raises), another flag-and-continue (emits a flagged row).

**Rule:** All mandatory fields of the same filing record must use the SAME error contract. If one missing mandatory field raises `FileProcessingError`, a different missing mandatory field on the same record must also raise (or both must flag-and-continue with a documented, accepted reason). Asymmetry is a design smell to surface in review: it lets one incomplete-row shape reach the filing surface while another is blocked, with no principled distinction between them.

**What happened (2026-06-28 modelo3 review, finding 1):** A PT Quadro 8A reward row has two mandatory fields resolved in `aggregate_taxable_rewards`: the Tabela X source country and the Tabela V income code. The country code was fail-closed (UNKNOWN/invalid country raises `FileProcessingError` pre-aggregation). The income code, under the same PT jurisdiction, was flag-and-continue: a taxable-now reward resolving to a blank code was appended to the filing-facing list with `review_required=True` and a red-filled "YES: <reason>" income-type cell. Both missing values produce a row that cannot be filed as a complete Quadro 8A line, yet one halted the run and the other emitted a flagged-but-incomplete filing row. The review flagged the asymmetry; the resolution made the income code fail-closed too, mirroring the country-code contract.

**Why this happens:** Mandatory-field handling is often added field-by-field across separate tasks (country validation in one task, income-code resolution in another), so each field inherits the error contract its own task chose without anyone comparing across the fields of the same record.

**Required behavior:**
1. When you add or change the handling for a missing/invalid mandatory field, enumerate the OTHER mandatory fields on the same filing record and confirm they share the same error contract.
2. If the contracts differ, either align them (preferred - fail-closed for all mandatory fields so an incomplete record never reaches the filing surface) or document an explicit, accepted reason for the asymmetry at the handling site.
3. In code review, treat "field A raises but field B flags on the same record" as a finding to raise, not an implementation detail.

**Distinguishing from the partial/uncertain-results indicator rule (CLAUDE.md §1):** That rule says partial/uncertain rows must carry an explicit in-band indicator. This lesson says that when the partial row's incompleteness is a MISSING MANDATORY field, the indicator is not enough - the row should not reach the filing surface at all unless every mandatory field on its record uses the same accepted flag-and-continue contract.

## 194. Flipping an Error Contract Orphans the Superseded Strategy's Surface Across All Tiers - Remove It, Do Not Leave a Dual Mechanism

**Principle:** Family D (consistency / no drift) + the surgical-edits orphan rule. When a branching behavior changes from strategy A to strategy B, every tier that strategy A touched becomes dead the moment the flip lands. The "remove orphans your changes created" hard rule covers orphans inside the file you just edited; this lesson covers the WIDER grep: the superseded strategy's surface typically spans tiers the flip task did not open (a dataclass field defined elsewhere, a renderer `if`-branch in another module, a dedicated test), and leaving it produces a dual mechanism where only one branch is reachable.

**Trigger:** You change how a field/condition is handled - most commonly flipping an error contract from flag-and-continue (emit a review-flagged row) to fail-closed (raise), or the reverse. Also triggers on any behavior flip that replaces one strategy wholesale with another (e.g. "compute X inline" -> "compute X via helper"; "render field on a detail line" -> "render field per row").

**Rule:** After the flip, grep ALL tiers for the superseded strategy's surface and remove it: (1) the dataclass/entity fields that only the old strategy populated; (2) the renderer or conditional branches that only the old strategy reached (`if entry.<flag>:` blocks whose producer no longer sets the flag); (3) the dedicated tests that exercise the now-unreachable path. A codebase that carries the fields, renderer, AND test for strategy A while only strategy B is live is a drift trap - a future maintainer reads the entity/renderer contract and expects the old behavior, and the test green-lights dead code. Verify the orphaned surface is not shared with another live consumer before removing (grep readers of each field/branch across src/).

**What happened (2026-06-28 modelo3 review round 4, finding 1):** Round 3 flipped the PT blank-income-code case from flag-and-continue to fail-closed (raise `FileProcessingError`), the user-approved decision (#193). The flip landed in `aggregate_taxable_rewards`, but three tiers of the OLD flag-and-continue strategy were left in place: `AggregatedRewardIncomeEntry.review_required`/`review_reason` fields (entities.py), two `if entry.review_required:` renderer blocks in `ib_sheet._write_other_capital_income_subsection` (income-type "YES:" override + red fill), and `test_other_capital_income_renders_yes_reason_when_review_required`. Because the only producer that could set the flag now raised before constructing the entry, every produced entry carried `review_required=False` and the renderer blocks were unreachable - dead dual mechanism. Round 4 caught it; the fix removed all three tiers (fields, renderer blocks, test) plus two stale assertions in the aggregator's own tests. Crucially the OTHER `review_required` readers (crypto_gains_sheet, derivatives_sheet, crypto_supplementary_sheet) bind to different entities where the flag stays live, so the removal was scoped to the reward entity only.

**Why this happens:** The flip task edits the producer (the aggregator) and verifies the new contract with a new test, so it goes green. The superseded strategy's surface lives in files the task never opened (the entity dataclass, a sibling renderer, a sibling test), so it is not in the task's diff and survives the commit. It then takes a later review round - or a maintainer confused by the dead contract - to notice.

**Required behavior:**
1. When you flip an error contract or replace a strategy wholesale, enumerate the tiers the OLD strategy touched: producer assignment, entity/dataclass fields, renderer/conditional branches, and tests.
2. Grep readers of each orphaned field/branch across src/ (`grep -rn "\.<field>" src/`) before removing, to confirm no OTHER live consumer still depends on it; remove only what is now unreachable.
3. Remove the dedicated test for the superseded behavior together with the behavior (a passing test for dead code green-lights the dead surface and is itself debt).
4. In code review, treat "the producer raises/never sets X, but a renderer/test still branches on X" as a finding to raise.

**Distinguishing from the hard "remove orphans your changes created" rule and #193:** The hard rule is about orphans INSIDE the file your edit touched (same diff). This lesson is about the WIDER, cross-tier orphan a behavior flip creates in sibling files the flip task did not open - it requires an explicit cross-file grep, not just cleaning up the file you edited. #193 is the DECISION of which error contract to use; this lesson is the CLEANUP of the superseded contract's surface once the decision flips it. #158 (byte-identical non-regression refactors must not add net-new side effects) is about not introducing NEW behavior in a refactor; this is about removing OLD behavior left behind by a contract change.
