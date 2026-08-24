# Project Decisions

Architecture and reporting decisions for this repository. Law-driven decisions are sourced per fiscal year in `docs/maintenance/tax/decision_points/`; this file records the stable engineering and reporting choices that do not change year to year.

## PD-001: Layered architecture

Domain-driven layering: `domain` -> `application` -> `infrastructure` -> `presentation`. Orchestration layers stay thin (about 500 lines); domain logic lives in dedicated services. See `README.md` for the full walkthrough.

## PD-002: FIFO per-wallet per-institution (CIRS art. 43 n.9)

Cost basis is matched first-in-first-out scoped per wallet and per institution, not globally. Engine lives in `crypto_fifo/`. Cross-asset FIFO carry-over matches by Transaction History identifier, never by day-level date alone.

## PD-003: Loan repayment gains excluded for PT

When `exclude_loan_repayment_gains=True`, loan-affected assets are excluded from Koinly CG parsing and rebuilt from Transaction History. Loan-affected assets are discovered from `"loan"` / `"loan repayment"` tags only (not `"loan fee"`).

## PD-004: Derivatives separated from spot

Derivatives/futures are split from spot into their own pipeline with an explicit OGR-vs-CG dedup step, then aggregated by `(disposal_date, asset, platform, holding_period)`. PT derivatives route to Anexo G Quadro 13, operation code G51.

## PD-005: Materiality and review gating

Post-aggregation, entries with `|gain/loss| < 1 EUR` are excluded. Zero-basis disposals are flagged for review only above `ZERO_BASIS_REVIEW_MIN_PROCEEDS` (default 10 EUR) and `ZERO_BASIS_REVIEW_THRESHOLD` (default 50). Partially-matched sells are never silently dropped; the placeholder-buy mechanism applies to the remaining quantity.

## PD-006: Optional crypto ingestion is non-blocking

Missing, mismatched-year, or unparseable Koinly input emits a warning and continues IB report generation without crypto data.

## PD-007: Law-driven flags in decision points TOML, not config.ini

`config.ini` holds only user preferences; law-driven flags (e.g. `exclude_loan_repayment_gains`) live in `docs/maintenance/tax/decision_points/<fiscal_year>.toml`, mirrored in the `.md` sidecar. A missing TOML for the configured `FISCAL_YEAR` fails fast at startup.

## PD-008: Per-lot review reasons re-evaluated at the aggregation boundary

Capital-gains entries are aggregated by `(disposal_date, asset, platform, holding_period)` before the user-visible row is rendered (Quadro 9.4 reports the disposal event, not the FIFO lot allocation; PT-C-025, PT-C-027). A single noisy zero-basis lot inside a material disposal must not poison the aggregated row's `Review flag`. Implementation: `_re_evaluate_aggregated_review()` in `application/crypto/aggregation.py` runs after `_aggregate_capital_entries()`. Gate (all three): `cost_eur > 0 AND proceeds_eur > 0 AND abs(gain_loss_eur) >= _MATERIALITY_THRESHOLD` (1 EUR). When the gate holds, the joined `review_reason` is split on `"; "`, zero-basis-family prefixes (`_ZERO_BASIS_REASON_PREFIXES`) are dropped, and the flag becomes `NO` if no parts survive. The more-severe "Zero acquisition cost with negative disposal proceeds" reason is NOT stripped (its prefix differs) because it flags a distinct fee-heavy liquidation / data anomaly whose guidance must survive aggregation.

