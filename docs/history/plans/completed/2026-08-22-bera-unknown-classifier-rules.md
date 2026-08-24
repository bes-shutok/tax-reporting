# Plan: Bera-Native Classifier Rules for the Unknown Family (Re-staking, Zaps, Position Tokens)

Language testing traps: `~/Projects/.ai-playbook/python_guidelines.md` (pytest guards: `pytest.raises` needs `match=`; hermeticity env-pin).

## Terms

- **Zap**: a single transaction that swaps and deposits in one step (wallet sends BERA and/or tokens to a router; the router adds liquidity and/or mints a position); the wallet's receives may be executed by contracts via internal calls.
- **Island**: a Kodiak vault that accepts an AMM LP token and minters a receipt ("island") token; re-staking means sending an LP token into such a vault.
- **LST / position token**: liquid-staking or staking-position receipt token (iBGT, LBGT, LAIR, iBERA) or a Koinly POS#-style position entry; identifies a staked position, not a freely traded asset.
- **Gas carrier**: a zero-value native (BERA) outflow leg that exists only to pay gas; excluded from the economic leg partition (design record Q6).
- **Receipt leg**: the incoming leg a wallet receives for a deposit/swap (LP token, island token, LST). "Receipt leg" being absent from the on-chain export while existing on-chain is the export-completeness gap.
- **Internal transaction**: a native-value transfer performed by a contract inside a transaction (not a top-level tx, not an ERC-20 Transfer log); invisible to the `txlist` and `tokentx` endpoints, served by `txlistinternal`.
- **Cluster signature**: the PII-free semantic key of a validation discrepancy cluster (see `docs/maintenance/glossary.md`).

## Gist & Examples

All 8 remaining `missing_rule` Unknown clusters (47 divergent records on the 2025 baseline, final 2026-08-22 run) root in the same fallback: `_classify_events` shape 9, a pure outflow with no in-legs. The leg shapes are uniform:

- 26x `Unknown|koinly=crypto_withdrawal/Cost+transfer/To pool|lp=true`: send a KODI LP token (BERA leg is the gas carrier). Island/vault re-staking; Koinly's side is the user's manual `To pool` marks plus gas Cost rows.
- 8x + 1x `Unknown|koinly=exchange/`: send BERA plus an LST (LBGT, LAIR, iBGT). Koinly recorded a real `exchange` (both sides), so Koinly's indexer SAW receives our export does not carry.
- 4x/3x/1x variants: BERA plus a KODI LP token, or a 3-asset zap send (BUSD + WETH + BERA), or iBGT.

Two distinct defects can produce these shapes, and the plan refuses to guess which: (A) the export is incomplete (receives exist on-chain but are missing from `bera_transactions.csv`, e.g. native value returned via an internal transaction that `txlist`/`tokentx` never serve); (B) the operations genuinely mint nothing to the wallet (position extended in-place) and need native classification rules. Koinly's `exchange/` rows are direct evidence that at least the LST clusters are (A). Task 1 settles each cluster with on-chain ground truth; Tasks 2 and 3 then execute per that routing table.

Concrete before/after (26x family): today a tx with legs `BERA out (0-value carrier) + KODI iBERA-iBGT out` emits `Event(Unknown) + review`, and every Koinly row reads as on-chain-zero. After: if the island receipt is recovered into the export (Task 2), the shape becomes bidirectional and classifies as a vault deposit; if nothing is received on-chain, the pure-outflow rule (Task 3) classifies it as `LiquidityDeposit` with the LP leg. Either way the record stops being Unknown. No comparator table widening is presupposed: `Cost` rows are exempt from the type comparison (they route to the gas-surface amount comparison) and `LiquidityDeposit` already accepts `transfer/To pool`, so Task 4 is derive-first - it adds an entry only if a real type mismatch survives reclassification, with a recorded skip path otherwise (verified on HEAD by the r1 review).

## Evaluation Criteria

