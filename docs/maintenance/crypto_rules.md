# Portugal Crypto Tax Rules (IRS / Modelo 3)

Domain knowledge for generating the crypto capital gains section of the tax report.
Consult this document before changing any crypto reporting logic.

Each rule carries a source reference and the date of the source document so outdated
rules can be identified when the law changes.

**Source authority levels:**
- `[OFFICIAL]`: direct text from AT (Autoridade Tributária) or DRE (Diário da República)
- `[SECONDARY]`: from reputable Portuguese tax advisory sites; plausible but not authoritative

---

## Section 1: Definitions

**PT-C-001** `[OFFICIAL | 2026-01-12]`
A criptoativo is "toda a representação digital de valor ou direitos que possa ser transferida
ou armazenada eletronicamente recorrendo à tecnologia de registo distribuído ou outra
semelhante" (CIRS art. 10 n.17). This includes Bitcoin, ETH, USDT, stablecoins,
and tokens of all kinds.
> Source: AT folheto "Criptoativos, Conceito fiscal e tributação", published 2026-01-12.

**PT-C-002** `[OFFICIAL | 2026-01-12]`
NFTs (non-fungible tokens that are unique and non-interchangeable with other crypto assets)
are **excluded** from this definition and not subject to the crypto capital gains regime
(CIRS art. 10 n.18).
> Source: AT folheto 2026-01-12.

**PT-C-003** `[OFFICIAL | 2026-01-12]`
Stablecoins (e.g. USDT, USDC) are treated as crypto assets, not as fiat currency.
They are subject to the same capital gains rules as other criptoativos.
> Source: AT folheto 2026-01-12 (lists stablecoins explicitly under "principais criptoativos").

---

## Section 2: Taxable Event (Alienação Onerosa)

**PT-C-004** `[OFFICIAL | 2026-01-12]`
A taxable disposal (alienação onerosa) occurs when crypto is sold for fiat money or
exchanged for goods/services. Loss of Portuguese tax residence is also treated as a
deemed disposal (CIRS art. 10 n.22).
> Source: AT folheto 2026-01-12.

**PT-C-005** `[OFFICIAL | 2026-01-12]`
**Crypto-to-crypto swaps are NOT a taxable event at the time of the swap.**
When the proceeds of a disposal take the form of another crypto asset, taxation is deferred
until the replacement asset is itself disposed of for fiat or in-kind (CIRS art. 10 n.20 for
non-securities; CIRS art. 5 n.11 for securities/Category E).
The replacement asset takes the acquisition cost of the asset surrendered.
> Source: AT folheto 2026-01-12.

**PT-C-006** `[OFFICIAL | 2026-01-12]`
This deferral for crypto-to-crypto swaps only applies when both parties are residents of
an EU/EEA member state or a jurisdiction with a double-tax treaty with Portugal
(CIRS art. 10 n.21). Swaps with parties in blacklisted jurisdictions are immediately taxable.
> Source: AT folheto 2026-01-12.

---

## Section 3: Capital Gains Calculation

**PT-C-007** `[OFFICIAL | 2026-01-12]`
Capital gain = **valor de realização − valor de aquisição − despesas necessárias**.
Expenses must be actually incurred and directly related to acquisition or disposal
(e.g. exchange trading fees, gas fees).
> Source: AT folheto 2026-01-12.

**PT-C-008** `[OFFICIAL | 2026-01-12]`
**FIFO is mandatory.** When disposing of crypto assets, the assets acquired earliest are
considered disposed of first (CIRS art. 43 n.6 al.g).
> Source: AT folheto 2026-01-12.

**PT-C-009** `[OFFICIAL | 2026-01-12]`
**FIFO is applied per wallet/exchange independently**, not globally across all wallets.
When the same asset is held on multiple platforms, FIFO is applied to each platform
separately (CIRS art. 43 n.7).
> Source: AT folheto 2026-01-12.

**PT-C-010** `[OFFICIAL | 2026-01-12]`
If AT considers the declared disposal value may diverge from fair market value,
it may determine the value itself. The presumed disposal value is the **market price on
the disposal date** (CIRS art. 52 n.1).
> Source: AT folheto 2026-01-12.

---

## Section 4: Holding Period and Exemption

