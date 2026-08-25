# Plan: Multi-leg TH projection rendering + nfttx fetch for ERC-721 position legs

Source: disposition actions in the gitignored `resources/result/2025/on_chain_th_dispositions.toml`
(multi-leg rendering gap family, 17 `missing_rule` signatures holding exit 3) + roadmap context in
`docs/history/backlog/2026-08-18-koinly-cancellation-program.md` (P1 flip gate needs zero-exit).
Branch: `2026-08-24-multi-leg-th-projection` (user decision 2026-08-24; new branch off master `951e10d`).
Requirements buffer: `docs/tmp/plan-requirements-multi-leg-projection.md` (user-confirmed same day).

## Terms

- **Leg pair**: one (out leg, in leg) tuple. The new adapter contract emits one projected TH row per
  leg pair per Event: out legs and in legs are zipped by position (`out[0]/in[0]`, `out[1]/in[1]`,
  ...); unpaired remainder legs emit one-sided rows (sending side only, or receiving side only).
  Single-pair Events (1 out + 1 in, or one-sided single) emit exactly ONE row, byte-identical to
  the current projection.
- **Carrier row (B5)**: the single row per tx whose representative leg is the native asset
  (`token_address is None`), else the first emitted row; it carries the tx gas as the
  `Fee Amount` payload. GasBurn rows NEVER carry the fee payload (gas is counted exactly once,
  once as the GasBurn row's `Sent Amount`).
- **nfttx**: the Etherscan account action returning ERC-721/1155 transfer events for an address,
  invisible to the currently fetched `txlist` (native) + `tokentx` (ERC-20) + `txlistinternal`
  (internal native) triple (`src/tax_reporting/application/on_chain_fetcher.py:9`,
  `src/tax_reporting/infrastructure/on_chain/etherscan_client.py:164-172`).
- **Position NFT**: an ERC-721 token representing an LP position (Koinly symbol format
  `SYMBOL#tokenID`, e.g. `ALGB-POS#26874`; quantity 1 per token ID). Position-token registry
  membership is resolved via `PositionTokenRegistry.is_position_token` /
  `is_position_vault` (`kind="position_nft"`). Membership and vault-target checks key on
  `token_address`; the `SYMBOL#tokenID` asset name is display/comparator-only and never feeds a
  classification decision.
- **event_id (per-row suffixing)**: the processor's per-Event identity
  `f"{tx_hash}#{n}"` (`src/tax_reporting/application/on_chain_th_adapter.py:151-175`). Under the
  new contract a single-pair row carries it VERBATIM; when one Event projects to multiple rows the
  adapter appends a leg-pair discriminator `.{k}` (k >= 2): row 1 `f"{tx_hash}#{n}"`, row 2
  `f"{tx_hash}#{n}.2"`, row 3 `f"{tx_hash}#{n}.3"`. NO two projected rows ever share
  `(tx_hash, event_id)`. This preserves the domain contract
  (`src/tax_reporting/domain/transaction.py:177-260`, Invariant 5 with event_id refinement):
  `TxCorrelationKey` equality for non-None `tx_id` requires matching `event_id`, so distinct
  per-row event ids keep every leg-pair row in its own dict/set bucket and
  `crypto_fifo/parsing.py:_dedup_by_tx_key` (keep-first-per-key, aggregate at INFO) removes only
  genuine duplicates. No consumer parses the `event_id` format (verified 2026-08-24: no
  `split("#")` on event_id anywhere in `src/` or `tests/`).
- **Skill-gate marker**: the plans-class marker at
  `~/.ai-playbook/runtime/skill-invoked/plans.<project>.<session>.marker`, refreshed BEFORE every
  plan-file write per `ai-playbook/agents/hooks/skill-gate/README.md` (Marker WRITE RECIPE):
  `SID="$(python3 ~/.ai-playbook/scripts/session_channel.py)"` then
  `python3 ~/.ai-playbook/scripts/skill_gate.py --write-marker --session-id "$SID"` (empty SID ->
  omit the flag; the core keys the literal `no-session`). Fail loud if unwritable.
- **Session key**: `sha1(value)[:16]` hex of the session-channel value
  (`CLAUDE_CODE_SESSION_ID` or `CURSOR_SESSION_ID` or `CURSOR_CONVERSATION_ID`; empty after strip
  -> literal `no-session`). Derived ONLY via the shared `session_channel.py` subprocess.

## Gist & Examples

**What changes.** Two completeness fixes in the on-chain TH pipeline, both required for the 2025
validation zero-exit (the P1 flip gate):

1. The adapter (`on_chain_th_adapter.py`) currently renders ONE `TransactionHistoryRow` per Event
   using only the FIRST leg per direction (`_first_leg_by_direction`, lines 217-218). Second and
   later legs never reach the projected TH, so every multi-leg tx diverges from Koinly's
   multi-row rendering. Worked example from the real baseline (disposition Task-5 record;
   tx hash withheld, see the gitignored dispositions file): the tx has TWO iBERA out-legs, 8.467888513983386625 and
   1.494333267173538816; the projection emitted only the first (8.4678...) while Koinly carries
   both (sum 9.96222178), producing the amount mismatch that held one exit-3 signature. Same
   family, bigger: every LP deposit/withdraw is inherently multi-leg (out WBERA + out WBTC, in
   KODI-LP), which is why 16 LP-shaped signatures show "on-chain 0 vs Koinly N" on every
   non-first leg. After this plan: out[0]+in[0] pair into row 1, out[1] goes one-sided into row 2
   (or pairs with in[1] when it exists), and the comparator's per-(asset, direction) SUM
   comparison sees identical totals on both sides.

2. The fetcher never pulls `nfttx`, so ERC-721 legs are invisible on-chain. Worked example
   (disposition r1-fix block; tx hash withheld, see the gitignored dispositions file): Koinly
   shows an `ALGB-POS#26874` receive
   (quantity 1) plus a 44.97 BUSD out; the on-chain side has the BUSD leg only, because the
   position-NFT mint transfer exists only in `nfttx`. After this plan the fetcher pulls `nfttx`
   and the decoder emits `asset="ALGB-POS#26874"`, `amount_raw=1`, `amount_decimals=0` - but ONLY
   for contracts in the position-token registry. Non-member nfttx transfers (spam airdrop mints
   such as BERA777) are skipped with a WARNING and a count, so they stay on-chain-invisible and
   the existing `events=none|koinly=crypto_deposit/` acceptable-difference cluster keeps
   describing them correctly.

Row identity, worked example (the iBERA tx above): its Event (event_id `0xbc0d...#5` for
illustration) projects to two rows - row 1 pairs iBERA-out[0] with the BERA-in leg and keeps
event_id `0xbc0d...#5` verbatim; row 2 carries iBERA-out[1] one-sided with event_id
`0xbc0d...#5.2`. The FIFO dedup layer sees two distinct `(tx_hash, event_id)` keys and keeps both
legs; without the suffix the second leg would be silently dropped as a "duplicate" (keep-first
per key), losing 1.4943 iBERA of disposal proceeds.

**Why now.** All 27 discrepancy clusters on the 2025 baseline are dispositioned; exit 3 is held
ONLY by the 17 `missing_rule` signatures of this one family (16 LP-shaped + the iBERA two-leg
Swap record, two of which also need the nfttx fetch). Landing both fixes is the entire remaining
distance to the zero-exit flip gate.

**What does NOT change.** The comparator, the exit-code contract (0/1/2/3), the non-opted-in
production path (flag stays off; Koinly-byte-identical characterization stays green), the CSV
schema (`bera_transactions.csv` gains rows, not columns), the processor's shape rules except where
newly-visible ERC-721 legs legitimately change which shape fires.

## Evaluation Criteria

**Quality dimensions:**
- Correctness: per-(asset, direction) totals of the projected rows equal the raw legs' totals for
  every Event (hermetic multi-leg fixtures: 2-out/1-in, 1-out/2-in, 2-out/2-in, single-pair).
- Regression: single-pair Events project byte-identically to the current implementation (pinned by
  the existing single-pair characterization tests, retargeted in Task 1).
- Gas integrity (B5): exactly one row per tx carries the fee payload; GasBurn rows never do.
- Consumer safety: EVERY emitted row satisfies the three consumer contracts (correlation-key
  resolver, token-origin indexing, fee filter) - not just the first row per Event - and no two
  projected rows share `(tx_hash, event_id)` (distinct `TxCorrelationKey` buckets).
- Decoding correctness: nfttx rows decode to `SYMBOL#tokenID` with quantity 1 and correct
  direction; malformed nfttx rows skip with a WARNING (row-level isolation).
- Test hygiene: hermetic synthetic fixtures only; suite green under the per-test timeout.

**Done when:**
- All RED->GREEN test tasks below pass; `uv run pytest` full suite green (baseline 2315 passed).
- Doc sweep clean: `docs/maintenance/on_chain_validation.md` documents the nfttx endpoint and the
  per-leg-pair adapter contract; no stale "one row per Event" / "first leg per direction" prose
  remains in the swept docs.

**Ship when:**
- The user runs `uv run tax-reporting --validate-on-chain-th 2025` on the real baseline and gets
  exit 0 (all 17 `missing_rule` signatures stop occurring; the fix-landed assertions pass), then
  flips `ON_CHAIN_TH_WALLETS` for the BERA wallet in `config.ini`. Re-fetching the 2025
  `bera_transactions.csv` (so nfttx rows land in the CSV) is part of this user-run validation;
  the harness and its artifacts stay gitignored.

## Review Scope

**Explicit must-fix**; findings on these paths are always in scope (review and fix if valid):

**Production code:**
- `src/tax_reporting/application/on_chain_th_adapter.py`
- `src/tax_reporting/application/on_chain_fetcher.py`
- `src/tax_reporting/infrastructure/on_chain/etherscan_client.py`
- `src/tax_reporting/infrastructure/on_chain/bera_decoder.py`
- `src/tax_reporting/infrastructure/on_chain/berachain_processor.py` *(method-scoped: only the
  classification paths whose leg tuples now include ERC-721 legs; all other shapes frozen -
  reject findings touching them)*
- `src/tax_reporting/application/on_chain_th_substitution.py` *(docstring/collaboration-surface
  only: the `projected_rows` field contract at lines 174-183 and any multi-row merge safety;
  the merge/serialization logic is frozen unless a Task 2 RED test forces a fix; registry-path
  helper extraction for Task 3 is allowed)*

**Tests:**
- `tests/unit/application/test_on_chain_th_adapter.py`
- `tests/unit/application/test_on_chain_th_substitution.py`
- `tests/unit/application/test_on_chain_fetcher.py`
- `tests/unit/infrastructure/test_bera_decoder.py`
- `tests/unit/infrastructure/test_etherscan_client.py`
- `tests/unit/infrastructure/test_berachain_processor.py` *(new ERC-721-leg cases only; the
  existing shape matrix is frozen)*
- `tests/unit/crypto_fifo/test_parsing_tx_key.py` *(Task 2 consumer-contract pin only)*
- `docs/maintenance/on_chain_validation.md`
- `docs/architecture/on-chain-tx-design.md` *(the two "one row per Event" design-record
  statements at ~lines 362 and 415 + the projected-row contract section)*

**Plan-related extension**; implementation and review may change files not listed above. Treat a
finding as in scope when it is **causally related to this plan**: it implements or completes a
plan task, fixes a regression introduced by plan work, closes wiring or docs implied by an
explicit must-fix change, or contradicts a contract the plan changed (e.g. a consumer of
`ProjectedThRow` that assumes one row per Event). If the link to the plan is weak or speculative,
drop as out of scope with a one-line reason.

**Out of scope; reject unless plan-related:**
- `src/tax_reporting/application/on_chain_validation/comparator.py`; per-(asset, direction) sum
  semantics and the PD-010 compatibility table are unchanged by this plan.
- `src/tax_reporting/application/crypto_fifo/parsing.py`; the dedup consumer is PINNED by a Task 2
  test, not modified - if the pin fails, the adapter's per-row event-id design is wrong, not the
  dedup.
- `resources/result/**` and `resources/source/<year>/**` real registries; gitignored user-owned
  surfaces (the harness re-run is a Ship-when condition, not a plan task).

## Design Invariants (CR Guard)

1. **Single-pair byte-identity**: an Event with exactly one out and one in leg (or a one-sided
   single leg) must project to the same `TransactionHistoryRow` field values as the current
   implementation (same amounts, currencies, `tx_src`/`tx_dest`, `row_index` ordering start,
   `event_id`). Prior-phase decision: the adapter's Koinly-compat contract, pinned by
   `test_one_row_per_event` (retargeted, not deleted, in Task 1).
2. **Gas counted exactly once (B5)**: exactly one row per tx carries the fee payload; GasBurn
   rows never do; the GasBurn row's `Sent Amount` remains the gas itself. P1 disposition C9
   (carrier-row enrichment) depends on this.
3. **Comparator untouched**: per-(asset, direction) sum comparison and the PD-010 compatibility
   table are NOT modified by this plan; multi-row correctness is achieved purely by preserving
   leg totals in the projection.
4. **Non-opted-in path invariants**: the Koinly-byte-identical characterization for the
   flag-off production path stays green throughout (the flag flips only in the Ship-when step,
   by the user).
5. **`event_id` per-row uniqueness**: the adapter carries the processor's `event_id` verbatim on
   the single-pair row and never defaults it to `None`; multi-row Events get the `.{k}` leg-pair
   suffix (k >= 2) so no two projected rows share `(tx_hash, event_id)`. This is what keeps
   `TxCorrelationKey` (domain Invariant 5: non-None `tx_id` equality requires matching
   `event_id`) and `crypto_fifo/parsing.py:_dedup_by_tx_key` (keep-first-per-key) from silently
   collapsing same-Event leg-pair rows. Prior-phase decision: review F7 hash/eq consistency in
   `src/tax_reporting/domain/transaction.py:177-260`.
6. **Hermeticity**: tests read committed synthetic fixtures only; no real wallet addresses, tx
   hashes, or gitignored registries in tests; no network in pytest.
7. **C8 boundary via membership gating**: no spam-NFT content filtering is added; instead the
   nfttx decode is position-registry-gated - only `PositionTokenRegistry` member contracts decode
   to rows, and non-member transfers (spam airdrop mints such as BERA777) are skipped with a
   WARNING and a match-count summary (AGENTS.md: add match-count warnings for non-unique
   deduplication keys). Spam NFTs therefore stay on-chain-invisible exactly as the C8
   `acceptable_difference` disposition (`events=none|koinly=crypto_deposit/`) describes, and no
   new on-chain-only spam cluster can appear to break the exit-0 Ship gate. If a future
   economically-meaningful ERC-721 is missing, the append-only dispositions file surfaces it as a
   NEW cluster and the registry gains a member - the gate catches the gap by construction.

## Validation Commands

```bash
uv run pytest tests/unit/application/test_on_chain_th_adapter.py tests/unit/application/test_on_chain_th_substitution.py tests/unit/application/test_on_chain_fetcher.py tests/unit/infrastructure/test_bera_decoder.py tests/unit/infrastructure/test_etherscan_client.py tests/unit/infrastructure/test_berachain_processor.py tests/unit/crypto_fifo/test_parsing_tx_key.py
uv run pytest
# Endpoint doc present (fail-closed positive grep, per-file):
if ! grep -q "nfttx" docs/maintenance/on_chain_validation.md; then echo "MISSING nfttx endpoint doc"; exit 1; fi
# Adapter contract prose present (per-file positive greps):
if ! grep -q "leg pair" docs/maintenance/on_chain_validation.md; then echo "MISSING leg-pair contract doc"; exit 1; fi
if ! grep -q "leg pair" docs/architecture/on-chain-tx-design.md; then echo "MISSING design-record leg-pair update"; exit 1; fi
# Stale single-row phrasing swept out of the contract surfaces (negated grep; zero matches = pass):
if grep -n "one row per Event\|first leg per direction" docs/maintenance/on_chain_validation.md README.md docs/maintenance/crypto_implementation_guidelines.md docs/architecture/on-chain-tx-design.md; then echo "STALE single-row phrasing"; exit 1; fi
# Adapter docstring updated (fail-closed positive grep on the production module):
if ! grep -q "leg pair" src/tax_reporting/application/on_chain_th_adapter.py; then echo "MISSING adapter docstring update"; exit 1; fi
```

*(The stale-phrasing grep intentionally does NOT sweep this plan file: its mentions are the
checker literal, not stale references.)*

### Task 1: Adapter multi-leg rendering (RED -> GREEN)

Files:
- `src/tax_reporting/application/on_chain_th_adapter.py`
- `tests/unit/application/test_on_chain_th_adapter.py`
- `src/tax_reporting/application/on_chain_th_substitution.py` *(docstring line ~176 only)*

- [x] `TestOnChainThAdapter#test_multi_out_single_in_emits_paired_then_one_sided_row`; given a Swap event (event_id `h#4`) with legs [out WBERA 5, out WBTC 0.005, in KODI-LP 36.65], expects 2 rows: row A (send WBERA 5, receive KODI-LP 36.65, event_id `h#4` verbatim) and row B (send WBTC 0.005, receiving side None, event_id `h#4.2`), distinct sequential `row_index` values, per-(asset, direction) totals equal to the raw legs
- [x] `TestOnChainThAdapter#test_single_out_multi_in_emits_paired_then_receive_only_row`; given legs [out BERA 1, in HONEY 10, in iBGT 3], expects row A (BERA 1 -> HONEY 10) and row B (receiving iBGT 3, sending side None)
- [x] `TestOnChainThAdapter#test_two_out_two_in_emits_two_paired_rows`; given [out A, out B, in C, in D], expects exactly rows (A->C) and (B->D), no one-sided remainder
- [x] `TestOnChainThAdapter#test_single_pair_event_row_unchanged`; given a single-out single-in Swap event (the existing `test_one_row_per_event` fixture), expects ONE row whose field values equal the current projection (retarget the existing test; assert field-by-field, not object identity)
- [x] `TestOnChainThAdapter#test_carrier_row_prefers_native_leg_among_multiple_rows`; given a tx whose event emits 3 rows where only row 2's representative leg is the native asset, expects the fee payload attached to row 2 only (rows 1 and 3 fee=None)
- [x] `TestOnChainThAdapter#test_gasburn_event_still_single_row_no_fee`; given a GasBurn event with gas and a zero-value native out leg, expects ONE row with Sent Amount = gas, no fee payload (B5 unchanged)
- [x] `TestOnChainThAdapter#test_multi_row_event_rows_carry_distinct_event_ids`; given an Event with event_id `h#4` that projects to 3 rows, expects row event_ids `h#4`, `h#4.2`, `h#4.3` (first row verbatim, `.{k}` suffix k >= 2 for the rest; no two rows share `(tx_hash, event_id)`)
- [x] `TestOnChainThAdapter#test_row_index_sequential_across_multi_row_events`; given tx A (event with 2 leg pairs) then tx B (single-pair event), expects `row_index` 0,1 for tx A's rows and 2 for tx B's row
- [x] Run -> expect RED: `uv run pytest tests/unit/application/test_on_chain_th_adapter.py`
- [x] Implement: zip out/in legs per Event in `_project_event` (rename or split into a per-pair row builder; keep the GasBurn special case single-row), derive the `.{k}` per-row event-id suffix for rows after the first, update `project_on_chain_transactions` row-index allocation and `_carrier_row_index` to operate over the expanded per-tx row list; update the module docstring and the `OnChainProjection.projected_rows` docstring (`on_chain_th_substitution.py:174-183`) to the per-leg-pair contract
- [x] Run -> expect GREEN
- [x] Commit: `feat(on-chain): project one TH row per Event leg pair`

### Task 2: Multi-row merge + consumer-contract safety (RED -> GREEN)

Files:
- `src/tax_reporting/application/on_chain_th_substitution.py` *(only if the RED test forces it)*
- `tests/unit/application/test_on_chain_th_substitution.py`
- `tests/unit/application/test_on_chain_th_adapter.py`
- `tests/unit/crypto_fifo/test_parsing_tx_key.py`

- [x] `TestOnChainThSubstituter#test_multi_row_event_rows_all_survive_merge`; given a synthetic Koinly TH and an on-chain projection where one tx emits 2 rows with event_ids `h#5` and `h#5.2`, expects both projected rows present in the merged TH output (no dedup drop), with distinct `TxCorrelationKey`s (distinct `(tx_hash, event_id)` pairs)
- [x] `TestParsingTxKey#test_dedup_keeps_same_event_leg_pair_rows`; given two TH consumption rows sharing tx_hash and asset (the iBERA worked example: two iBERA out legs) with event_ids `h#5` and `h#5.2`, expects BOTH rows retained after `_dedup_by_tx_key`; and given a genuine duplicate (same tx_hash AND same event_id twice), expects the second dropped with a review entry (pin the existing behavior)
- [x] `TestOnChainThAdapter#test_every_row_satisfies_all_three_consumers`; given a multi-leg Swap event (2 out, 1 in) projected to 2 rows, expects EACH row satisfies (a) correlation-key contract (non-None `tx_hash`, populated `event_id`), (b) token-origin indexing contract (non-empty `TxHash`; non-empty `TxSrc`/`TxDest` where the row's legs populate them), (c) fee-filter contract (Type, Fee Amount, Fee Currency, Sent Amount present-or-explicitly-empty) - extend the existing `test_single_row_satisfies_all_three_consumers` fixture set
- [x] Run -> expect RED: `uv run pytest tests/unit/application/test_on_chain_th_substitution.py tests/unit/application/test_on_chain_th_adapter.py`
- [x] Fix whatever drops or malforms duplicate-`event_id` rows in the merge path (audit `_merge_on_chain_into_koinly_th` structures keyed by row identity); if both tests pass immediately because the merge is already multi-row safe, record that evidence in the task log and keep the tests as regression pins
- [x] Run -> expect GREEN
- [x] Commit: `test(on-chain): pin multi-row event merge and consumer contracts`

### Task 3: nfttx fetch + ERC-721 decode (RED -> GREEN)

Files:
- `src/tax_reporting/infrastructure/on_chain/etherscan_client.py`
- `src/tax_reporting/application/on_chain_fetcher.py`
- `src/tax_reporting/infrastructure/on_chain/bera_decoder.py`
- `tests/unit/infrastructure/test_etherscan_client.py`
- `tests/unit/application/test_on_chain_fetcher.py`
- `tests/unit/infrastructure/test_bera_decoder.py`

- [x] `TestEtherscanClient#test_fetch_nft_transfers_uses_nfttx_action`; given a stubbed transport returning one page of `nfttx` rows for an address, expects the request carries `action=nfttx` and the parsed rows are returned (reusing the existing action machinery incl. boundary-block drain and max-rows ceiling)
- [x] `TestBeraDecoder#test_decode_nft_row_names_asset_with_token_id`; given an nfttx row (tokenSymbol `ALGB-POS`, tokenID `26874`, contractAddress set to a synthetic position-registry member, `to` = wallet - a mint receive), expects an `OnChainTxRow` with `asset="ALGB-POS#26874"`, `amount_raw=1`, `amount_decimals=0`, `direction="in"`, `token_address` = contractAddress, no fee fields
- [x] `TestBeraDecoder#test_decode_nft_row_out_direction_and_window`; given an nfttx row whose `from` = wallet (a send), expects `direction="out"`; given a row outside the wallet's date window, expects it skipped. Direction MUST be derived by reusing the shared `_direction` helper (`from`=wallet -> out, `to`=wallet -> in), never reimplemented inline
- [x] `TestBeraDecoder#test_decode_nft_row_non_member_contract_skips_with_warning`; given an nfttx row whose contractAddress is NOT in the position-token registry (spam airdrop, tokenSymbol `BERA777`), expects the row skipped with a WARNING and no `OnChainTxRow` emitted (membership gating; count surfaced by the fetcher summary)
- [x] `TestBeraDecoder#test_decode_malformed_nft_row_warns_and_skips`; given an nfttx row missing `tokenID`, expects a WARNING log and the row skipped (dataset continues)
- [x] `TestBeraDecoder#test_nft_row_overlapping_tokentx_transfer_decoded_once`; given the same transfer present in BOTH `raw_tokentx_rows` and `raw_nft_rows` (ERC-1155-style overlap: same `tx_hash`, `contractAddress`, direction; tokentx renders the plain symbol, nfttx renders `SYMBOL#tokenID`), expects ONE `OnChainTxRow` emitted - the nfttx-decoded one - and a WARNING carrying the dropped-overlap count (the nft surface is authoritative for registry-member contracts)
- [x] `TestOnChainFetcher#test_fetch_writes_nft_rows_to_csv`; given a stubbed client returning txlist + tokentx + nfttx rows for a registry-member contract, expects the written `bera_transactions.csv` contains the `ALGB-POS#26874` row with the existing 15-column schema unchanged
- [x] `TestOnChainFetcher#test_fetch_skips_non_registry_nft_contracts`; given a stubbed client whose nfttx page mixes one registry-member and one non-member transfer, expects only the member row written and a WARNING carrying the skipped count
- [x] Run -> expect RED: `uv run pytest tests/unit/infrastructure/test_etherscan_client.py tests/unit/application/test_on_chain_fetcher.py tests/unit/infrastructure/test_bera_decoder.py`
- [x] Implement: `fetch_nft_transfers` on the client; `raw_nft_rows` + position-registry parameters on `decode_rows` + `_decode_nft` (quantity 1, `SYMBOL#tokenID` asset, registry-membership gate before decode, row-level try/except per the decode conventions); an overlap guard dropping already-nft-decoded token transfers keyed `(tx_hash, token_address, direction)` with a match-count WARNING (Etherscan `nfttx`/`tokentx` can both carry a transfer for registry-member contracts; the key intentionally omits tokenID - `OnChainTxRow` has no token-id column, the asset name embeds it for NFTs, and any same-contract same-direction overlap row is dropped in favor of the authoritative nfttx row); wire the fetch into `run_on_chain_fetch`/`_decode_wallet` in provenance order (nfttx rows decoded after tokentx rows per block, mirroring the existing decode-order note); the fetcher loads the per-year position-token registry via the same resolution the substituter uses (extract `_resolve_registry_path` to a shared helper if it is still a private method); update the fetch-triple module docstring (`on_chain_fetcher.py:9`), the `decode_rows` docstring, and the now-false `etherscan_client.py:178-179` "ERC-721 NFT mint receipts are NOT recovered" sentence
- [x] Run -> expect GREEN
- [x] Commit: `feat(on-chain): fetch nfttx and decode registry-member ERC-721 position legs`

### Task 4: Classifier behavior with visible ERC-721 legs (RED -> GREEN)

Files:
- `src/tax_reporting/infrastructure/on_chain/berachain_processor.py` *(only the classification paths that consume position-NFT legs)*
- `tests/unit/infrastructure/test_berachain_processor.py` *(new cases only)*

- [x] `TestBerachainProcessor#test_deposit_with_position_nft_in_leg_classifies_liquidity_deposit`; given a tx with out WBERA to a pool/vault and in `ALGB-POS#26874` (position-token registry member by `token_address`), expects Event `LiquidityDeposit` (the now-visible bidirectional shape must not regress to Unknown/Swap vs today's registry-member-recipient inference)
- [x] `TestBerachainProcessor#test_withdraw_of_position_nft_to_vault_target_classifies_liquidity_withdraw`; given out `ALGB-POS#26874` (registry member by `token_address`) to a registry vault (`kind="position_nft"`) and in WBERA, expects `LiquidityWithdraw` (shape-6 vault-target rule)
- [x] `TestBerachainProcessor#test_position_nft_swapped_outside_vault_stays_swap`; given out `ALGB-POS#26874` to a non-vault DEX pair and in WBERA, expects `Swap` (LBGT-family invariant, user-confirmed 2026-08-23)
- [x] Run -> expect RED: `uv run pytest tests/unit/infrastructure/test_berachain_processor.py -k "position_nft"`
- [x] Implement the minimal classifier adjustment so the visible ERC-721 legs route through the intended shapes: extract the position-leg detection into a NAMED helper/detector function with direct unit tests (do not grow `_classify_events`, already over the module branch budget; do not reorder or rewrite existing shape rules). Membership and vault-target checks key on `token_address` only - the `SYMBOL#tokenID` asset name is display/comparator-only and never feeds a classification decision
- [x] Run -> expect GREEN; then run the full processor module to confirm the frozen shape matrix is green: `uv run pytest tests/unit/infrastructure/test_berachain_processor.py`
- [x] Commit: `feat(on-chain): classify ERC-721 position legs in deposit/withdraw shapes`

### Task 5: Documentation updates (non-behavioral)

Files:
- `docs/maintenance/on_chain_validation.md`
- `docs/architecture/on-chain-tx-design.md`

- [x] Add `nfttx` to the documented fetch endpoint set (currently `txlist` + `tokentx` + `txlistinternal`)
- [x] Replace the single-row adapter contract prose (any "one row per Event" / "first leg per direction" phrasing) with the per-leg-pair contract, the `.{k}` per-row event-id suffix, the multi-row-per-`tx_hash` note, and the registry-membership gate on nfttx decode
- [x] Amend the two RESOLVED statements in `docs/architecture/on-chain-tx-design.md` (~lines 362 and 415) IN PLACE: replace the "The adapter emits one row per Event" clause with the per-leg-pair contract plus a dated amendment note (`amended 2026-08-24: one row per (Event, leg pair); row-level distinct event_id via the .{k} suffix`), keeping the historical resolution context around it
- [x] Note that the multi-leg rendering family covers the 17 `missing_rule` disposition signatures holding exit 3 (cross-reference the umbrella backlog P1 status)
- [x] Sweep check -> expect pass: the Validation Commands stale-phrasing grep above

- [x] Commit: `docs(on-chain): nfttx endpoint + per-leg-pair projection contract`

### Task 6: Full-suite validation

- [x] Run -> expect green: `uv run pytest` (baseline 2315 passed before this plan; the plan only adds tests)
- [x] Run the full Validation Commands block above -> expect all pass
- [x] Commit (if any fixups were needed): `test(on-chain): multi-leg projection full-suite fixups`
