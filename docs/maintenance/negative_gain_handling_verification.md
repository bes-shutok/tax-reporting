# Negative Gain Handling Verification

## Purpose

This document verifies that the tax reporting tool correctly handles negative `gain_loss_eur` values (capital losses) throughout the entire processing pipeline, from Koinly CSV parsing to Excel output generation.

**Note:** This verification was performed on 2026-06-08. If any of the following components change significantly, this document should be re-verified: `koinly_parser.py`, `CryptoCapitalGainEntry`, `crypto_fifo/matching.py`, aggregation logic in `crypto_reporting.py`, or `crypto_gains_sheet.py`.

## Investigation Date

2026-06-08

## Scope

This verification covers the following components:

1. **Koinly CSV Parsing** (`koinly_parser.py`)
2. **Domain Entity Storage** (`CryptoCapitalGainEntry`)
3. **FIFO Gain Computation** (`crypto_fifo/matching.py`)
4. **Aggregation Sums** (`crypto_reporting.py`)
5. **Excel Output** (`crypto_gains_sheet.py`)

## Findings

### 1. Koinly CSV Parsing

**Component:** `parse_koinly_decimal()` in `koinly_parser.py`

**Finding:** Negative signs are preserved.

**Evidence:**
```python
def parse_koinly_decimal(value: str) -> Decimal:
    text = value.strip().replace(" ", "").replace(" ", "")
    # ... (normalization steps)
    return Decimal(text)  # Direct conversion, no abs()
```

**Verification:** `Decimal("-42.26")` produces `Decimal('-42.26')` (negative preserved)

---

### 2. Domain Entity Storage

**Component:** `CryptoCapitalGainEntry` dataclass

**Finding:** No sign conversion in storage.

**Evidence:**
```python
@dataclass(frozen=True)
class CryptoCapitalGainEntry:
    gain_loss_eur: Decimal  # Plain field, no transformation
```

**Verification:** Values are stored directly from parsed Koinly data without modification.

---

### 3. FIFO Gain Computation

**Component:** `_build_taxable_realization()` in `crypto_fifo/matching.py`

**Finding:** Gains computed as `proceeds - cost - fee`, naturally negative for losses.

**Evidence:**
```python
gain_loss_eur=(
    proportional_proceeds - proportional_cost - proportional_acq_fee
)
```

**Verification:**
- When `proceeds < cost + fee`, result is negative
- No `abs()` or sign reversal applied

---

### 4. Aggregation Sums

**Component:** `CapitalGainPeriodStats.from_entries()`, `_aggregate_capital_entries()`

**Finding:** Aggregations use algebraic sums (not absolute values).

**Evidence:**
```python
gain_loss_total_eur=sum((e.gain_loss_eur for e in entries), start=ZERO)
```

**Verification:**
- Plain `sum()` function
- `start=ZERO` is `Decimal("0")`, not `abs()`
- Negative entries sum to more negative totals

---

### 5. Excel Output

**Component:** `_render_capital_gain_row()` in `crypto_gains_sheet.py`

**Finding:** Negative values written directly to Excel cells.

**Evidence:**
```python
worksheet.cell(row_no, 7, entry.gain_loss_eur)
```

**Verification:**
- Direct assignment to cell
- No formatting or sign conversion
- Excel displays negative numbers correctly (e.g., -42.26)

---

## Test Coverage

Existing tests verify negative gain handling:

| Test | Purpose | Status |
|------|---------|--------|
| `test_filter_keeps_significant_losses` | Losses >= 1 EUR are retained | PASS |
| `test_filter_removes_small_losses_below_threshold` | Losses < 1 EUR are filtered | PASS |

---

## Conclusion

**The current implementation correctly handles negative capital gains (losses) across the entire pipeline.** No code changes are required. Negative values are preserved from parsing through aggregation to Excel output without any sign conversion or absolute-value operations.

## Implications

1. **Futures/derivatives losses:** When leveraged positions liquidate at a loss, the negative `gain_loss_eur` is correctly reported in the Excel output.
2. **Capital loss deductions:** Negative values in the "Gain/Loss (EUR)" column correctly represent deductible losses under Portuguese tax law.
3. **Statistics aggregation:** The CAPITAL GAINS STATISTICS section correctly sums losses as negative contributions to period totals.
