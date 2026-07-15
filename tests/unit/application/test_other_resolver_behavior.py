"""OTHER treatment - resolver-path characterization (Phase E).

Phase E deleted the ``treatment_other_via_resolver`` flag (Task 6).
``Treatment.OTHER`` has NO legacy adapter: the resolver IS the sole
identification source, and OTHER rows (acquisitions, transfers,
loan-creation) never reach a treatment-specific pipeline branch. The
flag existed in Phase D for symmetry only; it gated no output path.

The Phase-D flag-mechanic tests (flag-existence, flag-toggle
byte-identical) were deleted with the flag. The surviving resolver-
behavior test pins the identification source.
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


@pytest.mark.unit
class TestOtherResolverBehavior:
    """Pin the OTHER treatment identification on the resolver path."""

    def test_resolver_identifies_other_for_crypto_deposit(self, tmp_path: Path) -> None:
        """The OTHER-only ``crypto_deposit`` TH row resolves to ``Treatment.OTHER``.

        Pins the identification source (Phase B resolver) for the corpus row
        the OTHER pipeline branch nominally gates on. A ``crypto_deposit``
        with no sending side and no tag resolves to ``Treatment.OTHER`` per
        Invariant 3 of the resolver.
        """
        koinly_dir = _write_other_only_scenario(tmp_path)
        th_path = koinly_dir / "koinly_2025_transaction_history.csv"
        transactions = build_transactions_from_th(th_path)
        assert len(transactions) == 1, "OTHER-only fixture drifted: expected 1 TH row"
        config = TreatmentConfig(
            derivatives_tags=_load_derivatives_labels_config("koinly", 2025),
        )
        treatment = resolve_treatment(transactions[0], config)
        assert treatment is Treatment.OTHER, (
            f"expected OTHER for crypto_deposit acquisition, got {treatment.value!r}"
        )
