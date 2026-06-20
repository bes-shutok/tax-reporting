"""Configuration management for the tax reporting application."""

from __future__ import annotations

import configparser
import dataclasses
import logging
import re
import tomllib
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import NamedTuple, get_type_hints

from ..domain.exceptions import MissingDecisionPointsError
from ..domain.jurisdiction import DEFAULT_ZERO_BASIS_REVIEW_MIN_PROCEEDS, TaxJurisdictionConfig
from .logging_config import create_module_logger
from .validation import DEFAULT_SECURITY_CONFIG, SecurityConfig

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DECISION_POINTS_DIR = _REPO_ROOT / "docs/maintenance/tax/decision_points"


class ConversionRate(NamedTuple):
    """Represents a currency exchange rate pair.

    Attributes:
        base: The base currency code (e.g., 'EUR').
        calculated: The target currency code (e.g., 'USD').
    """

    base: str
    calculated: str
    rate: Decimal


_DEFAULT_JURISDICTION_COUNTRY = "PT"
_DEFAULT_JURISDICTION_FISCAL_YEAR = 2025
DEFAULT_ZERO_BASIS_REVIEW_THRESHOLD = Decimal("50")

# Derived at import time from TaxJurisdictionConfig field types so it stays in sync
# automatically when new bool flags are added to the dataclass + TOML schema.
# Non-bool fields (country, fiscal_year, zero_basis_review_threshold) are excluded.
_KNOWN_DECISION_FLAGS: frozenset[str] = frozenset(
    f.name
    for f, hint in zip(
        dataclasses.fields(TaxJurisdictionConfig),
        get_type_hints(TaxJurisdictionConfig).values(),
        strict=True,
    )
    if hint is bool
)


@dataclass
class Config:
    """Application configuration container.

    Attributes:
        base: The base currency for reporting (e.g. 'EUR').
        rates: List of configured currency conversion pairs.
        tax_jurisdiction: Country-specific tax jurisdiction settings. Required; always
            set via load_configuration_from_file() which reads law-driven flags from
            the per-year TOML decision points file.
        security: Security configuration settings.
    """

    base: str
    rates: list[ConversionRate]
    tax_jurisdiction: TaxJurisdictionConfig
    security: SecurityConfig = field(default_factory=lambda: DEFAULT_SECURITY_CONFIG)


def _load_decision_points_flags(
    country: str, fiscal_year: int, logger: logging.Logger
) -> dict[str, bool]:
    """Load law-driven decision flags from the per-year TOML decision points file.

    The TOML file is keyed by country ISO code and contains boolean flags that
    encode jurisdiction-specific tax decisions (e.g. whether loan repayment
    disposals are taxable events).

    Args:
        country: ISO 3166-1 alpha-2 country code (e.g. 'PT', 'US').
        fiscal_year: The fiscal year to load flags for.
        logger: Logger for diagnostics.

    Returns:
        Dict of flag name → bool for the requested country. Empty dict if the
        country section is absent in the TOML file.

    Raises:
        FileNotFoundError: If no TOML file exists for the requested fiscal year.
        ValueError: If the TOML is malformed, the [meta].fiscal_year mismatches,
            or any flag value is not a TOML boolean.
    """
    raw_path = _DECISION_POINTS_DIR / f"{fiscal_year}.toml"
    if raw_path.is_symlink():
        raise FileNotFoundError(
            f"Decision points file at {raw_path} is a symlink: only regular files are accepted"
        )
    path = raw_path.resolve()
    logger.info("Loading decision points flags for %s/%d from %s", country, fiscal_year, path)
    if not path.exists():
        raise FileNotFoundError(
            f"No decision points file found for fiscal year {fiscal_year} at {path}"
        )
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ValueError(f"Malformed decision points TOML at {path}: {e}") from e
    meta = data.get("meta")
    if not isinstance(meta, dict):
        raise ValueError(f"Decision points file {path} must contain a [meta] table")
    if "fiscal_year" not in meta:
        raise ValueError(f"Decision points file {path} [meta] table must contain a fiscal_year field")
    meta_fiscal_year = meta["fiscal_year"]
    if not isinstance(meta_fiscal_year, int):
        raise ValueError(
            f"Decision points file {path} fiscal_year must be an integer, "
            f"got {type(meta_fiscal_year).__name__}"
        )
    if meta_fiscal_year != fiscal_year:
        raise ValueError(
            f"Decision points file {path} is for fiscal year {meta_fiscal_year!r}, "
            f"expected {fiscal_year}"
        )
    countries = data.get("countries", {})
    if not isinstance(countries, dict):
        raise ValueError(f"Decision points file {path} must contain a [countries] table when present")
    flags = countries.get(country, {})
    if not isinstance(flags, dict):
        raise ValueError(f"Decision points file {path}: [countries.{country}] must be a table")
    for flag_name, flag_value in flags.items():
        if not isinstance(flag_value, bool):
            raise ValueError(
                f"Decision points flag {flag_name!r} in {path} must be a TOML boolean"
            )
        if flag_name not in _KNOWN_DECISION_FLAGS:
            raise ValueError(
                f"Unknown decision points flag {flag_name!r} in {path} "
                f"(known flags: {sorted(_KNOWN_DECISION_FLAGS)}). "
                f"Add it to _KNOWN_DECISION_FLAGS in config.py and TaxJurisdictionConfig if intentional."
            )
    logger.info("Loaded decision points flags for country %s from %s: %s", country, path, flags)
    return flags  # type: ignore[return-value]


