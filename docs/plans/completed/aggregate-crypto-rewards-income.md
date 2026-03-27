# Plan: Aggregate Crypto Rewards Income

## Research Summary

- Official Portuguese guidance indicates that crypto-related remuneration is not always taxable at receipt. When the remuneration assumes the form of cryptoassets, article 5(11) of the CIRS and the AT brochure state that taxation is deferred until later disposal.
- The current official Anexo J form instructions require a `País da Fonte` code from `Tabela X` and a current crypto capital-income code from `Tabela V` for immediately taxable foreign-source rewards. The same instructions do not provide an official fallback for countryless DeFi income.
- Secondary Portuguese practitioner guidance indicates that the relevant source-country logic is the fiscal residence of the platform / counterparty / paying entity, not the taxpayer residence in Portugal.
- For IRS-ready crypto output, the source-country fallback hierarchy should be: interface legal entity -> protocol / foundation / sponsoring legal entity -> validator operator when identifiable. Do not auto-fill `Portugal` only because the taxpayer performed the activity from Portugal.
- The local 2025 Koinly `income_report` is overwhelmingly token-denominated. That means the biggest lawful line reduction will likely come from excluding deferred crypto-denominated rewards from the immediate-income filing set before aggregating the remaining taxable rows.
- `ByBit` and `ByBit (2)` are the same account in this repository context and must be normalized to one reporting wallet for both capital gains and rewards.
- The same source-country policy must be reused by both the rewards and capital-gains sections so the final Crypto tab is IRS-ready end to end.

## Validation Commands

- `uv run pytest tests/unit/application/test_crypto_reporting.py tests/integration/test_excel_generation_integration.py`
- `uv run shares-reporting`

### Task 1: Classify rewards before aggregation

- [x] Add a reward-tax classification step in `src/shares_reporting/application/crypto_reporting.py` that separates rows into `taxable_now` and `deferred_by_law`.
 - [x] Base the classification on official rules already collected in `docs/domain/crypto_reporting_guidelines.md` and `docs/domain/crypto_rules.md`.
- [x] Treat crypto-denominated rewards as deferred by default, unless the code can positively identify an official exception bucket that requires immediate taxation.
- [x] Add unit tests for at least: crypto-denominated reward, fiat-denominated reward, exception-bucket reward, and DeFi reward that remains deferred by law.

### Task 2: Add an IRS-ready aggregation model

- [x] Introduce an aggregated reward model keyed by the final IRS reporting dimensions actually needed for Anexo J filing.
- [x] Aggregate only the `taxable_now` rows, not the deferred rows.
- [x] Keep the minimum safe aggregation key as `income_code + source_country`, and extend it if implementation work shows another official form field must stay separate.
- [x] Sum gross income and foreign-tax amounts inside each aggregated key.
- [x] Preserve a raw-to-aggregated reconciliation trail so every aggregated row can still be traced back to the underlying Koinly rows.
- [x] Determine `source_country` from the paying entity / platform / protocol legal-entity country, never from the taxpayer residence country.
- [x] Fail generation with a clear error if an immediately taxable row cannot be assigned all mandatory IRS fields, including a valid `Tabela X` country code.

### Task 3: Share source-country logic across the entire Crypto tab

- [X] Extract one shared country-resolution rule that is used by both reward rows and capital-gain rows.
- [X] Implement the hierarchy `interface entity -> protocol / foundation -> validator` for DeFi source-country resolution and reject taxpayer-residence fallback.
- [X] Apply the same `ByBit` / `ByBit (2)` wallet normalization before both country resolution and aggregation logic.
- [X] Remove any final-output behavior that leaves country or mandatory IRS fields unresolved in either section.
- [X] Encode known defaults from collected sources for EEA-facing CeFi operators, including `Kraken -> Ireland` and `Gate.io -> Malta`.

### Task 4: Normalize wallet aliases before aggregation

- [X] Add a wallet-normalization rule so `ByBit` and `ByBit (2)` are treated as the same account in both capital gains and rewards flows.
- [X] Reuse the same normalized wallet value everywhere it affects FIFO boundaries, aggregation keys, and report labels.
- [X] Add tests proving capital and reward rows from `ByBit` and `ByBit (2)` collapse into the same logical account.

### Task 5: Add chain derivation to crypto parsing and workbook output

- [x] Implement the `chain` field in the workbook using `docs/tax/crypto-origin/` as the trusted source archive for the final mapping.
- [x] Add a `chain` field to both `CryptoCapitalGainEntry` and `CryptoRewardIncomeEntry`.
- [x] Use the wallet / platform name only to derive a candidate chain identifier for lookup, not as the final source of truth.
- [X] Resolve the final `chain` value from trusted source material collected locally under `docs/tax/crypto-origin/` and referenced from `docs/tax/portugal-crypto-tax/sources.md`.
- [x] Use deterministic normalization rules such as:
  - `Ledger Berachain (BERA)` -> `Berachain`
  - `Ledger SUI` -> `SUI`
  - `Ethereum (ETH) - 0x...` -> `Ethereum`
  - `Solana (SOL) - ...` -> `Solana`
  - `ByBit (2)` -> `ByBit`
  - `Gate.io` -> `Gate.io`
