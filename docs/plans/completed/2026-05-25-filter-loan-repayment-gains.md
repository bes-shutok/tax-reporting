# Plan: Filter Loan Repayment Capital Gains (Country-Configurable)

**Superseded** by the FIFO rebuild approach. The lot-level filter was insufficient because Koinly's pool contamination is structural: loan deposit lots remain in the FIFO pool for future real disposals, and LBTC-to-WBTC carry-over propagates contaminated basis. See `docs/domain/koinly-fifo-findings.md` and `2026-05-27-rebuild-fifo-from-th.md`.

Per CIRS art. 10(20) and `../../domain/koinly_guidelines.md` Section 1.
Decision-points reference: `../../tax/decision_points/2025.md` (Task 1).
Premortem review: `docs/review/2026-05-26-premortem-filter-loan-repayment-gains.md`
Plan review: `docs/review/2026-05-26-plan-review-filter-loan-repayment-gains.md`

## Design Invariants (CR Guard)

- Loan repayment filtering is governed by a `[TAX JURISDICTION]` config section with `TAX_COUNTRY` and `FISCAL_YEAR`, not hardcoded to any country. Portugal sets `TAX_COUNTRY = PT`, but the mechanism is generic.
- `_parse_capital_gains_file()` receives a `TaxJurisdictionConfig` dataclass, not raw country strings. Config parsing happens in `infrastructure/config.py`; application layer stays config-format-agnostic.
- The loan repayment filter runs **before** `_aggregate_capital_entries()` on individual CG lots, not on aggregated entries. This ordering must not change: filtering at the lot level avoids overfiltering non-repayment entries that share the same `(date, asset, platform)` with loan repayment disposals. After lot-level removal, aggregation combines only non-repayment lots, producing correct totals. The filter must also run before materiality so that large phantom gains are excluded from the materiality check.
- The lot-level filter criterion is `(disposal_date, asset, platform) in fingerprints AND cost_eur == 0`. The `cost_eur == 0` condition is necessary but not sufficient: since genuine disposals can also have zero cost (Koinly "Missing cost basis" defect), the filter uses a **counting approach**: for each fingerprint key, remove at most N zero-cost lots where N equals the number of fingerprints for that key. Excess zero-cost lots sharing the same key are NOT removed but are flagged `review_required=True` with a reason explaining they share coordinates with loan repayments and have zero cost basis. This prevents underreporting when a genuine missing-basis disposal coincides with a loan repayment.
- Country validation (`_validate_capital_entries_have_valid_countries()`) must run AFTER the loan repayment filter, not before. Filtered entries don't participate in tax filing; their country codes are irrelevant and should not block processing.
- After the lot-level filter, any remaining CG entry whose `(date, asset, platform)` matches a loan repayment fingerprint is flagged with `review_required=True` and a specific `review_reason`. These entries are suspicious: they may be loan-related disposals that Koinly failed to tag as "Loan repayment" in the transaction history. They are NOT removed, only flagged for manual review in the final report.
- Filtered loan repayment entries with `cost_eur == 0` AND `|gain_loss_eur| >= threshold` are kept in the main capital gains table with red row background and a note column explaining they were excluded as loan repayment disposals but have zero cost basis, requiring manual review. This follows the same pattern as shares with placeholder buy dates. Entries below the threshold or with valid cost basis are fully excluded (no review needed).
- The red background rule applies to ALL capital gains entries in the report with `cost_eur == 0` AND `|gain_loss_eur| >= threshold`, not just filtered loan repayment entries. This catches the broader Koinly "Missing cost basis" defect (audit §5.1, §5.3, §5.4) for any disposal, regardless of origin. The threshold is configurable via `ZERO_BASIS_REVIEW_THRESHOLD` in the `[TAX JURISDICTION]` config section, defaulting to 50 in the report's base currency (EUR from Koinly).
- `CryptoTaxReport` is the transport for all filter results: it carries `loan_repayment_review`, `loan_activity`, and `zero_basis_review_threshold`. Sheet writers read from the report object, not from separate parameters or disconnected defaults.
- A "Loan Activity" tab summarizes per-asset loan receipts vs repayments with balance, flagging cross-year shortfalls (more repaid than received) and open loans at year-end. This is a read-only diagnostic for the user, not input to any filtering or calculation.
- `_extract_loan_repayment_fingerprints()` and `_filter_loan_repayment_lots()` are gated by `jurisdiction.exclude_loan_repayment_gains`. When the country does not exclude loan repayment gains, the filter is skipped entirely (no fingerprint extraction, no filtering pass).
- Decision points are versioned per fiscal year under `docs/tax/decision_points/<year>.md`. Each file is a self-contained snapshot of which laws are in effect and how they drive reporting behavior for that year. Laws themselves stay in `../../tax/laws` with enriched `sources.md` tracking effective and superseded dates.

