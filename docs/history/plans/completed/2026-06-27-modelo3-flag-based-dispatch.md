# Plan: Country-agnostic annex/income-code dispatch via decision-point flags

Supersedes the country-gating mechanism introduced by the 2026-06-26 modelo3-code-correctness plan
(lesson #182) and reverts its `PORTUGAL_COUNTRY_CODE` consolidation (commit `e9ca82f`).

Plan review: `docs/history/reviews/2026-06-27-plan-review-modelo3-flag-based-dispatch-r6.md` (r6, ready - 0 Blockers, 0 Medium; r5 Medium test_derivatives_sheet.py stale wording amended in Review Scope + Task 4; comprehensive wording grep clean) · r5 · r4 · r3

## Terms

- **Decision-point flag:** a `bool` field on `TaxJurisdictionConfig`, auto-discovered by the
  config loader (`_KNOWN_BOOL_FLAGS`) and populated per-country from
  `docs/maintenance/tax/decision_points/<year>.toml`; absent -> `False`.
- **Counterparty residency:** whether the derivative's operator/exchange entity is resident in the
  *taxpayer's own country* (`operator_country == country`), not in any hardcoded country.
- **Modelo 3 / Tabela V codes:** PT-specific IRS form codes (`G51`/`G30` derivatives operation
  codes; `E25` Categoria E income code). Country-specific emitted *values*, gated by country-agnostic flags.
- **OGR:** Other Gains Report; the source for derivatives P&L rows routed through `_split_ogr_index`.

## Gist & Examples

**What changes.** The modelo3 plan gated two PT-specific outputs on a `country == "PT"` literal in
the application layer: derivatives annex/operation-code routing (`G51`/`G30`) and crypto-reward
income codes (`E25`). That bakes Portugal into the pipeline. The established repo pattern is
country-**agnostic**: jurisdiction behavior is a **decision-point boolean flag** on
`TaxJurisdictionConfig` (siblings: `exclude_loan_repayment_gains`, `separate_derivatives_reporting`,
`futures_derivatives_taxable`), populated per-country from the decision-points TOML. The only
legitimate `== "PT"` lives in the config loader (validation + the country-from-config boundary).

This refactor replaces every application-layer country literal with two new flags, and fixes a latent
bug the country-gating hid: the derivatives residency test compared `operator_country == "PT"`
instead of "counterparty resident in the taxpayer's country" (`operator_country == country`).

The emitted codes themselves (G51/G30/E25) stay as **explicitly PT-named module constants** - they are
law-cited PT form data, not user config (YAGNI: only PT defines them; matches the existing
`_TABELA_X_COUNTRY_CODES` / `_INCOME_CODE_DESCRIPTIONS` hardcoded-constant pattern). When a real
second country arrives, extract a `_codes_for(country)` dispatch then.

**Example - derivatives routing, before vs after** (`ogr_handler._derivatives_route`):
```python
# BEFORE (country literal; residency also baked to PT)
def _derivatives_route(country, operator_country):
    if country.upper() != "PT": return "", ""
    if operator_country.upper() == "PT": return "G/Q13", "G51"
    return "J/Q9.2.B", "G30"

# AFTER (flag-gated; country-agnostic residency; codes are PT-named constants)
def _derivatives_route(country, operator_country, route_via_residency: bool):
    if not route_via_residency: return "", ""
    if operator_country.upper() == country.upper():
        return _PT_RESIDENT_ANNEX_HINT, _PT_RESIDENT_OPERATION_CODE      # "G/Q13", "G51"
    return _PT_NONRESIDENT_ANNEX_HINT, _PT_NONRESIDENT_OPERATION_CODE    # "J/Q9.2.B", "G30"
```

**Example - income codes** (`classification._resolve_income_code`):
```python
# AFTER
def _resolve_income_code(koinly_type, classify_with_income_codes: bool) -> str:
    if not classify_with_income_codes: return ""
    # interest/lending/lending interest -> "E25" (PT Tabela V); else ""
```

**Behavior preserved for PT.** PT production output is unchanged: `2025.toml [countries.PT]` sets
both flags `true`, so PT emits the same `G51`/`G30`/`E25` codes as today. The change is the
*gating mechanism* (flag, not literal) and the *residency test* (same-country, not PT-literal).

## Design Invariants (CR Guard)

1. **No application-layer country literal.** After this plan, `src/tax_reporting/application/`
   contains zero `== "PT"` / `!= "PT"` / `PORTUGAL_COUNTRY_CODE` references. `== "PT"` survives only
   in the config loader (`infrastructure/config.py`: validation + PT timezone default) and the
   Tabela-X membership set (`_TABELA_X_COUNTRY_CODES` in classification.py, which is legitimate
   country-list membership, not a gate). Validation command enforces this.
2. **Country-agnostic residency.** A derivative routes to the *resident* annex iff
   `operator_country == country` (counterparty resident in the taxpayer's own country), never
   `operator_country == "PT"`. The discriminating test is a non-PT jurisdiction with the flag on
   (`("DE","DE",True)` -> resident codes).
3. **Codes remain PT-specific constants.** `G51`/`G30`/`E25` are NOT abstracted into a per-country
   TOML table. They are renamed to `_PT_*` constants in their modules with legal citations, gated by
   the country-agnostic flag. (Per design discussion: a TOML code table is speculative for one
   country and would let non-expert users edit official form codes without review.)
4. **Defaults fail safe / jurisdiction-neutral.** Both flags default `False`; a jurisdiction without
   the flag emits no codes (blank). Entity field defaults remain the blank route.
5. **Loader unchanged.** `_KNOWN_BOOL_FLAGS` auto-discovers bool fields via `get_type_hints`; adding
   the two fields + TOML entries is sufficient. No `config.py` code edit. The two new flags follow the
   defaulted-`False` behavioral-switch shape (`futures_derivatives_taxable`/`separate_derivatives_reporting`
   siblings, also PT-relevant and also not fail-fast), NOT the required-field shape of
   `exclude_loan_repayment_gains` (the lone PT fail-fast at `config.py:321`, CIRS art. 10(20)-mandated).
   A PT TOML that drops either new key silently resolves `False` (blanks `G51`/`G30`/`E25`); accepted as
   consistent with the other defaulted-`False` switches.
6. **PT behavior is byte-identical.** PT (flags `true` in TOML; `True` in
   `build_koinly_jurisdiction`) produces the same routed codes and income codes as before the refactor.
7. **Intentional signature asymmetry (guard against a future bad refactor).** `_derivatives_route`
   keeps `country` (it genuinely needs it for the residency relation `operator_country == country`);
   `_resolve_income_code` drops `country` for a bool (its only `country` use was a binary PT-gate, so
   the bool is the truer concept). Do NOT "normalize" the resolver to take `country` again - that
   would re-introduce the country literal this refactor removes.

## Evaluation Criteria

**Quality dimensions:**
- Correctness: PT derivatives still route `G51` (resident operator) / `G30` (non-resident/UNKNOWN/empty);
  PT crypto interest still resolves `E25`, all other reward types blank. A flag-`False` jurisdiction
  emits blank codes. Residency is `operator_country == country` (proven by a `("DE","DE",True)`
  resident case and `("PT","DE",True)` non-resident case).
- Country-agnosticism: `grep` for application-layer country literals returns nothing.
- Maintainability: gating follows the existing decision-point-flag pattern (lesson #68 mechanism);
  docs (#182, SRG-010, PT-C-031, CLAUDE.md) describe the flag mechanism, not a country literal.
- No regression: full suite green except the 2 pre-existing `TestOgrCharacterizationGolden` errors.

**Release gates:**
- `uv run pytest -q` passes (1492 passed, 2 pre-existing errors).
- `uv run ruff check` clean on touched modules.
- No em dash in changed files (`check-no-em-dash.sh`).
- Application-layer country-literal grep empty.

## Review Scope

**Explicit must-fix**; findings on these paths are always in scope (review and fix if valid):

**Production code:**
- `src/tax_reporting/domain/jurisdiction.py` *(remove `PORTUGAL_COUNTRY_CODE` + `Final` import; add 2 flags)*
- `src/tax_reporting/application/crypto/ogr_handler.py` *(rename codes `_PT_*`; new `_derivatives_route` signature; residency fix; call site; drop import)*
- `src/tax_reporting/application/crypto/classification.py` *(`_resolve_income_code` signature + gate + docstring)*
- `src/tax_reporting/application/crypto/aggregation.py` *(`aggregate_taxable_rewards` signature + docstring)*
- `src/tax_reporting/application/persisting/workbook_builder.py` *(call site)*
- `src/tax_reporting/application/persisting/derivatives_sheet.py` *(gate + drop import + docstring)*
- `src/tax_reporting/application/persisting/crypto_supplementary_sheet.py` *(gate + drop import + docstrings)*

**Tests:**
- `tests/conftest.py` *(`build_koinly_jurisdiction` defaults)*
- `tests/unit/application/test_crypto_reporting.py` *(`TestDerivativesRouting` :11314, `TestIncomeCode` :11496, module-level `test_resolve_income_code_from_koinly_type` :2381, `test_aggregation_threads_reporting_country_to_resolver` :11533, and the 10 `aggregate_taxable_rewards(..., country="PT")` + 1 `country="DE"` callers)*
- `tests/unit/application/test_crypto_classification.py` *(`TestIncomeCodeResolution` :102 - 4 `_resolve_income_code(..., country="PT")` callers at lines 108/115/122/129)*
- `tests/unit/application/persisting/test_crypto_supplementary_sheet.py` *(`test_income_code_reference_omitted_under_non_pt` :254 - DE jurisdiction construction :259)*
- `tests/unit/application/persisting/test_derivatives_sheet.py` *(:462/:466/:484/:487 stale "under the PT jurisdiction"/"under PT" docstring + assertion-message wording - behavior stays green under PT default, but the wording must move to flag-based)*

**Decision points + docs:**
- `docs/maintenance/tax/decision_points/2025.toml`, `docs/maintenance/tax/decision_points/2025.md`
- `docs/maintenance/development_lessons.md` (#182), `AGENTS.md`/`CLAUDE.md`, `docs/maintenance/tax_reporting_guidelines.md` (SRG-010), `docs/maintenance/crypto_rules.md` (PT-C-031)

**Plan-related extension**; review may also change files not listed above when causally related -
e.g. additional test callers of `_resolve_income_code`/`aggregate_taxable_rewards`/`_derivatives_route`
discovered by `grep -rn` across `tests/` (lessons #111/#183), or stale doc cross-references to the
old "PT-country dispatch" wording. The 4 untracked rent-deduction files under
`docs/maintenance/tax/laws/pt/` (README.md, sources.md, the Portaria PDF,
rent_deduction_cross_reference.md) are NOT touched by this plan.

**Out of scope; reject unless plan-related:**
- `src/tax_reporting/infrastructure/config.py`; the loader is unchanged by design (Invariant 5). The
  two `== "PT"` checks there (validation line 321, timezone default line 276) are the approved
  country-from-config boundary and stay.
- `_TABELA_X_COUNTRY_CODES` membership set in classification.py (legitimate country list, not a gate).

## Validation Commands

```bash
# 1. Loader auto-discovers the new bool flags; PT TOML resolves them True; US False
uv run python -c "import tomllib;d=tomllib.load(open('docs/maintenance/tax/decision_points/2025.toml','rb'));print(d['countries']['PT']['route_derivatives_by_counterparty_residency'],d['countries']['PT']['classify_rewards_with_income_codes'])"
# 2. Routing: flag False -> blank; flag True + same-country -> resident; diff/UNKNOWN/empty -> non-resident
uv run python -c "from tax_reporting.application.crypto.ogr_handler import _derivatives_route as r;print(r('PT','PT',False),r('PT','PT',True),r('PT','DE',True),r('PT','UNKNOWN',True),r('DE','DE',True))"
# 3. Income code: flag-gated (interest -> E25 under True; blank under False)
uv run python -c "from tax_reporting.application.crypto.classification import _resolve_income_code as f;print(f('interest',True),f('interest',False),f('staking',True))"
# 4. NO application-layer country literal remains (Invariant 1)
! grep -rn '== "PT"\|!= "PT"\|PORTUGAL_COUNTRY_CODE' src/tax_reporting/application/
# 5. Full suite + lint + em-dash
uv run pytest -q
uv run ruff check src/tax_reporting/domain/jurisdiction.py src/tax_reporting/application/
bash ~/.ai-playbook/scripts/check-no-em-dash.sh file src/tax_reporting/domain/jurisdiction.py src/tax_reporting/application/crypto/ogr_handler.py src/tax_reporting/application/crypto/classification.py src/tax_reporting/application/crypto/aggregation.py src/tax_reporting/application/persisting/workbook_builder.py src/tax_reporting/application/persisting/derivatives_sheet.py src/tax_reporting/application/persisting/crypto_supplementary_sheet.py
```

### Task 1: RED - rewire routing/income-code tests to flag-based signatures

**Pre-step (lessons #111/#183 - the grep output IS the authoritative caller list; do NOT edit from memory):** before editing, run ALL THREE greps and record every hit:
- `grep -rn "_resolve_income_code(" tests/` (current snapshot: 4 hits in `test_crypto_classification.py`, ~30 in `test_crypto_reporting.py`)
- `grep -rn "aggregate_taxable_rewards(" tests/` (current snapshot: 10 `country="PT"` callers + 1 `country="DE"` caller, all in `test_crypto_reporting.py`)
- `grep -rn "_derivatives_route(" tests/` (current snapshot: all in `test_crypto_reporting.py::TestDerivativesRouting`)
- `grep -rn "build_koinly_jurisdiction(country=" tests/` (current snapshot: exactly TWO non-PT constructions - see the DE-inheritance rule below)

Every hit must be rewired in this task; a missed caller `TypeError`s at suite run. Re-run each grep after editing and confirm zero stale `country=` keyword hits remain on these three functions.

**Global rule - DE/non-PT flag inheritance (the trap r1/r2 found):** `build_koinly_jurisdiction(**overrides)` uses `defaults.update(overrides)`, which ADDS keys but never REMOVES them. The new flags default `True` in `build_koinly_jurisdiction`. Therefore `build_koinly_jurisdiction(country="DE")` alone leaves BOTH flags `True` - a "DE" jurisdiction would still emit `E25`/`G51`, silently inverting Invariant 4. **Every** `build_koinly_jurisdiction(country="<non-PT>")` construction that asserts non-Modelo3/blank behavior MUST explicitly pass the relevant flag(s) `=False`. The grep shows exactly two such constructions today; both are named below.

Files:
- `tests/unit/application/test_crypto_reporting.py`
- `tests/unit/application/test_crypto_classification.py`
- `tests/unit/application/persisting/test_crypto_supplementary_sheet.py`

- [x] `TestDerivativesRouting#test_*`; given the new signature `_derivatives_route(country, operator_country, route_via_residency)`, expects flag `False` -> `("", "")` for any country; flag `True` + same-country operator -> resident codes; flag `True` + differing/UNKNOWN/empty operator -> non-resident codes
- [x] `TestDerivativesRouting` adds TWO country-agnostic resident cases (lesson #133 - N independent guards, not one OR'd case): given `_derivatives_route("DE","DE",True)` AND `_derivatives_route("FR","FR",True)`, each expects resident codes (`"G/Q13"`,`"G51"`) - proves residency is `operator_country == country`, defeating both a PT literal and a `{PT,DE}` allow-list regression
- [x] `TestDerivativesRouting` adds a non-resident pair on a second non-PT country; given `_derivatives_route("FR","DE",True)`, expects non-resident codes (`"J/Q9.2.B"`,`"G30"`)
- [x] `TestDerivativesRouting` adds a flag-off case; given `_derivatives_route("PT","PT",False)`, expects `("", "")` - a PT jurisdiction with the flag off emits nothing
- [x] DELETE two stale-contract tests whose premise (non-PT country -> blank) no longer holds under flag-gating (r3 Blocker): `test_non_pt_jurisdiction_blanks_routing` (:11381; `_derivatives_route("DE","PT")` asserting blank) and `test_non_pt_jurisdiction_unknown_operator_blanks_routing` (:11409; `_derivatives_route("DE","UNKNOWN")` asserting blank). Under the new contract a DE jurisdiction with the flag `True` would route to non-resident codes (`("J/Q9.2.B","G30")`), NOT blank - so these tests assert a contract that is now wrong. Their original intent ("flag off -> blank" and "country-agnostic residency") is covered by the new `("PT","PT",False)` blank case and the `("DE","DE",True)`/`("FR","FR",True)` resident cases. Do NOT port them to 3-arg form keeping the blank assertion
- [x] Existing `test_pt_jurisdiction_empty_operator_defaults_nonresident` (~:11398; `_derivatives_route("PT","")` -> non-resident): add the third arg `True` (flag on + `"" != "PT"` -> non-resident, unchanged behavior)
- [x] Every `_resolve_income_code(...)` caller (grep-authoritative; spans `TestIncomeCode` methods, the module-level `test_resolve_income_code_from_koinly_type`, and `test_crypto_classification.py::TestIncomeCodeResolution`): new signature `_resolve_income_code(koinly_type, classify_with_income_codes)`; `country="PT"` -> `classify_with_income_codes=True` (interest/lending/lending interest -> `"E25"`, else `""`); `country="DE"`/`country="US"` -> `classify_with_income_codes=False` (everything -> `""`)
- [x] Every `aggregate_taxable_rewards(...)` caller (grep-authoritative; 10 `country="PT"` -> `classify_rewards_with_income_codes=True`; the `country="DE"` caller -> `classify_rewards_with_income_codes=False`)
- [x] `test_aggregation_threads_reporting_country_to_resolver` - rewrite prescriptively (r3 Medium): rename to `test_aggregation_threads_classification_flag_to_resolver`; REPLACE the foreign-operator IE fixture with a plain interest reward (the IE operator existed only to exercise country-threading, which no longer exists - drop it); delete the stale "B2 could mistakenly thread operator_country" rationale from the docstring; assert the SAME interest reward yields `income_code == "E25"` under `classify_rewards_with_income_codes=True` and `income_code == ""` under `False` (the dual assertion is the discriminator; a single-arm test cannot catch a country-literal revert - lesson #125)
- [x] DE construction #1 - `test_crypto_reporting.py::test_production_path_blanks_income_code_under_non_pt`: change `build_koinly_jurisdiction(country="DE")` (the `de_jurisdiction` local) to also pass `classify_rewards_with_income_codes=False`. Do NOT edit the `_capturing_aggregate` spy wrapper - it correctly forwards `**kwargs`, so the fix belongs on the jurisdiction object; the captured production call then carries `False` and the interest row blanks end-to-end
- [x] DE construction #2 - `test_crypto_supplementary_sheet.py::test_income_code_reference_omitted_under_non_pt`: change `build_koinly_jurisdiction(country="DE")` to also pass `classify_rewards_with_income_codes=False`, so the "1. INCOME CODES REFERENCE" section is structurally omitted (with the flag inherited `True` it would render and the test would fail)
- [x] Run -> expect RED: `uv run pytest tests/unit/application/test_crypto_reporting.py::TestDerivativesRouting tests/unit/application/test_crypto_reporting.py::TestIncomeCode tests/unit/application/test_crypto_classification.py tests/unit/application/persisting/test_crypto_supplementary_sheet.py -q` (TypeError: unexpected/missing keyword args against the still-country-gated production signatures)

### Task 2: GREEN - add flags, gate the four sites, rename codes `_PT_*`, fix residency, remove `PORTUGAL_COUNTRY_CODE`

Files:
- `src/tax_reporting/domain/jurisdiction.py`
- `src/tax_reporting/application/crypto/ogr_handler.py`
- `src/tax_reporting/application/crypto/classification.py`
- `src/tax_reporting/application/crypto/aggregation.py`
- `src/tax_reporting/application/persisting/workbook_builder.py`
- `src/tax_reporting/application/persisting/derivatives_sheet.py`
- `src/tax_reporting/application/persisting/crypto_supplementary_sheet.py`
- `tests/conftest.py`

- [x] `TaxJurisdictionConfig`: add `route_derivatives_by_counterparty_residency: bool = False` and `classify_rewards_with_income_codes: bool = False` (Attributes docstrings citing CIRS art. 10(1)(e)+Quadro 13/9.2.B and Tabela V E25 respectively); remove `PORTUGAL_COUNTRY_CODE` and `from typing import Final` (jurisdiction.py:7,17)
- [x] `build_koinly_jurisdiction` (conftest.py:184 defaults dict): add both flags `True` (PT default; keeps sheet/e2e tests unchanged)
- [x] `ogr_handler` constants (lines 32-35): rename `_RESIDENT_*`/`_NONRESIDENT_*` -> `_PT_RESIDENT_*`/`_PT_NONRESIDENT_*` with a CIRS art. 10(1)(e) + Quadro 13/9.2.B citation comment
- [x] `ogr_handler._derivatives_route` signature (line 38): `(country, operator_country, route_via_residency: bool) -> tuple[str, str]`
- [x] `ogr_handler` gate (line 64): `if not route_via_residency: return "", ""` (was `country.upper() != PORTUGAL_COUNTRY_CODE`)
- [x] `ogr_handler` residency fix (line 66): `if operator_country.upper() == country.upper():` -> resident (was `== PORTUGAL_COUNTRY_CODE`) - this is the latent bug the refactor fixes
- [x] `ogr_handler` call site (line 308): pass `jurisdiction.route_derivatives_by_counterparty_residency`; drop `PORTUGAL_COUNTRY_CODE` import (line 11); update the call-site comment (lines 307-309) from "PT-gated" to "flag-gated"
- [x] `classification._resolve_income_code(koinly_type, classify_with_income_codes: bool)` (line 458); gate `if not classify_with_income_codes: return ""` (line 479); docstring revision (line ~461) - drop "country == 'PT'"; leave `_TABELA_X_COUNTRY_CODES` (line 496) untouched
- [x] `aggregation.aggregate_taxable_rewards(reward_entries, classify_rewards_with_income_codes: bool)` (line 46); thread the flag to `_resolve_income_code` (line 107); docstring revision (lines ~56-58 - drop "country" / "NEVER the operator country")
- [x] `workbook_builder` call site (line 148): `aggregate_taxable_rewards(reward_entries, config.tax_jurisdiction.classify_rewards_with_income_codes)`
- [x] `derivatives_sheet` gate (line 79): `if entries and jurisdiction.route_derivatives_by_counterparty_residency:`; drop `PORTUGAL_COUNTRY_CODE` import (line 12)
- [x] `derivatives_sheet` WARNING format string (lines 85-88): change "under the PT jurisdiction" -> "under the active jurisdiction" (a non-PT jurisdiction with the flag on and an UNKNOWN operator would otherwise be mislabeled; CLAUDE.md Rule 1 self-explanatory labels); docstring BODY (lines 58-61) "(blank for non-PT jurisdictions)" -> "(blank when residency routing is disabled)" and "When the sheet renders under a PT jurisdiction ... a warning is emitted" -> "when residency routing is enabled and any entry has a blank annex_hint, a warning is emitted"; docstring Args (line ~70) "under a PT jurisdiction" -> "when residency routing is enabled"
- [x] `crypto_supplementary_sheet`: gate `if tax_jurisdiction.classify_rewards_with_income_codes:` (line 166); drop `PORTUGAL_COUNTRY_CODE` import (line 20); docstrings (lines ~137, ~150) "PT only" / `country == "PT"` -> "when income-code classification is enabled"
- [x] Run -> expect GREEN: `uv run pytest tests/unit/application/test_crypto_reporting.py::TestDerivativesRouting tests/unit/application/test_crypto_reporting.py::TestIncomeCode tests/unit/application/test_crypto_classification.py tests/unit/application/persisting/test_crypto_supplementary_sheet.py -q`
- [x] Loader auto-discovery roundtrip test (r3 Medium - Invariant 5 is currently untested; follow the sibling `test_separate_derivatives_reporting_true_from_toml` at test_crypto_reporting.py:9002, which always includes `exclude_loan_repayment_gains = true`): add a GREEN test that monkeypatches `_DECISION_POINTS_DIR` to a tmp dir, writes a `2025.toml` with both new flags `true` under `[countries.PT]`, calls `_load_tax_jurisdiction_config`, and asserts `route_derivatives_by_counterparty_residency is True` and `classify_rewards_with_income_codes is True`; plus a second case whose `[countries.PT]` KEEPS `exclude_loan_repayment_gains = true` (REQUIRED - the loader raises `ValueError` for PT without it, `config.py:321`) but OMITS the two new flags, and asserts both resolve `False` via the `setdefault(flag_name, False)` loop at `config.py:334-336` (the auto-discovery default), NOT via an empty section. Proves the loader picks up the new bool fields with NO `config.py` edit
- [x] Run full suite -> expect 1492 passed, 2 pre-existing `TestOgrCharacterizationGolden` errors: `uv run pytest -q`
- [x] Commit: `refactor: gate modelo3 annex/income-code dispatch on decision-point flags, not country literals`

### Task 3: Decision-points TOML + MD (DP-017 / DP-018)

Files:
- `docs/maintenance/tax/decision_points/2025.toml`
- `docs/maintenance/tax/decision_points/2025.md`

- [x] `2025.toml [countries.PT]`: add `route_derivatives_by_counterparty_residency = true` and `classify_rewards_with_income_codes = true` with legal-basis comments; `[countries.US]` left without them (default `False`)
- [x] `2025.md` Decision Points table: add DP-017 (route derivatives by counterparty residency -> Yes under PT; CIRS art. 10(1)(e) + Quadro 13/9.2.B; residency test `operator_country == country` -> resident=G51/Quadro 13, non-resident (or UNKNOWN/empty)=G30/Quadro 9.2.B) and DP-018 (classify crypto rewards with Modelo 3 income codes -> Yes under PT; Tabela V E25 for the interest family, else blank)
- [x] `2025.md` changelog: **revise the existing 2026-06-27 row at line 116 in place** (do NOT append a second same-dated row) - replace the "No new TaxJurisdictionConfig flag was added / dispatch reuses the existing `country` field / `2025.toml` sidecar is unchanged" wording with the flag-based mechanism (DP-017/DP-018 added; both flags `true` under PT; `2025.toml` updated; dispatch now gates on the flags, not `country`). Verify no duplicate 2026-06-27 row remains
- [x] Run -> expect GREEN: validation command 1 (TOML resolves both `True`)

### Task 4: Doc revisions - mechanism change (country literal -> flag)

Files:
- `docs/maintenance/development_lessons.md`
- `AGENTS.md` *(and the `CLAUDE.md` symlink)*
- `docs/maintenance/tax_reporting_guidelines.md`
- `docs/maintenance/crypto_rules.md`

- [x] `development_lessons.md` #182 (line 3168): revise the Rule and "What happened" - keep the principle (jurisdiction-specific output must be gated, never unconditional) but change the mechanism from "resolver takes `country`, gates on `country == 'PT'`" to "add a decision-point flag on `TaxJurisdictionConfig` (per #68), gate application code on the flag; never compare a country literal. Emitted codes remain jurisdiction-specific `_PT_*` constants." Re-title from "Country-Gated" to "Flag-Gated". Update the #68/#150 distinction paragraph
- [x] `AGENTS.md` (line 60): "Jurisdiction-specific output must be gated on `TaxJurisdictionConfig.country`, never unconditional" -> "...on a `TaxJurisdictionConfig` decision-point flag, never on a country literal nor unconditional"; keep cross-refs #68/#150/#182
- [x] `tax_reporting_guidelines.md` SRG-010 (line 88): rewrite to flag-based dispatch naming both flags; replace `TaxJurisdictionConfig.country == "PT"` wording
- [x] `tax_reporting_guidelines.md` country-gating prose OUTSIDE SRG-010 (lines 78, 79, 82, 84 - the single grep does not catch all): line 78 stale signature `_derivatives_route(country, operator_country)` -> new 3-arg signature; line 79 "Under a PT jurisdiction ... resolves these per row" -> "When `route_derivatives_by_counterparty_residency` is on"; line 82 `TaxJurisdictionConfig.country == "PT"` -> `classify_rewards_with_income_codes`; line 84 "Under a PT jurisdiction the sheet warns" -> "When the flag is on the sheet warns"
- [x] `crypto_rules.md` PT-C-031 (header line 140; body ~159-167): update the `ogr_handler._derivatives_route(country, operator_country)` description to the new 3-arg signature, the `operator_country == country` residency test (was `operator_country == "PT"`), and the `route_derivatives_by_counterparty_residency` gate (was `country == "PT"`); update "under PT it warns" -> "when the flag is on it warns"
- [x] Stale country-gating references outside the SRG/PT-C rule bodies (grep `docs/` and `tests/`): `tests/unit/application/persisting/test_ib_sheet.py:963` comment "income_code='' is what aggregate_taxable_rewards produces under non-PT" -> "...under classify_rewards_with_income_codes=False"; `docs/maintenance/project-walkthrough.md:143` "Under a PT jurisdiction the interest/lending family resolves to ... E25; under a non-PT country the income code resolves to blank" -> flag-based wording; `tests/unit/application/persisting/test_derivatives_sheet.py:462/466/484/487` docstring + assertion messages "under the PT jurisdiction" / "under PT" -> "when `route_derivatives_by_counterparty_residency` is on" (behavior is unchanged - the test stays green under the PT default - this is wording-only)
- [x] Update the defining docstrings of the two classes Task 1 rewrites line-by-line (r3 Low 2, re-raised r4 Medium 2 - the catch-all grep below is treated as optional by executors): `TestDerivativesRouting` docstring (`tests/unit/application/test_crypto_reporting.py:11247-11251`), `TestIncomeCode` docstring (`:11429-11443`), and the `:11424` section comment - replace "PT-gated" / 'under `country == "PT"`' / "non-PT jurisdiction" with flag-based wording matching the Task-1-rewritten tests. Also the stale occurrences at `:6293`, `:11432`, `:11442`, `:11554`, `:11581`, `test_ib_sheet.py:955`/`:989`, and `test_crypto_supplementary_sheet.py:255`
- [x] Grep for stale "PT-country dispatch" / `country == "PT"` / "PT-gated" / "Under a PT jurisdiction" / "non-PT jurisdiction" / "under non-PT" wording across `docs/maintenance/` and `tests/` and fix plan-related occurrences
- [x] Run → expect GREEN: `uv run pytest -q` (docs-only; suite unaffected); em-dash check on changed docs
- [x] Commit: `docs: switch modelo3 dispatch docs from country-literal to decision-point flags`
