# Instructions

Guidance for coding agents (canonical `AGENTS.md`; `CLAUDE.md` is a symlink to it). Hard rules first; detail lives in `README.md` and `docs/`.

## Documentation Hierarchy

This repo follows a three-layer docs layout under `docs/` (see `doc-hierarchy` skill).
- **Layer 1:** [README.md](docs/README.md) (concise overview).
- **Layer 2 (Shared):** `docs/architecture/` and `docs/maintenance/` (guidelines, glossary, decisions, tax-law). Update in the same session when behavior or rules change.
- **Layer 3 (History):** `docs/history/` (plans, completed plans).
- **LLM-only / Temporary:** `docs/tmp/` and gitignored `docs/history/reviews/` and `docs/maintenance/personal/`.
- **Resolution:** Other skills resolve paths (like `{plans_dir}`) from `.ai-playbook/facts.md` (using-skills Step 0).
- `AGENTS.md` is canonical; `CLAUDE.md` is a symlink.

## Instruction Rules

### 1. Reusable Engineering Rules

- For numeric fields from external reports, detect thousands/decimal separators or fail clearly.
- Do not classify values with a leading zero integer part (e.g. `0,001`) as thousands-grouped.
- Treat exactly one dot-grouped triplet (e.g. `1.234`) as ambiguous and raise a clear error. Only multi-group dot patterns (e.g. `1.234.567`) may be stripped as European thousands.
- Use f-strings in exception constructors; never pass multiple positional args.
- Catch row-level parse errors per row (warn and skip); do not let one bad row discard the whole dataset.
- When extracting a second derived value inside a `try...except` block, reuse the parsed object in the same block; wrap the secondary parse in a nested `try...except` if the outer loop must not block a trusted-path branch.
- When an optional field from external input is absent, use a type-safe sentinel (e.g. `"0"` for numeric, `"MISSING"` when `"0"` is itself valid), not `""`. See `coding_guidelines.md` #4.
- Data-loss conditions (unmatched items, dropped records) must be logged at warning+, never debug. See `coding_guidelines.md` #5.
- All-or-nothing validation for required file sets: none present -> skip; partial set -> raise `FileProcessingError` listing missing files; all present -> proceed.
- Verification/hygiene guards must fail closed when the manifest is absent; `grep -f <missing>` exits non-zero, so `cmd && echo BAD || echo GOOD` false-passes.
- Validation that depends on complete state runs post-aggregation, not per-row (mid-accumulation state can be temporarily invalid).
- When reusing a validation/security pattern, inherit the guards but recalibrate exception handling to the cost of silent failure at the new call site.
- Unmatched items from matching algorithms must never be silently discarded; apply an explicit fallback and log a warning.
- When an aggregator takes `entries[0]` for a field assumed constant across a group, add a heterogeneity guard. Sibling aggregators merging the same type must use byte-identical patterns or a shared helper; diverging patterns silently drop data.
- Partial or uncertain results must carry an explicit indicator so the user cannot mistake them for complete. Review flags must include specific actionable explanations, not bare booleans.
- User-facing output labels use self-explanatory terminology, not terse names from source formats. See `coding_guidelines.md` #6. F-strings interpolating `str | None` into user-facing text must degrade explicitly for `None` on warn-only config-drift paths.

### 2. Repository Style and Conventions

