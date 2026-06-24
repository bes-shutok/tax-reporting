# Feature Note: Embedded and Standalone Fee Filtering Gaps

**Date:** 2026-06-24
**Related Feature:** DP-015 (Filter Standalone Transaction and Network Fees)
**Context:** User observed that certain gas tokens (ETH, BNB, TON) appear in the aggregated Capital Gains output with proceeds exceeding the configured per-token ceilings (e.g. 1.1 EUR for BNB where the ceiling is 0.5 EUR). The user provided three specific examples: ETH on 2025-01-26, BNB on 2025-03-15, and TON on 2025-11-01.

## 1. The Underlying Anomaly: Daily Aggregation

The rows observed in the final Capital Gains output are **not individual Koinly transactions**; they are **daily aggregates** produced by `_aggregate_capital_entries()`. 
When multiple tiny `< 0.5 EUR` fee disposals bypass the fee filter on the same day, they sum together into a single visible row (e.g., `1.1 EUR` or `5.6 EUR`) that appears to violate the per-token ceiling configuration.

## 2. Why Did These Fees Bypass the Filter? (Data Collection)

Based on a detailed trace of the three examples in the Transaction History (TH), each token bypassed the filter for a completely different reason, revealing three distinct gaps:

### Gap A: Embedded Fees in Trades/Transfers (The BNB Example)
*   **The Data:** On `2025-03-15`, the BNB fees were paid during `exchange` and `transfer` transactions. Koinly embeds these fees directly in the primary transaction row using the `Fee Amount` and `Fee Currency` columns, rather than emitting a separate `crypto_withdrawal` row.
*   **The Gap:** The current fee filter restricts its scan strictly to `if row.get("Type", "").strip() != "crypto_withdrawal"`. It completely ignores `exchange` and `transfer` rows.
*   **The Result:** The filter never emits a `FeeThEvent` for these embedded fees, leaving them fully taxable and subject to daily aggregation.

### Gap B: Standalone Fees Failing the Co-occurrence Guard (The ETH Example)
*   **The Data:** On `2025-01-26`, the ETH network fees *were* exported as standalone `crypto_withdrawal` rows and explicitly tagged `Cost` by Koinly. However, their `TxHash` only appeared *once* in the TH CSV (the corresponding `exchange` row had a different TxHash assigned).
*   **The Gap:** The current filter enforces a strict TxHash co-occurrence guard (`tx_hash_counts[tx_hash] >= 2`) for *all* fee paths (even the explicitly tagged `Cost` path). If the `TxHash` only appears once, the filter ignores the `Cost` tag.
*   **The Result:** The trusted `Cost` transaction remains taxable and gets aggregated into the daily totals.

### Gap C: Missing Token Configuration (The TON Example)
*   **The Data:** On `2025-11-01`, the TON fees were correctly exported as untagged `crypto_withdrawal` rows with `< 2.0 EUR` Net Value, and their TxHash co-occurred 4 times. They met all code logic requirements.
*   **The Gap:** `docs/maintenance/tax/decision_points/2025.toml` mentions TON in the comment (`SOL/SUI/BNB/MATIC/TON fees are typically well under 0.50 EUR`), but TON was omitted from the actual `[countries.PT.exclude_transaction_fee_max_eur_per_asset]` table below it.
*   **The Result:** Because TON is not a dict key, the untagged fee path skips it and drops it into the "suspect" bucket instead. Suspects are intentionally *not* removed (Design Invariant 3), so they remain taxable.

### Gap D: Token Configuration Scalability and Duplication
*   **The Data:** Currently, the filter relies entirely on a hardcoded list of tokens in `2025.toml` to identify valid gas tokens for the untagged fee path.
*   **The Gap:** This duplicates configuration. The codebase already maintains a list of major chains in `docs/maintenance/tax/popular_crypto_tokens.json` (`layer_1_major_chains`). However, that list has inaccuracies (e.g., `XSTRK` is a staked derivative, not an L1; `BERA` is missing). Furthermore, `2025.toml` should not duplicate the token list; it should only define threshold overrides (e.g., ETH = 1.0) and a default threshold (e.g., 0.5).
*   **The Result:** Missing configuration (like Gap C) happens easily due to duplicated lists.

## 3. Portuguese Law Consultation (CIRS)

**Question:** Should embedded trading fees and standalone single-TxHash network fees be excluded from Capital Gains under Portuguese law?

**Analysis:**
*   Under **CIRS Art. 10(1)(k)**, crypto taxation applies to *alienação onerosa* (an onerous disposal).
*   An *alienação onerosa* intrinsically requires receiving **consideration** in exchange for the disposed asset (e.g., fiat, another token, or goods/services).
*   Network fees (gas) and exchange trading fees paid in crypto are utility costs incurred to execute a transaction. When you dispose of a fraction of BNB or ETH to pay the network/exchange, you receive no consideration *for that specific disposed fraction*.
*   **Conclusion:** Whether Koinly represents the fee as a standalone `crypto_withdrawal` or embeds it inside an `exchange` row, the economic reality is identical: it is a utility cost, not an *alienação onerosa*. **Both embedded fees and standalone network fees should be excluded from taxable Capital Gains.**

## 4. Requirements for a Future Fix Plan

To fix this issue in a future implementation plan, the following logic changes are required:

1.  **Parse Embedded Fees (`fee_filter.py`):** Remove the strict `crypto_withdrawal` check. Scan *all* TH rows for non-empty `Fee Amount` and `Fee Currency` columns. Treat these embedded fees as untagged fee events (subject to the per-token EUR ceilings). They do not require a TxHash co-occurrence guard because being in the `Fee` column intrinsically proves they are fees.
2.  **Relax Tagged Co-occurrence (`fee_filter.py`):** For `crypto_withdrawal` rows that are explicitly tagged `Cost` or `Loan fee`, drop the TxHash co-occurrence requirement (`>= 2`). The explicit tag from Koinly is sufficient authority to filter it.
3.  **Preserve Untagged Co-occurrence (`fee_filter.py`):** Maintain the TxHash co-occurrence guard *only* for untagged standalone `crypto_withdrawal` rows to prevent real small-asset disposals from being falsely filtered.
4.  **Refactor Token Configuration (`2025.toml` and `popular_crypto_tokens.json`):**
    *   **Fix JSON:** In `docs/maintenance/tax/popular_crypto_tokens.json`, remove `XSTRK` from `layer_1_major_chains` (move it to `restaking_lrt_depin`) and add `BERA` to `layer_1_major_chains`.
    *   **Update TOML:** Change `2025.toml` to introduce `exclude_transaction_fee_default_max_eur = 0.5`. Reduce the `exclude_transaction_fee_max_eur_per_asset` table to *only* explicit overrides (e.g., `ETH = 1.0`, `BERA = 0.1`).
    *   **Update Filter Logic:** Refactor the fee filter to load the `layer_1_major_chains` list. An untagged fee is allowed if its asset is in `layer_1_major_chains`; its threshold is the specific TOML override if present, otherwise the TOML default.
