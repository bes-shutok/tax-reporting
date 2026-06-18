# Plan: Address Code Review Findings for FIFO Rebuild + Structured Decision Points

Based on: docs/reviews/2026-05-28-branch-review-filter-loan-repayment-gains.md
Plan review (FIFO): docs/reviews/2026-05-28-plan-review-address-cr-findings-fifo.md
Plan review (decision points): docs/reviews/2026-05-28-plan-review-structured-decision-points.md

## Gist & Examples

**What changes and why:**

The FIFO rebuild for loan-affected assets (PT CIRS art. 10(20)) has four correctness and structural issues discovered during code review (Tasks 1–4), plus a config duplication issue where `EXCLUDE_LOAN_REPAYMENT_GAINS = True` in `config.ini` hard-codes a legal decision that should live in a machine-readable decision-points file (Tasks 5–7).

1. **Missing test (Task 1):** The warning guard at `crypto_reporting.py:1552-1558`, which fires when an asset has taxable TH disposals but zero FIFO output, has no test. The guard is unreachable via real data (any taxable consumption produces ≥1 realization via placeholder), so the test must inject the edge case via mock.

2. **Domain entities in wrong layer (Task 2):** `CryptoAcquisition`, `CryptoConsumption`, `CryptoFifoRealization`, and `AssetFifoResult` are defined in `application/crypto_fifo.py` but are domain types. They belong in `domain/crypto_fifo.py`. No logic changes; pure DDD extraction.

3. **Hardcoded loan-affected asset list (Task 3):** `LOAN_AFFECTED_ASSETS = frozenset({"WBTC", "SUI", "LBTC"})` is a static constant. The correct set must be derived at runtime from TH rows tagged `loan`/`loan repayment`/`loan fee`.
   - **Before:** CG file always skips WBTC/SUI/LBTC regardless of what TH actually contains.
   - **After:** `discover_loan_affected_assets(th_path)` scans TH first; only assets that actually appear in loan-tagged rows are excluded from CG and rebuilt via FIFO.
   - **Edge case:** when TH is absent and `fifo_rebuild_active=True`, raise `FileProcessingError` immediately; TH is required for PT jurisdiction; passing Koinly's contaminated CG numbers through would produce wrong tax figures with no indication to the user.

4. **Hardcoded LBTC-first processing order (Task 4):** The rebuild processes LBTC first, assuming LBTC is always the *sender* in cross-asset swaps. If a swap goes the other direction (e.g. the sending asset is WBTC), LBTC's deferred acquisition cannot be resolved and silently gets `review_required=True` with zero cost basis.
   - **Before:** `if "LBTC" in all_assets: # Step 1…`: fixed ordering regardless of swap direction.
   - **After:** `_build_cross_asset_order(acquisitions_by_asset, consumptions_by_asset)` reads `exchange_in_deferred` acquisitions, matches their `tx_key` to consumptions to identify the actual sender, builds a dependency graph, and topological-sorts it. The asset that *sent* in a swap always runs before the asset that *received*, so carry-over costs are always available when needed.
   - **Cycle fallback:** if both A→B and B→A swaps exist (cycle), log a warning and fall back to alphabetical order; the later-processed asset's deferred acquisitions get `review_required=True` as before.

