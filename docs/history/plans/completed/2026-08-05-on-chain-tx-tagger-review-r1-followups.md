# Plan: On-chain tx tagger review r1 follow-ups (round-2 hardening + F4/F9 wire rpc + F11-F13 tests + F20-F23 docs)

Resolves the deferred round-1 review findings plus the round-2 optional-hardening
findings, on branch `2026-08-02-on-chain-tx-tagger` vs `master`. The prior plan
(`docs/history/plans/completed/2026-08-04-on-chain-tx-tagger-review-r1-fixes.md`)
resolved F1, F2, F3, F5, F6, F7, F8, F10.

Python testing guidance: `docs/maintenance/python_guidelines.md` (pytest fixture
scoping, mock-target rules, `pytest.raises(match=)` PT011). Domain rules:
`docs/maintenance/crypto_implementation_guidelines.md`, `docs/maintenance/koinly_guidelines.md`.

## Terms

- RPC layer: the bytecode + implementation() fallback in `lp_autodiscovery.py`
  (layer 2 of the three-layer LP-token autodiscovery stack; design record §9.2
  decision #11). Classifies tokens NOT in the committed subgraph snapshot by
  fetching runtime bytecode via `eth_getCode` and fingerprinting it.
- snapshot: the committed `berachain_lp_snapshot.json` allowlist (layer 1; the
  only classifier that runs in production today).
- MO1 cap: the hard cap (default 50) on RPC-touching lookups per run.
- bridge file: `on_chain_th_bridge.csv`, the standalone on-chain CSV written
  into `koinly_dir` during substitution and unlinked after the merge.

## Gist & Examples

Four independent buckets, ordered smallest-to-largest:

1. **Round-2 hardening (3 findings, same spot)**: the F1 fix's try/finally in
   `OnChainThSubstituter.maybe_substitute` has two cosmetic robustness gaps found
   by the post-fix review: (a) the bridge write (`serialize_projected_rows_to_th_csv`)
   sits OUTSIDE the try, so a mid-write raise orphans a partial bridge; (b) the
   finally's `unlink()` is unguarded, so on a read-only `koinly_dir` it can mask
   the original F2 `ReportGenerationError` diagnostic. Both are 2-line fixes; the
   test gap (write-failure arm untested) closes with one test.

2. **F20-F23 + F8 doc drift (Low docs)**: SRG-012's "Multiple sources" anchor
   doesn't match the real heading; the byte-identical claim is overstated (Task 4's
   token_origin migration changed the Koinly path); a WARNING interpolates
   `sub_type=None`; and `crypto_implementation_guidelines.md` still names
   `_maybe_substitute_on_chain_th` in `main.py` (moved by F8).

3. **F11-F13 failure-path tests**: `rpc_client.py` (retry/backoff/redaction),
   the contract-registry loader (`build_contract_registry` F1 closed-enum guards),
   and the csv reader (malformed-row skip + direction coercion) all lack
   failure-path tests. F11 becomes load-bearing once bucket 4 wires rpc_client.

4. **F4 + F9 wire rpc_client**: the LP-autodiscovery RPC layer (layer 2) is
   unreachable today (`rpc_client=None`). Wire it from a new config-derived
   `ON_CHAIN_RPC_URL` so new LP pools not in the snapshot are auto-classified
   (the M2 stale-snapshot remedy). Move the MO1 cap into `is_lp_token` so the
   processor's per-leg calls are bounded (F4). Add one e2e test through the
   bytecode path.

Example (bucket 4, config wiring): today `config.ini` has no RPC key; the
substituter builds `LpAutodiscovery(snapshot=..., rpc_client=None)`. After:
```ini
[TAX JURISDICTION]
ON_CHAIN_TH_WALLETS = BERA
ON_CHAIN_RPC_URL = https://berachain-rpc.publicnode.com
```
and `OnChainThSubstituter` builds `RpcClient(rpc_url=jurisdiction.on_chain_rpc_url)`
when the URL is set (None → snapshot-only, byte-identical default).

## Evaluation Criteria

**Quality dimensions:**
- correctness (bucket 4): the MO1 cap bounds the processor's per-leg `is_lp_token`
  calls; a flaky RPC does not hang the run; flag-off (no RPC URL) is byte-identical.
- robustness (bucket 1): the bridge is cleaned up on ANY merge exception
  (including write failures); the finally-unlink never masks the original exception.
