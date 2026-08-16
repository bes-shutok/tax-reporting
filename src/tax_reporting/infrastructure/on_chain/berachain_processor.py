"""The Berachain processor: classify ``OnChainTxRow`` -> ``OnChainTransaction``.

This is the per-chain processor for the ``OnChainExplorer`` transaction
source with ``producer_name="Etherscan-Berachain"``. It is the SECOND step
of the on-chain TH path (Task 9 of the on-chain-tx-tagger plan):

    CSV (Task 7) -> list[OnChainTxRow] -> *this processor* -> list[OnChainTransaction]
                 -> adapter (Task 10) -> TransactionHistoryRow

The processor is PURE: it takes a flat ``list[OnChainTxRow]`` plus injected
dependencies (a :class:`ContractRegistry` and a :class:`LpAutodiscovery`)
and returns ``list[OnChainTransaction]``. It performs NO I/O - no RPC, no
filesystem reads. Classification is a pure function of the rows + the two
injected registries. This keeps the module under the 1000-line / 50-function
guideline (AGENTS.md) by keeping the I/O (CSV read, contract-registry load,
LP-snapshot load, RPC fallback) in their own modules.

Classification rules (leg pattern -> EventType / SubType), grounded in the
design record §9.1 and the plan's 11 test clauses. Rows are grouped by
``tx_hash``; each group becomes ONE :class:`OnChainTransaction`. Within a tx,
the legs are classified into Events:

+-----------------------------------+-------------------------------+---------------------+
| Leg pattern (within one tx_hash)  | EventType                     | SubType             |
+-----------------------------------+-------------------------------+---------------------+
| BIDIRECTIONAL 1 in-asset <-> 1 out| Swap                          | None                |
+-----------------------------------+-------------------------------+---------------------+
| BIDIRECTIONAL receiving LP token  | LiquidityDeposit              | internal_transfer   |
+-----------------------------------+-------------------------------+---------------------+
| MULTI inflow (rewards), no outflow| Reward (one per (tx, asset))  | staking | spam      |
+-----------------------------------+-------------------------------+---------------------+
| reward-claim-then-swap (distrib + | Reward + Swap (linked by      | staking/spam        |
| DEX router both touched)          | parent_event_id)              | (reward)            |
+-----------------------------------+-------------------------------+---------------------+
| GAS_ONLY (zero native outflow,    | GasBurn                       | cost_gas            |
| only gas burned)                  |                               |                     |
+-----------------------------------+-------------------------------+---------------------+
| inflow from unrecognized sender   | Reward                        | spam (+ review)     |
+-----------------------------------+-------------------------------+---------------------+
| direction == "unknown"            | Unknown                       | None (+ review)     |
+-----------------------------------+-------------------------------+---------------------+

Gas: lifted to the parent-tx level (``OnChainTransaction.gas``) from the
group's row-level ``fee_asset`` / ``fee_amount_raw`` (the CSV reader carries
gas per-row; the processor collapses it to one parent-tx gas). If all rows
have empty fee fields, ``gas`` is ``None``. Gas NEVER attaches to an Event
(decision 9: gas is a property of the tx, not of any leg/Event).

Attacker mitigations (see plan CRITICAL RULES):

- F1: ``operator_country`` validation is in the contract-registry LOADER
  (:func:`application.on_chain_config.load_contracts`), not here. The
  processor only READS ``operator_country``; it never sets or validates it.
- F4: rewards from senders NOT in the contract registry -> SubType=spam +
  review (never a clean staking).
- F6: ``wallet_address`` is lower-cased before direction equality (addresses
  can be checksummed or lower-cased).
- F7 (run-level invariant): if >1% of a wallet's legs have
  direction=unknown, raise :class:`FileProcessingError` (fail-loud). This is
  a RUN-LEVEL check (post-aggregation, not per-row) per AGENTS.md.

Design record: ``docs/architecture/on-chain-tx-design.md`` (§3 gas model,
§9.1 tag vocabulary, decisions 4, 8, 9, 15, blocker B3).
Implementation plan: ``docs/history/plans/2026-08-02-on-chain-tx-tagger.md``.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import replace
from typing import Final

from tax_reporting.domain.exceptions import FileProcessingError
from tax_reporting.domain.on_chain_config import ContractRegistry
from tax_reporting.domain.on_chain_transaction import (
    UNKNOWN_DIRECTION_MAX_FRACTION,
    UNKNOWN_DIRECTION_MIN_ABSOLUTE,
    Event,
    EventType,
    Gas,
    Leg,
    OnChainTransaction,
    SubType,
)
from tax_reporting.infrastructure.on_chain.lp_autodiscovery import LpAutodiscovery
from tax_reporting.infrastructure.on_chain.on_chain_csv_reader import OnChainTxRow

_LOGGER = logging.getLogger(__name__)

# Native-asset default decimals. Berachain's BERA is 18-decimal (EVM standard);
# used as a fallback when a fee_asset is present but no native leg supplies
# the decimals explicitly. Recorded here as a named constant (AGENTS.md: no
# magic numbers).
_NATIVE_DEFAULT_DECIMALS: Final = 18

# The native-leg asset is the one with no token_address (it is the chain's
# native coin, not an ERC-20). Used to (a) detect GAS_ONLY txs and (b) source
# the gas decimals when the fee is on the native leg.


class BerachainProcessor:
    """Per-chain processor: ``list[OnChainTxRow]`` -> ``list[OnChainTransaction]``.

    Coordinates LP-autodiscovery, the contract registry, and a pure
    leg-pattern classifier. PURE: no I/O (no RPC, no filesystem). All
    registries are injected.

    Attributes:
        chain: The chain name this processor targets (e.g. ``"Berachain"``).
            Used for the ``OnChainTransaction.chain`` field; the orchestrator
            selects the right processor per chain.
        contract_registry: The loaded + validated :class:`ContractRegistry`
            (reward-distributor / DEX-router / rebate-router tags). Consulted
            for reward-sender verification (F4) and DEX-router detection.
        lp_autodiscovery: The :class:`LpAutodiscovery` (Task 8). Consulted
            for the BIDIRECTIONAL-receiving-LP-token -> LiquidityDeposit
            classification.
    """

    def __init__(
        self,
        *,
        chain: str,
        contract_registry: ContractRegistry,
        lp_autodiscovery: LpAutodiscovery,
    ) -> None:
        """Bind the chain, contract registry, and LP autodiscovery."""
        self.chain = chain
        self.contract_registry = contract_registry
        self.lp_autodiscovery = lp_autodiscovery

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def process(self, rows: list[OnChainTxRow]) -> list[OnChainTransaction]:
        """Classify ``rows`` into ``list[OnChainTransaction]``.

        Groups rows by ``tx_hash`` (each group -> one
        :class:`OnChainTransaction`), lifts gas to the parent-tx level,
        classifies the legs into Events, then runs the run-level
        unknown-direction invariant (Attacker F7) across the whole run.

        Args:
            rows: Flat ``list[OnChainTxRow]`` from the CSV reader (Task 7),
                in any order. Rows sharing a ``tx_hash`` are coalesced into
                one :class:`OnChainTransaction`.

        Returns:
            ``list[OnChainTransaction]``, one per distinct ``tx_hash``, in
            first-seen order.

        Raises:
            FileProcessingError: If the run-level unknown-direction
                invariant is violated (Attacker F7: >1% of legs are
                direction=unknown).
        """
        # Run-level invariant (Attacker F7 / AGENTS.md: validation that
        # depends on complete state runs post-aggregation). Checked FIRST
        # so a degenerate wallet fails before any classification work.
        self._check_unknown_direction_rate(rows)

        groups = _group_by_tx_hash(rows)
        txs: list[OnChainTransaction] = []
        for tx_hash, group_rows in groups.items():
            tx = self._process_group(tx_hash, group_rows)
            txs.append(tx)
        return txs

    # ------------------------------------------------------------------
    # Run-level invariant (Attacker F7)
    # ------------------------------------------------------------------

    @staticmethod
    def _check_unknown_direction_rate(rows: list[OnChainTxRow]) -> None:
        """Raise FileProcessingError if >1% of legs have direction=unknown.

        Post-aggregation run-level check (AGENTS.md). A silently-high unknown
        rate signals a decoder or regression problem; fail-loud rather than
        emit a wallet-full of Unknown Events that downstream consumers would
        mis-handle. The 1% threshold is generous (the observed Berachain
        wallet has ~0% unknown-direction legs post-decoder).

        A small-N absolute floor (``UNKNOWN_DIRECTION_MIN_ABSOLUTE``) prevents
        a single weird tx in a small wallet (e.g. 1/50 = 2%) from aborting;
        the gate fires only when BOTH the fraction threshold is exceeded AND
        the absolute count is at least the floor (a systemic regression still
        fails loud).
        """
        if not rows:
            return
        unknown = sum(1 for r in rows if r.direction == "unknown")
        fraction = unknown / len(rows)
        if (
            unknown > UNKNOWN_DIRECTION_MAX_FRACTION * len(rows)
            and unknown >= UNKNOWN_DIRECTION_MIN_ABSOLUTE
        ):
            raise FileProcessingError(
                f"Run-level invariant violated: {unknown}/{len(rows)} legs "
                f"({fraction:.1%}) have direction=unknown, exceeding the "
                f"{UNKNOWN_DIRECTION_MAX_FRACTION:.0%} threshold AND the "
                f"{UNKNOWN_DIRECTION_MIN_ABSOLUTE}-leg absolute floor; this "
                f"signals a decoder/regression problem - investigate before "
                f"classifying"
            )

    # ------------------------------------------------------------------
    # Per-tx classification
    # ------------------------------------------------------------------

    def _process_group(
        self, tx_hash: str, rows: list[OnChainTxRow]
    ) -> OnChainTransaction:
        """Classify one tx's rows into one :class:`OnChainTransaction`."""
        gas = _lift_gas(rows)
        legs = [_to_leg(r) for r in rows]
        raw_events = self._classify_events(tx_hash, rows, legs)
        # Mint tx-unique event_ids in emission order AFTER classification so
        # the index reflects the actual order (and split Events get distinct
        # ids sharing the parent tx_hash - the parent_event_id linkage).
        events = _mint_event_ids(tx_hash, raw_events)
        # Use the first row's metadata for the parent-tx envelope fields.
        first = rows[0]
        return OnChainTransaction(
            tx_hash=tx_hash,
            block_number=first.block_number,
            timestamp_utc=first.timestamp_utc,
            chain=self.chain,
            wallet_label=first.wallet_label,
            wallet_address=first.wallet_address.lower(),
            gas=gas,
            events=tuple(events),
        )

    def _classify_events(  # noqa: PLR0911 - classification dispatcher with one return per shape
        self, tx_hash: str, rows: list[OnChainTxRow], legs: list[Leg]
    ) -> list[Event]:
        """Classify one tx's legs into a list of Events.

        Dispatch order matters: more-specific shapes are checked before the
        generic BIDIRECTIONAL swap. The shapes, in priority order:

        1. GAS_ONLY (zero-value native outflow, only gas burned) -> GasBurn.
        2. reward-claim-then-swap (reward-distributor AND DEX router both
           touched) -> Reward + Swap (split, linked by parent_event_id).
        3. MULTI inflow with no outflow (multi-token reward claim) -> one
           Reward Event per asset (summed).
        4. BIDIRECTIONAL receiving an LP token -> LiquidityDeposit.
        5. BIDIRECTIONAL 1 in-asset <-> 1 out-asset -> Swap.
        6. Any direction=unknown leg -> Unknown (+ review).
        7. PURE inflow from a single sender -> Reward (single-asset case).
        """
        # 6. Unknown-direction legs emit an Unknown Event each (never guess).
        #    Checked early so a stray unknown leg never gets folded into a
        #    Swap/Reward by a later branch. (The run-level invariant has
        #    already capped the unknown rate at <=1%.)
        if any(leg.direction == "unknown" for leg in legs):
            return self._unknown_events(tx_hash, legs)

        in_legs = [leg for leg in legs if leg.direction == "in"]
        out_legs = [leg for leg in legs if leg.direction == "out"]

        # 1. GAS_ONLY: a single zero-value native outflow whose only economic
        #    movement is the gas burn. Koinly drops these; the native model
        #    emits one GasBurn Event so the PT-deductible gas isn't lost.
        if _is_gas_only(legs):
            return [_gasburn_event(tx_hash, out_legs)]

        # 2. reward-claim-then-swap: both a reward-distributor AND a DEX
        #    router are touched. Split into a Reward Event (the distributor
        #    inflow) and a Swap Event (the DEX-router exchange), linked by
        #    their shared parent_event_id (the tx_hash).
        reward_inflows, dex_swap_legs = self._split_reward_then_swap(rows, legs)
        if reward_inflows is not None:
            return self._reward_then_swap_events(tx_hash, reward_inflows, dex_swap_legs)

        # 3. MULTI inflow, no outflow -> multi-token reward claim. Group
        #    in-legs by asset; emit one Reward Event per (tx, asset) with the
        #    SUMMED amount (matches Koinly's per-asset reward behavior).
        if in_legs and not out_legs:
            return self._multi_token_reward_events(tx_hash, in_legs)

        # 4. BIDIRECTIONAL receiving an LP token -> LiquidityDeposit.
        if in_legs and out_legs and self._receives_lp_token(in_legs):
            return [
                _event(
                    tx_hash,
                    EventType.LiquidityDeposit,
                    SubType.internal_transfer,
                    legs,
                )
            ]

        # 5. BIDIRECTIONAL 1 in-asset <-> 1 out-asset -> Swap.
        if in_legs and out_legs:
            return [_event(tx_hash, EventType.Swap, None, legs)]

        # 7. PURE inflow from a single sender (single-asset reward) -> Reward.
        #    Reached when there is exactly one in-leg and no outflow.
        if in_legs:
            return self._multi_token_reward_events(tx_hash, in_legs)

        # Fallback: nothing matched (e.g. only outflow legs with no in-legs
        # and not GAS_ONLY). Emit one Unknown Event + review rather than
        # silently dropping the tx (AGENTS.md: data-loss conditions must
        # never be silently discarded).
        _LOGGER.warning(
            "tx_hash=%s matched no classification pattern "
            "(in_legs=%d, out_legs=%d); emitting Event(Unknown) for review",
            tx_hash,
            len(in_legs),
            len(out_legs),
        )
        return [_event(tx_hash, EventType.Unknown, None, legs, review=True)]

    # ------------------------------------------------------------------
    # Shape detectors / event builders
    # ------------------------------------------------------------------

    def _receives_lp_token(self, in_legs: list[Leg]) -> bool:
        """Return True iff any in-leg's token is autodiscovery-confirmed LP.

        Uses the injected :class:`LpAutodiscovery` (Task 8): a token is LP
        iff the snapshot (or bytecode fallback) classifies it as such. A
        native-asset in-leg (no token_address) is never LP.
        """
        for leg in in_legs:
            if leg.token_address is None:
                continue
            if self.lp_autodiscovery.is_lp_token(leg.token_address).is_lp:
                return True
        return False

    def _split_reward_then_swap(
        self, rows: list[OnChainTxRow], legs: list[Leg]
    ) -> tuple[list[Leg], list[Leg]] | tuple[None, None]:
        """Detect the reward-claim-then-swap shape.

        Returns ``(reward_inflow_legs, remaining_swap_legs)`` when BOTH a
        reward-distributor AND a DEX router are touched in this tx; else
        ``(None, None)`` (no split). The reward inflow legs are those whose
        ``from_address`` is a registered reward-distributor; the remaining
        legs (the DEX-router exchange) form the Swap.

        The two must co-occur: a reward inflow alone is the multi-token
        reward shape (branch 3); a DEX-router exchange alone is the swap
        shape (branch 5). Only their co-occurrence triggers the split.
        """
        from_addresses = {(r.from_address or "").lower() for r in rows}
        has_distributor = any(
            self._is_reward_distributor(addr) for addr in from_addresses
        )
        has_dex_router = any(
            self._is_dex_router(addr) for addr in from_addresses
        )
        if not (has_distributor and has_dex_router):
            return None, None

        reward_legs: list[Leg] = []
        swap_legs: list[Leg] = []
        # Pair each leg with its source row to read from_address.
        for row, leg in zip(rows, legs, strict=True):
            if leg.direction == "in" and self._is_reward_distributor(
                (row.from_address or "").lower()
            ):
                reward_legs.append(leg)
            else:
                swap_legs.append(leg)
        # Only split if there is at least one reward inflow to extract.
        if not reward_legs:
            return None, None
        return reward_legs, swap_legs

    def _reward_then_swap_events(
        self, tx_hash: str, reward_inflows: list[Leg], swap_legs: list[Leg]
    ) -> list[Event]:
        """Build the (Reward + Swap) split, one Reward per reward asset.

        Both Events share the parent tx_hash (the design's
        ``parent_event_id`` linkage); each gets a unique ``event_id`` within
        the tx. The Reward Event's SubType follows the reward-sender
        verification rule (F4: verified distributor -> staking, else spam).
        """
        events: list[Event] = []
        # One Reward Event per (reward asset, sender). When the asset's legs
        # all share one sender the per-asset list has one summed leg (the
        # common case); when they have >1 distinct sender the heterogeneity
        # guard produces one summed leg per sender (F3).
        for asset_legs in _group_legs_by_asset(reward_inflows, tx_hash).values():
            for summed_leg in asset_legs:
                sub_type = self._reward_sub_type([summed_leg])
                events.append(
                    _event(
                        tx_hash,
                        EventType.Reward,
                        sub_type,
                        [summed_leg],
                        review=(sub_type is SubType.spam),
                    )
                )
        # The Swap Event carries the DEX-router exchange legs.
        events.append(_event(tx_hash, EventType.Swap, None, swap_legs))
        return events

    def _multi_token_reward_events(
        self, tx_hash: str, in_legs: list[Leg]
    ) -> list[Event]:
        """Build one Reward Event per asset, each with the SUMMED amount.

        Matches Koinly's per-asset reward behavior: N in-legs of the same
        asset collapse into ONE Reward Event whose single leg carries the
        summed ``amount_raw``. SubType follows the reward-sender
        verification rule (F4).
        """
        events: list[Event] = []
        for asset_legs in _group_legs_by_asset(in_legs, tx_hash).values():
            for summed_leg in asset_legs:
                sub_type = self._reward_sub_type([summed_leg])
                events.append(
                    _event(
                        tx_hash,
                        EventType.Reward,
                        sub_type,
                        [summed_leg],
                        review=(sub_type is SubType.spam),
                    )
                )
        return events

    def _reward_sub_type(self, asset_legs: list[Leg]) -> SubType:
        """Return the Reward SubType for an asset's legs (F4 verification).

        - staking: the from_address of the representative leg is a
          registered reward-distributor (the verified case).
        - spam: the from_address is NOT in the contract registry
          (Attacker F4: unverified-sender rewards are spam + review, never a
          clean staking).
        """
        # Use the first leg's from_address as the representative sender.
        sender = (asset_legs[0].from_address or "").lower() if asset_legs else ""
        if self._is_reward_distributor(sender):
            return SubType.staking
        # F4: unverified sender -> spam (never clean staking).
        return SubType.spam

    def _unknown_events(self, tx_hash: str, legs: list[Leg]) -> list[Event]:
        """Build one Unknown Event per unknown-direction leg (+ review).

        The processor does NOT guess the direction of an unknown leg
        (AGENTS.md: a classifier ``else`` fallback must use a non-valid
        sentinel + WARNING). Each unknown leg becomes its own Unknown Event
        carrying a review flag so the user cannot mistake it for a clean
        classification.
        """
        _LOGGER.warning(
            "tx_hash=%s has %d unknown-direction leg(s); emitting "
            "Event(Unknown) for each (the processor does not guess direction)",
            tx_hash,
            sum(1 for leg in legs if leg.direction == "unknown"),
        )
        return [
            _event(tx_hash, EventType.Unknown, None, [leg], review=True)
            for leg in legs
            if leg.direction == "unknown"
        ]

    # ------------------------------------------------------------------
    # Contract-registry lookups
    # ------------------------------------------------------------------

    def _is_reward_distributor(self, address: str) -> bool:
        """Return True iff ``address`` is a registered reward-distributor."""
        entry = self.contract_registry.get(address)
        return entry is not None and entry.kind == "reward_distributor"

    def _is_dex_router(self, address: str) -> bool:
        """Return True iff ``address`` is a registered DEX router."""
        entry = self.contract_registry.get(address)
        return entry is not None and entry.kind == "dex_router"


