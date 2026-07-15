"""Tests for configuration management functionality."""

import configparser
import logging
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from tax_reporting.infrastructure.config import (
    Config,
    ConversionRate,
    TaxJurisdictionConfig,
    _load_tax_jurisdiction_config,
    _parse_jurisdiction_section,
)

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

    def test_decision_points_toml_loads_without_via_resolver_flags(self, tmp_path, monkeypatch) -> None:
        """Phase E Task 6 characterization: the committed 2025.toml (with the six
        ``treatment_*_via_resolver`` lines removed) loads cleanly via
        ``load_tax_jurisdiction_config``. The Phase D required-presence guard that
        raised ``ConfigurationError`` on a missing flag is gone; this test pins the
        relaxed loader so a future re-introduction of the guard would surface here.
        """
        import tax_reporting.infrastructure.config as config_module

        # TOML shaped like the post-Phase-E committed 2025.toml: PT section with the
        # exclude flag and a sub-table, but NO ``treatment_*_via_resolver`` lines.
        post_phase_e_toml = (
            '[meta]\nfiscal_year = 2025\n'
            'source_decision_file = "docs/maintenance/tax/decision_points/2025.md"\n'
            'last_verified = "2026-05-26"\n'
            '[countries.PT]\nexclude_loan_repayment_gains = true\n'
            '[countries.PT.exclude_transaction_fee_max_eur_per_asset]\nETH = 1.0\n'
        )
        dp_dir = tmp_path / "decision_points"
        _write_toml(dp_dir, post_phase_e_toml)
        monkeypatch.setattr(config_module, "_DECISION_POINTS_DIR", dp_dir)

        cp = configparser.ConfigParser()
        cp.optionxform = lambda optionstr: optionstr
        cp["TAX JURISDICTION"] = {"TAX_COUNTRY": "PT", "FISCAL_YEAR": "2025"}
        logger = logging.getLogger(__name__)
        # The required-presence guard for the six treatment flags is removed in
        # Phase E Task 6; loading must succeed. Pre-edit (RED): the loader raises
        # ConfigurationError naming a missing ``treatment_*_via_resolver`` flag.
        result = _load_tax_jurisdiction_config(cp, logger)
        assert result.country == "PT"
        assert result.exclude_loan_repayment_gains is True

    def test_stale_via_resolver_flag_in_toml_rejected_as_unknown(self, tmp_path, monkeypatch) -> None:
        """Phase E Task 6 follow-up: a stale ``treatment_*_via_resolver`` line
        lingering in a future-year TOML (e.g. when copying ``2025.toml`` forward
        without the Phase E cleanup) must surface as a hard load error via the
        unknown-flag rejection path, not be silently dropped. The lower-level
        ``_load_tax_jurisdiction_config`` raises ``ValueError``; ``main()``
        converts that to ``ConfigurationError``.
        """
        import tax_reporting.infrastructure.config as config_module

        stale_toml = (
            '[meta]\nfiscal_year = 2025\n'
            'source_decision_file = "docs/maintenance/tax/decision_points/2025.md"\n'
            'last_verified = "2026-05-26"\n'
            '[countries.PT]\nexclude_loan_repayment_gains = true\n'
            'treatment_payment_via_resolver = true\n'
        )
        dp_dir = tmp_path / "decision_points"
        _write_toml(dp_dir, stale_toml)
        monkeypatch.setattr(config_module, "_DECISION_POINTS_DIR", dp_dir)

        cp = configparser.ConfigParser()
        cp.optionxform = lambda optionstr: optionstr
        cp["TAX JURISDICTION"] = {"TAX_COUNTRY": "PT", "FISCAL_YEAR": "2025"}
        logger = logging.getLogger(__name__)
        with pytest.raises(ValueError, match="Unknown decision points flag"):
            _load_tax_jurisdiction_config(cp, logger)


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


# Phase E Task 6: the six per-treatment resolver flags were removed from
# ``TaxJurisdictionConfig`` and the decision-points TOML. Kept as an empty-string
# alias for tests that still concatenate it into TOML fixtures; Task 8 owns the
# full sweep that deletes the remaining call sites.
_SIX_TREATMENT_FLAGS_TOML = ""


