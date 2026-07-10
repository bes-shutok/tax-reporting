"""Phase D Task 4 - PAYMENT flip: count-equality gate + re-zero block bypass.

Pins the per-treatment flip wiring for ``PAYMENT``: when
``jurisdiction.treatment_payment_via_resolver`` is True, the count-equality
gate in ``correct_payment_proceeds`` is bypassed (identification comes from
the resolver) and the re-zero snapshot/restore block in
``crypto_reporting.py`` is bypassed when ``treatment_spot_disposal_via_resolver``
is ALSO True (Invariant 8 + r7 Medium #2 fix).

The pure-corpus test (``test_resolver_identifies_payment``) uses the
committed synthetic ``2025/koinly/payment_ogr_collision/`` scenario; the
discriminating tests build temp Koinly directories whose counts differ or
whose flag combination exercises the bypass boundary, so a wrong
implementation fails visibly (per Phase D Invariant: a discriminating test
asserts a property that FAILS under a wrong implementation).

r8 Medium #1: the production caller ``load_koinly_crypto_report`` builds the
``list[Transaction]`` ONCE and filters ``[tx for tx in transactions if
resolve_treatment(tx, cfg) == Treatment.PAYMENT]``; this module exercises
that wiring end-to-end (no test-side re-build of ``Transaction`` objects).
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

_PAYMENT_OGR_COLLISION_DIR = Path(
    "resources/source/example/2025/koinly/payment_ogr_collision"
)

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
    """Path to the ``payment_ogr_collision`` TH fixture (committed)."""
    return _PAYMENT_OGR_COLLISION_DIR / "koinly_2025_transaction_history.csv"


def _build_transactions_from_th(th_path: Path) -> list[Transaction]:
    """Run the sanctioned Phase A factory chain over every TH row in ``th_path``.

    Mirrors the production wiring in ``load_koinly_crypto_report`` so the
    resolver identification test exercises the SAME construction path.
    """
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


def _make_jurisdiction(
    *,
    payment_flag: bool,
    spot_flag: bool = True,
    infer_payment_proceeds: bool = True,
) -> TaxJurisdictionConfig:
    """Build a TEST TaxJurisdictionConfig that exercises the payment-proceeds path.

    ``use_other_gains_report=True`` so the OGR override runs (and can mutate
    PAYMENT rows that share the OGR key); ``exclude_loan_repayment_gains=False``
    so the FIFO rebuild does not interfere; ``infer_payment_proceeds`` defaults
    True so the correction runs (the flag gates whether the correction fires
    at all, independent of the PAYMENT identification path).
    """
    return TaxJurisdictionConfig(
        country="TEST",
        fiscal_year=2025,
        exclude_loan_repayment_gains=False,
        zero_basis_review_threshold=Decimal("500"),
        use_other_gains_report=True,
        separate_derivatives_reporting=False,
        infer_payment_proceeds=infer_payment_proceeds,
        treatment_payment_via_resolver=payment_flag,
        treatment_spot_disposal_via_resolver=spot_flag,
    )


def _write_count_mismatch_scenario(tmp_path: Path) -> Path:
    """Build a temp Koinly directory with 2 CG lots + 1 Payment TH row.

    Both CG lots share the same ``(2025-06-15, EUROC, Wirex, 100)`` key as the
    single Payment TH row, so cg_count[key]=2 and th_count[key]=1. Under the
    legacy count-equality gate, correction is BLOCKED (a "Payment match
    ambiguous" review entry is appended and proceeds stay 0). Under the flag-on
    path, the count-equality gate is NOT consulted, so the payment-proceeds
    correction fires for the matched lot (the resolver-based identification
    consumes one TH row per CG lot, leaving the second lot unchanged when the
    TH bucket is empty - documented behavior).
    """
    koinly_dir = tmp_path / "count_mismatch"
    koinly_dir.mkdir()
    (koinly_dir / "koinly_2025_transaction_history.csv").write_text(
        "\n".join(
            [
                "Transaction report 2025",
                "",
                _TH_HEADER,
                # ONE Payment TH row: 100 EUROC on Wirex, Net Value 0 (the
                # unpriced-EUROC phantom-loss shape from payment_ogr_collision).
                '2025-06-15 12:00:00 UTC,crypto_withdrawal,Payment,Wirex,'
                '"100,00000000",EUROC,"20,00",,,,,,,"-20,00","0,00","0,00",,,'
                "synth-payment-001,Payment disposal (count-mismatch fixture)",
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
                # TWO CG lots on the same key: both with proceeds 0.
                '15/06/2025 12:00,01/05/2025 10:00,EUROC,"100,00000000","20,00",'
                '0.0,"-20,00","",Wirex,Short term',
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
                # No OGR row for this scenario: the count-equality gate is the
                # subject; an OGR override would conflate the residual-closing
                # behavior tested in test_payment_flip_with_spot_disposal_off.
            ]
        ),
        encoding="utf-8",
    )
    (koinly_dir / "koinly_2025_income_report.csv").write_text(
        "\n".join(["Income report 2025", "", _INCOME_HEADER]),
        encoding="utf-8",
    )
    return koinly_dir


def _write_residual_scenario(tmp_path: Path) -> Path:
    """Build a temp Koinly directory whose OGR override mutates a PAYMENT row.

    ONE Payment disposal (``Tag="Payment"``) with proceeds 0 + ONE OGR Loss row
    on the same legacy ``(2025-06-15, EUROC, Wirex)`` key. Under
    ``(spot_off, payment_on)`` partial rollback, the OGR override STILL mutates
    the PAYMENT row's proceeds (Task 3 OFF means spot_disposal_keys filter is
    NOT applied), so the re-zero snapshot/restore block MUST run to restore
    proceeds=0 before the payment-proceeds correction fires. This pins
    r7 Medium #2: the PAYMENT re-zero bypass depends on the SPOT_DISPOSAL flip
    ALSO being ON; under partial rollback, the re-zero block must remain
    active.
    """
    koinly_dir = tmp_path / "residual_close"
    koinly_dir.mkdir()
    (koinly_dir / "koinly_2025_transaction_history.csv").write_text(
        "\n".join(
            [
                "Transaction report 2025",
                "",
                _TH_HEADER,
                '2025-06-15 12:00:00 UTC,crypto_withdrawal,Payment,Wirex,'
                '"100,00000000",EUROC,"20,00",,,,,,,"-20,00","0,00","0,00",,,'
                "synth-payment-001,Payment disposal (residual fixture)",
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
                # OGR Loss row on the SAME key as the Payment disposal. Under
                # spot_flag=OFF, the OGR override mutates the PAYMENT row.
                '15/06/2025 12:00,EUROC,"100,00000000","15,00",Loss,Wirex',
            ]
        ),
        encoding="utf-8",
    )
    (koinly_dir / "koinly_2025_income_report.csv").write_text(
        "\n".join(["Income report 2025", "", _INCOME_HEADER]),
        encoding="utf-8",
    )
    return koinly_dir


def _capital_by_key(report, asset: str, platform: str) -> list:
    """Filter ``report.capital_entries`` by normalized (asset, platform)."""
    return [
        e
        for e in report.capital_entries
        if normalize_asset_ticker(e.asset) == asset
        and normalize_platform_name(e.wallet) == platform
    ]


@pytest.mark.unit
class TestPhaseDFlipPayment:
    """Pin the PAYMENT flip wiring on the count-equality gate and re-zero block."""

    def test_resolver_identifies_payment(self) -> None:
        """The ``payment_ogr_collision`` TH row (``Tag="Payment"``) resolves to PAYMENT.

        Pins the identification source (Phase B resolver) for the corpus row
        the PAYMENT flip gates on. Under default TreatmentConfig with the
        production derivatives labels injected, a ``Tag="Payment"`` row
        resolves to PAYMENT (default payment_tags is ``{"payment",
        "card payment"}``).
        """
        transactions = _build_transactions_from_th(_scenario_th_csv())
        assert len(transactions) == 1, (
            "payment_ogr_collision scenario drifted: expected 1 TH row"
        )
        config = _treatment_config_for_year(2025)
        treatment = resolve_treatment(transactions[0], config)
        assert treatment is Treatment.PAYMENT, (
            f"expected PAYMENT for Tag=Payment row, got {treatment.value!r}"
        )

    def test_count_gate_skipped_when_flag_on(self, tmp_path: Path) -> None:
        """Flag on: count-equality gate in ``correct_payment_proceeds`` is bypassed.

        With 2 CG lots + 1 Payment TH row on the same key, the legacy
        count-equality gate would block correction and emit a
        "Payment match ambiguous" review entry. Under
        ``treatment_payment_via_resolver=True``, the resolver-based
        identification makes the count-equality gate code path unreachable;
        the payment-proceeds correction fires on the lot whose resolver
        treatment is PAYMENT, regardless of the CG-row count.
        """
        koinly_dir = _write_count_mismatch_scenario(tmp_path)
        jurisdiction = _make_jurisdiction(payment_flag=True)
        report = load_koinly_crypto_report(koinly_dir, jurisdiction=jurisdiction)
        assert report is not None, "load_koinly_crypto_report returned None"

        # Under flag-on: NO "Payment match ambiguous" review entry was
        # appended (the count-equality gate is unreachable). At least one lot
        # was corrected (proceeds non-zero), proving the correction fired.
        ambiguous_reviews = [
            r
            for r in report.review_entries
            if "ambiguous" in (r.review_reason or "").lower()
        ]
        assert not ambiguous_reviews, (
            f"flag-on: count-equality gate was consulted (emitted {len(ambiguous_reviews)} "
            f"'Payment match ambiguous' reviews); expected bypass. "
            f"Reasons: {[r.review_reason for r in ambiguous_reviews]}"
        )
        corrected = [
            e
            for e in report.capital_entries
            if normalize_asset_ticker(e.asset) == "EUROC"
            and normalize_platform_name(e.wallet) == "Wirex"
            and e.proceeds_eur != 0
        ]
        assert corrected, (
            "flag-on: expected at least one EUROC/Wirex lot to be corrected under "
            "the resolver-based path; all lots still have proceeds=0"
        )

    def test_rezero_block_skipped_when_flag_on(self, tmp_path: Path) -> None:
        """Flag on AND SPOT_DISPOSAL on: re-zero block is a no-op for PAYMENT rows.

        The ``payment_ogr_collision`` corpus has ONE Payment disposal + ONE OGR
        Loss row on the same key. Under ``(payment_on, spot_on)``, the OGR
        override SKIPS the PAYMENT row (Task 3 spot_disposal_keys filter
        excludes it), so the residual the re-zero block exists to close cannot
        occur. The re-zero snapshot/restore block is bypassed (Invariant 8);
        the payment-proceeds correction fires via
        ``infer_payment_proceeds_active``.

        Discriminating assertion: with both flags on, the OGR override does NOT
        mutate the PAYMENT row (``ogr_validation`` is None on the resulting
        aggregated row, vs. populated under the legacy path where the override
        DOES mutate it and the re-zero block restores proceeds to 0).
        """
        jurisdiction = _make_jurisdiction(payment_flag=True, spot_flag=True)
        report = load_koinly_crypto_report(
            _PAYMENT_OGR_COLLISION_DIR, jurisdiction=jurisdiction
        )
        assert report is not None
        rows = _capital_by_key(report, "EUROC", "Wirex")
        assert rows, "expected at least one EUROC/Wirex aggregated row"
        entry = rows[0]
        # OGR override SKIPPED the PAYMENT row (spot_disposal_keys filter
        # excluded it); ogr_validation is None because the override did not
        # run for this row. Under the legacy path, the override WOULD have run
        # and ogr_validation WOULD be populated (the re-zero block then
        # restored proceeds to 0 for the payment-proceeds correction).
        assert entry.ogr_validation is None, (
            f"flag-on: expected OGR override to skip the PAYMENT row (ogr_validation "
            f"is None); got ogr_validation={entry.ogr_validation}. The re-zero "
            f"block bypass depends on the OGR override NOT mutating PAYMENT rows."
        )
        # The payment-proceeds correction still fires (EUROC is an EUR-pegged
        # stablecoin; Net Value 0 -> eur_par proceeds = amount = 100).
        assert entry.proceeds_eur == Decimal("100.00000000"), (
            f"flag-on: expected payment-proceeds correction to set proceeds to "
            f"EUR par (100); got {entry.proceeds_eur}"
        )

    def test_count_gate_runs_when_flag_off(self, tmp_path: Path) -> None:
        """Flag off: count-equality gate AND re-zero block run exactly as today.

        With ``treatment_payment_via_resolver=False``, the count-equality gate
        in ``correct_payment_proceeds`` runs unchanged; with 2 CG lots + 1 TH
        row on the same key, the gate emits a "Payment match ambiguous" review
        entry and NO lot is corrected. Pins Invariant 1 (bypass, not deletion)
        + Invariant 8 (the legacy path remains reachable when the flag is off).
        """
        koinly_dir = _write_count_mismatch_scenario(tmp_path)
        jurisdiction = _make_jurisdiction(payment_flag=False)
        report = load_koinly_crypto_report(koinly_dir, jurisdiction=jurisdiction)
        assert report is not None
        ambiguous_reviews = [
            r
            for r in report.review_entries
            if "ambiguous" in (r.review_reason or "").lower()
        ]
        assert ambiguous_reviews, (
            "flag-off (legacy): expected the count-equality gate to emit a "
            "'Payment match ambiguous' review entry; gate did not run"
        )
        # No lot was corrected (proceeds stays 0).
        corrected = [
            e
            for e in report.capital_entries
            if normalize_asset_ticker(e.asset) == "EUROC"
            and normalize_platform_name(e.wallet) == "Wirex"
            and e.proceeds_eur != 0
        ]
        assert not corrected, (
            "flag-off (legacy): expected zero corrected lots (count-equality "
            "gate blocks); at least one lot was corrected"
        )

    def test_mixed_state_infer_off_resolver_on_is_documented_noop(
        self, tmp_path: Path
    ) -> None:
        """``infer_payment_proceeds=False, treatment_payment_via_resolver=True`` is a documented no-op.

        Documents the mixed-state semantics: ``treatment_payment_via_resolver``
        governs ONLY the identification path (which TH rows are PAYMENT); the
        ``infer_payment_proceeds`` flag governs whether the correction runs at
        all. When ``infer_payment_proceeds=False``, neither the count-equality
        gate NOR the resolver-based identification path fires; the payment-
        proceeds correction does NOT run. The two flags are independent.

        Under this mixed state, all lots retain their original proceeds (the
        count-equality gate does not run, and no correction fires); no review
        entry is appended by ``correct_payment_proceeds`` (the function is not
        called).
        """
        koinly_dir = _write_count_mismatch_scenario(tmp_path)
        # infer_payment_proceeds=False + treatment_payment_via_resolver=True:
        # the resolver identifies PAYMENT rows but the correction does not run.
        jurisdiction = _make_jurisdiction(
            payment_flag=True, infer_payment_proceeds=False
        )
        report = load_koinly_crypto_report(koinly_dir, jurisdiction=jurisdiction)
        assert report is not None
        # The resolver still identifies the row as PAYMENT (mixed state is
        # observable only via the absence of correction, not via an error).
        # All EUROC/Wirex lots retain their original proceeds (0.0).
        for e in report.capital_entries:
            if (
                normalize_asset_ticker(e.asset) == "EUROC"
                and normalize_platform_name(e.wallet) == "Wirex"
            ):
                assert e.proceeds_eur == Decimal("0.0"), (
                    f"mixed-state: expected payment-proceeds correction to NOT fire "
                    f"(infer_payment_proceeds=False); got proceeds={e.proceeds_eur}"
                )
        # No "Payment match ambiguous" review either (count-equality gate
        # also requires infer_payment_proceeds_active to be reachable, since
        # correct_payment_proceeds is only called under that guard).
        ambiguous_reviews = [
            r
            for r in report.review_entries
            if "ambiguous" in (r.review_reason or "").lower()
        ]
        assert not ambiguous_reviews, (
            "mixed-state: count-equality gate emitted a review (correct_payment_"
            "proceeds was called); expected no call when infer_payment_proceeds=False"
        )

    def test_payment_flip_with_spot_disposal_off_still_closes_residual(
        self, tmp_path: Path
    ) -> None:
        """``(spot_off, payment_on)`` partial rollback: re-zero block STILL runs.

        r7 Medium #2: the PAYMENT flip's re-zero bypass depends on the
        SPOT_DISPOSAL flip ALSO being ON (so OGR skips PAYMENT rows). Under
        partial rollback ``(spot_off, payment_on)``, the OGR override STILL
        mutates PAYMENT rows' proceeds (Task 3 OFF means spot_disposal_keys
        filter is NOT applied), so the re-zero snapshot/restore block MUST
        still run to restore proceeds=0; otherwise the payment-proceeds
        correction sees proceeds != 0 and skips the row entirely (the
        candidate gate at ``payment_proceeds.py:615``).

        Discriminating assertion: with ``(spot_off, payment_on, infer=on)``,
        the resulting EUROC/Wirex lot's proceeds is the EUR-par corrected
        value (100), NOT the OGR-mutated value (15). This proves the re-zero
        block restored proceeds to 0 BEFORE the correction fired.
        """
        koinly_dir = _write_residual_scenario(tmp_path)
        jurisdiction = _make_jurisdiction(
            payment_flag=True, spot_flag=False, infer_payment_proceeds=True
        )
        report = load_koinly_crypto_report(koinly_dir, jurisdiction=jurisdiction)
        assert report is not None
        rows = _capital_by_key(report, "EUROC", "Wirex")
        assert rows, "expected at least one EUROC/Wirex aggregated row"
        entry = rows[0]
        # The payment-proceeds correction fired (proceeds non-zero, equal to
        # the EUR-par amount 100). If the re-zero block had been bypassed, the
        # OGR override would have mutated proceeds to 15 and the correction
        # would have skipped the row (proceeds != 0 candidate gate).
        assert entry.proceeds_eur == Decimal("100.00000000"), (
            f"(spot_off, payment_on): expected re-zero block to restore proceeds=0 "
            f"then payment-proceeds correction to set EUR par (100); got "
            f"proceeds={entry.proceeds_eur}. The re-zero block was incorrectly "
            f"bypassed under partial rollback (Task 3 OFF)."
        )
        # OGR override DID run (spot_flag=OFF means Task 3 filter is not
        # applied); ogr_validation is populated.
        assert entry.ogr_validation is not None, (
            "(spot_off, payment_on): expected OGR override to still mutate the "
            "PAYMENT row (Task 3 OFF); ogr_validation is None"
        )
