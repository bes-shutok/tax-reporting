"""Direct unit tests for the shared TH-lot matcher (extracted from derivatives_filter).

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
    CryptoDecisionCounts,
    CryptoReviewEntry,
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

        with caplog.at_level(logging.INFO):
            remove_matched_lots(
                lots,
                events,
                domain_label="derivatives",
                logger=logging.getLogger("tax_reporting.application.crypto.derivatives_filter"),
            )

        # Exactly one summary INFO (the removal summary), no unmatched-event warning.
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


class TestSummaryLevelContract:
    def test_remove_matched_lots_emits_exactly_one_summary(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        lots = [
            _make_cg_lot(disposal_timestamp="2025-01-24 23:40", amount=Decimal("0.5")),
            _make_cg_lot(disposal_timestamp="2025-01-24 23:40", amount=Decimal("0.5")),
        ]
        events = [_evt(amount=Decimal("0.5")), _evt(amount=Decimal("0.5"))]

        with caplog.at_level(logging.INFO):
            remove_matched_lots(
                lots,
                events,
                domain_label="derivatives",
                logger=logging.getLogger("tax_reporting.application.crypto.derivatives_filter"),
            )

        assert len(caplog.records) == 1, "remove_matched_lots must emit exactly one summary INFO"

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
                logger=logging.getLogger("tax_reporting.application.crypto.derivatives_filter"),
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

        with caplog.at_level(logging.INFO):
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
    """The summary INFO must carry the CALLER's logger.name, not th_lot_matcher's.

    Guards against a regression that re-homes logging under the th_lot_matcher
    logger (which would break the derivatives e2e logger-name assertions and
    misattribute fee-filter logs). (W6 was demoted WARNING -> INFO per rule #7
    EXTRACT_SURFACED; per-row detail now surfaces as CryptoReviewEntry rows +
    an A&M count cell.)
    """

    @pytest.mark.parametrize(
        ("domain_label", "caller_logger_name"),
        [
            ("derivatives", "tax_reporting.application.crypto.derivatives_filter"),
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

        with caplog.at_level(logging.INFO):
            remove_matched_lots(
                lots,
                events,
                domain_label=domain_label,
                logger=logging.getLogger(caller_logger_name),
            )

        assert len(caplog.records) == 1
        assert caplog.records[0].name == caller_logger_name, (
            f"summary INFO must carry the caller's logger.name "
            f"({caller_logger_name!r}), got {caplog.records[0].name!r}"
        )

    def test_summary_does_not_use_th_lot_matcher_logger_name(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        lots = [_make_cg_lot(disposal_timestamp="2025-01-24 23:40", amount=Decimal("0.5"))]
        events = [_evt(amount=Decimal("0.5"))]

        with caplog.at_level(logging.INFO):
            remove_matched_lots(
                lots,
                events,
                domain_label="derivatives",
                logger=logging.getLogger("tax_reporting.application.crypto.derivatives_filter"),
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


class TestRemoveMatchedLots:
    """M4: ``remove_matched_lots`` is domain-neutral.

    The matcher owns ONLY the match + the single summary INFO emit. It does NOT
    append :class:`CryptoReviewEntry` rows and does NOT write any
    ``decision_counts.*dedup`` field: those are caller-owned (the derivatives
    caller owns the review rows + ``derivatives_dedup_removed``; see
    ``test_derivatives_filter.py``). The ``review_entries`` / ``decision_counts``
    params stay as ``= None`` no-op defaults (INV-3 backward compat) so the
    ~10 existing test callers that omit them stay green, but their presence
    triggers nothing.
    """

    _CALLER_LOGGER_NAME = "tax_reporting.application.crypto.derivatives_filter"

    def test_matcher_emits_summary_info_but_no_review_rows(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Given matched/surplus/malformed lots, expects ONE summary INFO record
        but ZERO ``CryptoReviewEntry`` appends (the matcher is domain-neutral;
        callers own review rows).
        """
        lots = [
            _make_cg_lot(
                disposal_timestamp="2025-01-24 08:00", amount=Decimal("0")
            ),
            _make_cg_lot(
                disposal_timestamp="2025-01-24 09:00", amount=Decimal("-0.5")
            ),
            _make_cg_lot(
                disposal_timestamp="2025-01-24 10:00", amount=Decimal("0.5")
            ),
            _make_cg_lot(
                disposal_timestamp="2025-01-24 23:40",
                amount=Decimal("0.5"),
                acquisition_date="2025-01-12",
            ),
        ]
        events = [_evt(timestamp="2025-01-24 10:00", amount=Decimal("0.5"))]
        review_entries: list[CryptoReviewEntry] = []

        with caplog.at_level(logging.INFO, logger=self._CALLER_LOGGER_NAME):
            remove_matched_lots(
                lots,
                events,
                domain_label="derivatives",
                logger=logging.getLogger(self._CALLER_LOGGER_NAME),
                review_entries=review_entries,
            )

        summary_records = [
            r for r in caplog.records if "summary" in r.getMessage()
        ]
        assert len(summary_records) >= 1, (
            "matcher must still emit its single summary INFO"
        )
        assert review_entries == [], (
            f"matcher must append ZERO review rows (domain-neutral); "
            f"got {len(review_entries)}: "
            f"{[e.review_reason for e in review_entries]}"
        )

    def test_matcher_appends_zero_review_rows_for_matched_lots(self) -> None:
        """Given 3 matched lots, expects ZERO ``CryptoReviewEntry`` appends.

        The removed-lot review rows now live at the caller
        (``remove_derivatives_flagged_lots``); the matcher is match-only.
        """
        lots = [
            _make_cg_lot(
                disposal_timestamp="2025-01-24 23:40",
                amount=Decimal("0.5"),
                acquisition_date=f"2025-01-{day:02d}",
            )
            for day in (10, 11, 12)
        ]
        events = [_evt(amount=Decimal("0.5")) for _ in range(3)]
        review_entries: list[CryptoReviewEntry] = []

        remove_matched_lots(
            lots,
            events,
            domain_label="derivatives",
            logger=logging.getLogger(self._CALLER_LOGGER_NAME),
            review_entries=review_entries,
        )

        assert review_entries == [], (
            f"matcher must append ZERO review rows; got {len(review_entries)}: "
            f"{[e.review_reason for e in review_entries]}"
        )

    def test_matcher_appends_zero_review_rows_for_surplus_and_malformed_lots(
        self,
    ) -> None:
        """Given surplus + malformed lots, expects ZERO ``CryptoReviewEntry``
        appends. The surplus/malformed review rows now live at the caller.
        """
        lots = [
            _make_cg_lot(
                disposal_timestamp="2025-01-24 08:00", amount=Decimal("0")
            ),
            _make_cg_lot(
                disposal_timestamp="2025-01-24 09:00", amount=Decimal("-0.5")
            ),
            _make_cg_lot(
                disposal_timestamp="2025-01-24 23:40",
                amount=Decimal("0.5"),
                acquisition_date="2025-01-10",
            ),
            _make_cg_lot(
                disposal_timestamp="2025-01-24 23:40",
                amount=Decimal("0.5"),
                acquisition_date="2025-01-12",
            ),
        ]
        events = [_evt(amount=Decimal("0.5"))]
        review_entries: list[CryptoReviewEntry] = []

        remove_matched_lots(
            lots,
            events,
            domain_label="derivatives",
            logger=logging.getLogger(self._CALLER_LOGGER_NAME),
            review_entries=review_entries,
        )

        assert review_entries == [], (
            f"matcher must append ZERO review rows; got {len(review_entries)}: "
            f"{[e.review_reason for e in review_entries]}"
        )

    def test_matcher_does_not_set_decision_counts_dedup_field(self) -> None:
        """Given a non-empty match, the matcher must NOT write any
        ``decision_counts.*dedup`` field (caller-owned; INV-4a)."""
        lots = [
            _make_cg_lot(
                disposal_timestamp="2025-01-24 23:40", amount=Decimal("0.5")
            )
        ]
        events = [_evt(amount=Decimal("0.5"))]
        counts = CryptoDecisionCounts()
        before = counts.derivatives_dedup_removed

        remove_matched_lots(
            lots,
            events,
            domain_label="derivatives",
            logger=logging.getLogger(self._CALLER_LOGGER_NAME),
            decision_counts=counts,
        )

        assert counts.derivatives_dedup_removed == before, (
            "matcher must not touch derivatives_dedup_removed; got "
            f"{counts.derivatives_dedup_removed}"
        )

    def test_derivatives_dedup_summary_emits_info(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Given any non-empty derivatives dedup, expects ONE INFO record
        containing "Derivatives CG dedup summary" and ZERO WARNING records.
        """
        lots = [_make_cg_lot(disposal_timestamp="2025-01-24 23:40", amount=Decimal("0.5"))]
        events = [_evt(amount=Decimal("0.5"))]

        with caplog.at_level(logging.INFO, logger=self._CALLER_LOGGER_NAME):
            remove_matched_lots(
                lots,
                events,
                domain_label="derivatives",
                logger=logging.getLogger(self._CALLER_LOGGER_NAME),
            )

        summary_records = [
            r
            for r in caplog.records
            if "Derivatives CG dedup summary" in r.getMessage()
        ]
        assert len(summary_records) == 1, (
            f"expected ONE summary record; got {len(summary_records)}: "
            f"{[r.getMessage() for r in summary_records]}"
        )
        assert summary_records[0].levelno == logging.INFO, (
            f"summary must be INFO; got level {summary_records[0].levelno}"
        )
        warning_records = [
            r
            for r in caplog.records
            if r.levelno == logging.WARNING and "Derivatives CG dedup summary" in r.getMessage()
        ]
        assert warning_records == [], (
            "summary must NOT emit at WARNING; demoted to INFO"
        )
