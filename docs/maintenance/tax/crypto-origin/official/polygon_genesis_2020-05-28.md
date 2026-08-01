# Polygon (Matic Network) PoS Mainnet Genesis Extract

## Terminology

- Source page: official Polygon technology documentation describing the
  Matic Network PoS mainnet launch.
- Extracted fact: the PoS mainnet genesis-block date that grounds the
  repository `_CHAIN_LAUNCH_DATE["Polygon"]` value.

## Source

- URL: https://polygon.technology/blog/matic-mainnet-is-live
- Companion URL: https://docs.polygon.technology/pos/get-started/intro/
- Issuing date: 2020-05-28

## Extracted facts

- The Matic Network PoS mainnet (later rebranded to Polygon) launched on
  **2020-05-28**, with the genesis block produced on that date.
- Polygon is the EVM-compatible chain identified by Etherscan V2 chain id 137.

## Repository use

- Grounds `_CHAIN_LAUNCH_DATE["Polygon"] = date(2020, 5, 28)` in
  `src/tax_reporting/application/crypto/chain_derivation.py` (genesis date,
  not the 2024-01-23 Cayman-entity domicile date documented in
  `polygon_terms_2024-01-23.md`).
