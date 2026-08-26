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
    page returns exactly ``page_size`` rows it drains the page's LAST block
    (see below) and then advances ``startblock = max(blockNumber of the page)+1``
    and refetches ``page=1``. This means a run whose history length is an exact
    multiple of ``page_size`` issues one extra empty-page request before
    terminating (r1 F8) - that is the only reliable end-of-stream signal on
    Free tier and is accepted.

Boundary-block drain (mid-block page cuts):
    A full page can end INSIDE a block that has more rows for the wallet (a
    claim-style transaction puts 100+ transfer legs in one block). Advancing
    past the block there would silently drop that block's remaining rows, so
    on every full page the client re-queries the boundary block alone
    (``startblock = endblock = B``) and pages WITHIN it (Etherscan's own
    ``page`` parameter over the fixed single-block result set), skipping the
    first ``held`` rows it already accumulated (``held % page_size`` rows are
    sliced off page ``held // page_size + 1``; server row order for an
    immutable block range is stable). The drain ends on its own partial or
    empty page, then the outer loop advances to ``B + 1``.

Termination guards (DI-5):
    - A configurable ``max_rows`` ceiling caps any single call's accumulation
      and logs a WARNING when hit (defence against a runaway full-page stream).
    - Empty/``No transactions found`` results end the loop.
    - Persistent rate-limit (after ``max_retries``) and invalid-API-key
      responses raise :class:`~tax_reporting.domain.exceptions.FileProcessingError`.

Failure-mode translation:
    Known failure modes (``URLError``/``TimeoutError`` after retries exhausted,
    ``JSONDecodeError``, "Missing/Invalid API Key", persistent "Max rate limit
    reached", and status:"0" API-error strings that are not the documented
    empty response (e.g. an invalid module/action name)) are translated into
    ``FileProcessingError`` carrying the chainid
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
_NO_ROWS_MARKER = "no transactions found"
_BACKOFF_BASE_SECONDS = 0.1


