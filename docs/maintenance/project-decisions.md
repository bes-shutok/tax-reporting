# Project Decisions

Architecture and reporting decisions for this repository. Law-driven decisions are sourced per fiscal year in `docs/maintenance/tax/decision_points/`; this file records the stable engineering and reporting choices that do not change year to year.

## PD-001: Layered architecture

Domain-driven layering: `domain` -> `application` -> `infrastructure` -> `presentation`. Orchestration layers stay thin (about 500 lines); domain logic lives in dedicated services. See `README.md` for the full walkthrough.

## PD-002: FIFO per-wallet per-institution (CIRS art. 43 n.9)

Cost basis is matched first-in-first-out scoped per wallet and per institution, not globally. Engine lives in `crypto_fifo/`. Cross-asset FIFO carry-over matches by Transaction History identifier, never by day-level date alone.

## PD-003: Loan repayment gains excluded for PT

When `exclude_loan_repayment_gains=True`, loan-affected assets are excluded from Koinly CG parsing and rebuilt from Transaction History. Loan-affected assets are discovered from `"loan"` / `"loan repayment"` tags only (not `"loan fee"`).

## PD-004: Derivatives separated from spot

Derivatives/futures are split from spot into their own pipeline with an explicit OGR-vs-CG dedup step, then aggregated by `(disposal_date, asset, platform, holding_period)`. PT derivatives route to Anexo G Quadro 13, operation code G51.

## PD-005: Materiality and review gating

Post-aggregation, entries with `|gain/loss| < 1 EUR` are excluded. Zero-basis disposals are flagged for review only above `ZERO_BASIS_REVIEW_MIN_PROCEEDS` (default 10 EUR) and `ZERO_BASIS_REVIEW_THRESHOLD` (default 50). Partially-matched sells are never silently dropped; the placeholder-buy mechanism applies to the remaining quantity.

## PD-006: Optional crypto ingestion is non-blocking

Missing, mismatched-year, or unparseable Koinly input emits a warning and continues IB report generation without crypto data.

## PD-007: Law-driven flags in decision points TOML, not config.ini

`config.ini` holds only user preferences; law-driven flags (e.g. `exclude_loan_repayment_gains`) live in `docs/maintenance/tax/decision_points/<fiscal_year>.toml`, mirrored in the `.md` sidecar. A missing TOML for the configured `FISCAL_YEAR` fails fast at startup.

## PD-008: Per-lot review reasons re-evaluated at the aggregation boundary

Capital-gains entries are aggregated by `(disposal_date, asset, platform, holding_period)` before the user-visible row is rendered (Quadro 9.4 reports the disposal event, not the FIFO lot allocation; PT-C-025, PT-C-027). A single noisy zero-basis lot inside a material disposal must not poison the aggregated row's `Review flag`. Implementation: `_re_evaluate_aggregated_review()` in `application/crypto/aggregation.py` runs after `_aggregate_capital_entries()`. Gate (all three): `cost_eur > 0 AND proceeds_eur > 0 AND abs(gain_loss_eur) >= _MATERIALITY_THRESHOLD` (1 EUR). When the gate holds, the joined `review_reason` is split on `"; "`, zero-basis-family prefixes (`_ZERO_BASIS_REASON_PREFIXES`) are dropped, and the flag becomes `NO` if no parts survive. The more-severe "Zero acquisition cost with negative disposal proceeds" reason is NOT stripped (its prefix differs) because it flags a distinct fee-heavy liquidation / data anomaly whose guidance must survive aggregation.

Per-lot signal is preserved in `context.review_entries` and the per-lot DEBUG log (file handler at `DEBUG`; Bucket-C (DEVELOPER_ACTIONABLE class, pattern O) silent-data-loss aggregates stay WARNING on the console, while EXTRACT_SURFACED dedup/origin aggregates emit at INFO with their per-row detail surfaced in the extract per rule #7), and surfaced as Section 5 REVIEW REQUIRED on the Crypto Supplementary sheet; the re-evaluation only re-derives the user-visible aggregated row's flag and reason.

**Trade-off.** A maintainer seeing `review_reason` dropped at aggregation time might assume a bug and re-add the join; this PD is the record that the drop is deliberate. **Evidence (2026-07-21, 2025 export):** every aggregated disposal row correctly resolved to `Review flag = NO`, including the reward-derived rows whose non-zero aggregated cost confirmed the per-lot zero-basis noise was suppressed without losing the underlying signal (which remains on the Supplementary sheet). Specific portfolio figures are omitted here as personal data; see the underlying plan records for traceability. Plan of record: `docs/history/plans/completed/2026-07-15-review-flag-aggregation-boundary.md`.
