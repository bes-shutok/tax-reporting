# Koinly Guidelines

Repository-facing guidance for repairing known Koinly import defects before relying on exported gain/loss data.

## Glossary

- `Send`: Koinly transaction type for a one-sided outgoing asset movement.
- `Deposit`: Koinly transaction type for a one-sided incoming asset movement.
- `Exchange`: Koinly transaction type for a two-sided asset conversion.
- `Swap`: Koinly tag applied to an `Exchange` so basis and acquisition date carry across the conversion.
- `Add to Pool`: Koinly tag applied to a `Send` that moves the asset into a pool position.
- `Remove from Pool`: Koinly tag applied to a `Deposit` that returns the asset from a pool position.

## Scope

This note covers a specific DeFi decoding problem:

- the on-chain action is effectively `SUI -> sSUI -> Add to Pool` in one transaction
- Koinly flattens that into a plain `SUI` `Send` later tagged as `Add to Pool`
- the unwind later appears as an `sSUI` `Deposit` tagged `Remove from Pool` plus a broken `sSUI` `Send` / loan repayment

When this happens, Koinly can lose cost basis continuity because the pool-in is stored as `SUI` while the pool-out is stored as `sSUI`.

## Goal

Restore the economic flow so Koinly preserves basis across the wrapped-asset conversion:

- loan / pool in side: `SUI` loan, then `SUI -> sSUI` tagged `Swap`, then `sSUI` `Send` tagged `Add to Pool`
- pool out / repay side: `sSUI` `Deposit` tagged `Remove from Pool`, then `sSUI -> SUI` tagged `Swap`, then `SUI` repay

## Generic Example

Use a generic example rather than copying wallet-specific values:

- loan / pool in side:
  - on-chain: `100 SUI` is borrowed, `100 SUI` becomes `98.5 sSUI`, then `98.5 sSUI` is deposited into the pool
  - broken Koinly import: one `100 SUI` `Send` later tagged `Add to Pool`

- pool out / repay side:
  - on-chain: `98.5 sSUI` leaves the pool, converts back into `100 SUI`, then `100 SUI` is used to repay the loan
  - broken Koinly import: one `98.5 sSUI` `Send` / loan repayment

## Repair Workflow

### Pool In Side

If Koinly imported a one-click pool-in as a single `SUI` `Send`:

1. Create a manual duplicate first, then edit that duplicate into an `Exchange` from `SUI` to `sSUI` using the on-chain amounts. Save it and tag it `Swap`.
2. Edit the original imported row into an `sSUI` `Send` using the same on-chain `sSUI` amount, then tag it `Add to Pool`.

Result:

- manual duplicate: `SUI -> sSUI`, tag `Swap`
- original synced row: `sSUI` `Send`, tag `Add to Pool`

### Pool Out Side

If Koinly already has a separate pool-out `Deposit` row, keep that row and repair only the broken `Send` / repayment leg:

1. Ensure the pool return row is an `sSUI` `Deposit` tagged `Remove from Pool`, then create a manual duplicate of the broken `sSUI` `Send` / repayment row and edit the duplicate into the actual `SUI` loan repayment row.
2. Edit the original broken row into an `Exchange` from `sSUI` to `SUI` using the on-chain amounts, then tag it `Swap`.

Result:

- existing synced row: `sSUI` deposit, tag `Remove from Pool`
- original edited row: `sSUI -> SUI`, tag `Swap`
- manual duplicate: `SUI` loan repayment

## Why Duplicate First

Duplicate first because it is the safest reversible workflow:

- the original synced transaction stays intact until the replacement row exists
- the copied row inherits the useful timestamp and wallet context
- if the edit goes wrong, the source row still exists

## Resync Guidance

- Prefer keeping one synced row in the repaired flow where possible and adding only the minimum number of manual rows.
- Manual rows are safer than relying on Koinly to infer the missing wrapped-token leg later.
- A future importer improvement could still add a new auto-imported wrapped-token row. After any full resync, re-check the repaired transactions for duplicates.

## Validation Checklist

After each repair:

1. Confirm the wrapped asset is the one entering and leaving the pool.
2. Confirm the `Swap` carries basis from `SUI` into `sSUI` and back.
3. Confirm the principal returned from the pool is represented as an `sSUI` `Deposit` tagged `Remove from Pool`, not still tagged `Reward`.
4. Confirm the final loan repayment uses `SUI`, not `sSUI`, if the on-chain repayment is in `SUI`.
5. Re-open the affected capital gain rows and verify that the fake zero-basis gain disappeared or reduced to the actual economic gain.

## When Not To Use This Workaround

Do not apply this pattern when Koinly already imported all three legs correctly:

- `SUI -> sSUI` trade
- `sSUI` `Send` tagged `Add to Pool`
- `sSUI` `Deposit` tagged `Remove from Pool`

In that case, only fix the specific mislabeled row instead of reconstructing the whole flow.