**PT-C-011** `[OFFICIAL | 2026-01-12]`
**365-day exemption:** Gains and losses on disposal of non-securities crypto assets held
for **≥ 365 days** are **excluded from taxation** (CIRS art. 10 n.19).
These must still be declared in **Anexo G1, Quadro 7** (not Anexo G or Anexo J Quadro 9.4).
> Source: AT folheto 2026-01-12; Ofício Circulado 20269/2024, section 9.

**PT-C-012** `[OFFICIAL | 2022-12-30]`
**Transitional holding period rule:** For crypto acquired **before 01/01/2023**, the holding
period counts from the actual acquisition date (not from 01/01/2023). This means assets
bought in 2018 that were not disposed of before 2023 may already qualify for the
365-day exemption immediately upon the new regime's entry into force.
> Source: Art. 220 Lei n.º 24-D/2022 (LOE 2023), 30/12/2022.

**PT-C-013** `[OFFICIAL | 2026-01-12]`
The 365-day exemption **does not apply** when either counterparty is resident in a
jurisdiction without a double-tax treaty with Portugal or an information-exchange agreement
(CIRS art. 10 n.21). In those cases gains are taxable even if held >365 days.
> Source: AT folheto 2026-01-12.

---

## Section 5: Tax Rates and Englobamento

**PT-C-014** `[OFFICIAL | 2026-01-12]`
Taxable crypto capital gains are subject to a **28% flat rate** (taxa autónoma).
Portuguese tax residents may opt to **englobar** (add to total income for progressive rates),
which may be beneficial at lower income levels (CIRS art. 72 n.1 al.c, n.13).
> Source: AT folheto 2026-01-12.

**PT-C-015** `[OFFICIAL | 2024-03-24]`
**Mandatory englobamento** applies when: the net short-term balance (gains − losses on
assets held <365 days) is positive AND the taxpayer's taxable income (including this balance)
reaches the top income bracket of CIRS art. 68 n.1 (CIRS art. 72 n.14).
> Source: Ofício Circulado 20269/2024, section 8.6, dated 2024-03-24.

---

## Section 6: Losses

**PT-C-016** `[OFFICIAL | 2026-01-12]`
Capital losses (negative gain) from crypto disposals may be carried forward for **5 years**
and offset against future gains from the same category, but only if the taxpayer opts for
englobamento (CIRS art. 55 n.1 al.d).
> Source: AT folheto 2026-01-12.

**PT-C-017** `[OFFICIAL | 2026-01-12]`
Losses arising from transactions where the counterparty is in a **blacklisted jurisdiction**
(regime fiscal claramente mais favorável) are **not deductible** (CIRS art. 43 n.5).
> Source: AT folheto 2026-01-12.

**PT-C-031** `[OFFICIAL | CIRS art. 10(1)(e)]`
Futures and derivatives (including perpetual swaps, options, and other derivative instruments)
are classified as "instrumentos financeiros derivados" under CIRS art. 10(1)(e).
Disposals of derivative positions, including liquidations, are treated as alienação onerosa
and are taxable events. A liquidation is a forced disposal event, not a withdrawal.

**IRS filing routing (counterparty-residency-dependent):** Derivatives realizations route to
different Quadros depending on whether the counterparty (the exchange/operator entity) is resident
or non-resident in Portugal, per AT binding ruling Processo 28298/2025 paragraphs 22-23:
- **Resident counterparty** -> declared in **Anexo G, Quadro 13**
  ("INSTRUMENTOS FINANCEIROS DERIVADOS, WARRANTS AUTÓNOMOS E CERTIFICADOS"), lines 1301-1306, with
  income code **G51** ("Operações relativas a instrumentos financeiros derivados"); the englobamento
  option is signalled in **Quadro 15 of Anexo G**. Each line carries four mandatory fields: Código da
  operação, Titular, Rendimento líquido (the EUR P&L), and País da contraparte (counterparty country =
  operator entity country).
- **Non-resident counterparty** (income obtained abroad, e.g. ByBit/Binance/OKX) -> declared in
  **Anexo J, Quadro 9.2.B**, with income code **G30**; the englobamento option is signalled in
  **Quadro 9.2.C of Anexo J**.

