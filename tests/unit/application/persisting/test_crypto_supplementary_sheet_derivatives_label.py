"""W9: ``_write_review_rows`` label map coverage for ``source_section="derivatives"``.

Locks the exhaustiveness guard added by Task 9: a new ``source_section`` Literal
value must be added to the label map explicitly (no silent ``.get(..., "Income")``
fallback that would misrender as "Income").
"""

from __future__ import annotations

from typing import cast

import openpyxl
import pytest

from tax_reporting.application.crypto.entities import CryptoReviewEntry


def _render_first_column(review_entries: list[CryptoReviewEntry]) -> str:
    """Render the review block and return col 1 of the first data row."""
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    from tax_reporting.application.persisting.crypto_supplementary_sheet import (
        _write_review_rows,
    )

    # row_no=1: headers land on row 1, data starts on row 2.
    _write_review_rows(worksheet, 1, review_entries)
    return worksheet.cell(row=2, column=1).value


class TestWriteReviewRows:
    def test_derivatives_source_label(self):
        """Given a CryptoReviewEntry(source_section="derivatives"), col 1 renders "Derivatives"."""
        entry = CryptoReviewEntry(
            source_section="derivatives",
            date="2025-01-12",
            asset="USDT",
            platform="ByBit",
            review_reason="OGR row routed to derivatives by row type; no CG counterpart",
        )
        assert _render_first_column([entry]) == "Derivatives"

    def test_unknown_source_section_raises(self):
        """An unknown ``source_section`` Literal value fails loudly (exhaustiveness guard).

        Drives the failure path of the explicit ``else`` raise so a future
        regression reverting to silent ``.get(..., "Income")`` fails the suite
        instead of silently misrendering.
        """
        entry = CryptoReviewEntry(
            source_section=cast(str, "bogus"),
            date="2025-01-12",
            asset="USDT",
            platform="ByBit",
            review_reason="synthetic entry to drive the exhaustiveness guard",
        )
        with pytest.raises(AssertionError, match="Unknown CryptoReviewEntry.source_section"):
            _render_first_column([entry])
