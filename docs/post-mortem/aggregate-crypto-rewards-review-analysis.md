# Post-Mortem: Aggregate Crypto Rewards Review Load Analysis

**Date**: 2026-03-21
**Branch**: `reduce-lines-in-crypto-rewards`
**Plan**: `aggregate-crypto-rewards-income.md`

## Executive Summary

The aggregate crypto rewards feature required **9 Codex iterations + 4 Claude review iterations** to reach approval. This analysis identifies the root causes of review churn and provides concrete recommendations for reducing review load in future implementations.

**Key Finding**: Most issues stemmed from ambiguous requirements, unspecified edge cases, and missing acceptance criteria in the plan document.

---

## Issue Categories and Iteration Count

| Category | Iterations | Root Cause | Preventable? |
|----------|------------|------------|--------------|
| Fiat currency classification | 4+ | Incomplete definition of "fiat" | Yes |
| Wallet normalization scope | 4 | Ambiguous "ByBit (2)" language | Yes |
| Exception handling/cleanup | 3 | No error-path acceptance criteria | Yes |
| Validation timing | 3 | Unclear "when" specification | Yes |
| Test coverage gaps | 2 | No test requirement for critical functions | Yes |
| Dead code | 1 | Code evolved but plan didn't address | Partially |
| Documentation gaps | 1 | Not in acceptance criteria | Yes |

**Total Preventable Issues**: ~85% (7 of 8 categories)

---

## Detailed Issue Analysis

### 1. Fiat Currency Classification (4+ iterations)

**What Went Wrong**:
- Iteration 1-2: Hand-maintained allowlist missing AED, THB, PHP, RSD, UAH, PKR, KZT, GEL, AMD
- Iteration 3: Syntax error in exception handling (`except AttributeError, TypeError:`)
- Iteration 4-5: Added pycountry but included non-fiat codes (XAG, XAU, XPD, XPT, CHE, CLF, MXV, UYI)
- Iteration 6-7: GEL ticker collision (Gelato token vs Georgian Lari)
- Iteration 8-9: Still missing fund/unit codes (BOV, CHW, COU, USN, UYW)

**Plan Language (Task 1, line 22)**:
> "Treat crypto-denominated rewards as deferred by default, unless the code can positively identify an official exception bucket that requires immediate taxation."

**Problem**: Plan never defined what constitutes "fiat" vs "crypto". Implementers had to discover this through review feedback.

**Recommendation**:
```markdown
### Task 1: Classify rewards before aggregation

- [x] Add a reward-tax classification step...
- [x] **Fiat currency definition**: Use ISO 4217 standard as the source of truth for fiat currencies
  - Exclude commodity codes: XAG, XAU, XPD, XPT (precious metals)
  - Exclude special codes: XBA, XBB, XBC, XBD, XDR, XSU, XUA, XTS, XXX
  - Exclude fund/unit codes: BOV, CHE, CHW, CLF, COU, MXV, USN, UYI, UYW
  - **TICKER COLLISIONS**: Some tickers represent both fiat and crypto tokens
    - GEL = Georgian Lari (fiat) and Gelato Network token (crypto)
    - For collisions, crypto token takes precedence (deferred)
    - Maintain `_CRYPTO_TOKEN_FIAT_COLLISIONS` set for these known cases
```

### 2. Wallet Normalization Scope (4 iterations)

**What Went Wrong**:
- Iteration 1: Used regex `r" \(\d+\)$"` for ALL wallets (not just ByBit)
- Iteration 2-3: Restricted to `startswith("ByBit")` but still matched "ByBit Earn (2)"
- Iteration 4: Changed to exact pattern `r"^ByBit \(\d+\)$"`

**Plan Language (Task 4, line 45)**:
> "Add a wallet-normalization rule so `ByBit` and `ByBit (2)` are treated as the same account..."

**Problem**: The language "ByBit (2) -> ByBit" was interpreted as a pattern, not a specific case.

