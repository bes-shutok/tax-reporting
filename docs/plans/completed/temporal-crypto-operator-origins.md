# Plan: Temporal Crypto Operator Origin Resolution

## Problem Statement

The current crypto operator origin resolution has several limitations:

1. **No temporal tracking**: Operator mappings are static. If an operator changes legal domicile (e.g., Wirex moves crypto operations to a new entity), we cannot represent this historically.
2. **Entity selection criteria undocumented**: When a platform has multiple entities (head company, subsidiaries, regional operating companies), which one should be used for Portuguese tax reporting?
3. **Wirex split-scope not documented**: The code handles Wirex as split-scope (Wirex Limited GB for fiat, Wirex Digital HR for crypto), but this is not documented in the registry/decision log.
4. **No audit trail for past filings**: When reviewing past tax returns, we cannot determine which origin mapping was in effect at the time of filing.

## Example: Wirex Entity Changes

Wirex provides a concrete example of why temporal tracking matters:
- **Historically**: Crypto operations may have been under one entity
- **Current**: Wirex Limited (UK, fiat) vs Wirex Digital (Croatia, crypto) - split by service scope
- **Future**: Could change again with restructuring

When filing for tax year 2025 vs 2026, different entities may apply depending on when the change occurred.

## Background

### Current State

**Registry Structure** (`operator_chain_origin_registry.md`):
- Maps operator/chain to country
- Has `authority` field (official, inferred, repository override)
- Has `basis` field explaining WHY
- No date/time ranges

**Decision Log** (`mapping_decision_log.md`):
- CMD-001 through CMD-017 with detailed reasoning
- Links to archived source documents
- No temporal validity

**Code Implementation** (`crypto_reporting.py`):
- `resolve_operator_origin(platform, transaction_type)` returns `OperatorOrigin`
- Static mapping via if/else chains
- Wirex has special handling via `transaction_type` parameter
- No date-based lookup

### Portuguese Tax Context

Per Portuguese tax rules:
- **Source country**: Fiscal residence of the paying entity/platform/counterparty, NOT taxpayer residence
- **Entity selection**: For groups with multiple entities, use the entity that:
  1. Actually provides the service to the user (interface entity)
  2. Has Portuguese nexus for EU/EEA operators (e.g., Irish entity for EEA users)
  3. Is the crypto-specific operating company for platforms that split fiat/crypto

## Proposed Solution

### Phase 1: Documentation Updates (Immediate)

**1.1 Add Temporal Validity to Registry**

Extend `operator_chain_origin_registry.md` with temporal fields:

```markdown
- `Tonkeeper`
  - country: `United Kingdom`
  - valid_from: `2025-02-12`  # Date of terms verification
  - authority: `official`
  - basis: Tonkeeper terms identify `Ton Apps UK Ltd.` in England and Wales.
  - note: Koinly exports may contain typo "Tonkeper wallet" - code handles both.
```

**1.2 Document Entity Selection Criteria**

Add to `docs/tax/crypto-origin/entity_selection_criteria.md`:

```markdown
# Entity Selection Criteria for Portuguese Tax Reporting

## Hierarchy

For platforms with multiple legal entities, select the entity based on:

1. **Interface Entity Priority**: The entity that contracts directly with the user
2. **Service-Scope Split**: For platforms that separate fiat/crypto by legal entity
   - Use the crypto-specific entity for crypto transactions
   - Use the fiat entity for fiat transactions
3. **EU/EEA Nexus**: For EEA-facing users, prefer the EEA-licensed entity when available
4. **Default**: Foundation/Protocol entity when no interface entity exists

## Wirex Example

- **Fiat deposits**: Wirex Limited (GB) - UK entity for fiat services
- **Crypto deposits**: Wirex Digital (HR) - Croatian crypto operator
- **Basis**: Service scope split documented in Wirex account terms
```

**1.3 Document Wirex Split-Scope**

Add to `mapping_decision_log.md`:

```markdown
### CMD-018: Wirex Split-Scope (GB vs HR)

- Mapping: `Wirex (fiat) -> GB`, `Wirex (crypto) -> HR`
- valid_from: `2026-03-08`
- Source basis:
  - Wirex account terms (https://wirexapp.com/legal)
- Reasoning:
  - Wirex splits services by legal entity: Wirex Limited (UK) for fiat, Wirex Digital (Croatia) for crypto
  - Portuguese rules require using the entity that actually provides the service
  - For EUR/USD fiat rewards -> Wirex Limited (GB)
  - For crypto rewards -> Wirex Digital (HR)
```

