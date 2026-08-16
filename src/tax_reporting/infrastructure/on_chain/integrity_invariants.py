"""Post-cutover on-chain integrity invariants (Plan Task 13, MO2).

These are RUN-LEVEL (post-aggregation, not per-row -- AGENTS.md) checks that
catch systemic on-chain-source corruption AFTER the processor has produced
:class:`OnChainTransaction` objects and AFTER the contract registry has
loaded. They are the **audit echo / second line of defense** for the per-row
guards:

- **Registry dominance (Attacker F7):** no single contract-registry entry
  accounts for >30% of tx tags. Catches a typo'd or hostile registry entry
  tagging a majority of transactions (a config-write attack or a copy-paste
  error). The per-tx tag comes from a leg's ``from_address`` matching a
  registry entry.
- **Decimal overflow guard (echo of Task 7):** zero legs carry
  ``amount_decimals`` outside ``[0, 36]``. The CSV reader (Task 7) clamps on
  read; this check guards the post-processor output (and any future RPC path
  that bypasses the CSV reader) so a downstream consumer never computes
  ``10 ** 77``.
- **Unknown-direction rate (echo of the processor's hard fail):** <1% of
  legs have ``direction=unknown``. The processor (Task 9) already raises
  :class:`FileProcessingError` at >1% at the gate; this post-run echo is the
  audit WARN that the invariant held or, if a future path bypasses the gate,
  surfaces the regression.
- **Closed ``operator_country`` enum (Attacker F1 cheap mitigation):**
  every non-``None`` ``operator_country`` in the loaded contract registry is
  a valid ISO-3166 alpha-2 code. The registry loader (Task 9) already fails
  closed on an invalid code; this post-run echo audits the loaded registry.

Why a SEPARATE module (vs. folding into the processor)
------------------------------------------------------

The processor (Task 9) owns PER-TX classification and one run-level gate
(the >1% unknown-direction hard fail). These four invariants are a different
concern: they audit the *whole run's output* (post-processor) plus the
*loaded registry* (post-loader), independently of how either was produced.
Keeping them in a PURE post-processor module means:

- They run on the same ``list[OnChainTransaction]`` the adapter projects,
  so a future RPC-fed processor (no CSV reader) is still covered.
- They are trivially testable (pure function; inject synthetic txs + a
  synthetic registry -- no I/O, no fixtures beyond the committed example
  contract registry).
- The severity policy is centralized here (AGENTS.md "warn or fail per
  severity").

Severity policy (AGENTS.md)
--------------------------

- **WARN (soft, audit signal):** registry dominance >30%; unknown-direction
  rate >=1%. These are systemic-corruption *signals* -- a WARN surfaces the
  finding for human review without aborting a run that may still be
  salvageable. The processor's hard fail already covers the >1% unknown case
  at the gate; the WARN is the audit echo.
- **FAIL (hard, data corruption):** decimal-out-of-range legs; invalid
  ``operator_country`` code. These indicate the data is materially corrupt
  and downstream EUR / origin resolution would be wrong. The caller raises
  :class:`FileProcessingError` via :meth:`IntegrityReport.raise_if_failed`.

The checker is PURE: it takes the data and returns an
:class:`IntegrityReport`; no I/O. WARN findings are logged at WARNING so the
run's review surface is visible (AGENTS.md: data-loss/uncertain conditions
log at warning+); FAIL findings are recorded for the caller to raise.

Wired into ``main.py``'s on-chain TH path (Plan Task 11) as a post-processor
step (see ``_maybe_substitute_on_chain_th``): after the processor emits
``list[OnChainTransaction]``, the integrity checker audits them + the loaded
registry before the adapter projects them onto
:class:`TransactionHistoryRow`.

Accepted risk A1 (attacker-with-config-write-access)
----------------------------------------------------

This module is part of the cheap-mitigation layer for accepted risk A1 (see
``docs/maintenance/crypto_implementation_guidelines.md``): an attacker with
config-write access can poison the contract registry / LP snapshot. As a
single-user, local-only tool, the threat model does NOT justify
cryptographically signing the config; instead, the cheap mitigations
(closed ``operator_country`` enum + citation validation; decimal clamp;
dominance WARN) reduce the blast radius of a typo'd or hostile config
without the complexity of a signing scheme.

Design record: ``docs/architecture/on-chain-tx-design.md`` (premortem A1,
decisions 8, 11).
Implementation plan: ``docs/history/plans/2026-08-02-on-chain-tx-tagger.md``
(Task 13).
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from enum import Enum
from typing import Final

from tax_reporting.domain.exceptions import FileProcessingError
from tax_reporting.domain.on_chain_config import (
    ContractRegistry,
    is_valid_iso3166_alpha2,
)
from tax_reporting.domain.on_chain_transaction import (
    UNKNOWN_DIRECTION_MAX_FRACTION,
    UNKNOWN_DIRECTION_MIN_ABSOLUTE,
    OnChainTransaction,
)

_LOGGER = logging.getLogger(__name__)

# Attacker F7 mitigation: no single registry entry may tag more than this
# fraction of the run's transactions. 30% is generous (the observed Berachain
# wallet has the BGT Distributor tagging a minority of reward txs); a
# majority-tagging entry signals a typo'd or hostile registry entry.
_REGISTRY_DOMINANCE_MAX_FRACTION: Final = 0.30

# Decimal overflow guard (echo of Task 7's CSV-reader clamp). EVM tokens use
# at most 36 decimals; anything outside [0, 36] is attacker-controlled
# metadata that would let a downstream consumer compute 10 ** 77 and OOM.
_MIN_DECIMALS: Final = 0
_MAX_DECIMALS: Final = 36


class IntegritySeverity(Enum):
    """Severity of an :class:`IntegrityFinding`.

    - ``WARN``: audit signal; logged + recorded but does not abort the run.
    - ``FAIL``: data corruption; the caller raises
      :class:`FileProcessingError` via :meth:`IntegrityReport.raise_if_failed`.
    """

    WARN = "warn"
    FAIL = "fail"


@dataclass(frozen=True)
class IntegrityFinding:
    """One invariant finding.

    Attributes:
        check: Stable identifier for the invariant that fired (e.g.
            ``"registry_dominance"``, ``"decimal_range"``,
            ``"unknown_direction_rate"``, ``"operator_country_enum"``).
        severity: :data:`IntegritySeverity.WARN` or :data:`IntegritySeverity.FAIL`.
        message: Specific, actionable explanation (AGENTS.md: review flags
            must include specific actionable explanations, not bare booleans).
    """

    check: str
    severity: IntegritySeverity
    message: str


@dataclass(frozen=True)
class IntegrityReport:
    """The result of :func:`check_on_chain_integrity`.

    Carries all findings (WARN + FAIL). :attr:`has_failures` is True when any
    FAIL-level finding fired; :meth:`raise_if_failed` then raises
    :class:`FileProcessingError` aggregating every FAIL message. WARN
    findings are NOT raised (audit signal); the caller logs them.
    """

    findings: list[IntegrityFinding] = field(default_factory=list)

    @property
    def has_failures(self) -> bool:
        """True iff any FAIL-level finding fired."""
        return any(f.severity is IntegritySeverity.FAIL for f in self.findings)

    def raise_if_failed(self) -> None:
        """Raise :class:`FileProcessingError` aggregating all FAIL messages.

        No-op when there are no FAIL-level findings (the run's WARN signals
        are surfaced via logging, not raised). The aggregated message names
        every failing check + its message so the user can trace each cause
        (AGENTS.md: never collapse multiple causes into one).
        """
        failures = [f for f in self.findings if f.severity is IntegritySeverity.FAIL]
        if not failures:
            return
        detail = "; ".join(f"{f.check}: {f.message}" for f in failures)
        raise FileProcessingError(
            f"On-chain integrity invariants FAILED ({len(failures)} hard "
            f"finding(s)): {detail}"
        )


def check_on_chain_integrity(
    *,
    transactions: list[OnChainTransaction],
    registry: ContractRegistry,
) -> IntegrityReport:
    """Run the four post-cutover integrity invariants; return a report.

    PURE: no I/O. WARN findings are logged at WARNING (the run's review
    surface); FAIL findings are recorded for the caller to raise via
    :meth:`IntegrityReport.raise_if_failed`.

    Args:
        transactions: The processor's output ``list[OnChainTransaction]``
            (post-classification). The dominance + decimal + unknown checks
            audit these.
        registry: The loaded + validated :class:`ContractRegistry`. The
            dominance check uses it to identify which legs' senders are
            registered; the operator_country check audits its values.

    Returns:
        An :class:`IntegrityReport` carrying every finding (WARN + FAIL).
    """
    findings: list[IntegrityFinding] = []
    findings.extend(_check_registry_dominance(transactions, registry))
    findings.extend(_check_decimal_range(transactions))
    findings.extend(_check_unknown_direction_rate(transactions))
    findings.extend(_check_operator_country_enum(registry))

    report = IntegrityReport(findings=findings)
    # Surface WARN findings via logging so the run's review surface is
    # visible (AGENTS.md: data-loss/uncertain conditions log at warning+).
    # FAIL findings are surfaced by the caller via raise_if_failed().
    for finding in findings:
        if finding.severity is IntegritySeverity.WARN:
            _LOGGER.warning(
                "On-chain integrity invariant WARN (%s): %s",
                finding.check,
                finding.message,
            )
    return report


# ----------------------------------------------------------------------
# Invariant 1: registry dominance (Attacker F7) -- WARN
# ----------------------------------------------------------------------


def _check_registry_dominance(
    transactions: list[OnChainTransaction],
    registry: ContractRegistry,
) -> list[IntegrityFinding]:
    """WARN if any single registry entry tags >30% of transactions.

    A registry entry "tags" a transaction when one of its Events' legs has a
    ``from_address`` matching the entry's address (case-insensitive). The
    share is ``tagged_tx_count / total_tx_count``. A majority-tagging entry
    signals a typo'd or hostile registry entry (Attacker F7: a typo'd address
    that happens to match many senders, or a hostile entry poisoning the
    run).

    WARN-level (audit signal): the run may still be salvageable (the
    dominance could be legitimate for a wallet that interacts heavily with
    one protocol); the WARN surfaces it for human review.
    """
    if not transactions:
        return []

    total = len(transactions)
    # Count how many DISTINCT txs each registered address tags. A tx is
    # counted at most once per address even if multiple of its legs share the
    # sender (avoid inflating the share via a multi-leg reward claim).
    tagged_txs_per_address: Counter[str] = Counter()
    for tx in transactions:
        # Distinct registered senders touched by THIS tx (dedupe so a tx with
        # N legs from the same sender counts once for that sender).
        tx_senders: set[str] = set()
        for event in tx.events:
            for leg in event.legs:
                sender = (leg.from_address or "").lower()
                if not sender:
                    continue
                if registry.get(sender) is not None:
                    tx_senders.add(sender)
        for sender in tx_senders:
            tagged_txs_per_address[sender] += 1

    findings: list[IntegrityFinding] = []
    for address, count in tagged_txs_per_address.items():
        fraction = count / total
        if fraction > _REGISTRY_DOMINANCE_MAX_FRACTION:
            findings.append(
                IntegrityFinding(
                    check="registry_dominance",
                    severity=IntegritySeverity.WARN,
                    message=(
                        f"registry entry {address} tags {count}/{total} txs "
                        f"({fraction:.0%}), exceeding the "
                        f"{_REGISTRY_DOMINANCE_MAX_FRACTION:.0%} dominance "
                        f"threshold (Attacker F7: a typo'd or hostile entry "
                        f"tagging a majority of txs); review the registry"
                    ),
                )
            )
    return findings


# ----------------------------------------------------------------------
# Invariant 2: decimal range (echo of Task 7) -- FAIL
# ----------------------------------------------------------------------


def _check_decimal_range(
    transactions: list[OnChainTransaction],
) -> list[IntegrityFinding]:
    """FAIL if any leg carries ``amount_decimals`` outside ``[0, 36]``.

    Echo of the CSV reader's clamp (Task 7, Attacker F5). The CSV reader
    clamps on read, so a post-processor out-of-range leg indicates either a
    future RPC path that bypassed the clamp or a regression in the reader.
    FAIL-level (data corruption): a downstream consumer computing
    ``10 ** decimals`` would OOM on 10 ** 77.
    """
    bad: list[str] = []
    for tx in transactions:
        for event in tx.events:
            for leg in event.legs:
                if not (_MIN_DECIMALS <= leg.amount_decimals <= _MAX_DECIMALS):
                    bad.append(
                        f"tx_hash={tx.tx_hash} leg(asset={leg.asset}) "
                        f"amount_decimals={leg.amount_decimals}"
                    )
    if not bad:
        return []
    sample = bad[0]
    return [
        IntegrityFinding(
            check="decimal_range",
            severity=IntegritySeverity.FAIL,
            message=(
                f"{len(bad)} leg(s) carry amount_decimals outside "
                f"[{_MIN_DECIMALS},{_MAX_DECIMALS}] (first: {sample}); "
                f"a downstream consumer computing 10**decimals would OOM "
                f"(Attacker F5 echo of Task 7's CSV-reader clamp)"
            ),
        )
    ]


# ----------------------------------------------------------------------
# Invariant 3: unknown-direction rate (echo of processor hard fail) -- WARN
# ----------------------------------------------------------------------


def _check_unknown_direction_rate(
    transactions: list[OnChainTransaction],
) -> list[IntegrityFinding]:
    """WARN if >=1% of legs have ``direction=unknown``.

    Audit echo of the processor's run-level >1% hard fail (Task 9,
    :data:`on_chain_transaction.UNKNOWN_DIRECTION_MAX_FRACTION`). The
    processor raises :class:`FileProcessingError` at the gate; this post-run
    WARN surfaces the rate for audit (and catches a future path that
    bypasses the gate). WARN-level: the gate already aborted a >1% run, so a
    post-run WARN here means the rate is exactly at/above the threshold but
    the run was not gated (audit signal, not a second hard fail).

    The discriminator uses ``>=`` for the fraction (intentionally slightly
    stricter than the processor's ``>`` so an exactly-at-threshold rate is
    surfaced as an audit signal) and mirrors the processor's small-N
    absolute floor (``UNKNOWN_DIRECTION_MIN_ABSOLUTE``).
    """
    all_legs = [
        leg
        for tx in transactions
        for event in tx.events
        for leg in event.legs
    ]
    if not all_legs:
        return []
    total = len(all_legs)
    unknown = sum(1 for leg in all_legs if leg.direction == "unknown")
    fraction = unknown / total
    if (
        fraction >= UNKNOWN_DIRECTION_MAX_FRACTION
        and unknown >= UNKNOWN_DIRECTION_MIN_ABSOLUTE
    ):
        return [
            IntegrityFinding(
                check="unknown_direction_rate",
                severity=IntegritySeverity.WARN,
                message=(
                    f"{unknown}/{total} legs ({fraction:.1%}) have "
                    f"direction=unknown, at/above the "
                    f"{UNKNOWN_DIRECTION_MAX_FRACTION:.0%} threshold AND "
                    f"the {UNKNOWN_DIRECTION_MIN_ABSOLUTE}-leg absolute "
                    f"floor (audit echo of the processor's >1% hard fail; "
                    f"investigate the decoder if this run was not gated)"
                ),
            )
        ]
    return []


# ----------------------------------------------------------------------
# Invariant 4: closed operator_country enum (Attacker F1 cheap mitigation) -- FAIL
# ----------------------------------------------------------------------


def _check_operator_country_enum(
    registry: ContractRegistry,
) -> list[IntegrityFinding]:
    """FAIL if any registry entry's ``operator_country`` is not a valid ISO-3166 alpha-2.

    Cheap mitigation for Attacker F1 (a config-write attack setting a bogus
    country to misroute rewards). The registry loader (Task 9) already
    validates this at load time and fails closed; this post-run echo audits
    the LOADED registry (catches a regression in the loader, or a future
    path that constructs a ``ContractRegistry`` without the loader). A
    ``None`` ``operator_country`` (the Berachain B3 default) is valid.

    FAIL-level (data corruption): a bad country code would route rewards to
    the wrong source country in the IRS filing.
    """
    bad: list[str] = []
    for entry in registry.contracts.values():
        country = entry.operator_country
        if country is None:
            continue
        if not is_valid_iso3166_alpha2(country):
            bad.append(f"{entry.address}={country!r}")
    if not bad:
        return []
    return [
        IntegrityFinding(
            check="operator_country_enum",
            severity=IntegritySeverity.FAIL,
            message=(
                f"{len(bad)} contract registry entry(ies) carry an invalid "
                f"ISO-3166 alpha-2 operator_country (first: {bad[0]}); "
                f"Attacker F1 cheap mitigation: every operator_country must "
                f"be a valid alpha-2 code (the loader should have rejected "
                f"this - investigate the registry / loader path)"
            ),
        )
    ]
