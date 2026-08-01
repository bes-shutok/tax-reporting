# Ethereum Mainnet Genesis Extract

## Terminology

- Source page: official Ethereum mainnet launch / Frontier announcement.
- Extracted fact: the mainnet genesis-block (block 0) date that grounds the
  repository `_CHAIN_LAUNCH_DATE["Ethereum"]` value.

## Source

- URL: https://blog.ethereum.org/2015/07/30/ethereum-frontier-is-live
- Companion URL (history): https://ethereum.org/en/history
- Issuing date: 2015-07-30

## Extracted facts

- The Ethereum mainnet ("Frontier") launched on **2015-07-30**.
- Block 0 (the genesis block) carries a timestamp of 2015-07-30, establishing
  this as the first mainnet block date.

## Repository use

- Grounds `_CHAIN_LAUNCH_DATE["Ethereum"] = date(2015, 7, 30)` in
  `src/tax_reporting/application/crypto/chain_derivation.py` (genesis date,
  not the 2024-05-08 Swiss-Stiftung domicile date documented in
  `ethereum_foundation_2024-05-08.md`).
