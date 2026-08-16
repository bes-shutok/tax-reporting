# Plan: On-Chain Transaction Tagger (Berachain-first)

Design record: `docs/architecture/on-chain-tx-design.md` (15 decisions + premortem with 5 blockers resolved, 4 mitigations adopted). This plan operationalizes that design.

Language guidelines: `docs/maintenance/python_guidelines.md` (silent-failure patterns, PT011/PT014/PT015), `docs/maintenance/development_lessons.md`.

## Terms

- **Transaction Source** - `(ProducerKind, producer_name)`; how rows were collected. Koinly = `Aggregator`; on-chain via Etherscan = `OnChainExplorer` per chain. See `docs/maintenance/glossary.md`.
- **OnChainTransaction** (NEW) - the native domain object: one per `tx_hash`, holds N `Event`s + parent-tx-level gas. Faithful to on-chain reality (no Koinly-isms).
- **Event** (NEW) - one economic event within a tx (Swap, Reward, LP deposit, …); carries an `event_id` unique within its parent tx.
- **Leg** - one token movement within a tx (asset + direction + amount); the raw material Events are built from.
- **EventType / SubType** - orthogonal tag axes (see §9.1 of the design record). EventType = economic shape (7 values); SubType = decision-driving discriminator (7 optional values).
- **Adapter** - projects `OnChainTransaction` → `TransactionHistoryRow` (Koinly-compat shape existing consumers read).
- **Processor** - per-source module converting raw rows → `OnChainTransaction`. The BERA processor = `OnChainExplorer/Etherscan-Berachain`.

## Gist & Examples

### What changes and why

Today the crypto tax pipeline ingests only the Koinly transaction-history CSV (the `Aggregator` source). The on-chain Etherscan fetcher (`run_on_chain_fetch`) already writes `resources/result/<year>/bera_transactions.csv` but nothing reads it. This plan builds a parallel **on-chain-native parser + tagger** that turns that CSV into a fully-tagged transaction history, then an **adapter** projects it onto the `TransactionHistoryRow` shape the existing pipeline consumes - so a wallet can opt into on-chain-derived data instead of Koinly, per-wallet, behind a flag.

Why on-chain-native and not "just parse the CSV into Koinly rows": on-chain data is **richer and more honest** than Koinly's collapsed format. One tx_hash has N token-movement legs + one gas fee; Koinly collapses multi-leg swaps into one `exchange` row and drops gas for 384/424 shared txs. The native model preserves this (gas at parent-tx level; one Event per economic shape; multi-token reward claims emit one Reward Event per asset). The adapter then reconciles this with the lossy Koinly shape downstream consumers expect.

### Concrete example

