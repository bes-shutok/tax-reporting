"""Phase D Task 8b - Flag-isolation parametrized test (r7 Medium #5).

Pins Evaluation Criterion "Flag isolation" (plan lines 228-231): flipping ONE
treatment's flag to False must toggle ONLY that treatment's legacy adapter
reachability; the other five treatments' legacy adapters remain unaffected.
The assertion signal is "legacy adapter reachability" (``mock.patch`` on the
adapter function or its discriminator kwarg), NOT output equality. Two
configurations can produce identical output while both run the legacy adapter
- output equality is a necessary but not sufficient condition for isolation
(per r7 Medium #5).

Parametrized over the six ``Treatment`` members. For each case, the
corresponding ``treatment_X_via_resolver`` flag is set to False (the other
five to True), the pipeline runs on a fixture containing a row of the
corresponding treatment, and the test asserts in a SINGLE pipeline run:

  (c) the legacy adapter for THAT treatment is reached on the LEGACY path
      (flag off);
  (d) the legacy adapters for the OTHER treatments (where distinguishable)
      are NOT reached.

Discriminating signal per treatment (verified at authoring time):

  - SPOT_DISPOSAL: ``apply_ogr_event_level`` is called in BOTH flag states;
    the discriminator is the ``spot_disposal_keys`` kwarg. Flag-off (legacy)
    passes ``spot_disposal_keys=None`` (no treatment filter); flag-on
    (resolver) passes a non-empty set. The assertion checks the kwarg value.

  - PAYMENT: ``correct_payment_proceeds`` is called in BOTH flag states; the
    discriminator is the ``via_resolver`` kwarg. Flag-off (legacy) passes
    ``via_resolver=False``; flag-on passes ``True``.

  - LOAN_REPAYMENT: ``discover_loan_affected_assets`` is called in BOTH flag
    states; the discriminator is the ``via_resolver`` kwarg. Flag-off
    (legacy) passes ``via_resolver=False``; flag-on passes ``True``.

  - DERIVATIVES_CLOSE: ``find_derivatives_th_events`` is the LEGACY
    identification function. Under flag-off, ``apply_derivatives_dedup``
    calls it; under flag-on, it calls ``find_derivatives_th_events_from_transactions``
    instead. The discriminator IS whether ``find_derivatives_th_events``
    itself is called (``assert_called`` under flag-off).

  - REWARD_AIRDROP_LP: ``token_origin.resolve_treatment`` is consulted by
    ``TokenOriginResolver.__init__`` ONLY under flag-on (``via_resolver=True``).
    Under flag-off, the inline-literal path runs without consulting the
    resolver. The discriminator IS whether ``resolve_treatment`` was called
    from ``token_origin`` (``assert_not_called`` under flag-off; this is the
    inverse signal - there is no clean "legacy adapter IS called" target
    because ``_index_row`` always runs).

  - OTHER: no legacy adapter. The case asserts byte-identical pipeline
    output between flag-on and flag-off (true no-op; negative control).

The (d) clause: each case configures the jurisdiction gates so ONLY the
corresponding pipeline stage is enabled; the other four config-gated adapters
are structurally unreachable. For DERIVATIVES_CLOSE, ``use_other_gains_report=True``
(which the dedup gate requires) coenables ``apply_ogr_event_level``; the
SPOT_DISPOSAL adapter is exempt from the (d) clause for that case (its
reachability is driven by the shared config gate, not the SPOT_DISPOSAL
treatment flag under test).

A second test, ``test_payment_flag_with_spot_off_runs_rezero_block``, pins
r7 Medium #2 / Invariant 8: the re-zero snapshot/restore block bypass
requires BOTH the PAYMENT and SPOT_DISPOSAL flags ON. Under partial rollback
``(payment_on, spot_off)``, the block MUST remain active so the OGR-mutation
residual closes. The re-zero block is INLINE in ``crypto_reporting.py``
(lines 405-415 snapshot, 478-495 restore) with no encapsulating helper
function; the discriminator is the inline ``dataclasses.replace`` call in
the restore branch, patched at
``tax_reporting.application.crypto_reporting.replace`` (with ``wraps=`` so
the real replace still runs).
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

import tax_reporting.application.crypto.derivatives_dedup as dd_mod
import tax_reporting.application.crypto_reporting as cr_mod
import tax_reporting.application.token_origin as to_mod
from tax_reporting.application.crypto_reporting import load_koinly_crypto_report
from tax_reporting.infrastructure.config import TaxJurisdictionConfig

_MULTI_LOT_OGR_DIR = Path("resources/source/example/2025/koinly/multi_lot_ogr")
_PAYMENT_OGR_COLLISION_DIR = Path(
    "resources/source/example/2025/koinly/payment_ogr_collision"
)
_LOAN_AFFECTED_REBUILD_DIR = Path(
    "resources/source/example/2025/koinly/loan_affected_rebuild"
)
_DERIVATIVES_CLOSE_DIR = Path(
    "resources/source/example/2025/koinly/derivatives_close"
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


def _write_reward_airdrop_lp_scenario(tmp_path: Path) -> Path:
    """Build a temp Koinly directory with a Reward-tagged crypto_deposit row.

    The committed corpus has NO scenario with reward/airdrop/lp crypto_deposit
    rows, so this test authors a synthetic TH inline (committed test data per
    crypto_implementation_guidelines.md). The fixture is minimal: one Reward
    deposit + empty CG/OGR/Income. Under the flag-off path, the token_origin
    inline-literal identification path runs (the legacy adapter). Under
    flag-on, the resolver path runs.
    """
    koinly_dir = tmp_path / "reward_airdrop_lp"
    koinly_dir.mkdir()
    (koinly_dir / "koinly_2025_transaction_history.csv").write_text(
        "\n".join(
            [
                "Transaction report 2025",
                "",
                _TH_HEADER,
                # Reward deposit: 1.0 RWD received on Demo Spot, Tag=Reward.
                '2025-04-10 08:00:00 UTC,crypto_deposit,Reward,,,,,'
                'Demo Spot,"1,00000000",RWD,,,,,,,,,,,'
                "Reward deposit (flag-isolation fixture)",
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


def _write_other_only_scenario(tmp_path: Path) -> Path:
    """Build a temp Koinly directory whose sole TH row resolves to OTHER.

    A single crypto_deposit (EUROC purchase at par on Wirex, no tag) resolves
    to Treatment.OTHER. No CG/OGR/Income data rows; the pipeline emits empty
    lists. Toggling treatment_other_via_resolver must produce byte-identical
    output (the flag is a true no-op; OTHER has no legacy adapter).
    """
    koinly_dir = tmp_path / "other_only"
    koinly_dir.mkdir()
    (koinly_dir / "koinly_2025_transaction_history.csv").write_text(
        "\n".join(
            [
                "Transaction report 2025",
                "",
                _TH_HEADER,
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


def _write_residual_scenario(tmp_path: Path) -> Path:
    """Build a temp Koinly directory whose OGR override mutates a PAYMENT row.

    One Payment disposal (Tag="Payment") with proceeds 0 + one OGR Loss row
    on the same legacy ``(2025-06-15, EUROC, Wirex)`` key. Under
    ``(payment_on, spot_off)`` partial rollback, the OGR override mutates the
    PAYMENT row's proceeds; the re-zero snapshot/restore block MUST run to
    restore proceeds=0 so the payment-proceeds correction fires.
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


