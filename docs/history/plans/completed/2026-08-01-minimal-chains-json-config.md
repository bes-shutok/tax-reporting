# Plan: Minimal `chains.json` config - derive chain facts internally

Follow-up to the Berachain on-chain fetcher (`docs/history/plans/completed/2026-07-31-berachain-on-chain-fetcher.md`).

Plan review: `docs/history/reviews/2026-08-01-plan-review-minimal-chains-json-config-r2.md` (r2, latest, ready - 0 blocking; r1 F1-F7 folded, r2 F1-F2 folded below) - r1 `docs/history/reviews/2026-08-01-plan-review-minimal-chains-json-config-r1.md`.

## Terms

- **chains.json**: the per-year on-chain wallet config at `resources/source/<year>/chains.json` (gitignored personal copy) / `resources/source/example/<year>/chains.json` (committed artificial template).
- **DI-2**: a design invariant of the fetcher stating chain identity comes EXCLUSIVELY from user config; see `on_chain_config.py:24-27`. This plan inverts it (see Design Invariants).
- **Chain registry**: the trusted chain-fact maps in `src/tax_reporting/application/crypto/chain_derivation.py` (`_CHAIN_NATIVE_FEE_ASSET` today; this plan adds `_CHAIN_TO_CHAINID` and `_CHAIN_LAUNCH_DATE`).
- **OnChainWalletConfig**: the dataclass returned by `load_on_chain_wallets` (`on_chain_config.py:78`); fields `chain, chainid, label, address, native_ticker, start_date, end_date`.
- **Fiscal year**: the `year` arg threaded through `run_on_chain_fetch` / `load_on_chain_wallets`; used to derive the date window.

## Gist & Examples

**What changes.** Today `chains.json` requires the user to supply all 7 fields:

```jsonc
// BEFORE - user must know chainid, native_ticker, and the date window
{
  "wallets": [
    { "chain": "Berachain", "chainid": 80094, "label": "Ledger Berachain (BERA)",
      "address": "0xdead000000000000000000000000000000000000",
      "native_ticker": "BERA", "start_date": "2025-02-06", "end_date": "2025-12-31" }
  ]
}
```

After this plan the user supplies only **wallet identity** - `chain`, `label`, `address`. The four chain-property fields (`chainid`, `native_ticker`, `start_date`, `end_date`) are derived internally:

```jsonc
// AFTER - minimal user config
{
  "wallets": [
    { "chain": "Berachain", "label": "Ledger Berachain (BERA)",
      "address": "0xdead000000000000000000000000000000000000" }
  ]
}
```

- `chainid` and `native_ticker` come from a new `_CHAIN_TO_CHAINID` map and the existing `_CHAIN_NATIVE_FEE_ASSET` map in `chain_derivation.py` (extended to expose public accessors).
- `start_date` = `max(date(year,1,1), chain_launch_date)`; `end_date` = `min(date(year,12,31), today)`. For Berachain, fiscal year 2025 → `start = 2025-02-06` (Jan 1 clamped up to genesis), `end = 2025-12-31`.

**Why.** `chainid`, `native_ticker`, and the date window are chain/protocol facts, not user choices. `native_ticker` is *already* known to the codebase (`_CHAIN_NATIVE_FEE_ASSET["Berachain"] = "BERA"`) - it was being pointlessly re-asked. The Etherscan V2 API takes only block numbers (`startblock=0`, `endblock=99999999` at `etherscan_client.py:149-150`); `start_date`/`end_date` are a **post-fetch local filter** in the decoder (`bera_decoder.py:151,189` via `_in_date_window`), never an API query parameter - so they were never reducing what's fetched. The fiscal year (already an arg) is the natural window for a year-scoped tax pipeline.

