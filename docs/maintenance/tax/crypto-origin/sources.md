# Crypto Origin Source Manifest

Retrieved on: 2026-03-15

## Terminology

- Official extract: a local Markdown representation of an official HTML source.
- Inferred mapping: a country choice derived from official materials that stop short of naming the domicile directly.
- Repository override: a user-directed local filing choice recorded explicitly.

## Official extracts

1. `official/berachain_terms_2025-02-05.md`
- URL: https://www.berachain.com/terms-of-service
- Issuing date: 2025-02-05
- Purpose: Berachain Foundation / governing-law extract for Berachain origin mapping.

18. `official/berachain_pol_next_2026-07-08.md`
- URL: https://docs.berachain.com/general/proof-of-liquidity/changelog
- Companion URL: https://x.com/berachain/status/2074495712000426195
- Issuing date: 2026-07-08 (mainnet activation; date conflict resolved in extract)
- Purpose: PoL Next token-model change (BGT deprecation, WBERA emissions, sWBERA) and taxable-event dating for 2026 BERA-ecosystem activity. Does not change the BVI origin mapping.

2. `official/starknet_foundation_privacy_undated.md`
- URL: https://www.starknet.io/privacy-policy/
- Issuing date: undated
- Purpose: Official privacy extract used for the current Starknet Foundation Cayman inference.

3. `official/zksync_terms_undated.md`
- URL: https://zksync.io/terms
- Issuing date: undated
- Purpose: Matter Labs legal-entity extract for zkSync ERA origin mapping.

4. `official/solana_foundation_site_undated.md`
- URL: https://solana.org/
- Issuing date: undated
- Purpose: Solana Foundation location extract for Solana origin mapping.

5. `official/ton_foundation_site_undated.md`
- URL: https://ton.foundation/
- Issuing date: undated
- Purpose: TON Foundation location extract for TON origin mapping.

6. `official/ethereum_foundation_2024-05-08.md`
- URL: https://blog.ethereum.org/2024/05/08/ethereum-foundation-report-2024
- Issuing date: 2024-05-08
- Purpose: Ethereum Foundation Swiss legal-form extract for Ethereum origin mapping.

7. `official/aptos_terms_2025-08-29.md`
- URL: https://aptosfoundation.org/terms
- Issuing date: 2025-08-29
- Purpose: Aptos Foundation registered-address extract for Aptos origin mapping.

8. `official/bnb_chain_terms_2026-01.md`
- URL: https://www.bnbchain.org/en/terms
- Issuing date: 2026-01
- Purpose: BNB Chain operator extract documenting the upstream ADGM / UAE position before repository override handling.

9. `official/arbitrum_foundation_ma_2023-07-20.md`
- URL: https://docs.arbitrum.foundation/assets/files/The%20Arbitrum%20Foundation%20M%26A%20-%2020%20July%202023-6e264ee4c38da73a3aa4c8581c5f751f.pdf
- Issuing date: 2023-07-20
- Purpose: Official Arbitrum Foundation Cayman-company extract.

10. `official/polygon_terms_2024-01-23.md`
- URL: https://polygon.technology/terms-of-use
- Issuing date: 2024-01-23
- Purpose: Official Polygon Cayman-entity extract.

11. `official/base_terms_2025-12-04.md`
- URL: https://docs.base.org/terms-of-service
- Issuing date: 2025-12-04
- Purpose: Official Base service-operator extract tying the exposed legal interface to Coinbase Technologies, Inc.

12. `official/filecoin_foundation_job_board_privacy_2024-04.md`
- URL: https://careers.fil.org/privacy-policy
- Issuing date: 2024-04
- Purpose: Official Filecoin Foundation registered-address extract.

13. `official/tonkeeper_terms_2025-02-12.md`
- URL: https://tonkeeper.com/terms
- Issuing date: 2025-02-12
- Purpose: Official Tonkeeper operator extract.

14. `official/sui_terms_undated.md`
- URL: https://www.sui.io/terms
- Issuing date: undated
- Purpose: Sui Foundation extract for Sui origin mapping.

