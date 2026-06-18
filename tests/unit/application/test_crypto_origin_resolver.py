"""Edge-case tests for TokenOriginResolver.

Covers multiple matches per key, epoch-date sentinel, crypto-to-crypto
exchange derivation, bridge-transfer type handling, and confidence
downgrade on ambiguous or flagged rows.
"""

from __future__ import annotations

from tax_reporting.application.token_origin import TokenOriginResolver
from tax_reporting.domain.token_origin import (
    AcquisitionMethod,
    TokenOrigin,
)

_TH_HEADER = (
    "Transaction report 2025\n"
    "\n"
    "Date,Type,Tag,Sending Wallet,Sent Amount,Sent Currency,Sent Cost Basis,"
    "Receiving Wallet,Received Amount,Received Currency,Received Cost Basis,"
    "Fee Amount,Fee Currency,Gain (EUR),Net Value (EUR),Fee Value (EUR),"
    "TxSrc,TxDest,TxHash,Description"
)


def _write_th(tmp_path, data_rows: str):
    path = tmp_path / "th.csv"
    path.write_text(f"{_TH_HEADER}\n{data_rows}", encoding="utf-8")
    return path


class TestOriginResolverMultipleMatches:
    """When multiple transaction history rows share the same (date, asset, wallet) key."""

    def test_multiple_deposits_same_key_agree_on_method(self, tmp_path) -> None:
        path = _write_th(
            tmp_path,
            "2025-03-10 08:00:00 UTC,crypto_deposit,Reward,,,,,"
            "Kraken,5,SOL,50,,,,,,,,,\n"
            "2025-03-10 14:00:00 UTC,crypto_deposit,Reward,,,,,"
            "Kraken,3,SOL,30,,,,,,,,,\n",
        )
        resolver = TokenOriginResolver(path)
        origin = resolver.resolve("2025-03-10", "SOL", "Kraken")
        assert origin.acquisition_method == AcquisitionMethod.REWARD
        assert origin.confidence == "medium"

    def test_multiple_deposits_same_key_disagree_on_method_reduces_confidence(self, tmp_path) -> None:
        path = _write_th(
            tmp_path,
            "2025-03-10 08:00:00 UTC,crypto_deposit,Reward,,,,,"
            "Kraken,5,SOL,50,,,,,,,,,\n"
            "2025-03-10 14:00:00 UTC,crypto_deposit,Lending interest,,,,,"
            "Kraken,3,SOL,30,,,,,,,,,\n",
        )
        resolver = TokenOriginResolver(path)
        origin = resolver.resolve("2025-03-10", "SOL", "Kraken")
        assert origin.confidence == "low"
        assert origin.acquisition_method == AcquisitionMethod.UNKNOWN
        assert origin.acquired_from_asset == "Unknown"

    def test_multiple_exchanges_same_key_different_from_asset(self, tmp_path) -> None:
        path = _write_th(
            tmp_path,
            "2025-06-15 10:00:00 UTC,exchange,,Kraken,100,BTC,5000,"
            "Kraken,2,ETH,5000,,,,,,,,,\n"
            "2025-06-15 16:00:00 UTC,exchange,,Kraken,3000,USDT,3000,"
            "Kraken,2,ETH,3000,,,,,,,,,\n",
        )
        resolver = TokenOriginResolver(path)
        origin = resolver.resolve("2025-06-15", "ETH", "Kraken")
        assert origin.confidence == "low"
        assert origin.acquisition_method == AcquisitionMethod.UNKNOWN
        assert origin.acquired_from_asset == "Unknown"

    def test_multiple_exchanges_same_key_different_from_platform(self, tmp_path) -> None:
        path = _write_th(
            tmp_path,
            "2025-06-15 10:00:00 UTC,exchange,,Kraken,100,BTC,5000,"
            "Kraken,2,ETH,5000,,,,,,,,,\n"
            "2025-06-15 16:00:00 UTC,exchange,,Binance,100,BTC,5000,"
            "Kraken,2,ETH,5000,,,,,,,,,\n",
        )
        resolver = TokenOriginResolver(path)
        origin = resolver.resolve("2025-06-15", "ETH", "Kraken")
        assert origin.confidence == "low"
        assert origin.acquisition_method == AcquisitionMethod.UNKNOWN

    def test_hash_record_dominates_without_confidence_reduction(self, tmp_path) -> None:
        path = _write_th(
            tmp_path,
            "2025-01-15 08:00:00 UTC,crypto_deposit,Reward,,,,,"
            "Kraken,10,ETH,200,,,,,,,,,\n"
            "2025-01-15 10:30:00 UTC,exchange,,Kraken,100,BTC,5000,"
            "Kraken,10,ETH,5000,,,,,,abc,def,hash123,trade\n",
        )
        resolver = TokenOriginResolver(path)
        origin = resolver.resolve("2025-01-15", "ETH", "Kraken")
        assert origin.acquisition_method == AcquisitionMethod.SWAP_CONVERSION
        assert origin.confidence == "high"


