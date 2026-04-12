from __future__ import annotations

import dataclasses
import logging
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from shares_reporting.application.crypto_reporting import (
    AcquisitionMethod,
    CryptoCapitalGainEntry,
    OperatorOrigin,
    RewardTaxClassification,
    TokenOrigin,
    TokenOriginResolver,
    _aggregate_capital_entries,
    _classify_reward_tax_status,
    _derive_chain,
    _filter_immaterial_entries,
    _format_datetime,
    _is_temporally_valid,
    _is_valid_tabela_x_country,
    _parse_koinly_decimal,
    _parse_transaction_date,
    _resolve_income_code,
    _validate_capital_entries_have_valid_countries,
    aggregate_taxable_rewards,
    load_koinly_crypto_report,
    resolve_operator_origin,
)

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

    report = load_koinly_crypto_report(koinly_dir)

    assert report is not None
    assert report.pdf_summary is not None
    assert report.pdf_summary.period == "1 Jan 2025 to 31 Dec 2025"
    assert report.pdf_summary.timezone == "Europe/Lisbon"


def test_parse_koinly_decimal_handles_single_group_comma_thousands_separator():
    assert _parse_koinly_decimal("1,000") == Decimal("1000")
    assert _parse_koinly_decimal("8,400") == Decimal("8400")
    assert _parse_koinly_decimal("1,001") == Decimal("1001")


def test_parse_koinly_decimal_handles_unambiguous_multi_group_thousands_separator():
    assert _parse_koinly_decimal("1,000,000") == Decimal("1000000")
    assert _parse_koinly_decimal("12,000,000") == Decimal("12000000")


def test_parse_koinly_decimal_keeps_decimal_comma_when_fractional_precision_is_not_thousands_grouped():
    assert _parse_koinly_decimal("1,50000000") == Decimal("1.50000000")
    assert _parse_koinly_decimal("3000,00") == Decimal("3000.00")


def test_parse_koinly_decimal_handles_both_common_mixed_separator_formats():
    assert _parse_koinly_decimal("1,234.56") == Decimal("1234.56")
    assert _parse_koinly_decimal("1.234,56") == Decimal("1234.56")


def test_parse_koinly_decimal_raises_on_ambiguous_single_group_dot():
    """Single-group dot values like '1.234' are ambiguous (decimal vs thousands) — must fail."""
    with pytest.raises(ValueError, match="Ambiguous"):
        _parse_koinly_decimal("1.234")
    with pytest.raises(ValueError, match="Ambiguous"):
        _parse_koinly_decimal("10.000")
    with pytest.raises(ValueError, match="Ambiguous"):
        _parse_koinly_decimal("100.000")
    # Negative values are equally ambiguous: -1.234 could be -1.234 or -1234
    with pytest.raises(ValueError, match="Ambiguous"):
        _parse_koinly_decimal("-1.234")
    with pytest.raises(ValueError, match="Ambiguous"):
        _parse_koinly_decimal("-10.000")


def test_parse_koinly_decimal_handles_multi_group_dot_as_european_thousands():
    """Multi-group dot values like '1.234.567' are unambiguously European thousands."""
    assert _parse_koinly_decimal("1.234.567") == Decimal("1234567")
    assert _parse_koinly_decimal("12.345.678") == Decimal("12345678")