15. `official/kraken_eea_licensing_undated.md`
- URL: https://support.kraken.com/articles/where-is-kraken-licensed-or-regulated
- Issuing date: undated
- Purpose: EEA-facing Kraken entity extract for Ireland mapping.

16. `official/gate_eu_about_undated.md`
- URL: https://www.gate.com/en-eu/about-us
- Issuing date: undated
- Purpose: Gate Europe / Malta extract for Gate.io EEA mapping.

17. Wirex account terms
- URL: https://wirexapp.com/legal
- Issuing date: verified 2026-03-08
- Purpose: Wirex service-scope split documentation (Wirex Limited GB for fiat, Wirex Digital HR for crypto).

## Mainnet genesis-date extracts (chain registry)

Added 2026-08-01 for plan `2026-08-01-minimal-chains-json-config` Task 1. These
archive the mainnet genesis/first-block DATE for each EVM chain (not the
legal-entity domicile dates in the entries above) and the Polygon MATIC->POL
ticker migration. They ground the `_CHAIN_LAUNCH_DATE` and
`_CHAIN_ON_CHAIN_NATIVE_TICKER` maps in
`src/tax_reporting/application/crypto/chain_derivation.py`.

19. `official/ethereum_genesis_2015-07-30.md`
- URL: https://blog.ethereum.org/2015/07/30/ethereum-frontier-is-live
- Companion URL: https://ethereum.org/en/history
- Issuing date: 2015-07-30
- Purpose: Ethereum mainnet (Frontier) genesis-block date, grounding `_CHAIN_LAUNCH_DATE["Ethereum"] = 2015-07-30` (not the 2024-05-08 Swiss-Stiftung domicile date in entry 6).

20. `official/bnb_chain_genesis_2020-09-01.md`
- URL: https://docs.bnbchain.org/bnb-smart-chain/overview/#mainnet-launch
- Companion URL: https://www.bnbchain.org/en/bnb-chain-history
- Issuing date: 2020-09-01
- Purpose: BNB Smart Chain mainnet genesis-block date, grounding `_CHAIN_LAUNCH_DATE["Binance Smart Chain"] = 2020-09-01` (not the 2026-01 domicile date in entry 8).

21. `official/berachain_genesis_2025-02-06.md`
- URL: https://blockworks.co/news/berachain-mainnet-live
- Companion URL: https://x.com/berachain/status/1889446634270310529
- Issuing date: 2025-02-06
- Purpose: Berachain mainnet genesis-block date, grounding `_CHAIN_LAUNCH_DATE["Berachain"] = 2025-02-06` (genesis, not the 2025-02-05 legal-entity service date in entry 1; matches the prior `_EARLIEST_BERA_TX_DATE` constant).

22. `official/polygon_genesis_2020-05-28.md`
- URL: https://polygon.technology/blog/matic-mainnet-is-live
- Companion URL: https://docs.polygon.technology/pos/get-started/intro/
- Issuing date: 2020-05-28
- Purpose: Polygon (Matic Network) PoS mainnet genesis-block date, grounding `_CHAIN_LAUNCH_DATE["Polygon"] = 2020-05-28` (not the 2024-01-23 Cayman-entity date in entry 10).

23. `official/arbitrum_genesis_2021-08-31.md`
- URL: https://arbitrum.foundation/post/launching-arbitrum-one
- Companion URL: https://docs.arbitrum.io/welcome/get-started-intro
- Issuing date: 2021-08-31
- Purpose: Arbitrum One mainnet genesis-block date, grounding `_CHAIN_LAUNCH_DATE["Arbitrum"] = 2021-08-31` (not the 2023-07-20 Foundation M&A document in entry 9).

24. `official/base_genesis_2023-08-09.md`
- URL: https://base.org/blog/base-mainnet-is-live
- Companion URL: https://docs.base.org/getting-started
- Issuing date: 2023-08-09
- Purpose: Base mainnet genesis-block date, grounding `_CHAIN_LAUNCH_DATE["BASE"] = 2023-08-09` (not the 2025-12-04 Coinbase Technologies terms date in entry 11).