class TestOriginResolverEpochDate:
    """Koinly uses 1970-01-01 as a sentinel for unknown acquisition dates."""

    def test_epoch_date_returns_unknown_even_with_matching_history(self, tmp_path) -> None:
        path = _write_th(
            tmp_path,
            "1970-01-01 00:00:00 UTC,exchange,,Kraken,100,BTC,5000,"
            "Kraken,2,ETH,5000,,,,,,abc,def,hash123,trade\n",
        )
        resolver = TokenOriginResolver(path)
        origin = resolver.resolve("1970-01-01", "ETH", "Kraken")
        assert origin.acquisition_method == AcquisitionMethod.UNKNOWN
        assert origin.confidence == "low"
        assert str(origin) == ""

    def test_any_1970_date_returns_unknown(self, tmp_path) -> None:
        path = _write_th(tmp_path, "")
        resolver = TokenOriginResolver(path)
        origin = resolver.resolve("1970-06-15", "BTC", "Kraken")
        assert origin.acquisition_method == AcquisitionMethod.UNKNOWN
        assert origin.confidence == "low"


class TestOriginResolverCryptoToCryptoExchange:
    """Exchange rows where both sent and received assets are crypto."""

    def test_btc_to_wbtc_swap_derives_swap_conversion(self, tmp_path) -> None:
        path = _write_th(
            tmp_path,
            "2025-02-10 12:00:00 UTC,exchange,,Ethereum,1,BTC,40000,"
            'Ethereum,1,WBTC,40000,,,,,,eth,eth,0xabc123,wrap\n',
        )
        resolver = TokenOriginResolver(path)
        origin = resolver.resolve("2025-02-10", "WBTC", "Ethereum")
        assert origin.acquisition_method == AcquisitionMethod.SWAP_CONVERSION
        assert origin.acquired_from_asset == "BTC"
        assert origin.acquired_from_platform == "Ethereum"
        assert origin.confidence == "high"

    def test_usdt_to_eth_swap(self, tmp_path) -> None:
        path = _write_th(
            tmp_path,
            "2025-05-20 09:30:00 UTC,exchange,,Kraken,3000,USDT,3000,"
            "Kraken,1,ETH,3000,,,,,,,,,\n",
        )
        resolver = TokenOriginResolver(path)
        origin = resolver.resolve("2025-05-20", "ETH", "Kraken")
        assert origin.acquisition_method == AcquisitionMethod.SWAP_CONVERSION
        assert origin.acquired_from_asset == "USDT"
        assert origin.confidence == "medium"


class TestOriginResolverBridgeTransfer:
    """Transfer type rows for cross-chain or cross-wallet movements."""

    def test_transfer_type_derives_bridge_transfer(self, tmp_path) -> None:
        path = _write_th(
            tmp_path,
            "2025-04-01 10:00:00 UTC,transfer,,Ethereum,0.5,ETH,1000,"
            "Polygon,0.5,ETH,1000,,,,,,eth,polygon,0xbridge456,bridge\n",
        )
        resolver = TokenOriginResolver(path)
        origin = resolver.resolve("2025-04-01", "ETH", "Polygon")
        assert origin.acquisition_method == AcquisitionMethod.BRIDGE_TRANSFER
        assert origin.acquired_from_asset == "ETH"
        assert origin.acquired_from_platform == "Ethereum"
        assert origin.confidence == "high"

    def test_transfer_without_hash_medium_confidence(self, tmp_path) -> None:
        path = _write_th(
            tmp_path,
            "2025-04-15 11:00:00 UTC,transfer,,Kraken,100,MATIC,50,"
            "Binance,100,MATIC,50,,,,,,,,,\n",
        )
        resolver = TokenOriginResolver(path)
        origin = resolver.resolve("2025-04-15", "MATIC", "Binance")
        assert origin.acquisition_method == AcquisitionMethod.BRIDGE_TRANSFER
        assert origin.acquired_from_asset == "MATIC"
        assert origin.acquired_from_platform == "Kraken"
        assert origin.confidence == "medium"

    def test_transfer_from_asset_defaults_to_received_when_sent_empty(self, tmp_path) -> None:
        path = _write_th(
            tmp_path,
            "2025-07-20 15:00:00 UTC,transfer,,,,,,"
            "Arbitrum,10,ARB,20,,,,,,,,,\n",
        )
        resolver = TokenOriginResolver(path)
        origin = resolver.resolve("2025-07-20", "ARB", "Arbitrum")
        assert origin.acquisition_method == AcquisitionMethod.BRIDGE_TRANSFER
        assert origin.acquired_from_asset == "ARB"

    def test_transfer_from_platform_defaults_to_receiving_wallet_when_sending_empty(self, tmp_path) -> None:
        path = _write_th(
            tmp_path,
            "2025-08-01 09:00:00 UTC,transfer,,,,,,"
            "Optimism,5,OP,10,,,,,,,,,\n",
        )
        resolver = TokenOriginResolver(path)
        origin = resolver.resolve("2025-08-01", "OP", "Optimism")
        assert origin.acquired_from_platform == "Optimism"


