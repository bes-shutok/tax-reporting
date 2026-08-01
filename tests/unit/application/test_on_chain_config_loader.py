"""Unit tests for the per-year on-chain wallet config loader.

TDD RED -> GREEN -> refactor. These tests cover
:func:`load_on_chain_wallets` and its path-injected helper
:func:`_load_on_chain_wallets_from_path`, mirroring the
derivatives-labels loader test shape
(``tests/unit/application/test_derivatives_filter.py``) so the config
loader can be exercised against arbitrary ``tmp_path`` files.

New contract (plan `2026-08-01-minimal-chains-json-config`): the user
supplies only wallet identity (``chain``, ``label``, ``address``); the
loader derives ``chainid``/``native_ticker``/``start_date``/``end_date``
from the trusted chain registry in ``chain_derivation.py`` plus the
fiscal-year arg.
"""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path

import pytest

from tax_reporting.domain.exceptions import FileProcessingError


def _write_config(path: Path, payload: object) -> Path:
    """Write ``payload`` as JSON to ``path`` and return the path."""
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _valid_wallet(**overrides: object) -> dict[str, object]:
    """Return a single-entry minimal wallet config dict (3-field contract).

    The user supplies only wallet identity (chain/label/address); the four
    chain-property fields (chainid, native_ticker, start_date, end_date)
    are derived by the loader from the chain registry + fiscal year.
    """
    entry: dict[str, object] = {
        "chain": "Berachain",
        "label": "Ledger Berachain (BERA)",
        "address": "0xdead000000000000000000000000000000000000",
    }
    entry.update(overrides)
    return {"wallets": [entry]}


