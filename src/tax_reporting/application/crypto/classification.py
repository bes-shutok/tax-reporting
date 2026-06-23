"""Tax classification logic for crypto rewards and income.

Extracted from crypto_reporting.py (Task 2 of DDD refactoring).
This module contains functions for classifying crypto rewards, resolving income codes,
and validating country codes for Portuguese tax filing.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

import pycountry

from ...domain.exceptions import FileProcessingError
from ...infrastructure.json_loader import DEGRADED, load_guarded_json
from .entities import CryptoCapitalGainEntry, DerivativesClassification, ParsedOgrRow, RewardTaxClassification


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
# Loaded from docs/maintenance/tax/popular_crypto_tokens.json to allow maintenance without code changes.
# Path computed from repository root for robustness against module structure changes.
_POPULAR_CRYPTO_TOKENS_FILE = (
    _REPOSITORY_ROOT / "docs" / "maintenance" / "tax" / "popular_crypto_tokens.json"
)

# Strict size cap for popular crypto tokens JSON (1 MiB). Mirrors
# payment_proceeds._MAX_TOKEN_FILE_SIZE; the file is the same config genre.
# Files of exactly this size pass; strictly larger files are rejected.
_MAX_TOKEN_FILE_SIZE = 1 * 1024 * 1024

logger = logging.getLogger(__name__)


def _on_error(failed_path: Path, kind: str, detail: str) -> object:
    """Policy callback for :func:`load_guarded_json`.

    Preserves the original MIXED policy of ``_load_popular_crypto_tokens``:
    symlink and oversize are security/data-integrity failures that raise
    ``FileProcessingError`` (the file is untrusted at that point); missing,
    stat errors, and invalid JSON degrade to a WARNING + ``DEGRADED`` so that
    token loading never aborts report generation.

    Args:
        failed_path: The path that failed (embedded in messages).
        kind: Failure kind from the closed set ``{"symlink", "missing",
            "oversize", "stat_error", "invalid_json"}``.
        detail: Helper-supplied detail string (``str(exc)`` for OSError/JSON
            errors, byte f-string for oversize).

    Returns:
        ``DEGRADED`` for the degrade kinds; never returns for symlink/oversize
        (those raise).

    Raises:
        FileProcessingError: For ``symlink`` and ``oversize`` kinds.
    """
    if kind == "symlink":
        raise FileProcessingError(
            f"Popular crypto tokens file at {failed_path} is a symlink: "
            "only regular files are accepted for security"
        )
    if kind == "oversize":
        raise FileProcessingError(
            f"Popular crypto tokens file exceeds size limit ({detail}): {failed_path}"
        )
    if kind == "missing":
        logger.warning(
            "Popular crypto tokens file not found at %s. Zero-value rewards for known assets "
            "may not be flagged for review. Using empty token set.",
            failed_path,
        )
        return DEGRADED
    if kind == "stat_error":
        logger.warning(
            "Could not stat popular crypto tokens file %s: %s. Using empty token set.",
            failed_path,
            detail,
        )
        return DEGRADED
    if kind == "invalid_json":
        logger.warning(
            "Failed to load popular crypto tokens from %s: %s. Using empty token set. "
            "Zero-value rewards for known assets may not be flagged for review.",
            failed_path,
            detail,
        )
        return DEGRADED
    # Defensive: unknown kind still degrades rather than propagating.
    logger.warning(
        "Unknown loader failure kind '%s' for popular crypto tokens file %s: %s. Using empty token set.",
        kind,
        failed_path,
        detail,
    )
    return DEGRADED


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

    data = load_guarded_json(
        _POPULAR_CRYPTO_TOKENS_FILE, size_limit=_MAX_TOKEN_FILE_SIZE, on_error=_on_error
    )
    if data is DEGRADED:
        return frozenset()

    # No try/except: json.load lives in the helper (failures surface via _on_error
    # as invalid_json); isinstance guards make AttributeError unreachable here.
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


# Matching tolerance for OGR-vs-CG disposal value comparison (Task 5 derivatives classifier).
# 1 cent EUR; absorbs rounding differences between OGR Value (EUR) and CG proceeds_eur.
# This is a MATCHING tolerance, not a classification threshold: it gates whether
# an OGR Loss row's disposal proceeds (OGR "Value (EUR)" column) agrees with the
# CG disposal proceeds (CryptoCapitalGainEntry.proceeds_eur). Comparing against
# gain_loss_eur would be wrong because the OGR "Value (EUR)" column captures the
# disposal value (proceeds), NOT the realized gain; the realized gain is a
# different quantity (cost-subtracted). Verified against the Case 1 fixture:
# OGR row 9 Value=4.17 matches CG line 19 proceeds_eur=4.17 (gain_loss_eur=2.44
# there), so the match only succeeds against proceeds_eur. Per CLAUDE.md §4
# (no hardcoded thresholds without flagging), this is the single numeric
# threshold in the classifier and is documented here as the matching precision.
_TOLERANCE_OGR_CG = Decimal("0.01")


def classify_derivatives_event(  # noqa: PLR0911
    ogr_row: ParsedOgrRow,
    cg_matches: list[CryptoCapitalGainEntry],
) -> DerivativesClassification:
    """Classify a single OGR row as derivatives, spot, or ambiguous (Task 5).

    The classifier uses two signals only: the OGR ``Type`` column and the
    existence of a CG counterpart whose disposal proceeds match the OGR
    magnitude within tolerance. No TH-label allowlist, no asset allowlist, no
    amount threshold (per r1 Blocker 2 and Monitor #2; these were proposed
    in the investigation and rejected as fragile).

    Classification matrix:

    - ``Type=Profit`` → Derivatives (profits never have CG counterparts in
      Koinly's model: realized derivatives P&L has no FIFO cost-basis trail).
    - ``Type=Loss`` with no CG counterpart → Derivatives (no spot disposal to
      anchor it).
    - ``Type=Loss`` with one CG whose ``proceeds_eur`` matches within tolerance
      → Spot (single-lot spot fee disposal).
    - ``Type=Loss`` with multiple CG whose aggregate ``proceeds_eur`` matches
      within tolerance → Spot (multi-lot spot fee disposal).
    - ``Type=Loss`` with one CG whose ``proceeds_eur`` mismatches → Ambiguous
      (single-CG suffix "manual review needed").
    - ``Type=Loss`` with multiple CG whose aggregate ``proceeds_eur``
      mismatches → Ambiguous (multi-CG suffix "aggregate-match check
      required").

    Args:
        ogr_row: The parsed OGR row under classification. ``gain_loss`` carries
            the OGR "Value (EUR)" column (disposal proceeds for Loss rows,
            realized P&L for Profit rows). ``abs(gain_loss)`` is compared
            against CG ``proceeds_eur``.
        cg_matches: CG entries that share the same ``(date, asset, wallet)``
            key as the OGR row. The caller (Task 7's ``_split_ogr_index``)
            computes this list; the classifier only inspects it.

    Returns:
        Sealed ``DerivativesClassification`` with one of three variants:
        ``Derivatives(reason)``, ``Spot(reason)``, or ``Ambiguous(reason)``.
        The ``kind`` discriminator drives downstream routing per the sealed-
        class sentinel pattern (Design Invariant 13).
    """
    if ogr_row.row_type == "Profit":
        return DerivativesClassification.Derivatives(
            reason="OGR Profit: derivatives P&L realization",
        )

    if ogr_row.row_type == "Loss":
        ogr_magnitude = abs(ogr_row.gain_loss)
        key_descriptor = f"({ogr_row.date}, {ogr_row.asset}, {ogr_row.wallet})"

        if len(cg_matches) == 0:
            return DerivativesClassification.Derivatives(
                reason="OGR Loss with no CG counterpart: derivatives realization",
            )

        if len(cg_matches) == 1:
            single_proceeds = cg_matches[0].proceeds_eur
            if abs(single_proceeds - ogr_magnitude) <= _TOLERANCE_OGR_CG:
                return DerivativesClassification.Spot(
                    reason="OGR Loss matches CG disposal: spot fee",
                )
            return DerivativesClassification.Ambiguous(
                reason=(
                    f"OGR={ogr_row.gain_loss} vs CG={single_proceeds} "
                    f"on {key_descriptor}: manual review needed"
                ),
            )

        # Multiple CG lots: aggregate proceeds comparison.
        aggregate_proceeds = sum(
            (cg.proceeds_eur for cg in cg_matches),
            start=Decimal("0"),
        )
        if abs(aggregate_proceeds - ogr_magnitude) <= _TOLERANCE_OGR_CG:
            return DerivativesClassification.Spot(
                reason=(
                    f"OGR Loss aggregate-matches {len(cg_matches)} CG lots: spot fee disposals"
                ),
            )
        return DerivativesClassification.Ambiguous(
            reason=(
                f"OGR={ogr_row.gain_loss} vs {len(cg_matches)} CG lots "
                f"on {key_descriptor}: aggregate-match check required"
            ),
        )

    # Unknown Type: defensive fallback. The plan's Monitor #2 requires that
    # unrecognized OGR shapes route to derivatives with review. Emit Ambiguous
    # with a specific reason rather than guessing. The current ByBit fixtures
    # only ever produce "Profit" or "Loss", so this branch is unreachable in
    # production data; it exists so future platforms with novel Type values
    # are flagged rather than silently mis-routed.
    return DerivativesClassification.Ambiguous(
        reason=(
            f"Unrecognized OGR Type='{ogr_row.row_type}' "
            f"on ({ogr_row.date}, {ogr_row.asset}, {ogr_row.wallet}): manual review needed"
        ),
    )
