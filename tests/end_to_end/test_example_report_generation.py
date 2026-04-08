"""End-to-end test verifying the repository can generate a report from committed example inputs.

The example data under resources/source/example/ is fully synthetic and exercises every
major feature: shares capital gains, dividends, rollover/leftover integration, crypto
capital events, crypto rewards, and blank Token origin after legacy removal.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import openpyxl
import pytest

from shares_reporting.application.crypto_reporting import (
    RewardTaxClassification,
    load_koinly_crypto_report,
)
from shares_reporting.application.extraction import parse_ib_export_all
from shares_reporting.application.persisting import generate_tax_report
from shares_reporting.application.transformation import calculate_fifo_gains
from shares_reporting.domain.collections import TradeCyclePerCompany

EXAMPLE_DIR = Path("resources", "source", "example")
EXAMPLE_IB_EXPORT = EXAMPLE_DIR / "ib_export.csv"
EXAMPLE_KOINLY_DIR = EXAMPLE_DIR / "koinly2024"


@pytest.mark.e2e
def test_example_ib_export_parses_successfully():
    ib_data = parse_ib_export_all(EXAMPLE_IB_EXPORT)
    assert len(ib_data.trade_cycles) >= 2
    assert len(ib_data.dividend_income) >= 2


@pytest.mark.e2e
def test_example_leftover_integrated():
    ib_data = parse_ib_export_all(EXAMPLE_IB_EXPORT)
    leftover_path = EXAMPLE_DIR / "shares-leftover.csv"
    assert leftover_path.exists()
    acme_cycle = next(
        (
            cycle
            for currency_company, cycle in ib_data.trade_cycles.items()
            if currency_company.currency.currency == "USD" and currency_company.company.ticker == "ACME"
        ),
        None,
    )
    assert acme_cycle is not None
    assert len(acme_cycle.bought) == 2
    leftover_buy = acme_cycle.bought[0]
    assert leftover_buy.quantity == 20
    assert leftover_buy.action.price == Decimal("15.00")


@pytest.mark.e2e
def test_example_shares_capital_gains():
    ib_data = parse_ib_export_all(EXAMPLE_IB_EXPORT)
    leftover_trades: TradeCyclePerCompany = {}
    capital_gains = {}
    calculate_fifo_gains(ib_data.trade_cycles, leftover_trades, capital_gains)
    total_cg_lines = sum(len(lines) for lines in capital_gains.values())
    assert total_cg_lines >= 2
    assert len(leftover_trades) >= 1


@pytest.mark.e2e
def test_example_crypto_report_loads():
    crypto = load_koinly_crypto_report(EXAMPLE_KOINLY_DIR)
    assert crypto is not None
    assert len(crypto.capital_entries) >= 2
    assert len(crypto.reward_entries) >= 2


@pytest.mark.e2e
def test_example_crypto_token_origin_is_blank():
    crypto = load_koinly_crypto_report(EXAMPLE_KOINLY_DIR)
    assert crypto is not None
    for entry in crypto.capital_entries:
        assert entry.token_swap_history == "", (
            f"Token origin should be blank for {entry.asset}, got '{entry.token_swap_history}'"
        )


@pytest.mark.e2e
def test_example_full_pipeline_generates_excel(tmp_path: Path):
    ib_data = parse_ib_export_all(EXAMPLE_IB_EXPORT)
    leftover_trades: TradeCyclePerCompany = {}
    capital_gains = {}
    calculate_fifo_gains(ib_data.trade_cycles, leftover_trades, capital_gains)
    crypto = load_koinly_crypto_report(EXAMPLE_KOINLY_DIR)
    output_path = tmp_path / "extract.xlsx"
    crypto_sheet_created = generate_tax_report(
        output_path,
        capital_gains,
        ib_data.dividend_income,
        crypto_tax_report=crypto,
    )
    assert crypto_sheet_created
    assert output_path.exists()
    wb = openpyxl.load_workbook(output_path)
    assert "Reporting" in wb.sheetnames
    assert "Crypto" in wb.sheetnames
    wb.close()


@pytest.mark.e2e
def test_example_crypto_sheet_has_blank_token_origin(tmp_path: Path):
    ib_data = parse_ib_export_all(EXAMPLE_IB_EXPORT)
    leftover_trades: TradeCyclePerCompany = {}
    capital_gains = {}
    calculate_fifo_gains(ib_data.trade_cycles, leftover_trades, capital_gains)
    crypto = load_koinly_crypto_report(EXAMPLE_KOINLY_DIR)
    output_path = tmp_path / "extract.xlsx"
    generate_tax_report(output_path, capital_gains, ib_data.dividend_income, crypto_tax_report=crypto)
    wb = openpyxl.load_workbook(output_path)
    ws = wb["Crypto"]
    token_origin_col = None
    header_row_num = None
    for row in ws.iter_rows(min_row=1, max_row=20):
        for cell in row:
            if cell.value == "Token origin":
                token_origin_col = cell.column
                header_row_num = cell.row
                break
        if token_origin_col:
            break
    assert token_origin_col is not None, "Token origin column header not found"
    assert header_row_num is not None
    checked = 0
    for row in ws.iter_rows(min_row=header_row_num + 1, max_row=ws.max_row):
        origin_val = row[token_origin_col - 1].value if token_origin_col <= len(row) else None
        asset = row[2].value if len(row) > 2 else None
        if asset and isinstance(asset, str) and asset.strip():
            assert origin_val is None or origin_val == "", (
                f"Token origin should be blank for asset {asset}, got {origin_val!r}"
            )
            checked += 1
    assert checked >= 1, "No capital gains data rows found to verify"
    wb.close()


@pytest.mark.e2e
def test_example_data_is_synthetic():
    ib_content = EXAMPLE_IB_EXPORT.read_text()
    assert "Demo Taxpayer" in ib_content
    assert "Demo Broker LLC" in ib_content
    assert "U9999999" in ib_content
    koinly_capital = sorted(EXAMPLE_KOINLY_DIR.glob("*capital_gains_report*.csv"))[0]
    koinly_filename = koinly_capital.name
    assert "xY9kLm2pQr" in koinly_filename
    koinly_income = sorted(EXAMPLE_KOINLY_DIR.glob("*income_report*.csv"))[0]
    assert "aB3cDn5oEf" in koinly_income.name


def _count_csv_data_rows(path: Path) -> int:
    """Count data rows in a Koinly CSV (skipping title, blank, and header lines)."""
    with path.open() as f:
        return max(0, sum(1 for line in f if line.strip()) - 2)


@pytest.mark.e2e
def test_example_crypto_source_has_high_volume_rows():
    capital_csv = sorted(EXAMPLE_KOINLY_DIR.glob("*capital_gains_report*.csv"))[0]
    income_csv = sorted(EXAMPLE_KOINLY_DIR.glob("*income_report*.csv"))[0]
    capital_rows = _count_csv_data_rows(capital_csv)
    income_rows = _count_csv_data_rows(income_csv)
    total_rows = capital_rows + income_rows
    assert total_rows >= 1000, (
        f"Example crypto source should contain at least 1000 rows, got {total_rows} "
        f"(capital={capital_rows}, income={income_rows})"
    )


@pytest.mark.e2e
def test_example_crypto_capital_gains_aggregate_to_few_lines():
    crypto = load_koinly_crypto_report(EXAMPLE_KOINLY_DIR)
    assert crypto is not None
    assert len(crypto.capital_entries) <= 5, (
        f"Aggregated capital entries should be at most 5, got {len(crypto.capital_entries)}"
    )
    capital_csv = sorted(EXAMPLE_KOINLY_DIR.glob("*capital_gains_report*.csv"))[0]
    raw_capital_rows = _count_csv_data_rows(capital_csv)
    compression_ratio = raw_capital_rows / len(crypto.capital_entries)
    assert compression_ratio >= 50, (
        f"Capital gains compression ratio should be >= 50x, got {compression_ratio:.1f}x "
        f"({raw_capital_rows} raw -> {len(crypto.capital_entries)} aggregated)"
    )
    total_gain = sum(float(e.gain_loss_eur) for e in crypto.capital_entries)
    assert 100 <= total_gain <= 200, (
        f"Total capital gains should be modest (100-200 EUR), got {total_gain:.2f} EUR"
    )


@pytest.mark.e2e
def test_example_crypto_rewards_are_many_but_classified():
    crypto = load_koinly_crypto_report(EXAMPLE_KOINLY_DIR)
    assert crypto is not None
    assert len(crypto.reward_entries) == 160, (
        f"Raw reward entries should be exactly 160, got {len(crypto.reward_entries)}"
    )
    total_reward_value = sum(float(e.value_eur) for e in crypto.reward_entries)
    assert total_reward_value <= 1000, (
        f"Total reward value should be modest (<1000 EUR), got {total_reward_value:.2f} EUR"
    )
    deferred = [e for e in crypto.reward_entries if e.tax_classification == RewardTaxClassification.DEFERRED_BY_LAW]
    taxable = [e for e in crypto.reward_entries if e.tax_classification == RewardTaxClassification.TAXABLE_NOW]
    assert len(taxable) == 10, (
        f"Example data should have exactly 10 taxable-now (fiat-denominated) rewards, got {len(taxable)}"
    )
    assert len(deferred) == 150, (
        f"Example data should have exactly 150 deferred-by-law (crypto-denominated) rewards, got {len(deferred)}"
    )
    assert len(taxable) + len(deferred) == len(crypto.reward_entries), (
        f"Taxable ({len(taxable)}) + deferred ({len(deferred)}) should equal total ({len(crypto.reward_entries)})"
    )


@pytest.mark.e2e
def test_example_high_volume_crypto_sheet_is_compact(tmp_path: Path):
    ib_data = parse_ib_export_all(EXAMPLE_IB_EXPORT)
    leftover_trades: TradeCyclePerCompany = {}
    capital_gains = {}
    calculate_fifo_gains(ib_data.trade_cycles, leftover_trades, capital_gains)
    crypto = load_koinly_crypto_report(EXAMPLE_KOINLY_DIR)
    output_path = tmp_path / "extract.xlsx"
    generate_tax_report(output_path, capital_gains, ib_data.dividend_income, crypto_tax_report=crypto)
    wb = openpyxl.load_workbook(output_path)
    ws = wb["Crypto"]
    asset_col = None
    for row in ws.iter_rows(min_row=1, max_row=20):
        for cell in row:
            if cell.value == "Asset":
                asset_col = cell.column
                break
        if asset_col:
            break
    assert asset_col is not None, "Asset column header not found in Crypto sheet"
    capital_data_rows = 0
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row):
        first_val = row[0].value if row else None
        if isinstance(first_val, str) and "CAPITAL GAINS STATISTICS" in first_val:
            break
        asset_val = row[asset_col - 1].value if asset_col <= len(row) else None
        if asset_val and isinstance(asset_val, str) and asset_val.strip():
            capital_data_rows += 1
    assert capital_data_rows <= 10, (
        f"Capital gains data rows in Crypto sheet should be at most 10, got {capital_data_rows}"
    )
    wb.close()
