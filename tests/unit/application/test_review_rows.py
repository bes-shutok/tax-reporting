"""Unit tests for the shared crypto review-row helper module.

Covers :func:`tax_reporting.application.crypto.review_rows._append_surplus_and_malformed_review_rows`,
the W6/W7 dedup extraction that collapses the structurally identical surplus-lot
and malformed-input-lot review-row construction in ``derivatives_filter`` and
``fee_filter`` (r1 F1 prefix asymmetry: derivatives prepends nothing; fee
prepends ``"Fee CG dedup: "``).

Tests follow the TDD RED -> GREEN cycle and assert byte-identical reason text
for BOTH prefixes so the helper cannot silently drift from the pre-refactor
inline wording (INV-text).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from tax_reporting.application.crypto.entities import (
    CryptoCapitalGainEntry,
    CryptoReviewEntry,
)
from tax_reporting.application.crypto.operator_origin import OperatorOrigin
from tax_reporting.application.crypto.review_rows import (
    _append_surplus_and_malformed_review_rows,
)
from tax_reporting.application.crypto.th_lot_matcher import IndexedLot

# Minimal operator-origin fixture (matches the shape used in the sibling
# filter tests; the review-row helper never inspects it).
_TEST_OPERATOR_ORIGIN = OperatorOrigin(
    platform="MetaMask",
    service_scope="crypto",
    operator_entity="MetaMask",
    operator_country="Unknown",
    source_url="",
    source_checked_on="2026-01-01",
    confidence="low",
    review_required=False,
    valid_from="2026-01-01",
)


def _make_cg_lot(
    *,
    disposal_timestamp: str,
    asset: str = "ETH",
    wallet: str = "MetaMask",
    amount: Decimal,
    acquisition_date: str = "2025-01-10",
) -> CryptoCapitalGainEntry:
    """Build a minimal CryptoCapitalGainEntry fixture for review-row tests."""
    return CryptoCapitalGainEntry(
        disposal_date=disposal_timestamp.split(" ")[0],
        acquisition_date=acquisition_date,
        asset=asset,
        amount=amount,
        cost_eur=Decimal("0.50"),
        proceeds_eur=Decimal("1.50"),
        gain_loss_eur=Decimal("1.00"),
        holding_period="Short term",
        wallet=wallet,
        platform=wallet,
        chain="Unknown",
        operator_origin=_TEST_OPERATOR_ORIGIN,
        annex_hint="J",
        review_required=False,
        notes="",
        review_reason=None,
        disposal_timestamp=disposal_timestamp,
    )


class TestReviewRowHelper:
    """Verifies the shared surplus + malformed review-row builder.

    Parametrized over the two call sites' prefixes (derivatives "" vs fee
    "Fee CG dedup: ") so INV-text byte-identity is asserted for both.
    """

    @pytest.mark.parametrize(
        ("surplus_prefix", "expected_surplus_reason"),
        [
            # derivatives case: NO prefix (r1 F1).
            (
                "",
                "Surplus lot - may indicate a missed FIFO split; "
                "review the listed key",
            ),
            # fee case: "Fee CG dedup: " prefix.
            (
                "Fee CG dedup: ",
                "Fee CG dedup: Surplus lot - may indicate a missed FIFO "
                "split; review the listed key",
            ),
        ],
    )
    def test_surplus_rows_built_with_prefix(
        self, surplus_prefix: str, expected_surplus_reason: str
    ) -> None:
        """Given a surplus lot list + prefix, builds CryptoReviewEntry rows
        with the byte-identical frozen reason text and is_suspicious=True."""
        lot = IndexedLot(
            index=0,
            entry=_make_cg_lot(
                disposal_timestamp="2025-03-30 12:00",
                asset="ETH",
                amount=Decimal("0.001"),
            ),
        )
        review_entries: list[CryptoReviewEntry] = []

        _append_surplus_and_malformed_review_rows(
            review_entries,
            surplus_lots=[lot],
            malformed_lots=[],
            surplus_prefix=surplus_prefix,
            malformed_prefix=surplus_prefix,
        )

        assert len(review_entries) == 1
        row = review_entries[0]
        assert isinstance(row, CryptoReviewEntry)
        assert row.source_section == "capital_gains"
        assert row.review_reason == expected_surplus_reason
        assert row.is_suspicious is True
        # Row metadata mirrors the lot's disposal/wallet (INV-1 no signal loss).
        assert row.date == "2025-03-30 12:00"
        assert row.asset == "ETH"
        assert row.platform == "MetaMask"

    @pytest.mark.parametrize(
        ("malformed_prefix", "expected_malformed_reason"),
        [
            # derivatives case: NO prefix (r1 F1).
            (
                "",
                "Malformed-input lot (non-positive amount 0); "
                "investigate the source export",
            ),
            # fee case: "Fee CG dedup: " prefix.
            (
                "Fee CG dedup: ",
                "Fee CG dedup: Malformed-input lot (non-positive amount 0); "
                "investigate the source export",
            ),
        ],
    )
    def test_malformed_rows_built_with_prefix(
        self, malformed_prefix: str, expected_malformed_reason: str
    ) -> None:
        """Given a malformed lot list + prefix, builds CryptoReviewEntry rows
        with the byte-identical frozen reason text and is_suspicious=True."""
        malformed_entry = _make_cg_lot(
            disposal_timestamp="2025-03-30 12:00",
            asset="ETH",
            amount=Decimal("0"),
        )
        review_entries: list[CryptoReviewEntry] = []

        _append_surplus_and_malformed_review_rows(
            review_entries,
            surplus_lots=[],
            malformed_lots=[malformed_entry],
            surplus_prefix=malformed_prefix,
            malformed_prefix=malformed_prefix,
        )

        assert len(review_entries) == 1
        row = review_entries[0]
        assert isinstance(row, CryptoReviewEntry)
        assert row.source_section == "capital_gains"
        assert row.review_reason == expected_malformed_reason
        assert row.is_suspicious is True
        assert row.date == "2025-03-30 12:00"
        assert row.asset == "ETH"
        assert row.platform == "MetaMask"
