"""Tests for configuration management functionality."""

import configparser
import logging
from decimal import Decimal
from pathlib import Path

import pytest

from tax_reporting.infrastructure.config import (
    Config,
    ConversionRate,
    TaxJurisdictionConfig,
    _load_security_config,
    _load_tax_jurisdiction_config,
)
from tax_reporting.infrastructure.validation import SecurityConfig

_TEST_JURISDICTION = TaxJurisdictionConfig(
    country="PT", fiscal_year=2025, exclude_loan_repayment_gains=False, zero_basis_review_threshold=Decimal("50")
)


@pytest.mark.unit
class TestConfig:
    """Test configuration data structure."""

    def test_config_creation(self):
        """Test Config object creation with basic parameters."""
        base_currency = "EUR"
        rates = [
            ConversionRate(base="EUR", calculated="USD", rate=Decimal("1.2")),
            ConversionRate(base="EUR", calculated="GBP", rate=Decimal("0.85")),
        ]

        config = Config(base=base_currency, rates=rates, tax_jurisdiction=_TEST_JURISDICTION)
        assert config.base == base_currency
        assert len(config.rates) == 2
        assert config.security is not None  # Should have default security config

    def test_config_with_custom_security(self):
        """Test Config object with custom security settings."""
        base_currency = "EUR"
        rates = []
        security = SecurityConfig(max_file_size_mb=50)

        config = Config(base=base_currency, rates=rates, tax_jurisdiction=_TEST_JURISDICTION, security=security)
        assert config.base == base_currency
        assert len(config.rates) == 0
        assert config.security.max_file_size_mb == 50


@pytest.mark.unit
class TestConversionRate:
    """Test conversion rate named tuple."""

    def test_conversion_rate_creation(self):
        """Test ConversionRate creation."""
        rate = ConversionRate(base="EUR", calculated="USD", rate=Decimal("1.2"))
        assert rate.base == "EUR"
        assert rate.calculated == "USD"
        assert rate.rate == Decimal("1.2")


@pytest.mark.unit
class TestLoadSecurityConfig:
    """Test loading security configuration section."""

    def test_load_security_config_with_values(self):
        """Test loading security config with all values."""
        config = configparser.ConfigParser()
        config["SECURITY"] = {
            "MAX_FILE_SIZE_MB": "50",
            "MAX_TICKER_LENGTH": "8",
            "MAX_CURRENCY_LENGTH": "5",
            "ALLOWED_EXTENSIONS": ".csv,.xlsx",
            "MAX_QUANTITY_VALUE": "1000000",
            "MAX_PRICE_VALUE": "100000",
            "MAX_FILENAME_LENGTH": "100",
        }

        logger = logging.getLogger(__name__)
        security_config = _load_security_config(config, logger)

        assert security_config.max_file_size_mb == 50
        assert security_config.max_ticker_length == 8
        assert security_config.max_currency_length == 5
        assert ".csv" in security_config.allowed_extensions
        assert ".xlsx" in security_config.allowed_extensions
        assert security_config.max_quantity_value == 1000000
        assert security_config.max_price_value == 100000
        assert security_config.max_filename_length == 100

    def test_load_security_config_missing_section(self):
        """Test loading security config when section is missing."""
        config = configparser.ConfigParser()
        config["OTHER"] = {"something": "value"}

        logger = logging.getLogger(__name__)
        security_config = _load_security_config(config, logger)

        # Should return default config
        assert security_config.max_file_size_mb > 0
        assert security_config.max_ticker_length > 0

    def test_load_security_config_with_invalid_values(self):
        """Test loading security config with invalid values."""
        config = configparser.ConfigParser()
        config["SECURITY"] = {
            "MAX_FILE_SIZE_MB": "invalid_number",
            "ALLOWED_EXTENSIONS": ".csv,.txt",
        }

        logger = logging.getLogger(__name__)
        # Should fall back to defaults when values are invalid
        security_config = _load_security_config(config, logger)
        assert security_config.max_file_size_mb > 0
        assert ".csv" in security_config.allowed_extensions


