# On-chain chain/wallet config

Configuration for the optional on-chain DEX transaction fetcher (Berachain/Etherscan V2
pipeline). This documents the `chains.json` schema, where the committed artificial
template lives, where the operator's real (gitignored) copy lives, and the required API
key.

## Schema

Each year's `chains.json` is a JSON object with a single `wallets` array. **The user
supplies only wallet identity**: three fields per entry. The loader derives every
other field from internal trusted sources (see "Derived fields" below).

### Minimal user schema

```jsonc
{
  "wallets": [
    {
      "chain": "Berachain",                    // str  - chain name; must be a key in the chain registry
      "label": "Ledger Berachain (BERA)",      // str  - human-readable wallet label, written into the CSV
      "address": "0x6abd...46715"              // str  - checksummed hex wallet address
    }
  ]
}
```

### Derived fields

The loader fills these from internal sources; the user does **not** supply them:

- `chainid`: from the trusted chain registry in
  `src/tax_reporting/application/crypto/chain_derivation.py` (`_CHAIN_TO_CHAINID`).
- `native_ticker`: from the on-chain ticker map in the same registry
  (`_CHAIN_ON_CHAIN_NATIVE_TICKER`; e.g. Polygon = `POL`).
- `start_date`: `max(date(year, 1, 1), chain_launch_date)` (fiscal-year start, clamped
  up to the chain's mainnet genesis).
- `end_date`: `min(date(year, 12, 31), today)` (fiscal-year end, clamped down to today).

DI-2 restated: chain facts (`chainid`, `native_ticker`, launch date) live in the
trusted chain registry; the user supplies only wallet identity (`chain`, `label`,
`address`).

### Supported chains

Only **Berachain** is currently supported for the on-chain fetcher. Other EVM chains
(Ethereum, Binance Smart Chain, Polygon, Arbitrum, BASE, Mantle, zkSync ERA) are
internally wired in the chain registry but are **not** safe to use yet: the fetcher
paginates from block 0 and a long-history chain's full history exceeds the `max_rows`
ceiling and is silently truncated. That truncation defect is pre-existing and tracked
separately. Requesting an unsupported or unknown `chain` raises `FileProcessingError`
naming the chain.

### Field notes

- `chain` must be a key present in the chain registry (see "Supported chains" above).
  An unknown chain name is a hard config error, surfaced as `FileProcessingError`.
- `address` must be a hex wallet address string; the loader requires a non-empty string
  (it does not enforce EIP-55 checksum format or normalize case). The decoder compares
  the configured address against each row's `from`/`to` case-insensitively, so a
  checksummed config address still matches the API's lower-case format; a leg matching
  neither is emitted with `direction="unknown"` and a WARNING.
- `native_ticker` / `start_date` / `end_date` are derived (see "Derived fields"
  above); they are not part of the user schema.

## Files

### (b) Committed artificial template: `resources/source/example/<year>/chains.json`

A committed, explicitly **artificial** template ships at
`resources/source/example/<year>/chains.json`. The `example` subtree is the only path
under `resources/source/` that is NOT gitignored (see `.gitignore`:
`/resources/source/*` ignored, then `!/resources/source/example` re-allowed).

The committed template uses only artificial values: a `chain` of `"Berachain"` and
an obviously-fake address (`0x0000...1111`). It exists so tests have a real file to
load and so the schema is self-documenting. **Never put real wallet addresses or real
chain identity in the committed template** (DI-7).

### (c) Personal counterpart: `resources/source/<year>/chains.json` (gitignored)

The operator creates the REAL config locally at
`resources/source/<year>/chains.json` (e.g. `resources/source/2025/chains.json`).
This path is matched by the `/resources/source/*` gitignore rule and is therefore
**NOT committed**; it holds personal wallet data. The fetcher reads this file at
run time. If it is absent, the fetcher logs a single WARNING and the run continues
without on-chain data (non-blocking; the IB/Koinly report is unaffected).

### (d) `BERA_CHAIN_API_KEY` environment variable

The fetcher calls the Etherscan V2 unified endpoint
(`https://api.etherscan.io/v2/api?chainid=<id>&...`) and requires an Etherscan API
key, read from the `BERA_CHAIN_API_KEY` environment variable via `os.getenv(...)`.
A single key works across all 60+ Etherscan V2 chains. Register a free key at
<https://etherscan.io/register>. If `BERA_CHAIN_API_KEY` is unset or empty, the
fetcher warns and skips (non-blocking). Never commit the key.

## Operator live dry-run (acceptance step; not a release gate)

With a real `resources/source/<year>/chains.json` in place and the key exported, the
recommended manual acceptance step is:

```bash
BERA_CHAIN_API_KEY=<key> uv run tax-reporting
```

This is optional and not part of the automated release gates (`uv run pytest` and
`uv run ruff check`); it is the operator's manual check that live data resolves.
