"""Direct unit tests for the shared TH-lot matcher (extracted from derivatives_dedup).

Covers the generic two-phase matcher (exact + contiguous-range), the
match-only vs remove semantics, surplus/malformed/unmatched signals, the
single-WARNING-summary contract, and the caller-logger-name invariant.

The matcher is generic over the event type via the ``ThEvent`` protocol; we
exercise it with a minimal frozen ``_Evt`` dataclass that satisfies the
protocol (``timestamp/asset/wallet/amount``). The derivatives and fee
callers each carry extra fields but the matcher reads only these four.
"""

from __future__ import annotations

import dataclasses
import logging
from decimal import Decimal

import pytest

from tax_reporting.application.crypto.entities import (
    CryptoCapitalGainEntry,
    OperatorOrigin,
)
from tax_reporting.application.crypto.th_lot_matcher import (
    IndexedLot,
    match_lots,
    remove_matched_lots,
)

_TEST_OPERATOR_ORIGIN = OperatorOrigin(
    platform="ByBit",
    service_scope="crypto",
    operator_entity="ByBit",
    operator_country="Unknown",
    source_url="",
    source_checked_on="2026-01-01",
    confidence="low",
    review_required=False,
    valid_from="2026-01-01",
)


def _make_cg_lot(  # noqa: PLR0913
    *,
    disposal_timestamp: str,
    asset: str = "USDT",
    wallet: str = "ByBit",
    amount: Decimal,
    acquisition_date: str = "2025-01-10",
    proceeds_eur: Decimal = Decimal("0"),
    gain_loss_eur: Decimal = Decimal("0"),
    cost_eur: Decimal = Decimal("0"),
) -> CryptoCapitalGainEntry:
    """Build a CryptoCapitalGainEntry fixture for matcher tests."""
    return CryptoCapitalGainEntry(
        disposal_date=disposal_timestamp.split(" ")[0],
        acquisition_date=acquisition_date,
        asset=asset,
        amount=amount,
        cost_eur=cost_eur,
        proceeds_eur=proceeds_eur,
        gain_loss_eur=gain_loss_eur,
        holding_period="Short term",
        wallet=wallet,
        platform=wallet,
        chain="Unknown",
        operator_origin=_TEST_OPERATOR_ORIGIN,
        annex_hint="J",
        review_required=False,
        notes="",
        disposal_timestamp=disposal_timestamp,
    )


@dataclasses.dataclass(frozen=True)
class _Evt:
    """Minimal frozen event satisfying the ThEvent protocol."""

    timestamp: str
    asset: str
    wallet: str
    amount: Decimal


def _evt(
    timestamp: str = "2025-01-24 23:40",
    asset: str = "USDT",
    wallet: str = "ByBit",
    amount: Decimal = Decimal("0.5"),
) -> _Evt:
    return _Evt(timestamp=timestamp, asset=asset, wallet=wallet, amount=amount)


class TestMatchLotsExact:
    """Phase 1 exact-match: same (timestamp, asset, wallet, amount_6dp)."""

    def test_match_only_returns_matched_metadata_and_leaves_entries_unchanged(self) -> None:
        """match_lots returns matched_metadata but does NOT remove from remaining_entries."""
        lots = [
            _make_cg_lot(disposal_timestamp="2025-01-24 23:40", amount=Decimal("0.5")),
        ]
        events = [_evt(amount=Decimal("0.5"))]

        result = match_lots(lots, events)

        assert result.matched_metadata, "expected one exact match"
        lot, match_type, event = result.matched_metadata[0]
        assert isinstance(lot, IndexedLot)
        assert match_type == "exact"
        assert event is events[0], "matcher must pass the original event object through"
        assert lot.index == 0
        # match_lots is match-only: remaining_entries equals input unchanged.
        assert result.remaining_entries == lots
        assert result.remaining_entries is not lots or result.remaining_entries == lots

    def test_match_only_emits_no_logging(self, caplog: pytest.LogCaptureFixture) -> None:
        lots = [_make_cg_lot(disposal_timestamp="2025-01-24 23:40", amount=Decimal("0.5"))]
        events = [_evt(amount=Decimal("0.5"))]

        with caplog.at_level(logging.DEBUG):
            match_lots(lots, events)

        assert not caplog.records, "match_lots must emit no logging at all"

    def test_remove_exact_match_removes_the_lot(self) -> None:
        lots = [
            _make_cg_lot(disposal_timestamp="2025-01-24 23:40", amount=Decimal("0.5")),
            _make_cg_lot(disposal_timestamp="2025-01-24 20:00", amount=Decimal("0.1")),
        ]
        events = [_evt(amount=Decimal("0.5"))]

        result = remove_matched_lots(
            lots, events, domain_label="derivatives", logger=logging.getLogger("test")
        )

        assert len(result.remaining_entries) == 1
        assert result.remaining_entries[0].amount == Decimal("0.1")
        assert len(result.matched_metadata) == 1