@pytest.mark.unit
class TestConfigValidation:
    """Test configuration validation logic."""

    def test_base_currency_validation_rejects_mismatched_rate(self, tmp_path, monkeypatch):
        """load_configuration_from_file raises ValueError when a rate key has a different base currency."""
        from tax_reporting.infrastructure.config import load_configuration_from_file

        (tmp_path / "config.ini").write_text(
            "[COMMON]\nTARGET CURRENCY = EUR\n"
            "[EXCHANGE RATES]\nUSD/EUR = 0.9\n"
        )
        monkeypatch.chdir(tmp_path)
        with pytest.raises(ValueError, match="Base currency mismatch"):
            load_configuration_from_file()

    def test_complete_config_construction(self, tmp_path, monkeypatch):
        """load_configuration_from_file produces a Config with correct base, rates and security defaults."""
        from tax_reporting.infrastructure.config import load_configuration_from_file

        (tmp_path / "config.ini").write_text(
            "[COMMON]\nTARGET CURRENCY = EUR\n"
            "[EXCHANGE RATES]\nEUR/USD = 1.2\nEUR/GBP = 0.85\n"
        )
        monkeypatch.chdir(tmp_path)
        cfg = load_configuration_from_file()
        assert cfg.base == "EUR"
        assert len(cfg.rates) == 2
        assert cfg.rates[0].base == "EUR"
        assert cfg.rates[0].calculated == "USD"
        assert cfg.rates[0].rate == Decimal("1.2")
        assert cfg.rates[1].calculated == "GBP"
        assert cfg.rates[1].rate == Decimal("0.85")
        assert cfg.security.max_file_size_mb > 0
        assert ".csv" in cfg.security.allowed_extensions