## Review Scope

Files directly changed as part of this plan. Review feedback is accepted **only** for the files listed here.
Any finding about a file not in this list must be rejected as out of scope.

**Production code -- in scope:**
- `../../tax/decision_points/2025.md` *(new)*
- `../../tax/decision_points/README.md` *(new)*
- `../../tax/laws/pt/crypto-tax/sources.md` -- enrich with Effective/Superseded columns
- `../../tax/laws/eu/crypto-tax/sources.md` -- enrich with Effective/Superseded columns (if schema differs from PT)
- `../../../src/shares_reporting/infrastructure/config.py` -- add `TaxJurisdictionConfig`, parse `[TAX JURISDICTION]` section
- `../../../src/shares_reporting/application/crypto_reporting.py` -- new `_extract_loan_repayment_fingerprints()`, `_filter_loan_repayment_lots()`, `_flag_colocated_entries()`, config-driven pipeline insertion into `_parse_capital_gains_file()`
- `../../../src/shares_reporting/application/persisting/crypto_gains_sheet.py` -- red background rendering for entries with zero cost basis >= configurable threshold
- `../../../src/shares_reporting/application/persisting/loan_activity_sheet.py` *(new)* -- loan activity summary tab
- `../../../src/shares_reporting/application/persisting/workbook_builder.py` -- wire loan activity sheet
- `../../../src/shares_reporting/main.py` -- thread `TaxJurisdictionConfig` into `_load_crypto_tax_report()` -> `load_koinly_crypto_report()`
- `../../../config.ini` -- add `[TAX JURISDICTION]` section
- `../../../tests/config.ini` -- add `[TAX JURISDICTION]` section
- `../../domain/koinly_guidelines.md` -- add cross-reference to decision-points doc (minor)

**Tests -- in scope:**
- `../../../tests/unit/application/test_crypto_reporting.py` -- new test functions for loan repayment filtering
- `../../../tests/unit/infrastructure/test_config.py` -- new test for `TaxJurisdictionConfig` parsing
- `../../../tests/unit/application/persisting/test_crypto_gains_sheet.py` -- new test for red background rendering of zero-cost entries
- `../../../tests/unit/application/persisting/test_loan_activity_sheet.py` *(new)* -- new test for loan activity summary tab

**Out of scope -- reject all review feedback:**
- `../../../src/shares_reporting/infrastructure/koinly_parser.py` -- no changes needed (reuses existing helpers)
- `../../../src/shares_reporting/domain/token_origin.py` -- no changes needed
- `../../tax/laws/pt/crypto-tax/platform-divergences.md` -- already documents the legal basis

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
- `../../tax/decision_points/README.md` *(new)*
- `../../tax/decision_points/2025.md` *(new)*
- `../../tax/laws/pt/crypto-tax/sources.md`
- `../../domain/koinly_guidelines.md`

- [x] Create `../../tax/decision_points/README.md` as the index:
  - Purpose: directory index and template reference
  - Table of contents listing each fiscal year file with a one-line summary
  - "Creating a new fiscal year" instructions: copy the latest year file, update laws-in-effect section, re-verify each decision point against current sources
  - Template section showing the canonical structure (see 2025.md below)
- [x] Create `../../tax/decision_points/2025.md` with the following structure:
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
- [x] Enrich `../../tax/laws/pt/crypto-tax/sources.md` with effective/superseded metadata:
  - For each source entry, add `Effective:` and `Superseded:` lines after the existing `Issuing date:` line
  - Rules: `Effective:` defaults to issuing date if not separately specified; `Superseded:` is `-` when still current; for sources that replace earlier ones, add the superseded date to the earlier entry
  - Example additions:
    ```
    5. `official/cirs_2025-07_code_consolidated.pdf`
    - Issuing date: 2025-05-20
    - Effective: 2025-07-01
    - Superseded: -
    ```
- [x] Check `../../tax/laws/eu/crypto-tax/sources.md` for the same enrichment opportunity; apply if the schema matches
- [x] Add one-line cross-reference from `../../domain/koinly_guidelines.md` Section 1 to `../../tax/decision_points/2025.md`
- [x] Commit: `docs: add fiscal-year decision points structure with effective/superseded law tracking`

### Task 2: Write failing tests for `TaxJurisdictionConfig` parsing

Files:
- `../../../tests/unit/infrastructure/test_config.py`

