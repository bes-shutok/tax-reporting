# Proposal: TH-anchored transaction model for crypto reporting

- **Status:** SHELVED (exploratory RFC; to be set aside after this write-up)
- **Date:** 2026-06-20
- **Branch:** 2026-06-19-doc-hierarchy-migration
- **Related:** DP-014 payment-proceeds correction; review findings #5, #10, #11, #14; `crypto_fifo.py` (loan-affected FIFO rebuild)

## Purpose

A standalone record of the "state machine per transaction" idea discussed while
addressing the DP-014 code review, so the reasoning and the real-data examples
that motivate it are not lost when we shelve it. Per the discussion, this is
written and then set aside; it is not an active plan.

## The problem in one sentence

The crypto pipeline joins three Koinly reports (Capital Gains, Other Gains,
Transaction History) by coarse, timezone-naive `(date, asset, wallet)` keys
rather than by transaction identity, so a single disposal event can be split,
duplicated, or paired with the wrong counterpart across reports, and the code
cannot tell.

## The three reports and what each carries

| Report | Date column | Zone | Carries |
|---|---|---|---|
| Capital Gains (CG) | `Date Sold` `DD/MM/YYYY HH:MM` | naive (treated as UTC by the code, actually local) | per-FIFO-lot cost, proceeds, gain, asset, wallet, holding period. No tag, no type, no tx id. |
| Other Gains (OGR) | `Date` `DD/MM/YYYY HH:MM` | naive (same) | per-row realized P&L (`Value (EUR)` is the gain/loss magnitude, signed by `Type`), asset, wallet, amount. Profit/Loss only. |
| Transaction History (TH) | `Date` `YYYY-MM-DD HH:MM:SS UTC` | explicit UTC | Type, Tag, Sending/Receiving wallets+amounts+cost basis, `Gain (EUR)`, `Net Value (EUR)`, `TxSrc`, `TxDest`, `TxHash`, Description. This is the only report with a transaction id and a type/tag. |

TH is the natural anchor: it is the only report that identifies what a
transaction *is* (type and tag) and *which* transaction it was (`TxHash` /
`TxSrc` / `TxDest`).

## Weaknesses exposed by the current design (with real-data evidence)

1. **The match key is not a transaction id.** CG, OGR, and the DP-014 payment
   matcher all join on variants of `(date, asset, wallet[, amount])`. Two
   distinct disposals that share that tuple are indistinguishable. This is the
   root of review finding #14 (the count-equality gate cannot tell a
   payment-origin CG row from a coincidental zero-proceeds row) and of the
   shaky "NECESSARILY spurious" premise in finding #5.

2. **One disposal event maps to many CG lots, but the OGR override assumes 1:1.**
   Measured on `resources/source/koinly2025/`: **226 of 473** CG
   `(date, asset, wallet)` keys contain multiple lots, up to 121. Concrete:
   - `2025-01-26 ETH / Kraken` -> 121 lots
   - `2025-02-01 USDT / ByBit` -> 110 lots
   - `2025-01-13 USDT / ByBit` -> 109 lots
   - `2025-06-14 TIA / Kraken` -> 62 lots
   - `2025-12-21 IBERA / Ledger Berachain (BERA)` -> 39 lots

   `_apply_ogr_direction_override` (`ogr_handler.py:426-501`) looks each CG lot
   up in the OGR index by `(date, asset, wallet)` and writes
   `proceeds = cost + final_gain_loss` per lot. If an OGR key ever matched a
   multi-lot disposal, the OGR gain would be added to every lot before
   aggregation, multiplying it by the lot count. Today this is latent only
   because **0 CG keys share a key with any OGR Profit/Loss row** in the current
   data; the structural assumption is unguarded.

