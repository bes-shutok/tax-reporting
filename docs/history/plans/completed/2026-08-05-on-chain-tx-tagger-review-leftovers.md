# Plan: On-chain tx tagger review leftovers (delete classify_many + wire check_freshness + doc sweep)

Resolves the non-blocking leftover findings from the two prior plans' Phase-3
round-2 reviews on branch `2026-08-02-on-chain-tx-tagger` vs `master`.

Python testing guidance: `docs/maintenance/python_guidelines.md`.

## Gist & Examples

Three buckets:

1. **Delete dead `classify_many`**: after the F4 cap moved into `is_lp_token`
   (prior plan Task 6), `classify_many` is a thin delegation wrapper with ZERO
   production callers (only its own tests call it; the processor calls
   `is_lp_token` directly per-leg). Keeping it is a maintenance trap: a future
   reader may assume it is the batch entry point and add cap-bypassing logic
   there again, the exact F4 regression the cap-move prevented. Delete the
   method, collapse its two dedicated cap tests into the `is_lp_token` cap tests
   (the `is_lp_token`-direct tests already pin the same invariants), and update
   the stale docstrings/comments that still attribute the cap to `classify_many`.

2. **Wire `check_freshness`**: the M2 snapshot-freshness WARN (`LpAutodiscovery
   .check_freshness(latest_tx_block)`) exists but has NO production caller.
   The substituter's `maybe_substitute` has both the snapshot (via `autodiscovery`)
   and the processed `txs` (each `OnChainTransaction` carries `block_number`).
   Wire the call after `processor.process(on_chain_rows)` and before the merge:
   compute `latest_tx_block = max(t.block_number for t in txs)` (guarded for
   empty txs) and call `autodiscovery.check_freshness(latest_tx_block)`. This
   closes the M2 stale-snapshot phantom-gain signal operationally.

3. **Doc accuracy sweep**: amend the design-record M2 "layer 2 designed but
   unbuilt" (now false: Task 7 wired it); add `ON_CHAIN_RPC_URL` to the
   `crypto_implementation_guidelines.md` fallback bullet; fix the README
   grammar nit (orphaned ON_CHAIN_RPC_URL sentence).

## Evaluation Criteria

- correctness: `classify_many` deletion preserves all cap behavior (the
  `is_lp_token`-direct tests still pass); `check_freshness` fires only when the
  snapshot predates the latest tx (not on every run); empty-txs case handled.
- test coverage: the collapsed `is_lp_token` cap tests still assert exact flag +
  exact RPC call count; a new test pins `check_freshness` is CALLED in
  `maybe_substitute` with the correct latest block.
- doc accuracy: no stale "designed but unbuilt"; the config key is documented
  where the fallback is described.

**Done when:**
- All new RED tests pass; `uv run pytest -q` full suite green.
- `! grep -rn 'classify_many' src/` returns empty (method + stale comments gone).
- `! grep -rn 'designed but unbuilt' docs/architecture/on-chain-tx-design.md` empty.
- The `check_freshness` wiring test passes.

**Ship when:** N/A (local-only).

## Review Scope

**Explicit must-fix:**
- `src/tax_reporting/infrastructure/on_chain/lp_autodiscovery.py` (delete classify_many; update docstrings)
- `src/tax_reporting/application/on_chain_th_substitution.py` (wire check_freshness)
- `tests/unit/infrastructure/test_lp_autodiscovery.py` (collapse classify_many tests)
- `tests/end_to_end/test_on_chain_bera_opted_in.py` (check_freshness wiring test, if the wiring is observable there; otherwise a substituter-level test)
- `docs/architecture/on-chain-tx-design.md` (M2 amendment)
- `docs/maintenance/crypto_implementation_guidelines.md` (ON_CHAIN_RPC_URL)
- `README.md` (grammar nit)

**Plan-related extension**: any causally-related file.

**Out of scope:** the test-naming/forward-looking nits (F11 redaction test name, test_rpc_fallback_timeout_and_cap name, isinstance check, defense-in-depth-at-sink, noqa comment).