class TestContiguousRange:
    """Phase 2 contiguous-range fallback for split FIFO lots."""

    def test_range_match_removes_contiguous_window(self) -> None:
        lots = [
            _make_cg_lot(
                disposal_timestamp="2025-01-24 23:40",
                amount=Decimal("70.0"),
                acquisition_date="2025-01-10",
            ),
            _make_cg_lot(
                disposal_timestamp="2025-01-24 23:40",
                amount=Decimal("50.0"),
                acquisition_date="2025-01-12",
            ),
        ]
        events = [_evt(amount=Decimal("120.0"))]

        result = remove_matched_lots(
            lots, events, domain_label="derivatives", logger=logging.getLogger("test")
        )

        assert len(result.remaining_entries) == 0
        assert len(result.matched_metadata) == 2
        assert {mt for _lot, mt, _ev in result.matched_metadata} == {"range"}

    def test_range_match_within_tolerance(self) -> None:
        """Tolerance is _RANGE_TOLERANCE_SCALE * range_size (10e-6 * N)."""
        # Two lots summing to 5.000025 vs event 5.000000: diff 0.000025 <= 2*1e-5.
        lots = [
            _make_cg_lot(
                disposal_timestamp="2025-01-13 13:01",
                amount=Decimal("1.5"),
                acquisition_date="2025-01-10",
            ),
            _make_cg_lot(
                disposal_timestamp="2025-01-13 13:01",
                amount=Decimal("1.5"),
                acquisition_date="2025-01-11",
            ),
            _make_cg_lot(
                disposal_timestamp="2025-01-13 13:01",
                amount=Decimal("2.000025"),
                acquisition_date="2025-01-12",
            ),
        ]
        events = [_evt(timestamp="2025-01-13 13:01", amount=Decimal("5.000000"))]

        result = remove_matched_lots(
            lots, events, domain_label="derivatives", logger=logging.getLogger("test")
        )

        assert len(result.remaining_entries) == 0
        assert len(result.matched_metadata) == 3


class TestSurplusLots:
    def test_surplus_lot_detected_when_more_lots_than_events_at_same_key(self) -> None:
        lots = [
            _make_cg_lot(disposal_timestamp="2025-01-24 23:40", amount=Decimal("0.5")),
            _make_cg_lot(disposal_timestamp="2025-01-24 23:40", amount=Decimal("0.5")),
        ]
        events = [_evt(amount=Decimal("0.5"))]

        result = match_lots(lots, events)

        assert len(result.surplus_lots) == 1
        assert result.surplus_lots[0].index == 1


