# Plan: Refactor crypto_fifo.py — Extract Helpers and Decouple I/O

Plan review: `docs/reviews/2026-05-29-plan-review-crypto-fifo-refactor.md`

## Gist & Examples

**What changes:** Four pure-refactoring tasks that reduce the complexity of `crypto_fifo.py` without changing any behaviour. Each large function is split into a named orchestrator plus focused helpers, and the file-I/O call is moved out of the row-processing logic.

**Why needed:** The review of the `filter-loan-repayment-gains` branch flagged `crypto_fifo.py` (1885 lines, five functions each 100-400 lines) as a maintenance risk. All five large functions have `# noqa: PLR0912/PLR0915` suppressions, confirming the complexity was already noticed during development. As the file grows with future tax year changes or new asset types, the lack of internal seams will make changes increasingly risky. The four deferred findings are:
- **#2** `parse_th_for_loan_affected_assets` (396 lines) mixes CSV iteration, filtering, and row classification
- **#3** `_handle_exchange` (285 lines) mixes exchange-type classification, wallet resolution, and emission
- **#9** `compute_fifo_for_asset` (237 lines) mixes pool management, the matching loop, and realization generation
- **#4** DIP: `crypto_fifo.py` (application layer) calls `read_koinly_rows` (file I/O from infrastructure) inside the row-processing function

**Concrete before/after:**

*Task 1 — before:* `parse_th_for_loan_affected_assets` iterates rows, parses fields, dispatches to `_handle_exchange`/`_handle_transfer`, and classifies the row all in one 396-line function body.

*Task 1 — after:* the outer function handles iteration, error recovery, and dispatch; a new `_classify_th_row` function owns the per-row dispatch logic (lines ~220–527 condensed into a helper).

*Task 4 — before:* `parse_th_for_loan_affected_assets(path: Path, ...)` calls `read_koinly_rows(path)` on line 1 of its body, coupling file I/O to classification logic.

*Task 4 — after:* a new `_classify_rows_for_loan_affected_assets(rows, ...)` function owns the classification logic (no I/O); `parse_th_for_loan_affected_assets` becomes a thin wrapper that calls `read_koinly_rows` and delegates.

**Edge cases / constraints:**
- No behaviour change in any task — the full existing test suite is the sole verification signal.
- `noqa` suppressions on extracted helpers must be evaluated freshly; some may no longer be needed after extraction, others may still be needed on the extracted function.
- The public signatures of `parse_th_for_loan_affected_assets` and `compute_fifo_for_asset` must not change. For private helpers `_handle_exchange` and `_handle_transfer`, the invariant is: do not change any call signatures used by their current local callers within `crypto_fifo.py` — callers in `crypto_reporting.py` and tests in `test_crypto_fifo.py` must require zero changes.

---

## Review Scope

Files directly changed as part of this plan. Review feedback is accepted **only** for the files listed here.
Any finding about a file not in this list must be rejected as out of scope.

**Production code — in scope:**
- `src/shares_reporting/application/crypto_fifo.py` — all four extraction/refactoring tasks

**Tests — in scope:**
- `tests/unit/application/test_crypto_fifo.py` — Task 4 only: update direct `parse_th_for_loan_affected_assets` call-sites if the public signature changes (expected: no change)

**Out of scope — reject all review feedback:**
- `src/shares_reporting/application/crypto_reporting.py` — caller of the public API; should require zero changes
- All other files — no changes expected

---

## Validation Commands

```bash
uv run pytest tests/unit/application/test_crypto_fifo.py -x --tb=short -q
uv run pytest tests/unit/application/test_crypto_reporting.py -x --tb=short -q -k "fifo or loan or rebuild"
uv run ruff check src/shares_reporting/application/crypto_fifo.py
```

Run after every task commit. Include the `test_crypto_reporting.py` subset after Tasks 1 and 4 to catch integration regressions in the FIFO rebuild and review-flag propagation paths (`crypto_reporting.py:1442-1564`).

---

### Task 1: Extract _classify_th_row from parse_th_for_loan_affected_assets

Extract the per-row dispatch block (the inner body of the `for row_index, row in enumerate(rows)` loop after field parsing) into a private `_classify_th_row` helper function. The outer function becomes an iterator + error-recovery orchestrator.

Files:
- `src/shares_reporting/application/crypto_fifo.py`

