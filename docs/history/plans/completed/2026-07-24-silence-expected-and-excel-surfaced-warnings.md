# Plan: Silence expected-behavior and Excel-surfaced crypto warnings

Predecessor: `docs/history/plans/completed/2026-07-23-group-leftover-crypto-warnings.md`
(patterns A–L). This plan extends the convention to the remaining sites the
prior plan left at WARNING because they were either (a) "expected behavior" with
no anomaly, or (b) anomalies whose audit signal already lives in the Excel
review list.

Verified-bucket trace: `docs/tmp/plan-requirements-silence-expected-and-excel-surfaced-warnings.md`
(data-flow re-verification of every site through `cross_asset → matching →
CryptoFifoRealization → CryptoCapitalGainEntry.review_reason`).

Relevant guideline: `docs/maintenance/project-guidelines.md` rule #7 (extended
by Task 9). caplog `at_level` pitfalls: `docs/maintenance/development_lessons.md`
(the 2026-07-22 configurable-log-level lesson family: `caplog.at_level(DEBUG)`
bypasses `configure_application_logging`; `at_level(WARNING)` filters INFO/DEBUG
before capture) and lesson #69 (sweep `tests/` for `at_level(WARNING)` assertions).

Plan review: `docs/history/reviews/2026-07-24-plan-review-silence-expected-and-excel-surfaced-warnings-r1.md` (r1: 1 Blocker + 6 Medium, incorporated) · `…-r2.md` (r2: 0 Blocker + 1 Medium + 2 Low + 1 Monitor, incorporated) · `…-r3.md` (r3: ready=yes). **AMENDED post-r3** with the native-gas split (Tasks 1–3 replace the flat INFO demotion; new Invariant #8); substantive revision resets the review counter, and the next review is r1 of the amended plan.

## Terms

- **Bucket A (EXPECTED_BEHAVIOR):** a warning site describing correct tax
  treatment with no anomaly and no downstream `review_required` flag. Target
  level: `logger.info(...)` (or `logger.debug(...)` when fully expected, see
  Bucket A-split below). Example: third-currency fee correctly folded into
  `AcquisitionContext.fee_eur` (consumed into `cost_eur` at `matching.py:189`).
- **Bucket A-split (native-gas vs anomalous third-token fee):** the third-
  currency-fee site (`_emitters.py:65/:195`) is NOT uniformly expected. It
  applies a **unified two-model rule** (no explicit CEX/DEX branch needed):
  a third-currency fee is **expected** (no warning) when EITHER model holds:
  - **CEX model (existing leg-check, kept):** `fee_currency in (sent_currency,
    received_currency)`; CEX deducts the fee from a trade leg (verified: ByBit
    rows take the fee in the received currency).
  - **DEX model (new native-gas check):** `fee_currency == native_gas_asset` of
    `_derive_chain(wallet)` → `_CHAIN_NATIVE_FEE_ASSET[chain]`; DEX pays gas in
    the chain's native token (verified: Ethereum swaps pay ETH, BSC pays BNB,
    Berachain pays BERA).
  It is **anomalous** (STAYS `logger.warning`) when the fee is **neither** a leg
  **nor** the chain's native gas (e.g. USDC / governance-token fee). When the
  chain is `"Unknown"` → fail-safe STAYS WARNING.
  This split exists because asset-keyed matching is unsafe: ETH/BNB/MATIC are
  native gas on one chain but regular bridged tokens on others, so the emitter
  must derive the chain per-row. Empirically validated against the real dataset
  (342 exchanges, 61 third-currency fees): only **19 have EUR value > 0**
  (6 ETH on Ethereum + 4 ETH on zkSync ERA + 9 BNB on Binance Smart Chain);
  ALL 19 are native-gas and are silenced by the new native-gas branch. The
  remaining 42 third-currency fees have EUR value 0.00 (17 BERA on Berachain +
  25 Kraken `FEE` rows) and are **already** suppressed by the existing
  `fee_value > ZERO` guard at `_emitters.py:61/191`; they never reach the
  warning today; the native-gas branch is defense-in-depth for them. Zero
  genuine CEX third-currency fees with EUR value exist. (Numbers verified with
  the production `parse_koinly_decimal`, which handles the European
  comma-decimal format `0,44`→0.44.) See Invariant #8 and Tasks 1–3.
- **Bucket B (HAS_EXCEL_SURFACE):** a warning site whose anomaly sets
  `review_required=True` + `review_reason` on an entry whose **data type renders
  a review column in the Excel report**; i.e. `CryptoFifoRealization` /
  `CryptoCapitalGainEntry` / `CryptoReviewEntry` / `DerivativesPnLEntry` (these
  types own a rendered review cell by schema). Classification is by the entry's
  **schema**, not by runtime `review_required` values (a blank cell for a clean
  row still counts). An `AcquisitionContext.review_reason` is an **intermediate**
  application field, NOT a rendered schema field; it only reaches Excel IF the
  acquisition is later consumed by a taxable disposal. Sites that set the flag
  only on an intermediate (e.g. a deposit lot that may never be disposed) are
  Bucket C unless every such row is guaranteed to produce a realized entry.
  Target: per-row `logger.debug(...)` + ONE aggregate `logger.info(...)`. The
  Excel cell is the canonical audit surface.
- **Bucket C (DEVELOPER_ACTIONABLE):** a warning site describing data loss or
  anomaly with NO Excel surface. Stays `logger.warning(...)`. Per-row Bucket-C
  sites inside loops get grouped (per-row DEBUG + ONE aggregate WARNING) to
  avoid flooding while preserving the warning-level signal.
- **`_emit_flagged_summary`**: shared aggregate emitter at
  `src/tax_reporting/application/crypto/fifo_helpers.py:219` (patterns J/K).
  New aggregates reuse it where the shape fits.
- **`_CHAIN_NATIVE_FEE_ASSET`**: new module-level frozen dict constant in
  `src/tax_reporting/application/crypto/chain_derivation.py` mapping each known
  chain to its native gas-token ticker (Ethereum→ETH, Solana→SOL, Sui→SUI,
  Binance Smart Chain→BNB, Berachain→BERA, Polygon→MATIC, TON→TON, Aptos→APT,
  Filecoin→FIL, and the EVM L2s Arbitrum/BASE/zkSync ERA/Mantle/Starknet→ETH).
  Native gas is a protocol-level fact (not jurisdiction/year-dependent law), so
  it lives as a constant next to `_KNOWN_CHAINS`, not in the decision-points TOML.
- **`_derive_chain(wallet)`**: existing function (`chain_derivation.py:47`)
  returning a canonical chain name or `"Unknown"`. Already used at
  `fifo_helpers.py:443` and `crypto_reporting.py:874`. Tasks 1–3 reuse it.
- **Pattern J / K / F**: existing grouping patterns from the predecessor plan
  (cross-asset deferred, transfer carry-over, unmatched-taxable). See rule #7.

## Gist & Examples