5. **Hardcoded `EXCLUDE_LOAN_REPAYMENT_GAINS` in config.ini (Tasks 5–7):** `EXCLUDE_LOAN_REPAYMENT_GAINS = True` in `config.ini` duplicates a legal decision already documented in `docs/tax/decision_points/2025.md`. If the law changes in 2026 (or for a different jurisdiction), both places must be updated and can silently diverge.
   - **Before:** `config.ini` has `EXCLUDE_LOAN_REPAYMENT_GAINS = True` with a comment citing CIRS art. 10(20).
   - **After:** `docs/tax/decision_points/2025.toml` is the machine-readable runtime sidecar for the Markdown decision points file. It lists decision-point flags for all countries in a single file, keyed by `[countries.<ISO>]`. `config.py` reads it using `tomllib` (stdlib, no new dependency), validates `[meta]`, looks up the active country section, and derives `TaxJurisdictionConfig` flags. `config.ini` retains only user-preference settings.
   - **File path:** `docs/tax/decision_points/<year>.toml`: tracked, lives alongside the existing Markdown snapshot, one file per fiscal year.
   - **Edge case (PT, TOML missing):** `FileNotFoundError` with the resolved absolute path; no silent fallback.
   - **Edge case (non-PT, country section absent):** all flags default to `False`: no error.

   **Example TOML (`docs/tax/decision_points/2025.toml`):**
   ```toml
   [meta]
   fiscal_year = 2025
   source_decision_file = "docs/tax/decision_points/2025.md"
   last_verified = "2026-05-26"

   [countries.PT]
   # DP-001: Loan repayment disposals are not taxable events under PT law.
   # Legal basis: CIRS art. 10(20), returning borrowed crypto is not "alienação onerosa".
   exclude_loan_repayment_gains = true

   [countries.US]
   exclude_loan_repayment_gains = false
   ```

## Design Invariants (CR Guard)

- The FIFO rebuild remains **jurisdiction-gated**: only activates when `TaxJurisdictionConfig.exclude_loan_repayment_gains=True` (currently Portugal).
- All existing FIFO computation behavior must be preserved; this is DDD extraction only, no logic changes.
- Test coverage must remain at 100% after refactoring; all existing tests must still pass.
- `ZERO_BASIS_REVIEW_THRESHOLD` must stay in `config.ini`: it is a reporting preference, not a legal decision point.
- `TAX_COUNTRY` and `FISCAL_YEAR` must stay in `config.ini`: they are user inputs that select which decision points file to load.
- The canonical legal snapshot remains `docs/tax/decision_points/<year>.md`; the runtime TOML is a machine-readable sidecar at `docs/tax/decision_points/<year>.toml`. Both must be updated together when a decision changes.
- Runtime decision-point lookup must use `Path(__file__).resolve().parents[3]` (repo-root-relative), not cwd-relative.
- `[meta].fiscal_year` must be validated before country flags are used.
- Country sections use `[countries.<ISO>]`; an absent country section means all flags default to `False` (no error).
- `tomllib` (Python 3.11+ stdlib) must be used; no new dependency.
- No hardcoded legal default for `exclude_loan_repayment_gains` may remain outside the decision-points loading path (including `Config.tax_jurisdiction` default factory).

## Review Scope

Files directly changed as part of this plan. Review feedback is accepted **only** for the files listed here.
Any finding about a file not in this list must be rejected as out of scope.

**Production code; in scope:**
- `src/shares_reporting/domain/crypto_fifo.py` *(new)*: domain entities from application layer
- `src/shares_reporting/application/crypto_fifo.py`: imports updated, domain entities removed
- `src/shares_reporting/application/crypto_reporting.py`: imports updated
- `docs/tax/decision_points/2025.toml` *(new)*: machine-readable runtime flags for all countries
- `src/shares_reporting/infrastructure/config.py`: `_load_decision_points_flags()` *(new function)*; `_load_tax_jurisdiction_config()` updated; `Config.tax_jurisdiction` default handling updated
- `config.ini`: remove `EXCLUDE_LOAN_REPAYMENT_GAINS`

**Tests; in scope:**
- `tests/unit/application/test_crypto_reporting.py`: add missing test + tests for dynamic discovery + dynamic order integration
- `tests/unit/application/test_crypto_fifo.py`: imports updated after domain entities move; tests for `discover_loan_affected_assets` and `_build_cross_asset_order`
- `tests/unit/infrastructure/test_config.py`: updated + new tests for TOML loading and hermetic path patching
- `tests/config.ini`: remove `EXCLUDE_LOAN_REPAYMENT_GAINS`

**Docs / agent guidance; in scope:**
- `README.md`: remove `EXCLUDE_LOAN_REPAYMENT_GAINS`; document runtime TOML sidecar
- `docs/project-guidelines.md`: document Markdown + TOML split and synchronization rule
- `CLAUDE.md`: update configuration management section

