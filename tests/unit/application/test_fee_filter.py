"""Unit tests for the standalone transaction/network fee filter (DP-015).

Exercises every identification path (tagged-fee, untagged-whitelist-pass,
untagged-whitelist-fail, untagged-co-occurrence-fail, unlisted-suspect,
unlisted-suspect-boundary, empty-dict-no-op), the ETH override band, both
matching phases (exact, contiguous range), suspect CG-flag propagation, and
suspect CryptoReviewEntry creation, plus disabled-state no-ops.

Tests follow the TDD RED -> GREEN cycle. TH CSVs are written inline with the
Koinly Transaction History column layout (preamble line + header row + data
rows) so ``read_koinly_rows`` detects the header.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from pathlib import Path

import pytest

from tax_reporting.application.crypto.entities import (
    CryptoCapitalGainEntry,
    CryptoReviewEntry,
)
from tax_reporting.application.crypto.fee_filter import (
    FeeThEvent,
    SuspectThEvent,
    flag_fee_suspects,
    remove_transaction_fees,
)
from tax_reporting.application.crypto.operator_origin import OperatorOrigin
from tax_reporting.domain.jurisdiction import TaxJurisdictionConfig

# Default per-token ceiling map (the user-confirmed values for FY2025 PT).
_PT_PER_ASSET: dict[str, Decimal] = {
    "ETH": Decimal("1.0"),
    "BERA": Decimal("0.1"),
}

_TEST_OPERATOR_ORIGIN = OperatorOrigin(
    platform="MetaMask",
    service_scope="crypto",
    operator_entity="MetaMask",
    operator_country="Unknown",
    source_url="",
    source_checked_on="2026-01-01",
    confidence="low",
    review_required=False,
    valid_from="2026-01-01",
)

# Full Koinly Transaction History header (column order matters for DictWriter).
_TH_HEADER = [
    "Date",
    "Type",
    "Tag",
    "Sending Wallet",
    "Sent Amount",
    "Sent Currency",
    "Sent Cost Basis",
    "Receiving Wallet",
    "Received Amount",
    "Received Currency",
    "Received Cost Basis",
    "Fee Amount",
    "Fee Currency",
    "Gain (EUR)",
    "Net Value (EUR)",
    "Fee Value (EUR)",
    "TxSrc",
    "TxDest",
    "TxHash",
    "Description",
]


def _write_th_csv(path: Path, rows: list[dict[str, str]]) -> None:
    """Write a Koinly Transaction History CSV with the standard preamble."""
    import csv

    with path.open("w", newline="", encoding="utf-8") as fh:
        fh.write("Transaction report 2025\n\n")
        writer = csv.DictWriter(fh, fieldnames=_TH_HEADER)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in _TH_HEADER})


def _make_cg_lot(  # noqa: PLR0913
    *,
    disposal_timestamp: str,
    asset: str = "ETH",
    wallet: str = "MetaMask",
    amount: Decimal,
    acquisition_date: str = "2025-01-10",
    proceeds_eur: Decimal = Decimal("1.50"),
    gain_loss_eur: Decimal = Decimal("1.00"),
    cost_eur: Decimal = Decimal("0.50"),
    review_required: bool = False,
    review_reason: str | None = None,
) -> CryptoCapitalGainEntry:
    """Build a CryptoCapitalGainEntry fixture for fee-filter tests."""
    return CryptoCapitalGainEntry(
        disposal_date=disposal_timestamp.split(" ")[0],
        acquisition_date=acquisition_date,
        asset=asset,
        amount=amount,
        cost_eur=cost_eur,
        proceeds_eur=proceeds_eur,
        gain_loss_eur=gain_loss_eur,
        holding_period="Short term",
        wallet=wallet,
        platform=wallet,
        chain="Unknown",
        operator_origin=_TEST_OPERATOR_ORIGIN,
        annex_hint="J",
        review_required=review_required,
        notes="",
        review_reason=review_reason,
        disposal_timestamp=disposal_timestamp,
    )


def _make_jurisdiction(
    *,
    flag: bool = True,
    per_asset: dict[str, Decimal] | None = None,
) -> TaxJurisdictionConfig:
    """Build a PT jurisdiction config fixture."""
    return TaxJurisdictionConfig(
        country="PT",
        fiscal_year=2025,
        exclude_loan_repayment_gains=True,
        zero_basis_review_threshold=Decimal("50"),
        exclude_transaction_fees=flag,
        exclude_transaction_fee_max_eur_per_asset=(
            dict(_PT_PER_ASSET) if per_asset is None else dict(per_asset)
        ),
    )


def _withdrawal_row(  # noqa: PLR0913
    *,
    date: str = "2025-03-30 12:00:00 UTC",
    tag: str = "",
    sending_wallet: str = "MetaMask",
    sent_amount: str,
    sent_currency: str,
    net_value_eur: str,
    tx_hash: str,
) -> dict[str, str]:
    """Build a ``crypto_withdrawal`` TH row."""
    return {
        "Date": date,
        "Type": "crypto_withdrawal",
        "Tag": tag,
        "Sending Wallet": sending_wallet,
        "Sent Amount": sent_amount,
        "Sent Currency": sent_currency,
        "Net Value (EUR)": net_value_eur,
        "TxHash": tx_hash,
    }


def _transfer_row(*, tx_hash: str, date: str = "2025-03-30 12:00:00 UTC") -> dict[str, str]:
    """Build a ``transfer`` TH row sharing a TxHash (for co-occurrence)."""
    return {
        "Date": date,
        "Type": "transfer",
        "Sending Wallet": "MetaMask",
        "Sent Amount": "1.00000000",
        "Sent Currency": "ETH",
        "Receiving Wallet": "Binance",
        "Received Amount": "1.00000000",
        "Received Currency": "ETH",
        "Net Value (EUR)": "3000.00",
        "TxHash": tx_hash,
    }


_FEE_LOGGER = "tax_reporting.application.crypto.fee_filter"


def _render_source_label(entry: CryptoReviewEntry) -> str:
    """Mirror the ``crypto_supplementary_sheet._write_review_rows`` source_label lookup.

    Asserting against this helper (rather than just ``entry.source_section``)
    binds the test to the rendered label so a forgotten extension that falls
    back to ``"Income"`` fails (r7 L5).
    """
    return {
        "capital_gains": "Capital Gains",
        "transaction_history": "Transaction History",
    }.get(entry.source_section, "Income")


class TestRemoveExactAndRangeMatches:
    """Phase 1 exact and phase 2 contiguous-range fee removal."""

    def test_removes_exact_matches(self, tmp_path: Path) -> None:
        """A CG lot of 0.001 ETH and a TH fee withdrawal of 0.001 ETH -> lot removed."""
        th = tmp_path / "th.csv"
        _write_th_csv(
            th,
            [
                _transfer_row(tx_hash="0xAAA"),
                _withdrawal_row(
                    tag="Cost",
                    sent_amount="0.00100000",
                    sent_currency="ETH",
                    net_value_eur="3.00",
                    tx_hash="0xAAA",
                ),
            ],
        )
        lots = [
            _make_cg_lot(
                disposal_timestamp="2025-03-30 12:00",
                asset="ETH",
                amount=Decimal("0.00100000"),
            )
        ]

        remaining, suspects = remove_transaction_fees(
            capital_entries=lots,
            transaction_history_file=th,
            jurisdiction=_make_jurisdiction(),
        )

        assert remaining == []
        assert suspects == []

    def test_removes_contiguous_range_matches(self, tmp_path: Path) -> None:
        """CG lots of 0.002 ETH + 0.00067371 ETH and a 0.00267371 ETH fee -> both removed."""
        th = tmp_path / "th.csv"
        _write_th_csv(
            th,
            [
                _transfer_row(tx_hash="0xAAA"),
                _withdrawal_row(
                    tag="Cost",
                    sent_amount="0.00267371",
                    sent_currency="ETH",
                    net_value_eur="3.00",
                    tx_hash="0xAAA",
                ),
            ],
        )
        lots = [
            _make_cg_lot(
                disposal_timestamp="2025-03-30 12:00",
                asset="ETH",
                amount=Decimal("0.00200000"),
            ),
            _make_cg_lot(
                disposal_timestamp="2025-03-30 12:00",
                asset="ETH",
                amount=Decimal("0.00067371"),
            ),
        ]

        remaining, _suspects = remove_transaction_fees(
            capital_entries=lots,
            transaction_history_file=th,
            jurisdiction=_make_jurisdiction(),
        )

        assert remaining == []


class TestPerLotLogIdentity:
    """r7 M4 / r8 M3: per-lot log records the removed lot identity + tx_hash."""

    def test_per_lot_log_records_removed_lot_identity_for_cross_tx_spot_check(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Per-lot INFO records the removed lot's identity tuple AND event.tx_hash/tagged.

        The cross-tx hazard (a tagged fee sharing a TxHash with a transfer while an
        UNRELATED same-minute/wallet/amount disposal exists) cannot be made to fail
        under the current matcher (it keys by minute/asset/wallet/amount only). This
        test asserts the MITIGATION log that makes such a match visible during the
        release-gate spot-check, NOT an unenforceable "unrelated lot survives"
        guarantee.
        """
        th = tmp_path / "th.csv"
        _write_th_csv(
            th,
            [
                _transfer_row(tx_hash="0xAAA"),
                _withdrawal_row(
                    tag="Cost",
                    sent_amount="0.00100000",
                    sent_currency="ETH",
                    net_value_eur="3.00",
                    tx_hash="0xAAA",
                ),
            ],
        )
        lots = [
            _make_cg_lot(
                disposal_timestamp="2025-03-30 12:00",
                asset="ETH",
                amount=Decimal("0.00100000"),
            )
        ]

        with caplog.at_level(logging.INFO, logger=_FEE_LOGGER):
            remove_transaction_fees(
                capital_entries=lots,
                transaction_history_file=th,
                jurisdiction=_make_jurisdiction(),
            )

        info_records = [
            r
            for r in caplog.records
            if r.levelno == logging.INFO and "Removed fee-matched CG lot" in r.getMessage()
        ]
        assert info_records, "expected a per-lot INFO record for the removed fee lot"
        msg = info_records[0].getMessage()
        assert "timestamp=2025-03-30 12:00" in msg
        assert "asset=ETH" in msg
        assert "wallet=MetaMask" in msg
        assert "amount=0.00100000" in msg
        assert "tx_hash=0xAAA" in msg
        assert "tagged=True" in msg


