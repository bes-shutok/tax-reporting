"""Tests for LP-token autodiscovery (Task 8, decision #11).

RED phase: these tests pin the behaviour of the three-layer LP-token
autodiscovery stack before the production module
``src/tax_reporting/infrastructure/on_chain/lp_autodiscovery.py`` and
``src/tax_reporting/infrastructure/on_chain/rpc_client.py`` exist.

Three-layer stack:
    1. Subgraph snapshot (primary) - O(1) address-keyed allowlist.
    2. Bytecode/implementation fingerprint (fallback) - one RPC call per
       unknown token: V2 pairs match the UniswapV2Pair runtime-bytecode
       fingerprint; Islands/Baults are EIP-1167 minimal proxies whose
       ``implementation()`` resolves to a known impl address.
    3. Tx-pattern (provenance only) - NOT a classification signal here.

CRITICAL RULE #1: NO live network calls. The RPC client is mocked via
:class:`unittest.mock.Mock`; tests assert call counts to verify the
snapshot short-circuits and the hard-cap behavior.

Hashing: per pyproject.toml there is NO ``web3``/``eth-hash``/``pysha3``
dependency, so the production fingerprint uses ``hashlib.sha256`` as a
stand-in for keccak256 (collision-resistant for matching; the specific
hash is a config detail - recorded in the execution log). Tests register
the sha256 of their canned bytecode in the fingerprint table so the match
is self-contained and deterministic.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from unittest.mock import Mock

import pytest

from tax_reporting.application.on_chain_config import load_lp_snapshot
from tax_reporting.domain.exceptions import ConfigurationError
from tax_reporting.infrastructure.on_chain.lp_autodiscovery import (
    LpAutodiscovery,
)

# Synthetic, obviously-fake addresses (Design Invariant #1; never real mainnet).
_SNAPSHOT_ADDR_PAIR = "0x000000000000000000000000000000000000dead"
_SNAPSHOT_ADDR_VAULT = "0x000000000000000000000000000000000000beef"
_SNAPSHOT_ADDR_STAKING = "0x0000000000000000000000000000000000001234"
_ADDR_NOT_IN_SNAPSHOT_V2 = "0x000000000000000000000000000000000000face"
_ADDR_NOT_IN_SNAPSHOT_ISLAND = "0x000000000000000000000000000000000000cafe"
_ADDR_UNKNOWN = "0x0000000000000000000000000000000000009999"

# Real KodiakIsland impl address (design record §9.2, cited). This is a
# documented trusted constant from the design record, not a new hardcoded
# value introduced here.
_KODIAK_ISLAND_IMPL = "0xCFe9Ee61c271fBA4D190498B5A71B8CB365a3590"

# Canned bytecodes the mock RPC client returns. Distinct per token so each
# test is self-contained. Production matches by hashing these.
_V2_PAIR_BYTECODE = "0xdead" + "42" * 100  # synthetic UniswapV2Pair-shaped
_ISLAND_PROXY_BYTECODE = "0xbeef" + "00" * 45  # EIP-1167 minimal-proxy shape
_UNKNOWN_BYTECODE = "0xabcd" + "01" * 30

# Committed example snapshot (tests MUST read committed synthetic data).
_EXAMPLE_SNAPSHOT = (
    Path(__file__).resolve().parents[3]
    / "resources"
    / "source"
    / "example"
    / "2025"
    / "berachain_lp_snapshot.json"
)


def _sha256_hex(hex_str: str) -> str:
    """Return the sha256 hex digest of the byte-string ``hex_str``."""
    return hashlib.sha256(hex_str.encode("ascii")).hexdigest()


def _snapshot_dict() -> dict[str, object]:
    """A minimal valid in-memory snapshot for fast tests."""
    return {
        "subgraph": "kodiak-v3",
        "subgraph_version": "2026-08-02.1",
        "snapshot_as_of_block": 1500000,
        "snapshot_as_of_date": "2025-12-15",
        "tokens": [
            {
                "token_address": _SNAPSHOT_ADDR_PAIR,
                "protocol": "Kodiak",
                "type": "Pair",
            },
            {
                "token_address": _SNAPSHOT_ADDR_VAULT,
                "protocol": "Kodiak",
                "type": "KodiakVault",
                "outputToken": _SNAPSHOT_ADDR_VAULT,
            },
            {
                "token_address": _SNAPSHOT_ADDR_STAKING,
                "protocol": "Kodiak",
                "type": "stakingToken",
            },
        ],
    }


@pytest.mark.unit
class TestLpAutodiscovery:
    """Test the three-layer LP-token autodiscovery stack."""

    def test_snapshot_primary_hit(self):
        # Given - a snapshot containing the three known token types and a
        # mocked RPC client whose call count we assert stays at 0.
        snapshot = load_lp_snapshot_from_dict(_snapshot_dict())
        rpc = Mock()
        autod = LpAutodiscovery(snapshot=snapshot, rpc_client=rpc)

        # When - a token_address present in the Pair / KodiakVault.outputToken
        # / stakingToken lists.
        result_pair = autod.is_lp_token(_SNAPSHOT_ADDR_PAIR)
        result_vault = autod.is_lp_token(_SNAPSHOT_ADDR_VAULT)
        result_staking = autod.is_lp_token(_SNAPSHOT_ADDR_STAKING)

        # Then - all classify True via the snapshot path; NO RPC call fired.
        assert result_pair.is_lp is True
        assert result_pair.source == "snapshot"
        assert result_vault.is_lp is True
        assert result_vault.source == "snapshot"
        assert result_staking.is_lp is True
        assert result_staking.source == "snapshot"
        assert rpc.get_code.call_count == 0
        assert rpc.get_implementation.call_count == 0

    def test_bytecode_fallback_v2_pair(self):
        # Given - a token NOT in snapshot; mock RPC returns the V2-pair
        # bytecode. The fingerprint table is seeded with the sha256 of that
        # exact bytecode under the "Pair" tag.
        snapshot = load_lp_snapshot_from_dict(_snapshot_dict())
        rpc = Mock()
        rpc.get_code.return_value = _V2_PAIR_BYTECODE
        fingerprints = {_sha256_hex(_V2_PAIR_BYTECODE): "Pair"}
        autod = LpAutodiscovery(
            snapshot=snapshot, rpc_client=rpc, fingerprints=fingerprints
        )

        # When
        result = autod.is_lp_token(_ADDR_NOT_IN_SNAPSHOT_V2)

        # Then - True via RPC fallback; exactly ONE eth_getCode call.
        assert result.is_lp is True
        assert result.source == "bytecode_v2"
        assert rpc.get_code.call_count == 1

    def test_bytecode_fallback_classifies_v2_pair(self):
        # Given - an LpAutodiscovery with a mock rpc_client whose get_code
        # returns bytecode whose sha256 matches a stored V2-pair fingerprint.
        # This pins the layer-2 fingerprint match through the DI seam (the
        # wiring exercised by Task 7: rpc_client is the seam the substituter
        # threads from ON_CHAIN_RPC_URL).
        snapshot = load_lp_snapshot_from_dict(_snapshot_dict())
        rpc = Mock()
        rpc.get_code.return_value = _V2_PAIR_BYTECODE
        fingerprints = {_sha256_hex(_V2_PAIR_BYTECODE): "Pair"}
        autod = LpAutodiscovery(
            snapshot=snapshot, rpc_client=rpc, fingerprints=fingerprints
        )

        # When - a token NOT in the snapshot.
        result = autod.is_lp_token(_ADDR_NOT_IN_SNAPSHOT_V2)

        # Then - the address classifies as a Pair via the bytecode fallback.
        assert result.is_lp is True
        assert result.source == "bytecode_v2"
        assert result.lp_type == "Pair"
        assert rpc.get_code.call_count == 1

    def test_bytecode_fallback_island_proxy(self):
        # Given - a token NOT in snapshot; its runtime bytecode does NOT
        # match a V2-pair fingerprint, so the fallback reads implementation()
        # and compares to the KodiakIsland impl address.
        snapshot = load_lp_snapshot_from_dict(_snapshot_dict())
        rpc = Mock()
        rpc.get_code.return_value = _ISLAND_PROXY_BYTECODE
        rpc.get_implementation.return_value = _KODIAK_ISLAND_IMPL
        fingerprints = {_sha256_hex(_V2_PAIR_BYTECODE): "Pair"}
        known_impls = {_KODIAK_ISLAND_IMPL: "KodiakVault"}
        autod = LpAutodiscovery(
            snapshot=snapshot,
            rpc_client=rpc,
            fingerprints=fingerprints,
            known_implementation_addresses=known_impls,
        )

        # When
        result = autod.is_lp_token(_ADDR_NOT_IN_SNAPSHOT_ISLAND)

        # Then - True via RPC fallback (implementation() path).
        assert result.is_lp is True
        assert result.source == "bytecode_island"
        assert rpc.get_code.call_count == 1
        assert rpc.get_implementation.call_count == 1

    def test_unknown_token_returns_false(self):
        # Given - a token NOT in snapshot and matching no fingerprint/impl.
        snapshot = load_lp_snapshot_from_dict(_snapshot_dict())
        rpc = Mock()
        rpc.get_code.return_value = _UNKNOWN_BYTECODE
        rpc.get_implementation.return_value = "0x" + "0" * 40
        fingerprints = {_sha256_hex(_V2_PAIR_BYTECODE): "Pair"}
        autod = LpAutodiscovery(
            snapshot=snapshot, rpc_client=rpc, fingerprints=fingerprints
        )

        # When
        result = autod.is_lp_token(_ADDR_UNKNOWN)

        # Then - False + a review flag with a specific, actionable reason
        # (never silently LP-classify an unknown address). Asserting the exact
        # flag value discriminates against a regression that dropped the flag
        # or mislabelled it; the helper sets "REVIEW" for the no-fingerprint
        # path (and "CAP_REACHED" only for the budget-exhausted path).
        assert result.is_lp is False
        assert result.review_flag == "REVIEW"
        assert result.review_reason is not None
        assert _ADDR_UNKNOWN.lower() in result.review_reason.lower()

    def test_snapshot_freshness_check(self, caplog):
        # Given - a snapshot whose snapshot_as_of_block predates the tax
        # year's latest tx block.
        snapshot = load_lp_snapshot_from_dict(_snapshot_dict())
        # snapshot_as_of_block in the fixture is 1_500_000.
        latest_tx_block = 1_600_000
        autod = LpAutodiscovery(snapshot=snapshot, rpc_client=Mock())

        # When
        with caplog.at_level(logging.WARNING):
            autod.check_freshness(latest_tx_block=latest_tx_block)

        # Then - a WARNING fires (M2: snapshot predates observed txs).
        assert any(
            "snapshot_as_of_block" in rec.message and "predates" in rec.message
            for rec in caplog.records
        ), f"expected a freshness WARNING, got: {[r.message for r in caplog.records]}"

    def test_snapshot_schema_validation_missing_subgraph_version(self):
        # Given - a snapshot missing subgraph_version.
        bad = _snapshot_dict()
        del bad["subgraph_version"]

        # Then - ConfigurationError naming the missing field.
        with pytest.raises(ConfigurationError, match="subgraph_version"):
            load_lp_snapshot_from_dict(bad)

    def test_snapshot_schema_validation_null_token_address(self):
        # Given - a snapshot with a null token_address field.
        bad = _snapshot_dict()
        bad["tokens"][0]["token_address"] = None

        # Then - ConfigurationError naming the null field.
        with pytest.raises(ConfigurationError, match="token_address"):
            load_lp_snapshot_from_dict(bad)

    def test_snapshot_schema_validation_rejects_latest_version(self):
        # Given - a snapshot whose subgraph_version is "latest" (unpinned).
        bad = _snapshot_dict()
        bad["subgraph_version"] = "latest"

        # Then - ConfigurationError (subgraph must be pinned, not latest).
        with pytest.raises(ConfigurationError, match="subgraph_version"):
            load_lp_snapshot_from_dict(bad)

    def test_is_lp_token_respects_cap(self):
        # Given - cap=2 and a mock rpc_client whose get_code returns unknown
        # bytecode (so each non-snapshot token consumes one RPC-touching
        # lookup). The cap bounds RPC calls via is_lp_token (the sole cap
        # entry point): the first ``cap`` lookups hit the RPC, the rest
        # return CAP_REACHED without an RPC call.
        snapshot = load_lp_snapshot_from_dict(_snapshot_dict())
        rpc = Mock()
        rpc.get_code.return_value = _UNKNOWN_BYTECODE
        rpc.get_implementation.return_value = "0x" + "0" * 40
        autod = LpAutodiscovery(
            snapshot=snapshot,
            rpc_client=rpc,
            fingerprints={_sha256_hex(_V2_PAIR_BYTECODE): "Pair"},
            cap=2,
        )
        addrs = [
            "0x000000000000000000000000000000000000a001",
            "0x000000000000000000000000000000000000a002",
            "0x000000000000000000000000000000000000a003",
        ]

        # When - call is_lp_token 3 times with distinct non-snapshot addresses.
        r1 = autod.is_lp_token(addrs[0])
        r2 = autod.is_lp_token(addrs[1])
        r3 = autod.is_lp_token(addrs[2])

        # Then - exactly 2 RPC calls (the cap allows 2 RPC-touching lookups);
        # the 3rd call returns CAP_REACHED and does NOT call get_code.
        assert rpc.get_code.call_count == 2
        assert r1.review_flag != "CAP_REACHED"
        assert r2.review_flag != "CAP_REACHED"
        assert r3.review_flag == "CAP_REACHED"

    def test_cap_resets_per_instance(self):
        # Given - two separate LpAutodiscovery instances each with cap=2.
        # The counter is per-instance (seeded in __init__), so exhausting one
        # does NOT exhaust the other.
        snapshot = load_lp_snapshot_from_dict(_snapshot_dict())
        rpc1 = Mock()
        rpc1.get_code.return_value = _UNKNOWN_BYTECODE
        rpc1.get_implementation.return_value = "0x" + "0" * 40
        rpc2 = Mock()
        rpc2.get_code.return_value = _UNKNOWN_BYTECODE
        rpc2.get_implementation.return_value = "0x" + "0" * 40
        autod1 = LpAutodiscovery(
            snapshot=snapshot,
            rpc_client=rpc1,
            fingerprints={_sha256_hex(_V2_PAIR_BYTECODE): "Pair"},
            cap=2,
        )
        autod2 = LpAutodiscovery(
            snapshot=snapshot,
            rpc_client=rpc2,
            fingerprints={_sha256_hex(_V2_PAIR_BYTECODE): "Pair"},
            cap=2,
        )

        # When - exhaust instance 1's budget (3 calls > cap 2).
        autod1.is_lp_token("0x000000000000000000000000000000000000c001")
        autod1.is_lp_token("0x000000000000000000000000000000000000c002")
        autod1.is_lp_token("0x000000000000000000000000000000000000c003")

        # Then - instance 2 still has a fresh budget; its first 2 calls hit
        # the RPC, the 3rd returns CAP_REACHED.
        r1 = autod2.is_lp_token("0x000000000000000000000000000000000000d001")
        r2 = autod2.is_lp_token("0x000000000000000000000000000000000000d002")
        r3 = autod2.is_lp_token("0x000000000000000000000000000000000000d003")
        assert rpc2.get_code.call_count == 2
        assert r1.review_flag != "CAP_REACHED"
        assert r2.review_flag != "CAP_REACHED"
        assert r3.review_flag == "CAP_REACHED"

    def test_load_committed_example_snapshot(self):
        # Given - the committed example snapshot file (synthetic addresses).
        snapshot = load_lp_snapshot(_EXAMPLE_SNAPSHOT)

        # Then - freshness metadata present; the synthetic addresses load.
        assert snapshot.snapshot_as_of_block == 1500000
        assert snapshot.subgraph_version != "latest"
        assert snapshot.subgraph_version  # non-empty
        assert _SNAPSHOT_ADDR_PAIR in snapshot.tokens
        assert _SNAPSHOT_ADDR_VAULT in snapshot.tokens
        assert _SNAPSHOT_ADDR_STAKING in snapshot.tokens


def load_lp_snapshot_from_dict(data: dict[str, object]):
    """Helper: build an LpSnapshot from an in-memory dict (no file I/O).

    Wraps :func:`load_lp_snapshot`'s core validation so tests can feed
    malformed dicts without writing temp files.
    """
    from tax_reporting.application.on_chain_config import build_lp_snapshot

    return build_lp_snapshot(data, source="<inline-test>")
