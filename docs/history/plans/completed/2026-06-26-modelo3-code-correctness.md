# Plan: Modelo 3 Code Correctness (Derivatives Routing + Crypto Income Codes)

Plan review: `docs/history/reviews/2026-06-26-plan-review-modelo3-code-correctness-r1.md` (r1, 2 Blockers + 7 Medium -> revised) · `docs/history/reviews/2026-06-26-plan-review-modelo3-code-correctness-r2.md` (r2, 1 Blocker em-dash + 1 Medium A5-layer -> revised) · `docs/history/reviews/2026-06-26-plan-review-modelo3-code-correctness-r3.md` (r3, 0 Blocker + 7 Medium wiring/test-surface -> revised) · `docs/history/reviews/2026-06-26-plan-review-modelo3-code-correctness-r5.md` (r5, 0 Blocker + 1 Medium e2e-caller-undercount -> revised) · `docs/history/reviews/2026-06-26-plan-review-modelo3-code-correctness-r6.md` (r6, 0 Blocker + 0 Medium, ready) · `docs/history/reviews/2026-06-26-plan-review-modelo3-code-correctness-r7.md` (r7, 0 Blocker + 0 Medium, ready - carrier-type refinement)

Two independent official-code correctness gaps in the crypto pipeline, both surfaced by the
FY2025 filing and documented in `docs/maintenance/crypto_rules.md` as known tool gaps.
Post-filing correctness only: the FY2025 workbook was filed as-is; this plan does not
regenerate filed output.

## Terms

- **Tabela V**: the Modelo 3 income-code table for Categoria E (rendimentos de capitais),
  e.g. `E25` = "juros ... criptoativos (al. u) do n. 2 do art. 5 CIRS". Mirrored at
  `docs/maintenance/tax/laws/pt/crypto-tax/official/modelo3_anexo_j_2025.pdf`.
- **Country codes are alpha-2** throughout this pipeline (NOT numeric Tabela X). Verified:
  `OperatorOrigin.operator_country` is populated with alpha-2 values (`"GB"`, `"AE"`,
  `"IE"`, `"HR"`, `"CH"` ...; `"UNKNOWN"` for unmapped) in `operator_origin.py`; the
  validator `_is_valid_tabela_x_country` checks membership in `_TABELA_X_COUNTRY_CODES`
  using alpha-2 codes. **Portugal = `"PT"`** (confirmed present in `_TABELA_X_COUNTRY_CODES`,
  `classification.py:83`).
- **annex_hint / operation_code**: per-row Modelo 3 routing strings for derivatives
  (`Anexo G, Quadro 13` / `G51` for resident counterparties; `Anexo J, Quadro 9.2.B` /
  `G30` for non-resident). A PT-IRS construct.
- **Counterparty residency**: the tax residency of the operator/exchange entity (not the
  taxpayer). Resident = `operator_country == "PT"`.
- **Reporting country**: `TaxJurisdictionConfig.country` (e.g. `"PT"`). The jurisdiction
  being filed. PT-specific rules in this plan fire only when this is `"PT"`.

## Design Invariants (PT-Country Dispatch)

The project is built to support multiple reporting countries; PT is the current main use
case, not a baked-in assumption. The following invariants hold:

1. **No PT rule fires unconditionally.** Every PT-IRS-specific output in this plan is gated
   on `TaxJurisdictionConfig.country == "PT"`. The gate is implemented at the resolution
   layer (income-code resolver, derivatives route helper), not by branching render code.
2. **Non-PT leaves PT fields blank, never synthetic.** When `country != "PT"`: official
   income codes resolve to `""`; derivatives `annex_hint`/`operation_code` resolve to `""`;
   the PT-only "Income Codes Reference" sheet section is omitted. No `40x`, no `G51`, no
   hardcoded `"PT"` label reaches a non-PT return.
3. **Entity field defaults are the neutral/blank route** (`annex_hint=""`,
   `operation_code=""`). Direct constructors that pass no jurisdiction produce no PT hint
   (fail safe). The OGR handler overrides per residency only under a PT jurisdiction.
