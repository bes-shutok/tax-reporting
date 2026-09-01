# Plan: Bridge-asset registry gate (spam airdrop vs trusted bridge mint)

Backlog origin: `docs/history/backlog/completed/2026-08-26-on-chain-review-followups.md`
item 3 (review r1 F8 discriminator gap; moved to `completed/` by this plan's
Task 3). Language/testing traps reference:
`docs/maintenance/python_guidelines.md`.
Contract decisions: 2026-08-26 the user approved the registry-gate scope with a
committed example template of public contracts; 2026-08-27 the user AMENDED the
ownership design (challenge: addresses of widely known public interchain
swappers/bridged tokens must not be user-maintained): the committed registry IS
the canonical curated public registry, the gitignored user file is an optional
escape hatch only, and no task populates a user registry. Rejected alternative:
union (base-plus-extension) resolution semantics; shadow semantics stay (the
C8-mirrored shared loader is unchanged).
Plan review: `docs/history/reviews/2026-08-26-plan-review-bridge-asset-registry-gate-r*.md`
(all rounds; glob reference, no enumerated round count).

## Terms

- **Zero-address mint**: a PURE inflow whose leg was issued by the zero address
  (`_is_zero_address(leg.from_address)`); no external sender exists; today
  `_reward_sub_type` (`berachain_processor.py:1176`, branch at :1192) classifies
  every such mint `Reward`/`SubType.bridge` + review, rendered Tag `Bridge` via the
  single `SUB_TYPE_TAG_OVERRIDES` entry.
- **Bridged-asset registry**: a NEW per-year registry of token contract addresses
  that are bridge-issued (the trusted-mint allowlist), mirroring the C8
  position-NFT membership boundary; `Leg.token_address` is the lookup key.
  Ownership (2026-08-27 amendment): the COMMITTED
  `resources/source/example/<year>/bera_bridged_assets.json` is the canonical
  curated registry of public canonical token contracts (production data, not a
  synthetic template); an OPTIONAL gitignored user file
  `resources/source/<year>/bera_bridged_assets.json` shadows it as an escape
  hatch for entries not yet committed. Public assets never require a user file.
- **C8 position-NFT membership boundary**: the precedent pattern:
  `src/tax_reporting/infrastructure/on_chain/position_token_registry.py` (symlink
  guard, size cap, schema validation, missing → empty registry + actionable
  WARNING) with a per-year facade in `application/on_chain_config.py`
  (`load_position_token_registry_for_year`) resolving via
  `resolve_registry_path` (`application/paths.py:46`: user
  `resources/source/<year>/` first, committed `resources/source/example/<year>/`
  fallback).
- **P2 keying rule**: the future rewards-from-on-chain split must key on the Tag
  (`Bridge`) and the review flag, NEVER on `EventType.Reward` alone
  (`on_chain_validation.md` "Bridge-mint classification").
- **Skill-gate marker / Session key**: see the Terms of
  `2026-08-26-on-chain-staleness-refusal.md` (same recipe; refresh before every
  Write/Edit to this plan file; FAIL-LOUD).

## Gist & Examples

The zero-address marker does not distinguish a trusted bridge mint (the wallet's
bridged WBTC deposits) from a junk airdrop mint; ANY token minted directly to the
wallet currently classifies `Reward`/`SubType.bridge` with Tag `Bridge`, the review
flag the only guard. This plan adds the registry discriminator:

- A zero-address mint of a token IN the bridged-asset registry → `SubType.bridge`,
  Tag `Bridge`, review with the existing bridge reason (unchanged behavior for
  registered assets).
- A zero-address mint NOT in the registry → `SubType.spam`, the default Reward tag
  (no override entry exists for spam), review with a NEW mint-specific spam reason
  naming the unregistered token; not the generic "sender ... is not a registered
  reward distributor" text, which would be wrong for a mint with no sender.
- Registry resolution mirrors the position-token chain: OPTIONAL user override
  `resources/source/<year>/bera_bridged_assets.json` → committed canonical
  `resources/source/example/<year>/bera_bridged_assets.json` → empty registry +
  actionable WARNING only when the committed file itself is missing (a corrupted
  checkout). A normal fresh clone loads the committed registry, so registered
  assets classify bridge out of the box; nothing is silently clean.

