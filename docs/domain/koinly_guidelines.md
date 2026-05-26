# Koinly Guidelines

Known Koinly behaviors, defects, and repair workflows that affect crypto tax processing.
Consult this document before processing Koinly exports or changing Koinly-related code.

For Portuguese-specific divergences between Koinly's treatment and CIRS tax law, see `docs/tax/laws/pt/crypto-tax/platform-divergences.md`.

---

## Section 1 -- Loan Repayment Treated as Taxable Disposal

Koinly treats `crypto_withdrawal` with tag `Loan repayment` as a **taxable disposal** by design. This is correct for US/UK/AU/DE but diverges from Portuguese law (CIRS art. 10(20)).

The `Loan repayment` tag is purely cosmetic and does not change the disposal behavior. The `"Realize gains on crypto-to-crypto trades?"` setting only controls `exchange` type transactions, not `crypto_withdrawal`.

Per Koinly's help center:
> "Repayment of a crypto loan in Koinly is equivalent to a disposal (selling crypto to a 3rd party)."
> -- [Crypto loans, repayments and collateral](https://support.koinly.io/en/articles/9490026)

> "Loan repayment, Margin repayment -- These tags do not change the behavior of the transaction (it remains a disposal)."
> -- [What are Tags](https://support.koinly.io/en/articles/9490023)

For the Portuguese legal analysis, jurisdiction comparison, and manual workarounds, see `docs/tax/laws/pt/crypto-tax/platform-divergences.md` Section 1.

Pipeline impact: loan repayment capital gains must be filtered from the Portuguese tax report after aggregation. See `docs/plans/2026-05-25-filter-loan-repayment-gains.md`.

---

## Section 2 -- Wrapped-Asset Pool Flow Repair (SUI/sSUI)

### The problem

Koinly's Sui blockchain decoder sometimes flattens a multi-step DeFi operation incorrectly:
- On-chain: `SUI -> sSUI -> Add to Pool` in one transaction
- Koinly import: single `SUI` `Send` tagged `Add to Pool`
- Unwind: `sSUI` `Deposit` tagged `Remove from Pool` plus a broken `sSUI` `Send` / loan repayment

This loses cost basis continuity because the pool-in is stored as `SUI` while the pool-out is stored as `sSUI`.

### Glossary

- `Send`: Koinly transaction type for a one-sided outgoing asset movement.
- `Deposit`: Koinly transaction type for a one-sided incoming asset movement.
- `Exchange`: Koinly transaction type for a two-sided asset conversion.
- `Swap`: Koinly tag applied to an `Exchange` so basis and acquisition date carry across the conversion.
- `Add to Pool`: Koinly tag applied to a `Send` that moves the asset into a pool position.
- `Remove from Pool`: Koinly tag applied to a `Deposit` that returns the asset from a pool position.

### Goal

Restore the economic flow so Koinly preserves basis across the wrapped-asset conversion:

- Loan / pool in side: `SUI` loan, then `SUI -> sSUI` tagged `Swap`, then `sSUI` `Send` tagged `Add to Pool`
- Pool out / repay side: `sSUI` `Deposit` tagged `Remove from Pool`, then `sSUI -> SUI` tagged `Swap`, then `SUI` repay

### Generic Example

- Loan / pool in side:
  - On-chain: `100 SUI` is borrowed, `100 SUI` becomes `98.5 sSUI`, then `98.5 sSUI` is deposited into the pool
  - Broken Koinly import: one `100 SUI` `Send` later tagged `Add to Pool`

- Pool out / repay side:
  - On-chain: `98.5 sSUI` leaves the pool, converts back into `100 SUI`, then `100 SUI` is used to repay the loan
  - Broken Koinly import: one `98.5 sSUI` `Send` / loan repayment

### Repair Workflow

#### Pool In Side

If Koinly imported a one-click pool-in as a single `SUI` `Send`:

1. Create a manual duplicate first, then edit that duplicate into an `Exchange` from `SUI` to `sSUI` using the on-chain amounts. Save it and tag it `Swap`.
2. Edit the original imported row into an `sSUI` `Send` using the same on-chain `sSUI` amount, then tag it `Add to Pool`.

Result:
- Manual duplicate: `SUI -> sSUI`, tag `Swap`
- Original synced row: `sSUI` `Send`, tag `Add to Pool`

#### Pool Out Side

If Koinly already has a separate pool-out `Deposit` row, keep that row and repair only the broken `Send` / repayment leg:

1. Ensure the pool return row is an `sSUI` `Deposit` tagged `Remove from Pool`, then create a manual duplicate of the broken `sSUI` `Send` / repayment row and edit the duplicate into the actual `SUI` loan repayment row.
2. Edit the original broken row into an `Exchange` from `sSUI` to `SUI` using the on-chain amounts, then tag it `Swap`.

Result:
- Existing synced row: `sSUI` deposit, tag `Remove from Pool`
- Original edited row: `sSUI -> SUI`, tag `Swap`
- Manual duplicate: `SUI` loan repayment

### Why Duplicate First

Duplicate first because it is the safest reversible workflow:
- The original synced transaction stays intact until the replacement row exists.
- The copied row inherits the useful timestamp and wallet context.
- If the edit goes wrong, the source row still exists.

### Resync Guidance

- Prefer keeping one synced row in the repaired flow where possible and adding only the minimum number of manual rows.
- Manual rows are safer than relying on Koinly to infer the missing wrapped-token leg later.
- A future importer improvement could still add a new auto-imported wrapped-token row. After any full resync, re-check the repaired transactions for duplicates.

### Validation Checklist

After each repair:

1. Confirm the wrapped asset is the one entering and leaving the pool.
2. Confirm the `Swap` tag carries basis and acquisition date from `SUI` into `sSUI` and back.
3. Confirm the principal returned from the pool is represented as an `sSUI` `Deposit` tagged `Remove from Pool`, not still tagged `Reward`.
4. Confirm the final loan repayment uses `SUI`, not `sSUI`, if the on-chain repayment is in `SUI`.
5. Re-open the affected capital gain rows and verify that the fake zero-basis gain disappeared or reduced to the actual economic gain.

### When Not To Use This Workaround

Do not apply this pattern when Koinly already imported all three legs correctly:
- `SUI -> sSUI` trade
- `sSUI` `Send` tagged `Add to Pool`
- `sSUI` `Deposit` tagged `Remove from Pool`

In that case, only fix the specific mislabeled row instead of reconstructing the whole flow.

---

## Section 3 -- Koinly Sources

Official documentation consulted:

| Article | URL | Key takeaway |
|---------|-----|-------------|
| Crypto loans, repayments and collateral | https://support.koinly.io/en/articles/9490026 | Loan repayment = disposal by design |
| What are Tags | https://support.koinly.io/en/articles/9490023 | Loan repayment tag is cosmetic only |
| What are transactions in Koinly | https://support.koinly.io/en/articles/9490022 | Transfer type is always tax-free |
| How Koinly handles transfers | https://support.koinly.io/en/articles/9490024 | Only between your own wallets |
| Custom CSV format | https://support.koinly.io/en/articles/8726314 | Import format reference |
| DeFi loaning and borrowing (blog) | https://koinly.io/blog/defi-loaning-and-borrowing-how-is-it-taxed/ | General info, contradicts help center on loans |
| Loan repayment discussion (community) | https://discuss.koinly.io/t/loan-repayment-isnt-a-profit-how-to-treat/19201 | Koinly staff recommends "change worth" workaround |
