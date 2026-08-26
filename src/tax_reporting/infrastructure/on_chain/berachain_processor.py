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
injected registries. The I/O (CSV read, contract-registry load,
LP-snapshot load, position-token-registry load, RPC fallback) lives in its
own modules. KNOWN DEBT: the module is OVER the 1000-line
guideline (AGENTS.md) after the 2026-08-22 unknown-classifier shapes; the
pure leg/gas helpers should be extracted to a sibling module in a planned
follow-up (kept here for now to bound this round's blast radius on the
order-critical dispatcher).

Classification rules (leg pattern -> EventType / SubType), grounded in the
design record §9.1 and the plan's 11 test clauses. Rows are grouped by
``tx_hash``; each group becomes ONE :class:`OnChainTransaction`. Within a tx,
the legs are classified into Events:

+-----------------------------------+-------------------------------+---------------------+
| Leg pattern (within one tx_hash)  | EventType                     | SubType             |
+-----------------------------------+-------------------------------+---------------------+
| BIDIRECTIONAL 1 in-asset <-> 1 out| Swap                          | None                |
+-----------------------------------+-------------------------------+---------------------+
| BIDIRECTIONAL sending LP/vault    | LiquidityWithdraw             | internal_transfer   |
| receipt token (island unstake;    | (+ review WARNING when the    |                     |
| registry-vault-target LST unstake | LP-member receive side is     |                     |
| is vault-target gated; LP-member  | not the redemption            |                     |
| sends to a non-counterparty       | counterparty: possible        |                     |
| recipient carry a review flag)    | disposal)                     |                     |
+-----------------------------------+-------------------------------+---------------------+
| BIDIRECTIONAL receiving LP token  | LiquidityDeposit              | internal_transfer   |
| or position-NFT-kind registry     | (+ review when only the       |                     |
| member token whose mint shape     | receives-from-vault arm       |                     |
| touches a registry vault (payment | fired - a provenance-only     |                     |
| to the vault OR NFT arriving from | mint, ambiguous with a vault- |                     |
| the vault; non-vault market       | seller resale)                |                     |
| purchases stay Swap)              |                               |                     |
+-----------------------------------+-------------------------------+---------------------+
| PURE outflow of LP-snapshot /     | LiquidityDeposit              | internal_transfer   |
| position-registry member tokens,  |                               | (+ review when no   |
| or multi-leg zap outflow (all     |                               | member signal)      |
| non-gas out-legs economic)        |                               |                     |
+-----------------------------------+-------------------------------+---------------------+
| PURE single-leg outflow (non-     | LiquidityDeposit              | internal_transfer   |
| member token) whose tx recipient  |                               |                     |
| is a position-registry VAULT      |                               |                     |
| (kind-gated)                      |                               |                     |
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
| PURE inflow from a registered     | Transfer                      | internal_transfer   |
| self-wallet (C3)                  |                               |                     |
+-----------------------------------+-------------------------------+---------------------+
| PURE outflow to a registered      | Transfer                      | internal_transfer   |
| self-wallet (C3)                  |                               |                     |
+-----------------------------------+-------------------------------+---------------------+
| direction == "unknown"            | Unknown                       | None (+ review)     |
+-----------------------------------+-------------------------------+---------------------+

Gas: lifted to the parent-tx level (``OnChainTransaction.gas``) from the
group's row-level ``fee_asset`` / ``fee_amount_raw`` (the CSV reader carries
gas per-row; the processor collapses it to one parent-tx gas). If all rows
have empty fee fields, ``gas`` is ``None``. Gas NEVER attaches to an Event
(decision 9: gas is a property of the tx, not of any leg/Event). Because
the gas lives on the tx, a zero-value NATIVE outflow leg (the gas carrier,
design record Q6) is excluded from the economic in/out partition inside
``_classify_events`` - except in the GAS_ONLY shape, whose single carrier
leg IS the GasBurn Event's payload.

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
from tax_reporting.infrastructure.on_chain.position_token_registry import (
    PositionTokenRegistry,
)

_LOGGER = logging.getLogger(__name__)

# Native-asset default decimals. Berachain's BERA is 18-decimal (EVM standard);
# used as a fallback when a fee_asset is present but no native leg supplies
# the decimals explicitly. Recorded here as a named constant (AGENTS.md: no
# magic numbers).
_NATIVE_DEFAULT_DECIMALS: Final = 18

# Minimum number of economic out-legs for the pure-outflow multi-leg (zap-add)
# deposit shape: a zap routes one input through several deposits/ swaps at once.
_MIN_MULTI_LEG_OUTLEGS: Final = 2

# ERC-20 mint sentinel: a Transfer event FROM the zero address is new token
# issuance (bridge deposit, e.g. bridged WBTC, or an on-chain mint/airdrop) -
# no external sender exists. Protocol constant, not chain identity; the
# BRIDGE reading is a classification choice in _reward_sub_type, not part of
# the sentinel's meaning (review r1 F14).
_ZERO_ADDRESS: Final = "0x0000000000000000000000000000000000000000"


