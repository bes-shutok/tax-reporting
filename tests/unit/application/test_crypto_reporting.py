from __future__ import annotations

from decimal import Decimal

from shares_reporting.application.crypto_reporting import (
    _parse_koinly_decimal,
    load_koinly_crypto_report,
    resolve_operator_origin,
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
                        '"1,35"',
                        '"0,10"',
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
                "01/01/2025 00:01,WXT,\"5,00000000\",\"17,10\",Reward,,Wirex",
                "02/01/2025 00:01,USDT,\"2,00000000\",\"2,10\",Lending interest,,ByBit (2)",
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
                "BTC,\"1,00000000\",\"100,00\",\"120,00\",",
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
                "BTC,\"1,00000000\",\"130,00\",\"150,00\",",
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
    assert report.reconciliation.capital_proceeds_total_eur == Decimal("3501.35")
    assert report.reconciliation.reward_total_eur == Decimal("19.20")
    assert report.reconciliation.opening_holdings is not None
    assert report.reconciliation.closing_holdings is not None
    assert report.reconciliation.opening_holdings.total_value_eur == Decimal("120.00")
    assert report.reconciliation.closing_holdings.total_value_eur == Decimal("150.00")
    assert report.skipped_zero_value_tokens == []


def test_resolve_operator_origin_splits_wirex_by_transaction_type():
    crypto_origin = resolve_operator_origin("Wirex", transaction_type="crypto_deposit")
    fiat_origin = resolve_operator_origin("Wirex", transaction_type="fiat_deposit")

    assert crypto_origin.service_scope == "crypto"
    assert fiat_origin.service_scope == "fiat"
    assert crypto_origin.operator_entity != fiat_origin.operator_entity


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
                "01/01/2025 00:01,AAA,\"1,00000000\",0.0,Reward,,Wirex",
                "02/01/2025 00:01,BBB,\"2,00000000\",\"2,10\",Reward,,Wirex",
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
                "ZERO,\"1,00000000\",\"10,00\",0.0,",
                "NZ,\"1,00000000\",\"10,00\",\"11,00\",",
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


def test_parse_koinly_decimal_handles_single_dot_european_thousands_grouping():
    assert _parse_koinly_decimal("10.000") == Decimal("10000")
    assert _parse_koinly_decimal("100.000") == Decimal("100000")


def test_parse_koinly_decimal_does_not_treat_subunit_values_as_thousands_grouping():
    assert _parse_koinly_decimal("0,001") == Decimal("0.001")
    assert _parse_koinly_decimal("0,010") == Decimal("0.010")
    assert _parse_koinly_decimal("0,100") == Decimal("0.100")
    assert _parse_koinly_decimal("0.001") == Decimal("0.001")
    assert _parse_koinly_decimal("0.010") == Decimal("0.010")
    assert _parse_koinly_decimal("0.100") == Decimal("0.100")
