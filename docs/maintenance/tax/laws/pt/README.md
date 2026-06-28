# Portugal Tax-Law Archive

Official references and source manifests for Portuguese tax law, grouped by scope. Each
subfolder keeps its own `sources.md` provenance manifest with issuing/effective/superseded
dates (see `docs/maintenance/project-guidelines.md` #1).

## Terminology

- Jurisdiction folder: `laws/<jurisdiction>/` (here `<jurisdiction>` = `pt`).
- Official download: a file mirrored locally from a public official portal, kept under an
  `official/` subfolder so derived notes stay outside it (SRG-005).
- Provenance manifest: a `sources.md` recording the issuing authority, dates, accessible
  mirror URL, and the provisions consulted for each mirrored file.

## Contents

- `crypto-tax/`: Portugal crypto-specific tax law, AT Modelo 3 annex forms (Anexo G/G1/J/E),
  oficios circulados, and AT binding rulings. Self-documenting; see `crypto-tax/README.md`
  and `crypto-tax/sources.md`.
- `official/`: Portugal tax-law references that are NOT crypto-specific. Currently holds the
  AT RNH folheto (NHR / Anexo L), the AT IRS deductions folheto (deducoes a coleta,
  beneficios fiscais e taxas, for rendimentos de 2025), Portaria n.º 106/2025/1 (CLS,
  tenant-side lease communication), and date-stamped consolidated-code snapshots for
  offline cross-reference: CIRS (última atualização Lei 26/2026), CPPT (DL 49/2025), and
  CIS (DL 49/2025). See `sources.md` for provenance and the staleness-management policy.
- `rent_deduction_cross_reference.md`: derived cross-reference note (not source-origin)
  verifying the FY2025 permanent-housing rent deduction (CIRS art. 78.º-E, incl. the cap
  reconciliation between consolidated text and the AT folheto) and the CLS scope/effective
  date. Verified 2026-06-27.
- `sources.md`: provenance manifest for the `official/` general-IRS references in this folder.

## Why the general (non-crypto) archive exists

The crypto and IB pipelines in this repo produce foreign-source income whose FILING
treatment depends on regimes outside crypto law. The most important is the Residente Nao
Habitual (RNH / NHR) regime: it determines whether foreign income is exempt-with-progression
(CIRS art. 81(4)-(5)) and how Anexo J and Anexo L are filled together. The AT RNH folheto
(`official/at_folheto_rnh_2022-10-19.pdf`) is the authoritative AT guide for those Anexo L
fields and is referenced from the FY2025 self-filing walkthrough.