class TestOriginResolverTransferPoolTags:
    """Transfer rows with pool-related tags."""

    def test_transfer_to_pool_skipped(self, tmp_path) -> None:
        """Transfer rows with 'To pool' tag (internal shuffle) should be skipped."""
        path = _write_th(
            tmp_path,
            # Exchange row that provides the LP origin
            "2025-02-23 18:47:14 UTC,exchange,Liquidity in,Ledger APTOS,19.95,APT,112.72,"
            "Ledger APTOS,0.79,CAKE-LP,112.72,,,,,,hash1,,,add liquidity\n"
            # Later transfer to pool (same asset, same wallet, tag contains "pool")
            "2025-02-23 18:47:49 UTC,transfer,To pool,Ledger APTOS,1.58,CAKE-LP,225.71,"
            "Ledger APTOS,1.58,CAKE-LP,225.71,,,,,,,hash2,,,pool transfer\n",
        )
        resolver = TokenOriginResolver(path)
        origin = resolver.resolve("2025-02-23", "CAKE-LP", "Ledger APTOS")
        # "To pool" transfer should be skipped, LP origin resolves correctly
        assert origin.acquisition_method == AcquisitionMethod.LIQUIDITY_PROVISION
        assert origin.acquired_from_asset == "APT"
        assert origin.acquired_from_platform == "Ledger APTOS"
        assert origin.confidence == "high"

    def test_transfer_redeem_from_pool_not_skipped(self, tmp_path) -> None:
        """Transfer rows with 'redeem' tag (liquidity return) should NOT be skipped.

        This test verifies the fix for the provenance regression where same-wallet/
        same-asset transfers were blanket-skipped. Legitimate liquidity returns like
        'redeem' from Gate.io must be indexed as transfer-origin candidates.
        """
        path = _write_th(
            tmp_path,
            # Transfer row with tag "redeem" (liquidity return, same asset/wallet)
            "2025-01-23 14:26:36 UTC,transfer,Redeem,Gate.io,0.5,BTC,1000,"
            "Gate.io,0.5,BTC,1000,,,,,,gate,,101623091496,redeem\n",
        )
        resolver = TokenOriginResolver(path)
        origin = resolver.resolve("2025-01-23", "BTC", "Gate.io")
        # "redeem" transfer should NOT be skipped - it's a legitimate liquidity return
        assert origin.acquisition_method == AcquisitionMethod.BRIDGE_TRANSFER
        assert origin.acquired_from_asset == "BTC"
        assert origin.acquired_from_platform == "Gate.io"
        assert origin.confidence == "high"

    def test_transfer_same_wallet_same_asset_indexed(self, tmp_path) -> None:
        """Transfer rows with same wallet/asset but no pool tag should be indexed.

        Same-wallet/same-asset transfers are only skipped when the tag explicitly
        indicates an internal pool shuffle (contains "pool").
        """
        path = _write_th(
            tmp_path,
            # Transfer row with same asset/wallet but no "pool" tag
            "2025-03-15 10:00:00 UTC,transfer,,Kraken,100,USDT,500,"
            "Kraken,100,USDT,500,,,,,,kraken,,0x888,address reuse\n",
        )
        resolver = TokenOriginResolver(path)
        origin = resolver.resolve("2025-03-15", "USDT", "Kraken")
        # Same-wallet/same-asset transfer WITHOUT "pool" tag should be indexed
        assert origin.acquisition_method == AcquisitionMethod.BRIDGE_TRANSFER
        assert origin.acquired_from_asset == "USDT"
        assert origin.acquired_from_platform == "Kraken"
        assert origin.confidence == "high"


class TestOriginResolverMissingCostBasis:
    """Capital gains rows with 'Missing cost basis' in Notes get low confidence."""

    def test_missing_cost_basis_downgrades_high_to_low(self, tmp_path) -> None:
        path = _write_th(
            tmp_path,
            "2025-01-15 10:30:00 UTC,exchange,,Kraken,100,BTC,5000,"
            "Kraken,2.5,ETH,5000,,,,,,,,abc,def,hash123,trade\n",
        )
        resolver = TokenOriginResolver(path)
        origin = resolver.resolve("2025-01-15", "ETH", "Kraken", notes="Missing cost basis")
        assert origin.acquisition_method == AcquisitionMethod.SWAP_CONVERSION
        assert origin.confidence == "low"

    def test_missing_cost_basis_case_insensitive(self, tmp_path) -> None:
        path = _write_th(
            tmp_path,
            "2025-01-15 10:30:00 UTC,exchange,,Kraken,100,BTC,5000,"
            "Kraken,2.5,ETH,5000,,,,,,,,abc,def,hash123,trade\n",
        )
        resolver = TokenOriginResolver(path)
        origin = resolver.resolve("2025-01-15", "ETH", "Kraken", notes="missing cost basis")
        assert origin.confidence == "low"

    def test_missing_cost_basis_within_longer_notes(self, tmp_path) -> None:
        path = _write_th(
            tmp_path,
            "2025-01-15 10:30:00 UTC,exchange,,Kraken,100,BTC,5000,"
            "Kraken,2.5,ETH,5000,,,,,,,,abc,def,hash123,trade\n",
        )
        resolver = TokenOriginResolver(path)
        origin = resolver.resolve(
            "2025-01-15", "ETH", "Kraken",
            notes="Auto-imported: Missing cost basis applied",
        )
        assert origin.confidence == "low"