Per-lot signal is preserved in `context.review_entries` and the per-lot DEBUG log (file handler at `DEBUG`; Bucket-C (DEVELOPER_ACTIONABLE class, pattern O) silent-data-loss aggregates stay WARNING on the console, while EXTRACT_SURFACED dedup/origin aggregates emit at INFO with their per-row detail surfaced in the extract per rule #7), and surfaced as Section 5 REVIEW REQUIRED on the Crypto Supplementary sheet; the re-evaluation only re-derives the user-visible aggregated row's flag and reason.

**Trade-off.** A maintainer seeing `review_reason` dropped at aggregation time might assume a bug and re-add the join; this PD is the record that the drop is deliberate. **Evidence (2026-07-21, 2025 export):** every aggregated disposal row correctly resolved to `Review flag = NO`, including the reward-derived rows whose non-zero aggregated cost confirmed the per-lot zero-basis noise was suppressed without losing the underlying signal (which remains on the Supplementary sheet). Specific portfolio figures are omitted here as personal data; see the underlying plan records for traceability. Plan of record: `docs/history/plans/completed/2026-07-15-review-flag-aggregation-boundary.md`.

## PD-009: Full Koinly cancellation for TY2026 (Koinly = one-time validation teacher)

Decided 2026-08-18 (`grill-with-docs` session; corrected same day). Koinly is fully cancelled for the 2026 tax-year filing: after the transition it is never read again, and it is NOT a runtime dependency of the on-chain path. During the transition only, Koinly exports serve as a one-time *validation baseline* (teacher): the 2025 historical export set - the ONLY baseline that will ever exist, because the subscription covers 2025 only and no 2026-YTD export set can be taken (user correction 2026-08-18) - is diffed against the on-chain projection by the validation harness until every discrepancy cluster is dispositioned.

Scope premise: 2026 crypto activity is Berachain-only; the ~28 legacy Koinly wallets (Wirex, ByBit, Kraken, SUI, …) are dormant for 2026 and need no new ingestion. Prior-year cost basis reaches 2026 disposals through the existing FIFO rollover state.

Consequence: the pipeline's current hard three-file Koinly requirement (`load_koinly_crypto_report`: `capital_gains_report` + `income_report` + `transaction_history`) must be replaced piecewise before cancellation: rewards income from on-chain Reward events (PD-011 supplies EUR pricing), capital gains computed pipeline-side (`crypto_fifo` as the sole engine), TH substituted via the existing `ON_CHAIN_TH_WALLETS` path. Roadmap of record: `docs/history/backlog/2026-08-18-koinly-cancellation-program.md`.

**Trade-off.** Cancelling removes Koinly's aggregation for 28 wallets and its price/Cost-basis columns; anything missed by the on-chain parser has no second source to catch it. Accepted because 2026 activity is Berachain-only and the harness's acceptance gate (zero unexplained clusters on the 2025 baseline - the only one that will exist) plus a Koinly-free TY2025 dry-run diff against the filed numbers precede the switch. 2026 itself has no Koinly cross-check by construction; that residual risk is carried by the integrity/freshness audits, Unknown-event review flags, and the disposition discipline's fail-loud exit gate. A maintainer seeing `load_koinly_crypto_report`'s three-file requirement relaxed should not "fix" it back - the relaxation is the point of this PD.

## PD-010: Validation-harness semantics - semantic equivalence, cluster-level resolution

Decided 2026-08-18. The on-chain-vs-Koinly comparison passes when, per shared `tx_hash`: (1) net amounts per `(asset, direction)` match within the baseline's display tolerance (Koinly truncates to 8 decimals), and (2) the on-chain `EventType` maps to the baseline `Type`/`Tag` via the fixed compatibility table (Reward↔`crypto_deposit/Reward`, Swap↔`exchange`, GasBurn↔`crypto_withdrawal/Cost`, LiquidityDeposit↔`transfer/To pool`, LiquidityWithdraw↔`transfer/From pool`, Transfer↔`transfer`; the 2025-H1 walk-forward tuning additionally accepts the untagged `crypto_deposit/""` rendering for `Reward` and the untyped `crypto_deposit/""` + `crypto_withdrawal/""` pair for `Swap`, and the 2026-08-22 amendment accepts `exchange` and the same untyped pair for `LiquidityDeposit`/`LiquidityWithdraw` - detailed rules in `on_chain_validation.md`). Row cardinality is irrelevant: Koinly's per-asset reward splits (up to 100 `Reward` rows for one claim) and its To-pool rows rendered as sent==received same-asset transfers are display artifacts, and downstream correlation already keys on `(tx_hash, event_id)` - reproducing them would copy Koinly quirks into the on-chain model.

Divergences are resolved at the **cluster** level only: each cluster (a group of txs sharing one divergence shape) is dispositioned as a *new rule* (classifier/heuristic gap → fix), an *updated rule* (existing rule too narrow/broad → fix), or *accepted as normal* (a documented known-baseline gap: gas-only txs dropped by Koinly - 12/139 in 2025; `Cost` rows displaying `0,00000000` for sub-8-decimal gas - 41 rows; Fee column left empty - Koinly carries gas as separate Cost rows instead; spam/NFT mints not imported). There is deliberately **no per-transaction override ledger**: a one-off ruling that cannot generalize into a rule means the rule set is not done.

**Trade-off.** Cluster-level resolution forces every ambiguity to become either code or a documented pattern (no escape hatch per tx), which is slower for genuine one-offs but leaves no hidden per-tx state that silently exempts future data.

**Amendment (walk-forward acceptance protocol, 2026-08-18).** Tuning the rules and then judging them on the same transactions is circular, so the 2025 baseline is validated walk-forward: (1) tune on an H1 date window (`--from/--to`, both sides filtered) until the H1 run exits 0; (2) freeze rules, registries, and the compatibility table; (3) ONE full-year run with everything frozen - cluster signatures absent from the H1 run's signature set are the generalization delta (expected: mid-year contract launches, unseen Koinly renderings), and each delta signature is either a missing rule or a new user disposition; (4) the flip gate (`ON_CHAIN_TH_WALLETS`) is the full-year zero-exit. Honest scope: the 2026-08-18 full-year cross-tab already informed the cluster taxonomy, so the holdout measures implementation generalization and new-signature discovery, not designer innocence - the alternative (no holdout) measures neither.

**Amendment (LP-rendering vocabulary, 2026-08-22, user-approved).** The freeze above presupposed the LP snapshot was populated before tuning; it was not (the 2025-H1 tuning ran with the synthetic placeholder, so pool txs classified as `Swap` and matched via Swap↔`exchange`, hiding C2). After the snapshot's real population (20 subgraph/RPC-derived tokens), pool operations classify correctly as `LiquidityDeposit`/`LiquidityWithdraw`, and the frozen entries (which only accepted the user's manual `transfer/To pool` / `From pool` marks) caused 13 previously-"matching" txs to diverge on type. The amendment widens those two entries to also accept `exchange` and the untyped `crypto_deposit/""` + `crypto_withdrawal/""` pair - the renderings Koinly auto-produces for pool operations because it has no native liquidity Type. Amount comparison is untouched, so the widening converts blanket cluster acceptances into per-transaction amount-verified matches (strictly more validation). `crypto_deposit/Reward` is deliberately NOT accepted for liquidity events: mixed deposit+claim txs stay surfaced until the classifier decides whether to emit a separate Reward event.

