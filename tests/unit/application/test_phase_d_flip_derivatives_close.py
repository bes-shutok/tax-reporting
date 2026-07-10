"""Phase D Task 6 - DERIVATIVES_CLOSE flip: derivatives dedup classifier bypass.

Pins the per-treatment flip wiring for ``DERIVATIVES_CLOSE``: when
``jurisdiction.treatment_derivatives_close_via_resolver`` is True, the
internal tag classifier inside ``find_derivatives_th_events`` (the
``label not in labels`` membership check) is NOT consulted;
identification comes from ``resolve_treatment`` with
``TreatmentConfig(derivatives_tags=<loaded JSON labels>)``. The dedup
algorithm itself (lot-level matching via ``remove_derivatives_flagged_lots``)
still runs unchanged - it consumes the identified set regardless of how
that set was produced.

r8 Medium #1 carry-forward: the resolver needs ``Transaction`` objects;
the production caller ``load_koinly_crypto_report`` builds the
``list[Transaction]`` ONCE (Task 3 wiring step) and passes it through the
existing dedup entry point. This module does NOT re-build ``Transaction``
objects inside the dedup task.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from tax_reporting.application.crypto.derivatives_dedup import (
    _load_derivatives_labels_config,
    find_derivatives_th_events,
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
    normalize_platform_name,
    parse_th_row,
    read_koinly_rows,
)

_DERIVATIVES_CLOSE_DIR = Path(
    "resources/source/example/2025/koinly/derivatives_close"
)


def _scenario_th_csv() -> Path:
    """Path to the ``derivatives_close`` TH fixture (committed)."""
    return _DERIVATIVES_CLOSE_DIR / "koinly_2025_transaction_history.csv"


def _build_transactions_from_th(th_path: Path) -> list[Transaction]:
    """Run the sanctioned Phase A factory chain over every TH row in ``th_path``.

    Mirrors the production wiring in ``load_koinly_crypto_report`` so the
    resolver identification tests exercise the SAME construction path.
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
    derivatives_flag: bool,
) -> TaxJurisdictionConfig:
    """Build a TEST TaxJurisdictionConfig that exercises the derivatives dedup path.

    ``separate_derivatives_reporting=True`` and ``use_other_gains_report=True``
    so the dedup gate passes and the OGR override runs (the derivatives
    dedup runs only when both flags are True - see ``apply_derivatives_dedup``
    gate).
    """
    return TaxJurisdictionConfig(
        country="TEST",
        fiscal_year=2025,
        exclude_loan_repayment_gains=False,
        zero_basis_review_threshold=Decimal("500"),
        use_other_gains_report=True,
        separate_derivatives_reporting=True,
        infer_payment_proceeds=False,
        treatment_derivatives_close_via_resolver=derivatives_flag,
    )


@pytest.mark.unit
class TestPhaseDFlipDerivativesClose:
    """Pin the DERIVATIVES_CLOSE flip wiring on the dedup internal classifier."""

    def test_resolver_identifies_derivatives_close(self) -> None:
        """Both ``Realized gain`` and ``Futures fee`` TH rows resolve to DERIVATIVES_CLOSE.

        Pins the identification source (Phase B resolver) for the two corpus
        rows the DERIVATIVES_CLOSE flip gates on. Under
        ``TreatmentConfig(derivatives_tags=<loaded JSON labels>)``, both
        ``Tag="Realized gain"`` and ``Tag="Futures fee"`` resolve to
        ``Treatment.DERIVATIVES_CLOSE`` (Phase B Invariant 5/6 - the JSON
        set is the sole source of derivatives tags, and the precedence
        orders the ``Realized gain`` overlap with reward tags to
        DERIVATIVES_CLOSE).
        """
        transactions = _build_transactions_from_th(_scenario_th_csv())
        assert len(transactions) == 2, (
            "derivatives_close scenario drifted: expected 2 TH rows"
        )
        config = _treatment_config_for_year(2025)
        treatments = [resolve_treatment(tx, config) for tx in transactions]
        assert all(t is Treatment.DERIVATIVES_CLOSE for t in treatments), (
            f"expected DERIVATIVES_CLOSE for both rows; got {[t.value for t in treatments]}"
        )

    def test_internal_classifier_skipped_when_flag_on(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Flag on: ``find_derivatives_th_events`` internal classifier is NOT consulted.

        When ``treatment_derivatives_close_via_resolver=True``, identification
        delegates to the resolver; the legacy
        ``find_derivatives_th_events(transaction_history_file, labels)``
        function (whose body is the internal ``label not in labels`` classifier)
        MUST NOT be called. The dedup algorithm itself still runs (it does
        lot-level work the resolver does not do) - the dedup consumes the
        resolver-identified set instead.

        Discriminating assertion: monkeypatch ``find_derivatives_th_events``
        to raise if called. Under flag-on, the resolver path produces the
        events WITHOUT calling the classifier; the test fails if the
        implementation falls through to the legacy classifier.
        """
        def _fail_if_called(*_args, **_kwargs):
            raise AssertionError(
                "find_derivatives_th_events (legacy internal classifier) was called "
                "under treatment_derivatives_close_via_resolver=True; the flag-on path "
                "must delegate to resolve_treatment instead."
            )

        # Patch at the module's own binding so the internal call site resolves
        # to the stub (the function calls ``find_derivatives_th_events`` by name
        # within its own module).
        from tax_reporting.application.crypto import derivatives_dedup as dd_mod

        monkeypatch.setattr(dd_mod, "find_derivatives_th_events", _fail_if_called)

        jurisdiction = _make_jurisdiction(derivatives_flag=True)
        report = load_koinly_crypto_report(
            _DERIVATIVES_CLOSE_DIR, jurisdiction=jurisdiction
        )
        assert report is not None, "load_koinly_crypto_report returned None"
        # The dedup pass still ran: the report loaded successfully with the
        # resolver-produced events consumed by the dedup algorithm. The
        # assertion is that no exception was raised by the stub (the
        # internal classifier was NOT consulted).

    def test_internal_classifier_runs_when_flag_off(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Flag off: legacy internal classifier runs exactly as today.

        When ``treatment_derivatives_close_via_resolver=False``, the legacy
        ``find_derivatives_th_events(transaction_history_file, labels)``
        function IS called (its internal ``label not in labels`` classifier
        is the identification source). Pins Invariant 1 (bypass, not
        deletion) - the legacy path remains reachable when the flag is off.

        Discriminating assertion: monkeypatch ``find_derivatives_th_events``
        to a spy that records the call. Under flag-off, the spy MUST be
        called; the test fails if the legacy classifier is unreachable.
        """
        from tax_reporting.application.crypto import derivatives_dedup as dd_mod

        call_count = 0

        def _spy(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            # Delegate to the real implementation so the pipeline produces a
            # valid report (the classifier is the production path under
            # flag-off; stubbing it out would prevent the dedup from running).
            return _real_find_derivatives_th_events(*args, **kwargs)

        _real_find_derivatives_th_events = find_derivatives_th_events
        monkeypatch.setattr(dd_mod, "find_derivatives_th_events", _spy)

        jurisdiction = _make_jurisdiction(derivatives_flag=False)
        report = load_koinly_crypto_report(
            _DERIVATIVES_CLOSE_DIR, jurisdiction=jurisdiction
        )
        assert report is not None, "load_koinly_crypto_report returned None"
        assert call_count >= 1, (
            "flag-off (legacy): expected find_derivatives_th_events to be called; "
            "the legacy internal classifier is unreachable"
        )
