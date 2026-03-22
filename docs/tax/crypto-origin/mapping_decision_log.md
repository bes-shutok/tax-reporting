# Crypto Mapping Decision Log

Reasoning record for chain/operator origin mappings used by this repository.

## Terminology

- Decision ID: numbered mapping rationale entry in this log.
- Source basis: the archived source set that supports the mapping.
- Repository override: a user-directed local filing choice that intentionally differs from the broadest upstream footprint.

## Decisions

### CMD-001: Berachain -> British Virgin Islands

- Mapping: `Berachain -> British Virgin Islands`
- Source basis:
  - [berachain_terms_2025-02-05.md](/Users/andrey/Projects/myrepos/shares/docs/tax/crypto-origin/official/berachain_terms_2025-02-05.md)
- Reasoning:
  - The official Berachain terms identify `BERA Chain Foundation`.
  - The same official terms use British Virgin Islands governing law.
  - This is strong enough to use BVI as the filing-facing origin anchor for Berachain rows.

### CMD-002: Starknet -> Cayman Islands

- Mapping: `Starknet -> Cayman Islands`
- Source basis:
  - [starknet_foundation_privacy_undated.md](/Users/andrey/Projects/myrepos/shares/docs/tax/crypto-origin/official/starknet_foundation_privacy_undated.md)
- Reasoning:
  - The archived Starknet Foundation material is official, but it does not cleanly state domicile in one direct sentence.
  - It does show Cayman legal/privacy handling in the foundation materials.
  - Because of that, the repository treats this as an inference from official material rather than a fully explicit domicile statement.

### CMD-003: zkSync ERA -> Cayman Islands

- Mapping: `zkSync ERA -> Cayman Islands`
- Source basis:
  - [zksync_terms_undated.md](/Users/andrey/Projects/myrepos/shares/docs/tax/crypto-origin/official/zksync_terms_undated.md)
- Reasoning:
  - The official zkSync terms identify `Matter Labs` as a Cayman Islands company.
  - This is a direct legal-entity anchor and supports a straightforward Cayman mapping.

### CMD-004: Solana -> Switzerland

- Mapping: `Solana -> Switzerland`
- Source basis:
  - [solana_foundation_site_undated.md](/Users/andrey/Projects/myrepos/shares/docs/tax/crypto-origin/official/solana_foundation_site_undated.md)
- Reasoning:
  - The official Solana site describes Solana Foundation as based in Zug, Switzerland.
  - That provides a direct official location anchor.

### CMD-005: TON -> Switzerland

- Mapping: `TON -> Switzerland`
- Source basis:
  - [ton_foundation_site_undated.md](/Users/andrey/Projects/myrepos/shares/docs/tax/crypto-origin/official/ton_foundation_site_undated.md)
- Reasoning:
  - TON Foundation states on its official site that it was founded in Switzerland as a non-profit.
  - That is a direct official foundation anchor for filing-facing mapping.

### CMD-006: Ethereum -> Switzerland

- Mapping: `Ethereum -> Switzerland`
- Source basis:
  - [ethereum_foundation_2024-05-08.md](/Users/andrey/Projects/myrepos/shares/docs/tax/crypto-origin/official/ethereum_foundation_2024-05-08.md)
- Reasoning:
  - Official Ethereum Foundation material describes it as a Swiss `Stiftung`.
  - That gives a direct Swiss legal-form anchor.

### CMD-007: Aptos -> Cayman Islands

- Mapping: `Aptos -> Cayman Islands`
- Source basis:
  - [aptos_terms_2025-08-29.md](/Users/andrey/Projects/myrepos/shares/docs/tax/crypto-origin/official/aptos_terms_2025-08-29.md)
- Reasoning:
  - The official Aptos terms list an Aptos Foundation address in George Town, Grand Cayman.
  - That is a direct official domicile anchor.

### CMD-008: Sui -> Cayman Islands

- Mapping: `Sui -> Cayman Islands`
- Source basis:
  - [sui_terms_undated.md](/Users/andrey/Projects/myrepos/shares/docs/tax/crypto-origin/official/sui_terms_undated.md)
- Reasoning:
  - The repository already uses Sui Foundation materials as the legal anchor for Sui.
  - Those collected materials tie Sui Foundation to the Cayman Islands.

### CMD-009: Arbitrum -> Cayman Islands

- Mapping: `Arbitrum -> Cayman Islands`
- Source basis:
  - [arbitrum_foundation_ma_2023-07-20.md](/Users/andrey/Projects/myrepos/shares/docs/tax/crypto-origin/official/arbitrum_foundation_ma_2023-07-20.md)
