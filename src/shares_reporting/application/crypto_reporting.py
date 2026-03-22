"""Crypto tax reporting helpers for Koinly exports."""

from __future__ import annotations

import csv
import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Final, TypedDict

import pycountry

from ..domain.exceptions import FileProcessingError

# Constants for decimal calculations
ZERO: Final = Decimal("0")
_MATERIALITY_THRESHOLD: Final = Decimal("1")

# Validation error display constants
_MAX_VALIDATION_ERROR_DISPLAY: Final = 5
# Ticker stripping constants
_MAX_TICKER_LENGTH: Final = 10
_SPLIT_PARTS_WITH_TICKER: Final = 2

# File size limits for security (prevent DoS via large files)
_MAX_CSV_BYTES: Final = 50 * 1024 * 1024  # 50 MB limit for CSV files


class RewardTaxClassification(Enum):
    """Tax classification status for crypto rewards per Portuguese law (CRG-001, CRG-002).

    taxable_now: Reward is immediately taxable as Category E income (remuneration not in crypto form).
    deferred_by_law: Reward received as cryptoassets, taxation deferred until disposal (CIRS art. 5(11)).
    """

    TAXABLE_NOW = "taxable_now"
    DEFERRED_BY_LAW = "deferred_by_law"


@dataclass(frozen=True)
class OperatorOrigin:
    """Operator and jurisdiction metadata for a wallet platform."""

    platform: str
    service_scope: str
    operator_entity: str
    operator_country: str
    source_url: str
    source_checked_on: str
    confidence: str
    review_required: bool


@dataclass(frozen=True)
class CryptoCapitalGainEntry:
    """Single taxable crypto disposal row for reporting."""

    disposal_date: str
    acquisition_date: str
    asset: str
    amount: Decimal
    cost_eur: Decimal
    proceeds_eur: Decimal
    gain_loss_eur: Decimal
    holding_period: str
    wallet: str
    platform: str
    chain: str
    operator_origin: OperatorOrigin
    annex_hint: str
    review_required: bool
    notes: str


@dataclass(frozen=True)
class CryptoRewardIncomeEntry:
    """Single crypto income/reward row for reporting."""

    date: str
    asset: str
    amount: Decimal
    value_eur: Decimal
    income_label: str
    source_type: str
    wallet: str
    platform: str
    chain: str
    operator_origin: OperatorOrigin
    annex_hint: str
    review_required: bool
    description: str
    tax_classification: RewardTaxClassification = RewardTaxClassification.DEFERRED_BY_LAW
    foreign_tax_eur: Decimal = ZERO


@dataclass(frozen=True)
class AggregatedRewardIncomeEntry:
    """Aggregated reward income for IRS filing (Anexo J Quadro 8A).

    Represents one line in the filing-ready rewards table after aggregation
    by income_code + source_country. Only includes rewards classified as taxable_now.

    Attributes:
        income_code: Tabela V income code for the reward type (e.g., "401" for crypto capital income).
        source_country: Tabela X country code where the income originated (from operator entity).
        gross_income_eur: Sum of all EUR values for this aggregation key.
        foreign_tax_eur: Sum of all foreign taxes paid (if any).
        raw_row_count: Number of original Koinly rows aggregated into this entry.
        chains: Sorted list of unique blockchain names contributing to this aggregated entry.
        description: Human-readable description of the aggregated income type.
    """

    income_code: str
    source_country: str
    gross_income_eur: Decimal
    foreign_tax_eur: Decimal
    raw_row_count: int
    chains: tuple[str, ...]
    description: str


@dataclass(frozen=True)
class HoldingsSnapshot:
    """Holdings totals for reconciliation."""

    asset_rows: int
    total_cost_eur: Decimal
    total_value_eur: Decimal


@dataclass(frozen=True)
class CryptoReconciliationSummary:
    """Control totals for capital and income sections."""

    capital_rows: int
    reward_rows: int
    short_term_rows: int
    long_term_rows: int
    mixed_rows: int
    unknown_rows: int
    capital_cost_total_eur: Decimal
    capital_proceeds_total_eur: Decimal
    capital_gain_total_eur: Decimal
    reward_total_eur: Decimal
    opening_holdings: HoldingsSnapshot | None
    closing_holdings: HoldingsSnapshot | None


@dataclass(frozen=True)
class CryptoSkippedZeroValueToken:
    """Asset skipped from report output because value is zero."""

    source_section: str
    asset: str
    count: int


@dataclass(frozen=True)
class CryptoCompletePdfSummary:
    """Extracted metadata from Koinly complete tax report PDF."""

    period: str | None
    timezone: str | None
    extracted_tokens: int


@dataclass(frozen=True)
class CryptoTaxReport:
    """Normalized crypto dataset ready for Excel rendering."""

    tax_year: int
    capital_entries: list[CryptoCapitalGainEntry]
    reward_entries: list[CryptoRewardIncomeEntry]
    reconciliation: CryptoReconciliationSummary
    skipped_zero_value_tokens: list[CryptoSkippedZeroValueToken] = field(default_factory=list)
    pdf_summary: CryptoCompletePdfSummary | None = None


# Crypto tokens that share tickers with ISO 4217 fiat currency codes.
# These are known cryptoassets that should be classified as deferred by law (CRG-001),
# even though their ticker collides with a fiat currency code.
_CRYPTO_TOKEN_FIAT_COLLISIONS: Final[frozenset[str]] = frozenset(
    (
        "GEL",  # Gelato Network token (fiat GEL = Georgian Lari)
    )
)


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