class TestTaggedRetains:
    """Standalone / empty-txhash tagged withdrawals are retained."""

    @pytest.mark.parametrize("tag", ["Cost", "Loan fee"])
    def test_filters_standalone_tagged_withdrawals_without_co_occurrence(
        self, tmp_path: Path, tag: str
    ) -> None:
        """A Cost/Loan fee withdrawal with a unique TxHash -> CG lot filtered."""
        th = tmp_path / "th.csv"
        _write_th_csv(
            th,
            [
                _withdrawal_row(
                    tag=tag,
                    sent_amount="0.00100000",
                    sent_currency="ETH",
                    net_value_eur="3.00",
                    tx_hash="0xUNIQUE",  # occurs once
                ),
            ],
        )
        lot = _make_cg_lot(
            disposal_timestamp="2025-03-30 12:00",
            asset="ETH",
            amount=Decimal("0.00100000"),
        )

        remaining, _suspects = remove_transaction_fees(
            capital_entries=[lot],
            transaction_history_file=th,
            jurisdiction=_make_jurisdiction(),
        )

        assert remaining == []

    @pytest.mark.parametrize("tag", ["Cost", "Loan fee"])
    def test_filters_tagged_withdrawals_with_empty_txhash(
        self, tmp_path: Path, tag: str
    ) -> None:
        """A Cost/Loan fee withdrawal with an empty TxHash -> CG lot filtered."""
        th = tmp_path / "th.csv"
        _write_th_csv(
            th,
            [
                _withdrawal_row(
                    tag=tag,
                    sent_amount="0.00100000",
                    sent_currency="ETH",
                    net_value_eur="3.00",
                    tx_hash="",
                ),
            ],
        )
        lot = _make_cg_lot(
            disposal_timestamp="2025-03-30 12:00",
            asset="ETH",
            amount=Decimal("0.00100000"),
        )

        remaining, _suspects = remove_transaction_fees(
            capital_entries=[lot],
            transaction_history_file=th,
            jurisdiction=_make_jurisdiction(),
        )

        assert remaining == []


