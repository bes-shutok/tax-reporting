# Plan: Multi-Jurisdiction Futures/Derivatives Loss Treatment

Related decision point: DP-010 (futures/derivatives losses are taxable disposals, not withdrawals)
References: `docs/plans/completed/2026-06-07-futures-derivatives-loss-treatment.md` (prior incomplete investigation)
Plan review r1: docs/reviews/2026-06-09-plan-review-multi-jurisdiction-futures-derivatives-loss-treatment.md
Plan review r2: docs/reviews/2026-06-09-plan-review-multi-jurisdiction-futures-derivatives-loss-treatment-r2.md

## Terms

- **Other Gains Report (OGR):** Koinly report containing futures/derivatives P/L with Type="Loss" or Type="Profit" classifications
- **Capital Gains Report (CG):** Koinly report calculating gains based on collateral disposition (proceeds - cost)
- **Derivatives P/L:** The actual profit or loss from futures/derivatives positions, distinct from collateral gains

## Gist & Examples

**Problem:** The system currently processes only Koinly's Capital Gains Report, which calculates gains based on collateral disposition (proceeds - cost basis). This is correct for some jurisdictions (e.g., USA where collateral disposition is the taxable event) but incorrect for Portugal where the actual derivatives P/L from Other Gains Report should be used.

**Example discrepancy (Portugal 2025):**
- **Other Gains Report:** `<OGR timestamp>,USDT,"-<proceeds> EUR","<loss magnitude>",Loss,ByBit`
- **Capital Gains Report:** `<same OGR timestamp>,USDT,...,Gain / loss="<small positive value>",ByBit,Short term`
- **Current system output:** Shows a small positive gain (from CG collateral calculation)
- **Expected for Portugal:** Should show the larger OGR loss (from OGR Type="Loss")

**Why the mismatch:** Koinly's Capital Gains Report treats futures liquidations as collateral disposals (proceeds minus cost basis), which can show gains even when the actual derivatives position lost money. The Other Gains Report contains the correct economic P/L classification (Type="Loss" vs Type="Profit").

**What changes:**
1. Add jurisdiction-specific configuration for which gain source to use (CG vs OGR)
2. Parse Koinly's Other Gains Report when enabled
3. Apply OGR loss/profit overrides when Type="Loss" or Type="Profit"
4. Keep default behavior (CG-only) for jurisdictions where collateral taxation applies

**Edge cases:**
- When OGR is enabled but file is missing: log warning and fall back to CG
- When OGR and CG have overlapping entries: match by (date, asset, wallet) and override
- When OGR Type="Profit": override CG with OGR value (may be lower or higher)
- When OGR has no matching entry in CG: should not happen (Koinly generates both), but log warning

**Negative requirements:**
- Do NOT force OGR-based treatment on all countries (USA may require CG collateral gains)
- Do NOT break existing CG-only behavior for jurisdictions not configured for OGR
- Do NOT treat FEE token rows in OGR (Value=0.0 EUR) as capital gains

## Review Scope

Files directly changed as part of this plan. Review feedback is accepted **only** for the files listed here.
Any finding about a file not in this list must be rejected as out of scope.

**Production code — in scope:**
- `src/tax_reporting/domain/jurisdiction.py` *(add `use_other_gains_report` config field)*
- `src/tax_reporting/application/crypto_reporting.py` *(add OGR parsing and override logic)*
- `src/tax_reporting/infrastructure/koinly_parser.py` *(add OGR row parsing if needed)*

**Tests — in scope:**
- `tests/unit/application/test_crypto_reporting.py` *(add OGR override tests)*
- `tests/unit/application/persisting/test_crypto_gains_sheet.py` *(verify loss values in Excel)*
- `tests/unit/infrastructure/test_koinly_parser.py` *(add OGR parsing tests, if new parser code)*

**Documentation — scope-linked (not a closed file list):**
- `docs/domain/crypto_rules.md` *(add PT-C-033 for OGR-based treatment)*
- `docs/tax/decision_points/2025.md` *(add DP-011 for OGR configuration)*
- `docs/tax/decision_points/2025.toml` *(add `use_other_gains_report = true` for PT)*

**Out of scope — reject all review feedback:**
- FIFO matching engine (unrelated to gain source selection)
- IB capital gains logic (unrelated to crypto derivatives)
- Transaction History processing (already used for loan activity, unchanged)

## Review Findings

**Round 1:** `docs/reviews/2026-06-09-plan-review-multi-jurisdiction-futures-derivatives-loss-treatment.md` - CONDITIONAL PASS (4 blockers identified)

**Round 2:** `docs/reviews/2026-06-09-plan-review-multi-jurisdiction-futures-derivatives-loss-treatment-r2.md` - ✅ PASS (zero blockers, all fixes verified)

