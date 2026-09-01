# Backlog: On-chain review-loop follow-ups (2026-08-26)

Three candidates deferred with record during the review loop on branch
`2026-08-25-nfttx-wire-action-fix` (rounds r1-r5; staging docs in gitignored
`docs/history/reviews/2026-08-26-branch-review-2026-08-25-nfttx-wire-acti*.md`).
Each was a valid, non-blocking finding whose fix was judged larger than the
round warranted; none blocks the `ON_CHAIN_TH_WALLETS` flip. Promote each as
its own plan (or fold into P2/P4 planning) when taken.

NOTE (review r2 overflow, 2026-08-28): this doc is ARCHIVED, but items 4
(fetcher CSV atomic write) and 5 (staleness-suite structural residuals)
REMAIN OPEN - they were never promoted. The umbrella backlog
(`docs/history/backlog/2026-08-18-koinly-cancellation-program.md`, P2
follow-up candidates section) carries the open pointers so active-backlog
scans still see them.

## 1. Staleness handling: hard refusal + in-artifact indicator (PROMOTED)

**Status (2026-08-27): promoted** to plan
`docs/history/plans/completed/2026-08-26-on-chain-staleness-refusal.md` (landed:
retry-then-refuse contract). The in-artifact indicator half stays a P2
candidate; all three items are now promoted (2026-08-28), so this doc is
archived under `docs/history/backlog/completed/`.

- **Discovered**: review r1 F6 (risk; stale-CSV failure mode), extended r2 F5
  (risk; artifact-side indicator) and hardened through r3-r5 (empty-config
  marker, TOCTOU guard, unrecognized-type raise).
- **Current state (landed)**: a failed or skipped on-chain refresh writes
  `bera_transactions.csv.fetch-failed` next to the CSV; on the next opted-in
  run the retry ladder (`on_chain_retry.retry_stale_on_chain_fetch`, threaded
  through `run_report`) re-fetches automatically with exponential backoff
  (six attempts over 63 s of backoff sleep plus transfer time) and, if every
  attempt fails (or no fetch callable is wired), the run is REFUSED with a
  `ReportGenerationError` (fail-loud, mirroring M1). A later successful fetch
  self-heals (the CSV is rewritten newer); deleting the marker is the
  documented manual clear (see `docs/maintenance/on_chain_validation.md`
  "Fetch-failure staleness marker").
- **Why deferred**: the collection fetch is deliberately non-blocking (DI-1)
  and pre-flip the substituted TH is not yet consumed by report generation.
  The refusal half of the original sketch is now LANDED (above); what remains
  open is the in-artifact indicator half only: it needs a home on the report
  surfaces (review_reason plumbing exists for Events, but staleness is
  projection-wide, not per-Event).
- **Plan sketch (remaining half)**: attach a projection-level review
  indicator that reaches the Excel review surfaces (Crypto Reconciliation /
  Platform Assumptions) naming the stale window, for the cases where the
  marker was manually cleared and the run proceeded on stale data for review
  only.
- **Acceptance**: a run whose on-chain refresh failed cannot produce output a
  user can mistake for complete (refusal, or a visible in-artifact flag).

## 2. Comparator module extraction (module-size rule)

**Status (2026-08-28): landed** via plan
`docs/history/plans/completed/2026-08-26-comparator-combo-extraction.md` (branch
`2026-08-27-comparator-combo-extraction`).

- **Discovered**: review r2 overflow (design; god-module) - the branch pushed
  `on_chain_validation/comparator.py` past the repo's 1000-line module-size
  rule (~990 on master at branch point; ~1023 after).
- **Why deferred**: mostly pre-existing size; a pure mechanical extraction
  mid-loop would churn the import seams the collision tests monkeypatch
  right at the exit-candidate rounds. Risk/benefit said: separate commit.
- **Plan sketch**: extract the combo-vocabulary block (the
  `EVENT_TYPE_TO_KOINLY` re-derivations, `_build_reverse_combo_map`,
  `_KOINLY_COMBO_TO_EVENT_TYPE`, `_event_type_of`, `_row_combo`) into a small
  `koinly_combo_map` module next to the adapter it reads; keep the
  module-attribute reads (test-patch visibility, documented in the builder);
  move/extend the collision + vocabulary-pin tests accordingly.
- **Acceptance**: comparator.py back under the rule; the injectivity guards
  and their tests unchanged in behavior.

## 3. Bridge-asset registry gate (spam airdrop vs trusted bridge mint)

**Status (2026-08-28): promoted** to plan
`docs/history/plans/2026-08-26-bridge-asset-registry-gate.md` (landed:
registry gate live; registered mint -> bridge, unregistered -> spam +
review).

- **Discovered**: review r1 F8 (risk; premortem discriminator gap).
- **State at deferral**: ANY token minted from the zero address to the
  wallet classified `Reward`/`SubType.bridge` with Tag `Bridge` + review; the
  discriminator gap is documented in `docs/maintenance/on_chain_validation.md`
  (the P2 rewards-from-on-chain split must key on the Tag and the review
  flag, NEVER on `EventType.Reward` alone).
- **Post-landing (2026-08-28)**: the registry gate replaced this behavior -
  a REGISTERED token's zero-address mint keeps `bridge`; an unregistered one
  (or an empty registry) now classifies `spam` + review with a mint-specific
  reason.
