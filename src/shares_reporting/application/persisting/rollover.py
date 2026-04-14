"""Rollover file export for unmatched securities."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from os import PathLike

from ...domain.collections import TradeCyclePerCompany
from ...domain.constants import ZERO_QUANTITY
from ...domain.value_objects import TradeType
from ...infrastructure.logging_config import create_module_logger
from .excel_utils import safe_remove_file


def export_rollover_file(leftover: str | PathLike[str], leftover_trades: TradeCyclePerCompany) -> None:
    """Export unmatched securities rollover file for next year's FIFO calculations.

    This function creates a CSV file containing all trades that couldn't be matched
    during the FIFO capital gains calculation process. These unmatched securities
    are rolled over to the next tax year to maintain FIFO continuity.

    Args:
        leftover: Output file path for the unmatched securities rollover file
        leftover_trades: Dictionary of trades to be rolled over to next year's calculations
    """
    logger = create_module_logger(__name__)
    logger.info("Generating unmatched securities rollover file: %s", Path(leftover).name)

    safe_remove_file(leftover)
    processed_companies = ZERO_QUANTITY

    with Path(leftover).open("w", newline="") as right_obj:
        writer = csv.DictWriter(
            right_obj,
            fieldnames=[
                "Trades",
                "Header",
                "DataDiscriminator",
                "Asset Category",
                "Currency",
                "Symbol",
                "Date/Time",
                "Quantity",
                "T. Price",
                "C. Price",
                "Proceeds",
                "Comm/Fee",
                "Basis",
                "Realized P/L",
            ],
        )
        writer.writeheader()
        for currency_company, trade_cycle in leftover_trades.items():
            processed_companies += 1
            row = {
                "Trades": "Trades",
                "Header": "Data",
                "DataDiscriminator": "Order",
                "Asset Category": "Stocks",
                "Currency": currency_company.currency.currency,
                "Symbol": currency_company.company.ticker,
            }

            logger.debug("Processing leftover trades for %s (%s)", row["Symbol"], row["Currency"])

            if trade_cycle.has_bought():
                bought_trades = trade_cycle.get(TradeType.BUY)
                logger.debug("Writing %s leftover buy trades for %s", len(bought_trades), row["Symbol"])

                for bought_trade in bought_trades:
                    row["Quantity"] = str(bought_trade.quantity)
                    action = bought_trade.action
                    row["Date/Time"] = str(action.date_time.date()) + ", " + str(action.date_time.time())
                    row["T. Price"] = str(action.price)
                    row["Proceeds"] = str(action.price * bought_trade.quantity)
                    if action.quantity == 0:
                        logger.error(
                            "Trade action has zero quantity for symbol %s - cannot calculate proportional fee",
                            row["Symbol"],
                        )
                        raise ValueError(
                            f"Trade action quantity cannot be zero for symbol {row['Symbol']} at {action.date_time}"
                        )
                    proportional_fee = action.fee * (bought_trade.quantity / action.quantity)
                    row["Comm/Fee"] = str(proportional_fee)
                    row["Basis"] = ""
                    row["Realized P/L"] = ""
                    writer.writerow(row)

    logger.info("Generated unmatched securities rollover file for %s companies", processed_companies)
