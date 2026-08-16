# Plan: On-chain tx tagger review r1 fixes (F1, F2, F3, F5, F6, F7, F8, F10)

Resolves the round-1 code-review findings staged in
`docs/history/reviews/2026-08-04-2026-08-02-on-chain-tx-tagger-code-review-r1.md`
against `master` on branch `2026-08-02-on-chain-tx-tagger`.

Python testing guidance: `docs/maintenance/python_guidelines.md` (pytest fixture
scoping, mock-target rules, `pytest.raises(match=)` PT011). Domain rules:
`docs/maintenance/crypto_implementation_guidelines.md`,
`docs/maintenance/koinly_guidelines.md`.

## Terms

- TH: Transaction History, the Koinly-shaped CSV the crypto pipeline consumes.
- bera CSV: `bera_transactions.csv`, the raw on-chain leg export.
- opted-in wallet: a wallet label listed in `ON_CHAIN_TH_WALLETS` whose TH rows
  are replaced by the on-chain projection.
- merged TH: the substituted TH file the pipeline reads instead of the user's
  Koinly export for an opted-in run.
- carrier row: the one projected TH row per tx carrying the parent-tx gas.
- event_id: on-chain-native split-Event discriminator threaded through the TH CSV.
- audit guard: `tests/unit/test_on_chain_tests_no_personal_data.py`, opt-in via
  `RUN_AUDIT_GUARD=1`, uses `sys.addaudithook` to catch gitignored personal-data
  reads in a single pytest subprocess.

## Gist & Examples

The round-1 review of the on-chain transaction-tagger feature surfaced two
blocking and several non-blocking findings. This plan resolves the blocking
ones (F1 destructive Koinly-TH overwrite, F5 config-key case mismatch) plus the
High non-blocking (F2 silent double-count, F8 main.py god-module) and the Medium
non-blocking in scope (F3 spam laundering, F6 loan-activity doc gap, F7 cross-run
leftover collision, F10 audit-guard coverage holes).

The central design change is F1+F7: today `_merge_on_chain_into_koinly_th`
writes the merged TH *on top of the user's real Koinly export* (or to a derived
name that matches the `*transaction_history*.csv` glob the pipeline re-runs at
`crypto_reporting.py:227`). On a mid-write crash the user's primary, gitignored
Koinly export is destroyed, and a leftover merged file re-triggers the glob
collision across runs. The fix writes the merged TH to a non-globbing derived
path (`on_chain_merged_th.csv`) and threads that explicit path forward through
the loader so the pipeline reads it directly; the user's real Koinly TH is never
opened for write.

Example before (F1, `main.py:889`):
```python
merged_path = koinly_th if koinly_th is not None and koinly_th != on_chain_th_csv else (
    koinly_dir / "on_chain_merged_transaction_history.csv"  # matches the glob
)
with merged_path.open("w", ...) as fh:  # overwrites the user's real Koinly TH
    ...
```

Example after:
```python
# Never overwrite the user's real Koinly export; write a derived, non-globbing file.
merged_path = koinly_dir / "on_chain_merged_th.csv"
with merged_path.open("w", ...) as fh:
    ...
return OnChainThSubstitutionResult(reconciliation=..., merged_th_path=merged_path)
```
and `main.py` threads `merged_th_path` into `_load_crypto_tax_report(...)` which
forwards it to `load_koinly_crypto_report(transaction_history_override=...)`,
replacing the re-glob at `crypto_reporting.py:227`.

The other fixes: F8 extracts the on-chain TH-substitution logic out of `main.py`
(into `application/on_chain_th_substitution.py`) before the behavioral fixes land
there; F2 normalizes wallet labels case-insensitively and fails loud when an
opted-in label matches nothing; F3 adds a heterogeneity guard so same-asset
multi-sender rewards split per sender instead of laundering spam into `staking`;
F5/F6 are doc-only; F10 makes the audit guard year-agnostic and module-discovery
glob-based.

## Evaluation Criteria

**Quality dimensions:**
- correctness (F1/F2/F3/F7): the user's real Koinly TH is byte-identical after
  an opted-in run; opted-in labels match case-insensitively and unmatched labels
  raise; same-asset multi-sender rewards split per sender; two opted-in runs on
  the same dir do not self-cannibalize.
