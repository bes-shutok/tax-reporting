# Backlog: Unknown-family classifier follow-ups (withdraw predicates, validation-CLI exits, path consolidation)

Status: backlog idea (pre-plan; promote via the `plans` skill when scheduled).
Workflow: when the implementing plan completes, move this file to `docs/history/backlog/completed/`.

Source: review r3 (2026-08-23) of branch `2026-08-22-bera-unknown-classifier-rules`
(`docs/history/reviews/2026-08-23-2026-08-22-bera-unknown-classifier-rules-code-review-r3.md`),
plus the r1 F8 deferred scope. The r3 quick wins (F2/F3/F5 tests, F7/F8 doc fixes) were
fixed directly on the branch; this file holds the items that need their own planned change.

## 1. Bidirectional withdraw predicates are one-sided (r3 F1 + r1 F8 deferred scope)

Two adjacent asymmetries in `_classify_events` shape 6 (bidirectional vault-withdraw
rule, `berachain_processor.py`):

- **r3 F1 (Medium)**: shape 6 fires `LiquidityWithdraw` for ANY bidirectional tx where
  some economic out-leg token is an LP-snapshot member - the receive side is
  unconstrained and there is no review flag. A market SALE of an LP-member token
  (out: LP, in: unrelated DEX asset) therefore classifies silently as
  `LiquidityWithdraw` instead of `Swap`. Not present in the 2025 baseline, but
  structurally reachable.
- **r1 F8 deferred scope**: the withdraw gate consults the LP snapshot only; a
  bidirectional send of a position-registry-only member (LST) has NO withdraw rule and
  falls through to `Swap`. The glossary was corrected to state the current behavior;
  whether LST unstakes SHOULD classify as `LiquidityWithdraw` is an open design
  question.

A single follow-up plan should decide both receive-side and LST semantics together
(suggested direction from the review: gate on a receive-side redemption signal, or add
`review=True` when the receive side does not match a redemption expectation; a test
pinning the LP-token sale shape - in-leg BERA from a DEX router, out-leg a KODI
member - is the RED case). Tax treatment differs between `Swap` and
`LiquidityWithdraw`, so this needs a decision, not a silent widening.

## 2. Validation-CLI uncaught exceptions collide with the exit-1 contract (r3 F4)

`--validate-on-chain-th` reachable malformed inputs (invalid registry `kind`,
missing `chains.json` with `ON_CHAIN_TH_WALLETS` set, malformed Koinly cell) surface
as raw tracebacks with exit 1, which collides with the documented
EXIT_VALIDATION_FAILED=1 misconfiguration status that acceptance scripts key on. The
report path wraps its dispatch in a SharesReportingError/Exception catch layer; the
validation path bypasses it. Fix: wrap the `_run_validation_from_cli` dispatch the
same way (friendly error + `logger.exception`), and consider a distinct exit code
(e.g. 2) for crash-vs-misconfiguration so acceptance scripts can distinguish.

## 3. `bera_csv_path` consolidated only 2 of 5 construction sites (r3 F6)

The export-path helper lives in `on_chain_th_substitution.py` but two private
constants remain (in the fetcher and the runner); a layout-convention change still
requires editing three constants in three modules. Fix: export `bera_csv_path` from
`on_chain_fetcher.py` (the file's producer), delete the runner's and substitution's
private constants, and import the one helper everywhere. Pure refactor.

## Also-rans recorded elsewhere

- Module-size extractions (`berachain_processor.py` over the 1,000-line limit,
  `on_chain_th_substitution.py` near it) are already marked KNOWN DEBT in module
  docstrings (r1 F5) and are not re-tracked here.
- The r1 F9 identity-dedup half of the boundary drain stays documented in the
  `_drain_boundary_block` docstring + `development_lessons.md` #138; any retry must
  first give the synthetic test rows real per-row identity fields.
