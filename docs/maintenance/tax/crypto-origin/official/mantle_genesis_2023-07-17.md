# Mantle Mainnet Genesis Extract

## Terminology

- Source page: official Mantle mainnet launch announcement.
- Extracted fact: the Mantle mainnet genesis-block date that grounds the
  repository `_CHAIN_LAUNCH_DATE["Mantle"]` value.

## Source

- URL: https://mantle.network/blog/mantle-network-mainnet-alpha-is-live
- Companion URL: https://docs.mantle.xyz/
- Issuing date: 2023-07-17

## Extracted facts

- Mantle mainnet (mainnet alpha) launched on **2023-07-17**, with the genesis
  block produced on that date (the Mantle token migrated from BIT on
  2023-07-14 ahead of the mainnet launch).
- Mantle is the EVM-compatible L2 chain identified by Etherscan V2 chain id
  5000.

## Repository use

- Grounds `_CHAIN_LAUNCH_DATE["Mantle"] = date(2023, 7, 17)` in
  `src/tax_reporting/application/crypto/chain_derivation.py` (genesis date).
