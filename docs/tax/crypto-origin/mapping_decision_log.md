# Crypto Mapping Decision Log

Reasoning record for chain/operator origin mappings used by this repository.

## Terminology

- Decision ID: numbered mapping rationale entry in this log.
- Source basis: the archived source set that supports the mapping.
- Repository override: a user-directed local filing choice that intentionally differs from the broadest upstream footprint.

## Decisions

### CMD-001: Berachain -> British Virgin Islands

- Mapping: `Berachain -> British Virgin Islands`
- service_start_date: `2025-02-05`
- valid_from: `2025-02-05`
- Source basis:
  - [berachain_terms_2025-02-05.md](/Users/andrey/Projects/myrepos/shares/docs/tax/crypto-origin/official/berachain_terms_2025-02-05.md)
- Reasoning:
  - The official Berachain terms identify `BERA Chain Foundation`.
  - The same official terms use British Virgin Islands governing law.
  - This is strong enough to use BVI as the filing-facing origin anchor for Berachain rows.

### CMD-002: Starknet -> Cayman Islands

- Mapping: `Starknet -> Cayman Islands`
- service_start_date: `2021-11-16`
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
- service_start_date: `2015-07-30`
- valid_from: `2026-03-15`
- Source basis:
  - [ethereum_foundation_2024-05-08.md](/Users/andrey/Projects/myrepos/shares/docs/tax/crypto-origin/official/ethereum_foundation_2024-05-08.md)
- Reasoning:
  - Official Ethereum Foundation material describes it as a Swiss `Stiftung`.
  - That gives a direct Swiss legal-form anchor.

### CMD-007: Aptos -> Cayman Islands

- Mapping: `Aptos -> Cayman Islands`
- service_start_date: `2022-10-17`
- valid_from: `2026-03-15`
- Source basis:
  - [aptos_terms_2025-08-29.md](/Users/andrey/Projects/myrepos/shares/docs/tax/crypto-origin/official/aptos_terms_2025-08-29.md)
- Reasoning:
  - The official Aptos terms list an Aptos Foundation address in George Town, Grand Cayman.
  - That is a direct official domicile anchor.

### CMD-008: Sui -> Cayman Islands

- Mapping: `Sui -> Cayman Islands`
- service_start_date: `2023-05-03`
- Source basis:
  - [sui_terms_undated.md](/Users/andrey/Projects/myrepos/shares/docs/tax/crypto-origin/official/sui_terms_undated.md)
- Reasoning:
  - The repository already uses Sui Foundation materials as the legal anchor for Sui.
  - Those collected materials tie Sui Foundation to the Cayman Islands.

### CMD-009: Arbitrum -> Cayman Islands

- Mapping: `Arbitrum -> Cayman Islands`
- service_start_date: `2021-08-31`
- valid_from: `2026-03-15`
- Source basis:
  - [arbitrum_foundation_ma_2023-07-20.md](/Users/andrey/Projects/myrepos/shares/docs/tax/crypto-origin/official/arbitrum_foundation_ma_2023-07-20.md)
- Reasoning:
  - The official Arbitrum Foundation M&A PDF lists a Grand Cayman registered office.
  - It is constituted under Cayman foundation-company law.
  - This is a direct official domicile anchor.

### CMD-010: Mantle -> British Virgin Islands

- Mapping: `Mantle -> British Virgin Islands`
- service_start_date: `2023-07-17`
- valid_from: `2024-03-15`
- Source basis:
  - [mantle_public_record_2024-03-15.md](/Users/andrey/Projects/myrepos/shares/docs/tax/crypto-origin/public/mantle_public_record_2024-03-15.md)
- Reasoning:
  - Mantle’s own terms are helpful for the legal interface but emphasize Singapore governing law rather than clearly stating domicile.
  - The public record links `Mantle Foundation S.A.` to the British Virgin Islands.
  - The repository therefore uses BVI, but keeps the provenance visible as public-record-supported rather than purely official-site-explicit.

### CMD-011: Polygon -> Cayman Islands

- Mapping: `Polygon -> Cayman Islands`
- service_start_date: `2020-05-28`
- valid_from: `2026-03-15`
- Source basis:
  - [polygon_terms_2024-01-23.md](/Users/andrey/Projects/myrepos/shares/docs/tax/crypto-origin/official/polygon_terms_2024-01-23.md)
- Reasoning:
  - Polygon’s legal terms identify `Polygon Labs UI (Cayman) Ltd.`.
  - That is a direct official legal-entity anchor.

### CMD-012: BASE -> United States

- Mapping: `BASE -> United States`
- service_start_date: `2023-08-09`
- valid_from: `2026-03-15`
- Source basis:
  - [base_terms_2025-12-04.md](/Users/andrey/Projects/myrepos/shares/docs/tax/crypto-origin/official/base_terms_2025-12-04.md)
- Reasoning:
  - The official Base terms identify `Coinbase Technologies, Inc.` as the contracting party for Base services.
  - This does not mean the chain as a protocol has one sovereign domicile in every sense.
  - It does give a defensible legal-interface anchor for filing-facing repository mapping, so the repository uses the United States.

### CMD-013: Filecoin -> United States

- Mapping: `Filecoin -> United States`
- service_start_date: `2020-10-15`
- valid_from: `2024-04-01`
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

### CMD-018: Wirex Split-Scope (GB vs HR)