- [x] Strip transport suffixes such as address tails (`- 0x...`, `- 5R39...`) and asset tickers in parentheses when they are only wallet-label noise.
- [x] Keep the raw wallet name unchanged in the workbook; `chain` is an additional normalized field, not a replacement.
- [x] Add a dedicated helper in `src/shares_reporting/application/crypto_reporting.py` so both capital and rewards use the exact same chain derivation logic.
- [X] Build and archive trusted reference material for every chain/operator inferred from the 2025 dataset before finalizing the mapping, including current examples such as `Berachain`, `Sui`, `Starknet`, `zkSync ERA`, `Ethereum`, `Solana`, `TON`, `Aptos`, `Arbitrum`, `Mantle`, `Polygon`, `BASE`, `Binance Smart Chain`, `Gate.io`, `Kraken`, `ByBit`, `Binance`, and `Wirex`.
- [X] Prefer official foundation / protocol / operator pages, terms, legal notices, or official PDFs for that archive; if the source is HTML, store an extracted Markdown or authoritative PDF instead of raw HTML.
- [x] Add the chain column to both Crypto worksheet tables:
  - capital gains: `Disposal chain`
  - rewards: `Reward chain`
- [x] Place the chain column next to wallet / platform metadata so country, operator, wallet, and chain are visually grouped.
- [x] If the wallet label does not allow a reasonable derivation, set `chain` to `Unknown` explicitly instead of guessing from the asset symbol alone.
- [x] Write tests first for the derivation helper before changing production code.
- [x] Minimum unit-test coverage:
  - `Ledger Berachain (BERA)` -> `Berachain`
  - `Ledger SUI` -> `SUI`
  - `Ethereum (ETH) - 0x6ABd...15` -> `Ethereum`
  - `ByBit (2)` -> `ByBit`
  - blank wallet -> `Unknown`
- [x] Add an integration test asserting the generated Crypto worksheet contains both new chain headers and writes the normalized values into the expected cells.

### Task 6: Redesign the Crypto sheet rewards section

- [x] Replace the current raw `REWARDS INCOME` presentation with an IRS-focused summary table that shows only the aggregated `taxable_now` rows.
- [x] Add a separate support section for `deferred_by_law` so nothing disappears from the workbook.
- [x] Mark the filing-facing section explicitly as IRS-ready and ensure every mandatory field is present.
- [x] Include counts and EUR totals for taxable-now and deferred-by-law rows in the reconciliation section.
- [x] Ensure there is no `manual_review` bucket in the final workbook output.
- [x] Keep enough support detail in the workbook for auditability even if the filing-facing table becomes much shorter.

### Task 7: Verify the legal minimum line count on real data

- [x] Run the extraction against the current Koinly dataset and count how many rows remain in the filing-ready rewards table after classification and aggregation.
- [x] Compare that count with the current raw reward count and record the reduction in the workbook or reconciliation area.
- [x] Spot-check the highest-value aggregated rows against operator country and official income-code rules before trusting the final layout.
- [x] Confirm that DeFi-like rows are absent from the filing-ready immediate-income section because they were correctly classified as `deferred_by_law`.
- [x] Spot-check capital-gain rows to confirm the same country logic is used there and that no final row is missing mandatory IRS-facing fields.
- [x] Spot-check that chain derivation is correct for the dominant wallets in the 2025 dataset, including `Ledger Berachain`, `Ledger SUI`, `Starknet`, `Ethereum`, `Solana`, and `ByBit`.

### Task 8: Update documentation

- [x] Extend `docs/tax/portugal-crypto-tax/README.md` with the final reward classification and aggregation rules once implemented.
- [X] Keep `docs/domain/crypto_reporting_guidelines.md` as the canonical numbered implementation-guidance document for crypto reporting behavior.
- [X] Keep `docs/domain/shares_reporting_guidelines.md` as the canonical numbered implementation-guidance document for cross-cutting report-generation behavior.
- [X] Update `docs/tax/portugal-crypto-tax/sources.md` if new official materials are consulted during implementation.
- [X] Create canonical chain/operator origin docs under `docs/tax/crypto-origin/` and make `docs/tax/portugal-crypto-tax/sources.md` reference those archived trusted sources.
- [x] Document that wallet / platform labels are only the discovery hint for chain lookup, while the final reported chain / country mapping comes from trusted archived sources.
- [x] Add or update tests and docs together so future changes do not re-expand the filing workload by accident.