- [x] Write failing test: `test_load_tax_jurisdiction_config_parses_country_and_year` -- config.ini with `[TAX JURISDICTION]\nTAX_COUNTRY = PT\nFISCAL_YEAR = 2025` produces `TaxJurisdictionConfig(country="PT", fiscal_year=2025, exclude_loan_repayment_gains=True)`
- [x] Write failing test: `test_load_tax_jurisdiction_config_defaults_when_section_absent` -- config.ini without `[TAX JURISDICTION]` section produces `TaxJurisdictionConfig(country="PT", fiscal_year=2025, exclude_loan_repayment_gains=True)` (PT/2025 is default for backward compatibility)
- [x] Write failing test: `test_load_tax_jurisdiction_config_unknown_country_defaults_to_no_filter` -- `TAX_COUNTRY = US` produces `exclude_loan_repayment_gains=False`
- [x] Write failing test: `test_tax_jurisdiction_config_country_code_normalized_to_upper` -- `TAX_COUNTRY = pt` produces `country="PT"`
- [x] Write failing test: `test_tax_jurisdiction_config_invalid_fiscal_year_raises` -- `FISCAL_YEAR = abc` raises `ValueError`
- [x] Write failing test: `test_tax_jurisdiction_config_zero_basis_threshold_from_config` -- `ZERO_BASIS_REVIEW_THRESHOLD = 100` produces `zero_basis_review_threshold=Decimal("100")`
- [x] Write failing test: `test_tax_jurisdiction_config_zero_basis_threshold_defaults_to_50` -- no `ZERO_BASIS_REVIEW_THRESHOLD` key produces `zero_basis_review_threshold=Decimal("50")`
- [x] Run -> expect RED: `uv run pytest tests/unit/infrastructure/test_config.py -v -k "tax_jurisdiction" --no-header -q`

### Task 3: Implement `TaxJurisdictionConfig` and config parsing

Files:
- `../../../src/shares_reporting/infrastructure/config.py`
- `../../../config.ini`
- `../../../tests/config.ini`

- [x] Add `TaxJurisdictionConfig` dataclass to `config.py`:
  ```python
  @dataclass(frozen=True)
  class TaxJurisdictionConfig:
      country: str
      fiscal_year: int
      exclude_loan_repayment_gains: bool
      zero_basis_review_threshold: Decimal
  ```
- [x] Add `_TAX_JURISDICTION_DEFAULTS` dict mapping country codes to their behavioral flags:
  ```python
  _TAX_JURISDICTION_DEFAULTS: dict[str, dict[str, bool]] = {
      "PT": {"exclude_loan_repayment_gains": True},
  }
  ```
  Countries not in this dict get all flags set to `False`.
- [x] Add `_load_tax_jurisdiction_config(config, logger) -> TaxJurisdictionConfig` that reads `[TAX JURISDICTION]` section, uppercases country code, parses fiscal year as int, looks up behavioral flags from defaults dict
- [x] Add `tax_jurisdiction: TaxJurisdictionConfig` field to `Config` dataclass
- [x] Wire into `load_configuration_from_file()`
- [x] Add `[TAX JURISDICTION]` section to both `../../../config.ini` and `../../../tests/config.ini`:
  ```ini
  [TAX JURISDICTION]
  TAX_COUNTRY = PT
  FISCAL_YEAR = 2025
  ZERO_BASIS_REVIEW_THRESHOLD = 50
  ```
- [x] Run -> expect GREEN: `uv run pytest tests/unit/infrastructure/test_config.py -v -k "tax_jurisdiction" --no-header -q`
- [x] Commit: `feat: add TaxJurisdictionConfig for country-specific tax treatment`

### Task 4: Write failing tests for `_extract_loan_repayment_fingerprints()`

Files:
- `../../../tests/unit/application/test_crypto_reporting.py`

- [x] Write failing test: `test_extract_loan_repayment_fingerprints_finds_tagged_withdrawals` -- transaction history CSV with one `crypto_withdrawal` row where `Tag=Loan repayment` produces a fingerprint set containing `(disposal_date, normalized_asset, normalized_wallet)`
- [x] Write failing test: `test_extract_loan_repayment_fingerprints_ignores_other_withdrawals` -- rows with `Tag=Cost` or empty tag produce no fingerprints
- [x] Write failing test: `test_extract_loan_repayment_fingerprints_ignores_non_withdrawal_types` -- `exchange` and `transfer` rows with `Tag=Loan repayment` produce no fingerprints
- [x] Write failing test: `test_extract_loan_repayment_fingerprints_normalizes_asset_and_wallet` -- verifies asset normalization (Cyrillic-to-Latin) and platform normalization (`ByBit (2)` -> `ByBit`) apply to fingerprints
- [x] Write failing test: `test_extract_loan_repayment_fingerprints_returns_empty_set_when_no_file` -- `None` path returns empty set
- [x] Run -> expect RED: `uv run pytest tests/unit/application/test_crypto_reporting.py -v -k "loan_repayment" --no-header -q`

