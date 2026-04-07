# Tax Reporting Tool: Project Walkthrough

This document is a slide-deck-style walkthrough of what this project does, why it exists, and what it produces.

---

## Glossary

- AT: `Autoridade Tributária e Aduaneira`, the Portuguese tax authority.
- IRS: Portuguese personal income tax.
- Modelo 3: the main Portuguese annual personal income tax return.
- Anexo: a schedule attached to Modelo 3.
- Quadro: a table or section inside an annex.
- Koinly: a crypto tax platform that imports transaction data and produces tax reports.
- FIFO: `first in, first out`, the rule that treats the oldest purchased units as sold first.
- Source country (`País da Fonte`): the country that Portuguese tax rules treat as the origin of the income or disposal.
- Holding period: how long the asset was held between purchase and sale.
- CEX: centralized exchange, such as Bybit or Kraken.
- DEX: decentralized exchange.
- DeFi: decentralized finance.
- Taxable now: income that is taxed when received.
- Deferred by law: income that is not taxed when received and is taxed later, usually when the asset is sold.

---

## Slide 1: Problem Statement

Crypto tax platforms like Koinly collect transaction history from exchanges, wallets, and services; compute cost basis and gains; classify income; and export generic capital-gains and income reports. But for a Portuguese taxpayer those exports are still not filing-ready for Modelo 3.

Even a mostly passive crypto user can end up with hundreds of yearly lines once daily staking, earn, or referral rewards are included. An active investor using several CEXs, DEXs, and DeFi protocols can easily reach tens of thousands of lines. A single CEX account such as Bybit can already generate daily reward rows for each staked asset.

A Koinly capital-gains export for one tax year can contain 900+ FIFO rows for just a handful of actual sale events. Each row describes one matched part of a sale, not a separate reportable sale. Koinly and similar tools often already calculate the hard part: gain or loss for each disposal and, where relevant, the holding-period split. The Portuguese bottleneck is different: the taxpayer still needs to turn this generic export detail into lines that can be entered into the right Modelo 3 annex, determine the `País da Fonte` for each line under Portuguese rules, and prepare the result for manual entry.

Demo asset: `resources/source/example/koinly2024/koinly_2024_capital_gains_report_xY9kLm2pQr_1700000000.csv` -- 900 rows of synthetic FIFO-lot data representing 4 actual disposals.

---

## Slide 2: Why This Repo Exists

This project turns detailed export data into a Portuguese tax-reporting summary while preserving the legal details that matter.

Specifically:

- The repo is a Portugal-specific layer on top of generic crypto tax exports. It does not replace Koinly's import, matching, or gain-calculation engine; it prepares the output for Portuguese reporting.
- The project is grounded in current official sources and professional guidance. Those materials are mirrored in the repo, tracked in source manifests, and re-checked before they are used in analysis or implementation.
- Koinly FIFO rows are combined into one line per sale event, grouped by disposal timestamp, asset, platform, and holding period. The current implementation groups at Koinly's minute-level timestamp precision. The official Anexo J Quadro 9.4 form only has Ano/Mês/Dia date columns -- no time-of-day field exists -- so day-level grouping would also be legally correct and would produce fewer lines (PT-C-020). Coarser grouping (per month, per year) is not acceptable.
- Crypto rewards are classified as taxable now when paid in fiat money and deferred by law when paid in crypto, under CIRS article 5(11), and then grouped by income code and source country for Anexo J Quadro 8A.
- `País da Fonte` is determined using Portuguese source-country rules tied to the operator or paying entity, because generic aggregators usually provide wallet or platform labels but not the country attribution needed for the tax return.
- Sub-1-EUR lines are filtered out because they have no material tax impact and the AT portal requires manual entry per line.
- Holding period is preserved in the output because short-term taxable disposals and `>=365`-day excluded disposals have different Portuguese treatment and may belong in different annexes.
- The LLM instruction set is part of the architecture. Before crypto logic is changed, it directs the implementation flow back through the domain rule files, implementation guidelines, and source manifests. This helps the project stay legally grounded while still supporting robust and fast-paced implementation.

The result: 900 raw capital-gains rows become 4 reporting lines. 160 raw reward rows are classified and either grouped into a filing summary or documented as deferred.

Demo asset: run `uv run pytest tests/end_to_end/test_example_report_generation.py -v` to see this compression in action.

---

## Slide 3: Legal and Reporting Basis

The legal and reporting basis has two layers: explicit official rules, and a practical reporting transformation derived from those rules.

Official sources say:

- CIRS (Codigo do IRS), consolidated through Lei n. 75/2024: defines the taxable event for cryptoassets (art. 5, nos. 10-12), the 365-day holding exemption (art. 10, no. 6), loss carry-forward rules, and the deferral mechanism for crypto-denominated remuneration (art. 5, no. 11).
  - Official source: `docs/tax/portugal-crypto-tax/official/cirs_2025-07_code_consolidated.pdf`

