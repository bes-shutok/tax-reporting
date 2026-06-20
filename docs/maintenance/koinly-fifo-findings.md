# Koinly FIFO & Loan Transaction Findings

**Date:** 2025-05-27  
**Context:** Investigation during `filter-loan-repayment-gains` branch development  
**Purpose:** Document findings about Koinly's internal FIFO behavior and its implications for Portuguese tax reporting

---

## 1. Koinly Does NOT Pair Loan Deposits with Loan Repayments

**Hypothesis (disproved):** Koinly internally matches "Loan" deposits with "Loan repayment" withdrawals to form capital gain pairs.

**Reality:** Koinly treats loan repayments as regular disposals and uses standard FIFO matching against ALL prior acquisitions (including non-loan purchases from months earlier).

**Evidence:**
- WBTC repayment on 2025-03-09: CG "Date Acquired" = **27/07/2024** (regular purchase, not a loan deposit)
- WBTC repayments on 2025-04-05: Most lots acquired on **01/03/2025** (not loan deposit dates)
- Only coincidentally do some lots match loan deposit dates (09/03/2025), because those happened to be the FIFO-next acquisitions
- Loan deposits for WBTC were on 2025-03-09 (14:44, 16:04, 16:06, 16:09)

**Implication:** Cannot identify loan CG entries by matching acquisition dates to loan deposit dates.

**Additional detail, FIFO splitting:** Koinly splits a single loan repayment into multiple CG FIFO lots. One TH repayment row can produce 1–6 CG lines (partial lot matching). The CG amounts sum closely to the TH sent amount (with tiny rounding differences).

---

## 2. Koinly's CG File is Fundamentally Unreliable for Portuguese Loan Treatment

Since Koinly mixes loan and non-loan transactions in the same FIFO pool:

1. **Loan repayment disposals consume real purchase cost basis**: e.g., a repayment on April 5 used a buy lot from July 2024 as its cost basis
2. **Loan deposit lots remain in the FIFO pool**: available for future real disposals at zero cost, overstating gains
3. **Cascading contamination**: LBTC→WBTC exchanges carry contaminated LBTC cost basis into WBTC lots

**For Portuguese tax law:** Neither loan receipt nor repayment is a taxable event. Both must be invisible to capital gains calculations.

**Cascading dependency detail:** Since WBTC, SUI, and LBTC all have loan activity AND there are LBTC→WBTC exchanges, rebuilding FIFO requires resolving all three assets together. The correct LBTC cost must be computed first (or simultaneously) to get correct carry-over values for LBTC→WBTC swaps.

---

## 3. Transaction History (TH) Column Semantics

### Headers
```
Date, Type, Tag, Sending Wallet, Sent Amount, Sent Currency, Sent Cost Basis,
Receiving Wallet, Received Amount, Received Currency, Received Cost Basis,
Fee Amount, Fee Currency, Gain (EUR), Net Value (EUR), Fee Value (EUR),
TxSrc, TxDest, TxHash, Description
```

### Key Fields for FIFO Rebuild

| Field | Meaning | Use |
|-------|---------|-----|
| `Received Cost Basis` | Koinly's carry-over cost from sent asset | ⚠️ Contaminated for loan-affected assets |
| `Net Value (EUR)` | Fair Market Value of the transaction | ✅ Reliable FMV for proceeds/acquisition cost |
| `Sent Cost Basis` | Koinly's FIFO cost of sent asset | ⚠️ We compute our own |
| `Gain (EUR)` | Net Value - Sent Cost Basis | Only populated for withdrawals, not exchanges |
| `Tag` | Transaction classification | ✅ Identifies loan transactions |

### Cost Basis Behavior by Transaction Type

**Loan deposit** (`crypto_deposit`, Tag="Loan"):
- `Received Cost Basis` = `Net Value` (FMV at receipt); both 130.88 for 0.00170238 WBTC
- No sent side (receiving wallet only)
- These add zero-cost-basis lots to Koinly's FIFO pool (problematic)

