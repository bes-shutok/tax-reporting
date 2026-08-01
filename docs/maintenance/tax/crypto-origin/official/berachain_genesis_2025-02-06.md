# Berachain Mainnet Genesis Extract

## Terminology

- Source page: launch-day reporting (Blockworks / Bankless) and the official
  Berachain mainnet announcement.
- Extracted fact: the mainnet genesis-block date that grounds the repository
  `_CHAIN_LAUNCH_DATE["Berachain"]` value.

## Source

- URL: https://blockworks.co/news/berachain-mainnet-live
- Companion URL: https://x.com/berachain/status/1889446634270310529
- Issuing date: 2025-02-06

## Extracted facts

- Berachain mainnet launched on **2025-02-06** (genesis block); this is the
  date mainnet blocks began carrying real transactions.
- This is deliberately NOT the operator registry's `service_start_date:
  2025-02-05` (the BERA Chain Foundation legal-entity service date) - a
  different semantic. The two dates differ by one day.

## Repository use

- Grounds `_CHAIN_LAUNCH_DATE["Berachain"] = date(2025, 2, 6)` in
  `src/tax_reporting/application/crypto/chain_derivation.py` (genesis date,
  matching the prior `_EARLIEST_BERA_TX_DATE` constant in
  `on_chain_config.py`, not the 2025-02-05 legal-entity service date in
  `berachain_terms_2025-02-05.md`).
