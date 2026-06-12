"""Unit tests for crypto classification logic extracted from crypto_reporting.py.

These tests follow the TDD RED → GREEN → refactor cycle.
Tests are written first to verify the expected behavior after extraction.
"""

from __future__ import annotations

from functools import lru_cache

import pytest


class TestClassifyRewardTaxStatus:
    """Tests for _classify_reward_tax_status function."""

    def test_classify_reward_taxable_now(self):
        """Given staking reward (non-crypto form), expects TAXABLE_NOW.

        Staking rewards paid in fiat currency (e.g., EUR, USD) are immediately
        taxable as Category E income because the remuneration does not assume
        the form of cryptoassets.
        """
        from tax_reporting.application.crypto.classification import _classify_reward_tax_status
        from tax_reporting.application.crypto.entities import RewardTaxClassification

        result = _classify_reward_tax_status("EUR")
        assert result == RewardTaxClassification.TAXABLE_NOW

    def test_classify_reward_deferred(self):
        """Given airdrop (crypto form), expects DEFERRED_BY_LAW.

        Airdrops received as cryptoassets have taxation deferred until disposal
        under CIRS art. 5(11) for non-securities and deferral rules for crypto-to-crypto swaps.
        """
        from tax_reporting.application.crypto.classification import _classify_reward_tax_status
        from tax_reporting.application.crypto.entities import RewardTaxClassification

        result = _classify_reward_tax_status("BTC")
        assert result == RewardTaxClassification.DEFERRED_BY_LAW

    def test_fiat_collision_detection(self):
        """Given GEL token, expects classified as crypto (not fiat).

        GEL is both a crypto token (Gelato Network) and a fiat currency (Georgian Lari).
        Known collisions are checked first to ensure correct tax treatment per CRG-001.
        """
        from tax_reporting.application.crypto.classification import _classify_reward_tax_status
        from tax_reporting.application.crypto.entities import RewardTaxClassification

        # GEL should be classified as deferred (crypto), not taxable (fiat)
        result = _classify_reward_tax_status("GEL")
        assert result == RewardTaxClassification.DEFERRED_BY_LAW


class TestFiatCurrencyCodes:
    """Tests for _get_all_fiat_currency_codes function."""

    def test_lru_cache_preserved(self):
        """Given two calls to _get_all_fiat_currency_codes, expects second call returns cached result.

        The LRU cache decorator ensures the expensive pycountry lookup is performed
        only once, with subsequent calls returning the cached frozenset.
        """
        from tax_reporting.application.crypto.classification import _get_all_fiat_currency_codes

        # First call - should populate cache
        first_result = _get_all_fiat_currency_codes()

        # Verify it's a frozenset
        assert isinstance(first_result, frozenset)

        # Second call - should return cached result (same object)
        second_result = _get_all_fiat_currency_codes()

        # Same object reference indicates cache hit
        assert first_result is second_result

    def test_fiat_currency_codes_content(self):
        """Given call to _get_all_fiat_currency_codes, expects contains common fiat codes.

        Verify that the result includes expected fiat currency codes like EUR, USD, GBP.
        """
        from tax_reporting.application.crypto.classification import _get_all_fiat_currency_codes

        codes = _get_all_fiat_currency_codes()

        # Should contain common fiat currencies
        assert "EUR" in codes
        assert "USD" in codes
        assert "GBP" in codes

        # Should NOT contain commodities (XAG, XAU) or special codes (XXX, XTS)
        assert "XAG" not in codes
        assert "XAU" not in codes
        assert "XXX" not in codes
        assert "XTS" not in codes


class TestIncomeCodeResolution:
    """Tests for _resolve_income_code function."""

    def test_resolve_staking_income_code(self):
        """Given staking type, expects 401 income code."""
        from tax_reporting.application.crypto.classification import _resolve_income_code

        result = _resolve_income_code("staking")
        assert result == "401"

    def test_resolve_airdrop_income_code(self):
        """Given airdrop type, expects 401 income code."""
        from tax_reporting.application.crypto.classification import _resolve_income_code

        result = _resolve_income_code("airdrop")
        assert result == "401"

    def test_resolve_interest_income_code(self):
        """Given interest type, expects 402 income code."""
        from tax_reporting.application.crypto.classification import _resolve_income_code

        result = _resolve_income_code("interest")
        assert result == "402"

    def test_resolve_unknown_income_code(self):
        """Given unknown type, expects default 401 income code."""
        from tax_reporting.application.crypto.classification import _resolve_income_code

        result = _resolve_income_code("unknown_type")
        assert result == "401"


class TestTabelaXValidation:
    """Tests for _is_valid_tabela_x_country function."""

    def test_valid_tabela_x_country(self):
        """Given valid Tabela X country code, expects True."""
        from tax_reporting.application.crypto.classification import _is_valid_tabela_x_country

        assert _is_valid_tabela_x_country("US") is True
        assert _is_valid_tabela_x_country("IE") is True
        assert _is_valid_tabela_x_country("MT") is True

    def test_invalid_tabela_x_country(self):
        """Given invalid Tabela X country code, expects False."""
        from tax_reporting.application.crypto.classification import _is_valid_tabela_x_country

        assert _is_valid_tabela_x_country("XX") is False
        assert _is_valid_tabela_x_country("ZZ") is False


class TestPopularCryptoTokens:
    """Tests for popular crypto token functions."""

    def test_popular_tokens_cached(self):
        """Given two calls to _get_popular_crypto_tokens, expects second call returns cached result.

        The LRU cache decorator ensures the file load is performed only once.
        """
        from tax_reporting.application.crypto.classification import _get_popular_crypto_tokens

        # First call
        first_result = _get_popular_crypto_tokens()

        # Second call - should return cached result (same object)
        second_result = _get_popular_crypto_tokens()

        # Same object reference indicates cache hit
        assert first_result is second_result

    def test_contains_popular_token(self):
        """Given asset containing popular token, expects True.

        Substring matching catches Koinly-specific naming variants like TSTON (contains TON).
        """
        from tax_reporting.application.crypto.classification import _contains_popular_token, _get_popular_crypto_tokens

        popular_tokens = _get_popular_crypto_tokens()

        # If we have popular tokens loaded, test substring matching
        if popular_tokens:
            # Test with a token that should exist
            first_token = list(popular_tokens)[0]
            assert _contains_popular_token(f"TS{first_token}") is True
        else:
            # Empty popular tokens - should return False
            assert _contains_popular_token("BTC") is False
