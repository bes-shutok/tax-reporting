"""Edge-case tests for TokenOriginResolver.

Covers multiple matches per key, epoch-date sentinel, crypto-to-crypto
exchange derivation, bridge-transfer type handling, and confidence
downgrade on ambiguous or flagged rows.
"""

from __future__ import annotations

from shares_reporting.application.crypto_reporting import (
    AcquisitionMethod,
    TokenOriginResolver,
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


class TestOriginResolverMissingCostBasis:
    """Capital gains rows with 'Missing cost basis' in Notes get low confidence."""

    def test_missing_cost_basis_downgrades_high_to_low(self, tmp_path) -> None:
        path = _write_th(
            tmp_path,
            "2025-01-15 10:30:00 UTC,exchange,,Kraken,100,BTC,5000,"
            "Kraken,2.5,ETH,5000,,,,,,abc,def,hash123,trade\n",
        )
        resolver = TokenOriginResolver(path)
        origin = resolver.resolve("2025-01-15", "ETH", "Kraken", notes="Missing cost basis")
        assert origin.acquisition_method == AcquisitionMethod.SWAP_CONVERSION
        assert origin.confidence == "low"

    def test_missing_cost_basis_case_insensitive(self, tmp_path) -> None:
        path = _write_th(
            tmp_path,
            "2025-01-15 10:30:00 UTC,exchange,,Kraken,100,BTC,5000,"
            "Kraken,2.5,ETH,5000,,,,,,abc,def,hash123,trade\n",
        )
        resolver = TokenOriginResolver(path)
        origin = resolver.resolve("2025-01-15", "ETH", "Kraken", notes="missing cost basis")
        assert origin.confidence == "low"

    def test_missing_cost_basis_within_longer_notes(self, tmp_path) -> None:
        path = _write_th(
            tmp_path,
            "2025-01-15 10:30:00 UTC,exchange,,Kraken,100,BTC,5000,"
            "Kraken,2.5,ETH,5000,,,,,,abc,def,hash123,trade\n",
        )
        resolver = TokenOriginResolver(path)
        origin = resolver.resolve(
            "2025-01-15", "ETH", "Kraken",
            notes="Auto-imported — Missing cost basis applied",
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
            "Kraken,2.5,ETH,5000,,,,,,abc,def,hash123,trade\n",
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