The repo resolves the filing route per row from counterparty residency, but only when the
`TaxJurisdictionConfig.route_derivatives_by_counterparty_residency` flag is on.
`ogr_handler._derivatives_route(country, operator_country, route_via_residency)` drives
`DerivativesPnLEntry.annex_hint` / `operation_code` as follows: when the flag is off, both fields
resolve to `""`. When the flag is on, a resident operator (`operator_country == country`, i.e. the
counterparty is a resident of the taxpayer's jurisdiction) yields `annex_hint="G/Q13"`,
`operation_code="G51"`; a non-resident, empty, or `UNKNOWN` operator yields `annex_hint="J/Q9.2.B"`,
`operation_code="G30"`. The entity defaults are the blank route, so a direct constructor that passes
no jurisdiction fails safe (no PT hint). The Derivatives P&L sheet renders `annex_hint` (Annex
column) and `operation_code` (Código column) per row; when the flag is on it warns if any rendered
Annex is blank. No filer override is required.
Cryptoasset disposals under alínea k) go to Quadro 18 instead; derivatives and cryptoassets are
reported in different Quadros.
> Source: CIRS art. 10(1)(e) - "Operações relativas a instrumentos financeiros derivados";
> confirmed via official AT portal rendering in `cirs_art10_portal_2026-04-01.html`.
> Filing routing: `docs/maintenance/tax/laws/pt/crypto-tax/official/modelo3_anexo_g_2026.pdf` page 4
> (Quadro 13 structure, verified 2026-06-13 via pdftotext extraction); AT PIV 28298/2025 paragraph 22
> (resident counterparty -> Anexo G Quadro 13, code G51; englobamento in Quadro 15) and paragraph 23
> (non-resident counterparty -> Anexo J Quadro 9.2.B, code G30; englobamento in Quadro 9.2.C), verified
> 2026-06-24 via pdftotext extraction of `at_piv_28298_2025.pdf`. Cross-referenced in
> `docs/maintenance/tax/decision_points/2025.md` "Filing Guidelines: Futures and Derivatives Losses".

> **Example:** ByBit SOL/USDT position `<POSITION_ID>` liquidated on 19 Jan 2025,
> 11:28:53 PM. Koinly reported -42.26 USD loss at 11:29:46 PM. The system assessed disposal
> of 280.36 USDT (271.79 EUR) as collateral disposition with negative gain/loss. This is
> correct treatment, not an error. For a detailed verification of how negative gains flow
> through the pipeline (parsing, storage, aggregation, Excel output), see
> `docs/maintenance/negative_gain_handling_verification.md`.

**PT-C-032** `[OFFICIAL | CIRS art. 10(19)]`
For **spot criptoativos** (art. 10(1)(k)), the 365-day rule excludes BOTH gains and losses symmetrically:
- **Short-term (<365 days):** gains/losses are taxable/deductible; losses can be carried forward for 5 years (PT-C-016)
- **Long-term (≥365 days):** both gains AND losses are excluded from taxation
The text states: "São excluídos os ganhos obtidos, bem como as perdas incorridas, resultantes das operações
previstas na **alínea k)** do n.º 1 relativas a criptoativos detidos por um período igual ou superior a
365 dias" (gains and losses from alínea k) operations on criptoativos held >=365 days are excluded).
> Source: CIRS art. 10(19); official AT portal rendering in `cirs_art10_portal_2026-04-01.html`.

> **Scope carve-out - derivatives are NOT covered by PT-C-032.** Art. 10(19) is textually limited to
> "operações previstas na alínea k)" (spot criptoativos). Derivatives fall under alínea e) and have **no
> 365-day holding-period exemption**: both their gains and losses are taxable/deductible regardless of
> holding period, and losses carry forward 5 years unconditionally (see DP-012, PT-C-034, and AT binding
> ruling Processo 28298/2025). Do not apply the >=365-day exclusion to derivatives.

**PT-C-033** `[OFFICIAL | 2026-01-12 | CIRS art. 10(1)(e) | AT folheto 2026-01-12]`

**Scope (flag-conditional):** PT-C-033 applies ONLY when `separate_derivatives_reporting=False`
(DP-012). When True, PT-C-034 governs: OGR values route to the Derivatives P&L tab instead of
overriding spot CG entries, and PT-C-033 is inert for derivatives rows. Spot disposals
continue to use the CG report as authoritative regardless of flag. Cross-reference: PT-C-034.

