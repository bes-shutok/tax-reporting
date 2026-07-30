"""Unit tests for crypto derivatives CG/TH deduplication loader.

These tests follow the TDD RED -> GREEN -> refactor cycle. They cover the
per-provider-per-year label config loader used to identify derivatives TH
events that should be removed from the capital-gains report.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import time
from decimal import Decimal
from pathlib import Path

import pytest

from tax_reporting.application.crypto.entities import CryptoCapitalGainEntry
from tax_reporting.application.crypto.operator_origin import OperatorOrigin
from tax_reporting.application.crypto_reporting import build_transactions_from_th
from tax_reporting.domain.exceptions import FileProcessingError
from tests.conftest import build_origin_resolver


class TestDerivativesLabelsConfig:
    """Tests for _load_derivatives_labels_config and its _from_path helper."""

    def test_loads_koinly_2025_labels(self):
        """Given docs/maintenance/tax/derivatives_labels/koinly_2025.json with the canonical
        label list, expects the loader to return the frozenset of those labels.
        """
        from tax_reporting.application.crypto.derivatives_filter import (
            _load_derivatives_labels_config,
        )

        result = _load_derivatives_labels_config(provider="koinly", year=2025)
        assert result == frozenset({"Funding fee", "Futures fee", "Realized gain"})

    def test_missing_file_returns_empty_silently(self, tmp_path: Path, caplog: pytest.LogCaptureFixture):
        """Given no config file for (provider, year), expects empty frozenset
        and no warning at the loader level. The apply_derivatives_dedup caller
        emits the single actionable WARNING with the remediation hint when it
        observes the empty result (verified in e2e
        ``test_dedup_skipped_when_config_missing``).
        """
        from tax_reporting.application.crypto.derivatives_filter import (
            _load_derivatives_labels_config_from_path,
        )

        missing = tmp_path / "absent_2099.json"
        with caplog.at_level(logging.WARNING, logger="tax_reporting.application.crypto.derivatives_filter"):
            result = _load_derivatives_labels_config_from_path(missing)

        assert result == frozenset()
        assert not any(
            record.levelno >= logging.WARNING for record in caplog.records
        ), "Loader must not warn for missing file; apply_derivatives_dedup owns that warning"

    def test_malformed_json_raises(self, tmp_path: Path):
        """Given a config file with invalid JSON, expects FileProcessingError
        with the file path and parse error message.
        """
        from tax_reporting.application.crypto.derivatives_filter import (
            _load_derivatives_labels_config_from_path,
        )

        bad = tmp_path / "bad.json"
        bad.write_text("{not valid json", encoding="utf-8")

        with pytest.raises(FileProcessingError) as exc_info:
            _load_derivatives_labels_config_from_path(bad)

        message = str(exc_info.value)
        assert str(bad) in message

    def test_missing_derivatives_th_labels_key_raises(self, tmp_path: Path):
        """Given a config file with valid JSON but no derivatives_th_labels key,
        expects FileProcessingError naming the file.
        """
        from tax_reporting.application.crypto.derivatives_filter import (
            _load_derivatives_labels_config_from_path,
        )

        bad = tmp_path / "missing_key.json"
        bad.write_text(json.dumps({"other_key": ["something"]}), encoding="utf-8")

        with pytest.raises(FileProcessingError) as exc_info:
            _load_derivatives_labels_config_from_path(bad)

        assert str(bad) in str(exc_info.value)

    def test_labels_value_wrong_type_raises(self, tmp_path: Path):
        """Given a config file where derivatives_th_labels is not a list of
        strings, expects FileProcessingError.
        """
        from tax_reporting.application.crypto.derivatives_filter import (
            _load_derivatives_labels_config_from_path,
        )

        bad = tmp_path / "wrong_type.json"
        bad.write_text(json.dumps({"derivatives_th_labels": 42}), encoding="utf-8")

        with pytest.raises(FileProcessingError) as exc_info:
            _load_derivatives_labels_config_from_path(bad)

        assert str(bad) in str(exc_info.value)

    def test_labels_value_nested_object_raises(self, tmp_path: Path):
        """Given a derivatives_th_labels value that is a nested object rather
        than a flat list, expects FileProcessingError.
        """
        from tax_reporting.application.crypto.derivatives_filter import (
            _load_derivatives_labels_config_from_path,
        )

        bad = tmp_path / "nested.json"
        bad.write_text(
            json.dumps({"derivatives_th_labels": {"foo": "bar"}}),
            encoding="utf-8",
        )

        with pytest.raises(FileProcessingError):
            _load_derivatives_labels_config_from_path(bad)

    def test_labels_value_non_string_elements_raises(self, tmp_path: Path):
        """Given a derivatives_th_labels value that is a list but contains
        non-string elements (numbers), expects FileProcessingError.
        """
        from tax_reporting.application.crypto.derivatives_filter import (
            _load_derivatives_labels_config_from_path,
        )

        bad = tmp_path / "non_strings.json"
        bad.write_text(
            json.dumps({"derivatives_th_labels": [1, 2, 3]}),
            encoding="utf-8",
        )

        with pytest.raises(FileProcessingError):
            _load_derivatives_labels_config_from_path(bad)

    def test_rejects_symlink_config(self, tmp_path: Path):
        """Given a config file that is a symlink, expects FileProcessingError
        for security reasons (mirrors classification.py:_load_popular_crypto_tokens).
        """
        from tax_reporting.application.crypto.derivatives_filter import (
            _load_derivatives_labels_config_from_path,
        )

        real = tmp_path / "real.json"
        real.write_text(
            json.dumps({"derivatives_th_labels": ["Funding fee"]}),
            encoding="utf-8",
        )
        link = tmp_path / "link.json"
        link.symlink_to(real)

        with pytest.raises(FileProcessingError) as exc_info:
            _load_derivatives_labels_config_from_path(link)

        assert str(link) in str(exc_info.value)

    def test_stat_error_raises(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Given a config file whose stat() raises OSError, expects
        FileProcessingError embedding the file path (closes a copy-paste hole
        where an implementer could degrade the stat_error arm).
        """
        from tax_reporting.application.crypto.derivatives_filter import Path as DedupPath
        from tax_reporting.application.crypto.derivatives_filter import (
            _load_derivatives_labels_config_from_path,
        )

        config = tmp_path / "stat_fails.json"
        config.write_text(
            json.dumps({"derivatives_th_labels": ["Funding fee"]}),
            encoding="utf-8",
        )

        def raise_oserror(self: Path) -> object:
            raise OSError("simulated stat failure")

        monkeypatch.setattr(DedupPath, "stat", raise_oserror)

        with pytest.raises(FileProcessingError) as exc_info:
            _load_derivatives_labels_config_from_path(config)

        assert str(config) in str(exc_info.value)


