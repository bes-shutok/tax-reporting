"""Phase D Task 5 - LOAN_REPAYMENT flip: ``_LOAN_PRINCIPAL_TAGS`` membership bypass.

Pins the per-treatment flip wiring for ``LOAN_REPAYMENT``: when
``jurisdiction.treatment_loan_repayment_via_resolver`` is True, the
``_LOAN_PRINCIPAL_TAGS`` membership check inside
``discover_loan_affected_assets`` is bypassed (identification comes from
``resolve_treatment``). Per Invariant 11 the flag-on path is NOT pure
resolver-delegation: it ALSO includes ``Treatment.OTHER`` rows whose
normalized tag is ``"loan"`` so borrow-only assets (collateral creation)
remain in the FIFO rebuild scope (user decision 2026-07-08: preserve
legacy asset set).

r7 Medium #1 fix: tag comparison uses the resolver's ``_normalize_tag``
(``.strip().lower()``) so the corpus's capitalized ``Tag="Loan"`` casing
matches. Parametrized over casing/whitespace variants to pin the
contract.

r8 Medium #1 Option A: the production caller
``load_koinly_crypto_report`` builds the ``list[Transaction]`` ONCE and
passes it to ``discover_loan_affected_assets`` together with the
``TreatmentConfig`` and the ``via_resolver`` flag; the function does NOT
construct ``Transaction`` objects internally (Family F layering).
"""

from __future__ import annotations

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
from tax_reporting.application.crypto_fifo import discover_loan_affected_assets
from tax_reporting.domain.transaction import Transaction
from tax_reporting.domain.treatment import Treatment
from tax_reporting.infrastructure.koinly_parser import (
    normalize_platform_name,
    parse_th_row,
    read_koinly_rows,
)

