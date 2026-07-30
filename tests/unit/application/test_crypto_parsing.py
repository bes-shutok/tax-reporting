"""Tests for crypto/parsing.py: file discovery and parsing helpers."""

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path

import pytest

from tax_reporting.application.crypto.entities import (
    CryptoReviewEntry,
    ParsedOgrRow,
)
from tax_reporting.application.crypto.ogr_handler import _build_ogr_index
from tax_reporting.application.crypto.parsing import (
    _MAX_PDF_BYTES,
    _decode_pdf_hex_token,
    _extract_tax_year,
)
from tax_reporting.application.crypto_fifo.contexts import (
    AcquisitionContext,
    ConsumptionContext,
    ParsedTxRow,
)
from tax_reporting.application.crypto_fifo.parsing import (
    _classify_deposit_row,
    _dedup_by_tx_key,
)
from tax_reporting.domain.crypto_fifo import CryptoAcquisition, CryptoConsumption
from tax_reporting.infrastructure.koinly_parser import (
    _find_and_parse_other_gains_file,
)


class TestExtractTaxYear:
    """Tests for _extract_tax_year()."""

    def test_extract_tax_year_from_capital_file(self, tmp_path: Path) -> None:
        """Given '2024-Capital Gains Report.csv', returns 2024."""
        # Arrange
        capital_file = tmp_path / "koinly_2024_capital_gains_report.csv"
        capital_file.write_text("data\n")

        # Act
        result = _extract_tax_year(tmp_path, capital_file, None)

        # Assert
        assert result == 2024

    def test_extract_tax_year_from_income_file(self, tmp_path: Path) -> None:
        """Given '2023-Income Report.csv', returns 2023."""
        # Arrange
        income_file = tmp_path / "koinly_2023_income_report.csv"
        income_file.write_text("data\n")

        # Act
        result = _extract_tax_year(tmp_path, None, income_file)

        # Assert
        assert result == 2023

    def test_extract_tax_year_fallback_to_jurisdiction(self, tmp_path: Path, monkeypatch) -> None:
        """Given files without year, returns jurisdiction.fiscal_year."""
        # Arrange: mock jurisdiction
        class MockJurisdiction:
            fiscal_year = 2025

        capital_file = tmp_path / "Capital_Gains_Report.csv"
        capital_file.write_text("data\n")

        # Act
        result = _extract_tax_year(tmp_path, capital_file, None, jurisdiction=MockJurisdiction())

        # Assert
        assert result == 2025

    def test_extract_tax_year_fallback_to_directory_name(self, tmp_path: Path) -> None:
        """Given no year in files and no jurisdiction, extracts from directory name."""
        # Arrange: create subdirectory with year in name
        year_dir = tmp_path / "koinly_2022"
        year_dir.mkdir()
        capital_file = year_dir / "Capital_Gains_Report.csv"
        capital_file.write_text("data\n")

        # Act
        result = _extract_tax_year(year_dir, capital_file, None)

        # Assert
        assert result == 2022

    def test_extract_tax_year_fallback_to_current_year(self, tmp_path: Path, monkeypatch) -> None:
        """Given no year anywhere, returns current year."""
        # Arrange: create directory without year patterns
        capital_file = tmp_path / "report.csv"
        capital_file.write_text("data\n")

        # Mock datetime.now() to return a fixed year for predictable testing
        import datetime
        fixed_date = datetime.datetime(2026, 6, 11, tzinfo=datetime.UTC)
        # datetime.now is called as now(tz=UTC), so the mock must accept the tz kwarg.
        mock_datetime = type("MockDatetime", (), {"now": lambda tz: fixed_date})  # noqa: ARG005
        monkeypatch.setattr("tax_reporting.application.crypto.parsing.datetime", mock_datetime)

        # Act
        result = _extract_tax_year(tmp_path, capital_file, None)

        # Assert
        assert result == 2026


