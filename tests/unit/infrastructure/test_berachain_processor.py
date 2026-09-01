"""Tests for the Berachain processor (Task 9).

RED phase: these tests pin the behaviour of the per-chain processor that
classifies a flat ``list[OnChainTxRow]`` (the CSV reader's output, Task 7)
into the native domain model ``list[OnChainTransaction]`` (Task 6) before
the production module
``src/tax_reporting/infrastructure/on_chain/berachain_processor.py`` exists.

The processor coordinates three pure (no-I/O) inputs:

- ``ContractRegistry`` (loaded + validated by
  :mod:`application.on_chain_config.load_contracts`) - address -> entry
  lookup mapping known reward distributors / DEX routers / rebate routers
  to a ``kind`` tag.
- :class:`LpAutodiscovery` (Task 8) - ``is_lp_token(addr)`` for the
  BIDIRECTIONAL-receiving-LP-token -> ``LiquidityDeposit`` classification.
- a pure leg-pattern classifier (this module).

Classification rules (leg pattern -> EventType / SubType), grounded in the
design record §9.1 and the 11 plan clauses:

+-----------------------------------+-----------------------------------+-------------------------+
| Leg pattern (within one tx_hash)  | EventType                         | SubType                 |
+-----------------------------------+-----------------------------------+-------------------------+
| BIDIRECTIONAL 1 in-asset <-> 1 out| Swap                              | None                    |
+-----------------------------------+-----------------------------------+-------------------------+
| BIDIRECTIONAL receiving LP token  | LiquidityDeposit                  | internal_transfer       |
+-----------------------------------+-----------------------------------+-------------------------+
| MULTI inflow (rewards), no outflow| Reward (one per (tx, asset))      | staking | spam          |
|                                   |                                   | | bridge (mint    |
|                                   |                                   | | from 0x0)      |
+-----------------------------------+-----------------------------------+-------------------------+
| reward-claim-then-swap (distrib + | Reward + Swap (linked by          | staking/spam (reward)   |
| DEX router both touched)          | parent_event_id)                  |                         |
+-----------------------------------+-----------------------------------+-------------------------+
| GAS_ONLY (zero native outflow,    | GasBurn                           | cost_gas                |
| only gas burned)                  |                                   |                         |
+-----------------------------------+-----------------------------------+-------------------------+
| inflow from unrecognized sender   | Reward                            | spam (+ review)         |
+-----------------------------------+-----------------------------------+-------------------------+
| direction == "unknown"            | Unknown                           | None (+ review)         |
+-----------------------------------+-----------------------------------+-------------------------+

Attacker mitigations implemented (see plan CRITICAL RULES):

- F1: ``operator_country`` validated against a closed ISO-3166 alpha-2 enum
  + a citation URL is required when ``operator_country`` is present (the
  contract registry loader enforces this; tests exercise the fall-through).
- F4: rewards from senders NOT in the contract registry -> SubType=spam +
  review (never a clean staking).
- F6: lower-case normalize ``wallet_address`` before direction equality.
- F7: run-level invariant - if >1% of a wallet's legs are
  direction=unknown, raise ``FileProcessingError`` (fail-loud).

Per AGENTS.md crypto-tests rule, tests MUST read committed synthetic data;
the committed example contract registry lives at
``resources/source/example/2025/berachain_contracts.json`` and ships EMPTY
``operator_country`` for every Berachain contract (B3).
"""

from __future__ import annotations

import logging
import re
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest

from tax_reporting.application.on_chain_config import (
    LpSnapshot,
    build_lp_snapshot,
    load_contracts,
)
from tax_reporting.domain.exceptions import FileProcessingError
from tax_reporting.domain.on_chain_config import (
    ContractEntry,
    ContractRegistry,
)
from tax_reporting.domain.on_chain_transaction import (
    Event,
    EventType,
    Gas,
    Leg,
    OnChainTransaction,
    SubType,
)
from tax_reporting.infrastructure.on_chain.berachain_processor import (
    BerachainProcessor,
)
from tax_reporting.infrastructure.on_chain.lp_autodiscovery import (
    LpAutodiscovery,
)
from tax_reporting.infrastructure.on_chain.on_chain_csv_reader import (
    OnChainTxRow,
)

# Committed example contract registry (tests MUST read committed synthetic data).
_EXAMPLE_CONTRACTS = (
    Path(__file__).resolve().parents[3]
    / "resources"
    / "source"
    / "example"
    / "2025"
    / "berachain_contracts.json"
)

# Synthetic addresses (Design Invariant #1; never real mainnet). The
# Distributor address is the one real address the design record cites; all
# others are synthetic ``0x...dead``-style.
_WALLET = "0xabcabcabcabcabcabcabcabcabcabcabcabcabca"
_WALLET_UPPER = "0xABCABCABCABCABCABCABCABCABCABCABCABCABCA"  # checksummed form
_DEX_ROUTER = "0x000000000000000000000000000000000000dead"  # in example registry
_REWARD_DISTRIBUTOR_VERIFIED = "0x000000000000000000000000000000000000beef"
_REWARD_DISTRIBUTOR_UNVERIFIED = "0x0000000000000000000000000000000000009999"
# ERC-20 mint sentinel: a Transfer event FROM the zero address is new token
# issuance (bridge deposit / airdrop mint) - no external sender exists.
_ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
_LP_TOKEN = "0x000000000000000000000000000000000000dead"  # matches example LP snapshot
# C3: synthetic second own wallet (matches the committed example registry's
# ``self_wallet`` entry; tests MUST read committed synthetic data, so the
# in-memory registry below mirrors that entry).
_SELF_WALLET = "0x0000000000000000000000000000000000002222"
# Synthetic position/staking receipt token (Plan 2026-08-22 Task 3): an
# address-keyed member of the (in-memory, synthetic) position-token registry.
# Never a real mainnet contract (Design Invariant #1).
_POSITION_TOKEN = "0x0000000000000000000000000000000000000f17"
# Synthetic registry-member RECIPIENT contract (position-NFT vault; the
# Task-5 fix gates single-leg pure outflows on recipient membership).
_REGISTRY_MEMBER_RECIPIENT = "0x0000000000000000000000000000000000000e77"
# Shape-6 follow-up (plan 2026-08-23-bera-unknown-followups, Task 1): a
# third-party buyer of an LP receipt token (counterparty mismatch), a DEX
# pair contract (LST exchange counterparty that is NOT a registry vault),
# and a generic non-vault recipient. All synthetic (Design Invariant #1).
_LP_BUYER = "0x0000000000000000000000000000000000000b09"
_DEX_PAIR = "0x0000000000000000000000000000000000000aa1"
_NONVAULT_RECIPIENT = "0x0000000000000000000000000000000000000cc3"
# Plan 2026-08-24 Task 4 (visible ERC-721 position legs): a synthetic ERC-721
# position-NFT contract (registry member, kind="position_nft"; the
# ``ALGB-POS#26874`` asset name embeds the token ID and is display-only) and
# a synthetic wrapped-native token. All synthetic (Design Invariant #1).
_POSITION_NFT = "0x0000000000000000000000000000000000000d7a"
_WBERA = "0x0000000000000000000000000000000000000bb1"
# Plan 2026-08-26 (bridge-asset registry gate): synthetic bridged-token
# contract addresses - members / non-members of the in-memory synthetic
# bridged-asset registry. Never real mainnet contracts (Design Invariant #1).
_BRIDGED_TOKEN = "0x0000000000000000000000000000000000000b77"
_BRIDGED_TOKEN_UPPER = "0x0000000000000000000000000000000000000B77"  # checksummed-style form
_BRIDGED_TOKEN_OTHER = "0x0000000000000000000000000000000000000c55"
_UNREGISTERED_MINT_TOKEN = "0x0000000000000000000000000000000000000d06"

_TS = datetime(2025, 2, 25, 13, 53, 25, tzinfo=UTC)


def _lp_snapshot() -> LpSnapshot:
    """An in-memory LpSnapshot containing the synthetic LP token."""
    return build_lp_snapshot(
        {
            "subgraph": "kodiak-v3",
            "subgraph_version": "2026-08-02.1",
            "snapshot_as_of_block": 1500000,
            "snapshot_as_of_date": "2025-12-15",
            "tokens": [
                {
                    "token_address": _LP_TOKEN,
                    "protocol": "Kodiak",
                    "type": "Pair",
                },
            ],
        },
        source="<inline-test>",
    )


def _row(  # noqa: PLR0913 - test fixture builder; many kwargs is the point
    *,
    tx_hash: str,
    asset: str,
    direction: str,
    amount_raw: int = 10**18,
    amount_decimals: int = 18,
    token_address: str | None = None,
    from_address: str = _REWARD_DISTRIBUTOR_VERIFIED,
    to_address: str = _WALLET,
    fee_asset: str | None = "BERA",
    fee_amount_raw: int | None = 21_000_002_730_000,
    wallet_address: str = _WALLET,
    block_number: int = 1_590_503,
    timestamp_utc: datetime = _TS,
    chain: str = "Berachain",
    wallet_label: str = "Ledger Berachain (BERA)",
) -> OnChainTxRow:
    """Build one ``OnChainTxRow`` with sensible synthetic defaults for tests."""
    return OnChainTxRow(
        tx_hash=tx_hash,
        block_number=block_number,
        timestamp_utc=timestamp_utc,
        chain=chain,
        from_address=from_address,
        to_address=to_address,
        asset=asset,
        token_address=token_address,
        amount_raw=amount_raw,
        amount_decimals=amount_decimals,
        direction=direction,  # type: ignore[arg-type]
        fee_asset=fee_asset,
        fee_amount_raw=fee_amount_raw,
        wallet_label=wallet_label,
        wallet_address=wallet_address,
    )


def _position_registry():  # type: ignore[no-untyped-def]
    """An in-memory PositionTokenRegistry containing the synthetic LST.

    Local import (not module level) so the RED phase of the 2026-08-22
    unknown-classifier plan fails ONLY the new tests: a module-level import
    of the not-yet-existing ``position_token_registry`` would break
    collection for every currently-green test in this file.
    """
    from tax_reporting.infrastructure.on_chain.position_token_registry import (
        build_position_token_registry,
    )

    return build_position_token_registry(
        {
            "as_of_date": "2026-08-22",
            "provenance": "<inline-test>",
            "tokens": [
                {
                    "token_address": _POSITION_TOKEN,
                    "label": "iTEST",
                    "kind": "lst",
                    "provenance": "<inline-test>",
                },
                {
                    "token_address": _REGISTRY_MEMBER_RECIPIENT,
                    "label": "TEST position vault",
                    "kind": "position_nft",
                    "provenance": "<inline-test>",
                },
                {
                    # Plan 2026-08-24 Task 4: the ERC-721 position-NFT
                    # contract itself (the mint the nfttx surface makes
                    # visible); membership is address-keyed, the
                    # ``ALGB-POS#26874`` asset name is display-only.
                    "token_address": _POSITION_NFT,
                    "label": "ALGB-POS",
                    "kind": "position_nft",
                    "provenance": "<inline-test>",
                },
            ],
        },
        source="<inline-test>",
    )


def _bridged_registry(*addresses: str):  # type: ignore[no-untyped-def]
    """An in-memory BridgedAssetRegistry whose only members are ``addresses``.

    Local import (not module level; same rationale as ``_position_registry``)
    so the RED phase of the 2026-08-26 bridge-asset-registry plan fails ONLY
    the new tests: a module-level import of the not-yet-existing
    ``bridged_asset_registry`` would break collection for every
    currently-green test in this file.

    Uses the plan's pinned JSON vocabulary: registry-level ``source``
    provenance string plus entries keyed by the LOWERCASED token address,
    each an object with an optional ``note`` (NOT C8's
    ``provenance``/``label``/``tokens`` vocabulary).
    """
    from tax_reporting.infrastructure.on_chain.bridged_asset_registry import (
        build_bridged_asset_registry,
    )

    return build_bridged_asset_registry(
        {
            "source": "<inline-test>",
            **{
                address.lower(): {"note": "synthetic bridged token"}
                for address in addresses
            },
        },
        source="<inline-test>",
    )


def _processor(  # noqa: PLR0913 - test fixture builder; many kwargs is the point
    *,
    registry_path: Path | None = None,
    registry: ContractRegistry | None = None,
    position_registry: object | None = None,
    bridged_registry: object | None = None,
) -> BerachainProcessor:
    """Build a processor bound to the example registry + an in-memory LP snapshot.

    The RPC-backed LP fallback is NOT exercised here; ``is_lp_token`` is
    served entirely by the snapshot. The mock RPC client is configured so
    that any token NOT in the snapshot returns "not LP" (empty bytecode, no
    implementation) rather than raising - the snapshot is the only
    classification signal these tests use.

    ``registry`` (an in-memory :class:`ContractRegistry`) takes precedence
    over the file-based default; the C3 self-wallet tests use it so their
    RED phase fails on CLASSIFICATION (not on the loader's kind enum, which
    accepts ``self_wallet`` only after the Task-8 implementation).
    """
    if registry is None:
        registry = load_contracts(registry_path or _EXAMPLE_CONTRACTS)
    snapshot = _lp_snapshot()
    rpc = Mock()
    # Empty bytecode + zero implementation -> is_lp_token returns Unknown
    # (not LP) for any token not in the snapshot, with no real RPC traffic.
    rpc.get_code.return_value = "0x"
    rpc.get_implementation.return_value = "0x0000000000000000000000000000000000000000"
    autod = LpAutodiscovery(snapshot=snapshot, rpc_client=rpc)
    # Optional registries are forwarded ONLY when provided: the RED phase of
    # the 2026-08-26 bridge-asset-registry plan must fail ONLY the new tests
    # (constructing BerachainProcessor with the not-yet-existing kwarg raises
    # TypeError), so pre-existing call sites keep the old signature.
    extra: dict[str, Any] = {}
    if position_registry is not None:
        extra["position_token_registry"] = position_registry
    if bridged_registry is not None:
        extra["bridged_asset_registry"] = bridged_registry
    return BerachainProcessor(
        chain="Berachain",
        contract_registry=registry,
        lp_autodiscovery=autod,
        **extra,
    )


def _self_wallet_registry() -> ContractRegistry:
    """An in-memory registry whose only entry is the synthetic self-wallet.

    Mirrors the committed example registry's ``self_wallet`` entry (C3):
    the processor READS the registry; building it via the domain types
    keeps these classification tests independent of loader-validation
    changes.
    """
    entry = ContractEntry(
        address=_SELF_WALLET,
        label="Example Self Wallet",
        kind="self_wallet",
        protocol=None,
        operator_country=None,
        citation=None,
    )
    return ContractRegistry(
        chain="Berachain",
        contracts={_SELF_WALLET: entry},
        source="<inline-test>",
    )


def _events(tx: OnChainTransaction) -> list[Event]:
    return list(tx.events)


def _review_messages(caplog: pytest.LogCaptureFixture) -> list[str]:
    """Return the rendered review-flag WARNING messages captured in ``caplog``."""
    return [
        r.getMessage()
        for r in caplog.records
        if r.levelno == logging.WARNING and "review flag" in r.getMessage()
    ]