4. **Country reaches the resolution layer, not just the sheets.** For Feature A
   (derivatives), `jurisdiction` is already in scope at the construction site
   (`ogr_handler._split_ogr_index` receives `jurisdiction`) - zero-hop. For Feature B
   (income codes), the REPORTING country is **not** in scope today and is established by
   Task B2 as a two-hop threading: `aggregate_taxable_rewards(reward_entries, country)`
   gains a `country` param (today it takes only `reward_entries`, `aggregation.py:46`);
   its sole production caller `workbook_builder.py:148` passes `config.tax_jurisdiction.country`
   (in scope at `:161`); `_resolve_income_code(entry.source_type, country)` consumes it at
   `aggregation.py:104`. The threaded value is the REPORTING country
   (`config.tax_jurisdiction.country`), NEVER `entry.operator_origin.operator_country`
   (the source/counterparty country) - threading the latter silently blanks every
   foreign-counterparty reward on a PT return. Render sheets read the already-resolved
   entry fields, except `write_crypto_supplementary_sheet`, which receives `jurisdiction`
   (threaded via `workbook_builder.py:163` `config.tax_jurisdiction`, in scope at `:161`)
   to decide whether to render the PT reference section; and `write_derivatives_sheet`, which
   receives `jurisdiction` for the re-scoped blank-annex guard (Task A4). Both sheet params are
   REQUIRED (no default): a forgotten production threading is a TypeError at call time, not a
   silent PT fallback. All existing test callers (supplementary ~32, derivatives ~24 unit
   + 2 e2e) pass a `jurisdiction` fixture (`build_koinly_jurisdiction()` for the PT cases) per P0.
   **Carrier type is the frozen `TaxJurisdictionConfig` value object** (not a bare `country: str`,
   not the whole `Config`): its `country: str` field is required with no default
   (`domain/jurisdiction.py:99`) and is validated fail-fast at config load
   (`infrastructure/config.py:234-241` - empty/non-alpha-2 raises `ValueError`), so the parameter
   TYPE itself guarantees the country is set - there is no `None`/sentinel default to forget. This
   is explicit dependency injection of a typed value object, not a `contextvars` context or a
   module-level cache: the pipeline is a single-threaded synchronous CLI, the value threads one hop
   to two sheet functions called from one site, and the codebase already passes `Config`/
   `TaxJurisdictionConfig` explicitly end to end (see python_guidelines.md #13).
5. **Consolidated income-code mapping lives in the crypto package; persisting derives from
   it.** `application/crypto/` already depends on nothing in `application/persisting/`, while
   `persisting/` already imports from `crypto/` (e.g. `workbook_builder.py:23`). The single
   owner of the type -> (official_code, description) mapping is therefore a crypto-package
   module (`classification.py` or a co-located helper); `persisting/tax_constants.py`
   derives/re-exports the description half from it. `crypto/` MUST NOT import from `persisting/`
   (no layer-inversion back-edge). (Alternative considered: drop the consolidation entirely
   and guard drift with a key-set-consistency test - see r3 Medium 3 / Accepted Risk. Not
   chosen: the consolidation was an accepted r1 Medium 5 fix and reversing it is the larger
   change.)

## Gist & Examples

### Feature A - Derivatives counterparty-residency routing (PT-gated)

**Problem.** `DerivativesPnLEntry` hardcodes `annex_hint="G/Q13"` and
`operation_code="G51"` (the resident-counterparty route) for every row
(`application/crypto/entities.py:162-164`), with comments claiming derivatives routing
"never branches". The correct rule (AT binding ruling Processo 28298/2025; documented in
`crypto_rules.md` PT-C-031) is counterparty-residency-dependent and is a PT/Modelo 3 rule:

- Resident counterparty (operator entity in Portugal) -> **Anexo G, Quadro 13**, code **G51**.
- Non-resident counterparty (income obtained abroad; foreign exchanges) -> **Anexo J,
  Quadro 9.2.B**, code **G30**.

The data needed to branch already lives on the entry (`operator_country`, alpha-2,
populated from `operator_origin.operator_country` at construction in `ogr_handler.py:280`).
`jurisdiction` is in scope at that construction site (`_split_ogr_index` receives it). The
FY2025 return is 100% non-resident counterparties, so the emitted `G/Q13 + G51` is wrong for
every row. The Derivatives P&L sheet renders a single detail line from `entries[0]`
(`persisting/derivatives_sheet.py` `_DETAIL_LINE_TEMPLATE`), which cannot represent a return
that mixes resident and non-resident counterparties.

**Change.** Add a pure helper `_derivatives_route(country, operator_country)` returning
`(annex_hint, operation_code)`:
- `country != "PT"` -> `("", "")` (Invariant 2: no Modelo 3 hint for non-PT).
- `operator_country == "PT"` -> `("G/Q13", "G51")`.
- otherwise (including `"UNKNOWN"`) -> `("J/Q9.2.B", "G30")` (fail-safe non-resident).

Call it at the `DerivativesPnLEntry` construction site, passing `jurisdiction.country` and
`operator_origin.operator_country`. Flip the entity field defaults to `("", "")` (Invariant
3). Add per-row **Annex** and **Código** columns to the sheet (rendering the possibly-blank
fields) and **drop** the single `entries[0]` detail line.

**Example.** Under PT jurisdiction, a Kraken (`"IE"`) row renders
`Annex: J/Q9.2.B | Código: G30`; a hypothetical PT-resident broker row renders
`Annex: G/Q13 | Código: G51`. Under a non-PT jurisdiction, both Annex/Código cells are blank.

### Feature B - Crypto income codes: internal 401-405 -> official Modelo 3 codes (PT-gated)

**Problem.** `classification.py:_KOINLY_TYPE_TO_INCOME_CODE` maps Koinly income types to
synthetic internal codes `401`-`405` (staking/reward/airdrop->401, interest->402,
mining->403, fork->404, dividend->405), labelled "Tabela V". `_resolve_income_code`
(`classification.py:445`) reads that dict and **defaults to `"401"`** for unknown types
(verified). `persisting/tax_constants.py:_INCOME_CODE_DESCRIPTIONS` repeats the codes with
descriptions. These are not official Modelo 3 codes and they leak to user-facing output:
`crypto_supplementary_sheet.py:176-179` writes the raw code into an "Income Codes Reference"
table (with a hardcoded `"PT"` country column at line 177); `ib_sheet.py:374` renders the
description via `get_income_code_description`.

Only one official mapping is verified so far: crypto interest = **E25** (Categoria E). The
others span categorias (e.g. mining is Categoria B, not a Categoria E code), so the fix is a
per-classification official-code resolution. B0 pins the mapping before B1/B2.

**Change.** Make the resolver country-aware: `_resolve_income_code(source_type, country)`.
Under `country == "PT"`: resolve each type to its official code (interest -> E25; others per
B0); unknown types resolve to `""` (no synthetic `401`). Under non-PT: resolve to `""`
(Invariant 2). Thread the REPORTING `country` into the call site at `aggregation.py:104` as a
two-hop change (Invariant 4): add `country` to `aggregate_taxable_rewards` and pass
`config.tax_jurisdiction.country` from `workbook_builder.py:148` (NOT
`operator_origin.operator_country`). Consolidate the duplicated type->code and
code->description structures into one owner in the crypto package (Invariant 5).
Render the official
codes at both user-facing sites; for non-PT, `get_income_code_description` returns `""` for a
blank code (no "Income code " fallback string) and the "Income Codes Reference" section is
omitted. The hardcoded `"PT"` country column derives from `jurisdiction.country`.

**Example.** Under PT, a Wirex crypto-interest reward renders code `E25` / the official E25
description. Under a non-PT jurisdiction, that row carries no income code and the reference
table section is absent.

## Evaluation Criteria

**Quality dimensions:**
- **Correctness (derivatives, PT):** every `DerivativesPnLEntry`'s `annex_hint` and
  `operation_code` match its `operator_country` residency (`"PT"` -> G/Q13 + G51; any other
  value incl. `"UNKNOWN"` -> J/Q9.2.B + G30), asserted at the construction layer and via a
  unit test exercising the resident branch.
- **Correctness (derivatives, non-PT):** when `country != "PT"`, `annex_hint` and
  `operation_code` are `""` regardless of operator residency; no `G51`/`G30` reaches a non-PT
  return.
- **Correctness (mixed residency):** under PT, the Derivatives P&L sheet renders each row's
  own route; a fixture with one resident + one non-resident row shows both routes (no
  `entries[0]` collapse, no single detail line).
- **Correctness (income codes, PT):** every Koinly income type with a known official code
  resolves to that code (interest -> E25); unknown types resolve to `""`, never `401`; no
  synthetic `40x` code reaches any user-facing cell.
- **Correctness (income codes, non-PT):** when `country != "PT"`, `income_code` resolves to
  `""`; the "Income Codes Reference" sheet section is omitted; no `40x`/`E25`/hardcoded `"PT"`
  reaches a non-PT return.
- **Country dispatch, not render branching:** the gate lives in `_derivatives_route` and
  `_resolve_income_code` (both take `country`); render sheets read the resolved entry fields.
  `write_crypto_supplementary_sheet` is the only sheet that receives `jurisdiction` (to omit
  the PT reference section under non-PT).
- **Intentional layout change, not regression:** the Derivatives P&L sheet grows from 10 to 12
  columns (added Annex + Código). Existing layout tests pinning the 10-column shape and the
  removed detail-line test are intentionally re-scoped/removed (see Task P0). Derivatives P&L
  totals, aggregation keys, and the loss-deductibility footnote are unchanged.
- **Maintainability:** residency routing and official-code mapping live in named, unit-tested
  helpers; the income-code mapping has a single owner in the crypto package (Invariant 5);
  no country literal without reusing `_TABELA_X_COUNTRY_CODES` or the jurisdiction config.

**Release gates:**
- `uv run pytest` full suite GREEN (with the re-scoped tests updated, not deleted silently).
- `uv run ruff check` clean on all touched files.
- No em dash in any changed file (`check-no-em-dash.sh`); no em dash in the plan itself.
- `crypto_rules.md` PT-C-031 updated; `tax_reporting_guidelines.md` updated with the new sheet
  columns (SRG ID) and the PT-country dispatch note; `decision_points/2025.md` changelog entry.

## Review Scope

**Explicit must-fix**; findings on these paths are always in scope (review and fix if valid):

**Production code:**
- `src/tax_reporting/application/crypto/entities.py` (DerivativesPnLEntry defaults/docstrings + stale `401` docstring ~line 418)
- `src/tax_reporting/application/crypto/ogr_handler.py` (residency routing at construction; country from `jurisdiction`)
- `src/tax_reporting/application/crypto/classification.py` (`_KOINLY_TYPE_TO_INCOME_CODE`, `_resolve_income_code` signature/default/docstring)
- `src/tax_reporting/application/crypto/aggregation.py` (thread `country` into the `_resolve_income_code` call at line 104)
- `src/tax_reporting/application/crypto/operator_origin.py` (read-only: confirm alpha-2 `"PT"` handling)
- `src/tax_reporting/application/persisting/derivatives_sheet.py` (per-row Annex/Código columns; drop detail line)
- `src/tax_reporting/application/persisting/tax_constants.py` (descriptions + docstring; consolidate mapping ownership; blank-code handling in `get_income_code_description`)
- `src/tax_reporting/application/persisting/ib_sheet.py` (render official descriptions; blank-safe for non-PT)
- `src/tax_reporting/application/persisting/crypto_supplementary_sheet.py` (country-driven reference section; jurisdiction param; remove hardcoded `"PT"`)
- `src/tax_reporting/application/persisting/workbook_builder.py` (thread `tax_jurisdiction` into `write_crypto_supplementary_sheet`)

**Tests:**
- `tests/unit/application/test_crypto_reporting.py` *(existing - new cases; ALSO 9 `aggregate_taxable_rewards(entries)` callers at lines 2027/2118/2167/2177/2205/2235/2286/2340/2435 take the new `country` arg - see P0)*
- `tests/unit/application/test_crypto_entities.py` *(existing - re-scope `test_default_annex_hint_is_g_q13` (:512) and `test_default_operation_code_is_g51` (:524), which pin the resident defaults A2 flips - see P0)*
- `tests/unit/application/persisting/test_derivatives_sheet.py` *(existing - re-scope 10-column + detail-line assertions)*
- `tests/unit/application/persisting/test_ib_sheet.py` *(existing - update income-code description assertions ~line 935-941 + non-PT blank case)*
- `tests/unit/application/persisting/test_crypto_supplementary_sheet.py` *(existing - update `{401..405}` set + sort at line 201/225; non-PT omits section; ALSO ~32 `write_crypto_supplementary_sheet(workbook, report)` callers take the new `jurisdiction` arg - see P0)*
- `tests/end_to_end/test_crypto_derivatives_separation.py` *(existing - `_EXPECTED_NUM_COLUMNS` at line 989 + mixed-residency case)*

**Plan-related extension**; implementation and review may change files not listed above when
causally related to a plan task (e.g. a shared country-code constant, or a guidelines/decision
-point doc update implied by an explicit must-fix change).

**Out of scope; reject unless plan-related:**
- `src/tax_reporting/application/persisting/assumptions_sheet.py`; the residency rule prose
  there is already correct (the gap is that the code did not implement what the prose states).
- The filed FY2025 workbook; this plan does not regenerate filed output.
- Building a full multi-country income-code framework; only the PT branch is implemented, with
  a non-PT blank fallback (future countries add their own branch).

## Validation Commands

Run the full block after the final commit (C1). Individual commands are valid only after
their owning task: the Feature-A grep after A2; the Feature-B `_resolve_income_code('interest','PT')`
import and the `40x` grep after B2 (the `40x` grep is clean only at B2 completion, since
`entities.py:418` lives in `application/`); the full `uv run pytest` after B3.

```bash
# Feature A: derivatives residency routing, PT-gated
uv run pytest tests/unit/application/test_crypto_reporting.py tests/unit/application/persisting/test_derivatives_sheet.py tests/end_to_end/test_crypto_derivatives_separation.py -q
# Entity defaults must be the neutral blank route; resident default gone
grep -n 'annex_hint: str = "G/Q13"\|operation_code: str = "G51"' src/tax_reporting/application/crypto/entities.py && echo "STALE resident default still hardcoded (BAD)" || echo "entity defaults flipped to blank (GOOD)"

# Feature B: official income codes, PT-gated; no synthetic 40x label in application/
grep -rn '"40[1-5]"' src/tax_reporting/application/ && echo "synthetic 40x code still in application/ (review)" || echo "no synthetic 40x codes in application/ (GOOD)"
uv run python -c "from tax_reporting.application.crypto.classification import _resolve_income_code; assert _resolve_income_code('interest', 'PT') == 'E25', _resolve_income_code('interest', 'PT'); assert _resolve_income_code('interest', 'DE') == '', 'non-PT must blank'; assert _resolve_income_code('unknown-type', 'PT') == '', 'PT unknown must not default to 401'"

# Cross-cutting
uv run ruff check src/tax_reporting/application/crypto/ src/tax_reporting/application/persisting/
uv run pytest -q
bash ~/.ai-playbook/scripts/check-no-em-dash.sh src/tax_reporting/application/crypto/entities.py src/tax_reporting/application/crypto/ogr_handler.py src/tax_reporting/application/crypto/classification.py src/tax_reporting/application/crypto/aggregation.py src/tax_reporting/application/persisting/derivatives_sheet.py src/tax_reporting/application/persisting/tax_constants.py src/tax_reporting/application/persisting/crypto_supplementary_sheet.py docs/history/plans/2026-06-26-modelo3-code-correctness.md
```

## Tasks

### Task P0 - Test-impact inventory and disposition (prerequisite)

Files:
- `tests/unit/application/persisting/test_derivatives_sheet.py`
- `tests/end_to_end/test_crypto_derivatives_separation.py`
- `tests/unit/application/persisting/test_ib_sheet.py`
- `tests/unit/application/persisting/test_crypto_supplementary_sheet.py`
- `tests/unit/application/test_crypto_entities.py` *(resident-default tests broken by A2)*
- `tests/unit/application/test_crypto_reporting.py` *(9 `aggregate_taxable_rewards` callers broken by B2)*

- [x] Enumerate every existing assertion this plan intentionally breaks and record its
  disposition (re-scope / delete) before touching production code:
  - `test_derivatives_sheet.py`: `_NUM_COLUMNS = len(_COLUMN_HEADERS)` (10 -> 12); the
    "Review lives in the last column (column 10)" assertion; the row-2 detail-line test
    (`test_detail_line_warns_when_entries_disagree` or equivalent) - DELETE (detail line
    removed in A4). The REQUIRED `jurisdiction` param added to `write_derivatives_sheet`
    (A4 guard) means every existing caller (~24) must pass a `jurisdiction` fixture
    (`build_koinly_jurisdiction()`); add the `test_blank_annex_under_pt_warns` and paired
    negative RED cases (A3).
  - `test_crypto_derivatives_separation.py:989` `_EXPECTED_NUM_COLUMNS = 10` -> 12. ALSO:
    2 `write_derivatives_sheet(wb, report)` callers at lines 1007 and 1049 take the new
    REQUIRED `jurisdiction` arg (A4) - pass `build_koinly_jurisdiction(separate_derivatives_reporting=True)`
    (the e2e file already imports `build_koinly_jurisdiction` at line 63).
  - `test_ib_sheet.py` (~line 935-941): the `40x` description assertions -> official
    descriptions; add a non-PT blank case.
  - `test_crypto_supplementary_sheet.py:201` `expected_codes = {"401".."405"}` and `:225` sort
    order -> the official code set; add a non-PT case asserting the reference section is
    omitted. ALSO: ~32 `write_crypto_supplementary_sheet(workbook, report)` callers take the
    new REQUIRED `jurisdiction` arg (B3). Disposition: add `jurisdiction` as a required param;
    update every caller to pass `build_koinly_jurisdiction()` (PT) or a non-PT jurisdiction for
    the new omits-section case. No optional default - a forgotten threading must fail loudly
    (Invariant 4).
  - `test_crypto_entities.py:502-524`: `test_default_annex_hint_is_g_q13` (asserts `:512
    annex_hint == "G/Q13"`) and `test_default_operation_code_is_g51` (asserts `:524
    operation_code == "G51"`) pin the resident defaults A2 flips to `("", "")`. Re-scope to
    `test_default_annex_hint_is_blank` / `test_default_operation_code_is_blank` asserting the
    neutral blank default (Invariant 3).
  - `test_crypto_reporting.py` 9 callers of `aggregate_taxable_rewards(entries)` (lines 2027,
    2118, 2167, 2177, 2205, 2235, 2286, 2340, 2435): B2 adds a REQUIRED `country` param (no
    default - a forgotten call site must fail loudly, not silently fall back to PT).
    Disposition: update each call to pass its jurisdiction's country explicitly (`"PT"` for the
    existing PT-scoped fixtures).