def _parse_jurisdiction_section(
    section: configparser.SectionProxy,
) -> tuple[str, int, Decimal, Decimal]:
    """Parse the [TAX JURISDICTION] section into (country, fiscal_year, threshold, min_proceeds)."""
    country = section.get("TAX_COUNTRY", _DEFAULT_JURISDICTION_COUNTRY).strip().upper()
    if not country:
        raise ValueError("TAX_COUNTRY in [TAX JURISDICTION] must not be empty")
    if not re.fullmatch(r"[A-Z]{2}", country):
        raise ValueError(
            f"TAX_COUNTRY in [TAX JURISDICTION] must be a 2-letter ISO 3166-1 alpha-2 code "
            f"(e.g. 'PT', 'US'), got: {country!r}"
        )
    fiscal_year_raw = section.get("FISCAL_YEAR", str(_DEFAULT_JURISDICTION_FISCAL_YEAR)).strip()
    try:
        fiscal_year = int(fiscal_year_raw)
    except ValueError as e:
        raise ValueError(f"Invalid FISCAL_YEAR in [TAX JURISDICTION]: {fiscal_year_raw!r}") from e
    threshold_raw = section.get(
        "ZERO_BASIS_REVIEW_THRESHOLD", str(DEFAULT_ZERO_BASIS_REVIEW_THRESHOLD)
    ).strip()
    try:
        threshold = Decimal(threshold_raw)
    except InvalidOperation as e:
        raise ValueError(f"Invalid ZERO_BASIS_REVIEW_THRESHOLD in [TAX JURISDICTION]: {threshold_raw!r}") from e
    if not threshold.is_finite() or threshold < 0:
        raise ValueError(
            f"ZERO_BASIS_REVIEW_THRESHOLD must be a finite non-negative number, got: {threshold_raw!r}"
        )
    min_proceeds_raw = section.get(
        "ZERO_BASIS_REVIEW_MIN_PROCEEDS", str(DEFAULT_ZERO_BASIS_REVIEW_MIN_PROCEEDS)
    ).strip()
    try:
        min_proceeds = Decimal(min_proceeds_raw)
    except InvalidOperation as e:
        raise ValueError(
            f"Invalid ZERO_BASIS_REVIEW_MIN_PROCEEDS in [TAX JURISDICTION]: {min_proceeds_raw!r}"
        ) from e
    if not min_proceeds.is_finite() or min_proceeds < 0:
        raise ValueError(
            f"ZERO_BASIS_REVIEW_MIN_PROCEEDS must be a finite non-negative number, got: {min_proceeds_raw!r}"
        )
    return country, fiscal_year, threshold, min_proceeds


def _load_tax_jurisdiction_config(
    config: configparser.ConfigParser, logger: logging.Logger
) -> TaxJurisdictionConfig:
    """Load tax jurisdiction configuration from the [TAX JURISDICTION] config section.

    Falls back to PT/2025 defaults for backward compatibility when the section is absent.

    Args:
        config: The parsed configparser instance.
        logger: Logger for diagnostics.

    Returns:
        TaxJurisdictionConfig with country, fiscal year, and behavioral flags.

    Raises:
        ValueError: If FISCAL_YEAR is present but cannot be parsed as an integer.
    """
    if "TAX JURISDICTION" not in config:
        logger.info("No [TAX JURISDICTION] section found; using defaults (PT, 2025)")
        country = _DEFAULT_JURISDICTION_COUNTRY
        fiscal_year = _DEFAULT_JURISDICTION_FISCAL_YEAR
        threshold = DEFAULT_ZERO_BASIS_REVIEW_THRESHOLD
        min_proceeds = DEFAULT_ZERO_BASIS_REVIEW_MIN_PROCEEDS
    else:
        country, fiscal_year, threshold, min_proceeds = _parse_jurisdiction_section(config["TAX JURISDICTION"])

    # PT excludes loan repayment gains per CIRS art. 10(20); all other countries default to False.
    try:
        flags = _load_decision_points_flags(country, fiscal_year, logger)
    except FileNotFoundError as e:
        raise MissingDecisionPointsError(
            f"Decision points file not found. Create "
            f"docs/maintenance/tax/decision_points/{fiscal_year}.toml and retry: {e}"
        ) from e
    if country == "PT" and "exclude_loan_repayment_gains" not in flags:
        raise ValueError(
            f"Decision points file for PT/fiscal_year={fiscal_year} must contain exclude_loan_repayment_gains flag "
            f"in [countries.PT] section (required per CIRS art. 10(20))"
        )
    config_field_names = {f.name for f in dataclasses.fields(TaxJurisdictionConfig)}
    flag_kwargs = {k: v for k, v in flags.items() if k in config_field_names}
    for flag_name in _KNOWN_DECISION_FLAGS:
        if flag_name in config_field_names:
            flag_kwargs.setdefault(flag_name, False)

    logger.info(
        "Tax jurisdiction config: country=%s, fiscal_year=%d, exclude_loan_repayment_gains=%s, "
        "zero_basis_threshold=%s, zero_basis_min_proceeds=%s",
        country,
        fiscal_year,
        flag_kwargs.get("exclude_loan_repayment_gains", False),
        threshold,
        min_proceeds,
    )
    return TaxJurisdictionConfig(
        country=country,
        fiscal_year=fiscal_year,
        zero_basis_review_threshold=threshold,
        zero_basis_review_min_proceeds=min_proceeds,
        **flag_kwargs,
    )


