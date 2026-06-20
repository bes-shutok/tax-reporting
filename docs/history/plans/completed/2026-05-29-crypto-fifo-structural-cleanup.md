# Plan: Crypto FIFO Structural Cleanup; Rename, ParsedTxRow, Package Split

Addresses review findings F1 and F8 from
`docs/reviews/2026-05-29-branch-review-filter-loan-repayment-gains-v3.md`.

## Gist & Examples

**What changes:**
Three sequential structural refactors to the FIFO module and the entire package name:

1. **Package rename** (`shares_reporting` → `tax_reporting`): The project is named
   `tax-reporting` in `pyproject.toml` and processes both shares _and_ crypto. The current
   name `shares_reporting` is misleading and out of date. Mechanical rename; no logic
   change.

2. **`ParsedTxRow` dataclass** (F1): `_classify_th_row` has 22 keyword parameters.
   The 18 read-only fields parsed from the CSV row are grouped into a frozen
   `ParsedTxRow` dataclass. The 4 mutable accumulator collections stay as explicit
   parameters. The same carrier flows down to `_handle_exchange`, `_emit_*`, and
   `_handle_transfer`, collapsing their wide signatures in turn.

3. **`crypto_fifo.py` package split** (F8): The file is ~2186 lines and grew with every
   iteration. Split into a `crypto_fifo/` sub-package with four focused modules. Public
   callers (tests, `crypto_reporting.py`) import from `crypto_fifo` as before; only the
   internal organisation changes.

**Why needed:**
- `PLR0913` suppressions on 6+ functions signal that parameter explosion is a structural
  smell, not a one-off exception.
- 2186-line files slow navigation and make future review harder. The domain dataclasses in
  `domain/crypto_fifo.py` already model the right boundaries; the application layer should
  mirror them.
- `shares_reporting` appears in 236 import statements across 36 files. The mismatch
  between the module name and the project name (`tax-reporting`) creates confusion.

**Before / After; ParsedTxRow:**
```python
# Before (22 kw-params)
_classify_th_row(
    row=row, row_index=row_index, date_str=date_str, tx_key=tx_key,
    row_type=row_type, sent_currency=sent_currency, ...,  # 18 more
    acquisitions=acquisitions, consumptions=consumptions,
    parse_failures_by_asset=parse_failures_by_asset,
    phantom_sending_transfers=phantom_sending_transfers,
)

# After (5 params)
_classify_th_row(
    parsed_row,
    acquisitions, consumptions,
    parse_failures_by_asset, phantom_sending_transfers,
)
```

**Before / After; package split:**
```
# Before
src/shares_reporting/application/crypto_fifo.py   # 2186 lines

# After
src/tax_reporting/application/crypto_fifo/
├── __init__.py      # public re-exports (AcquisitionContext, ConsumptionContext,
│                    #   discover_loan_affected_assets, parse_th_for_loan_affected_assets,
│                    #   compute_fifo_for_asset, resolve_cross_asset_exchanges)
├── contexts.py      # AcquisitionContext, ConsumptionContext, ParsedTxRow
├── parsing.py       # _classify_rows_for_loan_affected_assets, _classify_th_row,
│                    #   _handle_exchange, _emit_*, _handle_transfer,
│                    #   _add_acquisition/_add_consumption/_add_cross_asset_fee_consumption,
│                    #   _build_composite_tx_key, _order_platforms_for_transfers,
│                    #   _resolve_intra_asset_transfers, discover_loan_affected_assets,
│                    #   parse_th_for_loan_affected_assets
├── matching.py      # compute_fifo_for_asset, _consume_against_pool_inplace,
│                    #   _build_taxable_realization, _compute_holding_period
└── cross_asset.py   # resolve_cross_asset_exchanges, _build_cross_asset_order,
                     #   _lookup_carryover_cost, _apply_receiver_proportional_split
```

**Shares FIFO note:** `transformation.py` is 375 lines with two functions; no split
needed. `crypto_reporting.py` at 2455 lines is a future candidate (separate ticket).

**Edge cases handled:**
- `__init__.py` must re-export all symbols that external callers currently import.
  Any missing re-export is a compile-time ImportError caught by the test run.
- `ParsedTxRow` contains `loan_affected_assets: frozenset[str]` so helpers that
  currently accept it as a param can be simplified too.
- Circular imports: `contexts.py` must not import from `parsing.py`, `matching.py`, or
  `cross_asset.py`. Those three may all import from `contexts.py`.

---

## Review Scope

Files directly changed as part of this plan. Review feedback is accepted **only** for
the files listed here. Any finding about a file not in this list must be rejected as out
of scope.

**Production code; in scope:**
- `pyproject.toml`: package rename
- `src/tax_reporting/` *(new directory tree; all files)*
- `src/tax_reporting/application/crypto_fifo/__init__.py` *(new)*
- `src/tax_reporting/application/crypto_fifo/contexts.py` *(new)*
- `src/tax_reporting/application/crypto_fifo/parsing.py` *(new)*
- `src/tax_reporting/application/crypto_fifo/matching.py` *(new)*
- `src/tax_reporting/application/crypto_fifo/cross_asset.py` *(new)*

