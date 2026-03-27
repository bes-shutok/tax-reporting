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
    _build_swap_lookup,
    _classify_reward_tax_status,
    _derive_chain,
    _filter_immaterial_entries,
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


# =============================================================================
# Unit tests for _build_swap_lookup()
# =============================================================================


def test_build_swap_lookup_from_transaction_history(tmp_path):
    """Extract swap information from Koinly transaction history CSV."""
    tx_history_file = tmp_path / "koinly_2025_transaction_history.csv"

    # Create a transaction history file with exchange (swap) rows
    header = (  # noqa: E501
        "Date,Type,Tag,Sending Wallet,Sent Amount,Sent Currency,Sent Cost Basis,"
        "Receiving Wallet,Received Amount,Received Currency,Received Cost Basis,"
        "Fee Amount,Fee Currency,Gain (EUR),Net Value (EUR),Fee Value (EUR),"
        "TxSrc,TxDest,TxHash,Description"
    )
    csv_content = "\n".join(
        [
            "Transaction report 2025",
            "",
            header,
            '2025-02-16 17:10:42 UTC,exchange,"",Ledger SUI,"26,40816087",SUI,'  # noqa: E501
            '"29,83",Ledger SUI,"25,19665014",HASUI,"29,83","","","","83,05",'
            '"",0xabc,0xdef,tx123',
            '2025-03-01 10:00:00 UTC,exchange,"",ByBit (2),"100,00",USDT,'  # noqa: E501
            '"95,00",ByBit (2),"0,05",ETH,"95,00","","","","95,00","",'
            "0x456,0x789,tx456",
            '2025-03-05 14:30:00 UTC,crypto_deposit,Reward,"","","","",Kraken,'  # noqa: E501
            '"10,00",EUR,"10,00","","","","10,00","","","","",""',
            '2025-03-10 09:15:00 UTC,exchange,"",Ledger SUI,"50,00",SUI,'  # noqa: E501
            '"48,00",Ledger SUI,"48,00",USDT,"48,00","","","","48,00","",'
            "0x111,0x222,tx789",
        ]
    )
    tx_history_file.write_text(csv_content, encoding="utf-8")

    swap_lookup = _build_swap_lookup(tx_history_file)

    # Should extract 3 swap entries (1 exchange row is skipped - it's a crypto_deposit reward)
    # Keys are (wallet, date, received_currency), values are lists of (timestamp, swap_history) tuples
    assert len(swap_lookup) == 3

    # Check SUI -> HASUI swap on 2025-02-16 for Ledger SUI wallet (received currency: HASUI)
    sui_hasui_swaps = swap_lookup[("Ledger SUI", "2025-02-16", "HASUI")]
    assert len(sui_hasui_swaps) == 1
    assert sui_hasui_swaps[0][1] == "SUI → HASUI"  # swap_history string
    # Verify timestamp is preserved for time-ordered matching
    assert sui_hasui_swaps[0][0].year == 2025
    assert sui_hasui_swaps[0][0].month == 2
    assert sui_hasui_swaps[0][0].day == 16
    assert sui_hasui_swaps[0][0].hour == 17
    assert sui_hasui_swaps[0][0].minute == 10

    # Check USDT -> ETH swap on 2025-03-01 for ByBit wallet (normalized, received currency: ETH)
    usdt_eth_swaps = swap_lookup[("ByBit", "2025-03-01", "ETH")]
    assert len(usdt_eth_swaps) == 1
    assert usdt_eth_swaps[0][1] == "USDT → ETH"

    # Check SUI -> USDT swap on 2025-03-10 for Ledger SUI wallet (received currency: USDT)
    sui_usdt_swaps = swap_lookup[("Ledger SUI", "2025-03-10", "USDT")]
    assert len(sui_usdt_swaps) == 1
    assert sui_usdt_swaps[0][1] == "SUI → USDT"


def test_build_swap_lookup_missing_file_returns_empty_dict(tmp_path):
    """Missing transaction history file should return empty lookup dict."""
    missing_file = tmp_path / "nonexistent_transaction_history.csv"
    swap_lookup = _build_swap_lookup(missing_file)

    assert swap_lookup == {}