class TestDisposalTimestamp:
    """Tests for the disposal_timestamp field added in Task 3 of the plan.

    The plan adds an optional ``disposal_timestamp`` (minute precision) to
    ``CryptoCapitalGainEntry``, ``CryptoConsumption``, ``CryptoFifoRealization``,
    and a ``timestamp_str`` (minute precision) to ``ParsedTxRow``. The field
    supports the CG-side filter that matches CG lots to TH events by minute
    precision (day-level ``disposal_date`` is insufficient because CG rows on
    the same day may originate from different TH events).
    """

    def test_crypto_capital_gain_entry_has_field(self):
        """CryptoCapitalGainEntry exposes an optional disposal_timestamp field."""
        from tax_reporting.application.crypto.entities import CryptoCapitalGainEntry

        names = {f.name for f in dataclasses.fields(CryptoCapitalGainEntry)}
        assert "disposal_timestamp" in names

        # Default must be None (backward compat for existing constructors).
        disposal_timestamp_field = next(
            f for f in dataclasses.fields(CryptoCapitalGainEntry) if f.name == "disposal_timestamp"
        )
        assert disposal_timestamp_field.default is None

    def test_crypto_consumption_has_field(self):
        """CryptoConsumption exposes an optional disposal_timestamp field."""
        from tax_reporting.domain.crypto_fifo import CryptoConsumption

        names = {f.name for f in dataclasses.fields(CryptoConsumption)}
        assert "disposal_timestamp" in names

        disposal_timestamp_field = next(
            f for f in dataclasses.fields(CryptoConsumption) if f.name == "disposal_timestamp"
        )
        assert disposal_timestamp_field.default is None

    def test_crypto_fifo_realization_has_field(self):
        """CryptoFifoRealization exposes an optional disposal_timestamp field."""
        from tax_reporting.domain.crypto_fifo import CryptoFifoRealization

        names = {f.name for f in dataclasses.fields(CryptoFifoRealization)}
        assert "disposal_timestamp" in names

        disposal_timestamp_field = next(
            f for f in dataclasses.fields(CryptoFifoRealization) if f.name == "disposal_timestamp"
        )
        assert disposal_timestamp_field.default is None

    def test_parsed_tx_row_has_field(self):
        """ParsedTxRow exposes an optional timestamp_str field."""
        from tax_reporting.application.crypto_fifo.contexts import ParsedTxRow

        names = {f.name for f in dataclasses.fields(ParsedTxRow)}
        assert "timestamp_str" in names

        timestamp_str_field = next(
            f for f in dataclasses.fields(ParsedTxRow) if f.name == "timestamp_str"
        )
        assert timestamp_str_field.default is None

    def test_cg_parser_populates_timestamp(self, tmp_path: Path):
        """Given a CG row with Date Sold = '24/01/2025 23:40', expects
        disposal_timestamp to equal '2025-01-24 23:40' and disposal_date to
        remain '2025-01-24' (day-level, unchanged for backward compatibility).
        """
        from tax_reporting.application.crypto_reporting import (
            CapitalGainsParsingContext,
            _parse_capital_gains_file,
        )

        capital_csv = tmp_path / "capital.csv"
        capital_csv.write_text(
            "\n".join(
                [
                    "Capital gains report 2025",
                    "",
                    ",".join(
                        [
                            "Date Sold",
                            "Date Acquired",
                            "Asset",
                            "Amount",
                            "Cost (EUR)",
                            "Proceeds (EUR)",
                            "Gain / loss",
                            "Notes",
                            "Wallet Name",
                            "Holding period",
                        ]
                    ),
                    ",".join(
                        [
                            "24/01/2025 23:40",
                            "24/01/2025 23:40",
                            "USDT",
                            '"1,0"',
                            '"10,00"',
                            '"20,00"',
                            '"10,00"',
                            "",
                            "ByBit",
                            "Short term",
                        ]
                    ),
                ]
            ),
            encoding="utf-8",
        )


        context = CapitalGainsParsingContext(
            skipped_assets={},
            origin_resolver=build_origin_resolver(None),
            review_entries=[],
        )
        entries, _ = _parse_capital_gains_file(capital_csv, context)

        assert len(entries) == 1
        entry = entries[0]
        assert entry.disposal_date == "2025-01-24"
        assert entry.disposal_timestamp == "2025-01-24 23:40"

    def test_fifo_parser_populates_timestamp(self):
        """Given a TH row with Date = '2025-01-24 23:40:53 UTC', expects the
        resulting ParsedTxRow.timestamp_str to equal '2025-01-24 23:40'
        (seconds truncated) and date_str to remain '2025-01-24' (day-level).
        """
        from tax_reporting.application.crypto_fifo.parsing import (
            _classify_rows_for_loan_affected_assets,
        )

        rows = [
            {
                "Date": "2025-01-24 23:40:53 UTC",
                "Type": "crypto_withdrawal",
                "Tag": "",
                "Sending Wallet": "ByBit",
                "Receiving Wallet": "",
                "Sent Amount": "1.0",
                "Sent Currency": "USDT",
                "Received Amount": "",
                "Received Currency": "",
                "Fee Amount": "",
                "Fee Currency": "",
                "Fee Value (EUR)": "",
                "Sent Cost Basis": "",
                "Net Value (EUR)": "10",
                "TxHash": "",
            }
        ]
        acquisitions, consumptions, _, _ = _classify_rows_for_loan_affected_assets(
            rows, loan_affected_assets=frozenset({"USDT"})
        )

        assert "USDT" in consumptions
        assert len(consumptions["USDT"]) == 1
        con = consumptions["USDT"][0].con
        assert con.date == "2025-01-24"
        assert con.disposal_timestamp == "2025-01-24 23:40"

    def test_fifo_chain_propagates_timestamp(self):
        """Given a TH row feeding the FIFO engine, expects the resulting
        CryptoCapitalGainEntry.disposal_timestamp to equal the minute-precision
        timestamp from the TH Date (via CryptoConsumption then CryptoFifoRealization
        then fifo_helpers).
        """
        from tax_reporting.application.crypto_fifo.contexts import (
            AcquisitionContext,
            ConsumptionContext,
        )
        from tax_reporting.application.crypto_fifo.matching import _build_taxable_realization
        from tax_reporting.domain.crypto_fifo import CryptoAcquisition, CryptoConsumption

        acq = AcquisitionContext(
            acq=CryptoAcquisition(
                date="2025-01-01",
                asset="USDT",
                amount=Decimal("1.0"),
                cost_basis_eur=Decimal("10"),
                fee_eur=Decimal("0"),
                source_type="buy",
                wallet="ByBit",
                platform="ByBit",
                review_required=False,
            ),
            tx_key="acq-key",
            source_row_index=1,
        )
        con = ConsumptionContext(
            con=CryptoConsumption(
                date="2025-01-24",
                asset="USDT",
                amount=Decimal("1.0"),
                proceeds_eur=Decimal("20"),
                event_type="sell",
                taxable=True,
                wallet="ByBit",
                platform="ByBit",
                notes="",
                review_required=False,
                disposal_timestamp="2025-01-24 23:40",
            ),
            tx_key="con-key",
            source_row_index=2,
        )

        realization = _build_taxable_realization(
            acq, con, Decimal("1.0"), Decimal("10"), Decimal("0"), Decimal("20"), "USDT", "ByBit"
        )

        assert realization.disposal_date == "2025-01-24"
        assert realization.disposal_timestamp == "2025-01-24 23:40"

    def test_cross_asset_exchange_emitter_propagates_timestamp(self):
        """Given a cross-asset exchange TH row (sent and received both loan-affected,
        routed via _emit_cross_asset_exchange), expects every CryptoConsumption
        produced to carry disposal_timestamp equal to the minute-precision timestamp
        from the TH Date.
        """
        from tax_reporting.application.crypto_fifo.parsing import (
            _classify_rows_for_loan_affected_assets,
        )

        rows = [
            {
                "Date": "2025-01-24 23:40:53 UTC",
                "Type": "exchange",
                "Tag": "",
                "Sending Wallet": "ByBit",
                "Receiving Wallet": "Binance",
                "Sent Amount": "1.0",
                "Sent Currency": "USDT",
                "Received Amount": "0.001",
                "Received Currency": "WBTC",
                "Fee Amount": "0",
                "Fee Currency": "",
                "Fee Value (EUR)": "0",
                "Sent Cost Basis": "10",
                "Net Value (EUR)": "10",
                "TxHash": "",
            }
        ]
        acquisitions, consumptions, _, _ = _classify_rows_for_loan_affected_assets(
            rows, loan_affected_assets=frozenset({"USDT", "WBTC"})
        )

        # At least one consumption produced from this exchange must carry the timestamp.
        all_cons = [c.con for cs in consumptions.values() for c in cs]
        assert len(all_cons) >= 1
        for con in all_cons:
            assert con.disposal_timestamp == "2025-01-24 23:40", (
                f"Consumption {con.event_type} did not carry disposal_timestamp"
            )

    def test_sent_only_exchange_emitter_propagates_timestamp(self):
        """Given an exchange TH row where only the sent currency is loan-affected
        (routed via _emit_sent_only_exchange), expects the consumption to carry
        disposal_timestamp from the TH Date.
        """
        from tax_reporting.application.crypto_fifo.parsing import (
            _classify_rows_for_loan_affected_assets,
        )

        rows = [
            {
                "Date": "2025-01-24 23:40:53 UTC",
                "Type": "exchange",
                "Tag": "",
                "Sending Wallet": "ByBit",
                "Receiving Wallet": "Binance",
                "Sent Amount": "1.0",
                "Sent Currency": "USDT",
                "Received Amount": "100.0",
                "Received Currency": "EUR",
                "Fee Amount": "0",
                "Fee Currency": "",
                "Fee Value (EUR)": "0",
                "Sent Cost Basis": "10",
                "Net Value (EUR)": "10",
                "TxHash": "",
            }
        ]
        _acquisitions, consumptions, _, _ = _classify_rows_for_loan_affected_assets(
            rows, loan_affected_assets=frozenset({"USDT"})
        )

        all_cons = [c.con for cs in consumptions.values() for c in cs]
        assert len(all_cons) >= 1, "sent-only exchange must produce at least one consumption"
        for con in all_cons:
            assert con.disposal_timestamp == "2025-01-24 23:40", (
                f"Consumption {con.event_type} did not carry disposal_timestamp"
            )

    def test_fee_only_exchange_emitter_propagates_timestamp(self):
        """Given an exchange TH row where neither sent nor received currency is
        loan-affected but the fee currency is (routed via _emit_fee_only_exchange),
        expects the fee consumption to carry disposal_timestamp from the TH Date.
        """
        from tax_reporting.application.crypto_fifo.parsing import (
            _classify_rows_for_loan_affected_assets,
        )

        rows = [
            {
                "Date": "2025-01-24 23:40:53 UTC",
                "Type": "exchange",
                "Tag": "",
                "Sending Wallet": "Binance",
                "Receiving Wallet": "Coinbase",
                "Sent Amount": "100.0",
                "Sent Currency": "EUR",
                "Received Amount": "100.0",
                "Received Currency": "EUR",
                "Fee Amount": "0.5",
                "Fee Currency": "USDT",
                "Fee Value (EUR)": "0.45",
                "Sent Cost Basis": "100",
                "Net Value (EUR)": "100",
                "TxHash": "",
            }
        ]
        _acquisitions, consumptions, _, _ = _classify_rows_for_loan_affected_assets(
            rows, loan_affected_assets=frozenset({"USDT"})
        )

        all_cons = [c.con for cs in consumptions.values() for c in cs]
        assert len(all_cons) >= 1, "fee-only exchange must produce at least one consumption"
        for con in all_cons:
            assert con.disposal_timestamp == "2025-01-24 23:40", (
                f"Consumption {con.event_type} did not carry disposal_timestamp"
            )

    def test_transfer_emitter_propagates_timestamp(self):
        """Given a transfer TH row between two distinct wallets for a loan-affected
        asset plus a fee in another loan-affected asset (routed via _handle_transfer,
        exercising both the transfer_out and fee_disposal consumption sites), expects
        every consumption to carry disposal_timestamp from the TH Date.
        """
        from tax_reporting.application.crypto_fifo.parsing import (
            _classify_rows_for_loan_affected_assets,
        )

        rows = [
            {
                "Date": "2025-01-24 23:40:53 UTC",
                "Type": "transfer",
                "Tag": "",
                "Sending Wallet": "ByBit",
                "Receiving Wallet": "Binance",
                "Sent Amount": "1.0",
                "Sent Currency": "USDT",
                "Received Amount": "1.0",
                "Received Currency": "USDT",
                "Fee Amount": "0.01",
                "Fee Currency": "WBTC",
                "Fee Value (EUR)": "5",
                "Sent Cost Basis": "10",
                "Net Value (EUR)": "10",
                "TxHash": "",
            }
        ]
        _acquisitions, consumptions, _, _ = _classify_rows_for_loan_affected_assets(
            rows, loan_affected_assets=frozenset({"USDT", "WBTC"})
        )

        all_cons = [c.con for cs in consumptions.values() for c in cs]
        assert len(all_cons) >= 1, "transfer must produce at least one consumption"
        for con in all_cons:
            assert con.disposal_timestamp == "2025-01-24 23:40", (
                f"Consumption {con.event_type} did not carry disposal_timestamp"
            )

    def test_existing_constructors_backward_compat(self):
        """Given existing code that constructs CryptoCapitalGainEntry,
        CryptoConsumption, or CryptoFifoRealization without passing
        disposal_timestamp, expects no error (default None applies).
        """
        from tax_reporting.application.crypto.entities import CryptoCapitalGainEntry
        from tax_reporting.application.crypto.operator_origin import OperatorOrigin
        from tax_reporting.domain.crypto_fifo import (
            CryptoConsumption,
            CryptoFifoRealization,
        )

        operator_origin = OperatorOrigin(
            platform="ByBit",
            service_scope="crypto",
            operator_entity="ByBit",
            operator_country="Unknown",
            source_url="",
            source_checked_on="",
            confidence="low",
            review_required=False,
        )

        # CryptoCapitalGainEntry without disposal_timestamp must not raise.
        entry = CryptoCapitalGainEntry(
            disposal_date="2025-01-24",
            acquisition_date="2025-01-01",
            asset="USDT",
            amount=Decimal("1"),
            cost_eur=Decimal("10"),
            proceeds_eur=Decimal("20"),
            gain_loss_eur=Decimal("10"),
            holding_period="Short term",
            wallet="ByBit",
            platform="ByBit",
            chain="Unknown",
            operator_origin=operator_origin,
            annex_hint="J",
            review_required=False,
            notes="",
        )
        assert entry.disposal_timestamp is None

        # CryptoConsumption without disposal_timestamp must not raise.
        con = CryptoConsumption(
            date="2025-01-24",
            asset="USDT",
            amount=Decimal("1"),
            proceeds_eur=Decimal("20"),
            event_type="sell",
            taxable=True,
            wallet="ByBit",
            platform="ByBit",
            notes="",
            review_required=False,
        )
        assert con.disposal_timestamp is None

        # CryptoFifoRealization without disposal_timestamp must not raise.
        realization = CryptoFifoRealization(
            disposal_date="2025-01-24",
            acquisition_date="2025-01-01",
            asset="USDT",
            amount=Decimal("1"),
            cost_eur=Decimal("10"),
            proceeds_eur=Decimal("20"),
            gain_loss_eur=Decimal("10"),
            holding_period="Short term",
            wallet="ByBit",
            platform="ByBit",
            notes="",
            review_required=False,
        )
        assert realization.disposal_timestamp is None


