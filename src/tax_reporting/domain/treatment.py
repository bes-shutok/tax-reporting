"""``Treatment`` enum for the TH-anchored transaction state machine.

Closed six-value ``Treatment`` enum that classifies what a Transaction History
(TH) row *is* for tax purposes. Consumed by ``resolve_treatment``, the single
source of truth for treatment identification in the live crypto pipeline.

Plan: ``docs/history/plans/2026-07-06-th-tx-view-phase-b.md`` (Task 1).
RFC: ``docs/history/feature-notes/2026-06-20-th-anchored-transaction-state-machine.md``
(un-shelved 2026-07-05; Phase B of the five-phase rollout recorded there).

Member-to-rule mapping (cited per Invariant 1 of the plan):

- ``SPOT_DISPOSAL`` - default treatment for disposal-shaped rows (a populated
  sending side) whose tag matches no other treatment. Backed by CIRS
  art. 10(1)(k) (general capital-gains disposal rule for crypto assets).
- ``PAYMENT`` - DP-014: payments/proceeds tags (``payment``, ``card payment``)
  routed via the existing ``payment_proceeds.py`` classifier.
- ``LOAN_REPAYMENT`` - DP-001: non-taxable loan-repayment disposal scope
  (CIRS art. 10(20)). Excludes the borrowing-side ``loan`` tag (Invariant 9);
  only ``loan repayment`` matches.
- ``DERIVATIVES_CLOSE`` - DP-010 / DP-012: crypto-derivatives disposal routed
  to Anexo G Quadro 13 (operation code G51). Tag set is injected from
  ``docs/maintenance/tax/derivatives_labels/<provider>_<year>.json``.
- ``REWARD_AIRDROP_LP`` - DP-005 / PT-C-005: reward/airdrop/lending income
  classification; tag set mirrors the reward/airdrop/lp branches in
  ``token_origin.py``.
- ``OTHER`` - non-disposal rows (acquisitions, transfers, loan-creation) and
  any TH row whose tag is unrecognized. ``OTHER`` is the explicit landing for
  unmatched rows so the resolver is total (Invariant 2). It is NOT an
  optional/sentinel value: it carries the same observable weight as the other
  five values and exists to make unmatched rows loud rather than silent.

The snake-case string values (e.g. ``"spot_disposal"``) match the
``WalletKind.CEX = "cex"`` convention used in ``domain/transaction.py`` and
serve as stable serialization references. Adding a new value requires amending
Invariant 1 of the Phase B plan AND extending the matrix test.
"""

from __future__ import annotations

from enum import Enum


class Treatment(Enum):
    """Closed six-value treatment classification for a Transaction History row.

    See module docstring for the rule-to-member mapping and the role of
    ``OTHER`` as the explicit landing for unmatched rows.
    """

    SPOT_DISPOSAL = "spot_disposal"
    PAYMENT = "payment"
    LOAN_REPAYMENT = "loan_repayment"
    DERIVATIVES_CLOSE = "derivatives_close"
    REWARD_AIRDROP_LP = "reward_airdrop_lp"
    OTHER = "other"
