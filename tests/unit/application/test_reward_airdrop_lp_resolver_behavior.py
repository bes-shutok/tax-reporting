"""REWARD_AIRDROP_LP treatment - resolver-path characterization (Phase E).

Phase E Task 5 deleted the legacy inline-literal branches in
``token_origin.py::TokenOriginResolver._index_row`` and the
``_DEFAULT_REWARD_TAGS`` / ``_DEFAULT_AIRDROP_TAGS`` / ``_DEFAULT_LP_TAGS``
module-level constants (and the ``via_resolver`` parameter).
Identification of reward / airdrop / lp rows is now resolver-only:
``resolve_treatment`` over the pre-built ``list[Transaction]`` (built
ONCE in the production caller wiring step and passed through
``TokenOriginResolver``'s entry point) returns
``Treatment.REWARD_AIRDROP_LP``; the raw ``Tag`` literal then selects
the specific ``AcquisitionMethod`` (REWARD / AIRDROP /
LIQUIDITY_PROVISION / LIQUIDITY_WITHDRAWAL).

These characterization tests pin the surviving resolver-path behavior
post-Phase-E. The Phase-D flag-mechanic / legacy-branch tests
(``test_inline_literals_extracted_to_constants``,
``test_inline_literals_skipped_when_flag_on``,
``test_inline_literals_run_when_flag_off``) were deleted with the
legacy code paths they exercised.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tax_reporting.application import token_origin as token_origin_mod
from tax_reporting.application.crypto.treatment_resolver import (
    TreatmentConfig,
    resolve_treatment,
)
from tax_reporting.application.crypto_reporting import build_transactions_from_th
from tax_reporting.domain.token_origin import AcquisitionMethod
from tax_reporting.domain.treatment import Treatment

# Minimal synthetic TH CSV with reward / airdrop / lp deposit rows. The
# committed corpus under resources/source/example/2025/koinly/ has NO
# scenario with crypto_deposit rows tagged reward / airdrop / liquidity,
# so this test authors a synthetic TH inline (committed test data per
# crypto_implementation_guidelines.md "Committed Synthetic Fixtures"):
# sensitive fields (TxHash, TxSrc, TxDest) are empty; fictional wallets.
# Column layout mirrors the real Koinly TH export (see
# test_crypto_origin_resolver.py::_TH_HEADER).
_TH_HEADER = (
    "Transaction report 2025\n"
    "\n"
    "Date,Type,Tag,Sending Wallet,Sent Amount,Sent Currency,Sent Cost Basis,"
    "Receiving Wallet,Received Amount,Received Currency,Received Cost Basis,"
    "Fee Amount,Fee Currency,Gain (EUR),Net Value (EUR),Fee Value (EUR),"
    "TxSrc,TxDest,TxHash,Description"
)
_REWARD_TH_ROWS = (
    "2025-04-10 08:00:00 UTC,crypto_deposit,Reward,,,,,"
    "Demo Spot,\"1,00000000\",RWD,,,,,,,,,,,,\n"
    "2025-04-11 08:00:00 UTC,crypto_deposit,Airdrop,,,,,"
    "Demo Spot,\"2,00000000\",ADR,,,,,,,,,,,,\n"
    "2025-04-12 08:00:00 UTC,crypto_deposit,Liquidity in,,,,,"
    "Demo Spot,\"3,00000000\",LPT,,,,,,,,,,,,\n"
)


def _write_reward_th(tmp_path: Path) -> Path:
    """Write the synthetic reward/airdrop/lp TH CSV to ``tmp_path``.

    Returns the path so the resolver / construction helpers can read it.
    """
    th_path = tmp_path / "koinly_2025_transaction_history.csv"
    th_path.write_text(f"{_TH_HEADER}\n{_REWARD_TH_ROWS}", encoding="utf-8")
    return th_path


@pytest.mark.unit
class TestRewardAirdropLpResolverBehavior:
    """Characterize the REWARD_AIRDROP_LP identification on the resolver path.

    Phase E Task 5 deleted the legacy inline-literal branches and the
    ``_DEFAULT_REWARD_TAGS`` / ``_DEFAULT_AIRDROP_TAGS`` /
    ``_DEFAULT_LP_TAGS`` module-level constants from ``token_origin.py``.
    Identification is now resolver-only: ``resolve_treatment`` over the
    pre-built ``list[Transaction]`` is the sole source of the
    ``REWARD_AIRDROP_LP`` discriminator, and the raw ``Tag`` literal
    only disambiguates reward vs airdrop vs liquidity direction.
    """

    def test_resolver_identifies_reward_airdrop_lp(self, tmp_path: Path) -> None:
        """Tag=Reward and Tag=Airdrop rows resolve to REWARD_AIRDROP_LP.

        Pins the identification source (Phase B resolver) for the corpus
        rows the REWARD_AIRDROP_LP pipeline branch gates on. Under the
        default ``TreatmentConfig``, both ``Tag="Reward"`` and
        ``Tag="Airdrop"`` resolve to ``Treatment.REWARD_AIRDROP_LP``
        (Phase B Invariant 6 - reward / airdrop / lp tag sets all route
        to REWARD_AIRDROP_LP).
        """
        transactions = build_transactions_from_th(_write_reward_th(tmp_path))
        assert len(transactions) == 3, (
            f"expected 3 TH rows; got {len(transactions)}"
        )
        config = TreatmentConfig()
        treatments = [resolve_treatment(tx, config) for tx in transactions]
        assert treatments[0] is Treatment.REWARD_AIRDROP_LP, (
            f"Tag=Reward -> {[t.value for t in treatments]}"
        )
        assert treatments[1] is Treatment.REWARD_AIRDROP_LP, (
            f"Tag=Airdrop -> {[t.value for t in treatments]}"
        )
        assert treatments[2] is Treatment.REWARD_AIRDROP_LP, (
            f"Tag=Liquidity in -> {[t.value for t in treatments]}"
        )

    def test_reward_airdrop_lp_identification_resolver_path(
        self,
        tmp_path: Path,
    ) -> None:
        """Characterization: resolver path resolves origin; legacy constants are gone.

        Phase E Task 5 characterization. Given a ``REWARD_AIRDROP_LP``-
        treatment transaction, the indexer resolves origin via
        ``resolve_treatment`` over the pre-built ``transactions`` list
        (keyed by row index into ``self._treatment_by_row_index``).
        Phase E deleted the module-level ``_DEFAULT_REWARD_TAGS`` /
        ``_DEFAULT_AIRDROP_TAGS`` / ``_DEFAULT_LP_TAGS`` constants and
        the ``via_resolver`` parameter; the resolver path is the sole
        surviving branch.

        Discriminating assertions: (a) the three legacy constants no
        longer exist on the ``token_origin`` module (proving the
        deletion landed); (b) the resolver nonetheless resolves reward
        / airdrop / lp rows to the correct ``AcquisitionMethod`` via
        ``TreatmentConfig`` + the raw ``Tag`` literal.
        """
        th_path = _write_reward_th(tmp_path)
        transactions = build_transactions_from_th(th_path)
        config = TreatmentConfig()

        # Phase E Task 5 deleted the three module-level constants.
        assert not hasattr(token_origin_mod, "_DEFAULT_REWARD_TAGS"), (
            "Phase E Task 5: _DEFAULT_REWARD_TAGS must be deleted from token_origin.py"
        )
        assert not hasattr(token_origin_mod, "_DEFAULT_AIRDROP_TAGS"), (
            "Phase E Task 5: _DEFAULT_AIRDROP_TAGS must be deleted from token_origin.py"
        )
        assert not hasattr(token_origin_mod, "_DEFAULT_LP_TAGS"), (
            "Phase E Task 5: _DEFAULT_LP_TAGS must be deleted from token_origin.py"
        )

        from tax_reporting.application.token_origin import TokenOriginResolver

        resolver = TokenOriginResolver(
            th_path,
            transactions=transactions,
            config=config,
        )
        # Reward row (2025-04-10, RWD, Demo Spot).
        origin = resolver.resolve("2025-04-10", "RWD", "Demo Spot")
        assert origin.acquisition_method is AcquisitionMethod.REWARD, (
            f"resolver path: reward row must resolve via resolver; got {origin.acquisition_method}"
        )
        # Airdrop row.
        origin = resolver.resolve("2025-04-11", "ADR", "Demo Spot")
        assert origin.acquisition_method is AcquisitionMethod.AIRDROP, (
            f"resolver path: airdrop row must resolve via resolver; got {origin.acquisition_method}"
        )
        # LP provision row.
        origin = resolver.resolve("2025-04-12", "LPT", "Demo Spot")
        assert origin.acquisition_method is AcquisitionMethod.LIQUIDITY_PROVISION, (
            f"resolver path: LP row must resolve via resolver; got {origin.acquisition_method}"
        )
