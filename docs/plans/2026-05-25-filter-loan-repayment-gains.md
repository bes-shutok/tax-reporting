# Plan: Filter Loan Repayment Capital Gains (Country-Configurable)

Per CIRS art. 10(20) and `docs/domain/koinly_guidelines.md` Section 1.
Decision-points reference: `docs/tax/decision_points/2025.md` (Task 1).

## Design Invariants (CR Guard)

- Loan repayment filtering is governed by a `[TAX JURISDICTION]` config section with `TAX_COUNTRY` and `FISCAL_YEAR`, not hardcoded to any country. Portugal sets `TAX_COUNTRY = PT`, but the mechanism is generic.
- `_parse_capital_gains_file()` receives a `TaxJurisdictionConfig` dataclass, not raw country strings. Config parsing happens in `infrastructure/config.py`; application layer stays config-format-agnostic.
- The loan repayment filter runs **before** `_aggregate_capital_entries()` on individual CG lots, not on aggregated entries. This ordering must not change: filtering at the lot level avoids overfiltering non-repayment entries that share the same `(date, asset, platform)` with loan repayment disposals. After lot-level removal, aggregation combines only non-repayment lots, producing correct totals. The filter must also run before materiality so that large phantom gains are excluded from the materiality check.
- After the lot-level filter, any remaining CG entry whose `(date, asset, platform)` matches a loan repayment fingerprint is flagged with `review_required=True` and a specific `review_reason`. These entries are suspicious: they may be loan-related disposals that Koinly failed to tag as "Loan repayment" in the transaction history. They are NOT removed, only flagged for manual review in the final report.
- Filtered loan repayment entries with `cost_eur == 0` AND `|gain_loss_eur| >= threshold` are kept in the main capital gains table with red row background and a note column explaining they were excluded as loan repayment disposals but have zero cost basis, requiring manual review. This follows the same pattern as shares with placeholder buy dates. Entries below the threshold or with valid cost basis are fully excluded (no review needed).
- The red background rule applies to ALL capital gains entries in the report with `cost_eur == 0` AND `|gain_loss_eur| >= threshold`, not just filtered loan repayment entries. This catches the broader Koinly "Missing cost basis" defect (audit §5.1, §5.3, §5.4) for any disposal, regardless of origin. The threshold is configurable via `ZERO_BASIS_REVIEW_THRESHOLD` in the `[TAX JURISDICTION]` config section, defaulting to 50 in the report's base currency (EUR from Koinly).
- A "Loan Activity" tab summarizes per-asset loan receipts vs repayments with balance, flagging cross-year shortfalls (more repaid than received) and open loans at year-end. This is a read-only diagnostic for the user, not input to any filtering or calculation.
- `_extract_loan_repayment_fingerprints()` and `_filter_loan_repayment_lots()` are gated by `jurisdiction.exclude_loan_repayment_gains`. When the country does not exclude loan repayment gains, the filter is skipped entirely (no fingerprint extraction, no filtering pass).
- Decision points are versioned per fiscal year under `docs/tax/decision_points/<year>.md`. Each file is a self-contained snapshot of which laws are in effect and how they drive reporting behavior for that year. Laws themselves stay in `docs/tax/laws/` with enriched `sources.md` tracking effective and superseded dates.

## Review Scope

Files directly changed as part of this plan. Review feedback is accepted **only** for the files listed here.
Any finding about a file not in this list must be rejected as out of scope.

