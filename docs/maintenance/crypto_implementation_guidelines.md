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
4. Look up in trusted registry from `docs/maintenance/tax/crypto-origin/`
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

**Detailed reference**: See `docs/maintenance/tax/crypto-origin/entity_selection_criteria.md` for complete entity selection hierarchy.

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
2. The `review_reason` field is optional (`str | None`): entries without review flags have `None`, not an empty string.
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

## Testing Patterns

### Missing Path Coverage

All branches of conditional logic must have dedicated test coverage. Common gaps:
- Loan activity "Open loan" (received > repaid) and "Overpaid" (repaid > received) status branches
- Non-existent file path handling (`path.exists()` vs `path is None`)
- Asset/platform mismatch validation in FIFO matching

### Boundary Condition Testing

Always test exact threshold values, not just values on either side:
- Holding period: test exactly 365 days (not just 364 and 366)
- Zero-basis threshold: test exactly `threshold` value (not just below/above)
- Off-by-one errors in these conditions produce incorrect tax classifications

### Assertion Precision

Use exact equality when the expected count is known:
- `assert len(entries) == 1` when exactly one entry is expected
- Avoid `assert len(entries) >= 1`; it hides duplications and partial failures

### False-Positive Tests

Tests can encode incorrect behavior. When implementing:
- Non-taxable exchanges (crypto-to-crypto per Art. 10(20)): ensure tests assert `taxable=False`
- If a test asserts `taxable=True`, verify it's testing the correct classification

### Code Review Quality

Multi-agent review found critical implementation bugs that single-reviewer passes missed:
- Fee unit bugs (crypto quantity vs EUR value)
- Temporal FIFO violations (future-dated lots consumed by past disposals)
- Empty string handling in aggregation

Multiple review iterations were necessary: fixes in one pass revealed new issues. Always verify findings against actual code, not assumptions from prior iterations.

### Committed Synthetic Fixtures & CI Independence

To ensure tests execute reliably in Continuous Integration (CI) and are not coupled to user-specific exports, all crypto tests MUST read committed synthetic data instead of gitignored personal exports:
- **Zero Local-Data Dependency**: Tests must never load files from gitignored personal directories like `resources/source/koinly<year>/` or check for their presence. All test fixtures must reside under `resources/source/example/koinly<year>_<scenario>/`.
- **Enforcement Mechanisms**:
  - The `test_example_data_is_synthetic` hygiene assertion scans all committed example CSVs to verify filenames end in `_synth.csv` or `_example.csv`, sensitive transaction fields are empty, and wallets match a strict synthetic allowlist.
  - The validation script (moving personal `koinly2025` aside using a trap) ensures no tests implicitly read local folders.

### Synthetic Example Data Generation & Maintenance Workflow

When creating or updating example files (e.g., under `resources/source/example/koinly2025/`):
1. **Fabricate Details**: Use fictional wallet/exchange labels (e.g. `Demo Spot`, `Demo Futures`, `Demo Payment`, `Wirex`) and simulated asset quantities.
2. **Clear Sensitive Data**: All blockchain-specific unique identifiers (`TxHash`, `TxSrc`, `TxDest`) must be completely empty (empty strings) in every row of the transaction history CSV.
3. **Decouple Scenarios**: Keep distinct test behaviors (e.g., derivatives separation, zero-basis materiality, payment-proceeds correction) in separate subdirectories to avoid test pollution or unintended lot matching.
4. **Filing / Materiality Check**: Remember that `_filter_immaterial_entries()` drops any lot with `|gain/loss| < 1 EUR`. If a synthetic row is intended to survive and be asserted, ensure its recomputed cost and proceeds result in a gain/loss of at least `1.00 EUR`, or that OGR overrides bring it over the threshold.
5. **Document Fixtures**: Place a `README.md` inside the example directory detailing the scenario details, the transaction rows, and the tests they back.


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
| `test_example_fixture_has_no_duplicate_aggregation_keys` | Committed example koinly2025 fixture has zero duplicate keys after full pipeline |
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
    AIRDROP = "airdrop"
    LIQUIDITY_WITHDRAWAL = "liquidity_withdrawal"
    LIQUIDITY_PROVISION = "liquidity_provision"
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
| `crypto_deposit` or `fiat_deposit` with `reward`/`cashback`/`realized gain` tag | `reward` |
| `crypto_deposit` or `fiat_deposit` with `airdrop` tag | `airdrop` |
| `crypto_deposit` or `fiat_deposit` with `liquidity out` tag | `liquidity_withdrawal` |
| `crypto_deposit` or `fiat_deposit` with `liquidity in` tag | `liquidity_provision` |
| `exchange` with `liquidity out` tag | `liquidity_withdrawal` |
| `exchange` with `liquidity in` tag | `liquidity_provision` |
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
| LP withdrawal without paired withdrawal (no matching TxHash) | `from_asset` = `"LP position"`, `method` = `LIQUIDITY_WITHDRAWAL`, `confidence` = `medium` |
| LP withdrawal with paired withdrawal via TxHash | `from_asset` = LP token name (e.g., `"CETUS-LP"`), `method` = `LIQUIDITY_WITHDRAWAL`, `confidence` = `high` |
| LP provision with paired withdrawals | `from_asset` = joined provided token names (e.g., `"SSUI+USDC"`), `method` = `LIQUIDITY_PROVISION`, `confidence` = `high` |
| Same-TxHash LP provisions | Multiple LP provision records sharing the same TxHash are merged: `from_asset` = joined token names (e.g., `"SSUI+USDC"`), `confidence` = `high`. This is safe because TxHash is a deterministic on-chain identifier linking all legs of a single atomic transaction. Records are only merged when all have the same platform and method. Do NOT merge across different TxHash values. |
| `crypto_withdrawal` rows | Indexed by TxHash for provenance lookup; not directly resolvable (no `Received Currency`) |

### Testing Requirements

- Test positive matches (exchange, transfer, deposit rows in transaction history)
- Test fallback to `unknown` (no history file, no matching date, epoch date)
- Test multiple-match disambiguation (same confidence, conflicting methods)
- Test confidence downgrade for `Missing cost basis`
- Test that the workbook `Token origin` column shows the expected string format
- Test all transaction types listed in the mapping table above, including `buy`

### Transaction Type Completeness

When changing `_index_row`, verify coverage of ALL transaction types found in real Koinly exports:

1. Check the real fixture for all `Type` field values: `grep -h "^[^,]*," resources/source/koinly*/transaction_history*.csv | sort -u`
2. Each type must either have an explicit handler or an intentional early-return comment explaining why it is skipped.
3. Known types requiring explicit handling: `exchange`, `transfer`, `crypto_deposit`, `fiat_deposit`, `buy`.
4. Missing a common type (e.g. `buy`) causes blank origins for every matching transaction in production data.

### Graceful Degradation Consistency

Missing-data guards must be applied uniformly across all transaction type branches. If one branch returns early when a required field is empty, all branches that use that field must apply the same guard:

```python
# ❌ WRONG: exchange guards sent_currency but buy does not
def _index_row(self, row):
    if row_type == "exchange":
        if not sent_currency:
            return  # ← guard present
        ...
    elif row_type == "buy":
        # ← NO guard; falls through to from_asset = asset,
        # creating fabricated "EUROC acquired from EUROC"
        self._add_record(asset, sent_currency, ...)  # from_asset = asset when sent_currency is ""

# ✅ CORRECT: consistent early return for empty required field
    elif row_type == "buy":
        if not sent_currency:
            return  # degrade to unknown, same as exchange branch
        self._add_record(asset, sent_currency, ...)
```

Inconsistency produces fabricated provenance (e.g., "EUROC (direct_purchase)" when the resolver should return `unknown`).

