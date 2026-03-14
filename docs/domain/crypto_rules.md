# Portugal Crypto Tax Rules (IRS / Modelo 3)

Domain knowledge for generating the crypto capital gains section of the tax report.
Consult this document before changing any crypto reporting logic.

Each rule carries a source reference and the date of the source document so outdated
rules can be identified when the law changes.

**Source authority levels:**
- `[OFFICIAL]` — direct text from AT (Autoridade Tributária) or DRE (Diário da República)
- `[SECONDARY]` — from reputable Portuguese tax advisory sites; plausible but not authoritative

---

## Section 1 — Definitions

**PT-C-001** `[OFFICIAL | 2026-01-12]`
A criptoativo is "toda a representação digital de valor ou direitos que possa ser transferida
ou armazenada eletronicamente recorrendo à tecnologia de registo distribuído ou outra
semelhante" (CIRS art. 10 n.17). This includes Bitcoin, ETH, USDT, stablecoins,
and tokens of all kinds.
> Source: AT folheto "Criptoativos — Conceito fiscal e tributação", published 2026-01-12.

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

## Section 2 — Taxable Event (Alienação Onerosa)

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

## Section 3 — Capital Gains Calculation

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

## Section 4 — Holding Period and Exemption

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

## Section 5 — Tax Rates and Englobamento

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

## Section 6 — Losses

**PT-C-016** `[OFFICIAL | 2026-01-12]`
Capital losses (negative gain) from crypto disposals may be carried forward for **5 years**
and offset against future gains from the same category, but only if the taxpayer opts for
englobamento (CIRS art. 55 n.1 al.d).
> Source: AT folheto 2026-01-12.

**PT-C-017** `[OFFICIAL | 2026-01-12]`
Losses arising from transactions where the counterparty is in a **blacklisted jurisdiction**
(regime fiscal claramente mais favorável) are **not deductible** (CIRS art. 43 n.5).
> Source: AT folheto 2026-01-12.

---

## Section 7 — Declaration Forms

**PT-C-018** `[OFFICIAL | 2024-03-24]`
For **domestic-source** crypto (Portuguese exchanges): short-term disposals (<365 days)
go in **Anexo G, Quadro 18A**; long-term (≥365 days, exempt) in **Anexo G1, Quadro 7**.
> Source: Ofício Circulado 20269/2024, sections 8.8 and 9, dated 2024-03-24.

**PT-C-019** `[OFFICIAL | 2024-03-24]`
For **foreign-source** crypto (foreign exchanges such as Bybit, Kraken, Binance, Wirex):
disposals are declared in **Anexo J, Quadro 9.4** ("Alienação onerosa de criptoativos que
não constituam valores mobiliários").
> Source: Ofício Circulado 20269/2024, section 12.6, dated 2024-03-24.

**PT-C-020** `[OFFICIAL | 2024-03-24]`
**Required fields per line in Quadro 9.4 (Anexo J):**
- País da fonte (source country — country of the exchange)
- Data de realização (disposal date)
- Valor de realização (proceeds in EUR)
- Data de aquisição (acquisition date)
- Valor de aquisição (cost in EUR)
- Despesas e encargos (expenses and charges)
- Imposto pago no estrangeiro (foreign tax paid)
- País da contraparte (counterparty country)
- Opção pelo englobamento (opt into progressive taxation: yes/no)
> Source: Ofício Circulado 20269/2024, section 12.6, dated 2024-03-24.

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

## Section 8 — Reporting Obligations

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

## Section 9 — Practical Filing Guidance

**PT-C-025** `[SECONDARY | ~2025]`
Each disposal (alienação) should be reported as a separate line in the form
("uma linha por cada operação"). However, the AT circulars do not explicitly state this
for crypto. The "operation" is the **sale transaction**, not the individual FIFO lot allocation.
Multiple FIFO lots matched to the same sale event (same timestamp, same asset,
same wallet) can reasonably be reported as one aggregated line.
> Source: cryptobooks.tax/pt-PT (undated, consulted 2026-03-14); not found verbatim in official circulars.

**PT-C-026** `[SECONDARY | ~2025]`
The AT Portal das Finanças does **not support CSV or XML batch import** for Quadro 9.4.
Every line in Quadro 9.4 must be entered manually through the portal's web interface.
> Source: Research finding (2026-03-14); confirmed by absence of import feature in AT portal documentation.

---

## Section 10 — Implementation Decisions (this codebase)

These decisions are specific to this codebase and may be revised.

**PT-C-027** `[IMPLEMENTATION DECISION | 2026-03-14]`
The Crypto sheet aggregates FIFO lot rows by **(exact disposal timestamp, asset, wallet)**
before writing to Excel. This collapses multiple FIFO lot rows for the same real sale into
one line, consistent with PT-C-025.
Rationale: Koinly outputs one row per FIFO lot allocation; the "operação" for IRS purposes
is the sale transaction, not the lot.

**PT-C-028** `[IMPLEMENTATION DECISION | 2026-03-14]`
After timestamp-level aggregation, lines where **|gain/loss| < 1 EUR** are excluded from
the capital gains section of the Crypto sheet.
Rationale: these have no material tax impact (total excluded gain across the 2025 dataset
was ~6 EUR out of −1,452 EUR total). The AT portal requires manual entry of every line;
sub-1-EUR lines represent an impractical burden with no tax consequence.
This decision should be revisited if the dataset changes significantly.

**PT-C-029** `[IMPLEMENTATION DECISION | 2026-03-14]`
Negative gain lines (capital losses) are always retained regardless of the 1 EUR threshold,
because losses carry forward 5 years (PT-C-016) and have long-term tax value.
Only lines where |gain| < 1 EUR are excluded, which by definition means gain is between
−1 and +1 EUR.
> Note: Rule PT-C-028 already covers this — |gain| < 1 means the loss is also < 1 EUR in absolute value.