**Quality dimensions:**
- Correctness: per-family classifier tests with synthetic fixtures mirroring the real leg shapes (given/expects below); full suite green (baseline 2236 on 39eaf4c, after the UL#-citation conformance fix).
- Data fidelity: every routing decision in Task 1 cites on-chain ground truth (RPC receipt logs), not inference from either vendor's export.
- Validation-gate progress: after implementation, none of the 8 dispositioned Unknown signatures still occurs in `--validate-on-chain-th 2025`; any NEW Unknown signature is dispositioned with evidence or surfaced to the user, never silently accepted.
- Maintainability: new rules slot into the documented dispatch order (docstring updated in the same change); `berachain_processor.py` respects the module size limits (extract if > 1,000 lines).

**Done when:**
- Tasks landed on this branch with per-task commits; `BERA_CHAIN_API_KEY= uv run pytest -q` green.
- Harness re-run recorded: the 8 Unknown blocks' fix-landed assertions pass; residual divergences are either matched or attributed to the already-dispositioned rendering family (routed to the multi-row rendering plan).
- Comparator compatibility resolved: either a recorded PD-010 amendment (if a real type mismatch survived) or the derive-first skip evidence line; `on_chain_validation.md` and `glossary.md` swept; dispositions outcomes recorded without field edits (comment-only annotations or task log).

**Ship when:**
- The `ON_CHAIN_TH_WALLETS` flag flip stays gated on the whole program (this plan AND the multi-row rendering plan reaching zero-exit on the 2025 baseline); nothing in this plan flips it.

## Review Scope

**Explicit must-fix**; findings on these paths are always in scope (review and fix if valid):

**Production code:**
- `src/tax_reporting/infrastructure/on_chain/berachain_processor.py`
- `src/tax_reporting/infrastructure/on_chain/etherscan_client.py` *(conditional, Task 2)*
- `src/tax_reporting/infrastructure/on_chain/bera_decoder.py` *(conditional, Task 2)*
- `src/tax_reporting/application/on_chain_fetcher.py` *(conditional, Task 2)*
- `src/tax_reporting/application/on_chain_validation/comparator.py` *(scoped: `EVENT_COMPATIBILITY` table only; all other functions frozen)*
- `docs/maintenance/project-decisions.md`, `docs/maintenance/on_chain_validation.md`, `docs/maintenance/glossary.md`

**Tests:**
- `tests/unit/infrastructure/test_berachain_processor.py`
- `tests/unit/infrastructure/test_etherscan_client.py` *(conditional, Task 2)*
- `tests/unit/infrastructure/test_bera_decoder.py` *(conditional, Task 2)*
- `tests/integration/test_on_chain_fetch_integration.py` *(conditional, Task 2)*
- `tests/unit/application/test_on_chain_validation_comparator.py`

**Plan-related extension**; implementation and review may change files not listed above. Treat a finding as in scope when it is **causally related to this plan**: it implements or completes a plan task, fixes a regression introduced by plan work, closes wiring or docs implied by an explicit must-fix change, or contradicts a contract the plan changed. If the link to the plan is weak or speculative, drop as out of scope with a one-line reason.

**Out of scope; reject unless plan-related:**
- `src/tax_reporting/application/on_chain_th_adapter.py` and every Koinly-path file: the adapter contract is frozen; one-row-per-event rendering belongs to the multi-row rendering plan. Residual amount mismatches caused by that rendering are recorded there, not fixed here.
- `src/tax_reporting/application/on_chain_th_substitution.py` wiring: unchanged by this plan EXCEPT the conditional registry injection at `_build_processor` when Task 1 routes an LST cluster to verdict (B) (named in Task 3 Files); no other substitution-path change is in scope.

## Design Invariants (CR Guard)

- **Frozen adapter contract**: the production TH adapter renders one row per Event; this plan must not change it. Reclassified txs whose Koinly side has more rows than the adapter renders will still diverge on amounts; that residue belongs to the rendering plan and must be recorded, not patched around.
- **PD-010 freeze**: `EVENT_COMPATIBILITY` edits land only as a recorded amendment (#4) in `project-decisions.md` with per-cluster evidence; amount comparison is never weakened (amendment #2 precedent).
- **Dispatch-order discipline**: `_classify_events` documents its shape list in the docstring; any new shape updates the docstring in the same change and states where it slots (earlier shapes consume later ones; e.g. a position-token rule must precede shape 7 Swap, which consumes every 1-in-1-out bidirectional shape).
- **Address-keyed identity**: family detection uses token addresses and LP-snapshot membership; never asset-name matching.
- **Fail-loud fallback stays**: `Event(Unknown) + review` remains the terminal shape; the run-level unknown-direction rate invariant is unchanged.
- **Fetch-client seams and guards**: any new fetch reuses `_fetch_with_block_pagination` (block-range + boundary-block drain, 2026-08-22 semantics), the `max_rows` ceiling binds inside every loop, tests patch the `_http_get_json` seam only.
- **Hermeticity and data hygiene**: tests read committed synthetic fixtures only; real tx hashes and wallet addresses appear only in gitignored artifacts (`resources/result/2025/*`, session logs under `docs/tmp/`), never in committed files.
- **Koinly-path characterization suites stay green and unmodified.**

## Validation Commands

```bash
# Tiered tests (agent shell; env pin keeps the fetcher off in _main-wiring tests)
BERA_CHAIN_API_KEY= uv run pytest tests/unit/infrastructure/test_berachain_processor.py \
  tests/unit/infrastructure/test_etherscan_client.py \
  tests/unit/infrastructure/test_bera_decoder.py \
  tests/unit/application/test_on_chain_validation_comparator.py -q

BERA_CHAIN_API_KEY= uv run pytest -q

# Full-year harness re-run (read-only; uses the already-fetched CSV)
BERA_CHAIN_API_KEY= uv run tax-reporting --validate-on-chain-th 2025 > /tmp/unknown-plan-harness.log 2>&1
rc=$?; echo "harness exit: $rc"
# Exit 3 is expected while the rendering workstream is open; the gate is the
# Unknown-family assertions below, not the exit code.

# None of the 8 dispositioned Unknown signatures may still occur.
SIGS=(
  "events=Unknown|koinly=crypto_withdrawal/Cost+transfer/To pool"
  "events=Unknown|koinly=exchange/|sender=unregistered|lp=false|fee=fee_column"
  "events=Unknown|koinly=crypto_withdrawal/+crypto_withdrawal/Cost|sender=unregistered|lp=true"
  "events=Unknown|koinly=crypto_withdrawal/Cost+exchange/|sender=unregistered|lp=false"
  "events=Unknown|koinly=crypto_withdrawal/Cost|sender=unregistered|lp=true"
  "events=Unknown|koinly=crypto_withdrawal/+crypto_withdrawal/Cost|sender=unregistered|lp=false"
  "events=Unknown|koinly=crypto_withdrawal/|sender=unregistered|lp=true"
  "events=Unknown|koinly=exchange/|sender=unregistered|lp=false|fee=none"
)
for s in "${SIGS[@]}"; do
  if grep -F "still occurring" /tmp/unknown-plan-harness.log | grep -qF "$s"; then
    echo "FAIL: Unknown cluster still occurring: $s"; exit 1
  fi
done
# No undispositioned Unknown cluster may remain.
if grep -F "undispositioned cluster still occurring" /tmp/unknown-plan-harness.log | grep -qF "events=Unknown"; then
  echo "FAIL: undispositioned Unknown cluster remains"; exit 1
fi
test -s /tmp/unknown-plan-harness.log || { echo "FAIL: harness log empty"; exit 1; }
echo "Unknown-family gate: PASS"
```

### Task 1: Investigation - on-chain ground truth for the 8 Unknown clusters

Files:
- `docs/tmp/execute-plan/2026-08-22-bera-unknown-classifier-rules/task-1-investigation.md` *(new, gitignored session log)*

- [x] For each of the 8 signatures in the Validation Commands `SIGS` list, pick 1-2 sample `Tx Hash` values from the gitignored diff CSV (`resources/result/2025/on_chain_th_validation_diff.csv`) and tabulate their export legs from `resources/result/2025/bera_transactions.csv` (asset, direction, `amount_raw`, `token_address`); expect pure outflows (BERA out + token(s) out, no in-legs) and record whether the BERA out-leg is the zero-value gas carrier.
- [x] For one sample of the 26x To-pool family, one of the 8x `exchange/` LST family, and the 3-asset zap (`BUSD + WETH + BERA` out), fetch ground truth: `eth_call`-free `eth_getTransactionReceipt` via `curl -X POST https://rpc.berachain.com` and decode every log into (token contract, from, to, amount) using the wallet address from the gitignored `resources/source/2025/chains.json` (never commit it); compare against the export legs.
- [x] Record per sample: receives that exist on-chain but are missing from the export, their mechanism (ERC-20 Transfer log to wallet vs native value via internal call), and native-value balance deltas not covered by any log.
- [x] Also record per family: whether an address-keyed identity source EXISTS today (island/vault tokens are LP-snapshot members; the 2025 snapshot was verified in r1 to contain only pool/vault/island tokens, so LST/position tokens like LBGT/LAIR/iBGT have NO registry) - Task 3 needs this to decide whether a position-token registry must be created.
- [x] Produce the routing table: per cluster signature, verdict (A) receives-missing-from-export, (B) nothing-received-on-chain, or (C) mixed; write it to the task log and update the Task 2/Task 3 scope notes below with the finalized per-family classification targets (which `EventType`, which legs economic) before executing them.
- [x] Confirm no sample tx hash or wallet address leaves the gitignored log: `git status --short` shows no new tracked-file changes from this task.

**Routing outcome (Task 1, 2026-08-22; full evidence in the gitignored task log):** no mixed clusters. Routed **A** (receives missing from export): sig 2 `exchange/|fee=fee_column` (native BERA via internal tx, the true `txlistinternal` case), sig 4 zap `Cost+exchange/` (ERC-721 position mint; NOT recoverable via `txlistinternal`), sig 8 `exchange/|fee=none` (ERC-721 position mint; BERA leg economic). Routed **B** (nothing received on-chain): sigs 1/3/5/7 (LP pure outflow, delta-gas=0) and sig 6 (iBGT pure outflow). All five B-family LP tokens are LP-snapshot members; LBGT/iBGT/position-NFT are not (registry required → created in Task 3). Per-family classification targets: LP pure-outflow (1/3/5/7) → `LiquidityDeposit` (LP leg, snapshot-gated); iBGT (6) → `LiquidityDeposit` (registry-gated); zap (4) and BERA+iBGT (8) → `LiquidityDeposit` with all non-gas out-legs economic (multi-leg deposit); sig 2 after Task 2 recovery is bidirectional and classifies via the existing Swap shape.

### Task 2 (conditional: execute iff Task 1 routed any cluster to A): Export completeness for receives

Files:
- `src/tax_reporting/infrastructure/on_chain/etherscan_client.py`
- `src/tax_reporting/infrastructure/on_chain/bera_decoder.py`
- `src/tax_reporting/application/on_chain_fetcher.py`
- `tests/unit/infrastructure/test_etherscan_client.py`
- `tests/unit/infrastructure/test_bera_decoder.py`
- `tests/integration/test_on_chain_fetch_integration.py`

- [x] `TestEtherscanClient#test_fetch_internal_txs_uses_block_pagination`; given the `_http_get_json` seam returning a full page then a partial page for `action=txlistinternal`, expects `fetch_internal_txs` to accumulate via the same block-range + boundary-drain loop as `fetch_normal_txs`.
- [x] `TestEtherscanClient#test_fetch_internal_txs_boundary_drain`; given a full page cutting inside a block that has more internal rows, expects the boundary block drained with no rows dropped (mirrors the tokentx drain tests).
- [x] `TestBeraDecoder#test_internal_native_receive_becomes_in_leg`; given an internal-tx row with native value to the wallet for a tx already carrying a token out-leg, expects the decoded rows to include the receive leg with direction `in`.
- [x] `TestBeraDecoder#test_internal_row_without_gas_price_still_decodes`; given an internal-tx row whose schema omits `gasPrice` but carries `gasUsed` (the real `txlistinternal` field set per the Etherscan API docs; r2 F3), expects the row to decode into a receive leg, not be silently skipped; fees are NOT attributed to internal rows (the parent tx's gas already lives on its `txlist` row - no double count).
- [x] `TestOnChainFetchIntegration#test_full_flow_includes_internal_receives`; given the seam serving txlist + tokentx + txlistinternal, expects the CSV to carry the internal receive row.
- [x] Run → expect RED: `BERA_CHAIN_API_KEY= uv run pytest tests/unit/infrastructure/test_etherscan_client.py tests/unit/infrastructure/test_bera_decoder.py tests/integration/test_on_chain_fetch_integration.py -q`
- [x] Implement: `fetch_internal_txs` delegating to `_fetch_with_block_pagination("txlistinternal", address)`; decoder + fetcher wiring; no changes to existing endpoint semantics.
- [x] Run → expect GREEN; commit: `feat(on-chain): fetch internal native receives (txlistinternal)`
- [x] Re-fetch the year from a shell exporting `BERA_CHAIN_API_KEY` (interactive user shell via `zsh -ic` if the agent shell lacks it), then re-run the harness and record which A-verdict clusters gained receive legs (task log). Outcome: cluster 2 gained receive legs (internal BERA in-leg confirmed in `bera_transactions.csv`); clusters 4/8 (ERC-721 mints) remain unrecovered by txlistinternal as predicted by Task 1.
- [x] N/A - Task 1 routed sigs 2/4/8 here (routing outcome above); endpoint implemented. (Review r3 F9 annotation.)

### Task 3: Classifier rules for the (remaining) pure-outflow and position-token shapes

Slot order (dispatch-order discipline; r1 F6, corrected by r2 F1): ONLY the bidirectional vault-withdraw rule (send position token, receive LP/underlying) slots BEFORE shape 6 - shape 6 would otherwise classify that shape as an AMM deposit, and it is empirically RED on HEAD today. The receive direction needs NO new rule: island/vault tokens are LP-snapshot members, so shape 6 already classifies receive-position-token shapes as `LiquidityDeposit` (verified GREEN on HEAD by r2); it is pinned by a characterization test so the new withdraw rule cannot consume it. The pure-outflow rules slot AFTER shape 8 (self-wallet outbound transfer keeps precedence).

Position-token identity (r1 F2): island/vault tokens are already LP-snapshot members (address-keyed), so vault rules gate on the existing snapshot. LST/position tokens (LBGT, LAIR, iBGT) have NO registry today. If Task 1 routes any LST cluster to (B) (pure outflow with nothing received on-chain), FIRST create `resources/source/2025/bera_position_tokens.json` (gitignored, address-keyed allowlist with provenance metadata, mirroring the LP snapshot pattern) plus its loader, and gate the LST rules on it. The registry's membership is derived from the FULL set of divergent Unknown-family records (every distinct LST token address in the routing table's families), never from 1-2 samples - the validation gate only catches a missing member late (r2 F5). If all LST clusters route to (A), no registry is created and no LST rule is written in this plan (record the decision).

Files:
- `src/tax_reporting/infrastructure/on_chain/berachain_processor.py`
- `tests/unit/infrastructure/test_berachain_processor.py`
- `resources/source/2025/bera_position_tokens.json` *(new, gitignored; conditional on LST routing to B)*
- `src/tax_reporting/infrastructure/on_chain/position_token_registry.py` *(new, conditional; the loader lives in its own sibling module, mirroring `lp_autodiscovery.py`'s single-concern pattern)*
- `src/tax_reporting/application/on_chain_th_substitution.py` *(conditional, same condition; registry injection into `_build_processor` - the sole production `BerachainProcessor` construction site - mirroring the LP snapshot injection)*
- `tests/unit/infrastructure/test_position_token_registry.py` *(new, conditional; loader tested against an in-memory/`tmp_path` fixture - the real gitignored registry is never opened by tests)*

- [x] `TestBerachainProcessor#test_pure_outflow_lp_token_send_is_vault_deposit`; given economic legs = a single LP-token out-leg (LP-snapshot member; BERA leg is the zero-value gas carrier), expects `Event(LiquidityDeposit)` carrying the LP leg with no review flag (replaces the Unknown fallback for the 26x/4x/3x/1x lp=true families).
- [x] `TestBerachainProcessor#test_pure_outflow_lp_send_not_in_snapshot_stays_unknown`; given the same shape with a token NOT in the LP snapshot, expects `Event(Unknown) + review` unchanged (address-keyed gate, no name matching).
- [x] `TestBerachainProcessor#test_bidirectional_position_token_receive_is_liquidity_deposit_characterization`; characterization pin (runs GREEN before AND after the withdraw rule lands): given in-legs receiving an island/vault receipt token (LP-snapshot member) and out-legs sending the LP/underlying, expects `Event(LiquidityDeposit)` via existing shape 6; guards that the new withdraw rule does not consume the receive direction.
- [x] `TestBerachainProcessor#test_bidirectional_position_token_send_is_withdraw_precedes_amm_deposit`; given in-legs receiving LP/underlying assets and out-legs sending the island/vault receipt token, expects `Event(LiquidityWithdraw)`; RED on HEAD today (shape 6 currently reads this shape as an AMM deposit), proving the withdraw slot must precede shape 6.
- [x] `TestBerachainProcessor#test_self_wallet_outbound_precedes_pure_outflow_rule`; given a pure outflow of an LP-snapshot member whose single recipient is a registered self-wallet, expects `Event(Transfer)` (shape 8 keeps precedence over the new pure-outflow deposit rule).
- [x] `TestBerachainProcessor#test_multi_leg_lp_outflow_still_vault_deposit`; given economic legs = an LP-token out PLUS a second economic out-leg (e.g. BERA economic out alongside the LP; the zap-add shape), expects the routing-table-decided `EventType` for the multi-asset deposit family (pin the exact expectation from Task 1's evidence, not a default).
- [x] `TestBerachainProcessor#test_pure_outflow_lst_send_classifies_per_routing_table` (conditional, LST->B); given economic legs = a single LST out-leg gated on the new position-token registry, expects the routing-table-decided `EventType`. If all LST clusters routed to (A), replace this item with a one-line SKIPPED note citing the routing table.
- [x] `TestBerachainProcessor#test_three_asset_zap_send_classifies_per_routing_table`; given the `BUSD + WETH + BERA` out shape (plus receives if Task 2 recovered them), expects the routing-table-decided `EventType`.
- [x] Conditional wiring (only when the registry is created): inject the registry into `BerachainProcessor` via a constructor parameter wired at `_build_processor` in `on_chain_th_substitution.py` (mirroring the LP snapshot injection); grep-verify the constructor's caller identity before landing so the unit tests cannot stay green while the real pipeline runs registry-less (development_lessons.md #48 pattern).
- [x] `TestBerachainProcessor#test_unknown_fallback_still_terminal`; given a pure outflow of a non-LP, non-position token not covered by any new rule, expects `Event(Unknown) + review` with the existing warning (fallback unchanged).
- [x] Run → expect RED: `BERA_CHAIN_API_KEY= uv run pytest tests/unit/infrastructure/test_berachain_processor.py -q`
- [x] Implement the rules as leg-shape predicates slotted per the order above; update the `_classify_events` docstring shape list in the same change; extract a helper module if the processor would exceed 1,000 lines.
- [x] Run → expect GREEN; commit: `feat(on-chain): classify vault re-staking, zaps, and position tokens`

### Task 4: Comparator compatibility (derive-first) + docs

r1 F1 verified on HEAD: `Cost` rows are exempt from the type comparison (gas surface) and `LiquidityDeposit` already accepts `transfer/To pool`, so the expected amendment is a NO-OP for the known clusters. This task is derive-first: amend only what a REAL surviving type mismatch proves.

Files:
- `src/tax_reporting/application/on_chain_validation/comparator.py` *(EVENT_COMPATIBILITY only)*
- `tests/unit/application/test_on_chain_validation_comparator.py`
- `docs/maintenance/project-decisions.md`, `docs/maintenance/on_chain_validation.md`, `docs/maintenance/glossary.md`

- [x] Derive-first gate: re-run the harness after Task 3 and list every remaining TYPE mismatch (record.type_mismatch not None) on the affected clusters. If none survives reclassification, record that evidence line in the task log and mark the amendment items below SKIPPED-by-evidence (no table edit, no PD-010 amendment).
- [x] Conditional (only an observed mismatch): `TestOnChainThComparator#test_<event>_accepts_<combo>_rendering`; given the observed on-chain `EventType` and the observed Koinly `Type/Tag` combo, expects a type match (amounts still strict); write one test per observed combo, no speculative entries. **SKIPPED-by-evidence (review r1 F14)**: the post-Task-3 harness re-run left zero surviving `type_mismatch` rows on the affected clusters, so no combo was ever observed.
- [x] Conditional: negative boundary - the same shape with amounts differing beyond tolerance still mismatches by amount. **SKIPPED-by-evidence (review r1 F14)**: same zero-mismatch evidence; no table entry to boundary-test.
- [x] Conditional: implement the table entries; write the PD-010 amendment (#4) with the observed-mismatch evidence; sweep `on_chain_validation.md` comparator rules and `glossary.md` Semantic equivalence. **SKIPPED-by-evidence (review r1 F14)**: same zero-mismatch evidence; no EVENT_COMPATIBILITY edit and no PD-010 amendment #4 was written (derive-first gate recorded in the Task 4 log).
- [x] Unconditional docs: add the new Terms to `docs/maintenance/glossary.md` (zap, island, LST/position token, receipt leg, internal transaction; English as the defining language, generic vs PT-specific separated) - r1 F9.
- [x] Run → expect GREEN (or skip-path recorded); commit: `docs(on-chain): unknown-family classification docs and (if derived) PD-010 amendment #4`

### Task 5: Harness re-run, dispositions, residual routing

Files:
- `resources/result/2025/on_chain_th_dispositions.toml` *(gitignored, user-owned)*
- `docs/history/plans/2026-08-22-bera-unknown-classifier-rules.md` *(scope notes only)*

- [x] Run the full Validation Commands block; record matched/divergent/cluster counts in the task log.
- [x] Dispositions handling is append-only safe (r1 F3): do NOT edit any existing block's fields or add a status field; when a dispositioned cluster stops occurring, the gate stops counting it automatically. Optionally annotate at most the trailing comment of affected blocks (comment-only, as done for the 2026-08-22 fetch-fix block); if even that risks confusion, record the outcome in the task log instead.
- [x] Verify any NEW occurring signatures: disposition agent-decided with evidence, or surface to the user if a genuinely new shape appears; never force-close.
- [x] Verify residual divergences cluster under the already-dispositioned rendering-family blocks and record their counts as input to the multi-row rendering plan; no adapter changes in this plan.
- [x] Confirm the gate: zero of the 8 `SIGS` still occurring, zero undispositioned Unknown clusters (the Validation Commands loop).

### Task 6: Final validation

- [x] Run the complete Validation Commands block end-to-end from the repo root; expect all tiers green and `Unknown-family gate: PASS`.
- [x] Commit: `docs(on-chain): unknown-family plan outcome notes`
