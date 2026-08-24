"""Unit tests for PII-free cluster signatures (validation-harness Task 3).

Plan: ``docs/history/plans/2026-08-18-on-chain-validation-harness.md``
(Task 3). Decision: PD-010 - divergent txs are grouped into discrepancy
clusters by a PII-free *cluster signature* (event combo + Koinly Type/Tag
combo + sender-registration class + LP involvement + fee-surface class +
zero-display flag); the signature never contains tx hashes, wallet
addresses, dates, or amounts, so it is stable across re-runs and safe for
committed docs.

The records under test come from the PRODUCTION comparator
(:func:`compare_projection`) run on the production adapter projection, so
the signature logic is validated against exactly the record shape the
harness will cluster. Registry and LP snapshot are in-memory domain
objects (synthetic addresses only - PII rule; shapes reuse the comparator
test vocabulary).

Pinned behaviors (each test names its plan bullet):

1. ``test_signature_deterministic_under_reordering`` - shuffling the tx's
   events and the Koinly rows yields the IDENTICAL signature string.
2. ``test_signature_pii_free`` - signatures built from records carrying
   real-shape hashes/addresses/amounts/dates match the strict component
   grammar, contain no ``0x`` substring and no 16+ hex-character run.
3. ``test_components_discriminate`` - identical shapes differing only in
   sender class (or lp flag, or fee surface) produce DISTINCT signatures.
4. ``test_on_chain_only_and_koinly_only_shapes`` - a GasBurn-only
   on-chain tx renders ``koinly=none``; a Koinly-only NFT-mint shape
   renders ``events=none``.
5. ``test_group_into_clusters_buckets_discrepancy_records`` - divergent +
   one-sided records bucket by signature; MATCHED txs are excluded (they
   are not discrepancies).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from tax_reporting.application.on_chain_config import _CONTRACT_KINDS
from tax_reporting.application.on_chain_th_adapter import project_on_chain_transactions
from tax_reporting.application.on_chain_validation.clustering import (
    _SENDER_KIND_PRIORITY,
    cluster_signature,
    group_into_clusters,
)
from tax_reporting.application.on_chain_validation.comparator import (
    ThComparisonRecord,
    compare_projection,
)
from tax_reporting.domain.on_chain_config import (
    ContractEntry,
    ContractRegistry,
    LpSnapshot,
    LpTokenEntry,
)
from tax_reporting.domain.on_chain_transaction import (
    Event,
    EventType,
    Gas,
    Leg,
    OnChainTransaction,
    SubType,
)

# Synthetic identifiers only (Design Invariant PII; never real mainnet values).
_TX_HASH = "0xabc111def222abc333def444abc555def666abc777def888abc999def000ab"
_TX_HASH_B = "0xbca222fed111bca333fed444bca555fed666bca777fed888bca999fed000ba"
_TX_HASH_ON_CHAIN_ONLY = "0x1111111111111111111111111111111111111111111111111111111111111111"
_TX_HASH_KOINLY_ONLY = "0x2222222222222222222222222222222222222222222222222222222222222222"
_TX_HASH_MATCHED = "0x3333333333333333333333333333333333333333333333333333333333333333"
_WALLET_ADDRESS = "0xWallet0000000000000000000000000000000000a"
_COUNTERPARTY = "0xCounterParty00000000000000000000000000000b"
_COUNTERPARTY_A = "0xSenderA000000000000000000000000000000000c"
_COUNTERPARTY_B = "0xSenderB000000000000000000000000000000000d"
_BGT_TOKEN = "0xToken0000000000000000000000000000000001"
_LP_TOKEN = "0xLpToken00000000000000000000000000000002"
_OTHER_TOKEN = "0xOtherToken00000000000000000000000000003"
_WALLET_LABEL = "Ledger Berachain (BERA)"
_TIMESTAMP = datetime(2025, 3, 1, 12, 0, 0, tzinfo=UTC)
_DECIMALS = 18

# The plan's signature grammar: components joined with '|', each 'k=v' with a
# '|'-free value (PII-freeness is asserted component-wise against this regex).
_SIGNATURE_GRAMMAR = re.compile(r"^((events|koinly|sender|lp|fee|zero_display)=[^|]*\|?)+$")
_HEX_RUN = re.compile(r"[0-9a-fA-F]{16,}")


# --------------------------------------------------------------------------- #
# Fixture builders (on-chain side through the PRODUCTION adapter)              #
# --------------------------------------------------------------------------- #


def _to_raw(amount: Decimal, decimals: int = _DECIMALS) -> int:
    """Exact integer smallest-units for a clean decimal ``amount``."""
    return int(amount.scaleb(decimals))


def _in_leg(*, asset: str, amount: Decimal, token_address: str | None, source: str = _COUNTERPARTY) -> Leg:
    """An inflow leg from ``source`` into the tracked wallet."""
    return Leg(
        asset=asset,
        token_address=token_address,
        amount_raw=_to_raw(amount),
        amount_decimals=_DECIMALS,
        direction="in",
        from_address=source,
        to_address=_WALLET_ADDRESS,
    )


def _out_leg(*, asset: str, amount: Decimal, token_address: str | None) -> Leg:
    """An outflow leg from the tracked wallet to the counterparty."""
    return Leg(
        asset=asset,
        token_address=token_address,
        amount_raw=_to_raw(amount),
        amount_decimals=_DECIMALS,
        direction="out",
        from_address=_WALLET_ADDRESS,
        to_address=_COUNTERPARTY,
    )


def _tx(tx_hash: str, events: list[Event], *, gas: Gas | None = None) -> OnChainTransaction:
    """Wrap events into an ``OnChainTransaction`` (single wallet)."""
    return OnChainTransaction(
        tx_hash=tx_hash,
        block_number=1_000,
        timestamp_utc=_TIMESTAMP,
        chain="Berachain",
        wallet_label=_WALLET_LABEL,
        wallet_address=_WALLET_ADDRESS,
        gas=gas,
        events=tuple(events),
    )


def _reward_tx(  # noqa: PLR0913 (the predecessor's F1 fix added the `token` leg address)
    tx_hash: str,
    amount: Decimal,
    *,
    gas_amount: Decimal | None = None,
    asset: str = "BGT",
    token: str | None = _BGT_TOKEN,
    source: str = _COUNTERPARTY,
) -> OnChainTransaction:
    """A single-Event Reward claim; optional parent-tx gas on the carrier row."""
    event = Event(
        event_id=f"{tx_hash}#1",
        event_type=EventType.Reward,
        sub_type=SubType.staking,
        legs=(_in_leg(asset=asset, amount=amount, token_address=token, source=source),),
        parent_tx_hash=tx_hash,
    )
    gas = Gas(asset="BERA", amount_raw=_to_raw(gas_amount), decimals=_DECIMALS) if gas_amount is not None else None
    return _tx(tx_hash, [event], gas=gas)


def _gasburn_tx(tx_hash: str, gas_amount: Decimal) -> OnChainTransaction:
    """A gas-only tx: one zero-value native out-leg, gas at the tx level."""
    event = Event(
        event_id=f"{tx_hash}#1",
        event_type=EventType.GasBurn,
        sub_type=SubType.cost_gas,
        legs=(_out_leg(asset="BERA", amount=Decimal("0"), token_address=None),),
        parent_tx_hash=tx_hash,
    )
    return _tx(
        tx_hash,
        [event],
        gas=Gas(asset="BERA", amount_raw=_to_raw(gas_amount), decimals=_DECIMALS),
    )


def _koinly_row(  # noqa: PLR0913
    *,
    tx_hash: str = _TX_HASH,
    type_: str,
    tag: str = "",
    sent: str = "",
    sent_cur: str = "",
    recv: str = "",
    recv_cur: str = "",
    fee: str = "",
    fee_cur: str = "",
) -> dict[str, str]:
    """One raw Koinly TH row dict in the exact ``read_koinly_rows`` shape."""
    return {
        "Date": "2025-03-01 12:00:00 UTC",
        "Type": type_,
        "Tag": tag,
        "Sending Wallet": _WALLET_LABEL,
        "Sent Amount": sent,
        "Sent Currency": sent_cur,
        "Receiving Wallet": _WALLET_LABEL,
        "Received Amount": recv,
        "Received Currency": recv_cur,
        "Fee Amount": fee,
        "Fee Currency": fee_cur,
        "TxSrc": _COUNTERPARTY,
        "TxDest": _WALLET_ADDRESS,
        "TxHash": tx_hash,
    }


def _registry(entries: dict[str, str] | None = None) -> ContractRegistry:
    """An in-memory registry mapping synthetic address -> kind."""
    contracts = {
        address.lower(): ContractEntry(
            address=address.lower(),
            label=None,
            kind=kind,
            protocol=None,
            operator_country=None,
            citation=None,
        )
        for address, kind in (entries or {}).items()
    }
    return ContractRegistry(chain="Berachain", contracts=contracts, source="<inline-test>")


def _snapshot(token_addresses: set[str] | None = None) -> LpSnapshot:
    """An in-memory LP snapshot containing only the given synthetic tokens."""
    tokens = {
        address.lower(): LpTokenEntry(token_address=address.lower(), protocol=None, lp_type=None)
        for address in (token_addresses or set())
    }
    return LpSnapshot(
        subgraph=None,
        subgraph_version="test",
        snapshot_as_of_block=1,
        snapshot_as_of_date="2025-12-31",
        tokens=tokens,
        source="<inline-test>",
    )


def _single_divergent_record(
    tx: OnChainTransaction,
    koinly_rows: list[dict[str, str]],
) -> ThComparisonRecord:
    """The one divergent record of a two-input comparison (fails loudly if not).

    Passes the SOURCE transactions to ``compare_projection`` exactly like the
    runner does, so the record carries the on-chain token-address context the
    ``lp`` component resolves against (review r1 F1: the authoritative
    discriminator must reach the record on the production path).
    """
    result = compare_projection(
        koinly_rows, project_on_chain_transactions([tx]), on_chain_transactions=[tx]
    )
    assert len(result.divergent) == 1, f"expected one divergent record, got {len(result.divergent)}"
    return result.divergent[0]


def _components(signature: str) -> dict[str, str]:
    """Parse a signature into its ``k=v`` components (test observability)."""
    return dict(part.split("=", 1) for part in signature.split("|"))


def _assert_differs_only_in(first: str, second: str, component: str) -> None:
    """Assert two signatures differ in exactly the named component."""
    assert first != second
    parts_first, parts_second = _components(first), _components(second)
    assert parts_first[component] != parts_second[component]
    rest_first = {key: value for key, value in parts_first.items() if key != component}
    rest_second = {key: value for key, value in parts_second.items() if key != component}
    assert rest_first == rest_second


@pytest.mark.unit
class TestOnChainClusterSignature:
    """PD-010 cluster-signature pins for the clustering module."""

    def test_signature_deterministic_under_reordering(self) -> None:
        # Given - a claim+swap tx (Reward BGT in + native-out swap) with its
        # gas rendered by Koinly as a Cost row, run TWICE with the tx's events
        # and the Koinly rows in different orders.
        def build(events_reversed: bool, rows_reversed: bool) -> str:
            reward = Event(
                event_id=f"{_TX_HASH}#1",
                event_type=EventType.Reward,
                sub_type=SubType.staking,
                legs=(_in_leg(asset="BGT", amount=Decimal("12.345678901"), token_address=_BGT_TOKEN),),
                parent_tx_hash=_TX_HASH,
            )
            swap = Event(
                event_id=f"{_TX_HASH}#2",
                event_type=EventType.Swap,
                sub_type=None,
                legs=(
                    _out_leg(asset="BERA", amount=Decimal("1"), token_address=None),
                    _in_leg(asset="WETH", amount=Decimal("2"), token_address=_BGT_TOKEN),
                ),
                parent_tx_hash=_TX_HASH,
            )
            events = [swap, reward] if events_reversed else [reward, swap]
            tx = _tx(
                _TX_HASH,
                events,
                gas=Gas(asset="BERA", amount_raw=_to_raw(Decimal("0.001")), decimals=_DECIMALS),
            )
            rows = [
                _koinly_row(type_="crypto_deposit", tag="Reward", recv="11.0", recv_cur="BGT"),
                _koinly_row(type_="exchange", sent="1", sent_cur="BERA", recv="2", recv_cur="WETH"),
                _koinly_row(type_="crypto_withdrawal", tag="Cost", sent="0.001", sent_cur="BERA"),
            ]
            if rows_reversed:
                rows.reverse()
            record = _single_divergent_record(tx, rows)
            return cluster_signature(record, registry=_registry(), lp_snapshot=_snapshot())

        # Then - the identical signature string regardless of input ordering,
        # with every multivalued component rendered in sorted order.
        assert build(events_reversed=False, rows_reversed=False) == build(events_reversed=True, rows_reversed=True)
        assert build(events_reversed=False, rows_reversed=False) == (
            "events=Reward+Swap"
            "|koinly=crypto_deposit/Reward+crypto_withdrawal/Cost+exchange/"
            "|sender=unregistered"
            "|lp=false"
            "|fee=cost_rows"
            "|zero_display=false"
        )

    def test_signature_pii_free(self) -> None:
        # Given - records carrying real-SHAPE tx hashes (64-hex runs),
        # wallet-style addresses, amounts, and dates - one shared-divergent,
        # one on-chain-only, one Koinly-only.
        registry = _registry({_COUNTERPARTY: "reward_distributor"})
        divergent = _single_divergent_record(
            _reward_tx(_TX_HASH, Decimal("1.5")),
            [_koinly_row(type_="crypto_deposit", tag="Reward", recv="1.4", recv_cur="BGT")],
        )
        on_chain_only = compare_projection(
            [], project_on_chain_transactions([_gasburn_tx(_TX_HASH_ON_CHAIN_ONLY, Decimal("0.0001"))])
        ).on_chain_only[0]
        koinly_only = compare_projection(
            [
                _koinly_row(
                    tx_hash=_TX_HASH_KOINLY_ONLY,
                    type_="crypto_deposit",
                    tag="Reward",
                    recv="3.5",
                    recv_cur="BGT",
                )
            ],
            [],
        ).koinly_only[0]

        # Then - every signature matches the strict component grammar and
        # carries no '0x' substring and no 16+ hex-character run.
        for record in (divergent, on_chain_only, koinly_only):
            signature = cluster_signature(record, registry=registry, lp_snapshot=_snapshot())
            assert _SIGNATURE_GRAMMAR.match(signature) is not None, signature
            assert "0x" not in signature, signature
            assert _HEX_RUN.search(signature) is None, signature

    def test_components_discriminate(self) -> None:
        # Given (sender) - identical reward-claim shapes whose only difference
        # is the counterparty's registry kind (reward_distributor vs dex_router).
        registry_two_kinds = _registry({_COUNTERPARTY_A: "reward_distributor", _COUNTERPARTY_B: "dex_router"})
        rows = [_koinly_row(type_="crypto_deposit", tag="Reward", recv="1.4", recv_cur="BGT")]
        from_a = _single_divergent_record(_reward_tx(_TX_HASH, Decimal("1.5"), source=_COUNTERPARTY_A), rows)
        from_b = _single_divergent_record(_reward_tx(_TX_HASH, Decimal("1.5"), source=_COUNTERPARTY_B), rows)
        signature_a = cluster_signature(from_a, registry=registry_two_kinds, lp_snapshot=_snapshot())
        signature_b = cluster_signature(from_b, registry=registry_two_kinds, lp_snapshot=_snapshot())

        # Then - the signatures differ in EXACTLY the sender component.
        _assert_differs_only_in(signature_a, signature_b, "sender")
        assert _components(signature_a)["sender"] == "reward_distributor"
        assert _components(signature_b)["sender"] == "dex_router"

        # And given (lp, authoritative source) - identical REAL-SHAPE claims
        # whose visible tickers are ordinary non-LP symbols but whose on-chain
        # legs carry the snapshot-listed token ADDRESS on one side and a
        # non-listed address on the other (review r1 F1: the leg's
        # token_address is the authoritative LP discriminator; tickers never
        # match the snapshot's address keys, so an asset-only check is a dead
        # dimension on the production path).
        snapshot_with_lp = _snapshot({_LP_TOKEN})
        lp_hit = _single_divergent_record(
            _reward_tx(_TX_HASH, Decimal("1.5"), asset="BULT-ABC", token=_LP_TOKEN),
            [_koinly_row(type_="crypto_deposit", tag="Reward", recv="1.4", recv_cur="BULT-ABC")],
        )
        lp_miss = _single_divergent_record(
            _reward_tx(_TX_HASH, Decimal("1.5"), asset="BULT-XYZ", token=_OTHER_TOKEN),
            [_koinly_row(type_="crypto_deposit", tag="Reward", recv="1.4", recv_cur="BULT-XYZ")],
        )
        signature_hit = cluster_signature(lp_hit, registry=_registry(), lp_snapshot=snapshot_with_lp)
        signature_miss = cluster_signature(lp_miss, registry=_registry(), lp_snapshot=snapshot_with_lp)

        # Then - the signatures differ in EXACTLY the lp component.
        _assert_differs_only_in(signature_hit, signature_miss, "lp")
        assert _components(signature_hit)["lp"] == "true"
        assert _components(signature_miss)["lp"] == "false"

        # And given (lp, asset fallback) - a record with NO token-address
        # context (Koinly-only rows) still discriminates when an ASSET
        # identifier is itself the address-shaped rendering of a snapshot
        # token (the pre-F1 behavior, preserved as the fallback).
        lp_fallback_hit = compare_projection(
            [
                _koinly_row(
                    tx_hash=_TX_HASH_KOINLY_ONLY,
                    type_="crypto_deposit",
                    tag="Reward",
                    recv="1.4",
                    recv_cur=_LP_TOKEN,
                )
            ],
            [],
        ).koinly_only[0]
        assert (
            cluster_signature(lp_fallback_hit, registry=_registry(), lp_snapshot=snapshot_with_lp).split("|")[3]
            == "lp=true"
        )

        # And given (fee) - the same divergent claim with the gas rendered as
        # a Cost row on one side and as a Fee Amount cell on the other (the
        # Cost row necessarily also adds its Type/Tag combo to 'koinly').
        cost_rows = [
            _koinly_row(type_="crypto_deposit", tag="Reward", recv="1.4", recv_cur="BGT"),
            _koinly_row(type_="crypto_withdrawal", tag="Cost", sent="0.002", sent_cur="BERA"),
        ]
        fee_column = [
            _koinly_row(type_="crypto_deposit", tag="Reward", recv="1.4", recv_cur="BGT", fee="0.002", fee_cur="BERA"),
        ]
        with_gas = _reward_tx(_TX_HASH, Decimal("1.5"), gas_amount=Decimal("0.002"))
        signature_cost = cluster_signature(
            _single_divergent_record(with_gas, cost_rows), registry=_registry(), lp_snapshot=_snapshot()
        )
        signature_fee = cluster_signature(
            _single_divergent_record(with_gas, fee_column), registry=_registry(), lp_snapshot=_snapshot()
        )

        # Then - the signatures differ, with the fee component carrying the
        # two distinct Koinly gas-rendering surfaces.
        assert signature_cost != signature_fee
        assert _components(signature_cost)["fee"] == "cost_rows"
        assert _components(signature_fee)["fee"] == "fee_column"

    def test_signature_vocabulary_edge_values(self) -> None:
        """The signature vocabulary's remaining values and guards (review r1
        F12): ``fee=mixed``, ``sender=null_or_empty``, the sender priority
        tie-break, and the fail-loud ``|`` component-separator guard."""
        # Given (fee=mixed) - one tx whose Koinly gas rides BOTH a Cost row
        # and a Fee Amount cell (the MIXED surface).
        with_gas = _reward_tx(_TX_HASH, Decimal("1.5"), gas_amount=Decimal("0.002"))
        mixed_rows = [
            _koinly_row(type_="crypto_deposit", tag="Reward", recv="1.4", recv_cur="BGT", fee="0.001", fee_cur="BERA"),
            _koinly_row(type_="crypto_withdrawal", tag="Cost", sent="0.001", sent_cur="BERA"),
        ]
        signature_mixed = cluster_signature(
            _single_divergent_record(with_gas, mixed_rows), registry=_registry(), lp_snapshot=_snapshot()
        )

        # Then - the fee component carries the MIXED class.
        assert _components(signature_mixed)["fee"] == "mixed"

        # And given (sender=null_or_empty) - a KOINLY-ONLY record whose row
        # carries no counterparty at all (empty TxSrc/TxDest; on records with
        # an on-chain side the projection's TxDest - the tracked wallet -
        # always contributes the wallet address, so this vocabulary value is
        # reachable through the one-sided partition).
        no_counterparty_row = _koinly_row(
            tx_hash=_TX_HASH_KOINLY_ONLY,
            type_="crypto_deposit",
            tag="Reward",
            recv="1.4",
            recv_cur="BGT",
        )
        no_counterparty_row["TxSrc"] = ""
        no_counterparty_row["TxDest"] = ""
        koinly_only_no_counterparty = compare_projection([no_counterparty_row], []).koinly_only[0]
        signature_empty = cluster_signature(koinly_only_no_counterparty, registry=_registry(), lp_snapshot=_snapshot())

        # Then - the sender component carries the null_or_empty sentinel.
        assert _components(signature_empty)["sender"] == "null_or_empty"

        # And given (sender priority tie-break) - one tx whose Koinly rows
        # name TWO differently-registered counterparties (a distributor AND a
        # DEX router): the first kind in the fixed priority wins.
        registry_two_kinds = _registry({_COUNTERPARTY_A: "reward_distributor", _COUNTERPARTY_B: "dex_router"})
        from_distributor = _koinly_row(type_="crypto_deposit", tag="Reward", recv="1.4", recv_cur="BGT")
        from_distributor["TxSrc"] = _COUNTERPARTY_A
        from_router = _koinly_row(type_="exchange", sent="1", sent_cur="BERA", recv="2", recv_cur="WETH")
        from_router["TxSrc"] = _COUNTERPARTY_B
        signature_tie = cluster_signature(
            _single_divergent_record(_reward_tx(_TX_HASH, Decimal("1.5")), [from_distributor, from_router]),
            registry=registry_two_kinds,
            lp_snapshot=_snapshot(),
        )

        # Then - reward_distributor outranks dex_router regardless of row order.
        assert _components(signature_tie)["sender"] == "reward_distributor"

        # And given (the '|' guard) - a Koinly Tag carrying the component
        # separator would corrupt the encoding and must fail loudly.
        with pytest.raises(ValueError, match="component separator"):
            cluster_signature(
                _single_divergent_record(
                    _reward_tx(_TX_HASH, Decimal("1.5")),
                    [_koinly_row(type_="crypto_deposit", tag="Re|ward", recv="1.4", recv_cur="BGT")],
                ),
                registry=_registry(),
                lp_snapshot=_snapshot(),
            )

    def test_on_chain_only_and_koinly_only_shapes(self) -> None:
        # Given - a GasBurn-only on-chain tx the Koinly baseline dropped, and
        # a Koinly-only NFT-mint row the projection cannot carry.
        on_chain_only = compare_projection(
            [], project_on_chain_transactions([_gasburn_tx(_TX_HASH_ON_CHAIN_ONLY, Decimal("0.0001"))])
        ).on_chain_only[0]
        koinly_only = compare_projection(
            [
                _koinly_row(
                    tx_hash=_TX_HASH_KOINLY_ONLY,
                    type_="crypto_deposit",
                    tag="NFT",
                    recv="1",
                    recv_cur="NFT",
                )
            ],
            [],
        ).koinly_only[0]

        # Then - the absent side's components render 'none': the on-chain-only
        # tx has koinly=none (and fee=none - no Koinly rendering at all), the
        # Koinly-only shape has events=none.
        assert cluster_signature(on_chain_only, registry=_registry(), lp_snapshot=_snapshot()) == (
            "events=GasBurn|koinly=none|sender=unregistered|lp=false|fee=none|zero_display=false"
        )
        assert cluster_signature(koinly_only, registry=_registry(), lp_snapshot=_snapshot()) == (
            "events=none|koinly=crypto_deposit/NFT|sender=unregistered|lp=false|fee=none|zero_display=false"
        )

    def test_group_into_clusters_buckets_discrepancy_records(self) -> None:
        # Given - two same-shape divergent claims (different hashes), one
        # on-chain-only gas burn, one Koinly-only NFT mint, and one MATCHED
        # claim (not a discrepancy - must appear in no cluster).
        projected = project_on_chain_transactions(
            [
                _reward_tx(_TX_HASH, Decimal("1.5")),
                _reward_tx(_TX_HASH_B, Decimal("1.5")),
                _gasburn_tx(_TX_HASH_ON_CHAIN_ONLY, Decimal("0.0001")),
                _reward_tx(_TX_HASH_MATCHED, Decimal("1.5")),
            ]
        )
        koinly_rows = [
            _koinly_row(type_="crypto_deposit", tag="Reward", recv="1.4", recv_cur="BGT"),
            _koinly_row(tx_hash=_TX_HASH_B, type_="crypto_deposit", tag="Reward", recv="1.4", recv_cur="BGT"),
            _koinly_row(tx_hash=_TX_HASH_MATCHED, type_="crypto_deposit", tag="Reward", recv="1.5", recv_cur="BGT"),
            _koinly_row(tx_hash=_TX_HASH_KOINLY_ONLY, type_="crypto_deposit", tag="NFT", recv="1", recv_cur="NFT"),
        ]
        result = compare_projection(koinly_rows, projected)

        # Then - records bucket by signature: the two same-shape divergences
        # share one cluster, each one-sided shape gets its own, and the
        # matched hash appears NOWHERE.
        clusters = group_into_clusters(result, registry=_registry(), lp_snapshot=_snapshot())
        assert len(clusters) == 3
        divergent_cluster = [
            records for signature, records in clusters.items() if signature.startswith("events=Reward|")
        ]
        assert len(divergent_cluster) == 1
        assert [record.tx_hash for record in divergent_cluster[0]] == [_TX_HASH, _TX_HASH_B]
        assert any(record.tx_hash == _TX_HASH_ON_CHAIN_ONLY for records in clusters.values() for record in records)
        assert any(record.tx_hash == _TX_HASH_KOINLY_ONLY for records in clusters.values() for record in records)
        assert all(record.tx_hash != _TX_HASH_MATCHED for records in clusters.values() for record in records)

    def test_sender_priority_covers_every_registry_kind(self) -> None:
        """The sender-class priority vocabulary stays tied to the registry
        loader's kind vocabulary (review r1 F14, overflow): a future
        ``_CONTRACT_KINDS`` entry missing from ``_SENDER_KIND_PRIORITY``
        would silently cluster every occurrence as ``unregistered`` (the
        documented fallback), mis-keying real clusters with no test failing.
        """
        assert set(_SENDER_KIND_PRIORITY) == set(_CONTRACT_KINDS), (
            "a registry kind outside the sender priority silently clusters as unregistered"
        )
