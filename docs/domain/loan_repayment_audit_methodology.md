# Loan Repayment Audit Methodology

Repeatable methodology for auditing Koinly DeFi loan repayment treatment against capital gains reports. Use this at the start of each tax year to validate that loan-related gains/losses are correctly handled for Portuguese reporting.

For the legal basis (why loan repayment is not taxable under Portuguese law) and Koinly-specific behaviors, see `docs/tax/laws/pt/crypto-tax/platform-divergences.md` Section 1.

---

## Overview

Koinly treats loan repayment as a taxable disposal. For Portuguese tax purposes, these entries must be identified and excluded. The audit has three phases:

1. **Extract** loan receipts and repayments from the transaction history
2. **Cross-reference** against the capital gains report
3. **Flag** issues and compute the total phantom gain/loss

---

## Phase 1: Extract Loan Transactions

From the Koinly transaction history CSV, filter rows by tag:

- **Loan receipts**: tag = `Loan`, type = `crypto_deposit`
- **Loan repayments**: tag = `Loan repayment`, type = `crypto_withdrawal`

### Group by token

Group both receipts and repayments by asset (e.g., SUI, WBTC, LBTC). For each group, compute:

- Count of transactions
- Total quantity received/sent
- Total cost basis (EUR)
- Total net value (EUR)
- Total reported gain/loss (EUR)

### Annotated example per-token receipt table

| Date (UTC) | Received | Cost Basis (EUR) | Net Value (EUR) |
|---|---|---|---|
| 2025-03-09 | ~50 TokenA | ~100 | ~100 |
| 2025-06-09 | ~2,000 TokenA | ~5,800 | ~5,800 |
| 2025-12-15 | ~75 TokenA | ~100 | ~100 |

### Key fields to capture per repayment row

| Field | Source column |
|---|---|
| Date (UTC) | Transaction history timestamp |
| Sent amount | `Sent Amount` / `Sent Currency` |
| Cost basis | `Cost Basis` (EUR) |
| Gain | `Gain` (EUR) |
| Net value | `Net Value` (EUR) |

---

## Phase 2: Cross-Reference Against Capital Gains Report

Koinly batches multiple disposals across several loan repayments into a single timestamp window. Individual 1:1 matching between transaction history rows and CG report rows is unreliable.

### Matching strategy: date + asset level

For each (date, asset) group:

1. Sum the repayment totals from the transaction history
2. Sum the CG report entries for the same (date, asset)
3. Compare totals rather than individual rows

### Reconciliation table per (date, asset) group

For each group, compute:

| Metric | Computation |
|---|---|
| Repayment total sent | Sum of `Sent Amount` from transaction history |
| Repayment total cost basis | Sum of `Cost Basis` from transaction history |
| Repayment total gain | Sum of `Gain` from transaction history |
| CG total amount | Sum of `Amount` from CG report |
| CG total cost | Sum of `Cost` from CG report |
| CG total proceeds | Sum of `Proceeds` from CG report |
| CG total gain | Sum of `Gain` from CG report |
| Amount diff | Repayment total - CG total |
| Gain diff | Repayment gain - CG gain |

### Expected tolerance

Small differences (< 1 EUR, < 1 token) are normal due to:
- Gas fee disposals included in CG report but not tagged as loan repayments
- Koinly's FIFO lot decomposition splitting repayments differently
- Rounding in timestamp alignment (CET/CEST vs UTC)

Differences exceeding these thresholds indicate a data issue worth investigating.

---

## Phase 3: Flag Issues

### 3.1 Missing cost basis

Some loan repayment rows have no cost basis, meaning Koinly could not determine the acquisition cost. These rows may overstate gains (treats full proceeds as income) or understate losses.

**Detection**: repayment rows where `Cost Basis` is empty or zero but `Gain` is non-zero.

**Action**: Check if the corresponding loan receipt established a cost basis. If not, the gain/loss is unreliable.

### 3.2 Zero net value (no price data)

Some tokens (e.g., LP tokens, low-liquidity tokens) have no price data in Koinly. All receipts and repayments show zero cost basis and zero net value.

**Detection**: all entries for a token have `Net Value = 0.00` and `Cost Basis = 0.00`.

**Action**: All gain/loss calculations for this token are unreliable. Flag for manual review.

### 3.3 Receipt vs repayment balance

Compare total tokens received against total tokens repaid within the tax year:

| Token | Total Received | Total Repaid | Difference |
|---|---|---|---|
| TokenA | ~5,000 | ~6,000 | ~-1,000 shortfall |
| TokenB | ~0.06 | ~0.06 | ~0 balanced |

A significant shortfall (repaid more than received in the tax year) suggests:
- Additional loans taken before the tax year
- Loans from sources not tracked in Koinly
- Wrapped-asset conversions affecting the token count

**Action**: Investigate and document the source of the imbalance.

### 3.4 Loan receipts with zero cost basis

When loan receipts show zero cost basis AND zero net value, the token has no Koinly price data. Any subsequent disposal will have unreliable gain/loss.

**Detection**: receipt rows where both `Cost Basis = 0.00` and `Net Value = 0.00`.

**Action**: Mark all CG entries for this token as unreliable.

---

## Summary Table

After completing all three phases, produce a summary per token:

| Token | Repayments | TX Cost Basis (EUR) | TX Gain (EUR) | CG Gain (EUR) | TX-CG Diff (EUR) | Missing Cost Basis |
|---|---|---|---|---|---|---|
| TokenA | 10 | ~17,000 | ~-8,000 | ~-8,000 | ~-1 | 3/10 |
| TokenB | 5 | ~1,000 | ~+3,500 | ~+3,500 | ~0 | 3/5 |
| TokenC | 4 | ~1,000 | ~-1,000 | ~-1,000 | ~0 | 2/4 |

Grand totals:
- TX-reported gain: sum of all token TX gains
- CG-matched gain: sum of all token CG gains
- Difference: should be < 1 EUR if reconciliation is correct

---

## Post-Audit Actions

1. **Pipeline filter**: Ensure the code pipeline filters loan repayment CG entries (see `docs/plans/2026-05-25-filter-loan-repayment-gains.md`)
2. **Koinly fix**: Apply the "change worth" workaround (see `docs/tax/laws/pt/crypto-tax/platform-divergences.md` Option A) to neutralize phantom gains in Koinly itself
3. **Documentation**: Record the audit findings and total phantom impact for the tax year