# ----------------------------------------------------------------------
# Module-level pure helpers (no instance state, no I/O)
# ----------------------------------------------------------------------


def _group_by_tx_hash(rows: list[OnChainTxRow]) -> dict[str, list[OnChainTxRow]]:
    """Group rows by ``tx_hash``, preserving first-seen order.

    A ``defaultdict(list)`` would not preserve insertion order of keys
    across Python's hash randomization reliably for the test "first-seen
    order" expectation; this builds an ordered dict explicitly.
    """
    groups: dict[str, list[OnChainTxRow]] = {}
    for row in rows:
        groups.setdefault(row.tx_hash, []).append(row)
    return groups


def _to_leg(row: OnChainTxRow) -> Leg:
    """Project one :class:`OnChainTxRow` to a :class:`Leg`.

    The leg's ``direction`` is taken verbatim from the row (the CSV reader
    already coerced unexpected values to ``"unknown"`` with a review flag).
    Addresses are passed through as-is (lower-casing for equality happens at
    the comparison sites, not here, so the original checksummed form is
    preserved for downstream display).
    """
    return Leg(
        asset=row.asset,
        token_address=row.token_address,
        amount_raw=row.amount_raw,
        amount_decimals=row.amount_decimals,
        direction=row.direction,
        from_address=row.from_address,
        to_address=row.to_address,
    )


