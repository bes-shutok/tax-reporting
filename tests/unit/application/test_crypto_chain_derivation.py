"""Tests for chain derivation module."""

from __future__ import annotations

from tax_reporting.application.crypto.chain_derivation import (
    _CHAIN_NATIVE_FEE_ASSET,
    _KNOWN_CHAINS,
    _derive_chain,
    is_native_gas_fee,
)


def test_derive_chain_ethereum() -> None:
    """Given wallet ending with '.eth', expects 'Ethereum'."""
    result = _derive_chain("Ethereum (ETH)")
    assert result == "Ethereum"


def test_derive_chain_unknown() -> None:
    """Given wallet with no recognizable pattern, expects 'Unknown'."""
    result = _derive_chain("SomeRandomWalletName")
    assert result == "Unknown"


def test_derive_chain_solana() -> None:
    """Given wallet ending with '.sol', expects 'Solana'."""
    result = _derive_chain("Solana (SOL)")
    assert result == "Solana"


def test_derive_chain_empty_string() -> None:
    """Given empty string, expects 'Unknown'."""
    result = _derive_chain("")
    assert result == "Unknown"


def test_derive_chain_whitespace_only() -> None:
    """Given whitespace-only string, expects 'Unknown'."""
    result = _derive_chain("   ")
    assert result == "Unknown"


def test_derive_chain_ledger_prefix_unknown() -> None:
    """Given wallet with Ledger prefix but no recognizable chain, returns 'Unknown'."""
    result = _derive_chain("Ledger Nano X (SOL)")
    assert result == "Unknown"


def test_derive_chain_address_suffix_unknown() -> None:
    """Given wallet with address suffix but no separator, returns 'Unknown'."""
    result = _derive_chain("0x1234...abcd.eth")
    assert result == "Unknown"


def test_derive_chain_ticker_stripping_unknown() -> None:
    """Given wallet with ticker stripped but base name not in known chains, returns 'Unknown'."""
    result = _derive_chain("Metamask (ETH)")
    assert result == "Unknown"


def test_derive_chain_bnb_in_wallet_name() -> None:
    """Given wallet name containing 'bnb', derives 'Binance Smart Chain'."""
    result = _derive_chain("Binance Wallet (BTC)")
    assert result == "Binance"


def test_derive_chain_bsc_in_wallet_name() -> None:
    """Given wallet name containing 'bsc', derives 'Binance Smart Chain'."""
    result = _derive_chain("My BSC Wallet (USDT)")
    assert result == "Binance Smart Chain"


def test_derive_chain_gate_dotio() -> None:
    """Given wallet with gate.io, derives 'Gate.io'."""
    result = _derive_chain("gate.io Wallet")
    assert result == "Gate.io"


def test_derive_chain_case_insensitive() -> None:
    """Given wallet with mixed case, derives correct chain."""
    result = _derive_chain("ETHEREUM (ETH)")
    assert result == "Ethereum"


def test_derive_chain_bit_variants() -> None:
    """Given ByBit wallet variants, derives 'ByBit' (capitalization from known chains)."""
    assert _derive_chain("ByBit (2)") == "ByBit"
    assert _derive_chain("Bybit (2)") == "ByBit"
    assert _derive_chain("BYBIT (2)") == "ByBit"


def test_derive_chain_ledger_with_known_chain() -> None:
    """Given Ledger wallet with known chain after prefix, derives correctly."""
    assert _derive_chain("Ledger Ethereum") == "Ethereum"
    assert _derive_chain("Ledger Solana (SOL)") == "Solana"


def test_derive_chain_address_suffix_with_separator() -> None:
    """Given wallet with address suffix after ' - ', strips and derives chain."""
    assert _derive_chain("Ethereum (ETH) - 0x6ABd...1234") == "Ethereum"


def test_derive_chain_word_boundary_match() -> None:
    """Given wallet name containing known chain as a word, derives correctly."""
    assert _derive_chain("My Polygon Wallet") == "Polygon"


def test_derive_chain_ticker_only_match() -> None:
    """Given wallet that is just a ticker in parentheses, returns Unknown."""
    assert _derive_chain("(ETH)") == "Unknown"


