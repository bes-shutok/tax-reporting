# Shares Reporting Guidelines

Cross-cutting reporting guidelines for this repository outside the narrow tax-law rule set.

## Terminology

- `SRG-xxx`: numbered tax-reporting guideline for this repository.
- Core report: the main Interactive Brokers capital-gains / dividend output.
- Auxiliary dataset: optional supporting input such as Koinly crypto exports.

## Reliability Guidance

**SRG-001**
Auxiliary datasets must not block generation of the core report. Missing or malformed Koinly input must warn clearly and allow the IB report to finish without crypto data.

**SRG-002**
When the repository already carries a specific jurisdiction mapping or documented override, the workbook should use that specific value instead of vague placeholders such as `Multiple jurisdictions`.

**SRG-003**
Normalized reporting helpers such as `platform`, `wallet`, `chain`, and operator-country fields must be rendered alongside the raw data they explain, not as hidden transformations.

## Documentation Guidance

**SRG-004**
Canonical implementation/reporting guidance belongs under `docs/domain/`. Tax-law source archives belong under `docs/tax/...`.

**SRG-005**
In `docs/tax/.../official/`, keep only origin representations of source material. Derived summaries and repository guidance belong outside `official/`.

**SRG-006**
When the source is HTML, prefer a readable extracted Markdown or authoritative PDF representation over storing raw HTML.

**SRG-007**
Under `docs/tax/`, use `*-tax` folders for country-specific tax-law archives and `*-origin` folders for chain/operator domicile archives. Do not mix law and origin evidence in the same folder.

**SRG-008**
Immediately taxable non-IB Category E income from auxiliary datasets (for example, fiat-denominated lending or referral rewards sourced from Koinly) must be written to the `Reporting` worksheet's capital investment income section under `OTHER CAPITAL INVESTMENT INCOME`, not to the originating auxiliary worksheet's filing summary. The originating worksheet retains classification detail, per-row trace data, and reconciliation for auditability. This prevents the same taxable-now aggregate from appearing as a filing target in two locations and keeps the main Reporting sheet as the single filing-facing source for all Category E income.
