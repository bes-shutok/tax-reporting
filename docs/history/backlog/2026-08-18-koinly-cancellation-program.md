# Backlog: Koinly full-cancellation program for TY2026 (validate on-chain parsing, then replace all Koinly inputs)

Status: active program. P1 landed 2026-08-21 (followups closed 2026-08-22, review-residue slice
executed 2026-08-24); P2 is next; promote each phase via the `plans` skill when scheduled.
Workflow: when the program's final phase (P4) completes, move this file to
`docs/history/backlog/completed/`.

Source: `grill-with-docs` session 2026-08-18. Decisions are recorded in
`docs/maintenance/project-decisions.md` (PD-009, PD-010, PD-011); new glossary terms:
*Validation baseline*, *Discrepancy cluster*, *Semantic equivalence*, *Price collector*
(the *Gas-only tx* entry was also corrected against real data). This file holds the
program details, the verified data baseline, and the roadmap; P1 is the first slice to
promote to a plan.

## Goal

Cancel Koinly entirely for the 2026 tax-year filing. The on-chain Berachain parser
(landed behind `ON_CHAIN_TH_WALLETS`, plan `2026-08-02-on-chain-tx-tagger`) becomes the
sole crypto movement source; rewards income and capital gains stop coming from Koinly
reports; EUR pricing comes from a new price collector. Koinly's only remaining role is
one-time validation teacher: the 2025 historical export set - the ONLY Koinly baseline
that will ever exist (corrected 2026-08-18: the subscription covers 2025 only, so no
2026-YTD export set can be taken; 2026 runs on-chain-only with no Koinly cross-check by
construction) - is diffed against the on-chain projection until every discrepancy
cluster is dispositioned (PD-009, PD-010).

Scope premise (user-confirmed): 2026 crypto activity is **Berachain-only**. The ~28
legacy Koinly wallets (Wirex 1429 TH rows, ByBit 1062, Kraken 881, SUI 630, Binance 572,
…) are dormant for 2026; prior-year cost basis reaches any 2026 disposal through the
existing FIFO rollover state. No new ingestion is built for them.

## Verified data baseline (2026-08-18, real 2025 data; scratch analysis, production readers only)

Snapshot at P1 intake; items superseded since are recorded in the P1 status paragraph (e.g. the
LP snapshot allowlist landed 2026-08-22).

Machinery state:

- The substitution pipeline is fully wired (`application/on_chain_th_substitution.py`)
  but the flag has never been flipped in production: `config.ini` contains no
  `ON_CHAIN_*` keys.
- `resources/source/2025/berachain_lp_snapshot.json` still holds the SYNTHETIC
  placeholder addresses (`0x…dead`, `0x…beef`, `0x…1234`): the real Kodiak-subgraph
  allowlist was never populated. With `ON_CHAIN_RPC_URL` unset, LP classification is
  snapshot-only, i.e. effectively empty.
- `resources/source/2025/berachain_contracts.json` contains only the BGT Distributor
  (public contract, `0xd2f19a79b026fb636a7c300bf5947df113940761`); no self-wallet or
  vault entries.

Overlap (437 on-chain txs vs 426 Koinly BERA-wallet hashes; 4,937 legs; 4,887 Koinly
BERA-wallet rows):

| Slice | Count | Notes |
|---|---|---|
| Shared hashes | 424 | only 191 have equal row cardinality (Koinly splits multi-token claims into up to 100 `Reward` rows + 1 `Cost` row) |
| Koinly-only hashes | 2 | ERC-721 mints (`BERA777#378`, `BERA777#572`, null sender); fetcher pulls only `txlist`+`tokentx` (no NFT/internal actions) |
| On-chain-only hashes | 13 | 12 gas-only + 1 spam airdrop (`WWW.BERA777.XYZ`), as designed |

On-chain Event distribution on real data: 233 Swap / 139 GasBurn / 48 Unknown / 17
Reward - zero LiquidityDeposit/LiquidityWithdraw/Transfer events.

Koinly rendering facts that drive the harness tolerance rules:

- Gas is carried as separate `crypto_withdrawal/Cost` rows (`Sent Amount` = gas), not
  in the Fee column; only 34 BERA-wallet rows use the Fee column at all (24 `exchange`,
  10 `transfer`).
- 352 Cost rows total; 41 display `Sent = 0,00000000 BERA` (gas below the 8-decimal
  display floor) - the "empty orders where only fees are spent" pattern.
- Koinly amounts are truncated/rounded to 8 decimals; separators are European.

## Known discrepancy clusters (input to P1; counts from the shared-hash cross-tab)

Disposition vocabulary per PD-010: *new rule* / *updated rule* / *accepted as normal*.