**New function signature:**
```python
def _classify_th_row(
    *,
    row: dict[str, str],
    row_index: int,
    date_str: str,
    tx_key: str,
    row_type: str,
    sent_currency: str,
    received_currency: str,
    fee_currency: str,
    sent_amount: Decimal,
    received_amount: Decimal,
    sent_cost_basis: Decimal,
    net_value: Decimal,
    fee_amount: Decimal,
    fee_value: Decimal,
    sent_affected: bool,
    received_affected: bool,
    fee_affected: bool,
    loan_affected_assets: frozenset[str],
    acquisitions: dict[str, list[AcquisitionContext]],
    consumptions: dict[str, list[ConsumptionContext]],
    phantom_sending_transfers: set[tuple[str, str, str]],
) -> None: ...
```

**Outer function after extraction:**
```python
def parse_th_for_loan_affected_assets(path, loan_affected_assets):
    rows = read_koinly_rows(path)
    acquisitions, consumptions, phantom, failures = {}, {}, set(), {}
    for row_index, row in enumerate(rows, start=1):  # 1-based index preserved
        # pre-parse skip (LOAN_TAGS, affectedness) stays here — before field parsing
        ...
        try:
            # field parsing
            ...
        except ValueError as exc:
            # parse-failure attribution to affected assets stays here
            continue
        _classify_th_row(row=row, row_index=row_index, ..., acquisitions=acquisitions, ...)
    return acquisitions, consumptions, frozenset(phantom), failures
```

**Invariants that must be preserved (do not move to `_classify_th_row`):**
- `enumerate(rows, start=1)` — `row_index` is 1-based; used in composite tx keys and FIFO ordering.
- LOAN_TAGS skip and affectedness check execute *before* field parsing — this order must not change.
- The `try/except ValueError` error boundary stays in the orchestrator; `parse_failures_by_asset` attribution happens in the except handler (not inside the helper).
- `phantom_sending_transfers` accumulation: the set is passed into `_classify_th_row` and mutated there, same as `acquisitions`/`consumptions` — no change needed.

**Existing characterization tests to verify remain GREEN after extraction** (reference these in each run):
- `TestParseTh#test_parse_error_records_asset_and_row_index` — given a TH row with unparseable decimal, expects `parse_failures_by_asset` maps the affected asset to the failing row index
- `TestParseTh#test_parse_error_on_fee_only_row_attributes_fee_asset` — given a parse error on a fee-only affected row, expects the fee asset (not principal sides) is recorded in `parse_failures_by_asset`
- `TestParseTh#test_parse_error_on_unrecognised_asset_does_not_pollute_parse_failures` — given a parse error on a row with no loan-affected asset, expects `parse_failures_by_asset` remains empty

**Missing test to add before extraction** (ADD → run → expect GREEN to establish baseline):
- `TestBuildCompositeTxKey#test_duplicate_no_txhash_rows_get_unique_tx_keys` — given two TH rows with identical content (same date, wallets, amounts, currencies) but empty TxHash, expects each row produces a distinct tx_key (confirmed by `row_index` suffix in `_build_composite_tx_key`)

- [x] Add `TestBuildCompositeTxKey#test_duplicate_no_txhash_rows_get_unique_tx_keys` — call `_build_composite_tx_key` directly with two identical row dicts at row_index=1 and row_index=2; assert the two keys differ.
- [x] Run → expect GREEN (characterization: captures existing `_build_composite_tx_key` behaviour before refactor).
- [x] Verify `parse_th_for_loan_affected_assets` currently passes all existing tests: `uv run pytest tests/unit/application/test_crypto_fifo.py -x -q`
- [x] Extract the inner dispatch block into `_classify_th_row` with the signature above; leave the outer function as the orchestrator.
- [x] Confirm pre-parse skips and error-attribution logic remain in the orchestrator, not in the helper.
- [x] Remove `# noqa: PLR0912, PLR0915` from `parse_th_for_loan_affected_assets` if the extracted function no longer triggers them; add them to `_classify_th_row` only if needed.
- [x] Run → expect GREEN: `uv run pytest tests/unit/application/test_crypto_fifo.py -x -q && uv run pytest tests/unit/application/test_crypto_reporting.py -x -q -k "fifo or loan or rebuild"`
- [x] Lint: `uv run ruff check src/shares_reporting/application/crypto_fifo.py`
- [x] Commit: `refactor: extract _classify_th_row from parse_th_for_loan_affected_assets`

---

