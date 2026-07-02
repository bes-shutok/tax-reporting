"""Guarded JSON loader shared by all token/label config loaders.

Centralizes the mechanical file guards that previously were duplicated (with
deliberately different degrade-vs-raise policies) across three callers:

- symlink rejection (``path.is_symlink()``),
- existence check (``path.exists()``),
- strict size cap via ``path.stat().st_size`` (exactly ``size_limit`` passes;
  ``> size_limit`` is rejected),
- ``json.load`` of the file contents.

Policy is **not** owned here. Per the established guidance ("when reusing
a validation/security pattern, inherit the guards but recalibrate exception
handling"), the helper delegates every failure to a caller-supplied
``on_error(path, kind, detail)`` callback and returns whatever that callback
returns (or propagates its raise). The helper itself never decides
degrade-vs-raise and never logs. ``kind`` is a stable token from the closed set
``{"symlink", "missing", "oversize", "stat_error", "invalid_json"}``.

``DEGRADED`` is a single shared sentinel that an ``on_error`` returns to signal
"degrade". It is a dedicated ``object()`` instance, NOT ``None``, because a
legitimately-parsed JSON ``null`` is returned from ``json.load`` as ``None`` and
must stay distinguishable from a degrade (a caller's not-a-dict shape check
should still reject a ``null`` file rather than treating it as silent
degradation). The helper performs NO shape validation: a valid JSON object,
list, scalar, or ``null`` is returned from ``json.load`` as-is; schema checks
remain caller-owned (Invariant 7).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

# Dedicated sentinel an on_error returns to signal "degrade". Distinct from a
# parsed JSON null (which json.load returns as None) so callers' shape checks
# can still reject a null-valued file instead of mistaking it for a degrade.
DEGRADED: object = object()


def load_guarded_json(
    path: Path,
    *,
    size_limit: int,
    on_error: Callable[[Path, str, str], object],
) -> object:
    """Load JSON from ``path`` after mechanical guards, delegating failures.

    Runs, in order: symlink reject -> existence -> strict size cap ->
    ``json.load``. On each failure, calls ``on_error(path, kind, detail)`` and
    returns its result (or propagates its raise). This helper never raises and
    never logs; policy (degrade-vs-raise, message wording) lives entirely in
    ``on_error``.

    Args:
        path: File to load.
        size_limit: Maximum allowed file size in bytes. A file of exactly this
            size passes; strictly larger files are rejected.
        on_error: Callback ``(path, kind, detail) -> object`` invoked on every
            failure. ``kind`` is from the closed set ``{"symlink", "missing",
            "oversize", "stat_error", "invalid_json"}``.

    Returns:
        The parsed JSON value (object/list/scalar/None) on success, or whatever
        ``on_error`` returns on failure (commonly ``DEGRADED``).
    """
    # Invariant 8: symlink is checked BEFORE existence so a dangling symlink
    # reports "symlink" rather than "missing".
    if path.is_symlink():
        return on_error(path, "symlink", "config file path is a symlink, refusing to follow")

    if not path.exists():
        return on_error(path, "missing", "config file not found")

    try:
        file_size = path.stat().st_size
    except OSError as exc:
        return on_error(path, "stat_error", str(exc))

    # Strict: exactly size_limit passes; only strictly larger files are rejected.
    if file_size > size_limit:
        return on_error(path, "oversize", f"{file_size} bytes, max {size_limit} bytes")

    try:
        with path.open("r", encoding="utf-8") as fh:
            # Returned as-is; no shape validation (Invariant 7). A parsed null
            # yields None, which is NOT DEGRADED.
            return json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        return on_error(path, "invalid_json", str(exc))