For futures and derivatives reporting, use the Koinly Other Gains Report (OGR) values
when available, rather than Capital Gains Report values. The OGR provides:
- Explicit Type classification ("Loss" or "Profit") for better tax treatment
- More accurate handling of collateral flow during liquidations
- Better alignment with CIRS art. 10(1)(e) treatment of "instrumentos financeiros derivados"

When OGR contains a futures/derivatives entry (detected by Type="Loss" or Type="Profit"),
use the OGR value as the authoritative source for gain/loss calculation, overriding any
corresponding entry in the Capital Gains Report. This ensures derivatives are reported
with proper classification and collateral flow handling per Portuguese law.
> Source: CIRS art. 10(1)(e) "Operações relativas a instrumentos financeiros derivados";
> AT folheto "Criptoativos, Conceito fiscal e tributação", published 2026-01-12;
> official AT portal rendering in `cirs_art10_portal_2026-04-01.html`.

**PT-C-034** `[OFFICIAL | 2026-06-13 | CIRS art. 10(1)(e) and (k) | AT binding ruling Processo 28298/2025]`
When `separate_derivatives_reporting=True` (DP-012), derivatives P&L is reported separately
from spot crypto under CIRS art. 10(1)(e); spot retains art. 10(1)(k) with 365-day exemption.
Mixing the two produces incorrect tax treatment.

The split is performed by the classifier in `src/tax_reporting/application/crypto/classification.py`
using two signals only: the OGR row `Type` (Profit/Loss) and CG-counterpart existence. OGR/CG
counterpart matching uses a 1-cent (`Decimal("0.01")`) EUR tolerance to absorb rounding; this is
the single numeric threshold in the classifier and is documented here as the matching precision,
not a tax-law parameter.
> Source: AT binding ruling Processo 28298/2025 (archived at
> `docs/maintenance/tax/laws/pt/crypto-tax/official/at_piv_28298_2025.pdf`); CIRS art. 10(1)(e) and (k).
> Cross-reference: PT-C-033 (governs the flag-off path), PT-C-030 (review-flag specificity),
> PT-C-016 (loss carry-forward for derivatives losses).

---

## Section 7: Declaration Forms

**PT-C-018** `[OFFICIAL | 2024-03-24]`
For **domestic-source** crypto (Portuguese exchanges): short-term disposals (<365 days)
go in **Anexo G, Quadro 18A**; long-term (≥365 days, exempt) in **Anexo G1, Quadro 7**.
> Source: Ofício Circulado 20269/2024, sections 8.8 and 9, dated 2024-03-24.