class TestDecodePdfHexToken:
    """Tests for _decode_pdf_hex_token()."""

    def test_decode_pdf_hex_token_valid_utf8(self) -> None:
        """Given valid hex token bytes, returns decoded string."""
        # Arrange: "test" in hex
        token = b"74657374"

        # Act
        result = _decode_pdf_hex_token(token)

        # Assert
        assert result == "test"

    def test_decode_pdf_hex_token_valid_utf16_be(self) -> None:
        """Given valid UTF-16BE hex token with null bytes, returns decoded string."""
        # Arrange: "AB" in UTF-16BE hex (00 41 00 42)
        token = b"00410042"

        # Act
        result = _decode_pdf_hex_token(token)

        # Assert
        assert result == "AB"

    def test_decode_pdf_hex_token_invalid_length(self) -> None:
        """Given hex token with odd length, returns empty string."""
        # Arrange: odd-length hex string
        token = b"746"

        # Act
        result = _decode_pdf_hex_token(token)

        # Assert
        assert result == ""

    def test_decode_pdf_hex_token_invalid_hex(self) -> None:
        """Given invalid hex characters, returns empty string."""
        # Arrange: invalid hex
        token = b"GGHH"

        # Act
        result = _decode_pdf_hex_token(token)

        # Assert
        assert result == ""

    def test_decode_pdf_hex_token_empty_after_decode(self) -> None:
        """Given hex that decodes to empty/null bytes, returns empty string."""
        # Arrange: hex for "00 00" (null bytes)
        token = b"0000"

        # Act
        result = _decode_pdf_hex_token(token)

        # Assert
        assert result == ""

    def test_decode_pdf_hex_token_with_null_bytes(self) -> None:
        """Given UTF-16BE token, strips null bytes and returns text."""
        # Arrange: "AB" in UTF-16BE hex (00 41 00 42)
        token = b"00410042"

        # Act
        result = _decode_pdf_hex_token(token)

        # Assert
        assert result == "AB"


class TestMaxPdfBytes:
    """Tests for _MAX_PDF_BYTES constant."""

    def test_max_pdf_bytes_is_defined(self) -> None:
        """_MAX_PDF_BYTES constant is defined."""
        # Assert: constant exists and is a positive int
        assert isinstance(_MAX_PDF_BYTES, int)
        assert _MAX_PDF_BYTES > 0

    def test_max_pdf_bytes_value(self) -> None:
        """_MAX_PDF_BYTES is set to 20 MB."""
        # Assert: 20 MB = 20 * 1024 * 1024 bytes
        expected = 20 * 1024 * 1024
        assert expected == _MAX_PDF_BYTES


# =============================================================================
# Tests for _find_and_parse_other_gains_file (Task 6: list[ParsedOgrRow] return)
# =============================================================================

_OTHER_GAINS_CSV_HEADER = "Date,Asset,Amount,Value (EUR),Type,Wallet Name\n"


def _write_other_gains_csv(directory: Path, rows: list[dict[str, str]]) -> Path:
    """Write a minimal Other Gains Report CSV into ``directory`` and return its path."""
    import csv as _csv

    path = directory / "koinly_2025_other_gains_report.csv"
    fieldnames = ["Date", "Asset", "Amount", "Value (EUR)", "Type", "Wallet Name"]
    with path.open("w", newline="") as fh:
        writer = _csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return path