- Specific type annotations for generic collections (`list[Type] | None`, not `list | None`). See `development_lessons.md` #4.
- For generic collection or matching primitives, use TypeVar parameterization so subclass fields stay visible to static analysis.
- For type dispatch on generic hints in config loaders use `get_args(hint) == (str, Decimal)`, not `get_origin(hint) is dict`; overwrite the validated entry.
- Matching event fields must mirror domain entry field normalization; normalizing one side breaks matching for affected platforms.
- Type heterogeneous kwargs dicts as `dict[str, Any]` before `**`-unpacking into a dataclass; per-key narrowing doesn't survive a splat.
- Catch specific exception types (`FileProcessingError`, `ValueError`), not broad `Exception`.
- Koinly source discovery is year-agnostic (`koinly*`) and prefers a year matching parsed IB data.
- If an inferred IB tax year exists and the selected Koinly directory year differs, skip crypto loading for that run.
- Dividend aggregation validates one currency per symbol; mismatches raise `FileProcessingError`.
- `TradeDate` is a `NamedTuple(year, month, day)`. Do not call `.date()` on it; use it directly or call `.to_datetime()`.
- External-report date parsers must localize naive dates to the jurisdiction zone (a `strptime` literal like ` UTC` does not populate `tzinfo`).
- When classifying a dividend row as withholding tax, match only the literal `"Withholding Tax"`; never bare `"Tax"` (dividend descriptions contain "Tax" as a word fragment, e.g. "Tax-Exempt Interest").
- `docs/maintenance/tax/.../official/` keeps only source-origin files; derived notes and numbered guidance belong outside `official/`; `sources.md` records issuing/effective/superseded dates. See `project-guidelines.md` #1.
- For external source archive provenance and freshness checks, see `docs/maintenance/project-guidelines.md` #1.
- For fiscal-year versioned tax decision points, see `docs/maintenance/project-guidelines.md` #2.
- When AT guidance cites a CIRS paragraph number, verify against the consolidated CIRS/CPPT/CIS PDFs; AT documents may predate renumbering amendments. See `docs/maintenance/project-guidelines.md` #3.
- For tax/origin web sources, prefer authoritative PDFs or extracted Markdown/PDF over raw HTML; reuse local mirrors. A locally-archived official source wins outright over a conflicting secondary source; do not flag a competing "repo conflict."
- Authoritative law portals render the CURRENT version by default; for a prior fiscal year, use the version in force then ("Redações anteriores"), cross-checked against a year-dated secondary source. See `development_lessons.md` #31.
- Before assuming an official source is unavailable, probe the authority's canonical URL with a HEAD request; a web/search MCP tool quota/rate-limit is a tool outage, not a missing source. See `development_lessons.md` #37.
- Under `docs/maintenance/tax/`, use `laws/<jurisdiction>/crypto-tax/` for tax-law archives and `crypto-origin/` for chain/operator domicile archives.
- Adding a decision point flag requires the corresponding `TaxJurisdictionConfig` field and type-dispatch support; jurisdiction-specific output must be flag-gated, not country-literal-gated. See `development_lessons.md` #36.
- Decision-point flags whose value must be explicit require a required-presence loader guard; run the omit-the-flag test to confirm it raises `ConfigurationError`, not `NameError`. See `development_lessons.md` #49.
- In decision-points TOML, place country-level flags before any `[countries.XX.<child>]` nested subtable header or they are silently re-scoped. See `development_lessons.md` #50.
- Verify DP enumerated rules match implemented code branches; update prose on change.
- Share crypto `País da Fonte` resolution across rewards and capital gains. Never use taxpayer residence.
- Keep `docs/maintenance/tax/crypto-origin/` source manifest, registry, and decision log synchronized when changing chain/operator mappings.
- Chain derivation uses deterministic normalization and validates against trusted sources in `docs/maintenance/tax/crypto-origin/`.
- Wallet labels are discovery hints only; final chain/country mappings come from archived operator origin documents, not asset symbols. Use `Unknown` when labels don't allow reasonable chain derivation.
- Test-side per-row platform attribution must mirror `wallet_kind._row_platform` (skip empty OR case-insensitive `"unknown"`); bare `tr.sending_wallet or tr.receiving_wallet` misattributes since `"Unknown"` is truthy. See `development_lessons.md` #44.
- Throwaway shadow/verification scripts re-parsing an external-report CSV must call the production reader (`read_koinly_rows`, etc.), not `csv.DictReader` (preamble/header handling diverges). See `development_lessons.md` #45.
- Deletion-verification grep backstops must scan `docs/maintenance/`, `docs/architecture/`, `README.md` (not just `src/`/`tests/`); patterns cover prose phrases, not just identifiers. See `development_lessons.md` #55.
- Operator mapping temporal validity: `service_start_date` (matching) vs `valid_from` (audit-only); set `service_start_date <= valid_from`, leave `valid_from` null when unknown.
- Module size: when a module exceeds 1,000 lines or 50 functions/classes, extract cohesive responsibilities into separate modules.
- Orchestration layers stay thin (~500 lines max); extract sub-orchestrators or move domain logic to dedicated services when coordination grows.

