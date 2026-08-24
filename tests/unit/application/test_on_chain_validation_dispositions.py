"""Unit tests for the dispositions file + validation exit gate (Task 4).

Plan: ``docs/history/plans/2026-08-18-on-chain-validation-harness.md``
(Task 4). Decision: PD-010 - divergent txs are grouped into discrepancy
clusters; each cluster is resolved by a user ruling in an APPEND-ONLY,
user-owned dispositions file (``on_chain_th_dispositions.toml``); the
harness appends one template ``[[clusters]]`` block per NEW signature and
never rewrites or deletes existing entries (Design Invariant 8).

Gate semantics (Design Invariant 7): exit
:data:`EXIT_VALIDATION_INCOMPLETE` (3) while any occurring cluster lacks a
ruling or carries a fix-type ruling (``missing_rule`` /
``incorrect_processing``) whose cluster still occurs; exit 0 only when
solely ``acceptable_difference`` clusters remain. A fix-type ruling whose
cluster has STOPPED occurring passes - the fix-landed assertion.

Fail-loud (Design Invariant 2, M1): malformed TOML raises ``ValueError``
chaining ``tomllib.TOMLDecodeError`` with the file path in the message and
no file modification; an invalid disposition value, a structurally invalid
block, or a duplicate-signature block also fails loudly (a silently
waved-through cluster is the harness's failure mode).

All signatures below are synthetic PII-free cluster-signature strings
(clustering Task 3 vocabulary; the plan's C7 gas-only example included).

Pinned behaviors (each test names its plan bullet):

1. ``test_missing_file_created_with_header`` - no file: creation with the
   explanatory header comment (and a valid comment-only TOML document).
2. ``test_new_signatures_appended_as_template`` - one NEW signature: an
   appended template block with empty ``disposition``/``root_cause``/
   ``action`` and ``first_seen`` from the passed ``today``.
3. ``test_append_only_preserves_existing_entries`` - a pre-filled entry's
   full text stays byte-unchanged after an append run; the already-present
   signature is skipped, not re-appended.
4. ``test_no_duplicate_append_across_runs`` - the same NEW signature on two
   consecutive runs yields exactly one block (first ``first_seen`` kept).
5. ``test_gate_undispositioned_fails`` - an occurring cluster with no entry
   (or an appended-but-unfilled template) fails with exit 3 and the
   signature named in the reason.
6. ``test_gate_fix_type_still_occurring_fails`` - ``missing_rule`` /
   ``incorrect_processing`` occurring clusters fail (parametrized).
7. ``test_gate_fix_type_absent_passes`` - a fix-type entry whose cluster
   does NOT occur passes (the fix-landed assertion).
8. ``test_gate_all_acceptable_passes`` - only ``acceptable_difference``
   occurrences pass.
9. ``test_malformed_toml_fails_loud`` - unparseable TOML: ``ValueError``
   chaining ``tomllib.TOMLDecodeError``, path in the message, no file
   modification (the append path fails BEFORE writing on the same file).

Extra edge guards (repo conventions: fail-loud, no silent overwrite):

10. ``test_invalid_cluster_blocks_fail_loud`` - invalid disposition value /
    missing ``signature`` / non-array ``clusters`` / duplicate-signature
    blocks: ``ValueError`` with the file path (parametrized).
11. ``test_evaluate_gate_rejects_invalid_and_duplicate_entries`` - the
    vocabulary and duplicate-key guards enforced on directly constructed
    entries too (no silent overwrite of the ruling index).
12. ``test_append_rejects_signature_that_would_corrupt_toml`` - a signature
    carrying ``"`` fails before any file write (format integrity).
"""

from __future__ import annotations

import tomllib
from datetime import date
from pathlib import Path

import pytest

from tax_reporting.application.on_chain_validation.dispositions import (
    EXIT_VALIDATION_INCOMPLETE,
    DispositionEntry,
    append_new_clusters,
    evaluate_gate,
    load_dispositions,
)

