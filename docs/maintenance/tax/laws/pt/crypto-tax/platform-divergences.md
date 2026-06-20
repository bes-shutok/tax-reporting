# Platform Divergences from Portuguese Crypto Tax Law

Documents where common crypto tax platforms produce results that diverge from Portuguese tax law (CIRS art. 10, AT Folheto "Criptoativos" 2026-01-12).

Portuguese law defines a narrow taxable event: only "efetiva alienacao onerosa em dinheiro ou em especie (exceto criptoativos)" triggers capital gains (CIRS art. 10(20)). Many platforms default to broader disposal definitions that are correct for US/UK/AU/DE but over-report for Portuguese filers.

---

## 1. DeFi Loan Repayment Treated as Taxable Disposal

### Portuguese position

Loan repayment is returning borrowed property, not a sale. It does not match any taxable event under CIRS art. 10:

- Not "alienacao onerosa em dinheiro" (no fiat received)
- Not "alienacao onerosa em especie (exceto criptoativos)" (not exchanged for goods/services)
- Not deemed disposal on emigration (CIRS art. 10(22))

No official AT ruling (PIV, oficio circulado) addresses DeFi loans specifically, but the law is narrowly drafted and loan repayment falls outside the taxable scope by plain text.

### Koinly's treatment

Koinly treats `crypto_withdrawal` with tag `Loan repayment` as a taxable disposal equivalent to selling the crypto to a third party. Per Koinly's help center:

> "Repayment of a crypto loan in Koinly is equivalent to a disposal (selling crypto to a 3rd party) -- as such, it should appear as a withdrawal from your wallet."
> -- [Crypto loans, repayments and collateral](https://support.koinly.io/en/articles/9490026)

The `Loan repayment` tag is purely cosmetic and does not change this behavior:

> "Loan repayment, Margin repayment -- These tags do not change the behavior of the transaction (it remains a disposal)."
> -- [What are Tags](https://support.koinly.io/en/articles/9490023)

This is the **correct treatment for most major jurisdictions** where Koinly operates:

| Jurisdiction | Loan repayment = disposal? |
|---|---|
| US (IRS) | YES |
| UK (HMRC) | YES |
| Australia (ATO) | YES |
| Germany | YES (holdings < 1 year) |
| **Portugal (CIRS art. 10(20))** | **NO** |

Koinly has not built jurisdiction-specific logic for Portugal's unique crypto-to-crypto deferral rule. The `"Realize gains on crypto-to-crypto trades?"` setting only controls `exchange` type transactions, not `crypto_withdrawal`.

### Workarounds

**Option A -- Change worth to match cost basis** (recommended by Koinly support):

Edit each loan repayment transaction in Koinly, click "Change worth", set the worth equal to the cost basis. This zeros out the gain while keeping the transaction as a "disposal."

> Source: [Koinly community discussion](https://discuss.koinly.io/t/loan-repayment-isnt-a-profit-how-to-treat/19201)

**Option B -- Change type to Transfer:**

Edit the withdrawal, change type from "Withdrawal" to "Transfer", select a custom wallet as receiving wallet. Requires creating a custom wallet marked as "your own" for the lending protocol. Transfers between your own wallets are always tax-free in Koinly.

> Source: [How Koinly handles transfers](https://support.koinly.io/en/articles/9490024)

**Option C -- Filter in processing pipeline:**

Exclude loan repayment capital gains at the code level. See `../../../../plans/completed/2026-05-25-filter-loan-repayment-gains.md`.

### Scope of the issue in 2025 data

19 loan repayment transactions across SUI (10), WBTC (5), LBTC (4). Total phantom gain/loss impact: approximately -6,120 EUR. For the repeatable audit methodology, see `docs/maintenance/loan_repayment_audit_methodology.md`.

---

## 2. Required Koinly Settings for Portuguese Reporting

| Setting | Required value | Legal basis |
|---------|---------------|-------------|
| Realize gains on crypto-to-crypto trades? | **DISABLED** | CIRS art. 10(20): crypto-to-crypto is deferred |
| Realize gains on liquidity transactions? | **DISABLED** | LP operations are not taxable disposals |
| Realize gains on transfer fees? | **ENABLED** | Gas fees dispose of crypto with no consideration |
| Treat transfer fees as deductible costs? | **ENABLED** | Allows gas fee deduction |
| Cost basis method | **FIFO** | CIRS art. 43(8)(g): FIFO is mandatory |