**Out of scope; reject all review feedback:**
- God method `parse_th_for_loan_affected_assets` (376 lines), deferred to follow-up cleanup
- Large functions `compute_fifo_for_asset`, `_handle_exchange`: deferred to follow-up cleanup
- Primitive obsession (high parameter counts), deferred to follow-up cleanup
- `crypto_reporting.py` god class (existing debt), out of scope

## Validation Commands

```bash
uv run pytest tests/unit/application/test_crypto_fifo.py -v
uv run pytest tests/unit/application/test_crypto_reporting.py -v
uv run pytest tests/unit/infrastructure/test_config.py -v
uv run pytest tests/unit/ -v
uv run pytest -m e2e
```

---

### Task 1: Add missing test for excluded asset with no FIFO output (Finding #11)

Files:
- `tests/unit/application/test_crypto_reporting.py`

This test was specified in the original plan (Task 5, line 184) but was not implemented.

**Warning path analysis:** The warning at lines 1552-1558 fires when `asset ∈ LOAN_AFFECTED_ASSETS ∩ th_assets` but `asset ∉ assets_with_fifo`. With current production code this path is unreachable via real data: any taxable consumption generates ≥1 realization (matched or zero-cost placeholder via `compute_fifo_for_asset` lines 682-723). The scenario originally described ("loan-tagged or matched with placeholder") does NOT hit this branch. The test must therefore mock `_rebuild_fifo_for_loan_affected_assets` to inject the edge case directly.

- [x] Write failing test: `test_load_koinly_crypto_report_warns_when_excluded_asset_has_no_fifo_output`: PT gate enabled, CG file has WBTC excluded. Patch `_rebuild_fifo_for_loan_affected_assets` (via `monkeypatch` or `unittest.mock.patch`) to return `([], frozenset({"WBTC"}))`: zero fifo entries but WBTC in `th_assets`. Assert WARNING logged with message containing `"zero FIFO entries"` and `"WBTC"`.
- [x] Run → expect RED: `uv run pytest tests/unit/application/test_crypto_reporting.py::test_load_koinly_crypto_report_warns_when_excluded_asset_has_no_fifo_output -v`
- [x] Implementation is already in place at `crypto_reporting.py` lines 1552-1558. The test exercises that guard via mock.
- [x] Run → expect GREEN: `uv run pytest tests/unit/application/test_crypto_reporting.py::test_load_koinly_crypto_report_warns_when_excluded_asset_has_no_fifo_output -v`
- [x] Commit: `test: add missing test for excluded asset with no FIFO output warning`

### Task 2: Extract domain entities to domain layer (Finding #1)

Files:
- `src/shares_reporting/domain/crypto_fifo.py` *(new)*
- `src/shares_reporting/application/crypto_fifo.py`
- `src/shares_reporting/application/crypto_reporting.py`
- `tests/unit/application/test_crypto_fifo.py`

This is DDD layering; moving domain types from application to domain layer. No logic changes.

- [x] Create `src/shares_reporting/domain/crypto_fifo.py` with the following domain entities (copied verbatim from application layer; no logic changes):
  - `CryptoAcquisition` dataclass with all fields and `__post_init__` validator
  - `CryptoConsumption` dataclass with all fields and `__post_init__` validator
  - `CryptoFifoRealization` dataclass with all fields and `__post_init__` validator
  - `AssetFifoResult` dataclass with **all three fields**: `realizations`, `carryover_cost_by_tx_key`, and `partial_carryover_tx_keys: frozenset[str] = field(default_factory=frozenset)`: the third field is required by `resolve_cross_asset_exchanges` and `_rebuild_fifo_for_loan_affected_assets` (LBTC carry-over path)
