"""DERIVATIVES_CLOSE treatment - resolver-path characterization (Phase E).

Pins the resolver-path identification for ``DERIVATIVES_CLOSE``:
``resolve_treatment`` with
``TreatmentConfig(derivatives_tags=<loaded JSON labels>)`` is the sole
identification source. Phase E deleted the legacy standalone
``find_derivatives_th_events`` CSV scanner (Task 2) and the
``treatment_derivatives_close_via_resolver`` flag (Task 6); the dedup
algorithm itself (lot-level matching via
``remove_derivatives_flagged_lots``) still runs unchanged - it consumes
the resolver-identified set.

The production caller ``load_koinly_crypto_report`` builds the
``list[Transaction]`` ONCE and passes it through the dedup entry point.
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

_DERIVATIVES_CLOSE_DIR = Path(
    "resources/source/example/2025/koinly/derivatives_close"
)


def _scenario_th_csv() -> Path:
    """Path to the ``derivatives_close`` TH fixture (committed)."""
    return _DERIVATIVES_CLOSE_DIR / "koinly_2025_transaction_history.csv"


def _treatment_config_for_year(year: int) -> TreatmentConfig:
    """Build a TreatmentConfig with the production derivatives labels injected."""
    return TreatmentConfig(
        derivatives_tags=_load_derivatives_labels_config("koinly", year),
    )


@pytest.mark.unit
class TestDerivativesCloseResolverBehavior:
    """Pin the DERIVATIVES_CLOSE identification on the resolver path."""

    def test_resolver_identifies_derivatives_close(self) -> None:
        """Both ``Realized gain`` and ``Futures fee`` TH rows resolve to DERIVATIVES_CLOSE.

        Pins the identification source (Phase B resolver) for the two corpus
        rows the DERIVATIVES_CLOSE dedup gates on. Under
        ``TreatmentConfig(derivatives_tags=<loaded JSON labels>)``, both
        ``Tag="Realized gain"`` and ``Tag="Futures fee"`` resolve to
        ``Treatment.DERIVATIVES_CLOSE`` (Phase B Invariant 5/6 - the JSON
        set is the sole source of derivatives tags, and the precedence
        orders the ``Realized gain`` overlap with reward tags to
        DERIVATIVES_CLOSE).
        """
        transactions = build_transactions_from_th(_scenario_th_csv())
        assert len(transactions) == 2, (
            "derivatives_close scenario drifted: expected 2 TH rows"
        )
        config = _treatment_config_for_year(2025)
        treatments = [resolve_treatment(tx, config) for tx in transactions]
        assert all(t is Treatment.DERIVATIVES_CLOSE for t in treatments), (
            f"expected DERIVATIVES_CLOSE for both rows; got {[t.value for t in treatments]}"
        )
