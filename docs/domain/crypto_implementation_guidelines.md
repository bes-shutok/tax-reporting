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
- **MNT**: Mongolian tögrög (fiat) vs Mantle L2 token (crypto) → crypto wins

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
- Ticker collisions (GEL, MNT)

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

_CRYPTO_SHEET_NAMES = ("Crypto Gains", "Crypto Rewards", "Crypto Reconciliation")

@contextmanager
def _crypto_sheet_cleanup(workbook, extract):
    """Ensure cleanup on any exception from crypto sheet generation."""
    try:
        yield
    except Exception:
        # Same cleanup regardless of exception type
        for name in _CRYPTO_SHEET_NAMES:
            if name in workbook.sheetnames:
                workbook.remove(workbook[name])
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
            write_crypto_gains_sheet(workbook, crypto_tax_report)
            write_crypto_rewards_sheet(workbook, crypto_tax_report, aggregated_rewards)
            write_crypto_reconciliation_sheet(workbook, crypto_tax_report)
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
            write_crypto_gains_sheet(workbook, crypto_tax_report)
            write_crypto_rewards_sheet(workbook, crypto_tax_report, aggregated_rewards)
            write_crypto_reconciliation_sheet(workbook, crypto_tax_report)
            crypto_sheet_created = True
    except Exception:
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
   - `valid_from` date (when this mapping was verified from source documents)
   - Basis (why this country was chosen)

2. **`mapping_decision_log.md`** - Detailed reasoning with:
   - Decision ID (CMD-XXX)
   - Links to archived source documents
   - Full explanation of the reasoning

### Entity Selection Criteria (Portuguese Tax Rules)

**Detailed reference**: See `docs/tax/crypto-origin/entity_selection_criteria.md` for complete entity selection hierarchy.

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

**Implemented Feature**: The code now supports date-based lookup via the `transaction_date` parameter in `resolve_operator_origin()`.

**Temporal Validity Checking**:
- All `OperatorOrigin` instances include temporal fields:
  - `service_start_date`: When the platform actually started offering this service
    - Used for transaction date matching to avoid false positives on historical data
    - Prevents historical transactions from triggering "outside validity period" warnings
  - `valid_from`: When this specific mapping was verified from source documents
    - Used for audit trail and documentation purposes
    - Preserves verification timeline for historical tax filings
  - Optional `valid_until` date for expired mappings
- When `transaction_date` is provided, the function checks if the date falls within the service period using `service_start_date`
- If a transaction predates `service_start_date`, a warning is logged and the mapping is marked for review
- If `transaction_date` is outside known validity periods, a warning is logged for audit trail purposes

**Implementation Pattern**:

```python
def resolve_operator_origin(
    platform: str,
    transaction_type: str | None = None,
    transaction_date: str | None = None,  # NEW: supports "YYYY-MM-DD" or "YYYY-MM-DD HH:MM:SS"
) -> OperatorOrigin:
    """Resolve operator metadata with optional temporal validity checks.

    When transaction_date is provided, performs date-based mapping selection
    to ensure historical tax filings use the correct mapping for that period.

    Args:
        platform: Wallet or platform name
        transaction_type: Optional hint for service scope (e.g., "fiat_deposit" vs "crypto_deposit")
        transaction_date: Optional transaction date for temporal validity checks

    Returns:
        OperatorOrigin with platform metadata and validity information.
    """
```

**Helper Functions**:
- `_parse_transaction_date(transaction_date: str | None) -> str | None`: Parses transaction dates to ISO format (YYYY-MM-DD) for temporal validity checks. Supports formats: "YYYY-MM-DD" or "YYYY-MM-DD HH:MM:SS".
- `_is_temporally_valid(service_start_date: str | None, valid_until: str | None, transaction_date: str) -> bool`: Checks if a mapping is valid for a given transaction date using `service_start_date` for the lower bound (not `valid_from`, which is the verification date). Returns True if `service_start_date <= transaction_date <= valid_until` (or no validity constraints).

