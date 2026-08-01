"""Chain derivation from wallet labels.

Uses deterministic normalization rules to extract chain names from wallet labels.
The wallet/platform name is only a discovery hint; final mappings come from
trusted sources in docs/maintenance/tax/crypto-origin/operator_chain_origin_registry.md.
"""

from __future__ import annotations

from datetime import date
from typing import Final

from ...infrastructure.koinly_parser import normalize_platform_name

# Ticker stripping constants
_MAX_TICKER_LENGTH: Final = 10
_SPLIT_PARTS_WITH_TICKER: Final = 2

# Chain names from docs/maintenance/tax/crypto-origin/operator_chain_origin_registry.md
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
_KNOWN_CHAINS_BY_LENGTH: Final = tuple(sorted(_KNOWN_CHAINS, key=len, reverse=True))

# Chain -> native gas-token ticker. Native gas is a protocol fact (not jurisdiction/year
# law), so it lives next to _KNOWN_CHAINS. CEX names (ByBit, Kraken, Binance, Gate.io,
# Wirex, Tonkeeper) are intentionally absent: their fees are a CEX mechanic caught by the
# leg-check, not on-chain native gas. Tickers are uppercase (case-sensitive comparison).
_CHAIN_NATIVE_FEE_ASSET: Final[dict[str, str]] = {
    "Ethereum": "ETH",
    "Solana": "SOL",
    "Sui": "SUI",
    "Binance Smart Chain": "BNB",
    "Berachain": "BERA",
    "Polygon": "MATIC",
    "TON": "TON",
    "Aptos": "APT",
    "Filecoin": "FIL",
    # EVM L2s settle gas in ETH.
    "Arbitrum": "ETH",
    "BASE": "ETH",
    "zkSync ERA": "ETH",
    "Mantle": "ETH",
    "Starknet": "ETH",
}

# --- Chain registry: EVM/Etherscan-V2 chain facts --------------------------
# The three maps below cover EXACTLY the 8 EVM chains supported by the
# Etherscan V2 on-chain fetcher (NOT the 14-entry Koinly fee-check map above).
# They are the trusted registry the chains.json loader derives `chainid`,
# `native_ticker`, and the date window from (plan
# `2026-08-01-minimal-chains-json-config`, DI-2 restated). The module-load
# assert below enforces an identical key set across all three so a chain added
# to one map but not another fails loudly.

# Etherscan V2 chain ids. Source: Etherscan V2 supported-chains doc
# (https://docs.etherscan.io/supported-chains).
_CHAIN_TO_CHAINID: Final[dict[str, int]] = {
    "Ethereum": 1,
    "Binance Smart Chain": 56,
    "Berachain": 80094,
    "Polygon": 137,
    "Arbitrum": 42161,
    "BASE": 8453,
    "Mantle": 5000,
    "zkSync ERA": 324,
}

# CSV-output-correct native tickers for the on-chain fetcher. This is a
# SEPARATE contract from `_CHAIN_NATIVE_FEE_ASSET` (the 14-entry Koinly
# fee-check map, which is stale for CSV output and left untouched). Polygon is
# "POL": the MATIC->POL native-asset migration completed 2024-09-04 per the
# official polygon.technology announcement; POL is the native asset for
# FY2025+ CSV output. See
# docs/maintenance/tax/crypto-origin/official/polygon_pol_migration_2024-09-04.md.
_CHAIN_ON_CHAIN_NATIVE_TICKER: Final[dict[str, str]] = {
    "Ethereum": "ETH",  # genesis: ethereum_genesis_2015-07-30.md
    "Binance Smart Chain": "BNB",  # genesis: bnb_chain_genesis_2020-09-01.md
    "Berachain": "BERA",  # genesis: berachain_genesis_2025-02-06.md
    # POL since the 2024-09-04 migration (NOT MATIC).
    "Polygon": "POL",  # genesis: polygon_genesis_2020-05-28.md; ticker: polygon_pol_migration_2024-09-04.md
    "Arbitrum": "ETH",  # genesis: arbitrum_genesis_2021-08-31.md
    "BASE": "ETH",  # genesis: base_genesis_2023-08-09.md
    "Mantle": "MNT",  # genesis: mantle_genesis_2023-07-17.md
    "zkSync ERA": "ETH",  # genesis: zksync_era_genesis_2023-03-24.md
}

