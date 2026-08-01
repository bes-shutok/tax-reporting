# Arbitrum One Mainnet Genesis Extract

## Terminology

- Source page: official Arbitrum / Offchain Labs mainnet launch announcement.
- Extracted fact: the Arbitrum One mainnet genesis-block date that grounds the
  repository `_CHAIN_LAUNCH_DATE["Arbitrum"]` value.

## Source

- URL: https://arbitrum.foundation/post/launching-arbitrum-one
- Companion URL: https://docs.arbitrum.io/welcome/get-started-intro
- Issuing date: 2021-08-31

## Extracted facts

- Arbitrum One mainnet launched on **2021-08-31** (mainnet open to all users),
  with the genesis block produced on that date.
- Arbitrum is the EVM-compatible L2 chain identified by Etherscan V2 chain id
  42161.

## Repository use

- Grounds `_CHAIN_LAUNCH_DATE["Arbitrum"] = date(2021, 8, 31)` in
  `src/tax_reporting/application/crypto/chain_derivation.py` (genesis date,
  not the 2023-07-20 Arbitrum Foundation Cayman M&A document in
  `arbitrum_foundation_ma_2023-07-20.md`).