**Constraint that shapes the design.** The fetcher is EVM/Etherscan-V2 only. Of the 14 chains in `_CHAIN_NATIVE_FEE_ASSET`, only 8 are EVM and Etherscan-V2-supported: Ethereum(1), Binance Smart Chain(56), Berachain(80094), Polygon(137), Arbitrum(42161), BASE(8453), Mantle(5000), zkSync Era(324). The `_CHAIN_TO_CHAINID` map contains exactly these 8. Non-EVM chains (Solana, Sui, TON, Aptos, Filecoin, Starknet) are absent.

**Documented supported set is narrower than the internal map (F1 fold).** The fetcher paginates by block number from `startblock=0` (`etherscan_client.py:143,149`); derived `start_date`/`end_date` are a **post-fetch local filter** in the decoder, NOT a bound on the HTTP fetch. For long-history chains (Ethereum, BSC, Polygon, Arbitrum, BASE, zkSync) a single wallet's full history from block 0 will exceed the `max_rows=100000` ceiling (`etherscan_client.py:121,164-173`) and be silently truncated to a prefix with only a WARNING - a tax-data-loss condition. That truncation defect is **pre-existing and out of scope** for this plan (it is tracked separately; fixing it requires date-to-block pagination). To avoid the plan's docs advertising an unsafe capability:
- The **internal** `_CHAIN_TO_CHAINID`/`_CHAIN_LAUNCH_DATE` maps keep all 8 EVM chains (complete and correct).
- The **user-facing docs and the fail-closed error message** scope "supported" to chains whose genesis-to-today history is plausibly under `max_rows` - **Berachain only for now** - with a note that other EVM chains are technically wired but unsafe until the pagination is fixed.
- This matches the only real consumer: the personal `chains.json` has Berachain only.

## Evaluation Criteria

**Quality dimensions:**
- **Correctness**: derived `chainid`/`native_ticker`/`start_date`/`end_date` for a known chain match the values the old hand-written config produced (Berachain 2025 → chainid=80094, ticker=BERA, 2025-02-06..2025-12-31). Verified by loader test + `load_on_chain_wallets(2025)` smoke check.
- **Contract stability for downstream**: `OnChainWalletConfig` keeps all 7 fields; the decoder, fetcher, and every test that constructs the dataclass directly is unchanged. Only the loader's *inputs* change.
- **Fail-closed on unknown chain**: a `chain` value absent from `_CHAIN_TO_CHAINID` raises `FileProcessingError` naming the chain and listing supported chains; never silently produces a None chainid.
- **Registry coherence**: `_CHAIN_TO_CHAINID` is the authoritative EVM set; `_CHAIN_LAUNCH_DATE` has an identical key set, enforced by a module-load assert. `native_ticker_for`/`chain_launch_date` return None for any chain not in `_CHAIN_TO_CHAINID` (fail-closed for non-EVM chains like Solana).
- **Ticker correctness for CSV output (F2 fold)**: `native_ticker_for` does NOT blindly inherit `_CHAIN_NATIVE_FEE_ASSET` (built for Koinly fee-currency matching, a different contract). Polygon migrated MATIC→POL on 2024-09-04 (polygon.technology official blog); `_CHAIN_NATIVE_FEE_ASSET["Polygon"] == "MATIC"` is stale for FY2025+ CSV output. The on-chain ticker map is a **separate**, CSV-output-correct map (see Task 1), not the Koinly fee-check map.
- **No doc drift**: no remaining prose asserting "chainid/native_ticker flow EXCLUSIVELY from config" or "native_ticker is required" or "no chain identity in src/".

**Release gates:**
- `uv run pytest` full suite green.
- `uv run ruff check` on touched src files clean.
- `load_on_chain_wallets(2025)` smoke check returns the expected derived config.

## Review Scope

**Explicit must-fix**; findings on these paths are always in scope (review and fix if valid):

