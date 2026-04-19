# Plan: Fix Token Origin Resolution for LP Operations

## Context

The `TokenOriginResolver` (2,334-line `crypto_reporting.py`, lines 97-1119) fails to provide meaningful origin for tokens acquired from LP (liquidity pool) operations and misclassifies several deposit tags. When a user removes liquidity from a DEX pool, Koinly records `crypto_deposit` rows (tokens received) with empty `Sent Currency`, so the resolver produces self-referential results like `"SSUI (transfer, high confidence)"` — SSUI came from SSUI. The paired `crypto_withdrawal` row (LP tokens sent) is never indexed because `_index_row` skips rows with no `Received Currency`.

**Root causes:**
1. `crypto_withdrawal` rows (1,346 in the dataset) are completely invisible to the resolver
2. `crypto_deposit` rows with tag `"Liquidity out"` (20 rows) get self-referential `from_asset`
3. `crypto_deposit` rows with tag `"Liquidity in"` (20 rows) get `TRANSFER` instead of a DeFi-specific method
4. Tags `"airdrop"` (14 rows) and `"realized gain"` (3 rows) fall through to generic `TRANSFER`

**Fix:** Two-pass indexing — first index withdrawals by TxHash, then enrich deposit rows with paired withdrawal provenance. Add LP-specific and airdrop `AcquisitionMethod` enum values. Extract origin-related types to a dedicated domain module.

## Validation Commands
```bash
uv run pytest tests/unit/application/test_crypto_origin_resolver.py -x
uv run pytest tests/unit/application/test_crypto_reporting.py -x
uv run pytest -m unit -x
```

## Task 1: Write failing tests — LP withdrawal origin resolution
Files:
- `tests/unit/application/test_crypto_origin_resolver.py`

- [ ] Add `TestOriginResolverLiquidityOut` class with tests:
  - `test_liquidity_out_deposit_with_paired_withdrawal` — `crypto_deposit` with tag `"Liquidity out"` + `crypto_withdrawal` sharing same TxHash → `from_asset` resolves to LP token name (e.g., `CETUS-LP`), method `LIQUIDITY_WITHDRAWAL`
  - `test_liquidity_out_deposit_without_matching_withdrawal` — no paired withdrawal → `from_asset` is `"LP position"`, method `LIQUIDITY_WITHDRAWAL`
  - `test_liquidity_out_exchange_type` — `exchange` row with tag `"Liquidity out"` (both sent/received populated) → method `LIQUIDITY_WITHDRAWAL`, `from_asset` from `Sent Currency`
- [ ] Run RED: `uv run pytest tests/unit/application/test_crypto_origin_resolver.py -k "liquidity" -x`

## Task 2: Write failing tests — LP provision and new tag classification
Files:
- `tests/unit/application/test_crypto_origin_resolver.py`

- [ ] Add `TestOriginResolverLiquidityIn` class:
  - `test_liquidity_in_deposit_with_paired_withdrawals` — `crypto_deposit` receiving LP tokens + two `crypto_withdrawal` rows → `from_asset` is joined token names (e.g., `"SSUI+USDC"`), method `LIQUIDITY_PROVISION`
  - `test_liquidity_in_exchange_type` — `exchange` with tag `"Liquidity in"` → method `LIQUIDITY_PROVISION`
- [ ] Add `TestOriginResolverAirdropTag` class:
  - `test_airdrop_deposit` — `crypto_deposit` with tag `"Airdrop"` → method `AIRDROP`
- [ ] Add `TestOriginResolverRealizedGainTag` class:
  - `test_realized_gain_deposit` — `crypto_deposit` with tag `"Realized gain"` → method `REWARD`
- [ ] Run RED: `uv run pytest tests/unit/application/test_crypto_origin_resolver.py -x`

## Task 3: Implement — add AcquisitionMethod enum values
Files:
- `src/shares_reporting/application/crypto_reporting.py` (line 97-106)

- [ ] Add three new enum members before `TRANSFER`:
  ```python
  AIRDROP = "airdrop"
  LIQUIDITY_WITHDRAWAL = "liquidity_withdrawal"
  LIQUIDITY_PROVISION = "liquidity_provision"
  ```
- [ ] Run existing tests to verify no breakage: `uv run pytest tests/unit/application/test_crypto_origin_resolver.py -x`

## Task 4: Implement — add withdrawal indexing infrastructure
Files:
- `src/shares_reporting/application/crypto_reporting.py`

- [ ] Add `_WithdrawalRecord` frozen dataclass (near line 962): `sent_currency`, `sending_wallet`, `tag`, `date_key`, `tx_hash`
- [ ] Add `self._withdrawal_by_txhash: dict[str, list[_WithdrawalRecord]]` to `__init__` (line 981)
- [ ] Add `_index_withdrawal(self, row)` method — indexes `crypto_withdrawal` rows by TxHash, no-op for all other types. Requires non-empty TxHash and non-empty Sent Currency.
- [ ] Restructure `_build_lookup` (lines 993-995) to two-pass:
  ```python
  rows = _read_koinly_rows(path)
  for row in rows:
      self._index_withdrawal(row)
  for row in rows:
      self._index_row(row)
  ```
  Safe because `_read_koinly_rows` returns a `list`, not a generator.

