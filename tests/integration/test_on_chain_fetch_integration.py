"""End-to-end integration tests for the on-chain transaction fetcher (Task 7).

These tests drive the FULL orchestrator (:func:`run_on_chain_fetch`) against a
network-free DI-3 HTTP seam. The unit tests already proved the individual
pieces (client pagination, decoder mapping, CSV writer); this file wires them
together to guard the end-to-end contract:

- DI-5 block-range pagination advances the ``startblock`` query param past the
  previous page's max block (NOT a page-count increment), draining the full
  page's boundary block first so a mid-block page cut drops no rows.
- The decoder's date-window filter is exercised through the whole pipeline.
- The consolidated CSV at ``output_dir/<year>/bera_transactions.csv`` is
  sorted by ``block_number`` and carries the correct ``direction`` per the
  wallet address.

Config-free (DI-8): :func:`load_on_chain_wallets` is monkeypatched to return
an artificial wallet list so no real ``resources/source/<year>/chains.json``
is read.

Network-free (DI-3): the transport is the module-level
:func:`tax_reporting.infrastructure.on_chain.etherscan_client._http_get_json`
seam, monkeypatched directly. The client resolves its transport via that
module-level name; the low-level transport module is never referenced.

No real chain identity (DI-2): ``chainid=99999`` is a fictitious test-only
identifier, ``0x0000...1111`` is a placeholder wallet address, and the chain
name / ticker are artificial. No real-chain literals appear here.
"""

from __future__ import annotations

import csv
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from tax_reporting.application.on_chain_config import OnChainWalletConfig

# Module path of the config loader (monkeypatched to avoid repo-root files).
_LOADER = "tax_reporting.application.on_chain_fetcher.load_on_chain_wallets"
# Module path of the DI-3 HTTP seam. The client resolves its transport via this
# module-level name, so the seam is monkeypatched directly (NEVER the low-level
# transport). This is the network-free contract shared with the unit tests.
_HTTP_SEAM = "tax_reporting.infrastructure.on_chain.etherscan_client._http_get_json"
# Module path of the per-year position-token registry loader (the shared
# facade, review r4 F7). run_on_chain_fetch loads the per-year registry for
# nfttx decode gating; patching keeps these tests off the gitignored
# per-user registry file (AGENTS.md crypto-tests rule).
_REGISTRY_LOADER = (
    "tax_reporting.application.on_chain_fetcher.load_position_token_registry_for_year"
)


