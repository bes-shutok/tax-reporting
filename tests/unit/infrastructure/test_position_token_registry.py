"""Tests for the position-token registry loader (plan 2026-08-22 Task 3).

The position-token registry is the address-keyed allowlist for LST /
staking-position receipt tokens (LBGT, iBGT, position NFTs) that the
unknown-family classifier rules gate on. It mirrors the LP snapshot pattern
(``berachain_lp_snapshot.json``): a per-user gitignored JSON file with
provenance metadata, plus a committed ``example/`` template.

Hermeticity (AGENTS.md crypto-tests rule): these tests NEVER open the real
gitignored registry at ``resources/source/2025/bera_position_tokens.json``;
they write synthetic registries to ``tmp_path`` or build in-memory ones.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from tax_reporting.domain.exceptions import ConfigurationError, FileProcessingError
from tax_reporting.infrastructure.on_chain.position_token_registry import (
    PositionTokenRegistry,
    build_position_token_registry,
    load_position_token_registry,
)

_TOKEN_A = "0x0000000000000000000000000000000000000f17"
_TOKEN_A_UPPER = "0x0000000000000000000000000000000000000F17"
_TOKEN_B = "0x0000000000000000000000000000000000000ee5"


def _registry_data() -> dict[str, object]:
    """A minimal valid in-memory registry dict (synthetic addresses)."""
    return {
        "as_of_date": "2026-08-22",
        "provenance": "<inline-test>",
        "tokens": [
            {
                "token_address": _TOKEN_A,
                "label": "iTEST",
                "kind": "lst",
                "provenance": "cluster 6 (verdict B)",
            },
            {
                "token_address": _TOKEN_B,
                "label": "TEST-POS",
                "kind": "position_nft",
                "provenance": "cluster 4 zap receipt",
            },
        ],
    }


def _write_registry(tmp_path: Path, data: object) -> Path:
    """Write ``data`` as JSON to a tmp registry file; return its path."""
    path = tmp_path / "bera_position_tokens.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


@pytest.mark.unit
class TestBuildPositionTokenRegistry:
    """In-memory builder: schema validation + address-keyed membership."""

    def test_build_lowercases_addresses_and_members_lookup_case_insensitive(
        self,
    ) -> None:
        registry = build_position_token_registry(
            _registry_data(), source="<inline-test>"
        )

        assert isinstance(registry, PositionTokenRegistry)
        assert set(registry.tokens) == {_TOKEN_A, _TOKEN_B}
        # Membership is address-keyed and case-insensitive.
        assert registry.is_position_token(_TOKEN_A) is True
        assert registry.is_position_token(_TOKEN_A_UPPER) is True
        assert registry.is_position_token(_TOKEN_B) is True
        assert registry.is_position_token("0x000000000000000000000000000000000000abcd") is False
        assert registry.is_position_token("") is False

    def test_build_first_occurrence_wins_on_duplicate_addresses(self) -> None:
        data = _registry_data()
        tokens = data["tokens"]
        assert isinstance(tokens, list)
        tokens.append({"token_address": _TOKEN_A, "label": "STALE"})

        registry = build_position_token_registry(data, source="<inline-test>")

        # The first entry wins; the duplicate does not overwrite its label.
        assert registry.tokens[_TOKEN_A].label == "iTEST"
        assert len(registry.tokens) == 2

    def test_build_rejects_non_object(self) -> None:
        with pytest.raises(ConfigurationError, match="must be a JSON object"):
            build_position_token_registry(["not", "a", "dict"], source="<inline-test>")

    def test_build_rejects_missing_tokens_field(self) -> None:
        with pytest.raises(ConfigurationError, match="'tokens'"):
            build_position_token_registry({"as_of_date": "2026-08-22"}, source="<inline-test>")

    def test_build_rejects_tokens_not_a_list(self) -> None:
        with pytest.raises(ConfigurationError, match="'tokens' must be a list"):
            build_position_token_registry(
                {"tokens": {"addr": {}}}, source="<inline-test>"
            )

    def test_build_rejects_entry_missing_token_address(self) -> None:
        with pytest.raises(ConfigurationError, match="token_address"):
            build_position_token_registry(
                {"tokens": [{"label": "no-address"}]}, source="<inline-test>"
            )

    def test_build_rejects_entry_not_an_object(self) -> None:
        with pytest.raises(ConfigurationError, match="must be a JSON object"):
            build_position_token_registry(
                {"tokens": ["0xabc"]}, source="<inline-test>"
            )

    def test_build_rejects_invalid_optional_field_type(self) -> None:
        with pytest.raises(ConfigurationError, match="'label' must be a string"):
            build_position_token_registry(
                {"tokens": [{"token_address": _TOKEN_A, "label": 42}]},
                source="<inline-test>",
            )

    def test_build_rejects_unknown_kind(self) -> None:
        # Review r2 F1: ``kind`` is BEHAVIORAL (gates ``is_position_vault``);
        # a spelling variant (e.g. "vault", "Position_NFT") must fail LOUDLY
        # at load time instead of silently disabling the recipient rule.
        with pytest.raises(ConfigurationError, match="unknown 'kind' 'vault'"):
            build_position_token_registry(
                {"tokens": [{"token_address": _TOKEN_A, "kind": "vault"}]},
                source="<inline-test>",
            )

    def test_build_kind_gates_is_position_vault(self) -> None:
        # Review r2 F2: the kind gate is the only guard separating the TOKEN
        # predicate from the RECIPIENT predicate over one address set; an
        # ``lst`` member must be a position token but NEVER a position vault.
        registry = build_position_token_registry(
            _registry_data(), source="<inline-test>"
        )

        # _TOKEN_A is kind="lst"; _TOKEN_B is kind="position_nft".
        assert registry.is_position_vault(_TOKEN_A) is False
        assert registry.is_position_vault(_TOKEN_B) is True
        # Membership of ANY kind still serves the token rule.
        assert registry.is_position_token(_TOKEN_A) is True
        assert registry.is_position_token(_TOKEN_B) is True

    def test_build_kind_absent_is_never_a_vault(self) -> None:
        # An entry WITHOUT a kind serves the token rule but never the
        # recipient rule (the vault predicate matches only "position_nft").
        registry = build_position_token_registry(
            {"tokens": [{"token_address": _TOKEN_A}]}, source="<inline-test>"
        )

        assert registry.is_position_token(_TOKEN_A) is True
        assert registry.is_position_vault(_TOKEN_A) is False

    def test_is_position_nft_token_kind_gated(self) -> None:
        # Review r4 F4: direct pin for the kind-gated TOKEN predicate (the
        # decoder's nfttx gate and the processor's receive detector both
        # branch on it). Only kind="position_nft" members match; case is
        # irrelevant (addresses are lower-cased at load); empty never
        # matches. A future re-bodying without the kind gate (the r2-F1
        # regression shape) fails here even when processor-level tests are
        # shadowed by the vault-target discriminator.
        registry = build_position_token_registry(
            _registry_data(), source="<inline-test>"
        )

        # _TOKEN_A is kind="lst"; _TOKEN_B is kind="position_nft".
        assert registry.is_position_nft_token(_TOKEN_B) is True
        assert registry.is_position_nft_token(_TOKEN_A) is False
        assert registry.is_position_nft_token(_TOKEN_A_UPPER) is False
        assert registry.is_position_nft_token("") is False
        assert registry.is_position_nft_token(
            "0x000000000000000000000000000000000000abcd"
        ) is False

    def test_is_position_nft_token_kind_absent_is_false(self) -> None:
        # An entry WITHOUT a kind serves the bare token rule but never the
        # kind-gated NFT predicate.
        registry = build_position_token_registry(
            {"tokens": [{"token_address": _TOKEN_A}]}, source="<inline-test>"
        )

        assert registry.is_position_token(_TOKEN_A) is True
        assert registry.is_position_nft_token(_TOKEN_A) is False


@pytest.mark.unit
class TestLoadPositionTokenRegistry:
    """File loader: tmp_path fixtures only (never the real gitignored file)."""

    def test_load_valid_file_builds_registry(self, tmp_path: Path) -> None:
        path = _write_registry(tmp_path, _registry_data())

        registry = load_position_token_registry(path)

        assert registry.is_position_token(_TOKEN_A) is True
        assert registry.source == str(path)

    def test_load_missing_file_degrades_to_empty_registry_with_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        missing = tmp_path / "absent.json"

        with caplog.at_level(logging.WARNING):
            registry = load_position_token_registry(missing)

        assert isinstance(registry, PositionTokenRegistry)
        assert not registry.tokens
        assert registry.is_position_token(_TOKEN_A) is False
        assert any(
            "position-token registry" in r.getMessage() for r in caplog.records
        ), "expected a WARNING naming the missing registry"

    def test_load_invalid_json_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "bera_position_tokens.json"
        path.write_text("{not json", encoding="utf-8")

        with pytest.raises(FileProcessingError, match="invalid JSON"):
            load_position_token_registry(path)

    def test_load_schema_failure_raises_configuration_error(
        self, tmp_path: Path
    ) -> None:
        path = _write_registry(tmp_path, {"tokens": [{"label": "x"}]})

        with pytest.raises(ConfigurationError, match="token_address"):
            load_position_token_registry(path)

    def test_load_symlink_raises(self, tmp_path: Path) -> None:
        real = _write_registry(tmp_path, _registry_data())
        link = tmp_path / "link.json"
        link.symlink_to(real)

        with pytest.raises(FileProcessingError, match="symlink"):
            load_position_token_registry(link)

    def test_load_oversize_raises(self, tmp_path: Path) -> None:
        # Review r1 F18: the >256 KiB size-cap guard (a hand-curated registry
        # that outgrows the cap must fail loudly, not load). The blob pads the
        # per-registry ``_comment`` field so the schema stays otherwise valid -
        # only the SIZE triggers the guard.
        data = _registry_data()
        data["_comment"] = "x" * (256 * 1024 + 1)
        path = _write_registry(tmp_path, data)

        with pytest.raises(FileProcessingError, match="size limit"):
            load_position_token_registry(path)
