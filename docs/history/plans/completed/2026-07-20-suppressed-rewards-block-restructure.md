# Plan: Split suppressed-rewards / dust-summary blocks into outer header + sub-headers

User feedback on the just-completed deferred-reward-dust-skip work: in the Crypto
Supplementary sheet, the "Suppressed zero-value deferred rewards" block merges dust
+ unpriced into one clause, with no blank spacer row before the header. Desired end
state: **two clearly separated tables (dust / unpriced) under one outer header,
with a blank spacer row before the outer header**. Apply the same treatment to the
CRG-021 taxable-now "Dust summary:" block for consistency.

User answers (via AskUserQuestion):
1. **Outer header + 2 sub-headers** (keep "Suppressed zero-value deferred rewards"
   bold; add "Deferred dust (...)" + "Deferred unpriced (...)" sub-headers).
2. **One row per (token, wallet)** - same granularity as today, sorted by (asset,
   wallet).
3. **Restructure both** Section 3 (deferred) AND Section 2 (taxable-now) blocks.

This reverses the predecessor plan's r1-review decision to collapse two blocks into
one. That decision was an aesthetic call by 5 review agents; the user's lived
experience of the rendered sheet overrides it.

## Gist & Examples

**Production change.** In `crypto_supplementary_sheet.py`:

1. Add a **blank spacer row** before the outer header of each block (matches the
   existing `row_no += 1` spacer convention used at every section boundary:
   Section 2/3/4/5 headers).
2. Restructure `_write_suppressed_deferred_rewards_block` to render:
   - Spacer row.
   - Outer bold header: `"Suppressed zero-value deferred rewards"`.
   - **Sub-header 1 (bold)**: `"Deferred dust (priced-asset rounding)"` - followed
     by sorted per-(asset, wallet) dust lines. Rendered only when `dust_rows` is
     non-empty.
   - **Sub-header 2 (bold)**: `"Deferred unpriced (no Koinly price feed)"` -
     followed by sorted per-(asset, wallet) unpriced lines. Rendered only when
     `unpriced_rows` is non-empty.
3. Restructure `_write_dust_summary_block` (taxable-now, CRG-021) symmetrically:
   - Spacer row.
   - Outer bold header: `"Dust summary:"` (kept - many tests pin it).
   - **Sub-header (bold)**: `"Taxable-now dust (priced-asset rounding)"` - followed
     by sorted per-(asset, wallet) dust lines. (Taxable-now has only one bucket;
     unpriced taxable-now rows keep per-row YES in the detail table per CRG-021,
     so no second sub-header.)

**Per-row line format (unchanged):** `{asset} ({wallet}): {count} rows, summed
amount = {amount:.8f} {asset} -{reason}` for deferred; `{asset} dust ({wallet}):
{count} rows, summed Value EUR = {float(summed):.2f} (...)` for taxable-now. The
em-dash-no-space on deferred (`-dust` / `-unpriced`) stays pinned by the unit
tests at `test_crypto_supplementary_sheet.py:1846, 1897`.

**Section 4 reconciliation labels stay unchanged.** The three deferred lines
`("Deferred detail rows", N)`, `("Deferred dust rows (suppressed from detail)",
M)`, `("Deferred unpriced rows (suppressed from detail)", K)` and the two
taxable-now lines keep their exact text - they are bucket counts, independent of
the rendered block shape.

## Files

- `src/tax_reporting/application/persisting/crypto_supplementary_sheet.py` -
  restructure the two helpers; add spacer rows.
- `tests/unit/application/persisting/test_crypto_supplementary_sheet.py` - update
  pinning tests.
- `tests/end_to_end/test_crypto_dust_partition.py` - update e2e block-locator
  helpers.
- `docs/maintenance/crypto_reporting_guidelines.md` - update CRG-021 + CRG-022
  prose ("ONE block" → "outer header + sub-headers").
- `docs/maintenance/crypto_implementation_guidelines.md` - update CRG-021 +
  CRG-022 notes.
- `docs/maintenance/tax_reporting_guidelines.md` - update Section 3 description.
- `docs/maintenance/glossary.md` - update "Reward dust" / "Deferred dust" /
  "Unpriced deferred reward" entries.

## Tasks

### Task 1: RED - pinned-shape tests for the new block structure

Files: `tests/unit/application/persisting/test_crypto_supplementary_sheet.py`

