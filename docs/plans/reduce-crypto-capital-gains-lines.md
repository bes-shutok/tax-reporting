# Plan: Reduce Koinly Capital Gains Lines for Portuguese IRS

## Problem

The Koinly capital gains CSV (`koinly_2025_capital_gains_report_*.csv`) has 3,075 rows.
After existing zero-value filtering, **1,557 lines** appear in the Crypto sheet.
Each line must be entered manually into AT's Portal das Finanças (Modelo 3), making this unmanageable.

**Root cause:** Koinly outputs one row per FIFO lot allocation, not one row per sale event.
Example: selling USDT on 13/01/2025 at 13:01 on ByBit generates **103 separate rows** (one per historical lot acquired), all with gain = 0.

---

## Portuguese IRS Legal Constraints (verified from official documents — see `docs/domain/crypto_rules.md`)

Sources: `at_oficio_circulado_20269_2024.pdf`, `at_oficio_circulado_20278_2025.pdf`, `at_folheto_criptoativos_2026-01-12.pdf` (all read via pdftotext after installing poppler).

### Form used: Anexo J, Quadro 9.4 (foreign-source crypto disposals)

Since all crypto exchanges are foreign operators, disposals are declared in **Anexo J, Quadro 9.4** ("Alienação onerosa de criptoativos que não constituam valores mobiliários" — disposal of crypto that is not a security, from foreign sources).

**Required fields per line** (from Ofício Circulado 20269/2024, section 12.6):
- País da fonte (source country)
- **Data de realização** (disposal date)
- Valor de realização (proceeds)
- **Data de aquisição** (acquisition date)
- Valor de aquisição (cost)
- Despesas e encargos (expenses)
- Imposto pago no estrangeiro (foreign tax paid)
- País da contraparte (counterparty country)
- Opção pelo englobamento (opt into progressive tax)

### Key law facts (from AT brochure, 2026-01-12)

- **FIFO is mandatory**: "Consideram-se alienados os criptoativos adquiridos há mais tempo — FIFO"
- **FIFO per wallet**: "quando os criptoativos estejam depositados em mais do que uma instituição financeira ou prestador de serviços, aplica-se a regra do FIFO a cada uma, individualmente"
- **Gains = valor de realização − valor de aquisição − despesas**
- **Losses reportable**: "pode reportar as restantes perdas apuradas nesta categoria... reportadas para os cinco anos seguintes"
- **Long-term exclusion**: crypto held ≥365 days → gains/losses excluded from tax → declared in Anexo G1 (not Anexo J)
- **No de minimis threshold** found in any of the official documents

### What the AT documents do NOT say

The circulars do **not** explicitly state "uma linha por cada operação" for crypto.
They do **not** explicitly prohibit aggregating multiple FIFO lots into one line.
They do **not** address the case where one sale generates 100+ FIFO lot allocations.

### Interpretation: "data de aquisição" is the constraint

Since the form requires **both** `data de realização` and `data de aquisição` per line, it is designed for lot-level reporting. However:
- The circulars only describe the **fields** introduced, not the cardinality rules
- The form's physical row limit (10–20 rows on the PDF) makes lot-level reporting impossible for active traders
- AT has not issued specific guidance on aggregation for crypto with many small lots

### The ambiguity: what is one "alienação"?

- **Strictest interpretation**: each FIFO lot matched to a sale = one alienação → 1,557 lines
- **Practical interpretation**: each sale transaction = one alienação, FIFO lot allocation is accounting method → aggregate by (disposal timestamp, asset, wallet) → **568 lines**
- **Common practice interpretation**: one line per asset per year per holding tier → **99 lines** (no official backing found, but likely common in practice)

---

## AT Portal Batch Import: Not Available

Research confirms: the AT Portal das Finanças **does not support CSV/XML import for Quadro 9.4**. Every entry must be typed manually. No direct Koinly → AT integration exists.

---

## Line Count Analysis

| Strategy | Lines | Notes |
|---|---|---|
| Current (zero-filter only) | 1,557 | Raw FIFO lot rows |
| Aggregate by (timestamp, asset, wallet) | 568 | One per actual sale event — defensible |
| + filter \|gain\| < 1 EUR | **94** | ✅ **Chosen approach** — see PT-C-027, PT-C-028 |
| + filter zero-gain only | 401 | Legally uncertain: all alienações must be declared |
| Aggregate by (date only, asset, wallet) | 287 | May conflate same-day separate transactions |
| Aggregate by (asset, holding_period, wallet) | 99 | One per year per asset — no official backing |

Breakdown for the 568 timestamp-level groups:
- Positive gain: 204
- Negative gain (losses): 197
- Zero gain (e.g. USDT dust): 167

After applying \|gain/loss\| < 1 EUR filter → **94 lines**:
- Positive gain: 32
- Negative gain (losses): 62
- Total excluded gain impact: ~6 EUR on −1,452 EUR total (negligible)

---

## Decision: Option A + 1 EUR filter → 94 lines