- AT (Autoridade Tributaria e Aduaneira) informational booklet on criptoativos, issued 2026-01-12: confirms FIFO methodology, per-wallet FIFO application, and the reporting obligations for crypto-asset service providers.
  - Official source: `docs/tax/portugal-crypto-tax/official/at_folheto_criptoativos_2026-01-12.pdf`

- AT Oficio Circulado 20269/2024 and the official Anexo J instructions define the shape of each reporting line in Quadro 9.4: source country, disposal date and value, acquisition date and value, expenses, foreign tax, counterparty country, and englobamento option. The date fields are Ano, Mês, Dia (day precision only); the form has no time-of-day columns.
  - Official source: `docs/tax/portugal-crypto-tax/official/at_oficio_circulado_20269_2024.pdf`
  - Official source: `docs/tax/portugal-crypto-tax/official/modelo3_anexo_j_2025.pdf`

- AT Oficio Circulado 20278/2025: provides the updated Modelo 3 filing guidance for the following filing cycle.
  - Official source: `docs/tax/portugal-crypto-tax/official/at_oficio_circulado_20278_2025.pdf`

- Portaria 104/2026: defines the Modelo 3 annex structure including Anexo G1, Anexo J, and Anexo G updates.
  - Official source: `docs/tax/portugal-crypto-tax/official/dre_portaria_104_2026.pdf`

Practical reading used by this repo:

- The official texts do not literally say "aggregate Koinly FIFO rows by disposal date". What they do say is that the taxable moment is the `alienação onerosa`, and that each Quadro 9.4 line is structured around one disposal's sale and purchase fields. The official form confirms that dates are Ano/Mês/Dia with no time-of-day columns (modelo3_anexo_j_2025.pdf, approved by Portaria 104/2026). The repo currently groups at Koinly's minute-level precision; the form cannot represent that level of detail, so day-level grouping would be a valid simplification that reduces line count while staying within what the law requires.
- A Portuguese practitioner guide makes the practical reading explicit: each Quadro 9.4 line corresponds to a distinct event or gain. The repo follows that interpretation and treats multiple FIFO rows belonging to the same disposal as supporting detail for one reporting line.
  - Practitioner guidance: `https://cryptobooks.tax/pt-PT/blog/declarar-criptoativos-anexo-j-modelo-3`
- The repo still preserves holding-period splits inside the same disposal date because that distinction changes the Portuguese tax treatment and annex placement.

Important distinction: where the official source clearly defines a tax rule, such as FIFO, disposal-date reporting fields, or the 365-day exclusion, the repo implements it directly. Where the repo applies a reporting simplification, such as collapsing many FIFO rows into one disposal line or filtering sub-1-EUR amounts, that is a repository design choice built on those legal dimensions, not a verbatim AT instruction. Each design decision is tagged with an authority level in `docs/domain/crypto_rules.md` ([OFFICIAL], [SECONDARY], or [IMPLEMENTATION DECISION]). This is also reinforced by the repo instructions, which require developers and agents to consult the crypto rule files and source manifests before changing crypto-reporting logic.

---

## Slide 4: Capital Gains Example -- Short-Term Taxable Case

Before: 350 raw FIFO-lot rows for BTC sold on Kraken on 15/03/2024.

Each row describes one small matched part of the sale: 0.00001 BTC acquired at a slightly different cost, sold for 0.05 EUR gain. The raw CSV looks like:

```
Date Sold: 15/03/2024, Date Acquired: 10/01/2024, Asset: BTC, Amount: 0.00001000, Cost: 0.10 EUR, Proceeds: 0.15 EUR, Gain/loss: 0.05 EUR
Date Sold: 15/03/2024, Date Acquired: 11/01/2024, Asset: BTC, Amount: 0.00001000, Cost: 0.10 EUR, Proceeds: 0.15 EUR, Gain/loss: 0.05 EUR
... (350 rows)
```

After: one aggregated line.

```
Disposal: 15/03/2024 | BTC | Kraken | Short term | Amount: 0.00350000 | Cost: 35.00 EUR | Proceeds: 52.50 EUR | Gain: 17.50 EUR
```

This single line is what goes on Anexo J Quadro 9.4 for foreign-source capital gains. The aggregation collapses the 350 FIFO rows into one reporting row. The official form only has Ano/Mês/Dia date columns (modelo3_anexo_j_2025.pdf), so the form cannot distinguish same-day disposals at different times -- the current minute-level grouping in the code may produce more rows than the form can represent, and day-level aggregation would be a valid simplification. The underlying detail remains in the Koinly CSV source file for auditability.

Source: `resources/source/example/koinly2024/koinly_2024_capital_gains_report_xY9kLm2pQr_1700000000.csv` (rows 1-350).

---

## Slide 5: Capital Gains Example -- Long-Term Exempt Case

