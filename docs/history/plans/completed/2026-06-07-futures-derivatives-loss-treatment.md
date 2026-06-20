# Plan: Futures Derivatives Loss Treatment for Portugal 2025

Related decision point: DP-010 (futures/derivatives losses are taxable disposals, not withdrawals)
Plan review: the local review record

## Gist & Examples

**Problem:** The current system may not explicitly handle negative Realized P&L (losses) from crypto futures and derivatives in a country-specific manner. For Portugal, losses should be treated as deductible capital losses (not as withdrawals or pure profit), while other countries (e.g., USA) may have different treatment.

**Example scenario:** A ByBit futures liquidation on 19 Jan 2025 shows:
- ByBit reports: -273.86 USDT (loss)
- Koinly reports: -42.26 USD (loss)
- Current system shows: disposal of 280.36 USDT (271.79 EUR) as proceeds

The user observes that negative Realized P&L might be treated incorrectly. Under Portuguese law:
- CIRS art. 10(1)(e) covers "instrumentos financeiros derivados" (derivatives)
- Liquidations are alienação onerosa (taxable disposals)
- Losses can be carried forward 5 years if short-term (<365 days)
- Both gains AND losses are excluded if long-term (≥365 days)

**What changes:**
1. Add explicit validation that negative `gain_loss_eur` values are preserved and treated as losses for PT
2. Add country-specific configuration for derivatives loss treatment
3. Verify all relevant PT tax documents are properly archived and referenced
4. Add tests to verify negative gain handling per country

**Edge cases:**
- Negative `gain_loss_eur` must NOT be converted to absolute values
- Aggregation sums must preserve sign (sum of negatives = negative total)
- Zero-basis entries with negative gains should be flagged for review

**Negative requirements:**
- Do NOT treat negative gains as withdrawals
- Do NOT convert negative gains to positive values
- Do NOT apply PT-specific loss treatment to other countries without explicit configuration

## Review Scope

Files directly changed as part of this plan. Review feedback is accepted **only** for the files listed here.
Any finding about a file not in this list must be rejected as out of scope.

**Production code; in scope:**
- `src/tax_reporting/domain/jurisdiction.py` *(add derivatives_loss_treatment config field)*
- `src/tax_reporting/application/crypto_reporting.py` *(add country-specific loss handling if needed)*

**Tests; in scope:**
- `tests/unit/application/test_crypto_reporting.py` *(add tests for negative gain handling)*
- `tests/unit/application/persisting/test_crypto_gains_sheet.py` *(verify negative gains written correctly)*

**Documentation; scope-linked (not a closed file list):**
- `docs/domain/crypto_rules.md` *(PT-C-031, PT-C-032 already added)*
- `docs/tax/decision_points/2025.md` *(DP-010 already added)*
- `docs/tax/decision_points/2025.toml` *(futures_derivatives_taxable already added)*
- `docs/tax/laws/pt/crypto-tax/sources.md` *(verify all sources referenced)*

**Out of scope; reject all review feedback:**
- Koinly CSV parsing logic (already handles negatives correctly)
- FIFO matching engine (not related to loss treatment)
- IB capital gains logic (unrelated to crypto derivatives)
- Processing Koinly Other Gains Report (Task 7 is investigation only; no code changes planned unless findings reveal requirement)

## Validation Commands

```bash
# Run crypto reporting tests
uv run pytest tests/unit/application/test_crypto_reporting.py -k "loss" -v

# Run crypto gains sheet tests
uv run pytest tests/unit/application/persisting/test_crypto_gains_sheet.py -v

# Run all crypto-related tests
uv run pytest tests/unit/application/test_crypto_reporting.py -v

# Verify code compiles
uv run python -m py_compile src/tax_reporting/domain/jurisdiction.py src/tax_reporting/application/crypto_reporting.py
```

### Task 1: Verify Current Negative Gain Handling