**PT-C-019** `[OFFICIAL | 2024-03-24]`
For **foreign-source** crypto (foreign exchanges such as Bybit, Kraken, Binance, Wirex):
disposals are declared in **Anexo J, Quadro 9.4** ("Alienação onerosa de criptoativos que
não constituam valores mobiliários").
> Source: Ofício Circulado 20269/2024, section 12.6, dated 2024-03-24.

**PT-C-020** `[OFFICIAL | 2026-03-05]`
**Required fields per line in Quadro 9.4 (Anexo J):**
- País da fonte (source country: country of the exchange)
- Data de realização: **Ano, Mês, Dia** (disposal date, day precision only)
- Valor de realização (proceeds in EUR)
- Data de aquisição: **Ano, Mês, Dia** (acquisition date, day precision only)
- Valor de aquisição (cost in EUR)
- Despesas e encargos (expenses and charges)
- Imposto pago no estrangeiro (foreign tax paid)
- País da contraparte (counterparty country)
- Opção pelo englobamento (opt into progressive taxation: yes/no)

The form has **no time-of-day columns**; dates are captured as year, month, and day only.
The same day-level precision applies to Anexo G Quadro 18A (domestic crypto, short-term) and
Anexo G1 Quadro 7 (long-term exempt crypto). Aggregation coarser than day-level (e.g. per month
or per year) would merge distinct disposal events and is not acceptable. Aggregation at day-level
or finer is consistent with the form's design.
> Source: Ofício Circulado 20269/2024, section 12.6, dated 2024-03-24; form columns confirmed in
> modelo3_anexo_j_2025.pdf (in force from January 2026, approved by Portaria 104/2026, 2026-03-05);
> no override found in Ofício Circulado 20278/2025 (dated 2025-03-17) or Portaria 104/2026
> (dated 2026-03-05). Checked 2026-04-07.

**PT-C-021** `[OFFICIAL | 2025-03-17]`
The 2025 Modelo 3 update (for tax year 2024 filing) adjusted Quadro 9.4 by removing its
first (untitled) column. All other fields from PT-C-020 remain unchanged.
> Source: Ofício Circulado 20278/2025, section 12.3.2, dated 2025-03-17.

**PT-C-022** `[OFFICIAL | 2024-03-24]`
When the counterparty is outside the EU/EEA and there is no applicable double-tax treaty,
disposals are declared in **Quadro 18B** (Anexo G, domestic) or with the "país da
contraparte" field in Quadro 9.4 (Anexo J, foreign).
> Source: Ofício Circulado 20269/2024, section 8.8, dated 2024-03-24.

---

## Section 8: Reporting Obligations

**PT-C-023** `[OFFICIAL | 2026-01-12]`
Crypto service providers (custodians, exchange operators) with customers domiciled in
Portugal must report all transactions to AT each year by end of February, via the
"declaração de comunicação de operações com criptoativos" (CIRS art. 124-A).
This means AT may already hold transaction data for cross-verification.
> Source: AT folheto 2026-01-12.

**PT-C-024** `[OFFICIAL]`
No de minimis threshold exists in Portuguese law for crypto disposals. All alienações,
regardless of size, are in principle declarable. No official exemption for sub-threshold
transactions has been found in any of the documents reviewed.
> Source: Confirmed by absence of any such threshold in AT folheto 2026-01-12,
> Ofício Circulado 20269/2024, and Ofício Circulado 20278/2025.

---

## Section 9: Practical Filing Guidance

**PT-C-025** `[SECONDARY | ~2025]`
Each disposal (alienação) should be reported as a separate line in the form
("uma linha por cada operação"). However, the AT circulars do not explicitly state this
for crypto. The "operation" is the **sale transaction**, not the individual FIFO lot allocation.
Multiple FIFO lots matched to the same sale event (same disposal date, same asset,
same wallet) can reasonably be reported as one aggregated line.
> Source: CryptoBooks article "Declarar Cripto de Plataformas Estrangeiras: Anexo J IRS"
> (`https://cryptobooks.tax/pt-PT/blog/declarar-criptoativos-anexo-j-modelo-3`), consulted 2026-04-07;
> not found verbatim in official circulars.

**PT-C-026** `[SECONDARY | ~2025]`
The AT Portal das Finanças does **not support CSV or XML batch import** for Quadro 9.4.
Every line in Quadro 9.4 must be entered manually through the portal's web interface.
> Source: Research finding (2026-03-14); confirmed by absence of import feature in AT portal documentation.

---

## Section 10: Implementation Decisions (this codebase)

These decisions are specific to this codebase and may be revised.

**PT-C-027** `[IMPLEMENTATION DECISION | 2026-03-15, updated 2026-04-07]`
The Crypto sheet aggregates FIFO lot rows by **(disposal date, asset, platform, holding_period)**
before writing to Excel. This collapses multiple FIFO lot rows for the same real sale into
one line per holding period, preserving the taxable vs exempt breakdown needed for correct filing
(PT-C-011: short-term gains are taxable, long-term gains are exempt).
Rationale: Koinly outputs one row per FIFO lot allocation; the "operação" for IRS purposes
is the sale transaction, not the lot. The holding_period must be preserved to distinguish
taxable short-term gains from exempt long-term gains.

**Date precision constraint (PT-C-020):** the official Anexo J Quadro 9.4 form captures dates
as Ano/Mês/Dia (year, month, day); no time-of-day field exists. Aggregation must be at
**day-level or finer**; coarser aggregation (per month, per year) would merge distinct
disposal events and is not acceptable. The current implementation uses day-level dates
internally for grouping, matching the Anexo J form's Ano/Mes/Dia precision (PT-C-020).

**Multi-date acquisition behavior:** when aggregated rows consume lots from multiple acquisition
dates, the Notes field shows all acquisition dates (comma-separated) and the row is highlighted
with blue fill. This visual distinction signals that the aggregated line combines multiple
acquisition origins within the same holding period, helping the user verify that short-term and
long-term gains remain correctly separated (PT-C-011).

**PT-C-028** `[IMPLEMENTATION DECISION | 2026-03-14]`
After day-level aggregation, lines where **|gain/loss| < 1 EUR** are excluded from
the capital gains section of the Crypto sheet.
Rationale: these have no material tax impact (total excluded gain across the 2025 dataset
was ~6 EUR out of −1,452 EUR total). The AT portal requires manual entry of every line;
sub-1-EUR lines represent an impractical burden with no tax consequence.
This decision should be revisited if the dataset changes significantly.

**PT-C-029** `[IMPLEMENTATION DECISION | 2026-03-14]`
The 1 EUR materiality filter applies symmetrically to gains and losses.
After aggregation, any line where **|gain/loss| < 1 EUR** is excluded, including small
capital losses between −1 and 0 EUR, even though losses may in principle carry forward
for 5 years under PT-C-016.
Rationale: this codebase prioritises keeping the manual filing set manageable; retaining
large volumes of sub-1-EUR losses would materially bloat the report without practical value.

**PT-C-030** `[IMPLEMENTATION DECISION | 2026-03-27]`
Review flags in the Excel report carry specific, actionable reasons via the `review_reason`
field on `CryptoCapitalGainEntry` and `CryptoRewardIncomeEntry`. When `review_required=True`,
the Excel column shows "YES: \<reason\>" instead of a bare boolean. Each reason must explain
what the user needs to verify (e.g. "Bybit uses account-region specific entities; verify your
account region matches the operator entity"). Multiple reasons for the same entry are joined
with "; ". The goal is not to eliminate all review flags but to ensure each flag provides
enough context for the user to take action without re-examining source data.
Rationale: bare "YES" review flags required the user to trace back through source data
and operator mappings to understand why the flag was set. Specific reasons make manual
review more efficient and reduce the risk of incorrect dismissals.

**PT-C-035** `[IMPLEMENTATION DECISION | 2026-06-18]`
When the jurisdiction flag `infer_payment_proceeds` is set (PT FY2025, decision point
DP-014), a Koinly-tagged `Payment` / `Card Payment` disposal whose CG `proceeds_eur == 0`
because Koinly emitted `Net Value (EUR) = 0` ("No market rates found") is proceeds-corrected
rather than left at the DP-013 zero-basis flag. The correction is a TH-tag-driven CG
correlation (CG row matched to a payment-tagged TH row by calendar day, normalized asset,
normalized platform, amount at 6 dp) and resolves proceeds in a fixed three-tier order:
(1) primary - trust Koinly's own TH `Net Value (EUR)` when finite and `> 0` (PT-C-007);
(2) stablecoin fallback when `Net Value == 0` - EUR par for configured EUR-pegged
stablecoins, or the fiscal year-end peg->EUR rate conversion (from `[EXCHANGE RATES]`,
the same source shares/dividends use) for non-EUR-pegged stablecoins whose peg currency
has a configured rate; both fallbacks are `review_required=True` approximations of the
disposal-date FMV; (3) review flag for a non-EUR stablecoin whose peg has no config rate,
and for any non-stablecoin. Stablecoin membership and peg annotation are reused from
`docs/maintenance/tax/popular_crypto_tokens.json`; the payment tag pair (`payment`,
`card payment`) lives in `TreatmentConfig.payment_tags`
(`application/crypto/treatment_resolver.py`). No new config file.
Rationale: a goods/services purchase paid in crypto is a taxable alienação onerosa (PT-C-004)
and must carry a non-zero valor de realização; Koinly's price-DB miss (often a token-rename
alias such as EUROC -> EURC) must not silently produce a phantom full-cost loss. Every
inferred proceeds value is `review_required=True` with a reason naming the tier, so the
user can verify the approximation. Full post-Phase-E mechanism (deque + popleft
consumption discipline, day-key timezone rationale, loader degrade-never-raise, DP-013
branch interaction) is documented in `docs/maintenance/crypto_implementation_guidelines.md`
"Payment Proceeds Correction (DP-014)". Out of scope: LP-token unstaking is a distinct
non-taxable-deferred case (DP-005 / PT-C-005).

**PT-C-036** `[IMPLEMENTATION DECISION | 2026-06-23]`
When the jurisdiction flag `exclude_transaction_fees` is set (PT FY2025, decision point
DP-015), standalone network/transaction fee disposals that Koinly realizes on the disposed
fee token are filtered out of the capital gains worksheets rather than left as taxable
*alienações onerosas*. Legal basis: CIRS art. 10(1)(k) - a standalone transaction/network
fee is a non-taxable utility cost without received consideration, so it is not a taxable
disposal and Koinly's default gain/loss realization on the fee token must be removed.
Identification is two-pronged, both gated by a TxHash co-occurrence correlation guard
(the fee event's non-empty `TxHash` must appear at least twice in the Transaction History
CSV, so standalone service payments that share no transaction id remain taxable): (1)
tagged - any `crypto_withdrawal` whose tag is `Cost` or `Loan fee` is filtered (the explicit
tag is trusted; no EUR threshold); (2) untagged-whitelist - an untagged `crypto_withdrawal`
whose `Sent Currency` is a key in `exclude_transaction_fee_max_eur_per_asset` (a
`dict[str, Decimal]` whose keys are the gas-token whitelist and whose values are per-token
EUR ceilings: ETH = 1.0, SOL/SUI/BNB/MATIC/TON = 0.5) AND whose TH `Net Value (EUR)` is
`<=` that asset's ceiling. Unlisted-asset withdrawals are NEVER auto-filtered: an untagged,
TxHash-co-occurring withdrawal of an asset NOT in the dict whose `Net Value (EUR)` is
`<= max(per_asset.values())` is surfaced as a *suspect* (NOT removed) via a Crypto Gains
`review_required` flag (red "YES: \<reason\>" row, when the lot exists), a Crypto
Supplementary "Review required" row (SRG-009 already covers this section), and a log
WARNING - so legitimate gas tokens missing from the config can be discovered and added
(over-taxing on uncertainty is the safe direction). An empty `exclude_transaction_fee_max_eur_per_asset`
degrades the filter to tagged-only (NOT a full no-op). Full mechanism (TxHash co-occurrence
guard, two-phase lot matching, per-lot logging, suspect propagation, pipeline wiring) is
documented in `docs/maintenance/crypto_implementation_guidelines.md` "Transaction Fee
Filtering (DP-015)". Distinct from DP-006 (transfer fees are folded into the transferred
asset's cost basis via a Koinly setting; DP-015 filters a realized standalone-fee disposal
via a tool-side guard).