class TestOriginResolverBuyType:
    """Buy-type transaction history rows (fiat-to-crypto market purchases)."""

    def test_buy_type_resolves_as_direct_purchase(self, tmp_path) -> None:
        path = _write_th(
            tmp_path,
            "2025-07-24 09:48:39 UTC,buy,,Wirex,55.00,EUR,,"
            'Wirex,"54.59057000",EUROC,"55.00",,,,,,,,,\n',
        )
        resolver = TokenOriginResolver(path)
        origin = resolver.resolve("2025-07-24", "EUROC", "Wirex")
        assert origin.acquisition_method == AcquisitionMethod.DIRECT_PURCHASE
        assert origin.acquired_from_asset == "EUR"
        assert origin.acquired_from_platform == "Wirex"
        assert origin.confidence == "medium"

    def test_buy_without_sending_wallet_defaults_to_receiving_wallet(self, tmp_path) -> None:
        path = _write_th(
            tmp_path,
            "2025-07-24 09:48:39 UTC,buy,,,55.00,EUR,,"
            'Wirex,"54.59057000",EUROC,"55.00",,,,,,,,,\n',
        )
        resolver = TokenOriginResolver(path)
        origin = resolver.resolve("2025-07-24", "EUROC", "Wirex")
        assert origin.acquisition_method == AcquisitionMethod.DIRECT_PURCHASE
        assert origin.acquired_from_platform == "Wirex"

    def test_buy_without_sent_currency_returns_unknown(self, tmp_path) -> None:
        path = _write_th(
            tmp_path,
            "2025-07-24 09:48:39 UTC,buy,,,,,,"
            'Wirex,"54.59057000",EUROC,"55.00",,,,,,,,,\n',
        )
        resolver = TokenOriginResolver(path)
        origin = resolver.resolve("2025-07-24", "EUROC", "Wirex")
        assert origin.acquisition_method == AcquisitionMethod.UNKNOWN
        assert origin.confidence == "low"


