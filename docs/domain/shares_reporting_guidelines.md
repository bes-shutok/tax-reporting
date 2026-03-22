# Shares Reporting Guidelines

Cross-cutting reporting guidelines for this repository outside the narrow tax-law rule set.

## Terminology

- `SRG-xxx`: numbered shares-reporting guideline for this repository.
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