**PT-C-037** `[IMPLEMENTATION DECISION | 2026-07-04]`
OGR spot P&L is applied at the **disposal-event level**, not per lot. CG lots are
grouped into events by the same `(date, asset, wallet)` key the OGR `spot_index`
uses; the agree-vs-conflict direction decision is taken ONCE on the SIGN of
event totals (`cg_event_gain` vs `ogr_event_gain`). The `> 1 EUR` significance
gate is review-only (it controls the per-lot/per-event review flag), NOT part of
the branch decision - a direction conflict is always resolved with OGR authority
even when one side is below the noise floor. The result is distributed across
the event's lots via **first-lot-absorbs**:
- **Agree branch** (CG and OGR same sign): the FIRST lot (input order) receives
  `gain_loss_eur = ogr_event_gain` and `proceeds_eur = first_lot.cost_eur +
  ogr_event_gain`; the remaining lots receive `gain_loss_eur = 0` and
  `proceeds_eur = lot.cost_eur`. `sum(gain_loss_eur) == ogr_event_gain` and
  `sum(proceeds_eur) == event_cost + ogr_event_gain` byte-exactly (no
  cost-share division, no rounding). This fixes the legacy `N x` over-count,
  where the per-lot override wrote the FULL `ogr_gain_loss` to EVERY lot and
  aggregation summed to `|lots| x ogr_event_gain`.