- test coverage (buckets 3+4): rpc_client retry/backoff/redaction, the registry
  loader guards, the csv reader failure paths, and the e2e bytecode path are all
  pinned by discriminating tests.
- doc accuracy (bucket 2): all four doc issues fixed; no stale module-path or
  overstated claim remains.

**Done when:**
- All new RED tests pass (GREEN); `uv run pytest -q` full suite green.
- `RUN_AUDIT_GUARD=1 uv run pytest tests/unit/test_on_chain_tests_no_personal_data.py`
  still passes (bucket 4 must not break the guard).
- The flag-off path (no `ON_CHAIN_RPC_URL`) is byte-identical (characterization
  baselines unchanged).
- `! grep -rn '_maybe_substitute_on_chain_th' docs/maintenance docs/architecture README.md`
  returns empty (bucket 2 F8 drift).

**Ship when:** N/A (local-only personal tool).

## Review Scope

**Explicit must-fix**; findings on these paths are always in scope:

**Production code:**
- `src/tax_reporting/application/on_chain_th_substitution.py` *(buckets 1, 4)*
- `src/tax_reporting/infrastructure/on_chain/lp_autodiscovery.py` *(bucket 4)*
- `src/tax_reporting/infrastructure/on_chain/rpc_client.py` *(bucket 4, wiring only; no behavior change)*
- `src/tax_reporting/infrastructure/config.py` *(bucket 4, new config key)*
- `src/tax_reporting/domain/jurisdiction.py` *(bucket 4, new dataclass field)*
- `src/tax_reporting/infrastructure/on_chain/berachain_processor.py` *(bucket 2, sub_type=None interpolation)*

**Tests:**
- `tests/end_to_end/test_on_chain_bera_opted_in.py` *(bucket 1, write-failure test)*
- `tests/unit/infrastructure/test_rpc_client.py` *(new, buckets 3+4)*
- `tests/unit/application/test_on_chain_config_loader.py` *(bucket 3, registry loader tests)*
- `tests/unit/infrastructure/test_on_chain_csv_reader.py` *(bucket 3, failure-path tests)*
- `tests/unit/infrastructure/test_lp_autodiscovery.py` *(bucket 4, cap-in-is_lp_token test)*

**Docs:**
- `README.md`, `docs/architecture/on-chain-tx-design.md`, `docs/maintenance/{tax_reporting_guidelines,crypto_implementation_guidelines,koinly_guidelines}.md` *(bucket 2)*

**Plan-related extension**: implementation and review may change files not listed
above (e.g. `main.py` to thread the RPC URL, `test_main_on_chain_wiring.py` for
the config-to-substituter thread). Treat a finding as in scope when causally
related to this plan.

**Out of scope; reject unless plan-related:**
- `src/tax_reporting/infrastructure/on_chain/integrity_invariants.py`; F17
  (redundant echo check) is a separate simplification decision not bundled here.
- The on-chain modules' happy-path behavior ( characterization baselines must stay
  byte-identical).

## Design Invariants (CR Guard)

- **Koinly-byte-identical default (flag off).** When `ON_CHAIN_TH_WALLETS` is
  empty AND `ON_CHAIN_RPC_URL` is unset, the on-chain path is fully skipped and
  the RPC layer is never constructed. Pinned by `test_on_chain_koinly_characterization.py`.