**Production code -- in scope:**
- `docs/tax/decision_points/2025.md` *(new)*
- `docs/tax/decision_points/README.md` *(new)*
- `docs/tax/laws/pt/crypto-tax/sources.md` -- enrich with Effective/Superseded columns
- `docs/tax/laws/eu/crypto-tax/sources.md` -- enrich with Effective/Superseded columns (if schema differs from PT)
- `src/shares_reporting/infrastructure/config.py` -- add `TaxJurisdictionConfig`, parse `[TAX JURISDICTION]` section
- `src/shares_reporting/application/crypto_reporting.py` -- new `_extract_loan_repayment_fingerprints()`, `_filter_loan_repayment_lots()`, `_flag_colocated_entries()`, config-driven pipeline insertion into `_parse_capital_gains_file()`
- `src/shares_reporting/application/persisting/crypto_gains_sheet.py` -- red background rendering for entries with zero cost basis >= configurable threshold
- `src/shares_reporting/application/persisting/loan_activity_sheet.py` *(new)* -- loan activity summary tab
- `src/shares_reporting/application/persisting/workbook_builder.py` -- wire loan activity sheet
- `src/shares_reporting/main.py` -- thread `TaxJurisdictionConfig` into `_load_crypto_tax_report()` -> `load_koinly_crypto_report()`
- `config.ini` -- add `[TAX JURISDICTION]` section
- `tests/config.ini` -- add `[TAX JURISDICTION]` section
- `docs/domain/koinly_guidelines.md` -- add cross-reference to decision-points doc (minor)

**Tests -- in scope:**
- `tests/unit/application/test_crypto_reporting.py` -- new test functions for loan repayment filtering
- `tests/unit/infrastructure/test_config.py` -- new test for `TaxJurisdictionConfig` parsing
- `tests/unit/application/persisting/test_crypto_gains_sheet.py` -- new test for red background rendering of zero-cost entries
- `tests/unit/application/persisting/test_loan_activity_sheet.py` *(new)* -- new test for loan activity summary tab

**Out of scope -- reject all review feedback:**
- `src/shares_reporting/infrastructure/koinly_parser.py` -- no changes needed (reuses existing helpers)
- `src/shares_reporting/domain/token_origin.py` -- no changes needed
- `docs/tax/laws/pt/crypto-tax/platform-divergences.md` -- already documents the legal basis

## Validation Commands

```bash
uv run pytest tests/unit/infrastructure/test_config.py -v -k "tax_jurisdiction"
uv run pytest tests/unit/application/test_crypto_reporting.py -v -k "loan_repayment"
uv run pytest tests/unit/application/test_crypto_reporting.py -v
uv run pytest tests/unit/application/persisting/test_crypto_gains_sheet.py -v -k "loan_repayment or zero_cost"
uv run pytest tests/unit/application/persisting/test_loan_activity_sheet.py -v
uv run pytest tests/unit/ -v
```

---

### Task 1: Create fiscal-year versioned decision-points structure

Files:
- `docs/tax/decision_points/README.md` *(new)*
- `docs/tax/decision_points/2025.md` *(new)*
- `docs/tax/laws/pt/crypto-tax/sources.md`
- `docs/domain/koinly_guidelines.md`

- [ ] Create `docs/tax/decision_points/README.md` as the index:
  - Purpose: directory index and template reference
  - Table of contents listing each fiscal year file with a one-line summary
  - "Creating a new fiscal year" instructions: copy the latest year file, update laws-in-effect section, re-verify each decision point against current sources
  - Template section showing the canonical structure (see 2025.md below)