**Production code:**
- `src/tax_reporting/application/crypto/chain_derivation.py`
- `src/tax_reporting/application/on_chain_config.py`
- `src/tax_reporting/infrastructure/on_chain/etherscan_client.py` *(module docstring DI-2 citation only)*
- `src/tax_reporting/application/on_chain_fetcher.py` *(module docstring DI-2 citation only)*
- `resources/source/example/2025/chains.json`
- `resources/source/2025/chains.json` *(gitignored personal)*

**Tests:**
- `tests/unit/application/test_on_chain_config_loader.py` *(primary rewrite)*
- `tests/unit/application/test_on_chain_fetcher.py` *(factory helpers - verify only)*
- `tests/unit/application/test_main_on_chain_wiring.py` *(factory helpers - verify only)*
- `tests/unit/infrastructure/test_bera_decoder.py` *(factory helpers - verify only)*
- `tests/integration/test_on_chain_fetch_integration.py` *(factory helpers - verify only)*

**Documentation:**
- `docs/maintenance/tax/chain_wallets/README.md`
- `docs/architecture/integrations.md`
- `README.md`

**Plan-related extension**; implementation and review may change files not listed above when causally related (e.g. a stale DI-2 prose site surfaced by grep).

**Out of scope; reject unless plan-related:**
- `tests/unit/infrastructure/test_etherscan_client.py` - consumes `chainid` only as an `EtherscanV2Client` constructor kwarg, not the config dataclass; unaffected.
- The Koinly-side `_CHAIN_NATIVE_FEE_ASSET` consumers (`is_native_gas_fee`, `_derive_chain`) - unchanged; the map keeps all 14 entries for its original fee-check purpose.
- `docs/history/reviews/`, `docs/tmp/execute-plan/` - historical artifacts; never edit.

## Design Invariants (CR Guard)

- **DI-2 RESTATED (the core change).** Old: "chain identity (chainid, chain name, ticker, address, dates) comes EXCLUSIVELY from config; no chain identity hardcoded in src/." New: **chain facts (chainid, native_ticker, launch date) live in the trusted chain registry in `chain_derivation.py`; the user supplies only wallet identity (`chain` key, `label`, `address`).** Every DI-2 citation must be swept (4 sites: `on_chain_config.py:24-27`, `chain_wallets/README.md:32`, `etherscan_client.py:5,105`, `on_chain_fetcher.py:23-24`). The existing `_EARLIEST_BERA_TX_DATE` "ONE named exemption" (`on_chain_config.py:52-63`) is subsumed into the general `_CHAIN_LAUNCH_DATE` map.
- **`OnChainWalletConfig` field set is frozen at 7.** The dataclass keeps `chain, chainid, label, address, native_ticker, start_date, end_date`. Only the *source* of 4 fields changes (input → derived). Downstream readers (decoder `_in_date_window`, fetcher, tests constructing the dataclass directly) are unchanged. A reviewer proposing to drop fields from the dataclass breaks 5 test files.
- **Decoder date-window contract unchanged.** `bera_decoder._in_date_window(ts_dt, start, end)` (`bera_decoder.py:84-86`) treats the bounds as opaque inclusive `[start, end]`. Deriving the bounds from the fiscal year instead of user input changes only *which* dates flow in; the decoder is untouched.
- **The 8-chain EVM boundary is enforced by `_CHAIN_TO_CHAINID`'s key set.** This is the gating artifact: a chain must be a key in it to be fetchable. `native_ticker_for`/`chain_launch_date_for` return None for chains not in `_CHAIN_TO_CHAINID` (fail-closed for non-EVM chains), and the loader raises `FileProcessingError` on a None chainid. A RED test pins `native_ticker_for("Solana")` returns None (F3 fold).
- **On-chain ticker map is separate from the Koinly fee-check map (F2 fold).** A new `_CHAIN_ON_CHAIN_NATIVE_TICKER` map (CSV-output-correct) is the source for `native_ticker_for`; `_CHAIN_NATIVE_FEE_ASSET` (Koinly fee matching, 14 entries incl. `"Polygon": "MATIC"`) is left untouched for its original consumer. Polygon's on-chain ticker is `"POL"` for FY2025+. This avoids propagating a stale ticker into tax CSV output.
- **Launch-date semantics = genesis/first-tx, not legal-entity service date.** Berachain's `_CHAIN_LAUNCH_DATE` is `2025-02-06` (genesis, matching the existing `_EARLIEST_BERA_TX_DATE`), NOT the operator registry's `service_start_date: 2025-02-05` (BERA Chain Foundation legal-entity service date). These differ by one day and have different semantics; the on_chain_config.py:59-62 comment documenting this distinction is preserved.

