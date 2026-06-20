# Instructions

Guidance for coding agents (canonical `AGENTS.md`; `CLAUDE.md` is a symlink to it). Hard rules first; detail lives in `README.md` and `docs/`.

## Documentation Hierarchy

This repo follows a three-layer docs layout under `docs/`. Canonical schema: company guideline #48 plus the `doc-hierarchy-migrate` / `doc-hierarchy-upkeep` skills.

- **Start here:** `docs/README.md` (Layer 1 - concise overview; not a file catalog).
- **Facts / guidelines:** `repo_facts_rel` → `.ai-playbook/facts.md` (gitignored repo agent runtime); `project_guidelines_rel` → `docs/maintenance/project-guidelines.md`.
- **Shared knowledge (Layer 2):** `docs/architecture/` (seven topic overviews) and `docs/maintenance/` (crypto/tax guidelines, glossary, project decisions, decision-points and the tax-law archive under `docs/maintenance/tax/`). Update in the same session when behavior, contracts, or domain rules change.
- **Historical context (Layer 3):** `docs/history/` - reference only; active plans under `docs/history/plans/`, completed plans under `docs/history/plans/completed/`.
- **LLM-only:** `docs/tmp/` at root; gitignored `docs/history/reviews/` (review staging) and `docs/maintenance/personal/` (gitignored personal tax context) - not canonical human Layer 2.
- **Doc path resolution:** other skills resolve `{plans_dir}`, `{reviews_dir}`, `{tmp_dir}` from `.ai-playbook/facts.md` TOML (via `using-skills` Step 0), not from hardcoded defaults.
- **Instruction files:** `AGENTS.md` is canonical (`# Instructions`) for all agents; `CLAUDE.md` is a symlink (`ln -sf AGENTS.md CLAUDE.md`).

## Instruction Rules

### 1. Reusable Engineering Rules

- For numeric fields from external reports, detect thousands/decimal separators or fail clearly.
- Do not classify values with a leading zero integer part (e.g. `0,001`) as thousands-grouped.
- Treat exactly one dot-grouped triplet (e.g. `1.234`) as ambiguous and raise a clear error. Only multi-group dot patterns (e.g. `1.234.567`) may be stripped as European thousands.
- Use f-strings in exception constructors; never pass multiple positional args.
- Catch row-level parse errors per row (warn and skip). Do not let one bad row discard the whole dataset.
- When extracting a second derived value from an input parsed inside a `try ... except` block, reuse the parsed object inside the same block; re-invoking the parser outside it bypasses row-level handling. See `development_lessons.md` #106.
- When an optional field from external input is absent, use a type-safe sentinel (e.g. `"0"` for numeric fields) rather than `""`. See `coding_guidelines.md` #4.
- Data-loss conditions (unmatched items, dropped records) must be logged at warning+, never debug. See `coding_guidelines.md` #5.
- All-or-nothing validation for required file sets: none present -> skip gracefully; partial set -> raise `FileProcessingError` listing missing files; all present -> proceed. See `development_lessons.md` #51.
- Verification/hygiene guards that read a manifest/patterns file must fail closed when the manifest is absent: `grep -f <missing>` exits non-zero, so a `cmd && echo BAD || echo GOOD` form reports GOOD (a false pass) exactly when the guard cannot run, which is the default in CI when the manifest is gitignored. See `development_lessons.md` #126.
- Validation that depends on complete state runs post-aggregation, not per-row. Mid-accumulation state can be temporarily invalid (e.g. reversal arrives before dividend).
- When reusing a validation/security pattern, inherit the guards (symlink rejection, size limit) but recalibrate exception handling (degrade vs raise) to the cost of silent failure at the new call site. See `development_lessons.md` #105.
- Unmatched items from matching algorithms must never be silently discarded; apply an explicit fallback and log a warning.
- When an aggregator or detail-line renderer takes `entries[0]` for a field ASSUMED constant across a group (e.g., `annex_hint`, `operation_code`, `legal_category`), add a heterogeneity guard that warns when group members disagree. Silent assumption drift produces output that looks valid but is wrong. See `development_lessons.md` #118.
- Sibling aggregators in the same module that perform the same conceptual operation (e.g., merging narrative fields) must use byte-identical patterns or call a shared helper. Diverging patterns silently drop data in the diverging aggregator. See `development_lessons.md` #119.
- Partial or uncertain results must carry an explicit indicator so the user cannot mistake them for complete. Review flags must include specific actionable explanations, not bare booleans.
- User-facing output labels use self-explanatory terminology, not terse names inherited from source formats. See `coding_guidelines.md` #6. F-strings interpolating a `str | None` into user-facing text (review reasons, Excel cells) must degrade explicitly for `None` when it is reachable via a warn-only config-drift path; see `development_lessons.md` #131.