- [ ] Create `docs/tax/decision_points/2025.md` with the following structure:
  ```markdown
  # Decision Points: Fiscal Year 2025

  Valid for: 2025 calendar year (PT IRS filing in 2026).
  Last verified: <date of creation>.

  ## Laws in Effect

  Sources with their effective period for this fiscal year.
  References `docs/tax/laws/pt/crypto-tax/sources.md` for full provenance.

  | Source | Published | Effective | Superseded | Scope |
  |--------|-----------|-----------|------------|-------|
  | CIRS consolidated 2025-07 | 2025-05-20 | 2025-07-01 | - | Art. 10(17)-(22) crypto CG definition |
  | AT Folheto Criptoativos | 2026-01-12 | - | - | Interpretive guidance on CIRS art. 10 |
  | AT Oficio Circulado 20278/2025 | 2025-03-17 | - | - | Modelo 3 filing instructions |
  | Portaria 104/2026 | 2026-03-05 | 2026-01-01 | - | Modelo 3 annex approval |
  | ... | ... | ... | ... | ... |

  Effective date rules:
  - Empty Effective = immediately effective on publication date.
  - Empty Superseded = still current as of this fiscal year.
  - Superseded dates note when a source was replaced by a newer enactment.

  ## Decision Points

  | # | Decision Point | PT | US | UK | DE | AU | Notes |
  |---|---------------|----|----|----|----|----|----|
  | DP-001 | Loan repayment = taxable disposal? | No (CIRS art. 10(20)) | Yes (Rev. Rul. 2023-14) | Yes (HMRC CRYPTO22100) | Yes (<1yr holding) | Yes (CGT Event A1) | Koinly treats as disposal by default; PT filter required |
  | DP-002 | Crypto-to-crypto = deferred disposal? | Yes (CIRS art. 10(20)) | No (immediate CG) | No (immediate CG) | No (immediate CG) | No (immediate CG) | Already handled by Koinly |
  | DP-003 | ... | ... | ... | ... | ... | ... | Template for future decision points |

  ## Source References

  - PT: `docs/tax/laws/pt/crypto-tax/sources.md`, `docs/tax/laws/pt/crypto-tax/platform-divergences.md`
  - EU: `docs/tax/laws/eu/crypto-tax/sources.md`
  - US: Rev. Rul. 2023-14 (not archived; verify before relying)
  - UK: HMRC Cryptoassets Manual CRYPTO22100 (not archived; verify before relying)
  - DE: EStG section 23 (not archived; verify before relying)
  - AU: ITAA 1997 s 104-10, CGT Event A1 (not archived; verify before relying)

  ## Change Log

  | Date | Change |
  |------|--------|
  | <creation date> | Initial decision points for FY2025 |
  ```
- [ ] Enrich `docs/tax/laws/pt/crypto-tax/sources.md` with effective/superseded metadata:
  - For each source entry, add `Effective:` and `Superseded:` lines after the existing `Issuing date:` line
  - Rules: `Effective:` defaults to issuing date if not separately specified; `Superseded:` is `-` when still current; for sources that replace earlier ones, add the superseded date to the earlier entry
  - Example additions:
    ```
    5. `official/cirs_2025-07_code_consolidated.pdf`
    - Issuing date: 2025-05-20
    - Effective: 2025-07-01
    - Superseded: -
    ```
- [ ] Check `docs/tax/laws/eu/crypto-tax/sources.md` for the same enrichment opportunity; apply if the schema matches
- [ ] Add one-line cross-reference from `docs/domain/koinly_guidelines.md` Section 1 to `docs/tax/decision_points/2025.md`
- [ ] Commit: `docs: add fiscal-year decision points structure with effective/superseded law tracking`

### Task 2: Write failing tests for `TaxJurisdictionConfig` parsing

Files:
- `tests/unit/infrastructure/test_config.py`

- [ ] Write failing test: `test_load_tax_jurisdiction_config_parses_country_and_year` -- config.ini with `[TAX JURISDICTION]\nTAX_COUNTRY = PT\nFISCAL_YEAR = 2025` produces `TaxJurisdictionConfig(country="PT", fiscal_year=2025, exclude_loan_repayment_gains=True)`
- [ ] Write failing test: `test_load_tax_jurisdiction_config_defaults_when_section_absent` -- config.ini without `[TAX JURISDICTION]` section produces `TaxJurisdictionConfig(country="PT", fiscal_year=2025, exclude_loan_repayment_gains=True)` (PT/2025 is default for backward compatibility)
- [ ] Write failing test: `test_load_tax_jurisdiction_config_unknown_country_defaults_to_no_filter` -- `TAX_COUNTRY = US` produces `exclude_loan_repayment_gains=False`
- [ ] Write failing test: `test_tax_jurisdiction_config_country_code_normalized_to_upper` -- `TAX_COUNTRY = pt` produces `country="PT"`
- [ ] Write failing test: `test_tax_jurisdiction_config_invalid_fiscal_year_raises` -- `FISCAL_YEAR = abc` raises `ValueError`
- [ ] Write failing test: `test_tax_jurisdiction_config_zero_basis_threshold_from_config` -- `ZERO_BASIS_REVIEW_THRESHOLD = 100` produces `zero_basis_review_threshold=Decimal("100")`
- [ ] Write failing test: `test_tax_jurisdiction_config_zero_basis_threshold_defaults_to_50` -- no `ZERO_BASIS_REVIEW_THRESHOLD` key produces `zero_basis_review_threshold=Decimal("50")`
- [ ] Run -> expect RED: `uv run pytest tests/unit/infrastructure/test_config.py -v -k "tax_jurisdiction" --no-header -q`

