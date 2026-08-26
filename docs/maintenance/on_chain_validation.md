# On-chain TH validation harness

Maintenance doc for the on-chain Transaction-History validation harness
(`--validate-on-chain-th`), the instrument that proves the production
on-chain TH path is semantically equivalent to the Koinly baseline before
Koinly is cancelled (PD-009/PD-010 in `docs/maintenance/project-decisions.md`).

## Command

```bash
uv run tax-reporting --validate-on-chain-th YEAR [--from YYYY-MM-DD] [--to YYYY-MM-DD]
```

Runs the PRODUCTION on-chain path (registry load -> `read_on_chain_rows` ->
`BerachainProcessor.process` -> integrity/freshness audit -> adapter
projection) on the real personal data for YEAR and diffs the projection
against the real Koinly transaction-history export under the PD-010
semantic-equivalence rules. The command is READ-ONLY over its inputs: the
Koinly export and `bera_transactions.csv` are opened read-only, nothing is
merged into the report pipeline, and the only writes land under the
gitignored `resources/result/<YEAR>/` (see Artifacts below).

`--from`/`--to` set an inclusive validation window (ISO dates): BOTH sides
(on-chain rows and Koinly TH rows) are filtered to the same window, so the
hash partitions stay comparable. This enables the walk-forward protocol
(PD-010 amendment): tune on an H1 window, freeze
rules/registries/compatibility table, then run the full year once with
everything frozen.

Wallets under validation: derived from the `resources/source/<YEAR>/chains.json`
entries with `chain == "Berachain"` (`load_on_chain_wallets`). When
`ON_CHAIN_TH_WALLETS` is set in the `config.ini` `[TAX JURISDICTION]`
section, it takes precedence: the chains.json Berachain wallets are filtered
to the configured labels (normalized match, the same `normalize_wallet_label` semantics
the TH merge uses). The harness itself never requires the flag.

Exit codes:

| Code | Meaning |
|---|---|
| 0 | Gate passed: every occurring discrepancy cluster carries an `acceptable_difference` disposition. |
| 1 | Misconfigured run (fail-loud, before any dispositions append): no Berachain wallets resolved, absent `bera_transactions.csv`, the Koinly side missing (no directory for the year, or no `*transaction_history*.csv` in it), or an EMPTY comparison - both sides filtered to zero rows, e.g. a `--from/--to` window that misses the data (review r1 F5: exit 0 is the acceptance evidence for the production flip, so a run that compared zero transactions must never read as a validated pass). |
| 2 | Unexpected crash of the validation CLI path: the `cli()` wrapper in `main.py` catches it, logs the full traceback via `logger.exception`, prints a friendly one-line message, and exits `EXIT_VALIDATION_CRASH`. |
| 3 | Validation incomplete: at least one occurring cluster is undispositioned, or a fix-type (`missing_rule`/`incorrect_processing`) cluster still occurs. |

Acceptance scripts can distinguish an unexpected crash (code 2) from a
misconfigured run (code 1): the crash wrapper in `cli()` is the only source
of code 2 from within the tool itself, so a nonzero exit with that value
means "inspect the invocation for a usage error, then the log file for the
recorded traceback" rather than "fix the harness inputs".
Note (review r1 F7): `2` is also the exit code argparse itself uses for
command-line usage errors (e.g. an unknown flag), which are rejected before
the validation dispatch runs.
Note (review r3 F3): a malformed `on_chain_th_dispositions.toml` (e.g.
hand-corrupted by the user) raises `ValueError` before the gate runs and
therefore also surfaces as code 2 (an unexpected crash caught by the `cli()`
wrapper), not code 1 - the dispositions file is validated data, not a harness
input, so its parse failure is a crash for acceptance-script purposes.
Note (review r4 F4): a present-but-invalid `config.ini` (or a missing
decision-points TOML) raises `ConfigurationError` /
`MissingDecisionPointsError`, which the wrapper in `main.py` deliberately
re-raises instead of catching. The process still ends with exit 1, but the
surface is a raw traceback rather than the fail-loud harness message (and
never code 2): a run ending with code 1 on that raw surface means "fix the
configuration files", not the row-1 harness-input causes.

