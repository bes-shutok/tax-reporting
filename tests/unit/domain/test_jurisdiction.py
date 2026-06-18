"""Unit tests for TaxJurisdictionConfig domain model."""

from __future__ import annotations

from dataclasses import fields
from decimal import Decimal

from tax_reporting.domain.jurisdiction import TaxJurisdictionConfig


class TestTaxJurisdictionConfig:
    """Test suite for TaxJurisdictionConfig dataclass."""

    def test_use_other_gains_report_field_exists(self) -> None:
        """Verify that use_other_gains_report field exists with correct type and default."""
        field_names = {f.name for f in fields(TaxJurisdictionConfig)}
        assert "use_other_gains_report" in field_names, "use_other_gains_report field must exist"

        # Create instance with minimal required params to check default value
        config = TaxJurisdictionConfig(
            country="PT",
            fiscal_year=2025,
            exclude_loan_repayment_gains=True,
            zero_basis_review_threshold=Decimal("100"),
        )

        # Verify field is boolean
        assert hasattr(config, "use_other_gains_report"), "use_other_gains_report attribute must exist"
        assert isinstance(config.use_other_gains_report, bool), "use_other_gains_report must be bool type"

        # Verify default is False
        assert config.use_other_gains_report is False, "use_other_gains_report default must be False"

    def test_accepts_zero_basis_review_min_proceeds(self) -> None:
        """Verify that zero_basis_review_min_proceeds can be set and read back."""
        config = TaxJurisdictionConfig(
            country="PT",
            fiscal_year=2025,
            exclude_loan_repayment_gains=True,
            zero_basis_review_threshold=Decimal("100"),
            zero_basis_review_min_proceeds=Decimal("10"),
        )
        assert config.zero_basis_review_min_proceeds == Decimal("10")

    def test_defaults_zero_basis_review_min_proceeds_to_production_default_when_absent(self) -> None:
        """When the field is not supplied, it defaults to ``DEFAULT_ZERO_BASIS_REVIEW_MIN_PROCEEDS`` (10 EUR).

        This aligns the dataclass default with the production config.ini default so direct
        construction matches the loaded config. Callers who want prior flag-everything
        behavior must pass ``zero_basis_review_min_proceeds=Decimal("0")`` explicitly.
        """
        from tax_reporting.domain.jurisdiction import DEFAULT_ZERO_BASIS_REVIEW_MIN_PROCEEDS

        config = TaxJurisdictionConfig(
            country="PT",
            fiscal_year=2025,
            exclude_loan_repayment_gains=True,
            zero_basis_review_threshold=Decimal("100"),
        )
        assert config.zero_basis_review_min_proceeds == DEFAULT_ZERO_BASIS_REVIEW_MIN_PROCEEDS
        assert config.zero_basis_review_min_proceeds == Decimal("10")
