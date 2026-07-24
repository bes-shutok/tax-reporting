# Crypto Reporting Guidelines

Implementation guidelines for the `Crypto` worksheet and related Koinly ingestion behavior.

## Terminology

- `CRG-xxx`: numbered crypto-reporting guideline for this repository.
- Official rule: behavior driven directly by archived tax/operator source material.
- Repository override: an explicit local policy used when the user wants a filing-facing simplification that is narrower than the upstream platform's global footprint.

## Official Source Set

- `docs/maintenance/tax/laws/pt/crypto-tax/official/cirs_2025-07_code_consolidated.pdf`
- `docs/maintenance/tax/laws/pt/crypto-tax/official/at_folheto_criptoativos_2026-01-12.pdf`
- `docs/maintenance/tax/laws/pt/crypto-tax/official/at_piv_22065_2023-11-06.pdf`
- `docs/maintenance/tax/laws/pt/crypto-tax/official/at_piv_21506_undated.pdf`
- `docs/maintenance/tax/laws/pt/crypto-tax/official/modelo3_anexo_e_2025.pdf`
- `docs/maintenance/tax/laws/pt/crypto-tax/official/modelo3_anexo_j_2025.pdf`
- `docs/maintenance/tax/laws/pt/crypto-tax/official/at_oficio_circulado_20269_2024.pdf`
- `docs/maintenance/tax/laws/pt/crypto-tax/official/at_oficio_circulado_20278_2025.pdf`

## Official Findings

**CRG-001**
For non-business taxpayers, crypto-related remuneration received in the form of cryptoassets is not taxed at receipt. It moves to later taxation on disposal of the received cryptoasset.

**CRG-002**
Immediate category E reporting applies only when the remuneration does not itself assume the form of cryptoassets.

**CRG-003**
Under the current official design, a crypto-denominated reward can ultimately produce no Portuguese tax if the later disposal falls within the long-holding exclusion and no anti-exception rule disqualifies it. Do not force immediate taxation merely because that outcome feels conservative.

**CRG-004**
The same `País da Fonte` resolution rule must be used across crypto rewards and crypto capital gains.

## Filing Guidance

**CRG-005**
Never use taxpayer residence as the crypto `País da Fonte` merely because the activity happened while the taxpayer was in Portugal.

**CRG-006**
Use this source-country fallback order for DeFi rows:
- interface legal entity
- protocol / foundation / sponsoring legal entity
- validator operator for identifiable native staking

**For DEX (Decentralized Exchange) transactions specifically:**

The country determination follows the same hierarchy, with these clarifications:

1. **Interface legal entity**: If the DEX has a frontend UI with terms of service (e.g., Uniswap app interface), use that entity.
2. **Protocol / foundation**: For pure protocol interactions, use the chain's foundation entity (e.g., Ethereum Foundation → Switzerland for Uniswap on Ethereum).
3. **No separate DEX mapping required**: A DEX like Uniswap running on Ethereum uses the Ethereum chain mapping (Switzerland via Ethereum Foundation), unless the DEX has its own explicit legal entity.

**Examples:**
- Uniswap on Ethereum → Switzerland (via Ethereum Foundation)
- PancakeSwap on BNB Chain → Spain (via BNB repository override for EEA filing)
- Pure protocol interaction → Use chain origin from `operator_chain_origin_registry.md`

**CRG-007**
Taxable-now reward aggregates must be IRS-ready when projected to the `Reporting` worksheet: filing-facing rows written to the `CAPITAL INVESTMENT INCOME` section must not be missing mandatory IRS fields, and broad placeholders such as `Multiple jurisdictions` must not appear when a repository mapping policy exists. The `Crypto Rewards` worksheet is support detail and classification reconciliation; it retains per-row trace data and deferred-by-law entries but is not a second filing target for taxable-now aggregates.

## Data Normalization Guidance

**CRG-009**
`chain` is a normalized reporting field distinct from the raw wallet name. Keep the raw wallet label, but derive the candidate chain from that label and resolve the final chain against trusted archived sources under `docs/maintenance/tax/crypto-origin/`.

**CRG-010**
When a wallet / platform label is not sufficient to determine a defensible chain, use `Unknown` explicitly rather than guessing from the asset symbol alone.

