# Plan: Bera Unknown-family follow-ups (withdraw predicates, validation-CLI exit 2, CSV-path consolidation)

Source: `docs/history/backlog/2026-08-23-bera-unknown-followups.md` (review r3 F1/F4/F6 + r1 F8
deferred scope). Branch: `2026-08-18-on-chain-validation-harness` (user decision 2026-08-23;
follow-ups stay on the active feature branch).

## Terms

- **Shape 6**: the bidirectional vault-withdraw branch in
  `BerachainProcessor._classify_events` (`src/tax_reporting/infrastructure/on_chain/berachain_processor.py:428`),
  ordered before the deposit read (shape 7) and the Swap fallthrough (shape 8).
- **Member token**: a token address that is either an LP-snapshot member (via `LpAutodiscovery.is_lp_token`)
  or a position-token-registry member (via `PositionTokenRegistry.is_position_token`); see the
  existing `_is_member_token` helper (`berachain_processor.py:578`).
- **Redemption counterparty signal**: for an LP-snapshot member out-leg, the receive side matches
  the redemption expectation when at least one economic in-leg's `from_address` equals that
  out-leg's `to_address` (case-insensitive) - the vault/pair you sent the receipt token into is
  the address that sent the underlying back. For registry-only (LST) members this signal is NOT
  sufficient: an LST swapped on a DEX pair (out: LST to the pair, in: asset from the pair)
  satisfies it while being a disposal. Registry-only members therefore use a **vault-target
  discriminator** instead: they classify `LiquidityWithdraw` only when the member out-leg's
  `to_address` is a registry vault (`PositionTokenRegistry.is_position_vault`,
  `kind="position_nft"`); any other recipient falls through to the pre-existing `Swap` shape.
  The 2025 LBGT exchange family (`resources/source/2025/bera_position_tokens.json`, 8 txs)
  documents exactly this: its provenance states the registry entry is identity data, NOT a
  per-cluster rule, and bidirectional exchanges classify via the existing Swap shape.
- **EXIT_VALIDATION_FAILED (1)** (defined in `on_chain_validation/runner.py:106`) /
  **EXIT_VALIDATION_INCOMPLETE (3)** / **EXIT_VALIDATION_PASSED (0)** (defined in
  `src/tax_reporting/application/on_chain_validation/dispositions.py:48-52`): documented exit
  codes and the exit table in `docs/maintenance/on_chain_validation.md`.
- **Review surface (on-chain path)**: `Event` (`domain/on_chain_transaction.py:152-168`) has NO
  review field; review is expressed via the `_event(..., review=True)` WARNING log
  (`berachain_processor.py:997` def, warning at `1016-1023`). Tests assert review via `caplog`
  at WARNING level, not via an Event attribute.
- **`bera_csv_path`**: the helper producing `output_dir / str(year) / "bera_transactions.csv"`.

## Gist & Examples

**What changes:** Three small, independent fixes carried over from the Unknown-family review.
(1) The bidirectional withdraw rule no longer fires silently for every send of an LP/position
token: it classifies `LiquidityWithdraw` but flags the event for manual review when the receive
side does not look like a redemption, and it now also covers position-registry (LST) tokens, not
just LP-snapshot members. (2) The `--validate-on-chain-th` CLI path wraps unexpected crashes in a
friendly error and exits with a NEW code 2, so a crash no longer masquerades as the documented
exit-1 "misconfigured run" status. (3) The `bera_transactions.csv` path helper is consolidated to
one definition in its producing module.

**Why needed:** A market SALE of an LP-member token (out: LP receipt, in: unrelated DEX asset)
currently classifies silently as `LiquidityWithdraw` instead of a disposal - tax treatment differs,
so this needs a review flag, not a silent widening (review r3 F1). LST unstakes fall through to
`Swap` because the withdraw gate consults only the LP snapshot (r1 F8 deferred scope). Reachable
malformed inputs in the validation CLI surface as raw tracebacks that exit 1, colliding with the
exit code acceptance scripts key on (r3 F4). Three modules each hardcode the export CSV path (r3 F6).

