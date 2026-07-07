"""End-to-end smoke for Phase B (Task 4).

Exercises the full ``parse_th_row -> build_transaction -> resolve_treatment``
chain against synthetic TH rows so Phase A + Phase B wiring cannot silently
break. Mirrors the Phase A smoke test (``test_crypto_phase_a_smoke.py``) but
swaps ``classify_platform`` (Phase A) for ``resolve_treatment`` (Phase B) at
the end of the chain.

Per the plan, the ``WalletClassification`` fixture is constructed literally
(no registry or evidence wiring) so the smoke test is hermetic and does not
depend on the crypto-origin registry fixtures.
"""

from __future__ import annotations

from tax_reporting.application.crypto.entities import (
    Treatment,
    TreatmentConfig,
    WalletClassification,
    WalletKind,
    build_transaction,
    resolve_treatment,
)
from tax_reporting.domain.transaction import Transaction
from tax_reporting.infrastructure.koinly_parser import parse_th_row


def _cex_classification() -> WalletClassification:
    """Literal CEX classification fixture (no registry wiring).

    Phase B smoke tests do not exercise the classifier; they only need a
    ``WalletClassification`` that satisfies ``build_transaction``'s contract.
    A tier-1-style CEX fixture (confidence 1.0, source="registry") is the
    simplest input that does not trip ``is_unrecognized_wallet``.
    """
    return WalletClassification(
        kind=WalletKind.CEX,
        confidence=1.0,
        reason="fixture",
        source="registry",
    )


def _th_row(
    *,
    type_: str,
    tag: str,
    sending_side: bool,
) -> dict[str, str]:
    """Return a synthetic TH row dict for the smoke tests.

    A populated sending side mirrors a disposal-shaped row; an empty sending
    side with a populated receiving side mirrors an acquisition/transfer row.
    The Date is a parseable UTC literal; the other fields are neutral defaults.
    """
    if sending_side:
        sent_amount = "1,00000000"
        sent_currency = "ETH"
        sending_wallet = "Kraken"
        received_amount = ""
        received_currency = ""
        receiving_wallet = ""
    else:
        sent_amount = ""
        sent_currency = ""
        sending_wallet = ""
        received_amount = "1,00000000"
        received_currency = "ETH"
        receiving_wallet = "Kraken"

    return {
        "Date": "2025-06-14 12:33:01 UTC",
        "Type": type_,
        "Tag": tag,
        "Sending Wallet": sending_wallet,
        "Sent Amount": sent_amount,
        "Sent Currency": sent_currency,
        "Receiving Wallet": receiving_wallet,
        "Received Amount": received_amount,
        "Received Currency": received_currency,
        "TxHash": "",
        "TxSrc": "",
        "TxDest": "",
    }


def _run_chain(
    row: dict[str, str],
    *,
    row_index: int,
    config: TreatmentConfig,
) -> tuple[Transaction, Treatment]:
    """Run the Phase A + Phase B chain and return (transaction, treatment).

    Steps: ``parse_th_row -> build_transaction -> resolve_treatment``. The
    factory MUST be invoked (the ``Transaction`` constructor is not called
    directly) so the smoke test mirrors the sanctioned Phase A composition.
    """
    parsed = parse_th_row(row, row_index=row_index)
    transaction = build_transaction(parsed, _cex_classification())
    treatment = resolve_treatment(transaction, config)
    return transaction, treatment


class TestCryptoPhaseBSmoke:
    """End-to-end Phase B smoke tests (Phase A -> resolve_treatment chain)."""

    def test_full_chain_payment_row(self) -> None:
        """Given a TH row with Tag="Payment" and a populated sending side.

        The full chain ``parse_th_row -> build_transaction ->
        resolve_treatment(tx, TreatmentConfig())`` returns ``Treatment.PAYMENT``
        AND the parsed ``row_index`` is preserved on the Phase-A row (Monitor
        item 1 in the Phase A plan; this is the Phase B analog).
        """
        row = _th_row(type_="exchange", tag="Payment", sending_side=True)
        tx, treatment = _run_chain(row, row_index=7, config=TreatmentConfig())

        assert treatment is Treatment.PAYMENT
        assert tx.row.row_index == 7

    def test_full_chain_derivatives_close_with_injected_tags(self) -> None:
        """Given Tag="Realized gain" Type="crypto_withdrawal" + injected labels.

        With ``derivatives_tags=frozenset({"Realized gain"})`` (the production
        koinly_2025.json value), the chain resolves to
        ``Treatment.DERIVATIVES_CLOSE``. Without the injection the same row
        would resolve to ``REWARD_AIRDROP_LP`` (Invariant 6 precedence).
        """
        row = _th_row(
            type_="crypto_withdrawal",
            tag="Realized gain",
            sending_side=True,
        )
        config = TreatmentConfig(derivatives_tags=frozenset({"Realized gain"}))
        _tx, treatment = _run_chain(row, row_index=0, config=config)

        assert treatment is Treatment.DERIVATIVES_CLOSE

    def test_full_chain_other_for_plain_deposit(self) -> None:
        """Given Type="crypto_deposit", no sending side, no tag, expects OTHER.

        Non-disposal-shaped row with no special tag resolves to the OTHER
        default (Invariant 3).
        """
        row = _th_row(type_="crypto_deposit", tag="", sending_side=False)
        _tx, treatment = _run_chain(row, row_index=0, config=TreatmentConfig())

        assert treatment is Treatment.OTHER

    def test_full_chain_loan_repayment_trumps_disposal_side(self) -> None:
        """Given Tag="Loan Repayment" AND a populated sending side.

        Expects ``LOAN_REPAYMENT`` (the tag overrides the disposal default per
        Invariant 3 + Invariant 6 precedence).
        """
        row = _th_row(
            type_="exchange",
            tag="Loan Repayment",
            sending_side=True,
        )
        _tx, treatment = _run_chain(row, row_index=0, config=TreatmentConfig())

        assert treatment is Treatment.LOAN_REPAYMENT