**Chosen approach** (decided 2026-03-14, documented as PT-C-027 and PT-C-028 in `docs/domain/crypto_rules.md`):

1. **Aggregate by (exact disposal timestamp, asset, wallet)** — one line per real sale event.
   Each line has an exact `data de realização` and earliest `data de aquisição` from the FIFO lots.
   Rationale: the "alienação" is the sale transaction; FIFO lot allocation is an accounting method (PT-C-025).

2. **Drop lines where \|gain/loss\| < 1 EUR** after aggregation.
   Rationale: no de minimis threshold exists in law (PT-C-024), but sub-1-EUR lines have zero material
   tax impact (~6 EUR total excluded) and AT portal requires manual entry for every line (PT-C-026).

3. **Always keep negative gain lines** regardless of the 1 EUR filter (PT-C-029).
   Losses carry forward 5 years (PT-C-016) and have long-term tax value.
   Note: the \|gain\| < 1 EUR filter already covers this — a loss < 1 EUR in absolute value is between −1 and 0.

Options B (date-level, 287 lines) and C (year-level, 99 lines) were considered but not chosen:
- Option B risks merging distinct same-day transactions.
- Option C lacks official backing for year-level aggregation and uses approximate dates.

---

## Implementation Plan

### File: `src/shares_reporting/application/crypto_reporting.py`

Add `_aggregate_capital_entries()` helper called at end of `_parse_capital_gains_file()`.

```python
def _aggregate_capital_entries(entries: list[CryptoCapitalGainEntry]) -> list[CryptoCapitalGainEntry]:
    """Aggregate FIFO lot rows into one line per sale event (same timestamp + asset + wallet).

    Rationale: the sale transaction is the reportable alienação in Portuguese IRS Quadro 9.4.
    FIFO lot allocation is an accounting method, not a separate disposal event (PT-C-025, PT-C-027).
    """
    groups: dict[tuple[str, str, str], list[CryptoCapitalGainEntry]] = {}
    for entry in entries:
        key = (entry.disposal_date, entry.asset, entry.wallet)   # exact timestamp
        groups.setdefault(key, []).append(entry)

    result = []
    for group in groups.values():
        first = group[0]
        result.append(CryptoCapitalGainEntry(
            disposal_date=first.disposal_date,
            acquisition_date=min(e.acquisition_date for e in group),  # earliest FIFO lot
            asset=first.asset,
            amount=sum(e.amount for e in group),
            cost_eur=sum(e.cost_eur for e in group),
            proceeds_eur=sum(e.proceeds_eur for e in group),
            gain_loss_eur=sum(e.gain_loss_eur for e in group),
            holding_period=first.holding_period,
            wallet=first.wallet,
            platform=first.platform,
            operator_origin=first.operator_origin,
            annex_hint=first.annex_hint,
            review_required=any(e.review_required for e in group),
            notes="; ".join(dict.fromkeys(e.notes for e in group if e.notes)),
        ))
    return result


_MATERIALITY_THRESHOLD = Decimal("1")

def _filter_immaterial_entries(entries: list[CryptoCapitalGainEntry]) -> list[CryptoCapitalGainEntry]:
    """Drop lines where |gain/loss| < 1 EUR after aggregation (PT-C-028).

    Sub-1-EUR lines have no material tax impact and AT portal requires manual entry per line.
    Negative gain lines with |gain| >= 1 EUR are always retained (PT-C-029, PT-C-016).
    """
    return [e for e in entries if abs(e.gain_loss_eur) >= _MATERIALITY_THRESHOLD]
```

Call both at the end of `_parse_capital_gains_file()`:
```python
capital_entries = _aggregate_capital_entries(capital_entries)
capital_entries = _filter_immaterial_entries(capital_entries)
```

### Tests (TDD — write tests before implementation)

`tests/unit/application/test_crypto_reporting.py`:
1. `test_aggregate_same_timestamp_collapses_to_one_row` — summed amounts, earliest acquisition date
2. `test_aggregate_different_timestamps_stay_separate`
3. `test_aggregate_different_assets_stay_separate`
4. `test_aggregate_different_wallets_stay_separate`
5. `test_aggregate_review_required_is_or_of_group`
6. `test_aggregate_notes_deduped_and_joined`
7. `test_aggregate_single_entry_unchanged`
8. Integration: `test_parse_capital_gains_file_aggregates_dust_rows` — 103-row CSV → 1 row

### Reconciliation label update (`persisting.py`)
Update the capital rows count label to clarify it reflects aggregated sale events, not raw FIFO lot count.

---

## Verification

```bash
uv run pytest tests/unit/application/test_crypto_reporting.py -v -k "aggregate"
uv run pytest
uv run shares-reporting
# Open resources/result/extract.xlsx → Crypto sheet
# Count Capital Gains rows → should be ~94 (32 positive + 62 negative)
# Verify: sum of Gain/Loss matches Koinly PDF total (approximately −1,452 EUR)
```