Investigate how the current system handles negative `gain_loss_eur` values to determine if code changes are actually needed, or if the issue is purely documentation/verification.

Files:
- `src/tax_reporting/application/crypto_reporting.py`
- `src/tax_reporting/application/persisting/crypto_gains_sheet.py`

- [x] Review `parse_koinly_decimal` function in `koinly_parser.py`: given a negative input string like "-42.26", expects `Decimal("-42.26")` (negative preserved)
- [x] Review `CryptoCapitalGainEntry.gain_loss_eur` field; given negative parsed value, expects value stored without sign conversion
- [x] Review aggregation sums in `crypto_reporting.py`: given list of negative gains, expects sum produces negative total (not absolute)
- [x] Review Excel write in `crypto_gains_sheet.py`: given entry with negative `gain_loss_eur`, expects negative value written to cell (not absolute)
- [x] Document findings in the local investigation record; summarize whether current implementation is correct or needs fixes

**Note:** This task determines whether subsequent implementation tasks are needed. If current handling is already correct, the plan reduces to documentation and verification only.

**Decision tree:** If Task 1 finds current implementation is already correct:
- Skip Tasks 2, 4, 6 (implementation tasks)
- Tasks 3, 5, 7, 8 still run (verification/documentation/investigation)
- Proceed to final validation

### Task 2: Add Country-Specific Derivatives Loss Configuration (if needed) ⏭️ **SKIPPED**

**SKIP REASON:** Task 1 found current implementation is already correct. This task is not needed.

If Task 1 reveals that changes are needed, add configuration for country-specific derivatives loss treatment.

Files:
- `src/tax_reporting/domain/jurisdiction.py` *(modify)*
- `tests/unit/domain/test_jurisdiction.py` *(verify exists, create if missing)*

- [ ] Verify `tests/unit/domain/test_jurisdiction.py` exists; if not, add test file creation as part of this task
- [ ] `TaxJurisdictionConfigTest#test_derivatives_loss_treatment_default_false`: given new config without explicit setting, expects `derivatives_loss_treatment=False` (conservative default)
- [ ] `TaxJurisdictionConfigTest#test_derivatives_loss_treatment_pt_true`: given PT config with `derivatives_loss_treatment=True`, expects setting is preserved
- [ ] Run → expect RED: tests fail (field does not exist)
- [ ] Add `derivatives_loss_treatment: bool = False` field to `TaxJurisdictionConfig`
- [ ] Run → expect GREEN
- [ ] Commit: `feat: add derivatives_loss_treatment config field for country-specific loss handling`

- [ ] `TaxJurisdictionConfigTest#test_derivatives_loss_treatment_default_false`: given new config without explicit setting, expects `derivatives_loss_treatment=False` (conservative default)
- [ ] `TaxJurisdictionConfigTest#test_derivatives_loss_treatment_pt_true`: given PT config with `derivatives_loss_treatment=True`, expects setting is preserved
- [ ] Run → expect RED: tests fail (field does not exist)
- [ ] Add `derivatives_loss_treatment: bool = False` field to `TaxJurisdictionConfig`
- [ ] Run → expect GREEN
- [ ] Commit: `feat: add derivatives_loss_treatment config field for country-specific loss handling`

**Implementation detail:**
```python
@dataclass(frozen=True)
class TaxJurisdictionConfig:
    """Country-specific tax jurisdiction configuration.
    
    Attributes:
        country: ISO 3166-1 alpha-2 country code (e.g., 'PT', 'US').
        fiscal_year: The fiscal year this configuration applies to.
        exclude_loan_repayment_gains: Whether loan repayment disposals are excluded.
        zero_basis_review_threshold: Entries with zero cost basis and gain/loss at or
            above this threshold are flagged for review.
        derivatives_loss_treatment: Whether derivatives/futures losses are treated as
            deductible capital losses (True for PT per CIRS art. 10(1)(e), False for
            countries where losses may have different treatment).
    """
    country: str
    fiscal_year: int
    exclude_loan_repayment_gains: bool
    zero_basis_review_threshold: Decimal
    derivatives_loss_treatment: bool = False  # Default: conservative treatment
```

