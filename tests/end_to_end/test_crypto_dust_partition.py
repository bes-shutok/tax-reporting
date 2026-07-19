"""End-to-end data-trace verification for the CRG-021 reward dust partition.

Verifies (per docs/history/plans/2026-07-18-crypto-dust-partition-fee-skip.md
Task 7) that the committed synthetic Koinly 2025 example fixture in
``resources/source/example/2025/koinly/dust-partition/`` drives the production
``load_koinly_crypto_report`` -> ``generate_tax_report`` pipeline such that the
Crypto Supplementary tab renders the per-(asset, wallet) dust summary block for
zero-value taxable-now rewards on priced assets, while zero-value rewards on
assets with NO priced row anywhere in the export keep their per-row ``YES``
review flag in the Section 2 detail table.

These are full-pipeline pins of the r9 has-any-priced-row discriminator
(CRG-021): they exercise ``write_crypto_supplementary_sheet`` (Tasks 4 + 6)
end-to-end through the same ``generate_tax_report`` entry point the production
CLI uses. There is NO RED phase for Task 7 because the production pipeline is
already GREEN from Tasks 2/4/6; the e2e tests pass directly.

Fixture asset choice. The plan's Task 7 prose names ``BTC`` (priced asset) and
``OSBGT`` (unpriced asset) as the motivating examples, mirroring the unit
fixtures in ``test_crypto_supplementary_sheet.py``. The e2e fixture cannot use
those tickers literally because the production ``_classify_reward_tax_status``
classifier routes every crypto-denominated ticker (BTC and OSBGT included) to
``DEFERRED_BY_LAW``; the dust partition operates exclusively on
``taxable_now_entries``, so only fiat-denominated rewards can reach it through
the full pipeline. The fixture therefore uses the fiat currency codes ``EUR``
(the priced asset, the e2e-realizable analog of the unit fixture's BTC) and
``USD`` (the unpriced asset, the e2e-realizable analog of OSBGT). The dust
discriminator (``value_eur > 0`` anywhere in ``reward_entries``) is exercised
identically regardless of the ticker spelling, which is what Invariant 2
asserts.

Fixture contents (one scenario, three income rows + one CG USD row):
- Income row 1: ``EUR`` priced (``Value (EUR) = 3,00``, Wirex) -> TAXABLE_NOW,
  Detail path (priced asset, not zero).
- Income row 2: ``EUR`` zero-value (``Value (EUR) = 0,00``, Wirex) ->
  TAXABLE_NOW, Dust path (EUR has the priced row above; zero collapses to the
  per-(EUR, Wirex) dust summary line).
- Income row 3: ``USD`` zero-value (``Value (EUR) = 0,00``, Wirex) ->
  TAXABLE_NOW, per-row YES path (USD has NO priced income row anywhere; the
  priced USD CG row keeps USD in ``known_assets`` so the zero-value income
  reward is ``is_known`` and not skipped at parse, but the dust discriminator
  only consults ``reward_entries``, where USD has no priced row).
- CG row: one ``USD`` disposal (cost 5,00, proceeds 6,00, gain 1,00, Wirex) so
  USD enters ``known_assets`` via the CG scan in ``_collect_known_asset_tickers``
  and the zero-value USD income reward is retained (not routed to
  ``skipped_zero_value_tokens``).

Wallets are limited to ``SYNTHETIC_WALLET_ALLOWLIST`` (``Wirex``); all
TxHash/TxSrc/TxDest cells empty (synthetic-data hygiene, scoped by
``test_example_data_is_synthetic``).
"""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

import openpyxl
import pytest

from tax_reporting.application.crypto_reporting import (
    RewardTaxClassification,
    load_koinly_crypto_report,
)
from tax_reporting.application.persisting import generate_tax_report
from tests.conftest import build_koinly_jurisdiction

pytestmark = pytest.mark.e2e

_FIXTURE_DIR = Path("resources/source/example/2025/koinly/dust-partition")

# Phase E Task 5: mirror test_example_report_generation._EXAMPLE_JURISDICTION.
# ``exclude_loan_repayment_gains=False`` avoids the loan-asset FIFO rebuild
# (no loan-affected assets in this fixture; the rebuild would emit a benign
# warning but no entries). Income-code classification stays ON so the
# taxable-now EUR/USD interest rewards resolve to the official Tabela V E25
# code (a mandatory Quadro 8A field; without it the aggregation step
# fail-closes).
_JURISDICTION = build_koinly_jurisdiction(exclude_loan_repayment_gains=False)

