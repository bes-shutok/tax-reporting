"""On-chain TH substitution service (Plan F8).

Extracted verbatim from ``main.py`` (pure move; byte-identical behavior). Owns
the on-chain Transaction-History substitution for opted-in wallets: when the
on-chain CSV (``bera_transactions.csv``) is present for a year, this service
runs the on-chain parse path (CSV reader -> Berachain processor -> adapter),
serializes the projected rows to a TH-shaped CSV (with ``event_id``), and
MERGES them into the Koinly TH fed to the pipeline - replacing the opted-in
wallets' Koinly rows while preserving the non-opted-in wallets' rows.

The merge writes the on-chain projection to ``koinly_dir /
on_chain_merged_th.csv`` (a name that does NOT match the
``*transaction_history*.csv`` discovery glob, so the pipeline reads it via the
explicit ``transaction_history_override`` threaded through
``load_koinly_crypto_report`` instead of re-globbing — review F1/F7). The
user's real Koinly TH is opened READ-ONLY for row-drop counting and is never
written or truncated.

Fail-loud (M1): any failure on this path (CSV read, processor classification,
serialization, Koinly-TH merge) propagates to the caller, which wraps non-
``ConfigurationError`` / ``ReportGenerationError`` exceptions into
``ReportGenerationError``. This path is NOT under the broad ``except Exception``
that guards the collection-only ``run_on_chain_fetch``.

Two reusable seams (validation-harness Task 1, pure extraction):
:meth:`OnChainThSubstituter.build_projection` exposes the pre-merge pipeline
(reader -> processor -> audit -> adapter projection) with an optional inclusive
date window, and :func:`is_wallet_row` exposes the merge's wallet-row match
idiom, so downstream consumers (the TH validation harness) reuse EXACTLY the
production path instead of growing a parallel one.
"""

from __future__ import annotations

import csv
import logging
import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from ..domain.exceptions import ReportGenerationError
from ..domain.on_chain_config import ContractRegistry, LpSnapshot
from ..domain.on_chain_transaction import EventType, OnChainTransaction
from ..infrastructure.koinly_parser import _find_report_path, read_koinly_rows
from ..infrastructure.on_chain.berachain_processor import BerachainProcessor
from ..infrastructure.on_chain.integrity_invariants import check_on_chain_integrity
from ..infrastructure.on_chain.lp_autodiscovery import LpAutodiscovery
from ..infrastructure.on_chain.on_chain_csv_reader import read_on_chain_rows
from ..infrastructure.on_chain.position_token_registry import (
    PositionTokenRegistry,
    load_position_token_registry,
)
from ..infrastructure.on_chain.rpc_client import RpcClient
from .crypto.classification import _find_repository_root
from .crypto.entities import (
    OnChainDeltaBlock,
    OnChainReconciliationRecord,
    WalletSourceProvenance,
)
from .on_chain_config import (
    load_contracts,
    load_lp_snapshot,
)
from .on_chain_fetcher import bera_csv_path
from .on_chain_th_adapter import (
    TH_CSV_COLUMNS,
    ProjectedThRow,
    project_on_chain_transactions,
    serialize_projected_rows_to_th_csv,
)


def normalize_wallet_label(s: str) -> str:
    """Normalize a wallet label for case-insensitive matching (Plan F2).

    Strips surrounding whitespace, casefolds (a strict superset of lowercase
    for printable ASCII, so an exact match today still matches after
    normalization), and drops non-printable characters (control chars that
    could otherwise sneak past a bare ``.lower()`` comparison). Public
    (review r2 F7): the CLI validation path in :mod:`tax_reporting.main`
    imports this same normalization instead of reaching for a private
    helper; the reconciliation provenance keeps the RAW label (the user sees
    raw labels in the sheet).
    """
    return "".join(ch for ch in s.strip().casefold() if ch.isprintable())


def matched_wallet_labels(row: dict[str, str], labels: set[str]) -> set[str]:
    """Return which of ``labels`` the Koinly TH ``row``'s wallet cells match.

    Matches the row's ``Sending Wallet`` / ``Receiving Wallet`` cells against
    ``labels`` with the same ``normalize_wallet_label`` semantics the merge drop uses
    (strip + casefold + printable-only). Returns the SUBSET of ``labels``
    actually matched (empty set = no match), so callers that need the matched
    labels (the merge loop's fail-loud no-match check) reuse this single
    normalization instead of re-normalizing the same cells again (review
    r1 F20: four parallel copies of the same normalization can drift apart).

    Args:
        row: A Koinly TH row dict (as returned by ``read_koinly_rows``).
        labels: Wallet labels ALREADY normalized via ``normalize_wallet_label`` (and with
            empty entries filtered out). Pre-normalizing at the caller keeps
            an empty configured label from matching a row whose wallet cells
            are empty (``normalize_wallet_label("") == ""`` would otherwise be a member).

    Returns:
        The set of matched normalized labels (possibly empty).
    """
    sending_n = normalize_wallet_label((row.get("Sending Wallet") or "").strip())
    receiving_n = normalize_wallet_label((row.get("Receiving Wallet") or "").strip())
    return {label for label in (sending_n, receiving_n) if label in labels}


