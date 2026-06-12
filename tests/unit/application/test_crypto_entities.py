"""Tests for crypto entities module (Task 1 extraction)."""

from __future__ import annotations

import pytest
from decimal import Decimal

from tax_reporting.application.crypto.entities import (
    RewardTaxClassification,
    OperatorOrigin,
    CapitalGainPeriodStats,
    CryptoCapitalGainStats,
    CryptoCapitalGainEntry,
    LoanActivityEntry,
    CryptoRewardIncomeEntry,
    AggregatedRewardIncomeEntry,
    HoldingsSnapshot,
    CryptoReconciliationSummary,
    CryptoSkippedZeroValueToken,
    CryptoCompletePdfSummary,
    CryptoReviewEntry,
    CryptoTaxReport,
)


class TestEntitiesImport:
    """Verify all entities are accessible from crypto.entities module."""

    def test_reward_tax_classification_enum_exists(self) -> None:
        """RewardTaxClassification enum should be importable."""
        assert RewardTaxClassification.TAXABLE_NOW.value == "taxable_now"
        assert RewardTaxClassification.DEFERRED_BY_LAW.value == "deferred_by_law"

    def test_operator_origin_dataclass_exists(self) -> None:
        """OperatorOrigin dataclass should be importable."""
        origin = OperatorOrigin(
            platform="Test Platform",
            service_scope="crypto",
            operator_entity="Test Entity",
            operator_country="US",
            source_url="https://example.com",
            source_checked_on="2026-01-01",
            confidence="high",
            review_required=False,
        )
        assert origin.platform == "Test Platform"
        assert origin.operator_country == "US"

    def test_capital_gain_period_stats_exists(self) -> None:
        """CapitalGainPeriodStats dataclass should be importable."""
        stats = CapitalGainPeriodStats(
            count=1,
            cost_total_eur=Decimal("100"),
            proceeds_total_eur=Decimal("150"),
            gain_loss_total_eur=Decimal("50"),
        )
        assert stats.count == 1
        assert stats.gain_loss_total_eur == Decimal("50")

    def test_crypto_capital_gain_stats_exists(self) -> None:
        """CryptoCapitalGainStats dataclass should be importable."""
        st = CapitalGainPeriodStats(
            count=1,
            cost_total_eur=Decimal("100"),
            proceeds_total_eur=Decimal("150"),
            gain_loss_total_eur=Decimal("50"),
        )
        stats = CryptoCapitalGainStats(
            short_term=st,
            long_term=st,
            mixed=st,
            unknown=st,
            grand_total=st,
        )
        assert stats.short_term.count == 1

    def test_crypto_capital_gain_entry_exists(self) -> None:
        """CryptoCapitalGainEntry dataclass should be importable."""
        origin = OperatorOrigin(
            platform="Test",
            service_scope="crypto",
            operator_entity="Test Entity",
            operator_country="US",
            source_url="https://example.com",
            source_checked_on="2026-01-01",
            confidence="high",
            review_required=False,
        )
        entry = CryptoCapitalGainEntry(
            disposal_date="2026-01-01",
            acquisition_date="2025-01-01",
            asset="BTC",
            amount=Decimal("1"),
            cost_eur=Decimal("100"),
            proceeds_eur=Decimal("150"),
            gain_loss_eur=Decimal("50"),
            holding_period="long-term",
            wallet="Test Wallet",
            platform="Test",
            chain="Bitcoin",
            operator_origin=origin,
            annex_hint="G1",
            review_required=False,
            notes="",
        )
        assert entry.asset == "BTC"
        assert entry.gain_loss_eur == Decimal("50")

    def test_loan_activity_entry_exists(self) -> None:
        """LoanActivityEntry dataclass should be importable."""
        entry = LoanActivityEntry(
            asset="WBTC",
            received_count=1,
            received_amount=Decimal("1"),
            received_value_eur=Decimal("50000"),
            repaid_count=0,
            repaid_amount=Decimal("0"),
            repaid_value_eur=Decimal("0"),
            balance_amount=Decimal("1"),
            balance_status="Open loan",
        )
        assert entry.asset == "WBTC"
        assert entry.balance_status == "Open loan"

    def test_crypto_reward_income_entry_exists(self) -> None:
        """CryptoRewardIncomeEntry dataclass should be importable with foreign_tax_eur field."""
        origin = OperatorOrigin(
            platform="Test",
            service_scope="crypto",
            operator_entity="Test Entity",
            operator_country="US",
            source_url="https://example.com",
            source_checked_on="2026-01-01",
            confidence="high",
            review_required=False,
        )
        entry = CryptoRewardIncomeEntry(
            date="2026-01-01",
            asset="USDT",
            amount=Decimal("100"),
            value_eur=Decimal("100"),
            income_label="Reward",
            source_type="staking",
            wallet="Test Wallet",
            platform="Test",
            chain="Ethereum",
            operator_origin=origin,
            annex_hint="J",
            review_required=False,
            description="Staking reward",
            foreign_tax_eur=Decimal("10"),  # Verify field exists
        )
        assert entry.asset == "USDT"
        assert entry.foreign_tax_eur == Decimal("10")

    def test_aggregated_reward_income_entry_exists(self) -> None:
        """AggregatedRewardIncomeEntry dataclass should be importable."""
        entry = AggregatedRewardIncomeEntry(
            income_code="401",
            source_country="US",
            gross_income_eur=Decimal("100"),
            foreign_tax_eur=Decimal("10"),
            raw_row_count=5,
            chains=("Ethereum", "Solana"),
            description="Income code 401 from US",
        )
        assert entry.income_code == "401"
        assert entry.raw_row_count == 5

    def test_holdings_snapshot_exists(self) -> None:
        """HoldingsSnapshot dataclass should be importable."""
        snapshot = HoldingsSnapshot(
            asset_rows=10,
            total_cost_eur=Decimal("1000"),
            total_value_eur=Decimal("1500"),
        )
        assert snapshot.asset_rows == 10

    def test_crypto_reconciliation_summary_exists(self) -> None:
        """CryptoReconciliationSummary dataclass should be importable."""
        snapshot = HoldingsSnapshot(
            asset_rows=10,
            total_cost_eur=Decimal("1000"),
            total_value_eur=Decimal("1500"),
        )
        summary = CryptoReconciliationSummary(
            capital_rows=5,
            reward_rows=3,
            short_term_rows=2,
            long_term_rows=2,
            mixed_rows=1,
            unknown_rows=0,
            capital_cost_total_eur=Decimal("500"),
            capital_proceeds_total_eur=Decimal("600"),
            capital_gain_total_eur=Decimal("100"),
            reward_total_eur=Decimal("50"),
            opening_holdings=snapshot,
            closing_holdings=snapshot,
        )
        assert summary.capital_rows == 5
        assert summary.reward_rows == 3

    def test_crypto_skipped_zero_value_token_exists(self) -> None:
        """CryptoSkippedZeroValueToken dataclass should be importable."""
        token = CryptoSkippedZeroValueToken(
            source_section="income",
            asset="UNKNOWN",
            count=5,
            suspicious=False,
        )
        assert token.asset == "UNKNOWN"
        assert token.count == 5

    def test_crypto_complete_pdf_summary_exists(self) -> None:
        """CryptoCompletePdfSummary dataclass should be importable."""
        summary = CryptoCompletePdfSummary(
            period="1 January 2026 to 31 December 2026",
            timezone="Europe/Lisbon",
            extracted_tokens=150,
        )
        assert summary.extracted_tokens == 150

    def test_crypto_review_entry_exists(self) -> None:
        """CryptoReviewEntry dataclass should be importable."""
        entry = CryptoReviewEntry(
            source_section="capital_gains",
            date="2026-01-01",
            asset="SCAM",
            platform="Unknown",
            review_reason="Potential homoglyph scam token",
            is_suspicious=True,
        )
        assert entry.is_suspicious is True

    def test_crypto_tax_report_exists(self) -> None:
        """CryptoTaxReport dataclass should be importable."""
        origin = OperatorOrigin(
            platform="Test",
            service_scope="crypto",
            operator_entity="Test Entity",
            operator_country="US",
            source_url="https://example.com",
            source_checked_on="2026-01-01",
            confidence="high",
            review_required=False,
        )
        entry = CryptoCapitalGainEntry(
            disposal_date="2026-01-01",
            acquisition_date="2025-01-01",
            asset="BTC",
            amount=Decimal("1"),
            cost_eur=Decimal("100"),
            proceeds_eur=Decimal("150"),
            gain_loss_eur=Decimal("50"),
            holding_period="long-term",
            wallet="Test Wallet",
            platform="Test",
            chain="Bitcoin",
            operator_origin=origin,
            annex_hint="G1",
            review_required=False,
            notes="",
        )
        st = CapitalGainPeriodStats(
            count=1,
            cost_total_eur=Decimal("100"),
            proceeds_total_eur=Decimal("150"),
            gain_loss_total_eur=Decimal("50"),
        )
        stats = CryptoCapitalGainStats(
            short_term=st,
            long_term=st,
            mixed=st,
            unknown=st,
            grand_total=st,
        )
        snapshot = HoldingsSnapshot(
            asset_rows=10,
            total_cost_eur=Decimal("1000"),
            total_value_eur=Decimal("1500"),
        )
        reconciliation = CryptoReconciliationSummary(
            capital_rows=1,
            reward_rows=0,
            short_term_rows=1,
            long_term_rows=0,
            mixed_rows=0,
            unknown_rows=0,
            capital_cost_total_eur=Decimal("100"),
            capital_proceeds_total_eur=Decimal("150"),
            capital_gain_total_eur=Decimal("50"),
            reward_total_eur=Decimal("0"),
            opening_holdings=snapshot,
            closing_holdings=snapshot,
        )
        report = CryptoTaxReport(
            tax_year=2026,
            capital_entries=[entry],
            reward_entries=[],
            reconciliation=reconciliation,
            capital_gain_stats=stats,
        )
        assert report.tax_year == 2026
        assert len(report.capital_entries) == 1