@pytest.mark.unit
class TestLoadTaxJurisdictionConfig:
    """Tests for TaxJurisdictionConfig parsing from config file."""

    _PT_TOML = "[meta]\nfiscal_year = 2025\n[countries.PT]\nexclude_loan_repayment_gains = true\n"
    _NO_COUNTRY_TOML = "[meta]\nfiscal_year = 2025\n"

    def _make_config(self, section_entries: dict | None) -> configparser.ConfigParser:
        cp = configparser.ConfigParser()
        cp.optionxform = lambda optionstr: optionstr
        if section_entries is not None:
            cp["TAX JURISDICTION"] = section_entries
        return cp

    def test_load_tax_jurisdiction_config_parses_country_and_year(self, tmp_path, monkeypatch):
        import tax_reporting.infrastructure.config as config_module
        monkeypatch.setattr(config_module, "_DECISION_POINTS_DIR", tmp_path)
        (tmp_path / "2025.toml").write_text(self._PT_TOML)
        cp = self._make_config({"TAX_COUNTRY": "PT", "FISCAL_YEAR": "2025"})
        logger = logging.getLogger(__name__)
        result = _load_tax_jurisdiction_config(cp, logger)
        assert result.country == "PT"
        assert result.fiscal_year == 2025
        assert result.exclude_loan_repayment_gains is True

    def test_load_tax_jurisdiction_config_defaults_when_section_absent(self, tmp_path, monkeypatch):
        import tax_reporting.infrastructure.config as config_module
        monkeypatch.setattr(config_module, "_DECISION_POINTS_DIR", tmp_path)
        (tmp_path / "2025.toml").write_text(self._PT_TOML)
        cp = configparser.ConfigParser()
        cp.optionxform = lambda optionstr: optionstr
        logger = logging.getLogger(__name__)
        result = _load_tax_jurisdiction_config(cp, logger)
        assert result.country == "PT"
        assert result.fiscal_year == 2025
        assert result.exclude_loan_repayment_gains is True

    def test_load_tax_jurisdiction_config_unknown_country_defaults_to_no_filter(self, tmp_path, monkeypatch):
        import tax_reporting.infrastructure.config as config_module
        monkeypatch.setattr(config_module, "_DECISION_POINTS_DIR", tmp_path)
        (tmp_path / "2025.toml").write_text(self._NO_COUNTRY_TOML)
        cp = self._make_config({"TAX_COUNTRY": "US", "FISCAL_YEAR": "2025"})
        logger = logging.getLogger(__name__)
        result = _load_tax_jurisdiction_config(cp, logger)
        assert result.country == "US"
        assert result.exclude_loan_repayment_gains is False

    def test_tax_jurisdiction_config_country_code_normalized_to_upper(self, tmp_path, monkeypatch):
        import tax_reporting.infrastructure.config as config_module
        monkeypatch.setattr(config_module, "_DECISION_POINTS_DIR", tmp_path)
        (tmp_path / "2025.toml").write_text(self._PT_TOML)
        cp = self._make_config({"TAX_COUNTRY": "pt", "FISCAL_YEAR": "2025"})
        logger = logging.getLogger(__name__)
        result = _load_tax_jurisdiction_config(cp, logger)
        assert result.country == "PT"

    def test_tax_jurisdiction_config_invalid_fiscal_year_raises(self):
        cp = self._make_config({"TAX_COUNTRY": "PT", "FISCAL_YEAR": "abc"})
        logger = logging.getLogger(__name__)
        with pytest.raises(ValueError, match="Invalid FISCAL_YEAR"):
            _load_tax_jurisdiction_config(cp, logger)

    def test_tax_jurisdiction_config_invalid_threshold_raises(self):
        cp = self._make_config({"TAX_COUNTRY": "PT", "FISCAL_YEAR": "2025", "ZERO_BASIS_REVIEW_THRESHOLD": "abc"})
        logger = logging.getLogger(__name__)
        with pytest.raises(ValueError, match="Invalid ZERO_BASIS_REVIEW_THRESHOLD"):
            _load_tax_jurisdiction_config(cp, logger)

    def test_tax_jurisdiction_config_zero_basis_threshold_from_config(self, tmp_path, monkeypatch):
        import tax_reporting.infrastructure.config as config_module
        monkeypatch.setattr(config_module, "_DECISION_POINTS_DIR", tmp_path)
        (tmp_path / "2025.toml").write_text(self._PT_TOML)
        cp = self._make_config({"TAX_COUNTRY": "PT", "FISCAL_YEAR": "2025", "ZERO_BASIS_REVIEW_THRESHOLD": "100"})
        logger = logging.getLogger(__name__)
        result = _load_tax_jurisdiction_config(cp, logger)
        assert result.zero_basis_review_threshold == Decimal("100")

    def test_tax_jurisdiction_config_zero_basis_threshold_defaults_to_50(self, tmp_path, monkeypatch):
        import tax_reporting.infrastructure.config as config_module
        monkeypatch.setattr(config_module, "_DECISION_POINTS_DIR", tmp_path)
        (tmp_path / "2025.toml").write_text(self._PT_TOML)
        cp = self._make_config({"TAX_COUNTRY": "PT", "FISCAL_YEAR": "2025"})
        logger = logging.getLogger(__name__)
        result = _load_tax_jurisdiction_config(cp, logger)
        assert result.zero_basis_review_threshold == Decimal("50")

    def test_tax_jurisdiction_config_empty_country_raises(self):
        cp = self._make_config({"TAX_COUNTRY": "", "FISCAL_YEAR": "2025"})
        logger = logging.getLogger(__name__)
        with pytest.raises(ValueError, match="TAX_COUNTRY.*must not be empty"):
            _load_tax_jurisdiction_config(cp, logger)

    def test_tax_jurisdiction_config_threshold_nan_raises(self):
        """NaN is rejected as a threshold value."""
        cp = self._make_config({
            "TAX_COUNTRY": "PT",
            "FISCAL_YEAR": "2025",
            "ZERO_BASIS_REVIEW_THRESHOLD": "NaN",
        })
        logger = logging.getLogger(__name__)
        with pytest.raises(ValueError, match="finite non-negative"):
            _load_tax_jurisdiction_config(cp, logger)

    def test_tax_jurisdiction_config_threshold_infinity_raises(self):
        """Infinity is rejected as a threshold value."""
        cp = self._make_config({
            "TAX_COUNTRY": "PT",
            "FISCAL_YEAR": "2025",
            "ZERO_BASIS_REVIEW_THRESHOLD": "Infinity",
        })
        logger = logging.getLogger(__name__)
        with pytest.raises(ValueError, match="finite non-negative"):
            _load_tax_jurisdiction_config(cp, logger)

    def test_tax_jurisdiction_config_threshold_negative_raises(self):
        """Negative threshold is rejected."""
        cp = self._make_config({
            "TAX_COUNTRY": "PT",
            "FISCAL_YEAR": "2025",
            "ZERO_BASIS_REVIEW_THRESHOLD": "-10",
        })
        logger = logging.getLogger(__name__)
        with pytest.raises(ValueError, match="finite non-negative"):
            _load_tax_jurisdiction_config(cp, logger)

    def test_load_configuration_from_file_includes_tax_jurisdiction(self, tmp_path, monkeypatch):
        """Integration: load_configuration_from_file threads TAX JURISDICTION through to Config."""
        import tax_reporting.infrastructure.config as config_module
        from tax_reporting.infrastructure.config import load_configuration_from_file

        dp_dir = tmp_path / "decision_points"
        _write_toml(dp_dir, _MINIMAL_VALID_TOML + "[countries.PT]\nexclude_loan_repayment_gains = true\n")
        monkeypatch.setattr(config_module, "_DECISION_POINTS_DIR", dp_dir)

        (tmp_path / "config.ini").write_text(
            "[COMMON]\nTARGET CURRENCY = EUR\n"
            "[EXCHANGE RATES]\nEUR/USD = 1.0\n"
            "[TAX JURISDICTION]\nTAX_COUNTRY = PT\nFISCAL_YEAR = 2025\n"
            "ZERO_BASIS_REVIEW_THRESHOLD = 75\n"
        )
        monkeypatch.chdir(tmp_path)
        cfg = load_configuration_from_file()
        assert cfg.tax_jurisdiction.country == "PT"
        assert cfg.tax_jurisdiction.fiscal_year == 2025
        assert cfg.tax_jurisdiction.zero_basis_review_threshold == Decimal("75")
        assert cfg.tax_jurisdiction.exclude_loan_repayment_gains is True

    def test_reads_zero_basis_review_min_proceeds_from_config_ini(self, tmp_path, monkeypatch):
        """ZERO_BASIS_REVIEW_MIN_PROCEEDS in [TAX JURISDICTION] is parsed into the config."""
        import tax_reporting.infrastructure.config as config_module
        monkeypatch.setattr(config_module, "_DECISION_POINTS_DIR", tmp_path)
        (tmp_path / "2025.toml").write_text(self._PT_TOML)
        cp = self._make_config({
            "TAX_COUNTRY": "PT",
            "FISCAL_YEAR": "2025",
            "ZERO_BASIS_REVIEW_MIN_PROCEEDS": "10",
        })
        logger = logging.getLogger(__name__)
        result = _load_tax_jurisdiction_config(cp, logger)
        assert result.zero_basis_review_min_proceeds == Decimal("10")

    def test_falls_back_to_default_when_key_absent(self, tmp_path, monkeypatch):
        """When ZERO_BASIS_REVIEW_MIN_PROCEEDS is absent, DEFAULT_ZERO_BASIS_REVIEW_MIN_PROCEEDS is used."""
        import tax_reporting.infrastructure.config as config_module
        from tax_reporting.infrastructure.config import DEFAULT_ZERO_BASIS_REVIEW_MIN_PROCEEDS
        monkeypatch.setattr(config_module, "_DECISION_POINTS_DIR", tmp_path)
        (tmp_path / "2025.toml").write_text(self._PT_TOML)
        cp = self._make_config({"TAX_COUNTRY": "PT", "FISCAL_YEAR": "2025"})
        logger = logging.getLogger(__name__)
        result = _load_tax_jurisdiction_config(cp, logger)
        assert result.zero_basis_review_min_proceeds == DEFAULT_ZERO_BASIS_REVIEW_MIN_PROCEEDS

    def test_rejects_invalid_zero_basis_review_min_proceeds(self):
        """Non-numeric ZERO_BASIS_REVIEW_MIN_PROCEEDS raises ValueError with raw value in message."""
        cp = self._make_config({
            "TAX_COUNTRY": "PT",
            "FISCAL_YEAR": "2025",
            "ZERO_BASIS_REVIEW_MIN_PROCEEDS": "abc",
        })
        logger = logging.getLogger(__name__)
        with pytest.raises(ValueError, match="abc"):
            _load_tax_jurisdiction_config(cp, logger)

    def test_rejects_negative_zero_basis_review_min_proceeds(self):
        """Negative ZERO_BASIS_REVIEW_MIN_PROCEEDS raises ValueError."""
        cp = self._make_config({
            "TAX_COUNTRY": "PT",
            "FISCAL_YEAR": "2025",
            "ZERO_BASIS_REVIEW_MIN_PROCEEDS": "-5",
        })
        logger = logging.getLogger(__name__)
        with pytest.raises(ValueError, match="finite non-negative"):
            _load_tax_jurisdiction_config(cp, logger)

    def test_committed_config_ini_min_proceeds_matches_default(self):
        """Both committed INI files pin ZERO_BASIS_REVIEW_MIN_PROCEEDS to the domain default.

        Guards against drift between config.ini, tests/config.ini, and
        DEFAULT_ZERO_BASIS_REVIEW_MIN_PROCEEDS when the default is revised.
        """
        from tax_reporting.infrastructure.config import DEFAULT_ZERO_BASIS_REVIEW_MIN_PROCEEDS

        repo_root = Path(__file__).resolve().parents[3]
        ini_paths = [repo_root / "config.ini", repo_root / "tests" / "config.ini"]
        for ini_path in ini_paths:
            assert ini_path.exists(), f"committed config not found: {ini_path}"
            cp = configparser.ConfigParser()
            cp.read(ini_path, encoding="utf-8")
            raw = cp["TAX JURISDICTION"]["ZERO_BASIS_REVIEW_MIN_PROCEEDS"]
            assert Decimal(raw) == DEFAULT_ZERO_BASIS_REVIEW_MIN_PROCEEDS, (
                f"{ini_path.name} ZERO_BASIS_REVIEW_MIN_PROCEEDS={raw!r} diverges from "
                f"DEFAULT_ZERO_BASIS_REVIEW_MIN_PROCEEDS={DEFAULT_ZERO_BASIS_REVIEW_MIN_PROCEEDS}"
            )