@pytest.mark.unit
class TestLoadTaxJurisdictionConfig:
    """Tests for TaxJurisdictionConfig parsing from config file."""

    _PT_TOML = (
    "[meta]\nfiscal_year = 2025\n[countries.PT]\n"
    "exclude_loan_repayment_gains = true\nexclude_transaction_fees = true\n"
    + _SIX_TREATMENT_FLAGS_TOML
)
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

    def test_non_pt_country_missing_subtable_defaults_to_empty_dict(self, tmp_path, monkeypatch) -> None:
        """A non-PT country whose TOML omits the per-asset subtable gets an empty dict (no error).

        The dict field defaults via the dataclass default_factory=dict when absent
        from flag_kwargs; the loader never adds it. Asserts isinstance(dict) and empty.
        """
        import tax_reporting.infrastructure.config as config_module
        monkeypatch.setattr(config_module, "_DECISION_POINTS_DIR", tmp_path)
        (tmp_path / "2025.toml").write_text(self._NO_COUNTRY_TOML)
        cp = self._make_config({"TAX_COUNTRY": "US", "FISCAL_YEAR": "2025"})
        logger = logging.getLogger(__name__)
        result = _load_tax_jurisdiction_config(cp, logger)
        assert isinstance(result.exclude_transaction_fee_max_eur_per_asset, dict)
        assert result.exclude_transaction_fee_max_eur_per_asset == {}

    def test_pt_subtable_loaded_into_config(self, tmp_path, monkeypatch) -> None:
        """The PT per-asset subtable in 2025.toml is loaded into TaxJurisdictionConfig with Decimal values."""
        import tax_reporting.infrastructure.config as config_module
        monkeypatch.setattr(config_module, "_DECISION_POINTS_DIR", tmp_path)
        (tmp_path / "2025.toml").write_text(
            "[meta]\nfiscal_year = 2025\n[countries.PT]\n"
            "exclude_loan_repayment_gains = true\nexclude_transaction_fees = true\n"
            + _SIX_TREATMENT_FLAGS_TOML
            + "[countries.PT.exclude_transaction_fee_max_eur_per_asset]\n"
            "ETH = 1.0\nSOL = 0.5\n"
        )
        cp = self._make_config({"TAX_COUNTRY": "PT", "FISCAL_YEAR": "2025"})
        logger = logging.getLogger(__name__)
        result = _load_tax_jurisdiction_config(cp, logger)
        per_asset = result.exclude_transaction_fee_max_eur_per_asset
        assert per_asset["ETH"] == Decimal("1.0")
        assert per_asset["SOL"] == Decimal("0.5")
        assert all(isinstance(v, Decimal) for v in per_asset.values())

    def test_exclude_transaction_fees_defaults_to_false(self) -> None:
        """TaxJurisdictionConfig defaults exclude_transaction_fees to False when not provided."""
        config = TaxJurisdictionConfig(
            country="US",
            fiscal_year=2025,
            exclude_loan_repayment_gains=False,
            zero_basis_review_threshold=Decimal("50"),
        )
        assert config.exclude_transaction_fees is False

    def test_load_tax_jurisdiction_config_pt_excludes_transaction_fees(self, tmp_path, monkeypatch) -> None:
        """PT jurisdiction config loaded from the 2025.toml decision points has exclude_transaction_fees == True."""
        import tax_reporting.infrastructure.config as config_module

        monkeypatch.setattr(config_module, "_DECISION_POINTS_DIR", tmp_path)
        (tmp_path / "2025.toml").write_text(self._PT_TOML)
        cp = self._make_config({"TAX_COUNTRY": "PT", "FISCAL_YEAR": "2025"})
        logger = logging.getLogger(__name__)
        result = _load_tax_jurisdiction_config(cp, logger)
        assert result.country == "PT"
        assert result.exclude_transaction_fees is True

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
        _write_toml(dp_dir, _MINIMAL_VALID_TOML + _PT_VALID_SECTION_TOML)
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

    def test_load_tax_jurisdiction_config_pt_defaults_to_lisbon(self, tmp_path, monkeypatch):
        """PT with no IANA_TIMEZONE key resolves timezone to Europe/Lisbon."""
        import tax_reporting.infrastructure.config as config_module

        monkeypatch.setattr(config_module, "_DECISION_POINTS_DIR", tmp_path)
        (tmp_path / "2025.toml").write_text(self._PT_TOML)
        cp = self._make_config({"TAX_COUNTRY": "PT", "FISCAL_YEAR": "2025"})
        logger = logging.getLogger(__name__)
        result = _load_tax_jurisdiction_config(cp, logger)
        assert result.timezone == ZoneInfo("Europe/Lisbon")

    def test_load_tax_jurisdiction_config_explicit_zone_overrides_default(self, tmp_path, monkeypatch):
        """An explicit IANA_TIMEZONE overrides the PT default (Azores is UTC-1/+0, distinct from Lisbon)."""
        import tax_reporting.infrastructure.config as config_module

        monkeypatch.setattr(config_module, "_DECISION_POINTS_DIR", tmp_path)
        (tmp_path / "2025.toml").write_text(self._PT_TOML)
        cp = self._make_config({"TAX_COUNTRY": "PT", "FISCAL_YEAR": "2025", "IANA_TIMEZONE": "Atlantic/Azores"})
        logger = logging.getLogger(__name__)
        result = _load_tax_jurisdiction_config(cp, logger)
        assert result.timezone == ZoneInfo("Atlantic/Azores")

    def test_load_tax_jurisdiction_config_invalid_zone_raises(self, tmp_path, monkeypatch):
        """An invalid IANA_TIMEZONE raises ValueError naming the bad zone after decision-points load."""
        import tax_reporting.infrastructure.config as config_module

        monkeypatch.setattr(config_module, "_DECISION_POINTS_DIR", tmp_path)
        (tmp_path / "2025.toml").write_text(self._PT_TOML)
        cp = self._make_config({"TAX_COUNTRY": "PT", "FISCAL_YEAR": "2025", "IANA_TIMEZONE": "Foo/Bar"})
        logger = logging.getLogger(__name__)
        with pytest.raises(ValueError, match="Foo/Bar"):
            _load_tax_jurisdiction_config(cp, logger)

    def test_load_tax_jurisdiction_config_generic_zone_error_raises(self, tmp_path, monkeypatch):
        """A non-ZoneInfoNotFoundError failure from ZoneInfo() hits the generic except branch.

        The invalid-zone test above exercises only ``except ZoneInfoNotFoundError``; this
        covers the catch-all ``except Exception`` (e.g. a tz database read failure), which
        produces a different message that appends the underlying error.
        """
        import tax_reporting.infrastructure.config as config_module

        monkeypatch.setattr(config_module, "_DECISION_POINTS_DIR", tmp_path)
        (tmp_path / "2025.toml").write_text(self._PT_TOML)
        cp = self._make_config(
            {"TAX_COUNTRY": "PT", "FISCAL_YEAR": "2025", "IANA_TIMEZONE": "Europe/Lisbon"}
        )
        logger = logging.getLogger(__name__)

        def _boom(_key: str):
            raise OSError("tz database read failed")

        monkeypatch.setattr(config_module, "ZoneInfo", _boom)
        with pytest.raises(ValueError, match="Invalid IANA_TIMEZONE"):
            _load_tax_jurisdiction_config(cp, logger)

    def test_load_tax_jurisdiction_config_non_pt_without_key_is_none(self, tmp_path, monkeypatch):
        """Non-PT country without IANA_TIMEZONE yields timezone None (documented backward-compat)."""
        import tax_reporting.infrastructure.config as config_module

        monkeypatch.setattr(config_module, "_DECISION_POINTS_DIR", tmp_path)
        (tmp_path / "2025.toml").write_text(self._NO_COUNTRY_TOML)
        cp = self._make_config({"TAX_COUNTRY": "US", "FISCAL_YEAR": "2025"})
        logger = logging.getLogger(__name__)
        result = _load_tax_jurisdiction_config(cp, logger)
        assert result.timezone is None

    def test_parse_jurisdiction_section_surfaces_iana_timezone(self):
        """_parse_jurisdiction_section returns a NamedTuple carrying iana_timezone with PT default applied."""
        cp = configparser.ConfigParser()
        cp.optionxform = lambda optionstr: optionstr
        cp["TAX JURISDICTION"] = {"TAX_COUNTRY": "PT", "FISCAL_YEAR": "2025", "IANA_TIMEZONE": "Europe/Lisbon"}
        result = _parse_jurisdiction_section(cp["TAX JURISDICTION"])
        assert result.iana_timezone == "Europe/Lisbon"

        # PT default applied inside the section parser when the key is absent and country is PT.
        cp2 = configparser.ConfigParser()
        cp2.optionxform = lambda optionstr: optionstr
        cp2["TAX JURISDICTION"] = {"TAX_COUNTRY": "PT", "FISCAL_YEAR": "2025"}
        result2 = _parse_jurisdiction_section(cp2["TAX JURISDICTION"])
        assert result2.iana_timezone == "Europe/Lisbon"

        # Non-PT without key yields None.
        cp3 = configparser.ConfigParser()
        cp3.optionxform = lambda optionstr: optionstr
        cp3["TAX JURISDICTION"] = {"TAX_COUNTRY": "US", "FISCAL_YEAR": "2025"}
        result3 = _parse_jurisdiction_section(cp3["TAX JURISDICTION"])
        assert result3.iana_timezone is None


