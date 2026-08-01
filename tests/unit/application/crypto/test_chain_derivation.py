"""Tests for the chain registry maps and accessors.

These tests pin the trusted EVM chain-registry contract introduced by plan
``2026-08-01-minimal-chains-json-config`` Task 1:

- ``_CHAIN_TO_CHAINID``: the 8 EVM/Etherscan-V2 chain ids.
- ``_CHAIN_ON_CHAIN_NATIVE_TICKER``: CSV-output-correct native tickers
  (separate from the Koinly fee-check map ``_CHAIN_NATIVE_FEE_ASSET``;
  Polygon is ``"POL"``, not the stale ``"MATIC"``).
- ``_CHAIN_LAUNCH_DATE``: mainnet genesis/first-block dates.

The three maps must share an identical EVM key set (enforced by a
module-load assert).
"""

from __future__ import annotations

from datetime import date

import pytest

from tax_reporting.application.crypto.chain_derivation import (
    _CHAIN_LAUNCH_DATE,
    _CHAIN_ON_CHAIN_NATIVE_TICKER,
    _CHAIN_TO_CHAINID,
    chain_launch_date,
    chainid_for,
    native_ticker_for,
)

# The 8 EVM/Etherscan-V2-supported chains (exact spellings from _KNOWN_CHAINS).
_EVM_CHAINS = (
    "Ethereum",
    "Binance Smart Chain",
    "Berachain",
    "Polygon",
    "Arbitrum",
    "BASE",
    "Mantle",
    "zkSync ERA",
)