_TODAY = date(2026, 8, 19)
_TODAY_TEXT = "2026-08-19"
_SIG_GAS = "events=GasBurn|koinly=none|sender=unregistered|lp=false|fee=none|zero_display=false"
_SIG_NFT = "events=none|koinly=crypto_deposit/NFT|sender=unregistered|lp=false|fee=none|zero_display=false"


def _filled_block(
    signature: str,
    disposition: str,
    *,
    first_seen: str = _TODAY_TEXT,
    root_cause: str = "Koinly rounds the gas display to zero",
    action: str = "Accepted per the 2026-08-18 backlog ruling",
) -> str:
    """One user-filled ``[[clusters]]`` block (the shape the harness appends)."""
    return (
        "[[clusters]]\n"
        f'signature = "{signature}"\n'
        f'first_seen = "{first_seen}"\n'
        f'disposition = "{disposition}"\n'
        f'root_cause = "{root_cause}"\n'
        f'action = "{action}"\n'
    )


def _entry(signature: str, disposition: str) -> DispositionEntry:
    """A directly constructed entry (gate tests bypass the file)."""
    return DispositionEntry(
        signature=signature,
        first_seen=_TODAY_TEXT,
        disposition=disposition,
        root_cause="root cause" if disposition else "",
        action="action" if disposition else "",
    )