class TestOriginResolverGracefulDegradation:
    """No exceptions on edge cases; always returns a valid TokenOrigin."""

    def test_empty_transaction_history_returns_unknown(self, tmp_path) -> None:
        path = _write_th(tmp_path, "")
        resolver = TokenOriginResolver(path)
        origin = resolver.resolve("2025-01-15", "BTC", "Kraken")
        assert origin.acquisition_method == AcquisitionMethod.UNKNOWN
        assert origin.confidence == "low"

    def test_unrecognized_tx_type_skipped(self, tmp_path) -> None:
        path = _write_th(
            tmp_path,
            "2025-01-15 10:00:00 UTC,sell,,Kraken,1,BTC,50000,"
            "Kraken,50000,EUR,50000,,,,,,,,,\n",
        )
        resolver = TokenOriginResolver(path)
        origin = resolver.resolve("2025-01-15", "EUR", "Kraken")
        assert origin.acquisition_method == AcquisitionMethod.UNKNOWN

    def test_no_match_pre_koinly_date(self, tmp_path) -> None:
        path = _write_th(
            tmp_path,
            "2025-01-15 10:00:00 UTC,exchange,,Kraken,100,BTC,5000,"
            "Kraken,2.5,ETH,5000,,,,,,,,abc,def,hash123,trade\n",
        )
        resolver = TokenOriginResolver(path)
        origin = resolver.resolve("2020-06-01", "ETH", "Kraken")
        assert origin.acquisition_method == AcquisitionMethod.UNKNOWN
        assert origin.confidence == "low"

    def test_malformed_date_row_skipped(self, tmp_path) -> None:
        path = _write_th(
            tmp_path,
            "not-a-date,exchange,,Kraken,100,BTC,5000,"
            "Kraken,2.5,ETH,5000,,,,,,,,,\n",
        )
        resolver = TokenOriginResolver(path)
        origin = resolver.resolve("2025-01-15", "ETH", "Kraken")
        assert origin.acquisition_method == AcquisitionMethod.UNKNOWN

    def test_row_with_no_received_currency_skipped(self, tmp_path) -> None:
        path = _write_th(
            tmp_path,
            "2025-01-15 10:00:00 UTC,exchange,,Kraken,100,BTC,5000,"
            ",,,,,,,,,,\n",
        )
        resolver = TokenOriginResolver(path)
        origin = resolver.resolve("2025-01-15", "ETH", "Kraken")
        assert origin.acquisition_method == AcquisitionMethod.UNKNOWN

    def test_nonexistent_file_path_returns_unknown(self, tmp_path) -> None:
        resolver = TokenOriginResolver(tmp_path / "nonexistent.csv")
        origin = resolver.resolve("2025-01-15", "BTC", "Kraken")
        assert origin.acquisition_method == AcquisitionMethod.UNKNOWN
        assert origin.confidence == "low"

    def test_exchange_with_empty_sent_currency_skipped(self, tmp_path) -> None:
        path = _write_th(
            tmp_path,
            "2025-01-15 10:00:00 UTC,exchange,,,,"  # no sent amount/currency
            "Kraken,2.5,ETH,5000,,,,,,,,,\n",
        )
        resolver = TokenOriginResolver(path)
        origin = resolver.resolve("2025-01-15", "ETH", "Kraken")
        assert origin.acquisition_method == AcquisitionMethod.UNKNOWN

    def test_empty_date_field_skipped(self, tmp_path) -> None:
        path = _write_th(
            tmp_path,
            ",exchange,,Kraken,100,BTC,5000,"
            "Kraken,2.5,ETH,5000,,,,,,,,,\n",
        )
        resolver = TokenOriginResolver(path)
        origin = resolver.resolve("2025-01-15", "ETH", "Kraken")
        assert origin.acquisition_method == AcquisitionMethod.UNKNOWN

    def test_malformed_transaction_history_returns_empty_lookup(self, tmp_path) -> None:
        bad_path = tmp_path / "bad.csv"
        bad_path.write_text("NOT A VALID CSV\n\"\"\n\"\"\n", encoding="utf-8")
        resolver = TokenOriginResolver(bad_path)
        origin = resolver.resolve("2025-01-15", "ETH", "Kraken")
        assert origin.acquisition_method == AcquisitionMethod.UNKNOWN

    def test_asymmetric_bybit_alias_normalization(self, tmp_path) -> None:
        path = _write_th(
            tmp_path,
            "2025-01-01 00:15:00 UTC,crypto_deposit,Reward,,,,,"
            '"ByBit","0,25",USDT,"0,24",,,,,,,,,\n',
        )
        resolver = TokenOriginResolver(path)
        origin = resolver.resolve("2025-01-01", "USDT", "ByBit (2)")
        assert origin.acquisition_method == AcquisitionMethod.REWARD

    def test_empty_acquisition_date_returns_unknown(self, tmp_path) -> None:
        path = _write_th(
            tmp_path,
            "2025-01-15 10:00:00 UTC,exchange,,Kraken,100,BTC,5000,"
            "Kraken,2,ETH,5000,,,,,,,,,\n",
        )
        resolver = TokenOriginResolver(path)
        origin = resolver.resolve("", "ETH", "Kraken")
        assert origin.acquisition_method == AcquisitionMethod.UNKNOWN
        assert origin.confidence == "low"


class TestOriginResolverLiquidityOut:
    """Liquidity pool withdrawal scenarios: user removes liquidity and receives tokens."""

    def test_liquidity_out_deposit_with_paired_withdrawal(self, tmp_path) -> None:
        """crypto_deposit with tag 'Liquidity out' + crypto_withdrawal sharing same TxHash resolves to LP token name."""
        path = _write_th(
            tmp_path,
            # crypto_withdrawal row (LP tokens sent) - tag is 'Liquidity out' in real data
            # TxHash stored in TxSrc field (index 16) per real Koinly export format
            "2025-03-09 11:48:47 UTC,crypto_withdrawal,Liquidity out,Cetus,10,CETUS-LP,50,"
            ",,,,,,,,,0xfeedface,,,remove liquidity\n"
            # crypto_deposit row (tokens received from LP)
            "2025-03-09 11:48:47 UTC,crypto_deposit,Liquidity out,,,,,"
            "Cetus,100,SSUI,200,,,,,,0xfeedface,,,remove liquidity\n",
        )
        resolver = TokenOriginResolver(path)
        origin = resolver.resolve("2025-03-09", "SSUI", "Cetus")
        assert origin.acquisition_method == AcquisitionMethod.LIQUIDITY_WITHDRAWAL
        assert origin.acquired_from_asset == "CETUS-LP"
        assert origin.acquired_from_platform == "Cetus"
        assert origin.confidence == "high"

    def test_liquidity_out_deposit_without_matching_withdrawal(self, tmp_path) -> None:
        """No paired withdrawal → from_asset is 'LP position', method LIQUIDITY_WITHDRAWAL."""
        path = _write_th(
            tmp_path,
            # crypto_deposit row without paired crypto_withdrawal
            # TxHash stored in TxSrc field (index 16) per real Koinly export format
            "2025-03-09 11:48:47 UTC,crypto_deposit,Liquidity out,,,,,"
            "Cetus,100,SSUI,200,,,,,,0xfeedface,,,remove liquidity\n",
        )
        resolver = TokenOriginResolver(path)
        origin = resolver.resolve("2025-03-09", "SSUI", "Cetus")
        assert origin.acquisition_method == AcquisitionMethod.LIQUIDITY_WITHDRAWAL
        assert origin.acquired_from_asset == "LP position"
        assert origin.acquired_from_platform == "Cetus"
        assert origin.confidence == "medium"

    def test_liquidity_out_exchange_type(self, tmp_path) -> None:
        """exchange row with tag 'Liquidity out' (both sent/received populated).

        Method is LIQUIDITY_WITHDRAWAL, from_asset from Sent Currency.
        """
        path = _write_th(
            tmp_path,
            # TxHash stored in TxSrc field (index 16) per real Koinly export format
            "2025-03-09 11:48:47 UTC,exchange,Liquidity out,Cetus,5,CETUS-LP,25,"
            "Cetus,50,SSUI,100,,,,,,0xfeedface,,,remove liquidity\n",
        )
        resolver = TokenOriginResolver(path)
        origin = resolver.resolve("2025-03-09", "SSUI", "Cetus")
        assert origin.acquisition_method == AcquisitionMethod.LIQUIDITY_WITHDRAWAL
        assert origin.acquired_from_asset == "CETUS-LP"
        assert origin.acquired_from_platform == "Cetus"
        # Exchange LP operations retain tx_hash for high confidence
        assert origin.confidence == "high"