**Recommendation**:
```markdown
### Task 4: Normalize wallet aliases before aggregation

- [X] Add a wallet-normalization rule **ONLY for the specific ByBit case**:
  - EXACT pattern: `ByBit (2)`, `ByBit (3)`, `ByBit (4)`, etc. → `ByBit`
  - DO NOT normalize other platforms (e.g., preserve `Kraken (2)`, `Ethereum (ETH) - 0xabc (2)`)
  - DO NOT normalize ByBit sub-products (e.g., preserve `ByBit Earn (2)`, `ByBit Savings (3)`)
  - Implementation: `re.match(r"^ByBit \(\d+\)$", wallet)` not `startswith("ByBit")`
- [X] Add tests proving:
  - ByBit (2) → ByBit (normalized)
  - ByBit Earn (2) → ByBit Earn (2) (preserved)
  - Kraken (2) → Kraken (2) (preserved)
```

### 3. Exception Handling and Cleanup (3 iterations)

**What Went Wrong**:
- Iteration 1: Broad `except Exception` silently swallowed errors
- Iteration 2: Removed broad exception but skipped cleanup on `FileProcessingError`
- Iteration 3: Added cleanup to `FileProcessingError` path

**Plan Language (Task 2, line 33)**:
> "Fail generation with a clear error if an immediately taxable row cannot be assigned all mandatory IRS fields..."

**Problem**: Plan specified "fail with clear error" but not cleanup behavior.

**Recommendation**:
```markdown
### Task 2: Add an IRS-ready aggregation model

- [x] **Error handling requirements**:
  - On validation failure: Remove partial Crypto sheet, close workbook, remove stale output file, re-raise
  - On rendering error: Remove partial Crypto sheet, close workbook, remove stale output file, re-raise
  - NEVER silently continue without crypto data (only `main.py` may skip loading Koinly files)
  - All exception paths must ensure proper cleanup before re-raising
```

### 4. Validation Timing (3 iterations)

**What Went Wrong**:
- Iteration 1: Validation happened AFTER filtering, missing small gains
- Iteration 2: Moved validation before filtering
- Iteration 3: Clarified only TAXABLE_NOW needs validation (not DEFERRED)

**Plan Language (Task 2, line 33)**:
> "Fail generation with a clear error if an immediately taxable row cannot be assigned all mandatory IRS fields..."

**Problem**: "Before aggregating" (line 29) was ambiguous - before filtering? before aggregation? after parsing?

**Recommendation**:
```markdown
### Task 2: Add an IRS-ready aggregation model

- [x] **Validation sequence** (order matters):
  1. Parse Koinly files (all rows, no validation yet)
  2. **Validate TAXABLE_NOW entries for mandatory IRS fields** (income_code, source_country)
  3. Aggregate validated TAXABLE_NOW entries by (income_code, source_country)
  4. Filter out immaterial entries (|gain/loss| < 1 EUR) - AFTER validation
  5. DEFERRED_BY_LAW entries: No country validation required (support detail only)
```

### 5. Missing Test Coverage (2 iterations)

**What Went Wrong**:
- Iteration 1: No tests for `_normalize_platform_name()`, chain derivation
- Iteration 2: Added tests for these functions

**Problem**: Plan specified "Add unit tests for at least: crypto-denominated reward, fiat-denominated reward..." but not for critical helper functions.

**Recommendation**:
```markdown
### Task 1: Classify rewards before aggregation

- [x] Add unit tests for classification:
  - Crypto-denominated reward → DEFERRED_BY_LAW
  - Fiat-denominated reward → TAXABLE_NOW
  - Exception-bucket reward → TAXABLE_NOW
  - DeFi reward → DEFERRED_BY_LAW

### Task 4: Normalize wallet aliases before aggregation

- [X] **Required test coverage** for `_normalize_platform_name()`:
  - ByBit (2) → ByBit (normalized)
  - ByBit Earn (2) → ByBit Earn (2) (preserved - edge case)
  - Kraken (2) → Kraken (2) (preserved - not ByBit)
  - Empty wallet → "" (preserved)
  - Whitespace wallet → "  " (preserved)

### Task 5: Add chain derivation

- [x] **Required test coverage** for `_derive_chain()`:
  - Ledger Berachain (BERA) → Berachain
  - Ledger SUI → SUI
  - Ethereum (ETH) - 0x6ABd...15 → Ethereum
  - ByBit (2) → ByBit
  - Blank wallet → Unknown
  - All chains in `docs/tax/crypto-origin/chain-registry.md` must have tests
```

