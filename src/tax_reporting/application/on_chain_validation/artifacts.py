"""Validation artifact writers for the on-chain TH validation harness (PD-010).

Renders a finished comparison (validation-harness Tasks 2-4) into the two
REGENERATED artifacts under ``<output_dir>/<year>/`` (plan Terms; production:
gitignored ``resources/result/<year>/``):

- ``on_chain_th_validation.md`` - the human review report: a run header
  (inputs, ``snapshot_as_of_block``, RPC on/off, wallet labels, validation
  window), summary counts (shared / Koinly-only / on-chain-only / match /
  divergent, plus per-cluster dispositioned-vs-NEW), and one section per
  discrepancy cluster with at most :data:`_MAX_SAMPLES_PER_CLUSTER`
  side-by-side samples (tx hash + on-chain shape vs Koinly shape + amount
  diffs; the remainder is counted, never silently dropped).
- ``on_chain_th_validation_diff.csv`` - the drill-down for triage: one row
  per discrepancy record (divergent shared txs and one-sided presence
  records), keyed by ``tx_hash``, carrying the cluster signature, the
  disposition status, and a mismatch summary.

Both files are REGENERATED (write mode ``"w"``) on every run - never
appended. The DISPOSITIONS file is a different artifact with a different
lifecycle (append-only, user-owned; Task 4) and is never touched here.

The artifacts deliberately CONTAIN real tx hashes: the PII rule (Design
Invariant 6) is enforced by LOCATION (only the gitignored result dir), not
by omission. Cluster signatures themselves stay PII-free (Task 3); these
writers only render them. Written via the ``csv`` stdlib writer only - no
``DictReader``-based parsing anywhere in this package (UL #45, Design
Invariant 4).

Plan: ``docs/history/plans/2026-08-18-on-chain-validation-harness.md``
(Task 5).
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Final

from tax_reporting.application.on_chain_validation.comparator import (
    AmountMismatch,
    ComparisonResult,
    Presence,
    ThComparisonRecord,
    TypeMismatch,
)
from tax_reporting.application.on_chain_validation.dispositions import DispositionEntry

__all__ = [
    "DIFF_CSV_FILENAME",
    "MARKDOWN_REPORT_FILENAME",
    "ValidationRunHeader",
    "write_validation_artifacts",
]

#: The markdown validation report filename (plan Terms).
MARKDOWN_REPORT_FILENAME: Final = "on_chain_th_validation.md"

#: The diff-CSV drill-down filename (plan Terms).
DIFF_CSV_FILENAME: Final = "on_chain_th_validation_diff.csv"

#: Per-cluster sample cap (plan Evaluation Criteria: per-cluster sections
#: with <=5 side-by-side samples; the remainder renders as an explicit
#: "... and N more" count so truncation is observable, never silent).
_MAX_SAMPLES_PER_CLUSTER: Final = 5

#: Diff-CSV column headers (self-explanatory user-facing labels).
_CSV_COLUMNS: Final[tuple[str, ...]] = ("Tx Hash", "Cluster Signature", "Disposition", "Mismatch Summary")

#: Status label for a cluster with no ruling yet (explicit partial-state
#: indicator; the actionable next step renders next to it in the report).
_STATUS_NEW: Final = "NEW"

#: Type-safe sentinel for an absent wallet-labels list (never a real label).
_MISSING_TEXT: Final = "MISSING"

#: Spreadsheet-formula trigger characters: a CSV cell whose FIRST character is
#: one of these is parsed as a formula by Excel/LibreOffice when the personal
#: diff CSV is opened (review r1 F22). The Koinly currency/Type cells are
#: external input and can render at the START of the Mismatch Summary (the
#: asset key leads the amount-diff text), so a ``=HYPERLINK(...)``-shaped
#: value must never reach the cell verbatim.
_CSV_FORMULA_TRIGGERS: Final[frozenset[str]] = frozenset("=+-@")


def _csv_safe(cell: str) -> str:
    """Neutralize a formula-shaped CSV cell (CSV-injection hardening).

    Prefixing a single quote (the standard spreadsheet escape) keeps the
    value fully visible while preventing execution. Every other cell passes
    through verbatim: the ``0x...`` hashes and ``events=...`` signatures
    never start with a trigger character, so only genuinely formula-shaped
    external input is affected.
    """
    if cell and cell[0] in _CSV_FORMULA_TRIGGERS:
        return f"'{cell}"
    return cell


@dataclass(frozen=True)
class ValidationRunHeader:
    """Inputs of one validation run, recorded verbatim in the markdown run header.

    The future runner (plan Task 6) passes these in; the writers never derive
    them, so the report always states exactly which inputs produced it.

    Attributes:
        year: The validation (fiscal) year; selects ``<output_dir>/<year>/``.
        on_chain_csv: The on-chain CSV path used (``bera_transactions.csv``).
        koinly_source: The Koinly directory (or file) the baseline came from.
        snapshot_as_of_block: The LP snapshot's ``snapshot_as_of_block``
            (from the projection's :class:`LpSnapshot`).
        rpc_enabled: Whether RPC enrichment (``ON_CHAIN_RPC_URL``) was active.
        wallet_labels: The wallet labels under validation.
        date_from: Inclusive ``--from`` window bound, or ``None``.
        date_to: Inclusive ``--to`` window bound, or ``None``.
    """

    year: int
    on_chain_csv: str
    koinly_source: str
    snapshot_as_of_block: int
    rpc_enabled: bool
    wallet_labels: tuple[str, ...]
    date_from: date | None
    date_to: date | None


def _window_text(run: ValidationRunHeader) -> str:
    """Render the validation window (``--from/--to`` dates or "full year")."""
    if run.date_from is not None and run.date_to is not None:
        return f"{run.date_from.isoformat()} to {run.date_to.isoformat()} (inclusive)"
    if run.date_from is not None:
        return f"from {run.date_from.isoformat()} (inclusive)"
    if run.date_to is not None:
        return f"up to {run.date_to.isoformat()} (inclusive)"
    return "full year"


def _labels_text(labels: tuple[str, ...]) -> str:
    """Render the wallet labels, degrading an empty list explicitly."""
    if not labels:
        return _MISSING_TEXT
    return "; ".join(labels)


def _shape(combos: frozenset[tuple[str, str]]) -> str:
    """Render one side's ``Type/Tag`` shape (sorted, ``+``-joined), ``none`` when empty."""
    return "+".join(sorted(f"{type_}/{tag}" for type_, tag in combos)) or "none"


def _type_mismatch_text(mismatch: TypeMismatch) -> str:
    """Render a type incompatibility as actionable summary text."""
    parts: list[str] = []
    if mismatch.uncovered_koinly_combos:
        uncovered = "+".join(sorted(f"{type_}/{tag}" for type_, tag in mismatch.uncovered_koinly_combos))
        parts.append(f"type: Koinly combo(s) not explained by any on-chain event: {uncovered}")
    if mismatch.unmatched_event_types:
        unmatched = "+".join(sorted(event_type.name for event_type in mismatch.unmatched_event_types))
        parts.append(f"type: on-chain event type(s) without a compatible Koinly combo: {unmatched}")
    return "; ".join(parts)


def _amount_mismatch_text(mismatch: AmountMismatch) -> str:
    """Render one amount-divergent bucket with both sides and the tolerance.

    Decimals render via ``:f`` (never scientific notation - ``str()`` of
    ``Decimal("0.00000001")`` is ``"1E-8"``, unreadable in a report).
    """
    bucket = f"{mismatch.asset}/{mismatch.direction}" if mismatch.direction is not None else f"gas {mismatch.asset}"
    text = (
        f"{bucket}: on-chain {mismatch.on_chain_amount:f} vs Koinly {mismatch.koinly_amount:f}"
        f" (tolerance {mismatch.tolerance:f})"
    )
    if mismatch.zero_display:
        text += " [Koinly displays zero]"
    return text


def _mismatch_summary(record: ThComparisonRecord) -> str:
    """Render one record's mismatches; one-sided records explain their absence."""
    parts: list[str] = []
    if record.type_mismatch is not None:
        parts.append(_type_mismatch_text(record.type_mismatch))
    parts.extend(_amount_mismatch_text(mismatch) for mismatch in record.amount_mismatches)
    if parts:
        return "; ".join(parts)
    if record.presence is Presence.ON_CHAIN_ONLY:
        return "on-chain only: no Koinly transaction-history row carries this tx hash"
    return "Koinly only: no on-chain projection row carries this tx hash"


def _entries_by_signature(entries: list[DispositionEntry]) -> dict[str, DispositionEntry]:
    """Index the dispositions entries by signature (fail-loud on duplicates).

    A duplicate signature would be an ambiguous ruling; overwriting it
    silently is the harness's failure mode, so it raises instead.
    """
    index: dict[str, DispositionEntry] = {}
    for entry in entries:
        if entry.signature in index:
            raise ValueError(f"duplicate dispositions entry for cluster signature {entry.signature!r}")
        index[entry.signature] = entry
    return index


def _disposition_status(signature: str, index: dict[str, DispositionEntry]) -> str:
    """The cluster's status: its user ruling, or :data:`_STATUS_NEW`."""
    entry = index.get(signature)
    if entry is not None and entry.disposition != "":
        return entry.disposition
    return _STATUS_NEW


def _render_markdown(
    run: ValidationRunHeader,
    result: ComparisonResult,
    clusters: dict[str, list[ThComparisonRecord]],
    index: dict[str, DispositionEntry],
) -> str:
    """Render the full markdown validation report (deterministic ordering).

    Clusters iterate in sorted-signature order and records stay in the
    clustering module's hash-sorted order, so consecutive runs with the same
    inputs produce byte-identical reports.
    """
    statuses = {signature: _disposition_status(signature, index) for signature in clusters}
    dispositioned = sum(1 for status in statuses.values() if status != _STATUS_NEW)

    lines: list[str] = [
        f"# On-chain TH validation - {run.year}",
        "",
        "Run header:",
        "",
        f"- On-chain CSV: {run.on_chain_csv}",
        f"- Koinly source: {run.koinly_source}",
        f"- LP snapshot as of block: {run.snapshot_as_of_block}",
        f"- RPC enrichment: {'enabled' if run.rpc_enabled else 'disabled'}",
        f"- Wallets under validation: {_labels_text(run.wallet_labels)}",
        f"- Validation window: {_window_text(run)}",
        "",
        "## Summary",
        "",
        f"- Shared transaction hashes: {len(result.shared_tx_hashes)}",
        f"- Matched (semantically equivalent): {len(result.matched_tx_hashes)}",
        f"- Divergent: {len(result.divergent)}",
        f"- On-chain only: {len(result.on_chain_only)}",
        f"- Koinly only: {len(result.koinly_only)}",
        f"- Discrepancy clusters: {len(clusters)} ({dispositioned} dispositioned, {len(clusters) - dispositioned} NEW)",
        "",
        "Cluster dispositions:",
        "",
    ]
    for signature in sorted(clusters):
        lines.append(f"- {statuses[signature]} ({len(clusters[signature])} occurrence(s)): {signature}")
    lines.append("")

    for signature in sorted(clusters):
        records = clusters[signature]
        status = statuses[signature]
        lines.extend([f"## Cluster: {signature}", "", f"- Occurrences: {len(records)}"])
        if status == _STATUS_NEW:
            lines.append(
                "- Disposition: NEW (not yet ruled on; fill disposition/root_cause/action in the dispositions file)"
            )
        else:
            lines.append(f"- Disposition: {status}")
        lines.extend(
            [
                "",
                "### Samples",
                "",
                "| tx hash | on-chain shape | Koinly shape | mismatch detail |",
                "| --- | --- | --- | --- |",
            ]
        )
        for record in records[:_MAX_SAMPLES_PER_CLUSTER]:
            lines.append(
                f"| `{record.tx_hash}` | {_shape(record.on_chain_combos)} | {_shape(record.koinly_combos)}"
                f" | {_mismatch_summary(record)} |"
            )
        remaining = len(records) - _MAX_SAMPLES_PER_CLUSTER
        if remaining > 0:
            lines.extend(["", f"… and {remaining} more occurrence(s) not shown"])
        lines.append("")
    return "\n".join(lines) + "\n"


def _write_diff_csv(
    path: Path,
    clusters: dict[str, list[ThComparisonRecord]],
    index: dict[str, DispositionEntry],
) -> None:
    """Write the diff CSV (one row per discrepancy record, regenerated).

    Every field passes through :func:`_csv_safe` (review r1 F22): the
    Mismatch Summary renders external Koinly cells (a formula-shaped
    currency can lead the cell), and the Disposition column carries
    user-entered TOML strings, so the neutralization is applied uniformly
    rather than per-column.
    """
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(_CSV_COLUMNS)
        for signature in sorted(clusters):
            status = _disposition_status(signature, index)
            for record in clusters[signature]:
                row = (record.tx_hash, signature, status, _mismatch_summary(record))
                writer.writerow(tuple(_csv_safe(cell) for cell in row))


def write_validation_artifacts(
    *,
    output_dir: Path,
    run: ValidationRunHeader,
    result: ComparisonResult,
    clusters: dict[str, list[ThComparisonRecord]],
    dispositions: list[DispositionEntry],
) -> tuple[Path, Path]:
    """Write the regenerated validation artifacts under ``<output_dir>/<year>/``.

    Creates the year directory when missing. Both files are written in
    ``"w"`` mode, so a rerun REPLACES the previous artifacts (never
    concatenates); the append-only dispositions file is not touched.

    Args:
        output_dir: The artifacts root (production:
            ``resources/result/``; tests pass a tmp stand-in).
        run: The run-header inputs recorded verbatim in the markdown report.
        result: The :func:`compare_projection` outcome (summary counts).
        clusters: The :func:`group_into_clusters` output (per-cluster
            sections and CSV rows).
        dispositions: The loaded dispositions entries (dispositioned-vs-NEW
            status; entries whose clusters do not occur are ignored).

    Returns:
        ``(markdown_path, diff_csv_path)`` - the written artifact paths.

    Raises:
        ValueError: If ``dispositions`` contains two entries with the same
            signature (ambiguous ruling; never silently overwritten).
    """
    year_dir = output_dir / str(run.year)
    year_dir.mkdir(parents=True, exist_ok=True)
    index = _entries_by_signature(dispositions)
    markdown_path = year_dir / MARKDOWN_REPORT_FILENAME
    diff_csv_path = year_dir / DIFF_CSV_FILENAME
    markdown_path.write_text(_render_markdown(run, result, clusters, index), encoding="utf-8")
    _write_diff_csv(diff_csv_path, clusters, index)
    return markdown_path, diff_csv_path
