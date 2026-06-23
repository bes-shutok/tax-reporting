"""Direct unit tests for the guarded JSON loader.

These tests pin the contract of ``load_guarded_json`` and the ``DEGRADED``
sentinel before the production module
``src/tax_reporting/infrastructure/json_loader.py`` exists (RED phase).
Task 4 will implement the helper; the assertions below encode its design
invariants (plan ``2026-06-21-crypto-payment-proceeds-refactor.md``):

- Signature: ``load_guarded_json(path, *, size_limit, on_error) -> object``.
- The helper performs mechanical guards only: symlink reject -> existence ->
  ``stat()`` size cap -> ``json.load``. It NEVER decides degrade-vs-raise
  and NEVER logs; it calls ``on_error(path, kind, detail)`` and surfaces the
  handler's result (or propagates its raise).
- ``kind`` is a stable token from the closed set
  ``{"symlink", "missing", "oversize", "stat_error", "invalid_json"}``.
- ``DEGRADED`` is an exported module-level ``object()`` distinct from a
  legitimately-parsed JSON ``null`` (Invariant 4/6).
- Symlink is checked BEFORE existence (a dangling symlink reports
  ``"symlink"``, not ``"missing"``); size check is strict ``> size_limit``
  (exactly ``size_limit`` passes) (Invariant 8).
- Shape validation stays caller-owned: a valid JSON list is returned as-is
  (Invariant 7).
"""

import json
from pathlib import Path

import pytest

from tax_reporting.domain.exceptions import FileProcessingError
from tax_reporting.infrastructure.json_loader import DEGRADED, load_guarded_json

_CLOSED_KIND_SET = {"symlink", "missing", "oversize", "stat_error", "invalid_json"}


