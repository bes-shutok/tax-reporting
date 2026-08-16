# Plan: On-chain tx tagger final sweep (F17 hoist + F18 small-N floor + F19 doc fix + F23 retry broaden)

Resolves the last 4 deferred non-blocking findings worth fixing, on branch
`2026-08-02-on-chain-tx-tagger` vs `master`. F16 (enum members) and
defense-in-depth-at-sink are explicitly out of scope (enum members are
intentional forward-looking; the config seam is the only RpcClient construction
path).

## Gist & Examples

Four small, independent fixes:

1. **F17 - Hoist `_UNKNOWN_DIRECTION_MAX_FRACTION`**: the constant is
   duplicated in `berachain_processor.py:93` and `integrity_invariants.py:120`
   with a "kept in sync" comment. Hoist it to ONE shared location (the domain
   module `on_chain_transaction.py`, which both infra modules already import)
   and import from there. Both checks stay (the processor's is the runtime guard;
   the integrity checker's is the post-run audit echo) - only the constant
   source changes.

2. **F18 - Small-N absolute floor on the unknown-direction rate gate**: today a
   SINGLE unknown-direction leg in a <=99-row wallet trips the 1% gate
   (1/99 = 1.01%) and aborts the whole opted-in run. The per-tx classifier
   already emits Unknown+review for individual unknown legs. Add a small-N
   absolute floor so the gate fires only when `unknown > threshold AND unknown >=
   _UNKNOWN_DIRECTION_MIN_ABSOLUTE` (e.g. 5). A single weird tx in a small
   wallet no longer aborts; a systemic decoder regression (many unknowns) still
   does.

3. **F19 - csv reader docstring fix**: `_parse_row`'s docstring claims "Fallible
   secondary parses (the int conversions) are wrapped" but only `fee_amount_raw`
   is actually in a nested try/except; the other int conversions (`amount_raw`,
   `block_number`) rely on the broad outer handler. Correct the docstring to
   match the implementation.

4. **F23 - Broaden rpc retry exception coverage**: `_rpc` retries
   `URLError`/`TimeoutError` but not `http.client.HTTPException` (broken pipe,
   connection reset). Now that rpc_client is wired (ON_CHAIN_RPC_URL), a
   transient TCP-level error aborts the run instead of retrying. Add
   `http.client.HTTPException` to the retried-exception tuple.

## Evaluation Criteria

- correctness: the hoisted constant has the same value in both modules; the
  small-N floor does not mask a systemic regression; the retry broadening does
  not retry non-transient errors.
- test coverage: a test pins the small-N floor (1 unknown in 50 rows does NOT
  abort; 5 unknowns in 50 rows DOES); a test pins the HTTPException retry.

**Done when:**
- All new RED tests pass; `uv run pytest -q` full suite green.
- `grep -rn '_UNKNOWN_DIRECTION_MAX_FRACTION' src/` shows the constant defined
  ONCE (in the domain module) and imported by both infra modules.
- The csv reader docstring matches the implementation.

**Ship when:** N/A (local-only).

## Review Scope

**Explicit must-fix:**
- `src/tax_reporting/domain/on_chain_transaction.py` (hoisted constant)
- `src/tax_reporting/infrastructure/on_chain/berachain_processor.py` (import the constant; add small-N floor)
- `src/tax_reporting/infrastructure/on_chain/integrity_invariants.py` (import the constant)
- `src/tax_reporting/infrastructure/on_chain/on_chain_csv_reader.py` (docstring fix)
- `src/tax_reporting/infrastructure/on_chain/rpc_client.py` (broaden retry tuple)
- `tests/unit/infrastructure/test_berachain_processor.py` (small-N floor test)
- `tests/unit/infrastructure/test_rpc_client.py` (HTTPException retry test)

**Out of scope:** F16 (enum members are intentional); defense-in-depth-at-sink.

## Design Invariants

- **The 1% threshold value is unchanged (0.01).** Only its source moves (hoist)
  and its discriminator gains a floor (small-N).
- **Both checks stay.** The processor's runtime guard AND the integrity checker's
  audit echo both remain; only the constant source and the floor change.
- **The retry broadening does not change the retry count or backoff.** Only the
  exception tuple widens.

## Validation Commands

```bash
uv run pytest tests/unit/infrastructure/test_berachain_processor.py \
  tests/unit/infrastructure/test_rpc_client.py \
  tests/unit/infrastructure/test_lp_autodiscovery.py \
  tests/end_to_end/test_on_chain_bera_opted_in.py \
  tests/end_to_end/test_on_chain_integrity_invariants.py -q

uv run pytest -q

# Constant defined ONCE (in domain), imported by both infra modules:
grep -rn '_UNKNOWN_DIRECTION_MAX_FRACTION.*=.*0.01' src/ | wc -l | grep -q '^1$' && echo "OK: single definition" || echo "FAIL: multiple definitions"
```

## Tasks

### Task 1: F17 + F18 - hoist constant + small-N floor

Files:
- `src/tax_reporting/domain/on_chain_transaction.py`
- `src/tax_reporting/infrastructure/on_chain/berachain_processor.py`
- `src/tax_reporting/infrastructure/on_chain/integrity_invariants.py`
- `tests/unit/infrastructure/test_berachain_processor.py`

- [x] `TestBerachainProcessor#test_single_unknown_in_small_wallet_does_not_abort`; given 50 rows where exactly 1 has `direction=unknown` (2% > 1% threshold but count=1 < floor), expects `_check_unknown_direction_rate` does NOT raise (the small-N floor prevents a single weird tx from aborting the run)
- [x] `TestBerachainProcessor#test_five_unknowns_in_small_wallet_aborts`; given 50 rows where 5 have `direction=unknown` (10% > 1% AND count=5 >= floor), expects `FileProcessingError` (a systemic regression still fails loud)
- [x] Run -> expect RED (today 1/50 = 2% > 1% raises)
- [x] In `src/tax_reporting/domain/on_chain_transaction.py`: add `UNKNOWN_DIRECTION_MAX_FRACTION: Final = 0.01` and `UNKNOWN_DIRECTION_MIN_ABSOLUTE: Final = 5` as module-level constants (the shared source).
- [x] In `berachain_processor.py`: remove the local `_UNKNOWN_DIRECTION_MAX_FRACTION = 0.01` (line 93); import `UNKNOWN_DIRECTION_MAX_FRACTION` and `UNKNOWN_DIRECTION_MIN_ABSOLUTE` from the domain module; update the gate at line 193 to `if unknown > UNKNOWN_DIRECTION_MAX_FRACTION * len(rows) and unknown >= UNKNOWN_DIRECTION_MIN_ABSOLUTE:` (or equivalent: `fraction > threshold and count >= floor`). Update the error message to name both the fraction and the absolute count.
- [x] In `integrity_invariants.py`: remove the local `_UNKNOWN_DIRECTION_MAX_FRACTION = 0.01` (line 120); import from the domain module. Update the audit-echo check at line 365 to match the processor's new discriminator (fraction + floor). Remove the "kept in sync" comment (the constant is now shared).
- [x] Run -> expect GREEN
- [x] Commit: `fix(on-chain): hoist unknown-direction threshold + add small-N floor (F17, F18)` (deed52c)

### Task 2: F19 - csv reader docstring fix

Files:
- `src/tax_reporting/infrastructure/on_chain/on_chain_csv_reader.py`

- [x] In `_parse_row`'s docstring (~line 149): correct "Fallible secondary parses (the int conversions) are wrapped so a malformed cell on an otherwise-good row is reported with row context and the row skipped" to match the implementation - only `fee_amount_raw` is in a nested try/except; `amount_raw` and `block_number` rely on the broad outer handler. Reword to: "Per-row parse errors are caught by the outer handler (one bad row never discards the dataset); `fee_amount_raw` additionally has a nested try/except for row-context-specific reporting."
- [x] Commit: `docs(on-chain): fix csv reader _parse_row docstring to match implementation (F19)` (283f7b6 combined)

### Task 3: F23 - broaden rpc retry to include HTTPException

Files:
- `src/tax_reporting/infrastructure/on_chain/rpc_client.py`
- `tests/unit/infrastructure/test_rpc_client.py`

- [x] `TestRpcClient#test_retries_on_http_client_http_exception`; given `_http_post_json` monkeypatched to raise `http.client.HTTPException("connection reset")`, expects `get_code` raises `FileProcessingError` after exactly `max_retries+1` attempts (the HTTPException is retried, not treated as a hard failure)
- [x] Run -> expect RED (today HTTPException propagates uncaught on the first attempt)
- [x] In `_rpc` (~line 181): broaden the retried-exception tuple from `except (urllib.error.URLError, TimeoutError)` to `except (urllib.error.URLError, TimeoutError, http.client.HTTPException)`. Add `import http.client` at the module top. The retry count, backoff, and FileProcessingError wrapping stay unchanged.
- [x] Run -> expect GREEN
- [x] Commit: `fix(on-chain): retry on http.client.HTTPException in rpc_client (F23)` (283f7b6 combined)