def aggregate_taxable_rewards(
    reward_entries: list[CryptoRewardIncomeEntry],
) -> list[AggregatedRewardIncomeEntry]:
    """Aggregate taxable_now reward entries by income_code + source_country for IRS filing.

    This function:
    1. Filters to only taxable_now rewards (deferred_by_law rewards are excluded)
    2. Groups by (income_code, source_country)
    3. Sums gross_income_eur and foreign_tax_eur within each group
    4. Preserves raw_row_count for reconciliation trail
    5. Validates that all mandatory IRS fields are present

    Args:
        reward_entries: All parsed reward entries from Koinly income report.

    Returns:
        List of aggregated reward entries ready for IRS filing.

    Raises:
        FileProcessingError: If a taxable_now row cannot be assigned valid Tabela X country.
    """
    logger = logging.getLogger(__name__)

    # Filter to only immediately taxable rewards
    taxable_entries = [e for e in reward_entries if e.tax_classification == RewardTaxClassification.TAXABLE_NOW]

    if not taxable_entries:
        return []

    # Validate that all taxable entries have valid Tabela X country codes before aggregation.
    # This ensures the IRS-ready filing table never contains entries with missing mandatory fields.
    for entry in taxable_entries:
        source_country = entry.operator_origin.operator_country
        if not _is_valid_tabela_x_country(source_country):
            raise FileProcessingError(
                f"Immediately taxable reward from wallet '{entry.wallet}' (asset: {entry.asset}, "
                f"value: {entry.value_eur} EUR) cannot be assigned a valid Tabela X country code. "
                f"Resolved country: '{source_country}'. Please add a valid country mapping "
                f"for this platform/operator in resolve_operator_origin()."
            )

    # Aggregate by (income_code, source_country)
    class _RewardGroup(TypedDict):
        entries: list[CryptoRewardIncomeEntry]
        gross_income: Decimal
        foreign_tax: Decimal
        chains: set[str]

    groups: dict[tuple[str, str], _RewardGroup] = {}
    for entry in taxable_entries:
        income_code = _resolve_income_code(entry.source_type)
        source_country = entry.operator_origin.operator_country.upper()
        key = (income_code, source_country)

        if key not in groups:
            groups[key] = {
                "entries": [],
                "gross_income": ZERO,
                "foreign_tax": ZERO,
                "chains": set(),
            }

        groups[key]["entries"].append(entry)
        groups[key]["gross_income"] += entry.value_eur
        groups[key]["foreign_tax"] += entry.foreign_tax_eur
        groups[key]["chains"].add(entry.chain)

    # Build aggregated entries
    aggregated = []
    for (income_code, source_country), data in sorted(groups.items()):
        entries = data["entries"]
        chains_tuple = tuple(sorted(data["chains"]))
        aggregated.append(
            AggregatedRewardIncomeEntry(
                income_code=income_code,
                source_country=source_country,
                gross_income_eur=data["gross_income"],
                foreign_tax_eur=data["foreign_tax"],
                raw_row_count=len(entries),
                chains=chains_tuple,
                description=f"Income code {income_code} from {source_country}",
            )
        )

    logger.info(
        "Aggregated %d taxable-now reward rows into %d filing-ready entries (income_code + source_country)",
        len(taxable_entries),
        len(aggregated),
    )

    return aggregated


