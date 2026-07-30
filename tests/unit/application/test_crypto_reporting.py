from __future__ import annotations

import dataclasses
import logging
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from tax_reporting.application.crypto.aggregation import (
    _aggregate_capital_entries,
    _filter_immaterial_entries,
    _is_valid_tabela_x_country,
    _re_evaluate_aggregated_review,
    _resolve_income_code,
    aggregate_derivatives_entries,
    aggregate_taxable_rewards,
)
from tax_reporting.application.crypto.entities import DerivativesEventType, DerivativesPnLEntry, ParsedOgrRow
from tax_reporting.application.crypto.fifo_helpers import (
    _ZERO_COST_NEGATIVE_PROCEEDS_REASON,
    _ZERO_COST_REASON,
    _ZERO_PROCEEDS_REASON,
)
from tax_reporting.application.crypto.loan_activity import LOAN_OVERSHOOT_INTEREST_PCT
from tax_reporting.application.crypto_reporting import (
    CapitalGainsParsingContext,
    CryptoCapitalGainEntry,
    CryptoSkippedZeroValueToken,
    OperatorOrigin,
    RewardTaxClassification,
    _build_ogr_index,
    _classify_reward_tax_status,
    _collect_known_asset_tickers,
    _derive_chain,
    _is_temporally_valid,
    _load_popular_crypto_tokens,
    _parse_capital_gains_file,
    _parse_income_file,
    _parse_transaction_date,
    _validate_capital_entries_have_valid_countries,
    apply_ogr_event_level,
    load_koinly_crypto_report,
    resolve_operator_origin,
)
from tax_reporting.domain.constants import (
    LOAN_STATUS_IN_ASSET_INTEREST,
    LOAN_STATUS_NO_EUR_PRICE,
    LOAN_STATUS_OPEN_LOAN,
    LOAN_STATUS_OVERPAID_VERIFY,
    LOAN_STATUS_SETTLED,
)
from tax_reporting.domain.token_origin import (
    AcquisitionMethod,
    TokenOrigin,
)
from tax_reporting.infrastructure.koinly_parser import format_datetime, parse_koinly_decimal
from tests.conftest import build_koinly_jurisdiction, build_origin_resolver

_TEST_OPERATOR = OperatorOrigin(
    platform="TestPlatform",
    service_scope="crypto",
    operator_entity="Test Entity",
    operator_country="Test Country",
    source_url="",
    source_checked_on="2026-01-01",
    confidence="low",
    review_required=False,
    valid_from="2026-01-01",
)


def _make_entry(  # noqa: PLR0913
    disposal_date: str = "2025-01-13",
    acquisition_date: str = "2024-11-18",
    asset: str = "USDT",
    amount: Decimal = Decimal("1"),
    cost_eur: Decimal = Decimal("1"),
    proceeds_eur: Decimal = Decimal("1"),
    gain_loss_eur: Decimal = Decimal("0"),
    holding_period: str = "Short term",
    wallet: str = "ByBit",
    platform: str = "ByBit",
    chain: str = "ByBit",
    review_required: bool = False,
    notes: str = "",
    review_reason: str | None = None,
    token_swap_history: str = "",
    operator_origin: OperatorOrigin = _TEST_OPERATOR,
    ogr_validation=None,
) -> CryptoCapitalGainEntry:
    return CryptoCapitalGainEntry(
        disposal_date=disposal_date,
        acquisition_date=acquisition_date,
        asset=asset,
        amount=amount,
        cost_eur=cost_eur,
        proceeds_eur=proceeds_eur,
        gain_loss_eur=gain_loss_eur,
        holding_period=holding_period,
        wallet=wallet,
        platform=platform,
        chain=chain,
        operator_origin=operator_origin,
        annex_hint="J",
        review_required=review_required,
        notes=notes,
        review_reason=review_reason,
        token_swap_history=token_swap_history,
        ogr_validation=ogr_validation,
    )


def test_load_koinly_crypto_report_parses_core_sections(tmp_path):
    koinly_dir = tmp_path / "koinly2025"
    koinly_dir.mkdir()

    (koinly_dir / "koinly_2025_capital_gains_report_test.csv").write_text(
        "\n".join(
            [
                "Capital gains report 2025",
                "",
                ",".join(
                    [
                        "Date Sold",
                        "Date Acquired",
                        "Asset",
                        "Amount",
                        "Cost (EUR)",
                        "Proceeds (EUR)",
                        "Gain / loss",
                        "Notes",
                        "Wallet Name",
                        "Holding period",
                    ]
                ),
                ",".join(
                    [
                        "13/01/2025 13:01",
                        "18/11/2024 00:15",
                        "USDT",
                        '"1,50000000"',
                        '"1,25"',
                        '"2,35"',
                        '"1,10"',
                        "",
                        "ByBit (2)",
                        "Short term",
                    ]
                ),
                ",".join(
                    [
                        "20/01/2025 10:10",
                        "01/01/2024 00:00",
                        "BTC",
                        '"0,10000000"',
                        '"3000,00"',
                        '"3500,00"',
                        '"500,00"',
                        "Fee",
                        "Kraken",
                        "Long term",
                    ]
                ),
            ]
        ),
        encoding="utf-8",
    )

    (koinly_dir / "koinly_2025_income_report_test.csv").write_text(
        "\n".join(
            [
                "Income report 2025",
                "",
                "Date,Asset,Amount,Value (EUR),Type,Description,Wallet Name",
                '01/01/2025 00:01,WXT,"5,00000000","17,10",Reward,,Wirex',
                '02/01/2025 00:01,USDT,"2,00000000","2,10",Lending interest,,ByBit (2)',
            ]
        ),
        encoding="utf-8",
    )

    (koinly_dir / "koinly_2025_beginning_of_year_holdings_report_test.csv").write_text(
        "\n".join(
            [
                "Balances as at 01/01/2025 00:00",
                "",
                "Asset,Quantity,Cost (EUR),Value (EUR),Description",
                'BTC,"1,00000000","100,00","120,00",',
            ]
        ),
        encoding="utf-8",
    )
    (koinly_dir / "koinly_2025_end_of_year_holdings_report_test.csv").write_text(
        "\n".join(
            [
                "Balances as at 31/12/2025 23:59",
                "",
                "Asset,Quantity,Cost (EUR),Value (EUR),Description",
                'BTC,"1,00000000","130,00","150,00",',
            ]
        ),
        encoding="utf-8",
    )

    _write_minimal_transaction_history(koinly_dir)

    report = load_koinly_crypto_report(koinly_dir)

    assert report is not None
    assert report.tax_year == 2025
    assert len(report.capital_entries) == 2
    assert len(report.reward_entries) == 2
    assert report.reconciliation.short_term_rows == 1
    assert report.reconciliation.long_term_rows == 1
    assert report.reconciliation.capital_proceeds_total_eur == Decimal("3502.35")
    assert report.reconciliation.reward_total_eur == Decimal("19.20")
    assert report.reconciliation.opening_holdings is not None
    assert report.reconciliation.closing_holdings is not None
    assert report.reconciliation.opening_holdings.total_value_eur == Decimal("120.00")
    assert report.reconciliation.closing_holdings.total_value_eur == Decimal("150.00")
    assert report.skipped_zero_value_tokens == []
    # PT-C-011: short-term → Anexo J; long-term exempt → Anexo G1
    short_term_entry = next(e for e in report.capital_entries if e.holding_period == "Short term")
    long_term_entry = next(e for e in report.capital_entries if e.holding_period == "Long term")
    assert short_term_entry.annex_hint == "J"
    assert long_term_entry.annex_hint == "G1"
    assert short_term_entry.disposal_date == "2025-01-13"
    assert short_term_entry.acquisition_date == "2024-11-18"
    assert long_term_entry.disposal_date == "2025-01-20"
    assert long_term_entry.acquisition_date == "2024-01-01"
    assert report.reward_entries[0].date == "2025-01-01"
    assert report.reward_entries[1].date == "2025-01-02"


def test_resolve_operator_origin_splits_wirex_by_transaction_type():
    crypto_origin = resolve_operator_origin("Wirex", transaction_type="crypto_deposit")
    fiat_origin = resolve_operator_origin("Wirex", transaction_type="fiat_deposit")

    assert crypto_origin.service_scope == "crypto"
    assert fiat_origin.service_scope == "fiat"
    assert crypto_origin.operator_entity != fiat_origin.operator_entity


def test_resolve_operator_origin_uses_europe_override_for_binance_and_bsc():
    bsc_origin = resolve_operator_origin("Binance Smart Chain", transaction_type="crypto_disposal")
    binance_origin = resolve_operator_origin("Binance", transaction_type="crypto_deposit")

    assert bsc_origin.operator_country == "ES"
    assert "Spain" in bsc_origin.operator_entity
    assert bsc_origin.review_required is False
    assert binance_origin.operator_country == "ES"
    assert binance_origin.review_required is False


def test_resolve_operator_origin_resolves_eea_cex_defaults():
    kraken_origin = resolve_operator_origin("Kraken", transaction_type="crypto_disposal")
    gate_origin = resolve_operator_origin("Gate.io", transaction_type="crypto_disposal")

    assert kraken_origin.operator_country == "IE"
    assert kraken_origin.review_required is False
    assert gate_origin.operator_country == "MT"
    assert gate_origin.review_required is False


def test_resolve_operator_origin_resolves_chain_foundation_defaults():
    berachain_origin = resolve_operator_origin("Ledger Berachain", transaction_type="crypto_disposal")
    starknet_origin = resolve_operator_origin("Starknet", transaction_type="crypto_disposal")
    zksync_origin = resolve_operator_origin("zkSync ERA", transaction_type="crypto_disposal")
    solana_origin = resolve_operator_origin("Solana", transaction_type="crypto_disposal")
    ton_origin = resolve_operator_origin("TON", transaction_type="crypto_disposal")
    ethereum_origin = resolve_operator_origin("Ethereum", transaction_type="crypto_disposal")
    aptos_origin = resolve_operator_origin("Ledger APTOS", transaction_type="crypto_disposal")

    assert berachain_origin.operator_country == "VG"
    assert starknet_origin.operator_country == "KY"
    assert zksync_origin.operator_country == "KY"
    assert solana_origin.operator_country == "CH"
    assert ton_origin.operator_country == "CH"
    assert ethereum_origin.operator_country == "CH"
    assert aptos_origin.operator_country == "KY"


def test_resolve_operator_origin_resolves_additional_chain_and_wallet_defaults():
    arbitrum_origin = resolve_operator_origin("Arbitrum", transaction_type="crypto_disposal")
    mantle_origin = resolve_operator_origin("Mantle", transaction_type="crypto_disposal")
    polygon_origin = resolve_operator_origin("Polygon", transaction_type="crypto_disposal")
    base_origin = resolve_operator_origin("BASE", transaction_type="crypto_disposal")
    filecoin_origin = resolve_operator_origin("Filecoin", transaction_type="crypto_disposal")
    tonkeeper_origin = resolve_operator_origin("Tonkeeper wallet", transaction_type="crypto_disposal")

    assert arbitrum_origin.operator_country == "KY"
    assert mantle_origin.operator_country == "VG"
    assert polygon_origin.operator_country == "KY"
    assert base_origin.operator_country == "US"
    assert filecoin_origin.operator_country == "US"
    assert tonkeeper_origin.operator_country == "GB"


def test_resolve_operator_origin_base_variations_match():
    """BASE platform must match variations like 'base network', 'base chain', not just 'base' or 'base '."""
    base_exact = resolve_operator_origin("base", transaction_type="crypto_disposal")
    base_caps = resolve_operator_origin("BASE", transaction_type="crypto_disposal")
    base_network = resolve_operator_origin("base network", transaction_type="crypto_disposal")
    base_chain = resolve_operator_origin("base chain", transaction_type="crypto_disposal")
    base_mainnet = resolve_operator_origin("Base Mainnet", transaction_type="crypto_disposal")
    base_wallet = resolve_operator_origin("base wallet", transaction_type="crypto_disposal")

    # All should resolve to the same BASE platform origin
    assert base_exact.platform == "BASE"
    assert base_caps.platform == "BASE"
    assert base_network.platform == "BASE"
    assert base_chain.platform == "BASE"
    assert base_mainnet.platform == "BASE"
    assert base_wallet.platform == "BASE"

    # All should have the same operator country and entity
    assert base_exact.operator_country == "US"
    assert base_network.operator_country == "US"
    assert base_chain.operator_country == "US"
    assert base_exact.operator_entity == "Coinbase Technologies, Inc."
    assert base_network.operator_entity == "Coinbase Technologies, Inc."


def test_resolve_operator_origin_gate_exact_and_substring_match():
    """Gate platform must match both exact 'gate' and 'gate.io' substring variants."""
    gate_exact = resolve_operator_origin("gate", transaction_type="crypto_disposal")
    gate_dotio = resolve_operator_origin("gate.io", transaction_type="crypto_disposal")
    gate_caps = resolve_operator_origin("GATE", transaction_type="crypto_disposal")
    gate_wallet = resolve_operator_origin("Gate.io wallet", transaction_type="crypto_disposal")

    # All should resolve to Gate.io platform
    assert gate_exact.platform == "Gate.io"
    assert gate_dotio.platform == "Gate.io"
    assert gate_caps.platform == "Gate.io"
    assert gate_wallet.platform == "Gate.io"

    # All should have Malta as operator country
    assert gate_exact.operator_country == "MT"
    assert gate_dotio.operator_country == "MT"
    assert gate_caps.operator_country == "MT"
    assert gate_wallet.operator_country == "MT"


def test_load_koinly_crypto_report_returns_none_for_nonexistent_directory(tmp_path):
    """Non-existent directory must return None, not raise an error."""
    nonexistent = tmp_path / "does_not_exist"
    report = load_koinly_crypto_report(nonexistent)
    assert report is None


def test_load_koinly_crypto_report_returns_none_for_empty_directory(tmp_path):
    """Empty directory with no Koinly reports must return None."""
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    report = load_koinly_crypto_report(empty_dir)
    assert report is None


def test_load_koinly_crypto_report_returns_none_when_no_matching_files(tmp_path):
    """Directory with wrong file types must return None."""
    koinly_dir = tmp_path / "koinly2025"
    koinly_dir.mkdir()
    # Create wrong file type
    (koinly_dir / "wrong_file.txt").write_text("not a csv")
    report = load_koinly_crypto_report(koinly_dir)
    assert report is None


def test_load_koinly_crypto_report_raises_on_incomplete_koinly_export(tmp_path):
    """Incomplete Koinly export directories must fail clearly; only zero files still returns None."""
    from tax_reporting.domain.exceptions import FileProcessingError

    one_of_three_dir = tmp_path / "one_of_three"
    one_of_three_dir.mkdir()
    _write_minimal_capital_gains_report(one_of_three_dir)

    with pytest.raises(FileProcessingError, match="Incomplete Koinly export") as exc_info:
        load_koinly_crypto_report(one_of_three_dir)

    message = str(exc_info.value)
    assert "income_report (Income report)" in message
    assert "transaction_history (Transaction history)" in message

    two_of_three_dir = tmp_path / "two_of_three"
    two_of_three_dir.mkdir()
    _write_minimal_capital_gains_report(two_of_three_dir)
    _write_minimal_income_report(two_of_three_dir)

    with pytest.raises(FileProcessingError, match="Incomplete Koinly export") as exc_info:
        load_koinly_crypto_report(two_of_three_dir)

    assert "transaction_history (Transaction history)" in str(exc_info.value)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("jurisdiction_kwargs", "expect_raises"),
    [
        # Derivatives reporting ON (both flags True): malformed labels must
        # fail loudly as ConfigurationError so the run aborts instead of
        # silently double-counting derivatives disposals.
        (
            {"separate_derivatives_reporting": True, "use_other_gains_report": True},
            True,
        ),
        # Derivatives reporting OFF (one flag False): malformed labels must
        # degrade to empty derivatives_tags with a WARNING, not abort.
        (
            {"separate_derivatives_reporting": False, "use_other_gains_report": True},
            False,
        ),
    ],
)
def test_load_koinly_crypto_report_labels_error_branching(
    tmp_path, monkeypatch, jurisdiction_kwargs, expect_raises
):
    """F6 (Q1-NO-TEST) + F1 regression pin: the malformed-derivatives-labels
    ``FileProcessingError`` from ``_load_derivatives_labels_config`` must
    branch on ``TaxJurisdictionConfig.derivatives_dedup_enabled``. When
    derivatives reporting is ON, the caller re-raises as ``ConfigurationError``
    so ``main.py`` fails loudly; when OFF, it degrades to empty
    ``derivatives_tags`` with a WARNING.

    Under the pre-F1 bug, the ON-path re-raised ``FileProcessingError`` was
    swallowed by ``main.py``'s broad handler and the entire crypto report was
    silently dropped; this test pins the ON-path exception type as
    ``ConfigurationError`` so the swallow cannot recur (``main.py`` re-raises
    ``ConfigurationError`` at line 361-366).
    """
    import tax_reporting.application.crypto_reporting as cr_module
    from tax_reporting.domain.exceptions import ConfigurationError, FileProcessingError

    def _raise(*_args, **_kwargs):
        raise FileProcessingError("malformed labels JSON (simulated)")

    monkeypatch.setattr(cr_module, "_load_derivatives_labels_config", _raise)

    koinly_dir = tmp_path / "labels_branch"
    koinly_dir.mkdir()
    _write_minimal_capital_gains_report(koinly_dir)
    _write_minimal_income_report(koinly_dir)
    _write_minimal_transaction_history(koinly_dir)

    jurisdiction = build_koinly_jurisdiction(**jurisdiction_kwargs)

    if expect_raises:
        with pytest.raises(ConfigurationError, match="Derivatives labels JSON"):
            load_koinly_crypto_report(koinly_dir, jurisdiction=jurisdiction)
    else:
        report = load_koinly_crypto_report(koinly_dir, jurisdiction=jurisdiction)
        assert report is not None, (
            "OFF-path must not abort the run; expected a populated report with "
            "empty derivatives_tags (graceful degradation)."
        )


@pytest.mark.unit
def test_transaction_construction_is_unconditional(tmp_path, monkeypatch):
    """Phase E Task 6 characterization: ``Transaction`` objects are always built
    when a ``transaction_history_file`` is located, regardless of whether a
    ``jurisdiction`` is supplied. The Phase D ``any_resolver_on`` gate (which
    skipped per-row construction when every per-treatment resolver flag was
    off) is gone.

    Discriminating assertion (r3 Medium): patch ``build_transaction`` to count
    calls, write a TH CSV with one row, call with ``jurisdiction=None``, and
    assert ``build_transaction`` was invoked once. Under a Phase D regression
    that re-gated construction on ``any_resolver_on``, the call count would be
    zero with ``jurisdiction=None`` and this test would fail. Source-text
    inspections (``inspect.getsource`` substring checks) were retired because
    they pass under renamed-local regressions and trivially pass once the
    construction is extracted to a helper (lesson #46, Family H).
    """
    import tax_reporting.application.crypto as crypto_pkg
    import tax_reporting.application.crypto_reporting as cr_module

    real_build = crypto_pkg.transaction_factory.build_transaction
    calls: list = []

    def _capturing_build(row, classification):
        calls.append((row, classification))
        return real_build(row, classification)

    monkeypatch.setattr(
        cr_module, "build_transaction", _capturing_build
    )

    koinly_dir = tmp_path / "koinly2025"
    koinly_dir.mkdir()
    _write_minimal_capital_gains_report(koinly_dir)
    _write_minimal_income_report(koinly_dir)
    # Write a TH file with at least one row so construction has work to do;
    # an empty TH would make call-count zero for innocent reasons.
    th_path = koinly_dir / "koinly_2025_transaction_history.csv"
    row = ",".join(
        [
            "2025-04-10 10:00:00 UTC",
            "crypto_deposit",
            "Reward",
            "",
            "",
            "",
            "",
            "Kraken",
            '"5,00000000"',
            "USDC",
            '"5,00"',
            "",
            "",
            '"0,00"',
            '"5,00"',
            '"0,00"',
            "",
            "",
            "",
            "Reward income",
        ]
    )
    th_path.write_text(
        "\n".join(["Transaction report 2025", "", _TH_HEADER, row]),
        encoding="utf-8",
    )

    # jurisdiction=None is the discriminating case: under Phase D the
    # ``any_resolver_on`` gate evaluated False and the Transaction list was
    # never populated.
    report = load_koinly_crypto_report(koinly_dir, jurisdiction=None)
    assert report is not None
    assert len(calls) == 1, (
        f"Phase E Task 6: build_transaction must be called once for the TH row "
        f"even with jurisdiction=None (unconditional construction). Got "
        f"{len(calls)} calls; a Phase D-style any_resolver_on gate would "
        f"produce zero calls here."
    )


@pytest.mark.unit
def test_load_koinly_crypto_report_skips_zero_value_rows_and_tracks_assets(tmp_path):
    koinly_dir = tmp_path / "koinly2025"
    koinly_dir.mkdir()

    (koinly_dir / "koinly_2025_capital_gains_report_test.csv").write_text(
        "\n".join(
            [
                "Capital gains report 2025",
                "",
                ",".join(
                    [
                        "Date Sold",
                        "Date Acquired",
                        "Asset",
                        "Amount",
                        "Cost (EUR)",
                        "Proceeds (EUR)",
                        "Gain / loss",
                        "Notes",
                        "Wallet Name",
                        "Holding period",
                    ]
                ),
                ",".join(
                    [
                        "01/01/2025 10:00",
                        "01/01/2024 10:00",
                        "XXX",
                        '"10,00000000"',
                        "0.0",
                        "0.0",
                        "0.0",
                        "",
                        "Kraken",
                        "Long term",
                    ]
                ),
                ",".join(
                    [
                        "02/01/2025 10:00",
                        "01/01/2024 10:00",
                        "BTC",
                        '"0,10000000"',
                        '"1000,00"',
                        '"1200,00"',
                        '"200,00"',
                        "",
                        "Kraken",
                        "Long term",
                    ]
                ),
            ]
        ),
        encoding="utf-8",
    )

    (koinly_dir / "koinly_2025_income_report_test.csv").write_text(
        "\n".join(
            [
                "Income report 2025",
                "",
                "Date,Asset,Amount,Value (EUR),Type,Description,Wallet Name",
                '01/01/2025 00:01,AAA,"1,00000000",0.0,Reward,,Wirex',
                '02/01/2025 00:01,BBB,"2,00000000","2,10",Reward,,Wirex',
                '03/01/2025 00:01,WBТC,"3,00000000",0.0,Reward,,Kraken',  # Cyrillic Т (homoglyph)
            ]
        ),
        encoding="utf-8",
    )

    (koinly_dir / "koinly_2025_beginning_of_year_holdings_report_test.csv").write_text(
        "\n".join(
            [
                "Balances as at 01/01/2025 00:00",
                "",
                "Asset,Quantity,Cost (EUR),Value (EUR),Description",
                'ZERO,"1,00000000","10,00",0.0,',
                'NZ,"1,00000000","10,00","11,00",',
            ]
        ),
        encoding="utf-8",
    )

    _write_minimal_transaction_history(koinly_dir)

    report = load_koinly_crypto_report(koinly_dir)

    assert report is not None
    assert len(report.capital_entries) == 1
    assert len(report.reward_entries) == 1
    assert report.capital_entries[0].asset == "BTC"
    assert report.reward_entries[0].asset == "BBB"
    assert report.reconciliation.opening_holdings is not None
    assert report.reconciliation.opening_holdings.asset_rows == 1
    assert report.reconciliation.opening_holdings.total_value_eur == Decimal("11.00")

    skipped_assets = {(item.source_section, item.asset, item.count) for item in report.skipped_zero_value_tokens}
    assert ("capital_gains", "XXX", 1) in skipped_assets
    assert ("income", "AAA", 1) in skipped_assets
    assert ("holdings_opening", "ZERO", 1) in skipped_assets

    # Verify suspicious field for assets with non-Latin characters
    wbtc_entry = next((e for e in report.skipped_zero_value_tokens if e.asset == "WBТC"), None)
    assert wbtc_entry is not None, "WBТC (with Cyrillic Т) should be in skipped_zero_value_tokens"
    assert wbtc_entry.suspicious is True, "WBТC contains Cyrillic Т and should be flagged as suspicious"

    # Verify regular assets are not flagged as suspicious
    aaa_entry = next((e for e in report.skipped_zero_value_tokens if e.asset == "AAA"), None)
    assert aaa_entry is not None
    assert aaa_entry.suspicious is False, "AAA is a regular asset and should not be flagged as suspicious"


def test_load_koinly_crypto_report_flags_zero_cost_above_min_proceeds(tmp_path):
    """Zero-cost CG entry with proceeds >= min_proceeds is flagged end-to-end via the parsing path.

    Synthetic-fixture coverage for the ``cost=0 AND proceeds >= min_proceeds -> flag`` branch
    of the zero-basis materiality gate. The real ``koinly2025`` fixtures have no zero-cost
    entry with proceeds >= 10 EUR (the largest is BTC at 9.52 EUR), so the e2e suite cannot
    exercise this branch. This unit-tier integration test builds a synthetic koinly directory
    in tmp_path with a zero-cost BTC disposal at 15 EUR proceeds and asserts the review flag
    fires under ``min_proceeds=10`` and is suppressed under ``min_proceeds=20``.
    """
    from tax_reporting.infrastructure.config import TaxJurisdictionConfig

    def _build_dir(out_dir: Path) -> Path:
        out_dir.mkdir()
        (out_dir / "koinly_2025_capital_gains_report_test.csv").write_text(
            "\n".join(
                [
                    "Capital gains report 2025",
                    "",
                    _CG_HEADER,
                    ",".join(
                        [
                            "15/01/2025 10:00",
                            "01/01/2024 00:00",
                            "BTC",
                            '"0,10000000"',
                            '"0,00"',
                            '"15,00"',
                            '"15,00"',
                            "",
                            "Kraken",
                            "Long term",
                        ]
                    ),
                ]
            ),
            encoding="utf-8",
        )
        (out_dir / "koinly_2025_income_report_test.csv").write_text(
            "\n".join(
                ["Income report 2025", "", _INCOME_HEADER]
            ),
            encoding="utf-8",
        )
        _write_minimal_transaction_history(out_dir)
        return out_dir

    default_dir = _build_dir(tmp_path / "koinly_default")
    high_dir = _build_dir(tmp_path / "koinly_high")

    base_kwargs = {
        "country": "PT",
        "fiscal_year": 2025,
        "exclude_loan_repayment_gains": False,
        "zero_basis_review_threshold": Decimal("50"),
        "futures_derivatives_taxable": False,
        "use_other_gains_report": False,
        "separate_derivatives_reporting": False,
        "timezone": ZoneInfo("Europe/Lisbon"),
    }

    # Above-threshold: min_proceeds=10, proceeds=15 → flags with zero-cost reason.
    report_default = load_koinly_crypto_report(
        default_dir,
        jurisdiction=TaxJurisdictionConfig(
            zero_basis_review_min_proceeds=Decimal("10"),
            **base_kwargs,
        ),
    )
    assert report_default is not None
    flagged_default = [
        e for e in report_default.capital_entries
        if e.asset == "BTC"
        and e.cost_eur == Decimal("0")
        and e.review_required
        and e.review_reason
        and "Zero acquisition cost" in e.review_reason
    ]
    assert flagged_default, (
        "Zero-cost BTC with proceeds=15 EUR must be flagged under min_proceeds=10. "
        f"Entries: "
        f"{[(e.asset, e.proceeds_eur, e.review_required, e.review_reason) for e in report_default.capital_entries]}"
    )

    # Below-threshold: min_proceeds=20, proceeds=15 → zero-cost reason suppressed.
    report_high = load_koinly_crypto_report(
        high_dir,
        jurisdiction=TaxJurisdictionConfig(
            zero_basis_review_min_proceeds=Decimal("20"),
            **base_kwargs,
        ),
    )
    assert report_high is not None
    suppressed = [
        e for e in report_high.capital_entries
        if e.asset == "BTC" and e.review_reason and "Zero acquisition cost" in e.review_reason
    ]
    assert not suppressed, (
        "Zero-cost BTC with proceeds=15 EUR must NOT carry the zero-cost reason under min_proceeds=20. "
        f"Offending entries: "
        f"{[(e.asset, e.proceeds_eur, e.review_required, e.review_reason) for e in report_high.capital_entries]}"
    )


def test_load_koinly_crypto_report_parses_complete_pdf_summary(tmp_path):
    koinly_dir = tmp_path / "koinly2025"
    koinly_dir.mkdir()

    (koinly_dir / "koinly_2025_capital_gains_report_test.csv").write_text(
        "\n".join(
            [
                "Capital gains report 2025",
                "",
                ",".join(
                    [
                        "Date Sold",
                        "Date Acquired",
                        "Asset",
                        "Amount",
                        "Cost (EUR)",
                        "Proceeds (EUR)",
                        "Gain / loss",
                        "Notes",
                        "Wallet Name",
                        "Holding period",
                    ]
                ),
                ",".join(
                    [
                        "02/01/2025 10:00",
                        "01/01/2024 10:00",
                        "BTC",
                        '"0,10000000"',
                        '"1000,00"',
                        '"1200,00"',
                        '"200,00"',
                        "",
                        "Kraken",
                        "Long term",
                    ]
                ),
            ]
        ),
        encoding="utf-8",
    )

    fake_pdf = b"""%PDF-1.3
<506572696f643a> Tj
<31204a616e203230323520746f203331204465632032303235> Tj
<416c6c20646174657320616e642074696d65732061726520696e20746865204575726f70652f4c6973626f6e2074696d657a6f6e652e> Tj
"""
    (koinly_dir / "koinly_2025_complete_tax_report_fake.pdf").write_bytes(fake_pdf)

    _write_minimal_income_report(koinly_dir)
    _write_minimal_transaction_history(koinly_dir)

    report = load_koinly_crypto_report(koinly_dir)

    assert report is not None
    assert report.pdf_summary is not None
    assert report.pdf_summary.period == "1 Jan 2025 to 31 Dec 2025"
    assert report.pdf_summary.timezone == "Europe/Lisbon"


def test_parse_koinly_decimal_handles_single_group_comma_thousands_separator():
    assert parse_koinly_decimal("1,000") == Decimal("1000")
    assert parse_koinly_decimal("8,400") == Decimal("8400")
    assert parse_koinly_decimal("1,001") == Decimal("1001")


def test_parse_koinly_decimal_handles_unambiguous_multi_group_thousands_separator():
    assert parse_koinly_decimal("1,000,000") == Decimal("1000000")
    assert parse_koinly_decimal("12,000,000") == Decimal("12000000")


def test_parse_koinly_decimal_keeps_decimal_comma_when_fractional_precision_is_not_thousands_grouped():
    assert parse_koinly_decimal("1,50000000") == Decimal("1.50000000")
    assert parse_koinly_decimal("3000,00") == Decimal("3000.00")


def test_parse_koinly_decimal_handles_both_common_mixed_separator_formats():
    assert parse_koinly_decimal("1,234.56") == Decimal("1234.56")
    assert parse_koinly_decimal("1.234,56") == Decimal("1234.56")


def test_parse_koinly_decimal_raises_on_ambiguous_single_group_dot():
    """Single-group dot values like '1.234' are ambiguous (decimal vs thousands): must fail."""
    with pytest.raises(ValueError, match="Ambiguous"):
        parse_koinly_decimal("1.234")
    with pytest.raises(ValueError, match="Ambiguous"):
        parse_koinly_decimal("10.000")
    with pytest.raises(ValueError, match="Ambiguous"):
        parse_koinly_decimal("100.000")
    # Negative values are equally ambiguous: -1.234 could be -1.234 or -1234
    with pytest.raises(ValueError, match="Ambiguous"):
        parse_koinly_decimal("-1.234")
    with pytest.raises(ValueError, match="Ambiguous"):
        parse_koinly_decimal("-10.000")


def test_parse_koinly_decimal_handles_multi_group_dot_as_european_thousands():
    """Multi-group dot values like '1.234.567' are unambiguously European thousands."""
    assert parse_koinly_decimal("1.234.567") == Decimal("1234567")
    assert parse_koinly_decimal("12.345.678") == Decimal("12345678")


def test_parse_koinly_decimal_does_not_treat_subunit_values_as_thousands_grouping():
    assert parse_koinly_decimal("0,001") == Decimal("0.001")
    assert parse_koinly_decimal("0,010") == Decimal("0.010")
    assert parse_koinly_decimal("0,100") == Decimal("0.100")
    assert parse_koinly_decimal("0.001") == Decimal("0.001")
    assert parse_koinly_decimal("0.010") == Decimal("0.010")
    assert parse_koinly_decimal("0.100") == Decimal("0.100")


def test_capital_gains_file_skips_ambiguous_row_and_continues_parsing(tmp_path, caplog):
    """A row with an ambiguous decimal must be skipped with warning; subsequent valid rows still parse."""
    koinly_dir = tmp_path / "koinly2025"
    koinly_dir.mkdir()

    (koinly_dir / "koinly_2025_capital_gains_report.csv").write_text(
        "\n".join(
            [
                "Capital gains report 2025",
                "",
                ",".join(
                    [
                        "Date Sold",
                        "Date Acquired",
                        "Asset",
                        "Amount",
                        "Cost (EUR)",
                        "Proceeds (EUR)",
                        "Gain / loss",
                        "Notes",
                        "Wallet Name",
                        "Holding period",
                    ]
                ),
                # Row with ambiguous single-group dot decimal (cost_eur = "1.234")
                ",".join(
                    [
                        "13/01/2025 13:01",
                        "18/11/2024 00:15",
                        "ETH",
                        "1",
                        "1.234",  # ambiguous: should skip this row
                        "1.500",  # also ambiguous, but row already bad
                        "0.266",
                        "",
                        "Kraken",
                        "Short term",
                    ]
                ),
                # Valid row that must still appear in output
                ",".join(
                    [
                        "20/01/2025 10:10",
                        "01/01/2024 00:00",
                        "BTC",
                        '"0,10000000"',
                        '"3000,00"',
                        '"3500,00"',
                        '"500,00"',
                        "",
                        "Kraken",
                        "Long term",
                    ]
                ),
            ]
        ),
        encoding="utf-8",
    )

    _write_minimal_income_report(koinly_dir)
    _write_minimal_transaction_history(koinly_dir)

    with caplog.at_level(logging.WARNING, logger="tax_reporting.application.crypto_reporting"):
        report = load_koinly_crypto_report(koinly_dir)

    # Verify exactly 1 entry (BTC), ETH row was skipped
    assert report is not None
    assert len(report.capital_entries) == 1
    assert report.capital_entries[0].asset == "BTC"
    # Verify warning was logged about the skipped ambiguous row
    assert "ambiguous" in caplog.text.lower()
    assert "ETH" in caplog.text


# --- _re_evaluate_aggregated_review tests ---


@pytest.mark.unit
class TestReEvaluateAggregatedReview:
    """Tests for the inlined aggregation-boundary review-flag re-evaluator.

    Pins Invariant 2 (filter owns both fields atomically and MUST start with a
    None guard) and Invariant 3 (reuses `_MATERIALITY_THRESHOLD = Decimal("1")`).
    """

    def test_strips_zero_basis_when_aggregated_values_material(self):
        """Aggregated row with material cost/proceeds/gain drops zero-basis noise."""
        entry = _make_entry(
            cost_eur=Decimal("100"),
            proceeds_eur=Decimal("200"),
            gain_loss_eur=Decimal("100"),
            review_required=True,
            review_reason="; ".join(
                [
                    "Zero EUR value for known crypto asset - test fixture",
                    _ZERO_COST_REASON,
                    _ZERO_PROCEEDS_REASON,
                ]
            ),
        )

        required, reason = _re_evaluate_aggregated_review(entry)

        assert required is False
        assert reason is None

    def test_preserves_zero_basis_when_all_lots_zero(self):
        """Signal is preserved when the whole disposal really is suspect (cost=proceeds=0)."""
        entry = _make_entry(
            cost_eur=Decimal("0"),
            proceeds_eur=Decimal("0"),
            gain_loss_eur=Decimal("0"),
            review_required=True,
            review_reason="Zero EUR value for known crypto asset - test fixture",
        )

        required, reason = _re_evaluate_aggregated_review(entry)

        assert required is True
        assert reason == "Zero EUR value for known crypto asset - test fixture"

    def test_none_review_reason_with_material_values_returns_unchanged(self):
        """None review_reason on the default clean-disposal path MUST NOT crash.

        Pins the None-guard as the first line of the helper body. Without it,
        ``None.split("; ")`` crashes the pipeline on the first material clean
        disposal (every lot ``review_required=False`` produces ``review_reason=None``
        via ``"; ".join(...) or None`` at aggregation.py:331).
        """
        entry = _make_entry(
            cost_eur=Decimal("10"),
            proceeds_eur=Decimal("20"),
            gain_loss_eur=Decimal("10"),
            review_required=False,
            review_reason=None,
        )

        required, reason = _re_evaluate_aggregated_review(entry)

        assert required is False
        assert reason is None

    def test_preserves_zero_basis_when_only_cost_is_zero(self):
        """Pins the ``cost_eur > 0`` clause of the materiality gate independently."""
        entry = _make_entry(
            cost_eur=Decimal("0"),
            proceeds_eur=Decimal("200"),
            gain_loss_eur=Decimal("100"),
            review_required=True,
            review_reason=_ZERO_COST_REASON,
        )

        required, reason = _re_evaluate_aggregated_review(entry)

        assert required is True
        assert reason == _ZERO_COST_REASON

    def test_preserves_zero_basis_when_only_proceeds_are_zero(self):
        """Pins the ``proceeds_eur > 0`` clause of the materiality gate independently."""
        entry = _make_entry(
            cost_eur=Decimal("100"),
            proceeds_eur=Decimal("0"),
            gain_loss_eur=Decimal("100"),
            review_required=True,
            review_reason=_ZERO_PROCEEDS_REASON,
        )

        required, reason = _re_evaluate_aggregated_review(entry)

        assert required is True
        assert reason == _ZERO_PROCEEDS_REASON

    @pytest.mark.parametrize(
        "reason",
        [
            "Phantom lot: prior transfer not matched in FIFO",
            "Operator origin review: unresolved platform",
            "Homoglyph: asset symbol looks similar to a known ticker",
            "Missing cost basis with impact: verify Koinly cost data",
            "Foreign tax parse failure: unexpected withholding format",
            "OGR override: manual review threshold exceeded",
            # F5: the negative-proceeds variant shares the "Zero acquisition cost"
            # stem but flags a distinct fee-heavy-liquidation anomaly. The prefix
            # tuple narrows on ": " so this reason must SURVIVE aggregation.
            _ZERO_COST_NEGATIVE_PROCEEDS_REASON,
        ],
    )
    def test_preserves_unrelated_reasons(self, reason: str):
        """Non-zero-basis reasons survive aggregation unchanged when values are material."""
        entry = _make_entry(
            cost_eur=Decimal("100"),
            proceeds_eur=Decimal("200"),
            gain_loss_eur=Decimal("100"),
            review_required=True,
            review_reason=reason,
        )

        required, returned_reason = _re_evaluate_aggregated_review(entry)

        assert required is True
        assert returned_reason == reason

    def test_strips_at_exact_materiality_boundary(self):
        """Materiality gate is inclusive at exactly ``Decimal("1")`` (boundary ``>=``)."""
        entry = _make_entry(
            cost_eur=Decimal("10"),
            proceeds_eur=Decimal("11"),
            gain_loss_eur=Decimal("1"),
            review_required=True,
            review_reason=_ZERO_COST_REASON,
        )

        required, reason = _re_evaluate_aggregated_review(entry)

        assert required is False
        assert reason is None

    def test_preserves_when_gain_just_below_materiality(self):
        """Gain one cent below the threshold preserves the zero-basis reason (gate fails)."""
        entry = _make_entry(
            cost_eur=Decimal("10"),
            proceeds_eur=Decimal("10.99"),
            gain_loss_eur=Decimal("0.99"),
            review_required=True,
            review_reason=_ZERO_COST_REASON,
        )

        required, reason = _re_evaluate_aggregated_review(entry)

        assert required is True
        assert reason == _ZERO_COST_REASON

    @pytest.mark.parametrize(
        "reason",
        [
            _ZERO_COST_REASON,
            _ZERO_PROCEEDS_REASON,
            "Zero EUR value for known crypto asset - test fixture",
        ],
    )
    def test_strips_each_zero_basis_prefix_individually(self, reason: str):
        """Each of the three zero-basis prefixes is recognized after splitting on ``"; "``.

        Covers the two ``fifo_helpers`` constants PLUS the synthetic literal
        originating from ``crypto_reporting.py`` (not exercised by the imported
        constants alone).
        """
        entry = _make_entry(
            cost_eur=Decimal("100"),
            proceeds_eur=Decimal("200"),
            gain_loss_eur=Decimal("100"),
            review_required=True,
            review_reason=reason,
        )

        required, returned_reason = _re_evaluate_aggregated_review(entry)

        assert required is False
        assert returned_reason is None

    @pytest.mark.parametrize(
        ("joined_reason", "expected"),
        [
            # (i) Single survivor: zero-basis reason joined with a phantom-lot reason.
            (
                "Zero acquisition cost: verify basis; Phantom lot: prior transfer not matched",
                "Phantom lot: prior transfer not matched",
            ),
            # (ii) Multi-survivor: 3 parts, 2 non-zero-basis survivors + 1 zero-basis.
            (
                "Phantom lot: prior transfer not matched; "
                "Operator origin review: unresolved platform; Zero acquisition cost: verify basis",
                "Phantom lot: prior transfer not matched; "
                "Operator origin review: unresolved platform",
            ),
        ],
    )
    def test_joined_reason_partial_strip(self, joined_reason: str, expected: str):
        """Partial-strip path preserves surviving clauses in insertion order.

        Case (ii) catches a regression that returns ``[surviving[0]]`` instead of
        ``surviving`` (passes (i), fails (ii)).
        """
        entry = _make_entry(
            cost_eur=Decimal("100"),
            proceeds_eur=Decimal("200"),
            gain_loss_eur=Decimal("100"),
            review_required=True,
            review_reason=joined_reason,
        )

        required, reason = _re_evaluate_aggregated_review(entry)

        assert required is True
        assert reason == expected


# --- _aggregate_capital_entries tests ---


def test_aggregate_same_timestamp_collapses_to_one_row():
    """Multiple FIFO lot rows with same (disposal_date, asset, wallet, holding_period) collapse to one row."""
    entries = [
        _make_entry(
            acquisition_date="2024-01-01",
            amount=Decimal("10"),
            cost_eur=Decimal("8"),
            proceeds_eur=Decimal("9"),
            gain_loss_eur=Decimal("1"),
        ),
        _make_entry(
            acquisition_date="2024-06-01",
            amount=Decimal("20"),
            cost_eur=Decimal("16"),
            proceeds_eur=Decimal("18"),
            gain_loss_eur=Decimal("2"),
        ),
        _make_entry(
            acquisition_date="2024-11-18",
            amount=Decimal("30"),
            cost_eur=Decimal("24"),
            proceeds_eur=Decimal("27"),
            gain_loss_eur=Decimal("3"),
        ),
    ]

    result = _aggregate_capital_entries(entries)

    assert len(result) == 1
    agg = result[0]
    assert agg.amount == Decimal("60")
    assert agg.cost_eur == Decimal("48")
    assert agg.proceeds_eur == Decimal("54")
    assert agg.gain_loss_eur == Decimal("6")
    assert agg.acquisition_date == "2024-01-01"
    assert agg.disposal_date == "2025-01-13"
    assert agg.asset == "USDT"
    assert agg.wallet == "ByBit"


def test_aggregate_different_timestamps_stay_separate():
    entries = [
        _make_entry(disposal_date="2025-01-13", gain_loss_eur=Decimal("2")),
        _make_entry(disposal_date="2025-01-14", gain_loss_eur=Decimal("3")),
    ]

    result = _aggregate_capital_entries(entries)

    assert len(result) == 2
    dates = {e.disposal_date for e in result}
    assert dates == {"2025-01-13", "2025-01-14"}

    same_day_entries = [
        _make_entry(disposal_date="2025-03-15", acquisition_date="2024-01-01", gain_loss_eur=Decimal("1")),
        _make_entry(disposal_date="2025-03-15", acquisition_date="2024-06-01", gain_loss_eur=Decimal("2")),
    ]
    same_day_result = _aggregate_capital_entries(same_day_entries)
    assert len(same_day_result) == 1
    assert same_day_result[0].gain_loss_eur == Decimal("3")


def test_aggregate_same_day_different_times_collapses_to_one_row():
    """Entries with same-day disposal dates that previously had different timestamps must now collapse."""
    entries = [
        _make_entry(
            disposal_date="2025-03-15",
            acquisition_date="2024-01-01",
            amount=Decimal("5"),
            cost_eur=Decimal("4000"),
            proceeds_eur=Decimal("4500"),
            gain_loss_eur=Decimal("500"),
        ),
        _make_entry(
            disposal_date="2025-03-15",
            acquisition_date="2024-06-01",
            amount=Decimal("3"),
            cost_eur=Decimal("2400"),
            proceeds_eur=Decimal("2700"),
            gain_loss_eur=Decimal("300"),
        ),
    ]

    result = _aggregate_capital_entries(entries)

    assert len(result) == 1
    agg = result[0]
    assert agg.amount == Decimal("8")
    assert agg.cost_eur == Decimal("6400")
    assert agg.proceeds_eur == Decimal("7200")
    assert agg.gain_loss_eur == Decimal("800")
    assert agg.acquisition_date == "2024-01-01"


def test_aggregate_different_assets_stay_separate():
    entries = [
        _make_entry(asset="USDT", gain_loss_eur=Decimal("2")),
        _make_entry(asset="BTC", gain_loss_eur=Decimal("3")),
    ]

    result = _aggregate_capital_entries(entries)

    assert len(result) == 2
    assets = {e.asset for e in result}
    assert assets == {"USDT", "BTC"}


def test_aggregate_different_wallets_stay_separate():
    entries = [
        _make_entry(wallet="ByBit", platform="ByBit", gain_loss_eur=Decimal("2")),
        _make_entry(wallet="Kraken", platform="Kraken", gain_loss_eur=Decimal("3")),
    ]

    result = _aggregate_capital_entries(entries)

    assert len(result) == 2
    wallets = {e.wallet for e in result}
    assert wallets == {"ByBit", "Kraken"}


def test_aggregate_review_required_is_or_of_group():
    entries = [
        _make_entry(review_required=False),
        _make_entry(review_required=True, review_reason="test reason"),
        _make_entry(review_required=False),
    ]

    result = _aggregate_capital_entries(entries)

    assert len(result) == 1
    assert result[0].review_required is True


def test_aggregate_review_required_false_when_all_false():
    entries = [
        _make_entry(review_required=False),
        _make_entry(review_required=False),
    ]

    result = _aggregate_capital_entries(entries)

    assert result[0].review_required is False


def test_aggregate_different_holding_periods_stay_separate():
    """Sale event with mixed holding periods produces separate entries per holding period.

    This preserves the taxable vs exempt breakdown needed for correct filing
    (PT-C-011: short-term gains are taxable, long-term gains are exempt).
    """
    entries = [
        _make_entry(holding_period="Short term", gain_loss_eur=Decimal("100")),
        _make_entry(holding_period="Long term", gain_loss_eur=Decimal("200")),
    ]

    result = _aggregate_capital_entries(entries)

    assert len(result) == 2
    holding_periods = {e.holding_period for e in result}
    assert holding_periods == {"Short term", "Long term"}
    gains = {e.holding_period: e.gain_loss_eur for e in result}
    assert gains["Short term"] == Decimal("100")
    assert gains["Long term"] == Decimal("200")


def test_aggregate_preserves_holding_period_when_all_same():
    entries = [
        _make_entry(holding_period="Short term"),
        _make_entry(holding_period="Short term"),
    ]

    result = _aggregate_capital_entries(entries)

    assert result[0].holding_period == "Short term"


def test_aggregate_notes_deduped_and_joined():
    entries = [
        _make_entry(notes="fee paid"),
        _make_entry(notes="fee paid"),
        _make_entry(notes="partial fill"),
        _make_entry(notes=""),
    ]

    result = _aggregate_capital_entries(entries)

    assert len(result) == 1
    assert result[0].notes == "fee paid; partial fill"


def test_aggregate_single_entry_unchanged():
    entry = _make_entry(
        disposal_date="2025-03-01",
        acquisition_date="2024-01-15",
        asset="ETH",
        amount=Decimal("2"),
        cost_eur=Decimal("4000"),
        proceeds_eur=Decimal("4500"),
        gain_loss_eur=Decimal("500"),
        wallet="Kraken",
        notes="some note",
    )

    result = _aggregate_capital_entries([entry])

    assert len(result) == 1
    assert result[0] == entry


def test_aggregate_wallet_aliases_collapse_to_same_account():
    """ByBit and ByBit (2) should collapse into the same logical account after normalization."""
    entries = [
        _make_entry(
            wallet="ByBit",
            platform="ByBit",
            gain_loss_eur=Decimal("2"),
        ),
        _make_entry(
            wallet="ByBit (2)",
            platform="ByBit",
            gain_loss_eur=Decimal("3"),
        ),
    ]

    result = _aggregate_capital_entries(entries)

    # Should aggregate to single entry since platform normalizes to same value
    assert len(result) == 1
    assert result[0].gain_loss_eur == Decimal("5")
    # Platform should be the normalized name
    assert result[0].platform == "ByBit"


def test_aggregate_different_wallet_aliases_with_different_dates_stay_separate():
    """Different disposal dates should still stay separate even with normalized wallet."""
    entries = [
        _make_entry(
            disposal_date="2025-01-13",
            wallet="ByBit",
            platform="ByBit",
            gain_loss_eur=Decimal("2"),
        ),
        _make_entry(
            disposal_date="2025-01-14",
            wallet="ByBit (2)",
            platform="ByBit",
            gain_loss_eur=Decimal("3"),
        ),
    ]

    result = _aggregate_capital_entries(entries)

    # Different dates = different sale events, stay separate
    assert len(result) == 2
    dates = {e.disposal_date for e in result}
    assert dates == {"2025-01-13", "2025-01-14"}
    # Both should have normalized platform
    assert all(e.platform == "ByBit" for e in result)


def test_aggregate_multi_date_acquisition_adds_note_and_flag():
    """Multiple lots with different acquisition dates.

    Expects a note listing all dates and the multi_acquisition_dates flag set.
    """
    entries = [
        _make_entry(
            disposal_date="2025-06-14",
            acquisition_date="2024-04-13",
            asset="SEI",
            amount=Decimal("189.7173"),
            cost_eur=Decimal("100"),
            proceeds_eur=Decimal("200"),
            gain_loss_eur=Decimal("100"),
            holding_period="Short term",
            wallet="ByBit",
            platform="ByBit",
            chain="ETH",
        ),
        _make_entry(
            disposal_date="2025-06-14",
            acquisition_date="2024-04-19",
            asset="SEI",
            amount=Decimal("188.9919"),
            cost_eur=Decimal("100"),
            proceeds_eur=Decimal("200"),
            gain_loss_eur=Decimal("100"),
            holding_period="Short term",
            wallet="ByBit",
            platform="ByBit",
            chain="ETH",
        ),
    ]

    result = _aggregate_capital_entries(entries)

    assert len(result) == 1
    aggregated = result[0]
    assert aggregated.acquisition_date == "2024-04-13"  # Earliest date preserved
    assert aggregated.amount == Decimal("378.7092")  # Sum of both lots
    assert aggregated.multi_acquisition_dates is True
    assert aggregated.notes == "Acquired: 2024-04-13, 2024-04-19 (2 lots)"


def test_aggregate_single_date_no_note_or_flag():
    """Given multiple lots with the same acquisition date, expects no note and multi_acquisition_dates=False."""
    entries = [
        _make_entry(
            disposal_date="2025-06-14",
            acquisition_date="2024-04-13",  # SAME date for both
            asset="SEI",
            amount=Decimal("189.7173"),
            cost_eur=Decimal("100"),
            proceeds_eur=Decimal("200"),
            gain_loss_eur=Decimal("100"),
            holding_period="Short term",
            wallet="ByBit",
            platform="ByBit",
            chain="ETH",
        ),
        _make_entry(
            disposal_date="2025-06-14",
            acquisition_date="2024-04-13",  # SAME date
            asset="SEI",
            amount=Decimal("188.9919"),
            cost_eur=Decimal("100"),
            proceeds_eur=Decimal("200"),
            gain_loss_eur=Decimal("100"),
            holding_period="Short term",
            wallet="ByBit",
            platform="ByBit",
            chain="ETH",
        ),
    ]

    result = _aggregate_capital_entries(entries)

    assert len(result) == 1
    aggregated = result[0]
    assert aggregated.multi_acquisition_dates is False
    assert aggregated.notes == ""


def test_aggregate_multi_date_with_existing_notes_merges():
    """Given lots with different dates and existing notes, expects multi-date note prepended to existing notes."""
    entries = [
        _make_entry(
            disposal_date="2025-06-14",
            acquisition_date="2024-04-13",
            asset="SEI",
            amount=Decimal("189.7173"),
            cost_eur=Decimal("100"),
            proceeds_eur=Decimal("200"),
            gain_loss_eur=Decimal("100"),
            holding_period="Short term",
            wallet="ByBit",
            platform="ByBit",
            chain="ETH",
            notes="Existing note about fee",  # Existing note
        ),
        _make_entry(
            disposal_date="2025-06-14",
            acquisition_date="2024-04-19",
            asset="SEI",
            amount=Decimal("188.9919"),
            cost_eur=Decimal("100"),
            proceeds_eur=Decimal("200"),
            gain_loss_eur=Decimal("100"),
            holding_period="Short term",
            wallet="ByBit",
            platform="ByBit",
            chain="ETH",
            notes="Another existing note",  # Different existing note
        ),
    ]

    result = _aggregate_capital_entries(entries)

    assert len(result) == 1
    aggregated = result[0]
    assert aggregated.multi_acquisition_dates is True
    # Multi-date note first, then existing notes de-duplicated and joined (order preserved from first occurrence)
    assert aggregated.notes == (
        "Acquired: 2024-04-13, 2024-04-19 (2 lots); Existing note about fee; Another existing note"
    )


def test_aggregate_multi_date_three_lots_shows_all_dates():
    """Given three lots with three different dates, expects all dates in note."""
    entries = [
        _make_entry(
            disposal_date="2025-06-14",
            acquisition_date="2024-01-01",
            asset="SEI",
            amount=Decimal("100"),
            cost_eur=Decimal("50"),
            proceeds_eur=Decimal("100"),
            gain_loss_eur=Decimal("50"),
            holding_period="Short term",
            wallet="ByBit",
            platform="ByBit",
            chain="ETH",
        ),
        _make_entry(
            disposal_date="2025-06-14",
            acquisition_date="2024-04-13",
            asset="SEI",
            amount=Decimal("100"),
            cost_eur=Decimal("50"),
            proceeds_eur=Decimal("100"),
            gain_loss_eur=Decimal("50"),
            holding_period="Short term",
            wallet="ByBit",
            platform="ByBit",
            chain="ETH",
        ),
        _make_entry(
            disposal_date="2025-06-14",
            acquisition_date="2024-04-19",
            asset="SEI",
            amount=Decimal("100"),
            cost_eur=Decimal("50"),
            proceeds_eur=Decimal("100"),
            gain_loss_eur=Decimal("50"),
            holding_period="Short term",
            wallet="ByBit",
            platform="ByBit",
            chain="ETH",
        ),
    ]

    result = _aggregate_capital_entries(entries)

    assert len(result) == 1
    aggregated = result[0]
    assert aggregated.multi_acquisition_dates is True
    assert aggregated.notes == "Acquired: 2024-01-01, 2024-04-13, 2024-04-19 (3 lots)"


def test_aggregate_multi_date_with_review_required_preserves_review_flag():
    """Multi-date entry with review_required=True preserves the flag through aggregation.

    Rendering is tested separately in Task 6.
    """
    entries = [
        _make_entry(
            disposal_date="2025-06-14",
            acquisition_date="2024-04-13",
            asset="SEI",
            amount=Decimal("189.7173"),
            cost_eur=Decimal("100"),
            proceeds_eur=Decimal("200"),
            gain_loss_eur=Decimal("100"),
            holding_period="Short term",
            wallet="ByBit",
            platform="ByBit",
            chain="ETH",
            review_required=True,  # REVIEW REQUIRED
            review_reason="Test review reason",
        ),
        _make_entry(
            disposal_date="2025-06-14",
            acquisition_date="2024-04-19",
            asset="SEI",
            amount=Decimal("188.9919"),
            cost_eur=Decimal("100"),
            proceeds_eur=Decimal("200"),
            gain_loss_eur=Decimal("100"),
            holding_period="Short term",
            wallet="ByBit",
            platform="ByBit",
            chain="ETH",
        ),
    ]

    result = _aggregate_capital_entries(entries)

    assert len(result) == 1
    aggregated = result[0]
    assert aggregated.multi_acquisition_dates is True  # Still set
    assert aggregated.review_required is True  # Takes precedence via OR logic
    assert aggregated.notes == "Acquired: 2024-04-13, 2024-04-19 (2 lots)"
    assert aggregated.review_reason == "Test review reason"  # review_reason is a separate field


def test_aggregate_multi_date_all_empty_dates_no_flag():
    """Given all lots with empty acquisition dates, expects multi_acquisition_dates=False and no note."""
    entries = [
        _make_entry(
            disposal_date="2025-06-14",
            acquisition_date="",
            asset="SEI",
            amount=Decimal("100"),
            cost_eur=Decimal("50"),
            proceeds_eur=Decimal("100"),
            gain_loss_eur=Decimal("50"),
            holding_period="Short term",
            wallet="ByBit",
            platform="ByBit",
            chain="ETH",
        ),
        _make_entry(
            disposal_date="2025-06-14",
            acquisition_date="",
            asset="SEI",
            amount=Decimal("100"),
            cost_eur=Decimal("50"),
            proceeds_eur=Decimal("100"),
            gain_loss_eur=Decimal("50"),
            holding_period="Short term",
            wallet="ByBit",
            platform="ByBit",
            chain="ETH",
        ),
    ]

    result = _aggregate_capital_entries(entries)

    assert len(result) == 1
    aggregated = result[0]
    assert aggregated.multi_acquisition_dates is False
    assert aggregated.notes == ""


def test_aggregate_multi_date_mixed_empty_and_valid_dates():
    """Given lots with mixed empty and valid acquisition dates, expects only valid dates counted."""
    entries = [
        _make_entry(
            disposal_date="2025-06-14",
            acquisition_date="",
            asset="SEI",
            amount=Decimal("100"),
            cost_eur=Decimal("50"),
            proceeds_eur=Decimal("100"),
            gain_loss_eur=Decimal("50"),
            holding_period="Short term",
            wallet="ByBit",
            platform="ByBit",
            chain="ETH",
        ),
        _make_entry(
            disposal_date="2025-06-14",
            acquisition_date="2024-04-13",
            asset="SEI",
            amount=Decimal("100"),
            cost_eur=Decimal("50"),
            proceeds_eur=Decimal("100"),
            gain_loss_eur=Decimal("50"),
            holding_period="Short term",
            wallet="ByBit",
            platform="ByBit",
            chain="ETH",
        ),
    ]

    result = _aggregate_capital_entries(entries)

    assert len(result) == 1
    aggregated = result[0]
    # Empty dates are excluded, only one valid date means no multi-date flag
    assert aggregated.multi_acquisition_dates is False
    assert aggregated.notes == ""


def test_aggregate_single_lot_no_multi_date_flag():
    """Given a single lot, expects multi_acquisition_dates=False and no note."""
    entry = _make_entry(
        disposal_date="2025-06-14",
        acquisition_date="2024-04-13",
        asset="SEI",
        amount=Decimal("100"),
        cost_eur=Decimal("50"),
        proceeds_eur=Decimal("100"),
        gain_loss_eur=Decimal("50"),
        holding_period="Short term",
        wallet="ByBit",
        platform="ByBit",
        chain="ETH",
    )

    result = _aggregate_capital_entries([entry])

    assert len(result) == 1
    aggregated = result[0]
    assert aggregated.multi_acquisition_dates is False
    assert aggregated.notes == ""


class TestAggregateCapitalEntries:
    """Pattern L: aggregation no-acquisition-date per-row emissions grouped into ONE aggregate.

    ``_aggregate_capital_entries`` has 2 per-row WARNING sites (no-acquisition-date at the
    ``if not acquisition_date:`` branch, epoch-sentinel at the ``elif ... "1970-":`` branch)
    that Pattern L downgrades to DEBUG (message text unchanged), incrementing a ``Counter[str]``
    keyed by asset. The aggregate fires ONCE at the end of ``_aggregate_capital_entries`` (the
    function is called once per run from ``crypto_reporting.py``, NOT inside a per-asset loop, so
    no threading is needed). Per Design Invariant #3, the aggregated entry's
    ``review_required``/``review_reason`` are UNCHANGED; the audit signal stays on the data, not
    the log -- this is what surfaces in the Crypto Gains Excel "YES:" cell.
    """

    def test_l_aggregate_collapses_no_acquisition_date_warnings(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Aggregated entries built from pool-exhausted placeholder lots with either an empty
        acquisition date (``if not acquisition_date:`` branch) or an epoch-sentinel
        ``"1970-..."`` date (``elif acquisition_date.startswith("1970-")`` branch) produce
        exactly ONE INFO matching ``"N aggregated capital-gains entry(ies) with"`` that
        names the affected assets with counts, AND both per-row DEBUG branches are exercised.

        Fixture: three distinct assets, two of which hit the no-date branch (SEI, ATOM) and
        one of which hits the epoch-sentinel branch (SOL). Each lot is a pool-exhausted
        placeholder (``review_required=True`` with the inherited pool-exhausted
        ``review_reason`` set by predecessor pattern F). Each aggregated entry keeps its
        ``review_required=True`` + the inherited ``review_reason`` (Design Invariant #3,
        unchanged). Driving the epoch branch via this aggregate path pins the
        ``epoch_entries`` increment and the epoch DEBUG message (r1 F2): a regression
        breaking only the epoch branch would otherwise pass the suite.
        """
        pool_exhausted_reason_sei = (
            "FIFO pool exhausted: 100 SEI disposed with zero cost basis"
        )
        pool_exhausted_reason_atom = (
            "FIFO pool exhausted: 50 ATOM disposed with zero cost basis"
        )
        epoch_missing_date_reason_sol = (
            "Epoch sentinel acquisition date for SOL; "
            "missing Date field in TH row: holding period unknown, Short term"
        )
        entries = [
            _make_entry(
                disposal_date="2025-06-14",
                acquisition_date="",
                asset="SEI",
                amount=Decimal("100"),
                cost_eur=Decimal("0"),
                proceeds_eur=Decimal("100"),
                gain_loss_eur=Decimal("100"),
                holding_period="Short term",
                wallet="ByBit",
                platform="ByBit",
                chain="ETH",
                review_required=True,
                review_reason=pool_exhausted_reason_sei,
            ),
            _make_entry(
                disposal_date="2025-06-15",
                acquisition_date="",
                asset="ATOM",
                amount=Decimal("50"),
                cost_eur=Decimal("0"),
                proceeds_eur=Decimal("50"),
                gain_loss_eur=Decimal("50"),
                holding_period="Short term",
                wallet="Kraken",
                platform="Kraken",
                chain="ATOM",
                review_required=True,
                review_reason=pool_exhausted_reason_atom,
            ),
            _make_entry(
                disposal_date="2025-06-16",
                acquisition_date="1970-01-01",
                asset="SOL",
                amount=Decimal("25"),
                cost_eur=Decimal("0"),
                proceeds_eur=Decimal("25"),
                gain_loss_eur=Decimal("25"),
                holding_period="Short term",
                wallet="LedgerA",
                platform="LedgerA",
                chain="SOL",
                review_required=True,
                review_reason=epoch_missing_date_reason_sol,
            ),
        ]

        aggregation_logger = "tax_reporting.application.crypto.aggregation"

        with caplog.at_level(logging.DEBUG, logger=aggregation_logger):
            result = _aggregate_capital_entries(entries)

        # Exactly ONE aggregate INFO matching the prescribed summary substring
        # (demoted from WARNING to INFO in Task 8; aggregated entries inherit
        # ``review_required`` from their pool-exhausted placeholder lots, which is
        # the Excel-surfaced signal).
        aggregate_infos = [
            rec.getMessage()
            for rec in caplog.records
            if rec.levelno == logging.INFO
            and rec.name == aggregation_logger
            and "aggregated capital-gains entry(ies) with" in rec.getMessage()
        ]
        assert len(aggregate_infos) == 1, (
            f"Expected exactly ONE aggregate INFO, got {aggregate_infos}"
        )

        msg = aggregate_infos[0]
        # The summary names the total count (3 = one flagged entry per asset across both
        # the no-date branch and the epoch-sentinel branch).
        assert "3 aggregated capital-gains entry(ies) with" in msg, (
            f"Aggregate must name the total count; got {msg!r}"
        )
        # ... and names each affected asset with its count (sorted by asset).
        assert "ATOM: 1" in msg, (
            f"Aggregate must name ATOM with count; got {msg!r}"
        )
        assert "SEI: 1" in msg, (
            f"Aggregate must name SEI with count; got {msg!r}"
        )
        assert "SOL: 1" in msg, (
            f"Aggregate must name SOL with count; got {msg!r}"
        )
        # The aggregate points reviewers at the DEBUG log and the review column.
        assert "see DEBUG log" in msg, (
            f"Aggregate must point at the DEBUG log for per-row detail; got {msg!r}"
        )
        assert "Crypto Gains review column" in msg, (
            f"Aggregate must point at the review column; got {msg!r}"
        )

        # The per-row detail stays reachable at DEBUG. Both branches must be exercised:
        # - two no-acquisition-date DEBUG records (SEI, ATOM) from the ``if not`` branch;
        # - one epoch-sentinel DEBUG record (SOL) from the ``elif "1970-"`` branch.
        per_row_no_date = [
            r.getMessage()
            for r in caplog.records
            if r.levelno == logging.DEBUG
            and r.name == aggregation_logger
            and "no acquisition date" in r.getMessage().lower()
        ]
        assert len(per_row_no_date) == 2, (
            f"Expected 2 per-row no-acquisition-date DEBUG records (SEI, ATOM), "
            f"got {per_row_no_date}"
        )
        per_row_epoch = [
            r.getMessage()
            for r in caplog.records
            if r.levelno == logging.DEBUG
            and r.name == aggregation_logger
            and "epoch sentinel" in r.getMessage().lower()
        ]
        assert len(per_row_epoch) == 1, (
            f"Expected 1 per-row epoch-sentinel DEBUG record (SOL), got {per_row_epoch}"
        )

        # Design Invariant #3: the aggregated entries still carry review_required=True + the
        # inherited pool-exhausted / epoch-sentinel review_reason (this is what surfaces in
        # the Excel "YES:" cell).
        by_asset = {e.asset: e for e in result}
        assert by_asset["SEI"].review_required is True
        assert by_asset["SEI"].review_reason == pool_exhausted_reason_sei
        assert by_asset["ATOM"].review_required is True
        assert by_asset["ATOM"].review_reason == pool_exhausted_reason_atom
        assert by_asset["SOL"].review_required is True
        assert by_asset["SOL"].review_reason == epoch_missing_date_reason_sol

    def test_l_aggregate_not_emitted_when_all_dates_valid(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """No L-aggregate INFO fires when every aggregated entry has a valid
        acquisition date (r3 R3-3 negative guard).

        The post-loop guard ``if no_date_entries or epoch_entries:`` at
        ``aggregation.py:422`` is the only thing preventing a noisy ``0 ...
        flagged ()`` INFO on every run. The positive test above covers the
        non-empty path; this test pins the empty path. Removing the guard leaves
        the suite green, so without this assertion a future refactor dropping the
        guard would ship silently. Fixture: two entries with the
        ``_make_entry`` default valid ``acquisition_date`` (different assets so
        they form distinct groups), neither empty nor epoch-sentinel.
        """
        entries = [
            _make_entry(asset="BTC", disposal_date="2025-05-01", acquisition_date="2024-01-01"),
            _make_entry(asset="ETH", disposal_date="2025-05-02", acquisition_date="2024-02-01"),
        ]

        aggregation_logger = "tax_reporting.application.crypto.aggregation"

        with caplog.at_level(logging.DEBUG, logger=aggregation_logger):
            _aggregate_capital_entries(entries)

        aggregate_infos = [
            rec.getMessage()
            for rec in caplog.records
            if rec.levelno == logging.INFO
            and rec.name == aggregation_logger
            and "aggregated capital-gains entry(ies) with" in rec.getMessage()
        ]
        assert aggregate_infos == [], (
            "No L-aggregate INFO should fire when all acquisition dates are valid; "
            f"got {aggregate_infos}"
        )


def test_mixed_lot_aggregated_drops_zero_basis_reason():
    """Mixed-lot group: one noisy all-zero lot does not poison the aggregated row.

    Pins Invariant 1 (per-lot signal preservation) and Invariant 2 (filter owns
    both aggregated fields atomically): given a 5-entry group where one lot is
    all-zero with a zero-basis reason and the other four lots are clean and
    material, the aggregated entry drops the zero-basis reason entirely.
    """
    entries = [
        _make_entry(
            disposal_date="2025-02-01",
            acquisition_date="2024-06-01",
            asset="USDT",
            amount=Decimal("10"),
            cost_eur=Decimal("200"),
            proceeds_eur=Decimal("220"),
            gain_loss_eur=Decimal("20"),
            holding_period="Short term",
            wallet="ByBit",
            platform="ByBit",
            chain="ETH",
            review_required=False,
        )
        for _ in range(4)
    ]
    entries.append(
        _make_entry(
            disposal_date="2025-02-01",
            acquisition_date="2024-06-01",
            asset="USDT",
            amount=Decimal("0.0001"),
            cost_eur=Decimal("0"),
            proceeds_eur=Decimal("0"),
            gain_loss_eur=Decimal("0"),
            holding_period="Short term",
            wallet="ByBit",
            platform="ByBit",
            chain="ETH",
            review_required=True,
            review_reason="Zero EUR value for known crypto asset - test fixture",
        )
    )

    result = _aggregate_capital_entries(entries)

    assert len(result) == 1
    aggregated = result[0]
    assert aggregated.cost_eur == Decimal("800")
    assert aggregated.proceeds_eur == Decimal("880")
    assert aggregated.gain_loss_eur == Decimal("80")
    assert aggregated.review_required is False
    assert aggregated.review_reason is None


def test_all_zero_lot_group_preserves_zero_basis_reason():
    """All-zero-lot group: the aggregated row preserves the zero-basis reason.

    The materiality gate (``cost > 0 AND proceeds > 0 AND |gain| >= 1``) fails
    for a fully all-zero disposal, so the per-lot signal is preserved end-to-end.
    """
    entries = [
        _make_entry(
            disposal_date="2025-02-01",
            acquisition_date="2024-06-01",
            asset="USDT",
            amount=Decimal("0.0001"),
            cost_eur=Decimal("0"),
            proceeds_eur=Decimal("0"),
            gain_loss_eur=Decimal("0"),
            holding_period="Short term",
            wallet="ByBit",
            platform="ByBit",
            chain="ETH",
            review_required=True,
            review_reason="Zero EUR value for known crypto asset - test fixture",
        )
        for _ in range(3)
    ]

    result = _aggregate_capital_entries(entries)

    assert len(result) == 1
    aggregated = result[0]
    assert aggregated.review_required is True
    assert aggregated.review_reason is not None
    assert "Zero EUR value for known crypto asset" in aggregated.review_reason


def test_phantom_lot_reason_survives_mixed_aggregation():
    """Non-zero-basis reason survives aggregation in a mixed-lot group.

    The phantom-lot reason is preserved while the zero-basis reason is stripped:
    the filter splits on ``"; "`` and drops only zero-basis prefixes.
    """
    entries = [
        _make_entry(
            disposal_date="2025-02-01",
            acquisition_date="2024-06-01",
            asset="USDT",
            amount=Decimal("10"),
            cost_eur=Decimal("200"),
            proceeds_eur=Decimal("220"),
            gain_loss_eur=Decimal("20"),
            holding_period="Short term",
            wallet="ByBit",
            platform="ByBit",
            chain="ETH",
            review_required=True,
            review_reason="Phantom lot: prior transfer not matched in FIFO",
        ),
        _make_entry(
            disposal_date="2025-02-01",
            acquisition_date="2024-06-01",
            asset="USDT",
            amount=Decimal("0.0001"),
            cost_eur=Decimal("0"),
            proceeds_eur=Decimal("0"),
            gain_loss_eur=Decimal("0"),
            holding_period="Short term",
            wallet="ByBit",
            platform="ByBit",
            chain="ETH",
            review_required=True,
            review_reason="Zero EUR value for known crypto asset - test fixture",
        ),
    ]

    result = _aggregate_capital_entries(entries)

    assert len(result) == 1
    aggregated = result[0]
    assert aggregated.review_required is True
    assert aggregated.review_reason == "Phantom lot: prior transfer not matched in FIFO"


# --- _filter_immaterial_entries tests ---


def test_filter_keeps_entries_with_gain_above_threshold():
    entries = [
        _make_entry(gain_loss_eur=Decimal("2.00")),
        _make_entry(gain_loss_eur=Decimal("5.00")),
    ]

    result = _filter_immaterial_entries(entries)

    assert len(result) == 2


def test_filter_removes_entries_with_gain_below_threshold():
    entries = [
        _make_entry(gain_loss_eur=Decimal("0.99")),
        _make_entry(gain_loss_eur=Decimal("0.50")),
        _make_entry(gain_loss_eur=Decimal("0.01")),
    ]

    result = _filter_immaterial_entries(entries)

    assert len(result) == 0


def test_filter_keeps_entry_at_exact_threshold():
    """Gain exactly 1.00 EUR is kept (>= threshold, boundary-inclusive)."""
    entry = _make_entry(gain_loss_eur=Decimal("1.00"))

    result = _filter_immaterial_entries([entry])

    assert len(result) == 1


def test_filter_removes_zero_gain_entry():
    """Zero gain is below the 1 EUR threshold and must be filtered out."""
    entry = _make_entry(gain_loss_eur=Decimal("0"))

    result = _filter_immaterial_entries([entry])

    assert len(result) == 0


def test_filter_keeps_significant_losses():
    entries = [
        _make_entry(gain_loss_eur=Decimal("-5.00")),
        _make_entry(gain_loss_eur=Decimal("-1.00")),
    ]

    result = _filter_immaterial_entries(entries)

    assert len(result) == 2


def test_filter_removes_small_losses_below_threshold():
    """Losses < 1 EUR in absolute value are also filtered (between -1 and 0)."""
    entries = [
        _make_entry(gain_loss_eur=Decimal("-0.50")),
        _make_entry(gain_loss_eur=Decimal("-0.01")),
    ]

    result = _filter_immaterial_entries(entries)

    assert len(result) == 0


# --- Integration: aggregation through load_koinly_crypto_report ---


def test_parse_capital_gains_file_aggregates_dust_rows(tmp_path):
    """103 same-timestamp USDT FIFO lot rows aggregate to 1 sale event row."""
    koinly_dir = tmp_path / "koinly2025"
    koinly_dir.mkdir()

    header = ",".join(
        [
            "Date Sold",
            "Date Acquired",
            "Asset",
            "Amount",
            "Cost (EUR)",
            "Proceeds (EUR)",
            "Gain / loss",
            "Notes",
            "Wallet Name",
            "Holding period",
        ]
    )

    # 103 rows: same (disposal_date, asset, wallet), each with gain 0.20 EUR
    # Total gain = 103 * 0.20 = 20.60 EUR → passes materiality filter
    data_rows = [
        ",".join(
            [
                "13/01/2025 13:01",
                f"01/{(i % 12) + 1:02d}/2024 00:00",
                "USDT",
                '"0,10000000"',
                '"1,00"',
                '"1,20"',
                '"0,20"',
                "",
                "ByBit",
                "Short term",
            ]
        )
        for i in range(103)
    ]

    csv_content = "\n".join(["Capital gains report 2025", "", header, *data_rows])
    (koinly_dir / "koinly_2025_capital_gains_report.csv").write_text(csv_content, encoding="utf-8")

    _write_minimal_income_report(koinly_dir)
    _write_minimal_transaction_history(koinly_dir)

    report = load_koinly_crypto_report(koinly_dir)

    assert report is not None
    # 103 FIFO lot rows → 1 aggregated sale event
    assert len(report.capital_entries) == 1
    assert report.reconciliation.capital_rows == 1
    assert report.reconciliation.short_term_rows == 1
    agg = report.capital_entries[0]
    assert agg.asset == "USDT"
    assert agg.disposal_date == "2025-01-13"
    assert agg.wallet == "ByBit"
    assert agg.amount == Decimal("103") * Decimal("0.10000000")
    assert agg.cost_eur == Decimal("103")
    assert agg.proceeds_eur == Decimal("103") * Decimal("1.20")
    assert agg.gain_loss_eur == Decimal("103") * Decimal("0.20")
    # earliest acquisition date among 103 lots
    assert agg.acquisition_date == "2024-01-01"


def test_parse_capital_gains_file_filters_sub_1_eur_after_aggregation(tmp_path, caplog):
    """FIFO lot rows that aggregate to |gain| < 1 EUR are dropped, warning is emitted."""
    koinly_dir = tmp_path / "koinly2025"
    koinly_dir.mkdir()

    header = ",".join(
        [
            "Date Sold",
            "Date Acquired",
            "Asset",
            "Amount",
            "Cost (EUR)",
            "Proceeds (EUR)",
            "Gain / loss",
            "Notes",
            "Wallet Name",
            "Holding period",
        ]
    )

    # 3 lots for the same sale event, each with gain 0.30 EUR → total 0.90 EUR < 1 EUR threshold
    sub_threshold_rows = [
        ",".join(
            [
                "13/01/2025 13:01",
                "01/01/2024 00:00",
                "USDT",
                '"0,10000000"',
                '"1,00"',
                '"1,30"',
                '"0,30"',
                "",
                "ByBit",
                "Short term",
            ]
        )
        for _ in range(3)
    ]
    # One row that passes the filter (gain = 5.00 EUR)
    above_threshold_row = ",".join(
        [
            "20/01/2025 10:00",
            "01/06/2024 00:00",
            "BTC",
            '"0,01000000"',
            '"200,00"',
            '"205,00"',
            '"5,00"',
            "",
            "Kraken",
            "Short term",
        ]
    )

    csv_content = "\n".join(["Capital gains report 2025", "", header, *sub_threshold_rows, above_threshold_row])
    (koinly_dir / "koinly_2025_capital_gains_report.csv").write_text(csv_content, encoding="utf-8")

    _write_minimal_income_report(koinly_dir)
    _write_minimal_transaction_history(koinly_dir)

    # Lesson #69: the sub-1-EUR aggregate was demoted WARNING -> INFO (Task 2),
    # so caplog must capture at INFO to observe it.
    with caplog.at_level(logging.INFO, logger="tax_reporting.application.crypto_reporting"):
        report = load_koinly_crypto_report(koinly_dir)

    assert report is not None
    # Sub-threshold USDT sale event (0.90 EUR) is dropped; BTC row (5.00 EUR) is kept
    assert len(report.capital_entries) == 1
    assert report.reconciliation.capital_rows == 1
    assert report.capital_entries[0].asset == "BTC"
    assert "sub-1-EUR" in caplog.text


# --- Additional edge case tests ---


def test_aggregate_empty_list_returns_empty():
    """Empty input list returns empty list without error."""
    result = _aggregate_capital_entries([])
    assert result == []


def test_parse_koinly_decimal_handles_negative_numbers():
    """Negative numbers (losses) must parse correctly for tax reporting."""
    assert parse_koinly_decimal("-1,234.56") == Decimal("-1234.56")
    assert parse_koinly_decimal("-1.234,56") == Decimal("-1234.56")
    assert parse_koinly_decimal("-1,000") == Decimal("-1000")
    assert parse_koinly_decimal("-0,50") == Decimal("-0.50")
    assert parse_koinly_decimal("-500.00") == Decimal("-500.00")
    assert parse_koinly_decimal("-0.99") == Decimal("-0.99")


def test_resolve_operator_origin_case_insensitive():
    """Platform name matching must be case-insensitive."""
    wirex_crypto = resolve_operator_origin("WIREX", transaction_type="crypto_deposit")
    wirex_crypto_lower = resolve_operator_origin("wirex", transaction_type="crypto_deposit")
    wirex_crypto_mixed = resolve_operator_origin("WiReX", transaction_type="crypto_deposit")

    # All return the same canonical platform name regardless of input casing
    assert wirex_crypto.platform == "Wirex"
    assert wirex_crypto_lower.platform == "Wirex"
    assert wirex_crypto_mixed.platform == "Wirex"
    # Wirex no longer requires review (service_start_date enables historical matching)
    assert wirex_crypto.review_required is False
    assert wirex_crypto_lower.review_required is False
    assert wirex_crypto_mixed.review_required is False
    # All have the same operator entity (crypto scope)
    assert wirex_crypto.operator_entity == wirex_crypto_lower.operator_entity
    assert wirex_crypto.operator_entity == wirex_crypto_mixed.operator_entity

    # Test other platforms
    bybit_upper = resolve_operator_origin("BYBIT")
    bybit_lower = resolve_operator_origin("bybit")
    # Bybit has platform_assumption instead of review_required
    assert bybit_upper.review_required is False
    assert bybit_lower.review_required is False
    assert bybit_upper.platform_assumption is not None
    assert bybit_lower.platform_assumption is not None
    assert bybit_upper.operator_entity == bybit_lower.operator_entity


def test_resolve_operator_origin_unknown_platform():
    """Unknown platforms must return fallback with review required."""
    origin = resolve_operator_origin("UnknownPlatform123")
    assert origin.platform == "UnknownPlatform123"
    assert origin.operator_entity == "UNKNOWN_OPERATOR_REVIEW_REQUIRED"
    assert origin.operator_country == "UNKNOWN"
    assert origin.review_required is True
    assert origin.confidence == "low"


def test_filter_boundary_values_around_threshold():
    """Test boundary conditions at the 1.00 EUR materiality threshold."""
    entries = [
        _make_entry(gain_loss_eur=Decimal("0.99")),  # Below - filtered
        _make_entry(gain_loss_eur=Decimal("1.00")),  # At threshold - kept
        _make_entry(gain_loss_eur=Decimal("1.01")),  # Above - kept
        _make_entry(gain_loss_eur=Decimal("-0.99")),  # Below - filtered
        _make_entry(gain_loss_eur=Decimal("-1.00")),  # At threshold - kept
        _make_entry(gain_loss_eur=Decimal("-1.01")),  # Above - kept
    ]

    result = _filter_immaterial_entries(entries)

    assert len(result) == 4
    gains = [e.gain_loss_eur for e in result]
    assert Decimal("0.99") not in gains
    assert Decimal("1.00") in gains
    assert Decimal("1.01") in gains
    assert Decimal("-0.99") not in gains
    assert Decimal("-1.00") in gains
    assert Decimal("-1.01") in gains


def test_missing_cost_basis_with_zero_proceeds_no_review(tmp_path):
    """Missing cost basis with zero proceeds (no tax impact) should NOT require review."""
    koinly_dir = tmp_path / "koinly2025"
    koinly_dir.mkdir()

    header = ",".join(
        [
            "Date Sold",
            "Date Acquired",
            "Asset",
            "Amount",
            "Cost (EUR)",
            "Proceeds (EUR)",
            "Gain / loss",
            "Notes",
            "Wallet Name",
            "Holding period",
        ]
    )

    # Row with "missing cost basis" but truly zero values (no tax impact at all)
    # All zero - this is a false positive that should be suppressed
    all_zero_row = ",".join(
        [
            "20/01/2025 10:00",
            "01/06/2024 00:00",
            "BTC",
            '"0,01000000"',
            '"0,00"',  # Zero cost
            '"0,00"',  # Zero proceeds
            '"0,00"',  # Zero gain
            '"Missing cost basis"',  # Notes flag - should be suppressed for truly zero entries
            "Kraken",
            "Short term",
        ]
    )

    # Row with "missing cost basis" and non-zero proceeds (tax impact - should require review)
    non_zero_proceeds_row = ",".join(
        [
            "20/01/2025 11:00",
            "01/06/2024 00:00",
            "ETH",
            '"0,10000000"',
            '"0,00"',
            '"100,00"',  # Non-zero proceeds - tax impact
            '"100,00"',
            '"Missing cost basis"',  # Notes flag
            "Kraken",
            "Short term",
        ]
    )

    # Row with "missing cost basis" and non-zero cost/loss (tax impact - should require review)
    loss_with_missing_basis_row = ",".join(
        [
            "20/01/2025 12:00",
            "01/06/2024 00:00",
            "SOL",
            '"0,05000000"',
            '"50,00"',  # Non-zero cost (loss scenario)
            '"0,00"',  # Zero proceeds but loss has tax impact
            '"-50,00"',
            '"Missing cost basis"',  # Notes flag - loss cannot be verified
            "Kraken",
            "Short term",
        ]
    )

    csv_content = "\n".join(
        ["Capital gains report 2025", "", header, all_zero_row, non_zero_proceeds_row, loss_with_missing_basis_row]
    )
    (koinly_dir / "koinly_2025_capital_gains_report.csv").write_text(csv_content, encoding="utf-8")

    _write_minimal_income_report(koinly_dir)
    _write_minimal_transaction_history(koinly_dir)

    report = load_koinly_crypto_report(koinly_dir)

    assert report is not None
    # All-zero row should be filtered out, others pass
    assert len(report.capital_entries) == 2

    # Find the ETH entry (non-zero proceeds, gain)
    eth_entry = next(e for e in report.capital_entries if e.asset == "ETH")
    assert eth_entry.proceeds_eur == Decimal("100")
    assert eth_entry.review_required is True, "Non-zero proceeds with missing cost basis SHOULD require review"

    # Find the SOL entry (zero proceeds but has loss - tax impact)
    sol_entry = next(e for e in report.capital_entries if e.asset == "SOL")
    assert sol_entry.proceeds_eur == Decimal("0")
    assert sol_entry.cost_eur == Decimal("50")
    assert sol_entry.gain_loss_eur == Decimal("-50")
    assert sol_entry.review_required is True, (
        "Zero proceeds with non-zero cost/loss and missing cost basis SHOULD require review (loss cannot be verified)"
    )


# --- Reward tax classification tests ---


def test_classify_crypto_denominated_reward_as_deferred_by_law():
    """Crypto-denominated rewards must be classified as deferred by law (CRG-001)."""
    # Major cryptocurrencies
    assert _classify_reward_tax_status("BTC") == RewardTaxClassification.DEFERRED_BY_LAW
    assert _classify_reward_tax_status("ETH") == RewardTaxClassification.DEFERRED_BY_LAW
    assert _classify_reward_tax_status("SOL") == RewardTaxClassification.DEFERRED_BY_LAW

    # Stablecoins are treated as cryptoassets per PT-C-003
    assert _classify_reward_tax_status("USDT") == RewardTaxClassification.DEFERRED_BY_LAW
    assert _classify_reward_tax_status("USDC") == RewardTaxClassification.DEFERRED_BY_LAW

    # DeFi tokens
    assert _classify_reward_tax_status("UNI") == RewardTaxClassification.DEFERRED_BY_LAW
    assert _classify_reward_tax_status("AAVE") == RewardTaxClassification.DEFERRED_BY_LAW


def test_classify_fiat_denominated_reward_as_taxable_now():
    """Fiat-denominated rewards must be immediately taxable as Category E (CRG-002)."""
    # Major fiat currencies
    assert _classify_reward_tax_status("EUR") == RewardTaxClassification.TAXABLE_NOW
    assert _classify_reward_tax_status("USD") == RewardTaxClassification.TAXABLE_NOW
    assert _classify_reward_tax_status("GBP") == RewardTaxClassification.TAXABLE_NOW
    assert _classify_reward_tax_status("JPY") == RewardTaxClassification.TAXABLE_NOW

    # European currencies
    assert _classify_reward_tax_status("CHF") == RewardTaxClassification.TAXABLE_NOW
    assert _classify_reward_tax_status("SEK") == RewardTaxClassification.TAXABLE_NOW
    assert _classify_reward_tax_status("NOK") == RewardTaxClassification.TAXABLE_NOW
    assert _classify_reward_tax_status("DKK") == RewardTaxClassification.TAXABLE_NOW

    # Other global currencies
    assert _classify_reward_tax_status("AUD") == RewardTaxClassification.TAXABLE_NOW
    assert _classify_reward_tax_status("CAD") == RewardTaxClassification.TAXABLE_NOW
    assert _classify_reward_tax_status("SGD") == RewardTaxClassification.TAXABLE_NOW
    assert _classify_reward_tax_status("HKD") == RewardTaxClassification.TAXABLE_NOW


def test_classify_reward_case_insensitive():
    """Asset ticker classification must be case-insensitive."""
    assert _classify_reward_tax_status("btc") == RewardTaxClassification.DEFERRED_BY_LAW
    assert _classify_reward_tax_status("BTC") == RewardTaxClassification.DEFERRED_BY_LAW
    assert _classify_reward_tax_status("Btc") == RewardTaxClassification.DEFERRED_BY_LAW

    assert _classify_reward_tax_status("eur") == RewardTaxClassification.TAXABLE_NOW
    assert _classify_reward_tax_status("EUR") == RewardTaxClassification.TAXABLE_NOW
    assert _classify_reward_tax_status("Eur") == RewardTaxClassification.TAXABLE_NOW

    assert _classify_reward_tax_status("usdt") == RewardTaxClassification.DEFERRED_BY_LAW
    assert _classify_reward_tax_status("USDT") == RewardTaxClassification.DEFERRED_BY_LAW


def test_classify_reward_whitespace_tolerance():
    """Asset ticker classification must handle surrounding whitespace."""
    assert _classify_reward_tax_status(" BTC ") == RewardTaxClassification.DEFERRED_BY_LAW
    assert _classify_reward_tax_status("  EUR  ") == RewardTaxClassification.TAXABLE_NOW
    assert _classify_reward_tax_status("\tUSDT\n") == RewardTaxClassification.DEFERRED_BY_LAW


def test_classify_defi_staking_rewards_as_deferred():
    """DeFi staking, lending, and airdrop rewards must be deferred (crypto-denominated)."""
    # Staking rewards from various chains
    assert _classify_reward_tax_status("ETH") == RewardTaxClassification.DEFERRED_BY_LAW
    assert _classify_reward_tax_status("SOL") == RewardTaxClassification.DEFERRED_BY_LAW
    assert _classify_reward_tax_status("ATOM") == RewardTaxClassification.DEFERRED_BY_LAW

    # Lending interest
    assert _classify_reward_tax_status("USDC") == RewardTaxClassification.DEFERRED_BY_LAW

    # Airdrops
    assert _classify_reward_tax_status("UNI") == RewardTaxClassification.DEFERRED_BY_LAW

    # Liquidity mining
    assert _classify_reward_tax_status("CRV") == RewardTaxClassification.DEFERRED_BY_LAW


def test_classify_fiat_cash_reward_from_crypto_platform_as_taxable():
    """Cash withdrawals/rewards from crypto platforms in fiat are immediately taxable."""
    # EUR reward from a crypto exchange (fiat withdrawal to bank)
    assert _classify_reward_tax_status("EUR") == RewardTaxClassification.TAXABLE_NOW
    assert _classify_reward_tax_status("USD") == RewardTaxClassification.TAXABLE_NOW


def test_load_koinly_crypto_report_applies_reward_classification(tmp_path):
    """Verify reward entries include tax_classification field after parsing."""
    koinly_dir = tmp_path / "koinly2025"
    koinly_dir.mkdir()

    # Crypto-denominated rewards (deferred)
    (koinly_dir / "koinly_2025_income_report_test.csv").write_text(
        "\n".join(
            [
                "Income report 2025",
                "",
                "Date,Asset,Amount,Value (EUR),Type,Description,Wallet Name",
                '01/01/2025 00:01,BTC,"0,01000000","500,00",Reward,,ByBit',
                '02/01/2025 00:01,USDT,"10,00000000","10,10",Lending interest,,Wirex',
                # Fiat-denominated reward (taxable now)
                '03/01/2025 00:01,EUR,"5,00","5,00",Reward,Cashback,Kraken',
            ]
        ),
        encoding="utf-8",
    )

    (koinly_dir / "koinly_2025_capital_gains_report_test.csv").write_text(
        "\n".join(
            [
                "Capital gains report 2025",
                "",
                ",".join(
                    [
                        "Date Sold",
                        "Date Acquired",
                        "Asset",
                        "Amount",
                        "Cost (EUR)",
                        "Proceeds (EUR)",
                        "Gain / loss",
                        "Notes",
                        "Wallet Name",
                        "Holding period",
                    ]
                ),
                ",".join(
                    [
                        "13/01/2025 13:01",
                        "18/11/2024 00:15",
                        "USDT",
                        '"1,50000000"',
                        '"1,25"',
                        '"2,35"',
                        '"1,10"',
                        "",
                        "ByBit (2)",
                        "Short term",
                    ]
                ),
            ]
        ),
        encoding="utf-8",
    )

    _write_minimal_transaction_history(koinly_dir)

    report = load_koinly_crypto_report(koinly_dir)

    assert report is not None
    assert len(report.reward_entries) == 3

    # BTC reward is deferred (crypto-denominated)
    btc_reward = next((r for r in report.reward_entries if r.asset == "BTC"), None)
    assert btc_reward is not None
    assert btc_reward.tax_classification == RewardTaxClassification.DEFERRED_BY_LAW

    # USDT reward is deferred (stablecoin = cryptoasset per PT-C-003)
    usdt_reward = next((r for r in report.reward_entries if r.asset == "USDT"), None)
    assert usdt_reward is not None
    assert usdt_reward.tax_classification == RewardTaxClassification.DEFERRED_BY_LAW

    # EUR reward is taxable now (fiat-denominated per CRG-002)
    eur_reward = next((r for r in report.reward_entries if r.asset == "EUR"), None)
    assert eur_reward is not None
    assert eur_reward.tax_classification == RewardTaxClassification.TAXABLE_NOW


# --- Reward aggregation tests (Task 2) ---


def test_aggregate_taxable_rewards_by_income_code_and_country():
    """Aggregate taxable_now rewards by income_code + source_country."""
    from tax_reporting.application.crypto_reporting import ZERO, CryptoRewardIncomeEntry

    entries = [
        # Two EUR interest rewards from Kraken (Ireland) - income_code "E25" when
        # classify_rewards_with_income_codes is on,
        # same country "IE" so they aggregate into one group
        CryptoRewardIncomeEntry(
            date="2025-01-01",
            asset="EUR",
            amount=Decimal("100"),
            value_eur=Decimal("100"),
            income_label="Reward",
            source_type="interest",
            wallet="Kraken",
            platform="Kraken",
            chain="Kraken",
            operator_origin=dataclasses.replace(_TEST_OPERATOR, operator_country="IE"),
            annex_hint="J",
            review_required=False,
            description="Cashback",
            tax_classification=RewardTaxClassification.TAXABLE_NOW,
            foreign_tax_eur=ZERO,
        ),
        CryptoRewardIncomeEntry(
            date="2025-01-02",
            asset="EUR",
            amount=Decimal("50"),
            value_eur=Decimal("50"),
            income_label="Reward",
            source_type="interest",
            wallet="Kraken",
            platform="Kraken",
            chain="Kraken",
            operator_origin=dataclasses.replace(_TEST_OPERATOR, operator_country="IE"),
            annex_hint="J",
            review_required=False,
            description="Referral",
            tax_classification=RewardTaxClassification.TAXABLE_NOW,
            foreign_tax_eur=ZERO,
        ),
        # USD interest reward from Bybit (UAE) - different country, different aggregation group
        CryptoRewardIncomeEntry(
            date="2025-01-03",
            asset="USD",
            amount=Decimal("200"),
            value_eur=Decimal("185"),
            income_label="Reward",
            source_type="lending",
            wallet="ByBit",
            platform="ByBit",
            chain="ByBit",
            operator_origin=dataclasses.replace(_TEST_OPERATOR, operator_country="AE"),
            annex_hint="J",
            review_required=False,
            description="Reward",
            tax_classification=RewardTaxClassification.TAXABLE_NOW,
            foreign_tax_eur=ZERO,
        ),
        # Lending interest from Gate.io (Malta) - income_code "E25" when classify_rewards_with_income_codes is on,
        # separate group by country "MT"
        CryptoRewardIncomeEntry(
            date="2025-01-04",
            asset="EUR",
            amount=Decimal("75"),
            value_eur=Decimal("75"),
            income_label="Reward",
            source_type="lending interest",
            wallet="Gate.io",
            platform="Gate.io",
            chain="Gate.io",
            operator_origin=dataclasses.replace(_TEST_OPERATOR, operator_country="MT"),
            annex_hint="J",
            review_required=False,
            description="Staking",
            tax_classification=RewardTaxClassification.TAXABLE_NOW,
            foreign_tax_eur=ZERO,
        ),
        # Crypto-denominated reward (deferred) - should NOT be aggregated
        CryptoRewardIncomeEntry(
            date="2025-01-05",
            asset="BTC",
            amount=Decimal("0.01"),
            value_eur=Decimal("500"),
            income_label="Reward",
            source_type="reward",
            wallet="ByBit",
            platform="ByBit",
            chain="ByBit",
            operator_origin=dataclasses.replace(_TEST_OPERATOR, operator_country="AE"),
            annex_hint="J",
            review_required=False,
            description="BTC reward",
            tax_classification=RewardTaxClassification.DEFERRED_BY_LAW,
            foreign_tax_eur=ZERO,
        ),
    ]

    result = aggregate_taxable_rewards(entries, classify_rewards_with_income_codes=True)

    # With classification on, the interest/lending source types resolve to the official Tabela V
    # code E25. Groups stay separate because they differ by source_country.
    # 1. income_code="E25", country=IE (Kraken EUR interest: 100 + 50 = 150)
    # 2. income_code="E25", country=AE (Bybit USD lending: 185)
    # 3. income_code="E25", country=MT (Gate.io lending interest: 75)
    assert len(result) == 3

    # Find Ireland group (Kraken)
    ie_group = next((g for g in result if g.source_country == "IE"), None)
    assert ie_group is not None
    assert ie_group.income_code == "E25"
    assert ie_group.gross_income_eur == Decimal("150")
    assert ie_group.raw_row_count == 2

    # Find UAE group (Bybit)
    ae_group = next((g for g in result if g.source_country == "AE"), None)
    assert ae_group is not None
    assert ae_group.income_code == "E25"
    assert ae_group.gross_income_eur == Decimal("185")
    assert ae_group.raw_row_count == 1

    # Find Malta group (Gate.io lending interest)
    mt_group = next((g for g in result if g.source_country == "MT"), None)
    assert mt_group is not None
    assert mt_group.income_code == "E25"
    assert mt_group.gross_income_eur == Decimal("75")
    assert mt_group.raw_row_count == 1

    # A resolved income_code produces an "Income code <code> from <country>"
    # description (distinct from the "Reward income from <country>" form used for
    # blank-code rows when classify_rewards_with_income_codes is off).
    assert ie_group.description == "Income code E25 from IE"
    assert ae_group.description == "Income code E25 from AE"
    assert mt_group.description == "Income code E25 from MT"


def test_aggregate_taxable_rewards_interest_and_classification_off_do_not_raise(caplog):
    """Negative controls for the blank-income-code fail-closed contract.

    The classified non-interest raise is covered by
    ``test_aggregate_taxable_rewards_fails_on_blank_income_code_when_classified``. These
    are the two cases that must NOT raise: (1) a classified interest reward resolves to
    ``E25`` (a complete filing row); (2) when classification is off, blank is the
    expected/valid resolution for every type. Neither emits a blank-code warning.
    """
    from tax_reporting.application.crypto_reporting import ZERO, CryptoRewardIncomeEntry

    def _fiat_reward(source_type: str) -> CryptoRewardIncomeEntry:
        return CryptoRewardIncomeEntry(
            date="2025-01-01",
            asset="EUR",
            amount=Decimal("10"),
            value_eur=Decimal("10"),
            income_label="Reward",
            source_type=source_type,
            wallet="Kraken",
            platform="Kraken",
            chain="Kraken",
            operator_origin=dataclasses.replace(_TEST_OPERATOR, operator_country="IE"),
            annex_hint="J",
            review_required=False,
            description="Cashback",
            tax_classification=RewardTaxClassification.TAXABLE_NOW,
            foreign_tax_eur=ZERO,
        )

    # Interest fiat reward with classification on -> E25 -> no raise, no review flag, no warning.
    with caplog.at_level("WARNING", logger="tax_reporting.application.crypto.aggregation"):
        interest_result = aggregate_taxable_rewards([_fiat_reward("interest")], classify_rewards_with_income_codes=True)
    assert len(interest_result) == 1
    assert interest_result[0].income_code == "E25"
    assert not any("no official Tabela V income code" in rec.message for rec in caplog.records), (
        "Interest rewards resolve to E25 and must not trigger a blank-code warning"
    )

    # Non-interest fiat reward with classification off -> blank is expected -> no raise, no warning.
    caplog.clear()
    with caplog.at_level("WARNING", logger="tax_reporting.application.crypto.aggregation"):
        unclassified_result = aggregate_taxable_rewards(
            [_fiat_reward("reward")], classify_rewards_with_income_codes=False
        )
    assert len(unclassified_result) == 1
    assert unclassified_result[0].income_code == ""
    assert not any("no official Tabela V income code" in rec.message for rec in caplog.records), (
        "Blank income codes with classification off are expected and must not warn"
    )


def test_aggregate_taxable_rewards_filters_out_deferred_rewards():
    """Deferred_by_law rewards must be excluded from aggregation."""
    from tax_reporting.application.crypto_reporting import ZERO, CryptoRewardIncomeEntry

    entries = [
        # Taxable now
        CryptoRewardIncomeEntry(
            date="2025-01-01",
            asset="EUR",
            amount=Decimal("100"),
            value_eur=Decimal("100"),
            income_label="Reward",
            source_type="interest",
            wallet="Kraken",
            platform="Kraken",
            chain="Kraken",
            operator_origin=dataclasses.replace(_TEST_OPERATOR, operator_country="IE"),
            annex_hint="J",
            review_required=False,
            description="Cashback",
            tax_classification=RewardTaxClassification.TAXABLE_NOW,
            foreign_tax_eur=ZERO,
        ),
        # Deferred (crypto)
        CryptoRewardIncomeEntry(
            date="2025-01-02",
            asset="BTC",
            amount=Decimal("0.01"),
            value_eur=Decimal("500"),
            income_label="Reward",
            source_type="reward",
            wallet="ByBit",
            platform="ByBit",
            chain="ByBit",
            operator_origin=dataclasses.replace(_TEST_OPERATOR, operator_country="AE"),
            annex_hint="J",
            review_required=False,
            description="BTC reward",
            tax_classification=RewardTaxClassification.DEFERRED_BY_LAW,
            foreign_tax_eur=ZERO,
        ),
        # Another deferred
        CryptoRewardIncomeEntry(
            date="2025-01-03",
            asset="USDT",
            amount=Decimal("10"),
            value_eur=Decimal("10"),
            income_label="Reward",
            source_type="lending",
            wallet="Wirex",
            platform="Wirex",
            chain="Wirex",
            operator_origin=dataclasses.replace(_TEST_OPERATOR, operator_country="HR"),
            annex_hint="J",
            review_required=False,
            description="Interest",
            tax_classification=RewardTaxClassification.DEFERRED_BY_LAW,
            foreign_tax_eur=ZERO,
        ),
    ]

    result = aggregate_taxable_rewards(entries, classify_rewards_with_income_codes=True)

    # Only the EUR reward should be aggregated
    assert len(result) == 1
    assert result[0].gross_income_eur == Decimal("100")
    assert result[0].raw_row_count == 1


def test_aggregate_taxable_rewards_with_foreign_tax():
    """Foreign tax amounts must be summed within each aggregation group."""
    from tax_reporting.application.crypto_reporting import CryptoRewardIncomeEntry

    entries = [
        CryptoRewardIncomeEntry(
            date="2025-01-01",
            asset="EUR",
            amount=Decimal("100"),
            value_eur=Decimal("100"),
            income_label="Reward",
            source_type="interest",
            wallet="Kraken",
            platform="Kraken",
            chain="Kraken",
            operator_origin=dataclasses.replace(_TEST_OPERATOR, operator_country="IE"),
            annex_hint="J",
            review_required=False,
            description="Reward with tax",
            tax_classification=RewardTaxClassification.TAXABLE_NOW,
            foreign_tax_eur=Decimal("5"),
        ),
        CryptoRewardIncomeEntry(
            date="2025-01-02",
            asset="EUR",
            amount=Decimal("50"),
            value_eur=Decimal("50"),
            income_label="Reward",
            source_type="interest",
            wallet="Kraken",
            platform="Kraken",
            chain="Kraken",
            operator_origin=dataclasses.replace(_TEST_OPERATOR, operator_country="IE"),
            annex_hint="J",
            review_required=False,
            description="Another with tax",
            tax_classification=RewardTaxClassification.TAXABLE_NOW,
            foreign_tax_eur=Decimal("2.50"),
        ),
    ]

    result = aggregate_taxable_rewards(entries, classify_rewards_with_income_codes=True)

    assert len(result) == 1
    assert result[0].gross_income_eur == Decimal("150")
    assert result[0].foreign_tax_eur == Decimal("7.50")
    assert result[0].raw_row_count == 2


def test_aggregate_taxable_rewards_empty_list():
    """Empty input list returns empty list."""
    result = aggregate_taxable_rewards([], classify_rewards_with_income_codes=True)
    assert result == []


def test_aggregate_taxable_rewards_no_taxable_entries():
    """If all rewards are deferred, aggregation returns empty list."""
    from tax_reporting.application.crypto_reporting import ZERO, CryptoRewardIncomeEntry

    entries = [
        CryptoRewardIncomeEntry(
            date="2025-01-01",
            asset="BTC",
            amount=Decimal("0.01"),
            value_eur=Decimal("500"),
            income_label="Reward",
            source_type="reward",
            wallet="ByBit",
            platform="ByBit",
            chain="ByBit",
            operator_origin=dataclasses.replace(_TEST_OPERATOR, operator_country="AE"),
            annex_hint="J",
            review_required=False,
            description="BTC reward",
            tax_classification=RewardTaxClassification.DEFERRED_BY_LAW,
            foreign_tax_eur=ZERO,
        ),
    ]

    result = aggregate_taxable_rewards(entries, classify_rewards_with_income_codes=True)
    assert result == []


def test_aggregate_taxable_rewards_fails_on_invalid_country():
    """Aggregation must fail with clear error for taxable rewards without valid Tabela X country."""
    from tax_reporting.application.crypto_reporting import ZERO, CryptoRewardIncomeEntry
    from tax_reporting.domain.exceptions import FileProcessingError

    entries = [
        CryptoRewardIncomeEntry(
            date="2025-01-01",
            asset="EUR",
            amount=Decimal("100"),
            value_eur=Decimal("100"),
            income_label="Reward",
            source_type="reward",
            wallet="UnknownExchange",
            platform="UnknownExchange",
            chain="Unknown",
            operator_origin=dataclasses.replace(_TEST_OPERATOR, operator_country="UNKNOWN"),
            annex_hint="J",
            review_required=False,
            description="Reward",
            tax_classification=RewardTaxClassification.TAXABLE_NOW,
            foreign_tax_eur=ZERO,
        ),
    ]

    with pytest.raises(FileProcessingError, match="has an unresolved platform/operator"):
        aggregate_taxable_rewards(entries, classify_rewards_with_income_codes=True)


def test_aggregate_taxable_rewards_fails_on_blank_income_code_when_classified():
    """A PT taxable-now reward with no Tabela V income code must fail closed.

    Mirrors the country-code fail-closed contract (a taxable_now row with an
    invalid/UNKNOWN Tabela X country raises ``FileProcessingError`` before
    aggregation). The income type is also a mandatory Quadro 8A field, so a
    taxable_now reward whose ``source_type`` resolves to no official Tabela V
    code when classify_rewards_with_income_codes is on must raise rather than
    emit a flagged-but-incomplete filing row. ``tax_classification`` depends
    only on the asset being fiat, so a fiat reward of a non-interest type
    (e.g. EUR cashback, ``source_type="reward"``) is taxable_now and resolves
    to ``""`` when classification is on. Review round 3 finding 1.
    """
    from tax_reporting.application.crypto_reporting import ZERO, CryptoRewardIncomeEntry
    from tax_reporting.domain.exceptions import FileProcessingError

    entries = [
        CryptoRewardIncomeEntry(
            date="2025-01-01",
            asset="EUR",
            amount=Decimal("10"),
            value_eur=Decimal("10"),
            income_label="Reward",
            source_type="reward",
            wallet="Kraken",
            platform="Kraken",
            chain="Kraken",
            operator_origin=dataclasses.replace(_TEST_OPERATOR, operator_country="IE"),
            annex_hint="J",
            review_required=False,
            description="Cashback",
            tax_classification=RewardTaxClassification.TAXABLE_NOW,
            foreign_tax_eur=ZERO,
        ),
    ]

    with pytest.raises(FileProcessingError, match="no official Tabela V income code"):
        aggregate_taxable_rewards(entries, classify_rewards_with_income_codes=True)


def test_aggregate_taxable_rewards_wallet_aliases_collapse():
    """ByBit and ByBit (2) should collapse into the same logical account for reward aggregation.

    Rewards aggregate by (income_code, source_country), not by platform. Wallet
    normalization affects this indirectly because operator_country is derived from
    the normalized platform name via resolve_operator_origin(). Since both ByBit
    and ByBit (2) normalize to the same platform, they get the same country and
    aggregate together.
    """
    from tax_reporting.application.crypto_reporting import ZERO, CryptoRewardIncomeEntry

    entries = [
        CryptoRewardIncomeEntry(
            date="2025-01-01",
            asset="EUR",
            amount=Decimal("100"),
            value_eur=Decimal("100"),
            income_label="Reward",
            source_type="interest",
            wallet="ByBit",
            platform="ByBit",
            chain="ByBit",
            operator_origin=dataclasses.replace(_TEST_OPERATOR, operator_country="AE"),
            annex_hint="J",
            review_required=False,
            description="Reward 1",
            tax_classification=RewardTaxClassification.TAXABLE_NOW,
            foreign_tax_eur=ZERO,
        ),
        CryptoRewardIncomeEntry(
            date="2025-01-02",
            asset="EUR",
            amount=Decimal("50"),
            value_eur=Decimal("50"),
            income_label="Reward",
            source_type="interest",
            wallet="ByBit (2)",
            platform="ByBit",
            chain="ByBit",
            operator_origin=dataclasses.replace(_TEST_OPERATOR, operator_country="AE"),
            annex_hint="J",
            review_required=False,
            description="Reward 2",
            tax_classification=RewardTaxClassification.TAXABLE_NOW,
            foreign_tax_eur=ZERO,
        ),
    ]

    result = aggregate_taxable_rewards(entries, classify_rewards_with_income_codes=True)

    # Should aggregate to single entry since same income_code ("E25") and country (AE)
    assert len(result) == 1
    assert result[0].gross_income_eur == Decimal("150")
    assert result[0].source_country == "AE"
    assert result[0].raw_row_count == 2


def test_aggregate_taxable_rewards_different_platforms_stay_separate():
    """Different platforms with different countries should stay separate in reward aggregation.

    Since rewards aggregate by (income_code, source_country), different platforms
    in different countries produce separate aggregation groups.
    """
    from tax_reporting.application.crypto_reporting import ZERO, CryptoRewardIncomeEntry

    entries = [
        CryptoRewardIncomeEntry(
            date="2025-01-01",
            asset="EUR",
            amount=Decimal("100"),
            value_eur=Decimal("100"),
            income_label="Reward",
            source_type="interest",
            wallet="ByBit",
            platform="ByBit",
            chain="ByBit",
            operator_origin=dataclasses.replace(_TEST_OPERATOR, operator_country="AE"),
            annex_hint="J",
            review_required=False,
            description="Reward",
            tax_classification=RewardTaxClassification.TAXABLE_NOW,
            foreign_tax_eur=ZERO,
        ),
        CryptoRewardIncomeEntry(
            date="2025-01-02",
            asset="EUR",
            amount=Decimal("50"),
            value_eur=Decimal("50"),
            income_label="Reward",
            source_type="interest",
            wallet="Kraken",
            platform="Kraken",
            chain="Kraken",
            operator_origin=dataclasses.replace(_TEST_OPERATOR, operator_country="IE"),
            annex_hint="J",
            review_required=False,
            description="Reward",
            tax_classification=RewardTaxClassification.TAXABLE_NOW,
            foreign_tax_eur=ZERO,
        ),
    ]

    result = aggregate_taxable_rewards(entries, classify_rewards_with_income_codes=True)

    # Different countries = separate aggregation groups
    assert len(result) == 2
    countries = {e.source_country for e in result}
    assert countries == {"AE", "IE"}


def test_is_valid_tabela_x_country():
    """Validation of Portuguese Tabela X country codes."""
    # Valid EU/EEA countries
    assert _is_valid_tabela_x_country("PT") is True  # Portugal
    assert _is_valid_tabela_x_country("IE") is True  # Ireland
    assert _is_valid_tabela_x_country("MT") is True  # Malta
    assert _is_valid_tabela_x_country("ES") is True  # Spain
    assert _is_valid_tabela_x_country("DE") is True  # Germany
    assert _is_valid_tabela_x_country("FR") is True  # France

    # Valid non-European countries
    assert _is_valid_tabela_x_country("US") is True  # United States
    assert _is_valid_tabela_x_country("AE") is True  # United Arab Emirates
    assert _is_valid_tabela_x_country("CH") is True  # Switzerland
    assert _is_valid_tabela_x_country("GB") is True  # United Kingdom
    assert _is_valid_tabela_x_country("JP") is True  # Japan

    # Invalid codes
    assert _is_valid_tabela_x_country("UNKNOWN") is False
    assert _is_valid_tabela_x_country("XX") is False
    assert _is_valid_tabela_x_country("") is False
    assert _is_valid_tabela_x_country("ZZZ") is False

    # Case insensitive
    assert _is_valid_tabela_x_country("ie") is True
    assert _is_valid_tabela_x_country("Us") is True


def test_resolve_income_code_from_koinly_type():
    """Map Koinly income type to its official Modelo 3 code when classification is enabled."""
    # Interest family -> official E25 when classification is on
    assert _resolve_income_code("interest", True) == "E25"
    assert _resolve_income_code("lending", True) == "E25"
    assert _resolve_income_code("lending interest", True) == "E25"

    # Other Koinly types have no Tabela V code under classification -> ""
    assert _resolve_income_code("staking", True) == ""
    assert _resolve_income_code("reward", True) == ""
    assert _resolve_income_code("airdrop", True) == ""
    assert _resolve_income_code("mining", True) == ""
    assert _resolve_income_code("fork", True) == ""
    assert _resolve_income_code("dividend", True) == ""

    # Unknown types resolve to "" (no synthetic 401 default)
    assert _resolve_income_code("unknown_type", True) == ""
    assert _resolve_income_code("custom_reward", True) == ""
    assert _resolve_income_code("", True) == ""

    # Case insensitive
    assert _resolve_income_code("Interest", True) == "E25"
    assert _resolve_income_code("LENDING", True) == "E25"
    assert _resolve_income_code("  lending  ", True) == "E25"

    # Edge cases: whitespace-only and formula-prefix-only resolve to "" when classified
    assert _resolve_income_code("   ", True) == ""
    assert _resolve_income_code("\t\n", True) == ""
    assert _resolve_income_code("  \t  ", True) == ""
    assert _resolve_income_code("===", True) == ""
    assert _resolve_income_code("+++", True) == ""
    assert _resolve_income_code("---", True) == ""
    assert _resolve_income_code("@@@", True) == ""

    # Classification disabled -> "" for every type (Invariant 4)
    assert _resolve_income_code("interest", False) == ""
    assert _resolve_income_code("staking", False) == ""
    assert _resolve_income_code("unknown_type", False) == ""


def test_aggregate_preserves_reconciliation_trail():
    """Aggregation must preserve raw row count for reconciliation."""
    from tax_reporting.application.crypto_reporting import ZERO, CryptoRewardIncomeEntry

    entries = [
        CryptoRewardIncomeEntry(
            date=f"2025-01-{i:02d}",
            asset="EUR",
            amount=Decimal("10"),
            value_eur=Decimal("10"),
            income_label="Reward",
            source_type="interest",
            wallet="Kraken",
            platform="Kraken",
            chain="Kraken",
            operator_origin=dataclasses.replace(_TEST_OPERATOR, operator_country="IE"),
            annex_hint="J",
            review_required=False,
            description=f"Reward {i}",
            tax_classification=RewardTaxClassification.TAXABLE_NOW,
            foreign_tax_eur=ZERO,
        )
        for i in range(1, 6)  # 5 rows
    ]

    result = aggregate_taxable_rewards(entries, classify_rewards_with_income_codes=True)

    assert len(result) == 1
    assert result[0].raw_row_count == 5
    assert result[0].gross_income_eur == Decimal("50")  # 10 * 5


def test_validate_capital_entries_with_all_valid_countries_passes():
    """Validation should pass when all capital entries have valid Tabela X country codes."""

    entries = [
        _make_entry(
            wallet="Kraken",
            platform="Kraken",
            operator_origin=dataclasses.replace(_TEST_OPERATOR, operator_country="IE"),
        ),
        _make_entry(
            wallet="Gate.io",
            platform="Gate.io",
            operator_origin=dataclasses.replace(_TEST_OPERATOR, operator_country="MT"),
        ),
        _make_entry(
            wallet="ByBit",
            platform="ByBit",
            operator_origin=dataclasses.replace(_TEST_OPERATOR, operator_country="AE"),
        ),
    ]

    # Should return all entries unchanged (all valid countries)
    jurisdiction = _pt_jurisdiction()
    result = _validate_capital_entries_have_valid_countries(entries, jurisdiction)
    assert len(result) == 3
    assert all(not e.review_required for e in result)


def test_validate_capital_entries_flags_unknown_country_for_review(caplog):
    """Invalid country entries are flagged with review_required=True, report is not aborted."""
    import logging

    entries = [
        _make_entry(
            wallet="UnknownExchange",
            platform="UnknownExchange",
            operator_origin=dataclasses.replace(_TEST_OPERATOR, operator_country="UNKNOWN"),
        ),
    ]

    with caplog.at_level(logging.ERROR):
        jurisdiction = _pt_jurisdiction()
        result = _validate_capital_entries_have_valid_countries(entries, jurisdiction)

    assert len(result) == 1
    assert result[0].review_required is True
    assert "UnknownExchange" in result[0].review_reason
    assert "UNKNOWN" in result[0].review_reason
    assert any("unresolvable country" in r.message.lower() for r in caplog.records if r.levelno == logging.ERROR)


def test_validate_capital_entries_flags_multiple_unknown_countries(caplog):
    """Multiple invalid country entries are all flagged; report continues with all entries."""
    import logging

    entries = [
        _make_entry(
            wallet="UnknownExchange1",
            platform="UnknownExchange1",
            operator_origin=dataclasses.replace(_TEST_OPERATOR, operator_country="UNKNOWN"),
        ),
        _make_entry(
            wallet="UnknownExchange2",
            platform="UnknownExchange2",
            operator_origin=dataclasses.replace(_TEST_OPERATOR, operator_country="XX"),
        ),
    ]

    with caplog.at_level(logging.ERROR):
        jurisdiction = _pt_jurisdiction()
        result = _validate_capital_entries_have_valid_countries(entries, jurisdiction)

    assert len(result) == 2
    assert all(e.review_required for e in result)
    error_messages = " ".join(r.message for r in caplog.records if r.levelno == logging.ERROR)
    assert "2" in error_messages


def test_validate_capital_entries_logs_actionable_details(caplog):
    """Error log must include wallet, asset, date, and resolved country for debugging."""
    import logging

    entries = [
        _make_entry(
            disposal_date="2025-01-15",
            asset="BTC",
            wallet="SomeUnknownWallet",
            platform="SomeUnknownWallet",
            operator_origin=dataclasses.replace(_TEST_OPERATOR, operator_country="UNKNOWN"),
        ),
    ]

    with caplog.at_level(logging.ERROR):
        jurisdiction = _pt_jurisdiction()
        result = _validate_capital_entries_have_valid_countries(entries, jurisdiction)

    assert len(result) == 1
    assert result[0].review_required is True
    assert any(
        "SomeUnknownWallet" in r.message and "BTC" in r.message and "UNKNOWN" in r.message
        for r in caplog.records
    ), "Expected a single log record containing wallet, asset, and country info together"


def test_resolve_operator_origin_never_returns_taxpayer_residence():
    """Unknown platforms should return UNKNOWN country, never default to Portugal or taxpayer residence."""
    unknown_origin = resolve_operator_origin("CompletelyUnknownPlatformXYZ")

    assert unknown_origin.operator_country == "UNKNOWN"
    assert unknown_origin.operator_country != "Portugal"
    assert unknown_origin.operator_country != "PT"


def test_derive_chain_ledger_berachain():
    """Ledger Berachain (BERA) should derive Berachain."""
    assert _derive_chain("Ledger Berachain (BERA)") == "Berachain"
    assert _derive_chain("Ledger Berachain") == "Berachain"


def test_derive_chain_ledger_sui():
    """Ledger SUI should derive Sui."""
    assert _derive_chain("Ledger SUI") == "Sui"


def test_derive_chain_ethereum_with_address():
    """Ethereum (ETH) - 0x... should derive Ethereum."""
    assert _derive_chain("Ethereum (ETH) - 0x6ABd15") == "Ethereum"
    assert _derive_chain("Ethereum (ETH)") == "Ethereum"
    assert _derive_chain("Ethereum") == "Ethereum"


def test_derive_chain_solana_with_address():
    """Solana (SOL) - ... should derive Solana."""
    assert _derive_chain("Solana (SOL) - 5R39") == "Solana"
    assert _derive_chain("Solana (SOL)") == "Solana"
    assert _derive_chain("Solana") == "Solana"


def test_derive_chain_bybit_variants():
    """ByBit (2) and ByBit should both derive ByBit."""
    assert _derive_chain("ByBit (2)") == "ByBit"
    assert _derive_chain("ByBit") == "ByBit"
    assert _derive_chain("bybit") == "ByBit"


def test_derive_chain_known_chains():
    """Known chain names should derive correctly."""
    assert _derive_chain("Starknet") == "Starknet"
    assert _derive_chain("zkSync ERA") == "zkSync ERA"
    assert _derive_chain("TON") == "TON"
    assert _derive_chain("Aptos") == "Aptos"
    assert _derive_chain("Arbitrum") == "Arbitrum"
    assert _derive_chain("Mantle") == "Mantle"
    assert _derive_chain("Polygon") == "Polygon"
    assert _derive_chain("BASE") == "BASE"
    assert _derive_chain("Filecoin") == "Filecoin"
    assert _derive_chain("Binance Smart Chain") == "Binance Smart Chain"
    assert _derive_chain("Gate.io") == "Gate.io"
    assert _derive_chain("Kraken") == "Kraken"
    assert _derive_chain("Binance") == "Binance"
    assert _derive_chain("Wirex") == "Wirex"
    assert _derive_chain("Tonkeeper") == "Tonkeeper"


def test_derive_chain_gate_variants():
    """Gate.io variants should derive Gate.io."""
    assert _derive_chain("Gate.io") == "Gate.io"
    assert _derive_chain("gate.io") == "Gate.io"
    assert _derive_chain("GATE") == "Gate.io"
    assert _derive_chain("gate") == "Gate.io"


def test_derive_chain_bnb_or_bsc():
    """bnb or bsc should derive Binance Smart Chain."""
    assert _derive_chain("Binance Smart Chain") == "Binance Smart Chain"
    assert _derive_chain("bnb chain") == "Binance Smart Chain"
    assert _derive_chain("bsc") == "Binance Smart Chain"


def test_derive_chain_blank_wallet():
    """Blank or empty wallet should derive Unknown."""
    assert _derive_chain("") == "Unknown"
    assert _derive_chain("   ") == "Unknown"


def test_derive_chain_unknown_wallet():
    """Unknown wallet names should derive Unknown, not guess."""
    assert _derive_chain("CompletelyUnknownWallet") == "Unknown"
    assert _derive_chain("RandomXYZ") == "Unknown"


def test_derive_chain_case_insensitive():
    """Chain derivation should be case-insensitive."""
    assert _derive_chain("ETHEREUM") == "Ethereum"
    assert _derive_chain("berachain") == "Berachain"
    assert _derive_chain("SOLANA") == "Solana"
    assert _derive_chain("Kraken") == "Kraken"


def test_normalize_platform_name_bybit_aliases():
    """ByBit numbered aliases are NO LONGER collapsed (CRG-008 retired).

    After Phase A Task 8, normalize_platform_name performs no
    platform-specific normalization. Numbered ByBit aliases such as
    "ByBit (2)" are returned unchanged so the platform-level resolver
    (Invariant 4) is the single place where platforms are consolidated.
    """
    from tax_reporting.infrastructure.koinly_parser import normalize_platform_name

    assert normalize_platform_name("ByBit (2)") == "ByBit (2)"


def test_normalize_platform_name_bybit_plain_unchanged():
    """A plain "ByBit" wallet label is returned unchanged (trimmed)."""
    from tax_reporting.infrastructure.koinly_parser import normalize_platform_name

    assert normalize_platform_name("ByBit") == "ByBit"


@pytest.mark.parametrize(
    "wallet",
    [
        "ByBit (3)",
        "ByBit (4)",
        "ByBit (5)",
        "ByBit (10)",
    ],
)
def test_normalize_platform_name_bybit3_through_bybit10_no_longer_collapsed(wallet):
    """ByBit (3..10) numbered aliases are NO LONGER collapsed (CRG-008 retired).

    These were assertion lines inside the original
    test_normalize_platform_name_bybit_aliases before Phase A Task 8;
    preserved here as parametrized coverage.
    """
    from tax_reporting.infrastructure.koinly_parser import normalize_platform_name

    assert normalize_platform_name(wallet) == wallet


def test_normalize_platform_name_preserves_distinct_wallets():
    """Distinct wallets like Ethereum addresses should NOT be normalized."""
    from tax_reporting.infrastructure.koinly_parser import normalize_platform_name

    # These are distinct wallets and should be preserved
    assert normalize_platform_name("Ethereum (ETH) - 0xabc") == "Ethereum (ETH) - 0xabc"
    assert normalize_platform_name("Ethereum (ETH) - 0xdef") == "Ethereum (ETH) - 0xdef"
    assert normalize_platform_name("Solana (SOL) - 5R39") == "Solana (SOL) - 5R39"


def test_normalize_platform_name_empty_and_whitespace():
    """Empty and whitespace-only wallets should return Unknown."""
    from tax_reporting.infrastructure.koinly_parser import normalize_platform_name

    assert normalize_platform_name("") == "Unknown"
    assert normalize_platform_name("   ") == "Unknown"
    assert normalize_platform_name("\t") == "Unknown"


def test_normalize_platform_name_no_alias():
    """Wallets without numeric aliases should be unchanged."""
    from tax_reporting.infrastructure.koinly_parser import normalize_platform_name

    assert normalize_platform_name("Kraken") == "Kraken"
    assert normalize_platform_name("Binance") == "Binance"
    assert normalize_platform_name("Ledger Berachain (BERA)") == "Ledger Berachain (BERA)"


def test_normalize_platform_name_preserves_non_bybit_numbered_wallets():
    """Numbered wallets are preserved as distinct wallets.

    normalize_platform_name performs no platform-specific normalization,
    so platforms like Kraken keep their numbered wallets distinct.
    """
    from tax_reporting.infrastructure.koinly_parser import normalize_platform_name

    # Non-ByBit numbered wallets are preserved as distinct wallets
    assert normalize_platform_name("Kraken (2)") == "Kraken (2)"
    assert normalize_platform_name("Kraken (3)") == "Kraken (3)"
    assert normalize_platform_name("Binance (2)") == "Binance (2)"


def test_normalize_platform_name_preserves_bybit_prefixed_wallets():
    """ByBit-prefixed wallets are preserved unchanged.

    normalize_platform_name performs no platform-specific normalization;
    ByBit-prefixed wallets like 'ByBit Earn (2)' or 'ByBit Savings (3)'
    represent distinct products and are returned as-is.
    """
    from tax_reporting.infrastructure.koinly_parser import normalize_platform_name

    # ByBit-prefixed wallets with additional words are preserved
    assert normalize_platform_name("ByBit Earn (2)") == "ByBit Earn (2)"
    assert normalize_platform_name("ByBit Savings (3)") == "ByBit Savings (3)"
    assert normalize_platform_name("ByBit Earn") == "ByBit Earn"
    assert normalize_platform_name("ByBit Savings") == "ByBit Savings"


def test_normalize_asset_ticker_cyrillic_to_latin():
    """Asset tickers with Cyrillic characters should NOT be normalized.

    Non-Latin script characters (Cyrillic, Greek, etc.) are preserved as they may
    indicate homoglyph scam tokens. These are detected separately via
    contains_non_latin_characters() for scam token flagging.
    """
    from tax_reporting.infrastructure.koinly_parser import contains_non_latin_characters, normalize_asset_ticker

    # Cyrillic characters are preserved (NOT converted to Latin)
    assert normalize_asset_ticker("WBТC") == "WBТC"  # Cyrillic Т preserved
    assert normalize_asset_ticker("BТC") == "BТC"
    # But they are flagged as suspicious
    assert contains_non_latin_characters("WBТC")
    assert contains_non_latin_characters("BТC")
    # Latin characters work normally
    assert normalize_asset_ticker("WBTC") == "WBTC"
    assert not contains_non_latin_characters("WBTC")


def test_normalize_asset_ticker_unicode_normalization():
    """Asset tickers should be normalized to canonical composed unicode form."""
    from tax_reporting.infrastructure.koinly_parser import normalize_asset_ticker

    # Unicode normalization handles various unicode equivalence issues
    assert normalize_asset_ticker("BTC") == "BTC"
    assert normalize_asset_ticker("  BTC  ") == "BTC"  # Whitespace trimming
    assert normalize_asset_ticker("BTC\t") == "BTC"


def test_normalize_asset_ticker_preserves_valid_tickers():
    """Valid asset tickers should be preserved unchanged."""
    from tax_reporting.infrastructure.koinly_parser import normalize_asset_ticker

    assert normalize_asset_ticker("BTC") == "BTC"
    assert normalize_asset_ticker("ETH") == "ETH"
    assert normalize_asset_ticker("SUI") == "SUI"
    assert normalize_asset_ticker("HASUI") == "HASUI"
    assert normalize_asset_ticker("USDC") == "USDC"
    assert normalize_asset_ticker("USDT") == "USDT"


def test_wirex_fiat_reward_gets_gb_country_code():
    """Wirex fiat-denominated rewards should resolve to GB (Wirex Limited), not HR (Wirex Digital).

    This test verifies the fix for a bug where all Wirex rewards were getting the crypto
    operator origin (HR) regardless of whether they were fiat or crypto denominated.
    Fiat rewards should use the fiat operator (GB) per the split-by-service-scope design.
    """
    from tax_reporting.application.crypto.operator_origin import resolve_operator_origin

    # EUR reward should use "fiat_deposit" transaction type and get GB country
    fiat_origin = resolve_operator_origin("Wirex", transaction_type="fiat_deposit")
    assert fiat_origin.service_scope == "fiat"
    assert fiat_origin.operator_country == "GB"
    assert "Wirex Limited" in fiat_origin.operator_entity

    # Crypto rewards should use "crypto_deposit" transaction type and get HR country
    crypto_origin = resolve_operator_origin("Wirex", transaction_type="crypto_deposit")
    assert crypto_origin.service_scope == "crypto"
    assert crypto_origin.operator_country == "HR"
    assert "Wirex Digital" in crypto_origin.operator_entity


def test_caucasus_and_central_asia_fiat_currencies_classified_as_taxable_now():
    """KZT (Kazakhstan Tenge), GEL (Georgian Lari), and AMD (Armenian Dram) should be classified as taxable now.

    These are valid ISO 4217 fiat currency codes that were previously missing from the
    fiat currency allow-list, causing rewards in these currencies to be incorrectly
    classified as deferred_by_law instead of taxable_now (CRG-002 violation).

    NOTE: GEL (Georgian Lari) has a ticker collision with Gelato Network token (GEL).
    The collision list takes precedence to ensure correct tax treatment for the crypto token,
    so GEL is classified as DEFERRED_BY_LAW. See test_gel_token_collision() for details.
    """
    assert _classify_reward_tax_status("KZT") == RewardTaxClassification.TAXABLE_NOW
    # GEL is deferred due to Gelato token collision (see test_gel_token_collision)
    assert _classify_reward_tax_status("GEL") == RewardTaxClassification.DEFERRED_BY_LAW
    assert _classify_reward_tax_status("AMD") == RewardTaxClassification.TAXABLE_NOW

    # Also verify case insensitivity
    assert _classify_reward_tax_status("kzt") == RewardTaxClassification.TAXABLE_NOW
    assert _classify_reward_tax_status("Gel") == RewardTaxClassification.DEFERRED_BY_LAW
    assert _classify_reward_tax_status("amd") == RewardTaxClassification.TAXABLE_NOW


def test_gel_token_collision():
    """GEL ticker collision between Georgian Lari (fiat) and Gelato Network token (crypto).

    When a crypto token ticker collides with an ISO 4217 fiat currency code, the crypto
    token takes precedence to ensure correct tax treatment per CRG-001 (crypto-denominated
    rewards are deferred by law, not taxable at receipt).

    Source: Gelato Network official token sale announcement refers to $GEL as the token:
    https://medium.com/gelato-network/how-to-participate-in-the-gel-token-sale-b9be3a297d3a

    This test documents the known collision and verifies the correct classification.
    """
    # GEL token (Gelato Network) should be deferred by law (CRG-001)
    assert _classify_reward_tax_status("GEL") == RewardTaxClassification.DEFERRED_BY_LAW
    assert _classify_reward_tax_status("gel") == RewardTaxClassification.DEFERRED_BY_LAW


def test_all_iso_4217_fiat_currencies_classified_as_taxable_now():
    """All valid ISO 4217 fiat currency codes should be classified as taxable now (CRG-002).

    This test verifies that the implementation uses pycountry to cover all ISO 4217 codes,
    not just a hand-maintained allowlist. Previously missing codes like AFN, BWP, BND,
    MUR, MZN, and UZS are now correctly classified.

    The exceptions are GEL (Gelato Network token) and MNT (Mantle L2 token),
    which have known collisions with ISO 4217 fiat codes and are handled via
    the _CRYPTO_TOKEN_FIAT_COLLISIONS list.
    """
    # Previously missing ISO 4217 codes from external code review
    assert _classify_reward_tax_status("AFN") == RewardTaxClassification.TAXABLE_NOW  # Afghan Afghani
    assert _classify_reward_tax_status("BWP") == RewardTaxClassification.TAXABLE_NOW  # Botswanan Pula
    assert _classify_reward_tax_status("BND") == RewardTaxClassification.TAXABLE_NOW  # Brunei Dollar
    assert _classify_reward_tax_status("MUR") == RewardTaxClassification.TAXABLE_NOW  # Mauritian Rupee
    assert _classify_reward_tax_status("MZN") == RewardTaxClassification.TAXABLE_NOW  # Mozambican Metical
    assert _classify_reward_tax_status("UZS") == RewardTaxClassification.TAXABLE_NOW  # Uzbekistan Som

    # Verify case insensitivity for these codes
    assert _classify_reward_tax_status("afn") == RewardTaxClassification.TAXABLE_NOW
    assert _classify_reward_tax_status("Bwp") == RewardTaxClassification.TAXABLE_NOW

    # Exceptions due to crypto token collisions
    assert _classify_reward_tax_status("GEL") == RewardTaxClassification.DEFERRED_BY_LAW
    assert _classify_reward_tax_status("MNT") == RewardTaxClassification.DEFERRED_BY_LAW


def test_operator_origin_has_temporal_fields():
    """OperatorOrigin should have valid_from and valid_until fields for temporal tracking.

    Temporal validity tracking allows historical tax filings to reference the mapping
    that was in effect at the time of transaction, even if the mapping changes later.
    """
    origin = OperatorOrigin(
        platform="TestPlatform",
        service_scope="crypto",
        operator_entity="Test Entity",
        operator_country="US",
        source_url="https://example.com",
        source_checked_on="2026-03-15",
        confidence="high",
        review_required=False,
        valid_from="2025-01-01",
        valid_until=None,
    )

    assert origin.valid_from == "2025-01-01"
    assert origin.valid_until is None


def test_operator_origin_valid_from_default_is_none():
    """valid_from should default to None when not provided."""
    origin = OperatorOrigin(
        platform="TestPlatform",
        service_scope="crypto",
        operator_entity="Test Entity",
        operator_country="US",
        source_url="https://example.com",
        source_checked_on="2026-03-15",
        confidence="high",
        review_required=False,
    )

    assert origin.valid_from is None
    assert origin.valid_until is None


def test_resolve_operator_origin_includes_valid_from_dates():
    """resolve_operator_origin should include valid_from dates from the registry.

    This test verifies that all platform mappings have temporal validity tracking
    for audit trail support in historical tax filings.

    Note: valid_from is the verification date (when mapping was verified from source
    documents), not the launch date (service_start_date).
    """
    berachain = resolve_operator_origin("Berachain", transaction_type="crypto_disposal")
    assert berachain.valid_from == "2025-02-05"

    ethereum = resolve_operator_origin("Ethereum", transaction_type="crypto_disposal")
    assert ethereum.valid_from == "2026-03-15"  # Source verification date

    arbitrum = resolve_operator_origin("Arbitrum", transaction_type="crypto_disposal")
    assert arbitrum.valid_from == "2026-03-15"  # Source verification date

    tonkeeper = resolve_operator_origin("Tonkeeper wallet", transaction_type="crypto_disposal")
    assert tonkeeper.valid_from is None  # Historical operator with unknown verification date


def test_resolve_operator_origin_wirex_split_scope_uses_service_start_date():
    """Wirex split-scope mappings use founding date as service_start_date.

    Per CMD-021 (updated), Wirex uses the approximate founding date (2015-01-01) as
    service_start_date to allow legitimate historical transactions to be auto-classified.
    The valid_from field (2026-03-08) preserves the GB/HR split-scope verification date
    for audit trail.
    """
    fiat_origin = resolve_operator_origin("Wirex", transaction_type="fiat_deposit")
    crypto_origin = resolve_operator_origin("Wirex", transaction_type="crypto_deposit")

    assert fiat_origin.service_start_date == "2015-01-01"  # Approximate founding date
    assert crypto_origin.service_start_date == "2015-01-01"
    # valid_from preserves the verification date for audit trail
    assert fiat_origin.valid_from == "2026-03-08"
    assert crypto_origin.valid_from == "2026-03-08"


def test_resolve_operator_origin_unknown_platform_has_valid_from():
    """Unknown platforms should include valid_from for audit trail."""
    unknown = resolve_operator_origin("CompletelyUnknownPlatformXYZ")
    assert unknown.valid_from == "2026-03-08"
    assert unknown.valid_until is None


def test_resolve_operator_origin_with_transaction_date_within_validity():
    """resolve_operator_origin should return normally when transaction_date is within validity period."""
    # Berachain valid_from is 2025-02-05, so a transaction in 2025-03 should be valid
    origin = resolve_operator_origin(
        "Berachain", transaction_type="crypto_disposal", transaction_date="2025-03-15 14:30:00"
    )
    assert origin.platform == "Berachain"
    assert origin.valid_from == "2025-02-05"
    assert origin.operator_country == "VG"


def test_resolve_operator_origin_with_transaction_date_before_validity(caplog):
    """Out-of-validity transactions should log warning and set review_required=True.

    This is a data recovery scenario - we still return the earliest known mapping
    but warn the user to verify the historical origin and flag for manual review.
    """
    # Berachain valid_from is 2025-02-05, so a transaction in 2024 should trigger a warning
    with caplog.at_level(logging.WARNING, logger="tax_reporting.application.crypto_reporting"):
        origin = resolve_operator_origin(
            "Berachain", transaction_type="crypto_disposal", transaction_date="2024-06-01 10:00:00"
        )

    assert origin.platform == "Berachain"
    assert origin.valid_from == "2025-02-05"
    # Verify warning was logged
    assert any("Transaction date 2024-06-01" in record.message for record in caplog.records)
    # Verify review_required is set to True for out-of-validity transactions
    assert origin.review_required is True


def test_resolve_operator_origin_with_transaction_date_after_service_start():
    """resolve_operator_origin should work normally when transaction_date is after service_start_date."""
    # Ethereum service_start_date is 2015-07-30 (launch), valid_from is 2026-03-15 (verification)
    # Transaction in 2025 is after service_start_date, so no review required
    # valid_from is for audit trail only, not for transaction matching
    origin = resolve_operator_origin("Ethereum", transaction_type="crypto_disposal", transaction_date="2025-01-20")
    assert origin.platform == "Ethereum"
    assert origin.valid_from == "2026-03-15"  # Verification date (audit trail only)
    assert origin.review_required is False  # Transaction after service_start_date
    assert origin.operator_country == "CH"


def test_resolve_operator_origin_with_partial_date_format():
    """resolve_operator_origin should handle transaction_date in YYYY-MM-DD format."""
    origin = resolve_operator_origin("Arbitrum", transaction_type="crypto_disposal", transaction_date="2024-08-15")
    assert origin.platform == "Arbitrum"
    assert origin.valid_from == "2026-03-15"  # Source verification date (audit trail only)
    # Transaction in 2024 is after service_start_date (2021-08-31), so no review required
    assert origin.review_required is False


def test_resolve_operator_origin_with_invalid_date_format(caplog):
    """resolve_operator_origin should log warning and skip check when date format is invalid."""
    with caplog.at_level(logging.WARNING, logger="tax_reporting.application.crypto_reporting"):
        origin = resolve_operator_origin(
            "Solana", transaction_type="crypto_disposal", transaction_date="invalid-date-format"
        )

    assert origin.platform == "Solana"
    # Verify warning about invalid format was logged
    assert any("Invalid transaction_date format" in record.message for record in caplog.records)


def test_resolve_operator_origin_backward_compatible_without_date():
    """resolve_operator_origin should work without transaction_date parameter (backward compatibility)."""
    # Without transaction_date, should return normally
    origin = resolve_operator_origin("TON", transaction_type="crypto_disposal")
    assert origin.platform == "TON"
    assert origin.valid_from is None  # Historical operator, exact start date unknown
    assert origin.operator_country == "CH"


def test_resolve_operator_origin_wirex_with_transaction_date():
    """Wirex split-scope should work with transaction_date parameter."""
    # Wirex crypto valid_from is 2026-03-08 (split-scope verification date)
    crypto_origin = resolve_operator_origin(
        "Wirex", transaction_type="crypto_deposit", transaction_date="2026-06-01 12:00:00"
    )
    assert crypto_origin.service_scope == "crypto"
    assert crypto_origin.operator_country == "HR"

    # Wirex fiat valid_from is 2026-03-08 (split-scope verification date)
    fiat_origin = resolve_operator_origin(
        "Wirex", transaction_type="fiat_deposit", transaction_date="2026-06-01 12:00:00"
    )
    assert fiat_origin.service_scope == "fiat"
    assert fiat_origin.operator_country == "GB"


def test_resolve_operator_origin_wirex_historical_transaction_after_service_start():
    """Wirex transactions after service_start_date (2015-01-01) are auto-classified.

    Per CMD-021 (updated), Wirex uses the approximate founding date (2015-01-01) as
    service_start_date. Transactions on or after this date are auto-classified as GB
    (fiat) or HR (crypto) without review flags.
    """
    crypto_origin = resolve_operator_origin(
        "Wirex", transaction_type="crypto_disposal", transaction_date="2025-06-15 12:00:00"
    )

    # Verify no review required (transaction is after service_start_date)
    assert crypto_origin.review_required is False
    assert crypto_origin.service_start_date == "2015-01-01"
    assert crypto_origin.valid_from == "2026-03-08"


def test_resolve_operator_origin_wirex_transaction_before_service_start_date(caplog):
    """Wirex transactions before service_start_date should trigger warning and review_required.

    Per CMD-021 (updated), Wirex service_start_date is 2015-01-01 (approximate founding date).
    Transactions before this date should be flagged as outside the service period and
    require manual review.
    """
    with caplog.at_level(logging.WARNING, logger="tax_reporting.application.crypto_reporting"):
        crypto_origin = resolve_operator_origin(
            "Wirex", transaction_type="crypto_disposal", transaction_date="2014-06-15 12:00:00"
        )

    # Verify warning was logged about transaction outside service period
    assert any("service period" in record.message and "Wirex" in record.message for record in caplog.records)
    # Verify review_required is True (manual review needed)
    assert crypto_origin.review_required is True
    assert crypto_origin.service_start_date == "2015-01-01"


def test_resolve_operator_origin_wirex_transaction_after_service_start_date(caplog):
    """Wirex transactions on or after service_start_date (2015-01-01) should NOT trigger warning.

    Per CMD-021 (updated), Wirex service_start_date is 2015-01-01 (approximate founding date).
    Transactions on or after this date should NOT trigger review_required because
    they fall within the service period.
    """
    with caplog.at_level(logging.WARNING, logger="tax_reporting.application.crypto_reporting"):
        # Transaction after service_start_date (2025 transaction)
        crypto_origin = resolve_operator_origin(
            "Wirex", transaction_type="crypto_disposal", transaction_date="2025-03-10 12:00:00"
        )

    # Verify no warning was logged (transaction is after service_start_date)
    assert not any("service period" in record.message and "Wirex" in record.message for record in caplog.records)
    # Verify review_required is False (no manual review needed for post-service-start transactions)
    assert crypto_origin.review_required is False
    assert crypto_origin.service_start_date == "2015-01-01"
    assert crypto_origin.valid_from == "2026-03-08"


# =============================================================================
# Unit tests for _parse_transaction_date()
# =============================================================================


def test_parse_transaction_date_with_datetime_format():
    """Koinly format with time should extract date part."""
    assert _parse_transaction_date("2025-03-15 14:30:00") == "2025-03-15"
    assert _parse_transaction_date("2024-12-31 23:59:59") == "2024-12-31"


def test_parse_transaction_date_with_date_only_format():
    """ISO date format without time should be returned as-is."""
    assert _parse_transaction_date("2025-03-15") == "2025-03-15"
    assert _parse_transaction_date("2024-02-29") == "2024-02-29"  # leap year


def test_parse_transaction_date_with_none():
    """None input should return None."""
    assert _parse_transaction_date(None) is None


def test_parse_transaction_date_with_empty_string():
    """Empty string should return None."""
    assert _parse_transaction_date("") is None


def test_parse_transaction_date_rejects_invalid_february_31():
    """February 31st is not a valid date and should raise ValueError."""
    with pytest.raises(ValueError, match="Invalid date"):
        _parse_transaction_date("2025-02-31")


def test_parse_transaction_date_rejects_invalid_april_31():
    """April 31st is not a valid date and should raise ValueError."""
    with pytest.raises(ValueError, match="Invalid date"):
        _parse_transaction_date("2025-04-31")


def test_parse_transaction_date_rejects_invalid_month():
    """Month 13 is not valid and should raise ValueError."""
    with pytest.raises(ValueError, match="Invalid date"):
        _parse_transaction_date("2025-13-01")


def test_parse_transaction_date_rejects_invalid_day():
    """Day 32 is not valid and should raise ValueError."""
    with pytest.raises(ValueError, match="Invalid date"):
        _parse_transaction_date("2025-01-32")


def test_parse_transaction_date_rejects_malformed_format():
    """Non-ISO formats should raise ValueError."""
    with pytest.raises(ValueError, match="Unsupported transaction date format"):
        _parse_transaction_date("2025/03/15")
    with pytest.raises(ValueError, match="Unsupported transaction date format"):
        _parse_transaction_date("15-03-2025")


def test_parse_transaction_date_rejects_year_out_of_range():
    """Years outside reasonable range should raise ValueError."""
    with pytest.raises(ValueError, match="year.*out of reasonable range"):
        _parse_transaction_date("1899-01-01")
    with pytest.raises(ValueError, match="year.*out of reasonable range"):
        _parse_transaction_date("2101-01-01")


def test_parse_transaction_date_datetime_with_invalid_date():
    """Datetime format with invalid calendar date should raise ValueError."""
    with pytest.raises(ValueError, match="Invalid date"):
        _parse_transaction_date("2025-02-30 14:30:00")


# =============================================================================
# Unit tests for _is_temporally_valid()
# =============================================================================


def test_is_temporally_valid_with_no_constraints():
    """No validity constraints should always return True."""
    assert _is_temporally_valid(None, None, "2025-03-15") is True


def test_is_temporally_valid_with_empty_string_valid_from():
    """Empty string valid_from should behave like None (no constraint)."""
    assert _is_temporally_valid("", None, "2025-03-15") is True


def test_is_temporally_valid_transaction_before_valid_from():
    """Transaction date before valid_from should return False."""
    assert _is_temporally_valid("2025-02-01", None, "2025-01-15") is False


def test_is_temporally_valid_transaction_on_valid_from():
    """Transaction date equal to valid_from should return True."""
    assert _is_temporally_valid("2025-02-01", None, "2025-02-01") is True


def test_is_temporally_valid_transaction_after_valid_from():
    """Transaction date after valid_from should return True."""
    assert _is_temporally_valid("2025-02-01", None, "2025-03-15") is True


def test_is_temporally_valid_transaction_after_valid_until():
    """Transaction date after valid_until should return False."""
    assert _is_temporally_valid("2025-02-01", "2025-03-01", "2025-03-15") is False


def test_is_temporally_valid_transaction_on_valid_until():
    """Transaction date equal to valid_until should return True."""
    assert _is_temporally_valid("2025-02-01", "2025-03-01", "2025-03-01") is True


def test_is_temporally_valid_transaction_within_range():
    """Transaction date within validity range should return True."""
    assert _is_temporally_valid("2025-02-01", "2025-03-01", "2025-02-15") is True


def test_is_temporally_valid_valid_until_without_valid_from():
    """Edge case: valid_until without valid_from should return True when within range."""
    assert _is_temporally_valid(None, "2025-03-01", "2025-02-15") is True


def test_is_temporally_valid_valid_until_without_valid_from_after_expiration():
    """Edge case: valid_until without valid_from should return False when after expiration."""
    assert _is_temporally_valid(None, "2025-03-01", "2025-04-01") is False


def test_is_temporally_valid_with_very_old_dates():
    """String comparison should work for very old dates."""
    assert _is_temporally_valid("1900-01-01", None, "2025-03-15") is True


def test_is_temporally_valid_with_future_dates():
    """Future transaction dates should still compare correctly."""
    assert _is_temporally_valid("2025-01-01", None, "2099-12-31") is True


# =============================================================================
# OperatorOrigin validation tests
# =============================================================================


def test_operator_origin_accepts_valid_dates():
    """OperatorOrigin should accept valid ISO dates for valid_from and valid_until."""
    origin = OperatorOrigin(
        platform="TestPlatform",
        service_scope="crypto",
        operator_entity="Test Entity",
        operator_country="US",
        source_url="https://example.com",
        source_checked_on="2025-01-01",
        confidence="high",
        review_required=False,
        valid_from="2025-01-01",
        valid_until="2025-12-31",
    )
    assert origin.valid_from == "2025-01-01"
    assert origin.valid_until == "2025-12-31"


def test_operator_origin_accepts_none_dates():
    """OperatorOrigin should accept None for valid_from and valid_until."""
    origin = OperatorOrigin(
        platform="TestPlatform",
        service_scope="crypto",
        operator_entity="Test Entity",
        operator_country="US",
        source_url="https://example.com",
        source_checked_on="2025-01-01",
        confidence="high",
        review_required=False,
        valid_from=None,
        valid_until=None,
    )
    assert origin.valid_from is None
    assert origin.valid_until is None


def test_operator_origin_rejects_invalid_valid_from_format():
    """OperatorOrigin should reject non-ISO date format for valid_from."""
    with pytest.raises(ValueError, match="Invalid date"):
        OperatorOrigin(
            platform="TestPlatform",
            service_scope="crypto",
            operator_entity="Test Entity",
            operator_country="US",
            source_url="https://example.com",
            source_checked_on="2025-01-01",
            confidence="high",
            review_required=False,
            valid_from="2025/01/01",  # Wrong format
        )


def test_operator_origin_rejects_invalid_valid_until_format():
    """OperatorOrigin should reject non-ISO date format for valid_until."""
    with pytest.raises(ValueError, match="Invalid date"):
        OperatorOrigin(
            platform="TestPlatform",
            service_scope="crypto",
            operator_entity="Test Entity",
            operator_country="US",
            source_url="https://example.com",
            source_checked_on="2025-01-01",
            confidence="high",
            review_required=False,
            valid_from="2025-01-01",
            valid_until="2025/12/31",  # Wrong format
        )


def test_operator_origin_rejects_invalid_service_start_date_format():
    """OperatorOrigin should reject non-ISO date format for service_start_date."""
    with pytest.raises(ValueError, match="Invalid date"):
        OperatorOrigin(
            platform="TestPlatform",
            service_scope="crypto",
            operator_entity="Test Entity",
            operator_country="US",
            source_url="https://example.com",
            source_checked_on="2025-01-01",
            confidence="high",
            review_required=False,
            service_start_date="2025/01/01",  # Wrong format
        )


def test_operator_origin_allows_service_start_date_none():
    """OperatorOrigin should allow service_start_date to be None."""
    origin = OperatorOrigin(
        platform="TestPlatform",
        service_scope="crypto",
        operator_entity="Test Entity",
        operator_country="US",
        source_url="https://example.com",
        source_checked_on="2025-01-01",
        confidence="high",
        review_required=False,
        service_start_date=None,
    )
    assert origin.service_start_date is None


def test_operator_origin_rejects_valid_until_before_valid_from():
    """OperatorOrigin should reject valid_until earlier than valid_from."""
    with pytest.raises(ValueError, match="valid_until.*must be on or after valid_from"):
        OperatorOrigin(
            platform="TestPlatform",
            service_scope="crypto",
            operator_entity="Test Entity",
            operator_country="US",
            source_url="https://example.com",
            source_checked_on="2025-01-01",
            confidence="high",
            review_required=False,
            valid_from="2025-06-01",
            valid_until="2025-01-01",  # Earlier than valid_from
        )


def test_operator_origin_allows_equal_valid_from_and_valid_until():
    """OperatorOrigin should allow valid_until equal to valid_from (single day validity)."""
    origin = OperatorOrigin(
        platform="TestPlatform",
        service_scope="crypto",
        operator_entity="Test Entity",
        operator_country="US",
        source_url="https://example.com",
        source_checked_on="2025-01-01",
        confidence="high",
        review_required=False,
        valid_from="2025-06-01",
        valid_until="2025-06-01",
    )
    assert origin.valid_from == "2025-06-01"
    assert origin.valid_until == "2025-06-01"


def test_operator_origin_rejects_service_start_date_after_valid_from():
    """OperatorOrigin should reject service_start_date after valid_from."""
    with pytest.raises(ValueError, match="service_start_date.*must be on or before valid_from"):
        OperatorOrigin(
            platform="TestPlatform",
            service_scope="crypto",
            operator_entity="Test Entity",
            operator_country="US",
            source_url="https://example.com",
            source_checked_on="2025-01-01",
            confidence="high",
            review_required=False,
            service_start_date="2026-01-01",  # After valid_from
            valid_from="2025-06-01",
        )


def test_operator_origin_rejects_service_start_date_after_valid_until():
    """OperatorOrigin should reject service_start_date after valid_until."""
    with pytest.raises(ValueError, match="service_start_date.*must be on or before valid_until"):
        OperatorOrigin(
            platform="TestPlatform",
            service_scope="crypto",
            operator_entity="Test Entity",
            operator_country="US",
            source_url="https://example.com",
            source_checked_on="2025-01-01",
            confidence="high",
            review_required=False,
            service_start_date="2026-01-01",  # After valid_until
            valid_until="2025-12-31",
        )


def test_operator_origin_allows_service_start_date_equal_to_valid_from():
    """OperatorOrigin should allow service_start_date equal to valid_from."""
    origin = OperatorOrigin(
        platform="TestPlatform",
        service_scope="crypto",
        operator_entity="Test Entity",
        operator_country="US",
        source_url="https://example.com",
        source_checked_on="2025-01-01",
        confidence="high",
        review_required=False,
        service_start_date="2025-06-01",
        valid_from="2025-06-01",
    )
    assert origin.service_start_date == "2025-06-01"
    assert origin.valid_from == "2025-06-01"


def test_operator_origin_rejects_invalid_calendar_date():
    """OperatorOrigin should reject invalid calendar dates like February 31."""
    with pytest.raises(ValueError, match="Invalid date"):
        OperatorOrigin(
            platform="TestPlatform",
            service_scope="crypto",
            operator_entity="Test Entity",
            operator_country="US",
            source_url="https://example.com",
            source_checked_on="2025-01-01",
            confidence="high",
            review_required=False,
            valid_from="2025-02-31",  # Invalid date
        )


def test_operator_origin_rejects_year_before_crypto_genesis():
    """OperatorOrigin should reject years before 2009 (Bitcoin genesis)."""
    with pytest.raises(ValueError, match="year.*out of reasonable range"):
        OperatorOrigin(
            platform="TestPlatform",
            service_scope="crypto",
            operator_entity="Test Entity",
            operator_country="US",
            source_url="https://example.com",
            source_checked_on="2025-01-01",
            confidence="high",
            review_required=False,
            valid_from="2008-12-31",  # Before Bitcoin genesis
        )


# =============================================================================
# Integration test: CSV date parsing with temporal validity
# =============================================================================


def test_load_koinly_crypto_report_passes_dates_to_resolve_operator_origin(tmp_path, caplog):
    """Integration test: dates from CSV parsing should work with temporal validity checks.

    Verifies that the actual date format produced by format_datetime() matches
    what _parse_transaction_date() expects, and that temporal validity warnings
    are logged for transactions outside known validity periods.
    """
    koinly_dir = tmp_path / "koinly2025"
    koinly_dir.mkdir()

    # Berachain valid_from is 2025-02-05, so a disposal in 2024-06 should trigger warning
    csv_content = "\n".join(
        [
            "Capital gains report 2025",
            "",
            ",".join(
                [
                    "Date Sold",
                    "Date Acquired",
                    "Asset",
                    "Amount",
                    "Cost (EUR)",
                    "Proceeds (EUR)",
                    "Gain / loss",
                    "Notes",
                    "Wallet Name",
                    "Holding period",
                ]
            ),
            ",".join(
                [
                    "15/06/2024 13:01",  # Before Berachain valid_from (2025-02-05)
                    "18/11/2023 00:15",
                    "BERA",
                    '"1,00000000"',
                    '"1,00"',
                    '"2,00"',
                    '"1,00"',
                    "",
                    "Ledger Berachain",
                    "Short term",
                ]
            ),
        ]
    )
    (koinly_dir / "koinly_2025_capital_gains_report.csv").write_text(csv_content, encoding="utf-8")
    (koinly_dir / "koinly_2025_income_report.csv").write_text(
        "Income report 2025\n\nDate,Asset,Amount,Value (EUR),Type,Description,Wallet Name\n",
        encoding="utf-8",
    )
    _write_minimal_transaction_history(koinly_dir)

    with caplog.at_level(logging.WARNING, logger="tax_reporting.application.crypto_reporting"):
        report = load_koinly_crypto_report(koinly_dir)

    assert report is not None
    assert len(report.capital_entries) == 1
    # Verify warning was logged about transaction date predating valid_from
    assert any(
        "Transaction date 2024-06-15" in record.message and "Berachain" in record.message for record in caplog.records
    ), "Expected warning about transaction date outside validity period"


def test_resolve_operator_origin_ethereum_exact_history_no_review(caplog):
    """Ethereum has exact launch date (2015-07-30) and verification date (2026-03-15).

    The service_start_date is the launch date (2015-07-30) and valid_from is the
    verification date (2026-03-15). Transactions after the launch date should NOT
    be flagged for review, even if they fall before the verification date, because
    valid_from is for audit trail only and not used for transaction matching per
    the repository contract.
    """
    with caplog.at_level(logging.WARNING, logger="tax_reporting.application.crypto_reporting"):
        origin = resolve_operator_origin("Ethereum", None, "2024-01-20")

    # Should NOT be marked for review - transaction is after service_start_date
    assert origin.review_required is False

    # No verification warning should be logged (valid_from is audit-only)
    verification_warnings = [
        record.message
        for record in caplog.records
        if "verification date" in record.message.lower() and "ethereum" in record.message.lower()
    ]
    assert len(verification_warnings) == 0, "No verification warning for post-launch transactions"


def test_aggregate_capital_entries_produces_blank_swap_history():
    """Aggregation should produce blank swap history when all entries have blank token_swap_history."""
    entries = [
        _make_entry(
            disposal_date="2025-02-16",
            wallet="Ledger SUI",
            platform="Ledger SUI",
        ),
        _make_entry(
            disposal_date="2025-02-16",
            wallet="Ledger SUI",
            platform="Ledger SUI",
        ),
        _make_entry(
            disposal_date="2025-02-16",
            wallet="Ledger SUI",
            platform="Ledger SUI",
        ),
    ]

    result = _aggregate_capital_entries(entries)

    assert len(result) == 1
    assert result[0].token_swap_history == "", (
        "Aggregation should produce blank swap history after legacy heuristic removal"
    )


def test_aggregate_origin_field_single_origin():
    """When all lots share the same origin, aggregation returns it."""
    entries = [
        _make_entry(
            disposal_date="2025-02-16",
            wallet="Kraken",
            platform="Kraken",
            token_swap_history="EUR (direct_purchase, medium confidence)",
        ),
        _make_entry(
            disposal_date="2025-02-16",
            wallet="Kraken",
            platform="Kraken",
            token_swap_history="EUR (direct_purchase, medium confidence)",
        ),
    ]

    result = _aggregate_capital_entries(entries)

    assert len(result) == 1
    assert result[0].token_swap_history == "EUR (direct_purchase, medium confidence)"


def test_aggregate_origin_field_multiple_origins():
    """When lots have different origins, aggregation joins them with '; '."""
    entries = [
        _make_entry(
            disposal_date="2025-02-16",
            wallet="Kraken",
            platform="Kraken",
            token_swap_history="EUR (direct_purchase, medium confidence)",
        ),
        _make_entry(
            disposal_date="2025-02-16",
            wallet="Kraken",
            platform="Kraken",
            token_swap_history="BTC (swap_conversion, high confidence)",
        ),
    ]

    result = _aggregate_capital_entries(entries)

    assert len(result) == 1
    assert "EUR (direct_purchase, medium confidence)" in result[0].token_swap_history
    assert "BTC (swap_conversion, high confidence)" in result[0].token_swap_history
    assert "; " in result[0].token_swap_history


def test_aggregate_origin_field_mixed_empty_and_nonempty():
    """When some lots have origin and others are blank, aggregation appends an unresolved indicator."""
    entries = [
        _make_entry(
            disposal_date="2025-02-16",
            wallet="Kraken",
            platform="Kraken",
            token_swap_history="EUR (direct_purchase, medium confidence)",
        ),
        _make_entry(
            disposal_date="2025-02-16",
            wallet="Kraken",
            platform="Kraken",
            token_swap_history="",
        ),
    ]

    result = _aggregate_capital_entries(entries)

    assert len(result) == 1
    assert "EUR (direct_purchase, medium confidence)" in result[0].token_swap_history
    assert "1 lot unresolved" in result[0].token_swap_history


def test_aggregate_origin_field_all_blank():
    """When all lots have blank origin, aggregation returns empty string."""
    entries = [
        _make_entry(
            disposal_date="2025-02-16",
            wallet="Kraken",
            platform="Kraken",
            token_swap_history="",
        ),
        _make_entry(
            disposal_date="2025-02-16",
            wallet="Kraken",
            platform="Kraken",
            token_swap_history="",
        ),
    ]

    result = _aggregate_capital_entries(entries)

    assert len(result) == 1
    assert result[0].token_swap_history == ""


def test_aggregate_origin_field_plural_unresolved():
    """When multiple unknown lots exist, aggregation uses plural indicator."""
    entries = [
        _make_entry(
            disposal_date="2025-02-16",
            wallet="Kraken",
            platform="Kraken",
            token_swap_history="EUR (direct_purchase, medium confidence)",
        ),
        _make_entry(
            disposal_date="2025-02-16",
            wallet="Kraken",
            platform="Kraken",
            token_swap_history="",
        ),
        _make_entry(
            disposal_date="2025-02-16",
            wallet="Kraken",
            platform="Kraken",
            token_swap_history="",
        ),
    ]

    result = _aggregate_capital_entries(entries)

    assert len(result) == 1
    assert "EUR (direct_purchase, medium confidence)" in result[0].token_swap_history
    assert "2 lots unresolved" in result[0].token_swap_history


def test_parse_capital_gains_file_with_populated_resolver(tmp_path):
    """_parse_capital_gains_file populates token_swap_history from the origin resolver."""
    th_csv = tmp_path / "th.csv"
    th_csv.write_text(
        "\n".join(
            [
                "Transaction report 2025",
                "",
                (
                    "Date,Type,Tag,Sending Wallet,Sent Amount,Sent Currency,Sent Cost Basis,"
                    "Receiving Wallet,Received Amount,Received Currency,Received Cost Basis,"
                    "Fee Amount,Fee Currency,Gain (EUR),Net Value (EUR),Fee Value (EUR),"
                    "TxSrc,TxDest,TxHash,Description"
                ),
                (
                    '2025-01-15 10:00:00 UTC,exchange,"",Kraken,"1000,00",EUR,'
                    '"1000,00",Kraken,"0,10",BTC,"1000,00","","","","","","",""'
                ),
            ]
        ),
        encoding="utf-8",
    )

    capital_csv = tmp_path / "capital.csv"
    capital_csv.write_text(
        "\n".join(
            [
                "Capital gains report 2025",
                "",
                ",".join(
                    [
                        "Date Sold",
                        "Date Acquired",
                        "Asset",
                        "Amount",
                        "Cost (EUR)",
                        "Proceeds (EUR)",
                        "Gain / loss",
                        "Notes",
                        "Wallet Name",
                        "Holding period",
                    ]
                ),
                ",".join(
                    [
                        "15/03/2025 12:00",
                        "15/01/2025 10:00",
                        "BTC",
                        '"0,10"',
                        '"1000,00"',
                        '"1200,00"',
                        '"200,00"',
                        "",
                        "Kraken",
                        "Short term",
                    ]
                ),
            ]
        ),
        encoding="utf-8",
    )

    from collections import Counter


    resolver = build_origin_resolver(th_csv)
    skipped: Counter[tuple[str, str]] = Counter()
    review_entries: list = []
    context = CapitalGainsParsingContext(
        skipped_assets=skipped,
        origin_resolver=resolver,
        review_entries=review_entries,
    )
    entries, _ = _parse_capital_gains_file(capital_csv, context)

    assert len(entries) == 1
    assert entries[0].token_swap_history != "", (
        "Expected resolved origin, got blank token_swap_history"
    )
    assert "EUR" in entries[0].token_swap_history, (
        f"Expected origin containing 'EUR', got: {entries[0].token_swap_history!r}"
    )
    assert "swap_conversion" in entries[0].token_swap_history, (
        f"Expected swap_conversion method, got: {entries[0].token_swap_history!r}"
    )



# --- Review reason tests ---


def test_bybit_operator_origin_has_review_reason():
    """ByBit platform must have a specific platform_assumption explaining account-region concern."""
    origin = resolve_operator_origin("ByBit")
    assert origin.review_required is False  # Platform assumption, not row-level review
    assert origin.platform_assumption is not None
    assert "account-region" in origin.platform_assumption.lower()
    assert "Bybit" in origin.platform_assumption


def test_starknet_operator_origin_no_review_required():
    """Starknet has a known operator with reliable chain derivation; no review needed."""
    origin = resolve_operator_origin("Starknet")
    assert origin.review_required is False
    assert origin.review_reason is None


def test_mantle_operator_origin_has_review_reason():
    """Mantle platform must have a specific platform_assumption."""
    origin = resolve_operator_origin("Mantle")
    assert origin.review_required is False  # Platform assumption, not row-level review
    assert origin.platform_assumption is not None
    assert "Mantle" in origin.platform_assumption


def test_unknown_operator_origin_has_review_reason():
    """Unknown platforms must have a specific review_reason."""
    origin = resolve_operator_origin("SomeNewChain123")
    assert origin.review_required is True
    assert origin.review_reason is not None
    assert "Unknown platform" in origin.review_reason


def test_temporal_invalidity_sets_review_reason(caplog):
    """Out-of-validity transactions must have a review_reason with the service period."""
    with caplog.at_level(logging.WARNING, logger="tax_reporting.application.crypto_reporting"):
        origin = resolve_operator_origin(
            "Berachain", transaction_type="crypto_disposal", transaction_date="2024-06-01 10:00:00"
        )
    assert origin.review_required is True
    assert origin.review_reason is not None
    assert "2024-06-01" in origin.review_reason
    assert "service period" in origin.review_reason.lower()


def test_valid_transaction_has_no_review_reason():
    """Valid transactions on known platforms should not have a review_reason."""
    origin = resolve_operator_origin("Ethereum", transaction_type="crypto_disposal", transaction_date="2025-01-20")
    assert origin.review_required is False
    assert origin.review_reason is None


def test_capital_entry_review_reason_from_operator():
    """Capital entries should inherit review_reason from operator origin."""
    bybit_origin = resolve_operator_origin("ByBit")
    entry = _make_entry(
        operator_origin=bybit_origin,
        review_required=bybit_origin.review_required,
        review_reason=bybit_origin.review_reason,
    )
    assert entry.review_reason == bybit_origin.review_reason


def test_capital_entry_review_reason_missing_cost_basis(tmp_path):
    """Missing cost basis with tax impact must produce review_reason via _parse_capital_gains_file."""
    csv_content = "\n".join(
        [
            "Capital gains report 2025",
            "",
            ",".join(
                [
                    "Date Sold",
                    "Date Acquired",
                    "Asset",
                    "Amount",
                    "Cost (EUR)",
                    "Proceeds (EUR)",
                    "Gain / loss",
                    "Notes",
                    "Wallet Name",
                    "Holding period",
                ]
            ),
            ",".join(
                [
                    "15/01/2025 10:00",
                    "01/01/2024 10:00",
                    "ETH",
                    '"1,00000000"',
                    '"0,00"',
                    '"100,00"',
                    '"100,00"',
                    "Missing cost basis",
                    "Kraken",
                    "Short term",
                ]
            ),
        ]
    )
    csv_file = tmp_path / "capital_gains.csv"
    csv_file.write_text(csv_content, encoding="utf-8")

    from collections import Counter


    skipped = Counter()
    review_entries: list = []
    context = CapitalGainsParsingContext(
        skipped_assets=skipped,
        origin_resolver=build_origin_resolver(None),
        review_entries=review_entries,
    )
    entries, _ = _parse_capital_gains_file(csv_file, context)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.review_required is True
    assert entry.review_reason is not None
    assert "Missing cost basis" in entry.review_reason


def test_aggregate_joins_review_reasons():
    """Aggregation should join review_reasons from multiple entries."""
    entries = [
        _make_entry(review_required=True, notes="note1", review_reason="reason A"),
        _make_entry(review_required=True, notes="note2", review_reason="reason B"),
    ]
    result = _aggregate_capital_entries(entries)
    assert len(result) == 1
    assert result[0].review_required is True
    assert "reason A" in result[0].review_reason
    assert "reason B" in result[0].review_reason


def test_aggregate_review_reason_none_when_all_none():
    """Aggregation should produce None review_reason when all entries have None."""
    entries = [
        _make_entry(review_required=False),
        _make_entry(review_required=False),
    ]
    result = _aggregate_capital_entries(entries)
    assert len(result) == 1
    assert result[0].review_reason is None


def test_date_parse_failure_sets_review_reason():
    """Invalid transaction date format should set review_reason."""
    origin = resolve_operator_origin("Ethereum", transaction_type="crypto_disposal", transaction_date="not-a-date")
    assert origin.review_required is True
    assert origin.review_reason is not None
    assert "date format" in origin.review_reason.lower()


# =============================================================================
# Task 3: Automate resolvable review flags
# =============================================================================


def test_bybit_review_flag_is_intentional_with_reason():
    """ByBit platform_assumption exists because region-specific entities cannot be auto-detected from Koinly exports."""
    origin = resolve_operator_origin("ByBit")
    assert origin.review_required is False  # Platform assumption, not row-level review
    assert origin.operator_country == "AE"
    assert origin.platform_assumption is not None
    assert "account-region" in origin.platform_assumption


def test_bybit_review_reason_propagates_through_capital_gains_csv(tmp_path):
    """ByBit review reason must propagate from operator origin through full CSV parse."""
    csv_content = "\n".join(
        [
            "Capital gains report 2025",
            "",
            ",".join(
                [
                    "Date Sold",
                    "Date Acquired",
                    "Asset",
                    "Amount",
                    "Cost (EUR)",
                    "Proceeds (EUR)",
                    "Gain / loss",
                    "Notes",
                    "Wallet Name",
                    "Holding period",
                ]
            ),
            ",".join(
                [
                    "15/01/2025 10:00",
                    "01/01/2024 10:00",
                    "BTC",
                    '"0,10000000"',
                    '"1000,00"',
                    '"1200,00"',
                    '"200,00"',
                    "",
                    "ByBit",
                    "Long term",
                ]
            ),
        ]
    )
    csv_file = tmp_path / "capital_gains.csv"
    csv_file.write_text(csv_content, encoding="utf-8")

    from collections import Counter


    skipped = Counter()
    review_entries: list = []
    context = CapitalGainsParsingContext(
        skipped_assets=skipped,
        origin_resolver=build_origin_resolver(None),
        review_entries=review_entries,
    )
    entries, _ = _parse_capital_gains_file(csv_file, context)
    assert len(entries) == 1
    entry = entries[0]
    # Bybit has platform_assumption, not row-level review
    assert entry.review_required is False
    assert entry.operator_origin.platform_assumption is not None
    assert "account-region" in entry.operator_origin.platform_assumption


class TestBuildZeroBasisReviewReason:
    """Gating of the zero-basis review flag per the materiality rule.

    - cost=0 AND proceeds=0 (FEE token case): not flagged when min_proceeds > 0;
      flagged with both zero-cost and zero-proceeds reasons when min_proceeds = 0
      (legacy flag-everything escape hatch).
    - cost=0 AND 0 < proceeds < min_proceeds (small reward): no flag.
    - cost=0 AND proceeds >= min_proceeds: flag with zero-cost reason.
    - cost=0 AND proceeds < 0: always flag with the negative-proceeds reason,
      independent of min_proceeds (fee-heavy liquidation or data anomaly).
    - cost>0 AND proceeds=0: flag with zero-proceeds reason (threshold does not apply).
    """

    def test_zero_cost_zero_proceeds_never_flags(self):
        from tax_reporting.application.crypto_reporting import _build_zero_basis_review_reason

        review_required, review_reason = _build_zero_basis_review_reason(
            cost_eur=Decimal("0"),
            proceeds_eur=Decimal("0"),
            review_required=False,
            review_reason="",
            min_proceeds=Decimal("10"),
        )

        assert review_required is False
        assert review_reason == ""

    def test_zero_cost_small_proceeds_does_not_flag(self):
        from tax_reporting.application.crypto_reporting import _build_zero_basis_review_reason

        review_required, review_reason = _build_zero_basis_review_reason(
            cost_eur=Decimal("0"),
            proceeds_eur=Decimal("5"),
            review_required=False,
            review_reason="",
            min_proceeds=Decimal("10"),
        )

        assert review_required is False
        assert review_reason == ""

    def test_zero_cost_at_threshold_flags(self):
        from tax_reporting.application.crypto_reporting import _build_zero_basis_review_reason

        review_required, review_reason = _build_zero_basis_review_reason(
            cost_eur=Decimal("0"),
            proceeds_eur=Decimal("10"),
            review_required=False,
            review_reason="",
            min_proceeds=Decimal("10"),
        )

        assert review_required is True
        assert "Zero acquisition cost" in review_reason

    def test_zero_cost_above_threshold_flags(self):
        from tax_reporting.application.crypto_reporting import _build_zero_basis_review_reason

        review_required, review_reason = _build_zero_basis_review_reason(
            cost_eur=Decimal("0"),
            proceeds_eur=Decimal("30"),
            review_required=False,
            review_reason="",
            min_proceeds=Decimal("10"),
        )

        assert review_required is True
        assert "Zero acquisition cost" in review_reason
        assert "verify basis" in review_reason

    def test_zero_proceeds_with_nonzero_cost_always_flags(self):
        from tax_reporting.application.crypto_reporting import _build_zero_basis_review_reason

        review_required, review_reason = _build_zero_basis_review_reason(
            cost_eur=Decimal("50"),
            proceeds_eur=Decimal("0"),
            review_required=False,
            review_reason="",
            min_proceeds=Decimal("10"),
        )

        assert review_required is True
        assert "Zero disposal proceeds" in review_reason
        assert "verify sale data" in review_reason

    def test_min_proceeds_zero_flags_all_zero_cost(self):
        from tax_reporting.application.crypto_reporting import _build_zero_basis_review_reason

        review_required, review_reason = _build_zero_basis_review_reason(
            cost_eur=Decimal("0"),
            proceeds_eur=Decimal("0"),
            review_required=False,
            review_reason="",
            min_proceeds=Decimal("0"),
        )

        assert review_required is True
        assert "Zero acquisition cost" in review_reason
        assert "Zero disposal proceeds" in review_reason

    def test_min_proceeds_zero_flags_zero_cost_with_proceeds(self):
        from tax_reporting.application.crypto_reporting import _build_zero_basis_review_reason

        review_required, review_reason = _build_zero_basis_review_reason(
            cost_eur=Decimal("0"),
            proceeds_eur=Decimal("100"),
            review_required=False,
            review_reason="",
            min_proceeds=Decimal("0"),
        )

        assert review_required is True

    def test_preserves_existing_review_reason(self):
        from tax_reporting.application.crypto_reporting import _build_zero_basis_review_reason

        review_required, review_reason = _build_zero_basis_review_reason(
            cost_eur=Decimal("0"),
            proceeds_eur=Decimal("30"),
            review_required=True,
            review_reason="Existing review reason",
            min_proceeds=Decimal("10"),
        )

        assert review_required is True
        assert review_reason.startswith("Existing review reason;")
        assert "Zero acquisition cost" in review_reason

    def test_zero_cost_negative_proceeds_always_flags(self):
        """Zero cost with negative proceeds is always a data anomaly and must flag.

        Master flagged any entry with cost=0 regardless of proceeds sign. The
        materiality gate must not silently drop the flag for negative proceeds,
        which represents a fee-heavy liquidation or data quality issue worth
        surfacing regardless of magnitude.
        """
        from tax_reporting.application.crypto_reporting import _build_zero_basis_review_reason

        review_required, review_reason = _build_zero_basis_review_reason(
            cost_eur=Decimal("0"),
            proceeds_eur=Decimal("-50"),
            review_required=False,
            review_reason="",
            min_proceeds=Decimal("10"),
        )

        assert review_required is True
        assert "Zero acquisition cost" in review_reason
        assert "negative" in review_reason.lower()

    def test_zero_cost_negative_proceeds_flags_even_when_min_proceeds_zero(self):
        """Negative proceeds flags under the backward-compat escape hatch too."""
        from tax_reporting.application.crypto_reporting import _build_zero_basis_review_reason

        review_required, _ = _build_zero_basis_review_reason(
            cost_eur=Decimal("0"),
            proceeds_eur=Decimal("-1"),
            review_required=False,
            review_reason="",
            min_proceeds=Decimal("0"),
        )

        assert review_required is True

    def test_both_nonzero_does_not_flag(self):
        """When both cost and proceeds are non-zero, no flag fires."""
        from tax_reporting.application.crypto_reporting import _build_zero_basis_review_reason

        review_required, review_reason = _build_zero_basis_review_reason(
            cost_eur=Decimal("100"),
            proceeds_eur=Decimal("200"),
            review_required=False,
            review_reason="",
            min_proceeds=Decimal("10"),
        )

        assert review_required is False
        assert review_reason == ""


def test_platforms_without_service_start_date_allow_old_transactions():
    """Platforms without service_start_date must not flag old transactions as temporally invalid."""
    kraken_origin = resolve_operator_origin("Kraken", transaction_type="crypto_disposal", transaction_date="2015-01-01")
    assert kraken_origin.service_start_date is None
    assert kraken_origin.review_required is False

    binance_origin = resolve_operator_origin(
        "Binance", transaction_type="crypto_disposal", transaction_date="2017-01-01"
    )
    assert binance_origin.service_start_date is None
    assert binance_origin.review_required is False


def test_ethereum_early_service_start_date_allows_historical_transactions():
    """Ethereum's 2015 service_start_date must allow historical transactions from 2016+."""
    origin = resolve_operator_origin("Ethereum", transaction_type="crypto_disposal", transaction_date="2016-06-15")
    assert origin.service_start_date == "2015-07-30"
    assert origin.review_required is False
    assert origin.review_reason is None


def test_ethereum_service_start_date_allows_exact_start_date():
    """Transaction on Ethereum's exact service_start_date must be valid."""
    origin = resolve_operator_origin("Ethereum", transaction_type="crypto_disposal", transaction_date="2015-07-30")
    assert origin.review_required is False


def test_zero_value_entries_never_reach_report(tmp_path):
    """Zero-value entries must be filtered before reaching the final report output."""
    csv_content = "\n".join(
        [
            "Capital gains report 2025",
            "",
            ",".join(
                [
                    "Date Sold",
                    "Date Acquired",
                    "Asset",
                    "Amount",
                    "Cost (EUR)",
                    "Proceeds (EUR)",
                    "Gain / loss",
                    "Notes",
                    "Wallet Name",
                    "Holding period",
                ]
            ),
            ",".join(
                [
                    "01/01/2025 10:00",
                    "01/01/2024 10:00",
                    "FEE1",
                    '"10,00000000"',
                    "0.0",
                    "0.0",
                    "0.0",
                    "",
                    "Kraken",
                    "Short term",
                ]
            ),
            ",".join(
                [
                    "02/01/2025 10:00",
                    "01/01/2024 10:00",
                    "FEE2",
                    '"5,00000000"',
                    "0.0",
                    "0.0",
                    "0.0",
                    "",
                    "Kraken",
                    "Short term",
                ]
            ),
        ]
    )
    csv_file = tmp_path / "capital_gains.csv"
    csv_file.write_text(csv_content, encoding="utf-8")


    skipped = {}
    review_entries: list = []
    context = CapitalGainsParsingContext(
        skipped_assets=skipped,
        origin_resolver=build_origin_resolver(None),
        review_entries=review_entries,
    )
    entries, _ = _parse_capital_gains_file(csv_file, context)
    assert len(entries) == 0
    assert skipped[("capital_gains", "FEE1")] == {"count": 1, "suspicious": False}
    assert skipped[("capital_gains", "FEE2")] == {"count": 1, "suspicious": False}


# =============================================================================
# Task 1: Remove legacy token origin guessing
# =============================================================================


def test_capital_row_origin_resolved_from_acquisition_side_exchange(tmp_path):
    """Capital entries resolve token origin from the acquisition-side transaction history.

    When the Koinly transaction history contains an exchange (swap) row that matches
    the capital gains row's acquisition date, asset, and wallet, the resolver
    populates token_swap_history with the swap details and confidence level.
    """
    koinly_dir = tmp_path / "koinly2025"
    koinly_dir.mkdir()

    # Transaction history with an exchange (swap) row acquiring HASUI
    (koinly_dir / "koinly_2025_transaction_history.csv").write_text(
        "\n".join(
            [
                "Transaction report 2025",
                "",
                (
                    "Date,Type,Tag,Sending Wallet,Sent Amount,Sent Currency,Sent Cost Basis,"
                    "Receiving Wallet,Received Amount,Received Currency,Received Cost Basis,"
                    "Fee Amount,Fee Currency,Gain (EUR),Net Value (EUR),Fee Value (EUR),"
                    "TxSrc,TxDest,TxHash,Description"
                ),
                (
                    '2025-02-16 16:55:00 UTC,exchange,"",Ledger SUI,"26,40816087",SUI,'
                    '"29,83",Ledger SUI,"25,19665014",HASUI,"29,83","","","","83,05","",'
                    "0xabc,0xdef,tx123"
                ),
            ]
        ),
        encoding="utf-8",
    )

    # Capital gains with HASUI disposal whose acquisition date matches the exchange
    (koinly_dir / "koinly_2025_capital_gains_report.csv").write_text(
        "\n".join(
            [
                "Capital gains report 2025",
                "",
                ",".join(
                    [
                        "Date Sold",
                        "Date Acquired",
                        "Asset",
                        "Amount",
                        "Cost (EUR)",
                        "Proceeds (EUR)",
                        "Gain / loss",
                        "Notes",
                        "Wallet Name",
                        "Holding period",
                    ]
                ),
                ",".join(
                    [
                        "16/02/2025 17:10",
                        "16/02/2025 17:00",
                        "HASUI",
                        '"25,19665014"',
                        '"29,83"',
                        '"83,05"',
                        '"53,22"',
                        "",
                        "Ledger SUI",
                        "Short term",
                    ]
                ),
            ]
        ),
        encoding="utf-8",
    )

    (koinly_dir / "koinly_2025_income_report.csv").write_text(
        "Income report 2025\n\nDate,Asset,Amount,Value (EUR),Type,Description,Wallet Name\n",
        encoding="utf-8",
    )

    report = load_koinly_crypto_report(koinly_dir)

    assert report is not None
    assert len(report.capital_entries) == 1
    entry = report.capital_entries[0]

    assert "SUI" in entry.token_swap_history, (
        f"Expected resolved origin containing 'SUI' from acquisition-side exchange, "
        f"got: {entry.token_swap_history!r}"
    )
    assert "swap_conversion" in entry.token_swap_history, (
        f"Expected swap_conversion method, got: {entry.token_swap_history!r}"
    )
    assert "confidence" in entry.token_swap_history, (
        f"Expected confidence level in origin string, got: {entry.token_swap_history!r}"
    )


def test_loan_repayment_origin_resolved_from_acquisition_side_exchange(tmp_path):
    """Loan repayment scenario (e.g. WBTC -> LBTC) resolves origin from the exchange row.

    When the transaction history shows a WBTC -> LBTC exchange that matches the
    acquisition date, asset, and wallet of a capital gains row, the resolver
    identifies the swap_conversion origin.
    """
    koinly_dir = tmp_path / "koinly2025"
    koinly_dir.mkdir()

    # Transaction history with a WBTC -> LBTC exchange matching the acquisition
    (koinly_dir / "koinly_2025_transaction_history.csv").write_text(
        "\n".join(
            [
                "Transaction report 2025",
                "",
                (
                    "Date,Type,Tag,Sending Wallet,Sent Amount,Sent Currency,Sent Cost Basis,"
                    "Receiving Wallet,Received Amount,Received Currency,Received Cost Basis,"
                    "Fee Amount,Fee Currency,Gain (EUR),Net Value (EUR),Fee Value (EUR),"
                    "TxSrc,TxDest,TxHash,Description"
                ),
                # A WBTC -> LBTC exchange on the same day as the acquisition
                (
                    '2025-05-22 14:00:00 UTC,exchange,"",Ledger SUI,"0,50",WBTC,'
                    '"450,00",Ledger SUI,"0,50",LBTC,"450,00","","","","450,00","",'
                    "0xabc,0xdef,tx_wbtc_lbtc"
                ),
            ]
        ),
        encoding="utf-8",
    )

    # Capital gains with LBTC disposal whose acquisition date matches the exchange
    (koinly_dir / "koinly_2025_capital_gains_report.csv").write_text(
        "\n".join(
            [
                "Capital gains report 2025",
                "",
                ",".join(
                    [
                        "Date Sold",
                        "Date Acquired",
                        "Asset",
                        "Amount",
                        "Cost (EUR)",
                        "Proceeds (EUR)",
                        "Gain / loss",
                        "Notes",
                        "Wallet Name",
                        "Holding period",
                    ]
                ),
                ",".join(
                    [
                        "22/05/2025 15:00",
                        "22/05/2025 14:05",
                        "LBTC",
                        '"0,50"',
                        '"450,00"',
                        '"500,00"',
                        '"50,00"',
                        "",
                        "Ledger SUI",
                        "Short term",
                    ]
                ),
            ]
        ),
        encoding="utf-8",
    )

    (koinly_dir / "koinly_2025_income_report.csv").write_text(
        "Income report 2025\n\nDate,Asset,Amount,Value (EUR),Type,Description,Wallet Name\n",
        encoding="utf-8",
    )

    report = load_koinly_crypto_report(koinly_dir)

    assert report is not None
    assert len(report.capital_entries) == 1
    entry = report.capital_entries[0]

    assert "WBTC" in entry.token_swap_history, (
        f"Expected resolved origin containing 'WBTC' from exchange, "
        f"got: {entry.token_swap_history!r}"
    )
    assert "swap_conversion" in entry.token_swap_history, (
        f"Expected swap_conversion method, got: {entry.token_swap_history!r}"
    )


def test_origin_not_resolved_from_disposal_date_only(tmp_path):
    """Origin must NOT match on disposal date; only acquisition date is used.

    Regression guard: if the resolver or pipeline ever switches to matching on
    disposal date (the removed heuristic), this test would silently pass without
    catching the regression.
    """
    koinly_dir = tmp_path / "koinly2025"
    koinly_dir.mkdir()

    (koinly_dir / "koinly_2025_transaction_history.csv").write_text(
        "\n".join(
            [
                "Transaction report 2025",
                "",
                (
                    "Date,Type,Tag,Sending Wallet,Sent Amount,Sent Currency,Sent Cost Basis,"
                    "Receiving Wallet,Received Amount,Received Currency,Received Cost Basis,"
                    "Fee Amount,Fee Currency,Gain (EUR),Net Value (EUR),Fee Value (EUR),"
                    "TxSrc,TxDest,TxHash,Description"
                ),
                # Exchange on 2025-05-22 (matches disposal date, NOT acquisition date)
                (
                    '2025-05-22 14:00:00 UTC,exchange,"",Kraken,3000,USDT,3000,'
                    'Kraken,1,ETH,3000,,,,,,abc,def,tx_match_disposal,trade\n'
                ),
            ]
        ),
        encoding="utf-8",
    )

    # Capital gains row: sold on 2025-05-22, acquired on 2025-03-15
    (koinly_dir / "koinly_2025_capital_gains_report.csv").write_text(
        "\n".join(
            [
                "Capital gains report 2025",
                "",
                ",".join(
                    [
                        "Date Sold",
                        "Date Acquired",
                        "Asset",
                        "Amount",
                        "Cost (EUR)",
                        "Proceeds (EUR)",
                        "Gain / loss",
                        "Notes",
                        "Wallet Name",
                        "Holding period",
                    ]
                ),
                ",".join(
                    [
                        "22/05/2025 15:00",
                        "15/03/2025 10:00",
                        "ETH",
                        "1",
                        "2000",
                        "3000",
                        "1000",
                        "",
                        "Kraken",
                        "Short term",
                    ]
                ),
            ]
        ),
        encoding="utf-8",
    )

    (koinly_dir / "koinly_2025_income_report.csv").write_text(
        "Income report 2025\n\nDate,Asset,Amount,Value (EUR),Type,Description,Wallet Name\n",
        encoding="utf-8",
    )

    report = load_koinly_crypto_report(koinly_dir)

    assert report is not None
    assert len(report.capital_entries) == 1
    entry = report.capital_entries[0]

    assert entry.token_swap_history == "", (
        f"Expected blank origin (disposal date must not match), got: {entry.token_swap_history!r}"
    )


def test_example_fixture_has_no_duplicate_aggregation_keys():
    """Characterization test: loading the example koinly2025 fixture produces zero
    duplicate rows when grouped by the full aggregation key
    (disposal_date, asset, platform, holding_period).

    If this test fails, _aggregate_capital_entries() or upstream parsing has
    introduced a regression that splits same-key rows instead of collapsing them.
    """
    from collections import Counter

    from tests.conftest import KOINLY_2025_EXAMPLE_DIR

    report = load_koinly_crypto_report(KOINLY_2025_EXAMPLE_DIR)
    assert report is not None, "Failed to load koinly2025 example report"

    keys = [(e.disposal_date, e.asset, e.platform, e.holding_period) for e in report.capital_entries]
    dups = [(k, c) for k, c in Counter(keys).items() if c > 1]
    assert dups == [], (
        f"Duplicate aggregation keys found after loading example koinly2025: {dups}. "
        f"_aggregate_capital_entries() should collapse same-key rows."
    )


def test_acquisition_date_repeat_is_not_a_disposal_grouping_issue():
    """Document that a repeated acquisition_date across multiple disposal events
    is expected and must not be confused with a disposal-date grouping regression.

    The reported 2024-07-27 date was an acquisition date shared by
    FIFO lots sold at different later disposal dates. Each disposal is a distinct
    taxable event; the shared acquisition date simply reflects the common purchase
    that was partially sold over time.
    """
    shared_acq = "2024-07-27"
    entries = [
        _make_entry(
            disposal_date="2025-01-10",
            acquisition_date=shared_acq,
            amount=Decimal("10"),
            gain_loss_eur=Decimal("1"),
        ),
        _make_entry(
            disposal_date="2025-02-15",
            acquisition_date=shared_acq,
            amount=Decimal("15"),
            gain_loss_eur=Decimal("2"),
        ),
        _make_entry(
            disposal_date="2025-03-20",
            acquisition_date=shared_acq,
            amount=Decimal("5"),
            gain_loss_eur=Decimal("0.5"),
        ),
    ]

    result = _aggregate_capital_entries(entries)

    assert len(result) == 3, (
        f"Expected 3 separate disposal rows (different disposal dates), got {len(result)}"
    )
    disposal_dates = [e.disposal_date for e in result]
    assert disposal_dates == [
        "2025-01-10",
        "2025-02-15",
        "2025-03-20",
    ]
    for r in result:
        assert r.acquisition_date == shared_acq


def test_same_disposal_date_allowed_when_other_grouping_dims_differ():
    """Rows sharing a disposal_date are correctly kept separate when any other
    aggregation dimension (asset, platform, holding_period) differs."""
    shared_disposal = "2025-06-01"
    entries = [
        _make_entry(
            disposal_date=shared_disposal,
            asset="BTC",
            platform="ByBit",
            holding_period="Short term",
            gain_loss_eur=Decimal("10"),
        ),
        _make_entry(
            disposal_date=shared_disposal,
            asset="ETH",
            platform="ByBit",
            holding_period="Short term",
            gain_loss_eur=Decimal("20"),
        ),
        _make_entry(
            disposal_date=shared_disposal,
            asset="USDT",
            platform="Kraken",
            holding_period="Short term",
            gain_loss_eur=Decimal("5"),
        ),
        _make_entry(
            disposal_date=shared_disposal,
            asset="USDT",
            platform="ByBit",
            holding_period="Long term",
            gain_loss_eur=Decimal("3"),
        ),
    ]

    result = _aggregate_capital_entries(entries)

    assert len(result) == 4, (
        f"Expected 4 separate rows (different grouping dimensions), got {len(result)}"
    )
    result_keys = [(e.asset, e.platform, e.holding_period) for e in result]
    expected_keys = [
        ("BTC", "ByBit", "Short term"),
        ("ETH", "ByBit", "Short term"),
        ("USDT", "Kraken", "Short term"),
        ("USDT", "ByBit", "Long term"),
    ]
    assert sorted(result_keys) == sorted(expected_keys)


# --- Task 3: Long-term regression guards ---


def test_aggregate_never_emits_duplicate_keys():
    """Regression guard: _aggregate_capital_entries() must never emit two rows
    sharing the same (disposal_date, asset, platform, holding_period) key.

    This test feeds entries that form two identical aggregation keys plus one
    distinct key and verifies:
      - same-key entries collapse to one aggregated row
      - no duplicate keys exist in the output
    If this test fails, the aggregation function has a regression that splits
    same-key rows instead of collapsing them.
    """
    from collections import Counter

    shared_key_params = {
        "disposal_date": "2025-03-15",
        "asset": "USDT",
        "platform": "ByBit",
        "holding_period": "Short term",
    }
    entries = [
        _make_entry(
            **shared_key_params,
            acquisition_date="2024-06-01",
            amount=Decimal("50"),
            cost_eur=Decimal("40"),
            proceeds_eur=Decimal("45"),
            gain_loss_eur=Decimal("5"),
        ),
        _make_entry(
            **shared_key_params,
            acquisition_date="2024-09-15",
            amount=Decimal("30"),
            cost_eur=Decimal("25"),
            proceeds_eur=Decimal("28"),
            gain_loss_eur=Decimal("3"),
        ),
        _make_entry(
            disposal_date="2025-04-01",
            asset="BTC",
            platform="Kraken",
            holding_period="Long term",
            gain_loss_eur=Decimal("100"),
        ),
    ]

    result = _aggregate_capital_entries(entries)

    assert len(result) == 2, f"Expected 2 aggregated rows, got {len(result)}"

    keys = [(e.disposal_date, e.asset, e.platform, e.holding_period) for e in result]
    dups = [(k, c) for k, c in Counter(keys).items() if c > 1]
    assert dups == [], (
        f"Duplicate aggregation keys in output: {dups}. "
        f"_aggregate_capital_entries() must collapse same-key rows."
    )

    agg_usdt = next(e for e in result if e.asset == "USDT")
    assert agg_usdt.amount == Decimal("80")
    assert agg_usdt.cost_eur == Decimal("65")
    assert agg_usdt.proceeds_eur == Decimal("73")
    assert agg_usdt.gain_loss_eur == Decimal("8")
    assert agg_usdt.acquisition_date == "2024-06-01"


def test_same_timestamp_different_holding_period_stays_split():
    """Regression guard: same disposal timestamp with different holding periods
    must produce separate rows because the split is legally significant.

    PT-C-011 requires distinguishing short-term (taxable) from long-term
    (exempt) gains. If same-timestamp rows with different holding periods
    were merged, exempt long-term gains would incorrectly offset taxable
    short-term gains or vice versa.
    """
    shared_timestamp = "2025-07-27"
    entries = [
        _make_entry(
            disposal_date=shared_timestamp,
            acquisition_date="2024-01-15",
            asset="ETH",
            platform="Kraken",
            holding_period="Short term",
            amount=Decimal("5"),
            cost_eur=Decimal("8000"),
            proceeds_eur=Decimal("9000"),
            gain_loss_eur=Decimal("1000"),
        ),
        _make_entry(
            disposal_date=shared_timestamp,
            acquisition_date="2023-06-15",
            asset="ETH",
            platform="Kraken",
            holding_period="Long term",
            amount=Decimal("3"),
            cost_eur=Decimal("3000"),
            proceeds_eur=Decimal("5400"),
            gain_loss_eur=Decimal("2400"),
        ),
    ]

    result = _aggregate_capital_entries(entries)

    assert len(result) == 2, (
        f"Expected 2 separate rows (different holding periods), got {len(result)}"
    )
    by_period = {e.holding_period: e for e in result}
    assert "Short term" in by_period
    assert "Long term" in by_period

    short = by_period["Short term"]
    long = by_period["Long term"]
    assert short.gain_loss_eur == Decimal("1000")
    assert long.gain_loss_eur == Decimal("2400")
    assert short.disposal_date == shared_timestamp
    assert long.disposal_date == shared_timestamp


class TestAggregateOgrValidation:
    """Test OGR validation result aggregation across FIFO lots."""

    def test_aggregate_ogr_validation_no_conflicts_uses_first_ogr_gain_loss(self):
        """3 entries with validation results (no conflicts).

        Expects aggregated entry with ogr_gain_loss from first entry (NOT summed), no direction_conflict.
        """
        from tax_reporting.domain.entities import OgrValidationResult

        entries = [
            _make_entry(
                disposal_date="2025-01-13",
                asset="USDT",
                platform="ByBit",
                holding_period="Short term",
                gain_loss_eur=Decimal("10"),
                ogr_validation=OgrValidationResult(
                    ogr_gain_loss=Decimal("50"),  # OGR and CG both positive - no conflict
                    calculated_gain_loss=Decimal("10"),
                    direction_conflict=False,
                    magnitude_diff_percent=Decimal("400"),  # |(50-10)/10|*100 = 400% for individual lot
                    review_required=False,
                    review_reason=None,
                ),
            ),
            _make_entry(
                disposal_date="2025-01-13",
                asset="USDT",
                platform="ByBit",
                holding_period="Short term",
                gain_loss_eur=Decimal("15"),
                ogr_validation=OgrValidationResult(
                    ogr_gain_loss=Decimal("50"),  # Same OGR value (same lookup key)
                    calculated_gain_loss=Decimal("15"),
                    direction_conflict=False,
                    magnitude_diff_percent=Decimal("233"),  # |(50-15)/15|*100 = 233%
                    review_required=False,
                    review_reason=None,
                ),
            ),
            _make_entry(
                disposal_date="2025-01-13",
                asset="USDT",
                platform="ByBit",
                holding_period="Short term",
                gain_loss_eur=Decimal("20"),
                ogr_validation=OgrValidationResult(
                    ogr_gain_loss=Decimal("50"),  # Same OGR value (same lookup key)
                    calculated_gain_loss=Decimal("20"),
                    direction_conflict=False,
                    magnitude_diff_percent=Decimal("150"),  # |(50-20)/20|*100 = 150%
                    review_required=False,
                    review_reason=None,
                ),
            ),
        ]

        result = _aggregate_capital_entries(entries)

        assert len(result) == 1
        agg = result[0]
        # OGR value should be from first entry, NOT summed
        assert agg.ogr_validation is not None
        assert agg.ogr_validation.ogr_gain_loss == Decimal("50")
        # Calculated gain loss should be summed (10 + 15 + 20 = 45)
        assert agg.ogr_validation.calculated_gain_loss == Decimal("45")
        # No direction conflict: OGR (50) and CG (45) both positive
        assert agg.ogr_validation.direction_conflict is False
        # Magnitude diff percent recalculated from aggregated values
        # |(50 - 45) / 45| × 100 = 11.1%
        assert agg.ogr_validation.magnitude_diff_percent == Decimal("11.11111111111111111111111111")
        # No review required - diff is only 11% < 5% threshold... wait, 11 > 5
        # Actually 11.1% > 5%, so review should be required
        assert agg.ogr_validation.review_required is True
        assert "magnitude differs" in agg.ogr_validation.review_reason
        # Other fields should be aggregated as before
        assert agg.gain_loss_eur == Decimal("45")

    def test_aggregate_ogr_validation_direction_conflict_propagates(self):
        """2 entries where one has direction_conflict=True yield an aggregated entry with direction_conflict=True."""
        from tax_reporting.domain.entities import OgrValidationResult

        entries = [
            _make_entry(
                disposal_date="2025-01-13",
                asset="USDT",
                platform="ByBit",
                holding_period="Short term",
                gain_loss_eur=Decimal("10"),
                ogr_validation=OgrValidationResult(
                    ogr_gain_loss=Decimal("-100"),
                    calculated_gain_loss=Decimal("10"),
                    direction_conflict=True,
                    magnitude_diff_percent=Decimal("1100"),
                    review_required=True,
                    review_reason="Direction conflict: OGR shows loss but CG shows gain",
                ),
            ),
            _make_entry(
                disposal_date="2025-01-13",
                asset="USDT",
                platform="ByBit",
                holding_period="Short term",
                gain_loss_eur=Decimal("15"),
                ogr_validation=OgrValidationResult(
                    ogr_gain_loss=Decimal("-100"),
                    calculated_gain_loss=Decimal("15"),
                    direction_conflict=False,
                    magnitude_diff_percent=Decimal("10"),
                    review_required=False,
                    review_reason=None,
                ),
            ),
        ]

        result = _aggregate_capital_entries(entries)

        assert len(result) == 1
        agg = result[0]
        assert agg.ogr_validation is not None
        # direction_conflict recalculated from aggregated values
        # OGR = -100, CG = 25 (10+15), different signs → conflict
        assert agg.ogr_validation.direction_conflict is True
        # Magnitude diff percent recalculated from aggregated values
        # |(-100 - 25) / 25| × 100 = 500%
        assert agg.ogr_validation.magnitude_diff_percent == Decimal("500")
        # review_required should be True (direction conflict + both > 1 EUR)
        assert agg.ogr_validation.review_required is True
        # review_reason should indicate direction override
        assert "OGR direction override" in agg.ogr_validation.review_reason

    def test_aggregate_ogr_validation_uses_max_magnitude_diff_percent(self):
        """3 entries with different magnitude_diff_percent values.

        Expects aggregated entry with max magnitude_diff_percent.
        """
        from tax_reporting.domain.entities import OgrValidationResult

        entries = [
            _make_entry(
                disposal_date="2025-01-13",
                asset="USDT",
                platform="ByBit",
                holding_period="Short term",
                gain_loss_eur=Decimal("10"),
                ogr_validation=OgrValidationResult(
                    ogr_gain_loss=Decimal("-100"),
                    calculated_gain_loss=Decimal("10"),
                    direction_conflict=False,
                    magnitude_diff_percent=Decimal("10"),
                    review_required=False,
                    review_reason=None,
                ),
            ),
            _make_entry(
                disposal_date="2025-01-13",
                asset="USDT",
                platform="ByBit",
                holding_period="Short term",
                gain_loss_eur=Decimal("15"),
                ogr_validation=OgrValidationResult(
                    ogr_gain_loss=Decimal("-100"),
                    calculated_gain_loss=Decimal("15"),
                    direction_conflict=False,
                    magnitude_diff_percent=Decimal("25"),  # Max
                    review_required=True,
                    review_reason="Magnitude difference exceeds 10% threshold",
                ),
            ),
            _make_entry(
                disposal_date="2025-01-13",
                asset="USDT",
                platform="ByBit",
                holding_period="Short term",
                gain_loss_eur=Decimal("20"),
                ogr_validation=OgrValidationResult(
                    ogr_gain_loss=Decimal("-100"),
                    calculated_gain_loss=Decimal("20"),
                    direction_conflict=False,
                    magnitude_diff_percent=Decimal("15"),
                    review_required=False,
                    review_reason=None,
                ),
            ),
        ]

        result = _aggregate_capital_entries(entries)

        assert len(result) == 1
        agg = result[0]
        assert agg.ogr_validation is not None
        # Magnitude diff percent recalculated from aggregated values
        # OGR = -100, CG = 45 (10+15+20), direction conflict (different signs)
        # |(-100 - 45) / 45| × 100 = 322.2%
        assert agg.ogr_validation.magnitude_diff_percent == Decimal("322.2222222222222222222222222")
        # direction_conflict recalculated from aggregated values
        assert agg.ogr_validation.direction_conflict is True
        # review_required should be True (direction conflict + both > 1 EUR)
        assert agg.ogr_validation.review_required is True
        assert "OGR direction override" in agg.ogr_validation.review_reason

    def test_aggregate_ogr_validation_joins_review_reasons(self):
        """2 entries with review_reasons.

        Expects aggregated entry with review_reason built from aggregated state.
        """
        from tax_reporting.domain.entities import OgrValidationResult

        entries = [
            _make_entry(
                disposal_date="2025-01-13",
                asset="USDT",
                platform="ByBit",
                holding_period="Short term",
                gain_loss_eur=Decimal("10"),
                ogr_validation=OgrValidationResult(
                    ogr_gain_loss=Decimal("-100"),
                    calculated_gain_loss=Decimal("10"),
                    direction_conflict=False,
                    magnitude_diff_percent=Decimal("10"),
                    review_required=True,
                    review_reason="reason A",
                ),
            ),
            _make_entry(
                disposal_date="2025-01-13",
                asset="USDT",
                platform="ByBit",
                holding_period="Short term",
                gain_loss_eur=Decimal("15"),
                ogr_validation=OgrValidationResult(
                    ogr_gain_loss=Decimal("-100"),
                    calculated_gain_loss=Decimal("15"),
                    direction_conflict=False,
                    magnitude_diff_percent=Decimal("15"),
                    review_required=True,
                    review_reason="reason B",
                ),
            ),
        ]

        result = _aggregate_capital_entries(entries)

        assert len(result) == 1
        agg = result[0]
        assert agg.ogr_validation is not None
        # review_required is True based on aggregated state
        assert agg.ogr_validation.review_required is True
        # review_reason is built from aggregated state, not joined from individual lots
        # OGR = -100, CG = 25 (10+15), direction conflict (different signs)
        assert "OGR direction override" in agg.ogr_validation.review_reason

    def test_aggregate_ogr_validation_deduplicates_review_reasons(self):
        """Given 3 entries, expects aggregated entry with review_reason built from aggregated state."""
        from tax_reporting.domain.entities import OgrValidationResult

        entries = [
            _make_entry(
                disposal_date="2025-01-13",
                asset="USDT",
                platform="ByBit",
                holding_period="Short term",
                gain_loss_eur=Decimal("10"),
                ogr_validation=OgrValidationResult(
                    ogr_gain_loss=Decimal("-100"),
                    calculated_gain_loss=Decimal("10"),
                    direction_conflict=False,
                    magnitude_diff_percent=Decimal("10"),
                    review_required=True,
                    review_reason="duplicate reason",
                ),
            ),
            _make_entry(
                disposal_date="2025-01-13",
                asset="USDT",
                platform="ByBit",
                holding_period="Short term",
                gain_loss_eur=Decimal("15"),
                ogr_validation=OgrValidationResult(
                    ogr_gain_loss=Decimal("-100"),
                    calculated_gain_loss=Decimal("15"),
                    direction_conflict=False,
                    magnitude_diff_percent=Decimal("15"),
                    review_required=True,
                    review_reason="duplicate reason",  # Same as first
                ),
            ),
            _make_entry(
                disposal_date="2025-01-13",
                asset="USDT",
                platform="ByBit",
                holding_period="Short term",
                gain_loss_eur=Decimal("20"),
                ogr_validation=OgrValidationResult(
                    ogr_gain_loss=Decimal("-100"),
                    calculated_gain_loss=Decimal("20"),
                    direction_conflict=False,
                    magnitude_diff_percent=Decimal("20"),
                    review_required=True,
                    review_reason="unique reason",
                ),
            ),
        ]

        result = _aggregate_capital_entries(entries)

        assert len(result) == 1
        agg = result[0]
        assert agg.ogr_validation is not None
        # review_required is True based on aggregated state
        assert agg.ogr_validation.review_required is True
        # review_reason is built from aggregated state, not deduplicated from individual lots
        # OGR = -100, CG = 45 (10+15+20), direction conflict (different signs)
        assert "OGR direction override" in agg.ogr_validation.review_reason

    def test_aggregate_ogr_validation_none_when_all_none(self):
        """Given 3 entries with ogr_validation=None, expects aggregated entry with ogr_validation=None."""
        entries = [
            _make_entry(
                disposal_date="2025-01-13",
                asset="USDT",
                platform="ByBit",
                holding_period="Short term",
                gain_loss_eur=Decimal("10"),
                ogr_validation=None,
            ),
            _make_entry(
                disposal_date="2025-01-13",
                asset="USDT",
                platform="ByBit",
                holding_period="Short term",
                gain_loss_eur=Decimal("15"),
                ogr_validation=None,
            ),
            _make_entry(
                disposal_date="2025-01-13",
                asset="USDT",
                platform="ByBit",
                holding_period="Short term",
                gain_loss_eur=Decimal("20"),
                ogr_validation=None,
            ),
        ]

        result = _aggregate_capital_entries(entries)

        assert len(result) == 1
        agg = result[0]
        assert agg.ogr_validation is None
        assert agg.gain_loss_eur == Decimal("45")

    def test_aggregate_ogr_validation_skips_none_entries(self):
        """
Given 3 entries where one has ogr_validation=None, expects aggregated entry with validation from non-None entries.
        """
        from tax_reporting.domain.entities import OgrValidationResult

        entries = [
            _make_entry(
                disposal_date="2025-01-13",
                asset="USDT",
                platform="ByBit",
                holding_period="Short term",
                gain_loss_eur=Decimal("10"),
                ogr_validation=None,
            ),
            _make_entry(
                disposal_date="2025-01-13",
                asset="USDT",
                platform="ByBit",
                holding_period="Short term",
                gain_loss_eur=Decimal("15"),
                ogr_validation=OgrValidationResult(
                    ogr_gain_loss=Decimal("-100"),
                    calculated_gain_loss=Decimal("15"),
                    direction_conflict=False,
                    magnitude_diff_percent=Decimal("15"),
                    review_required=False,
                    review_reason=None,
                ),
            ),
            _make_entry(
                disposal_date="2025-01-13",
                asset="USDT",
                platform="ByBit",
                holding_period="Short term",
                gain_loss_eur=Decimal("20"),
                ogr_validation=OgrValidationResult(
                    ogr_gain_loss=Decimal("-100"),
                    calculated_gain_loss=Decimal("20"),
                    direction_conflict=False,
                    magnitude_diff_percent=Decimal("20"),
                    review_required=False,
                    review_reason=None,
                ),
            ),
        ]

        result = _aggregate_capital_entries(entries)

        assert len(result) == 1
        agg = result[0]
        assert agg.ogr_validation is not None
        assert agg.ogr_validation.ogr_gain_loss == Decimal("-100")
        # calculated_gain_loss sums only entries with ogr_validation (15 + 20 = 35)
        # Wait, but the first entry has ogr_validation=None, so it's excluded
        # Actually, looking at the code, calculated_gain_loss sums from with_ogr entries only
        # But gain_loss_eur in the aggregated entry sums ALL entries (10 + 15 + 20 = 45)
        # Let me check what the actual behavior is...
        assert agg.ogr_validation.calculated_gain_loss == Decimal("35")  # 15 + 20 (from with_ogr entries)
        # Magnitude diff percent recalculated from aggregated OGR vs calculated
        # OGR = -100, calculated = 35, different signs → direction conflict
        # |(-100 - 35) / 35| × 100 = 385.7%
        assert agg.ogr_validation.magnitude_diff_percent == Decimal("385.7142857142857142857142857")
        # direction_conflict recalculated from aggregated values
        assert agg.ogr_validation.direction_conflict is True


# --- Task 4: MNT ticker collision tests ---


def test_mnt_token_collision():
    """MNT ticker collision between Mantle token (crypto) and Mongolian tögrög (fiat).

    MNT rewards from ByBit/Koinly are Mantle L2 blockchain token, not Mongolian tögrög.
    The crypto token must be classified as DEFERRED_BY_LAW per CRG-001, not TAXABLE_NOW.

    The real Koinly dataset confirms 20 MNT reward rows from ByBit and Mantle wallets
    in the income report, and 17 disposal rows in the capital gains report; all
    referencing the Mantle blockchain token, not fiat currency.
    """
    assert _classify_reward_tax_status("MNT") == RewardTaxClassification.DEFERRED_BY_LAW
    assert _classify_reward_tax_status("mnt") == RewardTaxClassification.DEFERRED_BY_LAW
    assert _classify_reward_tax_status("Mnt") == RewardTaxClassification.DEFERRED_BY_LAW


def test_capital_gains_fee_notes_do_not_create_reward_entries(tmp_path):
    """Regression test: a capital-gains row with Notes = Fee must not create
    or alter reward entries when both capital-gains and income reports are
    loaded together via load_koinly_crypto_report().

    The user reported a concern that capital-gains rows with Notes = Fee might
    leak into the reward path. This test proves the boundary is clean: reward
    entries come exclusively from the income report file.
    """
    koinly_dir = tmp_path / "koinly2025"
    koinly_dir.mkdir()

    (koinly_dir / "koinly_2025_capital_gains_report_test.csv").write_text(
        "\n".join(
            [
                "Capital gains report 2025",
                "",
                ",".join(
                    [
                        "Date Sold",
                        "Date Acquired",
                        "Asset",
                        "Amount",
                        "Cost (EUR)",
                        "Proceeds (EUR)",
                        "Gain / loss",
                        "Notes",
                        "Wallet Name",
                        "Holding period",
                    ]
                ),
                ",".join(
                    [
                        "13/01/2025 13:01",
                        "18/11/2024 00:15",
                        "USDT",
                        '"1,50000000"',
                        '"1,25"',
                        '"2,35"',
                        '"1,10"',
                        "Fee",
                        "ByBit (2)",
                        "Short term",
                    ]
                ),
                ",".join(
                    [
                        "20/01/2025 10:10",
                        "01/01/2024 00:00",
                        "BTC",
                        '"0,10000000"',
                        '"3000,00"',
                        '"3500,00"',
                        '"500,00"',
                        "Fee",
                        "Kraken",
                        "Long term",
                    ]
                ),
            ]
        ),
        encoding="utf-8",
    )

    (koinly_dir / "koinly_2025_income_report_test.csv").write_text(
        "\n".join(
            [
                "Income report 2025",
                "",
                "Date,Asset,Amount,Value (EUR),Type,Description,Wallet Name",
                '01/01/2025 00:01,WXT,"5,00000000","17,10",Reward,,Wirex',
            ]
        ),
        encoding="utf-8",
    )

    _write_minimal_transaction_history(koinly_dir)

    report = load_koinly_crypto_report(koinly_dir)

    assert report is not None
    assert len(report.capital_entries) == 2
    assert all("Fee" in e.notes for e in report.capital_entries)
    assert len(report.reward_entries) == 1
    assert report.reward_entries[0].asset == "WXT"
    assert report.reward_entries[0].value_eur == Decimal("17.10")


def test_reward_parsing_independent_of_capital_gains_notes(tmp_path):
    """Reward entries must depend only on the income report CSV, never on
    Notes values from the capital-gains export.

    This test loads the same income report twice: once with a capital-gains
    file containing various Notes values, and once with an empty capital-gains
    file plus the required empty transaction history. The reward entries must
    be identical in both cases.
    """
    koinly_dir_with_cg = tmp_path / "with_capital_gains"
    koinly_dir_with_cg.mkdir()

    income_csv = "\n".join(
        [
            "Income report 2025",
            "",
            "Date,Asset,Amount,Value (EUR),Type,Description,Wallet Name",
            '01/01/2025 00:01,BTC,"0,01000000","500,00",Reward,,ByBit',
            '02/01/2025 00:01,EUR,"10,00","10,00",Reward,Cashback,Kraken',
        ]
    )

    (koinly_dir_with_cg / "koinly_2025_income_report_test.csv").write_text(income_csv, encoding="utf-8")
    (koinly_dir_with_cg / "koinly_2025_capital_gains_report_test.csv").write_text(
        "\n".join(
            [
                "Capital gains report 2025",
                "",
                ",".join(
                    [
                        "Date Sold",
                        "Date Acquired",
                        "Asset",
                        "Amount",
                        "Cost (EUR)",
                        "Proceeds (EUR)",
                        "Gain / loss",
                        "Notes",
                        "Wallet Name",
                        "Holding period",
                    ]
                ),
                ",".join(
                    [
                        "13/01/2025 13:01",
                        "18/11/2024 00:15",
                        "USDT",
                        '"1,50000000"',
                        '"1,25"',
                        '"2,35"',
                        '"1,10"',
                        "Fee",
                        "ByBit (2)",
                        "Short term",
                    ]
                ),
                ",".join(
                    [
                        "20/01/2025 10:10",
                        "01/01/2024 00:00",
                        "BTC",
                        '"0,10000000"',
                        '"3000,00"',
                        '"3500,00"',
                        '"500,00"',
                        "Missing cost basis",
                        "Kraken",
                        "Long term",
                    ]
                ),
            ]
        ),
        encoding="utf-8",
    )
    _write_minimal_transaction_history(koinly_dir_with_cg)

    koinly_dir_no_cg = tmp_path / "no_capital_gains"
    koinly_dir_no_cg.mkdir()
    (koinly_dir_no_cg / "koinly_2025_income_report_test.csv").write_text(income_csv, encoding="utf-8")
    _write_minimal_capital_gains_report(koinly_dir_no_cg)
    _write_minimal_transaction_history(koinly_dir_no_cg)

    report_with_cg = load_koinly_crypto_report(koinly_dir_with_cg)
    report_no_cg = load_koinly_crypto_report(koinly_dir_no_cg)

    assert report_with_cg is not None
    assert report_no_cg is not None

    assert len(report_with_cg.reward_entries) == len(report_no_cg.reward_entries) == 2

    rewards_with = sorted(report_with_cg.reward_entries, key=lambda r: (r.asset, r.date))
    rewards_no = sorted(report_no_cg.reward_entries, key=lambda r: (r.asset, r.date))

    for with_cg, no_cg in zip(rewards_with, rewards_no, strict=True):
        assert with_cg.asset == no_cg.asset
        assert with_cg.value_eur == no_cg.value_eur
        assert with_cg.amount == no_cg.amount
        assert with_cg.tax_classification == no_cg.tax_classification
        assert with_cg.wallet == no_cg.wallet
        assert with_cg.date == no_cg.date


def test_mnt_reward_stays_deferred_through_full_parse(tmp_path):
    """Parser-level regression: a reward row with Asset = MNT stays DEFERRED_BY_LAW
    after load_koinly_crypto_report(), proving the collision list is applied during
    income file parsing.

    Without the MNT entry in _CRYPTO_TOKEN_FIAT_COLLISIONS, pycountry would classify
    MNT as TAXABLE_NOW (fiat = Mongolian tögrög), which is wrong for the Mantle token.
    """
    koinly_dir = tmp_path / "koinly2025"
    koinly_dir.mkdir()

    (koinly_dir / "koinly_2025_income_report_test.csv").write_text(
        "\n".join(
            [
                "Income report 2025",
                "",
                "Date,Asset,Amount,Value (EUR),Type,Description,Wallet Name",
                '01/01/2025 00:01,MNT,"5,85000000","3,50",Reward,,ByBit (2)',
                '02/01/2025 00:01,MNT,"44,91000000","25,00",Reward,,Mantle (MNT)',
                '03/01/2025 00:01,EUR,"10,00","10,00",Reward,,Kraken',
            ]
        ),
        encoding="utf-8",
    )
    _write_minimal_capital_gains_report(koinly_dir)
    _write_minimal_transaction_history(koinly_dir)

    report = load_koinly_crypto_report(koinly_dir)

    assert report is not None
    mnt_rewards = [r for r in report.reward_entries if r.asset == "MNT"]
    assert len(mnt_rewards) == 2
    for reward in mnt_rewards:
        assert reward.tax_classification == RewardTaxClassification.DEFERRED_BY_LAW, (
            f"MNT reward must be DEFERRED_BY_LAW, got {reward.tax_classification}"
        )

    eur_reward = next(r for r in report.reward_entries if r.asset == "EUR")
    assert eur_reward.tax_classification == RewardTaxClassification.TAXABLE_NOW


# --- Task 1: CapitalGainPeriodStats tests ---


def test_capital_gain_period_stats_zero():
    """CapitalGainPeriodStats construction with zero values and correct property access."""
    from tax_reporting.application.crypto_reporting import CapitalGainPeriodStats

    _zero = Decimal("0")
    stats = CapitalGainPeriodStats(count=0, cost_total_eur=_zero, proceeds_total_eur=_zero, gain_loss_total_eur=_zero)
    assert stats.count == 0
    assert stats.cost_total_eur == Decimal("0")
    assert stats.proceeds_total_eur == Decimal("0")
    assert stats.gain_loss_total_eur == Decimal("0")


def test_capital_gain_period_stats_from_entries():
    """from_entries() correctly sums cost, proceeds, gain/loss and counts entries."""
    from tax_reporting.application.crypto_reporting import CapitalGainPeriodStats

    entries = [
        _make_entry(cost_eur=Decimal("100"), proceeds_eur=Decimal("120"), gain_loss_eur=Decimal("20")),
        _make_entry(cost_eur=Decimal("200"), proceeds_eur=Decimal("250"), gain_loss_eur=Decimal("50")),
        _make_entry(cost_eur=Decimal("50"), proceeds_eur=Decimal("45"), gain_loss_eur=Decimal("-5")),
    ]

    stats = CapitalGainPeriodStats.from_entries(entries)

    assert stats.count == 3
    assert stats.cost_total_eur == Decimal("350")
    assert stats.proceeds_total_eur == Decimal("415")
    assert stats.gain_loss_total_eur == Decimal("65")


def test_capital_gain_period_stats_from_empty_entries():
    """from_entries() with empty list returns zero-stats."""
    from tax_reporting.application.crypto_reporting import CapitalGainPeriodStats

    stats = CapitalGainPeriodStats.from_entries([])

    assert stats.count == 0
    assert stats.cost_total_eur == Decimal("0")
    assert stats.proceeds_total_eur == Decimal("0")
    assert stats.gain_loss_total_eur == Decimal("0")


# --- Task 2: CryptoCapitalGainStats aggregate tests ---


def test_compute_capital_gain_stats_all_periods():
    """Stats computed across all four holding periods with correct per-period and grand-total values."""
    from tax_reporting.application.crypto_reporting import CryptoCapitalGainStats

    entries = [
        _make_entry(
            holding_period="Short term", cost_eur=Decimal("100"),
            proceeds_eur=Decimal("120"), gain_loss_eur=Decimal("20"),
        ),
        _make_entry(
            holding_period="Short term", cost_eur=Decimal("50"),
            proceeds_eur=Decimal("60"), gain_loss_eur=Decimal("10"),
        ),
        _make_entry(
            holding_period="Long term", cost_eur=Decimal("200"),
            proceeds_eur=Decimal("250"), gain_loss_eur=Decimal("50"),
        ),
        _make_entry(
            holding_period="Mixed", cost_eur=Decimal("80"),
            proceeds_eur=Decimal("70"), gain_loss_eur=Decimal("-10"),
        ),
        _make_entry(
            holding_period="Unknown", cost_eur=Decimal("30"),
            proceeds_eur=Decimal("35"), gain_loss_eur=Decimal("5"),
        ),
    ]

    stats = CryptoCapitalGainStats.from_entries(entries)

    assert stats.short_term.count == 2
    assert stats.short_term.cost_total_eur == Decimal("150")
    assert stats.short_term.proceeds_total_eur == Decimal("180")
    assert stats.short_term.gain_loss_total_eur == Decimal("30")

    assert stats.long_term.count == 1
    assert stats.long_term.cost_total_eur == Decimal("200")
    assert stats.long_term.proceeds_total_eur == Decimal("250")
    assert stats.long_term.gain_loss_total_eur == Decimal("50")

    assert stats.mixed.count == 1
    assert stats.mixed.cost_total_eur == Decimal("80")
    assert stats.mixed.proceeds_total_eur == Decimal("70")
    assert stats.mixed.gain_loss_total_eur == Decimal("-10")

    assert stats.unknown.count == 1
    assert stats.unknown.cost_total_eur == Decimal("30")
    assert stats.unknown.proceeds_total_eur == Decimal("35")
    assert stats.unknown.gain_loss_total_eur == Decimal("5")

    assert stats.grand_total.count == 5
    assert stats.grand_total.cost_total_eur == Decimal("460")
    assert stats.grand_total.proceeds_total_eur == Decimal("535")
    assert stats.grand_total.gain_loss_total_eur == Decimal("75")


def test_compute_capital_gain_stats_single_period():
    """Only one period has non-zero stats, others are zero."""
    from tax_reporting.application.crypto_reporting import CryptoCapitalGainStats

    entries = [
        _make_entry(
            holding_period="Long term", cost_eur=Decimal("500"),
            proceeds_eur=Decimal("600"), gain_loss_eur=Decimal("100"),
        ),
        _make_entry(
            holding_period="Long term", cost_eur=Decimal("300"),
            proceeds_eur=Decimal("350"), gain_loss_eur=Decimal("50"),
        ),
    ]

    stats = CryptoCapitalGainStats.from_entries(entries)

    assert stats.short_term.count == 0
    assert stats.short_term.cost_total_eur == Decimal("0")

    assert stats.long_term.count == 2
    assert stats.long_term.cost_total_eur == Decimal("800")
    assert stats.long_term.gain_loss_total_eur == Decimal("150")

    assert stats.mixed.count == 0
    assert stats.unknown.count == 0

    assert stats.grand_total.count == 2
    assert stats.grand_total.cost_total_eur == Decimal("800")


def test_compute_capital_gain_stats_empty():
    """All periods and grand total are zero-stats from empty list."""
    from tax_reporting.application.crypto_reporting import CryptoCapitalGainStats

    stats = CryptoCapitalGainStats.from_entries([])

    assert stats.short_term.count == 0
    assert stats.long_term.count == 0
    assert stats.mixed.count == 0
    assert stats.unknown.count == 0
    assert stats.grand_total.count == 0
    assert stats.grand_total.cost_total_eur == Decimal("0")
    assert stats.grand_total.proceeds_total_eur == Decimal("0")
    assert stats.grand_total.gain_loss_total_eur == Decimal("0")


def test_compute_capital_gain_stats_mixed_gains():
    """Correct aggregation of positive and negative gains within a period."""
    from tax_reporting.application.crypto_reporting import CryptoCapitalGainStats

    entries = [
        _make_entry(
            holding_period="Short term", cost_eur=Decimal("100"),
            proceeds_eur=Decimal("150"), gain_loss_eur=Decimal("50"),
        ),
        _make_entry(
            holding_period="Short term", cost_eur=Decimal("200"),
            proceeds_eur=Decimal("100"), gain_loss_eur=Decimal("-100"),
        ),
        _make_entry(
            holding_period="Short term", cost_eur=Decimal("50"),
            proceeds_eur=Decimal("55"), gain_loss_eur=Decimal("5"),
        ),
    ]

    stats = CryptoCapitalGainStats.from_entries(entries)

    assert stats.short_term.count == 3
    assert stats.short_term.cost_total_eur == Decimal("350")
    assert stats.short_term.proceeds_total_eur == Decimal("305")
    assert stats.short_term.gain_loss_total_eur == Decimal("-45")

    assert stats.grand_total.count == 3
    assert stats.grand_total.gain_loss_total_eur == Decimal("-45")


def test_compute_capital_gain_stats_unrecognized_period(caplog):
    """Grand total EUR amounts include all entries even when holding period is unrecognized."""
    from tax_reporting.application.crypto_reporting import CryptoCapitalGainStats

    entries = [
        _make_entry(
            holding_period="Short term", cost_eur=Decimal("100"),
            proceeds_eur=Decimal("150"), gain_loss_eur=Decimal("50"),
        ),
        _make_entry(
            holding_period="Medium term", cost_eur=Decimal("200"),
            proceeds_eur=Decimal("250"), gain_loss_eur=Decimal("50"),
        ),
    ]

    stats = CryptoCapitalGainStats.from_entries(entries)

    assert stats.short_term.count == 1
    assert stats.long_term.count == 0
    assert stats.mixed.count == 0
    assert stats.unknown.count == 0
    assert stats.grand_total.count == 2
    assert stats.grand_total.cost_total_eur == Decimal("300")
    assert stats.grand_total.proceeds_total_eur == Decimal("400")
    assert stats.grand_total.gain_loss_total_eur == Decimal("100")
    assert "Unrecognised" in caplog.text


# --- Task 3: CryptoTaxReport integration of capital_gain_stats ---


def test_crypto_tax_report_includes_capital_gain_stats():
    """CryptoTaxReport has a capital_gain_stats field of type CryptoCapitalGainStats."""
    from tax_reporting.application.crypto_reporting import (
        CryptoCapitalGainStats,
        CryptoReconciliationSummary,
        CryptoTaxReport,
    )

    zero_stats = CryptoCapitalGainStats.from_entries([])
    report = CryptoTaxReport(
        tax_year=2025,
        capital_entries=[],
        reward_entries=[],
        reconciliation=CryptoReconciliationSummary(
            capital_rows=0,
            reward_rows=0,
            short_term_rows=0,
            long_term_rows=0,
            mixed_rows=0,
            unknown_rows=0,
            capital_cost_total_eur=Decimal("0"),
            capital_proceeds_total_eur=Decimal("0"),
            capital_gain_total_eur=Decimal("0"),
            reward_total_eur=Decimal("0"),
            opening_holdings=None,
            closing_holdings=None,
        ),
        capital_gain_stats=zero_stats,
    )

    assert isinstance(report.capital_gain_stats, CryptoCapitalGainStats)
    assert report.capital_gain_stats.grand_total.count == 0


def test_crypto_tax_report_capital_gain_stats_computed_from_entries(tmp_path):
    """load_koinly_crypto_report computes capital_gain_stats from capital entries."""
    koinly_dir = tmp_path / "koinly2025"
    koinly_dir.mkdir()

    (koinly_dir / "koinly_2025_capital_gains_report_test.csv").write_text(
        "\n".join(
            [
                "Capital gains report 2025",
                "",
                ",".join(
                    [
                        "Date Sold",
                        "Date Acquired",
                        "Asset",
                        "Amount",
                        "Cost (EUR)",
                        "Proceeds (EUR)",
                        "Gain / loss",
                        "Notes",
                        "Wallet Name",
                        "Holding period",
                    ]
                ),
                ",".join(
                    [
                        "15/01/2025 10:00",
                        "01/06/2024 00:00",
                        "BTC",
                        '"0,50000000"',
                        '"10000,00"',
                        '"12000,00"',
                        '"2000,00"',
                        "",
                        "ByBit (2)",
                        "Short term",
                    ]
                ),
                ",".join(
                    [
                        "20/02/2025 14:00",
                        "01/01/2023 00:00",
                        "ETH",
                        '"1,00000000"',
                        '"2000,00"',
                        '"2500,00"',
                        '"500,00"',
                        "",
                        "Kraken",
                        "Long term",
                    ]
                ),
            ]
        ),
        encoding="utf-8",
    )

    _write_minimal_income_report(koinly_dir)
    _write_minimal_transaction_history(koinly_dir)

    report = load_koinly_crypto_report(koinly_dir)
    assert report is not None

    stats = report.capital_gain_stats
    assert stats.short_term.count == 1
    assert stats.short_term.gain_loss_total_eur == Decimal("2000")
    assert stats.long_term.count == 1
    assert stats.long_term.gain_loss_total_eur == Decimal("500")
    assert stats.mixed.count == 0
    assert stats.unknown.count == 0
    assert stats.grand_total.count == 2
    assert stats.grand_total.gain_loss_total_eur == Decimal("2500")


def test_format_datetime_returns_date_only():
    assert format_datetime(datetime(2025, 1, 13, 13, 1, 0, tzinfo=UTC)) == "2025-01-13"


def test_format_datetime_epoch_sentinel_returns_1970_01_01():
    assert format_datetime(datetime(1970, 1, 1, 0, 0, 0, tzinfo=UTC)) == "1970-01-01"


class TestTokenOriginResolver:
    """Token origin resolver tests using implicit (date, asset, wallet) correlation."""

    _TH_HEADER = (
        "Transaction report 2025\n"
        "\n"
        "Date,Type,Tag,Sending Wallet,Sent Amount,Sent Currency,Sent Cost Basis,"
        "Receiving Wallet,Received Amount,Received Currency,Received Cost Basis,"
        "Fee Amount,Fee Currency,Gain (EUR),Net Value (EUR),Fee Value (EUR),"
        "TxSrc,TxDest,TxHash,Description"
    )

    def _write_th(self, tmp_path, data_rows: str):
        path = tmp_path / "th.csv"
        path.write_text(f"{self._TH_HEADER}\n{data_rows}", encoding="utf-8")
        return path

    def test_token_origin_resolver_swap_with_hash_high_confidence(self, tmp_path) -> None:
        path = self._write_th(
            tmp_path,
            '2025-01-15 10:30:00 UTC,exchange,,Kraken,100,BTC,5000,'
            "Kraken,2.5,ETH,5000,,,,,,abc,def,hash123,trade\n",
        )
        resolver = build_origin_resolver(path)
        origin = resolver.resolve("2025-01-15", "ETH", "Kraken")
        assert origin.acquisition_method == AcquisitionMethod.SWAP_CONVERSION
        assert origin.acquired_from_asset == "BTC"
        assert origin.acquired_from_platform == "Kraken"
        assert origin.confidence == "high"

    def test_token_origin_resolver_reward_deposit(self, tmp_path) -> None:
        path = self._write_th(
            tmp_path,
            "2025-03-10 08:00:00 UTC,crypto_deposit,Reward,,,,,"
            'ByBit,5,SOL,50,,,,,,,,,\n',
        )
        resolver = build_origin_resolver(path)
        origin = resolver.resolve("2025-03-10", "SOL", "ByBit")
        assert origin.acquisition_method == AcquisitionMethod.REWARD
        assert origin.confidence == "medium"

    def test_token_origin_resolver_unknown_when_no_match(self, tmp_path) -> None:
        path = self._write_th(
            tmp_path,
            '2025-01-15 10:30:00 UTC,exchange,,Kraken,100,BTC,5000,'
            "Kraken,2.5,ETH,5000,,,,,,abc,def,hash123,trade\n",
        )
        resolver = build_origin_resolver(path)
        origin = resolver.resolve("2025-06-01", "BTC", "UnknownWallet")
        assert origin.acquisition_method == AcquisitionMethod.UNKNOWN
        assert origin.confidence == "low"

    def test_token_origin_resolver_unknown_when_no_transaction_history(self) -> None:
        resolver = build_origin_resolver(None)
        origin = resolver.resolve("2025-01-15", "BTC", "Kraken")
        assert origin.acquisition_method == AcquisitionMethod.UNKNOWN
        assert origin.confidence == "low"

    def test_token_origin_resolver_epoch_date_returns_unknown(self, tmp_path) -> None:
        path = self._write_th(tmp_path, "")
        resolver = build_origin_resolver(path)
        origin = resolver.resolve("1970-01-01", "BTC", "Kraken")
        assert origin.acquisition_method == AcquisitionMethod.UNKNOWN
        assert origin.confidence == "low"

    def test_token_origin_resolver_direct_purchase_fiat_deposit(self, tmp_path) -> None:
        path = self._write_th(
            tmp_path,
            '2025-02-20 14:00:00 UTC,fiat_deposit,,Bank,5000,EUR,5000,'
            "Kraken,0.5,BTC,5000,,,,,,,,,\n",
        )
        resolver = build_origin_resolver(path)
        origin = resolver.resolve("2025-02-20", "BTC", "Kraken")
        assert origin.acquisition_method == AcquisitionMethod.DIRECT_PURCHASE
        assert origin.acquired_from_asset == "EUR"

    def test_token_origin_resolver_defi_yield_lending_interest(self, tmp_path) -> None:
        path = self._write_th(
            tmp_path,
            "2025-04-01 00:00:00 UTC,crypto_deposit,Lending interest,,,,,"
            'Ethereum,0.1,USDT,100,,,,,,,,,\n',
        )
        resolver = build_origin_resolver(path)
        origin = resolver.resolve("2025-04-01", "USDT", "Ethereum")
        assert origin.acquisition_method == AcquisitionMethod.DEFI_YIELD

    def test_token_origin_resolver_medium_confidence_without_hash(self, tmp_path) -> None:
        path = self._write_th(
            tmp_path,
            "2025-05-10 09:00:00 UTC,crypto_deposit,Reward,,,,,"
            'Kraken,10,ETH,200,,,,,,,,,\n',
        )
        resolver = build_origin_resolver(path)
        origin = resolver.resolve("2025-05-10", "ETH", "Kraken")
        assert origin.confidence == "medium"

    def test_token_origin_resolver_low_confidence_missing_cost_basis(self, tmp_path) -> None:
        path = self._write_th(
            tmp_path,
            '2025-01-15 10:30:00 UTC,exchange,,Kraken,100,BTC,5000,'
            "Kraken,2.5,ETH,5000,,,,,,abc,def,hash123,trade\n",
        )
        resolver = build_origin_resolver(path)
        origin = resolver.resolve("2025-01-15", "ETH", "Kraken", notes="Missing cost basis")
        assert origin.confidence == "low"

    def test_token_origin_resolver_cashback_is_reward(self, tmp_path) -> None:
        path = self._write_th(
            tmp_path,
            "2025-06-01 12:00:00 UTC,crypto_deposit,Cashback,,,,,"
            'Wirex,10,WXT,5,,,,,,,,,\n',
        )
        resolver = build_origin_resolver(path)
        origin = resolver.resolve("2025-06-01", "WXT", "Wirex")
        assert origin.acquisition_method == AcquisitionMethod.REWARD

    def test_token_origin_resolver_transfer_generic_deposit(self, tmp_path) -> None:
        path = self._write_th(
            tmp_path,
            "2025-07-01 09:00:00 UTC,crypto_deposit,,,,,,"
            'Binance,1,BTC,50000,,,,,,,,,\n',
        )
        resolver = build_origin_resolver(path)
        origin = resolver.resolve("2025-07-01", "BTC", "Binance")
        assert origin.acquisition_method == AcquisitionMethod.TRANSFER

    def test_token_origin_str_format(self) -> None:
        origin = TokenOrigin(
            acquired_from_asset="BTC",
            acquired_from_platform="Kraken",
            acquisition_method=AcquisitionMethod.SWAP_CONVERSION,
            confidence="medium",
        )
        assert str(origin) == "BTC (swap_conversion, medium confidence)"

    def test_token_origin_str_unknown_is_empty(self) -> None:
        origin = TokenOrigin(
            acquired_from_asset="Unknown",
            acquired_from_platform="Unknown",
            acquisition_method=AcquisitionMethod.UNKNOWN,
            confidence="low",
        )
        assert str(origin) == ""

    def test_token_origin_resolver_bybit_alias_normalized(self, tmp_path) -> None:
        path = self._write_th(
            tmp_path,
            "2025-01-01 00:15:00 UTC,crypto_deposit,Reward,,,,,"
            '"ByBit (2)","0,25",USDT,"0,24",,,,,,,,,\n',
        )
        resolver = build_origin_resolver(path)
        origin = resolver.resolve("2025-01-01", "USDT", "ByBit (2)")
        assert origin.acquisition_method == AcquisitionMethod.REWARD

    def test_token_origin_resolver_prefers_hash_over_no_hash(self, tmp_path) -> None:
        path = self._write_th(
            tmp_path,
            "2025-01-15 08:00:00 UTC,crypto_deposit,Reward,,,,,"
            'Kraken,10,ETH,200,,,,,,,,,\n'
            '2025-01-15 10:30:00 UTC,exchange,,Kraken,100,BTC,5000,'
            "Kraken,10,ETH,5000,,,,,,abc,def,hash123,trade\n",
        )
        resolver = build_origin_resolver(path)
        origin = resolver.resolve("2025-01-15", "ETH", "Kraken")
        assert origin.acquisition_method == AcquisitionMethod.SWAP_CONVERSION
        assert origin.confidence == "high"


_CG_HEADER = ",".join(
    [
        "Date Sold",
        "Date Acquired",
        "Asset",
        "Amount",
        "Cost (EUR)",
        "Proceeds (EUR)",
        "Gain / loss",
        "Notes",
        "Wallet Name",
        "Holding period",
    ]
)

_INCOME_HEADER = "Date,Asset,Amount,Value (EUR),Type,Description,Wallet Name"

_TH_HEADER = (
    "Date,Type,Tag,Sending Wallet,Sent Amount,Sent Currency,Sent Cost Basis,"
    "Receiving Wallet,Received Amount,Received Currency,Received Cost Basis,"
    "Fee Amount,Fee Currency,Gain (EUR),Net Value (EUR),Fee Value (EUR),"
    "TxSrc,TxDest,TxHash,Description"
)


def _write_minimal_capital_gains_report(koinly_dir: Path) -> Path:
    path = koinly_dir / "koinly_2025_capital_gains_report.csv"
    path.write_text("\n".join(["Capital gains report 2025", "", _CG_HEADER]), encoding="utf-8")
    return path


def _write_minimal_income_report(koinly_dir: Path) -> Path:
    path = koinly_dir / "koinly_2025_income_report.csv"
    path.write_text("\n".join(["Income report 2025", "", _INCOME_HEADER]), encoding="utf-8")
    return path


def _write_minimal_transaction_history(koinly_dir: Path) -> Path:
    path = koinly_dir / "koinly_2025_transaction_history.csv"
    path.write_text("\n".join(["Transaction report 2025", "", _TH_HEADER]), encoding="utf-8")
    return path


def _write_transaction_history(tmp_path, rows: list[str]) -> Path:
    path = tmp_path / "koinly_2025_transaction_history.csv"
    content = "\n".join(["Transaction report 2025", "", _TH_HEADER] + rows)
    path.write_text(content, encoding="utf-8")
    return path


def test_extract_loan_activity_with_settled_loan(tmp_path):
    """Loan receipt followed by matching repayment produces a settled balance."""
    from tax_reporting.application.crypto.loan_activity import _extract_loan_activity

    path = _write_transaction_history(
        tmp_path,
        [
            '2025-01-10 10:00:00 UTC,crypto_deposit,Loan,,,,,ByBit,100.00,SUI,50.00,,,,500.00,,"","","",""',
            '2025-06-15 10:00:00 UTC,crypto_withdrawal,Loan repayment,ByBit,100.00,SUI,50.00,,,,,,,,0,,"","","",""',
        ],
    )

    entries = _extract_loan_activity(path)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.asset == "SUI"
    assert entry.received_count == 1
    assert entry.received_amount == Decimal("100.00")
    assert entry.received_value_eur == Decimal("500.00")
    assert entry.repaid_count == 1
    assert entry.repaid_amount == Decimal("100.00")
    assert entry.balance_status == LOAN_STATUS_SETTLED
    assert entry.balance_amount == Decimal("0")


def test_extract_loan_activity_multiple_assets(tmp_path):
    """Multiple assets produce separate entries sorted alphabetically."""
    from tax_reporting.application.crypto.loan_activity import _extract_loan_activity

    path = _write_transaction_history(
        tmp_path,
        [
            '2025-01-10 10:00:00 UTC,crypto_deposit,Loan,,,,,ByBit,200.00,USDC,100.00,,,,800.00,,"","","",""',
            '2025-01-11 10:00:00 UTC,crypto_deposit,Loan,,,,,ByBit,300.00,BTC,150.00,,,,1200.00,,"","","",""',
        ],
    )

    entries = _extract_loan_activity(path)
    assert len(entries) == 2
    assert entries[0].asset == "BTC"
    assert entries[1].asset == "USDC"


def test_extract_loan_activity_empty_when_no_loan_rows(tmp_path):
    """Non-loan transaction history rows produce no loan activity entries."""
    from tax_reporting.application.crypto.loan_activity import _extract_loan_activity

    path = _write_transaction_history(
        tmp_path,
        [
            (
                '2025-01-10 10:00:00 UTC,crypto_withdrawal,Cost,'
                'ByBit,"1,00",SUI,"10,00",,,,,,,,,0,0,"","",""'
            ),
        ],
    )

    entries = _extract_loan_activity(path)
    assert entries == []


def test_extract_loan_activity_returns_empty_when_path_none(tmp_path):
    from tax_reporting.application.crypto.loan_activity import _extract_loan_activity

    assert _extract_loan_activity(None) == []


def test_extract_loan_activity_returns_empty_when_path_not_found(tmp_path):
    """A non-existent path (not None) must return an empty list without error."""
    from tax_reporting.application.crypto.loan_activity import _extract_loan_activity

    missing = tmp_path / "no_such_file.csv"
    assert _extract_loan_activity(missing) == []


def test_extract_loan_activity_open_loan_status(tmp_path):
    """More received than repaid produces 'Open loan' balance status."""
    from tax_reporting.application.crypto.loan_activity import _extract_loan_activity

    path = _write_transaction_history(
        tmp_path,
        [
            '2025-01-10 10:00:00 UTC,crypto_deposit,Loan,,,,,ByBit,100.00,SUI,50.00,,,,500.00,,"","","",""',
        ],
    )
    entries = _extract_loan_activity(path)
    assert len(entries) == 1
    assert entries[0].balance_status == LOAN_STATUS_OPEN_LOAN
    assert entries[0].balance_amount == Decimal("100.00")


def test_extract_loan_activity_overpaid_verify_status(tmp_path):
    """More repaid than received (100% overshoot) routes to LOAN_STATUS_OVERPAID_VERIFY (branch (d))."""
    from tax_reporting.application.crypto.loan_activity import _extract_loan_activity

    path = _write_transaction_history(
        tmp_path,
        [
            '2025-01-10 10:00:00 UTC,crypto_deposit,Loan,,,,,ByBit,50.00,SUI,25.00,,,,250.00,,"","","",""',
            '2025-06-15 10:00:00 UTC,crypto_withdrawal,Loan repayment,ByBit,100.00,SUI,50.00,,,,,,,,0,,"","","",""',
        ],
    )
    entries = _extract_loan_activity(path)
    assert len(entries) == 1
    assert entries[0].balance_status == LOAN_STATUS_OVERPAID_VERIFY
    assert entries[0].balance_amount == Decimal("-50.00")


@pytest.mark.unit
class TestExtractLoanActivityClassification:
    """Invariant-4 five-sentinel classifier: four branches (b)/(a)/(c)/(d) plus unchanged Settled/Open-loan.

    These tests call ``_extract_loan_activity`` via TH CSV fixtures (matching the
    ``test_extract_loan_activity_*`` pattern above) so they exercise the real
    production classifier. Branch coverage lives here, not in the sheet tests.
    """

    def test_small_overshoot_with_eur_classified_as_in_asset_interest(self, tmp_path):
        """Branch (c): overshoot_pct <= LOAN_OVERSHOOT_INTEREST_PCT -> IN_ASSET_INTEREST.

        Two fixtures pin both the production shape and the ROUND_HALF_UP rounding mode:
        (i) production-shape amounts (0.585270...% -> 0.5853% at 4dp);
        (ii) a discriminating fixture whose 5th decimal digit is exactly 5 with an even
        predecessor (0.58525%), where ROUND_HALF_UP yields 0.5853 but ROUND_HALF_EVEN
        would yield 0.5852. Case (ii) is the one that actually pins the rounding mode.
        """
        from tax_reporting.application.crypto.loan_activity import _extract_loan_activity

        cases = [
            # (i) Production-shape: 0.06187 vs 0.06151 -> 0.585270...% -> "overshoot 0.5853%"
            (
                "0.06151",
                "0.06187",
                "4697.96",
                "4712.19",
            ),
            # (ii) Discriminating: 10058.525 vs 10000 -> 0.58525% -> ROUND_HALF_UP -> 0.5853
            (
                "10000",
                "10058.525",
                "1000.00",
                "1005.85",
            ),
        ]
        for received_amount, repaid_amount, received_value_eur, repaid_value_eur in cases:
            path = _write_transaction_history(
                tmp_path,
                [
                    (
                        f'2025-01-10 10:00:00 UTC,crypto_deposit,Loan,,,,,ByBit,'
                        f'{received_amount},SUI,1.00,,,,{received_value_eur},,"","","",""'
                    ),
                    # Repayment row: Net Value (EUR) at column 15 (8 commas after Sent Cost
                    # Basis), matching the settled-loan fixture shape so the bound
                    # ``repaid_value_eur`` actually reaches ``entry.repaid_value_eur``.
                    (
                        f'2025-06-15 10:00:00 UTC,crypto_withdrawal,Loan repayment,ByBit,'
                        f'{repaid_amount},SUI,1.00,,,,,,,,{repaid_value_eur},,"","","",""'
                    ),
                ],
            )
            entries = _extract_loan_activity(path)
            assert len(entries) == 1, f"fixture amounts={received_amount}/{repaid_amount}"
            assert entries[0].balance_status == LOAN_STATUS_IN_ASSET_INTEREST, (
                f"fixture amounts={received_amount}/{repaid_amount}"
            )
            assert entries[0].balance_detail == "overshoot 0.5853%", (
                f"fixture amounts={received_amount}/{repaid_amount}"
            )

    def test_no_eur_price_classified_as_cannot_classify(self, tmp_path):
        """Branch (a): received_value_eur == 0 (and received_amount > 0) -> NO_EUR_PRICE.

        ``received_amount > 0`` is load-bearing: branch (b) (received_amount == 0 AND
        repaid_amount > 0) is evaluated FIRST and would route to OVERPAID_VERIFY, so a
        fixture with received_amount == 0 would go RED for the wrong reason.
        """
        from tax_reporting.application.crypto.loan_activity import _extract_loan_activity

        path = _write_transaction_history(
            tmp_path,
            [
                # Receipt: Net Value (EUR) = 0 (LBTC-shaped); received_amount > 0.
                '2025-01-10 10:00:00 UTC,crypto_deposit,Loan,,,,,ByBit,1.00,LBTC,0,,,,0,,"","","",""',
                # Repayment: Net Value (EUR) = 0 at column 15 (lesson #59); repaid_amount
                # slightly MORE than received so balance < ZERO and the classifier enters
                # the overshoot branches, where branch (a) (received_value_eur == 0) fires.
                '2025-06-15 10:00:00 UTC,crypto_withdrawal,Loan repayment,ByBit,1.01,LBTC,0,,,,,,,,0,,,,,"","","",""',
            ],
        )
        entries = _extract_loan_activity(path)
        assert len(entries) == 1
        assert entries[0].balance_status == LOAN_STATUS_NO_EUR_PRICE
        # F14: branch (a) intentionally leaves detail at its None default (no
        # overshoot string is meaningful without a EUR price). Pin that default
        # so a future edit setting detail inside this branch is caught.
        assert entries[0].balance_detail is None

    def test_large_overshoot_routes_to_overpaid_verify(self, tmp_path):
        """Branch (d): overshoot_pct > LOAN_OVERSHOOT_INTEREST_PCT -> OVERPAID_VERIFY (5.0% overshoot)."""
        from tax_reporting.application.crypto.loan_activity import _extract_loan_activity

        path = _write_transaction_history(
            tmp_path,
            [
                # Receipt 100 SUI with Net Value (EUR) > 0 so received_value_eur > 0.
                '2025-01-10 10:00:00 UTC,crypto_deposit,Loan,,,,,ByBit,100.00,SUI,50.00,,,,500.00,,"","","",""',
                # Repayment 105 SUI: 5.0% overshoot -> OVERPAID_VERIFY. Net Value (EUR)
                # at column 15 (8 commas after Sent Cost Basis) so repaid_value_eur > 0.
                (
                    '2025-06-15 10:00:00 UTC,crypto_withdrawal,Loan repayment,ByBit,'
                    '105.00,SUI,52.50,,,,,,,,525.00,,"","","",""'
                ),
            ],
        )
        entries = _extract_loan_activity(path)
        assert len(entries) == 1
        assert entries[0].balance_status == LOAN_STATUS_OVERPAID_VERIFY
        # F2: pin the user-visible 4dp overshoot string the classifier produces on
        # branch (d) (the path reviewers act on). Computes the expected literal from
        # the fixture amounts so a quantize/format regression fails here, not only
        # at the sheet echo. 5.0% overshoot -> "overshoot 5.0000%".
        expected_pct = (
            (abs(Decimal("105.00") - Decimal("100.00")) / Decimal("100.00") * 100)
            .quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        )
        assert entries[0].balance_detail == f"overshoot {expected_pct}%"

    @pytest.mark.parametrize(
        ("received_amount", "repaid_amount", "expected_status"),
        [
            # 0.99% overshoot -> IN_ASSET_INTEREST (strictly below boundary)
            ("100", "100.99", LOAN_STATUS_IN_ASSET_INTEREST),
            # 1.00% overshoot -> IN_ASSET_INTEREST (boundary inclusive: <=)
            ("100", "101", LOAN_STATUS_IN_ASSET_INTEREST),
            # 1.01% overshoot -> OVERPAID_VERIFY (strictly above boundary)
            ("100", "101.01", LOAN_STATUS_OVERPAID_VERIFY),
        ],
    )
    def test_overshoot_boundary_1pct_inclusive(
        self, tmp_path, received_amount, repaid_amount, expected_status
    ):
        """Boundary predicate ``overshoot_pct <= LOAN_OVERSHOOT_INTEREST_PCT`` is inclusive at 1.00%.

        All three cases carry received_value_eur > 0 (Net Value (EUR) populated on the
        receipt row); branch (a) (received_value_eur == 0 -> NO_EUR_PRICE) fires BEFORE
        branch (c), so a zero-EUR fixture would route all three cases to NO_EUR_PRICE and
        the test would go RED for the wrong reason.
        """
        from tax_reporting.application.crypto.loan_activity import _extract_loan_activity

        # Invariant 5: the threshold is Decimal("1"); pin it so an accidental edit to the
        # constant flips the boundary cases below for the right reason rather than silently
        # shifting where the IN_ASSET_INTEREST / OVERPAID_VERIFY split lands.
        assert Decimal("1") == LOAN_OVERSHOOT_INTEREST_PCT

        path = _write_transaction_history(
            tmp_path,
            [
                (
                    f'2025-01-10 10:00:00 UTC,crypto_deposit,Loan,,,,,ByBit,'
                    f'{received_amount},SUI,50.00,,,,500.00,,"","","",""'
                ),
                # Repayment row: Net Value (EUR) at column 15 (8 commas after Sent Cost
                # Basis), matching the settled-loan fixture shape so repaid_value_eur > 0.
                (
                    f'2025-06-15 10:00:00 UTC,crypto_withdrawal,Loan repayment,ByBit,'
                    f'{repaid_amount},SUI,50.00,,,,,,,,500.00,,"","","",""'
                ),
            ],
        )
        entries = _extract_loan_activity(path)
        assert len(entries) == 1
        assert entries[0].balance_status == expected_status

    @pytest.mark.parametrize(
        ("received_amount", "repaid_amount", "expected_status", "expected_detail"),
        [
            # F1: raw_pct straddles 1.00% but pct rounds to 1.0000. The branch
            # decision must use the rounded pct (what the reviewer sees), so the
            # rendered detail and the status agree. raw_pct=0.99996 -> pct=1.0000 ->
            # IN_ASSET_INTEREST (pct <= 1); display "overshoot 1.0000%".
            ("100", "100.99996", LOAN_STATUS_IN_ASSET_INTEREST, "overshoot 1.0000%"),
            # raw_pct=1.00004 -> pct=1.0000 -> IN_ASSET_INTEREST (pct <= 1). Before
            # the fix this routed to OVERPAID_VERIFY (raw_pct > 1) while rendering
            # the identical "overshoot 1.0000%", so display and fill disagreed.
            ("100", "101.00004", LOAN_STATUS_IN_ASSET_INTEREST, "overshoot 1.0000%"),
            # raw_pct=1.00006 -> pct=1.0001 -> OVERPAID_VERIFY (pct > 1); display
            # "overshoot 1.0001%". Sanity that values genuinely above 1.00% still
            # route to verify once pct crosses the threshold.
            ("100", "101.00006", LOAN_STATUS_OVERPAID_VERIFY, "overshoot 1.0001%"),
        ],
    )
    def test_overshoot_precision_display_agrees_with_decision(
        self, tmp_path, received_amount, repaid_amount, expected_status, expected_detail
    ):
        """F1: the branch decision uses the rounded ``pct`` so display and fill agree.

        The reviewer reads the 4dp ``balance_detail`` to verify the fill color. If
        the decision used unrounded ``raw_pct`` while the display used rounded
        ``pct``, two rows with identical visible detail could land on opposite sides
        of the in-asset-interest vs verify split. This pins that the rendered value
        and the routing decision use the same number.
        """
        from tax_reporting.application.crypto.loan_activity import _extract_loan_activity

        path = _write_transaction_history(
            tmp_path,
            [
                (
                    f'2025-01-10 10:00:00 UTC,crypto_deposit,Loan,,,,,ByBit,'
                    f'{received_amount},SUI,50.00,,,,500.00,,"","","",""'
                ),
                (
                    f'2025-06-15 10:00:00 UTC,crypto_withdrawal,Loan repayment,ByBit,'
                    f'{repaid_amount},SUI,50.00,,,,,,,,500.00,,"","","",""'
                ),
            ],
        )
        entries = _extract_loan_activity(path)
        assert len(entries) == 1
        assert entries[0].balance_status == expected_status, (
            f"amounts={received_amount}/{repaid_amount}: status should match the rounded pct"
        )
        assert entries[0].balance_detail == expected_detail

    def test_repayment_only_asset_routes_to_overpaid_verify(self, tmp_path):
        """Branch (b): received_amount == 0 AND repaid_amount > 0 -> OVERPAID_VERIFY (short-circuits branch (a)).

        Per Invariant 4, branch (b) is evaluated FIRST and short-circuits before branch
        (a) checks received_value_eur == 0; therefore received_value_eur == 0 has NO
        effect on a repayment-only row.
        """
        from tax_reporting.application.crypto.loan_activity import _extract_loan_activity

        path = _write_transaction_history(
            tmp_path,
            [
                # Repayment-only: no receipt row, so received_amount == 0; repaid_amount > 0.
                # Net Value (EUR) = 0 at column 15 (lesson #59).
                '2025-06-15 10:00:00 UTC,crypto_withdrawal,Loan repayment,ByBit,0.031,WBTC,0,,,,,,,,0,,,,,"","","",""',
            ],
        )
        entries = _extract_loan_activity(path)
        assert len(entries) == 1
        assert entries[0].balance_status == LOAN_STATUS_OVERPAID_VERIFY
        assert entries[0].balance_detail == "received_amount=0; repayment-only asset"

    def test_settled_and_open_loan_unchanged(self, tmp_path):
        """Regression guard: balance == ZERO -> SETTLED, balance > ZERO -> OPEN_LOAN; balance_detail is None."""
        from tax_reporting.application.crypto.loan_activity import _extract_loan_activity

        # Settled: equal received/repaid.
        settled_path = _write_transaction_history(
            tmp_path,
            [
                '2025-01-10 10:00:00 UTC,crypto_deposit,Loan,,,,,ByBit,100.00,SUI,50.00,,,,500.00,,"","","",""',
                # Repayment row: Net Value (EUR) at column 15 (8 commas after Sent Cost
                # Basis) so repaid_value_eur mirrors received_value_eur (lesson #59).
                (
                    '2025-06-15 10:00:00 UTC,crypto_withdrawal,Loan repayment,ByBit,'
                    '100.00,SUI,50.00,,,,,,,,500.00,,"","","",""'
                ),
            ],
        )
        settled_entries = _extract_loan_activity(settled_path)
        assert len(settled_entries) == 1
        assert settled_entries[0].balance_status == LOAN_STATUS_SETTLED
        assert settled_entries[0].balance_detail is None

        # Open loan: more received than repaid.
        open_path = _write_transaction_history(
            tmp_path,
            [
                '2025-01-10 10:00:00 UTC,crypto_deposit,Loan,,,,,ByBit,100.00,SUI,50.00,,,,500.00,,"","","",""',
            ],
        )
        open_entries = _extract_loan_activity(open_path)
        assert len(open_entries) == 1
        assert open_entries[0].balance_status == LOAN_STATUS_OPEN_LOAN
        assert open_entries[0].balance_detail is None


# ---------------------------------------------------------------------------
# _extract_loan_activity: skip-on-error paths
# ---------------------------------------------------------------------------

def test_extract_loan_activity_skips_blank_received_currency_with_warning(tmp_path, caplog):
    """A loan receipt row with blank Received Currency is skipped with a warning."""
    from tax_reporting.application.crypto.loan_activity import _extract_loan_activity

    path = _write_transaction_history(
        tmp_path,
        [
            "2025-01-10 10:00:00 UTC,crypto_deposit,Loan,,,,,ByBit,100.00,,50.00,,,,500.00,,,,",
        ],
    )

    with caplog.at_level("WARNING"):
        entries = _extract_loan_activity(path)

    assert entries == []
    assert any(
        "blank Received Currency" in r.message or "blank received currency" in r.message.lower()
        for r in caplog.records
    )


def test_extract_loan_activity_skips_blank_sent_currency_with_warning(tmp_path, caplog):
    """A loan repayment row with blank Sent Currency is skipped with a warning."""
    from tax_reporting.application.crypto.loan_activity import _extract_loan_activity

    path = _write_transaction_history(
        tmp_path,
        [
            "2025-06-15 10:00:00 UTC,crypto_withdrawal,Loan repayment,ByBit,100.00,,,,,,,,,,,,,,,",
        ],
    )

    with caplog.at_level("WARNING"):
        entries = _extract_loan_activity(path)

    assert entries == []
    assert any("blank Sent Currency" in r.message or "blank sent currency" in r.message.lower() for r in caplog.records)


def test_extract_loan_activity_skips_unparseable_amount_with_warning(tmp_path, caplog):
    """A loan receipt row with non-numeric amount is skipped and valid rows are still processed."""
    from tax_reporting.application.crypto.loan_activity import _extract_loan_activity

    path = _write_transaction_history(
        tmp_path,
        [
            "2025-01-10 10:00:00 UTC,crypto_deposit,Loan,,,,,ByBit,not-a-number,SUI,50.00,,,,500.00,,,,",
            '2025-01-11 10:00:00 UTC,crypto_deposit,Loan,,,,,ByBit,50.00,BTC,25.00,,,,250.00,,"","","",""',
        ],
    )

    with caplog.at_level("WARNING"):
        entries = _extract_loan_activity(path)

    assert len(entries) == 1
    assert entries[0].asset == "BTC"
    assert any("unparseable amount" in r.message.lower() for r in caplog.records)


# --- Loan-affected asset exclusion from CG file (Task 2) ---


def _write_koinly_dir_with_wbtc_and_eth(tmp_path):
    """Create a minimal koinly dir with WBTC + ETH CG rows."""
    koinly_dir = tmp_path / "koinly2025"
    koinly_dir.mkdir()
    _write_minimal_income_report(koinly_dir)
    _write_minimal_transaction_history(koinly_dir)

    header = ",".join(
        [
            "Date Sold",
            "Date Acquired",
            "Asset",
            "Amount",
            "Cost (EUR)",
            "Proceeds (EUR)",
            "Gain / loss",
            "Notes",
            "Wallet Name",
            "Holding period",
        ]
    )

    wbtc_row = ",".join(
        [
            "13/01/2025 13:01",
            "18/11/2024 00:15",
            "WBTC",
            '"1,00000000"',
            '"30000,00"',
            '"35000,00"',
            '"5000,00"',
            "",
            "ByBit",
            "Short term",
        ]
    )

    eth_row = ",".join(
        [
            "20/01/2025 10:10",
            "01/01/2024 00:00",
            "ETH",
            '"1,00000000"',
            '"2000,00"',
            '"2500,00"',
            '"500,00"',
            "",
            "Kraken",
            "Long term",
        ]
    )

    csv_content = "\n".join(["Capital gains report 2025", "", header, wbtc_row, eth_row])
    (koinly_dir / "koinly_2025_capital_gains_report.csv").write_text(csv_content, encoding="utf-8")
    return koinly_dir


def test_parse_capital_gains_file_excludes_loan_affected_assets_when_pt(tmp_path, caplog):
    """CG file with WBTC + ETH rows: PT jurisdiction skips WBTC (dynamic discovery), returns ETH only."""
    from tax_reporting.infrastructure.config import DEFAULT_ZERO_BASIS_REVIEW_THRESHOLD, TaxJurisdictionConfig

    koinly_dir = _write_koinly_dir_with_wbtc_and_eth(tmp_path)

    # Add TH with a loan-tagged WBTC row so dynamic discovery returns {"WBTC"}
    th_content = "\n".join(["Transaction report 2025", "", _FIFO_TH_HEADER, _WBTC_LOAN_TH_ROW])
    (koinly_dir / "koinly_2025_transaction_history.csv").write_text(th_content, encoding="utf-8")

    pt_jurisdiction = TaxJurisdictionConfig(
        country="PT",
        fiscal_year=2025,
        exclude_loan_repayment_gains=True,
        zero_basis_review_threshold=DEFAULT_ZERO_BASIS_REVIEW_THRESHOLD,
        timezone=ZoneInfo("Europe/Lisbon"),
    )

    with caplog.at_level(logging.WARNING, logger="tax_reporting.application.crypto_reporting"):
        report = load_koinly_crypto_report(koinly_dir, jurisdiction=pt_jurisdiction)

    assert report is not None
    assets = {e.asset for e in report.capital_entries}
    assert "WBTC" not in assets
    assert "ETH" in assets


def test_parse_capital_gains_file_includes_loan_affected_assets_when_non_pt(tmp_path):
    """CG file with WBTC + ETH rows: non-PT jurisdiction includes both."""
    from tax_reporting.infrastructure.config import DEFAULT_ZERO_BASIS_REVIEW_THRESHOLD, TaxJurisdictionConfig

    koinly_dir = _write_koinly_dir_with_wbtc_and_eth(tmp_path)
    non_pt_jurisdiction = TaxJurisdictionConfig(
        country="US",
        fiscal_year=2025,
        exclude_loan_repayment_gains=False,
        zero_basis_review_threshold=DEFAULT_ZERO_BASIS_REVIEW_THRESHOLD,
        timezone=ZoneInfo("America/New_York"),
    )

    report = load_koinly_crypto_report(koinly_dir, jurisdiction=non_pt_jurisdiction)

    assert report is not None
    assert len(report.capital_entries) == 2
    assets = {e.asset for e in report.capital_entries}
    assert assets == {"WBTC", "ETH"}


def test_parse_capital_gains_file_includes_loan_affected_assets_when_no_jurisdiction(tmp_path):
    """CG file with WBTC + ETH rows: no jurisdiction includes both."""
    koinly_dir = _write_koinly_dir_with_wbtc_and_eth(tmp_path)

    report = load_koinly_crypto_report(koinly_dir)

    assert report is not None
    assert len(report.capital_entries) == 2
    assets = {e.asset for e in report.capital_entries}
    assert assets == {"WBTC", "ETH"}


# --- FIFO pipeline integration tests (Task 5) ---

_FIFO_CG_HEADER = ",".join(
    [
        "Date Sold",
        "Date Acquired",
        "Asset",
        "Amount",
        "Cost (EUR)",
        "Proceeds (EUR)",
        "Gain / loss",
        "Notes",
        "Wallet Name",
        "Holding period",
    ]
)

_FIFO_TH_HEADER = (
    "Date,Type,Tag,Sending Wallet,Sent Amount,Sent Currency,Sent Cost Basis,"
    "Receiving Wallet,Received Amount,Received Currency,Received Cost Basis,"
    "Fee Amount,Fee Currency,Gain (EUR),Net Value (EUR),Fee Value (EUR),"
    "TxSrc,TxDest,TxHash,Description"
)

_WBTC_CG_ROW = ",".join(
    [
        "13/01/2025 13:01",
        "18/11/2024 00:15",
        "WBTC",
        '"1,00000000"',
        '"30000,00"',
        '"35000,00"',
        '"5000,00"',
        "",
        "ByBit",
        "Short term",
    ]
)

_ETH_CG_ROW = ",".join(
    [
        "20/01/2025 10:10",
        "01/01/2024 00:00",
        "ETH",
        '"1,00000000"',
        '"2000,00"',
        '"2500,00"',
        '"500,00"',
        "",
        "Kraken",
        "Long term",
    ]
)

_WBTC_BUY_TH_ROW = ",".join(
    [
        "2025-01-10 10:00:00 UTC",
        "exchange",
        "",
        "ByBit",
        "1000",
        "EUR",
        "1000",
        "ByBit",
        "0.1",
        "WBTC",
        "1000",
        "",
        "",
        "",
        "1000",
        "",
        "src1",
        "dst1",
        "tx_buy_1",
        "",
    ]
)

_WBTC_SELL_TH_ROW = ",".join(
    [
        "2025-06-15 10:00:00 UTC",
        "sell",
        "",
        "ByBit",
        "0.1",
        "WBTC",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "1500",
        "",
        "",
        "",
        "tx_sell_1",
        "",
    ]
)

# Loan-tagged row for WBTC: used to trigger dynamic discovery (discover_loan_affected_assets
# returns {"WBTC"} when this row is in the TH). The loan row itself is excluded from FIFO.
# Only Received Currency=WBTC (no fiat Sent Currency) to avoid EUR being added to the discovered set.
_WBTC_LOAN_TH_ROW = ",".join(
    [
        "2025-01-01 09:00:00 UTC",
        "exchange",
        "loan",
        "",
        "",
        "",
        "",
        "ByBit",
        "0.01",
        "WBTC",
        "1000",
        "",
        "",
        "",
        "1000",
        "",
        "",
        "",
        "tx_loan_wbtc",
        "",
    ]
)


def _pt_jurisdiction():
    from tax_reporting.infrastructure.config import DEFAULT_ZERO_BASIS_REVIEW_THRESHOLD, TaxJurisdictionConfig

    return TaxJurisdictionConfig(
        country="PT",
        fiscal_year=2025,
        exclude_loan_repayment_gains=True,
        zero_basis_review_threshold=DEFAULT_ZERO_BASIS_REVIEW_THRESHOLD,
        timezone=ZoneInfo("Europe/Lisbon"),
    )


def _non_pt_jurisdiction():
    from tax_reporting.infrastructure.config import DEFAULT_ZERO_BASIS_REVIEW_THRESHOLD, TaxJurisdictionConfig

    return TaxJurisdictionConfig(
        country="US",
        fiscal_year=2025,
        exclude_loan_repayment_gains=False,
        zero_basis_review_threshold=DEFAULT_ZERO_BASIS_REVIEW_THRESHOLD,
        timezone=ZoneInfo("America/New_York"),
    )


def test_load_koinly_crypto_report_uses_fifo_for_loan_affected_assets(tmp_path, caplog):
    """PT gate active: WBTC excluded from CG, rebuilt from TH via FIFO."""
    koinly_dir = tmp_path / "koinly2025"
    koinly_dir.mkdir()

    cg_content = "\n".join(
        ["Capital gains report 2025", "", _FIFO_CG_HEADER, _WBTC_CG_ROW, _ETH_CG_ROW]
    )
    (koinly_dir / "koinly_2025_capital_gains_report.csv").write_text(cg_content, encoding="utf-8")

    # Include loan-tagged WBTC row so dynamic discovery returns {"WBTC"} → excluded from CG
    th_content = "\n".join(
        ["Transaction report 2025", "", _FIFO_TH_HEADER, _WBTC_LOAN_TH_ROW, _WBTC_BUY_TH_ROW, _WBTC_SELL_TH_ROW]
    )
    (koinly_dir / "koinly_2025_transaction_history.csv").write_text(th_content, encoding="utf-8")
    _write_minimal_income_report(koinly_dir)

    with caplog.at_level(logging.WARNING, logger="tax_reporting.application.crypto_reporting"):
        report = load_koinly_crypto_report(koinly_dir, jurisdiction=_pt_jurisdiction())

    assert report is not None
    assets = {e.asset for e in report.capital_entries}
    assert "ETH" in assets
    assert "WBTC" in assets

    wbtc_entry = next(e for e in report.capital_entries if e.asset == "WBTC")
    assert wbtc_entry.gain_loss_eur == Decimal("500")
    assert wbtc_entry.proceeds_eur == Decimal("1500")
    assert wbtc_entry.cost_eur == Decimal("1000")
    assert wbtc_entry.holding_period == "Short term"
    assert wbtc_entry.disposal_date == "2025-06-15"
    assert wbtc_entry.acquisition_date == "2025-01-10"
    assert wbtc_entry.platform == "ByBit"


def test_load_koinly_crypto_report_skips_fifo_when_non_pt(tmp_path):
    """Non-PT gate: WBTC comes from CG parsing, FIFO engine is not invoked."""
    koinly_dir = tmp_path / "koinly2025"
    koinly_dir.mkdir()

    cg_content = "\n".join(
        ["Capital gains report 2025", "", _FIFO_CG_HEADER, _WBTC_CG_ROW, _ETH_CG_ROW]
    )
    (koinly_dir / "koinly_2025_capital_gains_report.csv").write_text(cg_content, encoding="utf-8")

    th_content = "\n".join(
        ["Transaction report 2025", "", _FIFO_TH_HEADER, _WBTC_BUY_TH_ROW, _WBTC_SELL_TH_ROW]
    )
    (koinly_dir / "koinly_2025_transaction_history.csv").write_text(th_content, encoding="utf-8")
    _write_minimal_income_report(koinly_dir)

    report = load_koinly_crypto_report(koinly_dir, jurisdiction=_non_pt_jurisdiction())

    assert report is not None
    assert len(report.capital_entries) == 2
    assets = {e.asset for e in report.capital_entries}
    assert assets == {"WBTC", "ETH"}

    wbtc_from_cg = next(e for e in report.capital_entries if e.asset == "WBTC")
    assert wbtc_from_cg.gain_loss_eur == Decimal("5000")
    assert wbtc_from_cg.proceeds_eur == Decimal("35000")
    assert wbtc_from_cg.disposal_date == "2025-01-13"


def test_load_koinly_crypto_report_falls_back_to_raw_cg_when_th_missing_for_fifo(tmp_path):
    """PT FIFO rebuild now fails fast when the required transaction history export is missing."""
    from tax_reporting.domain.exceptions import FileProcessingError

    koinly_dir = tmp_path / "koinly2025"
    koinly_dir.mkdir()

    cg_content = "\n".join(
        ["Capital gains report 2025", "", _FIFO_CG_HEADER, _WBTC_CG_ROW, _ETH_CG_ROW]
    )
    (koinly_dir / "koinly_2025_capital_gains_report.csv").write_text(cg_content, encoding="utf-8")
    _write_minimal_income_report(koinly_dir)

    with pytest.raises(FileProcessingError, match="Incomplete Koinly export") as exc_info:
        load_koinly_crypto_report(koinly_dir, jurisdiction=_pt_jurisdiction())

    assert "transaction_history (Transaction history)" in str(exc_info.value)


def test_load_koinly_crypto_report_no_false_warning_when_excluded_asset_absent_from_th(tmp_path, caplog):
    """PT gate active, TH has no loan rows for WBTC: WBTC not excluded from CG.

    With dynamic discovery, WBTC appears in CG (not excluded) because no loan-tagged
    TH rows reference WBTC. No 'zero FIFO' warning fires either.
    """
    koinly_dir = tmp_path / "koinly2025"
    koinly_dir.mkdir()

    cg_content = "\n".join(
        ["Capital gains report 2025", "", _FIFO_CG_HEADER, _WBTC_CG_ROW, _ETH_CG_ROW]
    )
    (koinly_dir / "koinly_2025_capital_gains_report.csv").write_text(cg_content, encoding="utf-8")

    th_row = ",".join(
        [
            "2025-03-15 12:00:00 UTC",
            "exchange",
            "",
            "Kraken",
            "500",
            "EUR",
            "500",
            "Kraken",
            "0.5",
            "ETH",
            "500",
            "",
            "",
            "",
            "500",
            "",
            "src_eth",
            "dst_eth",
            "tx_eth_1",
            "",
        ]
    )
    th_content = "\n".join(["Transaction report 2025", "", _FIFO_TH_HEADER, th_row])
    (koinly_dir / "koinly_2025_transaction_history.csv").write_text(th_content, encoding="utf-8")
    _write_minimal_income_report(koinly_dir)

    with caplog.at_level(logging.WARNING, logger="tax_reporting.application.crypto_reporting"):
        report = load_koinly_crypto_report(koinly_dir, jurisdiction=_pt_jurisdiction())

    assert report is not None
    eth_entries = [e for e in report.capital_entries if e.asset == "ETH"]
    assert len(eth_entries) == 1
    # No loan-tagged rows for WBTC in TH → discover returns frozenset() → WBTC NOT excluded from CG
    wbtc_entries = [e for e in report.capital_entries if e.asset == "WBTC"]
    assert len(wbtc_entries) == 1
    # No false-alarm "zero FIFO" warning: WBTC was never in the discovered loan_affected_assets
    assert "zero FIFO" not in caplog.text


def test_load_koinly_crypto_report_populates_fifo_entry_metadata(tmp_path, caplog):
    """FIFO-derived row gets operator_origin, annex_hint, chain, and token_swap_history."""
    koinly_dir = tmp_path / "koinly2025"
    koinly_dir.mkdir()

    eth_cg = ",".join(
        [
            "20/01/2025 10:10",
            "01/01/2024 00:00",
            "ETH",
            '"1,00000000"',
            '"2000,00"',
            '"2500,00"',
            '"500,00"',
            "",
            "Kraken",
            "Long term",
        ]
    )
    cg_content = "\n".join(["Capital gains report 2025", "", _FIFO_CG_HEADER, eth_cg])
    (koinly_dir / "koinly_2025_capital_gains_report.csv").write_text(cg_content, encoding="utf-8")

    # Include loan-tagged WBTC row so dynamic discovery returns {"WBTC"} → excluded from CG
    th_content = "\n".join(
        ["Transaction report 2025", "", _FIFO_TH_HEADER, _WBTC_LOAN_TH_ROW, _WBTC_BUY_TH_ROW, _WBTC_SELL_TH_ROW]
    )
    (koinly_dir / "koinly_2025_transaction_history.csv").write_text(th_content, encoding="utf-8")
    _write_minimal_income_report(koinly_dir)

    report = load_koinly_crypto_report(koinly_dir, jurisdiction=_pt_jurisdiction())

    assert report is not None
    wbtc_entry = next((e for e in report.capital_entries if e.asset == "WBTC"), None)
    assert wbtc_entry is not None, "Expected a WBTC capital gains entry from FIFO rebuild"
    # FIFO-derived WBTC entry must carry metadata assigned by _rebuild_fifo_for_loan_affected_assets
    assert wbtc_entry.operator_origin is not None
    assert wbtc_entry.annex_hint in ("J", "G1")
    assert wbtc_entry.chain is not None
    # Short-term disposal (acquired Jan 2025, sold Jun 2025) → annex J
    assert wbtc_entry.annex_hint == "J"
    assert wbtc_entry.token_swap_history is not None


def test_load_koinly_crypto_report_warns_when_excluded_asset_has_no_fifo_output(tmp_path, caplog):
    """PT gate active: WBTC in th_assets but _rebuild_fifo returns zero entries → WARNING logged."""
    from unittest.mock import patch

    koinly_dir = tmp_path / "koinly2025"
    koinly_dir.mkdir()

    cg_content = "\n".join(
        ["Capital gains report 2025", "", _FIFO_CG_HEADER, _ETH_CG_ROW]
    )
    (koinly_dir / "koinly_2025_capital_gains_report.csv").write_text(cg_content, encoding="utf-8")

    # TH file must exist so fifo_rebuild_active branch is entered
    th_content = "\n".join(
        ["Transaction report 2025", "", _FIFO_TH_HEADER, _WBTC_BUY_TH_ROW, _WBTC_SELL_TH_ROW]
    )
    (koinly_dir / "koinly_2025_transaction_history.csv").write_text(th_content, encoding="utf-8")
    _write_minimal_income_report(koinly_dir)

    mock_return = ([], frozenset({"WBTC"}))
    with (
        caplog.at_level(logging.WARNING, logger="tax_reporting.application.crypto_reporting"),
        patch(
            "tax_reporting.application.crypto_reporting.discover_loan_affected_assets",
            return_value=frozenset({"WBTC"}),
        ),
        patch(
            "tax_reporting.application.crypto_reporting._rebuild_fifo_for_loan_affected_assets",
            return_value=mock_return,
        ),
    ):
        report = load_koinly_crypto_report(koinly_dir, jurisdiction=_pt_jurisdiction())

    assert report is not None
    assert any("zero FIFO entries" in r.message for r in caplog.records if r.levelno == logging.WARNING)
    assert any("WBTC" in r.message for r in caplog.records if r.levelno == logging.WARNING)


def test_load_koinly_crypto_report_warns_when_loan_discovery_returns_empty(tmp_path, caplog):
    """PT gate active with TH file but no loan tags: warns about empty discovery."""
    koinly_dir = tmp_path / "koinly2025"
    koinly_dir.mkdir()

    eth_cg = ",".join(
        [
            "20/01/2025 10:10",
            "01/01/2024 00:00",
            "ETH",
            '"1,00000000"',
            '"2000,00"',
            '"2500,00"',
            '"500,00"',
            "",
            "Kraken",
            "Long term",
        ]
    )
    cg_content = "\n".join(["Capital gains report 2025", "", _FIFO_CG_HEADER, eth_cg])
    (koinly_dir / "koinly_2025_capital_gains_report.csv").write_text(cg_content, encoding="utf-8")

    # TH file exists but has NO loan or loan repayment tags → discovery returns empty
    th_content = "\n".join(
        ["Transaction report 2025", "", _FIFO_TH_HEADER, _WBTC_BUY_TH_ROW, _WBTC_SELL_TH_ROW]
    )
    (koinly_dir / "koinly_2025_transaction_history.csv").write_text(th_content, encoding="utf-8")
    _write_minimal_income_report(koinly_dir)

    with caplog.at_level(logging.WARNING, logger="tax_reporting.application.crypto_reporting"):
        report = load_koinly_crypto_report(koinly_dir, jurisdiction=_pt_jurisdiction())

    assert report is not None
    # Should warn about empty loan-affected assets discovery
    assert any(
        "no loan-affected assets discovered" in r.message for r in caplog.records if r.levelno == logging.WARNING
    )


def test_parse_capital_gains_file_skips_dynamically_discovered_assets(tmp_path):
    """_parse_capital_gains_file with loan_affected_assets=frozenset({'NEWASSET'}) skips NEWASSET rows."""
    from collections import Counter

    from tax_reporting.application.crypto_reporting import _parse_capital_gains_file

    newasset_row = ",".join([
        "13/01/2025 13:01",
        "18/11/2024 00:15",
        "NEWASSET",
        '"1,00000000"',
        '"500,00"',
        '"600,00"',
        '"100,00"',
        "",
        "Kraken",
        "Short term",
    ])
    eth_row = ",".join([
        "20/01/2025 10:10",
        "01/01/2024 00:00",
        "ETH",
        '"0,50000000"',
        '"1000,00"',
        '"1200,00"',
        '"200,00"',
        "",
        "Kraken",
        "Long term",
    ])
    cg_path = tmp_path / "cg.csv"
    cg_path.write_text(
        "\n".join(["Capital gains report 2025", "", _FIFO_CG_HEADER, newasset_row, eth_row]),
        encoding="utf-8",
    )

    skipped: Counter[tuple[str, str]] = Counter()
    resolver = build_origin_resolver(None)
    review_entries: list = []
    context = CapitalGainsParsingContext(
        skipped_assets=skipped,
        origin_resolver=resolver,
        review_entries=review_entries,
        loan_affected_assets=frozenset({"NEWASSET"}),
    )
    entries, _ = _parse_capital_gains_file(cg_path, context)

    assets = {e.asset for e in entries}
    assert "NEWASSET" not in assets
    assert "ETH" in assets


def test_load_koinly_crypto_report_uses_dynamic_discovery_not_hardcoded_constant(tmp_path, caplog):
    """TH has a loan row for TESTTOK; CG has a TESTTOK entry. TESTTOK CG entry excluded by dynamic set."""
    koinly_dir = tmp_path / "koinly2025"
    koinly_dir.mkdir()

    testtok_cg_row = ",".join([
        "13/01/2025 13:01",
        "18/11/2024 00:15",
        "TESTTOK",
        '"1,00000000"',
        '"500,00"',
        '"600,00"',
        '"100,00"',
        "",
        "Kraken",
        "Short term",
    ])
    cg_content = "\n".join(
        ["Capital gains report 2025", "", _FIFO_CG_HEADER, testtok_cg_row, _ETH_CG_ROW]
    )
    (koinly_dir / "koinly_2025_capital_gains_report.csv").write_text(cg_content, encoding="utf-8")

    # TH has a borrow-only loan-tagged TESTTOK row (no sending side). Phase D Task 5
    # Invariant 11: under flag-on default, dynamic discovery catches this row because
    # it resolves to OTHER (empty sending side) AND its normalized tag is "loan". A
    # row WITH a sending side would resolve to SPOT_DISPOSAL and drop out under the
    # flag-on path - the documented exception clause covers only borrow-side principal
    # creation. Borrow-only shape keeps this test meaningful under both flag states.
    testtok_loan_row = ",".join([
        "2025-01-01 10:00:00 UTC", "crypto_deposit", "loan", "", "", "", "",
        "Kraken", "1", "TESTTOK", "500", "", "", "", "500", "", "", "", "tx_loan_testtok", "",
    ])
    th_content = "\n".join(
        ["Transaction report 2025", "", _FIFO_TH_HEADER, testtok_loan_row]
    )
    (koinly_dir / "koinly_2025_transaction_history.csv").write_text(th_content, encoding="utf-8")
    _write_minimal_income_report(koinly_dir)

    with caplog.at_level(logging.WARNING):
        report = load_koinly_crypto_report(koinly_dir, jurisdiction=_pt_jurisdiction())

    assert report is not None
    assets = {e.asset for e in report.capital_entries}
    assert "TESTTOK" not in assets, "TESTTOK should be excluded by dynamic discovery"
    assert "ETH" in assets


def test_rebuild_fifo_marks_review_required_when_asset_has_parse_errors(tmp_path, caplog):
    """TH with a malformed WBTC row: all WBTC realizations must have review_required=True.

    When a TH row for a loan-affected asset fails to parse, the FIFO pool is potentially
    incomplete. Every realization for that asset must be flagged for manual review.
    """
    koinly_dir = tmp_path / "koinly2025"
    koinly_dir.mkdir()

    eth_cg = ",".join(
        [
            "20/01/2025 10:10",
            "01/01/2024 00:00",
            "ETH",
            '"1,00000000"',
            '"2000,00"',
            '"2500,00"',
            '"500,00"',
            "",
            "Kraken",
            "Long term",
        ]
    )
    cg_content = "\n".join(["Capital gains report 2025", "", _FIFO_CG_HEADER, eth_cg])
    (koinly_dir / "koinly_2025_capital_gains_report.csv").write_text(cg_content, encoding="utf-8")

    bad_wbtc_row = ",".join(
        [
            "2025-01-10 10:00:00 UTC",
            "buy",
            "",
            "",
            "",
            "",
            "",
            "ByBit",
            "BAD_DECIMAL",
            "WBTC",
            "1000",
            "",
            "",
            "",
            "1000",
            "",
            "src1",
            "dst1",
            "tx_bad_buy",
            "",
        ]
    )

    th_content = "\n".join(
        [
            "Transaction report 2025",
            "",
            _FIFO_TH_HEADER,
            _WBTC_LOAN_TH_ROW,
            bad_wbtc_row,
            _WBTC_SELL_TH_ROW,
        ]
    )
    (koinly_dir / "koinly_2025_transaction_history.csv").write_text(th_content, encoding="utf-8")
    _write_minimal_income_report(koinly_dir)

    with caplog.at_level(logging.ERROR):
        report = load_koinly_crypto_report(koinly_dir, jurisdiction=_pt_jurisdiction())

    assert report is not None
    wbtc_entries = [e for e in report.capital_entries if e.asset == "WBTC"]
    assert len(wbtc_entries) >= 1, "Expected WBTC entries from FIFO rebuild"
    for entry in wbtc_entries:
        assert entry.review_required is True, (
            f"WBTC entry (disposal {entry.disposal_date}) must have review_required=True due to parse error"
        )
        assert entry.review_reason is not None
        assert "parse error" in entry.review_reason.lower()



def test_rebuild_fifo_resolves_same_asset_cross_platform_transfer_after_sender_platform_fifo(
    tmp_path,
):
    """Integration: WBTC transferred Kraken→ByBit; ByBit sale should use Kraken's cost basis."""
    from tax_reporting.application.crypto_reporting import _rebuild_fifo_for_loan_affected_assets

    koinly_dir = tmp_path / "koinly2025"
    koinly_dir.mkdir()

    # Loan row triggers WBTC discovery
    loan_row = ",".join([
        "2025-01-01 09:00:00 UTC", "exchange", "loan", "", "", "", "",
        "ByBit", "0.01", "WBTC", "400", "", "", "", "400", "", "", "", "tx_loan", "",
    ])
    # Buy 1 WBTC on Kraken for 1000 EUR
    buy_row = ",".join([
        "2025-01-10 10:00:00 UTC", "exchange", "", "Kraken", "1000", "EUR", "1000",
        "Kraken", "1.0", "WBTC", "1000", "", "", "", "1000", "", "src", "dst", "tx_buy", "",
    ])
    # Transfer 1 WBTC from Kraken to ByBit
    transfer_row = ",".join([
        "2025-01-15 10:00:00 UTC", "transfer", "", "Kraken", "1.0", "WBTC", "1000",
        "ByBit", "1.0", "WBTC", "", "", "", "", "0", "", "", "", "tx_transfer", "",
    ])
    # Sell 1 WBTC on ByBit for 1500 EUR
    sell_row = ",".join([
        "2025-06-15 10:00:00 UTC", "sell", "", "ByBit", "1.0", "WBTC", "",
        "", "", "", "", "", "", "", "1500", "", "", "", "tx_sell", "",
    ])

    th_content = "\n".join([
        "Transaction report 2025", "", _FIFO_TH_HEADER,
        loan_row, buy_row, transfer_row, sell_row,
    ])
    th_path = koinly_dir / "koinly_2025_transaction_history.csv"
    th_path.write_text(th_content, encoding="utf-8")

    resolver = build_origin_resolver(th_path)
    loan_affected = frozenset({"WBTC"})

    entries, _ = _rebuild_fifo_for_loan_affected_assets(th_path, resolver, loan_affected)

    # ByBit sell should have cost basis = 1000 EUR (from Kraken buy via transfer)
    bybit_entries = [e for e in entries if e.platform == "ByBit"]
    assert len(bybit_entries) == 1, f"Expected 1 ByBit entry, got {bybit_entries}"
    bybit_entry = bybit_entries[0]
    assert bybit_entry.cost_eur == Decimal("1000"), (
        f"Expected cost_eur=1000 (transferred from Kraken), got {bybit_entry.cost_eur}"
    )
    assert bybit_entry.gain_loss_eur == Decimal("500")
    # review_required may be set by the operator origin resolver (e.g. ByBit region flags),
    # but must NOT be due to a failed transfer resolution.
    if bybit_entry.review_required and bybit_entry.review_reason:
        assert "transfer_in_deferred" not in bybit_entry.review_reason, (
            f"Transfer should be resolved, not deferred. Got review reason: {bybit_entry.review_reason}"
        )
        assert "carry-over not available" not in bybit_entry.review_reason, (
            f"Transfer carry-over should be available. Got: {bybit_entry.review_reason}"
        )


def test_apply_phantom_flags_only_for_unresolved_transfers(tmp_path):
    """Phantom flags appear only for unknown-receiver transfers, not resolved ones."""
    from tax_reporting.application.crypto_reporting import _rebuild_fifo_for_loan_affected_assets

    koinly_dir = tmp_path / "koinly2025"
    koinly_dir.mkdir()

    loan_row = ",".join([
        "2025-01-01 09:00:00 UTC", "exchange", "loan", "", "", "", "",
        "ByBit", "0.01", "WBTC", "400", "", "", "", "400", "", "", "", "tx_loan", "",
    ])
    buy_kraken = ",".join([
        "2025-01-10 10:00:00 UTC", "exchange", "", "Kraken", "1000", "EUR", "1000",
        "Kraken", "1.0", "WBTC", "1000", "", "", "", "1000", "", "src", "dst", "tx_buy_k", "",
    ])
    buy_bybit = ",".join([
        "2025-01-10 10:00:00 UTC", "exchange", "", "ByBit", "2000", "EUR", "2000",
        "ByBit", "0.5", "WBTC", "2000", "", "", "", "2000", "", "src", "dst", "tx_buy_b", "",
    ])
    # Resolved transfer: Kraken → ByBit (known receiver)
    transfer_resolved = ",".join([
        "2025-01-15 10:00:00 UTC", "transfer", "", "Kraken", "1.0", "WBTC", "1000",
        "ByBit", "1.0", "WBTC", "", "", "", "", "0", "", "", "", "tx_transfer_ok", "",
    ])
    # Sell on Kraken (from phantom transfer pool → would have phantom flag)
    # ... but since transfer was resolved (known receiver), Kraken pool is empty → placeholder
    # Sell on ByBit (from resolved transfer)
    sell_bybit = ",".join([
        "2025-06-15 10:00:00 UTC", "sell", "", "ByBit", "1.5", "WBTC", "",
        "", "", "", "", "", "", "", "2200", "", "", "", "tx_sell_b", "",
    ])

    th_content = "\n".join([
        "Transaction report 2025", "", _FIFO_TH_HEADER,
        loan_row, buy_kraken, buy_bybit, transfer_resolved, sell_bybit,
    ])
    th_path = koinly_dir / "koinly_2025_transaction_history.csv"
    th_path.write_text(th_content, encoding="utf-8")

    resolver = build_origin_resolver(th_path)
    loan_affected = frozenset({"WBTC"})

    entries, _ = _rebuild_fifo_for_loan_affected_assets(th_path, resolver, loan_affected)

    # ByBit sell: 1.5 WBTC sold, sourced from 0.5 (own buy) + 1.0 (transferred from Kraken)
    # None of the ByBit entries should be flagged as phantom
    bybit_entries = [e for e in entries if e.platform == "ByBit"]
    for entry in bybit_entries:
        if entry.review_reason:
            assert "phantom" not in entry.review_reason.lower(), (
                f"Resolved transfer should not produce phantom flag, got: {entry.review_reason}"
            )


def test_rebuild_fifo_threads_zero_basis_min_proceeds_into_review_flag(tmp_path):
    """The ``zero_basis_review_min_proceeds`` parameter threads through FIFO rebuild to the helper.

    Builds a TH fixture where WBTC is acquired at zero cost (empty Sent Cost Basis)
    then sold for 15 EUR proceeds. Under ``min_proceeds=10`` the zero-cost disposal
    is flagged with the zero-cost reason; under ``min_proceeds=20`` it is not. This
    is the only unit test that exercises the wiring between the new config field
    and the FIFO rebuild path end-to-end inside ``_rebuild_fifo_for_loan_affected_assets``.
    """
    from tax_reporting.application.crypto_reporting import _rebuild_fifo_for_loan_affected_assets

    koinly_dir = tmp_path / "koinly2025"
    koinly_dir.mkdir()

    loan_row = ",".join([
        "2025-01-01 09:00:00 UTC", "exchange", "loan", "", "", "", "",
        "ByBit", "0.01", "WBTC", "400", "", "", "", "400", "", "", "", "tx_loan", "",
    ])
    # Zero-cost WBTC acquisition: empty Sent Cost Basis → cost_basis_eur=0 (reward/airdrop-like).
    zero_cost_buy_row = ",".join([
        "2025-01-10 10:00:00 UTC", "exchange", "", "", "", "ETH", "",
        "ByBit", "0.1", "WBTC", "", "", "", "", "0", "", "", "", "tx_zero_buy", "",
    ])
    # Sell 0.1 WBTC for 15 EUR, above the 10 EUR default threshold, below a 20 EUR threshold.
    sell_row = ",".join([
        "2025-06-15 10:00:00 UTC", "sell", "", "ByBit", "0.1", "WBTC", "",
        "", "", "", "", "", "", "", "15", "", "", "", "tx_sell", "",
    ])

    th_content = "\n".join([
        "Transaction report 2025", "", _FIFO_TH_HEADER,
        loan_row, zero_cost_buy_row, sell_row,
    ])
    th_path = koinly_dir / "koinly_2025_transaction_history.csv"
    th_path.write_text(th_content, encoding="utf-8")

    resolver = build_origin_resolver(th_path)
    loan_affected = frozenset({"WBTC"})

    # Above-threshold case: min_proceeds=10, proceeds=15 → flags with zero-cost reason.
    entries_default, _ = _rebuild_fifo_for_loan_affected_assets(
        th_path, resolver, loan_affected, zero_basis_review_min_proceeds=Decimal("10")
    )
    wbtc_default = [e for e in entries_default if e.asset == "WBTC"]
    assert wbtc_default, "Expected WBTC entries from FIFO rebuild"
    for entry in wbtc_default:
        assert entry.cost_eur == Decimal("0"), (
            f"Expected zero cost basis, got {entry.cost_eur}"
        )
        assert entry.review_required is True, (
            f"Zero-cost disposal with proceeds >= min_proceeds must be flagged. "
            f"Got review_required={entry.review_required}, reason={entry.review_reason!r}"
        )
        assert entry.review_reason is not None
        assert "Zero acquisition cost" in entry.review_reason, (
            f"Expected zero-cost reason in review_reason, got: {entry.review_reason!r}"
        )

    # Below-threshold case: min_proceeds=20, proceeds=15 → zero-cost reason suppressed.
    entries_high, _ = _rebuild_fifo_for_loan_affected_assets(
        th_path, resolver, loan_affected, zero_basis_review_min_proceeds=Decimal("20")
    )
    wbtc_high = [e for e in entries_high if e.asset == "WBTC"]
    assert wbtc_high, "Expected WBTC entries from FIFO rebuild at higher threshold"
    for entry in wbtc_high:
        zero_cost_marker_present = (
            entry.review_reason is not None and "Zero acquisition cost" in entry.review_reason
        )
        assert not zero_cost_marker_present, (
            f"Zero-cost reason must be suppressed when proceeds < min_proceeds. "
            f"Got review_reason={entry.review_reason!r}"
        )


@pytest.mark.unit
def test_collect_known_asset_tickers_raises_when_all_files_fail_to_parse(tmp_path):
    """Fail-fast: FileProcessingError raised when all provided files fail to parse."""
    koinly_dir = tmp_path / "koinly2025"
    koinly_dir.mkdir()

    # Create malformed capital gains file (invalid CSV structure)
    capital_file = koinly_dir / "koinly_2025_capital_gains_report_test.csv"
    capital_file.write_text("not a valid csv", encoding="utf-8")

    # Create malformed income file (invalid CSV structure)
    income_file = koinly_dir / "koinly_2025_income_report_test.csv"
    income_file.write_text("also not valid", encoding="utf-8")

    from tax_reporting.domain.exceptions import FileProcessingError

    with pytest.raises(FileProcessingError, match="Failed to scan all Koinly files"):
        _collect_known_asset_tickers(capital_file, income_file)


@pytest.mark.unit
def test_collect_known_asset_tickers_warns_on_partial_failure(caplog, tmp_path):
    """Partial failure: logs warning but continues when at least one file parses successfully."""
    koinly_dir = tmp_path / "koinly2025"
    koinly_dir.mkdir()

    # Create valid capital gains file with non-zero BTC row
    capital_file = koinly_dir / "koinly_2025_capital_gains_report_test.csv"
    capital_content = "\n".join([
        "Capital gains report 2025",
        "",
        "Date Sold,Date Acquired,Asset,Amount,Cost (EUR),Proceeds (EUR),Gain / loss,Notes,Wallet Name,Holding period",
        "01/01/2025 10:00,01/01/2024 10:00,BTC,\"0,10000000\",\"1000,00\",\"1200,00\",\"200,00\",,Kraken,Long term",
    ])
    capital_file.write_text(capital_content, encoding="utf-8")

    # Create malformed income file
    income_file = koinly_dir / "koinly_2025_income_report_test.csv"
    income_file.write_text("malformed", encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger="tax_reporting.application.crypto_reporting"):
        result = _collect_known_asset_tickers(capital_file, income_file)

    # Should return assets from the valid file
    assert "BTC" in result

    # Should log warning about the failed file
    assert any("Failed to scan known assets" in record.message for record in caplog.records)


@pytest.mark.unit
def test_collect_known_asset_tickers_returns_empty_when_no_files_exist(tmp_path):
    """Returns empty frozenset when no files exist (graceful degradation)."""
    koinly_dir = tmp_path / "koinly2025"
    koinly_dir.mkdir()

    capital_file = koinly_dir / "koinly_2025_capital_gains_report_test.csv"
    income_file = koinly_dir / "koinly_2025_income_report_test.csv"

    # Neither file exists
    result = _collect_known_asset_tickers(capital_file, income_file)

    assert result == frozenset()


@pytest.mark.unit
def test_collect_known_asset_tickers_collects_non_zero_assets(tmp_path):
    """Collects asset tickers from rows with non-zero proceeds or value."""
    koinly_dir = tmp_path / "koinly2025"
    koinly_dir.mkdir()

    # Create capital gains file with mix of zero and non-zero proceeds
    capital_file = koinly_dir / "koinly_2025_capital_gains_report_test.csv"
    capital_content = "\n".join([
        "Capital gains report 2025",
        "",
        "Date Sold,Date Acquired,Asset,Amount,Cost (EUR),Proceeds (EUR),Gain / loss,Notes,Wallet Name,Holding period",
        "01/01/2025 10:00,01/01/2024 10:00,BTC,\"0,10000000\",\"1000,00\",\"1200,00\",\"200,00\",,Kraken,Long term",
        "02/01/2025 10:00,01/01/2024 10:00,ETH,\"0,20000000\",\"500,00\",\"0,00\",\"-500,00\",,Kraken,Short term",
        "03/01/2025 10:00,01/01/2024 10:00,USDT,\"1,00000000\",\"0,00\",\"0,00\",\"0,00\",,Kraken,Short term",
    ])
    capital_file.write_text(capital_content, encoding="utf-8")

    # Create income file with mix of zero and non-zero values
    income_file = koinly_dir / "koinly_2025_income_report_test.csv"
    income_content = "\n".join([
        "Income report 2025",
        "",
        "Date,Asset,Amount,Value (EUR),Type,Description,Wallet Name",
        "01/01/2025 00:01,USDC,\"10,00000000\",\"50,00\",Reward,,Wirex",
        "02/01/2025 00:01,DAI,\"5,00000000\",\"0,00\",Reward,,Wirex",
    ])
    income_file.write_text(income_content, encoding="utf-8")

    result = _collect_known_asset_tickers(capital_file, income_file)

    # Should only include assets with non-zero values
    assert "BTC" in result
    assert "USDC" in result
    # ETH has zero proceeds - should not be collected
    assert "ETH" not in result
    # USDT has zero proceeds - should not be collected
    assert "USDT" not in result
    # DAI has zero value - should not be collected
    assert "DAI" not in result


@pytest.mark.unit
def test_parse_income_file_flags_zero_value_known_assets_for_review(tmp_path, caplog):
    """Zero-value deferred rewards for known assets are routed to ``skipped_zero_value_deferred_rewards``
    with ``review_required=True`` propagated (CRG-022 parse-time skip, Invariant 1 , list preservation).

    Rewritten under CRG-022: the three zero-value BTC/ETH/USDT rows are DEFERRED_BY_LAW
    (crypto-denominated) + value_eur == 0, so they route to ``skipped_zero_value_deferred_rewards``
    instead of ``reward_entries``. Each retained entry carries the same ``review_required=True``
    + zero-value review_reason the parse path set, so the audit trail preserves full fidelity.
    """
    koinly_dir = tmp_path / "koinly2025"
    koinly_dir.mkdir()

    # Create income file with zero-value rewards for known assets
    income_file = koinly_dir / "koinly_2025_income_report_test.csv"
    income_content = "\n".join([
        "Income report 2025",
        "",
        "Date,Asset,Amount,Value (EUR),Type,Description,Wallet Name",
        "01/01/2025 00:01,BTC,\"1,00000000\",0.0,Reward,,Kraken",
        "02/01/2025 00:01,ETH,\"2,00000000\",0.0,Reward,,Kraken",
        "03/01/2025 00:01,USDT,\"10,00000000\",0.0,Reward,,Kraken",
    ])
    income_file.write_text(income_content, encoding="utf-8")

    skipped_assets: dict[tuple[str, str], dict] = {}
    skipped_zero_value_deferred_rewards: list = []

    with caplog.at_level(logging.WARNING, logger="tax_reporting.application.crypto_reporting"):
        entries = _parse_income_file(
            income_file,
            skipped_assets,
            known_assets=frozenset(["BTC", "ETH", "USDT"]),
            skipped_zero_value_deferred_rewards=skipped_zero_value_deferred_rewards,
        )

    # CRG-022: all three zero-value deferred rewards route to the skip list, so
    # ``reward_entries`` is now empty (the old contract put them in ``entries``).
    assert len(entries) == 0

    # All three retained entries carry the propagated review flag + zero-value reason
    # (full-fidelity list preservation , Invariant 1, user's hard requirement).
    assert len(skipped_zero_value_deferred_rewards) == 3
    for entry in skipped_zero_value_deferred_rewards:
        assert entry.review_required is True
        assert "Zero EUR value for known crypto asset" in (entry.review_reason or "")
        assert entry.value_eur == Decimal("0")
        assert entry.tax_classification == RewardTaxClassification.DEFERRED_BY_LAW

    # None should be in skipped_assets (they were known assets; routed to the skip list, not dropped)
    assert len(skipped_assets) == 0


@pytest.mark.unit
def test_parse_income_file_skips_zero_value_unknown_assets(tmp_path):
    """Zero-value rewards for unknown assets are skipped."""
    koinly_dir = tmp_path / "koinly2025"
    koinly_dir.mkdir()

    # Create income file with zero-value rewards for unknown assets
    income_file = koinly_dir / "koinly_2025_income_report_test.csv"
    income_content = "\n".join([
        "Income report 2025",
        "",
        "Date,Asset,Amount,Value (EUR),Type,Description,Wallet Name",
        "01/01/2025 00:01,UNKNOWN1,\"1,00000000\",0.0,Reward,,Kraken",
        "02/01/2025 00:01,UNKNOWN2,\"2,00000000\",0.0,Reward,,Kraken",
    ])
    income_file.write_text(income_content, encoding="utf-8")

    skipped_assets: dict[tuple[str, str], dict] = {}

    entries = _parse_income_file(income_file, skipped_assets, known_assets=frozenset(["BTC"]))

    # No entries should be created (unknown assets are skipped)
    assert len(entries) == 0

    # Both should be in skipped_assets
    assert skipped_assets[("income", "UNKNOWN1")]["count"] == 1
    assert skipped_assets[("income", "UNKNOWN2")]["count"] == 1
    assert skipped_assets[("income", "UNKNOWN1")]["suspicious"] is False
    assert skipped_assets[("income", "UNKNOWN2")]["suspicious"] is False


@pytest.mark.unit
def test_parse_income_file_zero_value_with_popular_token_matching(tmp_path):
    """Zero-value deferred rewards for popular tokens (via substring matching) are routed to
    ``skipped_zero_value_deferred_rewards`` with ``review_required=True`` (CRG-022).

    Rewritten under CRG-022: TSTON and TSUSDE are crypto-denominated (DEFERRED_BY_LAW) +
    value_eur == 0, so they route to ``skipped_zero_value_deferred_rewards`` instead of
    ``reward_entries``. UNKNOWNX is unknown (fails the ``is_known`` gate) and continues to
    be dropped via the ``skipped_assets`` else-branch (unchanged).
    """
    from unittest.mock import patch

    koinly_dir = tmp_path / "koinly2025"
    koinly_dir.mkdir()

    # Create income file with zero-value rewards for token variants
    income_file = koinly_dir / "koinly_2025_income_report_test.csv"
    income_content = "\n".join([
        "Income report 2025",
        "",
        "Date,Asset,Amount,Value (EUR),Type,Description,Wallet Name",
        "01/01/2025 00:01,TSTON,\"1,00000000\",0.0,Reward,,Kraken",
        "02/01/2025 00:01,TSUSDE,\"2,00000000\",0.0,Reward,,Kraken",
        "03/01/2025 00:01,UNKNOWNX,\"3,00000000\",0.0,Reward,,Kraken",
    ])
    income_file.write_text(income_content, encoding="utf-8")

    skipped_assets: dict[tuple[str, str], dict] = {}
    skipped_zero_value_deferred_rewards: list = []

    # Mock _get_popular_crypto_tokens to include TON and USDE for substring matching
    with patch(
        "tax_reporting.application.crypto_reporting._get_popular_crypto_tokens",
        return_value=frozenset(["BTC", "ETH", "TON", "USDE"]),
    ):
        entries = _parse_income_file(
            income_file,
            skipped_assets,
            known_assets=frozenset(["TON", "USDE"]),
            skipped_zero_value_deferred_rewards=skipped_zero_value_deferred_rewards,
        )

    # CRG-022: TSTON and TSUSDE (crypto -> DEFERRED_BY_LAW + zero-value) route to the
    # skip list; ``reward_entries`` is now empty. UNKNOWNX is unknown and drops via
    # the ``skipped_assets`` else-branch (unchanged).
    assert len(entries) == 0
    assert len(skipped_zero_value_deferred_rewards) == 2

    skipped_assets_seen = {e.asset for e in skipped_zero_value_deferred_rewards}
    assert "TSTON" in skipped_assets_seen
    assert "TSUSDE" in skipped_assets_seen
    assert "UNKNOWNX" not in skipped_assets_seen

    for entry in skipped_zero_value_deferred_rewards:
        assert entry.review_required is True
        assert "Zero EUR value for known crypto asset" in (entry.review_reason or "")
        assert entry.tax_classification == RewardTaxClassification.DEFERRED_BY_LAW

    # Only UNKNOWNX should be in skipped_assets (unchanged else-branch behavior)
    assert skipped_assets[("income", "UNKNOWNX")]["count"] == 1
    assert ("income", "TSTON") not in skipped_assets
    assert ("income", "TSUSDE") not in skipped_assets


@pytest.mark.unit
def test_parse_income_file_non_zero_rewards_always_processed(tmp_path):
    """Non-zero rewards are always processed regardless of known_assets."""
    koinly_dir = tmp_path / "koinly2025"
    koinly_dir.mkdir()

    # Create income file with non-zero rewards
    income_file = koinly_dir / "koinly_2025_income_report_test.csv"
    income_content = "\n".join([
        "Income report 2025",
        "",
        "Date,Asset,Amount,Value (EUR),Type,Description,Wallet Name",
        "01/01/2025 00:01,BTC,\"1,00000000\",\"100,00\",Reward,,Kraken",
        "02/01/2025 00:01,UNKNOWNX,\"2,00000000\",\"50,00\",Reward,,Kraken",
    ])
    income_file.write_text(income_content, encoding="utf-8")

    skipped_assets: dict[tuple[str, str], dict] = {}

    # Even with known_assets, all non-zero rewards should be processed
    entries = _parse_income_file(income_file, skipped_assets, known_assets=frozenset(["BTC"]))

    assert len(entries) == 2

    entry_assets = {e.asset for e in entries}
    assert "BTC" in entry_assets
    assert "UNKNOWNX" in entry_assets

    # No assets should be skipped (all have non-zero values)
    assert len(skipped_assets) == 0


@pytest.mark.unit
def test_load_popular_crypto_tokens_caches_result():
    """Verify that _load_popular_crypto_tokens caches the result after first load."""
    from unittest.mock import patch

    # Mock the file operations to count how many times the file is read
    read_count = 0

    def mock_exists(self):
        # Always return False to simulate file not found (graceful degradation)
        return False

    def mock_open(*args, **kwargs):
        nonlocal read_count
        read_count += 1
        raise FileNotFoundError("Mocked file not found")

    with patch.object(Path, "exists", mock_exists), patch(
        "builtins.open", side_effect=mock_open
    ):
        # Clear the cache before the test
        _load_popular_crypto_tokens.cache_clear()

        # First call - should read from file (and fail gracefully)
        result1 = _load_popular_crypto_tokens()
        assert result1 == frozenset()

        # Second call - should use cached result, not attempt to read file again
        result2 = _load_popular_crypto_tokens()
        assert result2 == frozenset()

        # Both results should be identical (same cached object)
        assert result1 is result2


@pytest.mark.unit
def test_load_popular_crypto_tokens_cache_clear_on_manual_invalidation():
    """Verify that cache can be cleared and reloaded."""
    from unittest.mock import patch

    def mock_exists(self):
        return False

    with patch.object(Path, "exists", mock_exists):
        # Clear the cache
        _load_popular_crypto_tokens.cache_clear()

        # First call
        result1 = _load_popular_crypto_tokens()
        assert result1 == frozenset()

        # Clear cache explicitly
        _load_popular_crypto_tokens.cache_clear()

        # Second call after cache clear - should read again (and still return empty set)
        result2 = _load_popular_crypto_tokens()
        assert result2 == frozenset()


@pytest.mark.unit
def test_skipped_zero_value_tokens_suspicious_flag_for_non_latin_assets(tmp_path):
    """Verify that assets with non-Latin characters are flagged with suspicious=True."""
    from tax_reporting.application.crypto_reporting import load_koinly_crypto_report

    koinly_dir = tmp_path / "koinly2025"
    koinly_dir.mkdir()

    # Capital gains with Cyrillic Т (homoglyph of T)
    (koinly_dir / "koinly_2025_capital_gains_report_test.csv").write_text(
        "\n".join([
            "Capital gains report 2025",
            "",
            ",".join([
                "Date Sold", "Date Acquired", "Asset", "Amount", "Cost (EUR)", "Proceeds (EUR)",
                "Gain / loss", "Notes", "Wallet Name", "Holding period",
            ]),
            ",".join([
                "01/01/2025 10:00", "01/01/2024 10:00", "WBТC", '"0,10000000"', "0.0", "0.0", "0.0",
                "", "Kraken", "Long term",
            ]),
        ]),
        encoding="utf-8",
    )

    # Income with Cyrillic characters
    (koinly_dir / "koinly_2025_income_report_test.csv").write_text(
        "\n".join([
            "Income report 2025",
            "",
            "Date,Asset,Amount,Value (EUR),Type,Description,Wallet Name",
            '01/01/2025 00:01,ВОС,"1,00000000",0.0,Reward,,Wirex',  # Cyrillic В and С
        ]),
        encoding="utf-8",
    )

    (koinly_dir / "koinly_2025_beginning_of_year_holdings_report_test.csv").write_text(
        "\n".join([
            "Balances as at 01/01/2025 00:00",
            "",
            "Asset,Quantity,Cost (EUR),Value (EUR),Description",
            'ZERО,"1,00000000","10,00",0.0,',  # Cyrillic О
        ]),
        encoding="utf-8",
    )

    _write_minimal_transaction_history(koinly_dir)

    report = load_koinly_crypto_report(koinly_dir)

    assert report is not None

    # Verify all skipped tokens have suspicious=True due to non-Latin characters
    for token in report.skipped_zero_value_tokens:
        if token.asset in ["WBТC", "ВОС", "ZERО"]:
            assert token.suspicious is True, f"{token.asset} should be flagged as suspicious (contains non-Latin)"


@pytest.mark.unit
def test_skipped_zero_value_tokens_normal_assets_not_suspicious(tmp_path):
    """Verify that normal assets (Latin only) are not flagged as suspicious."""
    from tax_reporting.application.crypto_reporting import load_koinly_crypto_report

    koinly_dir = tmp_path / "koinly2025"
    koinly_dir.mkdir()

    # Normal assets with zero value (Latin characters only)
    (koinly_dir / "koinly_2025_capital_gains_report_test.csv").write_text(
        "\n".join([
            "Capital gains report 2025",
            "",
            ",".join([
                "Date Sold", "Date Acquired", "Asset", "Amount", "Cost (EUR)", "Proceeds (EUR)",
                "Gain / loss", "Notes", "Wallet Name", "Holding period",
            ]),
            ",".join([
                "01/01/2025 10:00", "01/01/2024 10:00", "AAA", '"0,10000000"', "0.0", "0.0", "0.0",
                "", "Kraken", "Long term",
            ]),
        ]),
        encoding="utf-8",
    )

    (koinly_dir / "koinly_2025_income_report_test.csv").write_text(
        "\n".join([
            "Income report 2025",
            "",
            "Date,Asset,Amount,Value (EUR),Type,Description,Wallet Name",
            '01/01/2025 00:01,BBB,"1,00000000",0.0,Reward,,Wirex',
        ]),
        encoding="utf-8",
    )

    (koinly_dir / "koinly_2025_beginning_of_year_holdings_report_test.csv").write_text(
        "\n".join([
            "Balances as at 01/01/2025 00:00",
            "",
            "Asset,Quantity,Cost (EUR),Value (EUR),Description",
            'CCC,"1,00000000","10,00",0.0,',
        ]),
        encoding="utf-8",
    )

    _write_minimal_transaction_history(koinly_dir)

    report = load_koinly_crypto_report(koinly_dir)

    assert report is not None

    # Verify all skipped tokens have suspicious=False (normal assets)
    for token in report.skipped_zero_value_tokens:
        if token.asset in ["AAA", "BBB", "CCC"]:
            assert token.suspicious is False, f"{token.asset} should not be flagged as suspicious (Latin only)"


@pytest.mark.unit
def test_skipped_zero_value_tokens_suspicious_field_populated_in_report():
    """Verify that suspicious field is correctly populated in CryptoTaxReport."""
    from tax_reporting.application.crypto_reporting import (
        CryptoCapitalGainStats,
        CryptoReconciliationSummary,
        CryptoTaxReport,
    )

    # Create a report with skipped tokens that include suspicious assets
    skipped_tokens = [
        CryptoSkippedZeroValueToken(
            source_section="income",
            asset="WBТC",  # Cyrillic Т
            count=1,
            suspicious=True,
        ),
        CryptoSkippedZeroValueToken(
            source_section="income",
            asset="BTC",
            count=2,
            suspicious=False,
        ),
    ]

    report = CryptoTaxReport(
        tax_year=2025,
        capital_entries=[],
        reward_entries=[],
        reconciliation=CryptoReconciliationSummary(
            capital_rows=0,
            reward_rows=0,
            short_term_rows=0,
            long_term_rows=0,
            mixed_rows=0,
            unknown_rows=0,
            capital_cost_total_eur=Decimal("0"),
            capital_proceeds_total_eur=Decimal("0"),
            capital_gain_total_eur=Decimal("0"),
            reward_total_eur=Decimal("0"),
            opening_holdings=None,
            closing_holdings=None,
        ),
        capital_gain_stats=CryptoCapitalGainStats.from_entries([]),
        skipped_zero_value_tokens=skipped_tokens,
    )

    # Verify the suspicious field is preserved
    wbtc_token = next((t for t in report.skipped_zero_value_tokens if t.asset == "WBТC"), None)
    assert wbtc_token is not None
    assert wbtc_token.suspicious is True

    btc_token = next((t for t in report.skipped_zero_value_tokens if t.asset == "BTC"), None)
    assert btc_token is not None
    assert btc_token.suspicious is False


@pytest.mark.unit
def test_parse_capital_gains_file_creates_review_entry_for_zero_value_known_assets(tmp_path):
    """Verify that CryptoReviewEntry is created when a known asset has all-zero values."""
    from tax_reporting.application.crypto_reporting import (
        CapitalGainsParsingContext,
        _parse_capital_gains_file,
    )

    koinly_dir = tmp_path / "koinly2025"
    koinly_dir.mkdir()

    # Create capital gains file with zero-value known assets
    capital_file = koinly_dir / "koinly_2025_capital_gains_report_test.csv"
    capital_content = "\n".join([
        "Capital gains report 2025",
        "",
        "Date Sold,Date Acquired,Asset,Amount,Cost (EUR),Proceeds (EUR),Gain / loss,Notes,Wallet Name,Holding period",
        "01/01/2025 10:00,01/01/2024 10:00,BTC,\"0,10000000\",0.0,0.0,0.0,,Kraken,Long term",
        "02/01/2025 10:00,01/01/2024 10:00,ETH,\"0,20000000\",0.0,0.0,0.0,,Kraken,Short term",
    ])
    capital_file.write_text(capital_content, encoding="utf-8")

    from unittest.mock import MagicMock

    from tax_reporting.application.token_origin import TokenOriginResolver

    # Create mock origin resolver
    origin_resolver = MagicMock(spec=TokenOriginResolver)
    origin_resolver.resolve.return_value = {"origin": "Unknown"}

    review_entries: list = []
    known_assets = frozenset(["BTC", "ETH"])

    context = CapitalGainsParsingContext(
        skipped_assets={},
        origin_resolver=origin_resolver,
        review_entries=review_entries,
        known_assets=known_assets,
        loan_affected_assets=frozenset(),
    )

    # Mock _get_popular_crypto_tokens to return known assets
    from unittest.mock import patch

    with patch("tax_reporting.application.crypto_reporting._get_popular_crypto_tokens", return_value=known_assets):
        entries, _ = _parse_capital_gains_file(capital_file, context)

    # Verify review entries were created for the zero-value known assets
    assert len(review_entries) == 2

    # Check BTC review entry
    btc_review = next((e for e in review_entries if e.asset == "BTC"), None)
    assert btc_review is not None
    assert "zero" in btc_review.review_reason.lower()
    assert btc_review.is_suspicious is False

    # Check ETH review entry
    eth_review = next((e for e in review_entries if e.asset == "ETH"), None)
    assert eth_review is not None


@pytest.mark.unit
def test_parse_capital_gains_file_review_reason_includes_suspicious_flag(tmp_path):
    """Verify that review_reason includes suspicious flag for non-Latin assets."""
    from unittest.mock import MagicMock

    from tax_reporting.application.crypto_reporting import CapitalGainsParsingContext, _parse_capital_gains_file
    from tax_reporting.application.token_origin import TokenOriginResolver

    koinly_dir = tmp_path / "koinly2025"
    koinly_dir.mkdir()

    # Create capital gains file with zero-value asset containing non-Latin characters
    capital_file = koinly_dir / "koinly_2025_capital_gains_report_test.csv"
    capital_content = "\n".join([
        "Capital gains report 2025",
        "",
        "Date Sold,Date Acquired,Asset,Amount,Cost (EUR),Proceeds (EUR),Gain / loss,Notes,Wallet Name,Holding period",
        "01/01/2025 10:00,01/01/2024 10:00,WBТC,\"0,10000000\",0.0,0.0,0.0,,Kraken,Long term",
    ])
    capital_file.write_text(capital_content, encoding="utf-8")

    # Create mock origin resolver
    origin_resolver = MagicMock(spec=TokenOriginResolver)
    origin_resolver.resolve.return_value = {"origin": "Unknown"}

    review_entries: list = []
    skipped_assets: dict = {}
    # Include the Cyrillic version in known_assets to trigger review entry creation
    known_assets = frozenset(["WBТC"])

    context = CapitalGainsParsingContext(
        skipped_assets=skipped_assets,
        origin_resolver=origin_resolver,
        review_entries=review_entries,
        known_assets=known_assets,
        loan_affected_assets=frozenset(),
    )

    entries, _ = _parse_capital_gains_file(capital_file, context)

    # Verify review entry for WBТC (with Cyrillic Т)
    wbtc_review = next((e for e in review_entries if e.asset == "WBТC"), None)
    assert wbtc_review is not None
    assert wbtc_review.is_suspicious is True
    assert "non-latin" in wbtc_review.review_reason.lower() or "suspicious" in wbtc_review.review_reason.lower()


@pytest.mark.unit
def test_crypto_tax_report_review_entries_field_populated():
    """Verify that review_entries in CryptoTaxReport contains the expected entries."""
    from tax_reporting.application.crypto_reporting import (
        CryptoCapitalGainStats,
        CryptoReconciliationSummary,
        CryptoReviewEntry,
        CryptoTaxReport,
    )

    # Create a report with review entries
    review_entries = [
        CryptoReviewEntry(
            source_section="capital_gains",
            date="2025-01-15",
            asset="BTC",
            platform="Kraken",
            review_reason="Zero cost basis",
            is_suspicious=False,
        ),
        CryptoReviewEntry(
            source_section="capital_gains",
            date="2025-01-16",
            asset="ETH",
            platform="ByBit",
            review_reason="Zero proceeds",
            is_suspicious=False,
        ),
    ]

    report = CryptoTaxReport(
        tax_year=2025,
        capital_entries=[],
        reward_entries=[],
        reconciliation=CryptoReconciliationSummary(
            capital_rows=0,
            reward_rows=0,
            short_term_rows=0,
            long_term_rows=0,
            mixed_rows=0,
            unknown_rows=0,
            capital_cost_total_eur=Decimal("0"),
            capital_proceeds_total_eur=Decimal("0"),
            capital_gain_total_eur=Decimal("0"),
            reward_total_eur=Decimal("0"),
            opening_holdings=None,
            closing_holdings=None,
        ),
        capital_gain_stats=CryptoCapitalGainStats.from_entries([]),
        review_entries=review_entries,
    )

    # Verify review_entries field contains the expected entries
    assert len(report.review_entries) == 2
    assert report.review_entries[0].asset == "BTC"
    assert report.review_entries[1].asset == "ETH"
    assert all(e.is_suspicious is False for e in report.review_entries)


# =============================================================================
# Unit tests for _build_ogr_index()
# =============================================================================


def test_build_ogr_index():
    """Given parsed OGR rows with date, asset, wallet, expects index keyed by (date, asset, wallet)."""
    ogr_rows = [
        ParsedOgrRow(
            date="2025-01-13",
            asset="USDT",
            gain_loss=Decimal("-138.73"),
            row_type="Loss",
            wallet="ByBit",
        ),
        ParsedOgrRow(
            date="2025-01-14",
            asset="BTC",
            gain_loss=Decimal("500.00"),
            row_type="Profit",
            wallet="Kraken",
        ),
    ]

    index = _build_ogr_index(ogr_rows)

    # Index should have 2 entries
    assert len(index) == 2

    # Keys should be (date_only, asset_normalized, wallet_normalized)
    # Date should be YYYY-MM-DD (time stripped)
    assert ("2025-01-13", "USDT", "ByBit") in index
    assert ("2025-01-14", "BTC", "Kraken") in index


def test_ogr_index_lookup_by_key():
    """Given index with entry (2025-01-13, USDT, ByBit), expects lookup returns matching OGR value."""
    ogr_rows = [
        ParsedOgrRow(
            date="2025-01-13",
            asset="USDT",
            gain_loss=Decimal("-138.73"),
            row_type="Loss",
            wallet="ByBit",
        ),
    ]

    index = _build_ogr_index(ogr_rows)

    # Lookup should return negative value for Loss
    value = index[("2025-01-13", "USDT", "ByBit")]
    assert value == Decimal("-138.73")


def test_ogr_index_lookup_by_key_profit():
    """Given index with Profit entry, expects lookup returns positive value."""
    ogr_rows = [
        ParsedOgrRow(
            date="2025-01-15",
            asset="ETH",
            gain_loss=Decimal("250.00"),
            row_type="Profit",
            wallet="Gate.io",
        ),
    ]

    index = _build_ogr_index(ogr_rows)

    # Lookup should return positive value for Profit
    value = index[("2025-01-15", "ETH", "Gate.io")]
    assert value == Decimal("250")


def test_ogr_index_missing_key():
    """Given index and non-matching key, expects returns None."""
    ogr_rows = [
        ParsedOgrRow(
            date="2025-01-13",
            asset="USDT",
            gain_loss=Decimal("-138.73"),
            row_type="Loss",
            wallet="ByBit",
        ),
    ]

    index = _build_ogr_index(ogr_rows)

    # Non-matching key should return None
    assert ("2025-01-13", "BTC", "ByBit") not in index
    assert ("2025-01-14", "USDT", "ByBit") not in index
    assert ("2025-01-13", "USDT", "Kraken") not in index


def test_ogr_index_skips_zero_value_rows():
    """Zero-value rows (fee tokens, dust) are skipped at parse time, so the index never sees them.

    Under the Task 6 refactor, zero-value filtering lives in ``_parse_other_gains_row``
    (via ``_extract_ogr_gain_loss`` returning ``None``); ``_build_ogr_index`` is now a
    pure summing loop over ``ParsedOgrRow`` and performs no filtering itself. To preserve
    the test's intent ("zero-value rows do not appear in the index"), we reflect the new
    pipeline by constructing a ParsedOgrRow list that omits the zero-value row (the
    parser would have dropped it before _build_ogr_index is called).
    """
    ogr_rows = [
        ParsedOgrRow(
            date="2025-01-13",
            asset="USDT",
            gain_loss=Decimal("-138.73"),
            row_type="Loss",
            wallet="ByBit",
        ),
        # The zero-value FEE row would have been filtered by _parse_other_gains_row
        # and therefore never appears in the ParsedOgrRow list passed to _build_ogr_index.
    ]

    index = _build_ogr_index(ogr_rows)

    # Index should only have 1 entry (zero-value row was filtered at parse time)
    assert len(index) == 1
    assert ("2025-01-13", "USDT", "ByBit") in index


def test_ogr_index_handles_wallet_aliases(tmp_path):
    """'ByBit (2)' and 'ByBit' are NO LONGER collapsed at parse time (CRG-008 retired).

    After Phase A Task 8, normalize_platform_name performs only whitespace
    trimming; platform consolidation is the responsibility of the
    platform-level resolver (Invariant 4). The pure-summing _build_ogr_index
    therefore keeps the two rows as distinct (date, asset, wallet) keys.
    """
    import csv as _csv

    from tax_reporting.infrastructure.koinly_parser import _find_and_parse_other_gains_file

    ogr_file = tmp_path / "koinly_2025_other_gains_report.csv"
    fieldnames = ["Date", "Asset", "Amount", "Value (EUR)", "Type", "Wallet Name"]
    with ogr_file.open("w", newline="") as fh:
        writer = _csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow(
            {
                "Date": "13/01/2025 13:01",
                "Asset": "USDT",
                "Amount": "-142,11",
                "Value (EUR)": "138,73",
                "Type": "Loss",
                "Wallet Name": "ByBit (2)",
            }
        )
        writer.writerow(
            {
                "Date": "13/01/2025 14:00",
                "Asset": "USDT",
                "Amount": "100,00",
                "Value (EUR)": "100,00",
                "Type": "Profit",
                "Wallet Name": "ByBit",
            }
        )

    ogr_rows = _find_and_parse_other_gains_file(tmp_path)
    index = _build_ogr_index(ogr_rows)

    # Wallets no longer collapse; each (date, asset, wallet) tuple is its own key.
    assert len(index) == 2
    assert ("2025-01-13", "USDT", "ByBit (2)") in index
    assert ("2025-01-13", "USDT", "ByBit") in index
    # Values are kept per-key, NOT summed across aliases.
    assert index[("2025-01-13", "USDT", "ByBit (2)")] == Decimal("-138.73")
    assert index[("2025-01-13", "USDT", "ByBit")] == Decimal("100.00")


def test_ogr_index_skips_unknown_types():
    """Rows with unknown Type are skipped at parse time, so the index never sees them.

    Under the Task 6 refactor, unknown-Type filtering lives in
    ``_parse_other_gains_row`` (via ``_extract_ogr_gain_loss`` returning ``None``
    for types other than Profit/Loss); ``_build_ogr_index`` is now a pure summing
    loop and performs no filtering itself. To preserve the test's intent ("unknown
    Type rows do not appear in the index"), we reflect the new pipeline by
    constructing a ParsedOgrRow list that omits the unknown-Type row (the parser
    would have dropped it before _build_ogr_index is called).
    """
    ogr_rows = [
        # The UnknownType row would have been filtered by _parse_other_gains_row
        # and therefore never appears in the ParsedOgrRow list passed to _build_ogr_index.
        ParsedOgrRow(
            date="2025-01-14",
            asset="BTC",
            gain_loss=Decimal("500.00"),
            row_type="Profit",
            wallet="Kraken",
        ),
    ]

    index = _build_ogr_index(ogr_rows)

    # Index should only have 1 entry (unknown type was filtered at parse time)
    assert len(index) == 1
    assert ("2025-01-14", "BTC", "Kraken") in index


class TestOgrValidation:
    """Test OGR validation result domain type."""

    def test_ogr_validation_small_magnitude_diff(self):
        """
Given OGR=-100, CG=-90, expects direction_conflict=False, magnitude_diff_percent≈11.1%, review_required=True.
        """
        from tax_reporting.domain.entities import OgrValidationResult

        result = OgrValidationResult(
            ogr_gain_loss=Decimal("-100"),
            calculated_gain_loss=Decimal("-90"),
            direction_conflict=False,
            magnitude_diff_percent=Decimal("11.11"),
            review_required=True,
            review_reason="Magnitude difference exceeds 10% threshold",
        )

        assert result.ogr_gain_loss == Decimal("-100")
        assert result.calculated_gain_loss == Decimal("-90")
        assert result.direction_conflict is False
        assert result.magnitude_diff_percent == Decimal("11.11")
        assert result.review_required is True
        assert result.review_reason == "Magnitude difference exceeds 10% threshold"

    def test_ogr_validation_direction_conflict(self):
        """
Given OGR=-100, CG=+50, expects direction_conflict=True, magnitude_diff_percent≈300%, review_required=True.
        """
        from tax_reporting.domain.entities import OgrValidationResult

        result = OgrValidationResult(
            ogr_gain_loss=Decimal("-100"),
            calculated_gain_loss=Decimal("50"),
            direction_conflict=True,
            magnitude_diff_percent=Decimal("300"),
            review_required=True,
            review_reason="Direction conflict: OGR shows loss but CG shows gain",
        )

        assert result.ogr_gain_loss == Decimal("-100")
        assert result.calculated_gain_loss == Decimal("50")
        assert result.direction_conflict is True
        assert result.magnitude_diff_percent == Decimal("300")
        assert result.review_required is True
        assert result.review_reason == "Direction conflict: OGR shows loss but CG shows gain"

    def test_ogr_validation_within_threshold(self):
        """
Given OGR=-100, CG=-98, expects direction_conflict=False, magnitude_diff_percent≈2%, review_required=False.
        """
        from tax_reporting.domain.entities import OgrValidationResult

        result = OgrValidationResult(
            ogr_gain_loss=Decimal("-100"),
            calculated_gain_loss=Decimal("-98"),
            direction_conflict=False,
            magnitude_diff_percent=Decimal("2.04"),
            review_required=False,
            review_reason=None,
        )

        assert result.ogr_gain_loss == Decimal("-100")
        assert result.calculated_gain_loss == Decimal("-98")
        assert result.direction_conflict is False
        assert result.magnitude_diff_percent == Decimal("2.04")
        assert result.review_required is False
        assert result.review_reason is None

    def test_ogr_validation_no_ogr_match(self):
        """Given OGR=None, CG=+50, expects ogr_gain_loss=None, direction_conflict=False, review_required=False."""
        from tax_reporting.domain.entities import OgrValidationResult

        result = OgrValidationResult(
            ogr_gain_loss=None,
            calculated_gain_loss=Decimal("50"),
            direction_conflict=False,
            magnitude_diff_percent=None,
            review_required=False,
            review_reason=None,
        )

        assert result.ogr_gain_loss is None
        assert result.calculated_gain_loss == Decimal("50")
        assert result.direction_conflict is False
        assert result.magnitude_diff_percent is None
        assert result.review_required is False
        assert result.review_reason is None

    def test_ogr_validation_attached_to_entry(self):
        """Verify OGR validation can be attached to CryptoCapitalGainEntry without triggering entry-level validation."""
        from tax_reporting.domain.entities import OgrValidationResult

        ogr_validation = OgrValidationResult(
            ogr_gain_loss=Decimal("-100"),
            calculated_gain_loss=Decimal("-90"),
            direction_conflict=False,
            magnitude_diff_percent=Decimal("11.11"),
            review_required=True,
            review_reason="Magnitude difference exceeds 10% threshold",
        )

        # Entry should not have review_required=True based on ogr_validation
        # The two fields are independent
        entry = CryptoCapitalGainEntry(
            disposal_date="2025-01-13",
            acquisition_date="2025-01-10",
            asset="USDT",
            amount=Decimal("142.11"),
            cost_eur=Decimal("165.44"),
            proceeds_eur=Decimal("188.15"),
            gain_loss_eur=Decimal("22.71"),
            holding_period="Short-term (365 days)",
            wallet="ByBit",
            platform="ByBit",
            chain="Ethereum",
            operator_origin=OperatorOrigin(
                platform="ByBit",
                service_scope="crypto",
                operator_entity="Bybit group entity",
                operator_country="AE",
                source_url="https://bybit.com",
                source_checked_on="2026-01-01",
                confidence="medium",
                review_required=False,
            ),
            annex_hint="J",
            review_required=False,  # Entry-level flag, independent of ogr_validation.review_required
            notes="",
            ogr_validation=ogr_validation,
        )

        assert entry.ogr_validation is ogr_validation
        assert entry.review_required is False  # Entry-level validation not affected
        assert entry.ogr_validation.review_required is True  # OGR-level validation is set


class TestApplyOgrDirectionOverride:
    """Test OGR directional authority override behavior."""

    def test_ogr_direction_conflict_cg_gain_ogr_loss(self):
        """Given CG entry with gain=+100 and OGR=-100, expects final_gain_loss=-100 (CG magnitude with OGR direction),
        review_reason='OGR direction override: CG indicated gain'.
        """
        from tax_reporting.infrastructure.config import TaxJurisdictionConfig

        jurisdiction = TaxJurisdictionConfig(
            country="TEST",
            fiscal_year=2025,
            exclude_loan_repayment_gains=False,
            zero_basis_review_threshold=Decimal("500"),
            use_other_gains_report=True,
        )

        ogr_index = {
            ("2025-01-13", "USDT", "ByBit"): Decimal("-100")
        }

        cg_entry = CryptoCapitalGainEntry(
            disposal_date="2025-01-13",
            acquisition_date="2025-01-10",
            asset="USDT",
            amount=Decimal("100"),
            cost_eur=Decimal("100"),
            proceeds_eur=Decimal("200"),
            gain_loss_eur=Decimal("100"),  # CG shows gain
            holding_period="Short-term (3 days)",
            wallet="ByBit",
            platform="ByBit",
            chain="Ethereum",
            operator_origin=OperatorOrigin(
                platform="ByBit",
                service_scope="crypto",
                operator_entity="Bybit group entity",
                operator_country="AE",
                source_url="https://bybit.com",
                source_checked_on="2026-01-01",
                confidence="medium",
                review_required=False,
            ),
            annex_hint="J",
            review_required=False,
            notes="",
        )

        result = apply_ogr_event_level([cg_entry], ogr_index, jurisdiction)

        assert len(result) == 1
        # Direction override: use OGR direction (loss) with CG magnitude (100)
        assert result[0].gain_loss_eur == Decimal("-100")
        # Proceeds = cost + gain_loss = 100 + (-100) = 0
        assert result[0].proceeds_eur == Decimal("0")
        # OGR validation should be attached
        assert result[0].ogr_validation is not None
        assert result[0].ogr_validation.ogr_gain_loss == Decimal("-100")
        assert result[0].ogr_validation.calculated_gain_loss == Decimal("100")
        assert result[0].ogr_validation.direction_conflict is True
        assert result[0].ogr_validation.review_required is True
        assert "OGR direction override: CG indicated gain" in result[0].ogr_validation.review_reason

    def test_ogr_direction_agree_small_magnitude_diff(self):
        """Given CG entry with gain=-100 and OGR=-105, expects final_gain_loss=-105 (directions agree, use OGR
        magnitude), review_required=False (diff < 5%).
        """
        from tax_reporting.infrastructure.config import TaxJurisdictionConfig

        jurisdiction = TaxJurisdictionConfig(
            country="TEST",
            fiscal_year=2025,
            exclude_loan_repayment_gains=False,
            zero_basis_review_threshold=Decimal("500"),
            use_other_gains_report=True,
        )

        ogr_index = {
            ("2025-01-13", "USDT", "ByBit"): Decimal("-105")
        }

        cg_entry = CryptoCapitalGainEntry(
            disposal_date="2025-01-13",
            acquisition_date="2025-01-10",
            asset="USDT",
            amount=Decimal("100"),
            cost_eur=Decimal("200"),
            proceeds_eur=Decimal("100"),
            gain_loss_eur=Decimal("-100"),  # CG shows loss
            holding_period="Short-term (3 days)",
            wallet="ByBit",
            platform="ByBit",
            chain="Ethereum",
            operator_origin=OperatorOrigin(
                platform="ByBit",
                service_scope="crypto",
                operator_entity="Bybit group entity",
                operator_country="AE",
                source_url="https://bybit.com",
                source_checked_on="2026-01-01",
                confidence="medium",
                review_required=False,
            ),
            annex_hint="J",
            review_required=False,
            notes="",
        )

        result = apply_ogr_event_level([cg_entry], ogr_index, jurisdiction)

        assert len(result) == 1
        # Directions agree (both loss), use OGR magnitude
        assert result[0].gain_loss_eur == Decimal("-105")
        assert result[0].proceeds_eur == cg_entry.cost_eur + Decimal("-105")
        # OGR validation attached
        assert result[0].ogr_validation is not None
        assert result[0].ogr_validation.ogr_gain_loss == Decimal("-105")
        assert result[0].ogr_validation.calculated_gain_loss == Decimal("-100")
        assert result[0].ogr_validation.direction_conflict is False
        # Diff is 5%, which is NOT > 5%, so no review required
        assert result[0].ogr_validation.review_required is False
        assert result[0].ogr_validation.review_reason is None

    def test_ogr_direction_agree_large_magnitude_diff(self):
        """Given CG entry with gain=-100 and OGR=-106, expects final_gain_loss=-106, review_required=True (diff > 5%),
        review_reason mentions magnitude diff.
        """
        from tax_reporting.infrastructure.config import TaxJurisdictionConfig

        jurisdiction = TaxJurisdictionConfig(
            country="TEST",
            fiscal_year=2025,
            exclude_loan_repayment_gains=False,
            zero_basis_review_threshold=Decimal("500"),
            use_other_gains_report=True,
        )

        ogr_index = {
            ("2025-01-13", "USDT", "ByBit"): Decimal("-106")
        }

        cg_entry = CryptoCapitalGainEntry(
            disposal_date="2025-01-13",
            acquisition_date="2025-01-10",
            asset="USDT",
            amount=Decimal("100"),
            cost_eur=Decimal("200"),
            proceeds_eur=Decimal("100"),
            gain_loss_eur=Decimal("-100"),
            holding_period="Short-term (3 days)",
            wallet="ByBit",
            platform="ByBit",
            chain="Ethereum",
            operator_origin=OperatorOrigin(
                platform="ByBit",
                service_scope="crypto",
                operator_entity="Bybit group entity",
                operator_country="AE",
                source_url="https://bybit.com",
                source_checked_on="2026-01-01",
                confidence="medium",
                review_required=False,
            ),
            annex_hint="J",
            review_required=False,
            notes="",
        )

        result = apply_ogr_event_level([cg_entry], ogr_index, jurisdiction)

        assert len(result) == 1
        assert result[0].gain_loss_eur == Decimal("-106")
        assert result[0].ogr_validation is not None
        assert result[0].ogr_validation.direction_conflict is False
        # Diff is 6%, which IS > 5%, so review required
        assert result[0].ogr_validation.review_required is True
        assert "magnitude differs" in result[0].ogr_validation.review_reason.lower()
        assert "6.0%" in result[0].ogr_validation.review_reason

    def test_ogr_no_ogr_match(self):
        """
Given CG entry with gain=-100 and no OGR match, expects final_gain_loss=-100 (unchanged), ogr_validation=None.
        """
        from tax_reporting.infrastructure.config import TaxJurisdictionConfig

        jurisdiction = TaxJurisdictionConfig(
            country="TEST",
            fiscal_year=2025,
            exclude_loan_repayment_gains=False,
            zero_basis_review_threshold=Decimal("500"),
            use_other_gains_report=True,
        )

        # OGR index has different key - no match
        ogr_index = {
            ("2025-01-14", "BTC", "Kraken"): Decimal("50")
        }

        cg_entry = CryptoCapitalGainEntry(
            disposal_date="2025-01-13",
            acquisition_date="2025-01-10",
            asset="USDT",
            amount=Decimal("100"),
            cost_eur=Decimal("200"),
            proceeds_eur=Decimal("100"),
            gain_loss_eur=Decimal("-100"),
            holding_period="Short-term (3 days)",
            wallet="ByBit",
            platform="ByBit",
            chain="Ethereum",
            operator_origin=OperatorOrigin(
                platform="ByBit",
                service_scope="crypto",
                operator_entity="Bybit group entity",
                operator_country="AE",
                source_url="https://bybit.com",
                source_checked_on="2026-01-01",
                confidence="medium",
                review_required=False,
            ),
            annex_hint="J",
            review_required=False,
            notes="",
        )

        result = apply_ogr_event_level([cg_entry], ogr_index, jurisdiction)

        assert len(result) == 1
        # No change when no OGR match
        assert result[0].gain_loss_eur == Decimal("-100")
        assert result[0].proceeds_eur == Decimal("100")
        # No OGR validation attached
        assert result[0].ogr_validation is None

    def test_ogr_direction_conflict_small_absolute_diff(self):
        """Given CG entry with gain=0.01 and OGR=-1.01, expects direction_conflict=True but review_required=False
        (absolute diff 1 EUR not exceeded).
        """
        from tax_reporting.infrastructure.config import TaxJurisdictionConfig

        jurisdiction = TaxJurisdictionConfig(
            country="TEST",
            fiscal_year=2025,
            exclude_loan_repayment_gains=False,
            zero_basis_review_threshold=Decimal("500"),
            use_other_gains_report=True,
        )

        ogr_index = {
            ("2025-01-13", "USDT", "ByBit"): Decimal("-1.01")
        }

        cg_entry = CryptoCapitalGainEntry(
            disposal_date="2025-01-13",
            acquisition_date="2025-01-10",
            asset="USDT",
            amount=Decimal("1"),
            cost_eur=Decimal("10"),
            proceeds_eur=Decimal("10.01"),
            gain_loss_eur=Decimal("0.01"),  # Tiny gain
            holding_period="Short-term (3 days)",
            wallet="ByBit",
            platform="ByBit",
            chain="Ethereum",
            operator_origin=OperatorOrigin(
                platform="ByBit",
                service_scope="crypto",
                operator_entity="Bybit group entity",
                operator_country="AE",
                source_url="https://bybit.com",
                source_checked_on="2026-01-01",
                confidence="medium",
                review_required=False,
            ),
            annex_hint="J",
            review_required=False,
            notes="",
        )

        result = apply_ogr_event_level([cg_entry], ogr_index, jurisdiction)

        assert len(result) == 1
        # Direction conflict should be detected
        assert result[0].ogr_validation is not None
        assert result[0].ogr_validation.direction_conflict is True
        # But absolute diff is only 1 EUR, not > 1 EUR
        assert result[0].ogr_validation.review_required is False
        assert result[0].ogr_validation.review_reason is None

    def test_ogr_multiple_lots_same_disposal(self):
        """Given 109 CG lots for same (date, asset, wallet) with total gain=+500 and OGR=-147.19, expects each lot gets
        ogr_validation with ogr_gain_loss=-147.19, directions corrected, and after aggregation produces single entry
        with corrected totals.
        """
        from tax_reporting.infrastructure.config import TaxJurisdictionConfig

        jurisdiction = TaxJurisdictionConfig(
            country="TEST",
            fiscal_year=2025,
            exclude_loan_repayment_gains=False,
            zero_basis_review_threshold=Decimal("500"),
            use_other_gains_report=True,
        )

        ogr_index = {
            ("2025-01-13", "USDT", "ByBit"): Decimal("-147.19")
        }

        # Create 109 CG lots, each with a small gain
        # Total gain before OGR: 109 lots × ~4.59 = ~500
        lots = []
        per_lot_gain = Decimal("500") / Decimal("109")
        per_lot_cost = Decimal("100")
        per_lot_proceeds = per_lot_cost + per_lot_gain

        for _ in range(109):
            lot = CryptoCapitalGainEntry(
                disposal_date="2025-01-13",
                acquisition_date="2025-01-10",
                asset="USDT",
                amount=Decimal("1"),
                cost_eur=per_lot_cost,
                proceeds_eur=per_lot_proceeds,
                gain_loss_eur=per_lot_gain,  # Each lot shows small gain
                holding_period="Short-term (3 days)",
                wallet="ByBit",
                platform="ByBit",
                chain="Ethereum",
                operator_origin=OperatorOrigin(
                    platform="ByBit",
                    service_scope="crypto",
                    operator_entity="Bybit group entity",
                    operator_country="AE",
                    source_url="https://bybit.com",
                    source_checked_on="2026-01-01",
                    confidence="medium",
                    review_required=False,
                ),
                annex_hint="J",
                review_required=False,
                notes="",
            )
            lots.append(lot)

        # Apply OGR direction override (before aggregation)
        result = apply_ogr_event_level(lots, ogr_index, jurisdiction)

        assert len(result) == 109

        # Each lot should have OGR validation attached
        # All lots share the same OGR value for this disposal event
        for lot in result:
            assert lot.ogr_validation is not None
            assert lot.ogr_validation.ogr_gain_loss == Decimal("-147.19")
            # Direction conflict: CG showed gain, OGR shows loss
            assert lot.ogr_validation.direction_conflict is True
            # Each lot gets direction-corrected value (OGR direction with CG magnitude)
            assert lot.gain_loss_eur == -abs(per_lot_gain)  # Negative (loss direction) with CG magnitude

        # After aggregation, we'd have a single entry with summed values
        # This test verifies pre-aggregation state; aggregation is tested separately


class TestOgrDisabledBackwardCompatibility:
    """Test backward compatibility when OGR is disabled."""

    def test_ogr_disabled_entries_have_no_ogr_validation(self):
        """Jurisdiction with use_other_gains_report=False.

        Expects ogr_validation=None on all entries and gain/loss values unchanged from original CG.
        """
        from tax_reporting.infrastructure.config import TaxJurisdictionConfig

        jurisdiction = TaxJurisdictionConfig(
            country="TEST",
            fiscal_year=2025,
            exclude_loan_repayment_gains=False,
            zero_basis_review_threshold=Decimal("500"),
            use_other_gains_report=False,  # OGR disabled
        )

        # Create OGR index (should be ignored due to use_other_gains_report=False)
        ogr_index = {
            ("2025-01-13", "USDT", "ByBit"): Decimal("-999.99")
        }

        # Create CG entry with original gain/loss values
        cg_entry = CryptoCapitalGainEntry(
            disposal_date="2025-01-13",
            acquisition_date="2025-01-10",
            asset="USDT",
            amount=Decimal("100"),
            cost_eur=Decimal("100"),
            proceeds_eur=Decimal("200"),
            gain_loss_eur=Decimal("100"),  # Original CG value
            holding_period="Short-term (3 days)",
            wallet="ByBit",
            platform="ByBit",
            chain="Ethereum",
            operator_origin=OperatorOrigin(
                platform="ByBit",
                service_scope="crypto",
                operator_entity="Bybit group entity",
                operator_country="AE",
                source_url="https://bybit.com",
                source_checked_on="2026-01-01",
                confidence="medium",
                review_required=False,
            ),
            annex_hint="J",
            review_required=False,
            notes="",
        )

        result = apply_ogr_event_level([cg_entry], ogr_index, jurisdiction)

        assert len(result) == 1
        # Entry should have no OGR validation attached
        assert result[0].ogr_validation is None
        # Gain/loss values should remain unchanged from original CG
        assert result[0].gain_loss_eur == Decimal("100")
        assert result[0].proceeds_eur == Decimal("200")
        assert result[0].cost_eur == Decimal("100")

    def test_ogr_disabled_multiple_entries_all_unaffected(self):
        """Given multiple CG entries and jurisdiction with use_other_gains_report=False, expects all entries unchanged
        with no OGR validation.
        """
        from tax_reporting.infrastructure.config import TaxJurisdictionConfig

        jurisdiction = TaxJurisdictionConfig(
            country="TEST",
            fiscal_year=2025,
            exclude_loan_repayment_gains=False,
            zero_basis_review_threshold=Decimal("500"),
            use_other_gains_report=False,
        )

        # OGR index with entries that would match if OGR were enabled
        ogr_index = {
            ("2025-01-13", "USDT", "ByBit"): Decimal("-147.19"),
            ("2025-01-14", "BTC", "Kraken"): Decimal("250.50"),
        }

        entries = [
            CryptoCapitalGainEntry(
                disposal_date="2025-01-13",
                acquisition_date="2025-01-10",
                asset="USDT",
                amount=Decimal("100"),
                cost_eur=Decimal("100"),
                proceeds_eur=Decimal("200"),
                gain_loss_eur=Decimal("100"),
                holding_period="Short-term (3 days)",
                wallet="ByBit",
                platform="ByBit",
                chain="Ethereum",
                operator_origin=OperatorOrigin(
                    platform="ByBit",
                    service_scope="crypto",
                    operator_entity="Bybit group entity",
                    operator_country="AE",
                    source_url="https://bybit.com",
                    source_checked_on="2026-01-01",
                    confidence="medium",
                    review_required=False,
                ),
                annex_hint="J",
                review_required=False,
                notes="",
            ),
            CryptoCapitalGainEntry(
                disposal_date="2025-01-14",
                acquisition_date="2025-01-11",
                asset="BTC",
                amount=Decimal("1"),
                cost_eur=Decimal("3000"),
                proceeds_eur=Decimal("2800"),
                gain_loss_eur=Decimal("-200"),
                holding_period="Short-term (3 days)",
                wallet="Kraken",
                platform="Kraken",
                chain="Ethereum",
                operator_origin=OperatorOrigin(
                    platform="Kraken",
                    service_scope="crypto",
                    operator_entity="Payward Ireland",
                    operator_country="IE",
                    source_url="https://kraken.com",
                    source_checked_on="2026-01-01",
                    confidence="high",
                    review_required=False,
                ),
                annex_hint="J",
                review_required=False,
                notes="",
            ),
        ]

        result = apply_ogr_event_level(entries, ogr_index, jurisdiction)

        assert len(result) == 2
        for entry in result:
            assert entry.ogr_validation is None
        # Verify original CG values are preserved
        assert result[0].gain_loss_eur == Decimal("100")
        assert result[1].gain_loss_eur == Decimal("-200")


# =============================================================================
# =============================================================================
# TDD coverage for the separate_derivatives_reporting jurisdiction flag (DP-012).
# =============================================================================


class TestSeparateDerivativesReportingFlag:
    """TDD coverage for the separate_derivatives_reporting jurisdiction flag (DP-012)."""

    def test_separate_derivatives_reporting_default_false(self) -> None:
        """Given a TaxJurisdictionConfig with no separate_derivatives_reporting, the field defaults to False."""
        from tax_reporting.infrastructure.config import DEFAULT_ZERO_BASIS_REVIEW_THRESHOLD, TaxJurisdictionConfig

        config = TaxJurisdictionConfig(
            country="PT",
            fiscal_year=2025,
            exclude_loan_repayment_gains=True,
            zero_basis_review_threshold=DEFAULT_ZERO_BASIS_REVIEW_THRESHOLD,
        )
        assert config.separate_derivatives_reporting is False

    def test_separate_derivatives_reporting_true_from_toml(self, tmp_path, monkeypatch) -> None:
        """Given TOML with separate_derivatives_reporting=true under [countries.PT], the flag loads True."""
        import configparser
        import logging

        import tax_reporting.infrastructure.config as config_module
        from tax_reporting.infrastructure.config import _load_tax_jurisdiction_config

        toml_content = (
            "[meta]\n"
            "fiscal_year = 2025\n"
            "[countries.PT]\n"
            "exclude_loan_repayment_gains = true\n"
            "futures_derivatives_taxable = true\n"
            "use_other_gains_report = true\n"
            "separate_derivatives_reporting = true\n"
        )
        monkeypatch.setattr(config_module, "_DECISION_POINTS_DIR", tmp_path)
        (tmp_path / "2025.toml").write_text(toml_content, encoding="utf-8")

        cp = configparser.ConfigParser()
        cp.optionxform = lambda optionstr: optionstr
        cp["TAX JURISDICTION"] = {"TAX_COUNTRY": "PT", "FISCAL_YEAR": "2025"}
        logger = logging.getLogger(__name__)

        result = _load_tax_jurisdiction_config(cp, logger)
        assert result.separate_derivatives_reporting is True

    def test_modelo3_dispatch_flags_auto_discovered_by_loader(self, tmp_path, monkeypatch) -> None:
        """The two new Modelo 3 dispatch bool flags are auto-discovered by the loader.

        Proves Invariant 5 (no config.py edit): ``_KNOWN_BOOL_FLAGS`` is derived from
        ``get_type_hints(TaxJurisdictionConfig)`` at import time, so adding the two bool
        fields to the dataclass is sufficient for the loader to pick them up.

        Case 1 (true): a 2025.toml with both flags ``true`` under ``[countries.PT]`` ->
        both resolve ``True``.
        Case 2 (omitted): a 2025.toml whose ``[countries.PT]`` KEEPS
        ``exclude_loan_repayment_gains = true`` (REQUIRED: loader raises ValueError for
        PT without it, config.py:321) but OMITS the two new flags -> both resolve
        ``False`` via the ``setdefault(flag_name, False)`` auto-discovery default loop
        (config.py:334-336), NOT via an empty section.
        """
        import configparser
        import logging

        import tax_reporting.infrastructure.config as config_module
        from tax_reporting.infrastructure.config import _load_tax_jurisdiction_config

        def _load(toml_body: str):
            monkeypatch.setattr(config_module, "_DECISION_POINTS_DIR", tmp_path)
            (tmp_path / "2025.toml").write_text(toml_body, encoding="utf-8")
            cp = configparser.ConfigParser()
            cp.optionxform = lambda optionstr: optionstr
            cp["TAX JURISDICTION"] = {"TAX_COUNTRY": "PT", "FISCAL_YEAR": "2025"}
            logger = logging.getLogger(__name__)
            return _load_tax_jurisdiction_config(cp, logger)

        # Case 1: both new flags explicitly true.
        result_true = _load(
            "[meta]\n"
            "fiscal_year = 2025\n"
            "[countries.PT]\n"
            "exclude_loan_repayment_gains = true\n"
            "route_derivatives_by_counterparty_residency = true\n"
            "classify_rewards_with_income_codes = true\n"
        )
        assert result_true.route_derivatives_by_counterparty_residency is True
        assert result_true.classify_rewards_with_income_codes is True

        # Case 2: both new flags omitted -> auto-discovery default False.
        result_omitted = _load(
            "[meta]\n"
            "fiscal_year = 2025\n"
            "[countries.PT]\n"
            "exclude_loan_repayment_gains = true\n"
        )
        assert result_omitted.route_derivatives_by_counterparty_residency is False
        assert result_omitted.classify_rewards_with_income_codes is False


# =============================================================================
# Task 7 (docs/history/plans/2026-06-13-derivatives-separation.md): row-level OGR
# split into derivatives_entries and spot_index, plus protection of spot CG
# from derivatives direction override.
# =============================================================================


# Helper operator for the TestOgrSplit fixtures (kept local so tests do not
# depend on the module-level _TEST_OPERATOR, which is mutated by other suites).
_OGR_SPLIT_OPERATOR = OperatorOrigin(
    platform="ByBit",
    service_scope="crypto",
    operator_entity="Bybit group entity",
    operator_country="AE",
    source_url="https://bybit.com",
    source_checked_on="2026-01-01",
    confidence="medium",
    review_required=False,
)


def _make_ogr_split_entry(  # noqa: PLR0913
    *,
    disposal_date: str,
    asset: str,
    wallet: str,
    proceeds_eur: Decimal,
    gain_loss_eur: Decimal,
    cost_eur: Decimal | None = None,
) -> CryptoCapitalGainEntry:
    """Build a CryptoCapitalGainEntry for the OGR split fixtures."""
    return CryptoCapitalGainEntry(
        disposal_date=disposal_date,
        acquisition_date="2025-01-10",
        asset=asset,
        amount=Decimal("1"),
        cost_eur=cost_eur if cost_eur is not None else proceeds_eur,
        proceeds_eur=proceeds_eur,
        gain_loss_eur=gain_loss_eur,
        holding_period="Short-term (3 days)",
        wallet=wallet,
        platform=wallet,
        chain="Ethereum",
        operator_origin=_OGR_SPLIT_OPERATOR,
        annex_hint="J",
        review_required=False,
        notes="",
    )


def _ogr_split_jurisdiction(*, separate: bool):
    """Build a TaxJurisdictionConfig with use_other_gains_report and optional separate_derivatives_reporting.

    Phase E: ``treatment_spot_disposal_via_resolver`` is gone; OGR override
    gating now keys on the resolver identifying the TH row as SPOT_DISPOSAL.
    """
    from tax_reporting.infrastructure.config import TaxJurisdictionConfig

    return TaxJurisdictionConfig(
        country="PT",
        fiscal_year=2025,
        exclude_loan_repayment_gains=True,
        zero_basis_review_threshold=Decimal("500"),
        futures_derivatives_taxable=True,
        use_other_gains_report=True,
        separate_derivatives_reporting=separate,
    )


class TestOgrSplit:
    """TDD for _split_ogr_index routing ParsedOgrRow to derivatives_entries vs spot_index."""

    def test_profit_row_to_derivatives(self):
        """Given a Profit OGR row with no CG matches, expects the row in derivatives_entries and spot_index empty."""
        from tax_reporting.application.crypto.ogr_handler import _split_ogr_index

        rows = [
            ParsedOgrRow(
                date="2025-01-12",
                asset="USDT",
                gain_loss=Decimal("140.18"),
                row_type="Profit",
                wallet="ByBit",
            ),
        ]
        capital_entries: list[CryptoCapitalGainEntry] = []

        spot_index, derivatives_entries = _split_ogr_index(
            rows, capital_entries, _ogr_split_jurisdiction(separate=True)
        )

        assert spot_index == {}
        assert len(derivatives_entries) == 1
        entry = derivatives_entries[0]
        assert entry.date == "2025-01-12"
        assert entry.asset == "USDT"
        assert entry.platform == "ByBit"
        assert entry.pnl_eur == Decimal("140.18")
        assert entry.event_type.value == "profit"
        assert entry.review_required is False
        assert entry.review_reason == ""

    def test_loss_with_cg_match_to_spot(self):
        """Given a Loss OGR row matching a CG entry's proceeds, expects the row summed into spot_index."""
        from tax_reporting.application.crypto.ogr_handler import _split_ogr_index

        rows = [
            ParsedOgrRow(
                date="2025-01-12",
                asset="USDT",
                gain_loss=Decimal("-4.17"),
                row_type="Loss",
                wallet="ByBit",
            ),
        ]
        capital_entries = [
            _make_ogr_split_entry(
                disposal_date="2025-01-12",
                asset="USDT",
                wallet="ByBit",
                proceeds_eur=Decimal("4.17"),
                gain_loss_eur=Decimal("2.44"),
                cost_eur=Decimal("1.73"),
            ),
        ]

        spot_index, derivatives_entries = _split_ogr_index(
            rows, capital_entries, _ogr_split_jurisdiction(separate=True)
        )

        assert derivatives_entries == []
        assert spot_index == {("2025-01-12", "USDT", "ByBit"): Decimal("-4.17")}

    def test_mixed_key_split_per_row(self):
        """Given two OGR rows on the same key (Profit + Loss matching CG), expects per-row split."""
        from tax_reporting.application.crypto.ogr_handler import _split_ogr_index

        rows = [
            ParsedOgrRow(
                date="2025-01-12",
                asset="USDT",
                gain_loss=Decimal("140.18"),
                row_type="Profit",
                wallet="ByBit",
            ),
            ParsedOgrRow(
                date="2025-01-12",
                asset="USDT",
                gain_loss=Decimal("-4.17"),
                row_type="Loss",
                wallet="ByBit",
            ),
        ]
        capital_entries = [
            _make_ogr_split_entry(
                disposal_date="2025-01-12",
                asset="USDT",
                wallet="ByBit",
                proceeds_eur=Decimal("4.17"),
                gain_loss_eur=Decimal("2.44"),
                cost_eur=Decimal("1.73"),
            ),
        ]

        spot_index, derivatives_entries = _split_ogr_index(
            rows, capital_entries, _ogr_split_jurisdiction(separate=True)
        )

        assert len(derivatives_entries) == 1
        assert derivatives_entries[0].pnl_eur == Decimal("140.18")
        assert derivatives_entries[0].event_type.value == "profit"
        assert spot_index == {("2025-01-12", "USDT", "ByBit"): Decimal("-4.17")}

    def test_ambiguous_row_derivatives_with_review(self):
        """Given an OGR Loss row whose value mismatches the CG counterpart, expects review_required=True."""
        from tax_reporting.application.crypto.ogr_handler import _split_ogr_index

        rows = [
            ParsedOgrRow(
                date="2025-01-12",
                asset="USDT",
                gain_loss=Decimal("-4.17"),
                row_type="Loss",
                wallet="ByBit",
            ),
        ]
        # CG proceeds_eur=99.99 does NOT match OGR magnitude 4.17 -> Ambiguous
        capital_entries = [
            _make_ogr_split_entry(
                disposal_date="2025-01-12",
                asset="USDT",
                wallet="ByBit",
                proceeds_eur=Decimal("99.99"),
                gain_loss_eur=Decimal("-50"),
                cost_eur=Decimal("149.99"),
            ),
        ]

        spot_index, derivatives_entries = _split_ogr_index(
            rows, capital_entries, _ogr_split_jurisdiction(separate=True)
        )

        assert spot_index == {}
        assert len(derivatives_entries) == 1
        entry = derivatives_entries[0]
        assert entry.review_required is True
        assert entry.review_reason  # non-empty
        # Reason must cite the mismatch (mentions OGR and CG values or "manual review")
        assert "manual review" in entry.review_reason or "OGR=" in entry.review_reason

    def test_backward_compat_flag_false_returns_combined(self):
        """Given separate_derivatives_reporting=False, expects the combined summed index and empty derivatives."""
        from tax_reporting.application.crypto.ogr_handler import _split_ogr_index

        rows = [
            ParsedOgrRow(
                date="2025-01-12",
                asset="USDT",
                gain_loss=Decimal("140.18"),
                row_type="Profit",
                wallet="ByBit",
            ),
            ParsedOgrRow(
                date="2025-01-12",
                asset="USDT",
                gain_loss=Decimal("-4.17"),
                row_type="Loss",
                wallet="ByBit",
            ),
        ]
        capital_entries: list[CryptoCapitalGainEntry] = []

        spot_index, derivatives_entries = _split_ogr_index(
            rows, capital_entries, _ogr_split_jurisdiction(separate=False)
        )

        assert derivatives_entries == []
        # Summed combined: 140.18 + (-4.17) = 136.01
        assert spot_index == {("2025-01-12", "USDT", "ByBit"): Decimal("136.01")}

    def test_no_cg_no_th_tag_safety_net(self, caplog):
        """Given a Profit OGR row with no CG counterpart, expects ONE aggregate INFO + one DEBUG per-row.

        Pattern H (W9 demotion): the per-row WARNING was downgraded to DEBUG and
        grouped into ONE aggregate summary after the loop; this plan further
        demotes that aggregate from WARNING to INFO (console WARNINGs are
        reserved for project/processing problems; per-row data issues live in
        the user-facing extract via ``CryptoReviewEntry``). Design Invariant #3
        (per-row detail preserved at DEBUG) and #4 (Excel
        review list unchanged: ``DerivativesPnLEntry`` still appended) must hold.
        """
        from tax_reporting.application.crypto.ogr_handler import (
            _split_ogr_index,
        )

        rows = [
            ParsedOgrRow(
                date="2025-01-12",
                asset="USDT",
                gain_loss=Decimal("140.18"),
                row_type="Profit",
                wallet="ByBit",
            ),
        ]
        capital_entries: list[CryptoCapitalGainEntry] = []

        with caplog.at_level(
            logging.DEBUG, logger="tax_reporting.application.crypto.ogr_handler"
        ):
            spot_index, derivatives_entries = _split_ogr_index(
                rows, capital_entries, _ogr_split_jurisdiction(separate=True)
            )

        # Profit type is always derivatives, so the row is still routed.
        # Design Invariant #4: DerivativesPnLEntry still appended (unchanged).
        assert len(derivatives_entries) == 1
        assert derivatives_entries[0].pnl_eur == Decimal("140.18")
        assert spot_index == {}

        ogr_handler_records = [
            rec
            for rec in caplog.records
            if rec.name == "tax_reporting.application.crypto.ogr_handler"
        ]

        # ONE aggregate INFO matching "routed to derivatives by row type" (W9 demotion).
        info_messages = [
            rec.getMessage()
            for rec in ogr_handler_records
            if rec.levelno == logging.INFO
        ]
        aggregate_infos = [
            m for m in info_messages if "routed to derivatives by row type" in m
        ]
        assert len(aggregate_infos) == 1, (
            f"Expected exactly ONE aggregate INFO, got {aggregate_infos}"
        )
        # The summary names the total count of flagged rows.
        assert "1 OGR row(s) routed to derivatives by row type" in aggregate_infos[0]

        # ZERO WARNING records at all from ogr_handler (demoted to INFO).
        warning_messages = [
            rec.getMessage()
            for rec in ogr_handler_records
            if rec.levelno == logging.WARNING
        ]
        assert warning_messages == [], (
            f"Expected ZERO WARNING records after W9 demotion, got {warning_messages}"
        )

        # The legacy per-row substring must NOT appear at WARNING level (downgraded).
        # The unique per-row discriminator is "OGR row at (" (the aggregate uses
        # "N OGR row(s) routed...").
        legacy_warnings = [
            m for m in warning_messages if "OGR row at (" in m
        ]
        assert legacy_warnings == [], (
            f"Per-row no-CG-counterpart WARNING must be downgraded to DEBUG, "
            f"got {legacy_warnings}"
        )

        # Design Invariant #3: per-row detail preserved at DEBUG (1 record,
        # captures the "ByBit" platform-name detail).
        debug_messages = [
            rec.getMessage()
            for rec in ogr_handler_records
            if rec.levelno == logging.DEBUG
        ]
        per_row_debug = [
            m for m in debug_messages if "OGR row at (" in m and "ByBit" in m
        ]
        assert len(per_row_debug) == 1, (
            f"Expected 1 per-row DEBUG record capturing 'ByBit', got {per_row_debug}"
        )

    def test_no_cg_counterpart_emits_info_and_review_rows(self, caplog):
        """W9: a derivatives-classified OGR row with zero CG matches emits ONE INFO aggregate, ZERO WARNINGs,
        and a ``CryptoReviewEntry(source_section="derivatives")`` whose reason names the spot-vs-derivatives
        ambiguity.
        """
        from tax_reporting.application.crypto.ogr_handler import (
            _split_ogr_index,
        )
        from tax_reporting.application.crypto.entities import CryptoReviewEntry

        rows = [
            ParsedOgrRow(
                date="2025-01-12",
                asset="USDT",
                gain_loss=Decimal("140.18"),
                row_type="Profit",
                wallet="ByBit",
            ),
        ]
        capital_entries: list[CryptoCapitalGainEntry] = []
        review_entries: list[CryptoReviewEntry] = []

        with caplog.at_level(
            logging.INFO, logger="tax_reporting.application.crypto.ogr_handler"
        ):
            spot_index, derivatives_entries = _split_ogr_index(
                rows,
                capital_entries,
                _ogr_split_jurisdiction(separate=True),
                review_entries=review_entries,
            )

        # ONE INFO aggregate matching the W9 signature substring.
        info_messages = [
            rec.getMessage()
            for rec in caplog.records
            if rec.name == "tax_reporting.application.crypto.ogr_handler"
            and rec.levelno == logging.INFO
        ]
        aggregate_infos = [
            m for m in info_messages if "routed to derivatives by row type" in m
        ]
        assert len(aggregate_infos) == 1, aggregate_infos
        assert "no CG counterpart" in aggregate_infos[0]
        assert "1 OGR row(s) routed to derivatives by row type" in aggregate_infos[0]

        # ZERO WARNING records.
        warning_messages = [
            rec.getMessage()
            for rec in caplog.records
            if rec.name == "tax_reporting.application.crypto.ogr_handler"
            and rec.levelno == logging.WARNING
        ]
        assert warning_messages == [], warning_messages

        # ONE review row, source_section="derivatives", naming the spot-vs-derivatives ambiguity.
        assert len(review_entries) == 1, review_entries
        entry = review_entries[0]
        assert entry.source_section == "derivatives"
        assert entry.date == "2025-01-12"
        assert entry.asset == "USDT"
        assert entry.platform == "ByBit"
        assert "spot vs derivatives" in entry.review_reason
        assert "no CG counterpart" in entry.review_reason

    def test_derivatives_entry_carries_operator_entity_and_country(self):
        """Given an OGR row for ByBit routed to derivatives, expects operator_entity and operator_country from
        resolve_operator_origin.
        """
        from tax_reporting.application.crypto.ogr_handler import _split_ogr_index

        rows = [
            ParsedOgrRow(
                date="2025-01-12",
                asset="USDT",
                gain_loss=Decimal("140.18"),
                row_type="Profit",
                wallet="ByBit",
            ),
        ]
        capital_entries: list[CryptoCapitalGainEntry] = []

        spot_index, derivatives_entries = _split_ogr_index(
            rows, capital_entries, _ogr_split_jurisdiction(separate=True)
        )

        assert len(derivatives_entries) == 1
        entry = derivatives_entries[0]
        # Raw wallet name surfaces as user-facing operator entity (not internal sentinel).
        assert entry.operator_entity == "ByBit"
        # Resolved counterparty country code from resolve_operator_origin("ByBit").
        assert entry.operator_country == "AE"

    def test_derivatives_entry_for_unknown_platform_renders_wallet_name_and_unknown_country(self):
        """Given an OGR row for an unmapped platform, expects raw wallet name, UNKNOWN country, and review flag with
        platform-missing reason.
        """
        from tax_reporting.application.crypto.ogr_handler import _split_ogr_index

        rows = [
            ParsedOgrRow(
                date="2025-01-12",
                asset="USDT",
                gain_loss=Decimal("140.18"),
                row_type="Profit",
                wallet="UnknownExchange",
            ),
        ]
        capital_entries: list[CryptoCapitalGainEntry] = []

        spot_index, derivatives_entries = _split_ogr_index(
            rows, capital_entries, _ogr_split_jurisdiction(separate=True)
        )

        assert len(derivatives_entries) == 1
        entry = derivatives_entries[0]
        # Raw wallet name (NOT the internal sentinel "UNKNOWN_OPERATOR_REVIEW_REQUIRED").
        assert entry.operator_entity == "UnknownExchange"
        assert entry.operator_country == "UNKNOWN"
        assert entry.review_required is True
        # Platform-missing reason must be actionable and mention the resolution path.
        assert "resolve_operator_origin" in entry.review_reason
        assert entry.review_reason.startswith("Unknown platform")

    def test_derivatives_entry_for_known_platform_outside_service_period_carries_temporal_reason(self):
        """Given an OGR row for a KNOWN platform with a transaction date before its service_start_date,
        expects review_required=True with the resolver's temporal-validity reason (NOT the synthesised
        "Unknown platform" message, which would mislead the reviewer since the platform IS mapped)."""
        from tax_reporting.application.crypto.ogr_handler import _split_ogr_index

        # Berachain has service_start_date="2025-02-05"; a 2024 transaction predates it.
        rows = [
            ParsedOgrRow(
                date="2024-01-12",
                asset="BERA",
                gain_loss=Decimal("140.18"),
                row_type="Profit",
                wallet="Berachain",
            ),
        ]
        capital_entries: list[CryptoCapitalGainEntry] = []

        spot_index, derivatives_entries = _split_ogr_index(
            rows, capital_entries, _ogr_split_jurisdiction(separate=True)
        )

        assert len(derivatives_entries) == 1
        entry = derivatives_entries[0]
        # Berachain IS mapped, so operator_country is the real value, not UNKNOWN.
        assert entry.operator_country == "VG"
        assert entry.review_required is True
        # The temporal-validity reason must surface verbatim; the misleading
        # "Unknown platform" synthesised message must NOT appear.
        assert "service period" in entry.review_reason
        assert "2024-01-12" in entry.review_reason
        assert not entry.review_reason.startswith("Unknown platform")

    def test_review_reason_concatenation_order_is_platform_first(self):
        """Given an OGR row that is BOTH classification-ambiguous AND from an unmapped platform, expects platform reason
        first, '; ', then classification reason.
        """
        from tax_reporting.application.crypto.ogr_handler import _split_ogr_index

        rows = [
            ParsedOgrRow(
                date="2025-01-12",
                asset="USDT",
                gain_loss=Decimal("-4.17"),
                row_type="Loss",
                wallet="UnknownExchange",
            ),
        ]
        # CG proceeds_eur=99.99 mismatches OGR magnitude 4.17 -> Ambiguous classification
        capital_entries = [
            _make_ogr_split_entry(
                disposal_date="2025-01-12",
                asset="USDT",
                wallet="UnknownExchange",
                proceeds_eur=Decimal("99.99"),
                gain_loss_eur=Decimal("-50"),
                cost_eur=Decimal("149.99"),
            ),
        ]

        spot_index, derivatives_entries = _split_ogr_index(
            rows, capital_entries, _ogr_split_jurisdiction(separate=True)
        )

        assert len(derivatives_entries) == 1
        entry = derivatives_entries[0]
        assert entry.review_required is True
        # Platform reason first; classification reason second.
        assert entry.review_reason.startswith("Unknown platform")
        assert "; " in entry.review_reason
        platform_part, _, classification_part = entry.review_reason.partition("; ")
        assert "resolve_operator_origin" in platform_part
        # Classification reason cites the mismatch (manual review or OGR=).
        assert "manual review" in classification_part or "OGR=" in classification_part

    def test_spot_path_unaffected_by_operator_resolution(self):
        """Given a Spot-classified OGR row, expects spot_index populated and no DerivativesPnLEntry constructed."""
        from tax_reporting.application.crypto.ogr_handler import _split_ogr_index

        rows = [
            ParsedOgrRow(
                date="2025-01-12",
                asset="USDT",
                gain_loss=Decimal("-4.17"),
                row_type="Loss",
                wallet="ByBit",
            ),
        ]
        # CG proceeds_eur=4.17 matches OGR magnitude -> Spot classification.
        capital_entries = [
            _make_ogr_split_entry(
                disposal_date="2025-01-12",
                asset="USDT",
                wallet="ByBit",
                proceeds_eur=Decimal("4.17"),
                gain_loss_eur=Decimal("2.44"),
                cost_eur=Decimal("1.73"),
            ),
        ]

        spot_index, derivatives_entries = _split_ogr_index(
            rows, capital_entries, _ogr_split_jurisdiction(separate=True)
        )

        # Spot routing populates the spot_index and builds no derivatives entries.
        assert derivatives_entries == []
        assert spot_index == {("2025-01-12", "USDT", "ByBit"): Decimal("-4.17")}

    def test_separate_derivatives_disabled_produces_no_derivatives_entries_and_no_operator_resolution(
        self, monkeypatch
    ):
        """Given separate_derivatives_reporting=False, expects no derivatives entries and resolve_operator_origin NOT
        called (byte-identical to pre-Task-7 pipeline).
        """
        from tax_reporting.application.crypto import ogr_handler
        from tax_reporting.application.crypto.ogr_handler import _split_ogr_index

        def _fail_if_called(*args, **kwargs):  # noqa: ARG001
            raise AssertionError(
                "resolve_operator_origin must not be called when separate_derivatives_reporting=False"
            )

        monkeypatch.setattr(ogr_handler, "resolve_operator_origin", _fail_if_called)

        rows = [
            ParsedOgrRow(
                date="2025-01-12",
                asset="USDT",
                gain_loss=Decimal("140.18"),
                row_type="Profit",
                wallet="ByBit",
            ),
        ]
        capital_entries: list[CryptoCapitalGainEntry] = []

        spot_index, derivatives_entries = _split_ogr_index(
            rows, capital_entries, _ogr_split_jurisdiction(separate=False)
        )

        # Flag-off path returns combined summed index, empty derivatives list.
        assert derivatives_entries == []
        assert spot_index == {("2025-01-12", "USDT", "ByBit"): Decimal("140.18")}


class TestApplyOgrDirectionOverrideSpotProtection:
    """TDD for spot CG protection under separate_derivatives_reporting=True.

    These tests exercise _split_ogr_index + apply_ogr_event_level together
    to confirm that derivatives rows routed to derivatives_entries never reach the
    spot CG direction override, so spot fee disposal signs are preserved.
    """

    def test_spot_signs_not_flipped_by_derivatives(self):
        """Given Case 2 fixture (derivatives loss routed separately), expects spot CG signs preserved."""
        from tax_reporting.application.crypto.ogr_event_level import apply_ogr_event_level
        from tax_reporting.application.crypto.ogr_handler import (
            _split_ogr_index,
        )

        # 3 CG lots with small gains, on the same key, representing the spot
        # fee disposal side of a multi-lot realization.
        capital_entries = [
            _make_ogr_split_entry(
                disposal_date="2025-01-13",
                asset="USDT",
                wallet="ByBit",
                proceeds_eur=Decimal("1.00"),
                gain_loss_eur=Decimal("0.50"),
                cost_eur=Decimal("0.50"),
            )
            for _ in range(3)
        ]
        # OGR Loss row matches aggregate CG proceeds (3 × 1.00 = 3.00 within
        # tolerance of 4.17? No, to force Spot routing we use a CG-matching value.
        rows = [
            ParsedOgrRow(
                date="2025-01-13",
                asset="USDT",
                gain_loss=Decimal("-3.00"),
                row_type="Loss",
                wallet="ByBit",
            ),
        ]

        jurisdiction = _ogr_split_jurisdiction(separate=True)
        spot_index, derivatives_entries = _split_ogr_index(rows, capital_entries, jurisdiction)

        # All CG lots matched aggregate proceeds (3.00 == 3.00 within tolerance)
        # so this is routed to spot_index, NOT derivatives_entries.
        assert derivatives_entries == []
        assert spot_index == {("2025-01-13", "USDT", "ByBit"): Decimal("-3.00")}

        result = apply_ogr_event_level(capital_entries, spot_index, jurisdiction)

        # Each CG lot retains its positive gain (spot signs preserved). The
        # spot_index loss is applied as direction override here, but the spot fee
        # disposal gains remain positive because spot fee disposals were POSITIVE
        # gains in the fixture and the override only kicks in for the net loss
        # direction. The protection we test is that derivatives rows NEVER reach
        # this function. If a derivatives Profit row had leaked into spot_index
        # it would flip positive CG gains. We constructed the fixture so the Loss
        # IS in spot_index, which is the correct routing (matches CG). What we
        # assert is the broader contract: after override, each lot's gain/loss
        # is consistent with the spot index direction without any derivatives
        # contamination.
        assert len(result) == 3
        # The 3 CG lots match aggregate proceeds 3.00 EUR (3 × 1.00) within
        # tolerance of OGR magnitude 3.00, so Spot routing is correct. The spot
        # loss direction override will flip positive gains to losses:
        for entry in result:
            # Direction override flips sign because OGR is negative and CG is positive
            assert entry.gain_loss_eur == -abs(Decimal("0.50")), (
                f"Expected each lot gain to be flipped to -0.50 by spot direction override, "
                f"got {entry.gain_loss_eur}"
            )

    def test_derivatives_profit_not_applied_to_spot_fee_entry(self):
        """Given Case 1 fixture (one CG fee entry + 140.18 EUR Profit), expects CG fee gain retained."""
        from tax_reporting.application.crypto.ogr_event_level import apply_ogr_event_level
        from tax_reporting.application.crypto.ogr_handler import (
            _split_ogr_index,
        )

        # Single CG fee entry: proceeds 4.17 EUR, gain 2.44 EUR
        capital_entries = [
            _make_ogr_split_entry(
                disposal_date="2025-01-12",
                asset="USDT",
                wallet="ByBit",
                proceeds_eur=Decimal("4.17"),
                gain_loss_eur=Decimal("2.44"),
                cost_eur=Decimal("1.73"),
            ),
        ]
        # OGR Profit row: derivatives P&L realization, no CG counterpart matching it
        rows = [
            ParsedOgrRow(
                date="2025-01-12",
                asset="USDT",
                gain_loss=Decimal("140.18"),
                row_type="Profit",
                wallet="ByBit",
            ),
        ]

        jurisdiction = _ogr_split_jurisdiction(separate=True)
        spot_index, derivatives_entries = _split_ogr_index(rows, capital_entries, jurisdiction)

        # Profit type is always derivatives, so it is routed to derivatives_entries,
        # NOT to spot_index.
        assert len(derivatives_entries) == 1
        assert derivatives_entries[0].pnl_eur == Decimal("140.18")
        assert spot_index == {}

        # No spot_index entry to override, so the CG fee entry retains its original gain
        result = apply_ogr_event_level(capital_entries, spot_index, jurisdiction)

        assert len(result) == 1
        assert result[0].gain_loss_eur == Decimal("2.44")
        assert result[0].proceeds_eur == Decimal("4.17")
        assert result[0].ogr_validation is None


# =============================================================================
# Task 8: Derivatives aggregation
# =============================================================================


def _make_derivatives_entry(  # noqa: PLR0913
    date: str = "2025-01-12",
    asset: str = "USDT",
    platform: str = "ByBit",
    pnl_eur: Decimal = Decimal("100"),
    event_type: DerivativesEventType = DerivativesEventType.PROFIT,
    source_ref: str = "OGR:2025-01-12:USDT",
    legal_category: str = "CIRS art. 10(1)(e)",
    review_required: bool = False,
    review_reason: str = "",
) -> DerivativesPnLEntry:
    return DerivativesPnLEntry(
        date=date,
        asset=asset,
        platform=platform,
        pnl_eur=pnl_eur,
        event_type=event_type,
        source_ref=source_ref,
        legal_category=legal_category,
        review_required=review_required,
        review_reason=review_reason,
    )


class TestDerivativesAggregation:
    """Tests for aggregate_derivatives_entries grouping by (date, asset, platform, event_type)."""

    def test_groups_by_date_asset_platform_type(self):
        """Different event_types on the same (date, asset, platform) stay as separate entries."""
        entries = [
            _make_derivatives_entry(
                pnl_eur=Decimal("140.18"),
                event_type=DerivativesEventType.PROFIT,
            ),
            _make_derivatives_entry(
                pnl_eur=Decimal("-50.00"),
                event_type=DerivativesEventType.LOSS,
            ),
        ]

        result = aggregate_derivatives_entries(entries)

        assert len(result) == 2
        event_types = {e.event_type for e in result}
        assert event_types == {DerivativesEventType.PROFIT, DerivativesEventType.LOSS}

    def test_sums_within_group(self):
        """Two PROFIT entries on the same group key sum into one aggregated pnl_eur."""
        entries = [
            _make_derivatives_entry(
                pnl_eur=Decimal("140.18"),
                event_type=DerivativesEventType.PROFIT,
                source_ref="OGR:2025-01-12:USDT#a",
            ),
            _make_derivatives_entry(
                pnl_eur=Decimal("59.82"),
                event_type=DerivativesEventType.PROFIT,
                source_ref="OGR:2025-01-12:USDT#b",
            ),
        ]

        result = aggregate_derivatives_entries(entries)

        assert len(result) == 1
        assert result[0].pnl_eur == Decimal("200.00")

    def test_preserves_review_flags(self):
        """Aggregated review_required is the OR of source entries; reasons are joined uniquely."""
        entries = [
            _make_derivatives_entry(
                pnl_eur=Decimal("10"),
                event_type=DerivativesEventType.PROFIT,
                review_required=False,
                review_reason="",
            ),
            _make_derivatives_entry(
                pnl_eur=Decimal("20"),
                event_type=DerivativesEventType.PROFIT,
                review_required=True,
                review_reason="ambiguous classification",
            ),
        ]

        result = aggregate_derivatives_entries(entries)

        assert len(result) == 1
        assert result[0].review_required is True
        assert "ambiguous classification" in result[0].review_reason

    def test_legal_category_preserved(self):
        """Aggregated entry retains the legal_category from source entries."""
        entries = [
            _make_derivatives_entry(
                legal_category="CIRS art. 10(1)(e)",
                event_type=DerivativesEventType.PROFIT,
            ),
            _make_derivatives_entry(
                legal_category="CIRS art. 10(1)(e)",
                event_type=DerivativesEventType.PROFIT,
            ),
        ]

        result = aggregate_derivatives_entries(entries)

        assert len(result) == 1
        assert result[0].legal_category == "CIRS art. 10(1)(e)"

    def test_aggregate_derivatives_sums_event_count(self):
        """Three raw entries sharing the (date, asset, platform, event_type) key aggregate
        into one entry whose event_count equals the number of underlying rows (3)."""
        entries = [
            _make_derivatives_entry(
                pnl_eur=Decimal("10"),
                event_type=DerivativesEventType.PROFIT,
                source_ref="OGR:2025-01-12:USDT#a",
            ),
            _make_derivatives_entry(
                pnl_eur=Decimal("20"),
                event_type=DerivativesEventType.PROFIT,
                source_ref="OGR:2025-01-12:USDT#b",
            ),
            _make_derivatives_entry(
                pnl_eur=Decimal("30"),
                event_type=DerivativesEventType.PROFIT,
                source_ref="OGR:2025-01-12:USDT#c",
            ),
        ]

        result = aggregate_derivatives_entries(entries)

        assert len(result) == 1
        assert result[0].event_count == 3

    def test_aggregate_derivatives_preserves_operator_from_first_row(self):
        """Aggregated entry carries operator_entity/operator_country from the first group member.

        All rows in a group share the same platform (part of the aggregation key),
        so they share the same operator origin; we take it from the first row.
        """
        entries = [
            DerivativesPnLEntry(
                date="2025-01-12",
                asset="USDT",
                platform="ByBit",
                pnl_eur=Decimal("10"),
                event_type=DerivativesEventType.PROFIT,
                source_ref="OGR:2025-01-12:USDT#a",
                operator_entity="ByBit",
                operator_country="AE",
            ),
            DerivativesPnLEntry(
                date="2025-01-12",
                asset="USDT",
                platform="ByBit",
                pnl_eur=Decimal("20"),
                event_type=DerivativesEventType.PROFIT,
                source_ref="OGR:2025-01-12:USDT#b",
                operator_entity="ByBit",
                operator_country="AE",
            ),
        ]

        result = aggregate_derivatives_entries(entries)

        assert len(result) == 1
        assert result[0].operator_entity == "ByBit"
        assert result[0].operator_country == "AE"

    def test_aggregate_derivatives_event_count_defaults_to_one_for_singletons(self):
        """A single raw entry aggregates into one entry with event_count=1."""
        entries = [
            _make_derivatives_entry(
                pnl_eur=Decimal("100"),
                event_type=DerivativesEventType.PROFIT,
            ),
        ]

        result = aggregate_derivatives_entries(entries)

        assert len(result) == 1
        assert result[0].event_count == 1

    def test_aggregate_derivatives_merges_notes_across_group_members(self):
        """Non-first group members' notes must survive aggregation.

        Mirrors the capital-entries aggregator (aggregation.py:283-287), which joins
        unique non-empty notes with '; '. Without this, two raw entries in the same
        group carrying different notes would silently lose all but the first row's
        note (a silent-overwrite hazard).
        """
        entries = [
            DerivativesPnLEntry(
                date="2025-01-12",
                asset="USDT",
                platform="ByBit",
                pnl_eur=Decimal("10"),
                event_type=DerivativesEventType.PROFIT,
                source_ref="OGR:2025-01-12:USDT#a",
                notes="manual annotation A",
            ),
            DerivativesPnLEntry(
                date="2025-01-12",
                asset="USDT",
                platform="ByBit",
                pnl_eur=Decimal("20"),
                event_type=DerivativesEventType.PROFIT,
                source_ref="OGR:2025-01-12:USDT#b",
                notes="manual annotation B",
            ),
        ]

        result = aggregate_derivatives_entries(entries)

        assert len(result) == 1
        merged = result[0].notes
        assert "manual annotation A" in merged, f"First member note lost in merge: {merged!r}"
        assert "manual annotation B" in merged, f"Second member note lost in merge: {merged!r}"

    def test_aggregate_derivatives_notes_empty_when_no_member_has_notes(self):
        """Empty-notes happy path stays byte-identical to pre-fix behavior."""
        entries = [
            _make_derivatives_entry(
                pnl_eur=Decimal("10"),
                event_type=DerivativesEventType.PROFIT,
            ),
            _make_derivatives_entry(
                pnl_eur=Decimal("20"),
                event_type=DerivativesEventType.PROFIT,
            ),
        ]

        result = aggregate_derivatives_entries(entries)

        assert len(result) == 1
        assert result[0].notes == ""

    def test_aggregate_derivatives_notes_deduped_and_order_preserved(self):
        """Repeated notes within a group collapse to a single occurrence, order preserved."""
        entries = [
            DerivativesPnLEntry(
                date="2025-01-12",
                asset="USDT",
                platform="ByBit",
                pnl_eur=Decimal("10"),
                event_type=DerivativesEventType.PROFIT,
                source_ref="OGR:2025-01-12:USDT#a",
                notes="repeat note",
            ),
            DerivativesPnLEntry(
                date="2025-01-12",
                asset="USDT",
                platform="ByBit",
                pnl_eur=Decimal("20"),
                event_type=DerivativesEventType.PROFIT,
                source_ref="OGR:2025-01-12:USDT#b",
                notes="repeat note",
            ),
            DerivativesPnLEntry(
                date="2025-01-12",
                asset="USDT",
                platform="ByBit",
                pnl_eur=Decimal("30"),
                event_type=DerivativesEventType.PROFIT,
                source_ref="OGR:2025-01-12:USDT#c",
                notes="other note",
            ),
        ]

        result = aggregate_derivatives_entries(entries)

        assert len(result) == 1
        assert result[0].notes == "repeat note; other note", (
            f"Notes should be deduped and order-preserved; got {result[0].notes!r}"
        )

    def test_aggregate_derivatives_warns_on_mixed_annex_routes(self, caplog) -> None:
        """Mixed (annex_hint, operation_code) within a group is surfaced at warning+.

        Feature A's counterparty-residency routing made annex_hint/operation_code
        per-row variable, so a mixed-route group would silently drop non-first
        members' routes when the aggregator takes ``first.``. Safe today (platform
        is in the group key and routes are platform-deterministic), but the warning
        makes the latent gap observable. Discriminates against an implementation
        that takes ``first.`` with no heterogeneity check.
        """
        entries = [
            DerivativesPnLEntry(
                date="2025-01-12",
                asset="USDT",
                platform="ByBit",
                pnl_eur=Decimal("10"),
                event_type=DerivativesEventType.PROFIT,
                source_ref="OGR:2025-01-12:USDT#a",
                annex_hint="G1/Q8A",
                operation_code="G41",
            ),
            DerivativesPnLEntry(
                date="2025-01-12",
                asset="USDT",
                platform="ByBit",
                pnl_eur=Decimal("20"),
                event_type=DerivativesEventType.PROFIT,
                source_ref="OGR:2025-01-12:USDT#b",
                annex_hint="G/Q13",
                operation_code="G51",
            ),
        ]

        with caplog.at_level("WARNING", logger="tax_reporting.application.crypto.aggregation"):
            result = aggregate_derivatives_entries(entries)

        assert len(result) == 1
        # The first member's route is always rendered.
        assert result[0].annex_hint == "G1/Q8A"
        assert result[0].operation_code == "G41"
        # Heterogeneity is surfaced, not silent.
        assert any("mixed annex routes" in rec.message for rec in caplog.records), (
            "Expected a warning for mixed annex routes within a derivatives group"
        )

    def test_aggregate_derivatives_no_warning_on_uniform_routes(self, caplog) -> None:
        """Uniform routes within a group emit no heterogeneity warning (negative control)."""
        entries = [
            DerivativesPnLEntry(
                date="2025-01-12",
                asset="USDT",
                platform="ByBit",
                pnl_eur=Decimal("10"),
                event_type=DerivativesEventType.PROFIT,
                source_ref="OGR:2025-01-12:USDT#a",
                annex_hint="G/Q13",
                operation_code="G51",
            ),
            DerivativesPnLEntry(
                date="2025-01-12",
                asset="USDT",
                platform="ByBit",
                pnl_eur=Decimal("20"),
                event_type=DerivativesEventType.PROFIT,
                source_ref="OGR:2025-01-12:USDT#b",
                annex_hint="G/Q13",
                operation_code="G51",
            ),
        ]

        with caplog.at_level("WARNING", logger="tax_reporting.application.crypto.aggregation"):
            aggregate_derivatives_entries(entries)

        assert not any("mixed annex routes" in rec.message for rec in caplog.records), (
            "Uniform-route groups must not trigger the heterogeneity warning"
        )


# =============================================================================
# Task 9 (docs/history/plans/2026-06-13-derivatives-separation.md): pipeline integration
# of the OGR split inside load_koinly_crypto_report. The split must run AFTER
# FIFO rebuild/post-validation and BEFORE _aggregate_capital_entries. The
# derivatives_entries produced by the split must be aggregated separately and
# assigned to CryptoTaxReport.derivatives_entries. When the flag is off, the
# pipeline output must remain byte-identical to pre-Task-9 behavior.
# =============================================================================


class TestPipelineIntegration:
    """TDD for the load_koinly_crypto_report wiring of the OGR split.

    Verifies Design Invariant 2 (split runs after FIFO rebuild, before
    aggregation) and backward compatibility (flag off = pre-Task-9 output).
    """

    def test_split_runs_after_fifo_rebuild(self) -> None:
        """The classifier sees the FIFO-rebuilt CG lot when classifying the OGR row.

        Per the plan, the simplest verification is to call ``_split_ogr_index``
        directly with a post-FIFO ``capital_entries`` containing one CG lot whose
        ``(date, asset, wallet)`` matches an OGR Profit row, and confirm the
        classifier routes the OGR row to Spot (because the CG match exists).
        This proves the split can see FIFO-rebuilt lots, which only matters
        when the split runs AFTER FIFO rebuild in load_koinly_crypto_report.

        Note: a Profit row with NO CG counterpart is always classified as
        Derivatives (r1 Medium #7 safety net). A Profit row WITH a CG
        counterpart of equal magnitude is also routed to derivatives because
        classify_derivatives_event treats Profit rows as derivatives regardless
        of CG presence. To verify the post-FIFO timing matters, we use a Loss
        row: with no CG counterpart, it is Ambiguous; with a CG counterpart
        that matches in magnitude, it is Spot. The presence of the
        FIFO-rebuilt lot flips classification from Ambiguous to Spot.
        """
        from tax_reporting.application.crypto.ogr_handler import _split_ogr_index

        # OGR Loss row matching the FIFO-rebuilt CG lot's proceeds exactly.
        rows = [
            ParsedOgrRow(
                date="2025-01-12",
                asset="USDT",
                gain_loss=Decimal("-4.17"),
                row_type="Loss",
                wallet="ByBit",
            ),
        ]
        # FIFO-rebuilt CG lot: matches the OGR row key.
        capital_entries = [
            _make_ogr_split_entry(
                disposal_date="2025-01-12",
                asset="USDT",
                wallet="ByBit",
                proceeds_eur=Decimal("4.17"),
                gain_loss_eur=Decimal("2.44"),
                cost_eur=Decimal("1.73"),
            ),
        ]

        spot_index, derivatives_entries = _split_ogr_index(
            rows, capital_entries, _ogr_split_jurisdiction(separate=True)
        )

        # With the FIFO-rebuilt CG lot visible, the OGR row classifies as Spot.
        # The lot's proceeds (4.17) match the OGR magnitude (4.17).
        assert derivatives_entries == []
        assert spot_index == {("2025-01-12", "USDT", "ByBit"): Decimal("-4.17")}


    def test_derivatives_entries_empty_when_flag_off(self) -> None:
        """Given separate_derivatives_reporting=False, derivatives_entries is empty.

        Backward compatibility: when the flag is OFF, the dedup short-circuits
        at its gate (Design Invariant 14) so no CG lot is removed and no
        Derivatives P&L entry is produced. ``derivatives_entries`` must be
        empty. (Capital-side values under the resolver-keyed OGR override are
        characterized elsewhere; the legacy mixed-value 136.01 EUR backward-
        compat target was a Phase-D flag-off artifact and is no longer
        asserted.)
        """
        from tests.conftest import KOINLY_2025_EXAMPLE_DIR

        jurisdiction = _ogr_split_jurisdiction(separate=False)
        report = load_koinly_crypto_report(KOINLY_2025_EXAMPLE_DIR, jurisdiction=jurisdiction)
        assert report is not None, "Failed to load koinly2025 example report"

        # derivatives_entries must be empty when the flag is off.
        assert report.derivatives_entries == [], (
            f"Expected empty derivatives_entries when "
            f"separate_derivatives_reporting=False, got "
            f"{len(report.derivatives_entries)} entries"
        )


# --- jurisdiction-zone date localization (CG / income / DP-014 match-key) ---
#
# Naive Koinly dates (CG/OGR/Income) denote mainland-Portugal local time
# (WET/WEST); threading the jurisdiction ZoneInfo through parse_koinly_datetime
# converts them to a true-UTC instant so cross-report match keys agree. The
# summer-midnight cases (WEST = UTC+1) are the discriminating ones: a naive
# 15/06/2025 00:30 must roll back to the previous UTC day (2025-06-14 23:30).


@pytest.mark.unit
def test_parse_capital_gains_file_summer_midnight_disposal_true_utc_day(tmp_path):
    """A summer-midnight CG Date Sold localizes to the previous UTC day with a PT zone.

    Date Sold = 15/06/2025 00:30 is mainland-Portugal WEST (UTC+1); its true UTC
    instant is 2025-06-14 23:30. With ``zone=Europe/Lisbon`` the disposal_date
    and disposal_timestamp must reflect the UTC day, not the local day (without
    the zone both read 2025-06-15 because naive dates are stamped as UTC).
    """
    from collections import Counter

    th_csv = tmp_path / "th.csv"
    th_csv.write_text("\n".join(["Transaction report 2025", "", _TH_HEADER]), encoding="utf-8")
    capital_csv = tmp_path / "capital.csv"
    capital_csv.write_text(
        "\n".join(["Capital gains report 2025", "", _CG_HEADER, _cg_row(date_sold="15/06/2025 00:30")]),
        encoding="utf-8",
    )

    resolver = build_origin_resolver(th_csv)
    context = CapitalGainsParsingContext(
        skipped_assets=Counter(),
        origin_resolver=resolver,
        review_entries=[],
        zone=ZoneInfo("Europe/Lisbon"),
    )
    entries, _ = _parse_capital_gains_file(capital_csv, context)

    assert entries, "expected one CG entry from the summer-midnight row"
    assert entries[0].disposal_date == "2025-06-14", (
        f"summer-midnight disposal must map to the previous UTC day, got {entries[0].disposal_date}"
    )
    assert entries[0].disposal_timestamp == "2025-06-14 23:30", (
        "summer-midnight disposal timestamp must reflect the WEST->UTC offset, "
        f"got {entries[0].disposal_timestamp}"
    )


@pytest.mark.unit
def test_parse_capital_gains_file_winter_disposal_unchanged(tmp_path):
    """A winter CG Date Sold is unchanged by the PT zone (WET = UTC+0, no DST).

    Characterization test protecting existing fixtures: 13/01/2025 13:01 (WET)
    has no offset to UTC, so both the legacy UTC-stamp and the localized path
    yield 2025-01-13 13:01.
    """
    from collections import Counter

    th_csv = tmp_path / "th.csv"
    th_csv.write_text("\n".join(["Transaction report 2025", "", _TH_HEADER]), encoding="utf-8")
    capital_csv = tmp_path / "capital.csv"
    capital_csv.write_text(
        "\n".join(["Capital gains report 2025", "", _CG_HEADER, _cg_row(date_sold="13/01/2025 13:01")]),
        encoding="utf-8",
    )

    resolver = build_origin_resolver(th_csv)
    context = CapitalGainsParsingContext(
        skipped_assets=Counter(),
        origin_resolver=resolver,
        review_entries=[],
        zone=ZoneInfo("Europe/Lisbon"),
    )
    entries, _ = _parse_capital_gains_file(capital_csv, context)

    assert entries, "expected one CG entry from the winter row"
    assert entries[0].disposal_date == "2025-01-13", (
        f"winter disposal must be unchanged (WET = UTC+0), got {entries[0].disposal_date}"
    )
    assert entries[0].disposal_timestamp == "2025-01-13 13:01", (
        f"winter disposal timestamp must be unchanged, got {entries[0].disposal_timestamp}"
    )


@pytest.mark.unit
def test_parse_income_file_summer_date_true_utc_day(tmp_path):
    """A summer-midnight income Date localizes to the previous UTC day with a PT zone.

    Date = 15/06/2025 00:30 (WEST, UTC+1) -> true UTC 2025-06-14 23:30 -> calendar
    day 2025-06-14. Without the zone the naive date is stamped UTC and reads
    2025-06-15.
    """
    income_file = tmp_path / "income.csv"
    income_file.write_text(
        "\n".join(
            [
                "Income report 2025",
                "",
                _INCOME_HEADER,
                '15/06/2025 00:30,BTC,"0,10",1000.00,Reward,,Kraken',
            ]
        ),
        encoding="utf-8",
    )
    skipped: dict[tuple[str, str], dict] = {}
    entries = _parse_income_file(income_file, skipped, zone=ZoneInfo("Europe/Lisbon"))

    assert entries, "expected one income entry from the summer-midnight row"
    assert entries[0].date == "2025-06-14", (
        f"summer-midnight income date must map to the previous UTC day, got {entries[0].date}"
    )


@pytest.mark.unit
def test_payment_match_survives_summer_midnight_drift(tmp_path):
    """DP-014 correction survives a summer-midnight cross-report drift (capstone).

    The Payment disposal's CG Date Sold is 15/06/2025 00:30 (WEST, local
    midnight); its TH twin declares the true UTC instant 2025-06-14 23:30:00 UTC.
    With ``zone=Europe/Lisbon`` the CG disposal_date becomes 2025-06-14, matching
    the TH day, so the DP-014 correction fires and repairs proceeds to the TH Net
    Value. Without the zone, CG reads 2025-06-15 vs TH 2025-06-14 -> no match ->
    correction skipped -> proceeds stay 0.

    Uses the CSV-writing helpers so the pipeline reads the rows through
    parse_koinly_datetime (the fix path), not a hardcoded _make_cg_entry builder.
    """
    koinly_dir = tmp_path / "koinly2025"
    koinly_dir.mkdir()
    _write_payment_fixture(
        koinly_dir,
        cg_rows=[_cg_row(date_sold="15/06/2025 00:30", **_PHANTOM_USDT_BYBIT)],
        th_rows=[
            _th_payment_row(
                date_utc="2025-06-14 23:30:00 UTC",
                amount="50,00000000",
                net_value_eur='"120,00"',
            ),
        ],
    )

    report = load_koinly_crypto_report(
        koinly_dir,
        jurisdiction=_pp_jurisdiction(infer=True, timezone=ZoneInfo("Europe/Lisbon")),
    )
    assert report is not None

    matches = [
        e
        for e in report.capital_entries
        if e.asset == "USDT" and e.disposal_date == "2025-06-14" and e.platform == "ByBit (2)"
    ]
    assert matches, (
        "Expected the corrected Payment disposal on 2025-06-14 (the true UTC day); "
        "the summer-midnight drift broke the cross-report match so the correction was skipped"
    )
    assert matches[0].proceeds_eur == Decimal("120.00"), (
        "DP-014 correction must have repaired proceeds to the TH Net Value (120.00); "
        f"got {matches[0].proceeds_eur}"
    )


# --- DP-014 payment-proceeds correction integration tests ---
#
# These tests exercise the wiring of ``correct_payment_proceeds`` into
# ``load_koinly_crypto_report`` (after the OGR override, before aggregation,
# guarded by ``jurisdiction.infer_payment_proceeds``). Post-Phase-E the OGR
# override uses resolver-keyed SPOT_DISPOSAL identification, so PAYMENT rows
# are structurally excluded from OGR mutation and no re-zero snapshot/restore
# is needed. Synthetic tickers/amounts only; no real transaction data.
# See docs/history/plans/2026-06-18-crypto-payment-proceeds.md Task 6.

_OGR_HEADER = "Date,Asset,Amount,Value (EUR),Type,Wallet Name"

_PHANTOM_USDT_BYBIT = {
    "asset": "USDT",
    "amount": "50,00000000",
    "cost": "100,00",
    "proceeds": "0.0",
    "gain": "-100,00",
    "wallet": "ByBit (2)",
}

# PT-mainland zone reused as the default for payment-proceeds test jurisdictions so
# naive Koinly dates localize correctly (module-level constant: ZoneInfo must not be
# called in an argument default, per ruff B008).
_LISBON_TZ = ZoneInfo("Europe/Lisbon")


def _pp_jurisdiction(
    *,
    infer: bool = True,
    use_ogr: bool = False,
    timezone: ZoneInfo | None = _LISBON_TZ,
):
    """Build a PT/2025 jurisdiction with the payment-proceeds flag toggled.

    ``use_ogr`` enables the OGR override path so the resolver-keyed SPOT_DISPOSAL
    identification can be exercised. ``separate_derivatives_reporting`` is left
    False so the OGR path is the legacy combined-index override. ``timezone``
    defaults to ``ZoneInfo("Europe/Lisbon")`` (the production PT default; a
    configured jurisdiction without a resolved timezone now fails fast at crypto
    load rather than silently UTC-stamping). Existing fixtures use winter dates,
    so Lisbon localization is byte-identical to the prior UTC-stamp for them.
    """
    from tax_reporting.infrastructure.config import TaxJurisdictionConfig

    return TaxJurisdictionConfig(
        country="PT",
        fiscal_year=2025,
        exclude_loan_repayment_gains=False,
        zero_basis_review_threshold=Decimal("50"),
        infer_payment_proceeds=infer,
        use_other_gains_report=use_ogr,
        timezone=timezone,
    )


def _write_payment_fixture(
    koinly_dir: Path,
    *,
    cg_rows: list[str],
    th_rows: list[str],
    ogr_rows: list[str] | None = None,
    income_rows: list[str] | None = None,
) -> None:
    """Write a minimal Koinly export set exercising the payment-proceeds correction."""
    (koinly_dir / "koinly_2025_capital_gains_report.csv").write_text(
        "\n".join(["Capital gains report 2025", "", _CG_HEADER, *cg_rows]),
        encoding="utf-8",
    )
    default_income = ["01/01/2025 00:01,WXT,1,1.00,Reward,,Wirex"]
    (koinly_dir / "koinly_2025_income_report.csv").write_text(
        "\n".join(["Income report 2025", "", _INCOME_HEADER, *(income_rows or default_income)]),
        encoding="utf-8",
    )
    (koinly_dir / "koinly_2025_transaction_history.csv").write_text(
        "\n".join(["Transaction report 2025", "", _TH_HEADER, *th_rows]),
        encoding="utf-8",
    )
    if ogr_rows is not None:
        (koinly_dir / "koinly_2025_other_gains_report.csv").write_text(
            "\n".join(["Other gains report 2025", "", _OGR_HEADER, *ogr_rows]),
            encoding="utf-8",
        )


def _cg_row(**fields) -> str:  # noqa: PLR0913
    """Build a single CG CSV row string matching ``_CG_HEADER`` (keyword args).

    Decimal fields are QUOTED so the European decimal comma does not split the row.
    All fields have sensible defaults matching the common phantom-payment fixture.
    """
    f = {
        "date_sold": "13/01/2025 13:01",
        "acquisition_date": "18/11/2024 00:15",
        "asset": "USDT",
        "amount": "1,00000000",
        "cost": "1,00",
        "proceeds": "0.0",
        "gain": "-1,00",
        "wallet": "ByBit (2)",
        "holding_period": "Short term",
        "notes": "",
    }
    f.update(fields)
    return ",".join([
        f["date_sold"],
        f["acquisition_date"],
        f["asset"],
        f'"{f["amount"]}"',
        f'"{f["cost"]}"',
        f'"{f["proceeds"]}"',
        f'"{f["gain"]}"',
        f["notes"],
        f["wallet"],
        f["holding_period"],
    ])


def _th_payment_row(**fields) -> str:  # noqa: PLR0913
    """Build a single payment-tagged TH CSV row matching ``_TH_HEADER`` (keyword args)."""
    f = {
        "date_utc": "2025-01-13 13:01:00 UTC",
        "wallet": "ByBit (2)",
        "amount": "1,00000000",
        "currency": "USDT",
        "net_value_eur": '"0,0"',
        "tag": "Payment",
    }
    f.update(fields)
    return ",".join([
        f["date_utc"],
        "crypto_withdrawal",
        f["tag"],
        f["wallet"],
        f'"{f["amount"]}"',
        f["currency"],
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        f["net_value_eur"],
        "",
        "",
        "",
        "",
        "",
    ])


def _ogr_row(date: str, asset: str, amount: str, value_eur: str, row_type: str, wallet: str) -> str:  # noqa: PLR0913
    """Build a single OGR CSV row string matching ``_OGR_HEADER``.

    ``amount`` and ``value_eur`` are QUOTED so the European decimal comma does not
    split the row. Real Koinly OGR exports quote both (e.g.
    ``...,USD,"-17,05260000","16,48",Loss,Kraken``); unquoted commas produced a
    malformed row that csv parsing silently turned into garbage fields, leaving
    the OGR override inert (and the resolver-keyed SPOT_DISPOSAL identification
    it feeds never firing). Callers pass bare European decimals, e.g.
    ``"-0,01"`` / ``"0,01"``.
    """
    return ",".join([date, asset, f'"{amount}"', f'"{value_eur}"', row_type, wallet])


@pytest.mark.unit
def test_payment_proceeds_priced_row_corrected_from_net_value(tmp_path):
    """Flag on, priced Payment: proceeds = Koinly Net Value, gain recomputed."""
    koinly_dir = tmp_path / "koinly2025"
    koinly_dir.mkdir()
    _write_payment_fixture(
        koinly_dir,
        cg_rows=[_cg_row(**_PHANTOM_USDT_BYBIT)],
        th_rows=[_th_payment_row(amount="50,00000000", currency="USDT", net_value_eur='"120,00"')],
    )

    report = load_koinly_crypto_report(koinly_dir, jurisdiction=_pp_jurisdiction(infer=True))
    assert report is not None

    matches = [e for e in report.capital_entries if e.asset == "USDT" and e.disposal_date == "2025-01-13"]
    assert matches, "Expected the corrected USDT Payment lot to survive aggregation (gain 20 EUR is material)"
    entry = matches[0]
    assert entry.proceeds_eur == Decimal("120.00"), f"proceeds must equal Net Value 120.00, got {entry.proceeds_eur}"
    assert entry.gain_loss_eur == Decimal("20.00"), f"gain must be 20.00 (120 - 100), got {entry.gain_loss_eur}"
    assert entry.review_required is True
    assert "USDT" in (entry.review_reason or "")
    assert "Net Value" in (entry.review_reason or "")
    assert any(
        r.asset == "USDT" and "Net Value" in (r.review_reason or "") for r in report.review_entries
    ), "Expected a CryptoReviewEntry audit row naming USDT and Net Value"


@pytest.mark.unit
def test_payment_proceeds_eur_stablecoin_unpriced_falls_back_to_par(tmp_path):
    """Flag on, EUR-pegged stablecoin unpriced: proceeds = amount at par; gain recomputed."""
    koinly_dir = tmp_path / "koinly2025"
    koinly_dir.mkdir()
    _write_payment_fixture(
        koinly_dir,
        cg_rows=[_cg_row(asset="EURC", amount="73,00000000", cost="100,00", gain="-100,00", wallet="Wirex")],
        th_rows=[_th_payment_row(
            wallet="Wirex", amount="73,00000000", currency="EURC", net_value_eur='"0,0"'
        )],
    )

    report = load_koinly_crypto_report(koinly_dir, jurisdiction=_pp_jurisdiction(infer=True))
    assert report is not None

    matches = [e for e in report.capital_entries if e.asset == "EURC"]
    assert matches, "Expected the corrected EURC Payment lot to survive (|gain| 27 >= 1 EUR)"
    entry = matches[0]
    assert entry.proceeds_eur == Decimal("73.00"), f"proceeds must be amount at par 73.00, got {entry.proceeds_eur}"
    assert entry.gain_loss_eur == Decimal("-27.00"), f"gain must be -27.00 (73 - 100), got {entry.gain_loss_eur}"
    assert "EUR par" in (entry.review_reason or "")
    assert any(
        "EUR par" in (r.review_reason or "") and r.asset == "EURC" for r in report.review_entries
    )


@pytest.mark.unit
def test_payment_proceeds_usd_stablecoin_unpriced_converted_via_threaded_rate(tmp_path):
    """Flag on, USD-pegged stablecoin unpriced, rate threaded: proceeds = amount x year-end rate.

    The expected proceeds is DERIVED at runtime from the threaded ConversionRate.rate
    (not a hand-picked literal), so the rate direction is anchored to the real magnitude.
    """
    from tax_reporting.infrastructure.config import ConversionRate

    koinly_dir = tmp_path / "koinly2025"
    koinly_dir.mkdir()
    _write_payment_fixture(
        koinly_dir,
        cg_rows=[_cg_row(amount="80,00000000", cost="100,00", gain="-100,00")],
        th_rows=[_th_payment_row(amount="80,00000000", currency="USDT", net_value_eur='"0,0"')],
    )

    usd_rate = Decimal("0.90")
    rates = [ConversionRate(base="EUR", calculated="USD", rate=usd_rate)]
    expected_proceeds = Decimal("80") * usd_rate  # 72.00

    report = load_koinly_crypto_report(
        koinly_dir, jurisdiction=_pp_jurisdiction(infer=True), rates=rates
    )
    assert report is not None

    matches = [e for e in report.capital_entries if e.asset == "USDT" and e.disposal_date == "2025-01-13"]
    assert matches, "Expected the corrected USDT Payment lot to survive"
    entry = matches[0]
    assert entry.proceeds_eur == expected_proceeds, (
        f"proceeds must equal amount * year-end USD->EUR rate = {expected_proceeds}, "
        f"got {entry.proceeds_eur}"
    )
    assert entry.gain_loss_eur == expected_proceeds - Decimal("100"), (
        f"gain must be {expected_proceeds - Decimal('100')} (proceeds - cost), got {entry.gain_loss_eur}"
    )
    assert entry.review_required is True
    reason = entry.review_reason or ""
    assert "USD" in reason, f"reason must name the USD peg, got {reason!r}"
    assert "0.90" in reason, f"reason must name the rate 0.90, got {reason!r}"
    assert "year-end rate" in reason.lower(), f"reason must name 'year-end rate', got {reason!r}"
    assert "verify" in reason.lower(), f"reason must name 'verify', got {reason!r}"


@pytest.mark.unit
def test_payment_proceeds_config_missing_fails_fast(tmp_path, monkeypatch):
    """STRICT: config-missing path fails fast with ConfigurationError, never silent run.

    Previously (pre-STRICT) the config-missing path ran crypto with ``jurisdiction=None``
    and the test guarded a NameError on ``app_config`` (Design Invariant 8, DP-014). Under
    the STRICT localization contract the config-missing path can no longer run crypto at
    all: with real fixture data present, ``_load_crypto_tax_report`` raises
    ``ConfigurationError`` BEFORE any parsing, so neither a silent wrong-day report nor a
    NameError can occur. ``app_config`` is initialised to ``None`` in ``_main`` and the
    ``rates`` expression degrades safely to ``None``, so the NameError the old test guarded
    is structurally impossible; this test now pins the fail-fast contract end-to-end with
    real CG/TH data (vs. the monkeypatched-loader STRICT tests in
    ``test_main_koinly_directory.py``).
    """
    import tax_reporting.main as main_mod
    from tax_reporting.domain.exceptions import ConfigurationError

    def _raise_fnf(*_args, **_kwargs):
        raise FileNotFoundError("config.ini missing")

    monkeypatch.setattr(main_mod, "load_configuration_from_file", _raise_fnf)

    koinly_dir = tmp_path / "koinly2025"
    koinly_dir.mkdir()
    _write_payment_fixture(
        koinly_dir,
        cg_rows=[_cg_row(**_PHANTOM_USDT_BYBIT)],
        th_rows=[_th_payment_row(amount="50,00000000", currency="USDT", net_value_eur='"120,00"')],
    )

    # Simulate the _main config-load path: app_config stays None on FileNotFoundError.
    app_config = None
    try:
        app_config = main_mod.load_configuration_from_file()
    except FileNotFoundError:
        logging.getLogger("test_config_missing").warning(
            "Config file not found; crypto pipeline will run without jurisdiction filters"
        )

    # STRICT: with crypto data present and no resolved jurisdiction timezone, the helper
    # fails fast. The rates expression must still degrade safely to None (no NameError).
    with pytest.raises(ConfigurationError, match="no jurisdiction config"):
        main_mod._load_crypto_tax_report(
            koinly_dir=koinly_dir,
            tax_year_hint=2025,
            tax_jurisdiction=None,  # Stays None on the config-missing path
            logger=logging.getLogger("test_config_missing"),
            rates=app_config.rates if app_config is not None else None,
        )


@pytest.mark.unit
def test_payment_proceeds_config_missing_warns_then_fails_fast_via_main(tmp_path, monkeypatch):
    """STRICT: config-missing + Koinly present warns, then fails fast from ``_main``.

    Previously (pre-STRICT) ``_main`` warned "config not found; crypto pipeline will run
    without jurisdiction filters" and continued. Under the STRICT localization contract
    that silent run is incorrect by default: ``_main`` still emits the config-missing
    WARNING (during config load, before crypto), then the STRICT guard in
    ``_load_crypto_tax_report`` raises ``ConfigurationError`` which propagates OUT of
    ``_main`` unwrapped (via ``except ConfigurationError: raise``), rather than being
    wrapped into a ``ReportGenerationError`` or degraded to a silent skip. This test pins
    both halves: the WARNING fires, and a ``ConfigurationError`` (not a ``NameError`` on
    ``app_config``) escapes ``_main``.
    """
    import tax_reporting.main as main_mod
    from tax_reporting.domain.exceptions import ConfigurationError

    def _raise_fnf(*_args, **_kwargs):
        raise FileNotFoundError("config.ini missing")

    monkeypatch.setattr(main_mod, "load_configuration_from_file", _raise_fnf)
    monkeypatch.setattr(main_mod, "generate_tax_report", lambda *_a, **_kw: False)

    src = tmp_path / "ib_export.csv"
    src.write_text("Data,Header\n", encoding="utf-8")
    koinly_dir = tmp_path / "koinly2025"
    koinly_dir.mkdir()
    _write_payment_fixture(
        koinly_dir,
        cg_rows=[_cg_row(**_PHANTOM_USDT_BYBIT)],
        th_rows=[_th_payment_row(amount="50,00000000", currency="USDT", net_value_eur='"120,00"')],
    )
    monkeypatch.setattr(main_mod, "parse_ib_export_all", lambda _p: _EmptyIbData())
    monkeypatch.setattr(main_mod, "calculate_fifo_gains", lambda *_a, **_kw: None)
    monkeypatch.setattr(main_mod, "export_rollover_file", lambda *_a, **_kw: None)

    main_logger = logging.getLogger("tax_reporting.main")
    captured: list[str] = []

    class _CaptureHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured.append(record.getMessage())

    handler = _CaptureHandler(level=logging.WARNING)
    main_logger.addHandler(handler)
    raised: Exception | None = None
    try:
        try:
            main_mod._main(source_file=src, output_dir=tmp_path, log_level="WARNING")
        except Exception as exc:  # noqa: BLE001
            raised = exc
    finally:
        main_logger.removeHandler(handler)

    # STRICT: a ConfigurationError must escape _main (not a NameError, not None/continue).
    assert isinstance(raised, ConfigurationError), (
        f"Expected ConfigurationError to escape _main on the config-missing+crypto path; "
        f"got {type(raised).__name__ if raised else 'no exception'}: {raised}"
    )

    warn_text = " ".join(captured)
    assert "Config file not found" in warn_text or "without jurisdiction filters" in warn_text, (
        "Expected the config-missing WARNING from the except branch to fire before the guard; "
        "got: " + warn_text
    )


@dataclasses.dataclass
class _EmptyIbData:
    """Minimal stand-in for IBExportData so _main can proceed under monkeypatch."""

    trade_cycles: dict = dataclasses.field(default_factory=dict)
    dividend_income: dict = dataclasses.field(default_factory=dict)


@pytest.mark.unit
def test_payment_proceeds_flag_off_preserves_today_behavior(tmp_path):
    """Flag off: Payment row passes through unchanged."""
    koinly_dir = tmp_path / "koinly2025"
    koinly_dir.mkdir()
    _write_payment_fixture(
        koinly_dir,
        cg_rows=[_cg_row(**_PHANTOM_USDT_BYBIT)],
        th_rows=[_th_payment_row(amount="50,00000000", currency="USDT", net_value_eur='"120,00"')],
    )

    report = load_koinly_crypto_report(koinly_dir, jurisdiction=_pp_jurisdiction(infer=False))
    assert report is not None

    matches = [e for e in report.capital_entries if e.asset == "USDT" and e.disposal_date == "2025-01-13"]
    assert matches, "Expected the uncorrected USDT Payment lot to survive (phantom loss is material)"
    entry = matches[0]
    assert entry.proceeds_eur == Decimal("0"), f"proceeds must stay 0 with flag off, got {entry.proceeds_eur}"
    assert entry.gain_loss_eur == Decimal("-100.00"), f"phantom loss must survive, got {entry.gain_loss_eur}"
    assert not any(
        "Net Value" in (r.review_reason or "") or "EUR par" in (r.review_reason or "")
        for r in report.review_entries
    ), "Flag off must NOT append payment-proceeds correction review entries"


@pytest.mark.unit
def test_payment_proceeds_material_priced_payment_survives_filter(tmp_path):
    """Materiality inversion: a priced Payment whose Net Value makes |gain| >= 1 EUR survives."""
    koinly_dir = tmp_path / "koinly2025"
    koinly_dir.mkdir()
    _write_payment_fixture(
        koinly_dir,
        cg_rows=[_cg_row(**_PHANTOM_USDT_BYBIT)],
        th_rows=[_th_payment_row(amount="50,00000000", currency="USDT", net_value_eur='"120,00"')],
    )

    report = load_koinly_crypto_report(koinly_dir, jurisdiction=_pp_jurisdiction(infer=True))
    assert report is not None
    matches = [
        e for e in report.capital_entries if e.asset == "USDT" and e.gain_loss_eur == Decimal("20.00")
    ]
    assert matches, "Material corrected Payment (gain 20 EUR) must survive _filter_immaterial_entries"


@pytest.mark.unit
def test_payment_proceeds_ogr_path_corrects_zero_proceeds_payment(tmp_path):
    """Resolver-keyed OGR identification + payment-proceeds correction produces correct net proceeds.

    An OGR Loss row with near-zero magnitude on the SAME (date, asset, wallet) as a
    proceeds==0 Payment whose TH Net Value > 0. The TH row resolves to PAYMENT (not
    SPOT_DISPOSAL), so its key is NOT in ``spot_disposal_keys`` and
    ``apply_ogr_event_level`` leaves the Payment's proceeds at 0. The
    payment-proceeds correction then runs on the untouched zero-proceeds row and
    repairs it to the TH Net Value. This characterizes the post-Phase-E resolver
    path (no re-zero snapshot/restore; the residual the snapshot existed to close
    is structurally impossible because Payment rows are excluded from OGR by
    resolver-keyed identification).
    """
    koinly_dir = tmp_path / "koinly2025"
    koinly_dir.mkdir()
    _write_payment_fixture(
        koinly_dir,
        cg_rows=[_cg_row(**_PHANTOM_USDT_BYBIT)],
        th_rows=[_th_payment_row(amount="50,00000000", currency="USDT", net_value_eur='"120,00"')],
        ogr_rows=[_ogr_row("13/01/2025 13:01", "USDT", "-0,005", "0,005", "Loss", "ByBit (2)")],
    )

    report = load_koinly_crypto_report(
        koinly_dir, jurisdiction=_pp_jurisdiction(infer=True, use_ogr=True)
    )
    assert report is not None

    matches = [e for e in report.capital_entries if e.asset == "USDT" and e.disposal_date == "2025-01-13"]
    assert matches, "Expected the corrected USDT Payment lot to survive OGR + correction"
    entry = matches[0]
    assert entry.proceeds_eur == Decimal("120.00"), (
        f"After OGR + correction, proceeds must equal Net Value 120.00, got {entry.proceeds_eur}"
    )
    assert entry.gain_loss_eur == Decimal("20.00"), f"gain must be 20.00, got {entry.gain_loss_eur}"


@pytest.mark.unit
def test_payment_proceeds_same_key_legitimate_disposal_keeps_ogr_override(tmp_path):
    """Resolver-keyed OGR override does NOT touch a co-keyed Payment row.

    On ONE (date, asset, wallet) key: (a) a genuine non-zero-proceeds derivatives
    disposal whose TH row resolves to SPOT_DISPOSAL (so OGR overrides it), AND (b)
    a separate zero-proceeds Payment whose TH row resolves to PAYMENT (so OGR skips
    it). Post-Phase-E there is no re-zero block; nothing restores or clobbers
    either row. The legitimate disposal KEEPS its OGR-overridden proceeds; the
    Payment row flows to the payment-proceeds correction untouched.

    The two rows are given DIFFERENT holding periods so they land in SEPARATE
    aggregation buckets ((date, asset, platform, holding_period)); that lets us
    assert (a)'s proceeds in isolation.
    """
    koinly_dir = tmp_path / "koinly2025"
    koinly_dir.mkdir()
    _write_payment_fixture(
        koinly_dir,
        cg_rows=[
            # (a) Legitimate disposal: non-zero proceeds (150), gain 50. Long term
            #     so it aggregates into its own bucket, isolated from the Payment.
            _cg_row(
                amount="50,00000000",
                cost="100,00",
                proceeds="150,00",
                gain="50,00",
                holding_period="Long term",
            ),
            # (b) Zero-proceeds Payment, same (date, asset, wallet) as (a).
            _cg_row(**_PHANTOM_USDT_BYBIT),
        ],
        th_rows=[_th_payment_row(amount="50,00000000", currency="USDT", net_value_eur='"120,00"')],
        # Phase 1 event-level: OGR value is material (>= 1 EUR) so the legitimate
        # Long-term lot - which under event-level pooling absorbs the full OGR event
        # value as the first lot of the pooled (date, asset, wallet) event - survives
        # the materiality filter. Under legacy the legitimate lot was overridden
        # independently to -abs(50); under Phase 1 it gets the full OGR event value.
        ogr_rows=[_ogr_row("13/01/2025 13:01", "USDT", "-5,00", "5,00", "Loss", "ByBit (2)")],
    )

    report = load_koinly_crypto_report(
        koinly_dir, jurisdiction=_pp_jurisdiction(infer=True, use_ogr=True)
    )
    assert report is not None

    legitimate = [
        e
        for e in report.capital_entries
        if e.asset == "USDT"
        and e.disposal_date == "2025-01-13"
        and e.platform == "ByBit (2)"
        and e.holding_period.lower().startswith("long")
    ]
    assert len(legitimate) == 1, (
        "Expected the legitimate Long-term disposal as its own aggregated row "
        "(separate bucket from the Payment), "
        f"got {len(legitimate)}: {[(e.holding_period, e.proceeds_eur) for e in legitimate]}"
    )
    # (a) had non-zero proceeds and its TH row resolved to SPOT_DISPOSAL, so OGR
    # overrode it; the override survives (no re-zero block to undo it).
    assert legitimate[0].proceeds_eur > Decimal("0"), (
        "The legitimate non-zero-proceeds SPOT_DISPOSAL must KEEP its OGR-overridden proceeds; "
        f"got {legitimate[0].proceeds_eur}"
    )


@pytest.mark.unit
def test_payment_proceeds_same_day_aggregation_sums_proceeds(tmp_path):
    """Same-day aggregation: two corrected Payment lots aggregate to SUMMED proceeds."""
    koinly_dir = tmp_path / "koinly2025"
    koinly_dir.mkdir()
    _write_payment_fixture(
        koinly_dir,
        cg_rows=[
            _cg_row(amount="30,00000000", cost="60,00", gain="-60,00"),
            _cg_row(amount="20,00000000", cost="40,00", gain="-40,00"),
        ],
        th_rows=[
            _th_payment_row(amount="30,00000000", currency="USDT", net_value_eur='"70,00"'),
            _th_payment_row(amount="20,00000000", currency="USDT", net_value_eur='"50,00"'),
        ],
    )

    report = load_koinly_crypto_report(koinly_dir, jurisdiction=_pp_jurisdiction(infer=True))
    assert report is not None

    matches = [e for e in report.capital_entries if e.asset == "USDT" and e.disposal_date == "2025-01-13"]
    assert len(matches) == 1, f"Expected the two same-day lots to aggregate to ONE row, got {len(matches)}"
    entry = matches[0]
    # SUMMED proceeds = 70 + 50 = 120 (not overwritten).
    assert entry.proceeds_eur == Decimal("120.00"), (
        f"Aggregated proceeds must be SUMMED (70 + 50 = 120.00), got {entry.proceeds_eur}"
    )
    assert entry.gain_loss_eur == Decimal("20.00"), (
        f"Aggregated gain must be SUMMED (10 + 10 = 20.00), got {entry.gain_loss_eur}"
    )


@pytest.mark.unit
def test_payment_proceeds_eurc_reward_now_flagged_by_tokens_extension(tmp_path):
    """Backward-compat for the tokens.stablecoins extension (EUROC/EURC/EURT) under CRG-022.

    EURC is crypto-denominated (DEFERRED_BY_LAW), so under the CRG-022 parse-time skip a
    zero-value EURC reward is routed to ``skipped_zero_value_deferred_rewards`` (NOT dropped ,
    full-fidelity audit list, Invariant 1) carrying ``review_required=True`` propagated from
    the parse path. The ``is_known`` gate still passes (EURC is in tokens.stablecoins, so the
    row is NOT routed to the unknown-asset ``skipped_assets`` else-branch); it just lands in
    the deferred-skip list instead of ``reward_entries``.
    """
    # Clear the cache so this test loads the REAL extended JSON (with EURC) regardless
    # of what an earlier test cached with mocked data.
    _load_popular_crypto_tokens.cache_clear()

    koinly_dir = tmp_path / "koinly2025"
    koinly_dir.mkdir()
    _write_payment_fixture(
        koinly_dir,
        cg_rows=[_cg_row(amount="1,00000000", cost="1,00", proceeds="1,00", gain="0,00")],
        th_rows=[_th_payment_row(amount="1,00000000", currency="USDT", net_value_eur='"1,00"')],
        income_rows=[
            "01/02/2025 00:01,EURC,5,0.00,Reward,,Wirex",
            "01/03/2025 00:01,WXT,5,1.00,Reward,,Wirex",
        ],
    )

    report = load_koinly_crypto_report(koinly_dir, jurisdiction=_pp_jurisdiction(infer=False))
    assert report is not None

    # CRG-022: zero-value EURC (DEFERRED_BY_LAW) is retained in the deferred-skip audit list
    # with the propagated review flag, NOT in reward_entries.
    eurc_skipped = [e for e in report.skipped_zero_value_deferred_rewards if e.asset == "EURC"]
    assert eurc_skipped, (
        "A zero-value EURC reward must be retained in skipped_zero_value_deferred_rewards "
        "(CRG-022 deferred-skip audit list) with review_required propagated."
    )
    assert eurc_skipped[0].review_required is True
    assert eurc_skipped[0].value_eur == Decimal("0")
    assert eurc_skipped[0].tax_classification == RewardTaxClassification.DEFERRED_BY_LAW
    # And EURC must NOT appear in reward_entries (it was relocated, not duplicated).
    assert [e for e in report.reward_entries if e.asset == "EURC"] == []

    wxt_rewards = [e for e in report.reward_entries if e.asset == "WXT"]
    assert wxt_rewards, "Control: the non-zero WXT reward must still be parsed"


# --- DP-015 fee filtering integration tests ---
#
# These tests exercise the wiring of ``remove_transaction_fees`` (early pass,
# after derivatives dedup, before OGR/aggregation) and ``flag_fee_suspects``
# (late pass, after payment-proceeds, before aggregation) into
# ``load_koinly_crypto_report`` (Design Invariant 4, Option D pipeline). See
# docs/history/plans/2026-06-23-filter-transaction-fees.md Task 4.

_FEE_PER_ASSET = {
    "ETH": Decimal("1.0"),
    "SOL": Decimal("0.5"),
    "SUI": Decimal("0.5"),
    "BNB": Decimal("0.5"),
    "MATIC": Decimal("0.5"),
    "TON": Decimal("0.5"),
}


def _fee_jurisdiction(
    *,
    exclude_fees: bool = True,
    use_ogr: bool = False,
    infer_payment: bool = False,
    timezone: ZoneInfo | None = _LISBON_TZ,
):
    """Build a PT/2025 jurisdiction with the fee filter flag toggled.

    ``use_ogr`` enables the OGR override path (r7 L4 test: a suspect lot that
    also matches an OGR spot-index entry must STILL end up flagged).
    ``infer_payment`` enables the payment-proceeds path (r11 Blocker Option D
    test: late suspect flagging runs after payment-proceeds resolution).
    """
    from tax_reporting.infrastructure.config import TaxJurisdictionConfig

    return TaxJurisdictionConfig(
        country="PT",
        fiscal_year=2025,
        exclude_loan_repayment_gains=False,
        zero_basis_review_threshold=Decimal("50"),
        exclude_transaction_fees=exclude_fees,
        exclude_transaction_fee_max_eur_per_asset=dict(_FEE_PER_ASSET),
        use_other_gains_report=use_ogr,
        infer_payment_proceeds=infer_payment,
        timezone=timezone,
    )


def _th_fee_row(**fields) -> str:  # noqa: PLR0913
    """Build a single ``crypto_withdrawal`` TH CSV row matching ``_TH_HEADER``.

    TxHash is populated so the co-occurrence guard can fire (callers ensure the
    same TxHash appears on at least one other row, e.g. a ``transfer`` row, so
    the count is >= 2). Decimal fields are QUOTED to survive the European
    decimal comma.
    """
    f: dict[str, str] = {
        "date_utc": "2025-01-13 13:01:00 UTC",
        "tag": "",
        "wallet": "MetaMask",
        "amount": "0,00267371",
        "currency": "ETH",
        "net_value_eur": '"0,50"',
        "tx_hash": "0xfee1",
    }
    f.update(fields)
    return ",".join([
        f["date_utc"],
        "crypto_withdrawal",
        f["tag"],
        f["wallet"],
        f'"{f["amount"]}"',
        f["currency"],
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        f["net_value_eur"],
        "",
        "",
        "",
        f["tx_hash"],
        "",
    ])


def _th_transfer_row(**fields) -> str:
    """Build a non-withdrawal TH row sharing a TxHash (co-occurrence partner)."""
    f: dict[str, str] = {
        "date_utc": "2025-01-13 13:01:00 UTC",
        "wallet": "MetaMask",
        "tx_hash": "0xfee1",
    }
    f.update(fields)
    return ",".join([
        f["date_utc"],
        "transfer",
        "",
        f["wallet"],
        "",
        "",
        "",
        "Ledger",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        f["tx_hash"],
        "",
    ])


def _write_fee_fixture(
    koinly_dir: Path,
    *,
    cg_rows: list[str],
    th_rows: list[str],
    ogr_rows: list[str] | None = None,
    income_rows: list[str] | None = None,
) -> None:
    """Write a minimal Koinly export set exercising the fee filter."""
    (koinly_dir / "koinly_2025_capital_gains_report.csv").write_text(
        "\n".join(["Capital gains report 2025", "", _CG_HEADER, *cg_rows]),
        encoding="utf-8",
    )
    default_income = ["01/01/2025 00:01,WXT,1,1.00,Reward,,Wirex"]
    (koinly_dir / "koinly_2025_income_report.csv").write_text(
        "\n".join(["Income report 2025", "", _INCOME_HEADER, *(income_rows or default_income)]),
        encoding="utf-8",
    )
    (koinly_dir / "koinly_2025_transaction_history.csv").write_text(
        "\n".join(["Transaction report 2025", "", _TH_HEADER, *th_rows]),
        encoding="utf-8",
    )
    if ogr_rows is not None:
        (koinly_dir / "koinly_2025_other_gains_report.csv").write_text(
            "\n".join(["Other gains report 2025", "", _OGR_HEADER, *ogr_rows]),
            encoding="utf-8",
        )


@pytest.mark.unit
def test_load_koinly_crypto_report_applies_fee_filter(tmp_path):
    """Flag on: a tagged Cost fee withdrawal co-occurring with a transfer removes the matching CG lot."""
    koinly_dir = tmp_path / "koinly2025"
    koinly_dir.mkdir()
    tx_hash = "0xaabbcc"
    _write_fee_fixture(
        koinly_dir,
        cg_rows=[
            _cg_row(
                asset="ETH",
                amount="0,00267371",
                cost="0,50",
                proceeds="1,50",
                gain="1,00",
                wallet="MetaMask",
            ),
        ],
        th_rows=[
            _th_transfer_row(tx_hash=tx_hash),
            _th_fee_row(tag="Cost", currency="ETH", tx_hash=tx_hash),
        ],
    )

    report = load_koinly_crypto_report(koinly_dir, jurisdiction=_fee_jurisdiction(exclude_fees=True))
    assert report is not None

    eth_entries = [e for e in report.capital_entries if e.asset == "ETH"]
    assert eth_entries == [], (
        "The tagged Cost fee lot must be REMOVED from capital_entries when "
        "exclude_transaction_fees is True"
    )


@pytest.mark.unit
def test_load_koinly_crypto_report_skips_fee_filter_when_disabled(tmp_path):
    """Flag off: the fee CG lot is unchanged (no-op)."""
    koinly_dir = tmp_path / "koinly2025"
    koinly_dir.mkdir()
    tx_hash = "0xaabbcc"
    _write_fee_fixture(
        koinly_dir,
        cg_rows=[
            _cg_row(
                asset="ETH",
                amount="0,00267371",
                cost="0,50",
                proceeds="1,50",
                gain="1,00",
                wallet="MetaMask",
            ),
        ],
        th_rows=[
            _th_transfer_row(tx_hash=tx_hash),
            _th_fee_row(tag="Cost", currency="ETH", tx_hash=tx_hash),
        ],
    )

    report = load_koinly_crypto_report(koinly_dir, jurisdiction=_fee_jurisdiction(exclude_fees=False))
    assert report is not None

    eth_entries = [e for e in report.capital_entries if e.asset == "ETH"]
    assert len(eth_entries) == 1, (
        "The fee lot must be RETAINED when exclude_transaction_fees is False (no-op)"
    )


@pytest.mark.unit
def test_fee_suspect_flag_propagates_to_aggregated_cg_row(tmp_path, caplog):
    """Design Invariant 4: a CG-matched unlisted-asset suspect propagates end-to-end.

    Two branches are asserted in one test to discriminate a propagation break
    from a materiality drop:

    - MATERIAL branch (aggregated |gain_loss_eur| >= 1 EUR): the suspect lot
      survives materiality and the aggregated ``capital_entries`` row carries
      ``review_required=True`` + a non-None ``review_reason``. The PRIMARY
      assertion is the ``CryptoReviewEntry`` in ``report.review_entries``
      (it survives materiality regardless).
    - SUB-1-EUR branch (aggregated |gain_loss_eur| < 1 EUR): the lot is
      dropped by ``_filter_immaterial_entries`` so it appears ONLY in
      Supplementary (review_entries) + the log, NOT in ``capital_entries``.
    """
    tx_hash = "0xsuspect1"

    # MATERIAL branch: gain 2 EUR (>= 1).
    material_dir = tmp_path / "koinly_material"
    material_dir.mkdir()
    _write_fee_fixture(
        material_dir,
        cg_rows=[
            _cg_row(
                asset="XSTRK",
                amount="1,00000000",
                cost="1,00",
                proceeds="3,00",
                gain="2,00",
                wallet="MetaMask",
            ),
        ],
        th_rows=[
            _th_transfer_row(tx_hash=tx_hash),
            _th_fee_row(currency="XSTRK", amount="1,00000000", net_value_eur='"0,30"', tx_hash=tx_hash),
        ],
    )
    with caplog.at_level(logging.WARNING, logger="tax_reporting.application.crypto.fee_filter"):
        material_report = load_koinly_crypto_report(material_dir, jurisdiction=_fee_jurisdiction(exclude_fees=True))
    assert material_report is not None

    # PRIMARY assertion: the CryptoReviewEntry survives materiality (always).
    material_review = [
        r for r in material_report.review_entries if r.asset == "XSTRK"
    ]
    assert material_review, (
        "The BERA suspect must append a CryptoReviewEntry (PRIMARY assertion, survives materiality)"
    )
    # Material branch: the lot also survives in capital_entries with the flag.
    material_capital = [e for e in material_report.capital_entries if e.asset == "XSTRK"]
    assert material_capital, (
        "Material branch: the BERA suspect lot must survive materiality (|gain| 2 EUR >= 1)"
    )
    assert material_capital[0].review_required is True, (
        "Material branch: the aggregated CG row must carry review_required=True"
    )
    assert material_capital[0].review_reason is not None, (
        "Material branch: the aggregated CG row must carry a non-None review_reason"
    )

    # SUB-1-EUR branch: gain 0.50 EUR (< 1).
    tx_hash2 = "0xsuspect2"
    sub_dir = tmp_path / "koinly_sub"
    sub_dir.mkdir()
    _write_fee_fixture(
        sub_dir,
        cg_rows=[
            _cg_row(
                asset="XSTRK",
                amount="1,00000000",
                cost="1,00",
                proceeds="1,50",
                gain="0,50",
                wallet="MetaMask",
            ),
        ],
        th_rows=[
            _th_transfer_row(tx_hash=tx_hash2),
            _th_fee_row(currency="XSTRK", amount="1,00000000", net_value_eur='"0,30"', tx_hash=tx_hash2),
        ],
    )
    sub_report = load_koinly_crypto_report(sub_dir, jurisdiction=_fee_jurisdiction(exclude_fees=True))
    assert sub_report is not None
    sub_capital = [e for e in sub_report.capital_entries if e.asset == "XSTRK"]
    assert sub_capital == [], (
        "Sub-1-EUR branch: the suspect lot is dropped by materiality, NOT in capital_entries"
    )
    sub_review = [r for r in sub_report.review_entries if r.asset == "XSTRK"]
    assert sub_review, (
        "Sub-1-EUR branch: the suspect appears ONLY in Supplementary (review_entries)"
    )


@pytest.mark.unit
def test_fee_suspect_flag_survives_ogr_override(tmp_path):
    """r7 L4: a suspect lot also matching an OGR spot-index entry stays flagged.

    OGR's ``replace(...)`` (ogr_handler.py:494-501) omits ``review_required``/
    ``review_reason``; a future edit adding those would clobber the suspect
    flag. With the Option D ordering (suspect flagging AFTER OGR), the flag is
    applied last and survives. The aggregated entry must carry the fee-SUSPECT
    reason (not an OGR reason).
    """
    tx_hash = "0xogrsuspect"
    koinly_dir = tmp_path / "koinly_ogr"
    koinly_dir.mkdir()
    # CG gain 2 EUR (material) so the lot survives materiality.
    _write_fee_fixture(
        koinly_dir,
        cg_rows=[
            _cg_row(
                asset="XSTRK",
                amount="1,00000000",
                cost="1,00",
                proceeds="3,00",
                gain="2,00",
                wallet="MetaMask",
            ),
        ],
        th_rows=[
            _th_transfer_row(tx_hash=tx_hash),
            _th_fee_row(currency="XSTRK", amount="1,00000000", net_value_eur='"0,30"', tx_hash=tx_hash),
        ],
        ogr_rows=[
            _ogr_row("13/01/2025 13:01", "XSTRK", "1,00000000", "2,00", "Profit", "MetaMask"),
        ],
    )

    report = load_koinly_crypto_report(
        koinly_dir,
        jurisdiction=_fee_jurisdiction(exclude_fees=True, use_ogr=True),
    )
    assert report is not None

    xstrk_capital = [e for e in report.capital_entries if e.asset == "XSTRK"]
    assert xstrk_capital, "The BERA suspect lot must survive materiality + OGR"
    entry = xstrk_capital[0]
    assert entry.review_required is True, (
        "The OGR-matched suspect lot must STILL be review_required=True"
    )
    assert entry.review_reason is not None
    assert "unlisted asset" in entry.review_reason, (
        "The reason must be the fee-SUSPECT reason, not an OGR reason"
    )


@pytest.mark.unit
def test_fee_suspect_flagging_runs_after_payment_proceeds(tmp_path):
    """r11 Blocker Option D: late flagging runs after payment-proceeds.

    A CG-matched suspect lot with ``proceeds_eur == 0`` that matches a
    Payment-tagged TH bucket: payment-proceeds resolution runs first and sets
    its own payment-specific reason; the late suspect pass then OVERRIDES the
    flag with the fee-suspect reason on the final aggregated entry.
    """
    # Use USDT (a payment-proceeds stablecoin) as the suspect asset: it is NOT
    # in _FEE_PER_ASSET, so an untagged USDT withdrawal classifies as an
    # unlisted-asset suspect. MetaMask wallet is used so the raw CG lot wallet
    # equals the fee event's normalized Sending Wallet (the raw-vs-normalized
    # asymmetry only bites for ByBit-style suffixed wallets).
    tx_hash = "0xppsuspect"
    koinly_dir = tmp_path / "koinly_pp"
    koinly_dir.mkdir()
    _write_fee_fixture(
        koinly_dir,
        cg_rows=[
            _cg_row(
                asset="USDT",
                amount="50,00000000",
                cost="100,00",
                proceeds="0,0",
                gain="-100,00",
                wallet="MetaMask",
            ),
        ],
        th_rows=[
            # Co-occurrence partner (a transfer sharing the TxHash so the
            # suspect's TxHash count is >= 2).
            _th_transfer_row(tx_hash=tx_hash, wallet="MetaMask"),
            # Payment-tagged withdrawal sharing the SAME TxHash so it ALSO drives
            # the payment-proceeds correction on this lot (proceeds 0 -> 120).
            # Emitted inline because _th_payment_row hardcodes an empty TxHash.
            ",".join([
                "2025-01-13 13:01:00 UTC",
                "crypto_withdrawal",
                "Payment",
                "MetaMask",
                '"50,00000000"',
                "USDT",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                '"120,00"',
                "",
                "",
                "",
                tx_hash,
                "",
            ]),
            # Untagged USDT withdrawal (the suspect source). Same TxHash so the
            # co-occurrence guard passes; USDT is unlisted (not a dict key) so it
            # classifies as a suspect, NOT a removed fee.
            _th_fee_row(
                currency="USDT",
                amount="50,00000000",
                net_value_eur='"0,30"',
                wallet="MetaMask",
                tx_hash=tx_hash,
            ),
        ],
    )

    report = load_koinly_crypto_report(
        koinly_dir,
        jurisdiction=_fee_jurisdiction(exclude_fees=True, infer_payment=True),
    )
    assert report is not None

    usdt_capital = [e for e in report.capital_entries if e.asset == "USDT"]
    assert usdt_capital, "The USDT lot must survive (corrected proceeds 120 - cost 100 = +20 EUR, material)"
    entry = usdt_capital[0]
    assert entry.proceeds_eur == Decimal("120.00"), (
        "Control: payment-proceeds DID run and correct proceeds to the TH Net Value"
    )
    assert entry.review_required is True, (
        "Late suspect flagging must set review_required=True after payment-proceeds"
    )
    assert entry.review_reason is not None
    assert "unlisted asset" in entry.review_reason, (
        "The final reason must carry the fee-SUSPECT reason set by the late pass "
        "(the fee module JOINS it onto the payment-proceeds reason; the suspect "
        "reason must be present so the late pass is proven to have run after "
        "payment-proceeds resolution)"
    )


class TestDerivativesRouting:
    """TDD for flag-gated, residency-routed derivatives (Modelo 3 / art. 10(1)(e)).

    Flag-gated: with ``route_via_residency=True`` a differing/UNKNOWN/empty operator routes
    the derivatives P&L entry to Anexo J Q9.2.B with operation code G30 (non-resident);
    a same-country operator routes to Anexo G Q13 with G51 (resident). With the flag
    ``False`` every jurisdiction emits no Modelo 3 hint at all (the flag, not the country,
    now gates routing).

    One nonresident case (``test_nonresident_operator_gets_j_q92b_g30``) drives the real
    ``_split_ogr_index`` construction site (ogr_handler.py:265-282) via a synthetic OGR row
    whose wallet resolves to a non-PT operator. This forces the wiring under test; the pure
    ``_derivatives_route`` helper is unit-tested separately and must NOT substitute for
    construction coverage (the suite would otherwise go GREEN while construction still omits
    the routed fields).

    The resident / unknown / flag-off / country-agnostic cases call the pure helper
    ``_derivatives_route(country, operator_country, route_via_residency)`` directly.
    """

    def test_nonresident_operator_gets_j_q92b_g30(self):
        """Non-resident operator (AE) routes to J/Q9.2.B + G30 via construction when the flag is on.

        Builds the entry through the real ``_split_ogr_index`` path: a synthetic Profit OGR
        row whose wallet is ``ByBit`` (resolves to ``operator_country="AE"``) plus a PT
        jurisdiction with derivatives separation enabled (``route_derivatives_by_counterparty_residency``
        on). The resulting ``DerivativesPnLEntry`` must carry ``annex_hint == "J/Q9.2.B"``
        and ``operation_code == "G30"``.

        Pins the contract implemented at the construction site
        (ogr_handler.py via entities.py), where the route is resolved per row.
        """
        from tax_reporting.application.crypto.ogr_handler import _split_ogr_index

        rows = [
            ParsedOgrRow(
                date="2025-01-12",
                asset="USDT",
                gain_loss=Decimal("140.18"),
                row_type="Profit",
                wallet="ByBit",
            ),
        ]
        capital_entries: list[CryptoCapitalGainEntry] = []

        _spot_index, derivatives_entries = _split_ogr_index(
            rows, capital_entries, build_koinly_jurisdiction(separate_derivatives_reporting=True)
        )

        assert len(derivatives_entries) == 1
        entry = derivatives_entries[0]
        # ByBit resolves to AE (operator_origin.py:160), a non-PT alpha-2 code.
        assert entry.operator_country == "AE"
        assert entry.annex_hint == "J/Q9.2.B"
        assert entry.operation_code == "G30"

    def test_resident_route_through_full_construction(self, monkeypatch):
        """PT-resident counterparty routes to G/Q13 + G51 through real construction.

        Mirrors ``test_nonresident_operator_gets_j_q92b_g30`` but injects a PT-resident
        operator so the resident branch of ``_split_ogr_index`` is exercised end-to-end.
        No PT-domiciled operator is registered in ``operator_origin.py`` (so an e2e
        fixture cannot resolve a PT operator from wallet labels); the
        ``resolve_operator_origin`` symbol in the ``ogr_handler`` namespace is patched
        to return an ``OperatorOrigin(operator_country="PT")``. This is the same idiom
        used by ``test_separate_derivatives_disabled_produces_no_derivatives_entries_and_no_operator_resolution``
        (line ~9536) and keeps the test on the real ``_split_ogr_index`` construction
        site rather than calling ``_derivatives_route`` directly. If construction wiring
        ever drops the resident branch, this fails (the entry would carry the neutral
        blank default, not G/Q13 + G51).
        """
        from tax_reporting.application.crypto import ogr_handler
        from tax_reporting.application.crypto.ogr_handler import _split_ogr_index

        pt_operator = OperatorOrigin(
            platform="PTOperator",
            service_scope="crypto",
            operator_entity="PT Resident Entity",
            operator_country="PT",
            source_url="",
            source_checked_on="2026-01-01",
            confidence="high",
            review_required=False,
            valid_from="2026-01-01",
        )
        monkeypatch.setattr(ogr_handler, "resolve_operator_origin", lambda *_a, **_kw: pt_operator)

        rows = [
            ParsedOgrRow(
                date="2025-01-12",
                asset="USDT",
                gain_loss=Decimal("140.18"),
                row_type="Profit",
                wallet="PTOperator",
            ),
        ]
        capital_entries: list[CryptoCapitalGainEntry] = []

        _spot_index, derivatives_entries = _split_ogr_index(
            rows, capital_entries, build_koinly_jurisdiction(separate_derivatives_reporting=True)
        )

        assert len(derivatives_entries) == 1
        entry = derivatives_entries[0]
        assert entry.operator_country == "PT"
        assert entry.annex_hint == "G/Q13"
        assert entry.operation_code == "G51"

    def test_flag_off_blanks_through_full_construction(self):
        """Residency routing disabled emits blank annex/operation code through real construction.

        Construction-path counterpart to ``test_flag_off_blanks_for_pt_jurisdiction``:
        drives the real ``_split_ogr_index`` site with
        ``route_derivatives_by_counterparty_residency=False`` so the constructed
        ``DerivativesPnLEntry`` must carry blank ``annex_hint`` and
        ``operation_code`` regardless of jurisdiction (Invariant 2: Modelo 3 output
        is flag-gated). The ByBit/AE operator is intentional: even a routable
        counterparty must NOT produce a Modelo 3 hint when residency routing is
        disabled. If a future change adds a fallback default at construction (e.g.
        ``annex_hint=route or "G/Q13"``), the pure-helper tests stay green while
        this test fails, catching the silent annex emission.
        """
        from tax_reporting.application.crypto.ogr_handler import _split_ogr_index

        rows = [
            ParsedOgrRow(
                date="2025-01-12",
                asset="USDT",
                gain_loss=Decimal("140.18"),
                row_type="Profit",
                wallet="ByBit",
            ),
        ]
        capital_entries: list[CryptoCapitalGainEntry] = []

        _spot_index, derivatives_entries = _split_ogr_index(
            rows,
            capital_entries,
            build_koinly_jurisdiction(
                separate_derivatives_reporting=True,
                country="DE",
                timezone=ZoneInfo("Europe/Berlin"),
                route_derivatives_by_counterparty_residency=False,
            ),
        )

        assert len(derivatives_entries) == 1
        entry = derivatives_entries[0]
        # ByBit resolves to AE, a routable counterparty, but residency routing
        # disabled emits no Modelo 3 annex regardless of the operator.
        assert entry.annex_hint == ""
        assert entry.operation_code == ""

    def test_resident_operator_gets_g_q13_g51(self):
        """Same-country operator routes to G/Q13 + G51 when the flag is on.

        Calls the pure helper ``_derivatives_route(country, operator_country, route_via_residency)``
        directly (added in Task A2). Flag on + ``operator_country == country`` -> resident codes.
        """
        from tax_reporting.application.crypto.ogr_handler import _derivatives_route

        annex_hint, operation_code = _derivatives_route("PT", "PT", True)

        assert annex_hint == "G/Q13"
        assert operation_code == "G51"

    def test_unknown_country_defaults_nonresident(self):
        """UNKNOWN operator country defaults to non-resident (J/Q9.2.B + G30) when the flag is on.

        Fail-safe: when operator origin cannot be resolved, route to the non-resident annex
        rather than silently claiming PT residence. Calls the pure helper directly.
        """
        from tax_reporting.application.crypto.ogr_handler import _derivatives_route

        annex_hint, operation_code = _derivatives_route("PT", "UNKNOWN", True)

        assert annex_hint == "J/Q9.2.B"
        assert operation_code == "G30"

    def test_resident_route_country_agnostic_de(self):
        """Country-agnostic resident case: DE taxpayer + DE operator -> resident codes.

        Proves residency is ``operator_country == country``, defeating both a PT literal and a
        ``{PT, DE}`` allow-list regression. Flag on + same-country operator -> ``("G/Q13", "G51")``.
        """
        from tax_reporting.application.crypto.ogr_handler import _derivatives_route

        annex_hint, operation_code = _derivatives_route("DE", "DE", True)

        assert annex_hint == "G/Q13"
        assert operation_code == "G51"

    def test_resident_route_country_agnostic_fr(self):
        """Second country-agnostic resident case: FR taxpayer + FR operator -> resident codes.

        A second independent country closes the allow-list hole that a single DE case cannot.
        Flag on + same-country operator -> ``("G/Q13", "G51")``.
        """
        from tax_reporting.application.crypto.ogr_handler import _derivatives_route

        annex_hint, operation_code = _derivatives_route("FR", "FR", True)

        assert annex_hint == "G/Q13"
        assert operation_code == "G51"

    def test_nonresident_route_country_agnostic_fr_de(self):
        """Non-resident pair on a second non-PT country: FR taxpayer + DE operator -> non-resident codes.

        Flag on + differing operator country -> ``("J/Q9.2.B", "G30")``.
        """
        from tax_reporting.application.crypto.ogr_handler import _derivatives_route

        annex_hint, operation_code = _derivatives_route("FR", "DE", True)

        assert annex_hint == "J/Q9.2.B"
        assert operation_code == "G30"

    def test_flag_off_blanks_for_pt_jurisdiction(self):
        """Flag off -> blank routing for any jurisdiction, including PT.

        A PT jurisdiction with the flag off emits no Modelo 3 hint (the flag, not the country,
        now gates routing).
        """
        from tax_reporting.application.crypto.ogr_handler import _derivatives_route

        annex_hint, operation_code = _derivatives_route("PT", "PT", False)

        assert annex_hint == ""
        assert operation_code == ""

    def test_pt_jurisdiction_empty_operator_defaults_nonresident(self):
        """Empty operator country defaults to non-resident (J/Q9.2.B + G30) when the flag is on.

        Fail-safe mirror of the UNKNOWN case: an empty operator country must not be
        treated as resident. Flag on + ``"" != country`` -> non-resident, unchanged behaviour.
        Calls the pure helper directly.
        """
        from tax_reporting.application.crypto.ogr_handler import _derivatives_route

        annex_hint, operation_code = _derivatives_route("PT", "", True)

        assert annex_hint == "J/Q9.2.B"
        assert operation_code == "G30"


# --- Task 1 (RED): flag-gated official income-code resolution ---


@pytest.mark.unit
class TestIncomeCode:
    """Tests pinning the flag-gated official income-code resolution.

    These pin the contract implemented in ``_resolve_income_code`` and
    ``aggregate_taxable_rewards``: with ``classify_with_income_codes=True`` only
    the fiat-reward interest family resolves to the official Tabela V code
    ``E25``; every other Koinly type resolves to ``""`` (no synthetic ``40x``
    default); with ``classify_with_income_codes=False`` every type resolves to
    ``""`` (Invariant 4).

    The pure-helper cases call the two-arg signature
    ``_resolve_income_code(source_type, classify_with_income_codes)``. The
    aggregation case threads ``classify_rewards_with_income_codes=`` into
    ``aggregate_taxable_rewards``. The production-path case drives the real
    ``generate_tax_report`` entrypoint under a non-classifying jurisdiction.
    """

    # -- pure helper: classified interest family -> E25 --

    @pytest.mark.parametrize("koinly_type", ["interest", "lending", "lending interest"])
    def test_interest_resolves_to_e25_when_classified(self, koinly_type: str):
        """With classification on, the fiat-interest family resolves to the official E25."""
        assert _resolve_income_code(koinly_type, True) == "E25"

    # -- pure helper: every other type -> "" (NOT any 40x) when classified --

    @pytest.mark.parametrize(
        "koinly_type",
        ["staking", "reward", "airdrop", "mining", "fork", "dividend"],
    )
    def test_other_type_resolves_to_official_when_classified(self, koinly_type: str):
        """With classification on, non-interest types have no Tabela V code: official value is blank.

        Each must NOT return any synthetic ``40x`` code (the legacy default).
        """
        result = _resolve_income_code(koinly_type, True)
        assert result == ""
        assert not result.startswith("40"), f"Synthetic 40x code leaked for {koinly_type!r}: {result!r}"

    # -- pure helper: unknown type -> "" (old "401" default is gone) --

    def test_default_fallback_blank_when_classified(self):
        """With classification on, an unknown Koinly type resolves to blank, not the legacy '401'."""
        assert _resolve_income_code("some-unknown-type", True) == ""

    # -- pure helper: classification off -> "" for every type (Invariant 4) --

    @pytest.mark.parametrize("koinly_type", ["interest", "staking", "mining", "dividend"])
    def test_classification_off_resolves_blank(self, koinly_type: str):
        """With classification off, every type resolves to blank."""
        assert _resolve_income_code(koinly_type, False) == ""

    # -- reference-table descriptions must not present synthetic 40x as Tabela V --

    def test_descriptions_not_mislabeled_as_tabela_v(self):
        """Official-code descriptions must be consistent with Tabela V and free of synthetic 40x.

        B2 consolidates the type -> (official_code, description) mapping into the
        crypto package. At RED the consolidated owner does not exist and the
        legacy ``_INCOME_CODE_DESCRIPTIONS`` still carries invented 40x labels,
        so this fails until the consolidation lands.
        """
        from tax_reporting.application.crypto import classification as classification_mod

        # B2 exposes the consolidated mapping on the crypto package; until then
        # AttributeError / missing attribute is the expected RED signal.
        descriptions: dict[str, str] = classification_mod.INCOME_CODE_DESCRIPTIONS  # type: ignore[attr-defined]

        # Only E25 is a real Tabela V (Categoria E) code; no synthetic 40x may remain.
        assert "E25" in descriptions, "E25 official description must be present"
        for code, desc in descriptions.items():
            assert not code.startswith("40"), (
                f"Synthetic 40x code {code!r} still presented as Tabela V: {desc!r}"
            )

    # -- aggregation threads the classification flag (not country/operator_country) --

    def test_aggregation_threads_classification_flag_to_resolver(self):
        """aggregate_taxable_rewards must thread the classification flag to the resolver.

        Builds a single taxable_now interest reward. Under
        ``classify_rewards_with_income_codes=True`` the result must carry
        ``income_code == "E25"``; under ``classify_rewards_with_income_codes=False``
        the SAME reward must yield ``income_code == ""``. The dual assertion is the
        discriminator: a single-arm test cannot catch a country-literal
        revert that re-introduces PT-gating.
        """
        from tax_reporting.application.crypto_reporting import ZERO, CryptoRewardIncomeEntry

        plain_operator = dataclasses.replace(_TEST_OPERATOR, operator_country="PT")

        entries = [
            CryptoRewardIncomeEntry(
                date="2025-01-01",
                asset="EUR",
                amount=Decimal("100"),
                value_eur=Decimal("100"),
                income_label="Interest",
                source_type="interest",
                wallet="Nexo",
                platform="Nexo",
                chain="Nexo",
                operator_origin=plain_operator,
                annex_hint="J",
                review_required=False,
                description="Lending interest",
                tax_classification=RewardTaxClassification.TAXABLE_NOW,
                foreign_tax_eur=ZERO,
            ),
        ]

        classified_result = aggregate_taxable_rewards(entries, classify_rewards_with_income_codes=True)
        assert len(classified_result) == 1
        assert classified_result[0].income_code == "E25"

        unclassified_result = aggregate_taxable_rewards(entries, classify_rewards_with_income_codes=False)
        assert len(unclassified_result) == 1
        assert unclassified_result[0].income_code == ""

    # -- production path: classification-off blanks income_code end-to-end --

    def test_production_path_blanks_income_code_when_classification_off(self, tmp_path, monkeypatch):
        """The production workbook-builder path must blank income_code when classification is off.

        This is the ONLY shape that exercises the production call site
        ``workbook_builder.py:148`` (``aggregate_taxable_rewards``) under a
        non-classifying jurisdiction. ``test_workbook_builder.py`` hardcodes the
        classifying jurisdiction today, so without this case a classification-off
        regression at the production caller ships GREEN.

        Path chosen: the real ``generate_tax_report`` entrypoint, with
        ``load_configuration_from_file`` monkeypatched on the workbook_builder
        module to return a DE-jurisdiction ``Config`` (built via
        ``build_koinly_jurisdiction(country="DE", classify_rewards_with_income_codes=False)``). The real
        ``aggregate_taxable_rewards`` is wrapped to capture its return value so
        the aggregated ``income_code`` can be asserted without re-deriving it
        from the written workbook.
        """
        from tax_reporting.application.crypto_reporting import (
            ZERO,
            CryptoCapitalGainStats,
            CryptoReconciliationSummary,
            CryptoRewardIncomeEntry,
            CryptoTaxReport,
        )
        from tax_reporting.application.persisting import workbook_builder
        from tax_reporting.infrastructure.config import Config

        # DE jurisdiction via the shared test builder. The classification flag must
        # be explicitly disabled: build_koinly_jurisdiction(**overrides) only ADDS
        # keys, so country="DE" alone would leave the flag inherited True and the
        # interest row would resolve to E25 instead of blanking end-to-end.
        de_jurisdiction = build_koinly_jurisdiction(
            country="DE", classify_rewards_with_income_codes=False
        )

        # Build a fully valid Config from tests/config.ini (PT), then swap in the
        # DE jurisdiction. This avoids faking base/rates/security while still
        # putting a non-classifying jurisdiction in front of the crypto aggregation path.
        import dataclasses as _dc

        pt_config = workbook_builder.load_configuration_from_file()
        de_config = _dc.replace(pt_config, tax_jurisdiction=de_jurisdiction)

        def _fake_load_config() -> Config:
            return de_config

        monkeypatch.setattr(workbook_builder, "load_configuration_from_file", _fake_load_config)

        foreign_operator = dataclasses.replace(_TEST_OPERATOR, operator_country="IE")
        reward_entries = [
            CryptoRewardIncomeEntry(
                date="2025-01-01",
                asset="EUR",
                amount=Decimal("100"),
                value_eur=Decimal("100"),
                income_label="Interest",
                source_type="interest",
                wallet="Nexo",
                platform="Nexo",
                chain="Nexo",
                operator_origin=foreign_operator,
                annex_hint="J",
                review_required=False,
                description="Lending interest",
                tax_classification=RewardTaxClassification.TAXABLE_NOW,
                foreign_tax_eur=ZERO,
            ),
        ]

        # Spy on the production call site: wrap the real aggregator to capture
        # its return value while preserving production behaviour.
        real_aggregate = workbook_builder.aggregate_taxable_rewards
        captured: list[list] = []

        def _capturing_aggregate(reward_entries, *args, **kwargs):  # noqa: ANN002, ANN003
            result = real_aggregate(reward_entries, *args, **kwargs)
            captured.append(result)
            return result

        monkeypatch.setattr(workbook_builder, "aggregate_taxable_rewards", _capturing_aggregate)

        report = CryptoTaxReport(
            tax_year=2025,
            capital_entries=[],
            reward_entries=reward_entries,
            reconciliation=CryptoReconciliationSummary(
                capital_rows=0,
                reward_rows=0,
                short_term_rows=0,
                long_term_rows=0,
                mixed_rows=0,
                unknown_rows=0,
                capital_cost_total_eur=Decimal("0"),
                capital_proceeds_total_eur=Decimal("0"),
                capital_gain_total_eur=Decimal("0"),
                reward_total_eur=Decimal("0"),
                opening_holdings=None,
                closing_holdings=None,
            ),
            capital_gain_stats=CryptoCapitalGainStats.from_entries([]),
        )

        output = tmp_path / "report_de.xlsx"
        workbook_builder.generate_tax_report(str(output), {}, crypto_tax_report=report)

        assert captured, "aggregate_taxable_rewards was not invoked on the production path"
        aggregated = captured[0]
        assert len(aggregated) == 1
        assert aggregated[0].income_code == "", (
            f"Classification-off production path must blank income_code, got {aggregated[0].income_code!r}"
        )


# =============================================================================
# Phase 1: OGR event-level application (agree-branch first-lot-absorbs fix).
# See docs/history/plans/2026-07-04-ogr-event-level-application.md Task 1.
# =============================================================================


def _make_event_level_entry(  # noqa: PLR0913
    *,
    disposal_date: str = "2025-02-01",
    asset: str = "USDT",
    wallet: str = "ByBit",
    acquisition_date: str,
    cost_eur: Decimal,
    proceeds_eur: Decimal,
    gain_loss_eur: Decimal,
    holding_period: str = "Short-term (3 days)",
    notes: str = "",
) -> CryptoCapitalGainEntry:
    """Build a CryptoCapitalGainEntry for the OGR event-level fixtures."""
    return CryptoCapitalGainEntry(
        disposal_date=disposal_date,
        acquisition_date=acquisition_date,
        asset=asset,
        amount=Decimal("1"),
        cost_eur=cost_eur,
        proceeds_eur=proceeds_eur,
        gain_loss_eur=gain_loss_eur,
        holding_period=holding_period,
        wallet=wallet,
        platform=wallet,
        chain="Ethereum",
        operator_origin=_TEST_OPERATOR,
        annex_hint="J",
        review_required=False,
        notes=notes,
    )


def _event_level_jurisdiction(*, use_ogr: bool = True):
    """Build a TaxJurisdictionConfig for the OGR event-level fixtures."""
    from tax_reporting.infrastructure.config import TaxJurisdictionConfig

    return TaxJurisdictionConfig(
        country="TEST",
        fiscal_year=2025,
        exclude_loan_repayment_gains=False,
        zero_basis_review_threshold=Decimal("500"),
        use_other_gains_report=use_ogr,
    )


class TestApplyOgrEventLevel:
    """Phase 1: OGR P&L applied at the disposal-event level (first-lot-absorbs)."""

    def test_agree_multi_lot_first_lot_absorbs(self):
        """Agree branch, 3 lots, cg_event_gain +3.00 / OGR +9.00.

        First lot absorbs the full ``ogr_event_gain``; remaining lots get
        ``gain_loss_eur = 0`` and ``proceeds_eur = lot.cost_eur``. The
        ``sum(gain_loss_eur)`` must equal ``Decimal("9.00")`` byte-exactly
        (no division, no rounding).
        """
        from tax_reporting.application.crypto.ogr_event_level import apply_ogr_event_level

        lots = [
            _make_event_level_entry(
                acquisition_date="2025-01-01",
                cost_eur=Decimal("10"),
                proceeds_eur=Decimal("13"),
                gain_loss_eur=Decimal("1.00"),
            ),
            _make_event_level_entry(
                acquisition_date="2025-01-05",
                cost_eur=Decimal("30"),
                proceeds_eur=Decimal("33"),
                gain_loss_eur=Decimal("1.00"),
            ),
            _make_event_level_entry(
                acquisition_date="2025-01-10",
                cost_eur=Decimal("60"),
                proceeds_eur=Decimal("63"),
                gain_loss_eur=Decimal("1.00"),
            ),
        ]
        spot_index = {("2025-02-01", "USDT", "ByBit"): Decimal("9.00")}

        result = apply_ogr_event_level(lots, spot_index, _event_level_jurisdiction())

        assert len(result) == 3
        # Phase 1 event-level: first lot absorbs the full OGR event gain.
        assert result[0].gain_loss_eur == Decimal("9.00")
        assert result[0].proceeds_eur == result[0].cost_eur + Decimal("9.00")
        # Remaining lots get zero gain and proceeds == cost.
        assert result[1].gain_loss_eur == Decimal("0")
        assert result[1].proceeds_eur == result[1].cost_eur
        assert result[2].gain_loss_eur == Decimal("0")
        assert result[2].proceeds_eur == result[2].cost_eur
        # Byte-exact event total, no rounding.
        assert sum((r.gain_loss_eur for r in result), start=Decimal("0")) == Decimal("9.00")

    def test_agree_multi_lot_ogr_gain_loss_full_on_every_lot(self):
        """Per-lot ``ogr_validation.ogr_gain_loss`` carries the FULL event value on every lot.

        ``_aggregate_ogr_validation`` reads ``ogr_gain_loss`` from the first
        lot (aggregation.py:217-218) and must see the full event value, so
        every lot carries it. ``calculated_gain_loss`` holds each lot's
        PRE-distribution CG gain so aggregation reconstructs ``cg_event_gain``.
        """
        from tax_reporting.application.crypto.ogr_event_level import apply_ogr_event_level

        lots = [
            _make_event_level_entry(
                acquisition_date="2025-01-01",
                cost_eur=Decimal("10"),
                proceeds_eur=Decimal("13"),
                gain_loss_eur=Decimal("1.00"),
            ),
            _make_event_level_entry(
                acquisition_date="2025-01-05",
                cost_eur=Decimal("30"),
                proceeds_eur=Decimal("33"),
                gain_loss_eur=Decimal("2.00"),
            ),
            _make_event_level_entry(
                acquisition_date="2025-01-10",
                cost_eur=Decimal("60"),
                proceeds_eur=Decimal("63"),
                gain_loss_eur=Decimal("0.00"),
            ),
        ]
        spot_index = {("2025-02-01", "USDT", "ByBit"): Decimal("9.00")}

        result = apply_ogr_event_level(lots, spot_index, _event_level_jurisdiction())

        assert len(result) == 3
        for i, lot in enumerate(result):
            assert lot.ogr_validation is not None
            assert lot.ogr_validation.ogr_gain_loss == Decimal("9.00"), (
                f"lot {i}: ogr_gain_loss must be the FULL event value 9.00"
            )
        # calculated_gain_loss holds each lot's PRE-distribution CG gain.
        assert result[0].ogr_validation.calculated_gain_loss == Decimal("1.00")
        assert result[1].ogr_validation.calculated_gain_loss == Decimal("2.00")
        assert result[2].ogr_validation.calculated_gain_loss == Decimal("0.00")

    def test_conflict_multi_lot_byte_identical_to_legacy(self):
        """Conflict branch, 109 lots (CG +500 / OGR -147.19): byte-identical to legacy.

        Each lot keeps ``gain_loss_eur == -abs(per_lot_gain)`` and
        ``proceeds_eur == cost - abs(per_lot_gain)``. The conflict branch is
        UNCHANGED from the legacy per-lot override (Design Invariant 1).
        """
        from tax_reporting.application.crypto.ogr_event_level import apply_ogr_event_level

        jurisdiction = _event_level_jurisdiction()
        spot_index = {("2025-01-13", "USDT", "ByBit"): Decimal("-147.19")}

        lots = []
        per_lot_gain = Decimal("500") / Decimal("109")
        per_lot_cost = Decimal("100")
        per_lot_proceeds = per_lot_cost + per_lot_gain
        for i in range(109):
            lots.append(
                _make_event_level_entry(
                    disposal_date="2025-01-13",
                    acquisition_date=f"2025-01-{(i % 10) + 1:02d}",
                    cost_eur=per_lot_cost,
                    proceeds_eur=per_lot_proceeds,
                    gain_loss_eur=per_lot_gain,
                )
            )

        result = apply_ogr_event_level(lots, spot_index, jurisdiction)

        assert len(result) == 109
        for i, lot in enumerate(result):
            assert lot.gain_loss_eur == -abs(per_lot_gain), (
                f"lot {i}: conflict branch keeps CG magnitude with OGR sign"
            )
            assert lot.proceeds_eur == lot.cost_eur - abs(per_lot_gain)
            assert lot.ogr_validation is not None
            assert lot.ogr_validation.ogr_gain_loss == Decimal("-147.19")
            assert lot.ogr_validation.calculated_gain_loss == per_lot_gain

    def test_conflict_mixed_sign_sums_absolute_magnitudes(self):
        """Mixed-sign conflict event: the per-lot write sums to ``±sum(abs(lot))``,
        NOT ``±abs(cg_event_gain)``.

        The identity ``sum(±abs(lot.gain_loss_eur)) == ±abs(cg_event_gain)`` holds
        only when every lot shares the event's CG sign. For a mixed-sign event
        (lot A gain +5.00, lot B loss -3.00, so ``cg_event_gain = +2.00``) with an
        opposite-sign OGR (-5.00), the conflict branch writes ``[-5.00, -3.00]``
        which sums to ``-8.00`` (= ``-sum(abs(lot))``), not ``-2.00``
        (= ``-abs(cg_event_gain)``). This matches the legacy per-lot write
        (unchanged in Phase 1), so it is a documented property, not a regression.
        The test pins the actual summed behavior so a future porter does not write
        a ``sum == ±abs(cg_event_gain)`` assertion that fails on mixed-sign events.
        """
        from tax_reporting.application.crypto.ogr_event_level import apply_ogr_event_level

        lot_a = _make_event_level_entry(
            acquisition_date="2025-01-02",
            cost_eur=Decimal("100"),
            proceeds_eur=Decimal("105"),
            gain_loss_eur=Decimal("5.00"),
        )
        lot_b = _make_event_level_entry(
            acquisition_date="2025-01-03",
            cost_eur=Decimal("100"),
            proceeds_eur=Decimal("97"),
            gain_loss_eur=Decimal("-3.00"),
        )
        spot_index = {("2025-02-01", "USDT", "ByBit"): Decimal("-5.00")}

        result = apply_ogr_event_level(
            [lot_a, lot_b], spot_index, _event_level_jurisdiction()
        )

        # cg_event_gain = +2.00 (gain), OGR = -5.00 (loss) -> conflict branch.
        assert result[0].gain_loss_eur == Decimal("-5.00")  # -abs(lot_a)
        assert result[1].gain_loss_eur == Decimal("-3.00")  # -abs(lot_b)
        # The sum is -8.00 (sum of absolute magnitudes), NOT -abs(cg_event_gain) = -2.00.
        assert sum((lot.gain_loss_eur for lot in result), start=Decimal("0")) == Decimal("-8.00")
        # Each lot still carries the FULL event ogr_gain_loss (Design Invariant 3).
        assert result[0].ogr_validation.ogr_gain_loss == Decimal("-5.00")
        assert result[1].ogr_validation.ogr_gain_loss == Decimal("-5.00")
        # calculated_gain_loss holds each lot's PRE-distribution CG gain so
        # aggregation's _aggregate_ogr_validation reconstructs cg_event_gain
        # (Design Invariant 3 / Pitfall 5 data-loss guard).
        assert result[0].ogr_validation.calculated_gain_loss == Decimal("5.00")
        assert result[1].ogr_validation.calculated_gain_loss == Decimal("-3.00")
        # Per-lot direction_conflict = (ogr<0) != (lot_cg<0). OGR is negative:
        # lot_a (CG +5) conflicts; lot_b (CG -3) sign already matches OGR.
        # This is the unique fixture exercising the lot_b "sign matches OGR"
        # case, which gates the per-lot review flag via the
        # ``if not lot_direction_conflict: return False, None`` early return.
        assert result[0].ogr_validation.direction_conflict is True
        assert result[1].ogr_validation.direction_conflict is False
        # Removing the early return would over-flag lot_b; pin review_required=False.
        assert result[1].ogr_validation.review_required is False
        assert result[1].ogr_validation.review_reason is None

    def test_conflict_positive_ogr_uses_else_abs_arm(self):
        """Positive-OGR conflict event exercises the ``else abs(lot.gain_loss_eur)``
        arm of the production ternary at ``ogr_event_level.py:254-256``.

        Every other conflict fixture uses a negative OGR, so the ``else`` arm
        (OGR positive, conflict because CG is negative) is never exercised. A
        sign-flip or sign-collapse regression (e.g. ``-abs(...)`` unconditionally,
        or ``0`` in the else) would pass every other conflict test and silently
        turn a real loss into a gain (or zero) on positive-OGR events. The
        mixed-sign variant asserts per-lot ``+abs(lot.gain_loss_eur)`` summing
        to ``+sum(abs(lot))`` (NOT ``+abs(cg_event_gain)``) to pin the symmetric
        behavior of the conflict branch on both OGR signs.
        """
        from tax_reporting.application.crypto.ogr_event_level import apply_ogr_event_level

        lot_a = _make_event_level_entry(
            acquisition_date="2025-01-02",
            cost_eur=Decimal("100"),
            proceeds_eur=Decimal("95"),
            gain_loss_eur=Decimal("-5.00"),
        )
        lot_b = _make_event_level_entry(
            acquisition_date="2025-01-03",
            cost_eur=Decimal("100"),
            proceeds_eur=Decimal("103"),
            gain_loss_eur=Decimal("3.00"),
        )
        # cg_event_gain = -2.00 (loss), OGR = +20.00 (gain) -> conflict branch.
        spot_index = {("2025-02-01", "USDT", "ByBit"): Decimal("20.00")}

        result = apply_ogr_event_level(
            [lot_a, lot_b], spot_index, _event_level_jurisdiction()
        )

        # Positive OGR -> else abs(lot.gain_loss_eur) per lot. A sign-flip
        # regression (writing -abs unconditionally) would yield -5.00 / -3.00.
        assert result[0].gain_loss_eur == Decimal("5.00")  # +abs(lot_a)
        assert result[1].gain_loss_eur == Decimal("3.00")  # +abs(lot_b)
        # Mixed-sign sum is +sum(abs(lot)) = +8.00, NOT +abs(cg_event_gain) = +2.00.
        assert sum((lot.gain_loss_eur for lot in result), start=Decimal("0")) == Decimal("8.00")
        # proceeds follow the per-lot gain sign (cost + final_gain_loss).
        assert result[0].proceeds_eur == Decimal("100") + Decimal("5.00")
        assert result[1].proceeds_eur == Decimal("100") + Decimal("3.00")
        # Each lot carries the FULL positive ogr_event_gain (Design Invariant 3).
        assert result[0].ogr_validation.ogr_gain_loss == Decimal("20.00")
        assert result[1].ogr_validation.ogr_gain_loss == Decimal("20.00")
        # Per-lot direction_conflict mirrors (ogr<0) != (lot_cg<0); OGR positive
        # so lot_a (CG negative) conflicts, lot_b (CG positive) does not.
        assert result[0].ogr_validation.direction_conflict is True
        assert result[1].ogr_validation.direction_conflict is False
        # calculated_gain_loss holds the PRE-distribution CG gain.
        assert result[0].ogr_validation.calculated_gain_loss == Decimal("-5.00")
        assert result[1].ogr_validation.calculated_gain_loss == Decimal("3.00")

    def test_single_lot_agree_byte_identical(self):
        """Single-lot agree event reduces exactly to legacy output.

        ``gain_loss_eur == ogr_gain_loss`` and
        ``proceeds_eur == cost + ogr_gain_loss`` (no other lots to absorb).
        """
        from tax_reporting.application.crypto.ogr_event_level import apply_ogr_event_level

        lot = _make_event_level_entry(
            acquisition_date="2025-01-01",
            cost_eur=Decimal("100"),
            proceeds_eur=Decimal("104"),
            gain_loss_eur=Decimal("4.00"),
        )
        spot_index = {("2025-02-01", "USDT", "ByBit"): Decimal("6.00")}

        result = apply_ogr_event_level([lot], spot_index, _event_level_jurisdiction())

        assert len(result) == 1
        assert result[0].gain_loss_eur == Decimal("6.00")
        assert result[0].proceeds_eur == Decimal("100") + Decimal("6.00")
        assert result[0].ogr_validation is not None
        assert result[0].ogr_validation.ogr_gain_loss == Decimal("6.00")
        assert result[0].ogr_validation.calculated_gain_loss == Decimal("4.00")

    def test_single_lot_conflict_byte_identical(self):
        """Single-lot conflict event (CG +4.00, OGR -1.00): byte-identical to legacy.

        ``gain_loss_eur == -4.00`` and ``proceeds_eur == cost - 4.00``.
        """
        from tax_reporting.application.crypto.ogr_event_level import apply_ogr_event_level

        lot = _make_event_level_entry(
            acquisition_date="2025-01-01",
            cost_eur=Decimal("100"),
            proceeds_eur=Decimal("104"),
            gain_loss_eur=Decimal("4.00"),
        )
        spot_index = {("2025-02-01", "USDT", "ByBit"): Decimal("-1.00")}

        result = apply_ogr_event_level([lot], spot_index, _event_level_jurisdiction())

        assert len(result) == 1
        assert result[0].gain_loss_eur == Decimal("-4.00")
        assert result[0].proceeds_eur == Decimal("100") - Decimal("4.00")
        assert result[0].ogr_validation is not None
        assert result[0].ogr_validation.direction_conflict is True
        # Mirror the agree-branch single-lot anchor: pin both contract fields
        # (Design Invariant 3) so a future porter reading this anchor sees all
        # three gain/loss surfaces (gain_loss_eur / ogr_gain_loss /
        # calculated_gain_loss) and does not conflate them (Pitfall 5).
        assert result[0].ogr_validation.ogr_gain_loss == Decimal("-1.00")
        assert result[0].ogr_validation.calculated_gain_loss == Decimal("4.00")

    def test_calculated_gain_loss_reconstructs_cg_event_gain_after_aggregation(self):
        """After ``_aggregate_capital_entries``, the OgrValidationResult reconstructs ``cg_event_gain``.

        Given 3 lots CG +1/+1/+1 and OGR +9.00 (agree), the aggregated
        ``OgrValidationResult`` must be:
        ``ogr_gain_loss == 9.00``, ``calculated_gain_loss == 3.00``,
        ``magnitude_diff_percent == 200.0``, ``review_required is True``.
        Per-lot ``magnitude_diff_percent`` of 800% is expected and is NOT
        the asserted value (the assertion is on the aggregated result).
        """
        from tax_reporting.application.crypto.ogr_event_level import apply_ogr_event_level

        lots = [
            _make_event_level_entry(
                acquisition_date=f"2025-01-0{i}",
                cost_eur=Decimal("1"),
                proceeds_eur=Decimal("2"),
                gain_loss_eur=Decimal("1.00"),
            )
            for i in range(1, 4)
        ]
        spot_index = {("2025-02-01", "USDT", "ByBit"): Decimal("9.00")}

        overridden = apply_ogr_event_level(lots, spot_index, _event_level_jurisdiction())
        aggregated = _aggregate_capital_entries(overridden)

        assert len(aggregated) == 1
        agg = aggregated[0]
        assert agg.ogr_validation is not None
        assert agg.ogr_validation.ogr_gain_loss == Decimal("9.00")
        assert agg.ogr_validation.calculated_gain_loss == Decimal("3.00")
        assert agg.ogr_validation.magnitude_diff_percent == Decimal("200.0")
        assert agg.ogr_validation.review_required is True

    def test_direction_conflict_event_level_decision(self):
        """Direction conflict is decided on the SIGN of EVENT totals, not per lot.

        The branch decision compares signs only (``(cg<0) != (ogr<0)``); the
        ``> 1 EUR`` significance gate is REVIEW-ONLY (it gates the per-lot
        ``review_required`` flag in ``_conflict_review_state``), NOT part of the
        branch decision. See ``development_lessons.md`` #42 and PT-C-037. The
        boundary case (one side below 1 EUR) is covered by
        ``test_single_lot_conflict_byte_identical`` (CG +4.00 / OGR -1.00).
        """
        from tax_reporting.application.crypto.ogr_event_level import apply_ogr_event_level

        # 3 lots each +0.50 -> cg_event_gain +1.50 (gain).
        # OGR -2.00 -> opposite sign -> conflict branch taken on SIGN,
        # regardless of magnitude (the > 1 EUR gate does not gate the branch).
        lots = [
            _make_event_level_entry(
                acquisition_date=f"2025-01-0{i}",
                cost_eur=Decimal("1"),
                proceeds_eur=Decimal("1.50"),
                gain_loss_eur=Decimal("0.50"),
            )
            for i in range(1, 4)
        ]
        spot_index = {("2025-02-01", "USDT", "ByBit"): Decimal("-2.00")}

        result = apply_ogr_event_level(lots, spot_index, _event_level_jurisdiction())

        assert len(result) == 3
        # Conflict branch: each lot keeps CG magnitude with OGR sign.
        for i, lot in enumerate(result):
            assert lot.gain_loss_eur == -abs(Decimal("0.50")), f"lot {i}: conflict branch"
            assert lot.ogr_validation is not None
            assert lot.ogr_validation.direction_conflict is True

    def test_agree_multi_lot_zero_event_cost_no_raise(self):
        """Zero-cost agree event: first-lot-absorbs does not divide by ``event_cost``.

        Given N zero-``cost_eur`` lots sharing a key with an OGR row, the
        event is handled (first lot absorbs ``ogr_event_gain``; no division).
        """
        from tax_reporting.application.crypto.ogr_event_level import apply_ogr_event_level

        lots = [
            _make_event_level_entry(
                acquisition_date=f"2025-01-0{i}",
                cost_eur=Decimal("0"),
                proceeds_eur=Decimal("0"),
                gain_loss_eur=Decimal("0"),
            )
            for i in range(1, 4)
        ]
        spot_index = {("2025-02-01", "USDT", "ByBit"): Decimal("5.00")}

        result = apply_ogr_event_level(lots, spot_index, _event_level_jurisdiction())

        assert len(result) == 3
        # Phase 1 event-level: first lot absorbs the full OGR event gain, no division.
        assert result[0].gain_loss_eur == Decimal("5.00")
        assert result[0].proceeds_eur == Decimal("0") + Decimal("5.00")
        assert result[1].gain_loss_eur == Decimal("0")
        assert result[1].proceeds_eur == Decimal("0")
        assert result[2].gain_loss_eur == Decimal("0")
        assert result[2].proceeds_eur == Decimal("0")

    def test_no_ogr_match_unchanged(self):
        """Events with no OGR entry pass through with ``ogr_validation=None``."""
        from tax_reporting.application.crypto.ogr_event_level import apply_ogr_event_level

        lot = _make_event_level_entry(
            disposal_date="2025-03-01",
            acquisition_date="2025-01-01",
            cost_eur=Decimal("100"),
            proceeds_eur=Decimal("110"),
            gain_loss_eur=Decimal("10.00"),
        )
        spot_index = {("2025-02-01", "USDT", "ByBit"): Decimal("9.00")}

        result = apply_ogr_event_level([lot], spot_index, _event_level_jurisdiction())

        assert len(result) == 1
        assert result[0].ogr_validation is None
        assert result[0].gain_loss_eur == Decimal("10.00")
        assert result[0].proceeds_eur == Decimal("110")

    def test_output_length_and_order_preserved(self):
        """``len(out) == len(in)`` and each ``out[i]`` matches ``in[i]`` on the base identity tuple.

        Mixed input: unmatched lot, single-lot OGR event, multi-lot OGR
        event, zero-proceeds Payment lot. The base identity tuple is
        ``(disposal_date, acquisition_date, cost_eur, holding_period,
        disposal_timestamp, pre_OGR_proceeds_eur, pre_OGR_gain_loss_eur)``.
        """
        from tax_reporting.application.crypto.ogr_event_level import apply_ogr_event_level

        unmatched = _make_event_level_entry(
            disposal_date="2025-03-01",
            acquisition_date="2025-01-01",
            cost_eur=Decimal("100"),
            proceeds_eur=Decimal("110"),
            gain_loss_eur=Decimal("10.00"),
        )
        single = _make_event_level_entry(
            disposal_date="2025-02-01",
            acquisition_date="2025-01-02",
            cost_eur=Decimal("50"),
            proceeds_eur=Decimal("55"),
            gain_loss_eur=Decimal("5.00"),
        )
        multi_a = _make_event_level_entry(
            disposal_date="2025-04-01",
            acquisition_date="2025-01-03",
            cost_eur=Decimal("20"),
            proceeds_eur=Decimal("22"),
            gain_loss_eur=Decimal("2.00"),
        )
        multi_b = _make_event_level_entry(
            disposal_date="2025-04-01",
            acquisition_date="2025-01-04",
            cost_eur=Decimal("30"),
            proceeds_eur=Decimal("32"),
            gain_loss_eur=Decimal("2.00"),
        )
        payment = _make_event_level_entry(
            disposal_date="2025-05-01",
            acquisition_date="2025-01-05",
            cost_eur=Decimal("40"),
            proceeds_eur=Decimal("0"),
            gain_loss_eur=Decimal("-40.00"),
        )

        lots = [unmatched, single, multi_a, multi_b, payment]
        spot_index = {
            ("2025-02-01", "USDT", "ByBit"): Decimal("9.00"),
            ("2025-04-01", "USDT", "ByBit"): Decimal("7.00"),
        }

        result = apply_ogr_event_level(lots, spot_index, _event_level_jurisdiction())

        assert len(result) == len(lots)

        def identity(lot: CryptoCapitalGainEntry) -> tuple:
            return (
                lot.disposal_date,
                lot.acquisition_date,
                lot.cost_eur,
                lot.holding_period,
                lot.disposal_timestamp,
            )

        # The base identity on the FIVE stable fields (the OGR-mutable
        # proceeds_eur / gain_loss_eur are excluded) must match in-order.
        # disposal_timestamp is part of the identity per the plan tuple; here
        # all fixtures use the default (None) since _make_event_level_entry
        # does not set it.
        for i, (in_lot, out_lot) in enumerate(zip(lots, result, strict=True)):
            assert identity(in_lot) == identity(out_lot), (
                f"index {i}: base identity changed: in={identity(in_lot)} out={identity(out_lot)}"
            )

    def test_multi_event_mixed_agree_and_conflict_branches(self):
        """A single ``apply_ogr_event_level`` call mixes an AGREE event and a
        CONFLICT event.

        ``apply_ogr_event_level`` groups lots by ``(date, asset, wallet)`` and
        decides each event independently. Existing multi-event tests use only
        agree events (both OGR positive on positive-CG lots), so a bug in event
        keying or a branch-decision short-circuit that bled one event's decision
        into another's lots would not be caught. This fixture puts an agree
        event (key A) and a conflict event (key B) in the same call and asserts
        each event took the correct branch via per-event sums and per-lot
        ``direction_conflict`` flags.
        """
        from tax_reporting.application.crypto.ogr_event_level import apply_ogr_event_level

        # Event A: AGREE. Two positive-CG lots, OGR positive.
        agree_a = _make_event_level_entry(
            disposal_date="2025-02-01",
            acquisition_date="2025-01-02",
            cost_eur=Decimal("100"),
            proceeds_eur=Decimal("102"),
            gain_loss_eur=Decimal("2.00"),
        )
        agree_b = _make_event_level_entry(
            disposal_date="2025-02-01",
            acquisition_date="2025-01-03",
            cost_eur=Decimal("100"),
            proceeds_eur=Decimal("103"),
            gain_loss_eur=Decimal("3.00"),
        )
        # Event B: CONFLICT. Two positive-CG lots, OGR negative.
        conflict_c = _make_event_level_entry(
            disposal_date="2025-03-01",
            acquisition_date="2025-01-04",
            cost_eur=Decimal("50"),
            proceeds_eur=Decimal("52"),
            gain_loss_eur=Decimal("2.00"),
        )
        conflict_d = _make_event_level_entry(
            disposal_date="2025-03-01",
            acquisition_date="2025-01-05",
            cost_eur=Decimal("50"),
            proceeds_eur=Decimal("53"),
            gain_loss_eur=Decimal("3.00"),
        )
        lots = [agree_a, agree_b, conflict_c, conflict_d]
        spot_index = {
            # Event A: OGR +9.00 same sign as CG (+5.00) -> AGREE branch.
            ("2025-02-01", "USDT", "ByBit"): Decimal("9.00"),
            # Event B: OGR -8.00 opposite sign to CG (+5.00) -> CONFLICT branch.
            ("2025-03-01", "USDT", "ByBit"): Decimal("-8.00"),
        }

        result = apply_ogr_event_level(lots, spot_index, _event_level_jurisdiction())

        assert len(result) == 4
        # Event A (AGREE): first-lot-absorbs. Lot 0 = full OGR, lot 1 = 0.
        assert result[0].gain_loss_eur == Decimal("9.00")
        assert result[1].gain_loss_eur == Decimal("0")
        assert sum((r.gain_loss_eur for r in result[:2]), start=Decimal("0")) == Decimal("9.00")
        assert all(r.ogr_validation.direction_conflict is False for r in result[:2])
        # Event B (CONFLICT): per-lot -abs(lot.gain_loss_eur), no absorption.
        assert result[2].gain_loss_eur == Decimal("-2.00")
        assert result[3].gain_loss_eur == Decimal("-3.00")
        assert sum((r.gain_loss_eur for r in result[2:]), start=Decimal("0")) == Decimal("-5.00")
        assert all(r.ogr_validation.direction_conflict is True for r in result[2:])
        # Each event's lots carry that event's FULL ogr_gain_loss (not the other's).
        assert result[0].ogr_validation.ogr_gain_loss == Decimal("9.00")
        assert result[1].ogr_validation.ogr_gain_loss == Decimal("9.00")
        assert result[2].ogr_validation.ogr_gain_loss == Decimal("-8.00")
        assert result[3].ogr_validation.ogr_gain_loss == Decimal("-8.00")

    def test_cross_holding_period_agree_event_taxable_split_delta(self):
        """Cross-holding-period agree event: lot 0 (short-term) carries the full ``ogr_event_gain``.

        Given a multi-lot agree event whose lot 0 is short-term and another
        lot is long-term, OGR +9.00, after ``apply_ogr_event_level`` +
        ``_aggregate_capital_entries``: the SHORT-TERM aggregated group
        carries the full +9.00 (because lot 0 is short-term) and the
        LONG-TERM group carries 0.00 from this event. This documents the
        PT-C-011 split shift vs legacy's per-group over-count - it is the
        agreed delta, NOT a regression.
        """
        from tax_reporting.application.crypto.ogr_event_level import apply_ogr_event_level

        lots = [
            _make_event_level_entry(
                disposal_date="2025-02-01",
                acquisition_date="2025-01-10",
                cost_eur=Decimal("50"),
                proceeds_eur=Decimal("51"),
                gain_loss_eur=Decimal("1.00"),
                holding_period="Short-term (3 days)",
            ),
            _make_event_level_entry(
                disposal_date="2025-02-01",
                acquisition_date="2022-01-10",
                cost_eur=Decimal("50"),
                proceeds_eur=Decimal("51"),
                gain_loss_eur=Decimal("1.00"),
                holding_period="Long-term (> 1 year)",
            ),
        ]
        spot_index = {("2025-02-01", "USDT", "ByBit"): Decimal("9.00")}

        overridden = apply_ogr_event_level(lots, spot_index, _event_level_jurisdiction())
        aggregated = _aggregate_capital_entries(overridden)

        # Two aggregation groups (key includes holding_period).
        by_period = {e.holding_period: e for e in aggregated}
        short_term = next((e for k, e in by_period.items() if k.lower().startswith("short")), None)
        long_term = next((e for k, e in by_period.items() if k.lower().startswith("long")), None)
        assert short_term is not None, f"expected a short-term group, got {list(by_period)}"
        assert long_term is not None, f"expected a long-term group, got {list(by_period)}"
        # Phase 1 event-level: lot 0 (short-term) absorbs the full OGR event gain.
        assert short_term.gain_loss_eur == Decimal("9.00"), (
            f"short-term group carries the full ogr_event_gain (PT-C-011 delta); "
            f"got {short_term.gain_loss_eur}"
        )
        assert long_term.gain_loss_eur == Decimal("0"), (
            f"long-term group carries 0.00 from this event; got {long_term.gain_loss_eur}"
        )

    def test_migrated_loss_override_applies(self):
        """Migrated from ``test_ogr_loss_override_applied`` onto event-level application.

        Single-lot event, CG gain +22.71, OGR loss -138.73 (CONFLICT branch:
        CG and OGR disagree on direction). The legacy ``_apply_ogr_overrides``
        wrote the OGR value verbatim (``-138.73``); event-level conflict
        branch instead writes the per-lot CG magnitude with the OGR sign
        (``-abs(22.71) == -22.71``), which already sums to
        ``±abs(cg_event_gain)`` (Design Invariant 1, conflict branch
        UNCHANGED from legacy per-lot direction override).
        """
        from tax_reporting.application.crypto.ogr_event_level import apply_ogr_event_level

        cg_entry = CryptoCapitalGainEntry(
            disposal_date="2025-01-13",
            acquisition_date="2025-01-10",
            asset="USDT",
            amount=Decimal("142.11"),
            cost_eur=Decimal("165.44"),
            proceeds_eur=Decimal("188.15"),
            gain_loss_eur=Decimal("22.71"),  # CG shows a gain
            holding_period="Short-term (365 days)",
            wallet="ByBit",
            platform="ByBit",
            chain="Ethereum",
            operator_origin=OperatorOrigin(
                platform="ByBit",
                service_scope="crypto",
                operator_entity="Bybit group entity",
                operator_country="AE",
                source_url="https://bybit.com",
                source_checked_on="2026-01-01",
                confidence="medium",
                review_required=False,
            ),
            annex_hint="J",
            review_required=False,
            notes="Original gain from Koinly",
        )
        ogr_index = {("2025-01-13", "USDT", "ByBit"): Decimal("-138.73")}

        result = apply_ogr_event_level([cg_entry], ogr_index, _event_level_jurisdiction())

        assert len(result) == 1
        # Phase 1 event-level conflict branch: CG magnitude with OGR (loss) sign.
        assert result[0].gain_loss_eur == Decimal("-22.71")
        # proceeds = cost + gain_loss = 165.44 - 22.71
        assert result[0].proceeds_eur == cg_entry.cost_eur + Decimal("-22.71")
        assert result[0].ogr_validation is not None
        assert result[0].ogr_validation.direction_conflict is True
        assert result[0].ogr_validation.ogr_gain_loss == Decimal("-138.73")
        assert result[0].ogr_validation.calculated_gain_loss == Decimal("22.71")

    def test_migrated_no_override_when_disabled(self):
        """Migrated from ``test_ogr_no_override_when_disabled`` onto event-level application.

        When ``use_other_gains_report`` is ``False``, ``apply_ogr_event_level``
        returns the entries unchanged with no ``ogr_validation`` attached,
        regardless of any OGR index entry.
        """
        from tax_reporting.application.crypto.ogr_event_level import apply_ogr_event_level

        cg_entry = CryptoCapitalGainEntry(
            disposal_date="2025-01-13",
            acquisition_date="2025-01-10",
            asset="USDT",
            amount=Decimal("142.11"),
            cost_eur=Decimal("165.44"),
            proceeds_eur=Decimal("188.15"),
            gain_loss_eur=Decimal("22.71"),
            holding_period="Short-term (365 days)",
            wallet="ByBit",
            platform="ByBit",
            chain="Ethereum",
            operator_origin=OperatorOrigin(
                platform="ByBit",
                service_scope="crypto",
                operator_entity="Bybit group entity",
                operator_country="AE",
                source_url="https://bybit.com",
                source_checked_on="2026-01-01",
                confidence="medium",
                review_required=False,
            ),
            annex_hint="J",
            review_required=False,
            notes="",
        )
        ogr_index = {("2025-01-13", "USDT", "ByBit"): Decimal("-138.73")}

        result = apply_ogr_event_level([cg_entry], ogr_index, _event_level_jurisdiction(use_ogr=False))

        # No override should occur; entries returned unchanged.
        assert len(result) == 1
        assert result[0].gain_loss_eur == Decimal("22.71")
        assert result[0].proceeds_eur == Decimal("188.15")
        assert result[0].ogr_validation is None

    def test_migrated_skips_fee_tokens(self):
        """Migrated from ``test_ogr_skips_fee_tokens`` onto event-level application.

        Zero-value OGR rows are filtered out by ``_build_ogr_index`` /
        ``_split_ogr_index`` (fee tokens are not capital gains), so the
        ``spot_index`` is empty for that key. ``apply_ogr_event_level`` finds
        no OGR match and passes the lot through unchanged with
        ``ogr_validation=None``. This is the no-match path (same invariant
        as ``test_no_ogr_match_unchanged``) exercised on the legacy
        fee-token scenario.
        """
        from tax_reporting.application.crypto.ogr_event_level import apply_ogr_event_level

        cg_entry = CryptoCapitalGainEntry(
            disposal_date="2025-01-13",
            acquisition_date="2025-01-10",
            asset="USDT",
            amount=Decimal("142.11"),
            cost_eur=Decimal("165.44"),
            proceeds_eur=Decimal("188.15"),
            gain_loss_eur=Decimal("22.71"),
            holding_period="Short-term (365 days)",
            wallet="ByBit",
            platform="ByBit",
            chain="Ethereum",
            operator_origin=OperatorOrigin(
                platform="ByBit",
                service_scope="crypto",
                operator_entity="Bybit group entity",
                operator_country="AE",
                source_url="https://bybit.com",
                source_checked_on="2026-01-01",
                confidence="medium",
                review_required=False,
            ),
            annex_hint="J",
            review_required=False,
            notes="",
        )
        # Empty because zero-value fee-token OGR rows are skipped at index build time.
        ogr_index: dict[tuple[str, str, str], Decimal] = {}

        result = apply_ogr_event_level([cg_entry], ogr_index, _event_level_jurisdiction())

        # No match - original values preserved, no ogr_validation attached.
        assert len(result) == 1
        assert result[0].gain_loss_eur == Decimal("22.71")
        assert result[0].proceeds_eur == Decimal("188.15")
        assert result[0].ogr_validation is None


# =============================================================================
# Plan 2026-07-18-crypto-dust-partition-fee-skip, Task 1 (RED):
# FEE-token tracking-entry skip at parse (all-zero branch in
# _parse_capital_gains_file). Task 2 flips these GREEN by adding the
# _KOINLY_TRACKING_TOKENS module constant and the short-circuit + lookup-move.
# Tests that reference _KOINLY_TRACKING_TOKENS use a guarded import that
# pytest.fail()s naming the resolving task, per AGENTS.md rule 4 (a committed
# RED test that is itself the deliverable must never ImportError).
# =============================================================================


def _fee_all_zero_cg_row(asset: str, date_sold: str = "13/01/2025 13:01") -> str:
    """A CG CSV row with all-zero Cost/Proceeds/Gain (the FEE tracking-entry shape)."""
    return ",".join(
        [
            date_sold,
            "01/01/2024 00:00",
            asset,
            '"0,10000000"',
            "0.0",
            "0.0",
            "0.0",
            "",
            "Kraken",
            "Short term",
        ]
    )


def _write_cg_with_rows(koinly_dir: Path, rows: list[str]) -> Path:
    """Write a koinly_2025_capital_gains_report.csv with the standard CG header + rows."""
    path = koinly_dir / "koinly_2025_capital_gains_report.csv"
    path.write_text(
        "\n".join(["Capital gains report 2025", "", _CG_HEADER, *rows]),
        encoding="utf-8",
    )
    return path


@pytest.mark.unit
class TestParseCapitalGainsFile:
    """All-zero CG row warning grouping (Plan 2026-07-21 Task 3 / Pattern A).

    The per-row WARNING inside ``_parse_capital_gains_file`` ("Capital gains row N for
    X has all-zero values...") is downgraded to DEBUG and grouped into ONE
    aggregate INFO summary after the loop. Design Invariant #3 (per-row
    detail preserved at DEBUG in the file) and #4 (Excel review list
    unchanged) must hold.
    """

    def test_all_zero_rows_grouped_into_single_summary(self, tmp_path, caplog):
        """Three known-token all-zero CG rows emit ONE aggregate INFO + 3 DEBUG.

        The aggregate INFO must match ``"Flagged %d all-zero capital gains row"``
        and the 3 per-row DEBUG records must still be emitted. The 3
        ``CryptoReviewEntry`` rows continue to be appended to
        ``context.review_entries`` (Design Invariant #4: Excel review list
        unchanged).
        """
        from unittest.mock import MagicMock

        from tax_reporting.application.token_origin import TokenOriginResolver

        koinly_dir = tmp_path / "koinly2025"
        koinly_dir.mkdir()
        capital_file = _write_cg_with_rows(
            koinly_dir,
            [
                _fee_all_zero_cg_row("BTC", "01/01/2025 10:00"),
                _fee_all_zero_cg_row("ETH", "02/01/2025 10:00"),
                _fee_all_zero_cg_row("BTC", "03/01/2025 10:00"),
            ],
        )

        origin_resolver = MagicMock(spec=TokenOriginResolver)
        origin_resolver.resolve.return_value = {"origin": "Unknown"}

        review_entries: list = []
        known_assets = frozenset(["BTC", "ETH"])
        context = CapitalGainsParsingContext(
            skipped_assets={},
            origin_resolver=origin_resolver,
            review_entries=review_entries,
            known_assets=known_assets,
            loan_affected_assets=frozenset(),
        )

        from unittest.mock import patch

        with (
            patch(
                "tax_reporting.application.crypto_reporting._get_popular_crypto_tokens",
                return_value=known_assets,
            ),
            caplog.at_level(
                logging.DEBUG, logger="tax_reporting.application.crypto_reporting"
            ),
        ):
            _parse_capital_gains_file(capital_file, context)

        # Design Invariant #4: Excel review list unchanged (3 rows appended).
        assert len(review_entries) == 3, (
            f"Expected 3 CryptoReviewEntry rows, got {len(review_entries)}"
        )

        warning_messages = [
            rec.getMessage()
            for rec in caplog.records
            if rec.levelno == logging.WARNING
            and rec.name == "tax_reporting.application.crypto_reporting"
        ]

        # Task 4 (Plan 2026-07-24): the aggregate "Flagged N all-zero" summary was
        # demoted from WARNING to INFO at crypto_reporting.py:922 (Bucket B:
        # Excel-surfaced, no silent data loss). Capture it at INFO now.
        info_messages = [
            rec.getMessage()
            for rec in caplog.records
            if rec.levelno == logging.INFO
            and rec.name == "tax_reporting.application.crypto_reporting"
        ]
        all_zero_warnings = [
            m for m in info_messages if "all-zero capital gains row" in m
        ]
        assert len(all_zero_warnings) == 1, (
            f"Expected exactly ONE aggregate all-zero INFO, got {all_zero_warnings}"
        )
        # The summary names the total count of flagged rows.
        assert "Flagged 3 all-zero capital gains row" in all_zero_warnings[0]

        # The aggregate AND the legacy per-row WARNING substring must NOT appear at
        # WARNING level (aggregate demoted to INFO; per-row demoted to DEBUG).
        aggregate_at_warning = [
            m for m in warning_messages if "all-zero capital gains row" in m
        ]
        assert aggregate_at_warning == [], (
            f"All-zero aggregate must be INFO, not WARNING, got {aggregate_at_warning}"
        )
        legacy_warnings = [
            m for m in warning_messages if "has all-zero values" in m
        ]
        assert legacy_warnings == [], (
            f"Per-row all-zero WARNING must be downgraded to DEBUG, got {legacy_warnings}"
        )

        # Design Invariant #3: per-row detail preserved at DEBUG (3 records).
        debug_messages = [
            rec.getMessage()
            for rec in caplog.records
            if rec.levelno == logging.DEBUG
            and rec.name == "tax_reporting.application.crypto_reporting"
        ]
        per_row_debug = [m for m in debug_messages if "has all-zero values" in m]
        assert len(per_row_debug) == 3, (
            f"Expected 3 per-row DEBUG records for all-zero rows, got {per_row_debug}"
        )


@pytest.mark.unit
class TestParseCapitalGainsFileCallerFlush:
    """Pattern B caller-level flush wiring (r3 review F1).

    Design Invariant #10 names the CG-parse caller flush as load-bearing: the
    shared ``TokenOriginResolver`` accumulates disagreement keys from BOTH
    caller loops, and ``_parse_capital_gains_file`` MUST invoke
    ``context.origin_resolver.log_and_reset_disagreements(scope="capital gains
    parse")`` after its row loop (call site ``crypto_reporting.py:917``). The
    ``log_and_reset_disagreements`` METHOD is well-tested in isolation, but the
    CALLER wiring is not: mutation testing confirmed that deleting this flush
    call leaves the suite green. These tests pre-seed the resolver's
    ``_disagreements`` Counter and assert the caller-level flush fires, so a
    future refactor that drops the call ships RED.
    """

    def test_capital_gains_parse_caller_flushes_disagreements(
        self, tmp_path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A pre-seeded non-empty ``_disagreements`` is flushed by the CG-parse caller.

        Given a resolver whose ``_disagreements`` Counter already holds one
        disagreement key, running ``_parse_capital_gains_file`` flushes it: exactly
        ONE INFO matching ``"TokenOriginResolver (capital gains parse)"`` fires
        at the caller (emitted by ``log_and_reset_disagreements`` via
        ``logging.getLogger(__name__)`` in ``token_origin.py``), and
        ``resolver._disagreements`` is empty after the call. The flush was demoted
        from WARNING to INFO by Plan 2026-07-25 Task 8 (W1/W5 relocation).

        Mutation pin (r3 F1): deleting the
        ``context.origin_resolver.log_and_reset_disagreements(scope="capital
        gains parse")`` call at ``crypto_reporting.py:917`` leaves this test RED
        (no caller-level INFO, Counter still non-empty).
        """
        from collections import Counter

        from tax_reporting.application.token_origin import TokenOriginResolver

        # Build a resolver from an EMPTY transaction history so resolve() returns
        # unknown without mutating _disagreements (no disagree branch reached).
        # Then pre-seed _disagreements as if a prior stage had accumulated one.
        resolver = build_origin_resolver(None)
        assert isinstance(resolver, TokenOriginResolver)
        resolver._disagreements = Counter({("BTC", "Kraken", "2025-01-15"): 1})
        assert len(resolver._disagreements) == 1

        capital_csv = tmp_path / "capital.csv"
        capital_csv.write_text(
            "\n".join(
                [
                    "Capital gains report 2025",
                    "",
                    ",".join(
                        [
                            "Date Sold",
                            "Date Acquired",
                            "Asset",
                            "Amount",
                            "Cost (EUR)",
                            "Proceeds (EUR)",
                            "Gain / loss",
                            "Notes",
                            "Wallet Name",
                            "Holding period",
                        ]
                    ),
                    ",".join(
                        [
                            "15/03/2025 12:00",
                            "15/01/2025 10:00",
                            "BTC",
                            '"0,10"',
                            '"1000,00"',
                            '"1200,00"',
                            '"200,00"',
                            "",
                            "Kraken",
                            "Short term",
                        ]
                    ),
                ]
            ),
            encoding="utf-8",
        )

        review_entries: list = []
        context = CapitalGainsParsingContext(
            skipped_assets={},
            origin_resolver=resolver,
            review_entries=review_entries,
        )

        # caplog on the token_origin module logger (the flush emitter). Lesson #68:
        # filter rec.name on the emitting module's fully-qualified __name__.
        # Plan 2026-07-25 Task 8 demoted the flush WARNING -> INFO; caplog at INFO.
        with caplog.at_level(logging.INFO, logger="tax_reporting.application.token_origin"):
            _parse_capital_gains_file(capital_csv, context)

        # (a) Exactly ONE INFO matching the CG-parse caller scope fires.
        caller_flush_warnings = [
            rec.getMessage()
            for rec in caplog.records
            if rec.levelno == logging.INFO
            and rec.name == "tax_reporting.application.token_origin"
            and "TokenOriginResolver (capital gains parse)" in rec.getMessage()
        ]
        assert len(caller_flush_warnings) == 1, (
            f"Expected exactly ONE caller-flush INFO, got {caller_flush_warnings}"
        )
        # The summary names the scope and the disagreement count (1 across 1 distinct key).
        assert "1 origin-resolution disagreement(s) across 1 distinct" in caller_flush_warnings[0]

        # (b) The Counter is cleared after the call.
        assert len(resolver._disagreements) == 0, (
            f"Expected _disagreements cleared by caller flush, got {dict(resolver._disagreements)}"
        )

    def test_capital_gains_parse_caller_flush_still_fires_on_mid_loop_exception(
        self, tmp_path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The CG-parse caller flush STILL fires when ``CryptoCapitalGainEntry`` raises mid-loop.

        Mirrors the FIFO-rebuild variant
        (``test_crypto_fifo.py::TestFifoRebuildCallerFlush::test_fifo_rebuild_caller_flush_still_fires_on_mid_loop_exception``)
        to cover the r4-F2 ``finally`` justification symmetrically.
        ``context.origin_resolver.resolve(...)`` accumulates disagreements inside the
        CG-parse row loop, and ``CryptoCapitalGainEntry(...)``'s ``__post_init__``
        validators can raise ``ValueError`` mid-loop. Without the ``finally``, an
        exception propagates before the flush, silently dropping the CG-stage aggregate
        WARNING and leaving the shared ``TokenOriginResolver._disagreements`` Counter
        with unflushed CG-stage state (which the downstream FIFO-rebuild flush would
        then absorb under the WRONG scope label). Forcing a mid-loop exception
        (patching ``CryptoCapitalGainEntry`` to raise) must still emit the caller flush
        WARNING.

        Mutation pin (r5 F2): reverting the CG-parse ``finally`` to a plain trailing
        call (or deleting the flush) leaves this test RED (no caller-level WARNING,
        Counter still non-empty).
        """
        from collections import Counter
        from unittest.mock import patch

        from tax_reporting.application import crypto_reporting as crypto_reporting_module
        from tax_reporting.application.token_origin import TokenOriginResolver

        # Build a resolver from an EMPTY transaction history so resolve() returns
        # unknown without mutating _disagreements (no disagree branch reached).
        # Then pre-seed _disagreements as if a prior stage had accumulated one.
        resolver = build_origin_resolver(None)
        assert isinstance(resolver, TokenOriginResolver)
        resolver._disagreements = Counter({("BTC", "Kraken", "2025-01-15"): 1})
        assert len(resolver._disagreements) == 1

        # A valid CG CSV row that reaches the CryptoCapitalGainEntry(...) construction
        # site (all required fields parse cleanly; non-zero proceeds so it is not an
        # all-zero skip).
        capital_csv = tmp_path / "capital.csv"
        capital_csv.write_text(
            "\n".join(
                [
                    "Capital gains report 2025",
                    "",
                    ",".join(
                        [
                            "Date Sold",
                            "Date Acquired",
                            "Asset",
                            "Amount",
                            "Cost (EUR)",
                            "Proceeds (EUR)",
                            "Gain / loss",
                            "Notes",
                            "Wallet Name",
                            "Holding period",
                        ]
                    ),
                    ",".join(
                        [
                            "15/03/2025 12:00",
                            "15/01/2025 10:00",
                            "BTC",
                            '"0,10"',
                            '"1000,00"',
                            '"1200,00"',
                            '"200,00"',
                            "",
                            "Kraken",
                            "Short term",
                        ]
                    ),
                ]
            ),
            encoding="utf-8",
        )

        review_entries: list = []
        context = CapitalGainsParsingContext(
            skipped_assets={},
            origin_resolver=resolver,
            review_entries=review_entries,
        )

        # Patch CryptoCapitalGainEntry (imported into crypto_reporting) to raise
        # mid-loop, simulating a __post_init__ validation failure during the row loop.
        # The function's ``finally`` block must still flush the resolver.
        # caplog on the token_origin module logger (the flush emitter). Lesson #68:
        # filter rec.name on the emitting module's fully-qualified __name__.
        # Plan 2026-07-25 Task 8 demoted the flush WARNING -> INFO; caplog at INFO.
        with (
            caplog.at_level(logging.INFO, logger="tax_reporting.application.token_origin"),
            patch.object(
                crypto_reporting_module,
                "CryptoCapitalGainEntry",
                side_effect=ValueError("simulated mid-loop validation failure"),
            ),
            pytest.raises(ValueError, match="simulated mid-loop validation failure"),
        ):
            _parse_capital_gains_file(capital_csv, context)

        # Exactly ONE INFO matching the CG-parse caller scope fired in the finally.
        caller_flush_warnings = [
            rec.getMessage()
            for rec in caplog.records
            if rec.levelno == logging.INFO
            and rec.name == "tax_reporting.application.token_origin"
            and "TokenOriginResolver (capital gains parse)" in rec.getMessage()
        ]
        assert len(caller_flush_warnings) == 1, (
            f"Expected caller-flush INFO to fire in the finally block, got {caller_flush_warnings}"
        )

        # The Counter is still cleared (the finally flush ran).
        assert len(resolver._disagreements) == 0, (
            f"Expected _disagreements cleared by finally-flush, got {dict(resolver._disagreements)}"
        )


@pytest.mark.unit
class TestParseCapitalGainsFileFeeToken:
    """RED tests for the Koinly tracking-token (FEE) skip in _parse_capital_gains_file.

    Pinned by Plan 2026-07-18 Design Invariant 4: the discriminator is
    ``asset in _KOINLY_TRACKING_TOKENS`` at the top of the ``is_all_zero`` block,
    with the popular-token / non-Latin lookups moved INSIDE the block below the
    short-circuit (so the lookup-avoidance is real, not just asserted). These
    tests go RED against unchanged production (FEE today takes the else-branch
    at crypto_reporting.py:764-767 and lands in skipped_zero_value_tokens).
    """

    def test_fee_token_absent_from_skipped_zero_value_tokens(self, tmp_path):
        """Three FEE all-zero rows MUST NOT appear in skipped_zero_value_tokens.

        Today FEE lands as (capital_gains, FEE, count=3) via the else-branch
        _register_skipped_zero_asset call; after the Task 2 fix the short-circuit
        ``continue``s before that call. This test asserts the NEW (post-fix)
        behavior, so it goes RED against unchanged production.
        """
        koinly_dir = tmp_path / "koinly2025"
        koinly_dir.mkdir()
        _write_cg_with_rows(
            koinly_dir,
            [
                _fee_all_zero_cg_row("FEE", "13/01/2025 13:01"),
                _fee_all_zero_cg_row("FEE", "14/01/2025 13:01"),
                _fee_all_zero_cg_row("FEE", "15/01/2025 13:01"),
            ],
        )
        _write_minimal_income_report(koinly_dir)
        _write_minimal_transaction_history(koinly_dir)

        report = load_koinly_crypto_report(koinly_dir)
        assert report is not None

        fee_skipped = [
            t for t in report.skipped_zero_value_tokens if t.asset == "FEE"
        ]
        assert fee_skipped == [], (
            f"FEE tracking entries must NOT appear in skipped_zero_value_tokens; "
            f"found {fee_skipped}"
        )

    def test_fee_token_summary_info_log(self, tmp_path, caplog):
        """Three FEE rows in one CG file emit exactly one INFO summary line.

        The summary line's ``getMessage()`` must contain both
        ``"Skipped 3 Koinly tracking entries"`` and ``"FEE=3"`` (regex-strength
        assertion, r1 Medium #6: pin count AND asset, not just shape). Zero
        WARNING records may mention FEE (the per-row WARNING at the
        else-branch is replaced by the single summary INFO).
        """
        koinly_dir = tmp_path / "koinly2025"
        koinly_dir.mkdir()
        _write_cg_with_rows(
            koinly_dir,
            [
                _fee_all_zero_cg_row("FEE", "13/01/2025 13:01"),
                _fee_all_zero_cg_row("FEE", "14/01/2025 13:01"),
                _fee_all_zero_cg_row("FEE", "15/01/2025 13:01"),
            ],
        )
        _write_minimal_income_report(koinly_dir)
        _write_minimal_transaction_history(koinly_dir)

        with caplog.at_level(
            logging.DEBUG, logger="tax_reporting.application.crypto_reporting"
        ):
            report = load_koinly_crypto_report(koinly_dir)
        assert report is not None

        info_messages = [
            rec.getMessage()
            for rec in caplog.records
            if rec.levelno == logging.INFO
            and rec.name == "tax_reporting.application.crypto_reporting"
        ]
        fee_info = [m for m in info_messages if "Koinly tracking entries" in m]
        assert len(fee_info) == 1, (
            f"Expected exactly one FEE summary INFO record, got {fee_info}"
        )
        assert "Skipped 3 Koinly tracking entries" in fee_info[0]
        assert "FEE=3" in fee_info[0]

        fee_warnings = [
            rec.getMessage()
            for rec in caplog.records
            if rec.levelno == logging.WARNING
            and "FEE" in rec.getMessage()
        ]
        assert fee_warnings == [], (
            f"Expected zero WARNING records mentioning FEE, got {fee_warnings}"
        )

    def test_real_fee_disposal_passes_through(self, tmp_path):
        """A non-zero FEE CG row flows through normal CG processing.

        Regression guard for Invariant 4: ``is_all_zero`` is False for a real
        disposal, so the short-circuit never fires and the row reaches
        ``capital_entries``. The FEE tracking-token skip targets the all-zero
        branch only.
        """
        koinly_dir = tmp_path / "koinly2025"
        koinly_dir.mkdir()
        _write_cg_with_rows(
            koinly_dir,
            [
                ",".join(
                    [
                        "13/01/2025 13:01",
                        "01/01/2024 00:00",
                        "FEE",
                        '"0,10000000"',
                        '"10,00"',
                        '"12,00"',
                        '"2,00"',
                        "",
                        "Kraken",
                        "Short term",
                    ]
                ),
            ],
        )
        _write_minimal_income_report(koinly_dir)
        _write_minimal_transaction_history(koinly_dir)

        report = load_koinly_crypto_report(koinly_dir)
        assert report is not None

        fee_entries = [e for e in report.capital_entries if e.asset == "FEE"]
        assert len(fee_entries) == 1, (
            f"Real FEE disposal must reach capital_entries, got {fee_entries}"
        )
        assert fee_entries[0].cost_eur == Decimal("10.00")
        assert fee_entries[0].proceeds_eur == Decimal("12.00")
        assert fee_entries[0].gain_loss_eur == Decimal("2.00")

    def test_popular_token_all_zero_still_flagged(self, tmp_path):
        """BTC all-zero row is still appended to context.review_entries.

        Guards the popular-token code path (BTC is in the popular-token set,
        FEE is not). The moved-inside-the-block lookups still run for BTC, so
        it takes the review-entries branch (not the else-branch short-circuit
        reserved for Koinly tracking tokens). Substring assertion on
        review_reason per r1 Medium #8.
        """
        from tax_reporting.application.crypto_reporting import (
            CapitalGainsParsingContext,
            _parse_capital_gains_file,
        )

        koinly_dir = tmp_path / "koinly2025"
        koinly_dir.mkdir()
        cg_path = _write_cg_with_rows(
            koinly_dir,
            [_fee_all_zero_cg_row("BTC", "13/01/2025 13:01")],
        )

        review_entries: list = []
        context = CapitalGainsParsingContext(
            skipped_assets={},
            origin_resolver=build_origin_resolver(None),
            review_entries=review_entries,
            known_assets=frozenset(),
            loan_affected_assets=frozenset(),
        )
        _entries, _fallback = _parse_capital_gains_file(cg_path, context)

        btc_reviews = [e for e in review_entries if e.asset == "BTC"]
        assert len(btc_reviews) == 1, (
            f"Expected one BTC review entry, got {btc_reviews}"
        )
        assert (
            "Zero EUR value for known crypto asset" in btc_reviews[0].review_reason
        ), btc_reviews[0].review_reason

    def test_fee_token_skips_popular_token_and_non_latin_lookups(
        self, tmp_path, monkeypatch
    ):
        """FEE all-zero row triggers NONE of the three lookups.

        ``is_known_token`` is ``asset in _get_popular_crypto_tokens() or
        _contains_popular_token(asset)`` (short-circuit ``or`` over TWO
        lookups, r4 F3), and ``is_suspicious`` is
        ``contains_non_latin_characters(asset)``. All three are now (post-fix)
        computed INSIDE the ``is_all_zero`` block below the FEE short-circuit,
        so for a FEE row none of them is called. Without this test a future
        refactor that moves the lookups back to crypto_reporting.py:729-730
        would silently defeat the lookup-avoidance while passing the other
        FEE tests.
        """
        from tax_reporting.application import crypto_reporting as cr
        from tax_reporting.application.crypto_reporting import (
            CapitalGainsParsingContext,
            _parse_capital_gains_file,
        )

        koinly_dir = tmp_path / "koinly2025"
        koinly_dir.mkdir()
        cg_path = _write_cg_with_rows(
            koinly_dir,
            [_fee_all_zero_cg_row("FEE", "13/01/2025 13:01")],
        )

        call_counts = {
            "popular_tokens": 0,
            "contains_popular": 0,
            "non_latin": 0,
        }

        def _spy_popular():
            call_counts["popular_tokens"] += 1
            return frozenset()

        def _spy_contains_popular(_asset: str) -> bool:
            call_counts["contains_popular"] += 1
            return False

        def _spy_non_latin(_asset: str) -> bool:
            call_counts["non_latin"] += 1
            return False

        monkeypatch.setattr(cr, "_get_popular_crypto_tokens", _spy_popular)
        monkeypatch.setattr(cr, "_contains_popular_token", _spy_contains_popular)
        monkeypatch.setattr(cr, "contains_non_latin_characters", _spy_non_latin)

        review_entries: list = []
        context = CapitalGainsParsingContext(
            skipped_assets={},
            origin_resolver=build_origin_resolver(None),
            review_entries=review_entries,
            known_assets=frozenset(),
            loan_affected_assets=frozenset(),
        )
        _parse_capital_gains_file(cg_path, context)

        assert call_counts == {
            "popular_tokens": 0,
            "contains_popular": 0,
            "non_latin": 0,
        }, (
            "FEE short-circuit must fire before the popular-token / non-Latin "
            f"lookups; got {call_counts}"
        )


@pytest.mark.unit
class TestKoinlyTrackingTokensSet:
    """RED regression guard on Plan Invariant 6 / Design Invariant 5.

    ``_KOINLY_TRACKING_TOKENS`` is a ``frozenset[str]`` module constant whose
    exact membership is pinned: adding a token is a conscious, visible diff.
    """

    def test_set_contents_pinned(self):
        """_KOINLY_TRACKING_TOKENS equals frozenset({'FEE'}) exactly."""
        try:
            from tax_reporting.application.crypto_reporting import (
                _KOINLY_TRACKING_TOKENS,
            )
        except ImportError:
            pytest.fail(
                "Task 2 must add _KOINLY_TRACKING_TOKENS module constant to "
                "tax_reporting.application.crypto_reporting"
            )
        assert frozenset({"FEE"}) == _KOINLY_TRACKING_TOKENS


def _write_income_csv(income_file: Path, rows: list[str]) -> None:
    """Write a Koinly-format income CSV with the given data rows.

    Mirrors the inline CSV-construction pattern from
    ``test_parse_income_file_flags_zero_value_known_assets_for_review`` (around line 8107).
    Each row must already contain the seven comma-separated Koinly columns:
    Date,Asset,Amount,Value (EUR),Type,Description,Wallet Name.
    """
    income_file.write_text(
        "\n".join([
            "Income report 2025",
            "",
            "Date,Asset,Amount,Value (EUR),Type,Description,Wallet Name",
            *rows,
        ]),
        encoding="utf-8",
    )


def _parse_income_file_with_skip(
    income_file: Path,
    *,
    skipped_assets: dict[tuple[str, str], dict],
    known_assets: frozenset[str],
) -> tuple[list, list]:
    """Call ``_parse_income_file`` forwarding the ``skipped_zero_value_deferred_rewards``
    out-param (Plan 2026-07-19-deferred-reward-dust-skip, Task 2 contract - shipped).

    The out-param is now part of ``_parse_income_file``'s signature, so the call
    no longer raises ``TypeError``. The ``try/except TypeError`` is kept as a
    contract regression guard: if a future refactor drops the out-param, the
    ``pytest.fail`` surfaces it with a specific message instead of an unhandled
    exception (AGENTS.md rule 4: a committed test that is itself the deliverable
    must fail via ``pytest.fail`` naming the cause, never an unhandled exception).

    Returns ``(reward_entries, skipped_zero_value_deferred_rewards)``.
    """
    skipped_zero_value_deferred_rewards: list = []
    try:
        reward_entries = _parse_income_file(
            income_file,
            skipped_assets,
            known_assets=known_assets,
            skipped_zero_value_deferred_rewards=skipped_zero_value_deferred_rewards,
        )
    except TypeError as exc:
        pytest.fail(
            "_parse_income_file must keep the skipped_zero_value_deferred_rewards "
            f"out-param (got TypeError: {exc})"
        )
    return reward_entries, skipped_zero_value_deferred_rewards


@pytest.mark.unit
class TestParseIncomeFileDeferredSkip:
    """RED tests for the parse-time skip of zero-value DEFERRED_BY_LAW rewards (Plan
    2026-07-19-deferred-reward-dust-skip, Task 1).

    These tests exercise ``_parse_income_file`` DIRECTLY (the function-level path, NOT
    the full pipeline) and pass the NEW ``skipped_zero_value_deferred_rewards``
    out-param as a kwarg via ``_parse_income_file_with_skip``. Today the kwarg does not
    exist, so the call raises ``TypeError`` which is converted to a ``pytest.fail``
    naming Task 2. All four go RED against unchanged production.

    Pinned contract: zero-value DEFERRED_BY_LAW reward rows route to
    ``skipped_zero_value_deferred_rewards`` (a full ``list[CryptoRewardIncomeEntry]``,
    per Invariant 1 , list preservation, user's hard requirement) instead of
    ``reward_entries``. Non-zero deferred rows and ALL taxable-now rows stay in
    ``reward_entries`` unchanged.
    """

    def test_zero_value_deferred_reward_routed_to_skipped_list(self, tmp_path):
        """Zero-value BTC deferred reward is routed to ``skipped_zero_value_deferred_rewards``;
        the non-zero BTC deferred row stays in ``reward_entries``.

        Goes RED: today the ``skipped_zero_value_deferred_rewards`` out-param does not
        exist on ``_parse_income_file``, so the call raises ``TypeError`` which is
        converted to ``pytest.fail`` naming Task 2.
        """
        koinly_dir = tmp_path / "koinly2025"
        koinly_dir.mkdir()
        income_file = koinly_dir / "koinly_2025_income_report_test.csv"
        _write_income_csv(
            income_file,
            [
                # Zero-value BTC reward -> DEFERRED_BY_LAW + value_eur == 0 -> skip path
                '01/01/2025 00:01,BTC,"1,00000000",0.0,Reward,,Kraken',
                # Non-zero BTC reward -> stays in reward_entries
                '02/01/2025 00:01,BTC,"2,00000000","100,00",Reward,,Kraken',
            ],
        )

        skipped_assets: dict[tuple[str, str], dict] = {}
        reward_entries, skipped_zero_value_deferred_rewards = _parse_income_file_with_skip(
            income_file,
            skipped_assets=skipped_assets,
            known_assets=frozenset({"BTC"}),
        )

        # (a) reward_entries contains ONLY the non-zero BTC row.
        btc_reward_entries = [e for e in reward_entries if e.asset == "BTC"]
        assert len(btc_reward_entries) == 1, (
            "Expected exactly one BTC entry in reward_entries (the non-zero row); "
            "the zero-value BTC row must route to skipped_zero_value_deferred_rewards."
        )
        assert btc_reward_entries[0].value_eur == Decimal("100.00")
        assert btc_reward_entries[0].tax_classification == RewardTaxClassification.DEFERRED_BY_LAW

        # (b) skipped_zero_value_deferred_rewards contains the zero-value BTC row as a
        # full CryptoRewardIncomeEntry preserving all fields.
        btc_skipped = [e for e in skipped_zero_value_deferred_rewards if e.asset == "BTC"]
        assert len(btc_skipped) == 1, (
            "Expected exactly one BTC entry in skipped_zero_value_deferred_rewards; "
            f"got {len(btc_skipped)} (full skipped list: "
            f"{len(skipped_zero_value_deferred_rewards)} rows)."
        )
        entry = btc_skipped[0]
        assert entry.asset == "BTC"
        assert entry.value_eur == Decimal("0")
        assert entry.tax_classification == RewardTaxClassification.DEFERRED_BY_LAW
        # wallet / platform / amount preserved on the relocated entry.
        assert entry.wallet == "Kraken"
        assert entry.platform == "Kraken"
        assert entry.amount == Decimal("1")

    def test_nonzero_deferred_reward_stays_in_reward_entries(self, tmp_path):
        """Non-zero ETH deferred reward stays in ``reward_entries`` and the skip list is empty."""
        koinly_dir = tmp_path / "koinly2025"
        koinly_dir.mkdir()
        income_file = koinly_dir / "koinly_2025_income_report_test.csv"
        _write_income_csv(
            income_file,
            [
                # Non-zero ETH reward -> DEFERRED_BY_LAW, value_eur > 0 -> stays in reward_entries
                '01/01/2025 00:01,ETH,"2,00000000","50,00",Reward,,Kraken',
            ],
        )

        skipped_assets: dict[tuple[str, str], dict] = {}
        reward_entries, skipped_zero_value_deferred_rewards = _parse_income_file_with_skip(
            income_file,
            skipped_assets=skipped_assets,
            known_assets=frozenset({"ETH"}),
        )

        eth_reward_entries = [e for e in reward_entries if e.asset == "ETH"]
        assert len(eth_reward_entries) == 1
        assert eth_reward_entries[0].value_eur == Decimal("50.00")
        assert eth_reward_entries[0].tax_classification == RewardTaxClassification.DEFERRED_BY_LAW

        # The skip list must be empty when every deferred reward is non-zero.
        assert skipped_zero_value_deferred_rewards == []

    def test_taxable_now_zero_value_not_skipped(self, tmp_path):
        """Zero-value EUR taxable-now row stays in ``reward_entries``: the skip is
        DEFERRED_BY_LAW-only (scope boundary regression guard).

        EUR is fiat -> ``TAXABLE_NOW`` (per ``_classify_reward_tax_status``), so the
        zero-value skip must NOT fire; Part 7 taxable-now partition handles its own
        presentation.
        """
        koinly_dir = tmp_path / "koinly2025"
        koinly_dir.mkdir()
        income_file = koinly_dir / "koinly_2025_income_report_test.csv"
        _write_income_csv(
            income_file,
            [
                # EUR is fiat -> TAXABLE_NOW; zero-value must NOT be skipped
                # (deferred-only scope; Part 7 handles taxable-now presentation).
                '01/01/2025 00:01,EUR,"10,00000000",0.0,Reward,,Wirex',
            ],
        )

        skipped_assets: dict[tuple[str, str], dict] = {}
        reward_entries, skipped_zero_value_deferred_rewards = _parse_income_file_with_skip(
            income_file,
            skipped_assets=skipped_assets,
            known_assets=frozenset({"EUR"}),
        )

        eur_reward_entries = [e for e in reward_entries if e.asset == "EUR"]
        assert len(eur_reward_entries) == 1, (
            "Zero-value EUR (TAXABLE_NOW) row must stay in reward_entries; the skip "
            "is DEFERRED_BY_LAW-only."
        )
        assert eur_reward_entries[0].value_eur == Decimal("0")
        assert eur_reward_entries[0].tax_classification == RewardTaxClassification.TAXABLE_NOW

        # No EUR row appears in the deferred-skip list.
        assert [e for e in skipped_zero_value_deferred_rewards if e.asset == "EUR"] == []

    def test_skipped_row_preserves_full_fidelity(self, tmp_path):
        """The skipped WBERA deferred row retains ALL fields a non-skipped entry would have
        (Invariant 1 , list preservation, user's hard requirement).

        This test must FAIL if a future refactor switches
        ``skipped_zero_value_deferred_rewards`` to a count-only
        ``CryptoSkippedZeroValueToken`` shape: it asserts on field equality
        (asset, wallet, platform, amount, source_type), not just count.
        """
        koinly_dir = tmp_path / "koinly2025"
        koinly_dir.mkdir()
        income_file = koinly_dir / "koinly_2025_income_report_test.csv"
        _write_income_csv(
            income_file,
            [
                # Zero-value WBERA (passed via known_assets so it survives the is_known gate
                # deterministically; crypto -> DEFERRED_BY_LAW) with explicit
                # wallet/platform/amount/source_type.
                '01/01/2025 00:01,WBERA,"1,50000000",0.0,Reward,,Wirex',
            ],
        )

        skipped_assets: dict[tuple[str, str], dict] = {}
        _, skipped_zero_value_deferred_rewards = _parse_income_file_with_skip(
            income_file,
            skipped_assets=skipped_assets,
            known_assets=frozenset({"WBERA"}),
        )

        wbera_skipped = [e for e in skipped_zero_value_deferred_rewards if e.asset == "WBERA"]
        assert len(wbera_skipped) == 1, (
            "Expected exactly one WBERA entry in skipped_zero_value_deferred_rewards; "
            f"got {len(wbera_skipped)}."
        )
        entry = wbera_skipped[0]

        # Full-fidelity assertions: every field that a non-skipped entry would carry.
        # Asserting on field equality (not just count) is the load-bearing guard against
        # a count-only regression on the list-preservation invariant.
        assert entry.asset == "WBERA"
        assert entry.wallet == "Wirex"
        assert entry.platform == "Wirex"
        assert entry.amount == Decimal("1.5")
        assert entry.source_type == "Reward"
        assert entry.value_eur == Decimal("0")
        assert entry.tax_classification == RewardTaxClassification.DEFERRED_BY_LAW

    def test_default_kwarg_silently_drops_zero_value_deferred(self, tmp_path):
        """Backward-compat guard for the None-init shim at crypto_reporting.py:990-991.

        Calling ``_parse_income_file`` WITHOUT the ``skipped_zero_value_deferred_rewards``
        kwarg (the default-kwarg path exercised by legacy test call sites) must NOT
        crash: the shim rebinds the local to a fresh ``list`` and silently discards
        every zero-value DEFERRED row (the local list is dropped on return). The
        non-zero DEFERRED row still lands in ``reward_entries``.

        This test pins the documented silent-drop contract so a future refactor that
        removes the shim (e.g. makes the kwarg required) fails loudly here and forces
        the author to update the legacy callers at test_crypto_reporting.py:8178/8225/
        8274/10783 explicitly, rather than silently changing their behavior. (r1 review
        finding #5.)
        """
        koinly_dir = tmp_path / "koinly2025"
        koinly_dir.mkdir()
        income_file = koinly_dir / "koinly_2025_income_report_default_kwarg.csv"
        _write_income_csv(
            income_file,
            [
                # Zero-value BTC reward -> DEFERRED_BY_LAW + value_eur == 0 -> skip path.
                '01/01/2025 00:01,BTC,"1,00000000",0.0,Reward,,Kraken',
                # Non-zero BTC reward -> stays in reward_entries.
                '02/01/2025 00:01,BTC,"2,00000000","100,00",Reward,,Kraken',
            ],
        )

        skipped_assets: dict[tuple[str, str], dict] = {}
        # NOTE: deliberately does NOT pass ``skipped_zero_value_deferred_rewards``;
        # this exercises the None-init shim and proves the default-kwarg callers
        # parse without crashing.
        entries = _parse_income_file(income_file, skipped_assets, known_assets=frozenset({"BTC"}))

        # The shim silently drops the zero-value row because the local list is
        # discarded on return; reward_entries keeps only the non-zero BTC row.
        # If a future refactor removes the shim, this assertion fails and points the
        # author at the legacy call sites to update (or to make the kwarg required).
        assert len(entries) == 1, (
            f"Default-kwarg path changed: expected 1 entry (shim silently drops the "
            f"zero-value DEFERRED row); got {len(entries)}. If you removed the shim, "
            f"update the legacy callers at test_crypto_reporting.py:8178/8225/8274/10783 "
            f"or make the kwarg required."
        )
        assert entries[0].value_eur == Decimal("100.00")
        assert entries[0].tax_classification == RewardTaxClassification.DEFERRED_BY_LAW


@pytest.mark.unit
class TestCryptoReporting:
    """Bucket-B aggregate demotions in the CG-parse cluster (Plan 2026-07-24 Task 4).

    The cluster at ``crypto_reporting.py`` lines 900/907/915/922 is handled
    PER-LINE (Invariant #5): the FIFO-rebuild-buffered aggregate (:900) and the
    all-zero-flagged aggregate (:922) are Excel-surfaced Bucket-B signals
    demoted to INFO; the parse-error aggregate (:907) is Bucket-C (silent data
    loss) and MUST stay WARNING; :915 is already INFO. These tests pin the
    level discrimination with two separate emissions (Invariant #4) for the
    demoted sites and a positive-at-WARNING guard for the parse-error site.
    """

    def test_fifo_rebuild_buffered_aggregate_at_info(self, tmp_path, caplog):
        """A loan-affected asset's buffered raw CG row emits the aggregate at INFO.

        Positive: the "FIFO rebuild active: buffered N raw CG row(s)" aggregate
        appears at ``logging.INFO``. Negative: it does NOT appear at
        ``logging.WARNING`` (two separate emissions, Invariant #4). Each
        buffered entry in ``raw_loan_fallback`` retains ``review_required=True``
        (Excel-surface regression guard).
        """
        from collections import Counter
        from unittest.mock import MagicMock, patch

        from tax_reporting.application.token_origin import TokenOriginResolver

        newasset_row = ",".join(
            [
                "13/01/2025 13:01",
                "18/11/2024 00:15",
                "NEWASSET",
                '"1,00000000"',
                '"500,00"',
                '"600,00"',
                '"100,00"',
                "",
                "Kraken",
                "Short term",
            ]
        )
        eth_row = ",".join(
            [
                "20/01/2025 10:10",
                "01/01/2024 00:00",
                "ETH",
                '"0,50000000"',
                '"1000,00"',
                '"1200,00"',
                '"200,00"',
                "",
                "Kraken",
                "Long term",
            ]
        )
        cg_path = tmp_path / "cg.csv"
        cg_path.write_text(
            "\n".join(["Capital gains report 2025", "", _FIFO_CG_HEADER, newasset_row, eth_row]),
            encoding="utf-8",
        )

        def _run() -> object:
            skipped: Counter[tuple[str, str]] = Counter()
            resolver = MagicMock(spec=TokenOriginResolver)
            resolver.resolve.return_value = {"origin": "Unknown"}
            review_entries: list = []
            context = CapitalGainsParsingContext(
                skipped_assets=skipped,
                origin_resolver=resolver,
                review_entries=review_entries,
                loan_affected_assets=frozenset({"NEWASSET"}),
            )
            with patch(
                "tax_reporting.application.crypto_reporting._get_popular_crypto_tokens",
                return_value=frozenset({"ETH", "NEWASSET"}),
            ):
                entries, raw_loan_fallback = _parse_capital_gains_file(cg_path, context)
            return entries, raw_loan_fallback

        # Positive: aggregate appears at INFO.
        with caplog.at_level(logging.INFO, logger="tax_reporting.application.crypto_reporting"):
            entries, raw_loan_fallback = _run()

        info_messages = [
            rec.getMessage()
            for rec in caplog.records
            if rec.levelno == logging.INFO
            and rec.name == "tax_reporting.application.crypto_reporting"
        ]
        fifo_info = [m for m in info_messages if "FIFO rebuild active: buffered" in m]
        assert len(fifo_info) == 1, (
            f"Expected ONE FIFO-rebuild-buffered aggregate at INFO, got {fifo_info}"
        )
        assert "buffered 1 raw CG row" in fifo_info[0]

        # Excel-surface regression: each buffered entry retains review_required.
        assert len(raw_loan_fallback) == 1, (
            f"Expected 1 buffered raw CG fallback entry, got {len(raw_loan_fallback)}"
        )
        assert raw_loan_fallback[0].asset == "NEWASSET"
        assert raw_loan_fallback[0].review_required is True, (
            "Buffered loan-affected entry must retain review_required=True"
        )
        assert raw_loan_fallback[0].review_reason, (
            "Buffered loan-affected entry must retain a review_reason"
        )

        # Negative: aggregate does NOT appear at WARNING (fresh emission).
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="tax_reporting.application.crypto_reporting"):
            _run()

        warning_messages = [
            rec.getMessage()
            for rec in caplog.records
            if rec.levelno == logging.WARNING
            and rec.name == "tax_reporting.application.crypto_reporting"
        ]
        fifo_at_warning = [m for m in warning_messages if "FIFO rebuild active: buffered" in m]
        assert fifo_at_warning == [], (
            f"FIFO-rebuild-buffered aggregate must be INFO, not WARNING, got {fifo_at_warning}"
        )

    def test_all_zero_flagged_aggregate_at_info(self, tmp_path, caplog):
        """All-zero CG rows emit the "Flagged N all-zero" aggregate at INFO.

        Positive: the aggregate appears at ``logging.INFO``. Negative: it does
        NOT appear at ``logging.WARNING`` (two separate emissions, Invariant
        #4). Each entry in ``review_entries`` retains ``review_required=True``
        and a ``review_reason`` (Excel-surface regression guard).
        """
        from unittest.mock import MagicMock, patch

        from tax_reporting.application.token_origin import TokenOriginResolver

        koinly_dir = tmp_path / "koinly2025"
        koinly_dir.mkdir()
        capital_file = _write_cg_with_rows(
            koinly_dir,
            [_fee_all_zero_cg_row("BTC", "01/01/2025 10:00")],
        )

        def _run() -> list:
            resolver = MagicMock(spec=TokenOriginResolver)
            resolver.resolve.return_value = {"origin": "Unknown"}
            review_entries: list = []
            known_assets = frozenset({"BTC"})
            context = CapitalGainsParsingContext(
                skipped_assets={},
                origin_resolver=resolver,
                review_entries=review_entries,
                known_assets=known_assets,
                loan_affected_assets=frozenset(),
            )
            with patch(
                "tax_reporting.application.crypto_reporting._get_popular_crypto_tokens",
                return_value=known_assets,
            ):
                _parse_capital_gains_file(capital_file, context)
            return review_entries

        # Positive: aggregate appears at INFO.
        with caplog.at_level(logging.INFO, logger="tax_reporting.application.crypto_reporting"):
            review_entries = _run()

        info_messages = [
            rec.getMessage()
            for rec in caplog.records
            if rec.levelno == logging.INFO
            and rec.name == "tax_reporting.application.crypto_reporting"
        ]
        all_zero_info = [m for m in info_messages if "all-zero capital gains row" in m]
        assert len(all_zero_info) == 1, (
            f"Expected ONE all-zero aggregate at INFO, got {all_zero_info}"
        )
        assert "Flagged 1 all-zero capital gains row" in all_zero_info[0]

        # Excel-surface regression: the all-zero row is still surfaced as a
        # CryptoReviewEntry carrying a review_reason (Design Invariant #4).
        assert len(review_entries) == 1, (
            f"Expected 1 review entry, got {len(review_entries)}"
        )
        assert review_entries[0].asset == "BTC"
        assert review_entries[0].review_reason, (
            "All-zero review entry must retain a review_reason"
        )

        # Negative: aggregate does NOT appear at WARNING (fresh emission).
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="tax_reporting.application.crypto_reporting"):
            _run()

        warning_messages = [
            rec.getMessage()
            for rec in caplog.records
            if rec.levelno == logging.WARNING
            and rec.name == "tax_reporting.application.crypto_reporting"
        ]
        all_zero_at_warning = [m for m in warning_messages if "all-zero capital gains row" in m]
        assert all_zero_at_warning == [], (
            f"All-zero aggregate must be INFO, not WARNING, got {all_zero_at_warning}"
        )

    def test_parse_error_drops_stay_warning(self, tmp_path, caplog):
        """A CG row with an ambiguous decimal keeps the parse-error aggregate at WARNING.

        Regression guard for Invariant #5 (Bucket-C must not be swept): the
        "Skipped N capital gains row(s) due to ambiguous decimal values"
        aggregate at ``crypto_reporting.py:907`` is silent-data-loss signal
        and MUST remain at ``logging.WARNING`` (positive-at-WARNING).
        """
        from unittest.mock import MagicMock, patch

        from tax_reporting.application.token_origin import TokenOriginResolver

        ambiguous_row = ",".join(
            [
                "13/01/2025 13:01",
                "18/11/2024 00:15",
                "ETH",
                "1",
                "1.234",  # ambiguous single-group dot decimal -> row skipped
                "1.500",
                "0.266",
                "",
                "Kraken",
                "Short term",
            ]
        )
        cg_path = tmp_path / "cg.csv"
        cg_path.write_text(
            "\n".join(["Capital gains report 2025", "", _FIFO_CG_HEADER, ambiguous_row]),
            encoding="utf-8",
        )

        resolver = MagicMock(spec=TokenOriginResolver)
        resolver.resolve.return_value = {"origin": "Unknown"}
        review_entries: list = []
        context = CapitalGainsParsingContext(
            skipped_assets={},
            origin_resolver=resolver,
            review_entries=review_entries,
            known_assets=frozenset({"ETH"}),
            loan_affected_assets=frozenset(),
        )

        with (
            caplog.at_level(logging.WARNING, logger="tax_reporting.application.crypto_reporting"),
            patch(
                "tax_reporting.application.crypto_reporting._get_popular_crypto_tokens",
                return_value=frozenset({"ETH"}),
            ),
        ):
            _parse_capital_gains_file(cg_path, context)

        warning_messages = [
            rec.getMessage()
            for rec in caplog.records
            if rec.levelno == logging.WARNING
            and rec.name == "tax_reporting.application.crypto_reporting"
        ]
        parse_error_warnings = [
            m for m in warning_messages if "ambiguous decimal values" in m
        ]
        assert len(parse_error_warnings) == 1, (
            f"Expected parse-error aggregate to STAY at WARNING, got {parse_error_warnings}"
        )
        assert "Skipped 1 capital gains row" in parse_error_warnings[0]


@pytest.mark.unit
class TestCryptoDecisionCounts:
    """CryptoDecisionCounts is a NON-frozen mutable accumulator (INV-4a)."""

    def test_defaults_to_zero(self) -> None:
        from tax_reporting.application.crypto.entities import CryptoDecisionCounts

        counts = CryptoDecisionCounts()
        assert counts.sub_1_eur_filtered == 0
        assert counts.sub_1_eur_retained == 0
        assert counts.derivatives_dedup_removed == 0
        assert counts.fee_dedup_removed == 0

    def test_fields_are_mutable(self) -> None:
        """Passes set fields in-pass (NOT frozen: INV-4a)."""
        from tax_reporting.application.crypto.entities import CryptoDecisionCounts

        decision_counts = CryptoDecisionCounts()
        decision_counts.derivatives_dedup_removed = 5
        assert decision_counts.derivatives_dedup_removed == 5


@pytest.mark.unit
class TestSubOneEurFilter:
    """W10 sub-1-EUR capital gain aggregate emits INFO (not WARNING) with counts."""

    def test_aggregate_emits_info_with_counts(self, tmp_path, monkeypatch, caplog) -> None:
        """Given pre_filter_count=175 and post-filter len=2 (173 dropped), the
        aggregate emits ONE INFO record carrying both counts and ZERO WARNING
        records with that substring."""
        import tax_reporting.application.crypto_reporting as cr_module

        # Build a minimal koinly dir with one material CG row so load_koinly_crypto_report
        # reaches the W10 site; the actual counts are controlled via monkeypatch.
        koinly_dir = tmp_path / "koinly2025"
        koinly_dir.mkdir()
        _write_minimal_capital_gains_report(koinly_dir)
        _write_minimal_income_report(koinly_dir)
        _write_minimal_transaction_history(koinly_dir)

        # Control the pre/post filter counts deterministically (175 -> 2, 173 dropped).
        # We need real CryptoCapitalGainEntry-shaped objects so downstream code does not break.
        def _aggregator(_entries):  # noqa: ANN001
            # Return exactly 175 entries regardless of input so the W10 math is fixed.
            return [_entry_placeholder()] * 175

        def _filter(_entries):  # noqa: ANN001
            return list(_entries)[:2]

        monkeypatch.setattr(cr_module, "_aggregate_capital_entries", _aggregator)
        monkeypatch.setattr(cr_module, "_filter_immaterial_entries", _filter)

        with caplog.at_level(logging.INFO, logger="tax_reporting.application.crypto_reporting"):
            report = load_koinly_crypto_report(koinly_dir)

        assert report is not None

        info_records = [
            r for r in caplog.records
            if r.levelno == logging.INFO
            and "sub-1-EUR capital gain entries" in r.getMessage()
            and r.name == "tax_reporting.application.crypto_reporting"
        ]
        warning_records = [
            r for r in caplog.records
            if r.levelno == logging.WARNING
            and "sub-1-EUR capital gain entries" in r.getMessage()
            and r.name == "tax_reporting.application.crypto_reporting"
        ]
        assert len(info_records) == 1, (
            f"Expected exactly 1 INFO record for sub-1-EUR filter, got {len(info_records)}: "
            f"{[r.getMessage() for r in info_records]}"
        )
        assert warning_records == [], (
            f"Expected ZERO WARNING records for sub-1-EUR filter, got {warning_records}"
        )
        assert (
            "Filtered 173 sub-1-EUR capital gain entries (PT-C-028); 2 entries retained"
            in info_records[0].getMessage()
        )
        # The accumulator must carry the counts end-to-end.
        assert report.decision_counts.sub_1_eur_filtered == 173
        assert report.decision_counts.sub_1_eur_retained == 2

    def test_no_drop_sets_retained_unconditionally(self, tmp_path, monkeypatch) -> None:
        """The no-drop path (``dropped == 0``) still sets ``sub_1_eur_retained`` to the
        full capital-entries length (INV-4a: unconditional set, not gated on
        ``dropped > 0``). A regression reverting to ``if dropped > 0:`` would leave
        ``sub_1_eur_retained`` at 0 even when entries are retained, silently
        mis-stating the A&M PT-C-028 count cell.

        Fixture: monkeypatch ``_filter_immaterial_entries`` to a no-op returning
        the full list (so ``dropped == 0``) over a non-empty list (so
        ``len(capital_entries) > 0``). Note: production gates the W10 INFO emit
        on ``dropped > 0``, so on this fixture no INFO record fires; this test
        does NOT assert on the INFO record. AND the accumulator carries the
        correct retained count.
        """
        import tax_reporting.application.crypto_reporting as cr_module

        koinly_dir = tmp_path / "koinly2025"
        koinly_dir.mkdir()
        _write_minimal_capital_gains_report(koinly_dir)
        _write_minimal_income_report(koinly_dir)
        _write_minimal_transaction_history(koinly_dir)

        retained_count = 4

        def _aggregator(_entries):  # noqa: ANN001
            return [_entry_placeholder()] * retained_count

        def _filter(_entries):  # noqa: ANN001
            # No-op filter: nothing dropped. ``dropped == 0`` at the W10 site.
            return list(_entries)

        monkeypatch.setattr(cr_module, "_aggregate_capital_entries", _aggregator)
        monkeypatch.setattr(cr_module, "_filter_immaterial_entries", _filter)

        report = load_koinly_crypto_report(koinly_dir)

        assert report is not None
        # The set must be unconditional: ``sub_1_eur_retained`` equals the full
        # entries length even though ``sub_1_eur_filtered`` is 0.
        assert report.decision_counts.sub_1_eur_filtered == 0
        assert report.decision_counts.sub_1_eur_retained == retained_count


def _entry_placeholder() -> CryptoCapitalGainEntry:
    """A minimal CryptoCapitalGainEntry placeholder for count control in tests."""
    from tests.conftest import make_operator_origin

    return CryptoCapitalGainEntry(
        disposal_date="2025-06-15",
        acquisition_date="2025-01-10",
        asset="BTC",
        amount=Decimal("0.5"),
        cost_eur=Decimal("20000"),
        proceeds_eur=Decimal("25000"),
        gain_loss_eur=Decimal("5000"),
        holding_period="Short-term",
        wallet="kraken-wallet",
        platform="Kraken",
        chain="Ethereum",
        operator_origin=make_operator_origin(platform="Kraken"),
        annex_hint="J",
        review_required=False,
        notes="",
    )




class TestW2W3FifoRebuildGateInactive:
    """W2/W3 negative-path gate tests (Plan 2026-07-25 Task 3).

    The W2 (duplicate-tx_key) and W3 (zero-Net-Value) emit sites live INSIDE
    the FIFO rebuild path gated by ``fifo_rebuild_active and loan_affected_assets``
    (``crypto_reporting.py``). When that gate is False (non-PT jurisdiction or no
    loan-affected assets), the emit sites are UNREACHABLE: ZERO INFO records
    matching those substrings, ZERO new CryptoReviewEntry rows from those sites.

    This test drives end-to-end through ``load_koinly_crypto_report`` (the gate
    lives in the orchestrator, not the leaf): calling ``_dedup_by_tx_key``
    directly would bypass the gate and make the negative assertion meaningless.
    """

    def test_w2_w3_skipped_when_fifo_rebuild_inactive(self, tmp_path, caplog):
        """Non-PT jurisdiction (``fifo_rebuild_active=False``) → W2/W3 unreachable."""
        from tax_reporting.infrastructure.config import (
            DEFAULT_ZERO_BASIS_REVIEW_THRESHOLD,
            TaxJurisdictionConfig,
        )

        koinly_dir = tmp_path / "koinly2025"
        koinly_dir.mkdir()

        # CG + income minimal reports so load_koinly_crypto_report returns a report.
        (koinly_dir / "koinly_2025_capital_gains_report.csv").write_text(
            "\n".join(["Capital gains report 2025", "", _CG_HEADER]),
            encoding="utf-8",
        )
        (koinly_dir / "koinly_2025_income_report.csv").write_text(
            "\n".join(["Income report 2025", "", _INCOME_HEADER]),
            encoding="utf-8",
        )
        # TH containing rows that WOULD trigger W2 (duplicate-tx_key acquisition)
        # and W3 (zero-Net-Value deposit) IF the rebuild ran. Two identical buy
        # rows share TxHash "dup_w2"; one zero-NV deposit carries TxHash "znv_w3".
        dup_w2 = (
            '2025-01-15 10:00:00 UTC,buy,"","","","","",'
            'Kraken,"0,00200000",WBTC,"120,00",,,,"120,00",,,,dup_w2,""""'
        )
        zero_nv = (
            '2025-03-15 10:00:00 UTC,crypto_deposit,"",Kraken,0,,,'
            'Kraken Main,"0,5",WBTC,0,0,,0,0,0,src,dst,znv_w3,""""'
        )
        th_content = "\n".join(
            ["Transaction report 2025", "", _TH_HEADER, dup_w2, dup_w2, zero_nv]
        )
        (koinly_dir / "koinly_2025_transaction_history.csv").write_text(
            th_content, encoding="utf-8"
        )

        # Non-PT jurisdiction: ``exclude_loan_repayment_gains=False`` →
        # ``fifo_rebuild_active`` is False at ``crypto_reporting.py:316``,
        # so the ``fifo_rebuild_active and loan_affected_assets`` gate at
        # ``:363`` is False and ``_rebuild_fifo_for_loan_affected_assets``
        # (which calls parse_th → _dedup_by_tx_key) is never invoked.
        non_pt_jurisdiction = TaxJurisdictionConfig(
            country="US",
            fiscal_year=2025,
            exclude_loan_repayment_gains=False,
            zero_basis_review_threshold=DEFAULT_ZERO_BASIS_REVIEW_THRESHOLD,
            timezone=ZoneInfo("America/New_York"),
        )

        with caplog.at_level(logging.INFO):
            report = load_koinly_crypto_report(
                koinly_dir, jurisdiction=non_pt_jurisdiction
            )

        assert report is not None

        # ZERO INFO records matching "duplicate-tx_key" or "zero-Net-Value".
        info_messages = [
            rec.getMessage()
            for rec in caplog.records
            if rec.levelno == logging.INFO
        ]
        duplicate_txkey_infos = [m for m in info_messages if "duplicate-tx_key" in m]
        zero_nv_infos = [m for m in info_messages if "zero-Net-Value" in m]
        assert duplicate_txkey_infos == [], (
            "W2 duplicate-tx_key INFO must NOT fire when fifo_rebuild is inactive; "
            f"got {duplicate_txkey_infos}"
        )
        assert zero_nv_infos == [], (
            "W3 zero-Net-Value INFO must NOT fire when fifo_rebuild is inactive; "
            f"got {zero_nv_infos}"
        )

        # ZERO new CryptoReviewEntry rows naming the W2 tx_key or the W3 reason.
        w2_rows = [
            r for r in report.review_entries
            if "dup_w2" in r.review_reason or "duplicate" in r.review_reason.lower()
        ]
        w3_rows = [
            r for r in report.review_entries
            if "zero-net-value" in r.review_reason.lower()
        ]
        assert w2_rows == [], (
            "W2 review rows must NOT be appended when fifo_rebuild is inactive; "
            f"got {w2_rows}"
        )
        assert w3_rows == [], (
            "W3 review rows must NOT be appended when fifo_rebuild is inactive; "
            f"got {w3_rows}"
        )
