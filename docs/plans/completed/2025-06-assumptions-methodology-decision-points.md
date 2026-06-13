# Plan: Assumptions & Methodology Decision Points

Plan review: the local review record (latest, ready=yes) — 0 Blockers, 0 Medium | r2 (1 Blocker, 3 Medium addressed) | r1 (2 Blockers, 3 Medium addressed)

## Terms

- **DP-XXX**: Decision Point identifier from `docs/tax/decision_points/2025.toml`
- **PT-C-XXX**: Portugal Crypto rule identifier from `docs/domain/crypto_rules.md`
- **Methodology Assumptions**: The second section of the "Assumptions & Methodology" Excel sheet (Platform Assumptions is the first section)
- **CIRS**: Código do Imposto sobre o Rendimento das Pessoas Singulares (Portuguese Income Tax Code)

## Gist & Examples

The "Methodology Assumptions" section of the Assumptions & Methodology tab is missing critical Portuguese tax decision points. Currently it documents only 5 items (Aggregation Approach, FIFO Methodology, Holding Period Classification, Materiality Threshold, Data Sources). The canonical `docs/tax/decision_points/2025.md` documents 11 decision points (DP-001 through DP-011), and `docs/domain/crypto_rules.md` documents additional legal rules.

**What changes:**
- Restructure Methodology Assumptions from flat list to grouped sections (Taxable Events, Exemptions, Losses, Rates, Implementation)
- Document ALL decision points from decision_points/2025.md (DP-001 through DP-011) that are missing from current methodology_items
- Add PT-C rules without DP numbers that are legally significant (PT-C-012 transitional rule, PT-C-016 carry-forward, PT-C-017 blacklisted jurisdictions, PT-C-014 tax rates)
- Current items already have legal citations (PT-C-XXX references); new items need CIRS article numbers and AT folheto dates
- Update both Excel generation code and decision_points documentation
- Fix empty crypto data handling: methodology should render even without platform data (currently returns early)

**Note on legal citations:** Some decision points (DP-006 transfer fees, DP-009 cashback) lack explicit CIRS article citations in the canonical source. These will be documented with the best available legal basis (general principles, AT guidance) and marked clearly as implementation decisions where appropriate.

**Examples of missing items:**
- **Loan repayment exclusion** (DP-001): Returning borrowed crypto is NOT a taxable disposal (CIRS art. 10(20))
- **Crypto-to-crypto deferral** (DP-002): No tax on crypto-to-crypto swaps (CIRS art. 10(20))
- **Losses carry-forward** (PT-C-016): Capital losses may be carried forward 5 years (CIRS art. 55(1)(d))
- **Futures/derivatives treatment** (DP-010): Liquidations are taxable disposals, not withdrawals (CIRS art. 10(1)(e))

**Why this matters:**
The Methodology Assumptions section is the taxpayer's audit trail for filing decisions. Missing key decision points like "losses are actually considered losses under Portuguese law" makes it impossible to defend the filing if questioned. The section should be a complete reference for all Portuguese-tax-specific decisions applied to the report.

## Evaluation Criteria

**Quality dimensions:**
- **Legal traceability:** Every methodology item cites its legal basis with specific article numbers and source dates (e.g. "CIRS art. 10(20)", "AT folheto 2026-01-12", "AT PIV 22065")
- **Maintainability:** Methodology content derives from canonical sources (decision_points/2025.md, crypto_rules.md) with clear cross-references; no duplicated facts that can drift apart
- **Visual correctness:** Excel output renders with proper formatting (section headers in bold, readable line spacing, no overflow)

**Release gates:**
- Full test suite passes: `uv run pytest`
- Manual Excel inspection confirms grouped sections render correctly
- decision_points/2025.md stays in sync with report content

## Review Scope

Files directly changed as part of this plan. Review feedback is accepted **only** for the files listed here.
Any finding about a file not in this list must be rejected as out of scope.

**Production code — in scope:**
- `src/tax_reporting/application/persisting/assumptions_sheet.py` *(modified)*

**Tests — in scope:**
- `tests/unit/application/persisting/test_assumptions_sheet.py` *(new)*

