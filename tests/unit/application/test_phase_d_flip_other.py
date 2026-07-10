"""Phase D Task 8 - OTHER flip: true no-op on output (no legacy adapter).

Pins the per-treatment flip wiring for ``Treatment.OTHER``: when
``jurisdiction.treatment_other_via_resolver`` is True (default), the OTHER
treatment is identified via the Phase B ``resolve_treatment`` resolver. When
False, the flag is a documented no-op because OTHER has NO legacy adapter to
fall back to - the resolver IS the sole identification source, and OTHER
rows (acquisitions, transfers, loan-creation) never reach a treatment-specific
pipeline branch. The flag therefore exists for symmetry and forward-compatibility
(a future OTHER-routed behavior would consult it) but does not gate any current
output path.

The behavioral consequence: toggling ``treatment_other_via_resolver`` must
produce byte-identical pipeline output. This module asserts that property by
running the full ``load_koinly_crypto_report`` pipeline on an OTHER-only
subset (a single ``crypto_deposit`` acquisition whose resolver treatment is
``Treatment.OTHER``) with the flag on and off, and comparing the resulting
intermediate domain output (capital entries, reward entries, review entries,
derivatives entries) field-by-field. The Excel bytes themselves depend on too
many rendering modules to compare deterministically in a unit test, so the
intermediate domain layer is the tightest observable proxy for "the flag is a
true no-op on output, not just on identification" (per the task's proxy-choice
guidance).

Task 2 already landed ``treatment_other_via_resolver`` on
``TaxJurisdictionConfig``; the ``test_flag_exists_and_defaults_true`` assertion
is pre-existing GREEN from Task 2 (it pins Task 2's 1:1 mapping completeness,
not Task 8 work) and is reproduced here to document the no-op contract end to
end.
"""

from __future__ import annotations

import dataclasses
from decimal import Decimal
from pathlib import Path

import pytest

from tax_reporting.application.crypto.derivatives_dedup import (
    _load_derivatives_labels_config,
)
from tax_reporting.application.crypto.entities import CryptoTaxReport
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
    normalize_platform_name,
    parse_th_row,
    read_koinly_rows,
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


def _write_other_only_scenario(tmp_path: Path) -> Path:
    """Build a temp Koinly directory whose sole TH row resolves to ``Treatment.OTHER``.

    The single TH row is a ``crypto_deposit`` (an acquisition: no sending side,
    no special tag). Per ``resolve_treatment`` Invariant 3, a row with no
    sending currency and no matching tag resolves to ``Treatment.OTHER``.
    There are no CG/OGR/Income data rows, so the pipeline emits empty capital,
    reward, and derivatives lists regardless of the flag - the OTHER-only
    subset has no disposal to report.

    The byte-identical-output property is observable on the empty lists AND
    on the review_entries list (no review flag fires for an OTHER-only run
    under either flag state).
    """
    koinly_dir = tmp_path / "other_only"
    koinly_dir.mkdir()
    (koinly_dir / "koinly_2025_transaction_history.csv").write_text(
        "\n".join(
            [
                "Transaction report 2025",
                "",
                _TH_HEADER,
                # crypto_deposit acquisition: no sending side, no tag ->
                # resolve_treatment returns Treatment.OTHER. Five empty fields
                # after Type (Tag, Sending Wallet, Sent Amount, Sent Currency,
                # Sent Cost Basis) before Receiving Wallet, mirroring the
                # committed payment scenario's crypto_deposit row byte-for-byte.
                '2025-05-01 10:00:00 UTC,crypto_deposit,,,,,,'
                'Wirex,"100,00000000",EUROC,"100,00",,,'
                '"0,00","100,00","0,00",,,,EUROC purchase at par (OTHER-only fixture)',
            ]
        ),
        encoding="utf-8",
    )
    (koinly_dir / "koinly_2025_capital_gains_report.csv").write_text(
        "\n".join(["Capital gains report 2025", "", _CG_HEADER]),
        encoding="utf-8",
    )
    (koinly_dir / "koinly_2025_other_gains_report.csv").write_text(
        "\n".join(["Other gains report 2025", "", _OGR_HEADER]),
        encoding="utf-8",
    )
    (koinly_dir / "koinly_2025_income_report.csv").write_text(
        "\n".join(["Income report 2025", "", _INCOME_HEADER]),
        encoding="utf-8",
    )
    return koinly_dir


def _make_jurisdiction(*, other_flag: bool) -> TaxJurisdictionConfig:
    """Build a TEST TaxJurisdictionConfig exercising the OTHER flag toggle.

    ``exclude_loan_repayment_gains=False`` so the FIFO rebuild does not
    interfere; ``use_other_gains_report=False`` since the OTHER-only subset
    has no OGR rows to override. Only ``treatment_other_via_resolver`` varies.
    """
    return TaxJurisdictionConfig(
        country="TEST",
        fiscal_year=2025,
        exclude_loan_repayment_gains=False,
        zero_basis_review_threshold=Decimal("500"),
        use_other_gains_report=False,
        separate_derivatives_reporting=False,
        infer_payment_proceeds=False,
        treatment_other_via_resolver=other_flag,
    )


