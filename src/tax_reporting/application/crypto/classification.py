"""Tax classification logic for crypto rewards and income.

Extracted from crypto_reporting.py (Task 2 of DDD refactoring).
This module contains functions for classifying crypto rewards, resolving income codes,
and validating country codes for Portuguese tax filing.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path

import pycountry

from ...domain.exceptions import FileProcessingError
from .entities import RewardTaxClassification


def _find_repository_root() -> Path:
    """Find the repository root by searching for .git directory.

    Returns:
        Path to the repository root directory.

    Raises:
        RuntimeError: If .git directory cannot be found (not in a git repository).
    """
    current = Path(__file__).resolve()
    # Search up from current file location, max 10 levels to avoid infinite loops
    for _ in range(10):
        if (current / ".git").exists():
            return current
        current = current.parent
    raise RuntimeError(
        "Cannot find repository root (.git directory not found). "
        "This function must be run within a git repository."
    )


_REPOSITORY_ROOT = _find_repository_root()

# Crypto tokens that share tickers with ISO 4217 fiat currency codes.
# These are known cryptoassets that should be classified as deferred by law (CRG-001),
# even though their ticker collides with a fiat currency code.
_CRYPTO_TOKEN_FIAT_COLLISIONS: frozenset[str] = frozenset(
    (
        "GEL",  # Gelato Network token (fiat GEL = Georgian Lari)
        "MNT",  # Mantle token (fiat MNT = Mongolian tögrög)
    )
)

# Portuguese Tabela X country codes for IRS filing (ISO 3166-1 alpha-2)
_TABELA_X_COUNTRY_CODES: frozenset[str] = frozenset(
    {
        "AT",
        "BE",
        "BG",
        "CY",
        "CZ",
        "DE",
        "DK",
        "EE",
        "ES",
        "FI",
        "FR",
        "GR",
        "HR",
        "HU",
        "IE",
        "IS",
        "IT",
        "LI",
        "LT",
        "LU",
        "LV",
        "MT",
        "NL",
        "NO",
        "PL",
        "PT",
        "RO",
        "SE",
        "SI",
        "SK",
        "CH",
        "GB",
        "US",
        "AE",
        "AU",
        "CA",
        "JP",
        "SG",
        "IN",
        "BR",
        "MX",
        "ZA",
        "KR",
        "IL",
        "CN",
        "HK",
        "NZ",
        "RU",
        "TR",
        "BS",
        "KY",
        "VG",
        "BZ",
        "PA",
        "JE",
        "GG",
        "IM",
        "BM",
        "BV",
        "AG",
        "DM",
        "GD",
        "KN",
        "LC",
        "VC",
        "BB",
        "JM",
        "TT",
        "GY",
        "SR",
        "GL",
        "PM",
        "WF",
        "PF",
        "NC",
        "AS",
        "GU",
        "MP",
        "PR",
        "VI",
        "UM",
        "MH",
        "FM",
        "PW",
        "KI",
        "NR",
        "TV",
        "TO",
        "WS",
        "SB",
        "VU",
        "FJ",
        "CK",
        "NU",
        "TK",
        "PG",
        "SL",
        "ML",
        "NE",
        "TD",
        "SD",
        "ER",
        "DJ",
        "SO",
        "CI",
        "LR",
        "GH",
        "TG",
        "BJ",
        "NG",
        "CM",
        "CF",
        "AO",
        "CD",
        "CG",
        "GA",
        "GQ",
        "ST",
    }
)

# Koinly income type to Tabela V income code mapping for Portuguese IRS
_KOINLY_TYPE_TO_INCOME_CODE: dict[str, str] = {
    # Crypto capital income codes (Tabela V for Anexo J)
    "staking": "401",  # Rendimentos de capitais - criptoativos
    "reward": "401",
    "airdrop": "401",
    "interest": "402",  # Juros de criptoativos
    "lending": "402",
    "lending interest": "402",
    "mining": "403",  # Rendimentos da atividade de mineração
    "fork": "404",  # Rendimentos de forks
    "dividend": "405",  # Dividendos de criptoativos
    # Default fallback for unknown types
}

# Popular/known crypto tokens that should not have zero value in rewards.
# If a reward for one of these tokens has zero value, it's likely a Koinly data error
# (missing price data, export issue) and should be flagged for review instead of skipped.
# Loaded from docs/tax/popular_crypto_tokens.json to allow maintenance without code changes.
# Path computed from repository root for robustness against module structure changes.
_POPULAR_CRYPTO_TOKENS_FILE = (
    _REPOSITORY_ROOT / "docs" / "tax" / "popular_crypto_tokens.json"
)

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _load_popular_crypto_tokens() -> frozenset[str]:
    """Load popular crypto tokens from the external JSON file.

    Returns:
        Frozenset of popular crypto asset tickers. Returns empty frozenset if file
        is not found (logs warning and degrades gracefully).

    The file is cached after first load.

    Raises:
        FileProcessingError: If file is a symlink, exceeds size limit, or has invalid structure.
    """
    tokens: set[str] = set()

    # Security check: reject symlinks
    if _POPULAR_CRYPTO_TOKENS_FILE.is_symlink():
        raise FileProcessingError(
            f"Popular crypto tokens file at {_POPULAR_CRYPTO_TOKENS_FILE} is a symlink — "
            "only regular files are accepted for security"
        )

    if not _POPULAR_CRYPTO_TOKENS_FILE.exists():
        logger.warning(
            "Popular crypto tokens file not found at %s. Zero-value rewards for known assets "
            "may not be flagged for review. Using empty token set.",
            _POPULAR_CRYPTO_TOKENS_FILE,
        )
        return frozenset()

    # Security check: file size validation (max 1MB for token list JSON)
    max_token_file_size = 1 * 1024 * 1024  # 1MB
    try:
        file_size = _POPULAR_CRYPTO_TOKENS_FILE.stat().st_size
        if file_size > max_token_file_size:
            raise FileProcessingError(
                f"Popular crypto tokens file exceeds size limit ({file_size} bytes, "
                f"max {max_token_file_size} bytes): {_POPULAR_CRYPTO_TOKENS_FILE}"
            )
    except OSError as e:
        logger.warning(
            "Could not stat popular crypto tokens file %s: %s. Using empty token set.",
            _POPULAR_CRYPTO_TOKENS_FILE,
            e,
        )
        return frozenset()

    try:
        with _POPULAR_CRYPTO_TOKENS_FILE.open(encoding="utf-8") as f:
            data = json.load(f)

        # Validate JSON structure
        if not isinstance(data, dict):
            raise FileProcessingError(
                f"Popular crypto tokens file must contain a JSON object, got {type(data).__name__}: "
                f"{_POPULAR_CRYPTO_TOKENS_FILE}"
            )

        if "tokens" not in data:
            raise FileProcessingError(
                f"Popular crypto tokens file must contain a 'tokens' key: {_POPULAR_CRYPTO_TOKENS_FILE}"
            )

        tokens_obj = data["tokens"]
        if not isinstance(tokens_obj, dict):
            raise FileProcessingError(
                f"Popular crypto tokens 'tokens' value must be an object, got {type(tokens_obj).__name__}: "
                f"{_POPULAR_CRYPTO_TOKENS_FILE}"
            )

        for category_tokens in tokens_obj.values():
            if isinstance(category_tokens, list):
                tokens.update(category_tokens)

        logger.debug("Loaded %d popular crypto tokens from %s", len(tokens), _POPULAR_CRYPTO_TOKENS_FILE)
        return frozenset(tokens)
    except (json.JSONDecodeError, OSError, AttributeError) as e:
        logger.warning(
            "Failed to load popular crypto tokens from %s: %s. Using empty token set. "
            "Zero-value rewards for known assets may not be flagged for review.",
            _POPULAR_CRYPTO_TOKENS_FILE,
            e,
        )
        return frozenset()


# Cached accessor for popular tokens
def _get_popular_crypto_tokens() -> frozenset[str]:
    """Get the cached popular crypto tokens frozenset."""
    return _load_popular_crypto_tokens()


def _contains_popular_token(asset: str) -> bool:
    """Check if an asset ticker contains a popular crypto token as a substring.

    This catches Koinly-specific naming variants like:
    - TSTON (contains "TON")
    - TSUSDE (contains "USDE")
    - STAKED_* (if wrapped around a popular token)

    Tradeoff: Substring matching may cause false positives for tickers that
    coincidentally contain popular token names as substrings (e.g., "MATICAL"
    matches "MATIC", "SOLANA" matches "SOL"). This is acceptable because the
    consequence is merely flagging for review rather than incorrectly skipping
    a legitimate zero-value reward.

    Args:
        asset: The asset ticker to check.

    Returns:
        True if the asset contains any popular token as a substring (case-insensitive).
    """
    asset_upper = asset.upper()
    return any(token in asset_upper for token in _get_popular_crypto_tokens())


@lru_cache(maxsize=1)
def _get_all_fiat_currency_codes() -> frozenset[str]:
    """Get all ISO 4217 fiat currency codes using pycountry.

    Returns:
        A frozenset of all ISO 4217 currency alphabetic codes.

    This function uses pycountry to retrieve the complete list of official
    fiat currency codes, ensuring comprehensive coverage rather than relying
    on a hand-maintained allowlist. The result is cached for performance.

    Note: Excludes ISO 4217 codes that are NOT fiat currencies for tax purposes:
    - Commodities: XAG (Silver), XAU (Gold), XPD (Palladium), XPT (Platinum)
    - Special units: XBA, XBB, XBC, XBD (bond market units), XDR (SDR),
      XSU (Sucre), XUA (ADB Unit of Account)
    - Placeholders: XXX (no currency), XTS (testing)
    Only actual government-issued fiat currencies are included.
    """
    # ISO 4217 codes that are NOT fiat currencies for tax purposes.
    # These are commodities, special drawing rights, testing codes, or fund/unit codes.
    # Per CRG-002, only fiat-denominated rewards are immediately taxable.
    non_fiat_iso_codes = frozenset(
        {
            # Commodities
            "XAG",  # Silver (commodity)
            "XAU",  # Gold (commodity)
            "XPD",  # Palladium (commodity)
            "XPT",  # Platinum (commodity)
            # Bond market units and special drawing rights
            "XBA",  # Bond Markets Unit European Composite Unit
            "XBB",  # Bond Markets Unit European Monetary Unit
            "XBC",  # Bond Markets Unit European Unit of Account 9
            "XBD",  # Bond Markets Unit European Unit of Account 17
            "XDR",  # SDR (Special Drawing Right)
            "XSU",  # Sucre
            "XUA",  # ADB Unit of Account
            # Testing and placeholder codes
            "XTS",  # Testing code
            "XXX",  # No currency involved
            # Fund and unit codes (not ordinary government-issued fiat)
            "BOV",  # Bolivian Mvdol (funds code)
            "CHE",  # WIR Euro (complementary currency, issued by WIR Bank)
            "CHW",  # WIR Franc (complementary currency, issued by WIR Bank)
            "CLF",  # Unidad de Fomento (unit of account)
            "COU",  # Unidad de Valor Real (UVR) (funds code)
            "MXV",  # Mexican Unidad de Inversion (UDI) (unit of account)
            "USN",  # United States dollar (next day) (funds code)
            "UYI",  # Uruguay Peso en Unidades Indexadas (UI) (indexed unit)
            "UYW",  # Unidad previsional (indexed unit)
        }
    )

    return frozenset(c.alpha_3 for c in pycountry.currencies if c.alpha_3 not in non_fiat_iso_codes)


def _classify_reward_tax_status(asset: str) -> RewardTaxClassification:
    """Classify a crypto reward as taxable now or deferred by law (CRG-001, CRG-002).

    Classification rules:
    - Fiat-denominated rewards (asset is a fiat currency code) are immediately taxable as
      Category E income because the remuneration does not assume the form of cryptoassets.
    - Crypto-denominated rewards (all other assets) are deferred until disposal under
      CIRS art. 5(11) for non-securities and deferral rules for crypto-to-crypto swaps.

    Ticker collision handling: Some crypto tokens share tickers with ISO 4217 fiat currency
    codes (e.g., GEL = Gelato token vs Georgian Lari fiat). Known collisions are checked
    first to ensure correct tax treatment per CRG-001.

    Args:
        asset: The asset ticker from the reward row (e.g., "USDT", "EUR", "BTC", "GEL").

    Returns:
        RewardTaxClassification.TAXABLE_NOW for fiat-denominated rewards.
        RewardTaxClassification.DEFERRED_BY_LAW for crypto-denominated rewards.
    """
    asset_upper = asset.strip().upper()

    # Known crypto tokens that collide with fiat codes are always deferred (CRG-001)
    if asset_upper in _CRYPTO_TOKEN_FIAT_COLLISIONS:
        return RewardTaxClassification.DEFERRED_BY_LAW

    # Fiat currency rewards are immediately taxable (CRG-002)
    # Use pycountry to get all ISO 4217 codes, ensuring comprehensive coverage
    if asset_upper in _get_all_fiat_currency_codes():
        return RewardTaxClassification.TAXABLE_NOW

    # All crypto-denominated rewards are deferred by law (CRG-001)
    # This includes stablecoins like USDT, USDC which are treated as cryptoassets per PT-C-003
    return RewardTaxClassification.DEFERRED_BY_LAW


def _resolve_income_code(koinly_type: str) -> str:
    """Map Koinly income type to Portuguese Tabela V income code for Anexo J filing.

    Args:
        koinly_type: The type field from Koinly income report (e.g., "staking", "airdrop").

    Returns:
        Tabela V income code (e.g., "401" for crypto capital income).
        Defaults to "401" for unknown types (crypto capital income catch-all).
    """
    normalized_type = koinly_type.strip().lower()
    return _KOINLY_TYPE_TO_INCOME_CODE.get(normalized_type, "401")


def _is_valid_tabela_x_country(country: str) -> bool:
    """Check if a country code is a valid Portuguese Tabela X country code.

    Args:
        country: Country code to validate (e.g., "US", "IE", "MT").

    Returns:
        True if the country code is in the official Tabela X list.
    """
    return country.upper() in _TABELA_X_COUNTRY_CODES
