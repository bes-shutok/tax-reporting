# Base Mainnet Genesis Extract

## Terminology

- Source page: official Base / Coinbase mainnet launch announcement.
- Extracted fact: the Base mainnet genesis-block date that grounds the
  repository `_CHAIN_LAUNCH_DATE["BASE"]` value.

## Source

- URL: https://base.org/blog/base-mainnet-is-live
- Companion URL: https://docs.base.org/getting-started
- Issuing date: 2023-08-09

## Extracted facts

- Base mainnet launched on **2023-08-09** (public mainnet open to all users),
  with the genesis block produced on that date.
- Base is the EVM-compatible L2 chain identified by Etherscan V2 chain id 8453.

## Repository use

- Grounds `_CHAIN_LAUNCH_DATE["BASE"] = date(2023, 8, 9)` in
  `src/tax_reporting/application/crypto/chain_derivation.py` (genesis date,
  not the 2025-12-04 Coinbase Technologies service-operator terms date in
  `base_terms_2025-12-04.md`).
