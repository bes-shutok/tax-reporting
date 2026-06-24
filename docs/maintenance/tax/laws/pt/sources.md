# Source Manifest - Portugal (general IRS / non-crypto)

Retrieved on: 2026-06-24

## Terminology

- Official downloads: files mirrored locally from public official portals.
- Issuing authority: the body that authored the document (read from PDF metadata when present).
- Accessible mirror: a live government URL serving the document; recorded so the local copy can be re-verified periodically.

## Scope

This manifest covers Portugal tax-law references that are NOT crypto-specific (crypto lives under `crypto-tax/`). It exists because non-crypto Modelo 3 mechanics - notably the Residente Nao Habitual (RNH / NHR) regime and Anexo L - determine how income produced by this tool (foreign crypto, securities, and dividend income) is filed.

## Official downloads

1. `official/at_folheto_rnh_2022-10-19.pdf`
- Title: "Residente nao habitual (RNH) - Regime fiscal e anexo L do IRS"
- Issuing authority: Autoridade Tributaria e Aduaneira (AT) - from PDF `/Author` metadata.
- Issuing date: 2022-10-19 (local PDF `/CreationDate` and `/ModDate`: `D:20221019`).
- Effective: 2022-10-19 (AT informational leaflet; the RNH regime rules it summarises apply to grandfathered NHR taxpayers, including the 10-year window for those registered as NHR before the 2024 revocation).
- Superseded: - (no newer AT revision located; the same folheto is the operative AT leaflet).
- Accessible mirror: https://portaldascomunidades.mne.gov.pt/images/EMI/IRS_RNH_PT.pdf (Portal das Comunidades, Ministerio dos Negocios Estrangeiros - an official `gov.pt` host). Note: the live mirror currently serves an earlier export of the same folheto (`/CreationDate` `D:20220421`, 2022-04-21); the locally mirrored file is the later 2022-10-19 export. Both are 20 pages with identical title and page-1 text; the byte difference is a re-export, not a content revision.
- Purpose: authoritative AT guide to the RNH regime and Anexo L, used to confirm the NHR exemption-with-progression mechanism (CIRS art. 81(4)-(5)) and the Anexo J + Anexo L filing flow (Anexo J holds foreign-income detail; Anexo L Quadro 5 references it; Quadro 6C chooses exemption vs foreign-tax credit). Cited from the FY2025 self-filing walkthrough.
- Relevant provisions consulted: CIRS art. 81(4)-(5) (elimination of international double taxation / exemption with progression), the Anexo L Quadro 5 / 6C method-choice fields, and the Tabela de actividades de valor acrescentado (high-value-added activity list relevant to Category B at 20%).

## Related local archives

- `crypto-tax/`: Portugal crypto-specific tax law, AT forms (Anexo G/G1/J), oficios circulados, and binding rulings. See `crypto-tax/sources.md`.
- `crypto-tax/official/modelo3_anexo_j_2025.pdf`, `modelo3_anexo_g1_2025.pdf`, `modelo3_anexo_g_2026.pdf`: the official Modelo 3 annex forms referenced alongside this folheto when filing NHR-affected foreign income.

## Non-downloaded but relevant references

- AT RNH information page: https://info.portaldasfinancas.gov.pt/pt/apoio_contribuinte/Pages/residente-nao-habitual.aspx
  - Consulted: 2026-06-24
  - Purpose: AT landing page for the RNH regime; canonical portal entry for re-verifying the regime status and linked folhetos.
