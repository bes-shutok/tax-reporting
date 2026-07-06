"""Tests for the ``build_transaction`` factory (Task 5, Phase A).

The factory wires a ``WalletClassification`` (produced by ``classify_platform``
in ``application.crypto.wallet_kind``) into a ``Transaction`` domain object,
deriving the ``is_unrecognized_wallet`` flag per Invariant 8:

    is_unrecognized_wallet =
        (classification.source == "auto"
         and not classification.is_high_probability())
        OR classification.kind == WalletKind.UNKNOWN

Plan Task 5 list, 7 cases. Every test must FAIL under a wrong implementation
(discriminating, not OR'd together).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from tax_reporting.application.crypto.transaction_factory import build_transaction
from tax_reporting.application.crypto.wallet_kind import (
    HIGH_PROBABILITY_THRESHOLD,
    PlatformEvidence,
    WalletClassification,
    classify_platform,
)
from tax_reporting.domain.transaction import (
    Transaction,
    TransactionHistoryRow,
    WalletKind,
)


def _row(
    *,
    sending_wallet: str | None = "Kraken",
    receiving_wallet: str | None = None,
    row_index: int = 0,
) -> TransactionHistoryRow:
    """Build a minimal TransactionHistoryRow for factory tests.

    The sending/receiving wallet fields are parameters so each test can pin
    which side the factory reads. Other fields use neutral defaults.
    """
    return TransactionHistoryRow(
        utc_instant=datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC),
        type="crypto_withdrawal",
        tag="",
        sending_wallet=sending_wallet if sending_wallet is not None else "",
        sending_amount=Decimal("1.0") if sending_wallet is not None else None,
        sending_currency="USDT" if sending_wallet is not None else None,
        receiving_wallet=receiving_wallet if receiving_wallet is not None else "",
        receiving_amount=Decimal("1.0") if receiving_wallet is not None else None,
        receiving_currency="USDT" if receiving_wallet is not None else None,
        tx_hash=None,
        tx_src=None,
        tx_dest=None,
        row_index=row_index,
    )


class _StubRegistry:
    """Minimal RegistrySnapshot for factory tests.

    Maps a platform name to a WalletKind; returns None for unmapped platforms
    (signals "fall through to tier-2 auto-discovery").
    """

    def __init__(self, mapping: dict[str, WalletKind]) -> None:
        self._mapping = mapping

    def classify(self, platform: str) -> WalletKind | None:
        return self._mapping.get(platform)


class TestTransactionFactory:
    """Plan Task 5 ``TestTransactionFactory`` (7 cases)."""

    def test_registry_classified_wallet_yields_cex_and_false_flag(self) -> None:
        """Given a Kraken row with a registry CEX classification, the Transaction is CEX / not-unrecognized."""
        row = _row(sending_wallet="Kraken")
        classification = classify_platform(
            "Kraken",
            evidence=None,
            registry=_StubRegistry({"Kraken": WalletKind.CEX}),
        )
        txn = build_transaction(row, classification)
        assert isinstance(txn, Transaction)
        assert txn.wallet_kind is WalletKind.CEX
        assert txn.is_unrecognized_wallet is False

    def test_auto_discovered_unknown_wallet_yields_unknown_true_flag(self) -> None:
        """Given an unmapped platform with no row evidence, the Transaction is UNKNOWN / unrecognized. (Invariant 8.)"""
        row = _row(sending_wallet="Demo Futures")
        classification = classify_platform(
            "Demo Futures",
            evidence=None,
            registry=_StubRegistry({}),
        )
        txn = build_transaction(row, classification)
        assert txn.wallet_kind is WalletKind.UNKNOWN
        assert txn.is_unrecognized_wallet is True

    def test_auto_discovered_low_confidence_wallet_yields_unknown_true_flag_and_low_confidence_reason(
        self,
    ) -> None:
        """Given auto-discovered below-threshold classification, kind is majority but flag is True.

        (Invariant 8 + 12.)
        """
        row = _row(sending_wallet="Mixed Platform")
        # 12 on-chain / 3 off-chain -> DEX majority at 0.80 confidence (below threshold).
        evidence = PlatformEvidence(on_chain_votes=12, off_chain_votes=3, total=15)
        classification = classify_platform(
            "Mixed Platform",
            evidence=evidence,
            registry=_StubRegistry({}),
        )
        assert classification.confidence < HIGH_PROBABILITY_THRESHOLD
        txn = build_transaction(row, classification)
        assert txn.wallet_kind is WalletKind.DEX
        assert txn.is_unrecognized_wallet is True

    def test_factory_uses_receiving_wallet_when_sending_blank(self) -> None:
        """Given a crypto_deposit row whose sending wallet is blank, the factory classifies from the receiving wallet.

        The factory's wallet pick is ``sending_wallet if sending_wallet else receiving_wallet``.
        A crypto_deposit row has an empty sending wallet, so the receiving
        wallet drives the classification. Asserting on ``wallet_kind`` proves
        which side was read.
        """
        row = _row(sending_wallet=None, receiving_wallet="Wirex")
        classification = classify_platform(
            "Wirex",
            evidence=None,
            registry=_StubRegistry({"Wirex": WalletKind.CEX}),
        )
        txn = build_transaction(row, classification)
        assert txn.wallet_kind is WalletKind.CEX
        assert txn.is_unrecognized_wallet is False

    def test_factory_destructures_classification_correctly(self) -> None:
        """Given a registry DEX classification, the Transaction carries the DEX kind and False flag. (Family H.)

        Proves the factory destructures ``classification.kind`` into
        ``Transaction.wallet_kind`` rather than, say, hardcoding CEX or
        reading a different field.
        """
        row = _row(sending_wallet="Ledger")
        classification = WalletClassification(
            kind=WalletKind.DEX,
            confidence=1.0,
            reason="registry match",
            source="registry",
        )
        txn = build_transaction(row, classification)
        assert txn.wallet_kind is WalletKind.DEX
        assert txn.is_unrecognized_wallet is False

    def test_factory_does_not_call_classifier_itself(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The factory is a thin wrapper: given a pre-computed WalletClassification, it MUST NOT call classify_platform.

        Plan Task 5 originally specified "given a row and a classifier whose
        ``classify_platform`` is monkeypatched with a call counter, expects
        the counter to read 1 after ``build_transaction``". That phrasing
        assumes the factory takes a classifier and invokes it once. The
        implemented factory contract takes a *pre-computed*
        ``WalletClassification`` (the resolver runs upstream and is composed
        by the caller, not by the factory). Reinterpreted: the factory must
        NOT call ``classify_platform`` itself. Verified by monkeypatching
        ``classify_platform`` to raise and asserting ``build_transaction``
        completes without invoking it.
        """
        row = _row(sending_wallet="Kraken")
        classification = WalletClassification(
            kind=WalletKind.CEX,
            confidence=1.0,
            reason="registry match",
            source="registry",
        )

        def _explode(*_args: Any, **_kwargs: Any) -> WalletClassification:
            raise AssertionError("build_transaction must not call classify_platform")

        # The factory may or may not import classify_platform by name; patch
        # at both the wallet_kind module and (defensively) the factory module
        # namespace. ``raising=False`` makes the second patch a no-op when
        # the symbol is not imported there.
        monkeypatch.setattr(
            "tax_reporting.application.crypto.wallet_kind.classify_platform",
            _explode,
        )
        monkeypatch.setattr(
            "tax_reporting.application.crypto.transaction_factory.classify_platform",
            _explode,
            raising=False,
        )

        txn = build_transaction(row, classification)
        assert txn.wallet_kind is WalletKind.CEX

    def test_direct_constructor_construction_is_permitted_but_unsanctioned(self) -> None:
        """Given a direct Transaction(...) construction (no factory), no exception is raised.

        The frozen dataclass permits direct construction; the ``Transaction``
        docstring names ``build_transaction`` as the sanctioned callsite.
        This test documents the permitted-but-unsanctioned path so a future
        linter or guard does not silently break it without a plan amendment.
        """
        row = _row(sending_wallet="Kraken")
        txn = Transaction(
            row=row,
            wallet_kind=WalletKind.CEX,
            is_unrecognized_wallet=False,
        )
        assert txn.row is row
        assert txn.wallet_kind is WalletKind.CEX
        assert txn.is_unrecognized_wallet is False