_TEST_OPERATOR_ORIGIN = OperatorOrigin(
    platform="ByBit",
    service_scope="crypto",
    operator_entity="ByBit",
    operator_country="Unknown",
    source_url="",
    source_checked_on="2026-01-01",
    confidence="low",
    review_required=False,
    valid_from="2026-01-01",
)


def _make_cg_lot(  # noqa: PLR0913
    *,
    disposal_timestamp: str,
    asset: str = "USDT",
    wallet: str = "ByBit",
    amount: Decimal,
    acquisition_date: str = "2025-01-10",
    proceeds_eur: Decimal = Decimal("0"),
    gain_loss_eur: Decimal = Decimal("0"),
    cost_eur: Decimal = Decimal("0"),
) -> CryptoCapitalGainEntry:
    """Build a CryptoCapitalGainEntry fixture for dedup tests.

    The dedup matcher only inspects disposal_timestamp, asset, wallet, amount,
    acquisition_date, proceeds_eur, gain_loss_eur, and cost_eur. Sensible
    defaults are provided for the rest so each test only sets the fields it
    cares about.
    """
    return CryptoCapitalGainEntry(
        disposal_date=disposal_timestamp.split(" ")[0],
        acquisition_date=acquisition_date,
        asset=asset,
        amount=amount,
        cost_eur=cost_eur,
        proceeds_eur=proceeds_eur,
        gain_loss_eur=gain_loss_eur,
        holding_period="Short term",
        wallet=wallet,
        platform=wallet,
        chain="Unknown",
        operator_origin=_TEST_OPERATOR_ORIGIN,
        annex_hint="J",
        review_required=False,
        notes="",
        disposal_timestamp=disposal_timestamp,
    )


