# Cross-Reference: Permanent-Housing Rent Deduction (CIRS art. 78.º-E) and the Tenant CLS Route

Derived note (NOT an official source-origin file). Verified against primary sources on
2026-06-27. Provenance of each source is recorded in `sources.md`. No PII.

## Why this note exists

The permanent-housing rent deduction for IRS 2025 turned on three documents whose wording
must be read together; the consolidated CIRS main text and the AT folheto appear to
disagree on the cap until the transitional norm is read. This note records the
reconciliation so the deduction is neither under- nor over-claimed.

## Source set (consulted 2026-06-27)

- `official/portaria_106_2025_cls_locatario_2025-03-13.pdf` - Portaria n.º 106/2025/1, de
  13 de marco (mirrored). Approves the CLS ("Comunicacao do Locatario ou Sublocatario").
- `official/cirs_consolidado_2026-06-03.pdf` - CIRS consolidated text (última atualização
  Lei 26/2026, de 3 de junho), mirrored. art. 78.º-E ("Deducao de encargos com imoveis")
  verified locally against this snapshot; the live Portal rendering
  (info.portaldasfinancas.gov.pt/.../cirs_rep/Pages/irs78e.aspx) is the canonical
  re-verification URL. The operative art. 78.º-E text is transcribed in section 1.1.
- `official/at_folheto_irs_deducoes_2026-04-01.pdf` - AT deductions folheto for IRS 2025,
  note 8 (rent cap) and note 7 (global ceiling).
- `official/cis_consolidado_2025-03-27.pdf` and `official/cppt_consolidado_2025-03-27.pdf`
  - CIS art. 60 (CLS legal base) and CPPT art. 70.º/102.º (reclamacao graciosa prazo),
  mirrored for offline cross-reference.

## 1. CIRS art. 78.º-E - verified text and the cap reconciliation

### 1.1 The deduction (n.º 1, alinea a))

"e dedutivel um montante correspondente a 15 % do valor suportado por qualquer membro do
agregado familiar: a) Com as importancias, liquidas de subsidios ou comparticipacoes
oficiais, suportadas a titulo de renda pelo arrendatario de predio urbano ou da sua fracao
autonoma para fins de **habitacao permanente**, quando referentes a contratos de
arrendamento celebrados ao abrigo do Regime do Arrendamento Urbano (DL 321-B/90) ou do
**Novo Regime do Arrendamento Urbano (Lei 6/2006)** ... ate ao limite de 800 EUR."

Points confirmed against the primary text:
- 15 % of rent; rent must be for **fins de habitacao permanente**.
- Contracts under the NRAU (Lei 6/2006, de 27 de fevereiro) qualify. A 2021 contract is
  NRAU, so the legal basis is met IF the finalidade is "habitacao permanente".
- n.º 2: only encargos on faturas communicated to AT under DL 198/2012 (CAE 68200) OR via
  the art. 115(5) means (recibos de renda) are considered. This is the AT cross-check that
  keys the deduction to the contract registration and the recibos.

### 1.2 The cap discrepancy and the transitional norm (critical)

The consolidated CIRS n.º 1 a) and n.º 4 show, in the redacao of Lei 36/2024 (in force
since 1 January 2025):
- n.º 1 a) base limit: **800 EUR**.
- n.º 4 a) elevated (RC <= primeiro escalao de art. 68): **1 100 EUR**.
- n.º 4 b) sliding (1st escalao < RC <= 30 000): 800 + (1100 - 800) x (30 000 - RC) /
  (30 000 - valor do 1o escalao).

But the AT folheto (IRS 2025, note 8) lists, for FY2025:
- RC > 30 000: **700 EUR** (flat base).
- RC <= 8 059: **1 000 EUR** (flat elevated).
- sliding 8 059 - 30 000: 700 + 300 x (30 000 - RC) / 21 941.

These agree only once the transitional norm is read. Lei 36/2024, art. 3 (transitory):
"o aumento da deducao prevista na alinea a) do n.º 1 e nas alineas a) e b) do n.º 4 do
artigo 78.º-E ... e concretizado progressivamente: a) 50 % em 2025; b) 75 % em 2026;
c) 100 % em 2027."

