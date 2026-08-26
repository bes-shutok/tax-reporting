"""Unit tests for the semantic-equivalence comparator (validation-harness Task 2).

Plan: ``docs/history/plans/2026-08-18-on-chain-validation-harness.md`` (Task 2).
Decision: PD-010 (``docs/maintenance/project-decisions.md``) - two TH
projections of the same on-chain tx are equivalent when, per shared
``tx_hash``, net amounts per ``(asset, direction)`` match within the 8-decimal
display tolerance and each event's Koinly ``(Type, Tag)`` combo is in the
fixed compatibility table. Row cardinality is irrelevant.

The comparator under test consumes the PRODUCTION adapter projection
(``project_on_chain_transactions`` -> ``list[ProjectedThRow]``, carrier-row gas
rule and B5 included) and raw Koinly TH row dicts (the ``read_koinly_rows``
shape). The on-chain fixtures are therefore built through the real adapter so
the comparator is validated against exactly what the harness will see.

Pinned behaviors (each test names its plan bullet):

1. ``test_equal_claim_matches`` - a Reward claim split by Koinly into 3
   ``Reward`` rows plus a ``Cost`` row (the gas) matches the on-chain
   ``Reward`` event + carrier fee with ZERO mismatch records.
2. ``test_amount_within_display_tolerance_matches`` - a 9e-9 diff in a 1-row
   bucket is within tolerance.
3. ``test_amount_at_exact_tolerance_boundary`` - diff exactly equal to the
   tolerance PASSES; one unit beyond (1e-8 + 1e-15) FAILS (both boundary
   sides pinned).
4. ``test_hundred_row_bucket_tolerance_scales`` - a bucket fed by 100 Koinly
   rows whose summed rounding error is 4.7e-7 matches (tolerance 1e-6); a
   non-scaling 1e-8 tolerance would reject it.
5. ``test_type_incompatible_records_mismatch`` - on-chain ``Swap`` vs Koinly
   ``crypto_deposit/Reward`` yields a type-mismatch record carrying BOTH
   combo sets.
6. ``test_koinly_zero_display_cost_flagged`` - Koinly ``Cost`` displaying
   ``0,00000000`` vs on-chain ``GasBurn`` 0.0001 yields an amount-mismatch
   record with ``zero_display=True``.
7. ``test_hash_presence_partition`` - hashes present on one side only yield
   ``on_chain_only`` / ``koinly_only`` records and NO comparison for them.
8. ``test_fee_column_comparison`` - the Koinly ``Fee Amount`` column is
   compared against the on-chain carrier fee on the gas surface; an EMPTY fee
   cell (absent, not zero-displayed) mismatches with ``zero_display=False``.
9. ``test_liquidity_deposit_matches_koinly_to_pool`` (C2, Task 9 GREEN pin)
   - an on-chain ``LiquidityDeposit`` matches Koinly ``transfer/To pool``
   rows: the Task-2 compatibility entry for the real-data Koinly pool
   vocabulary, asserted through the public ``compare_projection`` API.
10. ``test_liquidity_withdraw_matches_koinly_from_pool`` (C2, Task 9 GREEN
    pin) - an on-chain ``LiquidityWithdraw`` matches Koinly
    ``transfer/From pool`` rows (same pin discipline; widened in Task 9 with
    the real-data ``From pool`` Type if the investigation found one).
11. ``test_asset_symbol_case_variance_matches`` (Task 11 Phase-1 tuning) -
    the SAME token under differently-cased tickers (``iBGT`` explorer vs
    ``IBGT`` Koinly, confirmed on the real 2025 baseline) is ONE asset
    bucket; same amount matches.
12. ``test_mirrored_koinly_row_counts_once`` (Task 11 Phase-1 tuning) - a
    Koinly row rendering BOTH sides of one movement (same currency, equal
    sent/received - the wallet-pair / pool-pair echo rendering confirmed on
    the real baseline, e.g. ``transfer/`` self-wallet rows) contributes its
    amount ONCE, on the direction(s) the on-chain projection carries.
13. ``test_gas_folded_into_native_amount_matches`` (Task 11 Phase-1 tuning) -
    when Koinly's gas surface for a currency is empty and the native OUT
    bucket differs from the on-chain amount by EXACTLY the on-chain gas, the
    gas was folded into the displayed amount - equivalent (both the event
    and the gas mismatch are suppressed).
14. ``test_reward_empty_tag_deposit_matches`` / ``test_swap_untyped_rows_match``
    (Task 11 Phase-1 compat widening) - real-baseline Koinly renderings of
    known events with EMPTY tags: reward deposits as ``crypto_deposit/''``
    and swaps as untyped ``crypto_deposit/''`` + ``crypto_withdrawal/''``
    row pairs.

All fixtures are synthetic (PII rule: no real hashes or addresses).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from tax_reporting.application.on_chain_th_adapter import (
    project_on_chain_transactions,
)
from tax_reporting.application.on_chain_validation.comparator import (
    Presence,
    Surface,
    compare_projection,
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
_TX_HASH_ON_CHAIN_ONLY = "0x1111111111111111111111111111111111111111111111111111111111111111"
_TX_HASH_KOINLY_ONLY = "0x2222222222222222222222222222222222222222222222222222222222222222"
_WALLET_ADDRESS = "0xWallet0000000000000000000000000000000000a"
_COUNTERPARTY = "0xCounterParty00000000000000000000000000000b"
_BGT_TOKEN = "0xToken0000000000000000000000000000000001"
_WBTC_TOKEN = "0xToken0000000000000000000000000000000007"
_LP_TOKEN = "0xToken0000000000000000000000000000000002"
_WALLET_LABEL = "Ledger Berachain (BERA)"
_TIMESTAMP = datetime(2025, 3, 1, 12, 0, 0, tzinfo=UTC)
_DECIMALS = 18


# --------------------------------------------------------------------------- #
# Fixture builders (on-chain side goes through the PRODUCTION adapter)         #
# --------------------------------------------------------------------------- #


def _to_raw(amount: Decimal, decimals: int = _DECIMALS) -> int:
    """Exact integer smallest-units for a clean decimal ``amount``."""
    return int(amount.scaleb(decimals))


def _in_leg(*, asset: str, amount: Decimal, token_address: str | None) -> Leg:
    """An inflow leg from the counterparty into the tracked wallet."""
    return Leg(
        asset=asset,
        token_address=token_address,
        amount_raw=_to_raw(amount),
        amount_decimals=_DECIMALS,
        direction="in",
        from_address=_COUNTERPARTY,
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


def _tx(
    tx_hash: str,
    events: list[Event],
    *,
    gas: Gas | None = None,
) -> OnChainTransaction:
    """Wrap events into an ``OnChainTransaction`` (single wallet, no gas)."""
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


def _reward_tx(tx_hash: str, amount: Decimal, *, gas_amount: Decimal | None = None) -> OnChainTransaction:
    """A single-Event Reward claim (BGT inflow); optional parent-tx gas.

    The BGT leg is an ERC-20 leg, so with gas set the adapter's carrier-row
    rule attaches the ``ProjectedFee`` payload to this (only, first) row -
    exactly the production claim shape.
    """
    event = Event(
        event_id=f"{tx_hash}#1",
        event_type=EventType.Reward,
        sub_type=SubType.staking,
        legs=(_in_leg(asset="BGT", amount=amount, token_address=_BGT_TOKEN),),
        parent_tx_hash=tx_hash,
    )
    gas = Gas(asset="BERA", amount_raw=_to_raw(gas_amount), decimals=_DECIMALS) if gas_amount is not None else None
    return _tx(tx_hash, [event], gas=gas)


def _swap_tx(
    tx_hash: str,
    *,
    sent_amount: Decimal,
    received_amount: Decimal,
    sent_asset: str = "BERA",
    received_asset: str = "BGT",
) -> OnChainTransaction:
    """A single-Event Swap: native BERA out, ERC-20 BGT in (no gas)."""
    event = Event(
        event_id=f"{tx_hash}#1",
        event_type=EventType.Swap,
        sub_type=None,
        legs=(
            _out_leg(asset=sent_asset, amount=sent_amount, token_address=None if sent_asset == "BERA" else _BGT_TOKEN),
            _in_leg(asset=received_asset, amount=received_amount, token_address=_BGT_TOKEN),
        ),
        parent_tx_hash=tx_hash,
    )
    return _tx(tx_hash, [event])


def _gasburn_tx(tx_hash: str, gas_amount: Decimal) -> OnChainTransaction:
    """A gas-only tx: one zero-value native out-leg, gas at the tx level.

    The adapter projects the GAS as the row's ``Sent Amount`` with NO fee
    payload (the B5 exception), so the comparator's gas surface sees exactly
    the burned amount.
    """
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


def _lp_deposit_tx(tx_hash: str) -> OnChainTransaction:
    """A single-Event LiquidityDeposit: native BERA out, LP token in (no gas).

    The adapter projects an Event's REPRESENTATIVE legs only (first out leg
    -> sending side, first in leg -> receiving side), so the two-leg shape
    keeps every amount visible in the projection - the fixture a Koinly
    ``transfer/To pool`` row can be built to match. Gas is omitted: this pin
    isolates the ``(Type, Tag)`` compatibility entry (Task 2's tests cover
    the gas surfaces).
    """
    event = Event(
        event_id=f"{tx_hash}#1",
        event_type=EventType.LiquidityDeposit,
        sub_type=SubType.internal_transfer,
        legs=(
            _out_leg(asset="BERA", amount=Decimal("1"), token_address=None),
            _in_leg(asset="UNI-V2", amount=Decimal("5"), token_address=_LP_TOKEN),
        ),
        parent_tx_hash=tx_hash,
    )
    return _tx(tx_hash, [event])


def _lp_withdraw_tx(tx_hash: str) -> OnChainTransaction:
    """A single-Event LiquidityWithdraw: LP token out, native BERA in (no gas).

    Mirror of :func:`_lp_deposit_tx` for the removal direction - the shape a
    Koinly ``transfer/From pool`` row renders.
    """
    event = Event(
        event_id=f"{tx_hash}#1",
        event_type=EventType.LiquidityWithdraw,
        sub_type=SubType.internal_transfer,
        legs=(
            _out_leg(asset="UNI-V2", amount=Decimal("5"), token_address=_LP_TOKEN),
            _in_leg(asset="BERA", amount=Decimal("1"), token_address=None),
        ),
        parent_tx_hash=tx_hash,
    )
    return _tx(tx_hash, [event])


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


def _transfer_in_tx(tx_hash: str, amount: Decimal) -> OnChainTransaction:
    """A single-Event Transfer: native BERA inflow, no out-leg (C3a shape).

    The adapter renders the receiving side only (no out leg), which is the
    projection shape the real-baseline mirrored Koinly ``transfer/`` rows are
    compared against.
    """
    event = Event(
        event_id=f"{tx_hash}#1",
        event_type=EventType.Transfer,
        sub_type=SubType.internal_transfer,
        legs=(_in_leg(asset="BERA", amount=amount, token_address=None),),
        parent_tx_hash=tx_hash,
    )
    return _tx(tx_hash, [event])


def _swap_tx_with_gas(
    tx_hash: str,
    *,
    sent_amount: Decimal,
    received_amount: Decimal,
    gas_amount: Decimal,
) -> OnChainTransaction:
    """A single-Event Swap: native BERA out, ERC-20 BGT in, parent-tx gas.

    The native out leg is the carrier row, so the adapter attaches the gas as
    the row's ``ProjectedFee`` - the production shape whose Koinly baseline
    sometimes folds the gas INTO the displayed native amount instead.
    """
    event = Event(
        event_id=f"{tx_hash}#1",
        event_type=EventType.Swap,
        sub_type=None,
        legs=(
            _out_leg(asset="BERA", amount=sent_amount, token_address=None),
            _in_leg(asset="BGT", amount=received_amount, token_address=_BGT_TOKEN),
        ),
        parent_tx_hash=tx_hash,
    )
    return _tx(tx_hash, [event], gas=Gas(asset="BERA", amount_raw=_to_raw(gas_amount), decimals=_DECIMALS))


@pytest.mark.unit
class TestOnChainThComparator:
    """PD-010 semantic-equivalence pins for ``compare_projection``."""

    def test_equal_claim_matches(self) -> None:
        # Given - the plan's worked example: on-chain Reward BGT 12.345678901
        # (exact) with gas 0.001 BERA lifted onto the carrier row, vs Koinly's
        # rendering as three 8-decimal Reward rows (summing 12.34567890) plus
        # one Cost row carrying the gas.
        projected = project_on_chain_transactions(
            [_reward_tx(_TX_HASH, Decimal("12.345678901"), gas_amount=Decimal("0.001"))]
        )
        koinly_rows = [
            _koinly_row(type_="crypto_deposit", tag="Reward", recv="4.11522630", recv_cur="BGT"),
            _koinly_row(type_="crypto_deposit", tag="Reward", recv="4.11522630", recv_cur="BGT"),
            _koinly_row(type_="crypto_deposit", tag="Reward", recv="4.11522630", recv_cur="BGT"),
            _koinly_row(type_="crypto_withdrawal", tag="Cost", sent="0.001", sent_cur="BERA"),
        ]

        # Then - semantic equivalence: match with zero mismatch records.
        result = compare_projection(koinly_rows, projected)
        assert result.matched_tx_hashes == {_TX_HASH}
        assert result.divergent == ()
        assert result.on_chain_only == ()
        assert result.koinly_only == ()

    def test_amount_within_display_tolerance_matches(self) -> None:
        # Given - a 9e-9 diff in a 1-row bucket (Koinly truncated the 9th
        # decimal), tolerance 1e-8.
        projected = project_on_chain_transactions([_reward_tx(_TX_HASH, Decimal("1.000000009"))])
        koinly_rows = [
            _koinly_row(type_="crypto_deposit", tag="Reward", recv="1.00000000", recv_cur="BGT"),
        ]

        # Then - within tolerance: match.
        result = compare_projection(koinly_rows, projected)
        assert result.matched_tx_hashes == {_TX_HASH}
        assert result.divergent == ()

    def test_amount_at_exact_tolerance_boundary(self) -> None:
        # Given - diff EXACTLY at the 1-row tolerance (1e-8): passes.
        projected_at = project_on_chain_transactions([_reward_tx(_TX_HASH, Decimal("1.00000001"))])
        koinly_rows = [
            _koinly_row(type_="crypto_deposit", tag="Reward", recv="1.00000000", recv_cur="BGT"),
        ]
        result_at = compare_projection(koinly_rows, projected_at)
        assert result_at.matched_tx_hashes == {_TX_HASH}
        assert result_at.divergent == ()

        # And given - one unit beyond the boundary (1e-8 + 1e-15): fails with
        # an amount-mismatch record on the event surface.
        beyond = Decimal("1.00000001") + Decimal("1e-15")
        projected_beyond = project_on_chain_transactions([_reward_tx(_TX_HASH, beyond)])
        result_beyond = compare_projection(koinly_rows, projected_beyond)
        assert result_beyond.matched_tx_hashes == frozenset()
        assert len(result_beyond.divergent) == 1
        record = result_beyond.divergent[0]
        assert record.presence is Presence.SHARED
        assert record.type_mismatch is None
        assert len(record.amount_mismatches) == 1
        mismatch = record.amount_mismatches[0]
        assert mismatch.surface is Surface.EVENT
        assert mismatch.asset == "BGT"
        assert mismatch.direction == "in"
        assert mismatch.on_chain_amount == beyond
        assert mismatch.koinly_amount == Decimal("1.00000000")
        assert mismatch.tolerance == Decimal("1e-8")
        assert mismatch.on_chain_amount - mismatch.koinly_amount == Decimal("1e-8") + Decimal("1e-15")
        assert mismatch.zero_display is False

    def test_hundred_row_bucket_tolerance_scales(self) -> None:
        # Given - a bucket fed by 100 Koinly Reward rows each displaying
        # "0.10000000" (sum 10.00000000) against the exact on-chain amount
        # 10.00000047: summed rounding error 4.7e-7, bucket tolerance
        # 1e-8 x 100 = 1e-6. A non-scaling 1e-8 tolerance would reject this.
        projected = project_on_chain_transactions([_reward_tx(_TX_HASH, Decimal("10.00000047"))])
        koinly_rows = [
            _koinly_row(type_="crypto_deposit", tag="Reward", recv="0.10000000", recv_cur="BGT") for _ in range(100)
        ]

        # Then - the per-bucket tolerance scales with the Koinly row count.
        result = compare_projection(koinly_rows, projected)
        assert result.matched_tx_hashes == {_TX_HASH}
        assert result.divergent == ()

    def test_type_incompatible_records_mismatch(self) -> None:
        # Given - an on-chain Swap rendered by Koinly as reward deposits.
        projected = project_on_chain_transactions(
            [_swap_tx(_TX_HASH, sent_amount=Decimal("1"), received_amount=Decimal("2"))]
        )
        koinly_rows = [
            _koinly_row(type_="crypto_deposit", tag="Reward", recv="2", recv_cur="BGT"),
        ]

        # Then - a type-mismatch record carrying BOTH combo sets.
        result = compare_projection(koinly_rows, projected)
        assert result.matched_tx_hashes == frozenset()
        assert len(result.divergent) == 1
        record = result.divergent[0]
        assert record.type_mismatch is not None
        assert record.type_mismatch.on_chain_combos == {("exchange", "")}
        assert record.type_mismatch.koinly_combos == {("crypto_deposit", "Reward")}

    def test_bridge_tag_combo_reverse_maps_to_reward(self) -> None:
        # The adapter's SubType bridge-tag override renders Reward/bridge
        # (zero-address mint, e.g. bridged WBTC) as ("crypto_deposit",
        # "Bridge"); the comparator's reverse lookup must recover
        # EventType.Reward for that combo instead of the fail-loud Unknown
        # fallback - otherwise every bridge mint lands in a spurious
        # Unknown cluster (found on the live 2025 baseline 2026-08-26).
        event = Event(
            event_id=f"{_TX_HASH}#1",
            event_type=EventType.Reward,
            sub_type=SubType.bridge,
            legs=(_in_leg(asset="WBTC", amount=Decimal("0.01"), token_address=_WBTC_TOKEN),),
            parent_tx_hash=_TX_HASH,
        )
        projected = project_on_chain_transactions([_tx(_TX_HASH, [event], gas=None)])
        koinly_rows = [
            _koinly_row(type_="exchange", tag="", sent="0.01", sent_cur="WBTC"),
        ]

        result = compare_projection(koinly_rows, projected)

        record = result.divergent[0]
        # Recovered type is Reward (the unknown-fallback path would read
        # {EventType.Unknown}); the exchange row stays an EXPLAINABLE
        # Koinly-side divergence, not an unknown-vocabulary error.
        assert record.on_chain_event_types == {EventType.Reward}
        uncovered = record.type_mismatch.uncovered_koinly_combos if record.type_mismatch else frozenset()
        assert ("exchange", "") in uncovered

    @pytest.mark.parametrize(
        "colliding_overrides",
        [
            # Override tag equals a BASE combo tag: (Reward, bridge) -> "Reward"
            # collides with the base (crypto_deposit, "Reward") combo.
            {(EventType.Reward, SubType.bridge): "Reward"},
            # Two overrides colliding on one combo (both keep base type
            # crypto_deposit, same tag).
            {(EventType.Reward, SubType.bridge): "Bridge", (EventType.Reward, SubType.spam): "Bridge"},
        ],
    )
    def test_colliding_override_fails_loud(self, monkeypatch, colliding_overrides) -> None:
        # Review r1 F4: the reverse-map injectivity guard is the only barrier
        # between a future override edit and silent EventType mis-mapping in
        # the validation gate; each collision mode must raise at build time
        # naming the colliding combo (not merely fail a length arithmetic
        # check). The builder derives combos via the adapter's koinly_combo,
        # so the colliding vocabulary is injected by patching the adapter
        # dict it reads.
        import tax_reporting.application.on_chain_th_adapter as adapter_module
        from tax_reporting.application.on_chain_validation.comparator import _build_reverse_combo_map

        monkeypatch.setattr(adapter_module, "SUB_TYPE_TAG_OVERRIDES", dict(colliding_overrides))
        with pytest.raises(RuntimeError, match="claimed twice"):
            _build_reverse_combo_map()

    def test_base_map_collision_fails_loud(self, monkeypatch) -> None:
        # Review r4 (and the corrected r3 note): the restored BASE-map
        # injectivity guard must raise when two EventTypes share one combo -
        # the exact master-era regression the r2 rewrite introduced
        # (last-writer-wins comprehension).
        import tax_reporting.application.on_chain_th_adapter as adapter_module
        from tax_reporting.application.on_chain_validation.comparator import _build_reverse_combo_map

        bad = dict(adapter_module.EVENT_TYPE_TO_KOINLY)
        bad[EventType.Unknown] = bad[EventType.Reward]  # two EventTypes, one combo
        monkeypatch.setattr(adapter_module, "EVENT_TYPE_TO_KOINLY", bad)

        with pytest.raises(RuntimeError, match="combos collide"):
            _build_reverse_combo_map()

    def test_koinly_zero_display_cost_flagged(self) -> None:
        # Given - the C7 accepted-gap shape: Koinly renders the gas-only burn
        # as a Cost row DISPLAYING "0,00000000" (European decimal comma) while
        # the on-chain GasBurn burned 0.0001 BERA.
        projected = project_on_chain_transactions([_gasburn_tx(_TX_HASH, Decimal("0.0001"))])
        koinly_rows = [
            _koinly_row(type_="crypto_withdrawal", tag="Cost", sent="0,00000000", sent_cur="BERA"),
        ]

        # Then - an amount-mismatch record on the gas surface with the
        # zero-display flag set (the Koinly cell DISPLAYS zero).
        result = compare_projection(koinly_rows, projected)
        assert result.matched_tx_hashes == frozenset()
        assert len(result.divergent) == 1
        record = result.divergent[0]
        assert record.type_mismatch is None
        assert len(record.amount_mismatches) == 1
        mismatch = record.amount_mismatches[0]
        assert mismatch.surface is Surface.GAS
        assert mismatch.asset == "BERA"
        assert mismatch.direction is None
        assert mismatch.on_chain_amount == Decimal("0.0001")
        assert mismatch.koinly_amount == Decimal("0")
        assert mismatch.zero_display is True
        assert record.zero_display is True

    def test_hash_presence_partition(self) -> None:
        # Given - one shared matching hash, one hash only in the projection
        # (a Koinly-dropped gas-only tx shape, here a Reward for simplicity),
        # and one hash only in the Koinly rows (a Koinly-only import).
        projected = project_on_chain_transactions(
            [
                _reward_tx(_TX_HASH, Decimal("1.5")),
                _reward_tx(_TX_HASH_ON_CHAIN_ONLY, Decimal("2.5")),
            ]
        )
        koinly_rows = [
            _koinly_row(type_="crypto_deposit", tag="Reward", recv="1.5", recv_cur="BGT"),
            _koinly_row(
                tx_hash=_TX_HASH_KOINLY_ONLY,
                type_="crypto_deposit",
                tag="Reward",
                recv="3.5",
                recv_cur="BGT",
            ),
        ]

        # Then - presence records for the one-sided hashes, NO comparison for
        # them (no mismatch details), and the shared hash matches.
        result = compare_projection(koinly_rows, projected)
        assert result.matched_tx_hashes == {_TX_HASH}
        assert result.divergent == ()
        assert len(result.on_chain_only) == 1
        assert len(result.koinly_only) == 1
        on_chain_only = result.on_chain_only[0]
        koinly_only = result.koinly_only[0]
        assert on_chain_only.tx_hash == _TX_HASH_ON_CHAIN_ONLY
        assert on_chain_only.presence is Presence.ON_CHAIN_ONLY
        assert on_chain_only.type_mismatch is None
        assert on_chain_only.amount_mismatches == ()
        assert koinly_only.tx_hash == _TX_HASH_KOINLY_ONLY
        assert koinly_only.presence is Presence.KOINLY_ONLY
        assert koinly_only.type_mismatch is None
        assert koinly_only.amount_mismatches == ()

    def test_unkeyed_koinly_rows_yield_one_record_each(self) -> None:
        # Given - TWO wallet rows whose TxHash cell is empty (manual/fiat
        # Koinly entries carry no on-chain hash) with DIFFERENT combos, plus
        # one keyed row (review r1 F10: an empty hash is UNKEYED, not a key -
        # N unrelated rows must not collapse into one aggregated record).
        koinly_rows = [
            _koinly_row(tx_hash="", type_="crypto_deposit", tag="Reward", recv="1.5", recv_cur="BGT"),
            _koinly_row(tx_hash="", type_="buy", recv="100", recv_cur="EUR"),
            _koinly_row(tx_hash=_TX_HASH, type_="crypto_deposit", tag="Reward", recv="3.5", recv_cur="BGT"),
        ]

        # Then - one koinly-only record PER unkeyed row (each carrying only
        # its own combo), never one aggregated record for all of them.
        result = compare_projection(koinly_rows, [])
        assert len(result.koinly_only) == 3
        unkeyed = [record for record in result.koinly_only if record.tx_hash == ""]
        assert len(unkeyed) == 2
        assert {f"{type_}/{tag}" for type_, tag in unkeyed[0].koinly_combos} == {"crypto_deposit/Reward"}
        assert {f"{type_}/{tag}" for type_, tag in unkeyed[1].koinly_combos} == {"buy/"}
        assert all(record.presence is Presence.KOINLY_ONLY for record in unkeyed)
        # And the empty hash never participates in the SHARED partition: an
        # unkeyed row cannot "match" a projected row that also lacks a hash.
        assert result.shared_tx_hashes == frozenset()

    def test_fee_column_comparison(self) -> None:
        # Given - Koinly carries the gas in the Fee Amount column (C9) against
        # the on-chain carrier fee: equal values match.
        projected = project_on_chain_transactions([_reward_tx(_TX_HASH, Decimal("1.5"), gas_amount=Decimal("0.002"))])
        koinly_with_fee = [
            _koinly_row(
                type_="crypto_deposit",
                tag="Reward",
                recv="1.5",
                recv_cur="BGT",
                fee="0.002",
                fee_cur="BERA",
            ),
        ]
        result_match = compare_projection(koinly_with_fee, projected)
        assert result_match.matched_tx_hashes == {_TX_HASH}
        assert result_match.divergent == ()

        # And given - an EMPTY Koinly fee cell (absent, not zero-displayed)
        # against the same on-chain carrier fee.
        koinly_without_fee = [
            _koinly_row(type_="crypto_deposit", tag="Reward", recv="1.5", recv_cur="BGT"),
        ]
        result_divergent = compare_projection(koinly_without_fee, projected)
        assert result_divergent.matched_tx_hashes == frozenset()
        assert len(result_divergent.divergent) == 1
        record = result_divergent.divergent[0]
        assert record.type_mismatch is None
        assert len(record.amount_mismatches) == 1
        mismatch = record.amount_mismatches[0]
        assert mismatch.surface is Surface.GAS
        assert mismatch.asset == "BERA"
        assert mismatch.on_chain_amount == Decimal("0.002")
        assert mismatch.koinly_amount == Decimal("0")
        # An empty cell is ABSENT, not displayed-as-zero: zero_display stays
        # False (the flag is reserved for the C7 "0,00000000" display shape).
        assert mismatch.zero_display is False

    def test_liquidity_deposit_matches_koinly_to_pool(self) -> None:
        # C2 (validation-harness plan Task 9, GREEN pin): an on-chain
        # LiquidityDeposit renders on the Koinly side as ``transfer`` rows
        # tagged ``To pool`` - the real-2025-baseline pool vocabulary the
        # Task-2 compatibility entry ships. Asserted through the public
        # compare_projection API (never by re-reading the constant), so the
        # pin fails only if someone narrows EVENT_COMPATIBILITY later.
        projected = project_on_chain_transactions([_lp_deposit_tx(_TX_HASH)])
        koinly_rows = [
            _koinly_row(
                type_="transfer",
                tag="To pool",
                sent="1",
                sent_cur="BERA",
                recv="5",
                recv_cur="UNI-V2",
            ),
        ]

        # Then - the pool-tag rendering is semantically equivalent: match.
        result = compare_projection(koinly_rows, projected)
        assert result.matched_tx_hashes == {_TX_HASH}
        assert result.divergent == ()
        assert result.on_chain_only == ()
        assert result.koinly_only == ()

    def test_liquidity_withdraw_matches_koinly_from_pool(self) -> None:
        # C2 (validation-harness plan Task 9, GREEN pin): an on-chain
        # LiquidityWithdraw renders on the Koinly side as ``transfer`` rows
        # tagged ``From pool``. Same pin discipline as the deposit test; the
        # Task-9 real-data investigation may WIDEN this entry's set (e.g. if
        # Koinly's From-pool rows carry a different Type) - the observed
        # combo gets its own pin alongside this one.
        projected = project_on_chain_transactions([_lp_withdraw_tx(_TX_HASH)])
        koinly_rows = [
            _koinly_row(
                type_="transfer",
                tag="From pool",
                sent="5",
                sent_cur="UNI-V2",
                recv="1",
                recv_cur="BERA",
            ),
        ]

        # Then - the pool-tag rendering is semantically equivalent: match.
        result = compare_projection(koinly_rows, projected)
        assert result.matched_tx_hashes == {_TX_HASH}
        assert result.divergent == ()
        assert result.on_chain_only == ()
        assert result.koinly_only == ()

    # ------------------------------------------------------------------ #
    # 2026-08-22 EVENT_COMPATIBILITY amendment (PD-010 amendment #2):    #
    # Koinly auto-renders pool operations outside its pool vocabulary    #
    # ------------------------------------------------------------------ #

    def test_liquidity_deposit_matches_koinly_exchange_rendering(self) -> None:
        # Given - the real 2025 baseline renders many pool deposits as plain
        # ``exchange`` rows (sent underlying, received LP): Koinly has no
        # native liquidity Type, and the user's manual ``transfer/To pool``
        # marks cover only part of the baseline. LP-snapshot enablement
        # (2026-08-22) reclassified those txs from Swap to LiquidityDeposit,
        # so the entry must accept the same rendering Swap already accepted
        # (amounts still compared strictly; only the TYPE check widens).
        projected = project_on_chain_transactions([_lp_deposit_tx(_TX_HASH)])
        koinly_rows = [
            _koinly_row(
                type_="exchange",
                tag="",
                sent="1",
                sent_cur="BERA",
                recv="5",
                recv_cur="UNI-V2",
            ),
        ]

        # Then - the exchange rendering is semantically equivalent: match.
        result = compare_projection(koinly_rows, projected)
        assert result.matched_tx_hashes == {_TX_HASH}
        assert result.divergent == ()

    def test_liquidity_withdraw_matches_koinly_exchange_rendering(self) -> None:
        # Mirror of the deposit pin: pool removals (LP out, underlying in)
        # render as plain ``exchange`` rows on the real baseline too.
        projected = project_on_chain_transactions([_lp_withdraw_tx(_TX_HASH)])
        koinly_rows = [
            _koinly_row(
                type_="exchange",
                tag="",
                sent="5",
                sent_cur="UNI-V2",
                recv="1",
                recv_cur="BERA",
            ),
        ]

        # Then - the exchange rendering is semantically equivalent: match.
        result = compare_projection(koinly_rows, projected)
        assert result.matched_tx_hashes == {_TX_HASH}
        assert result.divergent == ()

    def test_liquidity_deposit_matches_untyped_row_pair(self) -> None:
        # Given - the baseline also renders pool deposits as the untyped
        # ``crypto_deposit``/``crypto_withdrawal`` row pair (the same shape
        # Swap's Task-11 widening accepted).
        projected = project_on_chain_transactions([_lp_deposit_tx(_TX_HASH)])
        koinly_rows = [
            _koinly_row(type_="crypto_withdrawal", tag="", sent="1", sent_cur="BERA"),
            _koinly_row(type_="crypto_deposit", tag="", recv="5", recv_cur="UNI-V2"),
        ]

        # Then - the untyped pair is an equivalent LiquidityDeposit rendering.
        result = compare_projection(koinly_rows, projected)
        assert result.matched_tx_hashes == {_TX_HASH}
        assert result.divergent == ()

    def test_liquidity_deposit_reward_tag_row_still_mismatches(self) -> None:
        # Negative boundary: ``crypto_deposit/Reward`` is NOT in the
        # LiquidityDeposit entry. Koinly tags reward legs of mixed
        # deposit+claim txs that way, and whether the on-chain classifier
        # should emit a separate Reward event for them is an open question -
        # the harness must keep surfacing those as type mismatches.
        projected = project_on_chain_transactions([_lp_deposit_tx(_TX_HASH)])
        koinly_rows = [
            _koinly_row(type_="crypto_deposit", tag="Reward", recv="5", recv_cur="UNI-V2"),
        ]

        # Then - still divergent on type (not waved through).
        result = compare_projection(koinly_rows, projected)
        assert result.matched_tx_hashes == frozenset()
        assert len(result.divergent) == 1
        assert result.divergent[0].type_mismatch is not None

    # ------------------------------------------------------------------ #
    # 2026-08-22 issuer-glyph ticker aliases (PD-010 amendment #3)        #
    # ------------------------------------------------------------------ #

    def test_issuer_glyph_ticker_alias_matches(self) -> None:
        # Given - the same token renders with its issuer-declared Unicode
        # glyph ticker on the on-chain side (the contract's symbol() says
        # "USD₮0") and the ASCII industry ticker on the Koinly side
        # ("USDT0"); equal amounts then land in two complementary
        # half-empty buckets (confirmed on the real 2025 full-year baseline).
        event = Event(
            event_id=f"{_TX_HASH}#1",
            event_type=EventType.Reward,
            sub_type=SubType.staking,
            legs=(_in_leg(asset="USD₮0", amount=Decimal("0.127242"), token_address=_BGT_TOKEN),),
            parent_tx_hash=_TX_HASH,
        )
        projected = project_on_chain_transactions([_tx(_TX_HASH, [event])])
        koinly_rows = [
            _koinly_row(type_="crypto_deposit", tag="Reward", recv="0.12724200", recv_cur="USDT0"),
        ]

        # Then - one asset bucket regardless of glyph vs ASCII spelling.
        result = compare_projection(koinly_rows, projected)
        assert result.matched_tx_hashes == {_TX_HASH}
        assert result.divergent == ()

    def test_issuer_glyph_alias_does_not_mask_amount_diff(self) -> None:
        # Given - the same glyph/ASCII pair but amounts differing far beyond
        # tolerance (negative: the alias must not weaken the amount check).
        event = Event(
            event_id=f"{_TX_HASH}#1",
            event_type=EventType.Reward,
            sub_type=SubType.staking,
            legs=(_in_leg(asset="USD₮0", amount=Decimal("0.127242"), token_address=_BGT_TOKEN),),
            parent_tx_hash=_TX_HASH,
        )
        projected = project_on_chain_transactions([_tx(_TX_HASH, [event])])
        koinly_rows = [
            _koinly_row(type_="crypto_deposit", tag="Reward", recv="0.22724200", recv_cur="USDT0"),
        ]

        # Then - the merged bucket still mismatches by amount.
        result = compare_projection(koinly_rows, projected)
        assert result.matched_tx_hashes == frozenset()
        assert len(result.divergent) == 1
        assert result.divergent[0].type_mismatch is None
        assert len(result.divergent[0].amount_mismatches) == 1

    def test_issuer_rename_ticker_alias_matches(self) -> None:
        # Given - the issuer renamed a token (contract 0xfcbd14dc... on the
        # 2025 baseline): its ``symbol()`` now declares ``BUSD`` ("Bera USD")
        # while Koinly still renders the pre-rename label ``HONEY``. The same
        # contract's transfers then split into two complementary half-empty
        # buckets across the two sides (313 rows on the real baseline; the
        # address is unique in the dataset and per-tx amounts are equal).
        event = Event(
            event_id=f"{_TX_HASH}#1",
            event_type=EventType.Reward,
            sub_type=SubType.staking,
            legs=(_in_leg(asset="BUSD", amount=Decimal("0.173242"), token_address=_BGT_TOKEN),),
            parent_tx_hash=_TX_HASH,
        )
        projected = project_on_chain_transactions([_tx(_TX_HASH, [event])])
        koinly_rows = [
            _koinly_row(type_="crypto_deposit", tag="Reward", recv="0.17324200", recv_cur="HONEY"),
        ]

        # Then - one asset bucket regardless of pre/post-rename spelling.
        result = compare_projection(koinly_rows, projected)
        assert result.matched_tx_hashes == {_TX_HASH}
        assert result.divergent == ()

    def test_issuer_rename_alias_does_not_mask_amount_diff(self) -> None:
        # Given - the same rename pair but amounts differing far beyond
        # tolerance (negative: the rename alias must not weaken the amount
        # check either).
        event = Event(
            event_id=f"{_TX_HASH}#1",
            event_type=EventType.Reward,
            sub_type=SubType.staking,
            legs=(_in_leg(asset="BUSD", amount=Decimal("0.173242"), token_address=_BGT_TOKEN),),
            parent_tx_hash=_TX_HASH,
        )
        projected = project_on_chain_transactions([_tx(_TX_HASH, [event])])
        koinly_rows = [
            _koinly_row(type_="crypto_deposit", tag="Reward", recv="0.97324200", recv_cur="HONEY"),
        ]

        # Then - the merged bucket still mismatches by amount.
        result = compare_projection(koinly_rows, projected)
        assert result.matched_tx_hashes == frozenset()
        assert len(result.divergent) == 1
        assert result.divergent[0].type_mismatch is None
        assert len(result.divergent[0].amount_mismatches) == 1

    def test_ticker_identity_collision_fails_loud(self) -> None:
        # Given - two DISTINCT token contracts whose tickers fold to the same
        # bucket key (case-folded, glyph-alias-folded). Amount buckets join on
        # the folded ticker because the Koinly baseline CSV carries no
        # contract addresses, so a collision would silently merge two
        # different tokens' amounts: fail loud instead of comparing.
        event = Event(
            event_id=f"{_TX_HASH}#1",
            event_type=EventType.Reward,
            sub_type=SubType.staking,
            legs=(
                _in_leg(asset="DUP", amount=Decimal("1"), token_address=_BGT_TOKEN),
                _in_leg(asset="dup", amount=Decimal("2"), token_address=_LP_TOKEN),
            ),
            parent_tx_hash=_TX_HASH,
        )
        projected = project_on_chain_transactions([_tx(_TX_HASH, [event])])

        # Then - the identity collision is refused with the ticker and both
        # contract addresses in the message (addresses lowercased by the
        # guard; asserted on the message string, not a regex, so ordering
        # inside the address list cannot flake).
        with pytest.raises(ValueError) as exc_info:
            compare_projection([], projected, on_chain_transactions=[_tx(_TX_HASH, [event])])
        message = str(exc_info.value)
        assert "ticker identity collision" in message
        assert "DUP" in message
        assert _BGT_TOKEN.lower() in message
        assert _LP_TOKEN.lower() in message

    # ------------------------------------------------------------------ #
    # Task 11 Phase-1 tuning: real-baseline rendering-variance rules       #
    # ------------------------------------------------------------------ #

    def test_asset_symbol_case_variance_matches(self) -> None:
        # Given (Task 11 Phase-1 triage) - the SAME token renders under
        # differently-cased tickers on the two sides (explorer ``iBGT`` vs
        # Koinly ``IBGT``; confirmed on the real 2025 baseline for iBGT,
        # iBERA, stBGT, USDC.e, uniBTC, brBTC, yBGT/yBERA and the
        # Bault-/BAULT- and KODI-prefixed LP tokens). Same amount, 1-row
        # bucket.
        event = Event(
            event_id=f"{_TX_HASH}#1",
            event_type=EventType.Reward,
            sub_type=SubType.staking,
            legs=(_in_leg(asset="iBGT", amount=Decimal("1.5"), token_address=_BGT_TOKEN),),
            parent_tx_hash=_TX_HASH,
        )
        projected = project_on_chain_transactions([_tx(_TX_HASH, [event])])
        koinly_rows = [
            _koinly_row(type_="crypto_deposit", tag="Reward", recv="1.5", recv_cur="IBGT"),
        ]

        # Then - one asset bucket regardless of ticker casing: match.
        result = compare_projection(koinly_rows, projected)
        assert result.matched_tx_hashes == {_TX_HASH}
        assert result.divergent == ()

    def test_asset_symbol_case_variance_does_not_mask_amount_diff(self) -> None:
        # Given - the same case-variant pair but with amounts differing far
        # beyond tolerance (negative: normalization must not weaken the
        # amount comparison).
        event = Event(
            event_id=f"{_TX_HASH}#1",
            event_type=EventType.Reward,
            sub_type=SubType.staking,
            legs=(_in_leg(asset="iBGT", amount=Decimal("1.5"), token_address=_BGT_TOKEN),),
            parent_tx_hash=_TX_HASH,
        )
        projected = project_on_chain_transactions([_tx(_TX_HASH, [event])])
        koinly_rows = [
            _koinly_row(type_="crypto_deposit", tag="Reward", recv="2.5", recv_cur="IBGT"),
        ]

        # Then - the merged bucket still mismatches by amount.
        result = compare_projection(koinly_rows, projected)
        assert result.matched_tx_hashes == frozenset()
        assert len(result.divergent) == 1
        record = result.divergent[0]
        assert record.type_mismatch is None
        assert len(record.amount_mismatches) == 1
        assert record.amount_mismatches[0].surface is Surface.EVENT
        assert record.amount_mismatches[0].direction == "in"

    def test_mirrored_koinly_row_counts_once(self) -> None:
        # Given (Task 11 Phase-1 triage) - the Koinly wallet-pair echo
        # rendering: ONE movement displayed on BOTH sides of the same row
        # (same currency, equal sent/received), confirmed on the real 2025
        # baseline for self-wallet ``transfer/`` rows. The on-chain
        # projection carries the receiving side only (the C3a Transfer
        # shape).
        projected = project_on_chain_transactions([_transfer_in_tx(_TX_HASH, Decimal("49.95"))])
        koinly_rows = [
            _koinly_row(
                type_="transfer",
                tag="",
                sent="49.95000000",
                sent_cur="BERA",
                recv="49.95000000",
                recv_cur="BERA",
            ),
        ]

        # Then - the row counts ONCE on the on-chain-carried direction: the
        # out-side echo does not create an amount mismatch (the fee VALUE
        # difference is a separate gas-surface question, so the fee cell is
        # omitted here to isolate the mirror rule).
        result = compare_projection(koinly_rows, projected)
        assert result.matched_tx_hashes == {_TX_HASH}
        assert result.divergent == ()

    def test_mirrored_koinly_row_flags_both_sides_when_on_chain_carries_neither(self) -> None:
        # Given - a mirrored row for a currency the on-chain projection
        # carries NOWHERE (the C2 To-pool shape before LP enablement: on-chain
        # Unknown with no amounts). Negative: the mirror rule must NOT hide
        # the unmatched movement.
        projected = project_on_chain_transactions([_reward_tx(_TX_HASH, Decimal("1.5"))])
        koinly_rows = [
            _koinly_row(type_="transfer", tag="To pool", sent="5", sent_cur="UNI-V2", recv="5", recv_cur="UNI-V2"),
        ]

        # Then - BOTH directions mismatch (the movement stays surfaced).
        result = compare_projection(koinly_rows, projected)
        assert result.matched_tx_hashes == frozenset()
        assert len(result.divergent) == 1
        record = result.divergent[0]
        directions = {(m.asset, m.direction) for m in record.amount_mismatches if m.surface is Surface.EVENT}
        assert ("UNI-V2", "in") in directions
        assert ("UNI-V2", "out") in directions

    def test_gas_folded_into_native_amount_matches(self) -> None:
        # Given (Task 11 Phase-1 triage) - the Koinly gas-folding rendering
        # confirmed on the real 2025 baseline: when the Koinly side renders
        # NO gas surface at all (no Cost row, no Fee cell), the native OUT
        # amount DISPLAYS the on-chain amount PLUS the gas (40 +
        # 4.7822676733e-7 displayed as 40.00000048).
        projected = project_on_chain_transactions(
            [
                _swap_tx_with_gas(
                    _TX_HASH,
                    sent_amount=Decimal("40"),
                    received_amount=Decimal("36.653806976104435164"),
                    gas_amount=Decimal("0.00000047822676733"),
                )
            ]
        )
        koinly_rows = [
            _koinly_row(
                type_="exchange",
                tag="",
                sent="40.00000048",
                sent_cur="BERA",
                recv="36.65380698",
                recv_cur="BGT",
            ),
        ]

        # Then - the fold explains BOTH the native-out amount diff and the
        # empty gas surface: match with zero mismatch records.
        result = compare_projection(koinly_rows, projected)
        assert result.matched_tx_hashes == {_TX_HASH}
        assert result.divergent == ()

    def test_gas_fold_rule_requires_empty_koinly_gas_surface(self) -> None:
        # Given - the same amounts but the Koinly side ALSO renders the gas
        # as a Cost row (negative: folding is allowed only when the Koinly
        # gas surface for the currency is empty - otherwise the gas would be
        # counted twice).
        projected = project_on_chain_transactions(
            [
                _swap_tx_with_gas(
                    _TX_HASH,
                    sent_amount=Decimal("40"),
                    received_amount=Decimal("36.653806976104435164"),
                    gas_amount=Decimal("0.00000047822676733"),
                )
            ]
        )
        koinly_rows = [
            _koinly_row(
                type_="exchange",
                tag="",
                sent="40.00000048",
                sent_cur="BERA",
                recv="36.65380698",
                recv_cur="BGT",
            ),
            _koinly_row(type_="crypto_withdrawal", tag="Cost", sent="0.00000048", sent_cur="BERA"),
        ]

        # Then - the native-out amount mismatch STANDS (40.00000048 vs 40).
        result = compare_projection(koinly_rows, projected)
        assert result.matched_tx_hashes == frozenset()
        assert len(result.divergent) == 1
        record = result.divergent[0]
        event_out = [
            m
            for m in record.amount_mismatches
            if m.surface is Surface.EVENT and m.asset == "BERA" and m.direction == "out"
        ]
        assert len(event_out) == 1

    def test_gas_fold_rule_requires_exact_gas_identity(self) -> None:
        # Given - the native-out diff does NOT equal the on-chain gas
        # (negative: a real amount divergence must not launder itself as a
        # fold).
        projected = project_on_chain_transactions(
            [
                _swap_tx_with_gas(
                    _TX_HASH,
                    sent_amount=Decimal("40"),
                    received_amount=Decimal("36.653806976104435164"),
                    gas_amount=Decimal("0.00000047822676733"),
                )
            ]
        )
        koinly_rows = [
            _koinly_row(
                type_="exchange",
                tag="",
                sent="40.00000148",  # 1e-6 above the on-chain amount; gas is 4.78e-7
                sent_cur="BERA",
                recv="36.65380698",
                recv_cur="BGT",
            ),
        ]

        # Then - the amount mismatch stands.
        result = compare_projection(koinly_rows, projected)
        assert result.matched_tx_hashes == frozenset()
        assert any(
            m.surface is Surface.EVENT and m.asset == "BERA" and m.direction == "out"
            for m in result.divergent[0].amount_mismatches
        )

    def test_reward_empty_tag_deposit_matches(self) -> None:
        # Given (Task 11 Phase-1 compat widening) - the real-baseline Koinly
        # rendering of reward deposits with an EMPTY tag (confirmed for both
        # distributor and non-distributor rewards, amounts matching exactly).
        projected = project_on_chain_transactions([_reward_tx(_TX_HASH, Decimal("2.498641741561178768"))])
        koinly_rows = [
            _koinly_row(type_="crypto_deposit", tag="", recv="2.49864174", recv_cur="BGT"),
        ]

        # Then - the untagged deposit is an equivalent Reward rendering.
        result = compare_projection(koinly_rows, projected)
        assert result.matched_tx_hashes == {_TX_HASH}
        assert result.divergent == ()

    def test_swap_untyped_rows_match(self) -> None:
        # Given (Task 11 Phase-1 compat widening) - the real-baseline Koinly
        # rendering of a swap as an UNTYPED deposit + withdrawal row pair
        # (confirmed on the real 2025 baseline, amounts matching exactly
        # after case normalization).
        projected = project_on_chain_transactions(
            [
                _swap_tx(
                    _TX_HASH,
                    sent_amount=Decimal("21.227443380368415859"),
                    received_amount=Decimal("7.480247528147281699"),
                    sent_asset="50WBERA-50LBGT-WEIGHTED",
                    received_asset="LBGT",
                )
            ]
        )
        koinly_rows = [
            _koinly_row(type_="crypto_deposit", tag="", recv="7.48024753", recv_cur="LBGT"),
            _koinly_row(type_="crypto_withdrawal", tag="", sent="21.22744338", sent_cur="50WBERA-50LBGT-WEIGHTED"),
        ]

        # Then - the untyped pair is an equivalent Swap rendering.
        result = compare_projection(koinly_rows, projected)
        assert result.matched_tx_hashes == {_TX_HASH}
        assert result.divergent == ()
