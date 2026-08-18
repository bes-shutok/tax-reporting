# On-Chain Transaction Tagger - Design Record

> **Design record** for the on-chain-native transaction parser/tagger (Berachain-first). Captures the full rationale for the 15 design decisions and the four-persona premortem (5 blockers resolved, 4 mitigations adopted). The implementation plan at `docs/history/plans/2026-08-02-on-chain-tx-tagger.md` operationalizes this design. Originally produced via a `grill-with-docs` + `premortem` session on 2026-08-01/02; promoted from `docs/tmp/` to `docs/architecture/` so the rationale survives in-repo.

## Grilling: Bera On-Chain Extract → Standard Transaction Format (Replace Koinly TH)

**Status:** Interview complete; design frozen. All 15 decisions resolved; premortem blockers resolved.
**Date:** 2026-08-01 / 2026-08-02
**Subject:** Design a reader that parses `resources/result/<year>/bera_transactions.csv` into the same downstream transaction shape the Koinly TH reader produces today, so the Bera on-chain extract can *replace* (not duplicate) the Koinly report for the BERA wallet.

---

## 0. Shared understanding of the two formats (established from real data)

### 0.1 BERA on-chain extract (`bera_transactions.csv`) - raw, granular
- 4 937 rows / **437 unique tx hashes** (≈ 11.3 legs per tx on average).
- One row **per token transfer leg** (native BERA `txlist` leg + every ERC-20 `tokentx` leg). Multi-leg swaps produce N rows sharing one `tx_hash`.
- Schema: `tx_hash, block_number, timestamp_utc, chain, from_address, to_address, asset, token_address, amount_raw, amount_decimals, direction, fee_asset, fee_amount_raw, wallet_label, wallet_address`.
- Amounts are **integer smallest-unit** (`amount_raw` + `amount_decimals`); exact, no float.
- **Gas fee is folded into the native leg** (`fee_asset`/`fee_amount_raw` populated on the BERA `txlist` row; zeroed on ERC-20 legs). There is no separate "fee row."
- `direction` ∈ {`in`, `out`, `unknown`} is computed relative to the tracked `wallet_address`.
- **No `Type`, no `Tag`, no currency conversion, no cost basis, no `Description`.** Pure on-chain movement.

### 0.2 Koinly TH CSV - collapsed, interpreted
- 10 396 rows across all wallets; **4 293 of the BERA-wallet rows are `crypto_deposit` + `Tag=Reward`** (BGT/iBGT/osBGT/POLLEN/etc. staking & validator rewards).
- One row already represents Koinly's *interpretation*: a swap is one `exchange` row (`Sent Amount/Currency` ↔ `Received Amount/Currency`); a reward is one `crypto_deposit`/`Reward` row; a gas burn Koinly considers material is one `crypto_withdrawal`/`Cost` row.
- `Type` ∈ {`buy, sell, exchange, transfer, crypto_deposit, crypto_withdrawal, fiat_deposit, fiat_withdrawal`}; `Tag` ∈ {`Reward, Cost, Cashback, Loan, Loan repayment, Loan fee, To pool, From pool, Liquidity in/out, Swap, Realized gain, Airdrop, Fee refund, Payment, Futures fee, Funding fee, Lending interest, <empty>`}.
- Carries EUR-denominated `Sent/Received Cost Basis`, `Gain (EUR)`, `Net Value (EUR)`, `Fee Value (EUR)` - none of which exist on-chain.

### 0.3 The overlap (424 of 437 BERA hashes appear in Koinly; 2 Koinly BERA hashes absent from BERA)

| Compression `Koinly rows / BERA legs` | # hashes | Meaning |
|---|---|---|
| 1.00 (equal) | 328 | 1:1 - simple reward or simple swap Koinly did not collapse. |
| 0.50 / 0.33 / 0.25 / 0.20 | ~90 | Koinly **collapsed** a multi-leg swap or a multi-token reward claim into fewer rows (nets dust/refunds, splits multi-input swaps into one `exchange` row per input asset). |
| > 1.0 | ~6 | Koinly **split** one BERA tx into more rows than BERA legs (e.g. the BM reward tx with 40 BERA legs → multiple `Reward` rows, one per distinct reward token). |

### 0.4 The 13 BERA-only hashes (absent from Koinly)
- 12 of 13 are **zero-value native outflows with only gas burned** (failed txs or pure contract calls with no value movement). Koinly silently drops these because there is no value transfer to model.
- 1 of 13 is an `in` leg (`WWW.BERA777.XYZ`, a scam/spam airdrop) - Koinly chose not to import it.