def _is_zero_address(address: str | None) -> bool:
    """True iff ``address`` is the ERC-20 mint sentinel (review r5: single
    owner for the None-coalesce + lowercase normalization so the three
    classification sites cannot drift)."""
    return (address or "").lower() == _ZERO_ADDRESS

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
            (reward-distributor / DEX-router / rebate-router / self-wallet
            tags). Consulted for reward-sender verification (F4),
            DEX-router detection, and self-transfer detection (C3).
        lp_autodiscovery: The :class:`LpAutodiscovery` (Task 8). Consulted
            for the BIDIRECTIONAL-receiving-LP-token -> LiquidityDeposit
            classification.
        position_token_registry: The :class:`PositionTokenRegistry` (plan
            2026-08-22 Task 3) - address-keyed LST / staking-position
            allowlist gating the pure-outflow LST deposit rule. ``None``
            behaves as empty (Unknown fallback).
    """

    def __init__(
        self,
        *,
        chain: str,
        contract_registry: ContractRegistry,
        lp_autodiscovery: LpAutodiscovery,
        position_token_registry: PositionTokenRegistry | None = None,
    ) -> None:
        """Bind the chain, contract registry, LP autodiscovery, and position registry.

        ``position_token_registry`` (plan 2026-08-22 Task 3) gates the
        pure-outflow LST deposit rule. ``None`` behaves as an EMPTY registry
        (LST outflows fall to the Unknown fallback); the production wiring
        injects the loaded registry at
        :meth:`application.on_chain_th_substitution.OnChainThSubstituter._build_processor`.
        """
        self.chain = chain
        self.contract_registry = contract_registry
        self.lp_autodiscovery = lp_autodiscovery
        self.position_token_registry = position_token_registry

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

    def _classify_events(  # noqa: PLR0911, PLR0912 - classification dispatcher: one return/branch per recognized shape
        self, tx_hash: str, rows: list[OnChainTxRow], legs: list[Leg]
    ) -> list[Event]:
        """Classify one tx's legs into a list of Events.

        Dispatch order matters: earlier shapes consume later ones. The
        pure-inflow reward shape catches EVERY pure inflow, so the
        self-wallet check must precede it; a pure outflow passes the
        bidirectional branches untouched and reaches only the self-wallet
        check, the pure-outflow deposit rules, and the Unknown fallback.
        Shapes in ACTUAL dispatch order (plan 2026-08-22 Task 3 added the
        vault-withdraw rule as shape 6, slotting BEFORE the AMM-deposit
        read of the old shape 6 - which would otherwise classify a
        receipt-token send as a deposit - and the pure-outflow deposit
        rules as shapes 10-11, slotting AFTER the self-wallet outbound
        transfer, which keeps precedence):

        1. Any direction=unknown leg -> one Unknown Event per unknown leg
           (+ review); never guess a direction.
        2. GAS_ONLY (single zero-value native outflow, only gas burned) ->
           GasBurn (keeps its UNFILTERED leg - the carrier IS the payload).
        3. reward-claim-then-swap (reward-distributor AND DEX router both
           touched) -> Reward + Swap (split, linked by parent_event_id).
        4. PURE inflow whose single counterparty sender is a registered
           ``self_wallet`` -> Transfer/internal_transfer (C3a; before the
           reward branch, which would otherwise consume the shape).
        5. PURE inflow with no outflow (multi-token reward claim) -> one
           Reward Event per (asset, sender), summed. A leg MINTED from the
           zero address (bridge issuance, no external sender - e.g. bridged
           WBTC) yields SubType=bridge + review with a bridge-specific
           reason instead of the F4 spam rule (user direction 2026-08-26:
           CEX->bridge transfers must not read as rewards).
        6. BIDIRECTIONAL SENDING a member token, split by member source
           (plan 2026-08-23 Task 1). BEFORE shape 7: the deposit read
           would otherwise classify the receive side of the same tx as the
           event's direction; the send direction is the withdrawal.
           (a) LP-snapshot member out-leg (island unstake, AMM
           remove-liquidity) -> LiquidityWithdraw; clean only when EVERY
           member out-leg's recipient equals some economic in-leg's sender
           (case-insensitive; a missing recipient keeps a ``<missing>``
           sentinel and is never coverable); if any member out-leg's
           recipient is uncovered, the entry is still LiquidityWithdraw but
           carries a review WARNING naming the uncovered recipient(s)
           (possible disposal).
           (b) registry-ONLY member out-leg (e.g. an LST): a SINGLE leg
           fires LiquidityWithdraw ONLY when its to_address is a registry
           VAULT (kind-gated); anything else (a DEX-pair exchange included)
           falls through to Swap with NO shape-6 review warning. A batch
           with at least one vault-target leg fires LiquidityWithdraw, and
           every registry-member leg whose recipient is NOT a registry
           vault (or is missing) carries a review WARNING naming it
           (possible disposal); a batch with no vault-target leg keeps the
           Swap fall-through.
        7. BIDIRECTIONAL receiving an LP token, or a position-NFT-kind
           registry member whose mint shape touches a registry vault
           (payment to the vault OR NFT arriving from the vault) ->
           LiquidityDeposit.
        8. BIDIRECTIONAL 1 in-asset <-> 1 out-asset -> Swap.
        9. PURE outflow whose single recipient is a registered
           ``self_wallet`` -> Transfer/internal_transfer (C3b; keeps
           precedence over the pure-outflow deposit rules - an internal
           self-transfer is never a deposit).
        10. PURE outflow deposit rules: (a) every economic out-leg token
            is an LP-snapshot or position-registry member (island/vault
            re-staking, LST deposit), or (b) a SINGLE economic out-leg
            whose token is NOT a member but SOME out-direction leg
            recipient - INCLUDING the zero-value native gas carrier (the
            tx-level ``to``) - IS a position-registry VAULT member
            (deposit routed through a registered position-NFT vault; the
            ERC-721 receipt is invisible to txlist/tokentx/txlistinternal;
            Task 5 fix for the residual sig-2 family) -> LiquidityDeposit.
        11. PURE outflow with >=2 economic out-legs (zap-add / BERA+LST
            deposit shapes) -> LiquidityDeposit with ALL non-gas out-legs
            economic (a NON-ZERO native out-leg is economic, not a gas
            carrier - only zero-value native legs are carriers). Carries a
            review flag when NO member signal is present.
        12. Fallback -> one Unknown Event + review (never silently dropped).

        Before shapes 3-8, zero-value NATIVE outflow legs (gas carriers,
        design record Q6) are excluded from the in/out partition and from
        the Event leg lists: the actual gas is already lifted to the parent
        tx (:func:`_lift_gas`), so the carrier is not an economic movement.
        Shape 2 (GAS_ONLY) keeps its UNFILTERED leg (a gas-only tx's single
        leg IS the carrier shape); zero-value TOKEN legs are never excluded
        (narrow rule: only the chain's gas asset has no ``token_address``).
        """
        # 1. Unknown-direction legs emit an Unknown Event each (never
        #    guess). Checked first so a stray unknown leg never gets folded
        #    into a Swap/Reward/Transfer by a later branch. (The run-level
        #    invariant has already capped the unknown rate at <=1%.)
        if any(leg.direction == "unknown" for leg in legs):
            return self._unknown_events(tx_hash, legs)

        # Unfiltered direction split - consumed ONLY by the GAS_ONLY shape
        # below (its Event must carry the unfiltered carrier leg). Every
        # later shape partitions the ECONOMIC legs (C1 exclusion below), so
        # the two partitions below carry distinct names (the
        # old rebinding made the same names mean different things above and
        # below the C1 exclusion).
        unfiltered_out_legs = [leg for leg in legs if leg.direction == "out"]

        # 2. GAS_ONLY: a single zero-value native outflow whose only economic
        #    movement is the gas burn. Koinly drops these; the native model
        #    emits one GasBurn Event so the PT-deductible gas isn't lost.
        #    Keeps the UNFILTERED out-legs: a gas-only tx's single leg IS
        #    the carrier shape, and the Event must still carry it (the
        #    adapter renders its TxSrc/TxDest from that leg).
        if _is_gas_only(legs):
            return [_gasburn_event(tx_hash, unfiltered_out_legs)]

        # C1 gas-carrier exclusion (design record Q6): a zero-value NATIVE
        #    outflow leg is the gas carrier, not an economic leg; the actual
        #    gas is already lifted to the parent tx. Drop carriers from the
        #    economic partition so a claim-with-carrier tx classifies by its
        #    economic legs alone (Reward, not Swap). The exclusion applies
        #    ONLY where an economic leg remains: when every leg is a carrier
        #    (and the tx is not GAS_ONLY, handled above), the legs stay
        #    unfiltered so no Event is built from an empty list.
        economic_legs = [leg for leg in legs if not _is_gas_carrier(leg)]
        if not economic_legs:
            economic_legs = legs
        in_legs = [leg for leg in economic_legs if leg.direction == "in"]
        out_legs = [leg for leg in economic_legs if leg.direction == "out"]

        # 3. reward-claim-then-swap: both a reward-distributor AND a DEX
        #    router are touched. Split into a Reward Event (the distributor
        #    inflow) and a Swap Event (the DEX-router exchange), linked by
        #    their shared parent_event_id (the tx_hash).
        reward_inflows, dex_swap_legs = self._split_reward_then_swap(rows, legs)
        if reward_inflows is not None:
            # C1: gas carriers are not swap legs; drop them from the split's
            # swap side. When nothing economic remains there, the tx is a
            # pure claim - fall through to shape 4/5 instead of emitting a
            # legless Swap Event.
            economic_swap_legs = [
                leg for leg in dex_swap_legs if not _is_gas_carrier(leg)
            ]
            if economic_swap_legs:
                return self._reward_then_swap_events(
                    tx_hash, reward_inflows, economic_swap_legs
                )

        # 4. C3a self-wallet inbound: a pure inflow whose single
        #    counterparty sender (the in-legs' from-addresses) is a
        #    registered ``self_wallet`` is an internal self-transfer, not
        #    income. BEFORE shape 5: the pure-inflow reward branch consumes
        #    every pure-inflow shape, so a check placed later never sees
        #    inbound self-transfers.
        if in_legs and not out_legs and self._single_sender_is_self_wallet(in_legs):
            return [_transfer_event(tx_hash, in_legs)]

        # 5. MULTI inflow, no outflow -> multi-token reward claim. Group
        #    in-legs by asset; emit one Reward Event per (tx, asset, sender)
        #    with the SUMMED amount (matches Koinly's per-asset reward
        #    behavior).
        if in_legs and not out_legs:
            return self._multi_token_reward_events(tx_hash, in_legs)

        # 6. BIDIRECTIONAL SENDING a member token, split by member source
        #    (plan 2026-08-23 Task 1). BEFORE shape 7: the deposit read
        #    below classifies by the RECEIVE side, so a withdraw (send the
        #    receipt, receive the underlying) would misclassify as a
        #    deposit/Swap; the SEND direction of the receipt token is the
        #    withdrawal.
        #    (a) LP-snapshot member out-leg (island unstake / AMM
        #    remove-liquidity) -> LiquidityWithdraw, CLEAN only when the
        #    redemption-counterparty predicate holds (EVERY member out-leg's
        #    to_address equals some economic in-leg's from_address,
        #    case-insensitive; in-leg senders that are empty or the literal
        #    sentinel cannot provide coverage); otherwise the same Event
        #    carries a review WARNING naming the mismatched counterparty (the
        #    receive side may be a third-party sale, not a vault redemption).
        #    In a same-tx LP+registry mix this branch folds
        #    the registry-member out-legs into its review computation - the
        #    tx is clean ONLY when the LP subset predicate holds AND every
        #    registry-member out-leg targets a registry vault.
        #    (b) registry-ONLY member out-leg (position-registry member,
        #    e.g. an LST): a SINGLE leg fires LiquidityWithdraw ONLY when
        #    its to_address is a registry VAULT (kind-gated); a batch with
        #    at least one vault-target leg fires LiquidityWithdraw, and
        #    every registry-member leg whose recipient is NOT a registry
        #    vault (or is missing) carries a review WARNING naming it
        #    (one vault leg must not silently clean a
        #    sibling disposal leg). Everything else (a single DEX-pair
        #    counterparty included) falls through to Swap with NO review
        #    warning: registry entries are identity data, not per-cluster
        #    rules (the LBGT provenance rule).
        if in_legs and out_legs:
            # Full evaluation (no `any()` short-circuit) is intentional: the
            # recipient set below needs EVERY member out-leg, so later legs
            # must still be probed after the first snapshot member is found
            # (deliberate deviation from the plan's any() wording).
            lp_member_legs = [
                leg
                for leg in out_legs
                if leg.token_address is not None
                and self.lp_autodiscovery.is_lp_token(leg.token_address).is_lp
            ]
            if lp_member_legs:
                # EVERY member out-leg recipient must be covered
                # by an in-leg sender (subset, not ANY-match) - in a mixed
                # batch tx one covered leg must not clean an uncovered sale
                # leg. A MISSING recipient keeps a "<missing>"
                # marker (never coverable, fails closed into review) while
                # missing in-leg senders are excluded, so the empty-string
                # sentinel cannot self-collide into a clean match.
                member_recipients = {
                    (leg.to_address or "<missing>").lower() for leg in lp_member_legs
                }
                # A from_address cell holding the literal
                # "<missing>" marker (hand-edited CSV) must not spoof
                # coverage of the recipient sentinel - senders equal to the
                # sentinel are excluded, so the check stays fail-closed.
                in_senders = {
                    (leg.from_address or "").lower()
                    for leg in in_legs
                    if (leg.from_address or "").lower() not in ("", "<missing>")
                }
                unmatched = member_recipients - in_senders
                # Branch (a) must not shadow the registry-side
                # review condition in a same-tx LP+registry
                # mix: the (a) block returns before the registry arm below,
                # so the registry-member out-legs whose recipients are NOT
                # registry vaults (or are missing) are folded into THIS
                # branch's review computation. A mixed tx is clean ONLY when
                # the LP subset predicate holds AND every registry-member
                # out-leg targets a registry vault; one combined WARNING
                # names both the uncovered LP recipients and the non-vault
                # registry legs.
                registry_nonvault_recipients: set[str] = set()
                if self.position_token_registry is not None:
                    # Shared with the registry-only arm below so
                    # the two branches cannot drift apart (sibling shapes, one
                    # predicate).
                    registry_nonvault_recipients = {
                        (leg.to_address or "<missing>").lower()
                        for leg in self._registry_member_legs_without_vault_target(
                            out_legs
                        )
                    }
                if not unmatched and not registry_nonvault_recipients:
                    return [
                        _event(
                            tx_hash,
                            EventType.LiquidityWithdraw,
                            SubType.internal_transfer,
                            economic_legs,
                        )
                    ]
                reason_parts: list[str] = []
                if unmatched:
                    reason_parts.append(
                        f"LP-member out-leg recipient(s) {sorted(unmatched)} "
                        f"received no matching economic in-leg sender "
                        f"(in-leg senders: {sorted(in_senders)})"
                    )
                if registry_nonvault_recipients:
                    reason_parts.append(
                        f"registry-member out-leg recipient(s) "
                        f"{sorted(registry_nonvault_recipients)} are not "
                        f"registry vaults"
                    )
                return [
                    _event(
                        tx_hash,
                        EventType.LiquidityWithdraw,
                        SubType.internal_transfer,
                        economic_legs,
                        review=True,
                        reason=(
                            f"redemption-counterparty mismatch: "
                            f"{'; '.join(reason_parts)}; the "
                            f"receive side may be a third-party disposal of "
                            f"the LP/position token, not a vault redemption - "
                            f"verify before filing"
                        ),
                    )
                ]
            # Mirror the (a) subset semantics on the registry
            # side. A SINGLE registry-member out-leg keeps the plan's
            # vault-target rule (no vault target -> Swap fall-through, the
            # LBGT single-leg invariant); a batch with at least one
            # vault-target leg fires LiquidityWithdraw, and every
            # registry-member leg whose recipient is NOT a registry vault
            # (or is missing) is named in a review WARNING - one vault leg
            # must not silently clean a sibling disposal leg. A batch with
            # NO vault-target leg keeps the Swap fall-through (no fire).
            if self.position_token_registry is not None:
                registry_member_legs = [
                    leg
                    for leg in out_legs
                    if leg.token_address is not None
                    and self.position_token_registry.is_position_token(leg.token_address)
                ]
                registry_vault_legs = [
                    leg
                    for leg in registry_member_legs
                    if leg.to_address
                    and self.position_token_registry.is_position_vault(leg.to_address)
                ]
                if registry_vault_legs:
                    # Shared with the branch (a) fold above so
                    # the two branches cannot drift apart.
                    non_vault_recipients = {
                        (leg.to_address or "<missing>").lower()
                        for leg in self._registry_member_legs_without_vault_target(
                            registry_member_legs
                        )
                    }
                    if not non_vault_recipients:
                        return [
                            _event(
                                tx_hash,
                                EventType.LiquidityWithdraw,
                                SubType.internal_transfer,
                                economic_legs,
                            )
                        ]
                    return [
                        _event(
                            tx_hash,
                            EventType.LiquidityWithdraw,
                            SubType.internal_transfer,
                            economic_legs,
                            review=True,
                            reason=(
                                f"registry-member out-leg recipient(s) "
                                f"{sorted(non_vault_recipients)} are not registry "
                                f"vaults while sibling leg(s) targeted a vault; "
                                f"the receive side may be a third-party disposal "
                                f"of the position token, not a vault redemption - "
                                f"verify before filing"
                            ),
                        )
                    ]

        # 7. BIDIRECTIONAL receiving an LP token or a position-NFT-kind
        #    registry member token (an ERC-721 LP position mint; plan
        #    2026-08-24 Task 4 - the nfttx fetch makes those legs VISIBLE,
        #    so the receive-side detector accepts the kind-gated registry
        #    signal in addition to the LP snapshot; kind-gated
        #    so a DEX purchase of a registered LST stays a Swap; the
        #    position-NFT signal additionally requires the
        #    mint shape to touch a registry vault on EITHER side - the
        #    economic out-legs pay the vault OR the NFT arrives FROM the
        #    vault (a router-mediated mint pays an intermediary) - so a
        #    market purchase of a position NFT from a non-vault pair keeps
        #    the Swap fall-through - the LBGT receive-side invariant) ->
        #    LiquidityDeposit.
        if in_legs and out_legs and self._receives_member_receipt_token(in_legs, out_legs):
            # A provenance-only mint shape (the NFT arrives from the vault
            # but no economic out-leg pays one) is ambiguous with a
            # vault-seller resale or a mixed-provenance batch, so the event
            # carries a review flag with an actionable reason (PT-C-030
            # family), mirroring the shape-6 ambiguity pattern.
            provenance_reason = self._position_mint_provenance_review_reason(out_legs, in_legs)
            return [
                _event(
                    tx_hash,
                    EventType.LiquidityDeposit,
                    SubType.internal_transfer,
                    economic_legs,
                    review=provenance_reason is not None,
                    reason=provenance_reason,
                )
            ]

        # 8. BIDIRECTIONAL 1 in-asset <-> 1 out-asset -> Swap.
        if in_legs and out_legs:
            # Review r1 F3: a minted (zero-address) in-leg classified inside
            # a Swap hides a possible bridge/CEX transfer-in behind an
            # exchange shape (no distributor/router split applied). Warn; the
            # review workflow carries it from here. (r2 F4: the mint
            # predicate is computed ONCE.)
            minted_assets = sorted(
                {
                    leg.asset
                    for leg in in_legs
                    if _is_zero_address(leg.from_address)
                }
            )
            if minted_assets:
                # Review r5 (risk): the indicator must survive into the
                # artifact, not just the log - flag the Event so the merged-TH
                # Description carries the verification demand (repo rule:
                # partial/uncertain results carry an explicit indicator).
                reason = (
                    "swap contains a zero-address mint in-leg "
                    f"(asset(s) {', '.join(minted_assets)}); a bridge/CEX "
                    "transfer-in may be hidden inside the exchange shape - "
                    "verify source and cost basis before filing"
                )
                _LOGGER.warning("tx_hash=%s %s", tx_hash, reason)
                return [
                    _event(tx_hash, EventType.Swap, None, economic_legs, review=True, reason=reason)
                ]
            return [_event(tx_hash, EventType.Swap, None, economic_legs)]

        # 9. C3b self-wallet outbound: a pure outflow whose single recipient
        #    (the out-legs' to-addresses) is a registered ``self_wallet`` is
        #    the outbound leg of an internal self-transfer. BEFORE the
        #    fallback: today such txs fall to Event(Unknown) + review. (A tx
        #    with both in- and out-legs already returned at shape 6/7, so
        #    only pure outflows reach here.)
        if out_legs and self._single_recipient_is_self_wallet(out_legs):
            return [_transfer_event(tx_hash, out_legs)]

        # 10. PURE-outflow DEPOSIT rules (plan 2026-08-22 Task 3, routing
        #     targets 1/4 + the Task-5 residual sig-2 fix). Two predicates,
        #     one shared Event builder (``_deposit_event`` -
        #     "two shapes, one builder": twin constructions drift; three
        #     copies of the same body were collapsed into it):
        #     (a) member tokens: EVERY economic out-leg token is an
        #         LP-snapshot member (island/vault re-staking) or a
        #         position-registry member (LST deposit);
        #     (b) member recipient: a SINGLE-leg outflow whose token is
        #         NOT a member, but SOME out-direction leg - including the
        #         zero-value native gas carrier, whose ``to`` is the
        #         tx-level recipient - targets a position-registry VAULT
        #         (kind-gated): the wallet deposits into a
        #         registered vault and receives an ERC-721 position mint
        #         that txlist/tokentx/txlistinternal cannot serve.
        #     Both are gated ADDRESS-KEYED (never by asset name); a
        #     single-leg outflow with no member signal anywhere falls
        #     through to the Unknown fallback. AFTER shape 9 (a self-wallet
        #     transfer is never a deposit).
        if out_legs and not in_legs and (
            all(self._is_member_token(leg) for leg in out_legs)
            or (
                len(out_legs) == 1
                # Predicate (a) already established non-membership for a
                # single leg (``or`` short-circuit), so no re-check here
                # (the re-check was a dead conjunct).
                and self._any_out_leg_recipient_is_registry_member(legs)
            )
        ):
            return [self._deposit_event(tx_hash, out_legs)]

        # 11. PURE multi-leg outflow (routing target 2: zap-add / BERA+LST
        #     deposit shapes): >=2 economic out-legs -> LiquidityDeposit
        #     with ALL non-gas out-legs economic. The C1 carrier exclusion
        #     above already dropped zero-value native legs, so a NON-ZERO
        #     native out-leg (e.g. the economic BERA leg of the BERA+iBGT
        #     family) stays economic here. The clean
        #     (no-review) classification is limited to txs carrying a
        #     member signal (a member token on any out-leg, or a
        #     registry-member recipient); a member-signal-less multi-leg
        #     outflow is still classified LiquidityDeposit but flagged for
        #     review, so a genuine multi-asset disposal (batch send,
        #     payment plus donation) cannot silently lose its tax
        #     treatment.
        if out_legs and not in_legs and len(out_legs) >= _MIN_MULTI_LEG_OUTLEGS:
            gated = any(self._is_member_token(leg) for leg in out_legs) or (
                self._any_out_leg_recipient_is_registry_member(legs)
            )
            ungated_reason = (
                None
                if gated
                else (
                    f"multi-leg deposit received no LP/position-NFT member "
                    f"gate (no member token on any out-leg and no "
                    f"registry-member recipient; out-leg recipients: "
                    f"{sorted((leg.to_address or '<missing>').lower() for leg in out_legs)}); "
                    f"verify it is a genuine liquidity deposit before filing"
                )
            )
            return [
                self._deposit_event(
                    tx_hash, out_legs, review=not gated, reason=ungated_reason
                )
            ]

        # 12. Fallback: nothing matched (e.g. only outflow legs with no
        #    in-legs and not GAS_ONLY). Emit one Unknown Event + review
        #    rather than silently dropping the tx (AGENTS.md: data-loss
        #    conditions must never be silently discarded). The Event carries
        #    the UNFILTERED legs, so the warning names the economic counts
        #    AND the total to stay reconcilable with what it carries.
        _LOGGER.warning(
            "tx_hash=%s matched no classification pattern "
            "(economic in_legs=%d, economic out_legs=%d, %d leg(s) total "
            "on the Event); emitting Event(Unknown) for review",
            tx_hash,
            len(in_legs),
            len(out_legs),
            len(legs),
        )
        return [
            _event(
                tx_hash,
                EventType.Unknown,
                None,
                legs,
                review=True,
                reason=(
                    "no classification shape matched; verify the legs "
                    "manually before filing"
                ),
            )
        ]

    # ------------------------------------------------------------------
    # Shape detectors / event builders
    # ------------------------------------------------------------------

    def _deposit_event(
        self,
        tx_hash: str,
        out_legs: list[Leg],
        *,
        review: bool = False,
        reason: str | None = None,
    ) -> Event:
        """Build the shapes-10/11 ``LiquidityDeposit`` Event (one construction).

        Shapes 10 and 11 previously carried twin ``_event``
        constructions that a future SubType edit could silently diverge;
        both now share this builder (two shapes, one builder). ``reason``
        (review r7 F1) persists the actionable review explanation so the
        merged-TH Description cell keeps the review indicator.
        """
        return _event(
            tx_hash,
            EventType.LiquidityDeposit,
            SubType.internal_transfer,
            out_legs,
            review=review,
            reason=reason,
        )

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

    def _receives_position_token(self, in_legs: list[Leg]) -> bool:
        """Return True iff any in-leg's token is a position-NFT-kind member.

        Plan 2026-08-24 Task 4: the nfttx fetch makes ERC-721 position mints
        (e.g. an ``ALGB-POS#26874`` receive) VISIBLE as in-legs. Membership
        is keyed on ``token_address`` ONLY (address-keyed identity) and is
        KIND-GATED (only ``kind="position_nft"`` entries fire;
        an ``lst``-kind member is a tradable receipt token whose DEX purchase
        must stay a Swap per the LBGT invariant). The ``SYMBOL#tokenID``
        asset name is display/comparator-only and never feeds this decision.
        An absent registry is inert (fail-closed: the classifier falls
        through to the pre-existing shapes).
        """
        if self.position_token_registry is None:
            return False
        for leg in in_legs:
            if leg.token_address is None:
                continue
            if self.position_token_registry.is_position_nft_token(leg.token_address):
                return True
        return False

    def _receives_member_receipt_token(self, in_legs: list[Leg], out_legs: list[Leg]) -> bool:
        """Return True iff any in-leg carries a member receipt token.

        The bidirectional-receive (LiquidityDeposit) detector: accepts
        EITHER membership signal - an LP-snapshot member (via
        :meth:`_receives_lp_token`) OR a position-NFT-kind registry member
        (via :meth:`_receives_position_token`, plan 2026-08-24 Task 4;
        kind-gated per the LBGT invariant) that touches a registry vault on
        either side of the mint shape (the payment arm
        :meth:`_position_mint_pays_vault` OR the provenance arm
        :meth:`_position_mint_receives_from_vault`: a router-mediated mint
        pays an intermediary and still receives the NFT from the vault; a
        position NFT bought from a non-vault pair keeps the Swap
        fall-through per the LBGT receive-side invariant).
        One named detector so the dispatcher's shape-7 predicate stays a
        single call (the module's branch budget).
        """
        return self._receives_lp_token(in_legs) or (
            self._receives_position_token(in_legs)
            and (
                self._position_mint_pays_vault(out_legs)
                or self._position_mint_receives_from_vault(in_legs)
            )
        )

    def _position_mint_pays_vault(self, out_legs: list[Leg]) -> bool:
        """Return True iff any economic out-leg PAYS a registry vault (payment arm).

        The mint deposit's payment touchpoint: the wallet sends tokens TO
        the pool/vault (the deposit fixture shape). Matching keys on the
        out-leg ``to_address`` via
        :meth:`PositionTokenRegistry.is_position_vault` ONLY (address-keyed
        identity). An absent registry is inert (fail-closed).
        """
        if self.position_token_registry is None:
            return False
        for leg in out_legs:
            if leg.to_address and self.position_token_registry.is_position_vault(leg.to_address):
                return True
        return False

    def _position_mint_vault_senders(self, in_legs: list[Leg]) -> set[str]:
        """Return the lower-cased vault sender addresses of the provenance arm.

        Shared set-returning helper (review r6 F4) for the receives-from-vault
        detector and the provenance review-reason builder, so the arm
        evaluation exists in exactly ONE body and the reason cannot drift
        from the predicate that fired the classification. KIND-GATED (only
        ``kind="position_nft"`` token contracts via
        :meth:`PositionTokenRegistry.is_position_nft_token`) and
        sender-gated (the sender must be a registry vault via
        :meth:`PositionTokenRegistry.is_position_vault`). An absent registry
        is inert (fail-closed, empty set).
        """
        if self.position_token_registry is None:
            return set()
        return {
            leg.from_address.lower()
            for leg in in_legs
            if leg.token_address is not None
            and leg.from_address is not None
            and self.position_token_registry.is_position_nft_token(leg.token_address)
            and self.position_token_registry.is_position_vault(leg.from_address)
        }

    def _position_mint_receives_from_vault(self, in_legs: list[Leg]) -> bool:
        """Return True iff a kind-gated position-NFT in-leg arrives FROM a registry vault.

        The mint deposit's provenance touchpoint (a router/zapper-mediated
        mint: the wallet pays the intermediary, and the vault still
        dispatches the NFT). Delegates to the shared
        :meth:`_position_mint_vault_senders` set helper (review r6 F4: the
        arm evaluation lives in exactly one body). An absent registry is
        inert (fail-closed).
        """
        return bool(self._position_mint_vault_senders(in_legs))

    def _position_mint_provenance_review_reason(
        self, out_legs: list[Leg], in_legs: list[Leg]
    ) -> str | None:
        """Return an actionable review reason for a provenance-only mint shape.

        When the payment arm did NOT fire but the provenance arm did, the
        on-chain data cannot distinguish a router-mediated mint from a
        vault-seller resale (escrow release, liquidated-position resale) or
        a mixed-provenance batch: keep the LiquidityDeposit classification
        but flag for review, naming the vault-sender leg(s) and the
        non-vault payment counterparties (PT-C-030 family: specific,
        actionable explanations). Returns None when the shape is clean
        (payment arm fired) or no mint shape fired.
        """
        if self.position_token_registry is None:
            return None
        if self._position_mint_pays_vault(out_legs):
            return None
        vault_senders = self._position_mint_vault_senders(in_legs)
        if not vault_senders:
            return None
        # No out-leg pays a vault here, so every payee is a non-vault
        # payment counterparty.
        non_vault_payees = sorted(
            {(leg.to_address or "<missing>").lower() for leg in out_legs}
        )
        return (
            f"position-NFT received from registry vault sender(s) "
            f"{sorted(vault_senders)} but no economic out-leg pays a registry "
            f"vault (non-vault payment counterparties: {non_vault_payees}); "
            f"verify mint vs secondary purchase before filing"
        )

    def _is_member_token(self, leg: Leg) -> bool:
        """Return True iff ``leg`` sends a registry-member token (address-keyed).

        Membership = the LP snapshot (via :class:`LpAutodiscovery`) OR the
        position-token registry (plan 2026-08-22 Task 3). A native leg
        (``token_address`` is None) is never a member; matching is by
        ADDRESS, never by asset name (Design Invariant "Address-keyed
        identity").
        """
        if leg.token_address is None:
            return False
        if self.lp_autodiscovery.is_lp_token(leg.token_address).is_lp:
            return True
        return self.position_token_registry is not None and (
            self.position_token_registry.is_position_token(leg.token_address)
        )

    def _registry_member_legs_without_vault_target(self, out_legs: list[Leg]) -> list[Leg]:
        """Return the registry-member out-legs NOT targeting a registry vault.

        Shared predicate for the shape-6 branch (a) fold and the registry-only
        branch (b) (sibling shapes over the same type must use
        one helper, not duplicated copies that can drift). A leg qualifies
        when its token is a position-registry member AND its recipient is
        missing or not a registry vault. Returns an empty list when no
        registry is loaded (callers gate on the registry being present).
        """
        if self.position_token_registry is None:
            return []
        return [
            leg
            for leg in out_legs
            if leg.token_address is not None
            and self.position_token_registry.is_position_token(leg.token_address)
            and not (
                leg.to_address
                and self.position_token_registry.is_position_vault(leg.to_address)
            )
        ]

    def _any_out_leg_recipient_is_registry_member(self, legs: list[Leg]) -> bool:
        """Return True iff ANY out-direction leg's recipient is a registry VAULT.

        Scans the UNFILTERED legs (the full tx, not the C1-filtered economic
        partition): the registry-member vault is frequently the tx-level
        ``to`` - i.e. the recipient of the zero-value native GAS-CARRIER leg
        - while the economic leg's own recipient is the AMM pool.
        Recipient matching is kind-gated (``kind="position_nft"`` via
        :meth:`PositionTokenRegistry.is_position_vault`) so the registry's
        one address set cannot silently serve two different predicates -
        adding an LST (``kind="lst"``) entry widens the TOKEN rule (shape
        10a) but never the RECIPIENT rule here, because an LST token
        contract is a normal direct-interaction target, not the position-NFT
        vault the deposit routes through. An absent registry or no member
        vault recipient is never a match (fail-loud fallback, never a guess).
        """
        if self.position_token_registry is None:
            return False
        for leg in legs:
            if leg.direction != "out" or not leg.to_address:
                continue
            if self.position_token_registry.is_position_vault(leg.to_address):
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

        The two must co-occur: a reward inflow alone is the pure-inflow
        reward branch of :meth:`_classify_events`; a DEX-router exchange
        alone is the Swap branch. Only their co-occurrence triggers the
        split. (Branch names are used instead of shape numbers so these
        second-source references cannot drift when shapes are
        inserted.)
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
        # Pair each leg with its source row to read from_address. A
        # zero-address mint in-leg routes to the reward side too (review r1
        # F3): _reward_sub_type classifies it bridge + review, the same
        # treatment a pure-inflow mint gets, instead of silently absorbing
        # the bridge transfer-in into the Swap legs.
        for row, leg in zip(rows, legs, strict=True):
            sender = (row.from_address or "").lower()
            if leg.direction == "in" and (
                _is_zero_address(row.from_address) or self._is_reward_distributor(sender)
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
                sub_type = self._reward_sub_type(summed_leg)
                events.append(self._reward_event(tx_hash, summed_leg, sub_type))
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
                sub_type = self._reward_sub_type(summed_leg)
                events.append(self._reward_event(tx_hash, summed_leg, sub_type))
        return events

    def _reward_event(self, tx_hash: str, summed_leg: Leg, sub_type: SubType) -> Event:
        """Build one Reward Event (review r7 F1: spam/bridge always carry a reason).

        Shared by the reward-claim-then-swap split and the multi-token
        reward builder (sibling sites, one helper so the review plumbing
        cannot drift). A spam Reward is review-flagged with an actionable
        reason naming the unverified sender (PT-C-030 family), so the
        merged-TH Description cell keeps the review indicator. A bridge
        mint (zero-address issuance) carries its own actionable reason: the
        workflow cannot match the inflow to the originating acquisition
        (e.g. a CEX withdrawal), so the source and cost basis must be
        verified before filing (user direction 2026-08-26).
        """
        if sub_type is SubType.spam:
            reason = (
                f"reward classified as spam (sender "
                f"{(summed_leg.from_address or '<missing>').lower()} is not a "
                f"registered reward distributor); verify it is not taxable "
                f"income before filing"
            )
        elif sub_type is SubType.bridge:
            reason = (
                "inflow classified as a possible bridge transfer-in (tokens "
                "minted from the zero address - no external sender, e.g. "
                "bridged WBTC); the current workflow cannot match it to the "
                "originating acquisition (e.g. a CEX withdrawal) - verify "
                "source and cost basis before filing"
            )
        else:
            reason = None
        return _event(
            tx_hash,
            EventType.Reward,
            sub_type,
            [summed_leg],
            review=reason is not None,
            reason=reason,
        )

    def _reward_sub_type(self, summed_leg: Leg) -> SubType:
        """Return the Reward SubType for one summed (asset, sender) leg (F4).

        - bridge: the leg's from_address is the zero address - the tokens
          were MINTED (new issuance: a bridge deposit, e.g. bridged WBTC,
          or an on-chain mint). No external sender exists, so the F4
          unverified-sender premise does not apply; the Event carries
          review + a bridge-specific reason instead (user direction
          2026-08-26: CEX->bridge transfers must not read as rewards).
        - staking: the leg's from_address is a registered
          reward-distributor (the verified case).
        - spam: the from_address is NOT in the contract registry
          (Attacker F4: unverified-sender rewards are spam + review, never a
          clean staking).
        """
        sender = (summed_leg.from_address or "").lower()
        if _is_zero_address(summed_leg.from_address):
            return SubType.bridge
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
            _event(
                tx_hash,
                EventType.Unknown,
                None,
                [leg],
                review=True,
                reason=(
                    f"leg direction could not be derived (neither from "
                    f"{(leg.from_address or '<missing>').lower()} nor to "
                    f"{(leg.to_address or '<missing>').lower()} is the "
                    f"wallet); verify the counterparty before filing"
                ),
            )
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

    def _is_self_wallet(self, address: str) -> bool:
        """Return True iff ``address`` is a registered self-wallet (C3)."""
        entry = self.contract_registry.get(address)
        return entry is not None and entry.kind == "self_wallet"

    def _single_sender_is_self_wallet(self, in_legs: list[Leg]) -> bool:
        """Return True iff the in-legs share ONE registered self-wallet sender.

        Resolves the counterparty sender from the in-legs' ``from_address``
        values (the same lookup idiom :meth:`_is_reward_distributor` uses;
        addresses are lower-cased before the registry lookup). The
        single-sender requirement is the heterogeneity guard (AGENTS.md):
        a Transfer claims the legs ride ONE self-transfer, so legs with
        mixed or empty senders fall through to the reward branch (whose
        per-sender grouping + F4 verification handles them safely).
        """
        senders = {(leg.from_address or "").lower() for leg in in_legs}
        return len(senders) == 1 and self._is_self_wallet(senders.pop())

    def _single_recipient_is_self_wallet(self, out_legs: list[Leg]) -> bool:
        """Return True iff the out-legs share ONE registered self-wallet recipient.

        Mirror of :meth:`_single_sender_is_self_wallet` for the outbound
        direction: the counterparty is the out-legs' ``to_address``. Mixed
        or empty recipients fall through to the Unknown fallback (reviewed,
        never guessed) rather than being claimed as a self-transfer.
        """
        recipients = {(leg.to_address or "").lower() for leg in out_legs}
        return len(recipients) == 1 and self._is_self_wallet(recipients.pop())


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


def _is_gas_carrier(leg: Leg) -> bool:
    """Detect a gas-carrier leg (design record Q6): a zero-value NATIVE outflow.

    The native asset has no ``token_address``; a zero-value outflow of it is
    the tx's gas carrier - the leg the explorer emits so the (parent-tx)
    gas has a row to ride on. It is NOT an economic movement: the actual
    gas amount is lifted to the parent tx by :func:`_lift_gas`. Zero-value
    TOKEN legs (``token_address`` set) are never carriers (narrow rule:
    only the chain's gas asset has no contract).
    """
    return (
        leg.direction == "out"
        and leg.token_address is None
        and leg.amount_raw == 0
    )


def _is_gas_only(legs: list[Leg]) -> bool:
    """Detect the GAS_ONLY shape (decision-record: 139-tx shape).

    A GAS_ONLY tx is one whose only economic movement is the gas burn: a
    single zero-value native outflow. Heuristics: exactly one leg, and that
    leg is the gas-carrier shape (:func:`_is_gas_carrier`). The gas itself
    lives on the parent tx (lifted by :func:`_lift_gas`); this function
    only decides whether to emit a GasBurn Event.
    """
    if len(legs) != 1:
        return False
    return _is_gas_carrier(legs[0])


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


def _transfer_event(tx_hash: str, legs: list[Leg]) -> Event:
    """Build the Transfer Event for a C3 self-wallet shape (a or b).

    Both C3 branches (the inbound pure-inflow self-wallet branch and the
    outbound pure-outflow self-wallet branch of
    :meth:`BerachainProcessor._classify_events`) emit the byte-identical
    ``Transfer/internal_transfer`` Event, so the construction lives HERE
    once (the file's builder idiom) rather than inline twice in the
    dispatcher (two copies can drift apart; branch names are
    used instead of shape numbers so this reference cannot drift).
    """
    return _event(
        tx_hash,
        EventType.Transfer,
        SubType.internal_transfer,
        legs,
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


def _event(  # noqa: PLR0913 - module-level Event builder; the plan's frozen signature
    tx_hash: str,
    event_type: EventType,
    sub_type: SubType | None,
    legs: list[Leg],
    *,
    review: bool = False,
    reason: str | None = None,
) -> Event:
    """Build an :class:`Event` with a tx-unique sequential ``event_id``.

    ``event_id`` is ``f"{tx_hash}#{n}"`` where ``n`` is the 1-based index of
    this Event within its parent tx (assigned by the caller via the
    ``_EventIdMint`` helper to guarantee uniqueness). When ``review`` is
    True, a WARNING is logged naming the Event so the run's review surface
    is visible (AGENTS.md: data-loss/uncertain conditions log at warning+).
    ``reason`` (optional) appends a specific, actionable explanation to the
    review WARNING (AGENTS.md: review flags give specific reasons, not bare
    booleans).
    """
    # NOTE: ``event_id`` minting is done by ``_mint_event_ids`` AFTER the
    # events are built (so the index reflects emission order). This helper
    # leaves event_id as a placeholder; ``_mint_event_ids`` rewrites it.
    if review:
        _LOGGER.warning(
            "tx_hash=%s emitting Event(%s, sub_type=%s) with a review flag "
            "(uncertain classification - investigate%s)",
            tx_hash,
            event_type.name,
            sub_type.name if sub_type is not None else "<none>",
            f"; {reason}" if reason is not None else "",
        )
    return Event(
        event_id="",  # minted by _mint_event_ids
        event_type=event_type,
        sub_type=sub_type,
        legs=tuple(legs),
        parent_tx_hash=tx_hash,
        review_reason=reason if review else None,
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
