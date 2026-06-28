"""Income-code description lookup for Excel reporting.

The crypto package is the single owner of the official income-code ->
description mapping (Invariant 5; see
:mod:`tax_reporting.application.crypto.classification`). This module derives
the description half from there and exposes the legacy
``_INCOME_CODE_DESCRIPTIONS`` re-export plus a :func:`get_income_code_description`
helper used by the IB and crypto supplementary sheets.
"""

from __future__ import annotations

from tax_reporting.application.crypto.classification import INCOME_CODE_DESCRIPTIONS as _INCOME_CODE_DESCRIPTIONS


def get_income_code_description(income_code: str) -> str:
    """Get the human-readable description for an official income code.

    Args:
        income_code: The official income code (e.g., "E25").

    Returns:
        Human-readable description for the income code, ``""`` when the code
        is blank, or ``f"Income code {income_code}"`` for a non-blank unknown
        code (preserved so unmapped codes are still surfaced in output).
    """
    if not income_code:
        return ""
    return _INCOME_CODE_DESCRIPTIONS.get(income_code, f"Income code {income_code}")
