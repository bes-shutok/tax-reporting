# Project Guidelines

1. Every downloaded external source mirrored under `docs/.../official/` must have a corresponding `sources.md` entry that records the official URL, issuing date, effective date (when the source takes legal effect; defaults to issuing date if not separately specified), superseded date (when replaced by a newer enactment; `-` when still current), retrieval date, purpose, and the exact articles, sections, annexes, chapters, or clauses relied on. Publication date alone does not determine when a law applies; a source published in 2023 may take effect in 2025, and a 2024 enactment may supersede a 2021 law. The effective/superseded chain is what determines which sources govern a given fiscal year. Each time an archived external source is used for analysis, implementation, or user-facing advice, check the official source first for a newer version. If a newer official version exists, archive it in the correct folder and update the manifest before relying on that source.

2. Tax treatment decision points live in `docs/tax/decision_points/<year>.md`, one file per fiscal year. Each file is a self-contained snapshot listing which laws are in effect for that year (with effective/superseded dates), the per-country decision-point table, and source references. A `README.md` index lists all fiscal years and provides a template for creating new ones. When starting a new fiscal year, copy the latest year file, re-verify each decision point against current sources in `docs/tax/laws/`, and update the laws-in-effect table. When a law or interpretation has not changed, the new file may reference the prior year for unchanged rows rather than repeating full rationale.

   Each `<year>.md` has a machine-readable companion `<year>.toml` in the same directory. The TOML is the runtime sidecar consumed by `config.py`; it encodes law-driven boolean flags per country (e.g. `exclude_loan_repayment_gains`). When a decision point changes (new year or amended law), update **both** files together: the `.md` for the human-readable rationale and the `.toml` for the machine-readable flags. `config.ini` does not contain law-driven flags; those live exclusively in the TOML sidecar.

3. AT guidance documents (folheto, PIVs, ofícios circulados) may cite CIRS paragraph numbers from before a renumbering amendment. When consulting any AT guidance that cites a CIRS paragraph number, cross-check the number against the current consolidated CIRS PDF. The consolidated PDF includes inline annotations such as "(Anterior n.º 7 - Lei n.º 31/2024)" that make renaming explicit. Whenever a renumbering is discovered, update all affected references in `sources.md` "Relevant provisions consulted" fields, decision point notes, and `platform-divergences.md` in the same pass. The consolidated CIRS is always the authoritative current numbering; AT documents are authoritative on interpretation but may lag on paragraph numbering.

4. Multi-agent code review catches critical bugs that single-reviewer passes miss. The FIFO rebuild implementation (2026-05-27) required multiple review iterations: fixes in one pass revealed new issues. Always verify review findings against actual code state, not assumptions from prior iterations. Critical bugs found during review:
   - Fee unit errors (using crypto quantity instead of EUR value for cost basis)
   - Temporal FIFO violations (future-dated lots consumed by past disposals)
   - Empty string handling corrupting aggregation results
   - Missing review flags on zero-cost pool exhaustion

   Code review must examine the actual diff and source files in each iteration; summaries from prior passes become stale as code changes.

5. **Data handling: missing vs invalid.** Treat missing and invalid data differently.

   **Missing data** (supplementary info absent but can be added manually later: ISIN, country, security details): process with clear error indicators. Always log an `ERROR` with actionable guidance, include the record in output with a visible sentinel (`"MISSING_ISIN_REQUIRES_ATTENTION"`, `"UNKNOWN_COUNTRY"`), highlight in Excel, and never lose monetary amounts due to missing supplementary info.

   **Invalid data** (format corrupted, non-numeric amounts, required columns absent, broken structure): fail fast with a `FileProcessingError` containing row number, field, and expected format. Use exception chaining (`from e`). Do not continue processing with corrupted data.

   Key principles: never silently skip expected data; preserve financial integrity; distinguish missing (warn and continue) from invalid (stop immediately). Log with parameterised format (`logger.error("Row %d: bad value %s", row, val)`); raise with f-strings (`raise FileProcessingError(f"Row {row}: bad value {val}")`).

