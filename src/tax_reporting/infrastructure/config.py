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
from typing import Any, NamedTuple, get_args, get_type_hints
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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
# Single, explicit PT convenience default for IANA_TIMEZONE when TAX_COUNTRY=PT and the key is
# absent (user-approved constant during planning). Not a broad country->zone map. Non-PT
# countries must set IANA_TIMEZONE explicitly or leave timezone None (legacy UTC-stamp behavior).
_DEFAULT_PT_TIMEZONE = "Europe/Lisbon"

# Derived at import time from TaxJurisdictionConfig field types so it stays in sync
# automatically when new decision-point fields are added to the dataclass + TOML schema.
# Non-decision fields (country, fiscal_year, zero_basis_review_threshold,
# zero_basis_review_min_proceeds, timezone) are excluded because they are not bool-typed
# nor dict[str, Decimal]-typed.
_CONFIG_FIELDS_AND_HINTS = [
    (f, get_type_hints(TaxJurisdictionConfig)[f.name])
    for f in dataclasses.fields(TaxJurisdictionConfig)
]
_KNOWN_BOOL_FLAGS: frozenset[str] = frozenset(
    f.name for f, hint in _CONFIG_FIELDS_AND_HINTS if hint is bool
)
# dict[str, Decimal]-typed decision-point fields. Detected via get_args == (str, Decimal)
# (NOT get_origin is dict) so a future dict[K, V]-typed field with non-Decimal values is
# not admitted into the Decimal-conversion branch.
_KNOWN_DICT_POINTS: frozenset[str] = frozenset(
    f.name
    for f, hint in _CONFIG_FIELDS_AND_HINTS
    if get_args(hint) == (str, Decimal)
)
_KNOWN_DECIMAL_POINTS: frozenset[str] = frozenset(
    f.name
    for f, hint in _CONFIG_FIELDS_AND_HINTS
    if hint is Decimal and f.name not in ("zero_basis_review_threshold", "zero_basis_review_min_proceeds")
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
) -> dict[str, bool | Decimal | dict[str, Decimal]]:
    """Load law-driven decision flags from the per-year TOML decision points file.

    The TOML file is keyed by country ISO code and contains jurisdiction-specific tax
    decisions. Two field types are supported, derived from ``get_type_hints`` of
    ``TaxJurisdictionConfig``: boolean flags (e.g. whether loan repayment disposals are
    taxable events) and ``dict[str, Decimal]`` subtables (e.g. per-token fee ceilings).

    Args:
        country: ISO 3166-1 alpha-2 country code (e.g. 'PT', 'US').
        fiscal_year: The fiscal year to load flags for.
        logger: Logger for diagnostics.

    Returns:
        Dict of flag name to its typed value (``bool``, ``Decimal``, or ``dict[str, Decimal]``) for the
        requested country. Empty dict if the country section is absent in the TOML file.
        ``Decimal`` and ``dict[str, Decimal]`` values are converted from the raw TOML float/int values via
        ``Decimal(str(value))`` for binary-float-noise-free comparisons.

    Raises:
        FileNotFoundError: If no TOML file exists for the requested fiscal year.
        ValueError: If the TOML is malformed, the [meta].fiscal_year mismatches, a bool
            flag value is not a TOML boolean, a dict flag value is not a table or holds a
            non-numeric value, or a flag name is unknown.
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
    known_flags = _KNOWN_BOOL_FLAGS | _KNOWN_DICT_POINTS | _KNOWN_DECIMAL_POINTS
    validated: dict[str, bool | Decimal | dict[str, Decimal]] = {}
    for flag_name, flag_value in flags.items():
        validated[flag_name] = _validate_and_convert_flag(flag_name, flag_value, path, known_flags)
    logger.info("Loaded decision points flags for country %s from %s: %s", country, path, validated)
    return validated


def _validate_and_convert_flag(
    flag_name: str, flag_value: object, path: Path, known_flags: frozenset[str]
) -> bool | Decimal | dict[str, Decimal]:
    """Validate and convert a single decision-points flag value by type-dispatching.

    Returns the validated bool or the Decimal-converted dict (overwriting any raw TOML
    float/int values via ``Decimal(str(value))`` so downstream comparisons are binary-float-
    noise-free). Raises ``ValueError`` for an unknown flag name, a non-bool bool-flag value,
    a non-table dict-flag value, or a non-numeric dict-flag value.
    """
    if flag_name in _KNOWN_BOOL_FLAGS:
        if not isinstance(flag_value, bool):
            raise ValueError(f"Decision points flag {flag_name!r} in {path} must be a TOML boolean")
        return flag_value
    if flag_name in _KNOWN_DICT_POINTS:
        if not isinstance(flag_value, dict):
            raise ValueError(
                f"Decision points flag {flag_name!r} in {path} must be a TOML table "
                f"(dict[str, Decimal])"
            )
        try:
            return {k: Decimal(str(v)) for k, v in flag_value.items()}
        except InvalidOperation as e:
            raise ValueError(
                f"Decision points flag {flag_name!r} in {path} contains a non-numeric "
                f"value (raw={flag_value!r}): {e}"
            ) from e
    if flag_name in _KNOWN_DECIMAL_POINTS:
        if not isinstance(flag_value, (int, float)):
            raise ValueError(
                f"Decision points flag {flag_name!r} in {path} must be a TOML number"
            )
        try:
            return Decimal(str(flag_value))
        except InvalidOperation as e:
            raise ValueError(
                f"Decision points flag {flag_name!r} in {path} contains a non-numeric "
                f"value (raw={flag_value!r}): {e}"
            ) from e
    raise ValueError(
        f"Unknown decision points flag {flag_name!r} in {path} "
        f"(known flags: {sorted(known_flags)}). "
        f"Add it to _KNOWN_BOOL_FLAGS/_KNOWN_DICT_POINTS in config.py and "
        f"TaxJurisdictionConfig if intentional."
    )


class JurisdictionSectionFields(NamedTuple):
    """Parsed [TAX JURISDICTION] fields (NamedTuple so adding fields does not break positional unpacking).

    Attributes:
        country: ISO 3166-1 alpha-2 country code (upper-cased).
        fiscal_year: Fiscal year integer.
        threshold: Zero-basis review threshold (EUR).
        min_proceeds: Zero-basis review min proceeds (EUR).
        iana_timezone: Raw IANA timezone string from IANA_TIMEZONE, or the PT default
            ("Europe/Lisbon") when the key is absent and country is PT, or None otherwise.
            Resolved to a ZoneInfo value object in _load_tax_jurisdiction_config.
    """

    country: str
    fiscal_year: int
    threshold: Decimal
    min_proceeds: Decimal
    iana_timezone: str | None


def _parse_jurisdiction_section(section: configparser.SectionProxy) -> JurisdictionSectionFields:
    """Parse the [TAX JURISDICTION] section into country, fiscal_year, threshold, min_proceeds, iana_timezone."""
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
    iana_raw = section.get("IANA_TIMEZONE")
    if iana_raw is not None:
        iana_raw = iana_raw.strip()
    if iana_raw:
        iana_timezone: str | None = iana_raw
    elif country == "PT":
        iana_timezone = _DEFAULT_PT_TIMEZONE
    else:
        iana_timezone = None
    return JurisdictionSectionFields(country, fiscal_year, threshold, min_proceeds, iana_timezone)


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
        # Country defaults to PT, so the PT timezone default applies.
        iana_timezone: str | None = _DEFAULT_PT_TIMEZONE
    else:
        country, fiscal_year, threshold, min_proceeds, iana_timezone = _parse_jurisdiction_section(
            config["TAX JURISDICTION"]
        )

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
    # flag_kwargs holds heterogeneous decision-point values (bool flags and dict[str, Decimal]
    # subtables); per-key types are guaranteed by _load_decision_points_flags' type-dispatching
    # validation, so Any is the honest element type for the **-unpack into the dataclass ctor.
    flag_kwargs: dict[str, Any] = {k: v for k, v in flags.items() if k in config_field_names}
    # Only bool-typed decision-point fields default to False when absent from TOML.
    # dict[str, Decimal]-typed fields are non-bool and naturally excluded; when absent
    # they are NOT added to flag_kwargs, so the dataclass default_factory=dict supplies {}.
    for flag_name in _KNOWN_BOOL_FLAGS:
        if flag_name in config_field_names:
            flag_kwargs.setdefault(flag_name, False)

    # Resolve the IANA timezone string to a ZoneInfo value object exactly once, at config-load
    # (after the decision-points TOML loads, so an invalid zone surfaces as a plain ValueError
    # rather than being masked by MissingDecisionPointsError). timezone cannot ride
    # **flag_kwargs (only bool decision flags); pass it explicitly to the constructor.
    timezone: ZoneInfo | None
    if iana_timezone is not None:
        try:
            timezone = ZoneInfo(iana_timezone)
        except ZoneInfoNotFoundError as e:
            raise ValueError(
                f"Invalid IANA_TIMEZONE {iana_timezone!r} in [TAX JURISDICTION]: "
                f"not a recognized IANA tz database zone"
            ) from e
        except Exception as e:
            raise ValueError(
                f"Invalid IANA_TIMEZONE {iana_timezone!r} in [TAX JURISDICTION]: {e}"
            ) from e
    else:
        timezone = None

    logger.info(
        "Tax jurisdiction config: country=%s, fiscal_year=%d, exclude_loan_repayment_gains=%s, "
        "zero_basis_threshold=%s, zero_basis_min_proceeds=%s, timezone=%s",
        country,
        fiscal_year,
        flag_kwargs.get("exclude_loan_repayment_gains", False),
        threshold,
        min_proceeds,
        iana_timezone,
    )
    return TaxJurisdictionConfig(
        country=country,
        fiscal_year=fiscal_year,
        zero_basis_review_threshold=threshold,
        zero_basis_review_min_proceeds=min_proceeds,
        **flag_kwargs,
        timezone=timezone,
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