**Status:** READY FOR IMPLEMENTATION - All blockers fixed, zero blockers in round 2.

**Blockers applied:** See Fix sections in tasks below (marked with **🔴 BLOCKER FIX**).
**Mitigations applied:** See Mitigation sections in tasks below (marked with **🟡 MITIGATION**).

## Validation Commands

```bash
# Run crypto reporting tests
uv run pytest tests/unit/application/test_crypto_reporting.py -k "other_gains" -v

# Run crypto gains sheet tests
uv run pytest tests/unit/application/persisting/test_crypto_gains_sheet.py -v

# Run all crypto-related tests
uv run pytest tests/unit/application/test_crypto_reporting.py -v

# Verify code compiles
uv run python -m py_compile src/tax_reporting/domain/jurisdiction.py src/tax_reporting/application/crypto_reporting.py
```

### Task 1: Trace User's Specific Case Through Current System

Verify the actual bug by tracing data from source CSV through to Excel output. This is the data trace verification that was missing from the prior investigation.

Files:
- `resources/source/koinly2025/koinly_2025_other_gains_report_<ACCOUNT_TOKEN>.csv`
- `resources/source/koinly2025/koinly_2025_capital_gains_report_<ACCOUNT_TOKEN>.csv`
- `resources/result/extract.xlsx` *(current output)*

- [x] `grep "<OGR timestamp>.*USDT.*Loss,ByBit" koinly_2025_other_gains_report_<ACCOUNT_TOKEN>.csv` — given OGR file, expects row with `USDT,"-<proceeds> EUR","<loss magnitude>",Loss`
- [x] `grep "<OGR timestamp>.*USDT.*ByBit" koinly_2025_capital_gains_report_<ACCOUNT_TOKEN>.csv` — given CG file, expects matching row with positive gain
- [x] Open `extract.xlsx` Crypto Gains tab — given the matching USDT disposal, expects Gain/Loss value shown
- [x] Compare values — given OGR shows a Type="Loss" with larger magnitude and CG shows a smaller positive gain, expects Excel shows positive gain (current bug) not negative loss
- [x] Document findings in `docs/tmp/data_trace_verification_ogr_override.md` — confirm the bug and which entries are affected

**🔴 BLOCKER FIX 2.1:** Must create verification document before proceeding to Task 2. The document must include:
1. Actual OGR row showing the bug: `<OGR timestamp>,USDT,"-<proceeds>","<loss magnitude>",Loss,ByBit`
2. Corresponding CG rows that sum to the smaller positive gain
3. Current Excel output showing that smaller positive gain (demonstrates the bug)
4. Expected output after fix: the larger OGR loss