def _make_jurisdiction(  # noqa: PLR0913  # one kwarg per flag/gate for test clarity
    *,
    spot: bool = True,
    payment: bool = True,
    loan: bool = True,
    derivatives: bool = True,
    reward: bool = True,
    other: bool = True,
    use_other_gains_report: bool = False,
    separate_derivatives_reporting: bool = False,
    infer_payment_proceeds: bool = False,
    exclude_loan_repayment_gains: bool = False,
) -> TaxJurisdictionConfig:
    """Build a TEST TaxJurisdictionConfig for the flag-isolation matrix.

    The six ``treatment_*_via_resolver`` flags default True; each parametrize
    case flips exactly one to False. The four config gates
    (``use_other_gains_report``, ``separate_derivatives_reporting``,
    ``infer_payment_proceeds``, ``exclude_loan_repayment_gains``) are set per
    case so the corresponding treatment's pipeline stage is enabled.
    """
    return TaxJurisdictionConfig(
        country="TEST",
        fiscal_year=2025,
        exclude_loan_repayment_gains=exclude_loan_repayment_gains,
        zero_basis_review_threshold=Decimal("500"),
        use_other_gains_report=use_other_gains_report,
        separate_derivatives_reporting=separate_derivatives_reporting,
        infer_payment_proceeds=infer_payment_proceeds,
        treatment_spot_disposal_via_resolver=spot,
        treatment_payment_via_resolver=payment,
        treatment_loan_repayment_via_resolver=loan,
        treatment_derivatives_close_via_resolver=derivatives,
        treatment_reward_airdrop_lp_via_resolver=reward,
        treatment_other_via_resolver=other,
    )