The predecessor plan collapsed 4 high-volume per-row WARNING patterns (I/J/K/L)
into per-row DEBUG + ONE aggregate WARNING. A real `uv run tax-reporting` run
still prints **26 WARNING lines**. Two further classes are console noise:

1. **Expected behavior.** `Row 1292: exchange FARMDWBTCV3->WBTC has fee in third
   currency ETH (0.650000 EUR); adding to WBTC acquisition cost basis`. Paying
   gas in a third token is normal network behavior; the fee is correctly folded
   into the acquisition's `fee_eur` and later into the realization's `cost_eur`
   (`matching.py:189`). No anomaly, no review flag. This should not be WARNING.

2. **Anomalies already on the export.** `Flagged 601 all-zero capital gains
   row(s) for review (...); see DEBUG log and review list for details`. Each of
   those 601 rows sets `review_required=True` + `review_reason` and renders as a
   "YES:" cell in the Crypto Gains sheet the user receives. The developer
   running the tool sees a console duplicate of a signal the user already has.

**After:** a default `LOG_LEVEL=WARNING` run shows only the **Bucket C** set
(~8 lines: token-origin disagreements, duplicate-tx_key drops, derivatives/fee
dedup summaries, untagged-whitelist removal, sub-1-EUR filter, parse-error
drops). Bucket-A/B detail is reachable at `LOG_LEVEL=INFO`; per-row at DEBUG in
`logs/tax-reporting.log`.

**Example before/after (the headline case: third-currency fee, native-gas split):**
```
# BEFORE (console, default WARNING): Row 1292, an Ethereum DEX swap paying gas in ETH:
WARNING - Row 1292: exchange FARMDWBTCV3->WBTC has fee in third currency ETH (0.650000 EUR); adding to WBTC acquisition cost basis
# AFTER (native-gas branch, fee_currency == _CHAIN_NATIVE_FEE_ASSET["Ethereum"] == "ETH"):
# (silent at WARNING; DEBUG in the file log; ETH gas on Ethereum is expected)
# AFTER (anomalous branch, e.g. fee in USDC or a governance token, or unknown chain):
WARNING - Row N: exchange A->B has fee in third currency USDC (...); adding to B acquisition cost basis
# (STAYS WARNING: neither a trade leg nor the chain's native gas)
```

**Example before/after (Excel-surfaced anomaly):**
```
# BEFORE (console):
WARNING - Flagged 601 all-zero capital gains row(s) for review (...); see DEBUG log and review list for details
# AFTER (console):
# (silent at WARNING; the 601 rows still render "YES:" in the Crypto Gains sheet;
#  the aggregate summary appears at INFO)
```

### Verified bucket map (from data-flow re-verification)