class TestOtherGainsParse:
    """Task 6 RED tests: _find_and_parse_other_gains_file returns list[ParsedOgrRow]."""

    def test_returns_list_of_parsed_rows(self, tmp_path: Path) -> None:
        """Given an OGR CSV with 3 rows, returns list[ParsedOgrRow] length 3.

        Each row carries (date, asset, gain_loss, row_type, wallet). The parser
        returns a list of typed rows, NOT a pre-summed dict.
        """
        _write_other_gains_csv(
            tmp_path,
            [
                {
                    "Date": "13/01/2025 13:01",
                    "Asset": "USDT",
                    "Amount": "-142,11",
                    "Value (EUR)": "138,73",
                    "Type": "Loss",
                    "Wallet Name": "ByBit",
                },
                {
                    "Date": "14/01/2025 10:30",
                    "Asset": "BTC",
                    "Amount": "0,5",
                    "Value (EUR)": "500,00",
                    "Type": "Profit",
                    "Wallet Name": "Kraken",
                },
                {
                    "Date": "15/01/2025 09:00",
                    "Asset": "ETH",
                    "Amount": "1,0",
                    "Value (EUR)": "250,00",
                    "Type": "Profit",
                    "Wallet Name": "Gate.io",
                },
            ],
        )

        result = _find_and_parse_other_gains_file(tmp_path)

        # The parser must return a list of ParsedOgrRow, NOT a pre-summed dict.
        assert isinstance(result, list)
        assert len(result) == 3
        assert all(isinstance(row, ParsedOgrRow) for row in result)

        # Each row carries the parsed fields.
        by_key = {(r.date, r.asset, r.wallet): r for r in result}
        assert ("2025-01-13", "USDT", "ByBit") in by_key
        assert by_key[("2025-01-13", "USDT", "ByBit")].gain_loss == Decimal("-138.73")
        assert by_key[("2025-01-13", "USDT", "ByBit")].row_type == "Loss"

        assert ("2025-01-14", "BTC", "Kraken") in by_key
        assert by_key[("2025-01-14", "BTC", "Kraken")].gain_loss == Decimal("500.00")
        assert by_key[("2025-01-14", "BTC", "Kraken")].row_type == "Profit"

        assert ("2025-01-15", "ETH", "Gate.io") in by_key
        assert by_key[("2025-01-15", "ETH", "Gate.io")].gain_loss == Decimal("250.00")

    def test_preserves_per_row_type(self, tmp_path: Path) -> None:
        """Two OGR rows on the same key with different Type appear separately.

        Rows share the same (date, asset, wallet) key but have different Type
        (Profit and Loss). Both appear separately with original Type preserved,
        no summing at parse time.
        """
        _write_other_gains_csv(
            tmp_path,
            [
                {
                    "Date": "13/01/2025 13:01",
                    "Asset": "USDT",
                    "Amount": "-4,17",
                    "Value (EUR)": "4,17",
                    "Type": "Loss",
                    "Wallet Name": "ByBit",
                },
                {
                    "Date": "13/01/2025 13:01",
                    "Asset": "USDT",
                    "Amount": "140,18",
                    "Value (EUR)": "140,18",
                    "Type": "Profit",
                    "Wallet Name": "ByBit",
                },
            ],
        )

        result = _find_and_parse_other_gains_file(tmp_path)

        # The parser must NOT pre-sum: both rows appear separately with original Type.
        assert isinstance(result, list)
        assert len(result) == 2

        row_types = {r.row_type for r in result}
        assert row_types == {"Loss", "Profit"}

        losses = [r for r in result if r.row_type == "Loss"]
        profits = [r for r in result if r.row_type == "Profit"]
        assert len(losses) == 1
        assert len(profits) == 1
        assert losses[0].gain_loss == Decimal("-4.17")
        assert profits[0].gain_loss == Decimal("140.18")


class TestBuildOgrIndex:
    """Task 6 RED tests: _build_ogr_index(rows: list[ParsedOgrRow]) sums into dict."""

    def test_sums_into_dict(self) -> None:
        """Given list[ParsedOgrRow] with duplicate keys, _build_ogr_index sums values.

        Returns dict[(date, asset, wallet), Decimal] with values summed across
        rows sharing the same key.
        """
        rows = [
            ParsedOgrRow(
                date="2025-01-13",
                asset="USDT",
                gain_loss=Decimal("-4.17"),
                row_type="Loss",
                wallet="ByBit",
            ),
            ParsedOgrRow(
                date="2025-01-13",
                asset="USDT",
                gain_loss=Decimal("140.18"),
                row_type="Profit",
                wallet="ByBit",
            ),
        ]

        index = _build_ogr_index(rows)

        assert isinstance(index, dict)
        # Duplicate keys are summed into a single Decimal value.
        assert index[("2025-01-13", "USDT", "ByBit")] == Decimal("136.01")

    def test_backward_compat_matches_old_behavior(self, tmp_path: Path) -> None:
        """Composed pipeline produces the same dict the old single call produced.

        Given ByBit Case 1 fixtures, _build_ogr_index(_find_and_parse_other_gains_file(
        koinly_dir)) produces the same dict the old _find_and_parse_other_gains_file
        produced. The old function returned dict[(date, asset, wallet), Decimal] with
        summed values. The new pipeline is _find_and_parse_other_gains_file ->
        list[ParsedOgrRow] followed by _build_ogr_index summing into the same dict.
        This test guards backward compatibility: the composed output must equal the
        old single-call output shape.
        """
        _write_other_gains_csv(
            tmp_path,
            [
                {
                    "Date": "13/01/2025 13:01",
                    "Asset": "USDT",
                    "Amount": "-4,17",
                    "Value (EUR)": "4,17",
                    "Type": "Loss",
                    "Wallet Name": "ByBit",
                },
                {
                    "Date": "13/01/2025 13:01",
                    "Asset": "USDT",
                    "Amount": "140,18",
                    "Value (EUR)": "140,18",
                    "Type": "Profit",
                    "Wallet Name": "ByBit",
                },
            ],
        )

        rows = _find_and_parse_other_gains_file(tmp_path)
        index = _build_ogr_index(rows)

        # The composed pipeline must produce the old single-call shape.
        assert isinstance(index, dict)
        # Old behavior summed the two rows: -4.17 + 140.18 = 136.01
        assert index[("2025-01-13", "USDT", "ByBit")] == Decimal("136.01")


