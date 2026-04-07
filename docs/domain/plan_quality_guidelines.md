# Plan Quality Guidelines

**Purpose**: Guidelines for writing implementation plans that minimize review iterations and ambiguity.

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
### Task: Normalize wallet aliases

- [X] Normalize ONLY the exact pattern `ByBit (n)` where n is any digit
- [X] Use exact pattern matching: `re.match(r"^ByBit \(\d+\)$", wallet)`
- [X] DO NOT normalize other platforms' numbered wallets (e.g., `Kraken (2)`)
- [X] DO NOT normalize ByBit sub-products (e.g., `ByBit Earn (2)`, `ByBit Savings (3)`)
- [X] Test negative cases to verify over-normalization doesn't occur
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
| "Normalize ByBit (2) to ByBit" | "Normalize ONLY exact pattern `ByBit (n)` using `re.match(r"^ByBit \(\d+\)$")`" |
| "Strip numbered suffixes" | "Strip suffix ONLY for ByBit; preserve other platforms" |
| "Match wallets like..." | "Exact pattern: `^PATTERN$` with examples of non-matches" |

### Undefined Terms

| Anti-Pattern | Correct Specification |
|--------------|---------------------|
| "Fiat-denominated rewards" | "Rewards in ISO 4217 fiat currency codes (excluding XAG, XAU, ...)" |
| "Before aggregating" | "Step 3: Validate → Step 4: Aggregate (validation before aggregation)" |
| "Fail with clear error" | "Raise FileProcessingError, cleanup (remove sheet, close workbook, remove file), re-raise" |

### Missing Negative Requirements

| Anti-Pattern | Correct Specification |
|--------------|---------------------|
| (none listed) | "DO NOT normalize Kraken (2), Ethereum (ETH) - 0xabc (2), etc." |
| (none listed) | "DO NOT validate DEFERRED_BY_LAW entries for country codes" |
| (none listed) | "DO NOT guess chain from asset symbol; return Unknown instead" |

## Testing Requirements

### Required Test Categories

1. **Positive tests**: What should happen
2. **Negative tests**: What should NOT happen
3. **Edge case tests**: Boundary conditions
4. **Error path tests**: Exception handling and cleanup

### Test Specification Format

```markdown
### Testing Requirements

**Positive tests**:
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

1. **Create domain-specific implementation guidelines** in `docs/domain/<domain>_implementation_guidelines.md`
2. **Reference from CLAUDE.md/AGENTS.md** in Domain Knowledge References section
3. **Do NOT create generic skills** for project-specific domain knowledge
4. **Update lessons learned** in post-mortem documents after each major feature

## References

- Post-mortem: `docs/post-mortem/aggregate-crypto-rewards-review-analysis.md`
- Crypto implementation: `docs/domain/crypto_implementation_guidelines.md`
- Plan example: `docs/plans/aggregate-crypto-rewards-income.md`

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
presentation artifact under `docs/presentation/` rather than overloading `README.md`.

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