def is_wallet_row(row: dict[str, str], labels: set[str]) -> bool:
    """Return whether a Koinly TH ``row`` belongs to one of ``labels``.

    Thin boolean wrapper over :func:`matched_wallet_labels` (the merge's
    drop decision and the TH validation harness's row filter share ONE
    matching idiom - no parallel matching path can drift).
    """
    return bool(matched_wallet_labels(row, labels))


@dataclass
class OnChainMergeStats:
    """Merge stats returned by ``_merge_on_chain_into_koinly_th`` (Plan Task 12).

    Carries the per-wallet surviving-Koinly row counts (one entry per
    non-opted-in wallet that contributed Koinly TH rows) and the count of
    Koinly rows dropped (replaced by the on-chain projection). Consumed by
    ``maybe_substitute`` to assemble the reconciliation record.
    """

    koinly_per_wallet: dict[str, int] = field(default_factory=dict)
    dropped_koinly_rows: int = 0


@dataclass
class OnChainThSubstitutionResult:
    """Result of :meth:`OnChainThSubstituter.maybe_substitute` (Plan F1/F7).

    Carries the on-chain reconciliation record (per-wallet provenance + delta
    block; ``None`` only when the bera CSV is absent) and the explicit merged-TH
    path. The merged TH lives at ``on_chain_merged_th.csv`` (a NON-globbing
    name; ``*transaction_history*.csv`` does not match it), so the pipeline
    reads it via the explicit ``transaction_history_override`` threaded through
    ``load_koinly_crypto_report`` instead of re-globbing ``koinly_dir``.

    Attributes:
        reconciliation: The ``OnChainReconciliationRecord`` (per-wallet source
            provenance + Koinly-vs-on-chain delta block), or ``None`` when the
            bera CSV was absent (flag set but no on-chain data collected; the
            Koinly TH is left untouched).
        merged_th_path: Path to ``on_chain_merged_th.csv``, or ``None`` when the
            bera CSV was absent (no merge performed).
    """

    reconciliation: OnChainReconciliationRecord | None
    merged_th_path: Path | None


@dataclass
class OnChainProjection:
    """Result of :meth:`OnChainThSubstituter.build_projection` (validation-harness Task 1).

    Carries the FULL pre-merge pipeline output - the processed on-chain
    transactions, the adapter's TH projection, and the loaded registry /
    LP-snapshot collaborators - so downstream consumers (the TH substitution
    merge and the TH validation harness) see exactly what the production path
    produces.

    Attributes:
        transactions: The processor's ``OnChainTransaction`` list (one per
            ``tx_hash``; post-classification, post-audit).
        projected_rows: The adapter's ``ProjectedThRow`` list (one per Event).
        registry: The per-year contract registry that drove classification.
        lp_snapshot: The per-year LP-token snapshot used for LP classification.
    """

    transactions: list[OnChainTransaction]
    projected_rows: list[ProjectedThRow]
    registry: ContractRegistry
    lp_snapshot: LpSnapshot


# Upper bound on the sample-hashes list rendered in the delta block (keeps the
# cell readable; the full hash set lives in the merged TH for drill-down).
_DELTA_SAMPLE_HASH_CAP = 10

#: The Koinly TH discovery glob marker + suffix (the ONE definition shared by
#: the substituter's merge-side lookup and the validation runner's baseline
#: lookup - review r1 F17: twin inline literals can drift apart silently).
TH_MARKER = "transaction_history"
TH_SUFFIX = ".csv"


def in_window_inclusive(day: date, date_from: date | None, date_to: date | None) -> bool:
    """Inclusive window check (both bounds participate when set).

    The ONE shared predicate for BOTH sides of the TH validation (the raw-row
    filter in :meth:`OnChainThSubstituter.build_projection` and the runner's
    Koinly-baseline filter - review r1 F17): the two sides must see the same
    window or the hash partitions diverge, so the equality is enforced by
    sharing the code, not by parallel literals.
    """
    if date_from is not None and day < date_from:
        return False
    return date_to is None or day <= date_to


