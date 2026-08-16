"""Post-cutover on-chain integrity invariants (Plan Task 13).

These RUN-LEVEL (post-aggregation, not per-row -- AGENTS.md) checks catch
systemic on-chain-source corruption AFTER the processor has produced
``OnChainTransaction`` objects and AFTER the contract registry has loaded.
They are the audit echo / second line of defense for the per-row guards:

- **Registry dominance (Attacker F7):** no single contract-registry entry
  accounts for >30% of tags. Catches a typo'd registry entry tagging a
  majority of transactions (a config-write attack or a copy-paste error).
- **Decimal overflow guard (echo of Task 7):** zero legs carry
  ``amount_decimals`` outside ``[0, 36]``. The CSV reader clamps on read;
  this check guards the post-processor output (and any future RPC path
  that bypasses the CSV reader).
- **Unknown-direction rate (echo of the processor's hard fail):** <1% of
  legs have ``direction=unknown``. The processor already raises
  ``FileProcessingError`` at >1%; this post-run echo is the audit signal
  (WARN) for a run that slipped through (e.g. a unit test driving the
  processor directly, or a future path that does not gate on the
  invariant).
- **Closed ``operator_country`` enum (Attacker F1 cheap mitigation):**
  every ``operator_country`` value in the contract registry is a valid
  ISO-3166 alpha-2 code. The registry loader already fails closed on an
  invalid code; this post-run echo audits the loaded registry.

Severity assignments (per AGENTS.md "warn or fail per severity"):

- **WARN (soft, audit signal):** registry dominance >30%; unknown-direction
  rate >=1%. These are systemic-corruption *signals* -- a WARN surfaces the
  finding for human review without aborting a run that may still be
  salvageable (the processor's hard fail already covers the >1% unknown
  case at the gate; the WARN is the audit echo).
- **FAIL (hard, data corruption):** decimal-out-of-range legs; invalid
  ``operator_country`` code. These indicate the data is materially
  corrupt and downstream EUR/origin resolution would be wrong; the check
  raises ``FileProcessingError``.

The checker is PURE: it takes the data and returns an
:class:`IntegrityReport`; no I/O, no logging side effects beyond WARN
emission. Wired into ``main.py``'s on-chain TH path (Plan Task 11) as a
post-processor step.

Per AGENTS.md crypto-tests rule, these tests use committed synthetic data
(the example contract registry from Task 9 + inline synthetic
``OnChainTransaction`` objects); they NEVER reference gitignored personal
data.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from tax_reporting.application.on_chain_config import (
    ContractEntry,
    ContractRegistry,
    build_contract_registry,
)
from tax_reporting.domain.exceptions import FileProcessingError
from tax_reporting.domain.on_chain_transaction import (
    Event,
    EventType,
    Gas,
    Leg,
    OnChainTransaction,
    SubType,
)
from tax_reporting.infrastructure.on_chain.integrity_invariants import (
    IntegritySeverity,
    check_on_chain_integrity,
)

# Repo root (tests/end_to_end/... -> parents[2]).
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
# Committed example contract registry (Task 9) ships EMPTY operator_country
# for every entry (B3 resolution). Tests read this committed file, never the
# gitignored per-user registry at resources/source/2025/berachain_contracts.json.
_EXAMPLE_CONTRACTS = (
    _PROJECT_ROOT / "resources" / "source" / "example" / "2025" / "berachain_contracts.json"
)

# Synthetic on-chain addresses (Design Invariant #1; never real mainnet) used
# to build synthetic Events that reference registry entries for the dominance
# check.
_DOMINANT_DISTRIBUTOR = "0x000000000000000000000000000000000000beef"  # in example registry
_NORMAL_DISTRIBUTOR = "0xd2f19a7900000000000000000000000000000000"  # NOT in example registry


def _registry_from_example() -> ContractRegistry:
    """Load the committed example contract registry (Task 9)."""
    import json

    data = json.loads(_EXAMPLE_CONTRACTS.read_text(encoding="utf-8"))
    return build_contract_registry(data, source=str(_EXAMPLE_CONTRACTS))


def _leg(
    *,
    asset: str = "BGT",
    decimals: int = 18,
    direction: str = "in",
    from_address: str | None = None,
) -> Leg:
    """Build a synthetic Leg with sane defaults for the integrity tests."""
    return Leg(
        asset=asset,
        token_address=None,
        amount_raw=10**18,
        amount_decimals=decimals,
        direction=direction,  # type: ignore[arg-type]
        from_address=from_address,
        to_address="0xwallet",
    )


def _reward_tx(
    *,
    tx_hash: str,
    sender: str | None,
    asset: str = "BGT",
    decimals: int = 18,
) -> OnChainTransaction:
    """Build a synthetic one-Event Reward ``OnChainTransaction``.

    The leg's ``from_address`` is the reward sender; the processor tags a
    Reward as ``staking`` when the sender is a registered distributor, else
    ``spam``. The integrity dominance check counts how many txs each
    registry entry (by sender address) accounts for.
    """
    leg = _leg(asset=asset, decimals=decimals, direction="in", from_address=sender)
    event = Event(
        event_id=f"{tx_hash}#1",
        event_type=EventType.Reward,
        sub_type=SubType.staking,
        legs=(leg,),
        parent_tx_hash=tx_hash,
    )
    return OnChainTransaction(
        tx_hash=tx_hash,
        block_number=1,
        timestamp_utc=datetime(2025, 1, 1, tzinfo=UTC),
        chain="Berachain",
        wallet_label="BERA",
        wallet_address="0xwallet",
        gas=Gas(asset="BERA", amount_raw=10**9, decimals=18),
        events=(event,),
    )


# ----------------------------------------------------------------------
# ContractRegistry helpers for the operator_country check
# ----------------------------------------------------------------------


def _registry_with_operator_country(country: str | None) -> ContractRegistry:
    """Build a one-entry registry carrying ``country`` as operator_country.

    Used to exercise the closed-enum check in isolation: an invalid code
    (e.g. ``"XX"``) must FAIL the invariant; a valid code (e.g. ``"VG"``)
    must pass; ``None`` (the Berachain B3 default) must pass.
    """
    entry = ContractEntry(
        address=_DOMINANT_DISTRIBUTOR,
        label="Test Distributor",
        kind="reward_distributor",
        protocol="Test",
        operator_country=country,
        citation=("https://example.org/primary-source" if country is not None else None),
    )
    return ContractRegistry(
        chain="Berachain",
        contracts={entry.address: entry},
        source="<inline-test>",
    )


class TestOnChainIntegrity:
    """Plan Task 13: the four post-cutover on-chain integrity invariants."""

    # ------------------------------------------------------------------
    # 1. Registry dominance (Attacker F7) -- WARN
    # ------------------------------------------------------------------

    def test_no_single_registry_entry_dominates(self) -> None:
        """No single contract-registry entry accounts for >30% of tags.

        A clean run (each sender accounting for <=30% of txs) passes with no
        dominance finding. A synthetic run where one registry entry tags a
        MAJORITY of txs (e.g. 6 of 10 txs all tagged by the same distributor
        address) fires a WARN-level dominance finding.
        """
        registry = _registry_from_example()

        # Clean run: 4 txs, each from a DISTINCT sender (none in the
        # registry), so no single registry entry tags any tx -> 0% dominance
        # -> passes.
        clean_txs = [
            _reward_tx(tx_hash=f"0xclean{i}", sender=_NORMAL_DISTRIBUTOR)
            for i in range(4)
        ]
        clean_report = check_on_chain_integrity(
            transactions=clean_txs, registry=registry
        )
        dominance_clean = [
            f for f in clean_report.findings if f.check == "registry_dominance"
        ]
        assert dominance_clean == [], (
            f"clean run should have no dominance finding, got {dominance_clean}"
        )
        assert not clean_report.has_failures

        # Dominated run: 10 txs, 7 of which all come from the same registered
        # distributor (70% > 30% threshold) -> WARN-level dominance finding.
        dominated_txs = [
            _reward_tx(tx_hash=f"0xdom{i}", sender=_DOMINANT_DISTRIBUTOR)
            for i in range(7)
        ] + [
            _reward_tx(tx_hash=f"0xother{i}", sender=_NORMAL_DISTRIBUTOR)
            for i in range(3)
        ]
        dominated_report = check_on_chain_integrity(
            transactions=dominated_txs, registry=registry
        )
        dominance = [
            f for f in dominated_report.findings if f.check == "registry_dominance"
        ]
        assert len(dominance) == 1, (
            f"dominated run should fire exactly one dominance finding, got {dominance}"
        )
        finding = dominance[0]
        assert finding.severity is IntegritySeverity.WARN, (
            f"dominance is a WARN-level audit signal, got {finding.severity}"
        )
        # The finding must name the dominant address + its share (specific,
        # actionable - AGENTS.md).
        assert _DOMINANT_DISTRIBUTOR in finding.message
        assert "70%" in finding.message
        # WARN-level findings do NOT raise (audit signal); only FAIL raises.
        assert not dominated_report.has_failures

    # ------------------------------------------------------------------
    # 2. Decimal-out-of-range (echo of Task 7) -- FAIL
    # ------------------------------------------------------------------

    def test_no_decimal_out_of_range(self) -> None:
        """Zero legs carry ``amount_decimals`` outside ``[0, 36]``.

        A clean run (all legs within ``[0, 36]``) passes. A run with one leg
        carrying ``amount_decimals=77`` fails (FAIL-level: indicates data
        corruption; a downstream consumer computing ``10 ** 77`` would OOM).
        """
        registry = _registry_from_example()

        # Clean run: all legs at 18 decimals (EVM standard).
        clean_txs = [_reward_tx(tx_hash="0xdec_clean", sender=_NORMAL_DISTRIBUTOR)]
        clean_report = check_on_chain_integrity(
            transactions=clean_txs, registry=registry
        )
        decimal_clean = [
            f for f in clean_report.findings if f.check == "decimal_range"
        ]
        assert decimal_clean == [], (
            f"clean run should have no decimal finding, got {decimal_clean}"
        )

        # Corrupt run: one leg with amount_decimals=77 (outside [0, 36]).
        corrupt_txs = [
            _reward_tx(
                tx_hash="0xdec_bad",
                sender=_NORMAL_DISTRIBUTOR,
                decimals=77,
            )
        ]
        corrupt_report = check_on_chain_integrity(
            transactions=corrupt_txs, registry=registry
        )
        decimal = [
            f for f in corrupt_report.findings if f.check == "decimal_range"
        ]
        assert len(decimal) == 1, (
            f"corrupt run should fire exactly one decimal finding, got {decimal}"
        )
        finding = decimal[0]
        assert finding.severity is IntegritySeverity.FAIL, (
            f"decimal-out-of-range is FAIL-level (data corruption), got {finding.severity}"
        )
        assert "77" in finding.message
        assert corrupt_report.has_failures
        # FAIL-level findings are surfaced as a raised FileProcessingError by
        # ``raise_if_failed()`` (the caller decides whether to raise; the pure
        # ``check_on_chain_integrity`` only records the finding).
        with pytest.raises(FileProcessingError, match="77"):
            corrupt_report.raise_if_failed()

    # ------------------------------------------------------------------
    # 3. Unknown-direction rate (echo of processor hard fail) -- WARN
    # ------------------------------------------------------------------

    def test_unknown_direction_rate_under_threshold(self) -> None:
        """<1% of legs have direction=``unknown``.

        A clean run (0% unknown) passes. A run with >1% unknown-direction
        legs fires a WARN (the audit echo; the processor already raises
        ``FileProcessingError`` at >1% at the gate -- this is the post-run
        audit signal that the invariant held or, if a future path bypasses
        the gate, surfaces the regression).
        """
        registry = _registry_from_example()

        # Clean run: 5 txs, all legs direction=in (0% unknown).
        clean_txs = [
            _reward_tx(tx_hash=f"0xunk_clean{i}", sender=_NORMAL_DISTRIBUTOR)
            for i in range(5)
        ]
        clean_report = check_on_chain_integrity(
            transactions=clean_txs, registry=registry
        )
        unk_clean = [
            f for f in clean_report.findings if f.check == "unknown_direction_rate"
        ]
        assert unk_clean == [], (
            f"clean run should have no unknown-direction finding, got {unk_clean}"
        )

        # High-unknown run: 5 unknown-direction legs out of 10 total legs
        # (50% > 1% threshold AND count=5 >= absolute floor). Build via a leg
        # override. (The small-N absolute floor mirrors the processor's gate;
        # a sub-floor count would not fire the audit echo.)
        high_unk_txs: list[OnChainTransaction] = []
        for i in range(5):
            high_unk_txs.append(
                _reward_tx(tx_hash=f"0xunk_in{i}", sender=_NORMAL_DISTRIBUTOR)
            )
        for i in range(5):
            leg = _leg(direction="unknown", from_address=_NORMAL_DISTRIBUTOR)
            event = Event(
                event_id=f"0xunk_bad{i}#1",
                event_type=EventType.Unknown,
                sub_type=None,
                legs=(leg,),
                parent_tx_hash=f"0xunk_bad{i}",
            )
            high_unk_txs.append(
                OnChainTransaction(
                    tx_hash=f"0xunk_bad{i}",
                    block_number=1,
                    timestamp_utc=datetime(2025, 1, 1, tzinfo=UTC),
                    chain="Berachain",
                    wallet_label="BERA",
                    wallet_address="0xwallet",
                    gas=None,
                    events=(event,),
                )
            )
        high_report = check_on_chain_integrity(
            transactions=high_unk_txs, registry=registry
        )
        unk = [
            f for f in high_report.findings if f.check == "unknown_direction_rate"
        ]
        assert len(unk) == 1, (
            f"high-unknown run should fire exactly one finding, got {unk}"
        )
        finding = unk[0]
        assert finding.severity is IntegritySeverity.WARN, (
            f"unknown-direction is a WARN-level audit signal, got {finding.severity}"
        )
        assert "unknown" in finding.message
        # WARN-level findings do NOT raise.
        assert not high_report.has_failures

    # ------------------------------------------------------------------
    # 4. Closed operator_country enum (Attacker F1 cheap mitigation) -- FAIL
    # ------------------------------------------------------------------

    def test_operator_country_closed_enum(self) -> None:
        """Every ``operator_country`` value is a valid ISO-3166 alpha-2 code.

        A registry with no ``operator_country`` (the Berachain B3 default)
        passes. A registry with a valid code (e.g. ``"VG"``) passes. A
        registry with an INVALID code (e.g. ``"XX"``) fails (FAIL-level: a
        bad country code would route rewards to the wrong source country).
        """
        empty_txs: list[OnChainTransaction] = []

        # B3 default: empty operator_country (Berachain) -> passes.
        empty_registry = _registry_with_operator_country(country=None)
        empty_report = check_on_chain_integrity(
            transactions=empty_txs, registry=empty_registry
        )
        country_empty = [
            f for f in empty_report.findings if f.check == "operator_country_enum"
        ]
        assert country_empty == [], (
            f"empty operator_country should pass, got {country_empty}"
        )

        # Valid ISO-3166 alpha-2 (VG = British Virgin Islands) -> passes.
        valid_registry = _registry_with_operator_country(country="VG")
        valid_report = check_on_chain_integrity(
            transactions=empty_txs, registry=valid_registry
        )
        country_valid = [
            f for f in valid_report.findings if f.check == "operator_country_enum"
        ]
        assert country_valid == [], (
            f"valid operator_country 'VG' should pass, got {country_valid}"
        )

        # Invalid code (XX is NOT a valid ISO-3166 alpha-2 code) -> FAIL.
        invalid_registry = _registry_with_operator_country(country="XX")
        invalid_report = check_on_chain_integrity(
            transactions=empty_txs, registry=invalid_registry
        )
        country_invalid = [
            f for f in invalid_report.findings if f.check == "operator_country_enum"
        ]
        assert len(country_invalid) == 1, (
            f"invalid 'XX' should fire exactly one finding, got {country_invalid}"
        )
        finding = country_invalid[0]
        assert finding.severity is IntegritySeverity.FAIL, (
            f"invalid operator_country is FAIL-level (corruption), got {finding.severity}"
        )
        assert "XX" in finding.message
        assert invalid_report.has_failures
        with pytest.raises(FileProcessingError, match="XX"):
            invalid_report.raise_if_failed()
