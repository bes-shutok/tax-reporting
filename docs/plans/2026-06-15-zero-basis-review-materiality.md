# Plan: Zero-Basis Review Flag Materiality Threshold

Reference: CLAUDE.md Repository Constraints on zero-basis review.
Related rules: PT-C-024 (no de minimis threshold for declarable disposals); PT-C-028 (1 EUR materiality filter post-aggregation); PT-C-030 (review reasons must be specific and actionable).
Plan review: the zero-basis plan review (local) (r1, incorporated: B1 both-branches guard, M1 test rewrites, M2 signature default, M3 drop Task 3, M4 _KNOWN_DECISION_FLAGS note, L2-L4 citations, Mo1 expanded backward-compat coverage); the zero-basis plan review (local) (r2, ready=YES, 0 Blocker, 0 Medium, 2 Low, 2 Monitor; incorporated: Mo1 negative-value validation, Mo2 DP-013 naming).
Hardcoded value confirmation: 10 EUR default was confirmed by the user in the prior session ("exclude 0 basis warning for assets which actual value is less than 10 EUR"); flagged per CLAUDE.md Section 4 rule.

## Terms

- **Zero-basis review flag**: The `review_required=True` plus `review_reason` text set by `_build_zero_basis_review_reason` when `cost_eur == 0` or `proceeds_eur == 0`. Renders as "YES: <reason>" in the Excel Review column.
- **Red-fill threshold**: The existing `zero_basis_review_threshold` (default 50 EUR) on `TaxJurisdictionConfig`. Gates visual red-fill highlighting in the Crypto Gains sheet for entries with `|gain/loss| >= threshold`. Unchanged by this plan.
- **Min-proceeds threshold**: The new `zero_basis_review_min_proceeds` (default 10 EUR) introduced by this plan. Gates the zero-cost review flag: the flag fires only when `cost_eur == 0 AND proceeds_eur >= min_proceeds`.
- **FEE token disposals**: Kraken-specific utility token (`FEE`) used to pay Koinly exchange fees. Received free as a welcome bonus; disposed at zero EUR proceeds when paying fees. Generates zero-cost zero-proceeds CG entries that have no taxable gain but currently trigger the review flag.

## Gist and Examples

### Problem

`_build_zero_basis_review_reason` (`src/tax_reporting/application/crypto/fifo_helpers.py:353-381`) fires `review_required=True` for EVERY entry where `cost_eur == 0` or `proceeds_eur == 0`, regardless of the other side's value. At the user's disclosed scale (tens of thousands to millions of transactions per year), this produces 900+ review flags per year. Analysis of the 2025 dataset shows:

| Category | Count | Example | Tax treatment |
|----------|-------|---------|---------------|
| `cost=0 AND proceeds=0` | 779 | Kraken FEE token disposals (welcome bonus used to pay Koinly fees) | Gain/loss = 0; no declaration content; already excluded by PT-C-028 1 EUR materiality filter |
| `cost=0 AND 0 < proceeds < 10 EUR` | 146 | Small airdrops, staking rewards, cashback disposals | Taxable (gain = proceeds) but immaterial; user estimates 99% are rewards, not data errors |
| `cost=0 AND proceeds >= 10 EUR` | 4 | Larger disposals worth reviewing for data quality | Taxable; actionable review warranted |
| `cost>0 AND proceeds=0` | rare | Missing sale data, transfer errors | Legitimate data-quality concern; keep flagging |

All 779 FEE entries and most of the 146 small-reward entries are noise: the user cannot act on them, and per PT-C-028 they are already excluded from the final report. Per CLAUDE.md ("Partial or uncertain results must carry an explicit indicator so the user cannot mistake them for complete resolution"), the review flag must remain actionable; a routinely-firing non-actionable flag trains the user to ignore the review column entirely.

### PT authority basis

PT-C-024 (`docs/domain/crypto_rules.md:258-263`): "No de minimis threshold exists in Portuguese law for crypto disposals. All alienações, regardless of size, are in principle declarable." Confirmed by absence of any threshold in AT folheto 2026-01-12, Ofício Circulado 20269/2024, and Ofício Circulado 20278/2025.