### Task 5: Write failing tests for `_filter_loan_repayment_lots()`

Files:
- `../../../tests/unit/application/test_crypto_reporting.py`

- [x] Write failing test: `test_filter_loan_repayment_lots_removes_matching_entry` -- individual CG lot whose `(disposal_date, asset, platform)` matches a fingerprint is excluded from kept list and present in filtered list
- [x] Write failing test: `test_filter_loan_repayment_lots_keeps_non_matching_entry` -- lot that does not match any fingerprint is retained in kept list, filtered list empty
- [x] Write failing test: `test_filter_loan_repayment_lots_empty_fingerprints_keeps_all` -- empty fingerprint set retains all lots in kept list, filtered list empty
- [x] Write failing test: `test_filter_loan_repayment_lots_logs_filtered_count` -- when lots are removed, a warning is logged with the count
- [x] Write failing test: `test_filter_loan_repayment_lots_partial_match_only_removes_matching` -- mix of matching and non-matching lots on the same date/asset/platform; only matching lots removed, non-repayment lots preserved for aggregation
- [x] Write failing test: `test_filter_loan_repayment_lots_returns_both_lists` -- function returns a tuple `(kept, filtered)` where `kept` has non-matching entries and `filtered` has matching entries; both lists are non-empty when partial match
- [x] Write failing test: `test_select_review_candidates_selects_zero_cost_above_threshold` -- filtered entries with `cost_eur == 0` AND `|gain_loss_eur| >= 50` are selected as review candidates
- [x] Write failing test: `test_select_review_candidates_skips_zero_cost_below_threshold` -- filtered entries with `cost_eur == 0` AND `|gain_loss_eur| < 50` are NOT selected
- [x] Write failing test: `test_select_review_candidates_skips_nonzero_cost` -- filtered entries with `cost_eur > 0` are NOT selected regardless of gain
- [x] Write failing test: `test_select_review_candidates_uses_config_threshold` -- threshold value from `TaxJurisdictionConfig.zero_basis_review_threshold` is used instead of hardcoded 50
- [x] Run -> expect RED: `uv run pytest tests/unit/application/test_crypto_reporting.py -v -k "filter_loan_repayment" --no-header -q`

### Task 6: Write failing integration tests for pipeline order and config gating

Files:
- `../../../tests/unit/application/test_crypto_reporting.py`

- [x] Write failing test: `test_parse_capital_gains_file_filters_loan_repayments_when_config_enabled` -- end-to-end test with a Koinly capital gains CSV containing a loan repayment disposal AND a normal disposal, plus a transaction history CSV with a matching `crypto_withdrawal` tagged `Loan repayment`. `TaxJurisdictionConfig(country="PT", fiscal_year=2025, exclude_loan_repayment_gains=True)` passed in. Verifies: loan repayment entry absent from output, normal entry present.
- [x] Write failing test: `test_parse_capital_gains_file_keeps_loan_repayments_when_config_disabled` -- same setup but `TaxJurisdictionConfig(country="US", fiscal_year=2025, exclude_loan_repayment_gains=False)`. Verifies: both entries present (loan repayment not filtered).
- [x] Write failing test: `test_parse_capital_gains_file_loan_repayment_filter_before_aggregation` -- two CG lots on same date/asset/platform: one matches a loan repayment fingerprint, one does not. After pipeline, the non-repayment lot is aggregated normally and present in output. The loan repayment lot is absent. Proves filter runs on individual lots before aggregation.
- [x] Write failing test: `test_parse_capital_gains_file_loan_repayment_filter_before_materiality` -- loan repayment entry with gain > 1 EUR is still filtered when config enabled (proves loan repayment filter runs before materiality filter)
- [x] Write failing test: `test_parse_capital_gains_file_flags_colocated_non_repayment_entries` -- CG lots on a date/asset/platform that matches a loan repayment fingerprint, but where the specific lot was NOT removed by the filter. After pipeline, these entries have `review_required=True` with a `review_reason` explaining the colocation with loan repayments.
- [x] Run -> expect RED: `uv run pytest tests/unit/application/test_crypto_reporting.py -v -k "loan_repayment" --no-header -q`