**Example input (LP-token sale, the r3 F1 RED case):** bidirectional tx, out-leg 5 KODIAX (an
LP-snapshot member) to a DEX buyer, in-leg 2 BERA from the router address. The in-leg sender
(router) differs from the member out-leg recipient (buyer), so no redemption counterparty match.

**Example output:** one `Event(LiquidityWithdraw, sub_type=internal_transfer)` whose
classification emits a review WARNING naming the tx hash, the mismatched counterparty, and the
actionable reason (possible disposal, not a redemption) - NOT a clean withdraw and NOT a silent
`Swap`. The `Event` dataclass carries no review field (log-based review surface; see Terms).

**Example (genuine unstake, unchanged):** out-leg receipt token to the vault address, in-leg
underlying tokens `from_address` = the same vault address → `LiquidityWithdraw` with no review
warning (existing behavior, pinned by characterization tests).

**Example (LST DEX swap, stays Swap - r2 F1):** bidirectional exchange of an LST on its DEX pair
(out: LST to the pair contract, in: BERA from the pair). The vault-target discriminator rejects
the pair as a registry vault, so the tx falls through to the pre-existing `Swap` shape - the
2025 LBGT exchange family must not regress from `Swap` to `LiquidityWithdraw`.

**Edge cases handled:**
- Registry-only (LST) member unstake via the registry vault: same counterparty match → clean
  `LiquidityWithdraw` (previously `Swap`).
- LST member sent to a non-vault, non-pair counterparty: falls through to the pre-existing
  `Swap` shape (the registry-only branch fires only on a vault target); only LP-snapshot members
  with a non-redemption receive side get `LiquidityWithdraw` + review warning.
- Vaults that emit the underlying from a different address than the deposit target: flagged for
  review (safe direction - review, never silent misclassification).
- Native-asset legs (`token_address is None`) are never member tokens (existing invariant).
- Validation-CLI paths that raise `ConfigurationError` / `MissingDecisionPointsError` keep their
  current semantics; only UNEXPECTED exceptions map to exit 2.

## Design Invariants (CR Guard)

1. **Address-keyed identity**: membership and counterparty comparisons use lower-cased token and
   leg addresses, never asset names/tickers.
2. **Existing clean withdraws must not regress**: any 2025-baseline tx that classifies
   `LiquidityWithdraw` without a review warning today keeps exactly that classification; the
   review warning is ADDED only for non-redemption receive sides. The 2025 LBGT exchange family
   keeps its `Swap` classification. Characterization tests pin both.
3. **Exit-code contract**: 0 = passed, 1 = misconfigured run (per the `on_chain_validation.md`
   exit table), 3 = incomplete. New code 2 = unexpected crash only. Acceptance scripts keying on
   exit 1 must remain able to distinguish misconfiguration from a crash.
4. **Koinly-byte-identical invariants** of the on-chain TH path are untouched: the substitution
   bridge and comparator are not modified.
5. **Review warnings carry specific reasons** (UL: review_reason must be actionable); the WARNING
   names the tx hash, the event type, AND the discriminating reason (mismatched counterparty
   address, possible disposal). The generic "uncertain classification - investigate" message alone
   is insufficient for the new shape-6 cases; `_event` gains an optional reason parameter appended
   to the existing WARNING (log-based review surface - `Event` itself gains NO new field).
6. **Single owner for the CSV path**: after consolidation, exactly one module
  (`on_chain_fetcher.py`) defines the filename; other modules import the helper. The path VALUE
  (`output_dir / str(year) / "bera_transactions.csv"`) is byte-identical.

## Evaluation Criteria

**Quality dimensions:**
- Correctness: RED→GREEN per fix; each discriminating test fails under the pre-fix code (the
  sale case asserts review=True, which the current code cannot emit at shape 6).
