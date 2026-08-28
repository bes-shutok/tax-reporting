"""Semantic-equivalence comparator for on-chain TH validation (PD-010).

Compares two Transaction-History projections of the same on-chain activity -

- the PRODUCTION on-chain projection (``project_on_chain_transactions`` ->
  ``list[ProjectedThRow]``, carrier-row gas rule and the B5 GasBurn exception
  included), and
- the Koinly baseline's TH rows (raw ``read_koinly_rows`` dicts),

- and decides, per shared ``tx_hash``, whether they are semantically
equivalent per PD-010 (``docs/maintenance/project-decisions.md``):

1. net amounts per ``(tx_hash, asset, direction)`` bucket match within the
   8-decimal display tolerance, which SCALES with the number of Koinly rows
   feeding the bucket (each displayed cell is rounded to 8 decimals, so N
   rows accumulate less than N x 1e-8 of rounding error; the on-chain side is
   exact). Row cardinality is irrelevant - Koinly splits one claim into up to
   100 ``Reward`` rows and downstream correlation keys on
   ``(tx_hash, event_id)``.
2. every Koinly ``(Type, Tag)`` combo is compatible with the on-chain
   ``EventType`` via the fixed :data:`EVENT_COMPATIBILITY` table (and every
   on-chain event type is matched by at least one compatible combo).

Gas surface (the lossy Koinly gas renderings, PD-010 accepted-gap families):
Koinly = ``Tag=="Cost"`` rows' ``Sent Amount`` + every row's ``Fee Amount``;
on-chain = ``GasBurn`` ``sending_amount`` + carrier ``ProjectedFee`` amounts.
Both are summed per currency and compared with the SAME bucket rule.
``Cost`` rows and ``GasBurn`` rows are therefore exempt from the event-surface
type/amount comparison - their amounts are validated on the gas surface
instead (this is what lets a Reward claim + carrier fee match Koinly's
``Reward`` rows + one ``Cost`` row).

Real-baseline rendering-variance rules (Task 11 Phase-1 walk-forward tuning,
each confirmed against the real 2025 H1 data; PD-010 gas-rendering family
spirit - a rendering difference with an EXACT economic identity is
equivalence, not divergence):

1. **Ticker-case folding.** The same token renders under differently-cased
   tickers on the two sides (explorer ``iBGT`` vs Koinly ``IBGT``; likewise
   iBERA, stBGT, USDC.e, uniBTC, brBTC, yBGT/yBERA and the ``Bault-``/
   ``BAULT-`` and ``KODI``-prefixed LP tokens). Asset buckets are keyed by
   the case-folded symbol, so a case variance alone never diverges.
2. **Mirrored-row single counting.** Koinly renders ONE movement on BOTH
   sides of a single row when the counterparty is another tracked wallet or
   pool (same currency, equal displayed sent/received - the self-wallet
   ``transfer/`` and ``To pool``/``From pool`` echo rendering). Such a row
   contributes its amount ONCE, on the direction(s) the on-chain projection
   carries for that currency (both sides when the projection carries
   neither - the movement must stay surfaced).
3. **Gas folded into the native amount.** When the Koinly gas surface for a
   currency is entirely empty (no ``Cost`` row, no ``Fee Amount`` cell) and
   the native OUT bucket's Koinly total exceeds the on-chain amount by
   EXACTLY the on-chain gas (within the bucket tolerance), Koinly folded
   the gas INTO the displayed amount; both the event mismatch and the gas
   mismatch are explained and suppressed. When the Koinly gas surface is
   non-empty the fold is NOT applied (the gas would count twice).

This module contains NO parsing of its own: it reuses
``parse_koinly_decimal`` for Koinly amount cells and consumes the adapter's
``ProjectedThRow`` wrappers as-is (UL #45 - production readers only; no
DictReader-based CSV parsing anywhere in this package). A malformed Koinly
amount cell propagates the underlying ``ValueError`` (fail-loud: a silent
pass is the harness's failure mode).

Records carry the full per-tx context (event types, Koinly combos, gas-surface
class, zero-display flag, counterparties, assets) so the clustering step
(validation-harness Task 3) can build PII-free cluster signatures from the
records alone; the adapter and the ``koinly_combo_map`` vocabulary module stay
the only (Type, Tag) combo-vocabulary surfaces.

Plan: ``docs/history/plans/2026-08-18-on-chain-validation-harness.md`` (Task 2).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Final

from tax_reporting.application.koinly_combo_map import (
    event_type_of,
    koinly_tag,
    koinly_text,
    row_combo,
)
from tax_reporting.application.on_chain_th_adapter import ProjectedThRow
from tax_reporting.domain.on_chain_transaction import EventType, OnChainTransaction
from tax_reporting.infrastructure.koinly_parser import parse_koinly_decimal

__all__ = [
    "DISPLAY_TOLERANCE_PER_ROW",
    "EVENT_COMPATIBILITY",
    "AmountMismatch",
    "ComparisonResult",
    "KoinlyFeeSurface",
    "Presence",
    "Surface",
    "ThComparisonRecord",
    "TypeMismatch",
    "compare_projection",
]

#: Per-row display tolerance (PD-010): every Koinly TH amount cell is rendered
#: at 8 decimals, so ONE Koinly row's displayed amount can differ from the
#: exact on-chain value by up to 1e-8. The per-bucket tolerance is this
#: constant times ``max(1, koinly_rows_in_bucket)`` - see
#: :func:`_bucket_tolerance`.
DISPLAY_TOLERANCE_PER_ROW: Final = Decimal("0.00000001")

#: Fixed semantic-equivalence compatibility table (PD-010): for each on-chain
#: ``EventType``, the frozenset of Koinly ``(Type, Tag)`` combos that count as
#: an equivalent rendering of that event. This table is a VALIDATION-PACKAGE
#: constant (design invariant: no new Koinly vocabulary enters the frozen
#: adapter); it is frozen for the walk-forward protocol (PD-010 amendment)
#: after the Task-11 Phase-1 tuning.
#:
#: Notes:
#: - The LiquidityDeposit/LiquidityWithdraw entries deliberately differ from
#:   the adapter's ``EVENT_TYPE_TO_KOINLY`` tags: Koinly renders pool moves as
#:   ``transfer`` rows tagged ``To pool`` / ``From pool`` (confirmed against
#:   the real 2025 baseline; see plan Task 9).
#: - LiquidityDeposit/LiquidityWithdraw AMENDMENT (2026-08-22, PD-010
#:   amendment #2, user-approved): additionally accept ``exchange`` and the
#:   untyped ``crypto_deposit/""`` + ``crypto_withdrawal/""`` combos,
#:   mirroring ``Swap``. Koinly has no native liquidity Type, so the real
#:   baseline auto-renders pool operations as plain exchanges; the manual
#:   ``transfer/To pool`` marks (the user's abstract-pool workaround) cover
#:   only part of it. The original entries were frozen while the LP snapshot
#:   was still the synthetic placeholder, so pool txs classified as ``Swap``
#:   and matched via ``Swap``-vs-``exchange`` - the LP-snapshot population
#:   (2026-08-22) reclassified them and exposed the vocabulary gap. Amounts
#:   are still compared strictly; only the TYPE check widens, and
#:   ``crypto_deposit/Reward`` is deliberately NOT accepted (the reward legs
#:   of mixed deposit+claim txs stay surfaced as mismatches pending a
#:   classifier decision).
#: - ``GasBurn`` pairs with ``crypto_withdrawal/Cost`` per PD-010; both sides'
#:   gas rows are routed to the GAS-surface amount comparison (a Cost row is
#:   how Koinly renders gas - as a ``Cost`` row's ``Sent Amount`` or a ``Fee
#:   Amount`` cell - so their equivalence is an amount question, not a type
#:   question). The entry documents the PD-010 pairing and keeps the table
#:   complete for audit.
#: - ``Reward`` additionally accepts ``crypto_deposit/""``: the real 2025 H1
#:   baseline renders SOME reward deposits with an empty tag (both
#:   distributor and non-distributor claims, amounts matching exactly).
#: - ``Swap`` additionally accepts the untyped ``crypto_deposit/""`` +
#:   ``crypto_withdrawal/""`` row pair: the real 2025 H1 baseline renders
#:   SOME swaps as untyped deposit/withdrawal rows (amounts matching
#:   exactly). Every combo must still be covered and every event type still
#:   matched, so the widening only relaxes the TYPE check - amounts are
#:   compared as always.
#: - ``Unknown`` has an EMPTY set: an unclassified event is always divergent
#:   (the harness must surface it, never wave it through).
EVENT_COMPATIBILITY: Final[dict[EventType, frozenset[tuple[str, str]]]] = {
    EventType.Swap: frozenset({("exchange", ""), ("crypto_deposit", ""), ("crypto_withdrawal", "")}),
    EventType.Reward: frozenset({("crypto_deposit", "Reward"), ("crypto_deposit", "")}),
    EventType.GasBurn: frozenset({("crypto_withdrawal", "Cost")}),
    EventType.LiquidityDeposit: frozenset(
        {("transfer", "To pool"), ("exchange", ""), ("crypto_deposit", ""), ("crypto_withdrawal", "")}
    ),
    EventType.LiquidityWithdraw: frozenset(
        {("transfer", "From pool"), ("exchange", ""), ("crypto_deposit", ""), ("crypto_withdrawal", "")}
    ),
    EventType.Transfer: frozenset({("transfer", "")}),
    EventType.Unknown: frozenset(),
}

#: The literal Koinly tag marking a gas-rendering row (PD-010 gas surface).
_KOINLY_TAG_COST: Final = "Cost"

#: Type-safe sentinel for an amount cell that is present but carries no
#: currency (never a valid ticker, so it cannot alias a real asset bucket).
_MISSING_CURRENCY: Final = "MISSING"


class Surface(Enum):
    """Which comparison surface an amount bucket belongs to."""

    EVENT = "event"
    """Net-amount buckets keyed by ``(tx_hash, asset, direction)``."""

    GAS = "gas"
    """Gas-surface buckets keyed by ``(tx_hash, currency)`` (Cost rows,
    ``Fee Amount`` cells, ``GasBurn`` sending amounts, carrier fees)."""


class Presence(Enum):
    """On which side(s) of the comparison a tx hash appears."""

    SHARED = "shared"
    ON_CHAIN_ONLY = "on_chain_only"
    KOINLY_ONLY = "koinly_only"


class KoinlyFeeSurface(Enum):
    """How the Koinly side rendered the tx's gas (cluster-signature input).

    Values are the PD-010 signature vocabulary (plan Task 3): ``cost_rows``
    when gas rides ``Tag=="Cost"`` rows, ``fee_column`` when it rides ``Fee
    Amount`` cells, ``mixed`` when both, ``none`` when neither.
    """

    NONE = "none"
    COST_ROWS = "cost_rows"
    FEE_COLUMN = "fee_column"
    MIXED = "mixed"


@dataclass(frozen=True)
class TypeMismatch:
    """Per-tx ``(Type, Tag)`` incompatibility between the two projections.

    Attributes:
        on_chain_combos: The projected rows' ``(type, tag)`` combos on the
            EVENT surface (gas rows excluded - they are validated by amount).
        koinly_combos: The Koinly rows' ``(Type, Tag)`` combos on the EVENT
            surface (``Cost`` rows excluded).
        uncovered_koinly_combos: Koinly combos no on-chain event type
            explains (the actionable subset of ``koinly_combos``).
        unmatched_event_types: On-chain event types no Koinly combo matches.
    """

    on_chain_combos: frozenset[tuple[str, str]]
    koinly_combos: frozenset[tuple[str, str]]
    uncovered_koinly_combos: frozenset[tuple[str, str]]
    unmatched_event_types: frozenset[EventType]


@dataclass(frozen=True)
class AmountMismatch:
    """One bucket whose net amounts diverge beyond the display tolerance.

    Attributes:
        surface: Which surface the bucket belongs to.
        asset: Asset ticker (event surface) or gas currency (gas surface).
        direction: ``"in"`` / ``"out"`` on the event surface; ``None`` on the
            gas surface.
        on_chain_amount: The on-chain side's exact net amount for the bucket.
        koinly_amount: The Koinly side's summed displayed amount.
        tolerance: The bucket tolerance actually applied
            (``DISPLAY_TOLERANCE_PER_ROW * max(1, koinly_rows_in_bucket)``).
        zero_display: True iff the Koinly side CONTRIBUTED at least one row to
            the bucket, that contribution sums to exactly zero, and the
            on-chain side is non-zero - i.e. Koinly DISPLAYS a zero amount
            (the C7 ``"0,00000000"`` shape). An EMPTY cell (no contribution)
            is absence, not zero display, and keeps this False.
    """

    surface: Surface
    asset: str
    direction: str | None
    on_chain_amount: Decimal
    koinly_amount: Decimal
    tolerance: Decimal
    zero_display: bool


@dataclass(frozen=True)
class ThComparisonRecord:
    """One tx's comparison outcome (shared) or presence-partition entry.

    Shared-hash records with no :class:`TypeMismatch` and no
    :class:`AmountMismatch` are MATCHES (they land in
    :attr:`ComparisonResult.matched_tx_hashes`, not in ``divergent``).

    Beyond the mismatch details, the record carries the per-tx context the
    clustering step (validation-harness Task 3) needs to build PII-free
    cluster signatures from records alone: event types, Koinly combos, the
    gas-surface rendering class, the zero-display flag, counterparty
    addresses (resolved against the contract registry downstream), the
    assets touched, and the on-chain legs' token addresses (both checked
    against the LP snapshot downstream - review r1 F1).

    Attributes:
        tx_hash: The shared grouping key (on-chain hash; never an address).
        presence: Which side(s) the hash appears on. Presence records carry
            NO comparison details (``type_mismatch`` is ``None`` and
            ``amount_mismatches`` is empty).
        type_mismatch: The type-incompatibility detail, or ``None``.
        amount_mismatches: All bucket divergences, sorted for determinism.
        on_chain_event_types: ALL projected event types of the tx (including
            ``GasBurn``); empty for Koinly-only records.
        on_chain_combos: ALL projected ``(type, tag)`` combos (including the
            ``GasBurn`` row's); empty for Koinly-only records.
        koinly_combos: ALL Koinly ``(Type, Tag)`` combos (including ``Cost``
            rows); empty for on-chain-only records.
        koinly_fee_surface: How Koinly rendered the gas (signature input).
        zero_display: Whether ANY amount mismatch has ``zero_display=True``.
        on_chain_counterparties: Non-empty ``TxSrc``/``TxDest``-style
            addresses from the projected rows (registry lookup downstream).
        koinly_counterparties: Non-empty ``TxSrc``/``TxDest`` values from the
            Koinly rows.
        assets: Every asset/currency ticker either side mentions (LP-snapshot
            membership check downstream).
        token_addresses: Every leg token address the on-chain side's SOURCE
            transactions carry for this hash (the authoritative LP-snapshot
            discriminator; lower-cased membership check downstream - review
            r1 F1). Empty when no source transactions were supplied
            (Koinly-only records always; projection-only callers fall back to
            the asset identifiers).
    """

    tx_hash: str
    presence: Presence
    type_mismatch: TypeMismatch | None
    amount_mismatches: tuple[AmountMismatch, ...]
    on_chain_event_types: frozenset[EventType]
    on_chain_combos: frozenset[tuple[str, str]]
    koinly_combos: frozenset[tuple[str, str]]
    koinly_fee_surface: KoinlyFeeSurface
    zero_display: bool
    on_chain_counterparties: frozenset[str]
    koinly_counterparties: frozenset[str]
    assets: frozenset[str]
    token_addresses: frozenset[str] = frozenset()


@dataclass(frozen=True)
class ComparisonResult:
    """Outcome of :func:`compare_projection` (validation-harness Task 2).

    Attributes:
        shared_tx_hashes: Hashes present on BOTH sides (matched + divergent).
        matched_tx_hashes: Shared hashes that are semantically equivalent.
        divergent: One record per shared hash with at least one mismatch,
            sorted by ``tx_hash``.
        on_chain_only: Records for hashes present only in the projection
            (e.g. Koinly-dropped gas-only txs), sorted by ``tx_hash``.
        koinly_only: Records for hashes present only in the Koinly rows
            (e.g. Koinly-only NFT mints), sorted by ``tx_hash``.
    """

    shared_tx_hashes: frozenset[str]
    matched_tx_hashes: frozenset[str]
    divergent: tuple[ThComparisonRecord, ...]
    on_chain_only: tuple[ThComparisonRecord, ...]
    koinly_only: tuple[ThComparisonRecord, ...]


# --------------------------------------------------------------------------- #
# Internal accumulation helpers                                                #
# --------------------------------------------------------------------------- #


@dataclass
class _AmountBucket:
    """Mutable per-key accumulator shared by both surfaces."""

    on_chain: Decimal = Decimal("0")
    koinly: Decimal = Decimal("0")
    koinly_rows: set[int] = field(default_factory=set)


def _bucket_tolerance(koinly_rows_in_bucket: int) -> Decimal:
    """Per-bucket display tolerance (PD-010).

    Each Koinly amount cell is rounded to 8 decimals, so ``N`` rows feeding
    one bucket accumulate less than ``N x 1e-8`` of rounding error; the
    on-chain side is exact. ``max(1, ...)`` keeps buckets the Koinly side
    does not feed at the single-row tolerance: a missing contribution
    surfaces once it exceeds 1e-8, and sub-tolerance dust is
    indistinguishable from display rounding by design (PD-010).
    """
    return DISPLAY_TOLERANCE_PER_ROW * max(1, koinly_rows_in_bucket)


def _koinly_amount(row: dict[str, str], key: str) -> Decimal | None:
    """Parse a Koinly amount cell, or ``None`` when the cell is ABSENT.

    Empty/whitespace-only means the row has no value on that side (e.g. a
    ``crypto_deposit`` row has no ``Sent Amount``) and must NOT contribute a
    zero to any bucket - only a cell that DISPLAYS a value (even ``"0,00000000"``)
    contributes, so the zero-display flag can distinguish "rendered as zero"
    from "not rendered at all". Non-empty cells go through the production
    ``parse_koinly_decimal`` (European decimal comma included).
    """
    text = koinly_text(row, key)
    if not text:
        return None
    return parse_koinly_decimal(text)


def _koinly_currency(row: dict[str, str], key: str, *, amount: Decimal) -> str | None:
    """Resolve a bucket currency for a PRESENT amount, with a safe sentinel.

    Returns the stripped currency cell, or ``MISSING`` when a present amount
    carries no currency (a malformed row must surface as its own bucket and
    mismatch, never silently vanish), or ``None`` when there is no amount to
    bucket at all.
    """
    currency = koinly_text(row, key)
    if not currency:
        return _MISSING_CURRENCY if amount is not None else None
    return currency


#: Issuer ticker aliases (PD-010 amendment #3, 2026-08-22, user-delegated):
#: mappings from how one side renders a token's ticker to the issuer-declared
#: standard the other side already uses, for the SAME token contract. Two
#: shapes qualify (each with per-contract evidence):
#:
#: - Glyph vs ASCII: the ERC-20 ``symbol()`` carries a Unicode glyph while
#:   Koinly normalizes to the ASCII industry ticker (``USD₮0`` -> ``USDT0``;
#:   the contract's ``symbol()`` declares the glyph and the 2025 baseline
#:   carries equal per-tx amounts under both spellings).
#: - Issuer rename: the contract now declares a NEW ticker under its old
#:   address while Koinly still renders the pre-rename label (``HONEY`` ->
#:   ``BUSD``: contract 0xfcbd14dc... ``symbol()`` returns ``BUSD`` /
#:   ``name()`` ``"Bera USD"`` (verified 2026-08-22 via eth_call), Koinly
#:   renders ``HONEY``, the address is unique in the dataset, and per-tx
#:   amounts are equal once merged).
#:
#: Keys are matched post case-folding in :func:`_norm_asset`; chain-agnostic
#: (issuer-level, not chain-scoped). Extending the table requires the same
#: evidence shape, and :func:`_assert_ticker_identity_uniqueness` fails loud
#: if an alias would merge two distinct on-chain contracts.
_ISSUER_TICKER_ALIASES: Final[dict[str, str]] = {
    "USD₮0": "USDT0",
    "HONEY": "BUSD",
}


def _norm_asset(symbol: str | None) -> str:
    """Case-fold an asset/currency symbol for bucket keying (Task 11 rule 1).

    The same token renders under differently-cased tickers on the two sides
    (explorer ``iBGT`` vs Koinly ``IBGT``; confirmed on the real 2025
    baseline), so amount buckets are keyed by the folded symbol. On one chain
    a ticker is unique per contract; folding cannot merge two distinct
    assets of the SAME side into one bucket that would otherwise have
    matched. Issuer-declared spellings (glyph or rename) additionally fold
    through :data:`_ISSUER_TICKER_ALIASES` (amendment #3). ``None``/empty
    map to the type-safe ``MISSING`` sentinel.
    """
    if symbol is None:
        return _MISSING_CURRENCY
    folded = symbol.strip().upper() or _MISSING_CURRENCY
    return _ISSUER_TICKER_ALIASES.get(folded, folded)


def _group_koinly_by_hash(rows: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    """Group raw Koinly rows by their ``TxHash`` cell (stripped).

    An empty hash is NOT a key: rows without a hash (manual/fiat entries)
    are returned under the ``""`` key only for :func:`compare_projection` to
    pop back out and emit one record each (review r1 F10) - N unrelated
    unkeyed rows must never collapse into one aggregated record.
    """
    grouped: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        grouped.setdefault(koinly_text(row, "TxHash"), []).append(row)
    return grouped


def _group_projected_by_hash(rows: list[ProjectedThRow]) -> dict[str, list[ProjectedThRow]]:
    """Group projected rows by their ``tx_hash`` (``""`` when None)."""
    grouped: dict[str, list[ProjectedThRow]] = {}
    for projected in rows:
        grouped.setdefault(projected.row.tx_hash or "", []).append(projected)
    return grouped


def _token_addresses_by_hash(
    on_chain_transactions: list[OnChainTransaction] | None,
) -> dict[str, frozenset[str]]:
    """Map each source transaction's ``tx_hash`` to its legs' token addresses.

    The on-chain leg's ``token_address`` is the AUTHORITATIVE LP discriminator
    (review r1 F1): tickers never match the LP snapshot's address keys, so an
    asset-identifier check alone is a dead dimension on the production path.
    The map keys mirror :func:`_group_projected_by_hash` (the transaction-level
    hash the adapter stamps on every projected row). ``None``/empty legs and
    an absent transaction list contribute nothing.
    """
    by_hash: dict[str, set[str]] = {}
    for transaction in on_chain_transactions or ():
        addresses = by_hash.setdefault(transaction.tx_hash, set())
        for event in transaction.events:
            for leg in event.legs:
                if leg.token_address:
                    addresses.add(leg.token_address)
    return {tx_hash: frozenset(addresses) for tx_hash, addresses in by_hash.items()}


def _assert_ticker_identity_uniqueness(
    on_chain_transactions: list[OnChainTransaction] | None,
) -> None:
    """Refuse to compare when one folded ticker maps to >1 distinct contract.

    Amount buckets join the two sides on the folded ticker (case + issuer
    ticker alias) because the Koinly baseline CSV carries no contract addresses.
    That join is only sound while a folded ticker identifies exactly one
    contract within the dataset; two contracts folding to one key would
    silently merge two different tokens' amounts. Fail loud with the ticker
    and every colliding address instead (native legs have no
    ``token_address`` and are exempt - the chain's gas asset is unique).
    """
    ticker_addresses: dict[str, set[str]] = {}
    for transaction in on_chain_transactions or ():
        for event in transaction.events:
            for leg in event.legs:
                if leg.token_address:
                    ticker_addresses.setdefault(_norm_asset(leg.asset), set()).add(
                        leg.token_address.lower()
                    )
    collisions = {t: a for t, a in ticker_addresses.items() if len(a) > 1}
    if collisions:
        detail = "; ".join(f"{ticker} -> {sorted(addresses)}" for ticker, addresses in sorted(collisions.items()))
        raise ValueError(
            f"ticker identity collision: {len(collisions)} folded ticker(s) map to more "
            f"than one token contract, so ticker-keyed amount buckets would merge "
            f"distinct tokens: {detail}"
        )


def _add_on_chain(
    buckets: dict[tuple[str, ...], _AmountBucket],
    key: tuple[str, ...],
    amount: Decimal | None,
) -> None:
    """Accumulate an exact on-chain amount into ``buckets[key]``."""
    if amount is None:
        return
    buckets.setdefault(key, _AmountBucket()).on_chain += amount


def _add_koinly(
    buckets: dict[tuple[str, ...], _AmountBucket],
    key: tuple[str, ...],
    amount: Decimal | None,
    row_index: int,
) -> None:
    """Accumulate a Koinly displayed amount and its feeding-row count."""
    if amount is None:
        return
    bucket = buckets.setdefault(key, _AmountBucket())
    bucket.koinly += amount
    bucket.koinly_rows.add(row_index)


def _collect_event_buckets(
    projected_event_rows: list[ProjectedThRow],
    koinly_event_rows: list[dict[str, str]],
) -> dict[tuple[str, ...], _AmountBucket]:
    """Net amounts per ``(asset, direction)`` over the EVENT-surface rows.

    On-chain side: each projected non-GasBurn row's sending/receiving sides
    (exact Decimals from the adapter). Koinly side: each non-``Cost`` row's
    ``Sent Amount`` / ``Received Amount`` (8-decimal displayed values). Gas
    rows are excluded on both sides - they feed the gas surface instead.

    Asset keys are case-folded (:func:`_norm_asset`, Task 11 rule 1).

    Task 11 rule 2 (mirrored rows): a Koinly row rendering BOTH sides of one
    movement (same folded currency, displayed sent/received equal within the
    per-row display tolerance - the wallet-pair/pool-pair echo rendering)
    contributes its amount ONCE, on the direction(s) the on-chain projection
    carries for that currency (non-zero on-chain bucket). When the on-chain
    side carries NEITHER direction, the row contributes BOTH sides so the
    unmatched movement stays surfaced.
    """
    buckets: dict[tuple[str, ...], _AmountBucket] = {}
    for projected in projected_event_rows:
        row = projected.row
        _add_on_chain(buckets, (_norm_asset(row.sending_currency), "out"), row.sending_amount)
        _add_on_chain(buckets, (_norm_asset(row.receiving_currency), "in"), row.receiving_amount)
    for row_index, row in enumerate(koinly_event_rows):
        sent = _koinly_amount(row, "Sent Amount")
        received = _koinly_amount(row, "Received Amount")
        sent_cur = _koinly_currency(row, "Sent Currency", amount=sent)
        recv_cur = _koinly_currency(row, "Received Currency", amount=received)
        mirrored = (
            sent is not None
            and received is not None
            and sent_cur is not None
            and recv_cur is not None
            and _norm_asset(sent_cur) == _norm_asset(recv_cur)
            and abs(sent - received) <= DISPLAY_TOLERANCE_PER_ROW
        )
        if mirrored:
            currency = _norm_asset(sent_cur)
            carried = {
                direction
                for (asset, direction), bucket in buckets.items()
                if asset == currency and bucket.on_chain != 0
            }
            if carried:
                # One movement, rendered on both sides: count it once, on the
                # side(s) the on-chain projection actually carries.
                if "out" in carried:
                    _add_koinly(buckets, (currency, "out"), sent, row_index)
                if "in" in carried:
                    _add_koinly(buckets, (currency, "in"), received, row_index)
                continue
            # On-chain carries neither direction: contribute BOTH sides so the
            # movement stays surfaced (two mismatches, never a silent pass).
        if sent is not None:
            _add_koinly(buckets, (_norm_asset(sent_cur), "out"), sent, row_index)
        if received is not None:
            _add_koinly(buckets, (_norm_asset(recv_cur), "in"), received, row_index)
    return buckets


def _collect_gas_buckets(
    projected_rows: list[ProjectedThRow],
    koinly_rows: list[dict[str, str]],
) -> dict[tuple[str, ...], _AmountBucket]:
    """Gas amounts per ``currency`` over ALL rows of the tx (PD-010).

    On-chain: ``GasBurn`` rows' ``sending_amount`` (the burned gas, B5: those
    rows carry no fee payload) + carrier rows' ``ProjectedFee`` amounts.
    Koinly: ``Tag=="Cost"`` rows' ``Sent Amount`` + EVERY row's ``Fee Amount``.
    Currency keys are case-folded (:func:`_norm_asset`, Task 11 rule 1).
    """
    buckets: dict[tuple[str, ...], _AmountBucket] = {}
    for projected in projected_rows:
        row = projected.row
        if event_type_of(projected) is EventType.GasBurn:
            _add_on_chain(buckets, (_norm_asset(row.sending_currency),), row.sending_amount)
        if projected.fee is not None:
            _add_on_chain(buckets, (_norm_asset(projected.fee.currency),), projected.fee.amount)
    for row_index, row in enumerate(koinly_rows):
        if koinly_tag(row) == _KOINLY_TAG_COST:
            sent = _koinly_amount(row, "Sent Amount")
            if sent is not None:
                _add_koinly(buckets, (_norm_asset(_koinly_currency(row, "Sent Currency", amount=sent)),), sent, row_index)
        fee = _koinly_amount(row, "Fee Amount")
        if fee is not None:
            _add_koinly(buckets, (_norm_asset(_koinly_currency(row, "Fee Currency", amount=fee)),), fee, row_index)
    return buckets


def _mismatches_from_buckets(
    buckets: dict[tuple[str, ...], _AmountBucket],
    *,
    surface: Surface,
    skip_keys: frozenset[tuple[str, ...]] = frozenset(),
) -> tuple[AmountMismatch, ...]:
    """Compare each bucket's sides against its scaled display tolerance.

    "Within" includes exactly-at-boundary: ``diff == tolerance`` passes and
    ``diff == tolerance + one unit`` fails (pinned by unit test). Buckets are
    visited in sorted key order so records are deterministic. ``skip_keys``
    excludes buckets explained by an upstream rendering-variance rule (Task
    11 rule 3, the gas fold: the key is suppressed on BOTH surfaces).
    """
    mismatches: list[AmountMismatch] = []
    for key in sorted(buckets):
        if key in skip_keys:
            continue
        bucket = buckets[key]
        tolerance = _bucket_tolerance(len(bucket.koinly_rows))
        difference = abs(bucket.on_chain - bucket.koinly)
        if difference <= tolerance:
            continue
        asset = key[0]
        direction = key[1] if surface is Surface.EVENT else None
        zero_display = bucket.koinly == 0 and bool(bucket.koinly_rows) and bucket.on_chain != 0
        mismatches.append(
            AmountMismatch(
                surface=surface,
                asset=asset,
                direction=direction,
                on_chain_amount=bucket.on_chain,
                koinly_amount=bucket.koinly,
                tolerance=tolerance,
                zero_display=zero_display,
            )
        )
    return tuple(mismatches)


def _folded_gas_keys(
    event_buckets: dict[tuple[str, ...], _AmountBucket],
    gas_buckets: dict[tuple[str, ...], _AmountBucket],
) -> frozenset[tuple[str, ...]]:
    """Bucket keys explained by the Koinly gas-folding rendering (Task 11 rule 3).

    Koinly sometimes folds the tx gas INTO the displayed native-asset OUT
    amount and renders NO gas surface at all (no ``Cost`` row, no ``Fee
    Amount`` cell) - confirmed on the real 2025 baseline. The fold holds iff
    for a currency ``C``:

    - the Koinly gas surface for ``C`` is EMPTY (no rows contributed AND a
      zero total - a rendered zero-display cell is the C7 surface, not a
      fold), and
    - the native OUT bucket's Koinly total exceeds the on-chain total by
      EXACTLY the on-chain gas total for ``C`` (within the event bucket's
      scaled tolerance - the displayed amount is 8-decimal rounded).

    Returns the event ``(C, "out")`` and gas ``(C,)`` keys to suppress; any
    other divergence (a real amount diff, a rendered gas surface) keeps both
    mismatches.
    """
    folded: set[tuple[str, ...]] = set()
    for (asset, direction), bucket in event_buckets.items():
        if direction != "out":
            continue
        gas = gas_buckets.get((asset,))
        if gas is None or gas.koinly_rows or gas.koinly != 0:
            continue
        if gas.on_chain == 0:
            continue
        tolerance = _bucket_tolerance(len(bucket.koinly_rows))
        if abs((bucket.koinly - bucket.on_chain) - gas.on_chain) <= tolerance:
            folded.add((asset, "out"))
            folded.add((asset,))
    return frozenset(folded)


def _type_mismatch(
    projected_event_rows: list[ProjectedThRow],
    koinly_event_rows: list[dict[str, str]],
) -> TypeMismatch | None:
    """PD-010 compatibility check between event types and Koinly combos.

    Compatible iff every Koinly combo is in the compatibility set of SOME
    on-chain event type present AND every on-chain event type's set contains
    at least one observed combo. Empty-vs-empty (all rows routed to the gas
    surface on both sides) is compatible.
    """
    event_types = frozenset(event_type_of(projected) for projected in projected_event_rows)
    koinly_combos = frozenset(row_combo(row) for row in koinly_event_rows)
    allowed: set[tuple[str, str]] = set()
    for event_type in event_types:
        allowed.update(EVENT_COMPATIBILITY[event_type])
    uncovered = frozenset(combo for combo in koinly_combos if combo not in allowed)
    unmatched = frozenset(
        event_type for event_type in event_types if not (EVENT_COMPATIBILITY[event_type] & koinly_combos)
    )
    if not uncovered and not unmatched:
        return None
    return TypeMismatch(
        on_chain_combos=frozenset((projected.row.type, projected.row.tag) for projected in projected_event_rows),
        koinly_combos=koinly_combos,
        uncovered_koinly_combos=uncovered,
        unmatched_event_types=unmatched,
    )


def _fee_surface(koinly_rows: list[dict[str, str]]) -> KoinlyFeeSurface:
    """Classify how the Koinly side rendered the gas (signature vocabulary)."""
    has_cost_rows = any(koinly_tag(row) == _KOINLY_TAG_COST for row in koinly_rows)
    has_fee_column = any(koinly_text(row, "Fee Amount") for row in koinly_rows)
    if has_cost_rows and has_fee_column:
        return KoinlyFeeSurface.MIXED
    if has_cost_rows:
        return KoinlyFeeSurface.COST_ROWS
    if has_fee_column:
        return KoinlyFeeSurface.FEE_COLUMN
    return KoinlyFeeSurface.NONE


def _projected_context(
    projected_rows: list[ProjectedThRow],
) -> tuple[
    frozenset[EventType],
    frozenset[tuple[str, str]],
    frozenset[str],
    frozenset[str],
]:
    """Extract (event types, combos, counterparties, assets) from projection."""
    event_types: set[EventType] = set()
    combos: set[tuple[str, str]] = set()
    counterparties: set[str] = set()
    assets: set[str] = set()
    for projected in projected_rows:
        row = projected.row
        event_types.add(event_type_of(projected))
        combos.add((row.type, row.tag))
        for address in (row.tx_src, row.tx_dest):
            if address:
                counterparties.add(address)
        for asset in (row.sending_currency, row.receiving_currency):
            if asset:
                assets.add(asset)
        if projected.fee is not None:
            assets.add(projected.fee.currency)
    return frozenset(event_types), frozenset(combos), frozenset(counterparties), frozenset(assets)


def _koinly_context(
    koinly_rows: list[dict[str, str]],
) -> tuple[frozenset[tuple[str, str]], frozenset[str], frozenset[str]]:
    """Extract (combos, counterparties, assets) from raw Koinly rows."""
    combos: set[tuple[str, str]] = set()
    counterparties: set[str] = set()
    assets: set[str] = set()
    for row in koinly_rows:
        combos.add(row_combo(row))
        for address in (koinly_text(row, "TxSrc"), koinly_text(row, "TxDest")):
            if address:
                counterparties.add(address)
        for key in ("Sent Currency", "Received Currency", "Fee Currency"):
            currency = koinly_text(row, key)
            if currency:
                assets.add(currency)
    return frozenset(combos), frozenset(counterparties), frozenset(assets)


def _on_chain_only_record(
    tx_hash: str,
    projected_rows: list[ProjectedThRow],
    token_addresses: frozenset[str],
) -> ThComparisonRecord:
    """Presence record for a hash the Koinly baseline does not carry at all."""
    event_types, combos, counterparties, assets = _projected_context(projected_rows)
    return ThComparisonRecord(
        tx_hash=tx_hash,
        presence=Presence.ON_CHAIN_ONLY,
        type_mismatch=None,
        amount_mismatches=(),
        on_chain_event_types=event_types,
        on_chain_combos=combos,
        koinly_combos=frozenset(),
        koinly_fee_surface=KoinlyFeeSurface.NONE,
        zero_display=False,
        on_chain_counterparties=counterparties,
        koinly_counterparties=frozenset(),
        assets=assets,
        token_addresses=token_addresses,
    )


def _koinly_only_record(tx_hash: str, koinly_rows: list[dict[str, str]]) -> ThComparisonRecord:
    """Presence record for a hash the on-chain projection does not carry."""
    combos, counterparties, assets = _koinly_context(koinly_rows)
    return ThComparisonRecord(
        tx_hash=tx_hash,
        presence=Presence.KOINLY_ONLY,
        type_mismatch=None,
        amount_mismatches=(),
        on_chain_event_types=frozenset(),
        on_chain_combos=frozenset(),
        koinly_combos=combos,
        koinly_fee_surface=_fee_surface(koinly_rows),
        zero_display=False,
        on_chain_counterparties=frozenset(),
        koinly_counterparties=counterparties,
        assets=assets,
    )


def _compare_shared(
    tx_hash: str,
    koinly_rows: list[dict[str, str]],
    projected_rows: list[ProjectedThRow],
    token_addresses: frozenset[str],
) -> ThComparisonRecord:
    """Full PD-010 comparison for one tx hash present on both sides."""
    koinly_event_rows = [row for row in koinly_rows if koinly_tag(row) != _KOINLY_TAG_COST]
    projected_event_rows = [
        projected for projected in projected_rows if event_type_of(projected) is not EventType.GasBurn
    ]

    type_mismatch = _type_mismatch(projected_event_rows, koinly_event_rows)
    event_buckets = _collect_event_buckets(projected_event_rows, koinly_event_rows)
    gas_buckets = _collect_gas_buckets(projected_rows, koinly_rows)
    skip_keys = _folded_gas_keys(event_buckets, gas_buckets)
    amount_mismatches = _mismatches_from_buckets(event_buckets, surface=Surface.EVENT, skip_keys=skip_keys) + (
        _mismatches_from_buckets(gas_buckets, surface=Surface.GAS, skip_keys=skip_keys)
    )

    event_types, combos, on_chain_counterparties, on_chain_assets = _projected_context(projected_rows)
    koinly_combos, koinly_counterparties, koinly_assets = _koinly_context(koinly_rows)
    return ThComparisonRecord(
        tx_hash=tx_hash,
        presence=Presence.SHARED,
        type_mismatch=type_mismatch,
        amount_mismatches=amount_mismatches,
        on_chain_event_types=event_types,
        on_chain_combos=combos,
        koinly_combos=koinly_combos,
        koinly_fee_surface=_fee_surface(koinly_rows),
        zero_display=any(mismatch.zero_display for mismatch in amount_mismatches),
        on_chain_counterparties=on_chain_counterparties,
        koinly_counterparties=koinly_counterparties,
        assets=on_chain_assets | koinly_assets,
        token_addresses=token_addresses,
    )


def compare_projection(
    koinly_rows: list[dict[str, str]],
    projected: list[ProjectedThRow],
    *,
    on_chain_transactions: list[OnChainTransaction] | None = None,
) -> ComparisonResult:
    """Compare a Koinly TH baseline against the on-chain TH projection.

    Groups both sides by ``TxHash`` / ``tx_hash`` and partitions the hashes:

    - shared -> :func:`_compare_shared` (PD-010 semantic equivalence); hashes
      with zero mismatch details are matches, the rest divergent records;
    - on-chain-only / Koinly-only -> presence records with NO comparison
      (there is nothing to compare against).

    Args:
        koinly_rows: Raw Koinly TH row dicts (the ``read_koinly_rows`` shape).
        projected: The production adapter projection
            (``project_on_chain_transactions`` output).
        on_chain_transactions: The SOURCE transactions behind ``projected``
            (``OnChainProjection.transactions``). Their legs' token addresses
            reach the records as the authoritative LP discriminator (review
            r1 F1); ``None`` keeps the records address-free (the clustering
            LP check falls back to asset identifiers).

    Returns:
        A :class:`ComparisonResult` with deterministic (hash-sorted) records.

    Raises:
        ValueError: Propagated from ``parse_koinly_decimal`` when a non-empty
            Koinly amount cell is malformed (fail-loud by design - the harness
            must not silently skip a row it cannot read).
    """
    koinly_by_hash = _group_koinly_by_hash(koinly_rows)
    on_chain_by_hash = _group_projected_by_hash(projected)
    token_addresses_by_hash = _token_addresses_by_hash(on_chain_transactions)
    _assert_ticker_identity_uniqueness(on_chain_transactions)

    # Unkeyed Koinly rows (empty TxHash) are NOT one group (review r1 F10):
    # each is its own Koinly-only record - N unrelated no-hash rows must not
    # collapse into one aggregated record, and an unkeyed row can never join
    # the shared partition (it cannot "match" a hash it does not carry).
    unkeyed_koinly_rows = koinly_by_hash.pop("", [])
    koinly_only_hashes = koinly_by_hash.keys() - on_chain_by_hash.keys()

    on_chain_only = tuple(
        _on_chain_only_record(tx_hash, on_chain_by_hash[tx_hash], token_addresses_by_hash.get(tx_hash, frozenset()))
        for tx_hash in sorted(on_chain_by_hash.keys() - koinly_by_hash.keys())
    )
    keyed_koinly_only = tuple(
        _koinly_only_record(tx_hash, koinly_by_hash[tx_hash]) for tx_hash in sorted(koinly_only_hashes)
    )
    unkeyed_koinly_only = tuple(_koinly_only_record("", [row]) for row in unkeyed_koinly_rows)
    koinly_only = keyed_koinly_only + unkeyed_koinly_only

    shared_hashes = koinly_by_hash.keys() & on_chain_by_hash.keys()
    matched: set[str] = set()
    divergent: list[ThComparisonRecord] = []
    for tx_hash in sorted(shared_hashes):
        record = _compare_shared(
            tx_hash,
            koinly_by_hash[tx_hash],
            on_chain_by_hash[tx_hash],
            token_addresses_by_hash.get(tx_hash, frozenset()),
        )
        if record.type_mismatch is None and not record.amount_mismatches:
            matched.add(tx_hash)
        else:
            divergent.append(record)

    return ComparisonResult(
        shared_tx_hashes=frozenset(shared_hashes),
        matched_tx_hashes=frozenset(matched),
        divergent=tuple(divergent),
        on_chain_only=on_chain_only,
        koinly_only=koinly_only,
    )