### Task 3: Implement `TaxJurisdictionConfig` and config parsing

Files:
- `src/shares_reporting/infrastructure/config.py`
- `config.ini`
- `tests/config.ini`

- [ ] Add `TaxJurisdictionConfig` dataclass to `config.py`:
  ```python
  @dataclass(frozen=True)
  class TaxJurisdictionConfig:
      country: str
      fiscal_year: int
      exclude_loan_repayment_gains: bool
      zero_basis_review_threshold: Decimal
  ```
- [ ] Add `_TAX_JURISDICTION_DEFAULTS` dict mapping country codes to their behavioral flags:
  ```python
  _TAX_JURISDICTION_DEFAULTS: dict[str, dict[str, bool]] = {
      "PT": {"exclude_loan_repayment_gains": True},
  }
  ```
  Countries not in this dict get all flags set to `False`.
- [ ] Add `_load_tax_jurisdiction_config(config, logger) -> TaxJurisdictionConfig` that reads `[TAX JURISDICTION]` section, uppercases country code, parses fiscal year as int, looks up behavioral flags from defaults dict
- [ ] Add `tax_jurisdiction: TaxJurisdictionConfig` field to `Config` dataclass
- [ ] Wire into `load_configuration_from_file()`
- [ ] Add `[TAX JURISDICTION]` section to both `config.ini` and `tests/config.ini`:
  ```ini
  [TAX JURISDICTION]
  TAX_COUNTRY = PT
  FISCAL_YEAR = 2025
  ZERO_BASIS_REVIEW_THRESHOLD = 50
  ```
- [ ] Run -> expect GREEN: `uv run pytest tests/unit/infrastructure/test_config.py -v -k "tax_jurisdiction" --no-header -q`
- [ ] Commit: `feat: add TaxJurisdictionConfig for country-specific tax treatment`

### Task 4: Write failing tests for `_extract_loan_repayment_fingerprints()`

Files:
- `tests/unit/application/test_crypto_reporting.py`

- [ ] Write failing test: `test_extract_loan_repayment_fingerprints_finds_tagged_withdrawals` -- transaction history CSV with one `crypto_withdrawal` row where `Tag=Loan repayment` produces a fingerprint set containing `(disposal_date, normalized_asset, normalized_wallet)`
- [ ] Write failing test: `test_extract_loan_repayment_fingerprints_ignores_other_withdrawals` -- rows with `Tag=Cost` or empty tag produce no fingerprints
- [ ] Write failing test: `test_extract_loan_repayment_fingerprints_ignores_non_withdrawal_types` -- `exchange` and `transfer` rows with `Tag=Loan repayment` produce no fingerprints
- [ ] Write failing test: `test_extract_loan_repayment_fingerprints_normalizes_asset_and_wallet` -- verifies asset normalization (Cyrillic-to-Latin) and platform normalization (`ByBit (2)` -> `ByBit`) apply to fingerprints
- [ ] Write failing test: `test_extract_loan_repayment_fingerprints_returns_empty_set_when_no_file` -- `None` path returns empty set
- [ ] Run -> expect RED: `uv run pytest tests/unit/application/test_crypto_reporting.py -v -k "loan_repayment" --no-header -q`

### Task 5: Write failing tests for `_filter_loan_repayment_lots()`

Files:
- `tests/unit/application/test_crypto_reporting.py`

