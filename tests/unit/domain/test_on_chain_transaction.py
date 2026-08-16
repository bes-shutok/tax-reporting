"""Tests for the on-chain-native transaction domain model (Task 6).

Task 6 introduces a pure-data domain model that is *on-chain-native* rather than
Koinly-shaped: one ``OnChainTransaction`` per ``tx_hash`` holds N ``Event``s and
a single parent-tx-level ``Gas``. This file pins the closed enum memberships, the
parent-tx-level placement of gas, and the parent-linkage of Events.

Plan: ``docs/history/plans/2026-08-02-on-chain-tx-tagger.md`` (Task 6).
Design record: ``docs/architecture/on-chain-tx-design.md`` (§9.1, decisions 4 + 9).
"""

from __future__ import annotations

from datetime import UTC, datetime

from tax_reporting.domain.on_chain_transaction import (
    Event,
    EventType,
    Gas,
    Leg,
    OnChainTransaction,
    SubType,
)


class TestEventType:
    def test_seven_members(self) -> None:
        # §9.1: EventType is a closed enum of exactly these seven economic shapes.
        assert set(EventType) == {
            EventType.Swap,
            EventType.LiquidityDeposit,
            EventType.LiquidityWithdraw,
            EventType.Reward,
            EventType.Transfer,
            EventType.GasBurn,
            EventType.Unknown,
        }


class TestSubType:
    def test_seven_optional_members(self) -> None:
        # §9.1: SubType is a closed enum of exactly these seven decision-driving
        # discriminators (orthogonal to EventType; optional on an Event).
        assert set(SubType) == {
            SubType.staking,
            SubType.airdrop,
            SubType.validator_rebate,
            SubType.spam,
            SubType.cost_gas,
            SubType.internal_transfer,
            SubType.bridge,
        }


def _reward_event(tx_hash: str, event_id: str) -> Event:
    """Build a minimal Reward Event for the linkage/gas tests."""
    return Event(
        event_id=event_id,
        event_type=EventType.Reward,
        sub_type=SubType.staking,
        legs=(
            Leg(
                asset="BGT",
                token_address=None,
                amount_raw=1_097_000_000_000_000_000,
                amount_decimals=18,
                direction="in",
                from_address="0xd2f19a79b026fb636a7c300bf5947df113940761",
                to_address="0xabc",
            ),
        ),
        parent_tx_hash=tx_hash,
    )


def _swap_event(tx_hash: str, event_id: str) -> Event:
    """Build a minimal Swap Event sharing a parent tx with the reward Event."""
    return Event(
        event_id=event_id,
        event_type=EventType.Swap,
        sub_type=None,
        legs=(
            Leg(
                asset="BGT",
                token_address=None,
                amount_raw=1_097_000_000_000_000_000,
                amount_decimals=18,
                direction="out",
                from_address="0xabc",
                to_address="0xrouter",
            ),
            Leg(
                asset="HONEY",
                token_address="0xhoney",
                amount_raw=4_200_000,
                amount_decimals=6,
                direction="in",
                from_address="0xrouter",
                to_address="0xabc",
            ),
        ),
        parent_tx_hash=tx_hash,
    )


class TestOnChainTransaction:
    def test_gas_at_parent_level(self) -> None:
        # Decision 9 (§3 of the design record): gas is a PARENT-TX-level field;
        # one EVM tx burns gas exactly once regardless of how many Events it
        # contains, so NO Event carries gas.
        tx_hash = "0x" + "a" * 64
        tx = OnChainTransaction(
            tx_hash=tx_hash,
            block_number=12_345_678,
            timestamp_utc=datetime(2025, 3, 1, 9, 0, 0, tzinfo=UTC),
            chain="berachain",
            wallet_label="Ledger Berachain (BERA)",
            wallet_address="0xabc",
            gas=Gas(asset="BERA", amount_raw=20_000_000_000_000, decimals=18),
            events=(_reward_event(tx_hash, "evt1"), _swap_event(tx_hash, "evt2")),
        )

        # Gas is carried on the parent tx, not on either Event.
        assert isinstance(tx.gas, Gas)
        assert tx.gas.asset == "BERA"
        assert tx.gas.amount_raw == 20_000_000_000_000
        assert tx.gas.decimals == 18
        # No Event has a gas attribute (the model has no per-Event gas field).
        for event in tx.events:
            assert not hasattr(event, "gas")

    def test_events_linked_by_parent_event_id(self) -> None:
        # Decision 4 (cardinality): a tx_hash fans out to N Events, each carrying
        # its parent_tx_hash and a unique-within-tx event_id.
        tx_hash = "0x" + "b" * 64
        reward = _reward_event(tx_hash, "evt1")
        swap = _swap_event(tx_hash, "evt2")

        tx = OnChainTransaction(
            tx_hash=tx_hash,
            block_number=12_345_679,
            timestamp_utc=datetime(2025, 3, 2, 9, 0, 0, tzinfo=UTC),
            chain="berachain",
            wallet_label="Ledger Berachain (BERA)",
            wallet_address="0xabc",
            gas=None,
            events=(reward, swap),
        )

        # Every Event carries the parent tx hash.
        assert all(event.parent_tx_hash == tx_hash for event in tx.events)
        # event_ids are unique within the tx.
        event_ids = [event.event_id for event in tx.events]
        assert len(event_ids) == len(set(event_ids))
        # The two Events are distinct and both present.
        assert reward.event_id != swap.event_id
        assert reward.event_type == EventType.Reward
        assert swap.event_type == EventType.Swap