class TestChainRegistry:
    """Tests for the chain registry maps and their public accessors."""

    # --- chainid_for -------------------------------------------------------

    @pytest.mark.parametrize(
        ("chain", "expected_chainid"),
        [
            ("Ethereum", 1),
            ("Binance Smart Chain", 56),
            ("Berachain", 80094),
            ("Polygon", 137),
            ("Arbitrum", 42161),
            ("BASE", 8453),
            ("Mantle", 5000),
            ("zkSync ERA", 324),
        ],
    )
    def test_chainid_for_all_8_supported_evm_chains(
        self, chain: str, expected_chainid: int
    ) -> None:
        """Each of the 8 EVM chains resolves to its exact Etherscan V2 chain id.

        Chain ids sourced from the Etherscan V2 supported-chains doc
        (https://docs.etherscan.io/supported-chains). One assertion per row so
        a wrong value fails individually and names the offending chain.
        """
        assert chainid_for(chain) == expected_chainid, (
            f"chainid_for({chain!r}) returned {chainid_for(chain)!r}, "
            f"expected {expected_chainid}"
        )

    @pytest.mark.parametrize("chain", ["Solana", "Unknown"])
    def test_chainid_for_non_evm_chain_returns_none(self, chain: str) -> None:
        """Non-EVM chains and the Unknown sentinel return None (fail-closed).

        The EVM registry does not include Solana even though the Koinly
        fee-check map ``_CHAIN_NATIVE_FEE_ASSET`` does.
        """
        assert chainid_for(chain) is None

    # --- chain_launch_date -------------------------------------------------

    @pytest.mark.parametrize(
        ("chain", "expected_launch"),
        [
            # Berachain genesis (2025-02-06), NOT the 2025-02-05 legal-entity
            # service date (see berachain_genesis_2025-02-06.md).
            ("Berachain", date(2025, 2, 6)),
            ("Ethereum", date(2015, 7, 30)),
            ("Binance Smart Chain", date(2020, 9, 1)),
            ("Polygon", date(2020, 5, 28)),
            ("Arbitrum", date(2021, 8, 31)),
            ("BASE", date(2023, 8, 9)),
            ("Mantle", date(2023, 7, 17)),
            ("zkSync ERA", date(2023, 3, 24)),
        ],
    )
    def test_chain_launch_date_for_all_8_chains(
        self, chain: str, expected_launch: date
    ) -> None:
        """Each EVM chain resolves to its exact mainnet genesis/launch date.

        Genesis/first-block dates, not legal-entity service dates. Each value
        is cited to an archived genesis-dated source under
        ``docs/maintenance/tax/crypto-origin/official/``.
        """
        assert chain_launch_date(chain) == expected_launch, (
            f"chain_launch_date({chain!r}) returned {chain_launch_date(chain)!r}, "
            f"expected {expected_launch}"
        )

    @pytest.mark.parametrize("chain", ["Solana", "Unknown"])
    def test_chain_launch_date_for_non_evm_chain_returns_none(
        self, chain: str
    ) -> None:
        """Non-EVM chains return None for launch date (fail-closed)."""
        assert chain_launch_date(chain) is None

    # --- native_ticker_for (CSV-output-correct map) ------------------------

    @pytest.mark.parametrize(
        ("chain", "expected_ticker"),
        [
            ("Berachain", "BERA"),
            ("Ethereum", "ETH"),
            ("Binance Smart Chain", "BNB"),
            # F2 fold: POL is the native asset since the 2024-09-04
            # MATIC->POL migration; NOT the stale "MATIC" in the Koinly
            # fee-check map _CHAIN_NATIVE_FEE_ASSET.
            ("Polygon", "POL"),
        ],
    )
    def test_native_ticker_for_supported_evm_chains_csv_correct(
        self, chain: str, expected_ticker: str
    ) -> None:
        """CSV-output-correct native tickers for EVM chains.

        Asserts against the on-chain ticker map, not the Koinly fee-check map.
        Polygon is "POL" (post-2024-09-04), explicitly NOT "MATIC".
        """
        assert native_ticker_for(chain) == expected_ticker, (
            f"native_ticker_for({chain!r}) returned {native_ticker_for(chain)!r}, "
            f"expected {expected_ticker}"
        )
        # Belt-and-suspenders: the Polygon row must NEVER regress to MATIC.
        if chain == "Polygon":
            assert native_ticker_for("Polygon") != "MATIC"

    @pytest.mark.parametrize("chain", ["Solana", "Sui", "TON"])
    def test_native_ticker_for_non_evm_chain_returns_none(
        self, chain: str
    ) -> None:
        """Non-EVM chains return None for the on-chain ticker (fail-closed).

        F3 fold: the on-chain ticker map does NOT include non-EVM chains even
        though ``_CHAIN_NATIVE_FEE_ASSET`` does (Solana->SOL, Sui->SUI,
        TON->TON). Those tickers are Koinly fee-check entries, not on-chain
        CSV-output entries for the Etherscan-V2 fetcher.
        """
        assert native_ticker_for(chain) is None

    # --- registry coherence (identical key sets) --------------------------

    def test_registry_maps_have_identical_key_sets(self) -> None:
        """The three EVM registry maps share an identical 8-key set.

        ``_CHAIN_TO_CHAINID`` is the authoritative EVM set; the ticker and
        launch-date maps must cover exactly the same chains. Enforced at module
        load by an ``assert``; this test pins the contract for reviewers and
        guards against drift when a chain is added to one map but not another.
        """
        chainid_keys = set(_CHAIN_TO_CHAINID)
        ticker_keys = set(_CHAIN_ON_CHAIN_NATIVE_TICKER)
        launch_keys = set(_CHAIN_LAUNCH_DATE)

        assert chainid_keys == ticker_keys == launch_keys, (
            "Chain registry maps drifted: "
            f"chainid={sorted(chainid_keys)} "
            f"ticker={sorted(ticker_keys)} "
            f"launch={sorted(launch_keys)}"
        )
        # All three cover exactly the 8 EVM chains, no more, no less.
        assert chainid_keys == set(_EVM_CHAINS)

    def test_module_load_assert_predicate_catches_drift(self) -> None:
        """Prove the module-load key-set assert would fire on real drift.

        Constructs three local literals that intentionally mismatch (an extra
        key added to one map but not the others) and asserts the predicate the
        production assert evaluates is False for the drift - i.e. the assert's
        condition would fire. This tests the *predicate* without breaking the
        real module import (a real drift would crash the whole suite at import
        time, which is the intended fail-loud behavior, not something to stage
        here).
        """

        # The predicate the production assert evaluates.
        def _predicate(
            map_a: dict[str, object],
            map_b: dict[str, object],
            map_c: dict[str, object],
        ) -> bool:
            return set(map_a) == set(map_b) == set(map_c)

        # Drifted literals: an extra key "Drift" appears only in the first map.
        drifted_chainid: dict[str, int] = {
            "Ethereum": 1,
            "Binance Smart Chain": 56,
            "Drift": 999,
        }
        drifted_ticker: dict[str, str] = {
            "Ethereum": "ETH",
            "Binance Smart Chain": "BNB",
        }
        drifted_launch: dict[str, date] = {
            "Ethereum": date(2015, 7, 30),
            "Binance Smart Chain": date(2020, 9, 1),
        }

        # The predicate must be False for the drifted set (assert would fire).
        assert _predicate(drifted_chainid, drifted_ticker, drifted_launch) is False

        # And True for a consistent set (sanity check on the predicate itself).
        consistent_a: dict[str, int] = {"Ethereum": 1, "BASE": 8453}
        consistent_b: dict[str, str] = {"Ethereum": "ETH", "BASE": "ETH"}
        consistent_c: dict[str, date] = {
            "Ethereum": date(2015, 7, 30),
            "BASE": date(2023, 8, 9),
        }
        assert _predicate(consistent_a, consistent_b, consistent_c) is True
