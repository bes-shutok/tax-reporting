"""Characterization tests for the on-chain JSON-RPC client.

These tests pin the EXISTING behaviour of
``src/tax_reporting/infrastructure/on_chain/rpc_client.py`` via the
documented DI seam ``_http_post_json`` (module docstring lines 12-13:
"tests patch THAT name"). Production is NOT changed by this file.

The retry loop, backoff formula, and redaction surface are exercised
through the seam (and ``rpc_client.time.sleep`` for the backoff test),
keeping the suite network-free and deterministic.
"""

import http.client
import urllib.error

import pytest

from tax_reporting.domain.exceptions import FileProcessingError
from tax_reporting.infrastructure.on_chain import rpc_client
from tax_reporting.infrastructure.on_chain.rpc_client import RpcClient

# Neutral test-only values. The wallet address is a placeholder; it encodes
# no real chain identity.
_ADDRESS = "0x0000000000000000000000000000000000001111"
_RPC_URL = "https://example.invalid/rpc"


class _TransportSpy:
    """Record every call to the ``_http_post_json`` DI seam.

    Captures the exact ``headers`` dict each call received so the redaction
    test can assert on what the transport actually saw. Default behaviour is
    to raise ``URLError`` (transport failure); per-test overrides set
    ``self.responses`` or replace ``self.raise_error``.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict, dict, float]] = []
        # A fixed response returned on EVERY call when ``raise_urLError`` is
        # False. Per-call scripted responses are not needed because the
        # characterization tests pin loop-level behaviour (always-fail,
        # always-error, always-success).
        self.fixed_response: dict = {"result": "0xdeadbeef"}
        self.raise_urLError = True

    def __call__(self, url: str, payload: dict, headers: dict, timeout: float) -> dict:
        # Snapshot headers by value so later mutation cannot rewrite history.
        self.calls.append((url, dict(payload), dict(headers), timeout))
        if self.raise_urLError:
            raise urllib.error.URLError("boom")
        return dict(self.fixed_response)


@pytest.mark.unit
class TestRpcClient:
    """Pin rpc_client retry/backoff/redaction behaviour via the _http_post_json seam."""

    def test_retries_then_raises_after_max_retries(self, monkeypatch):
        # Given - the transport always fails with URLError; sleep is a no-op.
        spy = _TransportSpy()
        spy.raise_urLError = True
        monkeypatch.setattr(rpc_client, "_http_post_json", spy)
        monkeypatch.setattr(rpc_client.time, "sleep", lambda _s: None)
        client = RpcClient(rpc_url=_RPC_URL, max_retries=3)

        # When / Then - raises FileProcessingError matching "transport error".
        with pytest.raises(FileProcessingError, match="transport error"):
            client.get_code(_ADDRESS)

        # Discriminating property: exactly max_retries + 1 transport attempts
        # (attempt starts at 0; retries happen at attempt 0,1,2; attempt 3 raises).
        assert len(spy.calls) == client.max_retries + 1

    def test_json_rpc_error_object_raises(self, monkeypatch):
        # Given - the transport always returns a JSON-RPC error object.
        spy = _TransportSpy()
        spy.raise_urLError = False
        spy.fixed_response = {"error": {"code": -32000, "message": "reverted"}}
        monkeypatch.setattr(rpc_client, "_http_post_json", spy)
        monkeypatch.setattr(rpc_client.time, "sleep", lambda _s: None)
        client = RpcClient(rpc_url=_RPC_URL, max_retries=3)

        # When / Then - a JSON-RPC error object surfaces as FileProcessingError.
        with pytest.raises(FileProcessingError):
            client.get_code(_ADDRESS)

    def test_success_returns_result(self, monkeypatch):
        # Given - the transport returns a JSON-RPC success result.
        spy = _TransportSpy()
        spy.raise_urLError = False
        spy.fixed_response = {"result": "0xdeadbeef"}
        monkeypatch.setattr(rpc_client, "_http_post_json", spy)
        client = RpcClient(rpc_url=_RPC_URL)

        # When
        code = client.get_code(_ADDRESS)

        # Then - the result field is returned verbatim.
        assert code == "0xdeadbeef"

    def test_backoff_grows_exponentially(self, monkeypatch):
        # Given - the transport always fails so every retry backs off once.
        spy = _TransportSpy()
        spy.raise_urLError = True
        monkeypatch.setattr(rpc_client, "_http_post_json", spy)
        sleeps: list[float] = []
        monkeypatch.setattr(rpc_client.time, "sleep", lambda s: sleeps.append(s))
        backoff_base = 0.25
        client = RpcClient(rpc_url=_RPC_URL, max_retries=3, _backoff_base=backoff_base)

        # When / Then - raises after exhausting retries.
        with pytest.raises(FileProcessingError):
            client.get_code(_ADDRESS)

        # _sleep_backoff(attempt) is called with the POST-increment attempt,
        # so for max_retries=3 the loop sleeps at attempt=1,2,3 with durations
        # backoff_base * 2**(attempt-1) == base*1, base*2, base*4. The final
        # failure (attempt >= max_retries) raises WITHOUT a further sleep.
        expected = [backoff_base * (2 ** (a - 1)) for a in (1, 2, 3)]
        assert sleeps == expected

    def test_redact_headers_no_api_key_leak(self, monkeypatch, caplog):
        # DISCREPANCY (documented-vs-actual): the plan's redaction clause
        # claims "the redacted headers used in the request do NOT contain
        # 'secret'". The ACTUAL code (rpc_client._rpc) passes the RAW headers
        # (built by _headers(), which includes ``Authorization: Bearer secret``)
        # straight to _http_post_json; redaction is applied ONLY to the
        # _LOGGER.debug call (line 175: _redact_headers(headers)). So the
        # transport DOES receive the raw secret in its headers argument.
        #
        # Per the task's STOP-and-flag rule we do NOT change production. This
        # test pins the ACTUAL behaviour (raw secret reaches the transport
        # seam) AND verifies the documented invariants that DO hold:
        #   (a) the _redact_headers helper itself masks the secret, and
        #   (b) the secret never reaches a log line at DEBUG level.
        import logging

        spy = _TransportSpy()
        spy.raise_urLError = False
        spy.fixed_response = {"result": "0xdeadbeef"}
        monkeypatch.setattr(rpc_client, "_http_post_json", spy)
        client = RpcClient(rpc_url=_RPC_URL, api_key="secret")

        # When
        with caplog.at_level(logging.DEBUG, logger=rpc_client._LOGGER.name):
            client.get_code(_ADDRESS)

        # Then (a) - _redact_headers masks secret-bearing header values.
        raw_headers = spy.calls[0][2]
        redacted = rpc_client._redact_headers(raw_headers)
        assert "secret" not in " ".join(redacted.values())

        # Then (b) - the secret never appears in any captured log record,
        # because the debug call feeds _redact_headers(headers), not the raw
        # headers, into the format string.
        rendered = " ".join(rec.getMessage() for rec in caplog.records)
        assert "secret" not in rendered

        # FLAG (actual behaviour, contradicts the plan's claim): the raw
        # Authorization header handed to the transport seam DOES contain the
        # literal secret. This assertion documents the actual surface; if
        # production is later changed to redact before the call, flip this to
        # ``assert "secret" not in ...``.
        auth_values = " ".join(
            v for k, v in raw_headers.items() if k.lower() == "authorization"
        )
        assert "secret" in auth_values

    def test_retries_on_http_client_http_exception(self, monkeypatch):
        # Given - the transport always raises http.client.RemoteDisconnected
        # (a subclass of http.client.HTTPException). Sleep is a no-op so the
        # test does not pay real backoff time.
        calls: list[tuple] = []

        def _raise_http_exception(url, payload, headers, timeout):
            calls.append((url, payload, headers, timeout))
            raise http.client.RemoteDisconnected("server closed connection")

        monkeypatch.setattr(rpc_client, "_http_post_json", _raise_http_exception)
        monkeypatch.setattr(rpc_client.time, "sleep", lambda _s: None)
        client = RpcClient(rpc_url=_RPC_URL, max_retries=3)

        # When / Then - HTTPException is retried (not a hard failure on the
        # first attempt), so get_code raises FileProcessingError matching
        # "transport error" only after exhausting retries.
        with pytest.raises(FileProcessingError, match="transport error"):
            client.get_code(_ADDRESS)

        # Discriminating property: exactly max_retries + 1 transport attempts.
        # If HTTPException were NOT retried, it would propagate on the first
        # attempt and this count would be 1, not max_retries + 1.
        assert len(calls) == client.max_retries + 1


@pytest.mark.unit
class TestDecodeAddressSlot:
    """Direct unit tests for the ``_decode_address_slot`` helper.

    ``get_implementation`` delegates to this helper, and every ``test_rpc_client``
    case above drives ``get_code`` (which never reaches it). The ``lp_autodiscovery``
    suite mocks the whole ``RpcClient``, so without these direct tests the four
    decode branches (non-0x prefix, short body, all-zero slot, normal decode)
    would have zero coverage. A regression in the slot slicing (e.g. an
    off-by-one on ``_EVM_ADDRESS_HEX_LEN``) would mis-resolve every proxy
    implementation address and silently break the bytecode_island LP fallback.
    """

    def test_decodes_low_20_bytes_of_full_word(self):
        # A full 32-byte word whose low 20 bytes are 0xab...ab.
        addr_hex = "ab" * 20
        slot = "0x" + "00" * 12 + addr_hex
        assert rpc_client._decode_address_slot(slot) == "0x" + addr_hex

    def test_all_zero_word_returns_sentinel(self):
        # The implementation() call returns a zero word when the proxy points
        # at the zero address; the helper must surface ``"0x"`` (not ``"0x000...0"``).
        assert rpc_client._decode_address_slot("0x" + "00" * 32) == "0x"

    def test_short_body_returns_sentinel(self):
        # A body shorter than 32 bytes (e.g. a reverted/truncated return) cannot
        # hold a full address; return the sentinel rather than slicing garbage.
        assert rpc_client._decode_address_slot("0xdead") == "0x"

    def test_non_hex_prefix_returns_sentinel(self):
        # No ``0x`` prefix (malformed RPC return): return the sentinel instead of
        # raising, so a bad upstream response degrades to ``"0x"`` not a crash.
        assert rpc_client._decode_address_slot("nope") == "0x"

    def test_lowercases_uppercase_address(self):
        # EVM addresses are case-insensitive; the helper normalizes to lowercase
        # so downstream comparisons are byte-identical regardless of checksum casing.
        slot = "0x" + "00" * 12 + "AB" * 20
        assert rpc_client._decode_address_slot(slot) == "0x" + "ab" * 20
