"""JSON-RPC client for the LP-token bytecode fallback (Task 8, decision #11).

A thin EVM JSON-RPC client exposing the two read calls the LP-token
autodiscovery bytecode fallback needs:

- ``eth_getCode(address, "latest")`` -> runtime bytecode hex (for V2-pair
  runtime-bytecode fingerprinting).
- ``implementation()`` -> the impl address an EIP-1167 minimal proxy
  delegates to (for KodiakIsland / Bault detection).

This module mirrors :mod:`infrastructure.on_chain.etherscan_client` for
retry/backoff/timeout/secret-redaction. The DI seam is
:func:`_http_post_json`: tests patch THAT name (never urllib/urlopen
directly) so the unit tests stay network-free and deterministic.

Secret hygiene: the JSON-RPC payload may carry an API key in a header
(``Authorization: Bearer ...`` or ``x-api-key``). Whatever is in
:data:`_REDACTED_HEADERS` is masked before any payload is logged.

Hashing note (decision logged in the Task 8 execution log): the runtime
bytecode fingerprint itself is computed by the caller
(:mod:`lp_autodiscovery`), not here. This client only fetches raw bytes.
"""

from __future__ import annotations

import http.client
import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from tax_reporting.domain.exceptions import FileProcessingError

_LOGGER = logging.getLogger(__name__)

# JSON-RPC call id counter is module-local and per-call incremented; not a
# security-sensitive value.
_BACKOFF_BASE_SECONDS = 0.1

# EVM word (32 bytes) hex length, and an EVM address (20 bytes) hex length.
# Used by _decode_address_slot to slice an EIP-1967 implementation slot.
_EVM_WORD_HEX_LEN = 64
_EVM_ADDRESS_HEX_LEN = 40

# Headers whose values are masked in any debug log (never log the API key).
_REDACTED_HEADERS: frozenset[str] = frozenset({"authorization", "x-api-key"})


def _redact_headers(headers: dict[str, str]) -> dict[str, str]:
    """Return a debug-safe copy of ``headers`` with secret headers masked.

    Any header whose lower-cased name is in :data:`_REDACTED_HEADERS` is
    replaced with ``"***REDACTED***"`` so the raw API key never reaches a
    log line. Mirrors :func:`etherscan_client._redact_params`.
    """
    redacted: dict[str, str] = {}
    for name, value in headers.items():
        redacted[name] = "***REDACTED***" if name.lower() in _REDACTED_HEADERS else value
    return redacted