- maintainability (F8): `main.py` shrinks below ~600 lines and the on-chain TH
  substitution lives in a dedicated service module; characterization baselines
  unchanged.
- security/operability (F10): the audit guard catches a personal-data read for
  ANY fiscal year (not just 2025) and auto-covers newly added on-chain test
  modules without editing a static list.
- doc-accuracy (F5/F6): user-facing docs use the real INI key `ON_CHAIN_TH_WALLETS`;
  the loan-activity divergence is documented.

**Done when:**
- All new RED tests pass (GREEN) and the existing on-chain + characterization
  suites pass (three `test_on_chain_bera_opted_in.py` tests are updated in Task 2
  to consume `result.merged_th_path` instead of re-globbing; all other suites
  pass unchanged).
- `uv run pytest -q` full suite is green (non-regression).
- `RUN_AUDIT_GUARD=1 uv run pytest tests/unit/test_on_chain_tests_no_personal_data.py`
  passes.
- `wc -l src/tax_reporting/main.py` shows main.py under ~600 lines.
- `! grep -rn 'on_chain_th_wallets' README.md docs/architecture docs/maintenance`
  (no lowercase INI-key prose remains in user-facing docs; Python-attribute refs
  in code comments are excluded by scoping the grep to the doc files).

**Ship when:** N/A (local-only personal tool; no deploy).

## Review Scope

**Explicit must-fix**; findings on these paths are always in scope (review and
fix if valid):

**Production code:**
- `src/tax_reporting/application/on_chain_th_substitution.py` *(new)*
- `src/tax_reporting/main.py`
- `src/tax_reporting/application/crypto_reporting.py`
- `src/tax_reporting/infrastructure/on_chain/berachain_processor.py`
- `src/tax_reporting/infrastructure/config.py` *(optional F5 defense-in-depth)*

**Tests:**
- `tests/end_to_end/test_on_chain_bera_opted_in.py`
- `tests/unit/infrastructure/test_berachain_processor.py`
- `tests/unit/test_on_chain_tests_no_personal_data.py`

**Docs (F5/F6):**
- `README.md`
- `docs/architecture/on-chain-tx-design.md`
- `docs/maintenance/tax_reporting_guidelines.md`
- `docs/maintenance/crypto_implementation_guidelines.md`
- `docs/maintenance/koinly_guidelines.md`

**Plan-related extension**; implementation and review may change files not listed
above (e.g. `src/tax_reporting/application/on_chain_th_adapter.py` if the merged
filename constant moves there, or `tests/end_to_end/test_on_chain_integrity_invariants.py`
if a regression surfaces). Treat a finding as in scope when it is causally related
to this plan.

**Out of scope; reject unless plan-related:**
- `src/tax_reporting/infrastructure/on_chain/lp_autodiscovery.py` and
  `src/tax_reporting/infrastructure/on_chain/rpc_client.py`; F4/F9 (RPC cap +
  yagni) are deferred to a separate decision.
- `tests/unit/infrastructure/test_lp_autodiscovery.py`,
  `tests/unit/infrastructure/test_on_chain_csv_reader.py`,
  `tests/end_to_end/test_on_chain_integrity_invariants.py` loader tests; F11/F12/F13
  missing failure-path tests are deferred.
- `docs/history/plans/completed/2026-08-02-on-chain-tx-tagger.md` and
  `docs/history/reviews/*`; frozen history, not edited for F5.

## Design Invariants (CR Guard)

- **Koinly-byte-identical default (flag off).** When `ON_CHAIN_TH_WALLETS` is
  empty/unset, the on-chain path is fully skipped and the pipeline reads the
  user's real Koinly TH exactly as before. The new `transaction_history_override`
  param defaults to `None` (glob path); threading it must not change the flag-off
  path. Pinned by `test_on_chain_koinly_characterization.py` baselines.
- **User's real Koinly TH is read-only during substitution.** No code path opened
  by this plan may write to, truncate, or unlink the resolved `koinly_th`. The
  merged output lives at `on_chain_merged_th.csv` only.