- **Conflict branch** (opposite signs): UNCHANGED from legacy - each lot keeps
  `±abs(lot.gain_loss_eur)` with the OGR sign. The lots sum to
  `±sum(abs(lot.gain_loss_eur))`, which equals `±abs(cg_event_gain)` ONLY when
  every lot shares the event's CG sign; a mixed-sign event sums absolute
  magnitudes (matching the legacy per-lot write, unchanged here, so not a
  Phase 1 regression).
- **Single-lot events** (both branches) reduce exactly to the legacy output.

**Event identity caveat.** The `(date, asset, wallet)` key is a collapse, not a
no-collision proof: two genuinely distinct same-day spot disposals sharing it
pool into one event under both legacy and Phase 1 (Phase 1 additionally
concentrates the OGR gain on the pooled first lot). This is a pre-existing
ambiguity owned by the deferred Transaction view; see the plan's Monitor
section. Current FY data has 0 OGR matches, so the pooling is unobservable today.

**Cross-holding-period taxable-split shift (agree branch, multi-lot events).**
A multi-lot event whose lots span short and long holding periods is split
across two aggregation groups (aggregation keys on `holding_period`). Legacy
over-counted EACH group (`|group| x ogr_event_gain`); first-lot-absorbs places
the whole `ogr_event_gain` on lot 0, so the short-vs-long taxable split
(PT-C-011: short-term taxable, long-term exempt) shifts to wherever lot 0
lands. This is a deliberate, documented delta from legacy's per-group
over-count, asserted in tests - NOT a reduction-to-legacy claim.

