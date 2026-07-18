"""Loan activity extraction for crypto tax reporting."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from ...domain.constants import (
    LOAN_STATUS_IN_ASSET_INTEREST,
    LOAN_STATUS_NO_EUR_PRICE,
    LOAN_STATUS_OPEN_LOAN,
    LOAN_STATUS_OVERPAID_VERIFY,
    LOAN_STATUS_SETTLED,
)
from ...infrastructure.koinly_parser import normalize_asset_ticker, parse_koinly_decimal, read_koinly_rows
from .classification import _get_all_fiat_currency_codes
from .constants import ZERO
from .entities import LoanActivityEntry

# Invariant 5: module-level overshoot threshold (amount-space). Branch (c) of the
# classifier treats overshoot_pct <= LOAN_OVERSHOOT_INTEREST_PCT as in-asset interest.
LOAN_OVERSHOOT_INTEREST_PCT = Decimal("1")


def _extract_loan_activity(transaction_history_path: Path | None) -> list[LoanActivityEntry]:  # noqa: PLR0912, PLR0915
    """Extract per-asset loan activity from the Koinly transaction history.

    Scans for loan receipts (Tag='Loan', deposit types) and loan repayments
    (Tag='Loan repayment', crypto_withdrawal). Aggregates per asset and
    computes balance with status classification.

    Args:
        transaction_history_path: Path to the Koinly transaction history CSV, or None.

    Returns:
        Sorted list of LoanActivityEntry, one per asset with loan activity.
    """
    if transaction_history_path is None or not transaction_history_path.exists():
        return []

    logger = logging.getLogger(__name__)

    @dataclass
    class _Accumulator:
        received_count: int = 0
        received_amount: Decimal = ZERO
        received_value_eur: Decimal = ZERO
        repaid_count: int = 0
        repaid_amount: Decimal = ZERO
        repaid_value_eur: Decimal = ZERO

    accs: dict[str, _Accumulator] = {}
    rows = read_koinly_rows(transaction_history_path)

    for row_number, row in enumerate(rows, start=1):
        tag = row.get("Tag", "").strip().lower()
        row_type = row.get("Type", "").strip().lower()

        if tag == "loan" and row_type in ("crypto_deposit", "deposit", "transfer"):
            received_currency = row.get("Received Currency", "").strip()
            if not received_currency:
                logger.warning("Skipping loan receipt row %d: blank Received Currency", row_number)
                continue
            asset = normalize_asset_ticker(received_currency)
            received_amount_str = row.get("Received Amount", "0").strip()
            net_value_str = row.get("Net Value (EUR)", "0").strip()
            try:
                received_amount = parse_koinly_decimal(received_amount_str)
                received_value = parse_koinly_decimal(net_value_str)
            except ValueError as exc:
                logger.warning("Skipping loan receipt row %d for %s: unparseable amount: %s", row_number, asset, exc)
                continue
            if asset not in accs:
                accs[asset] = _Accumulator()
            accs[asset].received_count += 1
            accs[asset].received_amount += received_amount
            accs[asset].received_value_eur += received_value

        elif tag == "loan repayment" and row_type in {"crypto_withdrawal", "exchange", "sell", "transfer"}:
            # Loan repayments are executed as withdrawals (most common), exchanges (DeFi repay-in-kind),
            # sells, or on-chain transfers. For all these row types, the repaid crypto is in Sent Currency.
            # Note: "buy" is excluded: buy rows represent fiat→crypto purchases where Sent Currency
            # is fiat, not the crypto being repaid.
            sent_currency = row.get("Sent Currency", "").strip()
            if not sent_currency:
                logger.warning("Skipping loan repayment row %d: blank Sent Currency", row_number)
                continue
            if row_type == "exchange" and normalize_asset_ticker(sent_currency) in _get_all_fiat_currency_codes():
                received_currency = row.get("Received Currency", "").strip()
                logger.warning(
                    "Skipping loan repayment row %d: exchange type with fiat Sent Currency %s "
                    "(Received Currency=%s); fiat-mediated repayments should be type 'buy', not 'exchange'",
                    row_number,
                    sent_currency,
                    received_currency,
                )
                continue
            asset = normalize_asset_ticker(sent_currency)
            sent_amount_str = row.get("Sent Amount", "0").strip()
            net_value_str = row.get("Net Value (EUR)", "0").strip()
            try:
                sent_amount = parse_koinly_decimal(sent_amount_str)
                repaid_value = parse_koinly_decimal(net_value_str)
            except ValueError as exc:
                logger.warning("Skipping loan repayment row %d for %s: unparseable amount: %s", row_number, asset, exc)
                continue
            if asset not in accs:
                accs[asset] = _Accumulator()
            accs[asset].repaid_count += 1
            accs[asset].repaid_amount += sent_amount
            accs[asset].repaid_value_eur += repaid_value

    entries: list[LoanActivityEntry] = []
    for asset in sorted(accs):
        a = accs[asset]
        balance = a.received_amount - a.repaid_amount
        if balance == ZERO:
            status, detail = LOAN_STATUS_SETTLED, None
        elif balance < ZERO:
            status, detail = _classify_overpaid_balance(
                a.received_amount, a.repaid_amount, a.received_value_eur
            )
        else:
            status, detail = LOAN_STATUS_OPEN_LOAN, None
        entries.append(
            LoanActivityEntry(
                asset=asset,
                received_count=a.received_count,
                received_amount=a.received_amount,
                received_value_eur=a.received_value_eur,
                repaid_count=a.repaid_count,
                repaid_amount=a.repaid_amount,
                repaid_value_eur=a.repaid_value_eur,
                balance_amount=balance,
                balance_status=status,
                balance_detail=detail,
            )
        )
    return entries


def _classify_overpaid_balance(
    received_amount: Decimal, repaid_amount: Decimal, received_value_eur: Decimal
) -> tuple[str, str | None]:
    """Classify an over-repaid asset (``balance < ZERO``) into a status sentinel.

    Invariant 4: amount-space overshoot classifier. Four branches evaluated in
    this exact precedence order: (b) FIRST repayment-only, then (a) no EUR price,
    then (c) small overshoot, then (d) large overshoot. The branch structure
    guards division-by-zero: branch (b) short-circuits before any division, and
    branches (c)/(d) are only reached when ``received_amount > 0``.

    The branch decision compares the **rounded** ``pct`` against the threshold
    (not the unrounded ``raw_pct``) so the rendered ``balance_detail`` and the
    fill color always agree: a reviewer reading "overshoot 1.0000%" sees the
    same value the classifier used.
    """
    if received_amount == ZERO and repaid_amount > ZERO:
        # Branch (b): repayment-only asset (overshoot unbounded). received_amount == 0,
        # so raw_pct is undefined; set detail directly and do NOT quantize.
        return LOAN_STATUS_OVERPAID_VERIFY, "received_amount=0; repayment-only asset"
    if received_value_eur == ZERO:
        # Branch (a): no EUR price data -> cannot classify the overshoot.
        return LOAN_STATUS_NO_EUR_PRICE, None
    raw_pct = abs(repaid_amount - received_amount) / received_amount * 100
    pct = raw_pct.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    if pct <= LOAN_OVERSHOOT_INTEREST_PCT:
        # Branch (c): small overshoot -> likely in-asset interest.
        return LOAN_STATUS_IN_ASSET_INTEREST, f"overshoot {pct}%"
    # Branch (d): large overshoot -> verify (cross-year loan?).
    return LOAN_STATUS_OVERPAID_VERIFY, f"overshoot {pct}%"