### 0.5 Gas-fee asymmetry (the big one)
- **384 of 424 shared BERA txs have a non-zero gas fee in BERA that Koinly does NOT surface** in the TH `Fee Amount` column. Koinly tracks value transfers in TH; gas lives elsewhere (Koinly's cost basis / `Cost` rows), not in the TH fee column.
- BERA carries gas precisely on the native leg.
- Only 34 shared txs have a fee Koinly *does* surface (the `exchange` rows where Koinly filled `Fee Amount`).

### 0.6 Address correlation is exact
- BERA `from_address` for reward legs and Koinly `TxSrc` for `Reward` rows match one-for-one (top senders `0xaaaaaa01…`, `0xbbbbbb02…`, `0xd2f19a79…` are identical on both sides). Address → semantic mapping is feasible.

### 0.7 What the pipeline consumes (canonical contract)
The downstream pipeline does **not** consume raw `TransactionHistoryRow` uniformly. It has specialized consumers that each re-read specific (Type, Tag) subsets:
- **Rewards / income** → from the **Income report**, not TH (`_parse_income_file`).
- **Capital gains** → from the **Capital Gains report**; TH only for loan-affected FIFO rebuild + token-origin.
- **Loan activity** → TH rows where `Tag='Loan'` / `'Loan repayment'` (`loan_activity.py`).
- **Fee/suspect events** → TH `crypto_withdrawal` rows whose TxHash co-occurs ≥ 2× (`fee_filter.py`).
- **Token origin / provenance** → all TH rows (`TokenOriginResolver`).
- **Derivatives filter** → TH rows.
- Grouping by `TxHash` is **correlation-based**, done in consumers, not in the reader. No row merges a trade with its fee.

---

## 1. Goal / scope - what does "standard format suitable to processing instead of Koinly report" mean?

**Q1.** Is the end goal to make the BERA extract the **sole** source for the BERA wallet (Koinly no longer needed for that wallet), or to produce a **parallel** normalized format that coexists with Koinly (e.g. for cross-validation only)?

- *Recommended:* Sole source for the BERA wallet, gated behind a flag, with the reader emitting the SAME `TransactionHistoryRow`/`Transaction` objects the existing consumers already take - so we change the source, not the consumers.
- *Risk if parallel:* we end up maintaining two reward/capital-gains pipelines and must reconcile divergent totals forever.

**Q2.** Scope of "BERA wallet" - is the BERA extract only ever going to cover the one `Ledger Berachain (BERA)` wallet, or must the reader be chain-generic from day one?

- *Clarified (2026-08-02):* "wallet" here meant **Transaction Source** (the row-collection format), not the on-chain address. Modeled as `(ProducerKind, producer_name)`: `ProducerKind` ∈ {`Aggregator`, `CEX`, `OnChainExplorer`}. **Koinly is an `Aggregator`** (it ingests from mixed CEX+on-chain sources and re-emits one normalized format) - *not* a CEX; a direct Kraken export is `CEX`; on-chain Etherscan parsing is `OnChainExplorer`, **per chain** (Berachain first). One processor per `(ProducerKind, producer_name)`. **DEX-API feeds are out of scope.** See `docs/maintenance/glossary.md` → *Transaction Source*, *Processor*.

**Q3.** Which Koinly *reports* must the BERA reader ultimately subsume? TH only, or also the **Income** and **Capital Gains** reports (which are the actual reward / CG sources, not TH)?

- *Recommended:* This plan produces a TH-equivalent only. Income and CG must stay Koinly-derived (or get their own separate replacement plans) because they require EUR cost basis and FIFO lots that on-chain data alone cannot reconstruct without an external price oracle.

---

## 2. The classification problem - how do we infer Koinly's `Type`/`Tag` from raw legs?

The BERA extract has no Type/Tag. Every consumer above keys on these. This is the central design question.

**Q4.** What is the source of truth for mapping a `(from_address, to_address, asset, leg-pattern)` tuple to a Koinly `Type`/`Tag`?

- *Option A - contract-address registry:* maintain a curated `bera_contracts.json` (or extend `chain_derivation.py`) mapping known reward distributors (`0xaaaaaa01…`, `0xbbbbbb02…`, `0xd2f19a79…` BGT distributor) → `Tag=Reward`; known DEX routers → `Type=exchange`; the wallet's own address pair → `Type=transfer; Tag=To pool/From pool`.
- *Option B - purely heuristic:* `direction=in` + single leg + from not self → `Reward`; multi-leg with both in and out → `exchange`; in-and-out to same contract → `transfer/To pool`.
- *Recommended:* **A as the primary signal, B as fallback.** Heuristic-only will misclassify reward-claim swaps (which have both an in and an out leg) and liquidity operations. The registry is small (the data shows ~15 distinct sender addresses cover 99 % of reward volume) and is the only way to reach Koinly-equivalent precision.

**Q5.** How do we classify the **multi-leg reward claim** (the BM example: 40 legs, 14 distinct reward tokens, one tx)? Koinly emits one `Reward` row per distinct reward token.

- *Recommended:* Group legs by `tx_hash`, then within a tx, group `in` legs by `asset` and sum; emit one `crypto_deposit/Reward` row per (tx_hash, asset) with summed amount. Carry the gas fee on whichever row maps to the native BERA leg (or distribute - see Q9).

**Q6.** How do we classify a **swap** (multi-leg, both in and out, not a reward claim)? Koinly nets dust/refund legs and emits one `exchange` row per (sent-asset, received-asset) pair.

- *Recommended:* For each tx, partition legs into "out assets" and "in assets." If exactly one out-asset and one in-asset → single `exchange`. If multiple out-assets mapping to one in-asset (LP deposit) → one `exchange` per out-asset (matches the `50WBTC-50WBERA` example). The native BERA `out` leg with `amount=0` is the gas carrier, not a swap leg - exclude it from the asset partition.

**Q7.** What do we do with **liquidity pool operations** (`To pool` / `From pool` / `Liquidity in/out`)? These are tax-relevant in PT (deposit = not a disposal; withdrawal = acquisition of LP tokens). The BERA data has many `KODI …`, `50WBERA-50…-WEIGHTED` LP tokens.

- *Recommended:* Treat any tx where the wallet receives an LP token (`KODI *`, `*WEIGHTED`, `Bault-*`) in exchange for ≥1 underlying tokens as `Type=exchange; Tag=Liquidity in` (or `To pool`). The reverse as `Liquidity out` / `From pool`. This requires the LP-token set as a registry constant - **flagging for user confirmation per the no-hardcoded-values rule.**

**Q8.** How do we handle the **zero-value gas-only txs** (12 of the 13 BERA-only hashes)? They are real on-chain events Koinly drops.

- *Recommended:* Emit them as `crypto_withdrawal; Tag=Cost` with the gas amount as `Sent Amount` in BERA (this is exactly what Koinly's `Cost` rows are - see §0.5: 384 shared txs carry a gas fee Koinly drops from TH). They must NOT be silently dropped; PT treats gas as a deductible cost.

---

## 3. The gas-fee representation problem - RESOLVED (2026-08-02)

The BERA extract is *richer* than Koinly: it carries gas precisely on the native leg for every tx (384/424 shared txs have gas Koinly drops). The resolution:

**Gas lives at the PARENT-TX level in the native model.** Rationale: there is exactly one gas fee per EVM transaction (gas is a property of the tx, not of any leg/Event). Attaching it to one Event is artificial; replicating it across Events double-counts. So the native `OnChainTransaction` carries `gas: {asset, amount_raw, decimals}` as a tx-level field; individual `Event`s do not carry gas.

```
OnChainTransaction (one per tx_hash)
  ├─ tx_hash, block_number, timestamp_utc, wallet
  ├─ gas: {asset: native_ticker, amount_raw, decimals}   ← ONE fee, lives here
  └─ events: [Event, ...]
        └─ Event {event_id, EventType, SubType, legs:[...]}
```

**The adapter owns the Koinly-compat projection.** Today's `TransactionHistoryRow` has a flat `Fee Amount`/`Fee Currency` column on every row (no parent-tx concept). When the adapter projects a parent-tx-level gas onto N rows, it applies the **carrier-row rule**: the projected row derived from the native leg carries `Fee Amount` (others get `Fee=0`); if the tx has no native leg (pure ERC-20 reward arrival via internal tx), the *first* projected row carries it. This rule is documented as a Koinly-compat accommodation, **not** a domain truth - so the existing fee-filter (which sums `Fee Amount`) and cost-basis code keep working without double-count and without consumer changes.

- *No dedicated GasBurn row* (per user: "without extracting fee into a separate transaction if we can help it").
- *Conversion:* `fee_amount_raw` (wei) → `Decimal` BERA at read time using `amount_decimals=18`; keep `amount_raw` available on the native structure for audit. Never let a `float` touch a fee value.

> Note: the earlier "gas on each Event" framing was rejected - it was ambiguous between replicate (double-counts) and own-by-one-Event (artificial ownership). Parent-tx-level is the honest model.

---

## 4. Cost basis / EUR valuation - the irreducible gap

**Q11.** The BERA extract has **no EUR prices**. Koinly's TH has `Sent/Received Cost Basis`, `Gain`, `Net Value`, `Fee Value` in EUR. Several consumers (`_parse_capital_gains_file`, the reward-income code that needs EUR market value) depend on these.

- *Question:* Do we (a) accept that the BERA-derived TH has empty cost-basis columns and let downstream code fall back to the historical-rates service (`ExchangeRateService` already exists), or (b) declare cost-basis out of scope and keep Koinly as the price source even when BERA is the movement source?

- *Recommended:* **(a)** - leave cost-basis columns empty in the BERA-derived row; route through the existing EUR-rate service. This keeps a single price oracle. But this means the BERA reader CANNOT fully replace the Koinly Capital Gains report - only the TH movement layer. Confirm this scoping with the user explicitly (it is the crux of "instead of Koinly report").

---

## 5. Grouping & correlation-key compatibility

**Q12.** The pipeline keys correlation on `TxHash` alone (`TxCorrelationKey`, Invariant 2/11). The BERA extract's `tx_hash` is the Etherscan hash = Koinly's `TxHash`. Good. But the `TxCorrelationKeyResolver` selects sending vs receiving side. For a BERA-derived row, what populates `tx_src`/`tx_dest`?

- *Recommended:* `tx_src = from_address`, `tx_dest = to_address` of the *representative* leg (the native leg if present, else the first in-leg). These are checksummed EVM addresses and match Koinly's `TxSrc`/`TxDest` exactly (verified in §0.6).

**Q13.** `row_index` is the anti-collision mechanism when `tx_hash` is None. BERA rows always have a `tx_hash`. Do we still assign a synthetic `row_index`?

- *Recommended:* Yes, assign sequential `row_index` in emit order; cheap insurance and matches the `TransactionHistoryRow` contract.

---

## 6. Data-completeness reconciliation (what to surface to the user)

**Q14.** The 2 Koinly BERA-wallet hashes absent from the BERA extract, and the 1 spam airdrop BERA has that Koinly lacks - how do we report these reconciliation gaps?

- *Recommended:* Emit a reconciliation report (count + sample hashes) to the user-facing Excel "Assumptions & Methodology" sheet at WARNING level (data-loss condition, per the warning taxonomy). Never silently diverge from the Koinly baseline during the transition period.

**Q15.** During the transition (both Koinly and BERA exist), do we run both and diff, or switch outright?

- *Recommended:* Add a `--on-chain-source` flag (or `BERA_AS_TH_SOURCE=1` env) that selects the BERA-derived TH for the BERA wallet while other wallets keep Koinly. Run a one-time reconciliation diff in `docs/tmp/` (this analysis is the start of it) and pin a characterization test on the known divergence set before flipping the default.

---

## 7. Where the new code lives (module layout)

**Q16.** Module placement. Options:

- (a) `src/tax_reporting/infrastructure/bera_th_reader.py` - mirrors `koinly_parser.py`, produces `TransactionHistoryRow`.
- (b) Extend `on_chain_fetcher.py` to also emit a normalized TH alongside the raw CSV.
- (c) A new `application/on_chain_th_builder.py` that reads the raw CSV and classifies.

- *Recommended:* **(a) + (c):** a thin `bera_th_reader.py` (parses CSV → `OnChainTxRow`) plus `on_chain_th_builder.py` (classifies `OnChainTxRow` → `TransactionHistoryRow`). Keeps parsing and classification separately testable (per the extracted-helpers-need-direct-unit-tests rule). The fetcher (`on_chain_fetcher.py`) stays a pure collector.

### 7.1 Contract registry format - RESOLVED (2026-08-02)

- **Location:** `resources/source/<year>/<chain>_contracts.json` (e.g. `resources/source/2025/berachain_contracts.json`), alongside `chains.json`. User-owned; mirrors the existing `chains.json` convention; keeps magic values out of code.
- **Carries:** classification hints (`address` → `EventType`/`SubType` suggestion: reward-distributor, DEX-router, LP-pool) **plus an OPTIONAL `operator_country`** field per contract, defaulting to chain-level when absent.
- **Country research finding (cited):** per-distributor operator country is **mostly undiscoverable**. Validator/node-operator rebate routers carry no on-chain country metadata; the `berachain/metadata` validator registry schema has no country/legal-entity field. The ONE exception is the protocol's own BGT **Distributor** contract `0xd2f19a79b026fb636a7c300bf5947df113940761` - it is a Berachain protocol contract (listed in official deployed-contracts docs), so its payer is the **Bera Chain Foundation, Cayman Islands** (source: Bitstamp BERA MiCA whitepaper). The two large rebate routers (`0xaaaaaa01…`, `0xbbbbbb02…`) cannot be attributed to any jurisdiction → chain-level fallback.
- **Seed entry:** `{address: 0xd2f19a79…, kind: reward-distributor, operator_country: "KY"}`.
- **Future:** users may manually add `operator_country` to a contract when they independently identify the operator (e.g. a known staking-as-a-service firm). This is best-effort; never automatable for validators.
- **Schema distinction:** protocol emissions (Distributor → Foundation) vs validator/node-operator rebates (operator → own domicile) is a real economic distinction that the optional country field captures.

---

## 8. Open questions for the user (the irreducible decisions)

These are the questions I will ask, in order, once you confirm the analysis above is correct:

1. **Q1 + Q3 + Q11 (scope):** Is the BERA reader meant to *replace* the Koinly TH for the BERA wallet only, while Income/CG reports stay Koinly-sourced (because they need EUR cost basis the chain cannot provide)? Yes/no.
2. **Q4 (classification authority):** Are you willing to maintain a small `bera_contracts.json` reward-distributor + DEX-router registry as the primary Type/Tag signal, with heuristics as fallback?
3. **Q7 (LP tokens):** Confirm the LP-token symbol set (`KODI *`, `*WEIGHTED`, `Bault-*`, and any others) that should map to `Liquidity in/out` - this is a hardcoded set needing your sign-off.
4. **Q8 (gas-only txs):** Confirm zero-value gas-only txs should be emitted as `Cost` rows (PT-deductible) rather than dropped, diverging from Koinly.
5. **Q9 (gas placement):** Confirm option (b) - gas on the native-leg-derived row, attached to the first row when no native leg - and that we accept the `fee_filter.py` ≥2× guard may need re-tuning.
6. **Q15 (transition):** Do you want a side-by-side reconciliation flag during transition, or a hard switch?

---

## 9. Proposal - the remaining mechanical decisions (awaiting confirmation)

Derived from the BERA data shapes + the resolved architectural decisions (1–10). Each item is proposal-confirm, not open-ended.

### 9.1 Native `EventType` enum (data-grounded)

The 437 BERA tx hashes fall into these leg-pattern shapes (counted from real data):

| Shape | # txs | Description |
|---|---|---|
| BIDIRECTIONAL | 233 | both in and out legs (swaps, LP ops, reward-claim-then-swap) |
| GAS_ONLY | 139 | only out leg is native BERA `amount=0` (pure gas burn) |
| PURE_OUTFLOW | 48 | only outflow; non-zero (transfer / cost / withdrawal) |
| PURE_INFLOW | 17 | only inflow (canonical reward arrival) |

Proposed `EventType` enum (7 values, covering every observed shape + obvious future cases). Orthogonality rule: EventType encodes the economic *shape* only; instrument/treatment detail that could vary independently lives in SubType:

| EventType | Maps to Koinly | Fires when |
|---|---|---|
| `Swap` | `exchange` | BIDIRECTIONAL, 1-in-asset ↔ 1-out-asset (43 txs), or multi-in not receiving LP |
| `LiquidityDeposit` | `transfer` / `Liquidity in` (or `To pool`) | BIDIRECTIONAL receiving an LP token (35 txs) |
| `LiquidityWithdraw` | `transfer` / `Liquidity out` (or `From pool`) | BIDIRECTIONAL spending an LP token for underlying |
| `Reward` | `crypto_deposit` / `Reward` | PURE_INFLOW from a registered distributor (17 txs + the in-legs of multi-token claims) |
| `Transfer` | `transfer` / `<empty>` | PURE_OUTFLOW/INFLOW to/from a known self-wallet or bridge (internal movement; bridging is `SubType=bridge`, not a separate EventType, because PT treats it as a non-taxable transfer) |
| `GasBurn` | `crypto_withdrawal` / `Cost` | GAS_ONLY (139 txs) - *but* no dedicated Event: the gas is the parent-tx fee; for GAS_ONLY txs the tx emits one GasBurn Event so it isn't lost (this is the documented exception to "no separate fee row") |
| `Unknown` | `crypto_deposit`/`crypto_withdrawal` / `<empty>` + review flag | classification didn't fire (e.g. spam airdrop from unrecognized sender, multi-leg not matching any pattern) |

`BridgeOut`/`BridgeIn` were **removed** as distinct EventTypes - PT treats bridging as a non-taxable transfer, so it's `EventType=Transfer, SubType=bridge`.

**SubType (orthogonal to EventType, decision-driving only):** carries ONLY discriminators that (a) drive a downstream routing/tax/review decision AND (b) are NOT already encoded by EventType. Venue/chain/protocol provenance is excluded - recoverable from the contract address + the autodiscovery registry, and nothing downstream branches on it. Resulting set:

| SubType | Why decision-driving |
|---|---|
| `staking` | reward tax classification (CRG-001/002 taxable-now vs deferred-by-law) branches on staking vs airdrop vs fiat-denominated |
| `airdrop` | same classification; also drives the unpriced-deferred-reward review flag |
| `validator_rebate` | protocol-emission (Distributor→Cayman) vs operator-rebate country split (decision #8) |
| `spam` | drives the review flag for unrecognized airdrops |
| `cost_gas` | distinguishes gas-burn Cost treatment (PT deductible) from other withdrawals |
| `internal_transfer` | own-wallet movement, non-taxable; fee-filter and review logic both branch on it |
| `bridge` | cross-border movement; review-flag-relevant even though PT treatment = transfer |

SubType is OPTIONAL (an Event may have SubType=None when no discriminator applies). The processor picks the value; the adapter ignores SubType for Koinly Type/Tag mapping (Koinly has no equivalent).

**Confirm:** the 7 EventTypes + the SubType vocabulary. Note `GasBurn` is the one exception to "no separate fee row" - it only fires for the 139 GAS_ONLY txs that have no other Event, so the gas isn't silently lost.

### 9.2 LP-token recognition - RESOLVED (2026-08-02): autodiscovery, address-keyed

**Rejected:** symbol/name regex (`^(KODI |Bault-KODI )|WEIGHTED$`). Research confirmed it is unreliable by construction: V2 pairs all return symbol `UNI-V2` (generic across every pair), Islands/Baults use bytes32-packed symbols, and staking receipts (`iBERA`, `stBGT`, …) share naming conventions without being LP claims. Grouping distinct tokens by a regex on their symbol conflates unrelated instruments (per user: "if they named differently they are most probably unrelated").

**Adopted: address-keyed autodiscovery, three-layer stack:**

1. **Primary - subgraph snapshot allowlist.** A trusted registry file (committed like `chains.json`, refreshed periodically) built from the Kodiak subgraph, indexed by `token_address`. Sources:
    - V2 pairs: subgraph entity `Pair.id` (the LP ERC-20 address), with `token0`/`token1` for provenance.
    - Kodiak Islands (ERC-4626 auto-compounder over V3 positions): subgraph entity `KodiakVault.outputToken.id`.
    - Bault vaults (Kodiak's own auto-compounder wrapping an Island): `stakingToken` field from `https://backend.kodiak.finance/baults`.
    - Endpoint: `https://api.subgraph.ormilabs.com/api/public/d7eed6cc-ad4a-4862-8017-89893c4095d3/subgraphs/kodiak-v3/latest/gn`.
    - Lookup O(1) by `token_address`; 100% name-independent; covers every Kodiak LP product.

2. **Fallback - on-chain bytecode/implementation-address fingerprint** (for tokens not yet in the snapshot, e.g. brand-new pools):
    - V2 pairs: runtime bytecode keccak `0x4a2740657d3226d1efd99f96d24823ddae76337f38d17236ed104d1b390a8a66` (byte-identical UniswapV2Pair).
    - Islands/Baults: EIP-1167 minimal proxies; read `implementation()` and compare to documented impl addresses (`KodiakIsland` `0xCFe9Ee61c271fBA4D190498b5A71B8CB365a3590`; Bault impl via `BaultFactory` `0xffCAED1971C28cCcEaff111f4eD2235532537b8F`).
    - Cost: one `eth_getCode` + one `implementation()` call per unknown token. New RPC call path during parsing (the existing `etherscan_client.py` is the model; a thin `rpc_client.py` for `eth_getCode` is added).

3. **Provenance only - mint-on-deposit tx pattern** (the existing `token_origin.py` mechanism): once a token IS classified as LP (by #1 or #2), the tx pattern recovers which underlyings were spent to mint it. **Never used as the classifier** - it cannot distinguish LP claims from staking receipts (both mint-on-deposit).

**Research corrections absorbed:**
- "Bault" is Kodiak's own product (BaultFactory), not a third-party wrapper. `Bault-KODI *` tokens are nested Kodiak LPs.
- `50WBERA-50HONEY-WEIGHTED` is NOT a Balancer pool - Kodiak's subgraph has no WeightedPool/Vault type. It's an indexer naming artifact. No Balancer interface to design around.
- V3 pools are not holdable ERC-20s (LP is an NFT via `NonfungiblePositionManager`); only V2 pairs and Islands/Baults are detectable receipt tokens. V3 LP activity is out of scope for this tax model until NFT-position modeling is added.

**Trusted addresses to seed** (verified, cited from Kodiak docs + on-chain probes): V2 factory `0x5e705e184d233ff2a7cb1553793464a9d0c3028f`; V3 factory `0xD84CBf0B02636E7f53dB9E5e45A616E05d710990`; KodiakIsland impl `0xCFe9Ee61c271fBA4D190498b5A71B8CB365a3590`; KodiakIslandFactory `0x5261c5A5f08818c08Ed0Eb036d9575bA1E02c1d6`; BaultFactory `0xffCAED1971C28cCcEaff111f4eD2235532537b8F`.

### 9.3 Cost-basis / EUR valuation - RESOLVED (2026-08-02): deferred to taxable-event time

The on-chain-native model carries **no EUR prices**. Rationale (per user): prices are not needed for the parsing/tagging layer; they are only needed later, when a transaction becomes **final/taxable** (a disposal or a reward-realization event). At parse time the model records *what moved*; valuation is resolved downstream when the existing pipeline determines tax treatment.

- The adapter projects empty cost-basis columns onto `TransactionHistoryRow`; downstream code that needs EUR (capital gains, reward market value) resolves via the existing `ExchangeRateService` at taxable-event time. Single price oracle; no valuation logic in the parser.
- **Scope consequence:** the on-chain pipeline replaces Koinly's *movement layer* (TH). A future on-chain-derived price source is **not precluded** - it can be wired later as a separate concern feeding the same downstream rate-resolution path. But it is explicitly out of scope for this plan. CG/Income reports stay Koinly-sourced until/unless a separate price-oracle plan lands.

### 9.4 Transition mechanics (Q15)

**Proposed:** flag-gated, per-wallet. A new config field `ON_CHAIN_TH_WALLETS` (list of wallet labels) in `config.ini` `[TAX JURISDICTION]` selects which wallets use the on-chain-derived TH; unlisted wallets keep the Koinly TH. Default empty = today's behavior (all Koinly). When the BERA wallet is listed, the on-chain pipeline runs and its output replaces the Koinly TH rows for that wallet *only*.

Reconciliation: a one-time diff lives in `docs/tmp/` (this analysis is the seed). A characterization test pins the known divergence set (12 BERA-only gas txs, 1 spam airdrop, 2 Koinly-only hashes) before the flag is ever set. The diff re-runs as a verification script each time the user flips a new wallet on.

**Confirm:** `ON_CHAIN_TH_WALLETS` config field over a CLI flag or env var (config-field survives across runs, is versionable, and is the existing pattern for per-wallet decisions).

### 9.5 Module layout - REVISED (2026-08-02)

**Current collector modules (EXISTING, no rename):**
- `application/on_chain_fetcher.py` - orchestrator; writes `bera_transactions.csv`. Pure collector.
- `infrastructure/on_chain/etherscan_client.py` - Etherscan V2 HTTP client.
- `infrastructure/on_chain/bera_decoder.py` - decodes raw Etherscan rows → `OnChainTxRow` (the per-chain decode step).

**Proposed NEW modules (the parser/tagger/adapter):**

```
src/tax_reporting/
  domain/
    on_chain_transaction.py     # NEW: OnChainTransaction, Event, Leg, Gas dataclasses + EventType/SubType enums
  infrastructure/
    on_chain/
      on_chain_csv_reader.py    # NEW: parses bera_transactions.csv -> list[OnChainTxRow] (thin, no classification; generic across chains)
      berachain_processor.py    # NEW: the BERA processor - OnChainTxRow + berachain_contracts.json + LP-autodiscovery -> list[OnChainTransaction] (classification + tagging)
      rpc_client.py             # NEW: thin eth_getCode/implementation() client for the LP bytecode fallback (mirrors etherscan_client.py)
  application/
    on_chain_th_adapter.py      # NEW: list[OnChainTransaction] -> list[TransactionHistoryRow] (Koinly-compat projection: carrier-row gas rule, Event->Type/Tag mapping)
    on_chain_config.py          # EXISTING: extend to load <chain>_contracts.json + the LP-token snapshot alongside chains.json
    on_chain_fetcher.py         # EXISTING: untouched (pure collector)
```

**Naming rationale (answers user's question "How do we call the current module that collects data from berachain? Is it bera_th_reader.py?"):**
- The current collector is `on_chain_fetcher.py` + `bera_decoder.py`. There is **no `bera_th_reader.py`** - that was my earlier proposed name and it collides confusingly with `bera_decoder.py`. Dropped.
- New modules use **role names, not chain-prefixed names** where the role is generic: `on_chain_csv_reader.py` (parses the CSV format shared by all chains), `on_chain_th_adapter.py` (Koinly-compat projection, chain-agnostic).
- The **chain-specific** module is named for the chain, not the file role: `berachain_processor.py` (the BERA processor = classification + tagging + LP-autodiscovery for Berachain). Adding Ethereum later = `ethereum_processor.py` reusing the same reader + adapter.
- `rpc_client.py` is new infrastructure for the LP bytecode fingerprint fallback (§9.2 layer 2).

**Why split parsing, classification, projection into three:** each independently testable per the extracted-helpers-need-direct-unit-tests rule; the fetcher stays a pure collector (no change to working code); the chain-specific code is isolated to one processor module.

**Confirm:** the role-based naming + three-module split (csv_reader / berachain_processor / th_adapter) over a single fat `bera_th_reader.py`.

---

## 10. Resolved decisions (running tally)

1. **Goal** - parallel native pipeline; per-wallet Koinly replacement once validated.
2. **Output shape** - on-chain-native model + adapter to `TransactionHistoryRow`.
3. **Tag vocabulary** - native `EventType`+`SubType` (orthogonal), mapped to Koinly at the adapter.
4. **Cardinality** - split: one tx_hash → N Events linked by `parent_event_id`.
5. **Invariant 2** - amend `TxCorrelationKey` to `(tx_hash, event_id)`; re-scope fee-filter ≥2 guard; characterization test first.
6. **Parse everything** - gas-only + spam airdrop tagged, not dropped; sorting is downstream.
7. **Transaction Source** - `(ProducerKind, producer_name)`; Koinly=Aggregator, on-chain=OnChainExplorer per chain; DEX-API out of scope.
8. **Contract registry** - `resources/source/<year>/<chain>_contracts.json`; classification hints + optional `operator_country`. **Amended (B3):** ships EMPTY `operator_country` for Berachain - all Berachain rewards resolve via the existing chain-level VG (BVI, Berachain ToS, primary). A contract-level country override requires a primary source stronger than the chain-level mapping; the KY/Cayman seed (Bitstamp MiCA whitepaper, secondary) was dropped.
9. **Gas model** - gas at parent-tx level in native model; adapter applies carrier-row rule (native-leg-first, else first row) for the flat `Fee Amount` column. No dedicated GasBurn row (except GAS_ONLY txs).
10. **Fee conversion** - wei → `Decimal` at read time; raw kept for audit; never float.
11. **LP-token detection** - address-keyed autodiscovery: subgraph snapshot (primary) + on-chain bytecode/implementation-address fingerprint (fallback) + tx-pattern (provenance only). Symbol regex rejected. Bault=Kodiak's own; WEIGHTED is an indexer artifact not Balancer.
12. **Cost basis** - deferred to taxable-event time; parser carries no EUR; existing `ExchangeRateService` resolves later. TH-layer replacement only.
13. **Module layout** - role names for generic modules (`on_chain_csv_reader.py`, `on_chain_th_adapter.py`, `rpc_client.py`); chain-specific `berachain_processor.py`. No `bera_th_reader.py` (collides with existing `bera_decoder.py`). Fetcher untouched.
14. **Transition** - `ON_CHAIN_TH_WALLETS` config field in `[TAX JURISDICTION]`; per-wallet opt-in; default empty = today's behavior; one-time diff + characterization test before flipping.
15. **Tag vocabulary** - EventType (7: Swap/LiquidityDeposit/LiquidityWithdraw/Reward/Transfer/GasBurn/Unknown) + SubType (7, optional: staking/airdrop/validator_rebate/spam/cost_gas/internal_transfer/bridge). Orthogonal; decision-driving only; no venue/chain provenance (recoverable from registry). `BridgeOut/In` folded into Transfer+SubType=bridge; LP-ness lives in EventType, not duplicated in SubType.

## 11. Pending confirmation (section 9)

**None.** All 15 design decisions resolved (9.1–9.5 + decisions 1–10). The vocabulary is internally consistent and minimal:

- **EventType (7):** `Swap` · `LiquidityDeposit` · `LiquidityWithdraw` · `Reward` · `Transfer` · `GasBurn` · `Unknown`
- **SubType (7, optional):** `staking` · `airdrop` · `validator_rebate` · `spam` · `cost_gas` · `internal_transfer` · `bridge`
- Both follow the orthogonality + decision-driving-only principles (no redundant provenance).

**Next step:** write the implementation plan under `docs/history/plans/`.

---

## 12. Premortem findings (2026-08-02) - four personas

Each finding verified against actual source (line numbers cited). Findings already mitigated by the design are skipped.

### Blockers (must resolve in design before plan)

**B1. The adapter's column projection is NOT mechanical - three consumers read contradictory keys.** *Personas: Pessimist (root cause), Future Maintainer.* Verified:
- `token_origin.py:171,278` reads `tx_hash = row.get("TxSrc","")` with comment "Real Koinly exports store the transaction hash in TxSrc" - so it treats `TxSrc` AS the hash.
- `tx_correlation_key_resolver.py:93` reads `tx_id = row.tx_hash` (the real hash).
- `fee_filter.py:222` counts the `TxHash` column; `:241-245` reads `Fee Amount`/`Fee Currency`/`Sent Amount`/`Net Value (EUR)`.

**RESOLVED (2026-08-02):** Migrate the three consumers to key on `(tx_hash, event_id)`, gated by characterization tests on real Koinly data asserting byte-identical output for non-opted-in wallets. Koinly rows set `event_id=None` and behave identically to today; on-chain split rows carry distinct `event_id`. The adapter emits one row per Event (preserving granularity). Specifically:
- `crypto_fifo/parsing.py:228`: `tx_key` becomes `(tx_hash, event_id)` (event_id None for Koinly).
- `token_origin.py:171,278`: read `TxHash` not `TxSrc` (token_origin's TxSrc-as-hash was a Koinly quirk; the on-chain adapter populates TxHash correctly, and migrating token_origin is in-scope as part of the amendment).
- `fee_filter.py`: addressed under B4.
- The Koinly path is untouched (event_id=None preserves today's dedup semantics for Koinly rows). Characterization tests (decision #14) on the real `resources/source/2025/koinly/` data assert byte-identical FIFO/cost-basis output before and after the amendment - this is the regression catch.

**B2. The Invariant 2 amendment misses an entire second correlation-key system in `crypto_fifo/`.** *Persona: Future Maintainer (Finding 1, blocker).* Verified: `crypto_fifo/parsing.py:228,316,336` builds `tx_key` independently and dedups. **RESOLVED as part of B1** - `tx_key` becomes `(tx_hash, event_id)`, so the FIFO dedup no longer collides on split rows. The two parallel correlation systems (`TxCorrelationKey` and `tx_key`) are both amended in the same plan, with a cross-reference comment added at each site noting the other exists.

**B3. `operator_country` collision: KY (Cayman, decision #8) vs VG (BVI, existing `operator_origin.py:305`).** *Persona: Pessimist (Finding 3).* Verified facts:
- `operator_origin.py:302-305` maps `"Berachain"` → `operator_country="VG"`, citing `berachain.com/terms-of-service` (official primary source, authority=`official`).
- `docs/maintenance/tax/crypto-origin/operator_chain_origin_registry.md:21-24` confirms chain-level Berachain = **British Virgin Islands**, basis: "Berachain terms identify `BERA Chain Foundation` and British Virgin Islands governing law."
- Decision #8 seeded the Distributor contract `0xd2f19a79` → `KY` (Cayman) citing the **Bitstamp MiCA whitepaper**, which the research itself flagged as hedged ("the legal issuer of BERA has not been expressly identified in official public sources") - a *secondary* source.

**Assessment:** This is not "two equal sources disagree." The chain-level mapping is BVI per Berachain's own ToS (primary, official). The Cayman claim is secondary (Bitstamp's assessment). The Distributor contract is a protocol contract whose payer is the Foundation itself; no evidence distinguishes its payer from the chain-level entity. So the contract-level KY entry in decision #8 was likely a source-priority error - Cayman came from a weaker source.

**PENDING user decision:** confirm that the chain-level BVI (primary, Berachain ToS) is authoritative for the Distributor contract too, so decision #8's KY seed entry is **dropped** (the contract registry carries NO `operator_country` for the Distributor - it falls through to the existing VG chain-level mapping). This removes the collision entirely. The alternative (KY overrides VG at the contract level) requires justifying why a secondary source overrides a primary one.

**RESOLVED (2026-08-02):** BVI wins - drop KY seed. The Distributor contract `0xd2f19a79` carries NO `operator_country` in `berachain_contracts.json`; all Berachain rewards (Distributor + rebate routers) resolve via the existing chain-level `operator_origin.py:305` → VG (British Virgin Islands, primary source: Berachain ToS). **Decision #8 is amended:** the contract registry still supports an OPTIONAL `operator_country` field (for future chains where a per-contract override is justified by a *primary* source), but it ships EMPTY for Berachain. Source-priority rule recorded: a contract-level country override requires a primary source stronger than the chain-level mapping; secondary sources (exchange whitepapers) do not qualify.

**B4. `fee_filter.py` ≥2 co-occurrence guard becomes a tautology under the split model, and the "re-scope" is unspecified.** *Persona: Pessimist (Finding 2).* Verified: `fee_filter.py:222-226` counts bare `TxHash` across all TH rows; `:254` `occurs_at_least_twice = bool(tx_hash) and tx_hash_counts[tx_hash] >= 2`. Under the split model, a 40-leg reward claim emits 14 rows sharing one hash → `tx_hash_counts[h] >= 2` for every withdrawal including genuine disposals. **RESOLVED (2026-08-02):** The guard's *intent* is "this tx also had a non-fee event" (the withdrawal is correlated with real activity). Under the `(tx_hash, event_id)` key (B1 resolution), the shipped predicate is: **for on-chain rows (event_id present) the tx has ≥1 co-occurring NON-FEE event** (a row whose `Type != crypto_withdrawal`); for Koinly rows (no event_id) it reduces to today's `count >= 2`. A fee/withdrawal event co-occurring with a non-fee event in the same tx passes; a standalone withdrawal does not. This corrects the initial "≥2 distinct Events" wording (review F5), which would wrongly admit two fee/withdrawal-Cost events with no non-fee event. Characterization test (decision #14) pins the current Koinly-data behavior (where every Koinly row has `event_id=None` → count = 1 → guard behaves exactly as today for Koinly rows).

**B5. Carrier-row gas rule double-counts via `fee_filter.py`'s two independent fee-detection paths (GAS_ONLY txs only).** *Persona: Pessimist (Finding 5).* Verified: `fee_filter.py:241-245` has two paths - `is_withdrawal` (`row_type == "crypto_withdrawal"`) and `has_embedded_fee` (any row with `Fee Amount`/`Fee Currency`). Scope clarification: for normal BIDIRECTIONAL txs (233 txs), the adapter puts `Fee Amount` on the carrier row (an `exchange`/`transfer` row, not a `crypto_withdrawal`), so only `has_embedded_fee` fires once - **no double-count.** The double-count fires **only for the 139 GAS_ONLY txs**: the GasBurn Event emits a `crypto_withdrawal/Cost` row, AND if the carrier-row rule puts `Fee Amount` on that same row (because it's "the first row"), BOTH `is_withdrawal` and `has_embedded_fee` fire on the same row → the gas is counted twice. **RESOLVED (2026-08-02):** The carrier-row rule has an explicit exception: **a GasBurn/Cost row carries the gas as `Sent Amount` (the disposal) and leaves `Fee Amount` EMPTY.** The gas isn't a fee-on-top-of-itself. Concretely: the adapter's carrier-row selection skips rows whose `EventType=GasBurn` - gas-on-carrier-row only applies when the carrier row is a non-GasBurn Event (Swap/Transfer/etc.). For GAS_ONLY txs, the single GasBurn row IS the gas record; nothing else carries `Fee Amount`. This makes `has_embedded_fee` false for GasBurn rows, so only `is_withdrawal` fires (once). The §9.1 EventType-table wording "no dedicated Event... except GAS_ONLY txs" is amended to: GAS_ONLY txs emit exactly one GasBurn Event (as `crypto_withdrawal/Cost`, `Sent Amount` = gas, `Fee Amount` empty); no separate fee row.

### Mitigations needed (add safeguards before/during implementation)

**M1. The new parser inherits the broad `except Exception` in `_run_optional_on_chain_fetch` (`application/run_report.py`) → silent skip = wrong totals.** *Persona: Operator (Finding O-2, catastrophic).* Today the broad catch is correct because on-chain is a non-blocking side-collector nothing reads. Once `ON_CHAIN_TH_WALLETS` is set, a parse/tag exception in the opted-in wallet is caught and the run continues with missing/wrong rows - **a tax pipeline that silently skips data is strictly worse than one that crashes.** Fix: for opted-in wallets, parse/tag/adapter exceptions propagate as `ReportGenerationError`; the soft catch applies ONLY to the collection-only path. (This aligns with the codebase's own Family G data-loss-observability pattern.)

**M2. Subgraph snapshot staleness has no freshness signal; new pools silently mis-tagged as Swap.** *Personas: Operator (O-1, O-4, O-7), Pessimist (F4).* The snapshot is "refreshed periodically" with no `snapshot_as_of_block`/`snapshot_as_of_date` field, no drift check, and the endpoint is pinned to `/latest/gn` (schema can drift mid-flight). A Kodiak pool created after the snapshot cut → LP deposit falls through to `Swap` (taxable disposal) instead of `LiquidityDeposit` (non-disposal) → **phantom capital gain.** Layer 2 (bytecode fallback) was designed but not yet built, so layer 1 was the only classifier at launch (design-time caveat - since RESOLVED: layer 2 has shipped behind `ON_CHAIN_RPC_URL`, see the note below). Fix: require freshness metadata in the snapshot; pin a subgraph version (not `latest`); schema-validate on load; WARN/fail when tx dates postdate the snapshot; build layer 2 before launch OR explicitly mark LP-classification as best-effort with a review flag.

**RESOLVED (2026-08-04):** Layer 2 (bytecode fallback) shipped behind the `ON_CHAIN_RPC_URL` config key (Task 7 of the follow-ups plan `2026-08-05-on-chain-tx-tagger-review-leftovers`): when set, non-snapshot LP tokens are classified via runtime-bytecode fingerprinting (V2-pair keccak match; EIP-1167 minimal-proxy `implementation()` resolution); when unset, non-snapshot tokens fall to `Unknown` + review (snapshot-only, Koinly-byte-identical). Separately, `check_freshness` is now wired (Task 2 of this plan) so a stale snapshot - a tx whose block postdates `snapshot_as_of_block` - emits a WARN from `LpAutodiscovery.check_freshness`, invoked from `OnChainThSubstituter.maybe_substitute`.

**M3. The on-chain path is NOT wired into the Excel reconciliation surface.** *Persona: Operator (O-6, O-8).* The `Crypto Reconciliation` sheet is fed exclusively by `CryptoTaxReport` (Koinly-derived). The adapter produces `TransactionHistoryRow` - a different object that never reaches the reconciliation sheet. So "surface divergence to the Assumptions sheet" (§6/Q14) is an unimplemented aspiration. When the flag is on, the user has no Excel-visible record of the Koinly→on-chain delta, and a silent wallet-scoped failure (M1) is invisible in aggregate. Fix: wire per-wallet source provenance (Koinly/on-chain) + per-wallet row counts + a delta block into the reconciliation sheet.

**M4. Rollback is not clean: flipping the flag off does not restore Koinly-derived numbers.** *Persona: Operator (O-5).* The FIFO leftover rollover (`shares-leftover.csv`) and cost-basis state are written by the on-chain run; flipping the flag off doesn't un-corrupt them. Fix: stamp every `extract.xlsx` with per-wallet source provenance; document the rollback procedure (delete leftover + re-run from Koinly); consider keeping Koinly-derived numbers computable in parallel during transition.

### Monitor (observability; accept residual risk)

**MO1. Bytecode-fallback RPC path: 1 `eth_getCode` + 1 `implementation()` per unknown token.** *Persona: Operator (O-3).* A 100-token first load = 100-200 RPC calls; rate limits, timeouts, partial failure (some tokens classified, others not → inconsistent treatment within one tx). Add per-call timeout, max-retries, hard cap on fallback calls per run, and a summary line in Excel showing fallback/unknown counts.

**MO2. Post-cutover, there is no Koinly to diff against - the integrity story has a half-life of one tax year.** *Persona: Attacker (Finding 8).* The transition diff is one-time. After cutover, novel abuse (spam, scam LP, decimal abuse) has no detection surface. Add a Koinly-independent invariant suite: "no single registry entry accounts for >30% of tags," "zero legs with decimals outside [0,36]," "no `unknown`-direction rate >1%," "sum of Reward income per asset within 2× of prior year."

### Accepted risks (documented; no action)

**A1. Registry/snapshot integrity against a determined attacker.** *Persona: Attacker (Findings 1, 2, 3, 7).* The contract registry is user-editable; the subgraph snapshot is fetched unsigned; the bytecode hash is reproducible (a backdoored contract with V2 runtime bytecode). Fully mitigating these requires signed snapshots, factory-provenance cross-checks, and registry SHA-pinning. **Accepted** because: the threat model is a single-user personal tax tool, not a multi-tenant service; the user IS the editor; and a determined attacker with write access to the user's own config has easier attack vectors. Document the residual risk; add the closed-enum + citation validation (cheap) but skip the cryptographic signing (expensive, low marginal value here).

### Anti-patterns caught

The premortem also caught two process anti-patterns worth noting:
- **The design's "consumer list" for the Invariant 2 amendment was incomplete** - it listed fee_filter, token_origin, th_lot_matcher, wallet_kind, derivatives_filter but missed `crypto_fifo/` entirely (B2). Lesson: grep for the value, don't enumerate from memory.
- **"The adapter is a mechanical projection" was an unverified claim** (B1). Three consumers read incompatible column subsets; the projection has real reconciliation work. Lesson: a layer labeled "compat" still needs its downstream contracts audited.

### Highest-leverage design changes - all RESOLVED (2026-08-02)

1. **B1 + B2 - RESOLVED:** Migrate the three consumers (`crypto_fifo/parsing.py`, `token_origin.py`, `fee_filter.py`) to key on `(tx_hash, event_id)`, gated by characterization tests on real Koinly data. Koinly rows (`event_id=None`) behave identically to today; on-chain split rows carry distinct `event_id`. The adapter emits one row per Event (granularity preserved). The two parallel correlation systems (`TxCorrelationKey` + `tx_key`) are both amended with cross-reference comments.
2. **B3 - RESOLVED:** BVI (British Virgin Islands, Berachain ToS, primary) wins; decision #8's KY/Cayman seed (Bitstamp MiCA whitepaper, secondary) is dropped. Contract registry ships EMPTY `operator_country` for Berachain; all rewards resolve chain-level VG. Source-priority rule: a contract-level override requires a primary source stronger than the chain-level mapping.
3. **B4 + B5 - RESOLVED:** Co-occurrence guard re-scoped to count distinct `(tx_hash, event_id)` pairs (≥2 distinct Events, not ≥2 rows). GasBurn row exception: a GasBurn/Cost row carries gas as `Sent Amount` with `Fee Amount` empty (gas isn't a fee-on-top-of-itself); the carrier-row rule skips GasBurn rows. Koinly rows unaffected (event_id=None → guard behaves as today).

### Mitigations dispositioned

- **M1 (fail-loud for opted-in wallets):** adopted - parse/tag/adapter exceptions propagate as `ReportGenerationError`; the broad `except Exception` in `_run_optional_on_chain_fetch` (`application/run_report.py`) applies ONLY to the collection-only path.
- **M2 (subgraph snapshot freshness):** adopted - require `snapshot_as_of_block`/`snapshot_as_of_date`; pin subgraph version (not `latest`); schema-validate on load; WARN/fail when tx dates postdate snapshot. **RESOLVED (2026-08-04):** the WARN/fail arm is now wired - `LpAutodiscovery.check_freshness` is called from `OnChainThSubstituter.maybe_substitute` (Task 2 of plan `2026-08-05-on-chain-tx-tagger-review-leftovers`), so a tx block postdating the snapshot emits a WARN.
- **M3 (reconciliation sheet wiring):** adopted - wire per-wallet source provenance + row counts + Koinly-vs-on-chain delta into the Crypto Reconciliation sheet.
- **M4 (rollback):** adopted - stamp extract.xlsx with per-wallet source provenance; document rollback procedure (delete leftover + re-run from Koinly).
- **MO1 (RPC fallback limits):** monitor - add per-call timeout, max-retries, hard cap, Excel summary line.
- **MO2 (post-cutover invariants):** monitor - Koinly-independent integrity suite runs every year.
- **A1 (attacker-with-config-write-access):** accepted - single-user personal tax tool; document residual risk; add closed-enum + citation validation (cheap), skip cryptographic signing (expensive, low marginal value).

**All blockers resolved; all mitigations dispositioned. Next step:** write the implementation plan under `docs/history/plans/` incorporating these resolutions as explicit plan tasks (characterization tests first; consumer migrations gated; fail-loud wiring; reconciliation-sheet wiring).