But PT-C-024 governs declarability of taxable dispositions. A zero-gain disposal (`cost=0 AND proceeds=0`) has no taxable amount to declare. The 1 EUR materiality filter (PT-C-028, `docs/domain/crypto_rules.md:311-317`) already excludes these from the Excel output as an implementation decision; this plan extends the same logic to the review flag. Source records remain in the Koinly CSV for audit (CIRS art. 124-A requires custodians to report to AT, so AT may cross-verify).

### Solution: three-tier rule

Modify `_build_zero_basis_review_reason` to apply a new `zero_basis_review_min_proceeds` threshold (default 10 EUR):

1. `cost_eur == 0 AND proceeds_eur == 0` (FEE token case): never flag. No action possible.
2. `cost_eur == 0 AND 0 < proceeds_eur < min_proceeds` (small rewards): do not flag. Immaterial, likely reward.
3. `cost_eur == 0 AND proceeds_eur >= min_proceeds`: flag. Actionable review.
4. `cost_eur > 0 AND proceeds_eur == 0`: keep flagging. Legitimate data-quality concern.

The existing red-fill threshold (`zero_basis_review_threshold`, 50 EUR) is unchanged. The two thresholds serve different layers:

- `zero_basis_review_threshold` (50 EUR): visual red-fill for entries with large `|gain/loss|`.
- `zero_basis_review_min_proceeds` (10 EUR): gates the review_reason text for zero-cost entries.

For a zero-cost entry, gain = proceeds, so the progression is:

| `proceeds_eur` (zero-cost entry) | Review flag | Red fill |
|----------------------------------|-------------|----------|
| 0                                | no          | no       |
| 0 < proceeds < 10                | no          | no       |
| 10 <= proceeds < 50              | YES         | no       |
| proceeds >= 50                   | YES         | YES      |

### Examples (before to after)

**FEE token disposal (Kraken welcome bonus):**
- Before: `FEE 2025-03-15 Kraken cost=0 proceeds=0 gain=0 review=YES: Zero acquisition cost - verify basis...; Zero disposal proceeds - verify sale data...`
- After: `FEE 2025-03-15 Kraken cost=0 proceeds=0 gain=0 review=NO` (no flag; already excluded by materiality filter)

**Small staking reward disposal (5 EUR proceeds):**
- Before: `SUI 2025-04-20 Binance cost=0 proceeds=5.00 gain=5.00 review=YES: Zero acquisition cost - verify basis...`
- After: `SUI 2025-04-20 Binance cost=0 proceeds=5.00 gain=5.00 review=NO` (below threshold; user judges 99% are rewards)

**Larger zero-cost disposal (30 EUR proceeds):**
- Before: `review=YES: Zero acquisition cost - verify basis...`
- After: `review=YES: Zero acquisition cost - verify basis...` (unchanged; above threshold)

**Missing sale data (cost>0, proceeds=0):**
- Before: `review=YES: Zero disposal proceeds - verify sale data...`
- After: `review=YES: Zero disposal proceeds - verify sale data...` (unchanged; legitimate data-quality concern)

## Evaluation Criteria

**Quality dimensions:**
- Correctness: the three-tier rule matches the decision table above for all four input combinations; backward compatibility preserved when `zero_basis_review_min_proceeds=0` (current behavior, flag everything).
- Maintainability: the threshold lives on `TaxJurisdictionConfig` and flows through the same path as `zero_basis_review_threshold`; no new config plumbing patterns.
- Signal-to-noise: at the user's 2025 dataset scale, review flags drop from 900+ to approximately 4 (the actionable cases).

**Release gates:**
- All existing tests pass unchanged.
- New tests cover all four tiers.
- `ZERO_BASIS_REVIEW_MIN_PROCEEDS` added to both `config.ini` and `tests/config.ini`.

## Review Scope

**Explicit must-fix** - findings on these paths are always in scope (review and fix if valid):

**Production code:**
- `src/tax_reporting/domain/jurisdiction.py`
- `src/tax_reporting/infrastructure/config.py`
- `src/tax_reporting/application/crypto/fifo_helpers.py`
- `src/tax_reporting/application/crypto_reporting.py`