## Validation Commands

```bash
# 1. Loader smoke check - derived values for Berachain 2025
uv run python -c "from tax_reporting.application.on_chain_config import load_on_chain_wallets; w=load_on_chain_wallets(2025)[0]; assert w.chainid==80094 and w.native_ticker=='BERA' and str(w.start_date)=='2025-02-06' and str(w.end_date)=='2025-12-31', (w.chainid,w.native_ticker,w.start_date,w.end_date); print('OK', w.chain, w.chainid, w.native_ticker, w.start_date, w.end_date)"

# 2. Example template still loads (chain switched to a real supported chain)
uv run python -c "from tax_reporting.application.on_chain_config import load_on_chain_wallets; w=load_on_chain_wallets(2025); print('loaded', len(w), 'wallet(s) from example template')"

# 3. Unknown-chain rejection
uv run python -c "import json,pathlib; p=pathlib.Path('resources/source/2025/chains.json'); d=json.loads(p.read_text()); d['wallets'][0]['chain']='Solana'; p.write_text(json.dumps(d))" && \
uv run python -c "from tax_reporting.application.on_chain_config import load_on_chain_wallets; \
from tax_reporting.domain.exceptions import FileProcessingError; \
try:\n load_on_chain_wallets(2025); print('FAIL: no error')\nexcept FileProcessingError as e: print('OK rejected:', str(e)[:80])" ; \
git checkout -- resources/source/2025/chains.json

# 4. Scoped tests
uv run pytest tests/unit/application/test_on_chain_config_loader.py tests/unit/application/test_on_chain_fetcher.py tests/unit/application/test_main_on_chain_wiring.py tests/unit/infrastructure/test_bera_decoder.py tests/integration/test_on_chain_fetch_integration.py -q

# 5. Full suite + lint
uv run pytest -q
uv run ruff check src/tax_reporting/application/on_chain_config.py src/tax_reporting/application/crypto/chain_derivation.py

# 6. Doc-drift backstop: no remaining "EXCLUSIVELY from config" / "native_ticker is required" / "no chain identity in src" / "supplied by config" / "flows in from config" prose (F5 fold: broadened to catch etherscan_client.py:5,105 phrasing)
! grep -rEn "EXCLUSIVELY from this config|native_ticker is.*required|no chain identity is hardcoded|no chain identity in src|chainid.*supplied by config|chain identity.*flows in from config" docs/maintenance docs/architecture README.md src/tax_reporting
```

---

### Task 1: Add chain registry maps + public accessors (RED→GREEN)

Files:
- `src/tax_reporting/application/crypto/chain_derivation.py`
- `docs/maintenance/tax/crypto-origin/official/` *(archive launch-date sources - F4 fold)*