# Mock target module paths (verified at authoring time). If a legacy adapter
# moves between Phase D landing and Phase E deletion, these paths update in
# lockstep. All five are patched in a SINGLE pipeline run.
_MOCK_TARGETS = {
    "SPOT_DISPOSAL": "tax_reporting.application.crypto_reporting.apply_ogr_event_level",
    "PAYMENT": "tax_reporting.application.crypto_reporting.correct_payment_proceeds",
    "LOAN_REPAYMENT": "tax_reporting.application.crypto_reporting.discover_loan_affected_assets",
    "DERIVATIVES_CLOSE": "tax_reporting.application.crypto.derivatives_dedup.find_derivatives_th_events",
    # REWARD_AIRDROP_LP uses the inverse signal (see module docstring).
    "REWARD_AIRDROP_LP_INVERSE": "tax_reporting.application.token_origin.resolve_treatment",
}


def _build_case(
    treatment: str, tmp_path: Path
) -> tuple[TaxJurisdictionConfig, Path, frozenset[str]]:
    """Build the jurisdiction + fixture + coenabled set for a parametrize case.

    Each case flips exactly one flag to False and sets the config gates so
    the corresponding pipeline stage is enabled. Returns the jurisdiction,
    the fixture directory, AND the set of OTHER treatments whose legacy
    adapters are COENABLED by the case's config gates (and therefore exempt
    from the ``assert_not_called`` clause). For example, the DERIVATIVES_CLOSE
    case requires ``use_other_gains_report=True`` (for the dedup gate), which
    coenables the SPOT_DISPOSAL OGR override (``apply_ogr_event_level``);
    SPOT_DISPOSAL is in the coenabled set so the isolation assertion does not
    falsely flag it.
    """
    if treatment == "SPOT_DISPOSAL":
        return (
            _make_jurisdiction(spot=False, use_other_gains_report=True),
            _MULTI_LOT_OGR_DIR,
            frozenset(),
        )

    if treatment == "PAYMENT":
        return (
            _make_jurisdiction(payment=False, infer_payment_proceeds=True),
            _PAYMENT_OGR_COLLISION_DIR,
            frozenset(),
        )

    if treatment == "LOAN_REPAYMENT":
        return (
            _make_jurisdiction(loan=False, exclude_loan_repayment_gains=True),
            _LOAN_AFFECTED_REBUILD_DIR,
            frozenset(),
        )

    if treatment == "DERIVATIVES_CLOSE":
        # ``use_other_gains_report=True`` coenables ``apply_ogr_event_level``
        # (the OGR override runs whenever use_other_gains_report is True,
        # regardless of the SPOT_DISPOSAL flag). SPOT_DISPOSAL is therefore
        # in the coenabled set.
        return (
            _make_jurisdiction(
                derivatives=False,
                use_other_gains_report=True,
                separate_derivatives_reporting=True,
            ),
            _DERIVATIVES_CLOSE_DIR,
            frozenset({"SPOT_DISPOSAL"}),
        )

    if treatment == "REWARD_AIRDROP_LP":
        return (
            _make_jurisdiction(reward=False),
            _write_reward_airdrop_lp_scenario(tmp_path),
            frozenset(),
        )

    raise ValueError(f"unknown treatment: {treatment}")


def _kwarg_from_calls(
    mock_obj: mock.MagicMock, kwarg: str
) -> list[Any]:
    """Extract the ``kwarg`` value from every recorded call on ``mock_obj``.

    Returns the list of values (one per call that included the kwarg); calls
    that omitted the kwarg contribute ``None`` via ``.get``.
    """
    return [call.kwargs.get(kwarg) for call in mock_obj.call_args_list]