**Documentation — scope-linked (not a closed file list):**
- `docs/tax/decision_points/2025.md` — may be updated to ensure all decision points are documented
- `docs/domain/crypto_rules.md` — reference only; no changes expected

**Out of scope — reject all review feedback:**
- Other sheet writers (crypto_gains_sheet.py, ib_sheet.py, etc.) — not touched by this change
- Platform Assumptions section of assumptions_sheet.py — first section unchanged
- Other report tabs (IB, Crypto Gains, Crypto Supplementary, etc.) — not in scope

## Validation Commands

```bash
uv run pytest -m unit -x --tb=short
uv run tax-reporting --example
# Manual: inspect extract.xlsx, "Assumptions & Methodology" tab, Methodology Assumptions section
```

### Task 1: Verify current Methodology Assumptions content and structure

Files:
- `src/tax_reporting/application/persisting/assumptions_sheet.py`
- `docs/tax/decision_points/2025.md`
- `docs/domain/crypto_rules.md`

- [x] Read current methodology_items list in assumptions_sheet.py (lines 163-197)
- [x] Read DP-001 through DP-011 from decision_points/2025.md
- [x] Read PT-C rules from crypto_rules.md sections 1-9
- [x] Create gap analysis: list which decision points are missing from current methodology_items
- [x] Verify which items in current methodology_items have legal citations
- [x] Document expected grouped sections structure (Taxable Events, Exemptions, Losses, Rates, Implementation)
- [x] Commit: `investigation: gap analysis of methodology assumptions vs decision points`

### Task 2: Design new grouped structure with legal citations

Files:
- `src/tax_reporting/application/persisting/assumptions_sheet.py`
- `docs/tax/decision_points/2025.md`

- [x] Define section groups for methodology items:
  - Section 1: Taxable Events (alienação onerosa, crypto-to-crypto, loan repayment)
  - Section 2: Holding Period & Exemptions (365-day rule, transitional rule)
  - Section 3: Capital Gains Calculation (FIFO, per-wallet, fees, aggregation)
  - Section 4: Losses (carry-forward, blacklisted jurisdictions, futures/derivatives)
  - Section 5: Tax Rates (28% flat, englobamento)
  - Section 6: Other Gains (rewards classification)
  - Section 7: Implementation (materiality threshold, data sources, cashback, OGR usage)
- [x] Create explicit mapping table of DP-XXX/PT-C-XXX to sections:
  ```
  Taxable Events:
    - DP-001: Loan Repayment Exclusion
    - DP-002: Crypto-to-Crypto Deferral
    - DP-003: Cost Basis Method (FIFO)
    - DP-006: Transfer Fees
    - DP-007: Fee Deductibility
  Holding Period & Exemptions:
    - PT-C-011: 365-day exemption
    - PT-C-012: Transitional rule (assets acquired before 2023)
  Capital Gains Calculation:
    - DP-004: Per-Wallet FIFO
    - DP-005: Liquidity Provision
    - PT-C-027: Aggregation Approach (existing)
    - PT-C-008/PT-C-009: FIFO Methodology (existing)
  Losses:
    - PT-C-016: Losses Carry-Forward
    - DP-010: Futures/Derivatives Losses
    - PT-C-017: Blacklisted Jurisdictions
  Tax Rates:
    - PT-C-014: 28% Flat Rate and Englobamento
  Other Gains:
    - DP-008: Other Gains Classification
  Implementation:
    - DP-009: Cashback Treatment
    - DP-011: OGR Usage for Derivatives
    - PT-C-028: Materiality Threshold (existing)
  ```

- [x] For each DP-XXX and relevant PT-C-XXX, draft content with legal citation
- [x] Verify each item cites specific source: CIRS article number, AT folheto date, or PIV number
- [x] Ensure cross-references to decision_points/2025.md and crypto_rules.md are clear
- [x] Write methodology_items as list of (section_header, items) tuples for code structure
- [x] Commit: `design: grouped methodology structure with legal citations`

### Task 2b: Fix empty crypto data handling

Files:
- `src/tax_reporting/application/persisting/assumptions_sheet.py`

**CRITICAL:** Current implementation has early return when `not summaries` (lines 121-124), which skips the methodology section entirely. This violates Design Invariant #3.

