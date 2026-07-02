"""Conformance tests for the two-layer lessons corpus model.

This module pins two independent invariants of the lessons-corpus design
(see plan ``docs/history/plans/2026-06-29-lessons-corpus-derived-index.md``,
Task 3):

1. **User-level corpus (strict).** The shared ``development_lessons.md``
   resolved from ``shared_docs_dir`` (the *lowercase* facts key, never an
   env var) passes the read-only ``lessons_index.py`` gate and is non-empty.
   The gate is invoked via ``subprocess`` (no import of the user-level
   script); the runtime path is resolved from ``LESSONS_INDEX_SCRIPT`` with
   a default of ``${HOME}/.ai-playbook/scripts/lessons_index.py``. This test
   skips when either the gate script or the corpus file is absent, so it only
   runs where the playbook convention is actually installed.

2. **Project-file independence (convention).** The repo's
   ``docs/maintenance/development_lessons.md`` is plain markdown that stays
   valid with no skill, gate, or user corpus present: contiguous ``#N``
   headings and no coupling to the gate or the user-corpus ``UL#`` namespace.
   This is a pure-file assertion and always runs.

Gate-BEHAVIOR tests (duplicate / malformed-tag / fenced-pseudo-tag / taxonomy
table) do NOT live here: they are co-located with the gate as the in-memory
``--selftest`` of ``lessons_index.py`` in the ai-playbook repo. This module
keeps only the two project-relevant invariants above.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

# --------------------------------------------------------------------------- #
# Path constants.
# --------------------------------------------------------------------------- #
_REPO_ROOT = Path(__file__).resolve().parents[2]
_PROJECT_LESSONS = _REPO_ROOT / "docs" / "maintenance" / "development_lessons.md"


def _resolve_runtime_script() -> Path:
    """Resolve the gate script path from ``LESSONS_INDEX_SCRIPT`` (default
    ``${HOME}/.ai-playbook/scripts/lessons_index.py``). Does NOT verify the
    file exists; callers decide skip-vs-fail when it is absent.
    """
    return Path(
        os.environ.get(
            "LESSONS_INDEX_SCRIPT",
            str(Path.home() / ".ai-playbook" / "scripts" / "lessons_index.py"),
        )
    )


def _resolve_shared_docs_dir() -> Path | None:
    """Resolve ``shared_docs_dir`` by PARSING the lowercase facts key.

    ``SHARED_DOCS_DIR`` is never an exported env var (r3 Blocker B2); the
    value lives in ``.ai-playbook/facts.md`` as a markdown table row:

        | `shared_docs_dir` | ~/Projects/.ai-playbook/ | <description> |

    The facts file is searched repo-first (``<repo>/.ai-playbook/facts.md``)
    then user-home (``~/.ai-playbook/facts.md``). The value is tilde-prefixed
    and is expanded. Returns ``None`` if no facts file declares the key.

    The regex REQUIRES both backtick wrappers around the value cell. The facts
    file also has prose rows that mention ``shared_docs_dir`` in their
    description (where the value cell is plain text, not code); requiring the
    wrappers excludes those so the match is order-independent and only the
    canonical path row is captured.
    """
    # The facts file stores the key and its value both inline-code-wrapped
    # (`` `shared_docs_dir` `` and `` `~/Projects/.ai-playbook/` ``). Require
    # the value wrappers (no ``?``) so prose rows whose value cell is not
    # code-wrapped are not matched.
    pattern = re.compile(r"^\|\s*`shared_docs_dir`\s*\|\s*`([^|`]+?)`\s*\|", re.MULTILINE)
    for facts_path in (
        _REPO_ROOT / ".ai-playbook" / "facts.md",
        Path.home() / ".ai-playbook" / "facts.md",
    ):
        if not facts_path.is_file():
            continue
        match = pattern.search(facts_path.read_text(encoding="utf-8"))
        if match:
            # ``Path`` collapses any trailing slash on the facts value (e.g.
            # ``~/Projects/.ai-playbook/``) so the later
            # ``<dir>/development_lessons.md`` join does not double the
            # separator.
            return Path(match.group(1).strip()).expanduser().resolve()
    return None


def _run_gate(gate_script: Path, corpus_path: Path) -> subprocess.CompletedProcess[str]:
    """Invoke the read-only gate via subprocess; never import the script.

    The interpreter is the absolute ``sys.executable`` (no PATH lookup) and
    both arguments are trusted test inputs (the gate path resolved by the
    caller and a corpus path under our control), so the bandit S603 subprocess
    check does not apply.
    """
    return subprocess.run(  # noqa: S603 - trusted interpreter + args (see docstring)
        [sys.executable, str(gate_script), str(corpus_path)],
        check=False,
        capture_output=True,
        text=True,
    )


class TestLessonsCorpusConformance:
    """Strict user-corpus gate + project-file independence invariants."""

    # ------------------------------------------------------------------ #
    # User-corpus strict gate (the live cross-project authority).
    # ------------------------------------------------------------------ #
    def test_gate_passes_user_corpus(self) -> None:
        gate_script = _resolve_runtime_script()
        if not gate_script.is_file():
            pytest.skip(
                f"lessons_index.py gate script not found at {gate_script}; install "
                "it from the ai-playbook repo (scripts/lessons_index.py synced to "
                "~/.ai-playbook/scripts/)"
            )
        shared_docs_dir = _resolve_shared_docs_dir()
        assert shared_docs_dir is not None, (
            "could not resolve shared_docs_dir from .ai-playbook/facts.md (lowercase key); set it in the facts file"
        )
        corpus_path = shared_docs_dir / "development_lessons.md"
        if not corpus_path.is_file():
            pytest.skip(
                f"user-level corpus absent at {corpus_path}; playbook not cloned "
                "or convention not adopted at user level yet (run lessons-migrate "
                "to seed it)"
            )
        # Non-empty sanity check BEFORE trusting the exit code: the gate prints
        # ``OK: 0 lessons validated`` with exit 0 on an empty or whitespace-only
        # corpus, so a returncode-only assertion would pass vacuously on a stale
        # or truncated corpus file.
        corpus_text = corpus_path.read_text(encoding="utf-8")
        assert re.search(r"^## \d+\.", corpus_text, re.MULTILINE), (
            f"user-level corpus at {corpus_path} has no numbered lesson headings; "
            "a stale/empty file would pass the gate vacuously"
        )
        result = _run_gate(gate_script, corpus_path)
        assert result.returncode == 0, (
            f"user-level corpus failed the strict gate:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )

    # ------------------------------------------------------------------ #
    # Project-file independence (convention layer).
    # ------------------------------------------------------------------ #
    def test_project_file_independence(self) -> None:
        """The project file is plain markdown: contiguous ``#N`` and no
        gate/corpus coupling. Pure-file assertion, always runs.
        """
        assert _PROJECT_LESSONS.is_file(), f"project lessons file missing: {_PROJECT_LESSONS}"
        text = _PROJECT_LESSONS.read_text(encoding="utf-8")

        # Contiguous numbering 1..N (mirrors Validation Command 7). NOTE: this
        # regex is fence-unaware by design: the project file is a convention
        # layer (not gate-parsed) and currently has no fenced pseudo-headings,
        # so a ``## 99.`` inside a code fence would corrupt this list. The
        # gate's own fence-aware parser is the authority for the strict
        # user-level corpus; this check only guards the project file's shape.
        numbers = [int(m) for m in re.findall(r"^## (\d+)\.", text, re.MULTILINE)]
        expected = list(range(1, len(numbers) + 1))
        if numbers != expected:
            present = set(numbers)
            max_seen = numbers[-1] if numbers else 0
            missing = [n for n in range(1, max_seen + 1) if n not in present]
            pytest.fail(
                "non-contiguous #N in project file: "
                f"count={len(numbers)}, first={numbers[:5]}, last={numbers[-5:]}, "
                f"missing={missing}"
            )

        # Independence: no coupling to the gate or the user-corpus namespace.
        assert "lessons_index" not in text, (
            "project file couples to the gate (lessons_index) - it must be "
            "valid plain markdown with no skill/gate/corpus dependency"
        )
        assert "UL#" not in text, (
            "project file couples to the user-corpus UL# namespace - project "
            "instructions cite project #N only (within-layer references)"
        )