- [x] Confirm `tests/unit/application/persisting/test_derivatives_sheet.py` exists (it does)
  and read its current structure before re-scoping.

### Task A0 - Groundwork: Portugal country-code representation and dispatch point (authoritative; run first)

Files:
- `src/tax_reporting/application/crypto/classification.py` (read `_TABELA_X_COUNTRY_CODES`)
- `src/tax_reporting/application/crypto/ogr_handler.py` (read-only: confirm `jurisdiction` in `_split_ogr_index`)

- [x] Confirm `operator_country` is alpha-2 (verified: `"GB"`, `"AE"`, `"IE"`, `"UNKNOWN"`);
  Portugal = `"PT"`.
- [x] Confirm `"PT"` is present in `_TABELA_X_COUNTRY_CODES` (verified at
  `classification.py:83`). Reuse this constant/validator for any country membership check; do
  NOT introduce a parallel hardcoded country literal.
- [x] Confirm `jurisdiction: TaxJurisdictionConfig` is in scope at the derivatives
  construction site (`_split_ogr_index` receives it, verified line 160-163), so
  `jurisdiction.country` is available without new threading for Feature A.

### Task A1 - RED: derivatives residency routing at construction (PT-gated)

Files:
- `tests/unit/application/test_crypto_reporting.py` *(new cases)*