- [ ] Write failing test: `test_filter_loan_repayment_lots_removes_matching_entry` -- individual CG lot whose `(disposal_date, asset, platform)` matches a fingerprint is excluded from kept list and present in filtered list
- [ ] Write failing test: `test_filter_loan_repayment_lots_keeps_non_matching_entry` -- lot that does not match any fingerprint is retained in kept list, filtered list empty
- [ ] Write failing test: `test_filter_loan_repayment_lots_empty_fingerprints_keeps_all` -- empty fingerprint set retains all lots in kept list, filtered list empty
- [ ] Write failing test: `test_filter_loan_repayment_lots_logs_filtered_count` -- when lots are removed, a warning is logged with the count
- [ ] Write failing test: `test_filter_loan_repayment_lots_partial_match_only_removes_matching` -- mix of matching and non-matching lots on the same date/asset/platform; only matching lots removed, non-repayment lots preserved for aggregation
- [ ] Write failing test: `test_filter_loan_repayment_lots_returns_both_lists` -- function returns a tuple `(kept, filtered)` where `kept` has non-matching entries and `filtered` has matching entries; both lists are non-empty when partial match
- [ ] Write failing test: `test_select_review_candidates_selects_zero_cost_above_threshold` -- filtered entries with `cost_eur == 0` AND `|gain_loss_eur| >= 50` are selected as review candidates
- [ ] Write failing test: `test_select_review_candidates_skips_zero_cost_below_threshold` -- filtered entries with `cost_eur == 0` AND `|gain_loss_eur| < 50` are NOT selected
- [ ] Write failing test: `test_select_review_candidates_skips_nonzero_cost` -- filtered entries with `cost_eur > 0` are NOT selected regardless of gain
- [ ] Write failing test: `test_select_review_candidates_uses_config_threshold` -- threshold value from `TaxJurisdictionConfig.zero_basis_review_threshold` is used instead of hardcoded 50
- [ ] Run -> expect RED: `uv run pytest tests/unit/application/test_crypto_reporting.py -v -k "filter_loan_repayment" --no-header -q`

### Task 6: Write failing integration tests for pipeline order and config gating

Files:
- `tests/unit/application/test_crypto_reporting.py`

- [ ] Write failing test: `test_parse_capital_gains_file_filters_loan_repayments_when_config_enabled` -- end-to-end test with a Koinly capital gains CSV containing a loan repayment disposal AND a normal disposal, plus a transaction history CSV with a matching `crypto_withdrawal` tagged `Loan repayment`. `TaxJurisdictionConfig(country="PT", fiscal_year=2025, exclude_loan_repayment_gains=True)` passed in. Verifies: loan repayment entry absent from output, normal entry present.
- [ ] Write failing test: `test_parse_capital_gains_file_keeps_loan_repayments_when_config_disabled` -- same setup but `TaxJurisdictionConfig(country="US", fiscal_year=2025, exclude_loan_repayment_gains=False)`. Verifies: both entries present (loan repayment not filtered).
- [ ] Write failing test: `test_parse_capital_gains_file_loan_repayment_filter_before_aggregation` -- two CG lots on same date/asset/platform: one matches a loan repayment fingerprint, one does not. After pipeline, the non-repayment lot is aggregated normally and present in output. The loan repayment lot is absent. Proves filter runs on individual lots before aggregation.
- [ ] Write failing test: `test_parse_capital_gains_file_loan_repayment_filter_before_materiality` -- loan repayment entry with gain > 1 EUR is still filtered when config enabled (proves loan repayment filter runs before materiality filter)
- [ ] Write failing test: `test_parse_capital_gains_file_flags_colocated_non_repayment_entries` -- CG lots on a date/asset/platform that matches a loan repayment fingerprint, but where the specific lot was NOT removed by the filter. After pipeline, these entries have `review_required=True` with a `review_reason` explaining the colocation with loan repayments.
- [ ] Run -> expect RED: `uv run pytest tests/unit/application/test_crypto_reporting.py -v -k "loan_repayment" --no-header -q`

