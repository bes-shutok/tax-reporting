"""Wiring-seam tests for OnChainThSubstituter rpc_client (Task 7, F4+F9) and
``build_projection`` extraction pins (validation-harness Task 1).

Wiring-seam tests pin:

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

``build_projection`` tests (validation-harness Task 1) pin that the extracted
pre-merge pipeline is equivalent to the direct collaborator chain, that a
missing bera CSV returns ``None`` + WARNING, and that the optional date window
filters inclusively on both ends. They use a bera CSV under the FULL 15-column
header the reader's ``OnChainTxRow`` contract requires (the 3-column
``_make_bera_csv`` header makes every data row warn-and-skip, so extending
THAT header would yield a vacuous ``[] == []`` pass).
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import pytest

from tax_reporting.application.on_chain_config import load_contracts, load_lp_snapshot
from tax_reporting.application.on_chain_th_adapter import project_on_chain_transactions
from tax_reporting.application.on_chain_th_substitution import OnChainThSubstituter
from tax_reporting.domain.on_chain_transaction import EventType
from tax_reporting.infrastructure.on_chain.berachain_processor import BerachainProcessor
from tax_reporting.infrastructure.on_chain.lp_autodiscovery import LpAutodiscovery
from tax_reporting.infrastructure.on_chain.on_chain_csv_reader import read_on_chain_rows
from tax_reporting.infrastructure.on_chain.position_token_registry import (
    load_position_token_registry,
)


class _SentinelError(Exception):
    """Raised by the fake LpAutodiscovery to short-circuit maybe_substitute."""


_REPO_ROOT = Path(__file__).resolve().parents[3]
_EXAMPLE_2025_DIR = _REPO_ROOT / "resources" / "source" / "example" / "2025"
_EXAMPLE_CONTRACTS = _EXAMPLE_2025_DIR / "berachain_contracts.json"
_EXAMPLE_SNAPSHOT = _EXAMPLE_2025_DIR / "berachain_lp_snapshot.json"
_EXAMPLE_POSITION_TOKENS = _EXAMPLE_2025_DIR / "bera_position_tokens.json"

# Synthetic wallet label + addresses (Design Invariant #1; never real mainnet).
# The reward distributor is registered in the committed example registry, so a
# single in-leg from it classifies as a Reward claim (claim-shaped row).
_WALLET_LABEL = "Ledger Berachain (BERA)"
_BERA_WALLET_ADDR = "0xabcabcabcabcabcabcabcabcabcabcabcabcabca"
_REWARD_DISTRIBUTOR = "0x000000000000000000000000000000000000beef"  # in example registry

# The FULL 15-column header the reader's OnChainTxRow contract requires (same
# shape as the e2e ``_bera_csv_rows`` header; missing columns make the reader
# warn-and-skip every data row).
_BERA_CSV_HEADER = (
    "tx_hash,block_number,timestamp_utc,chain,from_address,to_address,"
    "asset,token_address,amount_raw,amount_decimals,direction,fee_asset,"
    "fee_amount_raw,wallet_label,wallet_address"
)


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


def _claim_row(tx_hash: str, *, block_number: int, timestamp_utc: str) -> str:
    """One claim-shaped CSV data row: a BGT in-leg from the registered example
    reward distributor (single-asset pure inflow -> one Reward Event).
    """
    return (
        f"{tx_hash},{block_number},{timestamp_utc},Berachain,"
        f"{_REWARD_DISTRIBUTOR},{_BERA_WALLET_ADDR},BGT,"
        f"0x000000000000000000000000000000000000b222,"
        f"500000000000000000,18,in,BERA,2100000000000,{_WALLET_LABEL},{_BERA_WALLET_ADDR}"
    )


def _write_bera_csv(output_dir: Path, data_rows: list[str], year: int = 2025) -> Path:
    """Write a bera_transactions.csv under the FULL 15-column header into a
    tmp ``output_dir`` and return its path (audit-guard safe).
    """
    bera = output_dir / str(year) / "bera_transactions.csv"
    bera.parent.mkdir(parents=True, exist_ok=True)
    bera.write_text("\n".join([_BERA_CSV_HEADER, *data_rows, ""]), encoding="utf-8")
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
            position_tokens_path=_EXAMPLE_POSITION_TOKENS,
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
    """Wiring-seam tests: on_chain_rpc_url -> RpcClient -> LpAutodiscovery.

    Plus ``build_projection`` extraction pins (validation-harness Task 1).
    """

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

    def test_build_projection_equivalent_to_direct_collaborator_chain(
        self, tmp_path: Path
    ) -> None:
        """Validation-harness Task 1: ``build_projection`` performs exactly the
        pre-merge pipeline ``maybe_substitute`` ran inline.

        Given a bera CSV with real claim-shaped rows under the FULL 15-column
        header (the reader's ``OnChainTxRow`` contract) and the committed
        ``example/`` registries, ``build_projection().transactions`` must equal
        the direct collaborator chain
        ``processor.process(read_on_chain_rows(csv))`` and
        ``.projected_rows`` must equal ``project_on_chain_transactions(txs)``
        (the audit still runs in between) - pinning that the extraction dropped
        no step. Both sides are asserted NON-EMPTY so a fixture that parses to
        zero rows fails loudly instead of passing vacuously.
        """
        bera_csv = _write_bera_csv(
            tmp_path,
            [
                _claim_row(
                    "0xaaa111", block_number=1000, timestamp_utc="2025-02-25T13:53:25+00:00"
                ),
                _claim_row(
                    "0xbbb222", block_number=1001, timestamp_utc="2025-02-26T10:00:00+00:00"
                ),
            ],
        )
        substituter = OnChainThSubstituter(
            contracts_path=_EXAMPLE_CONTRACTS,
            lp_snapshot_path=_EXAMPLE_SNAPSHOT,
            position_tokens_path=_EXAMPLE_POSITION_TOKENS,
        )

        projection = substituter.build_projection(
            year=2025, output_dir=tmp_path, logger=logging.getLogger(__name__)
        )

        # Direct collaborator chain: the same steps build_projection performs.
        registry = load_contracts(_EXAMPLE_CONTRACTS)
        snapshot = load_lp_snapshot(_EXAMPLE_SNAPSHOT)
        processor = BerachainProcessor(
            chain="Berachain",
            contract_registry=registry,
            lp_autodiscovery=LpAutodiscovery(snapshot=snapshot, rpc_client=None),
        )
        direct_txs = processor.process(read_on_chain_rows(bera_csv))
        direct_projected = project_on_chain_transactions(direct_txs)

        # Non-empty on BOTH sides: a fixture parsing to zero rows must fail
        # loudly (a vacuous [] == [] pass is not a pin).
        assert direct_txs, "fixture must parse to >=1 transaction"
        assert direct_projected, "fixture must project to >=1 TH row"

        assert projection is not None
        assert projection.transactions, "build_projection must produce >=1 transaction"
        assert projection.projected_rows, "build_projection must produce >=1 projected row"
        assert projection.transactions == direct_txs
        assert projection.projected_rows == direct_projected
        # The projection carries the loaded collaborators it classified with.
        assert projection.registry == registry
        assert projection.lp_snapshot == snapshot

    def test_build_projection_routes_position_token_deposit_via_registry(
        self, tmp_path: Path
    ) -> None:
        """Review r1 F4: the position-token registry injection at
        ``_build_processor`` is verifiable through the PRODUCTION wiring.

        Given a bera CSV whose single tx is a pure LST outflow (the token is
        the committed ``example/`` registry's ``kind="lst"`` member), a
        ``build_projection`` run with the example registries injected must
        classify it ``LiquidityDeposit`` (the member-token deposit rule), and
        the direct collaborator chain built WITH the loaded example registry
        must agree. Relevance guard: the same rows through a registry-LESS
        processor stay ``Unknown``, so the assertion is NOT invariant to the
        injection - if the ``_build_processor`` wiring drops the registry,
        this test fails instead of the whole suite staying green
        (development_lessons #48 wiring clause).
        """
        lst_out_row = (
            "0xlstwird,1000,2025-02-25T13:53:25+00:00,Berachain,"
            f"{_BERA_WALLET_ADDR},0x000000000000000000000000000000000000dead,iTEST,"
            "0x0000000000000000000000000000000000000f17,"
            f"1476177230747713290,18,out,BERA,2100000000000,{_WALLET_LABEL},{_BERA_WALLET_ADDR}"
        )
        bera_csv = _write_bera_csv(tmp_path, [lst_out_row])
        substituter = OnChainThSubstituter(
            contracts_path=_EXAMPLE_CONTRACTS,
            lp_snapshot_path=_EXAMPLE_SNAPSHOT,
            position_tokens_path=_EXAMPLE_POSITION_TOKENS,
        )

        projection = substituter.build_projection(
            year=2025, output_dir=tmp_path, logger=logging.getLogger(__name__)
        )

        assert projection is not None
        assert projection.transactions, "fixture must parse to >=1 transaction"
        projection_types = [
            e.event_type for t in projection.transactions for e in t.events
        ]
        assert EventType.LiquidityDeposit in projection_types

        # The direct chain built WITH the loaded registry agrees byte-for-byte.
        position_tokens = load_position_token_registry(_EXAMPLE_POSITION_TOKENS)
        processor_with_registry = BerachainProcessor(
            chain="Berachain",
            contract_registry=load_contracts(_EXAMPLE_CONTRACTS),
            lp_autodiscovery=LpAutodiscovery(
                snapshot=load_lp_snapshot(_EXAMPLE_SNAPSHOT), rpc_client=None
            ),
            position_token_registry=position_tokens,
        )
        assert (
            processor_with_registry.process(read_on_chain_rows(bera_csv))
            == projection.transactions
        )

        # Relevance guard: without the registry the same rows stay Unknown, so
        # the LiquidityDeposit assertion above pins the INJECTION, not the rows.
        processor_without_registry = BerachainProcessor(
            chain="Berachain",
            contract_registry=load_contracts(_EXAMPLE_CONTRACTS),
            lp_autodiscovery=LpAutodiscovery(
                snapshot=load_lp_snapshot(_EXAMPLE_SNAPSHOT), rpc_client=None
            ),
        )
        unregistered_txs = processor_without_registry.process(
            read_on_chain_rows(bera_csv)
        )
        assert [
            e.event_type for t in unregistered_txs for e in t.events
        ] == [EventType.Unknown]

    def test_build_projection_missing_bera_csv_returns_none(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Validation-harness Task 1: absent bera CSV -> ``None`` + WARNING
        (same semantics as today's early return in ``maybe_substitute``).
        """
        (tmp_path / "2025").mkdir(parents=True, exist_ok=True)
        substituter = OnChainThSubstituter(
            contracts_path=_EXAMPLE_CONTRACTS,
            lp_snapshot_path=_EXAMPLE_SNAPSHOT,
            position_tokens_path=_EXAMPLE_POSITION_TOKENS,
        )

        with caplog.at_level(logging.WARNING):
            projection = substituter.build_projection(
                year=2025, output_dir=tmp_path, logger=logging.getLogger(__name__)
            )

        assert projection is None
        assert "No on-chain CSV found" in caplog.text

    def test_build_projection_window_filters_inclusive(self, tmp_path: Path) -> None:
        """Validation-harness Task 1: ``date_from``/``date_to`` filter the RAW
        rows to the inclusive window BEFORE processing.

        Given claim rows on four dates (before ``date_from``, exactly on
        ``date_from``, exactly on ``date_to``, after ``date_to``), a windowed
        ``build_projection`` processes ONLY the two boundary rows (inclusive
        both ends; boundary values tested exactly); with no window args every
        row survives (production default is byte-identical).
        """
        _write_bera_csv(
            tmp_path,
            [
                _claim_row(
                    "0xbefore1", block_number=1000, timestamp_utc="2025-01-10T09:00:00+00:00"
                ),
                _claim_row(
                    "0xfrom000", block_number=1001, timestamp_utc="2025-02-01T12:00:00+00:00"
                ),
                _claim_row(
                    "0xto00000", block_number=1002, timestamp_utc="2025-03-31T23:59:59+00:00"
                ),
                _claim_row(
                    "0xafter01", block_number=1003, timestamp_utc="2025-04-15T08:00:00+00:00"
                ),
            ],
        )
        substituter = OnChainThSubstituter(
            contracts_path=_EXAMPLE_CONTRACTS,
            lp_snapshot_path=_EXAMPLE_SNAPSHOT,
            position_tokens_path=_EXAMPLE_POSITION_TOKENS,
        )
        logger = logging.getLogger(__name__)

        windowed = substituter.build_projection(
            year=2025,
            output_dir=tmp_path,
            logger=logger,
            date_from=date(2025, 2, 1),
            date_to=date(2025, 3, 31),
        )
        assert windowed is not None
        # ONLY the two boundary rows survive; the boundary DATES are tested
        # exactly (inclusive both ends), not just the row count.
        assert {tx.tx_hash for tx in windowed.transactions} == {"0xfrom000", "0xto00000"}
        assert {tx.timestamp_utc.date() for tx in windowed.transactions} == {
            date(2025, 2, 1),
            date(2025, 3, 31),
        }

        # No window args: every row survives (production default).
        unwindowed = substituter.build_projection(
            year=2025, output_dir=tmp_path, logger=logger
        )
        assert unwindowed is not None
        assert {tx.tx_hash for tx in unwindowed.transactions} == {
            "0xbefore1",
            "0xfrom000",
            "0xto00000",
            "0xafter01",
        }