- [x] `AssumptionsSheetTest#test_methodology_renders_without_crypto_data` — given empty capital_entries and reward_entries, expects methodology section still renders with "Methodology Assumptions" header and all content
- [x] Run → expect RED: `uv run pytest tests/unit/application/persisting/test_assumptions_sheet.py -x -k test_methodology_renders_without_crypto_data`
- [x] Remove early return logic; methodology section should populate regardless of platform data presence
- [x] Platform Assumptions section should show "No platform data found." when summaries empty, but methodology should still render below
- [x] Run → expect GREEN
- [x] Commit: `fix: methodology section renders even without crypto data`

### Task 3: Implement new methodology section structure

Files:
- `src/tax_reporting/application/persisting/assumptions_sheet.py`

- [x] `AssumptionsSheetTest#test_methodology_sections_render` — given a report with crypto data, expects methodology section renders with grouped section headers in bold
- [x] `AssumptionsSheetTest#test_methodology_items_have_legal_citations` — given methodology items, expects each item includes CIRS article or AT source reference
- [x] Run → expect RED: `uv run pytest tests/unit/application/persisting/test_assumptions_sheet.py -x -k methodology`
- [x] Refactor write_assumptions_and_methodology_sheet() to use grouped structure
- [x] Update methodology_items to nested structure: list of (section_title, [(label, description), ...])
- [x] Implement section header rendering: bold font, blank row before each section
- [x] Update methodology_items content with all missing decision points
- [x] Verify each description includes legal citation (CIRS art X, AT folheto date, or PIV number)
- [x] Run → expect GREEN
- [x] Commit: `feat: add grouped methodology sections with legal citations`

### Task 4: Add missing decision points to methodology content

Files:
- `src/tax_reporting/application/persisting/assumptions_sheet.py`

Add the following missing decision points to appropriate sections. This documents ALL decision points from decision_points/2025.md (DP-001 through DP-011) plus key PT-C rules:

**Taxable Events section:**
- [x] Loan Repayment Exclusion — Returning borrowed crypto is NOT taxable disposal (DP-001, CIRS art. 10(20))
- [x] Crypto-to-Crypto Deferral — No tax on crypto-to-crypto swaps (DP-002, CIRS art. 10(20))
- [x] Cost Basis Method — FIFO method mandatory (DP-003, CIRS art. 43 n.6 al.g, PT-C-008)
- [x] Transfer Fees — Gas fees are taxable disposals (DP-006, CIRS art. 10(4)(a), PT-C-007)
- [x] Fee Deductibility — Fees are deductible costs (DP-007, CIRS art. 10(4)(a), PT-C-007)

**Holding Period & Exemptions section:**
- [x] Transitional Rule — Assets acquired before 2023 qualify immediately (PT-C-012, Art. 220 Lei n.º 24-D/2022)

**Capital Gains Calculation section:**
- [x] Per-Wallet FIFO — FIFO applied per exchange/institution (DP-004, CIRS art. 43 n.9, PT-C-009)
- [x] Liquidity Provision — LP operations deferred (DP-005, CIRS art. 10(20))

**Losses section:**
- [x] Losses Carry-Forward — Capital losses carried forward 5 years (PT-C-016, CIRS art. 55(1)(d))
- [x] Futures/Derivatives Losses — Liquidations are taxable disposals (DP-010, CIRS art. 10(1)(e), PT-C-031)
- [x] Blacklisted Jurisdictions — Losses with blacklisted counterparties not deductible (PT-C-017, CIRS art. 43 n.5)

**Tax Rates section:**
- [x] 28% Flat Rate — Capital gains taxed at 28% flat rate (PT-C-014, CIRS art. 72(1)(c))
- [x] Englobamento — Option to aggregate for progressive rates (PT-C-014, CIRS art. 72(13))

**Other Gains section:**
- [x] Other Gains Classification — Rewards are Category E income, not Category G (DP-008, CIRS art. 5(11))

**Implementation section:**
- [x] Cashback Treatment — Record actual value, not zero-cost (DP-009, implementation decision)
- [x] OGR Usage for Derivatives — Use Other Gains Report values for futures/derivatives (DP-011, CIRS art. 10(1)(e))