def load_configuration_from_file() -> Config:
    """Load configuration from the standard config.ini file.

    Also reads the fiscal-year decision-points TOML from
    ``docs/maintenance/tax/decision_points/<fiscal_year>.toml`` to populate
    law-driven flags (e.g. ``exclude_loan_repayment_gains``).
    ``main()`` converts the resulting ``ValueError`` to ``ConfigurationError``.

    Returns:
        Config: The loaded application configuration.

    Raises:
        ValueError: If main currency or required exchange rates are missing,
            the decision-points TOML file is missing or malformed for the configured
            fiscal year, or any ``[TAX JURISDICTION]`` value is invalid.
    """
    logger = create_module_logger(__name__)
    config = configparser.ConfigParser()
    # Preserve case for option names
    # optionxform is a callable that transforms option names
    # Setting it to str preserves case sensitivity
    # Note: parameter name must be 'optionstr' to match ConfigParser's type annotation
    config.optionxform = lambda optionstr: optionstr

    config_path = "config.ini"
    try:
        files_read = config.read(config_path)
        if not files_read:
            raise FileNotFoundError(f"Configuration file not found: {config_path}")

        logger.info("Loaded configuration from %s", config_path)
        logger.debug("Available sections: %s", list(config.sections()))

    except (configparser.Error, OSError) as e:
        logger.error("Failed to read configuration file %s: %s", config_path, e)
        raise

    try:
        target: str = config["COMMON"]["TARGET CURRENCY"]
        logger.debug("Target currency: %s", target)

        rates: list[ConversionRate] = []
        for key in config["EXCHANGE RATES"]:
            base, calculated = key.split("/")
            if base != target:
                raise ValueError(f"Base currency mismatch: {base} != {target}")
            rate_value = Decimal(config["EXCHANGE RATES"][key])
            rates.append(ConversionRate(base=base, calculated=calculated, rate=rate_value))
            logger.debug("Loaded exchange rate %s = %s", key, rate_value)

        logger.info("Loaded %d exchange rates for base currency %s", len(rates), target)

        # Load security settings
        security_config = _load_security_config(config, logger)

        # Load tax jurisdiction settings
        tax_jurisdiction = _load_tax_jurisdiction_config(config, logger)

        return Config(base=target, rates=rates, security=security_config, tax_jurisdiction=tax_jurisdiction)

    except (KeyError, ValueError) as e:
        logger.error("Configuration parsing error: %s", e)
        raise


def _load_security_config(config: configparser.ConfigParser, logger: logging.Logger) -> SecurityConfig:
    """Load security configuration from config file or use defaults."""
    try:
        security_section = config["SECURITY"]

        # Parse security settings with fallback to defaults
        max_file_size_mb = int(security_section.get("MAX_FILE_SIZE_MB", "100"))
        max_ticker_length = int(security_section.get("MAX_TICKER_LENGTH", "10"))
        max_currency_length = int(security_section.get("MAX_CURRENCY_LENGTH", "3"))
        max_quantity_value = int(security_section.get("MAX_QUANTITY_VALUE", "10000000000"))
        max_price_value = int(security_section.get("MAX_PRICE_VALUE", "1000000000"))
        max_filename_length = int(security_section.get("MAX_FILENAME_LENGTH", "255"))

        # Parse allowed extensions
        extensions_str = security_section.get("ALLOWED_EXTENSIONS", ".csv,.txt")
        allowed_extensions = [ext.strip() for ext in extensions_str.split(",")]

        security_config = SecurityConfig(
            max_file_size_mb=max_file_size_mb,
            max_ticker_length=max_ticker_length,
            max_currency_length=max_currency_length,
            max_quantity_value=max_quantity_value,
            max_price_value=max_price_value,
            max_filename_length=max_filename_length,
            allowed_extensions=allowed_extensions,
        )

        logger.info(
            "Loaded security configuration: max_file_size=%sMB, max_ticker_length=%s, allowed_extensions=%s",
            max_file_size_mb,
            max_ticker_length,
            allowed_extensions,
        )

        return security_config

    except (KeyError, ValueError) as e:
        logger.warning("Failed to load security configuration, using defaults: %s", e)
        return DEFAULT_SECURITY_CONFIG
