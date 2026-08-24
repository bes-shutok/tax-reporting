"""Tests for the raw-row to CSV-row decoder (Task 4).

RED phase: these tests pin the behaviour of ``decode_rows`` before the
production module ``src/tax_reporting/infrastructure/on_chain/bera_decoder.py``
exists. The decoder is chain-agnostic: every chain-identity field (chain name,
native ticker, wallet address, dates) flows from ``OnChainWalletConfig``
(DI-2). There is NO ``chain_to_native_ticker`` fallback map (r1 F4).

Neutral placeholders are used throughout: ``Examplechain``/``EXM`` is the
artificial chain used by the committed template, ``0x0000...1111`` /
``0x0000...2222`` are placeholder wallet addresses, and ``chainid=99999`` is a
fictitious test-only chain identifier. No real chain identity literals appear
here or in the implementation (DI-2 clean).
"""

from __future__ import annotations

import logging
from datetime import date

import pytest

from tax_reporting.application.on_chain_config import OnChainWalletConfig
from tax_reporting.infrastructure.on_chain.bera_decoder import (
    OnChainTxRow,
    decode_rows,
)

# Neutral test-only values. chainid 99999 is fictitious; the wallet addresses
# are placeholders. None encode real chain identity (DI-2 clean).
_CHAINID = 99999
_NATIVE_TICKER = "EXM"
_CHAIN_NAME = "Examplechain"
_WALLET_FROM = "0x0000000000000000000000000000000000001111"
_WALLET_TO = "0x0000000000000000000000000000000000002222"

# A timestamp (Unix seconds) that falls on 2025-03-15 UTC, well inside the
# default config's date window. 1742169600 == 2025-03-16T21:20:00Z; any value
# inside the window is fine - we just need a known date for filter tests.
_TS_INSIDE = "1710518400"  # 2024-03-15T16:00:00Z -> date 2024-03-15
_TS_OUTSIDE = "1609459200"  # 2021-01-01T00:00:00Z -> date 2021-01-01


def _config(
    *,
    address: str = _WALLET_FROM,
    start: date = date(2024, 1, 1),
    end: date = date(2024, 12, 31),
    native_ticker: str = _NATIVE_TICKER,
) -> OnChainWalletConfig:
    """Build a neutral wallet config for tests (artificial chain)."""
    return OnChainWalletConfig(
        chain=_CHAIN_NAME,
        chainid=_CHAINID,
        label="example-wallet",
        address=address,
        native_ticker=native_ticker,
        start_date=start,
        end_date=end,
    )


def _txlist_row(**overrides: object) -> dict:
    """Build a minimal txlist row as the Etherscan API returns it.

    Pass keyword overrides (e.g. ``value="..."``, ``timeStamp=...``) to vary
    specific fields; the rest take neutral defaults.
    """
    base: dict = {
        "hash": "0xabc",
        "blockNumber": "100",
        "timeStamp": _TS_INSIDE,
        "from": _WALLET_FROM,
        "to": _WALLET_TO,
        "value": "1000000000000000000",
        "gas": "21000",
        "gasPrice": "1000000000",
        "gasUsed": "21000",
    }
    base.update(overrides)
    return base


def _internal_row(**overrides: object) -> dict:
    """Build a minimal txlistinternal row as the Etherscan API returns it.

    Mirrors the real ``action=txlistinternal`` field set per the Etherscan API
    docs: it carries ``gasUsed`` but NOT ``gasPrice`` (gas is recorded on the
    parent tx's ``txlist`` row, so no fee is attributed to internal rows).
    """
    base: dict = {
        "hash": "0xparent",
        "blockNumber": "150",
        "timeStamp": _TS_INSIDE,
        "from": _WALLET_FROM,
        "to": _WALLET_TO,
        "value": "2500000000000000000",
        "gas": "30000",
        "gasUsed": "30000",
        "input": "",
        "type": "call",
    }
    base.update(overrides)
    return base


def _tokentx_row(**overrides: object) -> dict:
    """Build a minimal tokentx row as the Etherscan API returns it."""
    base: dict = {
        "hash": "0xdef",
        "blockNumber": "200",
        "timeStamp": _TS_INSIDE,
        "from": _WALLET_FROM,
        "to": _WALLET_TO,
        "value": "5000000",
        "tokenSymbol": "USDC",
        "tokenName": "USD Coin",
        "tokenDecimal": "6",
        "contractAddress": "0xcontract123",
    }
    base.update(overrides)
    return base