**Tests; in scope:**
- `tests/unit/application/test_crypto_fifo.py`: import path update + new `ParsedTxRow`
  construction test

**Out of scope; reject all review feedback:**
- `src/tax_reporting/application/transformation.py`: 375 lines; no structural split needed
- `src/tax_reporting/application/crypto_reporting.py`: future split ticket; frozen here
- All other `src/tax_reporting/**` files; import-path-only changes, no logic change

---

## Validation Commands

```bash
uv run pytest -x --tb=short -q
uv run ruff check src/ tests/
```

---

### Task 1: Rename package `shares_reporting` → `tax_reporting`

This is a pure mechanical rename; no logic change. All 790 existing tests must stay
GREEN throughout.

Files:
- `pyproject.toml`
- `src/tax_reporting/` *(directory rename from `src/shares_reporting/`)*
- All `*.py` files under `src/` and `tests/` (import path updates)

- [x] Rename directory: `mv src/shares_reporting src/tax_reporting`
- [x] Update `pyproject.toml`:
  - `packages = ["src/shares_reporting"]` → `["src/tax_reporting"]`
  - entry point: `"shares_reporting.main:cli"` → `"tax_reporting.main:cli"`
  - `known-first-party = ["shares_reporting"]` → `["tax_reporting"]`
- [x] Update all `from shares_reporting.` / `import shares_reporting` occurrences in
  `src/` and `tests/` (236 sites across 36 files):
  `grep -r "shares_reporting" src/ tests/ --include="*.py" -l | xargs sed -i '' 's/shares_reporting/tax_reporting/g'`
- [x] Update `CLAUDE.md` if it references `shares_reporting` module paths
- [x] Run → expect GREEN: `uv run pytest -x --tb=short -q`
- [x] Run → expect clean: `uv run ruff check src/ tests/`
- [x] Commit: `refactor: rename package shares_reporting → tax_reporting`

---

### Task 2: Introduce `ParsedTxRow` dataclass (F1)

Reduces `_classify_th_row` from 22 keyword parameters to 5 by grouping the 18 read-only
CSV-derived fields into a frozen `ParsedTxRow` carrier. The same carrier flows to
`_handle_exchange`, the four `_emit_*` helpers, and `_handle_transfer`.

The 4 mutable accumulator collections (`acquisitions`, `consumptions`,
`parse_failures_by_asset`, `phantom_sending_transfers`) remain explicit parameters
because they are mutated in-place; they must not be bundled into an immutable dataclass.

Files:
- `src/tax_reporting/application/crypto_fifo.py`
- `tests/unit/application/test_crypto_fifo.py`

**`ParsedTxRow` fields (all 18 read-only):**
```python
@dataclass(frozen=True)
class ParsedTxRow:
    row: dict[str, str]          # raw CSV row (for wallet lookups in helpers)
    row_index: int
    date_str: str
    tx_key: str
    row_type: str
    sent_currency: str
    received_currency: str
    fee_currency: str
    sent_amount: Decimal
    received_amount: Decimal
    sent_cost_basis: Decimal
    net_value: Decimal
    fee_amount: Decimal
    fee_value: Decimal
    sent_affected: bool
    received_affected: bool
    fee_affected: bool
    loan_affected_assets: frozenset[str]
```

**New signatures (target):**
```python
def _classify_th_row(
    parsed_row: ParsedTxRow,
    acquisitions: dict[str, list[AcquisitionContext]],
    consumptions: dict[str, list[ConsumptionContext]],
    parse_failures_by_asset: dict[str, list[int]],
    phantom_sending_transfers: set[tuple[str, str, str]],
) -> None: ...

def _handle_exchange(
    parsed_row: ParsedTxRow,
    acquisitions: dict[str, list[AcquisitionContext]],
    consumptions: dict[str, list[ConsumptionContext]],
) -> None: ...

def _handle_transfer(
    parsed_row: ParsedTxRow,
    acquisitions: dict[str, list[AcquisitionContext]],
    consumptions: dict[str, list[ConsumptionContext]],
    phantom_sending_transfers: set[tuple[str, str, str]],
) -> None: ...

# _emit_* helpers: ParsedTxRow + wallet/platform (extracted by _handle_exchange locally)
# + acquisitions/consumptions; drop all individual currency/amount params
```

- [x] `TestParsedTxRow#test_parsedtxrow_is_frozen`: given a `ParsedTxRow` instance,
  expects `AttributeError` when attempting to mutate any field (frozen dataclass
  invariant)
- [x] `TestParsedTxRow#test_parsedtxrow_round_trips_all_fields`: given known field
  values, expects all 18 fields are accessible by name with correct types
- [x] Run → expect RED: `uv run pytest tests/unit/application/test_crypto_fifo.py -x -q`
- [x] Add `ParsedTxRow` dataclass to `crypto_fifo.py` (alongside
  `AcquisitionContext`/`ConsumptionContext`)
- [x] Refactor `_classify_rows_for_loan_affected_assets`: construct `ParsedTxRow` from
  the parsed fields, pass to `_classify_th_row`