**Loan repayment** (`crypto_withdrawal`, Tag="Loan repayment"):
- `Sent Cost Basis` = Koinly's FIFO cost (or empty when no lots available)
- `Net Value` = FMV at disposal time (= "proceeds" for gain calculation)
- `Gain` = Net Value - Sent Cost Basis
- Some have empty Sent Cost Basis → Koinly reports full Net Value as gain (zero cost)

**Exchange** (e.g., BTC→WBTC):
- `Sent Cost Basis` = 608.54 (Koinly's FIFO cost of BTC)
- `Received Cost Basis` = 608.54 (carry-over, NOT FMV)
- `Net Value` = 914.89 (FMV of the transaction)
- `Gain` = empty (exchanges NEVER have Gain populated in TH)
- **Verified:** 100% of 299 exchanges with both fields have `Received Cost Basis == Sent Cost Basis`

**Transfer** (wallet-to-wallet, same chain or bridge):
- Same currency, same amount on both sides (minus possible fee)
- Small fee possible (gas); treated as micro-disposal if "Realize gains on transfer fees?" is ON
- NOT a taxable event; skip in FIFO
- Wallet at disposal time comes from the disposal row's `Sending Wallet` field (no need to trace transfer chains)
- Holding period is NOT reset by transfers

**Sell** (crypto→fiat):
- `Sent Cost Basis` = Koinly's FIFO cost of crypto sold
- `Gain` = populated
- These ARE taxable events (the exit to fiat)

---

## 4. Loan-Affected Assets

| Tag | Assets |
|-----|--------|
| Loan (deposit) | WBTC, SUI, LBTC |
| Loan repayment | WBTC, SUI, LBTC |
| Loan fee | FEE |

All three main loan assets (WBTC, SUI, LBTC) have inter-dependencies via exchanges (e.g., LBTC→WBTC swaps).

---

## 5. Transaction Type Counts

- Loan deposits: 17 rows (WBTC, SUI, LBTC)
- Loan repayments: 19 rows (WBTC, SUI, LBTC)
- Loan fees: 45 rows (all FEE token, separate asset, immaterial)
- Total exchanges (all assets): 342
- CG file entries: ~3100 lines
- `crypto_withdrawal` Tag="Cost" (gas fees): 705 rows; these generate CG entries
- `Type=exchange` generating CG entries: **0**; Koinly does NOT generate CG for crypto→crypto exchanges

### What Generates Koinly CG Entries

Koinly's CG file only contains entries from:
1. **Gas/network fees** (Notes="Fee"): tiny amounts consumed as transaction costs
2. **`crypto_withdrawal`**: tokens leaving tracked wallets (to external, DeFi, etc.)
3. **`sell`** type: actual fiat exits

**NOT included in CG:** `Type=exchange` transactions. Verified: BTC→WBTC exchange of 0.01 BTC on 2025-02-23 does NOT appear in the CG file. This is consistent with Art. 10(20): crypto-to-crypto is non-taxable, so Koinly correctly excludes it from CG.

### File Structure Details

**TH file:** Title row ("Transaction report 2025") + blank line + header row + data rows. Must skip 2 lines before CSV parsing.

**CG file:** Title row ("Capital gains report 2025") + blank line + header row + data rows. Headers: `Date Sold, Date Acquired, Asset, Amount, Cost (EUR), Proceeds (EUR), Gain / loss, Notes, Wallet Name, Holding period`

**Timezone:** TH uses UTC. CG uses local time (UTC+1 in summer/DST for April/May, UTC in winter for March/December). This causes ±1 hour discrepancies when cross-referencing.

---

## 6. Architecture Decision: Rebuild FIFO from TH for Loan-Affected Assets Only

**Decision:** For Portuguese tax reporting, rebuild FIFO from TH for loan-affected assets (WBTC, SUI, LBTC), using carry-over cost basis. Use Koinly's CG directly for all other assets.

**Rationale:**
- Koinly's CG is contaminated by loan transactions in the FIFO pool for WBTC, SUI, LBTC
- For non-loan assets, Koinly's carry-over methodology is PT-correct (Art. 10(20))
- Carry-over cost = `Received Cost Basis` from TH (same value Koinly uses internally)
- Our rebuild uses the same methodology, just excludes loan-tagged rows from the FIFO pool

**Why `Received Cost Basis` from TH is also contaminated for loan-affected assets:**
- For an LBTC→WBTC exchange, `Received Cost Basis` for WBTC = Koinly's FIFO cost of LBTC
- If LBTC's FIFO pool includes loan deposits (zero-cost lots), LBTC's cost basis is wrong
- That wrong cost carries over into WBTC's acquisition cost
- Therefore we CANNOT simply use `Received Cost Basis` from TH for loan-affected assets
- We must compute our own FIFO for all three assets (WBTC, SUI, LBTC) from scratch

**Approach:**
1. Parse all TH rows into acquisitions/disposals per asset (WBTC, SUI, LBTC only)
2. Exclude rows with Tag = "Loan", "Loan repayment", "Loan fee"
3. Skip `Type=transfer` rows (not taxable events, but note fee if any)
4. For exchanges involving loan-affected assets on BOTH sides (e.g., LBTC→WBTC): compute LBTC's FIFO cost first, then use that as carry-over cost for WBTC acquisition
5. Run per-asset FIFO matching (adapt existing shares FIFO engine)
6. For non-loan assets: use Koinly's CG file directly (already correct)
7. Validate: for non-loan assets, compare our FIFO engine results to Koinly CG (should match exactly)

---

## 7. FIFO Engine Reuse

Existing shares FIFO engine (`transformation.py` + `accumulators.py`):
- `TradeAction`: buy/sell with company, datetime, currency, quantity, price, fee
- `TradeCycle`: collects buys/sells per asset
- `TradePartsWithinDay`: day-based grouping for FIFO ordering
- `CapitalGainLineAccumulator`: matches buy lots to sell lots
- `calculate_company_gains()`: core FIFO algorithm

Core algorithm is identical for crypto. Differences:
- Input format (Koinly TH vs IB CSV)
- Grouping key (asset symbol vs Company)
- Price derivation (carry-over cost from sent asset, not explicit price field)
- Output type (CryptoCapitalGainEntry vs CapitalGainLine)
- Filtering (exclude loan-tagged rows)
- Exchanges are NOT disposals (Art. 10(20)); they just transfer cost basis between assets
- Only `crypto_withdrawal` (non-loan, non-transfer) and `sell` types generate capital gain events

---

## 8. CRITICAL: Portuguese Law Mandates Carry-Over for Crypto-to-Crypto

### CIRS Art. 10(17)–(22): The Complete Framework

**Art. 10(17):** Definition: "crypto-asset" = any digital representation of value or rights transferable/storable via DLT.

**Art. 10(19):** Gains from crypto held **≥ 365 days** are **excluded** from taxation entirely.

**Art. 10(20):** When (19) doesn't apply [held < 365 days] AND the consideration received is **in the form of crypto-assets** → **no taxation occurs**. The received crypto-assets are assigned the acquisition value of the delivered crypto-assets (**carry-over cost basis mandated by statute**).

**Art. 10(21):** Exception: (19) and (20) don't apply when either party is NOT resident in EU/EEA or a jurisdiction with a tax treaty providing for exchange of information.

### Implications for Koinly Settings

| Setting | Correct value | Legal basis |
|---------|---------------|-------------|
| Realize gains on crypto → crypto trades? | **OFF** | Art. 10(20): deferral with carry-over |
| Realize gains on liquidity transactions? | **OFF** | LP tokens are crypto → same Art. 10(20) deferral |
| Wallet based cost-tracking | **OFF** | FIFO is per-asset globally |
| Cost basis method | **FIFO** | Standard Portuguese method |
| Realize gains on transfer fees? | **ON** | Fees are real consumption (tiny but correct) |
| Treat transfer fees as deductible costs? | **ON** | Reduces taxable gain; defensible |

### Key Correction

**Previous assumption (WRONG):** Each crypto-to-crypto swap is a taxable event under PT law, requiring FMV at each swap.

**Actual law:** Crypto-to-crypto swaps are explicitly tax-deferred under Art. 10(20). Carry-over cost basis is mandated. Taxation only occurs when exiting to fiat or to a non-qualifying counterparty (Art. 10(21)).

### Consequence for Architecture

- Koinly's carry-over behavior **IS the correct Portuguese treatment**
- Our FIFO rebuild for loan-affected assets must use **carry-over cost** (same as Koinly)
- `Received Cost Basis` in TH = carry-over cost = **the correct value for Portuguese FIFO**
- Validation against Koinly CG for non-loan assets is apples-to-apples (same methodology)
- No Koinly settings need to change; current configuration is PT-compliant

### Art. 10(21) Gray Area: DEX Counterparties

For on-chain swaps via DEX protocols:
- Is the smart contract/protocol considered a "counterparty"?
- If so, is the protocol's jurisdiction EU/EEA?
- Unclear under current guidance; conservative position may vary

For centralized exchanges (Kraken, ByBit, Gate.io): clearly EU-accessible entities with information sharing agreements → Art. 10(20) deferral applies.

---

## 9. Revised Open Questions for Plan

1. **Scope boundary:** Rebuild FIFO only for loan-affected assets (WBTC, SUI, LBTC) using carry-over cost from TH, or for all assets?

2. **Transfer fees:** Ignore (immaterial) or treat as micro-disposals? (Koinly already handles this with "Realize gains on transfer fees?" ON)

3. **Koinly CG as validation etalon:** What tolerance for rounding differences? (Koinly uses 2 decimal EUR)

4. **Art. 10(21) counterparty check:** Should we flag CG entries involving non-EU counterparties where deferral might not apply? (Future scope)

5. **What constitutes "exit to fiat" for taxation:** Only direct crypto→fiat sells? Or also crypto→stablecoin (USDT/USDC)? Note: USDT appears in CG file (223 entries); Koinly treats USDT disposals as taxable events.

6. **sSUI appreciation:** sSUI is a yield-bearing liquid staking token (appreciates vs SUI over time, unlike a 1:1 wrapped token). SUI→sSUI swaps are deferred under Art. 10(20). The embedded yield only materializes as a taxable gain when exiting to fiat. No special handling needed in current scope.

---

## 10. Current Branch Assessment

### Still Valuable (keep)

1. **TaxJurisdictionConfig** (`config.py`): FISCAL_YEAR, TAX_COUNTRY, EXCLUDE_LOAN_REPAYMENT_GAINS flag, config validation (NaN/Infinity/negative rejection). Still needed to gate loan exclusion behavior.

2. **Loan Activity Sheet** (`loan_activity_sheet.py`): Useful reporting output showing loan balances for user visibility. Independent of FIFO approach.

3. **Zero-cost red highlighting** (`crypto_gains_sheet.py`): Visual flagging of review-needed entries. Independent of FIFO approach.

4. **Decision points docs** (`docs/maintenance/tax/decision_points/`): Tax law documentation structure. PT-specific decision points.

5. **Tax law source references** (`docs/maintenance/tax/laws/`): Legal citation structure.

### Now Obsolete (discard)

6. **`_extract_loan_repayment_fingerprints()`**: Designed to match TH rows to CG rows for filtering. Not needed: we rebuild FIFO, not filter CG.

7. **`_filter_loan_repayment_lots()`**: Core filtering logic that removes CG entries. Entirely replaced by FIFO rebuild.

8. **`_flag_colocated_entries()` / `_select_review_candidates()`**: Ambiguity resolution for filtered entries. Not needed when we rebuild FIFO ourselves.

9. **Integration wiring in `crypto_reporting.py` pipeline**: The "filter before aggregation" pipeline step. Replaced by "build from TH" pipeline step.

10. **All loan filter tests** (`test_crypto_reporting.py` ~1200 lines): Test the now-obsolete filtering approach.

### Summary

~40% reusable infrastructure (config, sheets, docs) + ~60% obsolete filter logic. Branch cleanup should be part of the revised plan.