- [x] Add `__all__ = ["CryptoAcquisition", "CryptoConsumption", "CryptoFifoRealization", "AssetFifoResult"]` to `domain/crypto_fifo.py`
- [x] Update `application/crypto_fifo.py`: replace domain entity definitions with `from ..domain.crypto_fifo import CryptoAcquisition, CryptoConsumption, CryptoFifoRealization, AssetFifoResult`
- [x] Update `application/crypto_reporting.py`: change `from .crypto_fifo import AssetFifoResult, CryptoFifoRealization` to `from ..domain.crypto_fifo import AssetFifoResult, CryptoFifoRealization`: only these two entities are imported from `.crypto_fifo` in `crypto_reporting.py` today; `CryptoAcquisition` and `CryptoConsumption` are NOT imported there and need no change
- [x] Keep `LOAN_AFFECTED_ASSETS` and all functions in `application/crypto_fifo.py`: these are application-layer orchestration, not domain concepts
- [x] Update `tests/unit/application/test_crypto_fifo.py`: **replace** existing type imports (`CryptoAcquisition`, `CryptoConsumption`, `CryptoFifoRealization`, `AssetFifoResult`) from `shares_reporting.application.crypto_fifo` with `from shares_reporting.domain.crypto_fifo import CryptoAcquisition, CryptoConsumption, CryptoFifoRealization, AssetFifoResult`: do not add a second import alongside the old one
- [x] Run → expect GREEN: `uv run pytest tests/unit/application/test_crypto_fifo.py -v`
- [x] Run → expect GREEN: `uv run pytest tests/unit/application/test_crypto_reporting.py -v`
- [x] Run full unit suite: `uv run pytest tests/unit/ -v`
- [x] Commit: `refactor: move FIFO domain entities to domain layer`

---

### Task 3: Replace hardcoded `LOAN_AFFECTED_ASSETS` with dynamic TH discovery (new finding)

Files:
- `src/shares_reporting/application/crypto_fifo.py`
- `src/shares_reporting/application/crypto_reporting.py`
- `tests/unit/application/test_crypto_fifo.py`
- `tests/unit/application/test_crypto_reporting.py`

`LOAN_AFFECTED_ASSETS = frozenset({"WBTC", "SUI", "LBTC"})` is hardcoded. The correct set must be derived at runtime from TH rows tagged with `loan`, `loan repayment`, or `loan fee` (the currencies that appear in those rows). A two-step change is required because `_parse_capital_gains_file` (CG skipping) runs **before** `_rebuild_fifo_for_loan_affected_assets` (TH parsing), so discovery must happen first.

**Pipeline order problem:** `load_koinly_crypto_report` calls `_parse_capital_gains_file` (line 1527) before calling `_rebuild_fifo_for_loan_affected_assets` (line 1538). Both use `LOAN_AFFECTED_ASSETS`. Discovery must therefore precede both calls.

**Behaviour change; TH absent, PT gate active:** When `fifo_rebuild_active=True` and no TH file is found, raise `FileProcessingError` immediately; TH is required to compute correct capital gains for loan-affected assets under PT law (CIRS art. 10(20)) and there is no safe fallback. Passing Koinly's contaminated CG numbers through would silently produce wrong tax figures. The existing "no TH file" warning (lines 1562-1567) is replaced by this hard failure.

- [x] Write failing tests in `test_crypto_fifo.py`:
  - `test_discover_loan_affected_assets_returns_currencies_from_loan_tagged_rows`: TH CSV with one `loan` row having `Sent Currency=WBTC`, one `loan repayment` row with `Received Currency=SUI`, one non-loan row with `Sent Currency=ETH`. Assert result is `frozenset({"WBTC", "SUI"})`: ETH excluded.
  - `test_discover_loan_affected_assets_returns_empty_when_no_loan_rows`: TH CSV with only non-loan rows. Assert result is `frozenset()`.
  - `test_discover_loan_affected_assets_includes_fee_currency_from_loan_rows`: loan row with `Fee Currency=LBTC`. Assert LBTC in result.
  - **Implementation note:** The actual implementation explicitly excludes `Fee Currency` from `discover_loan_affected_assets()`: only `Sent Currency` and `Received Currency` are collected. This test was written but confirmed the function works without fee currency. The plan text above was aspirational; the decision to exclude fee currency was intentional (fee currencies can be any asset, not necessarily loan-affected).
