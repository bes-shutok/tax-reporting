"""Append-only dispositions file + validation exit gate (PD-010).

The dispositions file (``resources/result/<year>/on_chain_th_dispositions.toml``)
is the user-owned feedback loop of the on-chain TH validation harness
(validation-harness Task 4,
``docs/history/plans/2026-08-18-on-chain-validation-harness.md``):

- the harness APPENDS one ``[[clusters]]`` template block per NEW cluster
  signature (dedup by signature across runs) and NEVER rewrites or deletes
  existing entries (Design Invariant 8);
- the user fills ``disposition`` (``missing_rule`` |
  ``incorrect_processing`` | ``acceptable_difference``), ``root_cause``, and
  ``action`` by hand - the harness never writes a ruling;
- the exit gate (Design Invariant 7) exits :data:`EXIT_VALIDATION_INCOMPLETE`
  (3) while any occurring cluster lacks a ruling or any fix-type ruling
  (``missing_rule``/``incorrect_processing``) still occurs, and 0 only when
  solely ``acceptable_difference`` clusters remain. A fix-type ruling whose
  cluster has STOPPED occurring passes - that is the fix-landed assertion.

Exit codes owned here: :data:`EXIT_VALIDATION_INCOMPLETE` (3),
:data:`EXIT_VALIDATION_PASSED` (0), and :data:`EXIT_VALIDATION_CRASH` (2,
set by the ``cli()`` wrapper in ``main.py`` when the validation path crashes
unexpectedly; a misconfigured run is 1 via
:data:`tax_reporting.application.on_chain_validation.runner.EXIT_VALIDATION_FAILED`).

Fail-loud (Design Invariant 2, M1): malformed TOML raises ``ValueError``
chaining ``tomllib.TOMLDecodeError`` with the file path in the message; an
invalid ``disposition`` value, a structurally invalid block, or a duplicate
signature also fails loudly - a silently waved-through cluster is the
harness's failure mode, never a valid outcome here. Because the ``ValueError``
escapes :func:`...runner.run_validation` to the ``cli()`` wrapper in
``main.py``, a malformed dispositions file surfaces as exit 2
(:data:`EXIT_VALIDATION_CRASH`), not 1 - acceptance scripts must classify a
hand-corrupted dispositions TOML as a crash, not a misconfigured run.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Final

__all__ = [
    "EXIT_VALIDATION_CRASH",
    "EXIT_VALIDATION_INCOMPLETE",
    "EXIT_VALIDATION_PASSED",
    "DispositionEntry",
    "GateResult",
    "append_new_clusters",
    "evaluate_gate",
    "load_dispositions",
]

#: Exit code while validation is incomplete (Design Invariant 7): any
#: occurring cluster without a ruling, or with a fix-type ruling whose
#: cluster still occurs.
EXIT_VALIDATION_INCOMPLETE: Final[int] = 3

#: Exit code when the gate passes: solely ``acceptable_difference`` rulings
#: remain among the occurring clusters.
EXIT_VALIDATION_PASSED: Final[int] = 0

#: Exit code for an unexpected crash of the validation CLI path: the ``cli()``
#: wrapper in ``main.py`` catches it, logs via ``logger.exception``, prints a
#: friendly message, and exits with this code. Distinct from a misconfigured
#: run (1, :data:`tax_reporting.application.on_chain_validation.runner.EXIT_VALIDATION_FAILED`).
EXIT_VALIDATION_CRASH: Final[int] = 2

#: Fix-type rulings: they keep failing the gate while the cluster still
#: occurs, and assert the fix has landed once it stops occurring.
_FIX_DISPOSITIONS: Final[frozenset[str]] = frozenset({"missing_rule", "incorrect_processing"})

#: The only ruling that lets a cluster keep occurring without blocking.
_ACCEPTABLE_DISPOSITION: Final = "acceptable_difference"

#: The full user-ruling vocabulary (Invariant 8: rulings are user decisions;
#: an empty string means NEW - appended but not yet ruled on).
_VALID_DISPOSITIONS: Final[frozenset[str]] = _FIX_DISPOSITIONS | {_ACCEPTABLE_DISPOSITION}

#: Explanatory header, written ONCE at file creation (append-only invariant:
#: later appends never rewrite it).
_HEADER_COMMENT: Final = (
    "# On-chain TH validation dispositions (PD-010) - APPEND-ONLY, user-owned.\n"
    "# The validation harness appends one [[clusters]] template block per NEW\n"
    "# cluster signature and never rewrites or deletes existing entries. Fill\n"
    "# disposition, root_cause and action by hand for each NEW block:\n"
    '#   disposition = "missing_rule" | "incorrect_processing" | "acceptable_difference"\n'
    "# missing_rule / incorrect_processing keep failing the gate while the\n"
    "# cluster still occurs (a fix-type ruling passes once its cluster has\n"
    "# stopped occurring - the fix-landed assertion); acceptable_difference\n"
    "# lets the cluster keep occurring without blocking the gate.\n"
)

#: The template's disposition line, verbatim from the plan Task 4 TOML shape
#: (the inline comment documents the vocabulary at every appended block).
_TEMPLATE_DISPOSITION_LINE: Final = (
    'disposition = ""      # missing_rule | incorrect_processing | acceptable_difference\n'
)


@dataclass(frozen=True)
class DispositionEntry:
    """One ``[[clusters]]`` block of the dispositions file.

    Attributes:
        signature: The PII-free cluster signature (clustering Task 3 output).
        first_seen: ISO date the harness first appended the block.
        disposition: The user's ruling; ``""`` means NEW (not yet ruled on).
        root_cause: Free-text root cause (user-filled).
        action: Free-text remediation action (user-filled).
    """

    signature: str
    first_seen: str
    disposition: str
    root_cause: str
    action: str


@dataclass(frozen=True)
class GateResult:
    """Outcome of the validation exit gate (PD-010, Design Invariant 7).

    Attributes:
        passed: True only when every occurring cluster carries an
            ``acceptable_difference`` ruling (absent clusters never block).
        exit_code: :data:`EXIT_VALIDATION_PASSED` (0) or
            :data:`EXIT_VALIDATION_INCOMPLETE` (3).
        reason: Actionable failure text naming each failing signature and why
            it fails; ``""`` when passed.
    """

    passed: bool
    exit_code: int
    reason: str


def _ensure_valid_disposition(signature: str, disposition: object) -> None:
    """Validate a ruling against the plan vocabulary (fail-loud).

    ``""`` is valid (NEW - the template's not-yet-ruled state). Anything
    outside :data:`_VALID_DISPOSITIONS` must fail loudly: the gate's
    branch structure treats only ``acceptable_difference`` as non-blocking,
    so an invalid value reaching it would silently wave the cluster through.

    Raises:
        ValueError: If ``disposition`` is neither the empty string nor one
            of the three plan vocabulary values.
    """
    if isinstance(disposition, str) and (disposition == "" or disposition in _VALID_DISPOSITIONS):
        return
    raise ValueError(
        f"invalid disposition {disposition!r} for cluster signature {signature!r}: "
        f'expected one of {sorted(_VALID_DISPOSITIONS)} or "" (NEW)'
    )


def _entry_from_block(block: object) -> DispositionEntry:
    """Build a :class:`DispositionEntry` from one parsed TOML table.

    Raises:
        ValueError: If the block is not a table, lacks a non-empty
            ``signature`` string, or carries an invalid ``disposition``.
    """
    if not isinstance(block, dict):
        raise ValueError(f"cluster block must be a TOML table, got {type(block).__name__}")
    signature = block.get("signature")
    if not isinstance(signature, str) or not signature:
        raise ValueError("block is missing a non-empty 'signature' string")
    disposition = block.get("disposition", "")
    _ensure_valid_disposition(signature, disposition)
    return DispositionEntry(
        signature=signature,
        first_seen=str(block.get("first_seen", "")),
        disposition=disposition,
        root_cause=str(block.get("root_cause", "")),
        action=str(block.get("action", "")),
    )


def load_dispositions(path: Path) -> list[DispositionEntry]:
    """Load all ``[[clusters]]`` entries from the dispositions file.

    A missing file is not an error: it yields ``[]`` (every cluster is NEW;
    :func:`append_new_clusters` creates the file with its header).

    Args:
        path: Path to ``on_chain_th_dispositions.toml``.

    Returns:
        The entries in file order (append order).

    Raises:
        ValueError: If the file is unparseable TOML (chaining the original
            ``tomllib.TOMLDecodeError``, with the file path in the message),
            or a block is structurally invalid, carries an invalid
            ``disposition`` value, or duplicates an earlier signature.
    """
    if not path.exists():
        return []
    try:
        with path.open("rb") as handle:
            document = tomllib.load(handle)
    except tomllib.TOMLDecodeError as error:
        raise ValueError(f"malformed dispositions TOML in {path}: {error}") from error
    raw_clusters = document.get("clusters", [])
    if not isinstance(raw_clusters, list):
        raise ValueError(f"'clusters' must be an array of tables in {path}, got {type(raw_clusters).__name__}")

    entries: list[DispositionEntry] = []
    seen_signatures: set[str] = set()
    for index, block in enumerate(raw_clusters):
        try:
            entry = _entry_from_block(block)
        except ValueError as error:
            raise ValueError(f"invalid [[clusters]] block #{index + 1} in {path}: {error}") from error
        if entry.signature in seen_signatures:
            raise ValueError(
                f"invalid [[clusters]] block #{index + 1} in {path}: "
                f"duplicate cluster signature {entry.signature!r} (ambiguous ruling)"
            )
        seen_signatures.add(entry.signature)
        entries.append(entry)
    return entries


def _ensure_writable_signature(signature: str) -> None:
    """Guard the TOML format integrity of an appended block.

    Cluster signatures render inside TOML basic (double-quoted) strings; a
    quote, backslash, or CONTROL character (newline and carriage return
    included - Koinly Type/Tag cells can carry embedded ones past the
    end-strip-only text handling) would corrupt the appended block and break
    the next load. Fails loudly BEFORE any write.

    Raises:
        ValueError: If the signature is empty or contains a character TOML
            basic strings cannot carry verbatim.
    """
    if not signature:
        raise ValueError("cluster signature must be non-empty")
    if any((not character.isprintable()) or character in ('"', "\\") for character in signature):
        raise ValueError(
            f"cluster signature contains a character TOML basic strings cannot carry verbatim: {signature!r}"
        )


def _template_block(signature: str, first_seen: str) -> str:
    """Render one NEW-signature ``[[clusters]]`` template block (plan shape)."""
    return (
        "\n[[clusters]]\n"
        f'signature = "{signature}"\n'
        f'first_seen = "{first_seen}"\n'
        f"{_TEMPLATE_DISPOSITION_LINE}"
        'root_cause = ""\n'
        'action = ""\n'
    )


def append_new_clusters(path: Path, signatures: list[str], today: date) -> list[str]:
    """Append one template block per NEW cluster signature (append-only).

    Creates the file with the explanatory header comment when missing.
    Signatures already present ANYWHERE in the file are skipped, so
    consecutive runs never duplicate a block and existing entries are never
    rewritten. All validation (TOML parse, signature form) happens BEFORE
    the file is opened for writing, so a failure leaves the file untouched.

    Args:
        path: Path to ``on_chain_th_dispositions.toml`` (parent directory
            must exist; the caller owns directory creation).
        signatures: The occurring cluster signatures (unique, as from
            ``dict`` keys; a repeated input signature appends once).
        today: The run date stamped as ``first_seen`` (a ``date``; the
            caller injects it - never ``date.today()``).

    Returns:
        The signatures actually appended (the NEW ones, in input order).

    Raises:
        ValueError: If the existing file is malformed or contains an invalid
            block (propagated from :func:`load_dispositions`), or a
            signature cannot be rendered in TOML.
    """
    present_signatures = {entry.signature for entry in load_dispositions(path)}
    for signature in signatures:
        _ensure_writable_signature(signature)

    first_seen = today.isoformat()
    appended: list[str] = []
    blocks: list[str] = []
    for signature in signatures:
        if signature in present_signatures:
            continue
        present_signatures.add(signature)
        blocks.append(_template_block(signature, first_seen))
        appended.append(signature)

    file_existed = path.exists()
    if blocks or not file_existed:
        with path.open("a", encoding="utf-8") as handle:
            if not file_existed:
                handle.write(_HEADER_COMMENT)
            handle.write("".join(blocks))
    return appended


def evaluate_gate(clusters: dict[str, int], entries: list[DispositionEntry]) -> GateResult:
    """Evaluate the PD-010 exit gate over the occurring clusters.

    Semantics (Design Invariant 7): fail with exit
    :data:`EXIT_VALIDATION_INCOMPLETE` while any occurring cluster has no
    ruling (no entry, or an empty ``disposition``) or carries a fix-type
    ruling (``missing_rule``/``incorrect_processing``) whose cluster still
    occurs; pass with exit :data:`EXIT_VALIDATION_PASSED` only when solely
    ``acceptable_difference`` rulings remain. Entries whose clusters do NOT
    occur never block (the fix-landed assertion).

    Args:
        clusters: Occurring cluster signatures mapped to occurrence counts.
        entries: The loaded dispositions entries.

    Returns:
        A :class:`GateResult` whose ``reason`` names every failing signature
        with an actionable explanation (``""`` when passed).

    Raises:
        ValueError: If an entry carries an invalid ``disposition`` value
            (checked for ALL entries before the gate branches - an invalid
            ruling must never fall into the non-blocking else), or two
            entries share a signature (ambiguous ruling; never silently
            overwrite the index).
    """
    by_signature: dict[str, DispositionEntry] = {}
    for entry in entries:
        _ensure_valid_disposition(entry.signature, entry.disposition)
        if entry.signature in by_signature:
            raise ValueError(f"duplicate dispositions entry for cluster signature {entry.signature!r}")
        by_signature[entry.signature] = entry

    failures: list[str] = []
    for signature, count in clusters.items():
        entry = by_signature.get(signature)
        if entry is None or entry.disposition == "":
            failures.append(
                f"undispositioned cluster still occurring "
                f"(fill disposition/root_cause/action in the dispositions file): {signature} ({count} occurrence(s))"
            )
        elif entry.disposition in _FIX_DISPOSITIONS:
            failures.append(
                f"cluster dispositioned {entry.disposition} still occurring "
                f"(the fix has not landed yet): {signature} ({count} occurrence(s))"
            )
    if failures:
        return GateResult(passed=False, exit_code=EXIT_VALIDATION_INCOMPLETE, reason="\n".join(failures))
    return GateResult(passed=True, exit_code=EXIT_VALIDATION_PASSED, reason="")