class TestEmitters:
    """Tests for the third-currency-fee unified-rule split (Tasks 1-3 RED).

    A third-currency fee (fee_currency not in (sent_currency, received_currency)
    with fee_value > 0) follows a unified two-model rule:

      * CEX model (leg-check, kept): ``fee_currency in (sent, received)`` -> no
        third-currency message at all.
      * DEX model (new native-gas check): ``fee_currency == native_gas_asset``
        of ``_derive_chain(wallet)`` -> demoted to ``logging.DEBUG`` (expected
        gas behavior, fee folded into ``AcquisitionContext.acq.fee_eur``).
      * Anomalous (fee in neither a leg nor native gas) or unknown chain ->
        STAYS ``logging.WARNING`` (Invariant #8 fail-safe).

    The ``native_gas_fee*`` tests below are RED drivers: today
    ``_emit_cross_asset_exchange`` (``_emitters.py:65``) and
    ``_emit_received_only_exchange`` (``_emitters.py:195``) ALWAYS emit the
    third-currency message at WARNING, so the DEBUG-positive / WARNING-negative
    pair fails pre-Task-3. The ``..._stays_warning`` and ``cex_leg_fee`` tests
    assert pre-existing behavior (regression guards) and pass now.
    """

    _LOGGER_NAME = "tax_reporting.application.crypto_fifo._emitters"
    _FEE_MSG_MARKER = "fee in third currency"

    @staticmethod
    def _eth_cross_asset_row() -> dict[str, str]:
        """Cross-asset exchange row on Ethereum paying gas in ETH.

        sent=FARMDWBTCV3, received=WBTC (both loan-affected), fee_currency=ETH
        (neither a leg), wallet "Ethereum (ETH)" so ``_derive_chain`` -> "Ethereum"
        and ``is_native_gas_fee`` -> True. ``fee_value > 0`` reaches the warning.
        """
        return {
            "Date": "2025-01-24 23:40:53 UTC",
            "Type": "exchange",
            "Tag": "",
            "Sending Wallet": "Ethereum (ETH)",
            "Receiving Wallet": "Ethereum (ETH)",
            "Sent Amount": "1.0",
            "Sent Currency": "FARMDWBTCV3",
            "Received Amount": "0.001",
            "Received Currency": "WBTC",
            "Fee Amount": "0.0025",
            "Fee Currency": "ETH",
            "Fee Value (EUR)": "0.65",
            "Sent Cost Basis": "10",
            "Net Value (EUR)": "10",
            "TxHash": "",
        }

    @staticmethod
    def _eth_received_only_row() -> dict[str, str]:
        """Received-only exchange row on Ethereum paying gas in ETH.

        sent=EUR (NOT loan-affected), received=WBTC (loan-affected), so the row
        routes to ``_emit_received_only_exchange``. fee_currency=ETH is neither
        a leg, wallet "Ethereum (ETH)" -> native gas.
        """
        return {
            "Date": "2025-01-24 23:40:53 UTC",
            "Type": "exchange",
            "Tag": "",
            "Sending Wallet": "Ethereum (ETH)",
            "Receiving Wallet": "Ethereum (ETH)",
            "Sent Amount": "100.0",
            "Sent Currency": "EUR",
            "Received Amount": "0.001",
            "Received Currency": "WBTC",
            "Fee Amount": "0.0025",
            "Fee Currency": "ETH",
            "Fee Value (EUR)": "0.65",
            "Sent Cost Basis": "100",
            "Net Value (EUR)": "100",
            "TxHash": "",
        }

    def test_native_gas_fee_cross_asset_logs_at_debug(self, caplog: pytest.LogCaptureFixture):
        """Given a cross-asset exchange on wallet "Ethereum (ETH)" with
        fee_currency="ETH" (native gas, fee_value > 0), expects the
        "fee in third currency ... deferred acquisition cost basis" message at
        ``logging.DEBUG`` (positive) and NOT at ``logging.WARNING`` (negative),
        as two separate emissions. Also asserts ``fee_eur`` on the resulting
        ``AcquisitionContext`` includes the fee value (data-unchanged regression).
        """
        from tax_reporting.application.crypto_fifo.parsing import (
            _classify_rows_for_loan_affected_assets,
        )

        rows = [self._eth_cross_asset_row()]
        loan_affected = frozenset({"FARMDWBTCV3", "WBTC"})

        # Positive: message present at DEBUG.
        with caplog.at_level(logging.DEBUG, logger=self._LOGGER_NAME):
            acquisitions, _consumptions, _, _ = _classify_rows_for_loan_affected_assets(
                rows, loan_affected_assets=loan_affected
            )
        debug_messages = [r.getMessage() for r in caplog.records]
        assert any(self._FEE_MSG_MARKER in m for m in debug_messages), (
            "native-gas third-currency fee must be reachable at DEBUG"
        )

        # Regression: the fee value is folded into the acquisition's fee_eur
        # regardless of the log level (data unchanged).
        wbtc_acqs = acquisitions.get("WBTC", [])
        assert wbtc_acqs, "cross-asset exchange must produce a WBTC acquisition"
        assert wbtc_acqs[0].acq.fee_eur == Decimal("0.65"), (
            f"fee_eur must include the 0.65 third-currency fee; got {wbtc_acqs[0].acq.fee_eur}"
        )

        # Negative: message NOT present at WARNING. Fresh caplog context, re-invoke
        # the emitter so the record is captured under the WARNING filter (Invariant #4).
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger=self._LOGGER_NAME):
            _classify_rows_for_loan_affected_assets(rows, loan_affected_assets=loan_affected)
        warning_messages = [r.getMessage() for r in caplog.records]
        assert not any(self._FEE_MSG_MARKER in m for m in warning_messages), (
            "native-gas third-currency fee must NOT appear at WARNING; "
            f"got {[m for m in warning_messages if self._FEE_MSG_MARKER in m]}"
        )

    def test_native_gas_fee_received_only_logs_at_debug(self, caplog: pytest.LogCaptureFixture):
        """Given a received-only exchange on wallet "Ethereum (ETH)" with
        fee_currency="ETH" (native gas), expects the third-currency message at
        DEBUG (positive) and NOT at WARNING (negative), plus fee_eur regression.
        """
        from tax_reporting.application.crypto_fifo.parsing import (
            _classify_rows_for_loan_affected_assets,
        )

        rows = [self._eth_received_only_row()]
        loan_affected = frozenset({"WBTC"})

        with caplog.at_level(logging.DEBUG, logger=self._LOGGER_NAME):
            acquisitions, _consumptions, _, _ = _classify_rows_for_loan_affected_assets(
                rows, loan_affected_assets=loan_affected
            )
        debug_messages = [r.getMessage() for r in caplog.records]
        assert any(self._FEE_MSG_MARKER in m for m in debug_messages), (
            "native-gas third-currency fee must be reachable at DEBUG (received-only)"
        )

        # Regression: fee folded into the WBTC acquisition's fee_eur.
        wbtc_acqs = acquisitions.get("WBTC", [])
        assert wbtc_acqs, "received-only exchange must produce a WBTC acquisition"
        assert wbtc_acqs[0].acq.fee_eur == Decimal("0.65"), (
            f"fee_eur must include the 0.65 third-currency fee; got {wbtc_acqs[0].acq.fee_eur}"
        )

        caplog.clear()
        with caplog.at_level(logging.WARNING, logger=self._LOGGER_NAME):
            _classify_rows_for_loan_affected_assets(rows, loan_affected_assets=loan_affected)
        warning_messages = [r.getMessage() for r in caplog.records]
        assert not any(self._FEE_MSG_MARKER in m for m in warning_messages), (
            "native-gas third-currency fee must NOT appear at WARNING (received-only); "
            f"got {[m for m in warning_messages if self._FEE_MSG_MARKER in m]}"
        )

    def test_anomalous_third_token_fee_cross_asset_stays_warning(self, caplog: pytest.LogCaptureFixture):
        """Given a cross-asset exchange on "Ethereum (ETH)" with fee_currency="USDC"
        (neither a leg nor native gas), expects the third-currency message STILL at
        ``logging.WARNING`` (genuinely-anomalous case is not silenced). Regression
        guard: asserts pre-existing behavior.
        """
        from tax_reporting.application.crypto_fifo.parsing import (
            _classify_rows_for_loan_affected_assets,
        )

        rows = [
            {
                "Date": "2025-01-24 23:40:53 UTC",
                "Type": "exchange",
                "Tag": "",
                "Sending Wallet": "Ethereum (ETH)",
                "Receiving Wallet": "Ethereum (ETH)",
                "Sent Amount": "1.0",
                "Sent Currency": "FARMDWBTCV3",
                "Received Amount": "0.001",
                "Received Currency": "WBTC",
                "Fee Amount": "1.0",
                "Fee Currency": "USDC",
                "Fee Value (EUR)": "0.65",
                "Sent Cost Basis": "10",
                "Net Value (EUR)": "10",
                "TxHash": "",
            }
        ]
        with caplog.at_level(logging.WARNING, logger=self._LOGGER_NAME):
            _classify_rows_for_loan_affected_assets(rows, loan_affected_assets=frozenset({"FARMDWBTCV3", "WBTC"}))
        warning_messages = [r.getMessage() for r in caplog.records]
        assert any(self._FEE_MSG_MARKER in m for m in warning_messages), (
            "anomalous third-token fee (USDC) MUST stay at WARNING"
        )

    def test_unknown_chain_third_token_fee_stays_warning(self, caplog: pytest.LogCaptureFixture):
        """Given an exchange on wallet "Some Unknown DEX" with a third-currency
        fee, expects WARNING (Invariant #8 fail-safe: unknown chain -> no native
        gas map entry -> STAYS WARNING). Regression guard.
        """
        from tax_reporting.application.crypto_fifo.parsing import (
            _classify_rows_for_loan_affected_assets,
        )

        rows = [
            {
                "Date": "2025-01-24 23:40:53 UTC",
                "Type": "exchange",
                "Tag": "",
                "Sending Wallet": "Some Unknown DEX",
                "Receiving Wallet": "Some Unknown DEX",
                "Sent Amount": "1.0",
                "Sent Currency": "FARMDWBTCV3",
                "Received Amount": "0.001",
                "Received Currency": "WBTC",
                "Fee Amount": "0.0025",
                "Fee Currency": "ETH",
                "Fee Value (EUR)": "0.65",
                "Sent Cost Basis": "10",
                "Net Value (EUR)": "10",
                "TxHash": "",
            }
        ]
        with caplog.at_level(logging.WARNING, logger=self._LOGGER_NAME):
            _classify_rows_for_loan_affected_assets(rows, loan_affected_assets=frozenset({"FARMDWBTCV3", "WBTC"}))
        warning_messages = [r.getMessage() for r in caplog.records]
        assert any(self._FEE_MSG_MARKER in m for m in warning_messages), (
            "third-currency fee on an unknown chain MUST stay at WARNING (fail-safe)"
        )

    def test_cex_leg_fee_no_warning(self, caplog: pytest.LogCaptureFixture):
        """Given a CEX exchange (wallet "ByBit") where fee_currency == received_currency
        (the existing leg-check), expects NO third-currency-fee message at all. The
        leg-check suppresses CEX fees; the native-gas check composes, does not replace.
        Regression guard: asserts pre-existing behavior (passes pre-Task-3).
        """
        from tax_reporting.application.crypto_fifo.parsing import (
            _classify_rows_for_loan_affected_assets,
        )

        rows = [
            {
                "Date": "2025-01-24 23:40:53 UTC",
                "Type": "exchange",
                "Tag": "",
                "Sending Wallet": "ByBit",
                "Receiving Wallet": "ByBit",
                "Sent Amount": "1.0",
                "Sent Currency": "USDT",
                "Received Amount": "0.001",
                "Received Currency": "WBTC",
                "Fee Amount": "0.0005",
                "Fee Currency": "WBTC",
                "Fee Value (EUR)": "0.65",
                "Sent Cost Basis": "10",
                "Net Value (EUR)": "10",
                "TxHash": "",
            }
        ]
        with caplog.at_level(logging.DEBUG, logger=self._LOGGER_NAME):
            _classify_rows_for_loan_affected_assets(rows, loan_affected_assets=frozenset({"USDT", "WBTC"}))
        messages = [r.getMessage() for r in caplog.records]
        assert not any(self._FEE_MSG_MARKER in m for m in messages), (
            "CEX leg fee (fee_currency == received_currency) must not emit the third-currency message at any level"
        )