**Note:** This task confirms the bug exists before implementing the fix. Without completing the verification document with actual data, implementation should not proceed (verification-first principle per development_lessons.md #71).

### Task 2: Add Jurisdiction Configuration for OGR Treatment

Add a new boolean field to `TaxJurisdictionConfig` to control whether the jurisdiction uses Other Gains Report classifications.

Files:
- `src/tax_reporting/domain/jurisdiction.py`

- [x] `TaxJurisdictionTest#test_use_other_gains_report_field_exists` — given dataclass definition, expects `use_other_gains_report: bool` field exists with default `False`
- [x] Add field to dataclass — given `TaxJurisdictionConfig`, expects new field `use_other_gains_report: bool = False`
- [x] Run → expect RED: `uv run pytest tests/unit/domain/test_jurisdiction.py -k "use_other_gains" -v`
- [ ] Commit: `feat: add use_other_gains_report jurisdiction config field`

### Task 3: Parse Koinly Other Gains Report

Add parsing logic for Koinly's Other Gains Report CSV format.

Files:
- `src/tax_reporting/application/crypto_reporting.py`
- `src/tax_reporting/infrastructure/koinly_parser.py`

- [x] `KoinlyParserTest#test_parse_other_gains_row` — given OGR row `Date,Asset,Amount,Value (EUR),Type,Wallet`, expects returns parsed tuple with (date, asset, amount_eur, type, wallet)
- [x] `KoinlyParserTest#test_parse_other_gains_loss_type` — given row with `Type="Loss"`, expects type parsed as "Loss"
- [x] `KoinlyParserTest#test_parse_other_gains_profit_type` — given row with `Type="Profit"`, expects type parsed as "Profit"
- [x] `KoinlyParserTest#test_parse_other_gains_skips_fee_tokens` — given row with `Value="0.0"`, expects row is skipped (not capital gain)
- [x] Run → expect RED: `uv run pytest tests/unit/infrastructure/test_koinly_parser.py -k "other_gains" -v`
- [x] Add `_parse_other_gains_row` function to `koinly_parser.py`
- [x] Add `_find_and_parse_other_gains_file` function to locate and read OGR CSV

**🔴 BLOCKER FIX 2.3:** File discovery must follow existing pattern:
```python
other_gains_file = _find_report_file(koinly_dir, "other_gains_report")
if other_gains_file is None:
    if jurisdiction and jurisdiction.use_other_gains_report:
        logger.warning("OGR enabled but no file found in %s", koinly_dir)
    return {}
```
File pattern: `*other_gains_report*.csv` (matches `koinly_2025_other_gains_report_*.csv`)

**🔴 BLOCKER FIX 2.2:** OGR value extraction must use Value field, not Amount:
```python
def _extract_ogr_gain_loss(ogr_row: dict) -> Decimal | None:
    """Extract gain/loss value from OGR row based on Type field.

    OGR format: Date,Asset,Amount,Value (EUR),Type,Wallet Name
    - Amount is negative for Loss (quantity, not EUR)
    - Value (EUR) is positive magnitude for both Loss and Profit
    - Type indicates direction: "Loss" = negative, "Profit" = positive

    Returns: Negative Decimal for Loss, positive for Profit, None for invalid.
    """
    value_str = ogr_row["Value (EUR)"]
    value_eur = parse_koinly_decimal(value_str)
    row_type = ogr_row["Type"].strip().lower()

    if row_type == "loss":
        return -value_eur
    elif row_type == "profit":
        return value_eur
    else:
        logger.warning("Unknown OGR Type '%s', skipping override", ogr_row["Type"])
        return None
```

**🟡 MITIGATION 3.3:** Handle case-insensitive Type matching (e.g., "loss", "LOSS", "Loss").

- [x] Run → expect GREEN
- [x] Commit: `feat: add Koinly Other Gains Report parsing`

### Task 4: Build OGR Entry Index for Override Lookup

Create an in-memory index from parsed OGR rows for efficient (date, asset, wallet) lookup.

Files:
- `src/tax_reporting/application/crypto_reporting.py`

- [ ] `CryptoReportingTest#test_build_ogr_index` — given parsed OGR rows with date, asset, wallet, expects index keyed by (date, asset, wallet)
- [ ] `CryptoReportingTest#test_ogr_index_lookup_by_key` — given index with entry (2025-01-13, USDT, ByBit), expects lookup returns matching OGR value and type
- [ ] `CryptoReportingTest#test_ogr_index_missing_key` — given index and non-matching key, expects returns None
- [ ] Run → expect RED: `uv run pytest tests/unit/application/test_crypto_reporting.py -k "ogr_index" -v`
- [ ] Add `_build_ogr_index(parsed_ogr_rows)` function returning dict[(date, asset, wallet), (value_eur, type)]

**🔴 BLOCKER FIX 2.4:** Matching key must use date-only (strip time) and normalized values:
```python
def _build_ogr_index(ogr_rows: list[dict]) -> dict[tuple[str, str, str], Decimal]:
    """Build index for efficient CG entry lookup.

    Key: (date_only, asset_normalized, wallet_normalized)
    - date_only: ISO format YYYY-MM-DD (time stripped from Date field)
    - asset_normalized: Via normalize_asset_ticker()
    - wallet_normalized: Via normalize_platform_name()
    Value: gain/loss EUR (negative for Loss, positive for Profit)
    """
    index = {}
    for row in ogr_rows:
        date_str = parse_koinly_datetime(row["Date"])
        date_only = format_datetime(date_str)  # YYYY-MM-DD, time stripped
        asset = normalize_asset_ticker(row["Asset"])
        wallet = normalize_platform_name(row["Wallet Name"])
        gain_loss = _extract_ogr_gain_loss(row)

        if gain_loss is not None:
            index[(date_only, asset, wallet)] = gain_loss
    return index
```

**🟡 MITIGATION 3.1:** Add count validation after override to detect mismatched entries:
```python
matched_count = sum(1 for e in capital_entries if _ogr_key(e) in ogr_index)
unmatched_count = len(capital_entries) - matched_count
if unmatched_count > len(capital_entries) * 0.1:
    logger.warning("OGR override: %d of %d CG entries unmatched (%.1f%%)",
                  unmatched_count, len(capital_entries),
                  100 * unmatched_count / len(capital_entries))
```

- [ ] Run → expect GREEN
- [ ] Commit: `feat: build OGR entry index for override lookup`

### Task 5: Apply OGR Overrides to Capital Gains Entries

When jurisdiction enables `use_other_gains_report`, override CG gain/loss values with OGR classifications.

Files:
- `src/tax_reporting/application/crypto_reporting.py`

- [x] `CryptoReportingTest#test_ogr_loss_override_applied` — given CG entry with a smaller positive gain and OGR index with Type="Loss" of larger magnitude, expects entry gain/loss set to the OGR loss value
- [x] `CryptoReportingTest#test_ogr_profit_override_applied` — given CG entry with gain=+100 EUR and OGR index with Type="Profit", value=+80 EUR, expects entry gain/loss set to +80 EUR
- [x] `CryptoReportingTest#test_ogr_no_override_when_disabled` — given jurisdiction with `use_other_gains_report=False`, expects CG values unchanged regardless of OGR
- [x] `CryptoReportingTest#test_ogr_no_override_when_no_match` — given CG entry with no OGR match, expects CG value unchanged with warning log
- [x] `CryptoReportingTest#test_ogr_skips_fee_tokens` — given OGR entry with Value=0.0, expects override not applied (fee tokens are not capital gains)
- [x] Run → expect RED: `uv run pytest tests/unit/application/test_crypto_reporting.py -k "ogr_override" -v`
- [x] Add `_apply_ogr_overrides(capital_entries, ogr_index, jurisdiction)` function

**🟡 MITIGATION 3.2:** Override must happen BEFORE aggregation. Document explicitly:
```python
# CRITICAL: OGR override must happen BEFORE _aggregate_capital_entries
# because CG rows are individual FIFO lots that get summed in aggregation.
# OGR contains the correct total gain/loss for the disposal event.
# Overriding after aggregation would lose the lot-level trail.

if jurisdiction and jurisdiction.use_other_gains_report:
    ogr_index = _build_ogr_index(parsed_ogr_rows)
    capital_entries = _apply_ogr_overrides(capital_entries, ogr_index, jurisdiction)

capital_entries = _aggregate_capital_entries(capital_entries)
```

- [x] Call override function after `_parse_capital_gains_file` when `jurisdiction.use_other_gains_report=True`
- [x] Run → expect GREEN
- [x] Commit: `feat: apply OGR overrides to capital gains entries`

### Task 6: Verify Loss Values in Excel Output

Ensure that OGR-overridden losses appear as negative values in the Excel report.

Files:
- `tests/unit/application/persisting/test_crypto_gains_sheet.py`

- [x] `CryptoGainsSheetTest#test_loss_value_written_to_excel` — given entry with a negative gain_loss_eur, expects cell contains negative value (not absolute)
- [x] `CryptoGainsSheetTest#test_ogr_override_reflected_in_excel` — given PT jurisdiction with OGR overrides, expects the overridden disposal entry shows the OGR loss value (not the smaller CG gain)
- [x] Run → expect RED: `uv run pytest tests/unit/application/persisting/test_crypto_gains_sheet.py -k "loss" -v`
- [x] Verify existing Excel write code preserves negative sign (no change needed, just confirm)
- [x] Run → expect GREEN
- [x] Commit: `test: verify Excel loss values after OGR override`

### Task 7: Update Documentation and Configuration

Add Portugal-specific configuration and document the new behavior.

Files:
- `docs/tax/decision_points/2025.toml`
- `docs/tax/decision_points/2025.md`
- `docs/domain/crypto_rules.md`

- [x] Add `use_other_gains_report = true` to `[countries.PT]` in `2025.toml`
- [x] Add DP-011 to `2025.md` explaining OGR-based treatment for PT

**🔴 BLOCKER FIX 1.6.1:** DP-011 must include:
1. **Legal basis** (CIRS article reference for derivatives)
2. **Scope** (which derivatives types: futures, options, swaps)
3. **Effective date** (when this treatment applies)
4. **Interaction with DP-010** (how they relate: DP-010 says losses are taxable, DP-011 says use OGR values)
5. **When OGR overrides CG** (futures/derivatives with Type="Loss" or Type="Profit")

**🔴 BLOCKER FIX 1.6.2:** PT-C-033 must include:
- **Source authority level** ([OFFICIAL] or [SECONDARY])
- **Source date** (when the source was issued)
- **Reference to official document** (AT folheto, CIRS article)

- [x] Add PT-C-033 to `crypto_rules.md` with rule text and OGR reference
- [x] Run validation — given config files updated, expects `TaxJurisdictionConfig` loads without error and has `use_other_gains_report=True` for PT
- [x] Commit: `docs: add Portugal OGR configuration and PT-C-033`

### Task 8: Final Validation

Run full test suite and verify the fix with actual data.

- [x] Run all crypto tests — given implementation complete, expects `uv run pytest tests/unit/application/test_crypto_reporting.py -v` passes
- [x] Run full test suite — given all changes, expects `uv run pytest` passes
- [x] Manual verification with real data — given Koinly exports with futures losses, expects Excel shows losses as negative values for PT
- [x] Document final verification in `docs/tmp/futures_loss_fix_verification.md` — confirm the bug is fixed