def test_build_swap_lookup_handles_multiple_swaps_same_date_wallet(tmp_path):
    """Multiple swaps on same date/wallet producing different currencies should be stored separately.

    Each swap is keyed by (wallet, date, received_currency) so that disposals of
    different assets only get their relevant swap history, not all swaps from that day.
    """
    tx_history_file = tmp_path / "koinly_2025_transaction_history.csv"

    csv_content = "\n".join(
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
                '2025-02-16 10:00:00 UTC,exchange,"",Ledger SUI,"10,00",SUI,"10,00",'
                'Ledger SUI,"9,50",HASUI,"10,00","","","","10,00","",0xabc,0xdef,tx1'
            ),
            (
                '2025-02-16 11:00:00 UTC,exchange,"",Ledger SUI,"20,00",USDT,"19,00",'
                'Ledger SUI,"19,00",ETH,"19,00","","","","19,00","",0x123,0x456,tx2'
            ),
        ]
    )
    tx_history_file.write_text(csv_content, encoding="utf-8")

    swap_lookup = _build_swap_lookup(tx_history_file)

    # Swaps producing different currencies should be stored separately
    assert len(swap_lookup) == 2
    # HASUI disposal would get SUI → HASUI
    assert swap_lookup[("Ledger SUI", "2025-02-16", "HASUI")][0][1] == "SUI → HASUI"
    # ETH disposal would get USDT → ETH
    assert swap_lookup[("Ledger SUI", "2025-02-16", "ETH")][0][1] == "USDT → ETH"


def test_build_swap_lookup_skips_non_exchange_transactions(tmp_path):
    """Only Type='exchange' rows should be processed, other types ignored."""
    tx_history_file = tmp_path / "koinly_2025_transaction_history.csv"

    csv_content = "\n".join(
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
                '2025-01-01 00:01:23 UTC,crypto_deposit,Reward,"","","","",ByBit,'
                '"0,25",USDT,"0,24","","","","0,24","","","","",""'
            ),
            ('2025-01-02 10:00:00 UTC,fiat_withdrawal,"",Wirex,"0,97",EUR,"","","","","","","","0,97","","","","",""'),
            (
                '2025-01-03 14:30:00 UTC,transfer,To pool,Ledger SUI,"10,00",HASUI,'
                '"10,00",Ledger SUI,"10,00",HASUI,"10,00","","","","10,00","",0xabc,'
                "0xdef,tx1"
            ),
            (
                '2025-01-04 09:00:00 UTC,exchange,"",ByBit,"100,00",USDT,"95,00",'
                'ByBit,"0,05",ETH,"95,00","","","","95,00","",0x456,0x789,tx2'
            ),
        ]
    )
    tx_history_file.write_text(csv_content, encoding="utf-8")

    swap_lookup = _build_swap_lookup(tx_history_file)

    # Only the exchange transaction should be extracted (key includes received currency)
    assert len(swap_lookup) == 1
    assert swap_lookup[("ByBit", "2025-01-04", "ETH")][0][1] == "USDT → ETH"


def test_build_swap_lookup_normalizes_wallet_names(tmp_path):
    """Wallet names should be normalized using _normalize_platform_name for consistent matching."""
    tx_history_file = tmp_path / "koinly_2025_transaction_history.csv"

    csv_content = "\n".join(
        [
            "Transaction report 2025",
            "",
            (
                "Date,Type,Tag,Sending Wallet,Sent Amount,Sent Currency,Sent Cost Basis,"
                "Receiving Wallet,Received Amount,Received Currency,Received Cost Basis,"
                "Fee Amount,Fee Currency,Gain (EUR),Net Value (EUR),Fee Value (EUR),"
                "TxSrc,TxDest,TxHash,Description"
            ),
            # ByBit (2) should normalize to ByBit
            (
                '2025-02-01 10:00:00 UTC,exchange,"",ByBit (2),"100,00",USDT,"95,00",'
                'ByBit (2),"0,05",ETH,"95,00","","","","95,00","",0x456,0x789,tx1'
            ),
        ]
    )
    tx_history_file.write_text(csv_content, encoding="utf-8")

    swap_lookup = _build_swap_lookup(tx_history_file)

    # Should use normalized wallet name "ByBit" not "ByBit (2)" (key includes received currency)
    assert ("ByBit", "2025-02-01", "ETH") in swap_lookup
    assert swap_lookup[("ByBit", "2025-02-01", "ETH")][0][1] == "USDT → ETH"