- **Why deferred**: distinguishing a trusted bridge mint (bridged WBTC) from
  a junk airdrop mint needs a curated per-year registry + membership gate;
  which tokens are bridge-issued is public and derivable in-session from the
  archived origin documents, but the curation had not been built (amended:
  derivation was from the 2025 TH baseline and public canonical-contract
  knowledge, not crypto-origin documents; see development lesson #159); and the
  review flag already forces human verification on the filing path, so
  nothing is silent today.
- **Plan sketch**: mirror the C8 position-NFT membership boundary - a
  per-year registry entry kind (e.g. `bridged_asset`) keyed by token address;
  `_reward_sub_type` returns `SubType.bridge` only for registry members,
  falling through to `spam` for unregistered zero-address mints (both stay
  review-flagged). The committed registry holds the PUBLIC bridged-token
  contracts, provenance-cited per the crypto-origin rules (2026-08-27 user
  amendment: canonical curated public data, not user-maintained; a gitignored
  user override is an optional escape hatch only).
- **Acceptance**: an unregistered zero-address mint classifies spam + review
  (not bridge); registered bridged assets keep the Bridge tag; the
  validation-gate clusters for the 2025 baseline are unchanged for registered
  assets.

## 4. Fetcher CSV atomic write (staleness-review residual r1-F14)

- **Origin**: staleness plan review r1 finding F14 (risk lens; merged verdict
  across r1-r5 panels; see
  `docs/history/reviews/2026-08-26-on-chain-staleness-refusal-code-review-r1.md`
  F14 and r5 pass).
- **Problem**: `on_chain_fetcher.py` (~line 139, `_write_csv`/fetch path) writes
  the bera CSV via truncate-then-write (`path.open("w", newline=...)`), no
  temp-file rename. A concurrent process reading mid-write observes a partial
  CSV. Usual outcome: truncated row fails the CSV parse and M1 raises a spurious
  `ReportGenerationError` (rerun succeeds). Edge outcome: truncation lands on a
  row boundary, the shortened file still parses, and the projection silently
  under-reports on-chain activity.
- **Reachability**: requires two simultaneous runs of the same fiscal year
  against the same output dir with a fetch in flight during the other's read.
  Single-user local CLI makes this rare, and `docs/maintenance/on_chain_validation.md`
  documents concurrent runs as unsupported; the retry ladder only slightly
  widens the window by doubling fetch frequency in the broken state
  (r10-F2 "harmless duplicate fetch" reasoning holds for single-process
  sequential runs only).
- **Why deferred**: root cause lives in `on_chain_fetcher.py` internals, which
  the staleness plan's Review Scope explicitly put out of scope (ladder CALLS
  the fetch callable; marker write mechanics stay as landed).
- **Fix sketch**: write to a temp file in the same directory plus
  `os.replace(tmp, csv_path)` in the fetcher; consider the same treatment for
  the `.fetch-failed` marker write if it is not already atomic (single small
  write). After landing, drop the "concurrent runs unsupported" caveat from
  `on_chain_validation.md` or narrow it.
- **Acceptance**: a reader-loop racing a fetch write never observes a partial
  CSV (test: spawn writer + reader threads, or monkeypatch to interleave);
  staleness predicate mtimes still behave (os.replace preserves the new write
  time); full suite green.

## 5. Staleness-suite structural residuals (staleness-review r1/r4 drops)

Small, settled-at-review items recorded here so they are not lost; do them
opportunistically when next touching these modules, not as standalone work
unless they compound:

- **r1-F9 (kept debt)**: two load-bearing `# noqa: PLR0913` on
  `_resolve_koinly_stage` and `_substitute_on_chain_th` in
  `src/tax_reporting/application/run_report.py` (6 kwargs each after the
  `on_chain_fetch` threading). If a third argument ever lands on either,
  bundle the stage parameters (`output_dir`/`year`/`tax_jurisdiction`/`logger`)
  into a small stage-context object instead of a third noqa.
- **r1-F11 (placement note)**: `fetch_marker_is_stale` lives in
  `on_chain_th_substitution.py` next to its last-resort consumer, while the
  marker it interprets is created by `on_chain_fetcher.write_fetch_failed_marker`
  and the primary runtime caller is the ladder in `on_chain_retry.py`. Cohesion
  would be slightly cleaner beside the marker owner; the plan's
  single-definition invariant is satisfied as-is, so move only alongside other
  fetcher-side work (e.g. item 4) to avoid churn.
- **r4/r5 residual (531→527 lines)**: `run_report.py` sits ~27 lines over the
  ~500 orchestration ceiling; the overage is almost entirely plan-frozen
  comments (seam freeze, carve-out rationale). If a future change adds logic
  rather than prose, extract or condense then; do not cut frozen comments just
  to hit the number.

## Cross-references

- Umbrella program: `docs/history/backlog/2026-08-18-koinly-cancellation-program.md`
  (P2 follow-up candidates section points here).
- Maintenance context: `docs/maintenance/on_chain_validation.md` (bridge-mint
  classification and the bridge-asset registry gate; fetch-failure staleness marker).
- Staleness plan reviews: `docs/history/reviews/2026-08-26-on-chain-staleness-refusal-code-review-r{1..5}.md`
  (items 4-5 above are their dispositioned residuals).
