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

See `~/Projects/.ai-playbook/python_guidelines.md` #1 for full prevention rules.
Repo context: Koinly `_TH_HEADER` has 20 columns; hand-counting commas is the biggest source of wasted debug iterations.


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


## 34. Never Write Temporary Artifacts to Tracked Folders

**Principle:** Repository hygiene.

**Trigger:** When creating a one-off scratch script or a temporary data file.

**Rule:** 
- Temporary artifacts (scratch files, throwaway scripts like `fix_data.py`) must never be placed in git-tracked folders like the project root.
- Use the dedicated git-ignored scratch folder (`{tmp_dir}`) or the system-provided scratch space.

**What happened (2026-06-26):** A temporary `fix_anexoj.py` script was created in the project root to perform bulk markdown edits, leaving untracked pollution in the git tree that required manual cleanup.

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

**What happened (2026-07-05 OGR event-level port, Task 1):** The legacy `_apply_ogr_direction_override` decided `direction_conflict` PURELY on sign - `(ogr < 0) != (cg < 0)` - and applied the `> 1 EUR` absolute-magnitude gate ONLY to the review flag (so trivially small conflicts do not produce a noisy "YES: ..." review row). When porting to `apply_ogr_event_level` (event-level aggregation), the first draft applied the `> 1 EUR` gate to the BRANCH decision too, treating sub-1-EUR sign conflicts as "agree". This broke `test_single_lot_conflict_byte_identical`: a CG +4.00 / OGR -1.00 event must take the conflict branch (final = -4.00, material), but the gated draft routed it to the agree branch and produced +4.00. The fix made `_decide_event_branch` sign-only and kept the `> 1 EUR` gate on the review flag via `_conflict_review_state` / `_agree_review_state`. See user-level #54 for the dual-decision structure (this lesson is the threshold-scope refinement that #54 does not state).

**Why this happens:** When a function is rewritten at a higher abstraction level, the porter reads the original top-to-bottom and tends to fold "similar-looking" checks together. A magnitude gate that reads `if abs(...) > 1 EUR` next to a sign check feels like a unified "is this significant?" guard, so the porter applies it to the branch condition as well as the flag. The original code's separation (sign = routing policy; magnitude = reporting/noise policy) is implicit and easy to collapse.

**Required behavior:**
1. Before porting, enumerate the decisions in the original function (routing, flagging, value selection) and, for each threshold gate, record WHICH decision(s) it gates by reading every branch the gate's result flows into.
2. Write that mapping as a comment on the new helper (e.g. `# branch decision is sign-only; the > 1 EUR gate applies only to the review flag`).
3. Add a byte-identical RED test for the boundary case (a sub-gate-magnitude conflict that the original routed to the conflict branch, not the agree branch) so a future collapse fails loudly.
4. In code review, treat "this draft added a magnitude check to a branch condition that the original made on sign alone" as a finding, even when the new test suite passes overall - the new tests may not include the boundary case.

**Distinguishing from Family C (sentinel vs None vs exception):** Family C is about how "absent/invalid" is represented differently across two consumers. This lesson is about a threshold whose SCOPE (which decision it controls) is the policy distinction that drifted, not the threshold's representation.

**See also:** User-level lesson #54 (OGR Directional Authority vs Wholesale Replacement - the dual-decision structure this refines), CLAUDE.md §4 Agent Workflow Rules (re-read each RED test against current design invariants before flipping GREEN).

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