- [x] Refactor `_classify_th_row` signature (22 → 5 params); remove `# noqa: PLR0913`
- [x] Refactor `_handle_exchange` signature; remove `# noqa: PLR0913`
- [x] Refactor `_emit_cross_asset_exchange`, `_emit_received_only_exchange`,
  `_emit_sent_only_exchange`, `_emit_fee_only_exchange` signatures
- [x] Refactor `_handle_transfer` signature; remove `# noqa: PLR0913`
- [x] Run → expect GREEN: `uv run pytest -x --tb=short -q`
- [x] Run → expect clean: `uv run ruff check src/tax_reporting/application/crypto_fifo.py`
- [x] Commit: `refactor: introduce ParsedTxRow to collapse wide keyword signatures`

---

### Task 3: Split `crypto_fifo.py` into `crypto_fifo/` package (F8)

Move functions into four focused modules. `__init__.py` re-exports the public API so all
external import sites remain unchanged.

Files:
- `src/tax_reporting/application/crypto_fifo/` *(new package directory)*
- `src/tax_reporting/application/crypto_fifo/__init__.py` *(new)*
- `src/tax_reporting/application/crypto_fifo/contexts.py` *(new)*
- `src/tax_reporting/application/crypto_fifo/parsing.py` *(new)*
- `src/tax_reporting/application/crypto_fifo/matching.py` *(new)*
- `src/tax_reporting/application/crypto_fifo/cross_asset.py` *(new)*
- `src/tax_reporting/application/crypto_fifo.py` *(deleted)*

**Module assignment:**

| Module | Functions / Classes |
|--------|---------------------|
| `contexts.py` | `AcquisitionContext`, `ConsumptionContext`, `ParsedTxRow` |
| `parsing.py` | `discover_loan_affected_assets`, `parse_th_for_loan_affected_assets`, `_classify_rows_for_loan_affected_assets`, `_classify_th_row`, `_handle_exchange`, `_emit_cross_asset_exchange`, `_emit_received_only_exchange`, `_emit_sent_only_exchange`, `_emit_fee_only_exchange`, `_handle_transfer`, `_add_acquisition`, `_add_consumption`, `_add_cross_asset_fee_consumption`, `_build_composite_tx_key`, `_order_platforms_for_transfers`, `_resolve_intra_asset_transfers` |
| `matching.py` | `compute_fifo_for_asset`, `_consume_against_pool_inplace`, `_build_taxable_realization`, `_compute_holding_period` |
| `cross_asset.py` | `resolve_cross_asset_exchanges`, `_build_cross_asset_order`, `_lookup_carryover_cost`, `_apply_receiver_proportional_split` |
| `__init__.py` | Re-exports: `AcquisitionContext`, `ConsumptionContext`, `discover_loan_affected_assets`, `parse_th_for_loan_affected_assets`, `compute_fifo_for_asset`, `resolve_cross_asset_exchanges` |

**Import dependency direction** (no cycles allowed):
```
contexts.py   ← (no imports from other crypto_fifo modules)
parsing.py    ← contexts.py
matching.py   ← contexts.py  (imports AcquisitionContext, ConsumptionContext)
cross_asset.py ← contexts.py, matching.py (for CryptoFifoRealization via domain import)
__init__.py   ← parsing.py, matching.py, cross_asset.py
```

- [x] `TestCryptoFifoPackageImports#test_public_api_importable_from_package`: given
  `from tax_reporting.application.crypto_fifo import AcquisitionContext,
  ConsumptionContext, discover_loan_affected_assets, parse_th_for_loan_affected_assets,
  compute_fifo_for_asset, resolve_cross_asset_exchanges`, expects no `ImportError`
- [x] `TestCryptoFifoPackageImports#test_no_circular_imports`: given importing all four
  sub-modules in isolation, expects each imports cleanly without circular dependency
  errors
- [x] Run → expect RED (ImportError): `uv run pytest tests/unit/application/test_crypto_fifo.py -x -q`
- [x] Create `src/tax_reporting/application/crypto_fifo/` directory
- [x] Create `contexts.py` with `AcquisitionContext`, `ConsumptionContext`, `ParsedTxRow`
- [x] Create `parsing.py` (parsing group; imports from `contexts.py` and
  `tax_reporting.infrastructure.koinly_parser`)
- [x] Create `matching.py` (matching group; imports from `contexts.py` and
  `tax_reporting.domain.crypto_fifo`)
- [x] Create `cross_asset.py` (cross-asset group; imports from `contexts.py`,
  `matching.py`, `tax_reporting.domain.crypto_fifo`)
- [x] Create `__init__.py` with explicit re-exports; verify all symbols previously
  importable from `crypto_fifo` are present
- [x] Delete `src/tax_reporting/application/crypto_fifo.py`
- [x] Verify no test references private symbols via the module path (internal helpers
  like `_consume_against_pool_inplace` used in `test_crypto_fifo.py` must update their
  import to the sub-module path)
- [x] Run → expect GREEN: `uv run pytest -x --tb=short -q`
- [x] Run → expect clean: `uv run ruff check src/ tests/`
- [x] Commit: `refactor: split crypto_fifo.py into crypto_fifo/ package`
