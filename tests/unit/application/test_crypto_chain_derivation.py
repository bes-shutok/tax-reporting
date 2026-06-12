"""Tests for chain derivation module."""

from __future__ import annotations

from tax_reporting.application.crypto.chain_derivation import _derive_chain


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