class TestOnChainConfigLoader:
    """Tests for load_on_chain_wallets / _load_on_chain_wallets_from_path."""

    def test_load_minimal_config_derives_all_fields(self, tmp_path: Path):
        """Given a 3-field chains.json for year 2025, expects the returned
        OnChainWalletConfig has chainid/ticker/dates derived internally:
        chainid==80094, native_ticker=="BERA", start==2025-02-06 (Jan 1
        clamped up to genesis), end==2025-12-31.
        """
        from tax_reporting.application.on_chain_config import (
            OnChainWalletConfig,
            _load_on_chain_wallets_from_path,
        )

        path = _write_config(tmp_path / "chains.json", _valid_wallet())

        result = _load_on_chain_wallets_from_path(path, 2025)

        assert result == [
            OnChainWalletConfig(
                chain="Berachain",
                chainid=80094,
                label="Ledger Berachain (BERA)",
                address="0xdead000000000000000000000000000000000000",
                native_ticker="BERA",
                start_date=date(2025, 2, 6),
                end_date=date(2025, 12, 31),
            )
        ]

    def test_dates_derived_from_fiscal_year_for_pre_launch_january(
        self, tmp_path: Path
    ):
        """Given year 2025 and Berachain (genesis 2025-02-06), expects
        start_date==2025-02-06 (NOT 2025-01-01, because Jan 1 precedes
        launch and is clamped up to genesis).
        """
        from tax_reporting.application.on_chain_config import (
            _load_on_chain_wallets_from_path,
        )

        path = _write_config(tmp_path / "chains.json", _valid_wallet())

        result = _load_on_chain_wallets_from_path(path, 2025)

        assert len(result) == 1
        assert result[0].start_date == date(2025, 2, 6)

    def test_year_entirely_before_launch_raises(self, tmp_path: Path):
        """Given year 2024 and Berachain (genesis 2025-02-06), expects
        FileProcessingError: derived end_date 2024-12-31 < start_date
        2025-02-06 -> empty date window.
        """
        from tax_reporting.application.on_chain_config import (
            _load_on_chain_wallets_from_path,
        )

        path = _write_config(tmp_path / "chains.json", _valid_wallet())

        with pytest.raises(
            FileProcessingError, match=r"empty date window"
        ) as exc_info:
            _load_on_chain_wallets_from_path(path, 2024)
        assert "index 0" in str(exc_info.value)

    def test_end_date_clamped_to_today(self, tmp_path: Path):
        """Given a fiscal year whose Dec 31 is after today (year 2026,
        ``today`` injected as 2026-08-01), expects end_date==2026-08-01
        (min(fiscal end, today)).

        Note: a fiscal year that does NOT contain today (e.g. 2099 with
        today=2026-08-01) would trip the empty-window invariant
        (2099-01-01 > 2026-08-01), so this test uses the current fiscal
        year to exercise the end_date clamp in isolation.
        """
        from tax_reporting.application.on_chain_config import (
            _load_on_chain_wallets_from_path,
        )

        path = _write_config(tmp_path / "chains.json", _valid_wallet())
        fixed_today = date(2026, 8, 1)

        result = _load_on_chain_wallets_from_path(
            path, 2026, today=lambda: fixed_today
        )

        assert len(result) == 1
        assert result[0].end_date == fixed_today

    def test_unsupported_chain_raises_scoped_message(self, tmp_path: Path):
        """Given {chain:"Solana", ...}, expects FileProcessingError whose
        message names "Solana" (the rejected chain) AND contains
        "Berachain" (the currently-documented-supported chain, F1 fold),
        AND does NOT present "Solana" as a supported chain. Fails if the
        message lists the wrong set or omits the rejection reason.
        """
        from tax_reporting.application.on_chain_config import (
            _load_on_chain_wallets_from_path,
        )

        path = _write_config(
            tmp_path / "chains.json",
            _valid_wallet(chain="Solana"),
        )

        with pytest.raises(FileProcessingError) as exc_info:
            _load_on_chain_wallets_from_path(path, 2025)

        message = str(exc_info.value)
        # Names the rejected chain.
        assert "Solana" in message
        # Documents the currently-supported chain (F1 fold).
        assert "Berachain" in message
        # Does NOT list Solana as supported (the rejection reason must be
        # a discriminating message, not a generic list of every chain).
        assert "index 0" in message

    @pytest.mark.parametrize("field", ["chain", "label", "address"])
    def test_missing_required_field_raises(self, tmp_path: Path, field: str):
        """Given a wallet entry missing each of chain/label/address,
        expects FileProcessingError matching the field name and "index 0".
        """
        from tax_reporting.application.on_chain_config import (
            _load_on_chain_wallets_from_path,
        )

        entry = _valid_wallet()["wallets"][0]
        del entry[field]
        path = _write_config(tmp_path / "chains.json", {"wallets": [entry]})

        with pytest.raises(
            FileProcessingError, match=field
        ) as exc_info:
            _load_on_chain_wallets_from_path(path, 2025)
        assert "index 0" in str(exc_info.value)

    def test_extra_keys_ignored(self, tmp_path: Path):
        """Given an entry that ALSO carries the old fields (chainid,
        native_ticker, start_date, end_date), expects they are silently
        ignored and the derived values are used (hard-break,
        ignore-extras contract). A wrong user-supplied chainid must NOT
        leak into the result.
        """
        from tax_reporting.application.on_chain_config import (
            _load_on_chain_wallets_from_path,
        )

        path = _write_config(
            tmp_path / "chains.json",
            _valid_wallet(
                chainid=1,  # would be Ethereum; must be ignored
                native_ticker="WRONG",  # must be ignored
                start_date="2025-01-01",  # must be ignored (clamped to genesis)
                end_date="2099-12-31",  # must be ignored (clamped to fiscal end)
            ),
        )

        result = _load_on_chain_wallets_from_path(path, 2025)

        assert len(result) == 1
        wallet = result[0]
        assert wallet.chainid == 80094  # derived, NOT the supplied 1
        assert wallet.native_ticker == "BERA"  # derived, NOT "WRONG"
        assert wallet.start_date == date(2025, 2, 6)  # genesis clamp
        assert wallet.end_date == date(2025, 12, 31)  # fiscal end

    def test_missing_config_returns_empty_silent(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ):
        """Given a chains.json path that does not exist, expects an empty
        list AND no log record emitted by the loader (DI-6: the single
        WARNING is owned by the orchestrator layer, NOT here).
        """
        from tax_reporting.application.on_chain_config import (
            _load_on_chain_wallets_from_path,
        )

        missing = tmp_path / "absent_chains.json"

        with caplog.at_level(
            logging.DEBUG, logger="tax_reporting.application.on_chain_config"
        ):
            result = _load_on_chain_wallets_from_path(missing, 2025)

        assert result == []
        assert not caplog.records, (
            "Loader must stay silent for a missing config; the orchestrator "
            "owns the single WARNING (DI-6)."
        )

    def test_malformed_json_raises(self, tmp_path: Path):
        """Given a chains.json with invalid JSON, expects FileProcessingError
        naming the path (PT011 match).
        """
        from tax_reporting.application.on_chain_config import (
            _load_on_chain_wallets_from_path,
        )

        bad = tmp_path / "chains.json"
        bad.write_text("{not valid json", encoding="utf-8")

        with pytest.raises(FileProcessingError, match=str(bad)):
            _load_on_chain_wallets_from_path(bad, 2025)

    def test_missing_wallets_key_raises(self, tmp_path: Path):
        """Given valid JSON without a wallets key, expects FileProcessingError
        naming the missing key.
        """
        from tax_reporting.application.on_chain_config import (
            _load_on_chain_wallets_from_path,
        )

        path = _write_config(tmp_path / "chains.json", {"other": []})

        with pytest.raises(FileProcessingError, match="wallets"):
            _load_on_chain_wallets_from_path(path, 2025)

    def test_symlink_config_raises(self, tmp_path: Path):
        """Given a symlinked chains.json, expects FileProcessingError (the
        symlink guard fires before the existence check).
        """
        from tax_reporting.application.on_chain_config import (
            _load_on_chain_wallets_from_path,
        )

        target = tmp_path / "real_chains.json"
        target.write_text(json.dumps(_valid_wallet()), encoding="utf-8")
        link = tmp_path / "chains.json"
        link.symlink_to(target)

        with pytest.raises(FileProcessingError, match=str(link)):
            _load_on_chain_wallets_from_path(link, 2025)
