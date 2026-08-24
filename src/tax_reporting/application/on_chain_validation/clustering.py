"""PII-free cluster signatures for TH-validation discrepancies (PD-010).

Groups the comparator's per-tx records (validation-harness Task 2) into
*discrepancy clusters* - the unit of resolution in the validation harness -
by a stable, PII-free semantic key (plan Task 3,
``docs/history/plans/2026-08-18-on-chain-validation-harness.md``):

::

    events=<sorted EventType names>|koinly=<sorted Type/Tag combos>|sender=<class>
    |lp=<bool>|fee=<class>|zero_display=<bool>

(the two lines are one signature; wrapped for the 120-column limit):

Encoding rules (plan Terms + worked example):

- components join with ``|``; ``|`` is ONLY the component separator and
  NEVER appears inside a value (guarded fail-loud below);
- each Koinly combo renders ``Type/Tag``; the values of a multivalued
  component (``events``, ``koinly``) join with ``+`` and are SORTED, so the
  signature is deterministic under input reordering;
- an EMPTY multivalued component renders ``none`` - an on-chain-only record
  (no Koinly rows) reads ``koinly=none``, a Koinly-only record reads
  ``events=none``, and the absent side's fee rendering reads ``fee=none``;
- booleans render lowercase ``true``/``false``.

The signature deliberately contains NO tx hashes, wallet addresses, dates,
or amounts (Design Invariant PII): it survives re-runs while fixes land and
is safe for committed docs and the dispositions file (Task 4).

Inputs are the comparator's :class:`ThComparisonRecord` objects (which
already carry the cluster-signature context: event types, Koinly combos,
counterparties, assets, on-chain legs' token addresses, fee-surface class,
zero-display flag), the loaded :class:`ContractRegistry` (sender-class
resolution via ``ContractRegistry.get`` - the Koinly side's counterparties
arrive via the record's ``TxSrc``/``TxDest`` extraction), and the loaded
:class:`LpSnapshot` (LP-token involvement via token-address membership,
asset identifiers as the fallback).
"""

from __future__ import annotations

from typing import Final

from tax_reporting.application.on_chain_validation.comparator import (
    ComparisonResult,
    ThComparisonRecord,
)
from tax_reporting.domain.on_chain_config import ContractRegistry, LpSnapshot

__all__ = [
    "cluster_signature",
    "group_into_clusters",
]

#: Sentinel rendering an EMPTY multivalued component (plan Task 3 vocabulary).
_EMPTY_COMPONENT: Final = "none"

#: The component separator (ONLY between components, never inside a value).
_COMPONENT_SEPARATOR: Final = "|"

#: Joiner between the sorted values of a multivalued component (plan Terms:
#: "each Koinly combo is ``Type/Tag``, combos join with ``+``").
_VALUE_SEPARATOR: Final = "+"

#: Deterministic priority when a tx's counterparties resolve to more than one
#: registered kind (e.g. a claim+swap tx touching a distributor AND a router):
#: the first listed kind wins, in the plan Task 3 enumeration order. The
#: ``self_wallet`` kind lands in the registry loader with plan Task 8; the
#: classifier here is already forward-compatible with it.
_SENDER_KIND_PRIORITY: Final[tuple[str, ...]] = (
    "reward_distributor",
    "dex_router",
    "rebate_router",
    "self_wallet",
)

#: Sender-class sentinel when counterparties exist but NONE is registered
#: (also the fallback for a hypothetical registry kind outside the priority
#: vocabulary - the loader's kind validation keeps that unreachable today).
_SENDER_UNREGISTERED: Final = "unregistered"

#: Sender-class sentinel when the tx carries NO counterparty at all
#: (absent/empty ``TxSrc``/``TxDest`` on every row).
_SENDER_NULL_OR_EMPTY: Final = "null_or_empty"


def _render_multivalued(values: frozenset[str] | set[str]) -> str:
    """Render a multivalued component: sorted values joined with ``+``.

    An empty component renders the ``none`` sentinel (the absent side of a
    one-sided record). A value containing the component separator would
    corrupt the encoding and fails loudly (fail-loud by design - a silently
    mis-parsed signature would mis-bucket every cluster after it).
    """
    for value in values:
        if _COMPONENT_SEPARATOR in value:
            raise ValueError(
                f"cluster-signature value contains the component separator {_COMPONENT_SEPARATOR!r}: {value!r}"
            )
    if not values:
        return _EMPTY_COMPONENT
    return _VALUE_SEPARATOR.join(sorted(values))


