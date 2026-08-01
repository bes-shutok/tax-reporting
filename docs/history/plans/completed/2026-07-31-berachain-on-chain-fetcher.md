# Plan: Berachain on-chain DEX transaction fetcher

**Status:** planning · **Branch:** `2026-07-31-berachain-on-chain-fetcher` (local-only)

Plan review: `docs/history/reviews/2026-07-31-plan-review-berachain-on-chain-fetcher-r1.md`
(r1: 3 High blocking + 4 Medium + 2 Low; all 9 findings folded into the plan; F1 broad
`except Exception` in wiring + `URLError` RED test; F2 `_EARLIEST_BERA_TX_DATE` named
exemption + positive grep + primary-source cite (not registry); F3 chose pagination
option (b) paginate-from-0 + decoder date filter; F4 dropped `chain_to_native_ticker`
fallback, `native_ticker` required in config; F5 single-WARNING ownership at orchestrator;
F6 dropped `repository_root` param, loader resolves root via `_find_repository_root()`;
F7 defensive `on_chain_year` resolution; F8 off-by-one acknowledged in DI-5; F9 gate lives
in `main.py`.)

Language-guidance links for implementers:
- `docs/maintenance/python_guidelines.md` (PT011 `pytest.raises(..., match=)`, F401 re-exports)
- `docs/maintenance/crypto_implementation_guidelines.md` (pipeline pitfalls; chain/wallet conventions)
- `docs/maintenance/development_lessons.md` (sentinel usage, all-or-nothing config validation, row-level error isolation)
- `AGENTS.md` §3 "Repository Constraints": optional crypto ingestion is **non-blocking** (missing/mismatched/unparseable → warn and continue)

## Terms

- **On-chain fetcher**: a new self-contained module that pulls a wallet's Berachain
  transactions from the Etherscan V2 API and writes a standalone CSV. It does **not**
  feed the existing Koinly-based crypto tax pipeline (no FIFO, no capital-gains, no
  rewards); it is a parallel, year-scoped collection step producing a raw ledger.
- **Etherscan V2 unified endpoint**: `https://api.etherscan.io/v2/api?chainid=<id>&...`.
  Verified live: Berachain Mainnet `chainid=80094` is listed (status=1) on
  `api.etherscan.io/v2/chainlist`, `apiurl=https://api.etherscan.io/v2/api?chainid=80094`.
  `api.berascan.com/api` (V1) returns a deprecation message; `api.berascan.com/v2/api`
  returns 404. **Etherscan V2 is the only working host.** One API key works across all
  60+ V2 chains (multi-chain extensibility is free; the fetcher is keyed by `chainid`).
- **Free-tier pagination cap**: Etherscan reduced the per-request record cap from 10,000
  to **1,000 for Free-tier users, effective 2026-07-01** (in force today). The target
  wallet has ~4,887 Koinly rows; raw `txlist`+`tokentx` will exceed 1,000. **Block-range
  pagination (`startblock`/`endblock`) is mandatory, not optional.**
- **Wallet config file**: a new per-year, **gitignored** JSON file at
  `resources/source/<year>/chains.json` (matches the `.gitignore` rule for personal
  data under `/resources/source/*`). A committed **artificial** template lives at
  `resources/source/example/<year>/chains.json` (the `example` subtree is the only
  re-allowed path). Tests read only the artificial template.
- **`BERA_CHAIN_API_KEY`**: environment variable holding the Etherscan V2 API key.
  Read via `os.getenv(...)`; never committed. Absent/empty → fetcher warns and skips.
  (Greenfield: `os.getenv` is unused in `src/` today; this is the first env-var read.)

## Gist & Examples

**What changes.** Today the project's only crypto data source is Koinly CSV exports
(pre-decoded by Koinly). This plan adds a **second, independent on-chain data source**:
the Etherscan V2 API. For each wallet entry in the year's `chains.json`, the fetcher
pulls all normal transactions (`module=account&action=txlist`) and ERC-20 token
transfers (`module=account&action=tokentx`) within the config-specified date range,
decodes them into flat rows, and writes a single CSV:

```
resources/result/<year>/bera_transactions.csv
```

The fetcher runs automatically as part of `uv run tax-reporting`, gated by two
conditions: (a) a `chains.json` exists for the run's fiscal year, AND (b)
`BERA_CHAIN_API_KEY` is set in the environment. If either is absent, the fetcher
warns (matching the existing optional-ingestion convention at `main.py:248-251`) and
continues; the IB/Koinly report is unaffected.

**Why.** On-chain transaction hashes are the strongest possible audit trail for a tax
filing. Koinly's CSV is pre-processed and opaque; this fetcher gives an authoritative,
hash-anchored wallet-activity ledger that can be reconciled against Koinly later
(reconciliation is explicitly **out of scope** for this plan; see Review Scope).

**Concrete example.** Given `resources/source/2025/chains.json`:

```json
{
  "wallets": [
    {
      "chain": "Berachain",
      "chainid": 80094,
      "label": "Ledger Berachain (BERA)",
      "address": "0xdead000000000000000000000000000000000000",
      "native_ticker": "BERA",
      "start_date": "2025-02-06",
      "end_date": "2025-12-31"
    }
  ]
}
```

…and `BERA_CHAIN_API_KEY` set, a run produces `resources/result/2025/bera_transactions.csv`:

```csv
tx_hash,block_number,timestamp_utc,chain,from_address,to_address,asset,token_address,amount_raw,amount_decimals,direction,fee_asset,fee_amount_raw,wallet_label,wallet_address
0xba76da4e...,1234567,2025-02-25 13:53:25,Berachain,0xdead...00,0x77da...e6,BERA,,1000000000000000000,18,out,BERA,1000000000000,Ledger Berachain (BERA),0xdead000000000000000000000000000000000000
...
```

Each ERC-20 transfer row carries `token_address` + `amount_decimals` (raw integer value
scaled by the token's decimals); native BERA rows leave `token_address` empty and use
18 decimals. `direction` is `in`/`out` relative to the configured wallet address.

**Edge cases that shaped the design.**
- Wallet address is present in `txlist.from` or `txlist.to` (and in `tokentx.from`/`to`).
  The same on-chain tx produces multiple rows: one `txlist` row (native BERA value +
  gas fee) plus N `tokentx` rows (one per ERC-20 transfer leg). All share the same
  `tx_hash` and `block_number`.
- `start_date` before mainnet launch (2025-02-06): the loader **clamps** `start_date`
  up to mainnet launch and logs an INFO (Berachain has no pre-launch txs; a date before
  launch is a config mistake, not a hard error).
- `end_date` after today: clamped to today with an INFO.
- API key valid but rate-limited (`status:"0"`, `result:"Max rate limit reached"`):
  the client retries with exponential backoff (3 calls/sec cap); after N retries it
  raises a `FileProcessingError`, which the orchestrator catches → warns and continues
  (no CSV written).
- Empty result (wallet has no txs in range): writes a header-only CSV (distinguishable
  from "fetch failed, no CSV" by file existence).

## Evaluation Criteria

**Quality dimensions:**
- **Correctness**: every tx touching the configured wallet address within the date
  range appears in the CSV; raw integer amounts are preserved verbatim (no floating
  conversion in the fetcher; decimals are a separate column, not applied); pagination
  by block range retrieves the full history (no silent truncation at the 1,000 cap).
  Verified by: unit tests on the decoder + pagination loop; an integration test with a
  mocked HTTP layer returning a 2-page sequence that exercises block-range advance.
- **Non-blocking safety**: a missing config, missing/empty API key, API error, or parse
  failure NEVER prevents the IB/Koinly report from generating. Verified by: a test that
  runs `_main` with the fetcher enabled but the HTTP layer raising, and asserts the
  extract.xlsx still generates and a WARNING is logged.
- **Config safety**: malformed `chains.json` (missing key, wrong type, non-checksummed
  address, date before mainnet launch, `end_date < start_date`) raises `FileProcessingError`
  with a path-and-reason message; missing config is a silent skip (matches derivatives
  convention). Verified by: per-case RED tests.
- **Maintainability / extensibility**: adding a second chain (e.g. Ethereum, Arbitrum)
  is a config-only change (new entry with a different `chainid`), zero code change. The
  Etherscan client takes `chainid` as a parameter, not a hardcoded constant. AGENTS.md
  rule: **never hardcode a chain ticker/constant/ID without flagging**; `chainid` and
  chain name come from config, never literals in `src/`.
- **Test isolation**: tests never make real network calls; the HTTP function is the
  single injectable seam, patched via `monkeypatch.setattr` (matches
  `tests/unit/application/test_main_koinly_directory.py` convention).

**Release gates:**
- `uv run pytest` green (all 3 tiers).
- `uv run ruff check` clean on touched modules (HEAD-blob baseline; no new `# noqa`).
- A live dry-run against the real wallet (manual, by the operator, with their key) is
  **not** a release gate but is the recommended acceptance step; document the command.

## Review Scope

**Explicit must-fix**; findings on these paths are always in scope (review and fix if valid):

**Production code:**
- `src/tax_reporting/infrastructure/on_chain/etherscan_client.py` *(new)*; thin HTTP+pagination client
- `src/tax_reporting/infrastructure/on_chain/bera_decoder.py` *(new)*; raw API row → flat CSV row decoder
- `src/tax_reporting/application/on_chain_fetcher.py` *(new)*; orchestrator: load config → fetch → decode → write CSV
- `src/tax_reporting/main.py`; wire the fetcher as an optional step inside the crypto `try` block (lines ~252-264), after `generate_tax_report(...)`
- `docs/architecture/integrations.md`; update the "no service-to-service integrations" stance (line 3) to carve out this exception; add Berachain/Etherscan V2 to "Consumed inputs"

**Config / data:**
- `resources/source/example/2025/chains.json` *(new, committed, ARTIFICIAL addresses only)*
- `docs/maintenance/tax/chain_wallets/.gitkeep` or README note *(new)*; documents the gitignored `resources/source/<year>/chains.json` counterpart (NOT committed; personal data)

**Tests:**
- `tests/unit/infrastructure/test_etherscan_client.py` *(new)*
- `tests/unit/infrastructure/test_bera_decoder.py` *(new)*
- `tests/unit/application/test_on_chain_config_loader.py` *(new)*
- `tests/unit/application/test_on_chain_fetcher.py` *(new)*
- `tests/unit/application/test_main_on_chain_wiring.py` *(new)*; the non-blocking gate
- `tests/integration/test_on_chain_fetch_integration.py` *(new)*; mocked HTTP, 2-page block-range sequence

**Plan-related extension**; implementation and review may change files not listed above. Treat a finding as in scope when it is **causally related to this plan**: it implements or completes a plan task, fixes a regression introduced by plan work, closes wiring or docs implied by an explicit must-fix change, or contradicts a contract the plan changed.

**Out of scope; reject unless plan-related:**
- Koinly reconciliation / cross-validation (the fetcher writes its CSV independently; diffing against Koinly is a future plan).
- Feeding fetched txs into the existing crypto FIFO / capital-gains / rewards pipeline (would need price oracle + swap decoding; future plan).
- Swap-semantic decoding (Kodiak router ABI / subgraph overlay); `tokentx` rows are emitted as flat transfer legs; reconstructing "trade A→B" pairs is a future plan.
- Adding `httpx`/`requests` as a dependency; the client uses stdlib `urllib.request` (the project has no HTTP client today and this keeps the dependency surface unchanged).
- Any change to the existing crypto tax pipeline modules (`crypto_reporting.py`, `crypto_fifo/`, `token_origin.py`, etc.); frozen.

## Design Invariants (CR Guard)

- **DI-1 (non-blocking, broad catch):** the fetcher is optional. Missing config, missing/empty
  `BERA_CHAIN_API_KEY`, **any** API/network/parse failure → `logger.warning(...,
  "Continuing without on-chain transaction data.")` and the run proceeds. Mirrors the
  **broad** `except Exception` Koinly degrade template at `main.py:394-408` (NOT a narrow
  `except FileProcessingError`): the `urllib` stack raises `urllib.error.URLError`/
  `OSError`/`TimeoutError`/`json.JSONDecodeError`, none of which is a `FileProcessingError`,
  and any latent bug raises plain `Exception`. The fetcher wiring block in `main.py` MUST
  catch `Exception` (not just `FileProcessingError`) and log the WARNING; the outer crypto
  `try` tail at `main.py:272-273` (`except Exception → raise ReportGenerationError`)
  would otherwise abort the IB/Koinly report. (r1 review F1.) The fetcher internally
  translates known failure modes into `FileProcessingError` for clean attribution, but the
  wiring catch is broad so an unexpected type cannot escape. The ONLY exception that
  propagates is `ConfigurationError` (consistent with the existing contract), but the
  fetcher does not raise `ConfigurationError` for any of its own conditions.
- **DI-2 (config-driven, no hardcoded chain identity; ONE named exemption):** `chainid`,
  chain name, wallet address, label, date range, AND native ticker come EXCLUSIVELY from
  `chains.json`. No `80094`, `"Berachain"`, `"BERA"`, a wallet address, OR a
  `chain_to_native_ticker` fallback map appears as a literal in `src/`. **The single named
  exemption** is `_EARLIEST_BERA_TX_DATE = date(2025, 2, 6)` in `on_chain_config.py`, used
  only to clamp an overly-early `start_date`. This date is the **Berachain mainnet
  genesis-block date** (verified from primary sources: Blockworks/Bankless mainnet launch
  2025-02-06), NOT the registry's `service_start_date: 2025-02-05` (which is the BERA Chain
  Foundation's legal-entity service date; a different semantic). The constant's comment
  cites the primary source, not the registry. (r1 review F2.) AGENTS.md rule: never hardcode
  a chain ticker/constant/ID without flagging; this constant is flagged and justified here.
- **DI-3 (injectable HTTP seam; gate lives in wiring):** all network access goes through a
  single module-level function (`_http_get_json(url, params) -> dict`) in `etherscan_client.py`.
  Tests patch THAT symbol via `monkeypatch.setattr("tax_reporting.infrastructure.on_chain.etherscan_client._http_get_json", fake)`.
  No test patches `urllib.request.urlopen` directly (diverges from every existing test). The
  `BERA_CHAIN_API_KEY` presence check AND the empty-config check live in `main.py` (the
  wiring layer), NOT inside `run_on_chain_fetch`; so a missing key is a wiring-level skip,
  and `test_main_on_chain_wiring#skips_when_env_var_absent` genuinely tests wiring by
  patching `run_on_chain_fetch` and asserting it was never called. (r1 review F9.)
- **DI-4 (raw-amount preservation):** the decoder writes the API's raw integer `value`
  verbatim into `amount_raw`; token decimals go in a separate `amount_decimals` column.
  The fetcher NEVER converts to float/Decimal (AGENTS.md: numeric fields from external
  reports; detect separators or fail; here we sidestep by preserving the integer).
- **DI-5 (block-range pagination; steady-state startblock=0):** the client uses
  **option (b)** from planning: paginate from `startblock=0` and filter rows by `timeStamp`
  in the decoder (Task 4's `#row_date_filtered_outside_range` owns the date filter). This
  avoids 2 extra `getblocknbytime` calls per wallet per run and is simpler. Consequence:
  `startblock=0` is the steady-state first call on every run; the block-range advance
  (`startblock = lastReturnedBlockNumber + 1` whenever a page returns exactly `page_size`
  rows) is the mechanism that prevents re-fetching the same full page forever; it does NOT
  bound the initial window. Page-count pagination (`page`/`offset`) alone is INSUFFICIENT on
  the Free tier (1,000 cap, effective 2026-07-01). A `max_rows` ceiling guards against an
  API that returns full pages of real rows forever. NOTE: a history whose length is an exact
  multiple of `page_size` triggers one additional empty-page request; this is intentional,
  because Etherscan returns no total-count field on the Free tier and the empty page
  (`message:"No transactions found"`) is the only reliable end-of-stream signal. (r1 reviews
  F3, F8.)
- **DI-6 (config loader mirrors derivatives template; single-WARNING ownership):** reuse
  `load_guarded_json` from `infrastructure/json_loader.py`; implement an `_on_error` with
  policy missing → return `DEGRADED` silently (loader logs NOTHING), all other kinds → raise
  `FileProcessingError`. The single WARNING for "config missing/empty" is owned by the
  ORCHESTRATOR layer (`run_on_chain_fetch` / `main.py`), NOT the loader; this mirrors the
  derivatives template's explicit comment (`derivatives_filter.py:124-128`: "Logging here
  would double-warn for the same condition") and avoids the double-WARNING defect. (r1 review F5.)
  Schema validation (dict with `wallets` list; each entry has required keys with correct
  types) runs caller-side, modeled on `_load_derivatives_labels_config_from_path`
  (`application/crypto/derivatives_filter.py:102-156`).
- **DI-7 (committed example uses artificial data):** `resources/source/example/2025/chains.json`
  contains only explicitly-artificial addresses (e.g. `0x0000000000000000000000000000000000001111`,
  `0xdead000000000000000000000000000000000000`); never a real wallet, never data scraped
  from chain. (AGENTS.md: tests read committed synthetic data; user instruction.)
- **DI-8 (repo-root resolution; no private-symbol import):** `run_on_chain_fetch` does NOT
  take a `repository_root` parameter. The config loader (`on_chain_config.py`) resolves the
  repo root itself via the SAME `_find_repository_root()` helper that
  `application/crypto/classification.py:44` uses (import the helper, not the private
  `_REPOSITORY_ROOT` binding); OR, if circular-import risk exists, compute it via the
  `Path(__file__).resolve().parents[N]` pattern `cli()` already uses at `main.py:466`.
  `main.py` passes only `year`, `output_dir` (the validated `validated_output_dir`), and
  `api_key` to `run_on_chain_fetch`. (r1 review F6.)
- **DI-9 (year resolution defensive):** the wiring point resolves the fetcher's year via
  `on_chain_year = tax_jurisdiction.fiscal_year if tax_jurisdiction is not None else tax_year_hint`,
  and SKIPS the fetcher entirely if both are `None` (mirroring the existing fallback at
  `main.py:226-227`). This avoids an `AttributeError` if a future change makes
  `tax_jurisdiction` `None` at the insertion point. (r1 review F7.)

## Validation Commands

```bash
# Full suite (3 tiers); must be green
uv run pytest

# Lint touched modules against HEAD baseline (no new violations; do NOT --fix re-export modules)
uv run ruff check src/tax_reporting/infrastructure/on_chain/ src/tax_reporting/application/on_chain_fetcher.py src/tax_reporting/main.py

# DI-2 backstop: NO chain identity literals in src/ (chainid, chain name, ticker, wallet
# address, AND the native-ticker fallback map symbol). Widened per r1 review F4.
# Asserts zero matches; the `!` negation makes the pass condition explicit (zero hits = pass).
! grep -rEn "80094|Berachain|\"BERA\"|0x6abd7c1c|chain_to_native_ticker" src/tax_reporting/infrastructure/on_chain/ src/tax_reporting/application/on_chain_fetcher.py src/tax_reporting/application/on_chain_config.py
# main.py may reference the fetcher by symbol name only; assert no chain literals leaked there
! grep -rEn "80094|0x6abd7c1c" src/tax_reporting/main.py

# DI-2 positive assertion: the ONE permitted constant exists exactly once, in on_chain_config.py.
# (r1 review F2: the exemption must be enforced, not asserted.)
test "$(grep -rEn "_EARLIEST_BERA_TX_DATE" src/tax_reporting/ | wc -l | tr -d ' ')" -le 2 && \
  grep -rEn "_EARLIEST_BERA_TX_DATE" src/tax_reporting/ | grep -q "on_chain_config" && \
  echo "constant-exemption OK"

# DI-3 backstop: no test patches urllib directly
! grep -rEn "monkeypatch\.setattr.*urllib|urlopen" tests/

# DI-7 backstop: the committed example contains only the known artificial address
! grep -rEn "0x[0-9a-fA-F]{40}" resources/source/example/ | grep -v "0x0000000000000000000000000000000000001111"

# Config-template shape: the artificial example parses and validates
uv run python -c "import json,pathlib; d=json.loads(pathlib.Path('resources/source/example/2025/chains.json').read_text()); assert isinstance(d.get('wallets'), list) and d['wallets']; w=d['wallets'][0]; assert all(k in w for k in ('chain','chainid','label','address','native_ticker','start_date','end_date')); print('example config OK')"

# Integrations doc no longer claims 'no runtime integrations' unconditionally
grep -n "on-chain\|on_chain\|Etherscan" docs/architecture/integrations.md
```

---

### Task 1: Config schema + artificial template

Files:
- `resources/source/example/2025/chains.json` *(new, committed, artificial)*
- `docs/maintenance/tax/chain_wallets/README.md` *(new)*; documents the gitignored personal counterpart

- [x] Create `resources/source/example/2025/chains.json` with EXPLICITLY artificial data: a single wallet entry using `0x0000000000000000000000000000000000001111` as the address, `chain: "Examplechain"`, `chainid: 99999`, `label: "Example Wallet (EXM)"`, `native_ticker: "EXM"`, `start_date: "2025-02-06"`, `end_date: "2025-12-31"`. Do NOT use Berachain, 80094, BERA, or any real address (DI-2, DI-7). `native_ticker` is REQUIRED (no fallback map; r1 F4).
- [x] Create `docs/maintenance/tax/chain_wallets/README.md` documenting: (a) the schema (`wallets[].{chain, chainid, label, address, native_ticker, start_date, end_date}`; `native_ticker` required), (b) the committed artificial template at `resources/source/example/<year>/chains.json`, (c) the **gitignored** personal counterpart at `resources/source/<year>/chains.json` that the operator creates locally, (d) `BERA_CHAIN_API_KEY` env var requirement + Etherscan registration URL.
- [x] Commit: `feat(on-chain): add chains.json schema + artificial template + README`

---

### Task 2: Config loader (RED → GREEN)

Files:
- `src/tax_reporting/application/on_chain_config.py` *(new)*
- `tests/unit/application/test_on_chain_config_loader.py` *(new)*

- [x] `TestOnChainConfigLoader#load_valid_config`; given an artificial `chains.json` with one valid wallet entry, expects a list of one `OnChainWalletConfig(chain=..., chainid=99999, label=..., address=..., start_date=date(2025,2,6), end_date=date(2025,12,31))`.
- [x] `TestOnChainConfigLoader#missing_config_returns_empty_silent`; given a `chains.json` path that does not exist, expects an empty list AND **no log record emitted by the loader** (loader stays silent; DI-6; the single WARNING is owned by the orchestrator in Task 5/6, mirroring `derivatives_filter.py:124-128`).
- [x] `TestOnChainConfigLoader#malformed_json_raises`; given a `chains.json` with invalid JSON, expects `FileProcessingError` with `match=` naming the path (PT011).
- [x] `TestOnChainConfigLoader#missing_wallets_key_raises`; given valid JSON without a `wallets` key, expects `FileProcessingError` naming the missing key.
- [x] `TestOnChainConfigLoader#wallet_entry_missing_required_field_raises`; given a wallet entry without `address`, expects `FileProcessingError` naming the field and the offending entry index.
- [x] `TestOnChainConfigLoader#wallet_entry_wrong_type_raises`; given `chainid: "80094"` (string instead of int), expects `FileProcessingError`.
- [x] `TestOnChainConfigLoader#native_ticker_required_raises_when_absent`; given a wallet entry WITHOUT `native_ticker`, expects `FileProcessingError` (per F4/r1: there is NO fallback map, so the field is required, not optional).
- [x] `TestOnChainConfigLoader#end_date_before_start_date_raises`; given `start_date=2025-06-01, end_date=2025-05-01`, expects `FileProcessingError`.
- [x] `TestOnChainConfigLoader#start_date_before_mainnet_clamped`; given `start_date=2025-01-01`, expects the returned `start_date` clamped to `2025-02-06` (the `_EARLIEST_BERA_TX_DATE` constant) AND an INFO logged.
- [x] `TestOnChainConfigLoader#end_date_in_future_clamped`; given `end_date=2099-01-01`, expects clamping to today (inject a `today` callable; do NOT add `freezegun` as a dep) AND an INFO logged.
- [x] `TestOnChainConfigLoader#symlink_config_raises`; given a symlinked `chains.json`, expects `FileProcessingError` (reuses `load_guarded_json` symlink guard; Invariant 8; symlink checked before existence).
- [x] Run → expect RED: `uv run pytest tests/unit/application/test_on_chain_config_loader.py`
- [x] Implement `on_chain_config.py`: a frozen dataclass `OnChainWalletConfig(chain, chainid, label, address, native_ticker, start_date, end_date)`; `native_ticker` is REQUIRED (no fallback map; r1 F4); a `load_on_chain_wallets(year: int) -> list[OnChainWalletConfig]` that resolves the repo root itself via `_find_repository_root()` (import the helper from `application.crypto.classification`, NOT the private `_REPOSITORY_ROOT` binding; DI-8) and reads `<repo_root>/resources/source/<year>/chains.json`. Calls `load_guarded_json` with an `_on_error` where missing → return `DEGRADED` → loader returns `[]` SILENTLY (no log; DI-6), other kinds → raise `FileProcessingError`. Schema validation caller-side modeled on `_load_derivatives_labels_config_from_path`. Use `_EARLIEST_BERA_TX_DATE = date(2025, 2, 6)` with a comment citing the primary mainnet-launch source (Blockworks/Bankless 2025-02-06), explicitly NOT the registry's `service_start_date: 2025-02-05` (different semantic; r1 F2).
- [x] Run → expect GREEN.
- [x] Commit: `feat(on-chain): add per-year chains.json config loader`

---

### Task 3: Etherscan V2 client with block-range pagination (RED → GREEN)

Files:
- `src/tax_reporting/infrastructure/on_chain/etherscan_client.py` *(new)*
- `tests/unit/infrastructure/test_etherscan_client.py` *(new)*

- [x] `TestEtherscanClient#fetch_single_page`; given a mocked `_http_get_json` returning `{status:"1", result:[<3 rows with blockNumber 100,101,102>]}` for `txlist`, expects 3 rows and NO block-range advance (page not full).
- [x] `TestEtherscanClient#fetch_paginates_by_block_range`; given a mocked `_http_get_json` that returns a FULL page (page_size=3 rows at blocks 100,101,102) then a second page (blocks 103,104), expects 5 total rows AND the second call's `startblock` param == 103 (proves block-range advance, not page-count increment).
- [x] `TestEtherscanClient#terminates_at_empty_page`; given a mocked sequence ending in `{status:"0", message:"No transactions found", result:[]}`, expects the loop to stop (no infinite loop).
- [x] `TestEtherscanClient#rate_limit_retried_then_succeeds`; given a mocked sequence of `{status:"0", result:"Max rate limit reached"}` then a success page, expects the client to retry (backoff) and return the success page; assert `_http_get_json` was called ≥2 times.
- [x] `TestEtherscanClient#rate_limit_persistent_raises`; given a mocked persistent rate-limit response (exceeds max retries), expects `FileProcessingError` with `match=` naming rate limit.
- [x] `TestEtherscanClient#api_key_missing_in_response_raises`; given `{status:"0", result:"Missing/Invalid API Key"}`, expects `FileProcessingError` with `match=` (distinct from rate-limit; this is a config problem, not transient).
- [x] `TestEtherscanClient#max_rows_guard`; given a mocked infinite-full-page sequence, expects the loop to stop at a configurable max-rows ceiling and log a WARNING (DI-5 termination guard). Add a `caplog.at_level(WARNING)` assertion pinning the WARNING message substring (r2 F3-r2 observability).
- [x] `TestEtherscanClient#fetches_both_txlist_and_tokentx`; given the same wallet, expects the client to issue calls for BOTH `action=txlist` AND `action=tokentx`, returning both row sets (distinguished by which `action` the fake returns for).
- [x] Run → expect RED: `uv run pytest tests/unit/infrastructure/test_etherscan_client.py`
- [x] Implement `etherscan_client.py`: `EtherscanV2Client` (dataclass holding `base_url="https://api.etherscan.io/v2/api"`, `api_key`, `chainid`, `page_size`, `max_retries`, `max_rows`). A module-level `_http_get_json(url, params) -> dict` wraps `urllib.request` (the DI-3 injectable seam). Methods `fetch_normal_txs(address)` and `fetch_token_transfers(address)` share a private `_fetch_with_block_pagination(action, address)` implementing **option (b)** per DI-5: start `startblock=0`, advance `startblock = max(blockNumber) + 1` whenever a page returns exactly `page_size` rows, terminate when a page returns fewer than `page_size` rows OR an empty `result` (`message:"No transactions found"`). Date-range filtering happens in the DECODER (Task 4), NOT the client; the client does NOT call `getblocknbytime`. Acknowledge in the client docstring that `startblock=0` is the steady-state first call on every run and that one extra empty-page request can occur when history length is an exact multiple of `page_size` (r1 F8). Internally translate known failure modes (`URLError`/`TimeoutError` after retries exhausted, `JSONDecodeError`, "Missing/Invalid API Key", persistent "Max rate limit reached") into `FileProcessingError` with wallet/chain context for clean attribution; but note that the main.py wiring catch is broad `except Exception` (DI-1) so an unexpected type still cannot escape. The client redacts `apikey=` from any logged request URL (r1 overflow: secret-in-log).
- [x] Run → expect GREEN.
- [x] Commit: `feat(on-chain): add Etherscan V2 client with block-range pagination`

---

### Task 4: Raw-row → CSV-row decoder (RED → GREEN)

Files:
- `src/tax_reporting/infrastructure/on_chain/bera_decoder.py` *(new)*
- `tests/unit/infrastructure/test_bera_decoder.py` *(new)*

- [x] `TestBeraDecoder#native_bera_txlist_row`; given a `txlist` row `{hash, blockNumber, timeStamp, from, to, value:"1000000000000000000", gas, gasPrice, gasUsed}` and `wallet_address` == `from`, expects a decoded row with `asset="BERA"` (native; but see DI-2: the ticker must come from config's chain→native-ticker map, NOT a hardcoded "BERA"; for txlist rows the asset is the chain's native token, looked up from the wallet config), `token_address=""`, `amount_raw=1000000000000000000`, `amount_decimals=18`, `direction="out"`, `fee_amount_raw = gasUsed*gasPrice`, `fee_asset=native`.
- [x] `TestBeraDecoder#erc20_tokentx_row`; given a `tokentx` row with `tokenSymbol, tokenName, tokenDecimal:"6", contractAddress, value:"5000000"` and `wallet_address` == `to`, expects `amount_raw=5000000`, `amount_decimals=6`, `direction="in"`, `asset` from `tokenSymbol`, `token_address=contractAddress`.
- [x] `TestBeraDecoder#direction_resolved_from_wallet_address`; given the SAME row with `wallet_address` == `from`, expects `direction="out"`; with `wallet_address` == `to`, expects `direction="in"`. (The wallet address comes from config; the decoder is parameterized by it; no guessing.)
- [x] `TestBeraDecoder#row_date_filtered_outside_range`; given a row with `timeStamp` outside `[start_date, end_date]`, expects it to be EXCLUDED (returns None / skipped), with the filter happening in the decoder (not the client); proves date filtering is testable without HTTP.
- [x] `TestBeraDecoder#malformed_row_isolated`; given a row missing `value` or with a non-integer `value`, expects a WARNING logged with row context and the row SKIPPED (AGENTS.md: catch row-level parse errors per row; never let one bad row discard the dataset). Assert the decoder returns the rest.
- [x] `TestBeraDecoder#raw_amount_preserved_no_float`; given `value:"1000000000000000000"`, expects the decoded `amount_raw` field is the STRING `"1000000000000000000"` (or int); NOT a float. Assert `isinstance(amount_raw, int)` and that no float conversion occurred (DI-4).
- [x] `TestBeraDecoder#native_ticker_from_config_not_hardcoded`; given a wallet config with a NON-Berachain chain (use the artificial `Examplechain`/`EXM`), expects the txlist row's `asset` to be `"EXM"` (the config's `native_ticker` field), proving the native asset name flows from config (DI-2). This test must FAIL if the decoder hardcodes `"BERA"` OR has a `chain_to_native_ticker` fallback map. Rename consideration: the module is named `bera_decoder.py`; acceptable since it is a module path, not a chain-identity literal in logic, but if reviewers prefer neutrality, `on_chain_decoder.py` is fine (decide in implementation; not blocking). (r1 F4.)
- [x] Run → expect RED: `uv run pytest tests/unit/infrastructure/test_bera_decoder.py`
- [x] Implement `bera_decoder.py`: a `decode_rows(raw_txlist_rows, raw_tokentx_rows, wallet_config) -> list[OnChainTxRow]` (or an iterator). A frozen `OnChainTxRow` dataclass with the CSV columns. The native asset name for txlist rows comes from `wallet_config.native_ticker`; there is **NO `chain_to_native_ticker` fallback map** (r1 F4); `native_ticker` is a required config field (Task 2 enforces). No `"BERA"` literal in src.
- [x] Run → expect GREEN.
- [x] Commit: `feat(on-chain): add raw-row to CSV-row decoder`

---

### Task 5: Fetcher orchestrator + CSV writer (RED → GREEN)

Files:
- `src/tax_reporting/application/on_chain_fetcher.py` *(new)*
- `tests/unit/application/test_on_chain_fetcher.py` *(new)*

- [x] `TestOnChainFetcher#run_writes_csv_for_single_wallet`; given a config with one artificial wallet, a mocked client returning 2 txlist + 1 tokentx rows, and a mocked decoder, expects `resources/result/<year>/bera_transactions.csv` written with header + 3 data rows, sorted by `(block_number, action_order)`.
- [x] `TestOnChainFetcher#run_creates_year_subdir`; given an `output_dir` without a `<year>/` subdir, expects the fetcher to create `output_dir / str(year) /` before writing (establishes the new per-year output convention; assert the dir exists).
- [x] `TestOnChainFetcher#empty_result_writes_header_only`; given a mocked client returning no rows, expects a header-only CSV (file EXISTS; distinguishes "no txs" from "fetch failed").
- [x] `TestOnChainFetcher#uses_safe_remove_file_before_write`; given a pre-existing `bera_transactions.csv`, expects it to be removed before writing (reuse `safe_remove_file` from `persisting/excel_utils.py:148`); assert the new content replaces the old.
- [x] `TestOnChainFetcher#api_failure_raises_fileprocessingerror`; given a mocked client raising `FileProcessingError`, expects the orchestrator to propagate it (the caller in main.py catches and warns; DI-1).
- [x] `TestOnChainFetcher#multiple_wallets_independent`; given a config with 2 wallet entries (2 chains), expects rows for BOTH wallets in the CSV, each tagged with its own `wallet_label`/`wallet_address`/`chain`.
- [x] Run → expect RED: `uv run pytest tests/unit/application/test_on_chain_fetcher.py`
- [x] Implement `on_chain_fetcher.py`: `run_on_chain_fetch(*, year, output_dir, api_key, http_get_json=None) -> Path | None` (NO `repository_root` param; DI-8; the config loader resolves the repo root itself). Load config via `load_on_chain_wallets(year)`; if empty, log a single WARNING "No chains.json for year %s; continuing without on-chain transaction data." (DI-6: orchestrator owns this WARNING, loader stays silent) and return None. For each wallet, build an `EtherscanV2Client(chainid=wallet.chainid, api_key=..., ...)`, fetch txlist+tokentx, decode, accumulate. Write `output_dir / str(year) / "bera_transactions.csv"` via `csv.DictWriter` (fieldnames from `OnChainTxRow`), calling `safe_remove_file` first. Inject the HTTP seam via `http_get_json` param (defaults to the module-level `_http_get_json`).
- [x] Run → expect GREEN.
- [x] Commit: `feat(on-chain): add fetcher orchestrator + CSV writer`

---

### Task 6: main.py wiring + non-blocking gate (RED → GREEN)

Files:
- `src/tax_reporting/main.py`
- `tests/unit/application/test_main_on_chain_wiring.py` *(new)*

- [x] `TestMainOnChainWiring#skips_when_env_var_absent`; given a run with `chains.json` present but `BERA_CHAIN_API_KEY` unset (monkeypatch `os.getenv` to return None for that key), expects NO fetch call, a WARNING logged mentioning the env var, and the extract.xlsx still generates. Assert the fetcher symbol is not called (`monkeypatch.setattr("tax_reporting.main.run_on_chain_fetch", recorder)`; assert recorder not called). This proves the env-var gate lives in `main.py` (DI-3/DI-9), not inside the fetcher.
- [x] `TestMainOnChainWiring#skips_when_config_absent`; given `BERA_CHAIN_API_KEY` set but no `chains.json` for the year, expects the loader returns `[]` silently (no loader log), the orchestrator-level WARNING fires ONCE (DI-6 single-WARNING ownership), no fetch call, extract.xlsx generates. Assert EXACTLY one WARNING record for the config-absent condition (guards the r1 F5 double-WARNING regression).
- [x] `TestMainOnChainWiring#skips_when_no_jurisdiction`; given no config (so `tax_jurisdiction is None`) AND a `chains.json` present AND `BERA_CHAIN_API_KEY` set, expects the fetcher is NOT called, no `AttributeError` is raised, and a WARNING/INFO is logged (DI-9 defensive year resolution). This future-proofs against the upstream guard being relaxed.
- [x] `TestMainOnChainWiring#runs_when_both_present`; given both config + env var, expects `run_on_chain_fetch` called once with the correct `year` (resolved defensively per DI-9) and `output_dir=validated_output_dir`, extract.xlsx still generates.
- [x] `TestMainOnChainWiring#fetch_failure_non_fileprocessingerror_is_non_blocking`; **(the r1 F1 guard)** given both present but the (mocked) `run_on_chain_fetch` raises `urllib.error.URLError` (NOT `FileProcessingError`), expects a WARNING logged with "Continuing without on-chain transaction data", the run does NOT raise `ReportGenerationError`, and extract.xlsx generates. This is the critical regression guard: the wiring catch is `except Exception` (broad), mirroring `main.py:394-408`, so the `urllib` stack's non-`FileProcessingError` types cannot escape into the outer crypto `try` and abort the IB/Koinly report. Add a parametrized sibling asserting the same for `json.JSONDecodeError` and plain `Exception`.
- [x] `TestMainOnChainWiring#extract_report_unaffected_by_fetch`; given a full happy-path run, asserts the extract.xlsx content is byte-identical (or row-identical) to a run with the fetcher disabled; proves the fetcher never touches the IB/Koinly pipeline (frozen-pipeline invariant).
- [x] Run → expect RED: `uv run pytest tests/unit/application/test_main_on_chain_wiring.py`
- [x] Wire in `main.py`: inside the crypto `try` block (after `generate_tax_report(...)` at line ~252, before the `except ConfigurationError`):
    1. Resolve the year defensively: `on_chain_year = tax_jurisdiction.fiscal_year if tax_jurisdiction is not None else tax_year_hint` (DI-9). If `on_chain_year is None` → log WARNING and skip.
    2. Read `os.getenv("BERA_CHAIN_API_KEY")` (the env-var gate lives HERE in main.py; DI-3). If None/empty → `logger.warning("BERA_CHAIN_API_KEY not set; continuing without on-chain transaction data.")` and skip.
    3. Wrap `run_on_chain_fetch(year=on_chain_year, output_dir=validated_output_dir, api_key=key)` in `try: ... except Exception as exc: logger.warning("On-chain fetch failed: %s. Continuing without on-chain transaction data.", exc)`; **`except Exception`, NOT `except FileProcessingError`** (DI-1/r1 F1). Do NOT re-raise. (Note: the fetcher never raises `ConfigurationError` for its own conditions per DI-1, so a leading `except ConfigurationError: raise` clause is not required today; if a future change makes it possible, add that clause ahead of the broad catch, mirroring `main.py:386-393`.)
    4. Do NOT raise `ConfigurationError` for any fetcher condition (DI-1).
- [x] Run → expect GREEN.
- [x] Commit: `feat(on-chain): wire fetcher into main run as non-blocking optional step`

---

### Task 7: Integration test; mocked 2-page block-range sequence

Files:
- `tests/integration/test_on_chain_fetch_integration.py` *(new)*

- [x] `TestOnChainFetchIntegration#full_flow_two_pages`; given a temporary `resources/source/<year>/chains.json` (artificial wallet), a fake `_http_get_json` that returns a FULL page (3 txlist rows) then a second page (2 rows) then an empty page; exercising block-range advance; then tokentx rows, expects the written CSV to contain all 5 txlist-derived rows + the tokentx rows, sorted, with correct `direction` per the wallet address, and the second-page call's `startblock` param advanced past the first page's max block. This is the DI-5 end-to-end guard.
- [x] `TestOnChainFetchIntegration#date_range_filter_applied`; given rows with timestamps spanning outside `[start_date, end_date]`, expects only in-range rows in the CSV.
- [x] Run → expect GREEN directly (integration; the units already proved the pieces).
- [x] Commit: `test(on-chain): add 2-page block-range integration test`

---

### Task 8: Docs + integrations.md stance update

Files:
- `docs/architecture/integrations.md`
- `README.md` (config/runtime section only; NOT a catch-all)
- `docs/maintenance/development_lessons.md` (new lesson on the env-var-first config choice, if warranted)

- [x] Update `docs/architecture/integrations.md` line 3: change the unconditional "no service-to-service integrations at runtime" to carve out the on-chain fetcher exception (e.g. "no service-to-service integrations at runtime, except the optional on-chain transaction fetcher described below"). Add Berachain/Etherscan V2 to "Consumed inputs" with the endpoint URL and the `BERA_CHAIN_API_KEY` + `chains.json` requirements.
- [x] Update `README.md` runtime/config section: document `BERA_CHAIN_API_KEY` env var and the optional `resources/source/<year>/chains.json` config; note the output `resources/result/<year>/bera_transactions.csv`. Do NOT add operational runbook content to README (per plans skill routing rules).
- [x] Grep sweep for stale "no runtime integrations" / "no service-to-service" claims across `docs/maintenance/` and `docs/architecture/` and update each rendered-text site (AGENTS.md lesson: doc-drift grep backstops must sweep every rendered-text site, not only the edited literal).
- [x] Commit: `docs(on-chain): document Etherscan V2 fetcher + update integrations stance`

---

### Task 9: Final validation + live dry-run note

- [x] Run full suite: `uv run pytest`; expect green.
- [x] Run `uv run ruff check` on all touched modules; expect clean vs HEAD baseline (no new `# noqa`).
- [x] Run the Validation Commands block above; all pass (especially the DI-2/3/7 negated greps).
- [x] Add a one-line note in `docs/maintenance/tax/chain_wallets/README.md` with the manual live dry-run command for the operator: `BERA_CHAIN_API_KEY=<key> uv run tax-reporting` (with their real `resources/source/2025/chains.json`).
- [x] Move plan to `docs/history/plans/completed/` per plans lifecycle.
