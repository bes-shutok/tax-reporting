"""Shared repository-path helpers (application level).

Two helpers live here (``find_repository_root`` was promoted to a
module-level helper; ``resolve_registry_path`` moved here from the on-chain fetcher,
where its home forced cross-feature imports): several application features
(crypto classification, on-chain config, the on-chain fetcher, the TH
substitution service) need the repository root or per-year registry-path
resolution, and importing one feature module's name from another feature
module couples their refactorings. Keep this module dependency-free so any
layer can import it without cycle risk.
"""

from __future__ import annotations

import logging
from pathlib import Path

__all__ = ["find_repository_root", "resolve_registry_path"]

_LOGGER = logging.getLogger(__name__)


def find_repository_root() -> Path:
    """Find the repository root by searching for the ``.git`` directory.

    Returns:
        Path to the repository root directory.

    Raises:
        RuntimeError: If the ``.git`` directory cannot be found (not inside
            a git repository).
    """
    current = Path(__file__).resolve()
    # Search up from the current file location, max 10 levels to avoid
    # infinite loops.
    for _ in range(10):
        if (current / ".git").exists():
            return current
        current = current.parent
    raise RuntimeError(
        "Cannot find repository root (.git directory not found). "
        "This function must be run within a git repository."
    )


def resolve_registry_path(
    year: int,
    filename: str,
    override: Path | None,
    repo_root: Path,
    *,
    shadow_is_data_loss: bool = False,
) -> Path:
    """Resolve a per-year on-chain registry file path with example fallback.

    Shared resolution helper (extracted from the TH substituter so the
    fetcher resolves the position-token registry the same way; homed here
    generic per-year resource-path resolution with nothing
    fetcher-specific). Logs via this module's logger (no
    caller-threaded logger - all messages concern the resolution
    itself, so caller identity adds nothing).

    Resolution order (first match wins):
    1. ``override`` (explicit path injected by tests - points at the committed
       ``example/`` template so tests never read gitignored personal data,
       per AGENTS.md crypto-tests rule).
    2. ``resources/source/<year>/<filename>`` (the per-user override; gitignored,
       so absent on a fresh clone).
    3. ``resources/source/example/<year>/<filename>`` (the committed template;
       always present, so the opted-in path works out of the box).

    Logs INFO on the override and fallback legs. The per-user primary leg
    logs INFO by default (the per-user file is the designed production
    source; the committed example is a template). Callers passing
    ``shadow_is_data_loss=True`` - registries whose committed file is
    CANONICAL, so a partial per-user file shadows (fully replaces) it and
    silently drops committed entries - get a WARNING with the
    copy-and-append hint instead.
    """
    if override is not None:
        _LOGGER.info("Using injected on-chain registry path for %s: %s", filename, override)
        return override
    primary = repo_root / "resources" / "source" / str(year) / filename
    if primary.is_file():
        # The per-user file SHADOWS (fully replaces) the committed file:
        # a partial override silently drops committed entries, so the run
        # itself must say which registry was used.
        if shadow_is_data_loss:
            _LOGGER.warning(
                "Using per-user on-chain registry %s (fully replaces the committed "
                "registry): %s - committed entries not present in this file are "
                "dropped for this run; copy the committed file and append your "
                "entries to keep them",
                filename,
                primary,
            )
        else:
            _LOGGER.info(
                "Using per-user on-chain registry %s: %s",
                filename,
                primary,
            )
        return primary
    fallback = repo_root / "resources" / "source" / "example" / str(year) / filename
    _LOGGER.info(
        "No per-user %s at %s; falling back to committed example at %s.",
        filename,
        primary,
        fallback,
    )
    return fallback