- [x] `TestChainRegistry#test_chainid_for_all_8_supported_evm_chains`; given each of the 8 chains, expects the exact chainid - `chainid_for("Ethereum")==1`, `"Binance Smart Chain"==56`, `"Berachain"==80094`, `"Polygon"==137`, `"Arbitrum"==42161`, `"BASE"==8453`, `"Mantle"==5000`, `"zkSync ERA"==324` (parametrized, one assertion per chain so a wrong value fails individually). Sourced from Etherscan V2 supported-chains doc (https://docs.etherscan.io/supported-chains).
- [x] `TestChainRegistry#test_chainid_for_non_evm_chain_returns_none`; given `"Solana"` and `"Unknown"`, expects `chainid_for(...)` returns None.
- [x] `TestChainRegistry#test_chain_launch_date_for_all_8_chains`; given each chain, expects the exact genesis date - parametrized: `"Berachain"->date(2025,2,6)` (genesis, NOT 2025-02-05 service date), `"Ethereum"->date(2015,7,30)`, `"Binance Smart Chain"->date(2020,9,1)`, `"Polygon"->date(2020,5,28)`, `"Arbitrum"->date(2021,8,31)`, `"BASE"->date(2023,8,9)`, `"Mantle"->date(2023,7,17)`, `"zkSync ERA"->date(2023,3,24)`. Each value cited to an archived source (see F4 archive step).
- [x] `TestChainRegistry#test_native_ticker_for_supported_evm_chains_csv_correct`; given `"Berachain"->"BERA"`, `"Ethereum"->"ETH"`, `"Binance Smart Chain"->"BNB"`, and critically `"Polygon"->"POL"` (NOT `"MATIC"` - F2 fold: POL is the native asset since 2024-09-04 per polygon.technology). Asserts the CSV-output map, not the Koinly fee-check map.
- [x] `TestChainRegistry#test_native_ticker_for_non_evm_chain_returns_none`; given `"Solana"`, `"Sui"`, `"TON"`, expects `native_ticker_for(...)` returns None (F3 fold: fail-closed; the on-chain ticker map does NOT include non-EVM chains even though `_CHAIN_NATIVE_FEE_ASSET` does).
- [x] `TestChainRegistry#test_registry_maps_have_identical_key_sets`; given `_CHAIN_TO_CHAINID`, `_CHAIN_ON_CHAIN_NATIVE_TICKER`, `_CHAIN_LAUNCH_DATE`, expects identical key sets. Add a RED case demonstrating the module-load assert FAILS when a key is added to one map but not another (F3 fold: prove the assert catches real drift).
- [x] Run → expect RED (maps/accessors do not exist yet).
- [x] GREEN - add `from datetime import date`. Add THREE maps with identical 8-key sets: `_CHAIN_TO_CHAINID: Final[dict[str,int]]` (chainids, comment citing Etherscan V2 doc), `_CHAIN_ON_CHAIN_NATIVE_TICKER: Final[dict[str,str]]` (CSV-output-correct tickers; Polygon="POL" with comment citing the 2024-09-04 migration), `_CHAIN_LAUNCH_DATE: Final[dict[str,date]]` (genesis dates). Do NOT modify `_CHAIN_NATIVE_FEE_ASSET` (Koinly fee-check, unchanged). Add accessors `chainid_for(chain)->int|None`, `native_ticker_for(chain)->str|None`, `chain_launch_date(chain)->date|None`, each returning None for chains absent from `_CHAIN_TO_CHAINID`. Add module-load assert that the 3 new maps have identical key sets.
- [x] F4 archive step (r2 F1 fold: do NOT reuse domicile extracts): for EACH of the 8 chains, add (or verify) a genesis/launch-date source under `docs/maintenance/tax/crypto-origin/official/` that actually states the mainnet genesis or first-block DATE - not a domicile/terms extract. The existing `ethereum_foundation_2024-05-08.md` documents the Swiss-Stiftung domicile, NOT the 2015-07-30 genesis, so it does NOT ground Ethereum's launch date; a new genesis source is required for Ethereum too. Add minimal markdown citing the official genesis/announcement (e.g. block-0 timestamp, foundation launch announcement) per chain. Record each in `sources.md` (create if absent). Each `_CHAIN_LAUNCH_DATE` value's comment points to its genesis-dated archived file.
- [x] F4b archive step (r2 F2 fold: symmetric ticker provenance): archive the Polygon POL ticker source too - add (or verify) a source under `docs/maintenance/tax/crypto-origin/official/` that documents the 2024-09-04 MATIC→POL migration (the existing `polygon_terms_2024-01-23.md` is a pre-migration domicile extract and does NOT ground POL). The `_CHAIN_ON_CHAIN_NATIVE_TICKER["Polygon"]="POL"` comment points to it. Apply the same archive standard to any other ticker whose value post-dates a rename/migration.
- [x] Run → expect GREEN.
- [x] Commit: `feat(on-chain): add chain registry maps (chainid, ticker, launch date) with accessors`

### Task 2: Loader derives the 4 fields from fiscal year + registry (RED→GREEN)

Files:
- `src/tax_reporting/application/on_chain_config.py`
- `tests/unit/application/test_on_chain_config_loader.py`

Note: `_build_wallet_config` and `_load_on_chain_wallets_from_path` both live in `on_chain_config.py` (single file); both get the `year` param threaded (overflow finding).

RED first - rewrite the loader test for the new contract:
- [x] `TestOnChainConfigLoader#test_load_minimal_config_derives_all_fields`; given a chains.json with only `{chain:"Berachain", label:"...", address:"0x..."}` for year 2025, expects returned `OnChainWalletConfig` has `chainid==80094`, `native_ticker=="BERA"`, `start_date==date(2025,2,6)` (Jan 1 clamped up to genesis), `end_date==date(2025,12,31)`.
- [x] `TestOnChainConfigLoader#test_dates_derived_from_fiscal_year_for_pre_launch_january`; given year 2025 and Berachain (genesis 2025-02-06), expects `start_date==date(2025,2,6)` (NOT 2025-01-01, because Jan 1 precedes launch).
- [x] `TestOnChainConfigLoader#test_year_entirely_before_launch_raises`; given year 2024 and Berachain (genesis 2025-02-06), expects `FileProcessingError` (derived `end_date` 2024-12-31 < `start_date` 2025-02-06 → empty window).
- [x] `TestOnChainConfigLoader#test_end_date_clamped_to_today`; given a future fiscal year (e.g. 2099) and `today` injected as 2026-08-01, expects `end_date==date(2026,8,1)`.
- [x] `TestOnChainConfigLoader#test_unsupported_chain_raises_scoped_message`; given `{chain:"Solana", ...}`, expects `FileProcessingError` with a discriminating `match=` asserting the message names "Solana" AND contains "Berachain" (the currently-documented-supported chain, F1 fold) AND does NOT contain "Solana" as a supported chain. This fails if the message lists the wrong set or omits the rejection reason.
- [x] `TestOnChainConfigLoader#test_missing_required_field_raises` (parametrized over chain/label/address only); given an entry missing each of `chain`, `label`, `address`, expects `FileProcessingError` matching the field name and "index 0".
- [x] `TestOnChainConfigLoader#test_extra_keys_ignored`; given an entry that ALSO carries the old fields (`chainid`, `native_ticker`, `start_date`, `end_date`), expects they are silently ignored and the derived values are used (hard-break, ignore-extras contract).
- [x] Run → expect RED.
- [x] GREEN - in `on_chain_config.py`: import the 3 accessors; remove `chainid/native_ticker/start_date/end_date` from `_REQUIRED_KEYS`; delete `_EARLIEST_BERA_TX_DATE`; thread `year` into `_load_on_chain_wallets_from_path` and `_build_wallet_config`; in `_build_wallet_config` resolve `chainid_val`/`ticker`/`launch` (raise `FileProcessingError` on None chainid with a message that names the chain and documents Berachain as the currently-supported chain, noting other EVM chains are wired but unsafe due to a pre-existing pagination truncation - F1 fold), compute `start_date=max(date(year,1,1),launch)` / `end_date=min(date(year,12,31),now)`, keep the `end_date < start_date` invariant check; remove the two old user-input clamp INFO logs. Keep `OnChainWalletConfig` field set unchanged.
- [x] Run → expect GREEN.
- [x] Commit: `refactor(on-chain): derive chainid/ticker/dates from registry + fiscal year`

### Task 3: Update example template + personal config

Files:
- `resources/source/example/2025/chains.json`
- `resources/source/2025/chains.json` *(gitignored)*

- [x] Reduce `resources/source/example/2025/chains.json` to `{chain:"Berachain", label:"Example Wallet (BERA)", address:"0x0000000000000000000000000000000000001111"}` (switch chain from fake "Examplechain" to real "Berachain" so the template loads; keep the obviously-fake address - DI-7: no real addresses in committed template).
- [x] Reduce `resources/source/2025/chains.json` to `{chain:"Berachain", label:"Ledger Berachain (BERA)", address:"<operator's real wallet address>"}` (gitignored; not committed).
- [x] Run loader smoke check (Validation Command #1 and #2); both load with derived chainid=80094, ticker=BERA.
- [x] Commit: `chore(on-chain): minimize chains.json to wallet identity only`

### Task 4: Sweep DI-2 citations in src docstrings

Files:
- `src/tax_reporting/application/on_chain_config.py` *(module docstring)*
- `src/tax_reporting/infrastructure/on_chain/etherscan_client.py` *(module docstring + EtherscanV2Client docstring)*
- `src/tax_reporting/application/on_chain_fetcher.py` *(module docstring)*

- [x] In each module docstring, restate DI-2: chain facts come from the trusted registry in `chain_derivation.py`; the user supplies only wallet identity. Remove any "EXCLUSIVELY from config" / "never hardcoded" / "supplied by config" / "flows in from config" wording that the new maps contradict. Keep accurate statements (e.g. "chainid flows from the registry via `OnChainWalletConfig`"). **F7 fold:** for the `on_chain_config.py` module docstring, scope the edit to the DI-2 paragraph only; explicitly PRESERVE the DI-6 (single-WARNING ownership), DI-8 (repo-root resolution), and Schema-validation (`_load_derivatives_labels_config_from_path`) notes - do not delete them in the DI-2 rewrite.
- [x] Run Validation Command #6 (doc-drift backstop) over `src/tax_reporting`; expect zero matches.
- [x] Commit: `docs(on-chain): restate DI-2 invariant for registry-derived chain facts`

### Task 5: Update user-facing docs

Files:
- `docs/maintenance/tax/chain_wallets/README.md`
- `docs/architecture/integrations.md`
- `README.md`

- [x] Rewrite `chain_wallets/README.md` §Schema: show the minimal 3-field user schema (`chain`, `label`, `address`); add a "Derived fields" subsection listing `chainid`/`native_ticker` (source: chain registry in `chain_derivation.py`) and `start_date`/`end_date` (source: fiscal year clamped to chain launch / today). Restate DI-2. Update the template description (§b) to reflect the 3-field shape. Remove "native_ticker is required" and "no fallback map" prose. **F1 fold:** document the supported chain set as Berachain-only for now, with a note that other EVM chains are internally wired but unsafe until the block-0 pagination truncation is fixed (tracked separately).
- [x] `docs/architecture/integrations.md` L8: change "chain id + wallet list" → "wallet list (chain id and native ticker are derived from an internal chain registry)".
- [x] `README.md` L79: change "chain id and wallet list" → "wallet list (chain identity is derived from an internal chain registry)".
- [x] Run Validation Command #6 over `docs/maintenance docs/architecture README.md`; expect zero matches.
- [x] Commit: `docs(on-chain): document minimal chains.json schema and derived fields`

### Task 6: Final validation

- [x] Run `uv run pytest -q` (full suite) → expect green.
- [x] Run `uv run ruff check src/tax_reporting/application/on_chain_config.py src/tax_reporting/application/crypto/chain_derivation.py` → expect clean.
- [x] Run Validation Commands #1-#6 → all pass.
- [x] No commit/push unless instructed (repo is local-only per AGENTS.md).
