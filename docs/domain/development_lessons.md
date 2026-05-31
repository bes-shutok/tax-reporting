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

## 7. Refactoring and Maintenance
- Make small incremental changes and run `uv run pytest` after each one.
- Remove temporary scripts immediately after use.

## 8. Error Handling and Logging
- Always include row numbers and problematic data in error messages.
- Use `from e` exception chaining to preserve original context.
- Logging: parameterised format (`%s`). Exceptions: f-strings. See §1 Instruction Rules for full detail.

## 9. API Design for Production vs Testing
- Do not add features or parameters solely to satisfy tests; adjust tests to match production patterns instead.
- When tests need special handling, first try to make tests reflect real usage before adding complexity to production code.

## 10. Test Path and Fixture Management
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

## 11. Simplify Unnecessary Complexity (YAGNI)
- Remove parameters that always have the same value (e.g. `require_trades_section=True` → hardcode it).
- Do not add features "just in case".

## 12. Excel/openpyxl Column Width
- openpyxl stores formulas as strings; `cell.value` returns the raw formula (e.g., `"=USD EUR*(1234.56)"`), not the computed result.
- Auto-width logic must skip formula cells (`cell.data_type == "f"`) and size columns from headers + non-formula values only.
- The crypto sheet auto-width block has a missing `default=0` in `max()` that raises `ValueError` on empty columns — always provide `default=0` when calling `max()` on a generator.

## 13. Test Real Behavior, Not Implementation Details
- Verify that a feature works end-to-end, not just that it returns a certain value.
- Use realistic test data; check that integrated components produce correct outputs.

## 14. Test CSV Data Construction — Column Alignment

See `~/Projects/docs/python_guidelines.md` #1 for full prevention rules.
Repo context: Koinly `_TH_HEADER` has 20 columns; hand-counting commas is the biggest source of wasted debug iterations.

## 15. Post-Extraction Cleanup

See `~/Projects/docs/python_guidelines.md` #2 for full cleanup procedure.
Repo context: past extractions (crypto_reporting.py → token_origin.py + koinly_parser.py) left unused imports and dead code.

## 16. Aggregation Logic — Test Both Directions

See `~/Projects/docs/agent_workflow_guidelines.md` #1.
Repo context: LP liquidity operations — fixing "in" direction broke "out" because liquidity out produces multiple outputs from one input.

## 17. Operator Mapping Field Semantics (`service_start_date` / `valid_from`)

See `~/Projects/docs/agent_workflow_guidelines.md` #3 for the generic field-semantics lesson.
Repo-specific constraint: `valid_from` is audit-only (when the mapping was verified from source docs). `service_start_date` is for transaction matching (when the platform started offering this service). Never use `valid_from` as a matching gate. When both are known, `service_start_date <= valid_from`.

## 18. Review Agent False Positives

See `~/Projects/docs/agent_workflow_guidelines.md` #2.

## 19. Descriptive Output Labels

See `~/Projects/docs/coding_guidelines.md` #9 for the canonical rule.
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

See `~/Projects/docs/python_guidelines.md` #3 for the canonical rule.
Repo context: `AcquisitionContext`/`ConsumptionContext` wrappers were introduced to attach `tx_key` and `source_row_index` to domain entities without modifying the domain layer. The `__getattr__` delegation made type checkers unable to verify delegated field access (`.date`, `.asset`, etc.), and the `with_acq()`/`with_con()` factory methods were called only twice combined. The correct fix is to add `tx_key` and `source_row_index` directly to `CryptoAcquisition` and `CryptoConsumption` in the domain layer.

## 37. Monkeypatch Module-Level Path Constants in Unit Tests

See `~/Projects/docs/python_guidelines.md` #4 for the canonical rule.
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

See `~/Projects/docs/python_guidelines.md` #5 for the canonical rule.
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

## Quality Assurance Commands

```bash
uv run ruff check . --select=E501     # Line length
uv run ruff check . --select=F401     # Unused imports
uv run ruff check . --select=PL       # Pylint rules

grep -r "Path(__file__)" tests/ || echo "No fragile test paths"
grep -r "= True" src/ --include="*.py" | grep -v "def " | head -10

uv run pytest -m unit          # Fast feedback during development
uv run pytest -m integration   # Before committing
uv run pytest -m e2e           # Before release

grep -n "def test_" tests/ | cut -d: -f3 | sort | uniq -d  # Duplicate test names
```
