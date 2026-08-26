"""Tests for the Etherscan V2 client with block-range pagination.

RED phase: these tests pin the behaviour of ``EtherscanV2Client`` before the
production module ``src/tax_reporting/infrastructure/on_chain/etherscan_client.py``
exists. The DI-3 injectable seam is the module-level ``_http_get_json``: tests
monkeypatch that name rather than the underlying urllib transport directly.

Neutral placeholders are used throughout: ``chainid=99999`` is a fictitious
test-only chain identifier, and ``0x0000...1111`` is a placeholder wallet
address. No real chain identity literals appear here or in the implementation.
"""

import logging

import pytest

from tax_reporting.domain.exceptions import FileProcessingError
from tax_reporting.infrastructure.on_chain.etherscan_client import EtherscanV2Client

# Neutral test-only values. chainid 99999 is fictitious; the wallet address is a
# placeholder. Neither encodes real chain identity (DI-2 clean).
_CHAINID = 99999
_ADDRESS = "0x0000000000000000000000000000000000001111"


def _rows(*blocks: int) -> list[dict]:
    """Build minimal row dicts carrying only ``blockNumber`` (a string, as the API returns)."""
    return [{"blockNumber": str(b)} for b in blocks]


@pytest.mark.unit
class TestEtherscanClient:
    """Test the Etherscan V2 client's pagination, retry, and guard behaviour."""

    def test_fetch_single_page(self, monkeypatch):
        # Given - a page that is NOT full (3 rows but page_size=4)
        calls: list[tuple[str, dict]] = []

        def fake(url: str, params: dict) -> dict:
            calls.append((url, params))
            return {"status": "1", "message": "OK", "result": _rows(100, 101, 102)}

        monkeypatch.setattr(
            "tax_reporting.infrastructure.on_chain.etherscan_client._http_get_json", fake
        )
        client = EtherscanV2Client(api_key="k", chainid=_CHAINID, page_size=4)

        # When
        rows = client.fetch_normal_txs(_ADDRESS)

        # Then - 3 rows returned, single call, no block-range advance needed
        assert len(rows) == 3
        assert len(calls) == 1
        assert calls[0][1]["startblock"] == 0

    def test_fetch_paginates_by_block_range(self, monkeypatch):
        # Given - first call full (page_size=3 rows at blocks 100,101,102),
        # boundary-block drain (block 102 has only its 1 seen row -> partial),
        # then the advanced call partial (blocks 103,104). Proves block-range
        # advance, NOT page-count increment.
        calls: list[tuple[str, dict]] = []
        responses = [
            {"status": "1", "message": "OK", "result": _rows(100, 101, 102)},
            {"status": "1", "message": "OK", "result": _rows(102)},
            {"status": "1", "message": "OK", "result": _rows(103, 104)},
        ]

        def fake(url: str, params: dict) -> dict:
            calls.append((url, params))
            return responses.pop(0)

        monkeypatch.setattr(
            "tax_reporting.infrastructure.on_chain.etherscan_client._http_get_json", fake
        )
        client = EtherscanV2Client(api_key="k", chainid=_CHAINID, page_size=3)

        # When
        rows = client.fetch_normal_txs(_ADDRESS)

        # Then - 5 rows, 3 calls: full page -> boundary drain -> advance.
        assert len(rows) == 5
        assert len(calls) == 3
        # The drain re-queries the boundary block alone (102, 102) at page 1;
        # the 1 row it returns is the already-seen row (sliced off, no dup).
        assert calls[1][1]["startblock"] == 102
        assert calls[1][1]["endblock"] == 102
        assert calls[1][1]["page"] == 1
        # The outer advance is max(blockNumber of full page)+1 = 103, and
        # page stays at 1 (block-range advance, not page-count increment).
        assert calls[2][1]["startblock"] == 103
        assert calls[2][1]["endblock"] == 99999999
        assert calls[2][1]["page"] == 1

    def test_terminates_at_empty_page(self, monkeypatch):
        # Given - a full page, a boundary drain that comes back EMPTY
        # ("No transactions found"), and an advanced call that is also empty.
        # The loop must stop after the second empty page; no infinite loop.
        responses = [
            {"status": "1", "message": "OK", "result": _rows(100, 101, 102)},
            {"status": "0", "message": "No transactions found", "result": []},
            {"status": "0", "message": "No transactions found", "result": []},
        ]
        calls: list[tuple[str, dict]] = []

        def fake(url: str, params: dict) -> dict:
            calls.append((url, params))
            return responses.pop(0)

        monkeypatch.setattr(
            "tax_reporting.infrastructure.on_chain.etherscan_client._http_get_json", fake
        )
        client = EtherscanV2Client(api_key="k", chainid=_CHAINID, page_size=3)

        # When
        rows = client.fetch_normal_txs(_ADDRESS)

        # Then - loop stopped after the empty pages; 3 rows kept.
        assert len(rows) == 3
        assert len(calls) == 3

    def test_rate_limit_retried_then_succeeds(self, monkeypatch):
        # Given - a rate-limit response then a success page.
        responses = [
            {"status": "0", "result": "Max rate limit reached"},
            {"status": "1", "message": "OK", "result": _rows(100, 101)},
        ]
        calls: list[tuple[str, dict]] = []

        def fake(url: str, params: dict) -> dict:
            calls.append((url, params))
            return responses.pop(0)

        monkeypatch.setattr(
            "tax_reporting.infrastructure.on_chain.etherscan_client._http_get_json", fake
        )
        # Patch time.sleep to no-op so the test does not actually sleep.
        monkeypatch.setattr(
            "tax_reporting.infrastructure.on_chain.etherscan_client.time.sleep", lambda _s: None
        )
        client = EtherscanV2Client(api_key="k", chainid=_CHAINID, page_size=10)

        # When
        rows = client.fetch_normal_txs(_ADDRESS)

        # Then - retried then succeeded; seam called >= 2 times.
        assert len(rows) == 2
        assert len(calls) >= 2

    def test_rate_limit_persistent_raises(self, monkeypatch):
        # Given - a persistent rate-limit response that exceeds max retries.
        def fake(url: str, params: dict) -> dict:
            return {"status": "0", "result": "Max rate limit reached"}

        monkeypatch.setattr(
            "tax_reporting.infrastructure.on_chain.etherscan_client._http_get_json", fake
        )
        monkeypatch.setattr(
            "tax_reporting.infrastructure.on_chain.etherscan_client.time.sleep", lambda _s: None
        )
        client = EtherscanV2Client(api_key="k", chainid=_CHAINID, page_size=10, max_retries=2)

        # When / Then - FileProcessingError naming rate limit.
        with pytest.raises(FileProcessingError, match="rate limit"):
            client.fetch_normal_txs(_ADDRESS)

    def test_api_key_missing_in_response_raises(self, monkeypatch):
        # Given - an API-key error in the response (config problem, not transient).
        def fake(url: str, params: dict) -> dict:
            return {"status": "0", "result": "Missing/Invalid API Key"}

        monkeypatch.setattr(
            "tax_reporting.infrastructure.on_chain.etherscan_client._http_get_json", fake
        )
        client = EtherscanV2Client(api_key="k", chainid=_CHAINID, page_size=10)

        # When / Then - FileProcessingError naming the API key problem.
        with pytest.raises(FileProcessingError, match="API [Kk]ey"):
            client.fetch_normal_txs(_ADDRESS)

    def test_max_rows_guard(self, monkeypatch, caplog):
        # Given - an infinite-full-page sequence (every call returns a full page).
        def fake(url: str, params: dict) -> dict:
            # Each page returns page_size rows; blockNumbers climb so advance keeps going.
            start = int(params["startblock"])
            return {
                "status": "1",
                "message": "OK",
                "result": _rows(start, start + 1, start + 2),
            }

        monkeypatch.setattr(
            "tax_reporting.infrastructure.on_chain.etherscan_client._http_get_json", fake
        )
        client = EtherscanV2Client(
            api_key="k", chainid=_CHAINID, page_size=3, max_rows=6
        )

        # When
        with caplog.at_level(logging.WARNING):
            rows = client.fetch_normal_txs(_ADDRESS)

        # Then - stops at the max-rows ceiling and logs a WARNING substring.
        assert len(rows) == 6
        assert any("max_rows" in rec.message for rec in caplog.records)

    def test_full_page_cutting_mid_block_returns_all_boundary_block_rows(
        self, monkeypatch
    ):
        # The claim-tx shape: a FULL page ends INSIDE a block that has more
        # rows (page cut after 2 of block 102's 5 rows). Advancing to
        # startblock=103 silently drops the remaining 3 rows of block 102;
        # the client must drain the boundary block instead.
        responses: dict[tuple[int, int, int], dict] = {
            (0, 99999999, 1): {"status": "1", "message": "OK", "result": _rows(100, 102, 102)},
            (102, 102, 1): {"status": "1", "message": "OK", "result": _rows(102, 102, 102)},
            (102, 102, 2): {"status": "1", "message": "OK", "result": _rows(102, 102)},
            (103, 99999999, 1): {"status": "0", "message": "No transactions found", "result": []},
        }
        calls: list[tuple[str, dict]] = []

        def fake(url: str, params: dict) -> dict:
            calls.append((url, params))
            key = (int(params["startblock"]), int(params["endblock"]), int(params["page"]))
            return responses[key]

        monkeypatch.setattr(
            "tax_reporting.infrastructure.on_chain.etherscan_client._http_get_json", fake
        )
        client = EtherscanV2Client(api_key="k", chainid=_CHAINID, page_size=3)

        rows = client.fetch_token_transfers(_ADDRESS)

        block_counts = {b: sum(1 for r in rows if r["blockNumber"] == str(b)) for b in (100, 102)}
        assert block_counts == {100: 1, 102: 5}, (
            f"boundary block 102 must yield all 5 rows, got {block_counts}"
        )

    def test_whole_page_single_block_pages_within_block(self, monkeypatch):
        # A full page consisting ENTIRELY of one block's rows must continue
        # INSIDE that block at page=2 (not re-fetch page=1 and duplicate, not
        # advance past the block and drop the tail).
        responses: dict[tuple[int, int, int], dict] = {
            (0, 99999999, 1): {"status": "1", "message": "OK", "result": _rows(102, 102, 102)},
            (102, 102, 2): {"status": "1", "message": "OK", "result": _rows(102, 102)},
            (103, 99999999, 1): {"status": "0", "message": "No transactions found", "result": []},
        }
        calls: list[tuple[str, dict]] = []

        def fake(url: str, params: dict) -> dict:
            calls.append((url, params))
            key = (int(params["startblock"]), int(params["endblock"]), int(params["page"]))
            return responses[key]

        monkeypatch.setattr(
            "tax_reporting.infrastructure.on_chain.etherscan_client._http_get_json", fake
        )
        client = EtherscanV2Client(api_key="k", chainid=_CHAINID, page_size=3)

        rows = client.fetch_token_transfers(_ADDRESS)

        assert len(rows) == 5, f"block 102 has 5 rows total, got {len(rows)}"
        assert all(r["blockNumber"] == "102" for r in rows)

    def test_exact_multiple_block_drain_ends_on_empty_page(self, monkeypatch):
        # Block 102 has exactly 2*page_size rows: every drain page comes back
        # FULL, so end-of-block is signalled only by the extra empty page
        # (accepted semantics, mirroring r1 F8 for the outer loop).
        responses: dict[tuple[int, int, int], dict] = {
            (0, 99999999, 1): {"status": "1", "message": "OK", "result": _rows(102, 102, 102)},
            (102, 102, 2): {"status": "1", "message": "OK", "result": _rows(102, 102, 102)},
            (102, 102, 3): {"status": "0", "message": "No transactions found", "result": []},
            (103, 99999999, 1): {"status": "0", "message": "No transactions found", "result": []},
        }

        def fake(url: str, params: dict) -> dict:
            key = (int(params["startblock"]), int(params["endblock"]), int(params["page"]))
            return responses[key]

        monkeypatch.setattr(
            "tax_reporting.infrastructure.on_chain.etherscan_client._http_get_json", fake
        )
        client = EtherscanV2Client(api_key="k", chainid=_CHAINID, page_size=3)

        rows = client.fetch_token_transfers(_ADDRESS)

        assert len(rows) == 6, f"block 102 has exactly 6 rows, got {len(rows)}"

    def test_boundary_drain_end_of_block_is_quiet(self, monkeypatch, caplog):
        # Review r2 F6: when the boundary block's total row count exactly
        # equals ``held`` (the normal end-of-block path), the single-block
        # page returns exactly the already-held rows and ``take`` is empty -
        # that must be a QUIET (DEBUG) return, not a WARNING, so operators
        # are not trained to ignore the module's warnings.
        responses: dict[tuple[int, int, int], dict] = {
            (0, 99999999, 1): {"status": "1", "message": "OK", "result": _rows(100, 102, 102)},
            # Block 102 has exactly 2 rows (both already held): drain page 1
            # returns them, skip=2 slices them all off.
            (102, 102, 1): {"status": "1", "message": "OK", "result": _rows(102, 102)},
            (103, 99999999, 1): {"status": "0", "message": "No transactions found", "result": []},
        }

        def fake(url: str, params: dict) -> dict:
            key = (int(params["startblock"]), int(params["endblock"]), int(params["page"]))
            return responses[key]

        monkeypatch.setattr(
            "tax_reporting.infrastructure.on_chain.etherscan_client._http_get_json", fake
        )
        client = EtherscanV2Client(api_key="k", chainid=_CHAINID, page_size=3)

        with caplog.at_level(logging.WARNING):
            rows = client.fetch_token_transfers(_ADDRESS)

        assert len(rows) == 3
        assert not any("no progress" in rec.message for rec in caplog.records), (
            "normal end-of-block drain completion must not log a WARNING"
        )

    def test_boundary_drain_anomalous_repeat_warns_of_row_loss(self, monkeypatch, caplog):
        # Review r2 F15: the anomalous arm of the no-progress guard (the page
        # returns FEWER rows than already held) keeps its WARNING, and the
        # message must name the potential row loss.
        responses: dict[tuple[int, int, int], dict] = {
            (0, 99999999, 1): {"status": "1", "message": "OK", "result": _rows(100, 102, 102)},
            # Anomalous: only 1 row returned where 2 were already held.
            (102, 102, 1): {"status": "1", "message": "OK", "result": _rows(102)},
            (103, 99999999, 1): {"status": "0", "message": "No transactions found", "result": []},
        }

        def fake(url: str, params: dict) -> dict:
            key = (int(params["startblock"]), int(params["endblock"]), int(params["page"]))
            return responses[key]

        monkeypatch.setattr(
            "tax_reporting.infrastructure.on_chain.etherscan_client._http_get_json", fake
        )
        client = EtherscanV2Client(api_key="k", chainid=_CHAINID, page_size=3)

        with caplog.at_level(logging.WARNING):
            rows = client.fetch_token_transfers(_ADDRESS)

        assert len(rows) == 3
        msgs = [rec.message for rec in caplog.records if "no progress" in rec.message]
        assert msgs, "expected the anomalous no-progress WARNING"
        assert "will not be fetched this run" in msgs[0], (
            "the WARNING must name the potential row loss"
        )

    def test_boundary_drain_respects_max_rows(self, monkeypatch, caplog):
        # The max_rows ceiling must also bind INSIDE the boundary-block drain
        # (a single pathological block must not bypass the runaway guard).
        responses: dict[tuple[int, int, int], dict] = {
            (0, 99999999, 1): {"status": "1", "message": "OK", "result": _rows(100, 102, 102)},
            (102, 102, 1): {"status": "1", "message": "OK", "result": _rows(102, 102, 102)},
        }

        def fake(url: str, params: dict) -> dict:
            key = (int(params["startblock"]), int(params["endblock"]), int(params["page"]))
            return responses[key]

        monkeypatch.setattr(
            "tax_reporting.infrastructure.on_chain.etherscan_client._http_get_json", fake
        )
        client = EtherscanV2Client(api_key="k", chainid=_CHAINID, page_size=3, max_rows=4)

        with caplog.at_level(logging.WARNING):
            rows = client.fetch_token_transfers(_ADDRESS)

        assert len(rows) == 4
        assert any("max_rows" in rec.message for rec in caplog.records)

    def test_fetch_internal_txs_uses_block_pagination(self, monkeypatch):
        # txlistinternal must reuse the SAME block-range + boundary-drain loop
        # as fetch_normal_txs: full page (page_size=3 at blocks 100,101,102),
        # boundary-block drain (block 102 has only its 1 seen row -> partial),
        # then the advanced call partial (blocks 103, 104).
        calls: list[tuple[str, dict]] = []
        responses = [
            {"status": "1", "message": "OK", "result": _rows(100, 101, 102)},
            {"status": "1", "message": "OK", "result": _rows(102)},
            {"status": "1", "message": "OK", "result": _rows(103, 104)},
        ]

        def fake(url: str, params: dict) -> dict:
            calls.append((url, params))
            return responses.pop(0)

        monkeypatch.setattr(
            "tax_reporting.infrastructure.on_chain.etherscan_client._http_get_json", fake
        )
        client = EtherscanV2Client(api_key="k", chainid=_CHAINID, page_size=3)

        # When
        rows = client.fetch_internal_txs(_ADDRESS)

        # Then - 5 rows, 3 calls, all with action=txlistinternal; the drain
        # re-queries the boundary block alone and the outer loop advances to
        # max(block)+1 with page=1 (block-range advance, not page increment).
        assert len(rows) == 5
        assert len(calls) == 3
        assert all(c[1]["action"] == "txlistinternal" for c in calls)
        assert calls[1][1]["startblock"] == 102
        assert calls[1][1]["endblock"] == 102
        assert calls[1][1]["page"] == 1
        assert calls[2][1]["startblock"] == 103
        assert calls[2][1]["endblock"] == 99999999
        assert calls[2][1]["page"] == 1

    def test_fetch_internal_txs_boundary_drain(self, monkeypatch):
        # A FULL txlistinternal page ends INSIDE a block that has more internal
        # rows (page cut after 2 of block 102's 5 rows); the boundary block must
        # be drained so no rows are dropped (mirrors the tokentx drain tests).
        responses: dict[tuple[int, int, int], dict] = {
            (0, 99999999, 1): {"status": "1", "message": "OK", "result": _rows(100, 102, 102)},
            (102, 102, 1): {"status": "1", "message": "OK", "result": _rows(102, 102, 102)},
            (102, 102, 2): {"status": "1", "message": "OK", "result": _rows(102, 102)},
            (103, 99999999, 1): {"status": "0", "message": "No transactions found", "result": []},
        }
        calls: list[tuple[str, dict]] = []

        def fake(url: str, params: dict) -> dict:
            calls.append((url, params))
            key = (int(params["startblock"]), int(params["endblock"]), int(params["page"]))
            return responses[key]

        monkeypatch.setattr(
            "tax_reporting.infrastructure.on_chain.etherscan_client._http_get_json", fake
        )
        client = EtherscanV2Client(api_key="k", chainid=_CHAINID, page_size=3)

        rows = client.fetch_internal_txs(_ADDRESS)

        block_counts = {b: sum(1 for r in rows if r["blockNumber"] == str(b)) for b in (100, 102)}
        assert block_counts == {100: 1, 102: 5}, (
            f"boundary block 102 must yield all 5 internal rows, got {block_counts}"
        )

    def test_fetch_nft_transfers_uses_tokennfttx_action(self, monkeypatch):
        # The NFT surface must reuse the SAME block-range + boundary-drain
        # machinery as the other actions: full page (page_size=3 at blocks
        # 100,101,102), boundary-block drain (block 102 has only its 1 seen
        # row -> partial), then the advanced call partial (blocks 103, 104).
        # Etherscan V2's account action for ERC-721 transfers is
        # ``tokennfttx``; the ``nfttx`` name used earlier is rejected with
        # "Error! Missing Or invalid Action name" (verified against the live
        # V2 API 2026-08-25), which the client silently read as end-of-stream.
        calls: list[tuple[str, dict]] = []
        responses = [
            {"status": "1", "message": "OK", "result": _rows(100, 101, 102)},
            {"status": "1", "message": "OK", "result": _rows(102)},
            {"status": "1", "message": "OK", "result": _rows(103, 104)},
        ]

        def fake(url: str, params: dict) -> dict:
            calls.append((url, params))
            return responses.pop(0)

        monkeypatch.setattr(
            "tax_reporting.infrastructure.on_chain.etherscan_client._http_get_json", fake
        )
        client = EtherscanV2Client(api_key="k", chainid=_CHAINID, page_size=3)

        # When
        rows = client.fetch_nft_transfers(_ADDRESS)

        # Then - 5 rows, 3 calls, all with action=tokennfttx; the drain re-queries
        # the boundary block alone and the outer loop advances to max(block)+1
        # with page=1 (block-range advance, not page increment).
        assert len(rows) == 5
        assert len(calls) == 3
        assert all(c[1]["action"] == "tokennfttx" for c in calls)
        assert calls[1][1]["startblock"] == 102
        assert calls[1][1]["endblock"] == 102
        assert calls[1][1]["page"] == 1
        assert calls[2][1]["startblock"] == 103
        assert calls[2][1]["endblock"] == 99999999
        assert calls[2][1]["page"] == 1

    def test_status0_error_text_raises_instead_of_silent_empty(self, monkeypatch):
        # A status:"0" payload whose result is an ERROR STRING (e.g. the
        # live-verified "Error! Missing Or invalid Action name" the V2 API
        # returns for a bad action) is NOT end-of-stream: silently treating
        # it as such made an invalid action name look like an empty wallet
        # (the nfttx no-op bug, found on real data 2026-08-25). It must
        # raise FileProcessingError (DI-1 fail-loud), not return [].
        def fake(url: str, params: dict) -> dict:
            return {
                "status": "0",
                "message": "NOTOK",
                "result": "Error! Missing Or invalid Action name",
            }

        monkeypatch.setattr(
            "tax_reporting.infrastructure.on_chain.etherscan_client._http_get_json", fake
        )
        client = EtherscanV2Client(api_key="k", chainid=_CHAINID)

        with pytest.raises(FileProcessingError, match=r"(?i)missing or invalid action name"):
            client.fetch_nft_transfers(_ADDRESS)

    def test_status0_no_rows_string_result_still_terminates(self, monkeypatch):
        # The string-result variant of the documented empty response ("No
        # transactions found" in BOTH message and result) stays a legitimate
        # end-of-stream: rows fetched so far are returned, nothing raises.
        responses = [
            {"status": "1", "message": "OK", "result": _rows(100)},
            {"status": "0", "message": "No transactions found", "result": "No transactions found"},
        ]

        def fake(url: str, params: dict) -> dict:
            return responses.pop(0)

        monkeypatch.setattr(
            "tax_reporting.infrastructure.on_chain.etherscan_client._http_get_json", fake
        )
        client = EtherscanV2Client(api_key="k", chainid=_CHAINID, page_size=3)

        rows = client.fetch_token_transfers(_ADDRESS)

        assert len(rows) == 1

    def test_status0_nonempty_list_warns_and_terminates(self, monkeypatch, caplog):
        # Review r1 F2: a status:"0" payload carrying a NON-EMPTY result list
        # is an anomalous shape the old catch-all silently dropped; the guard
        # must still terminate the stream (rows are already accumulated) but
        # WARNING, naming the dropped page - never a silent loss.
        responses = [
            {"status": "1", "message": "OK", "result": _rows(100, 101)},
            {"status": "0", "message": "NOTOK", "result": _rows(101, 102)},
            {"status": "0", "message": "No transactions found", "result": []},
        ]

        def fake(url: str, params: dict) -> dict:
            return responses.pop(0)

        monkeypatch.setattr(
            "tax_reporting.infrastructure.on_chain.etherscan_client._http_get_json", fake
        )
        client = EtherscanV2Client(api_key="k", chainid=_CHAINID, page_size=2)

        with caplog.at_level(logging.WARNING, logger=EtherscanV2Client.__module__):
            rows = client.fetch_token_transfers(_ADDRESS)

        assert len(rows) == 2  # the accumulated page survives; the anomalous page ends the stream
        assert any(
            "status=0" in rec.getMessage() and "2 result row" in rec.getMessage()
            for rec in caplog.records
        ), "expected a WARNING naming the dropped status-0 non-empty page"

    @pytest.mark.parametrize(
        "payload",
        [
            {"status": "0", "message": "No transactions found", "result": ""},
            {"status": "0", "message": "NOTOK", "result": "No transactions found"},
            {"status": "0", "message": "No transactions found"},  # result key absent -> None
            {"status": "0", "message": "", "result": ""},  # empty text everywhere
            {"status": "0"},  # no message key, no result key
        ],
    )
    def test_status0_benign_empty_shapes_terminate(self, monkeypatch, payload):
        # Review r1 F5/F7 (benign-empty rule refined r3): each benign shape
        # terminates on its OWN signal - marker in result only, marker in
        # message only (with an absent result), or an EMPTY failure text
        # (no result string and no message). A single-field regression in
        # the marker check fails the result-only case; a narrowing of the
        # benign-empty rule fails the last two.
        monkeypatch.setattr(
            "tax_reporting.infrastructure.on_chain.etherscan_client._http_get_json",
            lambda _url, _params: payload,
        )
        client = EtherscanV2Client(api_key="k", chainid=_CHAINID)

        assert client.fetch_token_transfers(_ADDRESS) == []

    @pytest.mark.parametrize(
        "payload",
        [
            # Review r3 (risk): an error string carried by MESSAGE with an
            # EMPTY result cell - the earlier empty-result-first rule would
            # have read this as a benign empty page in BOTH loops.
            {"status": "0", "message": "Error! Missing Or invalid Action name", "result": ""},
            # r2's former benign case, reversed by the r3 rule: a non-marker
            # message with an empty result is NOT provably empty -> fail loud.
            {"status": "0", "message": "NOTOK", "result": ""},
        ],
    )
    def test_status0_message_borne_error_with_empty_result_raises(self, monkeypatch, payload):
        monkeypatch.setattr(
            "tax_reporting.infrastructure.on_chain.etherscan_client._http_get_json",
            lambda _url, _params: payload,
        )
        client = EtherscanV2Client(api_key="k", chainid=_CHAINID)

        with pytest.raises(FileProcessingError, match=r"(?i)action name|notok"):
            client.fetch_token_transfers(_ADDRESS)

    def test_status0_api_key_marker_with_empty_result_raises_before_benign(self, monkeypatch):
        # Review r3 (testing): the API-key hoist must precede the benign
        # empty-text return; this payload shape would slip through a
        # reordered guard.
        monkeypatch.setattr(
            "tax_reporting.infrastructure.on_chain.etherscan_client._http_get_json",
            lambda _url, _params: {
                "status": "0",
                "message": "Missing/Invalid API Key",
                "result": "",
            },
        )
        client = EtherscanV2Client(api_key="k", chainid=_CHAINID)

        with pytest.raises(FileProcessingError, match=r"(?i)api key"):
            client.fetch_internal_txs(_ADDRESS)  # drain-reachable action

    def test_status0_unrecognized_result_type_raises(self, monkeypatch):
        # Review r4 (risk): a status-0 payload whose result is neither a
        # string, a list, nor absent is anomalous; it must fail loud rather
        # than read as an empty text.
        monkeypatch.setattr(
            "tax_reporting.infrastructure.on_chain.etherscan_client._http_get_json",
            lambda _url, _params: {"status": "0", "message": "NOTOK", "result": {"err": 1}},
        )
        client = EtherscanV2Client(api_key="k", chainid=_CHAINID)

        with pytest.raises(FileProcessingError, match="unrecognized result type"):
            client.fetch_token_transfers(_ADDRESS)

    def test_boundary_drain_status0_error_text_raises(self, monkeypatch):
        # Same fail-loud contract inside the boundary-block drain: a NOTOK
        # error string during the drain must raise, not silently end the
        # block (which would drop the block's remaining rows).
        responses: dict[tuple[int, int, int], dict] = {
            (0, 99999999, 1): {
                "status": "1",
                "message": "OK",
                "result": _rows(102, 102, 102),
            },
            # The outer page consumed all of block 102's page-1 rows, so the
            # drain's first request is page 2 (held // page_size + 1).
            (102, 102, 2): {
                "status": "0",
                "message": "NOTOK",
                "result": "Error! Missing Or invalid Action name",
            },
        }

        def fake(url: str, params: dict) -> dict:
            key = (int(params["startblock"]), int(params["endblock"]), int(params["page"]))
            return responses[key]

        monkeypatch.setattr(
            "tax_reporting.infrastructure.on_chain.etherscan_client._http_get_json", fake
        )
        client = EtherscanV2Client(api_key="k", chainid=_CHAINID, page_size=3)

        with pytest.raises(FileProcessingError, match=r"(?i)missing or invalid action name"):
            client.fetch_internal_txs(_ADDRESS)

    def test_malformed_block_number_row_is_skipped_not_fatal(self, monkeypatch, caplog):
        # Review r3 F3: one row on a FULL page missing blockNumber must be
        # WARNING-skipped (never abort the wallet fetch); the boundary block
        # is computed from the remaining rows and pagination proceeds.
        responses: dict[tuple[int, int, int], dict] = {
            (0, 99999999, 1): {
                "status": "1",
                "message": "OK",
                "result": [
                    {"hash": "0xbad"},  # no blockNumber at all
                    {"blockNumber": "101", "hash": "0xok1"},
                    {"blockNumber": "102", "hash": "0xok2"},
                ],
            },
            (102, 102, 1): {"status": "1", "message": "OK", "result": _rows(102)},
            (103, 99999999, 1): {"status": "0", "message": "No transactions found", "result": []},
        }

        def fake(url: str, params: dict) -> dict:
            key = (int(params["startblock"]), int(params["endblock"]), int(params["page"]))
            return responses[key]

        monkeypatch.setattr(
            "tax_reporting.infrastructure.on_chain.etherscan_client._http_get_json", fake
        )
        client = EtherscanV2Client(api_key="k", chainid=_CHAINID, page_size=3)

        with caplog.at_level(logging.WARNING):
            rows = client.fetch_internal_txs(_ADDRESS)

        # All 3 rows come back (including the malformed one); boundary came
        # from the valid rows (drain queried block 102 alone), not a crash.
        assert len(rows) == 3
        assert any("malformed/missing blockNumber" in rec.message for rec in caplog.records)

    def test_all_rows_malformed_block_number_raises(self, monkeypatch):
        # Review r3 F3 (fail-loud arm): a FULL page where EVERY row has a
        # malformed blockNumber cannot resolve the boundary block -> raise
        # FileProcessingError rather than guessing the block range.
        def fake(url: str, params: dict) -> dict:
            return {
                "status": "1",
                "message": "OK",
                "result": [{"hash": "0xbad1"}, {"hash": "0xbad2"}, {"hash": "0xbad3"}],
            }

        monkeypatch.setattr(
            "tax_reporting.infrastructure.on_chain.etherscan_client._http_get_json", fake
        )
        client = EtherscanV2Client(api_key="k", chainid=_CHAINID, page_size=3)

        with pytest.raises(FileProcessingError, match="Cannot resolve the boundary block"):
            client.fetch_internal_txs(_ADDRESS)

    def test_fetches_both_txlist_and_tokentx(self, monkeypatch):
        # Given - the client must issue calls for BOTH actions.
        actions_seen: list[str] = []

        def fake(url: str, params: dict) -> dict:
            actions_seen.append(params["action"])
            if params["action"] == "txlist":
                return {"status": "1", "message": "OK", "result": _rows(100)}
            return {"status": "1", "message": "OK", "result": _rows(101, 102)}

        monkeypatch.setattr(
            "tax_reporting.infrastructure.on_chain.etherscan_client._http_get_json", fake
        )
        client = EtherscanV2Client(api_key="k", chainid=_CHAINID, page_size=10)

        # When
        normal = client.fetch_normal_txs(_ADDRESS)
        tokens = client.fetch_token_transfers(_ADDRESS)

        # Then - both actions were issued and the distinct row sets returned.
        assert "txlist" in actions_seen
        assert "tokentx" in actions_seen
        assert len(normal) == 1
        assert len(tokens) == 2
