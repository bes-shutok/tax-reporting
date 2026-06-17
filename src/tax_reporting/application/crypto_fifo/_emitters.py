"""Action emitters for the crypto FIFO parser. Builds AcquisitionContext and ConsumptionContext objects from classified ParsedTxRow inputs."""

from __future__ import annotations

import logging
from collections.abc import MutableMapping

from ...domain.crypto_fifo import CryptoAcquisition, CryptoConsumption
from ...infrastructure.koinly_parser import normalize_platform_name
from .contexts import ZERO, AcquisitionContext, ConsumptionContext, ParsedTxRow

logger = logging.getLogger(__name__)


def _handle_exchange(
    parsed_row: ParsedTxRow,
    *,
    acquisitions: MutableMapping[str, list[AcquisitionContext]],
    consumptions: MutableMapping[str, list[ConsumptionContext]],
) -> None:
    if parsed_row.sent_affected and parsed_row.received_affected:
        _emit_cross_asset_exchange(
            parsed_row,
            acquisitions=acquisitions,
            consumptions=consumptions,
        )
    elif parsed_row.received_affected and not parsed_row.sent_affected:
        _emit_received_only_exchange(
            parsed_row,
            acquisitions=acquisitions,
            consumptions=consumptions,
        )
    elif parsed_row.sent_affected and not parsed_row.received_affected:
        _emit_sent_only_exchange(
            parsed_row,
            consumptions=consumptions,
        )
    elif parsed_row.fee_affected and not parsed_row.sent_affected and not parsed_row.received_affected:
        _emit_fee_only_exchange(
            parsed_row,
            consumptions=consumptions,
        )


def _emit_cross_asset_exchange(
    parsed_row: ParsedTxRow,
    acquisitions: MutableMapping[str, list[AcquisitionContext]],
    consumptions: MutableMapping[str, list[ConsumptionContext]],
) -> None:
    wallet = parsed_row.row.get("Receiving Wallet", "").strip()
    platform = normalize_platform_name(wallet)
    sending_wallet = parsed_row.row.get("Sending Wallet", "").strip()
    sending_platform = normalize_platform_name(sending_wallet)

    third_currency_fee_recv = (
        parsed_row.fee_value
        if parsed_row.fee_currency not in (parsed_row.sent_currency, parsed_row.received_currency)
        and parsed_row.fee_value > ZERO
        else ZERO
    )
    if third_currency_fee_recv > ZERO:
        logger.warning(
            "Row %d: exchange %s->%s has fee in third currency %s (%.6f EUR); "
            "adding to %s deferred acquisition cost basis",
            parsed_row.row_index,
            parsed_row.sent_currency,
            parsed_row.received_currency,
            parsed_row.fee_currency,
            third_currency_fee_recv,
            parsed_row.received_currency,
        )
    _con = ConsumptionContext(
        con=CryptoConsumption(
            date=parsed_row.date_str,
            asset=parsed_row.sent_currency,
            amount=parsed_row.sent_amount,
            proceeds_eur=ZERO,
            event_type="exchange_out",
            taxable=False,
            wallet=sending_wallet,
            platform=sending_platform,
            notes="",
            review_required=False,
            disposal_timestamp=parsed_row.timestamp_str,
        ),
        tx_key=parsed_row.tx_key,
        source_row_index=parsed_row.row_index,
    )
    consumptions[_con.con.asset].append(_con)
    if parsed_row.fee_currency == parsed_row.sent_currency and parsed_row.fee_amount > ZERO:
        _con = ConsumptionContext(
            con=CryptoConsumption(
                date=parsed_row.date_str,
                asset=parsed_row.sent_currency,
                amount=parsed_row.fee_amount,
                proceeds_eur=parsed_row.fee_value,
                event_type="fee_disposal",
                taxable=True,
                wallet=sending_wallet,
                platform=sending_platform,
                notes=(
                    f"Fee for {parsed_row.sent_currency}->{parsed_row.received_currency} "
                    "exchange (fee in sent asset)"
                ),
                review_required=False,
                disposal_timestamp=parsed_row.timestamp_str,
            ),
            tx_key=parsed_row.tx_key,
            source_row_index=parsed_row.row_index,
        )
        consumptions[_con.con.asset].append(_con)
    recv_fee = parsed_row.fee_value if parsed_row.fee_currency == parsed_row.received_currency else ZERO
    _acq = AcquisitionContext(
        acq=CryptoAcquisition(
            date=parsed_row.date_str,
            asset=parsed_row.received_currency,
            amount=parsed_row.received_amount,
            cost_basis_eur=ZERO,
            fee_eur=recv_fee + third_currency_fee_recv,
            source_type="exchange_in_deferred",
            wallet=wallet,
            platform=platform,
            review_required=False,
        ),
        tx_key=parsed_row.tx_key,
        source_row_index=parsed_row.row_index,
    )
    acquisitions[_acq.acq.asset].append(_acq)
    if parsed_row.fee_currency == parsed_row.received_currency and parsed_row.fee_amount > ZERO:
        _con = ConsumptionContext(
            con=CryptoConsumption(
                date=parsed_row.date_str,
                asset=parsed_row.received_currency,
                amount=parsed_row.fee_amount,
                proceeds_eur=parsed_row.fee_value,
                event_type="fee_disposal",
                taxable=True,
                wallet=wallet,
                platform=platform,
                notes=(
                    f"Fee for {parsed_row.sent_currency}->{parsed_row.received_currency} "
                    "exchange (fee in received asset)"
                ),
                review_required=False,
                disposal_timestamp=parsed_row.timestamp_str,
            ),
            tx_key=parsed_row.tx_key,
            source_row_index=parsed_row.row_index,
        )
        consumptions[_con.con.asset].append(_con)
    _add_cross_asset_fee_consumption(
        parsed_row=parsed_row,
        consumptions=consumptions,
        principal_currencies=frozenset({parsed_row.sent_currency, parsed_row.received_currency}),
        wallet=sending_wallet,
        row_type="exchange",
    )


