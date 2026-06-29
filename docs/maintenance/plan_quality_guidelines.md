# Plan Quality Guidelines

**Purpose**: Guidelines for writing implementation plans that minimize review iterations and ambiguity.

## Gist & Examples Section Format

Every plan must include a `## Gist & Examples` section immediately after the header. This is the human-readable on-ramp for implementers and reviewers.

### Required Content

1. **What changes**: One paragraph explaining the feature in plain language
2. **Why needed**: Problem statement or context
3. **Concrete examples**: Input/output examples showing before/after behavior
4. **Edge cases**: Non-obvious scenarios that influenced design decisions

### Example Format

```markdown
## Gist & Examples

**What changes:** [One plain-language paragraph explaining what changes]

**Why needed:** [Problem statement or context: why this change is necessary]

**Example input:** [Concrete input data structure, transaction, API call, etc.]

**Example output:** [Concrete output showing the transformation or result]

**Edge cases handled:** [List non-obvious scenarios that influenced design]
```

**Guidelines:**
- Use domain-appropriate examples (database rows, API responses, config formats, etc.)
- Avoid domain jargon in the "What changes" paragraph; explain for a general technical audience
- Keep examples concise but complete enough to show the transformation
- In "Edge cases", focus on non-obvious scenarios, not routine happy paths

### Anti-Patterns to Avoid

| Anti-Pattern | Correct Approach |
|--------------|-----------------|
| "Rebuild FIFO from TH" (too terse) | "Rebuild FIFO from TH because source system output is contaminated by X" |
| "Handle edge cases" (vague) | "Handle: empty dates, missing keys, zero values, future timestamps" |
| No examples | Add concrete input → output transformations showing the behavior |
| Missing unit context | Always specify units (EUR vs USD, bytes vs KB, milliseconds vs seconds) |
```

## Core Concepts

- **Edge case**: A boundary condition or special scenario that requires explicit handling
- **Negative requirement**: A constraint specifying what must NOT be done
- **Acceptance criteria**: A checklist defining when a task is complete
- **Validation sequence**: The ordered steps in which data processing must occur

## Plan Structure Requirements

### Required Sections for Each Task

Every implementation task should include:

1. **Primary requirement** - What should be implemented
2. **Edge cases** - Known boundary conditions and how to handle them
3. **Negative requirements** - What must NOT be done
4. **Acceptance criteria** - Definition of done
5. **Testing requirements** - Including negative tests

## Plan Revision History

When updating an existing plan, preserve completed steps exactly as written unless the
user explicitly asks to rewrite historical entries. Do not delete or replace completed
tasks merely because new findings changed the next steps.

If new investigation changes the follow-up work:

1. keep completed sections intact as the historical record
2. append new context or follow-on tasks below the preserved history
3. clearly distinguish completed reasoning from newly opened work

This keeps the plan usable both as an execution checklist and as an audit trail of why
the direction changed.

### Pattern-Specific Specifications

When specifying patterns in plans:

- **Exact patterns**: Use `re.match("^PATTERN$")` not `startswith()` or broad regex
- **Examples of what NOT to match**: Include negative test cases
- **Scope delimitation**: Explicitly state what is out of scope

**Example**:

```markdown
### Task: Normalize platform-specific aliases

- [ ] Normalize ONLY the exact pattern `Platform (n)` where n is any digit
- [ ] Use exact pattern matching: `re.match(r"^Platform \(\d+\)$", input)`
- [ ] DO NOT normalize other platforms' numbered aliases
- [ ] DO NOT normalize sub-products (e.g., `Platform Earn (2)`, `Platform Savings (3)`)
- [ ] Test negative cases to verify over-normalization doesn't occur
```

### Data Classification Specifications

When specifying classification logic:

1. **Define the source of truth** (e.g., "ISO 4217 standard via pycountry")
2. **List explicit exclusions** with reasons
3. **Handle edge cases** (ticker collisions, ambiguous values)
4. **Specify fallback behavior** (e.g., "return Unknown, do not guess")

**Example**:

```markdown
### Fiat Currency Classification

**Source of truth**: ISO 4217 via pycountry.currencies

**Exclusions** (not ordinary government-issued fiat):
- Commodities: XAG, XAU, XPD, XPT (precious metals)
- Special codes: XBA, XBB, XBC, XBD, XDR, XSU, XUA, XTS, XXX
- Fund/unit codes: BOV, CHE, CHW, CLF, COU, MXV, USN, UYI, UYW