- **Fail-loud opted-in contract (M1).** A parse failure on the opted-in path must
  raise `ReportGenerationError`, never silently fall back to Koinly. The
  `try/except ReportGenerationError|ConfigurationError|Exception` boundary at
  `main.py:294-322` stays; extraction must preserve it.
- **event_id CSV bridge.** The merged TH must continue to carry `event_id` on
  on-chain rows and empty `event_id` on Koinly rows; `TH_CSV_COLUMNS` ordering is
  unchanged.
- **`_find_report_path` glob semantics.** The pipeline's TH discovery glob is
  `*transaction_history*.csv`. The merged filename `on_chain_merged_th.csv` must
  NOT match it; discovery happens via the explicit `transaction_history_override`.
- **Heterogeneity-guard rule (AGENTS.md).** Aggregators taking `entries[0]` for a
  field assumed constant must guard when the field varies across the group.

## Validation Commands

```bash
# Affected suites (run after each task):
uv run pytest tests/end_to_end/test_on_chain_bera_opted_in.py \
  tests/end_to_end/test_on_chain_koinly_characterization.py \
  tests/end_to_end/test_on_chain_integrity_invariants.py \
  tests/unit/infrastructure/test_berachain_processor.py \
  tests/unit/test_on_chain_tests_no_personal_data.py -q

# Full non-regression:
uv run pytest -q

# Audit guard after Task 7:
RUN_AUDIT_GUARD=1 uv run pytest tests/unit/test_on_chain_tests_no_personal_data.py -q

# F8 shrink check:
test "$(wc -l < src/tax_reporting/main.py)" -lt 600

# F5: no lowercase INI-key prose in user-facing docs (Python-attribute refs are
# in src/, not these doc files):
! grep -rn '`on_chain_th_wallets`' README.md docs/architecture docs/maintenance

# F1: merged filename does NOT match the TH discovery glob:
if grep -rn 'on_chain_merged_th\.csv' src/tax_reporting/application/on_chain_th_substitution.py | grep -q .; then :; else echo "merged path constant missing"; exit 1; fi
```

## Tasks

### Task 1: F8 - Extract `OnChainThSubstituter` service (pure move, byte-identical)

Files:
- `src/tax_reporting/application/on_chain_th_substitution.py` *(new)*
- `src/tax_reporting/main.py`
- `tests/end_to_end/test_on_chain_bera_opted_in.py`

This is a pure refactor (no behavior change). Use characterization items that run
GREEN before and after the move.

