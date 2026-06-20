# System Overview

## What this service does

`tax-reporting` transforms Interactive Brokers (IB) and Koinly CSV exports into Portuguese (PT) IRS-ready tax-reporting outputs: capital gains, dividends, and crypto rewards/capital gains, plus a FIFO rollover CSV.

It is a local batch CLI tool (no server, no API). Start at `docs/README.md` (Layer 1) and `README.md` (repo root) for onboarding.

## Layered architecture

Domain-driven layering: `domain` -> `application` -> `infrastructure` -> `presentation`.

- `domain/` - pure tax/currency logic, value objects (e.g. `TradeDate` NamedTuple), jurisdiction config.
- `application/` - orchestration: CSV parsing, currency conversion, FIFO matching, aggregation, Excel rendering. Orchestration layers stay thin (~500 lines); crypto sub-orchestrators live under `application/crypto/` and `crypto_fifo/`.
- `infrastructure/` - I/O and config: `config.py` (reads `config.ini` + decision-points TOML), file readers/writers.
- `presentation/` - Excel report assembly and worksheet layout.

## Entry point and data flow

`uv run tax-reporting` (flags: `--example`, `--source-file`, `--output-dir`, `--log-level`).

Input CSVs in `resources/source/` -> domain-driven transform (currency conversion, ISIN mapping, FIFO) -> Excel reports + `shares-leftover.csv` rollover in `resources/result/`. If `shares-leftover.csv` sits beside the export it is merged and ordered before current trades for FIFO.

## Boundaries

- **No network at runtime.** Exchange rates and ISIN mappings are static config; operator origin is resolved from archived source documents under `docs/maintenance/tax/crypto-origin/`, never fetched live.
- **Optional crypto** is non-blocking: missing/mismatched/unparseable Koinly input warns and continues IB-only reporting.

## Pointers

- Domain rules: `docs/maintenance/domain-model.md`, `docs/maintenance/crypto_rules.md`.
- Reporting structure: `docs/maintenance/tax_reporting_guidelines.md`.
- Decisions: `docs/maintenance/project-decisions.md`.