**Tests:**
- `tests/unit/application/test_crypto_reporting.py` (extend existing zero-basis tests near lines 3889-3955; the existing `test_build_zero_basis_review_reason_*` functions document current behavior and must be updated or joined by new three-tier tests; specifically rewrite `test_build_zero_basis_review_reason_both_zero` at line 3921 to assert `review_required=False`)
- `tests/unit/domain/test_jurisdiction.py` (new field coverage)
- `tests/unit/infrastructure/test_config.py` (extend existing `TestLoadTaxJurisdictionConfig` class near lines 158, 225-234; reuse `_PT_TOML` at line 161 and `_make_config` at line 164)

**Config:**
- `config.ini`
- `tests/config.ini`

**Plan-related extension** - implementation and review may change files not listed above. Treat a finding as in scope when it is causally related to this plan.

**Out of scope - reject unless plan-related:**
- `src/tax_reporting/application/crypto/entities.py` - r1 Medium 3: `CryptoTaxReport` does not carry the new threshold; it is consumed only at FIFO build time via `crypto_reporting.py:458`.
- `src/tax_reporting/application/persisting/crypto_gains_sheet.py` - red-fill rendering unchanged; the existing `zero_basis_review_threshold` continues to gate visual highlighting.
- `docs/tax/decision_points/2025.toml` - TOML schema is boolean-only; numeric thresholds live in `config.ini`.

## Design Invariants (CR Guard)

1. **Red-fill threshold unchanged.** `zero_basis_review_threshold` (default 50 EUR) continues to gate red-fill highlighting in `crypto_gains_sheet.py:160`. This plan does not touch the red-fill logic; the new `zero_basis_review_min_proceeds` only gates the review_reason text.

2. **`cost>0 AND proceeds=0` keeps flagging.** The zero-proceeds review flag is a legitimate data-quality signal (sold something for nothing: transfer error, missing sale data, or wallet misconfiguration). The min-proceeds threshold applies only to the zero-cost branch.

3. **Zero-zero entries never flag.** `cost_eur == 0 AND proceeds_eur == 0` is suppressed unconditionally (not threshold-gated). Gain/loss = 0; there is no user action possible; PT-C-028 materiality filter already excludes these from output.

4. **Backward compatibility.** When `zero_basis_review_min_proceeds=Decimal("0")`, the function must behave identically to today (flag every zero-cost and zero-proceeds entry). This is the escape hatch if a future use case wants the old behavior.

5. **Default 10 EUR is an implementation decision, not a law-driven value.** PT-C-024 explicitly states no de minimis threshold exists in PT law. The 10 EUR default is a noise-reduction implementation decision per PT-C-028's rationale (impractical burden with no tax consequence). Document as such in the decision points MD.

6. **Config-only threshold.** The threshold is a user preference, not a law-driven flag. It lives in `config.ini [TAX JURISDICTION]`, not in `docs/tax/decision_points/2025.toml` (TOML schema is boolean-only per CLAUDE.md).

## Validation Commands

```bash
uv run pytest tests/unit/application/test_crypto_reporting.py -v -k zero_basis_review
uv run pytest tests/unit/domain/test_jurisdiction.py -v
uv run pytest tests/unit/infrastructure/test_config.py -v
uv run pytest -m unit -x --tb=short
uv run pytest -m e2e -x --tb=short
```

### Task 1: Add `zero_basis_review_min_proceeds` to TaxJurisdictionConfig

Files:
- `src/tax_reporting/domain/jurisdiction.py`
- `src/tax_reporting/infrastructure/config.py`