def test_parse_koinly_decimal_does_not_treat_subunit_values_as_thousands_grouping():
    assert _parse_koinly_decimal("0,001") == Decimal("0.001")
    assert _parse_koinly_decimal("0,010") == Decimal("0.010")
    assert _parse_koinly_decimal("0,100") == Decimal("0.100")
    assert _parse_koinly_decimal("0.001") == Decimal("0.001")
    assert _parse_koinly_decimal("0.010") == Decimal("0.010")
    assert _parse_koinly_decimal("0.100") == Decimal("0.100")


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
                        "1.234",  # ambiguous — should skip this row
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

    with caplog.at_level(logging.WARNING, logger="shares_reporting.application.crypto_reporting"):
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
    assert _parse_koinly_decimal("-1,234.56") == Decimal("-1234.56")
    assert _parse_koinly_decimal("-1.234,56") == Decimal("-1234.56")
    assert _parse_koinly_decimal("-1,000") == Decimal("-1000")
    assert _parse_koinly_decimal("-0,50") == Decimal("-0.50")
    assert _parse_koinly_decimal("-500.00") == Decimal("-500.00")
    assert _parse_koinly_decimal("-0.99") == Decimal("-0.99")


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
    assert bybit_upper.review_required is True
    assert bybit_lower.review_required is True
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
    from shares_reporting.application.crypto_reporting import ZERO, CryptoRewardIncomeEntry

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
    from shares_reporting.application.crypto_reporting import ZERO, CryptoRewardIncomeEntry

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
    from shares_reporting.application.crypto_reporting import CryptoRewardIncomeEntry

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
    from shares_reporting.application.crypto_reporting import ZERO, CryptoRewardIncomeEntry

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
    from shares_reporting.application.crypto_reporting import ZERO, CryptoRewardIncomeEntry
    from shares_reporting.domain.exceptions import FileProcessingError

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

    with pytest.raises(FileProcessingError, match="cannot be assigned a valid Tabela X country code"):
        aggregate_taxable_rewards(entries)


def test_aggregate_taxable_rewards_wallet_aliases_collapse():
    """ByBit and ByBit (2) should collapse into the same logical account for reward aggregation.

    Rewards aggregate by (income_code, source_country), not by platform. Wallet
    normalization affects this indirectly because operator_country is derived from
    the normalized platform name via resolve_operator_origin(). Since both ByBit
    and ByBit (2) normalize to the same platform, they get the same country and
    aggregate together.
    """
    from shares_reporting.application.crypto_reporting import ZERO, CryptoRewardIncomeEntry

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
    from shares_reporting.application.crypto_reporting import ZERO, CryptoRewardIncomeEntry

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


def test_aggregate_preserves_reconciliation_trail():
    """Aggregation must preserve raw row count for reconciliation."""
    from shares_reporting.application.crypto_reporting import ZERO, CryptoRewardIncomeEntry

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

    # Should not raise any exception
    _validate_capital_entries_have_valid_countries(entries)


def test_validate_capital_entries_fails_on_unknown_country():
    """Validation must fail with clear error when capital entries have invalid Tabela X country."""
    from shares_reporting.domain.exceptions import FileProcessingError

    entries = [
        _make_entry(
            wallet="UnknownExchange",
            platform="UnknownExchange",
            operator_origin=dataclasses.replace(_TEST_OPERATOR, operator_country="UNKNOWN"),
        ),
    ]

    with pytest.raises(FileProcessingError, match="invalid Tabela X country codes"):
        _validate_capital_entries_have_valid_countries(entries)


def test_validate_capital_entries_fails_on_multiple_unknown_countries():
    """Validation error should list all entries with invalid country codes."""
    from shares_reporting.domain.exceptions import FileProcessingError

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

    with pytest.raises(FileProcessingError, match="2 entries have invalid Tabela X country codes"):
        _validate_capital_entries_have_valid_countries(entries)


def test_validate_capital_entries_includes_detailed_error_info():
    """Validation error should include wallet, asset, date, and resolved country for debugging."""
    from shares_reporting.domain.exceptions import FileProcessingError

    entries = [
        _make_entry(
            disposal_date="2025-01-15",
            asset="BTC",
            wallet="SomeUnknownWallet",
            platform="SomeUnknownWallet",
            operator_origin=dataclasses.replace(_TEST_OPERATOR, operator_country="UNKNOWN"),
        ),
    ]

    with pytest.raises(FileProcessingError) as exc_info:
        _validate_capital_entries_have_valid_countries(entries)

    error_message = str(exc_info.value)
    assert "SomeUnknownWallet" in error_message
    assert "BTC" in error_message
    assert "2025-01-15" in error_message
    assert "UNKNOWN" in error_message


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
    from shares_reporting.application.crypto_reporting import _normalize_platform_name

    assert _normalize_platform_name("ByBit (2)") == "ByBit"
    assert _normalize_platform_name("ByBit (3)") == "ByBit"
    assert _normalize_platform_name("ByBit (4)") == "ByBit"
    assert _normalize_platform_name("ByBit (5)") == "ByBit"
    assert _normalize_platform_name("ByBit (10)") == "ByBit"
    assert _normalize_platform_name("ByBit") == "ByBit"