Before: 150 raw FIFO-lot rows for SOL sold on Kraken on 10/11/2024, held for more than 365 days.

```
Date Sold: 10/11/2024, Date Acquired: 01/06/2023, Asset: SOL, Amount: 0.50000, Cost: 4.00 EUR, Proceeds: 5.00 EUR, Gain/loss: 1.00 EUR
... (150 rows)
```

After: one aggregated line with holding period = Long term.

```
Disposal: 10/11/2024 | SOL | Kraken | Long term | Amount: 75.00000 | Cost: 600.00 EUR | Proceeds: 750.00 EUR | Gain: 150.00 EUR -> EXEMPT
```

Under CIRS art. 10, no. 6, gains on cryptoassets held for more than 365 days are exempt from IRS. This line goes to Anexo G1 rather than Anexo J. The repo preserves the holding period in the grouping key so short-term and long-term gains for the same asset on the same day are never merged.

Legal basis: CIRS art. 10, no. 6. Official source: `docs/tax/portugal-crypto-tax/official/cirs_2025-07_code_consolidated.pdf`. The 365-day threshold is an explicit statutory rule.

---

## Slide 6: Rewards Example -- Taxable Now vs. Deferred by Law

The 160 synthetic reward rows split into two categories:

Taxable now (10 rows -- EUR referral rewards from Kraken):

Ten EUR-denominated referral rewards are immediately taxable as Category E income under CIRS art. 5(11) because the remuneration is not in the form of cryptoassets, so the deferral rule does not apply. These rows are grouped by income code from Tabela V and source country from Tabela X into a single summary line for Anexo J Quadro 8A: income code 401, country IE, 30.00 EUR gross.

Deferred by law (150 rows):

All SOL staking rewards, ETH rewards, and ADA airdrops are denominated in cryptoassets. Under CIRS art. 5(11), remuneration received in the form of cryptoassets is not taxed at receipt; taxation is deferred until the taxpayer disposes of the assets. These 150 crypto-denominated rows appear in the "Deferred by Law - Support Detail" section of the Excel workbook for auditability but produce zero reporting lines for immediate filing.

This classification is the default for crypto-denominated income. The code only classifies a reward as taxable now when it can positively identify a fiat-denominated payment (CRG-001, CRG-002 in `docs/domain/crypto_reporting_guidelines.md`).

Legal basis: CIRS art. 5(11). Official source: `docs/tax/portugal-crypto-tax/official/cirs_2025-07_code_consolidated.pdf`. AT PIV 22065 (2023-11-06) confirms the deferral mechanism.

---

## Slide 7: Operational Value -- Safe Examples, Reproducibility, Audit Trail

Another core achievement of the project is its development method: implementation is tied directly to current official sources, professional guidance, and explicit LLM instructions about what must be checked before code is changed. That combination supports fast delivery without drifting away from the legal and filing basis.

Safe examples: The repository ships fully synthetic example data under `resources/source/example/`. All wallets, exchanges, transaction hashes, and account identifiers are obviously fake (e.g., "Example Kraken Wallet", "Example Binance Wallet"). A fresh clone can exercise every major feature without private files.

Reproducibility: Running `uv run pytest tests/end_to_end/test_example_report_generation.py -v` generates a complete Excel report from the example inputs and verifies that:

- 900+ raw crypto capital-gains rows aggregate to at most 5 reporting lines
- 160 raw reward rows are classified (10 taxable now, 150 deferred) and aggregated or documented
- All report sections (shares capital gains, dividends, crypto gains, crypto rewards, reconciliation) are present and non-empty

Audit trail: The Excel workbook preserves the aggregated capital-gains summary and the full deferred-by-law reward detail for auditability. Every aggregated capital-gains line corresponds to a set of FIFO rows that can be traced in the Koinly CSV source. Every reward classification cites the applicable rule (CRG-001 or CRG-002). The source country for each operator is resolved from archived origin documents under `docs/tax/crypto-origin/`, not guessed.

Demo assets:
- Example inputs: `resources/source/example/`
- Expected output: `resources/result/example/extract.xlsx`
- E2E tests: `tests/end_to_end/test_example_report_generation.py`

---

## Slide 8: Recommended Next Steps

1. Token origin matching: The current "Token origin" column is intentionally blank because the removed legacy heuristic (same-day disposal matching) was unreliable. A Koinly-first implementation using deterministic acquisition-side fields from the Koinly transaction history is planned -- see the follow-up plan referenced in `docs/plans/`.

2. More asset types: The current IB pipeline handles shares and dividends. Futures, options, and fixed income are on the roadmap.

3. Broader source support: The architecture is designed to accommodate additional data sources, including Binance, Coinbase, and DeFi protocols, alongside the current Koinly integration.

4. Presentation evolution: This Markdown document can be converted into formal slides (reveal.js, Google Slides, or LaTeX Beamer) when the project is ready for external audiences.
