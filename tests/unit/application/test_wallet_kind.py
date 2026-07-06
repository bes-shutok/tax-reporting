"""Tests for the two-tier platform-level WalletKindResolver (Task 4, Phase A).

Covers the public surface of ``application.crypto.wallet_kind``:

- ``HIGH_PROBABILITY_THRESHOLD`` (named constant; no inline ``0.95`` literals).
- ``EVM_TXHASH_REGEX`` / ``BTC_TXHASH_REGEX`` / ``SOL_TXHASH_REGEX`` protocol facts.
- ``PlatformEvidence`` frozen dataclass.
- ``WalletClassification`` frozen dataclass with ``is_high_probability()``.
- ``aggregate_platform_evidence(rows)`` per-platform tally.
- ``classify_platform(platform, evidence, registry)`` two-tier classifier.
- ``RegistrySnapshot`` Protocol (tier-1 contract).

Discriminating test policy (plan Task 4 list, 11 cases): every test must FAIL
under a wrong implementation, not just OR together. Boundary tests at exactly
0.95 and 0.94 discriminate ``>=`` from ``>``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Protocol

import pytest

from tax_reporting.application.crypto.wallet_kind import (
    BTC_TXHASH_REGEX,
    EVM_TXHASH_REGEX,
    HIGH_PROBABILITY_THRESHOLD,
    SOL_TXHASH_REGEX,
    PlatformEvidence,
    RegistrySnapshot,
    aggregate_platform_evidence,
    classify_platform,
)
from tax_reporting.domain.transaction import TransactionHistoryRow, WalletKind

# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _evm_txhash() -> str:
    """Return a 66-char 0x + 64-hex EVM hash (synthetic)."""
    return "0x" + "a" * 64


def _btc_txhash() -> str:
    """Return a 64-hex BTC hash (synthetic)."""
    return "f" * 64


def _sol_txhash() -> str:
    """Return an 88-char base58 Solana signature (synthetic)."""
    # base58 alphabet; 88 chars matches the Solana signature length.
    return "1" * 44 + "Z" * 44


def _row(  # noqa: PLR0913
    *,
    platform: str,
    type_: str,
    tx_hash: str | None = None,
    sending_wallet: str | None = "set",
    receiving_wallet: str | None = None,
    row_index: int = 0,
) -> TransactionHistoryRow:
    """Build a minimal TransactionHistoryRow for evidence-aggregation tests.

    The platform is attributed from sending_wallet if it is non-None, else
    receiving_wallet (mirrors the factory rule in Task 5). Both default to
    ``None`` so callers pass the side they want attributed.
    """
    if sending_wallet == "set":
        sending_wallet = platform
    if receiving_wallet == "set":
        receiving_wallet = platform
    return TransactionHistoryRow(
        utc_instant=datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC),
        type=type_,
        tag="",
        sending_wallet=sending_wallet or "",
        sending_amount=Decimal("1") if sending_wallet else None,
        sending_currency="USDT" if sending_wallet else None,
        receiving_wallet=receiving_wallet or "",
        receiving_amount=Decimal("1") if receiving_wallet else None,
        receiving_currency="USDT" if receiving_wallet else None,
        tx_hash=tx_hash,
        tx_src=None,
        tx_dest=None,
        row_index=row_index,
    )


class _StubRegistry:
    """Minimal RegistrySnapshot implementation for tier-1 tests."""

    def __init__(self, mapping: dict[str, WalletKind]) -> None:
        self._mapping = mapping

    def classify(self, platform: str) -> WalletKind | None:
        return self._mapping.get(platform)


# ---------------------------------------------------------------------------
# TestPlatformEvidenceAggregation - row-evidence tally + tier-2 classification
# ---------------------------------------------------------------------------


class TestPlatformEvidenceAggregation:
    """Tests for the row-evidence aggregation and tier-2 auto-discovery."""

    def test_pure_cex_platform_classifies_cex_at_100(self) -> None:
        """Given 5 off-chain Type rows for Kraken, expects CEX at confidence 1.0.

        Discriminates: fails if off-chain Types do not vote off-chain, or if
        confidence is not 1.0 for a unanimous vote.
        """
        rows = [
            _row(platform="Kraken", type_=t, row_index=i, tx_hash=f"TRADE-2024-{i:04d}")
            for i, t in enumerate(["buy", "sell", "fiat_deposit", "fiat_withdrawal", "buy"])
        ]
        evidence = aggregate_platform_evidence(rows)
        assert evidence["Kraken"] == PlatformEvidence(on_chain_votes=0, off_chain_votes=5, total=5)
        classification = classify_platform("Kraken", evidence["Kraken"], registry=None)
        assert classification.kind is WalletKind.CEX
        assert classification.confidence == 1.0
        assert classification.source == "auto"

    def test_pure_dex_platform_classifies_dex_at_100(self) -> None:
        """Given 5 on-chain Type rows for a Ledger wallet, expects DEX at 1.0.

        Discriminates: fails if on-chain Types do not vote on-chain.
        """
        rows = [
            _row(
                platform="Ledger Berachain (BERA)",
                type_=t,
                row_index=i,
                tx_hash=_evm_txhash(),
            )
            for i, t in enumerate(
                ["crypto_deposit", "crypto_withdrawal", "crypto_deposit", "crypto_withdrawal", "crypto_deposit"]
            )
        ]
        evidence = aggregate_platform_evidence(rows)
        key = "Ledger Berachain (BERA)"
        assert evidence[key] == PlatformEvidence(on_chain_votes=5, off_chain_votes=0, total=5)
        classification = classify_platform(key, evidence[key], registry=None)
        assert classification.kind is WalletKind.DEX
        assert classification.confidence == 1.0
        assert classification.source == "auto"

    def test_mixed_evidence_classifies_majority_with_confidence_below_100(self) -> None:
        """Given 12 on-chain / 3 off-chain rows for one platform, expects DEX at 0.80.

        Discriminates: fails if confidence does not equal majority/total, or if
        the reason does not name both tallies.
        """
        rows: list[TransactionHistoryRow] = []
        idx = 0
        for _ in range(12):
            rows.append(_row(platform="Mixed", type_="crypto_deposit", row_index=idx, tx_hash=_evm_txhash()))
            idx += 1
        for _ in range(3):
            rows.append(_row(platform="Mixed", type_="buy", row_index=idx, tx_hash=f"TRADE-2024-{idx:04d}"))
            idx += 1
        evidence = aggregate_platform_evidence(rows)
        assert evidence["Mixed"] == PlatformEvidence(on_chain_votes=12, off_chain_votes=3, total=15)
        classification = classify_platform("Mixed", evidence["Mixed"], registry=None)
        assert classification.kind is WalletKind.DEX
        assert classification.confidence == pytest.approx(0.80)
        assert "12" in classification.reason
        assert "3" in classification.reason

    def test_no_evidence_returns_unknown(self) -> None:
        """Given a platform with zero rows, classifying with evidence=None yields UNKNOWN.

        Discriminates: fails if classify_platform does not handle evidence=None.
        """
        classification = classify_platform("Unseen", evidence=None, registry=None)
        assert classification.kind is WalletKind.UNKNOWN
        assert classification.confidence == 0.0
        assert classification.source == "auto"


# ---------------------------------------------------------------------------
# TestWalletKindRegistryTier - tier-1 contract + boundary tests
# ---------------------------------------------------------------------------


class TestWalletKindRegistryTier:
    """Tests for the tier-1 registry lookup and the 0.95 boundary direction."""

    def test_registry_match_returns_kind_at_100_with_registry_source(self) -> None:
        """Given a registry that maps Kraken -> CEX, expects CEX 1.0 source=registry.

        Tier 1 is authoritative even if row evidence disagrees. Discriminates:
        fails if the registry signal is ignored, or if source != "registry".
        """
        registry = _StubRegistry({"Kraken": WalletKind.CEX})
        # Conflicting row evidence (DEX majority) - tier 1 must win.
        rows = [
            _row(platform="Kraken", type_="crypto_withdrawal", row_index=i, tx_hash=_evm_txhash()) for i in range(5)
        ]
        evidence = aggregate_platform_evidence(rows)
        classification = classify_platform("Kraken", evidence["Kraken"], registry=registry)
        assert classification.kind is WalletKind.CEX
        assert classification.confidence == 1.0
        assert classification.source == "registry"

    def test_registry_miss_falls_back_to_auto_discovery(self) -> None:
        """Given a platform NOT in the registry, expects source=auto.

        Discriminates: fails if registry-miss does not fall through to tier 2.
        """
        registry = _StubRegistry({"Kraken": WalletKind.CEX})  # does NOT contain "Demo Futures"
        rows = [_row(platform="Demo Futures", type_="buy", row_index=i, tx_hash=f"T-{i}") for i in range(3)]
        evidence = aggregate_platform_evidence(rows)
        classification = classify_platform("Demo Futures", evidence["Demo Futures"], registry=registry)
        assert classification.source == "auto"
        assert classification.kind is WalletKind.CEX

    def test_threshold_boundary_at_exactly_0_95_not_red_flagged(self) -> None:
        """Given evidence yielding confidence == 0.95 (19/1 split), expects high-probability True.

        Boundary test for ``>=``. Discriminates: fails if comparison is ``>``
        (strict greater-than would flag 0.95 as not high-probability).
        """
        # 19 on-chain + 1 off-chain = 20 rows, majority 19 -> 19/20 = 0.95 exactly.
        rows: list[TransactionHistoryRow] = []
        for i in range(19):
            rows.append(_row(platform="Boundary", type_="crypto_deposit", row_index=i, tx_hash=_evm_txhash()))
        rows.append(_row(platform="Boundary", type_="buy", row_index=19, tx_hash="T-19"))
        evidence = aggregate_platform_evidence(rows)["Boundary"]
        assert evidence == PlatformEvidence(on_chain_votes=19, off_chain_votes=1, total=20)
        classification = classify_platform("Boundary", evidence, registry=None)
        assert classification.confidence == pytest.approx(0.95)
        assert classification.is_high_probability() is True

    def test_threshold_boundary_at_exactly_0_94_red_flagged(self) -> None:
        """Given evidence yielding confidence == 0.94 (47/3 split), expects high-probability False.

        Boundary test for ``>=``. Discriminates: fails if comparison is ``>``
        AND the threshold is exactly 0.94 (47/50 = 0.94 exactly); also fails if
        the threshold is wrong.
        """
        # 47 on-chain + 3 off-chain = 50 rows; 47/50 = 0.94 exactly.
        rows: list[TransactionHistoryRow] = []
        for i in range(47):
            rows.append(_row(platform="Boundary", type_="crypto_deposit", row_index=i, tx_hash=_evm_txhash()))
        for i in range(47, 50):
            rows.append(_row(platform="Boundary", type_="buy", row_index=i, tx_hash=f"T-{i}"))
        evidence = aggregate_platform_evidence(rows)["Boundary"]
        assert evidence == PlatformEvidence(on_chain_votes=47, off_chain_votes=3, total=50)
        classification = classify_platform("Boundary", evidence, registry=None)
        assert classification.confidence < HIGH_PROBABILITY_THRESHOLD
        assert classification.is_high_probability() is False


# ---------------------------------------------------------------------------
# TestWalletKindTxHashShapes - protocol-fact regexes + threshold-literal guard
# ---------------------------------------------------------------------------


class TestWalletKindTxHashShapes:
    """Tests for the on-chain TxHash shape regexes (Invariant 13) and the
    no-inline-threshold-literal guard (Invariant 12)."""

    @pytest.mark.parametrize(
        ("tx_hash", "regex_name"),
        [
            (_evm_txhash(), "evm"),
            (_btc_txhash(), "btc"),
            (_sol_txhash(), "sol"),
        ],
    )
    def test_evm_txhash_shape_matches(self, tx_hash: str, regex_name: str) -> None:
        """Given an on-chain-shaped hash, expects the matching regex to vote on-chain.

        Each parametrized case is independently discriminating: a wrong regex
        for one protocol (e.g. EVM length off by one) must fail its own case
        even if the others pass. Constants sourced from
        docs/tmp/phase-a-tx-id-semantics.md Q2.
        """
        regex = {"evm": EVM_TXHASH_REGEX, "btc": BTC_TXHASH_REGEX, "sol": SOL_TXHASH_REGEX}[regex_name]
        assert regex.match(tx_hash) is not None

    @pytest.mark.parametrize(
        "tx_hash",
        ["TRADE-2024-X7Y8", "a1b2c3d4"],
    )
    def test_short_alphanumeric_txhash_classified_offchain(self, tx_hash: str) -> None:
        """Given a short exchange-internal id, expects NO on-chain regex to match.

        Discriminates: a single row with this tx_hash and an off-chain Type
        must aggregate as off-chain only.
        """
        rows = [_row(platform="Internal", type_="buy", row_index=0, tx_hash=tx_hash)]
        evidence = aggregate_platform_evidence(rows)["Internal"]
        assert evidence.on_chain_votes == 0
        assert evidence.off_chain_votes == 1
        assert evidence.total == 1

    def test_no_inline_threshold_literal(self) -> None:
        """Given the wallet_kind module source, expects zero inline ``0.95`` literals.

        The threshold MUST be the named constant ``HIGH_PROBABILITY_THRESHOLD``.
        Discriminates: fails if any inline ``0.95`` appears outside the
        constant definition.
        """
        import tax_reporting.application.crypto.wallet_kind as wk_module

        source = Path(wk_module.__file__).read_text(encoding="utf-8")
        # Allow only the canonical constant DEFINITION line (which mentions
        # both the constant name and the literal). Every other ``0.95`` is a
        # violation (Invariant 12 + plan's validation grep contract).
        lines = [
            line
            for line in source.splitlines()
            if not ("HIGH_PROBABILITY_THRESHOLD" in line and "0.95" in line and "=" in line)
        ]
        cleaned_source = "\n".join(lines)
        assert "0.95" not in cleaned_source, (
            "Inline 0.95 literal found outside HIGH_PROBABILITY_THRESHOLD constant definition"
        )


# ---------------------------------------------------------------------------
# Protocol shape sanity check (RegistrySnapshot is a typing.Protocol)
# ---------------------------------------------------------------------------


def test_registry_snapshot_is_protocol() -> None:
    """Given the RegistrySnapshot symbol, expects it to be a typing.Protocol subclass.

    Documents the tier-1 contract for Task 5/7 implementers.
    """
    assert issubclass(RegistrySnapshot, Protocol)  # type: ignore[arg-type]