## Design Invariants (CR Guard)

- **F4 cap preserved.** Deleting `classify_many` must not change the cap behavior
  of `is_lp_token` (the production entry point). The `is_lp_token`-direct tests
  pin it.
- **check_freshness is a WARN, not a fail.** A stale snapshot must NOT abort the
  run; the WARN names both blocks so the user can refresh. The fail-loud M1
  boundary stays unchanged.
- **Empty txs guard.** If `processor.process` returns an empty list, skip the
  check (no tx blocks to compare; `max()` on empty raises ValueError).
- **Koinly-byte-identical default (flag off).** The check_freshness wiring runs
  only inside `maybe_substitute`, which is only called on the opted-in path.

## Validation Commands

```bash
uv run pytest tests/unit/infrastructure/test_lp_autodiscovery.py \
  tests/end_to_end/test_on_chain_bera_opted_in.py \
  tests/end_to_end/test_on_chain_koinly_characterization.py \
  tests/end_to_end/test_on_chain_integrity_invariants.py \
  tests/unit/infrastructure/test_berachain_processor.py -q

uv run pytest -q

# classify_many fully removed (method + stale comments + test names):
! grep -rn 'classify_many' src/ tests/

# M2 "designed but unbuilt" amended:
! grep -rn 'designed but unbuilt' docs/architecture/on-chain-tx-design.md
```

## Tasks

### Task 1: Delete dead classify_many + update stale docstrings

Files:
- `src/tax_reporting/infrastructure/on_chain/lp_autodiscovery.py`
- `tests/unit/infrastructure/test_lp_autodiscovery.py`

- [x] `TestLpAutodiscovery#test_classify_many_deleted_no_production_caller`; given the repo, expects `grep -rn 'classify_many' src/` returns empty (the method, the module docstring reference, the `_DEFAULT_CAP` comment, the `__init__` cap-param docstring, the is_lp_token comments, all updated to name `is_lp_token`, not `classify_many`). This is a characterization test of the deletion.
- [x] `TestLpAutodiscovery#test_is_lp_token_cap_preserved_after_classify_many_deletion`; given `cap=2` + 4 distinct non-snapshot addresses via REPEATED `is_lp_token` calls (the production path), expects exactly 2 RPC calls and 2 CAP_REACHED (the collapsed regression net; this already exists as `test_is_lp_token_respects_cap_independent_of_classify_many`; verify it still passes after the deletion, and that `test_classify_many_cap_unchanged_after_move` is REMOVED since its subject no longer exists).
- [x] Run -> expect GREEN (the deletion is a refactor; the is_lp_token tests are the regression net)
- [x] Delete the `classify_many` method (lines ~237-258). Remove `test_classify_many_cap_unchanged_after_move` and `test_rpc_fallback_timeout_and_cap` (the latter only exercises `classify_many`; its cap assertion is loose and now-orphaned, its name promised "timeout" it never tested, per the testing worker). Update all stale docstrings/comments that reference `classify_many` as the cap owner (module docstring ~line 27; `_DEFAULT_CAP` comment ~line 56; `__init__` cap-param docstring ~line 126; is_lp_token comments ~lines 156, 189-191) to name `is_lp_token` instead. Rename `test_is_lp_token_respects_cap_independent_of_classify_many` -> `test_is_lp_token_respects_cap` (drop the now-meaningless classify_many reference); `test_cap_resets_per_instance` stays. These two are the surviving regression net. NOTE (review-plan F3): the `! grep` validation must cover BOTH `src/` AND `tests/` so a stale token left in a test name (e.g. the old rename target) fails the gate.
- [x] Run -> expect GREEN
- [x] Commit: `refactor(on-chain): delete dead classify_many; is_lp_token is the sole cap entry point` (c364951)

### Task 2: Wire check_freshness into maybe_substitute

Files:
- `src/tax_reporting/application/on_chain_th_substitution.py`
- `tests/end_to_end/test_on_chain_bera_opted_in.py` (or a substituter-level test)