def _write_toml(path, content: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "2025.toml").write_text(content, encoding="utf-8")


_MINIMAL_VALID_TOML = (
    '[meta]\nfiscal_year = 2025\nsource_decision_file = "docs/maintenance/tax/decision_points/2025.md"\n'
    'last_verified = "2026-05-26"\n'
)


@pytest.mark.unit
class TestLoadDecisionPointsFlags:
    """Tests for _load_decision_points_flags() in isolation."""

    def test_loads_pt_exclude_flag_from_toml(self, tmp_path, monkeypatch) -> None:
        """PT section with exclude_loan_repayment_gains=true returns the correct flag dict."""
        import tax_reporting.infrastructure.config as config_module
        from tax_reporting.infrastructure.config import _load_decision_points_flags

        dp_dir = tmp_path / "decision_points"
        _write_toml(dp_dir, _MINIMAL_VALID_TOML + "[countries.PT]\nexclude_loan_repayment_gains = true\n")
        monkeypatch.setattr(config_module, "_DECISION_POINTS_DIR", dp_dir)

        logger = logging.getLogger(__name__)
        flags = _load_decision_points_flags("PT", 2025, logger)

        assert flags == {"exclude_loan_repayment_gains": True}

    def test_missing_toml_raises_file_not_found(self, tmp_path, monkeypatch) -> None:
        """FileNotFoundError is raised when no TOML exists for the requested fiscal year."""
        import tax_reporting.infrastructure.config as config_module
        from tax_reporting.infrastructure.config import _load_decision_points_flags

        dp_dir = tmp_path / "decision_points"
        dp_dir.mkdir()
        monkeypatch.setattr(config_module, "_DECISION_POINTS_DIR", dp_dir)

        logger = logging.getLogger(__name__)
        with pytest.raises(FileNotFoundError, match="2025"):
            _load_decision_points_flags("PT", 2025, logger)

    def test_absent_country_section_returns_empty_dict(self, tmp_path, monkeypatch) -> None:
        """When country section is absent in TOML, returns empty dict."""
        import tax_reporting.infrastructure.config as config_module
        from tax_reporting.infrastructure.config import _load_decision_points_flags

        dp_dir = tmp_path / "decision_points"
        _write_toml(dp_dir, _MINIMAL_VALID_TOML + "[countries.PT]\nexclude_loan_repayment_gains = true\n")
        monkeypatch.setattr(config_module, "_DECISION_POINTS_DIR", dp_dir)

        logger = logging.getLogger(__name__)
        flags = _load_decision_points_flags("US", 2025, logger)

        assert flags == {}

    def test_fiscal_year_metadata_mismatch_raises(self, tmp_path, monkeypatch) -> None:
        """ValueError if [meta].fiscal_year != requested fiscal_year."""
        import tax_reporting.infrastructure.config as config_module
        from tax_reporting.infrastructure.config import _load_decision_points_flags

        dp_dir = tmp_path / "decision_points"
        _write_toml(
            dp_dir,
            '[meta]\nfiscal_year = 2024\nsource_decision_file = "x"\nlast_verified = "2025-01-01"\n',
        )
        monkeypatch.setattr(config_module, "_DECISION_POINTS_DIR", dp_dir)

        logger = logging.getLogger(__name__)
        with pytest.raises(ValueError, match="fiscal year"):
            _load_decision_points_flags("PT", 2025, logger)

    def test_invalid_flag_type_raises(self, tmp_path, monkeypatch) -> None:
        """ValueError if a flag value is not a TOML boolean."""
        import tax_reporting.infrastructure.config as config_module
        from tax_reporting.infrastructure.config import _load_decision_points_flags

        dp_dir = tmp_path / "decision_points"
        _write_toml(
            dp_dir, _MINIMAL_VALID_TOML + "[countries.PT]\nexclude_loan_repayment_gains = 1\n"
        )
        monkeypatch.setattr(config_module, "_DECISION_POINTS_DIR", dp_dir)

        logger = logging.getLogger(__name__)
        with pytest.raises(ValueError, match="must be a TOML boolean"):
            _load_decision_points_flags("PT", 2025, logger)

    def test_malformed_toml_raises_clear_error(self, tmp_path, monkeypatch) -> None:
        """ValueError with file path in message when TOML is malformed."""
        import tax_reporting.infrastructure.config as config_module
        from tax_reporting.infrastructure.config import _load_decision_points_flags

        dp_dir = tmp_path / "decision_points"
        dp_dir.mkdir()
        (dp_dir / "2025.toml").write_bytes(b"[invalid toml\n\x00garbage")
        monkeypatch.setattr(config_module, "_DECISION_POINTS_DIR", dp_dir)

        logger = logging.getLogger(__name__)
        with pytest.raises(ValueError, match="Malformed"):
            _load_decision_points_flags("PT", 2025, logger)

    def test_missing_fiscal_year_field_raises_clear_error(self, tmp_path, monkeypatch) -> None:
        """ValueError with clear message when [meta] table exists but lacks fiscal_year field."""
        import tax_reporting.infrastructure.config as config_module
        from tax_reporting.infrastructure.config import _load_decision_points_flags

        dp_dir = tmp_path / "decision_points"
        _write_toml(
            dp_dir,
            '[meta]\nsource_decision_file = "x"\nlast_verified = "2025-01-01"\n',
        )
        monkeypatch.setattr(config_module, "_DECISION_POINTS_DIR", dp_dir)

        logger = logging.getLogger(__name__)
        with pytest.raises(ValueError, match="fiscal_year field"):
            _load_decision_points_flags("PT", 2025, logger)

    def test_fiscal_year_not_int_raises_clear_error(self, tmp_path, monkeypatch) -> None:
        """ValueError when fiscal_year field exists but is not an integer."""
        import tax_reporting.infrastructure.config as config_module
        from tax_reporting.infrastructure.config import _load_decision_points_flags

        dp_dir = tmp_path / "decision_points"
        _write_toml(
            dp_dir,
            '[meta]\nfiscal_year = "2025"\nsource_decision_file = "x"\nlast_verified = "2025-01-01"\n',
        )
        monkeypatch.setattr(config_module, "_DECISION_POINTS_DIR", dp_dir)

        logger = logging.getLogger(__name__)
        with pytest.raises(ValueError, match="must be an integer"):
            _load_decision_points_flags("PT", 2025, logger)


