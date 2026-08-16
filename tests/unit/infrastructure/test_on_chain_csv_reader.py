"""Tests for the on-chain ``bera_transactions.csv`` reader (Task 7).

RED phase: these tests pin the behaviour of the reader before the production
module ``src/tax_reporting/infrastructure/on_chain/on_chain_csv_reader.py``
exists. The reader is a THIN pre-classification parser: it emits
:class:`OnChainTxRow` records carrying row-level fields (incl. per-row gas as
``fee_asset``/``fee_amount_raw``). The processor (Task 9, NOT this task) groups
rows by ``tx_hash`` and lifts gas to the parent :class:`OnChainTransaction`.

Per AGENTS.md crypto-tests rule, tests MUST read committed synthetic data; the
real ``resources/result/2025/bera_transactions.csv`` is gitignored
(``resources/result/*``). The fixtures below use the real 15-column HEADER
SHAPE (verified against the on-disk file) with synthetic data rows. The real
file is NOT referenced from any test.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import pytest

from tax_reporting.domain.exceptions import FileProcessingError
from tax_reporting.infrastructure.on_chain.on_chain_csv_reader import (
    OnChainTxRow,
    read_on_chain_rows,
)

# The REAL on-disk header (verified 2026-08-02 against
# resources/result/2025/bera_transactions.csv). Lowercase snake_case, 15 cols.
_REAL_HEADER = (
    "tx_hash,block_number,timestamp_utc,chain,from_address,to_address,"
    "asset,token_address,amount_raw,amount_decimals,direction,fee_asset,"
    "fee_amount_raw,wallet_label,wallet_address"
)

# Synthetic, test-only values (no real chain identity literal: DI-2).
_TX_HASH = "0x" + "a" * 64
_FROM_ADDR = "0x" + "1" * 40
_TO_ADDR = "0x" + "2" * 40
_WALLET_ADDR = _TO_ADDR


def _one_row_csv(**overrides: str) -> str:
    """Build a single-row CSV string using the real header + a synthetic row.

    Caller overrides are applied to the data-row cell values by column name.
    """
    cells = {
        "tx_hash": _TX_HASH,
        "block_number": "1590503",
        "timestamp_utc": "2025-02-25T13:53:25+00:00",
        "chain": "Testchain",
        "from_address": _FROM_ADDR,
        "to_address": _TO_ADDR,
        "asset": "TST",
        "token_address": "",
        "amount_raw": "1000000000000000000",
        "amount_decimals": "18",
        "direction": "in",
        "fee_asset": "TST",
        "fee_amount_raw": "2100000273000",
        "wallet_label": "Test Wallet (TST)",
        "wallet_address": _WALLET_ADDR,
    }
    cells.update(overrides)
    data_line = ",".join(cells[col] for col in (
        "tx_hash", "block_number", "timestamp_utc", "chain", "from_address",
        "to_address", "asset", "token_address", "amount_raw",
        "amount_decimals", "direction", "fee_asset", "fee_amount_raw",
        "wallet_label", "wallet_address",
    ))
    return f"{_REAL_HEADER}\n{data_line}\n"


@pytest.mark.unit
class TestOnChainCsvReader:
    """Test the on-chain CSV reader's parse, type, guard, and hygiene behaviour."""

    def test_parses_all_columns(self, tmp_path) -> None:
        """Given the real 15-column header, each row parses into an OnChainTxRow
        with all 15 fields populated correctly (amount_raw as int, amount_decimals
        as int, direction in {in,out,unknown})."""
        csv_text = _one_row_csv() + _one_row_csv(
            tx_hash="0x" + "b" * 64,
            direction="out",
            token_address="0x" + "9" * 40,
        )
        path = tmp_path / "bera_transactions.csv"
        path.write_text(csv_text, encoding="utf-8")

        rows = read_on_chain_rows(path)

        assert len(rows) == 2
        row = rows[0]
        # All 15 fields populated + correct types.
        assert isinstance(row, OnChainTxRow)
        assert row.tx_hash == _TX_HASH
        assert row.block_number == 1590503
        assert row.timestamp_utc == datetime(2025, 2, 25, 13, 53, 25, tzinfo=UTC)
        assert row.chain == "Testchain"
        assert row.from_address == _FROM_ADDR
        assert row.to_address == _TO_ADDR
        assert row.asset == "TST"
        # Native asset -> empty token_address normalizes to None.
        assert row.token_address is None
        assert row.amount_raw == 1000000000000000000
        assert isinstance(row.amount_raw, int)
        assert row.amount_decimals == 18
        assert isinstance(row.amount_decimals, int)
        assert row.direction == "in"
        assert row.fee_asset == "TST"
        assert row.fee_amount_raw == 2100000273000
        assert row.wallet_label == "Test Wallet (TST)"
        assert row.wallet_address == _WALLET_ADDR
        # Second row carries its distinct values incl. token_address present.
        assert rows[1].direction == "out"
        assert rows[1].token_address == "0x" + "9" * 40

    def test_amount_raw_is_int_not_float(self, tmp_path) -> None:
        """Given amount_raw=1000000000000000000 (10**18), expects amount_raw is
        int(10**18), never float."""
        csv_text = _one_row_csv(amount_raw="1000000000000000000")
        path = tmp_path / "bera_transactions.csv"
        path.write_text(csv_text, encoding="utf-8")

        rows = read_on_chain_rows(path)

        assert len(rows) == 1
        assert rows[0].amount_raw == 10**18
        assert isinstance(rows[0].amount_raw, int)
        assert not isinstance(rows[0].amount_raw, float)  # bool/int distinction guard

    def test_decimal_overflow_clamped(self, tmp_path, caplog) -> None:
        """Given amount_decimals=77 (attacker-controlled, F5), expects the reader
        clamps to [0,36], logs WARNING, and emits the row with a review flag
        (never computes 10**77)."""
        csv_text = _one_row_csv(amount_decimals="77")
        path = tmp_path / "bera_transactions.csv"
        path.write_text(csv_text, encoding="utf-8")

        with caplog.at_level(logging.WARNING):
            rows = read_on_chain_rows(path)

        assert len(rows) == 1
        # Clamped into the valid range (never 77).
        assert rows[0].amount_decimals == 36
        # WARNING fired naming the clamp.
        assert any("decimal" in rec.message.lower() and "77" in rec.message for rec in caplog.records)
        # Review flag set with a specific, actionable reason (not a bare boolean).
        assert rows[0].review_flag == "decimal_clamped"
        assert rows[0].review_reason is not None
        assert "77" in rows[0].review_reason
        assert "0" in rows[0].review_reason
        assert "36" in rows[0].review_reason

    def test_skips_blank_rows_and_handles_bom(self, tmp_path) -> None:
        """Given a CSV with a BOM (\\ufeff) + trailing blank lines, expects a
        clean parse (BOM stripped, blank rows dropped)."""
        csv_text = (
            "\ufeff" + _REAL_HEADER + "\n"
            + ",".join([
                _TX_HASH, "1590503", "2025-02-25T13:53:25+00:00", "Testchain",
                _FROM_ADDR, _TO_ADDR, "TST", "", "1000000000000000000", "18",
                "in", "TST", "2100000273000", "Test Wallet (TST)", _WALLET_ADDR,
            ]) + "\n"
            # Trailing blank lines that DictReader emits as all-empty dicts.
            + ",,,,,,,,,,,,,,\n"
            + "\n"
        )
        path = tmp_path / "bera_transactions.csv"
        path.write_text(csv_text, encoding="utf-8")

        rows = read_on_chain_rows(path)

        assert len(rows) == 1
        assert rows[0].tx_hash == _TX_HASH
        # BOM must NOT have leaked into the first column header (which would
        # mis-key the row under "\ufefftx_hash").
        assert rows[0].chain == "Testchain"

    def test_malformed_row_skipped_good_rows_survive(self, tmp_path, caplog) -> None:
        """Given a CSV with one good row (tx_hash 0xgood) and one bad row
        (unparseable timestamp_utc), expects read_on_chain_rows returns 1 row
        (0xgood) and a WARNING naming the bad row's tx_hash.

        Characterizes the per-row skip+WARN guard (AGENTS.md: one bad row never
        discards the dataset). The bad row's tx_hash cell IS itself parseable
        as a string, so the WARNING can (and does) carry it for traceability.
        """
        good_tx_hash = "0xgood"
        bad_tx_hash = "0xbad"
        # Bad row: timestamp_utc is unparseable -> datetime.fromisoformat raises
        # ValueError, caught by the per-row guard.
        bad_row = ",".join([
            bad_tx_hash, "1590503", "not-a-real-timestamp", "Testchain",
            _FROM_ADDR, _TO_ADDR, "TST", "", "1000000000000000000", "18",
            "in", "TST", "2100000273000", "Test Wallet (TST)", _WALLET_ADDR,
        ])
        good_row = ",".join([
            good_tx_hash, "1590503", "2025-02-25T13:53:25+00:00", "Testchain",
            _FROM_ADDR, _TO_ADDR, "TST", "", "1000000000000000000", "18",
            "in", "TST", "2100000273000", "Test Wallet (TST)", _WALLET_ADDR,
        ])
        csv_text = f"{_REAL_HEADER}\n{bad_row}\n{good_row}\n"
        path = tmp_path / "bera_transactions.csv"
        path.write_text(csv_text, encoding="utf-8")

        with caplog.at_level(logging.WARNING):
            rows = read_on_chain_rows(path)

        # Good row survived; bad row was dropped.
        assert len(rows) == 1
        assert rows[0].tx_hash == good_tx_hash
        # A WARNING fired naming the bad row's tx_hash (traceability).
        assert any(
            rec.levelno >= logging.WARNING and bad_tx_hash in rec.message
            for rec in caplog.records
        ), f"expected a WARNING mentioning {bad_tx_hash}; got {[r.message for r in caplog.records]}"

    def test_direction_coerced_to_unknown_with_review_flag(self, tmp_path) -> None:
        """Given a row with direction=sideways, expects the row's direction is
        coerced to "unknown" and review_flag == "direction_coerced".

        Characterizes the direction-coercion guard: an unexpected direction is
        never silently dropped nor silently mislabeled; it carries an explicit
        review indicator so the consumer cannot mistake it for a clean parse.
        """
        csv_text = _one_row_csv(direction="sideways")
        path = tmp_path / "bera_transactions.csv"
        path.write_text(csv_text, encoding="utf-8")

        rows = read_on_chain_rows(path)

        assert len(rows) == 1
        assert rows[0].direction == "unknown"
        assert rows[0].review_flag == "direction_coerced"
        # The review_reason must be specific and actionable (AGENTS.md), naming
        # the offending value so the cause is traceable.
        assert rows[0].review_reason is not None
        assert "sideways" in rows[0].review_reason

    def test_symlink_refused(self, tmp_path) -> None:
        """Given a symlinked bera CSV, expects FileProcessingError.

        Characterizes the symlink-refusal hygiene guard (mirrors koinly_parser):
        a symlink is never transparently followed, preventing an attacker- or
        operator-placed link from redirecting ingestion.
        """
        target = tmp_path / "real_bera_transactions.csv"
        target.write_text(_one_row_csv(), encoding="utf-8")
        link = tmp_path / "bera_transactions_symlink.csv"
        link.symlink_to(target)

        with pytest.raises(FileProcessingError, match="symlink"):
            read_on_chain_rows(link)

    def test_size_cap_exceeded(self, tmp_path) -> None:
        """Given a CSV exceeding the size cap (50 MB), expects FileProcessingError.

        Characterizes the size-cap hygiene guard (mirrors koinly_parser): an
        oversized CSV is rejected before parsing to prevent DoS via an
        attacker-controlled huge file.
        """
        # Build a real file just over the 50 MB cap. Pad the first data row's
        # wallet_label cell so the on-disk size exceeds the limit.
        size_cap = 50 * 1024 * 1024
        # Header + a realistic row minus the padding cell is ~ a few hundred
        # bytes; pad by size_cap to comfortably clear the threshold.
        padding = "X" * (size_cap + 1024)
        padded_row = ",".join([
            _TX_HASH, "1590503", "2025-02-25T13:53:25+00:00", "Testchain",
            _FROM_ADDR, _TO_ADDR, "TST", "", "1000000000000000000", "18",
            "in", "TST", "2100000273000", padding, _WALLET_ADDR,
        ])
        path = tmp_path / "bera_transactions.csv"
        path.write_text(f"{_REAL_HEADER}\n{padded_row}\n", encoding="utf-8")

        assert path.stat().st_size > size_cap  # sanity: the file really is over

        with pytest.raises(FileProcessingError, match="size"):
            read_on_chain_rows(path)
