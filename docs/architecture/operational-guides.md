# Operational Guides

How to run and maintain the tool. There is no deployment, server, or dashboard - operations are local runs and annual data maintenance.

## Running

```
uv run tax-reporting [--example] [--source-file PATH] [--output-dir PATH] [--log-level LEVEL]
```

Alt: `uv run python ./src/tax_reporting/main.py`. Outputs land in `resources/result/`.

## Testing

`uv run pytest` (never `uvx pytest`). Three tiers: `tests/unit/`, `tests/integration/`, `tests/end_to_end/`.

## Annual maintenance

- **Exchange rates** - update `[EXCHANGE RATES]` in `config.ini` from the national central bank each tax year.
- **Decision points** - for a new fiscal year, copy `docs/maintenance/tax/decision_points/2025.toml` (and `.md` sidecar), set `[meta].fiscal_year`, and re-verify each decision point against current sources in `docs/maintenance/tax/laws/`. The `.md` and `.toml` must stay synchronized.
- **Operator origin** - keep `docs/maintenance/tax/crypto-origin/` source manifest, registry, and decision log synchronized when changing chain/operator mappings.

## Dependencies

- `uv` (local, not on PyPI) for environment and test running.
- Python 3.14; Ruff is the primary linter/formatter (line length 120, Google-style docstrings).

## Pointers

- Project guidelines and conventions: `docs/maintenance/project-guidelines.md`.
- Coding/quality rules: repo root `AGENTS.md`.