25. `official/mantle_genesis_2023-07-17.md`
- URL: https://mantle.network/blog/mantle-network-mainnet-alpha-is-live
- Companion URL: https://docs.mantle.xyz/
- Issuing date: 2023-07-17
- Purpose: Mantle mainnet genesis-block date, grounding `_CHAIN_LAUNCH_DATE["Mantle"] = 2023-07-17`.

26. `official/zksync_era_genesis_2023-03-24.md`
- URL: https://matterlabs.introduction/blog/zksync-era-mainnet-is-live
- Companion URL: https://docs.zksync.io/
- Issuing date: 2023-03-24
- Purpose: zkSync Era mainnet genesis-block date, grounding `_CHAIN_LAUNCH_DATE["zkSync ERA"] = 2023-03-24` (not the Matter Labs legal-entity terms in entry 3).

27. `official/polygon_pol_migration_2024-09-04.md`
- URL: https://polygon.technology/blog/polygon-migration-now-complete
- Companion URL (governance proposal): https://polygon.technology/governance/proposals/046
- Issuing date: 2024-09-04
- Purpose: Polygon MATIC->POL native-asset migration effective date, grounding `_CHAIN_ON_CHAIN_NATIVE_TICKER["Polygon"] = "POL"` (post-migration native ticker for FY2025+ CSV output; separate contract from the stale-for-CSV `_CHAIN_NATIVE_FEE_ASSET["Polygon"] = "MATIC"` Koinly fee-check map).

## Public-record extracts

1. `public/mantle_public_record_2024-03-15.md`
- URL: https://www.ipd.gov.hk/hkipjournal/15032024/PUBLICATION_TYPE_TRADE_MARK_REGISTERED.pdf
- Issuing date: 2024-03-15
- Purpose: public-record support for `Mantle Foundation S.A.` in the British Virgin Islands.

## Canonical registry

- `operator_chain_origin_registry.md`
  - Purpose: repository-facing summary of current chain/operator origin mappings and local overrides.

## Source-priority rule (B3)

For Berachain operator-origin resolution, **primary sources win over secondary sources.**

- **Primary sources** are official chain documents (governing-law clauses in the chain's Terms of Service, foundation legal-form filings, official documentation). For Berachain, the primary source is the Berachain Foundation governing-law extract (`official/berachain_terms_2025-02-05.md`): Berachain Foundation Ltd. is domiciled in the British Virgin Islands (BVI). This is the chain-level mapping `Berachain -> VG` applied in `operator_origin.py:305`.
- **Secondary sources** are data aggregators (exchange MiCA whitepapers, data-provider profiles, third-party analyses). They do NOT override a primary source. A secondary source claiming a different operator domicile for a Berachain contract does not qualify.

**Consequence for the contract registry (`resources/source/<year>/berachain_contracts.json`):** the registry ships EMPTY `operator_country` for every contract. No primary source attributes a specific Berachain DEX / reward-distributor contract to a single operator country distinct from the chain-level domicile; the only primary source (the Berachain ToS) is chain-level. Secondary sources (e.g. a Bitstamp MiCA whitepaper citing Cayman for a Kodiak entity) were evaluated and **dropped** because they are secondary and do not override the chain-level BVI mapping. All Berachain rewards therefore fall through to the chain-level `VG` (British Virgin Islands).

A per-contract `operator_country` override may be added to the registry ONLY when a PRIMARY source stronger than the chain-level mapping attributes the contract's operator to a specific country. The registry loader (`application/on_chain_config.build_contract_registry`, Attacker F1 mitigation) requires both a valid ISO-3166 alpha-2 code AND a `citation` URL pointing at that primary source; an uncited or secondary-only override fails closed. The post-run `operator_country_enum` integrity invariant (Plan `2026-08-02-on-chain-tx-tagger` Task 13) is the audit echo.

Design record: `docs/architecture/on-chain-tx-design.md` (blocker B3 resolution). Plan: `docs/history/plans/2026-08-02-on-chain-tx-tagger.md` (Task 9 ships the empty-`operator_country` registry; Task 13 documents the rule here).

