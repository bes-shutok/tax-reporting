"""Portuguese IRS tax constants for Excel reporting.

This module defines constants used for Portuguese tax reporting labels and
descriptions, particularly income codes from Tabela V used for categorizing
capital investment income.
"""

from __future__ import annotations

_INCOME_CODE_DESCRIPTIONS: dict[str, str] = {
    "401": "Crypto capital income (staking, rewards, airdrops)",
    "402": "Crypto interest (lending, deposit interest)",
    "403": "Mining income",
    "404": "Fork income",
    "405": "Crypto dividends",
}


def get_income_code_description(income_code: str) -> str:
    """Get human-readable description for a Portuguese Tabela V income code.

    Args:
        income_code: The Tabela V income code (e.g., "401").

    Returns:
        Human-readable description for the income code, or the code itself
        if not found in the mapping.
    """
    return _INCOME_CODE_DESCRIPTIONS.get(income_code, f"Income code {income_code}")