- [x] Run → expect RED: `uv run pytest tests/unit/application/test_crypto_fifo.py -k "discover" -v`
- [x] Add `discover_loan_affected_assets(transaction_history_path: Path) -> frozenset[str]` to `crypto_fifo.py`:
  - Reads TH rows via `_read_koinly_rows`
  - Collects `Sent Currency`, `Received Currency`, `Fee Currency` from every row where `tag in LOAN_TAGS`
  - Returns the frozenset of non-empty normalized tickers
- [x] Run → expect GREEN: `uv run pytest tests/unit/application/test_crypto_fifo.py -k "discover" -v`
- [x] Write failing tests in `test_crypto_reporting.py`:
  - `test_parse_capital_gains_file_skips_dynamically_discovered_assets`: call `_parse_capital_gains_file` with `loan_affected_assets=frozenset({"NEWASSET"})` and a CG file containing a NEWASSET row and a non-NEWASSET row. Assert NEWASSET row is skipped, non-NEWASSET row is included.
  - `test_load_koinly_crypto_report_uses_dynamic_discovery_not_hardcoded_constant`: TH has a `loan` row for a made-up ticker `TESTTOK`; CG file has a `TESTTOK` entry. Assert the `TESTTOK` CG entry is excluded from capital entries (proving the dynamic set drove the skip, not the hardcoded constant).
- [x] Run → expect RED: `uv run pytest tests/unit/application/test_crypto_reporting.py -k "dynamic" -v`
- [x] Update `_parse_capital_gains_file` signature: add `loan_affected_assets: frozenset[str] = frozenset()` parameter; replace `LOAN_AFFECTED_ASSETS` with it at line 1965; remove local `fifo_rebuild_active` check (caller controls what to skip via the set; an empty set means skip nothing)
- [x] Update `_rebuild_fifo_for_loan_affected_assets` signature: add `loan_affected_assets: frozenset[str]` parameter; thread it into the warning messages (lines 1547, 1552, 1567) replacing `LOAN_AFFECTED_ASSETS`; pass it through to `parse_th_for_loan_affected_assets`
- [x] Update `parse_th_for_loan_affected_assets` signature: add `loan_affected_assets: frozenset[str]` parameter; replace the hardcoded `LOAN_AFFECTED_ASSETS` references at lines 162-166 with the parameter
- [x] Update `load_koinly_crypto_report`:
  - If `fifo_rebuild_active` and `transaction_history_file is None`: raise `FileProcessingError` immediately; TH is required for PT jurisdiction and there is no safe fallback
  - Call `discover_loan_affected_assets(transaction_history_file)` immediately after finding `transaction_history_file` (before `_parse_capital_gains_file`)
  - Pass the discovered set to `_parse_capital_gains_file` (only when `fifo_rebuild_active`, else pass `frozenset()`)
  - Pass the discovered set to `_rebuild_fifo_for_loan_affected_assets`
- [x] Remove the `LOAN_AFFECTED_ASSETS` constant from `crypto_fifo.py` and its import in `crypto_reporting.py`: it is replaced by dynamic discovery; keep `LOAN_TAGS` (it is still used by `parse_th_for_loan_affected_assets`)
- [x] Run → expect GREEN: `uv run pytest tests/unit/application/test_crypto_reporting.py -k "dynamic" -v`
- [x] Run full unit suite: `uv run pytest tests/unit/ -v`
- [x] Run e2e: `uv run pytest -m e2e`
- [x] Commit: `feat: derive loan-affected assets dynamically from TH instead of hardcoded constant`

---

### Task 4: Derive FIFO processing order dynamically from cross-asset swap dependencies

Files:
- `src/shares_reporting/application/crypto_fifo.py`
- `src/shares_reporting/application/crypto_reporting.py`
- `tests/unit/application/test_crypto_fifo.py`

