# Plan: Payment-proceeds refactor - share guarded JSON loader + split sanitizer (DP-014 review #6, #12)

Options record: `docs/history/feature-notes/2026-06-20-crypto-payment-proceeds-refactor-options.md`
Review source: findings #6, #12 in `docs/history/reviews/2026-06-20-branch-review-doc-hierarchy-migration.md`
Plan review: r4 confirmation (`docs/history/reviews/2026-06-21-plan-review-crypto-payment-proceeds-refactor-r4.md`, 0 Blocker / 0 Medium / 0 Low / 1 Monitor - r3 amendments verified, ready) · r3 full panel (`…-r3.md`, 0 Blocker / 1 Medium / 5 Low / 5 Monitor - all incorporated) · r2 (`…-r2.md`, inline spot-check, 0/0) · r1 (`…-r1.md`, full panel, 0 Blocker / 7 Medium, all incorporated).
Language testing guide: `docs/maintenance/development_lessons.md` (#91 extracted-helper tests, #105 reuse-pattern recalibration).

## Terms

- **DP-014** - the payment-proceeds correction feature (`application/crypto/payment_proceeds.py`) whose review surfaced this refactor.
- **Guarded JSON reader** - a shared helper that performs symlink rejection, a size cap, and `json.load`; the security-load discipline centralized by Finding #6.
- **on_error policy** - the caller-supplied callback `(path, kind, detail) -> object` that decides degrade-vs-raise per failure, so the three callers keep their deliberately different policies (lesson #105).
- **DEGRADED** - a single shared sentinel (`object()`) exported from `json_loader.py` that an `on_error` returns to signal "degrade"; distinct from a legitimately-parsed JSON `null` so callers' shape checks still reject a `null` file.
- **Excel sigil defusal** - the `= + - @` leading-prefix neutralization that exists only because of Excel; stays in `persisting/excel_utils.py`.

## Gist & Examples

Two independent pure-structure refactors (zero behavior change, including log/error message wording the existing tests pin), each taking the "share/split" Option B from the options record instead of the narrower "move" Option A. Both pay off the duplication the DP-014 work exposed inside `application/crypto/`.

**Finding #6 - the secure-load discipline for JSON config is copy-pasted three ways.** Three modules each reinvent symlink rejection + 1 MiB size cap + `json.load` over (different) JSON config files:

- `classification._load_popular_crypto_tokens` (reads `popular_crypto_tokens.json`; raises on symlink/oversize/bad-shape, degrades on missing/parse)
- `derivatives_dedup._load_derivatives_labels_config_from_path` (reads `derivatives_labels/<provider>_<year>.json`; raises on everything except missing-file, because a silent skip would leave derivatives P&L double-counted)
- `payment_proceeds._load_payment_proceeds_config_from_path` (reads `popular_crypto_tokens.json`; degrades on everything, so a corrupt token file never aborts report generation)

The guards are extracted into one helper `load_guarded_json(path, *, size_limit, on_error)` in `infrastructure/json_loader.py`. The helper owns the mechanical guards + `json.load`; each caller keeps its return shape, its schema validation, and - via the `on_error` callback - its degrade-vs-raise policy AND its existing message wording. Example:

```python
# Before (payment_proceeds): ~40 inline lines re-implementing symlink/size/json guards
# After:
data = load_guarded_json(path, size_limit=_MAX_TOKEN_FILE_SIZE, on_error=_on_error)
if data is DEGRADED:
    return _default_config()
# ...caller-owned schema validation unchanged
```

**Finding #12 - `safe_cell_value` is a layer leak when used as a sanitizer.** `payment_proceeds._sanitize_substring` imports `safe_cell_value` from the presentation sub-package (`persisting/excel_utils.py`) but only needs the control-char strip, not the Excel formula-sigil defusal. The function splits cleanly:

- `strip_control_chars(value)` - neutral, layer-agnostic - new `infrastructure/text_sanitize.py`
- Excel sigil defusal stays in `persisting/excel_utils.py`; `safe_cell_value` becomes "defuse after strip" (public name + behavior unchanged for all ~10 persisting callers)
- `payment_proceeds._sanitize_substring` calls `strip_control_chars` directly; the cross-layer import is removed

## Evaluation Criteria

**Quality dimensions:**

- **Behavior preservation (primary), messages included:** every existing test in `test_excel_utils.py`, `test_payment_proceeds.py`, `test_derivatives_dedup.py`, and `test_crypto_classification.py` stays GREEN unchanged; these are the characterization net. The three loaders' degrade-vs-raise semantics AND their log/error wording are preserved - in particular the parametrized `test_malformed_or_oversize_or_symlink_degrades` still finds "invalid JSON" / "exceeds size limit" / "symlink" in the warnings, `derivatives_dedup` still raises on bad JSON (double-counting hazard) and stays silent on missing, and `payment_proceeds` still degrades on all failures.
- **Direct helper coverage:** `load_guarded_json` and `strip_control_chars` each get direct unit tests (lesson #91). `load_guarded_json` tests cover all five failure kinds, the `on_error` raise-vs-return contract, the `DEGRADED`-vs-`null` distinction, the closed set of `kind` tokens, and the `size_limit` boundary (exactly-at-limit passes, limit+1 fails).
- **No duplication:** after the refactor, grepping for the inline guard idiom (`is_symlink()` / `stat().st_size`) inside `application/crypto/` returns nothing - the discipline lives once in `infrastructure/json_loader.py`.
- **No layer leak:** `grep "safe_cell_value" src/tax_reporting/application/crypto/` returns nothing; `payment_proceeds` no longer imports from `persisting/`.
- **Maintainability:** each crypto module shrinks by its inline guard block; no module crosses the repo's size ceilings; no stale "mirrors classification" docstrings remain.

**Release gates:**

- `uv run pytest` full suite GREEN.
- `uv run ruff check src/ tests/` clean - including no unused `# noqa` (RUF100) on the refactored loaders.
- No new public API surface in the crypto modules (the helper/util are internal).
- Options record flipped to IMPLEMENTED.

## Review Scope

**Explicit must-fix** - findings on these paths are always in scope (review and fix if valid):

**Production code:**
- `src/tax_reporting/infrastructure/text_sanitize.py` *(new)*
- `src/tax_reporting/infrastructure/json_loader.py` *(new)*
- `src/tax_reporting/application/persisting/excel_utils.py`
- `src/tax_reporting/application/crypto/payment_proceeds.py`
- `src/tax_reporting/application/crypto/classification.py`
- `src/tax_reporting/application/crypto/derivatives_dedup.py`

**Tests:**
- `tests/unit/infrastructure/test_text_sanitize.py` *(new)*
- `tests/unit/infrastructure/test_json_loader.py` *(new)*
- `tests/unit/application/persisting/test_excel_utils.py`
- `tests/unit/application/test_payment_proceeds.py`
- `tests/unit/application/test_derivatives_dedup.py`
- `tests/unit/application/test_crypto_classification.py`

**Plan-related extension** - implementation/review may also touch:

- `docs/maintenance/development_lessons.md` - add (unconditional) a one-line cross-reference under lesson #105 pointing to `infrastructure/json_loader.py` as the canonical in-repo example of "inherit the guards, recalibrate exception handling."
- `docs/maintenance/crypto_implementation_guidelines.md` - grep for stale "mirrors classification._load_popular_crypto_tokens" / inline-guard references (r1 flagged lines ~1110-1117 and ~1496-1509) and repoint them to the shared loader.
- `docs/history/feature-notes/2026-06-20-crypto-payment-proceeds-refactor-options.md` - flip Status DEFERRED → IMPLEMENTED with the Task 2/5/6/8 commit refs.

**Out of scope - reject unless plan-related:**
- `src/tax_reporting/application/persisting/{assumptions_sheet,crypto_gains_sheet,crypto_supplementary_sheet,derivatives_sheet,ib_sheet,loan_activity_sheet}.py` - they call `safe_cell_value` unchanged (public behavior preserved); review only if a finding shows the split altered their output.
- `src/tax_reporting/application/crypto_reporting.py` - re-exports `_load_popular_crypto_tokens` (`F401` noqa); review only if the symbol import stops resolving.

## Design Invariants (CR Guard)

1. **Zero behavior change, messages included.** Pure-structure refactor. The three loaders' observable behavior (return values, exception types, warning log text, and which failure raises vs degrades) is identical before and after. The characterization tests are the contract. Each caller's `on_error` reproduces its existing message wording (or a message containing the same key phrase + path), so no existing assertion needs to change.
2. **`derivatives_dedup` MUST raise `FileProcessingError`** on `symlink`/`oversize`/`stat_error`/`invalid_json`/bad-shape. Silent degradation here leaves derivatives P&L double-counted (its module docstring calls this a correctness hazard). Its `on_error` returns `DEGRADED` ONLY for `kind == "missing"` (and stays silent - no loader-level log - so `test_missing_file_returns_empty_silently` holds); it raises for every other kind.
3. **`payment_proceeds` MUST keep degrading on every failure** (warn + `_default_config()`); a corrupt token file never aborts report generation. Its warnings still contain "invalid JSON" / "exceeds size limit" / "symlink" (the parametrized test's substrings) and the path.
4. **`classification` keeps its mixed policy:** raise on `symlink`/`oversize`/bad-shape; degrade (warn + empty frozenset) on `missing`/`stat_error`/`invalid_json`. Its `on_error` branches on the `kind` token. A parsed JSON `null` is NOT a degrade - it flows to the not-a-dict shape check and raises (this is why the sentinel is a dedicated object, not `None`).
5. **`safe_cell_value` public contract unchanged.** All ~10 `persisting/` callers keep calling `safe_cell_value(value)` with byte-identical output; only its internal composition changes (strip then defuse). The Excel sigil defusal never leaves `persisting/`.
6. **The `on_error` callback is the only policy seam; `DEGRADED` is the only degrade signal.** `load_guarded_json` itself never decides degrade-vs-raise and never logs; it calls `on_error(path, kind, detail)` and returns the handler's result (or propagates its raise). `kind` is a stable token from the closed set `{"symlink","missing","oversize","stat_error","invalid_json"}`; `on_error` returns the exported `DEGRADED` sentinel to degrade. `load_guarded_json` exports `DEGRADED` so a parsed `null` is never conflated with a degrade.
7. **Shape validation stays caller-owned.** The helper stops at `json.load`; each caller validates its own schema (`tokens.stablecoins`/`stablecoin_pegs`/`payment_tags` for payment; `derivatives_th_labels` for derivatives; `tokens` for classification).
8. **Symlink is checked before existence** inside the helper, preserving the current ordering (a dangling symlink reports as symlink, not missing) for all three callers. Size check is strict `> size_limit` (exactly `size_limit` passes).

## Monitor

- **TOCTOU between `is_symlink()` and `open()`** (pre-existing in all three loaders, not introduced here). Centralizing the read into one helper is the prerequisite for a future atomic open+stat+fstat fix. Owner: a future hardening task under `application/crypto/` - out of scope for this refactor; no behavior change either way.
- **Path/exception-text embedded in WARNING `detail`** (pre-existing). Centralization does not regress it. Owner: same future hardening task if warning-detail scrubbing is ever required.
- **`DEGRADED` sentinel is heavier than two of three callers need** (accepted design choice). It exists only to defend classification's `null`-file raise; payment_proceeds and derivatives never parse `null` as a degrade, so for them a direct degrade-value return would be equivalent. Documented (Terms); revisit only if a fourth caller appears that also needs the `null` distinction. Owner: this plan (accepted); no action.
- **`_sanitize_substring` redirect removes the only mechanism that could defuse a leading formula sigil in a FUTURE reason builder.** Every current reason builder interpolates the asset/peg mid-prose, so a leading sigil never reaches cell position 0 today and `test_formula_injection_in_review_reasons_neutralized` stays GREEN (verified). If a future reason builder interpolates the asset at position 0, add a RED `test_sanitize_substring_defuses_leading_sigil` to Task 2 first. Owner: future reason-builder work; backstop is the existing characterization test.
- **Task 8 `AttributeError`-arm drop is safe, but its proof is slightly overstated.** Task 7's `test_tokens_value_not_dict_raises` exercises the `isinstance(tokens_obj, dict)` raise, not the dropped `AttributeError` arm specifically. The arm is genuinely unreachable post-refactor (all shape access is `isinstance`/`in`-based on a dict); the one-line code comment in Task 8 is sufficient. Owner: this plan (accepted); no action.

## Validation Commands

```bash
# Direct helper coverage (new)
uv run pytest tests/unit/infrastructure/test_text_sanitize.py tests/unit/infrastructure/test_json_loader.py -v

# Characterization nets stay GREEN
uv run pytest tests/unit/application/persisting/test_excel_utils.py \
  tests/unit/application/test_payment_proceeds.py \
  tests/unit/application/test_derivatives_dedup.py \
  tests/unit/application/test_crypto_classification.py -v

# Full suite + lint (RUF100 catches any unused # noqa left on the refactored loaders)
uv run pytest
uv run ruff check src/ tests/

# Finding #12 contract removal: no cross-layer sanitizer import in crypto
grep -rn "safe_cell_value" src/tax_reporting/application/crypto/ && echo "LEAK REMAINS" || echo "clean"

# Finding #6 contract removal: no inline guard idiom left in crypto
grep -rn "is_symlink()\|stat().st_size" src/tax_reporting/application/crypto/ && echo "DUPLICATION REMAINS" || echo "clean"
```

### Task 1: `strip_control_chars` - direct unit tests (RED)

Files:
- `tests/unit/infrastructure/test_text_sanitize.py` *(new)*

- [ ] `TestStripControlChars#test_strips_control_chars_keeps_printable` - given `"a\x00b\x07c"`, expects `"abc"`
- [ ] `TestStripControlChars#test_preserves_tab` - given `"a\tb"`, expects `"a\tb"` (tab is the only control char kept, matching current `safe_cell_value`)
- [ ] `TestStripControlChars#test_strips_newline_cr_ff` - given `"a\nb\rc\fd"`, expects the control chars stripped to `"abcd"`
- [ ] `TestStripControlChars#test_empty_string` - given `""`, expects `""`
- [ ] `TestStripControlChars#test_whitespace_only_preserved` - given `"   "`, expects `"   "`
- [ ] `TestStripControlChars#test_multi_byte_utf8_preserved` - given `"测试"`, expects `"测试"` unchanged
- [ ] `TestStripControlChars#test_does_not_defuse_formula_sigil` - given `"=evil"`, expects `"=evil"` returned as-is (the strip is layer-agnostic; defusal is Excel's job - binds the split)
- [ ] Run → expect RED: `uv run pytest tests/unit/infrastructure/test_text_sanitize.py -v` (module does not exist yet)

### Task 2: create `strip_control_chars`; split `safe_cell_value`; redirect `_sanitize_substring` (GREEN + refactor)

Files:
- `src/tax_reporting/infrastructure/text_sanitize.py` *(new)*
- `src/tax_reporting/application/persisting/excel_utils.py`
- `src/tax_reporting/application/crypto/payment_proceeds.py`

- [ ] Create `infrastructure/text_sanitize.py` with a module docstring stating it is layer-agnostic and intentionally does NOT defuse formula sigils, and `strip_control_chars(value: str) -> str` = `"".join(ch for ch in value if ch >= " " or ch in ("\t",))` (the exact predicate currently inline in `safe_cell_value` at `excel_utils.py:142`).
- [ ] Refactor `safe_cell_value` (`excel_utils.py:125-146`) to compose `strip_control_chars` then the Excel sigil defusal; keep the public name, docstring intent, and output byte-identical. Import `strip_control_chars` from `infrastructure.text_sanitize`.
- [ ] Redirect `payment_proceeds._sanitize_substring` (line ~484) to call `strip_control_chars` directly; swap the import at line 42 from `safe_cell_value` (persisting) to `strip_control_chars` (infrastructure); drop the `persisting` import.
- [ ] Run → expect GREEN: `uv run pytest tests/unit/infrastructure/test_text_sanitize.py tests/unit/application/persisting/test_excel_utils.py -v`
- [ ] Characterization (must stay GREEN): `uv run pytest tests/unit/application/test_payment_proceeds.py::test_formula_injection_in_review_reasons_neutralized -v` - proves the payment sanitize path still strips control chars after the redirect.
- [ ] Commit: `refactor(crypto): split safe_cell_value control-char strip into infrastructure util (DP-014 #12)`

### Task 3: `load_guarded_json` - direct unit tests (RED)

Files:
- `tests/unit/infrastructure/test_json_loader.py` *(new)*

- [ ] `TestLoadGuardedJson#test_valid_json_returned_parsed` - given a real JSON file, expects the parsed object returned unchanged (no schema validation applied)
- [ ] `TestLoadGuardedJson#test_parsed_null_is_returned_not_degraded` - given a file containing `null`, expects `None` returned (NOT `DEGRADED`) - binds Invariant 4/6 that a parsed `null` is distinct from a degrade
- [ ] `TestLoadGuardedJson#test_symlink_calls_on_error_symlink` - given a symlink `path`, expects `on_error(path, "symlink", _)` invoked and its return value surfaced
- [ ] `TestLoadGuardedJson#test_missing_calls_on_error_missing` - given a non-existent path, expects `on_error(path, "missing", _)` invoked
- [ ] `TestLoadGuardedJson#test_dangling_symlink_reports_symlink_not_missing` - given a symlink whose target does not exist, expects kind `"symlink"` (binds the symlink-before-exists ordering, Invariant 8)
- [ ] `TestLoadGuardedJson#test_oversize_calls_on_error_oversize` - given a file larger than `size_limit`, expects kind `"oversize"` with byte detail
- [ ] `TestLoadGuardedJson#test_size_limit_boundary_at_limit_passes` - given a file exactly `size_limit` bytes, expects it parsed (no `on_error` call)
- [ ] `TestLoadGuardedJson#test_size_limit_boundary_over_limit_fails` - given `size_limit + 1` bytes, expects kind `"oversize"`
- [ ] `TestLoadGuardedJson#test_stat_error_calls_on_error_stat_error` - given a path whose `stat()` raises `OSError` (monkeypatched), expects kind `"stat_error"`
- [ ] `TestLoadGuardedJson#test_invalid_json_calls_on_error_invalid_json` - given a file with malformed JSON, expects kind `"invalid_json"`
- [ ] `TestLoadGuardedJson#test_on_error_raise_propagates` - given an `on_error` that raises `FileProcessingError`, expects `load_guarded_json` to propagate it (derivatives policy)
- [ ] `TestLoadGuardedJson#test_on_error_return_degraded` - given an `on_error` that returns `DEGRADED`, expects `load_guarded_json` to return `DEGRADED` (identity) - binds the degrade contract
- [ ] `TestLoadGuardedJson#test_kind_is_from_closed_set` - across all failure cases, expects every `kind` argument to be one of `{"symlink","missing","oversize","stat_error","invalid_json"}` - typo-proofs the contract callers branch on (esp. derivatives' missing-vs-raise)
- [ ] `TestLoadGuardedJson#test_does_not_validate_shape` - given valid JSON that is a list (not the caller's expected dict schema), expects it returned as-is (shape validation is the caller's job, Invariant 7)
- [ ] Run → expect RED: `uv run pytest tests/unit/infrastructure/test_json_loader.py -v`

### Task 4: create `load_guarded_json` + `DEGRADED` (GREEN)

Files:
- `src/tax_reporting/infrastructure/json_loader.py` *(new)*

- [ ] Module docstring: states the guards centralized (symlink reject, size cap, `json.load`), the `on_error` policy seam (lesson #105), the closed `kind` set, and the `DEGRADED`-vs-`null` distinction. Import nothing from `domain` (the helper does not raise; callers do) except types if needed.
- [ ] Define `DEGRADED: object = object()` (module-level, exported) with a comment explaining it is distinct from a parsed `null`.
- [ ] Implement `load_guarded_json(path: Path, *, size_limit: int, on_error: Callable[[Path, str, str], object]) -> object` per Invariants 6-8: symlink check → exists check → stat (oversize when `file_size > size_limit`; exactly `size_limit` passes) → `json.load`. On each failure call `on_error(path, kind, detail)` and return its result; raise nothing itself. `kind` tokens: `symlink`, `missing`, `oversize`, `stat_error`, `invalid_json`. `detail`: symlink/missing → short static text; oversize → `f"{file_size} bytes, max {size_limit} bytes"`; stat_error/invalid_json → `str(exc)`.
- [ ] Run → expect GREEN: `uv run pytest tests/unit/infrastructure/test_json_loader.py -v`
- [ ] Commit: `feat(infra): add guarded JSON loader with on_error policy seam`

### Task 5: route `payment_proceeds` through the loader (refactor, behavior-preserving)

Files:
- `src/tax_reporting/application/crypto/payment_proceeds.py`

- [ ] Replace the inline symlink/exists/stat/size/`json.load` block in `_load_payment_proceeds_config_from_path` (lines ~129-177) with `data = load_guarded_json(path, size_limit=_MAX_TOKEN_FILE_SIZE, on_error=_on_error)`. The `_on_error(path, kind, detail)` logs the EXISTING-style WARNING for each kind and returns `DEGRADED`. The human phrase ("symlink" / "not found" / "could not stat" / "exceeds size limit" / "invalid JSON") MUST appear in the `_on_error` WARNING format string itself - `detail` alone is insufficient (for `invalid_json`, `detail` is `str(exc)`; for `oversize`, `detail` is `"{bytes} bytes, max {limit} bytes"`; neither contains the asserted phrase) - so the parametrized `test_malformed_or_oversize_or_symlink_degrades` substrings still match. Also embed the path and `detail`.
- [ ] After the call: `if data is DEGRADED: return _default_config()`. Keep the schema validation (`tokens.stablecoins`, `stablecoin_pegs`, `payment_tags`) and the peg/tokens drift guard unchanged (Invariant 7).
- [ ] Update the function/module docstrings: replace "Mirrors the security guards of `classification._load_popular_crypto_tokens`" with a reference to `infrastructure.json_loader.load_guarded_json`.
- [ ] Re-evaluate the `# noqa: PLR0911, PLR0912` on the function (line 110): the guard returns/branches moved to the helper, so remove the noqa directives that are no longer needed; keep (with a comment) only those ruff still reports. Do not run `ruff check --fix` on this module beyond the noqa (it does not re-export).
- [ ] `uv run ruff check src/tax_reporting/application/crypto/payment_proceeds.py` clean - catches any orphaned `# noqa` (RUF100) at THIS commit rather than deferring the discovery to Task 9.
- [ ] Run → expect GREEN (characterization, NO assertion changes): `uv run pytest tests/unit/application/test_payment_proceeds.py -v` - `test_reads_reused_popular_crypto_tokens_json`, `test_missing_file_returns_defaults`, `test_malformed_or_oversize_or_symlink_degrades` (all 3 parametrized kinds), `test_stablecoin_pegs_drift_from_tokens_warns` all pass unchanged. If any wording drifts, fix the `_on_error` message to restore the asserted substring rather than editing the test.
- [ ] Commit: `refactor(crypto): route payment_proceeds config load through guarded JSON loader (DP-014 #6)`

### Task 6: route `derivatives_dedup` through the loader (refactor, behavior-preserving)

Files:
- `src/tax_reporting/application/crypto/derivatives_dedup.py`
- `tests/unit/application/test_derivatives_dedup.py`

- [ ] `TestDerivativesLabelsConfig#test_stat_error_raises` (NEW characterization) - given a config path whose `stat()` raises `OSError` (monkeypatch `tax_reporting.application.crypto.derivatives_dedup.Path.stat`), expects `FileProcessingError` with `str(path)` in the message. Run → GREEN against the CURRENT code first (captures the existing raise at `derivatives_dedup.py:94-97`); must stay GREEN after the refactor. Binds the raise arm of the most safety-critical kind (Invariant 2) - the symmetric twin of classification's `test_stat_error_degrades_to_empty`, closing a copy-paste hole where an implementer could degrade derivatives' `stat_error` and every other Task-6 test would still pass.
- [ ] Replace the inline symlink/exists/stat/size/`json.load` block in `_load_derivatives_labels_config_from_path` (lines ~73-105) with `data = load_guarded_json(path, size_limit=_MAX_LABELS_FILE_SIZE, on_error=_on_error)`. The `_on_error(path, kind, detail)` returns `DEGRADED` for `kind == "missing"` WITHOUT logging (the `apply_derivatives_dedup` caller owns the single WARNING; `test_missing_file_returns_empty_silently` asserts no loader-level warning), and raises `FileProcessingError` embedding the path for every other kind (`symlink`/`oversize`/`stat_error`/`invalid_json`). Do NOT add a `path.exists()` pre-check - the helper checks symlink before missing (Invariant 8); a pre-check would turn a dangling symlink from raise into silent-empty.
- [ ] After the call: `if data is DEGRADED: return frozenset()`. Keep the schema validation (`derivatives_th_labels` list-of-strings) unchanged.
- [ ] Update the docstring comments at lines ~55/73/86 that say "mirrors classification._load_popular_crypto_tokens" to reference `infrastructure.json_loader.load_guarded_json`.
- [ ] Run → expect GREEN (characterization, NO assertion changes): `uv run pytest tests/unit/application/test_derivatives_dedup.py -v` - `test_missing_file_returns_empty_silently`, `test_malformed_json_raises`, `test_missing_derivatives_th_labels_key_raises`, `test_labels_value_wrong_type_raises`, `test_rejects_symlink_config`, AND the new `test_stat_error_raises` all pass (the raise-message tests assert `str(path) in message`, so the `_on_error` raise must embed the path).
- [ ] `uv run ruff check src/tax_reporting/application/crypto/derivatives_dedup.py` clean.
- [ ] Commit: `refactor(crypto): route derivatives_dedup config load through guarded JSON loader (DP-014 #6)`

### Task 7: characterization tests for `classification` loader policy (GREEN before refactor)

Files:
- `tests/unit/application/test_crypto_classification.py`

`classification._load_popular_crypto_tokens` currently has no direct policy tests (only caching/substring tests exist). These capture the mixed policy before Task 8 changes the implementation. Add a MANDATORY `@pytest.fixture(autouse=True)` scoped to `TestClassificationTokenLoader` that (setup + `yield` + teardown) monkeypatches the module's `_POPULAR_CRYPTO_TOKENS_FILE` to a `tmp_path` AND calls `_load_popular_crypto_tokens.cache_clear()` - NOT optional per-test setup, since `@lru_cache(maxsize=1)` (`classification.py:206`) reads the module global at call time and a forgotten `cache_clear()` in one of the cases would read a prior test's cached state. Leave the sibling `TestPopularCryptoTokens.test_popular_tokens_cached` untouched.

- [ ] `TestClassificationTokenLoader#test_symlink_raises` - given a symlinked token file, expects `FileProcessingError`
- [ ] `TestClassificationTokenLoader#test_oversize_raises` - given a token file > 1 MiB, expects `FileProcessingError`
- [ ] `TestClassificationTokenLoader#test_missing_degrades_to_empty` - given a missing path, expects `frozenset()` plus a WARNING log
- [ ] `TestClassificationTokenLoader#test_stat_error_degrades_to_empty` - given a path whose `stat()` raises `OSError` (monkeypatch `tax_reporting.application.crypto.classification.Path.stat` - this target survives the Task 8 move of `stat()` into `infrastructure.json_loader`), expects `frozenset()`, a WARNING log, and NO exception raised (binds the stat_error-degrade branch; explicit degrade discriminator, not just the return value)
- [ ] `TestClassificationTokenLoader#test_invalid_json_degrades_to_empty` - given malformed JSON, expects `frozenset()` plus a WARNING log
- [ ] `TestClassificationTokenLoader#test_not_dict_raises` - given valid JSON that is a list, expects `FileProcessingError`
- [ ] `TestClassificationTokenLoader#test_parsed_null_raises_not_dict` - given a file containing `null`, expects `FileProcessingError` (binds Invariant 4: a parsed `null` is not a degrade)
- [ ] `TestClassificationTokenLoader#test_missing_tokens_key_raises` - given `{}`, expects `FileProcessingError`
- [ ] `TestClassificationTokenLoader#test_tokens_value_not_dict_raises` - given `{"tokens": ["not", "a", "dict"]}`, expects `FileProcessingError` (binds the tokens-not-dict branch, the arm most likely to regress)
- [ ] Run → expect GREEN (characterization of current behavior): `uv run pytest tests/unit/application/test_crypto_classification.py -v`

### Task 8: route `classification` through the loader (refactor, behavior-preserving)

Files:
- `src/tax_reporting/application/crypto/classification.py`

- [ ] Replace the inline symlink/exists/stat/size/`json.load` block in `_load_popular_crypto_tokens` (lines ~221-289) with `data = load_guarded_json(_POPULAR_CRYPTO_TOKENS_FILE, size_limit=_MAX_TOKEN_FILE_SIZE, on_error=_on_error)`. The `_on_error(path, kind, detail)` raises `FileProcessingError` for `kind in ("symlink", "oversize")` and logs+returns `DEGRADED` for `kind in ("missing", "stat_error", "invalid_json")` (Invariant 4).
- [ ] After the call: `if data is DEGRADED: return frozenset()`. Keep the `@lru_cache` wrapper and the `tokens` schema validation (not-dict / missing-key / tokens-not-dict → raise) unchanged. Promote the inline `max_token_file_size = 1 * 1024 * 1024` (line ~237) to a module-level `_MAX_TOKEN_FILE_SIZE` constant - matching payment_proceeds naming (`_MAX_TOKEN_FILE_SIZE`); the derivatives loader uses `_MAX_LABELS_FILE_SIZE` for its labels file, so do NOT name it after derivatives.
- [ ] `AttributeError` arm: the old `except (json.JSONDecodeError, OSError, AttributeError)` block wrapped `json.load` (now in the helper, surfaced as `invalid_json` via `on_error`) plus shape access. Post-refactor the shape access is caller-side and guarded by `isinstance` checks, so the `AttributeError` arm is unreachable; it is intentionally dropped. Task 7's characterization (incl. `test_tokens_value_not_dict_raises`, `test_parsed_null_raises_not_dict`) proves no regression. Add a one-line code comment documenting this.
- [ ] Run → expect GREEN: `uv run pytest tests/unit/application/test_crypto_classification.py -v` - Task 7 characterization tests stay GREEN (proves the mixed policy is preserved).
- [ ] `uv run ruff check src/tax_reporting/application/crypto/classification.py` clean.
- [ ] Commit: `refactor(crypto): route classification token load through guarded JSON loader (DP-014 #6)`

### Task 9: final lint, full suite, contract greps

Files:
- `src/tax_reporting/application/crypto/{payment_proceeds,classification,derivatives_dedup}.py`

(The inline guard blocks were removed in-line by Tasks 5/6/8 as part of replacing them with the helper call; this task is the cross-cutting verification pass.)

- [ ] `uv run ruff check src/ tests/` clean - confirm no unused `# noqa` (RUF100) survives on the three refactored loaders, and no dropped `json` import is now orphaned (only remove `import json` if the module no longer references it directly; classification/payment/derivatives may still use `json` for fixture/other purposes - verify each).
- [ ] `uv run pytest` full suite GREEN.
- [ ] Verify the two contract-removal greps in `## Validation Commands` both print `clean`.
- [ ] Commit (only if any cleanup was needed): `refactor(crypto): tidy after guarded-JSON-loader extraction`

### Task 10: docs sync

Files:
- `docs/history/feature-notes/2026-06-20-crypto-payment-proceeds-refactor-options.md`
- `docs/maintenance/development_lessons.md`
- `docs/maintenance/crypto_implementation_guidelines.md`

- [ ] Flip the options record Status from DEFERRED to IMPLEMENTED; note both findings resolved via Option B with the commit refs from Tasks 2/5/6/8.
- [ ] In `development_lessons.md` lesson #105, add an unconditional one-line cross-reference to `infrastructure/json_loader.py` as the canonical in-repo example of "inherit the guards, recalibrate exception handling."
- [ ] Grep `docs/maintenance/crypto_implementation_guidelines.md` for stale inline-guard / "mirrors classification" references (r1 flagged ~lines 1110-1117 and ~1496-1509) and repoint them to the shared loader.
- [ ] Run `check-no-em-dash.sh` on changed docs (no `-` in generated text).
- [ ] Commit: `docs(crypto): mark DP-014 refactor options #6/#12 implemented`