### 2. Repository Style and Conventions

- Specific type annotations for generic collections (`list[Type] | None`, not `list | None`). See `development_lessons.md` #8.
- Catch specific exception types (`FileProcessingError`, `ValueError`), not broad `Exception`. See `development_lessons.md` #9.
- Koinly source discovery is year-agnostic (`koinly*`) and prefers a year matching parsed IB data.
- If an inferred IB tax year exists and the selected Koinly directory year differs, skip crypto loading for that run.
- Dividend aggregation validates one currency per symbol; mismatches raise `FileProcessingError`.
- `TradeDate` is a `NamedTuple(year, month, day)`. Do not call `.date()` on it; use it directly or call `.to_datetime()`.
- When classifying a dividend row as withholding tax, match only the literal `"Withholding Tax"`; never bare `"Tax"` (dividend descriptions contain "Tax" as a word fragment, e.g. "Tax-Exempt Interest").
- `docs/maintenance/tax/.../official/` keeps only source-origin files; derived notes and numbered guidance belong outside `official/`; `sources.md` records issuing/effective/superseded dates. See `docs/maintenance/project-guidelines.md` #1.
- For external source archive provenance and freshness checks, see `docs/maintenance/project-guidelines.md` #1.
- For fiscal-year versioned tax decision points, see `docs/maintenance/project-guidelines.md` #2.
- When AT guidance cites a CIRS paragraph number, verify against the consolidated CIRS PDF; AT documents may predate renumbering amendments. See `docs/maintenance/project-guidelines.md` #3.
- For tax/origin web sources, prefer authoritative PDFs or extracted Markdown/PDF over raw HTML; reuse local mirrors.
- Before assuming an official source is unavailable, probe the issuing authority's canonical URL with a HEAD request. See `development_lessons.md` #98.
- Under `docs/maintenance/tax/`, use `laws/<jurisdiction>/crypto-tax/` for tax-law archives and `crypto-origin/` for chain/operator domicile archives.
- Adding a boolean flag to `docs/maintenance/tax/decision_points/<year>.toml` requires the corresponding field on `TaxJurisdictionConfig` in `domain/jurisdiction.py`. See `development_lessons.md` #68.
- When a `docs/maintenance/tax/decision_points/<year>.md` entry enumerates a rule as N-tier/N-case, verify the enumeration (count and cases) matches the implemented code branches; update the prose when a branch is added or changed. See `development_lessons.md` #123.
- Share crypto `País da Fonte` resolution across rewards and capital gains. Never use taxpayer residence.
- Keep `docs/maintenance/tax/crypto-origin/` source manifest, registry, and decision log synchronized when changing chain/operator mappings.
- Chain derivation uses deterministic normalization and validates against trusted sources in `docs/maintenance/tax/crypto-origin/`.
- Wallet labels are discovery hints only; final chain/country mappings come from archived operator origin documents.
- When wallet labels don't allow reasonable chain derivation, use `Unknown` explicitly rather than guessing from asset symbols.
- Operator mapping temporal validity: `service_start_date` = when the platform started offering this service (matching); `valid_from` = when this mapping was verified from source documents (audit). Set `service_start_date` before `valid_from` when both known; for unknown verification dates, set `service_start_date` and leave `valid_from` null.
- Module size: when a module exceeds 1,000 lines or 50 functions/classes, extract cohesive responsibilities into separate modules. See `development_lessons.md` #87, #88.
- Orchestration layers stay thin (~500 lines max); extract sub-orchestrators or move domain logic to dedicated services when coordination grows. See `development_lessons.md` #87.