Reconciliation (the increase is phased, so FY2025 gets 50% of the step-up):
- Base: pre-2025 600 -> 2027 full 800; +50% of 200 in 2025 = **700** (matches folheto).
- Elevated: pre-2025 900 -> 2027 full 1 100; +50% of 200 in 2025 = **1 000** (matches).
- Sliding denominator 21 941 = 30 000 - 8 059, so "valor do 1o escalao" relevant for the
  low-income elevation is 8 059 (the folheto's flat-elevation threshold).

Conclusion: for **FY2025 the operative cap is the folheto's note 8 (700 / 1 000 / sliding
700 + 300 x (30 000 - RC)/21 941, RC = colectavel / 2 joint)**. The consolidated CIRS main
text's 800 / 1 100 are the 2027 full-target figures and must NOT be used for IRS 2025.
This is exactly the project-guidelines #3 hazard (consolidated code text vs the redacao in
force for the fiscal year, including transitional norms).

Later amendment (not relevant to FY2025): DL 97/2026, de 20 de maio, added art. 78.º-E
n.º 10, elevating the alinea a) limit to 1 000 EUR from 2027 (900 EUR for 2026). Affects
FY2026/FY2027 only.

## 2. Portaria 106/2025/1 (CLS) - tenant route, verified scope

Transcribed/verified from the mirrored PDF (diploma body, pp. 1-2):
- CLS bases on **CIS art. 60(4)**, altered by **Lei 56/2023, de 6 de outubro**. It lets
  the locatario/sublocatario communicate the contrato (inicio, **alteracao**, cessacao)
  when the locador does not comply with the duty to communicate (CIS art. 60(1)).
- Art. 2(1): "A CLS tem **natureza facultativa**".
- Art. 2(3)-(4): the tenant states the motivo and attaches the contract + supporting
  docs; **for alterations/cessations, the tenant must cite the contrato's ID as registered
  in the Portal**. So a finalidade correction can be flagged as an "alteracao".
- Art. 3: the Portaria "produz efeitos a **1 de agosto de 2025**". The CLS therefore
  cannot recharacterize a contract for FY2025; it only takes effect for communications
  from August 2025 onward and does not retroactively override the landlord's existing
  registration.

Implication for the rent matter: the CLS is a useful parallel/evidence step but cannot, by
its own terms, fix FY2025. The decisive route for FY2025 remains the administrative
reclamacao against the IRS 2025 liquidation (arguing effective permanent residence and
clerical-error classification not imputable to the tenants).

## 3. CIS art. 60 (legal base of the CLS)

Cited verbatim in the Portaria preamble: Lei 56/2023 altered CIS art. 60 to add the n.º 4
tenant-communication possibility. Full CIS art. 60 text now verified locally against the
mirrored `official/cis_consolidado_2025-03-27.pdf` (artigo 60.º, p. 54); the operative
n.º 4 substance matches what the Portaria preamble quotes.

## 4. Net effect on the filing

- Substantive right: the 15% rent deduction (art. 78.º-E(1)(a)) is available for NRAU
  permanent-housing contracts. The legal test is "fins de habitacao permanente"; the
  Portal-registered finalidade is the administrative gate that AT uses to auto-grant it.
- If the finalidade stays "Nao Permanente", AT auto-sets the 2025 deduction to 0. The fix
  is an administrative reclamacao after liquidation (plus, optionally, a CLS for the
  record). The CLS alone does not cure FY2025.
- For FY2025 the cap is the folheto note 8 (50% phase), NOT the consolidated 800/1 100.

## 5. Reclamacao graciosa prazo (verified from the mirrored CPPT)

The post-liquidacao route is a CPPT reclamacão graciosa, not the IRS-automático
declaracão-de-substituicão mechanism (which has its own shorter window). Verified directly
against `official/cppt_consolidado_2025-03-27.pdf` (última atualização DL 49/2025):
- **art. 70.º n.º 1**: the reclamacao graciosa prazo is **120 dias**, counted from the
  "conhecimento" event defined in art. 102.º n.º 1.
- **art. 102.º n.º 1**: the impugnacão judicial prazo is **3 meses**.

This corrects an earlier "~30 days" note (which conflated the prazo with the
IRS-automático substituição window). A secondary LLM-search summary had also returned a
wrong article ("art. 130"); primary-source PDF verification settled it - exactly the
reason the consolidated codes were mirrored for offline cross-reference
(development_lessons.md #188).