| # | Site | Bucket | Downstream flag evidence | Action |
|---|------|--------|--------------------------|--------|
| 1 | `_emitters.py:65` third-currency fee (deferred) | A-split | `matching.py:189` (fee in cost) | native-gas → DEBUG; anomalous/unknown → STAYS WARNING (Tasks 1–3) |
| 2 | `_emitters.py:195` third-currency fee (received-only) | A-split | `matching.py:189` | native-gas → DEBUG; anomalous/unknown → STAYS WARNING (Tasks 1–3) |
| 3 | `_emitters.py:177` empty Sent Cost Basis | B | `matching.py:199-200,206` | per-row DEBUG + NEW aggregate INFO |
| 4 | `_emitters.py:339` unknown receiver platform (phantom) | B | `fifo_helpers.py:74-78` (`_apply_phantom_lot_flags`) | → INFO |
| 5 | `matching.py:134` epoch acquisition date | B | `matching.py:198-204` (`or is_epoch_acq`) | per-row DEBUG + NEW aggregate INFO |
| 6 | `matching.py:141` epoch disposal date | B | `matching.py:198-204` (`or is_epoch_con`) | per-row DEBUG + NEW aggregate INFO |
| 7 | `matching.py:175` deferred acquisition consumed | B | `matching.py:198-204` (`or is_deferred_acq`) | per-row DEBUG + aggregate INFO (reachable in prod via the unresolved-deferred branch; see Invariant #2) |
| 8 | `matching.py:58` non-positive acquisition skipped | C | none (`continue` drops it) | per-row DEBUG + NEW aggregate WARNING |
| 9 | `matching.py:244` negative consumption skipped | C | none (`return` drops it) | per-row DEBUG + NEW aggregate WARNING |
| 10 | `transfer.py:48` cyclic transfer dependency | B | `transfer.py:163-169` | → INFO |
| 11 | `cross_asset.py:48` cyclic swap dependency | B | `cross_asset.py:218,241,259` | → INFO |

**Aggregate-only flips (Bucket B, existing aggregate → INFO):**
`crypto_reporting.py:900` (FIFO rebuild buffered), `:922` (all-zero flagged);
`matching.py:84` (pool exhausted non-taxable); `fifo_helpers.py:378`
(pool-exhausted taxable); J/K aggregates via `_emit_flagged_summary`
(`fifo_helpers.py:390,397`); `fee_filter.py:643` (suspect fees surfaced);
`aggregation.py:425` (missing/epoch acquisition dates).

**Bucket C (STAY WARNING, untouched):** `token_origin.py` disagreements ×2;
`parsing.py:369` duplicate-tx_key drops; `parsing.py:290` zero-NV deposits
(flag set on `AcquisitionContext`, an intermediate, not a rendered entry;
reclassified from B per r1 finding: a deposit held to year-end sets
`review_reason` on a lot that never reaches Excel); `th_lot_matcher.py:400`
derivatives & fee dedup summaries; `fee_filter.py:434` untagged-whitelist
removal (pattern I); `crypto_reporting.py:907` parse-error drops;
`crypto_reporting.py:567` sub-1-EUR filter.

**Critical:** `crypto_reporting.py:900/907/915/922` are tightly clustered.
Lines 900 & 922 are Bucket B (→ INFO); 907 is Bucket C (parse-error drops, STAYS
WARNING); 915 is already INFO. A mechanical "demote the cluster" sweep would
silently hide a Bucket-C data-loss signal. Task 4 handles these one at a time
with the per-line bucket map above.

## Evaluation Criteria

**Quality dimensions:**
- **correctness:** full suite green (1831+ tests); no `review_required` /
  `review_reason` / value changes; verified by the existing CG/FIFO test
  assertions on those fields (Tasks 1–6 include regression assertions that the
  Excel-surface flags survive each demotion). This is a logging-level change;
  it must not mutate any accumulator or reorder any `replace` call.
- **observability:** real `uv run tax-reporting` run at default WARNING shows
  ~9 WARNING lines (the Bucket-C set, including zero-NV deposits which stay
  WARNING per r1 finding), down from 26. `LOG_LEVEL=INFO` restores Bucket-A/B
  aggregates; file log keeps per-row DEBUG.
- **maintainability:** rule #7 gains a pattern→class lookup table; new
  aggregates reuse `_emit_flagged_summary` where the shape fits (Task 8 J/K); the
  new `_CHAIN_NATIVE_FEE_ASSET` map is a `Final` constant co-located with
  `_KNOWN_CHAINS` (protocol fact, not law config).
- **regression-guard power:** each demoted site has BOTH a positive assertion
  at `caplog.at_level(DEBUG)` (message present at its new level) AND a negative
  assertion at `caplog.at_level(WARNING)` (message absent); guards must
  discriminate "correctly demoted" from "deleted" from "mis-demoted to a
  suppressed level" (premortem blocker B1).

**Release gates:**
- `uv run pytest` full suite green.
- Real-run WARNING count verified (~9).
- `review-plan` ready=yes (Blocker=0, Medium=0) after ≥2 rounds.

## Review Scope

**Explicit must-fix** (findings on these paths are always in scope):

**Production code:**
- `src/tax_reporting/application/crypto/chain_derivation.py` *(new constant + helper, Task 1)*
- `src/tax_reporting/application/crypto_fifo/_emitters.py`
- `src/tax_reporting/application/crypto_fifo/matching.py`
- `src/tax_reporting/application/crypto_fifo/transfer.py`
- `src/tax_reporting/application/crypto_fifo/cross_asset.py`
- `src/tax_reporting/application/crypto_fifo/parsing.py`
- `src/tax_reporting/application/crypto/fifo_helpers.py`
- `src/tax_reporting/application/crypto/aggregation.py`
- `src/tax_reporting/application/crypto/fee_filter.py`
- `src/tax_reporting/application/crypto_reporting.py`
- `docs/maintenance/project-guidelines.md`

**Tests:**
- `tests/unit/application/test_crypto_chain_derivation.py` *(new cases for `_CHAIN_NATIVE_FEE_ASSET` + `is_native_gas_fee`, Task 1)*
- `tests/unit/application/test_crypto_fifo.py`
- `tests/unit/application/test_derivatives_filter.py` *(owns the `_emitters` tests)*
- `tests/unit/application/test_crypto_reporting.py`
- `tests/unit/application/test_fee_filter.py` *(if exists)*
- `tests/unit/application/test_aggregation.py` *(if exists)*
- new test cases authored by Tasks 1, 2, 4, 5, 6, 7 as needed (in the files enumerated above)

**Plan-related extension:** implementation and review may change files not
listed above. A finding is in scope when causally related to this plan (implements
a task, fixes a plan-introduced regression, closes wiring/docs implied by an
explicit must-fix change, or contradicts a contract the plan changed). Weak or
speculative links are dropped with a one-line reason.

**Out of scope; reject unless plan-related:**
- `src/tax_reporting/domain/crypto_fifo.py`: no log sites; frozen.
- `src/tax_reporting/presentation/`: no crypto-pipeline log sites; frozen.
- The `normalize_asset_ticker` control-char hardening (deferred security
  follow-up from the predecessor plan; out of scope here).

## Validation Commands

```bash
# Full suite (must stay green; no behavior change)
uv run pytest

# Confirm Bucket-C aggregates still emit WARNING (grep the surviving sites)
grep -rn "logger.warning" src/tax_reporting/application/crypto_fifo/ \
  src/tax_reporting/application/crypto/ src/tax_reporting/application/crypto_reporting.py \
  src/tax_reporting/application/token_origin.py

# Confirm no Bucket-A/B site still calls logger.warning (the demoted substrings).
# NOTE: substrings must match the ACTUAL emitted text (r1 finding: "missing/epoch
# acquisition dates" matched aggregation.py only, not the matching.py epoch messages).
# NOTE: "third currency" is DELIBERATELY ABSENT here: after Task 3 the anomalous/
# unknown-chain branch STILL warns on it (the native-gas branch moved to DEBUG). See
# the dedicated split-validation block below.
for s in "empty Sent Cost Basis" "Cyclic" "all-zero" \
         "pool exhausted" "suspect untagged network fees" \
         "Empty or epoch acquisition date" "Empty or epoch disposal date" \
         "missing/epoch acquisition dates" "FIFO rebuild active: buffered" \
         "unknown receiver platform"; do
  hits=$(grep -rn "$s" src/tax_reporting/application/ | grep "logger.warning" | wc -l | tr -d ' ')
  echo "$s: $hits warning-site(s) (expect 0)"
done

# Validate the third-currency-fee SPLIT (Task 3): the native-gas branch is DEBUG,
# the anomalous/unknown-chain branch STAYS WARNING. Both branches share the
# "fee in third currency" text, so check the call-site branch structure instead.
echo "third-currency-fee call sites (expect each emitter to branch on is_native_gas_fee):"
grep -n "is_native_gas_fee\|third currency" src/tax_reporting/application/crypto_fifo/_emitters.py

# Confirm Bucket-C substrings STILL call logger.warning (must NOT have been demoted).
# Includes the NEW grouped Bucket-C aggregates from Tasks 5b/6 (non-positive/negative).
for s in "origin-resolution disagreement" "duplicate-tx_key" "CG dedup summary" \
         "untagged-whitelisted fee disposal" "sub-1-EUR" "ambiguous decimal values" \
         "zero-Net-Value crypto_deposit" "non-positive acquisition" \
         "negative-consumption"; do
  hits=$(grep -rn "$s" src/tax_reporting/application/ | grep "logger.warning" | wc -l | tr -d ' ')
  echo "$s: $hits warning-site(s) (expect >=1)"
done

# Confirm the NEW Bucket-B aggregate messages (Tasks 7a/7b) survive at INFO, not WARNING (r2 F2).
for s in "epoch-sentinel dates" "unresolved deferred-acquisition lot"; do
  whits=$(grep -rn "$s" src/tax_reporting/application/ | grep "logger.warning" | wc -l | tr -d ' ')
  ihits=$(grep -rn "$s" src/tax_reporting/application/ | grep "logger.info" | wc -l | tr -d ' ')
  echo "$s: WARNING=$whits (expect 0), INFO=$ihits (expect >=1)"
done

# Real-run WARNING count (manual; requires personal data not in repo)
# uv run tax-reporting 2>&1 | grep -c "WARNING"
```

## Design Invariants (CR Guard)

1. **No audit signal lost.** Every demoted site either (a) has an Excel review
   surface (Bucket B; verified via the downstream flag lines in the bucket map),
   (b) describes correct treatment with no anomaly (Bucket A; fee folded into
   `cost_eur` at `matching.py:189`), or (c) stays WARNING (Bucket C). The
   "data-loss conditions must be logged at warning+" rule (`coding_guidelines.md`
   #5) is satisfied: Bucket-C aggregates stay WARNING; Bucket-B's warning-level
   signal is redundant with the Excel cell the user receives.
2. **`matching.py:175` IS reachable in production (r1 Blocker correction).**
   `cross_asset._resolve_single_acquisition` has TWO branches: the RESOLVED
   branch (`cross_asset.py:238-265`) rewrites `source_type` to
   `"exchange_in_resolved"`, but the UNRESOLVED branch (`cross_asset.py:190-203`)
   returns `acq.with_acq(review_required=True, review_reason=...)` WITHOUT
   passing `source_type=`, and `with_acq` uses `dataclasses.replace`
   (`contexts.py:32-38`), which preserves unspecified fields. So an unresolved
   deferred acquisition (tx_key mismatch, or a dependency cycle that processed
   the receiver first) retains `source_type="exchange_in_deferred"`, reaches
   `_build_taxable_realization`, and fires `matching.py:132` (`is_deferred_acq`)
   → `matching.py:175`. This is a genuine production path (the existing test at
   `test_crypto_fifo.py:929-959` constructs it). `matching.py:175` is therefore
   **Bucket B** (it sets `review_required=True` + `deferred_reason` on the
   realization at `matching.py:198-204, 206`, rendering the Crypto Gains "YES:"
   cell). Task 7b demotes the per-row WARNING → DEBUG and adds ONE aggregate
   INFO. It is NOT a double-count of Pattern J: Pattern J names cross-asset
   *resolution* causes (unresolved/zero/partial/multi_sender at acquisition
   time); `matching.py:175` is the *realization-time* consequence (the deferred
   acquisition was consumed by a taxable disposal with zero cost). Different
   audit events, both Bucket B. (Original "dead in production" claim was wrong:
   it traced only the resolved branch.)
3. **Bucket-C per-row sites stay WARNING via grouping, not demotion.**
   `matching.py:58` (non-positive acquisition) and `:244` (negative consumption)
   are genuine silent data loss (`continue`/`return` drops the row with no flag).
   Tasks 4b/5 group them (per-row DEBUG + ONE aggregate WARNING) so they stop
   flooding but remain loud. They MUST NOT be demoted to INFO.
4. **Test guards have discriminating power (premortem B1, r1 F9).**
   `caplog.at_level(WARNING)` filters INFO/DEBUG records before capture, so a
   bare "assert message absent" passes whether the site was demoted, deleted, or
   mis-demoted to a suppressed level. Every demoted site's regression test MUST
   assert BOTH: (positive) the message appears at its new level under
   `caplog.at_level(DEBUG)`, AND (negative) it does not appear under
   `caplog.at_level(WARNING)`. The positive and negative assertions MUST be
   **separate emissions** (two `with caplog.at_level(...)` blocks re-invoking
   the code under test), NOT one capture filtered twice, because a single
   `at_level(DEBUG)` capture contains the record regardless. Note: caplog
   attaches its own root handler and bypasses `configure_application_logging`,
   so these guards prove the EMIT level, not that the file handler receives
   DEBUG at the production default; the file-handler-DEBUG invariant is owned
   by the prior plan's test and re-confirmed in Task 10.
5. **`crypto_reporting.py:900/907/915/922` cluster handled per-line.** 900 & 922
   → INFO (Bucket B); 907 STAYS WARNING (Bucket C, parse-error drops); 915
   already INFO. A mechanical cluster sweep is forbidden.
6. **`_emit_flagged_summary` needs a `level` kwarg (r1 F7).** The helper at
   `fifo_helpers.py:219-252` hardcodes `logger.warning(...)` (line 247). The new
   Bucket-B INFO aggregates (empty-Sent-Cost-Basis, epoch dates) and the J/K
   flip (Task 8) target INFO. Task 8 MUST add `level: int = logging.WARNING` to
   the helper signature and pass `level=logging.INFO` from INFO callers, so both
   Bucket-B INFO and any Bucket-C WARNING aggregates reuse it. Verified:
   `_emit_flagged_summary`'s only callers are J (`fifo_helpers.py:390`) and K
   (`:397`), both Bucket B; flipping them to INFO is consistent with the
   schema-based rule. The non-positive/negative-consumption aggregates (Tasks
   4b/5) use a count-only shape (no cause breakdown) and stay inline like
   pattern F (they are Bucket C, emit WARNING).
7. **Aggregate emission scope = once per run, not per-asset (r1 F2).** There is
   no `process_asset_fifo`; the actual functions are `_process_single_asset_fifo`
   (`fifo_helpers.py:111`, per-asset, called in a loop at `:349-364`) and
   `compute_fifo_for_asset` (`matching.py:19`, per-(asset,platform)). The new
   counters are incremented deep in per-row loops (`matching.py:58/134/141/175/244`,
   `_emitters.py:177`). The aggregate MUST emit ONCE from
   `_rebuild_fifo_for_loan_affected_assets` (the true top-level caller), next to
   the existing `_emit_flagged_summary` calls at `fifo_helpers.py:390,397`,
   exactly as J/K/F do. **Counter threading differs by call depth (r2 F1):**
   - **Task 5b (`matching.py:58` non-positive):** site is in `compute_fifo_for_asset`'s
     direct body (where `AssetFifoResult` is built at `matching.py:92`). Add a
     `non_positive_acq_count` field to `AssetFifoResult` and populate it inline;
     the pattern-F `unmatched_taxable_count` precedent (`matching.py:96`) applies
     cleanly.
   - **Task 6 (`matching.py:244` negative):** site is in `_consume_against_pool_inplace`
     (`matching.py:213`), called per-consumption from `compute_fifo_for_asset`.
     Thread a `negative_consumption_counter: list[int]` into
     `_consume_against_pool_inplace` **exactly like the existing
     `unmatched_taxable_counter`** (`matching.py:74,79,220`); sum it in
     `compute_fifo_for_asset` onto an `AssetFifoResult` field.
   - **Tasks 6a/6b (`matching.py:134/141/175` epoch + deferred):** sites fire in
     `_build_taxable_realization` (`matching.py:100`), a LEAF returning one
     `CryptoFifoRealization` with no `AssetFifoResult` handle. Thread
     `epoch_counter: list[int]` and `deferred_consumed_counter: list[int]` into
     `_build_taxable_realization` → `_consume_against_pool_inplace` (alongside
     `unmatched_taxable_counter`), then sum onto `AssetFifoResult` fields in
     `compute_fifo_for_asset`. This is the in-place mutable-accumulator convention
     already established at `matching.py:74`; use it for consistency rather than
     changing `_build_taxable_realization`'s return signature.
   The aggregate emits once per run from `_rebuild_fifo_for_loan_affected_assets`
   after summing the per-asset `AssetFifoResult` fields.
8. **Third-currency-fee: unified two-model rule, not a flat demotion.** The
   `_emitters.py:65/:195` third-currency-fee site applies the **OR of two
   expected-case models**: (a) CEX model: `fee_currency in (sent, received)`,
   the existing leg-check (kept); (b) DEX model: `fee_currency ==
   _CHAIN_NATIVE_FEE_ASSET.get(_derive_chain(wallet))`, the new native-gas
   check. A fee that satisfies EITHER → `logger.debug(...)` (no warning). A fee
   that satisfies NEITHER → STAYS `logger.warning(...)`. Unknown chain
   (`_derive_chain` returns `"Unknown"`) → fail-safe WARN. The CEX leg-check is
   NOT removed or weakened; it composes with the native-gas check. **Data
   validated** (342 exchanges, 61 third-currency fees; numbers from the
   production `parse_koinly_decimal`): only **19 have EUR value > 0** (6 ETH on
   Ethereum + 4 ETH on zkSync ERA + 9 BNB on BSC); ALL 19 are native-gas and
   silenced by the new branch. The other 42 (17 BERA + 25 Kraken `FEE`) have
   EUR value 0.00 and are already suppressed by `fee_value > ZERO`
   (`_emitters.py:61/191`); the native-gas branch is defense-in-depth for
   them; zero genuine CEX third-currency fees with EUR value exist. The map
   lives as `_CHAIN_NATIVE_FEE_ASSET` in `chain_derivation.py`
   (protocol fact, not law) and MUST cover every chain in `_KNOWN_CHAINS` that
   has a distinct native gas token; EVM L2s (Arbitrum/BASE/zkSync/Mantle/
   Starknet) map to ETH. CEX names in `_KNOWN_CHAINS` (ByBit/Kraken/Binance/
   Gate.io/Wirex) are intentionally ABSENT from the map (CEX fees are caught by
   the leg-check, not native-gas). `ParsedTxRow.row` (the raw row dict) already
   carries `Sending Wallet` / `Receiving Wallet`, and the emitters already read
   them (e.g. `_emitters.py:53`), so the emitter can call
   `_derive_chain(parsed_row.row.get("Sending Wallet", ""))` with NO new field
   or signature change; Task 1 only adds the constant + a helper.

## Terms (Skill-gate marker; Session key)

*(Skill-gate marker recipe: the `skill-gate/README.md` referenced by the plans
skill is not present in this environment; only `~/.ai-playbook/scripts/session_channel.py`
exists. The marker is a hardening backstop, not load-bearing for plan correctness.
Proceeding without it; flagged for the user.)*

---

### Task 0: Enumerate every `caplog.at_level(WARNING)` test that will break (r1 F3)

Files:
- (no code changes; produces a checked-in manifest under `docs/tmp/`)

Before any demotion, list every test whose `caplog.at_level(WARNING)` positive
assertion will fail once the referenced substring moves below WARNING. This
prevents unexpected REDs mid-implementation and assigns per-task ownership for
each stale assertion (lesson #69).

- [x] Run: `grep -rn "caplog.at_level(logging.WARNING)\|caplog.at_level(WARNING)" tests/unit/application/test_crypto_fifo.py tests/unit/application/test_crypto_reporting.py tests/unit/application/test_derivatives_filter.py tests/unit/application/test_fee_filter.py tests/unit/application/test_aggregation.py`
- [x] For each hit, record (file:line, substring asserted, owning task) into `docs/tmp/caplog-warning-sweep-2026-07-24.md`.
- [x] Cross-check each recorded substring against the bucket map: if the substring is a Bucket-A/B site (demoted), the owning task MUST convert it; if it is Bucket-C (stays WARNING), the test is unaffected.
- [x] No commit (manifest is a working aid under `docs/tmp/`, gitignored category).

### Task 1: Add `_CHAIN_NATIVE_FEE_ASSET` constant + `is_native_gas_fee` helper

Files:
- `src/tax_reporting/application/crypto/chain_derivation.py` *(new constant + helper)*
- `tests/unit/application/test_crypto_chain_derivation.py` *(locate existing; add cases)*

New domain data: the chain → native gas-token map. Native gas is a protocol
fact (not jurisdiction/year law), so it is a `Final` frozen dict next to
`_KNOWN_CHAINS` (per the user decision; flagged per AGENTS.md hardcode rule).

- [x] Locate the existing chain_derivation test file via `grep -rln "_derive_chain\|chain_derivation" tests/`. Record its path.
- [x] `TestChainDerivation#test_chain_native_fee_asset_map_complete`; given every chain in `_KNOWN_CHAINS`, expects each on-chain chain (Ethereum, Solana, Sui, Binance Smart Chain, Berachain, Polygon, TON, Aptos, Filecoin, Arbitrum, BASE, zkSync ERA, Mantle, Starknet) to have an entry in `_CHAIN_NATIVE_FEE_ASSET`, and CEX names (ByBit, Kraken, Binance, Gate.io, Wirex, Tonkeeper) to be ABSENT (their fees are caught by the leg-check). EVM L2s (Arbitrum/BASE/zkSync ERA/Mantle/Starknet) → ETH.
- [x] `TestChainDerivation#test_is_native_gas_fee_true_for_eth_on_ethereum`; given wallet `"Ethereum (ETH)"` and fee_currency `"ETH"`, expects `is_native_gas_fee(wallet, fee_currency)` → True.
- [x] `TestChainDerivation#test_is_native_gas_fee_false_for_eth_on_solana`; given wallet `"Solana (SOL)"` and fee_currency `"ETH"` (ETH bridged to Solana, not native gas), expects → False (proves the map is chain-keyed, not asset-keyed; the safety property).
- [x] `TestChainDerivation#test_is_native_gas_fee_false_for_unknown_chain`; given wallet `"Some Unknown Wallet"` and any fee_currency, expects → False (fail-safe; caller warns).
- [x] `TestChainDerivation#test_is_native_gas_fee_false_for_bnb_on_binance_cex`; given wallet `"Binance (2)"` (the CEX) and fee_currency `"BNB"`, expects → False (Binance CEX is absent from the map; its BNB fees are a CEX loyalty mechanic handled by the leg-check, NOT native gas).
- [x] `TestChainDerivation#test_is_native_gas_fee_true_for_eth_on_zksync_era_bare`; given wallet `"zkSync ERA"` (bare chain name, no parenthesized ticker, a real-data edge case relying on the word-boundary match branch at `chain_derivation.py:106-116`) and fee_currency `"ETH"`, expects → True (also guards the L2→ETH map entry).
- [x] Add `_CHAIN_NATIVE_FEE_ASSET: Final[dict[str, str]]` and `def is_native_gas_fee(wallet: str, fee_currency: str) -> bool` (returns `fee_currency == _CHAIN_NATIVE_FEE_ASSET.get(_derive_chain(wallet))`, which is False when the chain is absent or Unknown). Run → GREEN.
- [x] Commit: `feat(crypto): add chain->native-fee-asset map and is_native_gas_fee helper`

### Task 2: RED tests for the third-currency-fee unified-rule split

Files:
- `tests/unit/application/test_derivatives_filter.py` *(the existing file owning `_emit_cross_asset_exchange` / `_emit_received_only_exchange` tests; verified via `grep -rln "_emit_cross_asset_exchange\|third currency" tests/`)*

- [x] `TestEmitters#test_native_gas_fee_cross_asset_logs_at_debug`; given a cross-asset exchange on wallet `"Ethereum (ETH)"` with `fee_currency="ETH"` (third currency = native gas, `fee_value > 0`), expects the "fee in third currency ... deferred acquisition cost basis" message at `logging.DEBUG`, NOT at WARNING, AND `AcquisitionContext.acq.fee_eur` includes the fee value (regression: data unchanged). Two separate `caplog.at_level` blocks (Invariant #4).
- [x] `TestEmitters#test_native_gas_fee_received_only_logs_at_debug`; same for the received-only path (`_emitters.py:195`) with ETH fee on Ethereum.
- [x] `TestEmitters#test_anomalous_third_token_fee_cross_asset_stays_warning`; given a cross-asset exchange on `"Ethereum (ETH)"` with `fee_currency="USDC"` (neither a leg nor native gas), expects the message STILL at `logging.WARNING` (the genuinely-anomalous case is NOT silenced).
- [x] `TestEmitters#test_unknown_chain_third_token_fee_stays_warning`; given an exchange on wallet `"Some Unknown DEX"` with a third-currency fee, expects WARNING (fail-safe for unknown chain; Invariant #8).
- [x] `TestEmitters#test_cex_leg_fee_no_warning`; given a CEX exchange (e.g. wallet `"ByBit"`) where `fee_currency == received_currency` (the existing leg-check), expects NO third-currency-fee message at all (regression: the leg-check still suppresses CEX fees; the native-gas check composes, does not replace). NOTE: this test asserts PRE-EXISTING behavior and will PASS before Task 3; it is a regression guard for the leg-check preservation, NOT a RED driver, so it is excluded from the RED `-k` filter below and verified GREEN in Task 3.
- [x] Run → expect RED (only the two genuinely-failing selectors `native_gas_fee*`; the two `..._stays_warning` tests assert current behavior and pass pre-Task-3, so they are regression guards, not RED drivers): `uv run pytest tests/unit/application/test_derivatives_filter.py -k "native_gas_fee or anomalous_third_token or unknown_chain_third or cex_leg_fee" -x` (emitter tests live in `test_derivatives_filter.py`, verified via `grep -rln "_emit_cross_asset_exchange" tests/`; only the `native_gas_fee*` selectors fail pre-Task-3).

### Task 3: GREEN: apply the unified two-model rule in `_emitters.py`

Files:
- `src/tax_reporting/application/crypto_fifo/_emitters.py`

- [x] Add `from ..crypto.chain_derivation import is_native_gas_fee` (verify import resolves: `uv run python -c "from tax_reporting.application.crypto_fifo._emitters import _emit_received_only_exchange"`).
- [x] At `_emitters.py:64` (cross-asset deferred path) and `:194` (received-only path): replace the bare `if third_currency_fee_recv > ZERO: logger.warning(...)` with a branch. **Reuse the existing `sending_wallet` local** (cross-asset path binds it at `_emitters.py:55`; received-only path binds it at `:171`; both already `Sending Wallet` stripped) as the fee-payer chain hint; do NOT re-bind `wallet` (that shadows the Receiving-side local used for the acquisition at `:124/:169`). If `is_native_gas_fee(sending_wallet, parsed_row.fee_currency)` → `logger.debug(...)` (expected native gas); else → `logger.warning(...)` (genuinely anomalous or unknown chain). The `fee_eur` rolling into the acquisition is UNCHANGED in both branches (the fee always enters cost basis; only the log level splits).
- [x] Run → expect GREEN: `uv run pytest tests/unit/application/test_derivatives_filter.py -k "native_gas_fee or anomalous_third_token or unknown_chain_third or cex_leg_fee" -x`
- [x] Run the full emitter suite to confirm no regression: `uv run pytest tests/unit/application/test_derivatives_filter.py -x`
- [x] Commit: `refactor(crypto): split third-currency-fee warning into native-gas (DEBUG) vs anomalous (WARNING)`

### Task 4: Demote Bucket-B aggregate sites in `crypto_reporting.py` cluster to INFO

Files:
- `src/tax_reporting/application/crypto_reporting.py`
- `tests/unit/application/test_crypto_reporting.py`

- [x] `TestCryptoReporting#test_fifo_rebuild_buffered_aggregate_at_info`; given loan-affected assets with buffered raw CG rows, expects the "FIFO rebuild active: buffered N raw CG row(s)" aggregate at INFO, not WARNING; AND each buffered entry retains `review_required=True` (regression: Excel surface unchanged).
- [x] `TestCryptoReporting#test_all_zero_flagged_aggregate_at_info`; given all-zero CG rows, expects the "Flagged N all-zero capital gains row(s) for review" aggregate at INFO, not WARNING; AND each entry retains `review_required=True` + `review_reason`.
- [x] `TestCryptoReporting#test_parse_error_drops_stay_warning`; given a CG row with an ambiguous decimal, expects the "Skipped N capital gains row(s) due to ambiguous decimal values" aggregate (crypto_reporting.py:907) to STILL appear at WARNING (regression guard: Bucket-C must not be swept).
- [x] Change `logger.warning` → `logger.info` at `crypto_reporting.py:900` (FIFO rebuild buffered) and `:922` (all-zero flagged). LEAVE `:907` (parse errors) and `:915` (already INFO) UNTOUCHED.
- [x] Run → expect GREEN: `uv run pytest tests/unit/application/test_crypto_reporting.py -k "fifo_rebuild_buffered_aggregate or all_zero_flagged_aggregate or parse_error_drops" -x`
- [x] Commit: `refactor(crypto): demote Excel-surfaced CG aggregates (FIFO-buffered, all-zero) to INFO`

### Task 5: GREEN: group empty-Sent-Cost-Basis (Bucket B) + non-positive-acquisition (Bucket C) in `_emitters.py` / `matching.py`

Files:
- `src/tax_reporting/application/crypto_fifo/_emitters.py`
- `src/tax_reporting/application/crypto_fifo/matching.py`
- `src/tax_reporting/application/crypto/fifo_helpers.py`
- `tests/unit/application/test_crypto_fifo.py`

This task covers TWO sites with DIFFERENT bucket assignments in the same
neighborhood; do not conflate them.

**5a: empty Sent Cost Basis (Bucket B → per-row DEBUG + aggregate INFO):**
- [x] `TestCryptoFifo#test_empty_sent_cost_basis_per_row_debug_aggregate_info`; given a received-only exchange with empty Sent Cost Basis, expects the per-row "empty Sent Cost Basis" message at DEBUG (not WARNING), ONE aggregate INFO "N exchange(s) with empty Sent Cost Basis" summary, and the acquisition retains `review_required=True` + the carry-over review_reason.
- [x] Update/replace the STALE existing test `tests/unit/application/test_crypto_fifo.py::test_logs_warning_on_empty_cost_basis` (line ~321); its `caplog.at_level(WARNING)` positive assertion fails post-demotion; convert to the positive-at-DEBUG + negative-at-WARNING pair (r1 F3; identified in Task 0 manifest).
- [x] Demote `logger.warning` at `_emitters.py:177` → `logger.debug`; add a mutable counter (threaded like J/K's `dict[str,int]` or a simple `list[int]`) incremented in the branch; emit ONE aggregate `logger.info(...)` from `_rebuild_fifo_for_loan_affected_assets` (the top-level caller, NOT the leaf; Invariant #7). Emit inline at INFO (Pattern-F count-only shape); the `_emit_flagged_summary` helper is reserved for the J/K cause-breakdown aggregates (Task 8) whose `dict[str,int]` shape it matches; a single-int count does not fit its signature.

**5b: non-positive acquisition (Bucket C → per-row DEBUG + aggregate WARNING):**
- [x] `TestCryptoFifo#test_non_positive_acquisition_per_row_debug_aggregate_warning`; given an acquisition with `amount <= 0`, expects the per-row "Skipping non-positive acquisition" message at DEBUG (not WARNING), ONE aggregate WARNING "Skipped N non-positive acquisition(s) for <asset>", and the acquisition is still dropped from the pool (regression: data-loss treatment unchanged).
- [x] Demote `logger.warning` at `matching.py:58` → `logger.debug`; return the count on `AssetFifoResult` (the pattern-F `unmatched_taxable_count` precedent at `matching.py:96`, preferred over threading a mutable dict), sum it in `_process_single_asset_fifo`, and emit ONE aggregate `logger.warning(...)` from `_rebuild_fifo_for_loan_affected_assets` after the per-asset loop. STAYS WARNING (Bucket C: silent data loss, no Excel surface).

- [x] Run → expect GREEN: `uv run pytest tests/unit/application/test_crypto_fifo.py -k "empty_sent_cost_basis or non_positive_acquisition" -x`
- [x] Commit: `refactor(crypto): group empty-Sent-Cost-Basis (INFO) and non-positive-acquisition (WARNING) emissions`

### Task 6: GREEN: group negative consumption (Bucket C) in `matching.py`

Files:
- `src/tax_reporting/application/crypto_fifo/matching.py`
- `tests/unit/application/test_crypto_fifo.py`

- [x] `TestCryptoFifo#test_negative_consumption_per_row_debug_aggregate_warning`; given a consumption with `amount < 0`, expects the per-row "Negative consumption amount" message at DEBUG (not WARNING), ONE aggregate WARNING "Skipped N negative-consumption event(s)", and the consumption is still dropped (early `return`).
- [x] Demote `logger.warning` at `matching.py:244` → `logger.debug`; thread a `negative_consumption_counter: list[int]` into `_consume_against_pool_inplace` exactly like the existing `unmatched_taxable_counter` (`matching.py:74,79,220`), sum it onto an `AssetFifoResult` field in `compute_fifo_for_asset`, and emit ONE aggregate `logger.warning(...)` from `_rebuild_fifo_for_loan_affected_assets` after the per-asset loop (Invariant #7, r2 F1). STAYS WARNING (Bucket C).
- [x] Run → expect GREEN: `uv run pytest tests/unit/application/test_crypto_fifo.py -k negative_consumption -x`
- [x] Commit: `refactor(crypto): group negative-consumption emissions (WARNING aggregate)`

### Task 7: GREEN: group epoch-date warnings (Bucket B) + group `matching.py:175` deferred-acquisition-consumed (Bucket B) in `matching.py`

Files:
- `src/tax_reporting/application/crypto_fifo/matching.py`
- `src/tax_reporting/application/crypto_fifo/cross_asset.py`
- `src/tax_reporting/application/crypto/fifo_helpers.py`
- `tests/unit/application/test_crypto_fifo.py`

**7a: epoch dates (Bucket B → per-row DEBUG + aggregate INFO):**
- [x] `TestCryptoFifo#test_epoch_dates_per_row_debug_aggregate_info`; given a taxable realization with an epoch-sentinel acquisition and/or disposal date, expects the per-row "Empty or epoch acquisition date" / "Empty or epoch disposal date" messages at DEBUG (not WARNING), ONE aggregate INFO "N realization(s) with epoch-sentinel dates", and the realization retains `review_required=True` (via `or is_epoch_acq`/`or is_epoch_con`). Two separate `caplog.at_level` blocks per Invariant #4.
- [x] Demote `logger.warning` at `matching.py:134` and `:141` → `logger.debug`; thread an `epoch_counter: list[int]` into `_build_taxable_realization` → `_consume_against_pool_inplace` (alongside the existing `unmatched_taxable_counter`, per Invariant #7 r2 F1), sum onto an `AssetFifoResult` field in `compute_fifo_for_asset`, and emit ONE aggregate `logger.info(...)` inline (Pattern-F count-only shape) from `_rebuild_fifo_for_loan_affected_assets` after the per-asset loop.

**7b: `matching.py:175` deferred acquisition consumed (Bucket B → per-row DEBUG + aggregate INFO; r1 F1 correction):**
- [x] `TestCryptoFifo#test_deferred_acquisition_consumed_reachable_in_production`; given a realization consuming an UNRESOLVED deferred acquisition (`source_type="exchange_in_deferred"` retained because `cross_asset.py:190-203` does not rewrite `source_type` on the unresolved branch), expects `matching.py:175` to fire: per-row message at DEBUG (not WARNING), realization retains `review_required=True` + `deferred_reason`. This mirrors the existing `test_crypto_fifo.py:929-959` setup (`tx_key="orphan_key"`, no sender).
- [x] `TestCryptoFifo#test_deferred_acquisition_consumed_aggregate_info`; given N such realizations, expects ONE aggregate INFO "N realization(s) consumed an unresolved deferred-acquisition lot (cost basis zero; gain overstated)"; distinct wording from Pattern J's "cross-asset deferred acquisition(s) flagged" to avoid reconciliation confusion (Invariant #2).
- [x] Demote `logger.warning` at `matching.py:175` → `logger.debug`; thread a `deferred_consumed_counter: list[int]` into `_build_taxable_realization` → `_consume_against_pool_inplace` (Invariant #7 r2 F1), sum onto an `AssetFifoResult` field, and emit ONE aggregate `logger.info(...)` from `_rebuild_fifo_for_loan_affected_assets`. This is Bucket B (realization `review_required` + `deferred_reason` render in Crypto Gains). It is NOT a double-count of Pattern J (different audit event: realization-time consequence vs resolution-time cause; see Invariant #2).

- [x] Run → expect GREEN: `uv run pytest tests/unit/application/test_crypto_fifo.py -k "epoch or deferred_acquisition_consumed" -x`
- [x] Commit: `refactor(crypto): group epoch-date (INFO) and deferred-acquisition-consumed (INFO) emissions`

### Task 8: Demote remaining Bucket-B aggregate sites (parsing, pool-exhausted, suspect fees, aggregation) + Bucket-A/B root-cause notices

Files:
- `src/tax_reporting/application/crypto_fifo/parsing.py`
- `src/tax_reporting/application/crypto_fifo/matching.py`
- `src/tax_reporting/application/crypto_fifo/transfer.py`
- `src/tax_reporting/application/crypto_fifo/cross_asset.py`
- `src/tax_reporting/application/crypto/fee_filter.py`
- `src/tax_reporting/application/crypto/aggregation.py`
- `src/tax_reporting/application/crypto/fifo_helpers.py`
- corresponding test files (locate via grep per site)

Each site below is a one-line `logger.warning` → `logger.info` flip (the per-row
side is already DEBUG for these, or is a single aggregate). Add a paired test
(positive-at-INFO + negative-at-WARNING) for each unless an existing test only
needs its `at_level` flipped. `parsing.py:290` (zero-NV deposits) is NOT in this
list; it stays WARNING (Bucket C; r1 F5: the flag is set on an
`AcquisitionContext` intermediate, not a rendered entry).

- [x] **First:** add a `level: int = logging.WARNING` kwarg to `_emit_flagged_summary` (`fifo_helpers.py:219-252`) and route the body through `logger.log(level, ...)` instead of `logger.warning(...)` (r1 F7). This unblocks Tasks 5a/7a/7b which reuse the helper at INFO.
- [x] `matching.py:84` FIFO pool exhausted (non-taxable) → INFO (Bucket B; downstream `partial_carryover_tx_keys` feeds `review_required` in `cross_asset.py:218` / `transfer.py:167`).
- [x] `transfer.py:48` cyclic transfer dependency → INFO (Bucket A/B root-cause notice; consequence surfaced via Pattern K).
- [x] `cross_asset.py:48` cyclic swap dependency → INFO (Bucket A/B root-cause notice; consequence surfaced via Pattern J).
- [x] `fee_filter.py:643` suspect fees surfaced → INFO (Bucket B; `CryptoReviewEntry` appended at `fee_filter.py:624-633`).
- [x] `aggregation.py:425` missing/epoch acquisition dates → INFO (Bucket B; inherits `review_required` from placeholder lots).
- [x] `_emitters.py:339` unknown receiver platform (phantom) → INFO (Bucket B; `fifo_helpers.py:74-78` sets the flag downstream).
- [x] J/K aggregates via `_emit_flagged_summary` (`fifo_helpers.py:390,397`): pass `level=logging.INFO` at both call sites. VERIFIED (r1 F7): `grep -rn "_emit_flagged_summary" src/` returns exactly two callers (`:390` J, `:397` K), both Bucket B; flipping to INFO is consistent with the schema-based rule and affects no Bucket-C caller.
- [x] For each flipped site, sweep `tests/` for `caplog.at_level(WARNING)` assertions on its substring (lesson #69); convert to `at_level(INFO)` and add the negative-at-WARNING guard (two separate `with` blocks; Invariant #4). Cross-check against the Task 0 manifest.
- [x] Run → expect GREEN: `uv run pytest` (full suite; these are scattered)
- [x] Commit: `refactor(crypto): add level kwarg to _emit_flagged_summary; demote remaining Excel-surfaced and root-cause warnings to INFO`

### Task 9: Extend rule #7 with the HAS_EXCEL_SURFACE→INFO class + pattern lookup table

Files:
- `docs/maintenance/project-guidelines.md`
- `docs/maintenance/development_lessons.md` *(new lessons #72, #73)*
- `docs/maintenance/crypto_implementation_guidelines.md` *(native-gas split mechanism)*

- [x] Extend rule #7 with a third class: **HAS_EXCEL_SURFACE → per-row DEBUG + aggregate INFO**, defined as "the entry's data type has a review column/field rendered in the report, regardless of per-row `review_required` values" (premortem M2: classify by schema, not runtime values). State the audit surface is the Excel cell; the console aggregate is a nicety reachable at INFO.
- [x] Add the EXPECTED_BEHAVIOR class, with the **native-gas split** (Bucket A-split): a fee that is the chain's native gas token → DEBUG (fully expected); a genuinely third-token fee or unknown-chain fee → STAYS WARNING. Document the unified two-model rule (CEX leg-check OR DEX native-gas check) and that asset-keyed matching is unsafe (ETH/BNB/MATIC are cross-chain).
- [x] Document the new `_CHAIN_NATIVE_FEE_ASSET` constant location (`chain_derivation.py`, protocol fact not law) in the crypto-implementation guidelines and cross-reference the crypto-origin registry (the chain list mirrors `_KNOWN_CHAINS`).
- [x] Add a **pattern→class→target-level lookup table** covering A/H/I/J/K/L + new (A-split = native-gas third-currency-fee, M = empty-Sent-Cost-Basis, N = epoch dates, O = non-positive/negative grouped WARNING, P = deferred-acquisition-consumed) so a newcomer can map a site in under a minute (premortem M3). Include the `platform_review_required` caveat (Platform Assumptions sheet is a distinct surface).
- [x] Cross-reference the predecessor plan and this plan in the rule.
- [x] Add lesson #72: "Log-level bucket assignments must be re-derived by tracing the site's output through ALL branches of the pipeline to the Excel review cell, not by reading the emitter line or tracing only the happy path. Initial trace of `matching.py:175` concluded it was 'dead in production because `cross_asset` rewrites `source_type` first', but `cross_asset._resolve_single_acquisition` has an UNRESOLVED branch (`cross_asset.py:190-203`) that returns via `with_acq(review_required=True, review_reason=...)` WITHOUT setting `source_type`, and `dataclasses.replace` preserves the original `source_type="exchange_in_deferred"`, so `matching.py:175` IS reachable (tx_key mismatch / dependency cycle). The review-plan panel caught it." *(Implemented as lesson #73 due to a numbering conflict: #72 was already taken by the ruff-baseline lesson added earlier this session.)*
- [x] Add lesson #73: "A 'third-currency fee' warning that treats all non-leg fees as anomalous is CEX-shaped and wrong for DEX: on a DEX the expected fee is the chain's native gas token (a third currency by definition). The correct rule is the OR of two expected-case models: fee is a trade leg (CEX) OR fee is the chain's native gas (DEX, via `_CHAIN_NATIVE_FEE_ASSET[_derive_chain(wallet)]`). Asset-keyed matching is unsafe (ETH/BNB/MATIC are native gas on one chain but bridged tokens on others); the map must be chain-keyed. A flat 'demote to INFO' would silence genuinely anomalous third-token fees (USDC/governance-token) along with expected gas; the split preserves the warning for the anomalous case." *(Implemented as lesson #74 due to the #72 numbering conflict.)*
- [x] Run → expect GREEN: `uv run pytest` (doc change; suite unaffected)
- [x] Commit: `docs: extend rule #7 with HAS_EXCEL_SURFACE→INFO class and pattern lookup table`

### Task 10: Full-suite verification + real-run WARNING count

Files:
- (no code changes; verification only)

- [x] Run full suite: `uv run pytest` → expect all green (1831+).
- [x] Run the Validation Commands grep sweeps → expect 0 warning-sites for Bucket-A/B substrings, ≥1 for each Bucket-C substring (including the new non-positive/negative grouped aggregates and zero-NV deposits).
- [ ] (Manual, requires personal data) `uv run tax-reporting 2>&1 | grep -c "WARNING"` → expect ~9 (the Bucket-C set, incl. zero-NV deposits). If the real dataset triggers non-positive/negative paths, up to ~11.
- [x] Verify `logs/tax-reporting.log` still contains the per-row DEBUG trail for a demoted site (file-handler-DEBUG invariant; re-confirm the prior plan's file-handler-DEBUG test stays green; r1 F9).
- [x] Commit (if any test hygiene surfaced): `test(crypto): finalize warning-level sweep` *(no commit needed; no test hygiene surfaced; all validation green.)*