### 3. Repository Constraints

- Optional crypto ingestion is non-blocking: missing/mismatched-year/unparseable Koinly input emits a warning and continues IB report generation without crypto data.
- Partially-unmatched sells (FIFO exhausts all buys before all sells are consumed) must never be silently dropped. Apply the placeholder-buy mechanism to the remaining sell quantity, log at `logger.warning`, and include the capital gain line.
- Partially-matched buys written to the rollover CSV use proportional fee: `proportional_fee = action.fee * (rolled_quantity / original_quantity)`.
- Dividend per-symbol validation runs after all rows for all symbols are accumulated, not per row. Symbols that fail post-accumulation validation are skipped with `logger.warning`; they must not abort other symbols.
- Aggregate crypto capital gains by `(disposal_date, asset, platform, holding_period)` before reporting. Do not bypass `_aggregate_capital_entries()`.
- After aggregation, exclude entries where `|gain/loss| < 1 EUR`. Do not remove `_filter_immaterial_entries()` or parameterize `_MATERIALITY_THRESHOLD` without a `crypto_rules.md` update.
- Crypto reward income must be aggregated by `(income_code, source_country)` before inclusion in the IRS-ready filing table. Do not bypass `aggregate_taxable_rewards()`.
- Reward classification (taxable_now vs deferred_by_law) uses `_classify_reward_tax_status()` (cite CRG-001/002). Taxable-now crypto-origin fiat rewards are the `Reporting`/`OTHER CAPITAL INVESTMENT INCOME` target; `Crypto Supplementary` is support only. See SRG-008.
- The aggregation step fails with `FileProcessingError` if any taxable-now row cannot be assigned all mandatory IRS fields (valid Tabela X country code).
- When `review_required=True`, `review_reason` must contain a specific, actionable explanation; Excel shows "YES: \<reason\>", not a bare boolean. See PT-C-030.
- `OperatorOrigin` has two review flags: `review_required` (row-level) and `platform_review_required` (platform-level). Never conflate them. See CRG-016.
- The Platform Assumptions tab is a complete manifest. Do not filter; use `platform_review_required=True` to highlight.
- Tests verifying "YES:"/"NO" rendering must set `review_required`/`review_reason` on the fixture entry; do not delegate to `origin.review_required`.
- When a downstream consumer synthesises a `review_reason` from a flag multiple upstream cases set, branch on the discriminator (sentinel/enum) the upstream sets; don't collapse causes. RED tests must exercise each cause.
- When migrating a test off a real fixture to synthetic data whose unmapped identifiers flip an orthogonal signal (e.g. `review_required=True`), re-scope the assertion to the behavior under test, not the incidental flag.
- Crypto capital gains statistics must be computed via `CryptoCapitalGainStats.from_entries()` and rendered as "1b. CAPITAL GAINS STATISTICS"; grand totals come from the full entries list, not per-period subtotals.
- Token origin resolution uses `TokenOriginResolver` with implicit `(date, asset, wallet)` correlation; unmatched rows return `unknown` (blank). Do not reintroduce same-day disposal-context matching.
- Token origin resolution supports LP operations and airdrops: `AIRDROP`, `LIQUIDITY_WITHDRAWAL`, `LIQUIDITY_PROVISION`, `DIRECT_PURCHASE`.
- `token_swap_history` aggregation via `_aggregate_origin_field()`: if all lots share the same origin, use it; otherwise join unique non-empty origins with '; '; when some lots have unknown origin, append "N lot(s) unresolved" to flag partial resolution.
- Koinly transaction history files use `*transaction_history*.csv`, not `*transactions_report*.csv`.
- Koinly TH `TxHash` is the on-chain transaction identifier; `TxSrc`/`TxDest` are wallet addresses, not tx-id candidates. `TxCorrelationKey.tx_id` derives from `tx_hash` alone; never collapse the three fields into one precedence chain, and never fall back to `tx_src`/`tx_dest` as tx-id candidates. See `development_lessons.md` #43.
- When `TaxJurisdictionConfig.exclude_loan_repayment_gains` is True, loan-affected assets (from `discover_loan_affected_assets()`) are excluded from CG parsing and rebuilt from TH; non-loan assets use Koinly CG (FIFO in `crypto_fifo/`, CIRS art. 43 n.9).
- `discover_loan_affected_assets()` uses only `"loan"` and `"loan repayment"` tags (not `"loan fee"`); loan fee rows' Sent Currency is the gas/service fee asset, not the loan principal.
- `discover_loan_affected_assets()` delegates to `resolve_treatment` and needs the Invariant 11 `OTHER + tag="loan"` clause (borrowing-side principal classifies as `Treatment.OTHER`, not `LOAN_REPAYMENT`). See `development_lessons.md` #52.
- When IB data has no current-year trades (`tax_year_hint` is None), the Koinly directory year hint falls back to `TaxJurisdictionConfig.fiscal_year`, which drives Koinly directory selection for crypto-only runs.
- Run `_validate_capital_entries_have_valid_countries()`, `_aggregate_capital_entries()`, and `_filter_immaterial_entries()` only after FIFO-derived entries are merged with raw CG rows.
- Keep pipeline stages decoupled: run value corrections and data recovery passes before manual review flags or suspect-identification passes, to prevent clobbering and reason-joining hacks.
- OGR overrides apply BEFORE `_aggregate_capital_entries()` when `jurisdiction.use_other_gains_report=True`. When porting, preserve each threshold gate's original scope (the `> 1 EUR` gate is review-flag only, not the agree-vs-conflict branch). See `development_lessons.md` #42.
- When plan pseudocode compares two same-unit fields by name across domain objects, confirm they represent the same economic quantity before implementing; set candidate fields to DIFFERENT realistic values in RED fixtures so a field-name conflation fails visibly.
- Plan wiring steps enabling a code path via a new kwarg/flag must trace the entry-point guard, grep-verify caller identity, and verify Validation Commands actually validate. See `development_lessons.md` #48.
- When a plan body clause edits a file a plan invariant freezes, the freeze wins; scope the edit and test to the invariant-safe subset. See `development_lessons.md` #53.
- Cross-asset FIFO carry-over matches by TH transaction identifier, never by day-level date alone.
- Any excluded asset yielding zero FIFO output must log at warning+.
- Crypto derivatives/futures liquidations reporting losses are disposals of collateral even at a loss; this is correct tax treatment, not an error. See `development_lessons.md` #26.
- Crypto tests MUST read committed synthetic data under `resources/source/example/<year>/koinly/[<scenario>/]`; never reference gitignored personal data. See `crypto_implementation_guidelines.md`.


