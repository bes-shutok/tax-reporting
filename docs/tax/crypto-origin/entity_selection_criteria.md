# Entity Selection Criteria for Portuguese Tax Reporting

## Overview

When a crypto platform or chain has multiple legal entities (parent company, subsidiaries, regional operating companies), determining the correct entity for Portuguese tax reporting requires specific criteria. This document establishes the rules used by this repository for entity selection.

## Portuguese Tax Context

Per Portuguese tax rules for crypto income and capital gains:

- **Source country principle**: The fiscal residence of the paying entity/platform/counterparty determines the source country, NOT the taxpayer's residence.
- **Entity selection**: For groups with multiple entities, use the entity that actually provides the service to the user.

## Entity Selection Hierarchy

For platforms with multiple legal entities, select the entity based on the following priority order:

### 1. Interface Entity Priority (Highest)

The entity that contracts directly with the user through the terms of service takes precedence. This is typically the entity named in:
- User agreements / terms of service
- Privacy policies
- Account-specific disclosures

### 2. Service-Scope Split

For platforms that separate fiat/crypto by legal entity, use the service-specific entity:

- **Crypto transactions**: Use the crypto-specific operating company
- **Fiat transactions**: Use the fiat/banking entity
- **Basis**: Portuguese rules require using the entity that actually provides the service

### 3. EU/EEA Nexus

For EEA-facing users, when the platform has multiple regional entities:

- Prefer the EEA-licensed entity when available
- This reflects the entity that has regulatory nexus for the user's region

### 4. Default: Foundation/Protocol Entity

When no interface entity exists (e.g., pure protocol foundations):

- Use the foundation or protocol entity identified in official materials
- Document as foundation/protocol-level rather than service-interface-level

## Examples

### Wirex: Service-Scope Split

- **Fiat deposits/rewards**: Wirex Limited (GB) - UK entity for fiat services
- **Crypto deposits/rewards**: Wirex Digital (HR) - Croatian crypto operator
- **Basis**: Wirex account terms explicitly split services by legal entity
- **Implementation**: The code uses `transaction_type` parameter to disambiguate

### Binance: EU/EEA Nexus

- **Europe-facing users**: Spanish entity (repository override)
- **Basis**: User requested Europe-specific filing override to avoid "Multiple jurisdictions"
- **Note**: Documented as repository override, not global domicile claim

### TON: Foundation Entity

- **Selection**: TON Foundation (Switzerland)
- **Basis**: No interface entity for the protocol itself; foundation is the legal anchor

## Implementation Notes

- The `service_scope` field in `operator_chain_origin_registry.md` documents service-specific mappings
- The `resolve_operator_origin()` function accepts an optional `transaction_type` parameter for disambiguation
- When `transaction_type` is provided, code selects the matching service-scope entity

## References

- CMD-018: Wirex Split-Scope documentation
- `operator_chain_origin_registry.md`: Current mappings with service_scope annotations
- `docs/domain/crypto_rules.md`: Portuguese tax rules for source country determination