class TestOriginResolverLiquidityIn:
    """Liquidity pool provision scenarios: user provides tokens and receives LP tokens."""

    def test_liquidity_in_deposit_with_paired_withdrawals(self, tmp_path) -> None:
        """crypto_deposit receiving LP tokens + two crypto_withdrawal rows → from_asset is joined token names."""
        path = _write_th(
            tmp_path,
            # First withdrawal: SSUI sent - tag is 'Liquidity in' in real data
            # TxHash stored in TxSrc field (index 16) per real Koinly export format
            "2025-03-09 10:30:00 UTC,crypto_withdrawal,Liquidity in,Cetus,100,SSUI,200,"
            ",,,,,,,,,0xabc123,,,add liquidity\n"
            # Second withdrawal: USDC sent
            "2025-03-09 10:30:00 UTC,crypto_withdrawal,Liquidity in,Cetus,500,USDC,500,"
            ",,,,,,,,,0xabc123,,,add liquidity\n"
            # crypto_deposit row: LP tokens received
            "2025-03-09 10:30:00 UTC,crypto_deposit,Liquidity in,,,,,"
            "Cetus,5,CETUS-LP,25,,,,,,0xabc123,,,add liquidity\n",
        )
        resolver = TokenOriginResolver(path)
        origin = resolver.resolve("2025-03-09", "CETUS-LP", "Cetus")
        assert origin.acquisition_method == AcquisitionMethod.LIQUIDITY_PROVISION
        # Token names should be joined with "+"
        assert origin.acquired_from_asset == "SSUI+USDC"
        assert origin.acquired_from_platform == "Cetus"
        assert origin.confidence == "high"

    def test_liquidity_in_exchange_type(self, tmp_path) -> None:
        """exchange with tag 'Liquidity in' → method LIQUIDITY_PROVISION."""
        path = _write_th(
            tmp_path,
            # TxHash stored in TxSrc field (index 16) per real Koinly export format
            "2025-03-09 10:30:00 UTC,exchange,Liquidity in,Cetus,100,SSUI,200,"
            "Cetus,5,CETUS-LP,25,,,,,,0xabc123,,,add liquidity\n",
        )
        resolver = TokenOriginResolver(path)
        origin = resolver.resolve("2025-03-09", "CETUS-LP", "Cetus")
        assert origin.acquisition_method == AcquisitionMethod.LIQUIDITY_PROVISION
        assert origin.acquired_from_asset == "SSUI"
        assert origin.acquired_from_platform == "Cetus"
        # Exchange LP operations retain tx_hash for high confidence
        assert origin.confidence == "high"


class TestOriginResolverAirdropTag:
    """Airdrop transaction classification."""

    def test_airdrop_deposit(self, tmp_path) -> None:
        """crypto_deposit with tag 'Airdrop' → method AIRDROP."""
        path = _write_th(
            tmp_path,
            "2025-03-10 12:00:00 UTC,crypto_deposit,Airdrop,,,,,"
            "Metamask,100,ARB,150,,,eth,eth,0xairdrop,airdrop claim\n",
        )
        resolver = TokenOriginResolver(path)
        origin = resolver.resolve("2025-03-10", "ARB", "Metamask")
        assert origin.acquisition_method == AcquisitionMethod.AIRDROP
        assert origin.acquired_from_asset == "Unknown"
        assert origin.acquired_from_platform == "Unknown"
        assert origin.confidence == "medium"


class TestOriginResolverRealizedGainTag:
    """Realized gain transaction classification."""

    def test_realized_gain_deposit(self, tmp_path) -> None:
        """crypto_deposit with tag 'Realized gain' → method REWARD."""
        path = _write_th(
            tmp_path,
            "2025-03-11 15:30:00 UTC,crypto_deposit,Realized gain,,,,,"
            "Kraken,0.5,ETH,1000,,,exchange,exchange,0xgain,realized\n",
        )
        resolver = TokenOriginResolver(path)
        origin = resolver.resolve("2025-03-11", "ETH", "Kraken")
        assert origin.acquisition_method == AcquisitionMethod.REWARD
        assert origin.acquired_from_asset == "Unknown"
        assert origin.acquired_from_platform == "Unknown"
        assert origin.confidence == "medium"