def test_normalize_platform_name_preserves_distinct_wallets():
    """Distinct wallets like Ethereum addresses should NOT be normalized."""
    from shares_reporting.application.crypto_reporting import _normalize_platform_name

    # These are distinct wallets and should be preserved
    assert _normalize_platform_name("Ethereum (ETH) - 0xabc") == "Ethereum (ETH) - 0xabc"
    assert _normalize_platform_name("Ethereum (ETH) - 0xdef") == "Ethereum (ETH) - 0xdef"
    assert _normalize_platform_name("Solana (SOL) - 5R39") == "Solana (SOL) - 5R39"


def test_normalize_platform_name_empty_and_whitespace():
    """Empty and whitespace-only wallets should return Unknown."""
    from shares_reporting.application.crypto_reporting import _normalize_platform_name

    assert _normalize_platform_name("") == "Unknown"
    assert _normalize_platform_name("   ") == "Unknown"
    assert _normalize_platform_name("\t") == "Unknown"


def test_normalize_platform_name_no_alias():
    """Wallets without numeric aliases should be unchanged."""
    from shares_reporting.application.crypto_reporting import _normalize_platform_name

    assert _normalize_platform_name("Kraken") == "Kraken"
    assert _normalize_platform_name("Binance") == "Binance"
    assert _normalize_platform_name("Ledger Berachain (BERA)") == "Ledger Berachain (BERA)"


def test_normalize_platform_name_preserves_non_bybit_numbered_wallets():
    """Numbered wallets other than ByBit should be preserved as distinct wallets.

    This test verifies that only ByBit numbered aliases are normalized per CRG-008.
    Other platforms like Kraken may have genuinely distinct numbered wallets that
    should not be merged during aggregation.
    """
    from shares_reporting.application.crypto_reporting import _normalize_platform_name

    # Non-ByBit numbered wallets are preserved as distinct wallets
    assert _normalize_platform_name("Kraken (2)") == "Kraken (2)"
    assert _normalize_platform_name("Kraken (3)") == "Kraken (3)"
    assert _normalize_platform_name("Binance (2)") == "Binance (2)"


def test_normalize_platform_name_preserves_bybit_prefixed_wallets():
    """ByBit-prefixed wallets that are NOT the simple 'ByBit (n)' pattern should be preserved.

    This test verifies that only the exact pattern 'ByBit (n)' is normalized per CRG-008.
    Other ByBit-prefixed wallets like 'ByBit Earn (2)' or 'ByBit Savings (3)' represent
    distinct products and should not be collapsed into the main ByBit account.
    """
    from shares_reporting.application.crypto_reporting import _normalize_platform_name

    # ByBit-prefixed wallets with additional words are preserved
    assert _normalize_platform_name("ByBit Earn (2)") == "ByBit Earn (2)"
    assert _normalize_platform_name("ByBit Savings (3)") == "ByBit Savings (3)"
    assert _normalize_platform_name("ByBit Earn") == "ByBit Earn"
    assert _normalize_platform_name("ByBit Savings") == "ByBit Savings"


def test_normalize_asset_ticker_cyrillic_to_latin():
    """Asset tickers with Cyrillic characters should be normalized to Latin equivalents.

    This test verifies the fix for the WBТC issue where the 'T' was a Cyrillic
    character (U+0422) instead of Latin 'T'.
    """
    from shares_reporting.application.crypto_reporting import _normalize_asset_ticker

    # Cyrillic Т (U+0422) -> Latin T
    assert _normalize_asset_ticker("WBТC") == "WBTC"
    assert _normalize_asset_ticker("BТC") == "BTC"
    # Multiple Cyrillic characters
    assert _normalize_asset_ticker("ТЕSТ") == "TEST"


