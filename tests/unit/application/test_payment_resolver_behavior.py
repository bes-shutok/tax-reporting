"""PAYMENT treatment - resolver-path characterization (Phase E).

Phase E deleted the legacy ``_DEFAULT_PAYMENT_TAGS`` scanner, the
count-equality gate, the re-zero snapshot/restore block, and the
``treatment_payment_via_resolver`` flag (Tasks 3, 6, 7). Identification of
PAYMENT disposals is now resolver-only: ``resolve_treatment`` over the
pre-built ``list[Transaction]`` (built ONCE in the production caller and
passed through ``correct_payment_proceeds``) is the sole source of the
PAYMENT discriminator.

The Phase-D flag-mechanic tests (count-equality gate divergence,
re-zero restore under partial rollback) were deleted with the flag. The
surviving resolver-behavior test pins the identification source.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tax_reporting.application.crypto.derivatives_filter import (
    _load_derivatives_labels_config,
)
from tax_reporting.application.crypto.treatment_resolver import (
    TreatmentConfig,
    resolve_treatment,
)
from tax_reporting.application.crypto_reporting import build_transactions_from_th
from tax_reporting.domain.treatment import Treatment

_PAYMENT_OGR_COLLISION_DIR = Path(
    "resources/source/example/2025/koinly/payment_ogr_collision"
)


def _scenario_th_csv() -> Path:
    """Path to the ``payment_ogr_collision`` TH fixture (committed)."""
    return _PAYMENT_OGR_COLLISION_DIR / "koinly_2025_transaction_history.csv"


def _treatment_config_for_year(year: int) -> TreatmentConfig:
    """Build a TreatmentConfig with the production derivatives labels injected."""
    return TreatmentConfig(
        derivatives_tags=_load_derivatives_labels_config("koinly", year),
    )


@pytest.mark.unit
class TestPaymentResolverBehavior:
    """Pin the PAYMENT identification on the resolver path."""

    def test_resolver_identifies_payment(self) -> None:
        """The ``payment_ogr_collision`` TH row (``Tag="Payment"``) resolves to PAYMENT.

        Pins the identification source (Phase B resolver) for the corpus row
        the PAYMENT pipeline branch gates on. Under default TreatmentConfig
        with the production derivatives labels injected, a ``Tag="Payment"``
        row resolves to PAYMENT (default payment_tags is ``{"payment",
        "card payment"}``).

        Post-Phase-E this is the sole identification source: the legacy
        ``_DEFAULT_PAYMENT_TAGS`` scanner, the count-equality gate, and the
        ``treatment_payment_via_resolver`` flag are all gone.
        """
        transactions = build_transactions_from_th(_scenario_th_csv())
        assert len(transactions) == 1, (
            "payment_ogr_collision scenario drifted: expected 1 TH row"
        )
        config = _treatment_config_for_year(2025)
        treatment = resolve_treatment(transactions[0], config)
        assert treatment is Treatment.PAYMENT, (
            f"expected PAYMENT for Tag=Payment row, got {treatment.value!r}"
        )