@pytest.mark.unit
class TestBerachainProcessor:
    """Test the per-chain BERA processor's classification + tagging."""

    def test_simple_swap(self) -> None:
        # Given - a BIDIRECTIONAL tx with 1 in-asset <-> 1 out-asset (the
        # 43-tx shape). The out leg goes to the DEX router; the in leg
        # comes back from the DEX router. Gas is on the native out leg.
        rows = [
            _row(
                tx_hash="0xswap",
                asset="BERA",
                direction="out",
                token_address=None,
                from_address=_WALLET,
                to_address=_DEX_ROUTER,
                amount_raw=10**18,
            ),
            _row(
                tx_hash="0xswap",
                asset="HONEY",
                direction="in",
                token_address="0x000000000000000000000000000000000000abcd",
                from_address=_DEX_ROUTER,
                to_address=_WALLET,
                amount_raw=42 * 10**18,
                fee_asset=None,
                fee_amount_raw=None,
            ),
        ]
        processor = _processor()

        txs = processor.process(rows)

        assert len(txs) == 1
        events = _events(txs[0])
        assert len(events) == 1
        assert events[0].event_type is EventType.Swap
        assert events[0].sub_type is None
        # The Swap event carries both legs.
        assert len(events[0].legs) == 2

    def test_lp_deposit(self) -> None:
        # Given - a BIDIRECTIONAL tx receiving an LP token
        # (autodiscovery-confirmed via the snapshot). Two assets go out, the
        # LP token comes in.
        #
        # C2 citation (validation-harness plan Task 9): THIS test is the
        # ``test_lp_stake_with_snapshot_entry_classifies_liquidity_deposit``
        # clause - an in-memory snapshot entry (the ``_lp_snapshot`` helper)
        # plus a Kodiak-router stake shape classifying ``LiquidityDeposit``.
        # Cited here instead of duplicated per the plan bullet.
        rows = [
            _row(
                tx_hash="0xlpdep",
                asset="BERA",
                direction="out",
                token_address=None,
                from_address=_WALLET,
                to_address=_DEX_ROUTER,
                fee_asset="BERA",
                fee_amount_raw=21_000_002_730_000,
            ),
            _row(
                tx_hash="0xlpdep",
                asset="HONEY",
                direction="out",
                token_address="0x000000000000000000000000000000000000abcd",
                from_address=_WALLET,
                to_address=_DEX_ROUTER,
                fee_asset=None,
                fee_amount_raw=None,
            ),
            _row(
                tx_hash="0xlpdep",
                asset="UNI-V2",
                direction="in",
                token_address=_LP_TOKEN,  # snapshot-confirmed LP token
                from_address=_DEX_ROUTER,
                to_address=_WALLET,
                amount_raw=5 * 10**18,
                fee_asset=None,
                fee_amount_raw=None,
            ),
        ]
        processor = _processor()

        txs = processor.process(rows)

        assert len(txs) == 1
        events = _events(txs[0])
        assert len(events) == 1
        assert events[0].event_type is EventType.LiquidityDeposit
        assert events[0].sub_type is SubType.internal_transfer

    def test_multi_token_reward_claim(self) -> None:
        # Given - the BM multi-token reward-claim shape: many in-legs (14
        # distinct reward assets here, fewer for the test), NO outflow. Each
        # distinct asset must produce one Reward Event whose amount is the
        # SUM of that asset's in-legs.
        assets = ["BGT", "HONEY", "WBERA", "iBGT"]
        rows: list[OnChainTxRow] = []
        # Two in-legs of BGT (must sum into ONE Reward Event); one each for
        # the rest.
        rows.append(
            _row(
                tx_hash="0xreward",
                asset="BGT",
                direction="in",
                from_address=_REWARD_DISTRIBUTOR_VERIFIED,
                to_address=_WALLET,
                amount_raw=10**18,
                fee_asset=None,
                fee_amount_raw=None,
            )
        )
        rows.append(
            _row(
                tx_hash="0xreward",
                asset="BGT",
                direction="in",
                from_address=_REWARD_DISTRIBUTOR_VERIFIED,
                to_address=_WALLET,
                amount_raw=2 * 10**18,
                fee_asset=None,
                fee_amount_raw=None,
            )
        )
        for asset in assets[1:]:
            rows.append(
                _row(
                    tx_hash="0xreward",
                    asset=asset,
                    direction="in",
                    from_address=_REWARD_DISTRIBUTOR_VERIFIED,
                    to_address=_WALLET,
                    amount_raw=3 * 10**18,
                    fee_asset=None,
                    fee_amount_raw=None,
                )
            )
        processor = _processor()

        txs = processor.process(rows)

        assert len(txs) == 1
        events = _events(txs[0])
        # 4 distinct reward assets -> 4 Reward Events.
        assert len(events) == 4
        assert all(e.event_type is EventType.Reward for e in events)
        # One Event per asset (grouping key).
        event_assets = {
            e.legs[0].asset if e.legs else None for e in events
        }
        assert event_assets == set(assets)
        # The BGT Event's amount is the SUM of its two in-legs (3 * 10**18).
        bgt_event = next(e for e in events if e.legs[0].asset == "BGT")
        assert bgt_event.legs[0].amount_raw == 3 * 10**18

    def test_gas_only_tx_emits_gasburn(self) -> None:
        # Given - a GAS_ONLY tx: zero-value native outflow, only gas burned.
        # The single leg is a zero-amount BERA outflow; the gas is the only
        # economic movement.
        rows = [
            _row(
                tx_hash="0xgasonly",
                asset="BERA",
                direction="out",
                token_address=None,
                from_address=_WALLET,
                to_address="0x0000000000000000000000000000000000000001",
                amount_raw=0,
                fee_asset="BERA",
                fee_amount_raw=21_000_002_730_000,
            ),
        ]
        processor = _processor()

        txs = processor.process(rows)

        assert len(txs) == 1
        events = _events(txs[0])
        assert len(events) == 1
        assert events[0].event_type is EventType.GasBurn
        # Gas is surfaced on the parent tx so it is not lost.
        assert txs[0].gas is not None
        assert txs[0].gas.asset == "BERA"

    def test_distributor_claim_with_zero_value_gas_carrier_classifies_reward(self) -> None:
        # C1 (validation-harness plan Task 7; design record Q6): a
        # distributor/vault claim carries a zero-value NATIVE out-leg - the
        # gas carrier. The actual gas rides the parent tx (_lift_gas); the
        # carrier is NOT an economic leg, so the tx classifies by its
        # economic legs alone: a pure-inflow Reward claim (staking), NOT the
        # generic Swap the pre-fix in/out partition misrouted ~110 real
        # claims to.
        rows = [
            _row(
                tx_hash="0xclaimcarrier",
                asset="BGT",
                direction="in",
                token_address="0x000000000000000000000000000000000000bgt0",
                from_address=_REWARD_DISTRIBUTOR_VERIFIED,
                to_address=_WALLET,
                amount_raw=10**18,
                fee_asset=None,
                fee_amount_raw=None,
            ),
            # The gas carrier: zero-value native outflow (tx gas nonzero).
            _row(
                tx_hash="0xclaimcarrier",
                asset="BERA",
                direction="out",
                token_address=None,
                from_address=_WALLET,
                to_address=_REWARD_DISTRIBUTOR_VERIFIED,
                amount_raw=0,
                fee_asset="BERA",
                fee_amount_raw=21_000_002_730_000,
            ),
        ]
        processor = _processor()

        txs = processor.process(rows)

        assert len(txs) == 1
        events = _events(txs[0])
        # A single Reward Event (staking), not a Swap.
        assert len(events) == 1
        assert events[0].event_type is EventType.Reward
        assert events[0].sub_type is SubType.staking
        # The Reward carries only the economic BGT in-leg (carrier excluded).
        assert len(events[0].legs) == 1
        assert events[0].legs[0].asset == "BGT"
        # The gas survives at the parent-tx level (the carrier's whole point).
        assert txs[0].gas is not None
        assert txs[0].gas.asset == "BERA"

    def test_swap_with_zero_value_native_leg_excludes_carrier(self) -> None:
        # C1: a REAL swap carrying an extra zero-value native out-leg. The
        # swap survives, but the carrier leg is excluded from the Event's
        # leg list (it is not an economic movement; the gas is on the tx).
        rows = [
            _row(
                tx_hash="0xswapcarrier",
                asset="HONEY",
                direction="in",
                token_address="0x000000000000000000000000000000000000abcd",
                from_address=_DEX_ROUTER,
                to_address=_WALLET,
                amount_raw=42 * 10**18,
                fee_asset=None,
                fee_amount_raw=None,
            ),
            _row(
                tx_hash="0xswapcarrier",
                asset="BERA",
                direction="out",
                token_address=None,
                from_address=_WALLET,
                to_address=_DEX_ROUTER,
                amount_raw=10**18,
                fee_asset="BERA",
                fee_amount_raw=21_000_002_730_000,
            ),
            # The gas carrier: zero-value native outflow riding the swap.
            _row(
                tx_hash="0xswapcarrier",
                asset="BERA",
                direction="out",
                token_address=None,
                from_address=_WALLET,
                to_address=_DEX_ROUTER,
                amount_raw=0,
                fee_asset=None,
                fee_amount_raw=None,
            ),
        ]
        processor = _processor()

        txs = processor.process(rows)

        assert len(txs) == 1
        events = _events(txs[0])
        assert len(events) == 1
        assert events[0].event_type is EventType.Swap
        # The Swap carries ONLY the two economic legs - the carrier is gone.
        assert len(events[0].legs) == 2
        assert not any(
            leg.direction == "out"
            and leg.token_address is None
            and leg.amount_raw == 0
            for leg in events[0].legs
        )

    def test_gas_only_still_gasburn(self) -> None:
        # C1 regression guard on the GAS_ONLY branch: a gas-only tx's single
        # leg IS the carrier shape, and the GasBurn Event must keep carrying
        # it. An over-broad exclusion that empties _gasburn_event's leg list
        # would render blank TxSrc/TxDest at the adapter (addr_leg), so the
        # leg payload is asserted explicitly.
        rows = [
            _row(
                tx_hash="0xgasonlyguard",
                asset="BERA",
                direction="out",
                token_address=None,
                from_address=_WALLET,
                to_address="0x0000000000000000000000000000000000000001",
                amount_raw=0,
                fee_asset="BERA",
                fee_amount_raw=21_000_002_730_000,
            ),
        ]
        processor = _processor()

        txs = processor.process(rows)

        assert len(txs) == 1
        events = _events(txs[0])
        assert len(events) == 1
        assert events[0].event_type is EventType.GasBurn
        assert events[0].sub_type is SubType.cost_gas
        # The Event STILL carries the (unfiltered) out-leg.
        assert len(events[0].legs) == 1
        assert events[0].legs[0].direction == "out"
        assert events[0].legs[0].token_address is None
        assert events[0].legs[0].amount_raw == 0

    def test_zero_value_token_leg_not_excluded(self) -> None:
        # C1 narrow rule (negative): only NATIVE zero-value legs are gas
        # carriers. A zero-value TOKEN leg (token_address set) stays in the
        # partition and in the Swap's legs.
        rows = [
            _row(
                tx_hash="0xtokzero",
                asset="HONEY",
                direction="in",
                token_address="0x000000000000000000000000000000000000abcd",
                from_address=_DEX_ROUTER,
                to_address=_WALLET,
                amount_raw=42 * 10**18,
                fee_asset=None,
                fee_amount_raw=None,
            ),
            _row(
                tx_hash="0xtokzero",
                asset="BERA",
                direction="out",
                token_address=None,
                from_address=_WALLET,
                to_address=_DEX_ROUTER,
                amount_raw=10**18,
                fee_asset="BERA",
                fee_amount_raw=21_000_002_730_000,
            ),
            # A zero-value TOKEN out-leg - NOT a carrier; it must remain.
            _row(
                tx_hash="0xtokzero",
                asset="HONEY",
                direction="out",
                token_address="0x000000000000000000000000000000000000abcd",
                from_address=_WALLET,
                to_address=_DEX_ROUTER,
                amount_raw=0,
                fee_asset=None,
                fee_amount_raw=None,
            ),
        ]
        processor = _processor()

        txs = processor.process(rows)

        assert len(txs) == 1
        events = _events(txs[0])
        assert len(events) == 1
        assert events[0].event_type is EventType.Swap
        # All three legs carried - the zero-value TOKEN leg REMAINS.
        assert len(events[0].legs) == 3
        zero_token_legs = [
            leg
            for leg in events[0].legs
            if leg.token_address is not None and leg.amount_raw == 0
        ]
        assert len(zero_token_legs) == 1

    def test_reward_then_swap_split_respects_carrier_exclusion(self) -> None:
        # C4's suspected shape (the multi-Event split case): a claim+swap tx
        # (distributor in-leg + router swap legs) carrying a zero-value
        # native gas-carrier out-leg. The split fires (distributor AND DEX
        # router both touched) but the carrier appears in NEITHER Event: not
        # in the Reward's legs, not in the Swap's legs.
        rows = [
            # Reward inflow from the verified distributor.
            _row(
                tx_hash="0xsplitcarrier",
                asset="BGT",
                direction="in",
                token_address="0x000000000000000000000000000000000000bgt0",
                from_address=_REWARD_DISTRIBUTOR_VERIFIED,
                to_address=_WALLET,
                amount_raw=10**18,
                fee_asset="BERA",
                fee_amount_raw=21_000_002_730_000,
            ),
            # Swap: BGT out to the DEX router.
            _row(
                tx_hash="0xsplitcarrier",
                asset="BGT",
                direction="out",
                token_address="0x000000000000000000000000000000000000bgt0",
                from_address=_WALLET,
                to_address=_DEX_ROUTER,
                amount_raw=10**18,
                fee_asset=None,
                fee_amount_raw=None,
            ),
            # Swap: HONEY in from the DEX router.
            _row(
                tx_hash="0xsplitcarrier",
                asset="HONEY",
                direction="in",
                token_address="0x000000000000000000000000000000000000abcd",
                from_address=_DEX_ROUTER,
                to_address=_WALLET,
                amount_raw=5 * 10**18,
                fee_asset=None,
                fee_amount_raw=None,
            ),
            # The gas carrier: zero-value native outflow.
            _row(
                tx_hash="0xsplitcarrier",
                asset="BERA",
                direction="out",
                token_address=None,
                from_address=_WALLET,
                to_address=_DEX_ROUTER,
                amount_raw=0,
                fee_asset=None,
                fee_amount_raw=None,
            ),
        ]
        processor = _processor()

        txs = processor.process(rows)

        assert len(txs) == 1
        events = _events(txs[0])
        assert len(events) == 2
        by_type = {e.event_type: e for e in events}
        assert set(by_type) == {EventType.Reward, EventType.Swap}
        reward_event = by_type[EventType.Reward]
        swap_event = by_type[EventType.Swap]
        # Reward: only the distributor's BGT in-leg; staking.
        assert reward_event.sub_type is SubType.staking
        assert len(reward_event.legs) == 1
        assert reward_event.legs[0].asset == "BGT"
        # Swap: the router exchange legs ONLY (BGT out + HONEY in).
        assert len(swap_event.legs) == 2
        # The carrier leg is in NEITHER Event's legs.
        for event in events:
            assert not any(
                leg.direction == "out"
                and leg.token_address is None
                and leg.amount_raw == 0
                for leg in event.legs
            )

    def test_reward_claim_then_swap_splits(self) -> None:
        # Given - a tx that claims a reward AND swaps it in one atomic
        # transaction: both a reward-distributor AND a DEX-router are
        # touched. Expects TWO Events (Reward + Swap) linked by
        # parent_event_id.
        rows = [
            # Reward inflow from the verified distributor.
            _row(
                tx_hash="0xrewswap",
                asset="BGT",
                direction="in",
                token_address="0x000000000000000000000000000000000000bgt0",
                from_address=_REWARD_DISTRIBUTOR_VERIFIED,
                to_address=_WALLET,
                amount_raw=10**18,
                fee_asset="BERA",
                fee_amount_raw=21_000_002_730_000,
            ),
            # Swap: BGT out to the DEX router...
            _row(
                tx_hash="0xrewswap",
                asset="BGT",
                direction="out",
                token_address="0x000000000000000000000000000000000000bgt0",
                from_address=_WALLET,
                to_address=_DEX_ROUTER,
                amount_raw=10**18,
                fee_asset=None,
                fee_amount_raw=None,
            ),
            # ...HONEY in from the DEX router.
            _row(
                tx_hash="0xrewswap",
                asset="HONEY",
                direction="in",
                token_address="0x000000000000000000000000000000000000abcd",
                from_address=_DEX_ROUTER,
                to_address=_WALLET,
                amount_raw=5 * 10**18,
                fee_asset=None,
                fee_amount_raw=None,
            ),
        ]
        processor = _processor()

        txs = processor.process(rows)

        assert len(txs) == 1
        events = _events(txs[0])
        types = {e.event_type for e in events}
        assert types == {EventType.Reward, EventType.Swap}
        # Both Events share the parent tx_hash (linked by parent_event_id,
        # which is the parent tx_hash itself per the domain model).
        assert all(e.parent_tx_hash == "0xrewswap" for e in events)
        # Each Event has a unique event_id within the tx.
        ids = {e.event_id for e in events}
        assert len(ids) == 2

    def test_gas_attaches_to_parent_tx(self) -> None:
        # Given - any tx with gas, expects OnChainTransaction.gas populated
        # and NO Event carries gas.
        rows = [
            _row(
                tx_hash="0xgastest",
                asset="BERA",
                direction="out",
                token_address=None,
                from_address=_WALLET,
                to_address=_DEX_ROUTER,
                fee_asset="BERA",
                fee_amount_raw=21_000_002_730_000,
            ),
            _row(
                tx_hash="0xgastest",
                asset="HONEY",
                direction="in",
                token_address="0x000000000000000000000000000000000000abcd",
                from_address=_DEX_ROUTER,
                to_address=_WALLET,
                fee_asset=None,
                fee_amount_raw=None,
            ),
        ]
        processor = _processor()

        txs = processor.process(rows)

        assert len(txs) == 1
        tx = txs[0]
        assert isinstance(tx.gas, Gas)
        assert tx.gas.asset == "BERA"
        assert tx.gas.amount_raw == 21_000_002_730_000
        # Gas attaches to the parent tx, NEVER to any Event (the Event type
        # has no gas field by design; this asserts the negative by pinning the
        # exact dataclass field set, so a future added ``gas`` field fails
        # loudly instead of being accommodated by a hasattr tautology).
        import dataclasses

        from tax_reporting.domain.on_chain_transaction import Event

        event_fields = {f.name for f in dataclasses.fields(Event)}
        assert "gas" not in event_fields
        assert {
            "event_id",
            "event_type",
            "sub_type",
            "legs",
            "parent_tx_hash",
            # Review r6 F1: the persisted review reason (None when unflagged).
            "review_reason",
        } == event_fields
        for event in _events(tx):
            assert "gas" not in {f.name for f in dataclasses.fields(event)}

    def test_spam_airdrop_tagged_not_dropped(self, caplog) -> None:
        # Given - an inflow from an UNRECOGNIZED sender (the
        # WWW.BERA777.XYZ case). Expects Event(Reward, SubType=spam) + a
        # review flag, NEVER dropped (Koinly dropped it; the native model
        # does not).
        rows = [
            _row(
                tx_hash="0xspam",
                asset="BERA777",
                direction="in",
                token_address="0x000000000000000000000000000000000007777",
                from_address=_REWARD_DISTRIBUTOR_UNVERIFIED,  # NOT in registry
                to_address=_WALLET,
                amount_raw=10**18,
                fee_asset=None,
                fee_amount_raw=None,
            ),
        ]
        processor = _processor()

        with caplog.at_level(logging.WARNING, logger=BerachainProcessor.__module__):
            txs = processor.process(rows)

        # NEVER dropped: exactly one tx with one Event.
        assert len(txs) == 1
        events = _events(txs[0])
        assert len(events) == 1
        assert events[0].event_type is EventType.Reward
        assert events[0].sub_type is SubType.spam
        # The review surface is observable in the run's WARNING log (the Event
        # model has no review field, so the WARNING is the discriminable signal
        # a regression that drops review=True would break).
        review_msgs = _review_messages(caplog)
        assert review_msgs, "expected a review-flag WARNING for the spam Event"

    def test_unknown_direction_does_not_misclassify(self, caplog) -> None:
        # Given - a leg with direction=unknown. Expects WARNING + an
        # Event(Unknown) + a review flag (the processor must NOT guess).
        #
        # The run-level invariant (>1% unknown -> FileProcessingError) and
        # the per-tx Unknown Event coexist: a SINGLE stray unknown leg (well
        # under 1% of the wallet's legs) emits an Unknown Event; only a
        # wallet-wide >1% rate raises. So this test includes many
        # known-direction legs to keep the unknown leg a tiny minority.
        rows: list[OnChainTxRow] = []
        # 200 known-direction legs (100 simple swaps, 2 legs each) so the
        # single unknown leg is 1/201 ~= 0.5% (under the 1% threshold).
        for i in range(100):
            rows.append(
                _row(
                    tx_hash=f"0xknown{i}",
                    asset="BERA",
                    direction="out",
                    from_address=_WALLET,
                    to_address=_DEX_ROUTER,
                )
            )
            rows.append(
                _row(
                    tx_hash=f"0xknown{i}",
                    asset="HONEY",
                    direction="in",
                    token_address="0x000000000000000000000000000000000000abcd",
                    from_address=_DEX_ROUTER,
                    to_address=_WALLET,
                    fee_asset=None,
                    fee_amount_raw=None,
                )
            )
        # The one unknown-direction leg (its own tx).
        rows.append(
            _row(
                tx_hash="0xunknown",
                asset="MYSTERY",
                direction="unknown",
                token_address="0x000000000000000000000000000000000000abcd",
                from_address=_DEX_ROUTER,
                to_address=_WALLET,
                fee_asset=None,
                fee_amount_raw=None,
            )
        )
        processor = _processor()

        with caplog.at_level(logging.WARNING):
            txs = processor.process(rows)

        # The unknown-leg tx exists and was NOT misclassified.
        unk_txs = [tx for tx in txs if tx.tx_hash == "0xunknown"]
        assert len(unk_txs) == 1
        events = _events(unk_txs[0])
        assert len(events) == 1
        assert events[0].event_type is EventType.Unknown
        # The processor warned (no silent misclassification).
        assert any("unknown" in rec.message.lower() for rec in caplog.records)

    def test_every_flagged_event_persists_actionable_review_reason(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Review r7 F1: EVERY Event built with review=True must persist a
        # specific actionable ``review_reason`` (PT-C-030 family) so the
        # merged-TH Description cell keeps the review indicator on the
        # persisted surface. The r6 tests pinned only the reason-bearing
        # shapes (provenance mint, shape-6 mismatch); this property test
        # covers the flagged-without-reason sites: the matched-no-pattern
        # Unknown fallback, the unknown-direction per-leg fallback, the
        # ungated shape-11 multi-leg deposit, and spam rewards.
        rows: list[OnChainTxRow] = []
        # 200 known-direction swap legs (100 simple swaps) so the single
        # unknown-direction leg stays far under the run-level >1% unknown
        # guard (F7 fail-loud).
        for i in range(100):
            rows.append(
                _row(
                    tx_hash=f"0xpad{i}",
                    asset="BERA",
                    direction="out",
                    from_address=_WALLET,
                    to_address=_DEX_ROUTER,
                )
            )
            rows.append(
                _row(
                    tx_hash=f"0xpad{i}",
                    asset="HONEY",
                    direction="in",
                    token_address="0x000000000000000000000000000000000000abcd",
                    from_address=_DEX_ROUTER,
                    to_address=_WALLET,
                    fee_asset=None,
                    fee_amount_raw=None,
                )
            )
        # Spam reward (unverified sender, F4).
        rows.append(
            _row(
                tx_hash="0xspam",
                asset="BERA777",
                direction="in",
                token_address="0x000000000000000000000000000000000007777",
                from_address=_REWARD_DISTRIBUTOR_UNVERIFIED,
                to_address=_WALLET,
                fee_asset=None,
                fee_amount_raw=None,
            )
        )
        # Matched-no-pattern fallback: a single non-member economic outflow
        # with no member signal anywhere (no registry loaded).
        rows.append(
            _row(
                tx_hash="0xtermfb",
                asset="HONEY",
                direction="out",
                token_address="0x000000000000000000000000000000000000abcd",
                from_address=_WALLET,
                to_address=_DEX_ROUTER,
                amount_raw=10**18,
                fee_asset=None,
                fee_amount_raw=None,
            )
        )
        # Ungated shape-11 multi-leg deposit: two non-member economic
        # out-legs, no registry-member recipient.
        for asset, token in (
            ("WETH", "0x000000000000000000000000000000000000aaaa"),
            ("BUSD", "0x000000000000000000000000000000000000bbbb"),
        ):
            rows.append(
                _row(
                    tx_hash="0xungated",
                    asset=asset,
                    direction="out",
                    token_address=token,
                    from_address=_WALLET,
                    to_address=_DEX_ROUTER,
                    amount_raw=10**18,
                    fee_asset=None,
                    fee_amount_raw=None,
                )
            )
        # Unknown-direction leg (its own tx).
        rows.append(
            _row(
                tx_hash="0xunknown",
                asset="MYSTERY",
                direction="unknown",
                token_address="0x000000000000000000000000000000000000abcd",
                from_address=_DEX_ROUTER,
                to_address=_WALLET,
                fee_asset=None,
                fee_amount_raw=None,
            )
        )
        processor = _processor()

        with caplog.at_level(logging.WARNING, logger=BerachainProcessor.__module__):
            txs = processor.process(rows)

        events = [event for tx in txs for event in tx.events]
        by_tx: dict[str, list[Event]] = {}
        for event in events:
            by_tx.setdefault(event.parent_tx_hash, []).append(event)
        # Per-shape: each newly-reasoned flagged Event carries a specific,
        # actionable reason (non-empty, names what to verify).
        expected: dict[str, EventType] = {
            "0xspam": EventType.Reward,
            "0xtermfb": EventType.Unknown,
            "0xungated": EventType.LiquidityDeposit,
            "0xunknown": EventType.Unknown,
        }
        for tx_hash, event_type in expected.items():
            matching = [e for e in by_tx[tx_hash] if e.event_type is event_type]
            assert matching, f"expected an {event_type.name} Event for {tx_hash}"
            for event in matching:
                assert event.review_reason, f"{tx_hash}: flagged Event has no review_reason"
                assert "verify" in event.review_reason, (
                    f"{tx_hash}: review_reason is not actionable: {event.review_reason!r}"
                )
        # Property: every review-flag WARNING corresponds to an Event with a
        # non-empty review_reason (no flagged Event may persist None).
        flag_pattern = re.compile(r"tx_hash=(?P<tx>\S+) emitting Event\((?P<type>\w+),")
        flagged: set[tuple[str, str]] = set()
        for record in caplog.records:
            message = record.getMessage()
            if record.levelno == logging.WARNING and "review flag" in message:
                match = flag_pattern.search(message)
                assert match is not None, f"unparseable review WARNING: {message!r}"
                flagged.add((match.group("tx"), match.group("type")))
        assert flagged, "expected review-flag WARNINGs for the fixture shapes"
        missing = [
            event
            for event in events
            if (event.parent_tx_hash, event.event_type.name) in flagged
            and not event.review_reason
        ]
        assert not missing, f"flagged Events persisted without a review_reason: {missing}"

    def test_reward_distributor_country_falls_through_to_chain(self) -> None:
        # Given - a BGT reward from the verified Distributor
        # 0xd2f19a79... (in the example registry). Expects NO contract-level
        # operator_country is set on the produced Event (B3: Berachain
        # contracts ship EMPTY operator_country and fall through to the
        # chain-level VG mapping, which the processor does NOT itself
        # resolve - that is operator_origin.py's job).
        rows = [
            _row(
                tx_hash="0xbgt",
                asset="BGT",
                direction="in",
                token_address="0x000000000000000000000000000000000000bgt0",
                # The REAL Distributor address (design-record cited).
                from_address="0xd2f19a79b026fb636a7c300bf5947df113940761",
                to_address=_WALLET,
                amount_raw=10**18,
                fee_asset=None,
                fee_amount_raw=None,
            ),
        ]
        processor = _processor()

        txs = processor.process(rows)

        assert len(txs) == 1
        events = _events(txs[0])
        assert len(events) == 1
        assert events[0].event_type is EventType.Reward
        # B3: the contract registry has NO operator_country for this
        # Distributor (verified by the example file). The processor must NOT
        # invent one - operator_country resolution is downstream
        # (operator_origin.py). So the Event carries no country tag of any
        # kind (it has only EventType/SubType/legs/ids by design). The
        # assertion is structural: there is no country field to set, and the
        # registry entry the processor consulted has operator_country=None.
        registry = processor.contract_registry
        entry = registry.get("0xd2f19a79b026fb636a7c300bf5947df113940761")
        assert entry is not None
        assert entry.operator_country is None

    def test_unverified_sender_reward_is_spam(self, caplog) -> None:
        # Given - a Reward from a sender NOT in the contract registry
        # (Attacker F4 mitigation). Expects SubType=spam + a review flag,
        # NEVER a clean staking Reward.
        rows = [
            _row(
                tx_hash="0xunverified",
                asset="HONEY",
                direction="in",
                token_address="0x000000000000000000000000000000000000abcd",
                from_address=_REWARD_DISTRIBUTOR_UNVERIFIED,  # NOT in registry
                to_address=_WALLET,
                amount_raw=10**18,
                fee_asset=None,
                fee_amount_raw=None,
            ),
        ]
        processor = _processor()

        with caplog.at_level(logging.WARNING, logger=BerachainProcessor.__module__):
            txs = processor.process(rows)

        assert len(txs) == 1
        events = _events(txs[0])
        assert len(events) == 1
        assert events[0].event_type is EventType.Reward
        # F4: unverified -> spam + review, never clean staking.
        assert events[0].sub_type is SubType.spam
        # The review surface is observable in the run's WARNING log; this is the
        # discriminable signal since Event has no review field.
        review_msgs = _review_messages(caplog)
        assert review_msgs, "expected a review-flag WARNING for the spam Event"

    def test_pure_inflow_mint_from_zero_is_bridge_not_spam(self) -> None:
        # Bridge issuance shape (real 2025 data: the wallet's 3 WBTC mints -
        # bridged BTC arriving on Berachain): the only in-leg is MINTED from
        # the zero address, so there is NO external sender and the F4
        # unverified-sender premise does not apply. Must classify
        # SubType=bridge with a review reason naming the possible
        # bridge/CEX transfer-in and the acquisition-basis verification
        # (user direction 2026-08-26), NOT spam.
        rows = [
            _row(
                tx_hash="0xbridgemint",
                asset="WBTC",
                direction="in",
                token_address="0x0000000000000000000000000000000000000b7c",
                from_address=_ZERO_ADDRESS,
                to_address=_WALLET,
                amount_raw=10**8,
                amount_decimals=8,
                fee_asset=None,
                fee_amount_raw=None,
            ),
        ]
        # r1-F1 retrofit (plan 2026-08-26 Task 2): the minted token is
        # registered in the synthetic bridged-asset registry so this
        # characterization keeps expecting bridge under the registry gate.
        processor = _processor(
            bridged_registry=_bridged_registry("0x0000000000000000000000000000000000000b7c")
        )

        txs = processor.process(rows)

        assert len(txs) == 1
        events = _events(txs[0])
        assert len(events) == 1
        assert events[0].event_type is EventType.Reward
        assert events[0].sub_type is SubType.bridge
        assert events[0].sub_type is not SubType.spam
        reason = events[0].review_reason
        assert reason is not None, "a bridge mint must stay review-flagged"
        assert "bridge" in reason.lower()
        assert "zero address" in reason.lower()
        assert "basis" in reason.lower()

    def test_mint_from_zero_with_gas_carrier_still_bridge(self) -> None:
        # The same bridge mint carrying the C1 zero-value native gas-carrier
        # out-leg: the carrier is excluded from the in/out partition, so the
        # tx stays a PURE inflow and must still classify Reward/bridge.
        rows = [
            _row(
                tx_hash="0xbridgegas",
                asset="WBERA",
                direction="in",
                token_address="0x000000000000000000000000000000000000be17",
                from_address=_ZERO_ADDRESS,
                to_address=_WALLET,
                amount_raw=10**18,
                fee_asset=None,
                fee_amount_raw=None,
            ),
            _row(
                tx_hash="0xbridgegas",
                asset="BERA",
                direction="out",
                token_address=None,
                from_address=_WALLET,
                to_address="0x0000000000000000000000000000000000000router",
                amount_raw=0,
                fee_asset="BERA",
                fee_amount_raw=21_000_002_730_000,
            ),
        ]
        # r1-F1 retrofit (plan 2026-08-26 Task 2): registered WBERA mint.
        processor = _processor(
            bridged_registry=_bridged_registry("0x000000000000000000000000000000000000be17")
        )

        txs = processor.process(rows)

        events = _events(txs[0])
        assert len(events) == 1
        assert events[0].event_type is EventType.Reward
        assert events[0].sub_type is SubType.bridge

    def test_mixed_mint_and_sender_inflow_classifies_per_asset(self) -> None:
        # Multi-token pure inflow where ONE asset is minted from the zero
        # address (bridge) and ONE arrives from an unregistered sender: the
        # per-(tx, asset) grouping keeps the discriminators independent -
        # mint asset -> bridge, sender asset -> spam.
        rows = [
            _row(
                tx_hash="0xmixed",
                asset="WBTC",
                direction="in",
                token_address="0x0000000000000000000000000000000000000b7c",
                from_address=_ZERO_ADDRESS,
                to_address=_WALLET,
                amount_raw=10**8,
                amount_decimals=8,
                fee_asset=None,
                fee_amount_raw=None,
            ),
            _row(
                tx_hash="0xmixed",
                asset="HONEY",
                direction="in",
                token_address="0x000000000000000000000000000000000000abcd",
                from_address=_REWARD_DISTRIBUTOR_UNVERIFIED,
                to_address=_WALLET,
                amount_raw=10**18,
                fee_asset=None,
                fee_amount_raw=None,
            ),
        ]
        # r1-F1 retrofit (plan 2026-08-26 Task 2): the WBTC mint leg is
        # registered (the HONEY sender leg needs no registration - it
        # classifies via the sender-verification branch).
        processor = _processor(
            bridged_registry=_bridged_registry("0x0000000000000000000000000000000000000b7c")
        )

        txs = processor.process(rows)

        events = _events(txs[0])
        by_asset = {
            next(leg.asset for leg in event.legs if leg.direction == "in"): event
            for event in events
        }
        assert by_asset["WBTC"].sub_type is SubType.bridge
        assert by_asset["HONEY"].sub_type is SubType.spam

    def test_reward_then_swap_routes_mint_leg_to_bridge_reward(self) -> None:
        # Review r1 F3: inside the reward-claim-then-swap split, a
        # zero-address mint in-leg must route to the REWARD side (classified
        # bridge + review by _reward_sub_type), never be absorbed into the
        # Swap legs.
        rows = [
            _row(
                tx_hash="0xsplitmint",
                asset="BGT",
                direction="in",
                from_address=_REWARD_DISTRIBUTOR_VERIFIED,
                to_address=_WALLET,
                fee_asset=None,
                fee_amount_raw=None,
            ),
            _row(
                tx_hash="0xsplitmint",
                asset="WBTC",
                direction="in",
                token_address="0x0000000000000000000000000000000000000b7c",
                from_address=_ZERO_ADDRESS,
                to_address=_WALLET,
                amount_raw=10**8,
                amount_decimals=8,
                fee_asset=None,
                fee_amount_raw=None,
            ),
            _row(
                tx_hash="0xsplitmint",
                asset="BGT",
                direction="out",
                token_address="0x0000000000000000000000000000000000000bgt",
                from_address=_WALLET,
                to_address=_DEX_ROUTER,
                fee_asset=None,
                fee_amount_raw=None,
            ),
            _row(
                tx_hash="0xsplitmint",
                asset="HONEY",
                direction="in",
                token_address="0x0000000000000000000000000000000000000hny",
                from_address=_DEX_ROUTER,
                to_address=_WALLET,
                fee_asset=None,
                fee_amount_raw=None,
            ),
        ]
        # r1-F1 retrofit (plan 2026-08-26 Task 2): the split's WBTC mint
        # in-leg is registered so the Reward half stays bridge.
        processor = _processor(
            bridged_registry=_bridged_registry("0x0000000000000000000000000000000000000b7c")
        )

        txs = processor.process(rows)

        events = _events(txs[0])
        by_type = {}
        for event in events:
            for leg in event.legs:
                if leg.direction == "in":
                    by_type[leg.asset] = (event.event_type, event.sub_type)
        assert by_type["BGT"] == (EventType.Reward, SubType.staking)
        assert by_type["WBTC"] == (EventType.Reward, SubType.bridge)
        assert by_type["HONEY"] == (EventType.Swap, None)
        bridge_event = next(e for e in events if e.sub_type is SubType.bridge)
        assert bridge_event.review_reason is not None

    def _split_gate_rows(self) -> list[OnChainTxRow]:
        """A reward-claim-then-swap tx whose reward in-leg is a zero-address
        mint of ``_BRIDGED_TOKEN`` (plan 2026-08-26 Task 1; the split routing
        also feeds ``_reward_sub_type``, so the registry gate applies there -
        review r1 F3: the split path is a SECOND gate entry)."""
        return [
            _row(
                tx_hash="0xsplitgate",
                asset="BGT",
                direction="in",
                from_address=_REWARD_DISTRIBUTOR_VERIFIED,
                to_address=_WALLET,
                fee_asset=None,
                fee_amount_raw=None,
            ),
            _row(
                tx_hash="0xsplitgate",
                asset="WBTC",
                direction="in",
                token_address=_BRIDGED_TOKEN,
                from_address=_ZERO_ADDRESS,
                to_address=_WALLET,
                amount_raw=10**8,
                amount_decimals=8,
                fee_asset=None,
                fee_amount_raw=None,
            ),
            _row(
                tx_hash="0xsplitgate",
                asset="BGT",
                direction="out",
                token_address="0x0000000000000000000000000000000000000bgt",
                from_address=_WALLET,
                to_address=_DEX_ROUTER,
                fee_asset=None,
                fee_amount_raw=None,
            ),
            _row(
                tx_hash="0xsplitgate",
                asset="HONEY",
                direction="in",
                token_address="0x0000000000000000000000000000000000000hny",
                from_address=_DEX_ROUTER,
                to_address=_WALLET,
                fee_asset=None,
                fee_amount_raw=None,
            ),
        ]

    def test_reward_then_swap_split_mint_leg_registry_gate(self) -> None:
        # Plan 2026-08-26 Task 1 (review r1 F3): inside the split, a
        # REGISTERED zero-address mint in-leg stays Reward/bridge, while an
        # UNREGISTERED one flips to Reward/spam + review; the verified
        # distributor Reward half and the Swap half are unchanged either way.
        rows = self._split_gate_rows()

        def _by_in_asset(events: list[Event]) -> dict[str, tuple[EventType, SubType | None]]:
            routed: dict[str, tuple[EventType, SubType | None]] = {}
            for event in events:
                for leg in event.legs:
                    if leg.direction == "in":
                        routed[leg.asset] = (event.event_type, event.sub_type)
            return routed

        registered = _by_in_asset(
            _events(
                _processor(bridged_registry=_bridged_registry(_BRIDGED_TOKEN)).process(rows)[0]
            )
        )
        assert registered["WBTC"] == (EventType.Reward, SubType.bridge)
        assert registered["BGT"] == (EventType.Reward, SubType.staking)
        assert registered["HONEY"] == (EventType.Swap, None)

        unregistered = _by_in_asset(
            _events(
                _processor(
                    bridged_registry=_bridged_registry(_BRIDGED_TOKEN_OTHER)
                ).process(rows)[0]
            )
        )
        assert unregistered["WBTC"] == (EventType.Reward, SubType.spam)
        assert unregistered["BGT"] == (EventType.Reward, SubType.staking)
        assert unregistered["HONEY"] == (EventType.Swap, None)
        spam_event = next(
            e
            for e in _events(
                _processor(
                    bridged_registry=_bridged_registry(_BRIDGED_TOKEN_OTHER)
                ).process(rows)[0]
            )
            if e.sub_type is SubType.spam
        )
        assert spam_event.review_reason is not None, "a mint-spam split half must stay review-flagged"
        assert "registered reward distributor" not in spam_event.review_reason

    def test_zero_address_mint_registered_token_bridge(self) -> None:
        # Plan 2026-08-26 Task 1: characterization - a zero-address mint of a
        # token IN the bridged-asset registry keeps TODAY's behavior
        # (Reward/bridge with the existing bridge review reason; Design
        # Invariant "registry members' behavior byte-identical").
        rows = [
            _row(
                tx_hash="0xregmint",
                asset="WBTC",
                direction="in",
                token_address=_BRIDGED_TOKEN,
                from_address=_ZERO_ADDRESS,
                to_address=_WALLET,
                amount_raw=10**8,
                amount_decimals=8,
                fee_asset=None,
                fee_amount_raw=None,
            ),
        ]
        processor = _processor(bridged_registry=_bridged_registry(_BRIDGED_TOKEN))

        txs = processor.process(rows)

        assert len(txs) == 1
        events = _events(txs[0])
        assert len(events) == 1
        assert events[0].event_type is EventType.Reward
        assert events[0].sub_type is SubType.bridge
        reason = events[0].review_reason
        assert reason is not None, "a registered bridge mint must stay review-flagged"
        # Review r1 F8: pin the bridge reason byte-identically (the plan
        # invariant "registry members' behavior byte-identical"), mirroring
        # ``test_sender_spam_reason_unchanged`` - substring asserts would let
        # wording drift pass the suite.
        assert reason == (
            "inflow classified as a possible bridge transfer-in (tokens "
            "minted from the zero address - no external sender, e.g. "
            "bridged WBTC); the current workflow cannot match it to the "
            "originating acquisition (e.g. a CEX withdrawal) - verify "
            "source and cost basis before filing"
        )

    def test_zero_address_mint_unregistered_token_spam(self) -> None:
        # Plan 2026-08-26 Task 1: a zero-address mint of a token NOT in the
        # registry classifies Reward/spam + review with a MINT-SPECIFIC reason
        # naming the unregistered token - never the sender-spam text (there is
        # no sender; UL #91 discriminator branching).
        rows = [
            _row(
                tx_hash="0xjunkmint",
                asset="JUNK",
                direction="in",
                token_address=_UNREGISTERED_MINT_TOKEN,
                from_address=_ZERO_ADDRESS,
                to_address=_WALLET,
                amount_raw=5_000_000 * 10**18,
                fee_asset=None,
                fee_amount_raw=None,
            ),
        ]
        processor = _processor(bridged_registry=_bridged_registry(_BRIDGED_TOKEN_OTHER))

        txs = processor.process(rows)

        assert len(txs) == 1
        events = _events(txs[0])
        assert len(events) == 1
        assert events[0].event_type is EventType.Reward
        assert events[0].sub_type is SubType.spam
        assert events[0].sub_type is not SubType.bridge
        reason = events[0].review_reason
        assert reason is not None, "an unregistered mint must stay review-flagged"
        # Review r2 overflow: pin the mint-spam reason byte-identically,
        # mirroring the registered-mint bridge pin above and the sender-spam
        # pin (substring asserts would let wording drift pass the suite).
        assert reason == (
            f"mint classified as spam (token "
            f"{_UNREGISTERED_MINT_TOKEN.lower()} "
            f"was minted from the zero address and is not in the "
            f"bridged-asset registry - possible spam airdrop); verify "
            f"the token's origin and value before filing"
        )
        assert "registered reward distributor" not in reason

    def test_zero_address_mint_empty_registry_spam(self) -> None:
        # Plan 2026-08-26 Task 1: an EMPTY registry (the corrupted-checkout
        # degradation) means EVERY zero-address mint classifies spam + review
        # (nothing silently clean; never a silent bridge).
        rows = [
            _row(
                tx_hash="0xemptyreg",
                asset="WBTC",
                direction="in",
                token_address=_BRIDGED_TOKEN,
                from_address=_ZERO_ADDRESS,
                to_address=_WALLET,
                amount_raw=10**8,
                amount_decimals=8,
                fee_asset=None,
                fee_amount_raw=None,
            ),
        ]
        processor = _processor(bridged_registry=_bridged_registry())

        txs = processor.process(rows)

        assert len(txs) == 1
        events = _events(txs[0])
        assert len(events) == 1
        assert events[0].event_type is EventType.Reward
        assert events[0].sub_type is SubType.spam
        # Review r4 F7: byte-pin the full reason, mirroring the unregistered
        # sibling (same mint-spam f-string; wording drift must fail the suite).
        reason = events[0].review_reason
        assert reason is not None, "an empty-registry mint must stay review-flagged"
        assert reason == (
            f"mint classified as spam (token "
            f"{_BRIDGED_TOKEN.lower()} "
            f"was minted from the zero address and is not in the "
            f"bridged-asset registry - possible spam airdrop); verify "
            f"the token's origin and value before filing"
        )

    def test_zero_address_mint_native_token_spam(self) -> None:
        # Plan 2026-08-26 Task 1: a zero-address mint whose Leg.token_address
        # is None (the native asset - no contract address to be a registry
        # member) classifies spam + review.
        rows = [
            _row(
                tx_hash="0xnativemint",
                asset="BERA",
                direction="in",
                token_address=None,
                from_address=_ZERO_ADDRESS,
                to_address=_WALLET,
                fee_asset=None,
                fee_amount_raw=None,
            ),
        ]
        processor = _processor(bridged_registry=_bridged_registry(_BRIDGED_TOKEN))

        txs = processor.process(rows)

        assert len(txs) == 1
        events = _events(txs[0])
        assert len(events) == 1
        assert events[0].event_type is EventType.Reward
        assert events[0].sub_type is SubType.spam
        # Review r1 F3: pin the explicit ``<native asset>`` degradation (the
        # ``str | None`` f-string must degrade explicitly; repo style rule).
        # Review r3 F5: byte-pin the full reason, mirroring the sibling
        # sender-spam exact pin (wording drift must fail the suite).
        expected_reason = (
            "mint classified as spam (token <native asset> "
            "was minted from the zero address and is not in the "
            "bridged-asset registry - possible spam airdrop); verify "
            "the token's origin and value before filing"
        )
        assert events[0].review_reason == expected_reason

    def test_bridged_asset_membership_case_insensitive(self) -> None:
        # Plan 2026-08-26 Task 1: the registry stores the LOWERCASE address
        # and the leg carries the CHECKSUMMED form - membership is
        # case-insensitive, so the mint classifies bridge.
        rows = [
            _row(
                tx_hash="0xcasecheck",
                asset="WBTC",
                direction="in",
                token_address=_BRIDGED_TOKEN_UPPER,
                from_address=_ZERO_ADDRESS,
                to_address=_WALLET,
                amount_raw=10**8,
                amount_decimals=8,
                fee_asset=None,
                fee_amount_raw=None,
            ),
        ]
        processor = _processor(bridged_registry=_bridged_registry(_BRIDGED_TOKEN))

        txs = processor.process(rows)

        assert len(txs) == 1
        events = _events(txs[0])
        assert len(events) == 1
        assert events[0].event_type is EventType.Reward
        assert events[0].sub_type is SubType.bridge

    def test_sender_spam_reason_unchanged(self) -> None:
        # Plan 2026-08-26 Task 1 (UL #91: each cause exercised): a
        # NON-zero-address reward from an unregistered sender keeps the
        # EXISTING sender-spam reason text byte-identical when a bridged-asset
        # registry is loaded - the registry gate must not disturb the
        # sender-verification branch.
        rows = [
            _row(
                tx_hash="0xsenderspam",
                asset="HONEY",
                direction="in",
                token_address="0x000000000000000000000000000000000000abcd",
                from_address=_REWARD_DISTRIBUTOR_UNVERIFIED,  # NOT in registry
                to_address=_WALLET,
                amount_raw=10**18,
                fee_asset=None,
                fee_amount_raw=None,
            ),
        ]
        processor = _processor(bridged_registry=_bridged_registry(_BRIDGED_TOKEN))

        txs = processor.process(rows)

        assert len(txs) == 1
        events = _events(txs[0])
        assert len(events) == 1
        assert events[0].event_type is EventType.Reward
        assert events[0].sub_type is SubType.spam
        expected_reason = (
            f"reward classified as spam (sender "
            f"{_REWARD_DISTRIBUTOR_UNVERIFIED.lower()} is not a "
            f"registered reward distributor); verify it is not taxable "
            f"income before filing"
        )
        assert events[0].review_reason == expected_reason

    def test_empty_sender_spam_reward_keeps_sender_spam_reason(self) -> None:
        # Review r5 F2 (post-exit polish): pin the negative boundary of the
        # mint-vs-sender discriminator - a spam Reward whose from_address is
        # EMPTY (the CSV reader coerces a missing cell to "") is NOT a
        # zero-address mint, so it must keep the SENDER-spam reason (with the
        # '<missing>' placeholder for the empty sender), never the
        # mint-spam text. A truthiness regression on _is_zero_address
        # ("" is falsy) would flip this reason while the suite stayed green.
        rows = [
            _row(
                tx_hash="0xemptysender",
                asset="HONEY",
                direction="in",
                token_address=_UNREGISTERED_MINT_TOKEN,
                from_address="",  # reader coercion of a missing cell
                to_address=_WALLET,
                amount_raw=5_000_000 * 10**18,
                fee_asset=None,
                fee_amount_raw=None,
            ),
        ]
        processor = _processor(bridged_registry=_bridged_registry(_BRIDGED_TOKEN))

        txs = processor.process(rows)

        assert len(txs) == 1
        events = _events(txs[0])
        assert len(events) == 1
        assert events[0].event_type is EventType.Reward
        assert events[0].sub_type is SubType.spam
        assert events[0].review_reason == (
            "reward classified as spam (sender <missing> is not a "
            "registered reward distributor); verify it is not taxable "
            "income before filing"
        )

    def test_swap_absorbing_mint_leg_warns(self, caplog) -> None:
        # Review r1 F3 residual: a bidirectional mint+out tx with NO
        # distributor/router split classifies as a Swap; the zero-address
        # mint in-leg must at least WARN that a bridge/CEX transfer-in may
        # be hidden inside the exchange shape.
        rows = [
            _row(
                tx_hash="0xswapmint",
                asset="WBTC",
                direction="in",
                token_address="0x0000000000000000000000000000000000000b7c",
                from_address=_ZERO_ADDRESS,
                to_address=_WALLET,
                amount_raw=10**8,
                amount_decimals=8,
                fee_asset=None,
                fee_amount_raw=None,
            ),
            _row(
                tx_hash="0xswapmint",
                asset="HONEY",
                direction="out",
                token_address="0x0000000000000000000000000000000000000hny",
                from_address=_WALLET,
                to_address="0x0000000000000000000000000000000000000pair",
                fee_asset=None,
                fee_amount_raw=None,
            ),
        ]
        processor = _processor()

        with caplog.at_level(logging.WARNING, logger=BerachainProcessor.__module__):
            txs = processor.process(rows)

        events = _events(txs[0])
        assert len(events) == 1
        assert events[0].event_type is EventType.Swap
        assert any(
            "zero-address mint in-leg" in rec.getMessage() for rec in caplog.records
        ), "expected the Swap-absorbs-mint WARNING"
        # Review r5 (risk): the indicator must also live ON the Event so it
        # survives into the merged-TH Description, not only the log.
        assert events[0].review_reason is not None
        assert "zero-address mint in-leg" in events[0].review_reason

    def test_same_asset_multi_sender_reward_splits_per_sender(self) -> None:
        # Given - a tx with TWO same-asset reward in-legs from DIFFERENT
        # senders: leg A from a registered reward-distributor (verified),
        # leg B from an unverified address. The heterogeneity guard (F3)
        # must NOT collapse them into one summed Reward Event (which would
        # launder the spam sender's amount into a clean `staking` event).
        # Instead: ONE Reward Event PER (asset, sender) -> two Reward Events
        # for the same asset: one `staking` (verified amount) + one `spam`
        # with review=True (unverified amount).
        verified_amount = 10**18
        spam_amount = 4 * 10**18
        rows = [
            _row(
                tx_hash="0xmulti",
                asset="HONEY",
                direction="in",
                token_address="0x000000000000000000000000000000000000abcd",
                from_address=_REWARD_DISTRIBUTOR_VERIFIED,  # in registry
                to_address=_WALLET,
                amount_raw=verified_amount,
                fee_asset=None,
                fee_amount_raw=None,
            ),
            _row(
                tx_hash="0xmulti",
                asset="HONEY",
                direction="in",
                token_address="0x000000000000000000000000000000000000abcd",
                from_address=_REWARD_DISTRIBUTOR_UNVERIFIED,  # NOT in registry
                to_address=_WALLET,
                amount_raw=spam_amount,
                fee_asset=None,
                fee_amount_raw=None,
            ),
        ]
        processor = _processor()

        txs = processor.process(rows)

        assert len(txs) == 1
        events = _events(txs[0])
        # TWO Reward Events for the same asset (one per sender), NOT one
        # collapsed event for the summed amount.
        assert len(events) == 2
        assert all(e.event_type is EventType.Reward for e in events)
        # One staking (verified sender) + one spam (unverified sender).
        staking_events = [e for e in events if e.sub_type is SubType.staking]
        spam_events = [e for e in events if e.sub_type is SubType.spam]
        assert len(staking_events) == 1
        assert len(spam_events) == 1
        # The staking event carries ONLY the verified-sender amount; the
        # spam event carries ONLY the unverified-sender amount (not summed).
        assert staking_events[0].legs[0].amount_raw == verified_amount
        assert spam_events[0].legs[0].amount_raw == spam_amount
        # The spam event carries a review flag (F4); the staking event does not.
        # (Event.review is asserted indirectly via sub_type spam above + the
        # _event helper's review= contract; here we assert the sender split
        # is the load-bearing property.)
        # Both events are for the SAME asset (HONEY).
        assert {e.legs[0].asset for e in events} == {"HONEY"}
        # The two senders are distinct on the two events' representative legs.
        senders = {(e.legs[0].from_address or "").lower() for e in events}
        assert senders == {
            _REWARD_DISTRIBUTOR_VERIFIED.lower(),
            _REWARD_DISTRIBUTOR_UNVERIFIED.lower(),
        }

    def test_inbound_from_registered_self_wallet_classifies_transfer(self) -> None:
        # C3 (validation-harness plan Task 8): 1 BERA in-leg from a
        # REGISTERED self-wallet address (the tracked wallet's second own
        # wallet). Expects ONE Transfer Event (internal_transfer), NOT the
        # Reward the branch-3 pure-inflow shape produces for this shape
        # today (~10 real 2025 self-transfers mis-tagged Reward/spam).
        rows = [
            _row(
                tx_hash="0xinself",
                asset="BERA",
                direction="in",
                token_address=None,
                from_address=_SELF_WALLET,
                to_address=_WALLET,
                amount_raw=10**18,
                fee_asset=None,
                fee_amount_raw=None,
            ),
        ]
        processor = _processor(registry=_self_wallet_registry())

        txs = processor.process(rows)

        assert len(txs) == 1
        events = _events(txs[0])
        assert len(events) == 1
        assert events[0].event_type is EventType.Transfer
        assert events[0].sub_type is SubType.internal_transfer
        # The Transfer carries the economic in-leg.
        assert len(events[0].legs) == 1
        assert events[0].legs[0].asset == "BERA"

    def test_outbound_to_registered_self_wallet_classifies_transfer(self) -> None:
        # C3: 1 BERA out-leg TO a registered self-wallet. Expects ONE
        # Transfer Event (internal_transfer), NOT the Event(Unknown) +
        # review the pure-outflow fallback emits for this shape today.
        rows = [
            _row(
                tx_hash="0xoutself",
                asset="BERA",
                direction="out",
                token_address=None,
                from_address=_WALLET,
                to_address=_SELF_WALLET,
                amount_raw=10**18,
                fee_asset="BERA",
                fee_amount_raw=21_000_002_730_000,
            ),
        ]
        processor = _processor(registry=_self_wallet_registry())

        txs = processor.process(rows)

        assert len(txs) == 1
        events = _events(txs[0])
        assert len(events) == 1
        assert events[0].event_type is EventType.Transfer
        assert events[0].sub_type is SubType.internal_transfer
        assert len(events[0].legs) == 1
        assert events[0].legs[0].direction == "out"

    def test_self_wallet_check_precedes_reward_branch(self) -> None:
        # C3 ordering pin: a MULTI-asset inbound self-transfer (BERA + BGT
        # in-legs, both from the self-wallet, no out-leg) ALSO satisfies the
        # branch-3 pure-inflow multi-token reward shape. The self-wallet
        # dispatch must run BEFORE branch 3, or the tx misclassifies as
        # per-asset Reward Events; under the fix it is ONE Transfer carrying
        # both legs.
        rows = [
            _row(
                tx_hash="0xmultiself",
                asset="BERA",
                direction="in",
                token_address=None,
                from_address=_SELF_WALLET,
                to_address=_WALLET,
                amount_raw=10**18,
                fee_asset=None,
                fee_amount_raw=None,
            ),
            _row(
                tx_hash="0xmultiself",
                asset="BGT",
                direction="in",
                token_address="0x000000000000000000000000000000000000bgt0",
                from_address=_SELF_WALLET,
                to_address=_WALLET,
                amount_raw=2 * 10**18,
                fee_asset=None,
                fee_amount_raw=None,
            ),
        ]
        processor = _processor(registry=_self_wallet_registry())

        txs = processor.process(rows)

        assert len(txs) == 1
        events = _events(txs[0])
        assert len(events) == 1
        assert events[0].event_type is EventType.Transfer
        assert events[0].sub_type is SubType.internal_transfer
        # Both assets ride the ONE Transfer (not split per asset).
        assert {leg.asset for leg in events[0].legs} == {"BERA", "BGT"}

    def test_unregistered_sender_still_reward_spam(self) -> None:
        # C3 negative (behavior preserved): the SAME pure-inflow shape from
        # an UNREGISTERED sender still classifies Reward (spam) + review.
        # The self-wallet branch must not swallow ordinary airdrop spam
        # (F4: unverified senders are never a clean classification).
        rows = [
            _row(
                tx_hash="0xspamself",
                asset="BERA",
                direction="in",
                token_address=None,
                from_address=_REWARD_DISTRIBUTOR_UNVERIFIED,  # NOT registered
                to_address=_WALLET,
                amount_raw=10**18,
                fee_asset=None,
                fee_amount_raw=None,
            ),
        ]
        # Registry contains ONLY the self-wallet entry, so the sender is
        # unregistered by construction.
        processor = _processor(registry=_self_wallet_registry())

        txs = processor.process(rows)

        assert len(txs) == 1
        events = _events(txs[0])
        assert len(events) == 1
        assert events[0].event_type is EventType.Reward
        assert events[0].sub_type is SubType.spam

    # ------------------------------------------------------------------
    # Unknown-family classifier rules (plan 2026-08-22-bera-unknown-
    # classifier-rules, Task 3): pure-outflow vault re-staking, zaps, and
    # position tokens.
    # ------------------------------------------------------------------

    def test_pure_outflow_lp_token_send_is_vault_deposit(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Task 3 routing target 1 (the 26x/4x/3x/1x lp=true families): a
        # PURE outflow whose single economic leg sends an LP-token
        # (LP-snapshot member; island/vault re-staking); the BERA leg is
        # the zero-value gas carrier. Expects Event(LiquidityDeposit)
        # carrying ONLY the LP leg, with NO review flag.
        rows = [
            _row(
                tx_hash="0xlpout",
                asset="BERA",
                direction="out",
                token_address=None,
                from_address=_WALLET,
                to_address=_DEX_ROUTER,
                amount_raw=0,
                fee_asset="BERA",
                fee_amount_raw=21_000_002_730_000,
            ),
            _row(
                tx_hash="0xlpout",
                asset="KODI-iBERA-iBGT",
                direction="out",
                token_address=_LP_TOKEN,  # snapshot-confirmed LP token
                from_address=_WALLET,
                to_address=_DEX_ROUTER,
                amount_raw=167562392010422254161,
                fee_asset=None,
                fee_amount_raw=None,
            ),
        ]
        processor = _processor()

        with caplog.at_level(logging.WARNING, logger=BerachainProcessor.__module__):
            txs = processor.process(rows)

        assert len(txs) == 1
        events = _events(txs[0])
        assert len(events) == 1
        assert events[0].event_type is EventType.LiquidityDeposit
        assert events[0].sub_type is SubType.internal_transfer
        # Only the economic LP leg rides the Event (carrier excluded).
        assert len(events[0].legs) == 1
        assert events[0].legs[0].token_address == _LP_TOKEN
        # No review flag: the classification is clean, so no review WARNING.
        assert not _review_messages(caplog)

    def test_pure_outflow_lp_send_not_in_snapshot_stays_unknown(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Task 3 address-keyed gate (negative): the SAME pure-outflow shape
        # with a token NOT in the LP snapshot (and not a position token)
        # stays Event(Unknown) + review - never a name-based guess.
        rows = [
            _row(
                tx_hash="0xlplpunknown",
                asset="BERA",
                direction="out",
                token_address=None,
                from_address=_WALLET,
                to_address=_DEX_ROUTER,
                amount_raw=0,
                fee_asset="BERA",
                fee_amount_raw=21_000_002_730_000,
            ),
            _row(
                tx_hash="0xlplpunknown",
                asset="SOME-TOKEN",
                direction="out",
                token_address="0x000000000000000000000000000000000000abcd",  # NOT in snapshot
                from_address=_WALLET,
                to_address=_DEX_ROUTER,
                amount_raw=10**18,
                fee_asset=None,
                fee_amount_raw=None,
            ),
        ]
        processor = _processor()

        with caplog.at_level(logging.WARNING, logger=BerachainProcessor.__module__):
            txs = processor.process(rows)

        assert len(txs) == 1
        events = _events(txs[0])
        assert len(events) == 1
        assert events[0].event_type is EventType.Unknown
        assert _review_messages(caplog), "expected a review-flag WARNING for the Unknown fallback"

    def test_bidirectional_position_token_receive_is_liquidity_deposit_characterization(
        self,
    ) -> None:
        # Task 3 characterization pin (must stay GREEN before AND after the
        # withdraw rule lands): in-legs RECEIVE an island/vault receipt
        # token (LP-snapshot member) while out-legs send the LP/underlying
        # -> Event(LiquidityDeposit) via the EXISTING bidirectional-receive
        # shape. Guards that the new withdraw rule (which slots before it)
        # never consumes the receive direction.
        rows = [
            _row(
                tx_hash="0xislrecv",
                asset="BERA",
                direction="out",
                token_address=None,
                from_address=_WALLET,
                to_address=_DEX_ROUTER,
                amount_raw=10**18,
                fee_asset="BERA",
                fee_amount_raw=21_000_002_730_000,
            ),
            _row(
                tx_hash="0xislrecv",
                asset="KODI-LP",
                direction="out",
                token_address="0x000000000000000000000000000000000000abcd",
                from_address=_WALLET,
                to_address=_DEX_ROUTER,
                amount_raw=5 * 10**18,
                fee_asset=None,
                fee_amount_raw=None,
            ),
            _row(
                tx_hash="0xislrecv",
                asset="KODI-ISLAND",
                direction="in",
                token_address=_LP_TOKEN,  # island receipt: LP-snapshot member
                from_address=_DEX_ROUTER,
                to_address=_WALLET,
                amount_raw=4 * 10**18,
                fee_asset=None,
                fee_amount_raw=None,
            ),
        ]
        processor = _processor()

        txs = processor.process(rows)

        assert len(txs) == 1
        events = _events(txs[0])
        assert len(events) == 1
        assert events[0].event_type is EventType.LiquidityDeposit
        assert events[0].sub_type is SubType.internal_transfer

    def test_bidirectional_position_token_send_is_withdraw_precedes_amm_deposit(
        self,
    ) -> None:
        # Task 3 withdraw rule (RED on HEAD: the pre-rule dispatch reads
        # this shape as a plain Swap): in-legs RECEIVE the LP/underlying
        # while out-legs SEND the island/vault receipt token (LP-snapshot
        # member) -> Event(LiquidityWithdraw). The rule must slot BEFORE
        # the bidirectional-receive deposit shape.
        rows = [
            _row(
                tx_hash="0xislsend",
                asset="KODI-ISLAND",
                direction="out",
                token_address=_LP_TOKEN,  # island receipt: LP-snapshot member
                from_address=_WALLET,
                to_address=_DEX_ROUTER,
                amount_raw=4 * 10**18,
                fee_asset="BERA",
                fee_amount_raw=21_000_002_730_000,
            ),
            _row(
                tx_hash="0xislsend",
                asset="KODI-LP",
                direction="in",
                token_address="0x000000000000000000000000000000000000abcd",
                from_address=_DEX_ROUTER,
                to_address=_WALLET,
                amount_raw=5 * 10**18,
                fee_asset=None,
                fee_amount_raw=None,
            ),
        ]
        processor = _processor()

        txs = processor.process(rows)

        assert len(txs) == 1
        events = _events(txs[0])
        assert len(events) == 1
        assert events[0].event_type is EventType.LiquidityWithdraw
        assert events[0].sub_type is SubType.internal_transfer
        assert {leg.direction for leg in events[0].legs} == {"in", "out"}

    def test_self_wallet_outbound_precedes_pure_outflow_rule(self) -> None:
        # Task 3 precedence pin: a PURE outflow of an LP-snapshot member
        # whose single recipient is a registered self-wallet classifies
        # Transfer (shape 8 keeps precedence over the new pure-outflow
        # deposit rule - an internal self-transfer is never a deposit).
        rows = [
            _row(
                tx_hash="0xselflpout",
                asset="BERA",
                direction="out",
                token_address=None,
                from_address=_WALLET,
                to_address=_SELF_WALLET,
                amount_raw=0,
                fee_asset="BERA",
                fee_amount_raw=21_000_002_730_000,
            ),
            _row(
                tx_hash="0xselflpout",
                asset="KODI-LP",
                direction="out",
                token_address=_LP_TOKEN,
                from_address=_WALLET,
                to_address=_SELF_WALLET,
                amount_raw=5 * 10**18,
                fee_asset=None,
                fee_amount_raw=None,
            ),
        ]
        processor = _processor(registry=_self_wallet_registry())

        txs = processor.process(rows)

        assert len(txs) == 1
        events = _events(txs[0])
        assert len(events) == 1
        assert events[0].event_type is EventType.Transfer
        assert events[0].sub_type is SubType.internal_transfer

    def test_multi_leg_lp_outflow_still_vault_deposit(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Task 3 routing target 2 (multi-leg pure outflow): an LP-token out
        # PLUS a second economic out-leg (the zap-add shape) ->
        # Event(LiquidityDeposit) with ALL non-gas out-legs economic.
        # Review r2 F3 (gated arm): the LP member token carries the member
        # signal, so the clean classification must carry NO review flag.
        rows = [
            _row(
                tx_hash="0xzaplp",
                asset="BERA",
                direction="out",
                token_address=None,
                from_address=_WALLET,
                to_address=_DEX_ROUTER,
                amount_raw=0,
                fee_asset="BERA",
                fee_amount_raw=21_000_002_730_000,
            ),
            _row(
                tx_hash="0xzaplp",
                asset="KODI-LP",
                direction="out",
                token_address=_LP_TOKEN,
                from_address=_WALLET,
                to_address=_DEX_ROUTER,
                amount_raw=5 * 10**18,
                fee_asset=None,
                fee_amount_raw=None,
            ),
            _row(
                tx_hash="0xzaplp",
                asset="HONEY",
                direction="out",
                token_address="0x000000000000000000000000000000000000abcd",
                from_address=_WALLET,
                to_address=_DEX_ROUTER,
                amount_raw=42 * 10**18,
                fee_asset=None,
                fee_amount_raw=None,
            ),
        ]
        processor = _processor()

        with caplog.at_level(logging.WARNING, logger=BerachainProcessor.__module__):
            txs = processor.process(rows)

        assert len(txs) == 1
        events = _events(txs[0])
        assert len(events) == 1
        assert events[0].event_type is EventType.LiquidityDeposit
        # BOTH economic out-legs ride the Event; the gas carrier does not.
        assert len(events[0].legs) == 2
        assert {leg.asset for leg in events[0].legs} == {"KODI-LP", "HONEY"}
        # Gated multi-leg outflow (member LP token): clean, no review flag.
        assert not _review_messages(caplog), "member-signal multi-leg deposit must NOT carry a review flag"

    def test_multi_leg_outflow_with_economic_native_leg_keeps_bera(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Review r3 F2: sibling of test_multi_leg_lp_outflow_still_vault_deposit
        # with the native BERA out-leg carrying a NON-ZERO amount (the
        # BERA+iBGT family shape): a non-zero native out leg is ECONOMIC, not
        # a gas carrier, and must ride the Event. A refactor widening the
        # gas-carrier exclusion from zero-value to ALL native out-legs drops
        # the economic BERA amount and fails this test.
        rows = [
            _row(
                tx_hash="0xeconbera",
                asset="BERA",
                direction="out",
                token_address=None,
                from_address=_WALLET,
                to_address=_DEX_ROUTER,
                amount_raw=10**18,  # ECONOMIC native out, NOT a gas carrier
                fee_asset="BERA",
                fee_amount_raw=21_000_002_730_000,
            ),
            _row(
                tx_hash="0xeconbera",
                asset="KODI-LP",
                direction="out",
                token_address=_LP_TOKEN,
                from_address=_WALLET,
                to_address=_DEX_ROUTER,
                amount_raw=5 * 10**18,
                fee_asset=None,
                fee_amount_raw=None,
            ),
        ]
        processor = _processor()

        with caplog.at_level(logging.WARNING, logger=BerachainProcessor.__module__):
            txs = processor.process(rows)

        assert len(txs) == 1
        events = _events(txs[0])
        assert len(events) == 1
        assert events[0].event_type is EventType.LiquidityDeposit
        # BOTH economic legs ride the Event, native BERA included.
        assert {leg.asset for leg in events[0].legs} == {"BERA", "KODI-LP"}
        # LP member token carries the member signal: no review flag.
        assert not _review_messages(caplog), "member-signal multi-leg deposit must NOT carry a review flag"

    def test_multi_leg_outflow_registry_member_recipient_clears_review_flag(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Review r3 F5: the shape-11 gate's RECIPIENT arm. The same
        # member-signal-less multi-leg zap as
        # test_three_asset_zap_send_classifies_per_routing_table, but the
        # zero-value BERA carrier leg targets a position-registry VAULT
        # recipient: that member signal must clear the review flag. Deleting
        # the recipient disjunct from the gate re-flags this tx and fails
        # the test.
        rows = [
            _row(
                tx_hash="0xzaprecv",
                asset="BERA",
                direction="out",
                token_address=None,
                from_address=_WALLET,
                to_address=_REGISTRY_MEMBER_RECIPIENT,  # tx-level `to`: the vault
                amount_raw=0,  # zero-value gas carrier
                fee_asset="BERA",
                fee_amount_raw=21_000_002_730_000,
            ),
            _row(
                tx_hash="0xzaprecv",
                asset="WETH",
                direction="out",
                token_address="0x000000000000000000000000000000000000aaaa",  # NOT a member
                from_address=_WALLET,
                to_address=_DEX_ROUTER,
                amount_raw=16614564627822753,
                fee_asset=None,
                fee_amount_raw=None,
            ),
            _row(
                tx_hash="0xzaprecv",
                asset="BUSD",
                direction="out",
                token_address="0x000000000000000000000000000000000000bbbb",  # NOT a member
                from_address=_WALLET,
                to_address=_DEX_ROUTER,
                amount_raw=44967194308601099299,
                fee_asset=None,
                fee_amount_raw=None,
            ),
        ]
        processor = _processor(position_registry=_position_registry())

        with caplog.at_level(logging.WARNING, logger=BerachainProcessor.__module__):
            txs = processor.process(rows)

        assert len(txs) == 1
        events = _events(txs[0])
        assert len(events) == 1
        assert events[0].event_type is EventType.LiquidityDeposit
        assert {leg.asset for leg in events[0].legs} == {"WETH", "BUSD"}
        # The registry-member vault recipient clears the review flag.
        assert not _review_messages(caplog), "registry-member recipient multi-leg deposit must NOT carry a review flag"

    def test_pure_outflow_lst_send_classifies_per_routing_table(self) -> None:
        # Task 3 routing target 4 (cluster 6, verdict B): a PURE outflow of
        # a single LST out-leg gated on the NEW position-token registry ->
        # Event(LiquidityDeposit); single iBGT out-leg economic, no review.
        rows = [
            _row(
                tx_hash="0xlstout",
                asset="BERA",
                direction="out",
                token_address=None,
                from_address=_WALLET,
                to_address=_DEX_ROUTER,
                amount_raw=0,
                fee_asset="BERA",
                fee_amount_raw=21_000_002_730_000,
            ),
            _row(
                tx_hash="0xlstout",
                asset="iTEST",
                direction="out",
                token_address=_POSITION_TOKEN,  # position-registry member
                from_address=_WALLET,
                to_address=_DEX_ROUTER,
                amount_raw=1476177230747713290,
                fee_asset=None,
                fee_amount_raw=None,
            ),
        ]
        processor = _processor(position_registry=_position_registry())

        txs = processor.process(rows)

        assert len(txs) == 1
        events = _events(txs[0])
        assert len(events) == 1
        assert events[0].event_type is EventType.LiquidityDeposit
        assert events[0].sub_type is SubType.internal_transfer
        assert len(events[0].legs) == 1
        assert events[0].legs[0].token_address == _POSITION_TOKEN

    def test_pure_outflow_lst_send_without_registry_stays_unknown(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Review r1 F17: the None-registry degradation contract at the
        # PROCESSOR level - the same pure LST outflow as the routing-table
        # test above, built through a processor constructed WITHOUT a
        # position-token registry, must degrade fail-loud to
        # ``Event(Unknown) + review`` (mirroring the loader's degradation
        # test); if ``None`` later raised or silently widened, this fails.
        rows = [
            _row(
                tx_hash="0xlstnoreg",
                asset="iTEST",
                direction="out",
                token_address=_POSITION_TOKEN,
                from_address=_WALLET,
                to_address=_DEX_ROUTER,
                amount_raw=1476177230747713290,
                fee_asset="BERA",
                fee_amount_raw=21_000_002_730_000,
            ),
        ]
        processor = _processor()  # NO position_token_registry

        with caplog.at_level(logging.WARNING, logger=BerachainProcessor.__module__):
            txs = processor.process(rows)

        assert len(txs) == 1
        events = _events(txs[0])
        assert len(events) == 1
        assert events[0].event_type is EventType.Unknown
        assert _review_messages(caplog), "expected a review-flag WARNING for the Unknown fallback"

    def test_pure_outflow_to_registry_member_recipient_is_vault_deposit(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Task 3/5 fix (sig 2 residual `exchange/|fee=fee_column`): a PURE
        # outflow with a SINGLE economic out-leg whose token is NOT an
        # LP/position member and whose recipient is the AMM pool (NOT a
        # registry member), BUT whose tx-level recipient - the ``to`` of the
        # zero-value native BERA carrier leg - IS a position-token-registry
        # member (the position-NFT vault). The wallet deposits into a
        # registered vault and receives an ERC-721 position mint invisible
        # to txlist/tokentx/txlistinternal -> Event(LiquidityDeposit)
        # carrying the economic leg, no review flag.
        rows = [
            _row(
                tx_hash="0xvaultrecv",
                asset="BERA",
                direction="out",
                token_address=None,
                from_address=_WALLET,
                to_address=_REGISTRY_MEMBER_RECIPIENT,  # tx-level `to`: the vault
                amount_raw=0,  # zero-value gas carrier
                fee_asset="BERA",
                fee_amount_raw=21_000_002_730_000,
            ),
            _row(
                tx_hash="0xvaultrecv",
                asset="BUSD",
                direction="out",
                token_address="0x000000000000000000000000000000000000b00b",  # NOT a member token
                from_address=_WALLET,
                to_address="0x000000000000000000000000000000000000c0de",  # AMM pool, NOT a member
                amount_raw=10**18,
                fee_asset=None,
                fee_amount_raw=None,
            ),
        ]
        processor = _processor(position_registry=_position_registry())

        with caplog.at_level(logging.WARNING, logger=BerachainProcessor.__module__):
            txs = processor.process(rows)

        assert len(txs) == 1
        events = _events(txs[0])
        assert len(events) == 1
        assert events[0].event_type is EventType.LiquidityDeposit
        assert events[0].sub_type is SubType.internal_transfer
        # Only the economic BUSD leg rides the Event (carrier excluded).
        assert len(events[0].legs) == 1
        assert events[0].legs[0].token_address == "0x000000000000000000000000000000000000b00b"
        # No review flag: the classification is clean, so no review WARNING.
        assert not _review_messages(caplog)

    def test_pure_outflow_to_registry_member_economic_leg_recipient_is_vault_deposit(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Review r1 F16: sibling of the carrier-leg test above - the SAME
        # single-leg pure-outflow shape, but the registry-member vault is the
        # ECONOMIC leg's own ``to_address`` (direct deposit; the carrier goes
        # to the router). Both arms of the recipient scan must route to
        # ``LiquidityDeposit``; a refactor scanning only the carrier leg (or
        # only the economic leg) must fail one of the two tests.
        rows = [
            _row(
                tx_hash="0xvaultecon",
                asset="BERA",
                direction="out",
                token_address=None,
                from_address=_WALLET,
                to_address=_DEX_ROUTER,  # tx-level `to`: the router, NOT a member
                amount_raw=0,  # zero-value gas carrier
                fee_asset="BERA",
                fee_amount_raw=21_000_002_730_000,
            ),
            _row(
                tx_hash="0xvaultecon",
                asset="BUSD",
                direction="out",
                token_address="0x000000000000000000000000000000000000b00b",  # NOT a member token
                from_address=_WALLET,
                to_address=_REGISTRY_MEMBER_RECIPIENT,  # economic leg to the vault
                amount_raw=10**18,
                fee_asset=None,
                fee_amount_raw=None,
            ),
        ]
        processor = _processor(position_registry=_position_registry())

        with caplog.at_level(logging.WARNING, logger=BerachainProcessor.__module__):
            txs = processor.process(rows)

        assert len(txs) == 1
        events = _events(txs[0])
        assert len(events) == 1
        assert events[0].event_type is EventType.LiquidityDeposit
        assert events[0].sub_type is SubType.internal_transfer
        assert len(events[0].legs) == 1
        assert events[0].legs[0].token_address == "0x000000000000000000000000000000000000b00b"
        assert not _review_messages(caplog)

    def test_pure_outflow_to_non_registry_recipient_stays_unknown(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Address-keyed gate (negative): the SAME single-leg pure-outflow
        # shape with a recipient NOT in the position-token registry stays
        # Event(Unknown) + review - membership is keyed by address, never
        # by asset name or shape similarity.
        rows = [
            _row(
                tx_hash="0xnonmemberrecv",
                asset="BERA",
                direction="out",
                token_address=None,
                from_address=_WALLET,
                to_address="0x000000000000000000000000000000000000c0de",
                amount_raw=0,
                fee_asset="BERA",
                fee_amount_raw=21_000_002_730_000,
            ),
            _row(
                tx_hash="0xnonmemberrecv",
                asset="BUSD",
                direction="out",
                token_address="0x000000000000000000000000000000000000b00b",
                from_address=_WALLET,
                to_address="0x000000000000000000000000000000000000c0de",  # NOT a registry member
                amount_raw=10**18,
                fee_asset=None,
                fee_amount_raw=None,
            ),
        ]
        processor = _processor(position_registry=_position_registry())

        with caplog.at_level(logging.WARNING, logger=BerachainProcessor.__module__):
            txs = processor.process(rows)

        assert len(txs) == 1
        events = _events(txs[0])
        assert len(events) == 1
        assert events[0].event_type is EventType.Unknown
        assert _review_messages(caplog), "expected a review-flag WARNING for the Unknown fallback"

    def test_pure_outflow_to_lst_kind_recipient_stays_unknown(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Review r2 F2 (kind-gate negative arm): the recipient IS a registry
        # member address, but with kind="lst" (a tradable staking receipt
        # token contract, a normal direct-interaction target) - NOT a
        # position-NFT vault. The recipient rule is kind-gated (r1 F3), so
        # the tx stays Event(Unknown) + review; reverting
        # ``is_position_vault`` to plain membership must fail this test.
        rows = [
            _row(
                tx_hash="0xlstrecv",
                asset="BERA",
                direction="out",
                token_address=None,
                from_address=_WALLET,
                to_address=_POSITION_TOKEN,  # registry member, but kind="lst"
                amount_raw=0,
                fee_asset="BERA",
                fee_amount_raw=21_000_002_730_000,
            ),
            _row(
                tx_hash="0xlstrecv",
                asset="BUSD",
                direction="out",
                token_address="0x000000000000000000000000000000000000b00b",  # NOT a member token
                from_address=_WALLET,
                to_address="0x000000000000000000000000000000000000c0de",
                amount_raw=10**18,
                fee_asset=None,
                fee_amount_raw=None,
            ),
        ]
        processor = _processor(position_registry=_position_registry())

        with caplog.at_level(logging.WARNING, logger=BerachainProcessor.__module__):
            txs = processor.process(rows)

        assert len(txs) == 1
        events = _events(txs[0])
        assert len(events) == 1
        assert events[0].event_type is EventType.Unknown
        assert _review_messages(caplog), "expected a review-flag WARNING for the Unknown fallback"

    def test_three_asset_zap_send_classifies_per_routing_table(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Task 3 routing target 2 (cluster 4 zap: receives NOT recovered -
        # the receipt was an ERC-721 position mint txlistinternal cannot
        # serve): BUSD + WETH + BERA out (BERA is the zero-value gas
        # carrier) -> Event(LiquidityDeposit) with WETH and BUSD economic.
        # Review r2 F3 (ungated arm): no registry and no member signal ->
        # the deposit carries a review flag (r1 F2 gate), observable as a
        # review-flag WARNING; deleting the gate must fail this test.
        rows = [
            _row(
                tx_hash="0xzap3",
                asset="BERA",
                direction="out",
                token_address=None,
                from_address=_WALLET,
                to_address=_DEX_ROUTER,
                amount_raw=0,
                fee_asset="BERA",
                fee_amount_raw=21_000_002_730_000,
            ),
            _row(
                tx_hash="0xzap3",
                asset="WETH",
                direction="out",
                token_address="0x000000000000000000000000000000000000aaaa",
                from_address=_WALLET,
                to_address=_DEX_ROUTER,
                amount_raw=16614564627822753,
                fee_asset=None,
                fee_amount_raw=None,
            ),
            _row(
                tx_hash="0xzap3",
                asset="BUSD",
                direction="out",
                token_address="0x000000000000000000000000000000000000bbbb",
                from_address=_WALLET,
                to_address=_DEX_ROUTER,
                amount_raw=44967194308601099299,
                fee_asset=None,
                fee_amount_raw=None,
            ),
        ]
        processor = _processor()

        with caplog.at_level(logging.WARNING, logger=BerachainProcessor.__module__):
            txs = processor.process(rows)

        assert len(txs) == 1
        events = _events(txs[0])
        assert len(events) == 1
        assert events[0].event_type is EventType.LiquidityDeposit
        # Both non-gas out-legs are economic; the BERA carrier is excluded.
        assert {leg.asset for leg in events[0].legs} == {"WETH", "BUSD"}
        # Ungated multi-leg outflow: the review-flag WARNING must fire.
        assert _review_messages(caplog), "member-signal-less multi-leg outflow must carry a review flag"

    def test_unknown_fallback_still_terminal(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Task 3 fallback pin: a pure outflow of a non-LP, non-position
        # token not covered by any new rule stays Event(Unknown) + review
        # with the existing warning (the fail-loud fallback is terminal).
        rows = [
            _row(
                tx_hash="0xtermfb",
                asset="BERA",
                direction="out",
                token_address=None,
                from_address=_WALLET,
                to_address=_DEX_ROUTER,
                amount_raw=0,
                fee_asset="BERA",
                fee_amount_raw=21_000_002_730_000,
            ),
            _row(
                tx_hash="0xtermfb",
                asset="HONEY",
                direction="out",
                token_address="0x000000000000000000000000000000000000abcd",
                from_address=_WALLET,
                to_address=_DEX_ROUTER,
                amount_raw=10**18,
                fee_asset=None,
                fee_amount_raw=None,
            ),
        ]
        processor = _processor(position_registry=_position_registry())

        with caplog.at_level(logging.WARNING, logger=BerachainProcessor.__module__):
            txs = processor.process(rows)

        assert len(txs) == 1
        events = _events(txs[0])
        assert len(events) == 1
        assert events[0].event_type is EventType.Unknown
        assert _review_messages(caplog), "expected a review-flag WARNING for the terminal Unknown fallback"

    # ------------------------------------------------------------------
    # Shape-6 follow-ups (plan 2026-08-23-bera-unknown-followups, Task 1):
    # member-token gate split, LST unification, redemption-counterparty
    # review flag.
    # ------------------------------------------------------------------

    def test_lp_token_sale_review_flagged(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # A bidirectional tx whose out-leg sends an LP-snapshot member
        # (KODIAX-style receipt) to a BUYER while the in-leg BERA comes from
        # a DIFFERENT address (a DEX router): the receive side is not the
        # redemption counterparty, so the withdraw carries a review WARNING
        # naming the tx hash, the mismatched counterparty address, and a
        # disposal-specific reason.
        rows = [
            _row(
                tx_hash="0xlpsale",
                asset="KODI-ISLAND",
                direction="out",
                token_address=_LP_TOKEN,  # LP-snapshot member
                from_address=_WALLET,
                to_address=_LP_BUYER,  # NOT the in-leg sender
                amount_raw=4 * 10**18,
                fee_asset="BERA",
                fee_amount_raw=21_000_002_730_000,
            ),
            _row(
                tx_hash="0xlpsale",
                asset="BERA",
                direction="in",
                token_address=None,
                from_address=_DEX_ROUTER,  # differs from the member recipient
                to_address=_WALLET,
                amount_raw=5 * 10**18,
                fee_asset=None,
                fee_amount_raw=None,
            ),
        ]
        processor = _processor()

        with caplog.at_level(logging.WARNING, logger=BerachainProcessor.__module__):
            txs = processor.process(rows)

        assert len(txs) == 1
        events = _events(txs[0])
        assert len(events) == 1
        assert events[0].event_type is EventType.LiquidityWithdraw
        assert events[0].sub_type is SubType.internal_transfer
        review_msgs = _review_messages(caplog)
        assert review_msgs, "expected a review-flag WARNING for the LP sale shape"
        assert len(review_msgs) == 1, review_msgs
        msg = review_msgs[0]
        assert "0xlpsale" in msg
        assert _LP_BUYER in msg
        assert "disposal" in msg

    def test_vault_unstake_counterparty_match_clean(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Characterization: a bidirectional tx whose member-token out-leg
        # recipient EQUALS an in-leg's from_address (vault unstake) is a
        # clean LiquidityWithdraw - no review warning.
        rows = [
            _row(
                tx_hash="0xunstakeclean",
                asset="KODI-ISLAND",
                direction="out",
                token_address=_LP_TOKEN,  # LP-snapshot member
                from_address=_WALLET,
                to_address=_REGISTRY_MEMBER_RECIPIENT,  # the unstaking vault
                amount_raw=4 * 10**18,
                fee_asset="BERA",
                fee_amount_raw=21_000_002_730_000,
            ),
            _row(
                tx_hash="0xunstakeclean",
                asset="BERA",
                direction="in",
                token_address=None,
                from_address=_REGISTRY_MEMBER_RECIPIENT,  # == member recipient
                to_address=_WALLET,
                amount_raw=5 * 10**18,
                fee_asset=None,
                fee_amount_raw=None,
            ),
        ]
        processor = _processor(position_registry=_position_registry())

        with caplog.at_level(logging.WARNING, logger=BerachainProcessor.__module__):
            txs = processor.process(rows)

        assert len(txs) == 1
        events = _events(txs[0])
        assert len(events) == 1
        assert events[0].event_type is EventType.LiquidityWithdraw
        assert events[0].sub_type is SubType.internal_transfer
        assert not _review_messages(caplog), "counterparty-matching unstake must NOT carry a review flag"

    def test_lst_unstake_classifies_liquidity_withdraw(self) -> None:
        # A bidirectional tx whose out-leg sends a position-registry-ONLY
        # member (an LST) to the registry VAULT (kind="position_nft") with
        # underlying in-legs from the same vault: an LST unstake, unified
        # with the shape-6 withdraw as LiquidityWithdraw (vault-target
        # gated). RED on HEAD: the LP-snapshot-only gate falls to Swap.
        rows = [
            _row(
                tx_hash="0xlstunstake",
                asset="iTEST",
                direction="out",
                token_address=_POSITION_TOKEN,  # registry member, kind="lst"
                from_address=_WALLET,
                to_address=_REGISTRY_MEMBER_RECIPIENT,  # registry VAULT target
                amount_raw=1476177230747713290,
                fee_asset="BERA",
                fee_amount_raw=21_000_002_730_000,
            ),
            _row(
                tx_hash="0xlstunstake",
                asset="BERA",
                direction="in",
                token_address=None,
                from_address=_REGISTRY_MEMBER_RECIPIENT,  # the vault
                to_address=_WALLET,
                amount_raw=5 * 10**18,
                fee_asset=None,
                fee_amount_raw=None,
            ),
        ]
        processor = _processor(position_registry=_position_registry())

        txs = processor.process(rows)

        assert len(txs) == 1
        events = _events(txs[0])
        assert len(events) == 1
        assert events[0].event_type is EventType.LiquidityWithdraw
        assert events[0].sub_type is SubType.internal_transfer
        assert {leg.direction for leg in events[0].legs} == {"in", "out"}

    def test_lst_dex_swap_stays_swap(self) -> None:
        # An LST exchanged on a DEX pair: the out-leg LST goes to the pair
        # contract and the in-leg BERA comes from the SAME pair (the
        # counterparty match holds) - but the recipient is NOT a registry
        # vault, so this stays the pre-existing Swap. Pins the LBGT
        # provenance rule: registry entries are identity data, not
        # per-cluster rules (a counterparty-match-only design would misroute
        # this to LiquidityWithdraw).
        rows = [
            _row(
                tx_hash="0xlstdex",
                asset="iTEST",
                direction="out",
                token_address=_POSITION_TOKEN,  # registry member, kind="lst"
                from_address=_WALLET,
                to_address=_DEX_PAIR,  # NOT a registry vault
                amount_raw=1476177230747713290,
                fee_asset="BERA",
                fee_amount_raw=21_000_002_730_000,
            ),
            _row(
                tx_hash="0xlstdex",
                asset="BERA",
                direction="in",
                token_address=None,
                from_address=_DEX_PAIR,  # == the out-leg recipient
                to_address=_WALLET,
                amount_raw=5 * 10**18,
                fee_asset=None,
                fee_amount_raw=None,
            ),
        ]
        processor = _processor(position_registry=_position_registry())

        txs = processor.process(rows)

        assert len(txs) == 1
        events = _events(txs[0])
        assert len(events) == 1
        assert events[0].event_type is EventType.Swap
        assert events[0].sub_type is None

    # ------------------------------------------------------------------
    # Plan 2026-08-24 Task 4: classifier behavior with visible ERC-721
    # position legs (the nfttx fetch makes the position-NFT mint/burn legs
    # visible; membership and vault-target checks key on token_address
    # ONLY - the ``SYMBOL#tokenID`` asset name is display-only).
    # ------------------------------------------------------------------

    def test_deposit_with_position_nft_in_leg_classifies_liquidity_deposit(
        self,
    ) -> None:
        # RED on HEAD: the now-visible bidirectional shape (out WBERA to the
        # vault, in the ERC-721 position mint) reaches the plain Swap branch
        # because the receive-side detector only knows LP-snapshot members.
        # It must classify LiquidityDeposit, not regress from today's
        # registry-member-recipient inference (which read this tx as a PURE
        # outflow deposit while the mint leg was invisible).
        rows = [
            _row(
                tx_hash="0xposdep",
                asset="WBERA",
                direction="out",
                token_address=_WBERA,
                from_address=_WALLET,
                to_address=_REGISTRY_MEMBER_RECIPIENT,  # the position-NFT vault
                amount_raw=10**18,
                fee_asset="BERA",
                fee_amount_raw=21_000_002_730_000,
            ),
            _row(
                tx_hash="0xposdep",
                asset="ALGB-POS#26874",
                direction="in",
                token_address=_POSITION_NFT,  # registry member by ADDRESS
                from_address=_REGISTRY_MEMBER_RECIPIENT,
                to_address=_WALLET,
                amount_raw=1,
                amount_decimals=0,
                fee_asset=None,
                fee_amount_raw=None,
            ),
        ]
        processor = _processor(position_registry=_position_registry())

        txs = processor.process(rows)

        assert len(txs) == 1
        events = _events(txs[0])
        assert len(events) == 1
        assert events[0].event_type is EventType.LiquidityDeposit
        assert events[0].sub_type is SubType.internal_transfer
        assert {leg.direction for leg in events[0].legs} == {"in", "out"}

    def test_withdraw_of_position_nft_to_vault_target_classifies_liquidity_withdraw(
        self,
    ) -> None:
        # The ERC-721 position leg sent to a registry VAULT
        # (kind="position_nft") with the underlying coming back: the
        # shape-6 registry-only vault-target rule must keep firing now that
        # the leg is VISIBLE (previously the invisible leg left a pure
        # WBERA inflow -> Reward misroute). Regression pin.
        rows = [
            _row(
                tx_hash="0xposwd",
                asset="ALGB-POS#26874",
                direction="out",
                token_address=_POSITION_NFT,  # registry member by ADDRESS
                from_address=_WALLET,
                to_address=_REGISTRY_MEMBER_RECIPIENT,  # registry VAULT target
                amount_raw=1,
                amount_decimals=0,
                fee_asset="BERA",
                fee_amount_raw=21_000_002_730_000,
            ),
            _row(
                tx_hash="0xposwd",
                asset="WBERA",
                direction="in",
                token_address=_WBERA,
                from_address=_REGISTRY_MEMBER_RECIPIENT,  # the vault
                to_address=_WALLET,
                amount_raw=5 * 10**18,
                fee_asset=None,
                fee_amount_raw=None,
            ),
        ]
        processor = _processor(position_registry=_position_registry())

        txs = processor.process(rows)

        assert len(txs) == 1
        events = _events(txs[0])
        assert len(events) == 1
        assert events[0].event_type is EventType.LiquidityWithdraw
        assert events[0].sub_type is SubType.internal_transfer
        assert {leg.direction for leg in events[0].legs} == {"in", "out"}

    def test_position_nft_swapped_outside_vault_stays_swap(self) -> None:
        # LBGT-family invariant (user-confirmed 2026-08-23): an ERC-721
        # position leg exchanged on a DEX pair (NOT a registry vault) keeps
        # the Swap fall-through - registry entries are identity data, not
        # per-cluster rules. Pins that the deposit-side extension never
        # fires on the SEND side.
        rows = [
            _row(
                tx_hash="0xposdex",
                asset="ALGB-POS#26874",
                direction="out",
                token_address=_POSITION_NFT,  # registry member by ADDRESS
                from_address=_WALLET,
                to_address=_DEX_PAIR,  # NOT a registry vault
                amount_raw=1,
                amount_decimals=0,
                fee_asset="BERA",
                fee_amount_raw=21_000_002_730_000,
            ),
            _row(
                tx_hash="0xposdex",
                asset="WBERA",
                direction="in",
                token_address=_WBERA,
                from_address=_DEX_PAIR,  # == the out-leg recipient
                to_address=_WALLET,
                amount_raw=5 * 10**18,
                fee_asset=None,
                fee_amount_raw=None,
            ),
        ]
        processor = _processor(position_registry=_position_registry())

        txs = processor.process(rows)

        assert len(txs) == 1
        events = _events(txs[0])
        assert len(events) == 1
        assert events[0].event_type is EventType.Swap
        assert events[0].sub_type is None

    def test_lst_kind_receive_on_dex_swap_stays_swap(self) -> None:
        # Review r2 F1: a bidirectional DEX PURCHASE of a registered LST
        # (out WBERA to the pair, in the lst-kind member) must stay Swap -
        # the LBGT invariant (registry entries are identity data, not
        # per-cluster rules) applied to the RECEIVE side. RED on HEAD: the
        # ungated membership detector misroutes this to
        # LiquidityDeposit/internal_transfer (shape 7 fires before Swap).
        rows = [
            _row(
                tx_hash="0xlstbuy",
                asset="WBERA",
                direction="out",
                token_address=_WBERA,
                from_address=_WALLET,
                to_address=_DEX_PAIR,  # NOT a registry vault
                amount_raw=5 * 10**18,
                fee_asset="BERA",
                fee_amount_raw=21_000_002_730_000,
            ),
            _row(
                tx_hash="0xlstbuy",
                asset="iTEST",
                direction="in",
                token_address=_POSITION_TOKEN,  # registry member, kind="lst"
                from_address=_DEX_PAIR,
                to_address=_WALLET,
                amount_raw=1476177230747713290,
                fee_asset=None,
                fee_amount_raw=None,
            ),
        ]
        processor = _processor(position_registry=_position_registry())

        txs = processor.process(rows)

        assert len(txs) == 1
        events = _events(txs[0])
        assert len(events) == 1
        assert events[0].event_type is EventType.Swap
        assert events[0].sub_type is None

    def test_position_nft_bought_on_dex_stays_swap(self) -> None:
        # Review r3 F1: a bidirectional market PURCHASE of a position NFT
        # (out WBERA to a non-vault pair, in the position_nft-kind member
        # from that pair) must stay Swap - the LBGT invariant (user-confirmed
        # 2026-08-23; registry entries are identity data, not per-cluster
        # rules) mirrored to the RECEIVE side, exactly as the send side
        # (test_position_nft_swapped_outside_vault_stays_swap) and the
        # lst-kind receive side (test_lst_kind_receive_on_dex_swap_stays_swap)
        # already pin. The clean LiquidityDeposit fires only when the
        # economic out-legs target a registry vault (the mint shape the
        # plan's deposit fixture encodes).
        rows = [
            _row(
                tx_hash="0xposbuy",
                asset="WBERA",
                direction="out",
                token_address=_WBERA,
                from_address=_WALLET,
                to_address=_DEX_PAIR,  # NOT a registry vault
                amount_raw=5 * 10**18,
                fee_asset="BERA",
                fee_amount_raw=21_000_002_730_000,
            ),
            _row(
                tx_hash="0xposbuy",
                asset="ALGB-POS#26874",
                direction="in",
                token_address=_POSITION_NFT,  # registry member, kind="position_nft"
                from_address=_DEX_PAIR,  # == the out-leg recipient
                to_address=_WALLET,
                amount_raw=1,
                amount_decimals=0,
                fee_asset=None,
                fee_amount_raw=None,
            ),
        ]
        processor = _processor(position_registry=_position_registry())

        txs = processor.process(rows)

        assert len(txs) == 1
        events = _events(txs[0])
        assert len(events) == 1
        assert events[0].event_type is EventType.Swap
        assert events[0].sub_type is None

    def test_router_mediated_position_nft_mint_is_liquidity_deposit(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Review r4 F1: a router/zapper-mediated mint deposit - the wallet
        # pays an intermediary (a NON-vault router), and the position NFT
        # still arrives FROM the registry vault - is a LiquidityDeposit, not
        # a Swap. The mint's provenance touchpoint (the vault dispatching
        # the NFT) is recognized in addition to the payment touchpoint
        # (out-legs targeting the vault). RED on HEAD: the out-leg-only
        # discriminator misses the vault and the tx classifies as an
        # unflagged Swap.
        # Review r5 F1: the provenance-only shape is ambiguous with a
        # vault-seller resale, so the LiquidityDeposit carries a review flag
        # with an actionable reason naming the vault-sender and the
        # non-vault payment counterparty (PT-C-030 family).
        rows = [
            _row(
                tx_hash="0xzapper",
                asset="WBERA",
                direction="out",
                token_address=_WBERA,
                from_address=_WALLET,
                to_address=_DEX_PAIR,  # the router/zapper - NOT a registry vault
                amount_raw=5 * 10**18,
                fee_asset="BERA",
                fee_amount_raw=21_000_002_730_000,
            ),
            _row(
                tx_hash="0xzapper",
                asset="ALGB-POS#26874",
                direction="in",
                token_address=_POSITION_NFT,  # registry member, kind="position_nft"
                from_address=_REGISTRY_MEMBER_RECIPIENT,  # the vault dispatching the mint
                to_address=_WALLET,
                amount_raw=1,
                amount_decimals=0,
                fee_asset=None,
                fee_amount_raw=None,
            ),
        ]
        processor = _processor(position_registry=_position_registry())

        with caplog.at_level(logging.WARNING, logger=BerachainProcessor.__module__):
            txs = processor.process(rows)

        assert len(txs) == 1
        events = _events(txs[0])
        assert len(events) == 1
        assert events[0].event_type is EventType.LiquidityDeposit
        assert events[0].sub_type is SubType.internal_transfer
        assert {leg.direction for leg in events[0].legs} == {"in", "out"}
        # Provenance-only mint shape: ambiguous with a vault-seller resale,
        # so the classification must carry a review flag naming the
        # vault-sender and the non-vault payment counterparty.
        review_msgs = _review_messages(caplog)
        assert review_msgs, "provenance-only mint must carry a review flag"
        assert _DEX_PAIR.lower() in review_msgs[0].lower()
        assert _REGISTRY_MEMBER_RECIPIENT.lower() in review_msgs[0].lower()
        # Review r6 F1: the reason must also PERSIST on the Event (the log
        # alone is not a user-facing surface; PT-C-030 family).
        reason = events[0].review_reason
        assert reason is not None, (
            "r6 F1: the provenance-only mint's review reason must persist on the Event"
        )
        assert _DEX_PAIR.lower() in reason.lower()
        assert _REGISTRY_MEMBER_RECIPIENT.lower() in reason.lower()
        assert "verify" in reason.lower()

    def test_vault_seller_resale_classifies_deposit_with_review(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Review r5 F1 RED test: a secondary-market purchase where the vault
        # itself is the NFT transfer-from (escrow release, liquidated
        # position resale) while the payment goes to a non-vault marketplace
        # escrow. On-chain this is indistinguishable from a router-mediated
        # mint (both have vault provenance and non-vault payment), so the
        # Type stays LiquidityDeposit but the event must carry a review
        # flag with an actionable reason naming the vault-sender and the
        # non-vault payment counterparty. RED on HEAD: the provenance arm
        # alone vouches for the whole tx, classifying it review-free.
        rows = [
            _row(
                tx_hash="0xresale",
                asset="WBERA",
                direction="out",
                token_address=_WBERA,
                from_address=_WALLET,
                to_address=_DEX_PAIR,  # marketplace escrow - NOT a registry vault
                amount_raw=5 * 10**18,
                fee_asset="BERA",
                fee_amount_raw=21_000_002_730_000,
            ),
            _row(
                tx_hash="0xresale",
                asset="ALGB-POS#26874",
                direction="in",
                token_address=_POSITION_NFT,  # registry member, kind="position_nft"
                from_address=_REGISTRY_MEMBER_RECIPIENT,  # the vault re-selling the position
                to_address=_WALLET,
                amount_raw=1,
                amount_decimals=0,
                fee_asset=None,
                fee_amount_raw=None,
            ),
        ]
        processor = _processor(position_registry=_position_registry())

        with caplog.at_level(logging.WARNING, logger=BerachainProcessor.__module__):
            txs = processor.process(rows)

        assert len(txs) == 1
        events = _events(txs[0])
        assert len(events) == 1
        assert events[0].event_type is EventType.LiquidityDeposit
        assert events[0].sub_type is SubType.internal_transfer
        review_msgs = _review_messages(caplog)
        assert review_msgs, "vault-seller resale must carry a review flag"
        assert _DEX_PAIR.lower() in review_msgs[0].lower()
        assert _REGISTRY_MEMBER_RECIPIENT.lower() in review_msgs[0].lower()

    def test_mixed_provenance_position_batch_classifies_deposit_with_review(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Review r5 F1 RED test: a mixed-provenance batch - one position-NFT
        # in-leg minted from the vault plus a sibling position-NFT in-leg
        # purchased from a DEX pair in the same tx, all payments non-vault.
        # On HEAD the single vault-provenanced leg vouches for the whole tx
        # (review-free LiquidityDeposit); one vault leg must not silently
        # clean a sibling market-purchased leg, so the event must carry a
        # review flag.
        rows = [
            _row(
                tx_hash="0xmixbatch",
                asset="WBERA",
                direction="out",
                token_address=_WBERA,
                from_address=_WALLET,
                to_address=_DEX_PAIR,  # NOT a registry vault
                amount_raw=5 * 10**18,
                fee_asset="BERA",
                fee_amount_raw=21_000_002_730_000,
            ),
            _row(
                tx_hash="0xmixbatch",
                asset="ALGB-POS#26874",
                direction="in",
                token_address=_POSITION_NFT,  # registry member, kind="position_nft"
                from_address=_REGISTRY_MEMBER_RECIPIENT,  # the vault (mint provenance)
                to_address=_WALLET,
                amount_raw=1,
                amount_decimals=0,
                fee_asset=None,
                fee_amount_raw=None,
            ),
            _row(
                tx_hash="0xmixbatch",
                asset="ALGB-POS#26870",
                direction="in",
                token_address=_POSITION_NFT,  # same registry member contract
                from_address=_DEX_PAIR,  # market purchase (non-vault provenance)
                to_address=_WALLET,
                amount_raw=1,
                amount_decimals=0,
                fee_asset=None,
                fee_amount_raw=None,
            ),
        ]
        processor = _processor(position_registry=_position_registry())

        with caplog.at_level(logging.WARNING, logger=BerachainProcessor.__module__):
            txs = processor.process(rows)

        assert len(txs) == 1
        events = _events(txs[0])
        assert len(events) == 1
        assert events[0].event_type is EventType.LiquidityDeposit
        assert events[0].sub_type is SubType.internal_transfer
        assert {leg.direction for leg in events[0].legs} == {"in", "out"}
        assert len(events[0].legs) == 3
        review_msgs = _review_messages(caplog)
        assert review_msgs, "mixed-provenance batch must carry a review flag"
        assert _DEX_PAIR.lower() in review_msgs[0].lower()
        assert _REGISTRY_MEMBER_RECIPIENT.lower() in review_msgs[0].lower()

    # ------------------------------------------------------------------
    # Direct unit tests for the position-leg detector helpers (AGENTS.md:
    # extracted helpers need direct unit tests, not just indirect
    # integration).
    # ------------------------------------------------------------------

    def test_receives_position_token_member_by_address(self) -> None:
        # Membership is keyed on token_address ONLY: an in-leg carrying the
        # registry-member ERC-721 contract address is detected regardless
        # of the display asset name.
        processor = _processor(position_registry=_position_registry())
        leg = Leg(
            asset="ALGB-POS#26874",
            token_address=_POSITION_NFT,
            amount_raw=1,
            amount_decimals=0,
            direction="in",
            from_address=_REGISTRY_MEMBER_RECIPIENT,
            to_address=_WALLET,
        )

        assert processor._receives_position_token([leg]) is True

    def test_receives_position_token_lst_kind_false(self) -> None:
        # Review r2 F1: an lst-kind member (a tradable staking receipt
        # token) must NOT fire the receive-side position detector - only
        # position-NFT-kind members (ERC-721 LP position mints) do. An
        # ungated membership check here misroutes DEX LST buys to
        # LiquidityDeposit.
        processor = _processor(position_registry=_position_registry())
        lst_leg = Leg(
            asset="iTEST",
            token_address=_POSITION_TOKEN,  # registry member, kind="lst"
            amount_raw=1476177230747713290,
            amount_decimals=18,
            direction="in",
            from_address=_DEX_PAIR,
            to_address=_WALLET,
        )

        assert processor._receives_position_token([lst_leg]) is False

    def test_receives_position_token_non_member_and_native_false(self) -> None:
        # A non-member token and a native leg (token_address None) never
        # fire the detector.
        processor = _processor(position_registry=_position_registry())
        non_member = Leg(
            asset="HONEY",
            token_address=_WBERA,
            amount_raw=10**18,
            amount_decimals=18,
            direction="in",
            from_address=_DEX_ROUTER,
            to_address=_WALLET,
        )
        native = replace(non_member, asset="BERA", token_address=None)

        assert processor._receives_position_token([non_member]) is False
        assert processor._receives_position_token([native]) is False

    def test_receives_position_token_absent_registry_false(self) -> None:
        # No position registry loaded -> the detector is inert (fail-closed;
        # the classifier falls through to the pre-existing shapes).
        processor = _processor()
        leg = Leg(
            asset="ALGB-POS#26874",
            token_address=_POSITION_NFT,
            amount_raw=1,
            amount_decimals=0,
            direction="in",
            from_address=_REGISTRY_MEMBER_RECIPIENT,
            to_address=_WALLET,
        )

        assert processor._receives_position_token([leg]) is False

    def test_receives_member_receipt_token_combines_lp_and_position(self) -> None:
        # The shape-7 detector accepts EITHER signal: an LP-snapshot member
        # in-leg OR a position-registry member in-leg whose economic
        # out-legs target a registry vault (review r3 F1: the mint shape).
        processor = _processor(position_registry=_position_registry())
        lp_leg = Leg(
            asset="UNI-V2",
            token_address=_LP_TOKEN,  # LP-snapshot member
            amount_raw=5 * 10**18,
            amount_decimals=18,
            direction="in",
            from_address=_DEX_ROUTER,
            to_address=_WALLET,
        )
        pos_leg = Leg(
            asset="ALGB-POS#26874",
            token_address=_POSITION_NFT,  # position-registry member
            amount_raw=1,
            amount_decimals=0,
            direction="in",
            from_address=_REGISTRY_MEMBER_RECIPIENT,
            to_address=_WALLET,
        )
        plain_leg = Leg(
            asset="HONEY",
            token_address=_WBERA,
            amount_raw=10**18,
            amount_decimals=18,
            direction="in",
            from_address=_DEX_ROUTER,
            to_address=_WALLET,
        )
        vault_pay_leg = Leg(
            asset="WBERA",
            token_address=_WBERA,
            amount_raw=5 * 10**18,
            amount_decimals=18,
            direction="out",
            from_address=_WALLET,
            to_address=_REGISTRY_MEMBER_RECIPIENT,  # registry vault
        )
        nonvault_pay_leg = replace(vault_pay_leg, to_address=_DEX_PAIR)

        # LP signal needs no vault-target discriminator; the position-NFT
        # signal additionally requires the mint shape (either an out-leg
        # pays the vault, r3 F1, or the NFT arrives from the vault, r4 F1).
        assert processor._receives_member_receipt_token([lp_leg], [nonvault_pay_leg]) is True
        assert processor._receives_member_receipt_token([pos_leg], [vault_pay_leg]) is True
        # Review r4 F1: a position-NFT receive whose NFT arrives FROM the
        # vault fires even when the payer is a non-vault router (the
        # router-mediated mint shape).
        assert processor._receives_member_receipt_token([pos_leg], [nonvault_pay_leg]) is True
        assert processor._receives_member_receipt_token([plain_leg], [vault_pay_leg]) is False

    def test_position_mint_pays_vault_out_leg_payment_true(self) -> None:
        # Direct unit test for the PAYMENT arm: an economic out-leg whose
        # recipient is a position_nft-kind registry member (the vault the
        # mint deposit pays) fires the arm.
        processor = _processor(position_registry=_position_registry())
        leg = Leg(
            asset="WBERA",
            token_address=_WBERA,
            amount_raw=5 * 10**18,
            amount_decimals=18,
            direction="out",
            from_address=_WALLET,
            to_address=_REGISTRY_MEMBER_RECIPIENT,  # kind="position_nft" member
        )

        assert processor._position_mint_pays_vault([leg]) is True

    def test_position_mint_pays_vault_nonvault_or_native_false(self) -> None:
        # A non-vault recipient (DEX pair), a native leg (to_address None),
        # and an absent registry never fire the payment arm (fail-closed).
        member = _processor(position_registry=_position_registry())
        pair_leg = Leg(
            asset="WBERA",
            token_address=_WBERA,
            amount_raw=5 * 10**18,
            amount_decimals=18,
            direction="out",
            from_address=_WALLET,
            to_address=_DEX_PAIR,
        )
        native_leg = replace(pair_leg, asset="BERA", token_address=None, to_address=None)

        assert member._position_mint_pays_vault([pair_leg]) is False
        assert member._position_mint_pays_vault([native_leg]) is False
        assert member._position_mint_pays_vault([]) is False

        no_registry = _processor()
        vault_leg = replace(pair_leg, to_address=_REGISTRY_MEMBER_RECIPIENT)
        assert no_registry._position_mint_pays_vault([vault_leg]) is False

    def test_position_mint_receives_from_vault_provenance_true(self) -> None:
        # Direct unit test for the PROVENANCE arm: a kind-gated
        # position-NFT in-leg whose from_address is a registry vault fires
        # the arm even when no out-leg pays the vault (the router-mediated
        # mint shape).
        processor = _processor(position_registry=_position_registry())
        pos_leg = Leg(
            asset="ALGB-POS#26874",
            token_address=_POSITION_NFT,  # kind="position_nft" member
            amount_raw=1,
            amount_decimals=0,
            direction="in",
            from_address=_REGISTRY_MEMBER_RECIPIENT,  # the vault dispatching the mint
            to_address=_WALLET,
        )

        assert processor._position_mint_receives_from_vault([pos_leg]) is True

    def test_position_mint_receives_from_vault_kind_and_sender_gated_false(self) -> None:
        # The provenance arm is kind-gated (an lst-kind in-leg from a vault
        # never fires) and sender-gated (an NFT in-leg from a non-vault pair
        # never fires); an absent registry is inert (fail-closed).
        member = _processor(position_registry=_position_registry())
        pos_from_pair = Leg(
            asset="ALGB-POS#26874",
            token_address=_POSITION_NFT,
            amount_raw=1,
            amount_decimals=0,
            direction="in",
            from_address=_DEX_PAIR,  # NOT a vault
            to_address=_WALLET,
        )
        lst_from_vault = Leg(
            asset="iTEST",
            token_address=_POSITION_TOKEN,  # kind="lst": not kind-gated
            amount_raw=1476177230747713290,
            amount_decimals=18,
            direction="in",
            from_address=_REGISTRY_MEMBER_RECIPIENT,
            to_address=_WALLET,
        )

        assert member._position_mint_receives_from_vault([pos_from_pair]) is False
        assert member._position_mint_receives_from_vault([lst_from_vault]) is False
        assert member._position_mint_receives_from_vault([]) is False

        no_registry = _processor()
        pos_from_vault = replace(pos_from_pair, from_address=_REGISTRY_MEMBER_RECIPIENT)
        assert no_registry._position_mint_receives_from_vault([pos_from_vault]) is False

    def test_position_mint_vault_senders_returns_sender_set(self) -> None:
        # Review r6 F4: the shared set-returning helper behind the
        # receives-from-vault detector AND the provenance reason builder (the
        # arm evaluation exists in exactly one body). Direct unit test: the
        # set names the (lower-cased) vault senders and stays empty for the
        # gated-out shapes and the absent-registry case.
        processor = _processor(position_registry=_position_registry())
        pos_from_vault = Leg(
            asset="ALGB-POS#26874",
            token_address=_POSITION_NFT,
            amount_raw=1,
            amount_decimals=0,
            direction="in",
            from_address=_REGISTRY_MEMBER_RECIPIENT,
            to_address=_WALLET,
        )
        pos_from_pair = replace(pos_from_vault, from_address=_DEX_PAIR)
        lst_from_vault = replace(pos_from_vault, asset="iTEST", token_address=_POSITION_TOKEN)

        assert processor._position_mint_vault_senders([pos_from_vault]) == {
            _REGISTRY_MEMBER_RECIPIENT.lower()
        }
        assert processor._position_mint_vault_senders([pos_from_pair, lst_from_vault]) == set()
        assert _processor()._position_mint_vault_senders([pos_from_vault]) == set()

    def test_position_mint_provenance_review_reason_naming(self) -> None:
        # Direct unit test for the ambiguity reason builder: None when the
        # payment arm fires (clean deposit) or neither arm fires; a reason
        # naming the vault-sender leg(s) and the non-vault payment
        # counterparties when only the provenance arm fires.
        processor = _processor(position_registry=_position_registry())
        vault_pay = Leg(
            asset="WBERA",
            token_address=_WBERA,
            amount_raw=5 * 10**18,
            amount_decimals=18,
            direction="out",
            from_address=_WALLET,
            to_address=_REGISTRY_MEMBER_RECIPIENT,  # registry vault
        )
        nonvault_pay = replace(vault_pay, to_address=_DEX_PAIR)
        pos_from_vault = Leg(
            asset="ALGB-POS#26874",
            token_address=_POSITION_NFT,
            amount_raw=1,
            amount_decimals=0,
            direction="in",
            from_address=_REGISTRY_MEMBER_RECIPIENT,
            to_address=_WALLET,
        )
        pos_from_pair = replace(pos_from_vault, from_address=_DEX_PAIR)

        # Payment arm fires -> clean (no reason).
        assert (
            processor._position_mint_provenance_review_reason([vault_pay], [pos_from_vault])
            is None
        )
        # Neither arm -> no reason.
        assert (
            processor._position_mint_provenance_review_reason([nonvault_pay], [pos_from_pair])
            is None
        )
        # Provenance-only -> actionable reason naming both counterparties.
        reason = processor._position_mint_provenance_review_reason(
            [nonvault_pay], [pos_from_vault]
        )
        assert reason is not None
        assert _REGISTRY_MEMBER_RECIPIENT.lower() in reason.lower()
        assert _DEX_PAIR.lower() in reason.lower()
        assert "verify" in reason.lower()
        # Review r6 F3: a NATIVE gas out-leg carries ``to_address=None``; the
        # payee list must degrade to the "<missing>" sentinel, not crash or
        # emit a raw None into the user-facing reason.
        native_pay = replace(vault_pay, asset="BERA", token_address=None, to_address=None)
        native_reason = processor._position_mint_provenance_review_reason(
            [native_pay], [pos_from_vault]
        )
        assert native_reason is not None
        assert "<missing>" in native_reason

    def test_lst_send_to_nonvault_recipient_falls_through(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # An LST member out-leg to a non-vault, non-pair recipient with an
        # unrelated in-leg (counterparties differ): the registry-only gate
        # does not fire outside the vault target, so the tx falls through to
        # Swap, and NO shape-6 review warning is emitted (the review path is
        # LP-snapshot-only).
        rows = [
            _row(
                tx_hash="0xlstsend",
                asset="iTEST",
                direction="out",
                token_address=_POSITION_TOKEN,
                from_address=_WALLET,
                to_address=_NONVAULT_RECIPIENT,  # not a vault, not the in-leg sender
                amount_raw=1476177230747713290,
                fee_asset="BERA",
                fee_amount_raw=21_000_002_730_000,
            ),
            _row(
                tx_hash="0xlstsend",
                asset="BERA",
                direction="in",
                token_address=None,
                from_address=_DEX_ROUTER,
                to_address=_WALLET,
                amount_raw=5 * 10**18,
                fee_asset=None,
                fee_amount_raw=None,
            ),
        ]
        processor = _processor(position_registry=_position_registry())

        with caplog.at_level(logging.WARNING, logger=BerachainProcessor.__module__):
            txs = processor.process(rows)

        assert len(txs) == 1
        events = _events(txs[0])
        assert len(events) == 1
        assert events[0].event_type is EventType.Swap
        assert not _review_messages(caplog), "the shape-6 review path is LP-snapshot-only; no warning here"

    def test_native_leg_never_member(self) -> None:
        # Address-keyed identity invariant: a native-asset out-leg
        # (token_address is None) is never a member token, so a
        # bidirectional native exchange stays the pre-existing Swap.
        rows = [
            _row(
                tx_hash="0xnativeswap",
                asset="BERA",
                direction="out",
                token_address=None,  # native: never a member
                from_address=_WALLET,
                to_address=_DEX_ROUTER,
                amount_raw=10**18,
                fee_asset="BERA",
                fee_amount_raw=21_000_002_730_000,
            ),
            _row(
                tx_hash="0xnativeswap",
                asset="HONEY",
                direction="in",
                token_address="0x000000000000000000000000000000000000abcd",
                from_address=_DEX_ROUTER,
                to_address=_WALLET,
                amount_raw=42 * 10**18,
                fee_asset=None,
                fee_amount_raw=None,
            ),
        ]
        processor = _processor(position_registry=_position_registry())

        txs = processor.process(rows)

        assert len(txs) == 1
        events = _events(txs[0])
        assert len(events) == 1
        assert events[0].event_type is EventType.Swap
        assert events[0].sub_type is None

    # -- Review r1 follow-ups (code review 2026-08-24, F2-F5, F13) --------

    def test_mixed_batch_lp_member_legs_review_flagged(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Review r1 F2: a batched withdraw with TWO LP-member out-legs - one
        # genuine unstake leg (recipient == an in-leg sender) plus one sale
        # leg to a buyer - must NOT classify clean. EVERY member out-leg
        # recipient must be covered; the uncovered buyer leg keeps the review
        # WARNING naming it (ANY-match would silently clean the sale).
        rows = [
            _row(
                tx_hash="0xbatchunstake",
                asset="KODI-ISLAND",
                direction="out",
                token_address=_LP_TOKEN,
                from_address=_WALLET,
                to_address=_REGISTRY_MEMBER_RECIPIENT,  # covered by the in-leg sender
                amount_raw=2 * 10**18,
                fee_asset="BERA",
                fee_amount_raw=21_000_002_730_000,
            ),
            _row(
                tx_hash="0xbatchunstake",
                asset="KODI-ISLAND",
                direction="out",
                token_address=_LP_TOKEN,
                from_address=_WALLET,
                to_address=_LP_BUYER,  # NOT covered: a third-party sale leg
                amount_raw=2 * 10**18,
                fee_asset=None,
                fee_amount_raw=None,
            ),
            _row(
                tx_hash="0xbatchunstake",
                asset="BERA",
                direction="in",
                token_address=None,
                from_address=_REGISTRY_MEMBER_RECIPIENT,
                to_address=_WALLET,
                amount_raw=5 * 10**18,
                fee_asset=None,
                fee_amount_raw=None,
            ),
        ]
        processor = _processor(position_registry=_position_registry())

        with caplog.at_level(logging.WARNING, logger=BerachainProcessor.__module__):
            txs = processor.process(rows)

        assert len(txs) == 1
        events = _events(txs[0])
        assert len(events) == 1
        assert events[0].event_type is EventType.LiquidityWithdraw
        review_msgs = _review_messages(caplog)
        assert review_msgs, "uncovered member out-leg in a batch must carry a review flag"
        msg = review_msgs[0]
        assert _LP_BUYER in msg, "the WARNING must name the uncovered buyer recipient"
        assert "received no matching" in msg
        # Review r2 F6: the COVERED unstake recipient must not appear in the
        # unmatched-recipient portion of the reason (it legitimately shows up
        # in the parenthetical in-leg senders list). Review r3 F2: parse the
        # structured unmatched list between "recipient(s) " and " received"
        # instead of splitting on the parenthetical wording, so a harmless
        # rewording cannot spuriously fail the exclusion assertion.
        unmatched_part = msg.split("recipient(s) ", 1)[1].split(" received", 1)[0]
        assert _REGISTRY_MEMBER_RECIPIENT.lower() not in unmatched_part, (
            "the COVERED unstake recipient must NOT be named among the unmatched"
        )

    @pytest.mark.parametrize(
        ("in_from", "out_to"),
        [
            pytest.param(None, _LP_BUYER, id="missing-in-leg-sender"),
            pytest.param(_DEX_ROUTER, "", id="missing-out-leg-recipient"),
            pytest.param(_DEX_ROUTER, None, id="null-out-leg-recipient"),
            # Review r2 F2: a hand-edited CSV cell holding the literal
            # sentinel marker must not spoof coverage of a missing recipient.
            pytest.param("<missing>", "", id="sentinel-spoofed-in-leg-sender"),
        ],
    )
    def test_missing_address_fails_closed_into_review(
        self,
        caplog: pytest.LogCaptureFixture,
        in_from: str | None,
        out_to: str | None,
    ) -> None:
        # Review r1 F3: the empty-string address sentinel must not
        # self-collide into a clean match. A missing in-leg sender cannot
        # cover anything, and a missing member out-leg recipient (empty OR
        # None) is never coverable - both fail closed into the review branch.
        rows = [
            _row(
                tx_hash="0xmissingaddr",
                asset="KODI-ISLAND",
                direction="out",
                token_address=_LP_TOKEN,
                from_address=_WALLET,
                to_address=out_to,  # type: ignore[arg-type]
                amount_raw=4 * 10**18,
                fee_asset="BERA",
                fee_amount_raw=21_000_002_730_000,
            ),
            _row(
                tx_hash="0xmissingaddr",
                asset="BERA",
                direction="in",
                token_address=None,
                from_address=in_from,  # type: ignore[arg-type]
                to_address=_WALLET,
                amount_raw=5 * 10**18,
                fee_asset=None,
                fee_amount_raw=None,
            ),
        ]
        processor = _processor()

        with caplog.at_level(logging.WARNING, logger=BerachainProcessor.__module__):
            txs = processor.process(rows)

        assert len(txs) == 1
        events = _events(txs[0])
        assert len(events) == 1
        assert events[0].event_type is EventType.LiquidityWithdraw
        assert _review_messages(caplog), "a missing counterparty address must fail closed into review"
        if not out_to:
            # Review r2 F6: the reason must textually carry the sentinel.
            review_msgs = _review_messages(caplog)
            assert "<missing>" in review_msgs[0], (
                "the WARNING must name the <missing> sentinel for a missing recipient"
            )

    def test_lst_unstake_registry_absent_falls_through_to_swap(self) -> None:
        # Review r1 F4: the registry-only arm of shape 6 requires the
        # position registry to be loaded. Without it, an LST out-leg to a
        # vault-shaped recipient falls through to the pre-existing Swap (a
        # guard regression or a None-registry AttributeError must not ship).
        rows = [
            _row(
                tx_hash="0xlstnoreg",
                asset="iTEST",
                direction="out",
                token_address=_POSITION_TOKEN,
                from_address=_WALLET,
                to_address=_REGISTRY_MEMBER_RECIPIENT,  # vault-shaped target
                amount_raw=1476177230747713290,
                fee_asset="BERA",
                fee_amount_raw=21_000_002_730_000,
            ),
            _row(
                tx_hash="0xlstnoreg",
                asset="BERA",
                direction="in",
                token_address=None,
                from_address=_REGISTRY_MEMBER_RECIPIENT,
                to_address=_WALLET,
                amount_raw=5 * 10**18,
                fee_asset=None,
                fee_amount_raw=None,
            ),
        ]
        processor = _processor()  # NO position registry

        txs = processor.process(rows)

        assert len(txs) == 1
        events = _events(txs[0])
        assert len(events) == 1
        assert events[0].event_type is EventType.Swap
        assert events[0].sub_type is None

    def test_vault_unstake_counterparty_match_case_insensitive(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Review r1 F5: the redemption-counterparty comparison is
        # case-insensitive (Etherscan V2 returns checksummed addresses). A
        # mixed-case out-leg recipient must still match the lowercase in-leg
        # sender and classify clean (a case-sensitive regression would flag
        # real unstakes as disposals).
        rows = [
            _row(
                tx_hash="0xunstakecase",
                asset="KODI-ISLAND",
                direction="out",
                token_address=_LP_TOKEN,
                from_address=_WALLET,
                to_address="0x0000000000000000000000000000000000000E77",  # checksummed form
                amount_raw=4 * 10**18,
                fee_asset="BERA",
                fee_amount_raw=21_000_002_730_000,
            ),
            _row(
                tx_hash="0xunstakecase",
                asset="BERA",
                direction="in",
                token_address=None,
                from_address=_REGISTRY_MEMBER_RECIPIENT,  # lowercase form
                to_address=_WALLET,
                amount_raw=5 * 10**18,
                fee_asset=None,
                fee_amount_raw=None,
            ),
        ]
        processor = _processor(position_registry=_position_registry())

        with caplog.at_level(logging.WARNING, logger=BerachainProcessor.__module__):
            txs = processor.process(rows)

        assert len(txs) == 1
        events = _events(txs[0])
        assert len(events) == 1
        assert events[0].event_type is EventType.LiquidityWithdraw
        assert not _review_messages(caplog), "mixed-case vs lowercase counterparty forms must still match clean"

    def test_lp_out_leg_to_vault_with_router_sender_review_flagged(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Review r1 F13: the mirror mismatch direction - the LP-member
        # out-leg goes TO a known vault address while ALL in-legs come from a
        # DIFFERENT address (a router). The predicate is the set relation
        # between recipients and in-leg senders, not vault membership of the
        # recipient, so this takes the review branch too.
        rows = [
            _row(
                tx_hash="0xvaultmirror",
                asset="KODI-ISLAND",
                direction="out",
                token_address=_LP_TOKEN,
                from_address=_WALLET,
                to_address=_REGISTRY_MEMBER_RECIPIENT,  # a vault address
                amount_raw=4 * 10**18,
                fee_asset="BERA",
                fee_amount_raw=21_000_002_730_000,
            ),
            _row(
                tx_hash="0xvaultmirror",
                asset="BERA",
                direction="in",
                token_address=None,
                from_address=_DEX_ROUTER,  # NOT the vault recipient
                to_address=_WALLET,
                amount_raw=5 * 10**18,
                fee_asset=None,
                fee_amount_raw=None,
            ),
        ]
        processor = _processor(position_registry=_position_registry())

        with caplog.at_level(logging.WARNING, logger=BerachainProcessor.__module__):
            txs = processor.process(rows)

        assert len(txs) == 1
        events = _events(txs[0])
        assert len(events) == 1
        assert events[0].event_type is EventType.LiquidityWithdraw
        assert _review_messages(caplog), "vault recipient with a router sender is still a counterparty mismatch"
        # Review r6 F1: EVERY flagged shape persists its reason on the Event
        # (shape-6 redemption-counterparty mismatch is the second case).
        reason = events[0].review_reason
        assert reason is not None, (
            "r6 F1: the shape-6 redemption review reason must persist on the Event"
        )
        assert "mismatch" in reason.lower()

    # -- Review r2 follow-ups (code review 2026-08-24, F1/F5) --------------

    def test_batch_all_member_legs_covered_extra_sender_clean(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Review r2 F5: the clean twin of the mixed-batch test. Two LP-member
        # out-legs whose recipients (V1, V2) are BOTH covered by in-leg
        # senders, plus one EXTRA in-leg sender (a router forwarding the
        # underlying): a subset check classifies clean LiquidityWithdraw -
        # an exact-set-equality regression would flag legitimate batched
        # unstakes as disposals.
        rows = [
            _row(
                tx_hash="0xbatchclean",
                asset="KODI-ISLAND",
                direction="out",
                token_address=_LP_TOKEN,
                from_address=_WALLET,
                to_address=_REGISTRY_MEMBER_RECIPIENT,  # V1, covered
                amount_raw=2 * 10**18,
                fee_asset="BERA",
                fee_amount_raw=21_000_002_730_000,
            ),
            _row(
                tx_hash="0xbatchclean",
                asset="KODI-ISLAND",
                direction="out",
                token_address=_LP_TOKEN,
                from_address=_WALLET,
                to_address=_DEX_PAIR,  # V2, covered
                amount_raw=2 * 10**18,
                fee_asset=None,
                fee_amount_raw=None,
            ),
            _row(
                tx_hash="0xbatchclean",
                asset="BERA",
                direction="in",
                token_address=None,
                from_address=_REGISTRY_MEMBER_RECIPIENT,  # covers V1
                to_address=_WALLET,
                amount_raw=5 * 10**18,
                fee_asset=None,
                fee_amount_raw=None,
            ),
            _row(
                tx_hash="0xbatchclean",
                asset="BERA",
                direction="in",
                token_address=None,
                from_address=_DEX_PAIR,  # covers V2
                to_address=_WALLET,
                amount_raw=5 * 10**18,
                fee_asset=None,
                fee_amount_raw=None,
            ),
            _row(
                tx_hash="0xbatchclean",
                asset="HONEY",
                direction="in",
                token_address="0x000000000000000000000000000000000000abcd",
                from_address=_DEX_ROUTER,  # extra sender: subset, not equality
                to_address=_WALLET,
                amount_raw=42 * 10**18,
                fee_asset=None,
                fee_amount_raw=None,
            ),
        ]
        processor = _processor(position_registry=_position_registry())

        with caplog.at_level(logging.WARNING, logger=BerachainProcessor.__module__):
            txs = processor.process(rows)

        assert len(txs) == 1
        events = _events(txs[0])
        assert len(events) == 1
        assert events[0].event_type is EventType.LiquidityWithdraw
        assert events[0].sub_type is SubType.internal_transfer
        assert not _review_messages(caplog), (
            "a fully covered batch with an extra in-leg sender must NOT carry a review flag"
        )

    def test_mixed_registry_batch_nonvault_leg_review_flagged(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Review r2 F1: a batched registry-member withdraw with TWO LST
        # out-legs - one genuine vault-target leg plus one leg to a DEX
        # pair - must NOT classify clean. The batch fires LiquidityWithdraw
        # (at least one vault-target leg), and the non-vault leg carries a
        # review WARNING naming its recipient: one vault leg must not
        # silently clean a sibling disposal leg (registry-side mirror of
        # the r1 F2 LP subset rule). The SINGLE-leg LST DEX exchange keeps
        # its Swap fall-through (test_lst_dex_swap_stays_swap): only a
        # batch with a vault-target leg enters this review branch.
        rows = [
            _row(
                tx_hash="0xbatchlst",
                asset="iTEST",
                direction="out",
                token_address=_POSITION_TOKEN,  # registry member, kind="lst"
                from_address=_WALLET,
                to_address=_REGISTRY_MEMBER_RECIPIENT,  # the registry VAULT
                amount_raw=1476177230747713290,
                fee_asset="BERA",
                fee_amount_raw=21_000_002_730_000,
            ),
            _row(
                tx_hash="0xbatchlst",
                asset="iTEST",
                direction="out",
                token_address=_POSITION_TOKEN,
                from_address=_WALLET,
                to_address=_DEX_PAIR,  # NOT a registry vault: a sale leg
                amount_raw=1476177230747713290,
                fee_asset=None,
                fee_amount_raw=None,
            ),
            _row(
                tx_hash="0xbatchlst",
                asset="BERA",
                direction="in",
                token_address=None,
                from_address=_REGISTRY_MEMBER_RECIPIENT,
                to_address=_WALLET,
                amount_raw=5 * 10**18,
                fee_asset=None,
                fee_amount_raw=None,
            ),
        ]
        processor = _processor(position_registry=_position_registry())

        with caplog.at_level(logging.WARNING, logger=BerachainProcessor.__module__):
            txs = processor.process(rows)

        assert len(txs) == 1
        events = _events(txs[0])
        assert len(events) == 1
        assert events[0].event_type is EventType.LiquidityWithdraw
        review_msgs = _review_messages(caplog)
        assert review_msgs, "a registry-member leg to a non-vault in a batch must be flagged"
        msg = review_msgs[0]
        assert _DEX_PAIR.lower() in msg, "the WARNING must name the non-vault DEX recipient"
        assert (
            _REGISTRY_MEMBER_RECIPIENT.lower() not in msg
        ), "the vault-target leg's recipient must NOT be named"
        assert "disposal" in msg

    # -- Review r3 follow-ups (code review 2026-08-24, F1/F2) --------------

    def test_mixed_lp_and_registry_batch_nonvault_registry_leg_review_flagged(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Review r3 F1: branch (a) must not shadow the registry-side review
        # condition. A same-tx mix of a COVERED LP-member out-leg (recipient
        # == an in-leg sender, the subset predicate holds) and a
        # registry-member out-leg to a DEX pair (a non-vault recipient, a
        # possible disposal) must NOT classify clean: the LP branch folds the
        # registry-member legs into its review computation, so every member
        # leg participates regardless of which branch consumes the shape.
        rows = [
            _row(
                tx_hash="0xbatchmix",
                asset="KODI-ISLAND",
                direction="out",
                token_address=_LP_TOKEN,
                from_address=_WALLET,
                to_address=_REGISTRY_MEMBER_RECIPIENT,  # covered by the in-leg sender
                amount_raw=2 * 10**18,
                fee_asset="BERA",
                fee_amount_raw=21_000_002_730_000,
            ),
            _row(
                tx_hash="0xbatchmix",
                asset="iTEST",
                direction="out",
                token_address=_POSITION_TOKEN,  # registry member, kind="lst"
                from_address=_WALLET,
                to_address=_DEX_PAIR,  # NOT a registry vault: a sale leg
                amount_raw=1476177230747713290,
                fee_asset=None,
                fee_amount_raw=None,
            ),
            _row(
                tx_hash="0xbatchmix",
                asset="BERA",
                direction="in",
                token_address=None,
                from_address=_REGISTRY_MEMBER_RECIPIENT,
                to_address=_WALLET,
                amount_raw=5 * 10**18,
                fee_asset=None,
                fee_amount_raw=None,
            ),
        ]
        processor = _processor(position_registry=_position_registry())

        with caplog.at_level(logging.WARNING, logger=BerachainProcessor.__module__):
            txs = processor.process(rows)

        assert len(txs) == 1
        events = _events(txs[0])
        assert len(events) == 1
        assert events[0].event_type is EventType.LiquidityWithdraw
        review_msgs = _review_messages(caplog)
        assert review_msgs, (
            "a covered LP leg must not silently clean a sibling registry-member "
            "disposal leg in a same-tx mix"
        )
        msg = review_msgs[0]
        assert _DEX_PAIR.lower() in msg, (
            "the WARNING must name the non-vault registry-leg DEX recipient"
        )
        assert "registry vault" in msg, (
            "the WARNING must state the registry-leg half of the combined reason"
        )

    def test_mixed_lp_and_registry_batch_all_covered_clean(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # The clean twin of the r3 F1 test: a same-tx LP+registry mix where
        # the LP leg is covered AND the registry-member leg targets the
        # registry VAULT classifies clean LiquidityWithdraw with NO review
        # flag (the folded registry computation must not over-fire).
        rows = [
            _row(
                tx_hash="0xbatchmixclean",
                asset="KODI-ISLAND",
                direction="out",
                token_address=_LP_TOKEN,
                from_address=_WALLET,
                to_address=_REGISTRY_MEMBER_RECIPIENT,  # covered by the in-leg sender
                amount_raw=2 * 10**18,
                fee_asset="BERA",
                fee_amount_raw=21_000_002_730_000,
            ),
            _row(
                tx_hash="0xbatchmixclean",
                asset="iTEST",
                direction="out",
                token_address=_POSITION_TOKEN,  # registry member, kind="lst"
                from_address=_WALLET,
                to_address=_REGISTRY_MEMBER_RECIPIENT,  # the registry VAULT
                amount_raw=1476177230747713290,
                fee_asset=None,
                fee_amount_raw=None,
            ),
            _row(
                tx_hash="0xbatchmixclean",
                asset="BERA",
                direction="in",
                token_address=None,
                from_address=_REGISTRY_MEMBER_RECIPIENT,
                to_address=_WALLET,
                amount_raw=5 * 10**18,
                fee_asset=None,
                fee_amount_raw=None,
            ),
        ]
        processor = _processor(position_registry=_position_registry())

        with caplog.at_level(logging.WARNING, logger=BerachainProcessor.__module__):
            txs = processor.process(rows)

        assert len(txs) == 1
        events = _events(txs[0])
        assert len(events) == 1
        assert events[0].event_type is EventType.LiquidityWithdraw
        assert events[0].sub_type is SubType.internal_transfer
        assert not _review_messages(caplog), "a fully covered LP+registry mix must NOT carry a review flag"

    # -- Review r4 follow-ups (code review 2026-08-24, F1/F2/F3) -----------

    def test_registry_batch_no_vault_leg_falls_through_to_swap(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Review r4 F1: a registry-ONLY batch (TWO registry-member out-legs)
        # with NO vault-target leg must keep the Swap fall-through: the
        # `if registry_vault_legs:` gate is what fires LiquidityWithdraw, so
        # registry_member_legs being nonempty alone must not fire it. Mirrors
        # test_lst_dex_swap_stays_swap with two legs; pins the gate against a
        # regression that would reclassify a two-LST DEX exchange as
        # LiquidityWithdraw with a spurious review flag.
        rows = [
            _row(
                tx_hash="0xbatchnostake",
                asset="iTEST",
                direction="out",
                token_address=_POSITION_TOKEN,  # registry member, kind="lst"
                from_address=_WALLET,
                to_address=_DEX_PAIR,  # NOT a registry vault
                amount_raw=1476177230747713290,
                fee_asset="BERA",
                fee_amount_raw=21_000_002_730_000,
            ),
            _row(
                tx_hash="0xbatchnostake",
                asset="iTEST",
                direction="out",
                token_address=_POSITION_TOKEN,
                from_address=_WALLET,
                to_address=_NONVAULT_RECIPIENT,  # also NOT a registry vault
                amount_raw=1476177230747713290,
                fee_asset=None,
                fee_amount_raw=None,
            ),
            _row(
                tx_hash="0xbatchnostake",
                asset="BERA",
                direction="in",
                token_address=None,
                from_address=_DEX_ROUTER,  # unrelated in-leg sender
                to_address=_WALLET,
                amount_raw=5 * 10**18,
                fee_asset=None,
                fee_amount_raw=None,
            ),
        ]
        processor = _processor(position_registry=_position_registry())

        with caplog.at_level(logging.WARNING, logger=BerachainProcessor.__module__):
            txs = processor.process(rows)

        assert len(txs) == 1
        events = _events(txs[0])
        assert len(events) == 1
        assert events[0].event_type is EventType.Swap
        assert events[0].sub_type is None
        assert not _review_messages(caplog), "a vault-less registry batch must fall through to Swap with NO review flag"

    @pytest.mark.parametrize(
        "nonvault_to",
        [
            pytest.param("", id="empty-nonvault-recipient"),
            pytest.param(None, id="null-nonvault-recipient"),
        ],
    )
    def test_registry_batch_missing_nonvault_recipient_sentinel_named(
        self,
        caplog: pytest.LogCaptureFixture,
        nonvault_to: str | None,
    ) -> None:
        # Review r4 F2: registry-arm mirror of the LP-side
        # test_missing_address_fails_closed_into_review. In a vault-bearing
        # registry batch, the non-vault leg's missing recipient must surface
        # as the "<missing>" sentinel in the review WARNING (never silently
        # dropped by the `(to_address or "<missing>")` fallback regressing).
        rows = [
            _row(
                tx_hash="0xbatchlstmiss",
                asset="iTEST",
                direction="out",
                token_address=_POSITION_TOKEN,  # registry member, kind="lst"
                from_address=_WALLET,
                to_address=_REGISTRY_MEMBER_RECIPIENT,  # the registry VAULT
                amount_raw=1476177230747713290,
                fee_asset="BERA",
                fee_amount_raw=21_000_002_730_000,
            ),
            _row(
                tx_hash="0xbatchlstmiss",
                asset="iTEST",
                direction="out",
                token_address=_POSITION_TOKEN,
                from_address=_WALLET,
                to_address=nonvault_to,  # type: ignore[arg-type]
                amount_raw=1476177230747713290,
                fee_asset=None,
                fee_amount_raw=None,
            ),
            _row(
                tx_hash="0xbatchlstmiss",
                asset="BERA",
                direction="in",
                token_address=None,
                from_address=_REGISTRY_MEMBER_RECIPIENT,
                to_address=_WALLET,
                amount_raw=5 * 10**18,
                fee_asset=None,
                fee_amount_raw=None,
            ),
        ]
        processor = _processor(position_registry=_position_registry())

        with caplog.at_level(logging.WARNING, logger=BerachainProcessor.__module__):
            txs = processor.process(rows)

        assert len(txs) == 1
        events = _events(txs[0])
        assert len(events) == 1
        assert events[0].event_type is EventType.LiquidityWithdraw
        review_msgs = _review_messages(caplog)
        assert review_msgs, "a missing-recipient non-vault leg in a batch must be flagged"
        assert "<missing>" in review_msgs[0], (
            "the WARNING must name the <missing> sentinel for the missing recipient"
        )

    def test_mixed_lp_and_registry_batch_registry_absent_clean(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Review r4 F3: the r3-F1 cross-branch mix with NO position registry
        # loaded. The branch (a) registry fold is gated on the registry being
        # present, so the covered LP leg classifies clean LiquidityWithdraw
        # and the registry-member-looking leg is invisible to the review
        # computation. This is the ACCEPTED fail-open when the registry is
        # absent: identity data is unavailable without it, so the leg cannot
        # be flagged (pinned here so a change to the gate is a visible test
        # delta, not a silent semantics shift).
        rows = [
            _row(
                tx_hash="0xbatchmixnoreg",
                asset="KODI-ISLAND",
                direction="out",
                token_address=_LP_TOKEN,
                from_address=_WALLET,
                to_address=_REGISTRY_MEMBER_RECIPIENT,  # covered by the in-leg sender
                amount_raw=2 * 10**18,
                fee_asset="BERA",
                fee_amount_raw=21_000_002_730_000,
            ),
            _row(
                tx_hash="0xbatchmixnoreg",
                asset="iTEST",
                direction="out",
                token_address=_POSITION_TOKEN,  # looks like a registry member
                from_address=_WALLET,
                to_address=_DEX_PAIR,
                amount_raw=1476177230747713290,
                fee_asset=None,
                fee_amount_raw=None,
            ),
            _row(
                tx_hash="0xbatchmixnoreg",
                asset="BERA",
                direction="in",
                token_address=None,
                from_address=_REGISTRY_MEMBER_RECIPIENT,
                to_address=_WALLET,
                amount_raw=5 * 10**18,
                fee_asset=None,
                fee_amount_raw=None,
            ),
        ]
        processor = _processor()  # NO position registry: identity data absent

        with caplog.at_level(logging.WARNING, logger=BerachainProcessor.__module__):
            txs = processor.process(rows)

        assert len(txs) == 1
        events = _events(txs[0])
        assert len(events) == 1
        assert events[0].event_type is EventType.LiquidityWithdraw
        assert events[0].sub_type is SubType.internal_transfer
        assert not _review_messages(caplog), "registry-absent mixed batch must stay the accepted fail-open clean path"

    def test_registry_member_legs_without_vault_target_no_registry_returns_empty(
        self,
    ) -> None:
        # Direct unit test for the early return in
        # ``_registry_member_legs_without_vault_target``: with NO position
        # registry loaded the helper yields [] even for a leg that would be a
        # registry member (callers gate on registry presence; this pins the
        # guard itself, per the extracted-helpers rule).
        leg = Leg(
            asset="iTEST",
            token_address=_POSITION_TOKEN,
            amount_raw=1476177230747713290,
            amount_decimals=18,
            direction="out",
            from_address=_WALLET,
            to_address=_DEX_PAIR,
        )
        processor = _processor()  # NO position registry

        assert processor._registry_member_legs_without_vault_target([leg]) == []

    @pytest.mark.parametrize(
        ("token_address", "to_address", "expected_count"),
        [
            pytest.param(_POSITION_TOKEN, _DEX_PAIR, 1, id="member-nonvault-returned"),
            pytest.param(
                _POSITION_TOKEN, _REGISTRY_MEMBER_RECIPIENT, 0, id="member-vault-excluded"
            ),
            pytest.param(_LP_TOKEN, _DEX_PAIR, 0, id="non-member-excluded"),
            pytest.param(None, _DEX_PAIR, 0, id="native-leg-excluded"),
        ],
    )
    def test_registry_member_legs_without_vault_target_membership(
        self,
        token_address: str | None,
        to_address: str,
        expected_count: int,
    ) -> None:
        # Direct parametrized test for the helper's membership discriminators
        # (registry PRESENT): a registry-member token on a NON-vault recipient
        # is returned (the possible-disposal signal), while a member token on a
        # registry vault recipient, a NON-member token (LP-snapshot member is
        # not a position-registry member), and a native leg (token_address
        # None) are all excluded.
        leg = Leg(
            asset="iTEST" if token_address is not None else "BERA",
            token_address=token_address,
            amount_raw=1476177230747713290,
            amount_decimals=18,
            direction="out",
            from_address=_WALLET,
            to_address=to_address,
        )
        processor = _processor(position_registry=_position_registry())

        assert len(processor._registry_member_legs_without_vault_target([leg])) == expected_count


@pytest.mark.unit
class TestBerachainProcessorInvariants:
    """Run-level invariants the processor enforces post-aggregation."""

    def test_unknown_direction_rate_over_one_percent_raises(self) -> None:
        # Given - a run where >1% of a wallet's legs have direction=unknown.
        # 100 legs, 5 unknown -> 5% > 1% threshold AND count=5 >= floor -> the
        # run-level invariant fires FileProcessingError. (The small-N floor
        # requires >= UNKNOWN_DIRECTION_MIN_ABSOLUTE unknown legs; the
        # test_single_unknown_in_small_wallet_does_not_abort test pins the
        # other side of the floor.)
        rows: list[OnChainTxRow] = []
        # 95 known-direction legs (simple swaps, 2 legs each across 47 txs +
        # one extra out leg).
        for i in range(47):
            base = 10**18 + i
            rows.append(
                _row(
                    tx_hash=f"0xknown{i}",
                    asset="BERA",
                    direction="out",
                    from_address=_WALLET,
                    to_address=_DEX_ROUTER,
                    amount_raw=base,
                )
            )
            rows.append(
                _row(
                    tx_hash=f"0xknown{i}",
                    asset="HONEY",
                    direction="in",
                    token_address="0x000000000000000000000000000000000000abcd",
                    from_address=_DEX_ROUTER,
                    to_address=_WALLET,
                    amount_raw=base,
                    fee_asset=None,
                    fee_amount_raw=None,
                )
            )
        # One more known-direction out leg to reach 95 known legs.
        rows.append(
            _row(
                tx_hash="0xknown_extra",
                asset="BERA",
                direction="out",
                from_address=_WALLET,
                to_address=_DEX_ROUTER,
                amount_raw=10**18 + 99,
            )
        )
        # 5 unknown-direction legs (their own txs) -> 5/100 = 5% > 1% AND
        # count=5 >= floor.
        for j in range(5):
            rows.append(
                _row(
                    tx_hash=f"0xunk{j}",
                    asset=f"MYSTERY{j}",
                    direction="unknown",
                    token_address="0x000000000000000000000000000000000000abcd",
                    from_address=_DEX_ROUTER,
                    to_address=_WALLET,
                    fee_asset=None,
                    fee_amount_raw=None,
                )
            )
        assert len(rows) == 100
        processor = _processor()

        # When/Then - the run-level invariant fires post-aggregation.
        with pytest.raises(FileProcessingError, match="unknown"):
            processor.process(rows)

    def test_single_unknown_in_small_wallet_does_not_abort(self) -> None:
        # F18 small-N floor: 50 legs, exactly 1 unknown -> 2% > 1% threshold
        # BUT count=1 < floor of 5, so the run does NOT abort (a single weird
        # tx in a small wallet is handled per-tx as Unknown+review, not a
        # systemic decoder regression).
        rows: list[OnChainTxRow] = []
        # 49 known-direction legs (simple swaps, 2 legs each across 24 txs +
        # one extra out leg to reach 49).
        for i in range(24):
            base = 10**18 + i
            rows.append(
                _row(
                    tx_hash=f"0xknown{i}",
                    asset="BERA",
                    direction="out",
                    from_address=_WALLET,
                    to_address=_DEX_ROUTER,
                    amount_raw=base,
                )
            )
            rows.append(
                _row(
                    tx_hash=f"0xknown{i}",
                    asset="HONEY",
                    direction="in",
                    token_address="0x000000000000000000000000000000000000abcd",
                    from_address=_DEX_ROUTER,
                    to_address=_WALLET,
                    amount_raw=base,
                    fee_asset=None,
                    fee_amount_raw=None,
                )
            )
        # One more known-direction out leg to make 49 known legs.
        rows.append(
            _row(
                tx_hash="0xknown_extra",
                asset="BERA",
                direction="out",
                from_address=_WALLET,
                to_address=_DEX_ROUTER,
                amount_raw=10**18 + 99,
            )
        )
        # Exactly 1 unknown-direction leg -> 1/50 = 2% > 1% but count=1 < 5.
        rows.append(
            _row(
                tx_hash="0xunk1",
                asset="MYSTERY",
                direction="unknown",
                token_address="0x000000000000000000000000000000000000abcd",
                from_address=_DEX_ROUTER,
                to_address=_WALLET,
                fee_asset=None,
                fee_amount_raw=None,
            )
        )
        assert len(rows) == 50
        processor = _processor()

        # When/Then - the small-N floor prevents the abort; process() returns
        # normally (no FileProcessingError).
        txs = processor.process(rows)
        assert txs  # classification proceeded

    def test_five_unknowns_in_small_wallet_aborts(self) -> None:
        # F18 small-N floor: 50 legs, 5 unknown -> 10% > 1% AND count=5 >= 5,
        # so the run DOES abort (a systemic regression still fails loud even
        # in a small wallet).
        rows: list[OnChainTxRow] = []
        # 45 known-direction legs (simple swaps, 2 legs each across 22 txs +
        # one extra out leg to reach 45).
        for i in range(22):
            base = 10**18 + i
            rows.append(
                _row(
                    tx_hash=f"0xknown{i}",
                    asset="BERA",
                    direction="out",
                    from_address=_WALLET,
                    to_address=_DEX_ROUTER,
                    amount_raw=base,
                )
            )
            rows.append(
                _row(
                    tx_hash=f"0xknown{i}",
                    asset="HONEY",
                    direction="in",
                    token_address="0x000000000000000000000000000000000000abcd",
                    from_address=_DEX_ROUTER,
                    to_address=_WALLET,
                    amount_raw=base,
                    fee_asset=None,
                    fee_amount_raw=None,
                )
            )
        # One more known-direction out leg to make 45 known legs.
        rows.append(
            _row(
                tx_hash="0xknown_extra",
                asset="BERA",
                direction="out",
                from_address=_WALLET,
                to_address=_DEX_ROUTER,
                amount_raw=10**18 + 99,
            )
        )
        # 5 unknown-direction legs -> 5/50 = 10% > 1% AND count=5 >= 5.
        for j in range(5):
            rows.append(
                _row(
                    tx_hash=f"0xunk{j}",
                    asset=f"MYSTERY{j}",
                    direction="unknown",
                    token_address="0x000000000000000000000000000000000000abcd",
                    from_address=_DEX_ROUTER,
                    to_address=_WALLET,
                    fee_asset=None,
                    fee_amount_raw=None,
                )
            )
        assert len(rows) == 50
        processor = _processor()

        # When/Then - the count >= floor, so the run aborts.
        with pytest.raises(FileProcessingError, match="unknown"):
            processor.process(rows)

    def test_wallet_address_case_insensitive_direction_equality(self) -> None:
        # Given - Attacker F6: the wallet_address is checksummed (upper) on
        # the row but lower elsewhere. Direction equality must
        # case-insensitively match the wallet address, so a leg whose
        # to_address is the lower-cased wallet form is still classified
        # as "in" (not mis-typed as unknown).
        rows = [
            _row(
                tx_hash="0xcase",
                asset="HONEY",
                direction="in",
                token_address="0x000000000000000000000000000000000000abcd",
                from_address=_REWARD_DISTRIBUTOR_VERIFIED,
                to_address=_WALLET,  # lower-case
                wallet_address=_WALLET_UPPER,  # checksummed upper
                fee_asset=None,
                fee_amount_raw=None,
            ),
        ]
        processor = _processor()

        txs = processor.process(rows)

        assert len(txs) == 1
        events = _events(txs[0])
        assert len(events) == 1
        # Not mis-classified as Unknown despite the case mismatch.
        assert events[0].event_type is EventType.Reward