| # | Shape | Count | Working disposition |
|---|---|---|---|
| C1 | Reward claims → on-chain `Swap` vs Koinly `Reward`×N + `Cost` (includes plain claims FROM the registered BGT Distributor; e.g. 2025-xx in-leg BGT + out 0-value BERA gas leg) | ~110 txs (58× "Reward×1+Cost", 35× "Reward×100+Cost", plus singles) | **New/updated rule**: exclude the zero-value native gas-carrier leg from the swap partition so distributor/vault claims classify as `Reward` (design record Q6 said this; not implemented or not effective) |
| C2 | LP stake/unstake → on-chain `Unknown`/`Swap` vs Koinly `To pool`/`From pool` + `Cost` (e.g. 50WBTC-50WBERA-WEIGHTED via the Kodiak router) | ~44 txs (26 Unknown↔To pool, 8 Unknown↔exchange, 10 Swap↔From pool) | **Registry refresh (DONE 2026-08-22)**: real LP snapshot populated from the Kodiak subgraph; `ON_CHAIN_RPC_URL` bytecode fallback remains optional |
| C3 | Self-wallet transfers → on-chain `Reward`/spam vs Koinly `transfer` (e.g. 2025-02-25 1 BERA inbound from second own wallet `0xf89d7b9c…`) | 10 txs | **New rule/registry kind**: register self-custody wallet addresses as self-wallets → `Transfer` (SubType `internal_transfer`), not Reward |
| C4 | `Reward` vs Koinly `exchange` disagreements | 3 txs | Investigate individually in P1; likely claim+swap in one tx needing multi-Event split |
| C5 | Residual mixed shapes (`Swap` vs `crypto_deposit/''`+withdrawal combos) | ~30 txs | Investigate in P1; expect most to collapse once C1-C3 land |
| C6 | Gas-only agreement: 127 GasBurn↔`Cost` 1:1 | 127 | Matches; no action |
| C7 | Koinly drops 12 gas-only txs; 41 Cost rows show `0,00000000` | 12 + 41 rows | **Accepted as normal** (baseline gap rules) |
| C8 | ERC-721 mints Koinly-only (`BERA777#…`) | 2 | **Out of scope** (spam NFT mints, zero economic value) unless real NFT activity appears; do NOT extend the fetcher for this |
| C9 | Fee column: on-chain carrier-row rule fills `Fee Amount` where Koinly leaves it empty | ~all gassed txs | **Accepted as normal** (deliberate enrichment; GasBurn exception prevents double-count, B5) |

## Roadmap (each phase its own plan; promote in order)

### P1 - Validation harness + parser/registry fixes (promote first)

**Status: LANDED 2026-08-21**, followups closed 2026-08-22, review-residue slice executed 2026-08-24.
All of it lives on master as a single squash commit on top of `dece8c1` (the branch ref was deleted,
so intermediate branch SHAs such as the original P1 landing commit no longer resolve). P1 plan
archived at `docs/history/plans/completed/2026-08-18-on-chain-validation-harness.md` (execute-plan
code review r1: 16 findings fixed, r2: blocking-clean). The harness (`--validate-on-chain-th`) ran the
full walk-forward protocol on the real 2025 baseline: H1 tuned (comparator rules landed), frozen
full-year holdout recorded; C1/C3 fixed, C2 pins landed. Followups 2026-08-22: LP snapshot populated
from the Kodiak subgraph (C2 registry refresh done), Etherscan fetch workstream closed
(boundary-block drain; HONEY->BUSD issuer-rename fold). The review residue (shape-6 LP/LST withdraw
classification, validation-CLI crash exit code 2, `bera_csv_path` consolidation) became its own plan,
executed 2026-08-24 after six blocking-clean review rounds:
`docs/history/plans/completed/2026-08-23-bera-unknown-followups.md` (backlog archived at
`docs/history/backlog/completed/2026-08-23-bera-unknown-followups.md`). The flip gate stays open per
Ship-when: exit 3 is now held only by the multi-row rendering gap, the nfttx (ERC-721) fetch gap, and
one undispositioned Swap residual.

- Committed, user-runnable validation command (e.g. `uv run tax-reporting --validate-on-chain-th <year>`)
  that runs the production path (registry load → reader → processor → integrity/freshness audit →
  adapter projection) on REAL personal data (real Koinly TH, real `bera_transactions.csv`, real
  registries - deliberate: synthetic fixtures test known rules only; real data reveals
  unknown-unknowns). Read-only over inputs: no merge, no pipeline writes.
- Comparator applies the semantic-equivalence rules (PD-010 compatibility table +
  per-`(asset, direction)` amount comparison with the 8-decimal display tolerance +
  gas-vs-Cost-row comparison) and clusters divergences by PII-free semantic signature
  (event combo + Koinly Type/Tag combo + sender-registration class + LP-involvement +
  fee-surface class; never tx hashes or wallet addresses).
- Three artifacts, all under gitignored `resources/result/<year>/` (already excluded by
  `.gitignore:71` `resources/result/*`):
  - `on_chain_th_validation.md` (regenerated): run header (inputs, snapshot block, RPC on/off),
    summary (shared/Koinly-only/on-chain-only/match counts, per-cluster counts with
    dispositioned-vs-NEW status), per-cluster sections with ~5 side-by-side samples and
    amount diffs;
  - `on_chain_th_validation_diff.csv` (regenerated): one row per divergent tx for full
    drill-down/filtering;
  - `on_chain_th_dispositions.toml` (append-only; the FEEDBACK LOOP): harness appends a
    template block per NEW cluster signature; the user fills `disposition`
    (`missing_rule` | `incorrect_processing` | `acceptable_difference` - mapping to PD-010's
    new rule / fix-widen rule / accepted-as-normal), `root_cause`, `action`.
