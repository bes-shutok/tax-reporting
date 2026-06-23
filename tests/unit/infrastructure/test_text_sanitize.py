"""Tests for text sanitization helpers.

These tests pin the behavior of ``strip_control_chars`` before the
production module ``src/tax_reporting/infrastructure/text_sanitize.py``
exists (RED phase). The predicate Task 2 will extract is the one
currently inlined in ``safe_cell_value``::

    "".join(ch for ch in value if ch >= " " or ch in ("\t",))

i.e. printable characters (code point >= U+0020) and the tab character
are kept; every other control character (NUL, BEL, newline, carriage
return, form feed, ...) is stripped.
"""

import pytest

from tax_reporting.infrastructure.text_sanitize import strip_control_chars


@pytest.mark.unit
class TestStripControlChars:
    """Test stripping of control characters from cell-bound strings."""

    def test_strips_control_chars_keeps_printable(self):
        # Given
        value = "a\x00b\x07c"

        # When
        result = strip_control_chars(value)

        # Then
        assert result == "abc"

    def test_preserves_tab(self):
        # Given - tab is the only control char kept, matching safe_cell_value
        value = "a\tb"

        # When
        result = strip_control_chars(value)

        # Then
        assert result == "a\tb"

    def test_strips_newline_cr_ff(self):
        # Given
        value = "a\nb\rc\fd"

        # When
        result = strip_control_chars(value)

        # Then
        assert result == "abcd"

    def test_empty_string(self):
        # Given
        value = ""

        # When
        result = strip_control_chars(value)

        # Then
        assert result == ""

    def test_whitespace_only_preserved(self):
        # Given - regular spaces (>= " ") are printable, kept as-is
        value = "   "

        # When
        result = strip_control_chars(value)

        # Then
        assert result == "   "

    def test_multi_byte_utf8_preserved(self):
        # Given
        value = "测试"

        # When
        result = strip_control_chars(value)

        # Then
        assert result == "测试"

    def test_does_not_defuse_formula_sigil(self):
        # Given - strip is layer-agnostic; defusal is Excel's job (binds the split)
        value = "=evil"

        # When
        result = strip_control_chars(value)

        # Then
        assert result == "=evil"
