# Plan: Remove Legacy Token Origin Guessing And Add Safe Examples

## Context
The current Crypto sheet column is backed by repository-side heuristics that infer origin from disposal-day matching against Koinly `transaction_history` `exchange` rows. That behavior is misleading for rows such as loan repayments because it can show a swap string that describes a nearby same-day event rather than a deterministic Koinly-exported linkage for the disposed lot. The safer short-term change is to remove the legacy guessing logic completely, rename the user-facing column to `Token origin`, keep it blank until a Koinly-first implementation exists, and add fully fake example inputs and outputs so a new GitHub user can run every major feature without private files. The examples should not just be minimal smoke data: they should also demonstrate why the project is useful by collapsing large synthetic crypto histories into a small number of Portuguese-reporting-ready capital-gain and reward lines. Research on a proper Koinly-backed origin implementation should be captured as a separate follow-up plan after the cleanup lands.

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

- [x] Write failing test: add a focused unit test proving a capital row no longer inherits origin from a same-day disposal-driven `exchange` heuristic.
- [x] Run RED: `uv run pytest tests/unit/application/test_crypto_reporting.py -k “token_origin and legacy”`
- [x] Write failing test: add a regression for the `2025-05-22` style loan-repayment scenario asserting that, without deterministic Koinly-exported acquisition linkage, the origin field is blank rather than `WBTC -> LBTC`.
- [x] Run RED: `uv run pytest tests/unit/application/test_crypto_reporting.py -k “loan_repayment and token_origin”`
- [x] Remove the legacy provenance builder and disposal-day matching path from `src/shares_reporting/application/crypto_reporting.py`.
- [x] Keep the data model field in place for now so the workbook shape stays stable, but set it only from deterministic logic that already exists in this phase; otherwise leave it blank.
- [x] Delete or rewrite unit tests that currently encode disposal-day / near-midnight guessing behavior.
- [x] Run GREEN: `uv run pytest tests/unit/application/test_crypto_reporting.py`
- [x] Refactor names and comments so no code path still describes the removed heuristic as valid behavior.
- [x] Record negative requirements:
- [x] Do not keep `_build_swap_lookup()` or equivalent disposal-day fallback logic “just in case”.
- [x] Do not repurpose the old heuristic under a new name.
- [x] Do not attach token origin from same-day disposal context once this task is complete.
- [x] Definition of done:
- [x] No production code path derives origin from disposal-day guessing.
- [x] Tests fail if the old same-day inferred-origin behavior returns.

### Task 2: Rename The Column To Token Origin And Keep It Honest
Files:
- `src/shares_reporting/application/persisting.py`
- `tests/unit/application/test_crypto_reporting.py`

- [x] Write failing test: assert the Crypto worksheet header renders `Token origin` instead of `Token swap history`.
- [x] Run RED: `uv run pytest tests/integration/test_excel_generation_integration.py -k "token_origin"`
- [x] Update workbook rendering in `src/shares_reporting/application/persisting.py` so the header reads `Token origin`.
- [x] Update worksheet-oriented tests to expect the new header text.
- [x] Add a test that verifies blank origin renders as blank rather than stale swap text.
- [x] Run GREEN: `uv run pytest tests/integration/test_excel_generation_integration.py -k "token_origin"`
- [x] Record negative requirements:
- [x] Do not rename the column to a stronger claim such as `Exact origin`.
- [x] Do not keep any wording that implies the field is a direct Koinly column.
- [x] Do not reintroduce synthetic swap wording through comments, test names, or workbook labels.
- [x] Definition of done:
- [x] The workbook column is named `Token origin`.
- [x] The rendered values are blank unless supported by deterministic logic available in this phase.

### Task 3: Add Fully Fake End-To-End Example Data
Files:
- `resources/source/example/ib_export.csv`
- `resources/source/example/shares-leftover.csv`
- `resources/source/example/koinly2024/`
- `tests/end_to_end/test_example_report_generation.py`