class TestUnmatchedEvents:
    def test_unmatched_event_retained_in_result(self) -> None:
        lots = [_make_cg_lot(disposal_timestamp="2025-01-24 23:40", amount=Decimal("0.5"))]
        # Different amount: no exact or range match.
        events = [_evt(amount=Decimal("9.9"))]

        result = match_lots(lots, events)

        assert result.matched_metadata == []
        assert result.unmatched_events == events
        assert result.remaining_entries == lots

    def test_remove_matched_lots_does_not_warn_for_unmatched_events(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The matcher does NOT warn for unmatched events; the caller owns that."""
        lots = [_make_cg_lot(disposal_timestamp="2025-01-24 23:40", amount=Decimal("0.5"))]
        events = [_evt(amount=Decimal("9.9"))]

        with caplog.at_level(logging.WARNING):
            remove_matched_lots(
                lots,
                events,
                domain_label="derivatives",
                logger=logging.getLogger("tax_reporting.application.crypto.derivatives_dedup"),
            )

        # Exactly one summary WARNING (the removal summary), no unmatched-event warning.
        assert len(caplog.records) == 1
        assert "dedup summary" in caplog.records[0].getMessage()


class TestMalformedInput:
    def test_non_positive_amount_lots_skipped_and_listed(self) -> None:
        lots = [
            _make_cg_lot(disposal_timestamp="2025-01-24 08:00", amount=Decimal("0")),
            _make_cg_lot(disposal_timestamp="2025-01-24 09:00", amount=Decimal("-0.5")),
            _make_cg_lot(disposal_timestamp="2025-01-24 10:00", amount=Decimal("0.5")),
        ]
        events = [_evt(timestamp="2025-01-24 10:00", amount=Decimal("0.5"))]

        result = match_lots(lots, events)

        assert len(result.malformed_input_lots) == 2
        assert {e.amount for e in result.malformed_input_lots} == {Decimal("0"), Decimal("-0.5")}
        # The good lot is matched.
        assert len(result.matched_metadata) == 1


class TestSummaryWarningContract:
    def test_remove_matched_lots_emits_exactly_one_summary(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        lots = [
            _make_cg_lot(disposal_timestamp="2025-01-24 23:40", amount=Decimal("0.5")),
            _make_cg_lot(disposal_timestamp="2025-01-24 23:40", amount=Decimal("0.5")),
        ]
        events = [_evt(amount=Decimal("0.5")), _evt(amount=Decimal("0.5"))]

        with caplog.at_level(logging.WARNING):
            remove_matched_lots(
                lots,
                events,
                domain_label="derivatives",
                logger=logging.getLogger("tax_reporting.application.crypto.derivatives_dedup"),
            )

        assert len(caplog.records) == 1, "remove_matched_lots must emit exactly one summary WARNING"

    def test_match_lots_emits_no_summary(self, caplog: pytest.LogCaptureFixture) -> None:
        lots = [_make_cg_lot(disposal_timestamp="2025-01-24 23:40", amount=Decimal("0.5"))]
        events = [_evt(amount=Decimal("0.5"))]

        with caplog.at_level(logging.WARNING):
            match_lots(lots, events)

        assert not caplog.records, "match_lots must emit no summary"

    def test_empty_events_emits_no_summary(self, caplog: pytest.LogCaptureFixture) -> None:
        lots = [_make_cg_lot(disposal_timestamp="2025-01-24 23:40", amount=Decimal("0.5"))]

        with caplog.at_level(logging.WARNING):
            result = remove_matched_lots(
                lots,
                [],
                domain_label="derivatives",
                logger=logging.getLogger("tax_reporting.application.crypto.derivatives_dedup"),
            )

        assert not caplog.records
        assert result.remaining_entries == lots
        assert result.matched_metadata == []

    @pytest.mark.parametrize(
        ("domain_label", "expected_title"),
        [
            ("derivatives", "Derivatives CG dedup summary"),
            ("fee", "Fee CG dedup summary"),
        ],
    )
    def test_domain_label_appears_in_summary_title(
        self,
        caplog: pytest.LogCaptureFixture,
        domain_label: str,
        expected_title: str,
    ) -> None:
        lots = [_make_cg_lot(disposal_timestamp="2025-01-24 23:40", amount=Decimal("0.5"))]
        events = [_evt(amount=Decimal("0.5"))]

        with caplog.at_level(logging.WARNING):
            remove_matched_lots(
                lots,
                events,
                domain_label=domain_label,
                logger=logging.getLogger(f"tax_reporting.application.crypto.{domain_label}"),
            )

        assert len(caplog.records) == 1
        msg = caplog.records[0].getMessage()
        assert msg.startswith(expected_title), f"summary title must start with {expected_title!r}: {msg}"


class TestLoggerName:
    """The summary WARNING must carry the CALLER's logger.name, not th_lot_matcher's.

    Guards against a regression that re-homes logging under the th_lot_matcher
    logger (which would break the derivatives e2e logger-name assertions and
    misattribute fee-filter warnings).
    """

    @pytest.mark.parametrize(
        ("domain_label", "caller_logger_name"),
        [
            ("derivatives", "tax_reporting.application.crypto.derivatives_dedup"),
            ("fee", "tax_reporting.application.crypto.fee_filter"),
        ],
    )
    def test_summary_carries_caller_logger_name(
        self,
        caplog: pytest.LogCaptureFixture,
        domain_label: str,
        caller_logger_name: str,
    ) -> None:
        lots = [_make_cg_lot(disposal_timestamp="2025-01-24 23:40", amount=Decimal("0.5"))]
        events = [_evt(amount=Decimal("0.5"))]

        with caplog.at_level(logging.WARNING):
            remove_matched_lots(
                lots,
                events,
                domain_label=domain_label,
                logger=logging.getLogger(caller_logger_name),
            )

        assert len(caplog.records) == 1
        assert caplog.records[0].name == caller_logger_name, (
            f"summary WARNING must carry the caller's logger.name "
            f"({caller_logger_name!r}), got {caplog.records[0].name!r}"
        )

    def test_summary_does_not_use_th_lot_matcher_logger_name(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        lots = [_make_cg_lot(disposal_timestamp="2025-01-24 23:40", amount=Decimal("0.5"))]
        events = [_evt(amount=Decimal("0.5"))]

        with caplog.at_level(logging.WARNING):
            remove_matched_lots(
                lots,
                events,
                domain_label="derivatives",
                logger=logging.getLogger("tax_reporting.application.crypto.derivatives_dedup"),
            )

        assert caplog.records[0].name != "tax_reporting.application.crypto.th_lot_matcher"


class TestPassThroughIdentity:
    def test_matched_metadata_returns_original_event_objects(self) -> None:
        """The matcher returns the original event objects unchanged (pass-through).

        This is the r6 M2 requirement: a caller receives the concrete event
        type and can read event-specific fields (e.g. ``event.label``) on the
        returned objects with no cast.
        """
        lots = [_make_cg_lot(disposal_timestamp="2025-01-24 23:40", amount=Decimal("0.5"))]
        event = _evt(amount=Decimal("0.5"))
        events = [event]

        result = match_lots(lots, events)

        _lot, _mt, returned_event = result.matched_metadata[0]
        assert returned_event is event