### Manual Review Reduction Opportunities

Analysis of Koinly exports reveals these fixable false-positive triggers:

| Trigger | Root Cause | Fix |
|---------|-----------|-----|
| "Missing cost basis" with 0 EUR proceeds | Koinly marks as missing but disposal has 0 value | Only flag if `proceeds_eur > 0` |
| Character encoding (WBТC) | Cyrillic 'Т' (U+0422) instead of 'T' | Unicode normalize before parsing |
| Temporal validity warnings | Historical transactions before `service_start_date` | Use `service_start_date` separate from `valid_from` |

## FIFO Engine Patterns

### Overview

The FIFO rebuild engine (`crypto_fifo.py`) reconstructs capital gains for loan-affected assets from the Koinly Transaction History when `TaxJurisdictionConfig.exclude_loan_repayment_gains=True`. The affected-asset set is **dynamically discovered** from loan-tagged TH rows via `discover_loan_affected_assets()` (not a fixed constant). This is required because Koinly's CG output mixes loan and non-loan transactions in the same FIFO pool, contaminating cost basis.

### Data Model

- `CryptoAcquisition` -- an incoming lot (buy, exchange receipt, etc.) with cost basis, fee, and source metadata
- `CryptoConsumption` -- an outgoing event (sell, exchange send, withdrawal, gas fee) classified as taxable or non-taxable
- `CryptoFifoRealization` -- a matched lot pair (acquisition consumed by a taxable consumption) producing a capital gain/loss
- `AssetFifoResult` -- per-asset FIFO output: realizations list plus carry-over cost map keyed by `tx_key`

### Per-Wallet Scope (CIRS art. 43 n.9)

FIFO is applied per `(asset, platform)`, not globally per asset. The caller must pre-filter acquisitions and consumptions to a single `(asset, platform)` pair before calling `compute_fifo_for_asset()`. The function validates this invariant internally.

### Non-Taxable Exchange Consumptions

Crypto-to-crypto exchanges are not taxable under Art. 10(20) / DP-002. The engine models them as non-taxable consumptions that consume FIFO lots and record the carry-over cost in `carryover_cost_by_tx_key`, without emitting a capital gain row. The received side of the exchange becomes an acquisition with cost derived from the carry-over.

### Carry-Over Resolution by tx_key

Cross-asset exchanges (e.g. LBTC to WBTC/SUI) are resolved by matching the TH transaction identifier (`tx_key`), never by date. Same-day exchanges must not cross-wire costs. `_build_cross_asset_order()` determines per-asset processing order so that the sending asset always runs before the receiving asset, enabling carry-over lookup in a single pass. `resolve_cross_asset_exchanges()` then resolves deferred acquisitions from the carry-over map.

Unresolved deferred acquisitions (no matching carry-over entry) are flagged with `review_required=True` and a specific `review_reason`, and logged at warning level.

### Cross-Platform Carry-Over Keying

When `_rebuild_fifo_for_loan_affected_assets` merges carry-over maps from multiple per-platform FIFO runs, the merged dict must use `(tx_key, platform)` composite keys, not plain `tx_key` strings. Two platforms can independently produce a carry-over entry with the same `tx_key` (especially when `_build_composite_tx_key` is used because `TxHash` is empty and both platforms happen to process a row with identical Date/Amount/Currency fields). Without the platform dimension, the second write silently overwrites the first, using the wrong cost basis for one of the two assets.

The `AssetFifoResult.carryover_cost_by_tx_key` field therefore holds `dict[str | tuple[str, str], Decimal]`: per-platform results use plain `str` keys; the merged carry-over map used by `_rebuild_fifo_for_loan_affected_assets` uses `(tx_key, platform)` tuple keys.

### Intra-Asset Transfer Carry-Over

Cross-platform transfers of loan-affected assets (e.g. WBTC sent from Kraken to Ethereum wallet) are modelled as:
- A non-taxable `transfer_out` consumption on the **sender** platform, recording cost in `carryover_cost_by_tx_key`.
- A `transfer_in_deferred` acquisition on the **receiver** platform, resolved by `_resolve_intra_asset_transfers` after the sender's FIFO run completes.

`_resolve_intra_asset_transfers` must scope the carry-over lookup to the **sender platform** using a `tx_key → sender_platform` map built alongside `_order_platforms_for_transfers`. Iterating all platforms and returning the first matching tx_key (without platform scoping) silently assigns the wrong cost basis when two platforms happen to produce the same composite key.

### `_build_composite_tx_key` Blank-TxHash Limitation

When the Koinly `TxHash` column is empty, `_build_composite_tx_key` builds a fallback key from `(date, sent_currency, received_currency, amount)` suffixed with `_<row_index>`. This prevents two fee-only rows on the same date from producing the same key.

However, for cross-platform transfers where the **same** asset movement appears on two separate TH rows (one for the sending wallet, one for the receiving wallet), both rows will have **different** `row_index` values, producing different composite keys. The resulting `transfer_in_deferred` acquisition will not match the `transfer_out` consumption, causing an unresolvable deferred entry and a `review_required=True` flag.

This is a known limitation. Whenever a `transfer_in_deferred` remains unresolved, the engine must log at warning level with a message clearly attributing the review flag to the blank-TxHash condition rather than a FIFO pool issue.

### Transfer-Fee Handling

Transfer rows (`Type=transfer`) do not reset holding period or create taxable principal disposals. However, if a transfer charges a fee in a loan-affected asset, the fee portion is emitted as a separate taxable consumption with the fee amount and EUR value.

### Placeholder Buys

When the FIFO pool is exhausted (more sells than available acquisitions), a zero-cost placeholder realization is created with `review_required=True`, a specific `review_reason`, and `logger.warning(...)`. These entries must never be silently dropped.

### Holding Period Labels

Labels must remain Koinly-compatible strings: `"Short term"` for holdings <= 365 days, `"Long term"` for holdings > 365 days.

### Validation Sequence

After FIFO-derived entries are converted to `CryptoCapitalGainEntry` and merged with raw CG rows from non-loan assets:
1. `_validate_capital_entries_have_valid_countries()` -- validate all entries
2. `_aggregate_capital_entries()` -- aggregate by `(disposal_date, asset, platform, holding_period)`
3. `_filter_immaterial_entries()` -- exclude entries where `|gain/loss| < 1 EUR`

### Testing Requirements

- Test simple buy-then-sell with correct gain computation
- Test partial lot consumption with proportional fee allocation
- Test multiple lots consumed by a single disposal
- Test holding period classification (short vs long term), including exact 365-day boundary
- Test zero-cost placeholder on pool exhaustion with review_required flag
- Test cross-asset carry-over by tx_key (not by date)
- Test same-day exchanges do not cross-wire costs
- Test unresolved deferred acquisitions are flagged for review
- Test future-dated lots are NOT consumed by past disposals (temporal gating)
- Test disposal fee is included in gain calculation
- Test empty-string acquisition_date doesn't corrupt aggregation

### Critical Bug Patterns

#### Fee Unit Verification

External data often represents the same value in multiple units (raw crypto quantity vs EUR value). When parsing Koinly Transaction History rows:
- `Fee Amount` is the raw crypto quantity (e.g., 0.001 WBTC)
- `Fee Value (EUR)` is the EUR-denominated value
- Always use `fee_value` (EUR) for `fee_eur` fields that feed into cost basis calculations
- Using `fee_amount` (crypto quantity) corrupts cost basis by the price factor

#### Date Parsing Error Scope

Date parsing for TH rows must be inside the same try/except that catches decimal parsing errors. One bad row must never discard the whole dataset. The epoch sentinel (`1970-01-01`) returned by `_parse_koinly_datetime` for empty dates must be detected before `_compute_holding_period` to prevent false "Long term" classification (tax exemption in PT).