- [x] `TestOnChainBeraOptedIn#test_stale_snapshot_warns_via_check_freshness`; given a snapshot whose `snapshot_as_of_block` predates the latest tx block in the bera CSV, expects `maybe_substitute` logs a WARNING containing `"snapshot_as_of_block"` and `"predates"` (the check_freshness message), AND the run still succeeds (WARN, not fail). NOTE (review-plan F1): the example snapshot's `snapshot_as_of_block` is `1_500_000` (`resources/source/example/2025/berachain_lp_snapshot.json`), but the shared `_bera_csv_rows()` helper hardcodes `block_number=1000/1001`, far below 1_500_000. So the stale-snapshot test MUST construct bera rows with `block_number > 1_500_000` (e.g. 1_600_000). Parametrize `_bera_csv_rows(*, block_number=...)` (or build a dedicated stale-fixture row string) so the test can set a block_number above the snapshot threshold. An implementer who skips this will see the WARNING NOT fire and misdiagnose it as a wiring bug.
- [x] `TestOnChainBeraOptedIn#test_fresh_snapshot_no_warning`; given a snapshot whose snapshot_as_of_block >= the latest tx block (use the default `_bera_csv_rows()` block_number 1000/1001, which is below the example snapshot's 1_500_000), expects NO check_freshness WARNING fires.
- [x] Run -> expect RED (today check_freshness is never called from maybe_substitute)
- [x] In `OnChainThSubstituter.maybe_substitute`, after `txs = processor.process(on_chain_rows)` (~line 261) and after the integrity check, before the merge: if `txs` is non-empty, compute `latest_tx_block = max(t.block_number for t in txs)` and call `autodiscovery.check_freshness(latest_tx_block)`. Guard the empty case (skip if no txs). The call is a WARN-only side effect (check_freshness does not raise); it must NOT be inside the fail-loud try/except for merge errors (it runs before the merge). Place it where it logs the staleness signal as early as possible.
- [x] Run -> expect GREEN
- [x] Commit: `feat(on-chain): wire check_freshness WARN into the opted-in substitution path` (c95335f)

### Task 3: Doc accuracy sweep (M2 amendment + guidelines + README)

Files:
- `docs/architecture/on-chain-tx-design.md`
- `docs/maintenance/crypto_implementation_guidelines.md`
- `README.md`

Doc-only.

- [x] Amend the M2 paragraph (`docs/architecture/on-chain-tx-design.md` ~line 389): append a RESOLVED note that layer 2 (bytecode fallback) shipped behind `ON_CHAIN_RPC_URL` (Task 7 of the follow-ups plan), and that `check_freshness` is now wired (Task 2 of this plan) so a stale snapshot emits a WARN. Keep the original design-time text; append, do not rewrite.
- [x] Amend the M2 disposition (~line 420): note that the WARN/fail arm is now wired (check_freshness called from OnChainThSubstituter.maybe_substitute).
- [x] In `docs/maintenance/crypto_implementation_guidelines.md` (~line 1823, the bytecode-fallback bullet): add a clause naming `ON_CHAIN_RPC_URL` as the [TAX JURISDICTION] config key that gates the fallback, noting it is optional and the default (unset) is snapshot-only (Koinly-byte-identical). ALSO (review-plan F2): the layer-1 bullet (~line 1821) credits the loader with the freshness WARN that actually lives in `LpAutodiscovery.check_freshness` (now wired into `OnChainThSubstituter.maybe_substitute` by Task 2); correct the attribution so the doc names `check_freshness` as the WARN owner, not the loader.
- [x] In `README.md` (~line 76): fix the grammar of the ON_CHAIN_RPC_URL sentence so it is not orphaned in the config enumeration (join with ", and" or start a new sentence).
- [x] `! grep -rn 'designed but unbuilt' docs/architecture/on-chain-tx-design.md` -> empty
- [x] Commit: `docs(on-chain): amend M2 design record (layer 2 wired); document ON_CHAIN_RPC_URL in guidelines; fix README grammar`