- [x] Add `TestCryptoSupplementarySheetDeferredSkip#test_block_has_outer_header_and_two_subheaders`
- [x] Add `TestCryptoSupplementarySheetDeferredSkip#test_outer_header_preceded_by_blank_spacer_row`
- [x] Add `TestCryptoSupplementarySheetDeferredSkip#test_dust_only_renders_dust_subheader_only`
- [x] Add `TestCryptoSupplementarySheetDeferredSkip#test_unpriced_only_renders_unpriced_subheader_only`
- [x] Update existing `test_dust_and_unpriced_rows_render_in_one_block_sorted` (L1910-1976)
- [x] Add `TestCryptoSupplementarySheetDustSummary#test_taxable_now_block_has_outer_header_and_subheader`
- [x] Add `TestCryptoSupplementarySheetDustSummary#test_taxable_now_outer_header_preceded_by_blank_spacer_row`
- [x] Update `skip_prefixes` tuples (L1080 + L1141-1145)
- [x] Run → expect RED

### Task 2: GREEN - restructure both helpers + spacer rows

Files: `src/tax_reporting/application/persisting/crypto_supplementary_sheet.py`

- [x] Modify `_write_suppressed_deferred_rewards_block` (spacer + outer + 2 sub-headers + conditional render)
- [x] Modify `_write_dust_summary_block` symmetrically (spacer + outer + 1 sub-header)
- [x] Run → expect GREEN
- [x] Commit: `feat(crypto): split suppressed-rewards and dust-summary blocks into outer header + sub-headers`

### Task 3: Update e2e block-locator helpers

Files: `tests/end_to_end/test_crypto_dust_partition.py`

- [x] Update `_suppressed_deferred_block_lines` (L253-279) to walk across sub-headers
- [x] Verify `_section2_detail_rows` terminator (L214) still works
- [x] Run → expect GREEN
- [x] Commit: `test(crypto): adjust e2e block-locators for outer-header + sub-headers restructure`

### Task 4: Docs - CRG-021 + CRG-022 + glossary + SRG + impl note

- [x] CRG-021 (crypto_reporting_guidelines.md:125)
- [x] CRG-022 (crypto_reporting_guidelines.md:127)
- [x] crypto_implementation_guidelines.md:425 + :427
- [x] tax_reporting_guidelines.md:85
- [x] glossary.md:25, :26, :27
- [x] Doc-drift grep
- [x] Commit: `docs(crypto): update CRG-021/CRG-022 + glossary for outer-header + sub-headers block shape`

### Task 5: Final validation + visual confirm

- [x] Full crypto regression GREEN
- [x] Full e2e GREEN
- [x] Ruff clean
- [x] Generate example workbook; visually confirm Section 2 + Section 3 blocks

## Validation Commands

```bash
uv run pytest tests/unit/application/persisting/test_crypto_supplementary_sheet.py -v
uv run pytest tests/end_to_end/test_crypto_dust_partition.py tests/end_to_end/test_example_report_generation.py -v -m e2e
uv run pytest tests/unit/application/test_crypto_reporting.py tests/unit/application/persisting/ tests/end_to_end/ -k "crypto or supplementary or reconciliation"
uv run ruff check src/tax_reporting/application/persisting/crypto_supplementary_sheet.py tests/unit/application/persisting/test_crypto_supplementary_sheet.py tests/end_to_end/test_crypto_dust_partition.py
grep -rn "Dust summary\|Suppressed zero-value deferred rewards\|Deferred dust\|Deferred unpriced\|Taxable-now dust" docs/maintenance/ README.md
```

## Design Invariants

1. **Outer header text unchanged.** `"Suppressed zero-value deferred rewards"`
   and `"Dust summary:"` keep their exact text.
2. **Per-row line format unchanged.** Em-dash-no-space on deferred stays pinned;
   `:.8f` amount spec stays pinned; taxable-now `summed Value EUR` format stays.
3. **Conditional sub-header render.** A sub-header renders only when its bucket
   is non-empty.
4. **Spacer row matches existing convention.** `row_no += 1` before each outer
   header - identical to section-header spacers.
5. **Section 4 reconciliation labels stay verbatim.**
6. **Partition logic unchanged.** `_partition_skipped_rewards` still computes
   once; helpers take pre-partitioned rows (Invariant 5 preserved).
7. **No new public API.** The two helpers keep their existing signatures.
