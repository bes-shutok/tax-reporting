"""Pure domain types for on-chain config (wallets, LP snapshots, contract registry).

These are frozen dataclasses + one pure validator (``is_valid_iso3166_alpha2``).
They carry NO I/O and NO parsing: the loaders that build them live in
:mod:`tax_reporting.application.on_chain_config`. Infrastructure readers
(processor, integrity checker, decoder, autodiscovery) depend on THIS module,
not the application loader, so the dependency direction is
``infrastructure -> domain`` (not ``infrastructure -> application``).

Design record: ``docs/architecture/on-chain-tx-design.md`` (decisions 8, 11).
"""

from __future__ import annotations

import dataclasses
from datetime import date

import pycountry

__all__ = [
    "ContractEntry",
    "ContractRegistry",
    "LpSnapshot",
    "LpTokenEntry",
    "OnChainWalletConfig",
    "is_valid_iso3166_alpha2",
]


@dataclasses.dataclass(frozen=True)
class OnChainWalletConfig:
    """A single wallet entry from the per-year chains.json config.

    The user supplies only ``chain``/``label``/``address`` (wallet
    identity). The four chain-property fields below are DERIVED
    internally (DI-2 restated): ``chainid``/``native_ticker`` come from
    the trusted chain registry in :mod:`chain_derivation`, and
    ``start_date``/``end_date`` come from the fiscal year clamped to the
    chain's launch date / today.

    Attributes:
        chain: Human-readable chain name (e.g. ``"Berachain"``). The one
            chain-identity key supplied by the user; the registry derives
            the rest.
        chainid: Etherscan V2 numeric chain id (e.g. ``80094``). Derived
            from the chain registry via :func:`chainid_for`.
        label: Free-form wallet label used in CSV output.
        address: Wallet address this config targets.
        native_ticker: Native asset ticker for txlist rows (e.g.
            ``"BERA"``). Derived from the chain registry via
            :func:`native_ticker_for` (CSV-output-correct map).
        start_date: Inclusive start, derived as
            ``max(date(year, 1, 1), chain_launch_date)`` (Jan 1 clamped
            up to genesis for chains launching mid-year).
        end_date: Inclusive end, derived as
            ``min(date(year, 12, 31), today)`` (Dec 31 clamped down to
            today for future fiscal years).
    """

    chain: str
    chainid: int
    label: str
    address: str
    native_ticker: str
    start_date: date
    end_date: date


@dataclasses.dataclass(frozen=True)
class LpTokenEntry:
    """One LP-token entry from the snapshot's ``tokens`` list.

    Attributes:
        token_address: The LP ERC-20 / receipt-token address (lower-cased).
        protocol: Originating protocol tag (e.g. ``"Kodiak"``). Informational.
        lp_type: LP product type (``"Pair"``, ``"KodiakVault"``,
            ``"stakingToken"``). Drives downstream ``EventType`` tagging.
    """

    token_address: str
    protocol: str | None
    lp_type: str | None


@dataclasses.dataclass(frozen=True)
class LpSnapshot:
    """A loaded + validated LP-token snapshot.

    Attributes:
        subgraph: Subgraph identifier (informational).
        subgraph_version: Pinned subgraph version (NOT ``"latest"``).
        snapshot_as_of_block: The block the snapshot was taken at.
        snapshot_as_of_date: ISO date string the snapshot was taken on.
        tokens: ``{lower-cased token_address: LpTokenEntry}`` for O(1)
            lookup by the autodiscovery primary path.
        source: Where the snapshot was loaded from (path or marker), for
            error messages.
    """

    subgraph: str | None
    subgraph_version: str
    snapshot_as_of_block: int
    snapshot_as_of_date: str
    tokens: dict[str, LpTokenEntry]
    source: str


@dataclasses.dataclass(frozen=True)
class ContractEntry:
    """One contract entry from the registry's ``contracts`` list.

    Attributes:
        address: The contract address (lower-cased).
        label: Human-readable label (informational).
        kind: One of :data:`_CONTRACT_KINDS` (``dex_router``,
            ``reward_distributor``, ``rebate_router``, ``self_wallet``).
            Drives processor classification. ``self_wallet`` (C3) marks the
            tracked wallet's other own wallets: transfers to/from such an
            address classify as ``Transfer``, not Reward/spam or Unknown.
        protocol: Originating protocol tag (informational).
        operator_country: ISO-3166 alpha-2 country code for the operator's
            domicile, or ``None`` when the contract falls through to the
            chain-level mapping (the Berachain default per B3).
        citation: URL citing the PRIMARY source justifying
            ``operator_country`` when it is set; ``None`` when
            ``operator_country`` is ``None``.
    """

    address: str
    label: str | None
    kind: str
    protocol: str | None
    operator_country: str | None
    citation: str | None


@dataclasses.dataclass(frozen=True)
class ContractRegistry:
    """A loaded + validated per-chain contract registry.

    Provides an O(1) lower-cased ``address`` -> :class:`ContractEntry`
    lookup via :meth:`get` (the processor consults this for reward-sender
    verification and DEX-router detection). The ``chain`` field is
    informational (the loader does not cross-check it against the chain
    registry; the orchestrator selects the right file per chain).
    """

    chain: str | None
    contracts: dict[str, ContractEntry]
    source: str

    def get(self, address: str) -> ContractEntry | None:
        """Return the entry for ``address`` (case-insensitive) or ``None``."""
        return self.contracts.get(address.lower())


def is_valid_iso3166_alpha2(code: str) -> bool:
    """Return True iff ``code`` is a valid ISO-3166 alpha-2 country code.

    Uses :mod:`pycountry` (a project dependency per ``pyproject.toml``) as
    the authoritative closed enum (Attacker F1: a hand-rolled allowlist
    would silently rot as country codes are amended). ``code`` is upper-cased
    before lookup (ISO-3166 alpha-2 is case-insensitive in practice).

    Public so the post-run integrity checker
    (:mod:`tax_reporting.infrastructure.on_chain.integrity_invariants`,
    Plan Task 13) can reuse the EXACT validator the loader uses (DRY:
    AGENTS.md rule 30 -- sibling validators must use a shared helper, not
    two hand-parallel copies).
    """
    try:
        return pycountry.countries.get(alpha_2=code.upper()) is not None
    except (KeyError, AttributeError):
        # Defensive: a malformed code or a pycountry quirk -> treat as
        # invalid (fail-closed).
        return False


# Backward-compat alias for the original private name (the loader's internal
# call site). New callers should use the public ``is_valid_iso3166_alpha2``.
_is_valid_iso3166_alpha2 = is_valid_iso3166_alpha2
