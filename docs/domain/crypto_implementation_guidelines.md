# Crypto Implementation Guidelines

**Purpose**: Project-specific guidance for implementing crypto tax features, incorporating lessons learned from the aggregate-crypto-rewards implementation (2026-03-21).

**Status**: Living document - update when new crypto features are implemented.

## When to Use This Document

Refer to this document when:
- Implementing new crypto tax features
- Modifying crypto reward classification logic
- Changing wallet normalization behavior
- Updating crypto validation rules
- Adding new chains or operators to mappings

## Fiat Currency Classification

### Source of Truth

Use `pycountry.currencies` as the source of truth for ISO 4217 fiat currency codes.

### Non-Fiat ISO Codes to Exclude

These ISO 4217 codes are NOT ordinary government-issued fiat currencies and must be excluded:

| Category | Codes | Reason |
|----------|-------|--------|
| Commodities | XAG, XAU, XPD, XPT | Precious metals, not fiat |
| Special/Bond | XBA, XBB, XBC, XBD, XDR, XSU, XUA, XTS, XXX | Testing/bond codes |
| Fund/Unit | BOV, CHE, CHW, CLF, COU, MXV, USN, UYI, UYW | Unit of account, not spendable |

### Ticker Collisions

Some tickers represent both ISO 4217 fiat codes AND crypto token symbols. In these cases, the crypto token takes precedence (classify as `DEFERRED_BY_LAW`):

- **GEL**: Georgian Lari (fiat) vs Gelato Network token (crypto) → crypto wins

Maintain `_CRYPTO_TOKEN_FIAT_COLLISIONS` set in `crypto_reporting.py` for these known cases.

### Implementation Pattern

```python
from functools import lru_cache
import pycountry

@lru_cache(maxsize=1)
def _get_all_fiat_currency_codes() -> set[str]:
    """Get all ISO 4217 fiat currency codes, excluding non-fiat entries."""
    non_fiat_iso_codes = {
        # Precious metals
        "XAG", "XAU", "XPD", "XPT",
        # Special codes
        "XBA", "XBB", "XBC", "XBD", "XDR", "XSU", "XUA", "XTS", "XXX",
        # Fund and unit codes
        "BOV", "CHE", "CHW", "CLF", "COU", "MXV", "USN", "UYI", "UYW",
    }
    return {c.alpha_3 for c in pycountry.currencies} - non_fiat_iso_codes
```

### Testing Requirements

When testing fiat classification, include:
- Major currencies (EUR, USD, GBP)
- Previously missing codes (AED, THB, PHP, RSD, UAH, PKR, KZT, GEL, AMD)
- Non-fiat exclusions (XAU, XAG, CLF, BOV, CHW)
- Ticker collisions (GEL)

## Wallet Normalization

### ByBit Alias Normalization (CRG-008)

**ONLY normalize the exact pattern `ByBit (n)`** where `n` is any digit.

Do NOT normalize:
- Other platforms' numbered wallets (`Kraken (2)`, `Ethereum (ETH) - 0xabc (2)`)
- ByBit sub-products (`ByBit Earn (2)`, `ByBit Savings (3)`)

### Implementation Pattern

```python
def _normalize_platform_name(wallet: str) -> str:
    """Normalize wallet names for aggregation.

    ONLY normalizes the specific ByBit case authorized in CRG-008.
    All other wallets are preserved as-is.
    """
    cleaned = wallet.strip()

    # EXACT pattern: "ByBit (n)" where n is any digit
    if re.match(r"^ByBit \(\d+\)$", cleaned):
        return "ByBit"

    return cleaned
```

### What NOT to Do

| Anti-Pattern | Why It's Wrong |
|--------------|----------------|
| `re.search(r" \(\d+\)$", cleaned)` | Matches ANY wallet with (n) suffix |
| `cleaned.startswith("ByBit")` | Also matches "ByBit Earn (2)" |
| Manual string slicing | Fragile, doesn't handle edge cases |

### Testing Requirements

Include negative tests to verify over-normalization doesn't occur:
- ByBit (2) → ByBit (normalized)
- ByBit Earn (2) → ByBit Earn (2) (preserved)
- Kraken (2) → Kraken (2) (preserved)
- Ethereum (ETH) - 0xabc (2) → preserved (content after parentheses)

