# Plan: On-chain TH validation harness + parser/registry fixes (Koinly cancellation P1)

Promoted from backlog: `docs/history/backlog/2026-08-18-koinly-cancellation-program.md` (P1).
Decisions: PD-009/PD-010/PD-011 in `docs/maintenance/project-decisions.md`; glossary terms
*Validation baseline*, *Discrepancy cluster*, *Cluster signature*, *Dispositions file*,
*Semantic equivalence*. Language-specific testing traps: `python_guidelines.md`
(referenced by bare name per AGENTS.md; it lives in the ai-playbook shadow corpus,
not under this repo's `docs/maintenance/`).

**Format deviation from the backlog (flagged):** the dispositions file is
`on_chain_th_dispositions.toml`, not `.yaml`: the project has no YAML dependency
(`pyproject.toml` deps are `openpyxl` + `pycountry` only) and stdlib `tomllib` gives a
strict, fail-loud parse; appended `[[clusters]]` blocks are valid append-only TOML.
Everything else about the artifact (append-only, user-owned feedback loop, gate
semantics) is unchanged.

## Terms

- **Semantic equivalence** (PD-010): two TH projections of the same on-chain tx are
  equivalent when, per shared `tx_hash`, net amounts per `(asset, direction)` match
  within the 8-decimal display tolerance and each event's Koinly `(Type, Tag)` combo is
  in the compatibility table. Row cardinality is irrelevant (downstream keys on
  `(tx_hash, event_id)`).
- **Discrepancy cluster**: the unit of resolution, covering all divergent txs sharing one
  PII-free *cluster signature*. Resolved only cluster-level (new rule / updated rule /
  accepted as normal); there is no per-tx ledger.
- **Cluster signature**: PII-free semantic key - event combo + Koinly Type/Tag combo +
  sender-registration class + LP-involvement + fee-surface class + zero-display flag.
  Never tx hashes, wallet addresses, dates, or amounts; stable across re-runs.
- **Dispositions file**: `resources/result/<year>/on_chain_th_dispositions.toml`,
  append-only; harness appends a template `[[clusters]]` block per NEW signature, the
  user fills `disposition` (`missing_rule` | `incorrect_processing` |
  `acceptable_difference`), `root_cause`, `action`.
- **Validation baseline / datasets**: the real personal 2025 Koinly export set - the
  ONLY Koinly baseline that will ever exist (corrected 2026-08-18: the subscription
  covers 2025 only, so no 2026 export set can be taken; 2026 is on-chain-only with no
  Koinly cross-check by construction).
- **Walk-forward holdout**: the 2025 baseline is validated in two windows - tune on H1
  (`--from/--to` window), freeze rules/registries/compatibility table, then ONE
  full-year run whose NEW cluster signatures (never seen in H1) measure how the frozen
  rules handle unseen activity. Honest caveat: the 2026-08-18 full-year cross-tab
  already informed the cluster taxonomy, so this is an implementation-generalization
  holdout, not a blind one.
- **Gas-only tx / GasBurn**: tx whose only effect is burning gas; adapter emits
  `crypto_withdrawal / Cost` with `Sent Amount` = gas, `Fee Amount` empty (B5).
- **Carrier-row gas rule**: parent-tx gas lands on exactly ONE projected row's
  `Fee Amount` (GasBurn rows excepted per B5); other rows of the same tx carry empty fee.
- **M1 fail-loud boundary**: an opted-in wallet's on-chain TH parse failure raises
  `ReportGenerationError`; never swallowed by a soft-fail handler.
- **Skill-gate marker; Session key**: plans-skill write gate per
  `ai-playbook/agents/hooks/skill-gate/README.md`; session id via the shared
  `session_channel.py` subprocess (emptiness check first; empty → literal `no-session`,
  else `sha1(value)[:16]`). Refreshed before every plan-file write; fail-loud.

## Gist & Examples

**What changes:** a committed, user-runnable validation command
(`uv run tax-reporting --validate-on-chain-th <year>`) runs the *production* on-chain
path (registry load → `read_on_chain_rows` → `BerachainProcessor.process` → integrity +
freshness audit → adapter projection) on the REAL personal data for `<year>`, read-only,
and diffs the projection against the real Koinly transaction-history export under the
PD-010 semantic-equivalence rules. Divergences are grouped into discrepancy clusters by
PII-free signature; three artifacts land under gitignored `resources/result/<year>/`
(`on_chain_th_validation.md` + `on_chain_th_validation_diff.csv` regenerated each run;
`on_chain_th_dispositions.toml` append-only). The command exits 0 only when every
remaining cluster is dispositioned `acceptable_difference`. The command takes an
optional inclusive `--from/--to` date window (both sides filtered by date) so the
baseline can be validated walk-forward: tune on H1, freeze, then one full-year run
whose NEW signatures measure generalization to unseen activity. On top of the harness,
the known parser/registry gaps are fixed: C1 (zero-value gas-carrier leg misroutes reward
claims into `Swap`), C3 (no `self_wallet` registry kind → self-transfers classify as
Reward/spam), C2 enablement (LP compatibility-table entries + snapshot/RPC path).

**Why needed:** Koinly is being cancelled after TY2026 (PD-009). The on-chain parser has
never run in production (`config.ini` has no `ON_CHAIN_*` keys) and the real-data
cross-tab (backlog, 2026-08-18) shows ~110 misrouted reward claims, ~44 LP ops falling
to `Unknown`/`Swap`, and 10 self-transfers tagged Reward/spam. The harness is the
instrument that proves each fix lands (its cluster vanishes) and that nothing new
regressed - the acceptance gate for flipping `ON_CHAIN_TH_WALLETS` is zero-exit on the
2025 validation dataset, the only Koinly baseline that will ever exist.

**Example (worked, C1):** tx with one in-leg `BGT 12.345678901` from the registered BGT
distributor and one out-leg `BERA 0.00000000` (the gas-carrier; tx gas `0.001 BERA`).
Today `_classify_events` sees non-empty in/out legs → generic `Swap`
(`berachain_processor.py:295-297`); Koinly renders `Reward` rows (BGT, 8-decimal rounded)
+ one `Cost` row (gas) → comparator: type mismatch → cluster
`events=Swap|koinly=crypto_deposit/Reward+crypto_withdrawal/Cost|sender=reward_distributor|lp=false|fee=cost_rows|zero_display=false`
(signature encoding: each Koinly combo is `Type/Tag`, combos join with `+`, components
join with `|` - `|` is ONLY the component separator, never inside a value).
After the C1 fix the tx classifies `Reward` (subtype staking), the projected row is
`crypto_deposit/Reward`, buckets match within tolerance → the cluster stops occurring →
its (fix-type) disposition now asserts absence and the gate passes for it.

**Example (accepted gap, C7/C9):** a Koinly `Cost` row displaying `0,00000000` vs
on-chain gas `0.0001` produces an amount-mismatch record with `zero_display=true`; the
cluster is dispositioned `acceptable_difference` once and stops blocking the gate
forever. Same for the fee-column enrichment (C9) and the 12 Koinly-dropped gas-only txs.

**Edge cases handled:** amounts at exactly the per-bucket tolerance boundary (pass) and
one unit beyond (fail); Koinly splitting one claim into up to 100 `Reward` rows
(tolerance scales with per-bucket row count: `1e-8 × max(1, rows_in_bucket)`);
zero-value native legs (excluded from swap partition, C1) vs zero-value *token* legs
(kept - negative test); gas-only txs unchanged (still `GasBurn`); missing dispositions
file (created with header); malformed TOML in the dispositions file (fail-loud with
path context, never silently ignored); harness run with no Berachain wallets registered
(fail-loud - nothing to validate); absent `bera_transactions.csv` (reuse the existing
WARNING + skip semantics from `maybe_substitute`).

## Evaluation Criteria

**Quality dimensions:**
- Correctness: hermetic pytest suite green, pinning the comparator (compatibility table,
  per-bucket tolerance incl. exact-boundary tests, gas-vs-Cost, zero-display), cluster
  signature determinism + PII-freeness, dispositions append-only semantics, the four
  exit-gate cases, and the C1/C3 classification rules (positive + negative).
- Maintainability: the harness contains no parsing logic of its own - it reuses
  `OnChainThSubstituter`'s projection pipeline (Task 1 extraction), `read_koinly_rows`,
  `_find_report_path`, and the merge's wallet-row matching idiom; comparator constants
  cite PD-010.
- Security/PII: committed files carry no personal tx hashes/wallet addresses (docs
  address-free by grep; test addresses synthetic or reused from `example/` registries);
  real hashes appear only inside gitignored `resources/result/<year>/` artifacts;
  signature strings proven address-free by unit test.
- Observability: run header (inputs, `snapshot_as_of_block`, RPC on/off, wallet labels,
  validation window), summary counts (shared / Koinly-only / on-chain-only / match / divergent; per-cluster
  dispositioned-vs-NEW), per-cluster sections with ≤5 side-by-side samples.

**Done when:**
- `uv run pytest` fully green (all new harness tests included; Koinly-byte-identical
  characterization tests for the non-opted-in path still green).
- The full harness flow (load → compare → cluster → dispositions → artifacts → exit
  code) is exercised hermetically in `tests/integration/test_on_chain_validation_integration.py`
  on synthetic `example/` inputs.
- C1 and C3 landed RED→GREEN with the negative tests; C2 compatibility entries landed;
  the walk-forward protocol executed (Task 11: H1 tune → freeze → full-year holdout
  run) with the generalization delta and C4/C5 outcomes recorded PII-free in this
  plan file.
- Docs updated (README, AGENTS.md constraint line, new maintenance doc, glossary/PD
  `.yaml`→`.toml` sweep); Validation Commands block passes.

**Ship when:**
- You run the harness on the real 2025 data and finalize dispositions in
  `resources/result/2025/on_chain_th_dispositions.toml` (agent proposes, you rule).
- Corrected premise (2026-08-18): no 2026 Koinly exports exist or can be taken (the
  subscription covers 2025 only), so there is no second validation dataset; for the
  2026 filing year the pipeline runs on-chain-only and its outputs carry the usual
  review flags (Unknown events, registry misses) instead of a Koinly cross-check.
- The real 2025 LP snapshot is populated from the Kodiak subgraph, or `ON_CHAIN_RPC_URL`
  is set in `config.ini` (network actions; procedure documented in the maintenance doc).
- Full-year zero-exit closing the walk-forward protocol (H1 tuned, frozen-rules
  full-year run dispositioned) → you flip `ON_CHAIN_TH_WALLETS` for the BERA wallet in
  `config.ini`. This plan does NOT flip any production flag.
- Moved from Task 11 checklist (2026-08-19, inclusion gate): the two `iterate until
  exit 0` items (H1 and full-year) complete only after you finalize the drafted
  dispositions above - agent iteration already reached the Invariant-8 boundary
  (25 unruled clusters; see Walk-forward outcomes). Re-run the H1 window and the
  full year after ruling; fix rules only where a mechanical gap is justified
  (post-freeze fixes each need an H2-shape citation).

## Review Scope

**Explicit must-fix**; findings on these paths are always in scope (review and fix if valid):

**Production code:**
- `src/tax_reporting/application/on_chain_validation/__init__.py` *(new)*
- `src/tax_reporting/application/on_chain_validation/comparator.py` *(new)*
- `src/tax_reporting/application/on_chain_validation/clustering.py` *(new)*
- `src/tax_reporting/application/on_chain_validation/dispositions.py` *(new)*
- `src/tax_reporting/application/on_chain_validation/artifacts.py` *(new)*
- `src/tax_reporting/application/on_chain_validation/runner.py` *(new)*
- `src/tax_reporting/application/on_chain_th_substitution.py` (Task 1 extraction only)
- `src/tax_reporting/infrastructure/on_chain/berachain_processor.py` (C1/C3 branches in
  `_classify_events`; all other methods frozen - reject findings touching them)
- `src/tax_reporting/application/on_chain_config.py` (self_wallet kind validation)
- `src/tax_reporting/domain/on_chain_config.py` (ContractEntry kind docstring)
- `src/tax_reporting/main.py` (arg + dispatch wiring only)
- `resources/source/example/2025/berachain_contracts.json` (self_wallet example entry)

**Tests:**
- `tests/unit/application/test_on_chain_validation_comparator.py` *(new)*
- `tests/unit/application/test_on_chain_validation_clustering.py` *(new)*
- `tests/unit/application/test_on_chain_validation_dispositions.py` *(new)*
- `tests/unit/application/test_on_chain_validation_artifacts.py` *(new)*
- `tests/unit/application/test_on_chain_validation_runner.py` *(new)*
- `tests/integration/test_on_chain_validation_integration.py` *(new)*
- `tests/unit/application/test_on_chain_th_substitution.py` (Task 1 extraction net)
- `tests/unit/application/test_on_chain_th_adapter.py` (Task 7 adapter confirmation)
- `tests/unit/infrastructure/test_berachain_processor.py` (C1/C3 cases)
- `tests/unit/application/test_on_chain_config_loader.py` (self_wallet kind)
- `tests/unit/domain/test_on_chain_config_domain_types.py` (kind-docstring pin)
- `tests/unit/test_cli.py` (validate flag)

**Documentation:**
- `README.md` (flag, exit codes, artifacts), `AGENTS.md` (Repository Constraints line),
- `docs/maintenance/on_chain_validation.md` *(new)*,
- `docs/maintenance/glossary.md` + `docs/maintenance/project-decisions.md` +
- `docs/history/backlog/2026-08-18-koinly-cancellation-program.md` (`.yaml`→`.toml` sweep).

**Plan-related extension**; implementation and review may change files not listed above.
Treat a finding as in scope when it is **causally related to this plan**: it implements
or completes a plan task, fixes a regression introduced by plan work, closes wiring or
docs implied by an explicit must-fix change, or contradicts a contract the plan changed.
If the link to the plan is weak or speculative, drop as out of scope with a one-line
reason.

**Out of scope; reject unless plan-related:**
- `src/tax_reporting/application/on_chain_th_adapter.py` - the adapter contract
  (`TH_CSV_COLUMNS`, `EVENT_TYPE_TO_KOINLY`, carrier-row gas rule, B5) is frozen; the
  compatibility table lives in the validation package, NOT in the adapter.
- `src/tax_reporting/application/crypto_reporting.py`, `run_report.py`,
  `src/tax_reporting/infrastructure/koinly_parser.py` - consumed as-is (UL #45).
- P2/P3/P4 concerns (price collector, rewards income, CG pipeline, three-file
  requirement relaxation) and the ERC-721 fetcher extension (C8).

## Design Invariants (CR Guard)

1. **Non-opted-in path byte-identical.** `ON_CHAIN_TH_WALLETS` stays unset in
   `config.ini` throughout this plan; the Koinly-byte-identical characterization tests
   (`tests/end_to_end/test_on_chain_koinly_characterization.py`,
   `tests/end_to_end/test_on_chain_bera_opted_in.py`) must remain green and unmodified
   in their expectations after every task. Task 1 is a pure extraction - the serializer
   input must be bit-identical pre/post (the characterization suite is the measuring
   instrument; it compares rendered TH bytes/cells).
2. **M1 fail-loud preserved.** The validation package introduces no `except Exception`
   broad handler; opted-in wallet parse errors propagate as `ReportGenerationError`.
   Malformed dispositions TOML raises with path context (specific exception type, not a
   silent skip) - the harness is a review instrument, silent passes are its failure mode.
3. **Adapter contract frozen.** No new Koinly vocabulary enters
   `EVENT_TYPE_TO_KOINLY` or `TH_CSV_COLUMNS` from this plan; the semantic-equivalence
   compatibility table is a validation-package constant citing PD-010.
4. **Production readers only (UL #45).** The Koinly TH side is read via
   `read_koinly_rows` + `_find_report_path(koinly_dir, "transaction_history", ".csv")`;
   the on-chain side via `read_on_chain_rows`. No `csv.DictReader` anywhere in the
   validation package.
5. **Hermeticity.** No test opens gitignored personal data: runner tests always inject
   `wallets`, and the default `load_on_chain_wallets` resolution is exercised only via
   `monkeypatch.setattr` at the CONSUMER module
   `tax_reporting.application.on_chain_validation.runner` (the repo patch-seam
   convention documented at `run_report.py:31` - patching the defining module is
   ineffective under from-import binding); all test files are named `test_on_chain_*`
   so the existing audit-hook probe
   (`tests/unit/test_on_chain_tests_no_personal_data.py`, glob at :92-103) covers them.
6. **PII.** Cluster signatures contain no addresses/hashes/dates/amounts (unit-tested);
   artifacts with real hashes are written only under `resources/result/<year>/`
   (`.gitignore:71`); committed docs are address-free; the real self-wallet address is
   written ONLY to the gitignored `resources/source/2025/berachain_contracts.json`.
7. **Exit-gate semantics (PD-010/backlog).** Non-zero (constant
   `EXIT_VALIDATION_INCOMPLETE = 3`) while any cluster lacks a disposition OR any
   fix-type (`missing_rule`/`incorrect_processing`) cluster still occurs; zero only when
   solely `acceptable_difference` clusters remain. All four cases unit-tested.
8. **Dispositions file is append-only; disposition values are user rulings.** The
   harness appends template blocks (dedup by signature across runs) and never rewrites
   or deletes existing entries. `disposition` values come only from user decisions: the
   agent may pre-fill them ONLY for clusters the user already ruled on in the
   2026-08-18 backlog session (C7/C9 `acceptable_difference`, C8 out-of-scope note,
   citing that confirmation); every NEW cluster's `disposition` stays empty until the
   user fills it. `root_cause`/`action` drafts are allowed anytime.
9. **Wallet set derivation does not flip production.** Validation wallets come from
   `chains.json` Berachain entries (or explicit injection), NOT from requiring
   `ON_CHAIN_TH_WALLETS` in `config.ini`; if `ON_CHAIN_TH_WALLETS` is already set it
   takes precedence.

## Validation Commands

```bash
uv run pytest
uv run pytest tests/unit/application/test_on_chain_validation_comparator.py \
  tests/unit/application/test_on_chain_validation_clustering.py \
  tests/unit/application/test_on_chain_validation_dispositions.py \
  tests/unit/application/test_on_chain_validation_artifacts.py \
  tests/unit/application/test_on_chain_validation_runner.py \
  tests/integration/test_on_chain_validation_integration.py -q
( cd "$(pwd)" && uv run tax-reporting --help ) | grep -q -- '--validate-on-chain-th' \
  || { echo 'VALIDATE FLAG MISSING FROM CLI'; exit 1; }
( cd "$(pwd)" && uv run tax-reporting --help ) | grep -q -- '--from' \
  || { echo 'WINDOW FLAG MISSING FROM CLI'; exit 1; }
if git grep -n 'on_chain_th_dispositions[.]yaml' -- 'docs/*.md' README.md AGENTS.md; then
  echo 'STALE .yaml DISPOSITIONS REFERENCE'; exit 1; fi
test -d src/tax_reporting/application/on_chain_validation \
  || { echo 'VALIDATION PACKAGE MISSING'; exit 1; }
if grep -rn 'csv.DictReader' src/tax_reporting/application/on_chain_validation/; then
  echo 'DICTREADER IN VALIDATION PACKAGE (UL #45)'; exit 1; fi
test -f docs/maintenance/on_chain_validation.md \
  || { echo 'MAINTENANCE DOC MISSING'; exit 1; }
if grep -rnE '0x[0-9a-fA-F]{16,}' docs/maintenance/on_chain_validation.md README.md \
  docs/history/plans/2026-08-18-on-chain-validation-harness.md; then
  echo 'ADDRESS-LIKE LITERAL IN COMMITTED PROSE'; exit 1; fi
uv run python -c 'from tax_reporting.application.on_chain_validation.runner import run_validation' \
  || { echo 'RUNNER IMPORT FAILED'; exit 1; }
```

The `.yaml` sweep is a contract-removal check for the format deviation; the literal is
bracket-escaped (`on_chain_th_dispositions[.]yaml`) so the gate cannot match this
plan file's own command text once tracked - do NOT "normalize" the escape back to a
plain dot, and do NOT sweep the plan file itself (its mentions are the checker literal
and the deviation note, not stale references). The `test -d` pre-check keeps the
DictReader guard fail-closed when the package directory does not exist yet. The 16+hex
sweep keeps committed prose address-free (public contract constants live in registry
JSON, not prose). Cross-check any `0x` + 40-hex literal in the branch diff against the
`resources/source/example/` registries and the BGT-distributor constant before commit
(PII pre-push recipe), but that check is a task step, not this block.

### Task 1: Extract the reusable projection pipeline + wallet-row matcher (refactor)

Files:
- `src/tax_reporting/application/on_chain_th_substitution.py`
- `tests/unit/application/test_on_chain_th_substitution.py`

Pure refactor; no behavior change. The measuring instruments are the existing suites
(they run GREEN before and after - characterization, not RED):

- [x] Run → expect GREEN (characterization: `uv run pytest tests/unit/application/test_on_chain_th_substitution.py tests/end_to_end/test_on_chain_bera_opted_in.py tests/end_to_end/test_on_chain_koinly_characterization.py`)
- [x] Extract from `OnChainThSubstituter.maybe_substitute` (`on_chain_th_substitution.py:170`) the pre-merge pipeline into a public method `build_projection(*, year: int, output_dir: Path, logger: logging.Logger, date_from: date | None = None, date_to: date | None = None) -> OnChainProjection | None` on the same class; `OnChainProjection` carries `transactions: list[OnChainTransaction]`, `projected_rows: list[ProjectedThRow]`, `registry: ContractRegistry`, `lp_snapshot: LpSnapshot`. It performs exactly today's steps :203-226 (bera-csv absence → WARNING + `None`; `_find_repository_root`; `_load_registries`; `_build_processor`; `read_on_chain_rows`; `processor.process`; `_audit`; `project_on_chain_transactions`), with ONE addition: when `date_from`/`date_to` is set, the raw rows are filtered to the inclusive date window (comparing `row.timestamp_utc.date()`, the reader's already-parsed `datetime` at `on_chain_csv_reader.py:166`) BEFORE `processor.process`, so the processor, integrity checks, and projection never see out-of-window txs. Defaults `None` keep the production path byte-identical. `maybe_substitute` becomes: call `build_projection` (no window), then the existing merge/reconciliation tail unchanged.
- [x] Extract the inline wallet-row match from `_merge_on_chain_into_koinly_th` (:478-492) into a module-level `is_wallet_row(row: dict[str, str], labels: set[str]) -> bool` (same `_norm_label` semantics on `Sending Wallet`/`Receiving Wallet`); the merge and the harness both call it. No import moves - collaborators stay imported from the same modules (symbol-move audit: grep `monkeypatch.setattr`/`unittest.mock.patch` sites touching `on_chain_th_substitution` internals; none may need retargeting since no symbol changes module).
- [x] `TestOnChainThSubstituter#test_build_projection_equivalent_to_direct_collaborator_chain`; given a bera CSV with ≥1 real claim-shaped row under the FULL 15-column header the reader's `OnChainTxRow` contract requires (`tx_hash, block_number, timestamp_utc, chain, from_address, to_address, asset, token_address, amount_raw, amount_decimals, direction, fee_asset, fee_amount_raw, wallet_label, wallet_address` - reuse the e2e `_bera_csv_rows` header shape at `tests/end_to_end/test_on_chain_bera_opted_in.py:114-118`; the 3-column `_make_bera_csv` header makes every data row warn-and-skip, so extending THAT header yields a vacuous `[] == []` pass) and `_EXAMPLE_2025_DIR` registries, expects `build_projection().transactions` equals `processor.process(read_on_chain_rows(csv))` and `.projected_rows` equals `project_on_chain_transactions(txs)` - pinning that the extraction dropped no step (the audit still runs in between); assert BOTH sides non-empty so a fixture that parses to zero rows fails loudly
- [x] `TestOnChainThSubstituter#test_build_projection_missing_bera_csv_returns_none`; given `output_dir/<year>/` without `bera_transactions.csv`, expects `None` + WARNING (same as today's early return)
- [x] `TestOnChainThSubstituter#test_build_projection_window_filters_inclusive`; given a bera CSV with claim rows on three dates (before `date_from`, exactly on `date_from`, exactly on `date_to`, after `date_to`), expects `build_projection(date_from=..., date_to=...)` processes ONLY the two boundary rows (inclusive both ends; boundary values tested exactly) and no window args keeps all rows
- [x] Run → expect GREEN (full suite)
- [x] Commit: `refactor(on-chain): extract build_projection + is_wallet_row for reuse`

### Task 2: Semantic-equivalence comparator (RED → GREEN)

Files:
- `src/tax_reporting/application/on_chain_validation/__init__.py` *(new)*
- `src/tax_reporting/application/on_chain_validation/comparator.py` *(new)*
- `tests/unit/application/test_on_chain_validation_comparator.py` *(new)*

Constants: `DISPLAY_TOLERANCE_PER_ROW = Decimal("0.00000001")`; per-`(tx_hash, asset,
direction)` bucket tolerance `= DISPLAY_TOLERANCE_PER_ROW * max(1, koinly_rows_in_bucket)`
(each Koinly row is rounded to 8 decimals; N rows accumulate < N×1e-8; on-chain side is
exact). Compatibility table `EVENT_COMPATIBILITY: dict[EventType, frozenset[tuple[str, str]]]`
per PD-010: `Swap→{(exchange,"")}`, `Reward→{(crypto_deposit,"Reward")}`,
`GasBurn→{(crypto_withdrawal,"Cost")}`, `LiquidityDeposit→{(transfer,"To pool")}`,
`LiquidityWithdraw→{(transfer,"From pool")}` (Type confirmed in Task 9 against the real
diff), `Transfer→{(transfer,"")}`, `Unknown→frozenset()` (always divergent). Gas surface:
Koinly = `Tag=="Cost"` rows' `Sent Amount` + all `Fee Amount`; on-chain = `GasBurn`
`sending_amount` + carrier `ProjectedFee` amounts; compared per currency with the same
bucket rule. Input: `compare_projection(koinly_rows: list[dict[str,str]], projected:
list[ProjectedThRow]) -> ComparisonResult` grouping both sides by `TxHash` / `tx_hash`.

- [x] `TestOnChainThComparator#test_equal_claim_matches`; given on-chain `Reward` BGT `12.345678901` + carrier fee `0.001` BERA and Koinly `Reward`×3 (BGT rows summing `12.34567890`) + `Cost` `0.001`, expects match with zero mismatch records
- [x] `TestOnChainThComparator#test_amount_within_display_tolerance_matches`; given diff `9e-9` in a 1-row bucket, expects match
- [x] `TestOnChainThComparator#test_amount_at_exact_tolerance_boundary`; given diff exactly `1e-8` (1-row bucket), expects match; given `1e-8 + 1e-15`, expects amount-mismatch record (both boundary sides pinned)
- [x] `TestOnChainThComparator#test_hundred_row_bucket_tolerance_scales`; given a bucket fed by 100 Koinly rows whose rounding error sums to `4.7e-7`, expects match (tolerance `1e-6`)
- [x] `TestOnChainThComparator#test_type_incompatible_records_mismatch`; given on-chain `Swap` vs Koinly `crypto_deposit/Reward` rows, expects a type-mismatch record carrying both combo sets
- [x] `TestOnChainThComparator#test_koinly_zero_display_cost_flagged`; given Koinly `Cost` `0,00000000` vs on-chain `GasBurn` `0.0001`, expects an amount-mismatch record with `zero_display=True`
- [x] `TestOnChainThComparator#test_hash_presence_partition`; given hashes present on one side only, expects `on_chain_only`/`koinly_only` records and NO comparison for them
- [x] `TestOnChainThComparator#test_fee_column_comparison`; given Koinly `Fee Amount` `0.002` vs on-chain carrier fee `0.002`, expects match; given empty Koinly fee vs on-chain `0.002`, expects a fee-surface mismatch record
- [x] Run → expect RED: `uv run pytest tests/unit/application/test_on_chain_validation_comparator.py`
- [x] Minimal implementation (no adapter changes; `parse_koinly_decimal` for amounts)
- [x] Run → expect GREEN
- [x] Commit: `feat(on-chain): semantic-equivalence comparator for TH validation`

### Task 3: Cluster signatures (RED → GREEN)

Files:
- `src/tax_reporting/application/on_chain_validation/clustering.py` *(new)*
- `tests/unit/application/test_on_chain_validation_clustering.py` *(new)*

Signature components (joined `k=v` with `|`, each multivalued component sorted, `|`
never inside a value): `events` (EventType names, sorted), `koinly` (`Type/Tag` combos,
sorted, e.g. `crypto_deposit/Reward+crypto_withdrawal/Cost`; `none` when
empty), `sender` ∈ {`reward_distributor`,`dex_router`,`rebate_router`,`self_wallet`,
`unregistered`,`null_or_empty`}, `lp` (bool: any leg touches an `LpSnapshot` token),
`fee` ∈ {`cost_rows`,`fee_column`,`none`,`mixed`} (Koinly rendering), `zero_display`
(bool). Sender class resolved via `ContractRegistry.get` on the tx counterparties (Koinly
side via `TxSrc`/`TxDest`); on-chain-only/Koinly-only clusters use the absent side's
`none`. API: `cluster_signature(record, *, registry, lp_snapshot) -> str` and
`group_into_clusters(result, *, registry, lp_snapshot) -> dict[str, list[record]]`.

- [x] `TestOnChainClusterSignature#test_signature_deterministic_under_reordering`; given the same tx with events/rows shuffled, expects the identical signature string
- [x] `TestOnChainClusterSignature#test_signature_pii_free`; given records containing real-shape hashes/addresses/amounts/dates, expects the signature matches `^((events|koinly|sender|lp|fee|zero_display)=[^|]*\|?)+$` and contains no `0x` substring and no 16+ hex run
- [x] `TestOnChainClusterSignature#test_components_discriminate`; given identical shapes differing ONLY in sender class (or lp flag, or fee surface), expects distinct signatures
- [x] `TestOnChainClusterSignature#test_on_chain_only_and_koinly_only_shapes`; given a `GasBurn`-only on-chain tx and a Koinly-only NFT-mint shape, expects signatures with `koinly=none` / `events=none` respectively
- [x] Run → expect RED: `uv run pytest tests/unit/application/test_on_chain_validation_clustering.py`
- [x] Minimal implementation
- [x] Run → expect GREEN
- [x] Commit: `feat(on-chain): PII-free cluster signatures for TH validation`

### Task 4: Dispositions file + exit gate (RED → GREEN)

Files:
- `src/tax_reporting/application/on_chain_validation/dispositions.py` *(new)*
- `tests/unit/application/test_on_chain_validation_dispositions.py` *(new)*

TOML shape (append-only; `tomllib` parse; template text appended in `"a"` mode):

```toml
[[clusters]]
signature = "events=GasBurn|koinly=none|sender=unregistered|lp=false|fee=none|zero_display=false"
first_seen = "2026-08-19"
disposition = ""      # missing_rule | incorrect_processing | acceptable_difference
root_cause = ""
action = ""
```

(The example is the C7 shape of a gas-only tx Koinly dropped entirely - `koinly=none`
pairs with `fee=none`, since the fee-surface class describes the Koinly rendering;
a shared-hash zero-display Cost row would read
`koinly=crypto_withdrawal/Cost|…|fee=cost_rows|zero_display=true`.)

API: `load_dispositions(path) -> list[DispositionEntry]` (empty `disposition` ⇒ NEW),
`append_new_clusters(path, signatures, today) -> list[str]` (creates file with header
comment when missing; skips signatures already present ANYWHERE in the file; never
rewrites), `evaluate_gate(clusters: dict[str, int], entries) -> GateResult` with
`EXIT_VALIDATION_INCOMPLETE = 3`.

- [x] `TestOnChainDispositions#test_missing_file_created_with_header`; given no file, expects creation with the explanatory header comment
- [x] `TestOnChainDispositions#test_new_signatures_appended_as_template`; given one NEW signature, expects an appended block with empty `disposition`/`root_cause`/`action`
- [x] `TestOnChainDispositions#test_append_only_preserves_existing_entries`; given a pre-filled entry, expects its full text byte-unchanged after an append run
- [x] `TestOnChainDispositions#test_no_duplicate_append_across_runs`; given the same NEW signature on two consecutive runs, expects exactly one block
- [x] `TestOnChainDispositions#test_gate_undispositioned_fails`; given an occurring cluster with no entry, expects fail (exit 3) with the signature named in the reason
- [x] `TestOnChainDispositions#test_gate_fix_type_still_occurring_fails`; given an occurring cluster dispositioned `missing_rule`, expects fail
- [x] `TestOnChainDispositions#test_gate_fix_type_absent_passes`; given a `missing_rule` entry whose cluster does NOT occur, expects pass (the fix-landed assertion)
- [x] `TestOnChainDispositions#test_gate_all_acceptable_passes`; given only `acceptable_difference` occurrences, expects pass
- [x] `TestOnChainDispositions#test_malformed_toml_fails_loud`; given unparseable TOML, expects `ValueError` chaining `tomllib.TOMLDecodeError` with the file path in the message, and no file modification
- [x] Run → expect RED: `uv run pytest tests/unit/application/test_on_chain_validation_dispositions.py`
- [x] Minimal implementation
- [x] Run → expect GREEN
- [x] Commit: `feat(on-chain): append-only dispositions file + validation exit gate`

### Task 5: Artifacts writers (RED → GREEN)

Files:
- `src/tax_reporting/application/on_chain_validation/artifacts.py` *(new)*
- `tests/unit/application/test_on_chain_validation_artifacts.py` *(new)*

- [x] `TestOnChainValidationArtifacts#test_markdown_report_structure`; given a finished comparison, expects run header (inputs, `snapshot_as_of_block`, RPC on/off, wallet labels, validation window: `--from/--to` dates or "full year"), summary counts (shared/Koinly-only/on-chain-only/match/divergent + per-cluster dispositioned-vs-NEW), one section per cluster with ≤5 side-by-side samples including amount diffs
- [x] `TestOnChainValidationArtifacts#test_diff_csv_one_row_per_divergent_tx`; given 3 divergent txs in 2 clusters, expects 3 CSV rows keyed by `tx_hash` with cluster signature + mismatch summary columns
- [x] `TestOnChainValidationArtifacts#test_artifacts_regenerated_not_appended`; given pre-existing artifact files, expects a rerun replaces their content (no concatenation)
- [x] `TestOnChainValidationArtifacts#test_real_hashes_allowed_only_under_result_dir`; given records with real hashes, expects artifacts written under `<output_dir>/<year>/` (tmp stand-in) and containing the hashes (gitignored surface - PII rule enforced by location, not omission)
- [x] Run → expect RED: `uv run pytest tests/unit/application/test_on_chain_validation_artifacts.py`
- [x] Minimal implementation
- [x] Run → expect GREEN
- [x] Commit: `feat(on-chain): validation markdown + diff CSV artifacts`

### Task 6: Runner + CLI wiring (RED → GREEN)

Files:
- `src/tax_reporting/application/on_chain_validation/runner.py` *(new)*
- `src/tax_reporting/main.py`
- `tests/unit/application/test_on_chain_validation_runner.py` *(new)*
- `tests/unit/test_cli.py`
- `tests/integration/test_on_chain_validation_integration.py` *(new)*

Runner: `run_validation(*, year, output_dir, koinly_dir=None, wallets=None,
rpc_url=None, date_from=None, date_to=None, logger) -> int`. Resolution order mirrors
production: Koinly dir via the
production discovery in `application/koinly_directory.py` unless injected; wallets from
`load_on_chain_wallets(year)` filtered to `chain == "Berachain"` unless injected
(`ON_CHAIN_TH_WALLETS` config takes precedence when set - runner never requires it);
projection via `OnChainThSubstituter(...).build_projection` (Task 1, window args
passed through); Koinly TH via
`_find_report_path` + `read_koinly_rows` filtered by `is_wallet_row` (Task 1) and, when
a window is set, by an inclusive date filter on `parse_koinly_datetime(row["Date"]).date()`
(same production parser; both sides must see the same window or the hash sets diverge);
then
compare → cluster → dispositions → artifacts → gate. CLI: add
`--validate-on-chain-th YEAR` (`type=int`) in `_build_arg_parser` (`main.py:28-66`) plus
`--from DATE` / `--to DATE` (ISO `YYYY-MM-DD`, inclusive); `_validate_args`
(`main.py:70`) rejects combining the validate path with `--example`/`--source-file`,
rejects `--from`/`--to` without `--validate-on-chain-th`, and rejects `--from > --to`;
`cli()` (`main.py:191`) dispatches to `run_validation` (imported into `main.py`) and
`sys.exit(status)` - the normal report path (`main`/`_main`) is untouched. Fail-loud
enumeration (clear error + exit 1, raised BEFORE any dispositions append so a
misconfigured run never writes feedback-loop state): no Berachain wallets resolved;
absent bera CSV (the Task-1 WARNING + explicit "nothing validated", never a silent 0);
Koinly side missing - `_resolve_koinly_directory` returns `None` for the year, or the
resolved dir has no `*transaction_history*.csv` (`_find_report_path` → `None`; both
return `None` rather than raising - the runner must convert). Any run for a year with
no Koinly export (permanent for 2026 onward; see the corrected premise in Ship when)
hits exactly this path.

- [x] `TestOnChainValidationRunner#test_match_case_exits_zero_and_writes_artifacts`; given synthetic example-registry inputs where projection ≡ Koinly, expects exit 0, both artifacts written, dispositions file created with header and no NEW blocks
- [x] `TestOnChainValidationRunner#test_divergent_case_exits_three_and_appends`; given one divergent cluster, expects exit 3, a NEW template block appended, diff CSV row present
- [x] `TestOnChainValidationRunner#test_wallets_default_resolution_patched`; given `monkeypatch.setattr` on `load_on_chain_wallets` at the CONSUMER module `tax_reporting.application.on_chain_validation.runner` (patch-seam comment mirroring `run_report.py:31`; patching the source module `tax_reporting.application.on_chain_config` is ineffective under from-import binding) returning synthetic Berachain + Ethereum wallets, expects only Berachain labels used (no gitignored file opened - audit-guard compatibility)
- [x] `TestOnChainValidationRunner#test_no_berachain_wallets_fails_loud`; given empty wallet resolution, expects a clear error and exit 1, not exit 0
- [x] `TestOnChainValidationRunner#test_missing_koinly_side_fails_loud_before_dispositions`; given EITHER missing-Koinly-side source - (a) `_resolve_koinly_directory` patched at the consumer module `tax_reporting.application.on_chain_validation.runner` to return `None` (the documented load_on_chain_wallets seam convention; any post-2025 run hits this first since no 2026 exports exist), or (b) a resolved dir with no `*transaction_history*.csv` (`_find_report_path` → `None`) - expects a clear error naming the missing input and exit 1, with the dispositions file NOT created or appended (parametrized over both cases)
- [x] `test_validate_flag_parsed` (module-level function, matching `tests/unit/test_cli.py`'s module-function convention at :20-131); given `--validate-on-chain-th 2025`, expects parse success and dispatch to the runner (patched at `tax_reporting.main.run_validation`, mirroring the existing `@patch("tax_reporting.main.main")` dispatch tests at :133-165)
- [x] `test_validate_flag_conflicts_rejected` (module-level function); given `--validate-on-chain-th 2025 --example`, expects `_validate_args` error (also with `--source-file`)
- [x] `test_window_flags_validation` (module-level function); given `--from`/`--to` WITHOUT `--validate-on-chain-th`, expects `_validate_args` error; given `--from 2025-07-01 --to 2025-01-01` (inverted), expects error; given `--from 2025-01-01 --to 2025-06-30` with the validate flag, expects parse success with the two `date` values bound
- [x] `TestOnChainValidationRunner#test_window_filters_both_sides_equally`; given synthetic inputs with one tx inside and one outside the window on BOTH the on-chain and Koinly sides, expects the out-of-window tx appears NOWHERE in the comparison result (not even as an on-chain-only/koinly-only record - both sides filtered to the same inclusive window), and the artifacts' run header records the window
- [x] `TestOnChainValidationIntegration#test_end_to_end_hermetic_flow`; given tmp Koinly dir + synthesized `bera_transactions.csv` + `example/` registries with one matching and one divergent tx, expects the full chain load→compare→cluster→dispositions→artifacts→exit 3, and a second run after dispositioning `acceptable_difference` expects exit 0
- [x] Run → expect RED: `uv run pytest tests/unit/application/test_on_chain_validation_runner.py tests/unit/test_cli.py tests/integration/test_on_chain_validation_integration.py`
- [x] Minimal implementation (composition-root discipline: runner takes collaborators as parameters; `main.py` owns config/env reads and passes `rpc_url` from `load_configuration_from_file()`)
- [x] Run → expect GREEN (full suite)
- [x] Commit: `feat(on-chain): --validate-on-chain-th command wiring the harness end to end`

### Task 7: C1 - exclude zero-value native gas-carrier legs from the swap partition (RED → GREEN)

Files:
- `src/tax_reporting/infrastructure/on_chain/berachain_processor.py`
- `tests/unit/infrastructure/test_berachain_processor.py`
- `tests/unit/application/test_on_chain_th_adapter.py` (adapter-level confirmation bullet)

Rule (design record Q6, never implemented): a zero-value NATIVE (chain gas-asset)
outflow leg is the gas carrier; actual gas is already lifted to the parent tx
(`_lift_gas`, :521). Such legs are excluded from the in/out leg partition inside
`_classify_events` (:236; partition at :261-262, generic swap at :295-297,
`_split_reward_then_swap` at :335-373). The exclusion applies ONLY where an economic
leg remains: carriers are dropped from the swap/reward partition, from the
Event-construction leg lists of branches 3-5 (branch 5 builds its Swap from the FULL
`legs` list at :297 - that argument must receive the carrier-filtered legs, not just
the partition predicates), and from `_split_reward_then_swap`'s swap legs. The GAS_ONLY
branch (:267-268) keeps the UNFILTERED out-leg - a gas-only tx's single leg IS the
carrier shape, and `_gasburn_event(tx_hash, out_legs)` must not receive an empty list
(the adapter's `addr_leg` at `on_chain_th_adapter.py:228-230` would render blank
TxSrc/TxDest). Consequence: distributor/vault claims (in-leg
reward asset + 0-value native out) fall through to the pure-inflow reward branch -
branch 3, `if in_legs and not out_legs` at :281-282, which groups per asset into
`Reward` events (branch 7 at :301 is unreachable as written: branch 3 already consumes
every pure-inflow shape). Zero-value TOKEN legs are NOT excluded (narrow rule).

- [x] `TestBerachainProcessor#test_distributor_claim_with_zero_value_gas_carrier_classifies_reward`; given a BGT in-leg from the registered distributor + native out-leg `0.00000000` (tx gas nonzero), expects a single `Reward` event (staking), not `Swap` - RED today (generic swap branch swallows it)
- [x] `TestBerachainProcessor#test_swap_with_zero_value_native_leg_excludes_carrier`; given real in/out legs plus a 0-value native leg, expects `Swap` whose legs exclude the carrier leg
- [x] `TestBerachainProcessor#test_gas_only_still_gasburn`; given a single zero-value native leg, expects `GasBurn` unchanged INCLUDING its leg payload - assert the Event still carries the out-leg (or the projected row keeps a non-empty TxSrc), so an over-broad exclusion that empties `_gasburn_event`'s legs fails loudly (regression guard on :267)
- [x] `TestBerachainProcessor#test_zero_value_token_leg_not_excluded`; given a swap carrying a 0-value TOKEN leg, expects the leg remains in the partition (negative - narrow rule)
- [x] `TestBerachainProcessor#test_reward_then_swap_split_respects_carrier_exclusion`; given a claim+swap tx (distributor in-leg + router swap legs + 0-value native out), expects `Reward` + `Swap` events with the carrier leg in neither partition (C4's suspected shape - this is the multi-Event split case)
- [x] Audit existing processor tests for fixtures that pinned the PRE-fix `Swap` classification of claim-with-carrier shapes; update those assertions citing design record Q6 (do not delete coverage)
- [x] Adapter-level confirmation: existing `test_on_chain_th_adapter` projection for `Reward` events covers `crypto_deposit/Reward` rendering; extend with one case asserting the claim-with-carrier tx projects to exactly one Reward row with carrier fee set
- [x] Run → expect RED: `uv run pytest tests/unit/infrastructure/test_berachain_processor.py`
- [x] Minimal implementation in `_classify_events` (+ `_split_reward_then_swap` if the split path needs the same exclusion)
- [x] Run → expect GREEN (full suite - characterization must stay green)
- [x] Commit: `fix(on-chain): reward claims misrouted to Swap by gas-carrier leg (C1)`

### Task 8: C3 - `self_wallet` registry kind → `Transfer` (RED → GREEN)

Files:
- `src/tax_reporting/application/on_chain_config.py` (`_CONTRACT_KINDS` tuple :566 + kind validation :624)
- `src/tax_reporting/domain/on_chain_config.py` (`ContractEntry` docstring :108-132)
- `src/tax_reporting/infrastructure/on_chain/berachain_processor.py`
- `resources/source/example/2025/berachain_contracts.json`
- `tests/unit/application/test_on_chain_config_loader.py`
- `tests/unit/domain/test_on_chain_config_domain_types.py` (kind-docstring pin)
- `tests/unit/infrastructure/test_berachain_processor.py`

Add `self_wallet` to the contract kinds - the tuple `_CONTRACT_KINDS` lives at
`application/on_chain_config.py:566` (validation at :624); update the `ContractEntry`
docstring reference at `domain/on_chain_config.py:108-132`. Processor rule in
`_classify_events`, TWO dispatch points (verified against the current dispatch order):
(a) BEFORE branch 3 (`:281`, `if in_legs and not out_legs` - it consumes every
pure-inflow shape, so a check placed later never sees inbound self-transfers): a pure
inflow whose single counterparty sender (resolved from the rows' from-addresses, the
same idiom `_is_reward_distributor` uses at :472) is registered `kind=self_wallet` →
`Transfer` with `SubType.internal_transfer` (member already exists,
`domain/on_chain_transaction.py:95-112`); (b) BEFORE the Unknown fallback (:308-315): a
pure outflow whose single recipient is registered `kind=self_wallet` → `Transfer`
(today such txs fall to `Event(Unknown)` + review).

- [x] `TestContractRegistryLoader#test_self_wallet_kind_accepted`; given a contracts JSON with a `self_wallet` entry, expects it loads and `ContractRegistry.get` reports the kind
- [x] `TestContractRegistryLoader#test_unknown_kind_still_rejected`; given kind `"banana"`, expects the existing rejection error unchanged (negative)
- [x] `TestContractRegistryLoader#test_kinds_tuple_includes_self_wallet`; given the updated `_CONTRACT_KINDS` (`application/on_chain_config.py:566`), expects `self_wallet` present alongside the original three (the domain `ContractEntry` docstring at `domain/on_chain_config.py:108-132` lists it too)
- [x] `TestOnChainConfigDomainTypes#test_contract_entry_docstring_lists_self_wallet`; given the updated `ContractEntry` docstring (`domain/on_chain_config.py:108-132`), expects `self_wallet` listed among the kinds (doc-drift pin; keeps the file's RED-gate presence honest)
- [x] `TestBerachainProcessor#test_inbound_from_registered_self_wallet_classifies_transfer`; given 1 BERA in-leg from a registered self-wallet address, expects `Transfer`/`internal_transfer`, not `Reward` - RED today (branch 3 at :281 consumes the shape as `Reward`)
- [x] `TestBerachainProcessor#test_outbound_to_registered_self_wallet_classifies_transfer`; given 1 BERA out-leg to a registered self-wallet, expects `Transfer`/`internal_transfer`, not `Unknown` - RED today (pure outflow falls to the Unknown fallback at :308-315)
- [x] `TestBerachainProcessor#test_self_wallet_check_precedes_reward_branch`; given a self-wallet inbound tx that would ALSO satisfy the branch-3 pure-inflow reward shape, expects `Transfer` (ordering pin vs `:281`)
- [x] `TestBerachainProcessor#test_unregistered_sender_still_reward_spam`; given the same shape from an unregistered address, expects `Reward` (spam subtype) unchanged (negative - behavior preserved)
- [x] Add a synthetic `self_wallet` entry (obviously-fake address, e.g. `0x…2222` style) to `resources/source/example/2025/berachain_contracts.json`
- [x] Local-data step (guard: writes ONLY the gitignored `resources/source/2025/berachain_contracts.json`; nothing committed): register the real second self-wallet `0xf89d7b9c…` (full address read from the real 2025 Koinly TH / `chains.json` locally) as `self_wallet`
- [x] Update the `_classify_events` dispatch-order docstring (`:241-253`) and the `# noqa: PLR0911` "one return per shape" comment for the branches Tasks 7-8 add - the docstring already mis-describes dead branch 7 at `:301`; the C1/C3 edits are the moment to make it truthful (AGENTS.md: update prose on change)
- [x] Run → expect RED: `uv run pytest tests/unit/application/test_on_chain_config_loader.py tests/unit/infrastructure/test_berachain_processor.py tests/unit/domain/test_on_chain_config_domain_types.py`
- [x] Minimal implementation
- [x] Run → expect GREEN (full suite)
- [x] Commit: `feat(on-chain): self_wallet registry kind classifies self-transfers as Transfer (C3)`

### Task 9: C2 - LP compatibility pins + enablement path (GREEN pins + investigation)

Files:
- `src/tax_reporting/application/on_chain_validation/comparator.py`
- `tests/unit/application/test_on_chain_validation_comparator.py`
- `tests/unit/infrastructure/test_berachain_processor.py`
- `docs/maintenance/on_chain_validation.md` *(new; shared with Task 10)*

The compatibility entries themselves ship in Task 2's table; these tests are GREEN pins
of the real-data Koinly vocabulary (they fail only if someone narrows the table), plus
the execution-time investigation that may WIDEN it.

- [x] `TestOnChainThComparator#test_liquidity_deposit_matches_koinly_to_pool`; given on-chain `LiquidityDeposit` legs and Koinly `(transfer, "To pool")` rows, expects a type match (pin - entry landed in Task 2)
- [x] `TestOnChainThComparator#test_liquidity_withdraw_matches_koinly_from_pool`; given on-chain `LiquidityWithdraw` and Koinly `(transfer, "From pool")`, expects a type match (pin - widen ONLY the `LiquidityWithdraw` set if the investigation below finds Koinly's real Type differs)
- [x] Investigation checklist (execution-time, real data, read-only): run the harness on 2025 and read one `To pool`/`From pool` row's `Type`/`Tag` cells from `on_chain_th_validation_diff.csv`; if Koinly's `From pool` rows carry `crypto_withdrawal` rather than `transfer`, widen ONLY the `LiquidityWithdraw` compatibility set with a second pair and record the observed combo in this plan file (PII-free: Type/Tag values only) - outcome 2026-08-18: H1 run confirmed Koinly renders both pool tags with `Type=transfer` (119 From-pool / 195 To-pool rows in the real TH; no other Type carries a pool tag), so no widening applied
- [x] `TestBerachainProcessor#test_lp_stake_with_snapshot_entry_classifies_liquidity_deposit`; given an in-memory snapshot entry (existing `_lp_snapshot` helper, :114) and a Kodiak-router stake shape, expects `LiquidityDeposit` - if an existing test already pins this, cite it here instead of duplicating (existing `TestBerachainProcessor#test_lp_deposit` cited at the pin site)
- [x] Document the two enablement paths in the maintenance doc (Task 10): populate `resources/source/<year>/berachain_lp_snapshot.json` from the Kodiak subgraph (query recipe + `snapshot_as_of_block`/`snapshot_as_of_date` fields), or set `ON_CHAIN_RPC_URL` (https-only, `config.py:327-352`) for the bytecode fallback; the run header records which is active
- [x] Run → expect GREEN (`uv run pytest tests/unit/application/test_on_chain_validation_comparator.py tests/unit/infrastructure/test_berachain_processor.py`)
- [x] Commit: `feat(on-chain): LP pool-tag compatibility entries + enablement docs (C2)`

### Task 10: Documentation sweep + `.yaml`→`.toml` reconciliation (non-behavior)

Files:
- `README.md`
- `AGENTS.md`
- `docs/maintenance/on_chain_validation.md` *(new)*
- `docs/maintenance/glossary.md`
- `docs/maintenance/project-decisions.md`
- `docs/history/backlog/2026-08-18-koinly-cancellation-program.md`

- [x] `README.md`: document `--validate-on-chain-th <year>` (usage, read-only guarantee, exit codes 0/1/3, artifact paths under `resources/result/<year>/`, wallet derivation from `chains.json`, precedence of `ON_CHAIN_TH_WALLETS`); point to the maintenance doc; no time-bounded content
- [x] `AGENTS.md` Repository Constraints: one line - the validation harness is a user-run command writing only gitignored artifacts; the dispositions file is append-only and user-owned; gate semantics per PD-010
- [x] Create `docs/maintenance/on_chain_validation.md`: harness workflow, disposition vocabulary and feedback loop, cluster-signature components, PII rules (signatures PII-free; artifacts gitignored), the C2 enablement paths from Task 9, and the acceptance gate (zero-exit on the 2025 dataset - the only Koinly baseline that will ever exist - → flip `ON_CHAIN_TH_WALLETS`)
- [x] Sweep stale `.yaml` references for the dispositions artifact across TRACKED files (`git grep -n 'on_chain_th_dispositions' -- 'docs/*.md' README.md AGENTS.md`) and update every `.yaml` mention to `.toml` - verified carriers: glossary *Dispositions file* (`glossary.md:52`, "YAML feedback loop" + the `.yaml` path) and the backlog P1 artifact list; PD-010 has no `.yaml` mention (verified 2026-08-18). Untracked `docs/tmp/` buffers and gitignored `docs/history/reviews/` quote the string legitimately (deviation discussion) and are out of the sweep by construction (`git grep` sees tracked content only)
- [x] Commit: `docs: on-chain TH validation harness usage + dispositions toml reconciliation`

### Task 11: Real-data walk-forward validation + C4/C5 triage (execution-time verification)

Files:
- `docs/history/plans/2026-08-18-on-chain-validation-harness.md` (this file - record outcomes)
- `resources/result/2025/on_chain_th_validation.md` (gitignored output; not committed)

Walk-forward protocol (PD-010): tune on H1, FREEZE, then ONE full-year run measures
generalization. Honest caveat, stated up front: the 2026-08-18 full-year cross-tab
already informed the C1-C5 taxonomy, so the holdout measures IMPLEMENTATION
generalization (do the landed rules and registry entries generalize mechanically) and
new-signature discovery, not designer innocence.

**Phase 1 - tune on H1:**

- [x] Choose the window boundary (default 2025-07-01; adjust so each half keeps a workable share of the ~424 shared txs) and record it in this file's task notes
- [x] Run `uv run tax-reporting --validate-on-chain-th 2025 --from 2025-01-01 --to <boundary>` locally (real personal data; outputs land only under gitignored `resources/result/2025/`)
- [x] Record the H1 cluster table in this file's task notes: signature → count → status (dispositioned/NEW), PII-free (no hashes/addresses; counts and signatures only); also record the H1 signature SET (the holdout baseline)
- [x] Expected in H1: the C1 cluster (~110 txs overall) and C3 cluster (10 txs overall) no longer occur; C6 unchanged (matching); C7/C9 occur and take `acceptable_difference`; C8's Koinly-only NFT-mint clusters occur (PD-010 known-baseline gap) and take `acceptable_difference` with the ERC-721 out-of-scope note in `root_cause`, citing the 2026-08-18 backlog ruling; C2 shrinks only after the real snapshot/RPC enablement (Ship-when)
- [x] Triage C4 (3 txs) and C5 (~30 txs) shapes that appear in H1 from the diff CSV: for each shape, either implement the missing rule (RED→GREEN, same discipline as Tasks 7-8) or draft a disposition block (`missing_rule`/`incorrect_processing`/`acceptable_difference` + proposed root_cause/action) for the user to finalize - per PD-010 the CLUSTER is the unit; do not create per-tx entries
- [x] Pre-fill dispositions into `resources/result/2025/on_chain_th_dispositions.toml` ONLY for clusters the user already ruled on in the 2026-08-18 backlog session (C7 zero-display + the 12 dropped gas-only txs → `acceptable_difference`; C9 fee-column → `acceptable_difference`; C8 NFT mints → `acceptable_difference` with the ERC-721 out-of-scope note in `root_cause`), citing that confirmation in `root_cause`; draft `root_cause`/`action` freely for the rest, but leave every NEW cluster's `disposition` empty for the user (Invariant 8)

**Phase 2 - freeze + full-year holdout run:**

- [x] FREEZE: no edits to processor rules, registries, compatibility table, or tolerance constants after this point until the Phase-2 run is recorded
- [x] Run `uv run tax-reporting --validate-on-chain-th 2025` (full year) ONCE with everything frozen
- [x] Record the generalization delta in this file's task notes: cluster signatures present in the full-year run but NOT in the H1 signature set (expected families: mid-year contract launches surfacing as `sender=unregistered` clusters, unseen Koinly Type/Tag renderings for known EventTypes), each with count and PII-free shape description
- [x] Triage the delta: each NEW signature is either a missing rule (fix it, RED→GREEN, citing which H2 shape it generalizes) or a new `acceptable_difference` disposition for the user to rule on

**Phase 3 - full-year gate:**

- [x] PII backstop before commit: cross-check every `0x`+40-hex literal in `git diff master` against the `resources/source/example/` registries and the BGT-distributor public constant; any unmatched literal is a stop-and-fix
- [x] Commit (plan-file outcome notes only): `docs(on-chain): record 2025 walk-forward validation outcomes`

## Walk-forward outcomes (2026-08-19)

Task 11 execution record (PII-free: signatures, counts, and Type/Tag vocabularies only).
Honest caveat per PD-010: the 2026-08-18 full-year cross-tab informed the C1-C5 taxonomy, so the
holdout below measures implementation generalization and new-signature discovery, not designer
innocence.

### Boundary and protocol

- **H1 window**: `2025-01-01 .. 2025-07-01` inclusive (plan default; zero txs are dated exactly on
  the boundary day, so the hash counts equal the Task-9 `06-30` window - the boundary choice is
  immaterial to the split: 270 shared hashes in H1 vs 424 full-year).
- **Phase-1 tuning edits** (comparator only, RED -> GREEN, 9 new tests in
  `tests/unit/application/test_on_chain_validation_comparator.py`; full suite 2206 green; the
  processor, registries, adapter, config, and tolerance constants were never touched in Task 11):
  1. Ticker-case folding of asset buckets (explorer `iBGT` vs Koinly `IBGT` - same token, one
     bucket; likewise iBERA, stBGT, USDC.e, uniBTC, brBTC, yBGT/yBERA, and the `Bault-`/`BAULT-`
     and `KODI`-prefixed LP tokens).
  2. Mirrored-row single counting (Koinly wallet-pair/pool-pair echo rendering: one movement shown
     on BOTH sides of a row - same currency, equal amounts - counts once, on the direction(s) the
     on-chain projection carries; both sides when it carries neither, so unmatched movements stay
     surfaced).
  3. Gas-folded native amount (Koinly renders no gas surface at all and displays the native OUT
     amount inclusive of the gas: equivalence requires an EXACT identity - Koinly minus on-chain
     equals the on-chain gas within the bucket tolerance - and an empty Koinly gas surface for the
     currency; both the event and the gas mismatch are then explained).
  4. Compatibility widening (real-data renderings with exact amount agreement): `Reward` also
     accepts `crypto_deposit/""` (untagged reward deposits); `Swap` also accepts the untyped
     `crypto_deposit/""` + `crypto_withdrawal/""` row pair.
- **H1 effect**: matched 136 -> 187 of 270 shared; divergent 134 -> 83; clusters 28 -> 22.

### H1 cluster table (post-tuning; the holdout baseline)

| # | signature (abbreviated: events \| koinly \| sender \| fee) | count | status |
|---|---|---|---|
| 1 | `Unknown \| Cost+transfer/To pool \| unregistered \| cost_rows` | 21 | NEW (C2 draft) |
| 2 | `Swap \| crypto_withdrawal/Cost+exchange/ \| unregistered \| cost_rows` | 8 | NEW (multi-leg draft) |
| 3 | `Swap \| exchange/ \| unregistered \| none` | 8 | NEW (multi-leg draft) |
| 4 | `Transfer \| transfer/ \| self_wallet \| fee_column` | 7 | NEW (Koinly fee-estimate draft) |
| 5 | `Reward \| crypto_withdrawal/Cost+transfer/From pool \| unregistered \| cost_rows` | 5 | NEW (C2 draft) |
| 6 | `Swap \| crypto_deposit/+crypto_withdrawal/+Cost \| unregistered \| cost_rows` | 5 | NEW (multi-leg draft) |
| 7 | `Unknown \| exchange/ \| unregistered \| fee_column` | 5 | NEW (Unknown+quirks draft) |
| 8 | `GasBurn \| none \| unregistered \| none` | 4 | **dispositioned** acceptable_difference (C7, user-ruled 2026-08-18) |
| 9 | `Reward \| exchange/ \| unregistered \| none` | 3 | NEW (C4 draft; see C4 resolution below) |
| 10 | `Unknown \| crypto_withdrawal/+Cost \| unregistered \| cost_rows` | 3 | NEW (C2 draft) |
| 11 | `Unknown \| Cost+exchange/ \| unregistered \| cost_rows` | 3 | NEW (Unknown+quirks draft) |
| 12 | `Unknown \| crypto_withdrawal/Cost \| unregistered \| cost_rows` | 3 | NEW (multi-leg draft) |
| 13 | `Reward \| crypto_withdrawal/Cost \| unregistered \| cost_rows` | 2 | NEW (Koinly-dropped-row draft) |
| 14 | `Reward \| transfer/ \| unregistered \| fee_column` | 2 | NEW (classification+fee-estimate draft) |
| 15 | `Swap \| Cost+transfer/From pool \| unregistered \| cost_rows` | 2 | NEW (C2 draft) |
| 16 | `Unknown \| exchange/ \| unregistered \| none` | 2 | NEW (Unknown+quirks draft) |
| 17 | `none \| crypto_deposit/ \| unregistered \| none` | 2 | **dispositioned** acceptable_difference (C8, user-ruled 2026-08-18; ERC-721 out of scope) |
| 18 | `Reward \| none \| unregistered \| none` | 1 | NEW (spam-airdrop draft; distinct from C7) |
| 19 | `Swap \| crypto_deposit/+Cost+exchange/ \| unregistered \| cost_rows` | 1 | NEW (multi-leg draft) |
| 20 | `Swap \| crypto_deposit/Reward+Cost+exchange/ \| unregistered \| cost_rows` | 1 | NEW (multi-leg draft) |
| 21 | `Swap \| crypto_deposit/Reward+Cost+transfer/To pool \| unregistered \| cost_rows` | 1 | NEW (C2+multi-leg draft) |
| 22 | `Swap \| crypto_deposit/Reward+exchange/ \| unregistered \| none` | 1 | NEW (multi-leg draft) |

The H1 signature SET for the holdout comparison is these 22 strings in full (as recorded in the H1
`on_chain_th_validation.md`). Six fully-collapsed pre-tuning clusters stopped occurring in the
post-tuning H1 window (the pure ticker-case and untagged-rendering families); only THREE of them
stayed non-occurring through the full-year run - their TOML blocks remain among the 30 as the
3 legacy non-occurring blocks, disposition empty, and do not block the gate (only occurring
clusters gate). The other three resurfaced full-year with new sub-shapes (e.g. the
`Reward | crypto_deposit/Reward+Cost` glyph-alias family in the delta table below) or folded into
still-occurring signatures, so they left no non-occurring block. (Counts corrected 2026-08-20,
review r1 F19: verified against the TOML - 30 blocks = 2 filled + 25 drafted occurring + 3
non-occurring.)

### Freeze point

After the Phase-1 tuning and the one hand-edit pass on the dispositions TOML (C7/C8 pre-fills +
drafts; dispositions left empty everywhere else per Invariant 8). Working tree at freeze: branch
commit `87eb876` plus UNCOMMITTED edits to exactly two files -
`src/tax_reporting/application/on_chain_validation/comparator.py` and its test. No
processor/registry/adapter/compat-table/tolerance edits after the tuning landed.

### Phase 2 - full-year holdout run (frozen, run ONCE)

`uv run tax-reporting --validate-on-chain-th 2025` -> exit 3 (gate incomplete: unruled clusters).
424 shared / 298 matched / 126 divergent / 13 on-chain-only (12 C7 gas-only + 1 spam airdrop) /
2 Koinly-only (C8) / 27 clusters (2 dispositioned, 25 NEW).

**Generalization delta** (signatures occurring full-year but NOT in the H1 set) - 5 signatures,
all triaged to drafts (no new mechanical rule justified):

| signature | count | H2 shape |
|---|---|---|
| `Reward \| crypto_deposit/Reward+Cost \| unregistered \| cost_rows` | 5 | H2 reward claims with non-case residuals: 2 txs carry the Koinly ticker alias `USD(unicode glyph)0` vs the explorer `USDT0` (glyph alias needs a user-approved alias entry, not a mechanical rule); the rest are Koinly-side legs the projection does not carry (multi-leg family). This signature's H1 population collapsed via ticker-case folding; H2 resurfaced it with new sub-shapes. |
| `Swap \| crypto_deposit/+crypto_withdrawal/ \| unregistered \| none` | 1 | Untyped swap pair plus a Koinly-only native inbound leg (internal-transfer receive; fetcher pulls txlist+tokentx only). |
| `Swap \| crypto_deposit/+exchange/ \| unregistered \| none` | 1 | Koinly reward-shaped deposit row plus the swap row (multi-leg family). |
| `Swap \| exchange/ \| unregistered \| fee_column` | 2 | Koinly-only LP-token legs (multi-leg) plus one bucket where the exported Koinly amount differs at the seventh decimal on a ~500-unit amount (Koinly-side precision beyond the 8-decimal display tolerance; a tolerance-constant change would need a user ruling). |
| `Unknown \| crypto_withdrawal/ \| unregistered \| none` | 1 | C2 family: LP-token send-without-receive rendered by Koinly as an untyped withdrawal row. |

### Phase 3 - full-year gate state

Exit 0 is NOT reachable with Invariant 8 respected: 25 NEW (undispositioned) clusters remain.
Per the Task-11 execution boundary that is the designed handoff - the Ship-when items own the
resolution. No Phase-3 code fixes landed (none of the delta shapes generalizes to a mechanical
rule; see triage above). The frozen full-year run above is the recorded final state.

**Residual user-owned blockers (by family):** the four families partition the 25 NEW clusters
exactly (6 + 8 + 4 + 7 = 25) and their occurrence records sum to 127 (43 + 47 + 14 + 23),
matching the report's cluster table. Counts are occurrence RECORDS (divergent + one-sided), not
divergent txs only; recomputed from the report 2026-08-20, review r1 F19 (the originally
recorded 24 clusters / 91 records dropped the internal-receive cluster and understated three
families).

- **C2 LP enablement** (Ship-when: populate the real LP snapshot or set `ON_CHAIN_RPC_URL`):
  6 clusters / 43 occurrence records (the To/From-pool, untagged-withdrawal, and
  `crypto_withdrawal/+Cost` shapes).
- **Adapter multi-leg rendering** (out of this plan's scope - frozen adapter contract; a FUTURE
  plan must render one projected row per Event leg-pair): 8 clusters / 47 records. Production-relevant
  finding: 63 H1 events (more in H2) carry more than one leg in a direction; the projection
  renders only the FIRST leg per direction, so those amounts are absent from the projected TH -
  this lossiness equally affects the production substitution path, not just validation.
- **Unknown-fallback families** (sends-without-receives + Koinly internal-receive legs and
  Koinly-only staking-position tokens): 4 clusters / 14 records.
- **Koinly-side quirks** (estimated fee values, dropped reward rows, ticker glyph alias, one
  precision row, the C4 mirrored-exchange spam rewards, the un-ruled spam-airdrop on-chain-only
  tx): 7 clusters / 23 records.

**C4 resolution (data trace):** the three `Reward vs exchange` txs are NOT claim+swap splits.
They are pure inflows from unregistered senders (on-chain `Reward`, spam subtype + review per F4)
that Koinly renders as MIRRORED exchange rows (same asset both sides, equal amounts). After the
mirrored-row rule the amounts agree; only the type disagrees - drafted for the user.

**C5 resolution:** the residual mixed `Swap` shapes (backlog C5: `Swap` vs
`crypto_deposit/''`+withdrawal combos, ~30 txs estimated) are the adapter multi-leg rendering
family above - they did NOT collapse once C1-C3 landed (8 clusters / 47 occurrence records
full-year; ~27 H1 records against the cross-tab's ~30 estimate) because the root cause is the
frozen adapter contract rendering only the FIRST leg per direction: the projection-side amounts
are simply absent, which no classifier rule can repair. Drafted for the user; a FUTURE plan must
render one projected row per Event leg-pair (the same conclusion the residual-families list
records). (Outcome note added 2026-08-20, review r1 F20 overflow: the Done-when C5 half of
Task 11 was previously unauditable in this record.)

**C9 note:** no pure C9 (fee-column enrichment) cluster occurs in either window. The
empty-Koinly-gas-surface shapes either satisfy the exact gas-fold identity (absorbed as matches)
or sit inside multi-cause clusters needing their own rulings; the C9 ruling stays recorded in the
backlog and the dispositions TOML carries no C9 entry (nothing to pre-fill).

**Dispositions TOML state:** 30 blocks - 2 filled (`acceptable_difference`, C7 + C8, citing the
2026-08-18 backlog ruling; C8 root_cause carries the ERC-721 out-of-scope note), 25 drafted with
`disposition = ""` (agent proposals ride inline comments only), 3 legacy non-occurring blocks
untouched.

**PII backstop on `git diff master`:** every `0x`+40-hex literal in the diff is either the public
BGT-distributor constant, present in the `resources/source/example/` registries, or an
obviously-synthetic test fixture (`...b222`, `...abcd`, `...0001` in test files only). PASS.

**Tests:** `uv run pytest` -> 2206 passed (baseline 2197 + 9 new comparator rule tests);
characterization suites green and unmodified.

## Execution notes

- Ship-when items (user-owned): real 2025 dispositions finalized; real LP snapshot
  populated / `ON_CHAIN_RPC_URL` set; `ON_CHAIN_TH_WALLETS` flipped only after the
  full-year zero-exit that closes the walk-forward protocol (Task 11 Phase 3; no 2026
  Koinly exports exist or can be taken - corrected premise 2026-08-18).
- The Koinly TH wallet-row filter and projection reuse mean the harness sees EXACTLY what
  the production substitution would merge - no parallel parsing path can drift.
