"""Chain derivation from wallet labels.

Uses deterministic normalization rules to extract chain names from wallet labels.
The wallet/platform name is only a discovery hint; final mappings come from
trusted sources in docs/maintenance/tax/crypto-origin/operator_chain_origin_registry.md.
"""

from __future__ import annotations

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