### Task 7: Implement `_extract_loan_repayment_fingerprints()`

Files:
- `../../../src/shares_reporting/application/crypto_reporting.py`

- [x] Add import for `TaxJurisdictionConfig` from `..infrastructure.config`
- [x] Implement `_extract_loan_repayment_fingerprints(transaction_history_path: Path | None) -> frozenset[tuple[str, str, str]]`:
  - If `transaction_history_path is None` or file does not exist, return `frozenset()`
  - Read rows via `_read_koinly_rows()`
  - Filter to `Type == "crypto_withdrawal"` AND `Tag` (case-insensitive) contains `"loan repayment"`
  - Parse date via `_parse_koinly_datetime` + `_format_datetime` to get `date_key`
  - Build `(date_key, _normalize_asset_ticker(sent_currency), _normalize_platform_name(sending_wallet))` for each matching row
  - Skip rows where date parsing fails (log warning) or sent_currency is empty
  - Return `frozenset(...)` of all tuples
- [x] Run -> expect GREEN for fingerprint tests: `uv run pytest tests/unit/application/test_crypto_reporting.py -v -k "extract_loan_repayment" --no-header -q`

### Task 8: Implement `_filter_loan_repayment_lots()`, `_flag_colocated_entries()`, and `_select_review_candidates()`

Files:
- `../../../src/shares_reporting/application/crypto_reporting.py`

- [x] Implement `_filter_loan_repayment_lots(entries: list[CryptoCapitalGainEntry], fingerprints: frozenset[tuple[str, str, str]]) -> tuple[list[CryptoCapitalGainEntry], list[CryptoCapitalGainEntry]]`:
  - Filter criterion: `(entry.disposal_date, entry.asset, entry.platform) in fingerprints AND entry.cost_eur == ZERO`
  - The `cost_eur == 0` check is essential: Koinly assigns zero cost to loan repayment disposals (basis stays with collateral). This discriminates loan repayments from legitimate sales sharing the same `(date, asset, platform)` key (premortem B-1)
  - Split entries into `kept` (does not match filter criterion) and `filtered` (matches)
  - Log warning with count of filtered entries when any are removed
  - Return `(kept, filtered)` tuple
- [x] Implement `_flag_colocated_entries(entries: list[CryptoCapitalGainEntry], fingerprints: frozenset[tuple[str, str, str]]) -> list[CryptoCapitalGainEntry]`:
  - For each remaining entry, check if `(entry.disposal_date, entry.asset, entry.platform)` matches any fingerprint
  - Use `dataclasses.replace()` to create new instances (frozen dataclass; premortem M-2):
    ```python
    dataclasses.replace(entry, review_required=True, review_reason=reason)
    ```
  - If match and `entry.review_required` is False, replace with `review_required=True` and `review_reason="Co-located with loan repayment disposal on same date/asset/platform; verify this is not a loan-related disposal that Koinly failed to tag"`
  - If match and `entry.review_required` is already True, replace with appended colocation reason to existing `review_reason`
  - Return new list with replaced instances
- [x] Implement `_select_review_candidates(filtered: list[CryptoCapitalGainEntry], threshold: Decimal) -> list[CryptoCapitalGainEntry]`:
  - From the filtered (removed) entries, select those where `cost_eur == 0` AND `abs(gain_loss_eur) >= threshold`
  - Use `dataclasses.replace()` to create new instances with flags (frozen dataclass; premortem M-2):
    ```python
    dataclasses.replace(entry, review_required=True, review_reason=f"Loan repayment disposal excluded per CIRS art. 10(20) but has zero cost basis (gain/loss: {entry.gain_loss_eur} EUR); verify Koinly tagging is correct")
    ```
  - Return the review candidates list
- [x] Run -> expect GREEN for filter tests: `uv run pytest tests/unit/application/test_crypto_reporting.py -v -k "filter_loan_repayment" --no-header -q`

### Task 9: Wire config-driven pipeline into `_parse_capital_gains_file()`

Files:
- `../../../src/shares_reporting/application/crypto_reporting.py`
- `../../../src/shares_reporting/main.py`

