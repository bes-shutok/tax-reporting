"""LP-token autodiscovery: subgraph snapshot + bytecode fingerprint + provenance.

Implements decision #11 of the on-chain-tx design record
(``docs/architecture/on-chain-tx-design.md`` §9.2): address-keyed LP-token
detection via a three-layer stack. Symbol regex is REJECTED (V2 pairs all
return ``UNI-V2``; staking receipts share naming).

Three-layer stack
-----------------
1. **Primary - subgraph snapshot allowlist** (loaded + validated in
   :mod:`application.on_chain_config`): an O(1) ``token_address`` -> entry
   lookup. A hit classifies the token with NO RPC call.
2. **Fallback - on-chain bytecode/implementation fingerprint** (this module,
   via :class:`infrastructure.on_chain.rpc_client.RpcClient`): for tokens NOT
   in the snapshot, fetch runtime bytecode (one ``eth_getCode``); if its
   fingerprint matches a known V2-pair runtime bytecode, classify as Pair.
   Otherwise read ``implementation()``; if it resolves to a known impl
   address (KodiakIsland), classify as a vault. One or two RPC calls max.
3. **Provenance only - mint-on-deposit tx pattern**: handled by the existing
   :mod:`application.token_origin` mechanism; this module does NOT use tx
   pattern as a classification signal.

Public entry point: :meth:`LpAutodiscovery.is_lp_token`, returning a
:class:`LpClassification` (never a bare bool - per AGENTS.md a review flag
must carry a specific, actionable explanation).

Hard cap (MO1): :meth:`is_lp_token` caps the number of RPC-touching
lookups at ``cap`` (default 50); tokens beyond the cap are marked
``Unknown`` + review WITHOUT an RPC call, so a wallet with hundreds of
unknown tokens cannot saturate the RPC.

Hashing deferral (recorded in the Task 8 execution log): the design record
cites keccak256 for the V2-pair runtime-bytecode fingerprint, but
``pyproject.toml`` has NO ``web3`` / ``eth-hash`` / ``pysha3`` dependency.
Per the AGENTS.md "never introduce a dependency without asking" rule this
module uses :func:`hashlib.sha256` as a collision-resistant STAND-IN. The
matching is against stored fingerprints (a config detail), so any
collision-resistant hash works for the matching logic; switching to
keccak256 in production is a one-line config change.
"""

from __future__ import annotations

import dataclasses
import hashlib
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tax_reporting.domain.on_chain_config import LpSnapshot
    from tax_reporting.infrastructure.on_chain.rpc_client import RpcClient

_LOGGER = logging.getLogger(__name__)

# Hard cap on RPC-touching lookups per is_lp_token call (MO1). Beyond this,
# remaining tokens are marked Unknown + review without an RPC call.
_DEFAULT_CAP = 50


@dataclasses.dataclass(frozen=True)
class LpClassification:
    """The result of classifying one ``token_address``.

    Never a bare bool: an unknown address carries a ``review_flag`` +
    ``review_reason`` with a specific, actionable explanation (AGENTS.md:
    review flags must include specific actionable explanations, not bare
    booleans).

    Attributes:
        token_address: The address classified (lower-cased).
        is_lp: True if the token is an LP token.
        source: How the token was classified:
            ``"snapshot"`` (primary allowlist hit, no RPC),
            ``"bytecode_v2"`` (V2-pair runtime-bytecode fingerprint match),
            ``"bytecode_island"`` (implementation() resolved to a known
            KodiakIsland/Bault impl), or
            ``"unknown"`` (not LP / could not classify).
        review_flag: ``"REVIEW"`` when the token needs human review, else
            ``None``. Set for unknown tokens and for tokens beyond the cap.
        review_reason: Specific actionable explanation when
            ``review_flag`` is set, else ``None``.
        protocol: Originating protocol tag from the snapshot entry, when
            known (e.g. ``"Kodiak"``); else ``None``.
        lp_type: The LP product type when known (``"Pair"``,
            ``"KodiakVault"``, ``"stakingToken"``); else ``None``.
    """

    token_address: str
    is_lp: bool
    source: str
    review_flag: str | None = None
    review_reason: str | None = None
    protocol: str | None = None
    lp_type: str | None = None


def _fingerprint(hex_bytecode: str) -> str:
    """Return the sha256 stand-in fingerprint of a ``0x``-hex bytecode string.

    Production should use keccak256 (see module docstring); the matching
    logic is against stored fingerprints so any collision-resistant hash
    suffices. The hex string is hashed as ASCII bytes (deterministic; the
    leading ``0x`` is included so two bytecodes of different lengths but
    identical trailing bytes still hash distinctly).
    """
    return hashlib.sha256(hex_bytecode.encode("ascii")).hexdigest()