class TestOperatorOriginValidation:
    """Verify OperatorOrigin validation logic from original __post_init__."""

    def test_service_start_date_after_valid_from_raises_error(self) -> None:
        """OperatorOrigin with service_start_date > valid_from should raise ValueError."""
        with pytest.raises(ValueError, match="service_start_date.*must be on or before valid_from"):
            OperatorOrigin(
                platform="Test Platform",
                service_scope="crypto",
                operator_entity="Test Entity",
                operator_country="US",
                source_url="https://example.com",
                source_checked_on="2026-01-01",
                confidence="high",
                review_required=False,
                service_start_date="2026-06-01",
                valid_from="2026-01-01",
            )

    def test_service_start_date_after_valid_until_raises_error(self) -> None:
        """OperatorOrigin with service_start_date > valid_until should raise ValueError."""
        with pytest.raises(ValueError, match="service_start_date.*must be on or before valid_until"):
            OperatorOrigin(
                platform="Test Platform",
                service_scope="crypto",
                operator_entity="Test Entity",
                operator_country="US",
                source_url="https://example.com",
                source_checked_on="2026-01-01",
                confidence="high",
                review_required=False,
                service_start_date="2026-06-01",
                valid_until="2026-03-01",
            )

    def test_valid_until_before_valid_from_raises_error(self) -> None:
        """OperatorOrigin with valid_until < valid_from should raise ValueError."""
        with pytest.raises(ValueError, match="valid_until.*must be on or after valid_from"):
            OperatorOrigin(
                platform="Test Platform",
                service_scope="crypto",
                operator_entity="Test Entity",
                operator_country="US",
                source_url="https://example.com",
                source_checked_on="2026-01-01",
                confidence="high",
                review_required=False,
                valid_from="2026-06-01",
                valid_until="2026-03-01",
            )

    def test_review_required_without_review_reason_raises_error(self) -> None:
        """OperatorOrigin with review_required=True and no review_reason should raise ValueError."""
        with pytest.raises(ValueError, match="review_reason must be set when review_required=True"):
            OperatorOrigin(
                platform="Test Platform",
                service_scope="crypto",
                operator_entity="Test Entity",
                operator_country="US",
                source_url="https://example.com",
                source_checked_on="2026-01-01",
                confidence="high",
                review_required=True,
                review_reason=None,
            )


