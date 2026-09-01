"""Tests for the bridged-asset registry loader (plan 2026-08-26 Task 1).

The bridged-asset registry is the address-keyed allowlist of bridge-issued
token contracts (the trusted-mint allowlist) that the processor's
zero-address-mint gate consults: a mint of a MEMBER token classifies
``Reward``/``bridge``; a non-member (or an empty registry) classifies
``Reward``/``spam`` + review. Registry semantics mirror the C8
position-token chain (per-year, optional user override shadowing the
committed canonical file, missing -> empty + WARNING), but the JSON
vocabulary is DELIBERATELY DIFFERENT (plan review r1-F4 / r9-F1): a
registry-level ``source`` provenance string plus entries keyed by the
lowercased token address, each an object with an optional ``note`` string -
NOT C8's ``provenance``/``label``/``tokens`` vocabulary.

This module covers the GUARD cases only (plan Task 1): missing file, symlink,
invalid JSON, schema violation, oversize.

Hermeticity (AGENTS.md crypto-tests rule): these tests NEVER open the real
gitignored user registry at ``resources/source/2025/bera_bridged_assets.json``
or the committed canonical ``resources/source/example/2025/bera_bridged_assets.json``;
they write synthetic registries to ``tmp_path``.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from tax_reporting.domain.exceptions import ConfigurationError, FileProcessingError
from tax_reporting.infrastructure.on_chain.bridged_asset_registry import (
    build_bridged_asset_registry,
    load_bridged_asset_registry,
)

_TOKEN_A = "0x0000000000000000000000000000000000000b77"


def _registry_data() -> dict[str, object]:
    """A minimal valid in-memory registry dict (synthetic address)."""
    return {
        "source": "synthetic test registry (plan 2026-08-26)",
        _TOKEN_A: {"note": "synthetic bridged token"},
    }


def _write_registry(tmp_path: Path, data: object) -> Path:
    """Write ``data`` as JSON to a tmp registry file; return its path."""
    path = tmp_path / "bera_bridged_assets.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


@pytest.mark.unit
class TestBridgedAssetRegistry:
    """Loader GUARD cases only (missing/symlink/invalid-JSON/schema/oversize)."""

    def test_load_missing_file_degrades_to_empty_registry_with_spam_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        # A missing registry file must degrade to an EMPTY registry + an
        # actionable WARNING naming the spam consequence (zero-address mints
        # then classify spam + review) - never abort the run, never a silent
        # bridge.
        missing = tmp_path / "absent.json"

        with caplog.at_level(logging.WARNING):
            registry = load_bridged_asset_registry(missing)

        assert registry.is_bridged_asset(_TOKEN_A) is False
        # Review r5 F3 (post-exit polish): prefix-grade assertion matching
        # the facade sibling (the exact production message prefix + the spam
        # consequence), not a loose two-word substring check.
        assert any(
            record.getMessage().startswith("No bridged-asset registry at")
            and "spam" in record.getMessage()
            for record in caplog.records
            if record.levelno == logging.WARNING
        ), "expected a WARNING naming the registry and the spam consequence"

    def test_load_symlink_raises(self, tmp_path: Path) -> None:
        real = _write_registry(tmp_path, _registry_data())
        link = tmp_path / "link.json"
        link.symlink_to(real)

        with pytest.raises(FileProcessingError, match="symlink"):
            load_bridged_asset_registry(link)

    def test_load_invalid_json_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "bera_bridged_assets.json"
        path.write_text("{not json", encoding="utf-8")

        with pytest.raises(FileProcessingError, match="invalid JSON"):
            load_bridged_asset_registry(path)

    def test_load_schema_violation_raises_configuration_error(
        self, tmp_path: Path
    ) -> None:
        # Schema violation: an entry value must be a JSON object (here a bare
        # string), not a flat value.
        path = _write_registry(tmp_path, {"source": "x", _TOKEN_A: "flat-note"})

        with pytest.raises(ConfigurationError, match="must be a JSON object"):
            load_bridged_asset_registry(path)

    def test_load_oversize_raises(self, tmp_path: Path) -> None:
        # The >256 KiB size-cap guard (mirrors the position-token registry
        # policy): the blob pads a per-entry ``note`` so the schema stays
        # otherwise valid - only the SIZE triggers the guard.
        data = {"source": "x", _TOKEN_A: {"note": "x" * (256 * 1024 + 1)}}
        path = _write_registry(tmp_path, data)

        with pytest.raises(FileProcessingError, match="size limit"):
            load_bridged_asset_registry(path)

    @pytest.mark.parametrize(
        ("data", "match"),
        [
            # Unknown per-entry field: the pinned vocabulary allows ONLY
            # ``note`` (a C8-vocabulary hand-edit like ``label`` must fail).
            (
                {"source": "s", _TOKEN_A: {"label": "x"}},
                r"unknown field.*label",
            ),
            # Missing registry-level ``source`` provenance.
            ({_TOKEN_A: {"note": "x"}}, r"missing the required non-empty 'source'"),
            # Non-dict top-level JSON (a bare list).
            ([_TOKEN_A], r"must be a JSON object"),
            # Non-string ``note``.
            ({"source": "s", _TOKEN_A: {"note": 7}}, r"'note' must be a string"),
            # Non-address entry key: a ticker-style key can never match a leg
            # token address (review r1 F7 - fail at load, not silently).
            ({"source": "s", "WBTC": {"note": "x"}}, r"0x \+ 40-hex token"),
            # Non-address entry key: a 39-hex typo.
            (
                {"source": "s", "0x0000000000000000000000000000000000000b7": {"note": "x"}},
                r"0x \+ 40-hex token",
            ),
            # Review r2 F8: the EMPTY key is subsumed by the address-regex
            # guard (the standalone non-empty-string branch was removed); it
            # must fail with the SAME unified message.
            ({"source": "s", "": {"note": "x"}}, r"0x \+ 40-hex token"),
        ],
    )
    def test_build_schema_violations_raise_configuration_error(
        self, data: object, match: str
    ) -> None:
        # Review r1 F6: every schema-validation branch in
        # ``build_bridged_asset_registry`` is exercised (previously only the
        # bare-string entry value was under test), so dropping or weakening
        # any guard fails the suite.
        with pytest.raises(ConfigurationError, match=match):
            build_bridged_asset_registry(data, source="<inline-test>")

    def test_build_uppercase_address_key_lowercased_into_membership(self) -> None:
        # Review r1 F6: a valid mixed-case (checksummed-style) key is ACCEPTED
        # and stored lowercased, so membership is case-insensitive.
        upper = "0x0000000000000000000000000000000000000B77"
        registry = build_bridged_asset_registry(
            {"source": "s", upper: {"note": "x"}}, source="<inline-test>"
        )

        assert registry.tokens == {_TOKEN_A: "x"}
        assert registry.is_bridged_asset(_TOKEN_A)
        assert registry.is_bridged_asset(upper)

    def test_build_note_less_entry_allowed(self) -> None:
        # Review r2 overflow: an entry value of ``{}`` (no ``note``) is the
        # documented user escape hatch for entries without derivation
        # evidence; the note must stay OPTIONAL (None), and membership must
        # still hold.
        registry = build_bridged_asset_registry(
            {"source": "s", _TOKEN_A: {}}, source="<inline-test>"
        )

        assert registry.tokens == {_TOKEN_A: None}
        assert registry.is_bridged_asset(_TOKEN_A)

    def test_load_duplicate_keys_last_wins(self, tmp_path: Path) -> None:
        # Review r2 F5: the documented duplicate-key policy (json.loads
        # collapses duplicate JSON object keys LAST-wins) now has a failing
        # assertion - switching the builder to first-wins or rejecting
        # duplicates must fail the suite. Written as RAW JSON text so the
        # duplicate key actually reaches the parser.
        path = tmp_path / "bera_bridged_assets.json"
        path.write_text(
            "{"
            f'"source": "s", '
            f'"{_TOKEN_A}": {{"note": "first"}}, '
            f'"{_TOKEN_A}": {{"note": "second"}}'
            "}",
            encoding="utf-8",
        )

        registry = load_bridged_asset_registry(path)

        assert registry.tokens == {_TOKEN_A: "second"}

    def test_load_mixed_case_duplicate_case_fold_last_wins(self, tmp_path: Path) -> None:
        # Review r2 F5: two JSON keys differing only by case fold to the
        # SAME membership key (a distinct hazard from exact duplicates);
        # the later (mixed-case) entry wins the note, membership is
        # case-insensitive, and no merge into two members happens.
        upper = "0x0000000000000000000000000000000000000B77"
        path = tmp_path / "bera_bridged_assets.json"
        path.write_text(
            "{"
            f'"source": "s", '
            f'"{_TOKEN_A}": {{"note": "lower"}}, '
            f'"{upper}": {{"note": "upper"}}'
            "}",
            encoding="utf-8",
        )

        registry = load_bridged_asset_registry(path)

        assert registry.tokens == {_TOKEN_A: "upper"}
        assert registry.is_bridged_asset(upper)
        assert registry.is_bridged_asset(_TOKEN_A)