### Phase 2: Data Structure Changes (Deferred)

**2.1 Add Temporal Fields to OperatorOrigin**

```python
@dataclass
class OperatorOrigin:
    platform: str
    service_scope: str
    operator_entity: str
    operator_country: str
    source_url: str
    source_checked_on: str  # Already exists, keep
    confidence: str
    review_required: bool
    # NEW FIELDS:
    valid_from: str | None = None  # ISO date when this mapping became valid
    valid_until: str | None = None  # ISO date when this mapping expired
```

**2.2 Registry Data Format**

Change from flat list to list of mappings with date ranges:

```markdown
## Mappings

### Wirex

| Entity | Country | Service Scope | Valid From | Valid Until | Basis |
|--------|---------|---------------|------------|------------|-------|
| Wirex Limited | GB | fiat | 2016-01-01 | present | Original UK entity |
| Wirex Digital | HR | crypto | 2023-06-01 | present | Crypto operator since 2023 |

### Tonkeeper

| Entity | Country | Service Scope | Valid From | Valid Until | Basis |
|--------|---------|---------------|------------|------------|-------|
| Ton Apps UK Ltd. | GB | crypto | 2025-02-12 | present | Terms verification date |
```

### Phase 3: Date-Aware Resolution (Optional/Deferred)

**3.1 Add Date Parameter**

```python
def resolve_operator_origin(
    platform: str,
    transaction_type: str | None = None,
    transaction_date: TradeDate | None = None,  # NEW
) -> OperatorOrigin:
    """Resolve operator metadata, with optional date-based lookup.

    Args:
        platform: Wallet or platform name
        transaction_type: Optional hint for service scope
        transaction_date: If provided, use historical mapping in effect on this date
    """
```

**3.2 Lookup Logic**

If `transaction_date` is provided:
- Find all mappings for the platform
- Select the mapping where `valid_from <= transaction_date <= valid_until`
- If multiple mappings match (e.g., service scope split), use `transaction_type` to disambiguate

If `transaction_date` is None (current behavior):
- Use the mapping with the most recent `valid_from` (or no `valid_until`)

## Tasks

### Task 1: Documentation Updates

- [x] Add temporal fields to `operator_chain_origin_registry.md` (at least `valid_from`)
- [x] Create `entity_selection_criteria.md` with Portuguese tax rules
- [x] Add CMD-018 to `mapping_decision_log.md` for Wirex split-scope
- [x] Update all existing mappings with `valid_from` dates (use `source_checked_on` or source doc date)

### Task 2: Data Structure Changes (DEFERRED)

- [x] Add `valid_from` and `valid_until` fields to `OperatorOrigin` dataclass
- [x] Update all `OperatorOrigin` instantiations to include `valid_from`
- [x] Add tests for temporal lookups

### Task 3: Date-Aware Resolution (DEFERRED)

- [x] Add `transaction_date` parameter to `resolve_operator_origin()`
- [x] Implement date-based mapping selection logic
- [x] Add tests for historical transaction lookups
- [x] Update call sites in `_parse_capital_gains_file()` and `_parse_income_file()` to pass transaction date

## Open Questions

1. **Migration strategy**: For existing historical data (tax year 2024), should we re-run with new temporal mappings or keep existing output as-is?
2. **Backward compatibility**: If `transaction_date` is before the earliest `valid_from`, should we fail or use earliest mapping?
3. **Conflict resolution**: What if a user disputes a historical mapping after filing? Need a process for corrections.

## Dependencies

- None blocking for Phase 1 (documentation only)
- Phase 2 depends on Phase 1 completion
- Phase 3 depends on Phase 2 completion

## Acceptance Criteria

Phase 1 (documentation):
- [x] All mappings in registry have `valid_from` date
- [x] Wirex split-scope documented in registry and decision log
- [x] Entity selection criteria documented with Portuguese tax basis
- [x] All changes referenced from `crypto_implementation_guidelines.md`

Phase 2 (data structures, deferred):
- [x] `OperatorOrigin` has temporal fields
- [x] All instantiations include `valid_from`
- [x] Tests pass for new fields

Phase 3 (date-aware resolution, optional):
- [x] Can query historical mappings by transaction date
- [x] Tests cover date boundary cases
- [x] Backward compatible (works without transaction_date)