def _http_post_json(
    url: str, payload: dict, headers: dict[str, str], timeout: float
) -> dict:
    """POST a JSON-RPC request and parse the JSON response.

    The module-level DI seam: tests patch THIS name rather than
    ``urllib``/``urlopen`` directly, keeping the transport swappable and
    the unit tests network-free.
    """
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(  # noqa: S310 - trusted configured RPC host
        url, data=body, headers=headers, method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:  # noqa: S310
        raw = response.read()
    return json.loads(raw)


@dataclass
class RpcClient:
    """A minimal EVM JSON-RPC client for ``eth_getCode`` + ``implementation()``.

    Mirrors :class:`etherscan_client.EtherscanV2Client` for
    retry/backoff/timeout/secret-redaction. Two read calls are exposed;
    both honour ``max_retries`` and ``_backoff_base``.

    Attributes:
        rpc_url: The JSON-RPC endpoint (e.g. a Berachain RPC).
        api_key: Optional bearer/api-key secret. Redacted in logs. When
            empty, no auth header is sent.
        timeout: Per-call timeout in seconds (honoured by urllib).
        max_retries: Max transient-error retries before raising.
        base_url: (Kept for symmetry with EtherscanV2Client; alias of rpc_url.)
    """

    rpc_url: str
    api_key: str = ""
    timeout: float = 10.0
    max_retries: int = 3
    _backoff_base: float = field(default=_BACKOFF_BASE_SECONDS, repr=False)
    # Module-level JSON-RPC call id counter; per-call incremented. Not
    # security-sensitive.
    _next_id: int = field(default=1, repr=False)

    # ---- public read API ------------------------------------------------

    def get_code(self, address: str) -> str:
        """Return the runtime bytecode (``eth_getCode``) as a ``0x``-hex string.

        Returns ``"0x"`` for an EOA (no code). Used by the V2-pair runtime
        bytecode fingerprint fallback.
        """
        result = self._rpc("eth_getCode", [address, "latest"])
        if isinstance(result, str):
            return result
        raise FileProcessingError(
            f"eth_getCode for {address} returned non-string result: {result!r}"
        )

    def get_implementation(self, address: str) -> str:
        """Return the resolved implementation address of a proxy contract.

        Calls the proxy's ``implementation()`` view function via an
        ``eth_call`` with the 4-byte selector ``0x5c60da1b``
        (``keccak256("implementation()")[:4]``). This is the view-function
        introspection path (works for EIP-1167 minimal proxies of a factory
        that exposes the view, and for many beacon/transparent proxies); it is
        NOT an ``eth_getStorageAt`` read of the EIP-1967 implementation slot.
        Returns the resolved impl address (checksummed or lower-cased hex) or
        ``"0x"`` when the call returns a zero word / empty value. Used by the
        KodiakIsland / Bault detection fallback.
        """
        # EIP-1967 implementation slot selector: keccak256("implementation()").
        # This is a well-known fixed constant from the EIP, not a new
        # hardcoded value introduced by this task.
        selector = "0x5c60da1b"
        payload = {
            "to": address,
            "data": selector,
        }
        result = self._rpc("eth_call", [payload, "latest"])
        if isinstance(result, str):
            return _decode_address_slot(result)
        raise FileProcessingError(
            f"implementation() for {address} returned non-string result: {result!r}"
        )

    # ---- internals ------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            # Bearer-style is the most common; some RPCs use x-api-key. We
            # send Authorization: Bearer; callers that need x-api-key can
            # subclass or extend. The value is redacted before any log.
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _rpc(self, method: str, params: list) -> object:
        """Send one JSON-RPC ``method`` with ``params``, with retry/backoff."""
        call_id = self._next_id
        self._next_id += 1
        payload = {"jsonrpc": "2.0", "id": call_id, "method": method, "params": params}
        headers = self._headers()

        attempt = 0
        while True:
            _LOGGER.debug(
                "rpc %s id=%s redacted_headers=%s",
                method,
                call_id,
                _redact_headers(headers),
            )
            try:
                response = _http_post_json(
                    self.rpc_url, payload, headers, timeout=self.timeout
                )
            except (
                urllib.error.URLError,
                TimeoutError,
                http.client.HTTPException,
            ) as exc:
                if attempt >= self.max_retries:
                    raise FileProcessingError(
                        f"RPC {method} transport error for params={params}: {exc}"
                    ) from exc
                attempt += 1
                self._sleep_backoff(attempt)
                continue
            except json.JSONDecodeError as exc:
                raise FileProcessingError(
                    f"RPC {method} returned non-JSON for params={params}: {exc}"
                ) from exc

            # JSON-RPC error object.
            if "error" in response:
                err = response["error"]
                if attempt >= self.max_retries:
                    raise FileProcessingError(
                        f"RPC {method} error for params={params}: {err}"
                    )
                attempt += 1
                self._sleep_backoff(attempt)
                continue
            return response.get("result")

    def _sleep_backoff(self, attempt: int) -> None:
        """Sleep a small exponential backoff; tests patch ``time.sleep``."""
        time.sleep(self._backoff_base * (2 ** (attempt - 1)))


def _decode_address_slot(slot_hex: str) -> str:
    """Decode a 32-byte EVM storage slot holding an address into ``0x``-hex.

    The address occupies the low 20 bytes of the 32-byte slot. Returns
    ``"0x"`` for a zero slot. Mirrors how EIP-1967 impl slots are read.
    """
    if not slot_hex.startswith("0x"):
        return "0x"
    body = slot_hex[2:]
    if len(body) < _EVM_WORD_HEX_LEN:
        return "0x"
    addr = body[-_EVM_ADDRESS_HEX_LEN:]
    if set(addr) == {"0"}:
        return "0x"
    return "0x" + addr.lower()
