"""Guard: on-chain tests must never open gitignored personal data at runtime.

AGENTS.md crypto-tests rule requires tests to read only committed synthetic
data under ``resources/source/example/``; the gitignored personal data at
``resources/source/2025/`` (real Koinly exports, the real Berachain contract
registry / LP snapshot) and ``resources/result/2025/`` (the real
``bera_transactions.csv``) must never be opened by a test.

This was a latent defect: the on-chain e2e tests passed only because the real
``resources/source/2025/berachain_contracts.json`` +
``berachain_lp_snapshot.json`` happened to exist on the author's disk; on a
fresh clone (where those paths are absent - they are gitignored) the opted-in
path raised ``FileProcessingError``. The fix (``main._resolve_registry_path``
with an ``example/`` fallback + tests injecting the example paths via the
``contracts_path`` / ``lp_snapshot_path`` kwargs) closed it; this test pins it
via a Python audit hook that fails if any on-chain test opens a forbidden path.

Performance: the audit runs all guarded modules in a SINGLE subprocess (one
spawn, not one per module) because ``sys.addaudithook`` is process-global and
cannot be cleanly removed once installed.

Contract (2026-08-16 test-hermeticity plan, Design Invariant 3): the guard is
ALWAYS ON - it runs on every default ``uv run pytest`` invocation (fail-closed:
absent environment means the guard runs). The only opt-out is an explicit
``SKIP_AUDIT_GUARD=1``, mirroring the documented ``-m "not slow"`` explicit
deselection pattern: skipping must be named, never silent.
``RUN_AUDIT_GUARD=1`` (the pre-promotion opt-in gate) is still accepted as a
no-op alias so invocations recorded in archived completed-plan docs do not
error; it no longer selects anything special.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _is_forbidden_open(path_str: str, project_root: Path) -> bool:
    """Year-agnostic predicate: forbid opening gitignored personal data.

    Returns True when ``path_str`` resolves to a path under
    ``resources/source/<segment>/`` or ``resources/result/<segment>/`` where
    ``<segment>`` is anything OTHER than ``example``. This catches personal
    data for ANY year (``2024``, ``2025``, ``2026``, ...) while allowing the
    committed synthetic data under ``resources/source/example/<year>/`` and
    ``resources/result/example/`` (AGENTS.md crypto-tests rule).

    Paths that cannot be resolved relative to ``project_root`` (outside the
    repo tree, or already-relative paths that do not start with ``resources/``)
    are allowed: the guard only concerns in-repo personal-data reads.
    """
    try:
        rel = Path(path_str).resolve().relative_to(project_root.resolve())
    except (ValueError, OSError):
        # Outside project_root (e.g. stdlib/site-packages) -> allow.
        return False
    parts = rel.parts
    if len(parts) < 3:
        return False
    return (
        parts[0] == "resources"
        and parts[1] in ("source", "result")
        and parts[2] != "example"
    )


# On-chain test modules whose runtime file opens we guard. Discovered by glob so
# new on-chain / bera test modules are picked up automatically. Deduped + sorted
# STRINGS (glob results are absolute; the explicit _main callers below are
# repo-relative — the probe subprocess runs with cwd=_PROJECT_ROOT, so both
# resolve). The guard test module itself is excluded: spawning it would recurse.
#
# 2026-08-16 hermeticity incident: tests calling production ``_main`` inherit
# the DI-3 env gate and, when the developer shell exports ``BERA_CHAIN_API_KEY``
# (env-pin did not exist yet), performed a live fetch that opened the
# gitignored real wallet registry under ``resources/source/<year>/``. These two
# verified ``_main`` callers match neither glob, so they are guarded explicitly.
# ``tests/unit/application/test_main_koinly_directory.py`` is deliberately NOT
# added: an early grep matched only its ``via_main(`` test NAME; the file was
# verified not to call ``_main``.
_MAIN_CALLER_EXPLICIT_PATHS = (
    "tests/unit/test_cli.py",
    "tests/unit/application/test_crypto_reporting.py",
)

_ON_CHAIN_TEST_PATHS = sorted(
    {
        str(p)
        for pattern in (
            "tests/**/test_*on_chain*.py",
            "tests/**/test_*bera*.py",
        )
        for p in _PROJECT_ROOT.glob(pattern)
        if p.resolve() != Path(__file__).resolve()
    }
    | set(_MAIN_CALLER_EXPLICIT_PATHS)
)

# The probe script installs ONE file-open audit hook, runs ALL guarded modules
# in a single pytest session, and prints the forbidden paths it saw plus the
# per-module exit codes. One subprocess (not one per module) keeps spawn cost
# O(1) instead of O(N_modules).
#
# The hook mirrors the module-level ``_is_forbidden_open`` predicate: a
# year-agnostic path-shape check anchored at ``project_root``. ``project_root``
# is passed in (the subprocess does not inherit Python variables) so the shape
# check resolves opened paths relative to the same root the driver uses.
_PROBE = """
import sys
from pathlib import Path
project_root = Path(sys.argv[1])
modules = sys.argv[2:]
hits = []
def _is_forbidden(path_str):
    try:
        rel = Path(path_str).resolve().relative_to(project_root.resolve())
    except (ValueError, OSError):
        return False
    parts = rel.parts
    if len(parts) < 3:
        return False
    return parts[0] == 'resources' and parts[1] in ('source', 'result') and parts[2] != 'example'