### Task 7: Implement `_extract_loan_repayment_fingerprints()`

Files:
- `src/shares_reporting/application/crypto_reporting.py`

- [ ] Add import for `TaxJurisdictionConfig` from `..infrastructure.config`
- [ ] Implement `_extract_loan_repayment_fingerprints(transaction_history_path: Path | None) -> frozenset[tuple[str, str, str]]`:
  - If `transaction_history_path is None` or file does not exist, return `frozenset()`
  - Read rows via `_read_koinly_rows()`
  - Filter to `Type == "crypto_withdrawal"` AND `Tag` (case-insensitive) contains `"loan repayment"`
  - Parse date via `_parse_koinly_datetime` + `_format_datetime` to get `date_key`
  - Build `(date_key, _normalize_asset_ticker(sent_currency), _normalize_platform_name(sending_wallet))` for each matching row
  - Skip rows where date parsing fails (log warning) or sent_currency is empty
  - Return `frozenset(...)` of all tuples
- [ ] Run -> expect GREEN for fingerprint tests: `uv run pytest tests/unit/application/test_crypto_reporting.py -v -k "extract_loan_repayment" --no-header -q`

### Task 8: Implement `_filter_loan_repayment_lots()`, `_flag_colocated_entries()`, and `_select_review_candidates()`

Files:
- `src/shares_reporting/application/crypto_reporting.py`

- [ ] Implement `_filter_loan_repayment_lots(entries: list[CryptoCapitalGainEntry], fingerprints: frozenset[tuple[str, str, str]]) -> tuple[list[CryptoCapitalGainEntry], list[CryptoCapitalGainEntry]]`:
  - Split entries into `kept` (where `(entry.disposal_date, entry.asset, entry.platform)` NOT in `fingerprints`) and `filtered` (matching entries)
  - Log warning with count of filtered entries when any are removed
  - Return `(kept, filtered)` tuple
- [ ] Implement `_flag_colocated_entries(entries: list[CryptoCapitalGainEntry], fingerprints: frozenset[tuple[str, str, str]]) -> list[CryptoCapitalGainEntry]`:
  - For each remaining entry, check if `(entry.disposal_date, entry.asset, entry.platform)` matches any fingerprint
  - If match and `entry.review_required` is False, set `review_required=True` and `review_reason="Co-located with loan repayment disposal on same date/asset/platform; verify this is not a loan-related disposal that Koinly failed to tag"`
  - If match and `entry.review_required` is already True, append the colocation reason to the existing `review_reason`
  - Return list with flags applied
- [ ] Implement `_select_review_candidates(filtered: list[CryptoCapitalGainEntry], threshold: Decimal) -> list[CryptoCapitalGainEntry]`:
  - From the filtered (removed) entries, select those where `cost_eur == 0` AND `abs(gain_loss_eur) >= threshold`
  - For each selected entry, set `review_required=True` and `review_reason="Loan repayment disposal excluded per CIRS art. 10(20) but has zero cost basis (gain/loss: {gain_loss_eur} EUR); verify Koinly tagging is correct"`
  - Return the review candidates list
- [ ] Run -> expect GREEN for filter tests: `uv run pytest tests/unit/application/test_crypto_reporting.py -v -k "filter_loan_repayment" --no-header -q`

### Task 9: Wire config-driven pipeline into `_parse_capital_gains_file()`

Files:
- `src/shares_reporting/application/crypto_reporting.py`
- `src/shares_reporting/main.py`