**Call Sites**: The parsing functions pass transaction dates to `resolve_operator_origin()`:
- `_parse_capital_gains_file()`: passes `disposal_date` from CSV rows
- `_parse_income_file()`: passes `date` from CSV rows

**Testing Requirements**:
- Platform mappings may have `valid_from=None` for historical operators where the exact verification date is unknown
- Tests cover date boundary cases (before, during, after validity period)
- Tests verify warning logs for transactions outside validity period
- Tests verify backward compatibility (works without `transaction_date`)

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
                review_required=False,
                service_start_date="2015-01-01",  # Wirex founded ~2014-2015
                valid_from="2026-03-08",  # Split-scope verified 2026-03-08
            )
        return OperatorOrigin(
            platform="Wirex",
            service_scope="crypto",
            operator_entity="Wirex Digital (crypto operator, verify account terms)",
            operator_country="HR",
            source_url="https://wirexapp.com/legal",
            source_checked_on="2026-03-08",
            confidence="medium",
            review_required=False,
            service_start_date="2015-01-01",  # Wirex founded ~2014-2015
            valid_from="2026-03-08",  # Split-scope verified 2026-03-08
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

## Review Flag Specificity

### Pattern: review_reason Field

Every crypto entry that sets `review_required=True` must also populate `review_reason` with a specific, actionable explanation. The Excel output renders this as "YES: \<reason\>" rather than a bare boolean.

### Where review_reason Is Set

| Location | Trigger | Example Reason |
|----------|---------|---------------|
| `resolve_operator_origin()` | ByBit platform | "Bybit uses account-region specific entities; verify your account region matches the operator entity" |
| `resolve_operator_origin()` | Unknown platform | "Unknown platform - operator origin could not be determined automatically" |
| `resolve_operator_origin()` | Transaction date unparseable | "Transaction date format could not be parsed; temporal validity check skipped" |
| `resolve_operator_origin()` | Date outside service period | "Transaction date X is outside known service period [Y, Z] for platform" |
| `_parse_capital_gains_file()` | Missing cost basis with proceeds > 0 | "Missing cost basis with tax impact - verify cost calculation" |
| `_parse_income_file()` | Foreign tax field unparseable | "Foreign tax field could not be parsed - verify tax credit manually" |

### Aggregation of review_reason

When entries are aggregated by `_aggregate_capital_entries()`, multiple distinct reasons are joined with "; " using `dict.fromkeys()` to deduplicate while preserving order:

```python
review_reason="; ".join(dict.fromkeys(e.review_reason for e in group if e.review_reason)) or None,
```

### Lessons Learned

1. Bare "TRUE" review flags required users to trace through source data to understand why. Specific reasons eliminate this round-trip.
2. The `review_reason` field is optional (`str | None`) — entries without review flags have `None`, not an empty string.
3. When adding a new review flag condition, always provide a `review_reason` that tells the user what to verify, not just that something needs review.

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
    write_crypto_gains_sheet(workbook, crypto_tax_report)
    write_crypto_rewards_sheet(workbook, crypto_tax_report, aggregated_rewards)
    write_crypto_reconciliation_sheet(workbook, crypto_tax_report)
except Exception as e:
    logger.warning("Crypto failed, continuing: %s", e)
    # Returns successfully but report is incomplete!

# ✅ CORRECT - Clean up and re-raise
try:
    write_crypto_gains_sheet(workbook, crypto_tax_report)
    write_crypto_rewards_sheet(workbook, crypto_tax_report, aggregated_rewards)
    write_crypto_reconciliation_sheet(workbook, crypto_tax_report)
except Exception as e:
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

## Aggregation Grouping Invariants

### Expected Repeated Dates vs Forbidden Duplicate Aggregation Keys

When reviewing crypto capital gains output, it is critical to distinguish between two
different phenomena that can look similar in a spreadsheet:

**Expected: repeated acquisition_date across disposal events.**
A single purchase (e.g. 2024-07-27) may supply FIFO lots sold at multiple
different later disposal dates. Each disposal is a separate taxable event. The shared
acquisition date simply reflects the common purchase that was partially sold over
time. This is normal and does NOT indicate a grouping regression.

**Expected: repeated disposal_date with a differing aggregation dimension.**
Rows sharing a disposal_date but differing in `asset`, `platform`, or `holding_period`
must stay separate. Each distinct `(disposal_date, asset, platform, holding_period)`
tuple represents a separate aggregation group per PT-C-027.

**Forbidden: duplicate rows with the same full aggregation key.**
After `_aggregate_capital_entries()`, no two output rows may share the exact key
`(disposal_date, asset, platform, holding_period)`. If they do, the aggregation
function has a regression. The durable regression test
`test_aggregate_never_emits_duplicate_keys` guards this invariant.

### How to Diagnose a Reported Grouping Regression

1. Identify the reported date. Determine whether it appears in the `Acquisition date`
   column or the `Disposal date` column.
2. If the date is an acquisition date shared across multiple disposals, this is
   expected behavior (see above). No fix needed.
3. If the date is a disposal date, check the full aggregation key
   `(disposal_date, asset, platform, holding_period)` for each supposedly-duplicate row.
   If any key field differs, the rows are intentionally separate.
4. Only if two rows share the identical 4-tuple key after aggregation is there a true
   regression. File a bug referencing `test_aggregate_never_emits_duplicate_keys`.

### Regression Tests

| Test | Guard |
|------|-------|
| `test_aggregate_never_emits_duplicate_keys` | No duplicate aggregation keys in `_aggregate_capital_entries()` output |
| `test_same_timestamp_different_holding_period_stays_split` | Same-date rows with different holding periods stay separate (PT-C-011) |
| `test_same_disposal_date_allowed_when_other_grouping_dims_differ` | Same disposal date with different asset/platform/holding_period stays separate |
| `test_real_koinly_fixture_has_no_duplicate_aggregation_keys` | Real koinly2025 fixture has zero duplicate keys after full pipeline |
| `test_acquisition_date_repeat_is_not_a_disposal_grouping_issue` | Shared acquisition date across multiple disposals is not a bug |

## Koinly Export Files

### File Structure and Usage

Koinly generates multiple CSV files from tax reports. Only a subset is loaded by the crypto workbook builder.

| File | Current Usage |
|------|---------------|
| `koinly_*_capital_gains_report_*.csv` | Used for capital entries |
| `koinly_*_income_report_*.csv` | Used for reward entries |
| `koinly_*_transaction_history_*.csv` | Used for token origin resolution via `TokenOriginResolver` |
| `koinly_*_beginning_of_year_holdings_report_*.csv` | Used for opening holdings reconciliation |
| `koinly_*_end_of_year_holdings_report_*.csv` | Used for closing holdings reconciliation |

### Token Origin

The legacy same-day disposal-context guessing heuristic was removed in the `remove-legacy-token-origin-and-add-safe-examples` plan (2026-04-05). It has been replaced by the `TokenOriginResolver` described below.

## Token Origin Resolution

### Overview

The `TokenOriginResolver` populates the `Token origin` column in the Crypto sheet by correlating capital gains rows with the Koinly transaction history. Because the Koinly capital gains CSV provides no transaction ID, lot ID, or hash, all matching is implicit via `(date, asset, wallet)` correlation. This is best-effort, not exact.

### Data Model

```python
class AcquisitionMethod(Enum):
    DIRECT_PURCHASE = "direct_purchase"
    SWAP_CONVERSION = "swap_conversion"
    BRIDGE_TRANSFER = "bridge_transfer"
    DEFI_YIELD = "defi_yield"
    REWARD = "reward"
    TRANSFER = "transfer"
    UNKNOWN = "unknown"

@dataclass(frozen=True)
class TokenOrigin:
    acquired_from_asset: str
    acquired_from_platform: str
    acquisition_method: AcquisitionMethod
    confidence: str  # "high", "medium", or "low"
```

### Inputs

| Input | Source | Purpose |
|-------|--------|---------|
| Transaction history CSV | `koinly_*_transaction_history_*.csv` | Parsed once at resolver construction; builds a lookup indexed by `(date, asset, wallet)` |
| Capital gains row fields | `Date Acquired`, `Asset`, `Wallet Name`, `Notes` | Used to query the lookup at resolve time |

### Resolution Logic

1. Parse the transaction history CSV at construction, indexing each row by `(date, received_currency, normalized_wallet)`.
2. For each capital gains row, call `resolve(acquisition_date, asset, wallet, notes)`.
3. Look up matching acquisition records. If none found, return `unknown` with `low` confidence.
4. If the acquisition date is `1970-01-01` (Koinly's fallback for unknown), always return `unknown`.
5. Among multiple matches, select the record with the highest confidence. If multiple records share the same top confidence but disagree on method or source asset, downgrade to `low`.
6. If the capital gains row has `Missing cost basis` in notes, override confidence to `low`.

### Confidence Levels

| Level | When Assigned |
|-------|--------------|
| `high` | Transaction history row has a `TxHash` (explicit on-chain identifier) |
| `medium` | Matched via implicit date/asset/wallet correlation only |
| `low` | No match, ambiguous match, or `Missing cost basis` flag |

### Transaction Type Mapping

| Transaction History `Type` | Acquisition Method |
|---------------------------|-------------------|
| `exchange` | `swap_conversion` |
| `transfer` | `bridge_transfer` |
| `crypto_deposit` or `fiat_deposit` with `reward`/`cashback` tag | `reward` |
| `crypto_deposit` or `fiat_deposit` with `lending`/`interest` tag | `defi_yield` |
| `fiat_deposit` (no special tag) | `direct_purchase` |
| `crypto_deposit` (no special tag) | `transfer` |

### Output Format

The `Token origin` column in the workbook renders as:
- Non-blank: `"FROM_ASSET (method, confidence confidence)"` (e.g., `"BTC (swap_conversion, medium confidence)"`)
- Blank: when method is `unknown`

### Edge Cases

| Edge Case | Behaviour |
|-----------|-----------|
| No transaction history file | Resolver constructed with no lookup; all resolves return `unknown` |
| Acquisition date = `1970-01-01` | Returns `unknown` immediately |
| Multiple matches for same key | Best-confidence record selected; if tied and conflicting, confidence downgraded to `low` |
| `Missing cost basis` in notes | Confidence forced to `low` regardless of match quality |
| Pre-Koinly acquisition dates | No match in lookup; returns `unknown` |

### Testing Requirements

- Test positive matches (exchange, transfer, deposit rows in transaction history)
- Test fallback to `unknown` (no history file, no matching date, epoch date)
- Test multiple-match disambiguation (same confidence, conflicting methods)
- Test confidence downgrade for `Missing cost basis`
- Test that the workbook `Token origin` column shows the expected string format

### Manual Review Reduction Opportunities

Analysis of Koinly exports reveals these fixable false-positive triggers:

| Trigger | Root Cause | Fix |
|---------|-----------|-----|
| "Missing cost basis" with 0 EUR proceeds | Koinly marks as missing but disposal has 0 value | Only flag if `proceeds_eur > 0` |
| Character encoding (WBТC) | Cyrillic 'Т' (U+0422) instead of 'T' | Unicode normalize before parsing |
| Temporal validity warnings | Historical transactions before `service_start_date` | Use `service_start_date` separate from `valid_from` |

## References

- Plan: `docs/plans/aggregate-crypto-rewards-income.md`
- Plan: `docs/plans/crypto_manual_review_reduction.md` (token swap history — superseded; heuristic removed 2026-04-05)
- Plan: `docs/plans/2026-04-05-koinly-first-token-origin.md` (implemented: deterministic origin matching via `TokenOriginResolver`)
- Rules: `docs/domain/crypto_rules.md`
- Guidelines: `docs/domain/crypto_reporting_guidelines.md`
- Chain sources: `docs/tax/crypto-origin/`
- Post-mortem: `docs/post-mortem/aggregate-crypto-rewards-review-analysis.md`
