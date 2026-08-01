"""Raw-row to CSV-row decoder for on-chain transactions (Task 4).

Translates the raw Etherscan V2 row dicts (``txlist`` native transfers and
``tokentx`` ERC-20 transfers) into typed :class:`OnChainTxRow` records ready
for CSV writing. This is the pure-data mapping step of the on-chain fetcher
pipeline; it performs no I/O and is unit-testable without HTTP.

Chain-agnostic (DI-2):
    Every chain-identity field (chain name, native ticker, wallet address,
    date window) flows from :class:`OnChainWalletConfig`. The native asset
    name for ``txlist`` rows is ``wallet_config.native_ticker``. There is no
    chain-name-to-ticker fallback map (r1 F4); ``native_ticker`` is a required
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
from dataclasses import dataclass
from datetime import UTC, date, datetime

from tax_reporting.application.on_chain_config import OnChainWalletConfig

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
    the double-parse flagged in review r1 F4).
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


def decode_rows(
    raw_txlist_rows: list[dict],
    raw_tokentx_rows: list[dict],
    wallet_config: OnChainWalletConfig,
) -> list[OnChainTxRow]:
    """Decode raw Etherscan ``txlist`` + ``tokentx`` rows into CSV rows.

    Args:
        raw_txlist_rows: Native-transfer row dicts (``action=txlist``).
        raw_tokentx_rows: ERC-20-transfer row dicts (``action=tokentx``).
        wallet_config: The wallet this batch belongs to; supplies the chain
            name, native ticker, wallet address/label, and date window.

    Returns:
        The list of successfully-decoded :class:`OnChainTxRow` records.
        Rows outside the date window are skipped silently; rows that fail to
        parse are skipped after a WARNING (never raised - one bad row does not
        discard the dataset).
    """
    decoded: list[OnChainTxRow] = []
    for row in raw_txlist_rows:
        parsed = _decode_native(row, wallet_config)
        if parsed is not None:
            decoded.append(parsed)
    for row in raw_tokentx_rows:
        parsed = _decode_token(row, wallet_config)
        if parsed is not None:
            decoded.append(parsed)
    return decoded


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
            fee_asset=cfg.native_ticker,
            fee_amount_raw=gas_used * gas_price,
            wallet_label=cfg.label,
            wallet_address=cfg.address,
        )
    except (KeyError, ValueError, TypeError) as exc:
        _LOGGER.warning(
            "Skipping malformed txlist row (hash=%s): %s",
            row.get("hash"),
            exc,
        )
        return None


def _decode_token(
    row: dict, cfg: OnChainWalletConfig
) -> OnChainTxRow | None:
    """Decode one ``tokentx`` (ERC-20 transfer) row, or skip with a WARNING."""
    try:
        ts_dt = _parse_timestamp(row["timeStamp"])
        if not _in_date_window(ts_dt, cfg.start_date, cfg.end_date):
            return None
        amount_raw = int(row["value"])
        decimals = int(row["tokenDecimal"])
        return OnChainTxRow(
            tx_hash=row.get("hash", ""),
            block_number=str(row.get("blockNumber", "")),
            timestamp_utc=ts_dt.isoformat(),
            chain=cfg.chain,
            from_address=row.get("from", ""),
            to_address=row.get("to", ""),
            asset=str(row["tokenSymbol"]),
            token_address=str(row["contractAddress"]),
            amount_raw=amount_raw,
            amount_decimals=decimals,
            direction=_direction(row, cfg.address),
            # Gas is recorded on the parent txlist row, not the token leg.
            fee_asset="",
            fee_amount_raw=0,
            wallet_label=cfg.label,
            wallet_address=cfg.address,
        )
    except (KeyError, ValueError, TypeError) as exc:
        _LOGGER.warning(
            "Skipping malformed tokentx row (hash=%s): %s",
            row.get("hash"),
            exc,
        )
        return None