**Amendment (issuer ticker aliases + disposition authority, 2026-08-22, user-delegated).** Two relaxations delegated by the user the same day, both recorded for audit: (1) the comparator's asset-bucket normalization folds issuer-declared ticker aliases to the issuer's declared standard - two shapes qualify with per-contract evidence: Unicode-glyph vs ASCII (`USD₮0` -> `USDT0`; the contract's own `symbol()` carries the glyph, Koinly and exchanges use ASCII, and per-tx amounts match exactly once merged) and issuer rename (`HONEY` -> `BUSD`, added 2026-08-22 after the Etherscan fetcher's metadata refreshed mid-August 2026: contract `0xfcbd14dc...` now declares `BUSD`/`"Bera USD"` per on-chain `eth_call` while Koinly still renders the pre-rename `HONEY`; the address is unique in the 2025 dataset and per-tx amounts are equal once merged) - chain-agnostic, extended only with per-contract evidence of the same shape; (2) evidence-decisive cluster dispositions may be recorded by the agent (marked `agent-decided` in the dispositions file) instead of waiting for a user ruling - user rulings remain required for genuine judgment calls (tax treatment choices, ambiguity the data cannot resolve), and every agent-decided entry carries its evidence in `root_cause` with the standing backstop that the P4 dry-run comparison (our pipeline vs the Koinly-derived report) reopens any decision it contradicts.

## PD-011: EUR pricing via a network-gated price collector, not in-pipeline pricing

Decided 2026-08-18. Post-Koinly, EUR prices come from a *price collector* following the existing on-chain-fetcher pattern: an opt-in, network-gated collector writes a gitignored per-year cache of `(date, asset) → EUR` for assets appearing in Reward events and disposals; a manual override file fills gaps; unpriceable rewards fall to the existing zero-value review/skip path. The pipeline itself stays offline and reads only the cache file. One source serves both consumers: rewards income (market value at receipt - replaces Koinly's `Value (EUR)`) and disposal-time valuation for pipeline-side capital gains. Note: the 2026-08-01 design record's claim that an `ExchangeRateService` "already exists" was verified false on 2026-08-18 - only the IB fiat `[EXCHANGE RATES]` INI exists; this PD is the first crypto EUR pricing decision.

**Trade-off.** Collector + override adds a manual step and a cache file to maintain versus Koinly's turnkey pricing, but keeps the pipeline hermetic and offline (matching the suite's no-network guarantee) and keeps price provenance auditable for the filing.