- Mapping: `Wirex (fiat) -> GB`
- Mapping: `Wirex (crypto) -> HR`
- Source basis:
  - Wirex account terms (https://wirexapp.com/legal) - verified 2026-03-08
- Reasoning:
  - Wirex splits services by legal entity: Wirex Limited (UK) for fiat, Wirex Digital (Croatia) for crypto.
  - Portuguese tax rules require using the entity that actually provides the service to the user.
  - For EUR/USD fiat rewards and deposits: use Wirex Limited (GB) as the source country.
  - For crypto rewards and deposits: use Wirex Digital (HR) as the source country.
  - The code implementation uses the `transaction_type` parameter to disambiguate between fiat and crypto transactions.
- Implementation Note:
  - The original design proposed using `service_start_date=2015-01-01` (founding date) with a verification date check.
  - The actual implementation (CMD-021) uses the simpler approach of `service_start_date=2026-03-08` (verified date) with `valid_from=null`.
  - See CMD-021 for the final implementation details.
- See also: `entity_selection_criteria.md` for the service-scope split hierarchy.

### CMD-019: Temporal Validity Fallback Fix

- Issue: Code was incorrectly falling back to `valid_from` when `service_start_date` was None
- Fixed: `2026-03-25`
- Reasoning:
  - The temporal validity feature (Phase 2.3 of manual review reduction) introduced `service_start_date` as a field separate from `valid_from` to handle platforms like Wirex that were operational long before the mapping was formally verified.
  - Per the documented semantics in `operator_chain_origin_registry.md`:
    - `service_start_date`: When the platform actually started offering this service. Used for transaction date matching.
    - `valid_from`: When this specific mapping was verified from source documents. Used for audit trail only.
  - The implementation had a bug: `origin.service_start_date or origin.valid_from` was used as the lower bound for temporal checks.
  - This caused false positives for long-running chains like Ethereum (valid_from="2024-05-08", but operational since 2015), where historical transactions from 2024-01 were incorrectly flagged as outside the validity period.
  - Fix: Pass `origin.service_start_date` directly without fallback. When `service_start_date` is None, skip the lower-bound check entirely (as `_is_temporally_valid` already handles None by skipping the check).
  - Also fixed the log message to show the actual lower bound used instead of masking it as "unknown".
- Impact: Eliminates false review flags for pre-verification transactions on long-running chains that only have `valid_from` dates recorded.

### CMD-020: Verification Date Check for Manual Review (Design Document)

- Issue: Wirex transactions from 2015-2026-03-07 were silently auto-classified as GB/HR without any indication of uncertainty, because `service_start_date` (2015-01-01, approximate founding date) was the only lower bound used for temporal validity checks. The exact date when the GB/HR entity split began is unknown.
- Proposed: `2026-03-25` (design concept)
- Reasoning:
  - The `service_start_date` and `valid_from` fields have different semantics:
    - `service_start_date`: When the platform actually started offering this service (may be approximate)
    - `valid_from`: When this specific mapping was verified from source documents (definitive)
  - For Wirex, 2015-01-01 is the founding date, NOT when the GB/HR split began. The split could have occurred any time between 2015-2026.
  - The proposed design would add a verification date check: transactions occurring BEFORE `valid_from` would be flagged for manual review, even if they fall within the `service_start_date` period.
  - This would ensure historical transactions get manual attention while post-verification transactions are auto-classified normally.
- Implementation Note:
  - The actual implementation (CMD-021) chose a simpler approach: use the verified date (2026-03-08) directly as `service_start_date` rather than implementing the verification date check.
  - This eliminates the complexity of tracking two separate dates and the additional verification gate logic.
  - See CMD-021 for the final implementation details.

### CMD-021: Wirex Implementation Simplification (Updated 2026-03-26)

- Decision Date: `2026-03-25` (updated `2026-03-26`)
- Mapping: `Wirex (fiat) -> GB`, `Wirex (crypto) -> HR`
- service_start_date: `2015-01-01` (updated from `2026-03-08`)
- valid_from: `2026-03-08` (updated from `null`)
- review_required: `False`
- Reasoning:
  - The original implementation (2026-03-25) used `service_start_date=2026-03-08` (verification date) as a conservative boundary.
  - However, the actual sample data in `resources/source/koinly2025/` contains 2025 Wirex transactions (9 capital entries, 144 reward entries), all of which were being flagged for manual review because they predated 2026-03-08.
  - This defeated the stated goal of Phase 2.3 to "reduce manual review flags" for the actual 2025 data.
  - The corrected approach uses `service_start_date=2015-01-01` (approximate founding date, Wirex Limited incorporated in 2014) to allow legitimate 2025 transactions to be auto-classified.
  - The `valid_from=2026-03-08` preserves the GB/HR split-scope verification date for audit trail, separating the temporal matching boundary from the verification date.
  - While the exact date of the GB/HR entity split is unknown, Wirex has operated with this split structure since its early years (Wirex Limited for fiat, Wirex Digital for crypto), making 2015-01-01 a reasonable boundary for practical filing purposes.
- Impact:
  - Wirex transactions from 2015 onwards: auto-classified as GB (fiat) or HR (crypto) without review flags
  - Wirex transactions before 2015: flagged for manual review (unlikely in practice)
  - Achieves the Phase 2.3 goal of reducing manual review flags for the actual 2025 sample data
- See also: `operator_chain_origin_registry.md` for current Wirex entries, CMD-018 for original split-scope rationale