def _lift_gas(rows: list[OnChainTxRow]) -> Gas | None:
    """Lift the group's row-level gas to one parent-tx :class:`Gas`.

    The gas comes from the first row that has a non-empty ``fee_asset`` /
    ``fee_amount_raw``. Decimals default to the native leg's
    ``amount_decimals`` when the fee-bearing row is the native leg, else to
    the BERA-standard 18 (recorded as :data:`_NATIVE_DEFAULT_DECIMALS`).
    Returns ``None`` when every row has empty fee fields.
    """
    for row in rows:
        if row.fee_asset and row.fee_amount_raw is not None:
            # Source decimals from this row when it is the native leg; else
            # fall back to the native default (the fee asset is the native
            # coin on EVM chains).
            decimals = (
                row.amount_decimals
                if row.token_address is None
                else _NATIVE_DEFAULT_DECIMALS
            )
            return Gas(
                asset=row.fee_asset, amount_raw=row.fee_amount_raw, decimals=decimals
            )
    return None


def _is_gas_only(legs: list[Leg]) -> bool:
    """Detect the GAS_ONLY shape (decision-record: 139-tx shape).

    A GAS_ONLY tx is one whose only economic movement is the gas burn: a
    single zero-value native outflow. Heuristics: exactly one leg, it is an
    outflow of the native asset (no token_address), and its amount is zero.
    The gas itself lives on the parent tx (lifted by :func:`_lift_gas`);
    this function only decides whether to emit a GasBurn Event.
    """
    if len(legs) != 1:
        return False
    only = legs[0]
    return (
        only.direction == "out"
        and only.token_address is None
        and only.amount_raw == 0
    )


