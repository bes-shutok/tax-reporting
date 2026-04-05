# Plan: Remove Legacy Token Origin Guessing And Add Safe Examples

## Context
The current Crypto sheet column is backed by repository-side heuristics that infer origin from disposal-day matching against Koinly `transaction_history` `exchange` rows. That behavior is misleading for rows such as loan repayments because it can show a swap string that describes a nearby same-day event rather than a deterministic Koinly-exported linkage for the disposed lot. The safer short-term change is to remove the legacy guessing logic completely, rename the user-facing column to `Token origin`, keep it blank until a Koinly-first implementation exists, and add fully fake example inputs and outputs so a new GitHub user can run every major feature without private files. Research on a proper Koinly-backed origin implementation should be captured as a separate follow-up plan after the cleanup lands.

## Validation Commands
```bash
uv run pytest tests/unit/application/test_crypto_reporting.py
```

```bash
uv run pytest tests/end_to_end/test_excel_report_generation.py tests/end_to_end/test_full_ib_export_pipeline.py
```

```bash
uv run tax-reporting
```

### Task 1: Remove Legacy Token Origin Guessing With TDD
Files:
- `src/shares_reporting/application/crypto_reporting.py`
- `tests/unit/application/test_crypto_reporting.py`

- [ ] Write failing test: add a focused unit test proving a capital row no longer inherits origin from a same-day disposal-driven `exchange` heuristic.
- [ ] Run RED: `uv run pytest tests/unit/application/test_crypto_reporting.py -k "token_origin and legacy"`
- [ ] Write failing test: add a regression for the `2025-05-22` style loan-repayment scenario asserting that, without deterministic Koinly-exported acquisition linkage, the origin field is blank rather than `WBTC -> LBTC`.
- [ ] Run RED: `uv run pytest tests/unit/application/test_crypto_reporting.py -k "loan_repayment and token_origin"`
- [ ] Remove the legacy provenance builder and disposal-day matching path from `src/shares_reporting/application/crypto_reporting.py`.
- [ ] Keep the data model field in place for now so the workbook shape stays stable, but set it only from deterministic logic that already exists in this phase; otherwise leave it blank.
- [ ] Delete or rewrite unit tests that currently encode disposal-day / near-midnight guessing behavior.
- [ ] Run GREEN: `uv run pytest tests/unit/application/test_crypto_reporting.py`
- [ ] Refactor names and comments so no code path still describes the removed heuristic as valid behavior.
- [ ] Record negative requirements:
- [ ] Do not keep `_build_swap_lookup()` or equivalent disposal-day fallback logic “just in case”.
- [ ] Do not repurpose the old heuristic under a new name.
- [ ] Do not attach token origin from same-day disposal context once this task is complete.
- [ ] Definition of done:
- [ ] No production code path derives origin from disposal-day guessing.
- [ ] Tests fail if the old same-day inferred-origin behavior returns.

### Task 2: Rename The Column To Token Origin And Keep It Honest
Files:
- `src/shares_reporting/application/persisting.py`
- `tests/unit/application/test_crypto_reporting.py`

- [ ] Write failing test: assert the Crypto worksheet header renders `Token origin` instead of `Token swap history`.
- [ ] Run RED: `uv run pytest tests/unit/application/test_crypto_reporting.py -k "Token origin header"`
- [ ] Update workbook rendering in `src/shares_reporting/application/persisting.py` so the header reads `Token origin`.
- [ ] Update worksheet-oriented tests to expect the new header text.
- [ ] Add a test that verifies blank origin renders as blank rather than stale swap text.
- [ ] Run GREEN: `uv run pytest tests/unit/application/test_crypto_reporting.py -k "Token origin"`
- [ ] Record negative requirements:
- [ ] Do not rename the column to a stronger claim such as `Exact origin`.
- [ ] Do not keep any wording that implies the field is a direct Koinly column.
- [ ] Do not reintroduce synthetic swap wording through comments, test names, or workbook labels.
- [ ] Definition of done:
- [ ] The workbook column is named `Token origin`.
- [ ] The rendered values are blank unless supported by deterministic logic available in this phase.

### Task 3: Add Fully Fake End-To-End Example Data
Files:
- `resources/source/ib_export_example.csv`
- `resources/source/shares-leftover_example.csv`
- `resources/source/koinly2025/`
- `resources/result/`
- `tests/end_to_end/test_excel_report_generation.py`
- `tests/end_to_end/test_full_ib_export_pipeline.py`