def _write_toml(path, content: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "2025.toml").write_text(content, encoding="utf-8")


_MINIMAL_VALID_TOML = (
    '[meta]\nfiscal_year = 2025\nsource_decision_file = "docs/maintenance/tax/decision_points/2025.md"\n'
    'last_verified = "2026-05-26"\n'
)

# A minimal PT country section that satisfies the exclude_loan_repayment_gains
# required-presence check (config.py:321). Phase E Task 6 removed the Phase D
# six-treatment-flag required-presence guard; the alias is kept for tests that
# still append ``_SIX_TREATMENT_FLAGS_TOML``.
_PT_VALID_SECTION_TOML = (
    "[countries.PT]\nexclude_loan_repayment_gains = true\n" + _SIX_TREATMENT_FLAGS_TOML
)


@pytest.mark.unit
class TestLoadDecisionPointsFlags:
    """Tests for _load_decision_points_flags() in isolation."""

    def test_loads_pt_exclude_flag_from_toml(self, tmp_path, monkeypatch) -> None:
        """PT section with exclude_loan_repayment_gains=true returns the correct flag dict."""
        import tax_reporting.infrastructure.config as config_module
        from tax_reporting.infrastructure.config import _load_decision_points_flags

        dp_dir = tmp_path / "decision_points"
        _write_toml(dp_dir, _MINIMAL_VALID_TOML + _PT_VALID_SECTION_TOML)
        monkeypatch.setattr(config_module, "_DECISION_POINTS_DIR", dp_dir)

        logger = logging.getLogger(__name__)
        flags = _load_decision_points_flags("PT", 2025, logger)

        assert flags["exclude_loan_repayment_gains"] is True
        # Phase E Task 6: the six ``treatment_*_via_resolver`` flags are removed
        # from ``TaxJurisdictionConfig`` and the decision-points TOML; the loader
        # now rejects them as unknown flags. Only the ``exclude_loan_repayment_gains``
        # flag is asserted here.

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
        _write_toml(dp_dir, _MINIMAL_VALID_TOML + _PT_VALID_SECTION_TOML)
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

    def test_dict_subtable_parsed_with_decimal_str_conversion(self, tmp_path, monkeypatch) -> None:
        """A dict[str, Decimal] subtable is parsed and values are Decimal(str(value)).

        Includes a non-round ceiling (0.1) so the test pins the exact Decimal
        representation Decimal("0.1") rather than a binary-float-noisy value.
        """
        import tax_reporting.infrastructure.config as config_module
        from tax_reporting.infrastructure.config import _load_decision_points_flags

        dp_dir = tmp_path / "decision_points"
        _write_toml(
            dp_dir,
            _MINIMAL_VALID_TOML
            + "[countries.PT]\n"
            + "[countries.PT.exclude_transaction_fee_max_eur_per_asset]\n"
            + "ETH = 1.0\nSOL = 0.5\nX = 0.1\n",
        )
        monkeypatch.setattr(config_module, "_DECISION_POINTS_DIR", dp_dir)

        logger = logging.getLogger(__name__)
        flags = _load_decision_points_flags("PT", 2025, logger)

        per_asset = flags["exclude_transaction_fee_max_eur_per_asset"]
        assert isinstance(per_asset, dict)
        # Decimal(str(value)) - binary-float-noise-free. 0.1 is the load-bearing
        # discriminator: Decimal(0.1) would yield 0.1000000000000000055511151231...
        assert per_asset["ETH"] == Decimal("1.0")
        assert per_asset["SOL"] == Decimal("0.5")
        assert per_asset["X"] == Decimal("0.1")
        assert all(isinstance(v, Decimal) for v in per_asset.values())

    def test_invalid_dict_value_raises(self, tmp_path, monkeypatch) -> None:
        """A non-numeric value in a dict[str, Decimal] subtable raises a clear ValueError."""
        import tax_reporting.infrastructure.config as config_module
        from tax_reporting.infrastructure.config import _load_decision_points_flags

        dp_dir = tmp_path / "decision_points"
        _write_toml(
            dp_dir,
            _MINIMAL_VALID_TOML
            + "[countries.PT]\n"
            + "[countries.PT.exclude_transaction_fee_max_eur_per_asset]\n"
            + 'ETH = "not-a-number"\n',
        )
        monkeypatch.setattr(config_module, "_DECISION_POINTS_DIR", dp_dir)

        logger = logging.getLogger(__name__)
        with pytest.raises(ValueError, match="non-numeric"):
            _load_decision_points_flags("PT", 2025, logger)

    def test_non_bool_dict_value_for_dict_field_raises_table_error(self, tmp_path, monkeypatch) -> None:
        """A scalar value where a dict[str, Decimal] is expected raises ValueError naming the table requirement."""
        import tax_reporting.infrastructure.config as config_module
        from tax_reporting.infrastructure.config import _load_decision_points_flags

        dp_dir = tmp_path / "decision_points"
        _write_toml(
            dp_dir,
            _MINIMAL_VALID_TOML
            + "[countries.PT]\nexclude_transaction_fee_max_eur_per_asset = 1.0\n",
        )
        monkeypatch.setattr(config_module, "_DECISION_POINTS_DIR", dp_dir)

        logger = logging.getLogger(__name__)
        with pytest.raises(ValueError, match="must be a TOML table"):
            _load_decision_points_flags("PT", 2025, logger)

    def test_known_bool_flags_and_known_dict_points_both_nonempty(self) -> None:
        """Both _KNOWN_BOOL_FLAGS and _KNOWN_DICT_POINTS are non-empty at import.

        Guards against a broken type-detection check silently populating empty sets:
        the dict-set membership relies on get_args(hint) == (str, Decimal) detection.
        """
        from tax_reporting.infrastructure.config import _KNOWN_BOOL_FLAGS, _KNOWN_DICT_POINTS

        assert _KNOWN_BOOL_FLAGS  # non-empty
        assert _KNOWN_DICT_POINTS  # non-empty
        # exclude_transaction_fees is bool-typed; the new field is dict-typed.
        assert "exclude_transaction_fees" in _KNOWN_BOOL_FLAGS
        assert "exclude_transaction_fee_max_eur_per_asset" in _KNOWN_DICT_POINTS
        # The sets are disjoint by construction.
        assert _KNOWN_BOOL_FLAGS.isdisjoint(_KNOWN_DICT_POINTS)

    def test_loads_decimal_decision_points(self, tmp_path, monkeypatch) -> None:
        """A decimal decision point is parsed into a Decimal value."""
        import tax_reporting.infrastructure.config as config_module
        from tax_reporting.infrastructure.config import _load_decision_points_flags

        dp_dir = tmp_path / "decision_points"
        _write_toml(
            dp_dir,
            _MINIMAL_VALID_TOML
            + "[countries.PT]\nexclude_transaction_fee_default_max_eur = 0.5\n",
        )
        monkeypatch.setattr(config_module, "_DECISION_POINTS_DIR", dp_dir)

        logger = logging.getLogger(__name__)
        flags = _load_decision_points_flags("PT", 2025, logger)

        assert isinstance(flags["exclude_transaction_fee_default_max_eur"], Decimal)
        assert flags["exclude_transaction_fee_default_max_eur"] == Decimal("0.5")


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
        _write_toml(
            dp_dir,
            _MINIMAL_VALID_TOML + "[countries.PT]\nexclude_loan_repayment_gains = false\n" + _SIX_TREATMENT_FLAGS_TOML,
        )
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
        _write_toml(dp_dir, _MINIMAL_VALID_TOML + "[countries.US]\n" + _SIX_TREATMENT_FLAGS_TOML)
        monkeypatch.setattr(config_module, "_DECISION_POINTS_DIR", dp_dir)

        cp = self._make_config({"TAX_COUNTRY": "US", "FISCAL_YEAR": "2025"})
        logger = logging.getLogger(__name__)
        result = _load_tax_jurisdiction_config(cp, logger)

        assert result.country == "US"
        assert result.exclude_loan_repayment_gains is False  # Default when not specified
