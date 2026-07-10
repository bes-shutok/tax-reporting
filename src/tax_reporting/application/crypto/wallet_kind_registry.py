"""Production WalletKind registry adapter (Phase D Task 1).

Implements ``RegistrySnapshot`` (Phase A Protocol defined in
``wallet_kind.py``) by sourcing each platform's WalletKind from
``resolve_operator_origin`` via the new ``wallet_kind`` field on
``OperatorOrigin``. This closes the Phase A deferred-registry gap: Phase A
documented that ``operator_origin`` does NOT classify CEX/DEX and callers
pass ``registry=None``, forcing every platform through tier-2
auto-discovery. Phase D Task 1 makes the registry authoritative.

Closing the 540-row Binance gap is the headline motivation: under Phase A
auto-discovery, Binance's Kind column rendered blank (no TH row evidence
attributed to "Binance" because Koinly emits a platform label that the
voting logic could not tie to a kind). With the production registry,
Binance resolves to CEX at tier 1 (confidence 1.0) directly from the
operator-entity classification (``operator_origin.py`` ``"binance"``
branch -> "Binance Spain, S.L." is a centralized exchange operator).

The adapter is constructed in ``generate_tax_report``
(``workbook_builder.py``) and flows through the relaxed gate at
``assumptions_sheet.py:111`` (``if th_rows is not None or registry is not
None:``) so the registry-only call path actually fires the classifier.

Platforms not recognized by the entity chain return None so the caller
falls through to tier-2 auto-discovery. A small set of self-custody
wallet labels (e.g. "Ledger") are looked up directly against
``_PLATFORM_KIND`` because they have no operator entity but are on-chain
by definition.
"""

from __future__ import annotations

from ...domain.transaction import WalletKind
from .operator_origin import resolve_operator_origin
from .wallet_kind import RegistrySnapshot

__all__ = ["ProductionWalletKindRegistry"]


class ProductionWalletKindRegistry(RegistrySnapshot):
    """Production tier-1 WalletKind registry backed by operator_origin.

    Calls ``resolve_operator_origin(platform)`` and returns
    ``origin.wallet_kind``. ``resolve_operator_origin`` stamps
    ``wallet_kind`` from ``_PLATFORM_KIND`` for every recognized platform,
    including self-custody wallet labels such as "Ledger" that have no
    operator entity but are on-chain by definition. Returns None when the
    entity chain does not recognize the platform, so the caller falls
    through to tier-2 auto-discovery.
    """

    def classify(self, platform: str) -> WalletKind | None:
        origin = resolve_operator_origin(platform)
        return origin.wallet_kind
