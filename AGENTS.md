# Instructions

Guidance for coding agents (canonical `AGENTS.md`; `CLAUDE.md` is a symlink to it). Detail lives in `README.md` and `docs/`.

## Documentation Hierarchy

This repo follows a three-layer docs layout under `docs/` (see `doc-hierarchy` skill).
- **Layer 1:** [README.md](docs/README.md) (overview).
- **Layer 2 (Shared):** `docs/architecture/` and `docs/maintenance/` (guidelines, glossary, decisions, tax-law). Update in-session when behavior or rules change.
- **Layer 3 (History):** `docs/history/` (plans, completed plans, backlog ideas archived to `backlog/completed/`).
- **LLM-only / Temporary:** `docs/tmp/` and gitignored `docs/history/reviews/` and `docs/maintenance/personal/`.
- **Resolution:** Other skills resolve paths (like `{plans_dir}`) from `.ai-playbook/facts.md`.

## Instruction Rules

### 1. Reusable Engineering Rules

- For numeric fields from external reports, detect thousands/decimal separators or fail clearly.
- A leading-zero integer part (e.g. `0,001`) is never thousands-grouped; a single dot-grouped triplet (e.g. `1.234`) is ambiguous and must raise; only multi-group dot patterns (e.g. `1.234.567`) may be stripped as European thousands.
- Use f-strings in exception constructors; never pass multiple positional args.
- Catch row-level parse errors per row (warn and skip); one bad row must not discard the whole dataset.
- In a row-level `try...except`, reuse the parsed object for second derived values; nest a `try...except` around a fallible secondary parse when a trusted-path branch must not be skipped. See UL #80, #125.
- Absent optional fields use a type-safe sentinel (e.g. `"0"` for numeric, `"MISSING"` when `"0"` is valid), not `""`; a classifier `else` fallback uses a non-valid sentinel + WARNING. See `coding_guidelines.md` #4, `development_lessons.md` #106, #115.
- Data-loss conditions (unmatched items, dropped records) must not be silently discarded: apply an explicit fallback and log at warning+, not debug. See `coding_guidelines.md` #5.
- All-or-nothing validation for required file sets: none present -> skip; partial set -> raise `FileProcessingError` listing missing files; all present -> proceed.
- Verification/hygiene guards fail closed when the manifest is absent (`grep -f <missing>` false-passes `&&`). Coverage gates use subset semantics, not ANY-match; missing identifiers keep a sentinel (`development_lessons.md` #141).
- Validation that depends on complete state runs post-aggregation, not per-row (mid-accumulation state can be invalid).
- When reusing a validation/security pattern, inherit the guards but recalibrate exception handling to the cost of silent failure at the new call site.
- When an aggregator takes `entries[0]` for a field assumed constant across a group, add a heterogeneity guard. Sibling aggregators merging the same type must use byte-identical patterns or a shared helper.
- Partial or uncertain results must carry an explicit indicator so users cannot mistake them for complete. Review flags must give specific actionable explanations, not bare booleans.
- User-facing output labels use self-explanatory terminology, not terse names from source formats; f-strings interpolating `str | None` must degrade explicitly. See `coding_guidelines.md` #6.

### 2. Repository Style and Conventions

- Specific type annotations for generic collections (`list[Type] | None`, not `list | None`). See `development_lessons.md` #4.
- For generic collection or matching primitives, use TypeVar parameterization (keeps subclass fields visible to static analysis).
- For type dispatch on generic hints in config loaders use `get_args(hint) == (str, Decimal)`, not `get_origin(hint) is dict`; overwrite the validated entry.
- Matching event fields must mirror domain entry field normalization; normalizing one side breaks matching for affected platforms.
- Type heterogeneous kwargs dicts as `dict[str, Any]` before `**`-unpacking into a dataclass; per-key narrowing doesn't survive a splat.
- Catch specific exception types (`FileProcessingError`, `ValueError`), not broad `Exception`.
- Koinly source discovery is year-agnostic (`koinly*`) and prefers a year matching parsed IB data.
- If an inferred IB tax year exists and the selected Koinly directory year differs, skip crypto loading for that run.
- Dividend aggregation validates one currency per symbol; mismatches raise `FileProcessingError`.
- `TradeDate` is a `NamedTuple(year, month, day)`. Do not call `.date()` on it; use it directly or `.to_datetime()`.
- External-report date parsers must localize naive dates to the jurisdiction zone (a `strptime` literal ` UTC` does not populate `tzinfo`).
- Withholding-tax classification matches only the literal `"Withholding Tax"`, never bare `"Tax"` (descriptions contain "Tax" as a fragment, e.g. "Tax-Exempt Interest").
- `docs/maintenance/tax/.../official/` keeps only source-origin files; derived notes and numbered guidance belong outside `official/`; `sources.md` records issuing/effective/superseded dates. See `project-guidelines.md` #1.
- For fiscal-year versioned tax decision points, see `docs/maintenance/project-guidelines.md` #2.
- When AT guidance cites a CIRS paragraph number, verify against the consolidated CIRS/CPPT/CIS PDFs; AT documents may predate renumbering amendments. See `docs/maintenance/project-guidelines.md` #3.
- For tax/origin web sources, prefer authoritative PDFs or extracted Markdown over raw HTML and reuse local mirrors; a locally-archived official source wins over a conflicting secondary source.
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
- Wallet labels are discovery hints only; final chain/country mappings come from archived operator origin documents, not asset symbols; use `Unknown` when labels don't allow derivation.
- Test-side per-row platform attribution must mirror `wallet_kind._row_platform` (skip empty OR case-insensitive `"unknown"`); bare `tr.sending_wallet or tr.receiving_wallet` misattributes. See `development_lessons.md` #44.
- Throwaway shadow/verification scripts re-parsing an external-report CSV must call the production reader, not `csv.DictReader` (preamble/header handling diverges). See `development_lessons.md` #45.
- Doc-drift grep backstops scan `docs/maintenance/`, `docs/architecture/`, `README.md` prose; sweep NEW value at each rendered-text site. See `development_lessons.md` #55, #58, #70.
- Operator mapping temporal validity: `service_start_date` (matching) vs `valid_from` (audit-only); set `service_start_date <= valid_from`, leave `valid_from` null when unknown.
- Module size: when a module exceeds 1,000 lines or 50 functions/classes, extract cohesive responsibilities into separate modules.
- Orchestration layers stay thin (~500 lines max); extract sub-orchestrators or move domain logic to dedicated services when coordination grows.

### 3. Repository Constraints

- Optional crypto ingestion is non-blocking: missing/mismatched-year/unparseable Koinly input emits a warning and continues IB report generation without crypto data.
- Partially-unmatched sells must never be silently dropped. Apply the placeholder-buy mechanism to the remaining sell quantity, log at `logger.warning`, and include the capital gain line.
- Partially-matched buys written to the rollover CSV use proportional fee: `proportional_fee = action.fee * (rolled_quantity / original_quantity)`.
- Dividend per-symbol validation runs after all rows for all symbols are accumulated, not per row. Symbols that fail post-accumulation validation are skipped with `logger.warning`; they must not abort other symbols.
- Aggregate crypto capital gains by `(disposal_date, asset, platform, holding_period)` before reporting. Do not bypass `_aggregate_capital_entries()`.
- After aggregation, exclude entries where `|gain/loss| < 1 EUR`. Do not remove `_filter_immaterial_entries()` or parameterize `_MATERIALITY_THRESHOLD` without a `crypto_rules.md` update.
- Crypto reward income must be aggregated by `(income_code, source_country)` before inclusion in the IRS-ready filing table. Do not bypass `aggregate_taxable_rewards()`.
- Reward classification (taxable_now vs deferred_by_law) uses `_classify_reward_tax_status()` (cite CRG-001/002); taxable-now fiat rewards target `Reporting` (SRG-008); `Crypto Supplementary` is support only.
- The aggregation step fails with `FileProcessingError` if any taxable-now row cannot be assigned all mandatory IRS fields (valid Tabela X country code).
- When `review_required=True`, `review_reason` must contain a specific, actionable explanation; Excel shows "YES: \<reason\>", not a bare boolean. See PT-C-030.
- `OperatorOrigin` has two review flags: `review_required` (row-level) and `platform_review_required` (platform-level). Never conflate them. See CRG-016.
- The Platform Assumptions tab is a complete manifest. Do not filter; use `platform_review_required=True` to highlight.
- Tests verifying "YES:"/"NO" rendering must set `review_required`/`review_reason` on the fixture entry; do not delegate to `origin.review_required`.
- When a downstream consumer synthesises a `review_reason` from a flag multiple upstream cases set, branch on the discriminator (sentinel/enum) the upstream sets; RED tests must exercise each cause. See UL #91.
- When migrating real fixtures to synthetic data, keep assertions scoped to the target behavior and use e2e-realizable analogs when literal inputs cannot reach the full pipeline. See UL #114, #86.
- Crypto capital gains statistics must be computed via `CryptoCapitalGainStats.from_entries()` and rendered as "1b. CAPITAL GAINS STATISTICS"; grand totals come from the full entries list, not per-period subtotals.
- Token origin resolution uses `TokenOriginResolver` with implicit `(date, asset, wallet)` correlation; unmatched rows return `unknown` (see `crypto_implementation_guidelines.md`). Do not reintroduce same-day disposal-context matching.
- `token_swap_history` aggregation via `_aggregate_origin_field()`: all lots same origin -> use it; else join unique non-empty origins with '; '; append "N lot(s) unresolved" when some are unknown.
- Koinly transaction history files use `*transaction_history*.csv`, not `*transactions_report*.csv`.
- Koinly TH `TxHash` is the on-chain tx identifier; `TxSrc`/`TxDest` are wallet addresses; `TxCorrelationKey.tx_id` derives from `tx_hash` alone (#43).
- When `TaxJurisdictionConfig.exclude_loan_repayment_gains` is True, loan-affected assets (from `discover_loan_affected_assets()`) are excluded from CG parsing and rebuilt from TH; non-loan assets use Koinly CG (FIFO in `crypto_fifo/`).
- `discover_loan_affected_assets()` uses only `"loan"` and `"loan repayment"` tags (not `"loan fee"`); loan fee rows' Sent Currency is the gas/service fee asset, not the loan principal.
- `discover_loan_affected_assets()` delegates to `resolve_treatment` and needs the Invariant 11 `OTHER + tag="loan"` clause (borrowing-side principal classifies as `Treatment.OTHER`, not `LOAN_REPAYMENT`). See `development_lessons.md` #52.
- When IB data has no current-year trades (`tax_year_hint` is None), the Koinly directory year hint falls back to `TaxJurisdictionConfig.fiscal_year` (drives Koinly directory selection for crypto-only runs).
- Run `_validate_capital_entries_have_valid_countries()`, `_aggregate_capital_entries()`, `_filter_immaterial_entries()` only after FIFO-derived entries are merged with raw CG rows.
- Keep pipeline stages decoupled: run value corrections and data recovery before manual review flags or suspect-identification passes.
- OGR overrides apply BEFORE `_aggregate_capital_entries()` when `jurisdiction.use_other_gains_report=True`; when porting, preserve each threshold gate's original scope. See `development_lessons.md` #42.
- When one numeric value drives both a branch decision and a user-facing display, both must use the same precision (rounded, not raw), or two rows with identical visible text can route oppositely. See `development_lessons.md` #60.
- When plan pseudocode compares two same-unit fields by name across domain objects, confirm they represent the same economic quantity before implementing; set them to DIFFERENT values in RED fixtures so a conflation fails visibly.
- Plan wiring steps enabling a code path via a new kwarg/flag must trace the entry-point guard, grep-verify caller identity, and verify Validation Commands actually validate. See `development_lessons.md` #48.
- When a plan body clause edits a file a plan invariant freezes, the freeze wins; scope the edit and test to the invariant-safe subset. See `development_lessons.md` #53.
- Cross-asset FIFO carry-over matches by TH transaction identifier, never by day-level date.
- Any excluded asset yielding zero FIFO output must log at warning+.
- Crypto derivatives/futures liquidations reporting losses are disposals of collateral even at a loss; this is correct tax treatment, not an error. See `development_lessons.md` #26.
- Crypto tests MUST read committed synthetic data, never gitignored personal exports. See `crypto_implementation_guidelines.md`.
- The on-chain TH validation harness (`--validate-on-chain-th`) is user-run; its artifacts and the append-only user-owned `on_chain_th_dispositions.toml` stay gitignored; gate exit semantics per PD-010 (`on_chain_validation.md`).

### 4. Agent Workflow Rules

- Bug fixes follow TDD: failing test first (RED), then fix (GREEN). See `development_lessons.md` #27.
- When a plan is revised between RED and GREEN, re-read each RED test against current design invariants before flipping GREEN. Update changed assertions and cite the invariant.
- A committed RED test that is itself the deliverable must fail via `pytest.fail(<message>)` naming the resolving task, never an unhandled exception.
- A pre-existing RED draft matching the Task spec's names is an abstraction over the verbatim spec; re-derive its mechanism before trusting it. See `development_lessons.md` #62.
- A completed plan's task status note (`SKIPPED`/`deferred`/`done`) or feature-notes Status header is not ground truth for whether the artifact shipped; read the canonical artifact (PD/ADR, constant). See `development_lessons.md` #65.
- A regression test must exercise the production call site it claims to guard (not an adjacent derived value); before merging, revert the guarded change and confirm the test fails. See `development_lessons.md` #46.
- A test fixture binding a named local from a positional CSV field must put the value at the column index the production reader extracts. See `development_lessons.md` #59, #60.
- When building an index from source data, handle duplicate keys by summing, never silent overwrite.
- Test string sanitization/validation/parsing edge cases: empty, whitespace-only, multi-byte, control chars, multi-char prefixes, padded.
- Test error paths including double-failure (e.g. aggregation fails AND workbook.close fails).
- Examine existing source data files (`resources/source/koinly*/`) directly before asking for samples.
- Always use `uv run pytest`, not `uvx pytest`.
- Never write to `docs/review/` (singular); use `docs/history/reviews/` (plural). See `development_lessons.md` #29.
- **Never introduce a hardcoded value (asset ticker, constant set, threshold, magic string, fixed ordering) without first flagging it and asking the user.**
- Verification-first ordering for "is X handled correctly?": code inspection, test execution, doc review before implementation; skip if verification shows correctness.
- **CRITICAL:** Code inspection is INSUFFICIENT for "is X handled correctly?". Perform full data-trace verification across all source reports; confirm code branches on every authority-cited discriminator. See `development_lessons.md` #66.
- When a user provides multiple examples to investigate, trace and document ALL; do not assume the first's root cause covers the rest.
- When verifying a claim that a specific amount is missing from source data, verify whether the report output is an aggregation before concluding it is missing.
- When adding cross-module utility calls, verify imports resolve (`uv run python -c "from m import f"`).
- Static hygiene/leak guards must scan every file the protected value could realistically reach, including `skip`-in-CI tests whose real fixture is absent.
- New boolean-flag features need backward-compat tests verifying the "disabled" state preserves existing behavior, not just "enabled" works.
- When flipping a boolean-flag DEFAULT, characterization tests pinning legacy behavior must set the flag to its old value; add dedicated tests for the new path. See `development_lessons.md` #51.
- When extracting a function to a new module, check dependencies on constants from the source module (circular imports).
- On refactoring branches, fix all in-scope code review findings in the same branch, including findings touching changed files or addressing tech debt exposed by the extraction. See `development_lessons.md` #28.
- When a task REORDERS (moves) a block in a large function, verify structural singularity (moved block and `def` each appear once); "tests pass" is insufficient without end-to-end coverage. See `development_lessons.md` #67.
- When invoking `doing-code-review` (directly or via `execute-plan` Phase 3), launch the full `review-panel-selection.md` panel; "Solo" is a dedup label, not a skip mode. See user-level lessons #190.
- For edge-case tests, read the function implementation first to understand its patterns; don't assume from name/docs.
- Validation functions with conditional logic need comprehensive edge case coverage (format, zero-padding, range, calendar/time validity, boundaries, whitespace).
- Extracted helpers need direct unit tests, not just indirect integration (early returns, branches, boundaries, state mutation, edge cases).
- Discriminating tests assert a property that FAILS under a wrong implementation; cover N independent guards as N parametrized cases, each asserting its own signal (not one OR'd case).
- When a plan task, design invariant, or gist example makes any production-code claim (semantics, path, line, behavior, return shape), verify against actual source BEFORE writing dependent plan tasks.
- Resolve pseudocode-vs-test contradictions before implementation.
- In a refactor with a byte-identical non-regression criterion, a clause adding a net-new side effect the code does NOT emit is contradictory; verify it exists pre-refactor, else route to the owning feature task.
- Trace filtered TH rows back to their OGR source rows to confirm Type.
- Add match-count warnings for non-unique deduplication keys.
- Deduplicate overlapping items when splitting shared tax pipelines.
- When N source events pair against M target items by non-unique key, use an ordered queue (deque) per key and pop one target per event. Never `dict[key] = item` (silently overwrites on collision).
- Run fallible resolutions before mutating shared match structures.
- Recompute tolerance after shrinking sliding-window matchers.
- Re-run feasibility checks against the mutated post-phase-1 input set.
- When a task changes data flow semantics (filter/dedup/split), grep ALL `tests/` for assertions on the affected data identity tuple, not just the current task's file.
- When a plan task changes a function signature OR rendered output text (label cell), grep ALL test tiers for callers and row-locators matching the stale label, including method/function identifiers, not just prose.
- When renaming fixture paths/filenames, grep ALL test files AND docs for every shape (directory, filename, stem, prose); update conftest constants and scattered refs. See `development_lessons.md` #47.
- When a plan task changes an artifact's DISCOVERY mechanism (glob -> explicit path), grep ALL test tiers for every call to the OLD discovery helper; each re-discover call site must switch to the new explicit result (`development_lessons.md` #121).
- Before downgrading a per-row `logger.warning` to `logger.debug` (warning-grouping recipe, `project-guidelines.md` #7), verify the site's review surface, sweep ALL `caplog.at_level(WARNING)` substring assertions, and sweep docs for the level phrase. See `development_lessons.md` #69, #70.
- When a plan task removes dataclass fields, grep test construction sites; shared conftest helpers forwarding `**overrides` must filter removed keys or the suite becomes uncollectable. See `development_lessons.md` #54.
- A collection-time `NameError` naming a fixture the edited code does not use, after inserting a `class`/`def`, signals an orphaned indented body re-parented onto the new block; remove it. See `development_lessons.md` #57.
- For verification-only tasks inspecting `git diff <base>..HEAD` with missing expected files, check if a prior same-session commit already applied them.
- For comparing tool output against the committed baseline (linter/formatter), pipe the committed blob or use `git worktree add`; never `git stash`.
- Before a commit following a sub-agent `docs-branch`/worktree op, verify the working tree matches HEAD (a botched op can leave a staged index revert that a blind commit captures as a rollback). See `development_lessons.md` #71.
- Before `execute-plan` Step 1.1 on a pre-migration plan, grep and translate moved path prefixes (`docs/<module>/`) to migrated locations in the plan body and Step 0.4b.
- When validating branch compliance (e.g. em dashes) after changes are committed, diff explicitly against the target branch; do not rely on working-tree "touched"/"unstaged" filters.
- **Never proceed to plan execution or make code changes without explicit user approval when in Planning Mode.**
- Request a plan amendment before omitting prescribed behaviors.

### 5. Domain Knowledge References

- Before changing crypto reporting logic, read `docs/maintenance/crypto_rules.md`, `crypto_reporting_guidelines.md`, and `crypto_implementation_guidelines.md` (pitfalls); cite PT-C/CRG rule IDs for law-driven changes.
- Before processing Koinly exports or changing Koinly-related code, read `docs/maintenance/koinly_guidelines.md` (loan repayment disposal treatment, wrapped-asset repair, OGR relevance, required settings).
- Before discussing crypto tax treatment, proposing architecture, or advising on Koinly settings, check `docs/maintenance/tax/decision_points/` first.
- Before changing cross-cutting report-generation behavior, read `docs/maintenance/tax_reporting_guidelines.md` (also documents Excel report sections) and cite SRG IDs.
- Before changing cross-cutting logic that prior incidents cover, consult the root-cause principle catalog (`coding_guidelines.md` #17-#25; grep `**Principle:** Family X` tags in both lessons corpora; `generalize` skill).
- Before writing implementation plans, repository walkthroughs, or presentation artifacts, read `docs/maintenance/plan_quality_guidelines.md`.
- When adding terms to `docs/maintenance/glossary.md`, keep English as the defining language (preserve non-English naming in italics) and separate generic from PT-specific terms. See `development_lessons.md` #32.
- When a crypto presentation makes legal/filing claims, verify the current source set in `docs/maintenance/tax/laws/pt/crypto-tax/sources.md` and cite mirrored official documents.
- Before advising on NHR (Residente Não Habitual) foreign-income exemption or Anexo L filing, read the AT RNH folheto mirror at `docs/maintenance/tax/laws/pt/official/at_folheto_rnh_2022-10-19.pdf`.
- Before advising on an IRS reclamação/impugnação prazo, verify against the mirrored CPPT (`docs/maintenance/tax/laws/pt/official/`); secondary summaries have erred. See `project-guidelines.md` #3.
- Use the authority level and source date in `crypto_rules.md` to check whether a rule may be stale for the current tax year.
- For country-specific tax decision points, see `docs/maintenance/tax/decision_points/`.
- For private personal tax or immigration documents, read `docs/maintenance/personal/facts.md`; verify dynamic signing place/date and do not copy its data into tracked docs. See `development_lessons.md` #122.
- For tax classification of structured products, certificates, blacklisted-issuer rules (CIRS Art. 43(7)), see `development_lessons.md` #33.
- Portal das Financas entry data for an IRS annex/Quadro: transcribe the form's full field list (not a net total), confirm every title clause (incl. negated qualifiers); Q8A has no per-payer field, so aggregate by (Codigo + Pais). See `development_lessons.md` #35.

## Project Context

- **Purpose:** Processes Interactive Brokers and Koinly exports into Portuguese tax-reporting outputs (capital gains, dividends, crypto rewards).
- **Entry point:** `uv run tax-reporting` (flags in `README.md`). Alt: `uv run python ./src/tax_reporting/main.py`.
- **Dependencies:** `uv` (local, not on PyPI). Tests: `uv run pytest`.
- **Architecture:** Layered (domain -> application -> infrastructure -> presentation). Full walkthrough in `README.md`.
- **Excel report sections:** documented in `docs/maintenance/tax_reporting_guidelines.md`.
- **Data flow:** `resources/source/` CSVs -> domain-driven transform (currency conversion, ISIN mapping) -> Excel reports + rollover CSV in `resources/result/`; see `README.md` (incl. `shares-leftover.csv` merge ordering).

## Configuration

- `configparser` INI files: `config.ini` (prod), `tests/config.ini` (test). Sections `[COMMON]`, `[EXCHANGE RATES]`, `[TAX JURISDICTION]` (fields/defaults in `README.md`). Update exchange rates annually.
- `IANA_TIMEZONE`: auto-deduces `Europe/Lisbon` for `TAX_COUNTRY=PT`; REQUIRED for other countries with crypto data, else fails fast.
- **Law-driven flags** (e.g. `exclude_loan_repayment_gains`) live in `docs/maintenance/tax/decision_points/<fiscal_year>.toml`, NOT `config.ini` (user preferences only); update the `.md` and `.toml` sidecar together.
- TOML schema: `[meta].fiscal_year` (integer) + `[countries.XX]` boolean tables (multi-type loader accepts `dict[str, Decimal]`); copy `2025.toml` per year. Missing TOML -> `MissingDecisionPointsError`; invalid `[TAX JURISDICTION]` -> `ConfigurationError`.

## Testing

- 3-tier: `tests/unit/` (unit-marked), `tests/integration/`, `tests/end_to_end/` (e2e-marked).
- The suite is hermetic: no ambient env vars (env gate `BERA_CHAIN_API_KEY` pinned off by an autouse fixture); no outbound network (opt-in `@pytest.mark.network`); no gitignored-data opens (audit-hook; opt-out `SKIP_AUDIT_GUARD=1`): inline values, a synthetic fixture, or deterministic generation. See `development_lessons.md` #123, `coding_guidelines.md` #26.
- **Per-test timeout ALWAYS ON** (`timeout = 120`, pytest-timeout). A timeout = runaway loop or unbounded accumulation: fix the loop, never the timeout; synthetic external-report fixtures must carry all fields production branches on (`development_lessons.md` #138).
- Do not import pytest fixtures; they are injected by name (`tmp_path`, `monkeypatch`).
- Test class names must match `python_classes = ["Test*"]` in `pyproject.toml`; other prefixes are silently deselected.
- Pytest guards: `pytest.raises(...)` needs `match=` (PT011); asserting NONE of N lookups fire under a short-circuit predicate needs all N monkeypatched. See `python_guidelines.md` #14, #15.
- Remove unused imports (Ruff F401). Only import `Path` when instantiating or type-annotating.
- Test meaningful business logic and real edge cases; avoid duplicating coverage (high-value: complex CSV formats, tax calculations, error handling).
- Excel output tests: structural identification over hardcoded value exclusions; default-empty cell assertions accept `None`/`""`; reuse the production validator for validity predicates.

## Code Quality

- **Ruff** is primary linter/formatter (`pyproject.toml`: Python 3.14, line length 120, full ruleset), but **unenforced** (no pre-commit/CI). Before adding `# noqa`, check the HEAD blob (`git show HEAD:<file> | ruff check`) to avoid mis-attributing master debt. Never `ruff check --fix` re-export modules (`F401` strips re-exported names). For "today", use `datetime.now(tz=UTC).date()`, not `date.today()` (`DTZ011`). See `python_guidelines.md`, `development_lessons.md` #72, #112.
- Type hints: modern syntax (`X | Y`) with `from __future__ import annotations`; lazy logging, f-string exceptions, named-constant magic numbers (except tests). Never default essential indices/identifiers to 0. Refactor complex functions.
- Docstrings: always for public modules/classes/`__init__`/complex functions; skip trivial getters/setters/`__repr__`/private methods/test functions.
- **Code review checklist:** required params truly required; error messages have row context; exception chaining preserves originals; logging parameterized; fail-fast vs missing-data distinction correct.

## Data Handling

Missing-vs-invalid: see `docs/maintenance/project-guidelines.md` #5 for the full rules. Incremental: internal resolution sentinels must NOT leak to user-facing fields - use the raw input value.

## Lessons Learned

Full details, pre-commit checklist, and QA commands: `docs/maintenance/development_lessons.md`.
