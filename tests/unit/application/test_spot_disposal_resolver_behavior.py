"""SPOT_DISPOSAL treatment - resolver-path characterization (Phase E).

Phase E deleted the ``treatment_spot_disposal_via_resolver`` flag (Task 6)
and made the OGR event-level override gate on the resolver identifying the
TH row as ``Treatment.SPOT_DISPOSAL`` unconditionally. The Phase-D
flag-mechanic tests (legacy path runs when flag off; byte-identical under
both states) were deleted with the flag. The surviving tests pin the
resolver-path identification and the OGR-override behavior.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from tax_reporting.application.crypto.derivatives_filter import (
    _load_derivatives_labels_config,
)
from tax_reporting.application.crypto.treatment_resolver import (
    TreatmentConfig,
    resolve_treatment,
)
from tax_reporting.application.crypto_reporting import (
    build_transactions_from_th,
    load_koinly_crypto_report,
)
from tax_reporting.domain.treatment import Treatment
from tax_reporting.infrastructure.config import TaxJurisdictionConfig
from tax_reporting.infrastructure.koinly_parser import (
    normalize_asset_ticker,
    normalize_platform_name,
)

_MULTI_LOT_OGR_DIR = Path("resources/source/example/2025/koinly/multi_lot_ogr")

_TH_HEADER = (
    "Date,Type,Tag,Sending Wallet,Sent Amount,Sent Currency,Sent Cost Basis,"
    "Receiving Wallet,Received Amount,Received Currency,Received Cost Basis,"
    "Fee Amount,Fee Currency,Gain (EUR),Net Value (EUR),Fee Value (EUR),"
    "TxSrc,TxDest,TxHash,Description"
)

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

_OGR_HEADER = "Date,Asset,Amount,Value (EUR),Type,Wallet Name"


def _scenario_th_csv() -> Path:
    return _MULTI_LOT_OGR_DIR / "koinly_2025_transaction_history.csv"


def _treatment_config_for_year(year: int) -> TreatmentConfig:
    """Build a TreatmentConfig with the production derivatives labels injected."""
    return TreatmentConfig(
        derivatives_tags=_load_derivatives_labels_config("koinly", year),
    )


def _make_jurisdiction() -> TaxJurisdictionConfig:
    """Build a TEST TaxJurisdictionConfig that exercises the OGR path.

    ``use_other_gains_report=True`` so ``apply_ogr_event_level`` runs;
    ``separate_derivatives_reporting=False`` so all OGR rows are spot
    (matches the multi_lot_ogr corpus shape).
    """
    return TaxJurisdictionConfig(
        country="TEST",
        fiscal_year=2025,
        exclude_loan_repayment_gains=False,
        zero_basis_review_threshold=Decimal("500"),
        use_other_gains_report=True,
        separate_derivatives_reporting=False,
    )


def _write_mixed_treatment_scenario(tmp_path: Path) -> Path:
    """Build a temp Koinly directory with ONE SPOT_DISPOSAL + ONE PAYMENT event.

    Both events share the same disposal date (``2025-06-15``) but use
    different assets/wallets so they form distinct ``(date, asset, wallet)``
    keys. Each has a matching CG lot and an OGR Profit row, so the OGR
    override COULD apply to either under a hypothetical no-filter path.
    Under the resolver path, only the SPOT_DISPOSAL event is overridden;
    the PAYMENT event is excluded by the spot_disposal_keys filter.
    """
    koinly_dir = tmp_path / "mixed_treatment"
    koinly_dir.mkdir()
    (koinly_dir / "koinly_2025_transaction_history.csv").write_text(
        "\n".join(
            [
                "Transaction report 2025",
                "",
                _TH_HEADER,
                # SPOT_DISPOSAL event: ETH disposal on Kraken, no tag.
                '2025-06-15 12:00:00 UTC,crypto_withdrawal,,Kraken,"1,00000000",'
                'ETH,"800,00",,,,,,"200,00","1000,00","0,00",,,synth-spot-001,'
                "SPOT_DISPOSAL disposal (mixed-treatment fixture)",
                # PAYMENT event: EUROC payment on Wirex, Tag=Payment.
                '2025-06-15 12:00:00 UTC,crypto_withdrawal,Payment,Wirex,'
                '"100,00000000",EUROC,"20,00",,,,,,,"-20,00","0,00","0,00",,,'
                "synth-payment-001,PAYMENT disposal (mixed-treatment fixture)",
            ]
        ),
        encoding="utf-8",
    )
    (koinly_dir / "koinly_2025_capital_gains_report.csv").write_text(
        "\n".join(
            [
                "Capital gains report 2025",
                "",
                _CG_HEADER,
                # SPOT_DISPOSAL lot: ETH disposal on Kraken.
                '15/06/2025 12:00,01/05/2025 10:00,ETH,"1,00000000","800,00",'
                '"1000,00","200,00","",Kraken,Short term',
                # PAYMENT lot: EUROC disposal on Wirex with zero proceeds.
                '15/06/2025 12:00,01/05/2025 10:00,EUROC,"100,00000000","20,00",'
                '0.0,"-20,00","",Wirex,Short term',
            ]
        ),
        encoding="utf-8",
    )
    (koinly_dir / "koinly_2025_other_gains_report.csv").write_text(
        "\n".join(
            [
                "Other gains report 2025",
                "",
                _OGR_HEADER,
                '15/06/2025 12:00,ETH,"1,00000000","1000,00",Profit,Kraken',
                '15/06/2025 12:00,EUROC,"100,00000000","15,00",Profit,Wirex',
            ]
        ),
        encoding="utf-8",
    )
    (koinly_dir / "koinly_2025_income_report.csv").write_text(
        "\n".join(["Income report 2025", "", _INCOME_HEADER]),
        encoding="utf-8",
    )
    return koinly_dir


@pytest.mark.unit
class TestSpotDisposalResolverBehavior:
    """Pin the SPOT_DISPOSAL identification and OGR override on the resolver path."""

    def test_resolver_identifies_spot_disposal(self) -> None:
        """The ``multi_lot_ogr`` TH row (no special tag) resolves to SPOT_DISPOSAL.

        Pins the identification source (Phase B resolver) for the corpus row
        the OGR override is gated on. Under default TreatmentConfig with the
        production derivatives labels injected, an untagged disposal-shaped
        row resolves to SPOT_DISPOSAL.
        """
        transactions = build_transactions_from_th(_scenario_th_csv())
        assert len(transactions) == 1, "multi_lot_ogr scenario drifted: expected 1 TH row"
        config = _treatment_config_for_year(2025)
        treatment = resolve_treatment(transactions[0], config)
        assert treatment is Treatment.SPOT_DISPOSAL, (
            f"expected SPOT_DISPOSAL for untagged disposal row, got {treatment.value!r}"
        )

    def test_ogr_override_runs_on_spot_disposal(self) -> None:
        """OGR override runs on the SPOT_DISPOSAL lots once per event.

        Loads ``multi_lot_ogr`` end-to-end via ``load_koinly_crypto_report``.
        The corpus has one CG key with two lots + one OGR Profit row; under
        the event-level override, the first lot absorbs the full OGR event
        gain (Phase 1).
        """
        jurisdiction = _make_jurisdiction()
        report = load_koinly_crypto_report(_MULTI_LOT_OGR_DIR, jurisdiction=jurisdiction)
        assert report is not None, "load_koinly_crypto_report returned None for multi_lot_ogr"
        eth_rows = [
            e
            for e in report.capital_entries
            if normalize_asset_ticker(e.asset) == "ETH"
            and normalize_platform_name(e.wallet) == "Kraken"
        ]
        assert eth_rows, "expected at least one ETH/Kraken aggregated row after OGR override"
        eth = eth_rows[0]
        # The OGR Profit row value is 1000 EUR; agree branch writes the FULL
        # event value as gain_loss_eur (first lot absorbs).
        assert eth.gain_loss_eur == Decimal("1000.00"), (
            f"OGR override did not run; expected gain_loss_eur=1000.00 "
            f"(OGR event gain), got {eth.gain_loss_eur}"
        )
        assert eth.ogr_validation is not None, (
            "aggregated row must carry ogr_validation when override ran"
        )

    def test_ogr_override_skipped_on_non_spot_treatment(self, tmp_path: Path) -> None:
        """A non-SPOT_DISPOSAL lot is NOT overridden.

        Builds a temp Koinly directory with ONE SPOT_DISPOSAL event
        (ETH/Kraken, no tag) and ONE PAYMENT event (EUROC/Wirex,
        ``Tag="Payment"``), each with a matching CG lot and OGR Profit row.

        Under the resolver path: the SPOT_DISPOSAL lot is overridden
        (gain_loss_eur reflects OGR; ogr_validation set); the PAYMENT lot is
        NOT overridden (gain_loss_eur equals pre-override CG value ``-20``;
        ogr_validation is None).
        """
        koinly_dir = _write_mixed_treatment_scenario(tmp_path)

        report = load_koinly_crypto_report(koinly_dir, jurisdiction=_make_jurisdiction())
        assert report is not None
        by_key = {
            (normalize_asset_ticker(e.asset), normalize_platform_name(e.wallet)): e
            for e in report.capital_entries
        }
        spot = by_key[("ETH", "Kraken")]
        payment = by_key[("EUROC", "Wirex")]
        assert spot.ogr_validation is not None, (
            "SPOT_DISPOSAL lot must carry ogr_validation when override ran"
        )
        assert spot.gain_loss_eur == Decimal("1000.00"), (
            f"SPOT_DISPOSAL lot gain_loss_eur must reflect OGR override "
            f"(expected 1000.00); got {spot.gain_loss_eur}"
        )
        assert payment.ogr_validation is None, (
            "PAYMENT lot must NOT be overridden; ogr_validation must be None"
        )
        assert payment.gain_loss_eur == Decimal("-20"), (
            f"PAYMENT lot gain_loss_eur must equal pre-override CG value "
            f"(-20); got {payment.gain_loss_eur}"
        )