# Portuguese Tabela X country codes for IRS filing (ISO 3166-1 alpha-2)
_TABELA_X_COUNTRY_CODES: Final = frozenset(
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
_KOINLY_TYPE_TO_INCOME_CODE: Final[dict[str, str]] = {
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

_MAX_PDF_BYTES: Final = 20 * 1024 * 1024  # 20 MB limit for PDF parsing (increased from 10 MB due to growing Koinly report sizes)
DATE_FORMATS: Final = (
    "%d/%m/%Y %H:%M",
    "%Y-%m-%d %H:%M:%S UTC",
    "%Y-%m-%d %H:%M:%S",
    "%d/%m/%Y",
    "%Y-%m-%d",
)


def resolve_operator_origin(platform: str, transaction_type: str | None = None) -> OperatorOrigin:  # noqa: PLR0911, PLR0912
    """Resolve operator metadata from platform brand and transaction type.

    Source-country resolution hierarchy for DeFi:
    1. Interface legal entity (the exposed contracting party)
    2. Protocol / foundation / sponsoring legal entity
    3. Validator operator (when identifiable)

    IMPORTANT: This function NEVER defaults to the taxpayer's residence country.
    The source country must be derived from the paying entity / platform / protocol
    legal-entity domicile, not from where the taxpayer performed the activity.

    Args:
        platform: Wallet or platform name (e.g., "Ledger Berachain", "ByBit").
        transaction_type: Optional hint for service scope (e.g., "crypto_disposal", "fiat_deposit").

    Returns:
        OperatorOrigin with the resolved operator entity and country.
        Returns operator_country="UNKNOWN" and review_required=True for unrecognized platforms.
    """
    normalized = platform.lower()
    transaction_type_normalized = (transaction_type or "").lower()

    if "wirex" in normalized:
        if transaction_type_normalized.startswith("fiat"):
            return OperatorOrigin(
                platform="Wirex",
                service_scope="fiat",
                operator_entity="Wirex Limited",
                operator_country="GB",
                source_url="https://wirexapp.com/legal",
                source_checked_on="2026-03-08",
                confidence="medium",
                review_required=True,
            )
        return OperatorOrigin(
            platform="Wirex",
            service_scope="crypto",
            operator_entity="Wirex Digital (crypto operator, verify account terms)",
            operator_country="HR",
            source_url="https://wirexapp.com/legal",
            source_checked_on="2026-03-08",
            confidence="medium",
            review_required=True,
        )

    if "bybit" in normalized:
        return OperatorOrigin(
            platform="Bybit",
            service_scope="crypto",
            operator_entity="Bybit group entity (account-region specific)",
            operator_country="AE",
            source_url="https://www.bybit.com/en/legal/terms-of-service/terms-of-service",
            source_checked_on="2026-03-08",
            confidence="low",
            review_required=True,
        )

    if "berachain" in normalized:
        return OperatorOrigin(
            platform="Berachain",
            service_scope="crypto",
            operator_entity="BERA Chain Foundation",
            operator_country="VG",
            source_url="https://www.berachain.com/terms-of-service",
            source_checked_on="2026-03-15",
            confidence="high",
            review_required=False,
        )

    if "starknet" in normalized:
        return OperatorOrigin(
            platform="Starknet",
            service_scope="crypto",
            operator_entity="Starknet Foundation",
            operator_country="KY",
            source_url="https://www.starknet.io/privacy-policy/",
            source_checked_on="2026-03-15",
            confidence="medium",
            review_required=True,
        )

    if "zksync" in normalized:
        return OperatorOrigin(
            platform="zkSync",
            service_scope="crypto",
            operator_entity="Matter Labs",
            operator_country="KY",
            source_url="https://zksync.io/terms",
            source_checked_on="2026-03-15",
            confidence="high",
            review_required=False,
        )

    if "solana" in normalized:
        return OperatorOrigin(
            platform="Solana",
            service_scope="crypto",
            operator_entity="Solana Foundation",
            operator_country="CH",
            source_url="https://solana.org/",
            source_checked_on="2026-03-15",
            confidence="medium",
            review_required=False,
        )

    # Handle both correct "Tonkeeper" and common typo "Tonkeper" from Koinly exports
    if "tonkeeper" in normalized or "tonkeper" in normalized:
        return OperatorOrigin(
            platform="Tonkeeper",
            service_scope="crypto",
            operator_entity="Ton Apps UK Ltd.",
            operator_country="GB",
            source_url="https://tonkeeper.com/terms",
            source_checked_on="2026-03-15",
            confidence="high",
            review_required=False,
        )

    if re.search(r"\bton\b", normalized) and "tonkeeper" not in normalized and "tonkeper" not in normalized:
        return OperatorOrigin(
            platform="TON",
            service_scope="crypto",
            operator_entity="TON Foundation",
            operator_country="CH",
            source_url="https://ton.foundation/",
            source_checked_on="2026-03-15",
            confidence="high",
            review_required=False,
        )

    if "ethereum" in normalized:
        return OperatorOrigin(
            platform="Ethereum",
            service_scope="crypto",
            operator_entity="Ethereum Foundation",
            operator_country="CH",
            source_url="https://blog.ethereum.org/2024/05/08/ethereum-foundation-report-2024",
            source_checked_on="2026-03-15",
            confidence="high",
            review_required=False,
        )

    if "aptos" in normalized:
        return OperatorOrigin(
            platform="Aptos",
            service_scope="crypto",
            operator_entity="Aptos Foundation",
            operator_country="KY",
            source_url="https://aptosfoundation.org/terms",
            source_checked_on="2026-03-15",
            confidence="high",
            review_required=False,
        )

    if re.search(r"\bsui\b", normalized):
        return OperatorOrigin(
            platform="Sui",
            service_scope="crypto",
            operator_entity="Sui Foundation",
            operator_country="KY",
            source_url="https://www.sui.io/terms",
            source_checked_on="2026-03-15",
            confidence="medium",
            review_required=False,
        )

    if "arbitrum" in normalized:
        return OperatorOrigin(
            platform="Arbitrum",
            service_scope="crypto",
            operator_entity="The Arbitrum Foundation",
            operator_country="KY",
            source_url="https://docs.arbitrum.foundation/assets/files/The%20Arbitrum%20Foundation%20M%26A%20-%2020%20July%202023-6e264ee4c38da73a3aa4c8581c5f751f.pdf",
            source_checked_on="2026-03-15",
            confidence="high",
            review_required=False,
        )

    if re.search(r"\bmantle\b", normalized):
        return OperatorOrigin(
            platform="Mantle",
            service_scope="crypto",
            operator_entity="Mantle Foundation S.A.",
            operator_country="VG",
            source_url="https://www.ipd.gov.hk/hkipjournal/15032024/PUBLICATION_TYPE_TRADE_MARK_REGISTERED.pdf",
            source_checked_on="2026-03-15",
            confidence="medium",
            review_required=True,
        )

    if "polygon" in normalized:
        return OperatorOrigin(
            platform="Polygon",
            service_scope="crypto",
            operator_entity="Polygon Labs UI (Cayman) Ltd.",
            operator_country="KY",
            source_url="https://polygon.technology/terms-of-use",
            source_checked_on="2026-03-15",
            confidence="high",
            review_required=False,
        )

    if re.search(r"\bbase\b", normalized) and "coinbase" not in normalized:
        return OperatorOrigin(
            platform="BASE",
            service_scope="crypto",
            operator_entity="Coinbase Technologies, Inc.",
            operator_country="US",
            source_url="https://docs.base.org/terms-of-service",
            source_checked_on="2026-03-15",
            confidence="medium",
            review_required=False,
        )

    if "filecoin" in normalized:
        return OperatorOrigin(
            platform="Filecoin",
            service_scope="crypto",
            operator_entity="Filecoin Foundation",
            operator_country="US",
            source_url="https://careers.fil.org/privacy-policy",
            source_checked_on="2026-03-15",
            confidence="medium",
            review_required=False,
        )

    if "binance" in normalized:
        return OperatorOrigin(
            platform="Binance",
            service_scope="crypto",
            operator_entity="Binance Spain, S.L. (Europe override for filing output)",
            operator_country="ES",
            source_url="https://www.binance.com/es/about-legal/local-terms",
            source_checked_on="2026-03-15",
            confidence="medium",
            review_required=False,
        )

    if "gate.io" in normalized or normalized == "gate":
        return OperatorOrigin(
            platform="Gate.io",
            service_scope="crypto",
            operator_entity="Gate Technology Ltd",
            operator_country="MT",
            source_url="https://www.gate.com/en-eu/about-us",
            source_checked_on="2026-03-15",
            confidence="high",
            review_required=False,
        )

    if "kraken" in normalized:
        return OperatorOrigin(
            platform="Kraken",
            service_scope="crypto",
            operator_entity="Payward Ireland Limited / Payward Europe Solutions Limited",
            operator_country="IE",
            source_url="https://support.kraken.com/articles/where-is-kraken-licensed-or-regulated",
            source_checked_on="2026-03-15",
            confidence="high",
            review_required=False,
        )

    return OperatorOrigin(
        platform=platform,
        service_scope="crypto",
        operator_entity="UNKNOWN_OPERATOR_REVIEW_REQUIRED",
        operator_country="UNKNOWN",
        source_url="",
        source_checked_on="2026-03-08",
        confidence="low",
        review_required=True,
    )


def load_koinly_crypto_report(koinly_dir: Path) -> CryptoTaxReport | None:
    """Load Koinly exports from a directory and normalize for tax reporting."""
    if not koinly_dir.exists() or not koinly_dir.is_dir():
        return None

    capital_file = _find_report_file(koinly_dir, "capital_gains_report")
    income_file = _find_report_file(koinly_dir, "income_report")

    if capital_file is None and income_file is None:
        return None

    year = _extract_tax_year(koinly_dir, capital_file, income_file)
    skipped_assets: Counter[tuple[str, str]] = Counter()
    capital_entries = _parse_capital_gains_file(capital_file, skipped_assets) if capital_file else []
    reward_entries = _parse_income_file(income_file, skipped_assets) if income_file else []

    opening = _parse_holdings_file(
        _find_report_file(koinly_dir, "beginning_of_year_holdings_report"),
        "holdings_opening",
        skipped_assets,
    )
    closing = _parse_holdings_file(
        _find_report_file(koinly_dir, "end_of_year_holdings_report"),
        "holdings_closing",
        skipped_assets,
    )

    short_term_rows = sum(1 for row in capital_entries if row.holding_period.lower().startswith("short"))
    long_term_rows = sum(1 for row in capital_entries if row.holding_period.lower().startswith("long"))
    mixed_rows = sum(1 for row in capital_entries if row.holding_period.lower() == "mixed")
    unknown_rows = sum(1 for row in capital_entries if row.holding_period.lower() == "unknown")

    _recon_logger = logging.getLogger(__name__)
    categorised = short_term_rows + long_term_rows + mixed_rows + unknown_rows
    if categorised != len(capital_entries):
        unclassified = [
            row.holding_period
            for row in capital_entries
            if not row.holding_period.lower().startswith(("short", "long"))
            and row.holding_period.lower() not in ("mixed", "unknown")
        ]
        _recon_logger.warning(
            "Reconciliation mismatch: %d capital entries but only %d categorised by holding period. "
            "Unrecognised holding_period values: %s",
            len(capital_entries),
            categorised,
            sorted(set(unclassified)),
        )

    reconciliation = CryptoReconciliationSummary(
        capital_rows=len(capital_entries),
        reward_rows=len(reward_entries),
        short_term_rows=short_term_rows,
        long_term_rows=long_term_rows,
        mixed_rows=mixed_rows,
        unknown_rows=unknown_rows,
        capital_cost_total_eur=sum((row.cost_eur for row in capital_entries), start=ZERO),
        capital_proceeds_total_eur=sum((row.proceeds_eur for row in capital_entries), start=ZERO),
        capital_gain_total_eur=sum((row.gain_loss_eur for row in capital_entries), start=ZERO),
        reward_total_eur=sum((row.value_eur for row in reward_entries), start=ZERO),
        opening_holdings=opening,
        closing_holdings=closing,
    )

    skipped_zero_value_tokens = [
        CryptoSkippedZeroValueToken(source_section=section, asset=asset, count=count)
        for (section, asset), count in sorted(skipped_assets.items())
    ]

    complete_tax_report_file = _find_report_path(koinly_dir, "complete_tax_report", ".pdf")
    pdf_summary = _parse_complete_tax_report_pdf(complete_tax_report_file) if complete_tax_report_file else None

    return CryptoTaxReport(
        tax_year=year,
        capital_entries=capital_entries,
        reward_entries=reward_entries,
        reconciliation=reconciliation,
        skipped_zero_value_tokens=skipped_zero_value_tokens,
        pdf_summary=pdf_summary,
    )


def _find_report_file(koinly_dir: Path, marker: str) -> Path | None:
    return _find_report_path(koinly_dir, marker, ".csv")


def _find_report_path(koinly_dir: Path, marker: str, suffix: str) -> Path | None:
    matches = sorted(koinly_dir.glob(f"*{marker}*{suffix}"))
    return matches[0] if matches else None


def _extract_tax_year(koinly_dir: Path, capital_file: Path | None, income_file: Path | None) -> int:
    for candidate in [capital_file, income_file]:
        if candidate is None:
            continue
        match = re.search(r"koinly_(\d{4})_", candidate.name)
        if match:
            return int(match.group(1))
    fallback_match = re.search(r"(\d{4})", koinly_dir.name)
    if fallback_match:
        return int(fallback_match.group(1))
    return datetime.now(tz=UTC).year


def _aggregate_capital_entries(entries: list[CryptoCapitalGainEntry]) -> list[CryptoCapitalGainEntry]:
    """Aggregate FIFO lot rows into one line per sale event (same timestamp + asset + platform + holding_period).

    Rationale: the sale transaction is the reportable alienação in Portuguese IRS Quadro 9.4.
    FIFO lot allocation is an accounting method, not a separate disposal event (PT-C-025, PT-C-027).

    The holding_period is included in the aggregation key to preserve the taxable vs exempt breakdown
    needed for correct filing (PT-C-011: short-term gains are taxable, long-term gains are exempt).

    Uses normalized platform name in aggregation key so wallet aliases (e.g., "ByBit" and "ByBit (2)")
    collapse into the same logical account.
    """
    groups: dict[tuple[str, str, str, str], list[CryptoCapitalGainEntry]] = {}
    for entry in entries:
        key = (entry.disposal_date, entry.asset, entry.platform, entry.holding_period)
        groups.setdefault(key, []).append(entry)

    logger = logging.getLogger(__name__)
    result = []
    for group in groups.values():
        first = group[0]
        acquisition_date = min(e.acquisition_date for e in group)
        if acquisition_date.startswith("1970-"):
            logger.warning(
                "Aggregated entry for %r sold %s has epoch sentinel acquisition date — "
                "one or more lots had missing Date Acquired in Koinly export",
                first.asset,
                first.disposal_date,
            )
        result.append(
            CryptoCapitalGainEntry(
                disposal_date=first.disposal_date,
                acquisition_date=acquisition_date,
                asset=first.asset,
                amount=sum((e.amount for e in group), start=ZERO),
                cost_eur=sum((e.cost_eur for e in group), start=ZERO),
                proceeds_eur=sum((e.proceeds_eur for e in group), start=ZERO),
                gain_loss_eur=sum((e.gain_loss_eur for e in group), start=ZERO),
                holding_period=first.holding_period,
                wallet=first.wallet,
                platform=first.platform,
                chain=first.chain,
                operator_origin=first.operator_origin,
                annex_hint=first.annex_hint,
                review_required=any(e.review_required for e in group),
                notes="; ".join(dict.fromkeys(e.notes for e in group if e.notes)),
            )
        )
    result.sort(key=lambda e: (e.disposal_date, e.asset, e.platform, e.holding_period))
    return result


def _filter_immaterial_entries(entries: list[CryptoCapitalGainEntry]) -> list[CryptoCapitalGainEntry]:
    """Drop lines where |gain/loss| < 1 EUR after aggregation (PT-C-028).

    Sub-1-EUR lines have no material tax impact and AT portal requires manual entry per line.
    The absolute-value test means small losses (between -1 and 0) are also excluded.
    """
    return [e for e in entries if abs(e.gain_loss_eur) >= _MATERIALITY_THRESHOLD]


def _validate_capital_entries_have_valid_countries(entries: list[CryptoCapitalGainEntry]) -> None:
    """Validate that all capital entries have valid Tabela X country codes.

    This ensures the final workbook output never contains unresolved mandatory IRS fields.
    The source country must be derived from the paying entity/platform/protocol legal-entity
    domicile, never from the taxpayer's residence country.

    Args:
        entries: Parsed capital gain entries to validate.

    Raises:
        FileProcessingError: If any entry has an invalid Tabela X country code.
    """
    logger = logging.getLogger(__name__)
    invalid_entries = []

    for entry in entries:
        country = entry.operator_origin.operator_country
        if not _is_valid_tabela_x_country(country):
            invalid_entries.append(
                {
                    "wallet": entry.wallet,
                    "asset": entry.asset,
                    "disposal_date": entry.disposal_date,
                    "country": country,
                    "platform": entry.platform,
                }
            )

    if invalid_entries:
        error_details = "\n".join(
            f"  - Wallet: {e['wallet']}, Asset: {e['asset']}, Date: {e['disposal_date']}, "
            f"Resolved country: '{e['country']}' from platform '{e['platform']}'"
            for e in invalid_entries[:_MAX_VALIDATION_ERROR_DISPLAY]  # Show first 5 for readability
        )
        if len(invalid_entries) > _MAX_VALIDATION_ERROR_DISPLAY:
            error_details += f"\n  ... and {len(invalid_entries) - _MAX_VALIDATION_ERROR_DISPLAY} more"

        raise FileProcessingError(
            f"Cannot generate crypto capital gains report: {len(invalid_entries)} entries have "
            f"invalid Tabela X country codes. Please add valid country mappings for these platforms "
            f"in resolve_operator_origin().\n{error_details}"
        )

    logger.debug(
        "Validated %d capital entries: all have valid Tabela X country codes",
        len(entries),
    )


def _parse_capital_gains_file(path: Path, skipped_assets: Counter[tuple[str, str]]) -> list[CryptoCapitalGainEntry]:
    rows = _read_koinly_rows(path)
    capital_entries: list[CryptoCapitalGainEntry] = []

    logger = logging.getLogger(__name__)
    for row_number, row in enumerate(rows, start=1):
        asset = row.get("Asset", "").strip()
        try:
            cost_eur = _parse_koinly_decimal(row.get("Cost (EUR)", ""))
            proceeds_eur = _parse_koinly_decimal(row.get("Proceeds (EUR)", ""))
            gain_loss_eur = _parse_koinly_decimal(row.get("Gain / loss", ""))
            amount = _parse_koinly_decimal(row.get("Amount", ""))
            disposal_date = _format_datetime(_parse_koinly_datetime(row.get("Date Sold", "")))
            acquisition_date = _format_datetime(_parse_koinly_datetime(row.get("Date Acquired", "")))
        except ValueError as exc:
            logger.warning("Skipping capital gains row %d for %r — ambiguous decimal value: %s", row_number, asset, exc)
            continue

        if cost_eur == ZERO and proceeds_eur == ZERO and gain_loss_eur == ZERO:
            _register_skipped_zero_asset(skipped_assets, "capital_gains", asset)
            continue

        wallet = row.get("Wallet Name", "").strip()
        platform = _normalize_platform_name(wallet)
        operator_origin = resolve_operator_origin(platform, transaction_type="crypto_disposal")
        notes = row.get("Notes", "").strip()
        review_required = operator_origin.review_required or "missing cost basis" in notes.lower()
        holding_period = row.get("Holding period", "").strip() or "Unknown"
        # PT-C-011: long-term (≥365 days) exempt gains → Anexo G1; short-term taxable → Anexo J
        annex_hint = "G1" if holding_period.lower().startswith("long") else "J"

        capital_entries.append(
            CryptoCapitalGainEntry(
                disposal_date=disposal_date,
                acquisition_date=acquisition_date,
                asset=asset,
                amount=amount,
                cost_eur=cost_eur,
                proceeds_eur=proceeds_eur,
                gain_loss_eur=gain_loss_eur,
                holding_period=holding_period,
                wallet=wallet,
                platform=platform,
                chain=_derive_chain(wallet),
                operator_origin=operator_origin,
                annex_hint=annex_hint,
                review_required=review_required,
                notes=notes,
            )
        )

    # Validate that all entries have valid Tabela X country codes BEFORE aggregation/filtering.
    # This ensures invalid entries are caught even if they would be filtered out as immaterial.
    _validate_capital_entries_have_valid_countries(capital_entries)

    capital_entries = _aggregate_capital_entries(capital_entries)
    pre_filter_count = len(capital_entries)
    capital_entries = _filter_immaterial_entries(capital_entries)
    dropped = pre_filter_count - len(capital_entries)
    if dropped > 0:
        logger.warning(
            "Filtered %d sub-1-EUR capital gain entries (PT-C-028); %d entries retained",
            dropped,
            len(capital_entries),
        )

    return capital_entries


def _parse_income_file(path: Path, skipped_assets: Counter[tuple[str, str]]) -> list[CryptoRewardIncomeEntry]:
    rows = _read_koinly_rows(path)
    reward_entries: list[CryptoRewardIncomeEntry] = []
    logger = logging.getLogger(__name__)

    for row_number, row in enumerate(rows, start=1):
        asset = row.get("Asset", "").strip()
        try:
            value_eur = _parse_koinly_decimal(row.get("Value (EUR)", ""))
            amount = _parse_koinly_decimal(row.get("Amount", ""))
            date = _format_datetime(_parse_koinly_datetime(row.get("Date", "")))
        except ValueError as exc:
            logger.warning("Skipping income row %d for %r — ambiguous decimal value: %s", row_number, asset, exc)
            continue

        if value_eur == ZERO:
            _register_skipped_zero_asset(skipped_assets, "income", asset)
            continue

        wallet = row.get("Wallet Name", "").strip()
        platform = _normalize_platform_name(wallet)
        description = row.get("Description", "").strip()

        # Classify reward tax status based on asset type (CRG-001, CRG-002)
        # Must be done BEFORE operator origin resolution for platforms that split by fiat/crypto (e.g., Wirex)
        tax_classification = _classify_reward_tax_status(asset)

        # Determine transaction type for operator origin resolution based on asset classification
        # Platforms like Wirex have different operators for fiat vs crypto transactions
        if tax_classification == RewardTaxClassification.TAXABLE_NOW:
            transaction_type = "fiat_deposit"
        else:
            transaction_type = "crypto_deposit"

        operator_origin = resolve_operator_origin(platform, transaction_type=transaction_type)

        # Parse foreign tax if present in Koinly report (optional field)
        foreign_tax_eur = ZERO
        review_required = operator_origin.review_required
        if "Tax (EUR)" in row or "Foreign Tax" in row:
            try:
                tax_field = row.get("Tax (EUR)", "") or row.get("Foreign Tax", "")
                foreign_tax_eur = _parse_koinly_decimal(tax_field)
            except ValueError as exc:
                logger.warning(
                    "Row %d: Could not parse foreign tax for asset %r (value: %s EUR, field value: %r): %s. "
                    "Foreign tax credits will be omitted from this entry. Please verify the Koinly export.",
                    row_number,
                    asset,
                    value_eur,
                    tax_field if tax_field else "(empty)",
                    exc,
                )
                review_required = True  # Flag for manual review since tax data was lost

        reward_entries.append(
            CryptoRewardIncomeEntry(
                date=date,
                asset=asset,
                amount=amount,
                value_eur=value_eur,
                income_label="Reward",
                source_type=row.get("Type", "").strip(),
                wallet=wallet,
                platform=platform,
                chain=_derive_chain(wallet),
                operator_origin=operator_origin,
                annex_hint="J",
                review_required=review_required,
                description=description,
                tax_classification=tax_classification,
                foreign_tax_eur=foreign_tax_eur,
            )
        )

    return reward_entries


def _parse_holdings_file(
    path: Path | None, source_section: str, skipped_assets: Counter[tuple[str, str]]
) -> HoldingsSnapshot | None:
    if path is None:
        return None

    rows = _read_koinly_rows(path)
    logger = logging.getLogger(__name__)
    asset_rows = 0
    total_cost_eur = ZERO
    total_value_eur = ZERO

    for row in rows:
        asset = row.get("Asset", "").strip()
        try:
            value_eur = _parse_koinly_decimal(row.get("Value (EUR)", ""))
            cost_eur = _parse_koinly_decimal(row.get("Cost (EUR)", ""))
        except ValueError as exc:
            logger.warning("Skipping holdings row for %r — ambiguous decimal value: %s", asset, exc)
            continue
        if value_eur == ZERO:
            _register_skipped_zero_asset(skipped_assets, source_section, asset)
            continue
        asset_rows += 1
        total_cost_eur += cost_eur
        total_value_eur += value_eur

    return HoldingsSnapshot(
        asset_rows=asset_rows,
        total_cost_eur=total_cost_eur,
        total_value_eur=total_value_eur,
    )


def _parse_complete_tax_report_pdf(path: Path) -> CryptoCompletePdfSummary | None:
    file_size = path.stat().st_size
    if file_size > _MAX_PDF_BYTES:
        logging.getLogger(__name__).warning(
            "PDF file %s exceeds size limit (%d bytes, max %d bytes) - skipping metadata extraction",
            path.name,
            file_size,
            _MAX_PDF_BYTES,
        )
        return None
    content = path.read_bytes()
    hex_tokens = re.findall(rb"<([0-9A-Fa-f]{2,})>", content)
    decoded_tokens = [_decode_pdf_hex_token(token) for token in hex_tokens]
    cleaned_tokens = [token for token in decoded_tokens if token]

    if not cleaned_tokens:
        return None

    joined = " ".join(cleaned_tokens)
    period_match = re.search(r"\b\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}\s+to\s+\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}\b", joined)
    timezone_match = re.search(r"\b[A-Za-z]+/[A-Za-z_]+(?:/[A-Za-z_]+)?\b", joined)

    return CryptoCompletePdfSummary(
        period=period_match.group(0) if period_match else None,
        timezone=timezone_match.group(0) if timezone_match else None,
        extracted_tokens=len(cleaned_tokens),
    )


def _decode_pdf_hex_token(token: bytes) -> str:
    if len(token) % 2 != 0:
        return ""
    try:
        raw = bytes.fromhex(token.decode("ascii"))
    except ValueError:
        return ""
    if not raw:
        return ""
    text = raw.decode("utf-16-be", errors="ignore") if b"\x00" in raw else raw.decode("utf-8", errors="ignore")
    text = text.replace("\x00", "").strip()
    return text if text else ""


def _register_skipped_zero_asset(skipped_assets: Counter[tuple[str, str]], section: str, asset: str) -> None:
    cleaned_asset = asset or "UNKNOWN_ASSET"
    skipped_assets[(section, cleaned_asset)] += 1


def _read_koinly_rows(path: Path) -> list[dict[str, str]]:
    file_size = path.stat().st_size
    if file_size > _MAX_CSV_BYTES:
        raise FileProcessingError(
            f"CSV file {path.name} exceeds size limit ({file_size} bytes, max {_MAX_CSV_BYTES} bytes)"
        )
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    header_index = _detect_header_index(lines, path)
    reader = csv.DictReader(lines[header_index:])

    rows: list[dict[str, str]] = []
    for row in reader:
        if all((value is None or str(value).strip() == "") for value in row.values()):
            continue
        rows.append({key: (value or "") for key, value in row.items() if key is not None})
    return rows


def _detect_header_index(lines: list[str], path: Path) -> int:
    header_markers = ("Date Sold", "Date Acquired", "Date,", "Asset,Quantity", "Currency,Wallet")
    for index, line in enumerate(lines):
        if "," not in line:
            continue
        if any(marker in line for marker in header_markers):
            return index
    raise ValueError(f"Unable to detect CSV header in Koinly export: {path}")


def _parse_koinly_datetime(value: str) -> datetime:
    text = value.strip()
    if not text:
        return datetime(1970, 1, 1, tzinfo=UTC)

    for date_format in DATE_FORMATS:
        try:
            parsed = datetime.strptime(text, date_format)  # noqa: DTZ007
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError:
            continue
    raise ValueError(f"Unsupported Koinly date format: {value}")


def _format_datetime(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _parse_koinly_decimal(value: str) -> Decimal:
    text = value.strip().replace("\u00a0", "").replace(" ", "")
    if not text:
        return ZERO
    if text.startswith('"') and text.endswith('"'):
        text = text[1:-1]
    if text in {"", "-"}:
        return ZERO
    text = _normalize_koinly_decimal_text(text)
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"Unsupported Koinly decimal format: {value}") from exc


def _normalize_koinly_decimal_text(text: str) -> str:
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            return text.replace(".", "").replace(",", ".")
        return text.replace(",", "")

    if "," in text:
        # Comma-grouped single-triplet (e.g. "8,400") is treated as thousands, not decimal.
        # Koinly always quotes decimal-comma values (e.g. '"8,40000000"'), so an unquoted bare
        # "8,400" is unambiguously a large integer. This is intentionally asymmetric with the
        # dot case below, where a single-group dot (e.g. "1.234") is raised as ambiguous.
        if re.fullmatch(r"[+-]?[1-9]\d{0,2}(,\d{3})+", text):
            return text.replace(",", "")
        return text.replace(",", ".")

    if "." in text and re.fullmatch(r"[+-]?[1-9]\d{0,2}(\.\d{3}){2,}", text):
        return text.replace(".", "")

    if "." in text and re.fullmatch(r"[+-]?[1-9]\d{0,2}\.\d{3}", text):
        raise ValueError(f"Ambiguous decimal format: {text!r} — dot could be thousands separator or decimal point")

    return text


def _normalize_platform_name(wallet: str) -> str:
    """Normalize platform aliases for consistent operator resolution and aggregation.

    This function normalizes only the ByBit platform alias (e.g., "ByBit (2)" -> "ByBit")
    where the suffix represents a duplicate account in Koinly, not a distinct wallet.
    This is a repository-specific normalization per CRG-008.

    For all other wallets, including distinct numbered wallets like "Kraken (2)",
    the full wallet name is preserved to prevent incorrect aggregation of separate
    disposal events. Koinly may use numbered suffixes for genuinely distinct wallets
    on the same platform.

    Args:
        wallet: The raw wallet name from Koinly.

    Returns:
        Normalized platform name for ByBit aliases, or the original wallet name.
        Returns "Unknown" for empty wallets.
    """
    cleaned = wallet.strip()
    if not cleaned:
        return "Unknown"

    # Normalize only ByBit numbered aliases (repository-specific rule per CRG-008)
    # "ByBit (2)", "ByBit (3)", etc. -> "ByBit"
    # This must NOT match other ByBit-prefixed wallets like "ByBit Earn (2)"
    if re.match(r"^ByBit \(\d+\)$", cleaned):
        return "ByBit"

    return cleaned


# Chain names from docs/tax/crypto-origin/operator_chain_origin_registry.md
# These are the canonical chain identifiers used for reporting
_KNOWN_CHAINS: Final = frozenset(
    {
        "Berachain",
        "Starknet",
        "zkSync ERA",
        "Solana",
        "TON",
        "Ethereum",
        "Aptos",
        "Sui",
        "Arbitrum",
        "Mantle",
        "Polygon",
        "BASE",
        "Filecoin",
        "Binance Smart Chain",
        "ByBit",
        "Gate.io",
        "Kraken",
        "Binance",
        "Wirex",
        "Tonkeeper",
    }
)


def _derive_chain(wallet: str) -> str:  # noqa: PLR0911, PLR0912
    """Derive the blockchain/chain identifier from a wallet label.

    Uses deterministic normalization rules to extract chain names from wallet labels.
    The wallet/platform name is only a discovery hint; final mappings come from
    trusted sources in docs/tax/crypto-origin/operator_chain_origin_registry.md.

    Normalization rules:
    - Strip platform aliases like "Ledger " prefix
    - Strip asset tickers in parentheses (e.g., "(ETH)", "(SOL)")
    - Strip address suffixes after " - " (e.g., " - 0x6ABd...")
    - Normalize platform aliases (e.g., "ByBit (2)" -> "ByBit")

    Args:
        wallet: The raw wallet name from Koinly (e.g., "Ledger Berachain (BERA)",
               "Ethereum (ETH) - 0x6ABd...", "ByBit (2)").

    Returns:
        The normalized chain name if matched against known chains,
        or "Unknown" if the wallet label does not allow reasonable derivation.
    """
    if not wallet or not wallet.strip():
        return "Unknown"

    normalized = wallet.strip()

    # Normalize wallet aliases (e.g., "ByBit (2)" -> "ByBit")
    normalized = _normalize_platform_name(normalized)

    # Strip "Ledger " prefix if present (common Koinly pattern)
    if normalized.lower().startswith("ledger "):
        normalized = normalized[7:].strip()  # len("ledger ") == 7

    # Strip address suffixes after " - " (e.g., "Ethereum (ETH) - 0x6ABd...")
    if " - " in normalized:
        normalized = normalized.split(" - ", maxsplit=1)[0].strip()

    # Strip asset tickers in parentheses (e.g., "(ETH)", "(SOL)", "(BERA)")
    # Match pattern like "Ethereum (ETH)" or "Solana (SOL) - ..."
    if " (" in normalized and ")" in normalized:
        parts = normalized.split(" (", maxsplit=1)
        if len(parts) == _SPLIT_PARTS_WITH_TICKER and ")" in parts[1]:
            # Extract the base name before the ticker
            ticker_part = parts[1].split(")", maxsplit=1)
            # Only strip if it looks like a ticker (short, uppercase letters)
            if len(ticker_part[0]) <= _MAX_TICKER_LENGTH and ticker_part[0].isalpha():
                normalized = parts[0].strip()
            # else: keep the original if the parenthesized content isn't a simple ticker

    # Now match against known chains (case-insensitive)
    normalized_lower = normalized.lower()

    # Direct match against known chains
    for known_chain in _KNOWN_CHAINS:
        if normalized_lower == known_chain.lower():
            return known_chain

    # Check if the wallet name contains a known chain as a word
    # Sort by length descending to prefer more specific matches first
    chain_list = sorted(_KNOWN_CHAINS, key=len, reverse=True)
    for known_chain in chain_list:
        chain_lower = known_chain.lower()
        # Match word boundaries for chain names
        if f" {chain_lower} " in f" {normalized_lower} ":
            return known_chain
        # Match at start
        if normalized_lower.startswith(chain_lower + " "):
            return known_chain
        # Match at end
        if normalized_lower.endswith(" " + chain_lower):
            return known_chain

    # Special case: "bnb" or "bsc" -> Binance Smart Chain
    if "bnb" in normalized_lower or "bsc" in normalized_lower:
        return "Binance Smart Chain"

    # Special case: "gate" (with or without .io) -> Gate.io
    # Match "gate", "gate ", or any wallet containing "gate" and ".io" (e.g., "Gate.io")
    is_gate_wallet = (
        normalized_lower == "gate"
        or normalized_lower.startswith("gate ")
        or ("gate" in normalized_lower and ".io" in normalized_lower)
    )
    if is_gate_wallet:
        return "Gate.io"

    # No match found - return Unknown instead of guessing
    return "Unknown"
