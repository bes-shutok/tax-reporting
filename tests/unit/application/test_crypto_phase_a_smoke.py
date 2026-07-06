"""End-to-end smoke for Phase A (Task 9).

Exercises the full parse -> classify -> factory -> resolver chain against
synthetic TH rows so unrelated refactors cannot silently break Phase A wiring
(Monitor item 4 in the plan). The smoke chain is intentionally thin: it
documents the sanctioned upstream-to-downstream composition without
introducing new business logic.
"""

from __future__ import annotations

import logging

import pytest

from tax_reporting.application.crypto.entities import (
    TxCorrelationKey,
    TxCorrelationKeyResolver,
    WalletKind,
    build_transaction,
)
from tax_reporting.application.crypto.wallet_kind import classify_platform
from tax_reporting.infrastructure.koinly_parser import parse_th_row


def _kraken_th_row() -> dict[str, str]:
    """Return a synthetic Kraken crypto_deposit TH row.

    Registry-sourced platforms (Kraken, ByBit, Wirex) are CEX. The chain
    exercised by these tests uses ``classify_platform`` with a stub registry
    that returns CEX for "Kraken", so the tier-1 path (confidence 1.0) is
    taken and no auto-discovery warning fires.
    """
    return {
        "Date": "2025-06-14 12:33:01 UTC",
        "Type": "crypto_deposit",
        "Tag": "reward",
        "Sending Wallet": "",
        "Sent Amount": "",
        "Sent Currency": "",
        "Receiving Wallet": "Kraken",
        "Received Amount": "1,25000000",
        "Received Currency": "ETH",
        "TxHash": "0xabc",
        "TxSrc": "addrA",
        "TxDest": "addrB",
    }


class _KrakenRegistry:
    """Minimal RegistrySnapshot stub returning CEX for ``Kraken`` only.

    Production callers pass the real registry; the smoke test substitutes a
    stub to keep the test hermetic (no docs/maintenance/tax/crypto-origin
    fixture needed).
    """

    def classify(self, platform: str) -> WalletKind | None:
        if platform == "Kraken":
            return WalletKind.CEX
        return None


def _run_chain(row: dict[str, str], row_index: int) -> tuple[TxCorrelationKey, bool]:
    """Run the sanctioned Phase A chain and return the resolver 2-tuple.

    Steps: ``parse_th_row -> classify_platform -> build_transaction ->
    TxCorrelationKeyResolver.resolve``. The factory MUST be invoked (the
    ``Transaction`` constructor is not called directly).
    """
    parsed = parse_th_row(row, row_index=row_index)
    platform = parsed.sending_wallet if parsed.sending_wallet else parsed.receiving_wallet
    classification = classify_platform(platform, evidence=None, registry=_KrakenRegistry())
    transaction = build_transaction(parsed, classification)
    return TxCorrelationKeyResolver.resolve(transaction)


class TestCryptoPhaseASmoke:
    """End-to-end Phase A smoke tests."""

    def test_full_chain_against_synthetic_th_row(self) -> None:
        """Given a valid synthetic Kraken TH row, the full chain produces a key.

        The composite ``row_index`` must equal the row index supplied to
        ``parse_th_row`` (Invariant 5: the composite is unique per TH row).
        The chain invokes ``build_transaction`` rather than the
        ``Transaction(...)`` constructor directly.
        """
        row = _kraken_th_row()
        key, requires_review = _run_chain(row, row_index=3)

        assert isinstance(key, TxCorrelationKey)
        assert key.composite.row_index == 3
        # CEX row with a tx_hash present -> no DEX-aware review flag.
        assert requires_review is False
        # tx_id derives from tx_hash per Invariant 2 (amended 2026-07-06).
        assert key.tx_id == "0xabc"

    def test_chain_rejects_naive_datetime(self) -> None:
        """Given a TH row whose Date does not match any known format, expects a raise.

        ``parse_th_row`` delegates to ``parse_koinly_datetime``, which raises
        ``ValueError`` for unsupported formats. A date string that matches no
        entry in ``DATE_FORMATS`` (e.g. an ISO-8601 ``T`` separator) surfaces
        the error unchanged.
        """
        row = _kraken_th_row()
        # "T" separator matches no DATE_FORMATS entry (see koinly_parser.DATE_FORMATS).
        row["Date"] = "2025-06-14T12:33:01"
        with pytest.raises(ValueError, match="Unsupported Koinly date format"):
            _run_chain(row, row_index=0)

    def test_chain_emits_no_warning_for_registry_wallet(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Given a registry-tier wallet, the chain emits zero WARNING records.

        This is a chain-level smoke check, not a registry-path-specific
        guarantee: ``classify_platform`` does not log warnings in any branch,
        so the assertion passes regardless of which tier fires. The intent is
        to guard against a future logger.warning being added to the resolver
        chain without test coverage.

        Tier-1 classification (confidence 1.0, source="registry") is the
        intended silent path for registry matches. ``build_transaction`` does
        not flag ``is_unrecognized_wallet`` for registry-CEX rows (the
        factory's first clause is gated on ``source == "auto"``; the second
        clause is gated on ``kind is UNKNOWN``; neither fires for this row).
        """
        row = _kraken_th_row()

        with caplog.at_level(logging.WARNING):
            _run_chain(row, row_index=7)

        warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert warnings == [], f"Expected zero warnings; got: {[r.getMessage() for r in warnings]}"