#### FIFO Pool Temporal Gating

The FIFO consumption loop must enforce `acq.date <= con.date`. When a disposal exhausts all lots acquired on or before its own date, the remaining quantity is treated as pool-exhausted (zero-cost placeholder), not consumed from future-dated lots. Consuming from the future corrupts both gain amounts and holding period labels.

#### Pool-Exhaustion Review Signaling

When the FIFO pool is exhausted during a non-taxable exchange, the carry-over cost is zero. This zero-cost entry must be distinguished from a legitimately zero-cost acquisition (e.g., airdrops with no FMV). The resolver must check whether the zero cost is from pool exhaustion or from the original lot having zero cost, and set `review_required=True` with a specific reason in the exhaustion case.

#### Empty String in Aggregation

When aggregating capital entries, `min(e.acquisition_date for e in group)` picks `""` (empty string) if any entry has an empty acquisition date. Empty strings sort before all dates, corrupting the aggregated entry's acquisition date. Filter out empty strings before taking `min`, or set a sentinel date for unknowns.

#### Disposal Fee in Gain Calculation

When a consumption includes a disposal fee (`con.fee_eur`), this fee must be subtracted in the gain calculation: `gain = proceeds - cost - acquisition_fee - disposal_fee`. Missing the disposal fee overstates gains. This applies to both taxable realizations and non-taxable carry-over accumulation.

### Official Source Verification for Legal/Tax Decisions

When decision points or rules conflict, always verify against the primary authoritative source documents:
- For Portuguese tax: CIRS consolidated code (official PDF) and AT folheto
- AT documents may use outdated paragraph references after CIRS renumbering amendments
- Verify the current paragraph number against the consolidated CIRS PDF before relying on AT citations
- See `docs/maintenance/tax/laws/pt/crypto-tax/` for archived official sources

## Traceability and Review Flagging

### Review Entries Must Not Be Ghost Data

When flagging entries for manual review, ensure they remain visible in their primary data context. If an entry appears ONLY in a "REVIEW REQUIRED" section and not in the main capital gains/reward data, users cannot trace it back to source rows, creating a "ghost" review item with no audit trail.

**Correct pattern**: Zero-value entries for known assets should be added to the main entry list with `review_required=True`, AND added to review_entries for prominence. Review-only sections should be additive cross-references, not the sole location for flagged items.

```python
# ❌ WRONG - Zero-value known tokens appear only in review section
if is_all_zero and is_known_token:
    review_entries.append(CryptoReviewEntry(...))
    continue  # Skips adding to capital_entries

# ✅ CORRECT - Zero-value known tokens appear in both places
if is_all_zero and is_known_token:
    review_entries.append(CryptoReviewEntry(...))
    review_required = True  # Set flag
# Continue to create entry in capital_entries below with review_required=True
```

**Impact**: Traceability requires that every review-flagged item can be traced back to its source row in the main data set.

### Testing Excel Rendering Features

When adding new Excel sections or conditional formatting features (suspicious flags, review sections, color-coding), add test coverage for:

1. **Section structure**: Title, headers, note text
2. **Data row values**: Correct cell values for each column
3. **Formatting**: Red font, bold, italics, color fills
4. **Empty state**: Behavior when no items exist

**Example test structure**:
```python
def test_suspicious_flag_formatting(self):
    """Test that suspicious assets are highlighted with red font."""
    entry = CryptoReviewEntry(..., is_suspicious=True)
    # Write to Excel
    asset_cell = ws.cell(row, 3)
    assert asset_cell.font.bold is True
    assert asset_cell.font.color.rgb in ("FFFF0000", "00FF0000")
```

**Why**: Excel rendering is UI surface. Conditional formatting and new sections are user-visible and should have test coverage equivalent to unit tests for business logic.

## Derivatives Separation Lessons

Lessons from the 2026-06-13 derivatives separation plan. Each lesson records the WHAT, WHY,
and CONSEQUENCE of a design decision that future contributors must not undo without re-deriving
the rationale. Cross-reference: plan `docs/history/plans/2026-06-13-derivatives-separation.md`,
rules PT-C-033 / PT-C-034, guideline CRG-018.

### Why amount thresholds are rejected as a derivatives detection signal

The original classifier design considered using OGR amount thresholds (e.g. `>100 EUR` equals
derivatives) to distinguish futures rows from spot rows. This was rejected in r1 Blocker 2 and
Monitor #2 because spot disposals can also produce large values and the threshold is arbitrary;
any chosen cutoff would over-classify legitimate large spot trades and under-classify small
futures fees. The classifier in `src/tax_reporting/application/crypto/classification.py` instead
uses only two signals: the OGR row `Type` (Profit/Loss) and CG-counterpart existence within a
`Decimal("0.01")` EUR tolerance. The consequence is that no asset ticker, platform, or amount
allowlist may be reintroduced without re-opening this decision; doing so silently re-broadens the
classifier and reintroduces the silent over-classification risk.

### Why the OGR parser returns a row list, not a pre-summed dict

The OGR parser originally returned `dict[(date, asset, wallet), Decimal]` with values pre-summed.
This collapsed per-row `Type` information (Profit vs Loss) that the derivatives classifier needs
to distinguish a realized-P&L row from a fee row (r1 Blocker 7). The parser
`_find_and_parse_other_gains_file` in `src/tax_reporting/infrastructure/koinly_parser.py` now
returns `list[ParsedOgrRow]`, preserving per-row type and description. A separate
`_build_ogr_index()` function provides the summed dict for backward-compatible callers. The
consequence is that any future "optimization" that re-sums inside the parser breaks the classifier
and the Derivatives P&L tab silently; the parser must stay row-preserving.

### Why spot CG signs must be protected from derivatives OGR override

When `separate_derivatives_reporting=True`, derivatives OGR rows route to `derivatives_entries`
and never enter `_apply_ogr_direction_override` in
`src/tax_reporting/application/crypto/ogr_handler.py` (Design Invariant 6). This protection exists
because directional authority semantics (CRG-017) were designed for same-category disagreements:
when an OGR row and a CG row describe the same disposal, OGR wins on direction. If a derivatives
OGR loss were allowed to flip spot CG lot signs, a spot gain under art. 10(1)(k) could be
incorrectly converted into a loss, producing wrong tax treatment and silently bypassing the
365-day exemption logic. The consequence is that the override path must remain split by category;
merging the two override paths back together is a regression of this invariant.

### Why the split must run post-FIFO rebuild and pre-aggregation

The `_split_ogr_index` call in `src/tax_reporting/application/crypto_reporting.py` happens AFTER
the FIFO rebuild (which adds lots for loan-affected assets) and AFTER country validation, but
BEFORE `_aggregate_capital_entries` (Design Invariant 2). This ordering is load-bearing: the
classifier matches OGR rows against CG lots, and FIFO rebuild can add CG lots that did not exist
in the raw CG CSV (loan-affected assets are rebuilt from Transaction History). If the split ran
before FIFO rebuild, an OGR row whose only CG counterpart was added by rebuild would be
misclassified as derivatives (no CG counterpart found), routing spot activity to the wrong tab.
Running it before aggregation would lose the lot-level trail that PT-C-033 direction override
relies on (per CLAUDE.md repository constraint: OGR overrides before aggregation). The consequence
is that the split's position in the pipeline must not be moved; reordering it relative to FIFO
rebuild or aggregation breaks classification correctness for loan-affected assets.

### Why derivatives-flagged CG lots use a two-phase matcher (exact-then-contiguous-range)

The dedup step that removes derivatives-flagged CG lots from the spot aggregate
(`remove_derivatives_flagged_lots` in
`src/tax_reporting/application/crypto/derivatives_dedup.py`) runs TWO matching phases rather
than a single key-equality pass:

1. **Phase 1 (exact match)** pairs one derivatives TH event to one CG lot per
   `(timestamp, asset, wallet, amount_6dp)` key via per-key `deque`s. The deque
   (not a dict-of-scalars) is mandatory: when two derivatives events share a
   timestamp and amount with two CG lots, a dict-of-scalars would silently
   overwrite one lot, leaving it in the spot aggregate and removing the wrong
   lot for one of the events. See `development_lessons.md` #107.

2. **Phase 2 (contiguous-range fallback)** runs only for events that did not
   find an exact match. It uses a two-pointer sliding window over the
   unmatched lots at the same `(timestamp, asset, wallet)` to find a
   CONTIGUOUS range summing to the event amount within tolerance
   `Decimal("0.00001") * range_size`. Contiguity is required because FIFO
   acquisition order determines which lots may be grouped as one disposal's
   split; a non-contiguous subset of lots at the same timestamp cannot be a
   FIFO split and must not match. The tolerance must be recomputed after
   every shrink step and the shrink bound must be `left < right` (not
   `left <= right`) so the single-lot window survives as a candidate. See
   `development_lessons.md` #108.

The two-phase design exists because a derivatives disposal may appear in CG
either as one lot with the exact same amount as the TH event (phase 1 hits)
or as N adjacent lots whose amounts sum to the TH event amount within
conversion-rounding tolerance (phase 2 hits). A single-phase exact matcher
misses the second case; a single-phase fuzzy matcher admits non-contiguous
coincidental collisions. The consequence is that the two phases are
complementary and both must remain in this order; collapsing them into one
phase or reordering them breaks either correctness (silent over-removal) or
recall (silent under-removal).

After both phases, `_collect_surplus_lots` walks the non-empty phase-1
deques and emits a single summary WARNING naming the leftover lots. This
warning is the user's only audit signal for missed FIFO splits, stale lots
from a prior year, or coincidental key collisions; removing it makes
under-removal invisible.

## Derivatives CG Dedup via TH Labels

This section documents the TH-label-driven capital-gains dedup that ships
in `src/tax_reporting/application/crypto/derivatives_dedup.py`. It is an
implementation guideline only; the legal classification of derivatives
disposals is governed elsewhere. This section is self-contained and does
not cross-reference other rule or plan documents.

### Why TH labels are needed in addition to the OGR classifier

Koinly emits a single derivatives disposal in TWO reports at once:

1. The Other Gains Report (OGR), as a realized-PnL row (`Type=Profit` or
   `Type=Loss`, with the EUR value and date).
2. The Capital Gains Report (CG), as a FIFO lot disposal (with the full
   cost-basis trail: acquisition date, cost, proceeds, gain).

The derivatives classifier in `src/tax_reporting/application/crypto/classification.py`
operates per OGR row and decides whether each row represents a
derivatives event or a spot fee disposal by looking at the OGR `Type` and
the existence of a CG counterpart within a `Decimal("0.01")` EUR
tolerance. When the same disposal surfaces in both OGR and CG, the
classifier sees a CG counterpart for the OGR row, fails to disambiguate
the multi-row aggregate-match, and routes the OGR row to the
`derivatives_entries` collection with `review_required=True`. Meanwhile
the CG lots stay untouched in `capital_entries`. The result is
double-counting: the same disposal is taxed once as a positive Crypto
Gains entry and once as a negative Derivatives PnL entry.

The OGR-classifier signal is insufficient for this case because the
decision to remove a CG lot is per-lot, not per-OGR-row. The Koinly
Transaction History (TH) report carries a richer signal: the `Tag` column
on `crypto_withdrawal` rows (values like `Funding fee`, `Futures fee`,
`Realized gain`) directly identifies which asset movements are
derivatives events. The dedup uses TH labels as the CG-side filter,
running BEFORE the OGR classifier, so the classifier then sees the
matching OGR rows with no CG counterpart and routes them to
`derivatives_entries` cleanly (no `review_required` flag, no Ambiguous
classification).

### Per-provider-per-year config convention

The derivatives label set is provider-specific and year-specific: Koinly
may change the `Tag` vocabulary across years, and a future data source
(different tax-year provider for 2026+) may use entirely different
terminology. Per the repo's no-hardcoded-constant-sets rule, the labels
are stored as JSON under `docs/maintenance/tax/derivatives_labels/<provider>_<year>.json`:

```json
{
  "derivatives_th_labels": ["Funding fee", "Futures fee", "Realized gain"]
}
```

The provider is currently always `koinly` (the only supported source);
the year is the integer returned by `_extract_tax_year`. Adding a new
provider or year requires only a new JSON file under
`docs/maintenance/tax/derivatives_labels/`; no code change is needed.

The loader `_load_derivatives_labels_config(provider, year)` resolves the
path as `_REPOSITORY_ROOT / "docs" / "tax" / "derivatives_labels" /
f"{provider}_{year}.json"` and routes the secure-load
guards (symlink rejection and a file size limit of 1 MiB via
`_MAX_LABELS_FILE_SIZE`) through the shared
`infrastructure.json_loader.load_guarded_json`, supplying its own
`_on_error` policy callback (repo lesson #105: inherit the guards,
recalibrate exception handling). A malformed config
file (invalid JSON, missing `derivatives_th_labels` key, wrong value
type) raises `FileProcessingError` at startup; only a missing file
degrades gracefully.

### Match key and two-phase matching

The match key is `(timestamp, asset, wallet, amount)`:

- **Timestamp** is minute precision (`%Y-%m-%d %H:%M` UTC). The CG
  `Date Sold` column is minute precision (`DD/MM/YYYY HH:MM`); TH `Date`
  is second precision (`YYYY-MM-DD HH:MM:SS UTC`) and is truncated to
  minute for matching. Both normalize to `%Y-%m-%d %H:%M` via
  `parse_koinly_datetime` (which localizes naive dates to the jurisdiction
  zone and converts to UTC; TH explicit-UTC dates pass through)
  then `strftime("%Y-%m-%d %H:%M")`.
- **Asset** is normalized via `normalize_asset_ticker`.
- **Wallet** is normalized via `normalize_platform_name` (ByBit-specific:
  collapses `ByBit (2)` to `ByBit`; Kraken and Binance keep numbered
  suffixes).
- **Amount** is quantized to 6 decimals via
  `Decimal.quantize(Decimal("0.000001"))` for the exact-match phase.

Matching runs in two phases inside `remove_derivatives_flagged_lots()`:

1. **Phase 1 (exact match)** pairs one derivatives TH event to one CG
   lot per `(timestamp, asset, wallet, amount_6dp)` key via per-key
   `deque` objects (not a dict-of-scalars). The deque is mandatory:
   when two derivatives events share a timestamp and amount with two CG
   lots, a dict-of-scalars would silently overwrite one lot, leaving it
   in the spot aggregate and removing the wrong lot for one of the
   events.

2. **Phase 2 (contiguous-range fallback)** runs only for events that
   did not find an exact match. It uses a two-pointer sliding window
   over the unmatched lots at the same `(timestamp, asset, wallet)` to
   find a CONTIGUOUS range summing to the event amount within tolerance
   `Decimal("0.00001") * range_size`. The sliding-window logic lives in
   `_find_contiguous_range()`; the tolerance is recomputed after every
   shrink step and the shrink bound is `left < right` (not
   `left <= right`) so the single-lot window survives as a candidate.

For determinism, CG lots are sorted by
`(timestamp, asset, wallet, acquisition_date, row_index)` and TH events
by `(timestamp, asset, wallet, amount)` before matching. The same input
always produces the same output; no reliance on dict iteration order.

### Rounding and tolerance