- [x] Modify `_parse_capital_gains_file()` signature to accept `jurisdiction: TaxJurisdictionConfig` and `transaction_history_path: Path | None = None`
- [x] Insert loan repayment filter into the pipeline **before aggregation and before country validation**, gated by `jurisdiction.exclude_loan_repayment_gains`:
  ```python
  loan_repayment_review: list[CryptoCapitalGainEntry] = []
  if jurisdiction.exclude_loan_repayment_gains:
      fingerprints = _extract_loan_repayment_fingerprints(transaction_history_path)
      if not fingerprints and transaction_history_path is None:
          logger.warning(
              "Loan repayment filter enabled (country=%s) but no transaction history file found; "
              "loan disposals will NOT be filtered",
              jurisdiction.country,
          )
      pre_loan_filter = len(capital_entries)
      capital_entries, filtered = _filter_loan_repayment_lots(capital_entries, fingerprints)
      loan_filtered = pre_loan_filter - len(capital_entries)
      logger.info(
          "Loan repayment filter: %d fingerprints extracted, %d lots matched and removed, %d lots retained",
          len(fingerprints),
          loan_filtered,
          len(capital_entries),
      )
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

  # Validate countries AFTER loan repayment filter; filtered entries don't need valid countries (premortem M-4)
  _validate_capital_entries_have_valid_countries(capital_entries)

  capital_entries = _aggregate_capital_entries(capital_entries)
  pre_filter_count = len(capital_entries)
  capital_entries = _filter_immaterial_entries(capital_entries)
  ```
- [x] Return `(capital_entries, loan_repayment_review)` tuple from `_parse_capital_gains_file()`
- [x] Add `loan_repayment_review: list[CryptoCapitalGainEntry] = field(default_factory=list)` to `CryptoTaxReport` dataclass (premortem M-3: concrete return contract)
- [x] Update `load_koinly_crypto_report()` signature to accept `jurisdiction: TaxJurisdictionConfig`, pass both `jurisdiction` and `transaction_history_file` to `_parse_capital_gains_file()`, unpack the tuple, and set `loan_repayment_review` on the returned `CryptoTaxReport`
- [x] Update `_load_crypto_tax_report()` in `main.py` to accept and pass `TaxJurisdictionConfig` from the loaded `Config`
- [x] Thread the config from the main pipeline: `Config.tax_jurisdiction` -> `_load_crypto_tax_report()` -> `load_koinly_crypto_report()` -> `_parse_capital_gains_file()`
- [x] Run -> expect GREEN for all loan repayment tests: `uv run pytest tests/unit/application/test_crypto_reporting.py -v -k "loan_repayment" --no-header -q`
- [x] Commit: `feat: wire config-driven loan repayment filter into capital gains pipeline`

### Task 10: Write failing tests and implement red background for zero-cost entries

Files:
- `../../../tests/unit/application/persisting/test_crypto_gains_sheet.py`
- `../../../src/shares_reporting/application/persisting/crypto_gains_sheet.py`

- [x] Write failing test: `test_render_zero_cost_entry_has_red_background` -- a `CryptoCapitalGainEntry` with `cost_eur == 0` AND `|gain_loss_eur| >= threshold` renders with `PatternFill(start_color="FFFF0000")` on all cells in that row, matching the shares placeholder-buy-date pattern in `ib_sheet.py`
- [x] Write failing test: `test_render_zero_cost_below_threshold_no_red_background` -- entry with `cost_eur == 0` AND `|gain_loss_eur| < threshold` renders without red background
- [x] Write failing test: `test_render_nonzero_cost_no_red_background` -- entry with `cost_eur > 0` renders without red background regardless of gain
- [x] Write failing test: `test_render_loan_repayment_review_row_has_red_background` -- a `CryptoCapitalGainEntry` from `loan_repayment_review` list (which has zero cost by construction) renders with red background
- [x] Write failing test: `test_render_normal_row_no_red_background` -- a regular `CryptoCapitalGainEntry` with valid cost basis renders without red background
- [x] Run -> expect RED: `uv run pytest tests/unit/application/persisting/test_crypto_gains_sheet.py -v -k "loan_repayment or zero_cost" --no-header -q`
- [x] Update `write_crypto_gains_sheet()` signature to accept `loan_repayment_review: list[CryptoCapitalGainEntry] = None` and `zero_basis_review_threshold: Decimal = Decimal("50")` (implemented via CryptoTaxReport fields per design invariant)
- [x] After rendering normal capital gains rows, render `loan_repayment_review` entries in the same table
- [x] Apply red row background to ANY row (normal or loan repayment review) where `cost_eur == 0` AND `|gain_loss_eur| >= zero_basis_review_threshold` (same pattern as `ib_sheet.py` lines 161-164: `PatternFill(start_color="FFFF0000", end_color="FFFF0000", fill_type="solid")` applied to all columns)
- [x] Review entries are included in the same table (not a separate section) so the user can review them in context with other disposals
- [x] Run -> expect GREEN: `uv run pytest tests/unit/application/persisting/test_crypto_gains_sheet.py -v -k "loan_repayment or zero_cost" --no-header -q`
- [x] Commit: `feat: render zero-cost entries with red background in crypto gains sheet`

