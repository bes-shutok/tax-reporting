"""Unit tests for the Koinly combo vocabulary module (reverse map + lookups).

Plan: ``docs/history/plans/2026-08-26-comparator-combo-extraction.md`` (Task 3).

The two collision tests moved here from
``test_on_chain_validation_comparator.py`` (whole tests, params included); the
adapter ``monkeypatch.setattr`` seam is unchanged - the builder deliberately
reads the adapter MODULE attributes at call time, so patching
``on_chain_th_adapter`` is still visible after the move.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from tax_reporting.application import on_chain_th_adapter as adapter_module
from tax_reporting.application.koinly_combo_map import (
    KOINLY_COMBO_TO_EVENT_TYPE,
    build_reverse_combo_map,
    event_type_of,
    koinly_tag,
    koinly_text,
    row_combo,
)
from tax_reporting.application.on_chain_th_adapter import ProjectedThRow, koinly_combo
from tax_reporting.domain.on_chain_transaction import EventType, SubType
from tax_reporting.domain.transaction import TransactionHistoryRow


class TestKoinlyComboMap:
    def test_reverse_map_tracks_adapter_vocabulary(self) -> None:
        # Vocabulary pin (net-new, r1-F2): the shipped reverse map must equal
        # the exact inversion of the REAL adapter vocabulary - every base
        # combo and every override combo maps back to its EventType via the
        # adapter's own ``koinly_combo`` rendering. A manual registration or
        # a stale map drifts from this equality.
        expected = {koinly_combo(event_type, None): event_type for event_type in adapter_module.EVENT_TYPE_TO_KOINLY}
        for event_type, sub_type in adapter_module.SUB_TYPE_TAG_OVERRIDES:
            expected[koinly_combo(event_type, sub_type)] = event_type

        assert dict(KOINLY_COMBO_TO_EVENT_TYPE) == expected

    @pytest.mark.parametrize(
        "colliding_overrides",
        [
            # Override tag equals a BASE combo tag: (Reward, bridge) -> "Reward"
            # collides with the base (crypto_deposit, "Reward") combo.
            {(EventType.Reward, SubType.bridge): "Reward"},
            # Two overrides colliding on one combo (both keep base type
            # crypto_deposit, same tag).
            {(EventType.Reward, SubType.bridge): "Bridge", (EventType.Reward, SubType.spam): "Bridge"},
        ],
    )
    def test_reverse_map_collision_raises(self, monkeypatch, colliding_overrides) -> None:
        # Review r1 F4: the reverse-map injectivity guard is the only barrier
        # between a future override edit and silent EventType mis-mapping in
        # the validation gate; each collision mode must raise at build time
        # naming the colliding combo (not merely fail a length arithmetic
        # check). The builder derives combos via the adapter's koinly_combo,
        # so the colliding vocabulary is injected by patching the adapter
        # dict it reads.
        monkeypatch.setattr(adapter_module, "SUB_TYPE_TAG_OVERRIDES", dict(colliding_overrides))
        with pytest.raises(RuntimeError, match="claimed twice"):
            build_reverse_combo_map()

    def test_reverse_map_bad_forward_map_raises(self, monkeypatch) -> None:
        # Review r4 (and the corrected r3 note): the restored BASE-map
        # injectivity guard must raise when two EventTypes share one combo -
        # the exact master-era regression the r2 rewrite introduced
        # (last-writer-wins comprehension).
        bad = dict(adapter_module.EVENT_TYPE_TO_KOINLY)
        bad[EventType.Unknown] = bad[EventType.Reward]  # two EventTypes, one combo
        monkeypatch.setattr(adapter_module, "EVENT_TYPE_TO_KOINLY", bad)

        with pytest.raises(RuntimeError, match="combos collide"):
            build_reverse_combo_map()


class TestKoinlyComboMapReaders:
    """Direct unit tests for the four public readers (review r4 F1)."""

    def test_koinly_text_absent_cell_returns_empty_sentinel(self) -> None:
        assert koinly_text({}, "Type") == ""

    @pytest.mark.parametrize("value", ["", "   ", " \t \n "])
    def test_koinly_text_empty_or_whitespace_cell_returns_empty_sentinel(self, value: str) -> None:
        assert koinly_text({"Type": value}, "Type") == ""

    def test_koinly_text_strips_surrounding_whitespace(self) -> None:
        assert koinly_text({"Type": "  crypto_deposit \t"}, "Type") == "crypto_deposit"

    def test_koinly_tag_absent_cell_returns_empty_sentinel(self) -> None:
        assert koinly_tag({}) == ""

    @pytest.mark.parametrize("value", ["", "   "])
    def test_koinly_tag_empty_or_whitespace_cell_returns_empty_sentinel(self, value: str) -> None:
        assert koinly_tag({"Tag": value}) == ""

    def test_koinly_tag_strips_surrounding_whitespace(self) -> None:
        assert koinly_tag({"Tag": "  Bridge  "}) == "Bridge"

    def test_row_combo_pairs_stripped_type_with_stripped_tag(self) -> None:
        assert row_combo({"Type": " crypto_deposit ", "Tag": " Reward "}) == ("crypto_deposit", "Reward")

    def test_row_combo_absent_tag_yields_empty_tag_component(self) -> None:
        assert row_combo({"Type": "crypto_deposit"}) == ("crypto_deposit", "")

    def test_event_type_of_known_combo_recovers_event_type(self) -> None:
        combo = koinly_combo(EventType.Reward, None)
        assert combo in KOINLY_COMBO_TO_EVENT_TYPE  # vocabulary sanity for the fixture
        assert event_type_of(_projected(combo[0], combo[1])) is EventType.Reward

    def test_event_type_of_unknown_combo_falls_back_to_unknown(self) -> None:
        assert event_type_of(_projected("not_a_koinly_type", "NotATag")) is EventType.Unknown


def _projected(type_: str, tag: str) -> ProjectedThRow:
    """A minimal projected row carrying only the combo cells (reader fixture)."""
    row = TransactionHistoryRow(
        utc_instant=datetime(2025, 3, 1, 12, 0, 0, tzinfo=UTC),
        type=type_,
        tag=tag,
        sending_wallet="",
        sending_amount=None,
        sending_currency=None,
        receiving_wallet="",
        receiving_amount=Decimal("1"),
        receiving_currency="BGT",
        tx_hash="0xabc",
        tx_src=None,
        tx_dest="0xdest",
        row_index=0,
    )
    return ProjectedThRow(row=row, fee=None)
