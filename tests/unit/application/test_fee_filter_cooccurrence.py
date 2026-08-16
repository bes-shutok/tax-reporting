"""Tests for the re-scoped co-occurrence guard in ``fee_filter.py`` (Plan Task 5).

Plan: ``docs/history/plans/2026-08-02-on-chain-tx-tagger.md`` Task 5.

These tests pin the B4 re-scope (the co-occurrence guard keys on whether a
NON-FEE event co-occurs with the withdrawal, NOT merely on ``>= 2 rows sharing
the TxHash``) and the CSV<->object bridge that lets ``event_id`` reach
``fee_filter`` as a dict column (review F2). They also pin review F5's
correction (``>= 2 distinct events`` is WRONG: two fee/withdrawal-Cost events
with no non-fee event must BOTH be rejected) and the B5 GasBurn double-count
guard.

Bridge decision (Plan Task 5 Step 1, option (a)): the on-chain adapter
(Task 10) serializes its rows to a TH-shaped CSV that includes an ``event_id``
column. ``read_koinly_rows``/``_detect_header_index`` need NO change because
``csv.DictReader`` already surfaces every header column as a dict key, and the
parser's row builder (``koinly_parser.py:76``) preserves all columns
(``if key is not None``). For Koinly CSVs (which have no ``event_id`` column),
``row.get("event_id")`` is ``None``, preserving today's behavior; the guard
reduces to today's ``count >= 2`` semantics (the Koinly co-occurrence signal is
row-count based).

The production entry point exercised here is
``_identify_fee_and_suspect_events(transaction_history_file, jurisdiction)``
(``fee_filter.py:179``): it is the scan invoked by ``remove_transaction_fees``
(``fee_filter.py:503``) and is the single source for BOTH the removed-fee set
and the suspect set. ``fee_filter``'s public contract is a file ``Path`` (the
adapter writes a TH-shaped CSV), so each test writes inline TH rows to a tmp CSV.

A withdrawal is "admitted" by the guard when the scan produces a ``FeeThEvent``
(the tagged path OR the untagged-whitelist path) OR a ``SuspectThEvent`` for
that row; "rejected" when neither list carries an event for it. To make the
co-occurrence guard the load-bearing discriminator, these tests use UNTAGGED
whitelisted withdrawals (the tagged path does not consult the guard, per
``fee_filter.py:263-293``): the asset is on the ``per_asset`` whitelist so the
row reaches the guard, and the guard alone decides admission.
"""

from __future__ import annotations

import csv
from decimal import Decimal
from pathlib import Path

from tax_reporting.application.crypto.fee_filter import _identify_fee_and_suspect_events
from tax_reporting.domain.jurisdiction import TaxJurisdictionConfig

# Per-token ceiling map: ETH and BERA are whitelisted so untagged withdrawals of
# these assets reach the co-occurrence guard (the load-bearing discriminator).
_PER_ASSET: dict[str, Decimal] = {
    "ETH": Decimal("1.0"),
    "BERA": Decimal("0.1"),
}


def _make_jurisdiction() -> TaxJurisdictionConfig:
    """Build a PT jurisdiction config fixture with the fee flag on."""
    return TaxJurisdictionConfig(
        country="PT",
        fiscal_year=2025,
        exclude_loan_repayment_gains=True,
        zero_basis_review_threshold=Decimal("50"),
        exclude_transaction_fees=True,
        exclude_transaction_fee_max_eur_per_asset=dict(_PER_ASSET),
    )


# Full Koinly Transaction History header. The on-chain adapter (Task 10)
# serializes its rows to this same TH shape PLUS an ``event_id`` column (the
# bridge); tests append ``event_id`` to this header when building on-chain rows.
_TH_HEADER: list[str] = [
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


def _write_th_csv(
    path: Path, rows: list[dict[str, str]], *, include_event_id: bool = False
) -> None:
    """Write a TH-shaped CSV with the standard Koinly preamble.

    ``include_event_id=True`` appends the ``event_id`` column to the header
    (the on-chain adapter projection; the bridge). When False (Koinly rows),
    no ``event_id`` column is written, so ``row.get("event_id")`` is ``None``.
    """
    header = list(_TH_HEADER)
    if include_event_id:
        header.append("event_id")
    with path.open("w", newline="", encoding="utf-8") as fh:
        fh.write("Transaction report 2025\n\n")
        writer = csv.DictWriter(fh, fieldnames=header)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in header})