- [x] Write failing end-to-end test: verify the repository can generate a report from committed example inputs only, without relying on private local exports.
- [x] Run RED: `uv run pytest tests/end_to_end/test_excel_report_generation.py tests/end_to_end/test_full_ib_export_pipeline.py -k "example"`
- [x] Replace or augment the committed example inputs with obviously fake demo data that covers:
- [x] shares capital gains
- [x] dividends
- [x] rollover / leftover integration
- [x] crypto capital events
- [x] crypto rewards
- [x] blank `Token origin` examples after legacy removal
- [x] Keep all example data clearly synthetic:
- [x] use obviously fake wallet labels such as `Example SUI Wallet`
- [x] use random-looking hashes and identifiers
- [x] keep aggregate monetary values modest, preferably within about `1000 EUR`
- [x] avoid any real names, real account ids, or original wallet identifiers
- [x] Add or refresh a committed example output in a safe path if the project already uses committed output artifacts for demonstration.
- [x] Update or add end-to-end assertions so the generated workbook demonstrates all major report sections from the fake data.
- [x] Run GREEN: `uv run pytest tests/end_to_end/test_excel_report_generation.py tests/end_to_end/test_full_ib_export_pipeline.py`
- [x] Record negative requirements:
- [x] Do not copy your original wallet labels, transaction ids, timestamps that could identify you, or real balances into the example set.
- [x] Do not commit outputs with machine-local metadata or user-specific paths.
- [x] Do not make the examples look like real taxpayer records; they should read as demos.
- [x] Definition of done:
- [x] A fresh clone of the repository contains enough safe example data to exercise every major feature.
- [x] The example data is clearly fake and reviewable in git.

### Task 4: Document The Example Workflow For New Users
Files:
- `README.md`
- `resources/source/`
- `resources/result/`

- [x] Write failing doc-oriented test or checklist item: identify the missing README guidance for running the example dataset end-to-end.
- [x] Add a README section that explains:
- [x] which committed example files are safe to use
- [x] what command to run
- [x] which output file to inspect
- [x] which features are demonstrated by the example set
- [x] Explain `Token origin` accurately: after this cleanup phase it is intentionally blank unless deterministic Koinly-backed linkage exists.
- [x] Add a short note near the example data that it is synthetic and not tax advice.
- [x] Record negative requirements:
- [x] Do not direct users to private 2025 files.
- [x] Do not assume users will infer the examples workflow from tests alone.
- [x] Definition of done:
- [x] A new user can understand and run the full example workflow from the repository contents alone.

### Task 5: Research Koinly-First Origin Matching And Write A Follow-Up Plan
Files:
- `resources/source/koinly2025/koinly_2025_capital_gains_report_FhghyZA3cF_1774804455.csv`
- `resources/source/koinly2025/koinly_2025_transaction_history_jdKWUY9yc5_1774804468.csv`
- `src/shares_reporting/application/crypto_reporting.py`
- `docs/plans/`

- [x] Inspect the Koinly exports and document exactly which acquisition-side fields can support deterministic origin matching.
- [x] Verify whether `capital_gains_report` exposes any direct transaction id / lot id / hash linkage; if not, state that explicitly.
- [x] For the BTC-backed Ledger SUI cases, map which rows appear matchable from acquisition-side Koinly exports using:
- [x] wallet / platform
- [x] received asset
- [x] `Date Acquired`
- [x] received amount
- [x] received cost basis
- [x] event `Type` / `Tag`
- [x] Write a new implementation plan in `docs/plans/` for the future Koinly-first origin feature.
- [x] The follow-up plan must be TDD-oriented and separate from this cleanup plan.
- [x] Record negative requirements:
- [x] Do not implement the new origin feature in this plan.
- [x] Do not preserve the removed heuristic as a fallback in the follow-up design unless evidence shows no deterministic export-based alternative exists.
- [x] Do not describe inferred matching as “gold source” if the CSV exports do not actually encode a direct linkage key.
- [x] Definition of done:
- [x] This cleanup plan ends with a separate reviewable plan for the future Koinly-first implementation.
- [x] The repo is in a safer, less misleading state even before the replacement feature is built.

### Task 6: Expand The Example Crypto Dataset To Demonstrate High-Volume Aggregation Value
Files:
- `resources/source/example/koinly2024/`
- `resources/result/`
- `tests/end_to_end/test_example_report_generation.py`
- `README.md`

