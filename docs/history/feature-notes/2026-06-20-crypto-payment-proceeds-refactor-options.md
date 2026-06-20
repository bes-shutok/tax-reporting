# Proposal: DP-014 payment-proceeds refactor options (#6, #12)

- **Status:** DEFERRED (options record; not active work - choose before implementing)
- **Date:** 2026-06-20
- **Branch:** 2026-06-19-doc-hierarchy-migration
- **Related:** review findings #6, #12 in
  `docs/history/reviews/2026-06-20-branch-review-doc-hierarchy-migration.md`;
  DP-014 payment-proceeds correction.

## Purpose

Record the refactor decisions behind two Low-severity branch-review findings so
the choice is deliberate, not improvised when someone picks them up. Both are
pure code structure (no correctness impact today); neither is urgent. They are
deferred here rather than patched on the migration branch because each is an
architectural move the Triage Decision Rule reserves for the user.

Each finding has a real choice to make (share vs move, or split vs move). The
recommendations below are proposals to evaluate, not decisions - confirm with the
user before implementing either.

## Finding #6: config-guard duplication is now three-way

### What was filed

`payment_proceeds.py` bundles five concerns, and its config-loading block
(`PaymentProceedsConfig`, `_default_config`,
`_load_payment_proceeds_config_from_path`, `_get_payment_proceeds_config`, and
the `_DEFAULT_*` / `_MAX_TOKEN_FILE_SIZE` / `_PAYMENT_PROCEEDS_CONFIG_FILE`
constants, ~lines 56-274) is a near-copy of
`classification._load_popular_crypto_tokens`. The finding recommended extracting
the block into a `payment_proceeds_config.py` to mirror the per-concern split
already in the package.

### What verification found (stronger than filed)

The duplication is **three-way, not two-way**. Three modules in
`application/crypto/` each independently re-implement the same security guards
(symlink rejection, 1 MiB size cap, JSON shape validation) over the SAME file
`docs/maintenance/tax/popular_crypto_tokens.json`:

1. `classification._load_popular_crypto_tokens` (classification.py:207) - the
   original; reads the file into a `frozenset[str]`.
2. `derivatives_dedup.py` (lines 55/73/86) - its own symlink + size guards,
   explicitly commented as mirroring classification.
3. `payment_proceeds._load_payment_proceeds_config_from_path` (line 110) - its
   own symlink + size guards, commented as mirroring classification, but
   recalibrated to degrade (warn + defaults) rather than raise.

So the concrete problem is not "payment_proceeds bundles config loading" - it is
"the secure-load discipline for this one JSON file is copy-pasted in three
places, and each new reader reinvents the guards."

### Options

- **A. Move (the filed recommendation).** Extract payment_proceeds's config
  block into `payment_proceeds_config.py`. Reduces the five-concern module; does
  NOT touch the duplication with classification/derivatives_dedup, which keeps
  growing. Lowest risk; narrowest benefit.
- **B. Share (recommended).** Extract ONE secure JSON loader (symlink reject,
  size cap, `json.load`, optional shape validation) into a small package helper
  - e.g. `application/crypto/_token_config.py` with a function like
  `_load_token_config(path, *, size_limit, on_error)` - and have all three
  modules call it. Each caller keeps its own return shape and its own degrade vs
  raise policy (classification returns a `frozenset` and raises; payment_proceeds
  returns a `PaymentProceedsConfig` and degrades). The guards live once. This is
  the `coding_guidelines` "reuse a pattern, recalibrate exception handling"
  discipline applied to the loader, not just the comment.

### Recommendation

Option B. The three-way duplication is the actual debt, and it is in a single
package (`application/crypto/`), so a shared helper is a natural, low-coupling
seam. Option A would tidy one module while leaving two other copies in place and
inviting a fourth.

### Risk / open question

