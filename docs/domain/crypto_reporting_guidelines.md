# Crypto Reporting Guidelines

Implementation guidelines for the `Crypto` worksheet and related Koinly ingestion behavior.

## Terminology

- `CRG-xxx`: numbered crypto-reporting guideline for this repository.
- Official rule: behavior driven directly by archived tax/operator source material.
- Repository override: an explicit local policy used when the user wants a filing-facing simplification that is narrower than the upstream platform's global footprint.

## Official Source Set

- `docs/tax/portugal-crypto-tax/official/cirs_2025-07_code_consolidated.pdf`
- `docs/tax/portugal-crypto-tax/official/at_folheto_criptoativos_2026-01-12.pdf`
- `docs/tax/portugal-crypto-tax/official/at_piv_22065_2023-11-06.pdf`
- `docs/tax/portugal-crypto-tax/official/at_piv_21506_undated.pdf`
- `docs/tax/portugal-crypto-tax/official/modelo3_anexo_e_2025.pdf`
- `docs/tax/portugal-crypto-tax/official/modelo3_anexo_j_2025.pdf`
- `docs/tax/portugal-crypto-tax/official/at_oficio_circulado_20269_2024.pdf`
- `docs/tax/portugal-crypto-tax/official/at_oficio_circulado_20278_2025.pdf`

## Official Findings

**CRG-001**
For non-business taxpayers, crypto-related remuneration received in the form of cryptoassets is not taxed at receipt. It moves to later taxation on disposal of the received cryptoasset.

**CRG-002**
Immediate category E reporting applies only when the remuneration does not itself assume the form of cryptoassets.

**CRG-003**
Under the current official design, a crypto-denominated reward can ultimately produce no Portuguese tax if the later disposal falls within the long-holding exclusion and no anti-exception rule disqualifies it. Do not force immediate taxation merely because that outcome feels conservative.

**CRG-004**
The same `País da Fonte` resolution rule must be used across crypto rewards and crypto capital gains.

## Filing Guidance

**CRG-005**
Never use taxpayer residence as the crypto `País da Fonte` merely because the activity happened while the taxpayer was in Portugal.

**CRG-006**
Use this source-country fallback order for DeFi rows:
- interface legal entity
- protocol / foundation / sponsoring legal entity
- validator operator for identifiable native staking

**For DEX (Decentralized Exchange) transactions specifically:**

The country determination follows the same hierarchy, with these clarifications:

1. **Interface legal entity**: If the DEX has a frontend UI with terms of service (e.g., Uniswap app interface), use that entity.
2. **Protocol / foundation**: For pure protocol interactions, use the chain's foundation entity (e.g., Ethereum Foundation → Switzerland for Uniswap on Ethereum).
3. **No separate DEX mapping required**: A DEX like Uniswap running on Ethereum uses the Ethereum chain mapping (Switzerland via Ethereum Foundation), unless the DEX has its own explicit legal entity.

**Examples:**
- Uniswap on Ethereum → Switzerland (via Ethereum Foundation)
- PancakeSwap on BNB Chain → Spain (via BNB repository override for EEA filing)
- Pure protocol interaction → Use chain origin from `operator_chain_origin_registry.md`

**CRG-007**
The final Crypto sheet must be IRS-ready: filing-facing rows must not be missing mandatory IRS fields, and broad placeholders such as `Multiple jurisdictions` must not appear when a repository mapping policy exists.

## Data Normalization Guidance

**CRG-008**
`ByBit` and `ByBit (2)` are the same logical account in this repository and must be normalized before aggregation, country resolution, and workbook rendering.

**CRG-009**
`chain` is a normalized reporting field distinct from the raw wallet name. Keep the raw wallet label, but derive the candidate chain from that label and resolve the final chain against trusted archived sources under `docs/tax/crypto-origin/`.

**CRG-010**
When a wallet / platform label is not sufficient to determine a defensible chain, use `Unknown` explicitly rather than guessing from the asset symbol alone.

**CRG-011**
When adding or changing a crypto chain/operator mapping, keep the source archive, effective registry, and mapping decision log synchronized under `docs/tax/crypto-origin/`.

## Current Mapping Guidance

**CRG-012**
EEA-facing CeFi defaults currently used by this repository are:
- `Kraken -> Ireland`
- `Gate.io -> Malta`

**CRG-013**
`Binance` / `Binance Smart Chain` must not render as `Multiple jurisdictions` in the workbook. The current repository override for Europe-facing output is `Spain`, and this should remain documented as a local filing policy rather than a chain-governance fact.

**CRG-014**
Chain-origin mappings collected so far include:
- `Berachain -> British Virgin Islands`
- `Starknet -> Cayman Islands` (inferred from official foundation materials; keep provenance visible)
- `zkSync ERA -> Cayman Islands`
- `Solana -> Switzerland`
- `TON -> Switzerland`
- `Ethereum -> Switzerland`
- `Aptos -> Cayman Islands`