**CRG-011**
When adding or changing a crypto chain/operator mapping, keep the source archive, effective registry, and mapping decision log synchronized under `docs/maintenance/tax/crypto-origin/`.

## Current Mapping Guidance

**CRG-012**
EEA-facing CeFi defaults currently used by this repository are:
- `Kraken -> Ireland`
- `Gate.io -> Malta`

**CRG-013**
`Binance` / `Binance Smart Chain` must not render as `Multiple jurisdictions` in the workbook. The current repository override for Europe-facing output is `Spain`, and this should remain documented as a local filing policy rather than a chain-governance fact.

**CRG-014**
Chain-origin mappings collected so far include:
- `Berachain -> British Virgin Islands`
- `Starknet -> Cayman Islands` (inferred from official foundation materials; keep provenance visible)
- `zkSync ERA -> Cayman Islands`
- `Solana -> Switzerland`
- `TON -> Switzerland`
- `Ethereum -> Switzerland`
- `Aptos -> Cayman Islands`

## Platform Assumptions vs Row-Level Review Flags

**CRG-016**
Distinguish between platform-level review concerns and row-level review flags:

- **Platform-level concerns** (e.g., "Bybit uses account-region specific entities; verify your account region"): These apply to ALL transactions from a platform. Display them in the "Platform Assumptions" worksheet, a complete manifest of every platform in the report. Platform concerns must NOT set `review_required=True` on individual transaction rows.

- **Row-level review flags** (e.g., missing cost basis, date parsing errors, phantom transfers, FIFO pool exhaustion): These are specific to individual transactions and must be shown on the row with "YES: <reason>", with the row highlighted red.

**`OperatorOrigin` fields:**
- `platform_assumption`: free-text note shown in the Platform Assumptions tab (informational; does not trigger red rows)
- `platform_review_required: bool`: whether this platform must be manually verified before filing; controls red highlighting and "YES"/"NO" in the Platform Assumptions tab; does NOT affect individual transaction rows
- `review_required: bool` / `review_reason: str`: row-level flag; triggers "YES: <reason>" on the transaction row and red row fill; set only for per-transaction issues (temporal validity failures, unknown platforms, FIFO anomalies)

**Platform Assumptions tab** shows ALL platforms seen in the data (not just those with assumption text), columns: Platform | Operator Entity | Country | Confidence | Review Required | Assumption Note | Transaction Count. Rows with `platform_review_required=True` are sorted first and highlighted red.

**Test fixture rule:** Tests that verify row-level "YES:"/"NO" rendering must use explicit hardcoded `review_required` / `review_reason` values on the entry, not delegate to `origin.review_required`. The latter changes when the platform mapping changes and will silently break the rendering test.

**CRG-020**
Re-evaluate the aggregated row's review flag against the aggregated state, not against the per-lot state. When `_aggregate_capital_entries` joins per-lot `review_reason` values into the aggregated disposal row, the joined reason is a pre-filter input, not the final word: `_re_evaluate_aggregated_review` (inlined in `aggregation.py`) then re-derives the aggregated entry's `review_required` / `review_reason` from the aggregated `cost_eur`, `proceeds_eur`, and `gain_loss_eur`.

- **Zero-basis reasons are dropped** from the aggregated row when the aggregated values are material: `cost_eur > 0 AND proceeds_eur > 0 AND abs(gain_loss_eur) >= _MATERIALITY_THRESHOLD` (= `Decimal("1")`, reused from `_filter_immaterial_entries`). Zero-basis reasons are matched by stable prefix (`"Zero EUR value for known crypto asset"`, `"Zero acquisition cost"`, `"Zero disposal proceeds"`), not by full-string equality, so minor wording edits to the upstream literals do not silently break the strip set. A single noisy lot (e.g. one Koinly `FEE` tracking entry, or one reward lot with no price data) inside a multi-lot disposal no longer flags the aggregated row.
- **Non-zero-basis reasons survive aggregation unchanged.** Reasons unrelated to zero basis (phantom lot, operator-origin review, homoglyph, OGR override, missing-cost-basis-with-impact, foreign-tax parse failure) are preserved on the aggregated row when material.
- **Per-lot signals are not silenced.** The lot-level `review_required` / `review_reason` on `CryptoCapitalGainEntry` and `CryptoFifoRealization` remain set as before; the dropped per-lot noise still appears in `context.review_entries` and in the per-lot DEBUG log (file handler at `DEBUG`; the aggregate WARNING summary carries the warning-level signal on the console). The Excel aggregated row is the only thing cleaned up. No data is silently lost.
- **Materiality gate is a single constant.** Reuse `_MATERIALITY_THRESHOLD`; do not introduce a second materiality constant for the review-flag gate.
- **Both fields are owned atomically by the helper.** `_re_evaluate_aggregated_review` returns `(review_required, review_reason)` and the caller applies both in a single `replace(...)` call; `CryptoCapitalGainEntry.__post_init__` raises on the inconsistent pair `review_required=True AND review_reason=None`, so partial application crashes the pipeline. The helper also short-circuits on `review_reason is None` (the default clean-disposal path) before touching the materiality gate.