### Task 2: Extract emission helpers from _handle_exchange

`_handle_exchange` has four top-level branches based on which sides of the exchange are loan-affected. Extract each branch body into a focused helper.

Files:
- `src/shares_reporting/application/crypto_fifo.py`

**New helpers** (four branches confirmed at lines 1241, 1351, 1413, 1470):
- `_emit_cross_asset_exchange(...)` — `sent_affected and received_affected` (cross-asset crypto swap with deferred acquisition; covers crypto-to-crypto and wrapped-asset swaps)
- `_emit_received_only_exchange(...)` — `received_affected and not sent_affected` (any exchange where only the received side is loan-affected; covers fiat-to-crypto, crypto-to-crypto, and deposit-like flows)
- `_emit_sent_only_exchange(...)` — `sent_affected and not received_affected` (any exchange where only the sent side is loan-affected; covers crypto-to-fiat and crypto-to-crypto disposal flows)
- `_emit_fee_only_exchange(...)` — `fee_affected and not sent_affected and not received_affected` (fee disposal in a loan-affected asset when neither principal side is affected)

**After extraction, `_handle_exchange` body structure:**
```python
def _handle_exchange(...) -> None:
    wallet = ...
    platform = ...
    sending_platform = ...
    if sent_affected and received_affected:
        _emit_cross_asset_exchange(...)
    elif received_affected and not sent_affected:
        _emit_received_only_exchange(...)
    elif sent_affected and not received_affected:
        _emit_sent_only_exchange(...)
    elif fee_affected and not sent_affected and not received_affected:
        _emit_fee_only_exchange(...)
```

- [x] Verify `_handle_exchange` currently passes all existing tests (specifically `TestClassifyExchange*`).
- [x] Extract all four helpers; `_handle_exchange` becomes a dispatcher.
- [x] Remove `# noqa: PLR0913` from `_handle_exchange` if no longer needed; re-evaluate suppressions on extracted helpers.
- [x] Run → expect GREEN: `uv run pytest tests/unit/application/test_crypto_fifo.py -x -q`
- [x] Lint: `uv run ruff check src/shares_reporting/application/crypto_fifo.py`
- [x] Commit: `refactor: extract emission helpers from _handle_exchange`

---

### Task 3: Extract _match_consumption_to_lots from compute_fifo_for_asset

The FIFO deque loop inside `compute_fifo_for_asset` (approximately lines 565–763) owns the lot-matching algorithm. Extract it into `_match_consumption_to_lots` so the outer function handles sorting, pool construction, and result assembly.

Files:
- `src/shares_reporting/application/crypto_fifo.py`

**New function signature:**
```python
def _match_consumption_to_lots(
    con: ConsumptionContext,
    pool: deque[tuple[AcquisitionContext, Decimal]],
    asset: str,
    platform: str,
    carryover_cost_by_tx_key: dict[str, Decimal],
    partial_tx_keys: set[str],
) -> list[CryptoFifoRealization]: ...
```

The helper **mutates** `pool` (lots consumed), `carryover_cost_by_tx_key` (records deferred cost for non-taxable pool-exhausted events), and `partial_tx_keys` (marks transactions with incomplete carryover). Returns the realizations generated for this consumption event. The outer function iterates consumptions, calls the helper, and accumulates the returned realizations.

**Outer function after extraction:**
```python
def compute_fifo_for_asset(acquisitions, consumptions, asset, platform) -> AssetFifoResult:
    # ... validation ...
    sorted_acqs = sorted(...)
    sorted_cons = sorted(...)
    pool: deque[...] = deque(...)
    carryover_cost_by_tx_key: dict[str, Decimal] = {}
    partial_tx_keys: set[str] = set()
    realizations: list[CryptoFifoRealization] = []
    for con in sorted_cons:
        realizations.extend(_match_consumption_to_lots(con, pool, asset, platform,
                                                       carryover_cost_by_tx_key, partial_tx_keys))
    return AssetFifoResult(
        realizations=realizations,
        carryover_cost_by_tx_key=carryover_cost_by_tx_key,
        partial_carryover_tx_keys=frozenset(partial_tx_keys),
    )
```

