# Project Guidelines

## Documentation Hierarchy

This repo follows the three-layer docs layout under `docs/` (Layer 1 `README.md`; Layer 2 `architecture/` + `maintenance/`; Layer 3 `history/`). Start at `docs/README.md`. Canonical schema: company guideline #48 plus the `doc-hierarchy` / `doc-hierarchy-migrate` / `doc-hierarchy-upkeep` skills.

Resolved documentation paths for other skills:

| Key | Path |
|-----|------|
| plans_dir | `docs/history/plans/` |
| plans_completed_dir | `docs/history/plans/completed/` |
| reviews_dir | `docs/history/reviews/` |
| tmp_dir | `docs/tmp/` |
| proposals_dir | `docs/history/feature-notes/proposals/` |
| rfcs_dir | `docs/history/feature-notes/` |
| repo_facts_rel | `.ai-playbook/facts.md` |
| project_guidelines_rel | `docs/maintenance/project-guidelines.md` |

Law-driven decision points and the tax-law archive live under `docs/maintenance/tax/`; domain guidelines (crypto rules, reporting guidelines, Koinly, lessons) live directly under `docs/maintenance/`.

Layer 3 history subdirectories have distinct semantics; place a file by lifecycle stage, not by topic:
- `feature-notes/` (`rfcs_dir`) holds **active** RFCs / PRDs / proposals for improvement only. When an RFC lands (all phases shipped) or is superseded/frozen, move the file to `context/` (load-bearing reference / provenance material) or `investigations/` (post-mortems / one-time audits) so `feature-notes/` stays a clean "what's still on the table" view. Keep the date prefix when moving (citation sweep is a pure path-substitution); investigate-destination precedent (`aggregate-crypto-rewards-review-analysis.md`) uses non-prefixed names with a `**Date** / **Branch** / **Plan**` metadata block instead.
- `context/` holds load-bearing reference material and frozen artifacts cited by active maintenance docs (e.g. landed-RFC provenance for tax rules, frozen audit snapshots of deleted files).
- `investigations/` holds completed post-mortems and one-time analysis notes.
- `plans/completed/` is the archive for executed implementation plans; `migrations/` for one-time migration records.

1. Every downloaded external source mirrored under `docs/.../official/` must have a corresponding `sources.md` entry that records the official URL, issuing date, effective date (when the source takes legal effect; defaults to issuing date if not separately specified), superseded date (when replaced by a newer enactment; `-` when still current), retrieval date, purpose, and the exact articles, sections, annexes, chapters, or clauses relied on. Publication date alone does not determine when a law applies; a source published in 2023 may take effect in 2025, and a 2024 enactment may supersede a 2021 law. The effective/superseded chain is what determines which sources govern a given fiscal year. Each time an archived external source is used for analysis, implementation, or user-facing advice, check the official source first for a newer version. If a newer official version exists, archive it in the correct folder and update the manifest before relying on that source.

2. Tax treatment decision points live in `docs/maintenance/tax/decision_points/<year>.md`, one file per fiscal year. Each file is a self-contained snapshot listing which laws are in effect for that year (with effective/superseded dates), the per-country decision-point table, and source references. A `README.md` index lists all fiscal years and provides a template for creating new ones. When starting a new fiscal year, copy the latest year file, re-verify each decision point against current sources in `docs/maintenance/tax/laws/`, and update the laws-in-effect table. When a law or interpretation has not changed, the new file may reference the prior year for unchanged rows rather than repeating full rationale.

   Each `<year>.md` has a machine-readable companion `<year>.toml` in the same directory. The TOML is the runtime sidecar consumed by `config.py`; it encodes law-driven boolean flags per country (e.g. `exclude_loan_repayment_gains`). When a decision point changes (new year or amended law), update **both** files together: the `.md` for the human-readable rationale and the `.toml` for the machine-readable flags. `config.ini` does not contain law-driven flags; those live exclusively in the TOML sidecar.

3. AT guidance documents (folheto, PIVs, ofícios circulados) may cite CIRS paragraph numbers from before a renumbering amendment. When consulting any AT guidance that cites a CIRS paragraph number, cross-check the number against the current consolidated CIRS PDF **mirrored at `docs/maintenance/tax/laws/pt/official/`** (file `cirs_consolidado_<ultima-atualizacao-date>.pdf`; provenance and the current redação tag in `docs/maintenance/tax/laws/pt/sources.md`, entry 4). The CPPT (`cppt_consolidado_*.pdf`, entry 5) and CIS (`cis_consolidado_*.pdf`, entry 6) consolidated codes are mirrored alongside it for the same offline-verification reason (reclamação/impugnação prazos; CLS legal base). The consolidated PDF includes inline annotations such as "(Anterior n.º 7 - Lei n.º 31/2024)" that make renaming explicit. Whenever a renumbering is discovered, update all affected references in `sources.md` "Relevant provisions consulted" fields, decision point notes, and `platform-divergences.md` in the same pass. The consolidated CIRS is always the authoritative current numbering; AT documents are authoritative on interpretation but may lag on paragraph numbering.

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

6. **External-report naive dates are jurisdiction-local, not UTC.** Koinly's Capital Gains / Other Gains / Income `Date` columns are wall-clock local time (mainland-Portugal WET/WEST), proven by their ~0h winter / ~+1h summer offset versus the explicit-UTC Transaction History twins. Never assume a naive date equals UTC: a `strptime` format literal like ` UTC` does not populate `tzinfo`, so the naive and explicit-UTC formats are indistinguishable on `parsed.tzinfo`. Localize naive dates to the jurisdiction IANA zone (`IANA_TIMEZONE` in `config.ini` `[TAX JURISDICTION]`, resolved once at config load into a `ZoneInfo` on `TaxJurisdictionConfig.timezone` and threaded to the parser; default `Europe/Lisbon` for PT), convert to UTC at ingestion via `zoneinfo` (which owns DST transitions historically; never hand-code transition days), and leave explicit-UTC dates unchanged. A zone is MANDATORY to localize naive dates, so the application enforces a STRICT fail-fast: when crypto data is present and the timezone cannot be resolved, the crypto-loading boundary `_load_crypto_tax_report` (`main.py`) raises `ConfigurationError` - this covers BOTH a configured jurisdiction whose timezone is `None` (any non-PT country without `IANA_TIMEZONE`; PT auto-deduces `Europe/Lisbon`) AND the no-config path (`jurisdiction is None`, e.g. `config.ini` absent). `_main` propagates that `ConfigurationError` unwrapped (it is not degraded to "continue without crypto" nor wrapped into `ReportGenerationError`). The loader `load_koinly_crypto_report` itself stays a pure parser, unit-testable with `jurisdiction=None`; the no-zone silent-UTC-stamp is a deliberate library affordance in `parse_koinly_datetime`, NOT the application default. This keeps every calendar-day cross-report match key (DP-014 payment match, derivatives dedup, OGR override) on the true-UTC day, , and `docs/maintenance/koinly_guidelines.md` Section 5.

