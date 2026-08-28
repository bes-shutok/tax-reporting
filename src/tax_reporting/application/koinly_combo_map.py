"""Koinly ``(Type, Tag)`` combo vocabulary lookup for the validation harness.

The adapter module :mod:`tax_reporting.application.on_chain_th_adapter` is the
SINGLE vocabulary source: the reverse combo map here is DERIVED at import from
the adapter's ``EVENT_TYPE_TO_KOINLY`` + ``SUB_TYPE_TAG_OVERRIDES`` (no manual
registration), and the builder deliberately reads those dicts through the
adapter MODULE object at call time (not ``from``-imported names) so tests that
monkeypatch ``on_chain_th_adapter`` still see the patched dicts.

Extracted from ``on_chain_validation/comparator.py`` (module-size rule;
behavior identical).

Plan: ``docs/history/plans/2026-08-26-comparator-combo-extraction.md`` (Task 2).
"""

from __future__ import annotations

from typing import Final

from tax_reporting.application import on_chain_th_adapter as _adapter
from tax_reporting.application.on_chain_th_adapter import ProjectedThRow, koinly_combo
from tax_reporting.domain.on_chain_transaction import EventType

__all__ = [
    "KOINLY_COMBO_TO_EVENT_TYPE",
    "build_reverse_combo_map",
    "event_type_of",
    "koinly_tag",
    "koinly_text",
    "row_combo",
]


def build_reverse_combo_map() -> dict[tuple[str, str], EventType]:
    """Build the injective reverse combo map (see ``KOINLY_COMBO_TO_EVENT_TYPE`` docs); fail loudly on any collision."""
    # Both halves derive through the adapter's koinly_combo (review r2 F3):
    # the base half asks for the no-override rendering, the override half
    # iterates the adapter module's live vocabulary, so a future vocabulary
    # change flows through the one application-rule owner on both sides.
    # The maps are read through the MODULE ATTRIBUTE (not from-imported
    # names) deliberately: collision tests monkeypatch the adapter module's
    # dicts, and a from-import binding in this module would keep seeing the
    # original objects.
    forward = _adapter.EVENT_TYPE_TO_KOINLY
    reverse = {koinly_combo(event_type, None): event_type for event_type in forward}
    if len(reverse) != len(forward):
        # Review r3 (restored master guard): a base-vs-base collision in the
        # forward map must fail loudly at build time, not silently keep the
        # last EventType (last-writer-wins would misclassify validation
        # records for one of the two colliding types).
        raise RuntimeError(
            f"EVENT_TYPE_TO_KOINLY combos collide; cannot invert for "
            f"validation: {forward}"
        )
    for event_type, sub_type in _adapter.SUB_TYPE_TAG_OVERRIDES:
        override_combo = koinly_combo(event_type, sub_type)
        if override_combo in reverse:
            raise RuntimeError(
                f"Koinly combo {override_combo} is claimed twice; cannot invert "
                f"for validation (base map: {forward}; overrides: {_adapter.SUB_TYPE_TAG_OVERRIDES})"
            )
        reverse[override_combo] = event_type
    return reverse


#: Reverse of the adapter's ``EVENT_TYPE_TO_KOINLY`` PLUS the adapter's
#: ``SUB_TYPE_TAG_OVERRIDES`` vocabulary: recovering the ``EventType``
#: behind a projected row from its ``(type, tag)`` combo. Built by
#: :func:`build_reverse_combo_map`, which fails loudly on any collision -
#: naming the colliding combo for override collisions - when a future
#: adapter change collides two EventTypes on one combo - base-vs-base,
#: base-vs-override, or override-vs-override - instead of silently
#: mis-classifying validation records.
KOINLY_COMBO_TO_EVENT_TYPE: Final[dict[tuple[str, str], EventType]] = build_reverse_combo_map()


def koinly_text(row: dict[str, str], key: str) -> str:
    """Stripped cell text; ``""`` for absent cells (type-safe sentinel)."""
    return (row.get(key) or "").strip()


def koinly_tag(row: dict[str, str]) -> str:
    """Stripped ``Tag`` cell text; ``""`` for absent cells."""
    return koinly_text(row, "Tag")


def row_combo(row: dict[str, str]) -> tuple[str, str]:
    """The row's ``(Type, Tag)`` combo (the vocabulary key)."""
    return (koinly_text(row, "Type"), koinly_tag(row))


def event_type_of(projected: ProjectedThRow) -> EventType:
    """Recover the ``EventType`` behind a projected row.

    The adapter stamps each row with its ``EVENT_TYPE_TO_KOINLY`` combo, so
    the (injective, import-guarded) reverse lookup recovers the event type
    without the comparator re-deriving classification. A combo outside the
    mapping (future adapter vocabulary) maps to ``EventType.Unknown``, which
    ``EVENT_COMPATIBILITY`` in ``on_chain_validation.comparator`` holds
    incompatible - it flags divergence instead of silently passing.
    """
    return KOINLY_COMBO_TO_EVENT_TYPE.get((projected.row.type, projected.row.tag), EventType.Unknown)