- [x] Extend the synthetic Koinly example inputs so the crypto side contains high-volume history rather than just a few illustrative rows.
- [x] Target at least `1000` committed synthetic crypto rows across the relevant Koinly example extracts, with enough repeated patterns to show realistic aggregation behavior.
- [x] Design the synthetic data so the generated report demonstrates the core value proposition of this project:
- [x] many raw capital-gains rows collapse into a small number of filing-facing capital-gain lines after Portuguese-rule aggregation
- [x] many raw reward rows collapse into a small number of reporting-facing reward lines after taxable/deferred classification and aggregation
- [x] Keep the output intentionally compact and reviewable:
- [x] aim for only a few final crypto capital-gain lines in the report
- [x] aim for only a few final crypto reward summary lines in the report
- [x] make the compression visible enough that a reviewer can immediately see the before/after value of the pipeline
- [x] Preserve the example-safety constraints from Task 3:
- [x] obviously fake wallets, exchanges, hashes, and identifiers
- [x] modest totals and obviously synthetic values
- [x] no real user labels, wallet ids, or private balances
- [x] Add an explicit confirmation step for this task:
- [x] verify the committed example source files contain the intended high-volume crypto input
- [x] verify the generated example workbook contains only a small, structured set of crypto capital-gain and reward lines
- [x] capture those expectations in `tests/end_to_end/test_example_report_generation.py` without replacing the existing example tests
- [x] update the README example section so it explains that the example dataset demonstrates high-volume input collapsing into concise Portuguese-reporting output
- [x] Record negative requirements:
- [x] Do not add thousands of rows merely as noise; the data should be intentionally shaped to exercise aggregation rules
- [x] Do not make the final report verbose just to mirror the input size
- [x] Do not move this work into the Koinly-first token-origin plan; this task is about demonstrating current project value, not origin matching
- [x] Definition of done:
- [x] A fresh clone shows that the project can turn at least `1000` synthetic crypto source rows into a small number of clear report rows
- [x] The example dataset makes the aggregation/compression benefit obvious even before token-origin matching is implemented

### Task 7: Create An Examples-Driven Project Walkthrough And Choose The Initial Presentation Format
Files:
- `README.md`
- `docs/presentation/`
- `resources/source/example/`
- `resources/result/`

- [x] Research the most suitable first presentation format for explaining what this project is built to accomplish.
- [x] Capture the format decision explicitly and start with a dedicated Markdown presentation file under `docs/presentation/` rather than burying the material inside `README.md`.
- [x] Treat the first version as presentation-ready slide notes in Markdown:
- [x] one section per slide
- [x] draft wording for each slide
- [x] references to concrete demo assets to show on that slide, such as CSV paths, workbook paths, and future screenshots
- [x] Create a first-pass presentation document that explains:
- [x] what problem the project solves
- [x] why raw Koinly-style crypto exports are too verbose for filing-facing use
- [x] why Portuguese tax reporting needs legally relevant aggregation and classification instead of raw export dumping
- [x] what the high-volume synthetic example data represents
- [x] how many raw rows go in and how few structured rows come out
- [x] what the key report sections mean for a new user
- [x] Include a recommended slide flow, at minimum:
- [x] problem statement: Koinly can classify transactions, but can still leave the user with thousands of rows for capital gains and rewards
- [x] why this repo exists: convert export-scale detail into Portuguese-reporting-facing summaries while preserving the tax-relevant dimensions
- [x] legal/reporting basis: cite the current official Portuguese references that justify the classification and grouping dimensions
- [x] capital gains example: short-term / taxable case before and after
- [x] capital gains example: long-hold / excluded case before and after
- [x] rewards example: taxable-now vs deferred-by-law before and after
- [x] operational value: safe examples, reproducibility, and auditable source-to-output mapping
- [x] Use concrete before/after examples from the committed synthetic dataset and generated output, with short commentary explaining what is happening.
- [x] For each explanation that depends on Portuguese law or filing instructions, cite the most recent official source available at implementation time.
- [x] Be explicit in the presentation about the legal confidence level:
- [x] where the official source clearly defines the tax rule, say so
- [x] where the repo applies a reporting simplification, describe it as a filing-facing aggregation based on those legal dimensions, not as an explicit AT quote
- [x] Keep the first version simple:
- [x] examples plus text commentary are enough
- [x] no need for polished slides, branding, or a separate presentation tool in this phase
- [x] Add a short pointer from `README.md` to the dedicated presentation document so a new user can discover it easily without duplicating the full content there.
- [x] Record negative requirements:
- [x] Do not mix this task into the Koinly-first token-origin plan; this is a product-explanation artifact, not an origin-matching design task
- [x] Do not start with a heavyweight presentation format that is harder to maintain than the examples themselves
- [x] Do not describe the project only in abstract terms; the presentation should show concrete source-to-output transformations
- [x] Do not overclaim the legal basis for aggregation; distinguish clearly between explicit official rules and repository reporting design built on those rules
- [x] Definition of done:
- [x] The repo contains a clear first-pass presentation artifact explaining what the project does and why it is useful
- [x] The chosen initial format is explicitly justified and easy to evolve later into slides or richer docs if needed