The validate flag cannot be combined with `--example`, `--source-file`, or
`--output-dir`: the artifacts deliberately carry real tx hashes whose PII
rule is enforced by location (only the gitignored
`resources/result/<YEAR>/` surface - review r1 F21), so an alternate output
root is rejected rather than documented around.

## Artifacts (all under gitignored `resources/result/<YEAR>/`)

- `on_chain_th_validation.md` (regenerated every run): run header (inputs,
  `snapshot_as_of_block`, RPC on/off, wallet labels, validation window),
  summary counts (shared / Koinly-only / on-chain-only / match / divergent,
  per-cluster dispositioned-vs-NEW), and one section per cluster with up to
  five side-by-side samples.
- `on_chain_th_validation_diff.csv` (regenerated every run): one row per
  divergent tx, keyed by `tx_hash`, with the cluster signature and mismatch
  summary columns (carries real tx hashes; gitignored surface).
- `on_chain_th_dispositions.toml` (append-only, user-owned): the feedback
  loop; see the next sections.

## Harness workflow

load -> compare -> cluster -> dispositions -> artifacts -> gate:

1. **Load**: resolve the wallets (see Command), build the on-chain
   projection via the production pipeline
   (`OnChainThSubstituter.build_projection`, window args passed through -
   never a parallel parse path), and read the Koinly TH baseline with the
   production readers (`_find_report_path` + `read_koinly_rows`) filtered to
   the wallet rows (`is_wallet_row`) and, when a window is set, the same
   inclusive date filter.
2. **Compare**: `compare_projection` groups both sides by
   `TxHash`/`tx_hash` and applies the PD-010 semantic-equivalence rules: per
   shared hash, net amounts per `(asset, direction)` must match within the
   8-decimal display tolerance (the per-bucket tolerance scales with the
   Koinly row count), and each on-chain event's Koinly `(Type, Tag)` combo
   must be in the fixed compatibility table. Row cardinality is irrelevant.
   The 2025-H1 walk-forward tuning added four rendering-variance rules, each
   gated on an EXACT economic identity (details and negative guards in the
   `comparator.py` module docstring): asset buckets key on the case-folded
   ticker; a mirrored Koinly row (one movement rendered on BOTH sides, same
   currency, equal displayed amounts) counts once, on the direction(s) the
   projection carries (both when it carries neither, so the movement stays
   surfaced); a native-OUT amount exceeding the on-chain amount by EXACTLY
   the on-chain gas with an EMPTY Koinly gas surface for that currency is
   gas folded into the displayed amount (both the event and the gas mismatch
   are suppressed); and the compatibility table accepts the untagged
   `crypto_deposit/""` rendering for `Reward`, the untyped
   `crypto_deposit/""` + `crypto_withdrawal/""` pair for `Swap`, and - per
   the 2026-08-22 PD-010 amendment, after the LP snapshot's real population
   made pool operations classify as liquidity events - `exchange` and the
   same untyped pair for `LiquidityDeposit`/`LiquidityWithdraw` (Koinly has
   no native liquidity Type; the user's manual `To pool`/`From pool` marks
   cover only part of the baseline). Amount comparison is untouched by all
   of these; `crypto_deposit/Reward` is deliberately NOT accepted for
   liquidity events (mixed deposit+claim txs stay surfaced). Asset keys
   additionally fold issuer-declared ticker aliases (amendment #3,
   chain-agnostic, per-contract evidence required to extend the table):
   glyph-vs-ASCII spellings (`USD₮0` -> `USDT0`, the contract's `symbol()`
   carries the glyph) and issuer renames (`HONEY` -> `BUSD`: contract
   `0xfcbd14dc...` declared `BUSD`/`"Bera USD"` via on-chain `eth_call`
   (verified 2026-08-22, surfacing on the 2025 baseline when the Etherscan
   metadata refreshed mid-August 2026), while Koinly still renders the
   pre-rename `HONEY`; address unique in the dataset, per-tx amounts equal
   once merged). Aggregator labels are temporal views, not identity; see
   `development_lessons.md` #136 before extending the table. Because this ticker-keyed join is
   only sound while one folded ticker identifies one contract per dataset,
   the comparator FAILS LOUD (ticker-identity collision) when a run's
   on-chain legs map one folded ticker to two distinct token contracts -
   LP tokens included; token identity elsewhere (LP snapshot, contract
   registry, LP classification, cluster `lp=`) is address-keyed, never
   name-keyed.
