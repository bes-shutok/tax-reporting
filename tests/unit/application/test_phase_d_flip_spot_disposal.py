"""Phase D Task 3 - SPOT_DISPOSAL flip: OGR 1:1 override bypass.

Pins the per-treatment flip wiring for ``SPOT_DISPOSAL``: when
``jurisdiction.treatment_spot_disposal_via_resolver`` is True, the OGR
event-level override is gated on the resolver identifying the TH row as
``Treatment.SPOT_DISPOSAL``. When False, the legacy path runs unchanged
(Invariant 1: bypass, not deletion).

The pure-corpus test uses the committed synthetic
``2025/koinly/multi_lot_ogr/`` scenario (one CG key with two lots + one
OGR Profit row). The mixed-treatment test (r7 Medium #6) builds a temp
directory with TWO TH rows on the same date - one ``SPOT_DISPOSAL`` (no
tag) and one ``PAYMENT`` (``Tag="Payment"``) - each with a matching CG
lot and OGR Profit row, so a non-SPOT_DISPOSAL disposal event is
structurally present alongside a SPOT_DISPOSAL one. Under flag-on, only
the SPOT_DISPOSAL event is overridden; under flag-off, the legacy path
overrides both.

This module also pins r8 Medium #1 (single production ``Transaction``
construction caller) and r9 Monitor #1 (gate construction on
``any_resolver_on``) by exercising the integration through
``load_koinly_crypto_report``.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from tax_reporting.application.crypto.derivatives_dedup import (
    _load_derivatives_labels_config,
)
from tax_reporting.application.crypto.transaction_factory import build_transaction
from tax_reporting.application.crypto.treatment_resolver import (
    TreatmentConfig,
    resolve_treatment,
)
from tax_reporting.application.crypto.wallet_kind import (
    aggregate_platform_evidence,
    classify_platform,
)
from tax_reporting.application.crypto.wallet_kind_registry import (
    ProductionWalletKindRegistry,
)
from tax_reporting.application.crypto_reporting import load_koinly_crypto_report
from tax_reporting.domain.transaction import Transaction
from tax_reporting.domain.treatment import Treatment
from tax_reporting.infrastructure.config import TaxJurisdictionConfig
from tax_reporting.infrastructure.koinly_parser import (
    normalize_asset_ticker,
    normalize_platform_name,
    parse_th_row,
    read_koinly_rows,
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


def _build_transactions_from_th(th_path: Path) -> list[Transaction]:
    """Run the sanctioned Phase A factory chain over every TH row in ``th_path``."""
    rows = read_koinly_rows(th_path)
    parsed = [parse_th_row(row, row_index=index) for index, row in enumerate(rows)]
    evidence = aggregate_platform_evidence(parsed)
    registry = ProductionWalletKindRegistry()
    transactions: list[Transaction] = []
    for row in parsed:
        sending = row.sending_wallet.strip()
        platform_raw = (
            sending if sending and sending.lower() != "unknown" else row.receiving_wallet.strip()
        )
        platform = normalize_platform_name(platform_raw) if platform_raw else ""
        classification = classify_platform(
            platform,
            evidence.get(platform) if platform else None,
            registry,
        )
        transactions.append(build_transaction(row, classification))
    return transactions


def _treatment_config_for_year(year: int) -> TreatmentConfig:
    """Build a TreatmentConfig with the production derivatives labels injected."""
    return TreatmentConfig(
        derivatives_tags=_load_derivatives_labels_config("koinly", year),
    )


def _make_jurisdiction(*, flag_on: bool) -> TaxJurisdictionConfig:
    """Build a TEST TaxJurisdictionConfig that exercises the OGR path.

    ``use_other_gains_report=True`` so ``apply_ogr_event_level`` runs;
    ``separate_derivatives_reporting=False`` so all OGR rows are spot
    (matches the multi_lot_ogr corpus shape); the SPOT_DISPOSAL flag toggles.
    """
    return TaxJurisdictionConfig(
        country="TEST",
        fiscal_year=2025,
        exclude_loan_repayment_gains=False,
        zero_basis_review_threshold=Decimal("500"),
        use_other_gains_report=True,
        separate_derivatives_reporting=False,
        treatment_spot_disposal_via_resolver=flag_on,
    )


def _write_mixed_treatment_scenario(tmp_path: Path) -> Path:
    """Build a temp Koinly directory with ONE SPOT_DISPOSAL + ONE PAYMENT event.

    Both events share the same disposal date (``2025-06-15``) but use
    different assets/wallets so they form distinct ``(date, asset, wallet)``
    keys. Each has a matching CG lot and an OGR Profit row, so the OGR
    override COULD apply to either under the legacy path. Under the
    SPOT_DISPOSAL flag-on path, only the SPOT_DISPOSAL event is overridden.
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
class TestPhaseDFlipSpotDisposal:
    """Pin the SPOT_DISPOSAL flip wiring on the OGR event-level override."""

    def test_resolver_identifies_spot_disposal(self) -> None:
        """The ``multi_lot_ogr`` TH row (no special tag) resolves to SPOT_DISPOSAL.

        Pins the identification source (Phase B resolver) for the corpus row
        the OGR override is gated on. Under default TreatmentConfig with the
        production derivatives labels injected, an untagged disposal-shaped
        row resolves to SPOT_DISPOSAL.
        """
        transactions = _build_transactions_from_th(_scenario_th_csv())
        assert len(transactions) == 1, "multi_lot_ogr scenario drifted: expected 1 TH row"
        config = _treatment_config_for_year(2025)
        treatment = resolve_treatment(transactions[0], config)
        assert treatment is Treatment.SPOT_DISPOSAL, (
            f"expected SPOT_DISPOSAL for untagged disposal row, got {treatment.value!r}"
        )

    def test_ogr_override_runs_when_flag_on(self) -> None:
        """Flag on: OGR override runs on the SPOT_DISPOSAL lots once per event.

        Loads ``multi_lot_ogr`` end-to-end via ``load_koinly_crypto_report``
        with ``treatment_spot_disposal_via_resolver=True``. The corpus has one
        CG key with two lots + one OGR Profit row; under the event-level
        override, the first lot absorbs the full OGR event gain (Phase 1).
        Pins that the flag-on path does NOT skip the override for SPOT_DISPOSAL
        rows and applies it once per event (not per lot).
        """
        jurisdiction = _make_jurisdiction(flag_on=True)
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
            f"flag-on: OGR override did not run; expected gain_loss_eur=1000.00 "
            f"(OGR event gain), got {eth.gain_loss_eur}"
        )
        assert eth.ogr_validation is not None, (
            "flag-on: aggregated row must carry ogr_validation when override ran"
        )

    def test_ogr_override_skipped_when_flag_off(self) -> None:
        """Flag off: legacy OGR override runs unchanged.

        With ``treatment_spot_disposal_via_resolver=False``, the legacy
        ``apply_ogr_event_level`` runs without the treatment filter; the OGR
        override still fires on every key in spot_index. Pins Invariant 8:
        the bypass is structural, the legacy path remains reachable when
        the flag is off.
        """
        jurisdiction = _make_jurisdiction(flag_on=False)
        report = load_koinly_crypto_report(_MULTI_LOT_OGR_DIR, jurisdiction=jurisdiction)
        assert report is not None, "load_koinly_crypto_report returned None for multi_lot_ogr"
        eth_rows = [
            e
            for e in report.capital_entries
            if normalize_asset_ticker(e.asset) == "ETH"
            and normalize_platform_name(e.wallet) == "Kraken"
        ]
        assert eth_rows, "expected at least one ETH/Kraken aggregated row"
        eth = eth_rows[0]
        # Legacy path applies the same OGR override (corpus is pure
        # SPOT_DISPOSAL); the flag-off result MUST match the flag-on result
        # for this corpus (byte-identical non-regression on the pure case).
        assert eth.gain_loss_eur == Decimal("1000.00"), (
            f"flag-off (legacy): expected OGR-overridden gain_loss_eur=1000.00, "
            f"got {eth.gain_loss_eur}"
        )
        assert eth.ogr_validation is not None

    def test_ogr_override_skipped_on_non_spot_treatment(self, tmp_path: Path) -> None:
        """r7 Medium #6: a non-SPOT_DISPOSAL lot is NOT overridden when flag on.

        Builds a temp Koinly directory with ONE SPOT_DISPOSAL event
        (ETH/Kraken, no tag) and ONE PAYMENT event (EUROC/Wirex,
        ``Tag="Payment"``), each with a matching CG lot and OGR Profit row.

        Under ``treatment_spot_disposal_via_resolver=True``: the SPOT_DISPOSAL
        lot is overridden (gain_loss_eur reflects OGR; ogr_validation set);
        the PAYMENT lot is NOT overridden (gain_loss_eur equals pre-override
        CG value ``-20``; ogr_validation is None).

        Under ``treatment_spot_disposal_via_resolver=False`` (legacy): BOTH
        lots are overridden.

        This test FAILS today (no filter wiring): with no filter, BOTH lots
        are overridden regardless of the flag. Pins r7 Medium #6.
        """
        koinly_dir = _write_mixed_treatment_scenario(tmp_path)

        # Flag ON: only SPOT_DISPOSAL event is overridden.
        jurisdiction_on = _make_jurisdiction(flag_on=True)
        report_on = load_koinly_crypto_report(koinly_dir, jurisdiction=jurisdiction_on)
        assert report_on is not None
        on_by_key = {
            (normalize_asset_ticker(e.asset), normalize_platform_name(e.wallet)): e
            for e in report_on.capital_entries
        }
        spot_on = on_by_key[("ETH", "Kraken")]
        payment_on = on_by_key[("EUROC", "Wirex")]
        assert spot_on.ogr_validation is not None, (
            "flag-on: SPOT_DISPOSAL lot must carry ogr_validation when override ran"
        )
        assert spot_on.gain_loss_eur == Decimal("1000.00"), (
            f"flag-on: SPOT_DISPOSAL lot gain_loss_eur must reflect OGR override "
            f"(expected 1000.00); got {spot_on.gain_loss_eur}"
        )
        assert payment_on.ogr_validation is None, (
            "flag-on: PAYMENT lot must NOT be overridden; ogr_validation must be None"
        )
        assert payment_on.gain_loss_eur == Decimal("-20"), (
            f"flag-on: PAYMENT lot gain_loss_eur must equal pre-override CG value "
            f"(-20); got {payment_on.gain_loss_eur}"
        )

        # Flag OFF (legacy): BOTH events are overridden (no filter).
        jurisdiction_off = _make_jurisdiction(flag_on=False)
        report_off = load_koinly_crypto_report(koinly_dir, jurisdiction=jurisdiction_off)
        assert report_off is not None
        off_by_key = {
            (normalize_asset_ticker(e.asset), normalize_platform_name(e.wallet)): e
            for e in report_off.capital_entries
        }
        spot_off = off_by_key[("ETH", "Kraken")]
        payment_off = off_by_key[("EUROC", "Wirex")]
        assert spot_off.ogr_validation is not None, (
            "flag-off (legacy): SPOT_DISPOSAL lot must be overridden"
        )
        assert payment_off.ogr_validation is not None, (
            "flag-off (legacy): PAYMENT lot must ALSO be overridden (legacy path "
            "applies override to every key in spot_index)"
        )