@pytest.mark.unit
class TestOnChainDispositions:
    """PD-010 dispositions-file and exit-gate pins."""

    def test_missing_file_created_with_header(self, tmp_path: Path) -> None:
        # Given - no dispositions file at all.
        path = tmp_path / "on_chain_th_dispositions.toml"

        # When - an append run with NO occurring signatures.
        appended = append_new_clusters(path, [], _TODAY)

        # Then - the file is created with the explanatory header comment and
        # nothing else: it parses as valid (comment-only) TOML with no blocks.
        assert appended == []
        text = path.read_text(encoding="utf-8")
        assert text.lstrip().startswith("#")
        assert "APPEND-ONLY" in text
        for ruling in ("missing_rule", "incorrect_processing", "acceptable_difference"):
            assert ruling in text
        assert load_dispositions(path) == []

    def test_new_signatures_appended_as_template(self, tmp_path: Path) -> None:
        # Given - one NEW cluster signature on a missing file.
        path = tmp_path / "on_chain_th_dispositions.toml"

        # When.
        appended = append_new_clusters(path, [_SIG_GAS], _TODAY)

        # Then - exactly the NEW signature is reported appended and the block
        # is the plan's template: first_seen from `today`, empty disposition
        # (NEW), empty root_cause/action, vocabulary comment in the raw text.
        assert appended == [_SIG_GAS]
        entries = load_dispositions(path)
        assert len(entries) == 1
        assert entries[0].signature == _SIG_GAS
        assert entries[0].first_seen == _TODAY_TEXT
        assert entries[0].disposition == ""
        assert entries[0].root_cause == ""
        assert entries[0].action == ""
        assert 'disposition = ""' in path.read_text(encoding="utf-8")

    def test_append_only_preserves_existing_entries(self, tmp_path: Path) -> None:
        # Given - a pre-filled (user-ruled) entry already on disk.
        path = tmp_path / "on_chain_th_dispositions.toml"
        path.write_text(_filled_block(_SIG_GAS, "acceptable_difference"), encoding="utf-8")
        original = path.read_bytes()

        # When - an append run carrying one NEW signature AND the existing one.
        appended = append_new_clusters(path, [_SIG_NFT, _SIG_GAS], _TODAY)

        # Then - only the NEW signature appends; the pre-existing text stays
        # BYTE-UNCHANGED as a prefix (append-only, never rewritten), and the
        # user's ruling survives intact.
        assert appended == [_SIG_NFT]
        assert path.read_bytes().startswith(original)
        entries = {entry.signature: entry for entry in load_dispositions(path)}
        assert entries[_SIG_GAS].disposition == "acceptable_difference"
        assert entries[_SIG_GAS].root_cause == "Koinly rounds the gas display to zero"
        assert entries[_SIG_NFT].disposition == ""

    def test_no_duplicate_append_across_runs(self, tmp_path: Path) -> None:
        # Given - the same NEW signature on two consecutive runs.
        path = tmp_path / "on_chain_th_dispositions.toml"
        assert append_new_clusters(path, [_SIG_GAS], date(2026, 8, 19)) == [_SIG_GAS]

        # When - the second run re-sees the same signature.
        assert append_new_clusters(path, [_SIG_GAS], date(2026, 9, 1)) == []

        # Then - exactly one block exists (keyed by its signature line - the
        # header comment legitimately mentions [[clusters]] too) and the
        # original first_seen is kept.
        text = path.read_text(encoding="utf-8")
        assert text.count(f'signature = "{_SIG_GAS}"') == 1
        entries = load_dispositions(path)
        assert len(entries) == 1
        assert entries[0].first_seen == "2026-08-19"

    def test_gate_undispositioned_fails(self) -> None:
        # Given - an occurring cluster with NO entry at all.
        result = evaluate_gate({_SIG_GAS: 3}, [])

        # Then - fail with exit 3, the signature named in an actionable reason.
        assert result.passed is False
        assert result.exit_code == EXIT_VALIDATION_INCOMPLETE
        assert _SIG_GAS in result.reason

        # And given - an appended-but-unfilled template block (empty ruling).
        template_result = evaluate_gate({_SIG_GAS: 3}, [_entry(_SIG_GAS, "")])

        # Then - equally undispositioned: fail with exit 3.
        assert template_result.passed is False
        assert template_result.exit_code == EXIT_VALIDATION_INCOMPLETE
        assert _SIG_GAS in template_result.reason

    @pytest.mark.parametrize("disposition", ["missing_rule", "incorrect_processing"])
    def test_gate_fix_type_still_occurring_fails(self, disposition: str) -> None:
        # Given - an occurring cluster carrying a fix-type ruling.
        result = evaluate_gate({_SIG_GAS: 2}, [_entry(_SIG_GAS, disposition)])

        # Then - fail with exit 3, naming both the signature and WHICH ruling
        # still blocks (the fix has not landed yet).
        assert result.passed is False
        assert result.exit_code == EXIT_VALIDATION_INCOMPLETE
        assert _SIG_GAS in result.reason
        assert disposition in result.reason

    def test_gate_fix_type_absent_passes(self) -> None:
        # Given - a fix-type entry whose cluster does NOT occur (fix landed).
        result = evaluate_gate({}, [_entry(_SIG_GAS, "missing_rule")])

        # Then - pass with exit 0 and no failure reason.
        assert result.passed is True
        assert result.exit_code == 0
        assert result.reason == ""

    def test_gate_all_acceptable_passes(self) -> None:
        # Given - only acceptable_difference rulings, both clusters occurring.
        entries = [_entry(_SIG_GAS, "acceptable_difference"), _entry(_SIG_NFT, "acceptable_difference")]

        # When.
        result = evaluate_gate({_SIG_GAS: 5, _SIG_NFT: 2}, entries)

        # Then - pass with exit 0.
        assert result.passed is True
        assert result.exit_code == 0
        assert result.reason == ""

    def test_malformed_toml_fails_loud(self, tmp_path: Path) -> None:
        # Given - unparseable TOML on disk.
        path = tmp_path / "on_chain_th_dispositions.toml"
        path.write_text('[[clusters]\nsignature = "oops"', encoding="utf-8")
        before = path.read_bytes()

        # Then - load fails loudly: ValueError chaining TOMLDecodeError, with
        # the file path in the message.
        with pytest.raises(ValueError, match="malformed dispositions TOML") as excinfo:
            load_dispositions(path)
        assert str(path) in str(excinfo.value)
        assert isinstance(excinfo.value.__cause__, tomllib.TOMLDecodeError)

        # And - the append path fails on the same malformed file BEFORE any
        # write, leaving the file byte-unchanged.
        with pytest.raises(ValueError, match="malformed dispositions TOML"):
            append_new_clusters(path, [_SIG_GAS], _TODAY)
        assert path.read_bytes() == before

    @pytest.mark.parametrize(
        ("content", "match"),
        [
            pytest.param(_filled_block(_SIG_GAS, "banana"), "invalid disposition", id="invalid-disposition-value"),
            pytest.param(
                '[[clusters]]\nfirst_seen = "2026-08-19"\n',
                "missing a non-empty 'signature'",
                id="missing-signature",
            ),
            pytest.param("clusters = 5\n", "array of tables", id="clusters-not-array-of-tables"),
            pytest.param(
                _filled_block(_SIG_GAS, "missing_rule") + _filled_block(_SIG_GAS, "acceptable_difference"),
                "duplicate cluster signature",
                id="duplicate-signature-blocks",
            ),
        ],
    )
    def test_invalid_cluster_blocks_fail_loud(self, tmp_path: Path, content: str, match: str) -> None:
        # Given - a structurally invalid but parseable dispositions document.
        path = tmp_path / "on_chain_th_dispositions.toml"
        path.write_text(content, encoding="utf-8")

        # Then - load fails loudly with the specific cause AND the file path.
        with pytest.raises(ValueError, match=match) as excinfo:
            load_dispositions(path)
        assert str(path) in str(excinfo.value)

    def test_evaluate_gate_rejects_invalid_and_duplicate_entries(self) -> None:
        # Given - directly constructed entries with an out-of-vocabulary ruling.
        with pytest.raises(ValueError, match="invalid disposition"):
            evaluate_gate({}, [_entry(_SIG_GAS, "banana")])

        # And given - two entries for the same signature (ambiguous ruling).
        with pytest.raises(ValueError, match="duplicate"):
            evaluate_gate({}, [_entry(_SIG_GAS, "missing_rule"), _entry(_SIG_GAS, "acceptable_difference")])

    def test_append_rejects_signature_that_would_corrupt_toml(self, tmp_path: Path) -> None:
        # Given - a signature carrying a double quote (would corrupt the TOML
        # basic-string rendering of the appended block).
        path = tmp_path / "on_chain_th_dispositions.toml"
        corrupt_signature = 'events=Say"Hi|koinly=none|sender=unregistered|lp=false|fee=none|zero_display=false'

        # Then - the append fails loudly BEFORE creating or writing the file.
        with pytest.raises(ValueError, match="cannot carry verbatim"):
            append_new_clusters(path, [corrupt_signature], _TODAY)
        assert not path.exists()

    @pytest.mark.parametrize(
        "control_character",
        ["\r", "\x00", "\x1f", "\x7f", "\t"],
        ids=["carriage-return", "nul", "unit-separator", "del", "tab"],
    )
    def test_append_rejects_control_characters_past_the_writer_guard(
        self, tmp_path: Path, control_character: str
    ) -> None:
        """A signature carrying an embedded CONTROL character (the full TOML
        basic-string forbidden set, not just ``\\n``) fails loudly BEFORE any
        write (review r1 F6): an appended block a Koinly Type/Tag cell fed a
        raw CR/NUL into would make the append-only file UNPARSEABLE, and every
        later run would raise at load until the user hand-edits the file the
        harness is forbidden to rewrite."""
        path = tmp_path / "on_chain_th_dispositions.toml"
        corrupt_signature = (
            f"events=Say{control_character}Hi|koinly=none|sender=unregistered|lp=false|fee=none|zero_display=false"
        )

        with pytest.raises(ValueError, match="cannot carry verbatim"):
            append_new_clusters(path, [corrupt_signature], _TODAY)
        assert not path.exists(), "the guard must fire before the file is created or appended to"
