# Plan: Simplification Sweep: duplicate helpers, dead validators, sum-pass consolidation

Source: `docs/tmp/code-review/2026-07-15-whole-repo-simplify.md` (solo simplification reviewer pass over `src/tax_reporting/`)

Plan review: `docs/history/reviews/2026-07-15-plan-review-simplify-sweep-r2.md` (latest, ready=yes, Blocker=0 Medium=0; 4 Lows noted in artifact, Lr2-1 folded into Design Invariant #3) · `docs/history/reviews/2026-07-15-plan-review-simplify-sweep-r1.md` (r1 on revised plan, 5 Mediums folded) · `docs/history/reviews/2026-07-15-plan-review-simplify-sweep-r1-superseded.md` (r1 on pre-revision plan, drove Cluster 1 + Cluster 4-lifecycle removal)

## Scope note: findings dropped after r1 verification

The original simplification pass reported 10 Low findings. The r1 plan review verified that 4 of them rest on a broken grep that did not match multi-line `from … import (\n Name,\n)` blocks:

- **Original findings #1 and #2 (Cluster 1: re-export trim):** Every entity re-export has 1–6 test consumers (e.g., `CapitalGainPeriodStats`: 6 files; `RewardTaxClassification`: 6 files; `LoanActivityEntry`/`CryptoCompletePdfSummary`/`AggregatedRewardIncomeEntry`: 1 file each). The four "internal helpers" (`_load_popular_crypto_tokens`, `_build_ogr_index`, `_is_temporally_valid`, `_parse_transaction_date`) are also imported by `tests/unit/application/test_crypto_reporting.py:27,31,32,35`. The `crypto_reporting.py` `# noqa: F401` markers exist precisely because the module is a deliberate test-facing facade. The `crypto/__init__.py` package re-exports have zero submodule-path consumers but the file's own docstring declares the facade ("Domain entities are re-exported from here for convenience"). **Both findings invalid; dropped.**
- **Original finding #9 (Cluster 4: `_workbook_lifecycle` collapse):** The simplification reviewer claimed the `close_on_success`/`close_on_failure` pair was redundant. Verification against `workbook_builder.py:61-86` shows the asymmetry is intentional: `close_on_success` (line 61-70) does NOT wrap `workbook.close()`: close errors propagate to the caller on the success path; `close_on_failure` (line 72-86) wraps with try/except so a close error does not mask the original exception. The proposed single-`close()` form would silently swallow success-path close errors: a behavior change, not a refactor. **Finding invalid; dropped.**

This revision therefore sweeps **5 valid findings** (original #3, #4, #5, #6/#7/#8, #10) clustered into 3 groups, ~80 lines of cleanup.

## Gist & Examples

Three independent refactor clusters, ordered by ascending risk.

**Cluster A: Helper dedup (was Cluster 2).** Three small deletions in the crypto application layer:
- `_attributed_wallet = row.sending_wallet if row.sending_wallet else row.receiving_wallet` immediately followed by `del _attributed_wallet` at `transaction_factory.py:88-89`. The docstring admits "documented for the reader; not used downstream." The attribution rule it documents is already enforced by `_row_platform` in `wallet_kind.py`, so the inline cross-check adds nothing. Drop both lines plus the now-stale docstring sentences at 82-87.
- `_find_report_path` at `crypto/parsing.py:41-` is a function-body-identical duplicate of `_find_report_path` at `infrastructure/koinly_parser.py:419` (bodies match; docstrings differ in length and wording). Both modules are already imported by `crypto_reporting.py`. Keep the infrastructure copy (also called by `_find_and_find_other_gains_file`); delete the parsing.py copy.
- `_find_report_file` at `crypto/parsing.py:26-38` is a one-line wrapper that forwards to `_find_report_path(koinly_dir, marker, ".csv")`. With the duplicate removed, the wrapper has no reason to exist. Re-point five call sites in `crypto_reporting.py` (lines 205, 206, 207, 554, 559) to call `_find_report_path(koinly_dir, "<marker>", ".csv")` directly; the existing `.pdf` call site at line 611 already uses `_find_report_path` and just needs its import source changed.

**Cluster B: Validator infrastructure removal (was Cluster 3).** Six validators in `infrastructure/validation.py` have zero production callers (`validate_csv_file`, `sanitize_file_path`, `validate_company_ticker`, `validate_currency_code`, `validate_quantity`, `validate_price`). The `SecurityConfig` dataclass they consume exists only to feed them; `Config.security` is loaded by `_load_security_config` and read only by tests (`rg '\.security\b' src/` → zero hits). Remove the dead validators, `SecurityConfig`, `DEFAULT_SECURITY_CONFIG`, the `_load_security_config` loader, the `Config.security` field, and the `[SECURITY]` section in both `config.ini` and `tests/config.ini`. Update CLAUDE.md's Configuration section (enumerates `[COMMON]`, `[EXCHANGE RATES]`, `[SECURITY]`, `[TAX JURISDICTION]` → drop the `[SECURITY]` bullet).

**Cluster C: Counter-ize the holding-period tally (was Cluster 4 sum-pass only).** Four parallel `sum(1 for row in capital_entries if row.holding_period.lower().<op>)` passes at `crypto_reporting.py:564-567` each iterate the full list and re-lower every value. One `Counter` pass removes three iterations and three redundant `.lower()` calls:

```python
period_counts = Counter(row.holding_period.lower() for row in capital_entries)
short_term_rows = sum(c for k, c in period_counts.items() if k.startswith("short"))
long_term_rows  = sum(c for k, c in period_counts.items() if k.startswith("long"))
mixed_rows      = period_counts.get("mixed", 0)
unknown_rows    = period_counts.get("unknown", 0)
```

The `startswith` vs `==` split mirrors the original exactly. **The `startswith` semantics are load-bearing**: the actual values are space-separated (`"Short term"`, `"Long term"`): see Design Invariant #3: so a future cleanup that "tightens" `startswith("short")` to `== "short"` would silently break matching.

**Edge cases that motivated design decisions:**

- **Cluster A import contract.** `crypto_reporting.py:80-86` imports `_find_report_file` and `_find_report_path` from `crypto.parsing`. After dedup, `_find_report_path` is imported from `infrastructure.koinly_parser`. The named-import edit and the call-site re-points must land in the same commit to avoid `ImportError` mid-cluster.
- **Cluster A test fallout.** `tests/unit/application/test_crypto_parsing.py:10-16` imports `_find_report_file` and `_find_report_path` from `crypto.parsing`, and the file has dedicated test classes for both. The tests for `_find_report_path` (CSV, PDF, missing) get ported to `tests/unit/infrastructure/test_koinly_parser.py` (the canonical home, currently has zero coverage of `_find_report_path`); the `_find_report_file` tests are deleted (the wrapper goes away); the import block at lines 10-16 drops both names. Other tests in the file (e.g., `_extract_tax_year`, `_parse_complete_tax_report_pdf`) stay.
- **Cluster B test fallout.** `tests/unit/infrastructure/test_config.py` has 4 places that reference `Config.security`: `test_config_creation:41` (`assert config.security is not None`), `test_config_with_custom_security:43-52`, `TestLoadSecurityConfig` class at line 129 (4 methods), and `test_complete_config_construction:217-218` (two assertions on `cfg.security.max_file_size_mb` / `allowed_extensions`). All four must be edited in the same task. `tests/unit/application/persisting/test_workbook_builder.py:268,283` passes `security=SecurityConfig()` to `Config(...)`: the helper drops that kwarg and the import.
- **Cluster B doc fallout.** CLAUDE.md "Configuration" section enumerates `[COMMON]`, `[EXCHANGE RATES]`, `[SECURITY]`, `[TAX JURISDICTION]`. README.md may also reference SECURITY. Both must be checked and updated.
- **Cluster C semantics.** Today's four-pass form lower-cases `row.holding_period` four times per row; the Counter form lower-cases once. For values `["Short-term", "Long-term", "Mixed", "Unknown"]` (verified via `rg 'holding_period\s*=' src/`) both forms produce identical counts. The `startswith` semantics on `short`/`long` preserve any future variant matching (none exist today, but the semantics are explicit in the original code).

## Evaluation Criteria

**Quality dimensions:**

- **Correctness:** `uv run pytest` is green before and after each cluster commit (no test count regression except deliberate deletions, no new failures). The full suite (1713 baseline tests) must remain green at branch HEAD.
- **Maintainability:** `rg '<deleted-symbol>'` over `src/` and `tests/` returns zero hits after each cluster commit (no orphan references).
- **Hygiene:** `uv run ruff check` clean on every touched file (production AND tests); em-dash clean per CLAUDE.md (`~/.ai-playbook/scripts/check-no-em-dash.sh`).
- **Scope discipline:** each cluster lands as exactly one commit; no cross-cluster bundling.
- **Behavior preservation:** no behavior change in any cluster (Cluster C is a same-output refactor; Clusters A and B are pure deletion of dead code with no live caller).

**Release gates:**

- Full `uv run pytest` green at branch HEAD.
- `uv run ruff check` clean on all touched files.
- Manual smoke check: `uv run python ./src/tax_reporting/main.py --help` exits 0.

## Review Scope

**Explicit must-fix**; findings on these paths are always in scope (review and fix if valid):

**Production code:**
- `src/tax_reporting/application/crypto/parsing.py` (delete `_find_report_file`, `_find_report_path`)
- `src/tax_reporting/application/crypto/transaction_factory.py` (delete `_attributed_wallet` lines + stale docstring sentences)
- `src/tax_reporting/application/crypto_reporting.py` (`_find_report_*` import + call-site re-points; Counter-ize sum-pass at 564-567)
- `src/tax_reporting/infrastructure/koinly_parser.py` (canonical home for `_find_report_path`; no body change expected)
- `src/tax_reporting/infrastructure/validation.py` (delete 6 dead validators, `SecurityConfig`, `DEFAULT_SECURITY_CONFIG`, dead `__post_init__`)
- `src/tax_reporting/infrastructure/config.py` (delete `_load_security_config`, `Config.security` field, `SecurityConfig`/`DEFAULT_SECURITY_CONFIG` import)
- `config.ini` (drop `[SECURITY]` section)
- `tests/config.ini` (drop `[SECURITY]` section)
- `CLAUDE.md` (Configuration section: drop `[SECURITY]` from enumeration)
- `README.md` (if it references `[SECURITY]`)

**Tests:**
- `tests/unit/application/test_crypto_parsing.py` (drop `_find_report_*` test classes; update import block at lines 10-16)
- `tests/unit/infrastructure/test_koinly_parser.py` (add ported `_find_report_path` tests)
- `tests/unit/infrastructure/test_config.py` (delete `test_config_with_custom_security`, `TestLoadSecurityConfig`; drop `assert config.security` lines at 41 and 217-218; drop `SecurityConfig` import)
- `tests/unit/application/persisting/test_workbook_builder.py` (drop `security=SecurityConfig()` from `_build_test_config`)

**Plan-related extension**; implementation and review may change files not listed above. Treat a finding as in scope when it is causally related to this plan: it implements or completes a plan task, fixes a regression introduced by plan work, closes wiring or docs implied by an explicit must-fix change, or contradicts a contract the plan changed.

**Out of scope; reject unless plan-related:**
- `src/tax_reporting/application/persisting/workbook_builder.py` `_workbook_lifecycle`: out of scope by this revision; the simplification finding was invalid (success-path close-error propagation is intentional, see Scope note).
- `src/tax_reporting/application/crypto_reporting.py` and `crypto/__init__.py` re-export trim: out of scope by this revision; the simplification finding was invalid (every re-export has consumers, see Scope note).
- `src/tax_reporting/application/crypto/aggregation.py:19-35`: TYPE_CHECKING/else import split flagged as marginal by the simplification reviewer; route to a future architecture pass if touched.
- The deferred Plan A (review-flag SOT and the three false-positive flag fixes): separate plan.
- Phase E Round 7 verification review: separate authorization.

## Design Invariants (CR Guard)

1. **`_find_report_path` import path.** After dedup, `crypto_reporting.py` imports `_find_report_path` from `infrastructure.koinly_parser`. The two call signatures are byte-identical so call-site semantics are preserved exactly. The deleted `parsing._find_report_file` wrapper always passed `.csv`; the five new call sites pass `.csv` explicitly. Invariant: the six report-file lookups in `crypto_reporting.py` (capital_gains_report, income_report, transaction_history, beginning_of_year_holdings_report, end_of_year_holdings_report, complete_tax_report.pdf) continue to resolve the same paths. Today's call counts: 5 `_find_report_file` calls (lines 205, 206, 207, 554, 559) + 1 `_find_report_path` call (line 611) = 6 lookups. Post-refactor: all 6 use `_find_report_path` from `koinly_parser`.
2. **`Config` schema shrink.** Dropping `Config.security` requires every constructor caller to omit the kwarg. Verified callers passing `security=` are `test_workbook_builder.py:283` (test helper) and `config.py:_load_security_config` (the loader itself, deleted in the same task). No production code reads `Config.security` (`rg '\.security\b' src/tax_reporting/` → zero hits). The `[SECURITY]` section in `config.ini`/`tests/config.ini` becomes unparseable noise after the loader is removed; removing the section is required so `load_configuration_from_file` does not silently ignore user input (Family G: silent drift). CLAUDE.md and README.md must update in lockstep to avoid documenting a section the parser no longer reads.
3. **Counter form equivalence.** `long`/`short` use `startswith`; `mixed`/`unknown` use exact equality. The actual `holding_period` value set produced in `src/` (verified via `rg 'holding_period' src/`) is **space-separated**: `{"Short term", "Long term", "Unknown"}`. Sources: `crypto_fifo/matching.py:131,290,331` produce `"Short term"` / `"Long term"`; `crypto_reporting.py:791` defaults to `"Unknown"`. `"Mixed"` appears only as a presentation-layer Excel display label at `crypto_gains_sheet.py:186` (`("Mixed", stats.mixed)`): it is NEVER assigned to `holding_period` in src/, so the `mixed_rows` tally is always 0 in both the four-pass and Counter forms (the Counter's `period_counts.get("mixed", 0)` returns 0). The `startswith("short")` / `startswith("long")` semantics are load-bearing: a future cleanup that "tightens" to `== "short"` / `== "long"` would break matching on `"Short term"` / `"Long term"`. Verified by hand on `["Long term", "Long term", "Unknown", "Short term", "Short term"]` → `(short=2, long=2, mixed=0, unknown=1)` in both forms.
4. **`sanitize_directory_path` signature.** If `sanitize_directory_path` (the surviving helper in `validation.py`) takes `config: SecurityConfig = DEFAULT_SECURITY_CONFIG` as a parameter, the parameter must be dropped in the same edit that removes `SecurityConfig`. Verified via `grep -n 'config' src/tax_reporting/infrastructure/validation.py` before writing Task 2; no caller passes `config=` to `sanitize_directory_path` (`rg 'sanitize_directory_path\(' src/ tests/`), so dropping the parameter is safe.

## Validation Commands

```bash
# Per-cluster verification (run after each cluster's commit)

# Cluster A: helper dedup
# parsing.py wrappers gone
rg '_find_report_file|_find_report_path' src/tax_reporting/application/crypto/parsing.py
# Expected: zero hits
# call sites re-pointed (6 total: 5 .csv + 1 .pdf)
rg '_find_report_path\(' src/tax_reporting/application/crypto_reporting.py
# Expected: 6 hits, all importing from koinly_parser
# _attributed_wallet gone
rg '_attributed_wallet' src/tax_reporting/application/crypto/transaction_factory.py
# Expected: zero hits
# test_crypto_parsing.py still collects (import block updated)
uv run pytest tests/unit/application/test_crypto_parsing.py --collect-only
# Expected: success
# ported tests live in test_koinly_parser.py
rg '_find_report_path' tests/unit/infrastructure/test_koinly_parser.py
# Expected: at least 4 hits (csv, pdf, missing, multiple_matches)

# Cluster B: validator infra removal
# dead validators gone (sanitize_directory_path + validate_output_directory stay)
rg 'validate_csv_file|validate_company_ticker|validate_currency_code|validate_quantity|validate_price|sanitize_file_path' src/tax_reporting/infrastructure/validation.py
# Expected: zero hits
# SecurityConfig gone everywhere (production AND tests in scope: catches orphan imports like _load_security_config in test_config.py)
rg 'SecurityConfig|DEFAULT_SECURITY_CONFIG|_load_security_config' src/ tests/
# Expected: zero hits
# [SECURITY] section gone from configs
rg '^\[SECURITY\]' config.ini tests/config.ini
# Expected: zero hits
# CLAUDE.md and README.md no longer reference [SECURITY]
rg '\[SECURITY\]' CLAUDE.md README.md docs/
# Expected: zero hits (verify before-and-after)
# test_config.py no longer references .security
rg '\.security\b|SecurityConfig' tests/unit/infrastructure/test_config.py
# Expected: zero hits
# load_configuration_from_file tolerates the trimmed config
uv run python -c "from tax_reporting.infrastructure.config import load_configuration_from_file; load_configuration_from_file('config.ini'); print('ok')"

# Cluster C: sum-pass Counter
# Counter imported
rg 'from collections import Counter' src/tax_reporting/application/crypto_reporting.py
# Expected: 1 hit
# four-pass form gone
rg 'sum\(1 for row in capital_entries if row\.holding_period' src/tax_reporting/application/crypto_reporting.py
# Expected: zero hits

# Cross-cluster: full test suite + lint + em-dash (production AND tests in scope)
uv run pytest
uv run ruff check \
  src/tax_reporting/application/crypto/parsing.py \
  src/tax_reporting/application/crypto/transaction_factory.py \
  src/tax_reporting/application/crypto_reporting.py \
  src/tax_reporting/infrastructure/validation.py \
  src/tax_reporting/infrastructure/config.py \
  src/tax_reporting/infrastructure/koinly_parser.py \
  tests/unit/application/test_crypto_parsing.py \
  tests/unit/infrastructure/test_koinly_parser.py \
  tests/unit/infrastructure/test_config.py \
  tests/unit/application/persisting/test_workbook_builder.py
~/.ai-playbook/scripts/check-no-em-dash.sh

# End-to-end smoke
uv run python ./src/tax_reporting/main.py --help
```

### Task 1: Cluster A: Helper dedup and dead-var removal

Files:
- `src/tax_reporting/application/crypto/parsing.py`
- `src/tax_reporting/application/crypto/transaction_factory.py`
- `src/tax_reporting/application/crypto_reporting.py`
- `src/tax_reporting/infrastructure/koinly_parser.py` (read-only: confirm canonical helper body)
- `tests/unit/application/test_crypto_parsing.py`
- `tests/unit/infrastructure/test_koinly_parser.py`

- [x] Confirm `koinly_parser._find_report_path` body matches `parsing._find_report_path` body byte-for-byte (modulo docstring): read both files, diff visually. If they diverge, STOP and amend this plan before proceeding
- [x] Verify `test_koinly_parser.py` has zero direct coverage of `_find_report_path`: `rg '_find_report_path' tests/unit/infrastructure/test_koinly_parser.py` → expect zero hits (the port is required)
- [x] Edit `crypto_reporting.py:80-86`: in the `from .crypto.parsing import (...)` block, remove `_find_report_file` and `_find_report_path` from the name list. Add `from ..infrastructure.koinly_parser import _find_report_path` at the appropriate alphabetical position. Verify the existing import style for `..infrastructure` names in this file
- [x] Edit `crypto_reporting.py` six call sites: line 205 → `_find_report_path(koinly_dir, "capital_gains_report", ".csv")`; line 206 → `_find_report_path(koinly_dir, "income_report", ".csv")`; line 207 → `_find_report_path(koinly_dir, "transaction_history", ".csv")`; line 554 → `_find_report_path(koinly_dir, "beginning_of_year_holdings_report", ".csv")`; line 559 → `_find_report_path(koinly_dir, "end_of_year_holdings_report", ".csv")`; line 611 unchanged body but import source now `koinly_parser`. Confirm each marker string by reading the current call site before editing
- [x] Edit `crypto/parsing.py`: delete `_find_report_file` (lines 26-38) and `_find_report_path` (lines 41 through end of function). Keep `_extract_tax_year`, `_parse_complete_tax_report_pdf`, `_register_skipped_zero_asset`, and any other helpers in the file
- [x] Edit `transaction_factory.py`: delete lines 88-89 (`_attributed_wallet = ...; del _attributed_wallet`) and the docstring sentences at lines 82-87 that reference the cross-check ("Wallet attribution sanity: ... reviewer cross-checks.")
- [x] Edit `tests/unit/application/test_crypto_parsing.py:10-16`: in the `from tax_reporting.application.crypto.parsing import (...)` block, remove `_find_report_file` and `_find_report_path`. Keep any other names imported from `parsing`
- [x] Edit `tests/unit/application/test_crypto_parsing.py`: delete the `TestFindReportFile` class and the `TestFindReportPath` class (the `_find_report_file` tests are obsolete; the `_find_report_path` tests get ported to `test_koinly_parser.py` in the next step)
- [x] Edit `tests/unit/infrastructure/test_koinly_parser.py`: add a new test class `TestFindReportPath` with **four** methods ported from `test_crypto_parsing.py:50-95`: `test_find_report_path_csv` (given a dir with `*income_report*.csv`, returns the path), `test_find_report_path_pdf` (given a dir with `*complete_tax_report*.pdf`, returns the path), `test_find_report_path_missing` (given a dir with no matching marker, returns `None`), and `test_find_report_path_multiple_matches` (given a dir with multiple matching files, returns the alphabetically-first via `sorted()`: this is the ONLY test pinning the helper's ordering behavior; do NOT drop it). Add `from tax_reporting.infrastructure.koinly_parser import _find_report_path` to the test file's imports
- [x] Run `uv run pytest tests/unit/application/test_crypto_parsing.py tests/unit/infrastructure/test_koinly_parser.py --collect-only` → expect success (no ImportError, both files collect)
- [x] Run `uv run python -c "from tax_reporting.application.crypto_reporting import load_koinly_crypto_report; print('ok')"` → expect success
- [x] Run `uv run ruff check src/tax_reporting/application/crypto/parsing.py src/tax_reporting/application/crypto/transaction_factory.py src/tax_reporting/application/crypto_reporting.py tests/unit/application/test_crypto_parsing.py tests/unit/infrastructure/test_koinly_parser.py` → expect clean
- [x] Run `uv run pytest` → expect full green (test count unchanged: 3 tests ported, 1-2 `_find_report_file` tests deleted, net change depends on original count)
- [x] Commit: `refactor(crypto): dedupe _find_report_path into koinly_parser; drop dead _attributed_wallet and stale wallet-attribution docstring`

### Task 2: Cluster B: Validator infrastructure removal

Files:
- `src/tax_reporting/infrastructure/validation.py`
- `src/tax_reporting/infrastructure/config.py`
- `config.ini`
- `tests/config.ini`
- `tests/unit/infrastructure/test_config.py`
- `tests/unit/application/persisting/test_workbook_builder.py`
- `CLAUDE.md`
- `README.md`

- [x] Re-verify zero production callers: `rg 'validate_csv_file|validate_company_ticker|validate_currency_code|validate_quantity|validate_price|sanitize_file_path' src/tax_reporting/` → expect hits only inside `validation.py` itself
- [x] Re-verify zero production readers of `Config.security`: `rg '\.security\b' src/tax_reporting/` → expect zero hits
- [x] Check `sanitize_directory_path` signature in `validation.py`: read the function definition. If it takes `config: SecurityConfig = DEFAULT_SECURITY_CONFIG`, the parameter must be dropped in this same edit. Verify no caller passes `config=` to `sanitize_directory_path`: `rg 'sanitize_directory_path\(' src/ tests/`
- [x] Edit `validation.py`: delete `SecurityConfig` dataclass (lines ~27-51), the dead `__post_init__` (37-), `DEFAULT_SECURITY_CONFIG = SecurityConfig()` (53), `sanitize_file_path` (56-), `validate_csv_file` (121-), `validate_company_ticker` (237-), `validate_currency_code` (263-), `validate_quantity` (288-), `validate_price` (316-). Keep `sanitize_directory_path` (170-) and `validate_output_directory`. Drop the `config: SecurityConfig = DEFAULT_SECURITY_CONFIG` parameter from `sanitize_directory_path` and `validate_output_directory` if present
- [x] Edit `config.py`: delete the import `from .validation import DEFAULT_SECURITY_CONFIG, SecurityConfig` (line 19); delete the `Config.security` field (line 92); delete `_load_security_config` function (line 446-) and any call to it inside `_load_config_from_file` or equivalent (search for the call site)
- [x] Edit `config.ini`: delete the `[SECURITY]` section (line 18 onward, until the next `[` section header). Preserve all other sections
- [x] Edit `tests/config.ini`: delete the `[SECURITY]` section (line 11 onward). Preserve all other sections
- [x] Edit `tests/unit/infrastructure/test_config.py`:
  - In the `from tax_reporting.infrastructure.config import (...)` block at lines 11-18, remove the `_load_security_config` name (line 15): the function is deleted in the same task; leaving this import causes a collection-time `ImportError`
  - Delete the `from ...validation import SecurityConfig` import
  - Delete `test_config_with_custom_security` (line 43)
  - In `test_config_creation` (line 30): delete the assertion `assert config.security is not None` at line 41
  - Delete the `TestLoadSecurityConfig` class (line 129+) and all its methods (`test_load_security_config_with_values`, `test_load_security_config_missing_section`, `test_load_security_config_with_invalid_values`, plus any helpers)
  - In `test_complete_config_construction` (line 200): delete the assertions at lines 217-218 (`assert cfg.security.max_file_size_mb > 0` and `assert ".csv" in cfg.security.allowed_extensions`)
- [x] Edit `tests/unit/application/persisting/test_workbook_builder.py` in `_build_test_config` (line 264): delete line 268 (`from tax_reporting.infrastructure.validation import SecurityConfig`) and line 283 (`security=SecurityConfig(),`)
- [x] Edit `CLAUDE.md` Configuration section: change "Four sections: `[COMMON]`, `[EXCHANGE RATES]`, `[SECURITY]`, `[TAX JURISDICTION]`" to "Three sections: `[COMMON]`, `[EXCHANGE RATES]`, `[TAX JURISDICTION]`" and delete any bullet describing `[SECURITY]` fields
- [x] Edit `README.md`: grep first with a wide pattern (`rg -i 'security validation|\[SECURITY\]|file size limits|allowed extensions' README.md`). `README.md:75` contains a prose reference ("security validation settings (file size limits, allowed extensions, etc.)") WITHOUT the literal `[SECURITY]` token; the wide pattern catches it. Drop or rephrase any matching bullets in lockstep with the CLAUDE.md change
- [x] Run `uv run python -c "from tax_reporting.infrastructure.config import Config, load_configuration_from_file; print('ok')"` → expect success
- [x] Run `uv run python -c "from tax_reporting.infrastructure.config import load_configuration_from_file; load_configuration_from_file('config.ini'); print('loaded')"` → expect no KeyError, no mention of `[SECURITY]`
- [x] Run `uv run ruff check src/tax_reporting/infrastructure/validation.py src/tax_reporting/infrastructure/config.py tests/unit/infrastructure/test_config.py tests/unit/application/persisting/test_workbook_builder.py` → expect clean
- [x] Run `uv run pytest tests/unit/infrastructure/test_config.py tests/unit/application/persisting/test_workbook_builder.py` → expect green with the reduced test count
- [x] Run `uv run pytest` → expect full green
- [x] Commit: `refactor(infra): drop dead SecurityConfig, six unused validators, and [SECURITY] config section`

### Task 3: Cluster C: Counter-ize holding-period tally

Files:
- `src/tax_reporting/application/crypto_reporting.py`

- [x] Verify the only produced `holding_period` values today: `rg 'holding_period\s*=' src/` and inspect the assignment sites. Expected values: `"Short-term"`, `"Long-term"`, `"Mixed"`, `"Unknown"` (case-insensitive via `.lower()` at the tally site)
- [x] Run `uv run pytest tests/unit/application/test_crypto_reporting.py` → record baseline count of passing tests in this file (pre-refactor)
- [x] Edit `crypto_reporting.py`: add `from collections import Counter` to imports if not already present (check existing `collections` imports first)
- [x] Edit `crypto_reporting.py:564-567`: replace the four `sum(...)` passes with the Counter form from the Gist. Preserve the `startswith("short")` / `startswith("long")` / `== "mixed"` / `== "unknown"` semantics exactly. Preserve the local variable names (`short_term_rows`, `long_term_rows`, `mixed_rows`, `unknown_rows`): they are referenced downstream at lines 570+ for the reconciliation mismatch check
- [x] Run `uv run pytest tests/unit/application/test_crypto_reporting.py tests/integration/ tests/end_to_end/` → expect GREEN (same count as baseline; these exercise the four-bucket reconciliation path)
- [x] Run `uv run ruff check src/tax_reporting/application/crypto_reporting.py` → expect clean
- [x] Run `uv run pytest` → expect full green
- [x] Commit: `refactor(crypto_reporting): Counter-ize holding_period tally to one pass`

### Task 4: Branch-final verification

- [x] Run `uv run pytest` → expect green (test count: 1713 baseline + ported `_find_report_path` tests − deleted `_find_report_file` tests − deleted SecurityConfig tests; net delta recorded in the Cluster A and B commit messages)
- [x] Run `uv run ruff check` on every touched file (production AND tests) → expect clean
- [x] Run `~/.ai-playbook/scripts/check-no-em-dash.sh` → expect clean
- [x] Run `rg '<deleted-symbol>' src/ tests/` for each removed name (`_find_report_file`, `_attributed_wallet`, `SecurityConfig`, `DEFAULT_SECURITY_CONFIG`, `_load_security_config`, `validate_csv_file`, `validate_company_ticker`, `validate_currency_code`, `validate_quantity`, `validate_price`, `sanitize_file_path`) → expect zero hits each
- [x] Verify git log shows three commits (one per cluster: Tasks 1, 2, 3)
- [x] Manual smoke check: `uv run python ./src/tax_reporting/main.py --help` → expect exit 0

## Monitor

None at plan-creation time. The originally-flagged `_workbook_lifecycle` collapse (finding #9) is out of scope by this revision; if a future simplification pass revives it, the reviewer must read `workbook_builder.py:61-86` carefully and account for the asymmetric close-error policy (success-propagate / exception-swallow+log) before proposing any merge of the two callbacks.
