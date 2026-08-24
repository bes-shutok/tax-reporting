"""On-chain TH path wired behind ``on_chain_th_wallets`` (Plan Task 11).

These e2e tests pin the wiring of the on-chain-native transaction-history
path into ``main.py`` behind the ``on_chain_th_wallets`` flag (Plan Task 11 of
``docs/history/plans/2026-08-02-on-chain-tx-tagger.md``).

The flag
--------

``on_chain_th_wallets`` (config.ini ``[TAX JURISDICTION]
ON_CHAIN_TH_WALLETS``, a comma-separated list of wallet labels) opts one or
more wallets into the on-chain TH path. When the flag lists a wallet AND the
on-chain CSV (``bera_transactions.csv``) is present, the pipeline
(``run_report``) runs:

    read_on_chain_csv -> BerachainProcessor.process -> project_on_chain_transactions
                      -> serialize_projected_rows_to_th_csv
                      -> merge into the Koinly TH fed to the pipeline

The bridge (Plan Task 5 option (a)) serializes the adapter's
``list[ProjectedThRow]`` to a Koinly-TH-shaped CSV (with an ``event_id``
column) written where the pipeline reads TH from, so the existing
``remove_transaction_fees(transaction_history_file=<Path>)`` call picks it up
UNCHANGED. ``read_koinly_rows`` (a ``csv.DictReader``) preserves the
``event_id`` column automatically.

The fail-loud boundary (M1)
---------------------------

The on-chain PARSING/processing path is wrapped in its OWN
``try/except ReportGenerationError``. A parse failure for an opted-in wallet
propagates ``ReportGenerationError`` and is NEVER swallowed by the broad
``except Exception`` that guards the collection-only ``run_on_chain_fetch``
block (the broad except stays ONLY around ``run_on_chain_fetch`` -
collection soft-fail). This is the load-bearing fail-loud guarantee
(``test_opted_in_parse_failure_raises``).

When the flag is UNSET (or empty), today's all-Koinly behavior is preserved
byte-identically (Task 1 characterization stays GREEN).

Per AGENTS.md crypto-tests rule, these tests use ONLY committed synthetic
data (inline CSVs / committed example fixtures); they NEVER reference the
gitignored personal data at ``resources/result/2025/bera_transactions.csv``
or ``resources/source/2025/koinly/``.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from tax_reporting.application.on_chain_th_substitution import (
    OnChainThSubstituter,
    OnChainThSubstitutionResult,
)
from tax_reporting.application.run_report import run_report
from tax_reporting.domain.exceptions import ReportGenerationError

# Repo root (tests/end_to_end/test_on_chain_bera_opted_in.py -> parents[2]).
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_EXAMPLE_SOURCE = _PROJECT_ROOT / "resources" / "source" / "example" / "ib_export.csv"
_EXAMPLE_CONTRACTS = (
    _PROJECT_ROOT / "resources" / "source" / "example" / "2025" / "berachain_contracts.json"
)
_EXAMPLE_LP_SNAPSHOT = (
    _PROJECT_ROOT / "resources" / "source" / "example" / "2025" / "berachain_lp_snapshot.json"
)
_EXAMPLE_POSITION_TOKENS = (
    _PROJECT_ROOT / "resources" / "source" / "example" / "2025" / "bera_position_tokens.json"
)
# The committed example Koinly CG + income reports seed the synthetic koinly_dir
# so the crypto pipeline's 3-file presence guard clears (TH is overwritten by
# the synthetic on-chain-merged TH). Read from the committed example data.
_EXAMPLE_KOINLY_DIR = _PROJECT_ROOT / "resources" / "source" / "example" / "2025" / "koinly"

# Wallet labels used in the synthetic on-chain CSV + the synthetic Koinly TH.
# These are the values matched against ``on_chain_th_wallets``.
_BERA_WALLET_LABEL = "Ledger Berachain (BERA)"
_OTHER_WALLET_LABEL = "ByBit"

# Synthetic on-chain addresses (Design Invariant #1; never real mainnet). The
# BGT Distributor address is the one real trusted constant the design record
# cites (and the example contract registry ships); all others are synthetic.
_BERA_WALLET_ADDR = "0xabcabcabcabcabcabcabcabcabcabcabcabcabca"
_DEX_ROUTER = "0x000000000000000000000000000000000000dead"  # in example registry
_REWARD_DISTRIBUTOR = "0x000000000000000000000000000000000000beef"  # in example registry


def _bera_csv_rows(
    wallet_label: str = _BERA_WALLET_LABEL, *, block_number: int = 1000
) -> str:
    """A synthetic ``bera_transactions.csv`` body (header + 2 txs).

    Two distinct ``tx_hash`` values exercise the adapter's split-Event
    ``event_id`` minting: each tx projects to rows carrying a distinct
    ``event_id`` (``f"{tx_hash}#1"`` etc.). The ``wallet_label`` matches
    ``_BERA_WALLET_LABEL`` so it is matched by ``on_chain_th_wallets=[BERA]``.

    The two txs are simple swaps (1 in-asset <-> 1 out-asset) so the processor
    classifies each as a single Swap Event (the rows still carry distinct
    ``event_id``s per tx, exercising the observable the first test asserts).

    ``wallet_label`` is overridable so review-r1 F2's provenance case-mismatch
    test can seed a bera CSV whose ``wallet_label`` differs in case from the
    configured opted-in value (mirrors the F2 case-insensitive match setup).

    ``block_number`` (Task 2) sets tx1's block; tx2 lands at ``block_number +
    1``. Default ``1000`` keeps every existing test byte-identical. The
    freshness tests override it above the example snapshot's
    ``snapshot_as_of_block`` (1_500_000) to drive the stale-snapshot WARN and
    back to the default for the fresh-snapshot no-WARN case.
    """
    header = (
        "tx_hash,block_number,timestamp_utc,chain,from_address,to_address,"
        "asset,token_address,amount_raw,amount_decimals,direction,fee_asset,"
        "fee_amount_raw,wallet_label,wallet_address"
    )
    # tx1: a swap. In BERA from the DEX router, out HONEY to the DEX router.
    tx1_in = (
        f"0xaaa111,{block_number},2025-02-25T13:53:25+00:00,Berachain,"
        f"{_DEX_ROUTER},{_BERA_WALLET_ADDR},HONEY,0x000000000000000000000000000000000000a111,"
        f"1000000000000000000,18,in,BERA,2100000000000,{wallet_label},{_BERA_WALLET_ADDR}"
    )
    tx1_out = (
        f"0xaaa111,{block_number},2025-02-25T13:53:25+00:00,Berachain,"
        f"{_BERA_WALLET_ADDR},{_DEX_ROUTER},BERA,,2000000000000000000,18,out,BERA,2100000000000,"
        f"{wallet_label},{_BERA_WALLET_ADDR}"
    )
    # tx2: a reward claim from the verified distributor (single-asset Reward).
    tx2_in = (
        f"0xbbb222,{block_number + 1},2025-02-26T10:00:00+00:00,Berachain,"
        f"{_REWARD_DISTRIBUTOR},{_BERA_WALLET_ADDR},BGT,0x000000000000000000000000000000000000b222,"
        f"500000000000000000,18,in,BERA,2100000000000,{wallet_label},{_BERA_WALLET_ADDR}"
    )
    return "\n".join([header, tx1_in, tx1_out, tx2_in, ""])


def _synthetic_koinly_th(beara_rows: bool = True) -> str:
    """A synthetic Koinly TH CSV (preamble + header + 2 rows).

    One row is for the BERA wallet (``_BERA_WALLET_LABEL``), one for a
    non-opted-in wallet (``_OTHER_WALLET_LABEL``). When the BERA wallet is
    opted in, its row must be REPLACED by the on-chain projection; the other
    wallet's row must survive the merge.
    """
    return _synthetic_koinly_th_with_bera_label(
        bera_label=_BERA_WALLET_LABEL, beara_rows=beara_rows
    )


def _synthetic_koinly_th_with_bera_label(
    *, bera_label: str, beara_rows: bool = True
) -> str:
    """A synthetic Koinly TH CSV (preamble + header + 2 rows).

    Like :func:`_synthetic_koinly_th` but lets the caller override the BERA
    wallet row's ``Receiving Wallet`` cell (used by the F2 case-insensitive
    match test, which seeds a TH whose cell is a DIFFERENT case than the
    ``opted_in_wallets`` value to exercise normalized matching). One row is for
    the BERA wallet (``bera_label``), one for a non-opted-in wallet
    (``_OTHER_WALLET_LABEL``).
    """
    header = (
        "Transaction report 2025\n"
        "\n"
        "Date,Type,Tag,Sending Wallet,Sent Amount,Sent Currency,Sent Cost Basis,"
        "Receiving Wallet,Received Amount,Received Currency,Received Cost Basis,"
        "Fee Amount,Fee Currency,Gain (EUR),Net Value (EUR),Fee Value (EUR),"
        "TxSrc,TxDest,TxHash,Description"
    )
    bera_row = (
        "2025-01-10 09:00:00 UTC,crypto_deposit,,ByBit,0,,,"
        f"{bera_label},5,BERA,5,,,5,5,,0xfrom,0xto,0xkoInlybera1,"
    )
    other_row = (
        f"2025-01-11 09:00:00 UTC,crypto_deposit,,ByBit,0,,,"
        f"{_OTHER_WALLET_LABEL},2,ETH,2,,,2,2,,0xfrom2,0xto2,0xkoInlyother1,"
    )
    rows = [header]
    if beara_rows:
        rows.append(bera_row)
    rows.append(other_row)
    return "\n".join(rows) + "\n"


def _seed_koinly_dir(koinly_dir: Path, *, beara_th_rows: bool = True) -> None:
    """Seed a synthetic koinly_dir with the example CG + income reports + a synthetic TH.

    The CG + income reports are copied from the committed example data so the
    crypto pipeline's 3-file presence guard clears; the TH is the synthetic
    on-chain-mergeable TH (``_synthetic_koinly_th``).
    """
    import shutil

    koinly_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(
        _EXAMPLE_KOINLY_DIR / "koinly_2025_capital_gains_report.csv",
        koinly_dir / "koinly_2025_capital_gains_report.csv",
    )
    shutil.copy(
        _EXAMPLE_KOINLY_DIR / "koinly_2025_income_report.csv",
        koinly_dir / "koinly_2025_income_report.csv",
    )
    (koinly_dir / "koinly_2025_transaction_history.csv").write_text(
        _synthetic_koinly_th(beara_rows=beara_th_rows), encoding="utf-8"
    )


def _read_th_data_rows(th_path: Path) -> list[dict[str, str]]:
    """Read a TH CSV's data rows via the production ``read_koinly_rows`` reader.

    Returns the list of dict rows (header detected via the ``Date,`` marker).
    Used to inspect the merged TH after substitution.
    """
    from tax_reporting.infrastructure.koinly_parser import read_koinly_rows

    return read_koinly_rows(th_path)


@pytest.mark.e2e
class TestOnChainBeraOptedIn:
    """Pin the on-chain TH wiring behind ``on_chain_th_wallets`` (Plan Task 11)."""

    def test_opted_in_wallet_uses_onchain_path(self, tmp_path: Path) -> None:
        """Flag on + bera CSV present -> BERA wallet TH rows come from the
        on-chain adapter (distinct ``event_id``s); other wallets stay Koinly.

        Drives ``_maybe_substitute_on_chain_th`` against a synthetic koinly_dir
        + a synthetic ``bera_transactions.csv`` + a synthetic Koinly TH. After
        substitution, the merged TH read by the production reader must:

        - contain the on-chain rows for the BERA wallet, each carrying a
          non-empty ``event_id`` (distinct from any Koinly row);
        - retain the non-opted-in wallet's Koinly row (``_OTHER_WALLET_LABEL``);
        - drop the BERA wallet's original Koinly TH row (replaced by the
          on-chain projection).
        """
        koinly_dir = tmp_path / "koinly"
        koinly_dir.mkdir()
        (koinly_dir / "koinly_2025_transaction_history.csv").write_text(
            _synthetic_koinly_th(beara_rows=True), encoding="utf-8"
        )
        # Also need the CG + income reports so load_koinly_crypto_report could
        # run (not invoked here, but the merged TH must be valid for it).

        bera_csv_dir = tmp_path / "out" / "2025"
        bera_csv_dir.mkdir(parents=True)
        (bera_csv_dir / "bera_transactions.csv").write_text(_bera_csv_rows(), encoding="utf-8")

        logger = logging.getLogger("test_on_chain_bera_optedIn")
        substitution = OnChainThSubstituter(
            contracts_path=_EXAMPLE_CONTRACTS,
            lp_snapshot_path=_EXAMPLE_LP_SNAPSHOT,
            position_tokens_path=_EXAMPLE_POSITION_TOKENS,
        ).maybe_substitute(
            koinly_dir=koinly_dir,
            output_dir=tmp_path / "out",
            year=2025,
            opted_in_wallets=[_BERA_WALLET_LABEL],
            logger=logger,
        )

        # The merged TH now lives at a NON-globbing path (on_chain_merged_th.csv),
        # so re-globbing *transaction_history*.csv no longer finds it. The
        # substitution result carries the explicit merged path (F1/F7).
        assert substitution is not None, "the substitution must return a result when a bera CSV is present"
        assert isinstance(substitution, OnChainThSubstitutionResult)
        merged_th = substitution.merged_th_path
        assert merged_th is not None, "merged_th_path must be set when a bera CSV is present"
        assert merged_th.name == "on_chain_merged_th.csv"
        assert "transaction_history" not in merged_th.name, (
            "F1: the merged path name must NOT match the *transaction_history*.csv discovery glob"
        )
        rows = _read_th_data_rows(merged_th)

        # The BERA wallet's on-chain rows are present and carry distinct event_ids.
        on_chain_bera_rows = [r for r in rows if r.get("Sending Wallet") == _BERA_WALLET_LABEL
                              or r.get("Receiving Wallet") == _BERA_WALLET_LABEL]
        assert on_chain_bera_rows, (
            "the BERA wallet's on-chain TH rows must be present after substitution"
        )
        event_ids = [r.get("event_id", "") for r in on_chain_bera_rows if r.get("event_id")]
        assert event_ids, "on-chain BERA rows must carry non-empty event_ids"
        assert len(set(event_ids)) == len(event_ids), (
            f"on-chain BERA rows must carry DISTINCT event_ids (got {event_ids}); "
            "split Events must not collapse"
        )
        # The on-chain rows carry the real on-chain tx hashes (not the Koinly one).
        hashes = {r.get("TxHash", "") for r in on_chain_bera_rows}
        assert "0xkoInlybera1" not in hashes, (
            "the BERA wallet's Koinly TH row must be REPLACED by the on-chain projection "
            "(its Koinly hash 0xkoInlybera1 must not survive)"
        )

        # The non-opted-in wallet's Koinly row survives the merge.
        other_rows = [r for r in rows if r.get("Receiving Wallet") == _OTHER_WALLET_LABEL]
        assert len(other_rows) == 1, (
            "the non-opted-in wallet's Koinly TH row must survive the merge unchanged"
        )
        assert other_rows[0].get("TxHash") == "0xkoInlyother1"

    def test_non_prefixed_koinly_th_survives_merge(self, tmp_path: Path) -> None:
        """Regression for review F1: when the user's real Koinly TH file is
        named WITHOUT the ``koinly_`` prefix (e.g. a bare
        ``transaction_history.csv``), the non-opted-in wallets' rows must
        still SURVIVE the merge.

        Pre-F1, ``_merge_on_chain_into_koinly_th`` ran
        ``_find_report_path(koinly_dir, "transaction_history", ".csv")`` AFTER
        the on-chain CSV ``on_chain_transaction_history.csv`` had been written
        into ``koinly_dir``. The glob ``*transaction_history*.csv`` matched
        BOTH files and ``sorted()`` returned the alphabetically-first: a bare
        ``transaction_history.csv`` sorts AFTER ``on_chain_...``, so the merge
        read the on-chain file as "Koinly rows" and silently dropped the real
        Koinly data for every non-opted-in wallet.

        Post-F1, the caller pre-resolves the Koinly TH path BEFORE the on-chain
        file exists, so no collision is possible. This test pins that: the
        non-opted-in wallet's row must survive, and the reconciliation
        provenance must record that wallet as Koinly-sourced.
        """
        koinly_dir = tmp_path / "koinly"
        koinly_dir.mkdir()
        # BARE filename (no ``koinly_`` prefix) — the F1 edge case.
        (koinly_dir / "transaction_history.csv").write_text(
            _synthetic_koinly_th(beara_rows=True), encoding="utf-8"
        )

        bera_csv_dir = tmp_path / "out" / "2025"
        bera_csv_dir.mkdir(parents=True)
        (bera_csv_dir / "bera_transactions.csv").write_text(_bera_csv_rows(), encoding="utf-8")

        logger = logging.getLogger("test_on_chain_bera_non_prefixed_th")
        substitution = OnChainThSubstituter(
            contracts_path=_EXAMPLE_CONTRACTS,
            lp_snapshot_path=_EXAMPLE_LP_SNAPSHOT,
            position_tokens_path=_EXAMPLE_POSITION_TOKENS,
        ).maybe_substitute(
            koinly_dir=koinly_dir,
            output_dir=tmp_path / "out",
            year=2025,
            opted_in_wallets=[_BERA_WALLET_LABEL],
            logger=logger,
        )

        # The merged TH lives at the non-globbing on_chain_merged_th.csv (F1/F7);
        # consume the explicit path from the result instead of re-globbing.
        assert substitution is not None
        merged_th = substitution.merged_th_path
        assert merged_th is not None, "merged_th_path must be set when a bera CSV is present"
        rows = _read_th_data_rows(merged_th)
        other_rows = [r for r in rows if r.get("Receiving Wallet") == _OTHER_WALLET_LABEL]
        assert len(other_rows) == 1, (
            "F1 regression: the non-opted-in wallet's Koinly row was dropped "
            "(the bare transaction_history.csv collided with the on-chain file)"
        )
        assert other_rows[0].get("TxHash") == "0xkoInlyother1"

        # The reconciliation provenance must record the non-opted-in wallet as
        # Koinly-sourced with its row count (proves the merge read the REAL
        # Koinly TH, not the on-chain file). Asserts on the provenance table,
        # not a duplicated literal.
        rec = substitution.reconciliation
        assert rec is not None, "the on-chain reconciliation record must be returned"
        provenance = {
            entry.wallet_label: entry for entry in rec.per_wallet_source_provenance
        }
        assert _OTHER_WALLET_LABEL in provenance, (
            "the non-opted-in wallet must appear in the reconciliation provenance "
            "(its Koinly rows survived the merge)"
        )
        assert provenance[_OTHER_WALLET_LABEL].source_kind == "koinly"
        assert provenance[_OTHER_WALLET_LABEL].row_count >= 1

    def test_no_koinly_th_on_chain_rows_become_th(self, tmp_path: Path) -> None:
        """Regression for review F2-r2: with NO pre-existing Koinly TH file at
        all (a pure on-chain run with no Koinly data), the F1 hoist's
        ``koinly_th is None`` branch must still flow the on-chain rows through.

        ``_find_report_path`` returns ``None`` (no ``*transaction_history*.csv``
        present), so ``_merge_on_chain_into_koinly_th`` takes the ``else`` at
        main.py:774 (no Koinly rows to read/drop) and writes the merged TH to
        ``koinly_dir / "on_chain_merged_transaction_history.csv"`` (main.py:828).
        The standalone on-chain CSV is then unlinked (main.py:843-844), so the
        pipeline's re-glob resolves exactly ONE file: the merged TH. This pins
        that the on-chain rows populate the merged TH and that the merged file
        is re-discoverable by the production glob.
        """
        koinly_dir = tmp_path / "koinly"
        koinly_dir.mkdir()
        # NO Koinly TH file (any name) is written here: the None-branch edge.

        bera_csv_dir = tmp_path / "out" / "2025"
        bera_csv_dir.mkdir(parents=True)
        (bera_csv_dir / "bera_transactions.csv").write_text(_bera_csv_rows(), encoding="utf-8")

        logger = logging.getLogger("test_on_chain_no_koinly_th")
        substitution = OnChainThSubstituter(
            contracts_path=_EXAMPLE_CONTRACTS,
            lp_snapshot_path=_EXAMPLE_LP_SNAPSHOT,
            position_tokens_path=_EXAMPLE_POSITION_TOKENS,
        ).maybe_substitute(
            koinly_dir=koinly_dir,
            output_dir=tmp_path / "out",
            year=2025,
            opted_in_wallets=[_BERA_WALLET_LABEL],
            logger=logger,
        )

        # The merged TH now lives at on_chain_merged_th.csv (F1/F7); consume the
        # explicit path instead of re-globbing.
        merged_th = substitution.merged_th_path if substitution is not None else None
        assert merged_th is not None, (
            "F2-r2 regression: with no pre-existing Koinly TH, the merged TH must still be written"
        )
        assert merged_th.name == "on_chain_merged_th.csv", (
            "the merged TH must be written to the non-globbing on_chain_merged_th.csv name"
        )
        rows = _read_th_data_rows(merged_th)
        # The on-chain rows populate the merged TH (no Koinly rows exist).
        on_chain_bera_rows = [
            r for r in rows
            if r.get("Sending Wallet") == _BERA_WALLET_LABEL
            or r.get("Receiving Wallet") == _BERA_WALLET_LABEL
        ]
        assert on_chain_bera_rows, (
            "F2-r2 regression: the on-chain rows must populate the merged TH "
            "when no Koinly TH file exists"
        )
        # The standalone on-chain bridge CSV must have been unlinked so a later
        # run's ``*transaction_history*.csv`` glob cannot collide with a leftover
        # bridge artifact (review r1 F1: the bridge is now written to a
        # NON-globbing name ``on_chain_th_bridge.csv`` and is unlinked in a
        # try/finally so a failed merge cannot orphan it).
        assert not (koinly_dir / "on_chain_th_bridge.csv").exists(), (
            "the standalone on_chain_th_bridge.csv must be unlinked after the merge "
            "so the pipeline re-glob cannot collide with a leftover bridge artifact"
        )
        # The legacy globbing bridge name must NEVER appear on disk (the bridge
        # was renamed to a non-globbing name precisely so a leftover cannot match
        # the ``*transaction_history*.csv`` discovery glob).
        assert not (koinly_dir / "on_chain_transaction_history.csv").exists(), (
            "the legacy globbing bridge name on_chain_transaction_history.csv must "
            "never be written (it matches the *transaction_history*.csv discovery glob)"
        )

    def test_opted_in_parse_failure_raises(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """M1 fail-loud: a parse failure for an opted-in wallet raises
        ``ReportGenerationError``; it is NOT swallowed by the broad
        ``except Exception`` that guards the collection-only fetcher.

        Injects the failure by monkeypatching ``BerachainProcessor.process``
        to raise. Runs ``run_report`` with ``on_chain_th_wallets=[BERA]`` and
        the bera CSV present (so the opted-in parse path is reached). The
        failure must propagate as ``ReportGenerationError`` (the opted-in
        try/except wraps non-ConfigurationError exceptions into
        ReportGenerationError), NOT be silently swallowed.
        """
        from tax_reporting.domain.exceptions import FileProcessingError

        koinly_dir = tmp_path / "koinly"
        _seed_koinly_dir(koinly_dir, beara_th_rows=True)
        bera_csv_dir = tmp_path / "out" / "2025"
        bera_csv_dir.mkdir(parents=True)
        (bera_csv_dir / "bera_transactions.csv").write_text(_bera_csv_rows(), encoding="utf-8")

        # Inject a parse failure in the processor. FileProcessingError is the
        # processor's own failure type (run-level invariant); the opted-in
        # try/except must wrap it into ReportGenerationError (M1 fail-loud).
        def _boom(self, rows):  # type: ignore[no-untyped-def]
            raise FileProcessingError("injected parse failure for opted-in wallet")

        monkeypatch.setattr(
            "tax_reporting.infrastructure.on_chain.berachain_processor.BerachainProcessor.process",
            _boom,
        )

        # Point the contract-registry / LP-snapshot loaders at the committed
        # EXAMPLE files so no gitignored personal config is read.
        monkeypatch.setattr(
            "tax_reporting.application.on_chain_th_substitution._find_repository_root", lambda: _PROJECT_ROOT
        )
        # The helper resolves resources/source/<year>/...; point it at example
        # by overriding the two loader functions to read the example files.
        from tax_reporting.application import on_chain_config as _oc

        def _fake_load_contracts(path):  # type: ignore[no-untyped-def]
            return _oc.load_contracts(_EXAMPLE_CONTRACTS)

        def _fake_load_lp_snapshot(path):  # type: ignore[no-untyped-def]
            return _oc.load_lp_snapshot(_EXAMPLE_LP_SNAPSHOT)

        def _fake_load_position_tokens(path):  # type: ignore[no-untyped-def]
            from tax_reporting.infrastructure.on_chain.position_token_registry import (
                load_position_token_registry,
            )

            return load_position_token_registry(_EXAMPLE_POSITION_TOKENS)

        monkeypatch.setattr(
            "tax_reporting.application.on_chain_th_substitution.load_contracts", _fake_load_contracts
        )
        monkeypatch.setattr(
            "tax_reporting.application.on_chain_th_substitution.load_lp_snapshot", _fake_load_lp_snapshot
        )
        monkeypatch.setattr(
            "tax_reporting.application.on_chain_th_substitution.load_position_token_registry",
            _fake_load_position_tokens,
        )
        # Point ``_main`` at the synthetic koinly_dir (so the on-chain
        # substitution + crypto load read the synthetic TH, not the real
        # example data) and resolve the IB tax-year hint to 2025 (matches the
        # 2025 Koinly dir so the year-mismatch guard does not skip crypto).
        monkeypatch.setattr(
            "tax_reporting.application.run_report._resolve_koinly_directory", lambda *_args, **_kwargs: koinly_dir
        )
        monkeypatch.setattr(
            "tax_reporting.application.run_report._infer_tax_year_hint_from_ib_data", lambda _ib: 2025
        )

        # Build an opted-in PT/2025 jurisdiction.
        from tax_reporting.domain.jurisdiction import TaxJurisdictionConfig
        from tax_reporting.infrastructure.config import Config

        opted_in_config = Config(
            base="EUR",
            rates=[],
            tax_jurisdiction=TaxJurisdictionConfig(
                country="PT",
                fiscal_year=2025,
                exclude_loan_repayment_gains=True,
                zero_basis_review_threshold=Decimal("50"),
                timezone=ZoneInfo("Europe/Lisbon"),
                on_chain_th_wallets=[_BERA_WALLET_LABEL],
            ),
            log_level="WARNING",
        )

        with pytest.raises(ReportGenerationError, match="On-chain TH substitution failed"):
            run_report(
                source_file=_EXAMPLE_SOURCE,
                output_dir=tmp_path / "out",
                app_config=opted_in_config,
                on_chain_fetch=None,
                logger=logging.getLogger("test_opted_in_parse_failure"),
            )

    def test_collection_only_path_still_soft_fails(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Flag UNSET + an injected fetcher failure -> WARNING + report still
        generates (the broad ``except Exception`` is preserved for the
        collection-only path).

        ``on_chain_th_wallets`` is unset (empty list), so the opted-in parse
        path is NOT reached. The ``on_chain_fetch`` callable is INJECTED and
        raises (the injection replaces the former env-gated
        ``run_on_chain_fetch`` binding). The broad ``except Exception``
        around the injected fetch call must swallow it (collection-only
        soft-fail); ``extract.xlsx`` must still generate and NO
        ``ReportGenerationError`` must escape.
        """
        from tax_reporting.domain.exceptions import FileProcessingError
        from tax_reporting.domain.jurisdiction import TaxJurisdictionConfig
        from tax_reporting.infrastructure.config import Config

        # Flag UNSET (default empty list) -> all-Koinly path; the opted-in
        # parse try/except is skipped entirely.
        unset_config = Config(
            base="EUR",
            rates=[],
            tax_jurisdiction=TaxJurisdictionConfig(
                country="PT",
                fiscal_year=2025,
                exclude_loan_repayment_gains=True,
                zero_basis_review_threshold=Decimal("50"),
                timezone=ZoneInfo("Europe/Lisbon"),
            ),
            log_level="WARNING",
        )

        out_dir = tmp_path / "out"
        out_dir.mkdir()
        extract_path = out_dir / "extract.xlsx"

        def _boom_fetch(**kwargs):  # type: ignore[no-untyped-def]
            raise FileProcessingError("injected collection failure")

        logger = logging.getLogger("test_collection_only_soft_fail")
        with caplog.at_level(logging.WARNING, logger="test_collection_only_soft_fail"):
            # Must NOT raise (the broad except swallows the collection failure).
            run_report(
                source_file=_EXAMPLE_SOURCE,
                output_dir=out_dir,
                app_config=unset_config,
                on_chain_fetch=_boom_fetch,
                logger=logger,
            )

        assert extract_path.exists(), (
            "extract.xlsx must still generate despite the collection-only fetch failure"
        )
        assert "Continuing without on-chain transaction data" in caplog.text, (
            "the broad except must log a WARNING and continue (collection-only soft-fail)"
        )
        assert "injected collection failure" in caplog.text, (
            "the soft-fail WARNING must name the fetch failure"
        )

    def test_opted_in_reconciliation_diff(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Flag on + bera CSV present -> the run_report run completes and the
        Crypto Reconciliation sheet exists (high-level signal).

        The ``main()``-level variant of this e2e (driving the composition root
        with the env pinned) lives in
        ``tests/unit/application/test_main_composition_root.py``.

        NOTE: the detailed on-chain delta block (rows reclassified, gas added,
        etc.) is Task 12's reconciliation-sheet schema extension. For THIS
        task we assert the high-level signal (run completes + reconciliation
        sheet exists); the per-field delta assertions land in Task 12.
        """
        import openpyxl

        koinly_dir = tmp_path / "koinly"
        _seed_koinly_dir(koinly_dir, beara_th_rows=True)
        bera_csv_dir = tmp_path / "out" / "2025"
        bera_csv_dir.mkdir(parents=True)
        (bera_csv_dir / "bera_transactions.csv").write_text(_bera_csv_rows(), encoding="utf-8")

        # Point the loaders at the committed EXAMPLE files.
        from tax_reporting.application import on_chain_config as _oc

        def _fake_load_contracts(path):  # type: ignore[no-untyped-def]
            return _oc.load_contracts(_EXAMPLE_CONTRACTS)

        def _fake_load_lp_snapshot(path):  # type: ignore[no-untyped-def]
            return _oc.load_lp_snapshot(_EXAMPLE_LP_SNAPSHOT)

        def _fake_load_position_tokens(path):  # type: ignore[no-untyped-def]
            from tax_reporting.infrastructure.on_chain.position_token_registry import (
                load_position_token_registry,
            )

            return load_position_token_registry(_EXAMPLE_POSITION_TOKENS)

        monkeypatch.setattr(
            "tax_reporting.application.on_chain_th_substitution.load_contracts", _fake_load_contracts
        )
        monkeypatch.setattr(
            "tax_reporting.application.on_chain_th_substitution.load_lp_snapshot", _fake_load_lp_snapshot
        )
        monkeypatch.setattr(
            "tax_reporting.application.on_chain_th_substitution.load_position_token_registry",
            _fake_load_position_tokens,
        )
        monkeypatch.setattr(
            "tax_reporting.application.on_chain_th_substitution._find_repository_root",
            lambda: _PROJECT_ROOT,
        )
        # Point ``run_report`` at the synthetic koinly_dir + a 2025 IB year
        # hint so the on-chain substitution + crypto load read the synthetic TH.
        monkeypatch.setattr(
            "tax_reporting.application.run_report._resolve_koinly_directory", lambda *_args, **_kwargs: koinly_dir
        )
        monkeypatch.setattr(
            "tax_reporting.application.run_report._infer_tax_year_hint_from_ib_data", lambda _ib: 2025
        )

        from tax_reporting.domain.jurisdiction import TaxJurisdictionConfig
        from tax_reporting.infrastructure.config import Config

        opted_in_config = Config(
            base="EUR",
            rates=[],
            tax_jurisdiction=TaxJurisdictionConfig(
                country="PT",
                fiscal_year=2025,
                exclude_loan_repayment_gains=True,
                zero_basis_review_threshold=Decimal("50"),
                timezone=ZoneInfo("Europe/Lisbon"),
                on_chain_th_wallets=[_BERA_WALLET_LABEL],
            ),
            log_level="WARNING",
        )

        out_dir = tmp_path / "out"
        extract_path = out_dir / "extract.xlsx"
        run_report(
            source_file=_EXAMPLE_SOURCE,
            output_dir=out_dir,
            app_config=opted_in_config,
            on_chain_fetch=None,
            logger=logging.getLogger("test_opted_in_reconciliation_diff"),
        )

        assert extract_path.exists(), "the opted-in run must complete and produce extract.xlsx"
        wb = openpyxl.load_workbook(extract_path)
        try:
            # Task 12 extends this sheet with per-wallet source provenance +
            # the on-chain delta block. For Task 11 we only assert it EXISTS;
            # the detailed delta assertions come in Task 12.
            assert "Crypto Reconciliation" in wb.sheetnames, (
                "the Crypto Reconciliation sheet must exist (Task 12 adds the delta block)"
            )
        finally:
            wb.close()

    def test_user_koinly_th_byte_identical_after_substitution(self, tmp_path: Path) -> None:
        """F1 invariant: the user's real Koinly TH is READ-ONLY during substitution.

        Seeds a real Koinly TH at ``koinly_dir/koinly_2025_transaction_history.csv``
        plus a bera CSV for an opted-in wallet, then runs ``maybe_substitute``.
        Asserts:

        - the user's Koinly TH file is BYTE-IDENTICAL (same sha256) before vs
          after substitution (never written/truncated);
        - the merged output lives at ``on_chain_merged_th.csv`` (its name must NOT
          contain ``transaction_history``).
        """
        import hashlib

        koinly_dir = tmp_path / "koinly"
        koinly_dir.mkdir()
        koinly_th = koinly_dir / "koinly_2025_transaction_history.csv"
        koinly_th.write_text(_synthetic_koinly_th(beara_rows=True), encoding="utf-8")
        before_sha = hashlib.sha256(koinly_th.read_bytes()).hexdigest()

        bera_csv_dir = tmp_path / "out" / "2025"
        bera_csv_dir.mkdir(parents=True)
        (bera_csv_dir / "bera_transactions.csv").write_text(_bera_csv_rows(), encoding="utf-8")

        logger = logging.getLogger("test_byte_identical_koinly_th")
        substitution = OnChainThSubstituter(
            contracts_path=_EXAMPLE_CONTRACTS,
            lp_snapshot_path=_EXAMPLE_LP_SNAPSHOT,
            position_tokens_path=_EXAMPLE_POSITION_TOKENS,
        ).maybe_substitute(
            koinly_dir=koinly_dir,
            output_dir=tmp_path / "out",
            year=2025,
            opted_in_wallets=[_BERA_WALLET_LABEL],
            logger=logger,
        )

        # User's Koinly TH is byte-identical (read-only invariant).
        after_sha = hashlib.sha256(koinly_th.read_bytes()).hexdigest()
        assert before_sha == after_sha, (
            "F1 invariant: the user's real Koinly TH must be READ-ONLY (same sha256) "
            f"after substitution; before={before_sha} after={after_sha}"
        )

        # Merged output lives at on_chain_merged_th.csv; name excludes
        # transaction_history so it cannot collide with the discovery glob.
        assert substitution is not None
        merged_th = substitution.merged_th_path
        assert merged_th is not None
        assert merged_th.name == "on_chain_merged_th.csv"
        assert "transaction_history" not in merged_th.name

    def test_merged_th_read_via_override_not_glob(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """F7: ``load_koinly_crypto_report`` reads the merged TH via the explicit
        ``transaction_history_override``, NOT the user's real Koinly TH on disk.

        After substitution for an opted-in wallet, the merged TH (on-chain rows
        present, opted-in Koinly rows gone) is consumed via the explicit
        override path. The user's real Koinly TH remains on disk and must NOT be
        the file the pipeline reads.

        Observables (discriminating): when the override is set, the TH-discovery
        glob ``_find_report_path(..., "transaction_history", ...)`` must NOT be
        invoked (the glob is bypassed), and the merged-TH path must be the file
        opened by the TH reader. ``CryptoTaxReport`` does not surface raw TH
        rows, so the path-level spies are the direct proof; the on-disk read-only
        check confirms the user's real Koinly TH was never overwritten.
        """
        from tax_reporting.application import crypto_reporting as _cr
        from tax_reporting.application.crypto_reporting import load_koinly_crypto_report
        from tax_reporting.domain.jurisdiction import TaxJurisdictionConfig

        koinly_dir = tmp_path / "koinly"
        _seed_koinly_dir(koinly_dir, beara_th_rows=True)
        bera_csv_dir = tmp_path / "out" / "2025"
        bera_csv_dir.mkdir(parents=True)
        (bera_csv_dir / "bera_transactions.csv").write_text(_bera_csv_rows(), encoding="utf-8")

        logger = logging.getLogger("test_override_read")
        substitution = OnChainThSubstituter(
            contracts_path=_EXAMPLE_CONTRACTS,
            lp_snapshot_path=_EXAMPLE_LP_SNAPSHOT,
            position_tokens_path=_EXAMPLE_POSITION_TOKENS,
        ).maybe_substitute(
            koinly_dir=koinly_dir,
            output_dir=tmp_path / "out",
            year=2025,
            opted_in_wallets=[_BERA_WALLET_LABEL],
            logger=logger,
        )
        assert substitution is not None
        merged_th = substitution.merged_th_path
        assert merged_th is not None

        jurisdiction = TaxJurisdictionConfig(
            country="PT",
            fiscal_year=2025,
            exclude_loan_repayment_gains=True,
            zero_basis_review_threshold=Decimal("50"),
            timezone=ZoneInfo("Europe/Lisbon"),
        )

        # Spies: record whether the TH-discovery glob runs, and which TH paths the
        # reader opens. The override must bypass the glob AND read the merged TH.
        th_glob_markers: list[str] = []
        real_find_report_path = _cr._find_report_path

        def _spy_find_report_path(koinly_directory, marker, suffix):  # type: ignore[no-untyped-def]
            if marker == "transaction_history" and suffix == ".csv":
                th_glob_markers.append(marker)
            return real_find_report_path(koinly_directory, marker, suffix)

        monkeypatch.setattr(_cr, "_find_report_path", _spy_find_report_path)

        th_read_paths: list[Path] = []
        real_read_koinly_rows = _cr.read_koinly_rows

        def _spy_read_koinly_rows(path):  # type: ignore[no-untyped-def]
            th_read_paths.append(Path(path))
            return real_read_koinly_rows(path)

        monkeypatch.setattr(_cr, "read_koinly_rows", _spy_read_koinly_rows)

        report = load_koinly_crypto_report(
            koinly_dir,
            jurisdiction=jurisdiction,
            transaction_history_override=merged_th,
        )
        assert report is not None, "the merged TH must be read via the override"

        # The override must bypass the TH-discovery glob entirely.
        assert th_glob_markers == [], (
            "F7: with transaction_history_override set, the *transaction_history*.csv "
            "glob must NOT run; the override path is the source of truth"
        )
        # The merged TH must be the file the reader opened.
        assert any(Path(merged_th) == Path(p) for p in th_read_paths), (
            "F7: the merged TH path must be opened by the TH reader; "
            f"opened paths: {th_read_paths}, expected merged: {merged_th}"
        )
        # The user's real Koinly TH on disk must NOT have been the TH the pipeline
        # read (the override replaced it). Sanity-check that the real on-disk TH
        # still carries the opted-in row (proving read-only) AND that it was not
        # the resolved TH path.
        real_koinly_th = koinly_dir / "koinly_2025_transaction_history.csv"
        assert not any(Path(real_koinly_th) == Path(p) for p in th_read_paths), (
            "F7: the user's real Koinly TH must NOT be read when the override is set"
        )
        on_disk_rows = _read_th_data_rows(real_koinly_th)
        on_disk_hashes = {r.get("TxHash", "") for r in on_disk_rows}
        assert "0xkoInlybera1" in on_disk_hashes, (
            "the user's real Koinly TH must still carry the opted-in row on disk (read-only)"
        )

    def test_two_opted_in_runs_do_not_self_cannibalize(self, tmp_path: Path) -> None:
        """F1 None-branch: two consecutive ``maybe_substitute`` calls on the same
        ``koinly_dir`` with NO real Koinly TH must not self-cannibalize.

        The second run reads ``on_chain_merged_th.csv`` from the FIRST run as its
        on-disk TH (it does not match ``*transaction_history*.csv``, so the
        Koinly glob returns None -> None branch). The second run produces a
        correct merged TH with ``dropped_koinly_rows == 0`` (no self-cannibalization)
        and exactly ONE ``on_chain_merged_th.csv`` exists (overwritten, not duplicated).
        """
        koinly_dir = tmp_path / "koinly"
        koinly_dir.mkdir()
        bera_csv_dir = tmp_path / "out" / "2025"
        bera_csv_dir.mkdir(parents=True)
        (bera_csv_dir / "bera_transactions.csv").write_text(_bera_csv_rows(), encoding="utf-8")

        logger = logging.getLogger("test_two_runs_no_cannibalize")
        substituter = OnChainThSubstituter(
            contracts_path=_EXAMPLE_CONTRACTS,
            lp_snapshot_path=_EXAMPLE_LP_SNAPSHOT,
            position_tokens_path=_EXAMPLE_POSITION_TOKENS,
        )
        # First run (None branch: no Koinly TH on disk).
        first = substituter.maybe_substitute(
            koinly_dir=koinly_dir,
            output_dir=tmp_path / "out",
            year=2025,
            opted_in_wallets=[_BERA_WALLET_LABEL],
            logger=logger,
        )
        assert first is not None
        assert first.merged_th_path is not None

        # Second run on the SAME koinly_dir (no real Koinly TH added).
        second = substituter.maybe_substitute(
            koinly_dir=koinly_dir,
            output_dir=tmp_path / "out",
            year=2025,
            opted_in_wallets=[_BERA_WALLET_LABEL],
            logger=logger,
        )
        assert second is not None
        merged_th = second.merged_th_path
        assert merged_th is not None
        assert merged_th.name == "on_chain_merged_th.csv"

        # Exactly ONE on_chain_merged_th.csv (overwritten, not duplicated).
        merged_files = list(koinly_dir.glob("on_chain_merged_th.csv"))
        assert len(merged_files) == 1, (
            f"expected exactly one on_chain_merged_th.csv, got {len(merged_files)}"
        )

        # No self-cannibalization: the second run produced a correct merged TH
        # (on-chain rows present). dropped_koinly_rows == 0 because the Koinly
        # glob returned None (no real Koinly TH on disk; the merged file from run
        # one does NOT match *transaction_history*.csv).
        rows = _read_th_data_rows(merged_th)
        on_chain_bera_rows = [
            r for r in rows
            if r.get("Sending Wallet") == _BERA_WALLET_LABEL
            or r.get("Receiving Wallet") == _BERA_WALLET_LABEL
        ]
        assert on_chain_bera_rows, (
            "the second run must produce a correct merged TH (on-chain rows present)"
        )
        rec = second.reconciliation
        assert rec is not None
        assert rec.on_chain_delta.rows_reclassified == 0, (
            "no self-cannibalization: the second run must drop 0 Koinly rows "
            "(the on-disk merged TH does not match the *transaction_history*.csv glob)"
        )

    def test_opted_in_label_case_insensitive_match(self, tmp_path: Path) -> None:
        """F2: opted-in label matching is CASE-INSENSITIVE (normalized).

        Given ``opted_in_wallets=["BERA"]`` and a Koinly TH whose BERA wallet
        row's ``Receiving Wallet`` cell is ``bera`` (DIFFERENT case than the
        opted-in value), the BERA wallet's Koinly row MUST be dropped (matched
        case-insensitively via ``casefold``) and the on-chain rows MUST be
        present in the merged TH. Pre-F2 the drop used exact-set membership
        (``sending in opted_set``), so a case mismatch silently left the
        Koinly row in the merged TH alongside the on-chain projection - a
        double-count.
        """
        koinly_dir = tmp_path / "koinly"
        koinly_dir.mkdir()
        # The BERA wallet's Koinly TH row uses a LOWERCASE label "bera"; the
        # opted_in_wallets value below is the UPPERCASE "BERA". Pre-F2 (exact
        # match) this row would NOT be dropped.
        (koinly_dir / "koinly_2025_transaction_history.csv").write_text(
            _synthetic_koinly_th_with_bera_label(bera_label="bera", beara_rows=True),
            encoding="utf-8",
        )

        bera_csv_dir = tmp_path / "out" / "2025"
        bera_csv_dir.mkdir(parents=True)
        (bera_csv_dir / "bera_transactions.csv").write_text(_bera_csv_rows(), encoding="utf-8")

        logger = logging.getLogger("test_opted_in_case_insensitive")
        substitution = OnChainThSubstituter(
            contracts_path=_EXAMPLE_CONTRACTS,
            lp_snapshot_path=_EXAMPLE_LP_SNAPSHOT,
            position_tokens_path=_EXAMPLE_POSITION_TOKENS,
        ).maybe_substitute(
            koinly_dir=koinly_dir,
            output_dir=tmp_path / "out",
            year=2025,
            # UPPERCASE opted-in value; the TH cell is lowercase "bera".
            opted_in_wallets=["BERA"],
            logger=logger,
        )

        assert substitution is not None
        merged_th = substitution.merged_th_path
        assert merged_th is not None
        rows = _read_th_data_rows(merged_th)

        # The lowercase-"bera" Koinly row MUST be dropped (matched
        # case-insensitively). Its Koinly TxHash must NOT survive into the
        # merged TH (otherwise it double-counts alongside the on-chain rows).
        surviving_koinly_bera_hashes = {
            r.get("TxHash", "")
            for r in rows
            if r.get("TxHash") == "0xkoInlybera1"
        }
        assert surviving_koinly_bera_hashes == set(), (
            "F2: the lowercase-'bera' Koinly row must be DROPPED (matched "
            "case-insensitively); its Koinly hash must not survive the merge"
        )

        # The on-chain rows (from the bera CSV, wallet_label = the full
        # _BERA_WALLET_LABEL) MUST be present in the merged TH.
        on_chain_bera_rows = [
            r for r in rows
            if r.get("Sending Wallet") == _BERA_WALLET_LABEL
            or r.get("Receiving Wallet") == _BERA_WALLET_LABEL
        ]
        assert on_chain_bera_rows, (
            "F2: the on-chain rows must be present in the merged TH even when "
            "the opted-in label matched the Koinly row case-insensitively"
        )

        # The non-opted-in wallet's Koinly row still survives (sanity).
        other_rows = [r for r in rows if r.get("Receiving Wallet") == _OTHER_WALLET_LABEL]
        assert len(other_rows) == 1, (
            "the non-opted-in wallet's Koinly row must still survive the merge"
        )

        # The reconciliation delta must record exactly ONE dropped Koinly row
        # (the lowercase-"bera" row); proves the normalized match fed the count.
        rec = substitution.reconciliation
        assert rec is not None
        assert rec.on_chain_delta.rows_reclassified == 1, (
            "F2: the dropped-Koinly count must reflect the case-insensitively "
            "matched row (expected 1)"
        )

    def test_opted_in_provenance_count_matches_under_case_mismatch(self, tmp_path: Path) -> None:
        """Review r1 F2: the reconciliation provenance lookup must use the SAME
        normalization (``normalize_wallet_label``) as the merge drop.

        The merge drops Koinly rows on NORMALIZED labels (case-insensitive), but
        ``_build_on_chain_reconciliation_record`` previously looked up
        ``on_chain_per_wallet`` with the RAW configured label. When the
        configured ``ON_CHAIN_TH_WALLETS`` label differs in case/form from the
        bera CSV ``wallet_label`` (the very case F2 was written to tolerate),
        the opted-in wallet's provenance row reported ``row_count=0`` despite
        being correctly merged.

        Setup mirrors ``test_opted_in_label_case_insensitive_match``: the bera
        CSV ``wallet_label`` is the LOWERCASE form ``ledger berachain (bera)``
        while ``opted_in_wallets`` carries the canonical mixed-case
        ``_BERA_WALLET_LABEL``. The merge drop already tolerates this (F2), so
        the run succeeds; the provenance row must reflect the actual on-chain
        row count (NOT 0).
        """
        koinly_dir = tmp_path / "koinly"
        koinly_dir.mkdir()
        # Koinly TH bera row uses the canonical label so the merge drop matches
        # exactly (this test isolates the PROVENANCE lookup, not the drop).
        (koinly_dir / "koinly_2025_transaction_history.csv").write_text(
            _synthetic_koinly_th(beara_rows=True), encoding="utf-8"
        )

        bera_csv_dir = tmp_path / "out" / "2025"
        bera_csv_dir.mkdir(parents=True)
        # bera CSV wallet_label is the LOWERCASE form; the configured opted-in
        # value below is the canonical mixed-case form. These differ in case but
        # normalize to the same key under ``normalize_wallet_label``.
        (bera_csv_dir / "bera_transactions.csv").write_text(
            _bera_csv_rows(wallet_label="ledger berachain (bera)"), encoding="utf-8"
        )

        logger = logging.getLogger("test_opted_in_provenance_case_mismatch")
        substitution = OnChainThSubstituter(
            contracts_path=_EXAMPLE_CONTRACTS,
            lp_snapshot_path=_EXAMPLE_LP_SNAPSHOT,
            position_tokens_path=_EXAMPLE_POSITION_TOKENS,
        ).maybe_substitute(
            koinly_dir=koinly_dir,
            output_dir=tmp_path / "out",
            year=2025,
            # Canonical mixed-case configured label; the bera CSV cell above is
            # lowercase. Normalization must reconcile them for the provenance
            # lookup just as it already does for the merge drop.
            opted_in_wallets=[_BERA_WALLET_LABEL],
            logger=logger,
        )

        assert substitution is not None
        rec = substitution.reconciliation
        assert rec is not None
        provenance = {
            entry.wallet_label: entry for entry in rec.per_wallet_source_provenance
        }
        # The DISPLAYED wallet_label is the RAW configured label (the user sees
        # what they configured, not a normalized form).
        assert _BERA_WALLET_LABEL in provenance, (
            "the opted-in wallet must appear in the provenance under its RAW "
            "configured label (display keeps the raw label)"
        )
        entry = provenance[_BERA_WALLET_LABEL]
        assert entry.source_kind == "on_chain", (
            "F2: the opted-in wallet must be provenance-tagged on_chain even when "
            "the configured label's case differs from the bera CSV wallet_label"
        )
        assert entry.row_count >= 1, (
            f"F2: the opted-in wallet's on-chain row_count must reflect the merged "
            f"rows (expected >=1), not 0; the provenance lookup must use "
            f"normalize_wallet_label like the merge drop (got {entry.row_count})"
        )

    def test_opted_in_label_not_in_koinly_th_raises(self, tmp_path: Path) -> None:
        """F2 fail-loud: an opted-in label matching NO Koinly TH row raises
        ``ReportGenerationError`` (no silent double-count).

        Given ``opted_in_wallets=["GHOST"]`` and a Koinly TH whose
        ``Sending Wallet``/``Receiving Wallet`` cells contain NO label that
        normalizes to ``ghost``, the merge MUST raise ``ReportGenerationError``
        whose message matches ``"not found in Koinly TH"``. Pre-F2 the merge
        silently dropped zero Koinly rows and appended the on-chain rows,
        leaving the (mismatched) opted-in wallet's Koinly rows in the merged
        TH alongside the on-chain projection - a silent double-count with no
        signal to the user that the configured label matched nothing.
        """
        koinly_dir = tmp_path / "koinly"
        koinly_dir.mkdir()
        # The synthetic TH has only the BERA wallet + the OTHER wallet; neither
        # normalizes to "ghost".
        (koinly_dir / "koinly_2025_transaction_history.csv").write_text(
            _synthetic_koinly_th(beara_rows=True), encoding="utf-8"
        )

        bera_csv_dir = tmp_path / "out" / "2025"
        bera_csv_dir.mkdir(parents=True)
        (bera_csv_dir / "bera_transactions.csv").write_text(_bera_csv_rows(), encoding="utf-8")

        logger = logging.getLogger("test_opted_in_label_not_in_koinly_th")
        substituter = OnChainThSubstituter(
            contracts_path=_EXAMPLE_CONTRACTS,
            lp_snapshot_path=_EXAMPLE_LP_SNAPSHOT,
            position_tokens_path=_EXAMPLE_POSITION_TOKENS,
        )
        with pytest.raises(
            ReportGenerationError, match="not found in Koinly TH"
        ) as excinfo:
            substituter.maybe_substitute(
                koinly_dir=koinly_dir,
                output_dir=tmp_path / "out",
                year=2025,
                # "GHOST" matches no Sending/Receiving wallet in the TH.
                opted_in_wallets=["GHOST"],
                logger=logger,
            )
        assert "ghost" in str(excinfo.value).casefold(), (
            "the fail-loud message must name the unmatched normalized label"
        )

        # Review r1 F1: the F2 fail-loud raise fires mid-merge, AFTER the
        # standalone bridge CSV was serialized into ``koinly_dir``. The bridge
        # must NOT remain on disk after the raise: its name must not match the
        # ``*transaction_history*.csv`` discovery glob (renamed to
        # ``on_chain_th_bridge.csv``) AND a try/finally must unlink it even when
        # the merge raises. Otherwise the NEXT opted-in run's glob could return
        # the leftover bridge as ``koinly_th`` and read on-chain rows as Koinly
        # data (the F7-class collision).
        assert not (koinly_dir / "on_chain_th_bridge.csv").exists(), (
            "F1: the standalone bridge CSV must be cleaned up even when the F2 "
            "fail-loud raise fires mid-merge (try/finally unlink)"
        )
        assert not (koinly_dir / "on_chain_transaction_history.csv").exists(), (
            "F1: the legacy globbing bridge name must never be written"
        )

    def test_stale_snapshot_warns_via_check_freshness(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Task 2: a snapshot whose ``snapshot_as_of_block`` predates the latest
        tx block in the bera CSV triggers a check_freshness WARNING, and the run
        STILL SUCCEEDS (WARN, not fail).

        The example snapshot (``_EXAMPLE_LP_SNAPSHOT``) ships
        ``snapshot_as_of_block`` = 1_500_000. The default ``_bera_csv_rows()``
        hardcodes ``block_number`` 1000/1001 (far below 1_500_000), so to drive
        the stale-snapshot branch this test seeds bera rows whose
        ``block_number`` is ABOVE the snapshot threshold (1_600_000). The
        processor carries each tx's ``block_number`` through, so
        ``maybe_substitute`` must compute ``latest_tx_block = max(...)`` =
        1_600_001 and call ``autodiscovery.check_freshness(1_600_001)`` which
        logs a WARNING naming ``snapshot_as_of_block`` and ``predates``.

        check_freshness is WARN-only (does not raise), so the run must STILL
        complete and produce a valid merged TH (the substitution result is
        returned, not aborted).
        """
        koinly_dir = tmp_path / "koinly"
        koinly_dir.mkdir()
        (koinly_dir / "koinly_2025_transaction_history.csv").write_text(
            _synthetic_koinly_th(beara_rows=True), encoding="utf-8"
        )

        bera_csv_dir = tmp_path / "out" / "2025"
        bera_csv_dir.mkdir(parents=True)
        # block_number 1_600_000 -> tx1 at 1_600_000, tx2 at 1_600_001, both
        # above the snapshot's 1_500_000 threshold -> stale-snapshot branch.
        (bera_csv_dir / "bera_transactions.csv").write_text(
            _bera_csv_rows(block_number=1_600_000), encoding="utf-8"
        )

        logger = logging.getLogger("test_stale_snapshot_warns_via_check_freshness")
        with caplog.at_level(logging.WARNING):
            substitution = OnChainThSubstituter(
                contracts_path=_EXAMPLE_CONTRACTS,
                lp_snapshot_path=_EXAMPLE_LP_SNAPSHOT,
                position_tokens_path=_EXAMPLE_POSITION_TOKENS,
            ).maybe_substitute(
                koinly_dir=koinly_dir,
                output_dir=tmp_path / "out",
                year=2025,
                opted_in_wallets=[_BERA_WALLET_LABEL],
                logger=logger,
            )

        # check_freshness WARNING fired naming both diagnostic tokens.
        freshness_warnings = [
            rec.message
            for rec in caplog.records
            if rec.levelno == logging.WARNING
            and "snapshot_as_of_block" in rec.message
            and "predates" in rec.message
        ]
        assert freshness_warnings, (
            "check_freshness must emit a WARNING naming 'snapshot_as_of_block' "
            "and 'predates' when the snapshot predates the latest tx block; "
            f"got: {[r.message for r in caplog.records]}"
        )

        # WARN, not fail: the run still succeeds and produces a merged TH.
        assert substitution is not None, (
            "check_freshness is WARN-only; the run must NOT abort when the snapshot is stale"
        )
        merged_th = substitution.merged_th_path
        assert merged_th is not None
        rows = _read_th_data_rows(merged_th)
        on_chain_bera_rows = [
            r for r in rows
            if r.get("Sending Wallet") == _BERA_WALLET_LABEL
            or r.get("Receiving Wallet") == _BERA_WALLET_LABEL
        ]
        assert on_chain_bera_rows, (
            "the stale-snapshot WARNING must not prevent the on-chain rows "
            "from populating the merged TH"
        )

    def test_fresh_snapshot_no_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Task 2: a snapshot whose ``snapshot_as_of_block`` >= the latest tx
        block fires NO check_freshness WARNING.

        Uses the default ``_bera_csv_rows()`` (``block_number`` 1000/1001),
        which is BELOW the example snapshot's ``snapshot_as_of_block`` (1_500_000).
        With a fresh snapshot, ``check_freshness`` must NOT log a WARNING (the
        ``snapshot_as_of_block < latest_tx_block`` guard is False), so no
        freshness WARNING appears in the captured records.
        """
        koinly_dir = tmp_path / "koinly"
        koinly_dir.mkdir()
        (koinly_dir / "koinly_2025_transaction_history.csv").write_text(
            _synthetic_koinly_th(beara_rows=True), encoding="utf-8"
        )

        bera_csv_dir = tmp_path / "out" / "2025"
        bera_csv_dir.mkdir(parents=True)
        # Default block_number 1000/1001, below the snapshot's 1_500_000.
        (bera_csv_dir / "bera_transactions.csv").write_text(_bera_csv_rows(), encoding="utf-8")

        logger = logging.getLogger("test_fresh_snapshot_no_warning")
        with caplog.at_level(logging.WARNING):
            substitution = OnChainThSubstituter(
                contracts_path=_EXAMPLE_CONTRACTS,
                lp_snapshot_path=_EXAMPLE_LP_SNAPSHOT,
                position_tokens_path=_EXAMPLE_POSITION_TOKENS,
            ).maybe_substitute(
                koinly_dir=koinly_dir,
                output_dir=tmp_path / "out",
                year=2025,
                opted_in_wallets=[_BERA_WALLET_LABEL],
                logger=logger,
            )

        assert substitution is not None
        # NO freshness WARNING fired (snapshot is fresh relative to txs).
        freshness_warnings = [
            rec.message
            for rec in caplog.records
            if rec.levelno == logging.WARNING
            and "snapshot_as_of_block" in rec.message
            and "predates" in rec.message
        ]
        assert freshness_warnings == [], (
            "check_freshness must NOT emit a WARNING when the snapshot is fresh "
            "(snapshot_as_of_block >= latest tx block); "
            f"got: {freshness_warnings}"
        )

    @pytest.mark.parametrize(
        "scenario",
        ["bridge_write_failure", "finally_unlink_failure"],
    )
    def test_bridge_cleaned_up_on_merge_write_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scenario: str
    ) -> None:
        """Review r2 hardening: write-failure / cleanup-failure robustness.

        Two scenarios drive the two r2 production changes (each is RED today
        and GREEN after the fix):

        - ``bridge_write_failure``: ``Path.open`` raises when opening the BRIDGE
          file (``on_chain_th_bridge.csv``). The opted-in label MATCHES the
          Koinly TH (F2 passes), so the bridge write is reached. Today the
          bridge write lives OUTSIDE the try/finally, so a mid-write raise
          orphans the (partial) bridge on disk -> the ``bridge does NOT exist``
          assertion FAILS. After r2 (bridge write moved INSIDE the try), the
          finally unlinks the partial bridge -> GREEN. Drives the
          ``serialize_projected_rows_to_th_csv`` relocation.

        - ``finally_unlink_failure``: the opted-in label matches NO Koinly TH
          row (F2 raises ``ReportGenerationError`` mid-merge), AND
          ``Path.unlink`` is monkeypatched to raise ``OSError``. The finally's
          unlink runs on the F2 raise path. Today the unlink is UNGUARDED, so
          the unlink ``OSError`` MASKS the original ``ReportGenerationError``
          -> the ``raises ReportGenerationError`` assertion FAILS. After r2
          (unlink wrapped in ``try/except OSError`` with no re-raise), the
          original ``ReportGenerationError`` propagates -> GREEN. Drives the
          OSError guard.

        The merge-write scenario (monkeypatch ``on_chain_merged_th.csv``) is
        NOT parametrized here because the merge write is already inside the
        try/finally today; the bridge is already cleaned on that path (no r2
        change is needed for it). The two scenarios above are the ones that
        actually exercise the r2 hardening.

        Shared invariant: the user's real Koinly TH is NEVER unlinked (the
        ``on_chain_th_csv != koinly_th`` guard stays).
        """
        koinly_dir = tmp_path / "koinly"
        koinly_dir.mkdir()
        koinly_th = koinly_dir / "koinly_2025_transaction_history.csv"
        koinly_th.write_text(_synthetic_koinly_th(beara_rows=True), encoding="utf-8")

        bera_csv_dir = tmp_path / "out" / "2025"
        bera_csv_dir.mkdir(parents=True)
        (bera_csv_dir / "bera_transactions.csv").write_text(_bera_csv_rows(), encoding="utf-8")

        real_unlink = Path.unlink

        if scenario == "bridge_write_failure":
            # Bridge write fails MID-WRITE: the serializer creates the bridge
            # file (so a partial artifact exists on disk) and then raises. This
            # is the faithful simulation of a mid-write raise leaving a partial
            # ``on_chain_th_bridge.csv`` behind. Patching ``Path.open`` alone is
            # insufficient -- an ``open`` failure does not create the file, so
            # there is nothing to orphan; the production change (move the bridge
            # write inside the try) only matters when the file IS created.
            from tax_reporting.application import on_chain_th_substitution as _subst_mod

            real_serialize = _subst_mod.serialize_projected_rows_to_th_csv

            def _partial_serialize(rows, path, *args, **kwargs):  # type: ignore[no-untyped-def]
                # Create the bridge file on disk (simulates a partial write that
                # got far enough to truncate + emit the preamble).
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("Transaction report\n", encoding="utf-8")
                raise OSError("simulated bridge write failure")

            monkeypatch.setattr(
                "tax_reporting.application.on_chain_th_substitution.serialize_projected_rows_to_th_csv",
                _partial_serialize,
            )
            expected_exc_type: type = OSError
            expected_match = "simulated bridge write failure"
            opted_in = [_BERA_WALLET_LABEL]
            _ = real_serialize  # keep the reference for clarity
        else:
            # finally unlink fails: F2 raises ReportGenerationError mid-merge
            # (label "GHOST" matches no Koinly TH row), then the finally's
            # ``.unlink()`` raises OSError. The guard must keep the ORIGINAL
            # ReportGenerationError as the propagating exception.
            def _failing_unlink(self, *args, **kwargs):  # type: ignore[no-untyped-def]
                if self.name == "on_chain_th_bridge.csv":
                    raise OSError("simulated unlink failure")
                return real_unlink(self, *args, **kwargs)

            monkeypatch.setattr(Path, "unlink", _failing_unlink)
            expected_exc_type = ReportGenerationError
            expected_match = "not found in Koinly TH"
            opted_in = ["GHOST"]

        logger = logging.getLogger(f"test_bridge_cleaned_up_on_merge_write_failure[{scenario}]")
        substituter = OnChainThSubstituter(
            contracts_path=_EXAMPLE_CONTRACTS,
            lp_snapshot_path=_EXAMPLE_LP_SNAPSHOT,
            position_tokens_path=_EXAMPLE_POSITION_TOKENS,
        )
        with pytest.raises(expected_exc_type, match=expected_match) as excinfo:
            substituter.maybe_substitute(
                koinly_dir=koinly_dir,
                output_dir=tmp_path / "out",
                year=2025,
                opted_in_wallets=opted_in,
                logger=logger,
            )

        # Guard against the unlink OSError masking the original F2 exception:
        # the propagating exception must be the ORIGINAL (ReportGenerationError
        # for the F2 scenario), not the OSError from the finally cleanup.
        if scenario == "finally_unlink_failure":
            assert not isinstance(excinfo.value, OSError), (
                "r2: the finally-unlink OSError must NOT mask the original "
                "ReportGenerationError (unlink wrapped in try/except OSError)"
            )

        if scenario == "bridge_write_failure":
            # The partial bridge file must NOT remain on disk: the bridge write
            # lives INSIDE the try/finally so the finally unlinks it on the
            # non-F2 raise path. Today (bridge write OUTSIDE the try) the
            # partial bridge is orphaned -> this assertion FAILS (RED).
            assert not (koinly_dir / "on_chain_th_bridge.csv").exists(), (
                "r2: the partial bridge CSV must be cleaned up when the bridge "
                "write raises mid-write (bridge write inside the try/finally)"
            )

        # The user's real Koinly TH must NEVER be unlinked (the
        # ``on_chain_th_csv != koinly_th`` guard stays in both scenarios).
        assert koinly_th.exists(), (
            "r2: the user's real Koinly TH must NOT be unlinked by the finally "
            "(the on_chain_th_csv != koinly_th guard stays)"
        )
