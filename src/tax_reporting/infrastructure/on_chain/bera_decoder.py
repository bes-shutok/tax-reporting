"""Raw-row to CSV-row decoder for on-chain transactions (Task 4).

Translates the raw Etherscan V2 row dicts (``txlist`` native transfers and
``tokentx`` ERC-20 transfers) into typed :class:`OnChainTxRow` records ready
for CSV writing. This is the pure-data mapping step of the on-chain fetcher
pipeline; it performs no I/O and is unit-testable without HTTP.

Chain-agnostic (DI-2):
    Every chain-identity field (chain name, native ticker, wallet address,
    date window) flows from :class:`OnChainWalletConfig`. The native asset
    name for ``txlist`` rows is ``wallet_config.native_ticker``. There is no
    chain-name-to-ticker fallback map; ``native_ticker`` is a required
    config field (Task 2). No real-chain ticker literal appears here.

Date filtering (DI-5, option b):
    Rows whose ``timeStamp`` (Unix seconds) resolves to a UTC date outside the
    inclusive ``[wallet_config.start_date, wallet_config.end_date]`` window are
    SKIPPED here, in the decoder - not in the client. This keeps the date
    filter testable without an HTTP seam.

Raw-integer preservation (DI-4):
    Amounts are preserved as :class:`int` exactly as the integer-encoded
    ``value`` string represents them. No float conversion ever occurs: EVM
    values are 256-bit integers and float coercion would silently lose
    precision.

Row-level error isolation (AGENTS.md):
    Each row's parse is wrapped in ``try/except (KeyError, ValueError,
    TypeError)``. On failure the row is SKIPPED after a ``logger.warning``
    that carries row context (tx hash if present, the field that failed). One
    bad row never discards the dataset; the successfully-decoded rows are
    returned.
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime

from tax_reporting.domain.on_chain_config import OnChainWalletConfig
from tax_reporting.infrastructure.on_chain.position_token_registry import (
    PositionTokenRegistry,
)

_LOGGER = logging.getLogger(__name__)

# EVM native-asset decimals (wei per unit). Chain-agnostic constant: every
# EVM-compatible chain uses 18 decimals for its native coin.
_NATIVE_DECIMALS = 18


@dataclass(frozen=True)
class OnChainTxRow:
    """A single decoded on-chain transaction row, ready for CSV output.

    The field order matches the CSV header emitted by the fetcher (Task 5).
    """

    tx_hash: str
    block_number: str
    timestamp_utc: str
    chain: str
    from_address: str
    to_address: str
    asset: str
    token_address: str
    amount_raw: int
    amount_decimals: int
    direction: str
    fee_asset: str
    fee_amount_raw: int
    wallet_label: str
    wallet_address: str


def _parse_timestamp(time_stamp: str) -> datetime:
    """Parse an Etherscan ``timeStamp`` (Unix seconds string) to a UTC datetime.

    Parsed ONCE per row; the caller derives both the date-window check and the
    ISO-8601 ``timestamp_utc`` output field from the single returned value (avoids
    the double-parse pitfall: one parse per row feeds every derived value).
    """
    return datetime.fromtimestamp(int(time_stamp), tz=UTC)


def _in_date_window(ts_dt: datetime, start: date, end: date) -> bool:
    """True if the parsed timestamp date falls in ``[start, end]`` (inclusive)."""
    return start <= ts_dt.date() <= end


def _direction(row: dict, wallet_address: str) -> str:
    """Resolve direction from the wallet address vs the row's from/to.

    ``wallet_address == row["from"]`` -> ``"out"``; ``== row["to"]`` ->
    ``"in"``. When the wallet is NEITHER (an off-wallet leg, e.g. a checksum
    mismatch between the configured address and the API's lower-cased form),
    a WARNING carrying the tx hash + wallet + from/to is logged and the
    sentinel ``"unknown"`` is returned so the row is still emitted but
    flagged (rather than silently mislabeled as ``"in"``).
    """
    if wallet_address == row.get("from"):
        return "out"
    if wallet_address == row.get("to"):
        return "in"
    _LOGGER.warning(
        "Off-wallet leg for tx hash=%s: wallet=%s is neither from=%s nor to=%s; "
        "emitting row with direction='unknown'.",
        row.get("hash"),
        wallet_address,
        row.get("from"),
        row.get("to"),
    )
    return "unknown"


def decode_rows(  # noqa: PLR0913 - the optional row-surface kwargs (internal, nft + registry) keep every call site explicit about which surfaces it feeds
    raw_txlist_rows: list[dict],
    raw_tokentx_rows: list[dict],
    wallet_config: OnChainWalletConfig,
    *,
    raw_internal_rows: list[dict] | None = None,
    raw_nft_rows: list[dict] | None = None,
    position_registry: PositionTokenRegistry | None = None,
) -> list[OnChainTxRow]:
    """Decode raw Etherscan ``txlist`` + ``tokentx`` (+ ``txlistinternal`` + ``nfttx``) rows into CSV rows.

    Decode/provenance order: ``txlist`` rows, then ``txlistinternal`` rows,
    then ``tokentx`` rows, then ``nfttx`` rows (the nft surface is decoded
    LAST so its rows are authoritative - see the overlap guard below).

    Args:
        raw_txlist_rows: Native-transfer row dicts (``action=txlist``).
        raw_tokentx_rows: ERC-20-transfer row dicts (``action=tokentx``).
        wallet_config: The wallet this batch belongs to; supplies the chain
            name, native ticker, wallet address/label, and date window.
        raw_internal_rows: Optional internal-transaction row dicts
            (``action=txlistinternal``); native-value receives executed via
            internal calls that never appear in ``txlist``. Fees are NOT
            attributed to these rows (the parent tx's gas already lives on
            its ``txlist`` row - attributing it here would double-count).
        raw_nft_rows: Optional ERC-721/1155-transfer row dicts
            (wire ``action=tokennfttx``). Decoding is POSITION-REGISTRY-GATED and
            ERC-721 QUANTITY-1-ONLY: only transfers whose ``contractAddress``
            is a ``position_nft``-kind registry member
            (:meth:`PositionTokenRegistry.is_position_nft_token`;
            ``lst``-kind members do not decode) decode to rows (asset
            ``SYMBOL#tokenID``, quantity 1); ERC-1155-looking rows (batch
            ``tokenID`` containing ``*``, ``tokenValue`` other than 1, or
            an empty ``tokenID`` - the ERC-1155 batch shape) are skipped
            with a WARNING (ERC-1155
            quantity semantics are unsupported); non-member transfers (spam
            airdrop mints) are skipped with a WARNING + count and stay
            on-chain-invisible. Required companion: a non-``None``
            ``position_registry`` whenever ``raw_nft_rows`` is non-empty (an
            EMPTY registry is valid - all rows then skip as non-members).
        position_registry: The per-year position-token registry used to gate
            ``raw_nft_rows`` decoding (address-keyed membership; the
            ``SYMBOL#tokenID`` name is display-only).

    Returns:
        The list of successfully-decoded :class:`OnChainTxRow` records.
        Rows outside the date window are skipped silently; rows that fail to
        parse are skipped after a WARNING (never raised - one bad row does not
        discard the dataset). A ``tokentx`` row whose
        ``(tx_hash, token_address, direction)`` matches a decoded ``nfttx``
        row is dropped in favor of the authoritative nfttx row, accounted PER
        KEY COUNT (with 2 tokentx rows and 1 decoded nfttx row
        under the same key, exactly 1 tokentx row is dropped and 1 retained);
        a WARNING carries the dropped count, and a mismatch WARNING fires
        when the two surfaces do not reconcile per key. The key intentionally
        omits tokenID (``OnChainTxRow`` has no token-id column and the asset
        name embeds it for NFTs).

    Raises:
        ValueError: If ``raw_nft_rows`` is non-empty but
            ``position_registry`` is None (the membership gate cannot run).
    """
    decoded: list[OnChainTxRow] = []
    for row in raw_txlist_rows:
        parsed = _decode_native(row, wallet_config)
        if parsed is not None:
            decoded.append(parsed)
    for row in raw_internal_rows or []:
        parsed = _decode_internal(row, wallet_config)
        if parsed is not None:
            decoded.append(parsed)
    token_decoded: list[OnChainTxRow] = []
    for row in raw_tokentx_rows:
        parsed = _decode_token(row, wallet_config)
        if parsed is not None:
            token_decoded.append(parsed)

    nft_decoded = _decode_nft_rows(raw_nft_rows or [], wallet_config, position_registry)
    decoded.extend(_drop_overlapping_token_rows(token_decoded, nft_decoded))
    decoded.extend(nft_decoded)
    return decoded


def _decode_nft_rows(
    raw_nft_rows: list[dict],
    cfg: OnChainWalletConfig,
    position_registry: PositionTokenRegistry | None,
) -> list[OnChainTxRow]:
    """Decode registry-member ``nfttx`` rows (membership-gated) with a skip-count WARNING.

    The membership gate keys on ``contractAddress`` ONLY (address-keyed
    identity; the ``SYMBOL#tokenID`` name never feeds this decision).
    Non-member contracts (spam airdrop mints) never reach :func:`_decode_nft`
    and stay on-chain-invisible; their count surfaces in one summary WARNING.
    """
    if not raw_nft_rows:
        return []
    if position_registry is None:
        raise ValueError(
            "decode_rows: raw_nft_rows requires position_registry "
            "(membership-gated nfttx decoding cannot run without it)"
        )
    nft_decoded: list[OnChainTxRow] = []
    skipped_non_member = 0
    for row in raw_nft_rows:
        contract = str(row.get("contractAddress", ""))
        # The nfttx gate uses the KIND-GATED predicate
        # (ERC-721 position-NFT members only) so the ERC-721-surface gating
        # is uniform with the processor's receive detector. The skip bucket
        # therefore covers BOTH non-member contracts AND member contracts
        # of other kinds (an ``lst``-kind member is an ERC-20 that the
        # nfttx surface can nevertheless carry as an ERC-1155 transfer).
        if not position_registry.is_position_nft_token(contract):
            skipped_non_member += 1
            continue
        parsed = _decode_nft(row, cfg)
        if parsed is not None:
            nft_decoded.append(parsed)
    if skipped_non_member:
        _LOGGER.warning(
            "Skipped %d nfttx row(s) for contracts that are not "
            "position_nft-kind registry members (kind-gated membership "
            "decode; lst-kind members and non-member spam NFT transfers "
            "stay on-chain-invisible).",
            skipped_non_member,
        )
    return nft_decoded


def _drop_overlapping_token_rows(
    token_decoded: list[OnChainTxRow],
    nft_decoded: list[OnChainTxRow],
) -> list[OnChainTxRow]:
    """Drop ``tokentx`` rows whose transfer was already decoded from ``nfttx``.

    For registry-member contracts Etherscan can carry the SAME transfer on
    both surfaces; the nfttx-decoded row (``SYMBOL#tokenID``) is
    authoritative. The overlap key is ``(tx_hash, token_address,
    direction)`` and intentionally omits tokenID (``OnChainTxRow`` has no
    token-id column and the asset name embeds it for NFTs).

    The drop is accounted PER KEY COUNT, not per key set
    membership. One decoded nfttx row under a key consumes exactly ONE
    tokentx row of the same key; extra tokentx rows under the same key (a
    same-tx multi-transfer batch whose nft decode was partial) are RETAINED
    rather than silently lost, and a mismatch WARNING fires when the two
    surfaces do not reconcile per key (AGENTS.md: ordered per-key
    accounting, never silent overwrite/drop).
    """
    nft_key_counts = Counter(
        (row.tx_hash, row.token_address.lower(), row.direction)
        for row in nft_decoded
    )
    token_key_counts = Counter(
        (row.tx_hash, row.token_address.lower(), row.direction)
        for row in token_decoded
    )
    dropped_by_key: Counter[tuple[str, str, str]] = Counter()
    kept: list[OnChainTxRow] = []
    for row in token_decoded:
        key = (row.tx_hash, row.token_address.lower(), row.direction)
        if dropped_by_key[key] < nft_key_counts.get(key, 0):
            dropped_by_key[key] += 1
        else:
            kept.append(row)
    dropped_overlap = sum(dropped_by_key.values())
    if dropped_overlap:
        _LOGGER.warning(
            "Dropped %d tokentx row(s) already decoded from nfttx for "
            "registry-member contracts (overlap key: tx_hash + "
            "token_address + direction; the nfttx row is authoritative).",
            dropped_overlap,
        )
    # Reconciliation: for every key the nft surface decoded AND the tokentx
    # surface also carries, both surfaces should agree on the row count. An
    # imbalance means a partial nft decode (malformed/out-of-window nfttx
    # rows); retained tokentx rows already cover the loss, so this is a loud
    # review signal, not a drop. Keys with NO tokentx rows (nfttx-only
    # transfers) are not an overlap imbalance and stay silent.
    for key, nft_count in nft_key_counts.items():
        token_count = token_key_counts.get(key, 0)
        if token_count and token_count != nft_count:
            _LOGGER.warning(
                "Overlap mismatch for %s: %d tokentx row(s) vs %d nfttx "
                "row(s) decoded for this key; review this transaction "
                "manually.",
                key,
                token_count,
                nft_count,
            )
    return kept


def _build_native_row(  # noqa: PLR0913 - fee fields passed as kwargs keep the two call sites explicit
    row: dict,
    cfg: OnChainWalletConfig,
    ts_dt: datetime,
    amount_raw: int,
    *,
    fee_asset: str,
    fee_amount_raw: int,
) -> OnChainTxRow:
    """Build an ``OnChainTxRow`` for a native-transfer row.

    Shared by ``_decode_native`` (``txlist``: fee = gasUsed * gasPrice on the
    native asset) and ``_decode_internal`` (``txlistinternal``: NO fee - the
    parent tx's gas already lives on its ``txlist`` row), so adding an
    ``OnChainTxRow`` field requires editing ONE construction, not two.
    """
    return OnChainTxRow(
        tx_hash=row.get("hash", ""),
        block_number=str(row.get("blockNumber", "")),
        timestamp_utc=ts_dt.isoformat(),
        chain=cfg.chain,
        from_address=row.get("from", ""),
        to_address=row.get("to", ""),
        # DI-2: native asset name from config, never a literal.
        asset=cfg.native_ticker,
        token_address="",
        amount_raw=amount_raw,
        amount_decimals=_NATIVE_DECIMALS,
        direction=_direction(row, cfg.address),
        fee_asset=fee_asset,
        fee_amount_raw=fee_amount_raw,
        wallet_label=cfg.label,
        wallet_address=cfg.address,
    )


def _decode_native(
    row: dict, cfg: OnChainWalletConfig
) -> OnChainTxRow | None:
    """Decode one ``txlist`` (native transfer) row, or skip with a WARNING."""
    try:
        ts_dt = _parse_timestamp(row["timeStamp"])
        if not _in_date_window(ts_dt, cfg.start_date, cfg.end_date):
            return None
        amount_raw = int(row["value"])
        gas_used = int(row["gasUsed"])
        gas_price = int(row["gasPrice"])
        return _build_native_row(
            row,
            cfg,
            ts_dt,
            amount_raw,
            fee_asset=cfg.native_ticker,
            fee_amount_raw=gas_used * gas_price,
        )
    except (KeyError, ValueError, TypeError) as exc:
        _LOGGER.warning(
            "Skipping malformed txlist row (hash=%s): %s",
            row.get("hash"),
            exc,
        )
        return None


def _decode_internal(
    row: dict, cfg: OnChainWalletConfig
) -> OnChainTxRow | None:
    """Decode one ``txlistinternal`` (internal native transfer) row, or skip with a WARNING.

    Internal rows carry the parent tx's hash and a native ``value`` but do NOT
    carry a usable ``gasPrice`` (per the Etherscan ``txlistinternal`` field
    set); gas is paid by the parent tx and is already recorded on its
    ``txlist`` row, so no fee is attributed here (avoids double-counting).

    Reverted and zero-value rows are NOT economic receives:
    a reverted internal call never executed (``errCode`` non-empty /
    ``isError == '1'`` -> WARNING naming the hash, mirroring the malformed-row
    idiom), and a zero-value internal row carries no native movement. Decoding
    either would fabricate a phantom or amount-0 in-leg that flips the
    classifier's pure-outflow deposit shapes into bidirectional Swap/Reward
    shapes, so both are skipped.
    """
    if row.get("errCode") or str(row.get("isError", "0")) == "1":
        _LOGGER.warning(
            "Skipping reverted txlistinternal row (hash=%s, errCode=%s).",
            row.get("hash"),
            row.get("errCode") or "<isError>",
        )
        return None
    try:
        ts_dt = _parse_timestamp(row["timeStamp"])
        if not _in_date_window(ts_dt, cfg.start_date, cfg.end_date):
            return None
        amount_raw = int(row["value"])
        if amount_raw == 0:
            return None
        # Parent tx's gas lives on its txlist row; never attribute here.
        return _build_native_row(
            row, cfg, ts_dt, amount_raw, fee_asset="", fee_amount_raw=0
        )
    except (KeyError, ValueError, TypeError) as exc:
        _LOGGER.warning(
            "Skipping malformed txlistinternal row (hash=%s): %s",
            row.get("hash"),
            exc,
        )
        return None


def _decode_transfer_row(
    row: dict,
    cfg: OnChainWalletConfig,
    surface: str,
    derive: Callable[[dict, datetime], OnChainTxRow | None],
) -> OnChainTxRow | None:
    """Shared transfer-row decode scaffold.

    Wraps the timestamp parse, the inclusive date-window filter, and the
    malformed-row WARNING block common to the ``tokentx`` and ``nfttx``
    surfaces; ``derive`` is a per-surface closure that returns the finished
    :class:`OnChainTxRow` (via :func:`_build_transfer_row`) or ``None`` after
    logging its own surface-specific skip reason (e.g. the ERC-1155 guard).
    A ``ValueError`` raised inside ``derive`` is reported as a malformed
    ``surface`` row (WARNING + skip), mirroring the pre-refactor behavior.
    """
    try:
        ts_dt = _parse_timestamp(row["timeStamp"])
        if not _in_date_window(ts_dt, cfg.start_date, cfg.end_date):
            return None
        return derive(row, ts_dt)
    except (KeyError, ValueError, TypeError) as exc:
        _LOGGER.warning(
            "Skipping malformed %s row (hash=%s): %s",
            surface,
            row.get("hash"),
            exc,
        )
        return None


def _build_transfer_row(  # noqa: PLR0913 - one shared construction site
    row: dict,
    cfg: OnChainWalletConfig,
    ts_dt: datetime,
    *,
    asset: str,
    token_address: str,
    amount_raw: int,
    amount_decimals: int,
) -> OnChainTxRow:
    """Build ONE token-transfer ``OnChainTxRow`` (shared by both surfaces).

    Gas is recorded on the parent ``txlist`` row, never on a transfer leg,
    so the fee fields are zeroed here for both ``tokentx`` and ``nfttx``.
    """
    return OnChainTxRow(
        tx_hash=row.get("hash", ""),
        block_number=str(row.get("blockNumber", "")),
        timestamp_utc=ts_dt.isoformat(),
        chain=cfg.chain,
        from_address=row.get("from", ""),
        to_address=row.get("to", ""),
        asset=asset,
        token_address=token_address,
        amount_raw=amount_raw,
        amount_decimals=amount_decimals,
        direction=_direction(row, cfg.address),
        fee_asset="",
        fee_amount_raw=0,
        wallet_label=cfg.label,
        wallet_address=cfg.address,
    )


def _decode_token(
    row: dict, cfg: OnChainWalletConfig
) -> OnChainTxRow | None:
    """Decode one ``tokentx`` (ERC-20 transfer) row, or skip with a WARNING."""

    def derive(r: dict, ts_dt: datetime) -> OnChainTxRow:
        return _build_transfer_row(
            r,
            cfg,
            ts_dt,
            asset=str(r["tokenSymbol"]),
            token_address=str(r["contractAddress"]),
            amount_raw=int(r["value"]),
            amount_decimals=int(r["tokenDecimal"]),
        )

    return _decode_transfer_row(row, cfg, "tokentx", derive)


def _decode_nft(row: dict, cfg: OnChainWalletConfig) -> OnChainTxRow | None:
    """Decode one registry-member ``nfttx`` row (ERC-721 QUANTITY-1-ONLY), or skip with a WARNING.

    Callers MUST have already verified position-token-registry membership on
    ``row['contractAddress']`` (address-keyed gate in :func:`decode_rows`).
    The decoded asset name is the Koinly position-NFT symbol format
    ``SYMBOL#tokenID`` (display/comparator-only) with quantity 1 per token
    ID and 0 decimals. ERC-1155 rows (batch ``tokenID`` containing ``"*"``,
    ``tokenValue`` other than 1, or an empty ``tokenID`` - the batch shape
    on the nfttx surface) are SKIPPED with a WARNING - only
    ERC-721 quantity-1 semantics are decoded; honoring ``tokenValue`` would
    be a user decision. A MISSING ``tokenID`` key is a
    malformed row. Gas is recorded on the parent txlist
    row, never here. Direction reuses the shared :func:`_direction` helper
    (from=wallet -> out, to=wallet -> in).
    """

    def derive(r: dict, ts_dt: datetime) -> OnChainTxRow | None:
        token_id = str(r["tokenID"]).strip()
        # An empty tokenID with an empty tokenValue is the
        # ERC-1155 BATCH shape on the nfttx surface, so the empty check sits
        # INSIDE the ERC-1155-class guard (a skip reported as "malformed"
        # would send a reviewer hunting for a data problem that is actually
        # the documented unsupported-semantics case). A MISSING tokenID key
        # still raises below and is reported as malformed.
        # tokenValue is normalized before the membership test
        # so a JSON-numeric quantity (int 1) decodes instead of tripping the
        # string-only guard; a present-but-None value coerces to "" (never
        # ``str(None)`` == "None").
        _raw_tv = r.get("tokenValue", "")
        token_value = "" if _raw_tv is None else str(_raw_tv).strip()
        if "*" in token_id or token_value not in ("", "1") or not token_id:
            _LOGGER.warning(
                "nfttx row for %s looks ERC-1155 or lacks a token ID "
                "(tokenID=%r tokenValue=%s); ERC-1155 decoding is "
                "unsupported, skipping leg (hash=%s).",
                r.get("contractAddress"),
                token_id,
                r.get("tokenValue"),
                r.get("hash"),
            )
            return None
        return _build_transfer_row(
            r,
            cfg,
            ts_dt,
            asset=f"{r['tokenSymbol']}#{token_id}",
            token_address=str(r["contractAddress"]),
            # One position NFT per token ID: quantity is exactly 1.
            amount_raw=1,
            amount_decimals=0,
        )

    return _decode_transfer_row(row, cfg, "nfttx", derive)