---

## Recommendations for Plan Documents

### 1. Explicit Edge Case Sections

Add a dedicated "Edge Cases and Gotchas" section to each task:

```markdown
### Task 1: Edge Cases

**Fiat Currency Classification Edge Cases**:
- Commodity codes (XAG, XAU, XPD, XPT) are NOT fiat
- Fund/unit codes (BOV, CHE, CLF, COU, MXV, USN, UYI, UYW) are NOT fiat
- Ticker collisions: GEL (fiat) vs GEL (Gelato token) - crypto wins
- If pycountry is not available: Fail with clear error (do not guess)

**Reward Classification Edge Cases**:
- Stablecoins (USDT, USDC, DAI) are crypto-denominated → DEFERRED_BY_LAW
- Fiat-backed tokens that track currency but are on-chain → DEFERRED_BY_LAW
- Only actual fiat currency payouts (EUR, USD, etc.) → TAXABLE_NOW
```

### 2. Acceptance Criteria Checklist

Add explicit acceptance criteria to each task:

```markdown
### Task 2: Acceptance Criteria

**Definition of Done**:
- [ ] `aggregate_taxable_rewards()` raises `FileProcessingError` on missing country
- [ ] Validation happens BEFORE filtering (small gains still validated)
- [ ] Only TAXABLE_NOW entries validated (DEFERRED_BY_LAW skipped)
- [ ] Aggregation key is `(income_code, source_country)`
- [ ] Foreign tax is summed per aggregation key
- [ ] Raw→aggregated trail is preserved (for audit)
- [ ] Tests cover: valid case, missing country, foreign tax summation
- [ ] Integration test verifies Excel output has correct columns
```

### 3. Negative Test Requirements

Explicitly specify what should NOT happen:

```markdown
### Task 2: Negative Requirements

**What NOT to do**:
- [ ] DO NOT validate DEFERRED_BY_LAW entries for country codes
- [ ] DO NOT aggregate before validation (would miss invalid small gains)
- [ ] DO NOT use taxpayer residence as fallback country
- [ ] DO NOT silently skip invalid entries (must raise FileProcessingError)
- [ ] DO NOT aggregate DEFERRED_BY_LAW entries into IRS-ready table
```

---

## Recommendations for Skills

### New Skill: "crypto-implementation"

Create a specialized skill for crypto tax features that encodes lessons learned:

```markdown
# crypto-implementation Skill

## Context
This skill guides implementation of crypto tax features in the tax-reporting project, incorporating lessons learned from the aggregate-crypto-rewards implementation.

## Fiat Currency Classification

When implementing fiat vs crypto classification:

1. **Use pycountry as source of truth** for ISO 4217 fiat codes
2. **Always exclude** these non-fiat ISO codes:
   - Commodities: XAG, XAU, XPD, XPT
   - Special codes: XBA, XBB, XBC, XBD, XDR, XSU, XUA, XTS, XXX
   - Fund/unit codes: BOV, CHE, CHW, CLF, COU, MXV, USN, UYI, UYW
3. **Handle ticker collisions** with `_CRYPTO_TOKEN_FIAT_COLLISIONS` set
4. **Test with**: pytest tests/unit/application/test_crypto_reporting.py

## Wallet Normalization

When normalizing wallet aliases:

1. **ONLY normalize exact pattern matches** - use `re.match()` not `startswith()`
2. **ByBit pattern**: `r"^ByBit \(\d+\)$"` - NOT "ByBit Earn (2)" or "ByBit Savings (3)"
3. **Preserve all other numbered wallets**: "Kraken (2)", "Ethereum (ETH) - 0xabc (2)"
4. **Test the negative cases** to ensure over-matching doesn't occur

## Error Handling

For crypto sheet generation:

1. **All exception paths must clean up**:
   - Remove partial Crypto sheet
   - Close workbook
   - Remove stale output file
   - Re-raise the exception
2. **Never silently continue** after rendering errors
3. **Only main.py may skip** missing/unparseable Koinly files

## Validation Sequence

Follow this exact order:
1. Parse Koinly files (no validation)
2. Classify rewards (taxable_now vs deferred)
3. **Validate TAXABLE_NOW for mandatory IRS fields**
4. Aggregate validated entries
5. Filter immaterial entries (|gain/loss| < 1 EUR)

## Testing Requirements

For any new crypto function:
- Add unit tests for all code paths
- Add integration tests for Excel output changes
- Test edge cases explicitly (empty strings, whitespace, unknown values)
- Test negative cases (what should NOT be normalized/classified)
```

### Enhance Existing "test-driven-development" Skill

Add crypto-specific guidance:

```markdown
### Crypto Feature Testing

For crypto tax features, ensure:

1. **Fiat currency tests**: Include all excluded non-fiat codes
2. **Wallet normalization tests**: Test positive (normalize) AND negative (preserve) cases
3. **Chain derivation tests**: Test all chains in `docs/tax/crypto-origin/chain-registry.md`
4. **Error path tests**: Test that FileProcessingError is raised, not caught and silenced
5. **Cleanup tests**: Verify workbook.close() and file removal on errors
```

---

## Recommendations for Review Process

### 1. Pre-Review Checklist

Before starting review, verify:

```markdown
## Pre-Review Verification

- [ ] Plan has explicit edge cases section
- [ ] Plan has negative requirements (what NOT to do)
- [ ] Plan has acceptance criteria checklist
- [ ] All critical functions have tests specified
- [ ] Error handling behavior is specified
- [ ] Cleanup behavior on errors is specified
```

### 2. First Review Focus Areas

First review should prioritize:

1. **Edge cases**: Are all edge cases in the plan covered in code?
2. **Negative tests**: Do tests verify what should NOT happen?
3. **Error paths**: Are all error paths tested and properly clean up?
4. **Validation timing**: Is validation in the correct order?

### 3. Iteration Prevention

If a finding requires clarification of plan language:

1. **Update the plan first** with clarified language
2. **Then fix the code** to match the clarified plan
3. **This prevents** future reviewers from re-raising the same issue

---

## Summary of Concrete Improvements

### Plan Document Improvements

1. Add "Edge Cases and Gotchas" section to each task
2. Add "Negative Requirements" subsection (what NOT to do)
3. Add "Acceptance Criteria Checklist" (Definition of Done)
4. Specify error handling and cleanup behavior explicitly
5. Specify validation sequence as ordered steps
6. List all test cases including negative tests

### Skills Improvements

1. Create "crypto-implementation" skill with lessons learned
2. Enhance "test-driven-development" with crypto-specific guidance
3. Add pre-review checklist to review-related skills

### Process Improvements

1. Pre-review verification of plan completeness
2. First review focuses on edge cases and error paths
3. Update plan when clarifications are needed (not just code)

---

## Estimated Impact

If these recommendations were applied:

- **Fiat currency issues**: 4+ iterations → 1 iteration (prevented)
- **Wallet normalization issues**: 4 iterations → 1 iteration (prevented)
- **Exception handling issues**: 3 iterations → 1 iteration (prevented)
- **Validation timing issues**: 3 iterations → 1 iteration (prevented)
- **Test coverage gaps**: 2 iterations → 0 iterations (prevented)

**Total**: 16+ iterations → ~4-6 iterations (75% reduction in review load)