3. **Cluster**: `group_into_clusters` groups every discrepancy record
   (divergent, on-chain-only, Koinly-only) by its PII-free cluster
   signature.
4. **Dispositions**: `append_new_clusters` appends one template
   `[[clusters]]` block per NEW signature to the dispositions file (dedup
   across runs, never rewrites), then `load_dispositions` reads all entries
   back.
5. **Artifacts**: `write_validation_artifacts` regenerates the markdown
   report and the diff CSV.
6. **Gate**: `evaluate_gate` decides the exit code (0/3 above).

## Disposition vocabulary and the feedback loop

The dispositions file (`resources/result/<YEAR>/on_chain_th_dispositions.toml`)
is append-only and user-owned:

- the harness appends one `[[clusters]]` template block per NEW cluster
  signature (fields `signature`, `first_seen`, and empty `disposition`,
  `root_cause`, `action`) and never rewrites or deletes existing entries;
- the user fills each block by hand; the harness never writes a ruling.

Decision authority (amended 2026-08-22, user-delegated; PD-010 amendment
#3): the agent may record a disposition for an OPEN cluster when the data
decides it - amounts equal with only vocabulary differing, a source row
count the export cannot account for, an issuer-declared ticker - marking the
block `agent-decided` with the evidence in `root_cause`. User rulings remain
required for genuine judgment calls (tax-treatment choices, ambiguity the
data cannot resolve, preference). Backstop: the P4 dry-run comparison (our
pipeline's report vs the Koinly-derived one) reopens any agent-decided entry
it contradicts. (Two-source cardinality checks: `development_lessons.md`
#134; dispositions-file status hygiene: #135.)

Vocabulary (the TOML file's values map to PD-010's terms):

- `missing_rule` (PD-010 *new rule*): a classifier/heuristic gap -> fix;
- `incorrect_processing` (PD-010 *updated rule*): an existing rule is too
  narrow or too broad -> fix;
- `acceptable_difference` (PD-010 *accepted as normal*): Koinly was
  wrong/incomplete; the divergence is a documented known-baseline gap.

Feedback-loop semantics: fix-type rulings (`missing_rule`,
`incorrect_processing`) keep failing the gate while their cluster still
occurs and pass once it stops occurring (the fix-landed assertion);
`acceptable_difference` lets a cluster keep occurring without blocking. The
exit code stays 3 until only `acceptable_difference` clusters remain.
Malformed TOML fails loud with the file path (never silently ignored), and
the fail-loud input checks run BEFORE any append, so a misconfigured run
never writes feedback-loop state.

Run ONE validation of a given year at a time (review r1 F7): the append
dedup is check-then-act (`load_dispositions` -> membership check -> append),
so two concurrent runs on the same year can both pass the check and append
duplicate blocks, after which every later load fails loud on the duplicated
signature until the user hand-dedups the append-only file. The harness is
otherwise single-threaded; the only way to hit the window is running two
validations of the same year simultaneously.

## Cluster-signature components

The signature is a stable, PII-free semantic key (`clustering.py`);
components join as `k=v` with `|`:

```
events=<sorted EventType names>|koinly=<sorted Type/Tag combos>|sender=<class>|lp=<bool>|fee=<class>|zero_display=<bool>
```

- `events`: the on-chain event-type names, sorted, joined with `+` (`none`
  when the on-chain side is absent);
- `koinly`: the Koinly `Type/Tag` combos, sorted, joined with `+` (`none`
  when the Koinly side is absent);
- `sender`: the counterparty registration class, resolved via
  `ContractRegistry.get` on the tx counterparties (the Koinly side's arrive
  via `TxSrc`/`TxDest`): `reward_distributor` / `dex_router` /
  `rebate_router` / `self_wallet` / `unregistered` / `null_or_empty`;
- `lp`: whether any touched token is an LP-snapshot token (`true`/`false`),
  resolved from the on-chain legs' token addresses (the authoritative source -
  the snapshot is keyed by token addresses while visible tickers never match
  those keys; the runner threads the source transactions into the comparison)
  with the asset identifiers as the fallback (a Koinly-only record has no
  on-chain legs);
- `fee`: the Koinly fee-rendering surface: `cost_rows` / `fee_column` /
  `none` / `mixed`;
- `zero_display`: whether a compared amount renders `0,00000000` on the
  Koinly side (`true`/`false`).

`|` is only the component separator and never appears inside a value; the
values of a multivalued component are sorted, so the signature is
deterministic under input reordering. The cluster, not the individual tx,
is the unit of resolution (PD-010: no per-transaction override ledger).

## PII rules

- Cluster signatures are PII-free by construction: no tx hashes, no wallet
  addresses, no dates, no amounts (unit-tested). They may appear in
  committed docs and the dispositions file.
- Artifacts that carry real tx hashes (`on_chain_th_validation.md`,
  `on_chain_th_validation_diff.csv`) are written ONLY under gitignored
  `resources/result/<YEAR>/` (the PII rule is enforced by location, not by
  omission).
- Committed docs stay address-free (no `0x` + 40-hex literals); public
  contract addresses live in the registries, and the real self-wallet
  address lives only in the gitignored
  `resources/source/<YEAR>/berachain_contracts.json`.

## Acceptance gate (flipping `ON_CHAIN_TH_WALLETS`)

The 2025 Koinly export set is the ONLY Koinly baseline that will ever exist
(the subscription covers 2025 only; 2026 onward runs on-chain-only with no
Koinly cross-check by construction). The acceptance gate for flipping
`ON_CHAIN_TH_WALLETS` in `config.ini` (a user decision, made outside any
plan) is therefore:

1. Tune on an H1 window until the windowed run exits 0 (walk-forward
   protocol, PD-010 amendment).
2. FREEZE rules, registries, compatibility table, and tolerance constants.
3. Run the full year ONCE with everything frozen; triage its NEW
   signatures (each is a missing rule or a new user disposition).
4. The full-year zero-exit closes the protocol: the user may then flip
   `ON_CHAIN_TH_WALLETS` for the BERA wallet.

The validation-harness plan itself does NOT flip the flag; the
non-opted-in production path stays byte-identical until the user flips it.

## Fetch surface and adapter projection contract

### Fetch endpoints (four)

The collector (`on_chain_fetcher.py` -> `etherscan_client.py`) pulls FOUR Etherscan
account actions per wallet: `txlist` (native transfers), `tokentx` (ERC-20
transfers), `txlistinternal` (internal native value transfers, recovered via the
block-pagination seam), and `tokennfttx` (ERC-721/1155 transfers; plan
`2026-08-24-multi-leg-th-projection`). The wire action is `tokennfttx`: an
earlier `nfttx` name was rejected by the live V2 API ("Error! Missing Or
invalid Action name") and, before the fail-loud status:"0" guard, silently
looked like an empty wallet (found on real data 2026-08-25); "nfttx" survives
only as the surface label in prose and code. The `nfttx` surface is what makes
ERC-721 position-NFT legs (Koinly symbol format `SYMBOL#tokenID`, quantity 1)
reliably visible on-chain - they are not reliably present in the other three
actions (when `tokentx` duplicates one, the overlap guard below defers to the
`nfttx` row).

Registry-membership gate on nfttx decode: an `nfttx` row decodes to an
`OnChainTxRow` (`asset="SYMBOL#tokenID"`, `amount_raw=1`, `amount_decimals=0`)
ONLY when its `token_address` (contract) is a member of the per-year
position-token registry (`PositionTokenRegistry.is_position_nft_token`,
address-keyed and kind-gated to `position_nft` entries; `lst`-kind members
are ERC-20 tokens - when the nfttx surface nevertheless carries one as an
ERC-1155 transfer, the kind gate skips it (see the decoder WARNING and the
C2 registry section). Non-member transfers (spam airdrop mints such as BERA777) are
skipped with a WARNING and a count, so they stay on-chain-invisible and the
existing `events=none|koinly=crypto_deposit/` acceptable-difference cluster
keeps describing them correctly - no content filtering, membership only
(C8 boundary). An overlap guard keyed `(tx_hash, token_address, direction)`
drops a tokentx row that duplicates an nfttx-decoded transfer for the same
registry-member contract (the nft surface is authoritative), accounted PER KEY
COUNT (review r1 F2): one decoded nfttx row replaces exactly one tokentx row
of the same key, extra same-key tokentx rows are retained (never silently
dropped), a match-count WARNING carries the dropped count, and a mismatch
WARNING fires when the two surfaces disagree per key. ERC-721 quantity-1-only
(review r1 F3): an `nfttx` row that looks ERC-1155 (batch `tokenID`
containing `*`, `tokenValue` other than 1, or an empty `tokenID` with an
empty `tokenValue` - the ERC-1155 batch shape; review r2 F4) is
WARNING-skipped - ERC-1155 quantity semantics are unsupported and honoring
`tokenValue` would be a user decision.

### Adapter projection: one TH row per (Event, leg pair)

The adapter (`on_chain_th_adapter.py`) projects ONE `TransactionHistoryRow` per
(Event, leg pair): out legs and in legs zip by position (`out[0]/in[0]`,
`out[1]/in[1]`, ...), unpaired remainder legs emit one-sided rows (sending
side only, or receiving side only), and a single-pair Event (1 out + 1 in, or
a one-sided single) emits exactly ONE row byte-identical to the earlier
single-row projection. A `tx_hash` therefore legitimately maps to MULTIPLE
projected rows (multi-leg swaps, LP deposits/withdraws).

Per-row event-id suffix: the single-pair row carries the processor's
`event_id` (`f"{tx_hash}#{n}"`) verbatim; when one Event projects to multiple
rows, rows after the first append the leg-pair discriminator `.{k}` (k >= 2) -
row 1 `f"{tx_hash}#{n}"`, row 2 `f"{tx_hash}#{n}.2"`, row 3
`f"{tx_hash}#{n}.3"`. No two projected rows share `(tx_hash, event_id)`, which
keeps `TxCorrelationKey` (domain Invariant 5) and the FIFO dedup
(`crypto_fifo/parsing.py:_dedup_by_tx_key`, keep-first-per-key) from silently
collapsing same-Event leg-pair rows. Gas stays counted exactly once: exactly
one row per tx (the carrier row - the row whose representative leg is the
native asset, else the first row; GasBurn rows never) carries the fee payload.

Review r1 F1 fallback: a leg-bearing Event whose legs are ALL
direction="unknown" (the processor's shape-1 review path, reachable up to the
1% unknown-leg gate) still emits ONE review row - both sides empty, the
processor's `event_id` verbatim - plus a WARNING, so review-carrying rows can
never silently vanish from the projection.

### Fetch-failure staleness marker (2026-08-26)

The bera CSV is written only after every wallet and action succeeds, so a
failed refresh leaves the PREVIOUS run's `bera_transactions.csv` in place.
When that happens the run_report soft-fail catch writes a best-effort
`bera_transactions.csv.fetch-failed` marker next to the CSV (also written
when the wallet config resolves empty while a prior CSV exists); the TH
substitution stage then compares mtimes and logs a loud ERROR when the
marker is newer, naming the possible missing activity. By design this does
NOT refuse (the collection fetch is non-blocking; a valid prior CSV stays
reviewable), and a later successful fetch rewrites the CSV newer than the
marker, self-healing without any explicit cleanup; deleting the marker is
the documented manual clear. Promoting to a hard refusal and surfacing the
staleness inside the report artifacts are recorded P2 candidates in the
umbrella backlog.

### Bridge-mint classification (Reward/bridge, 2026-08-26)

A PURE inflow whose leg is MINTED from the zero address has no external
sender, so the F4 unverified-sender (spam) premise does not apply: the
processor classifies it `Reward` + `SubType.bridge` with review and a
bridge-specific reason (source and cost basis must be verified - the workflow
cannot match the inflow to the originating acquisition, e.g. a CEX withdrawal
routed through a bridge; real case: the wallet's bridged WBTC deposits).
The adapter renders such Events with Tag `Bridge` (not `Reward`) via the
named `SUB_TYPE_TAG_OVERRIDES` vocabulary, so merged-TH consumers and the
future P2 rewards-from-on-chain split cannot mistake a bridge/CEX transfer-in
for reward income. The comparator's reverse map is derived AUTOMATICALLY from that vocabulary at
import (`_build_reverse_combo_map` iterates `SUB_TYPE_TAG_OVERRIDES` and
raises on a colliding combo), so there is no manual registration step; a tag
override applied anywhere OTHER than the single `SUB_TYPE_TAG_OVERRIDES` dict
reverse-maps to `Unknown` and fails the gate loudly (observed once, 2026-08-26,
before the lookup was extended).

Discriminator gap (review r1 F8): the zero-address marker does NOT distinguish
a trusted bridge mint from a spam airdrop mint - ANY token minted directly to
the wallet classifies `Reward`/`SubType.bridge` and renders Tag `Bridge`, with
the review flag the only guard. Note (review r4): the frozen `EVENT_COMPATIBILITY` table deliberately does NOT accept a Koinly-side `Bridge` tag for `Reward` - only the ON-CHAIN projection renders `crypto_deposit/Bridge` (recovered by the reverse map). A manually Bridge-tagged baseline row would fail the gate loudly (type mismatch); widening the table is a PD-010 amendment to plan with the P2 rewards split. The P2 rewards-from-on-chain split must therefore key on the Tag (and the review flag), never on `EventType.Reward` alone; a registry-gated bridge-asset allowlist (mirroring the C8 position-NFT
membership boundary) is the recorded follow-up option if junk-mint noise
grows.

### The multi-leg rendering family and exit 3

The 17 `missing_rule` disposition signatures that held exit 3 on the 2025
baseline (16 LP-shaped signatures showing "on-chain 0 vs Koinly N" on every
non-first leg, plus the iBERA two-leg Swap record; two of which also needed
the `nfttx` fetch) are exactly the gap this per-leg-pair projection family
closes. The zero-exit on the 2025 full-year run is the P1 flip gate
prerequisite recorded in the umbrella backlog
`docs/history/backlog/2026-08-18-koinly-cancellation-program.md` (P1 status:
landed 2026-08-21; the multi-leg/nfttx slice is its remaining exit-3 closure
toward the `ON_CHAIN_TH_WALLETS` flip gate).

## C2 enablement paths (LP-token classification)

`BerachainProcessor` classifies a BIDIRECTIONAL tx receiving an LP token as
`LiquidityDeposit` (and the mirror direction as `LiquidityWithdraw`) only when
the token is KNOWN to be an LP token. LP-token recognition has two layers,
and at least one must be enabled for LP operations to classify correctly -
with neither fed real data, pool operations fall through to `Swap` /
`Reward` (taxable-disposal misclassification; C2). The validation run header
(`on_chain_th_validation.md`) records which layers are active: the
`LP snapshot as of block` line (present whenever a snapshot loads) and the
`RPC enrichment: enabled/disabled` line.

### Path 1 - populate the LP snapshot from the Kodiak subgraph

Populate `resources/source/<year>/berachain_lp_snapshot.json` (gitignored;
the committed synthetic template lives at
`resources/source/example/2025/berachain_lp_snapshot.json`). The file is the
PRIMARY classifier: an address-keyed allowlist consulted by
`LpAutodiscovery` with O(1) lookup.

Query recipe (entity sources per the design record,
`docs/architecture/on-chain-tx-design.md` §9.2 - see there for the endpoint
and the research corrections; do not re-derive here):

- Kodiak V2 pairs: subgraph entity `Pair.id` - the LP ERC-20 address, with
  `token0`/`token1` kept for provenance.
- Kodiak Islands (ERC-4626 auto-compounder over V3 positions): subgraph
  entity `KodiakVault.outputToken` (`.id`).
- Bault vaults (Kodiak's own auto-compounder wrapping an Island): the
  `stakingToken` field from the Bault backend listing.

Refresh notes from the 2026-08-22 population run (20 tokens for tax year
2025; see the gitignored snapshot's `_comment` for that run's provenance):

- Candidate addresses for a year = the distinct `token_address` values in
  that year's `bera_transactions.csv`; classify them with subgraph
  `id_in` / `outputToken_in` filters instead of name heuristics.
- The kodiak-v3 subgraph indexes NO entity for Kodiak weighted pools (the
  `50A-50B-WEIGHTED` share tokens) and no `Token` entity for non-pair
  ERC-20s, so those addresses return empty from every subgraph entity.
- The Bault backend listing drops retired vaults; historical staking tokens
  are absent from it.
- For addresses the subgraph and backend cannot confirm, the authoritative
  fallback is the token contract itself: `name()` / `symbol()` via
  `eth_call` on a public Berachain RPC (record the contract-declared name
  in the entry as provenance).
- Pin `subgraph_version` to the deployment hash from
  `_meta { deployment }` and set `snapshot_as_of_block` from
  `_meta { block { number } }` at query time.

Required fields (schema-validated on load by `build_lp_snapshot` in
`src/tax_reporting/application/on_chain_config.py`; a violation raises
`ConfigurationError` fail-loud):

- `subgraph`: informational subgraph name (e.g. `kodiak-v3`).
- `subgraph_version`: non-empty and NOT `latest` - pinned, so the schema
  cannot drift between snapshot and validation runs.
- `snapshot_as_of_block`: int >= 0 - the block the allowlist was taken at.
- `snapshot_as_of_date`: non-empty ISO date - the human-readable cut date.
- `tokens`: list of entries, each with a non-null string `token_address`;
  `protocol` and `type` are optional informational tags.

Freshness is enforced downstream, not by the loader: `LpAutodiscovery.
check_freshness` emits a WARNING when a tx's block postdates
`snapshot_as_of_block` (a brand-new pool absent from the snapshot would
otherwise misclassify as `Swap` instead of `LiquidityDeposit` - a phantom
capital gain). Refresh the snapshot (raising `snapshot_as_of_block` /
`snapshot_as_of_date`) whenever that WARNING fires on legitimate activity.

### Path 2 - set `ON_CHAIN_RPC_URL` for the bytecode fallback

Set `ON_CHAIN_RPC_URL` in the `[TAX JURISDICTION]` section of `config.ini`
to a Berachain JSON-RPC endpoint. This enables the FALLBACK classifier:
`LpAutodiscovery` fingerprints tokens not in the snapshot via on-chain
bytecode / implementation-address lookups through `RpcClient`.

Constraints (enforced at the config seam,
`src/tax_reporting/infrastructure/config.py`, `ON_CHAIN_RPC_URL` block):

- https-only: any non-`https` scheme is rejected with a `ValueError` at
  configuration load (the RPC client may send credentials; `http://` would
  carry them in cleartext).
- Optional: absent/empty keeps LP classification snapshot-only.

With the flag set, the validation run header records
`RPC enrichment: enabled`; with it unset, `disabled`.

### Path 3 - populate the position-token registry (LST / position-token deposits)

`BerachainProcessor` classifies a PURE outflow of LST / staking-position
receipt tokens (and single-leg deposits routed through a position-NFT vault
recipient) as `LiquidityDeposit` only when the token/recipient address is a
member of the position-token registry. Populate
`resources/source/<year>/bera_position_tokens.json` (gitignored; the
committed synthetic template lives at
`resources/source/example/2025/bera_position_tokens.json`). The registry is
an address-keyed allowlist (loaded by `load_position_token_registry` and
injected at `_build_processor` in `on_chain_th_substitution.py`): each entry
carries a non-empty `token_address` plus optional `label`, `kind`
(`"lst"` for tradable staking receipts vs `"position_nft"` for the vault
contracts a deposit routes through - `kind` gates the recipient rule and the
bidirectional-receive position-NFT mint detector (review r2 F1): an
`lst`-kind member bought on a DEX stays a `Swap`), and
`provenance`. The bidirectional position-NFT mint detector additionally
requires the mint shape to touch a registry vault on EITHER side (review
r3 F1 + r4 F1): the economic out-legs pay the vault OR the position NFT
arrives FROM the vault (a router/zapper-mediated mint pays an intermediary
and still receives the NFT from the vault); a market purchase from a
non-vault pair does neither and stays a `Swap`. A provenance-only mint
(NFT arrives from the vault but no economic out-leg pays one) keeps the
`LiquidityDeposit` classification but carries a review flag naming the
vault sender(s) and non-vault payment counterparties, mirroring the shape-6
ambiguity pattern: the actionable reason is visible in the merged TH
(`on_chain_merged_th.csv`) `Description` cell of the projected row and in
the build-time WARNING log, so the review-flagged-deposit scan below covers
both surfaces. (Review r7 F1: EVERY review-flagged Event - including spam
rewards, unknown-direction legs, and the matched-no-pattern `Unknown`
fallback - persists a specific actionable `review_reason` into that
`Description` cell, so an EMPTY `Description` on a flagged row is a bug,
not an accepted state.) Derive candidate addresses from the FULL set of divergent
records in the validation diff (Unknown clusters whose out-legs send receipt
tokens or whose tx recipient is the vault), recording the cluster/signature
as each entry's provenance - never from asset-name matching. When the
registry is absent or an address is missing, the affected txs surface
fail-loud for review (never a guess): single-leg outflows classify as
`Unknown` + review, while multi-leg outflows classify as `LiquidityDeposit`
carrying a review flag UNLESS another member signal (an LP-snapshot member
token on an out-leg, or a registry-member recipient) clears it. The
multi-leg family therefore does NOT surface as
an Unknown cluster (a review-flagged deposit may still match the baseline),
so when scanning for registry gaps also check the review-flagged deposits,
not only the Unknown clusters, in the next harness run.

### Which path when

The snapshot is deterministic, offline, and auditable - prefer it as the
source of truth and keep it refreshed past the latest tx block in the
dataset. The RPC fallback catches pools newer than the snapshot (or missed
by it) at the cost of network calls during a run; enabling it never removes
the need for freshness metadata. The two layers compose: snapshot first,
bytecode fallback for the remainder.