### Task 3: Verify and Archive All Portuguese Tax Documents

Ensure all relevant Portuguese tax authority documents are properly archived and referenced in sources.md.

Files:
- `docs/tax/laws/pt/crypto-tax/sources.md` *(verify)*
- `docs/tax/laws/pt/crypto-tax/official/cirs_art10_portal_2026-04-01.html` *(already archived)*

- [x] `verify_cirs_art10_derivatives_coverage`: given `cirs_art10_portal_2026-04-01.html`, expects file exists and contains "instrumentos financeiros derivados" text at line ~580
- [x] `verify_at_folheto_downloaded`: given sources.md entry for `at_folheto_criptoativos_2026-01-12.pdf`, expects PDF file exists in official/
- [x] `verify_cirs_consolidated_downloaded`: given sources.md entry for `cirs_2025-07_code_consolidated.pdf`, expects PDF file exists and includes art. 10(17)-(22)
- [x] `verify_sources_md_complete`: given sources.md, expects all 14 listed official files exist in `official/` directory
- [x] Run → expect GREEN (verification only, no code changes)
- [x] If any files are missing, document gap in the local investigation record for remediation

**Verification command:**
```bash
# Check all files listed in sources.md exist
cd docs/tax/laws/pt/crypto-tax
grep "official/" sources.md | sed -E 's/.*`official/([^`]+)`.*/\1/' | while read f; do
  if [ ! -f "official/$f" ]; then
    echo "MISSING: official/$f"
  fi
done

# Verify derivatives text exists
grep "instrumentos financeiros derivados" official/cirs_art10_portal_2026-04-01.html
```

### Task 4: Add Tests for Country-Specific Loss Handling ⏭️ **SKIPPED**

**SKIP REASON:** Task 1 found current implementation is already correct. This task is not needed.

Add tests to verify that negative gains are handled correctly per country configuration.

Files:
- `tests/unit/application/test_crypto_reporting.py` *(modify)*

- [ ] `test_negative_gain_preserved_for_pt`: given PT config with `derivatives_loss_treatment=True` and a Koinly row with "Gain / loss" = "-42.26", expects `gain_loss_eur = Decimal("-42.26")` (negative preserved)
- [ ] `test_negative_gain_aggregation Produces_negative_total`: given three entries with gains 100, -50, -30, expects total = 20 (not 180 or other incorrect sum)
- [ ] `test_negative_gain_written_to_excel_as_negative`: given entry with `gain_loss_eur = Decimal("-100")`, expects Excel cell value is -100 (not 100 or "100")
- [ ] `test_zero_basis_negative_gain_flags_review`: given entry with `cost_eur=0` and `gain_loss_eur=-1000` and threshold=100, expects `review_required=True` with reason about zero-basis loss
- [ ] Run → expect RED (tests for new verification behavior)
- [ ] Add test methods to `test_crypto_reporting.py`
- [ ] Run → expect GREEN
- [ ] Commit: `test: add country-specific negative gain handling tests`

### Task 5: Update Crypto Rules Documentation (Already Done)

The documentation updates were already completed in the investigation phase:

Files:
- `docs/domain/crypto_rules.md` *(already updated)*
- `docs/tax/decision_points/2025.md` *(already updated)*
- `docs/tax/decision_points/2025.toml` *(already updated)*

- [x] Verify PT-C-031 exists in `crypto_rules.md`: expects rule states derivatives are covered under CIRS art. 10(1)(e)
- [x] Verify PT-C-032 exists in `crypto_rules.md`: expects rule states losses follow holding-period rules with carry-forward for short-term
- [x] Verify DP-010 exists in `2025.md`: expects decision point states futures/derivatives losses are taxable disposals
- [x] Verify `futures_derivatives_taxable = true` in `2025.toml`: expects config setting exists for PT
- [x] Run → expect GREEN (verification only, documentation already complete)
- [x] No commit needed (already done in investigation phase)

### Task 6: Create Country-Specific Loss Treatment Guidance (Optional) ⏭️ **SKIPPED**

**SKIP REASON:** Task 1 found current implementation is already correct. This task is not needed.

If Task 1 reveals that USA or other countries have different derivatives loss treatment, add guidance documentation.

Files:
- `docs/tax/decision_points/2025.md` *(add USA entry if applicable)*
- `docs/tax/decision_points/country_specific_guidance.md` *(new, if needed)*

- [ ] Research USA derivatives tax treatment; given IRS publications on futures/derivatives, document how losses are treated (may differ from PT)
- [ ] Add DP-011 for USA if needed; given USA treats derivatives losses differently, expects decision point documents the difference
- [ ] Run → expect GREEN (documentation only)
- [ ] Commit: `docs: add country-specific derivatives loss treatment guidance (if applicable)`

**Note:** This task is optional and only if research reveals significant differences in how other countries handle derivatives losses. The plan can be completed without this task if PT treatment is the primary concern.

### Task 7: Investigate Koinly Other Gains Report for Derivatives Losses

Koinly provides multiple CSV exports. The Other Gains Report may contain futures/derivatives losses that Koinly treats separately from capital gains.

Files:
- `resources/source/koinly2025/2026-05-30/koinly_2025_other_gains_report_*.csv` *(example data)*
- the local investigation record *(findings document)*

- [x] `investigate_other_gains_report_structure`: given Koinly Other Gains CSV, expects columns are Date,Asset,Amount,Value (EUR),Type,Wallet Name
- [x] `verify_futures_losses_in_other_gains`: given sample data showing "19/01/2025 23:28,USDT,-273.86,265.49,Loss,ByBit", expects futures liquidation losses appear in this report
- [x] `compare_capital_vs_other_gains`: given both Capital Gains and Other Gains reports for same period, expects verify which losses appear where
- [x] `determine_if_other_gains_needed`: given PT tax law CIRS art. 10(1)(e), expects determine whether Other Gains Report losses should be treated as capital losses
- [x] Document findings in the local investigation record; include whether Other Gains Report needs to be processed and how

**Investigation questions:**
- Does Koinly classify futures liquidation losses as "Other gains" rather than "Capital gains"?
- Should the system process the Other Gains Report in addition to the Capital Gains Report?
- Are the losses in Other Gains Report reportable as capital losses under PT law?
- Do Transaction History "Futures fee" entries map to Other Gains Report entries?

**Decision gate:** If Task 7 investigation determines that Other Gains Report processing is required, create a separate implementation plan for that feature. Do not expand the scope of this plan to include full Other Gains Report processing; this would be a significant new feature beyond derivatives loss treatment.

**Sample findings from initial investigation:**
```
Other Gains Report line 29:
19/01/2025 23:28,USDT,"-273,86100000","265,49",Loss,ByBit

Transaction History shows:
2025-01-19 23:28:53 UTC,crypto_withdrawal,Futures fee,ByBit,"5,77853420",USDT...
```

### Task 8: Final Validation

Run full test suite and verify all changes work correctly together.

- [x] Run full crypto test suite: `uv run pytest tests/unit/application/test_crypto_reporting.py -v`
- [x] Run persisting tests: `uv run pytest tests/unit/application/persisting/test_crypto_gains_sheet.py -v`
- [x] Run domain tests: `uv run pytest tests/unit/domain/test_jurisdiction.py -v`
- [x] Verify documentation consistency; check `crypto_rules.md`, `2025.md`, `2025.toml` all align
- [x] Create summary report in the local investigation record; document findings, changes made, and any remaining gaps
- [x] Review Koinly Other Gains investigation findings from Task 7; determine if additional processing is needed

Run → expect all tests pass and documentation is consistent.
