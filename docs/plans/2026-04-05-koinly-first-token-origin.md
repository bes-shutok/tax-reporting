# Plan: Koinly-First Token Origin Matching

## Context

The legacy disposal-day swap guessing heuristic was removed (2026-04-05, plan `2026-04-05-remove-legacy-token-origin-and-add-safe-examples.md`). The `token_swap_history` data model field and the `Token origin` workbook column now remain blank. This plan designs the replacement: a deterministic origin field populated from Koinly export data that can be verified against source documents.

Research on the actual Koinly exports (`resources/source/koinly2025/`) reveals:

- The **Capital Gains Report** has columns: `Date Sold`, `Date Acquired`, `Asset`, `Amount`, `Cost (EUR)`, `Proceeds (EUR)`, `Gain / loss`, `Notes`, `Wallet Name`, `Holding period`. It contains **no transaction IDs, lot IDs, hashes, or any explicit linkage** to the transaction history.
- The **Transaction History** has columns: `Date`, `Type`, `Tag`, `Sending Wallet`, `Sent Amount`, `Sent Currency`, `Sent Cost Basis`, `Receiving Wallet`, `Received Amount`, `Received Currency`, `Received Cost Basis`, `Fee Amount`, `Fee Currency`, `Gain (EUR)`, `Net Value (EUR)`, `Fee Value (EUR)`, `TxSrc`, `TxDest`, `TxHash`, `Description`. It contains `TxHash`, `TxSrc`, `TxDest` for on-chain transactions.
- The **Income Report** has no transaction identifiers.
- There is **no direct foreign-key relationship** between capital gains rows and transaction history rows. Correlation is implicit via `(date, asset, wallet)` tuples.

Because the capital gains report does not expose acquisition-side transaction identifiers, deterministic origin matching must rely on **implicit correlation** between the capital gains report's acquisition columns (`Date Acquired`, `Asset`, `Wallet Name`, `Amount`) and the transaction history's sending/receiving fields on the same date/asset/wallet. This is weaker than a direct linkage key but is the strongest option available from the CSV exports alone.

## Validation Commands
```bash
uv run pytest tests/unit/application/test_crypto_reporting.py -x
```

```bash
uv run pytest tests/end_to_end/test_example_report_generation.py
```

### Task 1: Define The Origin Matching Data Model And Correlation Contract
Files:
- `src/shares_reporting/application/crypto_reporting.py`
- `tests/unit/application/test_crypto_reporting.py`

- [ ] Define a `TokenOrigin` dataclass (or TypedDict) that captures: `acquired_from_asset`, `acquired_from_platform`, `acquisition_method` (enum: `direct_purchase`, `swap_conversion`, `bridge_transfer`, `defi_yield`, `reward`, `transfer`, `unknown`), and an optional `confidence` field (`high`/`medium`/`low`).
- [ ] Add a correlation contract comment block in `crypto_reporting.py` explaining that origin derivation relies on implicit `(date, asset, wallet)` matching between the capital gains report and transaction history, not on explicit foreign keys.
- [ ] Write failing tests: given a capital gains row with `Date Acquired`, `Asset`, `Wallet Name`, and a transaction history containing a matching acquisition event, the origin resolver returns the correct `TokenOrigin`.
- [ ] Write failing tests: given a capital gains row where no matching transaction history row exists (CEX internal, or history gap), the origin resolver returns `TokenOrigin(acquisition_method=unknown)`.
- [ ] Run RED: `uv run pytest tests/unit/application/test_crypto_reporting.py -k "token_origin_resolver"`
- [ ] Implement the resolver: parse the transaction history to build an acquisition-side lookup, match capital gains rows to acquisition events, and populate `TokenOrigin`.
- [ ] Run GREEN: `uv run pytest tests/unit/application/test_crypto_reporting.py -k "token_origin_resolver"`
- [ ] Refactor: extract the resolver into its own module (`crypto_origin_resolver.py`) if the code exceeds ~100 lines.
- [ ] Negative requirements:
  - Do not reintroduce same-day disposal-context matching (the removed heuristic).
  - Do not treat implicit date/asset/wallet correlation as equivalent to a direct transaction-id link. Mark confidence as `medium` for correlated matches, `high` only if a hash or explicit identifier is available.
  - Do not derive origin for rows where the acquisition date predates the Koinly account history (use `unknown`).