@pytest.fixture(autouse=True)
def _hermetic_position_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Serve an EMPTY synthetic position-token registry to every test here."""
    from tax_reporting.infrastructure.on_chain.position_token_registry import (
        build_position_token_registry,
    )

    monkeypatch.setattr(
        _REGISTRY_LOADER,
        lambda _year, _override=None, _repo_root=None: build_position_token_registry(
            {"tokens": []}, source="<inline-test>"
        ),
    )

# Artificial test-only values (DI-2 clean: no real chain identity).
_CHAINID = 99999
_ADDRESS = "0x0000000000000000000000000000000000001111"
_OTHER = "0x0000000000000000000000000000000000002222"
_CHAIN = "Examplechain"
_TICKER = "EXM"
_LABEL = "Example Wallet (EXM)"


def _wallet(
    *,
    start_date: date = date(2025, 2, 6),
    end_date: date = date(2025, 12, 31),
) -> OnChainWalletConfig:
    """Return an artificial OnChainWalletConfig (no real chain identity)."""
    return OnChainWalletConfig(
        chain=_CHAIN,
        chainid=_CHAINID,
        label=_LABEL,
        address=_ADDRESS,
        native_ticker=_TICKER,
        start_date=start_date,
        end_date=end_date,
    )


def _ts(day: int) -> str:
    """Return a Unix-seconds timeStamp for 2025-02-{day:02d} (in range by default)."""
    return str(int(datetime(2025, 2, day, 12, 0, 0, tzinfo=UTC).timestamp()))


def _txlist_row(block: int, day: int, *, out: bool = True, hash_: str = "0xtx") -> dict[str, Any]:
    """Build one txlist (native transfer) raw row at the given block/day."""
    return {
        "hash": f"{hash_}-{block}",
        "blockNumber": str(block),
        "timeStamp": _ts(day),
        # 'out' direction when the wallet is the sender.
        "from": _ADDRESS if out else _OTHER,
        "to": _OTHER if out else _ADDRESS,
        "value": "1000000000000000000",
        "gasUsed": "21000",
        "gasPrice": "1000000000",
    }


def _tokentx_row(block: int, day: int, *, out: bool = False, hash_: str = "0xtt") -> dict[str, Any]:
    """Build one tokentx (ERC-20 transfer) raw row at the given block/day."""
    return {
        "hash": f"{hash_}-{block}",
        "blockNumber": str(block),
        "timeStamp": _ts(day),
        "from": _ADDRESS if out else _OTHER,
        "to": _OTHER if out else _ADDRESS,
        "value": "5000000",
        "tokenSymbol": "USDC",
        "tokenDecimal": "6",
        "contractAddress": "0xtoken",
    }


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    """Return (header fieldnames, list of row dicts) from the CSV at ``path``."""
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        fieldnames = list(reader.fieldnames or [])
        rows = [dict(r) for r in reader]
    return fieldnames, rows


@pytest.mark.integration
class TestOnChainFetchIntegration:
    """End-to-end integration tests for run_on_chain_fetch."""

    def test_full_flow_two_pages(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """End-to-end: a FULL txlist page (page_size rows at blocks 100-102)
        -> the boundary-block drain for block 102 -> an advanced txlist page
        (2 rows at blocks 103,104) -> an empty txlist page -> one tokentx row.
        Exercises DI-5 block-range advance + boundary drain through the
        orchestrator and asserts the written CSV.

        The client's default ``page_size`` is patched down to 3 so the first
        3-row page is "full" and the client MUST drain the boundary block
        (102) and then advance ``startblock`` past it (102 -> 103).
        """
        from tax_reporting.application.on_chain_fetcher import run_on_chain_fetch
        from tax_reporting.infrastructure.on_chain.etherscan_client import EtherscanV2Client

        monkeypatch.setattr(_LOADER, lambda _year: [_wallet()])
        # The orchestrator constructs ``EtherscanV2Client(api_key=...,
        # chainid=...)`` with the default page_size (1000). Replace the name
        # the orchestrator holds with a subclass whose page_size default is 3,
        # so a 3-row page is "full" and forces the block-range advance. This
        # keeps the integration test small and deterministic.
        class _SmallPageClient(EtherscanV2Client):
            def __init__(self, *, api_key: str, chainid: int, **kwargs: Any) -> None:
                super().__init__(api_key=api_key, chainid=chainid, page_size=3, **kwargs)

        monkeypatch.setattr(
            "tax_reporting.application.on_chain_fetcher.EtherscanV2Client", _SmallPageClient
        )

        calls: list[dict[str, Any]] = []

        # First txlist page (FULL): 3 rows at blocks 100,101,102.
        # All days are >= 6 so every row falls inside the wallet's date window.
        page_one_rows = [
            _txlist_row(100, 6, out=True, hash_="0xa"),
            _txlist_row(101, 6, out=False, hash_="0xa"),
            _txlist_row(102, 6, out=True, hash_="0xa"),
        ]
        # Boundary-block drain: block 102 holds only its 1 already-seen row
        # (partial page) -> block drained, outer loop advances to 103.
        drain_rows = [_txlist_row(102, 6, out=True, hash_="0xa")]
        # Third txlist call (partial): 2 rows at blocks 103,104 -> terminates.
        page_two_rows = [
            _txlist_row(103, 7, out=True, hash_="0xa"),
            _txlist_row(104, 8, out=False, hash_="0xa"),
        ]
        tokentx_rows = [_tokentx_row(200, 9, out=False, hash_="0xb")]
        txlist_pages: list[list[dict[str, Any]]] = [page_one_rows, drain_rows, page_two_rows]

        def fake_http(url: str, params: dict[str, str | int]) -> dict[str, Any]:
            calls.append(dict(params))
            action = str(params.get("action"))
            if action == "txlist":
                if txlist_pages:
                    consumed = txlist_pages.pop(0)
                    return {"status": "1", "message": "OK", "result": consumed}
                # Empty page -> end of stream.
                return {
                    "status": "0",
                    "message": "No transactions found",
                    "result": [],
                }
            if action == "tokentx":
                # Token transfers: one row then an empty page.
                if tokentx_rows:
                    consumed = tokentx_rows[:]
                    tokentx_rows.clear()
                    return {"status": "1", "message": "OK", "result": consumed}
                return {
                    "status": "0",
                    "message": "No transactions found",
                    "result": [],
                }
            return {"status": "0", "message": "No transactions found", "result": []}

        monkeypatch.setattr(_HTTP_SEAM, fake_http)
        result = run_on_chain_fetch(
            year=2025, output_dir=tmp_path, api_key="test-key"
        )

        # The CSV was written at the documented path.
        assert result is not None
        csv_path = tmp_path / "2025" / "bera_transactions.csv"
        assert csv_path == result
        assert csv_path.is_file()

        fieldnames, rows = _read_csv(csv_path)
        assert "tx_hash" in fieldnames

        # DI-5: full page -> boundary-block drain -> block-range advance.
        # Find the txlist calls in order.
        txlist_calls = [c for c in calls if str(c.get("action")) == "txlist"]
        assert len(txlist_calls) == 3, (
            "expected three txlist calls (full page + boundary drain + advance)"
        )
        assert int(txlist_calls[0]["startblock"]) == 0
        # The drain re-queries the boundary block alone at page 1.
        assert int(txlist_calls[1]["startblock"]) == 102
        assert int(txlist_calls[1]["endblock"]) == 102
        assert int(txlist_calls[1]["page"]) == 1
        # Advance = max block of the full page (102) + 1 = 103, page stays 1.
        assert int(txlist_calls[2]["startblock"]) == 103, (
            "block-range advance: startblock must be max(full page block)+1 = 103"
        )
        assert int(txlist_calls[2]["page"]) == 1, (
            "block-range advance keeps page=1 (not a page-count increment)"
        )

        # All 5 txlist-derived rows (blocks 100-104; block 102 exactly once)
        # + the 1 tokentx row present - the drain's re-fetch added no dup.
        block_numbers = [int(r["block_number"]) for r in rows]
        assert set(block_numbers) == {100, 101, 102, 103, 104, 200}
        assert len(rows) == 6

        # Sorted by block_number ascending (stable: decode order within a block).
        assert block_numbers == sorted(block_numbers)

        # Direction reflects the wallet address vs from/to.
        for row in rows:
            if row["from_address"] == _ADDRESS:
                assert row["direction"] == "out"
            else:
                assert row["direction"] == "in"

    def test_date_range_filter_applied(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """End-to-end date-window filter: given txlist rows whose timestamps
        span OUTSIDE the configured ``[start_date, end_date]`` window, expects
        only the in-range rows to land in the CSV. The filter lives in the
        decoder and is exercised here through the whole pipeline.
        """
        from tax_reporting.application.on_chain_fetcher import run_on_chain_fetch

        # Narrow window: only 2025-06-10 .. 2025-06-10 inclusive.
        wallet = _wallet(start_date=date(2025, 6, 10), end_date=date(2025, 6, 10))
        monkeypatch.setattr(_LOADER, lambda _year: [wallet])

        # Three txlist rows: before, in, and after the window. The 'in' row is
        # sent from the wallet (direction='out'); the others use a third party.
        in_window_ts = str(int(datetime(2025, 6, 10, 12, 0, 0, tzinfo=UTC).timestamp()))
        before_ts = str(int(datetime(2025, 6, 9, 12, 0, 0, tzinfo=UTC).timestamp()))
        after_ts = str(int(datetime(2025, 6, 11, 12, 0, 0, tzinfo=UTC).timestamp()))

        rows_payload = [
            {
                "hash": "0xbefore",
                "blockNumber": "100",
                "timeStamp": before_ts,
                "from": _OTHER,
                "to": _ADDRESS,
                "value": "1000000000000000000",
                "gasUsed": "21000",
                "gasPrice": "1000000000",
            },
            {
                "hash": "0xin",
                "blockNumber": "101",
                "timeStamp": in_window_ts,
                "from": _ADDRESS,
                "to": _OTHER,
                "value": "2000000000000000000",
                "gasUsed": "21000",
                "gasPrice": "1000000000",
            },
            {
                "hash": "0xafter",
                "blockNumber": "102",
                "timeStamp": after_ts,
                "from": _OTHER,
                "to": _ADDRESS,
                "value": "3000000000000000000",
                "gasUsed": "21000",
                "gasPrice": "1000000000",
            },
        ]

        def fake_http(url: str, params: dict[str, str | int]) -> dict[str, Any]:
            action = str(params.get("action"))
            if action == "txlist":
                # Single partial page (fewer than page_size) -> terminates.
                return {"status": "1", "message": "OK", "result": list(rows_payload)}
            # tokentx: empty -> end of stream.
            return {"status": "0", "message": "No transactions found", "result": []}

        monkeypatch.setattr(_HTTP_SEAM, fake_http)
        result = run_on_chain_fetch(
            year=2025, output_dir=tmp_path, api_key="test-key"
        )

        assert result is not None
        _, rows = _read_csv(result)

        # Only the in-window row survives; the out-of-window rows are skipped.
        hashes = {r["tx_hash"] for r in rows}
        assert hashes == {"0xin"}, (
            f"only the in-window row should be in the CSV, got {hashes}"
        )
        assert len(rows) == 1
        assert rows[0]["direction"] == "out"

    def test_full_flow_includes_internal_receives(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """End-to-end: the seam serves txlist + tokentx + txlistinternal; the
        CSV must carry the internal receive row (a native BERA receive via an
        internal call inside a parent tx that also has a token out-leg).
        """
        from tax_reporting.application.on_chain_fetcher import run_on_chain_fetch

        monkeypatch.setattr(_LOADER, lambda _year: [_wallet()])

        txlist_rows = [_txlist_row(100, 6, out=True, hash_="0xa")]
        tokentx_rows = [_tokentx_row(200, 7, out=True, hash_="0xb")]
        # Internal native receive to the wallet inside parent tx 0xc (cluster-2
        # shape). txlistinternal rows carry gasUsed but no gasPrice.
        internal_rows = [
            {
                "hash": "0xc",
                "blockNumber": "100",
                "timeStamp": _ts(6),
                "from": _OTHER,
                "to": _ADDRESS,
                "value": "2500000000000000000",
                "gas": "30000",
                "gasUsed": "30000",
                "type": "call",
            }
        ]

        def fake_http(url: str, params: dict[str, str | int]) -> dict[str, Any]:
            action = str(params.get("action"))
            payloads: dict[str, list[dict[str, Any]]] = {
                "txlist": txlist_rows,
                "tokentx": tokentx_rows,
                "txlistinternal": internal_rows,
            }
            if action in payloads and payloads[action]:
                consumed = payloads[action][:]
                payloads[action].clear()
                return {"status": "1", "message": "OK", "result": consumed}
            return {"status": "0", "message": "No transactions found", "result": []}

        monkeypatch.setattr(_HTTP_SEAM, fake_http)
        result = run_on_chain_fetch(
            year=2025, output_dir=tmp_path, api_key="test-key"
        )

        assert result is not None
        _, rows = _read_csv(result)

        # The internal receive row is present with direction 'in', native
        # asset, and no fee attributed (parent tx gas lives on its txlist row).
        internal_legs = [r for r in rows if r["tx_hash"] == "0xc"]
        assert len(internal_legs) == 1, (
            f"expected the internal receive row in the CSV, got hashes "
            f"{[r['tx_hash'] for r in rows]}"
        )
        leg = internal_legs[0]
        assert leg["direction"] == "in"
        assert leg["asset"] == _TICKER
        assert leg["amount_raw"] == "2500000000000000000"
        assert leg["fee_amount_raw"] == "0"
        # All three endpoints were served.
        assert len(rows) == 3