- [x] `TestDerivativesRouting#test_nonresident_operator_gets_j_q92b_g30`; given a PT
  jurisdiction and a derivatives OGR row whose `operator_country` is a non-PT alpha-2 code
  (e.g. `"IE"` or `"AE"`), expects the built `DerivativesPnLEntry.annex_hint == "J/Q9.2.B"`
  and `operation_code == "G30"`.
- [x] `TestDerivativesRouting#test_resident_operator_gets_g_q13_g51`; given a PT jurisdiction
  and `operator_country == "PT"`, expects `annex_hint == "G/Q13"` and
  `operation_code == "G51"`.
- [x] `TestDerivativesRouting#test_unknown_country_defaults_nonresident`; given a PT
  jurisdiction and `operator_country == "UNKNOWN"`, expects J/Q9.2.B + G30 (fail-safe).
- [x] `TestDerivativesRouting#test_non_pt_jurisdiction_blanks_routing`; given a non-PT
  jurisdiction (`country == "DE"`) and any operator_country (incl. `"PT"`), expects
  `annex_hint == ""` and `operation_code == ""` (Invariant 2: no Modelo 3 hint for non-PT).
- [x] **At least one nonresident case must build the entry through the real
  `_split_ogr_index(...)` construction path** (feed a synthetic OGR row whose wallet resolves
  to a non-PT operator, plus the PT jurisdiction), NOT by calling the pure `_derivatives_route`
  helper directly. This forces the wiring at `ogr_handler.py:266-281` under test; the pure
  helper is unit-tested separately in A2 and must not substitute for construction coverage
  (the suite would otherwise go GREEN while construction still omits the routed fields).
