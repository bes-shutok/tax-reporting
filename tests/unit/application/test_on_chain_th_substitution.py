"""Wiring-seam tests for OnChainThSubstituter rpc_client (Task 7, F4+F9).

These two tests pin the wiring seam:

    config key -> OnChainThSubstituter(on_chain_rpc_url=...) -> RpcClient iff set
    -> LpAutodiscovery(rpc_client=...)

They verify that ``maybe_substitute`` builds ``LpAutodiscovery`` with
``rpc_client=None`` when ``on_chain_rpc_url`` is None (the byte-identical
snapshot-only default), and with a non-None ``RpcClient`` when the URL is set
(the F3 wiring-seam test the plan-review flagged as missing).

Approach: monkeypatch the substituter module's ``LpAutodiscovery`` reference
with a capturing fake that records the ``rpc_client`` kwarg and then raises a
sentinel, so the test asserts the wiring WITHOUT running the processor / merge
chain. The sentinel short-circuits ``maybe_substitute`` right at the
``LpAutodiscovery(...)`` construction (the seam under test). A real bera CSV
file is created in ``tmp_path`` so the early ``bera_csv.is_file()`` guard
passes; the committed ``example/`` registry/snapshot paths are injected so no
gitignored personal data is read (AGENTS.md crypto-tests rule).
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from tax_reporting.application.on_chain_th_substitution import OnChainThSubstituter


class _SentinelError(Exception):
    """Raised by the fake LpAutodiscovery to short-circuit maybe_substitute."""


_REPO_ROOT = Path(__file__).resolve().parents[3]
_EXAMPLE_2025_DIR = _REPO_ROOT / "resources" / "source" / "example" / "2025"
_EXAMPLE_CONTRACTS = _EXAMPLE_2025_DIR / "berachain_contracts.json"
_EXAMPLE_SNAPSHOT = _EXAMPLE_2025_DIR / "berachain_lp_snapshot.json"


def _make_bera_csv(output_dir: Path, year: int) -> Path:
    """Create a minimal bera_transactions.csv in ``output_dir`` so the is_file()
    guard passes. ``output_dir`` MUST be a tmp_path (never a real source dir) so
    the audit guard never sees a forbidden personal-data path open.
    """
    bera = output_dir / str(year) / "bera_transactions.csv"
    bera.parent.mkdir(parents=True, exist_ok=True)
    # Minimal header-only CSV; the test short-circuits before the reader runs.
    bera.write_text("wallet_label,tx_hash,timestamp\n", encoding="utf-8")
    return bera


def _run_and_capture_autodiscovery_kwargs(monkeypatch, tmp_path, on_chain_rpc_url):
    """Run maybe_substitute with a capturing fake LpAutodiscovery; return kwargs.

    The bera CSV is created in ``tmp_path`` (not a real source dir) so the
    personal-data audit guard never trips. The committed ``example/`` registry /
    snapshot paths are injected so no gitignored personal data is read.
    """
    import tax_reporting.application.on_chain_th_substitution as mod

    captured: dict = {}

    def _fake_lp_autodiscovery_ctor(*args, **kwargs):
        captured.update(kwargs)
        raise _SentinelError("captured")

    monkeypatch.setattr(mod, "LpAutodiscovery", _fake_lp_autodiscovery_ctor)

    _make_bera_csv(tmp_path, 2025)
    substituter = OnChainThSubstituter(
        contracts_path=_EXAMPLE_CONTRACTS,
        lp_snapshot_path=_EXAMPLE_SNAPSHOT,
        on_chain_rpc_url=on_chain_rpc_url,
    )
    logger = logging.getLogger(__name__)
    with pytest.raises(_SentinelError):
        substituter.maybe_substitute(
            koinly_dir=tmp_path / "koinly",
            output_dir=tmp_path,
            year=2025,
            opted_in_wallets=["bera"],
            logger=logger,
        )
    return captured


@pytest.mark.unit
class TestOnChainThSubstituter:
    """Wiring-seam tests: on_chain_rpc_url -> RpcClient -> LpAutodiscovery."""

    def test_rpc_url_none_yields_snapshot_only_substituter(self, tmp_path, monkeypatch):
        # Given - OnChainThSubstituter(on_chain_rpc_url=None) and a bera CSV in
        # tmp_path so the early is_file() guard passes. A capturing fake
        # LpAutodiscovery short-circuits maybe_substitute right at the seam.
        captured = _run_and_capture_autodiscovery_kwargs(monkeypatch, tmp_path, None)

        # Then - LpAutodiscovery is built with rpc_client=None (the
        # byte-identical snapshot-only default; Koinly characterization stays GREEN).
        assert "rpc_client" in captured
        assert captured["rpc_client"] is None

    def test_rpc_url_set_builds_rpc_client(self, tmp_path, monkeypatch):
        # Given - OnChainThSubstituter(on_chain_rpc_url="https://example.rpc")
        # and a bera CSV in tmp_path so the early is_file() guard passes.
        captured = _run_and_capture_autodiscovery_kwargs(
            monkeypatch, tmp_path, "https://example.rpc"
        )

        # Then - LpAutodiscovery is built with a non-None rpc_client (an
        # RpcClient wired from the configured URL). This is the F3 wiring-seam
        # test the plan-review flagged as missing.
        assert "rpc_client" in captured
        assert captured["rpc_client"] is not None
        # The RpcClient carries the configured URL.
        assert captured["rpc_client"].rpc_url == "https://example.rpc"