- [x] `AssumptionsSheetTest#test_all_decision_points_documented` — given decision_points/2025.md content, expects each DP-XXX has corresponding methodology item
- [x] Run → expect RED
- [x] Add each missing decision point to methodology_items with legal citation
- [x] For DP-006 and DP-009 (lacking explicit CIRS citations), document with best available basis and mark as implementation decision where appropriate
- [x] Run → expect GREEN
- [x] Commit: `feat: add all decision points to methodology assumptions`

### Task 5: Verify decision_points documentation sync

Files:
- `docs/tax/decision_points/2025.md`

- [x] Read methodology_items from assumptions_sheet.py
- [x] Compare each item against decision_points/2025.md DP-001 through DP-011
- [x] Verify any decision point in report is documented in 2025.md
- [x] Verify any legal citation in report has matching source in sources.md or 2025.md

**NOTE:** Citation accuracy requires manual verification. Task 6 validates format (regex), but verifying that "CIRS art. 10(20)" actually exists in the official CIRS PDF is a manual step. Cross-check each citation against docs/tax/laws/pt/crypto-tax/official/ before finalizing.
- [x] If gaps found, update decision_points/2025.md to include missing items
- [x] Commit: `docs: sync decision_points with methodology assumptions`

### Task 6: Add Excel formatting and invariance tests

Files:
- `tests/unit/application/persisting/test_assumptions_sheet.py`

- [x] `AssumptionsSheetTest#test_platform_assumptions_section_unchanged` — given a report with crypto data, expects Platform Assumptions section structure (headers, column order, red-fill logic) unchanged after methodology refactor
- [x] `AssumptionsSheetTest#test_methodology_renders_without_crypto_data` — given empty entries, expects methodology section renders completely (Design Invariant #3 verification)
- [x] `AssumptionsSheetTest#test_section_headers_bold` — given methodology section, expects section headers (e.g. "Taxable Events") have `.font.bold is True`
- [x] `AssumptionsSheetTest#test_section_spacing` — given multiple sections, expects exactly 1 blank row between sections (cell value is None)
- [x] `AssumptionsSheetTest#test_legal_citation_format` — given methodology items, expects legal citations follow format: "CIRS art. X" or "AT folheto YYYY-MM-DD" or "AT PIV XXXXX" (regex validation)
- [x] Run → expect RED
- [x] Verify auto_column_width handles multi-line descriptions without overflow
- [x] Ensure no cell text is truncated in Excel output
- [x] Run → expect GREEN
- [x] Commit: `test: add Excel formatting and invariance verification`

### Task 7: Manual Excel verification and cleanup

Files:
- `src/tax_reporting/application/persisting/assumptions_sheet.py`

- [x] Run `uv run tax-reporting --example`
- [x] Open `resources/result/extract.xlsx`
- [x] Navigate to "Assumptions & Methodology" tab
- [x] Verify Platform Assumptions section unchanged (first section)
- [x] Verify Methodology Assumptions has grouped sections with headers
- [x] Verify section headers are bold
- [x] Verify blank rows between sections
- [x] Verify each item has legal citation
- [x] Verify no cell overflow (all text visible)
- [x] If formatting issues, fix in assumptions_sheet.py
- [x] Run full test suite: `uv run pytest`
- [x] Commit: `refinement: Excel formatting adjustments based on manual review`

### Task 8: Documentation updates

Files:
- `README.md` (if it references the Assumptions & Methodology tab)

- [x] Check if README.md mentions Assumptions & Methodology tab
- [x] If so, update description to reflect new grouped structure
- [x] Verify CLAUDE.md has no hardcoded references to old methodology items
- [x] Commit: `docs: update README for methodology section structure`

## Design Invariants

1. **Platform Assumptions section unchanged** — The first section of the sheet (Platform Assumptions) must remain exactly as is; only the Methodology Assumptions section is modified.
2. **Other tabs unchanged** — This plan touches only the Assumptions & Methodology tab writer; no other report tabs are affected.
3. **No crypto dependency** — The sheet must render correctly even when crypto data is absent (platforms list may be empty, but methodology should always populate).
