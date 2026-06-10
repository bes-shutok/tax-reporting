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