- [x] Run → expect GREEN (characterization: `TestOnChainBeraOptedIn#test_opted_in_wallet_uses_onchain_path`; captures existing merge behavior - opted-in rows replaced, non-opted-in Koinly rows survive, on-chain rows carry non-empty `event_id`)
- [x] Run → expect GREEN (characterization: `TestOnChainBeraOptedIn#test_non_prefixed_koinly_th_survives_merge`; captures the F1 prefixed-edge pre-resolution + provenance)
- [x] Run → expect GREEN (characterization: `TestOnChainBeraOptedIn#test_no_koinly_th_on_chain_rows_become_th`; captures the None branch + standalone-CSV unlink)
- [x] Run → expect GREEN (characterization: `TestOnChainKoinlyCharacterization#*`; Koinly-only baselines unchanged - the flag-off path is untouched)
- [x] Create `src/tax_reporting/application/on_chain_th_substitution.py` with `class OnChainThSubstituter` owning: the body of `_maybe_substitute_on_chain_th` (as `maybe_substitute`), `_merge_on_chain_into_koinly_th` (private method), `_build_on_chain_reconciliation_record` (private method), `_resolve_registry_path` (private method), the `OnChainMergeStats` dataclass (renamed from `_OnChainMergeStats`; fields `koinly_per_wallet: dict[str,int]`, `dropped_koinly_rows: int`), and `_DELTA_SAMPLE_HASH_CAP = 10`. Move the on-chain-only imports out of `main.py` (lines 19–24, 27–30, 32–36, 52, 60, 62–65 per the structural map: `_find_repository_root`, `OnChainDeltaBlock`/`OnChainReconciliationRecord`/`WalletSourceProvenance`, `load_contracts`/`load_lp_snapshot`, `TH_CSV_COLUMNS`/`project_on_chain_transactions`/`serialize_projected_rows_to_th_csv`, `EventType`/`OnChainTransaction`, `_find_report_path`/`read_koinly_rows`, `BerachainProcessor`/`check_on_chain_integrity`/`LpAutodiscovery`/`read_on_chain_rows`).
- [x] In `main.py`: replace the `_maybe_substitute_on_chain_th(...)` call at `main.py:295` with `OnChainThSubstituter(...).maybe_substitute(...)`. Keep the `try/except ReportGenerationError|ConfigurationError|Exception` boundary (`main.py:294-322`) byte-identical - only the inner call changes. Re-import only `OnChainThSubstituter` and the `OnChainReconciliationRecord` type that `_main` threads.
- [x] Constructor-signature-change audit: grep the repo for `_maybe_substitute_on_chain_th`, `_merge_on_chain_into_koinly_th`, `_build_on_chain_reconciliation_record`, `_OnChainMergeStats`, `_resolve_registry_path`. Only `tests/end_to_end/test_on_chain_bera_opted_in.py:57` imports one (`_maybe_substitute_on_chain_th`); update that import to construct `OnChainThSubstituter` and call `.maybe_substitute(...)` with the same kwargs. List every other reference as "docstring/comment only, no change."
- [x] Unused-import sweep in `main.py` after the move: `from dataclasses import dataclass, field` (line 16) and `import csv` (line 11) become unused once the on-chain helpers (the only consumers of `dataclass`/`field`/`csv.DictWriter`) move out - UNLESS other main.py code uses them; grep `main.py` for `dataclass`, `field(`, `csv.` after the extraction and remove any now-unused import to avoid Ruff F401. Verify against the HEAD blob (`git show HEAD:src/tax_reporting/main.py | ruff check`) before committing so pre-existing debt is not mis-attributed.
- [x] Run → expect GREEN (all characterization suites above still pass; `uv run pytest -q` full suite green)
- [x] Verify `wc -l src/tax_reporting/main.py` shrinks materially (toward ~550)
- [x] Commit: `refactor(on-chain): extract OnChainThSubstituter service from main.py (F8)` (abd27f5)

### Task 2: F1+F7 - Non-globbing merged path + explicit threading

Files:
- `src/tax_reporting/application/on_chain_th_substitution.py`
- `src/tax_reporting/application/crypto_reporting.py`
- `src/tax_reporting/main.py`
- `tests/end_to_end/test_on_chain_bera_opted_in.py`

