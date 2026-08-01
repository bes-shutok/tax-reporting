"""On-chain transaction fetcher orchestrator + CSV writer (Task 5).

This is the orchestration step of the optional, year-scoped on-chain
transaction fetcher (a parallel collection step that is independent of the
Koinly-based crypto tax pipeline). It:

1. Loads the per-year wallet config via :func:`load_on_chain_wallets`.
2. For each wallet, drives an :class:`EtherscanV2Client` to fetch the raw
   ``txlist`` (native) and ``tokentx`` (ERC-20) rows.
3. Decodes the raw rows via :func:`decode_rows`.
4. Writes a single consolidated CSV at
   ``output_dir / str(year) / "bera_transactions.csv"``.

Design notes
------------
- **DI-1 (propagate, do not swallow):** :class:`FileProcessingError` raised
  by the client (transport error, rate-limit exhaustion, invalid API key)
  is allowed to propagate out of :func:`run_on_chain_fetch`. The caller in
  ``main.py`` owns the broad ``except Exception`` catch that keeps the
  on-chain step non-blocking relative to the IB/Koinly report. This module
  NEVER catches and silences such errors itself.
- **DI-2 (registry-derived; no chain identity here):** chain facts
  (chainid, native ticker) originate in the trusted chain registry in
  :mod:`application.crypto.chain_derivation`, are loaded into
  :class:`OnChainWalletConfig`, and flow into this orchestrator. No chain
  name, ticker, chainid, or wallet address literal appears in this file.
- **DI-3 (HTTP seam):** the transport is the module-level
  :func:`tax_reporting.infrastructure.on_chain.etherscan_client._http_get_json`
  seam. Tests monkeypatch THAT name (never ``urllib``/``urlopen``). There is
  no instance-attribute injection surface: the client resolves its transport
  via the module-level name, so the only override path is monkeypatching that
  global.
- **DI-6 (single-WARNING ownership):** the orchestrator owns the ONE
  WARNING emitted when the wallet config is empty. The loader stays silent
  for a missing config (it just returns ``[]``); logging there would
  double-warn for the same condition.
- **DI-8 (no ``repository_root`` param):** the config loader resolves the
  repo root itself, so this function takes only ``output_dir``.
"""

from __future__ import annotations

import csv
import dataclasses
import logging
from pathlib import Path

from tax_reporting.application.on_chain_config import (
    OnChainWalletConfig,
    load_on_chain_wallets,
)
from tax_reporting.application.persisting.excel_utils import safe_remove_file
from tax_reporting.infrastructure.on_chain.bera_decoder import (
    OnChainTxRow,
    decode_rows,
)
from tax_reporting.infrastructure.on_chain.etherscan_client import EtherscanV2Client

logger = logging.getLogger(__name__)

# Output filename for the consolidated on-chain transactions CSV. The name is
# a stable output contract (not chain identity) and is therefore fine here.
_CSV_FILENAME = "bera_transactions.csv"


def _client_for_wallet(
    wallet: OnChainWalletConfig, api_key: str
) -> EtherscanV2Client:
    """Build an :class:`EtherscanV2Client` for ``wallet``.

    The client resolves its HTTP transport via the module-level
    :func:`tax_reporting.infrastructure.on_chain.etherscan_client._http_get_json`
    seam (DI-3); tests override that module global directly. There is no
    instance-attribute transport here.
    """
    return EtherscanV2Client(api_key=api_key, chainid=wallet.chainid)


def _decode_wallet(
    wallet: OnChainWalletConfig,
    client: EtherscanV2Client,
) -> list[OnChainTxRow]:
    """Fetch + decode all rows for a single ``wallet``.

    Propagates :class:`FileProcessingError` from the client (DI-1).
    """
    txlist_rows = client.fetch_normal_txs(wallet.address)
    tokentx_rows = client.fetch_token_transfers(wallet.address)
    return decode_rows(txlist_rows, tokentx_rows, wallet)


def _write_csv(path: Path, rows: list[OnChainTxRow]) -> None:
    """Write ``rows`` to ``path`` as a CSV with the OnChainTxRow header.

    The file is removed first (via :func:`safe_remove_file`) so a stale
    pre-existing file is fully replaced, never appended to. The year
    subdirectory is created if missing. A header is always written even
    when ``rows`` is empty (so an empty file distinguishes "no txs" from
    "fetch failed").
    """
    fieldnames = [f.name for f in dataclasses.fields(OnChainTxRow)]
    path.parent.mkdir(parents=True, exist_ok=True)
    safe_remove_file(path)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(dataclasses.asdict(row))


def run_on_chain_fetch(
    *,
    year: int,
    output_dir: Path,
    api_key: str,
) -> Path | None:
    """Run the on-chain transaction fetcher for ``year`` and write the CSV.

    Args:
        year: Four-digit fiscal year (e.g. ``2025``). Used to load the
            per-year wallet config and to resolve the output subdirectory.
        output_dir: Base output directory. The CSV is written to
            ``output_dir / str(year) / "bera_transactions.csv"``; the year
            subdirectory is created if missing.
        api_key: Etherscan V2 API key. Forwarded to each wallet's client.

    Returns:
        The :class:`Path` to the written CSV, or ``None`` if the wallet
        config for ``year`` is empty (in which case a single WARNING is
        logged - DI-6).

    Raises:
        FileProcessingError: Propagated unchanged from the Etherscan client
            (transport error after retries, persistent rate limit,
            invalid API key). The caller in ``main.py`` catches broadly
            (DI-1); this function does NOT swallow it.
    """
    wallets = load_on_chain_wallets(year)
    if not wallets:
        # DI-6: the orchestrator owns the single WARNING for an empty /
        # missing config. The loader returned [] silently.
        logger.warning(
            "No chains.json for year %s; continuing without on-chain transaction data.",
            year,
        )
        return None

    decoded: list[OnChainTxRow] = []
    for wallet in wallets:
        client = _client_for_wallet(wallet, api_key)
        # DI-1: FileProcessingError from the client propagates unchanged.
        decoded.extend(_decode_wallet(wallet, client))

    # Stable sort by numeric block_number ascending. block_number is a string
    # in the row but ordered numerically; Python's sort is stable, so rows
    # sharing a block keep their decode order (txlist rows accumulated before
    # tokentx rows for the same block).
    decoded.sort(key=lambda r: (int(r.block_number) if r.block_number else 0))

    csv_path = output_dir / str(year) / _CSV_FILENAME
    _write_csv(csv_path, decoded)
    logger.info(
        "Wrote %d on-chain transaction rows to %s", len(decoded), csv_path
    )
    return csv_path
