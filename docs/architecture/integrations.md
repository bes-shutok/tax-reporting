# Integrations

This is a local batch tool with **no service-to-service integrations at runtime, except the optional on-chain transaction fetcher described below**. The rest of this page records the external data sources the tool consumes (file-based) and the archived source material it references.

## Consumed inputs (file-based)

- **Interactive Brokers CSV exports** - flex-query-style CSVs in `resources/source/`. Numeric fields from external reports are parsed with thousands/decimal-separator detection that fails clearly on ambiguity (see `docs/maintenance/development_lessons.md`).
- **Etherscan V2 (Berachain) on-chain transactions** - optional, opt-in runtime integration. When enabled, the fetcher calls the Etherscan V2 unified API (`https://api.etherscan.io/v2/api`) to pull on-chain transaction history for configured wallet addresses and writes `resources/result/<year>/bera_transactions.csv`. Requires the `BERA_CHAIN_API_KEY` environment variable and the optional `resources/source/<year>/chains.json` config (wallet list; chain id and native ticker are derived from an internal chain registry). When the env var or config is absent, the fetcher is skipped and the tool behaves as a purely local batch job.
- **Koinly CSV exports** - `*transaction_history*.csv` (TH), capital-gains export, and the Other Gains Report (OGR). Optional and non-blocking.
- **Exchange rates** - static, configured in `config.ini` `[EXCHANGE RATES]`; updated annually from the national central bank.

## Referenced source archives (not loaded at runtime)

- **Operator/chain origin** - `docs/maintenance/tax/crypto-origin/` (registry, decision log, archived operator terms). Chain derivation uses deterministic normalization validated against this archive.
- **Tax law archive** - `docs/maintenance/tax/laws/<jurisdiction>/crypto-tax/official/` (CIRS, AT officios, Modelo 3 annexes, MiCA, DAC8). Cited for authority levels in `docs/maintenance/crypto_rules.md`.

## Runtime data files

Loaded by the application (paths resolved from repository root):

- `docs/maintenance/tax/decision_points/<year>.toml` - law-driven flags (see `infrastructure/config.py`).
- `docs/maintenance/tax/popular_crypto_tokens.json` - known-token list for zero-value reward detection.
- `docs/maintenance/tax/derivatives_labels/<provider>_<year>.json` - TH labels marking derivatives events.

## Pointers

- Koinly settings and ingestion rules: `docs/maintenance/koinly_guidelines.md`.
- Origin provenance and freshness: `docs/maintenance/tax/crypto-origin/sources.md`.
