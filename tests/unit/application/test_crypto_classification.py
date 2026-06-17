"""Unit tests for crypto classification logic extracted from crypto_reporting.py.

These tests follow the TDD RED → GREEN → refactor cycle.
Tests are written first to verify the expected behavior after extraction.
"""

from __future__ import annotations

from decimal import Decimal


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


class TestDerivativesClassifier:
    """Tests for classify_derivatives_event (Task 5 of derivatives separation plan).

    The classifier takes a single ParsedOgrRow and the list of CG entries that
    share the same (date, asset, wallet) key, and returns a sealed
    DerivativesClassification with variants Derivatives, Spot, or Ambiguous.

    Two design corrections from the plan pseudocode are encoded in these tests:
    - Correction 1: comparison is against CG ``proceeds_eur`` (the disposal
      value), NOT ``gain_loss_eur`` (the realized gain). OGR ``Value (EUR)`` is
      disposal proceeds; CG gain is a different quantity. Verified against the
      Case 1 fixture: OGR row 9 Value=4.17 matches CG line 19 proceeds_eur=4.17
      (gain_loss_eur there is 2.44, which would not match).
    - Correction 2: the Ambiguous branch splits into two distinct reason
      suffixes — "manual review needed" for single-CG mismatch, and
      "aggregate-match check required" for multi-CG mismatch.
    """

    def _make_capital_entry(  # noqa: PLR0913
        self,
        *,
        disposal_date: str = "2025-01-12",
        asset: str = "USDT",
        wallet: str = "ByBit",
        proceeds_eur: str = "4.17",
        cost_eur: str = "1.72",
        gain_loss_eur: str = "2.44",
    ):
        """Construct a CryptoCapitalGainEntry fixture with defaults from Case 1."""
        from tax_reporting.application.crypto.entities import (
            CryptoCapitalGainEntry,
            OperatorOrigin,
        )

        origin = OperatorOrigin(
            platform=wallet,
            service_scope="crypto",
            operator_entity="Test Entity",
            operator_country="US",
            source_url="https://example.com",
            source_checked_on="2026-01-01",
            confidence="high",
            review_required=False,
        )
        return CryptoCapitalGainEntry(
            disposal_date=disposal_date,
            acquisition_date="2024-12-16",
            asset=asset,
            amount=Decimal("4.27"),
            cost_eur=Decimal(cost_eur),
            proceeds_eur=Decimal(proceeds_eur),
            gain_loss_eur=Decimal(gain_loss_eur),
            holding_period="Short term",
            wallet=wallet,
            platform=wallet,
            chain="unknown",
            operator_origin=origin,
            annex_hint="",
            review_required=False,
            notes="",
        )

    def _make_ogr_row(
        self,
        *,
        date: str = "2025-01-12",
        asset: str = "USDT",
        gain_loss: str = "-4.17",
        row_type: str = "Loss",
        wallet: str = "ByBit",
    ):
        """Construct a ParsedOgrRow fixture."""
        from tax_reporting.application.crypto.entities import ParsedOgrRow

        return ParsedOgrRow(
            date=date,
            asset=asset,
            gain_loss=Decimal(gain_loss),
            row_type=row_type,
            wallet=wallet,
        )

    def test_ogr_profit_no_cg_counterpart(self):
        """Given an OGR Profit row, expects Derivatives variant.

        Profit rows never have CG counterparts in Koinly's model (realized
        derivatives P&L has no FIFO cost-basis trail), so a Profit row is
        unconditionally derivatives. Mirrors Case 1 OGR row 8 (140.18 EUR
        ByBit USDT Profit).
        """
        from tax_reporting.application.crypto.classification import classify_derivatives_event
        from tax_reporting.application.crypto.entities import DerivativesClassification

        ogr_row = self._make_ogr_row(
            gain_loss="140.18",
            row_type="Profit",
        )
        cg_matches: list = []

        result = classify_derivatives_event(ogr_row, cg_matches)

        assert isinstance(result, DerivativesClassification)
        assert result.kind == "derivatives"
        assert result.reason == "OGR Profit — derivatives P&L realization"

    def test_ogr_loss_exact_cg_match(self):
        """Given an OGR Loss row with one CG whose proceeds match, expects Spot.

        Mirrors Case 1 OGR row 9 (Value=-4.17, Loss) against CG line 19
        (proceeds_eur=4.17). The match is on ``proceeds_eur`` (disposal
        value), not ``gain_loss_eur`` (realized gain = 2.44). Comparing
        |4.17| against gain_loss_eur=2.44 would give 1.73 > tolerance and
        wrongly classify as Ambiguous, breaking the plan's Example.
        """
        from tax_reporting.application.crypto.classification import classify_derivatives_event
        from tax_reporting.application.crypto.entities import DerivativesClassification

        ogr_row = self._make_ogr_row(gain_loss="-4.17", row_type="Loss")
        cg_matches = [self._make_capital_entry(proceeds_eur="4.17", gain_loss_eur="2.44")]

        result = classify_derivatives_event(ogr_row, cg_matches)

        assert isinstance(result, DerivativesClassification)
        assert result.kind == "spot"
        assert result.reason == "OGR Loss matches CG disposal — spot fee"

    def test_ogr_loss_no_cg_counterpart(self):
        """Given an OGR Loss row with no CG counterpart, expects Derivatives.

        A Loss row with no matching CG entry has no FIFO cost-basis trail,
        so it is a derivatives realization (no spot disposal to anchor it).
        """
        from tax_reporting.application.crypto.classification import classify_derivatives_event
        from tax_reporting.application.crypto.entities import DerivativesClassification

        ogr_row = self._make_ogr_row(gain_loss="-100.00", row_type="Loss")
        cg_matches: list = []

        result = classify_derivatives_event(ogr_row, cg_matches)

        assert isinstance(result, DerivativesClassification)
        assert result.kind == "derivatives"
        assert result.reason == "OGR Loss with no CG counterpart — derivatives realization"

    def test_ogr_loss_value_mismatch_ambiguous(self):
        """Given an OGR Loss row with one CG whose proceeds differ, expects Ambiguous.

        The CG ``proceeds_eur`` differs from |OGR gain_loss| by more than the
        0.01 tolerance. Reason cites the mismatch with single-CG suffix
        "manual review needed".
        """
        from tax_reporting.application.crypto.classification import classify_derivatives_event
        from tax_reporting.application.crypto.entities import DerivativesClassification

        ogr_row = self._make_ogr_row(
            gain_loss="-8.31",
            row_type="Loss",
            date="2025-01-13",
        )
        # proceeds_eur=5.00, |OGR|=8.31 → diff 3.31 > 0.01 tolerance
        cg_matches = [self._make_capital_entry(proceeds_eur="5.00", disposal_date="2025-01-13")]

        result = classify_derivatives_event(ogr_row, cg_matches)

        assert isinstance(result, DerivativesClassification)
        assert result.kind == "ambiguous"
        assert result.reason == (
            "OGR=-8.31 vs CG=5.00 on (2025-01-13, USDT, ByBit) — manual review needed"
        )

    def test_ogr_loss_multiple_cg_entries_ambiguous(self):
        """Given an OGR Loss row with many CG entries whose aggregate differs, expects Ambiguous.

        Mirrors Case 2 shape: 109 CG lots on the same (date, asset, wallet)
        key with small individual gains. The aggregate proceeds does not
        match |OGR|, so the row is ambiguous. Reason uses the multi-CG
        suffix "aggregate-match check required".
        """
        from tax_reporting.application.crypto.classification import classify_derivatives_event
        from tax_reporting.application.crypto.entities import DerivativesClassification

        ogr_row = self._make_ogr_row(
            gain_loss="-138.73",
            row_type="Loss",
            date="2025-01-13",
        )
        # Build 109 CG lots whose proceeds sum to something far from 138.73.
        cg_matches = [
            self._make_capital_entry(
                proceeds_eur="0.10",
                disposal_date="2025-01-13",
            )
            for _ in range(109)
        ]

        result = classify_derivatives_event(ogr_row, cg_matches)

        assert isinstance(result, DerivativesClassification)
        assert result.kind == "ambiguous"
        assert result.reason == (
            "OGR=-138.73 vs 109 CG lots on (2025-01-13, USDT, ByBit) — aggregate-match check required"
        )

    def test_ogr_loss_multiple_cg_entries_aggregate_match(self):
        """Given an OGR Loss row with many CG entries whose aggregate matches, expects Spot.

        Multiple CG lots whose summed ``proceeds_eur`` matches |OGR gain_loss|
        within tolerance are collectively a spot fee disposal split across
        lots. Reason names the lot count.
        """
        from tax_reporting.application.crypto.classification import classify_derivatives_event
        from tax_reporting.application.crypto.entities import DerivativesClassification

        # OGR magnitude 12.00, split across 3 CG lots summing to 12.00.
        ogr_row = self._make_ogr_row(gain_loss="-12.00", row_type="Loss")
        cg_matches = [
            self._make_capital_entry(proceeds_eur="4.00"),
            self._make_capital_entry(proceeds_eur="5.00"),
            self._make_capital_entry(proceeds_eur="3.00"),
        ]

        result = classify_derivatives_event(ogr_row, cg_matches)

        assert isinstance(result, DerivativesClassification)
        assert result.kind == "spot"
        assert result.reason == "OGR Loss aggregate-matches 3 CG lots — spot fee disposals"