- [ ] Modify `_parse_capital_gains_file()` signature to accept `jurisdiction: TaxJurisdictionConfig` and `transaction_history_path: Path | None = None`
- [ ] Insert loan repayment filter into the pipeline **before aggregation**, gated by `jurisdiction.exclude_loan_repayment_gains`:
  ```python
  # Validate countries before any filtering
  _validate_capital_entries_have_valid_countries(capital_entries)

  loan_repayment_review: list[CryptoCapitalGainEntry] = []
  if jurisdiction.exclude_loan_repayment_gains:
      fingerprints = _extract_loan_repayment_fingerprints(transaction_history_path)
      pre_loan_filter = len(capital_entries)
      capital_entries, filtered = _filter_loan_repayment_lots(capital_entries, fingerprints)
      loan_filtered = pre_loan_filter - len(capital_entries)
      if loan_filtered > 0:
          logger.warning(
              "Filtered %d loan repayment capital gain lots (%s; country=%s, fy=%d); %d lots retained for aggregation",
              loan_filtered,
              "CIRS art. 10(20)" if jurisdiction.country == "PT" else "local law",
              jurisdiction.country,
              jurisdiction.fiscal_year,
              len(capital_entries),
          )
      loan_repayment_review = _select_review_candidates(filtered, jurisdiction.zero_basis_review_threshold)
      capital_entries = _flag_colocated_entries(capital_entries, fingerprints)

  capital_entries = _aggregate_capital_entries(capital_entries)
  pre_filter_count = len(capital_entries)
  capital_entries = _filter_immaterial_entries(capital_entries)
  ```
- [ ] Return `loan_repayment_review` alongside `capital_entries` from `_parse_capital_gains_file()` (as a named tuple or second return value) so the sheet writer can render them in the main table with red background
- [ ] Update `load_koinly_crypto_report()` signature to accept `jurisdiction: TaxJurisdictionConfig`, pass both `jurisdiction` and `transaction_history_file` to `_parse_capital_gains_file()`
- [ ] Update `_load_crypto_tax_report()` in `main.py` to accept and pass `TaxJurisdictionConfig` from the loaded `Config`
- [ ] Thread the config from the main pipeline: `Config.tax_jurisdiction` -> `_load_crypto_tax_report()` -> `load_koinly_crypto_report()` -> `_parse_capital_gains_file()`
- [ ] Run -> expect GREEN for all loan repayment tests: `uv run pytest tests/unit/application/test_crypto_reporting.py -v -k "loan_repayment" --no-header -q`
- [ ] Commit: `feat: wire config-driven loan repayment filter into capital gains pipeline`

### Task 10: Write failing tests and implement red background for zero-cost entries

Files:
- `tests/unit/application/persisting/test_crypto_gains_sheet.py`
- `src/shares_reporting/application/persisting/crypto_gains_sheet.py`

- [ ] Write failing test: `test_render_zero_cost_entry_has_red_background` -- a `CryptoCapitalGainEntry` with `cost_eur == 0` AND `|gain_loss_eur| >= threshold` renders with `PatternFill(start_color="FFFF0000")` on all cells in that row, matching the shares placeholder-buy-date pattern in `ib_sheet.py`
- [ ] Write failing test: `test_render_zero_cost_below_threshold_no_red_background` -- entry with `cost_eur == 0` AND `|gain_loss_eur| < threshold` renders without red background
- [ ] Write failing test: `test_render_nonzero_cost_no_red_background` -- entry with `cost_eur > 0` renders without red background regardless of gain
- [ ] Write failing test: `test_render_loan_repayment_review_row_has_red_background` -- a `CryptoCapitalGainEntry` from `loan_repayment_review` list (which has zero cost by construction) renders with red background
- [ ] Write failing test: `test_render_normal_row_no_red_background` -- a regular `CryptoCapitalGainEntry` with valid cost basis renders without red background
- [ ] Run -> expect RED: `uv run pytest tests/unit/application/persisting/test_crypto_gains_sheet.py -v -k "loan_repayment or zero_cost" --no-header -q`
- [ ] Update `write_crypto_gains_sheet()` signature to accept `loan_repayment_review: list[CryptoCapitalGainEntry] = None` and `zero_basis_review_threshold: Decimal = Decimal("50")`
- [ ] After rendering normal capital gains rows, render `loan_repayment_review` entries in the same table
- [ ] Apply red row background to ANY row (normal or loan repayment review) where `cost_eur == 0` AND `|gain_loss_eur| >= zero_basis_review_threshold` (same pattern as `ib_sheet.py` lines 161-164: `PatternFill(start_color="FFFF0000", end_color="FFFF0000", fill_type="solid")` applied to all columns)
- [ ] Review entries are included in the same table (not a separate section) so the user can review them in context with other disposals
- [ ] Run -> expect GREEN: `uv run pytest tests/unit/application/persisting/test_crypto_gains_sheet.py -v -k "loan_repayment or zero_cost" --no-header -q`
- [ ] Commit: `feat: render zero-cost entries with red background in crypto gains sheet`