class TestOriginResolverRealDataVerification:
    """Verification tests against known real transaction patterns."""

    def test_lp_withdrawal_2025_03_09_sui_cetus_lp(self, tmp_path) -> None:
        """Verify known LP withdrawal from 2025-03-09 11:48:47 UTC resolves to CETUS-LP origin.

        Real data pattern: TxHash 0xfeedface..., CETUS-LP tokens sent via crypto_withdrawal,
        SSUI received via crypto_deposit with 'Liquidity out' tag.
        Expected: from_asset = 'CETUS-LP', method = LIQUIDITY_WITHDRAWAL.
        """
        path = _write_th(
            tmp_path,
            # crypto_withdrawal row (LP tokens sent) - TxHash at index 16
            "2025-03-09 11:48:47 UTC,crypto_withdrawal,Liquidity out,SUI,6.97,CETUS-LP,173,"
            ",,,,,,,,,0xfeedfacefeedfacefeedfacefeedfacefeedfacefeedfacefeedfacefeedface,,,remove liquidity\n"  # noqa: E501
            # crypto_deposit row (SSUI received from LP) - TxHash at index 16
            "2025-03-09 11:48:47 UTC,crypto_deposit,Liquidity out,,,,,SUI,54.97,SSUI,172.42,"
            ",,,,,0xfeedfacefeedfacefeedfacefeedfacefeedfacefeedfacefeedfacefeedface,,,remove liquidity\n"  # noqa: E501
            # Additional deposits from same transaction (USDC, CETUS)
            "2025-03-09 11:48:47 UTC,crypto_deposit,Liquidity out,,,,,SUI,0.52,USDC,0.56,"
            ",,,,,0xfeedfacefeedfacefeedfacefeedfacefeedfacefeedfacefeedfacefeedface,,,remove liquidity\n"  # noqa: E501
            "2025-03-09 11:48:47 UTC,crypto_deposit,Liquidity out,,,,,SUI,0.15,CETUS,0.02,"
            ",,,,,0xfeedfacefeedfacefeedfacefeedfacefeedfacefeedfacefeedfacefeedface,,,remove liquidity\n",  # noqa: E501
        )
        resolver = TokenOriginResolver(path)
        origin = resolver.resolve("2025-03-09", "SSUI", "SUI")
        assert origin.acquisition_method == AcquisitionMethod.LIQUIDITY_WITHDRAWAL
        assert origin.acquired_from_asset == "CETUS-LP"
        assert origin.acquired_from_platform == "SUI"
        assert origin.confidence == "high"

        # Also verify USDC and CETUS from same transaction
        origin_usdc = resolver.resolve("2025-03-09", "USDC", "SUI")
        assert origin_usdc.acquisition_method == AcquisitionMethod.LIQUIDITY_WITHDRAWAL
        assert origin_usdc.acquired_from_asset == "CETUS-LP"

        origin_cetus = resolver.resolve("2025-03-09", "CETUS", "SUI")
        assert origin_cetus.acquisition_method == AcquisitionMethod.LIQUIDITY_WITHDRAWAL
        assert origin_cetus.acquired_from_asset == "CETUS-LP"


