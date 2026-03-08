"""Tests for placeholder buy transaction functionality."""

from decimal import Decimal

import pytest

from shares_reporting.application.transformation import calculate_fifo_gains
from shares_reporting.domain.constants import PLACEHOLDER_YEAR
from shares_reporting.domain.entities import (
    CurrencyCompany,
    QuantitatedTradeAction,
    TradeAction,
    TradeCycle,
)
from shares_reporting.domain.value_objects import Company, Currency, parse_company, parse_currency


@pytest.mark.unit
class TestPlaceholderBuys:
    """Test placeholder buy transaction creation for unmatched sells."""

    def test_calculate_fifo_gains_creates_placeholder_for_sells_without_buys(self):
        """Test that sells without buys get placeholder buy transactions."""
        # Arrange
        company = parse_company("AAPL")
        currency = parse_currency("USD")
        quantity = "100"
        trade_date = "2023-06-15, 10:30:00"

        sell_action = TradeAction(
            company=company,
            date_time=trade_date,
            currency=currency,
            quantity="-" + quantity,
            price="150.00",
            fee="1.00",
        )

        trade_cycle_per_company = {
            CurrencyCompany(currency, company): TradeCycle(
                bought=[],
                sold=[QuantitatedTradeAction(quantity=Decimal(quantity), action=sell_action)],
            )
        }

        leftover_trades = {}
        capital_gains = {}

        # Act
        calculate_fifo_gains(trade_cycle_per_company, leftover_trades, capital_gains)

        # Assert - should create capital gains (not leftover)
        assert len(capital_gains) == 1
        assert len(leftover_trades) == 0

        currency_company = CurrencyCompany(currency, company)
        gain_lines = capital_gains[currency_company]
        assert len(gain_lines) == 1

        # Verify placeholder buy date
        gain_line = gain_lines[0]
        assert gain_line.get_buy_date().year == PLACEHOLDER_YEAR
        assert gain_line.get_buy_date().month == 1
        assert gain_line.get_buy_date().day == 1

    def test_buys_without_sells_still_go_to_leftover(self):
        """Test that buys without sells are still added to leftover."""
        # Arrange
        company = Company(ticker="GOOGL")
        currency = Currency(currency="USD")

        buy_action = TradeAction(
            company=company,
            date_time="2023-06-15, 10:30:00",
            currency=currency,
            quantity="50",
            price="120.00",
            fee="1.00",
        )

        trade_cycle_per_company = {
            CurrencyCompany(currency, company): TradeCycle(
                bought=[QuantitatedTradeAction(quantity=Decimal("50"), action=buy_action)],
                sold=[],
            )
        }

        leftover_trades = {}
        capital_gains = {}

        # Act
        calculate_fifo_gains(trade_cycle_per_company, leftover_trades, capital_gains)

        # Assert
        assert len(leftover_trades) == 1
        assert len(capital_gains) == 0

    def test_partial_sell_mismatch_creates_placeholder_for_remaining_sells(self):
        """Test that partially-unmatched sells get placeholder buys, not silently dropped."""
        company = Company(ticker="TSLA")
        currency = Currency(currency="USD")

        buy_action = TradeAction(
            company=company,
            date_time="2023-05-01, 10:00:00",
            currency=currency,
            quantity="3",
            price="200.00",
            fee="1.00",
        )
        sell_action = TradeAction(
            company=company,
            date_time="2023-06-15, 10:30:00",
            currency=currency,
            quantity="-10",
            price="250.00",
            fee="1.00",
        )

        trade_cycle_per_company = {
            CurrencyCompany(currency, company): TradeCycle(
                bought=[QuantitatedTradeAction(quantity=Decimal("3"), action=buy_action)],
                sold=[QuantitatedTradeAction(quantity=Decimal("10"), action=sell_action)],
            )
        }

        leftover_trades = {}
        capital_gains = {}

        calculate_fifo_gains(trade_cycle_per_company, leftover_trades, capital_gains)

        # All 10 sold shares must appear in capital gains — none silently dropped
        currency_company = CurrencyCompany(currency, company)
        assert currency_company in capital_gains
        gain_lines = capital_gains[currency_company]
        assert len(gain_lines) == 2

        total_sold_qty = sum(line.sell_quantity() for line in gain_lines)
        assert total_sold_qty == Decimal("10")

        # The second line uses a placeholder buy (PLACEHOLDER_YEAR)
        placeholder_lines = [line for line in gain_lines if line.get_buy_date().year == PLACEHOLDER_YEAR]
        assert len(placeholder_lines) == 1
        assert placeholder_lines[0].sell_quantity() == Decimal("7")

        # No unmatched sells in leftover
        if currency_company in leftover_trades:
            assert not leftover_trades[currency_company].has_sold()

    def test_normal_matching_still_works(self):
        """Test that normal buy/sell matching still works correctly."""
        # Arrange
        company = Company(ticker="MSFT")
        currency = Currency(currency="USD")

        buy_action = TradeAction(
            company=company,
            date_time="2023-05-01, 10:00:00",
            currency=currency,
            quantity="10",
            price="300.00",
            fee="1.00",
        )

        sell_action = TradeAction(
            company=company,
            date_time="2023-06-15, 10:30:00",
            currency=currency,
            quantity="-10",
            price="320.00",
            fee="1.00",
        )

        trade_cycle_per_company = {
            CurrencyCompany(currency, company): TradeCycle(
                bought=[QuantitatedTradeAction(quantity=Decimal("10"), action=buy_action)],
                sold=[QuantitatedTradeAction(quantity=Decimal("10"), action=sell_action)],
            )
        }

        leftover_trades = {}
        capital_gains = {}

        # Act
        calculate_fifo_gains(trade_cycle_per_company, leftover_trades, capital_gains)

        # Assert
        assert len(capital_gains) == 1
        currency_company = CurrencyCompany(currency, company)
        gain_lines = capital_gains[currency_company]
        assert len(gain_lines) == 1

        # Should NOT be placeholder (year should be 2023, not PLACEHOLDER_YEAR)
        gain_line = gain_lines[0]
        assert gain_line.get_buy_date().year == 2023
