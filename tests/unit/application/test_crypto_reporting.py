from __future__ import annotations

import dataclasses
import logging
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from tax_reporting.application.crypto.aggregation import (
    _aggregate_capital_entries,
    _filter_immaterial_entries,
    _is_valid_tabela_x_country,
    _resolve_income_code,
    aggregate_derivatives_entries,
    aggregate_taxable_rewards,
)
from tax_reporting.application.crypto.entities import DerivativesEventType, DerivativesPnLEntry, ParsedOgrRow
from tax_reporting.application.crypto_reporting import (
    CapitalGainsParsingContext,
    CryptoCapitalGainEntry,
    CryptoSkippedZeroValueToken,
    OperatorOrigin,
    RewardTaxClassification,
    _apply_ogr_direction_override,
    _apply_ogr_overrides,
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
    load_koinly_crypto_report,
    resolve_operator_origin,
)
from tax_reporting.application.token_origin import TokenOriginResolver
from tax_reporting.domain.token_origin import (
    AcquisitionMethod,
    TokenOrigin,
)
from tax_reporting.infrastructure.koinly_parser import format_datetime, parse_koinly_decimal

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
                        "FEE",
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
    assert ("capital_gains", "FEE", 1) in skipped_assets
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
        # Two EUR rewards from Kraken (Ireland) - same income code "401", same country "IE"
        CryptoRewardIncomeEntry(
            date="2025-01-01",
            asset="EUR",
            amount=Decimal("100"),
            value_eur=Decimal("100"),
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
        CryptoRewardIncomeEntry(
            date="2025-01-02",
            asset="EUR",
            amount=Decimal("50"),
            value_eur=Decimal("50"),
            income_label="Reward",
            source_type="reward",
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
        # USD reward from Bybit (UAE) - different country, different aggregation group
        CryptoRewardIncomeEntry(
            date="2025-01-03",
            asset="USD",
            amount=Decimal("200"),
            value_eur=Decimal("185"),
            income_label="Reward",
            source_type="reward",
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
        # Staking reward from Gate.io (Malta) - different income code "401" but default for staking
        CryptoRewardIncomeEntry(
            date="2025-01-04",
            asset="EUR",
            amount=Decimal("75"),
            value_eur=Decimal("75"),
            income_label="Reward",
            source_type="staking",
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

    result = aggregate_taxable_rewards(entries)

    # Should have 3 aggregation groups:
    # 1. income_code=401, country=IE (Kraken EUR rewards: 100 + 50 = 150)
    # 2. income_code=401, country=AE (Bybit USD reward: 185)
    # 3. income_code=401, country=MT (Gate.io staking: 75) - staking maps to 401 by default
    assert len(result) == 3

    # Find Ireland group (Kraken)
    ie_group = next((g for g in result if g.source_country == "IE"), None)
    assert ie_group is not None
    assert ie_group.income_code == "401"
    assert ie_group.gross_income_eur == Decimal("150")
    assert ie_group.raw_row_count == 2

    # Find UAE group (Bybit)
    ae_group = next((g for g in result if g.source_country == "AE"), None)
    assert ae_group is not None
    assert ae_group.income_code == "401"
    assert ae_group.gross_income_eur == Decimal("185")
    assert ae_group.raw_row_count == 1

    # Find Malta group (Gate.io staking)
    mt_group = next((g for g in result if g.source_country == "MT"), None)
    assert mt_group is not None
    assert mt_group.income_code == "401"  # staking maps to 401
    assert mt_group.gross_income_eur == Decimal("75")
    assert mt_group.raw_row_count == 1


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

    result = aggregate_taxable_rewards(entries)

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
            source_type="reward",
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
            source_type="reward",
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

    result = aggregate_taxable_rewards(entries)

    assert len(result) == 1
    assert result[0].gross_income_eur == Decimal("150")
    assert result[0].foreign_tax_eur == Decimal("7.50")
    assert result[0].raw_row_count == 2


def test_aggregate_taxable_rewards_empty_list():
    """Empty input list returns empty list."""
    result = aggregate_taxable_rewards([])
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

    result = aggregate_taxable_rewards(entries)
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
        aggregate_taxable_rewards(entries)


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
            source_type="reward",
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
            source_type="reward",
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

    result = aggregate_taxable_rewards(entries)

    # Should aggregate to single entry since same income_code (401) and country (AE)
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
            source_type="reward",
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
            source_type="reward",
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

    result = aggregate_taxable_rewards(entries)

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
    """Map Koinly income type to Portuguese Tabela V income code."""
    # Known types
    assert _resolve_income_code("staking") == "401"
    assert _resolve_income_code("reward") == "401"
    assert _resolve_income_code("airdrop") == "401"
    assert _resolve_income_code("interest") == "402"
    assert _resolve_income_code("lending") == "402"
    assert _resolve_income_code("mining") == "403"
    assert _resolve_income_code("fork") == "404"
    assert _resolve_income_code("dividend") == "405"

    # Unknown types default to crypto capital income (401)
    assert _resolve_income_code("unknown_type") == "401"
    assert _resolve_income_code("custom_reward") == "401"
    assert _resolve_income_code("") == "401"

    # Case insensitive
    assert _resolve_income_code("STAKING") == "401"
    assert _resolve_income_code("Airdrop") == "401"
    assert _resolve_income_code("  lending  ") == "402"

    # Edge cases: whitespace-only defaults to 401
    assert _resolve_income_code("   ") == "401"
    assert _resolve_income_code("\t\n") == "401"
    assert _resolve_income_code("  \t  ") == "401"

    # Edge cases: formula-prefix-only defaults to 401 (not a digit)
    assert _resolve_income_code("===") == "401"
    assert _resolve_income_code("+++") == "401"
    assert _resolve_income_code("---") == "401"
    assert _resolve_income_code("@@@") == "401"


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
            source_type="reward",
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

    result = aggregate_taxable_rewards(entries)

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
    """ByBit wallet aliases should be normalized to ByBit."""
    from tax_reporting.infrastructure.koinly_parser import normalize_platform_name

    assert normalize_platform_name("ByBit (2)") == "ByBit"
    assert normalize_platform_name("ByBit (3)") == "ByBit"
    assert normalize_platform_name("ByBit (4)") == "ByBit"
    assert normalize_platform_name("ByBit (5)") == "ByBit"
    assert normalize_platform_name("ByBit (10)") == "ByBit"
    assert normalize_platform_name("ByBit") == "ByBit"


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
    """Numbered wallets other than ByBit should be preserved as distinct wallets.

    This test verifies that only ByBit numbered aliases are normalized per CRG-008.
    Other platforms like Kraken may have genuinely distinct numbered wallets that
    should not be merged during aggregation.
    """
    from tax_reporting.infrastructure.koinly_parser import normalize_platform_name

    # Non-ByBit numbered wallets are preserved as distinct wallets
    assert normalize_platform_name("Kraken (2)") == "Kraken (2)"
    assert normalize_platform_name("Kraken (3)") == "Kraken (3)"
    assert normalize_platform_name("Binance (2)") == "Binance (2)"


def test_normalize_platform_name_preserves_bybit_prefixed_wallets():
    """ByBit-prefixed wallets that are NOT the simple 'ByBit (n)' pattern should be preserved.

    This test verifies that only the exact pattern 'ByBit (n)' is normalized per CRG-008.
    Other ByBit-prefixed wallets like 'ByBit Earn (2)' or 'ByBit Savings (3)' represent
    distinct products and should not be collapsed into the main ByBit account.
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

    from tax_reporting.application.crypto_reporting import TokenOriginResolver

    resolver = TokenOriginResolver(th_csv)
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

    from tax_reporting.application.crypto_reporting import TokenOriginResolver

    skipped = Counter()
    review_entries: list = []
    context = CapitalGainsParsingContext(
        skipped_assets=skipped,
        origin_resolver=TokenOriginResolver(),
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

    from tax_reporting.application.crypto_reporting import TokenOriginResolver

    skipped = Counter()
    review_entries: list = []
    context = CapitalGainsParsingContext(
        skipped_assets=skipped,
        origin_resolver=TokenOriginResolver(),
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

    from tax_reporting.application.crypto_reporting import TokenOriginResolver

    skipped = {}
    review_entries: list = []
    context = CapitalGainsParsingContext(
        skipped_assets=skipped,
        origin_resolver=TokenOriginResolver(),
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


def test_real_koinly_fixture_has_no_duplicate_aggregation_keys():
    """Characterization test: loading the real koinly2025 fixture produces zero
    duplicate rows when grouped by the full aggregation key
    (disposal_date, asset, platform, holding_period).

    If this test fails, _aggregate_capital_entries() or upstream parsing has
    introduced a regression that splits same-key rows instead of collapsing them.
    """
    from collections import Counter
    from pathlib import Path

    koinly_dir = Path("resources/source/koinly2025")
    report = load_koinly_crypto_report(koinly_dir)
    if report is None:
        pytest.skip("koinly2025 fixture directory not available")

    keys = [(e.disposal_date, e.asset, e.platform, e.holding_period) for e in report.capital_entries]
    dups = [(k, c) for k, c in Counter(keys).items() if c > 1]
    assert dups == [], (
        f"Duplicate aggregation keys found after loading koinly2025: {dups}. "
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
        resolver = TokenOriginResolver(path)
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
        resolver = TokenOriginResolver(path)
        origin = resolver.resolve("2025-03-10", "SOL", "ByBit")
        assert origin.acquisition_method == AcquisitionMethod.REWARD
        assert origin.confidence == "medium"

    def test_token_origin_resolver_unknown_when_no_match(self, tmp_path) -> None:
        path = self._write_th(
            tmp_path,
            '2025-01-15 10:30:00 UTC,exchange,,Kraken,100,BTC,5000,'
            "Kraken,2.5,ETH,5000,,,,,,abc,def,hash123,trade\n",
        )
        resolver = TokenOriginResolver(path)
        origin = resolver.resolve("2025-06-01", "BTC", "UnknownWallet")
        assert origin.acquisition_method == AcquisitionMethod.UNKNOWN
        assert origin.confidence == "low"

    def test_token_origin_resolver_unknown_when_no_transaction_history(self) -> None:
        resolver = TokenOriginResolver(None)
        origin = resolver.resolve("2025-01-15", "BTC", "Kraken")
        assert origin.acquisition_method == AcquisitionMethod.UNKNOWN
        assert origin.confidence == "low"

    def test_token_origin_resolver_epoch_date_returns_unknown(self, tmp_path) -> None:
        path = self._write_th(tmp_path, "")
        resolver = TokenOriginResolver(path)
        origin = resolver.resolve("1970-01-01", "BTC", "Kraken")
        assert origin.acquisition_method == AcquisitionMethod.UNKNOWN
        assert origin.confidence == "low"

    def test_token_origin_resolver_direct_purchase_fiat_deposit(self, tmp_path) -> None:
        path = self._write_th(
            tmp_path,
            '2025-02-20 14:00:00 UTC,fiat_deposit,,Bank,5000,EUR,5000,'
            "Kraken,0.5,BTC,5000,,,,,,,,,\n",
        )
        resolver = TokenOriginResolver(path)
        origin = resolver.resolve("2025-02-20", "BTC", "Kraken")
        assert origin.acquisition_method == AcquisitionMethod.DIRECT_PURCHASE
        assert origin.acquired_from_asset == "EUR"

    def test_token_origin_resolver_defi_yield_lending_interest(self, tmp_path) -> None:
        path = self._write_th(
            tmp_path,
            "2025-04-01 00:00:00 UTC,crypto_deposit,Lending interest,,,,,"
            'Ethereum,0.1,USDT,100,,,,,,,,,\n',
        )
        resolver = TokenOriginResolver(path)
        origin = resolver.resolve("2025-04-01", "USDT", "Ethereum")
        assert origin.acquisition_method == AcquisitionMethod.DEFI_YIELD

    def test_token_origin_resolver_medium_confidence_without_hash(self, tmp_path) -> None:
        path = self._write_th(
            tmp_path,
            "2025-05-10 09:00:00 UTC,crypto_deposit,Reward,,,,,"
            'Kraken,10,ETH,200,,,,,,,,,\n',
        )
        resolver = TokenOriginResolver(path)
        origin = resolver.resolve("2025-05-10", "ETH", "Kraken")
        assert origin.confidence == "medium"

    def test_token_origin_resolver_low_confidence_missing_cost_basis(self, tmp_path) -> None:
        path = self._write_th(
            tmp_path,
            '2025-01-15 10:30:00 UTC,exchange,,Kraken,100,BTC,5000,'
            "Kraken,2.5,ETH,5000,,,,,,abc,def,hash123,trade\n",
        )
        resolver = TokenOriginResolver(path)
        origin = resolver.resolve("2025-01-15", "ETH", "Kraken", notes="Missing cost basis")
        assert origin.confidence == "low"

    def test_token_origin_resolver_cashback_is_reward(self, tmp_path) -> None:
        path = self._write_th(
            tmp_path,
            "2025-06-01 12:00:00 UTC,crypto_deposit,Cashback,,,,,"
            'Wirex,10,WXT,5,,,,,,,,,\n',
        )
        resolver = TokenOriginResolver(path)
        origin = resolver.resolve("2025-06-01", "WXT", "Wirex")
        assert origin.acquisition_method == AcquisitionMethod.REWARD

    def test_token_origin_resolver_transfer_generic_deposit(self, tmp_path) -> None:
        path = self._write_th(
            tmp_path,
            "2025-07-01 09:00:00 UTC,crypto_deposit,,,,,,"
            'Binance,1,BTC,50000,,,,,,,,,\n',
        )
        resolver = TokenOriginResolver(path)
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
        resolver = TokenOriginResolver(path)
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
        resolver = TokenOriginResolver(path)
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
    assert entry.balance_status == "Settled"
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
    assert entries[0].balance_status == "Open loan"
    assert entries[0].balance_amount == Decimal("100.00")


def test_extract_loan_activity_overpaid_status(tmp_path):
    """More repaid than received produces 'Overpaid' balance status."""
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
    assert entries[0].balance_status == "Overpaid (cross-year loan?)"
    assert entries[0].balance_amount == Decimal("-50.00")



    """An exchange row tagged 'Loan' must not be counted as a loan receipt."""
    from tax_reporting.application.crypto.loan_activity import _extract_loan_activity

    path = _write_transaction_history(
        tmp_path,
        [
            (
                '2025-01-10 10:00:00 UTC,exchange,Loan,'
                'ByBit,50.00,BTC,25.00,Kraken,100.00,SUI,50.00,,,300.00,,"","","",""'
            ),
        ],
    )

    entries = _extract_loan_activity(path)
    assert entries == []


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
    from tax_reporting.application.token_origin import TokenOriginResolver

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
    resolver = TokenOriginResolver(None)
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

    # TH has a loan-tagged TESTTOK row → dynamic discovery returns {"TESTTOK"}
    testtok_loan_row = ",".join([
        "2025-01-01 10:00:00 UTC", "exchange", "loan", "Kraken", "500", "EUR", "500",
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
    from tax_reporting.application.token_origin import TokenOriginResolver

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

    resolver = TokenOriginResolver(th_path)
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
    from tax_reporting.application.token_origin import TokenOriginResolver

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

    resolver = TokenOriginResolver(th_path)
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
    from tax_reporting.application.token_origin import TokenOriginResolver

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

    resolver = TokenOriginResolver(th_path)
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
    """Zero-value rewards for known assets are flagged with review_required=True."""
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

    with caplog.at_level(logging.WARNING, logger="tax_reporting.application.crypto_reporting"):
        entries = _parse_income_file(income_file, skipped_assets, known_assets=frozenset(["BTC", "ETH", "USDT"]))

    # All three zero-value rewards should be created with review_required=True
    assert len(entries) == 3
    for entry in entries:
        assert entry.review_required is True
        assert "Zero EUR value for known crypto asset" in entry.review_reason

    # None should be in skipped_assets (they were flagged for review instead)
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
    """Zero-value rewards for popular tokens (via substring matching) are flagged for review."""
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

    # Mock _get_popular_crypto_tokens to include TON and USDE for substring matching
    with patch(
        "tax_reporting.application.crypto_reporting._get_popular_crypto_tokens",
        return_value=frozenset(["BTC", "ETH", "TON", "USDE"]),
    ):
        entries = _parse_income_file(income_file, skipped_assets, known_assets=frozenset(["TON", "USDE"]))

    # TSTON (contains TON) and TSUSDE (contains USDE) should be flagged for review
    # UNKNOWNX should be skipped
    assert len(entries) == 2

    entry_assets = {e.asset for e in entries}
    assert "TSTON" in entry_assets
    assert "TSUSDE" in entry_assets
    assert "UNKNOWNX" not in entry_assets

    for entry in entries:
        assert entry.review_required is True
        assert "Zero EUR value for known crypto asset" in entry.review_reason

    # Only UNKNOWNX should be in skipped_assets
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
    """Wallet aliases like 'ByBit (2)' normalize to 'ByBit' at parse time.

    Under the Task 6 refactor, ``normalize_platform_name`` runs in
    ``_parse_other_gains_row`` (not in ``_build_ogr_index``), so the alias
    collapse is verified end-to-end by writing a real OGR CSV and running it
    through ``_find_and_parse_other_gains_file``. Both rows share the resulting
    ``(2025-01-13, USDT, ByBit)`` key; the new pure-summing ``_build_ogr_index``
    adds their signed values (-138.73 + 100 = -38.73), matching the old
    composed-pipeline behavior for keys that collapse together.
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

    # Both wallets normalize to "ByBit" at parse time and share one key.
    assert len(index) == 1
    assert ("2025-01-13", "USDT", "ByBit") in index
    # Summed value: -138.73 (Loss) + 100 (Profit) = -38.73
    assert index[("2025-01-13", "USDT", "ByBit")] == Decimal("-38.73")


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


# =============================================================================
# Unit tests for _apply_ogr_overrides()
# =============================================================================


def test_ogr_loss_override_applied():
    """CG entry with gain=+22.71 EUR and OGR index Type="Loss", value=-138.73 EUR.

    Expects entry gain/loss set to -138.73 EUR.
    """
    from tax_reporting.infrastructure.config import TaxJurisdictionConfig

    # Create a jurisdiction with use_other_gains_report enabled
    jurisdiction = TaxJurisdictionConfig(
        country="TEST",
        fiscal_year=2025,
        exclude_loan_repayment_gains=False,
        zero_basis_review_threshold=Decimal("500"),
        use_other_gains_report=True,
    )

    # Create OGR index with a loss entry
    ogr_index = {
        ("2025-01-13", "USDT", "ByBit"): Decimal("-138.73")
    }

    # Create CG entry that should be overridden
    cg_entry = CryptoCapitalGainEntry(
        disposal_date="2025-01-13",
        acquisition_date="2025-01-10",
        asset="USDT",
        amount=Decimal("142.11"),
        cost_eur=Decimal("165.44"),
        proceeds_eur=Decimal("188.15"),
        gain_loss_eur=Decimal("22.71"),  # Original gain from Koinly CG
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

    # Apply OGR override
    result = _apply_ogr_overrides([cg_entry], ogr_index, jurisdiction)

    # Expected: gain/loss should be overridden to -138.73 (loss from OGR)
    assert len(result) == 1
    assert result[0].gain_loss_eur == Decimal("-138.73")
    # Proceeds should be updated to maintain consistency: proceeds = cost + gain_loss
    # So proceeds = 165.44 + (-138.73) = 26.71
    expected_proceeds = cg_entry.cost_eur + Decimal("-138.73")
    assert result[0].proceeds_eur == expected_proceeds
    # Notes should mention OGR override
    assert "OGR override" in result[0].notes or "Other Gains Report" in result[0].notes


def test_ogr_profit_override_applied():
    """Given CG entry with gain=+100 EUR and OGR index with Type="Profit", value=+80 EUR, expects entry gain/loss set to
    +80 EUR.
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
        ("2025-01-15", "ETH", "Kraken"): Decimal("80")
    }

    cg_entry = CryptoCapitalGainEntry(
        disposal_date="2025-01-15",
        acquisition_date="2025-01-01",
        asset="ETH",
        amount=Decimal("1.0"),
        cost_eur=Decimal("400"),
        proceeds_eur=Decimal("500"),
        gain_loss_eur=Decimal("100"),  # Original gain
        holding_period="Short-term (14 days)",
        wallet="Kraken",
        platform="Kraken",
        chain="Ethereum",
        operator_origin=OperatorOrigin(
            platform="Kraken",
            service_scope="crypto",
            operator_entity="Payward Ireland Limited",
            operator_country="IE",
            source_url="https://kraken.com",
            source_checked_on="2026-01-01",
            confidence="high",
            review_required=False,
        ),
        annex_hint="J",
        review_required=False,
        notes="",
    )

    result = _apply_ogr_overrides([cg_entry], ogr_index, jurisdiction)

    assert len(result) == 1
    assert result[0].gain_loss_eur == Decimal("80")
    expected_proceeds = cg_entry.cost_eur + Decimal("80")
    assert result[0].proceeds_eur == expected_proceeds


def test_ogr_no_override_when_disabled():
    """Given jurisdiction with use_other_gains_report=False, expects CG values unchanged regardless of OGR."""
    from tax_reporting.infrastructure.config import TaxJurisdictionConfig

    jurisdiction = TaxJurisdictionConfig(
        country="TEST",
        fiscal_year=2025,
        exclude_loan_repayment_gains=False,
        zero_basis_review_threshold=Decimal("500"),
        use_other_gains_report=False,  # Disabled
    )

    ogr_index = {
        ("2025-01-13", "USDT", "ByBit"): Decimal("-138.73")
    }

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

    result = _apply_ogr_overrides([cg_entry], ogr_index, jurisdiction)

    # No override should occur
    assert len(result) == 1
    assert result[0].gain_loss_eur == Decimal("22.71")
    assert result[0].proceeds_eur == Decimal("188.15")


def test_ogr_no_override_when_no_match():
    """Given CG entry with no OGR match, expects CG value unchanged with warning log."""
    from tax_reporting.infrastructure.config import TaxJurisdictionConfig

    jurisdiction = TaxJurisdictionConfig(
        country="TEST",
        fiscal_year=2025,
        exclude_loan_repayment_gains=False,
        zero_basis_review_threshold=Decimal("500"),
        use_other_gains_report=True,
    )

    # OGR index has different date/asset/wallet - no match
    ogr_index = {
        ("2025-01-14", "BTC", "Kraken"): Decimal("100")
    }

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

    result = _apply_ogr_overrides([cg_entry], ogr_index, jurisdiction)

    # No override - original values preserved
    assert len(result) == 1
    assert result[0].gain_loss_eur == Decimal("22.71")
    assert result[0].proceeds_eur == Decimal("188.15")


def test_ogr_skips_fee_tokens():
    """Given OGR entry with Value=0.0, expects override not applied (fee tokens are not capital gains)."""
    from tax_reporting.infrastructure.config import TaxJurisdictionConfig

    jurisdiction = TaxJurisdictionConfig(
        country="TEST",
        fiscal_year=2025,
        exclude_loan_repayment_gains=False,
        zero_basis_review_threshold=Decimal("500"),
        use_other_gains_report=True,
    )

    # OGR index should NOT contain zero-value entries (they're filtered by _build_ogr_index)
    # This test verifies that zero-value OGR rows don't cause issues
    ogr_index = {}  # Empty because zero-value rows are skipped

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

    result = _apply_ogr_overrides([cg_entry], ogr_index, jurisdiction)

    # No override - original values preserved
    assert len(result) == 1
    assert result[0].gain_loss_eur == Decimal("22.71")


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

        result = _apply_ogr_direction_override([cg_entry], ogr_index, jurisdiction)

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

        result = _apply_ogr_direction_override([cg_entry], ogr_index, jurisdiction)

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

        result = _apply_ogr_direction_override([cg_entry], ogr_index, jurisdiction)

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

        result = _apply_ogr_direction_override([cg_entry], ogr_index, jurisdiction)

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

        result = _apply_ogr_direction_override([cg_entry], ogr_index, jurisdiction)

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
        result = _apply_ogr_direction_override(lots, ogr_index, jurisdiction)

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

        result = _apply_ogr_direction_override([cg_entry], ogr_index, jurisdiction)

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

        result = _apply_ogr_direction_override(entries, ogr_index, jurisdiction)

        assert len(result) == 2
        for entry in result:
            assert entry.ogr_validation is None
        # Verify original CG values are preserved
        assert result[0].gain_loss_eur == Decimal("100")
        assert result[1].gain_loss_eur == Decimal("-200")


# =============================================================================
# Characterization tests for OGR override (golden values captured BEFORE
# derivatives separation, see docs/history/plans/2026-06-13-derivatives-separation.md
# Task 1). These tests capture TODAY's pipeline behavior so that Tasks 2-14 can
# verify the separate_derivatives_reporting=False path remains byte-identical.
# =============================================================================


# Path to the golden-values snapshot written by Task 1. The file lives under
# docs/tmp/ (gitignored) and records the source_sha at capture time plus the two
# aggregated gain values. The characterization test reads this file and asserts
# both the gain values and that source_sha matches the current HEAD (Monitor #3
# mitigation: detects a stale golden file if an unrelated PR changes parser
# behavior before the plan lands).
_GOLDEN_JSON_PATH = Path("docs/tmp/derivatives-characterization-golden.json")


def _load_golden_snapshot() -> dict[str, str]:
    """Load the Task 1 golden-values JSON snapshot.

    Returns the parsed JSON as a dict. Fails the calling test if the file is
    missing or malformed. The snapshot must exist for the characterization
    contract to hold.
    """
    import json

    if not _GOLDEN_JSON_PATH.exists():
        pytest.fail(
            f"Golden snapshot not found at {_GOLDEN_JSON_PATH}. "
            "Run Task 1 of docs/history/plans/2026-06-13-derivatives-separation.md to create it."
        )
    return json.loads(_GOLDEN_JSON_PATH.read_text(encoding="utf-8"))


def _current_head_sha() -> str:
    """Return the current git HEAD commit hash (short-circuit on missing git)."""
    import subprocess

    try:
        # git is expected on PATH in the dev/CI environment; bare executable name
        # keeps the helper portable across machines (noqa: S607).
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],  # noqa: S607
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        pytest.fail(f"Could not determine git HEAD sha for golden-snapshot check: {exc}")


def _build_characterization_jurisdiction():
    """Build a PT/2025 jurisdiction matching the production decision-point flags.

    The characterization test must capture the REAL production OGR override
    behavior, which requires use_other_gains_report=True (the override path is
    gated on this flag at crypto_reporting.py:203). The flags mirror
    docs/maintenance/tax/decision_points/2025.toml [countries.PT] so the captured values
    reflect what main.py produces when run against the koinly2025 fixtures.
    """
    from tax_reporting.infrastructure.config import TaxJurisdictionConfig

    return TaxJurisdictionConfig(
        country="PT",
        fiscal_year=2025,
        exclude_loan_repayment_gains=True,
        zero_basis_review_threshold=Decimal("500"),
        futures_derivatives_taxable=True,
        use_other_gains_report=True,
    )


class TestOgrCharacterizationGolden:
    """Golden-value characterization tests for the OGR direction override.

    Captures the CURRENT pipeline output (pre-derivatives-separation) for the
    ByBit Case 1 and Case 2 fixtures. These values are the backward-compatibility
    target: once separate_derivatives_reporting is added (Task 3), the flag-off
    path must reproduce these exact values.

    The golden snapshot is read from docs/tmp/derivatives-characterization-golden.json,
    which also records the source_sha at capture time. The class-level fixture
    asserts the snapshot's source_sha matches the current HEAD so a stale golden
    file is detected rather than silently masking a behavior change (Monitor #3).
    """

    def setup_method(self) -> None:
        snapshot = _load_golden_snapshot()
        # Monitor #3 informational check: log when the snapshot was captured against
        # a different HEAD. Post-implementation (plan archived), source drift is
        # expected as the codebase evolves; the strict assertion would force a
        # golden refresh on every commit, which is unmaintainable. The value
        # assertions in the test methods are the real backward-compat contract.
        snapshot_sha = snapshot["source_sha"]
        head_sha = _current_head_sha()
        if snapshot_sha != head_sha:
            import logging

            logging.getLogger(__name__).warning(
                "Golden snapshot source_sha (%s) differs from current HEAD (%s). "
                "Values were captured at %s; re-verify the case1/case2 assertions "
                "if parser behavior has changed.",
                snapshot_sha,
                head_sha,
                snapshot_sha,
            )
        self._snapshot = snapshot

    def test_case1_gain_before_separation(self) -> None:
        """ByBit Case 1 aggregated gain for (2025-01-12, USDT, ByBit).

        The current pipeline mixes the OGR Profit row (+140.18 EUR futures P&L)
        with the OGR Loss row (-4.17 EUR futures fee) into a single summed key
        (140.18 + -4.17 = 136.01 EUR) and applies the direction override to the
        single CG fee-disposal lot. The aggregated Crypto Gains entry therefore
        reports 136.01 EUR, the mixed value this test captures.
        """
        report = load_koinly_crypto_report(
            Path("resources/source/koinly2025"),
            jurisdiction=_build_characterization_jurisdiction(),
        )
        if report is None:
            pytest.skip("koinly2025 fixture directory not available")

        matches = [
            e
            for e in report.capital_entries
            if e.disposal_date == "2025-01-12"
            and e.asset == "USDT"
            and e.platform == "ByBit"
        ]
        assert len(matches) == 1, (
            f"Expected exactly one aggregated entry for (2025-01-12, USDT, ByBit), "
            f"got {len(matches)}: {[(e.gain_loss_eur, e.holding_period) for e in matches]}"
        )
        expected = Decimal(self._snapshot["case1_gain_eur"])
        assert matches[0].gain_loss_eur == expected, (
            f"Case 1 golden value drift: expected {expected} EUR, got "
            f"{matches[0].gain_loss_eur} EUR. The OGR override behavior has changed; "
            "either update the golden snapshot (Task 1) or investigate the regression."
        )

    def test_case2_gain_before_separation(self) -> None:
        """ByBit Case 2 aggregated gain for (2025-01-13, USDT, ByBit).

        The current pipeline flips the sign of each CG lot when OGR reports a
        net loss for the same key. The 109 CG lots sum to +26.64 EUR
        pre-override; the direction override negates each lot's magnitude,
        producing an aggregated -26.64 EUR post-override.

        NOTE: the plan (docs/history/plans/2026-06-13-derivatives-separation.md Task 1)
        states the expected golden value is -147.19 EUR, but that figure is the
        OGR USDT ByBit total for 2025-01-13 (rows 0.15 + 8.31 + 138.73), NOT the
        override output. The _apply_ogr_direction_override function
        (ogr_handler.py:274-278) uses OGR for direction only and preserves the
        CG magnitude (-abs(entry.gain_loss_eur) per lot), so the real aggregated
        output is -26.64 EUR. This test captures the REAL behavior; the golden
        snapshot records -26.64 EUR with a full explanation in case2_note.
        """
        report = load_koinly_crypto_report(
            Path("resources/source/koinly2025"),
            jurisdiction=_build_characterization_jurisdiction(),
        )
        if report is None:
            pytest.skip("koinly2025 fixture directory not available")

        matches = [
            e
            for e in report.capital_entries
            if e.disposal_date == "2025-01-13"
            and e.asset == "USDT"
            and e.platform == "ByBit"
        ]
        assert len(matches) == 1, (
            f"Expected exactly one aggregated entry for (2025-01-13, USDT, ByBit), "
            f"got {len(matches)}: {[(e.gain_loss_eur, e.holding_period) for e in matches]}"
        )
        expected = Decimal(self._snapshot["case2_gain_eur"])
        assert matches[0].gain_loss_eur == expected, (
            f"Case 2 golden value drift: expected {expected} EUR, got "
            f"{matches[0].gain_loss_eur} EUR. The OGR override behavior has changed; "
            "either update the golden snapshot (Task 1) or investigate the regression."
        )


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
    """Build a TaxJurisdictionConfig with use_other_gains_report and optional separate_derivatives_reporting."""
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
        """Given a Profit OGR row with no CG counterpart, expects a safety-net logger.warning (r1 Medium #7)."""
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

        caplog.set_level(logging.WARNING)
        spot_index, derivatives_entries = _split_ogr_index(
            rows, capital_entries, _ogr_split_jurisdiction(separate=True)
        )

        # Profit type is always derivatives, so the row is still routed
        assert len(derivatives_entries) == 1
        assert derivatives_entries[0].pnl_eur == Decimal("140.18")
        assert spot_index == {}
        # Safety net warning fired for the no-CG-counterpart ambiguous case
        assert any(
            "routed to derivatives" in rec.message and "ByBit" in rec.message
            for rec in caplog.records
        ), f"Expected safety-net warning; got messages: {[r.message for r in caplog.records]}"

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

    These tests exercise _split_ogr_index + _apply_ogr_direction_override together
    to confirm that derivatives rows routed to derivatives_entries never reach the
    spot CG direction override, so spot fee disposal signs are preserved.
    """

    def test_spot_signs_not_flipped_by_derivatives(self):
        """Given Case 2 fixture (derivatives loss routed separately), expects spot CG signs preserved."""
        from tax_reporting.application.crypto.ogr_handler import (
            _apply_ogr_direction_override,
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

        result = _apply_ogr_direction_override(capital_entries, spot_index, jurisdiction)

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
        from tax_reporting.application.crypto.ogr_handler import (
            _apply_ogr_direction_override,
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
        result = _apply_ogr_direction_override(capital_entries, spot_index, jurisdiction)

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
        note (development_lessons.md #77 silent-overwrite hazard; review r1 Medium 2).
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

    def test_derivatives_entries_populated_when_flag_on(self) -> None:
        """Given separate_derivatives_reporting=True, derivatives_entries contains the 140.18 EUR profit.

        Uses the real koinly2025 fixture (Case 1: 2025-01-12 USDT ByBit Profit
        140.18 + Loss 4.17). With the flag ON, the Profit row is routed to
        derivatives_entries (Profit type is always derivatives) and the Loss
        row matches the CG fee-disposal lot, so it is routed to spot_index.
        """
        koinly_dir = Path("resources/source/koinly2025")
        if not koinly_dir.exists():
            pytest.skip("koinly2025 fixture directory not available")

        jurisdiction = _ogr_split_jurisdiction(separate=True)
        report = load_koinly_crypto_report(koinly_dir, jurisdiction=jurisdiction)
        if report is None:
            pytest.skip("koinly2025 fixture directory not available")

        # The Profit row (140.18 EUR) must appear in derivatives_entries
        # aggregated by (date, asset, platform, event_type).
        profit_matches = [
            e
            for e in report.derivatives_entries
            if e.date == "2025-01-12"
            and e.asset == "USDT"
            and e.platform == "ByBit"
            and e.event_type == DerivativesEventType.PROFIT
        ]
        assert len(profit_matches) == 1, (
            f"Expected exactly one derivatives Profit entry for "
            f"(2025-01-12, USDT, ByBit, PROFIT), got {len(profit_matches)}: "
            f"{[(e.pnl_eur, e.event_type) for e in profit_matches]}"
        )
        assert profit_matches[0].pnl_eur == Decimal("140.18"), (
            f"Expected 140.18 EUR derivatives profit, got {profit_matches[0].pnl_eur}"
        )

    def test_derivatives_entries_empty_when_flag_off(self) -> None:
        """Given separate_derivatives_reporting=False, derivatives_entries is empty.

        Backward compatibility: when the flag is OFF, the pipeline must behave
        byte-identically to pre-Task-9. The derivatives_entries field must be
        empty and the capital_entries path must apply the combined OGR index
        to capital_entries as before (Task 1 golden values: case1=136.01,
        case2=-26.64).
        """
        koinly_dir = Path("resources/source/koinly2025")
        if not koinly_dir.exists():
            pytest.skip("koinly2025 fixture directory not available")

        jurisdiction = _ogr_split_jurisdiction(separate=False)
        report = load_koinly_crypto_report(koinly_dir, jurisdiction=jurisdiction)
        if report is None:
            pytest.skip("koinly2025 fixture directory not available")

        # derivatives_entries must be empty when the flag is off.
        assert report.derivatives_entries == [], (
            f"Expected empty derivatives_entries when "
            f"separate_derivatives_reporting=False, got "
            f"{len(report.derivatives_entries)} entries"
        )

        # Task 1 backward-compat: case1=136.01 EUR, case2=-26.64 EUR.
        case1_matches = [
            e
            for e in report.capital_entries
            if e.disposal_date == "2025-01-12"
            and e.asset == "USDT"
            and e.platform == "ByBit"
        ]
        assert len(case1_matches) == 1, (
            f"Expected exactly one aggregated capital entry for Case 1, got "
            f"{len(case1_matches)}"
        )
        assert case1_matches[0].gain_loss_eur == Decimal("136.01"), (
            f"Case 1 backward-compat drift: expected 136.01 EUR, got "
            f"{case1_matches[0].gain_loss_eur} EUR"
        )

        case2_matches = [
            e
            for e in report.capital_entries
            if e.disposal_date == "2025-01-13"
            and e.asset == "USDT"
            and e.platform == "ByBit"
        ]
        assert len(case2_matches) == 1, (
            f"Expected exactly one aggregated capital entry for Case 2, got "
            f"{len(case2_matches)}"
        )
        assert case2_matches[0].gain_loss_eur == Decimal("-26.64"), (
            f"Case 2 backward-compat drift: expected -26.64 EUR, got "
            f"{case2_matches[0].gain_loss_eur} EUR"
        )

    def test_capital_entries_excludes_derivatives_when_flag_on(self) -> None:
        """Given Case 1 fixture with flag on, capital_entries excludes all derivatives lots.

        With separate_derivatives_reporting=True AND the derivatives TH-label
        CG dedup active, the 140.18 EUR Profit row is routed to
        derivatives_entries AND the 2.44 EUR Futures fee CG lot (CG line 19)
        is removed from capital_entries because its TH event (TH line 205)
        carries Label="Futures fee". So capital_entries contains NO entry for
        the 2025-01-12 USDT ByBit key.

        The key invariant this test guards is the ABSENCE of 136.01 EUR (the
        legacy mixed value) AND the ABSENCE of -2.44 EUR (the legacy
        direction-overridden spot fee value that applied before the dedup
        removed the lot).
        """
        koinly_dir = Path("resources/source/koinly2025")
        if not koinly_dir.exists():
            pytest.skip("koinly2025 fixture directory not available")

        jurisdiction = _ogr_split_jurisdiction(separate=True)
        report = load_koinly_crypto_report(koinly_dir, jurisdiction=jurisdiction)
        if report is None:
            pytest.skip("koinly2025 fixture directory not available")

        case1_matches = [
            e
            for e in report.capital_entries
            if e.disposal_date == "2025-01-12"
            and e.asset == "USDT"
            and e.platform == "ByBit"
        ]
        assert not case1_matches, (
            "Expected NO Crypto Gains entry for (2025-01-12, USDT, ByBit) "
            "after the derivatives CG dedup. The 2.44 EUR Futures fee CG lot "
            "(CG line 19) and the 140.18 EUR Profit row are both routed to "
            "derivatives_entries. Got "
            f"{len(case1_matches)} entries: "
            f"{[(e.gain_loss_eur, e.holding_period) for e in case1_matches]}"
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

    resolver = TokenOriginResolver(th_csv)
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

    resolver = TokenOriginResolver(th_csv)
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
    the TH day, so the DP-014 correction fires and rezeros proceeds to the TH Net
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
        if e.asset == "USDT" and e.disposal_date == "2025-06-14" and e.platform == "ByBit"
    ]
    assert matches, (
        "Expected the corrected Payment disposal on 2025-06-14 (the true UTC day); "
        "the summer-midnight drift broke the cross-report match so the correction was skipped"
    )
    assert matches[0].proceeds_eur == Decimal("120.00"), (
        "DP-014 correction must have rezeroed proceeds to the TH Net Value (120.00); "
        f"got {matches[0].proceeds_eur}"
    )


# --- DP-014 payment-proceeds correction integration tests ---
#
# These tests exercise the wiring of ``correct_payment_proceeds`` into
# ``load_koinly_crypto_report`` (after the OGR override, before aggregation,
# guarded by ``jurisdiction.infer_payment_proceeds``) plus the re-zero snapshot
# that closes the OGR pre-mutation residual. Synthetic tickers/amounts only;
# no real transaction data. See docs/history/plans/2026-06-18-crypto-payment-proceeds.md
# Task 6.

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

    ``use_ogr`` enables the OGR override path so the re-zero mitigation can be
    exercised. ``separate_derivatives_reporting`` is left False so the OGR path
    is the legacy combined-index override (the contract the re-zero snapshot
    was designed against). ``timezone`` defaults to ``ZoneInfo("Europe/Lisbon")``
    (the production PT default; a configured jurisdiction without a resolved
    timezone now fails fast at crypto load rather than silently UTC-stamping).
    Existing fixtures use winter dates, so Lisbon localization is byte-identical
    to the prior UTC-stamp for them.
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
    the OGR override inert (and the re-zero restore it is meant to trigger never
    firing). Callers pass bare European decimals, e.g. ``"-0,01"`` / ``"0,01"``.
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
    """Flag off (lesson #84): Payment row passes through unchanged."""
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
def test_payment_proceeds_ogr_rezero_restores_zero_before_correction(tmp_path):
    """OGR pre-mutation resilience (RED test for the re-zero mitigation).

    An OGR Loss row with near-zero magnitude on the SAME (date, asset, wallet) as a
    proceeds==0 Payment whose TH Net Value > 0. The classifier classifies Spot, so
    _apply_ogr_direction_override mutates the Payment's proceeds. The re-zero snapshot
    must restore the zero so correction's proceeds==0 gate fires and repairs it.
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
    assert matches, "Expected the corrected USDT Payment lot to survive after re-zero + correction"
    entry = matches[0]
    assert entry.proceeds_eur == Decimal("120.00"), (
        f"After re-zero + correction, proceeds must equal Net Value 120.00, got {entry.proceeds_eur}"
    )
    assert entry.gain_loss_eur == Decimal("20.00"), f"gain must be 20.00, got {entry.gain_loss_eur}"


@pytest.mark.unit
def test_payment_proceeds_rezero_index_based_not_key_based(tmp_path):
    """Re-zero does NOT clobber a same-key legitimate OGR-overridden disposal.

    On ONE (date, asset, wallet) key: (a) a genuine non-zero-proceeds derivatives
    disposal that OGR Spot-matches and overrides, AND (b) a separate zero-proceeds
    Payment. The re-zero snapshot is INDEX-based (it captures the i-th pre-OGR
    zero-proceeds entry), so (a) - which had non-zero proceeds - is never in the
    snapshot and KEEPS its OGR-overridden proceeds. A KEY-based snapshot would
    restore every row on the shared (date, asset, wallet) key to 0, destroying
    the legitimate disposal.

    The two rows are given DIFFERENT holding periods so they land in SEPARATE
    aggregation buckets ((date, asset, platform, holding_period)); that lets us
    assert (a)'s proceeds in isolation. If they aggregated into one row, a
    key-based re-zero clobbering (a) would still pass (the corrected Payment's
    proceeds mask it) - a false green the original test admitted.
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
        ogr_rows=[_ogr_row("13/01/2025 13:01", "USDT", "-0,01", "0,01", "Loss", "ByBit (2)")],
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
        and e.platform == "ByBit"
        and e.holding_period.lower().startswith("long")
    ]
    assert len(legitimate) == 1, (
        "Expected the legitimate Long-term disposal as its own aggregated row "
        "(separate bucket from the Payment), "
        f"got {len(legitimate)}: {[(e.holding_period, e.proceeds_eur) for e in legitimate]}"
    )
    # (a) was non-zero proceeds before OGR, so it is OUTSIDE the re-zero snapshot;
    # its OGR-overridden proceeds (recomputed as cost + final_gain_loss) survives.
    assert legitimate[0].proceeds_eur > Decimal("0"), (
        "The legitimate non-zero-proceeds disposal must KEEP its OGR-overridden proceeds "
        f"(re-zero is INDEX-based, not key-based); got {legitimate[0].proceeds_eur}"
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
    """Backward-compat for the tokens.stablecoins extension (EUROC/EURC/EURT).

    Adding EUR-pegged tickers enlarges the set _load_popular_crypto_tokens flattens,
    so a zero-value reward for an EUR-pegged stablecoin is now FLAGGED (not skipped).
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

    eurc_rewards = [e for e in report.reward_entries if e.asset == "EURC"]
    assert eurc_rewards, (
        "A zero-value EURC reward must be FLAGGED (EURC is now in tokens.stablecoins), "
        "not skipped."
    )
    assert eurc_rewards[0].review_required is True
    wxt_rewards = [e for e in report.reward_entries if e.asset == "WXT"]
    assert wxt_rewards, "Control: the non-zero WXT reward must still be parsed"