def _emit_received_only_exchange(
    parsed_row: ParsedTxRow,
    *,
    acquisitions: MutableMapping[str, list[AcquisitionContext]],
    consumptions: MutableMapping[str, list[ConsumptionContext]],
) -> None:
    wallet = parsed_row.row.get("Receiving Wallet", "").strip()
    platform = normalize_platform_name(wallet)
    sending_wallet = parsed_row.row.get("Sending Wallet", "").strip()

    cost = parsed_row.sent_cost_basis
    review_required = False
    review_reason: str | None = None
    if cost == ZERO:
        logger.warning(
            "Row %d: exchange %s->%s has empty Sent Cost Basis; keeping zero cost, marking for review",
            parsed_row.row_index,
            parsed_row.sent_currency,
            parsed_row.received_currency,
        )
        review_required = True
        review_reason = (
            f"Empty Sent Cost Basis on exchange {parsed_row.sent_currency}->{parsed_row.received_currency}; "
            "carry-over cost could not be determined"
        )
    third_currency_fee_recv = (
        parsed_row.fee_value
        if parsed_row.fee_currency not in (parsed_row.sent_currency, parsed_row.received_currency)
        and parsed_row.fee_value > ZERO
        else ZERO
    )
    if third_currency_fee_recv > ZERO:
        logger.warning(
            "Row %d: exchange %s->%s has fee in third currency %s (%.6f EUR); adding to %s acquisition cost basis",
            parsed_row.row_index,
            parsed_row.sent_currency,
            parsed_row.received_currency,
            parsed_row.fee_currency,
            third_currency_fee_recv,
            parsed_row.received_currency,
        )
    fee_same = parsed_row.fee_value if parsed_row.fee_currency == parsed_row.received_currency else ZERO
    _acq = AcquisitionContext(
        acq=CryptoAcquisition(
            date=parsed_row.date_str,
            asset=parsed_row.received_currency,
            amount=parsed_row.received_amount,
            cost_basis_eur=cost,
            fee_eur=fee_same + third_currency_fee_recv,
            source_type="exchange_in",
            wallet=wallet,
            platform=platform,
            review_required=review_required,
            review_reason=review_reason,
        ),
        tx_key=parsed_row.tx_key,
        source_row_index=parsed_row.row_index,
    )
    acquisitions[_acq.acq.asset].append(_acq)
    _add_cross_asset_fee_consumption(
        parsed_row=parsed_row,
        consumptions=consumptions,
        principal_currencies=frozenset({parsed_row.sent_currency, parsed_row.received_currency}),
        wallet=sending_wallet,
        row_type="exchange",
    )


