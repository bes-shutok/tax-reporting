# Crypto Manual Review Reduction & Token Swap History

**Status:** Complete - All phases (1.1-1.3, 2.1-2.3) implemented
**Created:** 2026-03-25
**Analysis:** Based on actual Koinly exports in `resources/source/koinly2025/`

## Problem Statement

1. Too many "YES" in Review flag column requiring manual attention
2. Token swap history (e.g., SUI → HASUI) not visible in capital gains output

## Data Analysis Findings

### Koinly Files Structure

| File | Contains Swap Data? | Current Usage |
|------|---------------------|---------------|
| `koinly_2025_capital_gains_report_*.csv` | ❌ No | Used for capital entries |
| `koinly_2025_income_report_*.csv` | ❌ No | Used for reward entries |
| `koinly_2025_transaction_history_*.csv` | ✅ **Yes** | **NOT CURRENTLY USED** |

### Token Swap Evidence Found

**Transaction history row 965:**
```csv
2025-02-16 17:10:42 UTC,exchange,"",Ledger SUI,"26,40816087",SUI,"29,83",Ledger SUI,"25,19665014",HASUI,"29,83"
```
This shows **SUI → HASUI swap** with:
- Type: `exchange`
- Sent Currency: `SUI`
- Received Currency: `HASUI`

### Current Manual Review Triggers

| Trigger | Count in Sample | Root Cause |
|---------|-----------------|------------|
| "Missing cost basis" in Notes | 4 rows | Koinly couldn't determine cost |
| "Fee" in Notes | 10+ rows | Legitimate fee transactions |
| Character encoding (WBТC) | 2 rows | Cyrillic 'Т' instead of 'T' |
| Unknown platform | TBD | Missing registry mapping |

## Implementation Plan

### Phase 1: Add Token Swap History (Quick Win)

**Change:** Parse transaction_history.csv to extract swap information

**Implementation:**

1. **Add new field** to `CryptoCapitalGainEntry`:
```python
token_swap_history: str = ""  # e.g., "SUI → HASUI"
```

2. **Create swap lookup** from transaction history:
```python
def _build_swap_lookup(transaction_history_path: Path) -> dict[tuple[str, str], str]:
    """Build lookup of (wallet, disposal_date) -> swap history string.

    Parses transaction_history.csv for Type="exchange" rows and extracts
    Sent Currency -> Received Currency swaps.
    """
```

3. **Match swaps to capital gains** during parsing:
```python
swap_history = swap_lookup.get((wallet, disposal_date), "")
```

4. **Add column** to Crypto sheet (after Notes column):
```python
capital_headers = [
    # ... existing ...
    "Notes",
    "Token swap history",  # NEW COLUMN
]
```

**Benefit:** Makes SUI → HASUI type swaps visible for audit trail

### Phase 2: Reduce Manual Review Flags

#### 2.1 Fix "Missing Cost Basis" False Positives

**Current logic (line 1373):**
```python
review_required = operator_origin.review_required or "missing cost basis" in notes.lower()
```

**Problem:** Flags row even when Cost=0, Proceeds=0, Gain=0 (zero-value disposal)

**Solution:**
```python
# Only flag if missing cost basis AND has non-zero proceeds (actual tax impact)
has_tax_impact = proceeds_eur > ZERO
missing_cost_with_impact = "missing cost basis" in notes.lower() and has_tax_impact
review_required = operator_origin.review_required or missing_cost_with_impact
```

**Impact:** Eliminates flags for zero-disposals that Koinly marked as "missing cost basis" but have 0 EUR proceeds

#### 2.2 Fix Character Encoding Issue ✅ COMPLETED

**Problem:** `WBТC` with Cyrillic 'Т' (U+0422) instead of 'T'

**Solution implemented:** Added `_normalize_asset_ticker()` function with comprehensive Cyrillic-to-Latin character mapping

**Changes:**
- Added `_normalize_asset_ticker()` function that handles common Cyrillic-to-Latin character confusions:
  - Т (U+0422) -> T, Е (U+0415) -> E, О (U+041E) -> O, Р (U+0420) -> P
  - А (U+0410) -> A, Н (U+041D) -> H, К (U+041A) -> K, М (U+041C) -> M
  - С (U+0421) -> C, В (U+0412) -> B, Х (U+0425) -> X
  - Plus lowercase variants: у -> y, е -> e, о -> o, р -> p, а -> a