- Exit-code gate: non-zero while any cluster lacks a disposition OR any fix-type
  (`missing_rule`/`incorrect_processing`) cluster still occurs - a fix-type disposition
  asserts the cluster vanishes once its fix lands. Zero exit = dataset done (only
  `acceptable_difference` clusters remain).
- Must call production readers only (UL #45); no new parsing logic outside the processor.
- Hermetic pytest coverage pins the diff/cluster/signature logic on synthetic `example/`
  fixtures.
- Fix clusters C1-C5 (processor rules + registry kinds); refresh
  `resources/source/2025/berachain_lp_snapshot.json` from the Kodiak subgraph; register the
  second self-wallet.
- Validation dataset: the 2025 Koinly export set ONLY (corrected 2026-08-18: the
  subscription covers 2025 only; no 2026-YTD export set can be taken, so there is no
  second baseline - 2026 runs on-chain-only and relies on the integrity/freshness
  audits, Unknown-event review flags, and the P4 dry-run instead of a Koinly
  cross-check).
- Walk-forward protocol (added 2026-08-18, PD-010 amendment): the harness takes a
  `--from/--to` date window; tune on H1 to zero-exit, FREEZE rules/registries/compat
  table, then ONE full-year frozen run whose NEW cluster signatures (absent from the
  H1 signature set) measure generalization to unseen activity; the flip gate is the
  subsequent full-year zero-exit.
- **Acceptance gate**: zero-exit on the 2025 dataset → flip `ON_CHAIN_TH_WALLETS`
  for the BERA wallet in `config.ini`.

### P2 - Price collector + rewards income from on-chain

- Price collector per PD-011 (opt-in, network-gated; gitignored `(date, asset) → EUR` cache +
  manual override file; unpriceable → existing zero-value review/skip path).
- Rewards income derived from on-chain `Reward` events (replaces `_parse_income_file`):
  CRG-001/002 classification, operator-origin resolution (Berachain chain-level VG per B3),
  existing `aggregate_taxable_rewards()` + IRS-table aggregation stay the consumers.
- Read `docs/maintenance/crypto_rules.md` + `decision_points/` before touching classification.

### P3 - Capital gains fully pipeline-side

- `crypto_fifo` becomes the sole CG engine over the (on-chain) TH; the Koinly CG report parse
  and the OGR override path are retired for on-chain-sourced years.
- Disposal-time EUR valuation via the P2 price source; rollover state carries prior-year basis.

### P4 - Koinly-free dry run + cancellation

- Re-run TY2025 end-to-end with zero Koinly inputs; diff every output against the filed 2025
  numbers (the strongest acceptance test available).
- Relax `load_koinly_crypto_report`'s three-file hard requirement (on-chain-only mode).
- Cancel the subscription; run TY2026 for real.

## Open confirmations (session tail, default-accepted unless overridden)

1. Validation artifact: CONFIRMED 2026-08-18 with the feedback-loop refinement - real personal
   data in, gitignored artifacts out (`on_chain_th_validation.md` + `_diff.csv` regenerated,
   `on_chain_th_dispositions.toml` append-only for user root-cause feedback); details in the
   P1 section.
2. Flip gate = zero unexplained clusters on the 2025 dataset (CORRECTED 2026-08-18: the
   subscription covers 2025 only, so no 2026-YTD export exists; 2025 is the sole baseline).
3. Cluster priority order C1 → C2 → C3 → C4/C5.
4. Roadmap order P1 → P2 → P3 → P4; P4 dry run precedes cancellation.
5. NFT/ERC-721 transfers out of scope (C8).

## Constraints / guards

- **PII**: no full personal tx hashes or wallet addresses in committed docs or tests (history
  was purged 2026-08-16); the validation report with real hashes writes only to gitignored
  `resources/result/`. Public contract addresses are fine.
- Hermeticity: tests never read gitignored personal data; the harness itself is a user-run
  command, not a pytest.
- Fail-loud M1 contract (opted-in wallet parse errors propagate as `ReportGenerationError`)
  is preserved; the harness must not introduce a broad `except Exception`.
- Koinly-byte-identical characterization invariants for the NON-opted-in path stay green
  throughout P1 (flag stays off in production until the gate passes).
- The price collector must not make the pipeline network-dependent at runtime (opt-in
  collector + cache file, same pattern as `BERA_CHAIN_API_KEY`).
- PD-003/PD-004/PD-005 semantics (loan exclusion, derivatives split, materiality) carry over
  unchanged to the on-chain-sourced years; P3 must re-verify each against `crypto_fifo`-sourced
  entries.