A shared loader means a single guard bug affects three readers - so the shared
helper needs the same direct unit-test coverage the duplicated blocks get
indirectly today (lesson #91: extracted helpers need direct tests, not just
indirect). Confirm the degrade-vs-raise policy is a caller concern (it is:
classification raises, payment_proceeds degrades), so the helper takes the
on-error behavior as a parameter rather than baking one in.

## Finding #12: `safe_cell_value` is a layer leak when used as a sanitizer

### What was filed

`payment_proceeds.py` (application/crypto) imports `safe_cell_value` from
`application/persisting/excel_utils.py` (the presentation sub-package) and routes
external substrings through it via `_sanitize_substring`. Every other caller is
inside `persisting/`. The finding noted the reuse is correct in effect today but
couples the reason builder to the spreadsheet output format.

### What verification found

Confirmed `safe_cell_value` (excel_utils.py:125-146) is the only non-`persisting/`
caller: `payment_proceeds.py:42` imports it; the other ~10 callers are all in
`persisting/` sheets. The function does exactly two things, and they split
cleanly:

1. Control-char strip: `"".join(ch for ch in value if ch >= " " or ch == "\t")`.
   Layer-agnostic - relevant anywhere an external string becomes review/log text.
2. Excel formula-sigil defusal: `if cleaned[:1] in ("=", "+", "-", "@"): return
   f" {cleaned}"`. Presentation-specific - it exists only because of Excel.

`payment_proceeds._sanitize_substring` (line 475) needs the control-char strip
(the reason text is built from external asset/peg strings). It does NOT need the
Excel defusal for correctness - the reasons begin with a fixed prose prefix, so a
leading sigil can never land at cell position 0 (finding #4's analysis). But the
defusal does no harm there either.

### Options

- **A. Move (the filed recommendation).** Move the whole `safe_cell_value` to a
  shared util (e.g. `infrastructure/text_sanitize.py`) and have `persisting/`
  import it. Removes the layer leak, but forces presentation knowledge (the Excel
  sigil defusal) into a shared util that the application layer then depends on -
  the leak moves rather than disappears.
- **B. Split (recommended).** Extract the control-char strip into a shared
  `strip_control_chars(value)` in a neutral util (e.g.
  `infrastructure/text_sanitize.py`), and keep the Excel sigil defusal in
  `persisting/excel_utils.py` where `safe_cell_value` becomes
  `defuse_excel_cell(strip_control_chars(value))` (or just prepends the space).
  `payment_proceeds._sanitize_substring` then calls `strip_control_chars`
  directly - no presentation dependency. The application layer gets exactly the
  protection it needs (control chars); the presentation layer keeps the
  Excel-specific concern.

### Recommendation

Option B. The two responsibilities are genuinely different layers, and the split
matches the dependency direction: a neutral text util that both layers can depend
on, with the Excel concern staying in the package that writes sheets.

### Risk / open question

All ~10 `persisting/` callers keep calling `safe_cell_value` unchanged (it still
defuses after stripping), so no caller-side churn - the split is internal to
excel_utils plus redirecting one import in payment_proceeds. Confirm whether the
neutral util's home is `infrastructure/` (a generic text helper) or
`application/` (if we consider it application-shared) - `infrastructure/` fits the
"cross-cutting, no domain logic" reading, but the package choice is the user's
call (no hardcoded new package path without sign-off).

## Why these are deferred (not done on the migration branch)

- Both are Low severity, zero correctness impact today, and architectural
  (module moves / layer seams). The Triage Decision Rule holds these for the
  user, and interleaving them with the migration commit would muddy the
  migration's "pure renames + DP-014 feature" diff.
- The DP-014 feature is shippable as-is; these are quality-of-structure
  improvements that pay off the next time someone touches config loading or adds
  a non-presentation caller of sanitization.

## Triggers to implement

- A fourth reader of `popular_crypto_tokens.json` appears (would make the
  duplication four-way - implement #6 option B then).
- A second non-`persisting/` caller of `safe_cell_value` appears (would make the
  layer leak systemic - implement #12 option B then).
- Any planned refactor pass over `application/crypto/` (fold both in then).