class LpAutodiscovery:
    """Three-layer LP-token classifier.

    Attributes:
        snapshot: The loaded + validated :class:`LpSnapshot` (primary
            allowlist). May be empty (no snapshot file); classification
            then falls straight through to the RPC fallback.
        rpc_client: The :class:`RpcClient` used by the bytecode fallback.
            ``None`` only when no fallback is desired (every unknown token
            becomes Unknown + review with no RPC call).
        fingerprints: ``{sha256_fingerprint: lp_type}`` for V2-pair runtime
            bytecodes. Defaults to an empty dict; the processor (Task 9)
            seeds the real fingerprints. Tests seed synthetic ones.
        known_implementation_addresses: ``{impl_address: lp_type}`` for
            EIP-1167 minimal-proxy impls (KodiakIsland, Bault). Defaults
            empty; seeded by the processor / tests.
        cap: Hard cap on RPC-touching lookups per :meth:`is_lp_token`.
    """

    def __init__(
        self,
        snapshot: LpSnapshot,
        rpc_client: RpcClient | None,
        *,
        fingerprints: dict[str, str] | None = None,
        known_implementation_addresses: dict[str, str] | None = None,
        cap: int = _DEFAULT_CAP,
    ) -> None:
        """Bind the snapshot, RPC fallback, and fingerprint/impl registries.

        See the class docstring for the meaning of each attribute; the
        constructor stores them verbatim (lower-casing the impl-address keys)
        and defaults the optional registries to empty dicts.
        """
        self.snapshot = snapshot
        self.rpc_client = rpc_client
        self.fingerprints = fingerprints or {}
        # Normalize impl-address keys to lower-case so callers may pass either
        # checksummed (EIP-55) or lower-cased forms; the RPC result is
        # lower-cased before lookup (see is_lp_token).
        self.known_implementation_addresses = {
            (k.lower() if isinstance(k, str) and k.startswith("0x") else k): v
            for k, v in (known_implementation_addresses or {}).items()
        }
        self.cap = cap
        # MO1 cap as a per-instance counter (F4): shared across all
        # is_lp_token calls on this instance, seeded once in __init__. A new
        # LpAutodiscovery gets a fresh budget (per-run, not per-tx).
        # Pre-decrement: the first ``cap`` RPC-touching lookups proceed; the
        # next sees budget <= 0 and returns CAP_REACHED.
        self._rpc_budget = self.cap

    def is_lp_token(self, address: str) -> LpClassification:
        """Classify one ``token_address``.

        Order: snapshot (no RPC) -> [cap check + decrement] -> V2-pair
        bytecode fingerprint (one RPC) -> implementation() (one more RPC)
        -> Unknown + review.
        """
        addr = address.lower()

        # Layer 1 - snapshot (primary).
        entry = self.snapshot.tokens.get(addr)
        if entry is not None:
            return LpClassification(
                addr,
                is_lp=True,
                source="snapshot",
                protocol=entry.protocol,
                lp_type=entry.lp_type,
            )

        # Layers 2/3 - bytecode fallback. Requires an RPC client. The
        # rpc_client-None short-circuit stays BEFORE the cap check so a None
        # rpc_client never consumes budget.
        if self.rpc_client is None:
            return self._unknown(addr, reason="no RPC client configured")

        # MO1 cap (F4): pre-call check + pre-decrement. The decrement happens
        # before the RPC call. When the budget is exhausted, return a
        # CAP_REACHED-flagged classification without an RPC call.
        if self._rpc_budget <= 0:
            return self._unknown(
                addr,
                reason=(
                    f"token {addr} not classified: the RPC-fallback cap "
                    f"({self.cap}) was reached; review and either add it to "
                    f"the LP snapshot or raise the cap"
                ),
                flag="CAP_REACHED",
            )
        self._rpc_budget -= 1

        # V2-pair runtime-bytecode fingerprint.
        code = self.rpc_client.get_code(addr)
        fp = _fingerprint(code)
        if fp in self.fingerprints:
            lp_type = self.fingerprints[fp]
            return LpClassification(
                addr,
                is_lp=True,
                source="bytecode_v2",
                lp_type=lp_type,
            )

        # EIP-1167 minimal-proxy implementation() resolution.
        impl = self.rpc_client.get_implementation(addr)
        impl_addr = impl.lower() if impl.startswith("0x") else impl
        if impl_addr in self.known_implementation_addresses:
            lp_type = self.known_implementation_addresses[impl_addr]
            return LpClassification(
                addr,
                is_lp=True,
                source="bytecode_island",
                lp_type=lp_type,
            )

        return self._unknown(
            addr,
            reason=(
                f"token {addr} is not in the LP snapshot and its runtime "
                f"bytecode / implementation() matched no known LP fingerprint; "
                f"review and add to the snapshot if it is an LP token"
            ),
        )

    def check_freshness(self, latest_tx_block: int) -> None:
        """WARN if the snapshot predates the latest observed tx block (M2).

        A snapshot older than the tax year's latest tx means recent pools are
        missing from the allowlist; the bytecode fallback covers them but at
        RPC cost. The WARNING names both blocks so the user can decide to
        refresh the snapshot.
        """
        if self.snapshot.snapshot_as_of_block < latest_tx_block:
            _LOGGER.warning(
                "snapshot_as_of_block %d predates the latest observed tx block "
                "%d; recent LP pools may be missing from the allowlist - "
                "consider refreshing the snapshot (subgraph_version=%s)",
                self.snapshot.snapshot_as_of_block,
                latest_tx_block,
                self.snapshot.subgraph_version,
            )

    @staticmethod
    def _unknown(
        addr: str, *, reason: str, flag: str = "REVIEW"
    ) -> LpClassification:
        """Build an Unknown classification carrying a review flag + reason."""
        return LpClassification(
            addr,
            is_lp=False,
            source="unknown",
            review_flag=flag,
            review_reason=reason,
        )