def test_capital_gains_entry_includes_swap_history(tmp_path):
    """Integration test: capital gains entries should include swap history from transaction history.

    With time-ordered matching, a disposal only gets swap history from swaps that happened
    AT OR BEFORE the acquisition time. A swap creates a lot, so the swap must happen
    before the lot is acquired (not between acquisition and disposal).
    """
    koinly_dir = tmp_path / "koinly2025"
    koinly_dir.mkdir()

    # Create transaction history with SUI -> HASUI swap at 16:55 (before acquisition)
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

    # Create capital gains report with HASUI disposal at 17:10 (after swap)
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
                        "16/02/2025 17:10",  # Disposal happens AFTER the swap
                        "16/02/2025 17:00",  # Acquisition happens AFTER the swap (swap created the lot)
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
    # Verify the swap history is populated (swap at 16:55, acquisition at 17:00)
    assert entry.token_swap_history == "SUI → HASUI"
    assert entry.asset == "HASUI"
    assert entry.wallet == "Ledger SUI"


def test_capital_gains_entry_empty_swap_history_when_no_match(tmp_path):
    """Capital gains entry should have empty swap history when no matching swap exists."""
    koinly_dir = tmp_path / "koinly2025"
    koinly_dir.mkdir()

    # Create transaction history with a swap on a different date
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
                    '2025-02-16 17:10:42 UTC,exchange,"",Ledger SUI,"26,40816087",SUI,'
                    '"29,83",Ledger SUI,"25,19665014",HASUI,"29,83","","","","83,05","",'
                    "0xabc,0xdef,tx123"
                ),
            ]
        ),
        encoding="utf-8",
    )

    # Create capital gains report with disposal on a different date
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
                        "20/02/2025 10:00",  # Different date - no swap match
                        "01/01/2024 00:00",
                        "HASUI",
                        '"10,00"',
                        '"10,00"',
                        '"15,00"',
                        '"5,00"',
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
    # Should have empty swap history since dates don't match
    assert entry.token_swap_history == ""


