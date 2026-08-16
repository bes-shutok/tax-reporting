"""On-chain-native transaction domain model: ``OnChainTransaction``/``Event``/``Leg``/``Gas`` + enums.

Why a *separate* model from the Koinly-shaped ``TransactionHistoryRow``?
-----------------------------------------------------------------------

The existing crypto tax pipeline consumes Koinly's *transaction-history* export
via ``TransactionHistoryRow`` (``domain/transaction.py``). Koinly is an
``Aggregator`` source (see the design record): it has already *collapsed and
interpreted* the raw on-chain movements into one row per economic event, dropping
detail the chain actually carries. Concretely, on a single EVM transaction with N
token-movement legs:

- **Koinly collapses multi-leg swaps** into one ``exchange`` row, netting dust
  and refund legs, and folds multi-input swaps into a single sent/received pair.
- **Koinly drops gas** for ~90% of shared transactions (384 of 424 Berachain txs
  have a non-zero BERA gas fee Koinly never surfaces in the TH ``Fee Amount``
  column).
- **Koinly silently drops gas-only transactions** (zero-value native outflows
  that burn only gas) and unrecognized spam airdrops.

On-chain data is *richer and more honest*: one ``tx_hash`` has N token-movement
``Leg`` and burns gas exactly once. So the native model here preserves that
shape -- one ``OnChainTransaction`` per ``tx_hash`` holds N ``Event`` and a
single parent-tx-level ``Gas`` (gas is a property of the tx, not of any leg/Event;
attaching it to one Event is artificial, replicating it across Events
double-counts). A separate ``application/on_chain_th_adapter.py`` (Task 10) then
projects this honest model onto the lossy ``TransactionHistoryRow`` shape the
existing consumers already read.

This module is **pure data** -- frozen dataclasses and closed enums, no I/O and
no parsing. The CSV reader (Task 7) and per-chain processor (Task 9) build these
objects; nothing here touches the filesystem or the network.

Design record: ``docs/architecture/on-chain-tx-design.md`` (§3 gas model, §9.1
tag vocabulary, decisions 4, 9, 15).
Implementation plan: ``docs/history/plans/2026-08-02-on-chain-tx-tagger.md``.

Enum value choices
------------------

``EventType`` and ``SubType`` use ``Enum`` (not ``StrEnum``) with explicit
snake/Pascal string ``.value``, mirroring the established convention in
``domain/treatment.py::Treatment`` (also ``Enum`` with snake-case values). The
design record and plan both specify plain ``Enum``; no concrete serialization
requirement in the design record called for ``StrEnum`` (Task 10's adapter maps
``EventType`` to Koinly ``Type``/``Tag`` via an explicit dict rather than
serializing the enum directly), so the repo convention wins. The chosen
``.value`` strings are stable serialization references (``"swap"``,
``"liquidity_deposit"``, ``"staking"``, ...).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Final, Literal

# Run-level unknown-direction invariant (Attacker F7 / AGENTS.md). Shared by
# the per-chain processor (runtime gate) and the integrity checker (post-run
# audit echo). Hoisted here so the two infra modules import ONE source rather
# than keeping duplicate copies "in sync".
#
# UNKNOWN_DIRECTION_MAX_FRACTION: if MORE THAN this fraction of a wallet's
#   legs have ``direction="unknown"``, the run aborts (fail-loud) - a
#   silently-high unknown rate signals a decoder/regression problem.
# UNKNOWN_DIRECTION_MIN_ABSOLUTE: small-N absolute floor. The gate fires only
#   when the fraction threshold is exceeded AND at least this many unknown
#   legs are observed, so a single weird tx in a small wallet (1/50 = 2%)
#   does NOT abort while a systemic regression (many unknowns) still does.
UNKNOWN_DIRECTION_MAX_FRACTION: Final = 0.01
UNKNOWN_DIRECTION_MIN_ABSOLUTE: Final = 5


class EventType(Enum):
    """Closed seven-value economic-shape classification for an on-chain Event.

    Encodes the *shape* of an event only (BIDIRECTIONAL swap, PURE_INFLOW
    reward, GAS_ONLY burn, ...), grounded in the four observed Berachain
    leg-pattern shapes. Orthogonal to ``SubType``: instrument/treatment detail
    that can vary independently lives there, not here. See §9.1 of the design
    record for the per-member fire-condition and the Koinly ``Type``/``Tag``
    each maps to at the adapter.
    """

    Swap = "swap"
    LiquidityDeposit = "liquidity_deposit"
    LiquidityWithdraw = "liquidity_withdraw"
    Reward = "reward"
    Transfer = "transfer"
    GasBurn = "gas_burn"
    Unknown = "unknown"


class SubType(Enum):
    """Closed seven-value, optional, decision-driving discriminator for an Event.

    Carries ONLY discriminators that drive a downstream routing/tax/review
    decision AND are NOT already encoded by ``EventType``. Venue/chain/protocol
    provenance is deliberately excluded (recoverable from the contract address
    + the LP-autodiscovery registry). Optional: an Event may have
    ``sub_type=None`` when no discriminator applies. See §9.1 of the design
    record.
    """

    staking = "staking"
    airdrop = "airdrop"
    validator_rebate = "validator_rebate"
    spam = "spam"
    cost_gas = "cost_gas"
    internal_transfer = "internal_transfer"
    bridge = "bridge"


@dataclass(frozen=True)
class Leg:
    """One token movement within a transaction.

    The raw material ``Event`` objects are built from: an asset moved in, out, or in
    an unknown direction relative to the tracked wallet. Amounts are integer
    smallest-units (``amount_raw`` + ``amount_decimals``) -- NEVER floats -- so
    the exact on-chain wei/micro-unit value survives; decimal-overflow clamping
    is the CSV reader's responsibility (Task 7). ``token_address`` is ``None``
    for the native-chain asset leg (which has no ERC-20 contract).
    """

    asset: str
    token_address: str | None
    amount_raw: int
    amount_decimals: int
    direction: Literal["in", "out", "unknown"]
    from_address: str | None
    to_address: str | None


@dataclass(frozen=True)
class Gas:
    """The single gas fee burned by one EVM transaction.

    Gas lives at the **parent-tx level** (decision 9): there is exactly one gas
    fee per EVM transaction regardless of how many Events it contains, so it is
    a field of ``OnChainTransaction``, not of ``Event``. ``amount_raw`` is the
    integer smallest-unit fee (e.g. wei); ``decimals`` is the asset's precision.
    """

    asset: str
    amount_raw: int
    decimals: int


@dataclass(frozen=True)
class Event:
    """One economic event within a transaction (e.g. a Swap, a Reward claim).

    A single ``tx_hash`` fans out to N ``Event`` (decision 4: the split
    model) -- e.g. a tx that claims a reward and swaps it in one atomic
    transaction yields one ``Reward`` Event and one ``Swap`` Event. Each Event
    carries its ``parent_tx_hash`` and an ``event_id`` that is unique within
    that parent tx; downstream consumers key on ``(tx_hash, event_id)`` to tell
    split Events apart. ``legs`` is an immutable tuple. ``sub_type`` is
    optional (``None`` when no decision-driving discriminator applies).
    """

    event_id: str
    event_type: EventType
    sub_type: SubType | None
    legs: tuple[Leg, ...]
    parent_tx_hash: str


@dataclass(frozen=True)
class OnChainTransaction:
    """One EVM transaction: the parent container for N ``Event`` and gas.

    One ``OnChainTransaction`` per ``tx_hash``. ``gas`` is the parent-tx-level
    fee (``None`` for a purely synthetic/zero-gas row); it is NOT replicated on
    any ``Event``. ``events`` is an immutable tuple of the economic Events
    observed in this tx. ``timestamp_utc`` is timezone-aware UTC. The chain's
    contract-registry country mapping is resolved at processing time
    (``berachain_processor``) and not stored here; this object is pure movement
    + classification, no EUR cost basis (decision 12: valuation is deferred to
    taxable-event time).
    """

    tx_hash: str
    block_number: int
    timestamp_utc: datetime
    chain: str
    wallet_label: str | None
    wallet_address: str | None
    gas: Gas | None
    events: tuple[Event, ...]
