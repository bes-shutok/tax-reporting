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
        # second call partial (blocks 103,104). Proves block-range advance,
        # NOT page-count increment.
        calls: list[tuple[str, dict]] = []
        responses = [
            {"status": "1", "message": "OK", "result": _rows(100, 101, 102)},
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

        # Then - 5 rows, 2 calls, second call's startblock advanced to 103
        assert len(rows) == 5
        assert len(calls) == 2
        # The advance is max(blockNumber of full page)+1 = 102+1 = 103, and
        # page stays at 1 (block-range advance, not page-count increment).
        assert calls[1][1]["startblock"] == 103
        assert calls[1][1]["page"] == 1

    def test_terminates_at_empty_page(self, monkeypatch):
        # Given - a sequence ending in an empty "No transactions found" page.
        responses = [
            {"status": "1", "message": "OK", "result": _rows(100, 101, 102)},
            {"status": "0", "message": "No transactions found", "result": []},
        ]
        calls: list[tuple[str, dict]] = []

        def fake(url: str, params: dict) -> dict:
            calls.append((url, params))
            return responses.pop(0)

        monkeypatch.setattr(
            "tax_reporting.infrastructure.on_chain.etherscan_client._http_get_json", fake
        )
        # page_size large enough that the first page is partial -> would normally
        # terminate after page 1; but we want to also exercise the empty-page path,
        # so make page_size exactly 3 (full) then empty.
        client = EtherscanV2Client(api_key="k", chainid=_CHAINID, page_size=3)

        # When
        rows = client.fetch_normal_txs(_ADDRESS)

        # Then - loop stopped after the empty page; no infinite loop.
        assert len(rows) == 3
        assert len(calls) == 2

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