class TestOriginResolverExchangeLPHighConfidence:
    """exchange type LP operations should retain tx_hash for high confidence and not be overridden."""

    def test_exchange_liquidity_in_keeps_high_confidence(self, tmp_path) -> None:
        """exchange rows with 'Liquidity in' tag should keep tx_hash for high confidence.

        Unlike crypto_deposit rows, exchange rows already have both sent and received
        currencies populated, so they don't need paired withdrawal lookup.
        """
        path = _write_th(
            tmp_path,
            "2025-02-23 18:47:14 UTC,exchange,Liquidity in,Ledger APTOS,0.00128427,ABTC,113.00,"
            "Ledger APTOS,0.78987847,CAKE-LP,113.00,,,,,,hash123,,,add liquidity\n",
        )
        resolver = TokenOriginResolver(path)
        origin = resolver.resolve("2025-02-23", "CAKE-LP", "Ledger APTOS")
        assert origin.acquisition_method == AcquisitionMethod.LIQUIDITY_PROVISION
        assert origin.acquired_from_asset == "ABTC"
        assert origin.confidence == "high"

    def test_exchange_liquidity_out_keeps_high_confidence(self, tmp_path) -> None:
        """exchange rows with 'Liquidity out' tag should keep tx_hash for high confidence."""
        path = _write_th(
            tmp_path,
            "2025-02-23 18:47:14 UTC,exchange,Liquidity out,Cetus,5,CETUS-LP,25,"
            "Cetus,50,SSUI,100,,,,,,hash123,,,remove liquidity\n",
        )
        resolver = TokenOriginResolver(path)
        origin = resolver.resolve("2025-02-23", "SSUI", "Cetus")
        assert origin.acquisition_method == AcquisitionMethod.LIQUIDITY_WITHDRAWAL
        assert origin.acquired_from_asset == "CETUS-LP"
        assert origin.confidence == "high"

    def test_exchange_lp_multi_leg_provisions_merge(self, tmp_path) -> None:
        """Multiple exchange LP provisions with same TxHash should merge.

        Same-asset, same-wallet transfers are skipped during indexing.
        When multiple exchange LP provisions share the same TxHash and disagree on from_asset (ABTC vs APT),
        the resolver merges them into a combined origin (ABTC+APT).
        """
        path = _write_th(
            tmp_path,
            # Two exchange rows acquiring LP tokens (same TxHash = multi-leg LP provision)
            "2025-02-23 18:47:14 UTC,exchange,Liquidity in,Ledger APTOS,0.00128427,ABTC,113.00,"
            "Ledger APTOS,0.78987847,CAKE-LP,113.00,,,,,,hash1,,,add liquidity\n"
            "2025-02-23 18:47:14 UTC,exchange,Liquidity in,Ledger APTOS,19.95031885,APT,112.72,"
            "Ledger APTOS,0.78987846,CAKE-LP,112.72,,,,,,hash1,,,add liquidity\n"
            # Later transfer to pool
            "2025-02-23 18:47:49 UTC,transfer,To pool,Ledger APTOS,1.57975693,CAKE-LP,225.71,"
            "Ledger APTOS,1.57975693,CAKE-LP,225.71,,,,,,,hash2,,,pool transfer\n",
        )
        resolver = TokenOriginResolver(path)
        origin = resolver.resolve("2025-02-23", "CAKE-LP", "Ledger APTOS")
        # Multiple exchange LP provisions with same TxHash should merge into combined origin
        assert origin.acquisition_method == AcquisitionMethod.LIQUIDITY_PROVISION
        assert origin.acquired_from_asset == "ABTC+APT"
        assert origin.acquired_from_platform == "Ledger APTOS"
        assert origin.confidence == "high"

    def test_exchange_lp_single_source_not_overridden(self, tmp_path) -> None:
        """Single exchange LP provision should resolve correctly despite same-day transfer.

        Same-asset, same-wallet transfers (like internal pool shuffles) are not indexed
        as acquisition candidates, so they don't compete with real acquisition events.
        The LP origin should resolve to the exchange provision.
        """
        path = _write_th(
            tmp_path,
            # Single exchange acquiring LP token
            "2025-02-23 18:47:14 UTC,exchange,Liquidity in,Ledger APTOS,19.95031885,APT,112.72,"
            "Ledger APTOS,0.78987846,CAKE-LP,112.72,,,,,,hash1,,,add liquidity\n"
            # Later transfer to pool (same asset, same wallet - should be skipped)
            "2025-02-23 18:47:49 UTC,transfer,To pool,Ledger APTOS,1.57975693,CAKE-LP,225.71,"
            "Ledger APTOS,1.57975693,CAKE-LP,225.71,,,,,,,hash2,,,pool transfer\n",
        )
        resolver = TokenOriginResolver(path)
        origin = resolver.resolve("2025-02-23", "CAKE-LP", "Ledger APTOS")
        # Same-asset, same-wallet transfers are skipped, so LP origin resolves correctly
        assert origin.acquisition_method == AcquisitionMethod.LIQUIDITY_PROVISION
        assert origin.acquired_from_asset == "APT"
        assert origin.acquired_from_platform == "Ledger APTOS"
        assert origin.confidence == "high"

    def test_exchange_lp_different_txhash_should_not_merge(self, tmp_path) -> None:
        """Multiple exchange LP provisions with different TxHash should NOT merge.

        When multiple exchange LP provisions have different TxHash values on the same
        day for the same asset and wallet, they represent separate add-liquidity
        transactions. Since TxHash is a deterministic on-chain identifier, merging
        across TxHash would conflate separate transactions and misstate provenance.
        The resolver returns unknown when disagreeing LP records have different TxHash.
        """
        path = _write_th(
            tmp_path,
            # Two exchange rows with different TxHash (separate LP provisions)
            "2025-02-23 18:47:14 UTC,exchange,Liquidity in,Ledger APTOS,0.00128427,ABTC,113.00,"
            "Ledger APTOS,0.78987847,CAKE-LP,113.00,,,,,,hash1,,,add liquidity\n"
            "2025-02-23 18:47:15 UTC,exchange,Liquidity in,Ledger APTOS,19.95031885,APT,112.72,"
            "Ledger APTOS,0.78987846,CAKE-LP,112.72,,,,,,hash2,,,add liquidity\n",
        )
        resolver = TokenOriginResolver(path)
        origin = resolver.resolve("2025-02-23", "CAKE-LP", "Ledger APTOS")
        # Different TxHash values should NOT merge - they disagree on from_asset
        assert origin == TokenOrigin.unknown()


