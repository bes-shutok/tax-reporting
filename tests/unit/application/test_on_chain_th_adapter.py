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

from datetime import UTC, datetime
from decimal import Decimal

from tax_reporting.application.on_chain_th_adapter import (
    EVENT_TYPE_TO_KOINLY,
    project_on_chain_transactions,
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
) -> Event:
    """Build an Event with an explicit event_id (matches processor minting)."""
    return Event(
        event_id=event_id,
        event_type=event_type,
        sub_type=sub_type,
        legs=tuple(legs),
        parent_tx_hash=_TX_HASH,
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
    # Clause 1: one row per Event                                       #
    # ----------------------------------------------------------------- #

    def test_one_row_per_event(self) -> None:
        # An OnChainTransaction with 2 Events -> 2 TransactionHistoryRows
        # sharing tx_hash, each with a distinct event_id.
        ev1 = _event(
            event_id=f"{_TX_HASH}#1",
            event_type=EventType.Reward,
            sub_type=SubType.staking,
            legs=[
                _erc20_leg(asset="BGT", amount_raw=1_097_000_000_000_000_000, direction="in"),
            ],
        )
        ev2 = _event(
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
        tx = _tx(events=[ev1, ev2])

        projected = project_on_chain_transactions([tx])

        assert len(projected) == 2
        rows = [p.row for p in projected]
        # Both rows share the real tx_hash.
        assert {row.tx_hash for row in rows} == {_TX_HASH}
        # Distinct event_ids, carried verbatim from the processor.
        assert {row.event_id for row in rows} == {f"{_TX_HASH}#1", f"{_TX_HASH}#2"}
        # row_index is adapter-local ordering, 0-based and unique.
        assert sorted(row.row_index for row in rows) == [0, 1]

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