- **Exact match**: both CG and TH amounts are quantized to 6 decimals via
  `_quantize_amount_6dp()` (constant `_EXACT_AMOUNT_QUANTUM =
  Decimal("0.000001")`, ROUND_HALF_EVEN). This absorbs Koinly rounding
  differences (TH amounts are raw chain amounts; CG amounts are
  FIFO-resolved and may differ in the last decimal) without introducing
  a fuzzy tolerance window for single-lot matching.
- **Contiguous-range match**: tolerance is
  `_RANGE_TOLERANCE_SCALE * range_size` where
  `_RANGE_TOLERANCE_SCALE = Decimal("0.00001")` and `range_size` equals
  the current sliding-window length. This is 10x the per-lot rounding
  error, absorbing accumulation when summing N independently-rounded
  lots (each lot is independently rounded to 6 decimals; summing N lots
  can drift by up to N times 0.0000005).

### Why contiguous-range, not subset-sum

FIFO consumption is inherently contiguous: a single disposal consumes the
oldest available acquisition tranches, which form a contiguous block when
lots are sorted by `acquisition_date`. Matching this semantics directly
(sliding window over sorted lots) is O(N) per event. General subset-sum
would be NP-hard and would risk false positives: with 108 CG lots at one
timestamp, coincidental non-contiguous subsets summing to any target are
virtually guaranteed, leading to silent over-removal. The contiguous
constraint eliminates this risk while correctly handling the realistic
FIFO-split case.

When no contiguous range matches, the event is marked unmatched and
falls through to the existing Ambiguous classifier on the OGR row. This
covers the rare case of non-contiguous consumption (e.g., cross-asset
transfer interleaving), which is not a FIFO pattern and warrants manual
review.

### Logging approach

Per the repo's data-loss-at-warning rule, removing a derivatives-flagged
CG lot is intentional correction (the lot belongs in Derivatives PnL,
not Crypto Gains), not unintentional data loss. At scale (thousands of
removals per year), per-lot WARNING lines would flood the log and drown
genuine warnings. The dedup therefore logs each removal at INFO level
(audit-traceable in debug logs) and emits exactly ONE WARNING summary at
the end per pipeline run, inside `_format_summary_warning()`. The
summary covers all three signal types in a single aggregate line:

- **Removals**: total count, breakdown by match type
  (`exact=N, range=M`), aggregate proceeds EUR, aggregate gain EUR
  removed.
- **Surplus lots**: count, total amount, sample of up to 3
  `(timestamp, asset, wallet, amount)` tuples. Surplus lots are leftover
  lots at any exact-match key after all events consumed theirs; they may
  indicate a missed FIFO split, a stale lot from a prior year, or a
  coincidental key collision.
- **Malformed-input lots**: count, sample of up to 3
  `(timestamp, asset, amount)` tuples. Malformed-input lots have
  non-positive amounts (zero or negative); they are skipped from
  matching because they would stall the sliding-window shrink condition.

NO per-lot WARNING emissions exist. Per-lot data-quality WARNINGs would
flood the log at scale and train the user to ignore the warning level
entirely, defeating the data-loss-at-warning rule. The summary is the
authoritative data-loss audit signal.

### Graceful degradation when config is missing

