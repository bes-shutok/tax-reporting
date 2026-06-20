# tax-reporting

Short overview for humans. **Start here (Layer 1).** Deeper material lives in Layer 2 (`docs/architecture/`, `docs/maintenance/`); historical context in `docs/history/`.

## What this service does

`tax-reporting` is a local batch CLI that transforms Interactive Brokers and Koinly CSV exports into Portuguese (PT) IRS-ready tax-reporting outputs: capital gains, dividends, and crypto rewards/capital gains, plus a FIFO rollover CSV. It has no server and no network access at runtime.

## Main responsibilities

- Match security disposals FIFO (per-wallet per-institution) and aggregate capital gains for filing.
- Aggregate dividends with withholding-tax detection and per-symbol currency validation.
- Ingest optional Koinly crypto exports, resolve token/operator origin, compute crypto capital gains and reward income, and attach actionable review flags.

## Key integrations and dependencies

- **Inputs:** IB flex-query CSVs and Koinly CSVs (Transaction History, Capital Gains, Other Gains Report) in `resources/source/`.
- **Static config:** exchange rates and ISIN mapping in `config.ini`; law-driven flags in `docs/maintenance/tax/decision_points/<year>.toml`.
- **Reference archive:** operator/chain origin and tax-law PDFs under `docs/maintenance/tax/`.
- **Toolchain:** `uv`, Python 3.14, Ruff.

## APIs and events (high level)

None. This is a CLI tool (`uv run tax-reporting`); there is no HTTP API and no asynchronous event flow. Input/output schemas are documented in `docs/architecture/api-contracts.md`; the processing flow in `docs/architecture/event-flows.md`.

## High-level flows

1. Load config (`config.ini` + decision-points TOML); fail fast on invalid jurisdiction or missing TOML.
2. Ingest IB trades (currency conversion, ISIN mapping); optionally ingest Koinly crypto (non-blocking).
3. Compute FIFO, aggregate, filter immaterial entries, attach review flags.
4. Render the Excel workbook and rollover CSV to `resources/result/`.

## Operations

- Run and flags: see `README.md` (repo root) and `docs/architecture/operational-guides.md`.
- Testing: `uv run pytest`.
- Annual maintenance: update exchange rates and copy the decision-points TOML/MD for the new fiscal year.

## Where to read next

| Layer | Folder | Use for |
|-------|--------|---------|
| 2 | `docs/architecture/` | System, domain, integrations, API/flow, ops, troubleshooting overviews |
| 2 | `docs/maintenance/` | Crypto/tax guidelines, glossary, project decisions, decision points, tax-law archive |
| 3 | `docs/history/` | Plans, investigations, feature notes (reference only) |