### 3. Repository Constraints

- Optional crypto ingestion is non-blocking: missing/mismatched-year/unparseable Koinly input emits a warning and continues IB report generation without crypto data.
- Partially-unmatched sells (FIFO exhausts all buys before all sells are consumed) must never be silently dropped. Apply the placeholder-buy mechanism to the remaining sell quantity, log at `logger.warning`, and include the resulting capital gain line.
- Partially-matched buys written to the rollover CSV use proportional fee: `proportional_fee = action.fee * (rolled_quantity / original_quantity)`.
- Dividend per-symbol validation runs after all rows for all symbols are accumulated, not per row. Symbols that fail post-accumulation validation are skipped with `logger.warning`; they must not abort other symbols.
- Aggregate crypto capital gains by `(disposal_date, asset, platform, holding_period)` before reporting. Do not bypass `_aggregate_capital_entries()`.
- After aggregation, exclude entries where `|gain/loss| < 1 EUR`. Do not remove `_filter_immaterial_entries()` or parameterize `_MATERIALITY_THRESHOLD` without a `crypto_rules.md` update.
- Crypto reward income must be aggregated by `(income_code, source_country)` before inclusion in the IRS-ready filing table. Do not bypass `aggregate_taxable_rewards()`.
- Reward classification into taxable_now vs deferred_by_law must use `_classify_reward_tax_status()` and cite CRG-001/CRG-002.
- Taxable-now crypto-origin fiat rewards must be validated and aggregated before inclusion in `Reporting` under `OTHER CAPITAL INVESTMENT INCOME`. The `Crypto Supplementary` worksheet retains support detail for both taxable-now and deferred rewards but is not a filing target. See SRG-008.
- The aggregation step fails with `FileProcessingError` if any taxable-now row cannot be assigned all mandatory IRS fields (valid Tabela X country code).
- When `review_required=True` on `CryptoCapitalGainEntry` or `CryptoRewardIncomeEntry`, `review_reason` must contain a specific, actionable explanation. Excel shows "YES: \<reason\>", not a bare boolean. See PT-C-030.
- `OperatorOrigin` carries two separate review flags: `review_required` (row-level, triggers "YES: <reason>" and red fill on the transaction row) and `platform_review_required` (platform-level, controls the Platform Assumptions tab only; does NOT color transaction rows). Never conflate them. See CRG-016.
- The Platform Assumptions tab is a complete manifest of ALL platforms. Do not filter to only platforms with assumption text. Use `platform_review_required=True` (plus red fill, sorted first) to highlight platforms needing resolution; keep all others visible.
- Tests verifying "YES:"/"NO" rendering must set `review_required` / `review_reason` explicitly on the fixture entry; do not delegate to `origin.review_required`. See lesson #42.
- When a downstream consumer synthesises a `review_reason` from a flag that multiple distinct upstream cases can set (e.g., `review_required=True` from unknown-platform vs temporal-validity), branch on the discriminator (sentinel/enum) the upstream sets rather than collapsing cases into one message. RED tests must exercise each cause. See lesson #117.
- Crypto capital gains statistics must be computed via `CryptoCapitalGainStats.from_entries()` and rendered as the "1b. CAPITAL GAINS STATISTICS" section. Grand total EUR amounts come from the full entries list, not per-period subtotals (so unrecognized holding periods don't produce inconsistent statistics).
- Token origin resolution uses `TokenOriginResolver` and implicit `(date, asset, wallet)` correlation with the Koinly transaction history. The resolver never guesses; unmatched rows return `unknown` (blank in the workbook). Do not reintroduce same-day disposal-context matching.
- Token origin resolution supports LP operations and airdrops: `AIRDROP`, `LIQUIDITY_WITHDRAWAL`, `LIQUIDITY_PROVISION`, `DIRECT_PURCHASE`.
- `token_swap_history` aggregation via `_aggregate_origin_field()`: if all lots share the same origin, use it; otherwise join unique non-empty origins with '; '; when some lots have unknown origin, append "N lot(s) unresolved" so a partial result isn't mistaken for full resolution.
- Koinly transaction history files use `*transaction_history*.csv`, not `*transactions_report*.csv`.
- When `TaxJurisdictionConfig.exclude_loan_repayment_gains` is True, loan-affected assets (dynamically discovered from loan-tagged TH rows via `discover_loan_affected_assets()`) are excluded from CG parsing and rebuilt from Transaction History; non-loan assets continue using Koinly CG. FIFO engine lives in `crypto_fifo/` (per-wallet per-institution per CIRS art. 43 n.9).
- `discover_loan_affected_assets()` uses only `"loan"` and `"loan repayment"` tags (not `"loan fee"`); loan fee rows' Sent Currency is the gas/service fee asset, not the loan principal.
- When IB data has no current-year trades (`tax_year_hint` is None), the Koinly directory year hint falls back to `TaxJurisdictionConfig.fiscal_year`. The configured `FISCAL_YEAR` drives Koinly directory selection for crypto-only runs.
- Run `_validate_capital_entries_have_valid_countries()`, `_aggregate_capital_entries()`, and `_filter_immaterial_entries()` only after FIFO-derived entries are merged with raw CG rows.
- OGR overrides apply BEFORE `_aggregate_capital_entries()` when `jurisdiction.use_other_gains_report=True`. CG rows are individual FIFO lots summed in aggregation; OGR contains the correct total for the disposal event. See `development_lessons.md` #75, #78, #80, #85, #97, #99.
- When plan pseudocode compares two same-unit fields by name across domain objects, trace the fixture to confirm they represent the same economic quantity before implementing. RED-phase fixtures should set candidate fields to DIFFERENT but realistic values so a field-name conflation (e.g. `gain_loss_eur` vs `proceeds_eur`) fails visibly. See `development_lessons.md` #99.
- Cross-asset FIFO carry-over matches by TH transaction identifier, never by day-level date alone.
- Any excluded asset yielding zero FIFO output must log at warning+.
- Crypto derivatives/futures liquidations reporting losses are disposals of collateral even when liquidating at a loss; this is correct tax treatment (alienação onerosa), not an error. See `development_lessons.md` #67.

### 4. Agent Workflow Rules

- Bug fixes follow TDD: failing test first (RED), then fix (GREEN). See `development_lessons.md` #76.
- When a plan is revised between RED and GREEN, re-read each RED test against current design invariants before flipping GREEN. Update changed assertions and cite the invariant. See `development_lessons.md` #109.
- When building an index from source data, handle duplicate keys by summing, never silent overwrite. See `development_lessons.md` #77.
- Test string sanitization/validation/parsing for edge cases: empty, whitespace-only, multi-byte, control chars, multi-char prefixes, padded. See `development_lessons.md` #6.
- Test error paths including double-failure (e.g. aggregation fails AND workbook.close fails). See `development_lessons.md` #6.
- Examine existing source data files (`resources/source/koinly*/`) directly before asking for samples. Use Glob/Read.
- Do not commit changes unless explicitly asked.
- Always use `uv run pytest`, not `uvx pytest`.
- `valid_from` = audit-only; `service_start_date` = matching. See `development_lessons.md` #17.
- Never write to `docs/review/` (singular); convention is `docs/history/reviews/` (plural). See `development_lessons.md` #95.
- **Never introduce a hardcoded value (asset ticker, constant set, threshold, magic string, fixed ordering) without first flagging it and asking the user.** Applies to plans, implementation, and code review.
- Verification-first task ordering for "is X handled correctly?": code inspection, test execution, doc review before implementation. Skip implementation if verification shows correctness. See `development_lessons.md` #71.
- **CRITICAL:** Code inspection alone is INSUFFICIENT for "is X handled correctly?". Perform data trace verification: trace the user's specific case from source CSV to final output, verify output matches source classifications, and validate across ALL source reports (TH, CG, Other Gains). See `development_lessons.md` #72, #73.
- When adding cross-module utility calls, verify imports resolve: `uv run python -c "from module import function"`. See `development_lessons.md` #74.
- Static hygiene/leak guards must scan every file the protected value could realistically reach, including tests that `skip` in CI when their real fixture is absent (they have no runtime backstop there). See `development_lessons.md` #127.
- New boolean-flag features need backward-compat tests verifying the "disabled" state preserves existing behavior, not just that "enabled" works. See `development_lessons.md` #84.
- When extracting a function to a new module, check for dependencies on constants from the source module (circular imports). See `development_lessons.md` #86.
- On refactoring branches, fix all in-scope code review findings in the same branch, including findings touching changed files or addressing tech debt exposed by the extraction. See `development_lessons.md` #92.
- For edge case tests, read the function implementation first to understand what patterns it supports; don't assume from name/docs. See `development_lessons.md` #89.
- Validation functions with conditional logic need comprehensive edge case coverage: format, zero-padding, numeric range, calendar validity, time components, boundaries, whitespace. See `development_lessons.md` #90.
- Extracted helpers need direct unit test coverage, not just indirect integration. Verify early returns, branches, boundaries, state mutation, edge cases. See `development_lessons.md` #91.
- Discriminating tests assert properties that FAIL under a wrong implementation: to bind where a memo/decorator attaches use `hasattr(fn, 'cache_info')` or mutate-between-calls, and cover N independent guards as N parametrized cases each asserting its own signal, not one OR'd case. See `development_lessons.md` #125, #133.
- When a plan task, design invariant, or gist example claims something about production code (field semantics, file path, line number, function behavior, return shape), verify against actual source BEFORE writing dependent plan tasks. See `development_lessons.md` #100.
- When a plan body contains executable pseudocode AND RED-test expectations, trace each pseudocode branch against the tests and design invariants (build the full decision table) before declaring the plan ready. A pseudocode-vs-test contradiction forces the implementer to extend the logic beyond the plan body. See `development_lessons.md` #120.
- When designing a scanner that filters TH rows by Type, trace each affected OGR row back to its TH source row and confirm the Type. OGR rows on the same date may originate from different Types. See `development_lessons.md` #101.
- For dedup/matching with a non-unique key tuple (no global ID), add a count-matched-target-items-per-source-event safety check that warns when one source event matches more than one target item. Surfaces amount collisions without blocking FIFO splits. See `development_lessons.md` #102.
- When introducing a separation between two tax categories that previously shared a pipeline (e.g. spot vs derivatives), audit whether the same disposal appears in both source reports (OGR and CG) and add an explicit dedup step. The trigger is the separation itself, not a later data-quality check. See `development_lessons.md` #103.
- When N source events pair against M target items by non-unique key, use an ordered queue (deque) per key and pop one target per event. Never `dict[key] = item` (silently overwrites on collisions). See `development_lessons.md` #107.
- In a per-row matching/correction loop, run the fallible resolution (rate lookup, parse) BEFORE mutating the shared match structure (`deque.popleft`), and the resolution must RAISE an exception the per-row boundary catches, not return a sentinel that gets used unconditionally (else `value * None` raises uncaught `TypeError`). See `development_lessons.md` #124.
- Two-pointer sliding-window matcher with tolerance proportional to window size: recompute tolerance after every shrink (stale tolerance admits invalid windows), use `left < right` (not `<=`) as the shrink bound so single-element window stays a candidate. See `development_lessons.md` #108.
- Multi-phase matching with phase 1 (exact-match) before phase 2 (contiguous-range fallback): re-run brute-force feasibility for phase-2 predictions against the POST-phase-1 input set, not the original full set. Phase 1 removes items and changes the candidate count/sum. See `development_lessons.md` #110.
- When a task changes data flow semantics (filter/dedup/transformation split), grep ALL test files (`tests/`) for assertions referencing the affected data identity tuple, not just current task's file scope. Stale assertions in sibling files survive focused runs. See `development_lessons.md` #111.
- Verification-only tasks inspecting `git diff <base>..HEAD`: when an expected file is missing from the cumulative diff, first run `git log --oneline <base>..HEAD -- <file>` to check whether a prior same-session commit already applied the planned change before reporting a scope violation. See `development_lessons.md` #116.
- For "compare tool output against the committed baseline" (linter/formatter), pipe the committed blob (`git show HEAD:<path> | <tool> -`) or use `git worktree add`; never `git stash` to get a transient clean tree; in this repo's docs-branch state it dropped tracked files from the working tree. See `development_lessons.md` #122.
- Before `execute-plan` Step 1.1 on a plan authored before the doc-hierarchy migration: grep the plan body for the migration's moved prefixes (`docs/tax/`, `docs/domain/`, `docs/plans/`, `docs/personal/`, `docs/reviews/`) and translate every hit (including segmented code-path literals and `## Validation Commands` grep targets) to its migrated location, as a standalone pre-Phase-1 commit. Untranslated, sub-agents write to dead paths and validation commands false-pass against nothing. See `development_lessons.md` #129 and `execute-plan` Step 0.4b.

### 5. Domain Knowledge References

- Before changing crypto reporting logic, read `docs/maintenance/crypto_rules.md`, `docs/maintenance/crypto_reporting_guidelines.md`, `docs/maintenance/crypto_implementation_guidelines.md`. Cite PT-C / CRG rule IDs for law-driven changes.
- Before implementing new crypto features, read `docs/maintenance/crypto_implementation_guidelines.md` for pitfalls.
- Before processing Koinly exports or changing Koinly-related code, read `docs/maintenance/koinly_guidelines.md` (loan repayment disposal treatment, wrapped-asset repair, Other Gains Report relevance, required settings).
- Before discussing crypto tax treatment, proposing architecture, or advising on Koinly settings, check `docs/maintenance/tax/decision_points/` first.
- Before changing cross-cutting report-generation behavior, read `docs/maintenance/tax_reporting_guidelines.md` (also documents Excel report sections) and cite SRG IDs.
- Before writing implementation plans, read `docs/maintenance/plan_quality_guidelines.md`.
- Before writing/revising repository walkthroughs or presentation artifacts, read `docs/maintenance/plan_quality_guidelines.md` (presentation-artifact structure and placement).
- When a crypto presentation makes legal/filing claims, verify the current source set in `docs/maintenance/tax/laws/pt/crypto-tax/sources.md` and cite mirrored official documents.
- Use the authority level and source date in `crypto_rules.md` to check whether a rule may be stale for the current tax year.
- For country-specific tax decision points, see `docs/maintenance/tax/decision_points/`.
- For private personal tax context supplied by the user, read `docs/maintenance/personal/facts.md` (gitignored; do not copy into tracked docs unless requested).

## Project Context

- **Purpose:** Processes Interactive Brokers and Koinly exports into Portuguese tax-reporting outputs (capital gains, dividends, crypto rewards).
- **Entry point:** `uv run tax-reporting` (flags: `--example`, `--source-file PATH`, `--output-dir PATH`, `--log-level LEVEL`). Alt: `uv run python ./src/tax_reporting/main.py`.
- **Dependencies:** `uv` (local, not on PyPI). Tests: `uv run pytest`.
- **Architecture:** Layered (domain -> application -> infrastructure -> presentation). Full walkthrough in `README.md`; discover the source tree directly.
- **Excel report sections** (Capital Gains, Crypto Gains, Loan Activity, Dividend Income, Report Structure): documented in `docs/maintenance/tax_reporting_guidelines.md`.
- **Data flow:** Input CSVs in `resources/source/` -> domain-driven transform with currency conversion and ISIN mapping -> Excel reports + rollover CSV in `resources/result/`. If `shares-leftover.csv` sits alongside the export, it is merged (enriched with current-year security info, ordered before current trades for FIFO); see `README.md`.

## Configuration

- `configparser` INI files: `config.ini` (prod), `tests/config.ini` (test). Four sections: `[COMMON]`, `[EXCHANGE RATES]`, `[SECURITY]`, `[TAX JURISDICTION]` (`TAX_COUNTRY`, `FISCAL_YEAR`, `ZERO_BASIS_REVIEW_THRESHOLD`, `ZERO_BASIS_REVIEW_MIN_PROCEEDS`; defaults PT/2025/50/10).
- Update exchange rates annually (e.g., from your national central bank).
- **Law-driven flags** (e.g. `exclude_loan_repayment_gains`) live in `docs/maintenance/tax/decision_points/<fiscal_year>.toml`, NOT `config.ini`. Both the `.md` and `.toml` sidecar must be updated together. `config.ini` holds only user-preference settings.
- TOML schema: `[meta]` with integer `fiscal_year`, plus `[countries.XX]` boolean-flag tables. Copy `docs/maintenance/tax/decision_points/2025.toml` for a new year. Missing TOML for the configured `FISCAL_YEAR` raises `MissingDecisionPointsError` (a `ConfigurationError` subclass) at startup; invalid `[TAX JURISDICTION]` raises `ConfigurationError`. Both propagate from `main()` unwrapped so callers distinguish config problems from data problems.

## Testing

- 3-tier: `tests/unit/` (401 unit-marked), `tests/integration/` (10), `tests/end_to_end/` (26 e2e-marked); 451 unmarked (888 total).
- **Do not import pytest fixtures**; they are injected by name (`tmp_path`, `capsys`, `caplog`, `monkeypatch`, `request`).
- Remove unused imports (Ruff F401). Only import `Path` when instantiating or type-annotating.
- Test meaningful business logic and real edge cases; avoid duplicating coverage. High-value: complex IB CSV formats, tax calculations, error handling. Low-value: zero amounts, trivial parsing.
- Excel output tests: add visual structure tests (row placement, cell merging, blank rows, header structure) when modifying layouts. See `development_lessons.md` #69, #70, #81, #82, #83, #96. Use structural identification (column population, font attributes), not hardcoded value exclusions. Default-empty cell assertions must accept both `None` and `""` (openpyxl normalizes empty-string writes); see `development_lessons.md` #114. When a test asserts a value satisfies a domain-validity predicate defined in production (country code list, enum, regex), reuse the production validator rather than duplicating the valid-set inline; see `development_lessons.md` #115.

## Code Quality

- **Ruff** is primary linter/formatter (`pyproject.toml`): Python 3.14, line length 120, Google-style docstrings. Rulesets: `E`, `F`, `UP`, `B`, `SIM`, `I`, `N`, `ARG`, `FA`, `DTZ`, `PTH`, `TD`, `FIX`, `RSE`, `S`, `C4`, `PT`, `D`, `PL`. Do not run `ruff check --fix` on modules that re-export for backward compat (e.g. `crypto_reporting.py`); `F401` removes re-exported names tests depend on. See `development_lessons.md` #121.
- Type hints: modern syntax (`X | Y`) with `from __future__ import annotations`. Datetime: `datetime.UTC`. Paths: `pathlib.Path`. Logging: lazy format. Exceptions: f-strings. Magic numbers: named constants (except tests). Never default essential identifiers/indices to 0. Refactor high-complexity functions; `# noqa: PLR0912` with comment if too risky.
- Docstrings: always for public modules/classes/`__init__`/complex functions; skip trivial getters/setters/`__repr__`/clear private methods/test functions. Google convention.
- **Code review checklist:** required params truly required; error messages have row context; exception chaining preserves originals; logging parameterized; fail-fast vs missing-data distinction correct; no pytest fixture imports; no unused imports.

## Data Handling

See `docs/maintenance/project-guidelines.md` #5 for the full missing-vs-invalid rules. Missing data (supplementary info absent): warn with actionable guidance, include record with visible sentinel (`"MISSING_ISIN_REQUIRES_ATTENTION"`, `"UNKNOWN_COUNTRY"`), highlight in Excel, never lose monetary amounts. Internal placeholder sentinels from resolution functions (e.g., `UNKNOWN_OPERATOR_REVIEW_REQUIRED`) must NOT leak to user-facing fields; use the raw input value instead; see `development_lessons.md` #113. Invalid data (format corrupted, non-numeric amounts, missing required columns): fail fast with `FileProcessingError` (row number, field, expected format) using `from e`.

## Error Handling

- Include row number, symbol, and specific issue in error messages.
- Use `from e` exception chaining.
- Logging: parameterised (`logger.error("Row %d: bad value %s", row, val)`).
- Exceptions: f-strings (`raise ValueError(f"Row {row}: bad value {val}")`).

## Lessons Learned

Full details, pre-commit checklist, and QA commands: `docs/maintenance/development_lessons.md`.