### Task 11: Write failing tests and implement Loan Activity sheet

Files:
- `../../../tests/unit/application/persisting/test_loan_activity_sheet.py` *(new)*
- `../../../src/shares_reporting/application/persisting/loan_activity_sheet.py` *(new)*
- `../../../src/shares_reporting/application/crypto_reporting.py`
- `../../../src/shares_reporting/application/persisting/workbook_builder.py`

- [x] Write failing test: `test_loan_activity_shows_per_asset_balance` -- loan activity data with SUI receipts and repayments produces a table with per-asset rows showing received amount, repaid amount, and balance
- [x] Write failing test: `test_loan_activity_flags_overpaid` -- when more repaid than received for an asset, the balance row shows "Overpaid (cross-year loan?)" indicator with explanation text
- [x] Write failing test: `test_loan_activity_flags_open_loan` -- when more received than repaid, the balance row shows "Open loan" indicator
- [x] Write failing test: `test_loan_activity_empty_when_no_loan_transactions` -- no loan transactions produces an empty sheet with header only
- [x] Run -> expect RED: `uv run pytest tests/unit/application/persisting/test_loan_activity_sheet.py -v --no-header -q`
- [x] Add `LoanActivityEntry` dataclass to `crypto_reporting.py`:
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
- [x] Add `_extract_loan_activity(transaction_history_path: Path | None) -> list[LoanActivityEntry]` to `crypto_reporting.py`:
  - Read transaction history, filter rows tagged "Loan" (receipts) and "Loan repayment" (repayments)
  - Aggregate per asset: count, total amount, total EUR value
  - Compute balance and status
  - Return sorted by asset
- [x] Add `loan_activity` field to `CryptoTaxReport` dataclass (alongside `loan_repayment_review` added in Task 9)
- [x] Wire `_extract_loan_activity()` call into `load_koinly_crypto_report()` alongside fingerprint extraction
- [x] Create `loan_activity_sheet.py` with `write_loan_activity_sheet()`:
  - Headers: Asset, Received Count, Received Amount, Received Value (EUR), Repaid Count, Repaid Amount, Repaid Value (EUR), Balance Amount, Status
  - Per-asset row from `LoanActivityEntry`
  - "Overpaid" rows get light-red background (`FFCCCC`)
  - Summary row at bottom with totals
- [x] Wire into `workbook_builder.py`: add `write_loan_activity_sheet(workbook, crypto_tax_report)` call after reconciliation sheet; pass `crypto_tax_report.loan_activity`
- [x] Run -> expect GREEN: `uv run pytest tests/unit/application/persisting/test_loan_activity_sheet.py -v --no-header -q`
- [x] Commit: `feat: add Loan Activity sheet with per-asset balance and shortfall detection`

### Task 12: Final validation

- [x] Run full unit test suite: `uv run pytest tests/unit/ -v --tb=short`
- [x] Run full test suite: `uv run pytest --tb=short`
- [x] Verify no formatting-only changes: `git diff`
- [x] Verify decision-points structure is complete: read `../../tax/decision_points/2025.md` and `../../tax/decision_points/README.md`
- [x] Verify `sources.md` enrichment has effective/superseded metadata for all PT sources

### Task 13: Premortem and plan review compliance audit

Ref: `../../reviews/2026-05-26-premortem-filter-loan-repayment-gains.md`
Ref: `../../reviews/2026-05-26-plan-review-filter-loan-repayment-gains.md`

This task verifies that all premortem AND plan review findings are addressed in the final implementation.
Run AFTER all other tasks are complete. If any check fails, fix the code before marking the plan done.

**Premortem findings:**

- [x] **B-1 (over-filtering):** Verify `_filter_loan_repayment_lots()` uses BOTH `(date, asset, platform) in fingerprints` AND `cost_eur == ZERO` as the filter criterion. Run:
  ```bash
  uv run pytest tests/unit/application/test_crypto_reporting.py -v -k "partial_match_only_removes_matching" --no-header -q
  ```
  Must pass: the test has two entries on the same `(date, asset, platform)`, only the one with `cost_eur=0` should be filtered.
- [x] **M-1 (silent no-op):** Grep for the warning message when filter is enabled but no transaction history:
  ```bash
  grep -n "Loan repayment filter enabled.*but no transaction history" src/shares_reporting/application/crypto_reporting.py
  ```
  Must find exactly one match. Write a test if none exists:
  ```bash
  uv run pytest tests/unit/application/test_crypto_reporting.py -v -k "no_transaction_history" --no-header -q
  ```
