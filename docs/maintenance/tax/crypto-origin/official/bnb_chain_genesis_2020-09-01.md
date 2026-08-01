# BNB Chain (BSC) Mainnet Genesis Extract

## Terminology

- Source page: official BNB Chain documentation describing the Beacon Chain /
  BSC mainnet launch.
- Extracted fact: the BSC mainnet genesis-block date that grounds the
  repository `_CHAIN_LAUNCH_DATE["Binance Smart Chain"]` value.

## Source

- URL: https://docs.bnbchain.org/bnb-smart-chain/overview/#mainnet-launch
- Companion URL: https://www.bnbchain.org/en/bnb-chain-history
- Issuing date: 2020-09-01

## Extracted facts

- The Binance Smart Chain (BSC) mainnet launched on **2020-09-01**, with the
  genesis block produced on that date.
- BSC is the EVM-compatible chain identified by Etherscan V2 chain id 56.

## Repository use

- Grounds `_CHAIN_LAUNCH_DATE["Binance Smart Chain"] = date(2020, 9, 1)` in
  `src/tax_reporting/application/crypto/chain_derivation.py` (genesis date,
  not the 2026-01 domicile/operator terms date documented in
  `bnb_chain_terms_2026-01.md`).