Ownership rationale (2026-08-27 user amendment): which token contracts are
bridge-issued is public knowledge (canonical contracts documented by the issuing
bridges and archived in the crypto-origin corpus), so the committed,
provenance-cited file is the source of truth and the agent curates it; the user
never hand-maintains public addresses (Wormhole-class swappers included). The
crypto-origin rule bans auto-discovered guesses without provenance; it does not
require user ownership. The committed entries carry registry-level `source`
provenance and per-entry `note`s naming the origin documents. User-owned data
stays exactly the personal layer: `chains.json` wallets, the dispositions TOML,
Koinly exports.

Amendment (2026-08-28, review r1 F5): the parenthetical above is superseded -
the crypto-origin corpus establishes chain domicile only, NOT token contracts
(neither committed address appears in `docs/maintenance/tax/`; see development
lesson #159 and the shipped registry's own `source` provenance, which cites the
2025 TH baseline and public explorer knowledge instead). Review r2
overflow: this amendment also supersedes the Task 2 bullet's "archived in
the crypto-origin documents" / "per-entry `note` naming the origin document"
wording in the Gist paragraph above and the Task 2 bullet below - the entries were derived from the 2025 TH baseline and
public explorer knowledge, not from crypto-origin documents (same lesson
#159 provenance story).

Example: the wallet receives 0.001 WBTC minted from the zero address (bridge
deposit, WBTC in registry) → `Reward`/`bridge`, Tag `Bridge`, review "verify source
and cost basis". The wallet receives 5,000,000 JUNK minted from the zero address
(airdrop, not in registry) → `Reward`/`spam`, review naming the unregistered mint.

Known consequence, accepted: unregistered zero-address mints in the 2025 baseline
will change projected combos (`crypto_deposit/Bridge` → the spam rendering), so the
validation gate may surface new clusters for them; registered assets' clusters must
be unchanged (Ship-when check).

## Evaluation Criteria

**Quality dimensions:**
- Correctness: registry members keep Bridge; unregistered/empty-registry/native
  (`token_address=None`) mints classify spam + review; membership is
  case-insensitive (checksummed leg vs lowercase registry entry).
- Review-surface quality (PT-C-030 family): each of the three reason branches
  (bridge, mint-spam, sender-spam) is specific and actionable; branch keys on the
  discriminator the upstream sets (`SubType` + the zero-address fact; UL #91).
- Hermeticity: tests read committed synthetic fixtures / the example template only;
  the optional user `resources/source/<year>/bera_bridged_assets.json` is
  gitignored user data and stays ABSENT by default (audit-hook guard).

**Done when:**
- All new unit tests GREEN (processor gate, loader, substitution wiring); full
  `uv run pytest -q` suite green.
- Validation Commands block passes, including the fail-closed doc sweep.

**Ship when:**
- The user runs `--validate-on-chain-th 2025` and confirms the baseline clusters for
  registered bridged assets are unchanged (the harness is user-run per AGENTS.md;
  new spam clusters for unregistered mints, if any, are dispositioned then).

## Review Scope

**Explicit must-fix**; findings on these paths are always in scope (review and fix if valid):

**Production code:**
- `src/tax_reporting/infrastructure/on_chain/bridged_asset_registry.py` *(new)*
- `src/tax_reporting/infrastructure/on_chain/berachain_processor.py` *(only `__init__` registry param, `_reward_sub_type`, and `_reward_event`; all other methods frozen; reject findings touching them; r2-F1; plus a comment-only alignment edit in the split-routing comment, review r2; no behavior change)*
- `src/tax_reporting/application/on_chain_config.py` *(new facade only)*
- `src/tax_reporting/application/on_chain_th_substitution.py` *(only `__init__` registry kwarg, `_load_registries`, `_build_processor`, and the registry-unpack call site in `build_projection` ~:418-424 that the 4-tuple return forces; r1-F2)*
- `resources/source/example/2025/bera_bridged_assets.json` *(new)*
- `docs/maintenance/on_chain_validation.md`

**Tests:**
- `tests/unit/infrastructure/test_bridged_asset_registry.py` *(new)*
- `tests/unit/infrastructure/test_berachain_processor.py`
- `tests/unit/application/test_on_chain_th_substitution.py`

**Plan-related extension**; implementation and review may change files not listed above.
Treat a finding as in scope when it is causally related to this plan: it implements or
completes a plan task, fixes a regression introduced by plan work, closes wiring or docs
implied by an explicit must-fix change, or contradicts a contract the plan changed.
In scope by that rule: existing tests that assert `SubType.bridge` for zero-address
mints and therefore need registry fixtures (data-identity grep below is a plan task).
If the link to the plan is weak or speculative, drop as out of scope with a one-line reason.

**Out of scope; reject unless plan-related:**
- `src/tax_reporting/application/on_chain_th_adapter.py`; `SUB_TYPE_TAG_OVERRIDES`
  gains no entry (spam keeps the default Reward tag).
- `src/tax_reporting/application/on_chain_validation/comparator.py`; the reverse map
  derives automatically and no new combo is introduced.
- BerachainProcessor decomposition: the module already exceeds the 1,000-line rule on
  master; this plan adds ~15 lines to `_reward_sub_type`/`_reward_event` and does NOT
  take the decomposition (pre-existing debt, separate effort).

## Design Invariants (CR Guard)

- **Registry members' behavior byte-identical**: a registered token's zero-address
  mint classifies, renders, and reviews exactly as today (`Reward`/`bridge`, Tag
  `Bridge`, existing bridge reason).
- **Nothing silently clean**: spam mints keep `review=True` with a specific reason;
  an empty/missing registry degrades to spam + review with an actionable WARNING,
  never to clean staking or silent bridge.
- **`SUB_TYPE_TAG_OVERRIDES` frozen**: exactly one entry (`(Reward, bridge) ->
  "Bridge"`); the spam rendering comes from the base map, not a new override.
- **P2 keying rule preserved**: consumers still discriminate on Tag + review flag;
  this plan changes which mints get the Bridge tag, not what the tag means.
- **Registry semantics mirror C8**: per-year, keyed by token address, optional
  user override → committed canonical fallback → empty + WARNING; symlink/size/
  schema guards identical in kind to `position_token_registry.py`. The committed
  file is the CANONICAL registry (public contracts, provenance-cited); the user
  file is an optional escape hatch that SHADOWS the committed one
  (first-match-wins, same as C8) and is never required for public assets. No
  task or doc may instruct populating a user registry for publicly documented
  assets.
- **Public-fact vs personal-data ownership boundary** (2026-08-27 amendment):
  registry membership is a public fact and lives committed; personal data (self
  wallets in `chains.json`, the dispositions TOML, Koinly exports) stays
  gitignored/user-owned. Absence of the user file must not degrade classification
  of committed assets: the loader falls back to the committed file, never to an
  empty registry while the committed file exists.
- **UL #91 discriminator branching**: `_reward_event` picks the reason by branching
  on `SubType` plus the zero-address fact (the discriminator combination upstream
  sets); RED tests must exercise all three causes (bridge, mint-spam, sender-spam).
- **PII boundary**: the committed canonical registry contains PUBLIC canonical token
  contract addresses only (no personal wallets/tx hashes); the user's optional
  override stays gitignored. Hardcoded-value rule: the committed addresses are
  flagged here as public-contract data (user-approved scope 2026-08-26), not
  invented constants.

## Validation Commands

```bash
test -f src/tax_reporting/infrastructure/on_chain/bridged_asset_registry.py \
  || { echo "bridged_asset_registry.py missing"; exit 1; }
test -f resources/source/example/2025/bera_bridged_assets.json \
  || { echo "example template missing"; exit 1; }
python3 -c "import json,sys; d=json.load(open('resources/source/example/2025/bera_bridged_assets.json')); sys.exit(0 if isinstance(d.get('source'), str) and d['source'].strip() else 1)" \
  || { echo "canonical registry lacks registry-level source provenance (or is invalid JSON)"; exit 1; }
grep -q "is_bridged_asset(" src/tax_reporting/infrastructure/on_chain/berachain_processor.py \
  || { echo "processor gate unwired"; exit 1; }
grep -q "load_bridged_asset_registry_for_year" src/tax_reporting/application/on_chain_config.py \
  || { echo "per-year facade missing"; exit 1; }

# Doc rewrite landed + old discriminator-gap prose gone (fail-closed):
test -f docs/maintenance/on_chain_validation.md || { echo "missing maintenance doc"; exit 1; }
grep -q "bridged-asset registry" docs/maintenance/on_chain_validation.md \
  || { echo "new registry contract missing from on_chain_validation.md"; exit 1; }
# r5-F1: the swept sentence is LINE-WRAPPED in the doc (:365-366), so a
# line-based grep can never fire; flatten before matching (the same wrap hazard
# the staleness plan hit at its r2):
if tr '\n' ' ' < docs/maintenance/on_chain_validation.md | grep -q "ANY token minted directly to the wallet classifies"; then
  echo "stale discriminator-gap prose remains"; exit 1
fi

uv run pytest tests/unit/infrastructure/test_bridged_asset_registry.py \
  tests/unit/infrastructure/test_berachain_processor.py \
  tests/unit/application/test_on_chain_th_substitution.py -q
uv run pytest -q
```

(The doc sweep targets the maintenance doc only; this plan file quotes the old
phrase as its checker literal.)

### Task 1: RED; processor gate, loader, and wiring tests

Files:
- `tests/unit/infrastructure/test_berachain_processor.py`
- `tests/unit/infrastructure/test_bridged_asset_registry.py` *(new)*
- `tests/unit/application/test_on_chain_th_substitution.py`

- [x] Inventory the existing bridge fixtures that must keep passing: `grep -n "SubType.bridge" tests/unit/infrastructure/test_berachain_processor.py` (r1-F1; the grep is authoritative; live sites at :1252/:1295/:1336/:1398/:1400 plus helper constructions as of r3); list each in the task log; Task 2 threads a synthetic registry fixture through them BEFORE the GREEN run (default `None` behaves as an empty registry and would otherwise flip their mints to spam)
- [x] `TestBerachainProcessor#test_reward_then_swap_split_mint_leg_registry_gate`; given a reward-claim-then-swap tx whose reward in-leg is a zero-address mint (the split-routing at :1086-1091 also feeds `_reward_sub_type`), expects registered → the Reward half is `bridge` with the Swap unchanged, and unregistered → the Reward half is `spam` + review (r1-F3: the split path is a second gate entry)
- [x] `TestBerachainProcessor#test_zero_address_mint_registered_token_bridge`; given a zero-address mint of a token whose address is in the synthetic bridged-asset registry, expects `Reward`/`SubType.bridge` with the bridge review reason (characterization: today's behavior)
- [x] `TestBerachainProcessor#test_zero_address_mint_unregistered_token_spam`; given a zero-address mint of a token NOT in the registry, expects `Reward`/`SubType.spam` + review whose reason names the unregistered mint (and does NOT contain "registered reward distributor")
- [x] `TestBerachainProcessor#test_zero_address_mint_empty_registry_spam`; given an empty registry, expects every zero-address mint to classify spam + review
- [x] `TestBerachainProcessor#test_zero_address_mint_native_token_spam`; given a zero-address mint whose `Leg.token_address` is `None`, expects spam + review (no address to be a registry member)
- [x] `TestBerachainProcessor#test_bridged_asset_membership_case_insensitive`; given the registry stores a lowercase address and the leg carries the checksummed form, expects bridge classification
- [x] `TestBerachainProcessor#test_sender_spam_reason_unchanged`; given a NON-zero-address reward from an unregistered sender, expects the existing sender-spam reason text unchanged (UL #91: each cause exercised)
- [x] `TestBridgedAssetRegistry` loader tests mirroring `tests/unit/infrastructure/test_position_token_registry.py` (mirror the GUARD cases only - missing/symlink/invalid-JSON/schema/oversize; fixtures use this plan's pinned `source`/`note` vocabulary, NOT C8's `provenance`/`label` keys; r9-F1): given a missing file, expects empty registry + WARNING naming the spam consequence; given a symlink, expects `FileProcessingError`; given invalid JSON, expects `FileProcessingError`; given a schema violation, expects `ConfigurationError`; given an oversize file, expects `FileProcessingError`
- [x] `TestOnChainThSubstitution#test_load_registries_resolves_bridged_assets`; given the example-template path resolution, expects `_load_registries` to return the bridged-asset registry alongside the existing three
- [x] Run → expect RED: `uv run pytest tests/unit/infrastructure/test_berachain_processor.py tests/unit/infrastructure/test_bridged_asset_registry.py tests/unit/application/test_on_chain_th_substitution.py -q`
- [x] Commit: `test(on-chain): bridged-asset registry gate RED`

### Task 2: GREEN; registry module, facade, wiring, gate

Files:
- `src/tax_reporting/infrastructure/on_chain/bridged_asset_registry.py` *(new)*
- `src/tax_reporting/application/on_chain_config.py`
- `src/tax_reporting/application/on_chain_th_substitution.py`
- `src/tax_reporting/infrastructure/on_chain/berachain_processor.py`
- `resources/source/example/2025/bera_bridged_assets.json` *(new, committed; created here so the Task 1 wiring test's example-fallback resolution has its file at the GREEN gate; r2-F2)*

- [x] Create `bridged_asset_registry.py` mirroring the position-token registry GUARD structure only (symlink/size/JSON guards, schema validation, missing → empty + actionable WARNING): `BridgedAssetRegistry` dataclass with `is_bridged_asset(address: str) -> bool` (case-normalized membership), `build_bridged_asset_registry(data, *, source)` with schema validation and provenance, `load_bridged_asset_registry(path)`. The JSON vocabulary is pinned and DELIBERATELY DIFFERS from C8's (r1-F4 one pinned vocabulary; r9-F1 anti-mirror note): registry-level `source` provenance string (NOT C8's `provenance`/`as_of_date`/`_comment`); entries form a JSON object keyed by the token address (lowercased), each value an object with an optional `note` string (NOT C8's `tokens` array of `{token_address, label, kind, provenance}`); no other keys validate
- [x] Add `load_bridged_asset_registry_for_year(year, override, repo_root)` to `on_chain_config.py` (filename literal `bera_bridged_assets.json` lives once, mirroring the position facade)
- [x] `OnChainThSubstituter.__init__` gains the `bridged_assets_path` override kwarg (tests inject the example path; same pattern as `position_tokens_path`); `_load_registries` loads and returns it (4-tuple); `_build_processor` passes `bridged_asset_registry=` to `BerachainProcessor`
- [x] `BerachainProcessor.__init__` gains `bridged_asset_registry: BridgedAssetRegistry | None = None` (None behaves as empty); `_reward_sub_type` zero-address branch consults membership → `bridge` for members, `spam` otherwise; `_reward_event` gains the mint-spam reason branch keyed on `SubType.spam` + `_is_zero_address(summed_leg.from_address)`
- [x] BEFORE the GREEN run, retrofit the inventoried existing bridge tests (r1-F1): construct the synthetic bridged-asset registry fixture and thread it through every inventoried site so registered-mint expectations stay `bridge` under the gate
- [x] Create the committed CANONICAL registry `resources/source/example/2025/bera_bridged_assets.json` with PUBLIC canonical token contracts only (the known bridged assets on Berachain as archived in the crypto-origin documents, e.g. bridged WBTC; derive the entries in-session from those documents and the 2025 baseline mint rows, per the automate-don't-ask rule); registry-level `source` provenance plus per-entry `note` naming the origin document; this file is production data, not a synthetic template; no personal wallets or tx hashes (r2-F2: created before the GREEN run so the Task 1 wiring test's example-fallback resolution has its file)
- [x] Constructor-signature-change audit: `grep -rn "BerachainProcessor(" src/ tests/`; every construction site listed; direct sites get the new kwarg only where a registry fixture is needed (default None keeps others compiling and behavior for non-mint paths identical)
- [x] Run → expect GREEN (Task 1 command)
- [x] Commit: `feat(on-chain): registry-gated bridge-mint classification (spam fallback)`

### Task 3: documentation + backlog promotion

Files:
- `docs/maintenance/on_chain_validation.md`
- `docs/history/backlog/2026-08-26-on-chain-review-followups.md`
- `docs/history/backlog/2026-08-18-koinly-cancellation-program.md`

- [x] Rewrite the discriminator-gap paragraph (`on_chain_validation.md:364-369`; r6-F1: spans :364-369; the opening phrase "Discriminator gap (review r1 F8)" is the authoritative locator); the registry gate is live; registered → Bridge, unregistered → spam + review; the P2 keying rule (Tag + review flag) unchanged. The rewrite must contain the literal phrase "bridged-asset registry" (the Validation Commands probe it; r6-F2)
- [x] Document the registry ownership contract in the same rewrite: the committed `resources/source/example/<year>/bera_bridged_assets.json` is the canonical curated public registry (provenance-cited); the gitignored `resources/source/<year>/bera_bridged_assets.json` is an OPTIONAL override that SHADOWS it, to be created only for entries not yet committed (never for publicly documented assets); per-year copies of the committed registry are a committed, reviewed act
- [x] Mark backlog item 3 promoted (link this plan); all three items now promoted → move the backlog doc to `docs/history/backlog/completed/`
- [x] Update the umbrella backlog P2-candidate line (line 201 area) for the bridge registry-gate mention
- [x] Commit: `docs(on-chain): bridge-asset registry gate; backlog complete`

### Task 4: full validation

- [x] Run the Validation Commands block end-to-end; all green
- [x] `uv run pytest -q` full suite green
- [x] Data-identity sweep across all test tiers (repo rule): `grep -rn "SubType.bridge" tests/`; every hit falls in one of three disposition categories: constructs a registry fixture, asserts a registered mint, or is a direct `Event` construction outside the processor (adapter/comparator/domain tests; unaffected by the gate; r3-F2); list each in the task log