- Safety: no silent data-loss or silent misclassification; non-redemption withdrawals are
  review-flagged with specific reasons, never dropped.
- Maintainability: one CSV-path definition; zero stale references after the move (grep-swept).
- Test coverage: negative paths (crash → exit 2; sale → review flag; LST sale → review flag) and
  backward-compat (clean withdraw stays unflagged; validation exit codes 0/1/3 passthrough intact).

**Done when:**
- `uv run pytest` green (full 3-tier suite).
- `docs/maintenance/on_chain_validation.md` exit table documents code 2.
- `docs/maintenance/glossary.md` LST-withdraw entry matches the unified behavior.
- Backlog file `docs/history/backlog/2026-08-23-bera-unknown-followups.md` moved to
  `docs/history/backlog/completed/` at plan completion.

**Ship when:** none - repository-local work only.

## Review Scope

**Explicit must-fix**; findings on these paths are always in scope (review and fix if valid):

**Production code:**
- `src/tax_reporting/infrastructure/on_chain/berachain_processor.py` (shape-6 branch and its
  helpers only: the shape-6 gate in `_classify_events`, `_sends_lp_token`/`_is_member_token`,
  the new redemption-counterparty logic, and the module-level `_event` helper's optional
  `reason` parameter; all other functions and methods in this file are frozen; reject findings
  touching them)
- `src/tax_reporting/main.py` (validation dispatch in `cli()` and `_run_validation_from_cli` only)
- `src/tax_reporting/application/on_chain_validation/dispositions.py` (exit-code constants block)
- `src/tax_reporting/application/on_chain_fetcher.py` *(gains `bera_csv_path`)*
- `src/tax_reporting/application/on_chain_th_substitution.py` *(loses the definition, gains import)*
- `src/tax_reporting/application/on_chain_validation/runner.py` *(loses `_BERA_CSV_FILENAME`)*

**Tests:**
- `tests/unit/infrastructure/test_berachain_processor.py`
- `tests/unit/test_cli.py` (owns CLI dispatch tests; already carries `run_validation` patch
  patterns and exit-1 passthrough cases)
- `tests/unit/application/test_on_chain_fetcher.py` *(new path-helper tests, if a suite exists there; else nearest fetcher test module)*

**Plan-related extension**; implementation and review may change files not listed above. Treat a
finding as in scope when it is **causally related to this plan**: it implements or completes a plan
task, fixes a regression introduced by plan work, closes wiring or docs implied by an explicit
must-fix change, or contradicts a contract the plan changed. If the link to the plan is weak or
speculative, drop as out of scope with a one-line reason.

**Documentation:** production code and tests use the explicit list. Docs may also be in scope
under plan-related extension when a change is substantively required to keep docs aligned
(`docs/maintenance/on_chain_validation.md`, `docs/maintenance/glossary.md`, module docstrings);
doc-closure includes grep for stale phrases, not only pre-listed paths.

**Out of scope; reject unless plan-related:**
- Module-size extraction of `berachain_processor.py` / `on_chain_th_substitution.py` (KNOWN DEBT,
  tracked in module docstrings).