def _emit_sent_only_exchange(
    parsed_row: ParsedTxRow,
    *,
    consumptions: MutableMapping[str, list[ConsumptionContext]],
) -> None:
    sending_wallet = parsed_row.row.get("Sending Wallet", "").strip()
    sending_platform = normalize_platform_name(sending_wallet)
    _con = ConsumptionContext(
        con=CryptoConsumption(
            date=parsed_row.date_str,
            asset=parsed_row.sent_currency,
            amount=parsed_row.sent_amount,
            proceeds_eur=ZERO,
            event_type="exchange_out",
            taxable=False,
            wallet=sending_wallet,
            platform=sending_platform,
            notes="",
            review_required=False,
            disposal_timestamp=parsed_row.timestamp_str,
        ),
        tx_key=parsed_row.tx_key,
        source_row_index=parsed_row.row_index,
    )
    consumptions[_con.con.asset].append(_con)
    if parsed_row.fee_currency == parsed_row.sent_currency and parsed_row.fee_amount > ZERO:
        _con = ConsumptionContext(
            con=CryptoConsumption(
                date=parsed_row.date_str,
                asset=parsed_row.sent_currency,
                amount=parsed_row.fee_amount,
                proceeds_eur=parsed_row.fee_value,
                event_type="fee_disposal",
                taxable=True,
                wallet=sending_wallet,
                platform=sending_platform,
                notes=(
                    f"Fee for {parsed_row.sent_currency}->{parsed_row.received_currency} "
                    "exchange (fee in sent asset)"
                ),
                review_required=False,
                disposal_timestamp=parsed_row.timestamp_str,
            ),
            tx_key=parsed_row.tx_key,
            source_row_index=parsed_row.row_index,
        )
        consumptions[_con.con.asset].append(_con)
    _add_cross_asset_fee_consumption(
        parsed_row=parsed_row,
        consumptions=consumptions,
        principal_currencies=frozenset({parsed_row.sent_currency}),
        wallet=sending_wallet,
        row_type="exchange",
    )


def _emit_fee_only_exchange(
    parsed_row: ParsedTxRow,
    *,
    consumptions: MutableMapping[str, list[ConsumptionContext]],
) -> None:
    sending_wallet = parsed_row.row.get("Sending Wallet", "").strip()
    sending_platform = normalize_platform_name(sending_wallet)
    if parsed_row.fee_amount > ZERO:
        _con = ConsumptionContext(
            con=CryptoConsumption(
                date=parsed_row.date_str,
                asset=parsed_row.fee_currency,
                amount=parsed_row.fee_amount,
                proceeds_eur=parsed_row.fee_value,
                event_type="exchange_fee",
                taxable=True,
                wallet=sending_wallet,
                platform=sending_platform,
                notes=f"Fee for {parsed_row.sent_currency}->{parsed_row.received_currency} exchange",
                review_required=False,
                disposal_timestamp=parsed_row.timestamp_str,
            ),
            tx_key=parsed_row.tx_key,
            source_row_index=parsed_row.row_index,
        )
        consumptions.setdefault(_con.con.asset, [])
        consumptions[_con.con.asset].append(_con)