## Task 5: Implement — LP provenance resolution and tag classification
Files:
- `src/shares_reporting/application/crypto_reporting.py`

- [ ] Add `_resolve_lp_provenance(self, tx_hash, receiving_wallet, tag)` method:
  - `"liquidity out"`: looks up withdrawals by TxHash → `from_asset` = LP token name (e.g., `CETUS-LP`). Fallback: `"LP position"`
  - `"liquidity in"`: looks up withdrawals → `from_asset` = joined provided tokens (e.g., `"SSUI+USDC"`). Multiple withdrawals per TxHash expected.
- [ ] Modify `_index_row` (lines 1041-1051) — extend `crypto_deposit`/`fiat_deposit` branch:
  - `"airdrop"` → `AIRDROP`
  - `"liquidity out"` → `LIQUIDITY_WITHDRAWAL` + `_resolve_lp_provenance()`
  - `"liquidity in"` → `LIQUIDITY_PROVISION` + `_resolve_lp_provenance()`
  - `"realized gain"` → `REWARD` (same category as cashback)
- [ ] Modify `_index_row` `exchange` branch (lines 1025-1030):
  - `"liquidity out"` tag → `LIQUIDITY_WITHDRAWAL`
  - `"liquidity in"` tag → `LIQUIDITY_PROVISION`
  - Others remain `SWAP_CONVERSION`
- [ ] Run GREEN: `uv run pytest tests/unit/application/test_crypto_origin_resolver.py -x`

## Task 6: Extract origin types to dedicated domain module
Files:
- NEW: `src/shares_reporting/domain/token_origin.py`
- `src/shares_reporting/application/crypto_reporting.py`
- `tests/unit/application/test_crypto_origin_resolver.py`
- `tests/unit/application/test_crypto_reporting.py`

This is the DDD extraction step. The 2,334-line `crypto_reporting.py` mixes domain types with application logic. Origin-related types (`AcquisitionMethod`, `TokenOrigin`, `_AcquisitionRecord`, `_WithdrawalRecord`, `TokenOriginResolver`) form a cohesive domain aggregate that can live independently.

- [ ] Create `src/shares_reporting/domain/token_origin.py` with:
  - `AcquisitionMethod` enum (moved from line 97)
  - `TokenOrigin` dataclass (moved from line 206)
  - `_WithdrawalRecord` dataclass (from Task 4)
  - `_AcquisitionRecord` dataclass (from line 962)
  - `TokenOriginResolver` class (from line 971)
  - Helper functions used only by the resolver: `_normalize_platform_name`, `_normalize_asset_ticker`, `_parse_koinly_datetime`, `_format_datetime` — OR keep these as imports from `crypto_reporting` if they're shared with other code
- [ ] Check which helpers (`_normalize_platform_name`, `_normalize_asset_ticker`, `_parse_koinly_datetime`, `_format_datetime`) are used outside the resolver. If shared, keep them in `crypto_reporting` and import. If resolver-only, move them.
- [ ] Update `crypto_reporting.py` to import from `domain.token_origin`
- [ ] Update test imports in `test_crypto_origin_resolver.py` and `test_crypto_reporting.py`:
  - `from shares_reporting.application.crypto_reporting import AcquisitionMethod, TokenOrigin, TokenOriginResolver` → `from shares_reporting.domain.token_origin import ...`
- [ ] Verify no circular imports: `domain.token_origin` must not import from `application.crypto_reporting`
- [ ] Run full suite: `uv run pytest -m unit -x`

## Task 7: Validate against real data
Files:
- `resources/source/koinly2025/` (read-only verification)

- [ ] Trace a known LP withdrawal through the resolver:
  - Timestamp: 2025-03-09 11:48:47 UTC
  - TxHash: `0xfeedface...`
  - Expected: SSUI capital gains with `Date Acquired = 2025-03-09` resolve to `from_asset = "CETUS-LP"`, method `LIQUIDITY_WITHDRAWAL`
- [ ] Verify no regressions on existing origin resolution (exchanges, rewards, transfers)
- [ ] Run e2e: `uv run pytest tests/end_to_end/ -x`

## Why same-TxHash grouping is safe

Per CLAUDE.md: "Do not reintroduce same-day disposal-context matching." Same-TxHash is fundamentally different — it's a deterministic on-chain identifier linking all legs of a single atomic transaction. This is not heuristic matching; it's cryptographic fact. The existing code already uses `TxHash` for confidence boosting (line 1055). Using it for grouping is a natural extension.

## Edge Cases

- **Empty TxHash on LP deposit**: Falls back to `from_asset = "LP position"` with `LIQUIDITY_WITHDRAWAL` method. Still more informative than current self-referential `TRANSFER`.
- **Multiple withdrawals with same TxHash**: For `Liquidity out`, deduplicates LP tokens. For `Liquidity in`, joins all distinct tokens with `+`.
- **No matching withdrawal for `Liquidity out`**: Uses `"LP position"` as `from_asset`.
- **Backward compatibility**: `_aggregate_origin_field()` only cares about the `token_swap_history` string format. New method values produce valid strings consumed identically.