- **Snapshot-only is still the default when RPC URL is unset.** Even when
  `ON_CHAIN_TH_WALLETS` lists wallets, an unset `ON_CHAIN_RPC_URL` means
  `rpc_client=None` → `is_lp_token` returns Unknown+review for non-snapshot tokens
  (today's behavior). The RPC URL OPTS INTO the bytecode fallback.
- **Fail-loud opted-in contract (M1).** A flaky RPC on the opted-in path fails
  loud (`ReportGenerationError`), never silently falls back. The existing
  try/except boundary in `_main` stays.
- **MO1 cap is per-run, not per-tx.** The cap (default 50) bounds total
  RPC-touching lookups across the whole opted-in run; moving it into `is_lp_token`
  must use an instance counter seeded in `__init__`, not a per-call local.
- **event_id CSV bridge + merged-TH path.** Unchanged by this plan.
- **User's real Koinly TH read-only.** Bucket 1 must not reintroduce any write
  path to `koinly_th`.

## Validation Commands

```bash
# Affected suites (run after each task):
uv run pytest tests/end_to_end/test_on_chain_bera_opted_in.py \
  tests/end_to_end/test_on_chain_koinly_characterization.py \
  tests/end_to_end/test_on_chain_integrity_invariants.py \
  tests/unit/infrastructure/test_berachain_processor.py \
  tests/unit/infrastructure/test_lp_autodiscovery.py \
  tests/unit/infrastructure/test_on_chain_csv_reader.py \
  tests/unit/infrastructure/test_rpc_client.py \
  tests/unit/application/test_on_chain_config_loader.py \
  tests/unit/test_on_chain_tests_no_personal_data.py -q

# Full non-regression:
uv run pytest -q

# Audit guard (bucket 4 must not break it):
RUN_AUDIT_GUARD=1 uv run pytest tests/unit/test_on_chain_tests_no_personal_data.py -q

# Bucket 2: no stale F8 module-path drift in user-facing docs:
! grep -rn '_maybe_substitute_on_chain_th' docs/maintenance docs/architecture README.md

# Bucket 2: no lowercase INI-key prose (regression check, F5 stays fixed):
! grep -rn '`on_chain_th_wallets`' README.md docs/architecture docs/maintenance
```

## Tasks

### Task 1: Round-2 hardening - guard finally-unlink + bridge write inside try + write-failure test

Files:
- `src/tax_reporting/application/on_chain_th_substitution.py`
- `tests/end_to_end/test_on_chain_bera_opted_in.py`

- [x] `TestOnChainBeraOptedIn#test_bridge_cleaned_up_on_merge_write_failure`; given an opted-in wallet whose label matches the Koinly TH (so the F2 check passes) and a monkeypatched `Path.open` that raises `OSError("simulated write failure")` when opening `on_chain_merged_th.csv`, expects `maybe_substitute` raises (OSError wrapped by the boundary into ReportGenerationError OR propagates) AND `on_chain_th_bridge.csv` does NOT exist afterward (the try/finally unlinked it on the non-F2 raise path)
- [x] Run -> expect RED (today the bridge write is outside the try; a write-failure raise leaves the bridge; and the finally-unlink is unguarded)
- [x] In `maybe_substitute`: move the `serialize_projected_rows_to_th_csv(projected, on_chain_th_csv)` call INSIDE the existing try block (so the finally covers it). Wrap the finally's `on_chain_th_csv.unlink()` in its own `try/except OSError` that logs a WARNING and does NOT re-raise (so an unlink failure on a read-only dir cannot mask the original F2/merge exception). Verify the finally still does NOT unlink the merged file or `koinly_th` (the `on_chain_th_csv != koinly_th` and `on_chain_th_csv != merged_path` guards stay).
- [x] Run -> expect GREEN
- [x] Commit: `fix(on-chain): guard finally-unlink + move bridge write inside try (review r2 hardening)` (110b2ab)

### Task 2: F20-F23 + F8 doc drift (Low docs)

Files:
- `docs/maintenance/tax_reporting_guidelines.md`
- `README.md`
- `src/tax_reporting/infrastructure/on_chain/berachain_processor.py`
- `docs/maintenance/crypto_implementation_guidelines.md`
- `docs/architecture/on-chain-tx-design.md` (only if it carries the byte-identical claim)

Doc-only except the berachain_processor WARNING interpolation (one token).

- [x] F20: in `docs/maintenance/tax_reporting_guidelines.md` SRG-012, fix the broken cross-section anchor: change `koinly_guidelines.md "Multiple sources"` to match the actual heading `"Section 6 -- Koinly is one of multiple Transaction Sources"` (or a shorter unambiguous form)
- [x] F21: in `README.md` and SRG-012, soften the byte-identical claim: scope it to the on-chain substitution ("defaults to empty, which leaves the on-chain substitution inactive") and add a one-clause note that the token_origin TxSrc->TxHash migration (Task 4 of the prior plan) is a separate unconditional Koinly-path change for multi-LP-withdrawal wallets
- [x] F22: in `src/tax_reporting/infrastructure/on_chain/berachain_processor.py` (~line 666), change `sub_type.name if sub_type is not None else None` to `sub_type.name if sub_type is not None else "<none>"` (explicit degradation per AGENTS.md)
- [x] F8 doc drift: in `docs/maintenance/crypto_implementation_guidelines.md` lines ~1831, ~1849, update the stale `main.py`'s `_maybe_substitute_on_chain_th` references to `OnChainThSubstituter.maybe_substitute` in `src/tax_reporting/application/on_chain_th_substitution.py`
- [x] `! grep -rn '_maybe_substitute_on_chain_th' docs/maintenance docs/architecture README.md` -> empty
- [x] Commit: `docs(on-chain): fix SRG-012 anchor, byte-identical claim, sub_type interpolation, F8 module-path drift (F20-F23)` (db0313a)

### Task 3: F13 - on_chain_csv_reader failure-path tests

Files:
- `tests/unit/infrastructure/test_on_chain_csv_reader.py`

- [x] `TestOnChainCsvReader#test_malformed_row_skipped_good_rows_survive`; given a CSV with one good row (tx_hash `0xgood`) and one bad row (unparseable `timestamp_utc`), expects `read_on_chain_rows` returns 1 row (`0xgood`) and a WARNING mentioning the bad tx_hash
- [x] `TestOnChainCsvReader#test_direction_coerced_to_unknown_with_review_flag`; given a row with `direction=sideways`, expects the row's `direction == "unknown"` and `review_flag == "direction_coerced"`
- [x] `TestOnChainCsvReader#test_symlink_refused`; given a symlinked bera CSV, expects `FileProcessingError`
- [x] `TestOnChainCsvReader#test_size_cap_exceeded`; given a CSV exceeding the size cap, expects `FileProcessingError`
- [x] Run -> expect GREEN (these test EXISTING behavior; no production change. If any arm does not behave as documented, stop and flag; do not silently change production behavior in this task.)
- [x] Commit: `test(on-chain): cover csv reader malformed-row/direction-coercion/symlink/size-cap (F13)` (cfd4fcb)

### Task 4: F12 - contract-registry loader F1 guard tests

Files:
- `tests/unit/application/test_on_chain_config_loader.py`

- [x] `TestContractRegistryLoader#test_country_without_citation_rejected`; given a `build_contract_registry` entry with `operator_country="VG"` and no `citation`, expects `ConfigurationError` matching `"citation"`
- [x] `TestContractRegistryLoader#test_citation_without_country_rejected`; given an entry with `citation` and no `operator_country`, expects `ConfigurationError` matching `"operator_country"`
- [x] `TestContractRegistryLoader#test_invalid_iso_code_rejected`; given `operator_country="XX"`, expects `ConfigurationError` matching `"ISO-3166"`
- [x] `TestContractRegistryLoader#test_invalid_kind_rejected`; given an invalid `kind`, expects `ConfigurationError`
- [x] Run -> expect GREEN (existing behavior; no production change)
- [x] Commit: `test(on-chain): pin contract-registry loader F1 closed-enum + citation guards (F12)` (89db287)

### Task 5: F11 - rpc_client retry/backoff/redaction tests

Files:
- `tests/unit/infrastructure/test_rpc_client.py` *(new)*

These become load-bearing once Task 7 wires rpc_client, but the tests pin the
module's existing behavior independent of wiring.

- [x] `TestRpcClient#test_retries_then_raises_after_max_retries`; given `_http_post_json` monkeypatched to always raise `URLError`, expects `get_code` raises `FileProcessingError` matching "transport error" after exactly `max_retries+1` attempts (assert the call count, not just the raise)
- [x] `TestRpcClient#test_json_rpc_error_object_raises`; given `_http_post_json` returning a JSON-RPC error object (`{"error": {"code": -32000, "message": "reverted"}}`), expects `FileProcessingError`
- [x] `TestRpcClient#test_success_returns_result`; given `_http_post_json` returning `{"result": "0x..."}`, expects `get_code` returns the result
- [x] `TestRpcClient#test_backoff_grows_exponentially`; given consecutive failures, expects `time.sleep` called with growing intervals (`_backoff_base * 2**(attempt-1)`)
- [x] `TestRpcClient#test_redact_headers_no_api_key_leak`; given an `api_key="secret"`, expects the redacted headers used in the request do NOT contain "secret" (verify via the `_http_post_json` spy's received headers)
- [x] Run -> expect GREEN (existing behavior; tests patch the documented `_http_post_json` DI seam)
- [x] Commit: `test(on-chain): cover rpc_client retry/backoff/redaction via _http_post_json seam (F11)` (4aa12cc)

### Task 6: F4 - move MO1 cap into is_lp_token (instance counter)

Files:
- `src/tax_reporting/infrastructure/on_chain/lp_autodiscovery.py`
- `tests/unit/infrastructure/test_lp_autodiscovery.py`

This task makes the cap load-bearing for the processor's per-leg calls. It does
NOT wire rpc_client yet (Task 7 does); it just moves the enforcement so the cap
holds regardless of which entry point the processor uses.

- [x] `TestLpAutodiscovery#test_is_lp_token_respects_cap_independent_of_classify_many`; given an `LpAutodiscovery` with `cap=2` and a mock rpc_client whose `get_code` returns unknown bytecode, calling `is_lp_token` 3 times with distinct non-snapshot addresses, expects exactly 2 `rpc_client.get_code` calls (the cap allows 2 RPC-touching lookups), and the 3rd call returns a classification with `flag == CAP_REACHED` (assert the EXACT flag value, not just `.review`) and does NOT call `rpc_client.get_code`. This pins the budget-decrement semantics (pre-call check + decrement) so an off-by-one fails visibly.
- [x] `TestLpAutodiscovery#test_classify_many_cap_unchanged_after_move`; given `cap=2` and 4 distinct non-snapshot addresses via `classify_many`, expects exactly 2 RPC calls and 2 `CAP_REACHED`-flagged results (the move must preserve `classify_many`'s observable cap behavior: the first 2 get RPC, the rest get CAP_REACHED). This is the regression net for the `classify_many` refactor below.
- [x] `TestLpAutodiscovery#test_cap_resets_per_instance`; given two separate `LpAutodiscovery` instances each with `cap=2`, exhausting one does NOT exhaust the other (the counter is per-instance, seeded in `__init__`)
- [x] Run -> expect RED (today `is_lp_token` has no cap; the 3rd call hits the RPC)
- [x] In `LpAutodiscovery.__init__`: add `self._rpc_budget = self.cap` (instance counter). In `is_lp_token`, BEFORE the `rpc_client.get_code` call (~line 180), check `self._rpc_budget`; if `<= 0`, return the SAME `CAP_REACHED`-flagged classification that `classify_many` currently builds at lines 240-250 (same `LpClassification` flag value, same review reason text; do NOT change the reason text). Otherwise decrement `self._rpc_budget -= 1` immediately BEFORE the `get_code` call (pre-decrement, matching today's `classify_many` line 257 semantics where the decrement happens before `is_lp_token`). Then remove `classify_many`'s local `rpc_budget` tracking (lines 225, 240-250, 257): `classify_many` now simply delegates to `is_lp_token` per address, and the cap enforcement happens inside `is_lp_token` via the shared instance counter. The observable result is identical: the first `cap` non-snapshot addresses get RPC classification, the rest get `CAP_REACHED`. The two new tests above pin BOTH the `is_lp_token`-direct path and the `classify_many`-delegated path so the move cannot silently change either.
- [x] Run -> expect GREEN (both cap tests pass; the existing `test_rpc_fallback_timeout_and_cap` still passes if it asserts the cap behavior; verify and update if its assertion shape changed)
- [x] Commit: `fix(on-chain): move MO1 RPC cap into is_lp_token as instance counter (F4)` (b08c543)

### Task 7: F4+F9 - wire rpc_client from config-derived ON_CHAIN_RPC_URL

Files:
- `src/tax_reporting/domain/jurisdiction.py`
- `src/tax_reporting/infrastructure/config.py`
- `src/tax_reporting/application/on_chain_th_substitution.py`
- `src/tax_reporting/main.py`
- `tests/unit/infrastructure/test_config.py`
- `tests/unit/infrastructure/test_lp_autodiscovery.py` (the bytecode-fallback unit test)
- `tests/unit/application/test_on_chain_th_substitution.py` *(new; the two wiring-seam tests, matches the production module path)*
- `README.md` (document the new config key)

This is the largest task. It wires the RPC layer so new LP pools not in the
snapshot are auto-classified.

- [x] `TestLoadTaxJurisdictionConfig#test_on_chain_rpc_url_loaded`; given a `[TAX JURISDICTION]` section with `ON_CHAIN_RPC_URL = https://example.rpc`, expects `TaxJurisdictionConfig.on_chain_rpc_url == "https://example.rpc"`; given no key, expects `None`
- [x] `TestLpAutodiscovery#test_bytecode_fallback_classifies_v2_pair`; given an `LpAutodiscovery` with a mock rpc_client whose `get_code` returns bytecode whose sha256 matches a stored V2-pair fingerprint, expects `is_lp_token` classifies the address as Pair (unit test of the layer-2 fingerprint match through the DI seam)
- [x] `TestOnChainThSubstituter#test_rpc_url_none_yields_snapshot_only_substituter`; given `OnChainThSubstituter(on_chain_rpc_url=None)`, expects `maybe_substitute` builds `LpAutodiscovery` with `rpc_client=None` (verify via a spy/monkeypatch on the LpAutodiscovery ctor or the RpcClient import); this pins the byte-identical default (the wiring seam: config → OnChainThSubstituter(on_chain_rpc_url=...) → RpcClient iff set → LpAutodiscovery)
- [x] `TestOnChainThSubstituter#test_rpc_url_set_builds_rpc_client`; given `OnChainThSubstituter(on_chain_rpc_url="https://example.rpc")`, expects `maybe_substitute` builds `LpAutodiscovery` with a non-None `rpc_client` (the wiring-seam test the plan-review F3 flagged as missing)
- [x] Run -> expect RED (config field absent; substituter ctor has no on_chain_rpc_url kwarg; substituter still passes rpc_client=None)
- [x] In `src/tax_reporting/domain/jurisdiction.py`: add `on_chain_rpc_url: str | None = None` to `TaxJurisdictionConfig` (after `on_chain_th_wallets`, line ~134). Note config.py lines 45-52 auto-derive the field list from the dataclass, so this is the single source of truth.
- [x] In `src/tax_reporting/infrastructure/config.py`: (a) add `on_chain_rpc_url: str | None` to `JurisdictionSectionFields` NamedTuple (after `on_chain_th_wallets`); (b) in `_parse_jurisdiction_section`, read `section.get("ON_CHAIN_RPC_URL")` and pass it positionally to the `JurisdictionSectionFields(...)` ctor at line ~314; (c) in `_load_tax_jurisdiction_config`, update the POSITIONAL UNPACK at line ~353 (`country, fiscal_year, ... = _parse_jurisdiction_section(...)`) to include the new field, AND pass `on_chain_rpc_url=...` to the `TaxJurisdictionConfig(...)` ctor at line ~419 (NOT via flag_kwargs). CRITICAL lockstep (plan-review F5): `JurisdictionSectionFields` is a NamedTuple; adding a positional field requires updating BOTH the construction (line ~314) AND the positional unpack (line ~353) in the same commit, or the unpack raises ValueError. Constructor-signature-change audit: grep for every `JurisdictionSectionFields(`, `TaxJurisdictionConfig(`, and the positional unpack `= _parse_jurisdiction_section(` site (production + tests) and update each.
- [x] In `src/tax_reporting/application/on_chain_th_substitution.py`: add `on_chain_rpc_url: str | None = None` to `OnChainThSubstituter.__init__`. In `maybe_substitute` at the `LpAutodiscovery(snapshot=..., rpc_client=None)` construction (line ~228), build `rpc_client = RpcClient(rpc_url=on_chain_rpc_url) if on_chain_rpc_url else None` and pass it. Import `RpcClient`. When `on_chain_rpc_url` is None, behavior is byte-identical (snapshot-only).
- [x] In `src/tax_reporting/main.py`: thread `on_chain_rpc_url=tax_jurisdiction.on_chain_rpc_url` into the `OnChainThSubstituter(...)` construction. The EXACT site is `main.py:281` inside the `if opted_in_wallets and on_chain_year_for_th is not None:` gate (line 279); it is a chained call `OnChainThSubstituter().maybe_substitute(...)`, so the RPC URL must be passed to the `OnChainThSubstituter(...)` ctor (the first pair of parens), NOT to `maybe_substitute`. NOTE (plan-review F2): `tax_jurisdiction` is guaranteed non-None at this point because the gate at line 279 requires `opted_in_wallets` which is only non-empty when `tax_jurisdiction is not None` (line 264); state this assumption in the code comment. Verify the fail-loud try/except boundary (lines ~283-311) still wraps the construction + call.
- [x] In `README.md` `[TAX JURISDICTION]` section: document `ON_CHAIN_RPC_URL` (optional Berachain RPC endpoint; when set, the on-chain path auto-classifies LP tokens not in the snapshot via bytecode fingerprinting; when unset, non-snapshot tokens fall to Unknown+review).
- [x] Run -> expect GREEN (config test + bytecode-fallback unit test + the two wiring-seam tests pass; characterization suites unchanged because the default is unset → snapshot-only)
- [x] Commit: `feat(on-chain): wire rpc_client from ON_CHAIN_RPC_URL for LP bytecode fallback (F4, F9)` (6368475)