def hook(event, args):
    if event == 'open':
        if _is_forbidden(str(args[0])):
            hits.append(str(args[0]))
sys.addaudithook(hook)
import pytest
rc = pytest.main(modules + ['-q', '-p', 'no:cacheprovider'])
print('AUDIT_HITS=' + chr(1).join(sorted(set(hits))))
print('AUDIT_RC=' + str(rc))
"""


def _audit_guard_skip_reason() -> str | None:
    """Explicit-deselection gate for the probe tests (fail-closed, Design Invariant 3).

    Returns a skip reason ONLY when the user explicitly set ``SKIP_AUDIT_GUARD=1``
    (mirrors the documented ``-m "not slow"`` named deselection: skipping must
    be explicit, never silent). An absent environment returns ``None``: the
    guard runs. ``RUN_AUDIT_GUARD=1`` (the pre-promotion opt-in gate) is
    intentionally unread here: after the 2026-08-16 promotion it is a no-op
    alias kept so invocations recorded in archived completed-plan docs do not
    error; it no longer selects anything special.
    """
    if os.environ.get("SKIP_AUDIT_GUARD") == "1":
        return (
            "audit guard explicitly deselected via SKIP_AUDIT_GUARD=1 "
            "(mirrors '-m \"not slow\"' explicit deselection); absent env => guard runs"
        )
    return None


# SKIP_AUDIT_GUARD gate, expressed once at module level (the gate depends only
# on process-start environment, so every test in this module shares it; a new
# probe test cannot forget the opt-out).
_SKIP_REASON = _audit_guard_skip_reason()
pytestmark = pytest.mark.skipif(
    _SKIP_REASON is not None,
    reason=_SKIP_REASON or "audit guard enabled",
)


def _run_audit_probe(
    probe_dir: Path, modules: list[str]
) -> tuple[list[str], str, subprocess.CompletedProcess[str]]:
    """Spawn ONE probe subprocess that runs ``modules`` under the open-audit hook.

    Returns ``(hits, rc, result)``: ``hits`` is the deduped sorted list of
    forbidden paths the audit hook saw, ``rc`` is the probe's inner pytest exit
    code as a string, and ``result`` exposes raw stdout/stderr for failure
    messages. ``modules`` are repo-relative or absolute test-module paths; the
    subprocess runs with ``cwd=_PROJECT_ROOT`` so relative forbidden opens
    resolve against the project root.

    The probe script is written under ``probe_dir``, a per-invocation unique
    temp directory (``tmp_path_factory.mktemp``): a fixed shared path would let
    one pytest session's cleanup unlink the script while a concurrent session
    (two terminals on the same clone) is still executing it. Each session owns
    its probe file; pytest removes the temp dir tree at session end.
    """
    probe = probe_dir / "_probe_personal_data.py"
    probe.write_text(_PROBE)
    result = subprocess.run(  # noqa: S603 (probe is our own trusted script; inputs are project_root + test paths under tests/ or tmp_path)
        [sys.executable, str(probe), str(_PROJECT_ROOT), *modules],
        cwd=_PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    stdout = result.stdout.splitlines()
    hits_line = next((ln for ln in stdout if ln.startswith("AUDIT_HITS=")), "AUDIT_HITS=")
    rc_line = next((ln for ln in stdout if ln.startswith("AUDIT_RC=")), "AUDIT_RC=unknown")
    hits = [h for h in hits_line[len("AUDIT_HITS="):].split("\x01") if h]
    rc = rc_line[len("AUDIT_RC="):]
    return hits, rc, result


@pytest.mark.unit
class TestOnChainTestsNoPersonalData:
    """On-chain test modules must not open gitignored personal data."""

    @pytest.mark.parametrize(
        ("path_str", "project_root", "expected"),
        [
            # Forbidden: any year-segment under resources/source/<year>/ (not example).
            ("resources/source/2025/berachain_contracts.json", None, True),
            ("resources/source/2025/koinly/transaction_history.csv", None, True),
            ("resources/source/2026/berachain_contracts.json", None, True),
            ("resources/source/2024/koinly/x.csv", None, True),
            ("resources/source/2099/anything.json", None, True),
            # Forbidden: resources/result/<year>/ (real bera_transactions.csv etc.).
            ("resources/result/2025/bera_transactions.csv", None, True),
            ("resources/result/2026/bera_transactions.csv", None, True),
            # ALLOWED: committed synthetic data under resources/source/example/<year>/.
            ("resources/source/example/2025/berachain_contracts.json", None, False),
            ("resources/source/example/2025/koinly/transaction_history.csv", None, False),
            ("resources/source/example/koinly2024/x.csv", None, False),
            ("resources/result/example/x.csv", None, False),
            # ALLOWED: paths outside resources/, or short resources paths (< 3 parts).
            ("tests/unit/test_x.py", None, False),
            ("src/tax_reporting/main.py", None, False),
            ("resources/ib_export.csv", None, False),
            # ALLOWED: the guard test module itself (it must not flag its own source).
            ("tests/unit/test_on_chain_tests_no_personal_data.py", None, False),
        ],
    )
    def test_is_forbidden_open_predicate_year_agnostic(
        self, path_str: str, project_root: Path | None, expected: bool
    ) -> None:
        """The year-agnostic predicate forbids any resources/(source|result)/<seg>/ that is not example/."""
        root = project_root if project_root is not None else _PROJECT_ROOT
        assert _is_forbidden_open(path_str, root) is expected

    def test_guard_catches_personal_data_any_year(self, tmp_path: Path) -> None:
        """A synthetic resources/source/2026/ read must be caught (year-agnostic guard).

        Regression for F10: the old literal-2025 prefix list let a 2026 (or any
        non-2025 year) personal-data read pass silently. The year-agnostic
        predicate must catch ANY year-segment under resources/source/<seg>/ (or
        resources/result/<seg>/) that is not example/.

        Uses the pure helper directly (no subprocess, no real 2026 file left in
        the repo tree) so the test is deterministic and side-effect free.
        """
        synthetic = tmp_path / "resources" / "source" / "2026" / "berachain_contracts.json"
        assert _is_forbidden_open(str(synthetic), tmp_path) is True
        # And the committed-example analog stays allowed:
        allowed = tmp_path / "resources" / "source" / "example" / "2026" / "berachain_contracts.json"
        assert _is_forbidden_open(str(allowed), tmp_path) is False

    def test_on_chain_modules_do_not_open_personal_data(self, tmp_path_factory: pytest.TempPathFactory) -> None:
        """Assert no guarded on-chain test module opens a forbidden personal-data file.

        Runs all guarded modules in ONE subprocess under a ``sys.addaudithook``
        file-open audit. Fails if any forbidden path was opened, or if any
        module itself failed (a failing module makes the audit meaningless).

        Always-on (fail-closed, Design Invariant 3): the probe runs on every
        default ``uv run pytest`` invocation; an absent environment means the
        guard runs. The only opt-out is an explicit ``SKIP_AUDIT_GUARD=1``
        (mirrors the documented ``-m "not slow"`` explicit deselection), applied
        once at module level via ``pytestmark``. ``RUN_AUDIT_GUARD=1`` is
        accepted as a no-op alias so invocations recorded in archived completed
        plan docs do not error.
        """
        probe_dir = tmp_path_factory.mktemp("audit_probe")
        hits, rc, result = _run_audit_probe(probe_dir, _ON_CHAIN_TEST_PATHS)

        assert not hits, (
            "An on-chain test module opened gitignored personal data (AGENTS.md "
            f"crypto-tests rule violated): {hits}. The on-chain registry path "
            "resolution must inject the committed example/ path, not the per-user real one."
        )
        assert rc == "0", (
            f"A guarded on-chain test module failed (rc={rc}); stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )

    def test_synthetic_forbidden_open_detected(
        self, tmp_path: Path, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        """Positive control: a module-body open of a forbidden path must land in AUDIT_HITS.

        Writes a tiny synthetic module to ``tmp_path`` at RUNTIME and runs the
        probe subprocess on it (single subprocess, absolute ``tmp_path``
        argument). The module body calls ``open("resources/source/2099/synthetic.json")``:
        the open does NOT need to succeed - the audit event fires on the attempt
        - and the resulting module-body failure surfaces as a pytest collection
        error, so ``AUDIT_RC`` is NONZERO (2) by design. The assertion therefore
        targets ``AUDIT_HITS`` only and must never assert ``rc == 0`` here.

        The synthetic module must NEVER be committed under ``tests/``: it would
        pollute default collection, and a glob-matching name would make the
        always-on probe permanently flag its own synthetic violation (a
        permanently red suite). It exists only transiently under ``tmp_path``.
        """
        victim = tmp_path / "test_synthetic_forbidden_open_victim.py"
        victim.write_text('open("resources/source/2099/synthetic.json")\n')

        probe_dir = tmp_path_factory.mktemp("audit_probe")
        hits, _rc, _result = _run_audit_probe(probe_dir, [str(victim)])

        assert "resources/source/2099/synthetic.json" in hits, (
            "the probe did not report the synthetic forbidden open in AUDIT_HITS; "
            "the audit hook installation or the AUDIT_HITS parsing is broken"
        )