**Ticker collisions** (crypto takes precedence):
- GEL: Georgian Lari (fiat) vs Gelato Network token (crypto)

**Fallback**: Return "Unknown" for unrecognized values, do not guess
```

### Error Handling Specifications

When specifying error behavior:

1. **What exception type** to raise
2. **What cleanup** must occur before re-raising
3. **What must NOT happen** (silent continuation, partial output)

**Example**:

```markdown
### Error Handling

- On validation failure (FileProcessingError):
  - Remove partial Crypto sheet if created
  - Close workbook
  - Remove stale output file
  - Re-raise the exception
- On rendering error (any Exception):
  - Same cleanup as above
  - Re-raise the exception
- NEVER silently continue without crypto data
```

### Validation Sequence Specifications

When specifying validation timing:

1. **Order matters**: List steps in exact sequence
2. **What is validated when**: Be explicit about which entries need validation
3. **Before/after relationships**: Explicitly state "validation BEFORE filtering"

**Example**:

```markdown
### Validation Sequence

1. Parse Koinly files (no validation yet)
2. Classify rewards (taxable_now vs deferred)
3. Validate TAXABLE_NOW entries for mandatory IRS fields
4. Aggregate validated entries
5. Filter immaterial entries (|gain/loss| < 1 EUR) - AFTER validation

**Critical**: Validation occurs BEFORE filtering to catch invalid small gains
```

## Common Anti-Patterns

### Ambiguous Pattern Language

| Anti-Pattern | Correct Specification |
|--------------|---------------------|
| "Normalize (2) suffix" (no target) | "Normalize ONLY exact pattern `Platform (n)` using `re.match(r"^Platform \(\d+\)$")`" |
| "Strip numbered suffixes" (too broad) | "Strip suffix ONLY for specific platform; preserve others explicitly" |
| "Match patterns like..." | "Exact pattern: `^PATTERN$` with examples of what NOT to match" |

### Undefined Terms

| Anti-Pattern | Correct Specification |
|--------------|---------------------|
| "Denominated rewards" (what denom?) | "Rewards in ISO 4217 fiat currency codes (excluding XAG, XAU, ...)" |
| "Before aggregating" (what order?) | "Step 3: Validate → Step 4: Aggregate (validation BEFORE aggregation)" |
| "Fail with clear error" (what cleanup?) | "Raise ErrorType, cleanup (remove sheet, close file), re-raise" |

### Missing Negative Requirements

| Anti-Pattern | Correct Specification |
|--------------|---------------------|
| No negative requirements | "DO NOT normalize other platforms' numbered wallets; preserve explicitly" |
| No negative requirements | "DO NOT validate DEFERRED entries for condition X; only validate TAXABLE_NOW" |
| No negative requirements | "DO NOT guess missing values; return Unknown/Fallback instead" |

## Testing Requirements

### Required Test Categories

1. **Positive tests**: What should happen
2. **Negative tests**: What should NOT happen
3. **Edge case tests**: Boundary conditions
4. **Error path tests**: Exception handling and cleanup

### Pre-Computation Bug Pattern Checks

Before finalizing tasks that involve data processing, calculations, or external data parsing, verify these common bug patterns are addressed:

| Pattern | What to Check | Example Domain |
|---------|---------------|----------------|
| **Unit verification** | Numeric fields use correct units (currency vs raw count, bytes vs KB, ms vs seconds) | Using crypto quantity instead of EUR value; treating bytes as KB |
| **Temporal gating** | Earlier events cannot consume later state | Past sell consuming future buy; old state validating new input |
| **Empty string handling** | Aggregation `min()`/`max()` filters out empty strings | `""` corrupts `min()` aggregation keys |
| **Boundary values** | Tests include exact threshold values | Off-by-one: 365 vs 364/366; threshold vs threshold±1 |
| **Zero-cost propagation** | Zero-cost entries flagged with `review_required` | Distinguishing exhaustion from legitimate zero-cost (airdrops, gifts) |
| **Fee/completeness** | All cost components included in calculations | Disposal fee missing from gain; tax withheld from net proceeds |
| **Error scope** | Row-level parse errors caught per-row | One bad row crashes entire pipeline |
| **Policy-arm coverage symmetry** | When centralizing a shared helper across callers with divergent raise/degrade policies, pin each caller's policy arm for every failure kind; a test gap found for one caller must be audited across siblings, starting with the safety-critical kind (wrong policy silently corrupts an aggregate). See `development_lessons.md` #136 | Guarded-JSON loader: one caller must RAISE on stat_error (double-counting hazard), another degrades; copying the degrade policy flips the raise to a silent empty |

**How to apply:** When writing a task that processes external data or performs calculations, mentally walk through each item's lifecycle and verify:
- What happens when a field is empty, zero, or max value?
- What happens when a timestamp is out of order or missing?
- What happens when a pool/set is exhausted?
- Are all components (principal, fee, tax) accounted for?
- Does one bad item crash the pipeline or get skipped with a warning?

**Naming the root cause:** When a pre-computation or invariant check above addresses a
recurring failure shape, name the family (A to H) from the principle catalog
(`coding_guidelines.md` #17-#25) and consult `docs/maintenance/principle-index.md` to
recall prior incidents by problem shape rather than re-deriving the lesson (see the
`generalize` skill).

### Test Specification Format

1. **Positive tests**: What should happen
2. **Negative tests**: What should NOT happen
3. **Edge case tests**: Boundary conditions
4. **Error path tests**: Exception handling and cleanup

### Test Specification Format

```markdown
### Testing Requirements