def test_normalize_asset_ticker_unicode_normalization():
    """Asset tickers should be normalized to canonical composed unicode form."""
    from shares_reporting.application.crypto_reporting import _normalize_asset_ticker

    # Unicode normalization handles various unicode equivalence issues
    assert _normalize_asset_ticker("BTC") == "BTC"
    assert _normalize_asset_ticker("  BTC  ") == "BTC"  # Whitespace trimming
    assert _normalize_asset_ticker("BTC\t") == "BTC"


def test_normalize_asset_ticker_preserves_valid_tickers():
    """Valid asset tickers should be preserved unchanged."""
    from shares_reporting.application.crypto_reporting import _normalize_asset_ticker

    assert _normalize_asset_ticker("BTC") == "BTC"
    assert _normalize_asset_ticker("ETH") == "ETH"
    assert _normalize_asset_ticker("SUI") == "SUI"
    assert _normalize_asset_ticker("HASUI") == "HASUI"
    assert _normalize_asset_ticker("USDC") == "USDC"
    assert _normalize_asset_ticker("USDT") == "USDT"


def test_wirex_fiat_reward_gets_gb_country_code():
    """Wirex fiat-denominated rewards should resolve to GB (Wirex Limited), not HR (Wirex Digital).

    This test verifies the fix for a bug where all Wirex rewards were getting the crypto
    operator origin (HR) regardless of whether they were fiat or crypto denominated.
    Fiat rewards should use the fiat operator (GB) per the split-by-service-scope design.
    """
    from shares_reporting.application.crypto_reporting import resolve_operator_origin

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
    with caplog.at_level(logging.WARNING, logger="shares_reporting.application.crypto_reporting"):
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
    with caplog.at_level(logging.WARNING, logger="shares_reporting.application.crypto_reporting"):
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
    with caplog.at_level(logging.WARNING, logger="shares_reporting.application.crypto_reporting"):
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
    with caplog.at_level(logging.WARNING, logger="shares_reporting.application.crypto_reporting"):
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
    with pytest.raises(ValueError, match="Year.*out of reasonable range"):
        _parse_transaction_date("1899-01-01")
    with pytest.raises(ValueError, match="Year.*out of reasonable range"):
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
    with pytest.raises(ValueError, match="Year.*out of reasonable range"):
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

    Verifies that the actual date format produced by _format_datetime() matches
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

    with caplog.at_level(logging.WARNING, logger="shares_reporting.application.crypto_reporting"):
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
    with caplog.at_level(logging.WARNING, logger="shares_reporting.application.crypto_reporting"):
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

    from shares_reporting.application.crypto_reporting import TokenOriginResolver, _parse_capital_gains_file

    resolver = TokenOriginResolver(th_csv)
    skipped: Counter[tuple[str, str]] = Counter()
    entries = _parse_capital_gains_file(capital_csv, skipped, resolver)

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
    """ByBit platform must have a specific review_reason explaining account-region concern."""
    origin = resolve_operator_origin("ByBit")
    assert origin.review_required is True
    assert origin.review_reason is not None
    assert "account-region" in origin.review_reason.lower()
    assert "Bybit" in origin.review_reason


def test_starknet_operator_origin_no_review_required():
    """Starknet has a known operator with reliable chain derivation; no review needed."""
    origin = resolve_operator_origin("Starknet")
    assert origin.review_required is False
    assert origin.review_reason is None


def test_mantle_operator_origin_has_review_reason():
    """Mantle platform must have a specific review_reason."""
    origin = resolve_operator_origin("Mantle")
    assert origin.review_required is True
    assert origin.review_reason is not None
    assert "Mantle" in origin.review_reason


def test_unknown_operator_origin_has_review_reason():
    """Unknown platforms must have a specific review_reason."""
    origin = resolve_operator_origin("SomeNewChain123")
    assert origin.review_required is True
    assert origin.review_reason is not None
    assert "Unknown platform" in origin.review_reason