def _parse_block_number(row: dict) -> int | None:
    """Parse ``row['blockNumber']``, WARNING + skip on a malformed value.

    Mirrors the decoder layer's malformed-row guard: an
    unguarded ``int()`` here turned one bad row into a whole-wallet fetch
    abort. Returns ``None`` for malformed rows; callers treat ``None`` as
    "not in this block / not a boundary candidate".
    """
    try:
        return int(row["blockNumber"])
    except (KeyError, ValueError, TypeError):
        _LOGGER.warning(
            "Skipping row with malformed/missing blockNumber (hash=%s).",
            row.get("hash"),
        )
        return None


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

    def fetch_internal_txs(self, address: str) -> list[dict]:
        """Fetch internal (``txlistinternal``) transactions for ``address``.

        Recovers native-value transfers executed via internal calls (contract
        calls) that never appear in ``txlist``. Reuses the same block-range +
        boundary-drain pagination loop as the other actions; the endpoint's
        pagination semantics are identical. ERC-721 NFT mint receipts are NOT
        recovered by this endpoint; use :meth:`fetch_nft_transfers` (``tokennfttx``).
        """
        return self._fetch_with_block_pagination("txlistinternal", address)

    def fetch_nft_transfers(self, address: str) -> list[dict]:
        """Fetch ERC-721/1155 (``tokennfttx``) transfers for ``address``.

        Recovers position-NFT mint/send legs that are invisible to the
        ``txlist``/``tokentx``/``txlistinternal`` triple. The Etherscan V2
        account action is ``tokennfttx`` - the ``nfttx`` name used earlier
        was rejected by the live API with "Error! Missing Or invalid Action
        name" and, before the fail-loud status:"0" guard, silently looked
        like an empty wallet (found on real data 2026-08-25). Reuses the
        same block-range + boundary-drain pagination loop as the other
        actions; the endpoint's pagination semantics are identical. The
        endpoint returns BOTH ERC-721 and ERC-1155 transfers, but only
        ERC-721 quantity-1 semantics are decoded downstream (registry-gated;
        ERC-1155-looking rows are WARNING-skipped by the decoder). Whether
        a decoded row becomes a pipeline row is gated downstream by the
        position-token registry (decoder), not here.
        """
        return self._fetch_with_block_pagination("tokennfttx", address)

    def _fetch_with_block_pagination(self, action: str, address: str) -> list[dict]:
        """Drive the block-range pagination loop for one ``action``.

        See module docstring for the steady-state / end-of-stream contract.
        Translates known failure modes into ``FileProcessingError``.
        """
        accumulated: list[dict] = []
        startblock = 0
        while True:
            params = self._page_params(
                action, address, startblock, _ENDBLOCK_SENTINEL, page=1
            )
            payload = self._call_with_retries(params, action, address)
            status = str(payload.get("status", ""))
            result = payload.get("result")

            if status == "1" and isinstance(result, list):
                rows = result
                accumulated.extend(rows)
                # DI-5 termination guard: cap accumulation and warn.
                if len(accumulated) >= self.max_rows:
                    self._warn_max_rows(action, address, len(accumulated))
                    return accumulated[: self.max_rows]
                # Full page -> drain the boundary block (a page can end inside
                # a block that has more rows), then advance the block range.
                if len(rows) >= self.page_size:
                    boundary = self._max_block(rows)
                    held = sum(
                        1
                        for row in rows
                        if _parse_block_number(row) == boundary
                    )
                    if self._drain_boundary_block(action, address, boundary, held, accumulated):
                        return accumulated[: self.max_rows]
                    startblock = boundary + 1
                    continue
                # Partial page -> done.
                return accumulated

            if status == "0":
                # API-key errors raise inside the guard below (hoisted there
                # so the boundary drain gets the same pre-check). Rate-limit
                # payloads never reach this branch (the retry
                # layer consumes every rate-limit-marked payload, raising on
                # exhaustion); every other status:"0" payload goes through
                # the fail-loud guard below (the old catch-all treated ANY
                # status:"0" as end-of-stream, which made an invalid action
                # name look like an empty wallet).
                self._raise_unless_end_of_stream(payload, action, address, context="pagination")
                return accumulated

            # Unknown shape - log and stop rather than spin forever.
            _LOGGER.warning(
                "unexpected Etherscan response shape for action=%s address=%s; "
                "stopping pagination",
                action,
                address,
            )
            return accumulated

    def _drain_boundary_block(
        self,
        action: str,
        address: str,
        block: int,
        held: int,
        accumulated: list[dict],
    ) -> bool:
        """Page within the single ``block`` range until the block is drained.

        Called after a full outer page whose last block is ``block``; ``held``
        is how many of that block's rows (its first, in server order) were
        already accumulated. Continues with Etherscan's own ``page`` parameter
        over the fixed ``[block, block]`` result set, slicing the ``held %
        page_size`` already-seen rows off the first response, so no row is
        duplicated or dropped at the page boundary. This relies on the
        documented assumption that server row order for an immutable block
        range is stable (module docstring); an identity-based reconciliation
        was attempted and reverted - not because the
        endpoint's rows are unidentifiable, but because the synthetic TEST
        rows carried no per-row identity fields (all rows collapsed to one
        identity and the drain made no progress); see
        development_lessons.md #138. Mutates ``accumulated``.

        Returns:
            True when the ``max_rows`` ceiling was hit (caller trims and
            returns), False when the block drained normally.
        """
        while True:
            page_num = held // self.page_size + 1
            skip = held % self.page_size
            params = self._page_params(action, address, block, block, page=page_num)
            payload = self._call_with_retries(params, action, address)
            status = str(payload.get("status", ""))
            result = payload.get("result")

            if status == "1" and isinstance(result, list):
                take = result[skip:]
                if not take:
                    if len(result) == skip:
                        # The NORMAL end-of-block path - the
                        # page carried exactly the already-held rows (the
                        # block's total equals ``held``), so there is nothing
                        # unseen. DEBUG, not WARNING (a WARNING here fired on
                        # every fetch ending exactly at a block boundary).
                        _LOGGER.debug(
                            "Boundary-block drain reached the end of block %d "
                            "for action=%s address=%s (block total == held "
                            "rows); nothing left to fetch.",
                            block,
                            action,
                            address,
                        )
                        return False
                    # No-progress guard (anomalous): a paged response that
                    # repeats only already-held rows (or returns fewer than
                    # already held) leaves ``held`` (and therefore
                    # ``page_num``) unchanged; stop the drain loudly rather
                    # than re-requesting the same page forever. Name the potential
                    # row loss explicitly.
                    _LOGGER.warning(
                        "Boundary-block drain made no progress for action=%s "
                        "address=%s block=%d page=%d: the page carried no "
                        "unseen rows; remaining rows of block %d, if any, "
                        "will not be fetched this run.",
                        action,
                        address,
                        block,
                        page_num,
                        block,
                    )
                    return False
                accumulated.extend(take)
                held += len(take)
                if len(accumulated) >= self.max_rows:
                    self._warn_max_rows(action, address, len(accumulated))
                    return True
                # Full page -> the block may have further rows; keep paging.
                if len(result) >= self.page_size:
                    continue
                return False

            if status == "0":
                # Includes the beyond-data empty page that ends an
                # exact-multiple block (accepted extra request, r1 F8 analog);
                # an API ERROR string here fails loud instead of silently
                # dropping the boundary block's remaining rows.
                self._raise_unless_end_of_stream(
                    payload, action, address, context="boundary-block drain"
                )
                return False

            _LOGGER.warning(
                "unexpected Etherscan response shape for action=%s address=%s "
                "block=%d; stopping boundary-block drain",
                action,
                address,
                block,
            )
            return False

    def _page_params(
        self, action: str, address: str, startblock: int, endblock: int, *, page: int
    ) -> dict[str, str | int]:
        """Build one page request's query parameters (shared by both loops)."""
        return {
            "chainid": self.chainid,
            "module": "account",
            "action": action,
            "address": address,
            "startblock": startblock,
            "endblock": endblock,
            "page": page,
            "offset": self.page_size,
            "sort": "asc",
            "apikey": self.api_key,
        }

    def _warn_max_rows(self, action: str, address: str, row_count: int) -> None:
        """Log the single max_rows-ceiling WARNING (shared by both loops)."""
        _LOGGER.warning(
            "max_rows ceiling reached for action=%s address=%s chainid=%s; "
            "stopping at %d rows",
            action,
            address,
            self.chainid,
            row_count,
        )

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
        """Return the maximum ``blockNumber`` across ``rows`` (all strings).

        Malformed ``blockNumber`` values are WARNING-skipped via
        :func:`_parse_block_number` rather than aborting the
        whole wallet fetch with a raw ``ValueError``.
        """
        blocks = [
            block
            for block in (_parse_block_number(row) for row in rows)
            if block is not None
        ]
        if not blocks:
            raise FileProcessingError(
                "Cannot resolve the boundary block: every row on the full "
                "page has a malformed/missing blockNumber; stopping rather "
                "than guessing the block range to advance to."
            )
        return max(blocks)

    def _raise_unless_end_of_stream(
        self, payload: dict, action: str, address: str, *, context: str
    ) -> None:
        """Raise on a status:"0" payload that is not a benign empty shape.

        Benign end-of-stream shapes: an empty ``result`` list; an empty
        failure text (no ``result`` string and no ``message``); or the
        "No transactions found" text variant in either field (review r3:
        the message can carry the error, so the check reads the FULL
        concatenated text, never the result cell alone). A NON-EMPTY list arriving with
        status:"0" is anomalous (status 1 normally accompanies lists): the
        page is dropped to end the stream, but a WARNING names it so the
        drop is never silent (review r1 F2). Anything else is an API error
        string - an invalid module/action name, a proxy refusal, and so on -
        that must not be silently read as an empty wallet
        (silent-data-loss guard; see the ``tokennfttx`` fix, 2026-08-25).
        Rate-limit payloads never reach this guard: ``_call_with_retries``
        consumes every payload whose failure text carries the rate-limit
        marker (retrying, then raising on exhaustion), so no slipped-through
        rate limit can terminate a stream here (review r1 F10 correction of
        the earlier comment).
        """
        # API-key/config errors raise FIRST, before any benign-empty
        # return (review r2 overflow: an error payload whose result is an
        # empty string or None must not slip past the marker inspection -
        # the boundary drain has no separate pre-check).
        text = self._failure_text(payload)
        if _API_KEY_MARKER in text:
            raise FileProcessingError(
                f"Etherscan API key rejected for action={action} "
                f"chainid={self.chainid} address={address}: {text}"
            )
        result = payload.get("result")
        if isinstance(result, list):
            if result:
                _LOGGER.warning(
                    "Etherscan status=0 with %d result row(s) for action=%s "
                    "address=%s chainid=%s (%s); dropping the anomalous page "
                    "and ending the stream",
                    len(result),
                    action,
                    address,
                    self.chainid,
                    context,
                )
            return
        # Review r3: benign iff the FULL failure text (result + message) is
        # empty or carries the no-rows marker - the message field can carry
        # an error string even when the result cell is empty (an earlier
        # empty-result-first rule would have read a message-borne error as
        # a benign empty page in BOTH loops). Review r4 (risk): a result of
        # an UNRECOGNIZED type (neither str, list, nor None) is anomalous
        # and fails loud rather than reading as an empty text.
        if result is not None and not isinstance(result, str):
            raise FileProcessingError(
                f"Etherscan returned an unrecognized result type "
                f"({type(result).__name__}) for action={action} "
                f"chainid={self.chainid} address={address} ({context}): {text!r}"
            )
        if not text.strip() or _NO_ROWS_MARKER in text:
            return
        raise FileProcessingError(
            f"Etherscan error for action={action} chainid={self.chainid} "
            f"address={address} ({context}): {text}"
        )

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