- [x] `TestOnChainBeraOptedIn#test_user_koinly_th_byte_identical_after_substitution`; given a real Koinly TH seeded at `koinly_dir/koinly_2025_transaction_history.csv` and a bera CSV for an opted-in wallet, expects the user's Koinly TH file is byte-identical (same sha256) after `maybe_substitute`, and the merged output lives at `on_chain_merged_th.csv` (assert its name does NOT contain `transaction_history`)
- [x] `TestOnChainBeraOptedIn#test_merged_th_read_via_override_not_glob`; given the substitution result, expects `load_koinly_crypto_report(koinly_dir=..., transaction_history_override=merged_th_path)` reads the merged file (opted-in Koinly rows gone, on-chain rows present) while the user's real Koinly TH still on disk is NOT the file read
- [x] `TestOnChainBeraOptedIn#test_two_opted_in_runs_do_not_self_cannibalize`; given two consecutive `maybe_substitute` calls on the same `koinly_dir` with no real Koinly TH (the None branch), expects the second run produces a correct merged TH and `dropped_koinly_rows == 0` (no self-cannibalization), and exactly one `on_chain_merged_th.csv` exists (overwritten, not duplicated)
- [x] Run → expect RED
- [x] In `OnChainThSubstituter._merge_on_chain_into_koinly_th`: change `merged_path` to `koinly_dir / "on_chain_merged_th.csv"` always (both the `koinly_th is not None` and None branches). Stop overwriting `koinly_th`; the user's real Koinly TH is opened READ-ONLY (for row-drop counting) and never written. Keep the `on_chain_th_csv` write + post-merge unlink unchanged. Remove the false "primary Koinly export is reproducible" comment. Return the merged path.
- [x] Change the substitution result to carry `merged_th_path: Path` (add a small dataclass `OnChainThSubstitutionResult(reconciliation: OnChainReconciliationRecord | None, merged_th_path: Path | None)`; `None` when no bera CSV). Update `maybe_substitute` to return it.
- [x] In `crypto_reporting.load_koinly_crypto_report`: add `transaction_history_override: Path | None = None`; at line 227, `transaction_history_file = transaction_history_override if transaction_history_override is not None else _find_report_path(koinly_dir, "transaction_history", ".csv")`. The required-file check at lines 229-235 continues to gate on the resolved path. Backward-compat: `None` preserves the glob (flag-off path byte-identical). Grep all callers of `load_koinly_crypto_report` and `_load_crypto_tax_report` (production + tests); confirm the only production caller is the `_main` path and every test caller omits the new param (default `None`), so backward compat holds.
- [x] In `main.py._load_crypto_tax_report`: add `transaction_history_override: Path | None = None` and forward it to `load_koinly_crypto_report`. In `_main`, capture `substitution = OnChainThSubstituter(...).maybe_substitute(...)`; set `on_chain_reconciliation = substitution.reconciliation if substitution else None` and pass `transaction_history_override=substitution.merged_th_path if substitution else None` into `_load_crypto_tax_report`. Preserve the fail-loud try/except boundary.
- [x] Rewrite the THREE existing tests in `tests/end_to_end/test_on_chain_bera_opted_in.py` that re-discover the merged TH via `_find_report_path` - because `on_chain_merged_th.csv` no longer matches `*transaction_history*.csv`, the glob returns None and the tests break. Switch each to consume `result.merged_th_path` from the new `OnChainThSubstitutionResult` instead of re-globbing: (a) `test_opted_in_wallet_uses_onchain_path` (line 232: `merged_th = _find_report_path(...)` → use `substitution.merged_th_path`); (b) `test_non_prefixed_koinly_th_survives_merge` (line 307); (c) `test_no_koinly_th_on_chain_rows_become_th` (lines 365-388: replace the `_find_report_path` + line-374 name assertion with `merged_th = substitution.merged_th_path; assert merged_th is not None; assert merged_th.name == "on_chain_merged_th.csv"`). The standalone-CSV unlink assertion at line 391 still holds. Keep the row-content assertions (`_read_th_data_rows(merged_th)`) reading from the explicit path.
- [x] Run → expect GREEN
- [x] Commit: `fix(on-chain): write merged TH to non-globbing path; thread explicit override (F1, F7)` (43d253d)

### Task 3: F2 - Wallet-label normalization + fail-loud on no-match

Files:
- `src/tax_reporting/application/on_chain_th_substitution.py`
- `tests/end_to_end/test_on_chain_bera_opted_in.py`

- [x] `TestOnChainBeraOptedIn#test_opted_in_label_case_insensitive_match`; given `opted_in_wallets=["BERA"]` and a Koinly TH whose `Sending Wallet` cell is `bera` (different case), expects the BERA wallet's Koinly rows ARE dropped (matched case-insensitively) and on-chain rows are present in the merged TH
- [x] `TestOnChainBeraOptedIn#test_opted_in_label_not_in_koinly_th_raises`; given `opted_in_wallets=["GHOST"]` matching no `Sending Wallet`/`Receiving Wallet` in the Koinly TH, expects `ReportGenerationError` whose message matches `"not found in Koinly TH"` (fail-loud, not silent double-count)
- [x] Run → expect RED
- [x] In `_merge_on_chain_into_koinly_th`: add a module-level `_norm_label(s) -> str` returning `"".join(ch for ch in s.strip().casefold() if ch.isprintable())`. Build `opted_norm = {_norm_label(w) for w in opted_in_wallets if w.strip()}`. In the drop loop, compute `sending_n = _norm_label(sending_raw)`, `receiving_n = _norm_label(receiving_raw)`, and drop when either is in `opted_norm`; track the set of matched normalized labels. After the loop (when `koinly_th is not None`), if `opted_norm - matched`, raise `ReportGenerationError(f"Opted-in wallet label(s) not found in Koinly TH after normalization: {sorted(opted_norm - matched)}")`. Reconcile `koinly_per_wallet` and `dropped_koinly_rows` so per-wallet counts stay correct under the normalized match. (Note: implement agent found `ReportGenerationError` was NOT pre-imported; added `from ..domain.exceptions import ReportGenerationError`.)
- [x] Run → expect GREEN
- [x] Commit: `fix(on-chain): normalize opted-in labels + fail loud on no-match (F2)` (e62063a)