If the config file `docs/maintenance/tax/derivatives_labels/<provider>_<year>.json`
does not exist, `_load_derivatives_labels_config_from_path()` logs a
single `logger.warning` naming the missing file and returns an empty
frozenset. The caller `apply_derivatives_dedup()` then logs a second
WARNING ("Derivatives TH-label config missing for koinly year N; CG
dedup skipped. Add docs/maintenance/tax/derivatives_labels/koinly_N.json to
enable.") and returns the input unchanged. The pipeline degrades to the
pre-dedup behavior (the double-counting risk the dedup was designed to
fix) but the warning surfaces the misconfiguration.

This is the only graceful-degradation path. A malformed config file
(invalid JSON, missing `derivatives_th_labels` key, wrong value type,
symlink, oversized file) raises `FileProcessingError` at startup; the
user sees the problem immediately rather than discovering silent
double-counting at audit time.

### Orchestration thinness rule

`crypto_reporting.py` is already well over the ~500-line orchestration
threshold. To avoid absorbing more orchestration logic into it, the
dedup wiring lives entirely in `derivatives_dedup.py`. The pipeline call
site in `load_koinly_crypto_report` is a single-line invocation:

```python
capital_entries = apply_derivatives_dedup(
    capital_entries=capital_entries,
    jurisdiction=jurisdiction,
    transaction_history_file=transaction_history_file,
    year=year,
)
```

The `apply_derivatives_dedup()` function encapsulates the full
gate-check-config-scan-filter sequence: (1) gate on
`jurisdiction.separate_derivatives_reporting` AND
`jurisdiction.use_other_gains_report` AND `transaction_history_file`;
(2) load labels via `_load_derivatives_labels_config(provider="koinly",
year=year)`; (3) scan TH via `find_derivatives_th_events()`; (4) filter
CG lots via `remove_derivatives_flagged_lots()`. The dedup runs AFTER
`_validate_capital_entries_have_valid_countries` and BEFORE
`_split_ogr_index`, so the OGR classifier sees the filtered
`capital_entries` list.

### Legal characterization (inline)

Under Portuguese CIRS, derivatives dispose under article 10(1)(e)
(ganhos e perdas relativos a apertos a termo e outros instrumentos
financeiros derivados); cryptoassets dispose under article 10(1)(k)
(ganhos e perdas decorrentes da alienação onerosa de criptoativos,
unidades de conta ou tokens virtuais não qualificados como títulos,
direitos ou valores mobiliários). The two articles define different
taxation regimes; the same disposal cannot be taxed under both.

The dedup exists to prevent the same disposal from being taxed under
both articles. When Koinly reports a derivatives disposal in BOTH the
CG report (where it would flow into Crypto Gains, taxable under
art. 10(1)(k)) AND the OGR report (where it would flow into Derivatives
PnL, taxable under art. 10(1)(e)), the dedup removes the CG lots so the
disposal surfaces only in Derivatives PnL under art. 10(1)(e). This
matches the economic characterization: a derivatives disposal is a
derivative, not a cryptoasset disposal, regardless of whether the
underlying collateral is a cryptoasset.

### Summary of design invariants

| Invariant | Why |
|-----------|-----|
| Filter runs after FIFO rebuild and country validation | Sees rebuilt lots and validated country codes |
| Filter runs before `_split_ogr_index` | Classifier sees filtered list, routes OGR rows cleanly |
| Gated on `jurisdiction is not None` AND `separate_derivatives_reporting` AND `use_other_gains_report` AND `transaction_history_file` | Defensive None guard plus functional gates: without OGR there is no Derivatives PnL surface for removed lots; without TH there is no derivatives Label signal |
| Two-phase matching (exact then contiguous-range) | Phase 1 handles same-amount events; phase 2 handles FIFO-split lots |
| Per-key `deque` for exact match | Prevents silent overwrite on same-key collisions |
| Contiguous constraint on range match | Matches FIFO semantics; avoids NP-hard subset-sum false positives |
| Per-lot INFO, single aggregate WARNING | Data-loss signal at WARNING; no noise flood at scale |
| Graceful degradation only for missing config | Malformed config is a correctness hazard; raises immediately |
| Orchestration in `derivatives_dedup.py`, not `crypto_reporting.py` | Keeps the orchestrator thin |

## Payment Proceeds Correction (DP-014)

Implementation guideline for the TH-tag-driven CG proceeds correction that
ships in `src/tax_reporting/application/crypto/payment_proceeds.py`. The
legal characterization (taxable alienação onerosa for goods/services paid in
crypto, valor de realização equals the FMV of the crypto spent) lives at
PT-C-004 and PT-C-007 in `crypto_rules.md`; the fiscal-year decision point is
DP-014 in `docs/maintenance/tax/decision_points/2025.md` (+ `.toml` sidecar
flag `infer_payment_proceeds`). This section documents the mechanism only.

### Why the correction exists (Koinly zero-valuation root cause)

A Koinly `Payment` / `Card Payment` disposal (a goods/services purchase paid in
crypto) is a taxable alienação onerosa (PT-C-004) and must carry a non-zero
valor de realização (PT-C-007). But when Koinly's price DB cannot match the
imported ticker, it emits `Net Value (EUR) = 0` ("No market rates found") for
the TH row, and the corresponding CG row lands with `proceeds_eur == 0`. With
cost > 0 and proceeds = 0, the row presents as a phantom full-cost loss.

The price-DB miss is frequently a token-rename alias, not a real unpriced
asset. The worked example is the 1:1 EUR-pegged Circle stablecoin that
launched in 2022 as EUROC and was later renamed to the canonical ticker EURC:
Koinly still holds the old EUROC label, which its price DB no longer matches.
Both tickers are listed in `docs/maintenance/tax/popular_crypto_tokens.json`
under `tokens.stablecoins` and `stablecoin_pegs` so the EUR-par tier resolves
either label. EUROC and EURC are public-reference tickers documented here as
the rename example; the real motivating disposal (amounts, wallet, dates) is
recorded only in the gitignored personal trace, never in tracked docs.

### Three-tier proceeds resolution (source order is fixed)

`_resolve_proceeds()` resolves the EUR proceeds for a matched payment disposal
in this exact order; the first tier that yields a value wins:

1. **Tier 1 primary - Koinly `Net Value (EUR)`.** When the matched TH row's
   `Net Value (EUR)` is finite and `> 0`, trust Koinly's own priced market
   value (outcome `net_value`). Works for ANY asset Koinly prices, including
   USD-pegged stablecoins (USDT, USDC, DAI) under normal market conditions.
   The `is_finite()` guard is required because `parse_koinly_decimal` accepts
   `inf` / `nan` and `Decimal("inf") > 0` is `True`.

2. **Tier 2 stablecoin fallback - EUR par or peg rate** (only when Net Value
   is zero/missing AND the asset is a configured stablecoin). Two sub-cases,
   BOTH `review_required=True` because they approximate the disposal-date FMV:
   - **EUR par** (outcome `eur_par`) for an EUR-pegged stablecoin: proceeds =
     disposal `amount` at 1 EUR (par assumption). Applies to stablecoins whose
     `stablecoin_pegs` entry is `"EUR"` (EURC, EUROC, EURT).
   - **Peg rate** (outcome `peg_rate`) for a non-EUR-pegged stablecoin whose
     peg currency has a finite positive rate in the derived peg->EUR map:
     `proceeds = amount * peg_to_eur_rates[peg]`.

3. **Tier 3 review flag - no inference.** The row is left unchanged at
   `proceeds_eur == 0` and a specific review entry is appended:
   - `non_eur_stablecoin_no_rate` - a non-EUR stablecoin whose peg currency
     has NO configured rate (reason names the peg and tells the user to supply
     the EUR realization value).
   - `not_stablecoin` - any non-stablecoin (reason tells the user to check the
     asset's ticker mapping in Koinly, since a price-DB miss on a non-stablecoin
     usually means a rename/alias not yet in the token file).

### Year-end peg->EUR rate comes from the bounded `Config.rates`, not arbitrary rate plumbing

The non-EUR-stablecoin tier-2 conversion is driven by a SINGLE bounded rate
dict, `_derive_peg_to_eur_rates(rates, stablecoin_pegs)`, built from the
`ConversionRate` list threaded through `load_koinly_crypto_report` as the
`rates` kwarg. That list is the SAME `[EXCHANGE RATES]` source that shares and
dividends already depend on (parsed once into `Config.rates` in
`infrastructure/config.py`). Implications:

- A stablecoin pegged to a fiat WITH a configured `[EXCHANGE RATES]` rate
  (e.g. USDT/USDC/DAI pegged to USD, and `config.ini` carries EUR/USD) is
  converted via the fiscal year-end peg->EUR rate.
- A stablecoin pegged to a fiat with NO `[EXCHANGE RATES]` rate falls to the
  tier-3 `non_eur_stablecoin_no_rate` review flag - there is NO auto-conversion
  and NO arbitrary-asset rate lookup. Adding the missing rate to
  `[EXCHANGE RATES]` is the supported remedy (see Monitor note in the plan).
- The year-end rate is an APPROXIMATION of the disposal-date FX rate
  (PT-C-007), which is exactly why every tier-2 converted entry is
  `review_required=True` with a reason naming the peg, the rate value, and
  "Verify the year-end rate."
- Provenance caveat (load-bearing for the label): the loader reads ONLY the
  unqualified `[EXCHANGE RATES]` section and ignores archived
  `[EXCHANGE RATES YYYY]` sections. The operator must maintain
  `[EXCHANGE RATES]` as the fiscal year-end rate for that run (the same
  convention shares use). Maintaining it as a spot/mid-year rate makes the
  converted proceeds diverge from the disposal-date FMV by an unbounded amount
  and the reason ("year-end rate, verify") would misdescribe it.
- Config-inversion note: a valid-but-wrong-MAGNITUDE rate (e.g. entering the
  USD-per-EUR reciprocal instead of EUR-per-USD) passes every guard
  (`is_finite() and > 0`). This is NOT crypto-specific: the feature reuses the
  same rate shares/dividends depend on, so an inverted value is a repo-wide
  config-maintenance error. No crypto-only magnitude-direction guard is added
  (it would be direction-specific per peg and inconsistent with the shares
  consumer); the control is operator config maintenance, plus this feature adds
  MORE visibility than shares get (`review_required=True` + the reason names
  the rate value).

### Day-key timezone rationale

The CG/OGR/Income `Date` columns are local-time-naive (mainland-Portugal
WET/WEST), while the TH `Date` is true UTC at second precision. Both are
localized to the same true-UTC instant at ingestion: naive dates are stamped
with the jurisdiction `IANA_TIMEZONE` (resolved once at config load into a
`ZoneInfo` on `TaxJurisdictionConfig.timezone`, defaulting to `Europe/Lisbon`
for PT) and converted to UTC by `parse_koinly_datetime`, while TH
explicit-UTC dates pass through unchanged (a ` UTC` literal in the `strptime`
format does not populate `tzinfo`; detection is on the matched format string).
Because a zone is mandatory to localize naive dates, the application enforces a
STRICT fail-fast at the crypto-loading boundary: when crypto data is present and
the timezone cannot be resolved - a configured jurisdiction with `timezone is
None` (any non-PT country without `IANA_TIMEZONE`) OR no config loaded at all
(`jurisdiction is None`) - `_load_crypto_tax_report` in `main.py` raises
`ConfigurationError` before any date is parsed, and `_main` propagates it
unwrapped. The program fails rather than silently treating naive dates as UTC.
The loader `load_koinly_crypto_report` itself stays a pure parser and does NOT
enforce this; the no-zone UTC-stamp remains a deliberate library affordance in
`parse_koinly_datetime` for direct/programmatic callers (and unit tests), not
the application default. The correlation then collapses both onto a 10-character calendar day
(`YYYY-MM-DD`) via `_calendar_day()`, so a CG row and its TH twin match even
when their sub-day wall-clock representations differ, including a summer
disposal in the 00:00-01:00 local window that maps to the previous UTC day.
With both sides on the true-UTC day, the calendar-day key is timezone-robust;
a +/-1-day window is no longer needed. See the crypto-timezone-normalization
plan and `development_lessons.md` #132.

### Deque + count-equality collision-blocks-correction pattern

`build_payment_tag_index()` indexes payment-tagged TH rows by
`(calendar day, normalized asset ticker, normalized platform, amount at 6
decimal places)` into `dict[key, deque[int]]`. The deque (not a
dict-of-scalars) is mandatory: when two payment events share a key, a
dict-of-scalars would silently overwrite one, leaving the wrong twin matched.

`correct_payment_proceeds()` pre-counts BOTH static sides BEFORE the entry
loop: `cg_count[key]` over the candidate population (entries with
`proceeds_eur == 0` AND asset NOT in `loan_affected_assets`), and
`th_count[key]` as the static size of each payment bucket captured once before
any `popleft`. A count-equality gate then blocks correction for ALL candidates
on a key whenever `cg_count[key] != th_count[key]`, appending ONE per-key
review entry naming the count mismatch. This means a collision never silently
picks the wrong twin.

Per-row discipline (lesson #124): the fallible `parse_koinly_decimal` +
`_resolve_proceeds` run BEFORE `bucket.popleft()`, and the resolver RAISES an
exception the per-row boundary catches rather than returning a sentinel used
unconditionally. On success, `dataclasses.replace(...)` mutates the entry,
THEN `popleft()` runs. On exception the row is emitted unchanged, the bucket
is NOT popped, and NO review entry is appended (the row's existing in-place
DP-013 reason covers it - deliberate asymmetry).

### Reuse of `_quantize_amount_6dp`

Amounts in both the TH index key and the CG entry key are quantized via
`_quantize_amount_6dp` reused from `derivatives_dedup.py`
(`Decimal.quantize(Decimal("0.000001"))`, ROUND_HALF_EVEN). This absorbs
Koinly rounding differences (TH amounts are raw chain amounts; CG amounts are
FIFO-resolved and may differ in the last decimal) so a CG row and its TH twin
collapse onto the same 6-decimal key.

### Reuse of `popular_crypto_tokens.json` (no new config file)

Stablecoin membership, peg annotation, and the payment tag set are REUSED from
`docs/maintenance/tax/popular_crypto_tokens.json` - the SAME file the
zero-value-reward detector in `classification._load_popular_crypto_tokens`
already reads. Adding sibling top-level keys is safe for that loader because
it reads only `data["tokens"]`. No new config file is introduced; the loader
resolves the path as `_REPOSITORY_ROOT / "docs" / "maintenance" / "tax" /
"popular_crypto_tokens.json"`. JSON schema for the keys this feature reads:

```json
{
  "meta": { "...": "existing meta block; description and maintenance_note updated" },
  "tokens": {
    "stablecoins": ["USDT", "USDC", "DAI", "EURC", "EUROC", "EURT"]
  },
  "stablecoin_pegs": {
    "USDT": "USD", "USDC": "USD", "DAI": "USD",
    "EURC": "EUR", "EUROC": "EUR", "EURT": "EUR"
  },
  "payment_tags": ["payment", "card payment"]
}
```

Required-key invariants enforced by `_load_payment_proceeds_config_from_path`:

- `tokens.stablecoins` MUST be a list of strings.
- `stablecoin_pegs` MUST be a string->string map.
- `payment_tags` MUST be a list of strings.
- `stablecoin_pegs` keys MUST be a subset of `tokens.stablecoins`; drift
  (a peg for a ticker absent from `tokens.stablecoins`, or vice versa) logs a
  WARNING naming the offending tickers but the config is still loaded
  (proceeds inference may mis-route stablecoins whose peg is unset).

### Loader degrades, never raises (lesson #105)

`_load_payment_proceeds_config_from_path()` routes the secure-load guards
(symlink rejection, 1 MiB size limit via `_MAX_TOKEN_FILE_SIZE`) through the
shared `infrastructure.json_loader.load_guarded_json` and supplies its own
`_on_error` policy callback that RECALIBRATES exception handling to
DEGRADE never raise. A corrupt token file must never abort report generation.
On ANY failure mode (missing, symlink, oversize, malformed JSON, missing keys,
drift) the policy callback logs a WARNING naming the path and the specific
failure, then returns the defaults: empty stablecoin set, empty peg map, the
canonical payment tag pair `["payment", "card payment"]`. This is the deliberate
recalibration called for by lesson #105: reuse the guards but weigh the cost
of silent failure at the new call site (a missing peg map means EUR-par and
peg-rate tiers never fire - visible as unchanged zero-proceeds rows with the
DP-013 flag, not a crashed run).

The cached resolver `_get_payment_proceeds_config()` is `@lru_cache(maxsize=1)`;
the reader `_load_payment_proceeds_config_from_path()` is NOT, so unit tests
can drive it with distinct `tmp_path` fixtures and get fresh reads.

### `tokens.stablecoins` extension side effect (zero-value rewards)

Adding EUR-pegged tickers (EURC, EUROC, EURT) to `tokens.stablecoins` also
enlarges the set `classification._load_popular_crypto_tokens` flattens, so a
zero-value reward for an EUR-pegged stablecoin is now FLAGGED for review
(previously it was not - the ticker was absent from the popular-token set).
This is the intended side effect: EUR-pegged stablecoin rewards are no longer
silently skipped when Koinly reports zero value. The backward-compat test in
`tests/unit/application/test_crypto_reporting.py` verifies the new flagging
behavior.

### Pipeline wiring and re-zero snapshot

The correction is wired into `load_koinly_crypto_report`
(`crypto_reporting.py`) at a specific, load-bearing position:

1. AFTER `_apply_ogr_direction_override` (the OGR directional authority runs
   first on the raw CG lots).
2. After a re-zero snapshot+restore that closes the OGR pre-mutation residual:
   before the OGR override, the indices of pre-OGR entries whose `proceeds_eur
   == 0` AND whose asset is NOT loan-affected are captured; after the override,
   any such index whose proceeds is now non-zero (OGR mutated THAT row) is
   restored to `proceeds_eur == 0` so the correction's `proceeds == 0` gate
   fires on it. INDICES not keys: a key-based snapshot would also restore a
   genuine non-zero OGR-overridden derivatives disposal that merely shares a
   `(date, asset, wallet)` key with a zero-proceeds Payment. An OGR override
   touching an originally-zero-proceeds row is NECESSARILY spurious (a real OGR
   disposal has non-zero proceeds).
3. BEFORE `_aggregate_capital_entries` so corrected lots aggregate by
   `(date, asset, platform, holding_period)`.

Corrected entries intentionally SKIP re-validation and derivatives dedup (safe:
the original `proceeds_eur == 0` entry already passed validation; payments are
spot disposals; country code inherited unchanged) and flow into aggregation and
the materiality filter. The whole block is guarded by
`jurisdiction.infer_payment_proceeds` and by the three-file presence guard that
guarantees `transaction_history_file` is non-None.

### Relationship to DP-013 (zero-basis review flag)

DP-013's `cost>0 AND proceeds=0` data-quality branch is NARROWED (not removed)
by this flag: when `infer_payment_proceeds=True`, positively-identified
Koinly-tagged Payment/Card Payment disposals whose TH `Net Value (EUR) == 0`
are proceeds-corrected (tier 2/3 of DP-014) rather than left flagged. The flag
still fires for every OTHER zero-proceeds row (unmatched, non-payment, or the
flag off). Branch-count invariant: DP-014 does NOT add or remove a branch -
`_build_zero_basis_review_reason` keeps exactly four `if`-blocks; the
`cost>0 AND proceeds=0` branch is the one DP-014 narrows.

### Out of scope (DP-005 follow-up)

LP-token unstaking / "liquidity out" is a distinct non-taxable-deferred case
(DP-005 / PT-C-005) tracked as a follow-up. It will reuse the CG<->TH tag
correlation built here (`build_payment_tag_index`), keyed on liquidity tags to
EXCLUDE rather than proceeds-correct.

### Abstract worked example

A user spends N units of an EUR-pegged stablecoin on a card payment. Koinly's
price DB has no match for the imported ticker (a rename alias), so it emits
`Net Value (EUR) = 0`. The CG row lands with `proceeds_eur == 0` and a phantom
full-cost loss. The correction correlates the CG row to the payment-tagged TH
row by `(calendar day, asset, platform, amount @ 6dp)`, sees Net Value is zero,
and - because the asset is a configured EUR-pegged stablecoin - sets
`proceeds_eur = N` (EUR par), `review_required=True` with reason naming the par
assumption. The phantom loss is replaced by the realized gain/loss on the
EUR-par proceeds, and the row flows into aggregation and the materiality
filter. (Real disposal amounts and dates live only in the gitignored personal
trace at `docs/maintenance/personal/payment-proceeds-trace.md`.)

## Transaction Fee Filtering (DP-015)

Legal basis: CIRS art. 10(1)(k). A standalone network/transaction fee is a
non-taxable utility cost without received consideration, so it is not an
*alienação onerosa*. Koinly tags network/gas fee withdrawals with `Cost` or
`Loan fee` and by default realizes a gain/loss on the disposed fee token; those
realized disposals must be filtered out of the capital gains worksheets when
`exclude_transaction_fees` is set (PT FY2025). This is the implementation-rule
companion to PT-C-036.

### TxHash co-occurrence correlation guard

Some service payments (card fees, subscriptions) are also tagged `Cost` by
Koinly and ARE taxable. To distinguish a non-taxable network fee from a taxable
service payment, BOTH identification paths require the fee event's non-empty
`TxHash` to appear at least twice in the Transaction History CSV (a network fee
shares its transaction id with the main transfer it accompanies; a standalone
service payment does not). Withdrawals with an empty or unique `TxHash` are left
taxable. The guard applies to fees AND suspects.

The scanner makes two passes over the materialized TH row list (Pass 1: count
each non-empty `TxHash` into a frequency map; Pass 2: classify each
`crypto_withdrawal` against the map). Each row body is wrapped in
`try...except (ValueError, KeyError, InvalidOperation)` (per repo Rule #9) so a
malformed row is skipped with a warning without aborting the pass.

### Two-prong identification

1. **Tagged**: any `crypto_withdrawal` whose tag is `Cost` or `Loan fee`. The
   explicit tag is trusted; NO EUR amount threshold is applied. The fiat
   `Net Value (EUR)` cell is parsed inside a separate nested
   `try...except ValueError` that degrades to `Decimal("0")` on failure (so a
   corrupted fiat string on a tagged row does NOT drop the tagged fee - the tag
   is the authority).
2. **Untagged-whitelist**: an untagged `crypto_withdrawal` (empty tag) whose
   `Sent Currency` is a key in `exclude_transaction_fee_max_eur_per_asset`
   (the dict keys ARE the eligibility whitelist) AND whose TH `Net Value (EUR)`
   is `<=` that asset's per-token ceiling. The fiat string guard uses a
   `"MISSING"` sentinel (NOT `""`) so an explicit CSV value of `"0"` / `"0.00"`
   (a valid zero-priced gas fee) is NOT skipped - a whitelisted asset at 0.0 IS
   filtered.

Per-token ceilings (confirmed values): ETH = 1.0 (ETH gas can reach ~0.70 EUR);
SOL/SUI/BNB/MATIC/TON = 0.5. The fee scanner resolves the ceiling as
`per_asset[asset]` (membership already checked; no `"default"` fallback).

### Unlisted-asset suspect surfacing (NOT removed)

An untagged, TxHash-co-occurring `crypto_withdrawal` whose `Sent Currency` is
NOT a dict key AND whose `Net Value (EUR) <= max(per_asset.values())` is a
*suspect*. It stays taxable (over-taxing on uncertainty is the safe direction)
and is surfaced three ways so a legitimate gas token missing from the config
(e.g. BERA) can be discovered and added as one config line:

- a `review_required=True` flag on the CG-matched lot (a red "YES: \<reason\>"
  Crypto Gains row when the aggregated `|gain_loss| >= 1` EUR; below that,
  materiality drops it from Crypto Gains);
- a `CryptoReviewEntry` appended to the threaded `review_entries` list
  (`source_section="capital_gains"` when the suspect matched a CG lot, else the
  new `"transaction_history"`), rendered in the Crypto Supplementary "Review
  required" section (SRG-009 already covers this section - no new SRG needed);
- a `logger.warning` naming the asset and its `Net Value (EUR)`.

The suspect pass is run LATE in the pipeline (after `correct_payment_proceeds`,
before aggregation) so any proceeds corrections are complete when the flag is
set, avoiding reason-joining or clobbering in `payment_proceeds.py`.

### Empty-dict no-op

When `exclude_transaction_fees` is enabled but
`exclude_transaction_fee_max_eur_per_asset` is empty (a country that enables
the flag without listing tokens, or a misconfiguration): the suspect branch is
skipped entirely via an explicit `if per_asset:` guard (no `max()` call on an
empty dict); the untagged-whitelist branch finds nothing (no keys); the TAGGED
`Cost`/`Loan fee` path is dict-INDEPENDENT and STILL filters. The filter
DEGRADES to tagged-only under an empty dict - it is NOT a full no-op.

### Matching, removal, and per-lot logging

Fee events are matched to Capital Gains lots by the shared two-phase matcher
(`th_lot_matcher`, extracted from `derivatives_dedup`; rule #119) keyed by
`(disposal_timestamp, asset, wallet, amount_6dp)` where `wallet` is the
normalized Sending Wallet name (NOT `platform`, which is the institution).
Matched lots are removed; suspects are matched in a match-only mode (no
removal). The per-lot log records the removed lot's identity tuple
`(disposal_timestamp, asset, wallet, amount)` plus the fee event's `TxHash`:
tagged removals log at INFO (trusted); untagged-whitelisted removals log at
WARNING (an untagged-whitelisted withdrawal CAN be a genuine dust disposal, so
it must not be silent). Exactly one aggregate summary WARNING is emitted per
fee pass via the caller-passed logger (`domain_label="fee"`).

### Accepted risk: cross-tx match

The correlation guard validates the fee EVENT's TxHash multiplicity, NOT the
correspondence between the fee's TxHash and the matched CG lot's origin
(`CryptoCapitalGainEntry` carries no TxHash). A tagged fee sharing a TxHash
with a transfer while an UNRELATED same-minute/wallet/amount disposal exists
could match the wrong lot (silent lost tax). Enforcing correspondence requires
plumbing TxHash onto CG lots (out of scope). Mitigation: the per-lot INFO log
records the removed lot's identity tuple alongside the fee's TxHash so a
cross-transaction match is visible during the release-gate spot-check.

## References

- Plan: `docs/history/plans/2026-06-18-crypto-payment-proceeds.md` (DP-014)
- Plan: `docs/history/plans/aggregate-crypto-rewards-income.md`
- Plan: `docs/history/plans/crypto_manual_review_reduction.md` (token swap history, superseded; heuristic removed 2026-04-05)
- Plan: `docs/history/plans/2026-04-05-koinly-first-token-origin.md` (implemented: deterministic origin matching via `TokenOriginResolver`)
- Rules: `docs/maintenance/crypto_rules.md`
- Guidelines: `docs/maintenance/crypto_reporting_guidelines.md`
- Chain sources: `docs/maintenance/tax/crypto-origin/`
- Post-mortem: `docs/history/investigations/aggregate-crypto-rewards-review-analysis.md`