- The identity-dedup half of `_drain_boundary_block` (documented in its docstring +
  `development_lessons.md` #138).

## Validation Commands

```bash
uv run pytest tests/unit/infrastructure/test_berachain_processor.py tests/unit/test_cli.py -q

# Exit-code contract: 0/1/3 constants unchanged, new 2 present, doc table updated (per-file gates)
for f in src/tax_reporting/application/on_chain_validation/dispositions.py; do
  grep -n "EXIT_VALIDATION_PASSED: Final\[int\] = 0" "$f" || { echo "missing EXIT 0 in $f"; exit 1; }
  grep -n "EXIT_VALIDATION_INCOMPLETE: Final\[int\] = 3" "$f" || { echo "missing EXIT 3 in $f"; exit 1; }
  grep -n "EXIT_VALIDATION_CRASH: Final\[int\] = 2" "$f" || { echo "missing EXIT 2 in $f"; exit 1; }
done
grep -n "EXIT_VALIDATION_FAILED: Final\[int\] = 1" src/tax_reporting/application/on_chain_validation/runner.py || { echo "EXIT 1 moved or removed from runner.py"; exit 1; }
grep -n "| 2 |" docs/maintenance/on_chain_validation.md || { echo "exit-2 row missing from doc table"; exit 1; }
# Doc must NOT claim a crash reports exit 1 (negated sweep)
if grep -nEi "crash|traceback" docs/maintenance/on_chain_validation.md | grep -i "exit 1"; then
  echo "doc still maps crashes to exit 1"; exit 1
fi

# CSV-path consolidation: single helper in the fetcher; NO path constants or
# path-construction idiom left in the other two modules. The fetcher KEEPS
# `_CSV_FILENAME` (the one literal, used only inside bera_csv_path).
test -f src/tax_reporting/application/on_chain_fetcher.py || exit 1
grep -n "^def bera_csv_path" src/tax_reporting/application/on_chain_fetcher.py || { echo "helper not exported from fetcher"; exit 1; }
grep -n "_CSV_FILENAME.*=.*\"bera_transactions[.]csv\"" src/tax_reporting/application/on_chain_fetcher.py || { echo "single filename constant missing from fetcher"; exit 1; }
for f in src/tax_reporting/application/on_chain_validation/runner.py \
         src/tax_reporting/application/on_chain_th_substitution.py; do
  test -f "$f" || { echo "missing $f"; exit 1; }
  if grep -nE "_CSV_FILENAME|_BERA_CSV_FILENAME" "$f"; then echo "stale path constant in $f"; exit 1; fi
  if grep -nE 'str\(year\) / (_CSV_FILENAME|_BERA_CSV_FILENAME|"bera_transactions[.]csv")' "$f"; then echo "bera-CSV path construction outside the single helper in $f"; exit 1; fi
done

# Full suite
uv run pytest
```

Note: the `[.]` escapes in the last sweep are intentional (self-match immunity for this plan
document); do not "normalize" them, and exclude this plan file from any sweep instructions.

### Task 1: Shape 6 - member-token gate, LST unification, redemption-counterparty review flag

Files:
- `src/tax_reporting/infrastructure/on_chain/berachain_processor.py`
- `tests/unit/infrastructure/test_berachain_processor.py`
- `docs/maintenance/glossary.md`

- [x] `TestBerachainProcessor#test_lp_token_sale_review_flagged`; given a bidirectional tx whose out-leg sends an LP-snapshot member (KODIAX-style receipt) to a buyer while the in-leg BERA comes `from_address` a DIFFERENT address (DEX router), expects one `Event(LiquidityWithdraw, internal_transfer)` and a `caplog` WARNING (at WARNING level) naming the tx hash, the mismatched counterparty address, and a disposal-specific reason (RED: current code emits no review warning at shape 6)
- [x] `TestBerachainProcessor#test_vault_unstake_counterparty_match_clean`; given a bidirectional tx whose member-token out-leg recipient equals an in-leg's `from_address` (vault unstake), expects `LiquidityWithdraw` and NO review warning in `caplog` (characterization: pins existing clean-withdraw behavior)
- [x] `TestBerachainProcessor#test_lst_unstake_classifies_liquidity_withdraw`; given a bidirectional tx whose out-leg sends a position-registry-only member (LST, `kind="lst"`) to the registry vault (`kind="position_nft"` address) with underlying in-legs from the same vault, expects `LiquidityWithdraw` (RED: current LP-snapshot-only gate falls through to `Swap`)
- [x] `TestBerachainProcessor#test_lst_dex_swap_stays_swap`; given a bidirectional exchange of an LST on a DEX pair (out-leg LST `to_address` = pair contract, in-leg BERA `from_address` = the SAME pair - counterparty match holds but the recipient is not a registry vault), expects the pre-existing `Swap` classification, NOT `LiquidityWithdraw` (RED vs the counterparty-match-only design; pins the LBGT provenance rule that registry entries are identity data, not per-cluster rules)
- [x] `TestBerachainProcessor#test_lst_send_to_nonvault_recipient_falls_through`; given an LST member out-leg to a non-vault, non-pair recipient with an unrelated in-leg (counterparties differ), expects `Swap` - the registry-only gate does not fire outside the vault target, and no shape-6 review warning is emitted (the review path is LP-snapshot-only)
- [x] `TestBerachainProcessor#test_native_leg_never_member`; given a bidirectional tx with a native-asset out-leg (`token_address is None`) and unrelated in-leg, expects the pre-existing `Swap` classification (address-keyed identity invariant, no regression)
- [x] Run → expect RED: `uv run pytest tests/unit/infrastructure/test_berachain_processor.py -q`
- [x] GREEN: split the shape-6 gate by member source - (a) LP-snapshot member out-leg (`lp_autodiscovery.is_lp_token(...).is_lp`, iterated over ALL out-legs via `any(...)` exactly like today's `_sends_lp_token`): fire `LiquidityWithdraw`; clean only when the redemption-counterparty predicate holds (some economic in-leg's `from_address` equals the member out-leg's `to_address`, case-insensitive), otherwise `_event(..., review=True, reason=...)`; (b) registry-only member out-leg: fire `LiquidityWithdraw` ONLY when that out-leg's `to_address` is a registry vault (`position_token_registry.is_position_vault`, registry present), otherwise fall through to the pre-existing `Swap` shape. Extend the `_event` helper with an optional `reason: str | None = None` parameter appended to the existing review WARNING (no `Event` field added); delete `_sends_lp_token` if no other caller remains (grep first)
- [x] Update the module docstring classification table (`berachain_processor.py:32-38`) and `docs/maintenance/glossary.md`: registry-vault LST unstakes classify `LiquidityWithdraw` (vault-target gated); LP-member sends with non-redemption receive sides classify `LiquidityWithdraw` with a review warning; LST exchanges outside the vault target stay `Swap`
- [x] Run → expect GREEN
- [x] Commit: `fix(on-chain): shape-6 member-token gate with redemption-counterparty review flag (r3 F1 + r1 F8)`

### Task 2: Validation-CLI crash wrapper and EXIT_VALIDATION_CRASH=2

Files:
- `src/tax_reporting/application/on_chain_validation/dispositions.py`
- `src/tax_reporting/application/on_chain_validation/runner.py` (docstring exit-code list)
- `src/tax_reporting/main.py`
- `tests/unit/test_cli.py` (existing classes there are `TestValidateWalletPrecedence`/`TestCliMain`/`TestMainWithMissingConfig`; CREATE a new `TestCli` class for these cases or add them to `TestCliMain` - follow the file's existing patch idioms for `run_validation`)
- `docs/maintenance/on_chain_validation.md`

Tests below cite `TestCli`; use the class name actually created.

- [x] `TestCli#test_validation_crash_exits_2`; given `--validate-on-chain-th` args and a `run_validation` monkeypatched to raise `RuntimeError`, expects `SystemExit` with code 2 and a friendly one-line printed message (no BARE unhandled traceback propagating out of `cli()`; the detail goes through `logger.exception` into the logging surface) plus a `logger.exception` record (RED: today the traceback propagates and the process exits 1)
- [x] `TestCli#test_validation_exit_codes_passthrough`; given `run_validation` returning 0, 1, and 3 (parametrized), expects `sys.exit` receives the value unchanged (backward compat; exit 1 stays misconfiguration-only)
- [x] `TestCli#test_validation_config_error_not_swallowed`; given `_run_validation_from_cli` monkeypatched to raise `ConfigurationError` (and a second parametrized case for `MissingDecisionPointsError`), expects `pytest.raises(ConfigurationError, match=...)` / `pytest.raises(MissingDecisionPointsError, match=...)` catches the SAME exception type propagating out of `cli()` (NOT converted to `SystemExit(2)` and NOT swallowed into a friendly message)
- [x] Run → expect RED: `uv run pytest tests/unit/test_cli.py -q`
- [x] GREEN: add `EXIT_VALIDATION_CRASH: Final[int] = 2` to the constants block in `dispositions.py` and add it to the module's `__all__`; update the docstring exit-code lists in `dispositions.py` and in `runner.py`'s module docstring (currently 0/1/3); wrap the `_run_validation_from_cli(args)` call site in `cli()` (`main.py:321`) mirroring the report path's wrapper: catch `Exception`, `logger.exception`, print friendly message, `sys.exit(EXIT_VALIDATION_CRASH)`; re-raise `ConfigurationError`/`MissingDecisionPointsError` untouched before the generic catch
- [x] Add the `| 2 | Unexpected crash...` row to the exit table in `docs/maintenance/on_chain_validation.md` and state that acceptance scripts can distinguish a crash (code 2) from a misconfigured run (code 1). Word the new prose so no line containing "crash"/"traceback" also contains the literal "exit 1" (the Validation Commands sweep forbids that combination; "(code 1)" parenthetical style is safe)
- [x] Run → expect GREEN
- [x] Commit: `fix(on-chain): validation-CLI crashes exit 2 with friendly error (r3 F4)`

### Task 3: Consolidate bera_csv_path into on_chain_fetcher.py

Files:
- `src/tax_reporting/application/on_chain_fetcher.py`
- `src/tax_reporting/application/on_chain_th_substitution.py`
- `src/tax_reporting/application/on_chain_validation/runner.py`

Pure refactor (no behavior change) - characterization items only where no existing coverage pins
the path value:

- [x] `tests/unit/application/test_on_chain_fetcher.py` (or nearest existing fetcher suite); given `output_dir` and `year`, expects `bera_csv_path` returns `output_dir / str(year) / "bera_transactions.csv"` (characterization: run GREEN before the move; add only if no existing test pins this)
- [x] Run → expect GREEN (characterization: captures existing behavior before refactor)
- [x] Move `bera_csv_path` to `on_chain_fetcher.py` (the CSV's producer), built on its existing `_CSV_FILENAME` constant - the fetcher KEEPS that constant as the single filename literal; in `on_chain_th_substitution.py` and `on_chain_validation/runner.py`, import the helper, delete `_BERA_CSV_FILENAME` (runner), remove the now-dead local definition (substitution), and update the docstring path mentions (`on_chain_fetcher.py:13`, `on_chain_th_substitution.py:305,376`) to reference the helper; keep the path VALUE byte-identical; verify no circular import (`on_chain_fetcher.py` must not import `on_chain_th_substitution`)
- [x] Symbol-move audit: grep `tests/` for `monkeypatch.setattr` and string-form `patch` on `bera_csv_path`, `_CSV_FILENAME`, `_BERA_CSV_FILENAME` (already verified empty at plan time; re-run and retarget any site found)
- [x] Run the Validation Commands consolidation block → all gates pass
- [x] Commit: `refactor(on-chain): single bera_csv_path owner in on_chain_fetcher (r3 F6)`

### Task 4: Final validation and backlog closure

Files:
- `docs/history/backlog/2026-08-23-bera-unknown-followups.md`

- [x] Run the full `## Validation Commands` block → all pass, `uv run pytest` green
- [x] Move the backlog file to `docs/history/backlog/completed/` (its stated workflow)
- [x] Commit: `docs: archive bera-unknown-followups backlog (plan executed)`