### Task 4: F3 - Heterogeneity guard in `_group_legs_by_asset`

Files:
- `src/tax_reporting/infrastructure/on_chain/berachain_processor.py`
- `tests/unit/infrastructure/test_berachain_processor.py`

- [x] `TestBerachainProcessor#test_same_asset_multi_sender_reward_splits_per_sender`; given a tx with two same-asset reward in-legs from different senders (leg A from a registered reward-distributor, leg B from an unverified address), expects TWO Reward Events emitted for that asset: one `sub_type=staking` for the verified-sender amount, one `sub_type=spam` with `review=True` for the unverified-sender amount (not one collapsed `staking` event for the summed amount)
- [x] Run → expect RED
- [x] In `_group_legs_by_asset` (berachain_processor.py:573): after grouping by `asset`, for each asset compute `senders = {(leg.from_address or "").lower() for leg in asset_legs}`. If `len(senders) > 1`, re-group that asset's legs by `(leg.from_address or "").lower()`, log a WARNING naming `tx_hash`/asset/sender-count, and emit one summed leg per sender. The callers `_reward_then_swap_events` (line 383) and `_multi_token_reward_events` (line 409) then naturally emit one Reward Event per `(asset, sender)`. (If re-grouping changes the dict value shape, update the two call sites to iterate the per-sender sub-lists.) Add a small-N absolute floor so a single heterogeneity case is not swallowed by the rate guard. (Implemented via option 1: `tx_hash` passed into the helper; both callers updated to iterate per-sender sub-lists; return shape `{asset: [summed_leg_per_sender, ...]}`.)
- [x] Run → expect GREEN
- [x] Commit: `fix(on-chain): split same-asset multi-sender rewards per sender (F3)` (fe4935a)

### Task 5: F5 - Config-key case mismatch (docs)

Files:
- `README.md`
- `docs/architecture/on-chain-tx-design.md`
- `docs/maintenance/tax_reporting_guidelines.md`
- `docs/maintenance/crypto_implementation_guidelines.md`
- `docs/maintenance/koinly_guidelines.md`
- `src/tax_reporting/infrastructure/config.py` *(optional defense-in-depth)*

Doc-only rename of the INI-key prose; no RED test required for the docs.

- [x] In `README.md:76`: change `` `on_chain_th_wallets` `` (INI-key prose) to `` `ON_CHAIN_TH_WALLETS` ``
- [x] In `docs/architecture/on-chain-tx-design.md` lines 279, 283, 336, 387: change the INI-key prose to `ON_CHAIN_TH_WALLETS`
- [x] In `docs/maintenance/tax_reporting_guidelines.md:98` (SRG-012): change to `ON_CHAIN_TH_WALLETS`
- [x] In `docs/maintenance/crypto_implementation_guidelines.md` lines 1807, 1831, 1840, 1849: change INI-key prose to `ON_CHAIN_TH_WALLETS`
- [x] In `docs/maintenance/koinly_guidelines.md` lines 326, 329, 337 (§6): change INI-key prose to `ON_CHAIN_TH_WALLETS`
- [x] Verify Python-attribute references (`tax_jurisdiction.on_chain_th_wallets` in `src/` code comments, and any doc prose that explicitly says "the Python field/attribute `on_chain_th_wallets`") stay lowercase; do NOT edit them. Each edit must be scoped to prose describing the INI key the user types into `config.ini` `[TAX JURISDICTION]`, not prose describing the attribute. When a sentence is ambiguous, reword to name the INI key explicitly (`the ON_CHAIN_TH_WALLETS INI key (the Python attribute is on_chain_th_wallets)`) rather than blanket-renaming.
- [x] Verify `docs/history/plans/completed/2026-08-02-on-chain-tx-tagger.md` and `docs/history/reviews/*` are NOT edited (frozen history)
- [x] Optional defense-in-depth: in `config.py` loader, after reading the section, warn via `logger.warning` when a literal lowercase `on_chain_th_wallets` key is present in `[TAX JURISDICTION]` (the user almost certainly followed the docs). Add `TestConfigLoader#test_lowercase_on_chain_key_warns`; given a config with the lowercase key, expects a WARNING matching `"ON_CHAIN_TH_WALLETS"` (advising the correct case) (ADDED)
- [x] Run → expect GREEN (docs build / `uv run pytest tests/unit/infrastructure/test_config.py -q` if the optional loader change lands)
- [x] `! grep -rn '\`on_chain_th_wallets\`' README.md docs/architecture docs/maintenance` → empty
- [x] Commit: `docs(on-chain): use real INI key ON_CHAIN_TH_WALLETS in user-facing docs (F5)` (cb0ad3a)

