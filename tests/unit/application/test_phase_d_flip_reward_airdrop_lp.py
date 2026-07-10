"""Phase D Task 7 - REWARD_AIRDROP_LP flip: token_origin inline-literal bypass.

Pins the per-treatment flip wiring for ``REWARD_AIRDROP_LP``: when
``jurisdiction.treatment_reward_airdrop_lp_via_resolver`` is True, the
inline tag-literal identification in
``token_origin.py::TokenOriginResolver._index_row`` (the reward /
airdrop / liquidity branches that read the raw ``Tag`` literal) is NOT
consulted; identification comes from ``resolve_treatment`` over the
pre-built ``list[Transaction]`` (built ONCE in Task 3's wiring step and
passed through ``TokenOriginResolver``'s entry point).

Co-opportunistic scope (plan NOTE, line 874): this task also extracts
the inline reward / airdrop / lp tag literals in ``token_origin.py`` to
module-level constants named ``_DEFAULT_REWARD_TAGS``,
``_DEFAULT_AIRDROP_TAGS``, ``_DEFAULT_LP_TAGS`` (mirroring the existing
resolver-side names in ``treatment_resolver.py:70,73,76``). The
extraction is a task-internal scope check, NOT a Phase D correctness
gate.

Invariant 4 tension (resolved): ``treatment_resolver.py`` is on the
frozen list ("CR guard: reject any edit to ...
src/tax_reporting/application/crypto/treatment_resolver.py"). The plan
clause "Remove the duplicated definitions from treatment_resolver.py:70,
73, 76 and import them from token_origin.py instead" would directly
violate Invariant 4. Per the task instructions' CRITICAL note, the
Invariant-4-safe interpretation is: extract the duplicates in
``token_origin.py`` to module-level constants with the SAME names, but
do NOT modify the resolver-side definitions. The "single source of
truth" intent is documented; the resolver frozen state takes precedence.

r8 Medium #1 carry-forward: the flag-on identification path consumes
the ``transactions: list[Transaction]`` built ONCE in Task 3's wiring
step; this task does NOT re-build ``Transaction`` objects internally.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tax_reporting.application import token_origin as token_origin_mod
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
from tax_reporting.domain.token_origin import AcquisitionMethod
from tax_reporting.domain.transaction import Transaction
from tax_reporting.domain.treatment import Treatment
from tax_reporting.infrastructure.koinly_parser import (
    normalize_platform_name,
    parse_th_row,
    read_koinly_rows,
)

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


@pytest.mark.unit
class TestPhaseDFlipRewardAirdropLp:
    """Pin the REWARD_AIRDROP_LP flip wiring on the token_origin inline literals."""

    def test_inline_literals_extracted_to_constants(self) -> None:
        """Module-level constants exist with the exact resolver-side names.

        Pins the co-opportunistic extraction (plan Task 7 NOTE): the
        reward / airdrop / lp tag literals in ``token_origin.py`` are
        extracted to module-level constants named
        ``_DEFAULT_REWARD_TAGS``, ``_DEFAULT_AIRDROP_TAGS``,
        ``_DEFAULT_LP_TAGS`` (mirroring the resolver-side names in
        ``treatment_resolver.py:70,73,76`` so there is ONE naming scheme).

        Invariant 4 tension: the plan also asks to remove the
        resolver-side definitions, but ``treatment_resolver.py`` is on
        the frozen list. Per the task instructions' CRITICAL note, this
        test asserts ONLY the token_origin-side extraction; the
        resolver-side definitions remain frozen.
        """
        assert hasattr(token_origin_mod, "_DEFAULT_REWARD_TAGS"), (
            "token_origin.py must define _DEFAULT_REWARD_TAGS"
        )
        assert hasattr(token_origin_mod, "_DEFAULT_AIRDROP_TAGS"), (
            "token_origin.py must define _DEFAULT_AIRDROP_TAGS"
        )
        assert hasattr(token_origin_mod, "_DEFAULT_LP_TAGS"), (
            "token_origin.py must define _DEFAULT_LP_TAGS"
        )
        # Pin the exact values (no silent drift vs. the inline literals
        # the branches used pre-extraction).
        reward = token_origin_mod._DEFAULT_REWARD_TAGS
        airdrop = token_origin_mod._DEFAULT_AIRDROP_TAGS
        lp = token_origin_mod._DEFAULT_LP_TAGS
        assert set(reward) == {"reward", "cashback", "realized gain"}, (
            f"_DEFAULT_REWARD_TAGS drifted: {set(reward)!r}"
        )
        assert set(airdrop) == {"airdrop"}, (
            f"_DEFAULT_AIRDROP_TAGS drifted: {set(airdrop)!r}"
        )
        assert set(lp) == {"liquidity in", "liquidity out"}, (
            f"_DEFAULT_LP_TAGS drifted: {set(lp)!r}"
        )

    def test_resolver_identifies_reward_airdrop_lp(self, tmp_path: Path) -> None:
        """Tag=Reward and Tag=Airdrop rows resolve to REWARD_AIRDROP_LP.

        Pins the identification source (Phase B resolver) for the two
        corpus rows the REWARD_AIRDROP_LP flip gates on. Under the
        default ``TreatmentConfig``, both ``Tag="Reward"`` and
        ``Tag="Airdrop"`` resolve to ``Treatment.REWARD_AIRDROP_LP``
        (Phase B Invariant 6 - reward / airdrop / lp tag sets all route
        to REWARD_AIRDROP_LP).
        """
        transactions = _build_transactions_from_th(_write_reward_th(tmp_path))
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

    def test_inline_literals_skipped_when_flag_on(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Flag on: token_origin inline reward/airdrop/lp literals are NOT consulted.

        When ``treatment_reward_airdrop_lp_via_resolver=True``, the
        reward / airdrop / lp branches in ``_index_row`` delegate to
        ``resolve_treatment`` over the pre-built ``transactions`` list;
        the inline tag-literal checks (``tag in ("reward", "cashback",
        "realized gain")`` etc.) MUST NOT be consulted.

        Discriminating assertion: monkeypatch the module-level constants
        ``_DEFAULT_REWARD_TAGS`` / ``_DEFAULT_AIRDROP_TAGS`` /
        ``_DEFAULT_LP_TAGS`` to EMPTY sets so the inline check would
        match nothing. Under flag-on, the resolver path still produces
        the correct ``AcquisitionMethod`` (REWARD / AIRDROP /
        LIQUIDITY_PROVISION) because it does not consult these sets -
        it consults ``TreatmentConfig``. The test fails if the
        implementation falls through to the inline literals.
        """
        th_path = _write_reward_th(tmp_path)
        transactions = _build_transactions_from_th(th_path)
        config = TreatmentConfig()

        # Empty the token_origin-side tag sets so the inline literal
        # branches match nothing. Under flag-on, identification MUST
        # still succeed via the resolver + TreatmentConfig.
        monkeypatch.setattr(token_origin_mod, "_DEFAULT_REWARD_TAGS", frozenset())
        monkeypatch.setattr(token_origin_mod, "_DEFAULT_AIRDROP_TAGS", frozenset())
        monkeypatch.setattr(token_origin_mod, "_DEFAULT_LP_TAGS", frozenset())

        from tax_reporting.application.token_origin import TokenOriginResolver

        resolver = TokenOriginResolver(
            th_path,
            transactions=transactions,
            config=config,
            via_resolver=True,
        )
        # The reward row (2025-04-10, RWD, Demo Spot) must resolve to
        # AcquisitionMethod.REWARD despite the emptied inline sets.
        origin = resolver.resolve("2025-04-10", "RWD", "Demo Spot")
        assert origin.acquisition_method is AcquisitionMethod.REWARD, (
            f"flag-on: reward row must resolve via resolver; got {origin.acquisition_method}"
        )
        # Airdrop row.
        origin = resolver.resolve("2025-04-11", "ADR", "Demo Spot")
        assert origin.acquisition_method is AcquisitionMethod.AIRDROP, (
            f"flag-on: airdrop row must resolve via resolver; got {origin.acquisition_method}"
        )
        # LP provision row.
        origin = resolver.resolve("2025-04-12", "LPT", "Demo Spot")
        assert origin.acquisition_method is AcquisitionMethod.LIQUIDITY_PROVISION, (
            f"flag-on: LP row must resolve via resolver; got {origin.acquisition_method}"
        )

    def test_inline_literals_run_when_flag_off(
        self,
        tmp_path: Path,
    ) -> None:
        """Flag off: legacy inline-literal identification runs exactly as today.

        When ``treatment_reward_airdrop_lp_via_resolver=False`` (or the
        kwargs are absent for backward compat), the legacy inline-literal
        branches in ``_index_row`` run unchanged. Pins Invariant 1
        (bypass, not deletion) - the legacy path remains reachable when
        the flag is off.
        """
        th_path = _write_reward_th(tmp_path)

        from tax_reporting.application.token_origin import TokenOriginResolver

        # Backward-compat: no kwargs -> legacy path (default via_resolver=False).
        resolver = TokenOriginResolver(th_path)
        origin = resolver.resolve("2025-04-10", "RWD", "Demo Spot")
        assert origin.acquisition_method is AcquisitionMethod.REWARD, (
            f"flag-off (default): reward row must resolve via inline literals; "
            f"got {origin.acquisition_method}"
        )
        origin = resolver.resolve("2025-04-11", "ADR", "Demo Spot")
        assert origin.acquisition_method is AcquisitionMethod.AIRDROP, (
            f"flag-off (default): airdrop row must resolve via inline literals; "
            f"got {origin.acquisition_method}"
        )
        origin = resolver.resolve("2025-04-12", "LPT", "Demo Spot")
        assert origin.acquisition_method is AcquisitionMethod.LIQUIDITY_PROVISION, (
            f"flag-off (default): LP row must resolve via inline literals; "
            f"got {origin.acquisition_method}"
        )

        # Explicit flag-off path: same behavior.
        resolver_off = TokenOriginResolver(
            th_path,
            transactions=[],
            config=TreatmentConfig(),
            via_resolver=False,
        )
        origin = resolver_off.resolve("2025-04-10", "RWD", "Demo Spot")
        assert origin.acquisition_method is AcquisitionMethod.REWARD, (
            f"flag-off (explicit): reward row must resolve via inline literals; "
            f"got {origin.acquisition_method}"
        )