def _make_acq_context(
    *, tx_key: str, source_row_index: int, asset: str = "WBTC",
    date: str = "2025-01-15", source_type: str = "buy",
) -> AcquisitionContext:
    """Build a minimal AcquisitionContext for direct _dedup_by_tx_key tests."""
    return AcquisitionContext(
        acq=CryptoAcquisition(
            date=date,
            asset=asset,
            amount=Decimal("1"),
            cost_basis_eur=Decimal("100"),
            fee_eur=Decimal("0"),
            source_type=source_type,
            wallet="Kraken",
            platform="Kraken",
            review_required=False,
        ),
        tx_key=tx_key,
        source_row_index=source_row_index,
    )


def _make_con_context(
    *, tx_key: str, source_row_index: int, asset: str = "WBTC",
    date: str = "2025-02-15", event_type: str = "exchange_out",
) -> ConsumptionContext:
    """Build a minimal ConsumptionContext for direct _dedup_by_tx_key tests."""
    return ConsumptionContext(
        con=CryptoConsumption(
            date=date,
            asset=asset,
            amount=Decimal("1"),
            proceeds_eur=Decimal("0"),
            event_type=event_type,
            taxable=False,
            wallet="Kraken",
            platform="Kraken",
            notes="",
            review_required=False,
        ),
        tx_key=tx_key,
        source_row_index=source_row_index,
    )


