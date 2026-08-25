"""Composition-root tests for the ``_main`` on-chain fetch env gate (DI-3).

The env gate (``BERA_CHAIN_API_KEY``) is read exactly ONCE, in the composition
root, at construction time. If set, it binds
``functools.partial(run_on_chain_fetch, api_key=key)`` and injects it into
``run_report``; if absent, it injects ``None`` (skip) with the "not set"
WARNING. The WARNING fires at construction time, i.e. whenever the gate is
evaluated and the var is absent (CR-Guard-accepted widening; pinned here).

These tests are the ONE legitimate env seam in the retargeted suite
(``monkeypatch.setenv``/``delenv``). ``_main`` is driven with:

- a real tmp ``config.ini`` (chdir; the loader reads ``config.ini`` from the
  CWD - no loader patching), and
- ``run_report`` monkeypatched on the composition-root module to capture the
  kwargs it receives.

This file is outside Validation gate #5's file set, so importing
``tax_reporting.main`` here is legitimate. The audit-trail WARNING assertion
reads the on-disk log (redirected into tmp) because ``_main`` reconfigures the
root logger, which detaches pytest's caplog handler mid-run.
"""

from __future__ import annotations

import functools
import logging
from pathlib import Path

import pytest

import tax_reporting.main as main_module
from tax_reporting.main import _main

_TMP_CONFIG_INI = """\
[COMMON]
TARGET CURRENCY = EUR
LOG_LEVEL = WARNING

[EXCHANGE RATES]
EUR/USD = 0.88292

[TAX JURISDICTION]
TAX_COUNTRY = PT
FISCAL_YEAR = 2025
ZERO_BASIS_REVIEW_THRESHOLD = 50
ZERO_BASIS_REVIEW_MIN_PROCEEDS = 10
"""


_OPTED_IN_CONFIG_INI = """\
[COMMON]
TARGET CURRENCY = EUR
LOG_LEVEL = WARNING

[EXCHANGE RATES]
EUR/USD = 0.88292

[TAX JURISDICTION]
TAX_COUNTRY = PT
FISCAL_YEAR = 2025
ZERO_BASIS_REVIEW_THRESHOLD = 50
ZERO_BASIS_REVIEW_MIN_PROCEEDS = 10
ON_CHAIN_TH_WALLETS = Ledger Berachain (BERA)
"""


