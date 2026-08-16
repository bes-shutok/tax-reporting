"""Domain-layer regression tests for the on-chain config types.

These tests pin two things that review F12 (layer-violation refactor) made
load-bearing:

1. The five frozen dataclasses + the ``is_valid_iso3166_alpha2`` validator
   are importable from :mod:`tax_reporting.domain.on_chain_config` and
   construct/validate correctly.
2. The four infrastructure readers (processor, integrity checker, decoder,
   autodiscovery) resolve these types to the DOMAIN module, NOT the
   application loader. This is the discriminating test: if a future change
   re-introduces ``from tax_reporting.application.on_chain_config import ...``
   in any infrastructure module, the ``__module__`` assertion fails here.
"""

from __future__ import annotations

import datetime

import pytest

from tax_reporting.domain.on_chain_config import (
    ContractEntry,
    ContractRegistry,
    LpSnapshot,
    LpTokenEntry,
    OnChainWalletConfig,
    is_valid_iso3166_alpha2,
)

_DOMAIN_MODULE = "tax_reporting.domain.on_chain_config"


@pytest.mark.unit
class TestOnChainConfigDomainTypes:
    """Pin construction + validation of the moved domain types."""

    def test_on_chain_wallet_config_constructs(self):
        cfg = OnChainWalletConfig(
            chain="Berachain",
            chainid=80094,
            label="Ledger Berachain (BERA)",
            address="0xdead000000000000000000000000000000000000",
            native_ticker="BERA",
            start_date=datetime.date(2025, 2, 6),
            end_date=datetime.date(2025, 12, 31),
        )
        assert cfg.chain == "Berachain"
        assert cfg.chainid == 80094
        # Frozen: mutation must raise.
        with pytest.raises((AttributeError, TypeError)):
            cfg.chain = "Ethereum"  # type: ignore[misc]

    def test_lp_snapshot_and_token_entry_construct(self):
        token = LpTokenEntry(
            token_address="0xabc0000000000000000000000000000000000000",
            protocol="Kodiak",
            lp_type="Pair",
        )
        snapshot = LpSnapshot(
            subgraph="kodiak-islands",
            subgraph_version="2025-01",
            snapshot_as_of_block=1_500_000,
            snapshot_as_of_date="2025-01-15",
            tokens={token.token_address: token},
            source="example",
        )
        assert snapshot.tokens[token.token_address] is token

    def test_contract_registry_get_is_case_insensitive(self):
        entry = ContractEntry(
            address="0xd2f19a7900000000000000000000000000000000",
            label="RewardDistributor",
            kind="reward_distributor",
            protocol="Berachain",
            operator_country=None,
            citation=None,
        )
        # Stored under the lower-cased address (the loader convention).
        registry = ContractRegistry(
            chain="Berachain",
            contracts={entry.address: entry},
            source="example",
        )
        # Lookup is case-insensitive (the processor passes mixed-case checksummed addresses).
        assert registry.get(entry.address.upper()) is entry
        assert registry.get("0xUNRELATED000000000000000000000000000000") is None

    def test_is_valid_iso3166_alpha2_closed_enum(self):
        # Valid alpha-2 codes (case-insensitive on input).
        assert is_valid_iso3166_alpha2("PT") is True
        assert is_valid_iso3166_alpha2("vg") is True  # British Virgin Islands
        # Invalid / malformed.
        assert is_valid_iso3166_alpha2("XX") is False
        assert is_valid_iso3166_alpha2("") is False


@pytest.mark.unit
class TestInfrastructureImportsFromDomain:
    """Discriminating test: infrastructure resolves these types to the DOMAIN
    module, not the application loader (review F12 layer-violation fix).

    If a future change re-introduces
    ``from tax_reporting.application.on_chain_config import ContractRegistry``
    in any of these four modules, the ``__module__`` assertion fails here.
    """

    def test_berachain_processor_contract_registry_from_domain(self):
        import importlib

        proc = importlib.import_module(
            "tax_reporting.infrastructure.on_chain.berachain_processor"
        )
        # The processor binds ContractRegistry at module top-level (it imports it
        # for the BerachainProcessor constructor annotation + _classify_events).
        assert proc.ContractRegistry.__module__ == _DOMAIN_MODULE

    def test_integrity_invariants_types_from_domain(self):
        import importlib

        inv = importlib.import_module(
            "tax_reporting.infrastructure.on_chain.integrity_invariants"
        )
        # The integrity module imports ContractRegistry + is_valid_iso3166_alpha2.
        # Both must resolve to the domain module.
        assert inv.ContractRegistry.__module__ == _DOMAIN_MODULE
        assert inv.is_valid_iso3166_alpha2.__module__ == _DOMAIN_MODULE

    def test_bera_decoder_wallet_config_from_domain(self):
        import importlib

        dec = importlib.import_module(
            "tax_reporting.infrastructure.on_chain.bera_decoder"
        )
        assert dec.OnChainWalletConfig.__module__ == _DOMAIN_MODULE

    def test_no_infrastructure_module_imports_on_chain_config_from_application(self):
        """Grep-level guard: no infrastructure module under on_chain/ imports
        the moved types from the application loader. This is the high-recall
        backstop for the four re-pointed modules plus any future addition."""
        import pkgutil

        import tax_reporting.infrastructure.on_chain as on_chain_pkg

        offenders: list[str] = []
        for mod_info in pkgutil.iter_modules(on_chain_pkg.__path__):
            mod_name = f"tax_reporting.infrastructure.on_chain.{mod_info.name}"
            import importlib

            mod = importlib.import_module(mod_name)
            from pathlib import Path

            src = Path(mod.__file__).read_text(encoding="utf-8")
            if "application.on_chain_config import" in src or (
                "application import on_chain_config" in src
            ):
                offenders.append(mod_name)
        assert not offenders, (
            f"infrastructure modules still import from application.on_chain_config "
            f"(layer violation, review F12): {offenders}"
        )