def _gasburn_event(tx_hash: str, out_legs: list[Leg]) -> Event:
    """Build the single GasBurn Event for a GAS_ONLY tx.

    The Event carries the zero-value native outflow leg (the gas itself is
    on the parent tx via :func:`_lift_gas`, NOT on this Event - gas is a
    property of the tx, not of a leg/Event). SubType is ``cost_gas`` so the
    adapter can project it as ``crypto_withdrawal/Cost`` (the documented
    Koinly shape for GAS_ONLY txs).
    """
    return _event(
        tx_hash,
        EventType.GasBurn,
        SubType.cost_gas,
        out_legs,
    )


def _group_legs_by_asset(
    legs: list[Leg], tx_hash: str
) -> dict[str, list[Leg]]:
    """Group legs by ``asset``, SUMMING same-asset legs into one representative.

    Returns ``{asset: [summed_leg, ...]}`` so each asset's value is a list of
    one or more summed legs (one per DISTINCT sender). For the common case
    (one sender per asset) the list has exactly one leg with the summed
    ``amount_raw`` (matches Koinly's per-asset reward collapse). When an
    asset's legs have MORE THAN ONE distinct ``from_address`` (sender), the
    heterogeneity guard fires (AGENTS.md: an aggregator taking ``entries[0]``
    for a field assumed constant must guard when the field varies): the legs
    are re-grouped by ``(from_address or "").lower()`` and one summed leg is
    emitted PER sender, so a spam sender's amount cannot be laundered into a
    clean ``staking`` Reward Event (Attacker F3).

    Args:
        legs: The in-legs to group and sum.
        tx_hash: The parent tx_hash, used in the heterogeneity WARNING so the
            run's review surface names the offending tx (the helper is
            module-level with no ``self``; the callers pass the tx_hash they
            already hold).

    Returns:
        ``{asset: [summed_leg_per_sender, ...]}``. Callers iterate the
        per-asset list to emit one Reward Event per summed leg (one per
        (asset, sender)).
    """
    grouped: dict[str, list[Leg]] = defaultdict(list)
    for leg in legs:
        grouped[leg.asset].append(leg)
    summed: dict[str, list[Leg]] = {}
    for asset, asset_legs in grouped.items():
        senders = {(leg.from_address or "").lower() for leg in asset_legs}
        if len(senders) > 1:
            # Heterogeneity guard (AGENTS.md): the asset's legs come from
            # distinct senders. Re-group by sender and emit one summed leg
            # per sender so reward-sender attribution (F4) is preserved per
            # sender (a spam sender must NOT be laundered into a staking
            # Reward Event by being summed with a verified sender).
            _LOGGER.warning(
                "tx_hash=%s asset=%s has %d distinct reward senders %s; "
                "splitting into one Reward Event per sender (heterogeneity "
                "guard, F3) instead of one collapsed event",
                tx_hash,
                asset,
                len(senders),
                sorted(senders),
            )
            by_sender: dict[str, list[Leg]] = defaultdict(list)
            for leg in asset_legs:
                by_sender[(leg.from_address or "").lower()].append(leg)
            per_sender: list[Leg] = []
            for sender_legs in by_sender.values():
                first = sender_legs[0]
                total = sum(leg.amount_raw for leg in sender_legs)
                per_sender.append(replace(first, amount_raw=total))
            summed[asset] = per_sender
        else:
            first = asset_legs[0]
            total = sum(leg.amount_raw for leg in asset_legs)
            summed[asset] = [replace(first, amount_raw=total)]
    return summed


