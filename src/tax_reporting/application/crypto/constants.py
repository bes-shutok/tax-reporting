"""Shared constants for crypto reporting modules.

This module centralizes constants used across multiple crypto sub-modules
to avoid duplication while preventing circular import dependencies.
"""

from __future__ import annotations

from decimal import Decimal

# Zero value for decimal calculations
ZERO: Decimal = Decimal("0")

__all__ = ["ZERO"]