This is a surgical event-level patch; it introduces no new decision-point flag
and no new `TaxJurisdictionConfig` field (no `decision_points/` edit). The
full TH-anchored Transaction view (TxHash / minute-precision identity, raw-row
threading) remains deferred.

> Source: RFC feature-note `docs/history/context/2026-06-20-th-anchored-transaction-state-machine.md`;
> implementation plan `docs/history/plans/2026-07-04-ogr-event-level-application.md`.
> Cross-reference: PT-C-035 (OGR as authoritative realization source), PT-C-030
> (review-flag specificity), PT-C-011 (short-vs-long holding-period taxable split).

**PT-C-038** `[IMPLEMENTATION DECISION | 2026-07-08, updated 2026-07-11 Phase E]`
Per-treatment identification is authoritative from the TH-anchored resolver
(`resolve_treatment` in `application/crypto/treatment_resolver.py`);
identification is resolver-only with no legacy fallback. The six per-stage
adapters consume the pre-built `list[Transaction]` from
`crypto_reporting.py::load_koinly_crypto_report`:

- OGR 1:1 override identifies SPOT_DISPOSAL rows via the resolver; a
  non-SPOT_DISPOSAL row sharing the same `(date, asset, wallet)` key is NOT
  overridden;
- payment-proceeds correction identifies PAYMENT rows via the resolver; the
  re-zero snapshot/restore block is gone (Phase E Task 7); the OGR override
  skips PAYMENT rows so the residual the re-zero block existed to close
  cannot occur;
- loan-affected asset discovery consults `Treatment.LOAN_REPAYMENT` rows AND
  `Treatment.OTHER` rows whose normalized tag is `"loan"` (the
  borrowing-side principal creation); the extra clause (Invariant 11)
  preserves borrow-only assets so they remain in the FIFO rebuild;
- derivatives dedup identification delegates to the resolver via
  `find_derivatives_th_events_from_transactions`; the legacy internal tag
  classifier is gone (the lot-level dedup algorithm itself is unchanged);
- reward/airdrop/LP identification delegates to the resolver; `TreatmentConfig.reward_tags` / `.airdrop_tags` / `.lp_tags` (in `application/crypto/treatment_resolver.py`) are the single source of truth. Phase E Task 5 deleted the former `token_origin.py` duplicates.
- OTHER rows flow through the standard pipeline without a dedicated override.

History (Phase D): the six `treatment_*_via_resolver` flags (DP-019) mapped
1:1 to the six `Treatment` members and provided per-treatment rollback
granularity (flipping a flag to `false` restored the legacy identification
path for that treatment). Phase E (2026-07-11, plan
`docs/history/plans/completed/2026-07-10-th-tx-view-phase-e.md`) deleted the six legacy
adapters AND the six flags, the `_REQUIRED_TREATMENT_FLAGS` tuple, the
`_enforce_required_treatment_flags` loader guard, and the `_countries_table_for`
helper. The pre-Phase-E flag-mechanic behavior is preserved in
`docs/maintenance/development_lessons.md` lessons #49-#52 (append-only
history). Cross-reference: DP-019 (removed); Phase D plan
`docs/history/plans/completed/2026-07-08-th-tx-view-phase-d.md`.

> Source: RFC feature-note `docs/history/context/2026-06-20-th-anchored-transaction-state-machine.md`;
> implementation plan `docs/history/plans/completed/2026-07-10-th-tx-view-phase-e.md` (Phase E).
> Cross-reference: PT-C-035 (payment-proceeds correction), PT-C-037 (OGR
> event-level application), CRG-019 (post-Phase-E identification notes).
