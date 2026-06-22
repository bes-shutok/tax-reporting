# Proposal: Treat Crypto Transfer Fees as Non-Taxable Costs (DP-006 & DP-007)

- **Status:** PROPOSAL / FEATURE SUGGESTION
- **Date:** 2026-06-21
- **Related:** 
  - Decision Points: [2025.md](../../maintenance/tax/decision_points/2025.md) (DP-006, DP-007)
  - Platform Divergences: [platform-divergences.md](../pt/crypto-tax/platform-divergences.md)
  - Koinly Guidelines: [koinly_guidelines.md](../../maintenance/koinly_guidelines.md)

---

## 1. Executive Summary

When transferring crypto-assets between a taxpayer's own wallets (e.g., from one centralized exchange to another, or to a self-custody wallet), the transfer itself is a non-taxable event. However, these transactions incur transfer/network fees paid in crypto-assets (such as BTC, JUP, or gas tokens). 

Koinly's default settings treat these fee payments as **taxable disposals** of the fee token. If the fee token has appreciated since it was acquired, Koinly realizes a capital gain on the fee and reports it as a profit in the **Crypto Gains** report.

Under Portuguese tax law, the consumption of crypto-assets to pay for network or platform transfer fees is **not a taxable disposal** because there is no onerous exchange (no fiat, other crypto, or valuable consideration is received in return). Rather, the fee is a transaction expense. Realizing a taxable gain on this fee creates a "phantom gain" that overstates the taxpayer's liability.

This proposal documents the issue, analyzes two specific examples from the FY2025 data (2025-02-02), explains the legal basis for treating these fees as non-taxable, and outlines options to correct this platform divergence.

---

## 2. Investigated Examples (FY2025 Data: 2025-02-02)

Two clear examples of this divergence occur in the user's transaction data on February 2, 2025:

### Example A: JUP Transfer (ByBit to Kraken)

*   **Timestamp:** 2025-02-02 10:52:03 UTC
*   **Transaction Type:** Transfer (wallet-to-wallet)
*   **Asset:** JUP (Jupiter)
*   **Amounts:** 453.58596000 JUP sent from ByBit; 452.78596000 JUP received at Kraken.
*   **Transfer Fee:** **0.80000000 JUP** (Fair Market Value: **0.74 EUR**)
*   **FIFO Cost Basis of Fee:** **0.40 EUR** (derived from the JUP acquisition lot on 2025-01-27)
*   **Koinly Treatment:**
    *   Koinly generated a capital gain row in the Capital Gains Report:
        ```text
        02/02/2025 10:52, 27/01/2025 15:09, JUP, 0.80000000, 0.40, 0.74, 0.35, Fee, ByBit, Short term
        ```
    *   It treated the 0.8 JUP fee as a taxable disposal, resulting in a **0.35 EUR realized gain** (profit) included in the total taxable capital gains.

### Example B: BTC Transfer (Gate.io to Kraken)

*   **Timestamp:** 2025-02-02 11:32:26 UTC
*   **Transaction Type:** Transfer (wallet-to-wallet)
*   **Asset:** BTC (Bitcoin)
*   **Amounts:** 0.10062586 BTC sent from Gate.io; 0.10052586 BTC received at Kraken.
*   **Transfer Fee:** **0.00010000 BTC** (Fair Market Value: **9.52 EUR**)
*   **FIFO Cost Basis of Fee:** **0.00 EUR** (due to rounding or a zero-cost lot acquired on 2025-01-23)
*   **Koinly Treatment:**
    *   Koinly generated a capital gain row in the Capital Gains Report:
        ```text
        02/02/2025 11:32, 23/01/2025 14:26, BTC, 0.00010000, 0.0, 9.52, 9.52, Fee, Gate.io, Short term
        ```
    *   It treated the 0.0001 BTC fee as a taxable disposal, resulting in a **9.52 EUR realized gain** (profit) included in the total taxable capital gains.

---

## 3. Portuguese Legal Analysis

The current configuration of the tax-reporting tool (DP-006) lists "Realize gains on transfer fees? = ON" as a requirement, citing the AT Leaflet (*Folheto Criptoativos* 2026-01-12) on "alienação onerosa". However, a closer reading of Portuguese statutory law reveals a clear divergence:

1.  **Narrow Definition of Taxable Event:** Under **CIRS Article 10(1)(k)**, capital gains are only triggered by the *"alienação onerosa de criptoativos"* (onerous disposal of crypto-assets). 
2.  **No Consideration (Onerous Exchange):** An onerous disposal requires an exchange where the taxpayer receives consideration (e.g., fiat currency or other property). Paying a transaction fee to a decentralized network (miners) or a centralized exchange to move one's own assets does not result in the taxpayer receiving any currency or property. The fee is a utility consumption/holding cost, not an exchange.
3.  **No Administrative Deeming Provisions:** Unlike the US (IRS), UK (HMRC), and Australia (ATO), which have published specific administrative guidelines declaring that paying network/gas fees in crypto is a taxable disposal of the fee token, the Portuguese Tax Authority (AT) has issued no such guidance. The law only taxes actual alienations, and tax laws in Portugal must be interpreted strictly according to their plain text (principle of legality).
4.  **Deductibility of Expenses:** Under **CIRS Article 10(4)(a)**, net capital gains (*"líquidos"*) are calculated by deducting *"despesas necessárias e efetivamente praticadas, inerentes à aquisição e alienação"*. A transfer fee is a transaction expense. Instead of triggering a taxable disposal itself, the cost value of the fee should either:
    *   Be added to the acquisition cost (increasing the cost basis) of the transferred assets, or
    *   Be deducted as a disposal expense when the transferred assets are eventually sold for fiat.

**Conclusion:** Treating crypto transfer fees as taxable disposals that generate capital gains is a compliance error for Portugal. They should be treated as non-taxable costs/losses.

---

## 4. Implementation Options

To correct this behavior, the tax-reporting system has two main options:

### Option 1: Disable "Realize gains on transfer fees?" in Koinly (Recommended)

*   **Description:** Change the Portfolio Setting `"Realize gains on transfer fees?"` (or `"Treat transfer fees as disposals"`) to **DISABLED** (OFF) within Koinly's interface.
*   **Behavior:** 
    *   Koinly will remove the "Fee" disposal rows (such as the 0.35 EUR gain for JUP and 9.52 EUR gain for BTC) from the exported Capital Gains CSV.
    *   The fee tokens are still deducted from the user's balances (so ledger balances remain correct).
    *   Koinly will automatically distribute the value of the transfer fee to increase the cost basis of the transferred asset. This correctly treats the fee as an acquisition/holding cost.
*   **Pros:** Solves the problem at the data source; no custom Python code or pipeline filtering required.
*   **Cons:** Requires the user to change settings in their Koinly UI and re-export the reports.

### Option 2: Pipeline-Level Exclusion (Python Code Filter)

*   **Description:** Keep the setting `ON` in Koinly but filter out transfer fee gains during the Python data-ingestion pipeline.
*   **Behavior:**
    *   The parser in `src/tax_reporting/application/crypto_reporting.py` or the capital gains loader can inspect the `Notes` column of the Koinly Capital Gains CSV.
    *   Any row where `Notes == "Fee"` (or where the transaction is identified as a transfer fee disposal) is skipped and excluded from the aggregation.
*   **Pros:** Requires no changes by the user in Koinly; fully automated in the reporting pipeline.
*   **Cons:** Increases complexity in custom code; requires maintaining a string-matching filter on Koinly's `Notes` column.

---

## 5. Proposed Modifications to Documentation and Configuration

If the user approves moving forward with Option 1 or Option 2, the following files should be updated:

1.  **[2025.md](../../maintenance/tax/decision_points/2025.md) (Decision Point DP-006):**
    *   Change PT status to **No** (Transfer fees are not taxable disposals).
    *   Change Koinly Setting to `"Realize gains on transfer fees?"` = **OFF** (or N/A if handled by code filter).
    *   Update legal basis and notes to reflect that transfer fees are utility consumption/costs without consideration, and realizing gains is incorrect for PT.
2.  **[2025.toml](../../maintenance/tax/decision_points/2025.toml):**
    *   If Option 2 is chosen, add a configuration flag `exclude_transfer_fee_gains = true` to trigger the pipeline filter.
3.  **[platform-divergences.md](../pt/crypto-tax/platform-divergences.md):**
    *   Add a new section: **"3. Transfer Fees Treated as Taxable Disposals"** documenting Koinly's default behavior, the Portuguese legal position, the JUP and BTC examples, and the workarounds.
    *   Update Section 2's Recommended Settings table to show `Realize gains on transfer fees? = DISABLED`.
4.  **[assumptions_sheet.py]((../../../../src/tax_reporting/application/persisting/assumptions_sheet.py)) (DP-006 Methodology text):**
    *   Update the Excel sheet builder's description of DP-006 to state that transfer fees are non-taxable costs, and realizing gains is disabled to comply with PT law.
