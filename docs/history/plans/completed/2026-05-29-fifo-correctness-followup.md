# Plan: FIFO Correctness Follow-up

Plan review: `docs/reviews/2026-05-29-plan-review-fifo-correctness-followup.md`

Addresses deferred findings from code review `docs/reviews/2026-05-29-branch-review-filter-loan-repayment-gains.md`:
finding #1 (transfer lot carry-over), #2 (parse-error data loss), #5 (carry-over key scope), #7 (domain entity cleanup).

## Gist & Examples

**What changes:** Four correctness and structural improvements to the FIFO engine for loan-affected crypto assets:

1. **Parse-error data loss (#2)**: when a TH row fails to parse, the affected asset's FIFO pool is silently
   incomplete. This changes the failure mode from warn-and-skip to warn-and-flag: all realizations for the
   affected asset are marked `review_required=True` with a specific reason so the user sees the gap in the workbook.

2. **Carry-over key scope (#5)**: the merged carry-over dict used by `resolve_cross_asset_exchanges` is keyed
   only by `tx_key`, so two platforms producing the same composite key (same-date same-pair swap, no TxHash)
   could cross-contaminate cost basis across platforms. Changing the merged key to `(tx_key, platform)` restricts
   look-up to the correct platform.

3. **Transfer lot carry-over (#1)**: when a loan-affected asset is transferred between platforms, the current
   code neither consumes the lot from the sender pool nor creates it on the receiver pool. Any subsequent sale
   on the receiver produces a zero-cost placeholder. This models the transfer the same way as a cross-asset
   exchange: a non-taxable consumption on the sender and a `transfer_in_deferred` acquisition on the receiver,
   resolved by `resolve_cross_asset_exchanges` using the carry-over by `(tx_key, platform)`.

4. **Domain entity cleanup (#7)**: `CryptoAcquisition`, `CryptoConsumption`, and `AssetFifoResult` in the
   domain layer carry `tx_key`, `source_row_index`, and `carryover_cost_by_tx_key`: Koinly parser correlation
   IDs and pipeline workflow state that are not pure financial facts. These are moved to application-layer
   correlation wrappers, leaving the domain types as pure FIFO facts.

**Why needed:**

- #2: Under the PT gate, TH is the *sole* source for loan-affected asset FIFO. A silently incomplete pool
  produces wrong tax figures with no user-visible indication.
- #5: The FIFO scope is per `(asset, platform)` per CIRS art. 43 n.9. A tx_key-only key violates that scope
  when the same composite key appears on two platforms (possible for off-chain swaps with no TxHash).
- #1: Cross-platform transfers of loan-affected assets are common (e.g. WBTC moved from Kraken to ByBit before
  selling). Without lot carry-over the entire transferred amount produces a zero-cost capital gain.
- #7: `domain/crypto_fifo.py` is coupled to Koinly parser internals (`tx_key`, `source_row_index`). Any change
  to how the TH parser builds its correlation keys requires updating the domain type contract.

**Example 2 (parse error flagging):**
```
Before: TH row 47 has unparseable date → WARNING logged, row skipped, WBTC FIFO runs with missing acquisition,
        realization produced with cost_eur=0, review_required=False (user sees "correct-looking" zero-cost gain)

After:  TH row 47 has unparseable date → ERROR logged (row skipped), WBTC added to parse_failed_assets,
        all WBTC realizations marked review_required=True with reason
        "TH parse error on row 47: FIFO pool for WBTC may be incomplete; verify all acquisitions are present"
```

**Example 5 (carry-over key):**
```
Before: Platform A swap at 10:00 produces key "composite_2025-01-01_..." → merged_carryover["composite_..."] = 150
        Platform B swap at 10:00 same pair produces same key → WARNING + summed to 300
        Receiver on Platform B deferred acquisition resolves to 300 EUR (wrong; double-counted Platform A)

After:  merged_carryover[("composite_...", "Platform A")] = 150
        merged_carryover[("composite_...", "Platform B")] = 150  (distinct keys, no collision)
        Receiver on Platform B resolves to 150 EUR (correct)
```

**Example 1 (transfer lot carry-over):**
```
Before: WBTC transferred Kraken→ByBit on 2025-01-10 (cost basis 1000 EUR)
        ByBit WBTC pool: empty
        Sale on ByBit 2025-06-01: zero-cost placeholder, gain = 2000 EUR (overstated by 1000)
        Kraken WBTC pool: phantom lot retained, future sale would also be wrong

After:  Transfer parsed: non-taxable consumption (Kraken, tx_key=T1) → carryover["T1", "Kraken"] = 1000
                         transfer_in_deferred acquisition (ByBit, tx_key=T1, cost=0)
        resolve_cross_asset_exchanges resolves ByBit deferred acquisition → cost_basis=1000
        Sale on ByBit: gain = 1000 EUR (correct)
        Kraken pool: lot consumed, no phantom
```

**Example 7 (domain cleanup):**
```
Before: CryptoAcquisition(date=..., asset=..., amount=..., cost_basis_eur=..., fee_eur=...,
                           source_type=..., wallet=..., platform=...,
                           tx_key="TXH_abc123",          ← Koinly correlation ID
                           source_row_index=42,          ← parser line number
                           review_required=..., ...)

After:  CryptoAcquisition(date=..., asset=..., amount=..., cost_basis_eur=..., fee_eur=...,
                           source_type=..., wallet=..., platform=...,
                           review_required=..., ...)       ← pure financial facts only

        AcquisitionCorrelation(acq=CryptoAcquisition(...), tx_key="TXH_abc123", source_row_index=42)
        (application layer; used by parser and FIFO engine for matching, not persisted to domain)
```

**Edge cases handled:**
- #2: Row fails to parse before `sent_currency`/`received_currency` are known → treat as "unknown asset" and
  log the error but cannot flag a specific asset. Fail loudly (log at ERROR) but continue.
- #1: Transfer fee paid in the same loan-affected asset as the principal; the fee portion is already modelled
  as a separate taxable consumption; the transferred (received) amount is `sent_amount - fee_amount`; the
  carryover for the deferred acquisition is proportional: `carryover * received_amount / sent_amount`.
- #1: Transfer where receiving wallet is unknown (no `Receiving Wallet` column value) → log WARNING and fall
  back to `phantom_sending_transfers` behaviour (flag sender's future realizations `review_required=True`)
  rather than creating an acquisition on an unknown platform.
- #5: The `resolve_cross_asset_exchanges` look-up uses the *deferred acquisition's platform* as the key
  component. For same-asset transfers the deferred platform is the receiver, not the sender. For cross-asset
  exchanges (LBTC→WBTC) the carry-over platform is the sender asset's platform and the deferred acquisition
  platform may differ; the resolution must iterate over all `(tx_key, *)` entries to find matches, or store
  the platform mapping explicitly.

## Design Invariants (CR Guard)

Prior-phase decisions that must not be compromised:

- **Per-wallet FIFO scope (CIRS art. 43 n.9 / DP-004):** FIFO must be computed per `(asset, platform)`, never
  globally per asset. Any carry-over resolution that merges across platforms must do so explicitly and only for
  cross-platform lot transfers (the carry-over, not the FIFO matching itself, crosses platforms).
- **TH is authoritative for loan-affected assets:** `_parse_capital_gains_file` drops ALL CG rows for
  loan-affected assets when the PT gate is active. There is no Koinly CG fallback. Incomplete TH data must be
  surfaced to the user, never silently propagated.
- **`review_required=True` must include a specific `review_reason`:** enforced by `__post_init__` on all three
  domain entities; any new `review_required=True` set must also set `review_reason` to an actionable string.
- **`_aggregate_capital_entries` and `_filter_immaterial_entries` must not be bypassed** (CLAUDE.md constraint).
- **`phantom_sending_transfers` belt-and-suspenders:** even after implementing proper transfer lot tracking (#1),
  keep a version of the phantom-transfer warning for cases where the receiver platform is unknown, so incomplete
  transfers are still surfaced.

## Review Scope

Files directly changed as part of this plan. Review feedback is accepted **only** for the files listed here.
Any finding about a file not in this list must be rejected as out of scope.

**Production code; in scope:**
- `src/shares_reporting/domain/crypto_fifo.py`: remove `tx_key`/`source_row_index` from domain entities (task 4)
- `src/shares_reporting/application/crypto_fifo.py`: transfer lot carry-over (#1), parse-error flagging (#2)
- `src/shares_reporting/application/crypto_reporting.py`: carry-over key type (#5), resolve logic update (#5/#1)

**Tests; in scope:**
- `tests/unit/application/test_crypto_fifo.py`
- `tests/unit/application/test_crypto_reporting.py`

**Out of scope; reject all review feedback:**
- `src/shares_reporting/application/persisting/crypto_gains_sheet.py`: presentation layer, unchanged
- `src/shares_reporting/application/crypto_fifo.py` methods not listed in tasks; frozen; flag separately

## Validation Commands

```bash
uv run pytest tests/unit/application/test_crypto_fifo.py tests/unit/application/test_crypto_reporting.py -x --tb=short -q
uv run pytest tests/unit/ -q
uv run pytest -m e2e -q
```

---

### Task 1: Surface parse errors as asset-level flags (Finding #2)

**Files:**
- `src/shares_reporting/application/crypto_fifo.py`
- `tests/unit/application/test_crypto_fifo.py`

**Behaviour change:** `parse_th_for_loan_affected_assets` currently warns and skips on `ValueError`
(fine for supplementary data; wrong when TH is the sole source). The new behaviour:
- Log at `logger.error` (not `logger.warning`) for any parse failure involving a loan-affected asset.
- Track structured parse failures, not just asset names: `parse_failures_by_asset: dict[str, list[int]]`
  (or equivalent application-layer record carrying at least `asset` and `row_index`).
- Return the parse-failure structure as an additional element from `parse_th_for_loan_affected_assets`
  (4th return value; update all callers).
- In `_rebuild_fifo_for_loan_affected_assets`, after computing FIFO realizations, mark every realization for an
  asset with parse failures as `review_required=True` and include concrete row attribution in the reason, e.g.
  `"TH parse error on row 47: FIFO pool for WBTC may be incomplete; verify all acquisitions/disposals are present"`.
  If multiple rows failed for the same asset, include the first row and mention additional failed rows, or join the
  row numbers explicitly.

**Note on asset attribution:** the current code already normalizes `Sent Currency`, `Received Currency`, and
`Fee Currency` before the parse `try` block. Reuse those already-computed normalized tickers to identify affected
loan assets in the `except` block; do not re-parse raw currency strings there. If no loan-affected asset can be
attributed, log at ERROR without asset attribution and do not create an unknown placeholder.

- [x] Write failing tests in `test_crypto_fifo.py`:
  - `TestParseThParseFail#test_parse_error_records_asset_and_row_index`: TH with one malformed WBTC buy row
    (bad decimal) and one valid WBTC sell row; run through `parse_th_for_loan_affected_assets`; assert the returned
    parse-failure structure records `WBTC` and the failing row index.
  - `TestParseThParseFail#test_parse_error_logged_at_error_level`: same setup; assert `caplog` contains an
    ERROR-level record mentioning the row index.
  - `TestParseThParseFail#test_parse_error_on_unrecognised_asset_does_not_pollute_parse_failures`: TH with a
    malformed row where only a non-loan-affected asset is involved; assert the parse-failure structure is empty.
  - `TestParseThParseFail#test_parse_error_on_fee_only_row_attributes_fee_asset`: malformed row where only
    `Fee Currency` is loan-affected; assert the fee asset is recorded in the parse-failure structure.
- [x] Run → expect RED: `uv run pytest tests/unit/application/test_crypto_fifo.py -k "ParseFail" -v`
- [x] Implement in `parse_th_for_loan_affected_assets`:
  - Add `parse_failures_by_asset: dict[str, list[int]] = {}` (or equivalent structured record) before the row loop.
  - In the `except ValueError` block: change `logger.warning` to `logger.error`; use the already-normalized
    `sent_currency`, `received_currency`, and `fee_currency` values to attribute the failing row to all affected
    loan assets.
  - Return a 4-tuple `(acquisitions, consumptions, phantom_sending_transfers, parse_failures_by_asset)`.
  - Update all callers of `parse_th_for_loan_affected_assets` to unpack the 4th element.
- [x] In `_rebuild_fifo_for_loan_affected_assets`, after `all_realizations` is built, flag realizations for
  assets present in `parse_failures_by_asset` with `review_required=True` and an actionable `review_reason`
  that preserves row attribution.
- [x] Write failing test in `test_crypto_reporting.py`:
  - `test_rebuild_fifo_marks_review_required_when_asset_has_parse_errors`: integration test using a TH file
    with one malformed row for WBTC; after `_rebuild_fifo_for_loan_affected_assets`, assert all WBTC
    `CryptoCapitalGainEntry` objects have `review_required=True`.
- [x] Run → expect GREEN: `uv run pytest tests/unit/application/test_crypto_fifo.py tests/unit/application/test_crypto_reporting.py -k "ParseFail or parse_error" -v`
- [x] Commit: `fix: surface TH parse errors as asset-level review flags (Finding #2)`

---

### Task 2: Key carry-over by (tx_key, platform) (Finding #5)

**Files:**
- `src/shares_reporting/application/crypto_fifo.py`
- `src/shares_reporting/application/crypto_reporting.py`
- `tests/unit/application/test_crypto_fifo.py`
- `tests/unit/application/test_crypto_reporting.py`

**Behaviour change:** The `merged_carryover` dict assembled inside `_rebuild_fifo_for_loan_affected_assets`
currently maps `tx_key → Decimal`. Change it to map `(tx_key, platform) → Decimal`, where `platform` is the
*sender platform that produced the carry-over*. Update `resolve_cross_asset_exchanges` in
`src/shares_reporting/application/crypto_fifo.py` to accept the platform-keyed data and look up by
`(tx_key, sender_platform)`.

**Required sender-platform wiring:** the current `tx_key_to_sender` map built by `_build_cross_asset_order`
contains sender **assets**, not sender **platforms**. Task 2 must add an explicit platform-aware correlation map
(e.g. `tx_key_to_sender_platforms` or `tx_key_to_sender_contexts`) built from the non-taxable sender consumptions,
and thread that map through `_rebuild_fifo_for_loan_affected_assets` into `resolve_cross_asset_exchanges`.
Without this extra wiring, the new `(tx_key, platform)` key cannot be resolved correctly.

**Key matching in `resolve_cross_asset_exchanges`:** with `(tx_key, platform)` keys, match only entries whose
`tx_key` equals the deferred acquisition's `tx_key` and whose platform is present in the sender-platform map for
that transaction. Keep the existing multi-sender aggregation semantics, but now aggregate over `(sender asset,
 sender platform)` matches rather than assets alone.

The "same tx_key, multiple platforms" warning (currently triggered when the same `tx_key` appears in
`merged_carryover` from two platforms) should become: log the collision as INFO (it is now expected for
cross-platform transfers resolved in Task 3) rather than WARNING. Remove the WARNING for now (Task 3 will
re-introduce it only for unresolved cases).

- [x] Write failing tests in `test_crypto_reporting.py` and `test_crypto_fifo.py`:
  - `TestResolveCarryoverPlatformKey#test_same_tx_key_different_platforms_not_summed`: two platform-specific
    carry-over contributors for the same asset and `tx1`; verify `merged_carryover` contains distinct
    `("tx1", "PlatformA")` and `("tx1", "PlatformB")` entries.
  - `TestResolveCarryoverPlatformKey#test_resolve_uses_sender_platform_when_looking_up_carryover`: deferred
    acquisition with `tx_key="tx1"` and sender platform `Kraken`; verify only `("tx1", "Kraken")` contributes.
  - `TestBuildCrossAssetOrder#test_sender_platforms_are_exposed_for_platform_key_lookup`: assert the new
    sender-platform correlation map exposes the producing platform needed by `resolve_cross_asset_exchanges`.
- [x] Run → expect RED
- [x] Update `_build_cross_asset_order` (or add a sibling helper) to return the sender-platform correlation
  data needed for `(tx_key, platform)` lookups.
- [x] Update `_rebuild_fifo_for_loan_affected_assets`: change `merged_carryover` key construction from `key`
  to `(key, platform)` and remove the multi-platform-sum WARNING.
- [x] Update `resolve_cross_asset_exchanges` in `application/crypto_fifo.py`: accept platform-keyed carry-over
  data plus the new sender-platform map; look up by `(acq.tx_key, sender_platform)` for each matched sender
  platform and sum only the matched contributors.
- [x] Update the call from `_rebuild_fifo_for_loan_affected_assets` to pass the platform-keyed carry-over data
  and the new sender-platform map.
- [x] Run → expect GREEN
- [x] Commit: `fix: key cross-asset carry-over by (tx_key, platform) to prevent platform cross-contamination (Finding #5)`

---

### Task 3: Transfer lot carry-over (Finding #1)

**Files:**
- `src/shares_reporting/application/crypto_fifo.py`
- `src/shares_reporting/application/crypto_reporting.py`
- `tests/unit/application/test_crypto_fifo.py`
- `tests/unit/application/test_crypto_reporting.py`

**Behaviour change (high complexity):** model cross-platform transfer of loan-affected assets as sender-platform
carry-over plus a receiver deferred acquisition, but do **not** assume the existing asset-level single-pass flow can
resolve same-asset transfers. In the current pipeline, `_rebuild_fifo_for_loan_affected_assets` resolves deferred
acquisitions **before** it computes any per-platform FIFO for that same asset, so a WBTC Kraken→ByBit transfer has
no WBTC sender carry-over available yet. This task therefore requires a pipeline redesign for same-asset transfers:
either (a) a second within-asset resolution pass after sender-platform FIFO results exist, or (b) platform-level
processing order inside the asset. The `phantom_sending_transfers` mechanism remains the fallback for transfers
where the receiver platform is unknown or the intra-asset carry-over cannot be resolved.

**Implementation steps inside `_handle_transfer`:**

When `sent_currency in loan_affected_assets` and `sent_amount > ZERO`:
1. Determine `sending_platform = normalize_platform_name(row.get("Sending Wallet", ""))`.
2. Determine `receiving_wallet = row.get("Receiving Wallet", "").strip()` and
   `receiving_platform = normalize_platform_name(receiving_wallet)`.
3. If `receiving_platform` is empty or unknown, fall back: add to `phantom_sending_transfers` and log
   WARNING (existing behaviour).
4. Otherwise: emit a non-taxable consumption from `sending_platform` (amount=`sent_amount`, taxable=False,
   `event_type="transfer_out"`) and a deferred acquisition on `receiving_platform`
   (amount=`received_amount`, cost_basis_eur=ZERO, `source_type="transfer_in_deferred"`, same `tx_key`).
5. If the fee currency equals `sent_currency` (fee deducted from same asset), the net `received_amount =
   sent_amount - fee_amount`. The fee disposal is already emitted separately by the existing fee-disposal path.
   Do NOT double-count it: do not add a second fee disposal in this new path.

**Update `resolve_cross_asset_exchanges` / intra-asset transfer resolution:** add handling for
`source_type="transfer_in_deferred"`, but only after introducing sender-platform correlation from Task 2 and a
same-asset resolution point that runs *after* the sender platform's FIFO carry-over exists. Reusing the current
pre-FIFO `resolve_cross_asset_exchanges` call is insufficient for same-asset transfers because `fifo_by_asset`
does not yet contain the current asset's sender-platform carry-over.

**Carry-over proportioning for fee deduction:** the sender's non-taxable consumption covers `sent_amount`
(including the fee portion). The receiver's deferred acquisition covers `received_amount = sent_amount - fee_amount`.
When resolving, scale the carry-over proportionally: `resolved_cost = carryover * received_amount / sent_amount`.
Add this scaling inside `resolve_cross_asset_exchanges` for `transfer_in_deferred` acquisitions
(unlike cross-asset exchanges where amounts differ by nature, this is fee-driven shrinkage of a same-asset lot).

**Keep `phantom_sending_transfers` only where resolution truly failed, but preserve enough metadata to make that
decision:** the current `phantom_sending_transfers` contract is a `frozenset[(asset, platform, date)]`, while
`_apply_phantom_lot_flags` sees only `AssetFifoResult.realizations`, which no longer contain `tx_key`. That is not
enough information to skip only the transfer rows that were successfully resolved. Extend the phantom-transfer
metadata (or apply the filter earlier in the pipeline) so the code can distinguish resolved vs unresolved transfer
markers without guessing from date alone.

- [x] Write failing tests in `test_crypto_fifo.py`:
  - `TestHandleTransfer#test_transfer_emits_nontaxable_consumption_on_sender`: TH with a WBTC `transfer`
    row, sending from Kraken; assert `consumptions["WBTC"]` contains one entry with `event_type="transfer_out"`,
    `taxable=False`, `platform="Kraken"`.
  - `TestHandleTransfer#test_transfer_emits_deferred_acquisition_on_receiver`: same row; assert
    `acquisitions["WBTC"]` contains one entry with `source_type="transfer_in_deferred"`, `platform="ByBit"`,
    `cost_basis_eur=Decimal("0")`.
  - `TestHandleTransfer#test_transfer_with_same_asset_fee_uses_received_amount_for_deferred`: transfer row
    with `Sent Amount=1.0`, `Received Amount=0.99`, `Fee Amount=0.01`, `Fee Currency=WBTC`; assert deferred
    acquisition `amount=Decimal("0.99")` and separate fee disposal `amount=Decimal("0.01")`.
  - `TestHandleTransfer#test_transfer_with_unknown_receiver_falls_back_to_phantom_flag`: transfer row with
    empty `Receiving Wallet`; assert `phantom_sending_transfers` is non-empty and NO deferred acquisition is
    created.
- [x] Run → expect RED
- [x] Implement changes in `_handle_transfer()` as described above.
- [x] Write failing tests in `test_crypto_fifo.py` and `test_crypto_reporting.py`:
  - `TestFifoCrossPlatformTransfer#test_transfer_lot_cost_basis_carries_to_receiver_platform`: unit-level
    sender/receiver carry-over resolution for one asset across two platforms.
  - `TestFifoCrossPlatformTransfer#test_transfer_with_fee_proportions_cost_correctly`: assert the receiver lot
    cost scales by `received_amount / sent_amount` and the same-asset fee remains a separate taxable disposal.
  - `test_rebuild_fifo_resolves_same_asset_cross_platform_transfer_after_sender_platform_fifo`: integration test
    at `_rebuild_fifo_for_loan_affected_assets` level proving the pipeline change really resolves a same-asset
    Kraken→ByBit transfer instead of leaving the deferred acquisition unresolved.
  - `test_apply_phantom_flags_only_for_unresolved_transfers`: verify phantom warnings remain for unknown/failed
    receiver cases but not for transfers that were actually resolved.
- [x] Run → expect RED
- [x] Implement the chosen intra-asset resolution design (second pass or platform-ordered processing) so
  `transfer_in_deferred` is resolved only after the sender platform's carry-over exists.
- [x] Add proportional scaling for `transfer_in_deferred`: `resolved_cost = carryover * received_amount / sent_amount`.
- [x] Update phantom-transfer metadata and `_apply_phantom_lot_flags` (or move the filtering earlier) so only
  unresolved transfers continue to flag later sender-platform realizations.
- [x] Run → expect GREEN
- [x] Commit: `fix: carry FIFO lot across platforms for loan-affected asset transfers (Finding #1)`

---

### Task 4: Extract Koinly correlation fields to application layer (Finding #7)

**Files:**
- `src/shares_reporting/domain/crypto_fifo.py`
- `src/shares_reporting/application/crypto_fifo.py`
- `src/shares_reporting/application/crypto_reporting.py`
- `tests/unit/application/test_crypto_fifo.py`
- `tests/unit/application/test_crypto_reporting.py`

**Behaviour change (structural):** Remove `tx_key: str` and `source_row_index: int` from
`CryptoAcquisition` and `CryptoConsumption`, but do **not** remove carry-over data from the FIFO result contract
without introducing an explicit application-layer replacement. Current callers need both the financial realizations
and the carry-over correlation output.

**Domain entities after change:**
- `CryptoAcquisition`: `date`, `asset`, `amount`, `cost_basis_eur`, `fee_eur`, `source_type`, `wallet`,
  `platform`, `review_required`, `review_reason`: pure financial acquisition facts.
- `CryptoConsumption`: `date`, `asset`, `amount`, `proceeds_eur`, `event_type`, `taxable`, `wallet`,
  `platform`, `notes`, `review_required`, `review_reason`: pure financial disposal facts.
- `CryptoFifoRealization`: already clean after earlier CR fixes (no tx_key).
- Domain `AssetFifoResult`: either stays domain-local until follow-up cleanup, or is replaced by an explicit
  application-layer FIFO result type that carries both `realizations` and carry-over correlation data. The plan
  must keep a concrete producer/consumer contract for carry-over values; they cannot simply disappear.

**New application-layer types** (add to `crypto_fifo.py` or a new `_fifo_context.py` under `application/`):
```python
@dataclass(frozen=True)
class AcquisitionContext:
    """Application-layer correlation wrapper for CryptoAcquisition."""
    acq: CryptoAcquisition
    tx_key: str
    source_row_index: int

@dataclass(frozen=True)
class ConsumptionContext:
    """Application-layer correlation wrapper for CryptoConsumption."""
    con: CryptoConsumption
    tx_key: str
    source_row_index: int
```

**Migration path:**
- `parse_th_for_loan_affected_assets` returns `dict[str, list[AcquisitionContext]]` and
  `dict[str, list[ConsumptionContext]]` instead of bare domain entity dicts.
- `compute_fifo_for_asset` accepts `list[AcquisitionContext]` and `list[ConsumptionContext]`; accesses
  `ctx.acq` / `ctx.con` for financial facts and `ctx.tx_key` / `ctx.source_row_index` for correlation.
- `_build_cross_asset_order` must also be updated to consume the context wrappers rather than bare domain entities.
- Introduce an explicit application-layer FIFO result contract (for example `PlatformFifoResult`) that contains
  `realizations`, platform-keyed carry-over data, and `partial_carryover_tx_keys`; thread that through
  `_rebuild_fifo_for_loan_affected_assets` and `resolve_cross_asset_exchanges`.
- `resolve_cross_asset_exchanges` accepts `dict[str, list[AcquisitionContext]]` instead of bare dicts; the
  resolved output is `dict[str, list[AcquisitionContext]]` with updated `acq.cost_basis_eur` (via
  `replace(ctx, acq=replace(ctx.acq, cost_basis_eur=...))`).
- All test helpers `_acq(...)` and `_con(...)` in `test_crypto_fifo.py`, plus helper constructors in
  `TestBuildCrossAssetOrder`, must return `AcquisitionContext` / `ConsumptionContext`; update all call sites.

**Note:** This is the most invasive change. Do it LAST (after Tasks 1–3) so the correlation fields are still
available during those behaviour fixes. Verify no circular imports: `domain/crypto_fifo.py` must not import
from `application/`.

- [x] Write failing tests in `test_crypto_fifo.py`:
  - `TestAcquisitionContext#test_acquisition_context_wraps_domain_entity`: construct `AcquisitionContext`
    with a domain `CryptoAcquisition` and assert `.acq.cost_basis_eur` and `.tx_key` are accessible.
  - `TestAcquisitionContext#test_parse_th_returns_acquisition_contexts_not_bare_entities`: `parse_th_for_loan_affected_assets`
    with a valid buy row; assert the returned dict value is a list of `AcquisitionContext` objects.
- [x] Run → expect RED
- [x] Add `AcquisitionContext` and `ConsumptionContext` to `application/crypto_fifo.py`.
- [x] Add an explicit application-layer FIFO result type carrying realizations + carry-over correlation data.
- [x] Update `parse_th_for_loan_affected_assets` to return context wrappers.
- [x] Update `compute_fifo_for_asset` to accept and unpack context wrappers and to return the new application-layer
  FIFO result type.
- [x] Update `_build_cross_asset_order` to accept the context wrappers.
- [x] Update `resolve_cross_asset_exchanges` to accept and return context wrappers.
- [x] Remove `tx_key` and `source_row_index` from `CryptoAcquisition` and `CryptoConsumption` in `domain/crypto_fifo.py`.
- [x] Update `_rebuild_fifo_for_loan_affected_assets` to consume the new application-layer FIFO result type.
- [x] Update all test helpers in `test_crypto_fifo.py` and all call sites in `test_crypto_reporting.py`.
- [x] Verify no circular imports: `uv run python -c "from shares_reporting.domain.crypto_fifo import CryptoAcquisition"`
- [x] Run → expect GREEN: `uv run pytest tests/unit/ -q`
- [x] Commit: `refactor: extract Koinly correlation fields from domain entities to application-layer wrappers (Finding #7)`