@pytest.mark.unit
class TestLoadGuardedJson:
    """Direct tests for the guarded JSON loader and the DEGRADED sentinel."""

    def test_valid_json_returned_parsed(self, tmp_path: Path):
        # Given - a real, well-formed JSON file
        path = tmp_path / "cfg.json"
        payload = {"tokens": {"stablecoins": ["USDT"]}}
        path.write_text(json.dumps(payload), encoding="utf-8")

        recorder: list[tuple[Path, str, str]] = []

        def on_error(p: Path, kind: str, detail: str) -> object:  # noqa: ARG001
            recorder.append((p, kind, detail))
            return DEGRADED

        # When
        result = load_guarded_json(path, size_limit=1024, on_error=on_error)

        # Then - parsed object returned unchanged; on_error never called
        assert result == payload
        assert recorder == []

    def test_parsed_null_is_returned_not_degraded(self, tmp_path: Path):
        # Given - a file whose JSON content is `null`
        path = tmp_path / "null.json"
        path.write_text("null", encoding="utf-8")

        def on_error(p: Path, kind: str, detail: str) -> object:  # noqa: ARG001
            raise AssertionError(f"on_error must not be called for parsed null, got kind={kind}")

        # When
        result = load_guarded_json(path, size_limit=1024, on_error=on_error)

        # Then - a parsed null is None, NOT the DEGRADED sentinel (Invariant 4/6)
        assert result is None
        assert result is not DEGRADED

    def test_symlink_calls_on_error_symlink(self, tmp_path: Path):
        # Given - path is a symlink (to a real target)
        target = tmp_path / "real.json"
        target.write_text("{}", encoding="utf-8")
        link = tmp_path / "link.json"
        link.symlink_to(target)

        recorded: dict[str, object] = {}

        def on_error(p: Path, kind: str, detail: str) -> object:
            recorded["path"] = p
            recorded["kind"] = kind
            recorded["detail"] = detail
            return "sentinel-result"

        # When
        result = load_guarded_json(link, size_limit=1024, on_error=on_error)

        # Then - on_error invoked with kind "symlink" and its return value surfaced
        assert recorded["path"] == link
        assert recorded["kind"] == "symlink"
        assert result == "sentinel-result"

    def test_missing_calls_on_error_missing(self, tmp_path: Path):
        # Given - a path that does not exist
        path = tmp_path / "absent.json"

        recorded: dict[str, object] = {}

        def on_error(p: Path, kind: str, detail: str) -> object:
            recorded["path"] = p
            recorded["kind"] = kind
            recorded["detail"] = detail
            return DEGRADED

        # When
        result = load_guarded_json(path, size_limit=1024, on_error=on_error)

        # Then - on_error invoked with kind "missing"
        assert recorded["path"] == path
        assert recorded["kind"] == "missing"
        assert result is DEGRADED

    def test_dangling_symlink_reports_symlink_not_missing(self, tmp_path: Path):
        # Given - a symlink whose target does NOT exist (dangling)
        link = tmp_path / "dangling.json"
        link.symlink_to(tmp_path / "no-such-target.json")

        recorded: dict[str, object] = {}

        def on_error(p: Path, kind: str, detail: str) -> object:  # noqa: ARG001
            recorded["kind"] = kind
            return DEGRADED

        # When
        load_guarded_json(link, size_limit=1024, on_error=on_error)

        # Then - symlink is checked BEFORE existence (Invariant 8)
        assert recorded["kind"] == "symlink"

    def test_oversize_calls_on_error_oversize(self, tmp_path: Path):
        # Given - a file larger than size_limit, with byte detail
        size_limit = 10
        path = tmp_path / "big.json"
        path.write_bytes(b"x" * (size_limit + 5))

        recorded: dict[str, object] = {}

        def on_error(p: Path, kind: str, detail: str) -> object:  # noqa: ARG001
            recorded["kind"] = kind
            recorded["detail"] = detail
            return DEGRADED

        # When
        load_guarded_json(path, size_limit=size_limit, on_error=on_error)

        # Then - kind "oversize" with byte detail
        assert recorded["kind"] == "oversize"
        assert "15" in str(recorded["detail"])
        assert str(size_limit) in str(recorded["detail"])

    def test_size_limit_boundary_at_limit_passes(self, tmp_path: Path):
        # Given - a file EXACTLY size_limit bytes of VALID JSON (boundary: passes)
        size_limit = 10
        path = tmp_path / "exact.json"
        path.write_bytes(b"1234567890")  # 10 bytes, parses to int 1234567890

        recorder: list[tuple[Path, str, str]] = []

        def on_error(p: Path, kind: str, detail: str) -> object:  # noqa: ARG001
            recorder.append((p, kind, detail))
            return DEGRADED

        # When
        result = load_guarded_json(path, size_limit=size_limit, on_error=on_error)

        # Then - parsed (json content irrelevant); on_error NOT called (Invariant 8)
        assert recorder == []
        # result is whatever json.load returned (may be ValueError on invalid, but not DEGRADED)
        assert result is not DEGRADED

    def test_size_limit_boundary_over_limit_fails(self, tmp_path: Path):
        # Given - size_limit + 1 bytes (boundary: fails)
        size_limit = 10
        path = tmp_path / "one_over.json"
        path.write_bytes(b"x" * (size_limit + 1))

        recorded: dict[str, object] = {}

        def on_error(p: Path, kind: str, detail: str) -> object:  # noqa: ARG001
            recorded["kind"] = kind
            return DEGRADED

        # When
        load_guarded_json(path, size_limit=size_limit, on_error=on_error)

        # Then - kind "oversize"
        assert recorded["kind"] == "oversize"

    def test_stat_error_calls_on_error_stat_error(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        # Given - a real file, but stat() raises OSError (monkeypatched)
        path = tmp_path / "statfail.json"
        path.write_text("{}", encoding="utf-8")

        def boom(self: Path, *args: object, **kwargs: object) -> object:  # noqa: ARG001
            raise OSError("simulated stat failure")

        monkeypatch.setattr(Path, "stat", boom)

        recorded: dict[str, object] = {}

        def on_error(p: Path, kind: str, detail: str) -> object:  # noqa: ARG001
            recorded["kind"] = kind
            recorded["detail"] = detail
            return DEGRADED

        # When
        load_guarded_json(path, size_limit=1024, on_error=on_error)

        # Then - kind "stat_error" (the loader calls path.stat() for the size)
        assert recorded["kind"] == "stat_error"
        assert "simulated stat failure" in str(recorded["detail"])

    def test_invalid_json_calls_on_error_invalid_json(self, tmp_path: Path):
        # Given - a file with malformed JSON
        path = tmp_path / "broken.json"
        path.write_text("{not valid json", encoding="utf-8")

        recorded: dict[str, object] = {}

        def on_error(p: Path, kind: str, detail: str) -> object:  # noqa: ARG001
            recorded["kind"] = kind
            recorded["detail"] = detail
            return DEGRADED

        # When
        load_guarded_json(path, size_limit=1024, on_error=on_error)

        # Then - kind "invalid_json"
        assert recorded["kind"] == "invalid_json"
        assert recorded["detail"] != ""

    def test_on_error_raise_propagates(self, tmp_path: Path):
        # Given - an on_error that raises FileProcessingError (derivatives policy)
        path = tmp_path / "absent.json"

        def on_error(p: Path, kind: str, detail: str) -> object:  # noqa: ARG001
            raise FileProcessingError(f"refusing to degrade for kind={kind}")

        # When / Then - the raise propagates out of load_guarded_json (Invariant 6)
        with pytest.raises(FileProcessingError, match="refusing to degrade"):
            load_guarded_json(path, size_limit=1024, on_error=on_error)

    def test_on_error_return_degraded(self, tmp_path: Path):
        # Given - an on_error that returns DEGRADED
        path = tmp_path / "absent.json"

        def on_error(p: Path, kind: str, detail: str) -> object:  # noqa: ARG001
            return DEGRADED

        # When
        result = load_guarded_json(path, size_limit=1024, on_error=on_error)

        # Then - DEGRADED returned by identity (binds the degrade contract)
        assert result is DEGRADED

    def test_kind_is_from_closed_set(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        # Given - a recorder that captures every (path, kind, detail) across
        # multiple failure scenarios; purpose: typo-proof the closed kind set
        recorded_kinds: list[str] = []

        def recorder_on_error(p: Path, kind: str, detail: str) -> object:  # noqa: ARG001
            recorded_kinds.append(kind)
            return DEGRADED

        # Scenario: symlink (real target)
        real = tmp_path / "real.json"
        real.write_text("{}", encoding="utf-8")
        good_link = tmp_path / "good_link.json"
        good_link.symlink_to(real)
        load_guarded_json(good_link, size_limit=1024, on_error=recorder_on_error)

        # Scenario: dangling symlink (symlink-before-exists ordering)
        dangling = tmp_path / "dangling.json"
        dangling.symlink_to(tmp_path / "no-target.json")
        load_guarded_json(dangling, size_limit=1024, on_error=recorder_on_error)

        # Scenario: missing
        load_guarded_json(tmp_path / "absent.json", size_limit=1024, on_error=recorder_on_error)

        # Scenario: oversize
        big = tmp_path / "big.json"
        big.write_bytes(b"x" * 100)
        load_guarded_json(big, size_limit=10, on_error=recorder_on_error)

        # Scenario: stat_error (monkeypatched)
        statfail = tmp_path / "statfail.json"
        statfail.write_text("{}", encoding="utf-8")

        def stat_boom(self: Path, *args: object, **kwargs: object) -> object:  # noqa: ARG001
            raise OSError("stat boom")

        monkeypatch.setattr(Path, "stat", stat_boom)
        load_guarded_json(statfail, size_limit=1024, on_error=recorder_on_error)

        # Scenario: invalid_json (restore stat first)
        monkeypatch.undo()
        broken = tmp_path / "broken.json"
        broken.write_text("{broken", encoding="utf-8")
        load_guarded_json(broken, size_limit=1024, on_error=recorder_on_error)

        # Then - every recorded kind is a member of the closed set
        assert recorded_kinds, "expected at least one failure kind to be recorded"
        for kind in recorded_kinds:
            assert kind in _CLOSED_KIND_SET, f"unknown kind {kind!r} not in closed set {_CLOSED_KIND_SET}"
        # And every kind from the closed set was exercised (defensive coverage)
        assert set(recorded_kinds) == _CLOSED_KIND_SET

    def test_does_not_validate_shape(self, tmp_path: Path):
        # Given - valid JSON that is a LIST, not the caller's expected dict schema
        path = tmp_path / "list.json"
        payload = ["not", "a", "dict"]
        path.write_text(json.dumps(payload), encoding="utf-8")

        recorder: list[tuple[Path, str, str]] = []

        def on_error(p: Path, kind: str, detail: str) -> object:  # noqa: ARG001
            recorder.append((p, kind, detail))
            return DEGRADED

        # When
        result = load_guarded_json(path, size_limit=1024, on_error=on_error)

        # Then - returned as-is; shape validation is the caller's job (Invariant 7)
        assert result == payload
        assert recorder == []