@pytest.mark.unit
class TestBeraDecoder:
    """Test the raw-row to CSV-row decoder behaviour."""

    def test_native_bera_txlist_row(self):
        # Given - a txlist native transfer where the wallet is the sender
        cfg = _config(address=_WALLET_FROM)
        row = _txlist_row()

        # When
        result = decode_rows([row], [], cfg)

        # Then - one decoded row with native-tx semantics
        assert len(result) == 1
        decoded = result[0]
        assert isinstance(decoded, OnChainTxRow)
        # DI-2: asset is the config's native_ticker, NOT a hardcoded literal.
        assert decoded.asset == _NATIVE_TICKER
        assert decoded.token_address == ""
        assert decoded.amount_raw == 1000000000000000000
        assert decoded.amount_decimals == 18
        assert decoded.direction == "out"
        # fee_amount_raw == gasUsed * gasPrice == 21000 * 1_000_000_000
        assert decoded.fee_amount_raw == 21000 * 1000000000
        assert decoded.fee_asset == _NATIVE_TICKER

    def test_erc20_tokentx_row(self):
        # Given - a tokentx (ERC-20) row where the wallet is the recipient
        cfg = _config(address=_WALLET_TO)
        row = _tokentx_row()

        # When
        result = decode_rows([], [row], cfg)

        # Then
        assert len(result) == 1
        decoded = result[0]
        assert decoded.amount_raw == 5000000
        assert decoded.amount_decimals == 6
        assert decoded.direction == "in"
        assert decoded.asset == "USDC"
        assert decoded.token_address == "0xcontract123"

    @pytest.mark.parametrize(
        ("wallet_address", "expected_direction"),
        [
            (_WALLET_FROM, "out"),
            (_WALLET_TO, "in"),
        ],
    )
    def test_direction_resolved_from_wallet_address(
        self, wallet_address, expected_direction
    ):
        # Given - the SAME txlist row; only the wallet config address changes
        cfg = _config(address=wallet_address)
        row = _txlist_row()

        # When
        result = decode_rows([row], [], cfg)

        # Then
        assert len(result) == 1
        assert result[0].direction == expected_direction

    def test_off_wallet_leg_emits_unknown_and_warns(self, caplog):
        # Given - a wallet address matching NEITHER the row's from nor to (the
        # checksum-mismatch / off-wallet-leg case). r1 F3: the row must still
        # be emitted but flagged direction='unknown' (NOT silently 'in'), and a
        # WARNING carrying the tx hash + wallet + from/to must fire.
        off_wallet = "0x0000000000000000000000000000000000009999"
        cfg = _config(address=off_wallet)
        row = _txlist_row(hash="0xoff")  # from=_WALLET_FROM, to=_WALLET_TO

        # When
        with caplog.at_level(logging.WARNING):
            result = decode_rows([row], [], cfg)

        # Then - row emitted with the sentinel direction, not 'in'.
        assert len(result) == 1
        assert result[0].direction == "unknown"
        warning_text = "\n".join(rec.message for rec in caplog.records)
        assert "Off-wallet leg" in warning_text
        assert "0xoff" in warning_text  # tx hash carried in the WARNING
        assert off_wallet in warning_text  # wallet address carried

    def test_row_date_filtered_outside_range(self):
        # Given - a row whose timeStamp falls OUTSIDE the config date window
        cfg = _config(start=date(2024, 1, 1), end=date(2024, 12, 31))
        outside_row = _txlist_row(timeStamp=_TS_OUTSIDE)  # 2021-01-01
        inside_row = _txlist_row(timeStamp=_TS_INSIDE, blockNumber="101")  # 2024

        # When
        result = decode_rows([outside_row, inside_row], [], cfg)

        # Then - the outside row is SKIPPED (filter lives in the decoder,
        # not the client; this is testable without HTTP).
        assert len(result) == 1
        assert result[0].block_number == "101"

    def test_malformed_row_isolated(self, caplog):
        # Given - one row missing 'value' and one row with a non-integer
        # 'value', alongside a well-formed row
        cfg = _config(address=_WALLET_FROM)
        good = _txlist_row(blockNumber="100")
        missing_value = _txlist_row(blockNumber="101")
        del missing_value["value"]
        bad_value = _txlist_row(blockNumber="102", value="not-a-number")

        # When
        with caplog.at_level(logging.WARNING):
            result = decode_rows([good, missing_value, bad_value], [], cfg)

        # Then - the good row is returned; the two bad rows are SKIPPED with a
        # WARNING carrying row context (AGENTS.md: catch row-level parse errors
        # per row; never let one bad row discard the dataset).
        assert len(result) == 1
        assert result[0].block_number == "100"
        warning_text = "\n".join(rec.message for rec in caplog.records)
        assert warning_text, "expected a WARNING for the malformed rows"

    def test_raw_amount_preserved_no_float(self):
        # Given - a txlist row with the canonical 1e18 native value
        cfg = _config(address=_WALLET_FROM)
        row = _txlist_row(value="1000000000000000000")

        # When
        result = decode_rows([row], [], cfg)

        # Then - amount_raw is preserved as int (or str), NEVER a float (DI-4).
        assert len(result) == 1
        amount_raw = result[0].amount_raw
        assert isinstance(amount_raw, (int, str))
        assert not isinstance(amount_raw, float)
        assert str(amount_raw) == "1000000000000000000"

    def test_internal_native_receive_becomes_in_leg(self):
        # Given - an internal-tx row with native value TO the wallet, for a tx
        # that already carries a token out-leg (the cluster-2 shape: native BERA
        # received via an internal call inside a parent tx).
        cfg = _config(address=_WALLET_TO)
        token_out = _tokentx_row(**{"from": _WALLET_TO, "to": _WALLET_FROM})
        internal = _internal_row()  # from=_WALLET_FROM, to=_WALLET_TO

        # When
        result = decode_rows([], [token_out], cfg, raw_internal_rows=[internal])

        # Then - the decoded rows include BOTH legs: the token out-leg and the
        # native receive leg with direction 'in'.
        assert len(result) == 2
        receive = [r for r in result if r.direction == "in"]
        assert len(receive) == 1
        assert receive[0].asset == _NATIVE_TICKER
        assert receive[0].amount_raw == 2500000000000000000
        assert receive[0].amount_decimals == 18
        assert receive[0].token_address == ""
        assert receive[0].tx_hash == "0xparent"

    def test_internal_row_without_gas_price_still_decodes(self):
        # Given - an internal-tx row whose schema omits ``gasPrice`` (the real
        # txlistinternal field set per the Etherscan API docs) but carries
        # ``gasUsed``. The row must decode into a receive leg, not be silently
        # skipped; fees are NOT attributed to internal rows (the parent tx's
        # gas already lives on its txlist row - no double count).
        cfg = _config(address=_WALLET_TO)
        assert "gasPrice" not in _internal_row()  # fixture mirrors the real schema
        internal = _internal_row()

        # When
        result = decode_rows([], [], cfg, raw_internal_rows=[internal])

        # Then - one decoded receive leg with zero fee attributed.
        assert len(result) == 1
        decoded = result[0]
        assert decoded.direction == "in"
        assert decoded.asset == _NATIVE_TICKER
        assert decoded.fee_amount_raw == 0
        assert decoded.fee_asset == ""

    def test_reverted_internal_row_skipped_with_warning(self, caplog):
        # Review r1 F1: a reverted internal call (errCode non-empty / isError
        # == '1') never executed, so it must NOT become a phantom in-leg that
        # flips the classifier's pure-outflow deposit shapes into
        # bidirectional Swap/Reward shapes.
        cfg = _config(address=_WALLET_TO)
        token_out = _tokentx_row(**{"from": _WALLET_TO, "to": _WALLET_FROM})
        reverted_by_errcode = _internal_row(errCode="Reverted")
        reverted_by_iserror = _internal_row(isError="1")

        with caplog.at_level(logging.WARNING):
            result = decode_rows(
                [],
                [token_out],
                cfg,
                raw_internal_rows=[reverted_by_errcode, reverted_by_iserror],
            )

        # Only the token out-leg survives: both reverted rows are skipped.
        assert len(result) == 1
        assert result[0].direction == "out"
        warnings = [r for r in caplog.records if "reverted" in r.getMessage()]
        assert len(warnings) == 2, "each reverted row logs its own WARNING naming the hash"
        assert all("0xparent" in w.getMessage() for w in warnings)

    def test_zero_value_internal_row_skipped(self):
        # Review r1 F1: a zero-value internal row carries no native movement;
        # decoding it would fabricate an amount-0 in-leg. It must be skipped so
        # the tx's pure-outflow deposit shape is not flipped.
        cfg = _config(address=_WALLET_TO)
        token_out = _tokentx_row(**{"from": _WALLET_TO, "to": _WALLET_FROM})
        zero_value = _internal_row(value="0")

        result = decode_rows([], [token_out], cfg, raw_internal_rows=[zero_value])

        assert len(result) == 1
        assert result[0].direction == "out"

    def test_native_ticker_from_config_not_hardcoded(self):
        # Given - a NON-real chain (artificial Examplechain / EXM). If the
        # decoder hardcodes "BERA" OR has a chain_to_native_ticker fallback
        # map, this row's asset would NOT equal "EXM".
        cfg = _config(address=_WALLET_FROM, native_ticker="EXM")
        row = _txlist_row()

        # When
        result = decode_rows([row], [], cfg)

        # Then - the native asset name flows from config (DI-2; r1 F4).
        assert len(result) == 1
        assert result[0].asset == "EXM"