- [ ] `TestTaxJurisdictionConfig#accepts_zero_basis_review_min_proceeds` - given a config with the new field set to `Decimal("10")`, expects the field is accessible and equals `Decimal("10")`
- [ ] `TestTaxJurisdictionConfig#defaults_zero_basis_review_min_proceeds_to_zero_when_absent` - given a jurisdiction config constructed without the field, expects `zero_basis_review_min_proceeds == Decimal("0")` (backward-compatible default: flag everything)
- [ ] `TestLoadTaxJurisdictionConfig#reads_zero_basis_review_min_proceeds_from_config_ini` - given `config.ini` with `ZERO_BASIS_REVIEW_MIN_PROCEEDS = 10` under `[TAX JURISDICTION]`, expects the parsed `TaxJurisdictionConfig.zero_basis_review_min_proceeds` to equal `Decimal("10")`. Reuse the existing `_PT_TOML` constant and `_make_config` helper at `test_config.py:161-172`.
- [ ] `TestLoadTaxJurisdictionConfig#falls_back_to_default_when_key_absent` - given `config.ini` without the key, expects the parsed config uses `DEFAULT_ZERO_BASIS_REVIEW_MIN_PROCEEDS` (Decimal 10)
- [ ] `TestLoadTaxJurisdictionConfig#rejects_invalid_zero_basis_review_min_proceeds` - given `config.ini` with `ZERO_BASIS_REVIEW_MIN_PROCEEDS = abc`, expects `ValueError` with the raw value in the message
- [ ] `TestLoadTaxJurisdictionConfig#rejects_negative_zero_basis_review_min_proceeds` - given `config.ini` with `ZERO_BASIS_REVIEW_MIN_PROCEEDS = -5`, expects `ValueError` (r2 Monitor 1: mirror the `is_finite() and >= 0` validation from `ZERO_BASIS_REVIEW_THRESHOLD` at `config.py:193-196`; a negative value would over-flag rather than under-flag so is harmless, but explicit validation prevents confusion)
- [ ] Run -> expect RED: `uv run pytest tests/unit/domain/test_jurisdiction.py::TestTaxJurisdictionConfig tests/unit/infrastructure/test_config.py -v`
- [ ] Add `DEFAULT_ZERO_BASIS_REVIEW_MIN_PROCEEDS = Decimal("10")` to `config.py` near `DEFAULT_ZERO_BASIS_REVIEW_THRESHOLD`
- [ ] Add `zero_basis_review_min_proceeds: Decimal = Decimal("0")` to `TaxJurisdictionConfig` after `zero_basis_review_threshold` (default 0 preserves current behavior when not set). Valid per r1 verified assumption 14: `zero_basis_review_threshold` has no default, but the fields below (`futures_derivatives_taxable` etc.) already have defaults, so inserting a defaulted field here does not violate dataclass ordering.
- [ ] Verified (r1 Medium 4): `_KNOWN_DECISION_FLAGS` auto-derivation at `config.py:44-52` includes only `bool` fields (`if hint is bool`); the new `Decimal` field is correctly excluded from TOML flag validation. No registration needed.
- [ ] Update the config loader in `config.py` to read `ZERO_BASIS_REVIEW_MIN_PROCEEDS`, defaulting to `DEFAULT_ZERO_BASIS_REVIEW_MIN_PROCEEDS` when absent. Mirror the validation pattern at `config.py:187-196` (`try Decimal(...) except InvalidOperation`, then `if not value.is_finite() or value < 0: raise ValueError(...)`)
- [ ] Add `ZERO_BASIS_REVIEW_MIN_PROCEEDS = 10` to `config.ini [TAX JURISDICTION]`
- [ ] Add `ZERO_BASIS_REVIEW_MIN_PROCEEDS = 10` to `tests/config.ini [TAX JURISDICTION]`
- [ ] Run -> expect GREEN
- [ ] Commit: `feat(config): add zero_basis_review_min_proceeds threshold for review flag gating`

### Task 2: Gate the zero-cost review flag by min_proceeds in `_build_zero_basis_review_reason`

Files:
- `src/tax_reporting/application/crypto/fifo_helpers.py`
- `src/tax_reporting/application/crypto_reporting.py`

