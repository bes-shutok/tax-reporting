"""On-chain TH adapter: project ``OnChainTransaction`` -> ``TransactionHistoryRow``.

This module exists ONLY to bridge the on-chain-native transaction model
(``domain.on_chain_transaction``: ``OnChainTransaction`` / ``Event`` / ``Leg`` /
``Gas``) onto the Koinly-shaped ``TransactionHistoryRow``
(``domain.transaction``) the existing crypto-tax pipeline already consumes.

Why this module is a NON-DOMAIN accommodation (Future Maintainer F5)
--------------------------------------------------------------------

The on-chain-native model is *richer and more honest* than Koinly's collapsed
shape: one ``OnChainTransaction`` carries N ``Event`` objects plus a single
parent-tx-level ``Gas`` (gas is a property of the tx, not of any leg/Event).
The Koinly-shaped ``TransactionHistoryRow`` has a FLAT ``Fee Amount`` /
``Fee Currency`` column on every row (no parent-tx concept) and one row per
economic event with no native multi-leg structure. Reconciling the two is a
LOSSY projection:

- **Carrier-row gas rule (the core non-domain accommodation).** Gas lives at
  the parent-tx level on ``OnChainTransaction``, but ``TransactionHistoryRow``
  has no parent-tx-level gas field, so gas must ride on ONE row's ``Fee Amount``
  / ``Fee Currency``. The rule: pick the **carrier row** = the row derived from
  the NATIVE leg (``token_address is None``) if the tx has one, else the FIRST
  emitted row; put ``Fee Amount`` = gas amount (converted from raw via decimals)
  and ``Fee Currency`` = gas asset on the carrier row only.

- **GasBurn exception (B5 double-count prevention).** A GasBurn Event projects
  to ``crypto_withdrawal`` / ``Cost`` and carries the gas as ``Sent Amount``
  (gas IS the value burned). The carrier-row rule therefore SKIPS GasBurn rows:
  a GasBurn row's ``Fee Amount`` is EMPTY so the fee-filter's ``has_embedded_fee``
  predicate is False for it and the gas is counted EXACTLY ONCE (on the
  ``Sent Amount`` side), not twice (once as Sent Amount AND once as Fee Amount).

Because the typed ``TransactionHistoryRow`` has NO fee field (it is pure
movement + identity data), the carrier-row rule cannot put gas ON the row.
Instead, the adapter tags the carrier row with an OPTIONAL
:class:`ProjectedFee` payload (carried alongside the row in a
:class:`ProjectedThRow` wrapper). The CSV bridge (Plan Task 11) emits
``Fee Amount`` / ``Fee Currency`` from this payload; non-carrier rows get empty
fee cells. This keeps ``TransactionHistoryRow`` a pure domain object while
making the carrier-row rule observable and auditable.

The ``EventType`` -> Koinly ``Type`` / ``Tag`` mapping is a SINGLE DICT
(:data:`EVENT_TYPE_TO_KOINLY`) so it is trivial to audit against the design
record (§9.1). SubType is IGNORED for Koinly Type/Tag mapping (Koinly has no
equivalent; the design record §9.1 explicitly states this).

Design record: ``docs/architecture/on-chain-tx-design.md`` (§3 carrier-row gas
rule, §9.1 EventType -> Koinly mapping, decision 9: parent-tx-level gas).
Implementation plan: ``docs/history/plans/2026-08-02-on-chain-tx-tagger.md``.
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from tax_reporting.domain.on_chain_transaction import (
    Event,
    EventType,
    Gas,
    Leg,
    OnChainTransaction,
)
from tax_reporting.domain.transaction import TransactionHistoryRow

__all__ = [
    "EVENT_TYPE_TO_KOINLY",
    "TH_CSV_COLUMNS",
    "ProjectedFee",
    "ProjectedThRow",
    "project_on_chain_transactions",
    "serialize_projected_rows_to_th_csv",
]

_LOGGER = logging.getLogger(__name__)


# Closed EventType -> Koinly (Type, Tag) mapping (design record §9.1).
#
# This is a SINGLE DICT so it is trivial to audit against the design record.
# SubType is deliberately NOT consulted here: Koinly has no SubType equivalent
# (design record §9.1), and the per-shape tag is fixed by the EventType alone.
#
# Mapping rationale (design record §9.1 table + plan):
#   Swap            -> exchange          / ""          (the canonical swap row)
#   Reward          -> crypto_deposit    / "Reward"    (matches Koinly reward shape)
#   LiquidityDeposit-> transfer          / "Liquidity in"   (LP provision)
#   GasBurn         -> crypto_withdrawal / "Cost"      (PT-deductible gas burn)
#   LiquidityWithdraw -> crypto_withdrawal / "Liquidity out"  (LP withdrawal)
#   Transfer        -> transfer          / ""          (non-taxable movement)
#   Unknown         -> crypto_deposit    / ""          (safe default + review
#                                                     upstream; a deposit is the
#                                                     least-presumptuous shape
#                                                     for an unrecognized inflow)
EVENT_TYPE_TO_KOINLY: dict[EventType, tuple[str, str]] = {
    EventType.Swap: ("exchange", ""),
    EventType.Reward: ("crypto_deposit", "Reward"),
    EventType.LiquidityDeposit: ("transfer", "Liquidity in"),
    EventType.GasBurn: ("crypto_withdrawal", "Cost"),
    EventType.LiquidityWithdraw: ("crypto_withdrawal", "Liquidity out"),
    EventType.Transfer: ("transfer", ""),
    EventType.Unknown: ("crypto_deposit", ""),
}


@dataclass(frozen=True)
class ProjectedFee:
    """The gas fee payload attached to a CARRIER row (carrier-row gas rule).

    The typed ``TransactionHistoryRow`` has NO fee field, so the carrier-row
    rule cannot put gas on the row itself. Instead, the adapter tags the ONE
    carrier row per tx with this payload; the CSV bridge (Plan Task 11) emits
    ``Fee Amount`` / ``Fee Currency`` from it. Non-carrier rows (and ALL
    GasBurn rows per the B5 exception) carry ``fee=None``.

    Attributes:
        amount: Gas amount converted from raw via ``Decimal(amount_raw) /
            Decimal(10 ** decimals)`` (the reader clamped decimals to [0,36]
            so ``10 ** decimals`` is safe here).
        currency: Gas asset ticker (e.g. ``"BERA"``).
    """

    amount: Decimal
    currency: str


@dataclass(frozen=True)
class ProjectedThRow:
    """A projected ``TransactionHistoryRow`` plus an optional carrier-row fee.

    Wraps the pure typed row with the carrier-row gas payload so the
    non-domain accommodation (gas on one row's ``Fee Amount``) stays
    observable without polluting the domain object.

    Attributes:
        row: The typed ``TransactionHistoryRow`` (pure movement + identity).
        fee: The carrier-row gas payload, or ``None``. Exactly ONE row per tx
            with gas carries a non-None ``fee``, EXCEPT when the carrier would
            be a GasBurn row (the B5 exception -> no fee payload, gas rides on
            the row's ``Sent Amount`` instead).
    """

    row: TransactionHistoryRow
    fee: ProjectedFee | None


def project_on_chain_transactions(
    txs: list[OnChainTransaction],
) -> list[ProjectedThRow]:
    """Project ``list[OnChainTransaction]`` -> ``list[ProjectedThRow]``.

    One ``Event`` per ``OnChainTransaction`` projects to ONE
    ``TransactionHistoryRow`` (the split model). Each row carries the
    processor's ``event_id`` (``f"{tx_hash}#{n}"``) VERBATIM; ``event_id`` is
    NEVER defaulted to None for on-chain rows (Task 2's amendment would be dead
    code otherwise). ``row_index`` is adapter-local 0-based ordering, assigned
    by enumerating the emitted rows across all input txs in order.

    The carrier-row gas rule is applied per tx: the row derived from the native
    leg (``token_address is None``) carries the gas ``fee`` payload; if the tx
    has no native leg, the FIRST emitted row carries it; GasBurn rows NEVER
    carry the fee payload (the B5 exception).

    Args:
        txs: ``list[OnChainTransaction]`` from the per-chain processor (Task 9),
            in any order; each tx's ``events`` tuple drives the per-Event rows.

    Returns:
        ``list[ProjectedThRow]`` in tx-then-event order (input order preserved;
        rows within a tx share ``tx_hash`` and have distinct ``event_id``).
    """
    projected: list[ProjectedThRow] = []
    row_index = 0
    for tx in txs:
        tx_rows: list[tuple[int, Event, TransactionHistoryRow]] = []
        for event in tx.events:
            row = _project_event(tx, event, row_index=row_index)
            tx_rows.append((row_index, event, row))
            row_index += 1
        # Resolve and attach the carrier-row fee payload for this tx.
        carrier_index = _carrier_row_index(tx, tx_rows)
        for index, _event, row in tx_rows:
            fee: ProjectedFee | None = None
            if (
                carrier_index == index
                and tx.gas is not None
                # B5 exception: GasBurn rows NEVER carry the fee payload.
                and _event.event_type is not EventType.GasBurn
            ):
                fee = _to_fee(tx.gas)
            projected.append(ProjectedThRow(row=row, fee=fee))
    return projected


# --------------------------------------------------------------------------- #
# Internal helpers                                                            #
# --------------------------------------------------------------------------- #


def _project_event(
    tx: OnChainTransaction, event: Event, *, row_index: int
) -> TransactionHistoryRow:
    """Project ONE ``Event`` to a typed ``TransactionHistoryRow``.

    Carries the processor's ``event_id`` verbatim, picks the Koinly
    ``Type``/``Tag`` from :data:`EVENT_TYPE_TO_KOINLY`, and populates the
    sending / receiving sides from the representative legs of the Event.
    """
    koinly_type, koinly_tag = EVENT_TYPE_TO_KOINLY[event.event_type]
    sending_wallet = tx.wallet_label or "Unknown"
    receiving_wallet = tx.wallet_label or "Unknown"

    out_leg = _first_leg_by_direction(event.legs, "out")
    in_leg = _first_leg_by_direction(event.legs, "in")

    # GasBurn: gas is the value burned -> Sent Amount = gas, no receiving side.
    # The event carries a zero-value native outflow leg, but the adapter
    # projects the GAS as Sent Amount (the honest on-chain shape). The carrier-
    # row rule SKIPS this row's fee payload so the gas is counted once.
    if event.event_type is EventType.GasBurn and tx.gas is not None:
        sending_amount = _raw_to_decimal(tx.gas.amount_raw, tx.gas.decimals)
        sending_currency = tx.gas.asset
        # Use the leg's addresses for tx_src/tx_dest (the wallet paid the gas).
        addr_leg = out_leg or in_leg
        tx_src = addr_leg.from_address if addr_leg is not None else None
        tx_dest = addr_leg.to_address if addr_leg is not None else None
        return TransactionHistoryRow(
            utc_instant=tx.timestamp_utc,
            type=koinly_type,
            tag=koinly_tag,
            sending_wallet=sending_wallet,
            sending_amount=sending_amount,
            sending_currency=sending_currency,
            receiving_wallet=receiving_wallet,
            receiving_amount=None,
            receiving_currency=None,
            tx_hash=tx.tx_hash,
            tx_src=tx_src,
            tx_dest=tx_dest,
            row_index=row_index,
            event_id=event.event_id,
        )

    # Sending side: from the representative out leg (Koinly convention: the
    # out leg is the asset disposed/sent).
    if out_leg is not None:
        sending_amount = _raw_to_decimal(out_leg.amount_raw, out_leg.amount_decimals)
        sending_currency = out_leg.asset
    else:
        sending_amount = None
        sending_currency = None

    # Receiving side: from the representative in leg.
    if in_leg is not None:
        receiving_amount = _raw_to_decimal(in_leg.amount_raw, in_leg.amount_decimals)
        receiving_currency = in_leg.asset
    else:
        receiving_amount = None
        receiving_currency = None

    # Representative leg for tx_src / tx_dest: prefer the OUT leg (the
    # disposal side), else the IN leg. This mirrors the Koinly convention
    # (TxSrc = the sender's address, TxDest = the receiver's address).
    rep_leg = out_leg or in_leg
    tx_src = rep_leg.from_address if rep_leg is not None else None
    tx_dest = rep_leg.to_address if rep_leg is not None else None

    return TransactionHistoryRow(
        utc_instant=tx.timestamp_utc,
        type=koinly_type,
        tag=koinly_tag,
        sending_wallet=sending_wallet,
        sending_amount=sending_amount,
        sending_currency=sending_currency,
        receiving_wallet=receiving_wallet,
        receiving_amount=receiving_amount,
        receiving_currency=receiving_currency,
        tx_hash=tx.tx_hash,
        tx_src=tx_src,
        tx_dest=tx_dest,
        row_index=row_index,
        event_id=event.event_id,
    )


def _carrier_row_index(
    tx: OnChainTransaction, tx_rows: list[tuple[int, Event, TransactionHistoryRow]]
) -> int | None:
    """Return the row_index of the carrier row for ``tx``'s gas.

    The carrier row = the row derived from the NATIVE leg
    (``token_address is None``) if the tx has one, else the FIRST emitted row.
    Returns ``None`` when the tx has no events.

    The GasBurn exception is enforced at payload-attachment time (the carrier
    may be a GasBurn row, in which case no fee payload is attached); this
    function only identifies WHICH row is the carrier.

    When the native-leg carrier IS a GasBurn, the B5 skip means the gas is NOT
    emitted as a ``Fee Amount`` on any row of the tx; it remains only on the
    GasBurn row's ``Sent Amount`` (gas is counted exactly once).
    """
    if not tx_rows:
        return None
    # Prefer the row whose representative leg is the native leg.
    for index, event, _row in tx_rows:
        if _is_native_leg_event(event):
            return index
    # No native leg -> the first emitted row is the carrier.
    return tx_rows[0][0]


def _is_native_leg_event(event: Event) -> bool:
    """Return True iff ``event``'s representative leg is the native-chain asset.

    The native asset has ``token_address is None``. The representative leg is
    the OUT leg if present (the disposal side), else the IN leg.
    """
    rep = _first_leg_by_direction(event.legs, "out")
    if rep is None:
        rep = _first_leg_by_direction(event.legs, "in")
    return rep is not None and rep.token_address is None


def _first_leg_by_direction(legs: tuple[Leg, ...], direction: str) -> Leg | None:
    """Return the first leg of ``legs`` matching ``direction``, else None."""
    for leg in legs:
        if leg.direction == direction:
            return leg
    return None


def _raw_to_decimal(amount_raw: int, decimals: int) -> Decimal:
    """Convert a raw integer smallest-unit amount to a Decimal at ``decimals``.

    The CSV reader (Task 7) already clamped ``decimals`` to [0,36], so
    ``10 ** decimals`` is safe here (no overflow). Uses Decimal throughout so
    no float ever touches an amount value (AGENTS.md / design record §3).
    """
    return Decimal(amount_raw) / Decimal(10) ** decimals


def _to_fee(gas: Gas) -> ProjectedFee:
    """Build the carrier-row fee payload from a parent-tx-level ``Gas``."""
    return ProjectedFee(
        amount=_raw_to_decimal(gas.amount_raw, gas.decimals),
        currency=gas.asset,
    )


# --------------------------------------------------------------------------- #
# CSV bridge (Plan Task 11, bridge option (a))                                #
# --------------------------------------------------------------------------- #
#
# The on-chain adapter returns ``list[ProjectedThRow]`` (a typed
# ``TransactionHistoryRow`` + an optional carrier-row ``ProjectedFee``). The
# crypto pipeline, however, consumes a Transaction-History-shaped CSV file via
# ``koinly_parser.read_koinly_rows`` / ``_detect_header_index`` and
# ``remove_transaction_fees(transaction_history_file=<Path>)``. Bridge option
# (a) (decided in Plan Task 5): serialize the projected rows to a TH-shaped
# CSV that includes an ``event_id`` column, written to the location the
# pipeline reads TH from. The existing ``read_koinly_rows`` (a ``csv.DictReader``)
# preserves the ``event_id`` column automatically (Task 5 confirmed this), so
# ``fee_filter`` and ``token_origin`` see it without any parser change.
#
# The columns are the STANDARD Koinly TH header (verified against a real Koinly
# export header) plus a trailing ``event_id`` (lowercase, the Task 5 bridge
# contract). The Koinly header carries two rows of preamble (a title row and a
# blank row) before the column header; ``_detect_header_index`` finds the
# header via the ``Date,`` marker, so this serializer writes the SAME preamble
# shape (title + blank + header) so the file is readable by the production
# reader unchanged.

#: The standard Koinly Transaction-History column order (verified against a
#: real Koinly ``*transaction_history*.csv`` export header) PLUS the trailing
#: ``event_id`` column (Task 5 bridge contract; lowercase). The order MUST
#: match a real Koinly TH header so the serialized file is indistinguishable
#: from a Koinly export to ``read_koinly_rows`` / ``_detect_header_index``
#: (which keys on the ``Date,`` marker).
TH_CSV_COLUMNS: tuple[str, ...] = (
    "Date",
    "Type",
    "Tag",
    "Sending Wallet",
    "Sent Amount",
    "Sent Currency",
    "Sent Cost Basis",
    "Receiving Wallet",
    "Received Amount",
    "Received Currency",
    "Received Cost Basis",
    "Fee Amount",
    "Fee Currency",
    "Gain (EUR)",
    "Net Value (EUR)",
    "Fee Value (EUR)",
    "TxSrc",
    "TxDest",
    "TxHash",
    "Description",
    "event_id",
)

#: The Koinly TH datetime format (UTC literal suffix; see
#: ``koinly_parser.DATE_FORMATS``). The adapter's rows carry timezone-aware
#: UTC datetimes; this formats them back into the Koinly TH shape so
#: ``parse_koinly_datetime`` round-trips them.
_TH_DATE_FORMAT = "%Y-%m-%d %H:%M:%S UTC"


def _decimal_to_str(value: Decimal | None) -> str:
    """Render a Decimal amount as a Koinly-style string (empty when None)."""
    if value is None:
        return ""
    # str(Decimal) preserves the exact value (no float rounding). Koinly writes
    # plain decimal strings; the reader's parse_koinly_decimal accepts this.
    return str(value)


def serialize_projected_rows_to_th_csv(
    rows: list[ProjectedThRow], path: Path, *, title: str = "Transaction report"
) -> Path:
    """Serialize ``list[ProjectedThRow]`` to a Koinly-TH-shaped CSV at ``path``.

    Bridge option (a) (Plan Task 5/11): the crypto pipeline consumes a
    Transaction-History-shaped CSV via ``read_koinly_rows``; this serializer
    writes the projected on-chain rows in that exact shape (standard Koinly TH
    columns + a trailing ``event_id`` column) so the existing
    ``remove_transaction_fees(transaction_history_file=<Path>)`` call picks it
    up UNCHANGED.

    Per-row emission rules (the carrier-row gas rule, observable through the
    CSV cells):

    - **Carrier row**: ``Fee Amount`` / ``Fee Currency`` come from the row's
      ``ProjectedFee`` payload (the parent-tx gas). Exactly ONE row per tx with
      gas carries a non-empty fee (except GasBurn rows per the B5 exception).
    - **Non-carrier rows**: ``Fee Amount`` / ``Fee Currency`` are EMPTY.
    - **GasBurn rows**: ``Sent Amount`` = gas (the value burned), ``Fee Amount``
      EMPTY (B5: gas is not a fee on itself). The adapter already set the
      row's ``sending_amount`` to the gas decimal; this serializer just writes
      it through and leaves fee empty (the carrier payload is ``None`` for
      GasBurn rows by adapter construction).
    - ``TxHash`` = the real on-chain hash (Task 4's migration reads ``TxHash``
      not ``TxSrc``); ``TxSrc`` / ``TxDest`` = the leg addresses.
    - ``event_id`` = the row's ``event_id`` (the split-Event discriminator);
      empty for Koinly-shaped rows (on-chain rows always carry a non-None id).

    The file is written with the Koinly preamble (title row + blank row +
    header) so ``_detect_header_index`` finds the header via the ``Date,``
    marker exactly as it does for a real Koinly export.

    Args:
        rows: ``list[ProjectedThRow]`` from :func:`project_on_chain_transactions`.
        path: Destination CSV path. The parent directory is created if missing.
            Any pre-existing file is overwritten (truncated, not appended).
        title: The preamble title row (defaults to ``"Transaction report"``).

    Returns:
        The ``path`` written (for chaining / logging).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    # Koinly TH files carry a title row + a blank row before the header. We
    # mirror that shape so the production reader's ``_detect_header_index``
    # (which scans for the ``Date,`` marker) locates the header identically.
    with path.open("w", newline="", encoding="utf-8") as fh:
        fh.write(f"{title}\n")
        fh.write("\n")
        writer = csv.DictWriter(fh, fieldnames=list(TH_CSV_COLUMNS))
        writer.writeheader()
        for projected in rows:
            row = projected.row
            fee = projected.fee
            writer.writerow(
                {
                    "Date": row.utc_instant.strftime(_TH_DATE_FORMAT),
                    "Type": row.type,
                    "Tag": row.tag,
                    "Sending Wallet": row.sending_wallet,
                    "Sent Amount": _decimal_to_str(row.sending_amount),
                    "Sent Currency": row.sending_currency or "",
                    "Sent Cost Basis": "",
                    "Receiving Wallet": row.receiving_wallet,
                    "Received Amount": _decimal_to_str(row.receiving_amount),
                    "Received Currency": row.receiving_currency or "",
                    "Received Cost Basis": "",
                    "Fee Amount": _decimal_to_str(fee.amount) if fee is not None else "",
                    "Fee Currency": fee.currency if fee is not None else "",
                    "Gain (EUR)": "",
                    "Net Value (EUR)": "",
                    "Fee Value (EUR)": "",
                    "TxSrc": row.tx_src or "",
                    "TxDest": row.tx_dest or "",
                    "TxHash": row.tx_hash or "",
                    "Description": "",
                    "event_id": row.event_id or "",
                }
            )
    _LOGGER.info(
        "Serialized %d projected on-chain TH row(s) to %s (bridge option (a): TH-shaped CSV with event_id)",
        len(rows),
        path,
    )
    return path
