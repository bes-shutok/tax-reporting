# Plan: Derivatives P&L tab: Annex hint, Operator entity/country, Notes, Event count, Operation code

Plan review: the derivatives-pnl-columns plan review (local) (r2, ready, 0 Blockers, 0 Mediums, 2 Lows folded in) · [r1](2026-06-15-plan-review-derivatives-pnl-columns-r1.md) (2 Blockers + 6 Mediums, incorporated)

## Gist & Examples

The Derivatives P&L tab (`src/tax_reporting/application/persisting/derivatives_sheet.py`) currently
renders 7 columns: Date, Asset, Platform, Event Type, P&L (EUR), Legal Category, Review. The user
asked for four additional columns and asked me to research what else is missing for Portuguese tax
filing.

Research against `docs/tax/laws/pt/crypto-tax/official/modelo3_anexo_g_2026.pdf` (Quadro 13 structure,
verified 2026-06-13) plus `docs/tax/laws/pt/crypto-tax/sources.md` (income code G51) produced:

- **Annex hint**: Anexo G, Quadro 13 (income code G51); PT-C-031 now records this routing. Derivatives
  have no 365-day exemption, so the hint is a single constant `G/Q13`, unlike crypto where it branches
  on holding period.
- **Operator entity / country**: Quadro 13 line field "País da contraparte" is mandatory. The pipeline
  already has `resolve_operator_origin()` (returns `OperatorOrigin` with `operator_entity` and
  `operator_country`); we call it for capital_entries and reward_entries today but never for
  derivatives entries. This plan wires it in.
- **Notes**: free-form user-annotation column, empty by default. The pipeline does NOT auto-populate
  notes (classification reason already lives in `review_reason`; auto-populating notes would duplicate
  it). The column exists so reviewers can jot manual annotations during filing review, matching the
  `CryptoCapitalGainEntry.notes` semantics where the field is empty unless a caller sets it.
- **Event count / lots**: number of underlying OGR rows aggregated into one Derivatives P&L row by
  `aggregate_derivatives_entries()`. Default 1; summed during aggregation.
- **Operation code (Código da operação)**: REQUIRED by Quadro 13 line 1301-1306. Default value
  **G51** ("Operações relativas a instrumentos financeiros derivados") from
  `docs/tax/laws/pt/crypto-tax/sources.md` line 153. Pending sub-agent research on whether AT
  distinguishes futures vs options vs perpetuals with sub-codes; if research finds a single universal
  code, this field becomes a constant. If sub-codes exist, we will flag it and ask the user before
  hardcoding a mapping.

### Example before / after

