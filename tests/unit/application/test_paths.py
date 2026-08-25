"""Direct tests for the shared repository-root helper (review r2 F6).

Every consumer test monkeypatches :func:`find_repository_root` away, so the
module's two documented behaviors (cwd-independent ``__file__``-anchored
resolution; fail-loud ``RuntimeError`` when ``.git`` is unreachable) were
unpinned. These tests invoke the REAL function.
"""

from __future__ import annotations

import pytest


@pytest.mark.unit
class TestFindRepositoryRoot:
    """Pin the public root-resolution helper's contract."""

    def test_root_resolution_is_cwd_independent(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        """The anchor is ``__file__`` (this source tree), never ``Path.cwd()``.

        Chdir to a directory OUTSIDE the repository (the classic mistake the
        promotion to ``application.paths`` was meant to make impossible: an
        implementation switching to ``Path.cwd()`` would resolve the tmp dir
        and fail/return the wrong root); the real function must still resolve
        THIS repository's root.
        """
        from tax_reporting.application.paths import find_repository_root

        monkeypatch.chdir(tmp_path)

        root = find_repository_root()

        assert (root / ".git").exists()
        assert root != tmp_path

    def test_raises_outside_repository(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        """Fail loud with ``RuntimeError`` when no ``.git`` is reachable.

        The module resolves from ``Path(__file__)``; the exposed seam for a
        non-repo location is the module-level ``Path`` name (monkeypatched to
        a file inside the tmp tree, which has no ``.git`` up its parent
        chain).
        """
        from tax_reporting.application import paths

        real_path = paths.Path
        monkeypatch.setattr(
            paths, "Path", lambda _ignored: real_path(tmp_path / "not_a_repo.py")
        )

        with pytest.raises(RuntimeError, match=r"\.git"):
            paths.find_repository_root()