### 4. Agent Workflow Rules

- Bug fixes follow TDD: failing test first (RED), then fix (GREEN). See `development_lessons.md` #27 (revert a RED break on an untracked file via Edit, not `git checkout`).
- When a plan is revised between RED and GREEN, re-read each RED test against current design invariants before flipping GREEN. Update changed assertions and cite the invariant.
- A committed RED test that is itself the deliverable (a later task flips it GREEN) must fail via `pytest.fail(<message>)` naming the resolving task, never an unhandled exception.
- A regression test must exercise the production call site it claims to guard (not an adjacent derived value); before merging, revert the guarded change and confirm the test fails. When a fix has two halves, scope each assertion to its half. See `development_lessons.md` #46.
- When building an index from source data, handle duplicate keys by summing, never silent overwrite.
- Test string sanitization/validation/parsing for edge cases: empty, whitespace-only, multi-byte, control chars, multi-char prefixes, padded.
- Test error paths including double-failure (e.g. aggregation fails AND workbook.close fails).
- Examine existing source data files (`resources/source/koinly*/`) directly before asking for samples. Use Glob/Read.
- Commits allowed by default; never push/PR without instruction (Git Push Policy). `~/Projects/myrepos` stay local-only.
- Always use `uv run pytest`, not `uvx pytest`.
- Never write to `docs/review/` (singular); use `docs/history/reviews/` (plural). See `development_lessons.md` #29.
- **Never introduce a hardcoded value (asset ticker, constant set, threshold, magic string, fixed ordering) without first flagging it and asking the user.**
- Verification-first task ordering for "is X handled correctly?": code inspection, test execution, doc review before implementation. Skip implementation if verification shows correctness.
- **CRITICAL:** Code inspection is INSUFFICIENT for "is X handled correctly?". Perform full data trace verification across all source reports and confirm code branches on every authority-cited discriminator.
- When a user provides multiple examples to investigate, trace and document ALL of them; do not assume the first example's root cause covers the rest.
- When verifying a user's claim that a specific amount is missing from the source data, verify whether the report output is an aggregation before concluding it is missing.
- When adding cross-module utility calls, verify imports resolve: `uv run python -c "from module import function"`.
- Static hygiene/leak guards must scan every file the protected value could realistically reach, including tests that `skip` in CI when their real fixture is absent.
- New boolean-flag features need backward-compat tests verifying the "disabled" state preserves existing behavior, not just that "enabled" works.
- When flipping a boolean-flag DEFAULT, characterization tests pinning legacy behavior must set the flag to its old value in their config helper; add dedicated tests for the new path. See `development_lessons.md` #51.
- When extracting a function to a new module, check for dependencies on constants from the source module (circular imports).
- On refactoring branches, fix all in-scope code review findings in the same branch, including findings touching changed files or addressing tech debt exposed by the extraction. See `development_lessons.md` #28.
- For edge case tests, read the function implementation first to understand what patterns it supports; don't assume from name/docs.
- Validation functions with conditional logic need comprehensive edge case coverage (format, zero-padding, range, calendar/time validity, boundaries, whitespace).
- Extracted helpers need direct unit test coverage, not just indirect integration. Verify early returns, branches, boundaries, state mutation, edge cases.
- Discriminating tests assert a property that FAILS under a wrong implementation; cover N independent guards as N parametrized cases, each asserting its own signal (not one OR'd case).
- When a plan task, design invariant, or gist example claims something about production code (field semantics, file path, line number, function behavior, return shape), verify against actual source BEFORE writing dependent plan tasks.
- Resolve pseudocode-vs-test contradictions before implementation.
- In a refactor with a byte-identical non-regression criterion, a clause adding a net-new side effect the code does NOT emit is contradictory; verify it exists pre-refactor, else route to the owning feature task.
- Trace filtered TH rows back to their OGR source rows to confirm Type.
- Add match-count warnings for non-unique deduplication keys.
- Deduplicate overlapping items when splitting shared tax pipelines.
- When N source events pair against M target items by non-unique key, use an ordered queue (deque) per key and pop one target per event. Never `dict[key] = item` (silently overwrites on collisions).
- Run fallible resolutions before mutating shared match structures.
- Recompute tolerance after shrinking sliding-window matchers.
- Re-run feasibility checks against the mutated post-phase-1 input set.
- When a task changes data flow semantics (filter/dedup/transformation split), grep ALL test files (`tests/`) for assertions referencing the affected data identity tuple, not just current task's file scope.
- When a plan task changes a function signature OR rendered output text (description/label cell), grep ALL test tiers for callers and row-locators matching the stale label; a dedicated test file is not exhaustive. Also grep method/function identifiers, not just prose.
- When renaming fixture paths or filenames, grep ALL test files AND docs for every shape the rename touches (directory, filename, filename-stem-as-glob-prefix, docstring prose); update conftest constants AND scattered references together; evolve (not delete) any hygiene check that enforced the renamed token as a marker. See `development_lessons.md` #47.
- When a plan task removes dataclass fields, grep test construction sites; shared conftest helpers forwarding `**overrides` must filter removed keys or the suite becomes uncollectable. See `development_lessons.md` #54.
- For verification-only tasks inspecting `git diff <base>..HEAD` with missing expected files, check if a prior same-session commit already applied the change.
- For comparing tool output against the committed baseline (linter/formatter), pipe the committed blob or use `git worktree add`; never use `git stash`.
- Before `execute-plan` Step 1.1 on a pre-migration plan, grep and translate moved path prefixes (`docs/<module>/`) to their migrated locations in the plan body and `execute-plan` Step 0.4b.
- When validating branch compliance (e.g. for em dashes), do not rely on working-tree filters like "touched" or "unstaged" if changes have already been committed; diff explicitly against the target branch.
- **Never proceed to plan execution or make code changes without explicit user approval when in Planning Mode.** Bypassing the approval gate violates user intent and creates unwanted code churn.
- Request a plan amendment before omitting prescribed behaviors.
- Temporary artifacts and scratch scripts must not be placed in git-tracked folders like the project root; use a dedicated git-ignored scratch folder or the system scratch directory. See `development_lessons.md` #34.


### 5. Domain Knowledge References

- Before changing crypto reporting logic or implementing new crypto features, read `docs/maintenance/crypto_rules.md`, `docs/maintenance/crypto_reporting_guidelines.md`, and `docs/maintenance/crypto_implementation_guidelines.md` (pitfalls); cite PT-C/CRG rule IDs for law-driven changes.
- Before processing Koinly exports or changing Koinly-related code, read `docs/maintenance/koinly_guidelines.md` (loan repayment disposal treatment, wrapped-asset repair, Other Gains Report relevance, required settings).
- Before discussing crypto tax treatment, proposing architecture, or advising on Koinly settings, check `docs/maintenance/tax/decision_points/` first.
- Before changing cross-cutting report-generation behavior, read `docs/maintenance/tax_reporting_guidelines.md` (also documents Excel report sections) and cite SRG IDs.
- Before changing cross-cutting logic that prior incidents cover, consult the root-cause principle catalog (`coding_guidelines.md` #17-#25; grep the in-band `**Principle:** Family X` tags in `docs/maintenance/development_lessons.md`, plus the user-level corpus; see the `generalize` skill).
- Before writing implementation plans, repository walkthroughs, or presentation artifacts, read `docs/maintenance/plan_quality_guidelines.md`.
- When adding terms to `docs/maintenance/glossary.md`, keep English as the defining language (preserve original non-English naming in italics) and separate generic from jurisdiction-specific (PT) terms; see `development_lessons.md` #32.
- When a crypto presentation makes legal/filing claims, verify the current source set in `docs/maintenance/tax/laws/pt/crypto-tax/sources.md` and cite mirrored official documents.
- Before advising on NHR (Residente Não Habitual) foreign-income exemption or Anexo L filing, read the AT RNH folheto mirror at `docs/maintenance/tax/laws/pt/official/at_folheto_rnh_2022-10-19.pdf` (provenance and folder index under `docs/maintenance/tax/laws/pt/`).
- Before advising on an IRS reclamação/impugnação prazo, verify against the mirrored CPPT (`docs/maintenance/tax/laws/pt/official/`); secondary summaries have erred. See `project-guidelines.md` #3.
- Use the authority level and source date in `crypto_rules.md` to check whether a rule may be stale for the current tax year.
- For country-specific tax decision points, see `docs/maintenance/tax/decision_points/`.
- For private personal tax context supplied by the user, read `docs/maintenance/personal/facts.md` (gitignored; do not copy into tracked docs unless requested).
- For tax classification of structured products, certificates, and blacklisted-issuer rules (CIRS Art. 43(7)), see `development_lessons.md` #33.
- When preparing Portal das Financas entry data for an IRS annex/Quadro, transcribe the form's full official field list (not just a net total) and confirm every title clause (incl. negated/directional qualifiers); Q8A has no per-payer field, so aggregate by (Codigo + Pais). See `development_lessons.md` #35.

## Project Context

- **Purpose:** Processes Interactive Brokers and Koinly exports into Portuguese tax-reporting outputs (capital gains, dividends, crypto rewards).
- **Entry point:** `uv run tax-reporting` (flags in `README.md`). Alt: `uv run python ./src/tax_reporting/main.py`.
- **Dependencies:** `uv` (local, not on PyPI). Tests: `uv run pytest`.
- **Architecture:** Layered (domain -> application -> infrastructure -> presentation). Full walkthrough in `README.md`; discover the source tree directly.
- **Excel report sections** (Capital Gains, Crypto Gains, Loan Activity, Dividend Income, Report Structure): documented in `docs/maintenance/tax_reporting_guidelines.md`.
- **Data flow:** Input CSVs in `resources/source/` -> domain-driven transform (currency conversion, ISIN mapping) -> Excel reports + rollover CSV in `resources/result/`; see `README.md` (incl. `shares-leftover.csv` merge ordering).

## Configuration

- `configparser` INI files: `config.ini` (prod), `tests/config.ini` (test). Three sections: `[COMMON]`, `[EXCHANGE RATES]`, `[TAX JURISDICTION]` (fields and defaults documented in `README.md`). Update exchange rates annually.
- `IANA_TIMEZONE`: auto-deduces `Europe/Lisbon` for `TAX_COUNTRY=PT`; REQUIRED for other countries with crypto data, else fails fast.
- **Law-driven flags** (e.g. `exclude_loan_repayment_gains`) live in `docs/maintenance/tax/decision_points/<fiscal_year>.toml`, NOT `config.ini` (user preferences only); update the `.md` and `.toml` sidecar together.
- TOML schema: `[meta].fiscal_year` (integer) + `[countries.XX]` boolean tables (multi-type loader also accepts `dict[str, Decimal]` subtables); copy `2025.toml` per year. Missing TOML raises `MissingDecisionPointsError`; invalid `[TAX JURISDICTION]` raises `ConfigurationError`; both surface unwrapped from `main()`.

## Testing

- 3-tier: `tests/unit/` (401 unit-marked), `tests/integration/` (10), `tests/end_to_end/` (26 e2e-marked); 451 unmarked (888 total).
- **Do not import pytest fixtures**; they are injected by name (`tmp_path`, `capsys`, `caplog`, `monkeypatch`, `request`).
- Tests must not read gitignored data; inline expected values, commit the fixture, or generate it deterministically. See `coding_guidelines.md` #26, `development_lessons.md` #38.
- Test class names must match `python_classes = ["Test*"]` in `pyproject.toml`; non-`Test*`-prefix names are silently deselected.
- Pair `pytest.raises(ExceptionType, match=<regex>)` with a `match=` argument whose substring comes from the intended raise site; Ruff PT011 flags bare-type raises for over-broad assertion. See `python_guidelines.md` #14.
- Remove unused imports (Ruff F401). Only import `Path` when instantiating or type-annotating.
- Test meaningful business logic and real edge cases; avoid duplicating coverage. High-value: complex IB CSV formats, tax calculations, error handling; low-value: zero amounts, trivial parsing.
- Excel output tests: structural identification over hardcoded value exclusions; default-empty cell assertions accept `None` and `""`; reuse the production validator for domain-validity predicates.

## Code Quality

- **Ruff** is primary linter/formatter (`pyproject.toml`: Python 3.14, line length 120, full ruleset). Do not run `ruff check --fix` on modules that re-export for backward compat (e.g. `crypto_reporting.py`); `F401` removes re-exported names tests depend on.
- Type hints: modern syntax (`X | Y`) with `from __future__ import annotations`; `datetime.UTC`, `pathlib.Path`, lazy logging, f-string exceptions, named-constant magic numbers (except tests). Never default essential identifiers/indices to 0. Refactor high-complexity functions; `# noqa: PLR0912` with comment if too risky.
- Docstrings: always for public modules/classes/`__init__`/complex functions; skip trivial getters/setters/`__repr__`/clear private methods/test functions. Google convention.
- **Code review checklist:** required params truly required; error messages have row context; exception chaining preserves originals; logging parameterized; fail-fast vs missing-data distinction correct; no pytest fixture imports; no unused imports.

## Data Handling

Missing-vs-invalid: see `docs/maintenance/project-guidelines.md` #5 for the full rules. Incremental: internal resolution sentinels (e.g. `UNKNOWN_OPERATOR_REVIEW_REQUIRED`) must NOT leak to user-facing fields - use the raw input value.



## Lessons Learned

Full details, pre-commit checklist, and QA commands: `docs/maintenance/development_lessons.md`.