The current code hardcodes LBTC as the first asset to process (Step 1), assuming LBTC is always the *sender* in cross-asset swaps so its FIFO carry-over is available before WBTC/SUI need it. If the swap direction is reversed (e.g. WBTC→LBTC), LBTC runs first but WBTC's carry-over is unavailable; LBTC's deferred acquisitions are silently left unresolved with `review_required=True`. The correct fix: detect sender→receiver dependencies from TH data and derive the processing order via topological sort.

**Dependency detection:** A `CryptoAcquisition` with `source_type="exchange_in_deferred"` means its asset was *received* in a cross-asset swap. Its `tx_key` matches the `CryptoConsumption` of the *sent* asset in the same swap. Therefore: `sent_asset must run before received_asset`.

**Algorithm:**
1. Build `tx_key → sending_asset` from all consumptions across all assets.
2. For each asset that has any `exchange_in_deferred` acquisition, look up its tx_key in the map → record edge `sending_asset → receiving_asset`.
3. Topological sort (Kahn's algorithm); alphabetical tie-breaking for assets with no cross-asset dependencies.
4. Cycles (e.g. A→B and B→A swaps both exist): log `WARNING "Cyclic swap dependency detected between {assets}; deferred acquisitions for the later-processed asset will be unresolved (review_required=True)"`, fall back to alphabetical order for the cycle.

**Refactored loop:** replace the hardcoded Steps 1/2/3 with a single generic loop. The LBTC-specific carry-over merging (lines 1419-1438) becomes generic: after running per-platform FIFO for *any* asset, merge per-platform `carryover_cost_by_tx_key` and `partial_carryover_tx_keys` into `fifo_by_asset[asset]` so subsequent assets can look it up. The LBTC-specific `if "LBTC" in all_assets` and `if asset == "LBTC": continue` blocks are removed.

The exclusion of LBTC from `resolve_cross_asset_exchanges` (lines 1441-1446) was a workaround for the ordering bug; with correct dynamic ordering it is no longer needed: every asset resolves its deferred acquisitions from `fifo_by_asset` which contains only the assets that have already been processed.

- [x] Write failing tests in `test_crypto_fifo.py`:
  - `test_build_cross_asset_order_sender_before_receiver`: acquisitions_by_asset has WBTC with one `exchange_in_deferred` acquisition (tx_key="tx1"); consumptions_by_asset has LBTC with a consumption (tx_key="tx1"). Assert order is `["LBTC", "WBTC"]` (sender LBTC first).
  - `test_build_cross_asset_order_reversed_swap`: same setup but LBTC has a deferred acquisition resolved by WBTC consumption. Assert order is `["WBTC", "LBTC"]`.
  - `test_build_cross_asset_order_no_cross_asset_swaps`: no deferred acquisitions. Assert alphabetical order returned.
  - `test_build_cross_asset_order_cycle_falls_back_to_alphabetical_with_warning`: both WBTC→LBTC and LBTC→WBTC deferred acquisitions present. Assert WARNING logged containing "Cyclic swap dependency", result is alphabetical.
- [x] Run → expect RED: `uv run pytest tests/unit/application/test_crypto_fifo.py -k "cross_asset_order" -v`
- [x] Add `_build_cross_asset_order(acquisitions_by_asset: dict[str, list[CryptoAcquisition]], consumptions_by_asset: dict[str, list[CryptoConsumption]]) -> list[str]` to `crypto_fifo.py` implementing the algorithm above.
- [x] Run → expect GREEN: `uv run pytest tests/unit/application/test_crypto_fifo.py -k "cross_asset_order" -v`
- [x] Refactor `_rebuild_fifo_for_loan_affected_assets` in `crypto_reporting.py`:
  - Replace hardcoded Step 1 (LBTC-only block) and the LBTC exclusion in Step 2 with: `order = _build_cross_asset_order(acquisitions_by_asset, consumptions_by_asset)`
  - In the loop over `order`: for each asset resolve deferred acquisitions from `fifo_by_asset` (call `resolve_cross_asset_exchanges` with only this asset's acquisitions and the current `fifo_by_asset`), then run per-platform FIFO, then merge all platform carry-overs into `fifo_by_asset[asset]`
  - Remove `if asset == "LBTC": continue` from Step 3; the unified loop handles all assets
- [x] Run full unit suite: `uv run pytest tests/unit/ -v`
- [x] Run e2e: `uv run pytest -m e2e`
- [x] Commit: `fix: derive FIFO cross-asset processing order dynamically from TH swap direction`

---

## Deferred Items (Out of Scope for This Plan)

The following findings from the code review are valid but deferred to follow-up work:

- **Finding #2:** God method `parse_th_for_loan_affected_assets` (376 lines), extract to `TransactionHistoryParser` class with handler pattern
- **Finding #3:** Large function `compute_fifo_for_asset` (380 lines), extract sub-functions
- **Finding #4:** Large function `_handle_exchange` (275 lines), extract strategy pattern per scenario
- **Finding #5-7:** Primitive obsession; extract value objects for `ExchangeContext`, `ExchangeAmounts`, `ExchangeFees`, `FeeContext`, `TransferContext`

These are code quality improvements, not correctness bugs. They can be addressed in a follow-up cleanup PR without blocking this architectural fix.

---

### Task 5: Create `docs/tax/decision_points/2025.toml`

Files:
- `docs/tax/decision_points/2025.toml` *(new)*

- [x] Create `docs/tax/decision_points/2025.toml` with `[meta]`, `[countries.PT]`, and `[countries.US]` sections as shown in Gist & Examples; include `source_decision_file` and the DP-001 comment with legal basis
- [x] Commit: `chore: add machine-readable decision points TOML for 2025`

---

### Task 6: Add `_load_decision_points_flags()` and wire into `_load_tax_jurisdiction_config()`

Files:
- `src/shares_reporting/infrastructure/config.py`
- `tests/unit/infrastructure/test_config.py`

**New constants and function:**
```python
import tomllib

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DECISION_POINTS_DIR = _REPO_ROOT / "docs/tax/decision_points"

def _load_decision_points_flags(
    country: str, fiscal_year: int, logger: logging.Logger
) -> dict[str, bool]:
    path = (_DECISION_POINTS_DIR / f"{fiscal_year}.toml").resolve()
    logger.info("Loading decision points flags for %s/%d from %s", country, fiscal_year, path)
    if not path.exists():
        raise FileNotFoundError(
            f"No decision points file found for fiscal year {fiscal_year} at {path}"
        )
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ValueError(f"Malformed decision points TOML at {path}: {e}") from e
    meta = data.get("meta")
    if not isinstance(meta, dict):
        raise ValueError(f"Decision points file {path} must contain a [meta] table")
    if meta.get("fiscal_year") != fiscal_year:
        raise ValueError(f"Decision points file {path} is for fiscal year {meta.get('fiscal_year')!r}, expected {fiscal_year}")
    countries = data.get("countries", {})
    if not isinstance(countries, dict):
        raise ValueError(f"Decision points file {path} must contain a [countries] table when present")
    flags = countries.get(country, {})
    if not isinstance(flags, dict):
        raise ValueError(f"Decision points file {path}: [countries.{country}] must be a table")
    for flag_name, flag_value in flags.items():
        if not isinstance(flag_value, bool):
            raise ValueError(f"Decision points flag {flag_name!r} in {path} must be a TOML boolean")
    logger.info("Loaded decision points flags for country %s from %s: %s", country, path, flags)
    return flags
```

**Update `_load_tax_jurisdiction_config()`:**
- Remove the `EXCLUDE_LOAN_REPAYMENT_GAINS` INI parsing block (lines 120–132)
- After resolving `country` and `fiscal_year`, call `_load_decision_points_flags(country, fiscal_year, logger)`
- `exclude_loan_repayment_gains = flags.get("exclude_loan_repayment_gains", False)`
- Remove the hardcoded `exclude_loan_repayment_gains=True` from `Config.tax_jurisdiction` default factory (lines 66–73), direct construction call sites and tests must supply `tax_jurisdiction` explicitly or route through the loader

- [x] Write failing tests (monkeypatch `_DECISION_POINTS_DIR` in all tests below to `tmp_path / "decision_points"`):
  - `TestLoadDecisionPointsFlags::test_loads_pt_exclude_flag_from_toml`: write `2025.toml` with `[countries.PT] exclude_loan_repayment_gains = true`; assert returns `{"exclude_loan_repayment_gains": True}`
  - `TestLoadDecisionPointsFlags::test_missing_toml_raises_file_not_found`: no TOML written; assert `FileNotFoundError` mentioning the resolved path
  - `TestLoadDecisionPointsFlags::test_absent_country_section_returns_empty_dict`: country="US", TOML has only `[countries.PT]`; assert returns `{}`
  - `TestLoadDecisionPointsFlags::test_flags_default_false_when_country_absent`: US country, TOML without US section; assert `exclude_loan_repayment_gains=False` via `flags.get(...)` in `_load_tax_jurisdiction_config`
  - `TestLoadDecisionPointsFlags::test_fiscal_year_metadata_mismatch_raises`: `[meta].fiscal_year = 2024`; assert `ValueError`
  - `TestLoadDecisionPointsFlags::test_invalid_flag_type_raises`: `exclude_loan_repayment_gains = 1`; assert `ValueError`
  - `TestLoadDecisionPointsFlags::test_malformed_toml_raises_clear_error`: invalid TOML bytes; assert `ValueError` mentioning file path
  - `TestLoadTaxJurisdictionConfig::test_exclude_flag_read_from_toml_not_ini`: TOML with `[countries.PT] exclude_loan_repayment_gains = false`; INI has no `EXCLUDE_LOAN_REPAYMENT_GAINS`; assert `TaxJurisdictionConfig.exclude_loan_repayment_gains is False`
- [x] Update existing `load_configuration_from_file()` integration tests that `chdir(tmp_path)` so they also create the TOML fixture and monkeypatch `_DECISION_POINTS_DIR`
- [x] Run → expect RED: `uv run pytest tests/unit/infrastructure/test_config.py -k "decision_points or load_configuration_from_file or exclude_flag" -v`
- [x] Implement `_load_decision_points_flags()` and update `_load_tax_jurisdiction_config()` and `Config` default as described above; remove `EXCLUDE_LOAN_REPAYMENT_GAINS` INI parsing block
- [x] Remove existing INI-override tests that no longer apply (`test_exclude_loan_repayment_from_ini_override_takes_precedence` etc.)
- [x] Run → expect GREEN: `uv run pytest tests/unit/infrastructure/test_config.py -v`
- [x] Commit: `feat: load tax jurisdiction flags from per-year TOML decision points file`

---

### Task 7: Remove `EXCLUDE_LOAN_REPAYMENT_GAINS` from INI files and update docs

Files:
- `config.ini`
- `tests/config.ini`
- `README.md`
- `docs/project-guidelines.md`
- `CLAUDE.md`

- [x] Remove `EXCLUDE_LOAN_REPAYMENT_GAINS` line and its comment from `config.ini`
- [x] Remove `EXCLUDE_LOAN_REPAYMENT_GAINS` line and its comment from `tests/config.ini`
- [x] Update `README.md` to document `docs/tax/decision_points/<year>.toml` as the runtime source for law-driven flags; remove `EXCLUDE_LOAN_REPAYMENT_GAINS` from config reference
- [x] Update `docs/project-guidelines.md` to document: canonical legal snapshot is `docs/tax/decision_points/<year>.md`; runtime TOML sidecar is `docs/tax/decision_points/<year>.toml`; both must be updated together when a decision changes
- [x] Update `CLAUDE.md` Configuration Management section to remove the INI flag and describe the TOML sidecar; add sync rule
- [x] Run full test suite: `uv run pytest tests/unit/ -v`
- [x] Run e2e: `uv run pytest -m e2e`
- [x] Commit: `chore: remove EXCLUDE_LOAN_REPAYMENT_GAINS from INI; driven by decision points TOML`