- Applied normalization in `_parse_capital_gains_file()`, `_parse_income_file()`, and `_parse_holdings_file()`
- Added comprehensive tests for the normalization function

**Original planned solution:** Add normalization in `_parse_capital_gains_file`:
```python
import unicodedata

def _normalize_asset_ticker(asset: str) -> str:
    """Normalize common character encoding issues in asset tickers."""
    # Replace Cyrillic Т with Latin T
    asset = asset.replace("Т", "T")
    # Normalize unicode characters
    asset = unicodedata.normalize("NFKC", asset)
    return asset.strip()

# Usage in parsing loop:
asset = _normalize_asset_ticker(row.get("Asset", "").strip())
```

#### 2.3 Temporal Validity Improvements ✅ COMPLETED (Updated 2026-03-26)

**Current issue:** Wirex split-scope needed temporal boundaries to handle unknown GB/HR split date

**Solution implemented:** Added `service_start_date` field separate from `valid_from`

**Changes:**
- Added `service_start_date: str | None` field to `OperatorOrigin` dataclass
- Modified `_is_temporally_valid()` to use `service_start_date` for transaction matching
- Updated `_return_with_temporal_check()` to pass `service_start_date` instead of `valid_from`
- Updated Wirex entries with `service_start_date="2015-01-01"` (approximate founding date) and `valid_from="2026-03-08"` (verification date)
- IMPORTANT: `valid_from` is for audit trail only and NOT used for transaction matching
  per the repository contract (AGENTS.md, registry, guidelines). Only `service_start_date`
  is used for transaction date matching.

**Implementation Note:**
- The original implementation (2026-03-25) used `service_start_date="2026-03-08"` (verification date).
- However, the actual 2025 sample data contains Wirex transactions that were all being flagged for review.
- The corrected implementation (2026-03-26) uses `service_start_date="2015-01-01"` (approximate founding date, Wirex Limited incorporated in 2014).
- This allows legitimate 2025 Wirex transactions to be auto-classified, achieving the Phase 2.3 goal of reducing manual review flags.
- See CMD-021 (updated) in `mapping_decision_log.md` for the rationale.

**Result:**
- Wirex transactions from 2015 onwards are auto-classified as GB (fiat) or HR (crypto) without review flags
- Wirex transactions before 2015 would require historical investigation if present in actual data (unlikely in practice)
- The `valid_from="2026-03-08"` preserves the GB/HR split-scope verification date for audit trail
- For platforms with exact history (Ethereum, Arbitrum, BASE, etc.), `service_start_date` reflects their actual launch date and `valid_from` records the verification date

### Phase 3: Expand Platform Mappings

**Current unknown platforms to add:**
- DEX protocols: Uniswap, PancakeSwap (partial data exists in holdings)
- Wallet variants with different naming patterns
- DeFi protocols: Cetus, various LP tokens

**Action:** Review actual "Unknown" rows in output and add to registry

## Success Metrics

| Metric | Before | Target |
|--------|--------|--------|
| Manual review flags | TBD | < 5% of rows |
| Token swaps visible | No | Yes (SUI→HASUI) |
| False "missing cost basis" flags | TBD | 0 (zero-proceeds rows) |
| Character encoding issues | 2 (WBТC) | 0 |

## Implementation Order

1. ✅ **Phase 1.1**: Add token_swap_history field to dataclass (COMPLETED)
2. ✅ **Phase 1.2**: Parse transaction_history for swaps (COMPLETED)
3. ✅ **Phase 1.3**: Add column to Crypto sheet output (COMPLETED)
4. ✅ **Phase 2.1**: Fix "missing cost basis" logic (COMPLETED)
5. ✅ **Phase 2.2**: Add character normalization (COMPLETED)
6. ✅ **Phase 2.3**: Temporal validity refactoring (COMPLETED)
7. ⏳ **Phase 3**: Platform mappings (as data allows)

## Testing Strategy

Use existing Koinly exports as test data:
- Verify SUI→HASUI swap appears in output
- Verify "Missing cost basis" rows with 0 proceeds show NO review flag
- Verify character encoding fixes WBТC → WBTC
- Count review flags before/after

## References

- Koinly transaction history format (Type="exchange" for swaps)
- `crypto_reporting.py` line 1373 (missing cost basis logic)
- `operator_chain_origin_registry.md` (current mappings)
- Issue: Token swap history request (SUI → SSUI/HASUI example)
