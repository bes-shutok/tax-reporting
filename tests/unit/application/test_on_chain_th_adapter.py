"""Tests for the on-chain TH adapter (Plan Task 10).

The adapter is the THIRD step of the on-chain TH path:

    CSV (Task 7) -> processor (Task 9) -> list[OnChainTransaction]
        -> *this adapter* -> list[ProjectedThRow]   (Koinly-compat)

Plan: ``docs/history/plans/2026-08-02-on-chain-tx-tagger.md`` (Task 10).
Design record: ``docs/architecture/on-chain-tx-design.md`` (§3 carrier-row gas
rule, §9.1 EventType -> Koinly Type/Tag mapping, decision 9).

These eight tests pin the three load-bearing properties of the projection:

1. one ``TransactionHistoryRow`` per ``Event`` (the split model);
2. the closed ``EventType`` -> Koinly ``Type``/``Tag`` mapping (single dict);
3. the carrier-row gas rule including its GasBurn exception (the core
   non-domain accommodation forced by the lossy Koinly shape);
4. ``tx_hash``/``tx_src``/``tx_dest`` populated correctly so the THREE downstream
   consumers (``tx_correlation_key_resolver``, ``token_origin``, ``fee_filter``)
   simultaneously read their required fields off one row (review F6: this is the
   test that would have caught B1).

The adapter returns a list of ``ProjectedThRow`` wrappers: each carries the
typed ``TransactionHistoryRow`` (pure domain, no Koinly-ism) plus an OPTIONAL
``fee`` (a ``ProjectedFee`` carrying the gas amount/currency). Gas is at the
parent-tx level on ``OnChainTransaction`` and the typed row has NO fee field, so
the adapter cannot put gas ON the row; instead it tags the CARRIER row with the
``fee`` payload (Task 11's CSV bridge emits ``Fee Amount``/``Fee Currency`` from
it). This keeps ``TransactionHistoryRow`` pure while making the carrier-row rule
observable and auditable (review F5 mitigation).

This is also the F5 mitigation: the module docstring MUST declare that this
module exists ONLY to bridge to the Koinly-shaped ``TransactionHistoryRow`` and
MUST name the carrier-row gas rule as a non-domain accommodation.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal

from tax_reporting.application.on_chain_th_adapter import (
    EVENT_TYPE_TO_KOINLY,
    project_on_chain_transactions,
    serialize_projected_rows_to_th_csv,
)
from tax_reporting.domain.on_chain_transaction import (
    Event,
    EventType,
    Gas,
    Leg,
    OnChainTransaction,
    SubType,
)

_TX_HASH = "0xabc123def4567890abcdef1234567890abcdef1234567890abcdef1234567890"
_WALLET_LABEL = "Ledger Berachain (BERA)"
_WALLET_ADDRESS = "0xWallet0000000000000000000000000000000000a"
_TIMESTAMP = datetime(2026, 1, 15, 12, 30, 45, tzinfo=UTC)
_BLOCK_NUMBER = 1_234_567


# --------------------------------------------------------------------------- #
# Leg / Event / OnChainTransaction fixture builders                            #
# --------------------------------------------------------------------------- #


def _native_leg(
    *,
    asset: str = "BERA",
    amount_raw: int = 0,
    direction: str = "out",
    decimals: int = 18,
) -> Leg:
    """Build a native (no token_address) leg."""
    return Leg(
        asset=asset,
        token_address=None,
        amount_raw=amount_raw,
        amount_decimals=decimals,
        direction=direction,  # type: ignore[arg-type]
        from_address=_WALLET_ADDRESS,
        to_address="0xCounterParty00000000000000000000000000000b",
    )


def _erc20_leg(  # noqa: PLR0913
    *,
    asset: str,
    amount_raw: int,
    direction: str,
    decimals: int = 18,
    token_address: str = "0xToken0000000000000000000000000000000001",  # noqa: S107
    from_address: str | None = _WALLET_ADDRESS,
    to_address: str | None = "0xCounterParty00000000000000000000000000000b",
) -> Leg:
    """Build an ERC-20 leg (has a token_address)."""
    return Leg(
        asset=asset,
        token_address=token_address,
        amount_raw=amount_raw,
        amount_decimals=decimals,
        direction=direction,  # type: ignore[arg-type]
        from_address=from_address,
        to_address=to_address,
    )


def _event(
    *,
    event_type: EventType,
    sub_type: SubType | None,
    legs: tuple[Leg, ...] | list[Leg],
    event_id: str,
    review_reason: str | None = None,
) -> Event:
    """Build an Event with an explicit event_id (matches processor minting)."""
    return Event(
        event_id=event_id,
        event_type=event_type,
        sub_type=sub_type,
        legs=tuple(legs),
        parent_tx_hash=_TX_HASH,
        review_reason=review_reason,
    )


def _tx(
    *,
    events: tuple[Event, ...] | list[Event],
    gas: Gas | None = None,
    tx_hash: str = _TX_HASH,
) -> OnChainTransaction:
    """Build an OnChainTransaction envelope."""
    return OnChainTransaction(
        tx_hash=tx_hash,
        block_number=_BLOCK_NUMBER,
        timestamp_utc=_TIMESTAMP,
        chain="Berachain",
        wallet_label=_WALLET_LABEL,
        wallet_address=_WALLET_ADDRESS,
        gas=gas,
        events=tuple(events),
    )


class TestOnChainThAdapter:
    """Eight test clauses pinning the adapter projection."""

    # ----------------------------------------------------------------- #
    # Clause 1: per-leg-pair projection (multi-leg rendering)           #
    # ----------------------------------------------------------------- #

    def test_multi_out_single_in_emits_paired_then_one_sided_row(self) -> None:
        # A Swap Event (event_id #4) with legs [out WBERA 5, out WBTC 0.005,
        # in KODI-LP 36.65] -> 2 rows: row A pairs out[0] with in[0]
        # (event_id verbatim), row B carries out[1] one-sided with the
        # ".2" event-id suffix. Per-(asset, direction) totals preserved.
        swap = _event(
            event_id=f"{_TX_HASH}#4",
            event_type=EventType.Swap,
            sub_type=None,
            legs=[
                _erc20_leg(asset="WBERA", amount_raw=5, decimals=0, direction="out"),
                _erc20_leg(
                    asset="WBTC",
                    amount_raw=5_000_000_000_000_000,
                    decimals=18,
                    direction="out",
                    token_address="0xTokenWbtc0000000000000000000000000004",
                ),
                _erc20_leg(
                    asset="KODI-LP",
                    amount_raw=3_665,
                    decimals=2,
                    direction="in",
                    token_address="0xTokenKodiLp000000000000000000000000005",
                ),
            ],
        )
        tx = _tx(events=[swap])

        projected = project_on_chain_transactions([tx])

        assert len(projected) == 2
        row_a, row_b = (p.row for p in projected)
        # Row A: out[0] paired with in[0], event_id verbatim.
        assert row_a.sending_currency == "WBERA"
        assert row_a.sending_amount == Decimal(5)
        assert row_a.receiving_currency == "KODI-LP"
        assert row_a.receiving_amount == Decimal("36.65")
        assert row_a.event_id == f"{_TX_HASH}#4"
        # Row B: out[1] one-sided, ".2" suffix.
        assert row_b.sending_currency == "WBTC"
        assert row_b.sending_amount == Decimal("0.005")
        assert row_b.receiving_amount is None
        assert row_b.receiving_currency is None
        assert row_b.event_id == f"{_TX_HASH}#4.2"
        # Distinct sequential row_index values.
        assert sorted({row_a.row_index, row_b.row_index}) == [0, 1]
        # Per-(asset, direction) totals equal the raw legs.
        totals: dict[tuple[str, str], Decimal] = {}
        for row in (row_a, row_b):
            if row.sending_currency is not None:
                totals[(row.sending_currency, "out")] = (
                    totals.get((row.sending_currency, "out"), Decimal(0)) + row.sending_amount
                )
            if row.receiving_currency is not None:
                totals[(row.receiving_currency, "in")] = (
                    totals.get((row.receiving_currency, "in"), Decimal(0)) + row.receiving_amount
                )
        assert totals == {
            ("WBERA", "out"): Decimal(5),
            ("WBTC", "out"): Decimal("0.005"),
            ("KODI-LP", "in"): Decimal("36.65"),
        }

    def test_single_out_multi_in_emits_paired_then_receive_only_row(self) -> None:
        # Legs [out BERA 1, in HONEY 10, in iBGT 3] -> row A (BERA 1 ->
        # HONEY 10) and row B (receive-only iBGT 3, no sending side).
        swap = _event(
            event_id=f"{_TX_HASH}#3",
            event_type=EventType.Swap,
            sub_type=None,
            legs=[
                _native_leg(asset="BERA", amount_raw=1, decimals=0, direction="out"),
                _erc20_leg(asset="HONEY", amount_raw=10, decimals=0, direction="in"),
                _erc20_leg(
                    asset="iBGT",
                    amount_raw=3,
                    decimals=0,
                    direction="in",
                    token_address="0xTokenIbgt000000000000000000000000006",
                ),
            ],
        )
        tx = _tx(events=[swap])

        projected = project_on_chain_transactions([tx])

        assert len(projected) == 2
        row_a, row_b = (p.row for p in projected)
        assert row_a.sending_currency == "BERA"
        assert row_a.sending_amount == Decimal(1)
        assert row_a.receiving_currency == "HONEY"
        assert row_a.receiving_amount == Decimal(10)
        assert row_a.event_id == f"{_TX_HASH}#3"
        assert row_b.sending_amount is None
        assert row_b.sending_currency is None
        assert row_b.receiving_currency == "iBGT"
        assert row_b.receiving_amount == Decimal(3)
        assert row_b.event_id == f"{_TX_HASH}#3.2"

    def test_two_out_two_in_emits_two_paired_rows(self) -> None:
        # Legs [out A, out B, in C, in D] -> exactly rows (A->C) and (B->D),
        # no one-sided remainder.
        swap = _event(
            event_id=f"{_TX_HASH}#2",
            event_type=EventType.Swap,
            sub_type=None,
            legs=[
                _erc20_leg(asset="AAA", amount_raw=1, decimals=0, direction="out"),
                _erc20_leg(
                    asset="BBB",
                    amount_raw=2,
                    decimals=0,
                    direction="out",
                    token_address="0xTokenBbb00000000000000000000000000007",
                ),
                _erc20_leg(asset="CCC", amount_raw=3, decimals=0, direction="in"),
                _erc20_leg(
                    asset="DDD",
                    amount_raw=4,
                    decimals=0,
                    direction="in",
                    token_address="0xTokenDdd00000000000000000000000000008",
                ),
            ],
        )
        tx = _tx(events=[swap])

        projected = project_on_chain_transactions([tx])

        assert len(projected) == 2
        row_a, row_b = (p.row for p in projected)
        assert (row_a.sending_currency, row_a.receiving_currency) == ("AAA", "CCC")
        assert (row_b.sending_currency, row_b.receiving_currency) == ("BBB", "DDD")
        # No one-sided remainder: every side of every leg is represented.
        for row in (row_a, row_b):
            assert row.sending_amount is not None
            assert row.receiving_amount is not None

    def test_single_pair_event_row_unchanged(self) -> None:
        # Single-pair byte-identity (Design Invariant 1): a single-out
        # single-in Swap Event projects to ONE row whose field values equal
        # the pre-multi-leg projection (field-by-field, not object identity).
        swap = _event(
            event_id=f"{_TX_HASH}#2",
            event_type=EventType.Swap,
            sub_type=None,
            legs=[
                _erc20_leg(asset="BGT", amount_raw=1_097_000_000_000_000_000, direction="out"),
                _erc20_leg(
                    asset="HONEY",
                    amount_raw=4_200_000_000_000_000_000,
                    direction="in",
                    token_address="0xTokenHoney0000000000000000000000000002",
                ),
            ],
        )
        tx = _tx(events=[swap])

        projected = project_on_chain_transactions([tx])

        assert len(projected) == 1
        row = projected[0].row
        assert row.utc_instant == _TIMESTAMP
        assert row.type == "exchange"
        assert row.tag == ""
        assert row.sending_wallet == _WALLET_LABEL
        assert row.sending_amount == Decimal("1.097")
        assert row.sending_currency == "BGT"
        assert row.receiving_wallet == _WALLET_LABEL
        assert row.receiving_amount == Decimal("4.2")
        assert row.receiving_currency == "HONEY"
        assert row.tx_hash == _TX_HASH
        assert row.tx_src == _WALLET_ADDRESS
        assert row.tx_dest == "0xCounterParty00000000000000000000000000000b"
        assert row.row_index == 0
        # Single-pair row carries the processor event_id VERBATIM.
        assert row.event_id == f"{_TX_HASH}#2"

    def test_unknown_direction_only_event_emits_review_row(self, caplog) -> None:
        # Review r1 F1: a leg-bearing Event whose legs are ALL direction
        # "unknown" (the processor's shape-1 review path, reachable up to the
        # 1% unknown-leg gate) must still emit ONE projected row (both sides
        # None, event_id VERBATIM) with a WARNING - it must NOT silently
        # vanish from the projection.
        unknown = _event(
            event_id=f"{_TX_HASH}#7",
            event_type=EventType.Unknown,
            sub_type=None,
            legs=[
                _erc20_leg(
                    asset="MYST", amount_raw=2, decimals=0, direction="unknown"
                ),
                _erc20_leg(
                    asset="MYST",
                    amount_raw=3,
                    decimals=0,
                    direction="unknown",
                    token_address="0xTokenMyst00000000000000000000000000c",
                ),
            ],
        )
        tx = _tx(events=[unknown])

        with caplog.at_level(
            logging.WARNING,
            logger="tax_reporting.application.on_chain_th_adapter",
        ):
            projected = project_on_chain_transactions([tx])

        assert len(projected) == 1
        row = projected[0].row
        # Legacy shape: one row, both sides None, event_id verbatim.
        assert row.event_id == f"{_TX_HASH}#7"
        assert row.sending_amount is None
        assert row.sending_currency is None
        assert row.receiving_amount is None
        assert row.receiving_currency is None
        assert row.type == "crypto_deposit"
        assert row.row_index == 0
        # The fallback is loud: a WARNING names the event.
        assert any(
            "no out/in legs" in rec.getMessage() for rec in caplog.records
        ), "expected a WARNING for the zero-out/zero-in Event fallback"

    def test_legless_event_emits_no_row_with_warning(self, caplog) -> None:
        # Review r2 F11: a LEGLESS Event (no legs at all - theoretical today,
        # the processor always attaches legs) must not vanish SILENTLY; the
        # adapter emits no row but logs a WARNING naming the event.
        legless = _event(
            event_id=f"{_TX_HASH}#8",
            event_type=EventType.Unknown,
            sub_type=None,
            legs=[],
        )
        tx = _tx(events=[legless])

        with caplog.at_level(
            logging.WARNING,
            logger="tax_reporting.application.on_chain_th_adapter",
        ):
            projected = project_on_chain_transactions([tx])

        assert projected == []
        assert any(
            "has no legs; emitting no projected row" in rec.getMessage()
            for rec in caplog.records
        ), "expected a WARNING for the legless-Event drop"

    # ----------------------------------------------------------------- #
    # Clause 2: EventType -> Koinly Type/Tag mapping (single dict)      #
    # ----------------------------------------------------------------- #

    def test_event_to_koinly_type_mapping(self) -> None:
        # The mapping is a single auditable dict (plan implementation clause).
        # Expected mapping (design record §9.1 + plan):
        #   Swap            -> exchange          / (empty tag)
        #   Reward          -> crypto_deposit    / Reward
        #   LiquidityDeposit-> transfer          / Liquidity in
        #   GasBurn         -> crypto_withdrawal / Cost
        #   LiquidityWithdraw -> crypto_withdrawal / Liquidity out
        #   Transfer        -> transfer          / (empty tag)
        #   Unknown         -> crypto_deposit    / (empty tag)  (safe default)
        assert EVENT_TYPE_TO_KOINLY == {  # noqa: SIM300
            EventType.Swap: ("exchange", ""),
            EventType.Reward: ("crypto_deposit", "Reward"),
            EventType.LiquidityDeposit: ("transfer", "Liquidity in"),
            EventType.GasBurn: ("crypto_withdrawal", "Cost"),
            EventType.LiquidityWithdraw: ("crypto_withdrawal", "Liquidity out"),
            EventType.Transfer: ("transfer", ""),
            EventType.Unknown: ("crypto_deposit", ""),
        }

    def test_review_reason_persists_to_description_cell(self, tmp_path) -> None:
        # Review r6 F1: an Event flagged upstream carries ``review_reason``;
        # the adapter must carry it onto ``ProjectedThRow`` and the CSV bridge
        # serializer must write it into the existing ``Description`` cell
        # (PT-C-030 family: the reason reaches the user, not just the log).
        # Unflagged rows keep ``Description`` EMPTY so the flag-off
        # byte-identity surface is preserved.
        flagged = _event(
            event_type=EventType.LiquidityDeposit,
            sub_type=SubType.internal_transfer,
            legs=(_erc20_leg(asset="HONEY", amount_raw=10**18, direction="out"),),
            event_id=f"{_TX_HASH}#1",
            review_reason="verify mint vs secondary purchase before filing",
        )
        unflagged = _event(
            event_type=EventType.Swap,
            sub_type=None,
            legs=(
                _erc20_leg(asset="HONEY", amount_raw=10**18, direction="out"),
                _erc20_leg(asset="BGT", amount_raw=10**18, direction="in"),
            ),
            event_id=f"{_TX_HASH}#2",
        )
        projected = project_on_chain_transactions([_tx(events=[flagged, unflagged])])
        assert projected[0].review_reason == flagged.review_reason
        assert projected[1].review_reason is None

        path = tmp_path / "bridge.csv"
        serialize_projected_rows_to_th_csv(projected, path)
        # Read the bridge back via the PRODUCTION reader (preamble/header
        # handling; a raw csv.DictReader mis-detects the header).
        from tax_reporting.infrastructure.koinly_parser import read_koinly_rows

        data_rows = read_koinly_rows(path)
        assert data_rows[0]["Description"] == flagged.review_reason
        assert data_rows[1]["Description"] == ""

    # ----------------------------------------------------------------- #
    # Clause 3: carrier-row gas rule (native leg is the carrier)        #
    # ----------------------------------------------------------------- #

    def test_carrier_row_gas_native_leg(self) -> None:
        # A tx with gas + a Swap Event whose representative leg is the native
        # leg -> Fee Amount on the Swap's row, Fee Amount empty on other rows.
        gas = Gas(asset="BERA", amount_raw=20_000_000_000_000, decimals=18)  # 0.00002 BERA
        swap = _event(
            event_id=f"{_TX_HASH}#1",
            event_type=EventType.Swap,
            sub_type=None,
            legs=[
                _native_leg(amount_raw=500_000_000_000_000_000, direction="out"),
                _erc20_leg(
                    asset="HONEY",
                    amount_raw=4_200_000_000_000_000_000,
                    direction="in",
                ),
            ],
        )
        reward = _event(
            event_id=f"{_TX_HASH}#2",
            event_type=EventType.Reward,
            sub_type=SubType.staking,
            legs=[
                _erc20_leg(asset="BGT", amount_raw=1_097_000_000_000_000_000, direction="in"),
            ],
        )
        tx = _tx(events=[swap, reward], gas=gas)

        projected = project_on_chain_transactions([tx])
        by_event = {p.row.event_id: p for p in projected}

        # The Swap row (derived from the native leg) IS the carrier.
        swap_proj = by_event[f"{_TX_HASH}#1"]
        assert swap_proj.row.sending_currency == "BERA"  # native leg representative
        assert swap_proj.row.sending_amount == Decimal("0.5")
        # The carrier row carries the gas as the fee payload (the only row).
        assert swap_proj.fee is not None
        assert swap_proj.fee.amount == Decimal("0.00002")
        assert swap_proj.fee.currency == "BERA"
        # The non-carrier (Reward) row has NO fee payload.
        reward_proj = by_event[f"{_TX_HASH}#2"]
        assert reward_proj.fee is None

    # ----------------------------------------------------------------- #
    # Clause 4: carrier-row gas rule (no native leg -> first row)       #
    # ----------------------------------------------------------------- #

    def test_carrier_row_gas_no_native_leg(self) -> None:
        # A tx with gas but no native leg (pure ERC-20 reward) -> Fee Amount
        # on the FIRST emitted row.
        gas = Gas(asset="BERA", amount_raw=20_000_000_000_000, decimals=18)
        reward1 = _event(
            event_id=f"{_TX_HASH}#1",
            event_type=EventType.Reward,
            sub_type=SubType.staking,
            legs=[
                _erc20_leg(asset="BGT", amount_raw=1_097_000_000_000_000_000, direction="in"),
            ],
        )
        reward2 = _event(
            event_id=f"{_TX_HASH}#2",
            event_type=EventType.Reward,
            sub_type=SubType.staking,
            legs=[
                _erc20_leg(
                    asset="HONEY",
                    amount_raw=4_200_000_000_000_000_000,
                    direction="in",
                    token_address="0xTokenHoney0000000000000000000000000002",
                ),
            ],
        )
        tx = _tx(events=[reward1, reward2], gas=gas)

        projected = project_on_chain_transactions([tx])
        assert len(projected) == 2
        # The first emitted row (row_index 0, event_id #1) is the carrier.
        carrier = next(p for p in projected if p.row.row_index == 0)
        assert carrier.row.event_id == f"{_TX_HASH}#1"
        assert carrier.fee is not None
        assert carrier.fee.amount == Decimal("0.00002")
        assert carrier.fee.currency == "BERA"
        # The non-carrier row has NO fee payload.
        non_carrier = next(p for p in projected if p.row.row_index == 1)
        assert non_carrier.row.event_id == f"{_TX_HASH}#2"
        assert non_carrier.fee is None

    # ----------------------------------------------------------------- #
    # Clause 9 (validation-harness plan Task 7 / C1): a claim-with-      #
    # carrier tx projects to exactly one Reward row with the gas fee.   #
    # ----------------------------------------------------------------- #

    def test_claim_with_carrier_projects_single_reward_row_with_fee(self) -> None:
        # C1 adapter-level confirmation. Post-fix processor output for a
        # distributor claim carrying a zero-value native gas-carrier leg:
        # ONE Reward Event (the carrier leg is excluded from the Event's
        # legs - design record Q6) plus the parent-tx gas. The adapter must
        # project this to exactly one crypto_deposit/Reward row, and - with
        # no native leg left in any Event - the carrier-row gas rule falls
        # back to the FIRST emitted row, so the gas rides THIS row's fee
        # payload (the Koinly shape for claims: Reward rows + gas as Cost).
        gas = Gas(asset="BERA", amount_raw=20_000_000_000_000, decimals=18)  # 0.00002 BERA
        reward = _event(
            event_id=f"{_TX_HASH}#1",
            event_type=EventType.Reward,
            sub_type=SubType.staking,
            legs=[
                _erc20_leg(
                    asset="BGT",
                    amount_raw=1_097_000_000_000_000_000,
                    direction="in",
                    from_address="0xDistributor0000000000000000000000000000aa",
                ),
            ],
        )
        tx = _tx(events=[reward], gas=gas)

        projected = project_on_chain_transactions([tx])

        # Exactly ONE row: the Reward (the carrier leg produced no Event).
        assert len(projected) == 1
        p = projected[0]
        assert p.row.type == "crypto_deposit"
        assert p.row.tag == "Reward"
        assert p.row.receiving_currency == "BGT"
        assert p.row.receiving_amount == Decimal("1.097")
        # The gas rides the single row's fee payload (no native leg -> the
        # first-row carrier fallback; Reward is not GasBurn, so the B5
        # exception does not skip it).
        assert p.fee is not None
        assert p.fee.amount == Decimal("0.00002")
        assert p.fee.currency == "BERA"

    # ----------------------------------------------------------------- #
    # Clause 1b: carrier row over a MULTI-ROW Event's rows               #
    # ----------------------------------------------------------------- #

    def test_carrier_row_prefers_native_leg_among_multiple_rows(self) -> None:
        # One Event emits 3 rows (3 one-sided out legs); only row 2's
        # representative leg is the native asset -> the fee payload rides
        # row 2 only; rows 1 and 3 carry fee=None.
        gas = Gas(asset="BERA", amount_raw=20_000_000_000_000, decimals=18)  # 0.00002 BERA
        swap = _event(
            event_id=f"{_TX_HASH}#1",
            event_type=EventType.Swap,
            sub_type=None,
            legs=[
                _erc20_leg(asset="HONEY", amount_raw=1, decimals=0, direction="out"),
                _native_leg(amount_raw=2, decimals=0, direction="out"),
                _erc20_leg(
                    asset="BGT",
                    amount_raw=3,
                    decimals=0,
                    direction="out",
                    token_address="0xTokenBgt00000000000000000000000000009",
                ),
            ],
        )
        tx = _tx(events=[swap], gas=gas)

        projected = project_on_chain_transactions([tx])

        assert len(projected) == 3
        by_index = {p.row.row_index: p for p in projected}
        assert by_index[0].fee is None
        assert by_index[1].fee is not None
        assert by_index[1].fee.amount == Decimal("0.00002")
        assert by_index[1].fee.currency == "BERA"
        # Row 2 is the native-leg row.
        assert by_index[1].row.sending_currency == "BERA"
        assert by_index[2].fee is None

    def test_gasburn_event_still_single_row_no_fee(self) -> None:
        # B5 unchanged: a GasBurn Event projects to exactly ONE row with
        # Sent Amount = gas and NO fee payload, even under the per-leg-pair
        # contract (the GasBurn special case stays single-row).
        gas = Gas(asset="BERA", amount_raw=20_000_000_000_000, decimals=18)  # 0.00002 BERA
        gasburn = _event(
            event_id=f"{_TX_HASH}#1",
            event_type=EventType.GasBurn,
            sub_type=SubType.cost_gas,
            legs=[_native_leg(amount_raw=0, direction="out")],
        )
        tx = _tx(events=[gasburn], gas=gas)

        projected = project_on_chain_transactions([tx])

        assert len(projected) == 1
        p = projected[0]
        assert p.row.type == "crypto_withdrawal"
        assert p.row.tag == "Cost"
        assert p.row.sending_amount == Decimal("0.00002")
        assert p.row.sending_currency == "BERA"
        assert p.fee is None

    def test_multi_row_event_rows_carry_distinct_event_ids(self) -> None:
        # Design Invariant 5: an Event (event_id #4) projecting to 3 rows
        # carries event_ids `#4`, `#4.2`, `#4.3` (first verbatim, ".{k}"
        # suffix k >= 2 for the rest); no two rows share (tx_hash, event_id).
        swap = _event(
            event_id=f"{_TX_HASH}#4",
            event_type=EventType.Swap,
            sub_type=None,
            legs=[
                _erc20_leg(asset="AAA", amount_raw=1, decimals=0, direction="out"),
                _erc20_leg(
                    asset="BBB",
                    amount_raw=2,
                    decimals=0,
                    direction="out",
                    token_address="0xTokenBbb00000000000000000000000000007",
                ),
                _erc20_leg(
                    asset="CCC",
                    amount_raw=3,
                    decimals=0,
                    direction="out",
                    token_address="0xTokenCcc000000000000000000000000000a",
                ),
            ],
        )
        tx = _tx(events=[swap])

        projected = project_on_chain_transactions([tx])

        assert len(projected) == 3
        ids = [p.row.event_id for p in projected]
        assert ids == [f"{_TX_HASH}#4", f"{_TX_HASH}#4.2", f"{_TX_HASH}#4.3"]
        keys = [(p.row.tx_hash, p.row.event_id) for p in projected]
        assert len(set(keys)) == 3

    def test_row_index_sequential_across_multi_row_events(self) -> None:
        # row_index is adapter-local ordering over the EXPANDED per-tx row
        # list: tx A's 2 leg pairs -> rows 0,1; tx B's single pair -> row 2.
        tx_a_hash = "0xaaa000000000000000000000000000000000000000000000000000000000001"
        swap_a = _event(
            event_id=f"{tx_a_hash}#1",
            event_type=EventType.Swap,
            sub_type=None,
            legs=[
                _erc20_leg(asset="AAA", amount_raw=1, decimals=0, direction="out"),
                _erc20_leg(
                    asset="BBB",
                    amount_raw=2,
                    decimals=0,
                    direction="out",
                    token_address="0xTokenBbb00000000000000000000000000007",
                ),
                _erc20_leg(asset="CCC", amount_raw=3, decimals=0, direction="in"),
                _erc20_leg(
                    asset="DDD",
                    amount_raw=4,
                    decimals=0,
                    direction="in",
                    token_address="0xTokenDdd00000000000000000000000000008",
                ),
            ],
        )
        tx_a = _tx(events=[swap_a], tx_hash=tx_a_hash)
        swap_b = _event(
            event_id=f"{_TX_HASH}#1",
            event_type=EventType.Swap,
            sub_type=None,
            legs=[
                _erc20_leg(asset="BGT", amount_raw=1, decimals=0, direction="out"),
                _erc20_leg(asset="HONEY", amount_raw=2, decimals=0, direction="in"),
            ],
        )
        tx_b = _tx(events=[swap_b])

        projected = project_on_chain_transactions([tx_a, tx_b])

        assert len(projected) == 3
        assert [p.row.row_index for p in projected] == [0, 1, 2]

    # ----------------------------------------------------------------- #
    # Clause 5: GasBurn row -> Sent Amount=gas, Fee Amount EMPTY (B5)   #
    # ----------------------------------------------------------------- #

    def test_gasburn_row_fee_empty(self) -> None:
        # A GasBurn Event -> projected row has Sent Amount=gas, Fee Amount
        # EMPTY (B5: gas isn't a fee on itself; the carrier-row rule SKIPS
        # GasBurn rows so the fee payload is None on the GasBurn row).
        gas = Gas(asset="BERA", amount_raw=20_000_000_000_000, decimals=18)  # 0.00002 BERA
        gasburn = _event(
            event_id=f"{_TX_HASH}#1",
            event_type=EventType.GasBurn,
            sub_type=SubType.cost_gas,
            legs=[_native_leg(amount_raw=0, direction="out")],
        )
        tx = _tx(events=[gasburn], gas=gas)

        projected = project_on_chain_transactions([tx])
        assert len(projected) == 1
        p = projected[0]
        row = p.row

        # GasBurn -> crypto_withdrawal / Cost.
        assert row.type == "crypto_withdrawal"
        assert row.tag == "Cost"
        # Sent Amount carries the gas (the B5 rule: gas is the value sent).
        assert row.sending_currency == "BERA"
        assert row.sending_amount == Decimal("0.00002")
        # No receiving side on a GasBurn.
        assert row.receiving_amount is None
        assert row.receiving_currency is None
        # The carrier-row rule SKIPS GasBurn rows: the fee payload is EMPTY
        # (gas rides on Sent Amount, NOT on Fee Amount -> B5 double-count
        # prevention).
        assert p.fee is None

    def test_gasless_gasburn_falls_through_to_leg_pair_projection(self) -> None:
        # Review r3 F2: a gas-less GasBurn Event (tx.gas is None) must NOT
        # emit the r1-F1 both-sides-empty review row or crash; it falls
        # through to the generic leg-pair path (one paired row from its
        # out/in legs, event_id verbatim, no fee payload).
        gasburn = _event(
            event_id=f"{_TX_HASH}#9",
            event_type=EventType.GasBurn,
            sub_type=SubType.cost_gas,
            legs=[
                _native_leg(amount_raw=1, decimals=0, direction="out"),
                _erc20_leg(asset="HONEY", amount_raw=2, decimals=0, direction="in"),
            ],
        )
        tx = _tx(events=[gasburn], gas=None)

        projected = project_on_chain_transactions([tx])

        assert len(projected) == 1
        p = projected[0]
        assert p.row.sending_amount == Decimal(1)
        assert p.row.receiving_amount == Decimal(2)
        assert p.row.event_id == f"{_TX_HASH}#9"
        assert p.fee is None

    def test_gasburn_plus_multi_leg_event_gas_counted_once(self) -> None:
        # Review r3 F3 (B5 interaction): a tx containing BOTH a
        # GasBurn-with-gas Event and a multi-leg Swap Event counts the gas
        # exactly once - the GasBurn row carries it as Sent Amount with an
        # empty fee, and every Swap leg-pair row has fee=None (the B5
        # exception suppresses the carrier-row fee attachment, preventing a
        # double count). Event ids stay distinct across the two Events.
        gas = Gas(asset="BERA", amount_raw=20_000_000_000_000, decimals=18)  # 0.00002 BERA
        gasburn = _event(
            event_id=f"{_TX_HASH}#1",
            event_type=EventType.GasBurn,
            sub_type=SubType.cost_gas,
            legs=[_native_leg(amount_raw=0, direction="out")],
        )
        swap = _event(
            event_id=f"{_TX_HASH}#2",
            event_type=EventType.Swap,
            sub_type=None,
            legs=[
                _erc20_leg(asset="HONEY", amount_raw=1, decimals=0, direction="out"),
                _erc20_leg(
                    asset="BGT",
                    amount_raw=2,
                    decimals=0,
                    direction="out",
                    token_address="0xTokenBgt000000000000000000000000000006",
                ),
                _erc20_leg(
                    asset="WBERA",
                    amount_raw=3,
                    decimals=0,
                    direction="in",
                    token_address="0xTokenWbera0000000000000000000000000009",
                ),
            ],
        )
        tx = _tx(events=[gasburn, swap], gas=gas)

        projected = project_on_chain_transactions([tx])

        assert len(projected) == 3
        # (a) exactly one GasBurn single row: Sent Amount = gas, fee None.
        gasburn_rows = [p for p in projected if p.row.tag == "Cost"]
        assert len(gasburn_rows) == 1
        assert gasburn_rows[0].row.sending_amount == Decimal("0.00002")
        assert gasburn_rows[0].fee is None
        # (b) every Swap leg-pair row carries no fee (no double count).
        swap_rows = [p for p in projected if p.row.tag != "Cost"]
        assert len(swap_rows) == 2
        assert all(p.fee is None for p in swap_rows)
        # (c) event_ids stay distinct across the two Events (the multi-leg
        # Event's rows carry the ".{k}" suffixes).
        ids = [p.row.event_id for p in projected]
        assert len(set(ids)) == 3
        assert set(ids) == {f"{_TX_HASH}#1", f"{_TX_HASH}#2", f"{_TX_HASH}#2.2"}

    # ----------------------------------------------------------------- #
    # Clause 6: tx_src / tx_dest populated from the representative leg  #
    # ----------------------------------------------------------------- #

    def test_txsrc_txdest_populated_correctly(self) -> None:
        # tx_src = from_address, tx_dest = to_address of the representative
        # leg; tx_hash = the real hash.
        from_addr = "0xDistributor0000000000000000000000000000aa"
        to_addr = _WALLET_ADDRESS
        reward = _event(
            event_id=f"{_TX_HASH}#1",
            event_type=EventType.Reward,
            sub_type=SubType.staking,
            legs=[
                _erc20_leg(
                    asset="BGT",
                    amount_raw=1_097_000_000_000_000_000,
                    direction="in",
                    from_address=from_addr,
                    to_address=to_addr,
                ),
            ],
        )
        tx = _tx(events=[reward])

        projected = project_on_chain_transactions([tx])
        row = projected[0].row
        # tx_hash is the real on-chain hash (satisfies the resolver AND
        # token_origin's TxHash read per Task 4).
        assert row.tx_hash == _TX_HASH
        # tx_src = the representative leg's from_address.
        assert row.tx_src == from_addr
        # tx_dest = the representative leg's to_address.
        assert row.tx_dest == to_addr

    # ----------------------------------------------------------------- #
    # Clause 7 (LOAD-BEARING, review F6): one row satisfies all THREE   #
    # consumers simultaneously.                                         #
    # ----------------------------------------------------------------- #

    def test_single_row_satisfies_all_three_consumers(self) -> None:
        # For a representative Event of EACH EventType, the projected row
        # simultaneously satisfies:
        #   (a) tx_correlation_key_resolver: non-None tx_hash + populated
        #       event_id;
        #   (b) token_origin._index_withdrawal AND _index_row: non-empty
        #       TxHash for the withdrawal path; non-empty TxSrc/TxDest where
        #       the exchange/transfer provenance path reads them;
        #   (c) fee_filter: Type, Fee Amount, Fee Currency, Sent Amount,
        #       Net Value (EUR) all present-or-explicitly-empty per each
        #       consumer's contract.
        from_addr = "0xDistributor0000000000000000000000000000aa"
        to_addr = "0xRouter0000000000000000000000000000000000c"
        gas = Gas(asset="BERA", amount_raw=20_000_000_000_000, decimals=18)

        # A representative Event for each of the seven EventTypes. Each
        # projection must satisfy the three consumer contracts.
        representative_events: list[Event] = [
            _event(
                event_id=f"{_TX_HASH}#1",
                event_type=EventType.Swap,
                sub_type=None,
                legs=[
                    _native_leg(amount_raw=500_000_000_000_000_000, direction="out"),
                    _erc20_leg(
                        asset="HONEY",
                        amount_raw=4_200_000_000_000_000_000,
                        direction="in",
                        token_address="0xTokenHoney0000000000000000000000000002",
                    ),
                ],
            ),
            _event(
                event_id=f"{_TX_HASH}#2",
                event_type=EventType.Reward,
                sub_type=SubType.staking,
                legs=[
                    _erc20_leg(
                        asset="BGT",
                        amount_raw=1_097_000_000_000_000_000,
                        direction="in",
                        from_address=from_addr,
                        to_address=to_addr,
                    ),
                ],
            ),
            _event(
                event_id=f"{_TX_HASH}#3",
                event_type=EventType.LiquidityDeposit,
                sub_type=SubType.internal_transfer,
                legs=[
                    _native_leg(amount_raw=500_000_000_000_000_000, direction="out"),
                    _erc20_leg(
                        asset="KOD-LP",
                        amount_raw=1_000_000_000_000_000_000,
                        direction="in",
                        token_address="0xLpToken000000000000000000000000000003",
                    ),
                ],
            ),
            _event(
                event_id=f"{_TX_HASH}#4",
                event_type=EventType.LiquidityWithdraw,
                sub_type=None,
                legs=[
                    _erc20_leg(
                        asset="KOD-LP",
                        amount_raw=1_000_000_000_000_000_000,
                        direction="out",
                        token_address="0xLpToken000000000000000000000000000003",
                    ),
                    _native_leg(amount_raw=500_000_000_000_000_000, direction="in"),
                ],
            ),
            _event(
                event_id=f"{_TX_HASH}#5",
                event_type=EventType.Transfer,
                sub_type=None,
                legs=[
                    _native_leg(amount_raw=500_000_000_000_000_000, direction="out"),
                ],
            ),
            _event(
                event_id=f"{_TX_HASH}#6",
                event_type=EventType.GasBurn,
                sub_type=SubType.cost_gas,
                legs=[_native_leg(amount_raw=0, direction="out")],
            ),
            _event(
                event_id=f"{_TX_HASH}#7",
                event_type=EventType.Unknown,
                sub_type=None,
                legs=[
                    _erc20_leg(
                        asset="UNKNOWN",
                        amount_raw=1_000_000_000_000_000_000,
                        direction="in",
                        from_address=from_addr,
                        to_address=to_addr,
                    ),
                ],
            ),
        ]

        projected = project_on_chain_transactions(
            [_tx(events=representative_events, gas=gas)]
        )
        assert len(projected) == 7

        for p in projected:
            row = p.row
            # (a) tx_correlation_key_resolver contract: tx_hash non-None and
            # event_id populated (Invariant 2 amendment, dead-code otherwise).
            assert row.tx_hash is not None
            assert row.tx_hash == _TX_HASH
            assert row.event_id is not None
            assert row.event_id.startswith(f"{_TX_HASH}#")

            # (b) token_origin._index_withdrawal / _index_row contract: the
            # withdrawal path reads TxHash (non-empty here); the exchange and
            # transfer provenance paths read TxSrc/TxDest. For an on-chain row
            # these are the typed row fields tx_hash / tx_src / tx_dest.
            assert row.tx_hash  # non-empty for the withdrawal index
            # Type is one of the Koinly Types token_origin branches on.
            assert row.type in {
                "exchange",
                "transfer",
                "crypto_deposit",
                "crypto_withdrawal",
                "buy",
                "sell",
                "fiat_deposit",
                "fiat_withdrawal",
            }
            # The address fields are populated (token_origin's exchange/
            # transfer provenance reads them on the on-chain path).
            assert row.tx_src is not None
            assert row.tx_dest is not None

            # (c) fee_filter contract: Type present (asserted above); the
            # Fee Amount / Fee Currency fields are NOT TransactionHistoryRow
            # typed fields (they are CSV columns the bridge (Task 11) emits);
            # the carrier-row rule exposes them via the optional `fee`
            # payload. Every row has an explicit side (sending XOR receiving)
            # so the withdrawal/Cost path has a Sent Amount to read.
            if row.type == "crypto_deposit":
                # Reward / Unknown -> receiving side only (no sending side).
                assert row.receiving_amount is not None
                assert row.receiving_currency is not None
            elif row.type == "crypto_withdrawal":
                # GasBurn / LiquidityWithdraw -> sending side carries the asset.
                assert row.sending_amount is not None
                assert row.sending_currency is not None
            else:
                # exchange / transfer -> both sides OR sending side.
                assert (row.sending_amount is not None) or (
                    row.receiving_amount is not None
                )

        # The carrier-row rule picks the Swap row (native leg) as the
        # carrier; exactly ONE row of the seven carries the fee payload.
        fee_rows = [p for p in projected if p.fee is not None]
        assert len(fee_rows) == 1
        # The carrier is the native-leg-derived Swap row, NOT the GasBurn row.
        assert fee_rows[0].row.type == "exchange"

        # Spot-check the GasBurn row specifically: the carrier-row rule
        # SKIPS GasBurn rows so gas rides on Sent Amount, not Fee Amount.
        gasburn_proj = next(
            p for p in projected if p.row.type == "crypto_withdrawal" and p.row.tag == "Cost"
        )
        assert gasburn_proj.row.sending_currency == "BERA"
        assert gasburn_proj.row.sending_amount == Decimal("0.00002")
        assert gasburn_proj.fee is None  # B5: no double-count

    # ----------------------------------------------------------------- #
    # Clause 8: module docstring marks lifecycle (Future Maintainer F5) #
    # ----------------------------------------------------------------- #

    def test_module_docstring_marks_lifecycle(self) -> None:
        # The module docstring MUST declare this module exists ONLY to bridge
        # to the Koinly-shaped TransactionHistoryRow AND name the carrier-row
        # rule as a non-domain accommodation (Future Maintainer F5 mitigation).
        import tax_reporting.application.on_chain_th_adapter as mod

        doc = (mod.__doc__ or "").lower()
        # (a) exists ONLY to bridge to the Koinly-shaped TransactionHistoryRow.
        assert "only to bridge" in doc
        assert "koinly" in doc
        assert "transactionhistoryrow" in doc.replace(" ", "").replace("-", "")
        # (b) the carrier-row gas rule is named as a non-domain accommodation.
        assert "carrier" in doc
        assert "non-domain accommodation" in doc
        # (c) the GasBurn exception is named.
        assert "gasburn" in doc

    def test_every_row_satisfies_all_three_consumers(self) -> None:
        # Plan 2026-08-24 Task 2: EVERY row of a multi-row Event (not just the
        # first) satisfies the three consumer contracts: (a) correlation-key
        # resolver (non-None tx_hash, populated event_id), (b) token-origin
        # indexing (non-empty TxHash; non-empty TxSrc/TxDest where the row's
        # legs populate them), (c) fee-filter (Type present; Fee Amount/Fee
        # Currency present-or-explicitly-empty via the fee payload or its
        # absence; Sent Amount present on the sending side).
        gas = Gas(asset="BERA", amount_raw=20_000_000_000_000, decimals=18)
        swap = _event(
            event_id=f"{_TX_HASH}#5",
            event_type=EventType.Swap,
            sub_type=None,
            legs=[
                _erc20_leg(asset="IBERA", amount_raw=8, decimals=0, direction="out"),
                _erc20_leg(
                    asset="IBERA",
                    amount_raw=1,
                    decimals=0,
                    direction="out",
                    token_address="0xTokenIbera0000000000000000000000000b",
                ),
                _native_leg(amount_raw=9, decimals=0, direction="in"),
            ],
        )
        tx = _tx(events=[swap], gas=gas)

        projected = project_on_chain_transactions([tx])
        assert len(projected) == 2

        seen_pairs: set[tuple[str | None, str | None]] = set()
        for p in projected:
            row = p.row
            # (a) tx_correlation_key_resolver contract.
            assert row.tx_hash is not None
            assert row.tx_hash == _TX_HASH
            assert row.event_id is not None
            seen_pairs.add((row.tx_hash, row.event_id))
            # (b) token_origin indexing contract: non-empty TxHash for the
            # withdrawal index; TxSrc/TxDest populated (both rows' legs carry
            # from/to addresses).
            assert row.tx_hash
            assert row.tx_src is not None
            assert row.tx_dest is not None
            # (c) fee-filter contract: Type present and a known Koinly Type;
            # Fee Amount / Fee Currency present-or-explicitly-empty (the fee
            # payload carries them, or its absence means explicitly empty);
            # the sending side carries the disposal asset.
            assert row.type in {"exchange", "transfer"}
            assert row.sending_amount is not None
            assert row.sending_currency == "IBERA"
            if p.fee is not None:
                assert p.fee.amount == Decimal("0.00002")
                assert p.fee.currency == "BERA"
            # else: Fee Amount/Fee Currency are EXPLICITLY EMPTY on this row.

        # Distinct (tx_hash, event_id) per row (Design Invariant 5).
        assert seen_pairs == {(_TX_HASH, f"{_TX_HASH}#5"), (_TX_HASH, f"{_TX_HASH}#5.2")}
        # Exactly one carrier row carries the fee payload (B5 / gas once).
        fee_rows = [p for p in projected if p.fee is not None]
        assert len(fee_rows) == 1
        # Review r1 overflow: NEITHER row here is a native-derived carrier -
        # the representative leg prefers the pair's OUT leg, and both rows
        # pair ERC-20 IBERA out legs (row 1's native IN leg never becomes the
        # representative). The carrier is therefore the FIRST-ROW fallback.
        # The native-representative mechanism itself is discriminated by
        # test_carrier_row_prefers_native_leg_among_multiple_rows.
        assert fee_rows[0].row.event_id == f"{_TX_HASH}#5"
