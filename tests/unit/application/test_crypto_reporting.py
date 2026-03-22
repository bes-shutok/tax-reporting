from __future__ import annotations

import dataclasses
import logging
from decimal import Decimal

import pytest

from shares_reporting.application.crypto_reporting import (
    CryptoCapitalGainEntry,
    OperatorOrigin,
    RewardTaxClassification,
    _aggregate_capital_entries,
    _classify_reward_tax_status,
    _derive_chain,
    _filter_immaterial_entries,
    _is_valid_tabela_x_country,
    _parse_koinly_decimal,
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
)


def _make_entry(  # noqa: PLR0913
    disposal_date: str = "2025-01-13 13:01:00",
    acquisition_date: str = "2024-11-18 00:15:00",
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
            acquisition_date="2024-01-01 00:00:00",
            amount=Decimal("10"),
            cost_eur=Decimal("8"),
            proceeds_eur=Decimal("9"),
            gain_loss_eur=Decimal("1"),
        ),
        _make_entry(
            acquisition_date="2024-06-01 00:00:00",
            amount=Decimal("20"),
            cost_eur=Decimal("16"),
            proceeds_eur=Decimal("18"),
            gain_loss_eur=Decimal("2"),
        ),
        _make_entry(
            acquisition_date="2024-11-18 00:15:00",
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
    # earliest acquisition date
    assert agg.acquisition_date == "2024-01-01 00:00:00"
    assert agg.disposal_date == "2025-01-13 13:01:00"
    assert agg.asset == "USDT"
    assert agg.wallet == "ByBit"


def test_aggregate_different_timestamps_stay_separate():
    entries = [
        _make_entry(disposal_date="2025-01-13 13:01:00", gain_loss_eur=Decimal("2")),
        _make_entry(disposal_date="2025-01-14 09:00:00", gain_loss_eur=Decimal("3")),
    ]

    result = _aggregate_capital_entries(entries)

    assert len(result) == 2
    dates = {e.disposal_date for e in result}
    assert dates == {"2025-01-13 13:01:00", "2025-01-14 09:00:00"}


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
        _make_entry(review_required=True),
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
        disposal_date="2025-03-01 10:00:00",
        acquisition_date="2024-01-15 00:00:00",
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


def test_aggregate_different_wallet_aliases_with_different_timestamps_stay_separate():
    """Different timestamps should still stay separate even with normalized wallet."""
    entries = [
        _make_entry(
            disposal_date="2025-01-13 13:01:00",
            wallet="ByBit",
            platform="ByBit",
            gain_loss_eur=Decimal("2"),
        ),
        _make_entry(
            disposal_date="2025-01-14 09:00:00",
            wallet="ByBit (2)",
            platform="ByBit",
            gain_loss_eur=Decimal("3"),
        ),
    ]

    result = _aggregate_capital_entries(entries)

    # Different timestamps = different sale events, stay separate
    assert len(result) == 2
    timestamps = {e.disposal_date for e in result}
    assert timestamps == {"2025-01-13 13:01:00", "2025-01-14 09:00:00"}
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
    assert agg.disposal_date == "2025-01-13 13:01:00"
    assert agg.wallet == "ByBit"
    assert agg.amount == Decimal("103") * Decimal("0.10000000")
    assert agg.cost_eur == Decimal("103")
    assert agg.proceeds_eur == Decimal("103") * Decimal("1.20")
    assert agg.gain_loss_eur == Decimal("103") * Decimal("0.20")
    # earliest acquisition date among 103 lots
    assert agg.acquisition_date == "2024-01-01 00:00:00"


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
    # All require review
    assert wirex_crypto.review_required is True
    assert wirex_crypto_lower.review_required is True
    assert wirex_crypto_mixed.review_required is True
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
            date="2025-01-01 00:00:00",
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
            date="2025-01-02 00:00:00",
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
            date="2025-01-03 00:00:00",
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
            date="2025-01-04 00:00:00",
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
            date="2025-01-05 00:00:00",
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
            date="2025-01-01 00:00:00",
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
            date="2025-01-02 00:00:00",
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
            date="2025-01-03 00:00:00",
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
            date="2025-01-01 00:00:00",
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
            date="2025-01-02 00:00:00",
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
            date="2025-01-01 00:00:00",
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
            date="2025-01-01 00:00:00",
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
            date="2025-01-01 00:00:00",
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
            date="2025-01-02 00:00:00",
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
            date="2025-01-01 00:00:00",
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
            date="2025-01-02 00:00:00",
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
            date=f"2025-01-{i:02d} 00:00:00",
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
            disposal_date="2025-01-15 10:00:00",
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


def test_resolve_operator_origin_docstring_describes_hierarchy():
    """resolve_operator_origin docstring should document the DeFi hierarchy and reject taxpayer residence."""
    docstring = resolve_operator_origin.__doc__

    assert docstring is not None
    assert "hierarchy" in docstring.lower() or "interface" in docstring.lower()
    assert "taxpayer" in docstring.lower() or "residence" in docstring.lower()
    assert "never" in docstring.lower() or "reject" in docstring.lower() or "not default" in docstring.lower()


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

    The only exception is GEL, which has a known collision with Gelato Network token
    and is handled via the _CRYPTO_TOKEN_FIAT_COLLISIONS list.
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

    # GEL is the exception due to Gelato token collision
    assert _classify_reward_tax_status("GEL") == RewardTaxClassification.DEFERRED_BY_LAW