# Fixture-derived constants (CRG-021 Invariant 1: the partition is a view; the
# expected values are derived directly from the committed fixture rows, NOT
# from a "partition-disabled baseline" which does not exist).
_PRICED_ASSET = "EUR"
_UNPRICED_ASSET = "USD"
_PRICED_VALUE_EUR = Decimal("3.00")
# CG row that keeps USD in known_assets (proceeds > 0 in the CG scan).
_CG_USD_PROCEEDS_EUR = Decimal("6.00")
_EXPECTED_REWARD_TOTAL_EUR = _PRICED_VALUE_EUR  # 3.00 + 0.00 + 0.00
_EXPECTED_REWARD_ENTRIES_LEN = 3  # EUR priced + EUR zero + USD zero
_EXPECTED_DETAIL_ROWS = 2  # EUR priced + USD unpriced-YES (zero-EUR is dust)
_EXPECTED_DUST_ROWS = 1  # EUR zero-value (EUR priced elsewhere)


def _load_report():
    """Load the synthetic dust-partition fixture through the production pipeline."""
    report = load_koinly_crypto_report(_FIXTURE_DIR, jurisdiction=_JURISDICTION)
    assert report is not None, (
        f"load_koinly_crypto_report returned None for {_FIXTURE_DIR}; "
        "the committed fixture is missing or the three-file presence guard failed."
    )
    return report


def _generate_workbook(tmp_path: Path) -> openpyxl.Workbook:
    """Run the full production pipeline and return the loaded workbook.

    ``generate_tax_report`` is the same entry point the production CLI uses
    (``write_crypto_supplementary_sheet`` is invoked from ``workbook_builder``
    when ``crypto_tax_report`` is non-None). Empty capital-gains and dividend
    inputs are passed because the dust-partition tests are rewards-only.
    """
    report = _load_report()
    output_path = tmp_path / "dust_partition.xlsx"
    generate_tax_report(output_path, {}, None, crypto_tax_report=report)
    assert output_path.exists(), "generate_tax_report did not produce a workbook"
    return openpyxl.load_workbook(output_path)


def _supplementary_first_column(wb: openpyxl.Workbook) -> list[str | None]:
    """Return the first-column cell values from the Crypto Supplementary tab."""
    ws = wb["Crypto Supplementary"]
    return [
        (row[0] if row else None)
        for row in ws.iter_rows(values_only=True)
    ]


def _section2_detail_rows(wb: openpyxl.Workbook) -> list[dict[str, object]]:
    """Return the Section 2 reward-detail data rows keyed by header.

    Scans the Crypto Supplementary tab for the ``2. TAXABLE-NOW - SUPPORT
    DETAIL`` section header, then reads the header row and each subsequent
    data row until the Dust summary block or the next section starts. Returns a
    list of dicts keyed by the 11 reward-detail headers
    (``_REWARD_DETAIL_HEADERS`` in ``crypto_supplementary_sheet``).
    """
    ws = wb["Crypto Supplementary"]
    rows = list(ws.iter_rows(values_only=True))
    in_section = False
    header: list[str | None] = []
    detail: list[dict[str, object]] = []
    for row in rows:
        first = row[0] if row else None
        if isinstance(first, str) and first.startswith("2. TAXABLE-NOW"):
            in_section = True
            continue
        if not in_section:
            continue
        # Within Section 2 the detail block runs from the header row up to the
        # "Dust summary:" line (or the next section, whichever comes first).
        if isinstance(first, str) and (first.startswith("3. ") or first == "Dust summary:"):
            break
        if not header:
            # First non-empty row after the section header + note is the column
            # header row. Skip the italic note (single-cell row 1 value).
            if first == "Date" or (isinstance(first, str) and "Date" in first):
                header = [str(c) if c is not None else "" for c in row]
            continue
        # Data row: first cell is an ISO date.
        if isinstance(first, str) and re.match(r"^\d{4}-\d{2}-\d{2}", first):
            entry: dict[str, object] = {}
            for idx, col_name in enumerate(header):
                if idx < len(row) and col_name:
                    entry[col_name] = row[idx]
            detail.append(entry)
    return detail