### Task 2: Wire The Resolver Into The Pipeline And Populate Token Origin
Files:
- `src/shares_reporting/application/crypto_reporting.py`
- `src/shares_reporting/application/persisting.py`
- `tests/unit/application/test_crypto_reporting.py`
- `tests/integration/test_excel_generation_integration.py`

- [ ] Wire the new origin resolver into the capital-gains pipeline in `crypto_reporting.py`, passing the transaction history path at the call site where `token_swap_history` is currently set to `""`.
- [ ] Update `CryptoCapitalGainEntry.token_swap_history` to carry the resolved origin string (format: `"BTC (swap_conversion, medium confidence)"` or `""` for unknown).
- [ ] Write integration test: the workbook's `Token origin` column shows a non-blank value for rows where the resolver found a match, and blank for unknown.
- [ ] Write integration test: the workbook's `Token origin` column shows the confidence level.
- [ ] Run GREEN: `uv run pytest tests/integration/test_excel_generation_integration.py -k "token_origin"`
- [ ] Update the example dataset (`resources/source/example/`) to include a transaction history file so the e2e example tests exercise origin resolution.
- [ ] Run GREEN: `uv run pytest tests/end_to_end/test_example_report_generation.py`
- [ ] Negative requirements:
  - Do not remove the `Token origin` column or rename it.
  - Do not suppress `unknown` origin rows from the report.
  - Do not commit real wallet hashes or identifiers to the example dataset.

### Task 3: Handle Edge Cases And Confidence Levels
Files:
- `src/shares_reporting/application/crypto_origin_resolver.py` (or inline in `crypto_reporting.py`)
- `tests/unit/application/test_crypto_origin_resolver.py`

- [ ] Handle the case where multiple transaction history rows match the same `(date, asset, wallet)` tuple (e.g., several small deposits on the same day). Resolve by choosing the closest timestamp or aggregating.
- [ ] Handle the case where `Date Acquired` is `1970-01-01` (Koinly's fallback for unknown acquisition date). Always return `unknown` origin.
- [ ] Handle the case where the transaction history contains `exchange` rows where both sent and received assets are crypto (e.g., BTC -> WBTC). Derive `swap_conversion` origin from the sent side.
- [ ] Handle the case where the transaction history contains bridge/transfer rows. Derive `bridge_transfer` origin from the source chain.
- [ ] Handle the case where the capital gains row has `Notes = "Missing cost basis"`. Set `confidence = low`.
- [ ] Write failing tests for each edge case, then implement and run GREEN.
- [ ] Run: `uv run pytest tests/unit/application/test_crypto_origin_resolver.py`
- [ ] Negative requirements:
  - Do not raise exceptions on ambiguous matches; return the best-effort match with reduced confidence.
  - Do not assume the transaction history is complete or covers all acquisition dates.

### Task 4: Document The Origin Resolution Strategy And Update Domain Docs
Files:
- `docs/domain/crypto_reporting_guidelines.md`
- `docs/domain/crypto_implementation_guidelines.md`
- `README.md`

- [ ] Add a CRG rule (e.g., CRG-015) documenting the origin resolution strategy: implicit `(date, asset, wallet)` correlation, confidence levels, and fallback to `unknown`.
- [ ] Update `crypto_implementation_guidelines.md` with a "Token Origin Resolution" section describing the resolver, its inputs, outputs, and edge cases.
- [ ] Update `README.md` to reflect that `Token origin` is now populated with confidence levels for rows where acquisition-side correlation is possible.
- [ ] Update the example workflow note to mention that the example dataset now includes origin resolution.
- [ ] Negative requirements:
  - Do not describe implicit correlation as "gold source" or "exact". Use language like "best-effort correlation from Koinly export data".
  - Do not remove the disclaimer that origin values should be reviewed.

## Key Constraints

1. **No direct linkage key**: The Koinly capital gains CSV provides no transaction ID, lot ID, or hash that directly links to the transaction history. All matching is implicit via date/asset/wallet correlation. Code and documentation must reflect this limitation honestly.

2. **Confidence-aware**: Every resolved origin must carry a confidence level. This prevents downstream consumers from treating correlated-but-not-verified origins as fact.

3. **Graceful degradation**: When the transaction history is absent, incomplete, or ambiguous, the resolver returns `unknown` rather than guessing. This is the primary safety property that distinguishes the new approach from the removed heuristic.

4. **Example data safety**: The example dataset must use synthetic wallet names, fake hashes, and clearly synthetic data. No real identifiers.