**Positive tests** (what should happen):
- Input X produces expected output Y

**Negative tests** (what should NOT happen):
- Input Z should NOT be normalized/processed/modified

**Edge cases** (boundary conditions):
- Empty input → specific expected behavior (preserved, error, or default)
- Max value input → specific expected behavior
- Boundary value at threshold → specific expected classification

**Error path tests**:
- ErrorType A triggers cleanup and re-raise
- ErrorType B triggers fallback behavior with warning
```

### Integration Testing Requirements

For multi-step pipelines (e.g., parse → transform → persist), include integration tests that exercise the full flow, not just unit tests for individual components.

**When integration tests are required:**
- Data flows through multiple modules before reaching output
- Cross-module state needs verification (e.g., transformation + aggregation + rendering)
- Complex interactions (e.g., deferred resolution, cross-component references) that only emerge end-to-end

**Guidance:** Write integration tests that verify the full end-to-end behavior, not just individual component correctness.

### Boundary Test Checklist

When implementing threshold-based logic (`>=`, `<=`, `>`, `<`), always include tests at the exact boundary value:

| Threshold Type | Example Boundary Test |
|-----------------|------------------------|
| Holding period | Exactly 365 days (not just 364 and 366) |
| Zero-basis threshold | Exactly `threshold` EUR value |
| Pagination limit | Exactly `page_size` items |
| Rate limits | Exactly at limit (not just below/above) |

Off-by-one errors at boundaries are a common source of incorrect tax classifications and business logic bugs.
- ByBit (2) → ByBit (normalized)

**Negative tests** (what should NOT happen):
- Kraken (2) → Kraken (2) (preserved - not ByBit)
- ByBit Earn (2) → ByBit Earn (2) (preserved - sub-product)

**Edge cases**:
- Empty wallet → "" (preserved)
- Whitespace wallet → "  " (preserved)

**Error path tests**:
- FileProcessingError triggers cleanup and re-raise
- ValueError during rendering triggers cleanup and re-raise
```

## Acceptance Criteria Checklist

Each task should end with:

```markdown
### Definition of Done

- [ ] Implementation matches exact specification (not broader)
- [ ] All edge cases from specification are handled
- [ ] All negative requirements are satisfied (nothing unwanted happens)
- [ ] All positive tests pass
- [ ] All negative tests pass
- [ ] All edge case tests pass
- [ ] Error path tests verify cleanup occurs
- [ ] Documentation updated (README, CLAUDE.md, domain docs)
```

## Domain-Specific Guidelines

For project-specific domains (e.g., crypto tax):

1. **Create domain-specific implementation guidelines** in `docs/maintenance/<domain>_implementation_guidelines.md`
2. **Reference from CLAUDE.md/AGENTS.md** in Domain Knowledge References section
3. **Do NOT create generic skills** for project-specific domain knowledge
4. **Update lessons learned** in post-mortem documents after each major feature

## References

- Post-mortem: `docs/history/investigations/aggregate-crypto-rewards-review-analysis.md`
- Crypto implementation: `docs/maintenance/crypto_implementation_guidelines.md`
- Plan example: `docs/history/plans/aggregate-crypto-rewards-income.md`

## Return-Type Must Carry the Data Promised in Error Messages

