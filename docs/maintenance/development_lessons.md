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
