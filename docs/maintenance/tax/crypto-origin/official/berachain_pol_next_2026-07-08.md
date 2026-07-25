# Berachain PoL Next Upgrade Extract

## Terminology

- Source page: the official Berachain Proof-of-Liquidity changelog and the official `@berachain` activation announcement.
- Extracted fact: the token-model change (BGT deprecation, WBERA emissions, sWBERA liquid staking) relevant to repository token handling and to taxable-event dating for 2026 BERA-ecosystem activity.

## Source

- URL: https://docs.berachain.com/general/proof-of-liquidity/changelog
- Companion URL (activation date): https://x.com/berachain/status/2074495712000426195
- Issuing date: 2026-07-08 (mainnet hard-fork activation; see date-resolution note below)
- Retrieved on: 2026-07-25

## Extracted facts

- The Proof-of-Liquidity Next (`PoL Next`) upgrade deeply simplifies the Berachain token model.
- `BGT` (Bera Governance Token) is deprecated: it no longer influences validator reward allocation weight, block rewards, or governance.
- Contract emissions switched from `BGT` to `WBERA` (wrapped BERA, 1:1) on **2026-07-07**.
- The hard fork that permanently halts new `BGT` emissions activated on **2026-07-08 at 16:00:00 UTC**.
- Per-block emission rates under PoL Next: `0.4 WBERA` base rate to validator operators and `1.305 WBERA` reward rate to distributors.
- A new liquid-staking receipt token `sWBERA` was introduced as the post-PoL-Next yield path (replacing the old `BGT` reward route).
- Residual `BGT` sitting as an allowance on a Reward Vault is auto-converted to `WBERA` on the next claim from that vault (`no vault-owner action is required, no claim is missed, no balance disappears`).
- `BGT` held in a wallet (not on a vault) is NOT auto-converted: migration must be performed manually via the Berachain Hub (`unboost -> redeem for BERA -> optionally stake into sWBERA`).

## Date-resolution note

- The docs changelog groups this under a "May 2026" header, which reflects when the changelog entry / Bepolia testnet deployment was filed, NOT mainnet activation.
- The authoritative mainnet activation date (2026-07-08 16:00 UTC) comes from the official `@berachain` announcement thread and is corroborated by secondary press.
- For repository tax timing of user transactions, the relevant dates are the user's own redemption / claim transaction timestamps, not the upgrade date itself. The upgrade date is recorded here only as the marker after which no new `BGT` is created.

## Repository use

- Does NOT change the existing `Berachain -> British Virgin Islands` origin mapping (see CMD-001 and `berachain_terms_2025-02-05.md`); the operator entity and governing law are unaffected.
- Supports a forward-looking note that 2026 Koinly exports may surface tokens `WBERA`, `sWBERA`, and residual `BGT` redemptions, and that `BGT -> WBERA/BERA` redemptions are taxable disposals crystallizing at the on-chain transaction timestamp.
- No code or origin-mapping change is implied by this extract alone; the per-token fee ceilings and `popular_crypto_tokens.json` review are deferred to the data-driven plan triggered when 2026 Koinly data is available.