@pytest.mark.unit
class TestLoadTaxJurisdictionConfigWithToml:
    """Tests for _load_tax_jurisdiction_config integrating TOML flag loading."""

    def _make_config(self, section_entries: dict | None) -> configparser.ConfigParser:
        cp = configparser.ConfigParser()
        cp.optionxform = lambda optionstr: optionstr
        if section_entries is not None:
            cp["TAX JURISDICTION"] = section_entries
        return cp

    def test_exclude_flag_read_from_toml_not_ini(self, tmp_path, monkeypatch) -> None:
        """TOML with PT exclude_loan_repayment_gains=false; INI has no flag; result is False."""
        import tax_reporting.infrastructure.config as config_module

        dp_dir = tmp_path / "decision_points"
        _write_toml(dp_dir, _MINIMAL_VALID_TOML + "[countries.PT]\nexclude_loan_repayment_gains = false\n")
        monkeypatch.setattr(config_module, "_DECISION_POINTS_DIR", dp_dir)

        cp = self._make_config({"TAX_COUNTRY": "PT", "FISCAL_YEAR": "2025"})
        logger = logging.getLogger(__name__)
        result = _load_tax_jurisdiction_config(cp, logger)

        assert result.country == "PT"
        assert result.exclude_loan_repayment_gains is False

    def test_pt_requires_exclude_loan_repayment_gains_flag(self, tmp_path, monkeypatch) -> None:
        """ValueError when PT is configured but exclude_loan_repayment_gains flag is missing."""
        import tax_reporting.infrastructure.config as config_module

        dp_dir = tmp_path / "decision_points"
        # TOML with [countries.PT] section but missing exclude_loan_repayment_gains flag
        _write_toml(dp_dir, _MINIMAL_VALID_TOML + "[countries.PT]\n")
        monkeypatch.setattr(config_module, "_DECISION_POINTS_DIR", dp_dir)

        cp = self._make_config({"TAX_COUNTRY": "PT", "FISCAL_YEAR": "2025"})
        logger = logging.getLogger(__name__)
        with pytest.raises(ValueError, match="exclude_loan_repayment_gains flag"):
            _load_tax_jurisdiction_config(cp, logger)

    def test_other_country_allows_missing_exclude_flag(self, tmp_path, monkeypatch) -> None:
        """Non-PT countries can omit exclude_loan_repayment_gains flag (defaults to False)."""
        import tax_reporting.infrastructure.config as config_module

        dp_dir = tmp_path / "decision_points"
        # TOML with [countries.US] section but no exclude flag (valid for non-PT)
        _write_toml(dp_dir, _MINIMAL_VALID_TOML + "[countries.US]\n")
        monkeypatch.setattr(config_module, "_DECISION_POINTS_DIR", dp_dir)

        cp = self._make_config({"TAX_COUNTRY": "US", "FISCAL_YEAR": "2025"})
        logger = logging.getLogger(__name__)
        result = _load_tax_jurisdiction_config(cp, logger)

        assert result.country == "US"
        assert result.exclude_loan_repayment_gains is False  # Default when not specified
