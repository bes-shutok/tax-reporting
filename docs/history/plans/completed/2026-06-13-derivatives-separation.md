# Plan: Crypto Derivatives Separation (Financial Derivatives vs Cryptoassets)

Reference: the crypto-derivatives investigation (local) (findings source)
Plan review: the derivatives-separation plan review (local) (latest, ready) · r3 (1 Medium + 3 Low, fixed) · r2 (0 Blocker, 0 Medium) · r1 (8 Blockers + 7 Medium, addressed in r2)
Related decision points: DP-010 (`futures_derivatives_taxable`), DP-011 (`use_other_gains_report`) in `docs/tax/decision_points/2025.md`
Legal basis: CIRS art. 10(1)(e) (instrumentos financeiros derivados) vs art. 10(1)(k) (cryptoassets); AT Binding Ruling Processo 28298/2025

## Terms

- **OGR**: Koinly "Other Gains Report": CSV with columns `Date,Asset,Amount,Value (EUR),Type,Wallet Name`. No description column. `Type` is `Profit` or `Loss`.
- **CG**: Koinly "Capital Gains Report": FIFO lot disposals for spot crypto.
- **TH**: Koinly "Transaction History": raw `crypto_deposit`/`crypto_withdrawal` events. The label column (column 3) uses `"Realized gain"` for many event types (rewards, fee disposals, derivatives P&L realization); it is NOT derivatives-specific. Verified against `resources/source/koinly2025/koinly_2025_transaction_history_<ACCOUNT_TOKEN>.csv`.
- **Spot crypto**: Disposals taxed under CIRS art. 10(1)(k); 365-day exemption applies (art. 10(19)).
- **Derivatives**: Futures/perpetuals/options taxed under CIRS art. 10(1)(e), **no 365-day exemption**; always taxed on realization.
- **Directional authority**: When OGR and CG disagree on sign, OGR wins because it captures derivatives economics; see `ogr_handler.py:209-336`. Under the new model, this authority applies **only within the same event category**.
- **CG counterpart**: A CG entry on the same `(date, asset, wallet)` key whose EUR value matches the OGR row's EUR value within a small tolerance. Existence of a CG counterpart means the disposal has a FIFO cost-basis trail → spot fee disposal. Absence means derivatives P&L realization (no cost-basis trail).

## Gist & Examples

### What changes

Today the pipeline mixes three economically distinct events into one Crypto Gains sheet: (1) spot crypto-to-fiat/crypto-to-crypto disposals, (2) USDT lot disposals to pay futures fees, and (3) realized P&L from derivatives contracts. Per AT Binding Ruling Processo 28298/2025, derivatives are **Financial Derivatives** under CIRS art. 10(1)(e), not cryptoassets under art. 10(1)(k). The 365-day exemption does not apply, and mixing the two produces incorrect tax treatment.

This plan separates derivatives from spot crypto end-to-end: classify each OGR row as derivatives or spot using a sealed-result classifier, split the OGR index at the row level (not the summed-key level), add a new "Derivatives P&L" Excel tab reporting art. 10(1)(e) gains/losses, and gate the behavior behind a new decision point (DP-012) and jurisdiction flag.

### Why

Concrete failure traced in the investigation (Case 1, 2025-01-12 ByBit USDT), verified against the actual fixtures:

- OGR row 8: `<PROFIT_TIMESTAMP>,USDT,"<PROFIT_USDT>","140,18",Profit,ByBit` (futures P&L profit)
- OGR row 9: `<PROFIT_TIMESTAMP>,USDT,"-<FEE_PROCEEDS_USDT>","<FEE_PROCEEDS_EUR>",Loss,ByBit` (futures fee disposal)
- CG has exactly one matching row: the `<FEE_PROCEEDS_EUR> EUR` fee disposal (FIFO consumes a reward lot with cost `<COST_BASIS_EUR> EUR`, giving gain `<FEE_GAIN_EUR> EUR`).
- The parser at `koinly_parser.py:391` sums both OGR rows into the key `("2025-01-12", "USDT", "ByBit")` → `<PROFIT_EUR> + (<-FEE_PROCEEDS_EUR>) = <MIXED_AGGREGATE_EUR> EUR`. The per-row Type information is destroyed at this point.
- The OGR override applies the `<MIXED_AGGREGATE_EUR> EUR` net to the single CG fee entry. Final reported gain = `<MIXED_AGGREGATE_EUR> EUR`; proceeds = `<COST_BASIS_EUR> + <MIXED_AGGREGATE_EUR> = 137.73 EUR`.
- The `<PROFIT_EUR> EUR` futures profit has **no CG entry at all**: it is represented in TH as `<PROFIT_TIMESTAMP>,crypto_deposit,Realized gain,...,ByBit,...,USDT,"140,18"`, yet it dominates the reported gain because the override is direction-based, not lot-aware.

Case 2 (2025-01-13 ByBit USDT) shows the inverse failure: CG has ~109 USDT lot disposals showing small individual gains (sum `+<CG_LOTS_EUR> EUR`, characterized in Task 1; the plan originally estimated `<+OGR_NET_EUR>` but that figure is the OGR-row total, not the CG-lot aggregate) because reward lots were acquired at near-zero cost; OGR has realized losses totalling `<-OGR_NET_EUR> EUR` (rows 10, 16, 17: 0.15 + <FUTURES_FEE_EUR> + <REALIZED_LOSS_EUR>). The direction override flips every individual lot sign to negative while preserving CG magnitude (`ogr_handler.py:274-278`: `final_gain_loss = -abs(entry.gain_loss_eur)`), producing an aggregated `-<CG_LOTS_EUR> EUR` in Crypto Gains, which is economically wrong because spot fee disposals cannot inherit derivatives P&L attribution (the override should not touch these lots at all). The `<-OGR_NET_EUR> EUR` OGR net is real and belongs in Derivatives P&L, not Crypto Gains.

### Examples (before → after)

**Before (Case 1):** Crypto Gains sheet shows one row: `2025-01-12 USDT ByBit gain=<MIXED_AGGREGATE_EUR> EUR` (mixes <PROFIT_EUR> futures profit with <FEE_PROCEEDS_EUR> fee disposal).

**After (Case 1):**
- Crypto Gains sheet shows one row: `2025-01-12 USDT ByBit gain=<FEE_GAIN_EUR> EUR` (spot fee disposal only, CG authoritative).
- Derivatives P&L sheet shows two rows: `2025-01-12 USDT ByBit Type=PROFIT P&L=<PROFIT_EUR> EUR` and `2025-01-12 USDT ByBit Type=FEE P&L=<-FEE_PROCEEDS_EUR> EUR` (both under art. 10(1)(e), always taxed, no 365-day exemption).

**Before (Case 2):** Crypto Gains sheet shows ~109 flipped-to-negative rows totalling `-<CG_LOTS_EUR> EUR` (CG-lot aggregate magnitude, direction-flipped by the override; NOT the <-OGR_NET_EUR> OGR total).

**After (Case 2):**
- Crypto Gains sheet shows the original ~109 rows with their true small gains (`+<CG_LOTS_EUR> EUR` aggregate), **signs not flipped**.
- Derivatives P&L sheet shows the OGR rows for that date (funding fee, futures fees, realized P&L) summed by `(date, asset, platform, event_type)`, reported under art. 10(1)(e). The OGR net (`<-OGR_NET_EUR> EUR`) appears in Derivatives P&L, not in Crypto Gains.

### Classification model (verified against actual fixtures)

The classifier inspects each OGR row individually (the parser must stop pre-summing; see Task 6) and returns a sealed result:

| OGR row shape | CG counterpart? | Classification | Destination |
|---|---|---|---|
| `Type=Profit` | N/A (profits never have CG entries in Koinly's model) | `Derivatives("OGR Profit; no CG counterpart possible")` | Derivatives P&L |
| `Type=Loss` | Yes (exact EUR value match within tolerance) | `Spot("OGR Loss matches CG disposal")` | spot_index (current behavior) |
| `Type=Loss` | No | `Derivatives("OGR Loss with no CG counterpart; derivatives realization")` | Derivatives P&L |
| `Type=Loss` | Partial match (value mismatch beyond tolerance, or multiple ambiguous CG entries) | `Derivatives(review_required=True, "Ambiguous: OGR/CG value mismatch; manual review needed")` | Derivatives P&L with review flag |

### Edge cases motivating the design

1. **OGR Profit row with no CG entry** (Case 1 row 8, <PROFIT_EUR> EUR): always classified as derivatives; routed to Derivatives P&L. The Crypto Gains sheet is unaffected because there is no CG entry to override.
2. **OGR Loss row with matching CG entry** (Case 1 row 9, <-FEE_PROCEEDS_EUR> EUR): classified as spot; stays in spot_index; CG retains its FIFO-derived gain. The override does not apply the OGR Loss to the CG entry because the CG entry already correctly reflects the disposal.
3. **Multiple OGR rows on the same key with mixed classification** (Case 2, 2025-01-13: 3 OGR rows, 109 CG lots): each OGR row is classified independently. Spot-classified OGR Loss rows stay in spot_index; derivatives-classified rows go to `derivatives_entries`. CG lots are never sign-flipped by derivatives OGR entries.
4. **OGR row with ambiguous CG match** (value mismatch beyond tolerance): classified as derivatives with `review_required=True`; `review_reason` cites the mismatch. The row is never silently dropped.
5. **Platform with no derivatives activity**: Derivatives P&L sheet renders with headers and an empty-state row ("No derivatives activity for this jurisdiction"), so the user can see the category was considered (development_lessons.md #93).
6. **Jurisdiction with `separate_derivatives_reporting=False`**: preserves current behavior exactly; single Crypto Gains sheet, OGR override applied to all entries, byte-identical output to pre-change. This is the backward-compatibility path required by `development_lessons.md` #84, verified by a characterization test with golden values captured before any code change.
7. **OGR missing entirely**: Derivatives P&L sheet renders empty state; Crypto Gains sheet processes normally with CG values (existing fallback path).
8. **Non-ByBit platform with unexpected OGR shape** (Kraken, Binance, etc.): any OGR `Profit` row, or `Loss` row without an exact CG match, is classified as derivatives. If the platform uses labels or Type values the classifier does not recognize, the row still routes through the rules above; no platform-specific allowlist is used. Ambiguous cases carry `review_required=True` so non-ByBit activity is flagged for manual review rather than silently classified (Monitor #2 mitigation).

## Evaluation Criteria

**Quality dimensions:**

- **Correctness (tax law alignment):** derivatives P&L is reported under art. 10(1)(e) (always taxed, no 365-day exemption); spot crypto retains art. 10(1)(k) treatment including the exemption. Verified by data trace tests using the ByBit 2025-01-12 and 2025-01-13 fixtures.
- **Correctness (data trace):** trace the user's actual ByBit data from OGR/CG CSV through parsing, row-level split, classification, aggregation, and Excel output. Assert the futures profit (<PROFIT_EUR> EUR) lands in Derivatives P&L and the fee disposal (<FEE_GAIN_EUR> EUR gain) lands in Crypto Gains. Required by `development_lessons.md` #72, #73.
- **Backward compatibility (byte-identical):** with `separate_derivatives_reporting=False`, the generated Excel for the ByBit fixtures is byte-identical to the pre-change output. Verified by a characterization test that captures golden values **before** any code change and asserts identity after.
- **No silent drops:** every OGR row appears in either the spot_index, the `derivatives_entries` list, or a `logger.warning` with a specific actionable reason. Unmatched rows must not be discarded (repository constraint).
- **Aggregation correctness:** Derivatives P&L aggregates by `(date, asset, platform, event_type)`, not by `(date, asset, platform)` alone, so a Profit and a Fee on the same day do not collapse into a single misleading net.
- **Review flags:** any derivatives entry that cannot be confidently classified (ambiguous CG match, unrecognized Type) is emitted with `review_required=True` and a specific `review_reason` per PT-C-030.
- **Auditability:** the Derivatives P&L tab cites the legal basis (art. 10(1)(e)) in its header so a reader cannot mistake it for cryptoasset treatment.

**Release gates:**

- Tier 1 tests pass (see Validation Commands).
- Tier 2 full regression passes.
- New data trace test using the real ByBit fixtures in `resources/source/koinly2025/` confirms Case 1 and Case 2 outputs.
- `uv run ruff check src tests`: clean.
- Manual review of generated Excel: Derivatives P&L tab present, Crypto Gains tab no longer contains the mixed gain.
- Authoritative documents archived under `docs/tax/laws/pt/crypto-tax/official/` with `sources.md` entries (provenance rule: project-guidelines #1). Secondary sources (blogs) go under `docs/tax/laws/pt/crypto-tax/` (non-official), never under `official/`.

## Review Scope

**Explicit must-fix**: findings on these paths are always in scope (review and fix if valid):

**Production code:**
- `src/tax_reporting/domain/jurisdiction.py`: add `separate_derivatives_reporting: bool` field
- `src/tax_reporting/application/crypto/entities.py`: add `DerivativesEventType(Enum)`, `DerivativesPnLEntry` dataclass, `DerivativesClassification` sealed result; add `derivatives_entries` field to `CryptoTaxReport`
- `src/tax_reporting/application/crypto/classification.py`: add `classify_derivatives_event()` returning `DerivativesClassification`
- `src/tax_reporting/infrastructure/koinly_parser.py`: change `_find_and_parse_other_gains_file` to return `list[ParsedOgrRow]`; add separate `_build_ogr_index()` for the summed dict (backward compat)
- `src/tax_reporting/application/crypto/ogr_handler.py`: add `_split_ogr_index()`; update `_apply_ogr_direction_override` to accept flag and branch cleanly
- `src/tax_reporting/application/crypto/aggregation.py`: add `aggregate_derivatives_entries()` mirroring `_aggregate_capital_entries()`
- `src/tax_reporting/application/crypto_reporting.py`: wire classification, split, aggregation; insert split at line ~203 (post-FIFO, post-validation, pre-override)
- `src/tax_reporting/application/persisting/derivatives_sheet.py` *(new)*: new Excel tab renderer
- `src/tax_reporting/application/persisting/workbook_builder.py`: register the new sheet
- `docs/tax/decision_points/2025.md`: add DP-012
- `docs/tax/decision_points/2025.toml`: add `separate_derivatives_reporting = true` under `[countries.PT]`
- `docs/tax/laws/pt/crypto-tax/sources.md`: add new authoritative document entries
- `docs/tax/laws/pt/crypto-tax/official/`: archive AT binding ruling 28298/2025 if publicly available
- `docs/tax/laws/pt/crypto-tax/` *(non-official)*: secondary-source summary if AT ruling is not publicly available
- `docs/domain/crypto_rules.md`: add PT-C-034 (derivatives separation rule); update PT-C-033 to be flag-conditional
- `docs/domain/crypto_reporting_guidelines.md`: document the new tab and the split pipeline
- `docs/domain/crypto_implementation_guidelines.md`: capture implementation lessons
- `README.md`: add Derivatives P&L tab to the Excel Report Features section

**Tests:**
- `tests/unit/application/test_crypto_entities.py`: `DerivativesEventType`, `DerivativesPnLEntry`, `CryptoTaxReport.derivatives_entries`
- `tests/unit/application/test_crypto_classification.py`: `classify_derivatives_event()` with sealed-result assertions
- `tests/unit/application/test_crypto_parsing.py`: new `list[ParsedOgrRow]` return shape; `_build_ogr_index()` backward compat
- `tests/unit/application/test_crypto_reporting.py`: extend OGR override tests; add characterization test (golden values); add backward-compat tests for `separate_derivatives_reporting=False`; update `test_build_ogr_index` (line 7444) and related index tests for new parser shape
- `tests/unit/application/persisting/test_derivatives_sheet.py` *(new)*: tab rendering tests
- `tests/unit/application/persisting/test_workbook_builder.py`: verify new tab registered when flag on, skipped when off
- `tests/unit/application/persisting/test_assumptions_sheet.py`: methodology citation test only (NOT the 11 deferred branch-review findings)
- `tests/end_to_end/test_crypto_derivatives_separation.py` *(new)*: full pipeline trace with ByBit fixtures

**Plan-related extension**: implementation and review may change files not listed above. Treat a finding as in scope when it is **causally related to this plan**: it implements or completes a plan task, fixes a regression introduced by plan work, closes wiring or docs implied by an explicit must-fix change, or contradicts a contract the plan changed. If the link to the plan is weak or speculative, drop as out of scope with a one-line reason.

**Out of scope; reject unless plan-related:**
- `src/tax_reporting/application/persisting/assumptions_sheet.py`: 11 branch-review findings are deferred to a separate plan; the only allowed touch is adding one methodology item citing art. 10(1)(e) (Task 13).
- `docs/domain/development_lessons.md`: only touch if a genuinely new lesson emerges during implementation; do not retroactively edit.
- FIFO engine (`src/tax_reporting/application/crypto_fifo/`), unchanged; loan-affected assets still rebuilt from TH per existing rules.

## Design Invariants (CR Guard)

Prior-phase decisions and repository contracts that must not be compromised:

1. **OGR overrides BEFORE aggregation** (CLAUDE.md repository constraint, `development_lessons.md` #75, #78): CG rows are FIFO lots that get summed in aggregation; OGR contains the correct total for the disposal event. The derivatives split must also occur before aggregation so lot-level trail is preserved.
2. **Pipeline ordering; split after FIFO rebuild and country validation** (r1 Blocker 8): the `_split_ogr_index()` call happens at `crypto_reporting.py:~203` (after FIFO rebuild at lines 169-193 and country validation at line 197, immediately before `_apply_ogr_direction_override`). This ensures the classifier sees the final pre-aggregation `capital_entries`, including FIFO-rebuilt lots. A derivatives OGR row whose only CG counterpart was added by FIFO rebuild must be correctly classified as having a CG counterpart.
3. **Post-aggregation validation only** (CLAUDE.md repository constraint): validation that depends on complete state runs after all rows are accumulated. The derivatives index must tolerate mid-accumulation incomplete state.
4. **No silent drops**: unmatched OGR derivatives rows must be logged at `logger.warning` with a specific actionable reason, never discarded.
5. **`review_required=True` carries specific reason** (PT-C-030): the Excel output shows "YES: \<reason\>", not a bare boolean.
6. **Directional authority applies within event category only** (`development_lessons.md` #78, refined): when OGR and CG disagree on direction, OGR is authoritative, but only when both belong to the same category. Spot CG signs must not be flipped by derivatives OGR entries under the new model.
7. **Aggregation field semantics** (`development_lessons.md` #80): aggregated values are derived from the full entry list, not by summing subtotals, so unrecognized holding periods do not produce inconsistent statistics.
8. **Recalculate validation from aggregated values** (`development_lessons.md` #85): any cross-check on derivatives totals must read from the aggregated `derivatives_entries`, not from pre-aggregation state.
9. **Decision-point TOML/MD synchronized** (CLAUDE.md): both files must be updated together; the TOML drives runtime config, the MD is the human-readable decision record.
10. **Authoritative source provenance** (project-guidelines #1, CLAUDE.md): every new file under `docs/tax/.../official/` gets a `sources.md` entry with URL, issuing date, effective date, superseded date, purpose, and provisions consulted. **Secondary sources (blogs, FAQ pages) never go under `official/`**: they go under the parent `docs/tax/laws/pt/crypto-tax/` directory with a `sources.md` entry marked "secondary source."
11. **Backward compatibility default-safe and byte-identical** (`development_lessons.md` #84): the new flag defaults to `False`. With the flag `False`, the generated output must be byte-identical to the pre-change output. A characterization test captures golden values **before** any source code change and asserts identity after.
12. **FIFO rebuild assets unchanged**: `CryptoTaxReport.fifo_rebuild_assets` continues to carry loan-affected assets discovered via `discover_loan_affected_assets()`; derivatives separation does not affect loan repayment exclusion (DP-001).
13. **Sealed classifier result** (user CLAUDE.md sealed-class sentinel pattern): `classify_derivatives_event()` returns `DerivativesClassification` with variants `Derivatives(reason)`, `Spot(reason)`, `Ambiguous(reason)`. Only `Derivatives` variants become `DerivativesPnLEntry`; `Ambiguous` variants also become `DerivativesPnLEntry` but with `review_required=True`; `Spot` variants stay in the spot index. No boolean conflation.
14. **Row-level OGR parsing** (r1 Blocker 7): `_find_and_parse_other_gains_file` returns `list[ParsedOgrRow]` (not a pre-summed dict). Summing into the dict happens in a separate `_build_ogr_index()` function that backward-compatible callers use. The classifier sees individual rows so mixed-key handling works.
15. **No platform-specific allowlists or amount thresholds** (r1 Monitor #2, CLAUDE.md §4): the classifier uses OGR `Type` and CG-counterpart existence only. No hardcoded asset ticker allowlist (USDT/USDC/USD/BTC/ETH), no amount threshold (>100 EUR), no platform allowlist (ByBit). These were proposed in the investigation and rejected because they are fragile and over-classify legitimate spot trades.
16. **`DerivativesPnLEntry` is frozen** (r1 Low #3): uses `@dataclass(frozen=True)` matching `CryptoCapitalGainEntry` and `CryptoRewardIncomeEntry`.
17. **Event type uses enum, not string** (r1 Medium #1): `DerivativesEventType(Enum)` with `PROFIT`, `LOSS`. Used in `DerivativesPnLEntry.event_type` and as part of the aggregation key. (`FEE` variant deferred; see Monitor section.)
18. **`holding_period` deliberately omitted** (r1 Medium #2): `DerivativesPnLEntry` has no `holding_period` field because art. 10(1)(e) derivatives have no 365-day exemption. This is documented in the class docstring so future maintainers do not treat it as a gap.

## Validation Commands

**Tier 1; must-fix scope (must pass for plan completion):**

```bash
# Characterization test (captured before any code change, must remain GREEN throughout)
uv run pytest tests/unit/application/test_crypto_reporting.py::TestOgrCharacterizationGolden -v

# New entities, classifier, parser shape
uv run pytest tests/unit/application/test_crypto_entities.py -k "DerivativesEventType or DerivativesPnLEntry or derivatives_entries" -v
uv run pytest tests/unit/application/test_crypto_classification.py -k "Derivatives" -v
uv run pytest tests/unit/application/test_crypto_parsing.py -k "ogr_row_list or build_ogr_index" -v

# Split, aggregation, pipeline integration
uv run pytest tests/unit/application/test_crypto_reporting.py -k "OgrSplit or DerivativesAggregation or PipelineIntegration or backward_compat_flag_false" -v

# Existing OGR override tests still pass with new flag defaulting False
uv run pytest tests/unit/application/test_crypto_reporting.py -k "ogr or Ogr" -v

# New Excel tab
uv run pytest tests/unit/application/persisting/test_derivatives_sheet.py -v
uv run pytest tests/unit/application/persisting/test_workbook_builder.py -k "derivatives" -v

# Methodology citation only (not the 11 deferred findings)
uv run pytest tests/unit/application/persisting/test_assumptions_sheet.py::test_methodology_includes_derivatives_legal_basis -v

# End-to-end data trace with real ByBit fixtures
uv run pytest tests/end_to_end/test_crypto_derivatives_separation.py -v

# Lint clean
uv run ruff check src tests

# Decision-point TOML/MD in sync (use -E for BSD grep on macOS; per CLAUDE.md)
grep -Ec "DP-012|separate_derivatives_reporting" docs/tax/decision_points/2025.md
grep -Ec "DP-012|separate_derivatives_reporting" docs/tax/decision_points/2025.toml

# Authoritative doc provenance: every new official file has a sources.md entry
for f in docs/tax/laws/pt/crypto-tax/official/at_piv_28298*; do
  [ -f "$f" ] && grep -q "$(basename "$f")" docs/tax/laws/pt/crypto-tax/sources.md || echo "MISSING SOURCES ENTRY: $f"
done
```

**Tier 2; full regression (informational; any failure blocks release):**

```bash
uv run pytest -m unit
uv run pytest tests/end_to_end/
```

**Manual Excel check:**

```bash
uv run tax-reporting --example --output-dir /tmp/derivatives-separation-check
# Open the Excel and verify: Derivatives P&L tab present, Crypto Gains tab no longer mixes derivatives
```

## Monitor

Deferred risks with named triggers and owners. Each item has a specific condition that, when observed, prompts a follow-up plan or task.

1. **`FEE` event-type variant deferred**: `DerivativesEventType` ships with `PROFIT` and `LOSS` only. The `FEE` variant is deferred because the current ByBit fixtures do not distinguish a futures-fee OGR row from a realized-P&L OGR row (both have `Type=Loss`). **Trigger to add `FEE`:** when a Koinly export from any platform produces an OGR `Type=Loss` row whose description or TH counterpart explicitly identifies it as a futures fee (distinct from realized P&L), add `FEE` to the enum and update `_event_type_from_row_type` mapping. Owner: future contributor adding the first non-ByBit derivatives platform.
2. **Aggregate-match direction precedence**: Task 5's classifier branch `ogr_loss_multiple_cg_entries_aggregate_match` returns `Spot` when N CG lots' summed gain matches the OGR Loss magnitude within 1 cent. Direction disagreement (CG aggregate positive vs OGR Loss negative) takes precedence over magnitude match, so Case 2 (lots sum `<+OGR_NET_EUR>`, OGR sums `<-OGR_NET_EUR>`) correctly does NOT fire this branch. **Trigger to add an explicit test:** if a future dataset shows lots summing to a small positive value that matches a small OGR Loss magnitude (direction agreement, magnitude match), add `TestDerivativesClassifier#aggregate_match_with_direction_agreement_and_partial_derivatives_mix` to verify the classifier does not over-classify mixed lots as Spot. Owner: future contributor reviewing the aggregate-match branch.
3. **Characterization golden value stability**: Task 1 captures golden values from the current pipeline. If an unrelated PR changes parser behavior (e.g., fee-token normalization) before this plan lands, the golden values become stale. **Mitigation:** Task 1 writes `source_sha` (the git commit hash at capture time, via `git rev-parse HEAD`) into the characterization golden fixture (local); the characterization test asserts the field matches the pre-implementation commit. Owner: this plan's implementer (Task 1).

### Task 1: Capture characterization golden values (BEFORE any source change)

Files:
- `tests/unit/application/test_crypto_reporting.py`: add `TestOgrCharacterizationGolden` class
- the characterization golden fixture (local) *(new, temporary)*: captured output snapshot

This task runs **before** Tasks 2-14. It captures the current OGR override output for the ByBit Case 1 and Case 2 fixtures with `separate_derivatives_reporting=False` (the only behavior that exists today). These golden values are the backward-compatibility target.

- [x] `TestOgrCharacterizationGolden#case1_gain_before_separation`: given ByBit Case 1 fixtures with the current pipeline, expects the Crypto Gains aggregated gain for `(2025-01-12, USDT, ByBit)` to equal `<MIXED_AGGREGATE_EUR> EUR` (the current mixed value). This test captures today's behavior. Captured value matches.
- [x] `TestOgrCharacterizationGolden#case2_gain_before_separation`: given ByBit Case 2 fixtures with the current pipeline, expects the Crypto Gains aggregated gain for `(2025-01-13, USDT, ByBit)` to equal **`-<CG_LOTS_EUR> EUR`** (the ACTUAL current override output; plan originally stated `<-OGR_NET_EUR> EUR` but that is the OGR-row total, not the override output; the override at `ogr_handler.py:274-278` preserves CG magnitude and flips direction only, so 109 lots summing +<CG_LOTS_EUR> become -<CG_LOTS_EUR>). See the characterization golden fixture (local) `case2_note` for the full reconciliation. Downstream tasks (7, 11) use -<CG_LOTS_EUR> for the Crypto Gains backward-compat assertion; the <-OGR_NET_EUR> OGR net remains valid for `derivatives_entries`.
- [x] Run → expect GREEN (captures current behavior): `uv run pytest tests/unit/application/test_crypto_reporting.py::TestOgrCharacterizationGolden -v`: 2 passed.
- [x] After Tasks 2-14: re-run with `separate_derivatives_reporting=False` and assert the same golden values. The flag-off path must be byte-identical to today. *(deferred to Task 14 final validation; verified in Task 14: Case 1=<MIXED_AGGREGATE_EUR>, Case 2=-<CG_LOTS_EUR>, derivatives_entries=0)*
- [x] Record `source_sha = $(git rev-parse HEAD)` in the characterization golden fixture (local) at capture time (Monitor #3 mitigation). The characterization test asserts this hash matches the pre-implementation commit when run post-implementation. Recorded `f46568b`.
- [x] Commit: `test(characterization): capture OGR override golden values before derivatives separation`: 875686b

### Task 2: Archive authoritative documents and record provenance

Files:
- `docs/tax/laws/pt/crypto-tax/official/at_piv_28298_2025.pdf` *(new, if publicly available)*
- `docs/tax/laws/pt/crypto-tax/cryptotaxesportugal_futures_faq_2026-06-13.md` *(new, under non-official parent; NOT under `official/`)*
- `docs/tax/laws/pt/crypto-tax/sources.md`
- `docs/tax/laws/pt/crypto-tax/README.md`: only if a derivatives-specific ofício circulado is discovered

- [x] Search the AT information vinculativa portal (`https://info.portaldasfinancas.gov.pt/pt/informacao_fiscal/informacoes_vinculativas/rendimento/cirs/`) for Processo 28298/2025; if publicly available, download the PDF and save as `official/at_piv_28298_2025.pdf`. **Publicly available** (contrary to plan expectation); downloaded 64,788-byte 3-page PDF from `.../Documents/PIV_28298.pdf`. PIV paragraphs 18/21/22/23 confirm: futures = art. 10(1)(e); taxed at fiat conversion; resident source → Anexo G Quadro 13 code G51 (englobamento Quadro 15); non-resident source → Anexo J Quadro 9.2.B code G30.
- [x] If the AT ruling is NOT publicly available (binding rulings are often request-specific), archive the cryptotaxesportugal.com FAQ page as a markdown mirror at `docs/tax/laws/pt/crypto-tax/cryptotaxesportugal_futures_faq_2026-06-13.md`: this is under the parent directory, NOT under `official/`, because a blog summary is not source-origin (r1 Medium #5). Archived as a SUPPLEMENTARY secondary source (the PIV was public, so the FAQ is not the fallback but a plain-English companion). Marked SECONDARY with provenance header.
- [x] Verify `cirs_art10_portal_2026-04-01.html` contains both paragraph (e) ("instrumentos financeiros derivados") and paragraph (k) (cryptoassets). Record the verification with a date-stamped note in `sources.md`. Both verified verbatim; recorded in sources.md.
- [x] Search the AT ofício circulado index for any circular specifically addressing financial derivatives classification. If found, archive as `official/at_oficio_circulado_derivatives_<num>_<year>.pdf`; if not, record the search query and date in `sources.md`. No dedicated derivatives ofício circulado found; search query + date recorded. Ofício Circulado 20278/2025 remains operative.
- [x] Verify `modelo3_anexo_g_2026.pdf` includes a line/field for financial derivatives reporting. Record the field reference in `sources.md`. Quadro 13 "INSTRUMENTOS FINANCEIROS DERIVADOS" with income code G51 verified via pdftotext; crypto-asset disposals stay on Quadro 18/18A/18B. Recorded in sources.md.
- [x] Add a `sources.md` entry for every newly archived file. Official entries follow the existing 9-entry format (URL, issuing date, effective date, superseded date, purpose, provisions consulted). Secondary sources explicitly marked "Secondary source; underlying AT ruling not publicly available; retrieval attempted on 2026-06-13; legal basis cited from consolidated CIRS, not from this blog.": Entries #14 (PIV, official) and #15 (FAQ, secondary) appended.
- [x] Commit: `docs(tax): archive AT binding ruling 28298/2025 provenance and derivatives guidance`: a379733

### Task 3: Add decision point DP-012 and jurisdiction flag

Files:
- `docs/tax/decision_points/2025.md`
- `docs/tax/decision_points/2025.toml`
- `src/tax_reporting/domain/jurisdiction.py`
- `tests/unit/application/test_crypto_reporting.py`

- [x] `TaxJurisdictionConfig#separate_derivatives_reporting_default_false`: given a `TaxJurisdictionConfig` constructed with no `separate_derivatives_reporting`, expects the field to default to `False`
- [x] `TaxJurisdictionConfig#separate_derivatives_reporting_true_from_toml`: given decision-point TOML with `separate_derivatives_reporting = true` under `[countries.PT]`, expects the loaded config to have the flag `True`
- [x] Run → expect RED: `uv run pytest tests/unit/application/test_crypto_reporting.py -k "separate_derivatives_reporting" -v`: 2 failed (AttributeError + unknown-flag rejection from auto-discovery gate)
- [x] Add `separate_derivatives_reporting: bool = False` to `TaxJurisdictionConfig` in `src/tax_reporting/domain/jurisdiction.py` with a docstring citing DP-012 and CIRS art. 10(1)(e)
- [x] Add DP-012 row to the decision-points table in `docs/tax/decision_points/2025.md`: "Separate derivatives P&L from spot crypto? **Yes** (PT). Legal basis: CIRS art. 10(1)(e) vs art. 10(1)(k); AT binding ruling 28298/2025; Derivatives reported under art. 10(1)(e) with no 365-day exemption; spot retains art. 10(1)(k)"
- [x] Add `separate_derivatives_reporting = true` under `[countries.PT]` in `docs/tax/decision_points/2025.toml` with a comment block citing DP-012 and the legal basis
- [x] Run → expect GREEN; 2 passed; 437 unit tests pass (no regression); 0 new ruff errors
- [x] Commit: `feat(jurisdiction): add separate_derivatives_reporting flag (DP-012)`: e22b3fc

### Task 4: Add entities: `DerivativesEventType`, `DerivativesPnLEntry`, `DerivativesClassification`

Files:
- `src/tax_reporting/application/crypto/entities.py`
- `tests/unit/application/test_crypto_entities.py`

- [x] `TestDerivativesEventType#enum_values`: given `DerivativesEventType`, expects exactly `PROFIT`, `LOSS` members (FEE is deferred until a futures-fee OGR row distinct from realized P&L is observed in fixtures; see Monitor section)
- [x] `TestDerivativesPnLEntry#construction`: given date/asset/platform/pnl_eur/event_type, expects a frozen dataclass with those fields plus `source_ref: str`, `legal_category: str = "CIRS art. 10(1)(e)"`, `review_required: bool = False`, `review_reason: str = ""`
- [x] `TestDerivativesPnLEntry#frozen`: given a constructed `DerivativesPnLEntry`, expects mutation to raise `FrozenInstanceError`
- [x] `TestDerivativesPnLEntry#no_holding_period_field`: given the dataclass fields, expects `holding_period` to be absent (deliberate omission per art. 10(1)(e), no 365-day exemption)
- [x] `TestDerivativesClassification#sealed_variants`: given `DerivativesClassification`, expects exactly three variants: `Derivatives(reason: str)`, `Spot(reason: str)`, `Ambiguous(reason: str)`; each carries its reason
- [x] `TestCryptoTaxReport#derivatives_entries_default_empty`: given a `CryptoTaxReport` constructed without `derivatives_entries`, expects the field to default to an empty list
- [x] Run → expect RED: `uv run pytest tests/unit/application/test_crypto_entities.py -k "DerivativesEventType or DerivativesPnLEntry or DerivativesClassification or derivatives_entries" -v`: ImportError (names did not exist)
- [x] Add `DerivativesEventType(Enum)` with `PROFIT`, `LOSS` to `entities.py` (FEE deferred; see Monitor section)
- [x] Add `@dataclass(frozen=True) DerivativesPnLEntry` with fields: `date: str`, `asset: str`, `platform: str`, `pnl_eur: Decimal`, `event_type: DerivativesEventType`, `source_ref: str`, `legal_category: str = "CIRS art. 10(1)(e)"`, `review_required: bool = False`, `review_reason: str = ""`. Class docstring: "Note: `holding_period` is intentionally absent because art. 10(1)(e) derivatives have no 365-day exemption (unlike art. 10(1)(k) cryptoassets); all derivatives realizations are taxed regardless of holding duration."
- [x] Add `DerivativesClassification` sealed result with variants `Derivatives(reason)`, `Spot(reason)`, `Ambiguous(reason)`. Implement as a frozen dataclass with a `kind: str` discriminator plus `reason: str`, or as a sealed class hierarchy; either is acceptable as long as the three variants are distinct and carry a reason. Chose frozen-dataclass-with-`kind`-discriminator; `Derivatives`/`Spot`/`Ambiguous` class-method constructors.
- [x] Add `derivatives_entries: list[DerivativesPnLEntry] = field(default_factory=list)` to `CryptoTaxReport`
- [x] Run → expect GREEN; 6 passed; 26 entities suite pass; 437 unit pass; ruff clean
- [x] Commit: `feat(entities): add DerivativesEventType, DerivativesPnLEntry, DerivativesClassification, CryptoTaxReport.derivatives_entries`: c44175b

### Task 5: Implement derivatives classifier with sealed result

Files:
- `src/tax_reporting/application/crypto/classification.py`
- `tests/unit/application/test_crypto_classification.py`

The classifier uses two signals only: OGR `Type` and CG-counterpart existence. No TH-label allowlist (the actual TH label `"Realized gain"` is used for many event types and is not derivatives-specific; r1 Blocker 2). No asset allowlist. No amount threshold.

- [x] `TestDerivativesClassifier#ogr_profit_no_cg_counterpart`: given an OGR row with `Type=Profit` and no CG counterpart on the same key, expects `DerivativesClassification.Derivatives` with reason `"OGR Profit; derivatives P&L realization"`
- [x] `TestDerivativesClassifier#ogr_loss_exact_cg_match`: given an OGR row with `Type=Loss` and a CG entry on the same key whose EUR value matches within `0.01 EUR` tolerance, expects `DerivativesClassification.Spot` with reason `"OGR Loss matches CG disposal; spot fee"`
- [x] `TestDerivativesClassifier#ogr_loss_no_cg_counterpart`: given an OGR row with `Type=Loss` and no CG entry on the same key, expects `DerivativesClassification.Derivatives` with reason `"OGR Loss with no CG counterpart; derivatives realization"`
- [x] `TestDerivativesClassifier#ogr_loss_value_mismatch_ambiguous`: given an OGR row with `Type=Loss` and a CG entry on the same key whose EUR value differs by more than `0.01 EUR`, expects `DerivativesClassification.Ambiguous` with reason citing the mismatch (e.g., `"OGR=-<FUTURES_FEE_EUR> vs CG=-5.00 on (2025-01-13, USDT, ByBit), manual review needed"`)
- [x] `TestDerivativesClassifier#ogr_loss_multiple_cg_entries_ambiguous`: given an OGR row with `Type=Loss` and multiple CG entries on the same key (Case 2 shape: 109 lots), expects `DerivativesClassification.Ambiguous` with reason citing the count (e.g., `"OGR=-<REALIZED_LOSS_EUR> vs 109 CG lots on (2025-01-13, USDT, ByBit), aggregate-match check required"`)
- [x] `TestDerivativesClassifier#ogr_loss_multiple_cg_entries_aggregate_match`: given an OGR row with `Type=Loss` and multiple CG entries whose aggregate EUR value matches the OGR value within tolerance, expects `DerivativesClassification.Spot` with reason `"OGR Loss aggregate-matches N CG lots; spot fee disposals"`
- [x] Run → expect RED: `uv run pytest tests/unit/application/test_crypto_classification.py -k "DerivativesClassifier" -v`: 6 failed (ImportError)
- [x] Implement `classify_derivatives_event(ogr_row: ParsedOgrRow, cg_matches: list[CryptoCapitalGainEntry]) -> DerivativesClassification` in `classification.py`. Logic:
  - If `ogr_row.row_type == "Profit"`: return `Derivatives(reason="OGR Profit; derivatives P&L realization")` (profits never have CG counterparts in Koinly's model).
  - If `ogr_row.row_type == "Loss"`:
    - If `len(cg_matches) == 0`: return `Derivatives(reason="OGR Loss with no CG counterpart; derivatives realization")`.
    - If `len(cg_matches) == 1` and `abs(cg_matches[0].**proceeds_eur** - abs(ogr_row.gain_loss)) <= TOLERANCE`: return `Spot(reason="OGR Loss matches CG disposal; spot fee")`. **(DESIGN CORRECTION: pseudocode said `gain_loss_eur`; corrected to `proceeds_eur`: OGR Value column is disposal proceeds, so the matching CG quantity is `proceeds_eur` not `gain_loss_eur`. Verified against Case 1 fixture: OGR <FEE_PROCEEDS_EUR> matches CG proceeds_eur <FEE_PROCEEDS_EUR>, not gain_loss_eur <FEE_GAIN_EUR>.)**
    - If `len(cg_matches) > 1` and `abs(sum(cg.**proceeds_eur** for cg in cg_matches) - abs(ogr_row.gain_loss)) <= TOLERANCE`: return `Spot(reason=f"OGR Loss aggregate-matches {len(cg_matches)} CG lots; spot fee disposals")`. **(Same proceeds_eur correction.)**
    - Otherwise single-CG mismatch: return `Ambiguous(reason=f"OGR={ogr_row.gain_loss} vs CG={cg_matches[0].proceeds_eur} on ({ogr_row.date}, {ogr_row.asset}, {ogr_row.wallet}), manual review needed")`.
    - Otherwise multi-CG no-aggregate-match: return `Ambiguous(reason=f"OGR={ogr_row.gain_loss} vs {len(cg_matches)} CG lots on ({ogr_row.date}, {ogr_row.asset}, {ogr_row.wallet}), aggregate-match check required")`. **(DESIGN CORRECTION: split the single Ambiguous branch into two by CG-count so the reason suffix matches the test expectations.)**
  - TOLERANCE is `Decimal("0.01")` (1 cent). This is the only numeric threshold in the classifier and it is a matching tolerance, not a classification threshold; flagged here per CLAUDE.md §4.
- [x] Run → expect GREEN; 6 passed; 437 unit pass; ruff clean
- [x] Commit: `feat(classification): add sealed-result derivatives classifier using OGR Type and CG-counterpart signals`: 36fee52 (inline recovery: done sub-agent truncated after learn)

### Task 6: Change OGR parser to return row list; add `_build_ogr_index` for backward compat

Files:
- `src/tax_reporting/infrastructure/koinly_parser.py`
- `tests/unit/application/test_crypto_parsing.py`
- `tests/unit/application/test_crypto_reporting.py`: update `test_build_ogr_index` (line 7444) and related index tests

This task changes the return type of `_find_and_parse_other_gains_file` from `dict[tuple[str,str,str], Decimal]` to `list[ParsedOgrRow]`. The summing logic moves into a new `_build_ogr_index()` function that preserves the old contract for backward-compatible callers.

- [x] `TestOtherGainsParse#returns_list_of_parsed_rows`: given an OGR CSV with 3 rows, expects `_find_and_parse_other_gains_file()` to return a `list[ParsedOgrRow]` of length 3, each carrying `(date, asset, gain_loss, row_type, wallet)`: NOT a pre-summed dict
- [x] `TestOtherGainsParse#preserves_per_row_type`: given two OGR rows on the same `(date, asset, wallet)` key with different `Type` values (Profit and Loss), expects both rows to appear separately in the returned list with their original Type preserved (no summing)
- [x] `TestBuildOgrIndex#sums_into_dict`: given a `list[ParsedOgrRow]` with duplicate keys, expects `_build_ogr_index(rows)` to return `dict[(date, asset, wallet), Decimal]` with values summed (current behavior)
- [x] `TestBuildOgrIndex#backward_compat_matches_old_behavior`: given the ByBit Case 1 fixtures, expects `_build_ogr_index(_find_and_parse_other_gains_file(koinly_dir))` to produce the same dict that the old `_find_and_parse_other_gains_file` used to produce (regression target)
- [x] Run → expect RED: `uv run pytest tests/unit/application/test_crypto_parsing.py -k "parsed_rows or build_ogr_index or backward_compat" -v`
- [x] Add `ParsedOgrRow` typed structure (frozen dataclass) to `koinly_parser.py` or `entities.py`: `date: str` (ISO format, normalized via `format_datetime`), `asset: str` (normalized via `normalize_asset_ticker`), `gain_loss: Decimal`, `row_type: str`, `wallet: str` (normalized via `normalize_platform_name`: the parse-row function must be updated to call this, see below).
- [x] Change `_parse_other_gains_row` return type from `tuple[datetime, str, Decimal, str, str] | None` to `ParsedOgrRow | None`. The `date` field becomes a `str` (ISO format, produced by `format_datetime` at parse time) so downstream consumers (classifier, `_build_ogr_index`) receive a normalized string key directly. **Asset normalization (`normalize_asset_ticker`) already happens at `koinly_parser.py:333` and stays.** **Wallet normalization must change**: the current line 337 does bare `.strip()`, but `_build_ogr_index` at `ogr_handler.py:116` currently calls `normalize_platform_name()` on the raw wallet. Since Task 6 re-signatures `_build_ogr_index` into a pure summing loop (no normalization), `_parse_other_gains_row` line 337 must be updated to call `normalize_platform_name(ogr_row.get("Wallet Name", ""))` instead of `.strip()`: otherwise `test_ogr_index_handles_wallet_aliases` (line 7565) breaks because "ByBit (2)" no longer normalizes to "ByBit".
- [x] Change `_find_and_parse_other_gains_file(koinly_dir: Path) -> list[ParsedOgrRow]`. Remove the summing line (`result[key] = result.get(key, Decimal("0")) + gain_loss`). Each parsed row is appended to the list.
- [x] **Re-signature** the existing `_build_ogr_index` at `ogr_handler.py:95` from `(ogr_rows: list[dict])` to `(rows: list[ParsedOgrRow])`. The current implementation calls `_extract_ogr_gain_loss` and `parse_koinly_datetime` on raw dicts; under the new signature those parses already happened in `_parse_other_gains_row`, so `_build_ogr_index` becomes a pure summing loop over `ParsedOgrRow.gain_loss` keyed by `(ParsedOgrRow.date, ParsedOgrRow.asset, ParsedOgrRow.wallet)`. This is NOT a new function; the existing one is rewritten in place.
- [x] Update all 7 existing callers in `test_crypto_reporting.py` (lines 7444, 7489, 7509, 7529, 7558, 7586, 7616; the `test_build_ogr_index` and `test_ogr_index_*` cluster) to construct `list[ParsedOgrRow]` instead of raw dicts, or to call `_build_ogr_index(_find_and_parse_other_gains_file(...))`. Assertions on the summed dict shape remain unchanged.
- [x] Update `crypto_reporting.py:204` (the existing caller) to use `_build_ogr_index(_find_and_parse_other_gains_file(koinly_dir))` for the `separate_derivatives_reporting=False` path.
- [x] Run → expect GREEN (including the characterization test from Task 1)
- [x] Commit: `refactor(koinly_parser): return list[ParsedOgrRow] from OGR parser; add _build_ogr_index for backward compat`

### Task 7: Implement `_split_ogr_index` and update `_apply_ogr_direction_override`

Files:
- `src/tax_reporting/application/crypto/ogr_handler.py`
- `tests/unit/application/test_crypto_reporting.py`

- [x] `TestOgrSplit#profit_row_to_derivatives`: given a `list[ParsedOgrRow]` with one Profit row and no CG matches, expects `_split_ogr_index()` to return `derivatives_entries=[DerivativesPnLEntry(...)]` and `spot_index={}`
- [x] `TestOgrSplit#loss_with_cg_match_to_spot`: given a `list[ParsedOgrRow]` with one Loss row that matches a CG entry, expects `_split_ogr_index()` to return `spot_index={(date,asset,wallet): Decimal}` and `derivatives_entries=[]`
- [x] `TestOgrSplit#mixed_key_split_per_row`: given two OGR rows on the same key `(2025-01-12, USDT, ByBit)` where row 1 is Profit (<PROFIT_EUR>) and row 2 is Loss matching a CG entry (<-FEE_PROCEEDS_EUR>), expects row 1 in `derivatives_entries` and row 2 summed into `spot_index[(2025-01-12, USDT, ByBit)] = <-FEE_PROCEEDS_EUR>`
- [x] `TestOgrSplit#ambiguous_row_derivatives_with_review`: given an OGR Loss row with value mismatch to CG, expects the row in `derivatives_entries` with `review_required=True` and `review_reason` citing the mismatch
- [x] `TestOgrSplit#backward_compat_flag_false_returns_combined`: given `separate_derivatives_reporting=False`, expects `_split_ogr_index()` to return the combined summed index in `spot_index` and `derivatives_entries=[]` (no split occurs)
- [x] `TestOgrSplit#no_cg_no_th_tag_safety_net`: given an OGR Profit row with no CG counterpart and no recognizable TH tag, expects the row to appear in `derivatives_entries` (Profit type is always derivatives) AND a `logger.warning` emitted for the ambiguous platform case (r1 Medium #7)
- [x] `TestApplyOgrDirectionOverride#spot_signs_not_flipped_by_derivatives`: given Case 2 fixture (109 CG lots with small gains, separate_derivatives_reporting=True), expects each CG lot's `gain_loss_eur` to remain positive (spot fee disposal signs preserved), the derivatives loss is routed to `derivatives_entries` and never flips CG signs
- [x] `TestApplyOgrDirectionOverride#derivatives_profit_not_applied_to_spot_fee_entry`: given Case 1 fixture (one CG fee entry, separate_derivatives_reporting=True), expects the CG fee entry to retain its <FEE_GAIN_EUR> EUR gain and the <PROFIT_EUR> EUR profit to appear only in `derivatives_entries`
- [x] Run → expect RED: `uv run pytest tests/unit/application/test_crypto_reporting.py -k "OgrSplit or spot_signs_not_flipped or derivatives_profit_not_applied or no_cg_no_th_tag" -v`
- [x] Implement `_split_ogr_index(ogr_rows: list[ParsedOgrRow], capital_entries: list[CryptoCapitalGainEntry], jurisdiction: TaxJurisdictionConfig) -> tuple[dict[tuple[str,str,str], Decimal], list[DerivativesPnLEntry]]` in `ogr_handler.py`. Logic:
  - If `jurisdiction.separate_derivatives_reporting` is `False`: return `(_build_ogr_index(ogr_rows), [])`.
  - Otherwise: for each `row` in `ogr_rows`, find `cg_matches = [e for e in capital_entries if (e.disposal_date, normalize_asset_ticker(e.asset), normalize_platform_name(e.wallet)) == (row.date, row.asset, row.wallet)]`. Call `classify_derivatives_event(row, cg_matches)`. Route the result:
    - `Derivatives(reason)` → append `DerivativesPnLEntry(date=row.date, asset=row.asset, platform=row.wallet, pnl_eur=row.gain_loss, event_type=_event_type_from_row_type(row.row_type), source_ref=f"OGR:{row.date}:{row.asset}", review_required=False, review_reason="")` to `derivatives_entries`.
    - `Ambiguous(reason)` → same but `review_required=True`, `review_reason=reason`.
    - `Spot(reason)` → add `row.gain_loss` to `spot_index[(row.date, row.asset, row.wallet)]`.
  - `_event_type_from_row_type(row_type)`: `"Profit" → DerivativesEventType.PROFIT`; `"Loss"` → `DerivativesEventType.LOSS`. (FEE variant is deferred; see Monitor section.)
- [x] Update `_apply_ogr_direction_override` signature to accept `spot_index` (already split). When `separate_derivatives_reporting=False`, the caller passes the combined index; the function body is unchanged. When `True`, the caller passes only the spot slice; derivatives rows never reach this function.
- [x] Run → expect GREEN
- [x] Run the Task 1 characterization test with `separate_derivatives_reporting=False` to confirm byte-identical backward-compat output.
- [x] Commit: `feat(ogr_handler): split OGR into derivatives and spot at row level; protect spot CG from derivatives override`

### Task 8: Add derivatives aggregation

Files:
- `src/tax_reporting/application/crypto/aggregation.py`
- `tests/unit/application/test_crypto_reporting.py`

- [x] `TestDerivativesAggregation#groups_by_date_asset_platform_type`: given derivatives entries on the same `(date, asset, platform)` with different `event_type` (PROFIT and FEE), expects two aggregated entries (not collapsed into one net)
- [x] `TestDerivativesAggregation#sums_within_group`: given two PROFIT entries on the same group key, expects the aggregated `pnl_eur` to be their sum
- [x] `TestDerivativesAggregation#preserves_review_flags`: given a group where one source entry had `review_required=True`, expects the aggregated entry to carry `review_required=True` with the specific reason joined (deduplicated per existing `TestAggregateOgrValidation` pattern)
- [x] `TestDerivativesAggregation#legal_category_preserved`: given entries with `legal_category="CIRS art. 10(1)(e)"`, expects the aggregated entry to retain the same `legal_category`
- [x] Run → expect RED: `uv run pytest tests/unit/application/test_crypto_reporting.py -k "DerivativesAggregation" -v`
- [x] Implement `aggregate_derivatives_entries(entries: list[DerivativesPnLEntry]) -> list[DerivativesPnLEntry]` mirroring `_aggregate_capital_entries()`. Group key = `(date, asset, platform, event_type)`. Sum `pnl_eur` within group. Preserve `review_required` (True if any source entry has it) and join unique `review_reason` values.
- [x] Run → expect GREEN
- [x] Commit: `feat(aggregation): add aggregate_derivatives_entries grouping by date/asset/platform/type`

### Task 9: Wire pipeline integration in `crypto_reporting.py`

Files:
- `src/tax_reporting/application/crypto_reporting.py`
- `tests/unit/application/test_crypto_reporting.py`

The split happens at line ~203 (after FIFO rebuild at 169-193 and country validation at 197; immediately before the existing OGR override block). See Design Invariant 2.

- [x] `TestPipelineIntegration#split_runs_after_fifo_rebuild`: given a derivatives OGR row whose only CG counterpart was added by FIFO rebuild, expects the classifier to see the FIFO-rebuilt lot and classify the OGR row as Spot (not Derivatives), verifying the split runs post-FIFO
- [x] `TestPipelineIntegration#derivatives_entries_populated_when_flag_on`: given `separate_derivatives_reporting=True` and Case 1 fixture, expects `CryptoTaxReport.derivatives_entries` to contain the <PROFIT_EUR> EUR profit
- [x] `TestPipelineIntegration#derivatives_entries_empty_when_flag_off`: given `separate_derivatives_reporting=False`, expects `CryptoTaxReport.derivatives_entries` to be empty and the existing override path to apply (backward compatibility; Task 1 golden values match)
- [x] `TestPipelineIntegration#capital_entries_excludes_derivatives_when_flag_on`: given Case 1 fixture with flag on, expects `CryptoTaxReport.capital_entries` to contain only the spot fee disposal (<FEE_GAIN_EUR> EUR gain), not the mixed <MIXED_AGGREGATE_EUR> EUR
- [x] Run → expect RED: `uv run pytest tests/unit/application/test_crypto_reporting.py -k "PipelineIntegration and (derivatives or split_runs_after_fifo)" -v`
- [x] In `load_koinly_crypto_report`, replace the existing OGR override block (lines 203-212) with:
  ```python
  if jurisdiction and jurisdiction.use_other_gains_report:
      ogr_rows = _find_and_parse_other_gains_file(koinly_dir)
      if ogr_rows:
          spot_index, derivatives_entries = _split_ogr_index(ogr_rows, capital_entries, jurisdiction)
          capital_entries = _apply_ogr_direction_override(capital_entries, spot_index, jurisdiction)
  ```
  `_split_ogr_index` branches internally on `jurisdiction.separate_derivatives_reporting`: when `False`, it returns `(_build_ogr_index(ogr_rows), [])` (combined index, no derivatives); when `True`, it returns the split slices. The override call is unconditional because `spot_index` already contains the right slice. Then after `_aggregate_capital_entries` and `_filter_immaterial_entries`, aggregate `derivatives_entries` via `aggregate_derivatives_entries()` and assign to the report. Note: `_filter_immaterial_entries` applies to `capital_entries` only; `derivatives_entries` bypasses this filter because art. 10(1)(e) has no materiality carve-out.
- [x] Run → expect GREEN
- [x] Run the Task 1 characterization test with flag off to confirm byte-identical output.
- [x] Run full unit suite to confirm no regression: `uv run pytest -m unit`
- [x] Commit: `feat(crypto_reporting): integrate derivatives split at line 203 post-FIFO post-validation (DP-012)`

### Task 10: Add Derivatives P&L Excel tab

Files:
- `src/tax_reporting/application/persisting/derivatives_sheet.py` *(new)*
- `src/tax_reporting/application/persisting/workbook_builder.py`
- `tests/unit/application/persisting/test_derivatives_sheet.py` *(new)*
- `tests/unit/application/persisting/test_workbook_builder.py`

- [x] `TestDerivativesSheet#renders_header_with_legal_basis`: given a workbook and a `CryptoTaxReport` with derivatives entries, expects the sheet's first rows to contain the header "DERIVATIVES P&L (Financial Derivatives; CIRS art. 10(1)(e))" so readers cannot mistake the category
- [x] `TestDerivativesSheet#renders_one_row_per_aggregated_entry`: given two aggregated entries, expects exactly two data rows with columns: Date, Asset, Platform, Event Type, P&L (EUR), Legal Category, Review
- [x] `TestDerivativesSheet#totals_row`: given entries summing to +<PROFIT_EUR> and <-FEE_PROCEEDS_EUR>, expects a totals row showing net +<MIXED_AGGREGATE_EUR> EUR
- [x] `TestDerivativesSheet#empty_state_when_no_entries`: given an empty `derivatives_entries` list, expects the sheet to render headers and an "No derivatives activity for this jurisdiction" row (not skipped; per development_lessons.md #93)
- [x] `TestDerivativesSheet#review_reason_renders_as_YES_with_reason`: given an entry with `review_required=True` and `review_reason="Ambiguous OGR/CG value mismatch"`, expects the Review cell to render "YES: Ambiguous OGR/CG value mismatch" (not a bare "YES") per PT-C-030
- [x] `TestDerivativesSheet#loss_deductibility_footnote`: given any derivatives loss entry, expects a footnote or methodology row stating "Losses are deductible against other Category G gains; carry-forward 5 years per PT-C-016" (r1 Monitor #1 mitigation)
- [x] `TestDerivativesSheet#tab_registered_when_flag_on`: given `separate_derivatives_reporting=True`, expects `write_derivatives_sheet()` to be called by `workbook_builder`
- [x] `TestDerivativesSheet#tab_skipped_when_flag_off`: given `separate_derivatives_reporting=False`, expects no "Derivatives P&L" worksheet in the workbook
- [x] Run → expect RED: `uv run pytest tests/unit/application/persisting/test_derivatives_sheet.py -v`
- [x] Implement `write_derivatives_sheet(workbook, crypto_tax_report)` in `derivatives_sheet.py` following the patterns in `crypto_gains_sheet.py` (auto-sizing via `auto_column_width`, `safe_cell_value` for string fields, conditional formatting for review rows). Use structural identification for test assertions per development_lessons.md #96. Include the loss-deductibility footnote.
- [x] Register the sheet in `workbook_builder.py` conditional on `separate_derivatives_reporting`. When the flag is off, do not create the worksheet at all.
- [x] Run → expect GREEN
- [x] Commit: `feat(persisting): add Derivatives P&L Excel tab with art. 10(1)(e) header and loss-deductibility footnote`

### Task 11: Data trace verification with real ByBit fixtures

Files:
- `tests/end_to_end/test_crypto_derivatives_separation.py` *(new)*
- `resources/source/koinly2025/koinly_2025_other_gains_report_<ACCOUNT_TOKEN>.csv` (existing fixture, read-only)
- `resources/source/koinly2025/koinly_2025_capital_gains_report_<ACCOUNT_TOKEN>.csv` (existing fixture, read-only)
- `resources/source/koinly2025/koinly_2025_transaction_history_<ACCOUNT_TOKEN>.csv` (existing fixture, read-only)

- [x] `TestByBitCase1Trace#profit_in_derivatives_sheet`: given the real OGR/CG/TH ByBit fixtures, expects the pipeline to produce a Derivatives P&L entry for the <PROFIT_EUR> EUR futures profit (OGR row 8) AND a Crypto Gains entry for the <FEE_GAIN_EUR> EUR fee disposal (not <MIXED_AGGREGATE_EUR> EUR mixed)
- [x] `TestByBitCase1Trace#no_derivatives_value_in_capital_entries`: given Case 1 fixtures, expects no `CryptoCapitalGainEntry` in `capital_entries` with `gain_loss_eur == Decimal("<MIXED_AGGREGATE_EUR>")` (the previously incorrect mixed value)
- [x] `TestByBitCase1Trace#fee_disposal_in_spot_index`: given Case 1 fixtures, expects the <-FEE_PROCEEDS_EUR> EUR OGR Loss row (OGR row 9) to be classified as Spot and summed into the spot_index, not into derivatives_entries
- [x] `TestByBitCase2Trace#lots_remain_positive`: given Case 2 fixtures, expects the ~109 CG lot entries to retain their original positive gain values (not flipped to negative) AND the OGR Loss rows to appear in `derivatives_entries`
- [x] `TestByBitCase2Trace#derivatives_total_matches_ogr_net`: given Case 2 fixtures, expects the sum of `derivatives_entries.pnl_eur` to equal the OGR net (`<-OGR_NET_EUR> EUR` = sum of rows 10, 16, 17), confirming no value was lost in the split
- [x] `TestBackwardCompatTrace#flag_off_matches_golden_values`: given the same fixtures with `separate_derivatives_reporting=False`, expects the Task 1 golden values (Case 1: <MIXED_AGGREGATE_EUR> EUR in Crypto Gains; Case 2: <-OGR_NET_EUR> EUR in Crypto Gains) to reproduce exactly
- [x] Run → expect RED initially (then GREEN after Tasks 4-10): `uv run pytest tests/end_to_end/test_crypto_derivatives_separation.py -v`
- [x] Implement the fixtures-backed e2e test. Use `grep` to verify specific values in source CSVs as part of the test setup (data trace verification per `development_lessons.md` #72, #73). Example: `grep "<PROFIT_USDT>" resources/source/koinly2025/koinly_2025_other_gains_report_<ACCOUNT_TOKEN>.csv` to confirm the <PROFIT_EUR> EUR profit row exists in the source.
- [x] Run → expect GREEN
- [x] Commit: `test(e2e): data trace verification for ByBit derivatives separation Cases 1 and 2`

### Task 12: Update domain documentation

Files:
- `docs/domain/crypto_rules.md`
- `docs/domain/crypto_reporting_guidelines.md`
- `docs/domain/crypto_implementation_guidelines.md`

- [x] Add **PT-C-034** to `crypto_rules.md` under Section 6 (derivatives): "When `separate_derivatives_reporting=True` (DP-012), derivatives P&L is reported separately from spot crypto under CIRS art. 10(1)(e); spot retains art. 10(1)(k) with 365-day exemption. Mixing the two produces incorrect tax treatment. Source: AT binding ruling Processo 28298/2025; CIRS art. 10(1)(e) and (k). OGR/CG counterpart matching uses a 1-cent (`Decimal("0.01")`) EUR tolerance to absorb rounding; this is the single numeric threshold in the classifier and is documented here as the matching precision, not a tax-law parameter."
- [x] Update **PT-C-033** to be explicitly flag-conditional. New text: "PT-C-033 applies ONLY when `separate_derivatives_reporting=False`. When True, PT-C-034 governs: OGR values route to the Derivatives P&L tab instead of overriding spot CG entries, and PT-C-033 is inert for derivatives rows. Spot disposals continue to use the CG report as authoritative regardless of flag." Cross-reference PT-C-034.
- [x] Add a new section to `crypto_reporting_guidelines.md` titled "Derivatives P&L Tab (art. 10(1)(e))" documenting: (a) when the tab renders (flag on), (b) aggregation key `(date, asset, platform, event_type)`, (c) legal category citation in the header, (d) interaction with the Crypto Gains tab (spot only), (e) loss-deductibility footnote.
- [x] Add implementation lessons to `crypto_implementation_guidelines.md`: (a) why amount thresholds are rejected as a detection signal (r1 Blocker 2 / Monitor #2), (b) why the parser must return a row list and not a pre-summed dict (r1 Blocker 7), (c) why spot CG signs must be protected from derivatives OGR override (Design Invariant 6), (d) why the split must run post-FIFO rebuild (Design Invariant 2).
- [x] Commit: `docs(domain): add PT-C-034 and flag-conditional PT-C-033; document derivatives separation pipeline`

### Task 13: Update README and assumptions methodology citation

Files:
- `README.md`
- `src/tax_reporting/application/persisting/assumptions_sheet.py`
- `tests/unit/application/persisting/test_assumptions_sheet.py`

- [x] Add a "Derivatives P&L Section" subsection to `README.md` under "Excel Report Features" documenting: the new tab, its legal basis (CIRS art. 10(1)(e)), what it contains (realized P&L, funding fees, futures fees), and the controlling decision point (DP-012).
- [x] Add one methodology item to `assumptions_sheet.py`'s `methodology_items` list (the local variable at line 167 is typed `list[tuple[str, list[tuple[str, str, str]]]]`, not a tuple) citing art. 10(1)(e) for the Derivatives P&L tab and art. 10(1)(k) for the Crypto Gains tab. This is the one allowed touch to `assumptions_sheet.py` per the out-of-scope note; only the methodology citation, not the 11 branch-review findings.
- [x] Add `test_methodology_includes_derivatives_legal_basis` to `tests/unit/application/persisting/test_assumptions_sheet.py` asserting the new methodology item renders.
- [x] Run → expect RED then GREEN: `uv run pytest tests/unit/application/persisting/test_assumptions_sheet.py::test_methodology_includes_derivatives_legal_basis -v`
- [x] Commit: `docs(readme): document Derivatives P&L tab; add art. 10(1)(e) methodology citation`

### Task 14: Final validation and lint

- [x] Run Tier 1 validation commands (must all pass).
- [x] Run Tier 2 full regression (must all pass).
- [x] Run ruff: `uv run ruff check src tests`.
- [x] Manual Excel check: `uv run tax-reporting --example --output-dir /tmp/derivatives-separation-check` and open the output to verify both tabs render correctly.
- [x] Verify decision-point TOML/MD sync: both files reference DP-012 (grep commands in Validation Commands).
- [x] Verify `sources.md` has an entry for every new file (official and non-official).
- [x] Verify characterization test (Task 1) passes with `separate_derivatives_reporting=False`.
- [x] Commit (if any cleanup needed): `chore: final validation pass for derivatives separation`