### Task 6: F6 - Loan-activity divergence (docs)

Files:
- `docs/maintenance/koinly_guidelines.md`
- `docs/maintenance/tax_reporting_guidelines.md`

Doc-only; no RED test.

- [x] In `docs/maintenance/koinly_guidelines.md` §6 after line 343, append: the on-chain `EventType` vocabulary has no `Loan`/`Loan repayment`/`Loan fee` tag (see adapter `EVENT_TYPE_TO_KOINLY`); a wallet opted into on-chain TH will NOT produce loan-activity rows, so `loan_activity.py` classification and the loan-affected FIFO rebuild (which feeds the PT `exclude_loan_repayment_gains` path) are lost for that wallet. If the opted-in wallet has loan activity in Koinly, do not opt it into the on-chain TH path until a `Loan` EventType is added.
- [x] Mirror the same note in `docs/maintenance/tax_reporting_guidelines.md` SRG-012
- [x] Commit: `docs(on-chain): document loan-activity divergence for opted-in wallets (F6)` (05cff16)

### Task 7: F10 - Audit guard year-agnostic + glob discovery

Files:
- `tests/unit/test_on_chain_tests_no_personal_data.py`

- [x] `TestOnChainTestsNoPersonalData#test_guard_catches_personal_data_any_year`; given a synthetic `resources/source/2026/berachain_contracts.json` created in a tmp dir and a probe test module that opens it, expects the guard (run with `RUN_AUDIT_GUARD=1`) to FAIL/report the hit (year-agnostic catch). Clean up the tmp artifact in a `finally`. (Construct the test so it does not leave a real 2026 file in the repo.) (Implemented via pure-helper `_is_forbidden_open` + synthetic `tmp_path` paths, no real 2026 file; plus a 17-row parametrized predicate test.)
- [x] Run → expect RED (today the guard only forbids 2025-prefixed paths, so a 2026 read passes)
- [x] In `tests/unit/test_on_chain_tests_no_personal_data.py`: replace the literal-2025 `_FORBIDDEN_PREFIXES` (lines 39-44) with a year-agnostic predicate. Inside the `_PROBE` template (lines 60-75), change the hook match from `any(p.startswith(f) for f in forbidden)` to a path-shape check: resolve `p` as a `Path` and forbid when it is under `resources/source/<segment>/` or `resources/result/<segment>/` AND `<segment> != "example"` (covers any digits-year dir). Pass `_PROJECT_ROOT` into the probe so the shape check is anchored. (Implemented as pure helper `_is_forbidden_open(path_str, project_root)`; probe body inlines the same logic; project_root passed via sys.argv[1].)
- [x] Replace the static `_ON_CHAIN_TEST_PATHS` list (lines 49-54) with glob discovery: `sorted(glob("tests/**/test_*on_chain*.py", recursive=True)) + sorted(glob("tests/**/test_*bera*.py", recursive=True))` resolved under `_PROJECT_ROOT`, deduped + sorted. Keep the single-subprocess `sys.addaudithook` design intact. (13 modules discovered, was 4 static; guard module itself excluded to prevent recursion.)
- [x] Keep the `RUN_AUDIT_GUARD=1` opt-in skip (lines 93-97) unchanged
- [x] Run → expect GREEN (`RUN_AUDIT_GUARD=1 uv run pytest tests/unit/test_on_chain_tests_no_personal_data.py -q`); 17 passed live
- [x] Commit: `test(on-chain): make personal-data audit guard year-agnostic + glob-discovered (F10)` (2bc2e9e)