def _handle_transfer(
    parsed_row: ParsedTxRow,
    *,
    acquisitions: MutableMapping[str, list[AcquisitionContext]],
    consumptions: MutableMapping[str, list[ConsumptionContext]],
    phantom_sending_transfers: set[tuple[str, str, str]],
) -> None:
    """Handle a transfer row: emit non-taxable transfer_out + deferred acquisition when receiver known."""
    if parsed_row.sent_affected and parsed_row.sent_amount > ZERO:
        sending_wallet = parsed_row.row.get("Sending Wallet", "").strip()
        sending_platform = normalize_platform_name(sending_wallet)
        receiving_wallet = parsed_row.row.get("Receiving Wallet", "").strip()
        receiving_platform = normalize_platform_name(receiving_wallet)

        if sending_platform == receiving_platform:
            logger.debug(
                "Row %d: same-platform transfer of %s (%s -> %s); skipping",
                parsed_row.row_index,
                parsed_row.sent_currency,
                sending_wallet,
                receiving_wallet,
            )
        elif not receiving_wallet:
            logger.warning(
                "Row %d: transfer of loan-affected asset %s (%s) has unknown receiver platform — "
                "principal movement not tracked. Sending platform (%s) retains phantom lots; "
                "future disposals from that platform will be flagged review_required=True.",
                parsed_row.row_index,
                parsed_row.sent_currency,
                parsed_row.date_str,
                sending_platform,
            )
            phantom_sending_transfers.add((parsed_row.sent_currency, sending_platform, parsed_row.date_str))
        else:
            transfer_amount = parsed_row.received_amount if parsed_row.received_amount > ZERO else parsed_row.sent_amount
            if parsed_row.sent_amount > transfer_amount:
                logger.warning(
                    "Row %d: transfer of %s has sent_amount (%s) > received_amount (%s); "
                    "difference %s may be a bridge/protocol fee not tracked in FIFO pool",
                    parsed_row.row_index,
                    parsed_row.sent_currency,
                    parsed_row.sent_amount,
                    transfer_amount,
                    parsed_row.sent_amount - transfer_amount,
                )
            _con = ConsumptionContext(
                con=CryptoConsumption(
                    date=parsed_row.date_str,
                    asset=parsed_row.sent_currency,
                    amount=transfer_amount,
                    proceeds_eur=ZERO,
                    event_type="transfer_out",
                    taxable=False,
                    wallet=sending_wallet,
                    platform=sending_platform,
                    notes="",
                    review_required=False,
                    disposal_timestamp=parsed_row.timestamp_str,
                ),
                tx_key=parsed_row.tx_key,
                source_row_index=parsed_row.row_index,
            )
            consumptions[_con.con.asset].append(_con)
            _acq = AcquisitionContext(
                acq=CryptoAcquisition(
                    date=parsed_row.date_str,
                    asset=parsed_row.sent_currency,
                    amount=transfer_amount,
                    cost_basis_eur=ZERO,
                    fee_eur=ZERO,
                    source_type="transfer_in_deferred",
                    wallet=receiving_wallet,
                    platform=receiving_platform,
                    review_required=False,
                ),
                tx_key=parsed_row.tx_key,
                source_row_index=parsed_row.row_index,
            )
            acquisitions[_acq.acq.asset].append(_acq)

    if parsed_row.fee_amount <= ZERO or parsed_row.fee_currency not in parsed_row.loan_affected_assets:
        return

    wallet = parsed_row.row.get("Sending Wallet", "").strip()
    _con = ConsumptionContext(
        con=CryptoConsumption(
            date=parsed_row.date_str,
            asset=parsed_row.fee_currency,
            amount=parsed_row.fee_amount,
            proceeds_eur=parsed_row.fee_value,
            event_type="fee_disposal",
            taxable=True,
            wallet=wallet,
            platform=normalize_platform_name(wallet),
            notes="Fee from transfer",
            review_required=False,
            disposal_timestamp=parsed_row.timestamp_str,
        ),
        tx_key=parsed_row.tx_key,
        source_row_index=parsed_row.row_index,
    )
    consumptions[_con.con.asset].append(_con)


def _add_cross_asset_fee_consumption(
    *,
    parsed_row: ParsedTxRow,
    consumptions: MutableMapping[str, list[ConsumptionContext]],
    principal_currencies: frozenset[str],
    wallet: str,
    row_type: str | None = None,
) -> None:
    """Add a consumption for a fee paid in a loan-affected asset different from the principal."""
    if parsed_row.fee_currency not in parsed_row.loan_affected_assets:
        return
    if parsed_row.fee_currency in principal_currencies:
        return
    if parsed_row.fee_amount <= ZERO:
        return
    _con = ConsumptionContext(
        con=CryptoConsumption(
            date=parsed_row.date_str,
            asset=parsed_row.fee_currency,
            amount=parsed_row.fee_amount,
            proceeds_eur=parsed_row.fee_value,
            event_type="fee_disposal",
            taxable=True,
            wallet=wallet,
            platform=normalize_platform_name(wallet),
            notes=f"Cross-asset fee for {row_type or parsed_row.row_type}",
            review_required=False,
            disposal_timestamp=parsed_row.timestamp_str,
        ),
        tx_key=parsed_row.tx_key,
        source_row_index=parsed_row.row_index,
    )
    consumptions[_con.con.asset].append(_con)


def _build_composite_tx_key(row: dict[str, str], row_index: int) -> str:
    parts = [
        row.get("Date", ""),
        row.get("Sending Wallet", ""),
        row.get("Sent Amount", ""),
        row.get("Sent Currency", ""),
        row.get("Receiving Wallet", ""),
        row.get("Received Amount", ""),
        row.get("Received Currency", ""),
    ]
    key = "_".join(parts)
    return f"{key}_{row_index}" if any(parts) else f"row_{row_index}"
