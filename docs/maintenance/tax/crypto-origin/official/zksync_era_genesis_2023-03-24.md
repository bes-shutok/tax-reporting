# zkSync Era Mainnet Genesis Extract

## Terminology

- Source page: official Matter Labs zkSync Era mainnet launch announcement.
- Extracted fact: the zkSync Era mainnet genesis-block date that grounds the
  repository `_CHAIN_LAUNCH_DATE["zkSync ERA"]` value.

## Source

- URL: https://matterlabs.introduction/blog/zksync-era-mainnet-is-live
- Companion URL: https://docs.zksync.io/
- Issuing date: 2023-03-24

## Extracted facts

- zkSync Era mainnet launched on **2023-03-24** (full alpha open to all users),
  with the genesis block produced on that date.
- zkSync Era is the EVM-compatible L2 chain identified by Etherscan V2 chain
  id 324.

## Repository use

- Grounds `_CHAIN_LAUNCH_DATE["zkSync ERA"] = date(2023, 3, 24)` in
  `src/tax_reporting/application/crypto/chain_derivation.py` (genesis date,
  not the Matter Labs legal-entity terms date in
  `zksync_terms_undated.md`).
