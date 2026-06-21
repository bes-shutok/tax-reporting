# Plan: Crypto timezone normalization (naive dates as jurisdiction-local)

Related RFC: `docs/history/feature-notes/2026-06-20-th-anchored-transaction-state-machine.md` (weakness #3). Decision point: DP-014 (payment-proceeds correction). Review context: `docs/history/reviews/2026-06-20-branch-review-doc-hierarchy-migration.md`.

Plan review: `docs/history/reviews/2026-06-20-plan-review-crypto-timezone-normalization-r2.md` (latest, ready=yes: 0 Blocker, 0 Medium, 3 Low folded in) · `...-r1.md` (1 Blocker + 7 Medium, all addressed in r2) · `...-inline.md` (pre-review spot-check).

## Terms

- **CG** - Capital Gains Koinly report. `Date Sold` and `Date Acquired` are naive `DD/MM/YYYY HH:MM`.
- **OGR** - Other Gains Koinly report. `Date` is naive `DD/MM/YYYY HH:MM`.
- **TH** - Transaction History Koinly report. `Date` is explicit `YYYY-MM-DD HH:MM:SS UTC`.
- **WET / WEST** - mainland Portugal winter / summer zones (UTC+0 / UTC+1).
- **IANA zone** - tz-database name such as `Europe/Lisbon`, resolved with stdlib `zoneinfo`.
- **naive date** - a datetime string with no zone suffix; per project policy it denotes local time, not UTC, even when it numerically coincides with UTC.

## Gist & Examples

Koinly writes CG, OGR, and Income dates as naive `DD/MM/YYYY HH:MM` strings, and TH dates with an explicit `UTC` suffix. The parser (`parse_koinly_datetime`, `src/tax_reporting/infrastructure/koinly_parser.py:99`) currently stamps every naive date as UTC (`parsed.replace(tzinfo=UTC)` at line 118). A data trace against the real `resources/source/koinly2025/` set proves the naive dates are mainland-Portugal local time: the CG-minus-TH hour offset is ~0h in winter (Jan-Mar, Nov-Dec) and ~+1h in summer (Apr-Oct), with the spring-forward jump visible in late March and the fall-back in late October. That is WET (UTC+0) in winter and WEST (UTC+1) in summer.

Because the naive dates are local but treated as UTC, a summer disposal recorded 00:00-00:59 local (which is 23:00-23:59 UTC the previous day) is stamped onto the wrong UTC day. Every cross-report match key that pairs a naive date (CG) with an explicit-UTC date (TH) can then disagree by one calendar day. Two live keys are exposed:

- DP-014 payment matching (`_calendar_day` over CG `disposal_date` vs TH `Date`) can silently miss a payment twin.
- Derivatives dedup exact-match (`disposal_timestamp` from CG vs `timestamp` from TH) can mismatch at minute resolution.

The change: interpret naive dates as the jurisdiction's IANA zone (default `Europe/Lisbon` for PT), let `zoneinfo` convert to UTC (it handles DST transitions historically, so no manual spring/autumn day lookup), and keep TH explicit-UTC dates exactly as they are. All cross-report match keys then share one true-UTC instant/day.

Examples (zone `Europe/Lisbon`):

- Summer midnight. CG `15/06/2025 00:30` (WEST, UTC+1). Before: stamped `2025-06-15 00:30 UTC`, so `disposal_date = "2025-06-15"`. After: local 00:30 = UTC 23:30 the previous day, so `disposal_date = "2025-06-14"` and `disposal_timestamp = "2025-06-14 23:30"`. The TH twin for the same instant is `2025-06-14 23:30:00 UTC`, calendar day `2025-06-14`. The key now agrees; before it disagreed by a day.
- Winter midday (existing fixtures). CG `13/01/2025 13:01` (WET, UTC+0). Before and after: `2025-01-13 13:01 UTC`, `disposal_date = "2025-01-13"`. Unchanged, so every January fixture in the suite stays GREEN.
- TH explicit UTC. `2025-06-14 23:30:00 UTC` is left as UTC regardless of the zone parameter, because the format itself declares UTC.

The fix is localized: one parser change (add a `zone` keyword), one config field, and threading the resolved zone to the two naive-date parse sites (CG and OGR; income for consistency). TH-only parse sites (FIFO, derivatives dedup, token origin) need no change because TH always declares UTC and is already correct.

Design decision (confirmed with the user): the zone comes from an explicit `IANA_TIMEZONE` key in `config.ini` `[TAX JURISDICTION]`, defaulting to `Europe/Lisbon` when `TAX_COUNTRY=PT` and the key is absent. The string is resolved to a `ZoneInfo` value object exactly once, at config-load time (validated, fail-fast), and stored as `TaxJurisdictionConfig.timezone`, so the pipeline reads a ready value object and never reconstructs it. Non-PT countries must set the key explicitly; when it is absent and the country is not PT, `timezone` is `None` and naive dates keep the current UTC-stamp behavior (documented below as a Monitor).

## Evaluation Criteria

**Quality dimensions:**
- correctness: a naive summer-midnight CG disposal localizes to the previous UTC day and matches its TH twin; winter dates are byte-for-byte unchanged; TH explicit-UTC dates are unchanged.
- regression-safety: all existing winter-date fixtures stay GREEN with no fixture edits; `parse_koinly_datetime` with no `zone` argument preserves current behavior.
- robustness: an invalid `IANA_TIMEZONE` value fails fast at startup with `ConfigurationError`; DST transitions (spring-forward gap, fall-back ambiguity) produce a documented, deterministic result rather than raising.
- maintainability: `zoneinfo` owns DST math; no hardcoded transition-day table; the `parsed.tzinfo` trap (strptime never sets `tzinfo`, so the TH `UTC` suffix is a literal, not a zone) is handled by detecting whether the matched format declares UTC.

**Release gates:**
- `uv run pytest -q` green (full suite).
- `uv run ruff check src/ tests/` clean.
- A discriminating integration test proves the DP-014 payment match succeeds for a summer-midnight disposal whose UTC day differs from its local day, and fails on the unfixed code.

## Review Scope

**Explicit must-fix** - findings on these paths are always in scope (review and fix if valid):

**Production code:**
- `src/tax_reporting/infrastructure/koinly_parser.py` (parser `zone` param; OGR parse threading)
- `src/tax_reporting/domain/jurisdiction.py` (`iana_timezone` field; zone resolver)
- `src/tax_reporting/infrastructure/config.py` (load `IANA_TIMEZONE`; PT default; startup validation)
- `src/tax_reporting/application/crypto_reporting.py` (`CapitalGainsParsingContext.zone`; CG and income parse threading; OGR loader call)
- `config.ini` and `tests/config.ini` (optional `IANA_TIMEZONE` key)

**Tests:**
- `tests/unit/infrastructure/test_koinly_parser.py`
- `tests/unit/infrastructure/test_config.py`
- `tests/unit/application/test_crypto_reporting.py`

**Plan-related extension** - implementation and review may change files not listed above. Treat a finding as in scope when it is causally related to this plan: it implements or completes a plan task, fixes a regression introduced by plan work, closes wiring or docs implied by an explicit must-fix change, or contradicts a contract the plan changed. If the link to the plan is weak or speculative, drop as out of scope with a one-line reason.

**Out of scope - reject unless plan-related:**
- `src/tax_reporting/application/crypto/payment_proceeds.py` `_calendar_day` - no change needed; it is a string slice over inputs that are already true-UTC after this fix.
- `src/tax_reporting/application/crypto_fifo/`, `src/tax_reporting/application/crypto/derivatives_dedup.py`, `src/tax_reporting/application/token_origin.py` - TH-only parse paths; TH always declares UTC and is already correct.
- OGR 1:1 multi-lot override guard - separate latent risk tracked in the RFC; not addressed here.

## Adjacent branch-review finding (#3)

Branch-review finding #3
(`test_payment_proceeds_rezero_index_based_not_key_based` in
`tests/unit/application/test_crypto_reporting.py`, ~line 10589) is folded into
this plan. Its recommended hardening - isolate the legitimate OGR-overridden row
from aggregation so the `load_koinly_crypto_report` re-zero is proven index-based,
not key-based - lives in `test_crypto_reporting.py`, the same file this plan's
Task 3 capstone and the re-zero region thread `zone=` through. Handle it while
implementing those tasks: it is a test-quality fix independent of the shelved
TH-anchored state machine (that RFC lists #3 among findings that "can proceed"),
so it need not wait for the re-architecture.

## Design Invariants (CR Guard)

Prior decisions and contracts this plan must not compromise during review:

- **TH explicit-UTC dates are never relocalized.** A date whose matched format declares UTC stays UTC regardless of the `zone` argument. The detection is on the matched format string (it literally contains `UTC`), because `datetime.strptime` never sets `tzinfo` (the TH ` UTC` suffix is a literal in the format, not a `%z` directive). Relying on `parsed.tzinfo` to tell TH-UTC from naive-CG is wrong and is the trap this invariant names.
- **Match-key shapes are unchanged.** Cross-report keys keep using `YYYY-MM-DD` calendar-day strings and `YYYY-MM-DD HH:MM` timestamps. Only the underlying instant's zone changes; consumers (`_calendar_day` slice, derivatives dedup exact-match) need no edits.
- **`parse_koinly_datetime(value)` without `zone` preserves current behavior.** The `zone` parameter defaults to `None`; `None` means stamp naive dates as UTC exactly as today. Existing callers and tests that do not pass `zone` are unaffected until they are explicitly threaded.
- **`zoneinfo` owns DST; no transition-day table.** Per the RFC weakness-3 resolution and the user's policy, the tz database supplies spring/autumn transitions historically. Do not add a manual lookup or per-day check.
- **`config.ini` holds user-preference/runtime settings only; law-driven flags stay in decision-points TOML.** `IANA_TIMEZONE` is a runtime jurisdiction setting, not a law-driven boolean, so it lives in `config.ini` `[TAX JURISDICTION]`. The single `Europe/Lisbon` convenience default for `TAX_COUNTRY=PT` is an explicit, user-approved constant (approved during planning), not a broad country-to-zone map.
- **One zone resolution, stored as a value object.** The `IANA_TIMEZONE` string is resolved to a `ZoneInfo` exactly once, at config-load (infrastructure), validated fail-fast, and stored on `TaxJurisdictionConfig.timezone`. There is no `resolve_jurisdiction_zone` helper that re-constructs `ZoneInfo` at call sites; the parser receives the value object directly. This avoids a second, unguarded construction path.
- **The `timezone` field does not disturb decision-flag auto-registration.** `_KNOWN_DECISION_FLAGS` (config.py) is derived from `bool`-typed fields only; `timezone: ZoneInfo | None` is automatically excluded, so the flag loader needs no change.
- **Winter-date fixtures stay GREEN unchanged.** All January CG/OGR fixtures produce the same strings before and after (WET equals UTC); any test that requires editing to stay green signals a regression.

## Validation Commands

```bash
# Parser and config unit tests (the foundation).
uv run pytest tests/unit/infrastructure/test_koinly_parser.py tests/unit/infrastructure/test_config.py -q

# CG / income / OGR threading and the DP-014 integration test.
uv run pytest tests/unit/application/test_crypto_reporting.py tests/unit/application/test_payment_proceeds.py -q

# Full suite and lint.
uv run pytest -q
uv run ruff check src/ tests/

# Guard: every CG/OGR/income production parse site forwards zone= (grep the threading, not just the call).
grep -n "zone=" src/tax_reporting/application/crypto_reporting.py src/tax_reporting/infrastructure/koinly_parser.py
# Guard: the format-declares-UTC detection exists and the explicit-UTC branch returns UTC unchanged.
grep -n "UTC" src/tax_reporting/infrastructure/koinly_parser.py
```

## Tasks

### Task 1: Make `parse_koinly_datetime` zone-aware and format-aware

Files:
- `src/tax_reporting/infrastructure/koinly_parser.py`
- `tests/unit/infrastructure/test_koinly_parser.py`

- [x] `parse_koinly_datetime#summer_naive_local_to_utc` - given `15/06/2025 00:30` with `zone=ZoneInfo("Europe/Lisbon")`, expects `datetime(2025, 6, 14, 23, 30, tzinfo=UTC)` (local WEST midnight maps to the previous UTC day). Run -> expect RED (today it returns `2025-06-15 00:30 UTC`).
- [x] `parse_koinly_datetime#winter_naive_local_unchanged` - given `13/01/2025 13:01` with `zone=ZoneInfo("Europe/Lisbon")`, expects `datetime(2025, 1, 13, 13, 1, tzinfo=UTC)` (WET equals UTC). Run -> expect GREEN now (characterization).
- [x] `parse_koinly_datetime#explicit_utc_unaffected_by_zone` - given `2025-06-14 23:30:00 UTC` with `zone=ZoneInfo("Europe/Lisbon")`, expects `datetime(2025, 6, 14, 23, 30, tzinfo=UTC)` (declared UTC, zone ignored). Run -> expect GREEN now.
- [x] `parse_koinly_datetime#zone_none_backward_compatible` - given `15/06/2025 00:30` with no `zone`, expects `datetime(2025, 6, 15, 0, 30, tzinfo=UTC)` (current behavior preserved). Run -> expect GREEN now.
- [x] `parse_koinly_datetime#empty_string_epoch_sentinel` - given `""`, expects `datetime(1970, 1, 1, tzinfo=UTC)` unchanged by `zone`. Run -> expect GREEN now.
- [x] `parse_koinly_datetime#spring_forward_gap_fold_zero` - given `30/03/2025 02:30` with `zone=ZoneInfo("Europe/Lisbon")` (the 02:00->03:00 WEST gap, fold=0 default), expects a deterministic UTC result documented in the assertion. Run -> characterization of the chosen fold behavior.
- [x] `parse_koinly_datetime#fall_back_ambiguity_fold_zero` - given `26/10/2025 01:30` with `zone=ZoneInfo("Europe/Lisbon")` (ambiguous repeated hour, fold=0 default), expects the first-occurrence UTC result. Run -> characterization.
- [x] Run -> expect RED on the summer case.
- [x] Implement: add keyword-only `zone: ZoneInfo | None = None` to `parse_koinly_datetime`. After a successful `strptime`, branch on whether the matched `date_format` declares UTC (helper `_format_declares_utc(fmt)` returns `"UTC" in fmt`, true only for the `%Y-%m-%d %H:%M:%S UTC` format): if it declares UTC, return `parsed.replace(tzinfo=UTC)`; else if `zone` is not None, return `parsed.replace(tzinfo=zone).astimezone(UTC)`; else return `parsed.replace(tzinfo=UTC)` (backward compat). The empty-string epoch branch is unchanged.
- [x] Run -> expect GREEN.
- [x] Commit: `fix(crypto): localize naive Koinly dates to jurisdiction zone in parser`

### Task 2: Add `timezone` to the jurisdiction config (value object, PT default, fail-fast validation)

Files:
- `src/tax_reporting/domain/jurisdiction.py`
- `src/tax_reporting/infrastructure/config.py`
- `config.ini`
- `tests/config.ini`
- `tests/unit/infrastructure/test_config.py`

- [x] `load_tax_jurisdiction_config#pt_defaults_to_lisbon` - given `[TAX JURISDICTION]` with `TAX_COUNTRY=PT` and no `IANA_TIMEZONE` key, expects `config.timezone == ZoneInfo("Europe/Lisbon")`. Run -> expect RED.
- [x] `load_tax_jurisdiction_config#explicit_zone_overrides_default` - given `IANA_TIMEZONE=Atlantic/Azores` with `TAX_COUNTRY=PT`, expects `config.timezone == ZoneInfo("Atlantic/Azores")` (proves the non-default path; Azores is UTC-1/+0, distinct from Lisbon). Run -> expect RED.
- [x] `load_tax_jurisdiction_config#invalid_zone_raises` - given `IANA_TIMEZONE=Foo/Bar` with `TAX_COUNTRY=PT, FISCAL_YEAR=2025` (so the decision-points TOML loads and execution reaches the zone-validation branch rather than raising `MissingDecisionPointsError` first), expects the config loader to raise `ValueError` naming the bad zone, mirroring the existing invalid-`[TAX JURISDICTION]` test pattern in `test_config.py` (config.py raises `ValueError` for bad `TAX_COUNTRY`/`FISCAL_YEAR` at lines 156-188; `main()` converts it to `ConfigurationError`, satisfying the documented startup contract). Run -> expect RED.
- [x] `load_tax_jurisdiction_config#non_pt_without_key_is_none` - given `TAX_COUNTRY=US` and no `IANA_TIMEZONE` key, expects `config.timezone is None` (documented backward-compat for non-PT). Run -> expect RED.
- [x] `_parse_jurisdiction_section#surfaces_iana_timezone` - given a `[TAX JURISDICTION]` section with `IANA_TIMEZONE=Europe/Lisbon`, expects the section parser to return `iana_timezone="Europe/Lisbon"` on a NamedTuple (not the legacy positional 4-tuple); given no key with `TAX_COUNTRY=PT`, expects `iana_timezone="Europe/Lisbon"` (PT default applied inside the section parser where `country` is already known). Run -> expect RED.
- [x] Run -> expect RED.
- [x] Implement:
  - Append `timezone: ZoneInfo | None = None` at the END of `TaxJurisdictionConfig` (after `infer_payment_proceeds`). A defaulted field cannot precede the existing no-default fields (`country`, `fiscal_year`, `exclude_loan_repayment_gains`, `zero_basis_review_threshold`); inserting earlier raises `TypeError: non-default argument follows default argument`. Add `if TYPE_CHECKING: from zoneinfo import ZoneInfo` to `jurisdiction.py` (its `from __future__ import annotations` stringifies annotations, so no runtime import is needed).
  - Convert `_parse_jurisdiction_section`'s positional 4-tuple return to a `NamedTuple` (e.g. `JurisdictionSectionFields`; `NamedTuple` is already imported in config.py) so adding the timezone field does not break positional unpacking. Parse `IANA_TIMEZONE` here alongside the other `[TAX JURISDICTION]` keys, applying the single default constant `_DEFAULT_PT_TIMEZONE = "Europe/Lisbon"` when the key is absent and `country == "PT"`, else `None`. Keep all `[TAX JURISDICTION]` key parsing in this one function (cohesion; do not split the section's keys across two functions).
  - In `_load_tax_jurisdiction_config`, resolve the section's `iana_timezone` string to a validated `ZoneInfo | None`: when non-None, `ZoneInfo(value)` inside try/except `ZoneInfoNotFoundError` and broader `Exception` -> raise `ValueError(f"Invalid IANA_TIMEZONE {value!r} ...") from e` (matching the surrounding `[TAX JURISDICTION]` `ValueError` pattern; `main()` converts to `ConfigurationError`). Pass `timezone=<resolved>` EXPLICITLY to the `TaxJurisdictionConfig(...)` constructor at `config.py:248` (it cannot ride `**flag_kwargs`, which carries only the bool decision flags). Cover both the section-present and section-absent loader paths (section-absent already defaults `country` to `"PT"`). Add `from zoneinfo import ZoneInfo, ZoneInfoNotFoundError` to config.py (it imports neither today).
  - Add the optional `IANA_TIMEZONE` line to `config.ini` (commented, `; IANA_TIMEZONE = Europe/Lisbon`); leave `tests/config.ini` on the PT default unless a test needs otherwise.
- [x] Run -> expect GREEN.
- [x] Commit: `feat(crypto): add jurisdiction timezone config with PT default and fail-fast validation`

### Task 3: Thread the zone to CG and Income parsing (makes disposal_date / disposal_timestamp true-UTC)

Files:
- `src/tax_reporting/application/crypto_reporting.py`
- `tests/unit/application/test_crypto_reporting.py`

- [x] `_parse_capital_gains_file#summer_midnight_disposal_true_utc_day` - given a CG CSV row with `Date Sold = 15/06/2025 00:30` and a PT jurisdiction (zone `Europe/Lisbon`), expects the resulting `CryptoCapitalGainEntry.disposal_date == "2025-06-14"` and `disposal_timestamp == "2025-06-14 23:30"`. Run -> expect RED (today it yields `2025-06-15`).
- [x] `_parse_capital_gains_file#winter_disposal_unchanged` - given `Date Sold = 13/01/2025 13:01`, expects `disposal_date == "2025-01-13"` and `disposal_timestamp == "2025-01-13 13:01"`. Run -> expect GREEN now (characterization; protects existing fixtures).
- [x] `_parse_income_file#summer_date_true_utc_day` - given an income row with `Date = 15/06/2025 00:30` parsed with `zone=Europe/Lisbon`, expects the entry date `2025-06-14`. Run -> expect RED.
- [x] `load_koinly_crypto_report#payment_match_survives_summer_midnight_drift` (integration, the capstone) - given a payment disposal written via `_write_payment_fixture` with a CG row `Date Sold = 15/06/2025 00:30` (WEST) and its TH payment twin `_th_payment_row(date_utc="2025-06-14 23:30:00 UTC")` (the true UTC instant), with `infer_payment_proceeds=True`, expects the DP-014 correction to fire and the corrected entry's `disposal_date == "2025-06-14"`. Run -> expect RED (today CG day `2025-06-15` vs TH day `2025-06-14` do not match, so the correction is skipped).
- [x] Capstone MUST use the CSV-writing helpers `_write_payment_fixture` + `_cg_row(date_sold=...)` + `_th_payment_row(date_utc=...)` (defined in `test_crypto_reporting.py` at lines 10204/10233/10266), so the pipeline reads the rows through `parse_koinly_datetime` and `disposal_date` is parser-produced. Do NOT use the `_make_cg_entry` object-builder from `test_payment_proceeds.py` (it hardcodes `disposal_date` and would not exercise the timezone fix, making the test non-discriminating).
- [x] Run -> expect RED.
- [x] Implement: append `zone: ZoneInfo | None = None` to `CapitalGainsParsingContext` (`@dataclass(frozen=True)` at `crypto_reporting.py:452`). It MUST have a default: the class already has defaulted fields (`known_assets`, `loan_affected_assets`, `zero_basis_review_min_proceeds`), and a non-default field appended after them raises `TypeError: non-default argument follows default argument` at import. At the context build site (`crypto_reporting.py:184`, where `jurisdiction` is in scope) set `zone=jurisdiction.timezone if jurisdiction else None`. In `_parse_capital_gains_file` pass `zone=context.zone` to the `parse_koinly_datetime` calls at the `Date Sold` (513) and `Date Acquired` (516) sites. Add a `zone: ZoneInfo | None = None` keyword to `_parse_income_file`, pass `zone=zone` at its `parse_koinly_datetime` call (736), and pass `zone=jurisdiction.timezone if jurisdiction else None` from the call site at line 232.
- [x] Run -> expect GREEN (including the capstone integration test).
- [x] Commit: `fix(crypto): localize CG and income disposal dates to jurisdiction zone`

### Task 4: Thread the zone to OGR parsing (makes OGR index keys true-UTC)

Files:
- `src/tax_reporting/infrastructure/koinly_parser.py`
- `src/tax_reporting/application/crypto_reporting.py`
- `tests/unit/infrastructure/test_koinly_parser.py`

- [x] `_parse_other_gains_row#summer_date_true_utc_day` - given an OGR row `15/06/2025 00:30,USDT,143,75,"140,18",Profit,ByBit` parsed with `zone=ZoneInfo("Europe/Lisbon")`, expects `ParsedOgrRow.date == "2025-06-14"`. Run -> expect RED (today it yields `2025-06-15`).
- [x] `_parse_other_gains_row#winter_date_unchanged` - given `13/01/2025 13:01,...` with the same zone, expects `ParsedOgrRow.date == "2025-01-13"`. Run -> expect GREEN now (characterization).
- [x] `_find_and_parse_other_gains_file#zone_forwarded_end_to_end` (boundary/wiring) - given a temp dir containing an `*other_gains_report*.csv` with a summer-midnight row, calling `_find_and_parse_other_gains_file(dir, zone=ZoneInfo("Europe/Lisbon"))` expects the parsed `ParsedOgrRow.date == "2025-06-14"`. This proves the loader forwards `zone` to the row parser, not just that the leaf helper accepts it. Run -> expect RED until the loader forwards `zone`.
- [x] Run -> expect RED.
- [x] Implement: add keyword-only `zone: ZoneInfo | None = None` to `_parse_other_gains_row` and pass it to its `parse_koinly_datetime` call (`koinly_parser.py:354`); add the same keyword to `_find_and_parse_other_gains_file` and forward it to `_parse_other_gains_row` (`koinly_parser.py:425`); at the production call site `crypto_reporting.py:276` pass `zone=jurisdiction.timezone if jurisdiction else None`.
- [x] Run -> expect GREEN.
- [x] Commit: `fix(crypto): localize Other Gains Report dates to jurisdiction zone`

### Task 5: Documentation cross-references

Files:
- `README.md`
- `docs/maintenance/crypto_implementation_guidelines.md`
- `docs/maintenance/koinly_guidelines.md`
- `docs/history/feature-notes/2026-06-20-th-anchored-transaction-state-machine.md`
- `docs/maintenance/project-guidelines.md`

- [x] `README.md` - add `IANA_TIMEZONE` (optional; defaults to `Europe/Lisbon` for PT) to the Configuration section's `[TAX JURISDICTION]` list, noting it drives Koinly naive-date localization.
- [x] `AGENTS.md` (canonical project instructions; `CLAUDE.md` is its symlink) line ~161 - extend the `[TAX JURISDICTION]` key enumeration (`TAX_COUNTRY`, `FISCAL_YEAR`, `ZERO_BASIS_REVIEW_THRESHOLD`, `ZERO_BASIS_REVIEW_MIN_PROCEEDS`) to include `IANA_TIMEZONE` (optional; defaults to Europe/Lisbon for PT), keeping the canonical instruction file in sync with the new key.
- [x] `docs/architecture/api-contracts.md` line ~21 - extend the same `[TAX JURISDICTION]` key enumeration to include `IANA_TIMEZONE`, keeping the Layer 2 contract doc in sync with AGENTS.md.
- [x] `docs/maintenance/crypto_implementation_guidelines.md` - in the "Payment Proceeds Correction (DP-014)" section, replace the old "day-key timezone rationale" note with the corrected behavior: naive CG/OGR/Income dates are localized to `iana_timezone` and converted to UTC so CG and TH calendar-day keys agree; TH explicit-UTC dates are unchanged.
- [x] `docs/maintenance/koinly_guidelines.md` Section 5 - update any wording that implies naive dates are UTC; state CG/OGR/Income dates are local (WET/WEST for PT) and localized at ingestion.
- [x] `docs/history/feature-notes/2026-06-20-th-anchored-transaction-state-machine.md` weakness #3 - mark the timezone issue as addressed by this plan (reference the plan path); leave the multi-lot OGR item as still-open.
- [x] `docs/maintenance/project-guidelines.md` - add a numbered rule: Koinly naive dates are jurisdiction-local; localize via `zoneinfo` and convert to UTC at ingestion; never assume naive equals UTC. Cite `development_lessons.md` if a lesson is added.
- [x] Commit: `docs(crypto): document naive-date localization and IANA_TIMEZONE`

### Task 6: Final validation

Files: (none; verification only)

- [x] Run `uv run pytest -q` -> expect full green.
- [x] Run `uv run ruff check src/ tests/` -> expect clean.
- [x] Run the grep guards in `## Validation Commands` -> confirm every CG/OGR/income `parse_koinly_datetime` call passes `zone=`, and the format-declares-UTC branch is present.
- [x] Run `~/.ai-playbook/scripts/check-no-em-dash.sh` over changed docs (per global rule) -> expect clean.

## Monitor

- **Non-PT country without `IANA_TIMEZONE`.** When `country != "PT"` and the key is absent, `timezone` is `None` and naive dates keep the UTC-stamp behavior. That is backward-compatible but technically violates the "naive is local" policy for a non-PT run. Owner: a follow-up to emit a startup WARNING when crypto data is present and the zone is unresolved, or to require the key for any country that processes crypto. Not blocking this plan because the only live jurisdiction is PT.
  - **RESOLVED (2026-06-20/21, STRICT `ConfigurationError` guard):** adopted the stronger of the two options, then made it stricter still. The crypto-loading boundary `_load_crypto_tax_report` in `main.py` raises `ConfigurationError` whenever crypto data is present and the jurisdiction timezone cannot be resolved - covering BOTH a configured jurisdiction with no `IANA_TIMEZONE` (any non-PT country) AND the no-config path (`jurisdiction is None`, e.g. `config.ini` absent). `_main` propagates it unwrapped (it is neither degraded to "continue without crypto" nor wrapped into a `ReportGenerationError`). The loader `load_koinly_crypto_report` stays a pure parser; enforcement lives at the application boundary so the loader remains unit-testable in isolation. This goes beyond the originally-proposed WARNING to a hard fail-fast, per the policy that the program must never allow incorrect behavior by default when required data is missing. See `development_lessons.md` #135 (the propagation fix) and `docs/maintenance/project-guidelines.md` rule #6.
- **OGR 1:1 multi-lot override.** Independent latent risk (RFC weakness #2); the OGR override still assumes one OGR event per `(date, asset, wallet)` key. Today 0 CG keys match any OGR row, so it is dormant. Owner: the TH-anchored state-machine RFC; tracked there. This plan does not touch it.