def _koinly_withdrawal(  # noqa: PLR0913
    *,
    sent_currency: str = "ETH",
    sent_amount: str = "0.00100000",
    net_value_eur: str = "0.50",
    tx_hash: str = "0xAAA",
    tag: str = "",
    date: str = "2025-03-30 12:00:00 UTC",
) -> dict[str, str]:
    """A Koinly ``crypto_withdrawal`` TH row (no ``event_id`` column)."""
    return {
        "Date": date,
        "Type": "crypto_withdrawal",
        "Tag": tag,
        "Sending Wallet": "MetaMask",
        "Sent Amount": sent_amount,
        "Sent Currency": sent_currency,
        "Net Value (EUR)": net_value_eur,
        "TxHash": tx_hash,
    }


def _koinly_co_occurrence_row(*, tx_hash: str = "0xAAA") -> dict[str, str]:
    """A Koinly ``transfer`` TH row sharing a TxHash (the Koinly co-occurrence signal)."""
    return {
        "Date": "2025-03-30 12:00:00 UTC",
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


def _onchain_withdrawal(  # noqa: PLR0913
    *,
    event_id: str,
    tx_hash: str = "0xAAA",
    sent_currency: str = "ETH",
    sent_amount: str = "0.00100000",
    net_value_eur: str = "0.50",
    tag: str = "",
    date: str = "2025-03-30 12:00:00 UTC",
) -> dict[str, str]:
    """An on-chain ``crypto_withdrawal`` TH row carrying an ``event_id``."""
    return {
        "Date": date,
        "Type": "crypto_withdrawal",
        "Tag": tag,
        "Sending Wallet": "MetaMask",
        "Sent Amount": sent_amount,
        "Sent Currency": sent_currency,
        "Net Value (EUR)": net_value_eur,
        "TxHash": tx_hash,
        "event_id": event_id,
    }


def _onchain_nonfee_event(
    *,
    event_id: str,
    tx_hash: str = "0xAAA",
    event_type: str = "exchange",
    tag: str = "",
    date: str = "2025-03-30 12:00:00 UTC",
) -> dict[str, str]:
    """An on-chain NON-FEE event row carrying an ``event_id``.

    A Swap is ``Type=exchange``; a Reward is ``Type=crypto_deposit`` with
    ``Tag=Reward``. Both are the canonical non-fee events (a fee-bearing
    withdrawal is ``Type=crypto_withdrawal`` per ``fee_filter._FEE_TH_TYPE``).
    """
    return {
        "Date": date,
        "Type": event_type,
        "Tag": tag,
        "Sending Wallet": "MetaMask",
        "Sent Amount": "1.00000000",
        "Sent Currency": "BGT",
        "Receiving Wallet": "MetaMask",
        "Received Amount": "4.20000000",
        "Received Currency": "HONEY",
        "Net Value (EUR)": "3000.00",
        "TxHash": tx_hash,
        "event_id": event_id,
    }


class TestFeeFilterCooccurrence:
    """Plan Task 5 Step 2: the re-scoped co-occurrence guard (B4) + F5 correction."""

    def test_koinly_row_guard_unchanged(self, tmp_path: Path) -> None:
        """Koinly rows (no ``event_id`` column) -> guard behaves exactly as today.

        A whitelisted withdrawal whose TxHash appears >=2 times in TH is admitted
        (a ``FeeThEvent`` is emitted for it). This is the positive direction of
        the Koinly equivalence: ``has_nonfee_event_cooccurring`` reduces to
        ``count >= 2`` for Koinly rows.
        """
        th = tmp_path / "th.csv"
        _write_th_csv(
            th,
            [
                _koinly_co_occurrence_row(tx_hash="0xAAA"),
                _koinly_withdrawal(tx_hash="0xAAA", net_value_eur="0.50"),
            ],
        )

        fee_events, suspect_events = _identify_fee_and_suspect_events(
            th, _make_jurisdiction()
        )

        # The whitelisted ETH withdrawal (Net Value 0.50 <= 1.0 ceiling) is
        # admitted as an untagged-whitelist FeeThEvent.
        assert any(e.tx_hash == "0xAAA" for e in fee_events), (
            "Koinly co-occurring whitelisted withdrawal must be admitted (count >= 2)"
        )
        assert not any(s.tx_hash == "0xAAA" for s in suspect_events)

    def test_koinly_solo_withdrawal_rejected(self, tmp_path: Path) -> None:
        """A Koinly withdrawal whose TxHash appears only once -> rejected (review F4-r2).

        The NEGATIVE direction of the Koinly equivalence: the guard reduces to
        ``count >= 2``, so a withdrawal whose TxHash occurs only once is rejected
        by both the untagged-whitelist path (no FeeThEvent) AND the suspect path
        (no SuspectThEvent).
        """
        th = tmp_path / "th.csv"
        _write_th_csv(
            th,
            [
                # Solo withdrawal: TxHash 0xSOLO appears only once.
                _koinly_withdrawal(tx_hash="0xSOLO", net_value_eur="0.50"),
            ],
        )

        fee_events, suspect_events = _identify_fee_and_suspect_events(
            th, _make_jurisdiction()
        )

        assert not any(e.tx_hash == "0xSOLO" for e in fee_events), (
            "Solo Koinly withdrawal (TxHash count 1) must NOT be admitted"
        )
        assert not any(s.tx_hash == "0xSOLO" for s in suspect_events), (
            "Solo Koinly withdrawal (TxHash count 1) must NOT be a suspect either"
        )

    def test_onchain_withdrawal_cooccurs_with_nonfee_event_admitted(
        self, tmp_path: Path
    ) -> None:
        """On-chain: withdrawal co-occurring with a NON-FEE event (Swap) -> admitted (B4).

        One tx_hash has two Events with distinct ``event_id``s: a
        ``crypto_withdrawal`` (the fee candidate) and an ``exchange`` (a Swap,
        the canonical non-fee event). The withdrawal is admitted because a
        non-fee event co-occurs (B4 intent). This fails under the OLD ``count >=
        2`` predicate if event_ids are present but the count happens to be 2 —
        the load-bearing distinction is the NON-FEE-event predicate, not the row
        count.
        """
        th = tmp_path / "th.csv"
        _write_th_csv(
            th,
            [
                _onchain_withdrawal(event_id="evt_wd", tx_hash="0xAAA"),
                _onchain_nonfee_event(event_id="evt_swap", tx_hash="0xAAA"),
            ],
            include_event_id=True,
        )

        fee_events, _suspect_events = _identify_fee_and_suspect_events(
            th, _make_jurisdiction()
        )

        assert any(e.tx_hash == "0xAAA" for e in fee_events), (
            "On-chain withdrawal co-occurring with a non-fee event (Swap) must be "
            "admitted (B4: co-occurs with a non-fee event)"
        )

    def test_onchain_two_withdrawals_no_nonfee_event_rejected(
        self, tmp_path: Path
    ) -> None:
        """On-chain: two fee/withdrawal-Cost events, NO non-fee event -> BOTH rejected (F5).

        Review F5 (load-bearing): ``>= 2 distinct events`` is WRONG. A tx with two
        ``crypto_withdrawal`` events (both fees) and NO non-fee event must have
        BOTH rejected — the correct predicate is ``>= 1 non-fee event
        co-occurring``, not ``>= 2 distinct events``. Under the wrong ``>= 2
        distinct events`` predicate these would be wrongly admitted; the F5
        predicate rejects both.
        """
        th = tmp_path / "th.csv"
        _write_th_csv(
            th,
            [
                _onchain_withdrawal(
                    event_id="evt_wd1", tx_hash="0xAAA", sent_currency="ETH"
                ),
                _onchain_withdrawal(
                    event_id="evt_wd2", tx_hash="0xAAA", sent_currency="BERA"
                ),
            ],
            include_event_id=True,
        )

        fee_events, suspect_events = _identify_fee_and_suspect_events(
            th, _make_jurisdiction()
        )

        assert not any(e.tx_hash == "0xAAA" for e in fee_events), (
            "Two fee/withdrawal events with NO non-fee event must NOT be admitted "
            "(F5: '>=2 distinct events' is wrong; needs a non-fee co-occurrence)"
        )
        assert not any(s.tx_hash == "0xAAA" for s in suspect_events)

    def test_genuine_disposal_not_admitted_when_solo_event(self, tmp_path: Path) -> None:
        """An on-chain withdrawal that is the only Event in its tx -> rejected.

        The withdrawal is a genuine disposal (not a fee), but it is the only
        Event for its tx_hash: there is no non-fee co-occurrence (and no second
        row), so the guard rejects it. Under the OLD ``count >= 2`` predicate
        this is also rejected (count == 1); under the new predicate it is
        rejected because no non-fee event co-occurs.
        """
        th = tmp_path / "th.csv"
        _write_th_csv(
            th,
            [
                _onchain_withdrawal(event_id="evt_solo", tx_hash="0xSOLO"),
            ],
            include_event_id=True,
        )

        fee_events, suspect_events = _identify_fee_and_suspect_events(
            th, _make_jurisdiction()
        )

        assert not any(e.tx_hash == "0xSOLO" for e in fee_events), (
            "A solo on-chain withdrawal (only Event in its tx) must NOT be admitted"
        )
        assert not any(s.tx_hash == "0xSOLO" for s in suspect_events)


class TestFeeFilterGasBurn:
    """Plan Task 5 Step 2 (B5): a GasBurn row is not double-counted.

    A GasBurn Event is projected by the on-chain adapter (Task 10) as
    ``Type=crypto_withdrawal``/``Tag=Cost`` with ``Sent Amount``=gas and
    ``Fee Amount`` EMPTY (the carrier-row rule has an explicit GasBurn
    exception: gas is not a fee on top of itself). This test confirms the
    fee_filter's behavior GIVEN such a row: only the ``is_withdrawal`` path
    fires (the tagged-Cost withdrawal path), NOT the ``has_embedded_fee`` path
    (``Fee Amount`` is empty -> ``has_embedded_fee`` is False), so the gas is
    counted exactly once.
    """

    def test_gasburn_row_not_double_counted(self, tmp_path: Path) -> None:
        """GasBurn projection: ``Fee Amount`` empty -> only ``is_withdrawal`` fires."""
        th = tmp_path / "th.csv"
        _write_th_csv(
            th,
            [
                # A co-occurring non-fee event so the withdrawal is admitted by
                # the guard (the GasBurn row itself is the withdrawal under test;
                # the co-occurrence admits it via the tagged-Cost path).
                _onchain_nonfee_event(event_id="evt_swap", tx_hash="0xGAS"),
                # The GasBurn projection: crypto_withdrawal/Cost, Sent Amount=gas,
                # Fee Amount EMPTY (carrier-row GasBurn exception, Task 10).
                {
                    "Date": "2025-03-30 12:00:00 UTC",
                    "Type": "crypto_withdrawal",
                    "Tag": "Cost",
                    "Sending Wallet": "MetaMask",
                    "Sent Amount": "0.00020000",  # gas amount
                    "Sent Currency": "BERA",  # native gas asset
                    "Fee Amount": "",  # EMPTY (B5: gas isn't a fee on itself)
                    "Fee Currency": "",
                    "Net Value (EUR)": "0.01",
                    "TxHash": "0xGAS",
                    "event_id": "evt_gasburn",
                },
            ],
            include_event_id=True,
        )

        fee_events, _suspect_events = _identify_fee_and_suspect_events(
            th, _make_jurisdiction()
        )

        gasburn_events = [e for e in fee_events if e.tx_hash == "0xGAS"]
        # Exactly ONE FeeThEvent for the GasBurn row (the is_withdrawal/tagged
        # path), NOT two (the has_embedded_fee path must NOT also fire).
        assert len(gasburn_events) == 1, (
            f"GasBurn row must yield exactly one FeeThEvent (is_withdrawal path), "
            f"got {len(gasburn_events)}; has_embedded_fee must NOT also fire"
        )
        # The single event is the withdrawal-path event (NOT an embedded-fee
        # event): ``is_embedded`` is False.
        assert gasburn_events[0].is_embedded is False, (
            "GasBurn row must NOT be classified as an embedded fee (Fee Amount is "
            "empty -> has_embedded_fee is False); gas counted once via the "
            "is_withdrawal path only"
        )
        # Sanity: the gas asset is BERA and the amount is the gas amount.
        assert gasburn_events[0].asset == "BERA"
        assert gasburn_events[0].tagged is True  # Tag=Cost -> tagged path