A Berachain tx that claims a BGT reward and swaps it for HONEY in one atomic transaction:
- **On CSV (raw):** 3 legs sharing one `tx_hash` - `in BGT 1.097`, `out BGT 1.097`, `in HONEY 4.2`, plus gas `0.00002 BERA` on the native leg.
- **Native model:** one `OnChainTransaction` with `gas={BERA, 0.00002}` and two `Event`s - `Reward(BGT)` and `Swap(BGT→HONEY)` - linked by `parent_event_id`.
- **Adapter projection:** two `TransactionHistoryRow`s sharing `tx_hash`, each with distinct `event_id`; `Fee Amount` on the carrier row (the Swap's row, native-leg-first rule), `Fee Amount` empty on the Reward row.

### Why this is one plan, not two phases

The premortem (`docs/architecture/on-chain-tx-design.md` §12) found that the consumer key migrations (B1/B2), the adapter, the fee-filter re-scope (B4/B5), and the fail-loud wiring are **tightly coupled**: the adapter cannot emit split rows until consumers key on `(tx_hash, event_id)`; the live flip cannot happen until the fail-loud path and reconciliation sheet are wired. Splitting would leave a half-wired intermediate state. This plan sequences them so each commit leaves the codebase compiling and the Koinly path byte-identical.

### Edge cases that motivated decisions

- **139 GAS_ONLY txs** (zero-value native outflow, only gas burned): Koinly drops these silently. The native model emits one `GasBurn` Event so PT-deductible gas isn't lost. The adapter's carrier-row rule has an exception: a GasBurn row carries gas as `Sent Amount` with `Fee Amount` empty (gas isn't a fee on top of itself) - prevents the B5 double-count.
- **13 BERA-only hashes** (12 gas-only + 1 spam airdrop `WWW.BERA777.XYZ`): emitted with correct tags, not dropped; sorting/rejection is downstream.
- **Multi-token reward claim** (the BM tx: 40 legs, 14 distinct reward tokens): native model groups in-legs by asset and emits one Reward Event per (tx_hash, asset) with summed amount. The adapter projects one `crypto_deposit/Reward` row per asset.
- **LP-token detection**: symbol regex was rejected (V2 pairs all return `UNI-V2`; staking receipts share naming). Address-keyed autodiscovery: subgraph snapshot (primary) + on-chain bytecode/implementation-address fingerprint (fallback) + tx-pattern (provenance only).

## Evaluation Criteria

**Quality dimensions:**
- **Correctness (primary):** for every non-opted-in wallet, the Koinly-derived FIFO/cost-basis/reward/loan output is **byte-identical** before and after this plan, with ONE explicitly-documented exception: Task 4's `token_origin` `TxSrc`→`TxHash` migration fixes a pre-existing bug (the comment "Real Koinly exports store the transaction hash in TxSrc" is wrong - measured: 911/911 withdrawal rows have TxHash≠TxSrc; TxSrc is a wallet address, not a hash). The migration's Koinly-path delta is characterized in a dedicated test (Task 4) before the migration lands. For the opted-in BERA wallet, the on-chain-derived output reconciles against Koinly with only the documented divergences (gas now surfaced; spam/airdrop included; multi-leg compression differs).
- **No silent data loss:** a parse/tag/adapter failure for an opted-in wallet raises `ReportGenerationError` (fail-loud), never falls through `main.py:293`'s broad `except Exception`.
- **Reconciliation visibility:** the Crypto Reconciliation sheet shows per-wallet source provenance (Koinly/on-chain), per-wallet row counts, and a Koinly-vs-on-chain delta block when the flag is on.
- **LP-classification robustness:** the subgraph snapshot carries freshness metadata (`snapshot_as_of_block`, `snapshot_as_of_date`); the subgraph is pinned to a version (not `latest`); the snapshot is schema-validated on load; a WARN fires when tx dates postdate the snapshot.
- **Maintainability:** `berachain_processor.py` stays under the 1000-line / 50-function guideline (AGENTS.md); the three responsibilities (classify, tag, coordinate LP-autodiscovery) are separable.
- **Test coverage:** characterization tests pin every consumer's current behavior on real Koinly data before any amendment; the BERA processor has direct unit tests for each EventType classification path; the adapter has direct unit tests for the carrier-row gas rule (including the GasBurn exception).

**Release gates:**
- All characterization tests GREEN before AND after the consumer key migrations.
- The opted-in BERA wallet run produces a reconciliation diff with only the documented divergences.
- The fail-loud path is exercised by a test that injects a parse failure and asserts `ReportGenerationError` (not silent skip).
- The premortem's accepted-risk A1 (attacker-with-config-write-access) is documented in `docs/maintenance/`; the cheap mitigations (closed-enum + citation validation on `operator_country`; decimal clamp) are implemented.

## Review Scope

**Explicit must-fix:**

**Production code:**
- `src/tax_reporting/domain/on_chain_transaction.py` *(new)* - OnChainTransaction, Event, Leg, Gas dataclasses + EventType/SubType enums
- `src/tax_reporting/domain/transaction.py` - add `event_id` to `TransactionHistoryRow` + amend `TxCorrelationKey` (Invariant 2)
- `src/tax_reporting/infrastructure/on_chain/on_chain_csv_reader.py` *(new)* - parse `bera_transactions.csv` → `list[OnChainTxRow]`
- `src/tax_reporting/infrastructure/on_chain/berachain_processor.py` *(new)* - the BERA processor (classify + tag + LP-autodiscovery coordination)
- `src/tax_reporting/infrastructure/on_chain/rpc_client.py` *(new)* - `eth_getCode` + `implementation()` for the LP bytecode fallback
- `src/tax_reporting/infrastructure/on_chain/lp_autodiscovery.py` *(new)* - subgraph snapshot loader + bytecode fingerprint + tx-pattern provenance
- `src/tax_reporting/application/on_chain_th_adapter.py` *(new)* - `OnChainTransaction` → `TransactionHistoryRow` projection (carrier-row gas rule, Event→Type/Tag mapping)
- `src/tax_reporting/application/on_chain_config.py` - load `<chain>_contracts.json` + LP snapshot (extend existing loader; add schema validation + freshness check)
- `src/tax_reporting/application/crypto_fifo/parsing.py` - `tx_key` becomes `(tx_hash, event_id)` (B2)
- `src/tax_reporting/application/crypto_fifo/contexts.py` - `ParsedTxRow.tx_key` / `AcquisitionContext.tx_key` / `ConsumptionContext.tx_key` type change (B2)
- `src/tax_reporting/application/crypto_fifo/matching.py` - `carryover_cost_by_tx_key` dict key type (B2, review F1)
- `src/tax_reporting/application/crypto_fifo/transfer.py` - `tx_key_to_sender` dict key type (B2, review F1)
- `src/tax_reporting/application/crypto_fifo/cross_asset.py` - carry-over join key type (B2)
- `src/tax_reporting/application/crypto_fifo/merge.py` - `MergedAssetFifoResult.carryover_cost_by_tx_key` / `partial_carryover_tx_keys` type (B2)
- `src/tax_reporting/application/crypto_fifo/_emitters.py` - `tx_key` threading (B2, review F1)
- `src/tax_reporting/domain/crypto_fifo.py` - `AssetFifoResult.carryover_cost_by_tx_key` / `partial_carryover_tx_keys` type (B2, review F1-r3)
- `src/tax_reporting/application/crypto/fifo_helpers.py` - cross-package `tx_key` bridge (B2, review F1-r3)
- `src/tax_reporting/application/token_origin.py` - read `TxHash` not `TxSrc` (B1); update both `_index_withdrawal` and `_index_row`
- `src/tax_reporting/application/crypto/fee_filter.py` - re-scope co-occurrence guard to distinct `(tx_hash, event_id)` pairs (B4); confirm no GasBurn double-count (B5)
- `src/tax_reporting/application/crypto/tx_correlation_key_resolver.py` - `tx_id` derivation uses `(tx_hash, event_id)`
- `src/tax_reporting/application/main.py` - wire on-chain TH path behind `on_chain_th_wallets` flag; fail-loud for opted-in wallets (M1); keep broad `except Exception` for collection-only
- `src/tax_reporting/application/persisting/crypto_reconciliation_sheet.py` - per-wallet source provenance + row counts + delta block (M3)
- `src/tax_reporting/config.py` - load `on_chain_th_wallets` from `[TAX JURISDICTION]`

**Tests:**
- `tests/unit/domain/test_on_chain_transaction.py` *(new)*
- `tests/unit/infrastructure/test_on_chain_csv_reader.py` *(new)*
- `tests/unit/infrastructure/test_berachain_processor.py` *(new)*
- `tests/unit/infrastructure/test_lp_autodiscovery.py` *(new)*
- `tests/unit/application/test_on_chain_th_adapter.py` *(new)*
- `tests/unit/application/test_on_chain_config_contracts.py` *(new)* - schema validation, freshness, operator_country enum+citation
- `tests/unit/crypto_fifo/test_parsing_tx_key.py` *(new)* - characterization + amendment
- `tests/unit/application/test_token_origin_txhash.py` *(new)* - TxHash-not-TxSrc migration
- `tests/unit/application/test_fee_filter_cooccurrence.py` *(new)* - re-scoped guard
- `tests/end_to_end/test_on_chain_koinly_characterization.py` *(new)* - byte-identical Koinly output for non-opted-in wallets
- `tests/end_to_end/test_on_chain_bera_opted_in.py` *(new)* - the opted-in BERA wallet run + reconciliation diff

**Resources:**
- `resources/source/2025/berachain_contracts.json` *(new)* - contract registry (ships EMPTY `operator_country`; B3 resolution)
- `resources/source/2025/berachain_lp_snapshot.json` *(new)* - subgraph-derived LP allowlist (with `snapshot_as_of_block`, `snapshot_as_of_date`, `subgraph_version`)
- `resources/source/example/2025/berachain_contracts.json` *(new)* - example/template
- `resources/source/example/2025/berachain_lp_snapshot.json` *(new)* - example/template

**Plan-related extension:** implementation and review may change files not listed above (e.g. `crypto_fifo/cross_asset.py`, `merge.py`, `wallet_kind.py`, `derivatives_filter.py`) when they consume the amended `tx_key`/`TxCorrelationKey`. Treat a finding as in scope when it is causally related to the key migration or the adapter projection.

**Out of scope; reject unless plan-related:**
- `src/tax_reporting/application/extraction/processing.py` (IB Flex CSV reader; unrelated)
- `src/tax_reporting/infrastructure/koinly_parser.py` (the Koinly reader; must remain byte-identical - characterization depends on it)
- Any change to `derivatives_filter.py`'s derivatives-separation logic beyond what the key migration requires

## Validation Commands

```bash
# 1. Full test suite (the Koinly path must stay green throughout)
uv run pytest

# 2. Characterization: Koinly-path output byte-identical before/after consumer migrations
uv run pytest tests/end_to_end/test_on_chain_koinly_characterization.py -v

# 3. BERA processor direct unit tests
uv run pytest tests/unit/infrastructure/test_berachain_processor.py -v

# 4. Adapter gas-rule tests (including GasBurn exception)
uv run pytest tests/unit/application/test_on_chain_th_adapter.py -v

# 5. Fail-loud path (opted-in wallet parse failure raises ReportGenerationError, not silent skip)
uv run pytest tests/end_to_end/test_on_chain_bera_opted_in.py::test_parse_failure_raises -v

# 6. No stale TxSrc-as-hash reads remain in token_origin
! grep -n 'row.get("TxSrc"' src/tax_reporting/application/token_origin.py

# 7. No bare tx_hash-only correlation in crypto_fifo (event_id must be part of the key)
grep -n "tx_key = " src/tax_reporting/application/crypto_fifo/parsing.py | grep -v "event_id"

# 8. Snapshot freshness metadata present
python -c "import json; d=json.load(open('resources/source/2025/berachain_lp_snapshot.json')); assert d.get('snapshot_as_of_block') and d.get('subgraph_version'), 'missing freshness metadata'"

# 9. Contract registry ships no operator_country for Berachain (B3 resolution)
python -c "import json; d=json.load(open('resources/source/2025/berachain_contracts.json')); assert all('operator_country' not in v for v in d.get('contracts',[])), 'B3 violated: Berachain contract has operator_country'"
```

---

### Task 1: Characterization tests pinning current consumer behavior on real Koinly data

These run GREEN now and must remain GREEN after every amendment in this plan. They are the regression catch for B1/B2/B4/B5.

Files:
- `tests/end_to_end/test_on_chain_koinly_characterization.py` *(new)*

- [x] `TestOnChainKoinlyCharacterization#test_fifo_output_byte_identical`; given the real `resources/source/2025/koinly/` data and `on_chain_th_wallets` unset (all Koinly), expects the FIFO/capital-gains output (lot counts, totals per asset, carry-over cost basis) to be byte-identical to a pinned baseline captured at task-start. Pin the baseline as committed fixtures (synthetic data per AGENTS.md crypto-tests rule; if real-data-derived, generate deterministically and commit the generator).
- [x] `TestOnChainKoinlyCharacterization#test_reward_output_byte_identical`; given the same Koinly data, expects reward-income aggregation (per asset, per income_code, per source_country) byte-identical to baseline.
- [x] `TestOnChainKoinlyCharacterization#test_loan_activity_output_byte_identical`; given the same Koinly data, expects loan-activity classification (status per asset) byte-identical to baseline.
- [x] `TestOnChainKoinlyCharacterization#test_fee_filter_behavior_byte_identical`; given the same Koinly data, expects the fee-filter's removed-fee set and suspect set byte-identical to baseline.
- [x] Run → expect GREEN (all four pass at task start; they are the safety net for the migrations that follow).
- [x] Commit: `test(on-chain): pin Koinly-path characterization baselines before consumer migrations`

### Task 2: Add `event_id` to `TransactionHistoryRow` + `TxCorrelationKey` + amend the resolver (B1, Invariant 2; folds review F3, F7)

The native model's split Events require consumers to distinguish rows within a tx. `event_id` is `None` for Koinly rows (preserves today's semantics) and non-`None` for on-chain split rows. **Three sites change atomically:** the dataclass field, the key's `__eq__` AND `__hash__`, and the sole constructor (`tx_correlation_key_resolver.resolve`) that populates it - otherwise the amendment is dead code (review F3).

Files:
- `src/tax_reporting/domain/transaction.py`
- `src/tax_reporting/application/crypto/tx_correlation_key_resolver.py`
- `tests/unit/domain/test_transaction_event_id.py` *(new)*
- `tests/unit/application/test_tx_correlation_key_resolver_event_id.py` *(new)*

- [x] `TestTransactionEventId#test_koinly_row_has_none_event_id`; given a `TransactionHistoryRow` constructed by the Koinly parser, expects `event_id is None`.
- [x] `TestTransactionEventId#test_onchain_row_carries_event_id`; given an on-chain-derived row, expects `event_id` is the non-`None` Event identifier.
- [x] `TestTxCorrelationKey#test_two_rows_same_hash_different_event_id_not_equal`; given two rows with the same `tx_hash` but different `event_id`, expects `TxCorrelationKey.__eq__` returns False (the amendment: equality keys on `(tx_hash, event_id)` when both non-`None`).
- [x] `TestTxCorrelationKey#test_koinly_rows_same_hash_still_equal`; given two Koinly rows (`event_id=None`) sharing `tx_hash`, expects `__eq__` still returns True (Koinly semantics preserved).
- [x] `TestTxCorrelationKey#test_hash_incorporates_event_id`; given two keys with the same `tx_id` but different `event_id`, expects they are unequal AND both survive insertion into a `set` (i.e. `__hash__` incorporates `event_id` when non-`None`, review F7: `hash((self.tx_id, self.event_id))` when both present, else today's behavior). Without this, unequal keys collide in any dict/set keyed by `TxCorrelationKey`.
- [x] `TestTxCorrelationKeyResolver#test_resolver_passes_event_id_through`; given a `TransactionHistoryRow` with `event_id="evt2"`, expects `TxCorrelationKeyResolver.resolve(row)` produces a key carrying `event_id="evt2"` (review F3: the sole constructor at `tx_correlation_key_resolver.py:111` must read `row.event_id`, not silently default it).
- [x] `TestTxCorrelationKeyResolver#test_koinly_row_resolves_event_id_none`; given a Koinly `TransactionHistoryRow` (`event_id=None`), expects the resolver produces a key with `event_id=None` (today's behavior preserved).
- [x] Run → expect RED.
- [x] Amend `TransactionHistoryRow` to add `event_id: str | None = None` (default None preserves all existing construction sites). Amend `TxCorrelationKey`: add `event_id: str | None` field; amend `__eq__` to require `event_id` match when both non-`None` (None matches None); amend `__hash__` to incorporate `event_id` when non-`None`. Update the docstring's Invariant 2 reference. Amend `tx_correlation_key_resolver.resolve` (`:93` reads `tx_id = row.tx_hash`; add `event_id = row.event_id` and pass to the constructor at `:111`).
- [x] Run → expect GREEN.
- [x] Commit: `feat(domain): add event_id to TransactionHistoryRow + TxCorrelationKey + resolver (Invariant 2)`

### Task 3: Migrate `crypto_fifo` `tx_key` to `(tx_hash, event_id)` (B2; folds review F1, F8)

The FIFO dedup system is independent of `TxCorrelationKey` and must be amended in lockstep. **Two sub-tasks, sequenced so each commit typechecks** (review F8: a single commit widening the type while consumer annotations lag breaks `mypy`/`pyright`). **The consumer sweep must be COMPLETE** (review F1: the plan's own B2 anti-pattern - "consumer list was incomplete" - recurred when the original Task 3 named only `cross_asset.py` and `merge.py`).

Files:
- `src/tax_reporting/application/crypto_fifo/contexts.py` - `ParsedTxRow.tx_key`, `AcquisitionContext.tx_key`, `ConsumptionContext.tx_key`
- `src/tax_reporting/application/crypto_fifo/parsing.py` - `tx_key` construction at `:228`
- `src/tax_reporting/application/crypto_fifo/matching.py` - `carryover_cost_by_tx_key: dict[str, Decimal]` at `:74`; consumers at `:341, :414`
- `src/tax_reporting/application/crypto_fifo/transfer.py` - `tx_key_to_sender: dict[str, str]` at `:30`
- `src/tax_reporting/application/crypto_fifo/cross_asset.py` - `dict[str, list[str]]` at `:27`; `key[0]==tx_key` at `:58, :56, :61, :69`
- `src/tax_reporting/application/crypto_fifo/merge.py` - `MergedAssetFifoResult.carryover_cost_by_tx_key` at `:18`; `partial_carryover_tx_keys` at `:19`
- `src/tax_reporting/application/crypto_fifo/_emitters.py` - threads `tx_key` through every emitter
- `src/tax_reporting/domain/crypto_fifo.py` - `AssetFifoResult.carryover_cost_by_tx_key: dict[str, Decimal]` at `:104`; `partial_carryover_tx_keys: frozenset[str]` at `:105` (review F1-r3)
- `src/tax_reporting/application/crypto/fifo_helpers.py` - cross-package `tx_key` bridge, lines 90-280 (review F1-r3)
- `tests/unit/crypto_fifo/test_parsing_tx_key.py` *(new)*

**First, enumerate the complete consumer set (do NOT trust a list - grep ACROSS directories, not just `crypto_fifo/`):**
- [x] Run `grep -rn "tx_key" src/tax_reporting/application/crypto_fifo/ src/tax_reporting/application/crypto/ src/tax_reporting/domain/crypto_fifo.py` and record EVERY file + line that reads, types, or threads `tx_key` (including the `partial_carryover_tx_keys` / `partial_tx_keys` variants - review F2-r3). **The sweep MUST cross directory boundaries** (review F1-r3, the third recurrence of the round-1 F1 "consumer list was incomplete" anti-pattern - this time it crossed into `domain/crypto_fifo.py:104-105` and `application/crypto/fifo_helpers.py`). Do NOT scope the grep to `crypto_fifo/` alone; the type flows through `fifo_helpers.py` (the cross-package bridge) into `domain/crypto_fifo.py`. The verified baseline at plan-write time:
    - `crypto_fifo/contexts.py:29,46,69` - `tx_key` field on `ParsedTxRow`/`AcquisitionContext`/`ConsumptionContext`
    - `crypto_fifo/matching.py:74,75` - `carryover_cost_by_tx_key: dict[str, Decimal]`; `partial_tx_keys: set[str]`
    - `crypto_fifo/transfer.py:30` - `tx_key_to_sender: dict[str, str]`
    - `crypto_fifo/cross_asset.py:27,56,58,61,69` - `dict[str, list[str]]`; join key
    - `crypto_fifo/merge.py:18,19` - `carryover_cost_by_tx_key: dict[tuple[str,str], Decimal]`; `partial_carryover_tx_keys: frozenset[str]`
    - `crypto_fifo/_emitters.py` - threads `tx_key` through every emitter
    - **`domain/crypto_fifo.py:104,105`** - `AssetFifoResult.carryover_cost_by_tx_key: dict[str, Decimal]`; `partial_carryover_tx_keys: frozenset[str]` (review F1-r3)
    - **`application/crypto/fifo_helpers.py:90-280`** - the cross-package bridge; builds the nested `(tx_key, platform)` tuple feeding `merge.py:18`; `tx_key_to_sender`, `tx_key_to_asset_totals`, `merged_partial_tx_keys` (review F1-r3)
  Re-grep at execution in case new consumers landed.

**Sub-task 3a - annotation sweep (no behavior change; Koinly path byte-identical; commit typechecks):**
- [x] Introduce a type alias `TxKey = str | tuple[str, str]` in `contexts.py` and use it everywhere `tx_key` appears (rather than widening each annotation inline). This sidesteps the review F2-r2 trap: `merge.py:18` uses `dict[tuple[str, str], Decimal]` where the inner tuple is `(tx_key, platform)` - a NESTED tuple, not the tx_key type itself. Naively widening that annotation to `dict[str | tuple[str, str], Decimal]` would be wrong (the outer key is always a 2-tuple). The alias makes the intent explicit and keeps `merge.py`'s nested structure correctly typed.
- [x] Apply `TxKey` across EVERY consumer enumerated above - INCLUDING `domain/crypto_fifo.py:104-105` and `fifo_helpers.py` (review F1-r3) and the `partial_carryover_tx_keys`/`partial_tx_keys` variants (review F2-r3, also `tx_key`-keyed) - and at `merge.py` where it's the inner element of the nested tuple. No construction change yet - `parsing.py:228` still produces `str`. This commit typechecks (the alias widens; str is assignable to the union) and behavior is unchanged. The sweep is the load-bearing premise of the 3a/3b split (review F8): if 3a leaves any consumer with a stale `str` annotation, 3a does NOT typecheck and the split's safety guarantee is voided.
- [x] `TestParsingTxKey#test_koinly_rows_dedup_as_today`; given two Koinly TH rows sharing `tx_hash` (event_id=None), expects `_dedup_by_tx_key` keeps the first and drops the second (byte-identical to today).
- [x] Run Task 1 characterization → expect GREEN.
- [x] Commit: `refactor(crypto_fifo): widen tx_key type to str|tuple across all consumers (no behavior change)`

**Sub-task 3b - construction change + tests:**
- [x] `TestParsingTxKey#test_onchain_split_rows_not_deduped`; given two on-chain rows sharing `tx_hash` but with different `event_id`, expects `_dedup_by_tx_key` keeps BOTH (the fix: multi-token reward claims and multi-leg LP deposits are no longer silently dropped).
- [x] `TestParsingTxKey#test_cross_asset_carryover_uses_event_id`; given a cross-asset swap with two Events (event_id A, B), expects the carry-over cost basis join keys on `(tx_hash, event_id)` and does not merge unrelated Events.
- [x] `TestParsingTxKey#test_onchain_deferred_transfer_resolves_nonzero_cost`; given an on-chain `transfer_in_deferred` acquisition and a `transfer_out` consumption sharing a `(tx_hash, event_id)` tuple key, expects the carry-over cost resolves to a NON-zero value (review F1: this is the silent-zero-cost-basis corruption case for `matching.py:74` and `transfer.py:30` - the test must exercise the tuple key through the dict join, not just the type).
- [x] Run → expect RED.
- [x] Change `tx_key` construction (`parsing.py:228`) to `(tx_hash, event_id)` when `event_id` is non-`None`, else `tx_hash` (Koinly path unchanged). Add a cross-reference comment at each site noting `TxCorrelationKey` is the parallel system and both must stay consistent.
- [x] Run Task 1 characterization → expect GREEN (Koinly path byte-identical).
- [x] Run → expect GREEN.
- [x] Commit: `feat(crypto_fifo): migrate tx_key construction to (tx_hash, event_id) for split-event support`

### Task 4: Migrate `token_origin.py` to read `TxHash` not `TxSrc` (B1; folds review F4)

`token_origin.py:171,278` reads `row["TxSrc"]` AS the tx hash (a Koinly quirk). **The comment "Real Koinly exports store the transaction hash in TxSrc" is demonstrably wrong** (measured this session: 911/911 withdrawal rows have `TxHash`=real hash ≠ `TxSrc`=wallet address; `TxSrc` is the wallet's own address, identical across all rows from that wallet - so today's indexing by `TxSrc` collapses all withdrawals from one wallet into one dict key, which is itself a latent bug). The on-chain adapter populates `TxHash` correctly; token_origin must read it.

**Review F4 consequence:** the migration changes token_origin's lookup key on the KOINLY path itself (not just the on-chain path), so the plan's "byte-identical Koinly output" promise CANNOT hold for token_origin. This task characterizes the delta explicitly rather than silently blessing it.

Files:
- `src/tax_reporting/application/token_origin.py`
- `tests/unit/application/test_token_origin_txhash.py` *(new)*

- [x] `TestTokenOriginTxHash#test_koinly_withdrawal_indexed_by_txhash_after_migration`; given a Koinly TH withdrawal row, expects `_index_withdrawal` keys the record by `TxHash` (per-tx-hash) after migration, NOT by `TxSrc` (per-wallet-address) as before. This is the documented Koinly-path delta.
- [x] `TestTokenOriginTxHash#test_koinly_deposit_lookup_pairs_correctly_after_migration`; given a Koinly TH where a deposit and its corresponding withdrawal share a `TxHash`, expects `_resolve_lp_provenance` (and the standard withdrawal-lookup path) finds the withdrawal via the shared `TxHash` - confirming the deposit↔withdrawal pairing still resolves (it pairs by tx-hash now, which is MORE correct than the prior per-wallet collision).
- [x] `TestTokenOriginTxHash#test_multi_withdrawal_per_wallet_no_longer_collide`; given TWO LP-tagged Koinly TH withdrawals (`Tag=Liquidity out` or similar, so they pass the `:191` filter that gates `_index_withdrawal`) from the SAME wallet (same `TxSrc`=wallet address) but DIFFERENT `TxHash`es depositing different LP-token pairs, expects after migration `_resolve_lp_provenance` returns the DISTINCT `from_asset` for each (e.g. "WBERA+HONEY" for tx1, "WBTC+WBERA" for tx2). **Pre-migration** both withdrawals index under the shared `TxSrc` wallet-address key - and because `_index_withdrawal` APPENDS to a list (`:196-201`) rather than overwriting, the lookup returns the FIRST withdrawal's record for BOTH deposits (wrong `from_asset` for the second). **Post-migration** each withdrawal indexes under its own `TxHash`, so each deposit resolves its own pair (review F1-r2 + F3-r3: assert on the observable `from_asset` delta, not raw dict keying).
- [x] `TestTokenOriginTxHash#test_onchain_row_resolves_via_txhash`; given an on-chain-derived row with `TxHash`=real hash and `TxSrc`=from_address, expects the LP-provenance lookup finds the withdrawal (does not fall back to "LP position").
- [x] Run → expect RED (the migration is not yet applied).
- [x] Change `token_origin.py:171,278` to `row.get("TxHash", "")`. Replace the misleading comments with the correct rationale (`TxHash` is the per-transaction identifier; `TxSrc`/`TxDest` are wallet addresses).
- [x] Run the Task 1 characterization → expect the `test_loan_activity_output_byte_identical` and `test_fifo_output_byte_identical` to either stay GREEN (if token_origin's output happens to be identical because deposits and withdrawals pair by the same shared value either way) OR go RED with a documented delta. **If RED:** capture the delta as the new baseline and add a comment in the characterization test naming the token_origin migration as the cause. Do NOT silently re-capture.
- [x] Run → expect GREEN.
- [x] Commit: `fix(token_origin): read TxHash not TxSrc (B1); fixes latent per-wallet keying bug; document Koinly-path delta`

### Task 5: Re-scope `fee_filter.py` co-occurrence guard (B4) + define the CSV↔object bridge (folds review F2, F5)

**Review F2 (blocking):** `fee_filter.py:219` reads `rows = read_koinly_rows(transaction_history_file)` - raw CSV `dict[str,str]` rows keyed by column name. `event_id` is a field on the typed `TransactionHistoryRow` (Task 2), NOT a CSV column. As written, "count distinct `(tx_hash, event_id)`" is unimplementable - `event_id` is unreachable from the dicts fee_filter iterates. This task defines the bridge FIRST.

**Review F5 (blocking):** "≥2 distinct events" ≠ B4's stated intent "the withdrawal co-occurs with a non-fee event." A tx with two withdrawal/Cost events would be wrongly admitted. The correct predicate is "≥1 non-fee event co-occurs."

Files:
- `src/tax_reporting/application/crypto/fee_filter.py`
- `src/tax_reporting/application/crypto_reporting.py` - caller `remove_transaction_fees` (`:451-453`) and `_find_report_path` (`:215`)
- `src/tax_reporting/infrastructure/koinly_parser.py` - `read_koinly_rows` / `_detect_header_index` (only if bridge option (a) is chosen)
- `tests/unit/application/test_fee_filter_cooccurrence.py` *(new)*

**Step 1 - decide and document the bridge (do this BEFORE writing tests):**
- [x] Decide between (a) the on-chain adapter serializes its rows to a TH-shaped CSV that includes an `event_id` column, and `koinly_parser.read_koinly_rows`/`_detect_header_index` learn to expose it (keeps fee_filter's file-Path contract unchanged; lowest ripple); OR (b) `fee_filter` and its caller change to consume `list[TransactionHistoryRow]` instead of a file Path (larger signature change, touches `crypto_reporting.py:451-453`). **Recommended: (a)** - it preserves the existing file-Path contract and means Koinly CSVs (which have no event_id column) naturally yield `event_id=""`→None, preserving today's behavior. Record the choice in the task commit message and in a comment at `fee_filter.py:222`. **Chose (a).** Bridge is a no-op on the parser (DictReader preserves unknown columns); documented the contract on `_TxCooccurrence`.

**Step 2 - tests:**
- [x] `TestFeeFilterCooccurrence#test_koinly_row_guard_unchanged`; given Koinly TH rows (no `event_id` column → parsed as None/empty), expects the co-occurrence guard behaves exactly as today (a withdrawal whose TxHash appears ≥2 times in TH is admitted).
- [x] `TestFeeFilterCooccurrence#test_koinly_solo_withdrawal_rejected`; given a Koinly TH withdrawal whose TxHash appears only once, expects the guard rejects it (review F4-r2: the negative direction of the "Koinly rows behave as today" equivalence - only the positive was tested in round 1; this confirms `has_nonfee_event_cooccurring` reduces to `count >= 2` for Koinly rows in BOTH directions).
- [x] `TestFeeFilterCooccurrence#test_onchain_withdrawal_cooccurs_with_nonfee_event_admitted`; given on-chain rows where one tx_hash has a `crypto_withdrawal` event AND a non-fee event (e.g. a Swap), expects the withdrawal is admitted (B4 intent: co-occurs with a non-fee event).
- [x] `TestFeeFilterCooccurrence#test_onchain_two_withdrawals_no_nonfee_event_rejected`; given on-chain rows where one tx_hash has TWO `crypto_withdrawal/Cost` events and NO non-fee event, expects BOTH are rejected (review F5: "≥2 distinct events" would wrongly admit them; the correct predicate "≥1 non-fee event co-occurring" rejects them).
- [x] `TestFeeFilterCooccurrence#test_genuine_disposal_not_admitted_when_solo_event`; given an on-chain withdrawal that is the only Event in its tx, expects the guard rejects it.
- [x] `TestFeeFilterGasBurn#test_gasburn_row_not_double_counted`; given a GasBurn Event projected as `crypto_withdrawal/Cost` with `Sent Amount`=gas and `Fee Amount` empty, expects only the `is_withdrawal` path fires (not `has_embedded_fee`); the gas is counted once.
- [x] Run → expect RED.

**Step 3 - implementation:**
- [x] If bridge (a): extend `_detect_header_index`/`read_koinly_rows` to surface an `event_id` column when present (absent → default None). If bridge (b): change `remove_transaction_fees` to accept `list[TransactionHistoryRow]` and update the caller.
- [x] Change the Counter at `fee_filter.py:222` to count, per `tx_hash`, the set of `event_id`s AND whether any non-fee event is present. Update `occurs_at_least_twice` at `:254` to the F5-correct predicate: `bool(tx_hash) and has_nonfee_event_cooccurring(tx_hash)` (not merely `count >= 2`). For Koinly rows (event_id None), `has_nonfee_event_cooccurring` reduces to today's `count >= 2` semantics (Koinly's co-occurrence signal is row-count based and unchanged).
- [x] Confirm the carrier-row adapter rule (Task 10) leaves `Fee Amount` empty on GasBurn rows so `has_embedded_fee` is false for them.
- [x] Run Task 1 characterization → expect GREEN.
- [x] Run → expect GREEN.
- [x] Commit: `fix(fee_filter): re-scope co-occurrence guard to non-fee-event co-occurrence (B4); prevent GasBurn double-count (B5); define event_id CSV bridge`

### Task 6: Native domain model - `OnChainTransaction`, `Event`, `Leg`, `Gas` + `EventType`/`SubType` enums

Files:
- `src/tax_reporting/domain/on_chain_transaction.py` *(new)*
- `tests/unit/domain/test_on_chain_transaction.py` *(new)*

- [x] `TestEventType#test_seven_members`; given the EventType enum, expects exactly `Swap, LiquidityDeposit, LiquidityWithdraw, Reward, Transfer, GasBurn, Unknown`.
- [x] `TestSubType#test_seven_optional_members`; given the SubType enum, expects exactly `staking, airdrop, validator_rebate, spam, cost_gas, internal_transfer, bridge`.
- [x] `TestOnChainTransaction#test_gas_at_parent_level`; given an `OnChainTransaction` constructed with one tx_hash, two Events, and `gas={asset:BERA, amount_raw, decimals}`, expects `gas` is a tx-level field and no Event carries gas.
- [x] `TestOnChainTransaction#test_events_linked_by_parent_event_id`; given two Events from one tx, expects each carries a `parent_tx_hash` and a unique-within-tx `event_id`.
- [x] Run → expect RED.
- [x] Implement the frozen dataclasses + enums. `EventType`/`SubType` are `Enum`. `Leg` carries `(asset, token_address, amount_raw: int, amount_decimals: int, direction: Literal["in","out","unknown"], from_address, to_address)`. `Gas` carries `(asset, amount_raw: int, decimals: int)`. `Event` carries `(event_id, event_type, sub_type: SubType|None, legs: tuple[Leg,...], parent_tx_hash)`. `OnChainTransaction` carries `(tx_hash, block_number, timestamp_utc: datetime, chain, wallet_label, wallet_address, gas: Gas|None, events: tuple[Event,...])`.
- [x] Run → expect GREEN.
- [x] Commit: `feat(domain): add on-chain-native transaction model (OnChainTransaction/Event/Leg/Gas + EventType/SubType)`

### Task 7: `on_chain_csv_reader.py` - parse `bera_transactions.csv` → `list[OnChainTxRow]`

Thin parser, no classification. Mirrors `koinly_parser.read_koinly_rows` hygiene (symlink refusal, size cap, utf-8-sig, blank-row drop).

Files:
- `src/tax_reporting/infrastructure/on_chain/on_chain_csv_reader.py` *(new)*
- `tests/unit/infrastructure/test_on_chain_csv_reader.py` *(new)*

- [x] `TestOnChainCsvReader#test_parses_all_columns`; given the real `resources/result/2025/bera_transactions.csv` header, expects each row parsed into an `OnChainTxRow` with all 15 fields populated correctly (amount_raw as int, amount_decimals as int, direction in {in,out,unknown}).
- [x] `TestOnChainCsvReader#test_amount_raw_is_int_not_float`; given a row with `amount_raw=1000000000000000000`, expects `amount_raw` is `int(10**18)`, never `float`.
- [x] `TestOnChainCsvReader#test_decimal_overflow_clamped`; given a row with `amount_decimals=77` (attacker-controlled, per Attacker finding F5), expects the reader clamps to `[0,36]`, logs WARNING, and emits the leg with a review flag (never computes `10**77`).
- [x] `TestOnChainCsvReader#test_skips_blank_rows_and_handles_bom`; given a CSV with BOM + trailing blank lines, expects clean parse.
- [x] Run → expect RED.
- [x] Implement. Add the decimal clamp `[0,36]` with WARNING + review flag (Attacker F5 mitigation). Catch `MemoryError`/`OverflowError` in the decode except tuple.
- [x] Run → expect GREEN.
- [x] Commit: `feat(on-chain): add CSV reader for bera_transactions.csv (with decimal-overflow guard)`

### Task 8: LP-token autodiscovery - subgraph snapshot + bytecode fingerprint + tx-pattern provenance (decision #11)

Files:
- `src/tax_reporting/infrastructure/on_chain/lp_autodiscovery.py` *(new)*
- `src/tax_reporting/infrastructure/on_chain/rpc_client.py` *(new)*
- `src/tax_reporting/application/on_chain_config.py` - extend to load + schema-validate the snapshot
- `resources/source/2025/berachain_lp_snapshot.json` *(new)*
- `resources/source/example/2025/berachain_lp_snapshot.json` *(new)*
- `tests/unit/infrastructure/test_lp_autodiscovery.py` *(new)*

- [x] `TestLpAutodiscovery#test_snapshot_primary_hit`; given a token_address present in the snapshot's `Pair`/`KodiakVault.outputToken`/`stakingToken` lists, expects `is_lp_token(addr)` returns True via the snapshot path (no RPC call).
- [x] `TestLpAutodiscovery#test_bytecode_fallback_v2_pair`; given a token_address NOT in snapshot whose runtime bytecode keccak == `0x4a274065...` (UniswapV2Pair), expects `is_lp_token(addr)` returns True via the RPC fallback (one `eth_getCode` call).
- [x] `TestLpAutodiscovery#test_bytecode_fallback_island_proxy`; given a token_address NOT in snapshot whose `implementation()` resolves to `KodiakIsland` impl `0xCFe9Ee61...`, expects True via the RPC fallback.
- [x] `TestLpAutodiscovery#test_unknown_token_returns_false`; given a token_address not in snapshot and not matching any bytecode fingerprint, expects False + a review flag (never silently LP-classify an unknown address).
- [x] `TestLpAutodiscovery#test_snapshot_freshness_check`; given a snapshot whose `snapshot_as_of_block` predates the tax year's latest tx block, expects a WARNING (M2).
- [x] `TestLpAutodiscovery#test_snapshot_schema_validation`; given a snapshot missing `subgraph_version` or with a null `token_address` field, expects `ConfigurationError` (fail-loud, M2).
- [x] `TestLpAutodiscovery#test_rpc_fallback_timeout_and_cap`; given 100 unknown tokens, expects the RPC fallback honors per-call timeout, max-retries, and a hard cap (e.g. 50); beyond the cap, marks remaining as Unknown + review (MO1).
- [x] Run → expect RED.
- [x] Implement. `rpc_client.py` mirrors `etherscan_client.py` retry/backoff/timeout/secret-redaction. The snapshot loader validates required fields (`snapshot_as_of_block`, `snapshot_as_of_date`, `subgraph_version`, non-null addresses) and the expected count band. Pin the subgraph version (not `latest`) in the refresh script.
- [x] Run → expect GREEN.
- [x] Commit: `feat(on-chain): LP-token autodiscovery (subgraph snapshot + bytecode fallback + tx-pattern provenance)`

### Task 9: `berachain_processor.py` - classify `OnChainTxRow` → `OnChainTransaction` (the BERA processor)

The per-chain processor. Coordinates LP-autodiscovery, the contract registry, and the leg-pattern classifier. Stays under the 1000-line guideline by keeping classification pure (no I/O).

Files:
- `src/tax_reporting/infrastructure/on_chain/berachain_processor.py` *(new)*
- `resources/source/2025/berachain_contracts.json` *(new)* - ships EMPTY `operator_country` (B3)
- `resources/source/example/2025/berachain_contracts.json` *(new)*
- `tests/unit/infrastructure/test_berachain_processor.py` *(new)*

- [x] `TestBerachainProcessor#test_simple_swap`; given a BIDIRECTIONAL tx with 1 in-asset ↔ 1 out-asset (the 43-tx shape), expects one `Event(Swap)`.
- [x] `TestBerachainProcessor#test_lp_deposit`; given a BIDIRECTIONAL tx receiving an LP token (autodiscovery-confirmed), expects one `Event(LiquidityDeposit, SubType=internal_transfer)`.
- [x] `TestBerachainProcessor#test_multi_token_reward_claim`; given the BM tx (40 legs, 14 distinct reward assets), expects 14 `Event(Reward)` rows, one per asset, each with summed amount (matches Koinly's behavior).
- [x] `TestBerachainProcessor#test_gas_only_tx_emits_gasburn`; given a GAS_ONLY tx (139-tx shape), expects one `Event(GasBurn)` so the gas isn't lost.
- [x] `TestBerachainProcessor#test_reward_claim_then_swap_splits`; given a tx that claims a reward AND swaps it (both legs present, distributor + DEX router touched), expects TWO Events (Reward + Swap) linked by parent_event_id (the split model).
- [x] `TestBerachainProcessor#test_gas_attaches_to_parent_tx`; given any tx with gas, expects `OnChainTransaction.gas` populated and no Event carries gas.
- [x] `TestBerachainProcessor#test_spam_airdrop_tagged_not_dropped`; given an inflow from an unrecognized sender (the `WWW.BERA777.XYZ` case), expects `Event(Reward, SubType=spam)` + review flag, never dropped.
- [x] `TestBerachainProcessor#test_unknown_direction_does_not_misclassify`; given a leg with direction=`unknown`, expects the processor logs WARNING and emits `Event(Unknown)` + review (does not guess).
- [x] `TestBerachainProcessor#test_reward_distributor_country_falls_through_to_chain`; given a BGT reward from the Distributor `0xd2f19a79`, expects NO contract-level `operator_country` is set (B3: falls through to chain-level VG).
- [x] `TestBerachainProcessor#test_unverified_sender_reward_is_spam`; given a Reward from a sender NOT in the contract registry (Attacker F4 mitigation), expects SubType=`spam` + review flag, never a clean `staking` Reward.
- [x] Run → expect RED.
- [x] Implement. The contract registry loader validates `operator_country` against a closed ISO-3166 enum + requires a citation URL field when present (Attacker F1 mitigation). Lower-case normalize wallet_address before direction equality (Attacker F6 mitigation). Run-level invariant: if >1% of a wallet's legs are `unknown`-direction, raise `FileProcessingError`.
- [x] Run → expect GREEN.
- [x] Commit: `feat(on-chain): berachain processor (classify + tag with EventType/SubType)`

### Task 10: `on_chain_th_adapter.py` - project `OnChainTransaction` → `TransactionHistoryRow` (Koinly-compat)

Files:
- `src/tax_reporting/application/on_chain_th_adapter.py` *(new)*
- `tests/unit/application/test_on_chain_th_adapter.py` *(new)*

- [x] `TestOnChainThAdapter#test_one_row_per_event`; given an `OnChainTransaction` with 2 Events, expects 2 `TransactionHistoryRow`s sharing `tx_hash` with distinct `event_id`.
- [x] `TestOnChainThAdapter#test_event_to_koinly_type_mapping`; given each EventType, expects the mapped Koinly Type/Tag (Swap→exchange/empty, Reward→crypto_deposit/Reward, LiquidityDeposit→transfer/Liquidity in, GasBurn→crypto_withdrawal/Cost, etc.).
- [x] `TestOnChainThAdapter#test_carrier_row_gas_native_leg_first`; given a tx with gas + a Swap Event derived from the native leg, expects `Fee Amount` on the Swap's row and `Fee Amount` empty on other rows.
- [x] `TestOnChainThAdapter#test_carrier_row_gas_no_native_leg`; given a tx with gas but no native leg (pure ERC-20 reward), expects `Fee Amount` on the FIRST emitted row.
- [x] `TestOnChainThAdapter#test_gasburn_row_fee_empty`; given a GasBurn Event, expects the projected row has `Sent Amount`=gas, `Fee Amount` empty (B5: gas isn't a fee on itself; carrier-row rule skips GasBurn rows).
- [x] `TestOnChainThAdapter#test_txsrc_txdest_populated_correctly`; given an Event, expects `tx_src`=from_address and `tx_dest`=to_address of the representative leg, `tx_hash`=real hash (satisfies the resolver AND token_origin's TxHash read per Task 4).
- [x] `TestOnChainThAdapter#test_single_row_satisfies_all_three_consumers`; given a representative Event for EACH EventType, expects the projected `TransactionHistoryRow` simultaneously satisfies: (a) `tx_correlation_key_resolver` (non-None `tx_hash` + populated `event_id`), (b) `token_origin._index_withdrawal` AND `_index_row` (non-empty `TxHash` for the withdrawal path; non-empty `TxSrc`/`TxDest` where the exchange/transfer provenance path reads them), (c) `fee_filter` (`Type`, `Fee Amount`, `Fee Currency`, `Sent Amount`, `Net Value (EUR)` all present-or-explicitly-empty per each consumer's contract). **This is the test that would have caught B1** (review F6: three consumers read contradictory column subsets off one row; per-EventType mapping tests don't encode the cross-consumer assertion).
- [x] `TestOnChainThAdapter#test_module_docstring_marks_lifecycle`; the module docstring MUST declare this module exists ONLY to bridge to the Koinly-shaped TransactionHistoryRow and name the carrier-row rule as a non-domain accommodation (Future Maintainer F5 mitigation).
- [x] Run → expect RED.
- [x] Implement. The Event→Type/Tag mapping is a single dict (easy to audit). The carrier-row rule has the explicit GasBurn exception.
- [x] Run → expect GREEN.
- [x] Commit: `feat(on-chain): adapter projects OnChainTransaction to TransactionHistoryRow (Koinly-compat)`

### Task 11: Wire the on-chain TH path into `main.py` behind `on_chain_th_wallets` + fail-loud (M1)

**Depends on Task 5's bridge decision** (review F4-r2-Low): if Task 5 chose bridge option (a) - the adapter serializes rows to a TH-shaped CSV with `event_id` - then `main.py` writes that CSV to the same location the pipeline reads TH from, and the existing `remove_transaction_fees(transaction_history_file)` call picks it up unchanged. If bridge option (b) was chosen instead, `crypto_reporting.py:451-453` must be updated to pass `list[TransactionHistoryRow]`. This task inherits the choice silently unless noted; record it in the commit.

Files:
- `src/tax_reporting/main.py`
- `src/tax_reporting/config.py`
- `tests/end_to_end/test_on_chain_bera_opted_in.py` *(new)*

- [x] `TestOnChainBeraOptedIn#test_opted_in_wallet_uses_onchain_path`; given `on_chain_th_wallets=[BERA]` and the BERA CSV present, expects the BERA wallet's TH rows come from the on-chain adapter (distinct event_ids) and other wallets stay Koinly.
- [x] `TestOnChainBeraOptedIn#test_opted_in_parse_failure_raises`; given `on_chain_th_wallets=[BERA]` and a parse failure injected in the BERA processor, expects `ReportGenerationError` propagates (NOT swallowed by `main.py:293`'s broad except) (M1).
- [x] `TestOnChainBeraOptedIn#test_collection_only_path_still_soft_fails`; given `on_chain_th_wallets` unset, expects a fetcher failure still logs WARNING and continues (the broad except is preserved for the collection-only path).
- [x] `TestOnChainBeraOptedIn#test_opted_in_reconciliation_diff`; given `on_chain_th_wallets=[BERA]`, expects the reconciliation sheet shows the documented divergences (gas surfaced; spam included; multi-leg compression differs) and no others.
- [x] Run → expect RED.
- [x] Add `on_chain_th_wallets` to `[TAX JURISDICTION]` in `config.py` (default empty list). In `main.py`, when the flag lists a wallet, run the on-chain CSV reader → processor → adapter and substitute those rows for that wallet in the TH fed to the pipeline; wrap THIS path in `try/except ReportGenerationError` (fail-loud), keeping the broad `except Exception` ONLY around `run_on_chain_fetch` (collection). Stamp `extract.xlsx` per-wallet source provenance (M4).
- [x] Run Task 1 characterization → expect GREEN (flag unset → byte-identical).
- [x] Run → expect GREEN.
- [x] Commit: `feat(main): wire on-chain TH behind on_chain_th_wallets flag; fail-loud for opted-in wallets`

### Task 12: Reconciliation sheet - per-wallet source provenance + delta block (M3; folds review F9)

**Review F9:** `CryptoTaxReport.reconciliation` is a `CryptoReconciliationSummary` (`crypto_reporting.py:637,681`) with a FIXED field set, rendered by `write_crypto_reconciliation_sheet` (`crypto_reconciliation_sheet.py:16`). "Per-wallet source provenance + delta block" is a schema extension, not a wiring tick - this task sizes the schema explicitly.

Files:
- `src/tax_reporting/application/crypto/entities.py` - `CryptoReconciliationSummary` lives here at `:504` (review F3-r2: NOT `domain/crypto_report.py`); extend the dataclass
- `src/tax_reporting/application/persisting/crypto_reconciliation_sheet.py` - extend the writer
- `src/tax_reporting/application/crypto_reporting.py` - populate the new fields when building `CryptoTaxReport`
- `tests/unit/application/test_reconciliation_on_chain.py` *(new)*

- [x] `TestReconciliationOnChain#test_per_wallet_source_provenance`; given a run with `on_chain_th_wallets=[BERA]`, expects the reconciliation sheet shows BERA=on-chain, other wallets=Koinly, with per-wallet row counts.
- [x] `TestReconciliationOnChain#test_delta_block_when_flag_on`; given the flag on, expects a delta block listing rows reclassified, rewards added, gas added, LP reclassified (Koinly→on-chain).
- [x] `TestReconciliationOnChain#test_no_delta_block_when_flag_off`; given the flag unset, expects no delta block (today's behavior; `on_chain_delta is None`).
- [x] `TestReconciliationOnChain#test_new_fields_serialize`; given a `CryptoReconciliationSummary` with the new fields populated, expects round-trip serialization preserves them (review F9: schema extension needs a serialization test).
- [x] Run → expect RED.
- [x] Define the new `CryptoReconciliationSummary` fields with explicit dataclass shapes: `per_wallet_source_provenance: list[WalletSourceProvenance]` (where `WalletSourceProvenance` carries `wallet_label, source_kind: Literal["koinly","on_chain"], row_count`) and `on_chain_delta: OnChainDeltaBlock | None` (where `OnChainDeltaBlock` carries `rows_reclassified, rewards_added, gas_added, lp_reclassified` counts + sample hashes). Extend `write_crypto_reconciliation_sheet` to render them. Populate from the adapter's reconciliation record.
- [x] Run → expect GREEN.
- [x] Commit: `feat(reconciliation): per-wallet source provenance + on-chain delta block (extends CryptoReconciliationSummary schema)`

### Task 13: Post-cutover integrity invariants (MO2) + documented accepted risks (A1)

Files:
- `tests/end_to_end/test_on_chain_integrity_invariants.py` *(new)*
- `docs/maintenance/crypto_implementation_guidelines.md` - add a section on on-chain-source integrity invariants
- `docs/maintenance/tax/crypto-origin/sources.md` - record the B3 source-priority rule (primary over secondary)

- [x] `TestOnChainIntegrity#test_no_single_registry_entry_dominates`; given a run, expects no single contract-registry entry accounts for >30% of tags (catches a typo'd registry entry tagging 500 txs, Attacker F7).
- [x] `TestOnChainIntegrity#test_no_decimal_out_of_range`; given a run, expects zero legs with `amount_decimals` outside `[0,36]`.
- [x] `TestOnChainIntegrity#test_unknown_direction_rate_under_threshold`; given a run, expects <1% of legs have direction=`unknown`.
- [x] `TestOnChainIntegrity#test_operator_country_closed_enum`; given the contract registry, expects every `operator_country` value is a valid ISO-3166 alpha-2 code (Attacker F1 cheap mitigation).
- [x] Run → expect RED.
- [x] Implement the invariant checks as post-run assertions (warn or fail per severity). Document the accepted risk A1 (attacker-with-config-write-access; single-user tool; cheap mitigations added, crypto signing skipped) in `crypto_implementation_guidelines.md`. Record the B3 source-priority rule in `sources.md`.
- [x] Run → expect GREEN.
- [x] Commit: `feat(on-chain): post-cutover integrity invariants + documented accepted risks`

### Task 14: Documentation + AGENTS.md update

Files:
- `docs/maintenance/glossary.md` - already updated with Transaction Source / Processor / On-chain-native model terms (grilling session); verify completeness.
- `docs/maintenance/crypto_implementation_guidelines.md` - on-chain-source section (processor contract, LP-autodiscovery, fail-loud, reconciliation).
- `docs/maintenance/tax_reporting_guidelines.md` - note the on-chain TH source as an alternative to Koinly per wallet.
- `docs/maintenance/koinly_guidelines.md` - note that Koinly is one of multiple sources (Aggregator) and the on-chain path is a per-wallet alternative.
- `README.md` - document `on_chain_th_wallets` config field and `BERA_CHAIN_API_KEY` (already partially documented).
- `docs/maintenance/development_lessons.md` - capture the premortem lessons (the consumer-list-was-incomplete anti-pattern; the "adapter is mechanical" unverified-claim anti-pattern; the source-priority rule).

- [x] Verify glossary terms (Transaction Source, Processor, OnChainTransaction, Event, Leg, EventType/SubType, Adapter) are complete and consistent with the shipped code.
- [x] Add the on-chain-source section to `crypto_implementation_guidelines.md` covering: processor contract (one per ProducerKind/producer_name), LP-autodiscovery three-layer stack, fail-loud for opted-in wallets, reconciliation-sheet wiring.
- [x] Update `README.md` `[TAX JURISDICTION]` section with `on_chain_th_wallets`.
- [x] Add the premortem lessons to `development_lessons.md` (consumer list must be grepped not enumerated; "compat layer" still needs downstream contracts audited; source-priority: primary over secondary).
- [x] Commit: `docs(on-chain): document on-chain transaction source, LP-autodiscovery, and premortem lessons`

### Task 15: Final validation + characterization re-run

- [x] Run full suite: `uv run pytest` → all GREEN.
- [x] Re-run Task 1 characterization on real Koinly data → byte-identical (the safety net held through all migrations).
- [x] Run the opted-in BERA end-to-end → reconciliation diff shows only documented divergences.
- [x] Run the Validation Commands block → all pass.
- [x] Commit: `test(on-chain): final validation (Koinly byte-identical; BERA reconciliation clean)`