@pytest.mark.unit
class TestMainCompositionRoot:
    """Pin the env gate: fetch bound iff ``BERA_CHAIN_API_KEY`` present."""

    @staticmethod
    def _drive(tmp_path, monkeypatch) -> tuple[dict, Path]:
        """Prepare the tmp config + patched collaborators, run ``_main``, return kwargs + log path.

        Returns ``(captured_run_report_kwargs, log_path)``. ``run_report`` is
        replaced by a capture stub (so no pipeline runs), and the audit log is
        redirected into tmp_path so the construction-time WARNING can be read
        from disk (the root-logger reconfigure detaches caplog).
        """
        (tmp_path / "config.ini").write_text(_TMP_CONFIG_INI, encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        captured: dict = {}

        def _capture_run_report(**kwargs) -> None:
            captured.update(kwargs)

        monkeypatch.setattr(main_module, "run_report", _capture_run_report)

        tmp_log = tmp_path / "audit.log"
        real_configure = main_module.configure_application_logging

        def _redirecting_configure(*args, **kwargs):  # type: ignore[no-untyped-def]
            kwargs["log_file"] = tmp_log
            return real_configure(*args, **kwargs)

        monkeypatch.setattr(main_module, "configure_application_logging", _redirecting_configure)

        # Snapshot root handlers/level and restore afterwards (r2 overflow: ``_main``
        # reconfigures the root logger, so without the TestCliMain-style try/finally
        # the fresh StreamHandler/FileHandler pair leaks into other tests).
        root = logging.getLogger()
        original_level = root.level
        original_handlers = list(root.handlers)
        try:
            _main(source_file=tmp_path / "ib_export.csv", output_dir=tmp_path, log_level="WARNING")
        finally:
            # Close ONLY the handlers this run added, then re-attach the snapshotted
            # originals. Production ``configure_application_logging`` CLOSES the
            # original handlers while reconfiguring the root logger; we re-attach
            # the (possibly closed) original handler objects regardless, so root
            # never ends the test with zero handlers.
            for handler in list(root.handlers):
                if handler not in original_handlers:
                    handler.close()
                    root.handlers.remove(handler)
            for handler in original_handlers:
                if handler not in root.handlers:
                    root.handlers.append(handler)
            root.setLevel(original_level)
        return captured, tmp_log

    def test_env_key_binds_fetcher(self, tmp_path, monkeypatch):
        """Env gate ON: ``BERA_CHAIN_API_KEY=x`` -> non-None partial over ``run_on_chain_fetch``.

        Pins the DI-3 binding shape: the injected ``on_chain_fetch`` is
        ``functools.partial(run_on_chain_fetch, api_key="x")`` - the pipeline
        later calls it with ``year=``/``output_dir=`` only.
        """
        monkeypatch.setenv("BERA_CHAIN_API_KEY", "x")

        captured, _ = self._drive(tmp_path, monkeypatch)

        fetch = captured["on_chain_fetch"]
        assert fetch is not None, "on_chain_fetch must be bound when the env var is set"
        assert isinstance(fetch, functools.partial)
        assert fetch.func is main_module.run_on_chain_fetch, "the partial must wrap the real fetch orchestrator"
        assert fetch.args == ()
        assert fetch.keywords == {"api_key": "x"}

        # r1 F8: pin the app_config/logger threading at the _main -> run_report seam.
        # The fiscal-year literal matches FISCAL_YEAR in _TMP_CONFIG_INI above (the
        # tmp config.ini the fixture writes and the real loader parses).
        app_config = captured["app_config"]
        assert app_config is not None
        assert app_config.tax_jurisdiction.fiscal_year == 2025
        assert captured["logger"].name == "tax_reporting.main"

    def test_no_env_key_yields_none_fetcher_and_warning(self, tmp_path, monkeypatch):
        """Env gate OFF: var absent -> ``on_chain_fetch is None`` + the "not set" WARNING.

        Pins the CR-Guard-accepted construction-time widening: the WARNING
        fires whenever the gate is evaluated and the var is absent, and the
        fetch is skipped via ``None`` (single skip policy, no env tricks
        downstream).
        """
        monkeypatch.delenv("BERA_CHAIN_API_KEY", raising=False)

        captured, log_path = self._drive(tmp_path, monkeypatch)

        assert captured["on_chain_fetch"] is None, "on_chain_fetch must be None when the env var is absent"
        log_text = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
        assert "BERA_CHAIN_API_KEY not set" in log_text, (
            "the construction-time 'BERA_CHAIN_API_KEY not set' WARNING must reach the audit trail"
        )

    def test_pre_configure_failure_preserves_root_handlers(self, tmp_path, monkeypatch):
        """A failure inside the first configure call leaves root handlers untouched.

        Pins the pre-configure arm of the ``_drive`` restore (r6 deferred F2):
        when ``_main`` raises before/at its first ``configure_application_logging``
        call, the finally block must neither close nor duplicate the snapshotted
        originals. The failure is injected by making the redirected audit log
        path a directory, so the real configure raises while opening its
        FileHandler (no monkeypatch ordering fights with ``_drive``'s own patch).
        """
        monkeypatch.delenv("BERA_CHAIN_API_KEY", raising=False)
        (tmp_path / "audit.log").mkdir()  # FileHandler target occupied -> configure raises

        root = logging.getLogger()
        handlers_before = list(root.handlers)
        level_before = root.level

        with pytest.raises(Exception, match="audit.log"):
            self._drive(tmp_path, monkeypatch)

        assert root.handlers == handlers_before, (
            "pre-configure failure must leave root handlers identical (no closes, no duplicates)"
        )
        assert root.level == level_before

    def test_set_key_fetch_invoked_and_degrades(self, tmp_path, monkeypatch):
        """Canary: key SET + real ``_main`` + real ``run_report`` -> fetch invoked, DI-1 degrade.

        Pins the leaked-key residual path end to end: with the env gate ON, the
        composition root binds the fetch and ``run_report`` invokes it; a fetch
        that aborts (here: a simulated guard trip) degrades via the
        ``On-chain fetch failed`` WARNING and writes NO on-chain artifacts.

        ``run_on_chain_fetch`` itself is replaced because its FIRST operation
        opens the gitignored wallet registry (personal data): exercising the
        real fetcher would itself be the personal-data read this suite
        forbids. The hermeticity gate keeping the real fetcher out of tests is
        the ``_pin_hermetic_env`` autouse fixture (see tests/conftest.py).
        """
        monkeypatch.setenv("BERA_CHAIN_API_KEY", "canary")
        (tmp_path / "config.ini").write_text(_TMP_CONFIG_INI, encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        source_file = tmp_path / "ib_export.csv"
        source_file.write_text(
            "\n".join(
                [
                    "Statement,Header,Field Name,Field Value",
                    "Financial Instrument Information,Header,Asset Category,Symbol,Description,"
                    "Conid,Security ID,Underlying,Listing Exch.,Multiplier,Type,Code",
                    "Financial Instrument Information,Data,Stocks,ACME,ACME CORPORATION,"
                    "10000001,US0000000001,ACME,NYSE,1,COMMON,",
                    "Trades,Header,DataDiscriminator,Asset Category,Currency,Symbol,Date/Time,"
                    "Quantity,T. Price,C. Price,Proceeds,Comm/Fee,Basis,Realized P/L,MTM P/L,Code",
                    "Dividends,Header,Currency,Date,Description,Amount",
                    "Dividends,Data,EUR,2024-06-01,ACME(US0000000001) Cash Dividend EUR 0.50 per "
                    "Share (Ordinary Dividend),25.00",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        calls: list[dict] = []

        def _aborting_fetch(*, year: int, output_dir: Path, api_key: str) -> Path | None:
            calls.append({"year": year, "output_dir": output_dir, "api_key": api_key})
            raise RuntimeError("canary simulated guard abort")

        monkeypatch.setattr(main_module, "run_on_chain_fetch", _aborting_fetch)

        tmp_log = tmp_path / "audit.log"
        real_configure = main_module.configure_application_logging

        def _redirecting_configure(*args, **kwargs):  # type: ignore[no-untyped-def]
            kwargs["log_file"] = tmp_log
            return real_configure(*args, **kwargs)

        monkeypatch.setattr(main_module, "configure_application_logging", _redirecting_configure)

        root = logging.getLogger()
        original_level = root.level
        original_handlers = list(root.handlers)
        try:
            _main(source_file=source_file, output_dir=tmp_path, log_level="WARNING")
        finally:
            for handler in list(root.handlers):
                if handler not in original_handlers:
                    handler.close()
                    root.handlers.remove(handler)
            for handler in original_handlers:
                if handler not in root.handlers:
                    root.handlers.append(handler)
            root.setLevel(original_level)

        assert len(calls) == 1, "the injected fetch must be invoked exactly once when the key is set"
        assert calls[0]["year"] == 2025, "fetch year must resolve from the config jurisdiction (DI-9)"
        assert calls[0]["api_key"] == "canary"
        log_text = tmp_log.read_text(encoding="utf-8") if tmp_log.exists() else ""
        assert "On-chain fetch failed" in log_text, "a failing fetch must degrade via the DI-1 WARNING"
        assert "canary simulated guard abort" in log_text
        assert not (tmp_path / "2025" / "bera_transactions.csv").exists(), (
            "no on-chain artifacts may be written when the fetch aborts"
        )

    @staticmethod
    def _write_synthetic_bera_csv(out_dir: Path) -> None:
        """Write the synthetic ``bera_transactions.csv`` under ``<out>/2025`` (hermetic)."""
        bera_csv_dir = out_dir / "2025"
        bera_csv_dir.mkdir(parents=True)
        bera_wallet_addr = "0xabcabcabcabcabcabcabcabcabcabcabcabcabca"
        dex_router = "0x000000000000000000000000000000000000dead"
        reward_distributor = "0x000000000000000000000000000000000000beef"
        bera_csv_header = (
            "tx_hash,block_number,timestamp_utc,chain,from_address,to_address,"
            "asset,token_address,amount_raw,amount_decimals,direction,fee_asset,"
            "fee_amount_raw,wallet_label,wallet_address"
        )
        bera_csv = "\n".join(
            [
                bera_csv_header,
                f"0xaaa111,1000,2025-02-25T13:53:25+00:00,Berachain,"
                f"{dex_router},{bera_wallet_addr},HONEY,0x000000000000000000000000000000000000a111,"
                f"1000000000000000000,18,in,BERA,2100000000000,Ledger Berachain (BERA),{bera_wallet_addr}",
                f"0xaaa111,1000,2025-02-25T13:53:25+00:00,Berachain,"
                f"{bera_wallet_addr},{dex_router},BERA,,2000000000000000000,18,out,BERA,2100000000000,"
                f"Ledger Berachain (BERA),{bera_wallet_addr}",
                f"0xbbb222,1001,2025-02-26T10:00:00+00:00,Berachain,"
                f"{reward_distributor},{bera_wallet_addr},BGT,0x000000000000000000000000000000000000b222,"
                f"500000000000000000,18,in,BERA,2100000000000,Ledger Berachain (BERA),{bera_wallet_addr}",
                "",
            ]
        )
        (bera_csv_dir / "bera_transactions.csv").write_text(bera_csv, encoding="utf-8")

    def test_opted_in_on_chain_e2e_env_pinned(self, tmp_path, monkeypatch, capsys):
        """Main()-level e2e: opted-in on-chain TH run completes end to end.

        The ONE ``main()``-level e2e relocated from the opted-in on-chain e2e
        suite (Plan Task 5). Drives the full composition root: a real tmp
        ``config.ini`` carrying ``ON_CHAIN_TH_WALLETS`` (no loader patching),
        the committed example IB export, a synthetic Koinly dir + a synthetic
        ``bera_transactions.csv`` under tmp_path (committed synthetic data per
        AGENTS.md), and the env PINNED OFF (``BERA_CHAIN_API_KEY`` deleted) so
        the bound fetch is skipped - no network, hermetic by construction.

        Seam-less collaborators are patched on the namespace the orchestrator
        calls them through (Gist patching policy): the
        Koinly-directory/year-hint helpers on
        ``tax_reporting.application.run_report``; the contracts/LP loaders and
        repo-root resolver on ``tax_reporting.application.on_chain_th_substitution``.
        Asserts the run completes and the Crypto Reconciliation sheet exists
        (same observable as the e2e-suite variant).
        """
        import openpyxl

        project_root = Path(__file__).resolve().parents[3]
        example_source = project_root / "resources" / "source" / "example" / "ib_export.csv"
        example_koinly = project_root / "resources" / "source" / "example" / "2025" / "koinly"
        example_contracts = project_root / "resources" / "source" / "example" / "2025" / "berachain_contracts.json"
        example_lp_snapshot = project_root / "resources" / "source" / "example" / "2025" / "berachain_lp_snapshot.json"

        (tmp_path / "config.ini").write_text(_OPTED_IN_CONFIG_INI, encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("BERA_CHAIN_API_KEY", raising=False)

        import shutil

        koinly_dir = tmp_path / "koinly"
        koinly_dir.mkdir()
        shutil.copy(
            example_koinly / "koinly_2025_capital_gains_report.csv",
            koinly_dir / "koinly_2025_capital_gains_report.csv",
        )
        shutil.copy(
            example_koinly / "koinly_2025_income_report.csv",
            koinly_dir / "koinly_2025_income_report.csv",
        )
        synthetic_th = (
            "Transaction report 2025\n"
            "\n"
            "Date,Type,Tag,Sending Wallet,Sent Amount,Sent Currency,Sent Cost Basis,"
            "Receiving Wallet,Received Amount,Received Currency,Received Cost Basis,"
            "Fee Amount,Fee Currency,Gain (EUR),Net Value (EUR),Fee Value (EUR),"
            "TxSrc,TxDest,TxHash,Description\n"
            "2025-01-10 09:00:00 UTC,crypto_deposit,,ByBit,0,,,"
            "Ledger Berachain (BERA),5,BERA,5,,,5,5,,0xfrom,0xto,0xkoInlybera1,\n"
            "2025-01-11 09:00:00 UTC,crypto_deposit,,ByBit,0,,,"
            "ByBit,2,ETH,2,,,2,2,,0xfrom2,0xto2,0xkoInlyother1,\n"
        )
        (koinly_dir / "koinly_2025_transaction_history.csv").write_text(synthetic_th, encoding="utf-8")

        out_dir = tmp_path / "out"
        self._write_synthetic_bera_csv(out_dir)

        import tax_reporting.application.run_report as run_report_module
        from tax_reporting.application import on_chain_config as _oc
        from tax_reporting.application import on_chain_th_substitution as _subst

        monkeypatch.setattr(_subst, "load_contracts", lambda _path: _oc.load_contracts(example_contracts))
        monkeypatch.setattr(_subst, "load_lp_snapshot", lambda _path: _oc.load_lp_snapshot(example_lp_snapshot))
        monkeypatch.setattr(_subst, "find_repository_root", lambda: project_root)
        monkeypatch.setattr(run_report_module, "_resolve_koinly_directory", lambda *_a, **_k: koinly_dir)
        monkeypatch.setattr(run_report_module, "_infer_tax_year_hint_from_ib_data", lambda _ib: 2025)

        # Snapshot/restore pattern mirrors ``_drive``: this e2e runs the real
        # composition root (root-logger reconfigure included).
        root = logging.getLogger()
        original_level = root.level
        original_handlers = list(root.handlers)
        try:
            _main(source_file=example_source, output_dir=out_dir, log_level="WARNING")
        finally:
            # Close ONLY the handlers this run added, then re-attach the snapshotted
            # originals (see ``_drive``: production configure closes the originals;
            # re-attach them regardless so root never ends with zero handlers).
            for handler in list(root.handlers):
                if handler not in original_handlers:
                    handler.close()
                    root.handlers.remove(handler)
            for handler in original_handlers:
                if handler not in root.handlers:
                    root.handlers.append(handler)
            root.setLevel(original_level)

        # r2 F5: pin the relocated success print (the CLI's only success-confirmation
        # output, printed at the end of ``_main``).
        captured = capsys.readouterr()
        assert "Processing completed successfully!" in captured.out, (
            "the composition-root success print must reach stdout after a completed run"
        )

        extract_path = out_dir / "extract.xlsx"
        assert extract_path.exists(), "the main()-level opted-in run must produce extract.xlsx"
        wb = openpyxl.load_workbook(extract_path)
        try:
            assert "Crypto Reconciliation" in wb.sheetnames, (
                "the Crypto Reconciliation sheet must exist after the opted-in on-chain run"
            )
        finally:
            wb.close()