- [ ] `TestBuildZeroBasisReviewReason#zero_cost_zero_proceeds_never_flags` - given `cost_eur=0, proceeds_eur=0, min_proceeds=10`, expects `review_required=False` and empty `review_reason` (FEE token case)
- [ ] `TestBuildZeroBasisReviewReason#zero_cost_small_proceeds_does_not_flag` - given `cost_eur=0, proceeds_eur=5, min_proceeds=10`, expects `review_required=False` (small reward below threshold)
- [ ] `TestBuildZeroBasisReviewReason#zero_cost_at_threshold_flags` - given `cost_eur=0, proceeds_eur=10, min_proceeds=10`, expects `review_required=True` and reason mentions zero acquisition cost (boundary: at threshold, flag fires)
- [ ] `TestBuildZeroBasisReviewReason#zero_cost_above_threshold_flags` - given `cost_eur=0, proceeds_eur=30, min_proceeds=10`, expects `review_required=True` with zero-cost reason (actionable review)
- [ ] `TestBuildZeroBasisReviewReason#zero_proceeds_with_nonzero_cost_always_flags` - given `cost_eur=50, proceeds_eur=0, min_proceeds=10`, expects `review_required=True` with zero-proceeds reason (data-quality concern, threshold does not apply)
- [ ] `TestBuildZeroBasisReviewReason#min_proceeds_zero_flags_all_zero_cost` - given `cost_eur=0, proceeds_eur=0, min_proceeds=0`, expects `review_required=True` (backward-compat: threshold 0 preserves current behavior). ALSO add `min_proceeds_zero_flags_zero_cost_with_proceeds`: given `cost_eur=0, proceeds_eur=100, min_proceeds=0`, expects `review_required=True` (r1 Monitor 1: cover non-zero-proceeds zero-cost case under backward-compat threshold, not just the zero-zero corner).
- [ ] `TestBuildZeroBasisReviewReason#preserves_existing_review_reason` - given an entry that already has `review_required=True` and a non-empty `review_reason`, plus `cost_eur=0, proceeds_eur=30`, expects the new zero-cost reason is appended to the existing reason, not replacing it
- [ ] Run -> expect RED: `uv run pytest tests/unit/application/test_crypto_reporting.py -v -k zero_basis_review`
- [ ] Modify `_build_zero_basis_review_reason` signature to add `min_proceeds: Decimal = ZERO` as a new defaulted parameter at the end (preserves backward compat for existing tests that do not pass it). Final signature:
  ```python
  def _build_zero_basis_review_reason(
      cost_eur: Decimal,
      proceeds_eur: Decimal,
      review_required: bool,
      review_reason: str,
      min_proceeds: Decimal = ZERO,
  ) -> tuple[bool, str]:
  ```
- [ ] Replace BOTH branches with the three-tier logic. The proceeds branch MUST gain a `cost_eur > ZERO` guard so zero-zero entries do not trip it (this was r1 Blocker 1: leaving the proceeds branch unchanged lets `proceeds_eur == ZERO` evaluate True on zero-zero, re-flagging the FEE token case):
  ```python
  # tier 3: zero-cost with material proceeds (above min_proceeds threshold)
  if cost_eur == ZERO and proceeds_eur > ZERO and proceeds_eur >= min_proceeds:
      review_required = True
      zero_cost_reason = "Zero acquisition cost - verify basis (airdrop, data error, or misclassification)"
      review_reason = f"{review_reason}; {zero_cost_reason}" if review_reason else zero_cost_reason

  # tier 4: zero-proceeds with NONZERO cost (legitimate data-quality concern; cost guard prevents zero-zero flagging)
  if proceeds_eur == ZERO and cost_eur > ZERO:
      review_required = True
      zero_proceeds_reason = "Zero disposal proceeds - verify sale data (transfer error, data quality issue)"
      review_reason = f"{review_reason}; {zero_proceeds_reason}" if review_reason else zero_proceeds_reason

  # tiers 1 and 2 fall through with no flag:
  #   - cost=0 AND proceeds=0 (FEE token case): neither condition matches
  #   - cost=0 AND 0 < proceeds < min_proceeds (small reward): cost branch requires proceeds >= min_proceeds
  ```
- [ ] Trace verification (r1 recommended step 7): for each of the five input combinations, confirm the flag outcome matches the decision table:
  - `cost=0, proceeds=0, min_proceeds=10` -> no flag (both branch conditions False)
  - `cost=0, proceeds=5, min_proceeds=10` -> no flag (cost branch: `5 >= 10` False; proceeds branch: `cost_eur > ZERO` False)
  - `cost=0, proceeds=30, min_proceeds=10` -> flag with zero-cost reason (cost branch: `30 >= 10` True)
  - `cost=50, proceeds=0, min_proceeds=10` -> flag with zero-proceeds reason (proceeds branch: `cost_eur > ZERO` True)
  - `cost=50, proceeds=100, min_proceeds=10` -> no flag (neither branch matches)
