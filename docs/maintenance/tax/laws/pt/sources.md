# Source Manifest - Portugal (general IRS / non-crypto)

Retrieved on: 2026-06-25 (consolidated code snapshots added 2026-06-27)

## Terminology

- Official downloads: files mirrored locally from public official portals.
- Issuing authority: the body that authored the document (read from PDF metadata when present).
- Accessible mirror: a live government URL serving the document; recorded so the local copy can be re-verified periodically.

## Scope

This manifest covers Portugal tax-law references that are NOT crypto-specific (crypto lives under `crypto-tax/`). It exists because non-crypto Modelo 3 mechanics - notably the Residente Nao Habitual (RNH / NHR) regime, Anexo L, and the household deducoes a coleta (rent, education, dependents) - determine how income produced by this tool (foreign crypto, securities, and dividend income) is filed, and how the household's own deductions reduce the final coleta.

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

2. `official/at_folheto_irs_deducoes_2026-04-01.pdf`
- Title: "IRS - Deduções, benefícios fiscais e taxas para rendimentos do ano de 2025" (PDF `/Title` metadata).
- Issuing authority: Autoridade Tributária e Aduaneira (AT), "Folhetos informativos" series (Producer: Adobe PDF Library 16.0.7).
- Issuing date: 2026-04-01 (PDF `/CreationDate` 2026-04-01; `/ModDate` 2026-04-02). The content footer reads "fevereiro de 2026"; the file is the April-2026 export of that edition.
- Effective: IRS / Modelo 3 for rendimentos do ano de 2025 (filed in 2026). The deducoes a coleta amounts, brackets, and income-phased caps it lists are the in-force rules for FY2025.
- Superseded: - (no newer AT revision located as of 2026-06-25; operative AT deductions leaflet for IRS 2025).
- Accessible mirror: https://info.portaldasfinancas.gov.pt/pt/apoio_contribuinte/Folhetos_informativos/Documents/IRS_deducoes_2025.pdf (Portal das Finanças, AT). The locally mirrored file matches the live download (674 429 bytes, 19 pages, retrieved 2026-06-25).
- Purpose: authoritative AT guide to deducoes a coleta, beneficios fiscais, and taxas for IRS 2025. Used to fix the permanent-housing rent deduction (CIRS art. 78.º-E(1)(a)) and its income-phased cap (folheto note 8) in the FY2025 self-filing walkthrough, and to correct a stale "art. 78-A" reference in the personal docs (art. 78-A is now the dependente deduction; see project-guidelines #2 on CIRS renumbering).
- Relevant provisions consulted: CIRS art. 78.º-E(1)(a) and (b) (rendas de habitacao permanente; juros de dividas) with the income-phased cap in note 8 (rendas: 700 + 300 x (30 000 - RC) / 21 941; juros: 296 + 154 x (30 000 - RC) / 21 941; RC = colectavel / 2 for joint filers); note 7 global deduction ceiling (1 000 + 1 500 x (80 000 - RC) / 71 941, with the 3+-dependente +5% majoracao); CIRS art. 78.º-A (dependente deduction; 726 for age <= 3 years; fixed; outside the note-7 ceiling); CIRS art. 78.º-D (educacao; 30% up to 800); EBF art. 41.º-B(12).

3. `official/portaria_106_2025_cls_locatario_2025-03-13.pdf`
- Title: "Portaria n.º 106/2025/1, de 13 de marco" (DR 1.a serie, n.º 51).
- Issuing authority: Secretaria de Estado dos Assuntos Fiscais (signed by Cláudia Maria dos Reis Duarte Melo de Carvalho), Diario da Republica.
- Issuing date: 2025-03-13 (signed 2025-03-10; published 2025-03-13).
- Effective: enters into force the day after publication; **produces effects from 1 August 2025** (art. 3).
- Superseded: - (operative).
- Accessible mirror: https://files.diariodarepublica.pt/1s/2025/03/05100/0001100019.pdf (Diario da Republica, 1.a serie). Locally mirrored file matches the live download (4 598 186 bytes, 9 pages, retrieved 2026-06-27).
- Purpose: approves the **CLS ("Comunicacao do Locatario ou Sublocatario")** under CIS art. 60(4) (altered by Lei 56/2023), letting the tenant communicate a lease (incl. alterations/cessation) when the landlord does not. Consulted for the FY2025 rent matter: confirmed the CLS is facultative (art. 2(1)), can flag an alteration citing the registered contract ID (art. 2(4)), but **produces effects only from 1 August 2025**, so it cannot recharacterize FY2025. Cross-referenced in `rent_deduction_cross_reference.md` section 2.

4. `official/cirs_consolidado_2026-06-03.pdf`
- Title: "Codigo do IRS (CIRS)" consolidated text (base DL 442-A/88 de 30 de novembro, as amended).
- Issuing authority: Autoridade Tributária e Aduaneira (AT) consolidated-text compilation (PGDLei / Portal das Finanças codes index).
- Última atualização: Lei n.º 26/2026, de 3 de junho (read from the PDF front matter).
- Effective: **current consolidated redação** (3 June 2026). This is the operative text for FY2026 filings and the current numbering for any fiscal year; for a PRIOR fiscal year (e.g. FY2025), apply the redação in force for that period incl. transitional norms (project-guidelines #2). The Lei 36/2024 art. 3 transitional cap phase (50% 2025 / 75% 2026 / 100% 2027) means the consolidated main-text art. 78.º-E n.º 1 a) base 800 EUR / n.º 4 elevated 1 100 EUR is NOT the FY2025 operative cap (700 / 1 000); see `rent_deduction_cross_reference.md` section 1.2.
- Superseded: - (current; re-verify annually, see Staleness management below).
- Accessible mirror: https://info.portaldasfinancas.gov.pt/pt/informacao_fiscal/codigos_tributarios/cirs/Pages/codigo-do-irs.aspx (AT codes index; the consolidated PDF is served from the `Cod_download/Documents/` path under that page). Locally mirrored file retrieved 2026-06-27 (2 054 950 bytes).
- Purpose: offline cross-reference of the rent-deduction article (art. 78.º-E "Deducao de encargos com imoveis") and the foreign-income exemption mechanism (art. 81(4)-(5)); confirms article numbering so AT-cited paragraph numbers can be verified locally without a network round-trip (project-guidelines #2).
- Relevant provisions consulted: art. 78.º-E (rent/housing deduction, incl. the income-phased cap and Lei 36/2024 phase-in), art. 78.º-A (dependentes), art. 81(4)-(5) (RNH exemption with progression), art. 43 (structured products / capital gains).

5. `official/cppt_consolidado_2025-03-27.pdf`
- Title: "Codigo de Procedimento e de Processo Tributario (CPPT)" consolidated text (base DL 433/99 de 26/10, as amended).
- Issuing authority: AT consolidated-text compilation (Portal das Finanças codes index).
- Última atualização: Decreto-Lei n.º 49/2025, de 27/03 (read from the PDF front matter).
- Effective: valid for FY2025 (no newer amendment through retrieval date 2026-06-27).
- Superseded: - (operative as of retrieval; re-verify annually).
- Accessible mirror: https://info.portaldasfinancas.gov.pt/pt/informacao_fiscal/codigos_tributarios/cppt/Pages/codigo-de-procedimento-e-de-processo-tributario-in-1895.aspx (AT codes index; PDF served from `Cod_download/Documents/CPPT.pdf`). Locally mirrored file retrieved 2026-06-27 (1 174 127 bytes).
- Purpose: primary-source verification of the reclamação graciosa deadline after an IRS liquidação. **Corrects an earlier "~30 days" error** (which was the separate IRS-automático declaração-de-substituição mechanism): the reclamação graciosa prazo is **120 dias** (art. 70.º n.º 1, counted per art. 102.º n.º 1); the impugnação judicial prazo is 3 meses (art. 102.º n.º 1). Verified directly against the PDF (not via a secondary summary, which had returned a wrong article).
- Relevant provisions consulted: art. 70.º (apresentação, fundamentos e prazo da reclamação graciosa), art. 102.º (prazo da impugnação).

6. `official/cis_consolidado_2025-03-27.pdf`
- Title: "Codigo do Imposto do Selo (CIS)" consolidated text (base DL 287/2003 de 12 de novembro, as amended).
- Issuing authority: AT consolidated-text compilation (Portal das Finanças codes index).
- Última atualização: Decreto-Lei n.º 49/2025, de 27 de março (read from the PDF front matter).
- Effective: valid for FY2025 (no newer amendment through retrieval date 2026-06-27).
- Superseded: - (operative as of retrieval; re-verify annually).
- Accessible mirror: https://info.portaldasfinancas.gov.pt/pt/informacao_fiscal/codigos_tributarios/cis/Pages/codigo-do-imposto-do-selo.aspx (AT codes index; PDF served from `Cod_download/Documents/CIS.pdf`). Locally mirrored file retrieved 2026-06-27 (828 281 bytes).
- Purpose: legal base for the CLS (tenant-side lease communication). CIS art. 60(4) (altered by Lei 56/2023) is the provision Portaria 106/2025/1 implements; the CLS produces effects only from 1 August 2025 (Portaria art. 3), consistent with the CIS scheme. Mirrored so the cross-reference between Portaria 106/2025/1 and its parent CIS article can be verified locally.
- Relevant provisions consulted: art. 60.º (contratos de arrendamento, incl. n.º 4 tenant communication mechanism).

### Staleness management for consolidated-code snapshots (entries 4-6)

Consolidated codes are living texts amended by successive diplomas. A mirrored snapshot is NOT immediately obsolete: its "última atualização" tag identifies the operative redação for a given fiscal year, and `sources.md` provenance (this manifest) plus annual re-verification (project-guidelines #1, #2) bound the staleness. Because the project workflow hit an external-tool rate-limit mid-task (development_lessons.md #37) and an LLM-search fallback gave a WRONG prazo answer that primary-source PDF verification corrected, **offline access to the exact operative redação is the strongest reason to mirror**. Re-verify each snapshot annually (re-download, diff the "última atualização" tag, update the dated filename and provenance entry when it advances); for any prior fiscal year, apply the redação in force for that period incl. transitional norms rather than reading the consolidated base directly.

## Derived cross-reference note (not source-origin)

- `rent_deduction_cross_reference.md` (sibling file in this folder): consolidates the FY2025 rent-deduction verification - CIRS art. 78.º-E verified text; the **critical cap reconciliation** between the consolidated main text (800/1 100, 2027 full target) and the AT folheto note 8 (700/1 000, 2025 operative) via the Lei 36/2024 art. 3 transitional norm (50% phase in 2025); and the CLS scope/effective-date limits. Verified 2026-06-27 against the sources above.

## Related local archives

- `crypto-tax/`: Portugal crypto-specific tax law, AT forms (Anexo G/G1/J), oficios circulados, and binding rulings. See `crypto-tax/sources.md`.
- `crypto-tax/official/modelo3_anexo_j_2025.pdf`, `modelo3_anexo_g1_2025.pdf`, `modelo3_anexo_g_2026.pdf`: the official Modelo 3 annex forms referenced alongside this folheto when filing NHR-affected foreign income.

## Non-downloaded but relevant references

- AT RNH information page: https://info.portaldasfinancas.gov.pt/pt/apoio_contribuinte/Pages/residente-nao-habitual.aspx
  - Consulted: 2026-06-24
  - Purpose: AT landing page for the RNH regime; canonical portal entry for re-verifying the regime status and linked folhetos.

- Consolidated Codigo do IRS (CIRS), art. 78.º-E ("Deducao de encargos com imoveis") and art. 78.º-A (dependentes): Diario da Republica / PGD compilation; live consolidated rendering at https://info.portaldasfinancas.gov.pt/pt/informacao_fiscal/codigos_tributarios/cirs_rep/Pages/irs78e.aspx . **Now mirrored locally as `official/cirs_consolidado_2026-06-03.pdf` (entry 4 above)**; the live portal page remains the canonical re-verification URL. Authoritative current numbering; cross-check any AT-cited paragraph number against it (project-guidelines #2). For FY2025 use the redacao in force for that period; the AT folheto above is the operative synthesis.
  - Consulted: 2026-06-25 and 2026-06-27.
  - Purpose: confirm the rent deduction article (78.º-E(1)(a)) and the renumbering that moved "rendas de habitacao permanente" out of the former art. 78-A (now the dependente deduction).
  - 2026-06-27 finding: the consolidated main text shows n.º 1 a) base 800 EUR and n.º 4 elevated 1 100 EUR (redacao Lei 36/2024), but **Lei 36/2024 art. 3 phases the increase 50% (2025) / 75% (2026) / 100% (2027)**, so for FY2025 the operative cap is the folheto's 700 / 1 000, NOT the consolidated 800 / 1 100. Reconciliation recorded in `rent_deduction_cross_reference.md` section 1.2. This is the project-guidelines #2 hazard in practice (consolidated text vs fiscal-year redacao incl. transitional norms).

- Lei n.º 36/2024, de 7 de agosto (medidas no dominio da habitacao): Diario da Republica (https://www.dre.pt; identify by diploma reference). Not mirrored.
  - Consulted: 2026-06-25
  - Purpose: increased the housing deduction (encargos com imoveis) underlying the income-phased cap in folheto note 8.

- Lei n.º 45-A/2024, de 30 de dezembro (OE2025 - Orcamento do Estado para 2025): Diario da Republica (https://www.dre.pt; identify by diploma reference). Not mirrored.
  - Consulted: 2026-06-25
  - Purpose: state budget for 2025; carries the FY2025 housing-deduction cap regime that folheto note 8 reflects. Per-amendment attribution to be confirmed against the consolidated CIRS redacao annotations (project-guidelines #2).

- Portaria n.º 150/2004, de 13 de fevereiro (lista de paraísos fiscais / regimes fiscais claramente mais favoráveis): Diário da República (https://dre.pt/dr/detalhe/portaria/150-2004-578338). Not mirrored.
  - Consulted: 2026-06-26
  - Purpose: Official domestic blacklist of preferential tax regimes (tax havens) used to apply the capital loss disallowance rule (CIRS Artigo 43.º, n.º 5) and check RNH exemption exclusions. Under Portaria 150/2004, the United Arab Emirates (UAE) is a blacklisted jurisdiction, making losses from UAE-issued assets (like PSTEYV) non-deductible.
  - Relevant provisions: Tabela de regimes fiscais privilegiados.

- Portaria n.º 292/2025/1, de 5 de setembro (alteração à lista de paraísos fiscais): Diário da República (https://dre.pt/dre/detalhe/portaria/292-2025-934278891). Not mirrored.
  - Consulted: 2026-06-26
  - Purpose: Updates the list of preferential tax regimes approved by Portaria n.º 150/2004, removing Hong Kong, Liechtenstein, and Uruguay. Published on 2025-09-05, in force 2025-09-06, producing effects for tax years beginning on or after 2026-01-01. For FY2025 reporting, the removed jurisdictions remain blacklisted.