When a plan task promises an error message containing structured data (e.g. "include row 47 in
the review reason"), verify that the return type of the function producing that data actually
carries the structured information.

**Common failure:** promising "TH parse error on row <N>: ..." in a review reason, but specifying
the return type as `set[str]` (bare asset names). A `set[str]` cannot reconstruct which row
failed. The correct type is `dict[str, list[int]]` (asset → failed row indices) or an equivalent
structured record.

**Check:** for every plan task that mentions row indices, line numbers, record IDs, or similar
position data in error messages, verify the return type of the producing function carries those
values all the way to the consuming function.

---

## Verify Pipeline Execution Order Before Reusing an Existing Mechanism

Before writing a plan task that reuses an existing pipeline mechanism for a new case, verify the
execution order allows it.

**Example from this project:** same-asset cross-platform transfers were planned to reuse
`resolve_cross_asset_exchanges` (which resolves deferred acquisitions from carry-over).
The plan failed because `resolve_cross_asset_exchanges` runs **before** per-platform FIFO for
the current asset, so the sender platform's carry-over does not yet exist at resolution time.
The fix requires either a second pass or platform-ordered processing.

**Check:** for each "reuse existing mechanism X for new case Y" plan task, trace the moment X
runs in the pipeline and verify that all inputs X needs for Y exist at that moment.

---

## Key-Type Changes Require Tracing All Producers AND Consumers

When a plan task changes the key type of a shared data structure (e.g. from `str` to
`tuple[str, str]`), trace all **producers** (functions that write entries into the structure) and
all **consumers** (functions that look up entries) and update every one of them.

**Example from this project:** changing `merged_carryover` from `tx_key → Decimal` to
`(tx_key, platform) → Decimal` required not just updating the merge loop (producer) but also
adding a sender-platform correlation map so the lookup in `resolve_cross_asset_exchanges`
(consumer) knew which platform to pair with each `tx_key`. The producer-only change would have
left the consumer unable to form the new key.

**Check:** grep for every write to the data structure AND every read from it. List them in the
plan task. For each reader, verify it has access to all components of the new key.

---

## Sequence a Config/TOML Task Adjacent to the Production Task That Reads the Key

When a plan introduces a new config/decision-point key (for example a `TaxJurisdictionConfig`
boolean or a `decision_points/<year>.toml` flag) that production code in an earlier task reads,
sequence the config task **adjacent to or before** the production task, or explicitly document
the expected transient RED between them.

**Why this matters:** Per-task GREEN verification is the basic safety signal during plan
execution. When Task N (production code) ships before Task N+1 (the TOML/config key it reads),
the full suite is RED at the boundary between them (in the modelo3-flag-based-dispatch plan,
7 integration/e2e tests stayed RED after Task 2 because the production TOML lacked the two new
keys). A transient full-suite RED between two tasks hides any NEW breakage the second task
introduces and forces the orchestrator to verify GREEN independently of the per-task signal.

**Acceptable orderings, in preference:**
1. Config/TOML task first, then the production task that reads the key (suite stays GREEN at
   every boundary; the production task's per-task GREEN is meaningful on its own).
2. If research/design forces the production task first (so the key name and semantics are
   settled by real code), put the config task immediately next and have the production task
   log its deferred failures by name. The plan must state that the full suite is expected RED
   between the two tasks, so the orchestrator does not read it as a regression.

**Do not** leave more than one task boundary between a production task and the config key it
reads, and never end the plan with the config task still pending.

## Staged Replacement Planning

When an existing feature is misleading or unsafe and the correct replacement design still
needs research, split the work into two plans or phases:

1. cleanup/removal plan that deletes the misleading behavior, updates tests, and keeps the UI honest
2. follow-up research/implementation plan that designs and builds the replacement

Do not combine "remove incorrect behavior", "invent new matching logic", and "research the
true source of truth" into one implementation batch unless the replacement is already
specified well enough to test deterministically.

## Presentation Artifacts For Repository Value Demos

When a plan includes explaining what the repository accomplishes, prefer a dedicated
presentation artifact under `docs/maintenance/` rather than overloading `README.md`.

The first version should usually be Markdown slide notes that include:

1. one section per slide
2. draft wording for the message
3. references to concrete demo assets, such as CSV inputs, generated workbooks, or screenshots
4. explicit citation points for official sources when the slide makes legal or filing claims

Prefer Markdown slide notes as the default first format because they are version-controlled,
easy to review in pull requests, and require no separate presentation toolchain. Move format
justification and other authoring meta-notes here or to similar guidance documents, not into
the presentation artifact itself.

Use `README.md` only as a short discovery pointer to the dedicated presentation artifact.
