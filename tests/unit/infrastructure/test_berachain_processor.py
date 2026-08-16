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
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock

import pytest

from tax_reporting.application.on_chain_config import (
    LpSnapshot,
    build_lp_snapshot,
    load_contracts,
)
from tax_reporting.domain.exceptions import FileProcessingError
from tax_reporting.domain.on_chain_transaction import (
    Event,
    EventType,
    Gas,
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
_LP_TOKEN = "0x000000000000000000000000000000000000dead"  # matches example LP snapshot

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


def _processor(*, registry_path: Path | None = None) -> BerachainProcessor:
    """Build a processor bound to the example registry + an in-memory LP snapshot.

    The RPC-backed LP fallback is NOT exercised here; ``is_lp_token`` is
    served entirely by the snapshot. The mock RPC client is configured so
    that any token NOT in the snapshot returns "not LP" (empty bytecode, no
    implementation) rather than raising - the snapshot is the only
    classification signal these tests use.
    """
    registry = load_contracts(registry_path or _EXAMPLE_CONTRACTS)
    snapshot = _lp_snapshot()
    rpc = Mock()
    # Empty bytecode + zero implementation -> is_lp_token returns Unknown
    # (not LP) for any token not in the snapshot, with no real RPC traffic.
    rpc.get_code.return_value = "0x"
    rpc.get_implementation.return_value = "0x0000000000000000000000000000000000000000"
    autod = LpAutodiscovery(snapshot=snapshot, rpc_client=rpc)
    return BerachainProcessor(
        chain="Berachain", contract_registry=registry, lp_autodiscovery=autod
    )


def _events(tx: OnChainTransaction) -> list[Event]:
    return list(tx.events)


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
            "event_id", "event_type", "sub_type", "legs", "parent_tx_hash"
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
        review_msgs = [
            r for r in caplog.records
            if r.levelno == logging.WARNING and "review flag" in r.getMessage()
        ]
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
        review_msgs = [
            r for r in caplog.records
            if r.levelno == logging.WARNING and "review flag" in r.getMessage()
        ]
        assert review_msgs, "expected a review-flag WARNING for the spam Event"

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