def test_temporal_invalidity_sets_review_reason(caplog):
    """Out-of-validity transactions must have a review_reason with the service period."""
    with caplog.at_level(logging.WARNING, logger="shares_reporting.application.crypto_reporting"):
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

    from shares_reporting.application.crypto_reporting import TokenOriginResolver, _parse_capital_gains_file

    skipped = Counter()
    entries = _parse_capital_gains_file(csv_file, skipped, TokenOriginResolver())
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
    """ByBit review flag must stay because region-specific entities cannot be auto-detected from Koinly exports."""
    origin = resolve_operator_origin("ByBit")
    assert origin.review_required is True
    assert origin.operator_country == "AE"
    assert origin.review_reason is not None
    assert "account-region" in origin.review_reason


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

    from shares_reporting.application.crypto_reporting import TokenOriginResolver, _parse_capital_gains_file

    skipped = Counter()
    entries = _parse_capital_gains_file(csv_file, skipped, TokenOriginResolver())
    assert len(entries) == 1
    entry = entries[0]
    assert entry.review_required is True
    assert entry.review_reason is not None
    assert "account-region" in entry.review_reason


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

    from collections import Counter

    from shares_reporting.application.crypto_reporting import TokenOriginResolver, _parse_capital_gains_file

    skipped = Counter()
    entries = _parse_capital_gains_file(csv_file, skipped, TokenOriginResolver())
    assert len(entries) == 0
    assert skipped[("capital_gains", "FEE1")] == 1
    assert skipped[("capital_gains", "FEE2")] == 1


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
    """Origin must NOT match on disposal date — only acquisition date is used.

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


# --- Task 4: MNT ticker collision tests ---


def test_mnt_token_collision():
    """MNT ticker collision between Mantle token (crypto) and Mongolian tögrög (fiat).

    MNT rewards from ByBit/Koinly are Mantle L2 blockchain token, not Mongolian tögrög.
    The crypto token must be classified as DEFERRED_BY_LAW per CRG-001, not TAXABLE_NOW.

    The real Koinly dataset confirms 20 MNT reward rows from ByBit and Mantle wallets
    in the income report, and 17 disposal rows in the capital gains report — all
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
    file containing various Notes values, and once with no capital-gains file
    at all. The reward entries must be identical in both cases.
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

    koinly_dir_no_cg = tmp_path / "no_capital_gains"
    koinly_dir_no_cg.mkdir()
    (koinly_dir_no_cg / "koinly_2025_income_report_test.csv").write_text(income_csv, encoding="utf-8")

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
    from shares_reporting.application.crypto_reporting import CapitalGainPeriodStats

    _zero = Decimal("0")
    stats = CapitalGainPeriodStats(count=0, cost_total_eur=_zero, proceeds_total_eur=_zero, gain_loss_total_eur=_zero)
    assert stats.count == 0
    assert stats.cost_total_eur == Decimal("0")
    assert stats.proceeds_total_eur == Decimal("0")
    assert stats.gain_loss_total_eur == Decimal("0")


def test_capital_gain_period_stats_from_entries():
    """from_entries() correctly sums cost, proceeds, gain/loss and counts entries."""
    from shares_reporting.application.crypto_reporting import CapitalGainPeriodStats

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
    from shares_reporting.application.crypto_reporting import CapitalGainPeriodStats

    stats = CapitalGainPeriodStats.from_entries([])

    assert stats.count == 0
    assert stats.cost_total_eur == Decimal("0")
    assert stats.proceeds_total_eur == Decimal("0")
    assert stats.gain_loss_total_eur == Decimal("0")


# --- Task 2: CryptoCapitalGainStats aggregate tests ---


def test_compute_capital_gain_stats_all_periods():
    """Stats computed across all four holding periods with correct per-period and grand-total values."""
    from shares_reporting.application.crypto_reporting import CryptoCapitalGainStats

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
    from shares_reporting.application.crypto_reporting import CryptoCapitalGainStats

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
    from shares_reporting.application.crypto_reporting import CryptoCapitalGainStats

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
    from shares_reporting.application.crypto_reporting import CryptoCapitalGainStats

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
    from shares_reporting.application.crypto_reporting import CryptoCapitalGainStats

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
    from shares_reporting.application.crypto_reporting import (
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
    assert _format_datetime(datetime(2025, 1, 13, 13, 1, 0, tzinfo=UTC)) == "2025-01-13"


def test_format_datetime_epoch_sentinel_returns_1970_01_01():
    assert _format_datetime(datetime(1970, 1, 1, 0, 0, 0, tzinfo=UTC)) == "1970-01-01"


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