Cross-reference: plan `docs/history/plans/completed/2026-07-15-review-flag-aggregation-boundary.md`, `crypto_implementation_guidelines.md` "Aggregation of review_reason" (the joined-reason reduction is the pre-filter input CRG-020 re-derives from).

## Reward Dust Partition

**CRG-021, Reward dust partition for taxable-now rewards is presentation-layer and uses has-any-priced-row, not popular-token membership.** Zero-value taxable-now reward rows are split into a "Dust summary:" outer-header block on the Crypto Supplementary tab (Section 2) - outer bold header followed by a "Taxable-now dust (priced-asset rounding)" sub-header, then a 5-column table (Asset | Wallet | Rows | Summed Value (EUR) | Category), with a blank spacer row above the outer header (matches the section-boundary spacer convention) - iff the asset has at least one `value_eur > 0` row elsewhere in the export. Assets with no priced rows anywhere (e.g. OSBGT, PBERA, SWBERA, STBGT, illiquid wrappers Koinly cannot price) keep their per-row `YES` flag. The popular-token set (`popular_crypto_tokens.json`) is a separate concern with three consumers in `crypto_reporting.py` (today `:730, :955, :1012`; the `:730` site relocates inside the `is_all_zero` block under this plan, lookup unchanged, line number shifts); do not prune it to fix the dust discriminator. Dust partition does not mutate `reward_entries`, totals, or the Reporting worksheet, it is a view. Accepted risks: (A1) per-export "priced" proxy may misclassify a globally-priced asset whose every row in this export rounds to zero (cosmetic only, supplementary-tab noise, tax numbers unchanged); the discriminator is export-precision-coupled, if Koinly raises export precision above 2 decimals, assets whose rows previously all rounded to zero may flip into the "priced" set, so year-over-year dust-summary comparisons must account for export precision (the dust-line hint already suggests re-exporting at higher precision as the workaround); (A2) no runtime flag to disable Part 7, AGENTS.md rule 130 (backward-compat flag tests) does not apply because Part 7 is byte-for-byte presentation-layer only (Invariant 1: `reward_entries`, `taxable_now_total_eur`, `deferred_total_eur`, and the Reporting worksheet's OTHER CAPITAL INVESTMENT INCOME line are unchanged **on the taxable-now side**; the deferred side is parse-time skip per CRG-022); the "disabled" state is the pre-Part-7 rendering, recoverable by reverting the partition, and no tax output depends on the partition so there is no behavior to preserve via a flag. See CRG-022 for the deferred-side companion (parse-time skip, not presentation-layer).

**CRG-022, Deferred-reward zero-value skip at parse time + outer-header suppressed-rewards block; tax math unchanged.** Zero-value `DEFERRED_BY_LAW` reward rows are removed from `reward_entries` at parse time and relocated to a full-fidelity `skipped_zero_value_deferred_rewards: list[CryptoRewardIncomeEntry]` field on `CryptoTaxReport` (NOT count-only - every skipped row retains asset/wallet/platform/amount/value_eur/tax_classification verbatim, per Invariant 1 of the deferred-reward-dust-skip plan). The Crypto Supplementary tab (Section 3) renders an outer-header block from that list: a blank spacer row, then a bold outer header "Suppressed zero-value deferred rewards", followed by TWO sub-headers each with its own 5-column table (Asset | Wallet | Rows | Summed amount | Category) sorted per-`(asset, wallet)` - "Deferred dust (priced-asset rounding)" for dust rows (Category=`"dust"`), "Deferred unpriced (no Koinly price feed)" for unpriced rows (Category=`"unpriced"`); each sub-header renders only when its bucket is non-empty. Summed amount is native-unit `entry.amount` formatted with `:.8f` (8 dp matches Koinly's native precision). The sub-header carries the bucket label only; the Category column carries the short discriminator. (The prior verbose reason was removed when the column-table restructure deleted the single-line format.) (The predecessor plan's r1 review collapsed the buckets into one merged block; user feedback on the rendered sheet iterated twice - first the merged clause was hard to scan, then the clumped single-line format was hard to read column-by-column, so each bucket became a proper column table mirroring the sheet's other table sections.) The dust-vs-unpriced discriminator is the SAME as CRG-021's - priced-asset zero -> dust; no priced row anywhere -> unpriced - extracted as the shared `_priced_assets_in_export(reward_entries) -> frozenset[str]` helper used by BOTH `_partition_taxable_now` (CRG-021) and `_partition_skipped_rewards` (CRG-022) per AGENTS.md rule 30 (sibling aggregators must use byte-identical patterns or a shared helper, otherwise they silently desynchronize). The Section 4 deferred reconciliation line splits into three counts: `("Deferred detail rows", N)`, `("Deferred dust rows (suppressed from detail)", M)`, `("Deferred unpriced rows (suppressed from detail)", K)`; the Crypto Reconciliation sheet adds a sibling `("Skipped zero-value deferred rewards (audit)", len(skipped_zero_value_deferred_rewards))` so the bare `Reward rows` count (which drops because zero-value deferred rows leave `reward_entries`) stays auditable cross-sheet. The user-facing `Total reward rows (raw)` count drops accordingly (illustrative example: a large number of zero-value deferred rows on a real crypto-heavy 2025 export; the exact count is documented context from the plan's real-data trace, NOT a hardcoded threshold, and is omitted here as personal portfolio data). Tax math is byte-for-byte unchanged: `aggregate_taxable_rewards` filters to `taxable_now` (deferred rewards are filtered out by definition); `reward_total_eur` sums `value_eur` and zero-value rows contribute `Decimal("0")`; the FIFO / cost-basis pipeline reads NEITHER `reward_entries` NOR `skipped_zero_value_deferred_rewards` (grep-clean across `crypto_fifo/`), so the skip is basis-neutral (per Invariant 2). Compute-once-reuse (Invariant 5): `_partition_skipped_rewards` is called exactly once in `write_crypto_supplementary_sheet`, next to the existing `_partition_taxable_now` call, and the resulting `(dust_rows, unpriced_rows)` are passed into both the Section 3 block render and the Section 4 reconciliation - never re-partitioned. No platform-evidence guard (the real-data trace showed the protected `(platform, wallet)` tuples of surviving non-zero rewards already cover every distinct tuple in the export, so the parse-time skip starves `assumptions_sheet._accumulate` of nothing; the specific count is omitted here as personal portfolio data). No `_UNPRICED_NON_DISPOSEABLE_PATTERNS` substring filter on the native-unit amount sum (a no-op on the trace's unpriced-asset list and AGENTS.md's no-hardcoded-value rule cuts against introducing values with no data showing they are needed). Cross-reference: plan `docs/history/plans/completed/2026-07-19-deferred-reward-dust-skip.md`; CRG-021 (taxable-now side companion); glossary entries "Deferred dust" and "Unpriced deferred reward".

## Other Gains Report (OGR) Validation

**CRG-017**
The Other Gains Report (OGR) provides authoritative DIRECTION for crypto disposal events (gain vs loss), while the Capital Gains (CG) report provides MAGNITUDE via FIFO calculation. The system uses directional authority semantics, not wholesale replacement.

**Directional authority logic:**
- **Direction conflict (OGR and CG have different signs):** Use OGR direction with CG magnitude
  - Example: CG=+100 EUR (gain), OGR=-147 EUR (loss) → final = -100 EUR (loss with CG magnitude)
  - Flag with RED fill and review_required=True, reason="OGR direction override"
- **Directions agree (same sign):** Use OGR magnitude (more accurate for derivatives/futures)
  - Example: CG=-100 EUR, OGR=-105 EUR → final = -105 EUR (use OGR magnitude)
  - Flag with YELLOW fill only if magnitude exceeds thresholds

**Magnitude thresholds (both conditions must be met):**
- Relative difference > 5% (prevents noise on near-zero percentage fluctuations)
- Absolute difference > 1 EUR (prevents noise on small absolute values)

**Implementation details:**
- OGR data is indexed by `(disposal_date, asset, wallet)` and matched to CG entries
- Validation is applied per-lot before aggregation via `_apply_ogr_direction_override()`
- `OgrValidationResult` is attached to each entry with comparison metadata
- Multiple lots for the same disposal each get OGR validation attached; aggregation combines them
- Excel conditional formatting priority: RED (direction conflict) > YELLOW (magnitude diff) > entry-level review flags

**See also:** the "OGR Directional Authority vs Wholesale Replacement" lesson, plan `docs/history/plans/2026-06-10-ogr-validation-design.md`

## Derivatives P&L Tab (art. 10(1)(e))

**CRG-018**
The Derivatives P&L tab is the filing surface for realized derivatives P&L when derivatives
are separated from spot crypto per DP-012 (`separate_derivatives_reporting=True`).

**(a) When the tab renders.** The tab is created in the workbook only when the jurisdiction
flag `separate_derivatives_reporting` is `True` (DP-012). When `False`, the tab is not created
and derivatives rows are folded into Crypto Gains via the legacy PT-C-033 override path; output
is byte-identical to the pre-change behavior.

**(b) Aggregation key.** Derivatives entries are aggregated by
`(date, asset, platform, event_type)` mirroring `_aggregate_capital_entries` structure, but with
`event_type` (`DerivativesEventType.PROFIT` / `LOSS`) replacing `holding_period`. A Profit and a
Loss on the same `(date, asset, platform)` must NOT collapse into a single net; they stay separate
rows so the user can trace each realized event.

**(c) Legal category citation in the header.** The worksheet header cites "CIRS art. 10(1)(e)"
explicitly so a reader cannot mistake the category for cryptoasset treatment under art. 10(1)(k).
This is an auditability requirement (per Plan Evaluation Criteria), not cosmetic.

**(d) Interaction with the Crypto Gains tab.** When the flag is on, the Crypto Gains tab contains
ONLY spot crypto disposals (art. 10(1)(k), 365-day exemption applies). Derivatives P&L never mixes
into Crypto Gains. Spot-classified OGR rows (e.g. an OGR `Type=Loss` whose EUR value matches a CG
lot's `proceeds_eur` within `Decimal("0.01")` tolerance) stay in the spot_index and continue through
the PT-C-033 direction-override path. Derivatives-classified OGR rows route to `derivatives_entries`
and never enter `_apply_ogr_direction_override`, so spot CG lot signs cannot be flipped by
derivatives OGR rows (Design Invariant 6). Cross-reference: PT-C-034.

**(e) Loss-deductibility footnote.** The tab includes a footnote reading "Losses are deductible
against other Category G gains; carry-forward 5 years per PT-C-016" whenever any derivatives entry
has `event_type=LOSS`. The footnote is omitted only when no loss entry exists, to avoid implying
deductibility that the user's data does not exercise.

**See also:** PT-C-034 (derivatives separation rule), PT-C-033 (flag-off legacy path),
plan `docs/history/plans/2026-06-13-derivatives-separation.md`.

## Token Origin Resolution

**CRG-015**
Token origin is derived from implicit `(date, asset, wallet)` correlation between the Koinly capital gains report and the Koinly transaction history. The capital gains CSV provides no transaction ID, lot ID, or hash that directly links to the transaction history, so all matching is best-effort correlation, not a direct foreign-key link.

Origin resolution uses the `TokenOriginResolver` class:

- **Inputs**: Koinly transaction history CSV (parsed at construction time to build a lookup indexed by `(date, asset, wallet)`).
- **Matching**: For each capital gains row, the resolver looks up acquisition events matching `(Date Acquired, Asset, normalized wallet)` from the transaction history.
- **Acquisition methods**: `direct_purchase`, `swap_conversion`, `bridge_transfer`, `defi_yield`, `reward`, `transfer`, `unknown`.
- **Confidence levels**:
  - `high`: the transaction history row has a `TxHash` or other explicit on-chain identifier.
  - `medium`: matched via implicit date/asset/wallet correlation only.
  - `low`: ambiguous match (multiple conflicting records for the same key), capital gains row has `Missing cost basis`, or no match found.
- **Fallback**: When no matching transaction history row exists (CEX internal fills, history gaps, pre-Koinly acquisition dates, or epoch date `1970-01-01`), the resolver returns `unknown` with `low` confidence. It never guesses.
- **Output format**: The `Token origin` column shows `"FROM_ASSET (method, confidence confidence)"` for resolved rows, or blank for unknown.
- **Disclaimer**: Origin values are best-effort correlation from Koinly export data and should be reviewed against source documents before filing.

## Per-Treatment Resolver Identification (Phase E)

**CRG-019**
Identification of every disposal row's treatment is resolver-only: each
pipeline stage delegates to `resolve_treatment`
(`application/crypto/treatment_resolver.py`) over the pre-built
`list[Transaction]` produced once by
`crypto_reporting.py::load_koinly_crypto_report`. There is no legacy
identification path and no per-treatment rollback flag.

History (Phase D, 2026-07-08 through 2026-07-10): the six
`treatment_*_via_resolver` flags (DP-019) mapped 1:1 to the six `Treatment`
members and defaulted to `true`; flipping one to `false` restored the
legacy identification path for that treatment only. Phase E (2026-07-11,
plan `docs/history/plans/completed/2026-07-10-th-tx-view-phase-e.md`) deleted the six
legacy adapters AND the six flags, the `_REQUIRED_TREATMENT_FLAGS` tuple,
the `_enforce_required_treatment_flags` loader guard, and the
`_countries_table_for` helper. The pre-Phase-E flag-mechanic behavior is
preserved in `docs/maintenance/development_lessons.md` lessons #49-#52
(append-only history).

Per-stage identification notes (post-Phase-E):

- **OGR 1:1 override** (`apply_ogr_event_level` in
  `application/crypto/ogr_event_level.py`, called from
  `crypto_reporting.py::load_koinly_crypto_report`): the override is applied
  only to rows whose resolver treatment is `SPOT_DISPOSAL`; a
  non-SPOT_DISPOSAL row sharing the same `(date, asset, wallet)` key is NOT
  overridden.
- **Payment-proceeds correction** (`correct_payment_proceeds` in
  `application/crypto/payment_proceeds.py`): identification comes from the
  resolver (PAYMENT-treatment TH rows). The re-zero snapshot/restore block
  is gone (Phase E Task 7); the OGR override skips PAYMENT rows so the
  residual the re-zero block existed to close cannot occur.
- **Loan-affected asset discovery** (`discover_loan_affected_assets` in
  `application/crypto_fifo/parsing.py`): discovery consults
  `Treatment.LOAN_REPAYMENT` rows AND `Treatment.OTHER` rows whose normalized
  tag is `"loan"` (the borrowing-side principal creation). The extra
  `OTHER + tag=loan` clause (Invariant 11) preserves borrow-only assets so
  they remain in the FIFO rebuild; without it they would drop out silently.
- **Derivatives dedup** (`apply_derivatives_dedup` in
  `application/crypto/derivatives_filter.py`): identification delegates to
  the resolver via `find_derivatives_th_events_from_transactions`; the
  legacy internal tag classifier and the standalone CSV scanner are gone.
  The lot-level dedup algorithm itself is unchanged.
- **Reward/airdrop/LP identification** (`application/token_origin.py`):
  identification delegates to the resolver. The reward/airdrop/LP tag sets
  live once in `TreatmentConfig.reward_tags` / `.airdrop_tags` / `.lp_tags`
  (`application/crypto/treatment_resolver.py`) as the single source of truth
  the resolver consults; Phase E Task 5 deleted the former `token_origin.py`
  duplicates, so there is no longer a parallel definition.
- **OTHER**: no per-stage adapter exists; `Treatment.OTHER` rows flow
  through the standard pipeline without a dedicated override.

Cross-reference: PT-C-038, Phase E plan
`docs/history/plans/completed/2026-07-10-th-tx-view-phase-e.md`.
