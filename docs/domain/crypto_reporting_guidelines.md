# Crypto Reporting Guidelines

Implementation guidelines for the `Crypto` worksheet and related Koinly ingestion behavior.

## Terminology

- `CRG-xxx`: numbered crypto-reporting guideline for this repository.
- Official rule: behavior driven directly by archived tax/operator source material.
- Repository override: an explicit local policy used when the user wants a filing-facing simplification that is narrower than the upstream platform's global footprint.

## Official Source Set

- `docs/tax/laws/pt/crypto-tax/official/cirs_2025-07_code_consolidated.pdf`
- `docs/tax/laws/pt/crypto-tax/official/at_folheto_criptoativos_2026-01-12.pdf`
- `docs/tax/laws/pt/crypto-tax/official/at_piv_22065_2023-11-06.pdf`
- `docs/tax/laws/pt/crypto-tax/official/at_piv_21506_undated.pdf`
- `docs/tax/laws/pt/crypto-tax/official/modelo3_anexo_e_2025.pdf`
- `docs/tax/laws/pt/crypto-tax/official/modelo3_anexo_j_2025.pdf`
- `docs/tax/laws/pt/crypto-tax/official/at_oficio_circulado_20269_2024.pdf`
- `docs/tax/laws/pt/crypto-tax/official/at_oficio_circulado_20278_2025.pdf`

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

## Platform Assumptions vs Row-Level Review Flags

**CRG-016**
Distinguish between platform-level review concerns and row-level review flags:

- **Platform-level concerns** (e.g., "Bybit uses account-region specific entities; verify your account region"): These apply to ALL transactions from a platform. Display them in the "Platform Assumptions" worksheet — a complete manifest of every platform in the report. Platform concerns must NOT set `review_required=True` on individual transaction rows.

- **Row-level review flags** (e.g., missing cost basis, date parsing errors, phantom transfers, FIFO pool exhaustion): These are specific to individual transactions and must be shown on the row with "YES: <reason>", with the row highlighted red.

**`OperatorOrigin` fields:**
- `platform_assumption` — free-text note shown in the Platform Assumptions tab (informational; does not trigger red rows)
- `platform_review_required: bool` — whether this platform must be manually verified before filing; controls red highlighting and "YES"/"NO" in the Platform Assumptions tab; does NOT affect individual transaction rows
- `review_required: bool` / `review_reason: str` — row-level flag; triggers "YES: <reason>" on the transaction row and red row fill; set only for per-transaction issues (temporal validity failures, unknown platforms, FIFO anomalies)

**Platform Assumptions tab** shows ALL platforms seen in the data (not just those with assumption text), columns: Platform | Operator Entity | Country | Confidence | Review Required | Assumption Note | Transaction Count. Rows with `platform_review_required=True` are sorted first and highlighted red.

**Test fixture rule:** Tests that verify row-level "YES:"/"NO" rendering must use explicit hardcoded `review_required` / `review_reason` values on the entry, not delegate to `origin.review_required`. The latter changes when the platform mapping changes and will silently break the rendering test.

## Token Origin Resolution

**CRG-015**
Token origin is derived from implicit `(date, asset, wallet)` correlation between the Koinly capital gains report and the Koinly transaction history. The capital gains CSV provides no transaction ID, lot ID, or hash that directly links to the transaction history, so all matching is best-effort correlation — not a direct foreign-key link.

Origin resolution uses the `TokenOriginResolver` class:

- **Inputs**: Koinly transaction history CSV (parsed at construction time to build a lookup indexed by `(date, asset, wallet)`).
- **Matching**: For each capital gains row, the resolver looks up acquisition events matching `(Date Acquired, Asset, normalized wallet)` from the transaction history.
- **Acquisition methods**: `direct_purchase`, `swap_conversion`, `bridge_transfer`, `defi_yield`, `reward`, `transfer`, `unknown`.
- **Confidence levels**:
  - `high` — the transaction history row has a `TxHash` or other explicit on-chain identifier.
  - `medium` — matched via implicit date/asset/wallet correlation only.
  - `low` — ambiguous match (multiple conflicting records for the same key), capital gains row has `Missing cost basis`, or no match found.
- **Fallback**: When no matching transaction history row exists (CEX internal fills, history gaps, pre-Koinly acquisition dates, or epoch date `1970-01-01`), the resolver returns `unknown` with `low` confidence. It never guesses.
- **Output format**: The `Token origin` column shows `"FROM_ASSET (method, confidence confidence)"` for resolved rows, or blank for unknown.
- **Disclaimer**: Origin values are best-effort correlation from Koinly export data and should be reviewed against source documents before filing.