def test_capital_gains_swap_history_time_ordered_matching(tmp_path):
    """Swap history should only include swaps that happened AT OR BEFORE acquisition.

    A swap creates a lot, so the swap must happen before the lot is acquired.
    For example, if I swap SUI->HASUI at 14:00, I receive HASUI at 14:00.
    A HASUI lot acquired at 14:05 could have come from that swap, but a HASUI
    lot acquired at 13:55 could not (that would require time travel).
    """
    koinly_dir = tmp_path / "koinly2025"
    koinly_dir.mkdir()

    # Create transaction history with two swaps on the same day at different times
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
                # Swap at 14:00: SUI -> HASUI (creates HASUI lot)
                (
                    '2025-05-22 14:00:00 UTC,exchange,"",Ledger SUI,"100,00",SUI,'
                    '"95,00",Ledger SUI,"95,00",HASUI,"95,00","","","","95,00","",'
                    "0xabc,0xdef,tx1"
                ),
                # Swap at 16:00: SSUI -> SUI (creates SUI lot)
                (
                    '2025-05-22 16:00:00 UTC,exchange,"",Ledger SUI,"50,00",SSUI,'
                    '"48,00",Ledger SUI,"48,00",SUI,"48,00","","","","48,00","",'
                    "0x123,0x456,tx2"
                ),
            ]
        ),
        encoding="utf-8",
    )

    # Create capital gains report with two disposals at different times
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
                # Disposal 1 at 15:00: HASUI acquired at 14:05 (after first swap at 14:00)
                # This lot could have come from the 14:00 swap
                ",".join(
                    [
                        "22/05/2025 15:00",
                        "22/05/2025 14:05",  # Acquired after first swap at 14:00
                        "HASUI",
                        '"10,00"',
                        '"10,00"',
                        '"15,00"',
                        '"5,00"',
                        "",
                        "Ledger SUI",
                        "Short term",
                    ]
                ),
                # Disposal 2 at 17:00: SUI acquired at 16:05 (after second swap at 16:00)
                # This lot could have come from the 16:00 swap
                ",".join(
                    [
                        "22/05/2025 17:00",
                        "22/05/2025 16:05",  # Acquired after second swap at 16:00
                        "SUI",
                        '"5,00"',
                        '"5,00"',
                        '"7,00"',
                        '"2,00"',
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
    assert len(report.capital_entries) == 2

    # First disposal at 15:00: should get SUI -> HASUI swap (14:00 <= 14:05)
    hasui_entry = [e for e in report.capital_entries if e.asset == "HASUI"][0]
    assert hasui_entry.token_swap_history == "SUI → HASUI"

    # Second disposal at 17:00: should get SSUI -> SUI swap (16:00 <= 16:05)
    sui_entry = [e for e in report.capital_entries if e.asset == "SUI"][0]
    assert sui_entry.token_swap_history == "SSUI → SUI"


def test_capital_gains_swap_history_disposal_upper_bound_filter(tmp_path):
    """Swap history should NOT include swaps that occurred AFTER acquisition.

    Regression test for: swaps bleeding onto capital entries acquired before
    the swap occurred. This uses the SAME asset for both swap and capital entry
    to ensure the asset key doesn't mask the bug.

    Scenario:
    - SUI disposal at 15:00, acquired at 14:05
    - Swap at 16:00: some other asset -> SUI (affects SUI's swap history)
    - Expected: empty swap history (the swap happened after acquisition)

    A swap creates a lot, so a swap at 16:00 cannot be the source of a lot
    that was acquired at 14:05.
    """
    koinly_dir = tmp_path / "koinly2025"
    koinly_dir.mkdir()

    # Create capital gains report with SUI disposal BEFORE the swap
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
                # SUI disposal at 15:00, acquired at 14:05
                ",".join(
                    [
                        "22/05/2025 15:00",
                        "22/05/2025 14:05",
                        "SUI",
                        '"10,00"',
                        '"10,00"',
                        '"15,00"',
                        '"5,00"',
                        "",
                        "Ledger SUI",
                        "Short term",
                    ]
                ),
            ]
        ),
        encoding="utf-8",
    )

    # Create transaction history with a swap that affects SUI AFTER the disposal
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
                # Swap at 16:00: some other asset -> SUI (AFTER the disposal at 15:00)
                (
                    '2025-05-22 16:00:00 UTC,exchange,"",Ledger SUI,"100,00",HASUI,'
                    '"95,00",Ledger SUI,"95,00",SUI,"95,00","","","","95,00","",'
                    "0xabc,0xdef,tx1"
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
    # Should have empty swap history since the swap happened after disposal
    assert entry.token_swap_history == "", (
        f"Expected empty swap history for disposal before swap, got: {entry.token_swap_history}"
    )


def test_capital_gains_swap_history_same_minute_matching(tmp_path):
    """Swap history should match swaps in the same minute as the acquisition.

    Koinly capital gains reports truncate acquisition times to minute precision
    (e.g., "22:01" becomes "22:01:00"), while transaction history has actual
    seconds (e.g., "22:01:07 UTC"). A swap at 22:01:07 SHOULD match a lot
    acquired at 22:01 (same minute), because the swap happens at 22:01:07
    and when truncated to minute precision (22:01:00), it is at or before
    the acquisition time (22:01:00).

    Regression test for: same-minute swaps being dropped due to full datetime
    comparison (22:01:07 > 22:01:00). The code truncates both to minute precision
    for comparison.
    """
    koinly_dir = tmp_path / "koinly2025"
    koinly_dir.mkdir()

    # Create transaction history with a swap at 22:01:07
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
                # Swap at 22:01:07: XSTRK -> STRK
                (
                    '2025-02-23 22:01:07 UTC,exchange,"",Starknet (STRK),"188,00",XSTRK,'
                    '"45,82",Starknet (STRK),"122,67",STRK,"45,82","","","","26,91","",'
                    "0xabc,0xdef,tx1"
                ),
            ]
        ),
        encoding="utf-8",
    )

    # Create capital gains report with disposal at 22:01 (truncated to minute)
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
                # Disposal at 22:01 (truncated to minute, becomes 22:01:00)
                # Use larger amounts to avoid immateriality filter (gain >= 1 EUR)
                ",".join(
                    [
                        "23/02/2025 22:01",
                        "23/02/2025 22:01",
                        "STRK",
                        '"10,00"',
                        '"5,00"',
                        '"15,00"',
                        '"10,00"',
                        "",
                        "Starknet (STRK)",
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
    # Should have swap history since swap at 22:01:07 matches disposal at 22:01
    assert entry.token_swap_history == "XSTRK → STRK"


def test_capital_gains_swap_history_cross_day_near_midnight_with_time_window(tmp_path):
    """Cross-day near-midnight swaps should use a 1-hour window around acquisition.

    Regression test for: swaps from much earlier in the day being incorrectly
    included for near-midnight cross-day lots.

    Scenario:
    - Swap at 09:00: USDT -> ETH (creates ETH lot at 09:00)
    - Swap at 23:00: USDT -> ETH (creates ETH lot at 23:00)
    - ETH lot acquired at 23:00, sold at 00:05 next day (near-midnight)
    - Expected: only the 23:00 swap (within 1-hour window of 23:00), not the 09:00 swap

    The 1-hour window prevents swaps from earlier in the day from being
    incorrectly attributed to a near-midnight lot.
    """
    koinly_dir = tmp_path / "koinly2025"
    koinly_dir.mkdir()

    # Create transaction history with two swaps on the same day
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
                # Swap at 09:00: USDT -> ETH
                (
                    '2025-02-16 09:00:00 UTC,exchange,"",Kraken,"100,00",USDT,'
                    '"95,00",Kraken,"95,00",ETH,"95,00","","","","95,00","",'
                    "0xabc,0xdef,tx1"
                ),
                # Swap at 23:00: USDT -> ETH (creates the lot we're testing)
                (
                    '2025-02-16 23:00:00 UTC,exchange,"",Kraken,"100,00",USDT,'
                    '"95,00",Kraken,"95,00",ETH,"95,00","","","","95,00","",'
                    "0x123,0x456,tx2"
                ),
            ]
        ),
        encoding="utf-8",
    )

    # Create capital gains report with cross-day near-midnight disposal
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
                # Cross-day near-midnight: acquired at 23:00, sold at 00:05
                ",".join(
                    [
                        "17/02/2025 00:05",  # Disposal early morning
                        "16/02/2025 23:00",  # Acquisition late night (near-midnight)
                        "ETH",
                        '"10,00"',
                        '"10,00"',
                        '"15,00"',
                        '"5,00"',
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
    # Should only get the 23:00 swap (within 1-hour window), not the 09:00 swap
    assert entry.token_swap_history == "USDT → ETH"


def test_capital_gains_swap_history_same_day_most_recent_only(tmp_path):
    """Same-day swap history should only include the most recent swap before acquisition.

    Regression test for: multiple same-day swaps producing the same asset causing
    over-matching (all prior swaps included instead of just the most recent).

    Scenario:
    - Swap at 10:00: USDT -> ETH (creates ETH lot at 10:00)
    - Swap at 13:00: BTC -> ETH (creates another ETH lot at 13:00)
    - ETH lot acquired at 13:05, sold at 17:00
    - Expected: only "BTC -> ETH" (most recent before acquisition), not "USDT -> ETH; BTC -> ETH"

    A swap creates a lot at the moment of the swap. A lot acquired at 13:05 could
    only have come from the 13:00 swap (or later), not the 10:00 swap which created
    a different lot. Including all prior swaps creates misleading provenance.
    """
    koinly_dir = tmp_path / "koinly2025"
    koinly_dir.mkdir()

    # Create transaction history with two swaps producing the SAME asset (ETH)
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
                # Swap at 10:00: USDT -> ETH
                (
                    '2025-05-22 10:00:00 UTC,exchange,"",Kraken,"100,00",USDT,'
                    '"95,00",Kraken,"95,00",ETH,"95,00","","","","95,00","",'
                    "0xabc,0xdef,tx1"
                ),
                # Swap at 13:00: BTC -> ETH (creates the lot we're testing)
                (
                    '2025-05-22 13:00:00 UTC,exchange,"",Kraken,"50,00",BTC,'
                    '"48,00",Kraken,"48,00",ETH,"48,00","","","","48,00","",'
                    "0x123,0x456,tx2"
                ),
            ]
        ),
        encoding="utf-8",
    )

    # Create capital gains report with ETH acquired at 13:05 (after second swap)
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
                # ETH disposal at 17:00, acquired at 13:05
                ",".join(
                    [
                        "22/05/2025 17:00",
                        "22/05/2025 13:05",  # Acquired after second swap at 13:00
                        "ETH",
                        '"10,00"',
                        '"10,00"',
                        '"15,00"',
                        '"5,00"',
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
    # Should only get the most recent swap (13:00), not both swaps
    assert entry.token_swap_history == "BTC → ETH", (
        f"Expected only the most recent swap before acquisition, got: {entry.token_swap_history}"
    )


def test_build_swap_lookup_uses_receiving_wallet_as_key(tmp_path):
    """Swap lookup should use receiving wallet as the key for matching with capital gains."""
    tx_history_file = tmp_path / "koinly_2025_transaction_history.csv"

    csv_content = "\n".join(
        [
            "Transaction report 2025",
            "",
            (
                "Date,Type,Tag,Sending Wallet,Sent Amount,Sent Currency,Sent Cost Basis,"
                "Receiving Wallet,Received Amount,Received Currency,Received Cost Basis,"
                "Fee Amount,Fee Currency,Gain (EUR),Net Value (EUR),Fee Value (EUR),"
                "TxSrc,TxDest,TxHash,Description"
            ),
            # Sending from empty wallet to Ledger SUI
            (
                '2025-02-16 10:00:00 UTC,exchange,""," ","100,00",USDT,"95,00",'
                'Ledger SUI,"95,00",ETH,"95,00","","","","95,00","",0xabc,0xdef,tx1'
            ),
        ]
    )
    tx_history_file.write_text(csv_content, encoding="utf-8")

    swap_lookup = _build_swap_lookup(tx_history_file)

    # Should use receiving wallet "Ledger SUI" as the key (with received currency ETH)
    assert ("Ledger SUI", "2025-02-16", "ETH") in swap_lookup
    assert swap_lookup[("Ledger SUI", "2025-02-16", "ETH")][0][1] == "USDT → ETH"


def test_aggregate_capital_entries_joins_swap_history(tmp_path):
    """Aggregation should join swap history strings from multiple entries."""
    entries = [
        _make_entry(
            disposal_date="2025-02-16 10:00:00",
            wallet="Ledger SUI",
            platform="Ledger SUI",
            token_swap_history="SUI → HASUI",  # noqa: S106
        ),
        _make_entry(
            disposal_date="2025-02-16 10:00:00",
            wallet="Ledger SUI",
            platform="Ledger SUI",
            token_swap_history="SUI → USDT",  # noqa: S106
        ),
        _make_entry(
            disposal_date="2025-02-16 10:00:00",
            wallet="Ledger SUI",
            platform="Ledger SUI",
            token_swap_history="",  # Empty swap history
        ),
    ]

    result = _aggregate_capital_entries(entries)

    assert len(result) == 1
    # Swap history should be joined and deduplicated
    assert result[0].token_swap_history == "SUI → HASUI; SUI → USDT"


def test_capital_gains_swap_history_only_for_same_day_acquisition(tmp_path):
    """Swap history should only be assigned to lots acquired on the same day as the swap.

    Regression test for: same-day swaps bleeding onto older lots.
    Example: A LINK lot acquired on 2022-09-30, disposed on 2025-04-07,
    should NOT get "BTC → LINK" swap history from same-day 2025-04-07 swaps.
    Those swaps produced NEW LINK tokens on 2025-04-07, not the 2022-acquired lot.

    A swap creates a lot, so the swap must happen at or before the lot is acquired.
    """
    koinly_dir = tmp_path / "koinly2025"
    koinly_dir.mkdir()

    # Create transaction history with BTC -> LINK swap on 2025-04-07
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
                    '2025-04-07 06:40:00 UTC,exchange,"",Kraken,"0,00189000",BTC,'
                    '"114,94",Kraken,"13,59712230",LINK,"114,94","","","","129,22","",'
                    "0xabc,0xdef,tx1"
                ),
            ]
        ),
        encoding="utf-8",
    )

    # Create capital gains report with two LINK disposals on 2025-04-07
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
                # Older lot: acquired 2022-09-30, disposed 2025-04-07
                # Should NOT get swap history (different acquisition day)
                ",".join(
                    [
                        "07/04/2025 07:58",
                        "30/09/2022 09:14",
                        "LINK",
                        '"0,93585000"',
                        '"7,56"',
                        '"8,83"',
                        '"1,27"',
                        "Fee",
                        "Kraken",
                        "Long term",
                    ]
                ),
                # Same-day lot: acquired and disposed on 2025-04-07
                # The swap at 06:40 creates this lot, acquired at 06:45
                ",".join(
                    [
                        "07/04/2025 07:00",
                        "07/04/2025 06:45",  # Acquired after the swap at 06:40
                        "LINK",
                        '"5,00"',
                        '"100,00"',
                        '"120,00"',
                        '"20,00"',
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
    assert len(report.capital_entries) == 2

    # Find the older lot (2022-acquired) and same-day lot (2025-acquired)
    older_lot = [e for e in report.capital_entries if e.holding_period == "Long term"][0]
    same_day_lot = [e for e in report.capital_entries if e.holding_period == "Short term"][0]

    # Older lot should NOT have swap history (acquired on different day)
    assert older_lot.token_swap_history == "", (
        f"Older lot (acquired {older_lot.acquisition_date}) should not have swap history from 2025-04-07 swaps"
    )

    # Same-day lot SHOULD have swap history (swap at 06:40, acquisition at 06:45)
    assert same_day_lot.token_swap_history == "BTC → LINK", (
        f"Same-day lot (acquired {same_day_lot.acquisition_date}) should have swap history from 2025-04-07 swaps"
    )


def test_capital_gains_swap_history_near_midnight_cross_day(tmp_path):
    """Swap history should be preserved for near-midnight cross-day disposals.

    Regression test for: lots acquired at 23:55 and disposed at 00:05 losing swap history.
    When acquisition and disposal span midnight but are close together (within a few hours),
    the lot was clearly acquired from same-day swaps and should preserve swap history.

    Example: SUI → HASUI swap at 23:55, disposal of HASUI at 00:05 (10 minutes later).
    """
    koinly_dir = tmp_path / "koinly2025"
    koinly_dir.mkdir()

    # Create transaction history with SUI -> HASUI swap near midnight (23:55)
    (koinly_dir / "koinly_2025_transaction_history.csv").write_text(
        "\n".join(
            [
                "Transaction history 2025",
                "",
                "Date,Type,Tag,Sending Wallet,Sent Amount,Sent Currency,Sent Cost Basis,Receiving Wallet,Received Amount,Received Currency,Received Cost Basis,Fee,Fee Currency,Net Worth,Net Worth Currency,Order Hash,Transaction Hash,Label",  # noqa: E501
                '2025-02-16 23:55:00 UTC,exchange,"",Ledger SUI,"10,00",SUI,"10,00",Ledger SUI,"10,00",HASUI,"10,00",0,,"0,0",,0x111,0x222',  # noqa: E501
            ]
        ),
        encoding="utf-8",
    )

    # Create capital gains with disposal just after midnight (00:05)
    # Acquisition is at 23:55 (same day as swap), disposal at 00:05 (next day)
    (koinly_dir / "koinly_2025_capital_gains_report_Ledger SUI.csv").write_text(
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
                # Near-midnight disposal: acquired 23:55, disposed 00:05 (10 minutes later)
                # Should get swap history (near-midnight cross-day case)
                ",".join(
                    [
                        "17/02/2025 00:05",
                        "16/02/2025 23:55",
                        "HASUI",
                        '"10,00"',
                        '"10,00"',
                        '"12,00"',
                        '"2,00"',
                        "",
                        "Ledger SUI",
                        "Short term",
                    ]
                ),
            ]
        ),
        encoding="utf-8",
    )

    # Create empty income and holdings files
    (koinly_dir / "koinly_2025_income_report_Ledger SUI.csv").write_text(
        "\n".join(
            [
                "Income report 2025",
                "",
                "Date,Type,Tag,Asset,Amount,Price,Value,Currency,Notes,Wallet Name",
            ]
        ),
        encoding="utf-8",
    )

    (koinly_dir / "koinly_2025_holdings_report_Ledger SUI.csv").write_text(
        "\n".join(
            [
                "Balances as at 31/12/2025 23:59",
                "",
                "Wallet,Asset,Amount,Price,Value,Currency",
            ]
        ),
        encoding="utf-8",
    )

    report = load_koinly_crypto_report(koinly_dir)

    assert report is not None
    assert len(report.capital_entries) == 1

    entry = report.capital_entries[0]
    # Should have swap history (near-midnight cross-day case: 23:55 -> 00:05)
    assert entry.token_swap_history == "SUI → HASUI", (
        f"Near-midnight disposal (acquired {entry.acquisition_date}, "
        f"disposed {entry.disposal_date}) should have swap history from 23:55 swap"
    )