## Error Handling and Cleanup

### Crypto Sheet Generation Error Handling

All exception paths must:
1. Remove partial Crypto worksheet (if created)
2. Close the workbook
3. Remove stale output file
4. Re-raise the exception

### Implementation Pattern

**Option 1: Context Manager (Recommended)**

```python
from contextlib import contextmanager

@contextmanager
def _crypto_sheet_cleanup(workbook, extract):
    """Ensure cleanup on any exception from crypto sheet generation."""
    try:
        yield
    except Exception:
        # Same cleanup regardless of exception type
        if "Crypto" in workbook.sheetnames:
            del workbook["Crypto"]
        workbook.close()
        safe_remove_file(extract)
        raise  # Re-raise after cleanup

def generate_tax_report(...) -> bool:
    crypto_sheet_created = False

    if crypto_tax_report:
        with _crypto_sheet_cleanup(workbook, extract):
            # Validation FIRST - may raise FileProcessingError
            aggregated_rewards = aggregate_taxable_rewards(crypto_tax_report)
            # Rendering SECOND - may raise any exception
            add_crypto_report_sheet(workbook, crypto_tax_report, aggregated_rewards)
            crypto_sheet_created = True

    # Continue with rest of report...
```

**Option 2: Single Exception Handler (Simpler)**

```python
def generate_tax_report(...) -> bool:
    crypto_sheet_created = False

    try:
        if crypto_tax_report:
            aggregated_rewards = aggregate_taxable_rewards(crypto_tax_report)
            add_crypto_report_sheet(workbook, crypto_tax_report, aggregated_rewards)
            crypto_sheet_created = True
    except Exception:
        # All exceptions get the same cleanup
        if "Crypto" in workbook.sheetnames:
            del workbook["Crypto"]
        workbook.close()
        safe_remove_file(extract)
        raise  # Re-raise to fail the report

    # Continue with rest of report...
```

**Why not duplicate exception handlers?**
- If cleanup is identical, use one handler
- If you need different logging/monitoring per exception type, extract cleanup to a helper function
- Context managers provide the cleanest separation of cleanup logic

### What NOT to Do

| Anti-Pattern | Why It's Wrong |
|--------------|----------------|
| `except Exception: logger.warning(); continue` | Silently drops crypto data, produces incomplete report |
| `except FileProcessingError: del sheet; raise` | Skips workbook.close() and file cleanup |
| No cleanup before re-raise | Leaves stale report file on disk |

## Validation Sequence

Follow this exact order for crypto reward processing:

1. **Parse** - Parse Koinly files, collect all rows (no validation yet)
2. **Classify** - Separate TAXABLE_NOW from DEFERRED_BY_LAW
3. **Validate** - Validate TAXABLE_NOW for mandatory IRS fields
4. **Aggregate** - Group validated entries by key
5. **Filter** - Remove immaterial entries (|gain/loss| < 1 EUR)

### Common Mistake: Validating After Filtering

```python
# ❌ WRONG - Invalid small gains slip through validation
capital_entries = [e for e in entries if abs(e.gain_loss_eur) >= 1]
_validate_capital_entries_have_valid_countries(capital_entries)  # Too late!

# ✅ CORRECT - Validate everything, then filter
_validate_capital_entries_have_valid_countries(entries)
capital_entries = _aggregate_capital_entries(entries)
capital_entries = _filter_immaterial_entries(capital_entries)
```

### Validation Requirements by Entry Type

| Entry Type | Country Validation | Reason |
|------------|-------------------|---------|
| TAXABLE_NOW rewards | YES - required | Goes in IRS-ready filing table |
| DEFERRED_BY_LAW rewards | NO - skipped | Support detail only |
| Capital gains | YES - required | All gains go in filing table |

## Chain Derivation

### Deterministic Normalization Rules

When deriving blockchain from wallet names:

1. Strip address suffixes: `- 0xabc...`, `- 5R39...`
2. Strip asset tickers in parentheses: `(ETH)`, `(SOL)`, `(BERA)`
3. Strip `Ledger ` prefix for known patterns
4. Look up in trusted registry from `docs/tax/crypto-origin/`
5. Return `Unknown` if no match (do not guess from asset symbol)

### Implementation Pattern

```python
def _derive_chain(wallet: str) -> str:
    """Derive blockchain from wallet name using deterministic rules."""
    if not wallet or not wallet.strip():
        return "Unknown"

    cleaned = wallet.strip()

    # Strip address suffixes
    cleaned = re.sub(r" - 0x[a-fA-F0-9]+$", "", cleaned)
    cleaned = re.sub(r" - [1-9A-HJ-NP-Za-km-z]{32,44}$", "", cleaned)

    # Strip asset tickers in parentheses
    cleaned = re.sub(r" \([A-Z]{3,10}\)$", "", cleaned)

    # Handle "Ledger Chain (TICKER)" pattern
    ledger_match = re.match(r"Ledger (\w+) \([A-Z]+\)", cleaned)
    if ledger_match:
        cleaned = ledger_match.group(1)

    # Normalize platform name for lookup
    normalized = _normalize_platform_name(cleaned)

    # Look up in trusted registry
    return _CHAIN_REGISTRY.get(normalized, "Unknown")
```

### Testing Requirements

Test both positive matches and negative (unknown) cases:
- Known patterns: `Ledger Berachain (BERA)` → `Berachain`
- Address stripping: `Ethereum (ETH) - 0x6ABd...` → `Ethereum`
- Unknown wallets: `RandomWallet` → `Unknown` (not guessed)

## Operator Origin Resolution

When adding or modifying operator/chain mappings:

### Documentation Requirements

Every operator mapping must be documented in TWO places:

1. **`operator_chain_origin_registry.md`** - The mapping registry with:
   - Country code
   - Authority level (official, inferred, repository override)
   - `valid_from` date (when this mapping became effective)
   - Basis (why this country was chosen)

2. **`mapping_decision_log.md`** - Detailed reasoning with:
   - Decision ID (CMD-XXX)
   - Links to archived source documents
   - Full explanation of the reasoning

### Entity Selection Criteria (Portuguese Tax Rules)

For platforms with multiple legal entities, use this hierarchy:

1. **Interface Entity**: The entity that contracts directly with the user
2. **Service-Scope Split**: For platforms that separate fiat/crypto by entity
   - Use crypto-specific entity for crypto transactions
   - Use fiat entity for fiat transactions
3. **EU/EEA Nexus**: For EEA-facing users, prefer EEA-licensed entity when available
4. **Default**: Foundation/Protocol entity when no interface entity exists

**Example - Wirex Split-Scope**:
- Fiat deposits (EUR, USD): `Wirex Limited` → GB (United Kingdom)
- Crypto deposits: `Wirex Digital` → HR (Croatia)
- Basis: Wirex account terms document the split by service scope

### Temporal Considerations

**IMPORTANT**: Operator mappings can change over time due to:
- Corporate restructuring
- Regulatory changes
- Entity mergers/acquisitions

**Current Limitation**: The code does not yet support date-based lookup. All transactions use current mappings regardless of transaction date.

**Future Plan**: See `docs/plans/temporal-crypto-operator-origins.md` for proposed temporal tracking implementation.

### Implementation Pattern

```python
def resolve_operator_origin(platform: str, transaction_type: str | None = None) -> OperatorOrigin:
    """Resolve operator metadata from platform brand and transaction type.

    Source-country resolution hierarchy for DeFi:
    1. Interface legal entity (the exposed contracting party)
    2. Protocol / foundation / sponsoring legal entity
    3. Validator operator (when identifiable)

    IMPORTANT: This function NEVER defaults to the taxpayer's residence country.
    """
    normalized = platform.lower()
    transaction_type_normalized = (transaction_type or "").lower()

    # Wirex split-scope: different entities for fiat vs crypto
    if "wirex" in normalized:
        if transaction_type_normalized.startswith("fiat"):
            return OperatorOrigin(
                platform="Wirex",
                service_scope="fiat",
                operator_entity="Wirex Limited",
                operator_country="GB",
                source_url="https://wirexapp.com/legal",
                source_checked_on="2026-03-08",
                confidence="medium",
                review_required=True,
            )
        return OperatorOrigin(
            platform="Wirex",
            service_scope="crypto",
            operator_entity="Wirex Digital (crypto operator, verify account terms)",
            operator_country="HR",
            source_url="https://wirexapp.com/legal",
            source_checked_on="2026-03-08",
            confidence="medium",
            review_required=True,
        )
```

