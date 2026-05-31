"""Token origin resolution application service.

Provides ``TokenOriginResolver`` which parses the Koinly Transaction History CSV
and resolves how a given token was acquired (swap, purchase, bridge transfer, etc.)
by correlating capital gains rows against the transaction history.

Domain types (``AcquisitionMethod``, ``TokenOrigin``) live in
``tax_reporting.domain.token_origin``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from ..domain.token_origin import AcquisitionMethod, TokenOrigin
from ..infrastructure.koinly_parser import (
    format_datetime,
    normalize_asset_ticker,
    normalize_platform_name,
    parse_koinly_datetime,
    read_koinly_rows,
)

_MAX_TXHASH_LENGTH: Final = 128
_MAX_WITHDRAWALS_PER_TXHASH: Final = 100


@dataclass(frozen=True)
class _AcquisitionRecord:
    """Internal record for a transaction history acquisition event."""

    from_asset: str
    from_platform: str
    method: AcquisitionMethod
    confidence: str
    tx_hash: str = ""  # TxHash for merging same-TxHash LP provisions


@dataclass(frozen=True)
class _WithdrawalRecord:
    """Internal record for a crypto_withdrawal row.

    Withdrawals are indexed by TxHash and used as provenance for paired deposit rows
    (e.g., LP withdrawal where LP tokens are sent and underlying tokens are received).
    Only the sent currency is used; other fields on the raw row are not needed downstream.
    """

    sent_currency: str


class TokenOriginResolver:
    """Resolve token acquisition origins by correlating capital gains with transaction history.

    Parses the Koinly transaction history CSV once at construction time and builds
    an internal lookup indexed by (date, asset, wallet). The ``resolve()`` method
    then matches capital gains rows to acquisition events and returns a ``TokenOrigin``.
    """

    def __init__(self, transaction_history_path: Path | None = None) -> None:
        """Build the acquisition-event lookup from the transaction history CSV."""
        self._lookup: dict[tuple[str, str, str], list[_AcquisitionRecord]] = {}
        self._withdrawal_by_txhash: dict[str, list[_WithdrawalRecord]] = {}
        if transaction_history_path is not None and transaction_history_path.exists():
            try:
                self._build_lookup(transaction_history_path)
            except Exception as e:
                self._lookup.clear()
                self._withdrawal_by_txhash.clear()
                logging.getLogger(__name__).warning(
                    "Failed to parse transaction history %s: %s; origin resolution will return unknown for all rows",
                    transaction_history_path.name,
                    e,
                )

    def _build_lookup(self, path: Path) -> None:
        rows = read_koinly_rows(path)
        for row in rows:
            self._index_withdrawal(row)
        for row in rows:
            self._index_row(row)

    def _index_withdrawal(self, row: dict[str, str]) -> None:
        """Index crypto_withdrawal rows by TxHash for provenance lookup.

        Withdrawals are indexed so they can be used as provenance for paired deposit rows
        (e.g., when removing liquidity from a DEX pool: LP tokens sent, tokens received).

        Only withdrawals with 'liquidity out' or 'liquidity in' tags are indexed,
        as these are the only ones used for LP provenance resolution. Other withdrawals
        like gas costs (tag 'Cost') are excluded to avoid polluting the LP provenance.
        """
        tx_type = row.get("Type", "").strip().lower()
        if tx_type != "crypto_withdrawal":
            return

        # Read from TxSrc field (index 16), not TxHash field (index 18)
        # Real Koinly exports store the transaction hash in TxSrc
        tx_hash = row.get("TxSrc", "").strip()
        sent_currency = row.get("Sent Currency", "").strip()
        # Validate TxHash length to prevent DoS via dictionary key bloat
        # Bitcoin: 64 chars, Ethereum: 66 chars (0x + hash), 128 provides safe margin
        if not tx_hash or not sent_currency or len(tx_hash) > _MAX_TXHASH_LENGTH:
            return

        date_str = row.get("Date", "").strip()
        if not date_str:
            return

        try:
            parse_koinly_datetime(date_str)
        except ValueError:
            return

        tag = row.get("Tag", "").strip().lower()

        # Only index withdrawals with relevant liquidity tags.
        # This excludes gas cost withdrawals (tag 'Cost') that share the same TxHash.
        if tag not in ("liquidity out", "liquidity in"):
            return

        record = _WithdrawalRecord(sent_currency=normalize_asset_ticker(sent_currency))
        # Add sanity limit to prevent unbounded memory growth via malformed CSV
        withdrawals = self._withdrawal_by_txhash.setdefault(tx_hash, [])
        if len(withdrawals) >= _MAX_WITHDRAWALS_PER_TXHASH:
            logger = logging.getLogger(__name__)
            logger.warning("TxHash %s has too many withdrawals (%d), skipping", tx_hash, len(withdrawals))
            return
        withdrawals.append(record)

    def _resolve_lp_provenance(self, tx_hash: str, receiving_wallet: str, tag: str) -> tuple[str, str]:
        """Resolve LP token provenance from paired withdrawal records.

        For liquidity pool operations, Koinly records a crypto_deposit row (tokens received)
        paired with one or more crypto_withdrawal rows (tokens sent) sharing the same TxHash.
        This method extracts the originating asset(s) from the withdrawal records.

        Args:
            tx_hash: Transaction hash linking deposit and withdrawal rows.
            receiving_wallet: Wallet receiving the deposit (for platform default).
            tag: Normalized tag value ('liquidity out' or 'liquidity in').

        Returns:
            Tuple of (from_asset, from_platform). For 'liquidity out', returns LP token name
            (e.g., 'CETUS-LP') with fallback to 'LP position'. For 'liquidity in', returns
            joined provided token names (e.g., 'SSUI+USDC'). Platform defaults to receiving_wallet.
        """
        withdrawals = self._withdrawal_by_txhash.get(tx_hash, [])

        if tag == "liquidity out":
            if withdrawals:
                sent_currencies = {w.sent_currency for w in withdrawals}
                # For liquidity out, we expect a single LP token sent
                # Deduplicate if multiple withdrawals have same currency
                if len(sent_currencies) == 1:
                    from_asset = next(iter(sent_currencies))
                else:
                    # Multiple distinct currencies - join them (should be rare for liquidity out)
                    from_asset = "+".join(sorted(sent_currencies))
            else:
                from_asset = "LP position"
            from_platform = receiving_wallet if receiving_wallet else "Unknown"
            return (from_asset, from_platform)

        if tag == "liquidity in":
            if withdrawals:
                sent_currencies = {w.sent_currency for w in withdrawals}
                # For liquidity in, we expect multiple tokens provided (e.g., SSUI+USDC)
                from_asset = "+".join(sorted(sent_currencies))
            else:
                from_asset = "Unknown"
            from_platform = receiving_wallet if receiving_wallet else "Unknown"
            return (from_asset, from_platform)

        # Fallback for unrecognized tags
        return ("Unknown", receiving_wallet if receiving_wallet else "Unknown")

    def _index_row(self, row: dict[str, str]) -> None:  # noqa: PLR0911, PLR0912, PLR0915
        logger = logging.getLogger(__name__)
        tx_type = row.get("Type", "").strip().lower()
        date_str = row.get("Date", "").strip()
        if not date_str:
            return

        try:
            dt = parse_koinly_datetime(date_str)
            date_key = format_datetime(dt)
        except ValueError:
            logger.warning("Skipping transaction history row with unparseable date: %s", date_str)
            return

        received_currency = row.get("Received Currency", "").strip()
        receiving_wallet = row.get("Receiving Wallet", "").strip()
        if not received_currency:
            return

        asset = normalize_asset_ticker(received_currency)
        normalized_wallet = normalize_platform_name(receiving_wallet)
        key = (date_key, asset, normalized_wallet)

        sent_currency = row.get("Sent Currency", "").strip()
        sent_wallet = row.get("Sending Wallet", "").strip()
        tag = row.get("Tag", "").strip().lower()
        # Read from TxSrc field (index 16), not TxHash field (index 18)
        # Real Koinly exports store the transaction hash in TxSrc
        tx_hash = row.get("TxSrc", "").strip()

        if tx_type == "exchange":
            if not sent_currency:
                return
            if tag == "liquidity out":
                method = AcquisitionMethod.LIQUIDITY_WITHDRAWAL
            elif tag == "liquidity in":
                method = AcquisitionMethod.LIQUIDITY_PROVISION
            else:
                method = AcquisitionMethod.SWAP_CONVERSION
            from_asset = normalize_asset_ticker(sent_currency)
            from_platform = normalize_platform_name(sent_wallet) if sent_wallet else normalized_wallet
        elif tx_type == "transfer":
            normalized_sent_currency = normalize_asset_ticker(sent_currency) if sent_currency else ""
            normalized_sent_wallet = normalize_platform_name(sent_wallet) if sent_wallet else ""
            # Skip only internal pool shuffles (e.g., "To pool"), not all same-wallet/same-asset transfers.
            # Legitimate returns like "redeem" from liquidity pools must be indexed.
            if (
                normalized_sent_currency == asset
                and normalized_sent_wallet == normalized_wallet
                and tag
                and "pool" in tag.lower()
            ):
                return
            method = AcquisitionMethod.BRIDGE_TRANSFER
            from_asset = normalized_sent_currency if normalized_sent_currency else asset
            from_platform = normalized_sent_wallet if normalized_sent_wallet else normalized_wallet
        elif tx_type == "buy":
            if not sent_currency:
                return
            method = AcquisitionMethod.DIRECT_PURCHASE
            from_asset = normalize_asset_ticker(sent_currency)
            from_platform = normalize_platform_name(sent_wallet) if sent_wallet else normalized_wallet
        elif tx_type in ("crypto_deposit", "fiat_deposit"):
            if tag in ("reward", "cashback", "realized gain"):
                method = AcquisitionMethod.REWARD
                from_asset = "Unknown"
                from_platform = "Unknown"
                tx_hash = ""  # Clear tx_hash to force medium confidence (no paired transaction)
            elif tag == "airdrop":
                method = AcquisitionMethod.AIRDROP
                from_asset = "Unknown"
                from_platform = "Unknown"
                tx_hash = ""  # Clear tx_hash to force medium confidence (no paired transaction)
            elif tag in ("liquidity out", "liquidity in"):
                if tag == "liquidity out":
                    method = AcquisitionMethod.LIQUIDITY_WITHDRAWAL
                else:  # liquidity in
                    method = AcquisitionMethod.LIQUIDITY_PROVISION
                from_asset, from_platform = self._resolve_lp_provenance(tx_hash, normalized_wallet, tag)
                # For LP operations, use medium confidence if no matching withdrawal was found
                # (from_asset is "LP position" or "Unknown" in those cases)
                if from_asset in ("LP position", "Unknown"):
                    tx_hash = ""  # Clear tx_hash to force medium confidence
            elif tag in ("lending", "lending_interest", "lending interest", "interest"):
                method = AcquisitionMethod.DEFI_YIELD
                from_asset = normalize_asset_ticker(sent_currency) if sent_currency else asset
                from_platform = normalize_platform_name(sent_wallet) if sent_wallet else normalized_wallet
            elif tx_type == "fiat_deposit":
                method = AcquisitionMethod.DIRECT_PURCHASE
                from_asset = normalize_asset_ticker(sent_currency) if sent_currency else asset
                from_platform = normalize_platform_name(sent_wallet) if sent_wallet else normalized_wallet
            else:
                method = AcquisitionMethod.TRANSFER
                from_asset = normalize_asset_ticker(sent_currency) if sent_currency else asset
                from_platform = normalize_platform_name(sent_wallet) if sent_wallet else normalized_wallet
        else:
            return

        confidence = "high" if tx_hash else "medium"
        record = _AcquisitionRecord(
            from_asset=from_asset,
            from_platform=from_platform,
            method=method,
            confidence=confidence,
            tx_hash=tx_hash,
        )

        self._lookup.setdefault(key, []).append(record)

    _CONFIDENCE_RANK = {"high": 2, "medium": 1, "low": 0}

    def resolve(self, acquisition_date: str, asset: str, wallet: str, notes: str = "") -> TokenOrigin:
        """Resolve token origin from acquisition metadata.

        Args:
            acquisition_date: ISO date string (YYYY-MM-DD) from the capital gains row.
            asset: Normalized asset ticker.
            wallet: Raw or normalized wallet name.
            notes: Notes from the capital gains row (for confidence adjustment).

        Returns:
            TokenOrigin with resolved acquisition details, or unknown if no match.
        """
        logger = logging.getLogger(__name__)
        if not acquisition_date or acquisition_date.startswith("1970-"):
            return TokenOrigin.unknown()

        normalized_wallet = normalize_platform_name(wallet)
        key = (acquisition_date, asset, normalized_wallet)
        records = self._lookup.get(key, [])

        if not records:
            return TokenOrigin.unknown()

        best = max(records, key=lambda r: self._CONFIDENCE_RANK.get(r.confidence, 0))

        confidence = best.confidence
        if len(records) > 1:
            same_confidence = [r for r in records if r.confidence == best.confidence]
            if len(same_confidence) > 1:
                agree = all(
                    r.method == best.method
                    and r.from_asset == best.from_asset
                    and r.from_platform == best.from_platform
                    for r in same_confidence
                )
                if not agree:
                    # Check if disagreeing records are LP provisions from the same TxHash.
                    # Same-TxHash merging is safe because it's a deterministic on-chain identifier
                    # linking all legs of a single atomic transaction. Do NOT merge across TxHash.
                    lp_methods = (AcquisitionMethod.LIQUIDITY_PROVISION, AcquisitionMethod.LIQUIDITY_WITHDRAWAL)
                    if (
                        all(r.method in lp_methods for r in same_confidence)
                        and all(r.method == best.method for r in same_confidence)
                        and all(r.from_platform == best.from_platform for r in same_confidence)
                        and len({r.tx_hash for r in same_confidence}) == 1
                    ):
                        # Merge LP provisions: combine from_assets with "+"
                        from_assets = sorted({r.from_asset for r in same_confidence})
                        merged_from_asset = "+".join(from_assets)
                        single_hash = same_confidence[0].tx_hash
                        logger.info(
                            "Merged %d LP provision record(s) for %s at %s on %s: %s (tx_hash: %s)",
                            len(same_confidence),
                            asset,
                            wallet,
                            acquisition_date,
                            merged_from_asset,
                            single_hash if single_hash else "none",
                        )
                        return TokenOrigin(
                            acquired_from_asset=merged_from_asset,
                            acquired_from_platform=best.from_platform,
                            acquisition_method=best.method,
                            confidence=confidence,
                        )
                    logger.warning(
                        "Origin records disagree for %s at %s on %s — returning unknown",
                        asset,
                        wallet,
                        acquisition_date,
                    )
                    return TokenOrigin.unknown()

        if "missing cost basis" in notes.lower():
            confidence = "low"

        return TokenOrigin(
            acquired_from_asset=best.from_asset,
            acquired_from_platform=best.from_platform,
            acquisition_method=best.method,
            confidence=confidence,
        )