- [x] **M-2 (frozen dataclass):** Verify no direct attribute assignment on `CryptoCapitalGainEntry` in the new functions. Grep must find zero hits:
  ```bash
  grep -n "entry\.\(review_required\|review_reason\) =" src/shares_reporting/application/crypto_reporting.py | grep -v "dataclasses.replace\|replace("
  ```
  Verify `dataclasses.replace()` is used:
  ```bash
  grep -n "replace(" src/shares_reporting/application/crypto_reporting.py | grep -c "flag_colocated\|select_review"
  ```
- [x] **M-3 (return contract):** Verify `CryptoTaxReport` has `loan_repayment_review` field:
  ```bash
  grep -n "loan_repayment_review" src/shares_reporting/application/crypto_reporting.py | head -5
  ```
  Must show the field definition in the dataclass AND population in `load_koinly_crypto_report()`.
- [x] **M-4 (validation order):** Verify `_validate_capital_entries_have_valid_countries()` is called AFTER the loan repayment filter block in `_parse_capital_gains_file()`. Read the function and confirm the call appears after the `if jurisdiction.exclude_loan_repayment_gains:` block closes, not before it.
- [x] **Mon-1 (observability):** Verify `logger.info` with fingerprint and match counts exists:
  ```bash
  grep -n "fingerprints extracted" src/shares_reporting/application/crypto_reporting.py
  ```
  Must find the info-level log line with counts.

**Plan review findings (new):**

- [x] **PR-B1 (counting mechanism):** Verify `_filter_loan_repayment_lots()` uses a counting approach: for each fingerprint key, removes at most N zero-cost lots where N = number of fingerprints for that key. Excess zero-cost lots are flagged `review_required=True`, not removed.
  - If not implemented: refactor from simple set-membership to `Counter`-based approach
  - Add test: `test_filter_loan_repayment_lots_limits_removal_to_fingerprint_count`: 3 zero-cost lots on same key but only 1 fingerprint, 1 removed, 2 flagged
  ```bash
  uv run pytest tests/unit/application/test_crypto_reporting.py -v -k "limits_removal_to_fingerprint_count" --no-header -q
  ```
- [x] **PR-B2 (existing test contradiction):** Fix `test_filter_loan_repayment_lots_removes_matching_entry` to use `cost_eur=Decimal("0")`. Add test `test_filter_loan_repayment_lots_keeps_nonzero_cost_matching_key` proving non-zero cost entries are never filtered.
  ```bash
  uv run pytest tests/unit/application/test_crypto_reporting.py -v -k "removes_matching_entry or keeps_nonzero_cost" --no-header -q
  ```
- [x] **PR-B3 (tuple return breaks tests):** Verify all `_parse_capital_gains_file()` callers in tests unpack the return tuple correctly. Check:
  ```bash
  grep -n "_parse_capital_gains_file(" tests/unit/application/test_crypto_reporting.py | head -10
  ```
  Each call site must unpack: `entries, review = _parse_capital_gains_file(...)` or `result = _parse_capital_gains_file(...); entries = result[0]`.
- [x] **PR-B4 (reconciliation mismatch):** Verify `CryptoReconciliationSummary` either:
  (a) documents that `capital_rows` excludes review entries, or
  (b) has a `loan_repayment_review_rows` field.
  The reconciliation sheet should note filtered count if loan entries were removed.
- [x] **PR-B5 (threshold wiring):** Verify `zero_basis_review_threshold` is accessible to the sheet writer. Check:
  ```bash
  grep -n "zero_basis_review_threshold" src/shares_reporting/application/persisting/crypto_gains_sheet.py
  ```
  Threshold should come from `CryptoTaxReport` (add field if missing), not a disconnected parameter with hardcoded default.
- [x] **PR-M1 (malformed repayment rows):** Verify `_extract_loan_repayment_fingerprints()` logs a warning when rows are skipped due to blank fields:
  ```bash
  grep -n "malformed\|skipped.*loan" src/shares_reporting/application/crypto_reporting.py
  ```
- [x] **PR-M4 (empty file warning):** Verify warning fires when file exists but yields 0 fingerprints (not just when path is None):
  ```bash
  grep -n "yielded 0\|no.*fingerprints" src/shares_reporting/application/crypto_reporting.py
  ```

- [x] If any check above failed, fix the implementation and re-run full loan repayment tests:
  ```bash
  uv run pytest tests/unit/application/test_crypto_reporting.py -v -k "loan_repayment" --no-header -q
  uv run pytest tests/unit/ -v --tb=short
  ```
