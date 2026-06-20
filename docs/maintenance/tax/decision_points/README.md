# Decision Points: Directory Index

This directory contains per-fiscal-year snapshots of which laws are in effect and how they drive reporting behavior.
Each file is self-contained: it records the source set active for that year and the resulting decisions, so a future
reader can reproduce the reasoning without chasing references.

## Table of Contents

| File | Fiscal Year | Summary |
|------|-------------|---------|
| [2025.md](2025.md) | FY2025 (PT IRS filed in 2026) | Initial decision points: loan repayment exclusion (CIRS art. 10(20)), crypto-to-crypto deferral |

## Creating a New Fiscal Year File

1. Copy the latest year file: `cp 2025.md <new-year>.md`
2. Copy the corresponding TOML sidecar: `cp 2025.toml <new-year>.toml` and update `[meta].fiscal_year` to the new year.
3. Update the header: change "Fiscal Year" and "Valid for" to the new year.
4. Update "Laws in Effect": re-verify each source against its official URL. Add new sources; mark superseded ones.
5. Re-verify each decision point row against the current year's sources. Update the PT column if the law changed. Update the TOML flags to match.
6. Update the Change Log with the creation date and a summary of what changed from the prior year.
7. Add a row to the Table of Contents in this README.

## Verification Checklist When Updating a Decision Point

When verifying or updating a decision point that cites a CIRS article:

1. Open the cited archived source (AT folheto, PIV, ofício) and locate the cited paragraph.
2. Open the current consolidated CIRS PDF (`docs/maintenance/tax/laws/pt/crypto-tax/official/cirs_2025-07_code_consolidated.pdf`) and locate the same provision by searching for the legal text: not by paragraph number alone.
3. Check whether the consolidated PDF shows a renumbering annotation such as `(Anterior n.º 7 - Lei n.º 31/2024, de 28 de junho)`. If so, the AT document is using the old number; use the current number from the consolidated PDF.
4. If a discrepancy is found, update all affected references in the same pass: `sources.md` "Relevant provisions consulted" fields, decision point notes, and `platform-divergences.md`.
5. Add a note to the decision point row (in the Notes column) that the AT source uses the old paragraph number, to prevent future confusion.

## Canonical Structure Template

Each year file must follow this structure:

```markdown
# Decision Points: Fiscal Year <YYYY>

Valid for: <YYYY> calendar year (PT IRS filing in <YYYY+1>).
Last verified: <date>.

## Laws in Effect

| Source | Published | Effective | Superseded | Scope |
|--------|-----------|-----------|------------|-------|
| ...    | ...       | ...       | ...        | ...   |

Effective date rules:
- Empty Effective = immediately effective on publication date.
- Empty Superseded = still current as of this fiscal year.
- Superseded dates note when a source was replaced by a newer enactment.

## Decision Points

| # | Decision Point | PT | US | UK | DE | AU | Notes |
|---|---------------|----|----|----|----|----|----|
| DP-001 | ... | ... | ... | ... | ... | ... | ... |

## Source References

- PT: docs/maintenance/tax/laws/pt/crypto-tax/sources.md, docs/maintenance/tax/laws/pt/crypto-tax/platform-divergences.md
- EU: docs/maintenance/tax/laws/eu/crypto-tax/sources.md
- US: Rev. Rul. 2023-14 (not archived; verify before relying)
- UK: HMRC Cryptoassets Manual CRYPTO22100 (not archived; verify before relying)
- DE: EStG section 23 (not archived; verify before relying)
- AU: ITAA 1997 s 104-10, CGT Event A1 (not archived; verify before relying)

## Change Log

| Date | Change |
|------|--------|
| <date> | Initial decision points for FY<YYYY> |
```
