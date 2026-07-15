"""LOAN_REPAYMENT treatment - resolver-path characterization (Phase E).

Phase E deleted the legacy ``_LOAN_PRINCIPAL_TAGS`` membership branch from
``discover_loan_affected_assets`` (Task 4) and the
``treatment_loan_repayment_via_resolver`` flag (Task 6). Identification of
loan-affected assets is now resolver-only: ``resolve_treatment`` over the
pre-built ``list[Transaction]`` (built ONCE in the production caller) is
the sole source.

Per Invariant 11 the path is NOT pure resolver-delegation: it ALSO includes
``Treatment.OTHER`` rows whose normalized tag is ``"loan"`` so borrow-only
assets (collateral creation) remain in the FIFO rebuild scope (user
decision 2026-07-08: preserve legacy asset set).

The Phase-D flag-mechanic tests (legacy branch runs when flag off) were
deleted with the flag. The surviving characterization tests pin the
resolver-path identification, the Invariant 11 ``OTHER + tag=loan`` clause,
and the r7 Medium #1 tag-normalization contract.
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
from tax_reporting.application.crypto_fifo import discover_loan_affected_assets
from tax_reporting.application.crypto_reporting import build_transactions_from_th
from tax_reporting.domain.treatment import Treatment

_LOAN_AFFECTED_REBUILD_DIR = Path(
    "resources/source/example/2025/koinly/loan_affected_rebuild"
)

_TH_HEADER = (
    "Date,Type,Tag,Sending Wallet,Sent Amount,Sent Currency,Sent Cost Basis,"
    "Receiving Wallet,Received Amount,Received Currency,Received Cost Basis,"
    "Fee Amount,Fee Currency,Gain (EUR),Net Value (EUR),Fee Value (EUR),"
    "TxSrc,TxDest,TxHash,Description"
)


def _scenario_th_csv() -> Path:
    """Path to the ``loan_affected_rebuild`` TH fixture (committed)."""
    return _LOAN_AFFECTED_REBUILD_DIR / "koinly_2025_transaction_history.csv"


def _treatment_config_for_year(year: int) -> TreatmentConfig:
    """Build a TreatmentConfig with the production derivatives labels injected."""
    return TreatmentConfig(
        derivatives_tags=_load_derivatives_labels_config("koinly", year),
    )


def _fiat_codes() -> frozenset[str]:
    """Fiat codes excluded from discovery (mirrors production caller)."""
    return frozenset({"EUR", "USD"})


def _write_borrow_only_scenario(tmp_path: Path, tag: str) -> Path:
    """Build a temp TH CSV with a single ``Tag=<tag>`` crypto_deposit borrow row.

    The row resolves to ``Treatment.OTHER`` (Phase B Invariant 9:
    borrowing-side ``"loan"`` is principal creation, NOT
    ``LOAN_REPAYMENT``), so the Invariant 11 ``OTHER + normalized-tag=loan``
    clause is what keeps WBTC in scope.
    """
    th_path = tmp_path / f"th_{tag.strip().lower()}.csv"
    row = ",".join(
        [
            "2025-04-10 10:00:00 UTC",
            "crypto_deposit",
            tag,
            "",  # sending wallet empty (acquisition-side)
            "",  # sent amount
            "",  # sent currency
            "",  # sent cost basis
            "ByBit",  # receiving wallet
            '"0,10000000"',  # received amount
            "WBTC",  # received currency
            '"4000,00"',  # received cost basis
            "",  # fee amount
            "",  # fee currency
            '"0,00"',  # gain eur
            '"4000,00"',  # net value eur
            '"0,00"',  # fee value eur
            "",  # txsrc
            "",  # txdest
            "",  # txhash
            f"Borrow {tag}",  # description
        ]
    )
    content = "\n".join(["Transaction report 2025", "", _TH_HEADER, row])
    th_path.write_text(content, encoding="utf-8")
    return th_path


@pytest.mark.unit
class TestLoanRepaymentResolverBehavior:
    """Pin the LOAN_REPAYMENT identification and Invariant 11 on the resolver path."""

    def test_resolver_distinguishes_borrowing_from_repayment(self) -> None:
        """``Tag="Loan"`` resolves to OTHER; ``Tag="Loan Repayment`` to LOAN_REPAYMENT.

        Pins Phase B Invariant 9: the borrowing-side ``"loan"`` tag is
        principal creation (collateral deposit), NOT a repayment disposal.
        The resolver's ``loan_repayment_tags`` default excludes ``"loan"``;
        only ``"loan repayment"`` matches DP-001 non-taxable scope.
        """
        transactions = build_transactions_from_th(_scenario_th_csv())
        # Fixture has 3 rows: Loan (borrow), Loan Repayment, plain spot.
        assert len(transactions) == 3, (
            "loan_affected_rebuild scenario drifted: expected 3 TH rows"
        )
        borrow_tx = next(
            (tx for tx in transactions if tx.row.tag.strip().lower() == "loan"),
            None,
        )
        repayment_tx = next(
            (tx for tx in transactions if tx.row.tag.strip().lower() == "loan repayment"),
            None,
        )
        assert borrow_tx is not None, "scenario missing the Tag=Loan row"
        assert repayment_tx is not None, "scenario missing the Tag=Loan Repayment row"

        config = _treatment_config_for_year(2025)
        assert resolve_treatment(borrow_tx, config) is Treatment.OTHER, (
            "Phase B Invariant 9 violation: Tag=Loan (borrowing) must resolve to OTHER, "
            "not LOAN_REPAYMENT"
        )
        assert resolve_treatment(repayment_tx, config) is Treatment.LOAN_REPAYMENT, (
            "Tag=Loan Repayment must resolve to LOAN_REPAYMENT"
        )

    def test_loan_repayment_identification_resolver_path(self) -> None:
        """Characterization: resolver path identifies loan-affected assets.

        Phase E Task 4 deleted the ``_LOAN_PRINCIPAL_TAGS`` legacy branch.
        Loan-affected asset discovery uses ``Treatment.LOAN_REPAYMENT`` rows
        AND ``Treatment.OTHER`` rows whose normalized tag is ``"loan"``
        (Invariant 11). The ``loan_affected_rebuild`` scenario has BOTH a
        Tag=Loan borrow (WBTC) and a Tag=Loan Repayment disposal (WBTC), so
        WBTC is in scope.
        """
        th_path = _scenario_th_csv()
        transactions = build_transactions_from_th(th_path)
        config = _treatment_config_for_year(2025)
        result = discover_loan_affected_assets(
            _fiat_codes(),
            transactions=transactions,
            config=config,
        )
        # WBTC appears in both the Loan borrow row and the Loan Repayment
        # disposal row; EUR appears in the plain spot row (excluded as fiat).
        assert "WBTC" in result, (
            f"resolver path: WBTC must be in scope (Loan borrow + Loan Repayment); got {sorted(result)}"
        )

    @pytest.mark.parametrize(
        "tag",
        ["Loan", "loan", " LOAN ", "Loan  "],
        ids=["capitalized", "lowercase", "padded-upper", "trailing-space"],
    )
    def test_borrow_only_asset_stays_in_loan_affected(
        self, tmp_path: Path, tag: str
    ) -> None:
        """Borrow-only asset (Tag=Loan, no Loan Repayment row) stays in scope.

        Invariant 11 (r7 Medium #1): the path is NOT pure
        resolver-delegation. The borrowing-side ``Tag="Loan"`` row resolves
        to ``Treatment.OTHER`` (Phase B Invariant 9), so a pure
        LOAN_REPAYMENT filter would drop WBTC. The Invariant 11 clause
        (``OTHER`` AND ``_normalize_tag(tag) == "loan"``) is what keeps
        borrow-only assets in the FIFO rebuild scope (user decision
        2026-07-08: preserve legacy asset set).

        Parametrized over casing/whitespace variants to pin the r7 Medium
        #1 tag-normalization contract: comparing the raw ``"Loan"`` literal
        to ``"loan"`` is False; the resolver's ``_normalize_tag``
        (``.strip().lower()``) is the SOLE normalization point.
        """
        th_path = _write_borrow_only_scenario(tmp_path, tag)
        transactions = build_transactions_from_th(th_path)
        config = _treatment_config_for_year(2025)
        result = discover_loan_affected_assets(
            _fiat_codes(),
            transactions=transactions,
            config=config,
        )
        assert "WBTC" in result, (
            f"(tag={tag!r}): borrow-only WBTC dropped out of scope; "
            f"Invariant 11 OTHER+normalized-tag=loan clause not wired, or raw tag "
            f"compared without normalization (r7 Medium #1). Got {sorted(result)}"
        )

    def test_non_loan_other_tag_does_not_enter_scope(
        self, tmp_path: Path
    ) -> None:
        """Discriminating guard: OTHER-tagged rows whose tag is NOT ``"loan"`` stay out.

        Documents the negative space (no OTHER-tagged row whose normalized
        tag is NOT ``"loan"`` is pulled in by the Invariant 11 clause).
        """
        # TH row with Tag="Internal Move" (not in any configured tag set, so
        # resolves to OTHER, not REWARD_AIRDROP_LP / PAYMENT / etc.) receiving
        # USDC. The Invariant 11 clause (`OTHER AND normalized_tag == "loan"`)
        # must NOT pull USDC into scope. A bug that loosened the clause to
        # `OTHER AND "loan" in normalized_tag` would still not fire here, but a
        # bug that dropped the tag-equality check (`OTHER` alone) would.
        th_path = tmp_path / "th_other.csv"
        row = ",".join(
            [
                "2025-04-10 10:00:00 UTC",
                "crypto_deposit",
                "Internal Move",
                "",
                "",
                "",
                "",
                "Kraken",
                '"5,00000000"',
                "USDC",
                '"5,00"',
                "",
                "",
                '"0,00"',
                '"5,00"',
                '"0,00"',
                "",
                "",
                "",
                "Internal transfer",
            ]
        )
        content = "\n".join(["Transaction report 2025", "", _TH_HEADER, row])
        th_path.write_text(content, encoding="utf-8")

        transactions = build_transactions_from_th(th_path)
        config = _treatment_config_for_year(2025)
        result = discover_loan_affected_assets(
            _fiat_codes(),
            transactions=transactions,
            config=config,
        )
        assert "USDC" not in result, (
            f"resolver path: REWARD_AIRDROP_LP row leaked into loan-affected scope "
            f"(Invariant 11 clause over-collects); got {sorted(result)}"
        )

    def test_loan_fee_tag_does_not_pull_fee_asset_into_scope(
        self, tmp_path: Path
    ) -> None:
        """Characterization (M2 / r3 High): ``Tag="Loan Fee"`` rows must NOT
        pull the fee asset into loan-affected scope, EVEN when the row resolves
        to ``Treatment.OTHER``.

        The row below is a ``crypto_deposit`` with no sending side (a fee
        reimbursement modeled as an inbound deposit). With no
        ``sending_currency``, the resolver's default branch does NOT fire; the
        row resolves to ``Treatment.OTHER``. The Invariant 11 clause
        ``treatment is Treatment.OTHER and _normalize_tag(tag) == "loan"`` is
        then the SOLE gate. ``_normalize_tag("Loan Fee")`` returns
        ``"loan fee"``, which must NOT match the exact literal ``"loan"``. A
        regression that loosened the check to ``"loan" in normalized_tag``
        (prefix/substring match) would pull ETH into scope and fail this test.

        The Round 2 version of this test used a ``crypto_withdrawal`` fixture
        with a populated sending side, which resolves to SPOT_DISPOSAL, not
        OTHER - the Invariant 11 clause was structurally False and the test
        passed for any tag-check implementation. Reshaping to a no-sending-side
        deposit makes the test actually discriminating (lesson #46).
        """
        th_path = tmp_path / "th_loan_fee.csv"
        # crypto_deposit, no sending side, Tag="Loan Fee" -> resolves to OTHER.
        # The tag-equality check is the sole gate.
        row = ",".join(
            [
                "2025-04-10 10:00:00 UTC",
                "crypto_deposit",
                "Loan Fee",
                "",
                "",
                "",
                "",
                "ByBit",
                '"0,05000000"',
                "ETH",
                '"10,00"',
                "",
                "",
                '"0,00"',
                '"10,00"',
                '"0,00"',
                "",
                "",
                "",
                "ETH fee reimbursement",
            ]
        )
        content = "\n".join(["Transaction report 2025", "", _TH_HEADER, row])
        th_path.write_text(content, encoding="utf-8")

        transactions = build_transactions_from_th(th_path)
        config = _treatment_config_for_year(2025)
        # First verify the row actually resolves to OTHER so the test exercises
        # the intended branch (regression-catch for the r3 High fake-test fix).
        assert resolve_treatment(transactions[0], config) is Treatment.OTHER, (
            "Loan Fee deposit row must resolve to OTHER for this test to "
            "exercise the Invariant 11 clause; otherwise it is non-discriminating"
        )
        result = discover_loan_affected_assets(
            _fiat_codes(),
            transactions=transactions,
            config=config,
        )
        assert "ETH" not in result, (
            f"resolver path: Loan Fee row pulled ETH (fee asset) into scope; "
            f"_normalize_tag('Loan Fee') == 'loan fee', which must NOT match the "
            f"Invariant 11 'loan' literal. Got {sorted(result)}"
        )

    def test_fiat_currency_in_loan_row_excluded_from_scope(
        self, tmp_path: Path
    ) -> None:
        """Characterization (M2): fiat currencies in LOAN_REPAYMENT rows are
        excluded from loan-affected scope.

        A loan repayment modelled as an exchange (e.g. EUR->WBTC tagged "loan
        repayment") would otherwise pull EUR into scope, treating every
        EUR-involving TH row as a loan-affected acquisition or consumption.
        The ``fiat_currency_codes`` argument is the caller-supplied exclusion
        set; this test pins that it filters BOTH Sent and Received currencies
        on a LOAN_REPAYMENT row, not just the principal side.
        """
        th_path = tmp_path / "th_fiat_loan.csv"
        # crypto_exchange EUR -> WBTC tagged "Loan Repayment" (resolves to
        # LOAN_REPAYMENT). Without the fiat filter, EUR would enter scope.
        row = ",".join(
            [
                "2025-04-10 10:00:00 UTC",
                "crypto_exchange",
                "Loan Repayment",
                "ByBit",
                '"4000,00"',
                "EUR",
                '"4000,00"',
                "ByBit",
                '"0,10000000"',
                "WBTC",
                '"4000,00"',
                "",
                "",
                '"0,00"',
                '"4000,00"',
                '"0,00"',
                "",
                "",
                "",
                "Repay WBTC loan with EUR",
            ]
        )
        content = "\n".join(["Transaction report 2025", "", _TH_HEADER, row])
        th_path.write_text(content, encoding="utf-8")

        transactions = build_transactions_from_th(th_path)
        config = _treatment_config_for_year(2025)
        result = discover_loan_affected_assets(
            _fiat_codes(),  # frozenset({"EUR", "USD"})
            transactions=transactions,
            config=config,
        )
        assert "EUR" not in result, (
            f"resolver path: EUR (fiat) leaked into loan-affected scope from a "
            f"LOAN_REPAYMENT exchange row; fiat_currency_codes filter not applied "
            f"to the sent side. Got {sorted(result)}"
        )
        # Non-fiat asset on the same row is still captured.
        assert "WBTC" in result, (
            f"resolver path: WBTC (non-fiat loan asset) should be in scope. "
            f"Got {sorted(result)}"
        )