@pytest.mark.unit
class TestPhaseDFlipOther:
    """Pin the OTHER treatment flag as a true no-op on output."""

    def test_flag_exists_and_defaults_true(self) -> None:
        """``dataclasses.fields(TaxJurisdictionConfig)`` includes the OTHER flag.

        Pins the 1:1 Treatment-to-flag mapping (Invariant 2) for the OTHER
        member. The flag defaults to True (Invariant 3). This assertion is
        pre-existing GREEN from Task 2 (which landed all six flags); it is
        reproduced here to document the no-op contract end to end.
        """
        field_map = {
            f.name: f for f in dataclasses.fields(TaxJurisdictionConfig)
        }
        assert "treatment_other_via_resolver" in field_map, (
            "treatment_other_via_resolver must exist on TaxJurisdictionConfig "
            "(Invariant 2: 1:1 Treatment-to-flag mapping)"
        )
        # The default is True (a bool dataclass field default reads back as
        # the literal True via field.default).
        assert field_map["treatment_other_via_resolver"].default is True, (
            "treatment_other_via_resolver must default to True (Invariant 3: "
            "default ON at landing)"
        )

    def test_resolver_identifies_other_for_crypto_deposit(self, tmp_path: Path) -> None:
        """The OTHER-only ``crypto_deposit`` TH row resolves to ``Treatment.OTHER``.

        Pins the identification source (Phase B resolver) for the corpus row
        the OTHER flip nominally gates on. A ``crypto_deposit`` with no
        sending side and no tag resolves to ``Treatment.OTHER`` per Invariant 3
        of the resolver.
        """
        koinly_dir = _write_other_only_scenario(tmp_path)
        th_path = koinly_dir / "koinly_2025_transaction_history.csv"
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
        assert len(transactions) == 1, "OTHER-only fixture drifted: expected 1 TH row"
        config = TreatmentConfig(
            derivatives_tags=_load_derivatives_labels_config("koinly", 2025),
        )
        treatment = resolve_treatment(transactions[0], config)
        assert treatment is Treatment.OTHER, (
            f"expected OTHER for crypto_deposit acquisition, got {treatment.value!r}"
        )

    def test_other_treatment_byte_identical_with_or_without_flag(
        self, tmp_path: Path
    ) -> None:
        """Toggling ``treatment_other_via_resolver`` produces byte-identical output.

        The real behavioral assertion for Task 8: since OTHER has no legacy
        adapter, the flag is a true no-op on output, not just on identification.
        Running the full ``load_koinly_crypto_report`` pipeline on the
        OTHER-only subset with the flag on vs off must yield the same
        intermediate domain output (capital entries, reward entries, review
        entries, derivatives entries, loan activity, skipped zero-value
        tokens). Excel rendering depends on too many modules to compare
        deterministically in a unit test, so the intermediate domain layer is
        the tightest observable proxy (documented per the task's proxy-choice
        guidance).

        Discriminating assertion: if a future OTHER-routed behavior were
        wired (contradicting the "no special wiring" contract), the two
        reports would diverge and this test would fail.
        """
        koinly_dir = _write_other_only_scenario(tmp_path)

        jurisdiction_on = _make_jurisdiction(other_flag=True)
        jurisdiction_off = _make_jurisdiction(other_flag=False)

        report_on = load_koinly_crypto_report(koinly_dir, jurisdiction=jurisdiction_on)
        report_off = load_koinly_crypto_report(koinly_dir, jurisdiction=jurisdiction_off)
        assert report_on is not None, "flag-on: load_koinly_crypto_report returned None"
        assert report_off is not None, "flag-off: load_koinly_crypto_report returned None"

        # Row counts identical across every output list.
        _assert_report_lists_identical(report_on, report_off)

        # Field-by-field equality on capital entries (empty in this fixture,
        # but the equality check documents the contract for any future OTHER
        # row that does produce a capital entry).
        assert report_on.capital_entries == report_off.capital_entries, (
            "capital_entries diverged between flag-on and flag-off; OTHER flag "
            "is no longer a true no-op on output"
        )
        assert report_on.reward_entries == report_off.reward_entries, (
            "reward_entries diverged between flag-on and flag-off; OTHER flag "
            "is no longer a true no-op on output"
        )
        assert report_on.review_entries == report_off.review_entries, (
            "review_entries diverged between flag-on and flag-off; OTHER flag "
            "is no longer a true no-op on output"
        )
        assert report_on.derivatives_entries == report_off.derivatives_entries, (
            "derivatives_entries diverged between flag-on and flag-off; OTHER "
            "flag is no longer a true no-op on output"
        )


def _assert_report_lists_identical(
    report_on: CryptoTaxReport, report_off: CryptoTaxReport
) -> None:
    """Assert every output list on the two reports has the same length.

    Used by ``test_other_treatment_byte_identical_with_or_without_flag`` to
    surface the most coarse divergence (row count) before the field-by-field
    equality checks, so a failure message names the list that drifted.
    """
    pairs = [
        ("capital_entries", report_on.capital_entries, report_off.capital_entries),
        ("reward_entries", report_on.reward_entries, report_off.reward_entries),
        ("review_entries", report_on.review_entries, report_off.review_entries),
        ("derivatives_entries", report_on.derivatives_entries, report_off.derivatives_entries),
        ("loan_activity", report_on.loan_activity, report_off.loan_activity),
        (
            "skipped_zero_value_tokens",
            report_on.skipped_zero_value_tokens,
            report_off.skipped_zero_value_tokens,
        ),
    ]
    for name, on_list, off_list in pairs:
        assert len(on_list) == len(off_list), (
            f"{name} row count diverged: flag-on has {len(on_list)} rows, "
            f"flag-off has {len(off_list)} rows; OTHER flag is no longer a "
            f"true no-op on output"
        )
