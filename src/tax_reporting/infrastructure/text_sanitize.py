"""Layer-agnostic control-character stripping for cell-bound strings.

This module intentionally does NOT defuse Excel formula sigils (``= + - @``).
Formula-sigil defusal is a presentation concern that belongs to the Excel
layer (see :func:`tax_reporting.application.persisting.excel_utils.safe_cell_value`);
callers outside ``persisting/`` that only need control-char removal (e.g.
substring sanitization in domain/application code) should use
:func:`strip_control_chars` so they do not gain an unwanted dependency on the
presentation layer.

See docs/maintenance/development_lessons.md #7 for the Excel security guidance
that motivated this split.
"""

from __future__ import annotations


def strip_control_chars(value: str) -> str:
    r"""Remove control characters from a string, keeping printable chars and tab.

    Keeps any character whose code point is at least U+0020 (space) plus the
    tab character (``\t``). Every other control character (NUL, BEL, newline,
    carriage return, form feed, ...) is stripped. This is layer-agnostic: it
    does not neutralize Excel formula sigils (``= + - @``).

    Args:
        value: The raw string to clean.

    Returns:
        The string with control characters removed.
    """
    return "".join(ch for ch in value if ch >= " " or ch in ("\t",))
