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
  AT RNH folheto (NHR / Anexo L). See `sources.md` for provenance.
- `sources.md`: provenance manifest for the `official/` general-IRS references in this folder.

## Why the general (non-crypto) archive exists

The crypto and IB pipelines in this repo produce foreign-source income whose FILING
treatment depends on regimes outside crypto law. The most important is the Residente Nao
Habitual (RNH / NHR) regime: it determines whether foreign income is exempt-with-progression
(CIRS art. 81(4)-(5)) and how Anexo J and Anexo L are filled together. The AT RNH folheto
(`official/at_folheto_rnh_2022-10-19.pdf`) is the authoritative AT guide for those Anexo L
fields and is referenced from the FY2025 self-filing walkthrough.
