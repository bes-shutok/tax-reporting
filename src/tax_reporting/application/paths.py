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
) -> Path:
    """Resolve a per-year on-chain registry file path with example fallback.

    Shared resolution helper (extracted from the TH substituter so the
    fetcher resolves the position-token registry the same way; homed here
    generic per-year resource-path resolution with nothing
    fetcher-specific). Logs via this module's logger (no
    caller-threaded logger - both INFO messages concern the resolution
    itself, so caller identity adds nothing).

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
        _LOGGER.info("Using injected on-chain registry path for %s: %s", filename, override)
        return override
    primary = repo_root / "resources" / "source" / str(year) / filename
    if primary.is_file():
        return primary
    fallback = repo_root / "resources" / "source" / "example" / str(year) / filename
    _LOGGER.info(
        "No per-user %s at %s; falling back to committed example at %s.",
        filename,
        primary,
        fallback,
    )
    return fallback
