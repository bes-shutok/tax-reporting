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

## 2. Recommended Koinly Settings for Portuguese Reporting

| Setting | Recommended value | Legal basis |
|---------|------------------|-------------|
| Realize gains on crypto-to-crypto trades? | **DISABLED** | CIRS art. 10(20): crypto-to-crypto is deferred |
| Realize gains on liquidity transactions? | **DISABLED** | LP operations are not taxable disposals |
| Realize gains on transfer fees? | **DISABLED** | Transfer fees are utility costs, not "alienações onerosas" (no consideration received). Koinly then adjusts cost basis of the transferred asset by the fee value, achieving the correct CIRS art. 10(4)(a) deductibility implicitly. |
| Treat transfer fees as deductible costs? | **N/A** (greyed out when above is OFF) | Koinly UI disables this option when "Realize gains on transfer fees?" is OFF. Fee deductibility is achieved via the cost-basis adjustment mechanism instead. |
| Cost basis method | **FIFO** | CIRS art. 43(8)(g): FIFO is mandatory |

---

## 3. Transfer Fees Treated as Taxable Disposal (Realized Gains)

### Portuguese position

Paying a transfer fee in crypto-assets to move your own tokens between wallets/exchanges is a utility expense, not an exchange or sale. It does not match the definition of a taxable event under Portuguese law:
- Under **CIRS art. 10(1)(k)**, capital gains are only triggered by *"alienação onerosa"* (onerous disposal).
- Onerous disposal requires an exchange where the taxpayer receives valuable consideration (such as fiat currency or other property).
- Paying a transfer fee to a platform or blockchain network results in no received consideration, so it is a non-taxable consumption/loss of crypto-assets.
- Treating this consumption as a taxable disposal is incorrect under Portuguese law and leads to "phantom gains" on transfer fees.
- Under **CIRS art. 10(4)(a)**, such fees are necessary expenses that should reduce taxable gains (by adjusting cost basis or as direct deductions), rather than triggering immediate capital gains.

### Koinly's treatment

If the portfolio setting `"Realize gains on transfer fees?"` is enabled (`ON`), Koinly treats each transfer fee as a taxable disposal of the fee token. If the fee token has appreciated since it was acquired, Koinly calculates a capital gain based on FIFO cost basis and includes it in the "Crypto Gains" report.

### Investigated Examples (FY2025 Data: 2025-02-02)

1. **JUP wallet-to-wallet transfer:** fee token had appreciated since acquisition; Koinly
   realized a short-term capital gain on the fee amount. Under DP-006, this is excluded.
2. **BTC wallet-to-wallet transfer:** fee token had a near-zero cost basis; Koinly
   realized a short-term capital gain equal to FMV of the fee. Under DP-006, this is excluded.

### Workarounds

- **Option A -- Disable "Realize gains on transfer fees?" in Koinly settings (Recommended):**
  Disabling this option prevents Koinly from realizing capital gains on transfer fees. Koinly will adjust the cost basis of the transferred asset by adding the fee value, treating it correctly as a non-taxable cost.
- **Option B -- Pipeline-Level Filter:**
  Exclude Koinly Capital Gains rows where the `Notes` field is `"Fee"` at the reporting pipeline level (custom Python code filter).