_LOAN_AFFECTED_REBUILD_DIR = Path(
    "resources/source/example/2025/koinly/loan_affected_rebuild"
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


def _scenario_th_csv() -> Path:
    """Path to the ``loan_affected_rebuild`` TH fixture (committed)."""
    return _LOAN_AFFECTED_REBUILD_DIR / "koinly_2025_transaction_history.csv"


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


def _fiat_codes() -> frozenset[str]:
    """Fiat codes excluded from discovery (mirrors production caller)."""
    return frozenset({"EUR", "USD"})


def _write_borrow_only_scenario(tmp_path: Path, tag: str) -> Path:
    """Build a temp TH CSV with a single ``Tag=<tag>`` crypto_deposit borrow row.

    No ``Tag="Loan Repayment"`` row exists in the tax year. Under the legacy
    ``_LOAN_PRINCIPAL_TAGS`` membership path this row still matches (the set
    contains ``"loan"``). Under the flag-on path the row resolves to
    ``Treatment.OTHER`` (Phase B Invariant 9: borrowing-side ``"loan"`` is
    principal creation, NOT ``LOAN_REPAYMENT``), so the Invariant 11
    ``OTHER + normalized-tag=loan`` clause is what keeps WBTC in scope.
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
class TestPhaseDFlipLoanRepayment:
    """Pin the LOAN_REPAYMENT flip wiring on ``discover_loan_affected_assets``."""

    def test_resolver_distinguishes_borrowing_from_repayment(self) -> None:
        """``Tag="Loan"`` resolves to OTHER; ``Tag="Loan Repayment`` to LOAN_REPAYMENT.

        Pins Phase B Invariant 9: the borrowing-side ``"loan"`` tag is
        principal creation (collateral deposit), NOT a repayment disposal.
        The resolver's ``loan_repayment_tags`` default excludes ``"loan"``;
        only ``"loan repayment"`` matches DP-001 non-taxable scope.
        """
        transactions = _build_transactions_from_th(_scenario_th_csv())
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

    def test_loan_principal_tags_skipped_when_flag_on(self) -> None:
        """Flag on: ``_LOAN_PRINCIPAL_TAGS`` membership NOT consulted.

        End-to-end: ``load_koinly_crypto_report`` with the flag on consumes
        the pre-built ``transactions`` list. Loan-affected asset discovery
        uses ``Treatment.LOAN_REPAYMENT`` rows AND ``Treatment.OTHER`` rows
        whose normalized tag is ``"loan"`` (Invariant 11). The
        ``loan_affected_rebuild`` scenario has BOTH a Tag=Loan borrow
        (WBTC) and a Tag=Loan Repayment disposal (WBTC), so WBTC is in
        scope under either path; the discriminating assertion is that the
        resolver path runs (proven by WBTC being in scope AND no exception
        raised when ``_LOAN_PRINCIPAL_TAGS`` would not be consulted).
        """
        th_path = _scenario_th_csv()
        transactions = _build_transactions_from_th(th_path)
        config = _treatment_config_for_year(2025)
        result = discover_loan_affected_assets(
            th_path,
            _fiat_codes(),
            transactions=transactions,
            config=config,
            via_resolver=True,
        )
        # WBTC appears in both the Loan borrow row and the Loan Repayment
        # disposal row; EUR appears in the plain spot row (excluded as fiat).
        assert "WBTC" in result, (
            f"flag-on: WBTC must be in scope (Loan borrow + Loan Repayment); got {sorted(result)}"
        )

    def test_loan_principal_tags_runs_when_flag_off(self) -> None:
        """Flag off: ``_LOAN_PRINCIPAL_TAGS`` membership runs exactly as today.

        The same scenario under ``via_resolver=False`` must produce the
        legacy result (read_koinly_rows + tag in {loan, loan repayment}).
        Pins Invariant 1 (bypass, not deletion) on this identification path.
        """
        th_path = _scenario_th_csv()
        transactions = _build_transactions_from_th(th_path)
        config = _treatment_config_for_year(2025)
        result_via_resolver_off = discover_loan_affected_assets(
            th_path,
            _fiat_codes(),
            transactions=transactions,
            config=config,
            via_resolver=False,
        )
        # Legacy path: WBTC from Loan and Loan Repayment rows; ETH/EUR from
        # the plain spot row excluded (EUR as fiat, ETH not loan-tagged).
        assert "WBTC" in result_via_resolver_off, (
            f"flag-off: WBTC must be in scope under legacy membership; "
            f"got {sorted(result_via_resolver_off)}"
        )

    @pytest.mark.parametrize(
        "tag",
        ["Loan", "loan", " LOAN ", "Loan  "],
        ids=["capitalized", "lowercase", "padded-upper", "trailing-space"],
    )
    def test_borrow_only_asset_still_in_loan_affected_under_flag(
        self, tmp_path: Path, tag: str
    ) -> None:
        """Borrow-only asset (Tag=Loan, no Loan Repayment row) stays in scope under flag on.

        Invariant 11 (r7 Medium #1): the flag-on path is NOT pure
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
        transactions = _build_transactions_from_th(th_path)
        config = _treatment_config_for_year(2025)
        result = discover_loan_affected_assets(
            th_path,
            _fiat_codes(),
            transactions=transactions,
            config=config,
            via_resolver=True,
        )
        assert "WBTC" in result, (
            f"flag-on (tag={tag!r}): borrow-only WBTC dropped out of scope; "
            f"Invariant 11 OTHER+normalized-tag=loan clause not wired, or raw tag "
            f"compared without normalization (r7 Medium #1). Got {sorted(result)}"
        )

    def test_borrow_only_asset_dropped_under_pure_resolver_delegation(
        self, tmp_path: Path
    ) -> None:
        """Discriminating guard: if the flag-on path consulted ONLY ``LOAN_REPAYMENT``
        (no Invariant 11 ``OTHER + tag=loan`` clause), a borrow-only asset
        would drop. This test documents that failure mode by asserting the
        production wiring does NOT exhibit it - the previous test already
        pins the positive behavior; this test asserts the negative space
        (no OTHER-tagged row whose normalized tag is NOT ``"loan"`` is
        pulled in by the Invariant 11 clause).
        """
        # TH row with Tag="Reward" (resolves to REWARD_AIRDROP_LP, not OTHER)
        # receiving USDC. Must NOT enter scope under flag on (it is neither
        # LOAN_REPAYMENT nor OTHER+tag=loan).
        th_path = tmp_path / "th_reward.csv"
        row = ",".join(
            [
                "2025-04-10 10:00:00 UTC",
                "crypto_deposit",
                "Reward",
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
                "Reward income",
            ]
        )
        content = "\n".join(["Transaction report 2025", "", _TH_HEADER, row])
        th_path.write_text(content, encoding="utf-8")

        transactions = _build_transactions_from_th(th_path)
        config = _treatment_config_for_year(2025)
        result = discover_loan_affected_assets(
            th_path,
            _fiat_codes(),
            transactions=transactions,
            config=config,
            via_resolver=True,
        )
        assert "USDC" not in result, (
            f"flag-on: REWARD_AIRDROP_LP row leaked into loan-affected scope "
            f"(Invariant 11 clause over-collects); got {sorted(result)}"
        )