### Common Pitfalls

| Pitfall | Why It's Wrong | Fix |
|---------|----------------|-----|
| Only updating code, not docs | Future reviewers can't verify why mapping was chosen | Always update registry AND decision log |
| Using taxpayer residence | Violates Portuguese tax rules | Use operator domicile, not user location |
| No entity selection criteria | Unclear which subsidiary to use | Follow hierarchy: interface → service-scope → EU nexus |
| Not documenting service-scope splits | Wirex GB vs HR choice is unexplained | Document basis in account terms/review |

## Documentation Updates

When implementing crypto features, update:

1. **README.md** - Describe new features and behavior
2. **CLAUDE.md** - Add new constraints with rule IDs
3. **AGENTS.md** - Synchronize with CLAUDE.md
4. **Domain docs** - Update `crypto_rules.md` or `crypto_reporting_guidelines.md` with rule IDs

## Common Implementation Pitfalls

### Pitfall 1: Using `startswith()` for Pattern Matching

```python
# ❌ WRONG - Matches too broadly
if cleaned.startswith("ByBit"):
    return "ByBit"  # Also matches "ByBit Earn", "ByBit Wallet", etc.

# ✅ CORRECT - Exact pattern match
if re.match(r"^ByBit \(\d+\)$", cleaned):
    return "ByBit"
```

### Pitfall 2: Validating After Filtering

```python
# ❌ WRONG
filtered = [e for e in entries if abs(e.gain_loss_eur) >= 1]
validate(filtered)  # Invalid small gains slip through

# ✅ CORRECT
validate(entries)  # Catch all invalid entries
filtered = [e for e in entries if abs(e.gain_loss_eur) >= 1]
```

### Pitfall 3: Silent Error Swallowing

```python
# ❌ WRONG - User has no idea crypto was skipped
try:
    add_crypto_report_sheet(...)
except Exception as e:
    logger.warning("Crypto failed, continuing: %s", e)
    # Returns successfully but report is incomplete!

# ✅ CORRECT - Clean up and re-raise
try:
    add_crypto_report_sheet(...)
except Exception as e:
    if "Crypto" in workbook.sheetnames:
        del workbook["Crypto"]
    workbook.close()
    safe_remove_file(extract)
    raise  # Let the user know something failed
```

### Pitfall 4: Forgetting Negative Tests

```python
# ❌ INCOMPLETE - Only tests what should happen
def test_normalize_bybit():
    assert _normalize_platform_name("ByBit (2)") == "ByBit"

# ✅ COMPLETE - Also tests what should NOT happen
def test_normalize_bybit():
    assert _normalize_platform_name("ByBit (2)") == "ByBit"

def test_normalize_preserves_other_platforms():
    assert _normalize_platform_name("Kraken (2)") == "Kraken (2)"
    assert _normalize_platform_name("ByBit Earn (2)") == "ByBit Earn (2)"
```

## Pre-Implementation Checklist

Before implementing new crypto features, verify the plan has:

- [ ] Explicit edge cases section
- [ ] Negative requirements (what NOT to do)
- [ ] Error handling behavior specified
- [ ] Cleanup behavior on errors specified
- [ ] Validation sequence as ordered steps
- [ ] Test cases including negative tests
- [ ] Acceptance criteria checklist

If any are missing, clarify the plan first.

## References

- Plan: `docs/plans/aggregate-crypto-rewards-income.md`
- Rules: `docs/domain/crypto_rules.md`
- Guidelines: `docs/domain/crypto_reporting_guidelines.md`
- Chain sources: `docs/tax/crypto-origin/`
- Post-mortem: `docs/post-mortem/aggregate-crypto-rewards-review-analysis.md`