def test_capital_gains_swap_history_near_midnight_edge_case_21_59(tmp_path):
    """Swap history should be preserved for near-midnight cross-day disposals at 21:59.

    Regression test for: lots acquired at 21:59 (before the 22:00 threshold) and
    disposed at 00:05 losing swap history due to overly restrictive acquisition hour
    constraint. The total span is still short (< 6 hours) and disposal is early morning,
    so this should be considered a near-midnight cross-day case.

    Example: SUI -> HASUI swap at 21:59, disposal of HASUI at 00:05 (~2 hours later).
    """
    koinly_dir = tmp_path / "koinly2025"
    koinly_dir.mkdir()

    # Create transaction history with SUI -> HASUI swap at 21:59 (before 22:00 threshold)
    (koinly_dir / "koinly_2025_transaction_history.csv").write_text(
        "\n".join(
            [
                "Transaction history 2025",
                "",
                "Date,Type,Tag,Sending Wallet,Sent Amount,Sent Currency,Sent Cost Basis,Receiving Wallet,Received Amount,Received Currency,Received Cost Basis,Fee,Fee Currency,Net Worth,Net Worth Currency,Order Hash,Transaction Hash,Label",  # noqa: E501
                '2025-02-16 21:59:00 UTC,exchange,"",Ledger SUI,"10,00",SUI,"10,00",Ledger SUI,"10,00",HASUI,"10,00",0,,"0,0",,0x111,0x222',  # noqa: E501
            ]
        ),
        encoding="utf-8",
    )

    # Create capital gains with disposal just after midnight (00:05)
    # Acquisition is at 21:59 (same day as swap), disposal at 00:05 (next day)
    (koinly_dir / "koinly_2025_capital_gains_report_Ledger SUI.csv").write_text(
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
                # Edge case: acquired 21:59, disposed 00:05 (~2 hours later)
                # Should get swap history (near-midnight cross-day case even though 21:59 < 22:00)
                ",".join(
                    [
                        "17/02/2025 00:05",
                        "16/02/2025 21:59",
                        "HASUI",
                        '"10,00"',
                        '"10,00"',
                        '"12,00"',
                        '"2,00"',
                        "",
                        "Ledger SUI",
                        "Short term",
                    ]
                ),
            ]
        ),
        encoding="utf-8",
    )

    # Create empty income and holdings files
    (koinly_dir / "koinly_2025_income_report_Ledger SUI.csv").write_text(
        "\n".join(
            [
                "Income report 2025",
                "",
                "Date,Type,Tag,Asset,Amount,Price,Value,Currency,Notes,Wallet Name",
            ]
        ),
        encoding="utf-8",
    )

    (koinly_dir / "koinly_2025_holdings_report_Ledger SUI.csv").write_text(
        "\n".join(
            [
                "Balances as at 31/12/2025 23:59",
                "",
                "Wallet,Asset,Amount,Price,Value,Currency",
            ]
        ),
        encoding="utf-8",
    )

    report = load_koinly_crypto_report(koinly_dir)

    assert report is not None
    assert len(report.capital_entries) == 1

    entry = report.capital_entries[0]
    # Should have swap history (near-midnight cross-day case: 21:59 -> 00:05)
    assert entry.token_swap_history == "SUI → HASUI", (
        f"Near-midnight disposal (acquired {entry.acquisition_date}, "
        f"disposed {entry.disposal_date}) should have swap history from 21:59 swap"
    )