class TestRemoveDerivativesFlaggedLots:
    """Tests for remove_derivatives_flagged_lots (Task 5).

    Two-phase matcher:
      Phase 1 - exact match on (timestamp, asset, wallet, amount_6dp) via a
                per-key deque (one lot consumed per derivatives_event).
      Phase 2 - contiguous-range sliding-window fallback for unmatched
                events, tolerance Decimal('0.00001') * range_size.

    Logging: per-lot removals at INFO; exactly one WARNING summary per call
    covering removals, surplus lots, and malformed-input lots.
    """

    _LOGGER_NAME = "tax_reporting.application.crypto.derivatives_filter"

    def test_exact_match_removes_single_cg_lot(self):
        """Given one lot whose (timestamp, asset, wallet, amount_6dp) key
        matches a derivatives_event, expects the lot to be removed via
        exact match.
        """
        from tax_reporting.application.crypto.derivatives_filter import (
            DerivativesThEvent,
            remove_derivatives_flagged_lots,
        )

        lots = [
            _make_cg_lot(
                disposal_timestamp="2025-01-24 20:00",
                amount=Decimal("0.08838575"),
            )
        ]
        events = [
            DerivativesThEvent(
                timestamp="2025-01-24 20:00",
                asset="USDT",
                wallet="ByBit",
                amount=Decimal("0.08838575"),
                label="Funding fee",
            )
        ]

        filtered, count = remove_derivatives_flagged_lots(lots, events)

        assert count == 1
        assert filtered == []

    def test_keeps_non_matching_cg_lot(self):
        """Given a CG lot whose key has no matching derivatives_event, expects
        the lot to be retained.
        """
        from tax_reporting.application.crypto.derivatives_filter import (
            DerivativesThEvent,
            remove_derivatives_flagged_lots,
        )

        lots = [
            _make_cg_lot(
                disposal_timestamp="2025-01-13 03:45",
                amount=Decimal("108.335"),
            )
        ]
        events = [
            DerivativesThEvent(
                timestamp="2025-01-24 20:00",
                asset="USDT",
                wallet="ByBit",
                amount=Decimal("0.08838575"),
                label="Funding fee",
            )
        ]

        filtered, count = remove_derivatives_flagged_lots(lots, events)

        assert count == 0
        assert filtered == lots

    def test_amount_rounding_to_6_decimals_absorbs_koinly_drift(self):
        """Given a CG lot at 0.08838575 and an event at 0.08838580 (delta in
        the 8th decimal), expects the lot to be removed (both round to
        0.088386 at 6 decimals, exact match succeeds).
        """
        from tax_reporting.application.crypto.derivatives_filter import (
            DerivativesThEvent,
            remove_derivatives_flagged_lots,
        )

        lots = [
            _make_cg_lot(
                disposal_timestamp="2025-01-24 20:00",
                amount=Decimal("0.08838575"),
            )
        ]
        events = [
            DerivativesThEvent(
                timestamp="2025-01-24 20:00",
                asset="USDT",
                wallet="ByBit",
                amount=Decimal("0.08838580"),
                label="Funding fee",
            )
        ]

        filtered, count = remove_derivatives_flagged_lots(lots, events)

        assert count == 1
        assert filtered == []

    def test_contiguous_range_fallback_removes_fifo_split_lots(self):
        """Given one event at amount=120.0 and two contiguous lots at
        [70.0, 50.0] (no single lot matches), expects the contiguous-range
        fallback to find range {70.0, 50.0} (sum=120.0) and remove both.
        """
        from tax_reporting.application.crypto.derivatives_filter import (
            DerivativesThEvent,
            remove_derivatives_flagged_lots,
        )

        lots = [
            _make_cg_lot(
                disposal_timestamp="2025-01-24 23:40",
                amount=Decimal("70.0"),
                acquisition_date="2025-01-10",
            ),
            _make_cg_lot(
                disposal_timestamp="2025-01-24 23:40",
                amount=Decimal("50.0"),
                acquisition_date="2025-01-12",
            ),
        ]
        events = [
            DerivativesThEvent(
                timestamp="2025-01-24 23:40",
                asset="USDT",
                wallet="ByBit",
                amount=Decimal("120.0"),
                label="Realized gain",
            )
        ]

        filtered, count = remove_derivatives_flagged_lots(lots, events)

        assert count == 2
        assert filtered == []

    def test_contiguous_range_fallback_prefers_first_range(self):
        """Given an event at amount=70.0 and lots [70.0, 50.0, 20.0], expects
        the exact-match phase to remove the single 70.0 lot before the
        contiguous-range fallback runs (so the other lots are retained).
        """
        from tax_reporting.application.crypto.derivatives_filter import (
            DerivativesThEvent,
            remove_derivatives_flagged_lots,
        )

        lots = [
            _make_cg_lot(
                disposal_timestamp="2025-01-24 23:40",
                amount=Decimal("70.0"),
                acquisition_date="2025-01-10",
            ),
            _make_cg_lot(
                disposal_timestamp="2025-01-24 23:40",
                amount=Decimal("50.0"),
                acquisition_date="2025-01-12",
            ),
            _make_cg_lot(
                disposal_timestamp="2025-01-24 23:40",
                amount=Decimal("20.0"),
                acquisition_date="2025-01-14",
            ),
        ]
        events = [
            DerivativesThEvent(
                timestamp="2025-01-24 23:40",
                asset="USDT",
                wallet="ByBit",
                amount=Decimal("70.0"),
                label="Realized gain",
            )
        ]

        filtered, count = remove_derivatives_flagged_lots(lots, events)

        assert count == 1
        # The 70.0 lot was removed; the remaining two lots stay.
        remaining_amounts = sorted(e.amount for e in filtered)
        assert remaining_amounts == [Decimal("20.0"), Decimal("50.0")]

    def test_range_tolerance_absorbs_rounding_accumulation(self):
        """Given an event at amount=100.0 and lots
        [33.333333, 33.333333, 33.333334] (sum=99.999999, delta=0.000001
        within tolerance for range_size=3), expects all 3 lots removed.
        """
        from tax_reporting.application.crypto.derivatives_filter import (
            DerivativesThEvent,
            remove_derivatives_flagged_lots,
        )

        lots = [
            _make_cg_lot(
                disposal_timestamp="2025-01-24 23:40",
                amount=Decimal("33.333333"),
                acquisition_date="2025-01-10",
            ),
            _make_cg_lot(
                disposal_timestamp="2025-01-24 23:40",
                amount=Decimal("33.333333"),
                acquisition_date="2025-01-11",
            ),
            _make_cg_lot(
                disposal_timestamp="2025-01-24 23:40",
                amount=Decimal("33.333334"),
                acquisition_date="2025-01-12",
            ),
        ]
        events = [
            DerivativesThEvent(
                timestamp="2025-01-24 23:40",
                asset="USDT",
                wallet="ByBit",
                amount=Decimal("100.0"),
                label="Realized gain",
            )
        ]

        filtered, count = remove_derivatives_flagged_lots(lots, events)

        assert count == 3
        assert filtered == []

    def test_range_mismatch_keeps_lots(self):
        """Given an event at amount=100.0 and lots [70.0, 50.0] (sum=120.0,
        not within tolerance of 100.0), expects no lots removed.
        """
        from tax_reporting.application.crypto.derivatives_filter import (
            DerivativesThEvent,
            remove_derivatives_flagged_lots,
        )

        lots = [
            _make_cg_lot(
                disposal_timestamp="2025-01-24 23:40",
                amount=Decimal("70.0"),
                acquisition_date="2025-01-10",
            ),
            _make_cg_lot(
                disposal_timestamp="2025-01-24 23:40",
                amount=Decimal("50.0"),
                acquisition_date="2025-01-12",
            ),
        ]
        events = [
            DerivativesThEvent(
                timestamp="2025-01-24 23:40",
                asset="USDT",
                wallet="ByBit",
                amount=Decimal("100.0"),
                label="Realized gain",
            )
        ]

        filtered, count = remove_derivatives_flagged_lots(lots, events)

        assert count == 0
        assert len(filtered) == 2

    def test_non_contiguous_lots_do_not_match(self):
        """Given an event at amount=120.0 and lots sorted by acquisition_date
        as [70.0, 30.0, 50.0] (lots 70.0 and 50.0 are NOT adjacent, 30.0 sits
        between them), expects NO match. This is the critical test that
        prevents false-positive matches on coincidental non-contiguous subsets
        (addresses the 142.113 USDT Realized-gain case in Case 2).
        """
        from tax_reporting.application.crypto.derivatives_filter import (
            DerivativesThEvent,
            remove_derivatives_flagged_lots,
        )

        lots = [
            _make_cg_lot(
                disposal_timestamp="2025-01-24 23:40",
                amount=Decimal("70.0"),
                acquisition_date="2025-01-10",
            ),
            _make_cg_lot(
                disposal_timestamp="2025-01-24 23:40",
                amount=Decimal("30.0"),
                acquisition_date="2025-01-11",
            ),
            _make_cg_lot(
                disposal_timestamp="2025-01-24 23:40",
                amount=Decimal("50.0"),
                acquisition_date="2025-01-12",
            ),
        ]
        events = [
            DerivativesThEvent(
                timestamp="2025-01-24 23:40",
                asset="USDT",
                wallet="ByBit",
                amount=Decimal("120.0"),
                label="Realized gain",
            )
        ]

        filtered, count = remove_derivatives_flagged_lots(lots, events)

        assert count == 0
        assert len(filtered) == 3

    def test_multiple_th_events_at_same_timestamp_consumed_in_order(
        self, caplog: pytest.LogCaptureFixture
    ):
        """Given 2 derivatives_events at (2025-01-24 08:00, USDT, ByBit, 0.5)
        and 2 CG lots at the same key, expects both events to consume one
        lot each (deterministic deque order by acquisition_date). count=2,
        and the summary WARNING's "surplus lots" section is empty (no
        collision).
        """
        from tax_reporting.application.crypto.derivatives_filter import (
            DerivativesThEvent,
            remove_derivatives_flagged_lots,
        )

        lots = [
            _make_cg_lot(
                disposal_timestamp="2025-01-24 08:00",
                amount=Decimal("0.5"),
                acquisition_date="2025-01-10",
            ),
            _make_cg_lot(
                disposal_timestamp="2025-01-24 08:00",
                amount=Decimal("0.5"),
                acquisition_date="2025-01-12",
            ),
        ]
        events = [
            DerivativesThEvent(
                timestamp="2025-01-24 08:00",
                asset="USDT",
                wallet="ByBit",
                amount=Decimal("0.5"),
                label="Funding fee",
            ),
            DerivativesThEvent(
                timestamp="2025-01-24 08:00",
                asset="USDT",
                wallet="ByBit",
                amount=Decimal("0.5"),
                label="Funding fee",
            ),
        ]

        with caplog.at_level(logging.INFO, logger=self._LOGGER_NAME):
            filtered, count = remove_derivatives_flagged_lots(lots, events)

        assert count == 2
        assert filtered == []
        # Exactly one summary INFO (demoted from WARNING), and its "surplus
        # lots" section is empty.
        summary_records = [
            r
            for r in caplog.records
            if r.levelno == logging.INFO and "dedup summary" in r.getMessage()
        ]
        assert len(summary_records) == 1
        summary_message = summary_records[0].getMessage()
        assert "surplus" in summary_message.lower()
        # Surplus section present but showing zero count (no collision).
        assert "0 surplus" in summary_message

    def test_empty_deque_falls_to_range_fallback(self):
        """Given a derivatives_event at amount=0.5 whose exact-match key deque
        is empty (drained by prior events), expects the event to fall through
        to the contiguous-range fallback; if the fallback also finds no match,
        the event is marked unmatched.
        """
        from tax_reporting.application.crypto.derivatives_filter import (
            DerivativesThEvent,
            remove_derivatives_flagged_lots,
        )

        lots = [
            _make_cg_lot(
                disposal_timestamp="2025-01-24 08:00",
                amount=Decimal("0.5"),
                acquisition_date="2025-01-10",
            ),
            _make_cg_lot(
                disposal_timestamp="2025-01-24 08:00",
                amount=Decimal("0.2"),
                acquisition_date="2025-01-12",
            ),
            _make_cg_lot(
                disposal_timestamp="2025-01-24 08:00",
                amount=Decimal("0.3"),
                acquisition_date="2025-01-14",
            ),
        ]
        events = [
            # First event: exact-match consumes the 0.5 lot.
            DerivativesThEvent(
                timestamp="2025-01-24 08:00",
                asset="USDT",
                wallet="ByBit",
                amount=Decimal("0.5"),
                label="Funding fee",
            ),
            # Second event: exact-match key deque is empty (0.5 lot consumed);
            # contiguous-range fallback must find [0.2, 0.3]=0.5.
            DerivativesThEvent(
                timestamp="2025-01-24 08:00",
                asset="USDT",
                wallet="ByBit",
                amount=Decimal("0.5"),
                label="Funding fee",
            ),
        ]

        filtered, count = remove_derivatives_flagged_lots(lots, events)

        assert count == 3
        assert filtered == []

    def test_exact_match_collision_aggregated_in_summary(
        self, caplog: pytest.LogCaptureFixture
    ):
        """Given 1 derivatives_event at amount=0.5 and 3 CG lots at
        (2025-01-24 08:00, USDT, ByBit, 0.5), expects 1 lot removed (exact
        match, first in deque), 2 lots remaining, and the summary WARNING to
        include a "surplus lots" section naming count=2, total amount=1.0
        USDT, and a sample of up to 3 (timestamp, asset, wallet, amount)
        tuples. No per-lot WARNING is emitted.
        """
        from tax_reporting.application.crypto.derivatives_filter import (
            DerivativesThEvent,
            remove_derivatives_flagged_lots,
        )

        lots = [
            _make_cg_lot(
                disposal_timestamp="2025-01-24 08:00",
                amount=Decimal("0.5"),
                acquisition_date="2025-01-10",
            ),
            _make_cg_lot(
                disposal_timestamp="2025-01-24 08:00",
                amount=Decimal("0.5"),
                acquisition_date="2025-01-12",
            ),
            _make_cg_lot(
                disposal_timestamp="2025-01-24 08:00",
                amount=Decimal("0.5"),
                acquisition_date="2025-01-14",
            ),
        ]
        events = [
            DerivativesThEvent(
                timestamp="2025-01-24 08:00",
                asset="USDT",
                wallet="ByBit",
                amount=Decimal("0.5"),
                label="Funding fee",
            )
        ]

        with caplog.at_level(logging.INFO, logger=self._LOGGER_NAME):
            filtered, count = remove_derivatives_flagged_lots(lots, events)

        assert count == 1
        assert len(filtered) == 2

        # Exactly one summary INFO (demoted from WARNING); no per-lot WARNING lines.
        summary_records = [
            r
            for r in caplog.records
            if r.levelno == logging.INFO and "dedup summary" in r.getMessage()
        ]
        assert len(summary_records) == 1
        summary_message = summary_records[0].getMessage()
        # Surplus section reports count=2 and total amount=1.0.
        assert "2 surplus" in summary_message
        assert "1.0" in summary_message or "1,0" in summary_message

    def test_per_lot_removal_logged_at_info(
        self, caplog: pytest.LogCaptureFixture
    ):
        """Given a removal scenario, expects each removed lot to log at INFO
        level (not WARNING) with timestamp, asset, wallet, amount, match type,
        and matching TH Label.
        """
        from tax_reporting.application.crypto.derivatives_filter import (
            DerivativesThEvent,
            remove_derivatives_flagged_lots,
        )

        lots = [
            _make_cg_lot(
                disposal_timestamp="2025-01-24 20:00",
                amount=Decimal("0.08838575"),
            )
        ]
        events = [
            DerivativesThEvent(
                timestamp="2025-01-24 20:00",
                asset="USDT",
                wallet="ByBit",
                amount=Decimal("0.08838575"),
                label="Funding fee",
            )
        ]

        with caplog.at_level(logging.INFO, logger=self._LOGGER_NAME):
            remove_derivatives_flagged_lots(lots, events)

        info_records = [
            r
            for r in caplog.records
            if r.levelno == logging.INFO
            and "removed" in r.getMessage().lower()
        ]
        assert len(info_records) >= 1
        info_text = " ".join(r.getMessage() for r in info_records)
        assert "exact" in info_text.lower()
        assert "Funding fee" in info_text
        assert "USDT" in info_text
        assert "ByBit" in info_text
        assert "2025-01-24 20:00" in info_text

    def test_summary_logged_at_info_once(
        self, caplog: pytest.LogCaptureFixture
    ):
        """Given a removal scenario removing N lots, expects exactly one
        INFO summary log (demoted from WARNING) summarizing removals (total
        count, exact count, range count, aggregate proceeds, aggregate gain
        removed); surplus lots; and malformed-input lots. The summary is the
        ONLY dedup-summary record emitted (per-lot removal INFOs are separate).
        """
        from tax_reporting.application.crypto.derivatives_filter import (
            DerivativesThEvent,
            remove_derivatives_flagged_lots,
        )

        lots = [
            _make_cg_lot(
                disposal_timestamp="2025-01-24 20:00",
                amount=Decimal("0.08838575"),
                proceeds_eur=Decimal("0.08"),
                gain_loss_eur=Decimal("0.04"),
            )
        ]
        events = [
            DerivativesThEvent(
                timestamp="2025-01-24 20:00",
                asset="USDT",
                wallet="ByBit",
                amount=Decimal("0.08838575"),
                label="Funding fee",
            )
        ]

        with caplog.at_level(logging.INFO, logger=self._LOGGER_NAME):
            remove_derivatives_flagged_lots(lots, events)

        summary_records = [
            r
            for r in caplog.records
            if r.levelno == logging.INFO and "dedup summary" in r.getMessage()
        ]
        assert len(summary_records) == 1
        summary = summary_records[0].getMessage()
        # Removal counts: 1 total, 1 exact, 0 range.
        assert "1" in summary  # at least the total count
        # Sections present.
        assert "surplus" in summary.lower()
        assert "malformed" in summary.lower()

    def test_malformed_input_lots_aggregated_in_summary(
        self, caplog: pytest.LogCaptureFixture
    ):
        """Given 2 CG lots with amount <= 0 (0 and -0.5), expects both to be
        skipped from matching, collected into the summary WARNING's
        "malformed-input lots" section (count=2, sample includes both
        (timestamp, asset, amount) tuples), and no per-lot WARNING emitted.
        """
        from tax_reporting.application.crypto.derivatives_filter import (
            DerivativesThEvent,
            remove_derivatives_flagged_lots,
        )

        lots = [
            _make_cg_lot(
                disposal_timestamp="2025-01-24 08:00",
                amount=Decimal("0"),
            ),
            _make_cg_lot(
                disposal_timestamp="2025-01-24 09:00",
                amount=Decimal("-0.5"),
            ),
        ]
        events = [
            DerivativesThEvent(
                timestamp="2025-01-24 08:00",
                asset="USDT",
                wallet="ByBit",
                amount=Decimal("0.5"),
                label="Funding fee",
            )
        ]

        with caplog.at_level(logging.INFO, logger=self._LOGGER_NAME):
            filtered, count = remove_derivatives_flagged_lots(lots, events)

        assert count == 0
        assert len(filtered) == 2

        summary_records = [
            r
            for r in caplog.records
            if r.levelno == logging.INFO and "dedup summary" in r.getMessage()
        ]
        assert len(summary_records) == 1
        summary = summary_records[0].getMessage()
        assert "2 malformed" in summary

    def test_range_match_does_not_trigger_collision_warning(
        self, caplog: pytest.LogCaptureFixture
    ):
        """Given 1 derivatives_event at amount=120.0 and 2 contiguous CG lots
        at amounts [70.0, 50.0] (range-matched, not exact-matched), expects
        the summary WARNING's "surplus lots" section to be empty (the warning
        is reserved for same-key exact-match collisions only).
        """
        from tax_reporting.application.crypto.derivatives_filter import (
            DerivativesThEvent,
            remove_derivatives_flagged_lots,
        )

        lots = [
            _make_cg_lot(
                disposal_timestamp="2025-01-24 23:40",
                amount=Decimal("70.0"),
                acquisition_date="2025-01-10",
            ),
            _make_cg_lot(
                disposal_timestamp="2025-01-24 23:40",
                amount=Decimal("50.0"),
                acquisition_date="2025-01-12",
            ),
        ]
        events = [
            DerivativesThEvent(
                timestamp="2025-01-24 23:40",
                asset="USDT",
                wallet="ByBit",
                amount=Decimal("120.0"),
                label="Realized gain",
            )
        ]

        with caplog.at_level(logging.INFO, logger=self._LOGGER_NAME):
            remove_derivatives_flagged_lots(lots, events)

        summary_records = [
            r
            for r in caplog.records
            if r.levelno == logging.INFO and "dedup summary" in r.getMessage()
        ]
        assert len(summary_records) == 1
        summary = summary_records[0].getMessage()
        assert "0 surplus" in summary

    def test_empty_derivatives_events_returns_input_unchanged(
        self, caplog: pytest.LogCaptureFixture
    ):
        """Given capital_entries and an empty derivatives_events list, expects
        the function to return the input list unchanged with count 0 and no
        summary WARNING.
        """
        from tax_reporting.application.crypto.derivatives_filter import (
            remove_derivatives_flagged_lots,
        )

        lots = [
            _make_cg_lot(
                disposal_timestamp="2025-01-24 20:00",
                amount=Decimal("0.08838575"),
            )
        ]

        with caplog.at_level(logging.INFO, logger=self._LOGGER_NAME):
            filtered, count = remove_derivatives_flagged_lots(lots, [])

        assert count == 0
        assert filtered is lots  # unchanged identity, no copy
        warning_records = [
            r for r in caplog.records if r.levelno == logging.WARNING
        ]
        assert warning_records == []

    def test_performance_at_scale(self):
        """Given 10,000 CG lots (9,000 non-derivatives at 100 distinct
        timestamps with 90 lots each, 1,000 derivatives-flagged across 100
        timestamps with 10 lots each) and 1,000 derivatives_events, expects
        the function to complete in under 2 seconds.
        """
        from tax_reporting.application.crypto.derivatives_filter import (
            DerivativesThEvent,
            remove_derivatives_flagged_lots,
        )

        lots: list[CryptoCapitalGainEntry] = []
        events: list[DerivativesThEvent] = []

        # 9,000 non-derivatives: 100 timestamps x 90 lots each.
        for ts_idx in range(100):
            hour = ts_idx % 24
            timestamp = f"2025-01-{(ts_idx % 28) + 1:02d} {hour:02d}:00"
            for lot_idx in range(90):
                lots.append(
                    _make_cg_lot(
                        disposal_timestamp=timestamp,
                        amount=Decimal("0.5"),
                        acquisition_date=f"2024-12-{(lot_idx % 28) + 1:02d}",
                    )
                )

        # 1,000 derivatives-flagged lots: 100 timestamps x 10 lots each.
        # Each derivatives_event matches exactly one lot via exact match.
        for ts_idx in range(100):
            hour = ts_idx % 24
            timestamp = f"2025-02-{(ts_idx % 28) + 1:02d} {hour:02d}:00"
            for _ in range(10):
                lots.append(
                    _make_cg_lot(
                        disposal_timestamp=timestamp,
                        amount=Decimal("0.5"),
                    )
                )
            for _ in range(10):
                events.append(
                    DerivativesThEvent(
                        timestamp=timestamp,
                        asset="USDT",
                        wallet="ByBit",
                        amount=Decimal("0.5"),
                        label="Funding fee",
                    )
                )

        start = time.perf_counter()
        _, count = remove_derivatives_flagged_lots(lots, events)
        elapsed = time.perf_counter() - start

        assert count == 1000
        assert elapsed < 2.0, f"Expected <2.0s, took {elapsed:.3f}s"

    def test_performance_worst_case_single_event_many_lots(self):
        """Given 1 derivatives_event and 500 CG lots at the same
        (timestamp, asset, wallet) (none matching exactly, contiguous-range
        fallback must scan all 500), expects the function to complete in
        under 500 milliseconds (O(N) sliding window, not exponential).
        """
        from tax_reporting.application.crypto.derivatives_filter import (
            DerivativesThEvent,
            remove_derivatives_flagged_lots,
        )

        # 500 lots, each amount=1.0 - no exact match for amount=999.0.
        # The sliding window scans all 500 in O(N) time without finding a match.
        lots = [
            _make_cg_lot(
                disposal_timestamp="2025-01-24 23:40",
                amount=Decimal("1.0"),
                acquisition_date=f"2024-12-{(i % 28) + 1:02d}",
            )
            for i in range(500)
        ]
        events = [
            DerivativesThEvent(
                timestamp="2025-01-24 23:40",
                asset="USDT",
                wallet="ByBit",
                amount=Decimal("999.0"),
                label="Realized gain",
            )
        ]

        start = time.perf_counter()
        _, count = remove_derivatives_flagged_lots(lots, events)
        elapsed = time.perf_counter() - start

        assert count == 0
        assert elapsed < 0.5, f"Expected <0.5s, took {elapsed:.3f}s"