- Reasoning:
  - The official Arbitrum Foundation M&A PDF lists a Grand Cayman registered office.
  - It is constituted under Cayman foundation-company law.
  - This is a direct official domicile anchor.

### CMD-010: Mantle -> British Virgin Islands

- Mapping: `Mantle -> British Virgin Islands`
- Source basis:
  - [mantle_public_record_2024-03-15.md](/Users/andrey/Projects/myrepos/shares/docs/tax/crypto-origin/public/mantle_public_record_2024-03-15.md)
- Reasoning:
  - Mantle’s own terms are helpful for the legal interface but emphasize Singapore governing law rather than clearly stating domicile.
  - The public record links `Mantle Foundation S.A.` to the British Virgin Islands.
  - The repository therefore uses BVI, but keeps the provenance visible as public-record-supported rather than purely official-site-explicit.

### CMD-011: Polygon -> Cayman Islands

- Mapping: `Polygon -> Cayman Islands`
- Source basis:
  - [polygon_terms_2024-01-23.md](/Users/andrey/Projects/myrepos/shares/docs/tax/crypto-origin/official/polygon_terms_2024-01-23.md)
- Reasoning:
  - Polygon’s legal terms identify `Polygon Labs UI (Cayman) Ltd.`.
  - That is a direct official legal-entity anchor.

### CMD-012: BASE -> United States

- Mapping: `BASE -> United States`
- Source basis:
  - [base_terms_2025-12-04.md](/Users/andrey/Projects/myrepos/shares/docs/tax/crypto-origin/official/base_terms_2025-12-04.md)
- Reasoning:
  - The official Base terms identify `Coinbase Technologies, Inc.` as the contracting party for Base services.
  - This does not mean the chain as a protocol has one sovereign domicile in every sense.
  - It does give a defensible legal-interface anchor for filing-facing repository mapping, so the repository uses the United States.

### CMD-013: Filecoin -> United States

- Mapping: `Filecoin -> United States`
- Source basis:
  - [filecoin_foundation_job_board_privacy_2024-04.md](/Users/andrey/Projects/myrepos/shares/docs/tax/crypto-origin/official/filecoin_foundation_job_board_privacy_2024-04.md)
- Reasoning:
  - The official Filecoin Foundation page lists a Middletown, Delaware registered address.
  - That provides a direct official U.S. anchor for current repository mapping.

### CMD-014: Tonkeeper -> United Kingdom

- Mapping: `Tonkeeper -> United Kingdom`
- Source basis:
  - [tonkeeper_terms_2025-02-12.md](/Users/andrey/Projects/myrepos/shares/docs/tax/crypto-origin/official/tonkeeper_terms_2025-02-12.md)
- Reasoning:
  - The official Tonkeeper terms identify `Ton Apps UK Ltd.` in England and Wales.
  - This is a direct operator-level legal anchor and should take precedence over the broader `TON` chain mapping when the wallet is specifically Tonkeeper.

### CMD-015: Kraken -> Ireland

- Mapping: `Kraken -> Ireland`
- Source basis:
  - [kraken_eea_licensing_undated.md](/Users/andrey/Projects/myrepos/shares/docs/tax/crypto-origin/official/kraken_eea_licensing_undated.md)
- Reasoning:
  - The official Kraken licensing page names Irish entities for EEA-facing activity.
  - Because the user is filing from Europe, Ireland is the most defensible filing-facing mapping.

### CMD-016: Gate.io -> Malta

- Mapping: `Gate.io -> Malta`
- Source basis:
  - [gate_eu_about_undated.md](/Users/andrey/Projects/myrepos/shares/docs/tax/crypto-origin/official/gate_eu_about_undated.md)
- Reasoning:
  - Gate’s Europe-facing official page ties the service to Malta incorporation/regulation.
  - For Europe-facing filing output, Malta is the strongest current mapping.

### CMD-017: Binance / Binance Smart Chain -> Spain

- Mapping: `Binance -> Spain`
- Mapping: `Binance Smart Chain -> Spain`
- Source basis:
  - [bnb_chain_terms_2026-01.md](/Users/andrey/Projects/myrepos/shares/docs/tax/crypto-origin/official/bnb_chain_terms_2026-01.md)
- Reasoning:
  - The upstream BNB Chain material points to ADGM / UAE, and Binance globally spans multiple jurisdictions.
  - The user explicitly asked that `Multiple jurisdictions` not appear in the export and that the Europe-relevant choice be hardcoded.
  - The repository therefore records `Spain` as a Europe-facing repository override for filing output.
  - This is intentionally documented as a local override, not as a claim that upstream Binance or BNB Chain is globally domiciled in Spain.