# Mainnet genesis/first-block dates (NOT legal-entity service dates).
# Berachain is 2025-02-06 (genesis), not 2025-02-05 (BERA Chain Foundation
# legal-entity service date - a different semantic; see berachain_genesis_2025-02-06.md).
_CHAIN_LAUNCH_DATE: Final[dict[str, date]] = {
    "Ethereum": date(2015, 7, 30),  # ethereum_genesis_2015-07-30.md
    "Binance Smart Chain": date(2020, 9, 1),  # bnb_chain_genesis_2020-09-01.md
    "Berachain": date(2025, 2, 6),  # berachain_genesis_2025-02-06.md
    "Polygon": date(2020, 5, 28),  # polygon_genesis_2020-05-28.md
    "Arbitrum": date(2021, 8, 31),  # arbitrum_genesis_2021-08-31.md
    "BASE": date(2023, 8, 9),  # base_genesis_2023-08-09.md
    "Mantle": date(2023, 7, 17),  # mantle_genesis_2023-07-17.md
    "zkSync ERA": date(2023, 3, 24),  # zksync_era_genesis_2023-03-24.md
}

# Registry coherence: the three EVM fact maps must share an identical key set.
# Catches drift when a chain is added to one map but not another
# (intentional module-load invariant, not a test assertion).
assert (  # noqa: S101 - intentional module-load invariant, not a test assertion
    set(_CHAIN_TO_CHAINID)
    == set(_CHAIN_ON_CHAIN_NATIVE_TICKER)
    == set(_CHAIN_LAUNCH_DATE)
), (
    "Chain registry maps must share an identical EVM key set; drift detected "
    f"(chainid={sorted(_CHAIN_TO_CHAINID)} "
    f"ticker={sorted(_CHAIN_ON_CHAIN_NATIVE_TICKER)} "
    f"launch={sorted(_CHAIN_LAUNCH_DATE)})"
)


def chainid_for(chain: str) -> int | None:
    """Return the Etherscan V2 chain id for ``chain``, or ``None`` if not a supported EVM chain.

    Returns ``None`` for non-EVM chains (Solana, Sui, TON, ...) and for the
    ``"Unknown"`` sentinel (fail-closed against `_CHAIN_TO_CHAINID`'s key set).
    """
    return _CHAIN_TO_CHAINID.get(chain)


def native_ticker_for(chain: str) -> str | None:
    """Return the CSV-output-correct native ticker for ``chain``, or ``None`` if not a supported EVM chain.

    This reads the on-chain ticker map (`_CHAIN_ON_CHAIN_NATIVE_TICKER`), NOT
    the Koinly fee-check map (`_CHAIN_NATIVE_FEE_ASSET`); the two are separate
    contracts (Polygon is ``"POL"`` here, ``"MATIC"`` there). Returns ``None``
    for non-EVM chains and ``"Unknown"``.
    """
    return _CHAIN_ON_CHAIN_NATIVE_TICKER.get(chain)


def chain_launch_date(chain: str) -> date | None:
    """Return the mainnet genesis/launch date for ``chain``, or ``None`` if not a supported EVM chain.

    The date is genesis/first-block, NOT a legal-entity service date (e.g.
    Berachain is 2025-02-06 genesis, not 2025-02-05 service date). Returns
    ``None`` for non-EVM chains and ``"Unknown"``.
    """
    return _CHAIN_LAUNCH_DATE.get(chain)


def is_native_gas_fee(wallet: str, fee_currency: str) -> bool:
    """Return True if ``fee_currency`` is the native gas token of the chain derived from ``wallet``.

    Returns False when the chain is absent from the map or is "Unknown"
    (``.get`` returns ``None``, and the comparison is False), so unknown/CEX
    wallets fail safe and the caller warns. The comparison is case-insensitive
    on the fee ticker so a non-uppercase export variant still matches the
    uppercase map values.
    """
    return fee_currency.upper() == _CHAIN_NATIVE_FEE_ASSET.get(_derive_chain(wallet))


def _derive_chain(wallet: str) -> str:  # noqa: PLR0911, PLR0912
    """Derive the blockchain/chain identifier from a wallet label.

    Uses deterministic normalization rules to extract chain names from wallet labels.
    The wallet/platform name is only a discovery hint; final mappings come from
    trusted sources in docs/maintenance/tax/crypto-origin/operator_chain_origin_registry.md.

    Normalization rules:
    - Strip platform aliases like "Ledger " prefix
    - Strip asset tickers in parentheses (e.g., "(ETH)", "(SOL)")
    - Strip address suffixes after " - " (e.g., " - 0x6ABd...")
    - Trim whitespace (and map empty input to "Unknown") via normalize_platform_name

    Args:
        wallet: The raw wallet name from Koinly (e.g., "Ledger Berachain (BERA)",
               "Ethereum (ETH) - 0x6ABd...", "Binance (2)").

    Returns:
        The normalized chain name if matched against known chains,
        or "Unknown" if the wallet label does not allow reasonable derivation.
    """
    if not wallet or not wallet.strip():
        return "Unknown"

    normalized = wallet.strip()

    # Trim whitespace and map empty input to "Unknown" (no platform-specific normalization).
    normalized = normalize_platform_name(normalized)

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
    for known_chain in _KNOWN_CHAINS_BY_LENGTH:
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