@pytest.mark.unit
class TestPhaseDFlagIsolation:
    """Parametrized flag-isolation test (r7 Medium #5).

    Each parametrize case flips exactly one ``treatment_*_via_resolver`` flag
    to False, runs the pipeline on a fixture of the corresponding treatment,
    and asserts the toggled treatment's legacy adapter is reached on the
    LEGACY path while the other config-gated adapters are not reached. The
    assertion signal is legacy-adapter reachability / discriminator kwarg
    (``mock.patch``), not output equality.
    """

    @pytest.mark.parametrize(
        "treatment",
        [
            "SPOT_DISPOSAL",
            "PAYMENT",
            "LOAN_REPAYMENT",
            "DERIVATIVES_CLOSE",
            "REWARD_AIRDROP_LP",
            "OTHER",
        ],
    )
    def test_each_flag_independently_toggles_its_legacy_adapter(
        self,
        treatment: str,
        tmp_path: Path,
    ) -> None:
        """Flip one flag to False; assert only its legacy adapter is reached.

        For five of the six treatments (SPOT_DISPOSAL, PAYMENT,
        LOAN_REPAYMENT, DERIVATIVES_CLOSE, REWARD_AIRDROP_LP) the assertion
        is via ``mock.patch`` on the legacy adapter or its discriminator
        kwarg in a SINGLE pipeline run. The toggled treatment's legacy
        adapter IS reached on the legacy path; the other four config-gated
        adapters are NOT reached.

        REWARD_AIRDROP_LP uses the inverse signal (see module docstring):
        ``token_origin.resolve_treatment`` is NOT called under flag-off.

        OTHER has no legacy adapter; its case asserts byte-identical pipeline
        output between flag-on and flag-off (the flag is a true no-op).
        """
        if treatment == "OTHER":
            self._assert_other_is_noop(tmp_path)
            return

        jurisdiction, fixture_dir, coenabled = _build_case(treatment, tmp_path)

        # Patch all five signals in a single pipeline run. Use ``wraps=`` so
        # the real function still runs (the pipeline needs its return value);
        # the mock tracks the call and kwargs.
        with (
            mock.patch(
                _MOCK_TARGETS["SPOT_DISPOSAL"],
                wraps=cr_mod.apply_ogr_event_level,
            ) as m_spot,
            mock.patch(
                _MOCK_TARGETS["PAYMENT"],
                wraps=cr_mod.correct_payment_proceeds,
            ) as m_payment,
            mock.patch(
                _MOCK_TARGETS["LOAN_REPAYMENT"],
                wraps=cr_mod.discover_loan_affected_assets,
            ) as m_loan,
            mock.patch(
                _MOCK_TARGETS["DERIVATIVES_CLOSE"],
                wraps=dd_mod.find_derivatives_th_events,
            ) as m_deriv,
            mock.patch(
                _MOCK_TARGETS["REWARD_AIRDROP_LP_INVERSE"],
                wraps=to_mod.resolve_treatment,
            ) as m_reward_resolve,
        ):
            report = load_koinly_crypto_report(
                fixture_dir, jurisdiction=jurisdiction
            )
            assert report is not None, "load_koinly_crypto_report returned None"

            self._assert_toggled_on_legacy_path(
                treatment,
                m_spot,
                m_payment,
                m_loan,
                m_deriv,
                m_reward_resolve,
            )
            self._assert_other_four_not_called(
                treatment, coenabled, m_spot, m_payment, m_loan, m_deriv
            )

    def _assert_toggled_on_legacy_path(  # noqa: PLR0913  # one mock per treatment for test clarity
        self,
        treatment: str,
        m_spot: mock.MagicMock,
        m_payment: mock.MagicMock,
        m_loan: mock.MagicMock,
        m_deriv: mock.MagicMock,
        m_reward_resolve: mock.MagicMock,
    ) -> None:
        """(c) The toggled treatment's legacy adapter is reached on the legacy path.

        The discriminator per treatment (see module docstring):
          - SPOT_DISPOSAL: ``spot_disposal_keys is None`` on the call.
          - PAYMENT: ``via_resolver is False`` on the call.
          - LOAN_REPAYMENT: ``via_resolver is False`` on the call.
          - DERIVATIVES_CLOSE: ``find_derivatives_th_events`` IS called.
          - REWARD_AIRDROP_LP (inverse): ``resolve_treatment`` NOT called.
        """
        if treatment == "SPOT_DISPOSAL":
            assert m_spot.called, (
                "SPOT_DISPOSAL flag-off: expected apply_ogr_event_level to be "
                "called; it was not."
            )
            sdk_values = _kwarg_from_calls(m_spot, "spot_disposal_keys")
            # Flag-off (legacy): spot_disposal_keys MUST be None (no
            # treatment filter applied).
            assert any(v is None for v in sdk_values), (
                "SPOT_DISPOSAL flag-off: expected at least one call with "
                "spot_disposal_keys=None (legacy path, no treatment filter); "
                f"got values={sdk_values!r}."
            )

        elif treatment == "PAYMENT":
            assert m_payment.called, (
                "PAYMENT flag-off: expected correct_payment_proceeds to be "
                "called; it was not."
            )
            vr_values = _kwarg_from_calls(m_payment, "via_resolver")
            assert any(v is False for v in vr_values), (
                "PAYMENT flag-off: expected at least one call with "
                f"via_resolver=False (legacy count-equality gate path); "
                f"got values={vr_values!r}."
            )

        elif treatment == "LOAN_REPAYMENT":
            assert m_loan.called, (
                "LOAN_REPAYMENT flag-off: expected discover_loan_affected_assets "
                "to be called; it was not."
            )
            vr_values = _kwarg_from_calls(m_loan, "via_resolver")
            assert any(v is False for v in vr_values), (
                "LOAN_REPAYMENT flag-off: expected at least one call with "
                "via_resolver=False (legacy _LOAN_PRINCIPAL_TAGS membership "
                f"path); got values={vr_values!r}."
            )

        elif treatment == "DERIVATIVES_CLOSE":
            assert m_deriv.called, (
                "DERIVATIVES_CLOSE flag-off: expected find_derivatives_th_events "
                "to be called (legacy internal tag classifier path); it was not."
            )

        elif treatment == "REWARD_AIRDROP_LP":
            # Inverse signal: under reward flag-off, the legacy inline-literal
            # path runs and resolve_treatment is NOT called from token_origin.
            m_reward_resolve.assert_not_called(), (
                "REWARD_AIRDROP_LP flag-off: expected legacy inline-literal "
                "path to run without consulting resolve_treatment from "
                f"token_origin; got {m_reward_resolve.call_count} call(s)."
            )

    def _assert_other_four_not_called(  # noqa: PLR0913  # one mock per treatment for test clarity
        self,
        toggled: str,
        coenabled: frozenset[str],
        m_spot: mock.MagicMock,
        m_payment: mock.MagicMock,
        m_loan: mock.MagicMock,
        m_deriv: mock.MagicMock,
    ) -> None:
        """(d) The four non-toggled config-gated adapters are NOT called.

        Each case configures the jurisdiction so the toggled treatment's
        pipeline stage is enabled. Some config gates coenable other
        adapters (e.g. ``use_other_gains_report=True`` coenables
        ``apply_ogr_event_level`` for the DERIVATIVES_CLOSE case); those
        coenabled adapters are exempt from the ``assert_not_called`` clause
        (their reachability is driven by the shared config gate, not by the
        treatment flag under test).
        """
        if toggled != "SPOT_DISPOSAL" and "SPOT_DISPOSAL" not in coenabled:
            m_spot.assert_not_called()
        if toggled != "PAYMENT" and "PAYMENT" not in coenabled:
            m_payment.assert_not_called()
        if toggled != "LOAN_REPAYMENT" and "LOAN_REPAYMENT" not in coenabled:
            m_loan.assert_not_called()
        if toggled != "DERIVATIVES_CLOSE" and "DERIVATIVES_CLOSE" not in coenabled:
            m_deriv.assert_not_called()

    def _assert_other_is_noop(self, tmp_path: Path) -> None:
        """OTHER case: flag is a true no-op (byte-identical output).

        Runs the pipeline on an OTHER-only fixture with
        treatment_other_via_resolver=True and =False; asserts the resulting
        capital/reward/review/derivatives lists are byte-identical. OTHER
        has no legacy adapter; the flag exists for symmetry and
        forward-compatibility (a future OTHER-routed behavior would use it).
        This is the negative-control case (plan line 915): no
        ``assert_called`` check runs.
        """
        fixture_dir = _write_other_only_scenario(tmp_path)
        jurisdiction_on = _make_jurisdiction(other=True)
        jurisdiction_off = _make_jurisdiction(other=False)
        report_on = load_koinly_crypto_report(
            fixture_dir, jurisdiction=jurisdiction_on
        )
        report_off = load_koinly_crypto_report(
            fixture_dir, jurisdiction=jurisdiction_off
        )
        assert report_on is not None, (
            "load_koinly_crypto_report returned None for OTHER-only fixture (flag on)"
        )
        assert report_off is not None, (
            "load_koinly_crypto_report returned None for OTHER-only fixture (flag off)"
        )
        assert report_on.capital_entries == report_off.capital_entries, (
            "OTHER flag toggle changed capital_entries (expected byte-identical)"
        )
        assert report_on.reward_entries == report_off.reward_entries, (
            "OTHER flag toggle changed reward_entries (expected byte-identical)"
        )
        assert report_on.review_entries == report_off.review_entries, (
            "OTHER flag toggle changed review_entries (expected byte-identical)"
        )
        assert report_on.derivatives_entries == report_off.derivatives_entries, (
            "OTHER flag toggle changed derivatives_entries (expected byte-identical)"
        )

    def test_payment_flag_with_spot_off_runs_rezero_block(
        self, tmp_path: Path
    ) -> None:
        """``(payment_on, spot_off)`` partial rollback: re-zero block runs.

        r7 Medium #2 / Invariant 8: the re-zero snapshot/restore block bypass
        requires BOTH the PAYMENT and SPOT_DISPOSAL flags ON. Under partial
        rollback ``(payment_on, spot_off, infer=on)``, the OGR override
        STILL mutates the PAYMENT row's proceeds (Task 3 OFF means no
        spot_disposal_keys filter), so the re-zero restore block MUST run
        to restore proceeds=0 before the payment-proceeds correction fires.

        The re-zero block is INLINE in crypto_reporting.py (lines 405-415
        snapshot, 478-495 restore) with no encapsulating helper function.
        The restore branch calls ``dataclasses.replace`` (imported as
        ``replace`` in crypto_reporting); we patch
        ``tax_reporting.application.crypto_reporting.replace`` with
        ``wraps=`` so the real replace still runs, and detect the restore
        branch firing by observing the call count. Pairs with
        ``test_payment_flip_with_spot_disposal_off_still_closes_residual``
        in Task 4.
        """
        fixture_dir = _write_residual_scenario(tmp_path)
        jurisdiction = _make_jurisdiction(
            payment=True,
            spot=False,
            infer_payment_proceeds=True,
            use_other_gains_report=True,
        )
        with mock.patch(
            "tax_reporting.application.crypto_reporting.replace",
            wraps=cr_mod.replace,
        ) as mock_replace:
            report = load_koinly_crypto_report(
                fixture_dir, jurisdiction=jurisdiction
            )
            assert report is not None, "load_koinly_crypto_report returned None"
            # The re-zero restore branch called replace at least once
            # (mutated the PAYMENT row's proceeds back to 0). The snapshot
            # branch only captures indices (no replace); the restore branch
            # is the ONLY re-zero-block site that calls replace.
            assert mock_replace.called, (
                "(payment_on, spot_off): expected re-zero restore branch to "
                "call replace on the OGR-mutated PAYMENT row; it did not. "
                "The re-zero block was incorrectly bypassed under partial "
                "rollback (Invariant 8 violation)."
            )
        # Sanity: the payment-proceeds correction fired (proceeds non-zero,
        # EUR par 100), proving the re-zero block restored proceeds=0 before
        # the correction. Mirrors Task 4's
        # test_payment_flip_with_spot_disposal_off_still_closes_residual.
        euronc_rows = [
            e
            for e in report.capital_entries
            if e.asset == "EUROC" and e.wallet == "Wirex"
        ]
        assert euronc_rows, "expected at least one EUROC/Wirex row"
        assert euronc_rows[0].proceeds_eur == Decimal("100.00000000"), (
            f"(payment_on, spot_off): expected payment-proceeds correction to "
            f"set EUR par (100); got {euronc_rows[0].proceeds_eur}. The re-zero "
            f"block did not restore proceeds=0 before the correction fired."
        )
