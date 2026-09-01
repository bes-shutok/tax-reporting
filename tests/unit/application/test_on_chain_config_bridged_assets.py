"""Facade-resolution tests for the per-year bridged-asset registry.

Moved from ``tests/unit/infrastructure/test_bridged_asset_registry.py``
(review r2 F7) so the test tree mirrors the production layer split: the
facade :func:`tax_reporting.application.on_chain_config.load_bridged_asset_registry_for_year`
is an APPLICATION-layer resolution wrapper (the C8 precedent keeps its
``load_position_token_registry_for_year`` facade tests under
``tests/unit/application/``), while the loader/GUARD tests stay under
``tests/unit/infrastructure/``.

Coverage is unchanged: the user file SHADOWS (fully replaces) the committed
canonical registry, and the no-user-file default resolves the committed
``example/`` file. Hermeticity (AGENTS.md crypto-tests rule): the repo root
is pinned to ``tmp_path`` so no gitignored personal data is ever opened.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from tax_reporting.application.on_chain_config import (
    load_bridged_asset_registry_for_year,
)


@pytest.mark.unit
class TestBridgedAssetRegistryFacadeResolution:
    """Resolution legs of the per-year facade (r1 overflow; moved r2 F7)."""

    @staticmethod
    def _write(path: Path, token: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"source": f"synthetic {path.name}", token: {"note": "x"}}),
            encoding="utf-8",
        )

    def test_user_file_shadows_committed_canonical(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        user_token = "0x0000000000000000000000000000000000000e11"
        committed_token = "0x0000000000000000000000000000000000000e22"
        self._write(
            tmp_path / "resources" / "source" / "2025" / "bera_bridged_assets.json",
            user_token,
        )
        self._write(
            tmp_path / "resources" / "source" / "example" / "2025" / "bera_bridged_assets.json",
            committed_token,
        )

        with caplog.at_level(logging.INFO, logger="tax_reporting.application.paths"):
            registry = load_bridged_asset_registry_for_year(2025, repo_root=tmp_path)

        # SHADOW, not merge: the user file REPLACES the canonical registry
        # (the committed entry is gone for this run).
        assert registry.source.endswith("resources/source/2025/bera_bridged_assets.json")
        assert registry.is_bridged_asset(user_token)
        assert not registry.is_bridged_asset(committed_token)
        # Review r4 F1: this registry's shadow leg IS a data-loss condition
        # (the committed file is canonical), so the facade must route it
        # through the WARNING + copy-and-append hint (scoped to this
        # registry only; the other three stay INFO).
        assert any(
            "bera_bridged_assets.json" in record.getMessage()
            and "fully replaces the committed registry" in record.getMessage()
            and "copy the committed file and append" in record.getMessage()
            for record in caplog.records
            if record.levelno == logging.WARNING
        ), (
            "expected the bridged-registry shadow WARNING naming the "
            "dropped-entry consequence and the copy-and-append remedy"
        )

    def test_default_resolves_committed_example(self, tmp_path: Path) -> None:
        committed_token = "0x0000000000000000000000000000000000000e22"
        self._write(
            tmp_path / "resources" / "source" / "example" / "2025" / "bera_bridged_assets.json",
            committed_token,
        )

        registry = load_bridged_asset_registry_for_year(2025, repo_root=tmp_path)

        assert registry.source.endswith(
            "resources/source/example/2025/bera_bridged_assets.json"
        )
        assert registry.is_bridged_asset(committed_token)

    def test_missing_everything_degrades_to_empty_registry_with_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Given NEITHER the user file NOR the committed example (a
        corrupted-checkout shape: empty repo root), review r3 F6 pins the
        facade-level composition end-to-end: an EMPTY registry plus the
        loader WARNING naming the spam consequence (previously proven only
        via its halves: loader missing-file test + fallback-resolution
        test).
        """
        with caplog.at_level(
            logging.WARNING,
            logger="tax_reporting.infrastructure.on_chain.bridged_asset_registry",
        ):
            registry = load_bridged_asset_registry_for_year(2025, repo_root=tmp_path)

        assert not registry.tokens
        assert any(
            "No bridged-asset registry at" in record.getMessage()
            and "spam" in record.getMessage()
            for record in caplog.records
            if record.levelno == logging.WARNING
        ), "expected the loader WARNING naming the spam consequence"
