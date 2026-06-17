"""TH row parsing and classification for loan-affected assets.

Reads Koinly Transaction History rows, discovers loan-affected assets,
and classifies each row into acquisitions/consumptions for FIFO processing.
Action-emitter helpers live in ``_emitters.py`` to keep this module focused on
row parsing and classification.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import MutableMapping, Sequence
from pathlib import Path

from ...domain.crypto_fifo import CryptoAcquisition, CryptoConsumption
from ...infrastructure.koinly_parser import (
    format_datetime,
    normalize_asset_ticker,
    normalize_platform_name,
    parse_koinly_datetime,
    parse_koinly_decimal,
    read_koinly_rows,
)
from ._emitters import _add_cross_asset_fee_consumption, _build_composite_tx_key, _handle_exchange, _handle_transfer
from .contexts import (
    _LOAN_PRINCIPAL_TAGS,
    LOAN_TAGS,
    ZERO,
    AcquisitionContext,
    ConsumptionContext,
    ParsedTxRow,
)

logger = logging.getLogger(__name__)


def discover_loan_affected_assets(
    transaction_history_path: Path,
    fiat_currency_codes: frozenset[str],
) -> frozenset[str]:
    """Discover which assets are loan-affected by scanning loan-tagged rows in the TH CSV.

    Reads the Koinly Transaction History CSV and collects the Sent Currency and
    Received Currency from every row whose Tag is in ``_LOAN_PRINCIPAL_TAGS`` (i.e.
    ``"loan"`` and ``"loan repayment"``). ``"loan fee"`` rows are intentionally excluded
    from discovery: a fee-tagged row's Sent Currency is the gas/service fee asset (e.g.
    ETH for a WBTC loan gas payment), not the loan principal, and including it would
    incorrectly pull the fee asset into the FIFO rebuild scope. Fee Currency is also
    excluded for the same reason.

    Fiat currencies are excluded from the result: a loan repayment modelled as an
    exchange (e.g. EUR->WBTC tagged "loan repayment") would otherwise pull EUR into
    the FIFO rebuild scope, treating every EUR-involving TH row as a loan-affected
    acquisition or consumption.

    Args:
        transaction_history_path: Path to the Koinly transaction history CSV.
        fiat_currency_codes: Set of ISO 4217 fiat currency codes to exclude.
            Pass _get_all_fiat_currency_codes() from the caller to exclude all fiat
            currencies. Pass frozenset() explicitly if no fiat filtering is desired
            (e.g. in tests where only crypto tickers appear in loan rows).

    Returns:
        Frozenset of normalized asset tickers that appeared as Sent or Received
        Currency in loan principal-tagged rows, excluding any fiat currencies.
    """
    rows = read_koinly_rows(transaction_history_path)
    found: set[str] = set()
    for row in rows:
        tag = row.get("Tag", "").strip().lower()
        if tag not in _LOAN_PRINCIPAL_TAGS:
            continue
        for col in ("Sent Currency", "Received Currency"):
            ticker = normalize_asset_ticker(row.get(col, ""))
            if ticker and ticker not in fiat_currency_codes:
                found.add(ticker)
    return frozenset(found)


def parse_th_for_loan_affected_assets(
    transaction_history_path: Path,
    loan_affected_assets: frozenset[str] = frozenset(),
) -> tuple[
    dict[str, list[AcquisitionContext]],
    dict[str, list[ConsumptionContext]],
    frozenset[tuple[str, str, str]],
    dict[str, list[int]],
]:
    """Parse TH rows and classify acquisitions/consumptions for loan-affected assets.

    Reads the Koinly Transaction History CSV and produces two dictionaries keyed by
    normalized asset ticker. Only rows involving at least one asset in loan_affected_assets
    are processed. Loan-tagged rows (Tag=Loan/Loan repayment/Loan fee) are excluded
    entirely per CIRS art. 10(20).

    Args:
        transaction_history_path: Path to the Koinly transaction history CSV.
        loan_affected_assets: Set of asset tickers to process (from discover_loan_affected_assets).

    Returns:
        Tuple of (acquisitions_by_asset, consumptions_by_asset, phantom_sending_transfers,
        parse_failures_by_asset) where each dict is keyed by normalized asset ticker and
        phantom_sending_transfers is a frozenset of (asset, sending_platform, date) for
        cross-platform transfers of loan-affected assets. parse_failures_by_asset maps
        each loan-affected asset with a parse error to the list of failing row indices.
    """
    rows = read_koinly_rows(transaction_history_path)
    return _classify_rows_for_loan_affected_assets(rows, loan_affected_assets)


def _classify_rows_for_loan_affected_assets(  # noqa: PLR0912, PLR0915
    rows: Sequence[dict[str, str]],
    loan_affected_assets: frozenset[str] = frozenset(),
) -> tuple[
    dict[str, list[AcquisitionContext]],
    dict[str, list[ConsumptionContext]],
    frozenset[tuple[str, str, str]],
    dict[str, list[int]],
]:
    """Core classification logic for loan-affected assets from pre-loaded TH rows.

    Operates on rows already loaded from the CSV (no file I/O). This separation allows
    the classification logic to be tested without touching the file system and respects
    the application-to-infrastructure dependency direction.

    Args:
        rows: Pre-loaded Koinly transaction history rows.
        loan_affected_assets: Set of asset tickers to process.

    Returns:
        Same tuple structure as parse_th_for_loan_affected_assets.
    """
    acquisitions: defaultdict[str, list[AcquisitionContext]] = defaultdict(list)
    consumptions: defaultdict[str, list[ConsumptionContext]] = defaultdict(list)
    phantom_sending_transfers: set[tuple[str, str, str]] = set()
    parse_failures_by_asset: dict[str, list[int]] = {}

    for row_index, row in enumerate(rows, start=1):
        tag = row.get("Tag", "").strip().lower()
        row_type = row.get("Type", "").strip().lower()

        if tag in LOAN_TAGS:
            continue

        sent_currency = normalize_asset_ticker(row.get("Sent Currency", ""))
        received_currency = normalize_asset_ticker(row.get("Received Currency", ""))
        fee_currency = normalize_asset_ticker(row.get("Fee Currency", ""))
        sent_affected = sent_currency in loan_affected_assets
        received_affected = received_currency in loan_affected_assets
        fee_affected = fee_currency in loan_affected_assets

        if not sent_affected and not received_affected and not fee_affected:
            continue

        tx_hash = row.get("TxHash", "").strip()
        tx_key = tx_hash if tx_hash else _build_composite_tx_key(row, row_index)

        date_raw = row.get("Date", "").strip()
        if not date_raw:
            logger.error(
                "Row %d: mandatory Date field is blank — skipping row to prevent epoch-date "
                "misclassification (TH export may be incomplete or contain a malformed row)",
                row_index,
            )
            affected_assets_for_skip: list[str] = []
            if sent_affected and sent_currency:
                affected_assets_for_skip.append(sent_currency)
            if received_affected and received_currency:
                affected_assets_for_skip.append(received_currency)
            if fee_affected and fee_currency:
                affected_assets_for_skip.append(fee_currency)
            for a in affected_assets_for_skip:
                parse_failures_by_asset.setdefault(a, []).append(row_index)
            continue

        try:
            sent_amount = parse_koinly_decimal(row.get("Sent Amount", "0"))
            received_amount = parse_koinly_decimal(row.get("Received Amount", "0"))
            sent_cost_basis = parse_koinly_decimal(row.get("Sent Cost Basis", "0"))
            net_value = parse_koinly_decimal(row.get("Net Value (EUR)", "0"))
            fee_amount = parse_koinly_decimal(row.get("Fee Amount", "0"))
            fee_value = parse_koinly_decimal(row.get("Fee Value (EUR)", "0"))
            parsed_dt = parse_koinly_datetime(date_raw)
            date_str = format_datetime(parsed_dt)
            timestamp_str = parsed_dt.strftime("%Y-%m-%d %H:%M")
        except ValueError as exc:
            logger.error(
                "Row %d: unparseable value in TH row — skipping. "
                "Check Date, Sent Amount/Currency, Received Amount/Currency fields: %s",
                row_index,
                exc,
            )
            logger.debug(
                "Row %d raw field values: Date=%r, Sent=%r/%r, Received=%r/%r",
                row_index,
                row.get("Date", ""),
                row.get("Sent Amount", ""),
                row.get("Sent Currency", ""),
                row.get("Received Amount", ""),
                row.get("Received Currency", ""),
            )
            affected_assets: list[str] = []
            if sent_affected and sent_currency:
                affected_assets.append(sent_currency)
            if received_affected and received_currency:
                affected_assets.append(received_currency)
            if fee_affected and fee_currency:
                affected_assets.append(fee_currency)
            for affected_asset in affected_assets:
                parse_failures_by_asset.setdefault(affected_asset, []).append(row_index)
            continue

        _classify_th_row(
            ParsedTxRow(
                row=row,
                row_index=row_index,
                date_str=date_str,
                tx_key=tx_key,
                row_type=row_type,
                sent_currency=sent_currency,
                received_currency=received_currency,
                fee_currency=fee_currency,
                sent_amount=sent_amount,
                received_amount=received_amount,
                sent_cost_basis=sent_cost_basis,
                net_value=net_value,
                fee_amount=fee_amount,
                fee_value=fee_value,
                sent_affected=sent_affected,
                received_affected=received_affected,
                fee_affected=fee_affected,
                loan_affected_assets=loan_affected_assets,
                timestamp_str=timestamp_str,
            ),
            acquisitions=acquisitions,
            consumptions=consumptions,
            parse_failures_by_asset=parse_failures_by_asset,
            phantom_sending_transfers=phantom_sending_transfers,
        )

    _dedup_by_tx_key(acquisitions, consumptions, parse_failures_by_asset)
    return acquisitions, consumptions, frozenset(phantom_sending_transfers), parse_failures_by_asset


def _dedup_by_tx_key(
    acquisitions: MutableMapping[str, list[AcquisitionContext]],
    consumptions: MutableMapping[str, list[ConsumptionContext]],
    parse_failures_by_asset: dict[str, list[int]],
) -> None:
    """Remove duplicate tx_key entries per asset per direction, logging a warning for each skip.

    Koinly's wrapped-asset repair workflow can produce TH rows with duplicate TxHash values.
    A duplicated acquisition would double the FIFO pool quantity; a duplicated consumption
    would trigger two disposals of the same lot, generating a phantom gain. Deduplication
    keeps the first occurrence and discards subsequent rows with the same tx_key.

    The parse_failures_by_asset dict is updated for any row that is dropped so that the
    resulting FIFO realizations are flagged for manual review.
    """
    for asset, acqs in acquisitions.items():
        seen_acqs: set[tuple[str, str]] = set()
        kept: list[AcquisitionContext] = []
        for acq in acqs:
            dedup_key = (acq.tx_key, acq.acq.source_type)
            if dedup_key in seen_acqs:
                logger.warning(
                    "Duplicate tx_key %r / source_type %r for asset %s acquisitions (row %d); "
                    "skipping to prevent doubled FIFO pool quantity. "
                    "Check for duplicate TxHash rows in the Koinly Transaction History export.",
                    acq.tx_key,
                    acq.acq.source_type,
                    asset,
                    acq.source_row_index,
                )
                parse_failures_by_asset.setdefault(asset, []).append(acq.source_row_index)
            else:
                seen_acqs.add(dedup_key)
                kept.append(acq)
        acquisitions[asset] = kept

    for asset, cons in consumptions.items():
        seen_cons: set[tuple[str, str]] = set()
        kept_cons: list[ConsumptionContext] = []
        for con in cons:
            dedup_key = (con.tx_key, con.con.event_type)
            if dedup_key in seen_cons:
                logger.warning(
                    "Duplicate tx_key %r / event_type %r for asset %s consumptions (row %d); "
                    "skipping to prevent phantom disposal. "
                    "Check for duplicate TxHash rows in the Koinly Transaction History export.",
                    con.tx_key,
                    con.con.event_type,
                    asset,
                    con.source_row_index,
                )
                parse_failures_by_asset.setdefault(asset, []).append(con.source_row_index)
            else:
                seen_cons.add(dedup_key)
                kept_cons.append(con)
        consumptions[asset] = kept_cons


def _classify_th_row(
    parsed_row: ParsedTxRow,
    *,
    acquisitions: MutableMapping[str, list[AcquisitionContext]],
    consumptions: MutableMapping[str, list[ConsumptionContext]],
    parse_failures_by_asset: dict[str, list[int]],
    phantom_sending_transfers: set[tuple[str, str, str]],
) -> None:
    """Classify a single parsed TH row into acquisitions/consumptions for loan-affected assets."""
    match (parsed_row.row_type, parsed_row.sent_affected, parsed_row.received_affected):
        case ("exchange", _, _):
            _classify_exchange_row(parsed_row, acquisitions=acquisitions, consumptions=consumptions)
        case ("transfer", _, _):
            _classify_transfer_row(
                parsed_row,
                acquisitions=acquisitions,
                consumptions=consumptions,
                phantom_sending_transfers=phantom_sending_transfers,
            )
        case ("sell", True, _):
            _classify_sell_row(
                parsed_row,
                consumptions=consumptions,
                parse_failures_by_asset=parse_failures_by_asset,
            )
        case ("crypto_withdrawal", True, _):
            _classify_withdrawal_row(
                parsed_row,
                consumptions=consumptions,
                parse_failures_by_asset=parse_failures_by_asset,
            )
        case ("buy", _, True):
            _classify_buy_row(
                parsed_row,
                acquisitions=acquisitions,
                consumptions=consumptions,
                parse_failures_by_asset=parse_failures_by_asset,
            )
        case ("crypto_deposit", _, True):
            _classify_deposit_row(
                parsed_row,
                acquisitions=acquisitions,
                consumptions=consumptions,
                parse_failures_by_asset=parse_failures_by_asset,
            )
        case (_, True, _) | (_, _, True):
            _classify_unhandled_principal_row(
                parsed_row,
                consumptions=consumptions,
                parse_failures_by_asset=parse_failures_by_asset,
            )
        case (_, _, _):
            _classify_fee_only_row(parsed_row, consumptions=consumptions)


def _classify_exchange_row(
    parsed_row: ParsedTxRow,
    *,
    acquisitions: MutableMapping[str, list[AcquisitionContext]],
    consumptions: MutableMapping[str, list[ConsumptionContext]],
) -> None:
    _handle_exchange(
        parsed_row,
        acquisitions=acquisitions,
        consumptions=consumptions,
    )



def _classify_transfer_row(
    parsed_row: ParsedTxRow,
    *,
    acquisitions: MutableMapping[str, list[AcquisitionContext]],
    consumptions: MutableMapping[str, list[ConsumptionContext]],
    phantom_sending_transfers: set[tuple[str, str, str]],
) -> None:
    _handle_transfer(
        parsed_row,
        acquisitions=acquisitions,
        consumptions=consumptions,
        phantom_sending_transfers=phantom_sending_transfers,
    )



def _classify_sell_row(
    parsed_row: ParsedTxRow,
    *,
    consumptions: MutableMapping[str, list[ConsumptionContext]],
    parse_failures_by_asset: dict[str, list[int]],
) -> None:
    if parsed_row.received_affected:
        logger.warning(
            "Row %d: sell with both sides loan-affected (%s/%s); "
            "received side %s not tracked — expected exchange type in Koinly",
            parsed_row.row_index,
            parsed_row.sent_currency,
            parsed_row.received_currency,
            parsed_row.received_currency,
        )
        parse_failures_by_asset.setdefault(parsed_row.received_currency, []).append(parsed_row.row_index)
    sell_wallet = parsed_row.row.get("Sending Wallet", "").strip()
    _con = ConsumptionContext(
            con=CryptoConsumption(
                date=parsed_row.date_str,
                asset=parsed_row.sent_currency,
                amount=parsed_row.sent_amount,
                proceeds_eur=parsed_row.net_value,
                event_type="sell",
                taxable=True,
                wallet=sell_wallet,
                platform=normalize_platform_name(sell_wallet),
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
                    wallet=sell_wallet,
                    platform=normalize_platform_name(sell_wallet),
                    notes=f"Fee for sell of {parsed_row.sent_currency}",
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
        wallet=sell_wallet,
    )



def _classify_withdrawal_row(
    parsed_row: ParsedTxRow,
    *,
    consumptions: MutableMapping[str, list[ConsumptionContext]],
    parse_failures_by_asset: dict[str, list[int]],
) -> None:
    if parsed_row.received_affected:
        logger.warning(
            "Row %d: crypto_withdrawal with both sides loan-affected (%s/%s); "
            "received side %s not tracked",
            parsed_row.row_index,
            parsed_row.sent_currency,
            parsed_row.received_currency,
            parsed_row.received_currency,
        )
        parse_failures_by_asset.setdefault(parsed_row.received_currency, []).append(parsed_row.row_index)
    withdrawal_wallet = parsed_row.row.get("Sending Wallet", "").strip()
    _con = ConsumptionContext(
            con=CryptoConsumption(
                date=parsed_row.date_str,
                asset=parsed_row.sent_currency,
                amount=parsed_row.sent_amount,
                proceeds_eur=parsed_row.net_value,
                event_type="withdrawal",
                taxable=True,
                wallet=withdrawal_wallet,
                platform=normalize_platform_name(withdrawal_wallet),
                notes="",
                review_required=True,
                review_reason=(
                    f"crypto_withdrawal of {parsed_row.sent_currency}: verify this is a true disposal "
                    "and not a self-custody transfer to a wallet not tracked in Koinly. "
                    "If non-taxable, re-label as 'Transfer' in Koinly and re-run."
                ),
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
                    wallet=withdrawal_wallet,
                    platform=normalize_platform_name(withdrawal_wallet),
                    notes=f"Fee for withdrawal of {parsed_row.sent_currency}",
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
        wallet=withdrawal_wallet,
    )



def _classify_buy_row(
    parsed_row: ParsedTxRow,
    *,
    acquisitions: MutableMapping[str, list[AcquisitionContext]],
    consumptions: MutableMapping[str, list[ConsumptionContext]],
    parse_failures_by_asset: dict[str, list[int]],
) -> None:
    if parsed_row.sent_affected:
        logger.warning(
            "Row %d: buy with both sides loan-affected (%s/%s); "
            "sent side %s not tracked — expected exchange type in Koinly",
            parsed_row.row_index,
            parsed_row.sent_currency,
            parsed_row.received_currency,
            parsed_row.sent_currency,
        )
        parse_failures_by_asset.setdefault(parsed_row.sent_currency, []).append(parsed_row.row_index)
    _acq = AcquisitionContext(
            acq=CryptoAcquisition(
                date=parsed_row.date_str,
                asset=parsed_row.received_currency,
                amount=parsed_row.received_amount,
                cost_basis_eur=parsed_row.net_value,
                fee_eur=(
                    parsed_row.fee_value
                    if parsed_row.fee_currency == parsed_row.received_currency
                    else ZERO
                ),
                source_type="buy",
                wallet=parsed_row.row.get("Receiving Wallet", "").strip(),
                platform=normalize_platform_name(parsed_row.row.get("Receiving Wallet", "")),
                review_required=False,
            ),
            tx_key=parsed_row.tx_key,
            source_row_index=parsed_row.row_index,
    )
    acquisitions[_acq.acq.asset].append(_acq)
    _add_cross_asset_fee_consumption(
        parsed_row=parsed_row,
        consumptions=consumptions,
        principal_currencies=frozenset({parsed_row.received_currency}),
        wallet=parsed_row.row.get("Receiving Wallet", "").strip(),
    )



def _classify_deposit_row(
    parsed_row: ParsedTxRow,
    *,
    acquisitions: MutableMapping[str, list[AcquisitionContext]],
    consumptions: MutableMapping[str, list[ConsumptionContext]],
    parse_failures_by_asset: dict[str, list[int]],
) -> None:
    if parsed_row.sent_affected:
        logger.warning(
            "Row %d: crypto_deposit with both sides loan-affected (%s/%s); "
            "sent side %s not tracked",
            parsed_row.row_index,
            parsed_row.sent_currency,
            parsed_row.received_currency,
            parsed_row.sent_currency,
        )
        parse_failures_by_asset.setdefault(parsed_row.sent_currency, []).append(parsed_row.row_index)
    deposit_review_required = False
    deposit_review_reason: str | None = None
    if parsed_row.net_value == ZERO:
        logger.warning(
            "Row %d: crypto_deposit of %s has zero Net Value (EUR); "
            "cost basis may be missing in Koinly — marking for review",
            parsed_row.row_index,
            parsed_row.received_currency,
        )
        deposit_review_required = True
        deposit_review_reason = (
            f"crypto_deposit of {parsed_row.received_currency} "
            f"(row {parsed_row.row_index}) has zero Net Value; "
            "cost basis may be missing in Koinly — verify and correct manually"
        )
    _acq = AcquisitionContext(
            acq=CryptoAcquisition(
                date=parsed_row.date_str,
                asset=parsed_row.received_currency,
                amount=parsed_row.received_amount,
                cost_basis_eur=parsed_row.net_value,
                fee_eur=(
                    parsed_row.fee_value
                    if parsed_row.fee_currency == parsed_row.received_currency
                    else ZERO
                ),
                source_type="deposit",
                wallet=parsed_row.row.get("Receiving Wallet", "").strip(),
                platform=normalize_platform_name(parsed_row.row.get("Receiving Wallet", "")),
                review_required=deposit_review_required,
                review_reason=deposit_review_reason,
            ),
            tx_key=parsed_row.tx_key,
            source_row_index=parsed_row.row_index,
    )
    acquisitions[_acq.acq.asset].append(_acq)
    _add_cross_asset_fee_consumption(
        parsed_row=parsed_row,
        consumptions=consumptions,
        principal_currencies=frozenset({parsed_row.received_currency}),
        wallet=parsed_row.row.get("Receiving Wallet", "").strip(),
    )



def _classify_unhandled_principal_row(
    parsed_row: ParsedTxRow,
    *,
    consumptions: MutableMapping[str, list[ConsumptionContext]],
    parse_failures_by_asset: dict[str, list[int]],
) -> None:
    if parsed_row.sent_affected and parsed_row.received_affected:
        affected_asset = f"{parsed_row.sent_currency}/{parsed_row.received_currency}"
        affected_side = "both sent and received"
    elif parsed_row.sent_affected:
        affected_asset = parsed_row.sent_currency
        affected_side = "sent"
    else:
        affected_asset = parsed_row.received_currency
        affected_side = "received"
    # Determine which specific assets are affected for the failure registry
    if parsed_row.sent_affected and parsed_row.received_affected:
        for _fa in (parsed_row.sent_currency, parsed_row.received_currency):
            parse_failures_by_asset.setdefault(_fa, []).append(parsed_row.row_index)
    elif parsed_row.sent_affected:
        parse_failures_by_asset.setdefault(parsed_row.sent_currency, []).append(parsed_row.row_index)
    else:
        parse_failures_by_asset.setdefault(parsed_row.received_currency, []).append(parsed_row.row_index)
    logger.warning(
        "Row %d: unhandled row type %r for loan-affected asset %s (%s side); "
        "row skipped — verify no FIFO pool gap introduced",
        parsed_row.row_index,
        parsed_row.row_type,
        affected_asset,
        affected_side,
    )
    if parsed_row.fee_affected and parsed_row.fee_amount > ZERO:
        fee_wallet = (
            parsed_row.row.get("Sending Wallet", "").strip()
            or parsed_row.row.get("Receiving Wallet", "").strip()
        )
        _con = ConsumptionContext(
                con=CryptoConsumption(
                    date=parsed_row.date_str,
                    asset=parsed_row.fee_currency,
                    amount=parsed_row.fee_amount,
                    proceeds_eur=parsed_row.fee_value,
                    event_type="fee_disposal",
                    taxable=True,
                    wallet=fee_wallet,
                    platform=normalize_platform_name(fee_wallet),
                    notes=f"Fee for unhandled {parsed_row.row_type}",
                    review_required=False,
                    disposal_timestamp=parsed_row.timestamp_str,
                ),
                tx_key=parsed_row.tx_key,
                source_row_index=parsed_row.row_index,
        )
        consumptions[_con.con.asset].append(_con)



def _classify_fee_only_row(
    parsed_row: ParsedTxRow,
    *,
    consumptions: MutableMapping[str, list[ConsumptionContext]],
) -> None:
    if parsed_row.fee_affected and parsed_row.fee_amount > ZERO:
        fee_wallet = (
            parsed_row.row.get("Sending Wallet", "").strip()
            or parsed_row.row.get("Receiving Wallet", "").strip()
        )
        _con = ConsumptionContext(
                con=CryptoConsumption(
                    date=parsed_row.date_str,
                    asset=parsed_row.fee_currency,
                    amount=parsed_row.fee_amount,
                    proceeds_eur=parsed_row.fee_value,
                    event_type="fee_disposal",
                    taxable=True,
                    wallet=fee_wallet,
                    platform=normalize_platform_name(fee_wallet),
                    notes=(
                        f"Fee for {parsed_row.row_type} "
                        f"({parsed_row.sent_currency}->{parsed_row.received_currency})"
                    ),
                    review_required=False,
                    disposal_timestamp=parsed_row.timestamp_str,
                ),
                tx_key=parsed_row.tx_key,
                source_row_index=parsed_row.row_index,
        )
        consumptions[_con.con.asset].append(_con)
