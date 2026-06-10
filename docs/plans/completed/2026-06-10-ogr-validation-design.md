# Plan: OGR Validation vs Replacement Design Fix

Related: development_lessons.md #78 (OGR Validation vs Replacement Design)

Plan review: the local review record (Blockers: 0, Medium: 0, Low: 0, Monitor: 0, ready: yes)
Previous: the local review record (Blockers: 0, Medium: 2, Low: 2, Monitor: 1)
Round 1: the local review record (Blockers: 0, Medium: 5, Low: 3, Monitor: 2)

## Gist & Examples

**Problem:** The current OGR (Other Gains Report) implementation uses **wholesale replacement semantics** — OGR values completely replace calculated gain/loss values. This causes incorrect results when multiple CG lots share the same OGR key, as each lot gets overridden with the full OGR value before aggregation.

**Example of current (buggy) behavior:**
- 109 CG lots for ByBit USDT on 2025-01-13
- OGR contains 3 entries totaling <-OGR_NET_EUR> EUR (funding fee, futures fee, realized P&L)
- Each of 109 lots is overridden with <-REALIZED_LOSS_EUR> EUR (last value, before Bug #1 fix)
- After aggregation: 109 × (<-OGR_NET_EUR>) ≈ <-OVERRIDDEN_AGGREGATE_EUR> EUR ❌

**User requirement:** OGR should be used for **directional authority**, not wholesale replacement:
- OGR is AUTHORITATIVE for DIRECTION (loss vs gain) — overrides CG when signs differ
- CG provides MAGNITUDE via standard FIFO calculation — preserved unless OGR direction conflicts
- When OGR and CG agree on direction, use CG magnitude
- Magnitude differences > 5% → YELLOW flag (review recommended, not blocking)

**Target behavior:**
- Report shows gain/loss with OGR-corrected direction
- If OGR says Loss but CG said Gain → report Loss with CG magnitude, flag as "OGR direction override"
- If OGR says Gain but CG said Loss → report Gain with CG magnitude, flag as "OGR direction override"
- Magnitude differences > 5% → YELLOW flag with "OGR magnitude differs by X%" note
- User can see both CG and OGR context in review notes

**Edge cases:**
- OGR missing for a disposal that CG has → Use CG value, no flag
- CG has no lots for a disposal OGR has → Flag as "OGR-only, verify"
- Multiple holding periods (short-term + long-term) → OGR validates aggregate, not per-period
- Zero-value disposals → Skip validation

## Terms

- **OGR (Other Gains Report)**: Koinly export containing gains/losses for futures/derivatives with multiple fee components
- **CG (Capital Gains)**: Koinly export with individual FIFO lot realizations
- **Disposal event**: The sale/liquidation of an asset, potentially across multiple FIFO lots
- **Direction conflict**: OGR indicates loss but calculated CG indicates gain (or vice versa)
- **Magnitude threshold**: 5% difference between OGR and calculated values

## Review Scope

Files directly changed as part of this plan. Review feedback is accepted **only** for the files listed here.

**Production code — in scope:**
- `src/tax_reporting/application/crypto_reporting.py` *(OGR override logic)*
- `src/tax_reporting/domain/entities.py` *(if CryptoCapitalGainEntry needs new fields)*

**Tests — in scope:**
- `tests/unit/application/test_crypto_reporting.py` *(OGR validation tests)*
- `tests/unit/infrastructure/test_koinly_parser.py` *(OGR parsing tests)*

**Documentation — scope-linked:**
- `docs/domain/development_lessons.md` *(lesson #78 update)*
- `docs/domain/crypto_reporting_guidelines.md` *(if OGR guidance needed)*

**Out of scope — reject all review feedback:**
- Any other files modified incidentally during implementation
- Refactoring of unrelated CG parsing logic

## Validation Commands

```bash
# Run unit tests
uv run pytest tests/unit/application/test_crypto_reporting.py::TestOgrValidation -v

# Run full crypto reporting tests
uv run pytest tests/unit/application/test_crypto_reporting.py -v

# Integration test with real OGR data
uv run pytest tests/integration/ -k "ogr" -v
```

## Design Invariants

1. **OGR is authoritative for direction**: When OGR sign ≠ CG sign, OGR direction wins — report uses OGR direction with CG magnitude
2. **CG provides magnitude**: CG-derived gain/loss magnitude is preserved unless direction override requires sign change
3. **Direction override is always flagged**: When OGR direction is applied, set review_required=True with "OGR direction override" reason
4. **Magnitude threshold is 5%**: When OGR and CG directions agree but magnitudes differ > 5%, flag with "OGR magnitude differs" reason
5. **No silent data loss**: All OGR entries must be accounted for, even if they don't match CG entries
6. **Backward compatible**: When OGR is disabled, behavior is identical to pre-this-plan

### Task 1: Add validation result domain type

Files:
- `src/tax_reporting/domain/entities.py` *(new field on CryptoCapitalGainEntry)*

Create a new type to represent OGR validation results:

```python
@dataclass(frozen=True)
class OgrValidationResult:
    """Result of comparing OGR value against calculated gain/loss."""
    ogr_gain_loss: Decimal | None  # None if no OGR match
    calculated_gain_loss: Decimal
    direction_conflict: bool  # True when signs differ
    magnitude_diff_percent: Decimal | None  # None when ogr_gain_loss is None
    review_required: bool
    review_reason: str | None
```

Add optional field to `CryptoCapitalGainEntry`:
```python
ogr_validation: OgrValidationResult | None = None
```

**Implementation note for __post_init__ compatibility:**
The `CryptoCapitalGainEntry.__post_init__` method validates that `review_reason` is set when `review_required=True`. The `ogr_validation` field is NOT part of this validation — it carries its own `review_required` and `review_reason` fields independently. When constructing an entry with `ogr_validation.review_required=True`, do NOT set `entry.review_required=True` based on it — the two fields are separate. Entry-level validation enforces consistency between `entry.review_required` and `entry.review_reason` only; OGR validation fields are informational metadata and do not drive entry construction.

- [x] Create `OgrValidationResultTest` — given OGR=-100, CG=-90, expects direction_conflict=False, magnitude_diff_percent≈11.1%, review_required=True
- [x] Create `OgrValidationResultTest` — given OGR=-100, CG=+50, expects direction_conflict=True, magnitude_diff_percent≈300%, review_required=True
- [x] Create `OgrValidationResultTest` — given OGR=-100, CG=-98, expects direction_conflict=False, magnitude_diff_percent≈2%, review_required=False
- [x] Create `OgrValidationResultTest` — given OGR=None, CG=+50, expects ogr_gain_loss=None, direction_conflict=False, review_required=False
- [x] Run → expect RED
- [x] Implement `OgrValidationResult` dataclass with field validation
- [x] Add `ogr_validation` field to `CryptoCapitalGainEntry`
- [x] Run → expect GREEN
- [x] Commit: `feat(ogr): add validation result domain type`

### Task 2: Refactor OGR override to validation

Files:
- `src/tax_reporting/application/crypto_reporting.py`

Rename `_apply_ogr_overrides()` to `_validate_with_ogr()` and change semantics:

**Current (replacement):**
```python
new_proceeds = entry.cost_eur + ogr_gain_loss
result.append(replace(entry, gain_loss_eur=ogr_gain_loss, proceeds_eur=new_proceeds))
```

**New (directional authority):**
```python
validation = OgrValidationResult(
    ogr_gain_loss=ogr_gain_loss,
    calculated_gain_loss=entry.gain_loss_eur,
    direction_conflict=(ogr_gain_loss < 0) != (entry.gain_loss_eur < 0),
    magnitude_diff_percent=abs((ogr_gain_loss - entry.gain_loss_eur) / entry.gain_loss_eur * 100) if entry.gain_loss_eur != 0 else None,
    review_required=False,  # computed below
    review_reason=None
)

# Determine if direction override is needed
final_gain_loss = entry.gain_loss_eur
if validation.direction_conflict:
    # OGR is authoritative for direction: use OGR sign with CG magnitude
    final_gain_loss = -abs(entry.gain_loss_eur) if ogr_gain_loss < 0 else abs(entry.gain_loss_eur)
    validation.review_required = True
    validation.review_reason = f"OGR direction override: CG indicated {'loss' if entry.gain_loss_eur < 0 else 'gain'}"
elif validation.magnitude_diff_percent and validation.magnitude_diff_percent > 5:
    # Directions agree but magnitudes differ significantly
    # Also require absolute difference > 1 EUR to avoid noise on near-zero gains
    magnitude_diff = abs(ogr_gain_loss - entry.gain_loss_eur)
    if magnitude_diff > Decimal("1"):
        validation.review_required = True
        validation.review_reason = f"OGR magnitude differs from CG by {validation.magnitude_diff_percent:.1f}%"

result.append(replace(entry, gain_loss_eur=final_gain_loss, proceeds_eur=entry.cost_eur + final_gain_loss, ogr_validation=validation))
```

Update call site from `_apply_ogr_overrides(capital_entries, ...)` to `_apply_ogr_direction_override(capital_entries, ...)`.

- [x] Create `ApplyOgrDirectionOverrideTest` — given CG entry with gain=+100 and OGR=-100, expects final_gain_loss=-100 (CG magnitude with OGR direction), review_reason="OGR direction override: CG indicated gain"
- [x] Create `ApplyOgrDirectionOverrideTest` — given CG entry with gain=-100 and OGR=-105, expects final_gain_loss=-105 (directions agree, use OGR magnitude), review_required=False (diff < 5%)
- [x] Create `ApplyOgrDirectionOverrideTest` — given CG entry with gain=-100 and OGR=-106, expects final_gain_loss=-106, review_required=True (diff > 5%), review_reason mentions magnitude diff
- [x] Create `ApplyOgrDirectionOverrideTest` — given CG entry with gain=-100 and no OGR match, expects final_gain_loss=-100 (unchanged), ogr_validation=None
- [x] Create `ApplyOgrDirectionOverrideTest` — given CG entry with gain=0.01 and OGR=-1.01, expects direction_conflict=True but review_required=False (absolute diff 1 EUR not exceeded)
- [x] Create `ApplyOgrDirectionOverrideTest_MultipleLots` — given 109 CG lots for same (date, asset, wallet) with total gain=+500 and OGR=<-OGR_NET_EUR>, expects each lot gets ogr_validation with ogr_gain_loss=<-OGR_NET_EUR>, directions corrected, and after aggregation produces single entry with corrected totals
- [x] Run → expect RED
- [x] Implement `_apply_ogr_direction_override()` function with directional authority semantics and absolute threshold
- [x] Update call site to use new function name
- [x] Run → expect GREEN
- [x] Commit: `refactor(ogr): apply OGR as directional authority, not wholesale replacement`

### Task 3: Update aggregation to preserve OGR direction override

Files:
- `src/tax_reporting/application/crypto_reporting.py`

Update `_aggregate_capital_entries()` to handle `ogr_validation` field:

When aggregating entries with the same key, combine validation results:
- If any entry has `direction_conflict=True`, aggregated result has `direction_conflict=True`
- If any entry has `review_required=True`, aggregated result has `review_required=True`
- Combine `review_reason` strings with "; "
- Use the maximum `magnitude_diff_percent` from all entries
- **`ogr_gain_loss` is the OGR value for the group's (date, asset, wallet) key** — all lots in the group share the same OGR value because they share the same lookup key. Do NOT sum individual lot OGR values (that would duplicate the same OGR value N times).

- [x] Create `AggregateOgrValidationTest` — given 3 entries with validation results (no conflicts), expects aggregated entry with ogr_gain_loss from first entry (NOT summed), no direction_conflict
- [x] Create `AggregateOgrValidationTest` — given 2 entries where one has direction_conflict=True, expects aggregated entry with direction_conflict=True
- [x] Create `AggregateOgrValidationTest` — given 3 entries with different magnitude_diff_percent values, expects aggregated entry with max magnitude_diff_percent
- [x] Create `AggregateOgrValidationTest` — given 2 entries with review_reason="reason A" and "reason B", expects aggregated entry with review_reason="reason A; reason B"
- [x] Run → expect RED
- [x] Update `_aggregate_capital_entries()` to aggregate `ogr_validation` field:
    - Take ogr_gain_loss from the first entry in the group (all entries have the same value per lookup key)
    - Combine review_required via OR (True if ANY entry has review_required=True)
    - Combine review_reason strings via "; " with deduplication
    - Use max(magnitude_diff_percent) across all entries
    - Set direction_conflict to True if ANY entry has direction_conflict=True
- [x] Run → expect GREEN
- [x] Commit: `feat(ogr): aggregate validation results across lots`

### Task 4: Update Excel output to show OGR validation

Files:
- `src/tax_reporting/application/persisting/crypto_gains_sheet.py`

Add OGR validation columns to the Crypto Gains sheet:

**New columns (after existing gain/loss columns):**
- "OGR Gain/Loss (EUR)" — shows OGR value if present, blank otherwise
- "OGR Diff (%)" — shows magnitude difference percentage
- "OGR Review" — shows "YES: <reason>" or "NO"

Conditional formatting:
- When OGR Review contains "OGR direction override" → RED fill
- When OGR Review contains "magnitude differs" → YELLOW fill
- When OGR Review = "NO" → no special fill

- [x] Update `_CAPITAL_GAINS_NUM_COLS` constant from 17 to 20 to reflect new OGR columns
- [x] Create `CryptoGainsSheetOgrValidationTest` — given entry with ogr_validation.review_reason containing "OGR direction override", expects "OGR Review" column shows "YES: OGR direction override: ..." with RED fill
- [x] Create `CryptoGainsSheetOgrValidationTest` — given entry with ogr_validation.magnitude_diff_percent=10, review_reason="...", expects "OGR Diff (%)"=10, "OGR Review" shows "YES: ..." with YELLOW fill
- [x] Create `CryptoGainsSheetOgrValidationTest` — given entry with ogr_validation=None, expects "OGR Gain/Loss", "OGR Diff (%)", "OGR Review" columns are blank
- [x] Create `CryptoGainsSheetOgrValidationTest` — given entry with ogr_validation.review_required=False, expects "OGR Review" shows "NO" with no special fill
- [x] Run → expect RED
- [x] Add OGR validation columns to crypto gains sheet
- [x] Implement conditional formatting for direction conflicts (RED) and magnitude diffs (YELLOW)
- [x] Run → expect GREEN
- [x] Commit: `feat(ogr): add OGR validation columns to Excel output`

### Task 5: Update documentation

Files:
- `docs/domain/development_lessons.md`
- `docs/domain/crypto_reporting_guidelines.md`

Update lesson #78 to reflect completed implementation:

Change from "Open" status to "Completed" with reference to this plan.

Add OGR validation guidance to crypto_reporting_guidelines.md (new section documenting OGR semantics: directional authority, magnitude thresholds, review flags).

- [x] Update `development_lessons.md` lesson #78 — change status from "Open" to "Completed", add reference to this plan
- [x] Add OGR validation section to `crypto_reporting_guidelines.md` documenting directional authority, magnitude thresholds (relative 5% + absolute 1 EUR), and review flag semantics
- [x] Run → expect GREEN (no tests, documentation only)
- [x] Commit: `docs(ogr): update OGR validation design lesson and add guidelines`

### Task 6: Final validation

Files:
- All modified files

Run full test suite and verify:

- All existing OGR override tests are updated or removed
- New validation tests pass
- Excel output shows OGR data correctly
- No regressions in crypto reporting pipeline
- Backward compatibility: when OGR disabled, output identical to pre-implementation

- [x] Run `uv run pytest tests/unit/application/test_crypto_reporting.py -v` → expect all pass
- [x] Create `OgrDisabledBackwardCompatibilityTest` — given jurisdiction with use_other_gains_report=False, expects ogr_validation=None on all entries, Excel has no OGR columns (only 17 columns), gain/loss values unchanged from original CG
- [x] Run `ApplyOgrDirectionOverrideTest_MultipleLots` and verify: each of 109 lots gets ogr_validation with ogr_gain_loss=<-OGR_NET_EUR> (same value), after aggregation single entry has corrected direction and total gain from all lots
- [x] Run `uv run pytest tests/integration/ -k "crypto" -v` → expect all pass
- [x] Run `uv run pytest -m e2e -v` → expect all pass
- [x] Generate test report with real Koinly data → verify OGR columns populate correctly
- [x] Run → expect GREEN
- [x] Commit: `test(ogr): validate OGR validation implementation`

## Monitor

### Mon1. Multi-lot test case verification

**Issue:** The primary bug scenario (109 lots, OGR=<-OGR_NET_EUR>) is tested via `ApplyOgrDirectionOverrideTest_MultipleLots` but was only a test creation checkbox with no explicit verification in Task 6.

**Action:** Added explicit verification checkbox in Task 6 to run the multi-lot test and verify correct behavior after aggregation.

**Owner:** Task 6 (Final Validation)
