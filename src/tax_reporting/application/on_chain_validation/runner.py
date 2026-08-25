"""On-chain TH validation runner (validation-harness Task 6; PD-009/PD-010).

Wires the harness end to end behind one callable::

    wallets -> production projection (Task 1) -> Koinly TH baseline
            -> compare (Task 2) -> cluster (Task 3)
            -> dispositions (Task 4) -> artifacts (Task 5) -> exit gate

Resolution order mirrors production (plan Task 6):

- wallets: ``load_on_chain_wallets(year)`` filtered to
  ``chain == "Berachain"`` unless injected. The runner NEVER requires
  ``ON_CHAIN_TH_WALLETS`` (that config takes precedence when set, resolved in
  the composition root ``main.py`` which owns config reads - Design
  Invariant 9).
- projection: ``OnChainThSubstituter(...).build_projection`` (Task 1) with
  the inclusive window args passed through - the EXACT production pipeline
  (reader -> processor -> audit -> adapter), never a parallel parse path.
- Koinly TH: the production discovery ``_resolve_koinly_directory`` unless a
  directory is injected, then ``_find_report_path`` +
  ``read_koinly_rows`` filtered by ``is_wallet_row`` (Task 1) and, when a
  window is set, by an inclusive date filter on
  ``parse_koinly_datetime(row["Date"]).date()`` (the production parser; BOTH
  sides must see the same window or the hash partitions diverge).

Fail-loud enumeration (plan Task 6; all BEFORE any dispositions append so a
misconfigured run never writes feedback-loop state) - each logs a clear error
naming the missing input and returns :data:`EXIT_VALIDATION_FAILED`:

1. no Berachain wallets resolved;
2. absent bera CSV (``build_projection`` -> ``None``; its Task-1 WARNING has
   already fired - this adds the explicit "nothing validated");
3. Koinly side missing: no directory resolved for the year, or the resolved
   directory carries no ``*transaction_history*.csv``. Both discovery helpers
   return ``None`` rather than raising; any run for a year with no Koinly
   export (permanent for 2026 onward) hits exactly this path.
4. an EMPTY comparison: both sides filtered to zero rows (e.g. a
   ``--from/--to`` window that misses the data, or a bera CSV whose rows
   match no Koinly wallet row). Exit 0 is the acceptance evidence for the
   production flag flip, so a run that compared ZERO transactions must
   never be readable as a validated pass.

Exit codes: ``0`` gate passed, :data:`EXIT_VALIDATION_FAILED` (1)
misconfigured inputs, ``3`` validation incomplete (the dispositions gate,
Task 4), ``2`` unexpected crash (``EXIT_VALIDATION_CRASH`` in
``dispositions.py``, set by the ``cli()`` wrapper in ``main.py``).

Composition-root discipline: collaborators (wallets, Koinly dir, rpc_url,
window) arrive as parameters; this module performs no config/env reads.

Patch seams (the ``run_report.py:31`` consumer-module convention): tests patch
``load_on_chain_wallets``, ``_resolve_koinly_directory``, and
``OnChainThSubstituter`` on THIS module - patching their defining modules is
ineffective under from-import binding.

Plan: ``docs/history/plans/2026-08-18-on-chain-validation-harness.md``
(Task 6).
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Final

from tax_reporting.application.koinly_directory import (  # tests patch this symbol HERE (patch seam)
    _resolve_koinly_directory,
)
from tax_reporting.application.on_chain_config import BERACHAIN_CHAIN, load_on_chain_wallets
from tax_reporting.application.on_chain_fetcher import bera_csv_path
from tax_reporting.application.on_chain_th_substitution import (
    TH_MARKER,
    TH_SUFFIX,
    OnChainThSubstituter,
    in_window_inclusive,
    is_wallet_row,
    normalize_wallet_label,
)
from tax_reporting.application.on_chain_validation.artifacts import (
    ValidationRunHeader,
    write_validation_artifacts,
)
from tax_reporting.application.on_chain_validation.clustering import group_into_clusters
from tax_reporting.application.on_chain_validation.comparator import compare_projection
from tax_reporting.application.on_chain_validation.dispositions import (
    append_new_clusters,
    evaluate_gate,
    load_dispositions,
)
from tax_reporting.application.paths import find_repository_root
from tax_reporting.domain.on_chain_config import OnChainWalletConfig
from tax_reporting.infrastructure.koinly_parser import (
    _find_report_path,
    parse_koinly_datetime,
    read_koinly_rows,
)

__all__ = [
    "DISPOSITIONS_FILENAME",
    "EXIT_VALIDATION_FAILED",
    "run_validation",
]

#: Exit code for a misconfigured run (fail-loud enumeration): a missing input
#: (wallets / bera CSV / Koinly side) must never be mistaken for a validated
#: pass (0) or an incomplete-but-run state (3).
EXIT_VALIDATION_FAILED: Final[int] = 1

#: The append-only, user-owned dispositions file (plan Terms; lives under
#: ``<output_dir>/<year>/`` next to the regenerated artifacts).
DISPOSITIONS_FILENAME: Final = "on_chain_th_dispositions.toml"

# The TH discovery glob shape and the inclusive-window predicate come from
# ``on_chain_th_substitution`` (the ONE definition shared with the projection
# side), and the Berachain chain literal from the wallets loader
# (twin literals can drift apart silently).

#: Default Koinly base directory (production resolves the Koinly dir under
#: ``resources/source`` - the same base the report pipeline derives from its
#: source file's parent).
_KOINLY_BASE_DIR: Final = ("resources", "source")


def _resolve_validation_wallets(year: int, wallets: list[OnChainWalletConfig] | None) -> list[OnChainWalletConfig]:
    """Resolve the wallets under validation.

    Injected wallets are used as given (the injector decides the set); the
    default derives them from ``chains.json`` Berachain entries (Design
    Invariant 9 - ``ON_CHAIN_TH_WALLETS`` precedence is resolved in the
    composition root, which injects the filtered list).
    """
    if wallets is not None:
        return wallets
    return [wallet for wallet in load_on_chain_wallets(year) if wallet.chain == BERACHAIN_CHAIN]


def run_validation(  # noqa: PLR0913 (plan-fixed collaborator set)
    *,
    year: int,
    output_dir: Path,
    koinly_dir: Path | None = None,
    wallets: list[OnChainWalletConfig] | None = None,
    rpc_url: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    logger: logging.Logger,
) -> int:
    """Run the on-chain TH validation harness for ``year`` (read-only).

    The user's Koinly export and bera CSV are opened READ-ONLY; the only
    writes land under ``<output_dir>/<year>/`` (production: gitignored
    ``resources/result/<year>/``): the two regenerated artifacts and the
    append-only dispositions file.

    Args:
        year: The validation (fiscal) year; selects the bera CSV subdirectory,
            the Koinly directory, and the artifacts subdirectory.
        output_dir: Base output directory (bera CSV read from
            ``<output_dir>/<year>/``; artifacts written there).
        koinly_dir: Explicit Koinly directory; ``None`` resolves it via the
            production discovery (``resources/source/<year>/koinly``).
        wallets: The wallets under validation; ``None`` derives them from the
            ``chains.json`` Berachain entries for ``year``.
        rpc_url: Optional Berachain JSON-RPC endpoint (enables LP
            auto-discovery enrichment in the projection; recorded in the run
            header). ``None`` keeps the projection snapshot-only.
        date_from: Optional inclusive window start (both sides filtered).
        date_to: Optional inclusive window end (both sides filtered).
        logger: Logger for diagnostics.

    Returns:
        The exit status: ``0`` gate passed, ``1`` misconfigured inputs
        (fail-loud enumeration), ``3`` validation incomplete (dispositions
        gate).
    """
    # --- Fail-loud (1/4): no Berachain wallets resolved. ---------------------
    resolved_wallets = _resolve_validation_wallets(year, wallets)
    if not resolved_wallets:
        logger.error(
            "No Berachain wallets resolved for year %d; nothing was validated. "
            "Validation wallets come from resources/source/<year>/chains.json entries "
            "with chain == 'Berachain' (or the injected wallets parameter).",
            year,
        )
        return EXIT_VALIDATION_FAILED

    # --- Fail-loud (2/4): absent bera CSV (build_projection warns + None). ---
    bera_csv = bera_csv_path(output_dir, year)
    projection = OnChainThSubstituter(on_chain_rpc_url=rpc_url).build_projection(
        year=year,
        output_dir=output_dir,
        logger=logger,
        date_from=date_from,
        date_to=date_to,
    )
    if projection is None:
        logger.error(
            "No on-chain CSV found at %s; nothing was validated.",
            bera_csv,
        )
        return EXIT_VALIDATION_FAILED

    # --- Fail-loud (3/4): Koinly side missing (dir or TH file). --------------
    resolved_koinly_dir = (
        koinly_dir
        if koinly_dir is not None
        else _resolve_koinly_directory(
            find_repository_root().joinpath(*_KOINLY_BASE_DIR),
            tax_year_hint=year,
            fiscal_year=year,
        )
    )
    if resolved_koinly_dir is None:
        logger.error(
            "No Koinly directory found for year %d under %s; the validation requires "
            "the Koinly transaction-history baseline (no directory resolved).",
            year,
            find_repository_root().joinpath(*_KOINLY_BASE_DIR),
        )
        return EXIT_VALIDATION_FAILED
    koinly_th = _find_report_path(resolved_koinly_dir, TH_MARKER, TH_SUFFIX)
    if koinly_th is None:
        logger.error(
            "No *%s*%s file found in Koinly directory %s; the validation requires "
            "the Koinly transaction-history baseline.",
            TH_MARKER,
            TH_SUFFIX,
            resolved_koinly_dir,
        )
        return EXIT_VALIDATION_FAILED

    # --- Koinly baseline: wallet rows, then the same inclusive window. -------
    norm_labels = {normalize_wallet_label(wallet.label) for wallet in resolved_wallets if wallet.label.strip()}
    koinly_rows = [row for row in read_koinly_rows(koinly_th) if is_wallet_row(row, norm_labels)]
    if date_from is not None or date_to is not None:
        koinly_rows = [
            row
            for row in koinly_rows
            if in_window_inclusive(parse_koinly_datetime(row["Date"]).date(), date_from, date_to)
        ]

    # --- compare -> cluster. --------------------------------------------------
    # The SOURCE transactions ride along so each record carries the on-chain
    # legs' token addresses - the authoritative LP discriminator of the
    # cluster signature.
    result = compare_projection(
        koinly_rows,
        projection.projected_rows,
        on_chain_transactions=projection.transactions,
    )

    # --- Fail-loud (4/4): an EMPTY comparison is "nothing validated". --------
    # A window that misses the data (typo, wrong year) or a bera CSV whose
    # rows match no Koinly wallet row leaves both partitions empty; the gate
    # would vacuously pass with exit 0 - the exact evidence the flag-flip
    # acceptance trusts. Fail closed BEFORE any dispositions append (review
    # blocking).
    if not (result.shared_tx_hashes or result.on_chain_only or result.koinly_only):
        logger.error(
            "Nothing to compare for year %d (0 shared and 0 one-sided transaction hashes); "
            "check the --from/--to window and the bera CSV contents. Nothing was validated.",
            year,
        )
        return EXIT_VALIDATION_FAILED
    clusters = group_into_clusters(result, registry=projection.registry, lp_snapshot=projection.lp_snapshot)
    logger.info(
        "On-chain TH validation (%s): %d shared hash(es) -> %d matched, %d divergent, "
        "%d on-chain-only, %d Koinly-only, %d discrepancy cluster(s).",
        year,
        len(result.shared_tx_hashes),
        len(result.matched_tx_hashes),
        len(result.divergent),
        len(result.on_chain_only),
        len(result.koinly_only),
        len(clusters),
    )

    # --- dispositions (append-only) -> artifacts -> gate. ---------------------
    # All fail-loud checks are past: from here the run may write feedback-loop
    # state. The directory is created only now so error paths leave no trace.
    dispositions_path = output_dir / str(year) / DISPOSITIONS_FILENAME
    dispositions_path.parent.mkdir(parents=True, exist_ok=True)
    append_new_clusters(dispositions_path, list(clusters.keys()), datetime.now(tz=UTC).date())
    entries = load_dispositions(dispositions_path)
    run_header = ValidationRunHeader(
        year=year,
        on_chain_csv=str(bera_csv),
        koinly_source=str(resolved_koinly_dir),
        snapshot_as_of_block=projection.lp_snapshot.snapshot_as_of_block,
        rpc_enabled=rpc_url is not None,
        wallet_labels=tuple(wallet.label for wallet in resolved_wallets),
        date_from=date_from,
        date_to=date_to,
    )
    write_validation_artifacts(
        output_dir=output_dir,
        run=run_header,
        result=result,
        clusters=clusters,
        dispositions=entries,
    )
    gate = evaluate_gate({signature: len(records) for signature, records in clusters.items()}, entries)
    if gate.passed:
        logger.info("On-chain TH validation (%s) passed: every occurring cluster is acceptable.", year)
    else:
        logger.error(
            "On-chain TH validation (%s) incomplete (exit %d):\n%s",
            year,
            gate.exit_code,
            gate.reason,
        )
    return gate.exit_code
