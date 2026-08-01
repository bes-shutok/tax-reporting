# Polygon MATIC -> POL Migration Extract

## Terminology

- Source page: official Polygon technology announcement of the MATIC -> POL
  native-asset migration.
- Extracted fact: the migration effective date and the post-migration native
  ticker, grounding the repository on-chain CSV-output ticker for Polygon.

## Source

- URL: https://polygon.technology/blog/polygon-migration-now-complete
- Companion URL (governance proposal): https://polygon.technology/governance/proposals/046
- Issuing date: 2024-09-04

## Extracted facts

- The MATIC -> POL migration completed on **2024-09-04**; POL became the native
  gas and staking token of the Polygon PoS network on that date.
- The native on-chain ticker is `POL` for all activity on/after 2024-09-04
  (FY2025+). `MATIC` is the pre-migration native ticker.

## Repository use

- Grounds `_CHAIN_ON_CHAIN_NATIVE_TICKER["Polygon"] = "POL"` in
  `src/tax_reporting/application/crypto/chain_derivation.py` (the CSV-output
  ticker map for the Etherscan V2 on-chain fetcher).
- This is a SEPARATE contract from `_CHAIN_NATIVE_FEE_ASSET["Polygon"] =
  "MATIC"`, which is the stale-for-CSV Koinly fee-check map left as-is for its
  original consumer (`is_native_gas_fee`).
- Does NOT change the 2020-05-28 PoS mainnet genesis date
  (`polygon_genesis_2020-05-28.md`) or the 2024-01-23 Cayman-entity domicile
  extract (`polygon_terms_2024-01-23.md`).