class OnChainThSubstituter:
    """Substitute on-chain TH rows for opted-in wallets (Plan Task 11, bridge (a)).

    The pre-merge pipeline (reader -> processor -> audit -> adapter projection)
    is exposed as :meth:`build_projection` so the TH validation harness reuses
    the EXACT production path (validation-harness Task 1, pure extraction);
    :meth:`maybe_substitute` is that projection plus the Koinly-TH merge /
    reconciliation tail.

    When the on-chain CSV (``bera_transactions.csv``) is present for ``year``,
    :meth:`maybe_substitute` runs the on-chain parse path (CSV reader ->
    Berachain processor -> adapter) and writes a MERGED Transaction-History CSV
    into ``koinly_dir``: the Koinly TH rows for NON-opted-in wallets are
    preserved, and the on-chain projected rows REPLACE the opted-in wallets'
    Koinly rows. The merged CSV is written to ``koinly_dir /
    on_chain_merged_th.csv`` (a name that does NOT match the
    ``*transaction_history*.csv`` discovery glob), so the pipeline reads it via
    the explicit ``transaction_history_override`` threaded through
    ``load_koinly_crypto_report`` (review F1/F7). The user's real Koinly TH is
    never written or truncated (read-only).

    Fail-loud (M1): any failure on this path (CSV read, processor
    classification, serialization, Koinly-TH merge) propagates to the caller,
    which wraps non-ConfigurationError/ReportGenerationError exceptions into
    ``ReportGenerationError``. This path is NOT under the broad
    ``except Exception`` that guards the collection-only
    ``run_on_chain_fetch``.

    Args:
        contracts_path: Optional explicit path to ``berachain_contracts.json``.
            Tests inject the committed ``example/`` path so they never read
            gitignored personal data (AGENTS.md crypto-tests rule). ``None``
            (production) resolves via :meth:`_resolve_registry_path` with an
            ``example/`` fallback for fresh clones.
        lp_snapshot_path: Optional explicit path to ``berachain_lp_snapshot.json``
            (same resolution contract as ``contracts_path``).
        on_chain_rpc_url: Optional Berachain JSON-RPC endpoint
            (``ON_CHAIN_RPC_URL`` from ``[TAX JURISDICTION]``). When set,
            :meth:`maybe_substitute` builds an :class:`RpcClient` and passes it
            to :class:`LpAutodiscovery` so LP tokens NOT in the snapshot are
            auto-classified via bytecode fingerprinting (F4+F9). When ``None``
            (the default / flag unset), ``rpc_client=None`` and LP
            classification is snapshot-only (byte-identical to the pre-RPC
            behavior; Koinly characterization stays GREEN).
    """

    def __init__(
        self,
        *,
        contracts_path: Path | None = None,
        lp_snapshot_path: Path | None = None,
        position_tokens_path: Path | None = None,
        on_chain_rpc_url: str | None = None,
    ) -> None:
        """Initialize the substituter with optional test-injected registry paths."""
        self._contracts_path = contracts_path
        self._lp_snapshot_path = lp_snapshot_path
        self._position_tokens_path = position_tokens_path
        self._on_chain_rpc_url = on_chain_rpc_url

    def maybe_substitute(  # noqa: PLR0913
        self,
        *,
        koinly_dir: Path,
        output_dir: Path,
        year: int,
        opted_in_wallets: list[str],
        logger: logging.Logger,
    ) -> OnChainThSubstitutionResult:
        """Run the on-chain TH substitution for opted-in wallets.

        Returns:
            ``OnChainThSubstitutionResult`` carrying the on-chain reconciliation
            record (per-wallet source provenance + Koinly-vs-on-chain delta
            block; Plan Task 12) and the explicit merged-TH path
            (``on_chain_merged_th.csv``). When the bera CSV is absent (the
            opted-in flag is set but no on-chain data was collected), both fields
            are ``None``: the Koinly TH is left untouched and the run continues
            with Koinly data (the new reconciliation fields stay at their
            defaults so the sheet is byte-identical to the Koinly-only path).

        Args:
            koinly_dir: The Koinly directory the crypto pipeline will read from.
                The merged TH CSV is written here.
            output_dir: Base output directory; the bera CSV is read from
                the fetcher's ``bera_csv_path(output_dir, year)``.
            year: The fiscal year (selects the bera CSV subdirectory and the
                per-year contract registry / LP snapshot).
            opted_in_wallets: Wallet labels opting into the on-chain TH path
                (matched against the Koinly TH ``Sending Wallet`` /
                ``Receiving Wallet`` columns and the bera CSV ``wallet_label``).
            logger: Logger for diagnostics.
        """
        projection = self.build_projection(year=year, output_dir=output_dir, logger=logger)
        if projection is None:
            return OnChainThSubstitutionResult(reconciliation=None, merged_th_path=None)

        logger.info(
            "ON_CHAIN_TH_WALLETS=%s opted in; substituting on-chain TH from %s.",
            opted_in_wallets,
            bera_csv_path(output_dir, year),
        )
        txs = projection.transactions
        projected = projection.projected_rows

        koinly_th = _find_report_path(koinly_dir, TH_MARKER, TH_SUFFIX)
        merge_stats, merged_th_path = self._serialize_and_merge(
            projected=projected,
            koinly_dir=koinly_dir,
            koinly_th=koinly_th,
            opted_in_wallets=opted_in_wallets,
            logger=logger,
        )
        reconciliation = self._build_on_chain_reconciliation_record(
            txs=txs,
            projected=projected,
            opted_in_wallets=opted_in_wallets,
            merge_stats=merge_stats,
        )
        return OnChainThSubstitutionResult(
            reconciliation=reconciliation,
            merged_th_path=merged_th_path,
        )

    def build_projection(
        self,
        *,
        year: int,
        output_dir: Path,
        logger: logging.Logger,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> OnChainProjection | None:
        """Build the on-chain projection (reader -> processor -> audit -> adapter).

        Extracted verbatim from ``maybe_substitute``'s pre-merge pipeline
        (validation-harness Task 1; pure refactor - ``maybe_substitute`` calls
        this with no window so the production path is byte-identical). Performs
        exactly the original steps: bera-CSV presence check (absent -> WARNING
        + ``None``), repository-root resolution, registry + snapshot load,
        processor build, CSV read, classification, integrity/freshness audit,
        adapter projection.

        The ONE addition: when ``date_from``/``date_to`` is set, the RAW rows
        are filtered to the inclusive date window (comparing the reader's
        already-parsed ``OnChainTxRow.timestamp_utc.date()``) BEFORE
        ``processor.process``, so the processor, the integrity checks, and the
        projection never see out-of-window transactions.

        Fail-loud (M1): any failure on this path propagates to the caller
        (same contract as ``maybe_substitute``).

        Args:
            year: The fiscal year (selects the bera CSV subdirectory and the
                per-year contract registry / LP snapshot).
            output_dir: Base output directory; the bera CSV is read from
                the fetcher's ``bera_csv_path(output_dir, year)``.
            logger: Logger for diagnostics.
            date_from: Optional inclusive window start; rows whose
                ``timestamp_utc.date()`` is EARLIER are dropped before
                processing. ``None`` (production default) keeps every row.
            date_to: Optional inclusive window end; rows whose
                ``timestamp_utc.date()`` is LATER are dropped before
                processing. ``None`` (production default) keeps every row.

        Returns:
            ``OnChainProjection`` with the processed transactions, the
            projected TH rows, and the loaded registry + LP snapshot; or
            ``None`` when the bera CSV is absent (WARNING logged).
        """
        bera_csv = bera_csv_path(output_dir, year)
        if not bera_csv.is_file():
            logger.warning(
                "No on-chain CSV found at %s; no on-chain TH projection was built.",
                bera_csv,
            )
            return None

        logger.info("Building on-chain TH projection from %s.", bera_csv)

        # --- Pipeline (review F10: each stage was inline; now extracted helpers) ---
        repo_root = _find_repository_root()
        registry, snapshot, position_tokens = self._load_registries(year, repo_root, logger)
        processor, autodiscovery = self._build_processor(
            registry, snapshot, position_tokens
        )
        on_chain_rows = read_on_chain_rows(bera_csv)
        if date_from is not None or date_to is not None:
            # Inclusive window on the reader's parsed UTC date; applied to the
            # RAW rows so the processor/audit/projection never see out-of-window
            # transactions (validation-harness Task 1). Production passes no
            # window, so this filter never runs on the substituter path. The
            # SHARED predicate (review r1 F17): the runner's Koinly-side filter
            # uses the same function, so the two sides cannot drift.
            on_chain_rows = [
                row for row in on_chain_rows if in_window_inclusive(row.timestamp_utc.date(), date_from, date_to)
            ]
        txs = processor.process(on_chain_rows)
        self._audit(txs=txs, registry=registry, autodiscovery=autodiscovery)
        projected = project_on_chain_transactions(txs)
        logger.info(
            "On-chain TH path: %d CSV row(s) -> %d tx(s) -> %d projected TH row(s).",
            len(on_chain_rows),
            len(txs),
            len(projected),
        )
        return OnChainProjection(
            transactions=txs,
            projected_rows=projected,
            registry=registry,
            lp_snapshot=snapshot,
        )

    def _load_registries(
        self,
        year: int,
        repo_root: Path,
        logger: logging.Logger,
    ) -> tuple[ContractRegistry, LpSnapshot, PositionTokenRegistry]:
        """Resolve + load the per-year contract registry, LP snapshot, and position-token registry.

        Production resolves these from ``resources/source/<year>/`` (the per-user
        override dir); when absent (a fresh clone has no personal data there - it
        is gitignored), it falls back to the committed
        ``resources/source/example/<year>/`` templates so the opted-in path works
        out of the box. Tests inject the ``example/`` paths explicitly via the
        ctor kwargs so they never read gitignored personal data (AGENTS.md
        crypto-tests rule) even when it exists on disk. The loaders raise
        ConfigurationError / FileProcessingError on schema/IO failure (fail-loud).
        """
        registry = load_contracts(
            self._resolve_registry_path(
                year, "berachain_contracts.json", self._contracts_path, repo_root, logger
            )
        )
        snapshot = load_lp_snapshot(
            self._resolve_registry_path(
                year, "berachain_lp_snapshot.json", self._lp_snapshot_path, repo_root, logger
            )
        )
        # Position-token registry (plan 2026-08-22 Task 3): same resolution
        # contract, but the loader DEGRADES to an empty registry + WARNING
        # when the file is absent (LST outflows then classify Unknown +
        # review; a fresh clone without the personal registry must not
        # abort the opted-in path).
        position_tokens = load_position_token_registry(
            self._resolve_registry_path(
                year,
                "bera_position_tokens.json",
                self._position_tokens_path,
                repo_root,
                logger,
            )
        )
        return registry, snapshot, position_tokens

    def _build_processor(
        self,
        registry: ContractRegistry,
        snapshot: LpSnapshot,
        position_tokens: PositionTokenRegistry,
    ) -> tuple[BerachainProcessor, LpAutodiscovery]:
        """Wire the RPC client + LP autodiscovery + Berachain processor.

        F4+F9 wiring seam: build an RpcClient iff an RPC URL was configured
        (``ON_CHAIN_RPC_URL`` -> ``OnChainThSubstituter(on_chain_rpc_url=...)``
        -> here). When ``on_chain_rpc_url`` is None (the default / flag unset),
        ``rpc_client`` stays None and LP classification is snapshot-only
        (byte-identical to the pre-RPC behavior; Koinly characterization stays
        GREEN). When set, ``LpAutodiscovery`` uses it for the V2-pair
        bytecode / KodiakIsland implementation() fingerprint fallback so new LP
        pools not in the snapshot are auto-classified instead of falling to
        Unknown + review.

        Returns both the processor and the autodiscovery collaborator so the
        caller can thread ``autodiscovery`` to :meth:`_audit` (freshness check)
        without instance-attr coupling.
        """
        rpc_client = (
            RpcClient(rpc_url=self._on_chain_rpc_url)
            if self._on_chain_rpc_url
            else None
        )
        autodiscovery = LpAutodiscovery(snapshot=snapshot, rpc_client=rpc_client)
        processor = BerachainProcessor(
            chain="Berachain",
            contract_registry=registry,
            lp_autodiscovery=autodiscovery,
            position_token_registry=position_tokens,
        )
        return processor, autodiscovery

    def _audit(
        self,
        *,
        txs: list[OnChainTransaction],
        registry: ContractRegistry,
        autodiscovery: LpAutodiscovery,
    ) -> None:
        """Run post-classification integrity (fail-loud) + freshness (WARN-only).

        Plan Task 13 (MO2): a pure post-run audit of the processor output + the
        loaded registry. WARN findings are logged inside the checker; FAIL
        findings raise FileProcessingError (fail-loud: data corruption --
        decimal-out-of-range legs or an invalid operator_country would misroute
        downstream EUR/origin resolution).

        Task 2 (M2) freshness WARN: compare the snapshot's
        ``snapshot_as_of_block`` against the latest observed tx block. A snapshot
        predating the latest tx means recent LP pools may be missing from the
        allowlist; ``check_freshness`` logs a WARNING naming both blocks so the
        user can refresh the snapshot. WARN-only (does NOT raise); placed AFTER
        the fail-loud integrity check so a stale snapshot NEVER aborts the run.
        Empty-txs guard: ``max()`` on an empty sequence raises ValueError, so
        skip when the processor produced no txs (the example/empty-CSV edge).
        """
        integrity_report = check_on_chain_integrity(
            transactions=txs, registry=registry
        )
        integrity_report.raise_if_failed()
        if txs:
            latest_tx_block = max(t.block_number for t in txs)
            autodiscovery.check_freshness(latest_tx_block)

    def _serialize_and_merge(
        self,
        *,
        projected: list[ProjectedThRow],
        koinly_dir: Path,
        koinly_th: Path | None,
        opted_in_wallets: list[str],
        logger: logging.Logger,
    ) -> tuple[OnChainMergeStats, Path]:
        """Serialize projected rows to the bridge CSV, merge into Koinly TH, cleanup.

        The bridge filename is ``on_chain_th_bridge.csv`` -- a name that does NOT
        contain ``transaction_history``, so even if a failed run orphans it on
        disk it CANNOT match the ``*transaction_history*.csv`` discovery glob and
        poison the next opted-in run's Koinly-TH resolution (review r1 F1; the
        legacy name ``on_chain_transaction_history.csv`` matched the glob and was
        the F7-class collision hazard when the F2 fail-loud raise left it behind
        mid-merge).

        Merge: the existing Koinly TH (``koinly_th``) is opened READ-ONLY; rows
        whose Sending or Receiving wallet matches an opted-in label are dropped
        (replaced by the on-chain projection). The merged CSV is ALWAYS written
        to ``koinly_dir / "on_chain_merged_th.csv"`` (a non-globbing name;
        F1/F7), so the pipeline reads it via the explicit
        ``transaction_history_override`` instead of re-globbing.

        Review r1 F1 (try/finally): the F2 fail-loud raise (or any merge
        exception) fires AFTER the bridge CSV was serialized into
        ``koinly_dir``. The success-path unlink inside the merge does NOT run on
        raise, so without this try/finally the bridge would be orphaned. The
        finally unlinks the bridge whether the merge succeeded (the merge's own
        unlink already removed it; the ``if exists`` guard is a no-op) or raised
        (the finally is the only cleanup). Combined with the non-globbing name,
        a leftover bridge can neither remain on disk nor match the glob.

        Review r2 hardening: the bridge WRITE
        (``serialize_projected_rows_to_th_csv``) is INSIDE this try. A mid-write
        raise (e.g. disk full mid-flush) leaves a PARTIAL bridge file on disk;
        the finally unlinks it so it cannot be orphaned. Pre-r2 the write lived
        OUTSIDE the try, so a mid-write raise orphaned the partial bridge.
        """
        on_chain_th_csv = koinly_dir / "on_chain_th_bridge.csv"
        try:
            serialize_projected_rows_to_th_csv(projected, on_chain_th_csv)
            merge_stats, merged_th_path = self._merge_on_chain_into_koinly_th(
                koinly_dir=koinly_dir,
                koinly_th=koinly_th,
                on_chain_th_csv=on_chain_th_csv,
                opted_in_wallets=opted_in_wallets,
                logger=logger,
            )
        finally:
            # Review r2 hardening: wrap the cleanup unlink in its own
            # ``try/except OSError`` that logs a WARNING and does NOT re-raise.
            # An unlink failure (e.g. a read-only ``koinly_dir``) must NOT mask
            # the original exception (the F2 ``ReportGenerationError`` or a
            # bridge/merge write ``OSError``). Python's finally semantics: when
            # the finally body does not raise, the original exception propagates
            # unchanged; swallowing the unlink OSError here preserves that.
            #
            # Guard scope (unchanged from r1): the ``on_chain_th_csv !=
            # koinly_th`` check stays, so the user's real Koinly TH is NEVER
            # unlinked here. The merged file is NEVER unlinked here either:
            # ``on_chain_th_csv`` is ``on_chain_th_bridge.csv`` and the merged
            # file is ``on_chain_merged_th.csv`` (distinct names by construction),
            # so this branch only ever targets the transient bridge artifact.
            if on_chain_th_csv.exists() and on_chain_th_csv != koinly_th:
                try:
                    on_chain_th_csv.unlink()
                except OSError as unlink_exc:
                    logger.warning(
                        "On-chain TH bridge cleanup: failed to unlink %s: %s. "
                        "The original exception (if any) is preserved; the "
                        "leftover bridge uses a non-globbing name so it cannot "
                        "poison the next run's Koinly-TH glob.",
                        on_chain_th_csv,
                        unlink_exc,
                    )
        return merge_stats, merged_th_path

    def _merge_on_chain_into_koinly_th(
        self,
        *,
        koinly_dir: Path,
        koinly_th: Path | None,
        on_chain_th_csv: Path,
        opted_in_wallets: list[str],
        logger: logging.Logger,
    ) -> tuple[OnChainMergeStats, Path]:
        """Merge the on-chain TH CSV into a NON-globbing merged TH file.

        Reads the existing Koinly TH file (``koinly_th``, pre-resolved by the
        caller before the on-chain CSV was written so the ``*transaction_history*
        .csv`` glob could not match the on-chain file — review F1) READ-ONLY, for
        row-drop counting only. Drops rows whose ``Sending Wallet`` or
        ``Receiving Wallet`` is in ``opted_in_wallets`` (those are replaced by the
        on-chain projection), then appends the on-chain rows. The merged CSV is
        ALWAYS written to ``koinly_dir / "on_chain_merged_th.csv"`` (a name that
        does NOT match the ``*transaction_history*.csv`` discovery glob, so the
        pipeline reads it via the explicit ``transaction_history_override``
        instead of re-globbing — review F1/F7).

        INVARIANT (CR Guard): the user's real Koinly TH (``koinly_th``) is NEVER
        written, truncated, or unlinked on this path. It is opened READ-ONLY for
        row-drop counting. If no Koinly TH file exists, the on-chain rows become
        the merged TH (the None branch). ``on_chain_merged_th.csv`` from a prior
        run does NOT match the glob, so consecutive runs do not self-cannibalize.

        The merge produces a valid single-header CSV readable by
        ``read_koinly_rows`` / ``_detect_header_index``: ONE preamble + ONE header
        + the surviving Koinly data rows + the on-chain data rows.

        Returns:
            A ``(OnChainMergeStats, merged_path)`` tuple. The stats carry the
            per-wallet surviving-Koinly row counts and the count of Koinly rows
            dropped (replaced by the on-chain projection); ``merged_path`` is
            always ``koinly_dir / "on_chain_merged_th.csv"``.
        """
        # F2: match opted-in labels CASE-INSENSITIVELY (normalized). An exact
        # match today still matches after ``normalize_wallet_label`` (casefold is a strict
        # superset of exact for printable ASCII), so backward-compat holds. The
        # reconciliation provenance keeps RAW labels (the user sees raw labels
        # in the sheet); ONLY the drop decision uses the normalized form.
        opted_norm = {normalize_wallet_label(w) for w in opted_in_wallets if w.strip()}

        surviving_koinly_rows: list[dict[str, str]] = []
        dropped_koinly_rows = 0
        # Matched normalized labels (subset of ``opted_norm``); used by the
        # fail-loud-on-no-match check after the loop.
        matched_norm: set[str] = set()
        if koinly_th is not None and koinly_th != on_chain_th_csv:
            all_koinly_rows = read_koinly_rows(koinly_th)
            for row in all_koinly_rows:
                matches = matched_wallet_labels(row, opted_norm)
                if matches:
                    matched_norm.update(matches)
                    dropped_koinly_rows += 1
                    continue  # replaced by the on-chain projection
                surviving_koinly_rows.append(row)
            logger.info(
                "On-chain TH merge: kept %d/%d Koinly TH row(s) for non-opted-in wallets; "
                "dropped %d opted-in wallet row(s).",
                len(surviving_koinly_rows),
                len(all_koinly_rows),
                dropped_koinly_rows,
            )
            # F2 fail-loud: an opted-in label matching NO Koinly TH row means
            # the user almost certainly misconfigured the wallet list (typo,
            # wrong label). Silently dropping zero Koinly rows would leave the
            # wallet's Koinly rows in the merged TH alongside the on-chain
            # projection - a silent double-count with no signal. Raise instead.
            # (M1 contract: this raise propagates through the existing
            # try/except boundary in ``_main``; do NOT catch it here.) Skipped
            # in the None branch (no Koinly TH at all -> no rows to match
            # against; the on-chain projection becomes the whole TH).
            unmatched = opted_norm - matched_norm
            if unmatched:
                raise ReportGenerationError(
                    f"Opted-in wallet label(s) not found in Koinly TH after normalization: "
                    f"{sorted(unmatched)}"
                )
        else:
            logger.info(
                "On-chain TH merge: no pre-existing Koinly TH file; on-chain rows become the TH."
            )

        # Per-wallet surviving Koinly row counts (for the provenance table). A row
        # is attributed to its Sending Wallet when present, else its Receiving
        # Wallet (mirrors the merge's opted-in match). Surviving rows are, by
        # construction, NON-opted-in wallets, so every label here is Koinly-sourced.
        koinly_per_wallet: dict[str, int] = {}
        for row in surviving_koinly_rows:
            sending = (row.get("Sending Wallet") or "").strip()
            receiving = (row.get("Receiving Wallet") or "").strip()
            label = sending or receiving or "Unknown"
            koinly_per_wallet[label] = koinly_per_wallet.get(label, 0) + 1

        # The on-chain CSV (written by the serializer) is already TH-shaped with a
        # preamble + header + rows. Read its raw data rows (skip preamble+header)
        # and combine with the surviving Koinly rows, then write a single merged
        # TH file. ``read_koinly_rows`` returns dict rows keyed by column name; the
        # on-chain CSV has the same columns (plus ``event_id``). Koinly rows lack
        # ``event_id`` so they get an empty string (DictReader default None -> "").
        on_chain_rows_dicts = read_koinly_rows(on_chain_th_csv)
        # Normalize: ensure every row carries every TH column (Koinly rows predate
        # event_id; backfill empty so the merged DictWriter emits all columns).
        merged_rows: list[dict[str, str]] = []
        for row in surviving_koinly_rows:
            merged_row = {col: (row.get(col) or "") for col in TH_CSV_COLUMNS}
            merged_rows.append(merged_row)
        for row in on_chain_rows_dicts:
            merged_row = {col: (row.get(col) or "") for col in TH_CSV_COLUMNS}
            merged_rows.append(merged_row)

        # ALWAYS write the merged TH to the non-globbing ``on_chain_merged_th.csv``
        # (F1/F7). The user's real Koinly TH (``koinly_th``) is NEVER written to
        # or truncated (read-only invariant). The merged name does not match the
        # ``*transaction_history*.csv`` discovery glob, so the pipeline reads it
        # via the explicit ``transaction_history_override`` threaded through
        # ``load_koinly_crypto_report`` (no re-globbing).
        #
        # Atomic write (review F17): write to a sibling temp file, fsync, then
        # ``os.replace`` onto the final path. A crash/SIGINT/disk-full mid-flush
        # would otherwise leave a PARTIAL ``on_chain_merged_th.csv`` that the
        # next run's override would silently ingest as complete (wrong cost
        # basis with no fail-loud signal). The temp-then-rename ensures the
        # pipeline only ever sees a complete file or the previous run's file.
        # Mirrors the r2 hardening the bridge artifact already had.
        merged_path = koinly_dir / "on_chain_merged_th.csv"
        tmp_path = merged_path.with_suffix(".csv.tmp")
        with tmp_path.open("w", newline="", encoding="utf-8") as fh:
            fh.write("Transaction report\n")
            fh.write("\n")
            writer = csv.DictWriter(fh, fieldnames=list(TH_CSV_COLUMNS))
            writer.writeheader()
            for row in merged_rows:
                writer.writerow(row)
            fh.flush()
            os.fsync(fh.fileno())
        tmp_path.replace(merged_path)
        logger.info(
            "On-chain TH merge: wrote %d merged row(s) to %s.", len(merged_rows), merged_path
        )
        # Remove the standalone on-chain CSV now that its rows are merged in (it
        # matched the discovery glob pre-F1; unlinking keeps koinly_dir clean and
        # the on-chain standalone file is a transient bridge artifact).
        if on_chain_th_csv.exists() and on_chain_th_csv != merged_path:
            on_chain_th_csv.unlink()

        return (
            OnChainMergeStats(
                koinly_per_wallet=koinly_per_wallet,
                dropped_koinly_rows=dropped_koinly_rows,
            ),
            merged_path,
        )

    def _build_on_chain_reconciliation_record(
        self,
        *,
        txs: list[OnChainTransaction],
        projected: list,
        opted_in_wallets: list[str],
        merge_stats: OnChainMergeStats,
    ) -> OnChainReconciliationRecord:
        """Assemble the ``OnChainReconciliationRecord`` (Plan Task 12).

        Built from the on-chain projection + the Koinly-merge stats.

        Provenance table: one row per wallet that contributed to the merged TH.
        Opted-in wallets are ``on_chain`` (row count = their projected row count);
        every other wallet that contributed surviving Koinly rows is ``koinly``
        (row count from ``merge_stats.koinly_per_wallet``).

        Delta block: counts derived from the on-chain Events by ``EventType``
        (rewards added, gas added, LP reclassified) plus the dropped-Koinly count
        (rows reclassified Koinly -> on-chain). Sample hashes are a bounded,
        order-preserving sample of the on-chain tx hashes.
        """
        # Per-wallet on-chain projected row counts (one projected row per Event).
        # Review r1 F2: key by NORMALIZED label (``normalize_wallet_label``) so the lookup
        # below tolerates the same case/form mismatch the merge drop already
        # tolerates. The DISPLAYED ``wallet_label`` in the provenance row stays
        # RAW (the user sees what they configured); only the COUNT-lookup key is
        # normalized. Pre-r1 the raw configured label was used to look up a map
        # keyed by the raw bera CSV ``wallet_label`` — a case mismatch between
        # the two reported ``row_count=0`` despite a correct merge.
        on_chain_per_wallet: dict[str, int] = {}
        for p in projected:
            # ProjectedThRow.row.sending_wallet == receiving_wallet == tx.wallet_label
            # (the adapter sets both to ``tx.wallet_label``). Prefer sending then
            # receiving to be robust to future adapter changes.
            row = p.row
            label = (row.sending_wallet or row.receiving_wallet or "Unknown").strip()
            norm = normalize_wallet_label(label)
            on_chain_per_wallet[norm] = on_chain_per_wallet.get(norm, 0) + 1

        opted_set = {w.strip() for w in opted_in_wallets if w.strip()}

        provenance: list[WalletSourceProvenance] = []
        # Opted-in wallets first (on_chain), preserving the configured order so the
        # sheet reads deterministically.
        for wallet in opted_in_wallets:
            label = wallet.strip()
            if not label:
                continue
            provenance.append(
                WalletSourceProvenance(
                    wallet_label=label,
                    source_kind="on_chain",
                    # Look up the count by NORMALIZED label so a case/form
                    # mismatch between the configured label and the bera CSV
                    # wallet_label still resolves (review r1 F2).
                    row_count=on_chain_per_wallet.get(normalize_wallet_label(label), 0),
                )
            )
        # Then the surviving-Koinly wallets (koinly), sorted for determinism.
        for label, count in sorted(merge_stats.koinly_per_wallet.items()):
            if label in opted_set:
                continue
            provenance.append(
                WalletSourceProvenance(
                    wallet_label=label,
                    source_kind="koinly",
                    row_count=count,
                )
            )

        # Delta counts from the on-chain Events by EventType.
        rewards_added = 0
        gas_added = 0
        lp_reclassified = 0
        sample_hashes: list[str] = []
        seen_hashes: set[str] = set()
        for tx in txs:
            for event in tx.events:
                if event.event_type is EventType.Reward:
                    rewards_added += 1
                elif event.event_type is EventType.GasBurn:
                    gas_added += 1
                elif event.event_type in (EventType.LiquidityDeposit, EventType.LiquidityWithdraw):
                    lp_reclassified += 1
            # Sample the tx hashes (bounded, order-preserving, deduped).
            if tx.tx_hash and tx.tx_hash not in seen_hashes and len(sample_hashes) < _DELTA_SAMPLE_HASH_CAP:
                seen_hashes.add(tx.tx_hash)
                sample_hashes.append(tx.tx_hash)

        delta = OnChainDeltaBlock(
            rows_reclassified=merge_stats.dropped_koinly_rows,
            rewards_added=rewards_added,
            gas_added=gas_added,
            lp_reclassified=lp_reclassified,
            sample_hashes=sample_hashes,
        )
        return OnChainReconciliationRecord(
            per_wallet_source_provenance=provenance,
            on_chain_delta=delta,
        )

    def _resolve_registry_path(
        self,
        year: int,
        filename: str,
        override: Path | None,
        repo_root: Path,
        logger: logging.Logger,
    ) -> Path:
        """Resolve a per-year on-chain registry file path with example fallback.

        Resolution order (first match wins):
        1. ``override`` (explicit path injected by tests - points at the committed
           ``example/`` template so tests never read gitignored personal data,
           per AGENTS.md crypto-tests rule).
        2. ``resources/source/<year>/<filename>`` (the per-user override; gitignored,
           so absent on a fresh clone).
        3. ``resources/source/example/<year>/<filename>`` (the committed template;
           always present, so the opted-in path works out of the box).

        Logs INFO when the override or the fallback is used, so the user can see
        which registry drove classification.
        """
        if override is not None:
            logger.info("Using injected on-chain registry path for %s: %s", filename, override)
            return override
        primary = repo_root / "resources" / "source" / str(year) / filename
        if primary.is_file():
            return primary
        fallback = repo_root / "resources" / "source" / "example" / str(year) / filename
        logger.info(
            "No per-user %s at %s; falling back to committed example at %s.",
            filename,
            primary,
            fallback,
        )
        return fallback
