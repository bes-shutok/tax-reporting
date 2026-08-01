"""Etherscan V2 API client with block-range pagination.

Fetches the configured chain's native transactions (``txlist``) and token
transfers (``tokentx``) for a wallet address from the configured Etherscan V2
endpoint. The ``chainid`` originates from the trusted chain registry in
:mod:`application.crypto.chain_derivation`, flows through
:class:`OnChainWalletConfig`, and reaches this client as a constructor
argument; it is not a literal in this module. This module is chain-agnostic.

Block-range pagination (DI-5, option b):
    The Free tier exposes no result total-count, so end-of-stream is detected
    only by receiving a partial page or an empty result. The loop starts at
    ``startblock=0`` (the steady-state first call on every run), and whenever a
    page returns exactly ``page_size`` rows it advances
    ``startblock = max(blockNumber of the page) + 1`` and refetches ``page=1``.
    This means a run whose history length is an exact multiple of ``page_size``
    issues one extra empty-page request before terminating (r1 F8) - that is the
    only reliable end-of-stream signal on Free tier and is accepted.

Termination guards (DI-5):
    - A configurable ``max_rows`` ceiling caps any single call's accumulation
      and logs a WARNING when hit (defence against a runaway full-page stream).
    - Empty/``No transactions found`` results end the loop.
    - Persistent rate-limit (after ``max_retries``) and invalid-API-key
      responses raise :class:`~tax_reporting.domain.exceptions.FileProcessingError`.

Failure-mode translation:
    Known failure modes (``URLError``/``TimeoutError`` after retries exhausted,
    ``JSONDecodeError``, "Missing/Invalid API Key", persistent "Max rate limit
    reached") are translated into ``FileProcessingError`` carrying the chainid
    and address for clean attribution. The main.py wiring catch is a broad
    ``except Exception`` (DI-1), so an unexpected type still cannot escape.

Secret hygiene (r1 overflow):
    The ``apikey`` query parameter is redacted from any logged request URL via
    :func:`_redact_params`; the original key never reaches the log.

DI-3 injectable seam:
    :func:`_http_get_json` is the module-level indirection over ``urllib``.
    Tests monkeypatch THIS name (never ``urllib``/``urlopen`` directly), keeping
    the HTTP transport swappable and the unit tests network-free.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from tax_reporting.domain.exceptions import FileProcessingError

_LOGGER = logging.getLogger(__name__)

# Sentinel block far enough in the future to mean "to the chain tip".
_ENDBLOCK_SENTINEL = 99999999

# Substrings (lower-cased) that identify Etherscan's known status:"0" failure
# modes in the ``result``/``message`` fields. Kept generic; no chain identity.
_RATE_LIMIT_MARKER = "max rate limit reached"
_API_KEY_MARKER = "invalid api key"
_BACKOFF_BASE_SECONDS = 0.1


def _redact_params(params: dict[str, str | int]) -> dict[str, str | int]:
    """Return a debug-safe copy of ``params`` with ``apikey`` masked.

    The original ``apikey`` value must never reach a log line (r1 overflow:
    secret-in-log). The masked copy is what gets logged.
    """
    redacted = dict(params)
    if "apikey" in redacted:
        redacted["apikey"] = "***REDACTED***"
    return redacted


def _http_get_json(url: str, params: dict[str, str | int]) -> dict:
    """Build the query string, call ``urllib.request.urlopen``, parse JSON.

    This module-level function is the DI-3 injectable seam: tests patch THIS
    name (``tax_reporting.infrastructure.on_chain.etherscan_client._http_get_json``)
    rather than ``urllib``/``urlopen`` directly, so the transport is swappable
    and the unit tests stay network-free.

    Args:
        url: Base API URL (e.g. the configured Etherscan V2 endpoint).
        params: Query parameters; ``apikey`` is included verbatim here (it is
            masked only when logging - the actual request needs the real key).

    Returns:
        The parsed JSON response as a ``dict``.
    """
    query = urllib.parse.urlencode(params)
    full_url = f"{url}?{query}"
    with urllib.request.urlopen(full_url) as response:  # noqa: S310 - trusted configured host
        body = response.read()
    return json.loads(body)


@dataclass
class EtherscanV2Client:
    """Client for the configured Etherscan V2 endpoint.

    All chain identity (``chainid``) originates from the trusted chain
    registry in :mod:`application.crypto.chain_derivation` and reaches this
    client via :class:`OnChainWalletConfig`; this module defines no
    chain-identity literal. The ``base_url`` literal is the API host (not
    chain identity) and is fine.

    Attributes:
        api_key: Etherscan API key (secret; redacted in logs).
        chainid: The Etherscan V2 chainid, from the chain registry via
            :class:`OnChainWalletConfig`.
        page_size: Free-tier per-page row cap (default 1000).
        max_retries: Max rate-limit retries before raising.
        max_rows: Termination-guard ceiling on accumulated rows per call.
        base_url: The configured Etherscan V2 API host.
    """

    api_key: str
    chainid: int
    page_size: int = 1000
    max_retries: int = 3
    max_rows: int = 100000
    base_url: str = "https://api.etherscan.io/v2/api"
    # Backoff base in seconds; exposed for tests to keep determinism. The real
    # value is small; tests patch ``time.sleep`` to a no-op anyway.
    _backoff_base: float = field(default=_BACKOFF_BASE_SECONDS, repr=False)

    def fetch_normal_txs(self, address: str) -> list[dict]:
        """Fetch native (``txlist``) transactions for ``address``."""
        return self._fetch_with_block_pagination("txlist", address)

    def fetch_token_transfers(self, address: str) -> list[dict]:
        """Fetch ERC-20 (``tokentx``) token transfers for ``address``."""
        return self._fetch_with_block_pagination("tokentx", address)

    def _fetch_with_block_pagination(self, action: str, address: str) -> list[dict]:
        """Drive the block-range pagination loop for one ``action``.

        See module docstring for the steady-state / end-of-stream contract.
        Translates known failure modes into ``FileProcessingError``.
        """
        accumulated: list[dict] = []
        startblock = 0
        while True:
            params: dict[str, str | int] = {
                "chainid": self.chainid,
                "module": "account",
                "action": action,
                "address": address,
                "startblock": startblock,
                "endblock": _ENDBLOCK_SENTINEL,
                "page": 1,
                "offset": self.page_size,
                "sort": "asc",
                "apikey": self.api_key,
            }
            payload = self._call_with_retries(params, action, address)
            status = str(payload.get("status", ""))
            result = payload.get("result")

            if status == "1" and isinstance(result, list):
                rows = result
                accumulated.extend(rows)
                # DI-5 termination guard: cap accumulation and warn.
                if len(accumulated) >= self.max_rows:
                    _LOGGER.warning(
                        "max_rows ceiling reached for action=%s address=%s chainid=%s; "
                        "stopping at %d rows",
                        action,
                        address,
                        self.chainid,
                        len(accumulated),
                    )
                    return accumulated[: self.max_rows]
                # Full page -> advance block range, refetch page=1.
                if len(rows) >= self.page_size:
                    startblock = self._max_block(rows) + 1
                    continue
                # Partial page -> done.
                return accumulated

            if status == "0":
                text = self._failure_text(payload)
                # API key / config problem -> raise immediately (not transient).
                if _API_KEY_MARKER in text:
                    raise FileProcessingError(
                        f"Etherscan API key rejected for action={action} "
                        f"chainid={self.chainid} address={address}: {text}"
                    )
                # Persistent rate limit is handled inside _call_with_retries; if
                # it slips through here, treat as end-of-stream only when empty.
                if isinstance(result, list) and len(result) == 0:
                    return accumulated
                # Any other status:"0" (e.g. "No transactions found") ends the stream.
                return accumulated

            # Unknown shape - log and stop rather than spin forever.
            _LOGGER.warning(
                "unexpected Etherscan response shape for action=%s address=%s; "
                "stopping pagination",
                action,
                address,
            )
            return accumulated

    def _call_with_retries(
        self, params: dict[str, str | int], action: str, address: str
    ) -> dict:
        """Call the seam, retrying transient rate-limit responses with backoff.

        Translates transport errors (after retries exhausted) and persistent
        rate-limit into ``FileProcessingError``.
        """
        attempt = 0
        while True:
            _LOGGER.debug(
                "etherscan request action=%s chainid=%s params=%s",
                action,
                self.chainid,
                _redact_params(params),
            )
            try:
                payload = _http_get_json(self.base_url, params)
            except (urllib.error.URLError, TimeoutError) as exc:
                if attempt >= self.max_retries:
                    raise FileProcessingError(
                        f"Etherscan transport error for action={action} "
                        f"chainid={self.chainid} address={address}: {exc}"
                    ) from exc
                attempt += 1
                self._sleep_backoff(attempt)
                continue
            except json.JSONDecodeError as exc:
                raise FileProcessingError(
                    f"Etherscan returned non-JSON for action={action} "
                    f"chainid={self.chainid} address={address}: {exc}"
                ) from exc

            # Inspect for an embedded rate-limit signal.
            if str(payload.get("status", "")) == "0":
                text = self._failure_text(payload)
                if _RATE_LIMIT_MARKER in text and _API_KEY_MARKER not in text:
                    if attempt >= self.max_retries:
                        raise FileProcessingError(
                            f"Etherscan rate limit exhausted for action={action} "
                            f"chainid={self.chainid} address={address} "
                            f"after {attempt} retries"
                        )
                    attempt += 1
                    self._sleep_backoff(attempt)
                    continue
            return payload

    def _sleep_backoff(self, attempt: int) -> None:
        """Sleep a small exponential backoff; tests patch ``time.sleep``."""
        time.sleep(self._backoff_base * (2 ** (attempt - 1)))

    @staticmethod
    def _max_block(rows: list[dict]) -> int:
        """Return the maximum ``blockNumber`` across ``rows`` (all strings)."""
        return max(int(row["blockNumber"]) for row in rows)

    @staticmethod
    def _failure_text(payload: dict) -> str:
        """Lower-cased concatenation of ``result``/``message`` for marker matching."""
        parts = []
        result = payload.get("result")
        if isinstance(result, str):
            parts.append(result)
        message = payload.get("message")
        if isinstance(message, str):
            parts.append(message)
        return " ".join(parts).lower()