def test_derive_chain_ticker_too_long() -> None:
    """Given ticker over 10 chars, does not strip it."""
    assert _derive_chain("VeryLongTicker (ABCDEFGHIJK)") == "Unknown"


def test_derive_chain_direct_match_special_cases() -> None:
    """Given special case patterns directly, matches correctly."""
    assert _derive_chain("bnb") == "Binance Smart Chain"
    assert _derive_chain("bsc") == "Binance Smart Chain"
    assert _derive_chain("gate") == "Gate.io"


class TestChainDerivation:
    """Tests for the chain -> native gas-fee-asset map and is_native_gas_fee helper."""

    def test_chain_native_fee_asset_map_complete(self) -> None:
        """On-chain chains have a native-fee entry; CEX names are absent; L2s map to ETH."""
        on_chain = {
            "Ethereum",
            "Solana",
            "Sui",
            "Binance Smart Chain",
            "Berachain",
            "Polygon",
            "TON",
            "Aptos",
            "Filecoin",
            "Arbitrum",
            "BASE",
            "zkSync ERA",
            "Mantle",
            "Starknet",
        }
        cex_names = {"ByBit", "Kraken", "Binance", "Gate.io", "Wirex", "Tonkeeper"}

        # Every on-chain chain has a native fee-asset entry.
        for chain in on_chain:
            assert chain in _CHAIN_NATIVE_FEE_ASSET, f"Missing native fee asset for chain: {chain}"

        # Every CEX name is intentionally absent.
        for chain in cex_names:
            assert chain not in _CHAIN_NATIVE_FEE_ASSET, f"CEX {chain} should be absent from the map"

        # EVM L2s map to ETH.
        for l2 in ("Arbitrum", "BASE", "zkSync ERA", "Mantle", "Starknet"):
            assert _CHAIN_NATIVE_FEE_ASSET[l2] == "ETH"

        # The map covers every on-chain chain in _KNOWN_CHAINS and no CEX.
        on_chain_known = _KNOWN_CHAINS - cex_names
        assert set(_CHAIN_NATIVE_FEE_ASSET) == on_chain_known

    def test_is_native_gas_fee_true_for_eth_on_ethereum(self) -> None:
        """Given wallet 'Ethereum (ETH)' and fee_currency 'ETH', expects True."""
        assert is_native_gas_fee("Ethereum (ETH)", "ETH") is True

    def test_is_native_gas_fee_false_for_eth_on_solana(self) -> None:
        """Given wallet 'Solana (SOL)' and fee_currency 'ETH', expects False (map is chain-keyed, not asset-keyed)."""
        assert is_native_gas_fee("Solana (SOL)", "ETH") is False

    def test_is_native_gas_fee_false_for_unknown_chain(self) -> None:
        """Given unknown wallet and any fee_currency, expects False (fail-safe)."""
        assert is_native_gas_fee("Some Unknown Wallet", "ETH") is False

    def test_is_native_gas_fee_false_for_bnb_on_binance_cex(self) -> None:
        """Given wallet 'Binance (2)' (CEX) and fee_currency 'BNB', expects False (CEX absent from map)."""
        assert is_native_gas_fee("Binance (2)", "BNB") is False

    def test_is_native_gas_fee_true_for_eth_on_zksync_era_bare(self) -> None:
        """Given bare chain name 'zkSync ERA' and fee 'ETH', expects True (word-boundary match + L2->ETH)."""
        assert is_native_gas_fee("zkSync ERA", "ETH") is True

    def test_is_native_gas_fee_case_insensitive_on_fee_ticker(self) -> None:
        """Given a lowercase fee ticker 'eth' on Ethereum, expects True.

        The map values are uppercase; the comparison normalizes the fee ticker so
        a non-uppercase export variant still matches (review-loop r1 Low:
        quality#edge-case-input-casing). Unknown chain still fails safe.
        """
        assert is_native_gas_fee("Ethereum (ETH)", "eth") is True
        assert is_native_gas_fee("Ethereum (ETH)", "Eth") is True
        # Unknown chain unaffected: lowercase non-native ticker still False.
        assert is_native_gas_fee("Some Unknown Wallet", "eth") is False