class TestCapitalGainEntryValidation:
    """Verify CryptoCapitalGainEntry validation logic from original __post_init__."""

    def test_review_required_without_review_reason_raises_error(self) -> None:
        """CryptoCapitalGainEntry with review_required=True and no review_reason should raise ValueError."""
        origin = OperatorOrigin(
            platform="Test",
            service_scope="crypto",
            operator_entity="Test Entity",
            operator_country="US",
            source_url="https://example.com",
            source_checked_on="2026-01-01",
            confidence="high",
            review_required=False,
        )
        with pytest.raises(ValueError, match="review_reason must be set when review_required=True"):
            CryptoCapitalGainEntry(
                disposal_date="2026-01-01",
                acquisition_date="2025-01-01",
                asset="BTC",
                amount=Decimal("1"),
                cost_eur=Decimal("100"),
                proceeds_eur=Decimal("150"),
                gain_loss_eur=Decimal("50"),
                holding_period="long-term",
                wallet="Test Wallet",
                platform="Test",
                chain="Bitcoin",
                operator_origin=origin,
                annex_hint="G1",
                review_required=True,
                review_reason=None,
                notes="",
            )


class TestRewardIncomeEntryValidation:
    """Verify CryptoRewardIncomeEntry validation logic from original __post_init__."""

    def test_review_required_without_review_reason_raises_error(self) -> None:
        """CryptoRewardIncomeEntry with review_required=True and no review_reason should raise ValueError."""
        origin = OperatorOrigin(
            platform="Test",
            service_scope="crypto",
            operator_entity="Test Entity",
            operator_country="US",
            source_url="https://example.com",
            source_checked_on="2026-01-01",
            confidence="high",
            review_required=False,
        )
        with pytest.raises(ValueError, match="review_reason must be set when review_required=True"):
            CryptoRewardIncomeEntry(
                date="2026-01-01",
                asset="USDT",
                amount=Decimal("100"),
                value_eur=Decimal("100"),
                income_label="Reward",
                source_type="staking",
                wallet="Test Wallet",
                platform="Test",
                chain="Ethereum",
                operator_origin=origin,
                annex_hint="J",
                review_required=True,
                review_reason=None,
                description="Staking reward",
            )