def _reconciliation_map(wb: openpyxl.Workbook) -> dict[str, object]:
    """Return the Section 4 reconciliation key-value pairs as a dict."""
    ws = wb["Crypto Supplementary"]
    rows = list(ws.iter_rows(values_only=True))
    result: dict[str, object] = {}
    in_section = False
    for row in rows:
        first = row[0] if row else None
        if isinstance(first, str) and first.startswith("4. REWARDS CLASSIFICATION RECONCILIATION"):
            in_section = True
            continue
        if not in_section:
            continue
        if isinstance(first, str) and first.startswith("5. "):
            break
        if isinstance(first, str) and first:
            value = row[1] if len(row) > 1 else None
            result[first] = value
    return result


class TestCryptoDustPartitionE2E:
    """E2E pin for the CRG-021 dust partition via the full production pipeline."""

    def test_priced_asset_zero_collapses_to_dust_via_full_pipeline(self, tmp_path: Path) -> None:
        """Zero-value taxable-now reward on a priced asset collapses to the dust summary block.

        Given the fixture with one priced EUR reward (3.00 EUR) and one
        zero-value EUR reward, the Crypto Supplementary tab MUST render a
        ``Dust summary:`` block containing exactly one EUR line, and the
        Section 4 reconciliation MUST split into detail/dust counts
        (the zero-value EUR row counts as dust, not detail).
        """
        wb = _generate_workbook(tmp_path)
        first_col = _supplementary_first_column(wb)

        # The dust summary block header is present and is followed by exactly
        # one EUR dust line (the zero-value EUR reward; EUR is priced because
        # of the 3.00 EUR row in the same export).
        assert "Dust summary:" in first_col, (
            "Dust summary header missing from Crypto Supplementary; "
            "the zero-value priced-asset reward did not route to dust."
        )
        eur_dust_lines = [
            s
            for s in first_col
            if isinstance(s, str)
            and re.search(rf"{_PRICED_ASSET} dust .*: 1 rows, summed Value EUR = 0\.00", s)
        ]
        assert eur_dust_lines, (
            f"Expected one '{_PRICED_ASSET} dust ...: 1 rows, summed Value EUR = 0.00' line "
            f"in the dust summary block; first column: {first_col}"
        )

        # Section 4 reconciliation shows the split counts.
        recon = _reconciliation_map(wb)
        assert recon.get("Taxable-now detail rows") == _EXPECTED_DETAIL_ROWS, (
            f"Expected Taxable-now detail rows = {_EXPECTED_DETAIL_ROWS}, "
            f"got {recon.get('Taxable-now detail rows')!r}; recon: {recon}"
        )
        assert recon.get("Taxable-now dust rows (suppressed from detail)") == _EXPECTED_DUST_ROWS, (
            f"Expected Taxable-now dust rows = {_EXPECTED_DUST_ROWS}, "
            f"got {recon.get('Taxable-now dust rows (suppressed from detail)')!r}; recon: {recon}"
        )
        wb.close()

    def test_unpriced_asset_zero_keeps_per_row_yes_via_full_pipeline(self, tmp_path: Path) -> None:
        """Zero-value taxable-now reward on an asset with no priced income row keeps per-row YES.

        Given the fixture's zero-value USD reward (USD has NO priced row in
        ``reward_entries``; the priced USD CG row keeps USD in
        ``known_assets`` so the income reward is retained, not skipped), the
        USD row MUST appear in the Section 2 detail table with its ``Review
        flag`` cell starting ``YES:`` (full-pipeline version of the r9 headline
        fix pinned at the helper boundary by
        ``TestPartitionTaxableNow#test_unpriced_asset_zero_stays_in_real_rows``).
        """
        wb = _generate_workbook(tmp_path)
        detail = _section2_detail_rows(wb)

        usd_rows = [r for r in detail if str(r.get("Asset", "")) == _UNPRICED_ASSET]
        assert usd_rows, (
            f"Zero-value {_UNPRICED_ASSET} reward should appear in the Section 2 detail "
            f"table (unpriced asset -> per-row YES, NOT dust); detail rows: {detail}"
        )
        review_flag = str(usd_rows[0].get("Review flag", ""))
        assert review_flag.startswith("YES:"), (
            f"Unpriced-asset zero-value reward review flag must start 'YES:' (r9 headline fix); "
            f"got {review_flag!r}. USD detail row: {usd_rows[0]}"
        )

        # Sanity: the priced EUR row also stays in the detail table with NO
        # review flag (it is the priced anchor that makes EUR "priced").
        eur_rows = [r for r in detail if str(r.get("Asset", "")) == _PRICED_ASSET]
        assert eur_rows, f"Priced {_PRICED_ASSET} reward should appear in Section 2 detail; rows: {detail}"
        assert str(eur_rows[0].get("Review flag", "")) == "NO", (
            f"Priced {_PRICED_ASSET} reward should carry review flag 'NO' (no review needed); "
            f"got {eur_rows[0].get('Review flag')!r}"
        )
        wb.close()

    def test_reward_entries_unchanged_by_partition(self, tmp_path: Path) -> None:
        """Invariant 1 (presentation-layer only): the partition does not mutate reward_entries or totals.

        Given the fixture, the production pipeline's ``reward_entries`` length
        and the reconciliation totals MUST match the values derived directly
        from the fixture rows. There is no runtime flag to disable the
        partition, so there is no "partition-disabled baseline" to compare
        against (CRG-021 A2); the invariant is that the partition is a VIEW
        over ``reward_entries`` and never mutates the list, the
        ``taxable_now_total_eur``, or the ``reward_total_eur``.
        """
        report = _load_report()

        # reward_entries length: exactly the three income rows (the priced CG
        # USD row is a capital gain, not a reward).
        assert len(report.reward_entries) == _EXPECTED_REWARD_ENTRIES_LEN, (
            f"Expected reward_entries length = {_EXPECTED_REWARD_ENTRIES_LEN} "
            f"(EUR priced + EUR zero + USD zero), got {len(report.reward_entries)}. "
            f"Entries: {[(e.asset, e.value_eur, e.tax_classification) for e in report.reward_entries]}"
        )

        # reward_total_eur: sum of value_eur over ALL reward_entries.
        # The partition never mutates totals (Invariant 1).
        expected_reward_total = sum((e.value_eur for e in report.reward_entries), start=Decimal("0"))
        assert expected_reward_total == _EXPECTED_REWARD_TOTAL_EUR, (
            "Self-check: derived reward_total_eur does not match the expected constant; "
            f"derived={expected_reward_total}, expected={_EXPECTED_REWARD_TOTAL_EUR}"
        )
        assert report.reconciliation.reward_total_eur == _EXPECTED_REWARD_TOTAL_EUR, (
            f"Pipeline reconciliation.reward_total_eur = {report.reconciliation.reward_total_eur} "
            f"must equal the fixture-derived total {_EXPECTED_REWARD_TOTAL_EUR} (Invariant 1: "
            "the partition does not mutate totals)."
        )

        # taxable-now total: sum of value_eur over taxable-now rows only.
        taxable_now = [
            e for e in report.reward_entries
            if e.tax_classification == RewardTaxClassification.TAXABLE_NOW
        ]
        expected_taxable_now_total = sum((e.value_eur for e in taxable_now), start=Decimal("0"))
        assert expected_taxable_now_total == _EXPECTED_REWARD_TOTAL_EUR, (
            "Self-check: all three fixture reward rows are TAXABLE_NOW (EUR/USD are fiat), "
            f"so taxable_now_total must equal reward_total; got {expected_taxable_now_total}"
        )

        # Generate the workbook and confirm Section 4 reconciliation counts.
        wb = _generate_workbook(tmp_path)
        recon = _reconciliation_map(wb)
        detail_count = recon.get("Taxable-now detail rows")
        dust_count = recon.get("Taxable-now dust rows (suppressed from detail)")
        assert detail_count == _EXPECTED_DETAIL_ROWS, (
            f"Taxable-now detail rows = {detail_count!r}, expected {_EXPECTED_DETAIL_ROWS}; recon: {recon}"
        )
        assert dust_count == _EXPECTED_DUST_ROWS, (
            f"Taxable-now dust rows = {dust_count!r}, expected {_EXPECTED_DUST_ROWS}; recon: {recon}"
        )
        # Invariant 1 corollary: detail + dust MUST equal the taxable-now row count
        # (complementary-filter partition; the count-equality guard was dropped per
        # r4 Monitor #4 as tautological at the helper boundary, but it is a useful
        # presentation-layer sanity check at the e2e level).
        assert detail_count + dust_count == len(taxable_now), (
            f"detail ({detail_count}) + dust ({dust_count}) must equal taxable-now row count "
            f"({len(taxable_now)}); recon: {recon}"
        )
        # The taxable-now total value row must equal the fixture-derived total.
        assert recon.get("Taxable-now total value (EUR)") == float(_EXPECTED_REWARD_TOTAL_EUR), (
            f"Taxable-now total value = {recon.get('Taxable-now total value (EUR)')!r}, "
            f"expected {float(_EXPECTED_REWARD_TOTAL_EUR)}; recon: {recon}"
        )
        wb.close()