def _sender_class(record: ThComparisonRecord, registry: ContractRegistry) -> str:
    """Resolve the tx's sender-registration class from its counterparties.

    The record carries the union of the on-chain projection's row addresses
    and the Koinly rows' ``TxSrc``/``TxDest`` values. Classification per
    plan Task 3: any counterparty resolving (case-insensitively, via
    ``ContractRegistry.get``) to a registered kind yields that kind - by the
    fixed :data:`_SENDER_KIND_PRIORITY` when several kinds appear (the
    tracked wallet's own address is typically unregistered and must not
    drown the outside counterparty's class); counterparties with no entry at
    all yield ``unregistered``; NO counterparty at all yields
    ``null_or_empty``.
    """
    counterparties = record.on_chain_counterparties | record.koinly_counterparties
    if not counterparties:
        return _SENDER_NULL_OR_EMPTY
    kinds = {entry.kind for address in counterparties if (entry := registry.get(address)) is not None}
    for kind in _SENDER_KIND_PRIORITY:
        if kind in kinds:
            return kind
    return _SENDER_UNREGISTERED


def _lp_involved(record: ThComparisonRecord, lp_snapshot: LpSnapshot) -> bool:
    """Whether any token the tx touches is an LP-snapshot token.

    The AUTHORITATIVE discriminator is the record's ``token_addresses`` - the
    on-chain legs' token addresses threaded from the source transactions
    (review r1 F1) - because the snapshot is keyed by token addresses while
    ``assets`` carry tickers, which never match those keys on the production
    path. The asset identifiers remain as the FALLBACK source: a record with
    no on-chain side (Koinly-only) can still carry an address-shaped asset
    rendering of a snapshot token. Membership is checked case-insensitively
    (lower-cased snapshot keys), mirroring ``ContractRegistry.get``.
    """
    identifiers = record.token_addresses | record.assets
    return any(identifier.lower() in lp_snapshot.tokens for identifier in identifiers)


def cluster_signature(
    record: ThComparisonRecord,
    *,
    registry: ContractRegistry,
    lp_snapshot: LpSnapshot,
) -> str:
    """Build the PII-free cluster signature of one comparison record.

    Args:
        record: A comparator record (divergent, on-chain-only, or
            Koinly-only; matched txs produce no records and no clusters).
        registry: The loaded contract registry (sender-class resolution).
        lp_snapshot: The loaded LP-token snapshot (LP involvement).

    Returns:
        The deterministic signature string, e.g.
        ``events=GasBurn|koinly=none|sender=unregistered|lp=false|fee=none|zero_display=false``.

    Raises:
        ValueError: If a component value contains the ``|`` separator (the
            encoding invariant is load-bearing for every downstream consumer
            of the dispositions file).
    """
    return _COMPONENT_SEPARATOR.join(
        (
            f"events={_render_multivalued({event_type.name for event_type in record.on_chain_event_types})}",
            f"koinly={_render_multivalued({f'{type_}/{tag}' for type_, tag in record.koinly_combos})}",
            f"sender={_sender_class(record, registry)}",
            f"lp={str(_lp_involved(record, lp_snapshot)).lower()}",
            f"fee={record.koinly_fee_surface.value}",
            f"zero_display={str(record.zero_display).lower()}",
        )
    )


def group_into_clusters(
    result: ComparisonResult,
    *,
    registry: ContractRegistry,
    lp_snapshot: LpSnapshot,
) -> dict[str, list[ThComparisonRecord]]:
    """Group all discrepancy records of a comparison by cluster signature.

    Covers the three discrepancy partitions - ``divergent``,
    ``on_chain_only``, ``koinly_only`` - in that order (each already
    hash-sorted by the comparator, so bucket order is deterministic).
    Matched txs are NOT discrepancies and appear in no cluster.

    Args:
        result: The :func:`compare_projection` outcome.
        registry: The loaded contract registry (sender-class resolution).
        lp_snapshot: The loaded LP-token snapshot (LP involvement).

    Returns:
        ``{signature: records}`` with insertion-ordered buckets.
    """
    clusters: dict[str, list[ThComparisonRecord]] = {}
    for record in (*result.divergent, *result.on_chain_only, *result.koinly_only):
        clusters.setdefault(
            cluster_signature(record, registry=registry, lp_snapshot=lp_snapshot),
            [],
        ).append(record)
    return clusters
