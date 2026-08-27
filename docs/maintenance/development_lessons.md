## 1. Type Safety and Annotations
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


## 2. String and Code Formatting
- Keep f-strings on single lines or use explicit parenthesised concatenation.
- Break long lines with `(...)` grouping:

```python
# Good
error_message = (
    f"Error in row {row_number}: "
    f"Expected format X, got Y"
)
```


## 3. Function and Method Design
- Use parameter names that match the interface being implemented.
  Example: `lambda optionstr: optionstr` not `lambda option: option` for ConfigParser.
- Required vs Optional: use required parameters for essential data; only use defaults when a sensible default exists.


## 4. Type Annotation Specificity
- Use specific element types for generic collections: `list[Type] | None` instead of `list | None`.
- Specific types improve documentation, IDE autocomplete, and static analysis.
- When the type is imported only for annotations, keep it inside `TYPE_CHECKING` block.


## 5. Refactoring and Maintenance
- Make small incremental changes and run `uv run pytest` after each one.
- Remove temporary scripts immediately after use.


## 6. Error Handling and Logging
- Always include row numbers and problematic data in error messages.
- Use `from e` exception chaining to preserve original context.
- Logging: parameterised format (`%s`). Exceptions: f-strings. See §1 Instruction Rules for full detail.


## 7. Test Path and Fixture Management
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


## 8. Simplify Unnecessary Complexity (YAGNI)
- Remove parameters that always have the same value (e.g. `require_trades_section=True` → hardcode it).
- Do not add features "just in case".


## 9. Excel/openpyxl Column Width
- openpyxl stores formulas as strings; `cell.value` returns the raw formula (e.g., `"=USD EUR*(1234.56)"`), not the computed result.
- Auto-width logic must skip formula cells (`cell.data_type == "f"`) and size columns from headers + non-formula values only.
- The crypto sheet auto-width block has a missing `default=0` in `max()` that raises `ValueError` on empty columns; always provide `default=0` when calling `max()` on a generator.


## 10. Test CSV Data Construction: Column Alignment

**Principle:** Family H (Verify the real thing, not the abstraction)


See `~/Projects/.ai-playbook/python_guidelines.md` #1 for the full prevention rules.

When writing CSV test fixture rows for multi-column formats (e.g. Koinly TH rows), verify each value is at the correct column index by counting quoted fields as single units (quoted content containing commas counts as one field).

A misaligned column can make a test pass even with the bug it is designed to detect. Example: a test asserting `cost_basis_eur == 0` when `Sent Cost Basis` is empty will still pass if `Net Value (EUR)` is also empty, because an FMV-fallback bug would also produce 0. Place a non-zero value in `Net Value (EUR)` (col 14) to make the bug detectable.

Use `csv.DictReader([TH_HEADER, row])` or the test helper `_parse_row()` to verify field-to-column mapping before relying on a fixture row as a correctness check.

Repo witness: Koinly `_TH_HEADER` has 20 columns; hand-counting commas is the biggest source of wasted debug iterations.


## 11. Post-Extraction Cleanup

See `~/Projects/.ai-playbook/python_guidelines.md` #2 for full cleanup procedure.
Repo context: past extractions (crypto_reporting.py → token_origin.py + koinly_parser.py) left unused imports and dead code.


## 12. Review Agent False Positives

See `~/Projects/.ai-playbook/agent_workflow_guidelines.md` #2.


## 13. Frozen Dataclass `__post_init__` Field Normalization

A frozen dataclass cannot assign to its own fields in `__post_init__`. Use `object.__setattr__(self, field, value)` to normalize fields (e.g. converting empty strings to `None`) during validation. Without this, the normalization is computed but silently discarded.


## 14. Consult Decision Points Before Tax-Treatment Assumptions

Before discussing, proposing, or implementing any crypto tax treatment (cost-basis method, taxability of swaps, Koinly settings), check `docs/maintenance/tax/decision_points/` first. In this session, incorrect assumptions about crypto-to-crypto swap taxation led to a wrong recommendation (turn FMV on) when the answer was already documented in DP-002 (carry-over mandated by CIRS Art. 10(20)). Decision points exist specifically to prevent re-litigating settled questions.


## 15. Use `perl -i -pe` for Word-Boundary Replacements on macOS

macOS `sed` does not support `\b` word boundary anchors. Substitutions using `\b` appear to succeed (exit code 0) but make no substitutions, causing silent failures.

Use `perl -i -pe 's/\bold_name\b/new_name/g' file` for word-boundary renames on macOS. Verify with a grep after the substitution to confirm zero remaining occurrences.


## 16. Avoid `__getattr__` Delegation in Wrapper Dataclasses

See `~/Projects/.ai-playbook/python_guidelines.md` #3 for the canonical rule.
Repo context: `AcquisitionContext`/`ConsumptionContext` wrappers were introduced to attach `tx_key` and `source_row_index` to domain entities without modifying the domain layer. The `__getattr__` delegation made type checkers unable to verify delegated field access (`.date`, `.asset`, etc.), and the `with_acq()`/`with_con()` factory methods were called only twice combined. The correct fix is to add `tx_key` and `source_row_index` directly to `CryptoAcquisition` and `CryptoConsumption` in the domain layer.


## 17. Background Agent Timing: Never Run Tests While Agent Is Writing to Shared Modules

When a background agent is actively writing to source modules, running tests against those modules produces transient failures from broken partial state (half-written files, incomplete imports). Always wait for the background agent to complete before running tests on the modified files.


## 18. Suspicious Asset Detection via Non-Latin Script Characters

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


## 19. Zero-Value Flagging vs Skipping

**Rewards**: Skip zero-value rows by default, but flag known/popular tokens for review instead of skipping.

**Capital gains**: Flag zero-cost or zero-proceeds entries with specific review reasons:
- Zero cost: "Zero acquisition cost - verify basis (airdrop, data error, or misclassification)"
- Zero proceeds: "Zero disposal proceeds - verify sale data (transfer error, data quality issue)"

**Known assets**: Use both:
- Hardcoded popular tokens list (`_POPULAR_CRYPTO_TOKENS` with ~100 tokens: BTC, ETH, SOL, USDT, etc.)
- Dynamic discovery: scan files first for assets with non-zero values, use that as `known_assets` set
- Substring matching: catch Koinly variants like TSTON (contains "TON"), TSUSDE (contains "USDE")

**Reporting**: Flagged entries appear with red fill and "YES: <reason>" in the Review column.


## 20. Substring Matching for Token Variants

Koinly uses prefixes/suffixes for tracked or staked tokens (e.g., **TSTON**, **TSUSDE**); these don't match exact popular token names but contain the base token as a substring.

**Implementation**: `_contains_popular_token()` checks if any popular token exists as a substring (case-insensitive) within the asset ticker.

**Use**: Zero-value flagging uses this to catch variants like:
- TSTON → contains "TON" → flagged
- TSUSDE → contains "USDE" → flagged
- USDT itself → exact match → flagged


## 21. When Removing Functions, Remove Their Tests

When removing or deleting a function from a module, check for and remove any tests that import or test that function. Leaving tests that import deleted functions causes `ImportError` during test collection.

**Check**: Use `grep -rn "<function_name>" tests/` to find test references before removing the function.


## 22. Document Tradeoffs for Fuzzy Matching in Docstrings

When implementing fuzzy matching (substring matching, regex patterns, glob patterns, etc.) that could produce false positives, document the tradeoff explicitly in the docstring so future maintainers understand the design decision and don't "fix" what isn't broken.

**What to document**:
- What the fuzzy matching catches (intended targets)
- What false positives it may produce (collateral matches)
- Why the approach is acceptable despite its imperfections
- The consequence of a false positive (usually just flagging for review rather than skipping important data)

**Example** (from `_contains_popular_token`): "Tradeoff: Substring matching may cause false positives for tickers that coincidentally contain popular token names as substrings (e.g., 'MATICAL' matches 'MATIC'). This is acceptable because the consequence is merely flagging for review rather than incorrectly skipping a legitimate zero-value reward."


## 23. Review Documents Are Temporary Artifacts

Code review documents in `docs/history/reviews/` are temporary staging artifacts for the review workflow, not permanent documentation. They serve as:
- Approval artifacts before posting review comments to a PR
- Persistent record of what was reviewed and what changed

**Lifecycle**:
1. Created during code review with findings marked as `pending`
2. Updated to `fixed` / `drop` / `post` as findings are addressed
3. After all findings are addressed: either delete the file or move to `docs/tmp/` if it has reference value

**Do not**: Accumulate stale review documents in `docs/history/reviews/`. After the branch is merged, these documents have no further purpose.


## 24. Context Managers for Resource Cleanup

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


## 25. Parameter Objects for Complex Signatures

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


## 26. Futures/Derivatives Liquidation Mechanics

A leveraged futures position (e.g., SOL/USDT with USDT as collateral) creates a counterintuitive tax reporting outcome: even when the position is liquidated at a loss, the system reports a **disposal** of the collateral asset. This is correct behavior under Portuguese tax law, not an error.

**Why this happens:**
- A leveraged futures position has the collateral (e.g., USDT) as the underlying asset
- Liquidation is a forced closure where the exchange disposes of the collateral to cover the loss
- For tax purposes, this is an **alienação onerosa** (onerous disposal) under CIRS art. 10(1)(e): "instrumentos financeiros derivados"
- The disposal amount (e.g., "<COLLATERAL_USDT> USDT disposed") reflects the collateral being removed from the position
- The **negative capital gain** (the loss) appears in the gain/loss column and is deductible per PT-C-016 (5-year carry-forward for short-term)

**Key distinction:** A futures liquidation is NOT a withdrawal. A withdrawal (to your own wallet) is not a taxable event for the asset itself. A liquidation is a forced disposal by the exchange and IS taxable; the loss can offset future gains.

**Concrete example:** ByBit SOL/USDT position `<POSITION_ID>` liquidated on 19 Jan 2025, 11:28:53 PM. Koinly reported <-USD_LOSS> USD loss at 11:29:46 PM. The system correctly assessed disposal of <COLLATERAL_USDT> USDT (<COLLATERAL_EUR> EUR) as the collateral disposition, with the loss appearing as negative gain/loss.

**See also:** DP-010 in `docs/maintenance/tax/decision_points/2025.md`, PT-C-031 and PT-C-032 in `docs/maintenance/crypto_rules.md`, the "Cross-Report Validation for Multi-Report Systems" lesson, the "Authoritative Source Overrides Must Precede Aggregation" lesson


## 27. TDD for Bug Fixes

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

**See also:** the "Duplicate Key Handling in Index Building" lesson


## 28. Fix In-Scope Refactoring Findings in the Same Branch

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


## 29. Use the resolve-vars Utility Skill for Path Discovery

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


## 30. False Positives in AI Code Review: Operator Precedence on Resolved Types

When reviewing for operator precedence bugs involving logical `or` and `and`, verify the exact syntax of the implemented code. A common false positive occurs when the reviewer assumes the code checks for both actual types and string forward references (e.g., `hint is Decimal or hint == "Decimal" and name not in (...)`) and claims missing parentheses cause a precedence bug. If the code relies on `typing.get_type_hints()` to resolve forward references, it likely only checks the actual type (`hint is Decimal and name not in (...)`), making the precedence concern invalid.


## 31. Authoritative law portals render the CURRENT version; for a prior fiscal year, use the redação in force for that period, cross-checked against a year-specific secondary source.

**What happened (2026-06-24 FY2025 englobamento calc):** The AT portal page for CIRS art. 68 (IRS bracket table) renders the CURRENT law (OE2026, applies to 2026 income): first bracket 8,342 @ 12.5%. That is the wrong table for a 2025-income return filed in 2026. The 2025-income table (OE2025, first bracket 8,059 @ 13.0%) is the prior "redação em vigor até dezembro de 2025" version the page lists but does not render by default. A web-search LLM summary also mixed in 12.5% first-bracket figures, compounding the confusion. Using the current table would have changed the marginal bracket and the englobamento-vs-28% decision inputs. Resolved by cross-checking the OECD Tax and Benefit Policy Descriptions for Portugal 2025 (statutory schedule, reference date 1 Jan 2025) and PwC Guia Fiscal 2025, both of which confirmed the 8,059/13.0% 2025-income table.

**General rule:** When an authoritative source publishes versioned or time-series legal data (a tax code portal, a regulation page, an official form), the default page render is the CURRENT version, which may not be the version applicable to the reporting period you are working on. Before using any rate, threshold, bracket, or limit, confirm it is the redação/version in force for the specific date or fiscal year of the task. Do not treat a single web-search summary as confirmation; secondary summaries frequently conflate the current version with the period-specific one.

**Distinguishing from the "official archive wins over secondary" lesson and the "verify claims against source" lesson:** the former resolves conflicts between a secondary source and an ALREADY-ARCHIVED official source; the latter verifies plan-time claims against actual source. This lesson is the orthogonal version-selection step that must happen BEFORE either: the portal you consult is official and authoritative, but it is showing the wrong time slice. No archive conflict exists yet; the error is fetching the current redação when the task needs a prior one.

**How to apply:** For any year-sensitive tax figure, (1) identify the fiscal year/period the task targets and the law version in force for it ("redação em vigor até <date>"); (2) read the portal's version selector / "Redações anteriores" listing rather than the default render; (3) cross-check the period-specific value against at least one year-dated secondary source (e.g. OECD TaxBEN for that year, a Big-4 Guia Fiscal for that year) whose stated reference date matches the target period. Flag the version used in the artifact, per the no-hardcoding rule (CLAUDE.md §4).

---


## 32. Multilingual Glossary: Separate Generic from Jurisdiction-Specific, English Defines

**Principle:** Documentation corpus structure (reference docs must be navigable and unambiguous in the project's working language).

**Trigger:** Extending a glossary, dictionary, or reference doc that mixes language-neutral engineering terms with jurisdiction- or domain-specific terms that originate in another language (e.g. Portuguese tax-form field names, operation codes, legal article titles).

**Rule:**
- **Scope-tag the sections.** Separate language-neutral/engineering terms (FIFO, OGR, holding period) from jurisdiction- or domain-specific terms (schedules, quadros, operation codes, legal concepts) into distinct, explicitly labeled sections. Do not interleave them in one flat list.
- **English is the defining language.** Write the definition in the project's primary language (English). Preserve the original non-English naming (the exact portal/form string) alongside, in *italics*, for identification, never as the definition. Example: "**G01** - *Alienação onerosa de ações / partes sociais* - taxable disposal of shares, art. 10(1)(b)." Not: "G01 - Alienação onerosa de ações (shares)..."
- **State the convention once at the top** of the doc (language convention + section layout) so future additions follow it without re-deriving the rule.

**What happened (2026-06-26 glossary extension):** The first revision of `docs/maintenance/glossary.md` added IRS filing codes (G01, G30, Anexos, Quadros) as undifferentiated bullets interleaved with generic reporting terms (CG, OGR, FIFO), and used Portuguese as the primary definition language. The user flagged two problems: (a) generic and PT-specific content were inconsistent in the same sections; (b) Portuguese led the definition. The fix restructured into four labeled sections (Generic data & reporting terms, PT tax-jurisdiction terms, EU terms, Internal identifiers) with a top-of-file language convention and English-primary definitions preserving native naming in italics.

**How to apply:** Before adding a term to `docs/maintenance/glossary.md`, decide which labeled section it belongs to (generic vs jurisdiction-tagged), write the English definition, and append the original-language name in italics if the term originates in a non-English source. When a new jurisdiction is introduced, add a new labeled section rather than mixing it into an existing one. The in-place canonical statement of this convention is the top of `glossary.md`; this lesson is the discoverable cross-reference.


## 33. Tax Treatment of Structured Products and Certificates

**Principle:** Domain knowledge / Legal representation.

**Trigger:** When classifying a new asset, specifically one ending in "Certificate", "Tracker", or "Note".

**Rule:** 
- Structured products (e.g. certificates) are classified as derivatives (Code G30 in Anexo J Q9.2B), not as shares (Code G01 in Q9.2A). 
- The "País da Fonte" (Country of Source) for structured products is strictly the legal domicile of the issuer entity, regardless of the ISIN prefix (e.g., `CH` for Switzerland) or the exchange where it trades.
- **Blacklist trap:** Under CIRS Art. 43(7), any capital loss resulting from an issuer domiciled in a blacklisted tax haven (e.g., the United Arab Emirates) is completely non-deductible. It cannot offset other gains or be carried forward.

**Example (2026-06-26 PSTEYV):** A "Tracker Certificate" (PSTEYV) traded on the Swiss exchange with a `CH` ISIN was initially misclassified as a share. Its true issuer was a Vontobel entity in the Dubai International Financial Centre (UAE). Because the UAE is on Portugal's blacklist (Portaria 150/2004), the resulting ~3,900 EUR loss was entirely non-deductible, significantly altering the net taxable base.

---


## 34. Never Write Temporary Artifacts to Tracked Folders (and Split Documents vs Scripts)

**Principle:** Repository hygiene.

**Trigger:** When creating a one-off scratch script or a temporary data file.

**Rule:**
- Temporary artifacts (scratch files, throwaway scripts like `fix_data.py`) must never be placed in git-tracked folders like the project root.
- Split ephemeral scratch by kind, not lumped in one dir:
  - **Documents** (execute-plan logs, review scratch, diff snapshots - `.md`/`.patch`) go in `{tmp_dir}` (`docs/tmp/`). These have reference value for the next round's `learn` step and are synced to the orphan `docs` branch as a safety net.
  - **Scripts and scratch data** (`.py` shadow/verification scripts, `.csv`/`.txt` baseline counts, `__pycache__/`) go in repo-root `tmp/`, never `docs/tmp/`. Root `tmp/` is gitignored and NOT synced to the `docs` branch - throwaway scripts have zero durable value and pollute the safety net when they land there.

**What happened (2026-06-26):** A temporary `fix_anexoj.py` script was created in the project root to perform bulk markdown edits, leaving untracked pollution in the git tree that required manual cleanup.

**What happened (2026-07-21 docs/tmp prune):** The orphan `docs` branch had accumulated ~150 files under `docs/tmp/`, of which ~20 were throwaway `.py` shadow scripts and `.csv`/`.txt` baseline-count files from the phase-A through phase-E th-tx-view plans (e.g. `docs/tmp/phase-a-tx-id-semantics.py`, `docs/tmp/phase-c-shadow/shadow_run.py`, `docs/tmp/phase-c-shadow/__pycache__/`, `docs/tmp/phase-c-shadow/discrepancies.csv`, `docs/tmp/phase-*-baseline-count.txt`). These had been synced to the `docs` branch by `docs-branch` (which is add-only by design and never auto-prunes) even though they had no reference value past the plan that created them. The `execute-plan` Phase 5 cleanup step (which should have removed each plan's session dir on completion) had not been running, so the backlog grew unchecked. Full prune (150 -> 0 files) was done manually on 2026-07-21; backup at `refs/heads/docs-backup-pre-tmp-prune`. Root cause for the script pollution: the convention collapsed documents and scripts into one `{tmp_dir}`, so ad-hoc shadow scripts landed alongside the logs. The split above (documents in `docs/tmp/`, scripts in root `tmp/`) prevents the collapse from recurring. Cite AGENTS.md rule 4.160.

---


## 35. Anexo J Quadro 8A Has No Per-Payer Discriminator; Aggregate by (Código + País)

**Principle:** Domain knowledge / Filing mechanics (Modelo 3, Anexo J).

**Trigger:** When entering multiple Categoria E (capital income) lines in Anexo J Quadro 8 that share the same income code AND the same source country (e.g., several US dividends, all code E10 / country 840).

**Rule:**
- Quadro 8A (Rendimentos de Capitais, Categoria E) has **no ISIN field and no payer-NIF field** per line. Its columns are: Código do Rendimento, País da Fonte, Rendimento Bruto, and the Imposto Pago no Estrangeiro / Imposto Retido em Portugal sub-blocks.
- Because there is no per-payer discriminator, the portal's duplicate-line validation key collapses to **(Código + País da Fonte)**. Two lines with the same code AND same country are treated as a repeat and rejected with **error 159J "A linha está repetida"** - even when the gross and WHT amounts differ.
- **Fix:** aggregate all income lines that share (Código, País da Fonte) into **one row**, summing the gross and summing the withholding tax. The totals are preserved, so downstream englobamento / Anexo L exemption outcomes are unaffected.
- This applies broadly to any same-code/same-country Cat E grouping (multiple US dividends, multiple EU interest lines, etc.), not just dividends. If a genuine per-payer split is required for some other reason, it cannot be represented in Q8A.

**Example (2026-06-26):** Five US share dividends (code E10, country 840) entered as five separate Q8A rows triggered 159J. Resolved by aggregating them into a single E10/840 row (gross = sum of the five per-row EUR amounts; WHT = sum of the five withholding amounts), alongside the single CA dividend row and the Wirex interest row, for a final Q8 of 3 lines. The per-symbol/per-ISIN breakdown remains the source-of-truth in the reporting worksheet; it just cannot be transcribed one-row-per-line into Q8A.

**Distinguishing from the "stale-rule surface propagation" lesson:** that lesson corrects a RULE echoed across rendered surfaces. This lesson captures a FORM-STRUCTURE constraint (no discriminator field exists) that forces an aggregation at entry time; the trigger is a validation error, not a rule correction.

---


## 36. Jurisdiction-Specific Tax Output Must Be Flag-Gated, Never Fire Unconditionally

**Principle:** Family - configuration-driven jurisdiction dispatch (do not bake the primary use case's rules into the unconditional path).

**Trigger:** When adding or revising output that references a jurisdiction-specific tax construct: a national tax-form code table (e.g. Modelo 3 Tabela V income codes such as `E25`, Tabela de Codigos operation codes such as `G51`/`G30`), an annex/Quadro routing string, a country-only reference table or sheet section, or a hardcoded country label (e.g. a literal `"PT"`).

**Rule:**
- **Gate at the resolution layer, not the renderer, and on a decision-point flag, not a country literal.** Add a decision-point flag on `TaxJurisdictionConfig` for the dimension in question and have the helper/resolver take that flag as a parameter. Renderers read the already-resolved entry field; they do not branch on country or on the flag themselves (the one exception is a sheet that emits a country-only reference section, which receives `jurisdiction` to decide whether to render at all). Never compare a country literal (e.g. `country == "PT"`) in the application layer; the only sanctioned country-literal checks live in the config loader (`infrastructure/config.py`), which is the boundary that converts config into the country value the rest of the code reads.
- **Flag off leaves the field blank and omits country-only sections.** Never emit a synthetic placeholder code, and never hardcode the primary country's label. Unknown/missing inputs under the flag-on branch also resolve to blank rather than a synthetic default.
- **Defaults are jurisdiction-neutral.** Entity/record field defaults are the blank/neutral route, so direct construction without a configured jurisdiction cannot emit the primary country's rules (fail safe).
- **Emitted codes remain jurisdiction-specific `_PT_*` constants.** The flag gates whether the path fires; the actual annex/codes it emits (e.g. `_PT_RESIDENT_OPERATION_CODE = "G51"`) are still the primary jurisdiction's Modelo 3 constants, named with the `_PT_` prefix to make their jurisdictional scope explicit. The flag carries the dispatch dimension; the constants carry the concrete code values.
- **The pipeline targets multiple reporting countries.** PT is the current main use case, not a baked-in assumption. Adding a second country later means flipping its flags in the decision-point TOML, not refactoring an unconditional or country-literal-gated path.

**What happened (2026-06-26 modelo3-code-correctness plan, then 2026-06-27 modelo3-flag-based-dispatch plan):** The first plan replaced synthetic internal income codes (`401`-`405`) with official PT Tabela V codes (e.g. `E25` for crypto interest) and added counterparty-residency derivatives routing (`G51`/`G30`, Quadro 13 / 9.2.B) - both wired to fire for every row, regardless of reporting country. The user corrected: these are PT/Modelo 3 rules and must fire only when PT is the reporting country, otherwise the system bakes PT into a pipeline meant to support multiple countries. The first plan's fix was a "PT-Country Dispatch" invariant that gated on `country == "PT"`. The second plan (Task 2) then recognized that a country literal is the WRONG gate whenever the discriminating dimension is not literally "is this jurisdiction PT": counterparty residency for derivatives routing is orthogonal to the reporting country, and income-code classification is driven by tax-form schema, not by jurisdiction. Task 2 replaced four `country == "PT"` / `PORTUGAL_COUNTRY_CODE` gates with two decision-point flags (`route_derivatives_by_counterparty_residency`, `classify_rewards_with_income_codes`) on `TaxJurisdictionConfig`, removed `PORTUGAL_COUNTRY_CODE` from the application layer entirely, and renamed the emitted codes `_PT_*`. The flag carries the dimension explicitly, makes the gate jurisdiction-agnostic, and cures the latent-bug testability hazard documented in the "untestable predicate" lesson.

**General rule:** When a pipeline targets multiple jurisdictions, any output tied to one jurisdiction's tax forms must be gated on a decision-point flag that names the actual dispatch dimension (residency, tax-form schema, etc.), not on a country literal. The resolution layer takes the flag; renderers read the resolved field; defaults are jurisdiction-neutral; the flag-off branch is blank, never synthetic; the emitted codes stay jurisdiction-specific `_PT_*` constants. Prefer a flag gate over a country-literal gate whenever the dimension is not literally "is this jurisdiction X."

**Distinguishing from the "decision-point flag requires a config field" lesson and the "multi-type config loading" lesson:** the former is the mechanism (a decision-point flag needs a corresponding `TaxJurisdictionConfig` field and TOML sidecar); the latter is type-dispatch on config type hints. This lesson is the architectural principle those mechanisms serve: jurisdiction-specific output must not ride the unconditional path at all - it is flag-gated via a decision-point dimension, with a blank flag-off fallback, so the primary use case never becomes a hardcoded or country-literal default.

**Why a flag, not a country literal (2026-06-27 modelo3-flag-based-dispatch plan, Task 2):** Country-literal gating (`country == "PT"`) is the FIRST-GENERATION form of this principle and is correct only when the gate is purely "is this the PT jurisdiction." When the discriminating dimension is NOT the reporting country itself - counterparty residency for derivatives routing (a resident counterparty under any reporting country routes to the resident annex), or income-code classification (driven by tax-form schema, not by jurisdiction) - a country literal is the wrong gate. Migrating to a flag also cured the latent-residency-bug testability hazard documented in the "untestable predicate" lesson (a predicate coupled to the same literal that gates its entry is structurally untestable) and created the cross-task stale-premise obligation in the "deferred-test staleness" lesson (a contract change of this kind makes downstream references to the old mechanism stale).


## 37. When a Web/Search MCP Tool Quotas Out Mid-Task, Fall Back to Direct HTTP and Local Extraction

**Principle:** Source-verification discipline - the tool-outage sibling of the "probe the canonical URL before declaring a source absent" lesson and #31 (cite the year-correct redação). The hazard is treating a TOOL outage as a SOURCE outage.

**Trigger:** During source verification, a web-search or web-reader MCP tool returns a quota-exhausted / rate-limit error (e.g. `-429 Weekly/Monthly Limit Exhausted, resets <date>`, HTTP 429) instead of the requested page or results. The task still needs the source content to verify a claim.

**Rule:** A quota or rate-limit error from an MCP/search tool is a TOOL-side outage, not evidence that the source is missing, unverifiable, or stale. Do not abandon the verification or soften the citation to "could not verify." Fall back to direct HTTP from the shell (`curl -sL <url> -o file`, with a browser User-Agent if needed) and extract locally: `pdftotext` for PDFs; an HTML tag-strip (`python3 -c "import re,sys;..."`, `pandoc -f html -t plain`, or `lynx -dump`) for HTML. GET the same canonical URL the source-probing lesson has you HEAD-probe. Only if the direct GET also fails (non-2xx, DNS, connection refused) may you record the source as unavailable - and only after the  HEAD probe.

**What happened (2026-06-27 PT rent-deduction source verification):** While verifying Portaria 106/2025/1 (CLS) and the CIRS art. 78-E cap reconciliation for the FY2025 walkthrough, the web-search and web-reader MCP tools both returned `-429 Weekly/Monthly Limit Exhausted, resets 2026-07-09` for every request. The initial reaction was to treat the sources as not directly verifiable. Recovery was `curl -sL <dre files URL> -o portaria.pdf` + `pdftotext`, which retrieved the official PDF verbatim (9 pages, byte-count match), plus `curl` + HTML tag-strip for the consolidated CIRS article. All citations ended up primary-source-verified.

**Why this happens:** MCP/search tools sit behind shared monthly quotas independent of the underlying source's availability. A quota error carries zero information about whether `https://files.diariodarepublica.pt/...` resolves. Conflating the two produces filings or walkthroughs that cite a source as "unverified" when the official document was one `curl` away.

**Required behavior:**
1. When an MCP/search tool returns a quota/rate-limit error (429, "limit exhausted", "rate limited"), do NOT mark the source unverifiable. Switch transport to direct HTTP from the shell.
2. Direct-GET the canonical URL (`curl -sL [-A "<browser UA>"] <url> -o <file>`); for PDFs run `pdftotext <file> -`; for HTML strip tags.
3. Only if the direct GET itself fails (non-2xx after the HEAD probe) may you record the source as unavailable.
4. Record the fallback method in the work log (curl + pdftotext vs MCP) so the verification chain is auditable.

**Distinguishing from the "probe the canonical URL" lesson and #31:** that lesson is "before declaring a source ABSENT, probe its canonical URL with HEAD" (the existence check). #37 is "when a verification TOOL errors out, switch transport rather than abandoning verification" (tool-outage vs source-outage). #31 is about WHICH version to cite (year-correct redação). All three guard source-verification integrity; #37 specifically prevents a tool quota from masquerading as a missing source.


## 38. Tests Must Not Depend on Gitignored Data

**Principle:** Test-fixture portability - the cross-project rule in `coding_guidelines.md` #26. A test that reads a gitignored data file is green only on the machine that happens to hold the file and fails at setup on every fresh clone and CI run.

**Trigger:** A test's `setup_method`, fixture loader, or body opens a data file (a golden snapshot, a scratch JSON, a personal-data CSV) whose path is gitignored.

**Rule:** Test data a test reads at runtime must be committed to the repo, inlined as a literal in the test, or generated deterministically at test time - never placed under a gitignored path. Before reading a file from a test, run `git check-ignore <path>`; if it returns the path, the test depends on data absent from a clean checkout. For characterization/golden-snapshot tests specifically, do NOT write the captured value to a gitignored file and read it back in `setup_method` with a `pytest.fail` when missing - inline the expected value as a literal instead.

**What happened (2026-06-27 derivatives characterization test):** `TestOgrCharacterizationGolden` read two aggregated gain values from `docs/tmp/derivatives-characterization-golden.json` (gitignored), and `_load_golden_snapshot()` called `pytest.fail` when the file was absent. The full suite showed `1492 passed, 2 errors` - the two errors were setup failures, not assertion failures. The file existed on the author's machine (written during the derivatives-separation plan's Task 1) but nowhere else. Fix: inline `Decimal("136.01")` and `Decimal("-1.00")` directly in the test methods, delete the snapshot file, and remove the `_load_golden_snapshot` / `_current_head_sha` / `setup_method` machinery. Now `1494 passed` on any checkout.

**Why this happens:** A plan captures "golden" pre-change output to guard a backward-compat contract, and the implementer parks the snapshot under `{tmp_dir}` (`docs/tmp/`, gitignored by design for scratch). That conflates a durable test contract with ephemeral scratch. The test then cannot travel - it is correct only where the scratch file survived.

**Required behavior:**
1. Any data file a test reads must be version-controlled, inlined, or deterministically generated. Run `git check-ignore` on the path before depending on it.
2. Characterization/golden values go inline in the test as literals, not into a gitignored snapshot read back at setup.
3. If a snapshot must be a file (large/many values), commit it under `tests/` resources, not under `{tmp_dir}`.

**Distinguishing from related lessons:** This is portability of the test's INPUT data. The "static guards must cover skipped-in-CI paths" lesson is about hygiene/leak GUARDS scanning every file a protected value can reach (including skipped-in-CI tests) - that is guard coverage, not test input portability. The repo constraint "Crypto tests MUST read committed synthetic data under `resources/source/example/`" is the personal-data-specific instance of the same principle. See `coding_guidelines.md` #26 for the universal rule.


## 39. Mirror Consolidated Living-Code Statutes for Offline Cross-Reference; "It Will Be Outdated" Is Not a Reason to Skip Mirroring

**Principle:** Source-archiving discipline - the archiving sibling of the "official archive wins over secondary" lesson, #31 (cite the year-correct redação), and #37 (curl fallback when a verification tool quotas out). The hazard is declining to mirror an authoritative source because it is a "living" text that "will be immediately outdated."

**Trigger:** Deciding whether to mirror an official source that is a large consolidated code amended by successive diplomas (e.g. the CIRS, CPPT, CIS consolidated compilations on the Portal das Finanças), versus consulting it online only.

**Rule:** Default to MIRRORING. "It is a large living code, so it will be outdated the moment it is persisted" is NOT sufficient grounds to skip mirroring. The Portal's consolidated rendering is itself just a snapshot at retrieval time; tagging the file with its "última atualização" diploma (and date-stamping the filename by that date) makes it a definite, citable redação - the operative text for a given fiscal year. Staleness is bounded the same way as any archived source: `sources.md` provenance (issuing authority, última atualização, effective/superseded, retrieved date, accessible mirror URL, provisions consulted) plus annual re-verification (re-download, diff the última-atualização tag, bump the dated filename and entry when it advances; for a prior fiscal year apply the redação in force then, incl. transitional norms - #31). Offline access is exactly the resilience path #37 reaches for when an MCP tool rate-limits, and the authoritative reference that corrects a secondary summary that returns the wrong article. So: mirror, date-stamp, record provenance, and cite the local mirror from derived notes.

**What happened (2026-06-27 CIRS/CPPT/CIS mirroring):** Earlier in the rent-deduction work the consolidated CIRS was deliberately NOT mirrored, with a `sources.md` caveat reading "Not mirrored (the consolidated CIRS is a large living code; consult online rather than snapshotting)." The user challenged that call ("can't we download and version it to allow local cross reference, or are you saying the documentation is outdated right after persisting it? If not, let's download and cross reference all relevant docs as we should always do"). The concession was correct: the very next verification needed the CPPT reclamação-graciosa prazo, a secondary LLM-search summary returned the wrong article ("art. 130, 2 years"), and only primary-source PDF verification (`pdftotext` on the downloaded CPPT) settled it at art. 70 n.º 1 = 120 dias. Mirroring CIRS, CPPT, and CIS (date-stamped by última atualização) with `sources.md` entries 4-6 and a staleness-management section made offline cross-reference permanent.

**Why this happens:** "Living code" reads as a reason to defer to the live portal, but the staleness objection applies to EVERY archived external source (which is why `sources.md` provenance and annual re-verification exist per project-guidelines #1/#2) - it is not unique to consolidated codes. Meanwhile the cost of NOT mirroring is concrete: when a verification tool quotas out (#37) or a secondary summary errs, the agent has no local primary source to fall back to and must re-fetch under rate-limit pressure or accept "unverified."

**Required behavior:**
1. When you consult a consolidated statute (or any authoritative source) more than once, mirror it under the appropriate `official/` folder rather than consulting online each time.
2. Date-stamp the filename by the última-atualização date (e.g. `cirs_consolidado_2026-06-03.pdf`); record full provenance in `sources.md` (issuing authority, última atualização, effective/superseded, retrieved date, accessible mirror URL, provisions consulted).
3. Add a staleness-management note: re-verify annually, bump the dated filename + entry when the última atualização advances, and for a prior fiscal year apply the redação in force then (incl. transitional norms) rather than reading the consolidated base directly (#31, project-guidelines #2).
4. Cite the local mirror (not the live URL) from derived cross-reference notes once mirrored.

**Distinguishing from the "official archive wins over secondary" lesson, #31, #37:** that lesson = a locally-archived official source outranks a conflicting secondary. #31 = cite the redação in force for the target fiscal year. #37 = when a verification TOOL quotas out, switch transport (curl/pdftotext) rather than abandoning verification. #39 = the upstream decision to MIRROR the authoritative source in the first place so that the "official archive wins over secondary" lesson and #37 have a local artifact to fall back to - "living code" does not excuse skipping it.


## 40. Wiring Discoverability for a Newly Mirrored Source When the Instruction Entrypoint Is at the Size Ceiling

**Principle:** Discoverability + instruction-size-budget discipline. The `done` Step 2.6 obligation ("new reference material must be discoverable from the instruction paths future agents read") has to hold even when `AGENTS.md` is at the 30,720-byte gate and a net-new bullet will not fit.

**Trigger:** The session mirrors new official sources (or adds reusable reference material) and needs to wire them into the always-loaded instruction entrypoint (`AGENTS.md`/`CLAUDE.md` §5 "Domain Knowledge References"), but the entrypoint has near-zero size headroom.

**Rule:** Two techniques, in priority order. (1) If the reference has a DISTINCT seeker path (a reason an agent would look for it that no existing bullet's trigger covers), it deserves a dedicated bullet: COMPACT duplicate or verbose §5 bullets to make room rather than skip it - merge two bullets citing the same doc, and drop parentheticals that duplicate the linked doc's own contents. (2) Only if compaction cannot free enough, or the reference is already reached by an existing bullet's trigger, surface it by NAME inside that existing bullet (cheap - rename "the X PDF" to "the X/Y/Z PDFs") and route the CONCRETE PATH through the size-ungated Layer-2 doc the bullet already points to (`project-guidelines.md` #N, folder `README.md`, or `sources.md`). In both cases put the full path, dated-filename pattern, `sources.md` entry numbers, and use-cases in the Layer-2 doc; keep the entrypoint bullet as the one-line pointer; and verify the chain resolves. Do NOT let the size budget be the reason a mirror stays undiscoverable, and do NOT overflow the gate.

**What happened (2026-06-27 CIRS/CPPT/CIS discoverability):** After mirroring the three consolidated codes, the high-traffic paths still described them abstractly - `AGENTS.md` §5 said "verify against the consolidated CIRS PDF" with no hint a local mirror existed, and `project-guidelines.md` #3 said "cross-check against the current consolidated CIRS PDF" with no path. `AGENTS.md` was at 30,703/30,720 bytes (17 bytes of headroom). First pass (technique 2): renamed the §5 bullet to "the consolidated CIRS/CPPT/CIS PDFs" (+10 bytes, within budget) and put the concrete `official/` folder path, the dated-filename pattern, the `sources.md` entry numbers (4/5/6), and the CPPT/CIS use-cases into `project-guidelines.md` #3. That left a residual gap: a prazo-only seeker (who never reads the CIRS-trigger bullet) would not discover the CPPT mirror. Second pass (technique 1): the CPPT reference HAS a distinct seeker path (reclamação/impugnação prazos), so it deserved its own bullet; merged the two duplicate `plan_quality_guidelines.md` bullets and trimmed the verbose root-cause-catalog parenthetical, freeing ~200 bytes, and added a dedicated "Before advising on an IRS reclamação/impugnação prazo, verify against the mirrored CPPT" bullet - still under the gate (30,715/30,720).

**Why this happens:** Discoverability cross-refs land last (after the mirror and provenance are written), by which point the entrypoint is often near its ceiling from the session's earlier instruction edits. The instinct to add a dedicated §5 bullet per new source then collides with the size gate.

**Required behavior:**
1. For every source mirrored or reference doc added this session, confirm a future agent can reach it from an always-loaded entrypoint (run the done Step 2.6 check explicitly - do not assume `learn` wired it).
2. If the entrypoint is at the size ceiling, surface the reference by NAME in an existing bullet and put the concrete path + use-cases in the size-ungated Layer-2 doc that bullet points to.
3. Verify the chain resolves: entrypoint name -> Layer-2 path -> file. Re-run the instruction-size gate (`check-instruction-size.sh gate`) after the entrypoint edit.

**Distinguishing from done Step 2.6 and #39:** done Step 2.6 states the discoverability OBLIGATION for new reference material. #39 is the decision to MIRROR the source at all. #40 is the TECHNIQUE for making the mirror discoverable when the entrypoint size budget blocks a dedicated bullet - route the path through the Layer-2 doc the existing bullet already names.


## 41. Mandatory Fields on One Filing Record Share One Error Contract

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

## 42. A Magnitude/Materiality Gate That Belongs to One Decision Must Not Be Propagated to a Sibling Decision When Porting the Surrounding Logic

**Principle:** Family B (Error-policy propagation) - a fallible threshold check (the `> 1 EUR` materiality gate) was reused at a new decision site (branch routing) without carrying over the original code's policy that the gate never applied there.

**Trigger:** You are porting, refactoring, or "elevating" a function (e.g. per-lot to event-level, single-call to multi-call, inline to extracted helper) whose body combines TWO independent decisions: a discrete routing decision (e.g. agree vs conflict branch) and a separate reporting decision (e.g. whether to set a review flag) that happens to share a discriminator with the first. The original code applied a magnitude/materiality gate to only ONE of the two decisions.

**Rule:** When porting logic that contains a threshold gate, identify EVERY decision the original code made and confirm which decisions the gate did and did not apply to. The gate's scope must be preserved verbatim at the new call site. Do NOT let the gate "naturally extend" to a sibling decision because the sibling reads the same fields or because the gate "feels like a sensible significance check" for that branch. Branch routing that the original code made PURELY on sign (or another primitive comparator) must remain sign-only; the magnitude gate stays on the review-flag decision where the original put it.

**What happened (2026-07-05 OGR event-level port, Task 1):** The legacy `_apply_ogr_direction_override` decided `direction_conflict` PURELY on sign - `(ogr < 0) != (cg < 0)` - and applied the `> 1 EUR` absolute-magnitude gate ONLY to the review flag (so trivially small conflicts do not produce a noisy "YES: ..." review row). When porting to `apply_ogr_event_level` (event-level aggregation), the first draft applied the `> 1 EUR` gate to the BRANCH decision too, treating sub-1-EUR sign conflicts as "agree". This broke `test_single_lot_conflict_byte_identical`: a CG +4.00 / OGR -1.00 event must take the conflict branch (final = -4.00, material), but the gated draft routed it to the agree branch and produced +4.00. The fix made `_decide_event_branch` sign-only and kept the `> 1 EUR` gate on the review flag via `_conflict_review_state` / `_agree_review_state`. See lesson #92 for the dual-decision structure (this lesson is the threshold-scope refinement that #92 does not state).

**Why this happens:** When a function is rewritten at a higher abstraction level, the porter reads the original top-to-bottom and tends to fold "similar-looking" checks together. A magnitude gate that reads `if abs(...) > 1 EUR` next to a sign check feels like a unified "is this significant?" guard, so the porter applies it to the branch condition as well as the flag. The original code's separation (sign = routing policy; magnitude = reporting/noise policy) is implicit and easy to collapse.

**Required behavior:**
1. Before porting, enumerate the decisions in the original function (routing, flagging, value selection) and, for each threshold gate, record WHICH decision(s) it gates by reading every branch the gate's result flows into.
2. Write that mapping as a comment on the new helper (e.g. `# branch decision is sign-only; the > 1 EUR gate applies only to the review flag`).
3. Add a byte-identical RED test for the boundary case (a sub-gate-magnitude conflict that the original routed to the conflict branch, not the agree branch) so a future collapse fails loudly.
4. In code review, treat "this draft added a magnitude check to a branch condition that the original made on sign alone" as a finding, even when the new test suite passes overall - the new tests may not include the boundary case.

**Distinguishing from Family C (sentinel vs None vs exception):** Family C is about how "absent/invalid" is represented differently across two consumers. This lesson is about a threshold whose SCOPE (which decision it controls) is the policy distinction that drifted, not the threshold's representation.

**See also:** Lesson #92 (OGR Directional Authority vs Wholesale Replacement - the dual-decision structure this refines), CLAUDE.md §4 Agent Workflow Rules (re-read each RED test against current design invariants before flipping GREEN).

## 43. Lock Key-Resolution Rules from Field Semantics, Not Population Counts

**Principle:** Family H (Verify the real thing, not the abstraction) - field NAMES and population COUNTS are abstractions over field SEMANTICS; locking an identifier-precedence or merge key from prevalence alone risks collapsing semantically distinct fields into one. Compounded by Family D (Single source of truth) - the original design tried to make one derived `tx_id` field stand in for three fields that do not represent the same concept.

**Trigger:** You are designing a key-resolution rule (an identifier precedence, a dedup key, a correlation key, a grouping key) over candidate fields whose VALUES you have not yet classified by what they MEAN. The plan or task asks you to "lock the precedence from the data" by counting which candidate field is most populated, then "first non-empty of (A, B, C)" becomes the key. The candidate fields have similar-sounding names (e.g. `TxHash`, `TxSrc`, `TxDest`) and live in the same source row.

**Rule:** Before locking any key-resolution rule from empirical data, classify each candidate field's SEMANTICS (what real-world entity does this value identify?) and verify they represent the SAME concept. Population frequency answers "which field is most often non-empty"; it does NOT answer "are these fields interchangeable as identifiers". If two candidate fields can both be highly populated yet represent different concepts (e.g. on-chain transaction hash vs wallet address), a "first non-empty" precedence will silently collapse the wrong fields into the same key, and a triple-equality key built from the same set will FRAGMENT logical groups that share the real identifier but differ on the orthogonal fields. Either classify the candidates as semantically equivalent before locking precedence, or store them as independent fields and derive the key from the single field that represents the identifier concept.

**What happened (2026-07-05 th-tx-view Phase A, Task 1):** The original plan instructed Task 1 to lock a `tx_id` precedence over `(TxHash, TxSrc, TxDest)` by running a prevalence script over production Koinly CSVs and choosing the most-populated field per `Type`. The script ran cleanly (TxHash dominated every populated Type), and the proposed chain was "first non-empty of (TxHash, TxSrc, TxDest)". User push-back flagged that the three fields have distinct semantics (TxHash is the on-chain identifier; TxSrc/TxDest are wallet addresses). A follow-up semantics study over 125,468 production rows confirmed: TxSrc/TxDest never equal TxHash on the same row; in 398 production two-leg transfer clusters (withdrawal + deposit) the legs SHARE TxHash but MIRROR addresses (`withdrawal.TxSrc == deposit.TxDest`); one exchange hot-wallet address collapses 53,685 deposit rows. A triple-equality key would have fragmented every transfer cluster (the legs would not compare equal); a precedence chain would have silently treated a wallet address as a tx-id when TxHash was absent. The amendment: `TransactionHistoryRow` stores all three fields separately; `TxCorrelationKey.tx_id` derives from `tx_hash` alone.

**Why this happens:** Empirical "what is populated most" scripts are easy to write and feel rigorous, so the plan author treats the prevalence table as the answer. But population counts measure NON-EMPTINESS, not IDENTITY-OF-CONCEPT. Two fields can both be 100% populated and still represent different things. Without a semantics check (co-occurrence matrix, value-shape classification, cross-row grouping signal, multi-leg cluster inspection), the precedence lock is a guess about field meaning dressed up as a measurement.

**Required behavior:**
1. Before locking any identifier-precedence or merge key, classify each candidate field's semantics: what real-world entity does the value identify? Use direct inspection of value shapes (length, alphabet, format), co-occurrence with other candidate fields on the same row, and - for fields that purport to identify transactions - cross-row grouping behavior (does the same value recur across rows that should logically cluster?).
2. Verify the candidates are SEMANTICALLY EQUIVALENT before locking precedence. If they are not, do not collapse them into one field; store them separately and derive the key from the field that represents the identifier concept.
3. For grouping/correlation keys, inspect at least one multi-record logical cluster in production data (e.g. a two-leg transfer) and confirm the proposed key keeps the cluster together. If the key fragments the cluster, the key is wrong, even if every individual field is highly populated.
4. In plan review, treat any "lock precedence from prevalence counts" task as INCOMPLETE unless the task also requires a semantics/classification step. A prevalence table alone is not enough to lock a key-resolution rule.
5. Stale comments in source code that assert field semantics ("Real exports store the transaction hash in TxSrc") are not authoritative; verify against current data before either trusting or rewriting them.

**Distinguishing from Family B (Error-policy propagation):** Family B is about a threshold or fallible op being reused at a new site without carrying over the original policy. This lesson is about a KEY-RESOLUTION RULE being locked from the wrong evidence (counts vs semantics) - the failure is in the locking methodology, not in porting an existing rule to a new site.

**Distinguishing from Family C (sentinel vs None vs exception):** Family C is about how "absent/invalid" is represented. This lesson is about how "the identifier" is chosen when multiple candidate fields exist - the failure is conflating fields that look like identifiers but represent different concepts, not misrepresenting absence.

**See also:** `docs/history/plans/2026-07-05-th-tx-view-phase-a.md` (Amendment 2026-07-06), `docs/tmp/phase-a-tx-id-semantics.md` (the semantics study), CLAUDE.md §3 Repository Constraints (TxCorrelationKey derives from `tx_hash` alone).

## 44. Test-Helper Platform Attribution Must Mirror the Production "Unknown" Skip Rule

**Principle:** Family C (Representation: sentinel vs None vs exception) - the project's `normalize_platform_name` returns the literal string `"Unknown"` (not `None`, not `""`) for empty wallet input, and that literal is TRUTHY in Python. A naive `tr.sending_wallet or tr.receiving_wallet` therefore misattributes a row whose sending wallet is empty: the `or` short-circuits past the truthy `"Unknown"` and never reaches the populated receiving wallet. Compounded by Family H (Verify the real thing, not the abstraction) - the plan's verify snippets used the simpler form, which is correct for the treatment-resolver path (it never consults `wallet_kind`) but DIVERGES from production for any test that asserts on `wallet_kind` or `TxCorrelationKey.requires_review`.

**Trigger:** You are writing a corpus/characterization test (or any helper that derives a per-row platform from a `TransactionHistoryRow`) and need a single platform string to feed `classify_platform` or `build_transaction`. The plan or a sibling test snippet offers `tr.sending_wallet or tr.receiving_wallet` as the per-row platform attribution. The scenario fixtures include rows whose sending wallet is empty (e.g. a borrowing-side `crypto_deposit` receiving an asset at an exchange, where the Koinly `Sending Wallet` column is blank).

**Rule:** Any test-side per-row platform attribution helper MUST replicate the production `_row_platform` rule: strip, then skip when the value is empty OR equal (case-insensitively) to the literal `"Unknown"`. Do NOT use the bare `tr.sending_wallet or tr.receiving_wallet` form. The production helper lives in `tax_reporting.application.crypto.wallet_kind._row_platform`; mirror it byte-for-byte (including the case-insensitive `"unknown"` comparison) so a future change to either side surfaces as a test divergence rather than a silent misclassification.

**What happened (2026-07-07 th-tx-view Phase C, Task 7):** The plan's Task 4/5/6 verify snippets used `p = tr.sending_wallet or tr.receiving_wallet` for per-row platform attribution. This is correct for the treatment-resolver path (which reads `row.tag` and `row.sending_currency` only, never `wallet_kind`), but for the `loan_affected_rebuild` scenario's `Tag="Loan"` `crypto_deposit` row (receiving WBTC at ByBit, sending wallet blank) the bare `or` resolves to `"Unknown"` (truthy) and the row classifies as UNKNOWN instead of CEX. The production evidence aggregator `_row_platform` skips `"Unknown"` and falls through to the receiving wallet (ByBit -> CEX). The corpus test helper was authored to mirror `_row_platform` exactly so the DEX/CEX review-flag assertions on `dex_cex_tx_id_absence` and the borrowing-row classification on `loan_affected_rebuild` match production.

**Why this happens:** Python's `or` treats any non-empty string as truthy, including the literal `"Unknown"`. The production code deliberately uses `"Unknown"` as a sentinel for "no platform signal" (rather than `None` or `""`) because downstream rendering wants a displayable label. A test author copying a plan snippet has no signal that `"Unknown"` is a sentinel; the form looks correct and passes for any row whose sending wallet is populated. The trap only fires on rows with an empty sending wallet (borrowing-side deposits, some exchange-to-exchange transfers), which are exactly the rows where `wallet_kind` classification is load-bearing for review-flag assertions.

**Required behavior:**
1. Before writing a test-side platform attribution helper, read `wallet_kind._row_platform` and mirror its skip rule (empty OR case-insensitive `"unknown"` -> fall through to the other wallet; both empty/Unknown -> `None`).
2. Do NOT use `tr.sending_wallet or tr.receiving_wallet` in test helpers, even when a plan verify snippet uses that form. The plan snippet is a shorthand for the treatment-resolver path, not a general per-row platform attribution.
3. When a test asserts on `wallet_kind` or `TxCorrelationKey.requires_review` for a row with an empty sending wallet, add a comment naming `_row_platform` as the authority and the borrowing-side deposit as the discriminating case.
4. In code review of corpus/characterization tests, treat `tr.sending_wallet or tr.receiving_wallet` as a finding when the test also asserts on `wallet_kind` or the review flag; the form is only safe for treatment-resolver-only assertions.

**Distinguishing from Family D (Single source of truth):** Family D is about a fact being authoritative in two places and one drifting. This lesson is about a SENTINEL representation (`"Unknown"` as truthy string vs the implicit `None`/`""` the `or` operator assumes) that, when replicated in a test helper, silently misclassifies rows. The fix is to mirror the production skip rule, not to deduplicate the platform-attribution logic into a single shared function (the test helper legitimately cannot import the private `_row_platform` without breaking layering).

**See also:** `src/tax_reporting/application/crypto/wallet_kind.py` (`_row_platform`, lines 164-177), `docs/history/plans/2026-07-07-th-tx-view-phase-c.md` Task 7, CLAUDE.md §3 Repository Constraints (wallet labels are discovery hints only).

## 45. Shadow/Verification Scripts Must Reuse the Production Reader (Not `csv.DictReader`)

**Principle:** Family H (Verify the real thing, not the abstraction) - a throwaway shadow/diff/verification script that re-parses an external-report CSV must call the SAME production reader the pipeline uses, not a stdlib `csv.DictReader`. The production reader carries accumulated edge-case handling (preamble skipping, encoding, header-index detection) that the script author has no signal to rediscover. Compounded by Family G (Data-loss observability) - the divergence surfaces as a row-count mismatch or a phantom row that silently inflates the diff, with exit 0 because the script "successfully" parsed something.

**Trigger:** You are authoring a verification/shadow/diff script under `{tmp_dir}` (throwaway, deleted at end of phase) that loads an external-report CSV (Koinly, IB, etc.) to compare a legacy path against a new path row-by-row. The plan says "load the CSV and iterate". The natural Python stdlib reflex is `csv.DictReader(open(path))`.

**Rule:** Any throwaway or test-side script that re-parses an external-report CSV already handled by production MUST call the production reader (e.g. `read_koinly_rows` for Koinly transaction history). Do NOT use `csv.DictReader` or a hand-rolled `csv.reader` loop. The production reader carries `_detect_header_index` (preamble skip) and any column normalization; a naive `DictReader` will either (a) treat the preamble as a phantom row that fails `parse_th_row` and aborts the script, or (b) silently inflate the row count by 1, breaking the "CSV row count == TH row count" invariant.

**What happened (2026-07-07 th-tx-view Phase C, Task 9):** The Phase C shadow script `docs/tmp/phase-c-shadow/shadow_run.py` (throwaway; deleted in Task 11) iterates Koinly transaction-history rows to compare the legacy treatment-intent path against the Phase-A/B resolver path. Koinly TH CSVs begin with a preamble line ("Transaction report 2025"). A naive `csv.DictReader` would treat the preamble as a phantom data row: either `parse_th_row` raises on it (aborting the script), or the row count drifts by 1 (violating Invariant 7: "exit 0 iff CSV row count == TH row count"). The script was authored to call `read_koinly_rows` (production reader with `_detect_header_index`) so the count matches the production parser's count exactly.

**Why this happens:** The Koinly export format prefixes the actual header row with a human-readable report-title line. The production reader detects the header index by scanning for the known column names; a stdlib `DictReader` assumes row 0 is the header. There is no stdlib signal that "row 0 is a preamble" - the knowledge lives in the production reader. A throwaway-script author reaching for the stdlib reflex has no trigger to recall this; the script appears to work on any well-formed CSV that happens to start with a header.

**Required behavior:**
1. Before authoring a verification/shadow script that re-parses an external-report CSV, grep production for the existing reader (`read_koinly_rows`, `read_ib_rows`, etc.) and call it.
2. Do NOT use `csv.DictReader` or hand-rolled `csv.reader` loops for any external report format that has a known production reader, even in throwaway scripts under `{tmp_dir}`.
3. When the script's exit-code gate compares a row count (e.g. "CSV rows == TH rows"), document the reader-reuse decision in a comment naming the production reader as the authority.
4. In code review of throwaway scripts, treat `csv.DictReader(open(<external report path>))` as a finding when a production reader exists for that format; the divergence will surface as a phantom row or an abort.

**Distinguishing from Family D (Single source of truth):** Family D is about a fact being authoritative in two places and one drifting. This lesson is about a parser implementation detail (preamble skipping) that the stdlib does not carry; the fix is to delegate parsing to the production reader, not to deduplicate the parsing logic. The throwaway script legitimately cannot import production pipeline stages (it is invoked by absolute path and must not couple to `tax_reporting.main`), but it CAN and MUST import the leaf-level reader functions whose edge-case handling it depends on.

**See also:** `src/tax_reporting/infrastructure/koinly_parser.py` (`read_koinly_rows`, `_detect_header_index`), `docs/history/plans/2026-07-07-th-tx-view-phase-c.md` Task 9.

## 46. A Regression Test Must Exercise the Production Path It Claims to Guard (Not an Adjacent Derived Value)

**Principle:** Family H (Verify the real thing, not the abstraction) - a regression test that claims to guard a specific production code path must actually invoke THAT path (or an assertion-equivalent trace through it), not assert on a value derived from an adjacent/orthogonal path that would pass even if the guarded path regressed. The test NAME and docstring are abstractions over which path is exercised; the regression-catch property is a property of the actual call chain, not of the test's stated intent. Compounded by Family G (Data-loss observability) - the silent failure mode here is "test suite green while the guarded production behavior is broken", which is strictly worse than no test at all because it suppresses the signal a real bug would produce.

**Trigger:** You are authoring a characterization or regression test whose docstring says it guards a specific production behavior (a timezone fix, a dedup guard, a threshold gate, a normalization rule). The natural authoring reflex is to assert on the most accessible derived value (a composite key field, an aggregated total, a parsed intermediate). Before settling on that assertion, ask: "If I reverted the production change this test claims to guard, would this assertion fail?" If the answer is "no" or "I'm not sure", the test passes for the wrong reason.

**Rule:**
1. For every regression test, identify the EXACT production call site the test claims to guard (function, kwarg, line). The assertion must invoke that call site or a production path that transitively invokes it.
2. Before merging the test, run the revert check: comment out / revert the guarded production change and confirm the test fails. If it passes, the assertion is on the wrong path; expand it to exercise the guarded path directly.
3. The test docstring must state WHICH production path it exercises (function + the discriminating kwarg/branch), not just WHICH user-visible property it pins. A docstring that names a property without naming the code path leaves a future reader unable to tell whether the test still guards the path after refactors.
4. When a fix has two halves (e.g. a TH-side composite key AND a CG-side localized date that must carry the same instant), a test that asserts only one half does NOT prove the join; it proves that half in isolation. The docstring must scope the assertion to what it actually proves and must not claim the join/end-to-end property is verified.

**What happened (2026-07-08 th-tx-view Phase C review r1+r2, Findings 1):** The corpus test `test_summer_time_drift_uses_utc_instant` was authored to guard the summer-time-drift fix: a naive `parse_koinly_datetime("15/07/2025 00:30")` call (no `zone=` kwarg) re-stamps the CG date as UTC `2025-07-15T00:30:00Z`, but the production CG-date parsing path in `crypto_reporting.py::_parse_capital_gains_file` passes `zone=context.zone` (PT: `ZoneInfo("Europe/Lisbon")`) so the instant localizes to `2025-07-14T23:30:00Z`, matching the TH composite key. The original test asserted only on the TH-side `key.composite.utc_instant` value (`2025-07-14T23:30:00Z`), which is derived from the TH parsing path, NOT the CG parsing path. Reverting the `zone=` kwarg from the production CG-date call site would leave the TH-side assertion GREEN (it does not touch the CG path), so the test "passed for the wrong reason" - it did not exercise the production code path it was named after. The r1 fix added a CG-side assertion that called `parse_koinly_datetime(row["Date Sold"], zone=lisbon_zone)` directly with a test-local `ZoneInfo("Europe/Lisbon")`, but because the test supplied the zone itself the assertion never reached the production call site; an r2 review empirically confirmed a `zone=context.zone` revert on line 557 left the test GREEN (Family H re-introduced by the r1 fix itself). The r2 fix rewrote the CG-side assertion to invoke the production function directly: construct a `CapitalGainsParsingContext(zone=ZoneInfo("Europe/Lisbon"))`, call `_parse_capital_gains_file(cg_path, context)`, and assert `entries[0].disposal_timestamp == "2025-07-14 23:30"`. The expanded assertion was verified to fail under a `zone=context.zone`-kwarg revert (REGRESSION CAUGHT comment names the failure mode and the production line).

**Why this happens:** A regression test is usually authored AFTER the fix lands, against the post-fix fixture. The most accessible value to assert on is the one the test builder can read directly from the composite key or the aggregated output, not the one buried inside a production parsing call site. The builder reasons "the composite key reflects the fix, so asserting on it guards the fix" - but the composite key is assembled on a DIFFERENT path than the CG-date localization, and the two paths can drift independently. The test builder has no signal that the two paths share no code, because the test NAME ("uses UTC instant") and the fix's user-visible property (the instant value) obscure which path produced the asserted value.

**Distinguishing from lesson #43 (Lock Key-Resolution Rules from Field Semantics):** #43 is about deriving a key from the SEMANTICS of fields rather than the prevalence of their values. This lesson is about a test's assertion exercising a different CODE PATH than the production call site the test claims to guard, even when both paths produce the same value. #43's failure mode is "the key collapses semantically distinct fields"; this lesson's failure mode is "the test passes while the guarded production path is broken".

**Distinguishing from lesson #44 (Test-Helper Platform Attribution Must Mirror Production):** #44 is about a test HELPER diverging from production's skip rule, producing a different value than production would. This lesson is about the test ASSERTION targeting a value produced by an adjacent path, regardless of whether any helper diverges. #44's fix is to mirror the production skip rule in the helper; this lesson's fix is to expand the assertion to invoke the guarded production call site.

**Required behavior:**
1. When authoring a regression test, name the guarded production call site in the docstring (function + the discriminating kwarg/branch/line).
2. Before merging, run the revert check: revert the guarded production change and confirm the test fails. If it passes, the assertion is on the wrong path.
3. When a fix has multiple halves that must agree, the docstring must scope each assertion to the half it exercises; do not claim the join or end-to-end property is verified unless the test asserts on the joined output.
4. In code review of regression tests, treat "test name claims to guard X but no assertion invokes X's production path" as a finding even when all assertions pass; green is not sufficient when the assertion is on an adjacent path.

**See also:** `src/tax_reporting/application/crypto_reporting.py::_parse_capital_gains_file` (production CG-date parsing with `zone=`), `src/tax_reporting/infrastructure/koinly_parser.py::parse_koinly_datetime`, `tests/unit/application/test_phase_c_corpus.py::test_summer_time_drift_uses_utc_instant`, `docs/history/reviews/2026-07-08-th-tx-view-phase-c-code-review-r1.md` Finding 1.

## 47. Renaming Fixture Paths or Filenames Requires a Multi-Pattern Grep Across All Tests (Conftest Constants Are an Abstraction Over Scattered References)

**Principle:** Family H (Verify the real thing, not the abstraction) - a conftest path constant (`KOINLY_2025_ZERO_BASIS_EXAMPLE_DIR = Path("...")`) is an abstraction over the many concrete places that reference the fixture path or filenames: test docstrings, inline `_FIXTURE_DIR / "koinly_..._synth.csv"` joins, glob patterns (`glob("koinly_2025_capital_gains_report_*.csv")`), and prose comments. Updating the constant alone leaves the scattered references stale. Compounded by Family G (Data-loss observability) - a stale glob pattern silently matches zero files, so a test that should load the fixture either skips silently or fails with a confusing "file not found" that does not name the rename as the cause.

**Trigger:** You are renaming or moving fixture files/directories (e.g. `koinly2025_zero_basis/` -> `2025/koinly/zero_basis/`, or dropping a `_synth.csv` filename suffix). The natural reflex is to update the conftest path constant, update the test files you remember touch this fixture, and run the suite. Before stopping, ask: "Have I grepped ALL test files (`tests/`) for EVERY shape the rename touches - the directory name, the filename, the filename stem, and the glob pattern - not just the conftest constant?"

**Rule:**
1. When renaming a fixture path or filename, run a multi-pattern grep across ALL test files for EVERY shape the rename touches, in one pass:
   - the directory name (old and new): `grep -rn 'koinly2025_zero_basis\|2025/koinly/zero_basis' tests/`
   - the full filename (old and new): `grep -rn 'koinly_2025_capital_gains_report_synth\|koinly_2025_capital_gains_report\.csv' tests/`
   - the filename stem as a glob prefix: `grep -rn 'koinly_2025_capital_gains_report_\*\|koinly_2025_capital_gains_report\*' tests/`
   - any docstring or prose mention of the old path/filename
2. Update conftest constants AND every scattered reference in the same commit; do not leave a follow-up "I'll catch the rest later" because the test suite will not surface all stale references at once (some are in `@pytest.mark.skip`'d tests, some in docstrings that are never executed).
3. When the rename drops a token that a hygiene check enforces as a synthetic-data marker (e.g. `_synth.csv` suffix), the hygiene check MUST evolve in the same commit - either to scope by path (`under example/<year>/koinly/`) or to validate canonical naming via regex. Deleting the hygiene check entirely (on the theory that "the path now identifies it") loses the canonical-naming enforcement and lets non-canonical filenames leak in later.
4. After the rename, run the full test suite (not just the obviously-affected test file); stale glob patterns in unrelated test files fail only when those tests run.

**What happened (2026-07-08 fixture-layout-realign refactor):** The refactor moved 10 fixture folders to a new layout (`koinly2025_<scenario>/` -> `2025/koinly/<scenario>/`) and dropped the `_synth.csv` filename suffix. The initial sweep updated `tests/conftest.py` constants and the obviously-affected test files, but missed:
- `tests/end_to_end/test_crypto_zero_basis_materiality.py` - docstring still named `koinly2025_zero_basis` and an inline `_FIXTURE_DIR / "koinly_2025_capital_gains_report_synth.csv"` reference; caught only in a final verification sweep after unrelated tests started failing.
- Multiple test files used glob patterns like `koinly_2025_capital_gains_report_*.csv` that required the `_` separator before the wildcard; after the `_synth` suffix was dropped the filename became `koinly_2025_capital_gains_report.csv` (no match). The patterns had to be relaxed to `koinly_2025_capital_gains_report*.csv`.
- `test_example_report_generation.py` had a hygiene check enforcing `_synth.csv` / `_example.csv` as the synthetic-data marker; dropping the suffix broke the check, which had to be reworked to scope by path (`example/<year>/koinly/`) and validate canonical naming via regex `^koinly_\d{4}_.*\.csv$`.
- `README.md:138` and a walkthrough doc still referenced `example/koinly2024/`; missed in the initial doc sweep.

The conftest path constant looked like a single source of truth, but the fixture path was referenced in 5+ test files plus docs in shapes the constant did not cover (docstring prose, glob patterns, inline joins, hygiene regex).

**Why this happens:** Test fixtures are referenced in more shapes than production code: production code reads fixtures through one reader function with one glob; tests reference them through conftest constants, inline path joins, glob patterns, docstring examples, and hygiene assertions. A rename that "follows the imports" finds the conftest and direct callers but misses the prose and glob references. The conftest constant is an abstraction; the scattered references are the real thing.

**Distinguishing from lesson #44 (Test-Helper Platform Attribution Must Mirror Production):** #44 is about a test HELPER diverging from production's skip rule. This lesson is about scattered REFERENCES to a fixture path/filename diverging from the conftest constant after a rename. #44's fix is to mirror the production skip rule; this lesson's fix is to grep every shape of the rename across all tests and docs.

**Distinguishing from CLAUDE.md "grep ALL test files" rules (function signature changes, output text changes, data-flow semantics):** Those rules cover three specific shapes (callers of changed functions, row-locators matching stale labels, assertions referencing affected identity tuples). None of them cover fixture path/filename renames. This lesson extends the same discipline to a fourth shape: fixture path and filename references in docstrings, globs, inline joins, and hygiene checks.

**Required behavior:**
1. Before committing a fixture rename, grep ALL test files for the directory name, the filename, the filename stem as a glob prefix, and prose mentions - in one multi-pattern pass per shape.
2. Update conftest constants AND every scattered reference in the same commit; do not defer.
3. When the rename invalidates a hygiene check that enforced the renamed token as a marker, evolve the check in the same commit (path-scope + canonical-naming regex), do not delete it.
4. Run the full test suite after the rename, not just the obviously-affected test file; stale references in unrelated tests surface only when those tests run.
5. Grep docs (`README.md`, walkthrough docs, maintenance docs) in the same pass; the conftest constant does not cover prose references.

**See also:** `tests/conftest.py` (`KOINLY_2025_*_EXAMPLE_DIR` constants), `tests/end_to_end/test_example_report_generation.py` (synthetic-filename hygiene check, reworked to path-scope + canonical-naming regex), `tests/end_to_end/test_crypto_zero_basis_materiality.py` (missed in initial sweep), branch `2026-07-08-fixture-layout-realign` commit `df1982a`.

## 48. Plan Wiring Steps Must Trace the Entry-Point Guard at the Receiving Call Site (Passing a Kwarg Is Not the Same as Firing the Code Path)

**Principle:** Family H (Verify the real thing, not the abstraction) - a plan wiring instruction that says "pass `registry=<adapter>` at the call site to enable X" is an abstraction over the receiving function's control flow. The plan trusts the framing ("registry-only classification") without reading the entry-point guard that decides whether the block runs at all. Compounded by Family E (Temporal / ordering invariants) - the guard was written for a two-input contract (`th_rows AND registry`); passing only one input leaves the block unreachable, and the abstraction ("registry classification") does not surface the missing precondition.

**Trigger:** You are writing (or reviewing) a plan wiring step that says "enable behavior X at call site Y by passing kwarg K" or "flip flag F to route through code path Z". The natural reflex is to write the kwarg-pass instruction and move on. Before stopping, ask: "Have I read the FIRST executable line inside the receiving function to confirm my kwarg is not silently gated by an `if <other-kwarg> is not None:` (or a `if not flag:` early-return)? Have I grepped for the actual production caller of the receiving function, not the caller I remember?"

**Rule:**
1. When a plan wiring step propagates a new kwarg or flag to enable a code path, read the receiving function's opening lines (guards, early returns, `if`-gates) BEFORE writing the wiring instruction. If any guard references a DIFFERENT kwarg/flag that the plan does not also address, the wiring is incomplete: either widen the guard or widen the kwarg propagation.
2. When a plan wiring step names a production caller by memory ("`load_koinly_crypto_report` calls X"), grep-verify: `grep -rn 'X(' src/`. Trust the grep, not the mental model.
3. When a plan validates a change with a shell command (`check-no-em-dash.sh`, `pytest`, `ruff`), verify the command actually validates - run it once with a KNOWN violation in scope and confirm it fails. A script that prints usage and exits 0, or a `grep -f <missing-file>` that returns exit 1 for the wrong reason, is a silent no-op gate that the plan claims is a release gate.
4. Under review, when a plan claims "call site Y now fires code path Z under condition C", verify the claim by tracing: read call site Y, then read Y's callee's guards, then confirm Z is reachable under C. Do not accept plan prose as evidence.

**What happened (2026-07-08 Phase D plan Quality Gate, r3+r4+r5):** The Phase D plan for the TH-anchored transaction view landed the same Family H failure three times across sub-agent review rounds:
- **r3 N1:** Validation Commands and Task 11 both invoked `~/.ai-playbook/scripts/check-no-em-dash.sh` bare. The script requires a subcommand (`file`, `staged`, `touched`, `stdin`); a bare invocation prints usage and exits 0 without scanning anything. The plan's em-dash release gate was a silent no-op that the author never ran with a known em-dash to verify. Fixed by using `check-no-em-dash.sh touched` in both places.
- **r4 N1:** Task 1's wiring step named `crypto_reporting.py::load_koinly_crypto_report` as the caller of `write_assumptions_and_methodology_sheet`. Actual caller (verified via `grep -rn "write_assumptions_and_methodology_sheet" src/`) is `generate_tax_report` at `workbook_builder.py:169`. The plan author remembered the wrong caller; the implementer following the plan would have looked in the wrong file and stalled at GREEN time.
- **r5 N1:** Task 1's amended wiring step asserted "passing `registry=<adapter>` at `workbook_builder.py:169` (without `th_rows`) causes every platform to classify via the registry OR fall through to UNKNOWN." But `assumptions_sheet.py:111` gates the entire classification block behind `if th_rows is not None:`; when `th_rows=None`, the block is skipped and the registry is NEVER consulted (the Kind column stays BLANK, not UNKNOWN). The plan trusted the framing "registry-only classification" without reading the guard. Fixed by amending Invariant 5 to also permit widening the gate to `if th_rows is not None or registry is not None:` (option (ii)).

All three failures are the same shape: the plan claims a mechanism will fire at a call site, but the entry-point guard at that site (or the receiving-function's early gate, or the shell script's argument-required check) was not read. Each was a plan-time reasoning failure, caught only because the quality gate runs multiple review rounds with source verification.

**Why this happens:** Plan-writing operates on framings ("wire the resolver through", "enable the registry path", "gate the em-dash check"). Framings are abstractions over the actual call chains, guard conditions, and script contracts. When a plan's wiring step describes an intent without tracing the concrete code path, the abstraction can be internally coherent (the intent makes sense) while being unimplementable (the guard prevents the intent from firing). A review round that reads only the plan text catches naming and citation errors but not behavior claims - those require sub-agent source verification, which is why the plans skill Quality Gate mandates zero-Blocker-zero-Medium on the LATEST round, not the sum.

**Distinguishing from lesson #46 (regression test must exercise the guarded path):** #46 is about TEST code that claims to guard a path but exercises an adjacent one. This lesson is about PLAN WIRING STEPS that claim to enable a path but omit the guard preconditions. Both are Family H; #46's fix is to trace the test's actual call chain, this lesson's fix is to trace the plan's proposed call chain BEFORE writing the wiring step.

**Distinguishing from lesson #40 (verify code-branch-vs-authority-discriminator):** #40 is about verifying that code branches on every discriminator an authority cites. This lesson is about verifying that a plan's proposed kwarg propagation actually reaches the intended code path (not blocked by a sibling guard). #40 applies at implementation time; this lesson applies at plan-writing time.

**Required behavior:**
1. Before writing a plan wiring step, read the receiving function's opening guards (first 5-10 lines after the signature). Name the guard in the plan step if it interacts with the propagated kwarg/flag.
2. Grep-verify caller identity for any function name the plan cites as "the caller"; do not trust memory.
3. For every shell command in Validation Commands, run it once with a known violation in scope and confirm it fails. A silent-no-op gate is worse than no gate because it produces false confidence.
4. Under sub-agent review, treat "plan claims mechanism X fires at call site Y" as a source-verification target, not accepted prose.

**See also:** `src/tax_reporting/application/persisting/assumptions_sheet.py:111` (the `if th_rows is not None:` gate the r5 amendment widened), `docs/history/plans/2026-07-08-th-tx-view-phase-d.md` (the Phase D plan, Invariant 5 three-exception amendment and Task 1 wiring step), `docs/history/reviews/2026-07-08-plan-review-th-tx-view-phase-d-r3.md` through `r6.md` (the six review rounds).

## 49. Required-Presence Loader Guards for Decision-Point Flags (and the Silent-Guard Anti-Pattern)

**Principle:** Family G (Data-loss observability) - when a decision-point flag has a `False` default in `_KNOWN_BOOL_FLAGS` `setdefault`, the default silently masks the case where the flag was never authored into the decision-points TOML at all. The user cannot distinguish "flag deliberately off" from "flag forgotten, loader fell back to default." Compounded by Family H (Verify the real thing, not the abstraction) - a required-presence guard that references a helper function (`_countries_table_for(...)`) which was never defined is a silent no-op: the abstraction ("we have a guard") hides that the guard crashes with `NameError` at runtime instead of raising `ConfigurationError`. The guard exists on paper but was never executed end-to-end.

**Trigger:** You are adding a new law-driven flag to `TaxJurisdictionConfig` and a corresponding boolean entry to `docs/maintenance/tax/decision_points/<year>.toml`, OR you are introducing (or resurrecting) a "required-presence" validation that a flag must be explicitly authored rather than defaulted. Before moving on, ask: "Does this flag have a `False`/`True` default that would mask absence? Is there a loader guard that raises `ConfigurationError` naming the missing flag? Has that guard been executed end-to-end against a fixture that OMITS the flag, confirming it raises (not just that a fixture WITH the flag passes)?"

**Rule:**
1. Decision-point flags with a `False` default that must be EXPLICITLY authored (not defaulted) require a required-presence guard in `_load_tax_jurisdiction_config` (`infrastructure/config.py`). The guard iterates `_REQUIRED_TREATMENT_FLAGS` (or equivalent) and raises `ConfigurationError` naming the missing flag when the country section exists but omits any required flag. Place the guard AFTER `_KNOWN_BOOL_FLAGS` `setdefault` so the `False` default does not mask absence.
2. The guard skips when the country section is absent entirely (backward compat for jurisdictions that have no per-country section). When adding a NEW country section to the TOML, ALL required flags must be present or the loader raises.
3. Every new guard must be exercised by a test that OMITS the required flag and asserts `ConfigurationError` is raised with the flag name in the message. A test that only verifies a well-formed fixture loads is NOT a guard test; it cannot distinguish the guard from a no-op.
4. **Silent-guard anti-pattern (Family H):** when wiring a guard that calls a helper (`_countries_table_for`, `_enforce_required_treatment_flags`, etc.), the implementation is incomplete until the helper is defined AND the guard has been run. A guard skeleton that references an undefined helper compiles fine (the name is resolved at runtime, not import time) and is a `NameError` waiting to fire on the first real config load. After authoring any guard, run `uv run pytest` (not just `uv run python -c "import ..."`; import does not execute the guard body) and confirm the omit-the-flag test fails with `ConfigurationError`, not `NameError`.
5. When the inline guard body would push `_load_tax_jurisdiction_config` past ruff's `PLR0912` branch limit, extract it into a named helper (`_enforce_required_treatment_flags(flags, country, fiscal_year)`). Keep the guard call site visible in the loader so reviewers can see the guard fires on every load.

**What happened (2026-07-09 Phase D Task 2):** A prior session landed six new `treatment_*_via_resolver` flags on `TaxJurisdictionConfig` with `= True` defaults, a `_REQUIRED_TREATMENT_FLAGS` tuple in `config.py`, and a required-presence guard skeleton. The skeleton called `_countries_table_for(country, fiscal_year, logger)` - a helper that was referenced in the comment block but never defined. At runtime the guard would have raised `NameError: name '_countries_table_for' is not defined` on the first config load, not the intended `ConfigurationError`. Pass 1 of Task 2 defined the helper, extracted the body into `_enforce_required_treatment_flags` (PLR0912), and verified the guard raises correctly via `tests/unit/application/test_phase_d_flags.py`. The prior session's guard was a silent no-op because no test had executed the omit-the-flag path against the real loader.

**Why this happens:** Adding a flag in three places (domain field, TOML entry, loader wiring) is a multi-step edit where the guard is the last piece. It is tempting to write the guard as a skeleton ("I'll define the helper next") and stop. But the skeleton looks complete to a reviewer (it references a plausible helper name, has a docstring, lives in the right function), so it merges. The `True` default on the new flags made the omission invisible at import time: every existing test that loaded a fixture WITH the six flags passed, and no test loaded a fixture WITHOUT them. The guard only becomes load-bearing when a future contributor adds a seventh flag or a new country section and omits it - exactly the scenario the guard was written to catch.

**Distinguishing from lesson #36 (jurisdiction-specific output must be flag-gated):** #36 is the architectural principle (decision-point flags gate jurisdiction-specific output, never country-literal gates). This lesson is the loader-side enforcement: once a flag EXISTS, its presence in the TOML must be enforced, because a `False`/`True` default otherwise lets a forgotten flag pass as a deliberate value. #36 is about WHERE the flag gates; this is about WHETHER the flag was authored.

**Distinguishing from lesson #48 (plan wiring must trace the entry-point guard):** #48 is about PLAN steps that claim a kwarg enables a code path without reading the receiving guard. This lesson is about CODE that ships a guard whose helper is undefined, so the guard is unreachable. Both are Family H; #48's fix is source verification at plan time, this lesson's fix is end-to-end execution of the omit-the-flag test at implementation time.

**Required behavior:**
1. When adding a decision-point flag whose value must be explicit, add it to `_REQUIRED_TREATMENT_FLAGS` (or equivalent) and write the guard. Do not rely on the default to surface a forgotten flag.
2. After authoring any loader guard, run the omit-the-flag test and confirm it raises `ConfigurationError` (not `NameError`, not `AttributeError`, not a silent pass). Import-only verification does not execute the guard body.
3. When a guard references a helper, define the helper in the SAME commit. A guard skeleton with a TODO helper is a silent no-op.
4. When the guard body pushes the loader past PLR0912, extract into a named helper; do not inline `# noqa: PLR0912` to absorb the guard.

**See also:** `docs/maintenance/tax/decision_points/2025.md` DP-019 (Phase D loader/test artifacts referenced here were deleted in Phase E; see `docs/history/plans/completed/2026-07-10-th-tx-view-phase-e.md`).

## 50. TOML Subtable Scoping: Flag Entries Must Precede Nested Subtable Headers

**Principle:** Family D (Single source of truth) - in a TOML file, a `key = value` line belongs to the most recently preceding table/subtable header. Once a nested subtable header like `[countries.PT.exclude_transaction_fee_matchers]` appears, every subsequent `key = value` line is scoped under THAT subtable until a sibling/parent header resets scope. Flag entries intended for `[countries.PT]` that are appended AFTER a nested subtable header silently land in the wrong table and are invisible to the loader's country-level flag scan. Compounded by Family G (Data-loss observability): the TOML parses without error (the subtable legitimately accepts arbitrary keys), so the mis-scoped flag is silently dropped from the country-level flag dict.

**Trigger:** You are adding boolean flag entries (e.g. `treatment_*_via_resolver = true`) to a `[countries.XX]` table in `docs/maintenance/tax/decision_points/<year>.toml` that ALSO contains nested subtables (`[countries.XX.exclude_transaction_fee_matchers]`, `[countries.XX.some_dict_subtable]`). Before appending the new flags, scan the file for `[countries.XX.<child>]` headers. If any exists BELOW where you plan to insert, insert the flags ABOVE the first nested subtable header (or use an explicit `[countries.XX]` reset header).

**Rule:**
1. In a decision-points TOML, place country-level boolean flags IMMEDIATELY after the `[countries.XX]` header and BEFORE any `[countries.XX.<child>]` nested subtable header. Once a nested subtable header appears, subsequent bare `key = value` lines belong to the child, not the parent country table.
2. When adding a flag to a country section that already has nested subtables, insert above the first nested header, not at the end of the country block. If unsure of scope, add an explicit `[countries.XX]` reset header before the new flags (TOML permits re-opening a parent table after a child).
3. Verify placement with `python3 -c "import tomllib; d=tomllib.loads(open('<file>').read()); print(d['countries']['PT'])"` and confirm the new keys appear at the expected nesting level, not under a child subtable.
4. The multi-type loader in `config.py` accepts both boolean tables and `dict[str, Decimal]` subtables; a mis-scoped boolean may be silently absorbed by a dict-typed subtable and never reach the country-level flag scan.

**What happened (2026-07-09 Phase D Task 2):** The six `treatment_*_via_resolver = true` entries for `[countries.PT]` had to be placed BEFORE the `[countries.PT.exclude_transaction_fee_matchers]` subtable header. A naive append at the end of the PT block would have scoped all six flags under `exclude_transaction_fee_matchers`, where the loader's country-level flag scan would not find them and the required-presence guard (lesson #49) would have raised `ConfigurationError` for all six despite them being present in the file text.

**Why this happens:** TOML's "current table" is implicit positional state. When editing a TOML file, the natural edit point for "add to the PT section" is the end of the PT block, which is precisely where a nested subtable header has already shifted scope. The file looks correct (the flags are visually inside the PT block), the parser accepts it, and only a `tomllib` dump of the parsed structure reveals the mis-scope.

**Distinguishing from lesson #49 (required-presence guard):** #49 is about the LOADER detecting a missing flag. This lesson is about the AUTHORING mistake (mis-scoped flag) that causes the flag to be missing from the parsed country table even though it is present in the file text. The two compose: #50 prevents the mistake; #49 catches it when it slips through.

**Required behavior:**
1. When adding country-level flags to a decision-points TOML with nested subtables, insert immediately after the `[countries.XX]` header, before any nested subtable.
2. After editing, dump the parsed TOML and confirm the new keys are at the expected nesting level.
3. Treat the required-presence guard (#49) as the backstop: if it raises for a flag you believe you added, suspect mis-scoping before suspecting the flag name.

**See also:** `docs/maintenance/tax/decision_points/2025.toml` (`[countries.PT]` block with nested `exclude_transaction_fee_matchers`), `docs/maintenance/project-guidelines.md` #2 (decision-points TOML is the runtime sidecar).

## 51. Characterization Tests Pinning Legacy Behavior Need Explicit Legacy-Path Opt-In When the Feature Flag Default Flips

**Principle:** Family D (Single source of truth) - when a feature flag's default value flips (e.g. `treatment_spot_disposal_via_resolver` flips from default-False to default-True), the flag default and every characterization/golden test that pins the LEGACY behavior become two sources of truth that silently drift. The default now routes the characterization corpus through the NEW code path, so the golden values the test pins (e.g. an aggregated `136.01 EUR` mixing derivatives Profit+Loss rows under the legacy OGR override) no longer reproduce and the test fails not because the code regressed but because the test's contract was implicitly tied to the OLD flag value. Compounded by Family H (Verify the real thing, not the abstraction) - the test NAME ("characterizes legacy OGR override") is an abstraction over the actual control flow; the flag default is part of the control flow, and a test that does not explicitly set the flag is asserting against a moving target.

**Trigger:** You are flipping the default value of a boolean feature flag (or a flag-like config knob) from off to on (or on to off) and the repo contains characterization/golden/backward-compat tests whose pinned values were captured under the OLD default. Before flipping the default, grep for every test that exercises the affected code path (`grep -rn "<config-helper-name>" tests/`, `grep -rn "<flag-name>" tests/`) and identify which of those tests CHARACTERIZE legacy behavior (their docstring or golden values were chosen to lock the pre-flag output).

**Rule:**
1. When flipping a feature flag default, characterization tests that pin the LEGACY behavior must explicitly opt into the legacy path by setting the flag to its OLD value in their fixture/helper. Do not rely on the new default to preserve legacy golden values; the new default exists precisely to route new corpora through the new path, and a characterization corpus is by construction a legacy corpus.
2. The flag-on code path (the NEW behavior) must be exercised by DEDICATED tests, not by repurposing the characterization tests. If the characterization tests were the only coverage of the new path, add new tests before flipping the default.
3. When a characterization helper (e.g. `_build_characterization_jurisdiction`, `_ogr_split_jurisdiction`, `_load_with_separation`) constructs the config object, add the legacy flag value to the helper and document in its docstring WHY the flag is pinned (which legacy behavior the corpus characterizes). Future tests reusing the helper inherit the correct opt-in.
4. Verify after the flip that the characterization tests still pass unchanged on their golden values AND that the new dedicated tests pass on the new path. Both must be green; if a characterization test only passes after recomputing its golden value, the flip silently changed the contract and the test is no longer characterizing legacy behavior.
5. When a flag is per-treatment (e.g. six `treatment_*_via_resolver` flags), check whether flipping ONE flag's default affects characterization corpora that exercise OTHER treatments on the same corpus. A derivatives-tagged corpus may characterize the SPOT_DISPOSAL flag's legacy path indirectly because the resolver classifies derivatives-tagged rows to a different treatment whose flag is still off, but the filter applies per-KEY and may still exclude them.

**What happened (2026-07-09 Phase D Task 3 SPOT_DISPOSAL flip):** The `treatment_spot_disposal_via_resolver` flag flipped to default-True. Three characterization fixtures - `TestOgrCharacterizationGolden._build_characterization_jurisdiction`, `TestPipelineIntegration._ogr_split_jurisdiction` (used by `test_derivatives_entries_empty_when_flag_off`), and `TestBackwardCompatTrace._load_with_separation` (used by `test_flag_off_matches_golden_values`) - all pin legacy OGR override golden values (e.g. `136.01 EUR` mixing derivatives Profit+Loss rows). Under the default-True flip, the resolver classified derivatives-tagged rows (`Futures fee`, `Realized gain`) to DERIVATIVES_CLOSE (not SPOT_DISPOSAL), but the per-KEY filter logic interacted with the event-level aggregation in a way that the legacy mixed-Profit+Loss golden value drifted. Fix: set `treatment_spot_disposal_via_resolver=False` in all three helpers (opting the characterization corpora into the legacy path) and added dedicated tests in `test_phase_d_flip_spot_disposal.py` for the flag-on path.

**Why this happens:** The characterization test author captured the golden value when the flag did not exist (or was off). The test name and docstring describe the BEHAVIOR being characterized (legacy OGR override), not the FLAG VALUE that produces it. When the flag default flips, no signal tells the author that a config knob the test never mentioned is now part of the contract. The test fails, the golden value is recomputed, and the test now silently characterizes the NEW behavior under a name that still says "legacy" - the regression-catch property is lost.

**Distinguishing from lesson #44 (test-helper platform attribution):** #44 is about a test helper deriving a value differently from production. This lesson is about a test helper OMITTING a config flag that production now sets by default, with the same divergence symptom (test passes for the wrong reason after a behavior change). The two compose: #44 catches helpers that mis-derive; this catches helpers that under-specify.

**Required behavior:**
1. Before flipping a feature flag default, grep all tests for the flag name AND for config helpers that build the affected config object.
2. For each characterization/golden test on the affected code path, pin the flag to its legacy value in the helper and document why.
3. Add dedicated tests for the new flag-on path; do not repurpose characterization tests.
4. Run the full suite after the flip; any characterization test that needs its golden value recomputed is a signal the flag flip changed its contract, not that the test was wrong.

**See also:** `tests/unit/application/test_crypto_reporting.py` (`_build_characterization_jurisdiction`, `_ogr_split_jurisdiction`), `tests/end_to_end/test_crypto_derivatives_separation.py` (`_load_with_separation`), `docs/maintenance/project-guidelines.md` (decision-point flag defaults). (Phase D dedicated flag-on coverage `tests/unit/application/test_phase_d_flip_spot_disposal.py` was deleted in Phase E along with the `treatment_spot_disposal_via_resolver` flag; resolver-path coverage now lives in `tests/unit/application/test_spot_disposal_resolver_behavior.py`; see `docs/history/plans/completed/2026-07-10-th-tx-view-phase-e.md`.)

## 52. Flipping a Membership-Based Scope to a Resolver Delegate Must Preserve Membership-Only Members the Resolver Maps Elsewhere

**Principle:** Family G (Data-loss observability) - when a scope-defining function is reimplemented from "membership in a constant tag set" (`_LOAN_PRINCIPAL_TAGS = {"loan", "loan repayment"}`) to "delegation to a resolver that returns a treatment enum", the resolver may classify some rows that the OLD membership path included into a DIFFERENT treatment (e.g. `OTHER`), silently dropping them from the scope. Compounded by Family C (Representation: sentinel vs None vs exception) - the resolver's `OTHER` treatment conflates "borrow-side principal creation" (a loan-affected asset whose `Tag="Loan"` row receives the asset) with truly unrelated rows, so the new code cannot distinguish "drop on purpose" from "drop by accident". The data-loss symptom is exit-0 with a missing asset: FIFO rebuild produces zero lots for an asset that should have been rebuilt, and unless a warning+ guard catches zero-output assets, the loss is invisible.

**Trigger:** You are replacing a "scan rows for tag in CONSTANT_TAG_SET" implementation of a scope-defining function (e.g. `discover_loan_affected_assets`) with a delegation to a treatment/intent resolver that returns an enum whose values do not 1:1 correspond to the original tag set. The resolver maps some old-member rows to a treatment that is NOT the one you are flipping onto (e.g. a `Tag="Loan"` borrow-side deposit resolves to `OTHER`, not `LOAN_REPAYMENT`). Before flipping, enumerate the rows the OLD membership path included and check each against the resolver; any row that no longer maps to the flip-target treatment is a candidate for silent drop.

**Rule:**
1. When flipping a membership-based scope to a resolver delegate, enumerate every row the OLD membership path included (constant tag set x observed row shapes) and trace each through the resolver. Any row that resolves to a treatment OTHER than the flip-target needs an explicit preservation clause in the new code, or it silently drops.
2. The preservation clause must branch on the SAME discriminator the resolver uses (treatment enum value) PLUS a second signal that disambiguates "member the resolver maps elsewhere" from "unrelated row" - typically the normalized tag the OLD membership used. Do NOT branch on raw tag strings; reuse the resolver's normalization entry point so the clause tracks the resolver's notion of equivalence.
3. The preservation clause must be documented as a named invariant (e.g. "Invariant 11: borrow-only asset preservation") in the plan and referenced in the code comment, so a future reader does not delete the clause as "redundant" after the flip is complete.
4. Add a dedicated RED test for the preservation clause using a fixture whose row resolves to the non-flip-target treatment (e.g. a borrow-only asset with empty sending side) and assert the asset is STILL in scope. Add a negative test asserting an unrelated row with the same treatment is NOT pulled in by the clause.
5. Parametrize the preservation test over the normalization variants of the disambiguating signal (e.g. `["Loan", "loan", " LOAN ", "Loan  "]`) so a future change to the resolver's normalization cannot silently break the clause.
6. When the OLD membership path and the NEW resolver path coexist behind a flag (`via_resolver`), the legacy path must remain byte-identical (Phase D Invariant 1: bypass, not deletion) so the flag-off rollback reproduces the pre-flip scope exactly.

**What happened (2026-07-10 Phase D Task 5 LOAN_REPAYMENT flip):** `discover_loan_affected_assets` was reimplemented from "scan TH rows, include asset when `_normalize_tag(row.tag) in _LOAN_PRINCIPAL_TAGS`" to "iterate pre-built transactions, include asset when `resolve_treatment(tx, config) == Treatment.LOAN_REPAYMENT`" (behind `treatment_loan_repayment_via_resolver=True`). A borrow-only asset (a wallet that only ever BORROWED an asset, never repaid) has its principal-creation row tagged `"Loan"` with an empty sending side. The resolver classifies that row as `Treatment.OTHER` (it is a deposit, not a repayment disposal), NOT `LOAN_REPAYMENT`. Under pure resolver delegation the asset dropped out of `loan_affected_assets`, so the FIFO rebuild step skipped it, producing zero lots for an asset the legacy membership path had included. The Invariant 11 clause (`resolve_treatment == OTHER AND _normalize_tag(tx.row.tag) == "loan"`) was added to preserve borrow-only assets; without it, the loss would have been silent (zero-output asset, exit 0).

**Why this happens:** The resolver's treatment enum is a coarser classification than the membership tag set. `LOAN_REPAYMENT` in the resolver names the REPAYMENT event (a disposal), while `_LOAN_PRINCIPAL_TAGS` membership named the PRINCIPAL-CREATION event (a deposit). The two sets overlap on actual repayment rows but DIVERGE on borrow-only deposits, which are in the membership set but map to `OTHER` under the resolver. An author flipping the implementation who reads only the resolver's enum values (not the old membership constant) has no signal that the sets are not 1:1. The loss is invisible unless a zero-output-asset warning guard (CLAUDE.md: "Any excluded asset yielding zero FIFO output must log at warning+") catches it AND the author investigates the warning rather than suppressing it.

**Distinguishing from lesson #51 (characterization tests and flag-default flips):** #51 is about TEST golden values drifting when a flag default flips. This lesson is about PRODUCTION scope silently shrinking when the scope-defining function's implementation changes under the flag. The two compose: #51 catches test-side drift; this catches production-side data loss that the tests may not have covered (borrow-only assets are a minority scenario).

**Required behavior:**
1. Before flipping a membership-based scope to a resolver delegate, diff the OLD inclusion set against the NEW inclusion set on the full observed row corpus. Any set difference is a candidate for a preservation clause or a documented behavior shift.
2. The preservation clause must reuse the resolver's tag normalization (single source of truth); never inline a second normalization.
3. Name the clause as an invariant in the plan and reference it in the code comment so it survives future cleanup.
4. Test the clause with a RED fixture that exercises the divergent row shape AND a negative test for unrelated same-treatment rows.
5. Confirm the zero-output-asset warning guard fires loudly if a preservation clause is ever removed; treat such a warning as a data-loss signal, not noise.

**See also:** `src/tax_reporting/application/crypto/treatment_resolver.py` (`resolve_treatment`, `_normalize_tag`), `docs/history/plans/2026-07-08-th-tx-view-phase-d.md` (Invariant 11). (Phase D `via_resolver` branch in `parsing.py` and `tests/unit/application/test_phase_d_flip_loan_repayment.py` were deleted in Phase E; Invariant 11 resolver-path coverage now lives in `tests/unit/application/test_loan_repayment_resolver_behavior.py`; see `docs/history/plans/completed/2026-07-10-th-tx-view-phase-e.md`.)

## 53. When a Plan Body Clause Contradicts a Plan Invariant (Freeze), the Freeze Wins - Scope the Edit and the Test to the Invariant-Safe Subset

**Principle:** Family D (Single source of truth) - a multi-task plan has TWO sections that both make claims about the same file: the per-task body clauses (instructing concrete edits) and the cross-cutting invariants (declaring freeze/scope constraints). When a body clause instructs an edit that an invariant forbids, the two are NOT equal-authority: the invariant is the authoritative source because it encodes a cross-task constraint (a frozen file protects earlier-phase deliverables; a "single source of truth" goal protects a later-phase consolidation). The implementer must detect the contradiction at implement time, prefer the freeze, scope the edit to the invariant-safe subset, and scope the test to assert ONLY that subset. Compounded by Family H (Verify the real thing, not the abstraction) - "single source of truth" is an abstraction; the concrete artifact is two parallel definitions that must be byte-identical until a later phase consolidates them.

**Trigger:** You are implementing a plan task whose body clause names a specific file and edit (e.g. "remove the duplicated definitions from `treatment_resolver.py:70,73,76` and import them from `token_origin.py` instead"), AND the same plan has an Invariants section declaring a freeze on some files (e.g. "Invariant 4: `treatment_resolver.py` is on the Phase D frozen list - CR guard: reject any edit to that file"). Before writing the edit, grep the freeze list against EVERY file the clause touches.

**Rule:**
1. At implement time, read the plan's Invariants section BEFORE executing any body clause that names a file. Build the freeze set (the list of files the invariants protect).
2. For every file a body clause instructs you to edit, check membership in the freeze set. If the file is frozen, the body clause is OVER-CONSTRUED: do not edit the frozen file. Instead, execute the invariant-safe subset of the clause (e.g. extract the NON-frozen side's duplicates to named constants; leave the frozen side's definitions in place).
3. Document the deviation in a code comment at the invariant-safe edit site AND in the implement log, naming the invariant that took precedence and the future phase that can consolidate once the freeze lifts.
4. Scope the test to assert ONLY the invariant-safe subset (e.g. assert the non-frozen side's constants exist and match the frozen side byte-for-byte; do NOT assert the frozen side was removed or re-imported). A test that asserts the over-construal will fail at GREEN time and tempt the implementer to violate the freeze to make it pass.
5. Under review, treat "plan body clause edits file X" + "plan invariant freezes file X" as a contradiction to surface, not a puzzle to resolve silently. The reviewer confirms the implementer picked the invariant-safe subset; the plan author amends the body clause to match.

**What happened (2026-07-10 Phase D Task 7 REWARD_AIRDROP_LP flip):** The plan body NOTE (line 874) said: "Remove the duplicated definitions from `treatment_resolver.py:70,73,76` and import them from `token_origin.py` instead (single source of truth)." The same plan's Invariant 4 said: "`treatment_resolver.py` is on the Phase D frozen list - CR guard: reject any edit to `src/tax_reporting/application/crypto/treatment_resolver.py`." The frozen module-level constants (`_DEFAULT_REWARD_TAGS`, `_DEFAULT_AIRDROP_TAGS`, `_DEFAULT_LP_TAGS` at lines 70/73/76) ARE part of the frozen resolver (consumed by `TreatmentConfig` default factories, which `resolve_treatment` consumes). A literal reading of the body clause would have violated Invariant 4 and tripped the CR guard (or, if the CR guard were not yet wired, silently broken the Phase B freeze). The implementer picked the invariant-safe interpretation: extract the `token_origin.py`-side duplicates to module-level constants with the SAME names and byte-identical values; leave the resolver-side definitions frozen in place; document the parallel-definition state in a comment block; scope the `test_inline_literals_extracted_to_constants` test to assert ONLY the `token_origin.py`-side extraction. The "single source of truth" consolidation is deferred to a post-Phase-D phase when the freeze lifts.

**Why this happens:** A multi-task plan is written across many sessions and review rounds. The body clauses are written to express the IDEAL end state ("single source of truth"); the invariants are written to express the CROSS-TASK safety contract ("do not touch the Phase B frozen file while Phase D flips land"). When the two are written in different sessions (or amended across review rounds without re-cross-referencing every body clause against every invariant), a body clause can promise an edit an invariant forbids. The implementer, following the plan top-to-bottom, reaches the body clause first and is tempted to execute it literally; the invariant is in a different section and is only consulted if the implementer grep-checks the freeze set against the clause's target file.

**Distinguishing from lesson #48 (plan wiring steps must trace entry-point guards):** #48 is about a plan CLAIM that a mechanism will fire (Family H: the guard was not read). This lesson is about a plan CLAUSE that edits a file a plan INVARIANT freezes (Family D: two sections of the same plan disagree on whether a file is in scope). #48's fix is to trace the call chain; this lesson's fix is to grep the freeze set against the clause's target file BEFORE editing.

**Distinguishing from lesson #52 (flip must preserve membership-only members):** #52 is about a FLIP's new code path dropping members the old path included (Family H + G: data-loss under a representation change). This lesson is about a plan's INTERNAL contradiction between a body clause and an invariant (Family D: single source of truth vs freeze). #52's fix is to add a preservation clause to the new path; this lesson's fix is to scope the edit and test to the invariant-safe subset.

**Required behavior:**
1. Before executing any plan body clause that names a file, read the plan's Invariants section and build the freeze set. Grep-check every clause target against the freeze set.
2. When a clause and an invariant conflict, execute the invariant-safe subset, not the literal clause. Document the deviation at the edit site and in the implement log.
3. Scope the test to assert ONLY the invariant-safe subset. Never write a test that asserts the over-construal (frozen file edited); it will fail at GREEN and pressure the implementer to violate the freeze.
4. Under review, surface plan body-vs-invariant contradictions as findings; confirm the implementer picked the invariant-safe subset; ask the plan author to amend the body clause to match for future readers.
5. When authoring or amending a plan, after writing a body clause that names a file, grep the plan's own Invariants section for that filename. If an invariant freezes it, rewrite the clause to express the invariant-safe subset inline (do not leave the contradiction for the implementer to resolve).

**See also:** `src/tax_reporting/application/crypto/treatment_resolver.py` (frozen side; lines 70/73/76 unchanged), `docs/history/plans/2026-07-08-th-tx-view-phase-d.md` (Invariant 4 freeze list; Task 7 NOTE line 874 body clause). (Phase D `_DEFAULT_REWARD_TAGS`/`_DEFAULT_AIRDROP_TAGS`/`_DEFAULT_LP_TAGS` in `token_origin.py`, the parallel-definition comment block, and `tests/unit/application/test_phase_d_flip_reward_airdrop_lp.py` were deleted in Phase E; resolver-path coverage now lives in `tests/unit/application/test_reward_airdrop_lp_resolver_behavior.py`; see `docs/history/plans/completed/2026-07-10-th-tx-view-phase-e.md`.)

## 54. Removing Dataclass Fields Breaks Shared Conftest Helpers - Filter Removed Keys to Keep the Suite Collectable

**Principle:** Family G (Data-loss observability) - when a plan task removes dataclass fields from a domain/config type, every caller that passes those fields as kwargs crashes at the constructor with `TypeError: __init__() got an unexpected keyword argument`. The critical choke point is the shared conftest helper (e.g. `build_koinly_jurisdiction`) that MANY test files use to construct the type; if the helper still forwards the removed kwargs, the ENTIRE test suite becomes uncollectable, producing zero signal (not even the task's own RED tests run). Compounded by Family H (Verify the real thing, not the abstraction) - the helper's signature is an abstraction over the dataclass's current field set; the abstraction silently drifts when fields are removed without a helper update.

**Trigger:** You are implementing a plan task that removes dataclass fields from a type (e.g. dropping `treatment_*_via_resolver` flags from `TaxJurisdictionConfig`), AND a shared conftest helper constructs that type by forwarding `**overrides` (or explicit kwargs) to the constructor. Before declaring the task done, grep for every test helper that constructs the type: `grep -rn "<TypeName>(" tests/conftest.py tests/`.

**Rule:**
1. Before removing dataclass fields, grep for every construction site in tests: `grep -rn "TaxJurisdictionConfig(" tests/` (substitute the type name). Identify shared conftest helpers that forward `**overrides` or explicit kwargs.
2. Update the shared helper to FILTER the removed keys from overrides before forwarding (e.g. `overrides.pop("treatment_payment_via_resolver", None)` for each removed field, or a loop over a removed-keys set). This is a backward-compat shim: callers that still pass the removed keys silently drop them instead of crashing at construction.
3. Document the shim inline in the helper, naming the removal task/phase that owns deleting the call sites that still pass the removed keys.
4. Run the full suite (or at least `pytest --collect-only`) after the helper fix to confirm the suite is collectable. A zero-signal suite is the worst-case failure mode: not even the task's RED tests run.
5. The removal task that owns deleting the field should ALSO own deleting the call sites that pass it; but if those call sites are slated for a LATER task (e.g. a sweep task), the conftest shim keeps the intermediate state collectable.

**What happened (2026-07-11 Phase E Task 6 removal of six `treatment_*_via_resolver` flags):** Task 6 deleted six fields from `TaxJurisdictionConfig`, the required-presence loader guard, and the six flag lines from `2025.toml`. The plan's files list did NOT include `tests/conftest.py`. But `build_koinly_jurisdiction` (the shared helper used by every crypto test that constructs a jurisdiction) forwarded `**overrides` to the constructor. Every test that called `build_koinly_jurisdiction(treatment_spot_disposal_via_resolver=...)` (and there were many, across `test_crypto_reporting.py`, `test_phase_d_*.py`, `test_crypto_derivatives_separation.py`) would have crashed at the constructor with `TypeError`, breaking collection of the ENTIRE suite, including the 6 expected RED-window derivatives tests that Task 2's earlier deviation depended on. The minimal fix was to add the six removed keys to a filter set in the helper, silently dropping them from overrides. Without this fix, `pytest --collect-only` itself would fail.

**Why this happens:** A plan task that removes fields scopes its files list to production code and the task's own tests. The shared conftest helper is infrastructure that every test file implicitly depends on; it is rarely in any single task's files list because it is cross-cutting. When the helper forwards `**overrides`, it is structurally coupled to the dataclass's field set even though no import references the removed fields by name. The plan author cannot anticipate every helper that constructs the type; the implementer must grep for construction sites at implement time.

**Distinguishing from lesson #47 (fixture rename sweep):** #47 is about scattered REFERENCES to a fixture path diverging from a conftest constant after a rename (Family H + G: stale glob patterns silently match zero files). This lesson is about a shared HELPER that constructs a type crashing at the constructor when fields are removed (Family G: the symptom is total collection failure, zero signal). #47's fix is to grep every shape of the rename; this lesson's fix is to update the shared helper to filter removed keys and run `pytest --collect-only` to confirm collectability.

**Distinguishing from the CLAUDE.md rule on `**`-unpacking heterogeneous dicts (line 42):** that rule is about TYPE SAFETY when unpacking a `dict[str, Any]` into a dataclass (per-key narrowing doesn't survive a splat). This lesson is about FIELD REMOVAL breaking the splat at construction time. The splat-typing rule prevents type errors; this lesson prevents collection failure.

**Required behavior:**
1. When a plan task removes dataclass fields, grep for every construction site in tests BEFORE declaring the task done: `grep -rn "<TypeName>(" tests/`.
2. If a shared conftest helper forwards `**overrides` to the constructor, add the removed field names to a filter set in the helper so callers that still pass them silently drop them.
3. Run `pytest --collect-only` after the helper fix to confirm the suite is collectable. Do NOT rely on running just the task's own tests; collection failure is suite-wide.
4. Document the shim inline, naming the later task/phase that owns deleting the call sites that still pass the removed keys.
5. When authoring a plan task that removes fields, add a grep step for construction sites in tests to the task's validation commands, even if the task's files list does not name `tests/conftest.py`.

**See also:** `tests/conftest.py` (`build_koinly_jurisdiction` helper, six removed flag keys filtered from overrides), `src/tax_reporting/domain/jurisdiction.py` (six `treatment_*_via_resolver` fields removed), `docs/history/plans/completed/2026-07-10-th-tx-view-phase-e.md` (Task 6; Task 8 owns the call-site sweep).

## 55. Deletion Backstop Greps Must Cover Canonical Docs, Not Just src/ and tests/

**Principle:** Family G (Data-loss observability) - when a task deletes a mechanism (function, constant, flag, gate, code block) and ships a "verification grep" backstop to confirm no stale references remain, scoping the grep to `src/` and `tests/` only silently leaves stale NARRATION about the deleted mechanism in canonical docs (`docs/maintenance/`, `docs/architecture/`, README). The grep exits 0 (clean) while the docs continue to describe the deleted mechanism as live behavior. Future agents read those docs as authoritative and re-implement the deleted mechanism, or worse, act on stale contracts (a "live invariant" that no longer exists). Compounded by Family H (Verify the real thing, not the abstraction) - "the grep passed" is an abstraction over "no stale reference remains"; the concrete reality is "no stale reference remains in the scopes the grep scanned."

**Trigger:** You are implementing a plan task that deletes a named mechanism (function, constant, code block, flag, gate, data structure, validation step) AND the task's verification commands include a grep backstop like `grep -rn "<deleted_name>" src/ tests/` or `grep -rIn "<mechanism_phrase>" src/ tests/`. Before declaring the task done, ask: "Does any canonical doc narrate this mechanism as live? Does the grep scan those docs?"

**Rule:**
1. A deletion-verification grep's scope MUST include every location where the deleted mechanism could be narrated as live behavior: `src/`, `tests/`, AND canonical docs (`docs/maintenance/`, `docs/architecture/`, `README.md`, plus any repo-specific doc roots the project uses).
2. The grep patterns MUST cover not just the literal identifier (function/constant name) but also prose phrases that narrate the mechanism (e.g. for a "count-equality collision gate", also grep for `"count-equality"`, `"collision gate"`, `"collision-blocks-correction"`, the section TITLE in canonical docs).
3. When the grep hits a canonical doc, the doc section must be REWRITTEN to describe the post-deletion state, not left narrating the deleted mechanism with a "this was removed" footnote. Future readers skim for the current contract; a "historically, X" framing reads as "X is the design" to a casual reader.
4. If the task's verification commands are scoped to `src/ tests/` only, expand them BEFORE declaring the task done. Do NOT rely on a later review round to surface doc drift; the review sub-agents may not all read canonical docs either.
5. When authoring a plan task that deletes a mechanism, the task's grep backstop MUST explicitly list `docs/maintenance/` (or the project's equivalent canonical-docs root) in the search scope. Do not write `grep -rn "<name>" .` as a shorthand; explicit roots catch typos and signal intent.

**What happened (2026-07-12 review-loop Round 1 against `2026-07-10-th-tx-view-phase-e`):** Phase E deleted multiple mechanisms - the count-equality collision gate, the re-zero snapshot/restore block, `_DEFAULT_PAYMENT_TAGS`, `build_payment_tag_index`, `_LOAN_PRINCIPAL_TAGS` from `crypto_fifo/contexts.py`, three `_DEFAULT_*_TAGS` constants from `token_origin.py`, and six `treatment_*_via_resolver` flags. Phase E Task 10's verification grep scanned `src/` and `tests/` only. Round 1 review surfaced 1 High and several Medium findings: `docs/maintenance/crypto_implementation_guidelines.md:1495` still narrated the deleted count-equality collision gate as a LIVE mechanism (the section title was "Deque + count-equality collision-blocks-correction pattern"); `crypto_rules.md` PT-C-035 still listed the count-equality gate and re-zero snapshot in its mechanism inventory; `koinly_guidelines.md` cross-referenced the deleted gate; the resolver module docstring still said "the live crypto pipeline does NOT call the resolver yet" (stale by Phase D); `README.md` still listed `payment_tags` as a JSON key in the popular-crypto-tokens schema (the field had been removed). All of these were invisible to the Task 10 grep because the grep did not scan `docs/maintenance/` or `README.md`. A future agent reading `crypto_implementation_guidelines.md:1495` would have re-implemented the deleted gate on the assumption that the doc described the live contract.

**Why this happens:** Plan task files lists and verification greps are scoped to the production-code blast radius (`src/`) and the test blast radius (`tests/`). Canonical docs are treated as "downstream cleanup" or "documentation task", so they fall outside the deletion task's scope. But canonical docs are LOAD-BEARING for future agent reasoning: a stale contract in `crypto_implementation_guidelines.md` is worse than no contract at all because it actively misleads. The grep backstop is the last chance to catch this; scoping it to code dirs only defeats its purpose.

**Distinguishing from lesson #47 (fixture rename sweep):** #47 is about scattered test-side references to a renamed fixture path diverging from a conftest constant (Family H + G in tests). This lesson is about CANONICAL DOC narration of a DELETED MECHANISM surviving a code-only grep backstop (Family G + H in docs). #47's fix is multi-pattern grep across tests; this lesson's fix is multi-pattern grep across docs.

**Required behavior:**
1. When authoring or implementing a deletion task, expand the verification grep's scope to include `docs/maintenance/`, `docs/architecture/`, `README.md`, and any project-specific canonical-doc roots. Bare `grep -rn "<name>" src/ tests/` is INSUFFICIENT for a deletion that touches behavior canonical docs describe.
2. The grep patterns MUST include both the literal identifier AND prose phrases that narrate the mechanism (section titles, mechanism names, phrase descriptions). A function-name grep alone misses docs that describe behavior in prose without naming the function.
3. When the grep hits a canonical doc, rewrite the section to describe the POST-DELETION state. Do not leave "this was removed in Phase X" footnotes; casual readers will skim past the footnote and treat the surrounding prose as the live contract.
4. Verify the rewrite by re-grepping for the deleted mechanism's identifier and prose phrases in the same canonical doc; both should return zero hits after the rewrite.
5. When a plan task deletes a mechanism, the task's validation commands MUST include a docs-scope grep. If the plan does not have one, add it before declaring the task done.

**See also:** `docs/maintenance/crypto_implementation_guidelines.md` (line 1495 section rewrite), `docs/maintenance/crypto_rules.md` (PT-C-035 mechanism inventory), `docs/maintenance/koinly_guidelines.md` (cross-reference update), `README.md` (popular-crypto-tokens schema), `src/tax_reporting/application/crypto/treatment_resolver.py` (module docstring), `docs/history/plans/completed/2026-07-10-th-tx-view-phase-e.md` (Task 10 grep backstop, scoped to src/ and tests/ only).

## 56. Validate "narrow the broad except" findings by running the suite, not by reasoning about reachability

**Principle:** Family H (Verify the real thing, not the abstraction) - when a review finding proposes narrowing a broad `except (A, B, C)` clause to `except (A, B)`, the test suite is the authoritative oracle for whether exception type C is reachable at that call site. Each test that exercises the C path is a load-bearing caller; a narrowing that breaks the test is a regression, not a "stricter variant tradeoff". Compounded by Family B (Error-policy propagation) - the broad clause is itself a propagated error policy (catch every failure mode of the called helper and degrade to empty state); narrowing it without re-deriving the propagation is a policy change, not a cleanup.

**What happened (2026-07-15 review-loop Round 6 against `2026-07-10-th-tx-view-phase-e`):** Round 5 premortem flagged `tests/conftest.py:build_origin_resolver` for catching `(FileProcessingError, OSError, ValueError)`; the finding proposed narrowing to `(FileProcessingError, OSError)` so a helper bug that raised `ValueError` would surface as a test failure rather than silently degrading to an empty resolver. The staging doc already noted the premortem agent's claim that `ValueError` was unreachable was WRONG (Round 4 had correctly restored `ValueError` because `_detect_header_index` raises it on malformed CSV headers). The narrowing was nevertheless staged as a "stricter variant tradeoff" and accepted. Implementing the narrowing broke `test_malformed_transaction_history_returns_empty_lookup`, which feeds `build_origin_resolver` a headerless CSV and asserts the resolver returns an empty-lookup object (graceful degradation), not a propagated `ValueError`. The test was the authoritative oracle: the `ValueError` path is load-bearing.

**Why this happens:** Review sub-agents reason about exception reachability via static inspection of the called helper. They identify the documented exception types the helper raises, but miss the indirect callers (in this case `read_koinly_rows` -> `_detect_header_index` inside `build_transactions_from_th`). The orchestrator, trusting the agent's analysis and the staging doc's hedge ("a stricter variant tradeoff"), implements the narrowing without requiring the test suite to confirm no caller relies on the removed exception type. When a test breaks, the orchestrator reverts, but the cycle wastes a full test run and erodes confidence in the review findings.

**Distinguishing from lesson #27 (TDD for bug fixes):** #27 is about RED-then-GREEN for new behavior. This lesson is about a refactoring finding that proposes to remove an existing code path; the test suite must confirm no caller relies on the path before the finding can be applied.

**Required behavior:**
1. When a review finding proposes narrowing a broad `except (...)` clause, treat the narrowing as a behavior change, not a cleanup. The orchestrator MUST run the full test suite after the narrowing and BEFORE accepting the finding as applied.
2. Each test that fails after the narrowing is a load-bearing caller of the removed exception type. Do not stage the narrowing as a "tradeoff"; either keep the broad clause or update the broken test to reflect a deliberate behavior change (with the test's author confirming the new contract).
3. The staging doc for a narrowing finding MUST name the tests that pin each exception type's reachability. If the orchestrator cannot name them, the finding is under-evidenced and should be deferred (not applied as a "stricter variant").
4. When the premortem agent's reachability claim is contested in the staging doc's own analysis (as here: "the agent's claim that ValueError is dead was WRONG"), treat the contested narrowing as high-risk: require a green suite run before staging.

**See also:** `tests/conftest.py:build_origin_resolver` (broad except kept; ValueError from `_detect_header_index` is reachable and pinned by `tests/unit/application/test_crypto_origin_resolver.py::TestOriginResolverGracefulDegradation::test_malformed_transaction_history_returns_empty_lookup`), `src/tax_reporting/infrastructure/koinly_parser.py:_detect_header_index` (raises ValueError on malformed header), `docs/history/reviews/2026-07-14-branch-review-2026-07-10-th-tx-view-phase-e-r5.md` (F8 finding), `docs/history/reviews/2026-07-14-branch-review-2026-07-10-th-tx-view-phase-e-r6.md` (F8 rejection).


## 57. Inserting a `class` Between a Renamed Function and an Orphaned Dangling Body Absorbs the Orphan (Module-Collection `NameError`)

**Principle:** Family G (Data-loss observability) - an orphaned indented block (a function/control body left dangling when its `def` or control header was deleted in an earlier commit) is silently re-parented onto the nearest enclosing block whenever you insert a `class` (or any new `def`) between it and its former sibling. The breakage is silent at edit time and surfaces only as a module-collection-time `NameError` referencing a fixture/var the orphan referenced, which looks unrelated to the edit you just made. Compounded by Family D (Single source of truth) - the orphan has no header of its own, so it has no authoritative owner; whichever block geometrically precedes it owns it, and that ownership flips invisibly when the geometric neighbor changes.

**What happened (2026-07-17 Task 2 of `2026-07-15-review-flag-aggregation-boundary`):** `tests/unit/application/test_crypto_reporting.py` had carried a small pre-existing orphan for many commits: a docstring plus an indented body referencing `tmp_path` whose `def` header had been deleted in a long-ago commit (verified at HEAD `f5e606f`, and already orphaned when first introduced per `git show f884d80`). It sat immediately after `test_extract_loan_activity_overpaid_status`. Task 2 renamed that function (`..._overpaid_status` -> `..._overpaid_verify_status`) and inserted a new `TestExtractLoanActivityClassification` class in the gap between the renamed function and the orphan. Python geometrically attached the orphan to the new class body, so importing the module evaluated the orphaned body at class-definition time and raised `NameError: name 'tmp_path' is not defined`, blocking test collection.

**Why this happens:** Python uses indentation alone to assign a block to its enclosing `def`/`class`/control header. An orphan (header deleted, body indentation left intact) has no owner of its own; it is owned by whatever header geometrically encloses it. Inserting a `class ...:` line and a `pass`/method into the gap re-encloses the orphan under the new class. The edit that triggers this is a pure insertion (a rename plus a new class); the author has no signal that the lines after the insertion point are an orphan rather than the next legitimate test. The first symptom is a collection-time `NameError` whose name (`tmp_path`) points at the orphan's internals, not at the edit, so the root cause is non-obvious.

**Distinguishing from lesson #21 (When Removing Functions, Remove Their Tests):** #21 is about *imports of a deleted function in OTHER files* failing at collection. This lesson is about a *body whose header was deleted IN THIS file* being silently re-parented onto a newly inserted class in the SAME file. #21 fires across files via imports; #57 fires within one file via geometric re-enclosure, and the orphan was never a collected test to begin with (it was already dead).

**Required behavior:**
1. When renaming a test function or inserting a new `class`/`def` into a Python test module, run test COLLECTION (`pytest --collect-only` or the first GREEN run) immediately and treat any `NameError` at class/module-definition time (especially one referencing a fixture like `tmp_path` that the new code does not use) as a geometric-orphan signal, not a typo in the new code.
2. Before inserting a `class` body, eyeball the lines immediately following the insertion point for indented blocks that do not belong to a visible `def`/control header above them. An orphan is recognizable as an indented body with no header; remove it before inserting new structure, since it has no owner and no test coverage (grep the orphan's distinctive strings under `tests/` to confirm nothing references it).
3. Do not assume a pre-existing orphan is harmless because it has been present for many commits. It is dormant only as long as its geometric neighbor is stable; any insertion between it and that neighbor activates it.
4. When a collection `NameError` names a fixture the edited code does not reference, suspect a geometric orphan before suspecting a conftest or import problem. Read upward from the `NameError` site for an indented body with no owning header.

**See also:** `tests/unit/application/test_crypto_reporting.py` (orphan removed; `TestExtractLoanActivityClassification` inserted in the gap), Task 2 implement log `docs/tmp/execute-plan/2026-07-15-review-flag-aggregation-boundary/task-2-implement.log.md` (Errors and retries section), commit `f5e606f` (orphan pre-existing at HEAD), commit `f884d80` (orphan already headerless when first introduced).


## 58. When a Sentinel Constant Is Added, Every "Rendered Text" Rendering in Docs/README/Note-Cells Must Be Reconciled Against the Shipped Value (Not the Plan's Label)

**Principle:** Family G (Data-loss observability) - when a task ships a new sentinel/enum/constant value AND canonical docs, README, and in-sheet note-cells narrate what the user will SEE as a "rendered text" label, each rendering site must be reconciled against the constant value actually shipped. A short-form label that an author invents (or borrows from a sibling sentinel's style) silently disagrees with the runtime: the user reads the README expecting `"Overpaid (verify)"` and sees `"Overpaid (cross-year loan? verify)"` in the exported cell. Compounded by Family H (Verify the real thing, not the abstraction) - the plan's stale-string sweep grep is an abstraction over "no rendering disagrees with the shipped value"; it only asserts the OLD deleted literal is gone, not that NEW renderings match the new constant. The grep exits 0 (clean) while four rendering sites describe a value the cell never writes.

**Trigger:** A task (a) adds or renames a sentinel/enum/constant whose value reaches a user-visible surface (Excel cell, API field, report line, CLI output), AND (b) the same task or a sibling task updates canonical docs (`docs/maintenance/`, `docs/architecture/`), `README.md`, or an in-source note/summary string to describe what the user will see. Before declaring the task done, ask: "For every site that narrates a rendered label for this constant, does the narrated text equal the constant value the runtime emits?"

**Rule:**
1. When a task ships a constant whose value is rendered to the user, every docs/README/note-cell site that quotes a "rendered text" or "rendered as" form of that constant MUST quote the constant value VERBATIM (or explicitly distinguish "the cell writes the full sentinel `X`; the note-cell summary uses the short label `Y` for readability"). Do not invent a shorter or friendlier label for the rendered text without an inline note that the runtime emits the longer form.
2. A stale-string sweep grep scoped to the DELETED old literal (e.g. `grep -rn "Overpaid (cross-year loan?)" ...`) does NOT catch a short-form drift on the NEW constant. The sweep must additionally grep for the new constant's value at every rendering site, OR the task must include a mechanical check that each rendering site's quoted text `==` the constant value (read the constant def, then grep the docs for the quoted form).
3. When the plan's Examples section renders a sibling sentinel's value (e.g. `"Likely in-asset interest"`, `"Cannot classify: no EUR price data"`) but leaves the new sentinel as a bare symbol, the docs author has NO authoritative rendered form to copy; the author must read the constant definition and quote that value, not invent a parallel short label. The absence of an Examples rendering for the new sentinel is a signal to verify against the constant, not a license to abbreviate.
4. Sheet note-cells (human-readable summary prose inside the exported workbook) may legitimately use a short label, but only when the SAME doc paragraph or a sibling cell clarifies that the data cell writes the full sentinel. A note-cell short label with no such clarification reads as "the cell contains this" to a reader who only sees the note.
5. When a sentinel's value is matched by exact equality in fill-color or routing logic and asserted verbatim in unit tests, the docs/README are the ONLY place drift can hide; code and tests will not surface it. Treat docs-vs-constant reconciliation as a first-class task-completion check for sentinel-rendering changes, not as "downstream cleanup".

**What happened (2026-07-17 r1 review against `2026-07-15-review-flag-aggregation-boundary`):** Task 2 introduced `LOAN_STATUS_OVERPAID_VERIFY = "Overpaid (cross-year loan? verify)"` in `src/tax_reporting/domain/constants.py:60`. Task 3 docs propagated a short-form "rendered text" label instead: `docs/maintenance/koinly_guidelines.md:31,34` say `rendered text "Overpaid (verify)"`; `docs/maintenance/tax_reporting_guidelines.md:55,56` list the five rendered forms ending with `Overpaid (verify)`; `README.md:179` lists the five sentinels ending with `Overpaid (verify)`; and the sheet's own R1 note cell at `src/tax_reporting/application/persisting/loan_activity_sheet.py:77` also uses the short form. The data cell (column 9) actually writes the full constant `"Overpaid (cross-year loan? verify)"`, pinned by `tests/unit/application/persisting/test_loan_activity_sheet.py:169` (`assert ws.cell(data_row, 9).value == LOAN_STATUS_OVERPAID_VERIFY`). The plan's stale-string sweep (`grep -rn "Overpaid (cross-year loan?)" ...`) exited clean because it scanned for the DELETED old literal, not for the short-form drift on the new constant; the four rendering sites silently disagreed with the runtime.

**Why this happens:** When a task adds several sentinels at once, the docs author often renders the friendlier ones verbatim (because the plan's Examples section quotes them) and abbreviates the awkwardly-long one to a parallel short label. The author has no mechanical signal that the abbreviated form disagrees with the constant value: the constant is defined in a different file, the tests assert the full value (not the docs' rendering), and the stale-string sweep covers only the old literal. The drift surfaces only when a user reads the README, expects the short label, and sees the longer string in the export - or when a fresh adversarial review round reads the constant def and compares it to each rendering site.

**Distinguishing from lesson #55 (deletion backstop greps must cover canonical docs):** #55 is about a DELETED mechanism's narration surviving a code-only grep backstop (the grep scope was too narrow; it missed `docs/maintenance/` and `README.md`). This lesson is the ADDITION-SIDE mirror image: a NEWLY SHIPPED constant's rendered-text label drifting across docs/README/note-cells while the stale-string sweep (which DOES scan docs, per #55) passes because it greps for the wrong string (the deleted old literal, not the new short-form drift). #55 widens the grep SCOPE; this lesson widens the grep PATTERNS (the sweep must cover the new constant's value at every rendering site, not only the deleted literal). Both compound Family G + H, but on opposite sides of a rename.

**Distinguishing from lesson #36 (jurisdiction-specific output must be flag-gated):** #36 is about WHERE a constant fires (unconditional path vs flag-gated dispatch). This lesson is about whether the rendered-text label in docs MATCHES the constant value the runtime emits. #36 prevents baking the wrong dispatch; this lesson prevents the docs describing a value the user will not see.

**Required behavior:**
1. When a task adds or renames a sentinel/constant whose value reaches a user-visible cell/field/line, list every docs/README/note-cell site that quotes a "rendered text" form of it. For each site, open the constant definition and confirm the quoted text equals the constant value VERBATIM.
2. The task's stale-string sweep grep must include a pattern for the NEW constant's value, not only the DELETED old literal. If the new constant is `"Overpaid (cross-year loan? verify)"`, grep for that exact string at every rendering site and confirm each site that claims to show "rendered text" quotes it (or explicitly distinguishes note-cell short label from data-cell full sentinel).
3. When the plan's Examples section renders sibling sentinels but leaves the new sentinel as a bare symbol, treat the absence of an Examples rendering as a verification trigger, not a license to abbreviate: read the constant def and quote its value.
4. Sheet note-cells may use a short label only when the same doc or a sibling cell clarifies the data cell writes the full sentinel. An unqualified short label in a note-cell reads as "the cell contains this".
5. Add this check to the task's validation commands when a sentinel-rendering change ships: `grep -rn "<new constant value>" docs/maintenance/ docs/architecture/ README.md <sheet source file>` and eyeball each hit's surrounding "rendered text" phrasing for verbatim equality with the constant.

**See also:** `src/tax_reporting/domain/constants.py:60` (`LOAN_STATUS_OVERPAID_VERIFY` full value), `src/tax_reporting/application/persisting/loan_activity_sheet.py:77` (note-cell short label), `docs/maintenance/koinly_guidelines.md:31,34` and `docs/maintenance/tax_reporting_guidelines.md:55,56` and `README.md:179` (docs rendering sites with short-form drift), `tests/unit/application/persisting/test_loan_activity_sheet.py:169` (asserts the full sentinel reaches column 9), `docs/history/plans/completed/2026-07-15-review-flag-aggregation-boundary.md` (Validation Commands stale-string sweep scoped to the deleted old literal only), r1 review staging doc `docs/history/reviews/2026-07-17-2026-07-15-review-flag-aggregation-boundary-code-review-r1.md` (Finding 1).

## 59. A Test Fixture That Binds a Named Variable From a Positional CSV Field Must Match the Production Reader's Column Layout (Otherwise the Variable Silently Stays at Its Default)

**Principle:** Family H (Verify the real thing, not the abstraction) - when a test constructs a CSV/positional fixture row and binds a named local from one of its fields (e.g. `for received_amount, repaid_amount, received_value_eur, repaid_value_eur in cases:`), the variable name is an abstraction over "the production reader extracts THIS field from THIS column position". If the fixture's comma count puts the value at the wrong column, the bound local holds the right number but the production-parsed entry field holds the DEFAULT (0 / None / empty), because the reader pulls from a different column. Compounded by Family G (Data-loss observability) - the test stays GREEN when the classifier happens not to branch on the misrouted field, so a green run provides no signal that the fixture column count drifted from the production header. The latent gap surfaces only when a future classifier branch starts reading the field the test THOUGHT it was populating, and silently exercises the wrong path.

**Trigger:** You are authoring a test that feeds a positional (CSV / fixed-width / tuple) row into a production reader, and you bind a named local from a specific field position in that row whose value you also expect to appear on the parsed production object (e.g. `repaid_value_eur` the local vs `entry.repaid_value_eur` the parsed field). Before asserting the test passes, ask: "Does the comma count / column index of the value in my fixture match the column index the production reader extracts that named field from? If I added a debug print of the parsed field, would it equal my bound local?"

**Rule:**
1. When a test fixture binds a named local whose name mirrors a field on the production-parsed object, the column position the value occupies in the fixture MUST equal the column position the production reader extracts that field from. Equality of the bound local to the intended value is necessary but NOT sufficient; the parsed entry field must also equal it.
2. Copying an existing, proven-correct fixture row's comma shape is the safe way to add a sibling fixture. A new fixture authored from memory of "which fields are empty" almost always miscounts the empties between two non-empty positional fields, especially when the production header has many adjacent optional columns.
3. Passing tests are NOT evidence of fixture column correctness when the classifier under test does not branch on the misrouted field. Before relying on the fixture, either (a) add a debug assertion that the parsed entry field equals the bound local, or (b) grep the production reader for the column index it uses for that field and count the fixture's commas explicitly.
4. When the production reader reads a value from column N (e.g. `Net Value (EUR)` at position 15) and the fixture has many optional/empty columns before N, prefer matching the comma count of a known-good fixture verbatim over recomputing the count. An off-by-one in the empty-field count is invisible in the diff and silent at run time.
5. A bound variable that the classifier never reads is a LATENT fixture gap, not a harmless unused parameter: the variable name implies the test exercises that field, and a future classifier branch on that field will inherit the misalignment. Either fix the column alignment so the parsed field matches the local, or drop the parameter from the parametrize/destructuring loop if the field is genuinely unused.

**What happened (2026-07-17 r2 review against `2026-07-15-review-flag-aggregation-boundary`):** Three new `TestExtractLoanActivityClassification` repayment-row templates placed the EUR value at TH CSV column 11 (`Received Cost Basis`) instead of column 15 (`Net Value (EUR)`). The templates used four empty fields after `Sent Cost Basis` (e.g. `f'...Loan repayment,ByBit,{repaid_amount},SUI,1.00,,,,{repaid_value_eur},0,...'`), which lands `{repaid_value_eur}` at position 11 and `0` at position 12 (`Fee Amount`), leaving position 15 empty. The production reader `_extract_loan_activity` reads EUR values only from `Net Value (EUR)` (position 15) for both receipt and repayment branches (`src/tax_reporting/application/crypto/loan_activity.py:68,102`), so `entry.repaid_value_eur` parsed to `0` while the loop variable `repaid_value_eur` held the intended 525.00. The tests still passed because the classifier branches only on `received_value_eur` (`loan_activity.py:134`) and never re-reads `repaid_value_eur`; the variable name in the destructuring loop implied the test populated both EUR fields, but only the first was actually populated on the parsed entry. The unchanged sibling test `test_extract_loan_activity_with_settled_loan` at `test_crypto_reporting.py:6651` already had the correct shape (`,,,,,,,,0,` = eight empties then the value at position 15); the new fixtures were authored without matching that proven comma count. r2 fix realigned the three repayment rows to the settled-loan shape (eight empties between `Sent Cost Basis` and `Net Value (EUR)`); post-fix `entry.repaid_value_eur` correctly reads 525.00 (was 0).

**Witness (2026-07-18 r4 review, same family, second occurrence):** The r2 fix realigned three repayment rows but MISSED three more siblings in the same test class, all introduced in the same `295edd5` commit: the repayment rows in `test_settled_and_open_loan_unchanged`, `test_no_eur_price_classified_as_cannot_classify`, and `test_repayment_only_asset_routes_to_overpaid_verify`. Each had the same four-commas-after-`Sent Cost Basis` shape that landed the EUR value at column 11 (`Received Cost Basis`) instead of column 15 (`Net Value (EUR)`), so `entry.repaid_value_eur` again parsed to `0`. The 11-test class still passed because none of these three classifier branches read `repaid_value_eur` (settled branch keys off `balance == ZERO`; branch (a) keys off `received_value_eur == 0`; branch (b) keys off `received_amount == 0 AND repaid_amount > 0`). The r2 reviewer had empirically verified only the three fixtures it named; the r4 reviewer re-derived every repayment-row fixture's column count against `_TH_HEADER` from scratch and found the three survivors. r4 fix realigned all three to the eight-commas-after-`Sent Cost Basis` shape; post-fix the settled case's `entry.repaid_value_eur` reads 500.00 (was 0). The deeper verification rule (not yet encoded as a mechanical check): a fixture-sweep fix is incomplete until EVERY sibling row of the same shape in the same file has been parsed against the production header and confirmed column-aligned, not just the rows the prior review named.

**Why this happens:** A positional CSV with many adjacent optional columns (Sent Cost Basis, Received Cost Basis, Fee Amount, Fee Currency, Gain EUR, Net Value EUR) invites the author to compress the "empty middle" into a handful of commas written from memory. The author reasons "the EUR value goes near the end" and drops in four or five commas without counting against the production header. The reader silently reads column 15 (empty) into the entry field, and the test's bound local still holds the authored value, so the test's mental model ("I populated `repaid_value_eur`") is satisfied even though the parsed entry field is 0. There is no run-time signal because the classifier under test does not branch on the misrouted field; green hides the gap.

**Distinguishing from lesson #46 (regression test must exercise the production path it claims to guard):** #46 is about the test ASSERTION targeting a value produced by an adjacent code path (the assertion reads the wrong variable). This lesson is about the test FIXTURE feeding a value into the wrong column position (the fixture populates the wrong field), so the production-parsed entry field defaults while the bound local holds the intended value. #46's failure mode is "the assertion is green while the guarded path is broken"; this lesson's failure mode is "the fixture is green while a parsed field is silently default, and a future branch on that field will inherit the gap". #46 fixes the assertion target; this lesson fixes the fixture column count.

**Distinguishing from lesson #47 (fixture rename sweep across all references):** #47 is about scattered REFERENCES to a fixture path diverging from a conftest constant after a rename. This lesson is about the fixture ROW DATA's column-position layout diverging from the production reader's column extraction. #47 is a name/path problem; this lesson is a positional/count problem inside a single fixture row.

**Distinguishing from lesson #38 (tests must not depend on gitignored data):** #38 is about a test reading a data file that exists only on one machine. This lesson is about a test constructing a positional row inline whose column count is wrong relative to the production reader. #38 fails at setup on a fresh clone; this lesson passes everywhere and hides the gap.

**Required behavior:**
1. When authoring a positional CSV/tuple fixture that binds a named local mirroring a production-parsed field, count the fixture's commas/columns against the production header and confirm the value lands at the column index the reader extracts that field from.
2. When a proven-correct sibling fixture exists for the same reader, copy its comma shape verbatim for new sibling rows; do not recompute the empty-field count from memory.
3. For the first fixture in a new reader, add a one-off debug assertion (or a print during authoring) that the parsed entry field equals the bound local, then remove it once the alignment is confirmed.
4. In code review of positional fixtures, treat "a bound variable mirroring a parsed field where the fixture's comma count does not obviously match the production header" as a finding even when all assertions pass; green is not sufficient when the classifier does not branch on the field under question.
5. When a bound local is genuinely unused by the classifier under test, either fix the alignment so the parsed field matches the local (closes the latent gap for future branches) or drop the local from the parametrize/destructuring loop (removes the misleading implication that the field is exercised). Do not leave a bound local whose parsed-field counterpart silently defaults.

**See also:** `src/tax_reporting/application/crypto/loan_activity.py:68,102,134,157` (reader extracts EUR only from `Net Value (EUR)` position 15; classifier branches only on `received_value_eur`; `repaid_value_eur` stored but never re-read), `tests/unit/application/test_crypto_reporting.py:6651` (proven settled-loan repayment row with eight empties then value at position 15), `tests/unit/application/test_crypto_reporting.py:6792,6843,6890` (three misaligned repayment-row templates, fixed in r2), `tests/unit/application/test_crypto_reporting.py:6838,6991,7011` (three more misaligned repayment-row templates missed by r2, fixed in r4), r2 review staging doc `docs/history/reviews/2026-07-17-2026-07-15-review-flag-aggregation-boundary-code-review-r2.md` (Finding 2), r4 review staging doc `docs/history/reviews/2026-07-18-2026-07-15-review-flag-aggregation-boundary-code-review-r4.md` (Finding 1: same-family re-find of the three siblings r2 missed).

## 60. When One Number Drives Both a Branch Decision and a User-Facing Display, Both Must Use the Same Precision (Rounded or Unrounded); Otherwise Inputs Straddling the Rounding Threshold Have Identical Visible Text but Opposite Routing

**Principle:** Family D (Single source of truth / precision) - when a single numeric computation feeds TWO consumers (a routing/branch decision AND a user-facing display string), the SAME value (identical precision, identical rounding mode) must be passed to both. If the decision uses the unrounded raw value while the display renders a rounded/quantized form (or vice versa), inputs that straddle the threshold AFTER rounding but not before (or before but not after) produce two rows with byte-identical visible text that land on opposite sides of the branch. A reviewer reading the rendered text cannot predict the routing; the test suite can be green because each consumer's contract holds in isolation while the AGREE property between them is untested. Compounded by Family G (Data-loss observability) - the disagreement is silent: no exception, no warning, just two cells that look the same and behave differently.

**What happened (2026-07-17 r2 review of `2026-07-15-review-flag-aggregation-boundary`, Findings F1+F3):** `_extract_loan_activity` in `src/tax_reporting/application/crypto/loan_activity.py` computed the loan overshoot percentage as a raw Decimal, then quantized it for display:

```python
raw_pct = abs(repaid_amount - received_amount) / received_amount * 100
pct = raw_pct.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
if raw_pct <= LOAN_OVERSHOOT_INTEREST_PCT:   # decision used UNROUNDED raw_pct
    status = LOAN_STATUS_IN_ASSET_INTEREST
else:
    status = LOAN_STATUS_OVERPAID_VERIFY
detail = f"overshoot {pct}%"                  # display used ROUNDED pct
```

For `received_amount=100, repaid_amount=101.00004`: `raw_pct = 1.00004` (above the 1.0000 threshold) routed to OVERPAID_VERIFY, but `pct = "1.0000"` rendered the SAME display string as an input just under the threshold (`raw_pct = 0.99996` -> `pct = "1.0000"` -> IN_ASSET_INTEREST). A reviewer reading two rows both labeled `"overshoot 1.0000%"` saw one flagged "Likely in-asset interest" and one "Overpaid (cross-year loan? verify)" with no visible cause. The fix made the branch decision use the rounded `pct` (`if pct <= LOAN_OVERSHOOT_INTEREST_PCT`) so display and routing agree by construction; the extracted `_classify_overpaid_balance` helper documents this in its docstring.

**Why this happens:** The author computes a precise intermediate value, needs a rounded form for human-readable output, and reasons "the unrounded value is more accurate, so the decision should use it." That intuition is locally correct (the decision IS more precise) but ignores that the displayed value is the only signal a reviewer has to audit the decision. Once the display rounds, two inputs that the reviewer cannot distinguish can straddle the threshold. The author also typically tests each consumer in isolation: "does the rounding produce the right string?" and "does the threshold route correctly?" - neither test asserts that the rendered string and the routing AGREE for a given input.

**Distinguishing from lesson #58 (sentinel rendered-text must match shipped constant):** #58 is about a constant VALUE (a string sentinel) being abbreviated differently across docs/README/note-cells (Family G: rendered-text label drifts from the shipped value). This lesson is about a computed NUMERIC value feeding a decision and a display at two DIFFERENT precisions in the SAME function (Family D: the two consumers read different precisions of one number). #58's fix is to grep rendering sites for the constant; this lesson's fix is to make the decision consume the same quantized value the display renders.

**Required behavior:**
1. When one numeric computation drives both a branch/routing decision and a user-facing display, decide which precision is authoritative and pass the SAME variable to both. Do not let the decision read `raw_pct` while the display reads `pct` (or vice versa). Prefer the rounded/quantized form for BOTH so the rendered value is the value the classifier used: a reviewer reading "overshoot 1.0000%" sees exactly the number that drove the fill color.
2. Add a regression test that pins the AGREE property, not just each consumer in isolation: pick inputs that straddle the threshold AFTER rounding (one that rounds up across it, one that rounds down across it, one genuinely above) and assert the rendered `detail` string and the branch `status` are consistent. A parametrize over the straddling boundary is the smallest such test.
3. When extracting a helper to shrink an overlong function that contains such a decision/display pair, the extraction is an opportunity (not a risk) to document the precision contract in the helper docstring: name which value is authoritative and why the decision consumes it.
4. In code review, treat any block where the decision reads `raw_<x>` and the display reads `<x>` (or any `raw_*` / quantized `*` pair feeding a threshold and an f-string) as a finding even when each consumer's own tests pass; the AGREE property is the load-bearing invariant and it is rarely tested directly.

**See also:** `src/tax_reporting/application/crypto/loan_activity.py` (`_classify_overpaid_balance` docstring documents that the branch decision compares the rounded `pct` so display and fill agree; the division-by-zero guard puts branch (b) before any division), `tests/unit/application/test_crypto_reporting.py::TestExtractLoanActivityClassification::test_overshoot_precision_display_agrees_with_decision` (3-case parametrize over the 1.0000 threshold boundary: `0.99996` and `1.00004` both round to `1.0000` and both must route to IN_ASSET_INTEREST; `1.00006` rounds to `1.0001` and routes to OVERPAID_VERIFY), r2 review staging doc `docs/history/reviews/2026-07-17-branch-review-2026-07-15-review-flag-aggre.md` (Findings F1+F3).

## 61. When a Behavior-Change Task Gives a Value New Semantics, Pre-Existing Tests That Used the Value as an Orthogonal Fixture Placeholder Must Be Re-Scoped (Not Deleted)

**Principle:** Family D (Single source of truth) - when a behavior-change task assigns a NEW semantic to a previously-neutral value (e.g. `FEE` becomes "Koinly internal fee-accrual tracking token that must be short-circuited at parse time" instead of "some all-zero CG asset"), the new semantic becomes the single authoritative meaning of that value across the codebase. A pre-existing test that used the same value as a CONVENIENT placeholder for an orthogonal purpose (e.g. a fixture row `Asset=FEE` chosen just to stand in for "any all-zero CG row that should be filtered and tracked") now implicitly asserts the OLD behavior that the new semantic intentionally overrules: the test fails not because it regressed but because its fixture value collided with a meaning the test never cared about. Compounded by Family H (Verify the real thing, not the abstraction) - the test NAME and description (`skips_zero_value_rows_and_tracks_assets`) are abstractions over what the test actually verifies (all-zero filtering + WBTC Cyrillic homoglyph `suspicious` flag); the FEE value was incidental, so a reader who deletes the test to "fix" the failure also deletes the orthogonal coverage the test was carrying.

**Trigger:** A behavior-change task's GREEN run surfaces a regression in a PRE-EXISTING test (predating the plan), whose failing assertion mentions the very value the task just re-purposed (e.g. `assert ("capital_gains", "FEE", 1) in skipped_assets`), AND a NEW test added by the same plan asserts the OPPOSITE about that value (e.g. `assert FEE not in skipped_zero_value_tokens`). Before deleting or weakening the pre-existing test, classify whether its PRIMARY purpose is the changed value or something orthogonal to it.

**Rule:**
1. When a behavior-change task flips the meaning of a value `V`, grep every pre-existing test whose fixture or assertion mentions `V` (`grep -rn "V" tests/`). For each hit, classify the test's PRIMARY purpose against the changed behavior: (a) PRIMARY purpose IS the changed value (the test exists to pin exactly the behavior the task flips) -> the test's contract is superseded; either delete it or repurpose it to assert the NEW behavior, and document the supersession in its docstring; (b) PRIMARY purpose is ORTHOGONAL to `V` (the test verifies a different property, and `V` appeared only as a convenient fixture placeholder) -> RE-SCOPE the fixture value to a synthetic non-colliding sentinel (e.g. `XXX`, `ZZZ_PLACEHOLDER`) that preserves the orthogonal coverage without colliding with the new semantic. Do NOT delete the test.
2. The re-scope edit is exactly two lines: the fixture value (`Asset=FEE` -> `Asset=XXX`) and every assertion that pins the re-scoped value (`("capital_gains", "FEE", 1)` -> `("capital_gains", "XXX", 1)`). A re-scope that touches more than the value itself is changing the test's contract, not its placeholder, and must be treated as a supersession (1a) instead.
3. The re-scoped sentinel must be chosen so it cannot collide with a FUTURE behavior-change semantic: prefer obviously-synthetic tokens (`XXX`, `ZZZ_PLACEHOLDER`, `TEST_ASSET_N`) over realistic-looking names that a later task might assign meaning to. Document in the fixture or a comment that the value is a synthetic placeholder, so a future reader does not promote it to a real asset.
4. Run the full module after the re-scope (not just the two tests), because the same value `V` may appear in OTHER tests as a realistic value (not a placeholder) that SHOULD keep its assertion under the new behavior (e.g. `FEE1`/`FEE2` assets that the new short-circuit does NOT match, and which must still land in `skipped_zero_value_tokens`). Distinguish "value matches the new semantic" from "value merely shares a prefix/string with the new semantic" before re-scoping.
5. Document the re-scope in the implement log (which fixture, which assertions, why the test's primary purpose is orthogonal), and surface it to the orchestrator as a "plan-related extension" if the plan's per-task file scope did not list the test file. A pre-existing test re-scope causally required by the task's behavior change is in scope of the task that introduces the new semantic, even if the plan body did not enumerate the test file by name.

**What happened (2026-07-18 Task 2 of `2026-07-18-crypto-dust-partition-fee-skip`):** Task 2 added a `_KOINLY_TRACKING_TOKENS = frozenset({"FEE"})` short-circuit at the top of the `if is_all_zero:` block in `_parse_capital_gains_file`, so `FEE` rows no longer reach `skipped_zero_value_tokens` (they go to a separate `skipped_koinly_tracking` counter and `continue` early). The Task 1 RED test `test_fee_token_absent_from_skipped_zero_value_tokens` pins the NEW behavior. The pre-existing test `test_load_koinly_crypto_report_skips_zero_value_rows_and_tracks_assets` (predating the plan, last touched by commit `3b7f6b6`) asserted `("capital_gains", "FEE", 1) in skipped_zero_value_tokens` - the OLD behavior. Classification: the pre-existing test's PRIMARY purpose was orthogonal (it verifies that all-zero CG rows are filtered out of `capital_entries` and tracked in `skipped_zero_value_tokens`, plus a WBTC Cyrillic homoglyph `WB\u0422C` `suspicious`-flag check); the `FEE` row was a convenient all-zero CG placeholder. The orchestrator's fix re-scoped the fixture row `Asset=FEE` -> `Asset=XXX` (test line `:568`) and the assertion `("capital_gains", "FEE", 1)` -> `("capital_gains", "XXX", 1)` (line `:638`) - two lines, preserving the test's actual coverage. Verified that sibling `FEE1`/`FEE2` fixtures (test lines `:4880`+) are NOT matched by the new short-circuit (the predicate is exact `asset in _KOINLY_TRACKING_TOKENS`, not a prefix match) and their assertions were correctly left unchanged.

**Why this happens:** Test fixture values are chosen for convenience at authoring time, often reusing a short recognizable string (`FEE`, `AAA`, `BTC`) as a stand-in for "any row of shape X". At authoring time the string has no special production semantic, so the choice feels free. A later behavior-change task then assigns a real semantic to that exact string (it becomes a recognized tracking token, a reserved code, a special-case key), and the fixture value silently becomes a load-bearing assertion of the OLD behavior. The implementer of the behavior-change task typically has the plan's new test GREEN and sees only a "regression" in a pre-existing test whose name says nothing about the changed value; the tempting fix (delete the failing assertion, or delete the test) discards orthogonal coverage the test was carrying. The deeper fix (re-scope the placeholder value) preserves both the new semantic and the orthogonal coverage.

**Distinguishing from lesson #51 (characterization tests and flag-default flips):** #51 is about a feature-flag DEFAULT flipping and characterization/golden tests pinning the LEGACY output value drifting because they did not explicitly opt into the legacy flag value; the fix is to pin the flag to its OLD value in the test helper (the test still characterizes the legacy path). This lesson is about a NON-FLAG behavior change (a value gaining new semantics) where the pre-existing test was never characterizing either the old or the new behavior - it was testing something orthogonal and the value was incidental; the fix is to swap the fixture value to a non-colliding sentinel (the test still characterizes its orthogonal property). #51 preserves the old path opt-in; this lesson preserves the orthogonal coverage by changing the placeholder.

**Distinguishing from lesson #53 (plan body clause vs plan invariant freeze):** #53 is about a plan body clause instructing an edit that a plan invariant (a frozen-file list) forbids; the invariant wins and the edit is scoped to the invariant-safe subset. This lesson is about a plan body clause that is SILENT on a pre-existing test (the plan never mentioned the test file at all), yet the task's behavior change causally breaks the test; the resolution is a re-scope, not an invariant-safe subset, and the gap is in the plan's enumeration of affected tests rather than in a freeze contradiction.

**Required behavior:**
1. When a behavior-change task's full-suite run fails on a pre-existing test whose assertion mentions the value the task re-purposed, classify the test's PRIMARY purpose (the changed value, or orthogonal) before editing. Do not delete the test or weaken the assertion on the basis of "it's a regression from my task".
2. For an ORTHOGONAL primary purpose, re-scope the fixture value and its assertions to a synthetic non-colliding sentinel. Keep the edit to exactly the value sites (fixture row + assertions on that value); do not touch the test's other assertions or structure.
3. Choose a sentinel that cannot collide with a future behavior-change semantic (synthetic-looking, not a realistic asset/code/key), and note in the fixture or a comment that it is a placeholder.
4. Run the full module after the re-scope; verify other tests that use realistic values sharing a prefix/string with `V` (e.g. `FEE1`, `FEE2`) still pass because they are not matched by the new semantic and their assertions are unchanged.
5. Surface the re-scope to the orchestrator as a "plan-related extension" and document it in the implement log (which fixture, which assertions, why the test's primary purpose is orthogonal to the changed value).

**See also:** `src/tax_reporting/application/crypto_reporting.py` (`_KOINLY_TRACKING_TOKENS` module constant and the FEE short-circuit at the top of the `if is_all_zero:` block in `_parse_capital_gains_file`), `tests/unit/application/test_crypto_reporting.py::test_load_koinly_crypto_report_skips_zero_value_rows_and_tracks_assets` (re-scoped fixture row `:568` `Asset=XXX` and assertion `:638` `("capital_gains", "XXX", 1)`), implement log `docs/tmp/execute-plan/2026-07-18-crypto-dust-partition-fee-skip/task-2-implement.log.md` ("PLAN GAP DISCOVERED" and "Orchestrator resolution" sections), plan `docs/history/plans/2026-07-18-crypto-dust-partition-fee-skip.md` (Task 2 GREEN; Review Scope "plan-related extension" clause).


## 62. A Pre-Existing RED Draft in the Target File Is an Abstraction Over the Verbatim Plan Spec; Re-Derive the Test Shape From the Spec Before Treating the Draft as Authoritative

**Principle:** Family H (Verify the real thing, not the abstraction) - when a prior session has already staged a RED test draft in the file the current task targets (same test class name, same test method names, same asserted properties), the draft is an abstraction over the verbatim plan spec for that task. The draft's chosen RED MECHANISM (which production entry point the test calls, how the missing GREEN behavior is signaled) silently substitutes for the spec's required mechanism if the implementer trusts the draft as already-correct. The verbatim Task spec may be stricter (call the function directly, not via the full pipeline; signal via `pytest.fail` from a `try/except TypeError` on a new kwarg, not via a missing-field assertion on the assembled report), and the draft may have been authored from a paraphrase of the spec rather than from the spec text itself. Compounded by Family D (Single source of truth) - once two mechanisms exist in the file (the draft's and the spec's), the implementer who picks one without diffing against the spec makes the file drift from the plan; the next task inherits a RED state whose mechanism no one validated.

**Trigger:** The implementer opens the target test file and finds a test class (or set of test methods) whose names match the Task spec's required test names, but the implementation predates the current session (visible via `git blame` on the class, or via the implement log's "What I did" section describing a prior session's draft). Before reusing the draft verbatim, diff the draft's RED mechanism against the verbatim Task spec sentence that names: (a) the production entry point the test must call, (b) the shape of the missing GREEN behavior (new kwarg, new field, new return tuple element), and (c) the failure-mode the RED test must exhibit (`pytest.fail` naming the resolving task, never an unhandled exception, per AGENTS.md rule 4.113). If any of the three differ, rewrite the draft to the spec.

**Rule:**
1. When the target file already contains a test class matching the Task spec's names, run `git blame` on the class header and the first test method; if the commit predates the current session, treat the class as a DRAFT and re-derive its mechanism from the verbatim Task spec before running or extending it. Do not run the draft as-is to "see what fails" first; a wrong-mechanism RED that happens to fail green-for-the-wrong-reason looks like a valid RED and is then committed.
2. Re-derive the three load-bearing spec clauses by reading the Task spec text directly (not the implement log's paraphrase of it): (a) which production entry point does the spec name ("exercise `_parse_income_file` directly", not "exercise the full pipeline"), (b) what does the spec say the GREEN task will add ("add the `skipped_zero_value_deferred_rewards=[...]` kwarg to `_parse_income_file`", not "add a field to `CryptoTaxReport`"), and (c) what failure mode does the spec require ("wrap the call in `try/except TypeError` and convert to `pytest.fail` naming Task 2", not "assert the missing field raises"). If the draft's mechanism differs on any clause, rewrite the draft to match all three.
3. When rewriting, delete the draft's helper(s) that encode the wrong mechanism (e.g. a `_load_crypto_tax_report_safe` wrapper built to gate RED on a missing `CryptoTaxReport` field) rather than leaving them as dead code; the dead helper will mislead the next reader about which mechanism the suite exercises.
4. After the rewrite, confirm the RED state is the spec-mandated one: each of the four tests fails with the exact `pytest.fail(<message naming the resolving task>)` string, NOT with an unhandled `TypeError` whose traceback names the missing kwarg. The two are easy to conflate (both mention `unexpected keyword argument`) but only the `pytest.fail` form is a committed RED that survives a casual `pytest --tb=line` glance as "expected RED awaiting Task N".
5. Document the re-derivation in the implement log's "Deviations from plan" section: name the prior draft's mechanism, name the verbatim spec's mechanism, and cite the spec sentence that drove the rewrite. The next reviewer must be able to re-derive the same choice from the spec without trusting the implementer's paraphrase.

**What happened (2026-07-19 Task 1 of `2026-07-19-deferred-reward-dust-skip`):** A prior session had already added a `TestParseIncomeFileDeferredSkip` class plus a `_load_crypto_tax_report_safe` helper to `tests/unit/application/test_crypto_reporting.py`. That draft exercised the FULL pipeline (`load_koinly_crypto_report`) and gated RED on the missing `skipped_zero_value_deferred_rewards` FIELD on `CryptoTaxReport` (an `AttributeError`-style failure once Task 2 added the field but not the parse-time routing). The verbatim Task 1 spec, however, was stricter on all three clauses: (a) the tests must call `_parse_income_file` DIRECTLY (the function-level path), not the full pipeline; (b) GREEN is signaled by adding the `skipped_zero_value_deferred_rewards` OUT-PARAM (kwarg) to `_parse_income_file`, not by adding a field to `CryptoTaxReport`; (c) the RED failure must be a `pytest.fail` produced by wrapping the call in `try/except TypeError` (catching the missing-kwarg `TypeError` and converting it), never an unhandled exception. The implementer rewrote the class to match all three clauses, deleted the `_load_crypto_tax_report_safe` helper, added the spec-mandated `_write_income_csv` and `_parse_income_file_with_skip` module-level helpers, and verified all four tests fail with the named-task `pytest.fail` string (not a raw `TypeError`).

**Why this happens:** When a multi-task plan is split across sessions, an earlier session sometimes pre-stages a later task's RED tests as a "head start" using its own paraphrase of the spec. The paraphrase is usually directionally correct (the tests do verify the right behavior in spirit) but loosens the load-bearing mechanism clauses because the earlier session was reasoning about the END state, not about the strict RED contract the spec mandates for the current task. The current-task implementer, seeing a draft whose names match the spec, has a strong prior that the draft is "already done" and is tempted to run it as-is; a wrong-mechanism RED that fails (for any reason) looks identical to a correct RED at the `pytest -v` glance. The drift surfaces only when Task 2 implements the GREEN per the spec (kwarg on `_parse_income_file`) and the draft's RED mechanism (field on `CryptoTaxReport`) does not actually exercise the kwarg path, so the suite can be GREEN while the production routing the spec mandated is untested - the same Family H failure mode as lesson #46 (regression test exercising an adjacent path).

**Distinguishing from lesson #46 (regression test must exercise the production call site it claims to guard):** #46 is about a GREEN test that passes against a derived value while the production path it claims to guard regresses silently. This lesson is about a RED test that was authored against the WRONG production path (full pipeline instead of the function the spec names); the failure mode is the same in spirit (test does not exercise the spec-mandated path) but the lifecycle stage differs - #46 bites at GREEN time, this lesson bites at RED time and must be caught before the RED is committed, otherwise Task 2 inherits a RED state whose mechanism no one validated and the GREEN implementation may satisfy the letter of the draft's mechanism while violating the spec's.

**Distinguishing from AGENTS.md rule 4.112 (re-read each RED test against current design invariants when the plan is revised between RED and GREEN):** rule 4.112 fires when the PLAN changes between RED and GREEN and the RED test must be updated to match the new design. This lesson fires when the plan is UNCHANGED but a PRIOR SESSION drafted the RED from a paraphrase that diverged from the spec; the corrective action is the same (re-derive from the source of truth) but the trigger is "a pre-existing draft exists in the target file" rather than "the plan was revised". The two compose: when both fire (plan revised AND a stale draft exists), re-derive from the CURRENT spec text, not from the draft and not from the prior plan version.

**Required behavior:**
1. Before extending or running a pre-existing test class whose names match the current Task spec's required tests, run `git blame` on the class header. If the class predates the current session, treat it as a draft and re-derive its RED mechanism from the verbatim Task spec text.
2. Diff the draft's mechanism against the spec on all three load-bearing clauses: production entry point, GREEN signal shape, and RED failure mode. Rewrite the draft to match any clause that differs; do not preserve the draft's helper(s) that encode the wrong mechanism.
3. Confirm the rewritten RED fails via the spec-mandated `pytest.fail(<message naming the resolving task>)` string on every test, not via an unhandled exception. The two are easy to conflate at a glance but only the `pytest.fail` form is a committed RED that survives review.
4. Document the re-derivation in the implement log's "Deviations from plan" section: prior draft mechanism, verbatim spec mechanism, and the spec sentence that drove the rewrite. The next reviewer must re-derive the same choice from the spec.

**See also:** `tests/unit/application/test_crypto_reporting.py::TestParseIncomeFileDeferredSkip` (rewritten to call `_parse_income_file` directly via the `_parse_income_file_with_skip` helper, which wraps the call in `try/except TypeError` and converts to `pytest.fail` naming Task 2; the prior `_load_crypto_tax_report_safe` helper was deleted), AGENTS.md rule 4.113 (committed RED tests must fail via `pytest.fail` naming the resolving task, never an unhandled exception), AGENTS.md rule 4.112 (re-read RED tests against design invariants when the plan is revised between RED and GREEN), lesson #46 (regression test must exercise the production call site it claims to guard - same Family H shape at GREEN time), Task 1 implement log `docs/tmp/execute-plan/2026-07-19-deferred-reward-dust-skip/task-1-implement.log.md` ("What I did" and "Deviations from plan" sections), plan `docs/history/plans/completed/2026-07-19-deferred-reward-dust-skip.md` (Task 1 verbatim spec clauses).


## 63. Review-Phase Mechanical Compliance Gates Must Run on Committed HEAD Before Declaring a Round CLEAR; Localized-Feature Skip Rationale Does Not Substitute for the Compliance Script

**Principle:** Family H (Verify the real thing, not the abstraction) - a review round that declares CLEAR based on sub-agent verdicts alone is an abstraction over the actual committed state. The sub-agents reason about the diff they were prompted with; they do not, by default, run the repo's mechanical compliance scripts (`check-no-em-dash.sh`, `ruff`, instruction-size gate). When the conditional agents (`concurrency`, `premortem`) are skipped on a "localized feature" rationale, the round loses the adversarial breadth those agents add, and any compliance violation that the remaining agents did not flag (because no agent owns "run every mechanical gate on committed HEAD") ships to the next round or to merge. Compounded by Family A (Mechanical invariants over prompt advice) - the em-dash policy is already enforced by a script (`check-no-em-dash.sh`) and invoked by an in-repo rule (AGENTS.md rule 4.157); the script is the mechanical invariant, and a review round that does not invoke it has not verified the property the rule names.

**Trigger:** You are running a review loop (standalone `review-loop`, or `execute-plan` Phase 3) and are about to declare a round CLEAR based on the sub-agent panel returning zero Medium+ findings. Before declaring CLEAR, ask: "Have I run every repo-defined mechanical compliance script (`check-no-em-dash.sh touched`, `ruff check`, instruction-size gate) against the committed HEAD of this round, independent of what the sub-agents reported? Am I skipping a conditional agent (`concurrency`, `premortem`) on a 'localized feature' rationale - and if so, has the loss of adversarial breadth been compensated by an explicit mechanical gate, or am I just accepting narrower coverage?"

**Rule:**
1. Before declaring a review round CLEAR, run the repo's mechanical compliance scripts on the committed HEAD diff: `check-no-em-dash.sh touched` (or `file` on the changed text files), `ruff check` on changed source, and the instruction-size gate when instruction files are touched. The round is not CLEAR until every mechanical gate exits 0. A sub-agent panel returning zero findings is necessary but not sufficient.
2. When a conditional agent (`concurrency`, `premortem`) is skipped on a "localized feature" rationale, record the rationale in the staging doc Domains/metadata AND run the mechanical compliance gates as compensating coverage. Skipping an agent narrows the review; the mechanical gates are the floor that prevents a narrow-but-violating diff from shipping as CLEAR.
3. When a branch introduces content in files a prior round already cleared (e.g. new commits after a CLEAR commit), re-run the mechanical gates on the FULL `master...HEAD` (or `BASE...HEAD`) diff, not just the new commits. A CLEAR verdict at commit X does not extend to commits X+1..X+N without re-verification; AGENTS.md rule 4.157 explicitly requires diffing against the target branch, not relying on working-tree filters.
4. A `documentation` agent (or equivalent prose-reading lens) is the natural owner of "every mechanical prose/compliance gate ran clean" because it reads the full rendered text where em-dash and label-drift violations live; `quality` and `testing` agents focus on logic and are not wired to run compliance scripts. When the documentation agent is skipped (e.g. internal refactor with no prose), the orchestrator inherits the compliance-gate responsibility directly.

**What happened (2026-07-21 `review-loop` r4 on `2026-07-19-deferred-reward-dust-skip`):** The branch had cleared execute-plan Phase 3 at commit `8f8eaab` (r1 found 5 findings and fixed them; r2 and r3 were CLEAR). Five new commits then landed (`c1573fc` through `a0186ad`) restructuring the suppressed-rewards and dust-summary xlsx blocks into a column-table shape. Standalone review-loop r4 launched the full 7-agent panel on `master...HEAD`; `concurrency` and `premortem` were skipped per the r1/r2/r3 "localized feature" precedent. The `documentation` agent flagged em-dashes as a Low finding; orchestrator verification escalated it to Medium after discovering (a) `master` has zero em-dashes in the affected files, (b) the branch adds 128 U+2014 lines across 11 files including 7 in production source, (c) AGENTS.md rule 4.157 invokes the em-dash branch-compliance check and `check-no-em-dash.sh` is the canonical enforcer. The violation had accumulated across the five post-r3 commits AND across the earlier deferred-reward commits; no prior round ran `check-no-em-dash.sh` as a round gate, so the violation shipped through r1/r2/r3 CLEAR verdicts and only surfaced when r4's documentation agent read the full rendered prose.

**Why this happens:** Sub-agent panels reason about the diff and report findings by severity, but "run the repo's mechanical compliance scripts" is not in any single agent's prompt by default - it is an orchestrator responsibility that is easy to omit when the panel returns zero findings. The "localized feature" skip rationale for conditional agents compounds the gap: the rationale is usually correct for the SKIPPED agent's lens (no concurrency signals, no rollout blast radius) but is mentally over-generalized to "this round is low-risk overall," which then suppresses the mechanical-gate discipline. The em-dash policy in particular is easy to violate in prose because em-dashes are grammatically natural and no linter that runs in the default edit loop flags them; only the explicit `check-no-em-dash.sh` invocation catches them, and AGENTS.md rule 4.157 exists precisely because working-tree filters and "touched file" heuristics miss committed-but-not-staged violations.

**Distinguishing from lesson #48 point 3 (plan Validation Commands must actually validate):** #48.3 is about the PLAN-WRITING phase - a plan's Validation Commands section invokes a script bare and the script exits 0 without scanning (silent no-op gate claimed as a release gate). This lesson is about the REVIEW phase - the review round did not invoke the compliance script AT ALL, so there was no gate (silent or otherwise) between the committed code and the CLEAR verdict. Both are Family H; #48.3's fix is to run the script once with a known violation to confirm it fails, this lesson's fix is to run the script on committed HEAD before declaring CLEAR, every round, independent of sub-agent verdicts.

**Distinguishing from AGENTS.md rule 4.157 (diff explicitly against the target branch for em-dash compliance):** rule 4.157 names the WHAT (diff against the target branch, not working-tree filters) and the WHY (committed violations escape touched-file filters). This lesson names the WHEN (every review round before CLEAR, not just at plan Quality Gate) and the COMPENSATING COVERAGE (mechanical gates substitute for skipped conditional agents). Rule 4.157 is the normative rule; this lesson is the review-loop enforcement procedure that operationalizes it.

**Required behavior:**
1. Before declaring any review round CLEAR, run the repo's mechanical compliance scripts on the committed HEAD diff (`check-no-em-dash.sh touched`, `ruff check` on changed source, instruction-size gate when instruction files are touched). Record the gate results in the staging doc. The round is not CLEAR until every gate exits 0.
2. When a conditional agent is skipped, run the mechanical gates as compensating coverage and note in the staging doc that the gates substitute for the skipped agent's breadth. Do not let a "localized feature" skip rationale propagate into "no mechanical gates needed."
3. When new commits land after a prior CLEAR commit, re-run all gates on the FULL `BASE...HEAD` diff. A CLEAR verdict is point-in-time and does not extend to later commits.
4. Treat the `documentation` agent as the prose/compliance-gate owner when it is launched; when it is skipped, the orchestrator runs the compliance scripts directly.

**See also:** `docs/history/reviews/2026-07-21-branch-review-2026-07-19-deferred-reward-dust-skip-r4.md` (r4 staging doc, F2 em-dash finding with the 128-line / 11-file evidence and the upgrade from Low to Medium), AGENTS.md rule 4.157 (diff against target branch for em-dash compliance), `~/.ai-playbook/scripts/check-no-em-dash.sh` (canonical enforcement script; policy source `agent_workflow_guidelines.md §39`), lesson #48 point 3 (plan-time silent-no-op gate; same Family H shape at plan-writing time), `review-loop` SKILL.md (mechanical gate step before reporting round verdict), `doing-code-review` SKILL.md Step 4 (orchestrator mechanical-gate responsibilities).


## 64. Execute-Plan Phase 5 Cleanup Must Run on EVERY Exit Path (Interrupt, Max-Rounds, Handoff, Crash); Otherwise the Session Dir Survives and docs-branch Syncs It Permanently

**Principle:** Family E (Temporal / ordering invariants) - a cleanup step that only fires on the success path is an incomplete lifecycle guard. When the workflow exits via any non-success path (user interrupt, max-rounds stop, cross-session handoff, agent crash, operator abort), the session tmp dir (`{tmp_dir}/execute-plan/<plan-slug>/`) survives. The next `docs-branch` sync then copies it to the orphan `docs` branch, which is **add-only by design** and never auto-prunes. The session logs (which have reference value for the next round's `learn`) are fine to sync; the problem is that throwaway siblings (`.py` shadow scripts, `.csv` baseline counts, `__pycache__/`) land there too and accumulate forever. Compounded by Family A (Mechanical invariants over prompt advice) - the Phase 5 spec already says "remove session tmp on success", but "on success" is the wrong gate; the cleanup must run on every terminal exit, with success-vs-failure only controlling whether logs are preserved for resume/debugging.

**Trigger:** You are running `execute-plan` and the workflow is about to exit via a non-success path (user says stop after Phase 2, max-rounds hit at 10, session handoff to another agent, agent crash recovery, or any state where Phase 4 archive did not complete). Before exiting, ask: "Did Phase 5 run? If not, is the session dir going to be synced by the next `docs-branch` run with throwaway scripts still in it? Should I either run Phase 5 cleanup now or move the throwaway scripts to root `tmp/` per lesson #34 before the sync?"

**Rule:**
1. The Phase 5 success-only cleanup gate is correct for **logs with resume/debugging value** (preserve on failure/interrupt), but it is the wrong gate for **throwaway scripts and scratch data**. Throwaway `.py`/`.csv`/`__pycache__` files under `{tmp_dir}/execute-plan/<plan-slug>/` must be removed (or moved to repo-root `tmp/` per lesson #34) on EVERY terminal exit, not just success - otherwise `docs-branch` syncs them permanently and they accumulate across plans.
2. Before any `docs-branch` sync following a non-success execute-plan exit, audit `{tmp_dir}/execute-plan/<plan-slug>/` for throwaway scripts and either delete them or relocate to root `tmp/`. Keep the `.md` logs (they have `learn` value); drop the `.py`/`.csv`/`__pycache__`.
3. When a plan completes successfully, Phase 5 already removes the whole session dir - that path is fine. The gap is the non-success exits; operators (and the `done` skill before it syncs) must compensate.
4. Periodic pruning of the orphan `docs` branch's `docs/tmp/` is the backstop when (1)-(3) miss (the 2026-07-21 prune caught ~150 accumulated files). Treat a large `docs/tmp/` backlog on the docs branch as a signal that Phase 5 cleanup has been skipped across multiple sessions.

**What happened (2026-07-21 docs-branch prune):** The orphan `docs` branch had accumulated ~150 files under `docs/tmp/` across ~12 completed plans (fee-filtering, th-tx-view phases A-E, review-flag-aggregation, deferred-reward-dust-skip, suppressed-rewards-block-restructure, etc.). Of those, ~130 were `.md` session logs (legitimate but stale - the plans were all in `docs/history/plans/completed/`) and ~20 were throwaway `.py` shadow scripts, `.csv` baseline counts, and `__pycache__/` bytecode. Every one of those plans had completed (Phase 4 archived), so Phase 5 *should* have removed the session dir on success - but the cleanup did not run, and `docs-branch` (add-only) synced the survivors permanently. Root cause is twofold: (a) Phase 5 cleanup did not fire on the actual exit paths those sessions took (likely cross-session handoffs or operator aborts after Phase 3), and (b) the add-only `docs-branch` has no pruning step, so once synced the files persist forever. The 2026-07-21 manual prune (150 -> 0 files, backup briefly held at `refs/heads/docs-backup-pre-tmp-prune`) cleared the backlog; lesson #34's documents-vs-scripts split prevents future throwaway scripts from re-polluting; this lesson targets the Phase 5 exit-path gap.

**Why this happens:** `execute-plan` Phase 5's success checklist (all tasks `[x]`, Phase 2 + Phase 3 + Phase 4 done) is the correct gate for declaring victory, but it is silently also the ONLY path that triggers cleanup. Every other exit (user interrupt, max-rounds stop, handoff, crash) leaves the session dir in place - which is intentional for resume/debugging of the `.md` logs, but unintentional for the throwaway scripts that ride along. The operator who aborts a run assumes "the tmp dir is ephemeral, it'll get cleaned up"; it will not, because `docs-branch` syncs it next and then never removes it. The mismatch between "tmp is ephemeral" mental model and "docs-branch is permanent add-only" reality is the trap.

**Distinguishing from lesson #34 (documents vs scripts split):** #34 names WHERE each kind belongs (`.md` in `docs/tmp/`, `.py` in root `tmp/`). This lesson names WHEN the cleanup must run (every terminal exit, not just success) and WHY the backlog grows when it doesn't (docs-branch add-only sync). Both compose: #34 prevents future throwaway scripts from landing in `docs/tmp/` in the first place; this lesson ensures the `.md` logs themselves do not accumulate forever when sessions exit without Phase 5.

**Distinguishing from lesson #63 (review-phase mechanical gates):** #63 is about review rounds declaring CLEAR without running mechanical gates. This lesson is about execute-plan sessions exiting without running Phase 5 cleanup. Both are Family E (cleanup/gate skipped on the non-happy-path); the lifecycle stage differs (review loop vs plan execution).

**Required behavior:**
1. On any non-success terminal exit from `execute-plan`, before the next `docs-branch` sync, audit `{tmp_dir}/execute-plan/<plan-slug>/` for throwaway scripts (`.py`/`.csv`/`__pycache__`) and delete or relocate them per lesson #34. Preserve the `.md` logs if resume/debugging is plausible.
2. When `done` runs and a non-success execute-plan session dir exists under `{tmp_dir}/execute-plan/`, treat it as a pruning trigger: the `.md` logs may stay (sync is fine), but throwaway scripts must not sync to the docs branch.
3. Treat a large `docs/tmp/` backlog on the orphan docs branch as a signal that Phase 5 cleanup has been skipped across multiple sessions; prune periodically (the docs branch is add-only, so it will not self-clean).
4. The execute-plan skill should document that Phase 5 cleanup is success-only for LOGS but throwaway scripts must be cleaned on every exit; see the skill-scope dual placement below.

**See also:** `docs/history/reviews/2026-07-21-branch-review-2026-07-19-deferred-reward-dust-skip-r4.md` (unrelated r4 review, but the prune that surfaced this backlog happened in the same session), lesson #34 (documents vs scripts split - WHERE), lesson #63 (review-phase mechanical gates - Family E cleanup-skip cousin), `agents/skills/execute-plan/SKILL.md` Phase 5 (success-only cleanup spec at lines 608-636; the exit-path gap this lesson targets), `agents/skills/docs-branch/SKILL.md` (add-only sync invariant; never auto-prunes), `agents/skills/learn/SKILL.md:185` ("unless project-guidelines documents another gitignored scratch root" - the hook for the root `tmp/` relocation).


## 65. A Completed Plan's Task-Level Status Note ("SKIPPED", "deferred", "done") Is Not the Source of Truth for Whether the Decision/Artifact Actually Shipped; Verify Against the Canonical Artifact Before Treating the Note as Ground Truth

**Principle:** Family H (Verify the real thing, not the abstraction) - a completed plan's task checklist is a NARRATION of what the implementer intended or decided at task time, not a live read of the canonical artifact's current state. A task marked `SKIPPED` with a rationale ("criteria not met") can be reconsidered later and the artifact shipped anyway (by a follow-up commit, a later task, or the same plan's revision) WITHOUT the checklist line being updated. A task marked "deferred" in a feature-notes doc can be resolved by a separate plan without the original doc being annotated. Treating the plan note as ground truth - especially when asked "is X done?" - returns a stale answer that contradicts the actual repository. Compounded by Family G (Data-loss observability): the stale note is invisible to grep (the artifact exists; the note just doesn't mention it), so no backstop script catches the divergence. The only reliable verification is to open the canonical artifact the decision claimed to skip/defer/produce and confirm its current state.

**Trigger:** You are asked "is X done?" / "didn't we already do Y?" / "create a plan for Z" where Z is described in a feature-notes or deferred-findings doc. Before answering (or before drafting the plan), ask: "Am I about to trust a plan checklist line or a feature-notes 'Status' header as ground truth? What is the CANONICAL ARTIFACT this decision would have produced or skipped (an ADR/PD file, a constant, a doc section, a committed test)? Have I opened THAT artifact and read its current state, or am I reasoning from a summary/note that may predate a later change?"

**Rule:**
1. When verifying whether a decision shipped, open the canonical artifact the decision claimed to produce or skip, do not quote the plan task's status note. For a "write an ADR / PD-NNN" decision, read `docs/maintenance/project-decisions.md` (grep `^## PD-`); for a "skip this code path" decision, read the code path; for a "deferred to a follow-up" decision, grep for the resolved artifact across `docs/` and `src/`. The plan note is a hint about WHERE to look, not the answer.
2. A task note that says "SKIPPED: criteria not met" is a point-in-time rationale, not a permanent verdict. The criteria may have been satisfied later (e.g. by real-export evidence strengthening an ADR criterion); re-evaluate the criteria against current state, not against the note's original assessment.
3. Feature-notes and deferred-findings tracking docs are explicitly STALE-PRONE by design (each item carries a "Trigger to re-open" precisely because the doc is not kept live). When asked to act on an item in such a doc, re-run the trigger condition against the current codebase/export before assuming the item's "Status" header is current. A status header dated weeks or months ago is a draft, not ground truth.
4. When the verification reveals the note and the artifact disagree, the artifact wins. Update the tracking doc to match the artifact in the same pass; do not leave the stale note to mislead the next reader (this is the #55/#58 doc-drift backstop applied to status notes specifically).

**What happened (2026-07-21 review-flag-deferred-findings doc cleanup):** Asked to "create an implementation plan from `docs/history/feature-notes/completed/2026-07-15-review-flag-deferred-findings.md`", the agent first classified all 8 items by their Status headers and concluded item #6 (an ADR for the aggregation-boundary rule) was "still deferred." The user pushed back: "didn't we already done 6?" Verification: `docs/history/plans/completed/2026-07-15-review-flag-aggregation-boundary.md` Task 5 literally reads `[x] ... SKIPPED: rule fails criterion #1 ...`. That checklist line said the ADR was NOT written. But `docs/maintenance/project-decisions.md:33` contains `## PD-008: Per-lot review reasons re-evaluated at the aggregation boundary`, added by commit `43dc59b` (same day, after the plan's Task 5 note was written) once the 2025-export evidence strengthened the third ADR criterion. The plan note ("SKIPPED") and the canonical artifact (`## PD-008` exists) directly contradicted each other; the note was stale. The agent's first-pass answer ("#6 is deferred") was wrong because it trusted the plan checklist over the PD file. Fix: re-read the PD file, confirm PD-008 exists, and annotate the feature-notes #6 section with the accurate "Resolved 2026-07-21 by writing PD-008" status.

**Why this happens:** Plan task checklists are written DURING execution and are rarely revisited after the plan archives to `completed/`. A task that says "SKIPPED" captures the implementer's reasoning at that moment; if a later commit (sometimes the same day, sometimes months later in a separate plan) ships the skipped artifact, nobody updates the archived plan's checklist - the checklist is treated as a historical record, not a live status field. Feature-notes tracking docs have the same drift problem by design (each item has a "Trigger to re-open" because the author knows the doc will go stale). When a future agent is asked "is X done?", the fastest path is to grep the plan/feature-notes for the status note, which returns the stale narration; the slower, correct path is to open the canonical artifact. The speed gap is why the wrong answer is the default.

**Distinguishing from lesson #62 (pre-existing RED draft is an abstraction over the verbatim spec):** #62 is about a TEST draft diverging from the plan SPEC at write time (re-derive the test shape from the verbatim spec, not the draft). This lesson is about a STATUS NOTE diverging from a CANONICAL ARTIFACT at verification time (re-read the artifact, not the plan checklist). Both are Family H "verify the real thing"; #62's "real thing" is the spec text, this lesson's "real thing" is the shipped artifact.

**Distinguishing from lesson #55 (deletion backstop greps must cover docs) and #58 (addition-side short-form drift):** #55 and #58 are about CODE/CONSTANT changes whose narration drifts across docs after a rename or addition. This lesson is about a DECISION/STATUS whose plan-level narration drifts from the artifact the decision produced (or didn't). #55/#58 are caught by widening grep scope or patterns; this lesson is caught only by opening the canonical artifact and reading it, because the divergence is between a plan note and an artifact, not between two renderings of the same constant.

**Distinguishing from AGENTS.md "Verification-first task ordering" and "CRITICAL: Code inspection is INSUFFICIENT":** those rules govern verifying CODE behavior against source data. This lesson governs verifying a DECISION's status against the canonical artifact. The shape is the same (do not trust a summary/note; open the real thing) but the target differs: those rules target data-flow correctness, this one targets decision-status correctness.

**Required behavior:**
1. When asked "is X done?" or "did we already do Y?", identify the canonical artifact the decision would have produced or skipped (PD/ADR file, constant, doc section, committed test) and read ITS current state. Do not quote the plan task's `[x] SKIPPED`/`[x] done` line or the feature-notes Status header as the answer.
2. For items in a deferred-findings or feature-notes tracking doc, re-run the item's documented "Trigger to re-open" against the current codebase/export before treating the item as open or closed. Status headers in these docs are drafts, not ground truth.
3. When the artifact and the note disagree, the artifact wins. Update the stale note (plan checklist or feature-notes Status header) to match the artifact in the same pass, citing the commit that resolved the divergence.
4. A plan task marked "SKIPPED: criteria not met" invites re-evaluating the criteria against current evidence, not treating the skip as permanent. ADR/PD criteria in particular are often satisfied later by real-world use; re-check the criteria, then re-check whether the PD was written anyway.

**See also:** `docs/maintenance/project-decisions.md:33` (PD-008 - the canonical artifact the stale plan note claimed was skipped), `docs/history/plans/completed/2026-07-15-review-flag-aggregation-boundary.md` Task 5 (the stale `[x] SKIPPED` checklist line), `docs/history/feature-notes/completed/2026-07-15-review-flag-deferred-findings.md` item #6 (the stale "Deferred decision" header, corrected in this session), commit `43dc59b` (the same-day commit that shipped PD-008 after the Task 5 note was written), lesson #62 (test draft vs spec - same Family H shape, spec target), lessons #55/#58 (constant/code narration drift across docs - caught by grep widening; this lesson's drift is between plan note and artifact, caught only by reading the artifact), AGENTS.md "Verification-first task ordering" (same verify-the-real-thing principle applied to code behavior).

## 66. A Multi-Handler Logging Setup Where the Root Logger Inherits the Console Level Silently Gates the File Handler; Verify Per-Handler Filtering With an Empirical Reproduction Before Promising "Audit Trail Preserved"

**Principle:** Family H (Verify the real thing, not the abstraction) - in Python's `logging` module, a record must pass the LOGGER's effective level BEFORE any handler's `setLevel` is consulted. Setting `root_logger.setLevel(level)` (where `level` is the console threshold) and then `file_handler.setLevel(logging.DEBUG)` does NOT give the file handler all levels: when `level=WARNING`, DEBUG records are dropped at the root before reaching the file handler, and the file handler's `setLevel(DEBUG)` is inert. The per-handler threshold is the LAST gate, not the only gate. A plan or doc that promises "per-row detail preserved at DEBUG in the file" while the root logger is set to the console level is making an empirically false claim. Compounded by Family G (Data-loss observability): the silent drop is invisible to existing tests because `caplog.at_level(DEBUG)` in pytest BYPASSES `configure_application_logging` entirely (caplog attaches its own handler at the root), so the test suite is GREEN while production runtime drops DEBUG to the file. The bug is undetectable by code inspection alone when the root-setLevel call uses a parameter named `level` (reads as "the configured level", not "the root threshold") and is several lines above the file-handler `setLevel(DEBUG)` with a comment like `# File gets all levels` that is wrong as written.

**Trigger:** You are designing or reviewing a logging setup with two handlers at different thresholds (console at WARNING, file at DEBUG), OR you are writing/reviewing a plan that promises "DEBUG detail is preserved in the audit file while the console is quiet." Before accepting the claim, ask: "Where is the ROOT logger level set? Does it inherit the console threshold, or is it set to DEBUG independently? Is there an empirical reproduction (a `uv run python -c` snippet that emits a DEBUG line and greps the file) proving the file actually receives DEBUG at the configured console level, or is the claim derived from reading the per-handler `setLevel(DEBUG)` line in isolation?"

**Rule:**
1. When a logging configuration has per-handler thresholds, the ROOT logger MUST be set to the LOWEST handler threshold (typically `logging.DEBUG`); per-handler `setLevel` is the actual filter. Setting the root to the console threshold silently gates the file handler.
2. A plan, doc, or invariant that promises "DEBUG/X preserved in the file" while the console is at a higher level MUST be backed by an empirical reproduction: a standalone `uv run python -c "..."` that calls `configure_application_logging(level=<console_default>, log_file=tmp)`, emits a DEBUG line, flushes handlers, and asserts the DEBUG line appears in the file. Code inspection of the per-handler `setLevel` is INSUFFICIENT (echoes the AGENTS.md "CRITICAL: Code inspection is INSUFFICIENT" rule).
3. A regression test that guards the root-logger gating fix MUST be at the production-call-site layer (call `configure_application_logging` with the console default, emit DEBUG, assert file contents) - NOT at the `caplog.at_level(DEBUG)` layer, because caplog bypasses the configuration under test and would stay GREEN if the root-logger bug were reintroduced.
4. When a plan-review sub-agent claims empirical verification of a runtime behavior, treat it as higher-confidence than code-inspection claims; when a multi-round review gate's late round (r5+) surfaces a Blocker that earlier rounds missed via code inspection, that is the gate working as designed, not a process failure.

**What happened (2026-07-22 plan review rounds 1-6, `2026-07-21-configurable-log-level-and-warning-grouping`):** The plan's central Part B promise was "per-row warning detail downgraded from WARNING to DEBUG remains preserved in `logs/tax-reporting.log` because the file handler is hardcoded to `logging.DEBUG`" (`logging_config.py:49`). Rounds 1-4 of `review-plan` verified line numbers, signatures, and test impacts via code inspection; all passed. Round 5 ran a standalone `uv run python -c` reproduction against the ACTUAL `configure_application_logging(level='WARNING', log_file=tmp)` and emitted a DEBUG line: the file captured ZERO DEBUG records, proving the promise false. Root cause: `logging_config.py:26` sets `root_logger.setLevel(getattr(logging, level.upper()))` where `level` is the console threshold - so at the new default `LOG_LEVEL=WARNING`, the root gates DEBUG before the file handler sees it. The comment on `:49` (`# File gets all levels`) was wrong as written - it only holds when the root is also DEBUG. The existing test suite stayed GREEN throughout because pytest's `caplog.at_level(DEBUG)` attaches its own handler at the root and bypasses `configure_application_logging` entirely, so no production-call-site test exercised the bug. The fix (folded into the plan): set `root_logger.setLevel(logging.DEBUG)` unconditionally; per-handler `setLevel` does the filtering; add a regression test `test_file_handler_receives_debug_when_console_at_warning` that calls the production function and asserts file contents.

**Why this happens:** Python's two-level filtering (logger level THEN handler level) is counter-intuitive when the configuration function takes a single `level` parameter and applies it to both the root logger and the console handler. The natural reading "this function configures logging at `level`" obscures that the root-logger assignment has a side effect on every other handler. The comment `# File gets all levels` on the file-handler `setLevel` reinforces the misreading by asserting the very thing the root assignment breaks. The bug is latent (invisible) at the legacy default `LOG_LEVEL=INFO` because most production emissions are INFO/WARNING and reach the file anyway; changing the default to WARNING (this plan) makes DEBUG emissions - which Part B relies on - silently disappear. caplog-based tests cannot catch it because caplog is a pytest fixture that bypasses application logging configuration by design.

**Distinguishing from lesson #65 (plan note vs canonical artifact):** #65 is about a STATUS note diverging from a SHIPPED artifact at verification time. This lesson is about a CODE/CONFIG claim diverging from RUNTIME BEHAVIOR - the artifact (the `setLevel(DEBUG)` line) exists and is correct in isolation; the divergence is between the line's apparent semantics and the actual record flow. Both are Family H; #65's "real thing" is the artifact on disk, this lesson's "real thing" is the empirical runtime behavior.

**Distinguishing from AGENTS.md "CRITICAL: Code inspection is INSUFFICIENT for 'is X handled correctly?'":** that rule governs verifying data-flow correctness against source reports. This lesson is the logging-config-specific instance of the same principle: a per-handler `setLevel(DEBUG)` line "looks correct" under inspection but is empirically inert when the root gates first. The general principle is already in AGENTS.md; this lesson adds the logging-specific trigger and the empirical-reproduction requirement.

**Required behavior:**
1. When designing or reviewing a multi-handler logging configuration, verify the ROOT logger is set to the LOWEST handler threshold (usually DEBUG), not to the console threshold. The root level is the FIRST gate; per-handler `setLevel` is the LAST gate.
2. Any plan, doc, or invariant claiming "level X preserved in the file while the console is at higher level Y" MUST include an empirical reproduction command that calls the production logging-configuration function with the console default and asserts the lower-level line appears in the file. Code inspection of the file-handler `setLevel` is insufficient.
3. A regression test guarding this configuration MUST call the production logging function (not caplog's `at_level` bypass) and assert on file contents or handler mock calls.
4. When a multi-round plan review surfaces a late-round Blocker (r5+) that earlier code-inspection rounds missed, treat the late catch as the gate working as designed. Do NOT shorten the review loop to "fewer rounds" on the assumption that early-round code inspection is sufficient; runtime-behavior claims require empirical verification that code inspection cannot provide.

**See also:** `src/tax_reporting/infrastructure/logging_config.py:28` (the root-setLevel site, now fixed to `logging.DEBUG` so DEBUG records reach the file handler) and `:57` (the `file_handler.setLevel(logging.DEBUG)` + the now-accurate `# File gets all levels` comment; at the pre-fix state these were at `:26` and `:49`), `docs/history/plans/2026-07-21-configurable-log-level-and-warning-grouping.md` Task 1 (the fold that fixes the bug and adds the regression test), `docs/history/reviews/2026-07-21-plan-review-configurable-log-level-and-warning-grouping-r5.md` (the round that empirically caught the bug via `uv run python -c` reproduction), AGENTS.md "CRITICAL: Code inspection is INSUFFICIENT" (the parent principle), lesson #65 (same Family H, artifact-vs-status-note shape), Python `logging` module docs (logger effective level vs handler level).

## 67. A Function-Body Reorder That MOVES a Block but Leaves the Original Copy Behind Creates a Silent Duplicate; the Verify Step Must Assert Structural Singularity (One Definition / One Trailing Block), Not Just "Tests Pass"

**Principle:** Family E (Temporal / ordering invariants) - when a task reorders the body of a large function (moving a block to an earlier position in control flow), the operation "move" must be implemented as DELETE-then-INSERT, not INSERT-then-leave. A copy that is inserted at the new site but never deleted at the old site becomes dead code that duplicates the live block, and because the dead copy is textually valid Python (correct indentation, resolvable names from the enclosing scope) the module parses and the suite stays GREEN. Compounded by Family H (Verify the real thing, not the abstraction) - "the reorder compiles and the tests pass" is an abstraction over "the function body is structurally singular"; the concrete reality is "two copies of the crypto-report block and two copies of the epilogue exist at the end of `_main`, the second unreachable but valid." The suite has no signal because no test exercises `_main` end-to-end with a Koinly directory present (the very path the moved block implements), so the duplication is invisible to GREEN.

**Shape trigger (when to suspect this family):** A plan task instructs a structural REORDER of a function body (move block B from after C to before C, or "config-load first, then logging, then the IB/FIFO block"), and the function is long enough (or the block large enough) that the move is a multi-line cut. Before marking the task GREEN, ask: "Does my verify step assert the block exists ONCE (structural singularity), or does it only assert the tests pass? Is there a grep that counts `def _main` / `def main` definitions, or counts the moved block's signature line, and confirms the count is 1?"

**General form:** A "move" edit is a DELETE plus an INSERT. Implementing it as INSERT-only leaves the source copy in place, producing a duplicate. For move edits inside a single large function (where the source and destination share an enclosing scope), the duplicate is valid, compiles, and is unreachable - so the only reliable detector is a STRUCTURAL assertion (grep count of the moved block's signature, AST-node count, or `grep -c "def <name>"` for whole-function moves), not the test suite. A test suite that never exercises the moved block's code path will stay GREEN while the duplication ships.

**Example (2026-07-21 `2026-07-21-configurable-log-level-and-warning-grouping` Task 1 follow-up, commit aef1a1a7 + this fix):** Task 1 implemented Design Invariant 9 by rewriting `_main()` in `src/tax_reporting/main.py` so config-load runs first, logging is configured once, then the IB/FIFO block runs. The rewrite was done by writing the new ordered body and leaving the original trailing crypto-report block (the `try: crypto_tax_report = ... generate_tax_report(...) ...` block plus the `logger.info("Application completed successfully")` / `print("Processing completed successfully!")` epilogue) in place at the end of `_main`. The result: `_main` had its live pipeline, then immediately below it a SECOND full copy of the crypto-report block and a SECOND epilogue, both syntactically valid (names resolve in the enclosing scope) but unreachable (the first epilogue's `print` / `return`-via-fallthrough precedes them at runtime only because the first block is the one actually on the happy path). `uv run pytest tests/` reported 1809 passed because no test drives `_main` end-to-end with a real Koinly directory under the IB source's parent. The duplication was caught by a `done` follow-up review of the implement log, not by any test. The fix (this commit) is a pure 63-line deletion of the duplicate block + duplicate epilogue, confirmed by `grep -n "def _main\|def main"` showing exactly one `_main` (line 110) and one `main` (line 287), plus AST parse OK and 1809 tests still passing.

**Why this happens:** A function-body reorder of a long function is hard to perform as a clean DELETE+INSERT in a single edit because the new ordering and the old ordering overlap textually (both contain the same blocks). The implementer tends to write the new ordered body and then treat "the old trailing block" as already-superseded rather than explicitly deleting it; nothing in the diff view flags a duplicate the way it flags an orphaned import (a duplicate block has no broken reference). Python does not error on a second, unreachable, valid copy of a block inside the same function - unlike a second `def _main` at module scope (which would be a silent name shadow, also caught by the same `grep -c` check). The absence of an end-to-end `_main`+Koinly test removes the only runtime path that would distinguish "one crypto-report call" from "two crypto-report calls".

**Distinguishing from lesson #57 (geometric orphan re-parenting):** #57 is about an orphaned indented BODY whose HEADER was deleted, being silently re-enclosed under a newly inserted `class`/`def` and raising `NameError` at collection time. This lesson is about a WHOLE BLOCK (header intact, body intact) being DUPLICATED by a move edit, not re-parented; the duplicate is valid and raises nothing, so it ships silently rather than failing at collection. Both are Family E/G; #57 fires via geometric re-enclosure and surfaces as `NameError`, this lesson fires via copy-not-move and surfaces only under structural singularity grep or end-to-end coverage.

**Distinguishing from lesson #21 (when removing functions, remove their tests):** #21 is about imports of a DELETED function failing across files. This lesson is about a block that was meant to be MOVED (relocated within the same function) but was only COPIED; nothing is deleted across files and no import breaks.

**Distinguishing from lesson #28 (fix in-scope refactoring findings in the same branch):** #28 is about addressing review findings before merge. This lesson is the specific MECHANICAL-BACKSTOP rule for a MOVE edit: the verify step must grep for structural singularity, because the suite cannot detect an unreachable duplicate.

**Required behavior:**
1. Treat any plan task that says "move"/"reorder" a block inside a function as a DELETE+INSERT, not an INSERT-only. After the edit, explicitly confirm the source copy is gone (the diff must show deletion lines for the old site and addition lines for the new site, not just additions).
2. Add a STRUCTURAL-SINGULARITY assertion to the task's verify step for any function-body reorder of a large function: at minimum `grep -c "^def <name>" src/<path>` (or `grep -n "def <name>"`) must return exactly one definition per moved function, AND for a moved BLOCK, grep for the moved block's signature/distinctive first line must return exactly one match inside that function. "Tests pass" is INSUFFICIENT.
3. When a code path (e.g. `_main` end-to-end with a Koinly directory) has no test coverage, do not rely on the suite to catch duplication on that path; treat the path as unverified and add a structural grep as the backstop. Adding an end-to-end `_main` smoke test (even a minimal one with a fixture Koinly directory) would have made the duplicate block raise or double-execute and surface immediately.
4. After any `_main` rewrite, run `grep -n "def _main\|def main\b" src/tax_reporting/main.py` and confirm exactly one of each before declaring GREEN; this is a cheap, mechanical, zero-false-positive check for the whole-function and adjacent-block duplication class.

**See also:** `src/tax_reporting/main.py:110,287` (single `_main` and `main` after this fix), `docs/history/plans/2026-07-21-configurable-log-level-and-warning-grouping.md` Task 1 (the rewrite that introduced the duplicate), commit `aef1a1a7` (Task 1, introduced the duplication), this commit (pure 63-line deletion of the duplicate crypto-report block + duplicate epilogue), `docs/tmp/execute-plan/2026-07-21-configurable-log-level-and-warning-grouping/task-1-implement.log.md` (Task 1 implement log whose `_main` reorder Decision section did not flag the leftover copy), lesson #57 (Family E/G, geometric-orphan sibling; contrasts re-parented-body vs duplicated-block), lesson #21 (cross-file import of deleted function; contrasts), lesson #28 (fix refactoring findings in-branch), AGENTS.md "CRITICAL: Code inspection is INSUFFICIENT" (parent principle: tests-passing does not equal structurally-correct).

## 68. A `caplog.records` Filter on the Logger Name Must Match the Emitting Module's Fully-Qualified `__name__`, Not the Parent Package Aperture You Passed to `caplog.at_level`

**Principle:** Family H (Verify the real thing, not the abstraction) - in pytest's `caplog`, the `LogRecord.name` attribute is the emitting logger's name, which for `logging.getLogger(__name__)`-style module loggers is the module's fully-qualified name (e.g. `tax_reporting.application.crypto_fifo.parsing`), NOT the parent-package aperture argument you passed to the surrounding `caplog.at_level(DEBUG, logger="tax_reporting.application.crypto_fifo")` context. The aperture argument controls which records caplog PROPAGATES and CAPTURES (it accepts child-module records because propagation is on by default); it does not set the `LogRecord.name`. Filtering the captured records with `rec.name == "<parent package>"` selects ZERO records even though the records are present in `caplog.records`, because each record carries the emitting module's `__name__`, not the aperture. The result is a green-looking assertion failure ("expected 1, got 0") that points at a non-existent production bug when the real defect is in the test's filter predicate.

**Trigger:** You write a pytest assertion of the form `[rec for rec in caplog.records if rec.levelno == logging.X and rec.name == "<something>"]`, or you filter `caplog.records` by `rec.name` to scope a level/massage assertion to one module. Before trusting the filter, ask: "Did I pass a PARENT PACKAGE to `caplog.at_level(..., logger=...)`, and then filter `rec.name ==` on that same parent-package string? Does the emitting module use `logger = logging.getLogger(__name__)`, which makes each `LogRecord.name` the module's fully-qualified `__name__` rather than the aperture?" If both are true, the filter selects nothing.

**Rule:**
1. `LogRecord.name` is the name of the logger that EMITTED the record. For `logging.getLogger(__name__)` module loggers, that is the module's fully-qualified name (e.g. `tax_reporting.application.crypto_fifo.parsing`), not any parent package. Do not filter `rec.name` on the aperture argument you passed to `caplog.at_level`.
2. `caplog.at_level(level, logger="<parent>")` controls CAPTURE (which propagated records the fixture keeps); it accepts descendant-module records. It does NOT rename them. So the capture succeeds while a `rec.name == "<parent>"` filter fails, producing a misleading "got 0" result.
3. When scoping a caplog assertion to one module, either (a) filter on the module's fully-qualified `__name__` (the precise string the module's `getLogger(__name__)` uses), or (b) filter on a substring/`endswith` of the message rather than on `rec.name`, or (c) rely on the level filter alone when only one logger is in play.
4. When a caplog assertion fails with "expected N, got 0" but the production code visibly emits the record, first suspect the `rec.name` filter predicate (the most common false-zero cause), not the production logger call. Print `[rec.name for rec in caplog.records]` to see the real names before changing production code.

**What happened (2026-07-22 `2026-07-21-configurable-log-level-and-warning-grouping` Task 4 / Pattern C, RED-to-GREEN):** The new `TestCryptoFifoParsing#test_duplicate_tx_key_emits_single_summary` first filtered `caplog.records` with `rec.name == "tax_reporting.application.crypto_fifo"` (the parent package, matching the `caplog.at_level(DEBUG, logger="tax_reporting.application.crypto_fifo")` aperture). On the first GREEN run the aggregate-WARNING assertion failed with `assert len(aggregate_warnings) == 1, got 0` even though the aggregate WARNING was being emitted. Root cause: `_dedup_by_tx_key` lives in `crypto_fifo/parsing.py`, whose `logger = logging.getLogger(__name__)` emits records under `tax_reporting.application.crypto_fifo.parsing`; the parent-package filter matched none of them. Fix: corrected the filter to `rec.name == "tax_reporting.application.crypto_fifo.parsing"`. No production code change was needed; the production logger call was correct all along.

**Why this happens:** The `caplog.at_level(level, logger=NAME)` signature reads as "set NAME's level", which invites the assumption that the captured records' `.name` will be `NAME`. But `at_level`'s `logger` argument is a capture/propagation aperture, not a rename; the records keep the name of the logger that emitted them. When the aperture is a parent package and the emitter is a child module reached via propagation, the names diverge silently. The resulting "got 0" looks like a production emission bug (warning not emitted) and wastes time re-reading the production `logger.warning(...)` call when the defect is one `==` predicate in the test.

**Distinguishing from lesson #66 (root-logger gating vs caplog bypass):** #66 is about caplog BYPASSING `configure_application_logging` (caplog attaches its own handler at the root), so a caplog-based test stays GREEN while a production runtime behavior is broken. This lesson is the opposite direction: caplog IS capturing the record correctly (the record is in `caplog.records`), but the test's own `rec.name` filter is too coarse and selects zero records, producing a FALSE NEGATIVE (test fails) rather than #66's FALSE POSITIVE (test passes). Both are Family H; #66's "real thing" is runtime file-handler output, this lesson's "real thing" is the actual `LogRecord.name` value.

**Distinguishing from lesson #65 (status note vs canonical artifact):** #65 is about trusting a summary over an artifact at verification time. This lesson is about trusting an aperture argument as if it set the record name; the artifact (`caplog.records`) was always correct, the test predicate was the abstraction that diverged.

**Required behavior:**
1. When filtering `caplog.records` by `rec.name`, match the emitting module's fully-qualified `__name__` (the precise logger name), not the parent-package aperture passed to `caplog.at_level`.
2. When a caplog assertion fails with "expected N, got 0" but the production emission is visible, suspect the `rec.name` filter first. Print `[rec.name for rec in caplog.records]` (and `[rec.getMessage() for rec in caplog.records]`) before changing production code.
3. Prefer the fully-qualified module name (or a message substring filter) over the parent-package aperture for `rec.name` equality, because the aperture controls capture, not naming.

**See also:** `tests/unit/application/test_crypto_fifo.py` (`TestCryptoFifoParsing#test_duplicate_tx_key_emits_single_summary`, the test whose `rec.name` filter was corrected), `src/tax_reporting/application/crypto_fifo/parsing.py` (`_dedup_by_tx_key`, the module whose `getLogger(__name__)` records carry the fully-qualified name), `docs/tmp/execute-plan/2026-07-21-configurable-log-level-and-warning-grouping/task-4-implement.log.md` (Task 4 implement log, Errors and retries section documents the parent-package filter false-zero), lesson #66 (caplog bypass vs configure_application_logging - opposite-direction Family H sibling), lesson #65 (summary-vs-artifact Family H sibling), pytest `caplog` docs (`LogRecord.name` semantics; `at_level` capture aperture vs record naming).

## 69. Planning a Per-Row WARNING→DEBUG Conversion Requires Two Verifications the Gist Does Not Give You: (a) Trace Each Site's Review Surface to the Rendered Cell, and (b) Sweep ALL `caplog.at_level(WARNING)` Assertions on the Substring

**Principle:** Family H (Verify the real thing, not the abstraction) - when a plan's justification for downgrading a per-row WARNING to DEBUG is "the per-row detail is already surfaced in the Excel review list" (the established per-row-DEBUG + aggregate-WARNING convention, `docs/maintenance/project-guidelines.md` rule #7), that justification is a CLAIM about production behavior, and two distinct claims ride on it. Claim A: the site actually sets `review_required=True` + a `review_reason` that renders as a user-facing cell (so the audit trail survives the console downgrade). Claim B: every existing test that pins the per-row WARNING via `caplog.at_level(logging.WARNING)` has been accounted for and rewritten (because `at_level(WARNING)` does NOT capture DEBUG records, so those assertions silently flip from green to RED). Both claims must be verified against source at PLAN time, not discovered at implementation time: Claim A by tracing `review_required`/`review_reason` from the emission branch through `CryptoFifoRealization`/`CryptoCapitalGainEntry` to the rendered `"YES: <reason>"` cell in the persisting sheet; Claim B by grepping ALL of `tests/` for `caplog.at_level(logging.WARNING)` (or the implicit WARNING default) co-located with the substring being downgraded. A plan that names ONE such test and stops has almost certainly missed siblings.

**Trigger:** You are writing or reviewing an implementation plan that converts a per-row `logger.warning(...)` to `logger.debug(...)` plus one aggregate `logger.warning(...)` summary (the warning-grouping recipe, predecessor `docs/history/plans/completed/2026-07-21-configurable-log-level-and-warning-grouping.md` patterns A–H, or a follow-up plan extending it). The plan's Gist asserts each converted site "duplicates the Excel review list" and lists one existing caplog test to rewrite. Before trusting the Gist, ask: (a) "Have I TRACED `review_required`/`review_reason` from this exact emission branch to the cell the user sees, or am I trusting a convention rule's prose?" and (b) "Have I grepped ALL test files for EVERY `caplog.at_level(logging.WARNING)` whose capture window includes this substring, or did I stop at the first test I found?"

**Rule:**
1. **Review-surface trace (Claim A):** for every site the plan proposes to downgrade, read the emission branch and confirm it sets `review_required=True` AND a non-empty `review_reason` on the domain object (`CryptoFifoRealization`, `CryptoCapitalGainEntry`, `CryptoReviewEntry`, `DerivativesPnLEntry`) that flows to a rendered cell. Do NOT trust a convention rule's assertion that a site "has a review-list surface" or "is the only audit surface" - convention prose drifts from code. Sites that set ONLY a log line and no review flag genuinely have no surface and must stay per-row WARNING (group-collapse the duplicates into one WARNING, do NOT downgrade to DEBUG). The trace is: emission branch → `acq.with_acq(review_required=True, review_reason=...)` / `entry.review_required = True` → persisting sheet `f"YES: {entry.review_reason}"` cell write.
2. **Caplog sibling sweep (Claim B):** when downgrading a per-row WARNING whose substring is `S`, run `grep -rn "caplog.at_level(logging.WARNING\|caplog.at_level( WARNING\|at_level(WARNING" tests/` to find every WARNING-level capture window, then for each co-located file grep for `S` and any sibling substring the same emission produces (e.g. for "Resolved carry-over cost" also grep "multi-sender", "partial", "unresolved"). Each match is a test that will flip RED; it must be rewritten (switch to `caplog.at_level(logging.DEBUG)` and assert on `r.levelno == logging.DEBUG`, or drop the caplog assertion and keep the field assertions) and listed in the plan's task. Finding one test is not sufficient - the sibling tests are usually in the SAME file, a few classes apart, asserting on the OTHER sub-branches of the same multi-branch emission function.
3. **Multi-branch emission functions compound the risk:** a function with N per-row WARNING branches (e.g. `_resolve_single_acquisition` has 4: unresolved / multi-sender / zero-carryover / partial) has up to N sibling tests, one per branch, often in adjacent test classes. A plan that rewrites only the test for branch 1 leaves branches 2–N broken at the full-suite gate.
4. **Distrust the rule prose, trust the trace.** A written convention (`project-guidelines.md` rule #7) that says "do NOT downgrade sites X, Y, Z because the log line IS the only audit surface" is itself a claim about code; if a follow-up trace shows X/Y set `review_required=True` + `review_reason` → rendered cell, the rule's RATIONALE is wrong even if its conclusion happened to be right for Z. Correct the rule to match the trace; do not honor a rule whose stated reason is empirically false.

**What happened (2026-07-23 planning `2026-07-23-group-leftover-crypto-warnings`, predecessor's leftover 4 patterns):** The predecessor plan shipped warning-grouping for patterns A–H but left 4 per-row patterns at WARNING (113 console lines on real data). Its `project-guidelines.md` rule #7 explicitly forbade downgrading three of them - "cross-asset FIFO unresolved-deferred-acquisition, transfer carry-over review, or untagged-whitelist fee removals" - claiming "the log line IS the only audit surface." Planning-time trace disproved this for two of three: `_resolve_single_acquisition` (`cross_asset.py:159/189/197/204`) and `_resolve_intra_asset_transfers` (`transfer.py:104/123`) BOTH return `acq.with_acq(review_required=True, review_reason=<detailed paragraph>)`, which propagates through `CryptoFifoRealization` and renders as `"YES: <reason>"` in `crypto_gains_sheet.py:45`. The rule's rationale was factually wrong for J/K (correct only for pattern I, `fee_filter.py:411`, which genuinely writes no review row). Separately, the plan initially identified ONE existing caplog test to rewrite (`test_crypto_fifo.py:917`, asserting at WARNING on "unresolved"); the r1 `review-plan` review found THREE MORE sibling tests the plan had missed: `:960` (multi-sender, asserts `"multi-sender"`/`"multiple source"`), `:1023` (partial, asserts `"partial"`/`"unprocessed"`), and `:2861` (transfer, asserts `"carry-over not found"`) - all `caplog.at_level(logging.WARNING)`, all flipping RED on the downgrade, all in the same file a few classes apart, one per branch of the multi-branch emission functions.

**Why this happens:** The warning-grouping recipe is mechanical enough (Counter + post-loop summary + per-row → DEBUG) that the plan author focuses on the conversion mechanism and treats the two justifications as given: (a) "of course it has a review surface, the convention says so" and (b) "I found the test that asserts on it." Both are abstractions over the real thing. The convention rule is prose that can lag the code (someone added `review_required=True` after the rule was written); the "first test found" is a sampling artifact when a multi-branch function has one test class per branch. The review panel catches both because it reads every emission site and greps the whole `tests/` tree, which is exactly the verification the plan author should have done up front.

**Scope confirmation (2026-07-25 `2026-07-25-relocate-crypto-warnings-to-extract` Task 2):** the rule is not specific to the DEBUG target. Demoting the W10 sub-1-EUR capital-gain aggregate `logger.warning(...)` to `logger.info(...)` flipped `test_parse_capital_gains_file_filters_sub_1_eur_after_aggregation` (no explicit `at_level`, so caplog captured at the implicit WARNING default and the INFO record vanished). Same Family H shape, same fix (wrap the call in `caplog.at_level(logging.INFO, logger="<emitter>")`); no new lesson, witness only. Confirms Rule #2's "implicit-WARNING default" already covers the WARNING→INFO direction, not only WARNING→DEBUG.

**Scope confirmation (2026-07-25 `2026-07-25-relocate-crypto-warnings-to-extract` Task 8):** the sibling-sweep rule applies even when the sweep is scoped to one call-flush family inside one task. Demoting the shared W1/W5 token_origin disagreement aggregate `logger.warning(...)` to `logger.info(...)` required rewriting the three caller-flush tests that pin the post-flush emission. The implementer updated two of three (the normal-flush and finally-on-exception cases); the mid-loop-exception sibling (`test_fifo_rebuild_caller_flush_still_fires_on_mid_loop_exception`) was missed and recovered by the orchestrator on diff inspection. Same Family H shape, same fix (`caplog.at_level(logging.INFO)`, `rec.levelno == logging.INFO`); no new lesson, witness only. Confirms Rule #2's "do not stop at the first match" extends to siblings within a single task's own sweep list, not only across the whole `tests/` tree.

**Scope confirmation (2026-07-25 `2026-07-25-relocate-crypto-warnings-to-extract` Task 9):** the rule applies to PER-ROW WARNING→INFO demotions, not only aggregate-flush ones. Demoting the W9 OGR no-CG-counterpart per-row `logger.warning(...)` in `_split_ogr_index` to `logger.info(...)` required updating the sibling safety-net test (`test_no_cg_no_th_tag_safety_net`) from WARNING to INFO assertions. Nuance worth recording: that test already captured via `caplog.at_level(logging.DEBUG)`, so the capture WINDOW already included INFO records and the records were present in `caplog.records` after the demotion - only the ASSERTION level (`rec.levelno == logging.INFO`, and the expected count) needed updating, not the `at_level` aperture. So a pre-existing DEBUG capture window makes the demotion cheaper than the Task 2/8 cases (no window rewrite), but the assertion still flips and must be swept. Same Family H shape, same fix family; no new lesson, witness only. Confirms Rule #2's sweep applies to per-row emission sites, and that a sibling test capturing at DEBUG needs only an assertion-level update rather than an aperture change.

**Distinguishing from lesson #47 (rename requires multi-pattern grep across ALL tests):** #47 is about grepping all tests when a RENAME touches scattered references (directory, filename, stem, glob, prose). This lesson is about grepping all tests when a LOG-LEVEL DOWNGRADE invalidates `caplog.at_level(WARNING)` capture windows - a different shape (the assertion predicate's level filter, not a renamed identifier) that #47's "multi-pattern rename grep" does not cover. Both share the Family H root: verify the real thing, not the first match.

**Distinguishing from lesson #68 (`rec.name` filter must match emitting module `__name__`):** #68 is about a caplog assertion that captures the record but FILTERS it away with a too-coarse `rec.name` predicate (false negative: "got 0"). This lesson is about a caplog assertion that never captures the record at all because the capture WINDOW (`at_level(WARNING)`) excludes the new DEBUG level after the downgrade (also "got 0", but the root cause is the level, not the name filter). Both are Family H; #68's fix is the `rec.name` string, this lesson's fix is switching the window to `at_level(DEBUG)` or dropping the caplog assertion.

**Required behavior:**
1. At PLAN time, for each proposed per-row WARNING→DEBUG site, TRACE `review_required`/`review_reason` from the emission branch to the rendered user-facing cell and record the trace in the task. If a site sets no review flag, it has no surface - keep it per-row WARNING (group-collapse, do not downgrade).
2. At PLAN time, grep ALL of `tests/` for `caplog.at_level(logging.WARNING)` (and the implicit-WARNING default `caplog.at_level(...)`) and for the substring being downgraded AND sibling substrings from the same multi-branch function. List every matching test as a rewrite sub-task in the plan; do not stop at the first match.
3. When a plan invokes the warning-grouping recipe and its Gist asserts "has a review surface" or lists only one caplog test, treat those as unverified claims: read the emission branch and run the caplog sweep before approving the plan.
4. If a follow-up trace shows a convention rule's stated RATIONALE (not just its conclusion) is wrong about which sites have a surface, correct the rule text in the same plan.

**See also:** `docs/history/plans/2026-07-23-group-leftover-crypto-warnings.md` (the plan where both verifications were required; Task 5 corrects rule #7), `docs/history/reviews/2026-07-23-plan-review-group-leftover-crypto-warnings-r1.md` (r1 review findings 1 and 2 are the three missed sibling caplog tests), `docs/maintenance/project-guidelines.md` rule #7 (the convention whose rationale was wrong for J/K), `src/tax_reporting/application/crypto_fifo/cross_asset.py` (`_resolve_single_acquisition`, 4-branch emission with `review_required=True`), `src/tax_reporting/application/crypto_fifo/transfer.py` (`_resolve_intra_asset_transfers`), `src/tax_reporting/application/persisting/crypto_gains_sheet.py:45` (`f"YES: {entry.review_reason}"` - the rendered review surface), lesson #47 (rename multi-pattern grep - same family, different shape), lesson #68 (caplog `rec.name` filter - same family, opposite-direction sibling), lesson #66 (root-logger gating - same family, runtime-vs-test), lesson #65 (status note vs canonical artifact - same family), lesson #70 (doc-family prose sweep for logging-level changes - the docs-side mirror of this lesson's test-side caplog sweep).

## 70. A Logging-Level Change (per-row WARNING->DEBUG + aggregate WARNING) Drifts LEVEL-DESCRIPTION PROSE Across a Doc-Family; the Sweep Must grep for the LEVEL PHRASE, Not the Identifier

**Principle:** Family H (Verify the real thing, not the abstraction) - when a plan converts a per-row `logger.warning(...)` to `logger.debug(...)` plus one aggregate `logger.warning(...)` summary (the warning-grouping recipe, `docs/maintenance/project-guidelines.md` rule #7), the code change is small but its PROSE shadow is wide: multiple canonical docs (`docs/maintenance/*.md`, README, project-decisions) describe the same emission sites in prose as "log at WARNING", "the WARNING log", "logger.warning(...) for X". Those prose phrases are abstractions over "what level does this site emit at"; after the conversion they are all empirically false. The doc drift is NOT a deleted identifier (lesson #55's shape) and NOT a sentinel's rendered-text label (lesson #58's shape); it is a LEVEL-CONVENTION phrase repeated across a doc-family, where the grep target is the LEVEL WORD ("WARNING" / "logger.warning"), not a name. Because the same level phrase appears in many sibling docs far apart in the file tree, a site-by-site fix that corrects ONE doc (the one the plan task touches) silently leaves the siblings stale. The next review round re-surfaces the same drift family at new file:line coordinates; the plan author "fixes" it again per site without ever doing the family sweep that would have caught them all at once. Compounded by Family D (Single source of truth): the live contract is the code's `logger.debug(...)` / `logger.warning(...)` call; each prose restatement is an independent copy that must be reconciled, and a doc-family of N copies means N drift opportunities.

**Trigger:** You are implementing or reviewing a plan task that downgrades a per-row `logger.warning(...)` to `logger.debug(...)` (with or without adding an aggregate WARNING), AND any canonical doc narrates that site's logging behavior in prose. Before declaring the task done, ask: "Did I grep EVERY canonical doc root (`docs/maintenance/`, `docs/architecture/`, `README.md`, project-decisions) for the LEVEL phrase this site used ('log at WARNING', 'the WARNING log', 'logger.warning' + the site's substring), or did I only correct the one doc the task happened to edit? Are there sibling docs in the same logging-convention family that describe the same or a sibling emission site at the old level?"

**Shape trigger (when to suspect this family):** A plan task converts a `logger.warning(...)` call to `logger.debug(...)` (the warning-grouping recipe), or changes which level a per-row vs aggregate emission uses. The task's verification grep (if any) scans for the SUBSTRING or the FUNCTION NAME. Before marking GREEN, ask: "Does any canonical doc describe this site's level in prose ('logs at WARNING', 'the WARNING log', 'logger.warning(...)')? Is the grep pattern the LEVEL WORD or only the identifier? Did I find one stale doc and stop, or sweep the whole doc-family?"

**Rule:**
1. **Sweep the LEVEL PHRASE, not the identifier.** When a logging-level change lands, the stale-prose grep target is the level word ("WARNING" / "logger.warning" / "log at WARNING" / "the WARNING log") co-located with the site's substring or a sibling emission's substring. A grep for only the function name or the downgraded substring misses docs that describe the level in prose without naming the function. Run `grep -rn -iE "log at warning|the WARNING log|logger\.warning" docs/maintenance/ README.md` and reconcile every hit against the post-conversion level.
2. **Family sweep, not site fix.** The same level-convention prose repeats across a doc-family (project-guidelines, crypto_implementation_guidelines, crypto_reporting_guidelines, project-decisions, README). Fixing the one doc the task edited leaves the siblings stale; the next review round re-discovers them. After correcting one stale doc, immediately grep the OTHER docs in the same family for the same level phrase and fix all of them in the same pass. Do NOT rely on a later review round to surface sibling drift - review sub-agents read different docs and may each find a different sibling, serializing what should be one sweep.
3. **Re-grep after the sweep to confirm zero stale prose.** After the family sweep, re-run the level-phrase grep across the same doc roots; every remaining hit must be a site that genuinely still emits at WARNING (e.g. the mandatory aggregate WARNING for a no-surface pattern like I, or an unrelated emission). If a hit is ambiguous, trace it to the production `logger.<level>(...)` call site before accepting it.
4. **The aggregate WARNING is itself a new prose claim.** When the conversion ADDS an aggregate `logger.warning(...)` summary, docs that previously said "one WARNING per row" must now say "per-row DEBUG + ONE aggregate WARNING"; the count and the per-row level both changed. A doc that correctly said "one aggregate WARNING" before a SECOND aggregate was added (e.g. a dedup aggregate plus an untagged-whitelist aggregate in the same fee pass) is now stale by omission - sweep for the aggregate count too, not only the per-row level.

**Witness (2026-07-23 `2026-07-23-group-leftover-crypto-warnings` review r4, post-r3 commit aeefb60):** A FIFTH stale level-prose site surfaced in the same doc family at `crypto_implementation_guidelines.md:1742` ("Unlisted-asset suspect surfacing" listing "a `logger.warning` naming the asset and its `Net Value (EUR)`"). The production per-suspect record at `_surface_suspects` (`fee_filter.py:633`) emits at `logger.debug(...)` (downgraded by the predecessor plan, which treats the `CryptoReviewEntry` as the review surface per pattern A); the only WARNING in that path (`fee_filter.py:643`) carries a bare count. r3's R3-1a flagged the same line and dropped it as born-stale / predecessor-caused / outside the plan's 5-pattern scope (I/J/K/L/F). r4 re-raised it with the winning argument: the plan AUTHORED lesson #70 (this lesson) whose Rule #2 mandates the doc-family sweep, and the plan already fixed the immediately-adjacent fee-removal section at line 1767, so a known-stale claim 25 lines from a fix is exactly the drift Rule #2 exists to prevent. Reworded to per-suspect `logger.debug` (pattern A) + ONE aggregate WARNING count. Reinforces Rule #2: a plan that codifies a sweep rule should honor it on the same file it edited, even when the hit is born-stale and outside the plan's nominal pattern scope.

**What happened (2026-07-23 `2026-07-23-group-leftover-crypto-warnings` review r2, post-r1-fix commit 3779b72):** The plan shipped warning-grouping for patterns I/L (per-row DEBUG + aggregate WARNING). r1 review already fixed doc drift in `crypto_implementation_guidelines.md` at lines 881/903 (pattern F/J sibling) and `project-guidelines.md` rule #7. r2 fresh adversarial review found FOUR MORE stale level-prose claims in the SAME doc family that r1 missed: `crypto_implementation_guidelines.md:1767` ("untagged-whitelisted removals log at WARNING ... Exactly one aggregate summary WARNING" - now per-lot DEBUG + TWO aggregate WARNINGs), `crypto_implementation_guidelines.md:911` ("logger.warning(...)" for pattern F placeholder buys - now per-row DEBUG + aggregate WARNING, predecessor-caused), `crypto_reporting_guidelines.md:117` CRG-020 ("the WARNING log" - now per-lot DEBUG in file handler), and a doc-drift sweep then surfaced TWO MORE siblings in the same family: `project-decisions.md:37` ("the WARNING log") and `crypto_implementation_guidelines.md:423` ("the WARNING log"). Six stale level-prose claims across four docs, all the same drift family, all invisible to the plan task's site-by-site grep because the grep targeted the substring/function-name, not the level phrase, and did not sweep the doc-family after the first fix.

**Why this happens:** Logging-level conversions are presented as a "code" change with docs as "downstream cleanup", so the plan task's verification grep mirrors the code change (grep for the function or substring). The level phrase ("the WARNING log", "log at WARNING") is prose, not an identifier, so it does not occur to the author to grep for a common English word. Meanwhile the doc-family is large (4+ canonical docs all describe crypto logging conventions) and the same level phrase is copy-pasted across siblings, so one fix leaves N-1 stale. The r1 review found the doc the task touched; r2's fresh panel read DIFFERENT docs and found different siblings. Each round "fixes" one site without doing the family sweep, so the drift keeps re-appearing until someone greps the level phrase across the whole family at once.

**Distinguishing from lesson #55 (deletion backstop greps must cover canonical docs):** #55 is about a DELETED MECHANISM's identifier surviving a code-only grep (the grep SCOPE was too narrow: `src/ tests/` only, missed `docs/maintenance/`). This lesson is about a LOGGING-LEVEL CHANGE's prose phrase surviving a docs-scope grep (the grep PATTERNS were too narrow: substring/identifier only, missed the level word). #55 widens the grep SCOPE to include docs; this lesson widens the grep PATTERNS to include the level phrase AND requires a doc-FAMILY sweep (not just scanning docs, but fixing all sibling docs in one pass after the first hit). Both are Family H; #55's failure is "didn't scan docs at all", this lesson's failure is "scanned docs but grepped the wrong token and fixed only one sibling".

**Distinguishing from lesson #58 (sentinel rendered-text reconciliation):** #58 is about a NEWLY SHIPPED constant's rendered-text label drifting across docs/README/note-cells (the value the user SEES in a cell disagrees with the constant). This lesson is about a LOGGING LEVEL (not a rendered value) drifting across docs (the level at which a record is emitted disagrees with the doc's prose). #58's grep target is the constant's value string; this lesson's grep target is the level word. Both are Family H + D (multiple prose copies of one source-of-truth fact); #58 reconciles rendered text, this lesson reconciles level prose.

**Distinguishing from lesson #69 (caplog sibling sweep for WARNING->DEBUG):** #69 is the TEST-SIDE mirror: when a per-row WARNING becomes DEBUG, every `caplog.at_level(WARNING)` assertion on the substring flips RED and must be rewritten (grep tests for the level capture window). This lesson is the DOCS-SIDE mirror: when a per-row WARNING becomes DEBUG, every prose restatement of the level ("log at WARNING", "the WARNING log") becomes false and must be rewritten (grep docs for the level phrase). #69 sweeps `tests/` for `at_level(WARNING)`; this lesson sweeps `docs/maintenance/` + README for the level word. Both are required for the same conversion; doing only one leaves the other side stale.

**Required behavior:**
1. When a plan task converts a `logger.warning(...)` to `logger.debug(...)` (with or without adding an aggregate WARNING), the task's verification grep MUST include a level-phrase pattern (`grep -rn -iE "log at warning|the WARNING log|logger\.warning" docs/maintenance/ README.md`) co-located with the site's substring, NOT only the function name or the downgraded substring.
2. After correcting the first stale doc, immediately grep the OTHER docs in the same logging-convention family (project-guidelines, crypto_implementation_guidelines, crypto_reporting_guidelines, project-decisions, README) for the same level phrase and fix all siblings in the same pass. Do not defer sibling fixes to a later review round.
3. When the conversion ADDS or CHANGES the count of aggregate WARNINGs, sweep docs for the aggregate-count prose too ("one aggregate WARNING" -> "two aggregate WARNINGs"), not only the per-row level.
4. Re-run the level-phrase grep across all doc roots after the sweep; every remaining hit must trace to a production `logger.<level>(...)` call that genuinely still emits at that level.

**See also:** `docs/maintenance/project-guidelines.md` rule #7 (the warning-grouping convention whose prose drifted), `docs/maintenance/crypto_implementation_guidelines.md:1767,911,423,1742` (r2/r4 stale level-prose sites; :1742 is the r4 suspect-fee per-row DEBUG + aggregate WARNING count site), `docs/maintenance/crypto_reporting_guidelines.md:117` (CRG-020 "the WARNING log"), `docs/maintenance/project-decisions.md:37` (sibling "the WARNING log" found in family sweep), `docs/history/reviews/2026-07-23-group-leftover-crypto-warnings-code-review-r2.md` (r2 findings R2-5/R2-6/R2-7/R2-8 are the four stale level-prose claims; the doc-drift sweep found two more siblings), `docs/history/reviews/2026-07-23-group-leftover-crypto-warnings-code-review-r4.md` (r4 finding R4-1 is the suspect-fee born-stale site the plan still owed under its own Rule #2), lesson #55 (deletion doc-grep scope - same family, scope-vs-pattern distinction), lesson #58 (sentinel rendered-text reconciliation - same family, value-vs-level distinction), lesson #69 (caplog test-side sweep - the test-side mirror of this docs-side sweep), lesson #47 (rename multi-pattern grep - same family, identifier-vs-level distinction).

## 71. After a Sub-Agent docs-branch / worktree Operation, Verify the Main Repo's `git status` Is Clean and the Working Tree Matches HEAD Before the Next Commit; a Botched worktree/checkout/stash Can Leave the Index in a Reverted State That a Blind `git commit` Captures as a Feature Rollback

**Principle:** Family E (Temporal / ordering invariants) - a later event (a blind `git commit` in the next `done`/review-iteration commit step) consumes git-index state that an earlier event (a sub-agent's `docs-branch` worktree-based orphan-branch sync, or a botched `git checkout`/`git stash`/`git worktree` operation) mutated in a way that makes the precondition "working tree == HEAD" go STALE. The precondition was true when the orchestrator handed control to the sub-agent; it is no longer guaranteed when control returns, because the sub-agent's worktree/branch gymnastics can leak the orphan (docs) branch's base files back into the main repo's index and working tree, producing a staged REVERT of the entire feature while HEAD stays correct. Compounded by Family H (Verify the real thing, not the abstraction) - "the working tree was clean before the sub-agent ran" is an abstraction that does not survive the sub-agent's git mutation; the concrete post-condition the next commit must check is `git status` clean AND `git diff --cached --stat` empty (or matching only intended edits), not the remembered pre-condition. Compounded by Family A (Mechanical invariants over prompt advice) - the detection signal is mechanical and grep-able: a test-count DROP (1831 -> 1825) and/or `git diff --cached --stat` showing large deletions (+73/-1062 across 14 files); these are observable invariants, not judgment calls.

**Why this matters:** If the next `done` (or any commit step) runs `git commit` while the index holds the leaked revert, it commits the rollback and silently destroys the feature. HEAD looked correct (a8e451b) and `git log` looked correct, so a commit step that only checks HEAD/log (or trusts the orchestrator's "clean tree" note from before the sub-agent ran) ships the rollback. The recovery cost once committed is high (the rollback is now in history; reverting the revert re-introduces the feature but pollutes the log and can confuse review/CI baselines). The near-miss is invisible without the mechanical pre-commit checks because the index state is not surfaced by `git log` or `git show HEAD`.

**Shape trigger (when to suspect this family):** You are about to commit (or you just acquired control back from a sub-agent that ran `docs-branch`, a `git worktree` operation, a `git checkout`/`git stash`, or any orphan-branch sync). Ask: did a sub-agent or a prior process mutate the git index/worktree since the last time I (or the orchestrator) confirmed the tree was clean? If yes, the precondition "working tree matches HEAD" may be stale. This is independent of which feature, which repo, or which agent ran - it is about ANY intermediate git-state mutation between the last known-clean snapshot and the next commit.

**General form:** After any operation that mutates git index/worktree state outside your direct control (a sub-agent's `docs-branch` worktree sync, a `git worktree` add/remove, a `git checkout`/`git stash`/`git restore` that a sub-agent ran), and before the next `git commit`, mechanically verify (1) `git status` reports a clean tree (or only your intended edits) and (2) the staged diff matches HEAD plus only your intended edits (`git diff --cached --stat`). The signal that the index is in a reverted state is a test-count DROP on the suite you are about to commit (run `uv run pytest --co -q | tail -1` or equivalent and compare against the known-good count) and/or a `git diff --cached --stat` showing many deletions across files you did not intend to touch. If either signal fires, run `git reset --hard HEAD` to discard the leaked revert, re-stage ONLY your intended edits, then re-verify before committing. Do NOT run `git add -A`/`git add .` before this verification - it would stage the entire rollback.

**Required behavior:**
1. Before ANY `git commit` that follows a sub-agent's `docs-branch`/worktree/checkout/stash operation (including the `done` Step 3 commit that follows `done` Step 2 `docs-branch`, and the per-review-iteration `done` commit), run `git status` and `git diff --cached --stat` and confirm the only staged/unstaged paths are the ones you intentionally edited this iteration.
2. If `git diff --cached --stat` shows large deletions across files you did not edit (e.g. +73/-1062 across 14 files), STOP. The index holds a leaked revert from the sub-agent's git operation. Run `git reset --hard HEAD`, then re-stage only your intended edits.
3. Cross-check with the test suite: a test-count DROP (1831 -> 1825 in the witness) is a strong independent signal of a rollback in the working tree, because a revert of a feature removes that feature's tests. If the count is lower than the last known-good count on HEAD, investigate the working tree before committing.
4. Never use `git add -A`/`git add .` in a `done` commit step that runs after a sub-agent git operation; stage specific intended files by name so a leaked revert cannot be swept into the commit.
5. The orchestrator's "working tree clean" or "HEAD correct" note is only valid as-of the moment it was written; a subsequent sub-agent git op invalidates it. Re-verify at commit time, not at the time the note was authored.

**Example (2026-07-23 `2026-07-23-group-leftover-crypto-warnings` review r6):** r6 review ran `pytest` against the working tree (HEAD a8e451b, the verified feature tip with 1831 tests) and got 1825, not 1831. Investigation showed the working tree + git index held a STAGED REVERT of the entire feature (+73/-1062, 14 files, 1825 tests vs 1831) while HEAD was correct (a8e451b). The revert was a side effect of a prior `done` sub-agent's `docs-branch` Step 2 worktree-based orphan-branch sync: a botched worktree/checkout operation restored files from the docs orphan branch base into the main repo's index/worktree. The orchestrator caught it ONLY because r6 ran pytest and flagged the 6-test drop; if the next `done` had run `git commit` (or `git add -A && git commit`) without checking `git status`/`git diff --cached --stat`, it would have committed the rollback and silently destroyed the feature. Resolution: `git reset --hard HEAD` restored the verified feature state (1831 tests, clean tree, HEAD a8e451b unchanged). No commit ever captured the revert. This was an ENVIRONMENTAL artifact, not a code defect, but the pre-commit verification rule is now required because the near-miss was real and the detection signal (test-count delta + staged-deletion count) is mechanical.

**Distinguishing from lesson #64 (execute-plan Phase 5 cleanup exit path):** #64 is about ephemeral tmp/session-dir files surviving a non-success exit and being synced permanently by the add-only docs-branch (a file-accumulation problem). This lesson is about the docs-branch/worktree operation MUTATING the main repo's git INDEX into a reverted state that the next commit captures (a commit-integrity problem). #64's symptom is doc/tmp pollution; this lesson's symptom is a feature rollback in committed history. Both share the docs-branch worktree as the vector, but the mechanism and the required pre-commit check differ.

**Distinguishing from AGENTS.md rule "For comparing tool output against the committed baseline ... never `git stash`" (rule ~4.x):** that rule forbids `git stash` specifically as a verification-script tool because it can lose work. This lesson is broader: it covers ANY sub-agent git-state mutation (worktree sync, checkout, stash, restore) that can leave the index reverted, and it prescribes the post-subagent pre-commit verification, not a ban on one tool.

**See also:** `docs/history/reviews/2026-07-23-group-leftover-crypto-warnings-code-review-r6.md` (Environmental note section; the witness for this near-miss, including the +73/-1062 staged-revert and the 1831->1825 test-count signal), `docs/history/plans/2026-07-23-group-leftover-crypto-warnings.md` (the plan whose r6 review surfaced it), lesson #64 (execute-plan Phase 5 cleanup exit path - shares the docs-branch vector, different mechanism: file accumulation vs index revert), `agents/skills/done/SKILL.md` Step 3 (the commit step that must run the pre-commit verification after `docs-branch` Step 2; the guard this lesson codifies lives there), `agents/skills/docs-branch/SKILL.md` (the worktree-based orphan-branch sync whose botched operation leaked the revert; the upstream mitigation target).

## 72. When the Repo Has a Linter Configured but NO CI Gate (no pre-commit, no GitHub Actions), "ruff clean on my diff" Is Necessary but Not Sufficient; Run `ruff check` on the COMMITTED BASELINE (HEAD blob), Not the Working Tree, Because Pre-Existing Violations Silently Accumulate on master and a Diff-Only Clean Can Mislead You Into Adding `# noqa` to a Function Whose Predecessor Already Violated

**Principle:** Family H (Verify the real thing, not the abstraction) - "I ran `ruff check` and it passed" is an abstraction. The concrete invariant that actually holds repo health is "the committed baseline (HEAD) passes `ruff check`," which is a DIFFERENT and STRONGER property than "my working-tree diff introduces no new violations." When no CI gate enforces the former, the two properties drift apart: pre-existing violations live on master indefinitely (no gate rejects them), and a per-diff `ruff check` against the working tree reports clean even when the file already violated at HEAD. Compounded by Family A (Mechanical invariants over prompt advice) - the only mechanical signal that exposes the gap is running `ruff check` on the HEAD blob (`git show HEAD:<file> | ruff check --select <rule> -` or writing the blob to a temp file), not reasoning about "did I add a violation." Compounded by Family B (Make the implicit explicit / surface hidden state) - the hidden state here is "master carries N unsuppressed lint violations right now," which is invisible to a per-diff workflow until a new edit to the same function crosses a threshold (e.g. arg count 6 -> 7) and forces a `# noqa` that looks NEW but is silencing PRE-EXISTING debt.

**Why this matters:** Without the baseline check, an agent (or human) making a defensible small edit to a function that already violated at HEAD will either (a) add a `# noqa` and believe it is "new debt I am introducing," when it is actually silencing pre-existing debt that a refactor would also need to address, or (b) be surprised that a "trivial" edit (adding one keyword argument) suddenly turns a clean file into one `ruff check` reports as erroring, because the threshold crossing happened on this edit even though the violation's root cause predates it. The result is mis-attributed technical debt: the blame lands on the current change/PR rather than on master's accumulated un-gated violations, and the repo-wide debt is never reconciled because no single change is forced to address it. The fix-up cost is deferred indefinitely because nothing in the loop ever surfaces "HEAD itself violates."

**Shape trigger (when to suspect this family):** You are about to add a `# noqa` (or a suppression comment in any language) to a function/file during a focused change, OR you are about to declare "this file is lint-clean" after running `ruff check` on the working tree. Ask: (1) Does this repo have a CI gate that runs the linter on PRs (`.github/workflows/`, pre-commit config)? If NO, the linter is manual-discipline-only, so the committed baseline can carry violations that a per-diff check will never reveal. (2) Before attributing a violation to the current change, did I run `ruff check` on the HEAD blob of this exact file? If you cannot answer yes, the violation may be pre-existing debt that the current edit merely crossed the threshold on, not new debt the edit introduced.

**General form:** When a repo configures a linter (Ruff, ktlint, ESLint, golangci-lint) but ships WITHOUT an enforcement gate (no pre-commit hook, no CI workflow that fails on violations), do NOT treat "my working-tree diff passes the linter" as equivalent to "the file is lint-clean." Before adding a suppression comment (`# noqa`, `@Suppress`, `eslint-disable`) to a function during a change, run the linter on the COMMITTED BASELINE of that file (`git show HEAD:<path> > /tmp/head_blob.<ext>` then `ruff check /tmp/head_blob.<ext>`, or `git show HEAD:<path> | ruff check --stdin-filename <path> -`). If the baseline already violates the same rule, the suppression is silencing pre-existing debt; record that fact explicitly (a comment naming the pre-existing violation and that a refactor is out of scope), do NOT attribute the debt to the current PR, and flag the baseline debt for a dedicated cleanup task. The diff-only clean check remains necessary (do not introduce NEW violations), but it is not sufficient to claim repo lint health when no gate enforces the baseline.

**Required behavior:**
1. Before adding any `# noqa` / suppression comment during a focused change, check whether the repo has a linter CI gate (`.github/workflows/` or `.pre-commit-config.yaml`). If absent, the linter is manual-discipline-only and the HEAD baseline can carry violations.
2. When the gate is absent, run the linter on the HEAD blob of the file you are editing (`git show HEAD:<path>` piped to or temp-written for the linter) for the specific rule you are about to suppress. If HEAD already violates, the suppression is covering pre-existing debt; note this in the commit/PR rationale (e.g. "HEAD's `_classify_th_row` already had 6 params > 5; the 7th param crosses the same PLR0913 threshold; suppression defensible, refactor out of scope") rather than implying the change introduced the violation.
3. Never claim "this file is lint-clean" based solely on a working-tree `ruff check` when no CI gate enforces the baseline; qualify the claim as "this diff introduces no new violations" (the weaker, accurate statement).
4. When you discover HEAD-level baseline violations during a change, surface them for a dedicated cleanup rather than silently absorbing them into the current change's suppression - the cleanup task should not be implicit in a logging/refactor PR.

**Example (2026-07-24 `2026-07-24-silence-expected-and-excel-surfaced-warnings` Task 5):** Task 5 added an `empty_cost_basis_counter` keyword argument to `_classify_th_row` in `src/tax_reporting/application/crypto_fifo/parsing.py`, raising its parameter count from 6 to 7 and tripping Ruff's `PLR0913` (too many arguments, > 5). The implementer added `# noqa: PLR0913`. A subsequent `ruff check` on the working tree of all changed production files returned "All checks passed!" because the noqa suppressed it. However, running `ruff check --select PLR0913` on the HEAD blob of `parsing.py` (via `git show HEAD:src/tax_reporting/application/crypto_fifo/parsing.py > /tmp/head_parsing.py; uv run ruff check --select PLR0913 /tmp/head_parsing.py`) revealed "Found 1 error" - `_classify_th_row` ALREADY had 6 parameters at HEAD (unsuppressed PLR0913 violation on master). The repo has no `.github/workflows/` and no `.pre-commit-config.yaml`, so Ruff is configured (`pyproject.toml`: Python 3.14, line length 120, full ruleset) but completely unenforced. The 7th parameter did not CREATE the PLR0913 debt; it crossed the threshold on debt that already existed. The `# noqa: PLR0913` is therefore correctly attributed as "silences pre-existing master debt; refactor-to-context-object out of scope for this logging plan," NOT as "new debt Task 5 introduced." The diff-only working-tree `ruff check` would have reported clean either way, masking the baseline violation; only the HEAD-blob check exposed that the violation predates this change.

**Distinguishing from lesson around line 765/779 (PLR0912 branch-limit: extract a helper rather than inline `# noqa`):** those lessons address the DESIGN CHOICE of whether to suppress or refactor when YOU introduce the complexity. This lesson addresses the EPISTEMIC problem of whether the violation is yours at all: when no CI gate exists, you cannot tell from a working-tree `ruff check` whether the violation is new (your refactor target) or pre-existing (master debt you are merely thresholding). The fix here is a baseline-check STEP, not a refactor-vs-suppress design decision.

**Distinguishing from lesson around line 730 (validate that gates actually gate):** that lesson is about a gate that CLAIMS to validate but silently no-ops (a script that exits 0 on a known violation). This lesson is the ABSENCE of any gate at all - there is no script to no-op; the linter runs only when a human/agent remembers to invoke it, and the baseline accumulates violations between invocations. The fix here is "run the linter on HEAD, not just the diff," not "fix a broken gate script."

**See also:** `docs/history/plans/2026-07-24-silence-expected-and-excel-surfaced-warnings.md` (Task 5; the change that surfaced the pre-existing PLR0913 on `_classify_th_row`), AGENTS.md rule on Ruff as primary linter (rule ~4.x: "Ruff is primary linter/formatter; pyproject.toml Python 3.14, line length 120, full ruleset" - configures but does not ENFORCE), lesson around line 765/779 (PLR0912 extract-vs-suppress design choice - different concern: how to handle complexity YOU introduce), lesson around line 730 (validate gates actually gate - different concern: a present-but-broken gate vs the absent gate here), `coding_guidelines.md` #17+ (Family H / Family A principle catalog).

## 73. Log-Level Bucket Assignments Must Be Re-Derived by Tracing the Site's Output Through ALL Branches of the Pipeline to the Rendered Excel Review Cell, Not by Reading the Emitter Line or Tracing Only the Happy Path

**Principle:** Family H (Verify the real thing, not the abstraction) - "the emitter line calls `logger.warning` and the happy path rewrites `source_type`, so this site is dead in production" is an abstraction over the partial trace. The concrete invariant that holds is "does ANY branch of the downstream pipeline reach this emitter with the warning-level emission intact AND render a review cell?," which requires tracing EVERY branch (including the UNRESOLVED / error / cycle branch), not just the one a code-reading glance settles on. Compounded by Family A (Mechanical invariants over prompt advice) - the only mechanical signal that exposes the missed branch is a full data-flow trace from the emitter through every `return` / `with_acq` / `dataclasses.replace` site to the rendered cell, not a one-line reachability argument.

**Why this matters:** A bucket assignment (EXPECTED_BEHAVIOR / HAS_EXCEL_SURFACE / DEVELOPER_ACTIONABLE) built on a partial trace silently mis-classifies a site. If a reachable branch is missed, a site that DOES reach a review cell gets classified DEVELOPER_ACTIONABLE (no surface) and stays WARNING, leaving console noise the plan intended to silence; or worse, a site classified HAS_EXCEL_SURFACE on the happy path turns out to reach the cell only sometimes, so the audit signal vanishes for the rows that do not. The review-plan panel caught the specific case below; without the panel, the plan would have shipped with a wrong bucket assignment and the suite (which asserts log levels, not reachability truth) would have passed.

**Shape trigger (when to suspect this family):** You are about to declare "this `logger.warning` site is dead in production" or "this site always/never reaches the review cell" based on reading the emitter plus tracing ONE path. Ask: (1) Did I trace EVERY `return` in the function that emits, including the UNRESOLVED / error / cycle / early-return branches? (2) Does any branch construct the entry with a helper that uses `dataclasses.replace` (which PRESERVES fields the branch did not set), so an upstream field value reaches the cell even though THIS branch never assigned it? If you cannot answer yes to (1) and no to (2), the reachability claim is unverified.

**General form:** When assigning a per-row WARNING to a log-level bucket, derive the assignment by tracing the site's output through ALL branches of the pipeline to the rendered Excel review cell, not by reading the emitter line or tracing only the happy path. Specifically: enumerate every `return` in the emitting function and every downstream consumer; for branches that build the entry via a `with_*` helper backed by `dataclasses.replace`, confirm which ORIGINAL fields survive (replace preserves unspecified fields), because an upstream `source_type` / `review_required` can reach the cell through a branch that never set it. A branch that returns an entry with `review_required=True` + `review_reason` WITHOUT rewriting `source_type` is STILL reachable and STILL surfaces the cell if any caller retains the original `source_type`.

**Required behavior:**
1. Before classifying a per-row WARNING, list every `return` in the emitting function (including UNRESOLVED / error / cycle branches), not just the resolved happy path.
2. For each branch, trace the returned entry to the rendered cell, accounting for `dataclasses.replace` / `with_*` semantics: fields the branch did not set are PRESERVED from the original, so an upstream field can carry the entry to the cell through a branch that looks like it "does nothing."
3. Treat a branch as reachable if ANY caller path can enter it (tx_key mismatch, dependency cycle, pool exhaustion), even if the production happy path never does - production reachability is empirical and changes with the dataset; the bucket must hold for all inputs.
4. When in doubt, have a review-plan panel re-trace the data flow; a second trace over the full branch set is the cheapest verification.

**Example (2026-07-24 `2026-07-24-silence-expected-and-excel-surfaced-warnings`, deferred-acquisition-consumed site / pattern P):** The plan's initial trace of `src/tax_reporting/application/crypto_fifo/matching.py:175` concluded it was "dead in production because `cross_asset` rewrites `source_type` first" - i.e. the happy path in `cross_asset._resolve_single_acquisition` resolves the acquisition and sets `source_type` to a resolved value, so the `source_type="exchange_in_deferred"` branch at `matching.py:175` never fires. But `cross_asset._resolve_single_acquisition` has an UNRESOLVED branch (`cross_asset.py:190-203`) that returns via `with_acq(review_required=True, review_reason=...)` WITHOUT setting `source_type`. Because `with_acq` uses `dataclasses.replace`, the ORIGINAL `source_type="exchange_in_deferred"` is PRESERVED, so `matching.py:175` IS reachable (tx_key mismatch / dependency cycle enters the unresolved branch). The site therefore DOES set `review_required=True` + `review_reason` that renders as the "YES:" cell, making it Bucket B (HAS_EXCEL_SURFACE), not Bucket C (DEVELOPER_ACTIONABLE). The review-plan panel's full-branch trace caught this; the partial emitter-line trace had mis-classified it.

**Distinguishing from lesson #69 (per-row WARNING->DEBUG conversion requires tracing the review surface):** #69 establishes that you MUST trace each site's review surface before converting. This lesson sharpens HOW: trace through EVERY branch (including unresolved/error/cycle), and account for `dataclasses.replace` field-preservation, because a partial trace reaches the wrong conclusion even when following #69's "trace the surface" instruction. #69 says "trace it"; this lesson says "trace ALL branches, and watch for replace-preservation, or the trace is wrong."

**See also:** `docs/history/plans/2026-07-24-silence-expected-and-excel-surfaced-warnings.md` (Invariant #2; the deferred-acquisition-consumed reachability re-verification), `docs/maintenance/project-guidelines.md` rule #7 (three-class taxonomy + pattern lookup table, pattern P), lesson #69 (per-row WARNING->DEBUG conversion requires review-surface trace), `coding_guidelines.md` Family H (verify the real thing) / Family A (mechanical invariants over prompt advice).

## 74. A "Third-Currency Fee" Warning That Treats ALL Non-Leg Fees as Anomalous Is CEX-Shaped and Wrong for DEX: On a DEX the Expected Fee Is the Chain's Native Gas Token (a Third Currency by Definition)

**Principle:** Family H (Verify the real thing, not the abstraction) - "a fee in a currency that is neither the sent nor the received asset is anomalous" is an abstraction that happens to hold for CEX data but is FALSE for DEX data, where paying gas in the chain's native token is the EXPECTED mechanism and that native token is a third currency by definition. The concrete invariant that holds across both venue types is the OR of two expected-case models, not a single CEX-shaped rule. Compounded by Family B (Make the implicit explicit / surface hidden state) - the hidden state is "this asset ticker is native gas on chain X but a bridged token on chain Y," which an asset-keyed lookup flattens and a chain-keyed lookup preserves.

**Why this matters:** A flat rule that demotes every non-leg third-currency fee to INFO silences genuinely anomalous fees (a USDC fee, a governance-token fee, a fee in an asset that is neither leg nor gas) along with the expected gas fees. Conversely, keeping every non-leg fee at WARNING floods the console with expected gas fees. Both extremes are wrong because the population is MIXED: most non-leg fees on a DEX are expected gas, but a minority are anomalous. Only the chain-keyed native-gas split separates the two populations. Empirically (the production dataset: 342 exchanges, 61 third-currency fees) the split is decisive: 19 fees have EUR value > 0 and ALL 19 are native-gas (6 ETH on Ethereum, 4 ETH on zkSync ERA, 9 BNB on Binance Smart Chain); zero genuine anomalous third-token fees with EUR value exist, but the split preserves the WARNING for the day one appears.

**Shape trigger (when to suspect this family):** You are writing or reviewing a fee-validation rule keyed on the FEE ASSET (e.g. "if fee_currency not in (sent, received) -> warn") and the data spans both CEX and DEX venues. Ask: (1) Is the rule CEX-shaped (assumes the fee comes out of a trade leg)? On a DEX the fee is gas, paid in a third token. (2) Am I matching the asset ticker directly (ETH, BNB, MATIC) without deriving the chain? ETH/BNB/MATIC are native gas on one chain but regular bridged tokens on others, so asset-keyed matching is unsafe. If either answer is yes, the rule is wrong for DEX.

**General form:** A third-currency-fee warning must apply a UNIFIED two-model expected-case rule (no explicit CEX/DEX branch needed): the fee is EXPECTED (no warning) when EITHER (a) the CEX model holds - `fee_currency in (sent_currency, received_currency)`, the fee is a trade leg - OR (b) the DEX model holds - `fee_currency == _CHAIN_NATIVE_FEE_ASSET[_derive_chain(wallet)]`, the fee is the chain's native gas. The fee is ANOMALOUS (STAYS WARNING) when NEITHER model holds, and FAIL-SAFE STAYS WARNING when the chain is `"Unknown"`. The native-gas map MUST be chain-keyed (never asset-keyed), because ETH/BNB/MATIC are native gas on one chain but bridged tokens on others; derive the chain per-row. A flat "demote all non-leg fees to INFO" is wrong; the split preserves the WARNING for the genuinely anomalous case.

**Required behavior:**
1. For any third-currency-fee site, classify with the OR of the two models (leg OR native-gas), not a single non-leg-is-anomalous rule.
2. Make the native-gas lookup chain-keyed (`_CHAIN_NATIVE_FEE_ASSET[_derive_chain(wallet)]`), never asset-keyed; add the chain's native gas token when a chain is added to the registry, mirroring `_KNOWN_CHAINS`.
3. Fail closed: when the chain is `"Unknown"`, STAY WARNING rather than guessing the gas token.
4. Do NOT flatten the rule to "demote all non-leg fees to INFO"; preserve the WARNING branch for the genuinely anomalous (USDC / governance-token / unknown-chain) case.

**Example (2026-07-24 `2026-07-24-silence-expected-and-excel-surfaced-warnings`, third-currency-fee site / Bucket A-split):** The third-currency-fee emitter at `src/tax_reporting/application/crypto/_emitters.py:65` (deferred) and `:195` (received-only) emitted `logger.warning` for every fee whose currency was neither leg. On the production dataset this fired for 19 EUR-valued fees that are ALL native gas (Ethereum ETH, zkSync ERA ETH, BSC BNB) - correct DEX behavior, not anomalies. The fix applies the unified two-model rule: the CEX leg-check is KEPT, and a new DEX native-gas branch (`fee_currency == _CHAIN_NATIVE_FEE_ASSET[_derive_chain(wallet)]`) silences expected gas. Asset-keyed matching was rejected because ETH/BNB/MATIC are native gas on one chain but bridged tokens on others; the map is chain-keyed. Anomalous fees (USDC, governance-token, unknown-chain) STAY WARNING, so the day a genuinely anomalous third-token fee with EUR value appears it is still surfaced.

**Distinguishing from lesson #72 (ruff baseline check):** unrelated concern (lint-gate epistemics vs fee-classification correctness). This lesson's nearest neighbor is the project-guidelines rule #7 native-gas split and the `crypto_implementation_guidelines.md` `_CHAIN_NATIVE_FEE_ASSET` entry, which codify the rule this lesson generalizes.

**See also:** `docs/history/plans/2026-07-24-silence-expected-and-excel-surfaced-warnings.md` (Terms: Bucket A-split; Tasks 1-3 the native-gas branch), `docs/maintenance/project-guidelines.md` rule #7 (native-gas split), `docs/maintenance/crypto_implementation_guidelines.md` "Chain Derivation" / `_CHAIN_NATIVE_FEE_ASSET`, `coding_guidelines.md` Family H (verify the real thing) / Family B (make the implicit explicit).

## 75. When the User Asks "Should We Build a Feature for This External Change?", Verify the Existing Pipeline Already Handles It Before Agreeing to Build; "No Feature Needed" Is a Valid Outcome, and Code Changes Requiring Absent Source-Data Years Are Untestable and Must Be Deferred to Research/Archive Work

**Principle:** Family H (Verify the real thing, not the abstraction) - "the user described an external change to a chain/token, so we must update the pipeline" is an abstraction over an unverified assumption that the pipeline branches on the changed thing. The concrete invariant is whether ANY production code path branches on the specific discriminator the change altered; if none does, the pipeline already handles the new case generically. Compounded by Family A (Mechanical invariants over prompt advice) - the only mechanical signal that exposes "no change needed" is a full data-flow trace of the pipeline against the new inputs, not a scope-agreement conversation with the user.

**Why this matters:** Agreeing to build a feature the pipeline already provides duplicates logic, adds hardcoded values (asset tickers, token sets) that violate the repo's no-hardcoding rule without real data to calibrate them, and produces untestable code when the trigger year's source data does not yet exist. The repo's testing rules (TDD RED-first, regression tests must exercise the production call site, tests must read committed synthetic data) make speculative token-handling code unvalidatable, so it ships on faith. The correct outcome is often a documented deferral plus research/archive work, not a feature.

**Shape trigger (when to suspect this family):** A user (or you, prompted by external news) proposes a code/config change driven by an external event (chain upgrade, token deprecation, source-format change). Ask: (1) Does ANY production code path branch on the discriminator the event changed (token identity, event type, fee currency, chain), or is that path asset/event-type agnostic? (2) Does the trigger year's source data exist to write a RED test against? If (1) is "no branch, generic handling" or (2) is "data absent," the feature is not yet warranted.

**General form:** Before proposing a feature/config change in response to an external event, trace the production pipeline to confirm a real branch depends on the changed discriminator. Capital-gains disposal rows are processed generically (no per-ticker branch); reward classification keys on Koinly event type, not ticker; native-gas fee filtering keys on the chain, not the staking/wrapping receipt tokens. If the pipeline is generic over the changed dimension, the correct response is a documented forward-looking note (decision log / deferred feature-note) plus, where durable, archiving the official source documents - NOT speculative token-list or config edits. Code changes whose RED test requires a source-data year that does not yet exist must be deferred until that data arrives; do research and archive work now, defer the code.

**Required behavior:**
1. When an external change is proposed as a feature trigger, FIRST trace the production pipeline to find any branch keyed on the changed discriminator. Grep the source for the token/asset/chain/event-type and read the consuming function.
2. If no branch depends on it (the path is generic), state "no code change needed, the pipeline handles this generically" and record a forward-looking note in the decision log naming what to review when trigger data arrives.
3. If a real branch exists but the trigger year's source data is absent, do NOT write the config/code change now (it would be untestable). Do research/archive work (mirror official docs into the source-extract folder, update the source manifest, record the date-conflict resolution) and defer the code to a data-driven plan.
4. Never add hardcoded token tickers or fee ceilings to runtime config files without the real source-data export that tells you which exact ticker strings the upstream tool emits; the maintenance-file edit is one line but must wait for testability.

**Example (2026-07-25 Berachain PoL Next inquiry):** A user asked whether to build a workflow feature for the 2026 PoL Next upgrade (BGT deprecation, WBERA emissions, new sWBERA liquid staking). Tracing the pipeline showed: the capital-gains path (`_parse_capital_gains_file`) processes any disposal row generically with no per-ticker branch (a BGT->WBERA redemption is handled identically to any swap); reward classification (`_classify_reward_tax_status`) is asset-agnostic, keying on Koinly event type; native-gas fee filtering (`chain_derivation.py`) keys on the chain's gas token, and sWBERA/stBERA are staking receipts not gas. No feature was needed. Additionally, the user had no 2026 Koinly export yet, so any token-list or fee-ceiling edit to `popular_crypto_tokens.json` / `decision_points/2025.toml` would be untestable. The correct deliverable was: archive the official PoL Next docs into `crypto-origin/official/` with the resolved mainnet date, update `sources.md`, and add a `CMD-022` decision-log entry with a forward-looking note deferring the token-list/fee review to when 2026 data arrives. Zero code/config changes.

**Distinguishing from AGENTS.md "Verification-first ordering" and "CRITICAL: Code inspection is INSUFFICIENT":** those rules govern verifying CODE BEHAVIOR against source data before making a change. This lesson governs the SCOPE decision that precedes the change: whether to propose a change AT ALL in response to an external event. The verification target also differs - those rules trace data-flow correctness; this lesson asks whether any branch depends on the changed discriminator (a no-branch answer means no change is warranted, which those rules do not address).

**Distinguishing from lesson #65 (plan status note vs canonical artifact):** #65 is about trusting a SUMMARY over the real artifact. This lesson is about trusting a SCOPE ASSUMPTION ("external change -> must build") over a pipeline trace. Same Family H shape, different target: #65 targets decision-status correctness, this targets feature-necessity correctness.

**See also:** AGENTS.md "Verification-first ordering" and "CRITICAL: Code inspection is INSUFFICIENT" (data-flow verification, the change-level rule this scope-level rule precedes), lesson #65 (verify against canonical artifact, not summary - same Family H shape, decision-status target), `docs/maintenance/tax/crypto-origin/mapping_decision_log.md` CMD-022 (the documented deferral that resulted from applying this lesson), `docs/maintenance/tax/crypto-origin/official/berachain_pol_next_2026-07-08.md` (the archive deliverable produced instead of code), `coding_guidelines.md` Family H (verify the real thing) / Family A (mechanical invariants over prompt advice).

## 76. Console WARNINGs Are Reserved for Project/Processing Problems; Every Data Issue and Methodology Decision Lives in the Excel Extract. Pin Demotion/Grep Tasks to a Stable Signature Substring, Not a Line Number (Line Numbers Drift Across a Session)

**Principle:** Two related rules share this lesson.

(a) **Governing principle (console vs extract separation).** Family D (Single source of truth) and Family H (Verify the real thing, not the abstraction) - "this anomaly should be a WARNING because the user needs to see it" is an abstraction over an unverified claim about WHERE the audit surface lives. The concrete invariant is: a console `logger.warning(...)` is the signal that *something is wrong with the project or the way it processes data*; every *data issue* (per-row anomaly attributable to the source export or pipeline edge case) and every *methodology decision* (dedup, materiality filter, OGR routing) lives in the user-facing Excel extract - either as `CryptoReviewEntry` rows in Crypto Supplementary's "Review required" section or as a run-specific count suffix on an A&M methodology item. A console WARNING that merely announces a count of items the user can already see in the extract duplicates the audit surface. When the extract already carries the signal (per-row review cell, explicit review row, or A&M count), the console aggregate demotes to `logger.info(...)`; the WARNING level is preserved only for sites with NO extract surface (rule #7 DEVELOPER_ACTIONABLE class). This is codified in `project-guidelines.md` rule #7 as the 4th target class **EXTRACT_SURFACED** (per-row DEBUG + aggregate INFO + rows in Crypto Supplementary OR a count cell in A&M), distinct from HAS_EXCEL_SURFACE (where the per-row entry's OWN schema already renders a review cell - no new rows are added).

(b) **Line-number-drift root cause (pin to a substring, not a line number).** Family E (Temporal / ordering invariants) and Family H - a plan task that pins a "demote this WARNING" or "grep for this emission" step to a FILE:LINE coordinate is pinning to a value that goes STALE the moment any edit above the site shifts line numbers within the same session. The concrete precondition the task actually needs is "find the emission whose SIGNATURE SUBSTRING is S and demote it"; a line number is an abstraction over that substring that drifts as soon as code is inserted or removed above the site. When the task is implemented by an agent that reads the pinned line number verbatim, a 125-line upstream drift (e.g. 378 -> 503 across a single session) silently points at the wrong call site, the demotion falls through, and the WARNING survives into the real-run log. The detection signal is mechanical: the 10-substring `logger.warning` grep in `src/tax_reporting/application/` returns a non-zero count after the plan claims "all demoted to INFO".

**Why this matters:** Without (a), the operator's real-run console fills with WARNINGs that are not bugs (dedup summaries, materiality filter counts, OGR routing decisions), burying genuine project/processing WARNINGs and training the operator to ignore the console. Without (b), a planned demotion silently no-ops because the line-number pin drifted, and the no-op is invisible to the plan's "tests pass" gate (the existing tests do not assert the level of the drifted site) - it is only caught when the operator re-runs the pipeline and re-counts WARNINGs. Both share Family H: the plan author trusted an abstraction (a prose claim that "the user needs a WARNING here", a line-number pin) over the real thing (the extract surface that already carries the signal, the signature substring that uniquely identifies the call).

**Shape trigger (when to suspect this family):**
- For (a): you are classifying a per-row or aggregate WARNING site, or a plan proposes adding/maintaining a WARNING. Ask: "Is this WARNING announcing a *project/processing* problem, or is it announcing a *data issue* / *methodology decision* the extract already surfaces (per-row review cell, `CryptoReviewEntry` row, A&M count)? If the extract already carries the signal, the WARNING is a duplicate and belongs at INFO."
- For (b): you are writing or reviewing a plan task that says "demote the WARNING at `foo.py:378`" or "grep `foo.py:378` for the substring". Ask: "Is the step pinned to a LINE NUMBER or to a SIGNATURE SUBSTRING? If a line number, what happens if 125 lines are inserted above it during this session? Is there a substring (the WARNING's format string literal, a unique variable name) that uniquely identifies the call regardless of line drift?"

**General form:**
1. **Console vs extract:** Classify every console WARNING by tracing its information to the extract. If the same information reaches the user via a per-row review cell (HAS_EXCEL_SURFACE), an explicit `CryptoReviewEntry` row in Crypto Supplementary, or an A&M count suffix (both EXTRACT_SURFACED), the WARNING is a duplicate and demotes to aggregate INFO. Reserve WARNING for DEVELOPER_ACTIONABLE sites (data loss or anomaly with NO extract surface). This is the rule #7 four-class taxonomy (EXPECTED_BEHAVIOR / HAS_EXCEL_SURFACE / EXTRACT_SURFACED / DEVELOPER_ACTIONABLE).
2. **Pin to a substring, not a line number:** When a plan task must locate an emission for demotion or grep verification, pin the locator to a stable SIGNATURE SUBSTRING (the `logger.warning(...)` format-string literal, a unique local variable, or a function name) - NEVER to a bare `file:line`. The implementation step should read the file, find the substring, and demote/grep THAT call. Add a "Validation Command" that re-greps for the substring at WARNING and asserts zero hits, so a drifted no-op is caught mechanically.

**Required behavior:**
1. When classifying a WARNING site, run the rule #7 trace (per-row entry schema -> rendered cell; or pipeline adds `CryptoReviewEntry` rows / A&M count) before deciding the level. Demote to aggregate INFO whenever the extract carries the signal; keep WARNING only for no-surface sites.
2. When writing a plan task that demotes or greps an emission, pin the locator to a signature substring, not a line number. If a line number is given as a cross-reference, also record the substring so the implementer can re-find the site after drift.
3. Every "demote WARNING to INFO" plan task must include a post-condition grep that counts the substring at `logger.warning` in the affected module(s) and asserts zero. A non-zero count after the plan ships means a demotion fell through (drift, missed branch, or wrong site) and the task is not done.

**What happened (2026-07-25 `2026-07-25-relocate-crypto-warnings-to-extract`):** The predecessor plan (`2026-07-24-silence-expected-and-excel-surfaced-warnings.md`) demoted the *non-taxable* pool-exhausted sibling (`crypto_fifo/matching.py:111`) to INFO, but the *taxable* pool-exhausted aggregate at `fifo_helpers.py` was MISSED. The predecessor task had pinned the taxable demotion to a line number (`fifo_helpers.py:378`); across the predecessor session the taxable aggregate drifted from line 378 to line 503 as code was inserted above it, and the demotion task fell through - it pointed at stale coordinates and no-oped. When the operator ran the predecessor plan against real data, 11 console WARNINGs survived, one of them the drifted W4 taxable aggregate. The follow-up plan re-located the site by its signature substring and demoted it, and codified the EXTRACT_SURFACED class + this lesson. The lesson's two parts are inseparable: (a) explains WHY the W4 aggregate (and W1/W2/W3/W5/W6/W7/W9/W10) should be INFO not WARNING (the extract surfaces them), and (b) explains WHY the predecessor missed W4 specifically (line-number pin drifted 378->503).

**Distinguishing from lesson #69 (caplog sibling sweep for WARNING->DEBUG):** #69 is the TEST-SIDE rule: when a per-row WARNING becomes DEBUG, every `caplog.at_level(WARNING)` assertion on the substring flips RED and must be rewritten. This lesson's part (b) is the PLAN-SIDE rule: when a demotion task is pinned to a line number, the locator drifts and the demotion no-ops. Both share Family H (verify the real thing - the caplog window / the substring, not the abstraction - the captured-level claim / the line number), but the failure mode and the fix differ: #69 rewrites the caplog window; this lesson rewrites the plan locator from line-number to substring.

**Distinguishing from lesson #47 (rename requires multi-pattern grep across ALL tests):** #47 is about grepping ALL tests when a RENAME touches scattered references. This lesson is about pinning a DEMOTION/GREP locator to a stable substring so it survives line drift. #47 widens the grep SCOPE; this lesson changes the grep LOCATOR TYPE (substring vs line number). Both are Family H.

**Distinguishing from lesson #70 (doc-family prose sweep for logging-level changes):** #70 is the DOCS-SIDE rule: when a logging level changes, sweep docs for the level phrase. This lesson's part (b) is the PLAN-SIDE rule: pin the locator to a substring. They are complementary (docs prose + plan locator) but distinct failure modes.

**Witness (2026-07-26 `2026-07-25-relocate-crypto-warnings-to-extract` review r2, post-r1-fix commit b9ddb02):** r1's address-review corrected a stale pattern-A aggregate line ref in `project-guidelines.md` rule #7 from `:939` to the right value, but r1's OWN concurrent L2 edit (same commit) shifted the emit 939->943, so the freshly-corrected line was stale again the moment r1 landed; r2's fresh panel re-flagged it. The fix chosen was again line-correction rather than dropping the locator or pinning to the signature substring (`logger.info(` for the koinly-tracking summary continuation arg). Reinforces part (b): a line-number locator is a value that goes stale the moment ANY edit above the site shifts line numbers - including an edit in the SAME commit. Pin to the substring or drop the line; do not re-correct the line per round.

**Witness (2026-07-26 `2026-07-25-relocate-crypto-warnings-to-extract` review r3, STRUCTURAL M2-r3):** r1 and r2 each "fixed" a stale `file:line` ref in rule #7 by re-correcting the line number, and each freshly-corrected line was stale again the next round. The r3 review diagnosed this as systemic: rule #7's lookup-table Site column and prose were SATURATED with ~14 bare `file:line` citations, so the lesson's OWN canonical home was the densest violator of part (b). The root-cause fix (r3 M2-r3, STRUCTURAL) converted rule #7's Site column and prose to signature/substring citations (file + containing function + the `logger.info/warning(...)` format-string substring), dropping every bare line number; this also corrected a non-existent `crypto/_emitters.py` path (actual: `crypto_fifo/_emitters.py`) that the line-pinned prose had carried. Operationalizes part (b) on the lesson's own codification: a rule that pins to line numbers is itself a violator of the rule, and the durable fix is to convert the locator type, not to re-correct the line per round.

**Witness (2026-07-26 `2026-07-25-relocate-crypto-warnings-to-extract` review r4, L1-r4):** r3's structural conversion reached the project guidelines but stopped there; the SAME anti-pattern persisted in 12 bare `matching.py:NN` citations inside `fifo_helpers.py` SOURCE COMMENTS (Args docstrings, outer declaration comments, post-loop block comments across 4 emit sites x 3 occurrences each). The r4 review surfaced these as the last codified SOURCE-COMMENT violators of part (b) in the production tree (production-DOC violators in `crypto_implementation_guidelines.md` remained and were caught in r5; see r5 witness). Converting them to function+substring citations exposed a SECOND failure mode beyond staleness: one `:175` pointer was cited for the deferred-acquisition branch but actually pointed at the `if is_epoch_acq:` branch (a WRONG-BRANCH pointer, not a drifted-line one), and a `:250` pointer was cited for the negative-consumption guard whose code now sits at line 306 (pure stale drift). Extends part (b): a bare `file:line` can be wrong in two independent ways - the line drifted (stale) or it was the wrong branch from the start - and only a signature/substring citation makes either detectable on review.

**Witness (2026-07-26 `2026-07-25-relocate-crypto-warnings-to-extract` review r5, M2-r5 + L1-r4 narrowing):** r4's structural conversion reached the source comments but again STOPPED at the file boundary: the SIBLING production doc `crypto_implementation_guidelines.md` still carried 6 bare `file:line` citations (`matching.py:290`, `fifo_helpers.py:378`, `fee_filter.py:643/422/554/434`). r4's L1-r4 witness had claimed "the last codified violators in the production tree" when it meant "last SOURCE-COMMENT violators"; the production-DOC violators were outside r4's source-file sweep. r5 converted all 6 to signature/substring citations and narrowed the L1-r4 wording to "last codified SOURCE-COMMENT violator" with this forward reference. Two extensions of part (b): (1) a "comprehensive sweep" claim is itself an abstraction over the file set the sweep actually visited - r4's 8-file sweep covered `src/`-adjacent files but skipped the sibling doc-family file, and the witness repeated the abstraction; (2) a witness's scope claim must be as precise as the rule it serves. Saying "last violator in the production tree" when the verified scope is "last source-comment violator" is the SAME over-claim part (b) polices (line-number vs substring) applied one level up: the scope WORD is an abstraction over the concrete file set swept, and it drifts the moment a file outside that set exists. State the verified scope verbatim; never generalize a witness's scope beyond what the round actually inspected.

**Witness (2026-07-30 `2026-07-25-relocate-crypto-warnings-to-extract` review r6, M1/M2-r6):** r5's sweep stopped at the `src/tax_reporting/application/` boundary the plan's validation grep scans; the SIBLING domain-layer file `src/tax_reporting/domain/crypto_fifo.py` (NOT in the plan's Files lists, NOT in the diff, NOT reached by the validation grep) carried the same stale Pattern-F "aggregate WARNING" field comment r5 swept in `crypto/fifo_helpers.py` plus 4 bare `matching.py:NN` source-comment citations of the same Family-(b) anti-pattern. This is the SAME scope-boundary over-claim r5's witness already polices ("a 'comprehensive sweep' claim is an abstraction over the file set swept"), recursing one boundary further: each round's sweep has a boundary defined by where the validation grep or the round's file set ends, and the next fresh adversarial pass finds the file just outside it. No new rule; this witness exists only to record that the recursion is unbounded without a scope statement that names every causally-related layer, and that a validation grep scoped to one package cannot certify layers the grep never visits.

**Witness (2026-07-30 `2026-07-25-relocate-crypto-warnings-to-extract` review r7, convergence):** the r6 witness stated the recursion is "unbounded without a scope statement that names every causally-related layer." r7 falsifies the unqualified "unbounded": when the panel is primed to scan the FULL tree (application + domain + infrastructure + docs + tests) rather than a per-round file set, the recursion reached its last layer (tests) and converged at ZERO Medium - only 1 stale test-class docstring (L1-r7) and 5 out-of-scope soft bare-`file:line` production-comment cross-refs (L2-r7) remained. The recursion's depth is FINITE and equal to the number of distinct causally-related layers (here source -> docs -> domain -> tests); it terminates once the scope covers every layer rather than ending where a validation grep's package ends. Qualifies (does not duplicate) r6: r6's "unbounded" is correct for any sweep scoped to a subset of layers; r7 shows the subset qualifier was the load-bearing condition. Operational rule unchanged - name every causally-related layer in the scope statement - but the expected outcome is convergence, not infinite regress, once all layers are in scope.

**Witness (2026-07-30 `2026-07-25-relocate-crypto-warnings-to-extract` review r8, stability confirmation):** r8 is the SECOND consecutive zero-Medium round, confirming r7's convergence was stable rather than a single-round fluke - exactly the signal the two-consecutive-clear-rounds exit rule exists to catch. No new layer surfaced; the only residual findings were 4 Lows, all tests-layer docstring drift (one carried from r7, three newly noted), none touching the demotion logic or locator-citation rule this lesson polices. Reinforces r7 without duplicating it: the convergence mechanism is unchanged, and the residual debt is non-blocking prose in the last layer the sweep reached.

**See also:** `docs/maintenance/project-guidelines.md` rule #7 (the four-class taxonomy - EXPECTED_BEHAVIOR / HAS_EXCEL_SURFACE / EXTRACT_SURFACED / DEVELOPER_ACTIONABLE - and the W1-W10 pattern table where this principle is codified), `docs/history/plans/2026-07-25-relocate-crypto-warnings-to-extract.md` (the plan that added the EXTRACT_SURFACED class and re-located the drifted W4 site), `docs/history/plans/completed/2026-07-24-silence-expected-and-excel-surfaced-warnings.md` (the predecessor plan whose line-number-pinned W4 task drifted 378->503 and no-oped), `src/tax_reporting/application/crypto/fifo_helpers.py` (W4 taxable aggregate, the drifted site), lesson #69 (caplog sibling sweep - test-side mirror), lesson #47 (rename multi-pattern grep - same family, scope-vs-locator distinction), lesson #70 (doc-family prose sweep - docs-side mirror), `coding_guidelines.md` Family D (single source of truth) / Family E (temporal ordering) / Family H (verify the real thing).


## 77. Operator Mapping Field Semantics (`service_start_date` / `valid_from`)

**Principle:** Family D (Single source of truth)


See `~/Projects/.ai-playbook/agent_workflow_guidelines.md` #3 for the generic field-semantics lesson.
Repo-specific constraint: `valid_from` is audit-only (when the mapping was verified from source docs). `service_start_date` is for transaction matching (when the platform started offering this service). Never use `valid_from` as a matching gate. When both are known, `service_start_date <= valid_from`.

**See also (principle cluster D):** #96 (same family, distinct angle: field-semantics determine strategy (#96) vs field-identity (playbook lesson "A Locally-Archived Official Source Outranks a Conflicting External Secondary Source")).

## 78. AT Guidance May Cite Pre-Amendment Paragraph Numbers

**Principle:** Family H (Verify the real thing, not the abstraction)


See `docs/maintenance/project-guidelines.md` #3 for the full rule.
Concrete instance: AT folheto 2026-01-12 (published after Lei n.º 31/2024) still cited CIRS art. 43 as "(n.º 6)(g)" and "(n.º 7)"; the old numbers before the June 2024 amendment renumbered them to n.8(g) and n.9 respectively. The stale numbers had silently propagated into `sources.md` and `platform-divergences.md`. The discrepancy was only caught by cross-checking the folheto against the consolidated CIRS PDF (which shows inline annotations like `(Anterior n.º 7 - Lei n.º 31/2024)`).

Prevention: whenever consulting AT guidance that cites a CIRS paragraph number, search for that legal text in the consolidated CIRS PDF and confirm the current paragraph number before recording citations.

---

## 79. Decision Points TOML Missing Must Raise `ConfigurationError`, Not Bare `FileNotFoundError`

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

**See also (principle cluster B):** #77 (same family, distinct angle: write-side (catch specific not broad, #77) vs escape-side (convert the specific type so it evades the broad handler, playbook lesson "Verify Staged Diff Matches Implementation Before Finalizing")).

## 80. Defensive Warnings Must Also Record Items in the Failure-Tracking Structure

**Principle:** Family G (Data-loss observability)


When a defensive branch fires because a row cannot be fully processed (e.g. "both sides loan-affected"), always append the untracked item to `parse_failures_by_asset`; do not rely on a `logger.warning` alone. A logged warning is invisible to the workbook consumer; only items recorded in the failure-tracking structure surface as `review_required` flags in the output.

Example: in `_classify_th_row`, when both the sent and received currencies are loan-affected, the non-principal side was silently ignored. Fix: `parse_failures_by_asset.setdefault(untracked_currency, []).append(row_index)` in all four affected branches (sell, crypto_withdrawal, buy, crypto_deposit).

General principle: "Unmatched items must never be silently discarded" (see CLAUDE.md §1) applies to defensive-path items too; logging is necessary but insufficient when a failure-tracking collection exists.

**See also (principle cluster G):** playbook lesson "Recalculate Validation Metrics from Aggregated Values" (same family, distinct angle: structure-recording (playbook lesson "Update Documentation When Code Structure Changes") vs baseline log-it (playbook lesson "Recalculate Validation Metrics from Aggregated Values")).

## 81. Two-Level Review Flags: Separate Platform-Level from Row-Level

**Principle:** Family C (Representation: sentinel vs None vs exception)


When a dataclass field serves two semantically different purposes, introduce a second explicitly named field rather than overloading the first.

Example: `OperatorOrigin.review_required` was used for both (a) per-transaction issues (temporal validity failure, unknown platform) that should color transaction rows, and (b) platform-level concerns (e.g. account-region ambiguity) that should only appear on a summary tab. Adding `platform_review_required: bool = False` as a distinct field removed the conflation cleanly. See CRG-016.

**See also (principle cluster C):** playbook lesson "Calibrate Exception-Handling Strategy to the Cost of Silent Failure When Reusing a Helper Pattern" (same family, distinct angle: platform-vs-row flags (playbook lesson "Fail Fast for Data-Completeness Operations") vs independent-validation-vs-entry flags (playbook lesson "Calibrate Exception-Handling Strategy to the Cost of Silent Failure When Reusing a Helper Pattern", cites playbook lesson "Fail Fast for Data-Completeness Operations")).

## 82. Deduplication Key Must Capture Minimum Sufficient Identity

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

## 83. Fiscal Year Filter in FIFO Pipeline Must Apply to Disposals Only, Post-FIFO

**Principle:** Family G (Data-loss observability)


When filtering FIFO pipeline output to the reporting fiscal year, filter *only disposal /
realization records*, never the acquisition records. Prior-year acquisitions must remain
in the FIFO pool so cost-basis carry-over is correct; filtering them by year would produce
incorrect zero-cost gains for multi-year holds.

Correct position: filter `AssetFifoResult.realizations` after the FIFO engine produces
them, before converting to `CryptoCapitalGainEntry`. Do not pre-filter `acquisitions` or
`consumptions` inputs to the FIFO engine.

## 84. `TaxJurisdictionConfig` Lives in `domain/jurisdiction.py`

**Principle:** Family F (Layering / dependency direction)


`TaxJurisdictionConfig` was moved from `infrastructure/config.py` to `domain/jurisdiction.py`. `config.py` re-exports it for backward compat. All new code should import from `domain.jurisdiction` directly; infrastructure imports are for backward compat only.

## 85. Run-Determining Parameters Belong in the Output Artifact, Not in Logs

**Principle:** Family D (Single source of truth)


When a pipeline run produces different results depending on dynamically-discovered inputs (e.g. which assets are loan-affected, which platforms are active, which years are in scope), expose those inputs in the output report itself, as a dedicated worksheet section, a named range, or a metadata tab, rather than relegating them to log lines or ephemeral sidecar files.

Logs are consumed during a run and discarded; a sibling file adds surface area and may not be opened. The workbook is the primary artifact reviewed by the user. Embedding the run scope there lets the reviewer verify assumptions without cross-referencing external files, and makes the report self-documenting for future audits.

Example: `CryptoTaxReport.fifo_rebuild_assets` (which assets were rebuilt from Transaction History) is surfaced in the "FIFO Rebuild Scope" section of the Loan Activity tab, not just logged at INFO.

## 86. All-or-Nothing File Set Validation for External Exports

**Principle:** Family G (Data-loss observability)


When a subsystem requires a complete set of N files from an external tool export (e.g. Koinly's capital gains, income, and transaction history), validate with all-or-nothing semantics:

- **None present** → skip gracefully (no-op mode; the external data source is simply not configured for this run).
- **Partial set present (1 of N or 2 of N)** → raise `FileProcessingError` with an explicit list of missing files and export instructions. Partial presence is worse than none: it silently produces an incomplete report that looks valid (e.g. rewards disappear but no error is raised).
- **All N present** → proceed normally.

The silent-data-loss case that triggered this lesson: `income_file = None` was handled as `reward_entries = []` with no warning or error, so Wirex EUR lending interest vanished from the Crypto Rewards tab without any indication. The user attributed the disappearance to a code change, but the actual cause was a missing export file. Fail-fast on partial sets eliminates this class of confusion.

**See also (principle cluster G):** playbook lesson "Module and Class Size Limits" (same family, distinct angle: total-failure fail-fast (playbook lesson "Module and Class Size Limits") vs partial-file-set fail-fast (#89)).

## 87. Decision Point Flags Require TaxJurisdictionConfig Field

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

**See also (principle cluster D):** playbook lesson "Monkeypatch Module-Level Path Constants in Unit Tests", playbook lesson "Adding Excel Columns Requires Constant Updates", playbook lesson "Reconcile Plan Pseudocode Against Plan Tests and Design Invariants Before GREEN" (same family, distinct angle: multi-authority synchronization; the third is the test-enforced variant of the first's manual grep.).

## 88. Cross-Report Validation for Multi-Report Systems

**Principle:** Family G (Data-loss observability)


When investigating systems that process data from multiple source reports (e.g., Koinly Transaction History, Capital Gains Report, Other Gains Report), verify classifications match across ALL reports before concluding correctness:

1. **Identify all source reports:** List every CSV/report the system processes
2. **Cross-reference classifications:** If one report shows Type="Loss" and another shows Gain/Loss=positive, investigate which report drives the final output
3. **Verify final output reflects the correct classification:** The Excel/final output must match the economically correct classification, not just the mechanically calculated one
4. **Document which report is authoritative:** When source reports disagree, state which report's classification is correct and why

**Example:** Koinly's Other Gains Report correctly classified futures liquidations as "Loss" with negative amounts, while the Capital Gains Report calculated positive gains based on collateral proceeds. The system only processes Capital Gains Report, so losses appeared as gains in the final output. Cross-report validation would have caught this discrepancy.

**See also:** Lesson #94 (Authoritative Source Overrides Must Precede Aggregation)

## 89. Cross-Module Function Dependencies Require Complete Imports

**Principle:** Family H (Verify the real thing, not the abstraction)


When adding a function in one module that calls a function from another module, verify the import is complete. Unit tests that don't exercise the full code path (e.g., only test helper functions but not the file-discovery wrapper) can miss import errors that would cause runtime `NameError`.

**Verification:** After adding cross-module function calls, run `uv run python -c "from module import function"` to verify imports resolve at import time, not just at call time.

**Example:** `_find_and_parse_other_gains_file()` in `koinly_parser.py` called `_find_report_path()` from `crypto_reporting.py` without importing it. Unit tests for the helper functions (`_extract_ogr_gain_loss`, `_parse_other_gains_row`) passed because they didn't call the file-discovery function. A full import check would have revealed the missing dependency before runtime.

## 90. Authoritative Source Overrides Must Precede Aggregation

**Principle:** Family D (Single source of truth)


When applying overrides from an authoritative source (e.g., OGR) to calculated data (e.g., CG), the override must happen BEFORE aggregation when working with lot-level entries.

**Why this matters:** CG rows are individual FIFO lots that get summed in aggregation. The authoritative source (OGR) contains the correct total gain/loss for the disposal event. Overriding after aggregation would lose the lot-level trail and make reconciliation impossible.

**Pattern:**
1. Parse calculated source (CG): produces individual lot entries
2. Parse authoritative source (OGR): produces event-level totals
3. Match and override lot entries with authoritative values
4. Aggregate overridden lots: preserves lot-level trail in output

**Example:** In `crypto_reporting.py`, `_apply_ogr_overrides()` is called after `_parse_capital_gains_file` but BEFORE `_aggregate_capital_entries()`. This ensures that when OGR reports an authoritative per-disposal loss, each individual FIFO lot for that disposal is overridden with that authoritative value before being summed. If aggregation happened first, the lot-level detail would be lost and the override could not be traced back to specific lots.

**See also:** playbook lesson "Trace the Fixture When Plan Pseudocode Compares Same-Unit Fields by Name" (Cross-Report Validation), AGENTS.md constraint on OGR override timing

**See also (principle cluster D):** playbook lesson "Trace ALL Branches of a Multi-Branch Conditional When Implementing a Tiered Rule", playbook lesson "Grep Across ALL Test Files for Stale Assertions When a Task Changes Data Flow Semantics" (same family, distinct angle: OGR/CG authority -- override ordering (#94) vs split by aspect (playbook lesson "Trace ALL Branches of a Multi-Branch Conditional When Implementing a Tiered Rule") vs aggregate-then-validate (playbook lesson "Grep Across ALL Test Files for Stale Assertions When a Task Changes Data Flow Semantics")).

## 91. Duplicate Key Handling in Index Building

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

**See also:** playbook lesson "Add a Count-Matched-Items-Per-Event Safety Check When Matching by Non-Unique Keys" (TDD for Bug Fixes), playbook lesson "Trace ALL Branches of a Multi-Branch Conditional When Implementing a Tiered Rule" (OGR Validation vs Replacement Design)

## 92. OGR Directional Authority vs Wholesale Replacement (Completed)

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

**See also:** Lesson #94 (Authoritative Source Overrides Timing), playbook lesson "Calibrate Exception-Handling Strategy to the Cost of Silent Failure When Reusing a Helper Pattern" (Independent Validation Fields), CRG-017 in crypto_reporting_guidelines.md

**See also (principle cluster D):** playbook lesson "Grep Across ALL Test Files for Stale Assertions When a Task Changes Data Flow Semantics" (same family, distinct angle: OGR/CG authority -- override ordering (#94) vs split by aspect (playbook lesson "Trace ALL Branches of a Multi-Branch Conditional When Implementing a Tiered Rule") vs aggregate-then-validate (playbook lesson "Grep Across ALL Test Files for Stale Assertions When a Task Changes Data Flow Semantics")).

## 93. Probe the Canonical URL Before Assuming an Official Source Is Unavailable

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

**See also:** `docs/maintenance/project-guidelines.md` #1 (external source archive provenance and freshness), CLAUDE.md source-archival rules, playbook lesson "Reconcile Plan Pseudocode Against Plan Tests and Design Invariants Before GREEN" (verification for canonical source synchronization).

---

## 94. Trace Each Affected OGR Row to Its Originating TH Type Before Designing a Type-Filtered Scanner

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

**See also:** Lesson #93 (data trace verification), playbook lesson "Discriminating Tests: Assert Properties That FAIL Under the Wrong Implementation" (trace fixture when comparing same-unit fields by name), CLAUDE.md §3 Repository Constraints (derivatives separation).

**See also (principle cluster H):** playbook lesson "Verification Guards That Read a Manifest File Must Fail Closed When the Manifest Is Absent" (same family, distinct angle: general plan-claim rule (playbook lesson "Verification Guards That Read a Manifest File Must Fail Closed When the Manifest Is Absent") and its two specific witnesses.).

## 95. Audit for Shared Identifiers Across Reports When Separating a Previously-Merged Tax Category

**Principle:** Family D (Single source of truth)


When introducing a separation between two tax categories that previously shared a single pipeline (e.g., splitting a unified crypto-gains flow into spot vs derivatives), audit whether the same disposal event appears in **both** source reports that feed the separated paths. Without an explicit deduplication step removing the now-derivatives-classified items from the spot path, those items are double-counted: once in the new derivatives aggregate, once in the legacy spot aggregate. The trigger for the audit is the **introduction of the separation itself**, not a later data-quality or cross-report validation check.

**Why this happens:** Koinly (and similar exporters) emit one row per disposal event in each report that references it. A derivatives Futures-fee disposal appears both as an OGR `Loss` row (because it has no cost basis, so Koinly routes it to Other Gains) and as a CG lot (because Koinly also records it as a disposal of the fee asset against its acquisition lot). Before the separation, only the CG path was read, so the duplication was invisible. The moment a plan introduces a derivatives path that reads OGR, both paths light up for the same disposal, and the spot CG total silently inflates.

**Required behavior:**
1. When a plan introduces a new classification path that consumes a previously-unused source report (OGR, rewards, etc.), enumerate every other report the existing pipeline already reads (CG, TH).
2. For each disposal event in the new report, check whether the same `(date, asset, wallet, amount)` (or whatever identity tuple applies) also appears in the existing reports.
3. If overlap exists, write an explicit dedup step in the plan that removes the overlapping items from the legacy path. Do not rely on the new path's downstream classifier to "handle" the overlap; the legacy path aggregates independently.
4. Add a reconciliation test that asserts the union of (spot aggregate, derivatives aggregate) matches the pre-separation total. A drift in this union after the separation is the symptom of a missing dedup step.

**Distinguishing from playbook lesson "Trace the Fixture When Plan Pseudocode Compares Same-Unit Fields by Name" (Cross-Report Validation):** playbook lesson "Trace the Fixture When Plan Pseudocode Compares Same-Unit Fields by Name" catches **data corruption** where one report contradicts another (e.g., OGR says Loss while CG says Gain on the same disposal). This lesson catches **structural double-counting** where both reports agree and are individually correct, but the pipeline reads both without dedup. the failure mode for the playbook lesson above is wrong totals; the failure mode here is inflated totals with no inconsistency between reports.

**Anti-pattern:** A separation plan that says "OGR rows of Type Loss route to `derivatives_entries`; CG rows remain in spot" without checking whether the same disposal is present in both. The spot CG total silently includes the derivatives-classified lots, the derivatives total includes the OGR Loss, and the sum is greater than the pre-separation total. The error surfaces only at tax-filing time when the IRS-ready total is too high.

**Example:** The 2026-06-13 derivatives-separation plan split OGR into derivatives_entries vs spot but did not dedup the corresponding CG lots from the spot table. ByBit USDT Futures-fee and Funding-fee disposals on 2025-01-13 and 2025-01-24 appeared in both: as OGR Loss rows (routed to derivatives) and as CG lots (left in spot). The fix required the entire 2026-06-14 derivatives-th-label-cg-dedup follow-up plan to scan TH for `crypto_withdrawal` events labeled Funding fee / Futures fee / Realized gain, match them against CG lots by `(date, asset, wallet, amount)`, and remove the matched lots from the spot index before the spot/derivatives classifier runs. A 5-minute audit at 2026-06-13 plan time ("does any disposal appear in both OGR and CG?") would have caught the gap and avoided the follow-up plan entirely. See `docs/history/plans/2026-06-14-derivatives-th-label-cg-dedup.md`.

**See also:** Lesson #87 (deduplication key identity), playbook lesson "Trace the Fixture When Plan Pseudocode Compares Same-Unit Fields by Name" (cross-report validation), playbook lesson "Static Guards Must Cover Code Paths Skipped in CI (No Runtime Backstop)" (trace OGR→TH source Type), CLAUDE.md §3 Repository Constraints (derivatives separation), PT-C-034 in `docs/maintenance/crypto_rules.md`.

## 96. Reuse the Parsed Value Inside the Existing Try Block When Extracting a Second Derived Value

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

**Distinguishing from playbook lesson "Field Aggregation Strategy Depends on Semantics" (try/finally resource-cleanup scope):** playbook lesson "Field Aggregation Strategy Depends on Semantics" is about ensuring all raising operations are inside a try/finally so cleanup runs. This lesson is about not re-invoking a fallible operation outside a try/except that was set up to catch its first invocation. Both are error-scope guards but address different failure modes: The playbook lesson above prevents leaked resources; this one prevents uncaught exceptions that bypass row-level error handling.

**Example:** Task 3 of the 2026-06-14 derivatives-th-label-cg-dedup plan added `timestamp_str` to `ParsedTxRow` and `disposal_timestamp` to `CryptoCapitalGainEntry`. Both `_classify_rows_for_loan_affected_assets` (parsing.py) and `_parse_capital_gains_file` (crypto_reporting.py) already parsed the date inside a try block to compute `date_str`/`disposal_date`. The implementation captured `parsed_dt`/`disposal_dt` first, then derived both strings from it inside the same block, rather than re-calling `parse_koinly_datetime` outside. See the implementation log (local).

## 97. Internal Placeholder Sentinels From Resolution Functions Must Not Leak to User-Facing Output Fields

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

**See also (principle cluster C):** playbook lesson "Do Not Explicitly Omit Plan-Prescribed Behavior Without Amending the Plan First", playbook lesson "When Migrating a Test Off a Real Fixture to Synthetic Data, Narrow Assertions to the Behavior Under Test" (same family, distinct angle: sentinel string leak (playbook lesson "A Validation Command That Scans a Shared Parent Directory to Enforce a NEW Convention Will False-Fail on Pre-Existing Legacy Entries") vs `None`-value interpolation (playbook lesson "Do Not Explicitly Omit Plan-Prescribed Behavior Without Amending the Plan First") vs test-expectation `None`/`""` (playbook lesson "When Migrating a Test Off a Real Fixture to Synthetic Data, Narrow Assertions to the Behavior Under Test")).

## 98. Reuse the Production Validator When a Test Asserts Against a Domain-Validity Predicate

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

**Distinguishing from playbook lesson "Do Not `git stash` for Baseline Comparisons in the docs-branch State" (Structural Identification for Excel Output Tests):** playbook lesson "Do Not `git stash` for Baseline Comparisons in the docs-branch State" is about identifying which cells to inspect via structural properties (column population, font) rather than hardcoded value exclusions; it concerns test data selection, not validity predicates. This lesson concerns the validity check applied to the values once selected: even when a test correctly identifies rows structurally, it may still duplicate a domain list to validate the cell's value, which is the drift risk this rule addresses. The two compose: identify rows structurally (per the playbook lesson above), then validate values by reusing the production predicate (per this lesson).

**General form:** Whenever the test could be written as `value in SOME_SET_DEFINED_IN_PRODUCTION` or `value matches PRODUCTION_REGEX`, replace the inline duplicate with an import of the production function/constant. The test asserts the contract ("value is valid per the domain"), and the production code is the single source of truth for what "valid" means.

**Example:** Task 5 of the 2026-06-15 derivatives-pnl-columns plan added `test_derivatives_rows_operator_country_is_valid_or_unknown`, which asserts every derivatives row's `operator_country` is either a valid Tabela X country code or the literal `"UNKNOWN"` sentinel. The test imports `_is_valid_tabela_x_country` from `tax_reporting.application.crypto.classification`, the same validator the pipeline uses to validate reportable country codes, rather than re-listing the ISO 3166-1 alpha-2 codes inline. A future CIRS amendment that adds a country to the production list propagates to the test automatically. See the implementation log (local) Decision 3.

**See also:** playbook lesson "Do Not `git stash` for Baseline Comparisons in the docs-branch State" (structural identification for test data selection), CLAUDE.md "Code Quality" (no duplicated constants), `coding_guidelines.md` (single source of truth for domain predicates).

## 99. Check Prior Same-Session Commits Before Reporting a Verification-Time Scope Violation

**Principle:** Family H (Verify the real thing, not the abstraction)


When a verification-only task (e.g., a regression sweep, a "diff scope" check, a Phase 2 final validation) asserts that the cumulative diff should contain a specific file but `git diff <base>..HEAD -- <file>` shows the file is NOT in the diff, first check whether a prior same-session commit already applied the planned change to that file before reporting a scope violation.

**Why this matters:** Execute-plan sessions commit after each completed task. When a plan lists a source file as expected-modified and an earlier task's commit already included the edit (because the edit was naturally bundled with that task's primary change), the file will NOT appear in a later task's incremental diff even though the work was done. Reporting this as a "scope violation" or "missing change" is a false positive; the change exists in the cumulative history, just not in the latest task's incremental slice.

**Required behavior:**
1. When a verification task's "expected files in diff" list does not match `git diff --name-only <base>..HEAD`, run `git log --oneline <base>..HEAD -- <missing-file>` to check whether an earlier commit in the session already touched it.
2. If yes, confirm the change matches the plan's intent by reading the file at HEAD (`git show HEAD:<file>` or Read tool), then mark the verification item as satisfied; the work landed earlier, just not in the most recent task's commit.
3. Only report a scope violation when the file is absent from the entire `<base>..HEAD` range AND the planned change is genuinely missing from the working tree.

**Distinguishing from playbook lesson "Verification Guards That Read a Manifest File Must Fail Closed When the Manifest Is Absent" (plan-time claims):** playbook lesson "Verification Guards That Read a Manifest File Must Fail Closed When the Manifest Is Absent" covers verifying claims about production code at plan-authoring time. This lesson covers verifying scope at verification/commit time, when the diff inspection happens after multiple commits. The trigger is a mismatch between an expected-files list and an observed cumulative diff, not a plan-authoring claim.

**General form:** Verification tasks that inspect `git diff <base>..HEAD` must interpret "file X is missing from the diff" as "file X was not touched in this session", which requires checking the per-commit history, not just the aggregate diff stat. A file absent from the cumulative diff is genuinely missing; a file absent from the latest task's incremental commit may simply have landed earlier.

**Example:** Task 6 of the 2026-06-15 derivatives-pnl-columns plan listed `docs/maintenance/crypto_rules.md` as an expected file in the diff scope check. The diff `d2eda71..HEAD` did not show `crypto_rules.md`. Investigation showed the prior same-session commit `6083cf1 docs(crypto): extend PT-C-031 with Anexo G Quadro 13 filing routing for derivatives` had already extended PT-C-031 with the Anexo G Quadro 13 routing the plan depended on, so no further `crypto_rules.md` edit was required by this plan. The verification item was satisfied by the earlier commit, not violated. See the implementation log (local) Decision: crypto_rules.md.

**See also:** playbook lesson "Verification Guards That Read a Manifest File Must Fail Closed When the Manifest Is Absent" (verify plan-time claims about production code), `execute-plan` skill (Phase 2 final validation), CLAUDE.md §4 Agent Workflow Rules.

**See also (principle cluster H):** playbook lesson "Independent Validation Fields vs Entry-Level Review Flags", playbook lesson "Use Type Parameterization (TypeVar) in Shared Generic Primitives to Preserve Subclass Field Visibility Under Static Analysis", playbook lesson "Type Heterogeneous Validated Kwargs Dicts as `dict[str, Any]` to Feed `**`-Unpack Into a Dataclass Constructor Under basedpyright", playbook lesson "A Refactor Plan Clause That Instructs a Net-New Behavior Addition Conflicts With the Same Plan's Byte-Identical Non-Regression Criterion" (same family, distinct angle: the git/docs-state verification cluster.).

## 100. Branch on the Discriminator When Synthesising a Reason for a Multi-Cause Flag

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

**Distinguishing from playbook lesson "A Validation Command That Scans a Shared Parent Directory to Enforce a NEW Convention Will False-Fail on Pre-Existing Legacy Entries" (sentinel leak into display fields):** playbook lesson "A Validation Command That Scans a Shared Parent Directory to Enforce a NEW Convention Will False-Fail on Pre-Existing Legacy Entries" is about the VALUE of a field that reaches the display (an internal placeholder must not appear in a user-facing cell). This lesson is about WHICH MESSAGE a consumer synthesises when the same flag has multiple causes; the value is always user-facing by design (a reason string), but the message content must match the actual cause. The playbook lesson above says "do not display the sentinel"; this lesson says "do not collapse multiple causes into one message; branch on the discriminator".

**General form:** Any time a consumer turns a multi-cause boolean into prose, the prose must be selected per-cause using the discriminator the upstream sets. The boolean tells you THAT review is needed; the discriminator tells you WHY; the WHY is what the reviewer needs to read.

**Example:** Finding #1 (Medium) of the 2026-06-16 derivatives-pnl-columns code review r1 found that `_split_ogr_index` in `src/tax_reporting/application/crypto/ogr_handler.py` synthesised an "Unknown platform" message (with wording like `add this platform to resolve_operator_origin() before filing`) whenever `operator_origin.review_required` was True. But `resolve_operator_origin()` sets `review_required=True` for TWO distinct cases: (a) truly-unknown platform (sets `operator_entity="UNKNOWN_OPERATOR_REVIEW_REQUIRED"`), and (b) temporal-validity failure, a known platform whose `service_start_date` postdates the transaction (keeps the real mapped `operator_entity` and sets a specific `review_reason` mentioning the date and service period). The synthesised message misled reviewers for case (b): the platform IS mapped, but the message told them to add it. The fix branches on the `UNKNOWN_OPERATOR_REVIEW_REQUIRED` sentinel: for the truly-unknown case it synthesises the actionable fix-path message; for the temporal-validity case it surfaces `operator_origin.review_reason` verbatim (which carries the specific date and "service period" wording the reviewer needs). The new RED test `test_derivatives_entry_for_known_platform_outside_service_period_carries_temporal_reason` exercises case (b) explicitly and asserts the temporal reason is present while the "Unknown platform" message is absent. See the derivatives-pnl-columns code review r1 (local) Finding #1 and the implementation log (local).

**See also:** playbook lesson "A Validation Command That Scans a Shared Parent Directory to Enforce a NEW Convention Will False-Fail on Pre-Existing Legacy Entries" (internal sentinels must not leak to display fields), playbook lesson "A Mechanical `str.replace`/`sed` Pass Whose Search String Is a Substring of a Larger Token Silently Corrupts at the Wrong Offset" (test names must reflect their coverage scope; the missing temporal-validity test is an instance of that playbook lesson), Lesson #104 (sibling aggregators mirror byte-identical patterns -- distinct sibling-ness unit: aggregators in one module), Lesson #110 (centralized helper across callers with divergent policies -- distinct sibling-ness unit: callers of one helper), CLAUDE.md §1 "Partial or uncertain results must carry an explicit indicator" and "Review flags must include specific actionable explanations, not bare booleans".

## 101. Guard "Take From First Entry" Fields Against Silent Heterogeneity

**Principle:** Family G (Data-loss observability)


Lesson #96 documents the "lookup value fields - take from first entry" aggregation strategy, premised on the assumption that all entries in the group share an identical value for the field. That assumption is a design invariant, not a guaranteed runtime property. When the assumption silently fails (e.g., a future code path lets two group members carry different `annex_hint` / `operation_code` / `legal_category` values for the same disposal group), the renderer or aggregator that takes `entries[0]` will silently pick one value and discard the others, with no log or warning to flag the drift. The output looks correct (it has a value) but is wrong (it has the wrong value).

**Required behavior:**
1. Whenever an aggregator, renderer, or detail-line builder takes `entries[0]` (or `first`) for a field that is ASSUMED constant across the group, add a programmatic heterogeneity guard that emits a `logger.warning` when the assumption is violated.
2. The guard should build the set of distinct values (or distinct tuples, for multi-field constants like `(annex_hint, operation_code, legal_category)`) and warn when `len(distinct) > 1`. Include the count, the distinct values, and which row was actually rendered so a future maintainer can audit.
3. Do NOT raise; the first entry's value is still the best available. The warning makes the drift observable so a reviewer can decide whether the assumption needs strengthening or the data needs correcting.
4. Pair the guard with a RED test that constructs a group with heterogeneous values and asserts the warning fires, plus a negative control asserting no warning fires when values agree.

**Qualification gate (when this rule applies):**
- The field is read from `entries[0]` / `first` rather than aggregated (summed, OR-ed, joined).
- The field's correctness depends on all group members sharing the same value (a design invariant, not enforced by upstream).
- A silent violation would produce user-facing output that looks valid but is wrong.

**Distinguishing from #96 (aggregation strategy per field type):** Lesson #96 catalogs WHICH strategy to use per field type ("lookup value → take first"). This lesson catalogs the GUARD that must accompany the "take first" strategy when the "all members share the value" assumption is a design invariant that could silently fail. #96 says "use this strategy"; this lesson says "when you use the 'take first' strategy for an assumed-constant field, add a heterogeneity guard".

**General form:** Any time production code reads from the first element of a group for a field whose group-wide constancy is an assumption rather than a guarantee, the assumption must be checked at runtime and a warning emitted on violation. Silent assumption drift is worse than a logged warning because the output looks correct.

**Example:** Finding #1 (Medium) of the 2026-06-16 derivatives-pnl-columns code review r1 found that the derivatives-sheet detail-line renderer took `entries[0].annex_hint`, `entries[0].operation_code`, and `entries[0].legal_category` without verifying the other group members agreed. The current fixture set is homogeneous by construction (every group comes from a single disposal event), so the bug is latent. The fix added a guard in `derivatives_sheet.py` that builds `distinct_constant_tuples = {(e.annex_hint, e.operation_code, e.legal_category) for e in entries}` and emits `logger.warning("Derivatives P&L detail-line fields are heterogeneous ...", ...)` when `len(distinct_constant_tuples) > 1`. The RED tests `test_detail_line_warns_when_entries_disagree_on_constant_fields` and `test_detail_line_no_warning_when_entries_agree_on_constant_fields` exercise both branches. See the derivatives-pnl-columns branch review r1 (local) Finding #1 and the implementation log (local) Medium 1.

**See also:** Lesson #96 (field aggregation strategy per field type), playbook lesson "An `lru_cache`-Decorated Function That Reads a Module Global at Call Time Needs an Autouse Fixture That Rewires the Global AND Calls `cache_clear()` in BOTH Setup and Teardown" (branch on discriminator for multi-cause flags), CLAUDE.md §1 "Partial or uncertain results must carry an explicit indicator" and "Data-loss conditions (unmatched items, dropped records) must be logged at warning+".

## 102. Mirror Byte-Identical Aggregation Patterns Across Aggregators in the Same Module

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

**Distinguishing from #96 (aggregation strategy per field type):** Lesson #96 catalogs WHICH strategy to use per field type ("narrative text fields - join unique values with delimiter and deduplicate"). This lesson says: when that strategy is implemented in two aggregators in the same module, the implementations must agree byte-for-byte. #96 says "use the join-dedupe strategy"; this lesson says "use the SAME join-dedupe implementation as the sibling aggregator".

**Distinguishing from #110 (centralized helper across callers with divergent policies):** This lesson and Lesson #110 both govern sibling code, but address different units of sibling-ness with OPPOSITE prescriptions. This lesson is about sibling IMPLEMENTATIONS that should produce the SAME output (two aggregators in one module): they must mirror byte-identical patterns; a divergence silently drops data. #110 is about sibling CALLERS of a centralized seam that have INTENTIONALLY DIVERGENT policies for the same failure kind (one raises, another degrades): each caller's policy arm must be pinned individually; mirroring one caller's policy into another is precisely the bug (it flips a required raise to a silent degrade). This lesson says siblings must be identical; #110 says sibling callers must keep their distinct arms pinned and must NOT be copied wholesale.

**General form:** Sibling aggregators that perform the same operation must use the same implementation. Diverging implementations silently produce inconsistent output. The fix is byte-identical mirroring or extraction to a shared helper.

**Example:** Finding #2 (Medium) of the 2026-06-16 derivatives-pnl-columns code review r1 found that `aggregate_derivatives_entries` in `src/tax_reporting/application/crypto/aggregation.py` set `notes=first.notes` while the sibling `aggregate_capital_entries` (same module, lines 283-287) used the `"; ".join(dict.fromkeys(...)) or ""` pattern. For a group with two members carrying notes "manual annotation A" and "manual annotation B", the derivatives aggregator silently dropped "manual annotation B". The fix replaced `first.notes` with `merged_notes = "; ".join(dict.fromkeys(e.notes for e in group if e.notes)) or ""` (byte-identical to the capital-entries pattern). The RED tests `test_aggregate_derivatives_merges_notes_across_group_members`, `test_aggregate_derivatives_notes_empty_when_no_member_has_notes`, and `test_aggregate_derivatives_notes_deduped_and_order_preserved` exercise the merge, empty-input, and dedupe+ordering cases. See the derivatives-pnl-columns branch review r1 (local) Finding #2 and the implementation log (local) Medium 2.

**See also:** Lesson #96 (field aggregation strategy per field type), Lesson #95 (handle duplicate keys by summing, not silent overwrite), CLAUDE.md §1 "Data-loss conditions must be logged at warning+, never debug".

**See also (principle cluster A):** playbook lesson "An `lru_cache`-Decorated Function That Reads a Module Global at Call Time Needs an Autouse Fixture That Rewires the Global AND Calls `cache_clear()` in BOTH Setup and Teardown" (same family, distinct angle: multi-cause flag within one function (playbook lesson "An `lru_cache`-Decorated Function That Reads a Module Global at Call Time Needs an Autouse Fixture That Rewires the Global AND Calls `cache_clear()` in BOTH Setup and Teardown") vs sibling aggregators mirror patterns (this lesson) vs centralized helper across callers (#110). Each body distinguishes itself.).

## 103. Decision-Point Doc Prose Enumerations Must Match Implemented Code Branches

**Principle:** Family H (Verify the real thing, not the abstraction)


When a decision-point record (or any spec doc) describes a rule as an enumerated list, "N-tier rule", "N-step", or cases (1)-(N), every enumerated item must map to a code branch and every code branch must appear in the enumeration. Count mismatches and missing cases survive code review because each individual bullet reads plausibly in isolation; only a branch-by-branch cross-check catches the drift.

**What happened (2026-06-17):** `DP-013` in `docs/maintenance/tax/decision_points/2025.md` described the zero-basis review gate as a "Three-tier rule" and stated `cost=0 AND proceeds=0` "never flags" unconditionally. But `_build_zero_basis_review_reason` in `src/tax_reporting/application/crypto/fifo_helpers.py` implements four flagging branches, including a `cost=0 AND proceeds < 0` always-flag tier (independent of the threshold), and flags the zero-zero case when the threshold is 0. The fourth tier and the escape-hatch qualifier were both absent from the doc. The omission was found by the documentation review sub-agent, not by the implementer, the plan, or the earlier review rounds.

**Required behavior:**
1. When adding or changing a conditional branch in a rule that a decision-point doc enumerates, update the doc's enumeration (both the count and the cases) in the same change.
2. When reviewing such a change, cross-check each doc bullet against a code branch and each code branch against a doc bullet. Do not trust a "three-tier"/"four-tier" heading or a per-bullet read; count the branches.
3. Apply the same check to test class docstrings that summarize a gated rule (the `TestBuildZeroBasisReviewReason` summary had the same stale "three-tier" wording).

**Why this is distinct from playbook lesson "Early Returns Can Skip Mandatory Sections":** that playbook lesson covers field/flag sync (a TOML boolean needs a dataclass field). This lesson covers prose-enumeration accuracy (the `.md` rule description must list every implemented branch). Both can hold simultaneously: the `.md` and `.toml` sidecars were in sync with the dataclass, yet the `.md` prose was still wrong about the branch count.

**See also:** CLAUDE.md/AGENTS.md decision_points rule, `docs/maintenance/tax/decision_points/2025.md` DP-013.

## 104. Standalone Withdrawals Tagged Cost/Loan Fee Represent Taxable Disposals; Distinguish from Validator/Network Fees Using TxHash Co-occurrence

**Principle:** Family A (Equivalence-class coverage)


When implementing filters to exclude transaction/network fees (Koinly tag `Cost` or `Loan fee`) from capital gains reporting, be careful not to filter out standalone withdrawals that represent taxable disposals for service consideration (e.g. card subscriptions or service fee payments). Under jurisdictions like Portugal, while utility network/gas fees are non-taxable due to lack of direct consideration (CIRS Art. 10(1)(k)), spending crypto to purchase card services or subscriptions is a taxable *alienação onerosa* (PT-C-004) and must remain in the capital gains report.

**Required behavior:**
1. Do not filter out `Cost`/`Loan fee` rows blindly.
2. Build a frequency count of all non-empty transaction hashes (`TxHash`) from the Transaction History CSV.
3. A `Cost` or `Loan fee` withdrawal row is only classified as a utility network/gas fee if it has a non-empty `TxHash` that appears **at least twice** in the Transaction History CSV (co-occurring with a parent transaction, such as a trade, deposit, or transfer).
4. Standalone rows with unique or empty `TxHash` values must be kept as taxable disposals.

**Shape trigger (when to suspect this family):** filtering transaction fees based on cosmetic tags; the data contains both validator gas fees and service payments; some service payments are wrongly filtered out, creating under-reporting of capital gains.

**General form:** Filter logic targeting transaction costs based on broad tags must verify that the fee is a secondary utility charge co-occurring with a primary trade/transfer rather than a standalone payment. Using transaction ID/hash co-occurrence prevents broad tag matches from filtering taxable service purchases.

## 105. Decouple Pipeline Stages to Keep Correction Modules Single-Responsible and Prevent Flag Clobbering

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

**See also:** deduplication of spot vs derivatives, tracing TH rows to OGR.

## 106. Sentinel for `dict.get` Default Must Exclude All Valid Observed Data Values

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

**See also:** type-safe sentinels for absent optional fields, `coding_guidelines.md` #4.

## 107. Outer Row-Level Exception Block Must Not Prevent a Trusted-Branch Operation From Completing

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

**See also:** catch specific exception types, `coding_guidelines.md` #5 (warn-and-skip for row-level errors).

## 108. Use `get_args(hint)` Not `get_origin(hint)` for Precise Generic Type Dispatch in Config Loaders

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

**Corollary:** When the conversion step stores the result back into the dict (which it must -- see playbook lesson "A Review Loop Whose Finding Count Is Non-Monotonic Signals an Over-Engineered Mechanism - Cut It, Do Not Patch Its Edge Cases"), explicitly overwrite with the converted values: `flags[flag_name] = {k: Decimal(str(v)) for k, v in flag_value.items()}`. Merely instantiating Decimals during validation without storing them leaves raw TOML floats in the dict.

**Shape trigger:** a config loader type-dispatches on `get_origin(hint) is dict`; a new `dict[K, V]` field with a different value type is added; the loader silently applies the wrong conversion.

**See also:** decision-point config flag type dispatch, multi-type config loading requires explicit type-dispatching.

## 109. Matching Event Fields Must Mirror the Normalization Applied to Domain Entry Fields

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

**See also:** duplicate key handling in index builders, collision safety checks in matchers.

## 110. Aggregate Fragmented Lots Before Evaluating Ceilings

**Principle:** Family E (Match and aggregate first, calculate second)


When evaluating a value ceiling/threshold against an event that has been split into multiple fragmented lots (e.g., FIFO matching), checking the threshold against individual lot proceeds defeats the ceiling. Always group the matched lots by the underlying event and evaluate the sum of their proceeds against the ceiling, rather than evaluating lots independently.

## 111. DTA Suspension and NHR Blacklist Distinctions

**Principle:** Family H (Verify the real thing, not the abstraction)


When assessing NHR exemptions for foreign income, strictly rely on Portugal's domestic tax haven blacklist (Portaria n.º 150/2004) rather than international or EU non-cooperative lists.

**Trigger:** A Double Taxation Agreement (DTA) is suspended, or a country is added to an EU/international blacklist, and you need to determine if NHR exemption still applies.

**Rule:** 
- If a DTA is suspended, the Portuguese AT falls back to domestic law (CIRS Art. 81(5)). Foreign rental income remains exempt under NHR if it may be taxed in the source country under the OECD Model AND the source country is not on the Portuguese blacklist (Portaria n.º 150/2004).
- Do not assume an EU blacklist addition automatically nullifies Portuguese NHR exemptions; Portugal's domestic Portaria determines the legal status.

**Example (2026-06-25 Russia DTA suspension):** Russia was added to the EU non-cooperative list in 2023, and it suspended most DTA articles with Portugal. However, because Russia was not added to Portugal's domestic Portaria 150/2004 list, the NHR fallback rule (CIRS Art. 81(5)) still legally exempts Russian rental income in Portugal.

---

## 112. Getting "today" in this repo: use `datetime.now(tz=UTC).date()`, never `date.today()`

**Principle:** Family A (Mechanical invariants over prompt advice) / Family D (Single source of truth)

This repo's `pyproject.toml` selects the ruff `DTZ` ruleset and ignores `DTZ001`/`DTZ005` but NOT `DTZ011`. `date.today()` therefore trips `DTZ011` and fails `ruff check`. The codebase precedent for "now" is `datetime.now(tz=UTC)` (e.g. `src/tax_reporting/application/crypto/parsing.py:68` uses `datetime.now(tz=UTC).year`).

**Rule:** When new code needs the current date, write `datetime.now(tz=UTC).date()` (importing `datetime` and `UTC`), not `date.today()`. Do not add a `# noqa: DTZ011` to silence it; switch the call. Functions that need test-injectable time should take a `today` callable defaulting to `None` and fall back to `datetime.now(tz=UTC).date()` at call time, so tests inject a fixed date without `freezegun` and without breaking the DTZ rule.

**Shape trigger:** you reach for `date.today()` or `datetime.now()` without a tz argument in new application code; `ruff check` then fails on `DTZ011`.

**Why this matters:** `DTZ011` is selected on purpose to keep date-sources timezone-aware; a `# noqa` or `date.today()` defeats that invariant silently. Following the existing `datetime.now(tz=UTC)` precedent keeps the rule mechanical (grep for `date.today(` should find nothing in `src/`).

**See also:** `src/tax_reporting/application/crypto/parsing.py:68` (the precedent), `pyproject.toml` `[tool.ruff.lint]` select/ignore (DTZ selected, DTZ001/DTZ005 ignored, DTZ011 active), `docs/maintenance/project-guidelines.md` #6 (distinct: localizing naive external-report dates, not getting "today").

## 113. Negation-grep backstops must not match the forbidden token inside prose that merely narrates the seam

**Principle:** Family H (Verify the real thing, not the abstraction) / Family G (Data-loss observability)

This repo's DI-3 discipline includes a negated grep that asserts NO test patches `urllib`/`urlopen` directly (tests must go through the module-level `_http_get_json` seam). A docstring that NARRATED the seam with the sentence "the underlying urllib urlopen transport" caused that grep to match itself: the grep cannot distinguish a guarded code call from a prose mention, so a passing discipline looked like a violation. The fix was rewording the docstring ("the underlying urllib transport"), dodging the literal without weakening the test discipline.

**Rule:** When authoring a backstop NEGATION grep (a grep that must return ZERO matches), treat its forbidden token as a reserved word not just in code but in prose and docstrings. If a docstring or comment must mention the underlying mechanism the grep forbids, paraphrase it so the prose does not contain the grep's literal pattern (e.g. name the responsibility "the underlying transport" or "the network seam", not the token `urlopen` the grep forbids). Conversely, when a negation grep unexpectedly hits, FIRST determine whether the match is prose narration of the seam rather than the forbidden call it guards; do not weaken the grep to keep the prose.

**Shape trigger:** you author a backstop grep whose value is "zero matches for forbidden token X" AND you also write a docstring/comment that explains what the seam abstracts over; the natural phrasing names X ("wraps the X call", "delegates to X"). The grep then hits your own prose.

**Why this matters:** a negation grep is a binary invariant (zero-or-fail); it cannot score partial matches. Prose that legitimately explains the seam is indistinguishable to the grep from the forbidden direct call, so the invariant appears violated when the code is actually clean. The two recoveries - reword the prose, or weaken the grep - have opposite safety properties; always reword the prose.

**See also:** `src/tax_reporting/infrastructure/on_chain/etherscan_client.py` (`_http_get_json` seam docstring), the DI-3 backstop grep block in the on-chain fetcher plan, lesson #55 (deletion backstop greps must cover docs - the scope side; this lesson is the inverse pattern: the grep correctly scans prose and then must not be defeated by self-narration).

---

## 114. The `http_get_json` param on `run_on_chain_fetch` and the `_client_for_wallet` instance assignment are dead code (consumer reads the module global)

**Principle:** Family H (Verify the real thing, not the abstraction) / Family A (Mechanical invariants over prompt advice)

`run_on_chain_fetch(*, http_get_json=None)` accepts an optional DI-3 injection param, and `_client_for_wallet` does `client._http_get_json = http_get_json` when it is provided. But `EtherscanV2Client._call_with_retries` calls the MODULE-LEVEL name `_http_get_json(self.base_url, params)` (a bare global, NOT `self._http_get_json`). The instance attribute is therefore never read; the param and the assignment are dead code today. The unit and integration tests all drive the seam by monkeypatching the module global `tax_reporting.infrastructure.on_chain.etherscan_client._http_get_json` directly, which works regardless of the param. The docstring on `_client_for_wallet` (and the DI-3 note on `run_on_chain_fetch`) currently CLAIMS the instance injection works ("injected into the client so tests can drive the transport"), which is false and will mislead the next maintainer into relying on a no-op path.

**Rule:** Treat the `http_get_json=` param on `run_on_chain_fetch` and the `client._http_get_json = ...` line in `_client_for_wallet` as DEAD until the client is changed to call `self._http_get_json`. To drive the HTTP seam in tests, monkeypatch the module global (`tax_reporting.infrastructure.on_chain.etherscan_client._http_get_json`), never the param. If you fix the client to honor instance injection, use a `field(default_factory=...)` that captures the module function (a `field` default referencing `self._http_get_json` evaluates at runtime and breaks); simpler is to delete the param and the dead assignment entirely, since every test already uses the module-global path.

**Shape trigger:** you reach for `run_on_chain_fetch(..., http_get_json=fake)` in a test expecting it to intercept HTTP, OR you read the `_client_for_wallet` docstring and believe the instance injection is live, OR you are about to "use" the param in new code. The abstraction (a documented injection seam) and the reality (a bare module-global call inside the consumer) diverge.

**Why this matters:** a dead DI surface that is documented as working is worse than no seam at all: a test that passes `http_get_json=fake` will silently hit the real network (or the module default) instead of the fake, and the failure mode is "test does the wrong thing but looks GREEN". Flagged for Phase 3 cleanup (drop the param + assignment, or make the client honor `self._http_get_json` via `field(default_factory=...)`).

**See also:** `src/tax_reporting/application/on_chain_fetcher.py` (`_client_for_wallet` line `client._http_get_json = http_get_json`; `run_on_chain_fetch` signature), `src/tax_reporting/infrastructure/on_chain/etherscan_client.py` (`_call_with_retries` bare `_http_get_json(...)` call), lesson #113 (the DI-3 seam from the grep/prose side), the on-chain fetcher plan's permitted monkeypatch fallback.

---

## 115. A classifier function's terminal fallback must return a sentinel plus a warning, not a default that masquerades as a valid classification

**Principle:** Family C (Representation: sentinel vs None vs exception) / Family G (Data-loss observability)

A classification function that maps an input onto a small set of valid enum-like strings (e.g. `"in"` / `"out"`) via `if ... elif ...` branches must NOT let its terminal `else` fall through to one of those same valid values. An `else: return "in"` is indistinguishable from a genuine `wallet == row["to"]` classification: the downstream row is emitted looking correct, the audit trail shows no anomaly, and an off-wallet leg (here, a checksum mismatch between the configured address and the API's lower-cased form) is silently recorded as a credit. The fallback must instead return a sentinel the valid set does not contain (here `"unknown"`) AND emit a WARNING carrying enough context (tx hash, the wallet under test, the row's from/to) that a reviewer can find and fix the root cause; the row is still emitted, but flagged.

**Rule:** For any function that classifies an input into a fixed set of valid return values and has an "unmapped" path, that path must (1) return a sentinel value that is NOT a member of the valid set and (2) log a WARNING with the discriminating context. Never let the fallback return a valid enum member as a silent default. If a sentinel is not acceptable downstream, raise instead of silently mislabeling. Pair the rule with a test that exercises the unmapped path and asserts both the sentinel return value and the WARNING text.

**Shape trigger:** you are writing or reading an `if x == A: return "a"` / `if x == B: return "b"` / `else: return "a"` (or `"b"`) classifier; the `else` is a "shouldn't happen" case rather than a true fourth classification. The trigger is the terminal branch defaulting to a value that also appears as a legitimate `if`-branch result.

**Why this matters:** a silent valid-looking default is the worst representation choice (Family C): the row is not dropped (so the loss is not a missing row), but its meaning is wrong (so any downstream aggregation that keys on the classification, e.g. inflow vs outflow totals, is silently corrupted). A WARNING plus a non-valid sentinel converts the silent corruption into an observable, greppable anomaly without losing the row.

**Distinguishing from lesson #106 (sentinel for `dict.get` default):** #106 is the same Family-C root cause (a default that collides with a valid data value) but its shape is a `dict.get(key, default)` guard. This lesson is the classifier-function form: an `if/elif/else` whose terminal branch returns a valid enum member. #106 fires on dict-lookup guards; this lesson fires on classification fallback branches.

**Example:** `_direction(row, wallet_address)` in `src/tax_reporting/infrastructure/on_chain/bera_decoder.py` resolved a transaction leg to `"out"` (sender) or `"in"` (receiver); the original terminal `else` returned `"in"` as a default, silently recording any off-wallet leg as a credit. The fix returns the sentinel `"unknown"` and logs `WARNING` "Off-wallet leg for tx hash=...". The `test_off_wallet_leg_emits_unknown_and_warns` test pins both the return and the WARNING substring. See the on-chain fetcher code review r1 finding F3.

**See also:** lesson #106 (sentinel for `dict.get` default - the dict-lookup form of the same Family-C root), lesson #97 (internal sentinels must not leak to user-facing output - the opposite concern: a sentinel that SHOULD be a raw value), `coding_guidelines.md` #6 (user-facing labels use self-explanatory terminology), AGENTS.md Rule #4 (type-safe sentinels).

---

## 116. A config field that filters post-fetch does not bound the HTTP fetch

**Principle:** Family G (Data-loss observability)

A date-range field the consumer applies as a local filter AFTER rows are downloaded does NOT reduce what the API returns. The on-chain fetcher calls Etherscan V2 with `startblock=0`/`endblock=99999999` (block-number pagination, `etherscan_client.py:149-150`); `start_date`/`end_date` only drop rows inside `bera_decoder._in_date_window` (`bera_decoder.py:151,189`) after the full history is fetched. For a long-history chain (Ethereum, BSC, Polygon, Arbitrum, BASE, zkSync) a wallet's full history from block 0 exceeds the client's `max_rows=100000` ceiling (`etherscan_client.py:121,164-173`); the loop logs one WARNING and returns a truncated prefix - a tax-data-loss condition.

**Rule:** When a config field's name suggests it bounds a network fetch (date range, id range), verify WHERE the bound is enforced: an API query parameter, or a post-fetch local filter. Do not document a "supported" set of targets wider than the fetch can retrieve without silent truncation. Either narrow the documented set to what is safe, or fix the fetcher to bound the request at the API before advertising the wider set. A plan that moves such a field from user config to internal derivation is the moment to re-check, because the plan's prose re-states the supported set.

**Shape trigger:** a config refactor touches a date/range field consumed by a fetcher; the plan or docs claim a list of "supported" targets; the field name (`start_date`, `from_block`, `since`) implies it limits the request. Trace the field to its consumer: if it filters a list the transport already returned, the bound is illusory.

**Example:** The minimal-`chains.json` plan (`docs/history/plans/2026-08-01-minimal-chains-json-config.md`) initially documented all 8 EVM Etherscan-V2 chains as supported because the new `_CHAIN_TO_CHAINID` registry covered them. Plan review r1 F1 (High) caught that block-0 pagination silently truncates for 6 of 8; the fold narrowed the documented set to Berachain-only. See `etherscan_client.py:143-179` and `bera_decoder.py:84-86`.

**See also:** lesson #114 (same fetcher; a dead DI seam is the test-side analog - passes but does the wrong thing), `coding_guidelines.md` #5 / AGENTS.md Rule #1 (data-loss conditions never silently discarded; warning+, never debug).

---
## 117. Amending a type/contract that flows across module boundaries: grep across directories, not from memory

**Principle:** Family A (Verification-first; consumer-list completeness)

When a plan task amends a type or contract (a field type, a correlation key, a dataclass shape) that is consumed across module boundaries, the consumer enumeration MUST be derived by `grep` scoped across ALL directories the type can reach, not from memory, not from a single directory, and not from the plan's own file list. The failure mode recurs at directory boundaries: a sweep scoped to one package silently misses cross-package consumers that sit on the very type-flow path being widened.

**Rule:** Before writing any plan task that widens a type or amends a contract (e.g. `tx_key: str` -> `str | tuple[str, str]`, adding `event_id` to a key dataclass), run `grep -rn "<symbol>" src/` (scoped to the whole source tree, not one subdirectory) and record EVERY file + line that reads, types, or threads the symbol. The recorded list IS the sweep scope for the task; do not trust a pre-existing list, even one in the plan, without re-deriving it by grep at execution time. A type alias (e.g. `TxKey = str | tuple[str, str]`) introduced to make the widening consistent must flow to EVERY consumer in the same commit, or the "this commit typechecks" premise of a split refactor is voided. The plan's own premortem cannot catch this if the premortem's consumer list was itself enumerated from memory.

**Shape trigger:** a plan amends a type or contract; the task lists "affected consumers" by name; the grep scope is a single directory or a hand-curated list; the type flows through a `domain/` dataclass into an `application/` helper and back. Any of these -> suspect an incomplete sweep, especially when the type crosses a package/directory boundary the grep pattern does not cover.

**Example:** The on-chain transaction tagger plan (`docs/history/plans/2026-08-02-on-chain-tx-tagger.md`) amends `tx_key` (the FIFO correlation key) to support `(tx_hash, event_id)` for split events. Round 1 of plan review caught the sweep missing `crypto_fifo/matching.py`, `transfer.py`, `_emitters.py` (only `cross_asset.py` and `merge.py` were named). Round 2 caught the type-widening rationale was wrong for `merge.py`'s nested tuple. Round 3 caught the grep was scoped to `application/crypto_fifo/` only and missed `domain/crypto_fifo.py:104-105` (`AssetFifoResult.carryover_cost_by_tx_key`) and `application/crypto/fifo_helpers.py` (the cross-package bridge that builds the nested `(tx_key, platform)` tuple). Round 4's independent `grep -rn "tx_key" src/tax_reporting/` finally confirmed all 10 source files were in scope. Three review rounds were spent catching what one cross-directory grep at plan-write time would have caught.

**See also:** `coding_guidelines.md` #17+ (Family A verification-first); AGENTS.md Rule #4 ("When a plan task changes data flow semantics, grep ALL `tests/`" - this lesson is the production-code analog for type/contract amendments); lesson #46 (a regression test must exercise the production call site - the deferred-transfer-nonzero-cost test is the analog for the tx_key sweep).

---

## 118. A "compatibility layer" still needs its downstream contracts audited (a projection that fans out to N consumers is NOT mechanical)

**Principle:** Family A (Verification-first; downstream-contract completeness)

A module labeled a "compatibility layer", "adapter", "projection", or "mechanical mapping" is NOT a license to skip auditing the contracts of every downstream consumer that reads its output. The label describes the *intent* (preserve an existing shape so callers keep working); it does NOT describe the *risk*. When the projection fans one input object out to N rows consumed by M independent consumers that each read contradictory column subsets, the projection has real reconciliation work, and the only way to catch a silent contract violation is a cross-consumer assertion that projects a representative input for each output variant and asserts ALL consumers' contracts hold simultaneously on the projected row.

**Rule:** When designing or reviewing an adapter/compat layer that converts one rich domain object into the row shape existing consumers read:
1. Enumerate EVERY downstream consumer (grep, not memory - see lesson #117) and the EXACT column subset each reads.
2. For each output variant the adapter can emit, assert that a projected row of that variant satisfies ALL consumers' contracts at once (not per-consumer in isolation). Per-consumer tests pass even when two consumers read contradictory columns off the same row; only a cross-consumer test catches the contradiction.
3. Treat the carrier-row rule (or any rule that places a value on ONE of N output rows) as a load-bearing domain accommodation, not a cosmetic choice: document it as such in the module docstring, and assert the consumers that key on the placed value (vs the consumers that key on its absence) both see the row they expect.

**Shape trigger:** a plan or review describes a module as a "mechanical projection", "compat layer", "adapter", or "just maps X to Y"; the input fans out to multiple output rows; the existing consumers were written independently and read different column subsets; the plan's risk assessment says "no behavior change, consumers untouched". Any of these -> suspect the projection has hidden cross-consumer contradictions that per-variant tests will not catch.

**Example:** The on-chain transaction tagger plan (`docs/history/plans/2026-08-02-on-chain-tx-tagger.md`) Task 10 adapter projects one `OnChainTransaction` (parent-tx-level gas, N `Event`s) onto the Koinly-shaped `TransactionHistoryRow`. The plan's premortem B1 (`docs/architecture/on-chain-tx-design.md` §12) found the projection is NOT mechanical: three consumers read contradictory keys off one row - `tx_correlation_key_resolver` reads `tx_hash`; `token_origin` reads `TxHash` (and historically mis-read `TxSrc` as the hash); `fee_filter` counts `TxHash` and reads `Fee Amount`/`Fee Currency`/`Sent Amount`/`Net Value (EUR)`. The carrier-row gas rule places `Fee Amount` on ONE projected row (empty on the rest); a per-EventType mapping test passes even when `fee_filter` and `token_origin` disagree on what that row should carry. The cross-consumer assertion (Task 10 test #7: `test_single_row_satisfies_all_three_consumers`) is the test that would have caught B1 - it projects a representative Event for EACH EventType and asserts all three consumers' contracts hold on the same row. The module docstring MUST declare the adapter exists ONLY to bridge to the Koinly shape and name the carrier-row rule as a non-domain accommodation (Future Maintainer F5 mitigation), so a future contributor does not assume the projection is a free lunch.

**See also:** lesson #117 (the consumer-list grep discipline - this lesson is the contract-audit analog once the consumer list is complete); `coding_guidelines.md` #17+ (Family A verification-first); AGENTS.md Rule #4 (consumers that read contradictory subsets off one row); design record `docs/architecture/on-chain-tx-design.md` §12 B1 (the premortem finding this lesson generalizes).

---

## 119. Source-priority for operator/origin mapping: a locally-archived official (primary) source wins over a conflicting secondary source (on-chain B3 instance)

**Principle:** Family B (Source authority / primary over secondary) - the on-chain application of the existing AGENTS.md rule "A locally-archived official source wins over a conflicting secondary source".

For tax-law or operator-origin resolution, when two sources disagree on an operator/chain country mapping, a **locally-archived official (primary)** source outranks a **secondary** source (an exchange whitepaper, a third-party assessment, a blog). The conflict is NOT resolved by "two equal sources disagree" framing - the primary wins outright, and the secondary is dropped unless it can be promoted to primary (an official registry, a governing-law clause, a regulator filing). This is the operator-origin analog of the existing tax-law source-priority family (lessons #31, #37, #39); it applies the same hierarchy to on-chain contract-level country overrides.

**Rule:** When a contract-level or operator-level country override conflicts with a chain-level mapping:
1. Identify which source is PRIMARY (official: the protocol's own terms-of-service governing-law clause, a regulator filing, an official deployed-contracts doc) and which is SECONDARY (an exchange MiCA whitepaper, a third-party legal assessment, a secondary summary).
2. The primary wins; the secondary is dropped. The contract registry ships EMPTY for the override; the existing chain-level mapping (which itself must trace to a primary source) governs.
3. A contract-level override requires a PRIMARY source STRONGER than the chain-level mapping, not merely a different source. Record the resolution and the source-priority rationale in the artifact so a future contributor does not re-introduce the dropped secondary.

**Shape trigger:** a contract registry or operator-mapping entry cites a source whose authority is hedged ("the legal issuer has not been expressly identified in official public sources", "per <exchange>'s assessment"); it conflicts with a chain-level mapping citing the protocol's own terms-of-service; the plan or PR frames the conflict as "two sources disagree". Any of these -> apply source-priority: primary wins, secondary dropped.

**Example:** The on-chain transaction tagger premortem B3 (`docs/architecture/on-chain-tx-design.md` §12) found the Berachain Distributor contract `0xd2f19a79` operator-country mapping collided: the chain-level mapping (`operator_origin.py:305`) maps `"Berachain"` -> `VG` (British Virgin Islands) citing `berachain.com/terms-of-service` (official, primary - Berachain's own ToS identifies the Bera Chain Foundation and BVI governing law); decision #8 had seeded the Distributor -> `KY` (Cayman) citing the Bitstamp BERA MiCA whitepaper, which the research itself flagged as hedged ("the legal issuer of BERA has not been expressly identified in official public sources") - a secondary source. Resolution: BVI (primary) wins; the KY seed is dropped; `berachain_contracts.json` ships EMPTY `operator_country` for the Distributor and all Berachain rewards resolve via the chain-level VG. The source-priority rule (a contract-level override requires a primary source stronger than the chain-level mapping) is recorded so a future contributor adding a per-contract country override cites a primary source, not a secondary exchange assessment.

**See also:** AGENTS.md Rule #2 ("A locally-archived official source wins over a conflicting secondary source" - this lesson is the on-chain application); lesson #31 (cite the redação in force for the target fiscal year - the version-selection sibling); lesson #37 (probe the canonical URL before assuming an official source is unavailable); lesson #39 (mirror the authoritative source so the primary-over-secondary rule has a local artifact); design record `docs/architecture/on-chain-tx-design.md` §12 B3 (the premortem finding this lesson generalizes).

---

## 120. Resolve a glob-target file BEFORE serializing a same-pattern sibling into the lookup directory

**Principle:** Family E (Temporal / ordering invariants) - a glob/lookup that resolves a user-supplied file by a substring pattern shared with a sibling file the same pipeline is ABOUT TO WRITE runs in a race with the write. Resolved BEFORE the write, the glob returns the user's file; resolved AFTER the write, the glob can return the freshly-written sibling instead, silently dropping the user's data. Compounded by Family G (Data-loss observability) - the lookup succeeds (exit 0, a file is found and merged), so the drop surfaces only as missing rows with no error signal unless a regression test pins it.

**Rule:** When a pipeline (a) resolves a path to a user file via a pattern/glob AND (b) the same pipeline writes ANOTHER file matching that same pattern into the same lookup directory, the resolution MUST happen BEFORE the serialization. Pass the pre-resolved path into the merge step as an explicit argument; do NOT let the merge re-glob the directory after the sibling exists.

1. Identify every glob/lookup the pipeline performs against the directory where it ALSO writes a sibling file sharing the pattern.
2. Hoist each such lookup to run BEFORE the write. Pass the resolved `Path` (or `None`) into the consumer as a required kwarg; remove the consumer's internal `_find_report_path`/glob call.
3. Verify the hoist structurally: grep the moved lookup and the consumer's signature; each MUST appear exactly once. "Tests pass" is insufficient (the suite is GREEN under both orderings when the user's filename happens to sort first).
4. Pin the fix with a regression test for EACH degenerate input case the hoisted lookup can return, not only the primary wrong-match case. Enumerate the cases explicitly: (a) the user file exists but sorts after the sibling (wrong-match); (b) the user file is ABSENT entirely, so the lookup returns `None` (the merge must then write the derived file under a distinct name and leave the user path unset). Each case gets its own test that MUST FAIL without the hoist. A single test covering only (a) leaves the `None` branch the hoist introduced un-pinned; a follow-up review round will catch it as a coverage gap on already-correct code.

**Shape trigger:** a merge/override step that "finds the user's report file" by globbing a directory, in the same pipeline that serializes a derived/synthetic report file with a matching name pattern into that directory. The plan frames the lookup as "find the Koinly/CSV report"; the synthetic file is named to share the lookup substring. The suite is GREEN because the existing fixture's filename sorts before the synthetic one. Any of these -> suspect a glob-vs-write ordering hazard.

**Why this happens:** `_find_report_path` style helpers return `sorted(glob)[0]` (or the single/first match) and were correct when only ONE file matched. Once the pipeline writes a SECOND matching file, the helper's tie-break (`sorted`, lexicographic, mtime) becomes load-bearing, and the tie-break's winner depends on the user's filename - which the pipeline does not control. The hazard is invisible in tests because fixtures conventionally use a `prefix_` (e.g. `koinly_`) that sorts before the synthetic name; real users name their exports without the prefix.

**Example:** The on-chain transaction tagger (`docs/history/plans/2026-08-02-on-chain-tx-tagger.md`) merge step serialized `on_chain_transaction_history.csv` into the Koinly directory and then called `_merge_on_chain_into_koinly_th`, which internally re-resolved the Koinly TH via `_find_report_path(koinly_dir, "transaction_history", ".csv")`. Both the user's `transaction_history.csv` (no `koinly_` prefix) and the freshly-written `on_chain_transaction_history.csv` match the substring; `sorted()` picks `on_chain_...` (sorts before `transaction_history`), so the merge read the synthetic file as the Koinly TH and dropped the user's rows. Review r1 F1 (`docs/history/reviews/2026-08-03-2026-08-02-on-chain-tx-tagger-code-review-r1.md`) hoisted the `_find_report_path` call to the caller so it runs BEFORE the on-chain CSV is serialized, and passed the resolved path into the merge as a required `koinly_th` kwarg; the merge's internal glob was removed. The F2 regression test `test_non_prefixed_koinly_th_survives_merge` writes a bare `transaction_history.csv` and asserts the non-opted-in row survives; it FAILS with `assert 0 == 1` when F1 is reverted in place.

**Witness (2026-08-03 r2 targeted review of the same plan, post-r1-fix):** The r1 hoist introduced a NEW code path the original internal glob never had: when no `*transaction_history*.csv` exists in `koinly_dir`, the hoisted `_find_report_path` returns `None`, and `_merge_on_chain_into_koinly_th` must then write the merged TH to a distinct name (`on_chain_merged_transaction_history.csv`) and leave the user path unset. r1's regression test `test_non_prefixed_koinly_th_survives_merge` pinned only case (a) (user file exists, sorts after sibling); the `None` branch was correct by reading but had NO test. r2's targeted follow-up (finding F2-r2, Low, testing) added `test_no_koinly_th_on_chain_rows_become_th`, which creates an EMPTY `koinly_dir`, drives the substitution, and asserts the merged TH is written under the canonical `None`-branch name, contains the on-chain rows, and the standalone on-chain CSV is unlinked so the pipeline re-glob resolves exactly one file. Reinforces Rule step 4: a hoist does not have one regression shape, it has one PER degenerate input case the hoisted lookup can return.

**Distinguishing from lesson #47 (rename requires multi-pattern grep across all tests):** #47 is about scattered REFERENCES to a fixture path diverging after a rename (Family H + G: a stale glob silently matches zero files). This lesson is about a glob that matches the WRONG file because a same-pattern sibling was written into the lookup directory between the intended resolution point and the actual resolution point (Family E + G). #47's fix is to grep every shape of the rename; this lesson's fix is to move the glob before the write and pass the result in. Both share Family G (silent data loss with exit 0); the failure mode differs (zero-match vs wrong-match).

**See also:** lesson #90 (authoritative source overrides must precede aggregation - the same "order the load-bearing resolution before the lossy step" principle, applied to override-vs-aggregate instead of glob-vs-write); lesson #118 (compat-layer downstream contracts - the on-chain tagger review sibling); AGENTS.md constraint on data-loss observability ("Data-loss conditions ... must be logged at warning+"); design record `docs/architecture/on-chain-tx-design.md` §12 (premortem surface for the on-chain tagger); review `docs/history/reviews/2026-08-03-2026-08-02-on-chain-tx-tagger-code-review-r1.md` F1/F2 (the finding and primary regression test); review `docs/history/reviews/2026-08-03-2026-08-02-on-chain-tx-tagger-code-review-r2.md` F2-r2 (the `None`-branch coverage witness).

## 121. Changing a Discovery Mechanism (Glob to Explicit Path) Requires Rewriting Every Test That Re-Discovers via the Old Mechanism, Not Just the Test That Pins the Name

**Principle:** Family H (Verify the real thing, not the abstraction) + Family G (Data-loss observability). When production code discovers an artifact by a glob (`_find_report_path(koinly_dir, "transaction_history", ".csv")`), tests independently re-run the SAME glob to locate the post-mutation artifact. Changing production to discover via an explicit threaded path (so the glob no longer matches) breaks every test that re-runs the old glob - and a plan that only updates the ONE test pinning the artifact's *name* misses the other tests that call the discovery helper expecting non-None. The plan task's `Run -> expect GREEN` is then unreachable, which a `review-plan` pass catches but a `plans`-author eyeball does not.

**Trigger:** A plan task changes HOW an artifact is discovered (glob -> explicit override path; filename pattern -> registry lookup; sorted-list `matches[0]` -> caller-supplied path). The natural reflex is to update the one test that asserts the artifact's filename, and the one production write site. Before stopping, ask: "Have I grepped the WHOLE test tree for every call to the OLD discovery helper (`_find_report_path(...)`, the glob pattern, the discovery function name), not just the one assertion that pins the new name?"

**Rule:**
1. When a task changes the discovery mechanism for an artifact, grep the entire `tests/` tree for every call site of the OLD discovery helper AND the OLD filename pattern, in one pass: `grep -rn '_find_report_path(.*transaction_history' tests/` and `grep -rn 'on_chain_merged_transaction_history' tests/`.
2. For each call site, decide whether it (a) re-discovers to assert the artifact exists/passes a glob-rediscover contract (must switch to consuming the new explicit result field, e.g. `result.merged_th_path`), or (b) legitimately tests the discovery helper itself (keep the glob). A blanket "update the pinned-name assertion" leaves category (a) tests calling a glob that now returns None.
3. The plan task's `Run -> expect GREEN` step must list, by file and line, every test call site the mechanism change reaches; a GREEN claim that omits any call site is a plan defect.
4. Backward-compat default (`None` -> old glob path) is NOT sufficient proof: it preserves only callers that OMIT the new param. Callers that re-run the old glob INDEPENDENTLY (tests, sibling loaders) still break because they never see the override.

**What happened (2026-08-04 review-r1-fixes plan, review-plan r1 blocking finding F1):** The plan's Task 2 changed the merged TH filename from `on_chain_merged_transaction_history.csv` (matches `*transaction_history*.csv`) to `on_chain_merged_th.csv` (non-globbing), and threaded an explicit `transaction_history_override` path forward so production reads the merged file directly. Task 2's bullet only updated ONE pinned-name assertion (`test_on_chain_bera_opted_in.py:374`). But THREE tests in that file re-discover the merged TH via `_find_report_path(koinly_dir, "transaction_history", ".csv")` at lines 232, 307, and 365-371; once the filename no longer matches the glob, all three return None and their `assert merged_th is not None` fails. The plan's `Run -> expect GREEN` was unreachable as written. The `review-plan` r1 panel (testing lens) caught it as a blocking finding; the fold rewrote Task 2 to switch all three call sites to `result.merged_th_path`.

**Why this happens:** Tests mirror production's discovery to assert the post-mutation artifact is real - they re-run the same glob the loader will run. When production switches to an explicit path (the right fix for a destructive-overwrite or collision bug), the glob is no longer the discovery mechanism, but the tests still call it because their assertions were written when it WAS. The one test that pins the NAME is the visible anchor; the other tests that call the HELPER are the hidden ones. A plan author who follows the rename (#47) but not the mechanism change stops at the name anchor.

**Distinguishing from lesson #47 (rename requires multi-pattern grep across all tests):** #47 is about scattered REFERENCES to a renamed fixture (directory, filename, stem, glob pattern, prose) diverging from a conftest constant - the discovery mechanism (glob) is unchanged, only the name it matches changed. This lesson is about the discovery MECHANISM itself changing (glob -> explicit path), so tests that call the discovery helper break even when no name changed - the helper now returns None for the artifact that production reaches via the new path. #47's fix is grep every NAME shape; this lesson's fix is grep every DISCOVERY-HELPER call site and decide re-discover vs consume-explicit-result per site. Both share Family H (the visible anchor - constant or name - is an abstraction over the real, scattered call sites).

**Required behavior:**
1. Before writing a task that changes a discovery mechanism, grep the whole test tree for the OLD discovery helper and OLD pattern; list every call site by file+line in the task.
2. For each call site, state whether it switches to the new explicit result, keeps the helper (legitimately testing discovery), or is deleted.
3. The task's GREEN step must name each rewritten call site; an unnamed call site that the mechanism change reaches is a plan-review blocking finding waiting to happen.
4. Run the full affected suite (not just the file with the pinned-name assertion) before claiming GREEN; the other re-discover tests are in sibling test methods of the same file.

---

## 122. Personal document fields need distinct source checks

**Principle:** Family H (Verify the real thing, not the abstraction)

For a personal authority document, identity fields and signing fields have different sources. Load static identity details from the local facts file. Confirm dynamic fields, including signing place and date, for the current document. Do not copy values from a template or earlier draft.

**Rule:** Before delivery, compare every rendered identity field with the facts source and verify the requested signing place and date explicitly. Render the PDF and check the final text before sending it.

**Shape trigger:** A form is generated from a template or an earlier draft, and it includes a signing line or other context-specific fields. Treat those values as unverified until reconciled with the current request.

---

## 123. The Agent Shell Is Not the User Shell: Env-Gated Code Paths Make Tests Env-Dependent, and a Green Agent-Side Suite Proves Nothing About the User's Run

**Principle:** Family H (Verify the real thing, not the abstraction) + Family B (Make the implicit explicit / surface hidden state). A green, fast suite in the agent's non-interactive shell is an *abstraction* over the suite the user actually runs; the *real thing* includes the user's exported environment. Any production env gate (`os.getenv`) silently couples the two.

**Root cause (2026-08-16 test-hermeticity incident):** Production deliberately reads `os.getenv("BERA_CHAIN_API_KEY")` (`src/tax_reporting/main.py:358`, the DI-3 env gate) to enable the optional on-chain Etherscan V2 fetch (correct for production, hazardous for tests). The user's `.zshrc` exports that key, so every test calling `_main()` without pinning the env (`tests/unit/test_cli.py`, `tests/unit/application/test_crypto_reporting.py`, `tests/end_to_end/test_on_chain_bera_opted_in.py`, where the last fakes `getenv` in only one of its tests; its other `_main` calls inherit the real env) performed a live API fetch, read the gitignored real wallet registry `resources/source/<year>/chains.json`, burned API quota, and took ~9s per test at ~5% CPU. The agent shell (no key) ran the same suite green and fast, which is also why five code-review rounds and the then-opt-in path guard never saw it. Both shells were "correct"; only one matched the user's reality.

**Methodology caution (grep false-positive):** `tests/unit/application/test_main_koinly_directory.py` was initially suspected but verified NOT to call `_main` (an early grep matched the substring `via_main(` (a helper METHOD NAME), not a `_main` call site). Grep hits on substrings inside identifiers are not call-site evidence; verify each hit is a real call before treating it as affected.

**Rule: diagnostic ladder for "slow/flaky for the user, green and fast for the agent":**
1. **CPU-%-of-wall first.** Low CPU + long wall means waiting on I/O (network/disk), not compute; this single observation redirects the whole investigation.
2. **Reproduce the user's shell:** `zsh -i -c 'uv run pytest <files> -q'` loads the interactive env (rc files, exports). If the slowness appears here and not in the agent shell, it is environmental.
3. **Find the coupling:** diff the environments (`env` in both shells) and list every env-dependent production gate: `grep -rn getenv src/`. Each hit whose env var differs between shells is a candidate.
4. **Prove causation in BOTH directions:** unset the var in the user shell (fast again?) and set a dummy in the agent shell (slow now?). One direction is correlation; both is causation.

**Rule: fix contract (test infra only; production stays frozen):**
1. **Env-pin is PRIMARY.** A function-scoped autouse fixture (`_pin_hermetic_env` in `tests/conftest.py`) deletes the env var before every test (`monkeypatch.delenv(..., raising=False)` covers both "never set" and "set" shells). Tests that legitimately need the key use `monkeypatch.setenv` in the body, which runs after the fixture and wins.
2. **Socket guard is a TRIPWIRE, not the fix.** An autouse fixture (`_forbid_network`) raises `AssertionError` on any outbound DNS/socket call unless the test opts in with `@pytest.mark.network`. It cannot be the primary gate where the code under test wraps the call in a broad `except Exception` (DI-1 degrade template at `_main`), the AssertionError is swallowed into a warning; only the env-pin actually prevents that fetch.
3. **Audit-hook path guard always-on.** The open-monitor guard for gitignored personal data (`tests/unit/test_on_chain_tests_no_personal_data.py`) runs by default; the only opt-out is an explicit `SKIP_AUDIT_GUARD=1` (mirroring `-m "not slow"` explicit deselection, never a silent default).

**Shape trigger:** A user reports the test suite is slow, flaky, quota-burning, or touching personal data while the agent/CI run is green and fast; or production code reads `os.getenv`/`environ` anywhere; or a test invokes a wide entry point (`_main`, CLI runner) rather than a seam. Any of these → suspect an ambient-env dependency and run the ladder before touching code.

**See also:** plan `docs/history/plans/2026-08-16-test-hermeticity-guards.md` (guards, invariants, and the incident narrative); lesson #113 (negation-grep matching forbidden tokens inside narrating prose; the sibling grep-hygiene caution for the `via_main(` false-positive); AGENTS.md Testing section (the hermeticity contract: no ambient env vars, no outbound network, no gitignored-data opens).

---

## 124. Package-Wide Static Guards Must Derive the Module Set From the Package, Not a Hardcoded Tuple

**Principle:** Family H (Verify the real thing, not the abstraction). A hardcoded module tuple in a guard test is an abstraction over the package's current module list; it drifts silently the moment a module is added, so the guard stays green while its coverage shrinks.

**Trigger:** A test asserts "no module in package X performs Y" and enumerates the modules by hand.

**Rule:** Derive the set at test time: `pkgutil.walk_packages(pkg.__path__, prefix=...)` (covers subpackages too, not just top-level `iter_modules`), but SEED the list with the already-imported package module itself (`sys.modules[pkg.__name__]`) because `walk_packages` yields only CHILDREN, never the package's own `__init__`. Import each via `importlib.import_module`; never skip `ImportError` silently (a module that fails to import escapes the guard entirely) - collect skipped names and assert the list is empty with a message naming them, and pass an `onerror` callback to `walk_packages` that records traversal errors, also asserted empty. Keep only a sanity anchor asserting the known module is in the derived set. Never restate the package membership in the test.

**Example:** r3 review finding on the DI-3 env-read guard in `tests/unit/application/test_run_report.py` (`test_no_env_reads_is_static`): it hardcoded two modules while the `application` package had more; any future module reading `os.getenv` would have escaped the guard entirely. r4 finding: the r3 fix still used `iter_modules`, silently skipping the `crypto`, `crypto_fifo`, `extraction`, and `persisting` subpackages; `walk_packages` closed the gap. r5 findings: `walk_packages` still missed `application/__init__.py` itself (children only; fixed by seeding the package module), and the `except ImportError: continue` defensive skip would have silently exempted any unimportable module (fixed by asserting the skipped list empty).

**See also:** lesson #123 (hermeticity guards); AGENTS.md Testing section ("Static hygiene guards must scan every file the protected value could realistically reach").

---

## 125. Static Guards Ban the Operation, Not the Import of the Module That Can Perform It

**Principle:** Family H. Banning `import os` (by substring or AST `ast.Import`) targets a vehicle, not the hazard; a module may legitimately use the same import for safe operations. The guard must match the dangerous operation itself.

**Trigger:** Drafting an AST/substring hygiene guard and the simplest predicate is "the module imports X".

**Rule:** Match the operation's AST shapes (e.g. `os.getenv`/`os.environ` as Attribute/ImportFrom/Name predicates), which hold under any import style (`import os`, `from os import getenv`, `os = __import__("os")` aliasing is out of scope but import-style variation is not). Record any deliberate deviation from a reviewer's letter-of-the-finding fix in the test docstring.

**Example:** r3 finding: a literal `import os` ban over the application package would false-fail `on_chain_th_substitution`, which legitimately calls `os.fsync`; the env-read predicates already caught every import style. r4 finding: widening the module set to subpackages exposed a leftover `node.module == "os"` ImportFrom clause that false-failed `persisting/excel_utils`'s legitimate `from os import PathLike`; rescoped the clause to the env-read alias names only. Widening a guard's module set can surface latent over-firing predicates; re-scope every clause to the prohibited names, not the source module.

---

## 126. Assert the Callee's Call Shape Against a Raw Double, Not Against a Shape the Double Itself Constructed

**Principle:** Family H. A recording test double that formats or filters the kwargs it records can mirror the assertion back at itself; the test then verifies the double, not the production caller.

**Trigger:** A test asserts the exact kwargs keys/values a production function passed to an injected double.

**Rule:** The double must be minimal and raw: `def _fetch(**kwargs): calls.append(kwargs)`. Assert `set(calls[0]) == {...}` (or the values) directly on what the caller supplied, with no transformation between the call site and the recorded list.

**Example:** r3 finding in `tests/unit/application/test_main_on_chain_wiring.py` (`test_runs_when_fetch_injected`): the shared `_recording_fetch` helper made the kwargs assertion tautological; a local raw-kwargs double exposed the orchestrator's actual call shape (`{"year", "output_dir"}`).

## 127. Canary Tests for Env-Gated External Fetchers Replace the Fetcher, Not the Data Source

**Principle:** Family C. When a canary test proves that an env-gated external collaborator degrades safely, exercising the REAL collaborator would itself perform the forbidden access (open the personal-data registry, hit the network); the canary must fake at the collaborator boundary and pin the degrade contract, while naming the autouse fixture that keeps the real collaborator out of tests.

**Trigger:** Writing a test that sets the production env gate (e.g. an API key) and drives the real composition root to observe "the fetch aborts under test guards".

**Rule:** Replace only the external-collaborator function (at the composition-root module it is bound from) with a double that records its kwargs and raises a sentinel error; assert (a) the injected call happened exactly once with the config-derived year, (b) the broad-`except` degrade WARNING names the sentinel error, and (c) no artifacts were written. Never let the real collaborator run just to see the guards bite: its FIRST operation may be the personal-data read the suite forbids, and the degrade handler swallows the guard exception quietly anyway. State in the docstring which autouse fixture is the actual gate for the real path.

**Example:** `test_set_key_fetch_invoked_and_degrades` (tests/unit/application/test_main_composition_root.py): with `BERA_CHAIN_API_KEY` set and real `_main` + real `run_report`, `run_on_chain_fetch` is replaced because its first op opens the gitignored wallet registry; the aborting fake pins the DI-1 WARNING and the absence of `bera_transactions.csv`, and the docstring names `_pin_hermetic_env` (tests/conftest.py) as the gate keeping the real fetcher out.

**See also:** lesson #123 (hermeticity guards); AGENTS.md Testing section (the env-pin autouse note).

## 128. Plan-Embedded Forbidden-Pattern Greps Must Be Self-Match Immune

**Principle:** Family H (verify the real thing, not the abstraction). A validation command inside a plan file that greps for a forbidden literal (e.g. a renamed artifact) matches the plan's own command text once the plan is committed, so the gate exits 1 forever. Bracket-escape one character in the pattern literal (`artifact[.]yaml`, not `artifact.yaml`) so the document's own escaped text cannot satisfy the regex while genuine stale references still match; note beside the command that the escape is intentional so nobody "normalizes" it; verify the gate against the tracked state (intent-to-add) rather than the working tree. Witness: validation-harness plan review r2 found the `.yaml` sweep gate self-matching the plan's own line after `git add -N` simulation. See plans-skill Validation Commands authoring rules; user-level lessons #204.

The same immunity applies to prose inside the guarded files: a docstring or comment asserting a pattern's absence must not quote the deny literal verbatim (write "DictReader-based CSV parsing", not the full dotted import), or the guarded file trips its own gate. Witness: an on-chain comparator module docstring quoted the denied reader literal while asserting its absence; rephrased before the gate ran.

## 129. Project-corpus citations use prose, never the user-corpus token

**Principle:** Family H (verify the real thing, not the abstraction). A citation token that is canonical in the user-level corpus is a reserved word in the project corpus; the file-independence conformance test enforces this, but only in a suite run.

**Trigger:** A session appends to or edits `docs/maintenance/development_lessons.md` (a `learn` capture or a plan-authoring commit that records a lesson), especially when cross-referencing a user-level lesson.

**Rule:** In the project corpus, cite user-level lessons as prose (`user-level lessons #N`), never the raw user-corpus token `UL[#]N` (bracket escape intentional per lesson #128: this corpus must not contain the forbidden substring, not even inside this lesson). Before committing any edit to the corpus file, run `uv run pytest tests/unit/test_lessons_corpus_conformance.py`; "docs-only commit" is not a test-skip reason when a pure-file assertion covers the edited file. A full-suite run that PREDATES the final content edit covers nothing about the commit: the gate must run on the post-edit tree, however cheap the tier.

**Example:** A plan-authoring commit appended project lesson #128 ending with a raw user-corpus citation; the suite went red on `test_project_file_independence` only at the next implementation task's full-suite gate, forcing an out-of-scope one-token fix unrelated to that task. Repeated 2026-08-22 despite this lesson: the full suite ran GREEN immediately BEFORE appending lesson #136 (which cited the user corpus token), the commit went in without re-running any gate on the post-edit tree, and the red suite surfaced only when a plan-review sub-agent measured it three turns later - a pre-edit green run is not post-edit verification, and the tier that covers the edited file costs under a second.

## 130. Block-Count Assertions Anchor to a Per-Block Unique Line

**Principle:** Family H (verify the real thing, not the abstraction). A test that counts how many structural blocks a generated text file contains must not count the block-opening marker literal: the file's own header/help template legitimately documents the marker in prose, so the count measures documentation plus blocks.

**Trigger:** Asserting the number of rendered template blocks (TOML arrays of tables, INI sections, fenced blocks) in a file whose header comment explains the format and mentions the marker by name.

**Rule:** Key the count to a substring only a real rendered block contains (its identifying key line, e.g. `signature = "<expected-id>"`), never to the marker literal. An exact-equality count false-fails (header mention plus one block = 2 vs 1); a `>= 1` count false-passes when zero real blocks exist but the header mentions the marker. Both modes disappear when the anchor is the per-block unique line.

**Example:** A dispositions-file test asserted `text.count("[[clusters]]") == 1` after appending one cluster block; the file header reads "appends one [[clusters]] template block", so the count returned 2 and the test failed despite exactly one block existing. Re-keying the assertion to the block's `signature = "<SIG>"` line fixed it without touching the implementation.

**See also:** lesson #128 (deny-direction self-match immunity via bracket-escaping; here escaping is wrong because real blocks must match); user-level lessons #204; AGENTS.md Testing (structural identification over hardcoded value exclusions).

## 131. Interrupted TDD Tasks Recover RED Evidence in a HEAD Worktree

**Principle:** Family H (verify the real thing, not the abstraction). RED evidence is an observed failure of each new test at the pre-change baseline, not a narrative claim. When a TDD implement step is interrupted after GREEN-phase production edits are applied, the working tree can no longer produce that observation; the relaunch must neither skip RED nor reset the tree to fake it.

**Trigger:** Taking over an interrupted TDD task (quota cutoff, crash) whose working tree already mixes new tests with production changes and whose implement log records no RED run.

**Rule:** First audit the partial tree per file against HEAD (`git diff <file>`), classifying each task file COMPLETE or PARTIAL before writing anything. Then recover RED mechanically: `git worktree add <tmp> HEAD`, copy ONLY the new/modified test files in, run the new tests there; each new-behavior test must fail for the expected reason and negative clauses must pass; `git worktree remove --force <tmp>` and confirm the main tree is untouched. Never `git stash` and never reset the working tree to obtain RED.

**Example:** Task 8 of the 2026-08-18 on-chain validation harness plan: the predecessor was interrupted after applying loader/processor changes, leaving no RED evidence and a processor calling helpers that were never defined. The relaunch audited all task files, then proved RED at HEAD with only the three test files copied into a temp worktree: 6 failed for the exact expected reasons, 47 passed, both negative clauses green.

**See also:** lesson #27 (TDD RED then GREEN), lesson #46 (revert the guarded change and confirm the test fails; the worktree is the safe mechanism when that change is uncommitted and interleaved), lesson #71 (worktree ops can revert the main index; use a temp path and verify the tree afterwards), user-level lessons #69 (worktree over stash for transient clean trees).

## 132. Check the HEAD Blob Is Format-Clean Before Running the Formatter

**Principle:** Family H (verify the real thing, not the abstraction), sibling of #72. A linter reports; a formatter rewrites. When formatting is unenforced (no CI/pre-commit), the committed baseline drifts from the current formatter version, so formatting a touched file rewrites large regions of pre-existing code the task never touched.

**Trigger:** About to run an auto-formatting command (`ruff format`) over a file with uncommitted changes in a repo whose formatting is not CI-enforced.

**Rule:** First verify the file's HEAD blob is already format-clean under the installed tool version (`git show HEAD:<file> | uv run ruff format --check -`; a non-zero exit means the baseline itself is not format-clean). If it is not, do not run the formatter; hand-format only your own hunks, matching surrounding style. If churn already happened, reset the file to HEAD and re-apply only the intended hunks, comparing blob hashes where an audit snapshot exists, then re-run the suite.

**Example:** Task 8 of the 2026-08-18 on-chain validation harness plan: `uv run ruff format` churned about 200 pre-existing lines across two files whose HEAD blobs themselves would be rewritten by the current formatter (tool-version drift; the repo does not enforce formatting). Recovery: reset both files to HEAD, re-apply the intended hunks by hand, confirm one restored file's blob hash matched the pre-format audit; full suite stayed green.

**Witness (recurrence, 2026-08-24 bera-unknown-followups review r4 fixes):** `uv run ruff format` on two edited files churned ~150-480 pre-existing unformatted lines each; both HEAD blobs fail `ruff format --check`. Same recovery: `git checkout --` both files, re-apply only the intended edits, validate with `ruff check` instead.

**See also:** lesson #72 (`ruff check` on the HEAD blob for `# noqa` attribution; same unenforced-baseline root cause, reporting tool vs this mutating-tool failure mode); user-level lessons #68 (auto-fix rewriting re-export import blocks).

## 133. Tasks Changing Behavior After the Plan's Doc Task Re-Sweep Layer 2 Docs

**Principle:** Family D (single source of truth) - the code is the source and the Layer 2 doc is a view; a documentation task earlier in the same plan pins only the view that existed when it ran.

**Trigger:** Implementing a plan task that changes a module's runtime behavior (new rules, changed semantics) when an EARLIER task in the same plan already wrote or updated the Layer 2 doc describing that module.

**Rule:** A behavior-changing task must sweep the Layer 2 docs (`docs/maintenance/`, `docs/architecture/`, `README.md`) for the module's behavior description in the SAME task, not only the plan file. The doc task's checked `[x]` and the current task's Files list naming only the plan file are not evidence the Layer 2 docs are current; the later task's edits are exactly what invalidated them.

**Example:** Task 10 of the 2026-08-18 on-chain validation harness plan wrote `docs/maintenance/on_chain_validation.md` describing the comparator's PD-010 equivalence rules. Task 11 (real-data walk-forward tuning) then landed four comparator rendering-variance rules (ticker-case folding, mirrored-row single counting, gas-folded native amount, compatibility widening), updating the module docstring and the plan outcomes but NOT the maintenance doc - its Compare step still described the pre-tuning semantics. Caught in the Task-11 `done` verification pass and fixed there (rendering-variance paragraph added to the Compare step).

**See also:** AGENTS.md doc-hierarchy rule ("Update in-session when behavior or rules change"); the doc-drift grep backstops (lessons #55, #58, #70 - rendered-value sweeps; this is the plan-sequencing analog: the sweep must be re-run by whichever LATER task invalidates the doc).

## 134. Two-Source Total Disagreement: Compare Underlying Record Cardinality Before Ruling a Side Wrong

**Principle:** Family H (verify the real thing, not the abstraction). The real thing is the per-key record count on both sides; an aggregate total, a ratio, or a plausibility argument about the other side's aggregation is the abstraction.

**Trigger:** Two independent sources report different totals for the same entity (per-tx reward sums, per-day volumes, per-symbol amounts) and the drafting instinct is to hedge between "our side dropped something" and "their side merged something".

**Rule:** When sources disagree on a total, count the underlying records per key on BOTH sides before writing a root cause. A source returning FEWER records for the same key is incomplete, not wrong about arithmetic; a source carrying MORE records for the same on-chain key cannot plausibly have invented them. A per-row-scaled tolerance also leaks the counterparty's row count - read it as cardinality evidence. Disposition against the short side's fetch path, and verify the mechanism with one direct query (production reader on the source file) before committing the root-cause wording.

**Why:** The first draft of the 2025 claim-cluster root cause hedged "Koinly merged two claims (or our side dropped a leg)" - both branches looked plausible from the amounts alone.

**Shape:** Ours-roughly-X%-below-theirs across several assets in one entity, with no constant ratio (a constant ratio would suggest a fee or rounding rule instead).

**Example:** The 2025 on-chain-vs-Koinly validation: our per-asset claim sums ran ~25-35% below Koinly's. Per-tx comparison: the export carried 81 legs where Koinly had 101 rows for the same tx hash (18 eWBERA-4 and both sWBERA transfers absent, same receiving wallet) - fetch-side per-transaction truncation, settled in one query. Sibling of #116 (history-level `max_rows` truncation ceiling); this is per-transaction completeness.

**See also:** #116 (block-0 pagination ceiling); the harness's tolerance-scaling rule (`DISPLAY_TOLERANCE_PER_ROW * koinly_rows_in_bucket`) documented in `on_chain_validation.md`.

## 135. Append-Only Decision Files: Every Block Must State Its Current Status Accurately

**Principle:** Family D (single source of truth). The disposition/status field is the block's truth; a template comment baked in at append time becomes a second source that drifts silently when analysis or rules change.

**Trigger:** A harness appends template blocks to a human-facing append-only file (dispositions TOML, review ledgers) and the template comment carries a default proposal; later analysis revises proposals, families stop occurring, or decisions get recorded by other routes.

**Rule:**
1. Template comments never bake in a default proposal value; they carry status words that stay true ("awaiting ruling") or nothing.
2. When a block's reality changes, update its comment/status text in the same pass: append-only protects CONTENT and rulings, not stale labels.
3. Non-occurring blocks get an explicit "no ruling needed" marker so the reader's attention funnels to open items; the file owner asked to see ONLY what genuinely needs input.
4. Appended empty blocks for NEW signatures carry no explanation by default - the pass that drafts root causes owns filling them with plain-English evidence.

**Why:** The file owner opened the dispositions TOML after a re-run, saw the identical stale `# PROPOSED: acceptable_difference` comment on every drafted block (including blocks actually proposing missing_rule), found newly appended blocks empty, and concluded the file was untouched and misleading.

**Shape:** A human-facing register where re-runs change nothing visually (append-only) AND every block carries the same boilerplate comment.

**Example:** The 2025 dispositions TOML rebuild: accurate per-block proposals, plain-English root causes, "not occurring - no ruling needed" markers on dead blocks, `agent-decided` markers with evidence, and a header explaining the append-only mechanics plus where sample evidence lives (`on_chain_validation.md`).

**See also:** `on_chain_validation.md` (Disposition vocabulary and the decision-authority delegation); coding_guidelines #6 (user-facing labels self-explanatory - this is the register-file analog).

## 136. Aggregator Token Labels Are Temporal Views: Anchor Identity on the Contract

**Principle:** Family D (Single source of truth) - the token contract's address and its declared `symbol()`/`name()` are the identity source; a third-party aggregator/explorer label (Etherscan `tokenSymbol`, Koinly currency) is a view over that source and can be re-served differently over time, even for an unchanged contract address.

**Trigger:** Any join, alias, or user-facing rendering keyed on a token ticker that originates from an external report or explorer export, especially when comparing two exports fetched at different times (a re-fetch after a fix, a fresh validation baseline), or when a previously-matching comparison suddenly degrades with "on-chain X vs Koinly 0" half-empty buckets on BOTH assets.

**Rule:**
1. Treat third-party ticker labels as temporal. The same contract address can carry different labels across fetches: the 2026-08-22 Etherscan metadata refresh renamed `0xfcbd14dc...` from HONEY to BUSD between two fetches three weeks apart (313 rows relabeled with no data change).
2. When a label-keyed join degrades after a re-fetch, scope the change with a full-row multiset diff (Counter over full-row tuples, diffed both directions; count-equality can conceal whole-row relabeling), then query the contract itself (`eth_call symbol()`/`name()`) for ground truth before blaming either side.
3. Bridge stale-vs-current labels with an evidenced alias-table entry (per-contract evidence: address unique in the dataset, per-tx amounts equal once merged; `_ISSUER_TICKER_ALIASES`, PD-010 amendment #3), and keep the fail-loud ticker-collision guard as the backstop when an alias would merge two contracts.
4. Production identity stays address-keyed (CSV `token_address`, LP snapshot, chain registry); label aliases live only in the validation comparator.

**Example:** The pagination-drain re-fetch (2026-08-22) recovered 84 missing legs but matched DROPPED 300 -> 275: the same refresh that accompanied the re-fetch window relabeled the stablecoin contract, splitting equal per-tx amounts into complementary HONEY/BUSD half-empty buckets. `eth_call` proved the contract now declares BUSD ("Bera USD"); the issuer-rename alias entry recovered matched to 303 and closed the claim cluster.

**See also:** #134 (compare cardinality before ruling a side wrong); `docs/maintenance/on_chain_validation.md` comparator rules (issuer ticker aliases); PD-010 amendment #3 in `project-decisions.md`.

## 137. Routing-Contract Gates Must Scan Carrier Legs; Validate on Real Data

**Principle:** Family H (verified the abstraction, not the real thing). A routing rule derived from a real residual must be validated against that residual's actual leg structure; a synthetic positive test that simplifies the shape passes GREEN while the rule never fires on the data that motivated it.

**Trigger:** Writing a classifier/matcher gate keyed on a counterparty address (registry member, allow-list) for transactions where a router contract spends gas; declaring a "still occurring" gate closed after a code fix.

**Rule:**
1. When membership is inferred from a recipient address, scan ALL out-direction legs including the zero-value native gas carrier (the tx-level `to`), not only economic legs: routing/target contracts often appear solely as the carrier recipient while the economic legs go to pools.
2. Derive the positive test fixture from the real transaction's actual leg list (or re-run the harness) before declaring the gate closed; a synthetic shape that differs in one routing detail is a false GREEN.
3. Name the gate scope in the dispatch-order docstring in the same change when a shape slot's semantics widen.

**Why:** Pass 1 of the zap-deposit rule checked only the single economic leg's recipient (the AMM pool, not a member) and passed RED/GREEN on a synthetic fixture, yet the harness still reported the signature occurring; the registry-member vault was only the carrier leg's recipient.

**Shape:** GREEN unit tests plus a still-failing end-to-end occurrence gate after a "fix".

**Example:** The 2026-08-23 Unknown-family residual: a zap deposit whose BUSD leg went to a non-member pool and whose zero-value BERA carrier leg went to the position-NFT vault; extending the gate to `_any_out_leg_recipient_is_registry_member(legs)` over the unfiltered leg list closed the signature (final harness: zero of 8 still occurring).

**See also:** #136 (anchor identity on the contract); `docs/maintenance/on_chain_validation.md` harness gate semantics; AGENTS.md section 3 (on-chain TH validation harness is user-run).

## 138. Pagination Drain Loops Keep a Termination Guarantee When Switching Dedup Strategy

**Principle:** Family A (silently wrong result accepted). Replacing the termination mechanism of a loop (dedup-by-identity instead of positional slicing) also removes its only no-progress bound; any input where the new key collapses to one value turns the loop unbounded.

**Trigger:** Editing a positional pagination drain (slice-while-nonempty over an ordered client API) to deduplicate by a per-row identity tuple instead, or building synthetic test rows for such a loop via a row-helper that fills only the fields the test asserts on.

**Rule:**
1. A pagination loop must retain an explicit termination guarantee (no-progress break or `max_rows` cap) independent of the dedup key; the dedup strategy only narrows what is consumed, never what stops the loop.
2. Synthetic test rows for a loop keyed on row identity must populate the identity fields production rows carry; otherwise every fixture row collapses to one key and exercises a code path production never takes.
3. A loop that both accumulates memory and logs per iteration is a memory-amplification hazard: run the new fixture under pytest with a timeout before declaring the change safe.

**Why:** The 2026-08-23 review-fix switched the block-boundary drain to identity dedup; the test row-helper omitted identity fields, so all rows shared one identity tuple, the queue never drained, and the WARNING-per-row accumulation exceeded 20 GB under pytest and forced a machine reboot. The revert restored positional slicing while keeping the parse guard and a no-progress guard.

**Shape:** A "more correct dedup" refactor plus a test run that hangs or balloons memory instead of failing.

**See also:** #59 (fixture values at production column indices); the `_drain_boundary_block` docstring in `src/tax_reporting/infrastructure/on_chain/etherscan_client.py` (identity-dedup deferred until fixtures carry real identity fields).

## 139. Data-Registry Provenance Outranks a Coarse User Design Decision in Plans

**Principle:** Family D (single source of truth). A gitignored data registry's per-entry `provenance` field records the ground-truth classification contract for that entry; a user's coarse plan-level design decision cannot silently widen it. When the two conflict, the plan must encode a discriminating rule and surface the refinement to the user, not pick one.

**Trigger:** Writing a plan task that changes a classifier rule gated on a data registry (position-token registry, LP snapshot, origin mappings) based on an abstract design decision, without re-reading the registry entries' provenance text.

**Rule:**
1. Before a plan task widens a registry-gated rule, read every registry entry's `provenance` and check none of them states a narrower intended semantics (e.g. "identity data, not a per-cluster rule").
2. If a provenance statement conflicts with the requested widening, split the rule on a discriminating signal (e.g. vault-target vs counterparty match) so existing baseline classifications are preserved, and report the refinement to the user for veto.

**Why:** The 2026-08-23 follow-ups plan encoded a user decision "LST unstakes classify LiquidityWithdraw" as a counterparty-match rule; the registry's LBGT entry provenance explicitly said its bidirectional exchanges classify via the existing Swap shape. The counterparty rule would have silently reclassified that 8-tx baseline family; the plan-review round caught it and the rule was split on a vault-target discriminator.

**Shape:** A plan review finding that a new rule changes classification of existing baseline records the registry already documents differently.

**See also:** #136 (aggregator labels are temporal views; anchor identity on the contract); AGENTS.md "wallet labels are discovery hints only" constraint.

## 140. Asserting CLI Logging Output: caplog Is Dead After `configure_application_logging` Clears Root Handlers

**Principle:** Family H (Verify the real thing, not the abstraction). pytest's `caplog` works by attaching its own capture handler to the root logger; any code path that calls `configure_application_logging()` (the `cli()` entry does) CLEARS root handlers, dropping caplog's handler mid-test, so `caplog.records` ends up empty and the assertion fails with "got 0". caplog is not merely bypassed here (as in #66); it is actively destroyed by the code under test.

**Trigger:** Writing a test that invokes `cli()` (or anything calling `configure_application_logging`) and asserts on a log record, and reaching for `caplog.at_level(...)` / `caplog.records`.

**Rule:**
1. For tests that exercise `cli()`, assert logging output by reading the tmp-cwd log file (`logs/tax-reporting.log` under `tmp_path`), not via `caplog`. Follow the existing idiom of the file-not-found CLI test.
2. If a console StreamHandler mirrors the record to stdout, do NOT also assert the traceback text is absent from stdout; the design legitimately mirrors it there. Guard the actual contract instead (e.g. `pytest.raises(SystemExit)` with the exit code; no exception propagating out of `cli()`).

**Why:** During the 2026-08-23 validation-CLI crash-wrapper task, the crash test initially used `caplog`; `configure_application_logging` had cleared root handlers and the `logger.exception` record was only observable in the log file. Drafted negative stdout assertions also contradicted the logging design (StreamHandler mirrors the record), so they were dropped in favor of the SystemExit assertion.

**Shape:** A CLI-level test where `caplog.records` is empty despite production logging demonstrably firing.

**See also:** #66 (caplog bypasses logging config; assert production-call-site file contents); #68 (caplog `rec.name` filter mismatch).

## 141. Coverage Gates Over Matched Sets: ANY-Match Fails Open on Mixed Batches

**Principle:** Family B (Error-policy propagation): a coverage gate whose degraded state is "silently clean" is an error-policy hole; unmatched items must surface, not pass. A coverage gate written as set-intersection ANY-match (`covered & required`) declares a batch clean when ONE required item is covered, even while sibling items remain unmatched; the correct predicate is subset (`required - covered == empty`). Missing identifiers on either side must NOT be filtered symmetrically: filtering both sets makes an all-missing batch vacuously clean (fail-open); keep a non-coverable sentinel on the required side.

**Trigger:** Writing or reviewing a "all counterparties matched, else review-flag" gate over per-row address/identifier sets where some identifiers may be absent or unnormalizable.

**Rule:**
1. Express coverage as subset semantics: `unmatched = required - covered`; clean iff empty; the review reason must name the uncovered items.
2. Exclude missing identifiers from the covering set, but keep a `"<missing>"` sentinel in the required set so absent values are never coverable.
3. When a review finding proposes a literal fix, re-derive it against the CURRENT semantics if a sibling fix in the same round already changed the matching rule (a "filter both sets" fix written against ANY-match fails open once subset semantics land).

**Why:** The on-chain shape-6 LP-member gate used `member_recipients & in_senders` ANY-match, so a mixed batch (one vault-covered leg, one uncovered leg) passed clean with no review flag. Review r1 F2 switched to subset semantics; F3's literal suggested fix (filter BOTH sets of missing addresses) was rejected because it would have made an all-missing-recipient transaction vacuously clean; the fail-closed sentinel was implemented instead.

**Shape:** A gate whose boolean comes from set intersection rather than difference; a RED test where a batch with one covered and one uncovered item passes clean.

**Scope confirmation (2026-08-24 r2 of the 2026-08-23 on-chain plan):** the ANY-match hole had a SIBLING branch: the registry-member leg of the same shape-6 dispatch still used `any()` after the r1 LP-side fix landed, so a mixed registry batch (one vault-target leg + one DEX-pair leg) again passed clean. When a review fix corrects one branch of a symmetric dispatch, grep the sibling branches for the same predicate in the SAME round (per AGENTS.md "sibling aggregators use byte-identical patterns"). The sentinel itself was also spoofable: the source reader does no format validation, so a raw field containing the literal `<missing>` string could self-cover; the covering-set exclusion now rejects both `""` and the sentinel literal. Fix shape: fire the gate only on a vault-target leg (preserving the single-leg fall-through characterization), compute non-vault recipients over the member legs, and flag with a disposal-worded WARNING naming them. Same family, no new lesson.

**Scope confirmation (2026-08-24 r3 of the same plan):** the family crossed a branch boundary a third time: the LP-member dispatch branch `return`s before the registry-member branch runs, so once the LP subset predicate was satisfied, a same-transaction registry-member leg to a non-vault recipient passed clean with the registry gate never consulted. When a symmetric dispatch has EARLY-RETURN branches, a fix in one branch must re-derive coverage for inputs whose legs span BOTH branches (mixed batches), not just per-branch inputs; the fix folds registry-member non-vault out-legs into the LP branch's review computation so clean requires both predicates.

**See also:** AGENTS.md "Verification/hygiene guards must fail closed"; #106 (sentinel selection when a value is valid); AGENTS.md "sibling aggregators use byte-identical patterns or a shared helper".

## 142. Assert on Structured Message Delimiters, Not Prose Parentheticals

**Principle:** Family B (Error-policy propagation): a test that asserts on log/message text couples the suite to incidental wording; when a review fix rewords a message, the assertion breaks (or worse, silently stops testing the exclusion it pinned).

**Trigger:** Writing `assert "..." not in msg` / substring-parsing assertions against a WARNING/reason string that a later fix may reword.

**Rule:** When an assertion must extract a set from a message (e.g. the uncovered recipients a review reason names), parse between STABLE structured delimiters the message format guarantees (`label: ` before, ` received` after), never between a parenthetical aside and the next token; prefer asserting membership of the parsed set over the raw phrasing.

**Why:** The mixed-batch exclusion test split on the literal `" (in-leg senders"`, a parenthetical added by the r1 fix wording; review r3 F2 replaced it with `msg.split("recipient(s) ", 1)[1].split(" received", 1)[0]`, which survives rewording of the parenthetical while still verifying the same exclusion set.

**Shape:** A test regex/split key containing an opening parenthesis or punctuation that belongs to sentence prose, not a format contract.

**See also:** AGENTS.md "Review flags must give specific actionable explanations" (the reason text is free to change; the structured delimiters are the contract).

## 143. Prefer Early-Return Guards Over `assert` Narrowing in Production Helpers

**Principle:** Family B (error-policy propagation), sibling of the S101 lint intent. An `assert` used only to narrow `Optional` state for a type checker is a stripped-under-`-O` no-op guard and a full-ruleset lint violation (Ruff S101), not a contract.

**Trigger:** Adding a new helper inside production code that consumes an `Optional` field already gated `is not None` by both callers, and the draft uses `assert self.x is not None` to satisfy the type checker.

**Rule:** When the None case already has a defined behavior at the call sites (empty list, empty dict), give the helper its OWN early-return guard for that case (`if self.x is None: return <empty>`) instead of an `assert`; behavior is identical under the callers' gates and the guard survives `python -O`.

**Example (2026-08-24 bera-unknown-followups r4 F6):** extracting a shared non-vault-recipient predicate used by two dispatch branches, the first draft narrowed `self.position_registry` with `assert ... is not None` (Ruff S101); replaced with an early `return []`, byte-identical behavior under both callers' `is not None` gates.

**See also:** AGENTS.md Ruff section (full ruleset, unenforced); #132/#72 (check the HEAD blob before formatter/noqa decisions on the same files).

## 144. Derive Role-Polarity Test Expectations From the Production Helper

**Principle:** Family H (Verification discipline: intuition about sender/recipient polarity is an abstraction; the production direction helper is the real thing)

**Witness (2026-08-24, multi-leg projection plan review r3):** two nfttx decode test bullets in the plan asserted `from`=wallet -> `direction="in"` and `to`=wallet -> `direction="out"`, exactly inverted vs `bera_decoder._direction` (from=wallet -> out, to=wallet -> in). The bullets were drafted from mental polarity intuition while writing the plan; the helper that defines the mapping was one grep away and already had the answer.

1. When a plan's RED tests assert a role-polarity mapping (from/to, sender/recipient, source/target -> out/in, debit/credit), open the production helper that defines the mapping and transcribe its branches into the given/expects text before the review round does.
2. Add "reuse the shared helper" to the implement clause so the implementation and the tests cannot drift from the same source (Family D: one definition of the polarity).

## 145. A New Production Gitignored-Data Load Extends the Audit Guard's Reach Into Existing Real-Path Test Modules

**Principle:** Family H (verify the real thing). The always-on audit-hook guard scopes to whatever production code a test actually executes; adding a NEW production load of a gitignored per-user file silently re-scopes previously-clean test modules into the guarded set. The unit-tier patch fixtures of the task's own tests do not cover sibling integration modules that reach the same call via real (unmocked) paths.

**Trigger:** A task adds or wires a new production call that opens a gitignored data file (per-year registry, wallet config, personal export) into a module that existing tests already exercise for other behaviors.

**Rule:**
1. When wiring a new gitignored-file load into production, grep the test tree for modules that call the enclosing entry point via real paths (not patched), and add an autouse fixture in each patching the loader to an inline synthetic registry.
2. Never treat a green targeted-tier run as sufficient; the full-suite run is what fires the audit-hook guard and reveals the new reach.

**Why:** The 2026-08-24 multi-leg projection Task 3 added a per-year position-token registry load to the on-chain fetcher; `tests/integration/test_on_chain_fetch_integration.py` then opened the gitignored real registry through the real fetch path and the always-on audit guard failed the full suite (unit fetcher tests were clean because they patched the loader via the fake HTTP install). Fixed with an autouse hermetic-registry fixture in that integration module.

**Shape:** Full-suite failure in `test_on_chain_modules_do_not_open_personal_data` after a task that only added a data load, while the task's own targeted test set stays green.

**See also:** #123 (env-gated paths make tests machine-dependent; the guard family), #38 (tests must not read gitignored data directly), AGENTS.md Testing section (no gitignored-data opens; audit-hook).

## 146. Registry Membership Predicates Must Gate on the Registry's Kind Discriminator

**Principle:** Family F (classifier discriminators). A registry lookup that answers "is this token a member?" is an abstraction over the registry's real question, which is "is this token a member OF THE KIND the caller branches on?" Membership and kind are two predicates; conflating them lets entries of a sibling kind (here: LSTs in a position-token registry) route through a branch meant only for the gated kind.

**Trigger:** Any detector/classifier that branches on registry membership where the registry entries carry a kind/type field and the caller's semantics apply to only one kind.

**Rule:**
1. Registry accessor predicates must be kind-gated (`is_position_nft_token` checking `kind == "position_nft"`, mirroring the same discipline as `is_position_vault`), and callers use the kind-gate, never bare membership.
2. When review finds an overbroad predicate, add a RED test that drives a sibling-kind entry through the caller (a DEX receive of a registered LST) and asserts it stays on the un-gated path (Swap, not LiquidityDeposit).
3. Sweep prose (module docstring tables, detector docstrings, validation docs) in the same commit: "registry member" wording becomes "position-NFT-kind member".

**Why:** 2026-08-24 multi-leg projection review r2 F1: `_receives_position_token` gated on bare `is_position_token`, so DEX buys of registered LSTs (iBGT/LBGT) classified as LiquidityDeposit. The existing test covered only the OUT leg, hiding the receive-side gap. Fix: kind-gated `PositionTokenRegistry.is_position_nft_token` + 2 RED tests + prose sweep; deviation from the plan's literal "registry member by token_address" wording recorded (the plan's own Terms defined kind="position_nft").

**Shape:** A classifier test matrix where every fixture is the same kind as the branch under test; no sibling-kind row exercises the negative path.

**See also:** AGENTS.md Rule 1 (branch on the discriminator the upstream sets; UL #91), #144 (derive expectations from the production helper), the withholding-tax literal-match rule (same family: too-broad string/predicate match).

## 147. Degrade-Path Tests Must Pin Environment-Dependent Inputs, Not Rely on Absent Real Files

**Principle:** Family H (hermetic verification). A degrade/fallback test that lets production resolve a real environment path (repo root, per-year user file) is green only by accident of the machine: on a machine where the real file exists for that year, the degrade branch never runs and the test silently verifies nothing (or fails). Hermeticity here is about pinning the resolution input, not just the env var.

**Trigger:** A test exercises a "file missing -> warn and degrade" path whose file path is derived from the real repository root or another environment-dependent resolver, especially with a hardcoded year that may exist as a real gitignored file on some machines.

**Rule:**
1. In degrade-path tests, monkeypatch the path resolver (e.g. `find_repository_root`) to the test's `tmp_path` so the target file is provably absent, keeping the degrade branch deterministic on every machine.
2. Assert the WARNING text (unaffected), but never let the test's greenness depend on the real filesystem state of the developer's checkout.

**Why:** 2026-08-24 review r2 F2: `test_load_position_registry_degrades_with_warning` pinned year 2024 but let `find_repository_root` resolve the real repo root; green only because no 2024 registry existed locally while a 2025 one did (gitignored). Fixed by pinning the root to the empty `tmp_path`.

**Shape:** A fallback test that passes on the CI/agent shell and would take a different branch on a machine holding the real per-user file for the hardcoded year.

**See also:** #123 (env-gated paths make tests machine-dependent), #145 (audit-guard reach), AGENTS.md Testing section (hermetic suite contract).

## 148. Counterparty Classification Shapes Must Discriminate on the Counterparty Leg

**Principle:** Family F (classifier discriminators). An event-shape rule that routes to a counterparty-specific classification (deposit vs market trade) is an abstraction over the real question: WHO the counterparty is. Keying the shape only on the received asset conflates "received a position NFT" with "received it FROM the position vault"; the first is also true of an open-market purchase.

**Trigger:** A shape rule classifies an event by inspecting only the receipt legs (asset kind, amount pattern) while the target classification depends on the identity/kind of the paying counterparty.

**Rule:**
1. When a shape rule's classification encodes a counterparty relationship, add an explicit named helper that discriminates on the OUT (payer) leg (e.g. `_position_mint_pays_vault(out_legs)` keys on the counterparty being the vault), and gate the shape on it; absent registry entries fail closed (fall through to the review-bearing generic path, not the specialized one).
2. Add a RED integration test driving the same receipt asset through a NON-vault payer and assert the generic path (Swap), plus direct unit tests of the helper for both payer kinds.
3. When an external tool already labels the event, prefer the authority-settled invariant over the tool label when they conflict (here: settled LBGT out-side rule outrouted the shape-only shortcut).

**Why:** 2026-08-24 multi-leg projection review r3 F1: the shape-7 position-NFT signal keyed only on the receipt leg, so a market PURCHASE of a position NFT from a non-vault payer routed to the review-free LiquidityDeposit branch instead of Swap. Empirically verified on HEAD before fixing; fix mirrors the user-confirmed LBGT out-side rule (settled 2026-08-23).

**Shape:** A shape-rule test matrix whose every fixture has the same counterparty kind as the branch under test; no non-vault payer row exercises the fall-through.

**Scope confirmation (2026-08-24 r4 of the 2026-08-24 multi-leg projection plan):** the payer-leg discriminator itself had a mediation hole: a router/zapper-mediated mint pays a ROUTER (non-vault out-leg recipient) while the vault delivers the position NFT on the in-leg. Gating only on "out-leg pays the vault" misrouted those deposits to Swap. When a counterparty check fails on mediated flows, extend the helper to the counterpart leg's PROVENANCE (NFT received FROM the vault), not just the payment direction; name the helper for the disjunction (e.g. `_position_mint_touches_vault(out_legs, in_legs)`) and keep the residual (non-vault payment AND non-vault provenance) on the generic path as a legitimate market purchase, with no review flag. Fix also updated the shape table, shape-rule list, and validation-doc prose in the same pass.

**See also:** #146 (kind-gated registry predicates, same family), UL #91 (branch on the discriminator the upstream sets), AGENTS.md Rule 1 (discriminator branching).

## 149. Review Flags Must Persist Through Every Projection Boundary

**Principle:** Family D (indicator persistence). A review flag computed at an inner processing layer is only as good as its LAST persisted surface. If a downstream projection (adapter row, bridge CSV, merged report) reconstructs its own field set from scratch instead of carrying the reason, the flag dies at that boundary: the log ages out and the user-facing artifact shows an unexplained ambiguous row (PT-C-030 family).

**Trigger:** A domain object sets a review flag/reason, and a later layer serializes or re-projects that object into a user-facing artifact (row type, CSV, Excel) using a hand-built field list.

**Rule:**
1. When adding a review flag to a domain event, trace every projection boundary to the final user-facing surface and add the reason field to EACH layer's field set (domain dataclass -> projected row -> serializer cell), not just the layer that computes it.
2. Persist the reason for ALL flagged rows uniformly, not per-flag; empty string / None only for unflagged rows, preserving flag-off byte identity.
3. Reuse an existing user-facing cell (e.g. a free-text Description column) when one exists, rather than adding a column the downstream merge does not know.
4. Test at the outermost boundary: read the serialized artifact back via the production reader (not `csv.DictReader`; see UL #45) and assert the reason appears on flagged rows and absent on unflagged rows.

**Why:** 2026-08-24 multi-leg projection review r6 F1: `Event` carried no review fields; the processor logged the provenance-review reason then dropped it; the bridge CSV hardcoded an empty Description; ambiguous rows entered the substituted TH with no persistent indicator. Fix threaded `review_reason` (Event -> ProjectedThRow -> bridge/merged TH Description).

**Shape:** A processor method that computes a review reason inline in a `logger.warning` call while the row it emits has no corresponding field.

**See also:** PT-C-030 (review flags must be specific, not bare booleans), UL #45 (production reader for external-report CSVs), AGENTS.md Rule 1 (explicit indicators for partial/uncertain results).

## 150. Every Flagged Construction Site Must Pass a Reason

**Principle:** Family D (indicator persistence), producer side. A "flagged rows carry an actionable reason" guarantee is per-construction-site, not per-type: when several sites build the same object with the review flag set, fixing only the sites that already pass a reason leaves the flag-only sites persisting `review_reason=None`, rendering the flag indistinguishable from a clean row on the user surface.

**Trigger:** A dataclass has an optional `review_reason`, a review-fix guarantees flagged rows carry reasons, and grep shows multiple construction sites set the flag.

**Rule:**
1. Enumerate every site that constructs the object with the flag set (grep the builder and all its callers), not only sites already passing a reason.
2. Add a property-level test at the producing layer: every flagged instance carries a non-empty reason (a caplog-driven invariant pairs each flag WARNING with a reason-bearing row).
3. Collapse sibling flagged constructions over the same type into one shared helper so wording cannot drift.
4. Reasons name the concrete discriminator (addresses, missing gate, unverified sender) plus an action verb ("verify ... before filing").

**Why:** 2026-08-24 multi-leg projection review r7 F1: after r6 threaded `review_reason` through `Event`, four flagged construction sites (matched-no-pattern fallback, unknown-direction per-leg fallback, ungated multi-leg deposit, spam rewards) still built Events without `reason=`, so those flagged rows rendered an empty merged-TH Description.

**Shape:** grep of the builder call sites shows a mix of flagged constructions with and without a `reason` kwarg.

**See also:** lesson #149 (persistence through projection boundaries, downstream side), UL #91 (consumer-side reason synthesis: branch on the discriminator), PT-C-030.

## 151. Truncated personal tx-hash prefixes in tracked doc prose defeat full-width-hex PII scans

**Principle:** Family D (single source of truth: the purge set the standard; tracked prose must uphold it) x Family H (verify the real leak surface, not the convenient grep).

**Trigger:** A plan or other tracked document quotes "worked examples" from gitignored real-baseline artifacts (dispositions, registries, exports), and the diff is about to land on master via archive or squash.

**Rule:** PII scans for personal transaction hashes must ALSO match truncated forms (`0x` + 6-12 hex + `...`), not only full-width 40-hex literals; a truncated prefix of a personal tx is still the identifier class the history purge removed. Plan authors quoting real-baseline examples must withhold personal hashes at authoring time ("tx hash withheld, see the gitignored dispositions file") rather than relying on a later scrub. Before any archive/squash of a doc that quotes real baseline data, grep the diff for `0x[0-9a-fA-F]{6,12}\.\.\.` and check each hit against the gitignored sources and pre-existence on the base commit (public contracts like the BGT Distributor pre-exist and are fine).

**Why:** The multi-leg projection plan's worked examples quoted `0x...` truncated hashes from the gitignored dispositions; every full-width-hex scan passed clean, and the truncation also defeats prefix greps tuned to longer literals. The leak survived plan review, seven code-review rounds, and the archive commit; only the pre-squash recipe scan (cross-checking known-hash references) caught it, as new-to-master content the 2026-08-16 purge had specifically removed.

**Example:** `docs/history/plans/completed/2026-08-24-multi-leg-th-projection.md` quoted "tx `0xbc0d9b42...`" and "tx `0x377d40db...`" in its Gist worked examples. Neither existed on master; the squash would have reintroduced the purged identifier class. Fixed by replacing both with "tx hash withheld, see the gitignored dispositions file" (commit scrubbed pre-squash). The only remaining truncated hash in that diff (`0xd2f19a79...`) is the public BGT Distributor contract, pre-existing on master in three docs.

**See also:** the PII pre-push diff scan recipe (session memory), `coding_guidelines.md` hygiene patterns.

## 152. Narrating real-data findings in tracked docs is a PII surface

**Principle:** Family H (hygiene/PII guards cover every authored surface, not just code).

**Trigger:** writing validation/report narrative that references real personal transactions (hashes, amounts+dates, counterparties) into any TRACKED doc.

**Rule:** When narrating real-data findings in tracked docs, write identifiers withheld-by-default at authoring time ("tx hash withheld - see the gitignored dispositions file"), and run the pre-commit PII sweep over your PROSE edits, not just code/tests. The sweep for 6-12-hex truncated prefixes applies to doc text exactly as to source.

**Why:** The 2026-08-16 purge removed personal tx-hash identifiers from history; a review-loop narrative commit reintroduced an 8-hex prefix into the tracked backlog (caught by the r1 review panel, scrubbed same day). Amount+date+prefix jointly re-identify a purged tx even when no single field looks identifying.

**Shape:** you are editing docs/history or docs/maintenance text that summarizes a real-baseline run; the convenience of naming the tx feels harmless because the full hash is not present.

**Example:** Backlog FLIP-TIME WATCH prose cited a personal withdrawal by an 8-hex tx-hash prefix; the fix replaced it with a withheld-by-default phrase (the literal is intentionally not reproduced here). Lesson #151's purge precedent covers truncated prefixes; this lesson adds that NARRATIVE edits are the recurring entry path.

**See also:** #151 (truncated prefixes defeat full-width scans), #128 (self-match-immune greps).

## 153. Public-fact registries are committed, user files stay personal

**Principle:** Family D (single source of truth: duplicating public registry entries into a user file creates twin authorities that drift).

**Trigger:** designing any on-chain/address registry (bridged assets, CEX funding wallets, contract allowlists) and deciding committed vs gitignored user-owned.

**Rule:** Membership that is a public fact (canonical token/contract addresses, documented by the issuing protocols and archivable in crypto-origin) lives in the committed registry, provenance-cited (registry-level `source` plus per-entry note naming the origin document), and is agent-curated. The gitignored `resources/source/<year>/` file is an optional shadow override for entries not yet committed, never a duplicate of public entries. User-owned data stays the personal layer: chains.json wallets, the dispositions TOML, Koinly exports. A provenance rule (crypto-origin: archived documents, no auto-discovered guesses) bans unsourced data; it does not require user ownership.

**Why:** Citing a provenance rule to justify user ownership conflates curation with ownership (the 2026-08-27 user challenge on the bridge-asset registry plan). Public addresses duplicated into a user file shadow newer committed entries under first-match-wins resolution and rot silently; the user should maintain nothing derivable in-session.

**Shape:** a plan or loader that asks the user to supply addresses of widely known public protocols; a user-file population task whose entries are all public.

**Example:** The bridged-asset registry gate plan: the committed example file is the canonical production registry (fresh clones classify registered mints out of the box), and the gitignored user-registry population task was deleted (amended design confirmed by a full review panel plus a clean focused confirmation round).

**See also:** AGENTS.md §3 crypto-origin rules; #151/#152 (public contracts committable; self wallets and tx hashes never).