Before (single aggregated row, today's output):

| Date       | Asset | Platform | Event Type | P&L (EUR) | Legal Category      | Review |
|------------|-------|----------|------------|-----------|----------------------|--------|
| 2025-01-19 | USDT  | ByBit    | loss       | -271.79   | CIRS art. 10(1)(e)   | NO     |

After (same row, 13 columns):

| Date       | Asset | Platform | Event Type | P&L (EUR) | Annex hint | Operator entity | Operator country | Operation code | Event count | Legal Category      | Notes | Review |
|------------|-------|----------|------------|-----------|------------|-----------------|------------------|----------------|-------------|----------------------|-------|--------|
| 2025-01-19 | USDT  | ByBit    | loss       | -271.79   | G/Q13      | ByBit           | AE               | G51            | 1           | CIRS art. 10(1)(e)   |       | NO     |

(Operator country "AE" is the resolved ByBit counterparty country from `operator_origin.py`.)

## Evaluation Criteria

**Quality dimensions:**
- Correctness: every Quadro 13 mandatory field (Rendimento líquido, País da contraparte) is
  populated for every derivatives row; missing operator mapping surfaces as review flag, never silent.
- Coverage: rows with no operator mapping still render without crash; review_reason cites
  "add this platform to resolve_operator_origin()".
- Aggregation correctness: event_count reflects the number of underlying OGR rows in the group;
  aggregation preserves operator origin from the first row of the group (same wallet → same operator).
- Rendering: 13 columns total (was 7); review fill spans all 13 columns; total row still sits under
  the P&L column (now column 5, unchanged); loss footnote still appears.

**Release gates:**
- All unit tests pass: `uv run pytest -m unit`.
- E2E test for derivatives tab passes: `uv run pytest tests/end_to_end -k derivatives`.
- New Excel structural test verifies 13-column header layout (no hardcoded value exclusions per
  development_lessons.md #96).

## Review Scope

**Explicit must-fix:**

**Production code:**
- `src/tax_reporting/application/crypto/entities.py`: extend `DerivativesPnLEntry`
- `src/tax_reporting/application/crypto/ogr_handler.py`: populate new fields at construction
- `src/tax_reporting/application/crypto/aggregation.py`: aggregate `event_count`; preserve operator origin
- `src/tax_reporting/application/persisting/derivatives_sheet.py`: render 13 columns

**Tests:**
- `tests/unit/application/test_crypto_entities.py`: `DerivativesPnLEntry` dataclass tests
- `tests/unit/application/test_crypto_reporting.py`: covers `_split_ogr_index` and `aggregate_derivatives_entries`
- `tests/unit/application/persisting/test_derivatives_sheet.py`: sheet rendering
- `tests/end_to_end/test_crypto_derivatives_separation.py`: E2E

**Plan-related extension:** Implementation may touch `docs/domain/crypto_rules.md` (already updated
for PT-C-031 annex routing in the same session).

**Out of scope:**
- Crypto capital gains `annex_hint` branching in `fifo_helpers.py:310` is a separate code path
  (crypto CG, not derivatives) and is not modified by this plan.
- Migration of `derivatives_sheet.py` to follow the multi-section pattern of `crypto_gains_sheet.py`.
- Foreign-source derivatives routing to Anexo J (deferred; current Portuguese-data assumption holds).

## Design Invariants (CR Guard)

Predecessor plans: `docs/plans/completed/2026-06-13-derivatives-separation.md` and
`docs/plans/completed/2026-06-14-derivatives-th-label-cg-dedup.md`. Their Design Invariants remain
in force; this plan adds the following:

1. **Backward compatibility (flag-off path):** when `separate_derivatives_reporting=False`,
   `_split_ogr_index` returns `(_build_ogr_index(ogr_rows), [])` byte-identically to the pre-Task-7
   pipeline (ogr_handler.py:208-209). No `DerivativesPnLEntry` is constructed; the new fields do not
   affect this path. Test: `test_separate_derivatives_disabled_produces_no_derivatives_entries_and_no_operator_resolution`.
2. **OGR row `Type` remains the authoritative derivatives signal.** `resolve_operator_origin` does
   NOT reclassify rows; it only decorates entries that the classifier already routed to derivatives.
3. **Review reasons must be specific and actionable per PT-C-030.** The platform-missing reason
   carried forward from `OperatorOrigin.review_required` must cite the missing platform mapping
   explicitly. Template: `ogr_handler.py:67-71` ("entry flagged for review: add platform mapping to
   resolve_operator_origin()"). Concatenation order:
   `"; ".join(filter(None, [operator_origin_reason, classification_reason]))`; platform-level first
   so the reviewer sees the blocking action first.
4. **Aggregation key `(date, asset, platform, event_type)` guarantees all rows in a group share the
   same platform and therefore the same operator origin.** Carrying forward operator_entity,
   operator_country, annex_hint, operation_code from the first group member is correct
   (aggregation.py:340-343).
5. **Operation code `G51` is a closed-enum constant** from AT Quadro 13 instructions
   (`modelo3_anexo_g_2026.pdf`). It must not be parameterized without a `crypto_rules.md` update and
   an AT-source freshness check against `docs/tax/laws/pt/crypto-tax/sources.md`.
6. **Unmapped-platform cell rendering:** operator_entity column shows the raw wallet name from OGR
   (NOT the internal sentinel `"UNKNOWN_OPERATOR_REVIEW_REQUIRED"`); operator_country column shows
   `"UNKNOWN"`; row-level `review_required=True` with platform-missing reason. This matches the
   capital-entries pattern where row-level review surfaces missing mappings.

## Validation Commands

```bash
uv run pytest tests/unit/application/test_crypto_entities.py -k DerivativesPnLEntry -v
uv run pytest tests/unit/application/test_crypto_reporting.py -v
uv run pytest tests/unit/application/persisting/test_derivatives_sheet.py -v
uv run pytest tests/end_to_end/test_crypto_derivatives_separation.py -v
uv run ruff check src/tax_reporting/application/crypto/entities.py src/tax_reporting/application/crypto/ogr_handler.py src/tax_reporting/application/crypto/aggregation.py src/tax_reporting/application/persisting/derivatives_sheet.py
uv run pytest -m unit
```

## Task 1: Extend DerivativesPnLEntry with new fields (RED)

Files:
- `src/tax_reporting/application/crypto/entities.py`
- `tests/unit/application/test_crypto_entities.py`

- [x] `TestDerivativesPnLEntry#test_default_annex_hint_is_g_q13`: given a DerivativesPnLEntry constructed without annex_hint, expects `annex_hint == "G/Q13"`
- [x] `TestDerivativesPnLEntry#test_default_operation_code_is_g51`: given a DerivativesPnLEntry constructed without operation_code, expects `operation_code == "G51"`
- [x] `TestDerivativesPnLEntry#test_default_event_count_is_one`: given a DerivativesPnLEntry constructed without event_count, expects `event_count == 1`
- [x] `TestDerivativesPnLEntry#test_operator_fields_default_to_empty`: given a DerivativesPnLEntry constructed without operator_entity/operator_country, expects both to equal `""`
- [x] Run → expect RED (`uv run pytest tests/unit/application/test_crypto_entities.py -k DerivativesPnLEntry`)

Add the fields to the dataclass:

```python
@dataclass(frozen=True)
class DerivativesPnLEntry:
    date: str
    asset: str
    platform: str
    pnl_eur: Decimal
    event_type: DerivativesEventType
    source_ref: str
    legal_category: str = "CIRS art. 10(1)(e)"
    review_required: bool = False
    review_reason: str = ""
    # IRS Anexo G Quadro 13 routing; constant for derivatives (no 365-day exemption).
    annex_hint: str = "G/Q13"
    # Operation code from Tabela de Códigos; G51 covers "instrumentos financeiros derivados".
    operation_code: str = "G51"
    # Operator entity/country from resolve_operator_origin(); empty until OGR handler populates.
    operator_entity: str = ""
    operator_country: str = ""
    # Number of underlying OGR rows aggregated into this entry; 1 for non-aggregated.
    event_count: int = 1
    # Free-form notes (classification reason for ambiguous rows; blank otherwise).
    notes: str = ""
```

- [x] Run → expect GREEN
- [x] Commit: `feat(derivatives): add annex_hint, operator, notes, event_count, operation_code fields to DerivativesPnLEntry`

## Task 2: Populate operator origin in OGR handler (RED)

Files:
- `src/tax_reporting/application/crypto/ogr_handler.py`
- `tests/unit/application/test_crypto_reporting.py`

- [x] `TestOgrSplit#test_derivatives_entry_carries_operator_entity_and_country`: given an OGR row for "ByBit" routed to derivatives, expects the produced DerivativesPnLEntry to have `operator_entity="ByBit"` and `operator_country="AE"` resolved from `resolve_operator_origin("ByBit")`
- [x] `TestOgrSplit#test_derivatives_entry_for_unknown_platform_renders_wallet_name_and_unknown_country`: given an OGR row for an unmapped platform "UnknownExchange", expects `operator_entity="UnknownExchange"` (raw wallet name, NOT the internal sentinel), `operator_country="UNKNOWN"`, `review_required=True`, and review_reason starting with the platform-missing reason (e.g., "add platform mapping to resolve_operator_origin()")
- [x] `TestOgrSplit#test_review_reason_concatenation_order_is_platform_first`: given an OGR row that is BOTH classification-ambiguous AND from an unmapped platform, expects review_reason to start with the platform-missing reason followed by "; " and then the classification reason (matches capital-entries convention at ogr_handler.py:76)
- [x] `TestOgrSplit#test_spot_path_unaffected_by_operator_resolution`: given an OGR row classified as Spot, expects the spot_index to remain unchanged (no DerivativesPnLEntry built, no call to resolve_operator_origin)
- [x] `TestOgrSplit#test_separate_derivatives_disabled_produces_no_derivatives_entries_and_no_operator_resolution`: given an OGR row and `separate_derivatives_reporting=False`, expects `derivatives_entries == []` and `resolve_operator_origin` to NOT be called (monkeypatch it to raise if invoked); verifies the flag-off path is byte-identical to pre-Task-7 behavior per development_lessons.md #84
- [x] Run → expect RED

In `_split_ogr_index` (ogr_handler.py:159), call `resolve_operator_origin(row.wallet, transaction_date=row.date)` before constructing each DerivativesPnLEntry. Set:
- `operator_entity=row.wallet` (raw wallet name; `operator_origin.operator_entity` may be an internal sentinel like `"UNKNOWN_OPERATOR_REVIEW_REQUIRED"` for unmapped platforms, which would leak into Excel; use the raw wallet name as the user-facing value)
- `operator_country=operator_origin.operator_country` (the resolved country code, or `"UNKNOWN"` for unmapped platforms)
- `review_required = classification_kind_is_ambiguous OR operator_origin.review_required`
- `review_reason = "; ".join(filter(None, [operator_origin_reason, classification_reason]))`; platform-level first (matches ogr_handler.py:76 convention for capital entries)

The `notes` field is intentionally NOT set here. It is a free-form user-annotation column, empty by default.

- [x] Run → expect GREEN
- [x] Commit: `feat(derivatives): resolve operator origin when building DerivativesPnLEntry rows`

## Task 3: Aggregate event_count and preserve operator origin (RED)

Files:
- `src/tax_reporting/application/crypto/aggregation.py`
- `tests/unit/application/test_crypto_reporting.py`

- [x] `TestDerivativesAggregation#test_aggregate_derivatives_sums_event_count`: given three raw derivatives entries with the same (date, asset, platform, event_type) key, expects one aggregated entry with `event_count=3`
- [x] `TestDerivativesAggregation#test_aggregate_derivatives_preserves_operator_from_first_row`: given two raw entries in the same group with the same platform, expects the aggregated entry to carry the operator entity/country from the first group member
- [x] `TestDerivativesAggregation#test_aggregate_derivatives_event_count_defaults_to_one_for_singletons`: given one raw entry, expects the aggregated entry to have `event_count=1`
- [x] Run → expect RED

Update `aggregate_derivatives_entries` (aggregation.py:321) to:
1. Set `event_count=len(group)` in the aggregated `replace()` call.
2. Carry forward `operator_entity`, `operator_country`, `annex_hint`, `operation_code`, `notes` from the first group member. All rows in a group share the same platform (it is part of the aggregation key), so they share the same operator origin; `notes` is empty by default and stays empty.

- [x] Run → expect GREEN
- [x] Commit: `feat(derivatives): aggregate event_count and preserve operator origin across grouped rows`

## Task 4: Render 13 columns in Derivatives P&L sheet (RED)

Files:
- `src/tax_reporting/application/persisting/derivatives_sheet.py`
- `tests/unit/application/persisting/test_derivatives_sheet.py`

- [x] `TestDerivativesSheet#test_header_has_thirteen_columns`: given a CryptoTaxReport with one derivatives entry, expects row 3 to contain 13 header cells ending with Review at column 13
- [x] `TestDerivativesSheet#test_header_columns_include_annex_hint_operator_operation_code_event_count_notes`: given a rendered sheet, expects the header row to contain all of: "Annex hint", "Operator entity", "Operator country", "Operation code", "Event count", "Notes"
- [x] `TestDerivativesSheet#test_row_writes_annex_hint_in_column_6`: given a derivatives entry with default annex_hint, expects cell(row, 6) == "G/Q13"
- [x] `TestDerivativesSheet#test_row_writes_operator_entity_and_country_in_columns_7_and_8`: given an entry with operator_entity="ByBit" and operator_country="AE", expects cell(row, 7) == "ByBit" and cell(row, 8) == "AE"
- [x] `TestDerivativesSheet#test_row_writes_operation_code_in_column_9`: given an entry with default operation_code, expects cell(row, 9) == "G51"
- [x] `TestDerivativesSheet#test_row_writes_event_count_in_column_10`: given an entry with event_count=3, expects cell(row, 10) == 3
- [x] `TestDerivativesSheet#test_row_writes_legal_category_in_column_11`: given an entry, expects cell(row, 11) == "CIRS art. 10(1)(e)"
- [x] `TestDerivativesSheet#test_row_writes_notes_in_column_12_when_set`: given an entry with notes="manual annotation", expects cell(row, 12) == "manual annotation"
- [x] `TestDerivativesSheet#test_row_writes_notes_in_column_12_default_empty`: given an entry constructed without notes, expects cell(row, 12) to be empty ("" or None per `safe_cell_value("")`)
- [x] `TestDerivativesSheet#test_row_writes_review_in_column_13`: given a review-required entry with reason "missing platform mapping", expects cell(row, 13) == "YES: missing platform mapping"
- [x] `TestDerivativesSheet#test_review_fill_spans_all_thirteen_columns`: given a review-required entry, expects every cell in columns 1 through 13 to have the review PatternFill applied
- [x] `TestDerivativesSheet#test_total_row_pnl_in_column_5`: given two entries with net P&L, expects the Total row to have its numeric value in column 5 (unchanged from before)
- [x] `TestDerivativesSheet#test_loss_footnote_still_rendered_when_loss_present`: given an entry with negative P&L, expects the loss footnote row to appear after the total row
- [x] Run → expect RED

Update `derivatives_sheet.py`:

```python
_COLUMN_HEADERS = [
    "Date", "Asset", "Platform", "Event Type", "P&L (EUR)",
    "Annex hint", "Operator entity", "Operator country",
    "Operation code", "Event count", "Legal Category", "Notes", "Review",
]
# _NUM_COLUMNS = len(_COLUMN_HEADERS)  # 13
```

In the row loop (currently lines 63-80 of derivatives_sheet.py), after column 5 (P&L), write:
- col 6: `entry.annex_hint`
- col 7: `safe_cell_value(entry.operator_entity)`
- col 8: `safe_cell_value(entry.operator_country)`
- col 9: `entry.operation_code`
- col 10: `entry.event_count`
- col 11: `safe_cell_value(entry.legal_category)`
- col 12: `safe_cell_value(entry.notes)`
- col 13: review display (current col 7 logic)

Total row label stays at column 1; total P&L value stays at column 5. Review fill scope becomes `range(1, _NUM_COLUMNS + 1)`; already driven by `_NUM_COLUMNS`, so the change is automatic.

- [x] Run → expect GREEN
- [x] Commit: `feat(derivatives): render Annex hint, Operator, Operation code, Event count, Notes columns in P&L sheet`

## Task 5: Update E2E characterization test (RED)

Files:
- `tests/end_to_end/test_crypto_derivatives_separation.py`

- [x] `TestDerivativesE2E#test_derivatives_sheet_has_thirteen_columns`: given the example data run, expects the Derivatives P&L sheet to have 13 header cells in row 3
- [x] `TestDerivativesE2E#test_derivatives_rows_operator_country_is_valid_or_unknown`: given the example data run, expects every derivatives row to have operator_country that is either a valid Tabela X country code OR the literal string "UNKNOWN"; AND when operator_country == "UNKNOWN" the Review cell at column 13 starts with "YES:" (structural assertion, survives fixture platform changes)
- [x] Run → expect RED then GREEN after the implementation lands

If existing E2E tests assert 7-column structure (e.g., `_NUM_COLUMNS == 7`), update them to the new
13-column structure.

- [x] Run → expect GREEN
- [x] Commit: `test(e2e): update derivatives tab characterization for 13-column layout`

## Task 6: Regression sweep

- [x] `uv run pytest tests/unit/application/test_crypto_reporting.py::TestOgrCharacterizationGolden tests/unit/application/test_derivatives_dedup.py tests/end_to_end/test_crypto_derivatives_separation.py -v`: predecessor plan golden tests stay green
- [x] `uv run pytest -m unit`: all unit tests pass
- [x] `uv run pytest tests/end_to_end -k derivatives`: derivatives E2E passes
- [x] `uv run pytest`: full suite passes; no formatting-only files in `git status`
- [x] Inspect `git diff --stat`: confirm only the 4 production files + 3 test files + crypto_rules.md are modified

## Notes / Resolved research

- **Operation code (Código da operação):** Research against
  `docs/tax/laws/pt/crypto-tax/official/modelo3_anexo_g_2026.pdf` Quadro 13 instructions confirms AT
  publishes a closed 4-value enum: **G51** (derivativos), G52 (warrants autónomos), G53 (certificados),
  G54 (outros instrumentos complexos). Selection is by instrument category, not derivative subtype or
  asset class. Crypto perpetual swaps, futures, and options all fall under G51. The tool only handles
  G51 today; G52/G53/G54 are out of scope. Hardcoding `"G51"` as the default is correct and matches
  the closed-enum nature of the field. AT validators reject blank Código da operação on populated
  Quadro 13 lines, so we never emit blank.
- **Annex hint format:** `G/Q13` matches the shorthand style of crypto's `G1`/`J` and is what the
  column will display. The PT-C-031 rule text uses the long form ("Anexo G, Quadro 13") for clarity.

## Monitor

1. **ByBit account-region entity risk** (premortem r1): ByBit is mapped with
   `platform_review_required=True` (Platform Assumptions tab flags it). The plan's row-level
   `review_required` only OR-s from `operator_origin.review_required`, which is False for ByBit.
   If the user files ByBit derivatives without verifying their account region (Bybit Fintech Limited
   BVI vs the AE entity), AT may reject. **Owner:** future plan to consider elevating
   `platform_review_required` to row-level `review_required=True` for derivatives rows on platforms
   where `platform_review_required=True`.
2. **Event-count semantics ambiguity** (premortem r1): "Event count" reflects OGR-row aggregation,
   not underlying trade count. A single derivatives disposal FIFO-split into 108 CG lots
   (predecessor plan Case 2) still shows `event_count=1` because OGR collapses it to one row.
   **Owner:** monitor user support questions; if confusion arises, rename column to "OGR rows
   aggregated" or add a footnote in the sheet.