def _event(
    tx_hash: str,
    event_type: EventType,
    sub_type: SubType | None,
    legs: list[Leg],
    *,
    review: bool = False,
) -> Event:
    """Build an :class:`Event` with a tx-unique sequential ``event_id``.

    ``event_id`` is ``f"{tx_hash}#{n}"`` where ``n`` is the 1-based index of
    this Event within its parent tx (assigned by the caller via the
    ``_EventIdMint`` helper to guarantee uniqueness). When ``review`` is
    True, a WARNING is logged naming the Event so the run's review surface
    is visible (AGENTS.md: data-loss/uncertain conditions log at warning+).
    """
    # NOTE: ``event_id`` minting is done by ``_mint_event_ids`` AFTER the
    # events are built (so the index reflects emission order). This helper
    # leaves event_id as a placeholder; ``_mint_event_ids`` rewrites it.
    if review:
        _LOGGER.warning(
            "tx_hash=%s emitting Event(%s, sub_type=%s) with a review flag "
            "(uncertain classification - investigate)",
            tx_hash,
            event_type.name,
            sub_type.name if sub_type is not None else "<none>",
        )
    return Event(
        event_id="",  # minted by _mint_event_ids
        event_type=event_type,
        sub_type=sub_type,
        legs=tuple(legs),
        parent_tx_hash=tx_hash,
    )


def _mint_event_ids(tx_hash: str, events: list[Event]) -> list[Event]:
    """Assign tx-unique sequential ``event_id``s to ``events`` in place-safe form.

    Returns a new list of Events with ``event_id`` set to
    ``f"{tx_hash}#{n}"`` (1-based). Events without an id placeholder are
    given their final id here so the minting reflects the actual emission
    order (the design's ``parent_event_id`` linkage is the shared
    ``parent_tx_hash``; ``event_id`` distinguishes split Events within a tx).
    """
    return [
        replace(
            event,
            event_id=f"{tx_hash}#{index}",
        )
        for index, event in enumerate(events, start=1)
    ]
