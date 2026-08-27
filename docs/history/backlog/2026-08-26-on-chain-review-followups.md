# Backlog: On-chain review-loop follow-ups (2026-08-26)

Three candidates deferred with record during the review loop on branch
`2026-08-25-nfttx-wire-action-fix` (rounds r1-r5; staging docs in gitignored
`docs/history/reviews/2026-08-26-branch-review-2026-08-25-nfttx-wire-acti*.md`).
Each was a valid, non-blocking finding whose fix was judged larger than the
round warranted; none blocks the `ON_CHAIN_TH_WALLETS` flip. Promote each as
its own plan (or fold into P2/P4 planning) when taken.

## 1. Staleness handling: hard refusal + in-artifact indicator

- **Discovered**: review r1 F6 (risk; stale-CSV failure mode), extended r2 F5
  (risk; artifact-side indicator) and hardened through r3-r5 (empty-config
  marker, TOCTOU guard, unrecognized-type raise).
- **Current state (landed)**: a failed or skipped on-chain refresh writes
  `bera_transactions.csv.fetch-failed` next to the CSV; the TH substitution
  compares mtimes and logs a loud ERROR when the marker is newer; a later
  successful fetch self-heals (the CSV is rewritten newer); deleting the
  marker is the documented manual clear (see
  `docs/maintenance/on_chain_validation.md` "Fetch-failure staleness marker").
- **Why deferred**: the collection fetch is deliberately non-blocking (DI-1)
  and pre-flip the substituted TH is not yet consumed by report generation,
  so a refusal would have changed a documented design contract mid-review-loop
  for a failure mode not yet reachable in production. The in-artifact
  indicator needs a home on the report surfaces (review_reason plumbing
  exists for Events, but staleness is projection-wide, not per-Event).
- **Plan sketch**: for opted-in wallets, either refuse the run (fail-loud,
  mirroring the M1 parse-failure contract) or attach a projection-level
  review indicator that reaches the Excel review surfaces (Crypto
  Reconciliation / Platform Assumptions) naming the stale window. Decide the
  contract first (that is the real work); the plumbing is small.
- **Acceptance**: a run whose on-chain refresh failed cannot produce output a
  user can mistake for complete (refusal, or a visible in-artifact flag).

## 2. Comparator module extraction (module-size rule)

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

- **Discovered**: review r1 F8 (risk; premortem discriminator gap).
- **Current state (landed)**: ANY token minted from the zero address to the
  wallet classifies `Reward`/`SubType.bridge` with Tag `Bridge` + review; the
  discriminator gap is documented in `docs/maintenance/on_chain_validation.md`
  (the P2 rewards-from-on-chain split must key on the Tag and the review
  flag, NEVER on `EventType.Reward` alone).
- **Why deferred**: distinguishing a trusted bridge mint (bridged WBTC) from
  a junk airdrop mint needs a curated per-year registry + membership gate;
  which tokens are bridge-issued is public and derivable in-session from the
  archived origin documents, but the curation had not been built; and the
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

## Cross-references

- Umbrella program: `docs/history/backlog/2026-08-18-koinly-cancellation-program.md`
  (P2 follow-up candidates section points here).
- Maintenance context: `docs/maintenance/on_chain_validation.md` (bridge-mint
  classification + discriminator gap; fetch-failure staleness marker).
