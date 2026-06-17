"""Unit tests for crypto derivatives CG/TH deduplication loader.

These tests follow the TDD RED -> GREEN -> refactor cycle. They cover the
per-provider-per-year label config loader used to identify derivatives TH
events that should be removed from the capital-gains report.
"""

from __future__ import annotations

import csv
import dataclasses
import io
import json
import logging
import time
from decimal import Decimal
from pathlib import Path

import pytest

from tax_reporting.application.crypto.entities import CryptoCapitalGainEntry
from tax_reporting.application.crypto.operator_origin import OperatorOrigin
from tax_reporting.domain.exceptions import FileProcessingError


class TestDerivativesLabelsConfig:
    """Tests for _load_derivatives_labels_config and its _from_path helper."""

    def test_loads_koinly_2025_labels(self):
        """Given docs/tax/derivatives_labels/koinly_2025.json with the canonical
        label list, expects the loader to return the frozenset of those labels.
        """
        from tax_reporting.application.crypto.derivatives_dedup import (
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
        from tax_reporting.application.crypto.derivatives_dedup import (
            _load_derivatives_labels_config_from_path,
        )

        missing = tmp_path / "absent_2099.json"
        with caplog.at_level(logging.WARNING, logger="tax_reporting.application.crypto.derivatives_dedup"):
            result = _load_derivatives_labels_config_from_path(missing)

        assert result == frozenset()
        assert not any(
            record.levelno >= logging.WARNING for record in caplog.records
        ), "Loader must not warn for missing file; apply_derivatives_dedup owns that warning"

    def test_malformed_json_raises(self, tmp_path: Path):
        """Given a config file with invalid JSON, expects FileProcessingError
        with the file path and parse error message.
        """
        from tax_reporting.application.crypto.derivatives_dedup import (
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
        from tax_reporting.application.crypto.derivatives_dedup import (
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
        from tax_reporting.application.crypto.derivatives_dedup import (
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
        from tax_reporting.application.crypto.derivatives_dedup import (
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
        from tax_reporting.application.crypto.derivatives_dedup import (
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
        from tax_reporting.application.crypto.derivatives_dedup import (
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

        from tax_reporting.application.crypto_reporting import TokenOriginResolver

        context = CapitalGainsParsingContext(
            skipped_assets={},
            origin_resolver=TokenOriginResolver(),
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


def _write_th_csv(path: Path, rows: list[dict[str, str]]) -> None:
    """Write a Koinly transaction-history-shaped CSV file to ``path``.

    Mirrors the real TH export preamble (line 1 = title, line 2 = blank,
    line 3 = header) so that ``read_koinly_rows`` detects the header via
    ``_detect_header_index``. Each row is a dict keyed by TH column name.
    """
    fieldnames = [
        "Date",
        "Type",
        "Tag",
        "Sending Wallet",
        "Sent Amount",
        "Sent Currency",
        "Sent Cost Basis",
        "Receiving Wallet",
        "Received Amount",
        "Received Currency",
        "Received Cost Basis",
        "Fee Amount",
        "Fee Currency",
        "Gain (EUR)",
        "Net Value (EUR)",
        "Fee Value (EUR)",
        "TxSrc",
        "TxDest",
        "TxHash",
        "Description",
    ]

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        full_row = {key: row.get(key, "") for key in fieldnames}
        writer.writerow(full_row)

    data_rows = buffer.getvalue().splitlines()
    lines = ["Transaction report 2025", "", *data_rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class TestDerivativesThScanner:
    """Tests for find_derivatives_th_events (Task 4).

    The scanner reads a TH CSV via ``read_koinly_rows`` and returns one
    ``DerivativesThEvent`` per ``crypto_withdrawal`` row whose Label is in
    the provided ``labels`` set. Each event carries a minute-precision
    timestamp so the matcher can pair it with CG lots at the same minute.
    """

    def test_finds_funding_fee_event_with_timestamp(self, tmp_path: Path):
        from tax_reporting.application.crypto.derivatives_dedup import (
            DerivativesThEvent,
            find_derivatives_th_events,
        )

        th = tmp_path / "th.csv"
        _write_th_csv(
            th,
            [
                {
                    "Date": "2025-01-24 20:00:00 UTC",
                    "Type": "crypto_withdrawal",
                    "Tag": "Funding fee",
                    "Sending Wallet": "ByBit",
                    "Sent Amount": "0,08838575",
                    "Sent Currency": "USDT",
                }
            ],
        )

        events = find_derivatives_th_events(
            th, frozenset({"Funding fee", "Futures fee", "Realized gain"})
        )

        assert len(events) == 1
        event = events[0]
        assert isinstance(event, DerivativesThEvent)
        assert event.timestamp == "2025-01-24 20:00"
        assert event.asset == "USDT"
        assert event.wallet == "ByBit"
        assert event.amount == Decimal("0.08838575")
        assert event.label == "Funding fee"

    def test_truncates_seconds_from_timestamp(self, tmp_path: Path):
        from tax_reporting.application.crypto.derivatives_dedup import (
            find_derivatives_th_events,
        )

        th = tmp_path / "th.csv"
        _write_th_csv(
            th,
            [
                {
                    "Date": "2025-01-24 23:40:53 UTC",
                    "Type": "crypto_withdrawal",
                    "Tag": "Realized gain",
                    "Sending Wallet": "ByBit",
                    "Sent Amount": "40,75540000",
                    "Sent Currency": "USDT",
                }
            ],
        )

        events = find_derivatives_th_events(
            th, frozenset({"Realized gain"})
        )

        assert len(events) == 1
        assert events[0].timestamp == "2025-01-24 23:40"

    def test_ignores_non_withdrawal_type(self, tmp_path: Path):
        from tax_reporting.application.crypto.derivatives_dedup import (
            find_derivatives_th_events,
        )

        th = tmp_path / "th.csv"
        _write_th_csv(
            th,
            [
                {
                    "Date": "2025-01-24 00:15:03 UTC",
                    "Type": "crypto_deposit",
                    "Tag": "Funding fee",
                    "Receiving Wallet": "ByBit",
                    "Received Amount": "0,25289809",
                    "Received Currency": "USDT",
                }
            ],
        )

        events = find_derivatives_th_events(
            th, frozenset({"Funding fee"})
        )

        assert events == []

    def test_ignores_non_derivatives_labels(self, tmp_path: Path):
        from tax_reporting.application.crypto.derivatives_dedup import (
            find_derivatives_th_events,
        )

        th = tmp_path / "th.csv"
        _write_th_csv(
            th,
            [
                {
                    "Date": "2025-01-13 03:45:30 UTC",
                    "Type": "exchange",
                    "Tag": "",
                    "Sending Wallet": "ByBit",
                    "Sent Amount": "108,33500000",
                    "Sent Currency": "USDT",
                    "Receiving Wallet": "ByBit",
                    "Received Amount": "23,50000000",
                    "Received Currency": "SUI",
                }
            ],
        )

        events = find_derivatives_th_events(
            th, frozenset({"Funding fee", "Futures fee", "Realized gain"})
        )

        assert events == []

    def test_ignores_reward_label(self, tmp_path: Path):
        from tax_reporting.application.crypto.derivatives_dedup import (
            find_derivatives_th_events,
        )

        th = tmp_path / "th.csv"
        _write_th_csv(
            th,
            [
                {
                    "Date": "2025-01-24 00:15:03 UTC",
                    "Type": "crypto_withdrawal",
                    "Tag": "Reward",
                    "Sending Wallet": "ByBit",
                    "Sent Amount": "0,19103622",
                    "Sent Currency": "USDT",
                }
            ],
        )

        events = find_derivatives_th_events(
            th, frozenset({"Funding fee", "Futures fee", "Realized gain"})
        )

        assert events == []

    def test_multiple_events_at_same_timestamp(self, tmp_path: Path):
        from tax_reporting.application.crypto.derivatives_dedup import (
            find_derivatives_th_events,
        )

        th = tmp_path / "th.csv"
        _write_th_csv(
            th,
            [
                {
                    "Date": "2025-01-24 23:40:53 UTC",
                    "Type": "crypto_withdrawal",
                    "Tag": "Futures fee",
                    "Sending Wallet": "ByBit",
                    "Sent Amount": "0,41424953",
                    "Sent Currency": "USDT",
                },
                {
                    "Date": "2025-01-24 23:40:53 UTC",
                    "Type": "crypto_withdrawal",
                    "Tag": "Realized gain",
                    "Sending Wallet": "ByBit",
                    "Sent Amount": "40,75540000",
                    "Sent Currency": "USDT",
                },
            ],
        )

        events = find_derivatives_th_events(
            th, frozenset({"Futures fee", "Realized gain"})
        )

        assert len(events) == 2
        amounts = {e.amount for e in events}
        assert amounts == {Decimal("0.41424953"), Decimal("40.75540000")}
        for event in events:
            assert event.timestamp == "2025-01-24 23:40"

    def test_multiple_events_at_same_timestamp_same_amount(self, tmp_path: Path):
        from tax_reporting.application.crypto.derivatives_dedup import (
            find_derivatives_th_events,
        )

        th = tmp_path / "th.csv"
        _write_th_csv(
            th,
            [
                {
                    "Date": "2025-01-24 08:00:00 UTC",
                    "Type": "crypto_withdrawal",
                    "Tag": "Funding fee",
                    "Sending Wallet": "ByBit",
                    "Sent Amount": "0,50000000",
                    "Sent Currency": "USDT",
                    "TxHash": "hash-a",
                },
                {
                    "Date": "2025-01-24 08:00:00 UTC",
                    "Type": "crypto_withdrawal",
                    "Tag": "Funding fee",
                    "Sending Wallet": "ByBit",
                    "Sent Amount": "0,50000000",
                    "Sent Currency": "USDT",
                    "TxHash": "hash-b",
                },
            ],
        )

        events = find_derivatives_th_events(
            th, frozenset({"Funding fee"})
        )

        assert len(events) == 2
        for event in events:
            assert event.timestamp == "2025-01-24 08:00"
            assert event.asset == "USDT"
            assert event.wallet == "ByBit"
            assert event.amount == Decimal("0.50000000")
            assert event.label == "Funding fee"

    def test_empty_label_set_returns_empty(self, tmp_path: Path):
        from tax_reporting.application.crypto.derivatives_dedup import (
            find_derivatives_th_events,
        )

        th = tmp_path / "th.csv"
        _write_th_csv(
            th,
            [
                {
                    "Date": "2025-01-24 20:00:00 UTC",
                    "Type": "crypto_withdrawal",
                    "Tag": "Funding fee",
                    "Sending Wallet": "ByBit",
                    "Sent Amount": "0,08838575",
                    "Sent Currency": "USDT",
                }
            ],
        )

        events = find_derivatives_th_events(th, frozenset())

        assert events == []


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

    _LOGGER_NAME = "tax_reporting.application.crypto.derivatives_dedup"

    def test_exact_match_removes_single_cg_lot(self):
        """Given one lot whose (timestamp, asset, wallet, amount_6dp) key
        matches a derivatives_event, expects the lot to be removed via
        exact match.
        """
        from tax_reporting.application.crypto.derivatives_dedup import (
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
        from tax_reporting.application.crypto.derivatives_dedup import (
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
        from tax_reporting.application.crypto.derivatives_dedup import (
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
        from tax_reporting.application.crypto.derivatives_dedup import (
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
        from tax_reporting.application.crypto.derivatives_dedup import (
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
        from tax_reporting.application.crypto.derivatives_dedup import (
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
        from tax_reporting.application.crypto.derivatives_dedup import (
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
        from tax_reporting.application.crypto.derivatives_dedup import (
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
        from tax_reporting.application.crypto.derivatives_dedup import (
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
        # Exactly one summary WARNING, and its "surplus lots" section is empty.
        summary_records = [
            r for r in caplog.records if r.levelno == logging.WARNING
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
        from tax_reporting.application.crypto.derivatives_dedup import (
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
        from tax_reporting.application.crypto.derivatives_dedup import (
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

        # Exactly one WARNING (the summary); no per-lot WARNING lines.
        warning_records = [
            r for r in caplog.records if r.levelno == logging.WARNING
        ]
        assert len(warning_records) == 1
        summary_message = warning_records[0].getMessage()
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
        from tax_reporting.application.crypto.derivatives_dedup import (
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

    def test_summary_logged_at_warning_once(
        self, caplog: pytest.LogCaptureFixture
    ):
        """Given a removal scenario removing N lots, expects exactly one
        WARNING log summarizing removals (total count, exact count, range
        count, aggregate proceeds, aggregate gain removed); surplus lots;
        and malformed-input lots. The summary is the ONLY WARNING emitted.
        """
        from tax_reporting.application.crypto.derivatives_dedup import (
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

        warning_records = [
            r for r in caplog.records if r.levelno == logging.WARNING
        ]
        assert len(warning_records) == 1
        summary = warning_records[0].getMessage()
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
        from tax_reporting.application.crypto.derivatives_dedup import (
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

        warning_records = [
            r for r in caplog.records if r.levelno == logging.WARNING
        ]
        assert len(warning_records) == 1
        summary = warning_records[0].getMessage()
        assert "2 malformed" in summary

    def test_range_match_does_not_trigger_collision_warning(
        self, caplog: pytest.LogCaptureFixture
    ):
        """Given 1 derivatives_event at amount=120.0 and 2 contiguous CG lots
        at amounts [70.0, 50.0] (range-matched, not exact-matched), expects
        the summary WARNING's "surplus lots" section to be empty (the warning
        is reserved for same-key exact-match collisions only).
        """
        from tax_reporting.application.crypto.derivatives_dedup import (
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

        warning_records = [
            r for r in caplog.records if r.levelno == logging.WARNING
        ]
        assert len(warning_records) == 1
        summary = warning_records[0].getMessage()
        assert "0 surplus" in summary

    def test_empty_derivatives_events_returns_input_unchanged(
        self, caplog: pytest.LogCaptureFixture
    ):
        """Given capital_entries and an empty derivatives_events list, expects
        the function to return the input list unchanged with count 0 and no
        summary WARNING.
        """
        from tax_reporting.application.crypto.derivatives_dedup import (
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
        from tax_reporting.application.crypto.derivatives_dedup import (
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
        from tax_reporting.application.crypto.derivatives_dedup import (
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