**Existing characterization tests to verify remain GREEN after extraction:**
- `TestFifoBasic#test_zero_cost_placeholder_with_review` — given empty pool and a taxable consumption, expects a zero-cost realization with `review_required=True` and "pool exhausted" in `review_reason`
- `TestFifoCrossAssetCarryOver#test_lbtc_carry_over_becomes_wbtc_acquisition_cost` — given a non-taxable LBTC-to-WBTC exchange, expects `carryover_cost_by_tx_key` carries the cost to the deferred WBTC acquisition
- `TestFifoPartialTransferCarryOver#test_partial_transfer_marks_receiver_review_required` — given a non-taxable transfer where the sender pool is exhausted mid-way, expects the tx_key appears in `partial_carryover_tx_keys` and the receiver lot is flagged `review_required`

- [x] Verify `compute_fifo_for_asset` currently passes all `TestFifo*` tests.
- [x] Extract the deque-loop body into `_match_consumption_to_lots` with the signature above (including `partial_tx_keys` mutation).
- [x] Confirm the helper correctly handles both the taxable pool-exhausted path (placeholder realization + warning) and the non-taxable pool-exhausted path (`carryover_cost_by_tx_key[tx_key] = ZERO` + `partial_tx_keys.add`).
- [x] Remove `# noqa: PLR0912, PLR0915` from `compute_fifo_for_asset` if no longer needed.
- [x] Run → expect GREEN: `uv run pytest tests/unit/application/test_crypto_fifo.py -x -q`
- [x] Lint: `uv run ruff check src/shares_reporting/application/crypto_fifo.py`
- [x] Commit: `refactor: extract _match_consumption_to_lots from compute_fifo_for_asset`

---

### Task 4: Decouple file I/O from row classification (DIP fix)

`parse_th_for_loan_affected_assets` calls `read_koinly_rows(path)` as its first line, coupling the application-layer classification logic to the infrastructure-layer file reader. Extract the row-processing logic into a private `_classify_rows_for_loan_affected_assets(rows, ...)` function. The public function becomes a thin wrapper. This makes the classification logic testable without touching the file system, and respects the application → infrastructure dependency direction.

**Note:** `parse_koinly_decimal`, `parse_koinly_datetime`, and `normalize_*` utilities remain imported from `koinly_parser` within `crypto_fifo.py` — they are pure parsing utilities with no I/O side effects and do not violate DIP. Only the `read_koinly_rows` file-I/O call is moved.

Files:
- `src/shares_reporting/application/crypto_fifo.py`

**After extraction:**
```python
def parse_th_for_loan_affected_assets(
    transaction_history_path: Path,
    loan_affected_assets: frozenset[str] = frozenset(),
) -> tuple[...]:
    """Thin wrapper: reads CSV rows and delegates to _classify_rows_for_loan_affected_assets."""
    rows = read_koinly_rows(transaction_history_path)
    return _classify_rows_for_loan_affected_assets(rows, loan_affected_assets)


def _classify_rows_for_loan_affected_assets(
    rows: Sequence[dict[str, str]],
    loan_affected_assets: frozenset[str] = frozenset(),
) -> tuple[...]:
    """Core classification logic — operates on pre-loaded rows, no file I/O."""
    ...
```

- [x] Add `from collections.abc import Sequence` to imports (already available via `__future__` annotations, but explicit import needed for runtime use).
- [x] Extract the body of `parse_th_for_loan_affected_assets` (post-Task-1, i.e. after `_classify_th_row` is extracted) into `_classify_rows_for_loan_affected_assets(rows, loan_affected_assets)`; make `parse_th_for_loan_affected_assets` a one-liner wrapper.
- [x] Confirm `_classify_rows_for_loan_affected_assets` body preserves the same invariants as Task 1: `enumerate(rows, start=1)`, pre-parse skips before field parsing, `parse_failures_by_asset` attribution in the except handler (not in any extracted helper), and `phantom_sending_transfers` mutation.
- [x] Verify public signature of `parse_th_for_loan_affected_assets` is unchanged — all existing tests in `test_crypto_fifo.py` that pass a `Path` must continue to work without modification.
- [x] Run → expect GREEN: `uv run pytest tests/unit/application/test_crypto_fifo.py -x -q && uv run pytest tests/unit/application/test_crypto_reporting.py -x -q -k "fifo or loan or rebuild"`
- [x] Verify `crypto_reporting.py` requires zero changes: `uv run pytest tests/ -x -q`
- [x] Lint: `uv run ruff check src/shares_reporting/application/crypto_fifo.py`
- [x] Commit: `refactor: decouple file I/O from row classification in parse_th_for_loan_affected_assets`