- [x] Run -> expect RED: `uv run pytest tests/unit/application/test_crypto_reporting.py -k DerivativesRouting -q`

### Task A2 - GREEN: implement country-gated residency routing; flip defaults to blank

Files:
- `src/tax_reporting/application/crypto/ogr_handler.py`
- `src/tax_reporting/application/crypto/entities.py`

- [x] Add a pure helper `_derivatives_route(country: str, operator_country: str) -> tuple[str, str]`
  returning `(annex_hint, operation_code)`: non-PT -> `("", "")`; PT + operator `"PT"` ->
  `("G/Q13", "G51")`; PT + anything else (incl. `"UNKNOWN"`, empty) -> `("J/Q9.2.B", "G30")`.
  Unit-test the helper directly (PT-resident, PT-nonresident, PT-unknown, PT-empty,
  non-PT-with-PT-operator, non-PT-unknown).
- [x] At the `DerivativesPnLEntry(...)` construction (`ogr_handler.py:280` region), set
  `annex_hint`/`operation_code` from `_derivatives_route(jurisdiction.country, operator_origin.operator_country)`.
- [x] **Flip the entity field defaults** in `entities.py` to `("", "")` (Invariant 3). Update
  the docstrings/comments: remove the "constant for derivatives (no 365-day exemption)" claim
  (the actual text at `entities.py:161`, with a parallel at `:138-139`; there is no "never
  branches" string in source); document that the OGR handler resolves the route per
  (country, residency) and the default is the neutral blank (no PT hint without a PT
  jurisdiction).
- [x] Run -> expect GREEN: `uv run pytest tests/unit/application/test_crypto_reporting.py -k DerivativesRouting -q`
- [x] Commit: `feat(crypto): route derivatives by counterparty residency under PT jurisdiction`

### Task A3 - RED: per-row Annex/Código columns; detail line removed

Files:
- `tests/unit/application/persisting/test_derivatives_sheet.py` *(re-scope + new cases per P0)*

- [x] `DerivativesSheetTest#test_each_row_carries_own_route` (row-identified coherence against
  PINNED columns); the new columns are header **"Annex"** at column **11** and **"Código"** at
  column **12** (pinned by A4). Given two PT-jurisdiction entries with DISTINGUISHING platforms
  (resident row platform e.g. `"PT-Broker"` carrying G/Q13+G51; non-resident row platform e.g.
  `"Kraken"` carrying J/Q9.2.B+G30), locate each data row by its Platform cell (column 3) and
  read THAT row's column-11 and column-12 cells; assert the PT-Broker row has Annex=="G/Q13"
  AND Código=="G51" together, and the Kraken row has "J/Q9.2.B" + "G30" (each matched to its
  OWN entry, not the other row's values). Reading the specific pinned cells defeats column
  mislabel, field swap, and cross-row contamination (set-membership and generic "each row has
  cells" assertions do not). Also assert the row-2 `_DETAIL_LINE_TEMPLATE` detail line is GONE
  (A4 drops it) so the test cannot be satisfied by reading the legacy detail-line string.
- [x] `DerivativesSheetTest#test_mixed_residency_renders_both_routes`; given a mixed set,
  expects the sheet to contain both `G51` and `G30` in the per-row Código column (supplementary
  to the row-identified check above).
- [x] `DerivativesSheetTest#test_no_single_detail_line_route`; expects the old
  `entries[0]`-derived `_DETAIL_LINE_TEMPLATE` detail line is gone. Delete the prior
  detail-line warning test per P0.
- [x] `DerivativesSheetTest#test_blank_annex_under_pt_warns` (positive); given a PT
  jurisdiction and an entry whose `annex_hint == ""` (a row that failed to resolve a route),
  expects the retained re-scoped guard (A4) emits a `logger.warning` matching a specific
  message so a blank Annex under PT is never rendered silently. Pins the dev_lessons #77/#118
  "surface invalidity loudly" guarantee that the removed detail-line guard previously provided.
- [x] `DerivativesSheetTest#test_no_blank_annex_warning_when_routes_resolved` (paired negative,
  mirrors the existing `test_detail_line_*` positive/negative convention at test lines
  350/384); given a PT jurisdiction where ALL entries resolved non-blank annexes (or any non-PT
  jurisdiction), assert NO warning matching the guard's message is emitted. This forces the
  guard to be gated behind the real condition (PT + blank annex), defeating a trivial
  unconditional `logger.warning(...)` implementation.
- [x] Run -> expect RED: `uv run pytest tests/unit/application/persisting/test_derivatives_sheet.py -q`

### Task A4 - GREEN: per-row columns; remove entries[0] detail line

Files:
- `src/tax_reporting/application/persisting/derivatives_sheet.py`

- [x] Add **Annex** (column 11) and **Código** (column 12) as the last two `_COLUMN_HEADERS`,
  appended after "Review" (so Review moves from last to column 10), and write them in the
  per-row cell writer (10 -> 12 columns); populate column 11 from each entry's `annex_hint`
  and column 12 from `operation_code` (blank for non-PT). Update `_NUM_COLUMNS` to 12. Pin
  these indices so the A3 row-coherence test can read specific cells by position.
- [x] **Drop** the `_DETAIL_LINE_TEMPLATE` single detail line and the `entries[0]` read
  (decision: per-row columns carry the route). Remove the comment claiming the three fields
  are constants across all rows.
- [x] Keep the loss-deductibility footnote, totals row, and empty-state behavior unchanged;
  re-scope the "column 10 Review" assertion to the new last-column index.
- [x] **Retain a re-scoped invariant guard** in place of the removed
  `distinct_constant_tuples` block (dev_lessons #77/#118): when the sheet is rendered under a
  PT jurisdiction and any entry has `annex_hint == ""`, emit `logger.warning` (or raise) so a
  blank/failed route on a PT sheet is surfaced loudly, not silently rendered. The sheet
  receives `jurisdiction` (the `TaxJurisdictionConfig` value object, threaded like the
  supplementary sheet) for this check. This replaces the observability the detail-line guard
  provided.
- [x] Run -> expect GREEN (unit + e2e): `uv run pytest tests/unit/application/persisting/test_derivatives_sheet.py tests/end_to_end/test_crypto_derivatives_separation.py -q`
- [x] Commit: `feat(crypto): per-row Annex/Código columns in Derivatives P&L sheet`

### Task A5 - Unit coverage: resident route under a PT jurisdiction

Files:
- `tests/unit/application/test_crypto_reporting.py` *(new case)*

- [x] `TestDerivativesRouting#test_resident_route_through_full_construction`; given a synthetic
  `OperatorOrigin(operator_country="PT")` and a PT jurisdiction, construct the entry via the
  OGR handler path (or the public construction helper it uses) and assert the resolved entry
  carries `G/Q13` + `G51` end-to-end through construction (not just the pure helper). This
  exercises the resident branch through real construction plumbing, since no PT operator is
  registered in `operator_origin.py` (so an e2e fixture cannot resolve a PT operator from
  wallet labels). If a real PT operator is later registered, promote to e2e (see Monitor).
- [x] Run -> expect GREEN: `uv run pytest tests/unit/application/test_crypto_reporting.py -k resident_route -q`
- [x] Commit: `test(crypto): resident-counterparty derivatives route through construction`

### Task B0 - Investigation: official Modelo 3 code per crypto income type (gates B1/B2)

Files:
- `docs/maintenance/tax/laws/pt/crypto-tax/official/modelo3_anexo_j_2025.pdf` (read-only)
- `docs/maintenance/tax/laws/pt/official/` (other Tabela sources, read-only)

- [x] Data-trace the official code for each internal label by extracting the relevant Tabela
  with `pdftotext -layout` (the method that confirmed E25): interest (anchor: `E25`),
  staking/reward/airdrop, mining, fork, crypto dividends. Record the official code AND the
  categoria (E / G / B) for each. **Separate two consumer needs:** (1) resolver-reachable types
  - `_resolve_income_code` is called only inside `aggregate_taxable_rewards`, which filters to
  `taxable_now` (fiat rewards); crypto-denominated staking/reward/airdrop/mining/fork are
  `DEFERRED_BY_LAW` and never reach the resolver, so likely only `interest` -> E25 is
  resolver-reachable; (2) reference-table display labels - all codes appear in the static
  `_INCOME_CODE_DESCRIPTIONS` reference table regardless of classification. B1's parametrized
  resolver cases target set (1); set (2) is display strings, not resolver outputs.
- [x] For any income type with no single official code (e.g. types whose code depends on
  fiat-vs-crypto form, or rewards deferred to disposal under CRG-002), document the resolution
  rule rather than forcing a wrong code. Flag ambiguous cases to the user.
- [x] Decide and record the resolution shape (flat rename vs per-classification dispatch) and
  confirm the non-PT fallback is `""` for every type. B1 and B2 are written against THIS.
- [x] Write the mapping + shape into the task summary; it is the input to B1/B2.

### Task B1 - RED: official income-code resolution, PT-gated (after B0)

Files:
- `tests/unit/application/test_crypto_reporting.py` *(new cases)*

- [x] `IncomeCodeTest#test_interest_resolves_to_e25_under_pt`; given Koinly type `"interest"`
  (and `"lending"`, `"lending interest"`) under `country == "PT"`, expects
  `_resolve_income_code` to return `"E25"`.
- [x] `IncomeCodeTest#test_<type>_resolves_to_official_under_pt`; one parametrized case per
  income type pinned in B0, each asserting the official code (NOT any `40x`) under PT.
- [x] `IncomeCodeTest#test_default_fallback_blank_under_pt`; given an unknown Koinly type
  under PT, expects `""` (the old `"401"` synthetic default is gone).
- [x] `IncomeCodeTest#test_non_pt_resolves_blank`; given any type under `country != "PT"`
  (e.g. `"DE"`), expects `""` (Invariant 2).
- [x] `IncomeCodeTest#test_descriptions_not_mislabeled_as_tabela_v`; given the official codes,
  expects descriptions consistent with the official Tabela and that nothing presents synthetic
  `40x` codes as "Tabela V".
- [x] `IncomeCodeTest#test_aggregation_threads_reporting_country_to_resolver`; build taxable
  (`taxable_now`) reward entries with `source_type="interest"` and a FOREIGN-counterparty
  `operator_origin.operator_country` (e.g. `"IE"`), call the real
  `aggregate_taxable_rewards(entries, country="PT")`, and assert the resulting
  `AggregatedRewardIncomeEntry.income_code == "E25"` (under `country="DE"` assert `""`).
  This exercises the `aggregation.py:104` call site, NOT the pure helper, so it fails if B2
  forgets to thread `country`, or threads `operator_origin.operator_country` instead of the
  reporting country (the silent-correctness trap of r3 Medium 1).
- [x] `IncomeCodeTest#test_production_path_blanks_income_code_under_non_pt`; build a
  `CryptoTaxReport` with a `taxable_now` interest reward and run it through the PRODUCTION
  workbook-builder path (the `generate_tax_report` / `build_workbook` entrypoint, or
  `workbook_builder.py` directly with a `TaxJurisdictionConfig(country="DE")` constructed via
  `build_koinly_jurisdiction(country="DE")`), then assert the resulting aggregated rewards
  carry `income_code == ""` (Invariant 2). This is the ONLY test shape that catches a
  forgotten or wrong threading at the production call site `workbook_builder.py:148`; the
  direct `aggregate_taxable_rewards` call above bypasses it. (`test_workbook_builder.py`
  hardcodes PT today, so without this case a non-PT regression ships GREEN.)
- [x] Run -> expect RED: `uv run pytest tests/unit/application/test_crypto_reporting.py -k IncomeCode -q`

### Task B2 - GREEN: country-aware official codes; single owner; thread country into aggregation

Files:
- `src/tax_reporting/application/crypto/classification.py`
- `src/tax_reporting/application/crypto/aggregation.py`
- `src/tax_reporting/application/persisting/workbook_builder.py` (thread reporting country into `aggregate_taxable_rewards` at `:148`)
- `src/tax_reporting/application/persisting/tax_constants.py`
- `src/tax_reporting/application/crypto/entities.py` (stale `401` docstring ~line 418)

- [x] Change `_resolve_income_code(source_type, country)`: under `country == "PT"` return the
  official code per B0 (E25 for interest; others per B0), `""` for unknown types; under non-PT
  return `""`. Fix the docstring (stop referencing `"401"` / "Tabela V").
- [x] **Thread the REPORTING country into the resolver as a two-hop change (Invariant 4):**
  (a) add a REQUIRED `country: str` param to `aggregate_taxable_rewards(reward_entries, country)`
  (`aggregation.py:46`) - NO default, so a forgotten production call site is a TypeError at
  call time, not a silent PT fallback; (b) at the sole production caller `workbook_builder.py:148`
  pass `config.tax_jurisdiction.country` (in scope at `:161`); (c) at `aggregation.py:104` call
  `_resolve_income_code(entry.source_type, country)`. The threaded value is the REPORTING
  country, NEVER `entry.operator_origin.operator_country`. Update the 9 test callers per P0
  (each passes its jurisdiction's country explicitly - no optional default to hide behind).
- [x] **Consolidate the duplicated mapping (Invariant 5 - crypto owns):** today
  `classification.py` owns type->code and `tax_constants.py` owns code->description. Make the
  crypto package the single owner - a single type -> (official_code, description) mapping in
  `classification.py` (or a co-located helper) - and have `persisting/tax_constants.py`
  DERIVE/re-export the description half from it. `crypto/` MUST NOT import from `persisting/`
  (no layer inversion). Fix the `tax_constants.py` module docstring.
- [x] Make `get_income_code_description("")` return `""` (not the `"Income code "` fallback)
  so non-PT blank codes render blank at `ib_sheet.py:374`.
- [x] **Guard the sibling description f-string** at `aggregation.py:134`: when `income_code`
  is blank (non-PT), render e.g. `f"Reward income from {source_country}"` instead of the
  malformed `"Income code  from {source_country}"` (double space, empty code). Add the B1 RED
  case asserting no double-space/empty-prefix.
- [x] Fix the stale `401` reference in the `entities.py` docstring (~line 418).
- [x] Run -> expect GREEN: `uv run pytest tests/unit/application/test_crypto_reporting.py -k IncomeCode -q`
- [x] Commit: `fix(crypto): map crypto income codes to official Modelo 3 codes under PT jurisdiction`

### Task B3 - RED + GREEN: render official codes at both user-facing sites; country-driven reference section

Files:
- `src/tax_reporting/application/persisting/ib_sheet.py`
- `src/tax_reporting/application/persisting/crypto_supplementary_sheet.py`
- `src/tax_reporting/application/persisting/workbook_builder.py`
- `tests/unit/application/persisting/test_ib_sheet.py` *(existing - update ~line 935-941 + non-PT blank case)*
- `tests/unit/application/persisting/test_crypto_supplementary_sheet.py` *(existing - update line 201/225 + non-PT omits-section case)*

- [x] `IbSheetTest#test_other_capital_income_renders_official_description_under_pt`; given a PT
  jurisdiction and a crypto-interest entry, expects column 1 shows the official E25 description.
- [x] `IbSheetTest#test_other_capital_income_blank_under_non_pt`; given a non-PT jurisdiction,
  expects the income-code description cell is blank (no `40x`, no fallback string).
- [x] `CryptoSupplementarySheetTest#test_income_code_table_renders_official_codes_under_pt`;
  under PT, expects the Income Code reference table lists official codes (e.g. `E25`) in the
  correct sort order, with the Country column = `"PT"` sourced from the jurisdiction (not a
  hardcoded literal).
- [x] `CryptoSupplementarySheetTest#test_income_code_reference_omitted_under_non_pt`; under a
  non-PT jurisdiction, expects the "1. INCOME CODES REFERENCE" section is absent.
- [x] Thread `jurisdiction` into `write_crypto_supplementary_sheet` via `workbook_builder.py`
  (`config.tax_jurisdiction` is in scope at line 161). Add `tax_jurisdiction: TaxJurisdictionConfig`
  as a REQUIRED param (the frozen value object; its required `country` field makes "unset country"
  impossible by construction - see Invariant 4); update the ~32 existing test callers to pass
  `build_koinly_jurisdiction()` (PT) or a non-PT
  jurisdiction for the omits-section case (per P0). No optional default - a forgotten threading
  must fail loudly. Replace the hardcoded `"PT"` at `crypto_supplementary_sheet.py:177` with
  `jurisdiction.country`; gate the whole reference section on `country == "PT"`. Render
  official codes from the consolidated owner.
- [x] Update `ib_sheet.py:374` to render the description via the blank-safe
  `get_income_code_description`.
- [x] Run -> expect GREEN: `uv run pytest tests/unit/application/persisting/test_ib_sheet.py tests/unit/application/persisting/test_crypto_supplementary_sheet.py -q`
- [x] Commit: `fix(crypto): render official income codes under PT; omit PT reference section otherwise`

### Task C1 - Documentation sync

Files:
- `docs/maintenance/crypto_rules.md`
- `docs/maintenance/tax_reporting_guidelines.md`
- `docs/maintenance/tax/decision_points/2025.md`

- [x] Update `crypto_rules.md` PT-C-031: replace "the repo's `DerivativesPnLEntry` currently
  emits the resident route unconditionally ... the filer must override" with a statement that
  routing is now implemented per counterparty residency under a PT jurisdiction.
- [x] Update `tax_reporting_guidelines.md` (unconditional - A4 + B3 are cross-cutting changes):
  document the Derivatives P&L sheet's new Annex + Código columns under the relevant SRG ID;
  document the PT-country dispatch rule for crypto income codes and derivatives routing (PT
  branch implemented; non-PT leaves these fields blank).
- [x] Document explicitly that the Crypto Supplementary "1. INCOME CODES REFERENCE" section is
  rendered only under `country == "PT"` and is OMITTED (the whole numbered section, not just
  its fields) under non-PT jurisdictions - this is a user-visible structural change distinct
  from field-level blanking.
- [x] Add a `decision_points/2025.md` changelog entry noting derivatives routing and income
  codes are now code-driven and PT-gated (were documented filer-override gaps).
- [x] Grep tracked docs AND `src/tax_reporting/application/` for stale `40x` / "Tabela V"
  income-code claims and the "constant for derivatives (no 365-day exemption)" derivatives
  claim, and correct them. (Each known stale src site is task-owned; this grep is the backstop
  for any claim lingering elsewhere - match `40x`, "Tabela V", and "constant for derivatives".)
- [x] Commit: `docs(crypto): reflect implemented PT-gated derivatives routing + official income codes`

## Monitor

- **Promote A5 to e2e when a PT operator is registered.** Task A5 covers the resident route
  through construction (unit-level) because no PT-counterparty operator exists in
  `operator_origin.py` today. If a real PT operator is later registered, promote the resident
  case to the e2e `test_crypto_derivatives_separation.py` fixture so it exercises
  `ogr_handler` -> `Reporting` -> sheet end-to-end.
- **Allowlist-completeness assertion on `_derivatives_route`.** The helper returns from a
  closed 3-tuple set (`("G/Q13","G51")`, `("J/Q9.2.B","G30")`, `("","")`), so output is
  allowlisted by construction and there is no formula-injection vector (inputs come from the
  registry/config, not raw user input). Add a one-line test asserting the helper never
  returns a value outside the known three tuples, so a future edit cannot pass an unvalidated
  string through to a cell.
- **`aggregation.py:134` description field is currently unrendered** by `ib_sheet.py` (which
  uses `income_code`/`source_country`/`gross_income_eur`/`chains`, not `description`). The B2
  blank-code guard makes it safe; if a future change renders `description`, the B1 RED case
  already pins the no-double-space contract.