### Task 11: Write failing tests and implement Loan Activity sheet

Files:
- `tests/unit/application/persisting/test_loan_activity_sheet.py` *(new)*
- `src/shares_reporting/application/persisting/loan_activity_sheet.py` *(new)*
- `src/shares_reporting/application/crypto_reporting.py`
- `src/shares_reporting/application/persisting/workbook_builder.py`

- [ ] Write failing test: `test_loan_activity_shows_per_asset_balance` -- loan activity data with SUI receipts and repayments produces a table with per-asset rows showing received amount, repaid amount, and balance
- [ ] Write failing test: `test_loan_activity_flags_overpaid` -- when more repaid than received for an asset, the balance row shows "Overpaid (cross-year loan?)" indicator with explanation text
- [ ] Write failing test: `test_loan_activity_flags_open_loan` -- when more received than repaid, the balance row shows "Open loan" indicator
- [ ] Write failing test: `test_loan_activity_empty_when_no_loan_transactions` -- no loan transactions produces an empty sheet with header only
- [ ] Run -> expect RED: `uv run pytest tests/unit/application/persisting/test_loan_activity_sheet.py -v --no-header -q`
- [ ] Add `LoanActivityEntry` dataclass to `crypto_reporting.py`:
  ```python
  @dataclass(frozen=True)
  class LoanActivityEntry:
      asset: str
      received_count: int
      received_amount: Decimal
      received_value_eur: Decimal
      repaid_count: int
      repaid_amount: Decimal
      repaid_value_eur: Decimal
      balance_amount: Decimal  # received - repaid
      balance_status: str  # "Settled", "Overpaid (cross-year loan?)", "Open loan"
  ```
- [ ] Add `_extract_loan_activity(transaction_history_path: Path | None) -> list[LoanActivityEntry]` to `crypto_reporting.py`:
  - Read transaction history, filter rows tagged "Loan" (receipts) and "Loan repayment" (repayments)
  - Aggregate per asset: count, total amount, total EUR value
  - Compute balance and status
  - Return sorted by asset
- [ ] Add `loan_activity` field to `CryptoTaxReport` dataclass
- [ ] Wire `_extract_loan_activity()` call into `load_koinly_crypto_report()` alongside fingerprint extraction
- [ ] Create `loan_activity_sheet.py` with `write_loan_activity_sheet()`:
  - Headers: Asset, Received Count, Received Amount, Received Value (EUR), Repaid Count, Repaid Amount, Repaid Value (EUR), Balance Amount, Status
  - Per-asset row from `LoanActivityEntry`
  - "Overpaid" rows get light-red background (`FFCCCC`)
  - Summary row at bottom with totals
- [ ] Wire into `workbook_builder.py`: add `write_loan_activity_sheet(workbook, crypto_tax_report)` call after reconciliation sheet
- [ ] Run -> expect GREEN: `uv run pytest tests/unit/application/persisting/test_loan_activity_sheet.py -v --no-header -q`
- [ ] Commit: `feat: add Loan Activity sheet with per-asset balance and shortfall detection`

### Task 12: Final validation

- [ ] Run full unit test suite: `uv run pytest tests/unit/ -v --tb=short`
- [ ] Run full test suite: `uv run pytest --tb=short`
- [ ] Verify no formatting-only changes: `git diff`
- [ ] Verify decision-points structure is complete: read `docs/tax/decision_points/2025.md` and `docs/tax/decision_points/README.md`
- [ ] Verify `sources.md` enrichment has effective/superseded metadata for all PT sources