class TestCryptoParsing:
    """Duplicate-tx_key drops now emit INFO + CryptoReviewEntry rows (Plan
    2026-07-25 Task 3 / W2).

    Governing principle: console WARNINGs reserved for project/processing
    problems; data issues live in the user-facing extract (Crypto Supplementary
    review rows). The W2 aggregate ("Dropped N duplicate-tx_key ...") drops to
    INFO, and one ``CryptoReviewEntry(source_section="capital_gains")`` is
    appended per dropped acquisition/consumption (INV-1 no signal loss).
    """

    def test_duplicate_txkey_drops_emit_info_and_review_rows(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Given 2 acquisitions sharing a tx_key + 1 duplicate consumption,
        expects ONE INFO summary, ZERO WARNING records, and N+M review rows."""
        # Two acquisitions sharing tx_key "dup_acq" (same source_type "buy"):
        # first kept, second dropped. Plus two consumptions sharing tx_key
        # "dup_con" (same event_type "exchange_out"): first kept, second dropped.
        acquisitions = {
            "WBTC": [
                _make_acq_context(tx_key="dup_acq", source_row_index=1),
                _make_acq_context(tx_key="dup_acq", source_row_index=2),
            ]
        }
        consumptions = {
            "WBTC": [
                _make_con_context(tx_key="dup_con", source_row_index=10),
                _make_con_context(tx_key="dup_con", source_row_index=11),
            ]
        }
        review_entries: list[CryptoReviewEntry] = []
        parse_failures: dict[str, list[int]] = {}

        parsing_logger = "tax_reporting.application.crypto_fifo.parsing"
        with caplog.at_level(logging.INFO, logger="tax_reporting.application.crypto_fifo"):
            _dedup_by_tx_key(
                acquisitions, consumptions, parse_failures,
                review_entries=review_entries,
            )

        # ONE INFO summary, ZERO WARNING records.
        info_messages = [
            rec.getMessage()
            for rec in caplog.records
            if rec.levelno == logging.INFO and rec.name == parsing_logger
        ]
        aggregate_info = [
            m for m in info_messages
            if "Dropped" in m and "duplicate-tx_key acquisition(s)" in m
            and "consumption(s)" in m
        ]
        assert len(aggregate_info) == 1, (
            f"Expected exactly ONE aggregate INFO summary, got {aggregate_info}"
        )
        assert "Dropped 1 duplicate-tx_key acquisition(s)" in aggregate_info[0]
        assert "1 consumption(s)" in aggregate_info[0]

        warning_messages = [
            rec.getMessage()
            for rec in caplog.records
            if rec.levelno == logging.WARNING and rec.name == parsing_logger
        ]
        duplicate_warnings = [m for m in warning_messages if "duplicate-tx_key" in m]
        assert duplicate_warnings == [], (
            f"Expected ZERO WARNING records for duplicate-tx_key, got {duplicate_warnings}"
        )

        # N + M review rows (1 dropped acquisition + 1 dropped consumption = 2).
        assert len(review_entries) == 2, (
            f"Expected 2 CryptoReviewEntry rows (1 acq + 1 con), got {len(review_entries)}"
        )
        # All rows are capital_gains-sourced (W2 source_section per Task 3).
        assert all(r.source_section == "capital_gains" for r in review_entries), (
            f"All W2 review rows must be source_section='capital_gains'; got {review_entries}"
        )

        # Exactly one acquisition-distinguishing row + one consumption-distinguishing row,
        # each naming its tx_key.
        acq_rows = [r for r in review_entries if "acquisition" in r.review_reason]
        con_rows = [r for r in review_entries if "consumption" in r.review_reason]
        assert len(acq_rows) == 1, (
            f"Expected ONE acquisition review row, got {acq_rows}"
        )
        assert len(con_rows) == 1, (
            f"Expected ONE consumption review row, got {con_rows}"
        )
        assert "dup_acq" in acq_rows[0].review_reason, (
            f"Acquisition review reason must name the tx_key; got {acq_rows[0].review_reason}"
        )
        assert "dup_con" in con_rows[0].review_reason, (
            f"Consumption review reason must name the tx_key; got {con_rows[0].review_reason}"
        )
        # Row carries asset/date/platform context for the user.
        assert acq_rows[0].asset == "WBTC"
        assert con_rows[0].asset == "WBTC"
        assert acq_rows[0].platform == "Kraken"
        assert con_rows[0].platform == "Kraken"

        # INV-3 backward compat: omitting review_entries must NOT raise (existing
        # ~78 test callers do this). Demotion side-effect: nothing appended.
        acquisitions2 = {
            "WBTC": [
                _make_acq_context(tx_key="dup_acq2", source_row_index=1),
                _make_acq_context(tx_key="dup_acq2", source_row_index=2),
            ]
        }
        consumptions2: dict[str, list] = {"WBTC": []}
        # Should not raise AttributeError.
        _dedup_by_tx_key(acquisitions2, consumptions2, {})

    def test_zero_nv_deposit_emits_info_and_review_row(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Given a crypto_deposit TH row with Net Value == 0, expects ONE INFO
        aggregate, ZERO WARNING records, and a CryptoReviewEntry(source_section=
        'transaction_history') whose reason names the missing-cost-basis concern.

        Unit test at the ``_classify_deposit_row`` layer (the per-row classifier
        that the main parse loop calls inside ``_classify_rows_for_loan_affected_assets``),
        with a threaded ``review_entries`` list. Plan 2026-07-25 Task 4 / W3.
        """
        # Build a crypto_deposit ParsedTxRow with Net Value == 0 (the zero-NV branch).
        zero = Decimal("0")
        parsed_row = ParsedTxRow(
            row={
                "Date": "2025-03-15 10:00:00 UTC",
                "Type": "crypto_deposit",
                "Sending Wallet": "",
                "Receiving Wallet": "Kraken Main",
                "Sent Amount": "",
                "Sent Currency": "",
                "Received Amount": "0,5",
                "Received Currency": "WBTC",
                "Net Value (EUR)": "0",
                "TxHash": "znv_w3",
            },
            row_index=42,
            date_str="2025-03-15",
            tx_key="znv_w3",
            row_type="crypto_deposit",
            sent_currency="",
            received_currency="WBTC",
            fee_currency="",
            sent_amount=zero,
            received_amount=Decimal("0.5"),
            sent_cost_basis=zero,
            net_value=zero,
            fee_amount=zero,
            fee_value=zero,
            sent_affected=False,
            received_affected=True,
            fee_affected=False,
            loan_affected_assets=frozenset({"WBTC"}),
        )

        acquisitions: defaultdict[str, list[AcquisitionContext]] = defaultdict(list)
        consumptions: dict[str, list] = {}
        parse_failures: dict[str, list[int]] = {}
        zero_net_deposits: Counter[str] = Counter()
        review_entries: list[CryptoReviewEntry] = []

        parsing_logger = "tax_reporting.application.crypto_fifo.parsing"
        with caplog.at_level(logging.INFO, logger="tax_reporting.application.crypto_fifo"):
            _classify_deposit_row(
                parsed_row,
                acquisitions=acquisitions,
                consumptions=consumptions,
                parse_failures_by_asset=parse_failures,
                zero_net_deposits=zero_net_deposits,
                review_entries=review_entries,
            )

        # The per-row classifier must append the missing-cost-basis review row at
        # the zero-NV branch so the aggregate INFO at the orchestrator layer can
        # count it. ONE review row, source_section="transaction_history".
        assert len(review_entries) == 1, (
            f"Expected 1 CryptoReviewEntry for the zero-NV deposit, got {review_entries}"
        )
        row = review_entries[0]
        assert row.source_section == "transaction_history", (
            f"W3 review row source_section must be 'transaction_history'; got {row.source_section}"
        )
        assert row.asset == "WBTC"
        assert row.date == "2025-03-15"
        # Platform comes from the Receiving Wallet column.
        assert row.platform == "Kraken Main"
        # The reason must name the missing-cost-basis concern so the user knows
        # what to investigate in the source export.
        reason_lower = row.review_reason.lower()
        assert "zero-net-value" in reason_lower, (
            f"W3 review_reason must name the zero-Net-Value concern; got {row.review_reason}"
        )
        assert "cost basis" in reason_lower, (
            f"W3 review_reason must name the missing-cost-basis concern; got {row.review_reason}"
        )

        # The per-row classifier itself emits only DEBUG (the aggregate INFO is
        # emitted by the orchestrator at the end of the run). So ZERO WARNING
        # and ZERO INFO records naming the W3 substring at THIS layer.
        warning_messages = [
            rec.getMessage()
            for rec in caplog.records
            if rec.levelno == logging.WARNING and rec.name == parsing_logger
        ]
        zero_nv_warnings = [m for m in warning_messages if "zero-Net-Value" in m]
        assert zero_nv_warnings == [], (
            f"Expected ZERO WARNING records for zero-Net-Value, got {zero_nv_warnings}"
        )

        # The per-row classifier registered the deposit in the Counter so the
        # orchestrator's aggregate INFO ("Flagged N zero-Net-Value ...") can
        # summarize it. We assert the counter was bumped (the orchestrator emit
        # is demoted to INFO and tested end-to-end via the W2/W3 gate test).
        assert zero_net_deposits["WBTC"] == 1

        # INV-3 backward compat: omitting review_entries must NOT raise.
        review_entries_none: list[CryptoReviewEntry] | None = None
        parse_failures2: dict[str, list[int]] = {}
        _classify_deposit_row(
            parsed_row,
            acquisitions=defaultdict(list),
            consumptions={},
            parse_failures_by_asset=parse_failures2,
            zero_net_deposits=Counter(),
            review_entries=review_entries_none,
        )