- [ ] Update the external call site at `crypto_reporting.py:458-460` to pass `min_proceeds=jurisdiction.zero_basis_review_min_proceeds` (or `DEFAULT_ZERO_BASIS_REVIEW_MIN_PROCEEDS` fallback, matching the existing threshold pattern)
- [ ] Update the internal call site at `fifo_helpers.py:323-325` to thread the threshold through
- [ ] Update the five existing `test_build_zero_basis_review_reason_*` functions at `tests/unit/application/test_crypto_reporting.py:3889-3955` to pass the new `min_proceeds` parameter. SPECIFICALLY REWRITE `test_build_zero_basis_review_reason_both_zero` (line 3921) to assert `review_required is False` and empty `review_reason` (this was r1 Medium 1: the existing test asserts True for both-zero, which contradicts the new three-tier rule). The other four tests (`_zero_cost` at 3889, `_zero_proceeds` at 3905, `_appends_to_existing_reason` at 3939, `_no_trigger_when_both_nonzero` at 3955) need parameter addition but not assertion changes
- [ ] Run -> expect GREEN
- [ ] Commit: `feat(crypto): gate zero-basis review flag by min_proceeds threshold`

### Task 3: CryptoTaxReport field NOT needed (r1 Medium 3 resolution)

The new threshold is consumed only at FIFO build time (`fifo_helpers._build_zero_basis_review_reason` via `crypto_reporting.py:458`). The renderer `crypto_gains_sheet.py:160` reads only the existing `zero_basis_review_threshold` (red-fill gating) and does not need `min_proceeds`. Do NOT add `zero_basis_review_min_proceeds` to `CryptoTaxReport` - doing so would bloat the dataclass with an unused field.

### Task 4: Add decision point documentation

Files:
- `docs/tax/decision_points/2025.md`

- [ ] Verify `2025.md` Decision Points table structure (search for DP-012 entry at line 41 as the template)
- [ ] Add a new decision point entry **DP-013** (next sequential after DP-012) to the Decision Points table documenting:
  - Question: "Gate zero-basis review flag by min proceeds threshold?"
  - Answer: "Yes (default 10 EUR via `ZERO_BASIS_REVIEW_MIN_PROCEEDS` in `config.ini`)"
  - Koinly setting: "N/A (tool behavior)"
  - Legal basis: "PT-C-024 (no de minimis in law, but zero-gain disposals have nothing to declare); PT-C-028 (1 EUR materiality filter precedent)"
  - Notes: "Three-tier rule: `cost=0 AND proceeds=0` never flags (FEE tokens); `cost=0 AND 0 < proceeds < threshold` no flag (small rewards); `cost=0 AND proceeds >= threshold` flags; `cost>0 AND proceeds=0` keeps flagging (data-quality). Setting threshold to 0 restores current behavior."
- [ ] Add a Change Log entry at the bottom of `2025.md`: "`| 2026-06-15 | Added DP-013 for zero-basis review flag materiality threshold (noise reduction per PT-C-028 rationale) |`"
- [ ] Do NOT add to `2025.toml` (TOML schema is boolean-only; numeric thresholds live in `config.ini`)
- [ ] Commit: `docs(decisions): document zero_basis_review_min_proceeds implementation decision`

### Task 5: E2E backward compatibility test

Files:
- `tests/end_to_end/test_crypto_zero_basis_materiality.py` (new)

- [ ] `TestZeroBasisMaterialityE2E#fee_token_disposals_not_flagged` - given a Koinly CG fixture with FEE token disposals (cost=0, proceeds=0), expects the generated `CryptoTaxReport.capital_entries` contains those entries with `review_required=False` (or they are filtered out by materiality, in which case the test verifies they do not appear in the review-required set)
- [ ] `TestZeroBasisMaterialityE2E#small_reward_disposals_below_threshold_not_flagged` - given a fixture with zero-cost entries having proceeds between 0.01 and 9.99 EUR, expects `review_required=False`
- [ ] `TestZeroBasisMaterialityE2E#larger_zero_cost_disposals_above_threshold_flagged` - given a fixture with a zero-cost entry having proceeds >= 10 EUR, expects `review_required=True` with actionable reason
- [ ] `TestZeroBasisMaterialityE2E#backward_compat_min_proceeds_zero_flags_all` - given a `TaxJurisdictionConfig` constructed directly with `zero_basis_review_min_proceeds=Decimal("0")` (matching the e2e pattern at `tests/end_to_end/test_crypto_derivatives_separation.py:69` of constructing the config object directly rather than mocking `config.ini`), expects all zero-cost entries flagged (current behavior preserved)
- [ ] Run -> expect RED initially, then GREEN after Task 2 implementation
- [ ] Commit: `test(e2e): add zero-basis materiality backward-compat coverage`
