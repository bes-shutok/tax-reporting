# Glossary

Terms used across this repository.

**Language convention:** this glossary is in English. Where a term originates in a non-English jurisdiction (Portuguese tax law by default; EU directives otherwise), the original native-language naming is preserved in *italics* alongside the English explanation, so the original form fields and source documents remain identifiable. Jurisdiction is tagged in the section heading.

**Section layout:**
- [Generic data & reporting terms](#generic-data--reporting-terms) - project/engineering concepts, jurisdiction-neutral.
- [Portuguese (PT) tax-jurisdiction terms](#portuguese-pt-tax-jurisdiction-terms) - schedules, quadros, operation codes, and legal concepts. These drive the actual filing.
- [EU terms](#eu-terms)
- [Internal identifiers](#internal-identifiers)

See `docs/maintenance/crypto_rules.md` for authority levels and `docs/maintenance/tax/decision_points/` for per-year rulings.

## Generic data & reporting terms

- **CG** - Capital gains (crypto disposals). Report rows from the Koinly Capital Gains export.
- **OGR** - Other Gains Report (Koinly). Holds disposal totals used to override per-lot sums when `use_other_gains_report=True`.
- **TH** - Transaction History (Koinly). Source of truth for FIFO rebuild and cross-asset carry-over.
- **FIFO** - First-in-first-out lot matching, applied per-wallet per-institution (PT statutory basis: CIRS art. 43 n.9).
- **Holding period** - Short-term (< 365 days, taxable) vs long-term (exempt). In PT the exempt threshold is CIRS art. 10 n.6/n.19.
- **Materiality threshold** - Entries with `|gain/loss| < 1 EUR` are filtered post-aggregation (see `crypto_rules.md`).
- **Zero-basis review** - Zero-cost disposals flagged for manual review when proceeds meet `ZERO_BASIS_REVIEW_MIN_PROCEEDS`. Per-lot flag; re-evaluated at the aggregation boundary so that one noisy lot does not flag an aggregated disposal whose summed cost/proceeds/gain are material.
- **Aggregated review flag** - The `review_required` / `review_reason` rendered on a user-visible Excel row. Distinct from the per-lot flag living on in-memory entries; re-derived from aggregated values (summed cost, proceeds, gain) rather than joined from per-lot reasons.
- **Reward dust** - A zero-EUR-value reward row on an asset Koinly *can* price (the asset has at least one `value_eur > 0` row in the same export); the zero is a 2-decimal export rounding artifact. Collapsed into a per-`(asset, wallet)` summary block on the Crypto Supplementary tab. Contrast with genuinely-unpriced rewards (per-row `YES` flag retained).
- **In-asset interest** - Loan repayment overshoot where a DeFi variable-rate loan accrues interest in the borrowed asset, so `repaid_amount` exceeds `received_amount` by a small percentage. Not a cross-year anomaly; classified separately from genuine cross-year loans and from loans Koinly could not price.
- **Annex hint** - Repo workbook column (`Annex hint = J | G1`) indicating which IRS schedule each row targets (routing guide, not a filed value). Under PT, `J` = taxable Anexo J Quadro 9; `G1` = exempt long-term crypto (Anexo G1 Q7).
- **LP** - Liquidity provision / pool tokens (add/remove liquidity).
- **Derivatives** - Futures/perpetuals; losses on liquidation are disposals of collateral (a taxable disposal), not an error.
- **Stablecoin / payment token** - Fiat-pegged asset (e.g. EURC, USDC); proceeds classification per `docs/maintenance/tax/decision_points/`.

## Portuguese (PT) tax-jurisdiction terms

These are the actual fields, schedules, and codes used when filing the Portuguese IRS. Source documents: the official Modelo 3 forms mirrored in `docs/maintenance/tax/laws/pt/crypto-tax/official/modelo3_anexo_{e,g,g1,j}_<year>.pdf`. **Field numbers are renumbered by Portaria** (e.g. Portaria 104/2026); re-verify against the live form for the filing year before submitting.

### Tax bodies and instruments

- **AT** - *Autoridade Tributária e Aduaneira* - the Portuguese tax authority. Issues Ofícios Circulados and PIVs (binding info).
- **CIRS** - *Código do IRS* - the Portuguese personal income tax code. Consolidated text in `docs/maintenance/tax/laws/pt/crypto-tax/official/cirs_2025-07_code_consolidated.pdf`.
- **IRS** - Portuguese personal income tax return (*Modelo 3*), **not** the U.S. IRS.
- **Modelo 3 / Anexo / Quadro** - the return form, its schedules (*Anexo*), and the numbered tables within a schedule (*Quadro*, abbreviated `Q`).

### Filing concepts

- **Englobamento** - *englobamento* = aggregation option. Add a Category G/E block to overall income at the marginal rate instead of the 28% flat rate (*taxa autónoma*). Worth it when the marginal bracket < 28%; mandatory under CIRS art. 72(14) once the top bracket is hit (PT-C-015). Toggled per block (see toggles below) as `01` Sim vs `02` Nao.
- **Taxa autónoma** - *taxa autónoma* = the 28% flat autonomous rate on Category G/E income. The default if englobamento is not chosen.
- **País da Fonte / País da Contraparte** - portal fields: source country and counterparty country, entered as Tabela X numeric codes (e.g. US=840, CA=124, Cayman=136, IE=372, HR=191, AE=784, GB=826). For crypto, País da Fonte is resolved from operator origin, never from taxpayer residence.
- **Soma de Controlo** - *soma de controlo* = the portal's per-table control total that every line in the table must sum to. The walkthrough pre-computes it to reconcile before entry (e.g. Q9.2B derivatives = 405,61).
- **RNH** - *Residente Não Habitual* (NHR) regime. Foreign income meeting the gate is exempt (reported in Anexo L) rather than taxed at 28%/englobamento; see AT RNH folheto mirror.

### Schedules (Anexos)

- **Anexo A** - *rendimentos da Categoria A* - Category A income (dependent work / salary).
- **Anexo E** - *rendimentos da Categoria E* - capital income (interest, dividends). Englobamento toggle for interest lives here.
- **Anexo G** - Category G **domestic** capital gains. Notable quadros: **Q6** = salary-type gains + the Categoria A/B englobamento choice; **Q13** = financial-derivative operations (resident counterparty, codes G51-G54), englobamento toggle in **Q15**; **Q18** = crypto gains englobamento toggle.
- **Anexo G1** - exempt / separately-declared gains. **Q7** = criptoativos held >= 365 days (exempt under CIRS art. 10 n.19, but declaration is mandatory).
- **Anexo J** - **foreign-source** income (the detail schedules). **Q8** = foreign dividends/interest (Categoria E); **Q9** = foreign capital gains (*incrementos patrimoniais*), split into the tables below.
- **Anexo L** - NHR exemption schedule. Where RNH-exempt foreign income is reported under the 10-year regime.

### Anexo J · Quadro 9 table shorthand

The foreign capital-gains quadro is tabbed in the portal; the walkthrough abbreviates the tables as `Q9.2x` / `Q9.4x`:

- **Q9.2A (Tabela A)** - *Alienação onerosa de partes sociais e outros valores mobiliários* - taxable disposal of shares/securities, art. 10(1)(b). One line per disposal lot, with realization / acquisition / expenses values.
- **Q9.2B (Tabela B)** - *Outros incrementos patrimoniais* incl. derivatives with a **non-resident** counterparty, art. 10(1)(c),(e)-(h). Takes **net income** (*Rendimento Líquido*), not realization/acquisition; code **G30**. Resident-counterparty derivatives route to Anexo G Q13 / G51 instead (AT Processo 28298/2025).
- **Q9.2C** - englobamento toggle sub-table for the 9.2A/9.2B block (`01` Sim / `02` Nao).
- **Q9.4A (Tabela D)** - criptoativos held < 365 days, taxable, art. 10(1)(k). Same realization/acquisition shape as Q9.2A.
- **Q9.4B** - englobamento toggle sub-table for the 9.4A block (same `01`/`02` convention).
- **Q9.6** - *incrementos patrimoniais - outros* - residual foreign capital gains.

### Operation codes (Códigos)

From the official Modelo 3 code tables. One code per line, chosen from a closed enum:

- **G01** - *Alienação onerosa de ações / partes sociais* - taxable disposal of shares/securities, art. 10(1)(b). Used on every Q9.2A share-disposal line.
- **G30** - *Outros incrementos patrimoniais / instrumentos financeiros derivados com contraparte não residente* - other capital gains / derivatives with a non-resident counterparty. Used on Q9.2B derivative lines.
- **G51-G54** - closed enum for Anexo G Q13 derivative operations (resident counterparty). **G51** = *operações relativas a instrumentos financeiros derivados* (the default derivative code); G52-G54 = the other Q13 operation types. Non-resident counterparties do NOT use this enum (they use Q9.2B / G30).
- **E23 / E24** - Categoria E capital-income codes for **EU paying agents** (relevant for the withholding-tax field *Imposto retido* and *NIF da entidade retentora*). US/CA/UK paying agents use other Category E codes, not E23/E24.
- **E25** - *Juros e outros rendimentos de capitais decorrentes de operações relativas a criptoativos* - interest / capital income from crypto-asset operations, art. 5(2)(u) CIRS. Used for crypto-denominated interest (e.g. Wirex). Verified 2026-06-24 by `pdftotext` extraction of the Tabela in `modelo3_anexo_j_2025.pdf`.

## EU terms

- **DAC8 / MiCA** - EU directives/regulation under `docs/maintenance/tax/laws/eu/crypto-tax/`.

## Internal identifiers

- **CRG / SRG / PT-C** - Crypto Reporting Guideline / Structure Reporting Guideline / PT-Crypto rule IDs cited in `docs/maintenance/crypto_rules.md` and `docs/maintenance/crypto_reporting_guidelines.md`.
- **CMD** - Crypto Mapping Decision (operator origin) in `docs/maintenance/tax/crypto-origin/mapping_decision_log.md`.
- **DP** - Decision Point in `docs/maintenance/tax/decision_points/<year>.md`.
