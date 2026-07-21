"""``TreatmentConfig`` and ``resolve_treatment`` for the TH-anchored state machine.

The live crypto pipeline calls ``resolve_treatment`` at every per-treatment
stage (OGR override keying, payment-proceeds filter, loan-affected asset
discovery, derivatives dedup, reward/airdrop/LP identification, and TH-row
Transaction construction); the resolver is the single source of truth for
treatment identification. Phase E deleted the last legacy adapters that
branched on tag literals, so the frozenset defaults below are no longer
mirrored from a parallel classifier (Family D: single source of truth).

Plan origin: ``docs/history/plans/2026-07-06-th-tx-view-phase-b.md`` (Tasks 2 + 3).
RFC: ``docs/history/context/2026-06-20-th-anchored-transaction-state-machine.md``
(un-shelved 2026-07-05; Phase B of the five-phase rollout recorded there).

Default tag sets (Invariant 8): the five non-derivatives defaults are the
canonical tag matrix consulted by ``resolve_treatment``. Phase B originally
derived each set verbatim from a Phase-D legacy classifier's tag tuple so
the per-treatment delegation flip would not change behavior; Phase E
(``docs/history/plans/completed/2026-07-10-th-tx-view-phase-e.md``) deleted those
legacy classifiers, so these frozensets are now the single source of truth:

- ``_DEFAULT_PAYMENT_TAGS``: the canonical ``payment`` / ``card payment`` pair
  routed to ``Treatment.PAYMENT`` (DP-014).
- ``_DEFAULT_LOAN_REPAYMENT_TAGS``: ``{"loan repayment"}`` only. The
  borrowing-side ``"loan"`` tag is principal creation (collateral deposit),
  not a repayment disposal, so Invariant 9 excludes it from the repayment
  default. ``discover_loan_affected_assets`` still needs ``"loan"`` to keep
  borrow-only assets in the FIFO rebuild (Invariant 11); that clause lives
  in ``crypto_fifo/parsing.py``, not in this default.
- ``_DEFAULT_REWARD_TAGS`` / ``_DEFAULT_AIRDROP_TAGS`` / ``_DEFAULT_LP_TAGS``:
  the reward / airdrop / lp tag tuples routed to ``Treatment.REWARD_AIRDROP_LP``.

``derivatives_tags`` (Invariant 5) defaults to an empty frozenset. The
authoritative derivatives labels live in
``docs/maintenance/tax/derivatives_labels/<provider>_<year>.json`` and are
injected by the production caller; the resolver module MUST NOT hardcode any
value from that JSON (Family D - single source of truth).

Coercion contract: the constructor accepts any iterable of strings for each
field and normalizes it to a ``frozenset`` via ``__post_init__``. This matches
the "accept and normalize" pattern of ``payment_proceeds.py`` and lets a
careless caller pass a list without breaking.

``resolve_treatment`` (Task 3) is a pure free function that takes a Phase A
``Transaction`` and a ``TreatmentConfig`` and returns a ``Treatment`` member.
It is total (Invariant 2), case-insensitive on both sides (Invariant 4), and
applies a fixed precedence order when a tag matches two configured sets
(Invariant 6).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from tax_reporting.domain.transaction import Transaction
from tax_reporting.domain.treatment import Treatment

# Canonical payment / card-payment pair routed to ``Treatment.PAYMENT``
# (Invariant 8; DP-014).
_DEFAULT_PAYMENT_TAGS: frozenset[str] = frozenset({"payment", "card payment"})

# ``"loan repayment"`` only (Invariant 9). The borrowing-side ``"loan"`` tag is
# principal creation (collateral deposit), NOT a repayment disposal; only
# ``"loan repayment"`` matches the DP-001 non-taxable scope (CIRS art. 10(20)).
_DEFAULT_LOAN_REPAYMENT_TAGS: frozenset[str] = frozenset({"loan repayment"})

# Reward-tag tuple (Invariant 8). The ``"realized gain"`` entry overlaps the
# production koinly_2025 derivatives labels JSON; the resolver precedence
# (Task 3, Invariant 6) pins the overlap to ``DERIVATIVES_CLOSE`` once the
# JSON set is injected.
_DEFAULT_REWARD_TAGS: frozenset[str] = frozenset({"reward", "cashback", "realized gain"})

# Airdrop tag set (Invariant 8).
_DEFAULT_AIRDROP_TAGS: frozenset[str] = frozenset({"airdrop"})

# LP provision / withdrawal tag pair (Invariant 8).
_DEFAULT_LP_TAGS: frozenset[str] = frozenset({"liquidity in", "liquidity out"})


@dataclass(frozen=True)
class TreatmentConfig:
    """Frozen bundle of case-folded tag frozensets consulted by the resolver.

    Six fields, all ``frozenset[str]``:

    - ``payment_tags``: tags routed to ``Treatment.PAYMENT`` (DP-014).
    - ``loan_repayment_tags``: tags routed to ``Treatment.LOAN_REPAYMENT``
      (DP-001). Excludes the borrowing-side ``"loan"`` tag (Invariant 9).
    - ``derivatives_tags``: tags routed to ``Treatment.DERIVATIVES_CLOSE``
      (DP-010 / DP-012). Defaults to empty; production injects the JSON set.
    - ``reward_tags`` / ``airdrop_tags`` / ``lp_tags``: tags routed to
      ``Treatment.REWARD_AIRDROP_LP`` (DP-005 / PT-C-005).

    The constructor accepts any iterable of strings for each field and
    normalizes it to a ``frozenset`` via ``__post_init__`` (coercion, not
    rejection), so a caller may pass a list without breaking.
    """

    payment_tags: frozenset[str] = field(default_factory=lambda: _DEFAULT_PAYMENT_TAGS)
    loan_repayment_tags: frozenset[str] = field(default_factory=lambda: _DEFAULT_LOAN_REPAYMENT_TAGS)
    derivatives_tags: frozenset[str] = field(default_factory=frozenset)
    reward_tags: frozenset[str] = field(default_factory=lambda: _DEFAULT_REWARD_TAGS)
    airdrop_tags: frozenset[str] = field(default_factory=lambda: _DEFAULT_AIRDROP_TAGS)
    lp_tags: frozenset[str] = field(default_factory=lambda: _DEFAULT_LP_TAGS)

    def __post_init__(self) -> None:
        """Coerce each field to ``frozenset`` (accept iterable, normalize).

        Uses ``object.__setattr__`` because the dataclass is frozen. This is
        the sole normalization point at construction time; the resolver's
        case-insensitive match logic lives in ``resolve_treatment`` (Task 3).
        """
        object.__setattr__(self, "payment_tags", frozenset(self.payment_tags))
        object.__setattr__(self, "loan_repayment_tags", frozenset(self.loan_repayment_tags))
        object.__setattr__(self, "derivatives_tags", frozenset(self.derivatives_tags))
        object.__setattr__(self, "reward_tags", frozenset(self.reward_tags))
        object.__setattr__(self, "airdrop_tags", frozenset(self.airdrop_tags))
        object.__setattr__(self, "lp_tags", frozenset(self.lp_tags))


def _normalize_tag(value: str | None) -> str:
    """Strip + lower-case ``value`` (the SOLE normalization point).

    Invariant 4: both the row's tag AND every member of every config
    frozenset are normalized by this helper before any comparison. Mirrors
    ``payment_proceeds.py`` line 317 and ``crypto_fifo/parsing.py`` line 71
    (byte-identical patterns or a shared helper per CLAUDE.md).

    Returns ``""`` for ``None`` or empty/whitespace-only input so the
    disposal-default branch keys off an empty normalized string.
    """
    if not value:
        return ""
    return value.strip().lower()


def resolve_treatment(transaction: Transaction, config: TreatmentConfig) -> Treatment:
    """Classify a Phase-A ``Transaction`` into a ``Treatment`` member.

    Pure free function: no I/O, no logging, no mutation of inputs. Total
    (Invariant 2): returns a ``Treatment`` member for every input that
    satisfies the Phase-A ``Transaction`` constructor; never returns ``None``
    and never raises on real Koinly data.

    Invariants honored:

    - Invariant 2 (Totality): the ``OTHER`` value is the explicit landing for
      unmatched rows so the resolver never returns ``None`` or raises.
    - Invariant 3 (Disposal default): the default branch keys off
      ``row.sending_currency is not None`` -> ``SPOT_DISPOSAL``; ``None`` ->
      ``OTHER``. The default is consulted ONLY when no special tag matches;
      special tags override regardless of side. The branch does NOT consult
      ``Type`` and does NOT consult ``receiving_currency`` (the disposal
      signal is the sending-side shape, not the Type name).
    - Invariant 4 (Normalization): ``_normalize_tag`` is the SOLE
      normalization point. It is applied to both ``row.tag`` and every member
      of every config frozenset via a single comprehension; no inline
      ``.strip().lower()`` at any other call site.
    - Invariant 5 (No hardcoded derivatives tags): ``derivatives_tags`` is
      injected via config; this module contains NO derivatives label string
      literals.
    - Invariant 6 (Precedence, fixed in code): when a tag matches two
      configured sets, the resolver consults them in this exact order
      (highest first):

          ``LOAN_REPAYMENT`` > ``PAYMENT`` > ``DERIVATIVES_CLOSE`` >
          ``REWARD_AIRDROP_LP`` > ``SPOT_DISPOSAL`` (default for
          disposal-shaped) > ``OTHER``.

      Defaults do not overlap among the five non-derivatives sets, but
      ``"realized gain"`` (in ``_DEFAULT_REWARD_TAGS``) overlaps the
      production koinly_2025 derivatives JSON; the precedence pins the
      overlap to ``DERIVATIVES_CLOSE`` once the JSON set is injected.

    Args:
        transaction: A Phase-A ``Transaction`` whose ``row.tag`` and
            ``row.sending_currency`` drive the classification. The other
            row fields (including ``row.type``) are ignored; the disposal
            signal is the sending-side shape, not the Type name.
        config: A ``TreatmentConfig`` whose six frozensets supply the
            case-insensitive tag sets. Defaults match the existing
            precedent constants (Invariant 8); production callers inject
            ``derivatives_tags`` from the JSON labels file (Invariant 5).

    Returns:
        A ``Treatment`` member. Never ``None``; never raises on any input
        that satisfies the Phase-A constructor.
    """
    normalized_tag = _normalize_tag(transaction.row.tag)

    # Invariant 6 precedence order (highest first). ``_normalize_tag`` is
    # applied to every config member so case and whitespace differences on
    # EITHER side of the comparison are equivalent (Invariant 4
    # bidirectional). The non-derivatives defaults do not overlap, but the
    # explicit ordering keeps the resolver deterministic if a caller adds an
    # overlapping custom tag and pins the production-overlap case
    # (``"realized gain"`` -> DERIVATIVES_CLOSE once injected).
    if normalized_tag and normalized_tag in {_normalize_tag(t) for t in config.loan_repayment_tags}:
        return Treatment.LOAN_REPAYMENT
    if normalized_tag and normalized_tag in {_normalize_tag(t) for t in config.payment_tags}:
        return Treatment.PAYMENT
    if normalized_tag and normalized_tag in {_normalize_tag(t) for t in config.derivatives_tags}:
        return Treatment.DERIVATIVES_CLOSE
    if normalized_tag and (
        normalized_tag in {_normalize_tag(t) for t in config.reward_tags}
        or normalized_tag in {_normalize_tag(t) for t in config.airdrop_tags}
        or normalized_tag in {_normalize_tag(t) for t in config.lp_tags}
    ):
        return Treatment.REWARD_AIRDROP_LP

    # Invariant 3: default branch keys off the sending-side shape, NOT off
    # ``Type`` and NOT off ``receiving_currency``. A populated sending side
    # is a disposal-shaped row; an empty sending side is an
    # acquisition/transfer/loan-creation row.
    if transaction.row.sending_currency is not None:
        return Treatment.SPOT_DISPOSAL
    return Treatment.OTHER