_DERIVATIVES_CLOSE_DIR = Path(
    "resources/source/example/2025/koinly/derivatives_close"
)


def _scenario_th_csv() -> Path:
    """Path to the ``derivatives_close`` TH fixture (committed)."""
    return _DERIVATIVES_CLOSE_DIR / "koinly_2025_transaction_history.csv"


def _treatment_config_for_year(year: int):
    """Build a TreatmentConfig with the production derivatives labels injected."""
    from tax_reporting.application.crypto.derivatives_filter import (
        _load_derivatives_labels_config,
    )
    from tax_reporting.application.crypto.treatment_resolver import TreatmentConfig

    return TreatmentConfig(
        derivatives_tags=_load_derivatives_labels_config("koinly", year),
    )


def _make_derivatives_jurisdiction():
    """Build a TaxJurisdictionConfig that opens the derivatives dedup gate."""
    from tax_reporting.infrastructure.config import TaxJurisdictionConfig

    return TaxJurisdictionConfig(
        country="TEST",
        fiscal_year=2025,
        exclude_loan_repayment_gains=False,
        zero_basis_review_threshold=Decimal("500"),
        use_other_gains_report=True,
        separate_derivatives_reporting=True,
        infer_payment_proceeds=False,
    )


@pytest.mark.unit
class TestDerivativesFilter:
    """Phase E Task 2 characterization tests for the renamed module.

    Pins three properties that must survive the rename + legacy-scanner
    deletion + B3 labels-presence-gate refactor:
      1. The resolver-driven event builder still produces one
         :class:`DerivativesThEvent` per matched transaction.
      2. The module logger name is now
         ``tax_reporting.application.crypto.derivatives_filter``.
      3. The empty-tags WARNING still fires when
         :class:`TreatmentConfig.derivatives_tags` is empty (it no longer
         re-loads via ``_load_derivatives_labels_config`` inside
         :func:`apply_derivatives_dedup`).
    """

    _LOGGER_NAME = "tax_reporting.application.crypto.derivatives_filter"

    def test_resolver_path_produces_derivatives_events(self) -> None:
        """Given a ``list[Transaction]`` whose treatment is ``DERIVATIVES_CLOSE``,
        :func:`find_derivatives_th_events_from_transactions` returns one
        :class:`DerivativesThEvent` per matched transaction.

        The committed ``derivatives_close`` fixture has 2 TH rows; only the
        ``crypto_withdrawal`` row passes the Type guard and emits an event
        (the ``crypto_exchange`` row is correctly skipped - non-withdrawal
        rows carry no asset movement the matcher could pair with a CG lot).
        """
        from tax_reporting.application.crypto.derivatives_filter import (
            DerivativesThEvent,
            find_derivatives_th_events_from_transactions,
        )

        transactions = build_transactions_from_th(_scenario_th_csv())
        assert len(transactions) == 2, (
            "derivatives_close scenario drifted: expected 2 TH rows"
        )
        config = _treatment_config_for_year(2025)

        events = find_derivatives_th_events_from_transactions(transactions, config)

        # Exactly one event (the crypto_withdrawal row); the crypto_exchange
        # row is filtered by the ``_DERIVATIVES_TH_TYPE`` Type guard.
        assert len(events) == 1, (
            f"expected 1 event from 1 crypto_withdrawal tx; got {len(events)}"
        )
        event = events[0]
        assert isinstance(event, DerivativesThEvent)
        assert event.label == "Realized gain"
        assert event.wallet == "ByBit"

    def test_logger_name_after_rename(self, caplog: pytest.LogCaptureFixture) -> None:
        """Given a derivatives-flagged CG lot matched and removed, the INFO/WARNING
        records emit from logger ``tax_reporting.application.crypto.derivatives_filter``
        (NOT ``...derivatives_dedup``).
        """
        from tax_reporting.application.crypto.derivatives_filter import (
            DerivativesThEvent,
            remove_derivatives_flagged_lots,
        )

        lots = [
            _make_cg_lot(
                disposal_timestamp="2025-01-24 20:00",
                amount=Decimal("0.08838575"),
            )
        ]
        events = [
            DerivativesThEvent(
                timestamp="2025-01-24 20:00",
                asset="USDT",
                wallet="ByBit",
                amount=Decimal("0.08838575"),
                label="Funding fee",
            )
        ]

        with caplog.at_level(logging.INFO, logger=self._LOGGER_NAME):
            filtered, removed = remove_derivatives_flagged_lots(lots, events)

        assert removed == 1
        assert filtered == []
        record_names = {r.name for r in caplog.records}
        assert self._LOGGER_NAME in record_names, (
            f"expected logger name {self._LOGGER_NAME!r}; got {record_names}"
        )
        assert "tax_reporting.application.crypto.derivatives_dedup" not in record_names, (
            "old logger name 'derivatives_dedup' must not emit after rename"
        )

    def test_empty_derivatives_tags_warns_via_injected_config(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Given ``TreatmentConfig(derivatives_tags=frozenset())`` injected into
        :func:`apply_derivatives_dedup`, the empty-tags WARNING fires and the
        input is returned unchanged.

        Pins the B3 refactor: the labels-presence gate now reads
        ``config.derivatives_tags`` (already injected), not a re-load via
        ``_load_derivatives_labels_config``.
        """
        from tax_reporting.application.crypto.derivatives_filter import (
            apply_derivatives_dedup,
        )
        from tax_reporting.application.crypto.treatment_resolver import (
            TreatmentConfig,
        )

        lots = [
            _make_cg_lot(
                disposal_timestamp="2025-01-24 20:00",
                amount=Decimal("0.08838575"),
            )
        ]
        th_file = tmp_path / "th.csv"
        th_file.write_text("Transaction report 2025\n\nDate,Type,Tag\n")

        with caplog.at_level(logging.WARNING, logger=self._LOGGER_NAME):
            result = apply_derivatives_dedup(
                capital_entries=lots,
                jurisdiction=_make_derivatives_jurisdiction(),
                transaction_history_file=th_file,
                transactions=[],
                config=TreatmentConfig(derivatives_tags=frozenset()),
            )

        assert result is lots, (
            "empty-tags path must return the input list unchanged"
        )
        warning_records = [
            r for r in caplog.records if r.levelno >= logging.WARNING
        ]
        assert any(
            "Derivatives tags empty" in r.getMessage() for r in warning_records
        ), (
            f"expected empty-tags WARNING; got messages={[r.getMessage() for r in warning_records]}"
        )

    def test_derivatives_dedup_removed_count_set_on_decision_counts(
        self, tmp_path: Path
    ) -> None:
        """Given 3 removed lots threaded through ``apply_derivatives_dedup``
        with a ``CryptoDecisionCounts`` instance, expects
        ``decision_counts.derivatives_dedup_removed == 3`` (set once, not
        incremented).
        """
        from tax_reporting.application.crypto.derivatives_filter import (
            apply_derivatives_dedup,
        )
        from tax_reporting.application.crypto.entities import CryptoDecisionCounts
        from tax_reporting.application.crypto.treatment_resolver import (
            TreatmentConfig,
        )
        from tax_reporting.application.crypto_reporting import build_transactions_from_th

        # 3 CG lots each exactly matching one derivatives event.
        lots = [
            _make_cg_lot(
                disposal_timestamp=f"2025-01-24 0{i}:00",
                amount=Decimal("0.5"),
            )
            for i in range(3)
        ]

        # 3 crypto_withdrawal TH rows tagged "Realized gain" at the matching
        # (timestamp, asset, wallet, amount) keys -> 3 derivatives events.
        th_csv = tmp_path / "th.csv"
        th_csv.write_text(
            "Transaction report 2025\n\n"
            "Date,Type,Tag,Sending Wallet,Sent Amount,Sent Currency,"
            "Receiving Wallet,Received Amount,Received Currency,Net Value (EUR)\n"
            + "\n".join(
                f"2025-01-24 0{i}:00:00 UTC,crypto_withdrawal,Realized gain,"
                f"ByBit,\"0,5\",USDT,,,\"5,00\""
                for i in range(3)
            ),
            encoding="utf-8",
        )
        transactions = build_transactions_from_th(th_csv)
        assert len(transactions) == 3, (
            f"expected 3 TH rows parsed; got {len(transactions)}"
        )

        decision_counts = CryptoDecisionCounts()

        apply_derivatives_dedup(
            capital_entries=lots,
            jurisdiction=_make_derivatives_jurisdiction(),
            transaction_history_file=th_csv,
            transactions=transactions,
            config=TreatmentConfig(derivatives_tags=frozenset({"Realized gain"})),
            review_entries=None,
            decision_counts=decision_counts,
        )

        assert decision_counts.derivatives_dedup_removed == 3, (
            f"expected derivatives_dedup_removed == 3; "
            f"got {decision_counts.derivatives_dedup_removed}"
        )

