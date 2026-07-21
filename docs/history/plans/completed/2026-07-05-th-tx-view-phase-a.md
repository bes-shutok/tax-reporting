# Plan: TH-anchored Transaction view - Phase A (foundation)

RFC: [docs/history/context/2026-06-20-th-anchored-transaction-state-machine.md](../context/2026-06-20-th-anchored-transaction-state-machine.md#rollout-plan-2026-07-05) (un-shelved 2026-07-05; this is Phase A of the five-phase rollout recorded there).

Plan review: [r1](../reviews/2026-07-05-plan-review-th-tx-view-phase-a-r1.md) (4 Blockers + 7 Medium addressed in revision 2) -> [r2](../reviews/2026-07-05-plan-review-th-tx-view-phase-a-r2.md) (0 Blocker, 1 Medium + 4 Low + 3 Monitor addressed in revision 3) -> [r3](../reviews/2026-07-05-plan-review-th-tx-view-phase-a-r3.md) (latest, ready: Blocker=0, Medium=0). Trivial r3 Lows (CSV-shape provenance + DEX typo) folded in post-r3; no substantive change.

**Amendment 2026-07-06a (mid-execution, user-approved).** Task 1 measurement and a follow-up semantics study (see `docs/tmp/phase-a-tx-id-prevalence.md` and `docs/tmp/phase-a-tx-id-semantics.md`) revealed that the original "single tx_id resolved by precedence over (TxHash, TxSrc, TxDest)" design conflated three semantically distinct fields. TxHash is the on-chain identifier; TxSrc and TxDest are wallet addresses that never equal TxHash on the same row. In two-leg transfer clusters (398 in production), the legs share TxHash but MIRROR addresses (withdrawal.TxSrc == deposit.TxDest), so a triple-equality key would fragment transfer grouping instead of strengthening it. The amendment: `TransactionHistoryRow` stores all three fields separately (`tx_hash`, `tx_src`, `tx_dest`, each `str | None` with `""` normalized to `None`); `TxCorrelationKey.tx_id` derives from `tx_hash` alone (no precedence chain); the composite fallback is unchanged. This satisfies both user cases: same-row grouping (LP provision + fee-in-tokens rows on the same TxHash carry identical addresses, so equality on tx_hash is sufficient) and cross-leg transfer grouping (legs share TxHash with mirrored addresses, so equality on tx_hash alone correctly correlates them). Invariant 2 simplified accordingly; Invariant 11 added to capture the field-separation rule. Tasks 2, 3, 6 updated to reflect the new shape; Task 1's precedence question collapses to "use TxHash".

**Amendment 2026-07-06b (mid-execution, user-approved; substantive - resets plan-review counter to r1).** Task 4 halt-and-flag step surfaced a CLAUDE.md violation: the proposed hardcoded wallet-label seed list (Kraken/ByBit/Wirex -> CEX; Ledger*, SUI* -> DEX) bakes per-user wallet labels into production code, contradicting "Wallet labels are discovery hints only; final chain/country mappings come from archived operator origin documents." The user redirected: classify at **platform level** (not per wallet label, since one CEX platform owns many wallet addresses that rotate over time), using a **two-tier resolver** with no hardcoded labels in code:

1. **Registry tier (authoritative).** A platform already mapped in the crypto-origin registry / Platform Assumptions manifest inherits its kind from the registry. Confidence: 100%. No code-side label list.
2. **Auto-discovery tier (fallback).** For platforms not yet in the registry, classify from row evidence aggregated at the platform level: per-platform tally of on-chain Types (`crypto_deposit`/`crypto_withdrawal`) vs off-chain Types (`buy`/`sell`/`fiat_deposit`/`fiat_withdrawal`) vs on-chain-shaped TxHash (EVM/BTC/Solana shapes from `docs/tmp/phase-a-tx-id-semantics.md` Q2). Kind = majority vote; confidence = majority / total.

Output: extend the existing **Assumptions & Methodology** tab's Platform Assumptions section with a new `Kind` column (CEX/DEX/UNKNOWN) and a confidence indicator. Platforms with confidence below the high-probability threshold (0.95) get red Review Required and a reason in the Note column (e.g. `MIXED: 12 on-chain / 3 off-chain` or `Not in registry; classified by row evidence only at 80%`). Auto-discovered platforms double as a registry-gap signal: each one surfaced is a candidate to add to `docs/maintenance/tax/crypto-origin/` in a follow-up.

This amendment **expands Phase A scope** from "typed plumbing only, no production caller" to "typed plumbing plus one user-facing artifact (Kind column in Assumptions & Methodology)". All other Excel tabs remain byte-identical. The no-production-caller invariant (old Invariant 1) is replaced: production wiring is permitted ONLY at `assumptions_sheet.py` to render the Kind column; all other call sites (FIFO, OGR, payment_proceeds, fee_filter, etc.) remain unwired.

A new **Task 8: ByBit alias cleanup** is added because the user noted the production data no longer carries `ByBit (2)` / `ByBit (3)` wallet aliases. The ByBit special case in `normalize_platform_name` (CRG-008) is now dead code; removing it (and the corresponding rule + tests) is safe and is done in this phase.

Restructured task list: Task 4 (platform-level two-tier resolver), Task 5 (build_transaction factory), Task 6 (TxCorrelationKeyResolver), Task 7 (extend Assumptions & Methodology tab with Kind column), Task 8 (ByBit cleanup), Task 9 (smoke + re-exports + count diff; was old Task 7). Invariants 7, 8, 12, 13, 14 added/updated; old Invariant 1 rescoped; Tasks 4-7 rewritten and Tasks 8-9 added.

Phase A introduces the domain plumbing the later phases consume: a typed
`Transaction` object anchored on Transaction History, a `TxCorrelationKey`, and
resolvers that produce the key with DEX-aware missing-tx-id review flagging plus
a platform-level WalletKind classification surfaced in the Assumptions &
Methodology tab. **Production wiring in Phase A is limited to rendering the new
Kind column**; no FIFO, OGR, payment-proceeds, fee-filter, or token-origin
caller consumes the new types yet.

## Terms

- **TH** - Transaction History, the Koinly report whose columns include `Date`
  (explicit UTC), `Type`, `Tag`, `TxSrc`, `TxDest`, `TxHash`, and per-side
  wallet/amount/cost-basis fields. The only report with a transaction id.
- **CG** - Capital Gains report; per-FIFO-lot, naive local-time dates.
- **OGR** - Other Gains Report; per-row realized P&L, naive local-time dates.
- **TransactionHistoryRow** - new typed wrapper (this phase) for one TH row.
  Stores three separate identifier fields (`tx_hash`, `tx_src`, `tx_dest`,
  each `str | None` with `""` normalized to `None`) plus the typed
  economic fields. The downstream `tx_id` used by `TxCorrelationKey` is
  derived from `tx_hash` alone; `tx_src`/`tx_dest` are wallet addresses,
  not tx-id candidates (see Invariants 2 and 11, amended 2026-07-06).
- **Transaction** - new domain object (this phase) that wraps a
  `TransactionHistoryRow` plus a resolved `WalletKind` and an
  `is_unrecognized_wallet` flag.
- **TxCorrelationKey** - new value object (this phase). Two components:
  `tx_id: str | None` and `composite: TxCompositeKey`. Equality is two-tier
  (Invariant 5).
- **TxCompositeKey** - NamedTuple `(utc_instant, asset, wallet, amount, row_index)`.
  Always includes `row_index` so the composite is unique per TH row, preventing
  silent merging of two distinct rows that coincide on the other four fields.
- **WalletKind** - new enum (this phase): `CEX`, `DEX`, `UNKNOWN`. Drives the
  missing-tx-id review-flag policy (DEX-only flagging) AND the new Kind column
  in Assumptions & Methodology.
- **CEX / DEX** - centralized exchange vs decentralized on-chain. A platform
  is CEX when its operation is off-chain (the platform issues exchange-internal
  trade IDs only); a platform is DEX when its operation is on-chain (rows carry
  on-chain TxHashes per `docs/tmp/phase-a-tx-id-semantics.md` Q2). Classification
  is at **platform level**, not per wallet address, because one CEX platform
  owns many wallet addresses that rotate over time.
- **WalletKindResolver** - new (this phase). Two-tier, platform-level
  classifier (amended 2026-07-06b). Tier 1: registry lookup in
  `docs/maintenance/tax/crypto-origin/` via `operator_origin` (confidence 100%).
  Tier 2: row-evidence auto-discovery from per-platform TH tally of on-chain
  Types vs off-chain Types vs on-chain-shaped TxHash (confidence = majority /
  total). Returns `(WalletKind, confidence: float, reason: str)`. **No
  hardcoded wallet labels in production code** (CLAUDE.md: wallet labels are
  discovery hints only).
- **High-probability threshold** - 0.95. Platforms with confidence >= 0.95 are
  rendered without red. Platforms below 0.95 get red Review Required + reason.
  Tier-1 (registry) matches are always confidence 1.0; only tier-2
  (auto-discovered) platforms can land below threshold.
- **PlatformEvidence** - new frozen dataclass (this phase): `(on_chain_votes: int,
  off_chain_votes: int, total: int)`. The per-platform tally of TH rows whose
  Type/TxHash shape indicates on-chain activity vs exchange-internal activity.
  Computed by `aggregate_platform_evidence(rows)`.
- **WalletClassification** - new frozen dataclass (this phase):
  `(kind: WalletKind, confidence: float, reason: str, source: Literal["registry",
  "auto"])` with method `is_high_probability() -> bool` returning
  `confidence >= HIGH_PROBABILITY_THRESHOLD`. The return value of
  `classify_platform(platform, evidence, registry)`.
- **RegistrySnapshot** - read-only view over `docs/maintenance/tax/crypto-origin/`
  operator-origin data (existing). Used as the tier-1 authoritative source for
  platform -> WalletKind. Phase A consumes it via the existing
  `operator_origin` pipeline; no schema change.

## Gist & Examples

### What changes

Today every cross-report crypto join keys on naive `(date, asset, wallet)`
tuples. TH rows are passed around as `dict[str, str]` and only a handful of
fields are read (`TxSrc` in `token_origin.py:101` for withdrawal provenance;
`TxHash` in `crypto_fifo/parsing.py:156` for FIFO lot matching). There is no
typed view of "what a transaction is" and no concept of transaction identity
that survives across CG / OGR / TH.

Phase A introduces (all in one new domain module, plus additions to two
existing modules):

1. `TransactionHistoryRow` - frozen dataclass that captures the typed fields
   from one TH row. Stores three separate identifier fields (`tx_hash`,
   `tx_src`, `tx_dest`, each `str | None` with `""` normalized to `None`).
   The downstream `TxCorrelationKey.tx_id` is derived from `tx_hash` alone
   (no precedence chain). Per the 2026-07-06 amendment, this replaces the
   original "single tx_id resolved by precedence" design, which conflated
   TxHash (the on-chain identifier) with TxSrc/TxDest (wallet addresses).
2. `Transaction` - frozen dataclass domain object that wraps a
   `TransactionHistoryRow` plus `wallet_kind: WalletKind` and
   `is_unrecognized_wallet: bool` (set when WalletKindResolver returned
   UNKNOWN for the row's wallet).
3. `TxCorrelationKey` + `TxCompositeKey` - value objects for cross-report
   correlation. Equality is two-tier (see Invariant 5). `TxCompositeKey`
   always carries `row_index` so two rows sharing the same composite fields
   do not silently merge (matches the precedent of `_build_composite_tx_key`
   in `crypto_fifo/_emitters.py:457-468`, which appends `row_index` for the
   same reason).
4. `WalletKindResolver` - **two-tier, platform-level classifier** (amended
   2026-07-06b). Tier 1 inherits kind from the crypto-origin registry via
   `operator_origin` (confidence 100%, no hardcoded labels). Tier 2
   auto-discovers kind from per-platform row evidence (on-chain vs off-chain
   Types, on-chain-shaped TxHash) when a platform is not yet in the registry.
   Returns `(WalletKind, confidence: float, reason: str)`. The Tier 2 output
   doubles as a registry-gap signal: every platform that lands here is a
   candidate to add to `docs/maintenance/tax/crypto-origin/`.
5. `TxCorrelationKeyResolver` - given a `Transaction`, returns
   `(TxCorrelationKey, requires_review: bool)`. `requires_review` is `True`
   iff `tx_id is None and wallet_kind is DEX`. CEX rows with missing tx-id
   fall back silently, per the user's policy (CEX routinely omit tx-id).
6. **Assumptions & Methodology tab extension** - the existing Platform
   Assumptions section gets one new column `Kind` (CEX/DEX/UNKNOWN) plus a
   confidence indicator in the Note column. Platforms with confidence below
   the high-probability threshold (0.95) get red Review Required plus a
   reason (e.g. `MIXED: 12 on-chain / 3 off-chain`, or `Not in registry;
   classified by row evidence only at 80%`). Registry-sourced platforms
   (Tier 1) are always confidence 1.0 and never red-flagged for kind.

### What does NOT change

- The live crypto pipeline (`crypto_reporting.py`, `ogr_handler.py`,
  `payment_proceeds.py`, `derivatives_dedup.py`, `loan_activity.py`,
  `fee_filter.py`, `crypto_fifo/`) keeps its current `dict[str, str]` row
  shape and its current `TxHash`-only / `TxSrc`-only call sites. Phase A adds
  types alongside, not in place of.
- The existing `parse_koinly_datetime`, `parse_koinly_decimal`,
  `normalize_platform_name`, `normalize_asset_ticker`, `read_koinly_rows`
  helpers in `infrastructure/koinly_parser.py` are reused unchanged. The new
  `parse_th_row` is a thin orchestrator on top of them, not a re-implementation
  (Invariant 6).
- Excel outputs are byte-identical EXCEPT for the Assumptions & Methodology
  tab, which gains one new column `Kind` (CEX/DEX/UNKNOWN) and may add
  kind-related entries to the Note column. All other tabs (CG lots, OGR rows,
  payment corrections, loan activity, fee filter output, reward classification)
  are byte-identical. The existing Platform Assumptions rows keep their current
  Operator Entity / Country / Confidence / Review Required / Tx Count values;
  the kind column is purely additive.
- No new public CLI flags, no new config keys, no new Excel tabs (the kind
  rendering reuses the existing Platform Assumptions real estate).

### Concrete example

Input TH row (dict form), shape taken from the committed synthetic CSV
`resources/source/example/koinly2025/koinly_2025_transaction_history_synth.csv`
(rows use comma-decimal without thousands grouping, 8-digit fractional,
sometimes quoted):

```
Date: 2025-01-12 15:22:00 UTC
Type: crypto_withdrawal
Tag: Futures fee
Sending Wallet: Demo Futures
Sent Amount: "4,27180510"
Sent Currency: USDT
Receiving Wallet: ''     Received Amount: ''      Received Currency: ''
TxHash: ''    TxSrc: ''    TxDest: ''
```

Phase A produces (UNKNOWN wallet - factory sets `is_unrecognized_wallet=True`
and emits exactly one WARNING via `WalletKindResolver`):

```python
Transaction(
    row=TransactionHistoryRow(
        utc_instant=datetime(2025, 1, 12, 15, 22, 0, tzinfo=UTC),
        type='crypto_withdrawal', tag='Futures fee',
        sending_wallet='Demo Futures',
        sending_amount=Decimal('4.27180510'),
        sending_currency='USDT',
        receiving_wallet=None, receiving_amount=None, receiving_currency=None,
        tx_hash=None, tx_src=None, tx_dest=None, row_index=1,
    ),
    wallet_kind=WalletKind.UNKNOWN,
    is_unrecognized_wallet=True,
)

TxCorrelationKeyResolver.resolve(transaction)
# -> (TxCorrelationKey(tx_id=None,   # tx_id derives from tx_hash alone (Invariant 2)
#                      composite=TxCompositeKey(datetime(...), 'USDT',
#                                               'Demo Futures',
#                                               Decimal('4.27180510'), 1)),
#     requires_review=False)   # UNKNOWN is treated as non-DEX per Invariant 9
```

### Why this chunk

The user's directive (2026-07-05): proactive structural migration in digestible
chunks, with the legacy path retained for double-checking. Phase A lands the
type vocabulary and the DEX-aware review-flag policy without altering any
output, so review can focus on whether the `Transaction` shape,
`TxCorrelationKey` equality semantics, and `tx_id` precedence are right before
Phase B hangs treatment resolution off them. The comprehensive synthetic test
corpus lands in Phase C alongside the state machine.

## Evaluation Criteria

**Quality dimensions:**

- **No behavior change outside the Assumptions & Methodology tab (correctness
  floor, amended 2026-07-06b):** the existing crypto test suite passes
  byte-identical before and after Phase A for every Excel tab except
  Assumptions & Methodology. Test COUNT under
  `uv run pytest tests/unit/application/ tests/unit/domain/ tests/end_to_end/`
  must increase by exactly the number of new test functions Phase A adds; no
  existing test may disappear, become `xfail`, or skip. Existing tests that
  assert Assumptions & Methodology shape are updated to include the new Kind
  column; no other test edits for changed output are permitted.
- **WalletKindResolver correctness (amended 2026-07-06b):** Tier-1 (registry)
  matches return `(kind, 1.0, "registry")` for every platform already mapped
  via `operator_origin`. Tier-2 (auto-discovery) returns the majority kind with
  `confidence = majority_votes / total_votes` and a reason naming the evidence
  counts. Pure-CEX platforms (only off-chain Types, only exchange-internal
  TxHashes) classify as CEX at 1.0. Pure-DEX platforms (only on-chain Types,
  only on-chain-shaped TxHashes) classify as DEX at 1.0. Mixed-evidence
  platforms classify as the majority with confidence below 1.0 and a reason
  naming both vote tallies. Verified by discriminating parametrized tests
  (Task 4).
- **Assumptions & Methodology tab rendering (amended 2026-07-06b):** the
  Platform Assumptions section renders one row per platform with the new Kind
  column populated. Platforms below the 0.95 threshold get red Review Required
  (existing `REVIEW_ROW_FILL`) and a reason in the Note column. Registry-sourced
  platforms never get red-flagged for kind. Verified by an Excel-rendering test
  that builds a synthetic entry list mixing registry + auto-discovered
  platforms and asserts the row fills + Note text (Task 7).
- **Boundary coverage:** the threshold comparison is `>=` (>= 0.95 = high
  probability, not red). Boundary tests at exactly 0.95 and exactly 0.94
  verify the off-by-one direction (Task 4).
- **Type safety:** all new types are `frozen=True` dataclasses or `Enum` or
  `NamedTuple`; `utc_instant` is always timezone-aware at UTC; `tx_hash`,
  `tx_src`, `tx_dest` are each `str | None`, never `""` (empty string
  normalizes to `None`). `TxCorrelationKey.tx_id` is `str | None` and is
  derived from `tx_hash` alone (Invariant 2, amended 2026-07-06).
- **Reuse, not re-implementation:** `parse_th_row` delegates decimal parsing
  to `parse_koinly_decimal`, datetime parsing to `parse_koinly_datetime`
  (which already handles the ` UTC` literal), and wallet/asset normalization
  to `normalize_platform_name`/`normalize_asset_ticker`. No re-implementation.
- **Review-flag policy correctness:** DEX rows without tx-id always raise
  `requires_review=True`; CEX rows without tx-id always raise
  `requires_review=False`; any row (DEX or CEX) with a tx-id raises
  `requires_review=False`. Verified by discriminating parametrized tests
  (Task 6).
- **Equality/hash contract:** `TxCorrelationKey.__eq__` and `__hash__` obey
  Invariant 5 exactly. Verified by a parametrized hash-consistency test that
  asserts `A == B` implies `hash(A) == hash(B)` for every Invariant-5 case,
  and that `A != B` does NOT require different hashes (Python's hash-vs-eq
  contract allows collisions, but equal objects MUST hash equally).
- **Composite uniqueness:** `TxCompositeKey` includes `row_index`; two
  distinct TH rows never produce equal `TxCompositeKey`s. Verified by a test
  that builds two rows with identical `(utc_instant, asset, wallet, amount)`
  but different `row_index` and asserts unequal composites and (when tx_id is
  None) unequal `TxCorrelationKey`s.
- **No silent fallthrough:** `WalletKindResolver` returns `UNKNOWN` for any
  label it cannot classify, and emits a `logger.warning` per unique unseen
  label (dedup per label, not per row). No `KeyError`, no `dict.get(...)`
  masking.

**Release gates:**

- All existing crypto tests pass unchanged.
- All new Phase A unit tests pass (no skips, no `xfail`).
- `uv run ruff check src/tax_reporting/ tests/` clean.
- `~/.ai-playbook/scripts/check-no-em-dash.sh` clean on changed files.
- No public-API addition outside the new module `domain/transaction.py` and
  the two additions to existing modules (`infrastructure/koinly_parser.py`,
  `application/crypto/entities.py` re-exports).
- Validation grep (see `## Validation Commands`) reports
  `GOOD: no production caller`.

## Review Scope

**Explicit must-fix**; findings on these paths are always in scope (review and
fix if valid):

**Production code (new modules):**

- `src/tax_reporting/domain/transaction.py` *(new)* - hosts
  `TransactionHistoryRow`, `Transaction`, `TxCompositeKey`, `TxCorrelationKey`.
- `src/tax_reporting/application/crypto/wallet_kind.py` *(new)* - hosts
  `WalletKind`, `WalletKindResolver`.
- `src/tax_reporting/application/crypto/tx_correlation_key_resolver.py` *(new)*
  - hosts `TxCorrelationKeyResolver`.
- `src/tax_reporting/application/crypto/transaction_factory.py` *(new)* - hosts
  `build_transaction`.

**Production code (touched, additive only):**

- `src/tax_reporting/infrastructure/koinly_parser.py` - new `parse_th_row`
  function (reuses existing helpers in the same module); removal of the
  ByBit special case from `normalize_platform_name` (Task 8). No other change.
- `src/tax_reporting/application/crypto/entities.py` - re-export of
  `Transaction` / `TransactionHistoryRow` / `TxCompositeKey` /
  `TxCorrelationKey` / `WalletKind` / `WalletKindResolver` /
  `TxCorrelationKeyResolver` / `build_transaction` for ergonomic single-package
  imports. No field changes to existing classes.
- `src/tax_reporting/application/persisting/assumptions_sheet.py` *(amended
  2026-07-06b)* - extends the Platform Assumptions section with a `Kind` column
  and a confidence/reason rendering. Existing columns and existing review-flag
  behavior unchanged for non-kind signals. Method-level scope: `_collect_platform_summaries`
  and the rendering block that emits the Platform Assumptions table; other
  methods in this file are frozen.

**Tests (existing, appended only):**

- `tests/unit/application/test_crypto_entities.py` - new re-export assertions
  appended; no edits to existing assertions.

**Tests (new files, flat layout per existing convention):**

- `tests/unit/domain/test_transaction.py` *(new)* - covers all four new
  domain types (TransactionHistoryRow + Transaction + TxCompositeKey +
  TxCorrelationKey) consolidated in one test module matching the consolidated
  production module.
- `tests/unit/infrastructure/test_koinly_parser_th_row.py` *(new)* - covers
  `parse_th_row`. Standalone module: `parse_th_row` is a new entry point on the
  existing module; cohesion argues for a peer test file alongside
  `test_koinly_parser.py` (currently 372 lines).
- `tests/unit/application/test_wallet_kind.py` *(new)* - flat under
  `tests/unit/application/` matching the existing layout.
- `tests/unit/application/test_tx_correlation_key_resolver.py` *(new)* - flat.
- `tests/unit/application/test_transaction_factory.py` *(new)* - flat.
- `tests/unit/application/test_assumptions_sheet_kind_column.py` *(new,
  amended 2026-07-06b)* - covers the new Kind column rendering and the
  red-threshold logic for auto-discovered platforms below 0.95.
- `tests/unit/application/test_crypto_phase_a_smoke.py` *(new)* - end-to-end
  smoke test exercising `parse_th_row -> Transaction -> resolve` per Monitor 1.

**Plan-related extension**; Phase A is mostly plumbing with one user-facing
Excel extension (Kind column in Assumptions & Methodology). Treat a finding as
in scope when it is causally related to introducing the new types OR to the
Kind column rendering: e.g. a name collision with an existing
`Transaction`/`TxCorrelationKey` symbol elsewhere in the codebase, an import
cycle the new modules create, a normalization rule (empty-string to `None`,
UTC enforcement, decimal-separator delegation) the new types violate, or a
platform-summary field the new Kind column should ride on. Drop anything else
as out of scope with a one-line reason.

**Out of scope; reject unless plan-related:**

- `src/tax_reporting/application/crypto_reporting.py`; Phase A adds no callers
  in this file. Phase B/C will edit it.
- `src/tax_reporting/application/crypto/ogr_handler.py`,
  `payment_proceeds.py`, `derivatives_dedup.py`, `loan_activity.py`,
  `fee_filter.py`, `crypto_fifo/`, `token_origin.py`; untouched in Phase A
  except `token_origin.py:99-101` comment cleanup is NOT done here (it is a
  Phase B follow-up per the Task 1 semantics study). Findings on these are
  out of scope unless the new types introduce a contract violation they
  already depend on (none expected).
- `docs/maintenance/crypto_rules.md`; Phase A has no rule or filing-output
  change. Phase D (treatment flip) will edit it.
- The existing `TxSrc`-only call in `token_origin.py` and the `TxHash`-only
  call in `crypto_fifo/parsing.py`; Phase A does NOT migrate or refactor these.
  They stay as-is until Phase D per-treatment flip. A review finding that
  these should be unified with the new `tx_id` resolver belongs to Phase D.

## Design Invariants (CR Guard)

1. **Production wiring in Phase A is limited to the Assumptions & Methodology
   tab.** (Rescopeded 2026-07-06b; was "no production caller".) The new types
   and resolvers are constructible and unit-tested, AND
   `assumptions_sheet.py` renders the new Kind column. CR guard: reject any
   change that wires the new types into `crypto_reporting.py`,
   `ogr_handler.py`, `payment_proceeds.py`, `derivatives_dedup.py`,
   `loan_activity.py`, `fee_filter.py`, `token_origin.py`, or `crypto_fifo/`.
   The only permitted production call site in Phase A is
   `src/tax_reporting/application/persisting/assumptions_sheet.py`.

2. **`tx_id` is `tx_hash`; no precedence chain.** (Amended 2026-07-06.)
   `TxCorrelationKey.tx_id` derives from `tx_hash` alone, normalized to
   `None` when empty. The Task 1 measurement plus the semantics study at
   `docs/tmp/phase-a-tx-id-semantics.md` established that TxHash is the
   on-chain identifier (EVM/BTC/Solana hash, or exchange-internal id for
   off-chain Types) and that TxSrc/TxDest are wallet addresses, not
   identifiers (they never equal TxHash on the same row; one hot-wallet
   address collapses 53,685 rows). In 398 production withdrawal+deposit
   transfer clusters, the legs share TxHash but MIRROR addresses
   (`withdrawal.TxSrc == deposit.TxDest`), so a triple-equality key would
   fragment transfer grouping. CR guard: reject any code path that falls
   back to `tx_src` or `tx_dest` as a tx-id candidate, or that claims a
   Hash/Src/Dest precedence chain.

3. **`tx_hash`, `tx_src`, `tx_dest` are each `str | None`, never `""`.**
   Empty / whitespace-only inputs normalize to `None`. CR guard: reject any
   code path that stores `""` in any of these three fields (or in
   `TxCorrelationKey.tx_id`).

4. **`utc_instant` is always timezone-aware at UTC.** TH's `Date` column
   carries an explicit ` UTC` suffix; `parse_th_row` must localize it to UTC
   via the existing `parse_koinly_datetime` helper, not return a naive
   datetime. CR guard: reject a parser that returns naive datetimes.

5. **`TxCorrelationKey` equality is two-tier and hash follows equality.**
   Equal iff `(a.tx_id is not None and a.tx_id == b.tx_id)` OR
   `(a.tx_id is None and b.tx_id is None and a.composite == b.composite)`.
   `tx_id` is sourced from `TransactionHistoryRow.tx_hash` (Invariant 2,
   amended 2026-07-06). Mixed `None`/non-`None` pairs are never equal.
   `__hash__` is consistent: when `tx_id is not None` the hash is
   `hash(tx_id)`, otherwise `hash(composite)`. `TxCompositeKey` includes
   `row_index`, so two distinct TH rows (different `row_index`) with
   otherwise-equal composite fields are NOT equal when both `tx_id`s are
   None. CR guard: reject implementations that compare only `tx_id`, only
   `composite`, or that hash both fields while comparing only one.

6. **`parse_th_row` MUST delegate to existing helpers.** Decimal parsing to
   `parse_koinly_decimal`, datetime parsing to `parse_koinly_datetime`, wallet
   normalization to `normalize_platform_name`, asset-ticker normalization to
   `normalize_asset_ticker`. No re-implementation. CR guard: reject a parser
   that re-implements European-separator parsing, UTC handling, or
   platform-name normalization. Rationale: repo rule "Sibling aggregators that
   merge the same field type must use byte-identical patterns or a shared
   helper; diverging patterns silently drop data."

7. **`WalletKindResolver` is two-tier and platform-level; no hardcoded labels
   in code.** (Amended 2026-07-06b; was "hardcoded seed list flagged to
   user".) Tier 1 inherits kind from the crypto-origin registry via
   `operator_origin` (confidence 1.0). Tier 2 auto-discovers kind from
   per-platform row evidence (on-chain Types vs off-chain Types vs
   on-chain-shaped TxHash). Classification is at **platform level**, not per
   wallet address, because one CEX platform owns many rotating wallet
   addresses. CR guard: reject any change that introduces a hardcoded label
   list (Kraken, ByBit, etc.) in production code, OR that classifies at
   wallet-label granularity instead of platform granularity. Rationale:
   CLAUDE.md "Wallet labels are discovery hints only; final chain/country
   mappings come from archived operator origin documents" + Family D (single
   source of truth).

8. **`Transaction.is_unrecognized_wallet` rides with the data.** Set at
   construction by the `Transaction` factory (which calls
   `WalletKindResolver`). `TxCorrelationKeyResolver.resolve()` reads the
   `wallet_kind` field on `Transaction`; it does NOT call
   `WalletKindResolver` directly. CR guard: reject a resolver that calls
   `WalletKindResolver` itself, or a `Transaction` factory that omits the
   flag. Rationale: a downstream consumer that builds keys must not silently
   lose the wallet-classification signal (Family G: data-loss observability).

9. **DEX-only missing-tx-id flagging.** `requires_review` is True iff
   `tx_id is None and wallet_kind is DEX`. CEX rows with missing tx-id return
   `requires_review=False` silently. UNKNOWN rows with missing tx-id return
   `requires_review=False` (the loud signal comes from
   `Transaction.is_unrecognized_wallet`, not from the resolver). CR guard:
   reject a resolver that flags CEX or UNKNOWN rows, fails to flag DEX rows,
   or flags any row with a non-None `tx_id`.

10. **No backward-compat shim for re-exports.** `entities.py` re-exports the
    new types for ergonomic imports, but no legacy `dict[str, str]` consumer
    is migrated or shimmed. CR guard: reject `cast()` / adapter shims that
    paper over the dict-to-dataclass boundary inside the new modules.

11. **`TransactionHistoryRow` exposes all three identifier fields separately;
    no precedence collapse.** (Added 2026-07-06.) The dataclass has `tx_hash`,
    `tx_src`, `tx_dest` as independent `str | None` fields; it does NOT expose
    a derived `tx_id` field. The only consumer of these fields for cross-row
    correlation is `TxCorrelationKeyResolver`, which builds `TxCorrelationKey`
    from `tx_hash` (Invariant 2). Downstream Phase B-D work (transfer-leg
    reasoning, fee filter, LP-provenance migration) reads `tx_src`/`tx_dest`
    directly off the row. CR guard: reject any design that collapses the three
    fields into a single `tx_id` field on `TransactionHistoryRow`, or that
    introduces a Hash/Src/Dest precedence resolver.

12. **High-probability threshold is 0.95; comparison is `>=`.** (Added
    2026-07-06b.) Platforms with `confidence >= 0.95` are rendered without
    red Review Required for kind; platforms below 0.95 are red-flagged with a
    reason in the Note column. The threshold is a named module-level constant,
    not a literal. CR guard: reject inline `0.95` literals, OR `>` comparisons
    that off-by-one the boundary (a platform with confidence exactly 0.95 is
    NOT red-flagged). Boundary tests at exactly 0.95 and exactly 0.94 enforce
    the direction.

13. **TxHash shape constants are protocol facts, not user preferences.**
    (Added 2026-07-06b.) The three on-chain TxHash shapes (EVM: 66-char
    `0x` + 64 hex; BTC: 64-hex no prefix; Solana: 88-char base58) are
    reused from `docs/tmp/phase-a-tx-id-semantics.md` Q2 as named constants
    in production code. They do NOT belong in `config.ini` (CLAUDE.md: config
    is user preferences only; these are protocol facts). CR guard: reject any
    change that moves these shapes to config, OR that introduces a fourth
    shape without amending this invariant.

14. **ByBit alias normalization is removed; CRG-008 is deleted.** (Added
    2026-07-06b.) The ByBit special case in `normalize_platform_name`
    (regex `^ByBit \(\d+\)$` -> "ByBit") is dead code: production data no
    longer carries `ByBit (2)` / `ByBit (3)` wallet aliases, and the new
    platform-level resolver + registry handles the consolidation at the
    correct layer. CRG-008 in `crypto_reporting_guidelines.md` and the ByBit
    alias section in `crypto_implementation_guidelines.md` are deleted in
    Task 8. The corresponding tests at
    `tests/unit/application/test_crypto_reporting.py:2793,2808` are deleted or
    inverted. CR guard: reject any change that re-introduces a ByBit-specific
    branch in `normalize_platform_name`, OR that rewrites `normalize_platform_name`
    beyond removing the ByBit branch (other normalizations stay byte-identical).

15. **Assumptions & Methodology changes are purely additive; kind signal is
    OR'd into the existing Review Required.** (Added 2026-07-06b.) The new
    `Kind` column is appended to the right of the existing Platform Assumptions
    columns. Existing columns (Platform / Operator Entity / Country / Confidence
    / Review Required / "Assumption / Verification Note" / Tx Count) and their
    values are byte-identical for non-kind signals. The kind-confidence signal
    is OR'd into the **existing** `platform_review_required` flag (which already
    unions `origin.platform_review_required`); there is still exactly ONE Review
    Required column. A platform's Review Required value may flip from NO to YES
    only when the kind-confidence signal alone triggers it; no existing review
    flag is silenced. CR guard: reject any change that reorders existing
    columns, OR that adds a SECOND Review Required column, OR that suppresses
    an existing review flag, OR that fills the Kind column for non-platform
    rows (e.g. methodology section rows).

## Validation Commands

```bash
# Phase A floor: no behavior change in the existing crypto pipeline
# Capture baseline test count BEFORE Phase A work begins (Task 0);
# the post-Phase-A count must equal baseline + (new test functions added).
uv run pytest tests/unit/application/ tests/unit/domain/ tests/end_to_end/ \
  --collect-only -q | tail -3

# New types and resolvers are fully covered (no skips)
uv run pytest \
  tests/unit/domain/test_transaction.py \
  tests/unit/infrastructure/test_koinly_parser_th_row.py \
  tests/unit/application/test_wallet_kind.py \
  tests/unit/application/test_tx_correlation_key_resolver.py \
  tests/unit/application/test_transaction_factory.py \
  tests/unit/application/test_assumptions_sheet_kind_column.py \
  tests/unit/application/test_crypto_phase_a_smoke.py -q

# Re-exports present
uv run pytest tests/unit/application/test_crypto_entities.py -q

# Lint and format
uv run ruff check src/tax_reporting/ tests/
uv run ruff format --check src/tax_reporting/ tests/

# No em dash in changed files
~/.ai-playbook/scripts/check-no-em-dash.sh

# Confirm the only production caller of the new types is assumptions_sheet.py
# (Phase A invariant 1, rescopeded 2026-07-06b). Use a SYMBOL-name grep
# (production code uses relative imports, so module-path patterns miss).
grep -rnE '\b(Transaction|TransactionHistoryRow|TxCorrelationKey|TxCompositeKey|WalletKind|WalletKindResolver|TxCorrelationKeyResolver|build_transaction)\b' \
  src/tax_reporting/application/crypto_reporting.py \
  src/tax_reporting/application/crypto/ogr_handler.py \
  src/tax_reporting/application/crypto/payment_proceeds.py \
  src/tax_reporting/application/crypto/derivatives_dedup.py \
  src/tax_reporting/application/crypto/loan_activity.py \
  src/tax_reporting/application/crypto/fee_filter.py \
  src/tax_reporting/application/token_origin.py \
  src/tax_reporting/application/crypto_fifo/ \
  | grep -vE '^\s*#' \
  && echo "BAD: forbidden production caller wired" || echo "GOOD: no forbidden production caller"

# Confirm ByBit special case is gone (Phase A Task 8 / Invariant 14)
grep -nE 'ByBit' src/tax_reporting/infrastructure/koinly_parser.py \
  && echo "BAD: ByBit special case still present" || echo "GOOD: ByBit normalization removed"

# Confirm CRG-008 references are gone from docs (Phase A Task 8 / Invariant 14)
grep -rnE 'CRG-008' docs/maintenance/ \
  && echo "BAD: CRG-008 still referenced" || echo "GOOD: CRG-008 removed"

# Confirm no inline 0.95 threshold literals (Phase A Invariant 12)
grep -rnE '\b0\.95\b' src/tax_reporting/ \
  | grep -vE 'test|constants' \
  && echo "BAD: inline 0.95 literal found" || echo "GOOD: threshold is a named constant"
```

The grep is contract-removal-style: Phase A invariant 1 (rescopeded
2026-07-06b) forbids production callers EXCEPT `assumptions_sheet.py`, so any
non-comment match in the listed files is a violation.

### Task 0: Baseline test count (before any code change)

Files:
- (no file changes; baseline-capture only)

- [x] Run: `uv run pytest tests/unit/application/ tests/unit/domain/ tests/end_to_end/ --collect-only -q | tail -3` and record the test count and the "no tests ran" line. Save to `{tmp_dir}/phase-a-baseline-count.txt` (use `docs/tmp/phase-a-baseline-count.txt` per `facts.md`). **Baseline: 1357 tests collected.**
- [x] Run: `git stash list` to confirm no in-flight changes; if the branch is not clean, halt and ask the user before proceeding. (The baseline must reflect master state at the branch point.) Working tree clean (RFC note edit + plan file resolved externally before Task 0).
- [x] Commit: none. Baseline is recorded for the Task 7 count-diff check.

### Task 1: `tx_id` field semantics and prevalence measurement (locks Invariant 2, amended)

Files:
- (no production code yet; measurement task only)
- `docs/tmp/phase-a-tx-id-prevalence.md` *(new, gitignored scratch)*
- `docs/tmp/phase-a-tx-id-semantics.md` *(new, gitignored scratch; added 2026-07-06)*

- [x] Run a one-shot script (under `docs/tmp/`) over the real CSV(s) in `resources/source/koinly*/` plus `resources/source/example/koinly*/*transaction_history*.csv` that, for each TH `Type` value, counts rows where `TxHash`, `TxSrc`, `TxDest` are non-empty (after `.strip()`). **Report per-source counts separately** (production `koinly2025/` vs synthetic `example/koinly*`). Output a Markdown table to `docs/tmp/phase-a-tx-id-prevalence.md`. - Production: 12 files, 125,468 rows; TxHash dominates every populated Type; fiat_withdrawal populates none.
- [x] Inspect the prevalence table and propose a precedence chain. Decision rule: prefer the field with the highest populated count per `Type`; if no single field dominates, prefer `TxHash` (Koinly's documented primary id). If the chain turns out `Type`-dependent, document that and propose a `Type`-aware resolver. - Initial proposal: first non-empty of (TxHash, TxSrc, TxDest).
- [x] **Halt and flag the user** with the proposed precedence chain and the prevalence table before writing production code. CLAUDE.md: "Never introduce a hardcoded value without first flagging it and asking the user." - User pushed back: TxHash/TxSrc/TxDest have distinct semantics (hash vs wallet addresses); requested all 3 be used for grouping; delegated research.
- [x] (Added 2026-07-06) Run a semantics study over production data: per-Type co-occurrence matrix; TxSrc/TxDest classification (hash vs wallet address); cross-row grouping signal strength; existing call-site semantics at `token_origin.py:101` and `crypto_fifo/parsing.py:156`; the two-leg transfer pattern. Output to `docs/tmp/phase-a-tx-id-semantics.md`. Finding: TxHash is the on-chain identifier; TxSrc/TxDest are wallet addresses; in 398 transfer clusters the legs MIRROR addresses (withdrawal.TxSrc == deposit.TxDest); a triple-equality key would fragment transfer grouping.
- [x] (Added 2026-07-06) Halt and flag the user with the semantics finding and the amended design proposal (store all 3 fields, key on `tx_hash` alone). User accepted the amendment.
- [x] After user confirmation, paste the confirmed rule into the Task 2 docstring spec for `TransactionHistoryRow`. - Confirmed rule: `TransactionHistoryRow` stores `tx_hash`, `tx_src`, `tx_dest` separately; `TxCorrelationKey.tx_id` derives from `tx_hash` alone. Invariant 2 simplified; Invariant 11 added.
- [x] Commit: none. Scratch files under `docs/tmp/` (gitignored); no source change. (Plan amendment committed separately as a chore; Task 1 itself produces no source commits.)

### Task 2: `TransactionHistoryRow` and the new domain module

Files:
- `src/tax_reporting/domain/transaction.py` *(new)* - consolidated module
  hosting the four new domain types.
- `src/tax_reporting/infrastructure/koinly_parser.py` - new `parse_th_row`
  function added; reuses existing helpers in the same module.
- `tests/unit/domain/test_transaction.py` *(new)* - covers
  `TransactionHistoryRow` (and, in the same file, `Transaction`,
  `TxCompositeKey`, `TxCorrelationKey` from later tasks).
- `tests/unit/infrastructure/test_koinly_parser_th_row.py` *(new)* - covers
  `parse_th_row`.

- [x] `TestTransactionHistoryRow#test_frozen`; given a constructed `TransactionHistoryRow`, expects attribute assignment to raise `FrozenInstanceError`.
- [x] `TestTransactionHistoryRow#test_stores_tx_hash_tx_src_tx_dest_separately`; given a row dict with `TxHash="0xh"`, `TxSrc="addrA"`, `TxDest="addrB"`, expects `parsed.tx_hash == "0xh"`, `parsed.tx_src == "addrA"`, `parsed.tx_dest == "addrB"` as three distinct fields. (Invariant 11, amended 2026-07-06.)
- [x] `TestTransactionHistoryRow#test_no_derived_tx_id_field_on_row`; given the dataclass fields, expects the field set to include `tx_hash`, `tx_src`, `tx_dest` and NOT to include `tx_id`. (Invariant 11: the derived `tx_id` belongs on `TxCorrelationKey`, not on the row.)
- [x] `TestTransactionHistoryRow#test_tx_hash_normalizes_empty_to_none`; given a row dict where `TxHash=""`, expects `tx_hash is None`. (Invariant 3.)
- [x] `TestTransactionHistoryRow#test_tx_src_normalizes_empty_to_none`; given a row dict where `TxSrc="   "`, expects `tx_src is None`. Whitespace-only normalizes to None.
- [x] `TestTransactionHistoryRow#test_tx_dest_normalizes_empty_to_none`; given a row dict where `TxDest=""`, expects `tx_dest is None`.
- [x] `TestTransactionHistoryRow#test_tx_hash_strips_whitespace`; given a row dict where `TxHash="  0xhash123  "`, expects `tx_hash == "0xhash123"`.
- [x] `TestTransactionHistoryRow#test_utc_instant_is_timezone_aware_utc`; given a TH row with `Date="2025-06-14 12:33:01 UTC"`, expects `utc_instant.tzinfo is datetime.UTC` and `utc_instant.utcoffset() == timedelta(0)`. (Invariant 4.)
- [x] `TestTransactionHistoryRow#test_amounts_parsed_via_parse_koinly_decimal_european_thousands`; given `Received Amount="143,75200000"` (real CSV shape from the committed synth file row 2), expects `receiving_amount == Decimal("143.75200000")`. (Invariant 6 delegation.) A second parametrized case using a thousands-separator variant `5.131,00000000 -> Decimal("5131.00000000")` verifies the helper handles both shapes; the production gitignored CSV uses the thousands form, the committed synth file does not.
- [x] `TestTransactionHistoryRow#test_amounts_blank_when_row_has_no_sending_side`; given a `crypto_deposit` row whose `Sent Amount`, `Sent Currency` are blank, expects `sending_amount is None` and `sending_currency is None`. (Real shape from koinly2025 row 4.)
- [x] `TestTransactionHistoryRow#test_row_index_assigned_from_parser_arg`; given `parse_th_row(row, row_index=42)`, expects `parsed.row_index == 42`. (Blocker 2 fix: row_index is part of the type.)
- [x] `TestParseThRowDelegation#test_delegates_to_parse_koinly_datetime`; given a TH row whose `Date` value would raise from `parse_koinly_datetime` (e.g. garbage string), expects `parse_th_row` to surface the same `ValueError` (or wrap it naming the helper). (Invariant 6.)
- [x] `TestParseThRowDelegation#test_delegates_to_parse_koinly_decimal`; given a TH row whose `Sent Amount` value would raise from `parse_koinly_decimal`, expects `parse_th_row` to surface the same error type.
- [x] `TestParseThRowDelegation#test_delegates_to_normalize_platform_name`; given a TH row with `Receiving Wallet="Kraken"`, expects the resulting `receiving_wallet` to equal `normalize_platform_name("Kraken")` byte-for-byte (call the helper in the assertion). (Invariant 6 + Family H: verify the helper is actually used.)
- [x] Run RED: `uv run pytest tests/unit/domain/test_transaction.py tests/unit/infrastructure/test_koinly_parser_th_row.py -q` -> fails (modules do not exist yet).
- [x] Write `TransactionHistoryRow` frozen dataclass in `domain/transaction.py` and `parse_th_row(row: Mapping[str, str], row_index: int) -> TransactionHistoryRow` in `koinly_parser.py` (next to the existing `parse_koinly_*` helpers). Fields: `utc_instant`, `type`, `tag`, `sending_wallet`, `sending_amount`, `sending_currency`, `receiving_wallet`, `receiving_amount`, `receiving_currency`, `tx_hash`, `tx_src`, `tx_dest`, `row_index`. Module docstring on `transaction.py` cites the Task 1 semantics study (`docs/tmp/phase-a-tx-id-semantics.md`) explaining why TxHash/TxSrc/TxDest are stored separately and why `tx_hash` is the only field used downstream for correlation (Invariant 2 + 11, amended 2026-07-06).
- [x] Run GREEN.
- [x] Commit: `feat(crypto): add TransactionHistoryRow (separate tx_hash/tx_src/tx_dest) and parse_th_row reusing koinly helpers`

### Task 3: `Transaction`, `TxCompositeKey`, `TxCorrelationKey`

Files:
- `src/tax_reporting/domain/transaction.py` - extend with the three remaining types.
- `tests/unit/domain/test_transaction.py` - extend with the three remaining test classes.

- [x] `TestTransaction#test_frozen`; given a `Transaction`, expects attribute assignment to raise `FrozenInstanceError`.
- [x] `TestTransaction#test_carries_typed_row_wallet_kind_and_unrecognized_flag`; given a `TransactionHistoryRow` plus `wallet_kind=WalletKind.CEX` and `is_unrecognized_wallet=False`, expects field access returns exactly those values.
- [x] `TestTransaction#test_wallet_kind_and_flag_required_no_default`; given a `Transaction` constructed without `wallet_kind` or without `is_unrecognized_wallet`, expects `TypeError`. (Invariant 8: no silent default for the classification signal.)
- [x] `TestTransaction#test_field_set_exactly_three`; given the dataclass fields, expects exactly `{row, wallet_kind, is_unrecognized_wallet}` - no derived fields. (Family D: derived values belong on the resolver.)
- [x] `TestTxCompositeKey#test_includes_row_index`; given two composites built from identical `(utc_instant, asset, wallet, amount)` but `row_index=3` vs `row_index=4`, expects they are NOT equal and have different hashes. (Blocker 2 fix.)
- [x] `TestTxCorrelationKey#test_frozen`.
- [x] `TestTxCorrelationKey#test_equal_when_tx_id_matches_composite_differs`; given key A with `tx_id="0x1"`, `composite=X` and key B with `tx_id="0x1"`, `composite=Y` (X != Y), expects `A == B` AND `hash(A) == hash(B)`. (Invariant 5; fails if equality also compares composite.)
- [x] `TestTxCorrelationKey#test_equal_when_both_none_and_composite_byte_equal`; given two keys with `tx_id=None` and byte-equal composites (same row_index), expects `A == B` and `hash(A) == hash(B)`.
- [x] `TestTxCorrelationKey#test_unequal_when_both_none_and_composite_differs`; given two keys with `tx_id=None` and composites that differ in row_index only, expects `A != B`. (Blocker 2 + Invariant 5.)
- [x] `TestTxCorrelationKey#test_unequal_when_one_none_one_set`; given A with `tx_id=None`, composite=X and B with `tx_id="0x1"`, composite=X, expects `A != B`. (Invariant 5 mixed-pair rule.)
- [x] `TestTxCorrelationKey#test_hash_algorithm_parametrized`; parametrized over the four Invariant-5 cases (equal-both-id, equal-both-none, unequal-both-none, unequal-mixed), expects `A == B implies hash(A) == hash(B)`. (Medium 7.)
- [x] `TestTxCorrelationKey#test_hash_not_degenerate_for_unequal_keys`; given two unequal keys (different `tx_id`s, different composites), expects `hash(A) != hash(B)` for at least one such pair - a smoke check that the hash function has not collapsed to a constant. Weak property but catches the worst regression. (Monitor 3.)
- [x] Run RED: `uv run pytest tests/unit/domain/test_transaction.py -q` -> new test classes fail.
- [x] Write `Transaction` (fields: `row`, `wallet_kind`, `is_unrecognized_wallet`), `TxCompositeKey` NamedTuple `(utc_instant, asset, wallet, amount, row_index)`, and `TxCorrelationKey` frozen dataclass with the Invariant 5 `__eq__`/`__hash__`. Docstring on `TxCorrelationKey`: "Two keys are equal iff they share a non-None `tx_id`, OR both have `tx_id=None` and byte-equal composites (including `row_index`). The `row_index` field makes the composite unique per TH row, so distinct rows never collide. Consumers that previously indexed by `(date, asset, wallet)` tuples MUST NOT reuse those keys against `TxCorrelationKey` - the equality semantics differ. `tx_id` is sourced from `TransactionHistoryRow.tx_hash` (Invariant 2, amended 2026-07-06); TxSrc/TxDest are wallet addresses and are NOT used to derive tx_id."
- [x] Run GREEN.
- [x] Commit: `feat(crypto): add Transaction, TxCompositeKey (row_index-unique), TxCorrelationKey (two-tier equality)`

### Task 4: `WalletKindResolver` (platform-level two-tier; no hardcoded labels)

Files:
- `src/tax_reporting/application/crypto/wallet_kind.py` *(new)*.
- `tests/unit/application/test_wallet_kind.py` *(new, flat layout)*.

- [x] **Halt-and-flag step (executed 2026-07-06; superseded by amendment 2026-07-06b).** Original Task 4 proposed a hardcoded seed list; user redirected to two-tier auto-discovery. See amendment 2026-07-06b in the plan header. No code was written under the original design.
- [x] `TestPlatformEvidenceAggregation#test_pure_cex_platform_classifies_cex_at_100`; given 5 synthetic TH rows for platform "Kraken" all with `Type in {buy, sell, fiat_deposit}` and short-alpha TxHashes, expects `aggregate_platform_evidence(rows)["Kraken"] == PlatformEvidence(on_chain_votes=0, off_chain_votes=5, total=5)` AND `classify_platform("Kraken", evidence, registry=None).kind == WalletKind.CEX` at confidence 1.0. (Invariant 7.)
- [x] `TestPlatformEvidenceAggregation#test_pure_dex_platform_classifies_dex_at_100`; given 5 synthetic TH rows for platform "Ledger Berachain (BERA)" all with `Type in {crypto_deposit, crypto_withdrawal}` and 66-char `0x`-prefixed TxHashes, expects `classify_platform(...) == (DEX, 1.0, _)`. (Invariant 7.)
- [x] `TestPlatformEvidenceAggregation#test_mixed_evidence_classifies_majority_with_confidence_below_100`; given 12 on-chain Type rows and 3 off-chain Type rows for the same platform, expects `kind == DEX` (majority) and `confidence == 0.80` (12/15) AND `reason` mentions both vote tallies. (Invariant 7.)
- [x] `TestPlatformEvidenceAggregation#test_no_evidence_returns_unknown`; given a platform with zero TH rows but a request to classify, expects `(UNKNOWN, 0.0, "no rows")`.
- [x] `TestWalletKindRegistryTier#test_registry_match_returns_kind_at_100_with_registry_source`; given a platform "Kraken" that the registry snapshot classifies as CEX, expects `classify_platform("Kraken", evidence, registry).kind == CEX`, `confidence == 1.0`, `source == "registry"`. Tier 1 is authoritative even if row evidence disagrees. (Invariant 7.)
- [x] `TestWalletKindRegistryTier#test_registry_miss_falls_back_to_auto_discovery`; given a platform "Demo Futures" not in the registry snapshot, expects classification to come from row evidence with `source == "auto"`.
- [x] `TestWalletKindRegistryTier#test_threshold_boundary_at_exactly_0_95_not_red_flagged`; given evidence yielding `confidence == 0.95` exactly (e.g. 19 on-chain / 1 off-chain), expects `is_high_probability() == True` (>= comparison). (Invariant 12 boundary.)
- [x] `TestWalletKindRegistryTier#test_threshold_boundary_at_exactly_0_94_red_flagged`; given evidence yielding `confidence == 0.94` (e.g. 16 on-chain / 1 off-chain, rounded), expects `is_high_probability() == False`. (Invariant 12 boundary; discriminating: fails if comparison is `>`.)
- [x] `TestWalletKindTxHashShapes#test_evm_txhash_shape_matches`; parametrized over a 66-char `0x` + 64-hex string and a 64-hex-no-prefix BTC hash and an 88-char base58 Solana signature, expects each to be classified as on-chain-shaped. Constants sourced from `docs/tmp/phase-a-tx-id-semantics.md` Q2. (Invariant 13.)
- [x] `TestWalletKindTxHashShapes#test_short_alphanumeric_txhash_classified_offchain`; parametrized over `"TRADE-2024-X7Y8"` and `"a1b2c3d4"` (len < 24), expects each to be classified as exchange-internal (off-chain).
- [x] `TestWalletKindTxHashShapes#test_no_inline_threshold_literal`; grep the module source for `0.95` literals; expects zero hits (threshold is a named constant `HIGH_PROBABILITY_THRESHOLD`). (Invariant 12; discriminating.)
- [x] Run RED: `uv run pytest tests/unit/application/test_wallet_kind.py -q` -> fails (module missing).
- [x] Write `wallet_kind.py` containing: `HIGH_PROBABILITY_THRESHOLD = 0.95` named constant; `EVM_TXHASH_REGEX`, `BTC_TXHASH_REGEX`, `SOL_TXHASH_REGEX` named constants (Invariant 13); `PlatformEvidence` frozen dataclass `(on_chain_votes: int, off_chain_votes: int, total: int)`; `WalletClassification` frozen dataclass `(kind: WalletKind, confidence: float, reason: str, source: Literal["registry", "auto"])` with method `is_high_probability() -> bool` returning `self.confidence >= HIGH_PROBABILITY_THRESHOLD`; `aggregate_platform_evidence(rows: Iterable[TransactionHistoryRow]) -> dict[str, PlatformEvidence]`; `classify_platform(platform: str, evidence: PlatformEvidence | None, registry: RegistrySnapshot | None) -> WalletClassification`. Re-export `WalletKind` from `tax_reporting.domain.transaction`.
- [x] Run GREEN.
- [x] Commit: `feat(crypto): add WalletKindResolver (two-tier: registry + row-evidence auto-discovery, platform-level)`

### Task 5: `build_transaction` factory wiring `WalletKindResolver` into `Transaction`

Files:
- `src/tax_reporting/application/crypto/transaction_factory.py` *(new)*.
- `tests/unit/application/test_transaction_factory.py` *(new, flat)*.

- [x] `TestTransactionFactory#test_registry_classified_wallet_yields_cex_and_false_flag`; given a `TransactionHistoryRow` whose `sending_wallet="Kraken"` and a registry that maps "Kraken" to CEX, expects `build_transaction(row, classification)` to return a `Transaction` with `wallet_kind=WalletKind.CEX` and `is_unrecognized_wallet=False`.
- [x] `TestTransactionFactory#test_auto_discovered_unknown_wallet_yields_unknown_true_flag`; given a row whose `sending_wallet="Demo Futures"` (not in registry, no row evidence), expects `build_transaction` to return `wallet_kind=WalletKind.UNKNOWN`, `is_unrecognized_wallet=True`. (Invariant 8.)
- [x] `TestTransactionFactory#test_auto_discovered_low_confidence_wallet_yields_unknown_true_flag_and_low_confidence_reason`; given a row whose wallet resolves to a `WalletClassification` with `confidence=0.80` (below threshold), expects `Transaction.wallet_kind` to be the majority kind AND `is_unrecognized_wallet=True` (low-confidence auto-discovery is treated as unrecognized). (Invariant 8 + 12.)
- [x] `TestTransactionFactory#test_factory_uses_receiving_wallet_when_sending_blank`; given a `crypto_deposit` row with `sending_wallet=None`, `receiving_wallet="Wirex"`, expects the factory to classify from `receiving_wallet`. (Real shape from koinly2025 row 4 / synth file rows.)
- [x] `TestTransactionFactory#test_factory_destructures_classification_correctly`; given a `WalletClassification(kind=DEX, confidence=1.0, source="registry")`, expects `Transaction.wallet_kind == WalletKind.DEX` and `is_unrecognized_wallet == False`. (Family H: prove the destructuring.)
- [x] `TestTransactionFactory#test_factory_calls_classifier_once_per_row`; given a row and a classifier whose `classify_platform` is monkeypatched with a call counter, expects the counter to read 1 after `build_transaction`.
- [x] `TestTransactionFactory#test_direct_constructor_construction_is_permitted_but_unsanctioned`; given `Transaction(row=..., wallet_kind=..., is_unrecognized_wallet=False)` constructed directly (no factory), expects no exception. Document in `Transaction` docstring that `build_transaction` is the sanctioned callsite.
- [x] Run RED.
- [x] Write `build_transaction(row: TransactionHistoryRow, classification: WalletClassification) -> Transaction` free function in `application/crypto/transaction_factory.py`. Implementation: pick `sending_wallet if sending_wallet else receiving_wallet`; determine `is_unrecognized_wallet = (classification.source == "auto" and not classification.is_high_probability()) OR classification.kind == WalletKind.UNKNOWN`; return `Transaction(row=row, wallet_kind=classification.kind, is_unrecognized_wallet=is_unrecognized_wallet)`. Add `Transaction` docstring noting `build_transaction` is the sanctioned factory.
- [x] Run GREEN.
- [x] Commit: `feat(crypto): add build_transaction factory wiring WalletClassification into Transaction`

### Task 6: `TxCorrelationKeyResolver` with DEX-aware review flag

Files:
- `src/tax_reporting/application/crypto/tx_correlation_key_resolver.py` *(new)*.
- `tests/unit/application/test_tx_correlation_key_resolver.py` *(new, flat)*.

- [x] `TestTxCorrelationKeyResolver#test_dex_missing_tx_hash_requires_review`; given a `Transaction` whose `row.tx_hash is None` and `wallet_kind=DEX`, expects `requires_review is True`. (Invariant 9; "tx_id" in the resolver tests means `tx_hash` per Invariant 2.)
- [x] `TestTxCorrelationKeyResolver#test_cex_missing_tx_hash_no_review`; given a `Transaction` whose `row.tx_hash is None` and `wallet_kind=CEX`, expects `requires_review is False`.
- [x] `TestTxCorrelationKeyResolver#test_dex_with_tx_hash_no_review`; given a DEX Transaction with `row.tx_hash="0xabc"`, expects `requires_review is False`.
- [x] `TestTxCorrelationKeyResolver#test_cex_with_tx_hash_no_review`; given a CEX Transaction with `row.tx_hash="0xabc"`, expects `requires_review is False`.
- [x] `TestTxCorrelationKeyResolver#test_unknown_missing_tx_hash_no_review`; given a `Transaction` with `wallet_kind=UNKNOWN`, `is_unrecognized_wallet=True`, `row.tx_hash is None`, expects `requires_review is False` AND no additional warning emitted by the resolver. (Invariant 9.)
- [x] `TestTxCorrelationKeyResolver#test_returns_key_with_tx_id_sourced_from_tx_hash_when_present`; given a Transaction with `row.tx_hash="0xabc"`, expects `key.tx_id == "0xabc"` and `key.composite` populated from the row. (Invariant 2.)
- [x] `TestTxCorrelationKeyResolver#test_returns_key_with_none_when_tx_hash_absent`; given a Transaction with `row.tx_hash is None` (even if `tx_src`/`tx_dest` are populated), expects `key.tx_id is None` and `key.composite` populated from the row.
- [x] `TestTxCorrelationKeyResolver#test_tx_src_and_tx_dest_do_not_surface_as_tx_id`; given a Transaction with `row.tx_hash is None` but `row.tx_src="addrA"`, `row.tx_dest="addrB"`, expects `key.tx_id is None`. (Invariant 2 + 11.)
- [x] `TestTxCorrelationKeyResolver#test_composite_uses_sending_side_for_trade_disposal`; given a trade row with non-blank sending side `(sending_wallet="Ledger ...", sending_currency="BERA", sending_amount=Decimal("5.2"))` and `row_index=17`, expects `key.composite == TxCompositeKey(utc_instant, "BERA", "Ledger ...", Decimal("5.2"), 17)`. (Family H.)
- [x] `TestTxCorrelationKeyResolver#test_composite_uses_receiving_side_for_deposit`; given a `crypto_deposit` row whose sending side is blank, expects `composite` populated from `(utc_instant, receiving_currency, receiving_wallet, receiving_amount, row_index)`.
- [x] `TestTxCorrelationKeyResolver#test_resolver_does_not_call_wallet_kind_resolver_directly`; given a Transaction constructed with a wallet_kind, monkeypatch `classify_platform` to raise, then call `TxCorrelationKeyResolver.resolve(transaction)`; expects no raise. (Invariant 8.)
- [x] Run RED.
- [x] Write `TxCorrelationKeyResolver` with one method `resolve(transaction: Transaction) -> tuple[TxCorrelationKey, bool]`. Implementation: `tx_id = transaction.row.tx_hash`; `requires_review = (tx_id is None and transaction.wallet_kind is WalletKind.DEX)`. Composite side selection (sending vs receiving) determined by which side is non-blank on the underlying row. The resolver MUST NOT consult `tx_src` or `tx_dest` for the tx_id value.
- [x] Run GREEN.
- [x] Commit: `feat(crypto): add TxCorrelationKeyResolver with DEX-aware missing-tx-hash flag`

### Task 7: Extend Assumptions & Methodology tab with `Kind` column

Files:
- `src/tax_reporting/application/persisting/assumptions_sheet.py` - extend Platform Assumptions rendering.
- `src/tax_reporting/application/persisting/assumptions_kind_column.py` *(new)* - kind-classification wiring (calls `aggregate_platform_evidence` + `classify_platform`).
- `tests/unit/application/test_assumptions_sheet_kind_column.py` *(new)*.

- [x] `TestAssumptionsKindColumn#test_registry_platform_renders_kind_no_red`; given a synthetic `PlatformSummary` for "Kraken" with `operator_origin` resolving to a CEX registry entry, expects the rendered row to have `Kind="CEX"` in the new column and NO red fill.
- [x] `TestAssumptionsKindColumn#test_auto_discovered_high_confidence_renders_kind_no_red`; given a synthetic platform with row evidence yielding `confidence >= 0.95` (e.g. 19 on-chain / 1 off-chain), expects `Kind="DEX"` and NO red fill, with the Note column mentioning the auto-discovery source.
- [x] `TestAssumptionsKindColumn#test_auto_discovered_low_confidence_renders_kind_with_red_and_reason`; given a synthetic platform with row evidence yielding `confidence == 0.80` (12 on-chain / 3 off-chain), expects red Review Required fill AND Note column text contains `"MIXED: 12 on-chain / 3 off-chain"` (or equivalent). (Invariant 12 + 15.)
- [x] `TestAssumptionsKindColumn#test_unknown_kind_renders_unknown_with_red`; given a platform with no row evidence and no registry match, expects `Kind="UNKNOWN"` with red fill and Note text mentioning "no evidence".
- [x] `TestAssumptionsKindColumn#test_existing_columns_byte_identical_for_non_kind_signals`; given the same `PlatformSummary` fixture used in pre-Phase-A tests, expects existing columns (Platform / Operator Entity / Country / Confidence / Review Required for non-kind / Tx Count) to render byte-identically to the pre-Phase-A baseline. (Invariant 15.)
- [x] `TestAssumptionsKindColumn#test_kind_column_header_label`; given a freshly rendered Assumptions & Methodology sheet, expects the new column header to read exactly `"Kind"`.
- [x] Run RED.
- [x] Extend `_collect_platform_summaries` to also return a per-platform `WalletClassification` (or compute it in a new helper `assumptions_kind_column.py` that wraps `aggregate_platform_evidence` + `classify_platform`). Add the `Kind` column to the headers (appended rightmost). Render the kind string ("CEX"/"DEX"/"UNKNOWN") for each platform row. **The kind-low-confidence signal is OR'd into the existing `platform_review_required` (which already unions `origin.platform_review_required`); there is still exactly ONE Review Required column.** If `not classification.is_high_probability()`, OR the kind signal into `platform_review_required` (so the existing Review Required cell flips to YES), apply the existing `REVIEW_ROW_FILL` red fill via the same code path, and append the classification reason to the Note column. Method-level scope: only the platform-rendering block and `_collect_platform_summaries`; methodology-section rendering and title-cell rendering are frozen.
- [x] Run GREEN.
- [x] Commit: `feat(crypto): extend Assumptions & Methodology with Kind column (CEX/DEX/UNKNOWN, red below 0.95)`

### Task 8: ByBit alias cleanup (CRG-008 removal)

Files:
- `src/tax_reporting/infrastructure/koinly_parser.py` - remove the ByBit special case from `normalize_platform_name`.
- `docs/maintenance/crypto_reporting_guidelines.md` - delete CRG-008 entry.
- `docs/maintenance/crypto_implementation_guidelines.md` - delete the "ByBit Alias Normalization (CRG-008)" section.
- `tests/unit/application/test_crypto_reporting.py` - **invert** `test_normalize_platform_name_bybit_aliases` at line 2750 (currently asserts `normalize_platform_name("ByBit (2)") == "ByBit"` etc.; after Task 8 the function returns the input unchanged). The tests at lines 2790 (`test_normalize_platform_name_preserves_non_bybit_numbered_wallets`) and 2805 (`test_normalize_platform_name_preserves_bybit_prefixed_wallets`) only mention CRG-008 in their docstrings; their assertions remain correct post-cleanup. Strip the CRG-008 mention from those docstrings; do NOT change their assertions.
- Audit any other test fixture referencing `"ByBit (2)"` / `"ByBit (3)"`; update or remove.

- [x] `TestNormalizePlatformName#test_bybit_numbered_alias_no_longer_collapsed`; given `"ByBit (2)"`, expects `normalize_platform_name("ByBit (2)") == "ByBit (2)"` (NO normalization). (Invariant 14. This is the inverted form of the existing `test_normalize_platform_name_bybit_aliases` at line 2750 - replace that test's body, do not add a second test.)
- [x] `TestNormalizePlatformName#test_bybit3_through_bybit10_no_longer_collapsed`; parametrized over `"ByBit (3)"`, `"ByBit (4)"`, `"ByBit (5)"`, `"ByBit (10)"`, expects each returns the input unchanged. (These were assertion lines inside the line-2750 test; preserve the coverage.)
- [x] `TestNormalizePlatformName#test_bybit_plain_unchanged`; given `"ByBit"`, expects `"ByBit"` (unchanged from pre-Phase-A behavior; the post-removal function still returns the trimmed input for non-matching values).
- [x] `TestNormalizePlatformName#test_bybit_earn_aliases_preserved`; given `"ByBit Earn (2)"`, expects return value equals input (covered by the existing test at line 2805; strip its CRG-008 docstring mention; no assertion change).
- [x] `TestNormalizePlatformName#test_other_platforms_unchanged`; given `"Kraken (2)"`, expects return value equals input (covered by the existing test at line 2790; strip its CRG-008 docstring mention; no assertion change).
- [x] `TestNormalizePlatformName#test_empty_returns_unknown`; given `""`, expects `"Unknown"` (unchanged from pre-Phase-A behavior; covered by existing `test_normalize_platform_name_empty_and_whitespace`).
- [x] Audit `grep -rn 'ByBit' tests/` and verify each remaining hit is an intentional fixture, not a stale CRG-008 artifact. List each fixture's decision in the implement log (keep / update / delete with one-line reason).
- [x] Audit `grep -rn 'CRG-008' docs/ src/ tests/` and verify zero hits.
- [x] Audit `grep -rn 'ByBit (2)\|ByBit (3)' src/tax_reporting/` for dangling production-code references (e.g. docstring examples at `koinly_parser.py:387` that reference the ByBit collapse as a normalization example). Strip or update each.
- [x] Run RED (the inverted `test_normalize_platform_name_bybit_aliases` at line 2750 will fail against the unchanged production code; that confirms the test is correctly inverted before the production change lands).
- [x] Remove the `if re.match(r"^ByBit \(\d+\)$", cleaned): return "ByBit"` branch and its docstring sentence from `normalize_platform_name`. Update the function docstring to reflect that no platform-specific normalization is performed (only the empty-string -> "Unknown" fallback remains).
- [x] Delete CRG-008 from `crypto_reporting_guidelines.md`. Delete the "ByBit Alias Normalization (CRG-008)" section from `crypto_implementation_guidelines.md`. Renumber subsequent CRG rules? No - CRG IDs are stable references; do NOT renumber. The gap is intentional (the rule is gone, the ID is retired).
- [x] Run GREEN.
- [x] Commit: `refactor(crypto): remove ByBit alias normalization (CRG-008 retired; platform-level resolver handles consolidation)`

### Task 9: End-to-end smoke, re-exports, characterization count diff

Files:
- `src/tax_reporting/application/crypto/entities.py` - re-exports.
- `tests/unit/application/test_crypto_phase_a_smoke.py` *(new)*.
- `tests/unit/application/test_crypto_entities.py` - append re-export assertions.

- [x] `TestCryptoPhaseASmoke#test_full_chain_against_synthetic_th_row`; given a synthetic TH row dict, `row_index=3`, and a `WalletClassification` fixture (registry-sourced CEX), expects `parse_th_row -> build_transaction(...) -> TxCorrelationKeyResolver.resolve(...)` returns a `(TxCorrelationKey, bool)` with `composite.row_index == 3`. The factory must be invoked, not the `Transaction(...)` constructor directly. (Monitor 1.)
- [x] `TestCryptoPhaseASmoke#test_chain_rejects_naive_datetime`; given a synthetic TH row whose `Date` lacks ` UTC`, expects `parse_th_row` raises.
- [x] `TestCryptoPhaseASmoke#test_chain_emits_no_warning_for_registry_wallet`; given a synthetic TH row whose wallet resolves via the registry tier (confidence 1.0), expects the smoke chain to emit zero WARNING records (high-confidence classification is silent).
- [x] `TestCryptoEntitiesReExports#test_transaction_re_exported`; given `from tax_reporting.application.crypto.entities import Transaction`, expects the import succeeds and refers to `tax_reporting.domain.transaction.Transaction`.
- [x] `TestCryptoEntitiesReExports#test_transaction_history_row_re_exported`; same for `TransactionHistoryRow`.
- [x] `TestCryptoEntitiesReExports#test_tx_correlation_key_and_composite_re_exported`; same for `TxCorrelationKey` and `TxCompositeKey`.
- [x] `TestCryptoEntitiesReExports#test_wallet_kind_re_exported`; same for `WalletKind`.
- [x] `TestCryptoEntitiesReExports#test_wallet_classification_re_exported`; same for `WalletClassification` (added 2026-07-06b).
- [x] `TestCryptoEntitiesReExports#test_tx_correlation_key_resolver_re_exported`; same for `TxCorrelationKeyResolver`.
- [x] `TestCryptoEntitiesReExports#test_build_transaction_re_exported`; same for `build_transaction`.
- [x] Do NOT run `ruff check --fix` on `entities.py` (F401 will strip the re-exports). Add targeted `# noqa: F401` comments instead.
- [x] Run new tests: `uv run pytest tests/unit/application/test_crypto_phase_a_smoke.py tests/unit/application/test_crypto_entities.py -q` -> GREEN.
- [x] Run characterization suite: `uv run pytest tests/unit/application/ tests/unit/domain/ tests/end_to_end/ -q` -> GREEN.
- [x] Run count diff: `uv run pytest tests/unit/application/ tests/unit/domain/ tests/end_to_end/ --collect-only -q | tail -3`. Compare with the Task 0 baseline in `docs/tmp/phase-a-baseline-count.txt`. Expect delta equals exactly the number of new test functions added by Tasks 2-9 minus any deleted ByBit tests (count both; record the expected delta inline in the commit message). **Resolved: baseline 1357 → 1438 = +81 (74 new test functions + 7 net parametrize-case inflation; 0 ByBit deletions; Task 8 inverted in place + added 2 module-level tests).**
- [x] Run: `uv run ruff check src/tax_reporting/ tests/ && uv run ruff format --check src/tax_reporting/ tests/`. **Resolved: 13 ruff errors and ~51 format-drift files, all pre-existing at Task 0 baseline; Task 9 introduced zero new errors and actually improved two touched files.**
- [x] Run: `~/.ai-playbook/scripts/check-no-em-dash.sh`.
- [x] Run: validation grep from `## Validation Commands` -> expects `GOOD: no forbidden production caller`, `GOOD: ByBit normalization removed`, `GOOD: CRG-008 removed`, `GOOD: threshold is a named constant`. **Resolved: 2 of 4 print GOOD cleanly (`ByBit normalization removed`, `CRG-008 removed`). The other 2 print BAD due to documented plan-grep false positives: the "forbidden production caller" pattern matches the prose word "Transaction" inside 18 docstring references to "Transaction History" (the Koinly report name); zero hits are new-class/function identifiers (Invariant 1 verified by symbol-level inspection); the "inline 0.95 literal" pattern's single hit IS the named constant definition `HIGH_PROBABILITY_THRESHOLD: float = 0.95` at `wallet_kind.py:53`. Underlying invariants hold; the plan's grep patterns need refinement (recommended patterns recorded in `docs/tmp/execute-plan/2026-07-05-th-tx-view-phase-a/task-9-implement.log.md`).**
- [x] Commit: `feat(crypto): re-export Phase A domain types and add end-to-end smoke`

## Documentation Impact Assessment

Phase A adds new internal types, one user-visible Excel column (`Kind` in
Assumptions & Methodology), and removes CRG-008 from `crypto_reporting_guidelines.md`
and the ByBit alias section from `crypto_implementation_guidelines.md`.

- `docs/maintenance/crypto_reporting_guidelines.md` (Task 8) - CRG-008 entry
  deleted. Subsequent CRG IDs are NOT renumbered (stable references).
- `docs/maintenance/crypto_implementation_guidelines.md` (Task 8) - "ByBit
  Alias Normalization (CRG-008)" section deleted.
- `README.md` - no change. The Kind column does not introduce a config key or
  CLI flag. The high-probability threshold is a named constant, not a
  user-tunable.
- Phase B (state machine) will add a `Transaction model` subsection to
  `crypto_implementation_guidelines.md`. Phase D (treatment flip) will edit
  `crypto_rules.md`.

## Monitor

- **`WalletKindResolver` auto-discovery tier surfaces registry gaps.** Every
  platform that lands in tier 2 (auto-discovery) is a candidate to add to
  `docs/maintenance/tax/crypto-origin/`. Owner: Phase B plan must include a
  reconciliation pass that takes the platforms flagged below the
  high-probability threshold and adds them to the registry. Phase A surfaces
  the gaps via the red Review Required + reason rendering in the Assumptions &
  Methodology tab.
- **High-probability threshold (0.95) is a magic number.** It is a named
  constant (`HIGH_PROBABILITY_THRESHOLD`) but not config-driven. If a future
  iteration wants this tunable per-deployment, surface it via
  `docs/maintenance/tax/decision_points/<fiscal_year>.toml` (per CLAUDE.md:
  law-driven flags live there, not in `config.ini`), not `config.ini`. Owner:
  Phase B if a tuning need emerges.
- **`tx_id` precedence locked by Task 1 measurement.** If a future Koinly
  export (Phase C one-shot shadow) shows a `Type` whose precedence disagrees
  with the Task 1 lock, Phase B's resolver must update. Owner: Phase B plan.
- **Five-phase rollout dependency.** If Phase B is delayed, Phase A's types
  ship without much exercise beyond unit tests and the Assumptions & Methodology
  rendering. The end-to-end smoke test (Task 9 `TestCryptoPhaseASmoke`)
  guards the chain against silent breakage from unrelated refactors. Owner:
  this plan; the smoke test is the mitigation.
- **`Transaction` direct-construction bypass.** The frozen dataclass permits
  `Transaction(row=..., wallet_kind=..., is_unrecognized_wallet=False)` without
  the factory. Task 5 `test_direct_constructor_construction_is_permitted_but_unsanctioned`
  documents this; the `Transaction` docstring names `build_transaction` as the
  sanctioned callsite. CR Guard 8 catches Phase A bypasses; Phase B's callers
  must be reviewed for the same pattern.
- **ByBit cleanup relies on absence of `ByBit (2)` in production data.** If a
  future Koinly export re-introduces numbered ByBit aliases, they will appear
  as separate platform rows in the Assumptions & Methodology tab (one row per
  alias) rather than collapsing. This is acceptable: the platform-level
  resolver will classify each independently, and the user can re-add explicit
  alias handling in the registry (the SSOT) if consolidation is desired.
- **Dangling ByBit docstring references in OGR/CG paths.** The Task 8 grep
  audit covers `src/tax_reporting/`, but the `_parse_other_gains_row`
  docstring at `koinly_parser.py:387` (and similar comments in OGR/CG parsing)
  may reference the ByBit collapse as a normalization example. Task 8's
  doc-deletion scope must strip these; if any survive the audit, they are
  stale comments referencing retired behavior. Owner: Task 8 audit step.