- [ ] Write failing end-to-end test: verify the repository can generate a report from committed example inputs only, without relying on private local exports.
- [ ] Run RED: `uv run pytest tests/end_to_end/test_excel_report_generation.py tests/end_to_end/test_full_ib_export_pipeline.py -k "example"`
- [ ] Replace or augment the committed example inputs with obviously fake demo data that covers:
- [ ] shares capital gains
- [ ] dividends
- [ ] rollover / leftover integration
- [ ] crypto capital events
- [ ] crypto rewards
- [ ] blank `Token origin` examples after legacy removal
- [ ] Keep all example data clearly synthetic:
- [ ] use obviously fake wallet labels such as `Example SUI Wallet`
- [ ] use random-looking hashes and identifiers
- [ ] keep aggregate monetary values modest, preferably within about `1000 EUR`
- [ ] avoid any real names, real account ids, or original wallet identifiers
- [ ] Add or refresh a committed example output in a safe path if the project already uses committed output artifacts for demonstration.
- [ ] Update or add end-to-end assertions so the generated workbook demonstrates all major report sections from the fake data.
- [ ] Run GREEN: `uv run pytest tests/end_to_end/test_excel_report_generation.py tests/end_to_end/test_full_ib_export_pipeline.py`
- [ ] Record negative requirements:
- [ ] Do not copy your original wallet labels, transaction ids, timestamps that could identify you, or real balances into the example set.
- [ ] Do not commit outputs with machine-local metadata or user-specific paths.
- [ ] Do not make the examples look like real taxpayer records; they should read as demos.
- [ ] Definition of done:
- [ ] A fresh clone of the repository contains enough safe example data to exercise every major feature.
- [ ] The example data is clearly fake and reviewable in git.

### Task 4: Document The Example Workflow For New Users
Files:
- `README.md`
- `resources/source/`
- `resources/result/`

- [ ] Write failing doc-oriented test or checklist item: identify the missing README guidance for running the example dataset end-to-end.
- [ ] Add a README section that explains:
- [ ] which committed example files are safe to use
- [ ] what command to run
- [ ] which output file to inspect
- [ ] which features are demonstrated by the example set
- [ ] Explain `Token origin` accurately: after this cleanup phase it is intentionally blank unless deterministic Koinly-backed linkage exists.
- [ ] Add a short note near the example data that it is synthetic and not tax advice.
- [ ] Record negative requirements:
- [ ] Do not direct users to private 2025 files.
- [ ] Do not assume users will infer the examples workflow from tests alone.
- [ ] Definition of done:
- [ ] A new user can understand and run the full example workflow from the repository contents alone.

### Task 5: Research Koinly-First Origin Matching And Write A Follow-Up Plan
Files:
- `resources/source/koinly2025/koinly_2025_capital_gains_report_FhghyZA3cF_1774804455.csv`
- `resources/source/koinly2025/koinly_2025_transaction_history_jdKWUY9yc5_1774804468.csv`
- `src/shares_reporting/application/crypto_reporting.py`
- `docs/plans/`

- [ ] Inspect the Koinly exports and document exactly which acquisition-side fields can support deterministic origin matching.
- [ ] Verify whether `capital_gains_report` exposes any direct transaction id / lot id / hash linkage; if not, state that explicitly.
- [ ] For the BTC-backed Ledger SUI cases, map which rows appear matchable from acquisition-side Koinly exports using:
- [ ] wallet / platform
- [ ] received asset
- [ ] `Date Acquired`
- [ ] received amount
- [ ] received cost basis
- [ ] event `Type` / `Tag`
- [ ] Write a new implementation plan in `docs/plans/` for the future Koinly-first origin feature.
- [ ] The follow-up plan must be TDD-oriented and separate from this cleanup plan.
- [ ] Record negative requirements:
- [ ] Do not implement the new origin feature in this plan.
- [ ] Do not preserve the removed heuristic as a fallback in the follow-up design unless evidence shows no deterministic export-based alternative exists.
- [ ] Do not describe inferred matching as “gold source” if the CSV exports do not actually encode a direct linkage key.
- [ ] Definition of done:
- [ ] This cleanup plan ends with a separate reviewable plan for the future Koinly-first implementation.
- [ ] The repo is in a safer, less misleading state even before the replacement feature is built.