3. **Dates are timezone-naive and assumed UTC, but are actually local.**
   Cross-referencing unambiguous CG/TH disposal pairs (TH is explicit UTC): the
   CG-minus-TH hour offset is ~0 in winter (Jan-Mar, Nov-Dec) and ~+1h in summer
   (Apr-Oct), with the spring-forward jump visible in late March and the
   fall-back in late October. That is mainland Portugal (WET = UTC+0 in winter,
   WEST = UTC+1 in summer). So CG `Date Sold` and OGR `Date` are Portuguese
   local time; the code's `parse_koinly_datetime` assuming naive = UTC
   (`koinly_parser.py:117-118`) is wrong. In summer a disposal recorded
   00:00-01:00 local maps to the previous UTC day, so any calendar-day match key
   can drift by a day. The DP-014 payment match happens to work on the current
   EUROC/Wirex case only because that disposal does not sit in that window.

4. **The OGR proceeds formula `proceeds = cost + gain` is an identity that hides
   a correspondence assumption.** It is correct only when the matched CG lot's
   cost basis is the same basis Koinly used to compute the OGR gain. For
   loan-affected assets whose FIFO we rebuild from TH (different basis from
   Koinly's pool), `our_cost + koinly_gain` is internally inconsistent. Again
   latent (0 matches), but the formula is correct-by-coincidence, not by
   construction.

5. **Payment and OGR P&L are reasoned about as if mutually exclusive, but
   nothing enforces it.** The re-zero block (finding #5/#10/#11) exists to undo
   an OGR mutation on an originally-zero-proceeds Payment row. In the current
   data there are 0 Payment/OGR key collisions, so the question is moot, but the
   pipeline has no positive way to know a CG row is a Payment (the tag lives only
   in TH).

## The proposal: a unified Transaction view anchored on TH

Build one `Transaction` object per disposal (and per acquisition) sourced from
the TH row, then hang the CG lots and the OGR P&L off it by transaction id
rather than by date/asset/wallet. Treatment is resolved from the TH `Type` and
`Tag`, not inferred from proceeds magnitude or count arithmetic.

Sketch of the shape:

```
TH row (authoritative: type, tag, net value, tx id, UTC instant)
  |
  +-- correlates by TxHash / TxSrc-TxDest / (UTC instant, asset, wallet, amount)
      (transaction identity, not calendar day)
  |
  +-- CG lots belonging to this disposal (one event -> N lots, summed for reporting)
  +-- OGR P&L row belonging to this disposal (one event -> one P&L, or none)
  +-- resolved treatment from Type + Tag:
        Payment / Card Payment -> valor de realizacao = disposal FMV (DP-014)
        loan repayment        -> non-taxable (DP-001)
        derivatives close     -> art. 10(1)(e), Quadro 13 (DP-010/DP-012)
        spot disposal         -> art. 10(1)(k), 365-day rule
        reward / airdrop / LP -> income or deferred per DP-005/PT-C-005
```

Matching becomes: for each TH disposal, find its CG lots and OGR row by
transaction id (and a normalized UTC instant as a tiebreaker), then compute the
reported gain from the joined state. The proceeds question becomes "what is
this transaction's realization value" rather than "reconstruct proceeds from a
lot cost plus a position-level gain."

## What it would fix

- **Challenge 1 (formula):** the OGR P&L attaches to the disposal event, not to
  individual lots, so it is applied once; proceeds is the event's realization
  value, not `lot_cost + position_gain`.
- **Challenge 2 (Payment vs OGR):** each transaction has one resolved treatment
  from its TH type/tag, so a Payment and a derivatives P&L cannot be conflated;
  a key collision between two different transactions is resolved by tx id.
- **Review #14 (count gate):** payment identity comes from the TH tag directly,
  not from count arithmetic over a key.
- **Review #5/#10/#11 (re-zero block):** the OGR-mutates-a-Payment-row problem
  disappears because OGR P&L no longer overrides in-place CG lots; the joined
  model computes treatment from type, so there is no spurious mutation to undo.
- **Timezone:** one normalization point (TH instant in UTC) replaces per-report
  calendar-day keys; naive CG/OGR dates are localized to the jurisdiction zone
  and converted to UTC once, at ingestion.

## This discipline already half-exists

The loan-affected FIFO rebuild in `crypto_fifo.py` already correlates by TH
transaction identifier, not by day-level date (cross-asset carry-over matches by
TH tx id; per CLAUDE.md "Cross-asset FIFO carry-over matches by TH transaction
identifier, never by day-level date alone"). The proposal is to extend that
discipline from loan-affected assets to all crypto disposals, making TH the
single source of truth for transaction identity and treatment across the whole
pipeline.

## Cost and why this is shelved (YAGNI)

- In the current data the OGR override matches 0 CG keys, there are 0
  Payment/OGR collisions, and the only live cross-report match (DP-014
  EUROC/Wirex) works. Most of the failure modes above are latent, not active.
- A full re-architecture keyed on TH transaction id is a large change (new
  domain object, re-plumbing of CG parsing, OGR handling, and the payment
  corrector; re-baseline of the test suite and the Excel outputs).
- The marginal value today is low because the current data does not exercise the
  multi-lot-OGR or Payment/OGR-collision paths.

So: write it down, set it aside, and revisit only if a future Koinly export
produces a wrong number traceable to one of the latent cases above.

## What to do now instead (the smaller, warranted fixes)

These are independent of the shelved re-architecture and address the confirmed
risks:

1. **Timezone normalization (do this).** Stop assuming naive dates are UTC.
   Localize naive CG/OGR dates to the jurisdiction's IANA zone
   (`TaxJurisdictionConfig.country` -> e.g. `Europe/Lisbon`) using `zoneinfo`,
   which handles DST transitions historically; then convert to UTC for all
   cross-report match keys. This removes the manual "lookup transition days" or
   "check each spring/autumn day" burden: the tz database already knows the
   Portugal transitions (verified by the DST shift visible in the current data).
   Policy, per the user: a date with no explicit zone is local time even when it
   coincides with UTC.
2. **Document the OGR 1:1 assumption (do this).** Add an explicit guard or
   review flag in `_apply_ogr_direction_override` so a multi-lot key that
   matches an OGR row is surfaced rather than silently over-counted, until the
   state-machine model exists.
3. **Keep the review-fix work.** Findings #4, #7, #8, #9, #13 (robustness) and
   the test-quality/doc fixes (#1, #2, #3, #15-#21) are independent of this
   design question and can proceed.

## Deferred review findings (owned here)

Disposition of the 2026-06-20 branch review findings
(`docs/history/reviews/2026-06-20-branch-review-doc-hierarchy-migration.md`)
relative to this RFC:

- **Owned here (deferred, not patched piecemeal):** #5 (re-zero "NECESSARILY
  spurious" premise), #10 (re-zero snapshot/restore simplification), #11
  (`crypto_reporting.py` inline re-zero orchestration debt), and #14
  (count-equality gate checks body counts, not payment origin). A TH-anchored
  transaction model structurally fixes all four (see weakness 1, weakness 5, and
  "What it would fix" above); patching them on the migration branch would be
  churn the state machine later removes. The "Related" line above is therefore
  an ownership declaration, not just an association.
- **Proceeded independently (fixed on the migration branch):** #1, #2, #4, #7,
  #8, #9, #13, #15-#21.
- **Folded into the timezone-normalization plan:** #3 (the re-zero index-vs-key
  test in `tests/unit/application/test_crypto_reporting.py`), co-located with
  that plan's `test_crypto_reporting.py` edits.
- **Separate refactor proposal:** #6 (module split) and #12 (`safe_cell_value`
  layer leak) - pure code structure, not transaction-identity concerns.

## Triggers to un-shelve

- A Koinly export where an OGR Profit/Loss row shares a key with a multi-lot CG
  disposal (would over-count the gain today).
- A Payment disposal and an OGR P&L row on the same key (would force the re-zero
  block's contested premise).
- A summer-time disposal in the 00:00-01:00 local window that mis-matches its TH
  twin by a day.
- Any disposal whose rebuilt (TH) cost basis meets an OGR row (inconsistent
  `our_cost + koinly_gain`).

## Open questions

- Does Koinly populate `TxHash` / `TxSrc` / `TxDest` reliably enough across all
  wallets (Kraken, ByBit, Ledger, SUI, Wirex) to use as the primary correlation
  id, or is `(UTC instant, asset, wallet, amount)` still needed as a fallback?
- For derivatives, does the TH row carry enough (Type, tx id) to route
  per-transaction under Quadro 13 without the current OGR-type classifier?