class TestUntaggedWhitelist:
    """Untagged whitelisted-asset withdrawals filtered by per-token ceiling."""

    def test_removes_untagged_gas_fees_matching_whitelist(self, tmp_path: Path) -> None:
        """Untagged 0.00010301 ETH with Net Value 0.28 (<= 1.0) -> lot removed."""
        th = tmp_path / "th.csv"
        _write_th_csv(
            th,
            [
                _transfer_row(tx_hash="0xAAA"),
                _withdrawal_row(
                    sent_amount="0.00010301",
                    sent_currency="ETH",
                    net_value_eur="0.28",
                    tx_hash="0xAAA",
                ),
            ],
        )
        lot = _make_cg_lot(
            disposal_timestamp="2025-03-30 12:00",
            asset="ETH",
            amount=Decimal("0.00010301"),
        )

        remaining, _suspects = remove_transaction_fees(
            capital_entries=[lot],
            transaction_history_file=th,
            jurisdiction=_make_jurisdiction(),
        )

        assert remaining == []

    def test_removes_eth_untagged_fee_in_override_band(self, tmp_path: Path) -> None:
        """Untagged ETH with Net Value 0.70 (0.5 < 0.70 <= 1.0) -> lot filtered.

        Discriminates the ETH override from the 0.5 default: a mis-resolution to
        the default would retain 0.70.
        """
        th = tmp_path / "th.csv"
        _write_th_csv(
            th,
            [
                _transfer_row(tx_hash="0xAAA"),
                _withdrawal_row(
                    sent_amount="0.00025000",
                    sent_currency="ETH",
                    net_value_eur="0.70",
                    tx_hash="0xAAA",
                ),
            ],
        )
        lot = _make_cg_lot(
            disposal_timestamp="2025-03-30 12:00",
            asset="ETH",
            amount=Decimal("0.00025000"),
        )

        remaining, _suspects = remove_transaction_fees(
            capital_entries=[lot],
            transaction_history_file=th,
            jurisdiction=_make_jurisdiction(),
        )

        assert remaining == []

    def test_filters_eth_untagged_fee_at_exact_ceiling(self, tmp_path: Path) -> None:
        """Untagged ETH at Net Value 1.0 (== override) -> filtered.

        Pins the ``<=`` inclusivity of the ETH ceiling; a ``< 1.0`` impl would
        wrongly retain a genuine ETH gas fee at exactly 1.0.
        """
        th = tmp_path / "th.csv"
        _write_th_csv(
            th,
            [
                _transfer_row(tx_hash="0xAAA"),
                _withdrawal_row(
                    sent_amount="0.00035000",
                    sent_currency="ETH",
                    net_value_eur="1.0",
                    tx_hash="0xAAA",
                ),
            ],
        )
        lot = _make_cg_lot(
            disposal_timestamp="2025-03-30 12:00",
            asset="ETH",
            amount=Decimal("0.00035000"),
        )

        remaining, _suspects = remove_transaction_fees(
            capital_entries=[lot],
            transaction_history_file=th,
            jurisdiction=_make_jurisdiction(),
        )

        assert remaining == []

    def test_retains_eth_untagged_fee_over_ceiling(self, tmp_path: Path) -> None:
        """Untagged ETH at Net Value 1.01 (> 1.0) -> lot retained (and NOT a suspect).

        The 1.01-retain independently pins the NON-SUSPECT guard (an impl that
        wrongly flags an over-ceiling whitelisted withdrawal as a suspect fails
        here). The three clauses (1.0-filtered + 1.01-retained + 0.70-filtered)
        JOINTLY pin both ``<=`` inclusivity AND ceiling == 1.0.
        """
        th = tmp_path / "th.csv"
        _write_th_csv(
            th,
            [
                _transfer_row(tx_hash="0xAAA"),
                _withdrawal_row(
                    sent_amount="0.00036000",
                    sent_currency="ETH",
                    net_value_eur="1.01",
                    tx_hash="0xAAA",
                ),
            ],
        )
        lot = _make_cg_lot(
            disposal_timestamp="2025-03-30 12:00",
            asset="ETH",
            amount=Decimal("0.00036000"),
        )

        remaining, suspects = remove_transaction_fees(
            capital_entries=[lot],
            transaction_history_file=th,
            jurisdiction=_make_jurisdiction(),
        )

        assert remaining == [lot]
        # An over-ceiling whitelisted withdrawal is NOT a suspect either.
        assert suspects == []

    def test_retains_untagged_non_whitelist_withdrawals(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Untagged 10.0 ZK (not a dict key) with Net Value 5.0 (> max 1.0) -> retained.

        Neither filtered nor a suspect; no suspect WARNING, no flag.
        """
        th = tmp_path / "th.csv"
        _write_th_csv(
            th,
            [
                _transfer_row(tx_hash="0xAAA"),
                _withdrawal_row(
                    sent_amount="10.00000000",
                    sent_currency="ZK",
                    net_value_eur="5.0",
                    tx_hash="0xAAA",
                ),
            ],
        )
        lot = _make_cg_lot(
            disposal_timestamp="2025-03-30 12:00",
            asset="ZK",
            amount=Decimal("10.00000000"),
        )

        with caplog.at_level(logging.WARNING, logger=_FEE_LOGGER):
            remaining, suspects = remove_transaction_fees(
                capital_entries=[lot],
                transaction_history_file=th,
                jurisdiction=_make_jurisdiction(),
            )

        assert remaining == [lot]
        assert suspects == []
        assert not any(
            "Possible untagged fee for unlisted asset" in r.getMessage()
            for r in caplog.records
        )

    def test_retains_untagged_whitelist_withdrawals_exceeding_threshold(
        self, tmp_path: Path
    ) -> None:
        """Untagged SOL with Net Value 0.75 (> 0.5) -> lot retained."""
        th = tmp_path / "th.csv"
        _write_th_csv(
            th,
            [
                _transfer_row(tx_hash="0xAAA"),
                _withdrawal_row(
                    sent_amount="0.00500000",
                    sent_currency="SOL",
                    net_value_eur="0.75",
                    tx_hash="0xAAA",
                ),
            ],
        )
        lot = _make_cg_lot(
            disposal_timestamp="2025-03-30 12:00",
            asset="SOL",
            amount=Decimal("0.00500000"),
        )

        remaining, _suspects = remove_transaction_fees(
            capital_entries=[lot],
            transaction_history_file=th,
            jurisdiction=_make_jurisdiction(),
        )

        assert remaining == [lot]

    def test_retains_untagged_whitelist_withdrawal_with_unique_txhash(
        self, tmp_path: Path
    ) -> None:
        """Untagged SOL with Net Value 0.1 (<= ceiling) but TxHash once -> retained."""
        th = tmp_path / "th.csv"
        _write_th_csv(
            th,
            [
                _withdrawal_row(
                    sent_amount="0.00100000",
                    sent_currency="SOL",
                    net_value_eur="0.1",
                    tx_hash="0xUNIQUE",
                ),
            ],
        )
        lot = _make_cg_lot(
            disposal_timestamp="2025-03-30 12:00",
            asset="SOL",
            amount=Decimal("0.00100000"),
        )

        remaining, _suspects = remove_transaction_fees(
            capital_entries=[lot],
            transaction_history_file=th,
            jurisdiction=_make_jurisdiction(),
        )

        assert remaining == [lot]

    def test_filters_untagged_at_exact_threshold(self, tmp_path: Path) -> None:
        """Untagged SOL at Net Value 0.5 (== ceiling) -> filtered (<= inclusive)."""
        th = tmp_path / "th.csv"
        _write_th_csv(
            th,
            [
                _transfer_row(tx_hash="0xAAA"),
                _withdrawal_row(
                    sent_amount="0.00300000",
                    sent_currency="SOL",
                    net_value_eur="0.5",
                    tx_hash="0xAAA",
                ),
            ],
        )
        lot = _make_cg_lot(
            disposal_timestamp="2025-03-30 12:00",
            asset="SOL",
            amount=Decimal("0.00300000"),
        )

        remaining, _suspects = remove_transaction_fees(
            capital_entries=[lot],
            transaction_history_file=th,
            jurisdiction=_make_jurisdiction(),
        )

        assert remaining == []

    def test_filters_untagged_zero_eur_fee(self, tmp_path: Path) -> None:
        """Untagged SOL at Net Value 0.0 -> filtered (genuine zero-priced gas fee)."""
        th = tmp_path / "th.csv"
        _write_th_csv(
            th,
            [
                _transfer_row(tx_hash="0xAAA"),
                _withdrawal_row(
                    sent_amount="0.00100000",
                    sent_currency="SOL",
                    net_value_eur="0.0",
                    tx_hash="0xAAA",
                ),
            ],
        )
        lot = _make_cg_lot(
            disposal_timestamp="2025-03-30 12:00",
            asset="SOL",
            amount=Decimal("0.00100000"),
        )

        remaining, _suspects = remove_transaction_fees(
            capital_entries=[lot],
            transaction_history_file=th,
            jurisdiction=_make_jurisdiction(),
        )

        assert remaining == []

    def test_retains_untagged_fee_with_missing_net_value(self, tmp_path: Path) -> None:
        """Untagged whitelist withdrawal with blank Net Value (EUR) -> retained.

        The explicit "MISSING" string guard prevents it from defaulting to 0.
        """
        th = tmp_path / "th.csv"
        _write_th_csv(
            th,
            [
                _transfer_row(tx_hash="0xAAA"),
                _withdrawal_row(
                    sent_amount="0.00100000",
                    sent_currency="SOL",
                    net_value_eur="",
                    tx_hash="0xAAA",
                ),
            ],
        )
        lot = _make_cg_lot(
            disposal_timestamp="2025-03-30 12:00",
            asset="SOL",
            amount=Decimal("0.00100000"),
        )

        remaining, _suspects = remove_transaction_fees(
            capital_entries=[lot],
            transaction_history_file=th,
            jurisdiction=_make_jurisdiction(),
        )

        assert remaining == [lot]


class TestTaggedNoThreshold:
    """Tagged fees are filtered regardless of EUR value."""

    @pytest.mark.parametrize("tag", ["Cost", "Loan fee"])
    def test_tagged_fee_not_subject_to_eur_threshold(
        self, tmp_path: Path, tag: str
    ) -> None:
        """A Cost/Loan fee with Net Value 5.0 (above override) -> filtered regardless."""
        th = tmp_path / "th.csv"
        _write_th_csv(
            th,
            [
                _transfer_row(tx_hash="0xAAA"),
                _withdrawal_row(
                    tag=tag,
                    sent_amount="0.00100000",
                    sent_currency="ETH",
                    net_value_eur="5.0",
                    tx_hash="0xAAA",
                ),
            ],
        )
        lot = _make_cg_lot(
            disposal_timestamp="2025-03-30 12:00",
            asset="ETH",
            amount=Decimal("0.00100000"),
        )

        remaining, _suspects = remove_transaction_fees(
            capital_entries=[lot],
            transaction_history_file=th,
            jurisdiction=_make_jurisdiction(),
        )

        assert remaining == []

    def test_tagged_fee_with_missing_net_value_still_removed(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A Cost-tagged withdrawal with a BLANK Net Value (EUR) cell -> CG lot removed.

        The tag is the authority; the defensive parse sentinels
        ``net_value_eur = Decimal("0")``; the scanner does NOT raise; the per-lot
        log interpolates 0 EUR.
        """
        th = tmp_path / "th.csv"
        _write_th_csv(
            th,
            [
                _transfer_row(tx_hash="0xAAA"),
                _withdrawal_row(
                    tag="Cost",
                    sent_amount="0.00100000",
                    sent_currency="ETH",
                    net_value_eur="",
                    tx_hash="0xAAA",
                ),
            ],
        )
        lot = _make_cg_lot(
            disposal_timestamp="2025-03-30 12:00",
            asset="ETH",
            amount=Decimal("0.00100000"),
        )

        with caplog.at_level(logging.INFO, logger=_FEE_LOGGER):
            remaining, _suspects = remove_transaction_fees(
                capital_entries=[lot],
                transaction_history_file=th,
                jurisdiction=_make_jurisdiction(),
            )

        assert remaining == []
        # No exception was raised (test reaching assertions proves that). The
        # per-lot INFO record was emitted for the trusted tagged removal.
        assert any(
            "Removed fee-matched CG lot" in r.getMessage() and "tagged=True" in r.getMessage()
            for r in caplog.records
        )


class TestMalformedRows:
    """Malformed TH rows are skipped without aborting the scan."""

    def test_malformed_th_row_is_skipped_and_good_rows_processed(
        self, tmp_path: Path
    ) -> None:
        """A mix of valid fee rows and an invalid row -> invalid skipped, valid extracted."""
        th = tmp_path / "th.csv"
        _write_th_csv(
            th,
            [
                _transfer_row(tx_hash="0xAAA"),
                _withdrawal_row(
                    tag="Cost",
                    sent_amount="0.00100000",
                    sent_currency="ETH",
                    net_value_eur="3.00",
                    tx_hash="0xAAA",
                ),
                # Malformed: unparseable Sent Amount throws ValueError.
                _withdrawal_row(
                    tag="Cost",
                    sent_amount="not-a-number",
                    sent_currency="ETH",
                    net_value_eur="3.00",
                    tx_hash="0xBBB",
                ),
                _transfer_row(tx_hash="0xBBB"),
            ],
        )
        # The valid 0xAAA fee removal still fires; the malformed 0xBBB row is
        # skipped and does NOT abort.
        lot = _make_cg_lot(
            disposal_timestamp="2025-03-30 12:00",
            asset="ETH",
            amount=Decimal("0.00100000"),
        )

        remaining, _suspects = remove_transaction_fees(
            capital_entries=[lot],
            transaction_history_file=th,
            jurisdiction=_make_jurisdiction(),
        )

        assert remaining == []


class TestUntaggedWhitelistedWarning:
    """Pattern I: untagged-whitelisted removals group-collapse to ONE aggregate WARNING.

    The per-tx_hash detail moves to DEBUG (audit trail preserved at DEBUG in the
    file handler); exactly ONE aggregate WARNING carries the count + per-asset
    breakdown. Stays WARNING because there is no Excel review surface for these
    removals - the WARNING is the audit trail (distinct from J/K/L downgrades).
    """

    def test_untagged_whitelisted_per_row_at_debug_and_one_aggregate_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Untagged-whitelisted SOL removal -> per-tx_hash detail at DEBUG + ONE aggregate WARNING.

        Pattern I (group-collapse, NOT downgrade): the per-tx_hash detail
        (asset=SOL, Net Value=0.3, tx_hash=0xAAA) is captured at DEBUG, and
        exactly ONE WARNING-level record carries the new aggregate leading-phrase
        (a count followed by the pluralizable ``"disposal(s)"`` tail that
        distinguishes it from the per-row singular ``"disposal for"``). The
        aggregate carries the count and a per-asset breakdown.
        """
        th = tmp_path / "th.csv"
        _write_th_csv(
            th,
            [
                _transfer_row(tx_hash="0xAAA"),
                _withdrawal_row(
                    sent_amount="0.00100000",
                    sent_currency="SOL",
                    net_value_eur="0.3",
                    tx_hash="0xAAA",
                ),
            ],
        )
        lot = _make_cg_lot(
            disposal_timestamp="2025-03-30 12:00",
            asset="SOL",
            amount=Decimal("0.00100000"),
        )

        # caplog at DEBUG so the downgraded per-row detail is captured.
        with caplog.at_level(logging.DEBUG, logger=_FEE_LOGGER):
            remaining, _suspects = remove_transaction_fees(
                capital_entries=[lot],
                transaction_history_file=th,
                jurisdiction=_make_jurisdiction(),
            )

        assert remaining == []

        # Per-tx_hash detail captured at DEBUG (not WARNING): the aggregate
        # leading-phrase must NOT match a per-row record.
        per_row_debug = [
            r
            for r in caplog.records
            if r.levelno == logging.DEBUG
            and "Removed untagged-whitelisted fee disposal for" in r.getMessage()
        ]
        assert per_row_debug, (
            "expected the per-tx_hash detail at DEBUG for the untagged-whitelisted removal"
        )
        per_row_msg = per_row_debug[0].getMessage()
        assert "SOL" in per_row_msg
        assert "0.3" in per_row_msg
        assert "0xAAA" in per_row_msg

        # Exactly ONE WARNING-level aggregate record matching the new aggregate
        # leading-phrase; it carries the count and per-asset breakdown. The
        # aggregate wording uses the pluralizable "disposal(s)" tail.
        aggregate_warnings = [
            r
            for r in caplog.records
            if r.levelno == logging.WARNING
            and "untagged-whitelisted fee disposal(s) (" in r.getMessage()
        ]
        assert len(aggregate_warnings) == 1, (
            "expected exactly ONE aggregate WARNING for the untagged-whitelisted removals, "
            f"got {len(aggregate_warnings)}"
        )
        aggregate_msg = aggregate_warnings[0].getMessage()
        assert aggregate_msg.startswith("Removed 1 untagged-whitelisted fee disposal"), (
            f"aggregate must start with count + leading-phrase; got {aggregate_msg!r}"
        )
        # Per-asset breakdown names SOL with count 1.
        assert "SOL: 1" in aggregate_msg, (
            f"aggregate per-asset breakdown must name 'SOL: 1'; got {aggregate_msg!r}"
        )
        # The aggregate tail reminds the reviewer to verify each is a network fee.
        assert "verify each is a network fee" in aggregate_msg, (
            f"aggregate must carry the 'verify each is a network fee' reminder; got {aggregate_msg!r}"
        )

    def test_tagged_removal_does_not_emit_untagged_aggregate(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A tagged Cost removal logs at INFO and emits NO untagged-whitelisted aggregate.

        Verifies the aggregate wording does not collide with the tagged path:
        no WARNING matching the untagged-whitelisted aggregate leading-phrase
        AND no DEBUG record containing the per-row prefix. The ``not any(...)``
        predicate keys on the aggregate-distinguishing tail
        (``"disposal(s) ("`` / ``"verify each is a network fee"``), NOT on the
        shared ``"Removed untagged-whitelisted fee disposal"`` prefix alone, so a
        mixed tagged+untagged fixture would not let the aggregate trip the
        negative check (r1 finding #3 wording discipline). The Task 1 grep-gate
        (count of ``"disposal for"`` == 1) is the load-bearing invariant; this
        negative assertion mirrors it.
        """
        th = tmp_path / "th.csv"
        _write_th_csv(
            th,
            [
                _transfer_row(tx_hash="0xAAA"),
                _withdrawal_row(
                    tag="Cost",
                    sent_amount="0.00100000",
                    sent_currency="ETH",
                    net_value_eur="3.00",
                    tx_hash="0xAAA",
                ),
            ],
        )
        lot = _make_cg_lot(
            disposal_timestamp="2025-03-30 12:00",
            asset="ETH",
            amount=Decimal("0.00100000"),
        )

        # caplog at DEBUG so a stray per-row emission would be captured too.
        with caplog.at_level(logging.DEBUG, logger=_FEE_LOGGER):
            remove_transaction_fees(
                capital_entries=[lot],
                transaction_history_file=th,
                jurisdiction=_make_jurisdiction(),
            )

        # Tagged removal still logs at INFO (the INFO branch is UNCHANGED).
        assert any(
            r.levelno == logging.INFO and "Removed fee-matched CG lot" in r.getMessage()
            for r in caplog.records
        ), "tagged removal must log at INFO"

        # No WARNING-level record matches the untagged-whitelisted aggregate
        # (keys on the aggregate-distinguishing tail, not the shared prefix).
        assert not any(
            r.levelno == logging.WARNING
            and "untagged-whitelisted fee disposal(s) (" in r.getMessage()
            for r in caplog.records
        ), "tagged removal must NOT emit the untagged-whitelisted aggregate WARNING"

        # No DEBUG per-row record contains the per-row prefix (the load-bearing
        # grep-gate invariant: ``"disposal for"`` count is 0 for a tagged-only run).
        assert not any(
            r.levelno == logging.DEBUG
            and "Removed untagged-whitelisted fee disposal for" in r.getMessage()
            for r in caplog.records
        ), "tagged removal must NOT emit the untagged-whitelisted per-row DEBUG record"


class TestSuspects:
    """Unlisted-asset suspects are surfaced (flagged), not removed."""

    def test_warns_on_unlisted_suspected_fee(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Untagged RUNE (not a dict key) with Net Value 0.3 (<= max 1.0) -> retained,
        flagged review_required=True, CryptoReviewEntry(source_section=capital_gains)
        appended.

        Per-row detail is captured at DEBUG (pattern D conversion: the in-loop
        emission was downgraded to ``logger.debug``); exactly one aggregate WARNING
        summary ("Surfaced N suspect untagged network fees") is emitted. The
        aggregate uses distinct "Surfaced" wording that must NOT collide with the
        per-row "Possible untagged fee for unlisted asset" substring (see the
        negative assertion in ``test_retains_untagged_non_whitelist_withdrawals``).
        """
        th = tmp_path / "th.csv"
        _write_th_csv(
            th,
            [
                _transfer_row(tx_hash="0xAAA"),
                _withdrawal_row(
                    sent_amount="0.01000000",
                    sent_currency="RUNE",
                    net_value_eur="0.3",
                    tx_hash="0xAAA",
                ),
            ],
        )
        lot = _make_cg_lot(
            disposal_timestamp="2025-03-30 12:00",
            asset="RUNE",
            amount=Decimal("0.01000000"),
        )

        review_entries: list[CryptoReviewEntry] = []
        # caplog at DEBUG so the downgraded per-row detail is captured.
        with caplog.at_level(logging.DEBUG, logger=_FEE_LOGGER):
            remaining, suspects = remove_transaction_fees(
                capital_entries=[lot],
                transaction_history_file=th,
                jurisdiction=_make_jurisdiction(),
            )
            flagged = flag_fee_suspects(
                capital_entries=remaining,
                suspect_events=suspects,
                review_entries=review_entries,
            )

        # Lot retained (suspects are NOT removed).
        assert len(flagged) == 1
        assert flagged[0].review_required is True
        assert flagged[0].review_reason is not None
        assert "RUNE" in flagged[0].review_reason
        # CryptoReviewEntry appended with capital_gains source (it matched a CG lot).
        assert len(review_entries) == 1
        assert review_entries[0].source_section == "capital_gains"
        assert review_entries[0].asset == "RUNE"
        # Per-row detail is preserved at DEBUG (pattern D Design Invariant 3).
        per_row_records = [
            r
            for r in caplog.records
            if r.levelno == logging.DEBUG
            and "Possible untagged fee for unlisted asset RUNE" in r.getMessage()
            and "0.3" in r.getMessage()
        ]
        assert len(per_row_records) == 1, (
            "per-row DEBUG detail for RUNE suspect must be captured exactly once"
        )
        # Exactly one aggregate INFO summary using the distinct "Surfaced" wording
        # (demoted from WARNING to INFO in Task 8; CryptoReviewEntry is appended
        # downstream, preserving the Excel review signal).
        summary_records = [
            r
            for r in caplog.records
            if r.levelno == logging.INFO
            and "Surfaced" in r.getMessage()
            and "suspect untagged network fees" in r.getMessage()
        ]
        assert len(summary_records) == 1, (
            "exactly one aggregate INFO summary for suspect untagged network fees"
        )

        # Negative-at-WARNING guard (Invariant #4): summary demoted to INFO, no WARNING.
        assert not any(
            r.levelno == logging.WARNING
            and "Surfaced" in r.getMessage()
            and "suspect untagged network fees" in r.getMessage()
            for r in caplog.records
        )

    def test_warns_on_unlisted_suspected_fee_at_exact_max(
        self, tmp_path: Path
    ) -> None:
        """Untagged RUNE at Net Value 1.0 (== max(per_asset.values())) -> suspect surfaced."""
        th = tmp_path / "th.csv"
        _write_th_csv(
            th,
            [
                _transfer_row(tx_hash="0xAAA"),
                _withdrawal_row(
                    sent_amount="0.01000000",
                    sent_currency="RUNE",
                    net_value_eur="1.0",
                    tx_hash="0xAAA",
                ),
            ],
        )
        lot = _make_cg_lot(
            disposal_timestamp="2025-03-30 12:00",
            asset="RUNE",
            amount=Decimal("0.01000000"),
        )

        review_entries: list[CryptoReviewEntry] = []
        remaining, suspects = remove_transaction_fees(
            capital_entries=[lot],
            transaction_history_file=th,
            jurisdiction=_make_jurisdiction(),
        )
        flag_fee_suspects(
            capital_entries=remaining,
            suspect_events=suspects,
            review_entries=review_entries,
        )

        assert len(suspects) == 1
        assert len(review_entries) == 1

    def test_no_warning_for_unlisted_large_withdrawal(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Untagged RUNE with Net Value 5.0 (> max ceiling) -> retained, NOT flagged."""
        th = tmp_path / "th.csv"
        _write_th_csv(
            th,
            [
                _transfer_row(tx_hash="0xAAA"),
                _withdrawal_row(
                    sent_amount="10.00000000",
                    sent_currency="RUNE",
                    net_value_eur="5.0",
                    tx_hash="0xAAA",
                ),
            ],
        )
        lot = _make_cg_lot(
            disposal_timestamp="2025-03-30 12:00",
            asset="RUNE",
            amount=Decimal("10.00000000"),
        )

        review_entries: list[CryptoReviewEntry] = []
        with caplog.at_level(logging.WARNING, logger=_FEE_LOGGER):
            remaining, suspects = remove_transaction_fees(
                capital_entries=[lot],
                transaction_history_file=th,
                jurisdiction=_make_jurisdiction(),
            )
            flagged = flag_fee_suspects(
                capital_entries=remaining,
                suspect_events=suspects,
                review_entries=review_entries,
            )

        assert suspects == []
        assert len(flagged) == 1
        assert flagged[0].review_required is False
        assert review_entries == []
        assert not any(
            "Possible untagged fee for unlisted asset" in r.getMessage()
            for r in caplog.records
        )

    def test_whitelisted_over_ceiling_is_not_suspect(self, tmp_path: Path) -> None:
        """Untagged SOL with Net Value 0.75 (> 0.5 SOL ceiling, <= max 1.0) -> NOT a suspect.

        Guards the safety seam of Design Invariant 3: a wrong impl that flags
        "anything <= max(per_asset.values()) regardless of whitelist membership"
        fails here.
        """
        th = tmp_path / "th.csv"
        _write_th_csv(
            th,
            [
                _transfer_row(tx_hash="0xAAA"),
                _withdrawal_row(
                    sent_amount="0.00500000",
                    sent_currency="SOL",
                    net_value_eur="0.75",
                    tx_hash="0xAAA",
                ),
            ],
        )
        lot = _make_cg_lot(
            disposal_timestamp="2025-03-30 12:00",
            asset="SOL",
            amount=Decimal("0.00500000"),
        )

        review_entries: list[CryptoReviewEntry] = []
        remaining, suspects = remove_transaction_fees(
            capital_entries=[lot],
            transaction_history_file=th,
            jurisdiction=_make_jurisdiction(),
        )
        flagged = flag_fee_suspects(
            capital_entries=remaining,
            suspect_events=suspects,
            review_entries=review_entries,
        )

        assert suspects == []
        assert flagged[0].review_required is False
        assert review_entries == []

    def test_no_warning_for_unlisted_suspect_with_unique_txhash(
        self, tmp_path: Path
    ) -> None:
        """Untagged RUNE with Net Value 0.1 (<= ceiling) but TxHash once -> NOT a suspect."""
        th = tmp_path / "th.csv"
        _write_th_csv(
            th,
            [
                _withdrawal_row(
                    sent_amount="0.01000000",
                    sent_currency="RUNE",
                    net_value_eur="0.1",
                    tx_hash="0xUNIQUE",
                ),
            ],
        )
        lot = _make_cg_lot(
            disposal_timestamp="2025-03-30 12:00",
            asset="RUNE",
            amount=Decimal("0.01000000"),
        )

        review_entries: list[CryptoReviewEntry] = []
        remaining, suspects = remove_transaction_fees(
            capital_entries=[lot],
            transaction_history_file=th,
            jurisdiction=_make_jurisdiction(),
        )
        flag_fee_suspects(
            capital_entries=remaining,
            suspect_events=suspects,
            review_entries=review_entries,
        )

        assert suspects == []
        assert review_entries == []

    def test_two_same_valued_suspect_lots_both_flagged(self, tmp_path: Path) -> None:
        """Two suspect events with value-identical but distinct CG lots -> BOTH flagged.

        Guards the r7 M6 INDEX-keyed rebuild: a regression that abandons
        ``IndexedLot.index`` for a value/dict-keyed rebuild silently overwrites
        on collision and flags only ONE.
        """
        th = tmp_path / "th.csv"
        _write_th_csv(
            th,
            [
                _transfer_row(tx_hash="0xAAA"),
                _withdrawal_row(
                    sent_amount="0.01000000",
                    sent_currency="RUNE",
                    net_value_eur="0.3",
                    tx_hash="0xAAA",
                ),
                _transfer_row(tx_hash="0xBBB"),
                _withdrawal_row(
                    sent_amount="0.01000000",
                    sent_currency="RUNE",
                    net_value_eur="0.3",
                    tx_hash="0xBBB",
                ),
            ],
        )
        lot_a = _make_cg_lot(
            disposal_timestamp="2025-03-30 12:00",
            asset="RUNE",
            amount=Decimal("0.01000000"),
        )
        lot_b = _make_cg_lot(
            disposal_timestamp="2025-03-30 12:00",
            asset="RUNE",
            amount=Decimal("0.01000000"),
        )

        review_entries: list[CryptoReviewEntry] = []
        remaining, suspects = remove_transaction_fees(
            capital_entries=[lot_a, lot_b],
            transaction_history_file=th,
            jurisdiction=_make_jurisdiction(),
        )
        flagged = flag_fee_suspects(
            capital_entries=remaining,
            suspect_events=suspects,
            review_entries=review_entries,
        )

        assert len(suspects) == 2
        # BOTH lots flagged (index-keyed rebuild, not value-keyed).
        assert flagged[0].review_required is True
        assert flagged[1].review_required is True

    def test_fee_surplus_lot_then_flagged_as_suspect(self, tmp_path: Path) -> None:
        """A Cost-tagged RUNE fee with 2 CG lots (1 fee event) leaves 1 surplus lot;
        an untagged RUNE suspect matching the surviving lot -> survivor flagged as
        suspect (NOT removed, NOT double-removed)."""
        th = tmp_path / "th.csv"
        _write_th_csv(
            th,
            [
                _transfer_row(tx_hash="0xAAA"),
                # Tagged fee event (1 event) for 0.001 RUNE.
                _withdrawal_row(
                    tag="Cost",
                    sent_amount="0.00100000",
                    sent_currency="RUNE",
                    net_value_eur="0.3",
                    tx_hash="0xAAA",
                ),
                _transfer_row(tx_hash="0xBBB"),
                # Untagged suspect event for the surviving 0.001 RUNE lot.
                _withdrawal_row(
                    sent_amount="0.00100000",
                    sent_currency="RUNE",
                    net_value_eur="0.3",
                    tx_hash="0xBBB",
                ),
            ],
        )
        # Two value-identical lots: fee pass removes ONE (surplus = 1).
        lot_a = _make_cg_lot(
            disposal_timestamp="2025-03-30 12:00",
            asset="RUNE",
            amount=Decimal("0.00100000"),
        )
        lot_b = _make_cg_lot(
            disposal_timestamp="2025-03-30 12:00",
            asset="RUNE",
            amount=Decimal("0.00100000"),
        )

        review_entries: list[CryptoReviewEntry] = []
        remaining, suspects = remove_transaction_fees(
            capital_entries=[lot_a, lot_b],
            transaction_history_file=th,
            jurisdiction=_make_jurisdiction(),
        )
        # Fee pass removed one lot; one survives.
        assert len(remaining) == 1
        assert len(suspects) == 1
        flagged = flag_fee_suspects(
            capital_entries=remaining,
            suspect_events=suspects,
            review_entries=review_entries,
        )
        # Survivor flagged as suspect, NOT removed.
        assert len(flagged) == 1
        assert flagged[0].review_required is True

    def test_non_cg_suspect_appends_transaction_history_entry(
        self, tmp_path: Path
    ) -> None:
        """A RUNE suspect that does NOT match any CG lot -> CryptoReviewEntry(source_section=
        transaction_history) appended and a WARNING logged."""
        th = tmp_path / "th.csv"
        _write_th_csv(
            th,
            [
                _transfer_row(tx_hash="0xAAA"),
                _withdrawal_row(
                    sent_amount="0.01000000",
                    sent_currency="RUNE",
                    net_value_eur="0.3",
                    tx_hash="0xAAA",
                ),
            ],
        )
        # No CG lot at the suspect's key -> no match.
        review_entries: list[CryptoReviewEntry] = []
        remaining, suspects = remove_transaction_fees(
            capital_entries=[],
            transaction_history_file=th,
            jurisdiction=_make_jurisdiction(),
        )
        flagged = flag_fee_suspects(
            capital_entries=remaining,
            suspect_events=suspects,
            review_entries=review_entries,
        )

        assert suspects, "expected a suspect from the unlisted RUNE withdrawal"
        assert flagged == []
        assert len(review_entries) == 1
        assert review_entries[0].source_section == "transaction_history"
        # r7 L5: assert the RENDERED label too, so a forgotten extension that
        # falls back to "Income" fails the test.
        rendered = _render_source_label(review_entries[0])
        assert rendered == "Transaction History"

    def test_capital_gains_suspect_renders_capital_gains_label(
        self, tmp_path: Path
    ) -> None:
        """r7 L5: a CG-matched suspect renders 'Capital Gains' (sanity check the mapping)."""
        th = tmp_path / "th.csv"
        _write_th_csv(
            th,
            [
                _transfer_row(tx_hash="0xAAA"),
                _withdrawal_row(
                    sent_amount="0.01000000",
                    sent_currency="RUNE",
                    net_value_eur="0.3",
                    tx_hash="0xAAA",
                ),
            ],
        )
        lot = _make_cg_lot(
            disposal_timestamp="2025-03-30 12:00",
            asset="RUNE",
            amount=Decimal("0.01000000"),
        )
        review_entries: list[CryptoReviewEntry] = []
        remaining, suspects = remove_transaction_fees(
            capital_entries=[lot],
            transaction_history_file=th,
            jurisdiction=_make_jurisdiction(),
        )
        flag_fee_suspects(
            capital_entries=remaining,
            suspect_events=suspects,
            review_entries=review_entries,
        )

        assert review_entries[0].source_section == "capital_gains"
        assert _render_source_label(review_entries[0]) == "Capital Gains"

    def test_suspect_reason_appends_to_existing_reason(
        self, tmp_path: Path
    ) -> None:
        """r4 Medium: a CG-matched suspect with an existing review_reason gets the suspect
        reason APPENDED (not clobbering the tax-critical reason)."""
        th = tmp_path / "th.csv"
        _write_th_csv(
            th,
            [
                _transfer_row(tx_hash="0xAAA"),
                _withdrawal_row(
                    sent_amount="0.01000000",
                    sent_currency="RUNE",
                    net_value_eur="0.3",
                    tx_hash="0xAAA",
                ),
            ],
        )
        existing_reason = "Missing cost basis with tax impact"
        lot = _make_cg_lot(
            disposal_timestamp="2025-03-30 12:00",
            asset="RUNE",
            amount=Decimal("0.01000000"),
            review_required=True,
            review_reason=existing_reason,
        )

        review_entries: list[CryptoReviewEntry] = []
        remaining, suspects = remove_transaction_fees(
            capital_entries=[lot],
            transaction_history_file=th,
            jurisdiction=_make_jurisdiction(),
        )
        flagged = flag_fee_suspects(
            capital_entries=remaining,
            suspect_events=suspects,
            review_entries=review_entries,
        )

        assert flagged[0].review_reason is not None
        assert existing_reason in flagged[0].review_reason
        assert "RUNE" in flagged[0].review_reason


class TestEmptyDictAndCollisions:
    """Empty-dict safety, collisions, and summary logging."""

    from unittest.mock import patch

    @patch("tax_reporting.application.crypto.fee_filter._load_layer_1_major_chains", return_value=set())
    def test_empty_dict_with_flag_enabled_is_noop(
        self, mock_load: object, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Flag enabled, EMPTY per_asset and empty L1 chains, untagged co-occurring RUNE -> no crash, no
        suspect WARNING, no CryptoReviewEntry, lot retained. The max() guard short-
        circuits the suspect branch; the untagged-whitelisted branch finds nothing."""
        th = tmp_path / "th.csv"
        _write_th_csv(
            th,
            [
                _transfer_row(tx_hash="0xAAA"),
                _withdrawal_row(
                    sent_amount="0.01000000",
                    sent_currency="RUNE",
                    net_value_eur="0.3",
                    tx_hash="0xAAA",
                ),
            ],
        )
        lot = _make_cg_lot(
            disposal_timestamp="2025-03-30 12:00",
            asset="RUNE",
            amount=Decimal("0.01000000"),
        )

        review_entries: list[CryptoReviewEntry] = []
        with caplog.at_level(logging.WARNING, logger=_FEE_LOGGER):
            remaining, suspects = remove_transaction_fees(
                capital_entries=[lot],
                transaction_history_file=th,
                jurisdiction=_make_jurisdiction(per_asset={}),
            )
            flagged = flag_fee_suspects(
                capital_entries=remaining,
                suspect_events=suspects,
                review_entries=review_entries,
            )

        assert remaining == [lot]
        assert suspects == []
        assert flagged == [lot]
        assert review_entries == []
        # The empty-dict configuration WARNING fired.
        assert any(
            "exclude_transaction_fees is enabled but" in r.getMessage()
            for r in caplog.records
        )
        # No suspect WARNING.
        assert not any(
            "Possible untagged fee for unlisted asset" in r.getMessage()
            for r in caplog.records
        )

    def test_tagged_fee_still_removed_with_empty_dict(self, tmp_path: Path) -> None:
        """r10 testing: a Cost-tagged co-occurring withdrawal under an EMPTY per_asset ->
        the lot IS removed. The tagged path is dict-INDEPENDENT (Gist step 1)."""
        th = tmp_path / "th.csv"
        _write_th_csv(
            th,
            [
                _transfer_row(tx_hash="0xAAA"),
                _withdrawal_row(
                    tag="Cost",
                    sent_amount="0.00100000",
                    sent_currency="ETH",
                    net_value_eur="3.00",
                    tx_hash="0xAAA",
                ),
            ],
        )
        lot = _make_cg_lot(
            disposal_timestamp="2025-03-30 12:00",
            asset="ETH",
            amount=Decimal("0.00100000"),
        )

        remaining, _suspects = remove_transaction_fees(
            capital_entries=[lot],
            transaction_history_file=th,
            jurisdiction=_make_jurisdiction(per_asset={}),
        )

        assert remaining == []

    def test_warns_on_collision(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        """Multiple CG entries matching the same TH fee withdrawal event -> a surplus
        warning fires (the matcher flags surplus lots at the same exact-match key)."""
        th = tmp_path / "th.csv"
        _write_th_csv(
            th,
            [
                _transfer_row(tx_hash="0xAAA"),
                _withdrawal_row(
                    tag="Cost",
                    sent_amount="0.00100000",
                    sent_currency="ETH",
                    net_value_eur="3.00",
                    tx_hash="0xAAA",
                ),
            ],
        )
        # Two value-identical lots, only one fee event -> one surplus lot.
        lot_a = _make_cg_lot(
            disposal_timestamp="2025-03-30 12:00",
            asset="ETH",
            amount=Decimal("0.00100000"),
        )
        lot_b = _make_cg_lot(
            disposal_timestamp="2025-03-30 12:00",
            asset="ETH",
            amount=Decimal("0.00100000"),
        )

        with caplog.at_level(logging.WARNING, logger=_FEE_LOGGER):
            remaining, _suspects = remove_transaction_fees(
                capital_entries=[lot_a, lot_b],
                transaction_history_file=th,
                jurisdiction=_make_jurisdiction(),
            )

        # One lot removed, one surplus retained.
        assert len(remaining) == 1
        # The summary WARNING fired naming surplus lots.
        assert any(
            "Fee CG dedup summary" in r.getMessage() and "surplus" in r.getMessage()
            for r in caplog.records
        )

    def test_summary_warning_is_logged(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Exactly one aggregate warning summary for the fee pass carrying the "Fee"
        domain label and the fee module's logger name; the suspect pass (match_lots)
        emits NO summary."""
        th = tmp_path / "th.csv"
        _write_th_csv(
            th,
            [
                _transfer_row(tx_hash="0xAAA"),
                _withdrawal_row(
                    tag="Cost",
                    sent_amount="0.00100000",
                    sent_currency="ETH",
                    net_value_eur="3.00",
                    tx_hash="0xAAA",
                ),
            ],
        )
        lot = _make_cg_lot(
            disposal_timestamp="2025-03-30 12:00",
            asset="ETH",
            amount=Decimal("0.00100000"),
        )

        with caplog.at_level(logging.WARNING, logger=_FEE_LOGGER):
            remove_transaction_fees(
                capital_entries=[lot],
                transaction_history_file=th,
                jurisdiction=_make_jurisdiction(),
            )

        summary_records = [
            r for r in caplog.records if "Fee CG dedup summary" in r.getMessage()
        ]
        assert len(summary_records) == 1, "exactly one aggregate fee summary WARNING"
        assert summary_records[0].name == _FEE_LOGGER


class TestNoOpGates:
    """Disabled-flag and missing-jurisdiction no-ops."""

    def test_disabled_flag_is_noop(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """exclude_transaction_fees = False -> returned list equals input, no warning,
        no CryptoReviewEntry."""
        th = tmp_path / "th.csv"
        _write_th_csv(
            th,
            [
                _transfer_row(tx_hash="0xAAA"),
                _withdrawal_row(
                    tag="Cost",
                    sent_amount="0.00100000",
                    sent_currency="ETH",
                    net_value_eur="3.00",
                    tx_hash="0xAAA",
                ),
            ],
        )
        lot = _make_cg_lot(
            disposal_timestamp="2025-03-30 12:00",
            asset="ETH",
            amount=Decimal("0.00100000"),
        )

        review_entries: list[CryptoReviewEntry] = []
        with caplog.at_level(logging.WARNING, logger=_FEE_LOGGER):
            remaining, suspects = remove_transaction_fees(
                capital_entries=[lot],
                transaction_history_file=th,
                jurisdiction=_make_jurisdiction(flag=False),
            )
            flagged = flag_fee_suspects(
                capital_entries=remaining,
                suspect_events=suspects,
                review_entries=review_entries,
            )

        assert remaining == [lot]
        assert suspects == []
        assert flagged == [lot]
        assert review_entries == []
        assert not caplog.records, "disabled flag must emit no warnings"

    def test_no_jurisdiction_is_noop(self, tmp_path: Path) -> None:
        """jurisdiction = None -> returned list equals input."""
        th = tmp_path / "th.csv"
        _write_th_csv(th, [])
        lot = _make_cg_lot(
            disposal_timestamp="2025-03-30 12:00",
            asset="ETH",
            amount=Decimal("0.00100000"),
        )

        remaining, suspects = remove_transaction_fees(
            capital_entries=[lot],
            transaction_history_file=th,
            jurisdiction=None,
        )

        assert remaining == [lot]
        assert suspects == []

    def test_no_transaction_history_file_is_noop(self) -> None:
        """transaction_history_file = None -> returned list equals input."""
        lot = _make_cg_lot(
            disposal_timestamp="2025-03-30 12:00",
            asset="ETH",
            amount=Decimal("0.00100000"),
        )

        remaining, suspects = remove_transaction_fees(
            capital_entries=[lot],
            transaction_history_file=None,
            jurisdiction=_make_jurisdiction(),
        )

        assert remaining == [lot]
        assert suspects == []


class TestEventTypes:
    """Smoke-test the FeeThEvent / SuspectThEvent dataclasses (frozen, hashable)."""

    def test_fee_th_event_is_frozen_and_hashable(self) -> None:
        import dataclasses as _dc

        ev = FeeThEvent(
            timestamp="2025-03-30 12:00",
            asset="ETH",
            wallet="MetaMask",
            amount=Decimal("0.001"),
            tagged=True,
            tx_hash="0xAAA",
            net_value_eur=Decimal("0"),
        )
        assert hash(ev) == hash(ev)
        with pytest.raises(_dc.FrozenInstanceError):
            ev.tagged = False  # type: ignore[misc]

    def test_suspect_th_event_is_frozen_and_hashable(self) -> None:
        ev = SuspectThEvent(
            timestamp="2025-03-30 12:00",
            asset="RUNE",
            wallet="MetaMask",
            amount=Decimal("0.001"),
            tx_hash="0xAAA",
            net_value_eur=Decimal("0.3"),
        )
        assert hash(ev) == hash(ev)

class TestEmbeddedFees:
    """Embedded fees from exchange rows evaluated against CG proceeds."""

    def test_parses_embedded_fees_and_evaluates_proceeds(self, tmp_path: Path) -> None:
        """An exchange row with inflated TH Net Value but embedded fee within ceiling."""
        th = tmp_path / "th.csv"
        _write_th_csv(
            th,
            [
                {
                    "Date": "2025-03-30 12:00:00 UTC",
                    "Type": "exchange",
                    "Tag": "",
                    "Sending Wallet": "MetaMask",
                    "Sent Amount": "1.00000000",
                    "Sent Currency": "BTC",
                    "Receiving Wallet": "MetaMask",
                    "Received Amount": "20.00000000",
                    "Received Currency": "ETH",
                    "Fee Amount": "0.00100000",
                    "Fee Currency": "BNB",
                    "Net Value (EUR)": "5000.00",
                    "TxHash": "0xAAA",
                },
            ],
        )
        lot = _make_cg_lot(
            disposal_timestamp="2025-03-30 12:00",
            asset="BNB",
            wallet="MetaMask",
            amount=Decimal("0.00100000"),
            proceeds_eur=Decimal("0.40"),
            gain_loss_eur=Decimal("0.40"),
            cost_eur=Decimal("0.00"),
        )
        
        remaining, _suspects = remove_transaction_fees(
            capital_entries=[lot],
            transaction_history_file=th,
            jurisdiction=_make_jurisdiction(),
        )

        assert remaining == []

    def test_retains_embedded_fees_exceeding_proceeds_threshold(self, tmp_path: Path) -> None:
        """An exchange row where the matched CG lot proceeds > ceiling -> retained."""
        th = tmp_path / "th.csv"
        _write_th_csv(
            th,
            [
                {
                    "Date": "2025-03-30 12:00:00 UTC",
                    "Type": "exchange",
                    "Tag": "",
                    "Sending Wallet": "MetaMask",
                    "Sent Amount": "1.00000000",
                    "Sent Currency": "BTC",
                    "Receiving Wallet": "MetaMask",
                    "Received Amount": "20.00000000",
                    "Received Currency": "ETH",
                    "Fee Amount": "0.00100000",
                    "Fee Currency": "BNB",
                    "Net Value (EUR)": "5000.00",
                    "TxHash": "0xAAA",
                },
            ],
        )
        lot = _make_cg_lot(
            disposal_timestamp="2025-03-30 12:00",
            asset="BNB",
            wallet="MetaMask",
            amount=Decimal("0.00100000"),
            proceeds_eur=Decimal("0.60"),
            gain_loss_eur=Decimal("0.60"),
            cost_eur=Decimal("0.00"),
        )
        
        remaining, _suspects = remove_transaction_fees(
            capital_entries=[lot],
            transaction_history_file=th,
            jurisdiction=_make_jurisdiction(),
        )

        assert remaining == [lot]

    def test_retains_fragmented_embedded_fees_exceeding_threshold_in_aggregate(self, tmp_path: Path) -> None:
        """An exchange row where two matched CG lots' combined proceeds > ceiling -> both retained."""
        th = tmp_path / "th.csv"
        _write_th_csv(
            th,
            [
                {
                    "Date": "2025-03-30 12:00:00 UTC",
                    "Type": "exchange",
                    "Tag": "",
                    "Sending Wallet": "MetaMask",
                    "Sent Amount": "1.00000000",
                    "Sent Currency": "BTC",
                    "Receiving Wallet": "MetaMask",
                    "Received Amount": "20.00000000",
                    "Received Currency": "ETH",
                    "Fee Amount": "0.00100000",
                    "Fee Currency": "BNB",
                    "Net Value (EUR)": "5000.00",
                    "TxHash": "0xAAA",
                },
            ],
        )
        # Ceiling is 0.5 EUR. Two lots of 0.3 EUR sum to 0.6 EUR > 0.5 EUR.
        lot1 = _make_cg_lot(
            disposal_timestamp="2025-03-30 12:00",
            asset="BNB",
            wallet="MetaMask",
            amount=Decimal("0.00050000"),
            proceeds_eur=Decimal("0.30"),
            gain_loss_eur=Decimal("0.30"),
            cost_eur=Decimal("0.00"),
        )
        lot2 = _make_cg_lot(
            disposal_timestamp="2025-03-30 12:00",
            asset="BNB",
            wallet="MetaMask",
            amount=Decimal("0.00050000"),
            proceeds_eur=Decimal("0.30"),
            gain_loss_eur=Decimal("0.30"),
            cost_eur=Decimal("0.00"),
        )
        
        remaining, _suspects = remove_transaction_fees(
            capital_entries=[lot1, lot2],
            transaction_history_file=th,
            jurisdiction=_make_jurisdiction(),
        )

        assert remaining == [lot1, lot2]
