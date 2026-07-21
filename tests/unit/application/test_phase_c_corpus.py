"""Phase C corpus characterization tests.

Loads each of the six committed synthetic Koinly scenario directories under
``resources/source/example/2025/koinly/<scenario>/`` and asserts the
sanctioned Phase A + Phase B chain produces a stable ``Treatment`` member
and a stable ``TxCorrelationKey`` per TH row. The tests are
verification-only: no production code is changed by this module or by the
fixtures it loads.

Sanctioned chain per row (the order named by the plan's Terms):

    parse_th_row -> aggregate_platform_evidence -> classify_platform ->
    build_transaction -> {TxCorrelationKeyResolver.resolve,
    resolve_treatment}

The corpus-side ``_StubRegistry`` substitutes for the production
operator-origin registry binding (CEX vs DEX kind), which Phase A deferred
to a later task. Without the stub, a single ``crypto_withdrawal`` row
votes ``on_chain`` regardless of platform name, so Kraken/Wirex would
resolve to DEX and trip ``requires_review=True``, contradicting Phase A's
CEX-silent policy. The stub mirrors the registry contract
(``classify(platform) -> WalletKind | None``) for the six platform labels
the corpus uses.

Legacy-intent helper
--------------------

``_legacy_intent`` is a corpus-side replica of the per-treatment legacy
classification that the pre-Phase-B pipeline would have assigned to a TH
row. Phase E deleted the production constants that formerly lived in
``payment_proceeds.py`` (``_DEFAULT_PAYMENT_TAGS``) and
``crypto_fifo/contexts.py`` (``_LOAN_PRINCIPAL_TAGS``); the replicas
below are inlined from the values those constants held at Phase D landing
(matching ``TreatmentConfig`` defaults). ``TreatmentConfig.payment_tags``
is the authoritative surviving source for the payment set. The
derivatives JSON is loaded via ``_load_derivatives_labels_config`` (kept
in Phase E; it populates ``TreatmentConfig.derivatives_tags``). The
reward/airdrop/lp tag literals from ``token_origin.py`` existed only as
inline string literals and were deleted by Task 5; the replicas stay
inlined here.

Plan: ``docs/history/plans/2026-07-07-th-tx-view-phase-c.md`` (Task 7).
RFC: ``docs/history/context/2026-06-20-th-anchored-transaction-state-machine.md``.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from tax_reporting.application.crypto.derivatives_filter import _load_derivatives_labels_config
from tax_reporting.application.crypto.transaction_factory import build_transaction
from tax_reporting.application.crypto.treatment_resolver import TreatmentConfig, resolve_treatment
from tax_reporting.application.crypto.tx_correlation_key_resolver import TxCorrelationKeyResolver
from tax_reporting.application.crypto.wallet_kind import (
    WalletKind,
    aggregate_platform_evidence,
    classify_platform,
)
from tax_reporting.domain.transaction import Transaction, TxCorrelationKey
from tax_reporting.domain.treatment import Treatment
from tax_reporting.infrastructure.koinly_parser import parse_th_row, read_koinly_rows
from tests.conftest import build_origin_resolver

# Phase E Task 4 deleted ``_LOAN_PRINCIPAL_TAGS`` from ``crypto_fifo.contexts``;
# ``TreatmentConfig.loan_repayment_tags`` is the surviving authoritative source.
# The borrowing-side ``"loan"`` tag is NOT in the repayment default (Phase B
# Invariant 9: principal creation is not a repayment disposal), but the
# corpus helper includes it because ``discover_loan_affected_assets`` still
# needs it to keep borrow-only assets in the FIFO rebuild (Invariant 11).
_TREATMENT_CONFIG = TreatmentConfig()
_LOAN_REPAYMENT_TAGS: frozenset[str] = _TREATMENT_CONFIG.loan_repayment_tags
_LOAN_PRINCIPAL_TAGS: frozenset[str] = _LOAN_REPAYMENT_TAGS | frozenset({"loan"})

# ---------------------------------------------------------------------------
# Corpus scenario inventory
# ---------------------------------------------------------------------------

_SCENARIOS: tuple[str, ...] = (
    "multi_lot_ogr",
    "payment_ogr_collision",
    "summer_time_drift",
    "dex_cex_tx_id_absence",
    "loan_affected_rebuild",
    "derivatives_close",
)

_EXAMPLE_ROOT = Path("resources/source/example/2025/koinly")

# Reward / airdrop / lp tag sets: read once at import time from
# ``TreatmentConfig`` defaults. Post-Phase-E the resolver reads the same
# source, so these reads check resolver self-consistency under default config
# rather than drift detection (Phase C Invariant 5 in its original pre-Phase-E
# form is obsolete). Phase E Task 5 deleted the legacy
# ``_DEFAULT_REWARD_TAGS`` / ``_DEFAULT_AIRDROP_TAGS`` / ``_DEFAULT_LP_TAGS``
# constants from ``token_origin.py``; ``TreatmentConfig`` is now the single
# source of truth.
_REWARD_TAGS: frozenset[str] = _TREATMENT_CONFIG.reward_tags
_AIRDROP_TAGS: frozenset[str] = _TREATMENT_CONFIG.airdrop_tags
_LP_TAGS: frozenset[str] = _TREATMENT_CONFIG.lp_tags

# Phase E Task 3 deleted ``_DEFAULT_PAYMENT_TAGS`` from ``payment_proceeds.py``;
# ``TreatmentConfig.payment_tags`` is the surviving authoritative source. The
# helper reads it once at import time so a drift in the default is visible.
_PAYMENT_TAGS: frozenset[str] = _TREATMENT_CONFIG.payment_tags


def _scenario_dir(scenario: str) -> Path:
    """Return the committed synthetic fixture directory for ``scenario``."""
    return _EXAMPLE_ROOT / scenario


def _th_csv(scenario: str) -> Path:
    """Return the Transaction History CSV path for ``scenario``.

    Per CLAUDE.md, Koinly TH files use the ``*transaction_history*.csv``
    filename token. The committed scenario fixtures follow the
    ``koinly_2025_transaction_history.csv`` naming convention.
    """
    return _scenario_dir(scenario) / "koinly_2025_transaction_history.csv"


class _StubRegistry:
    """Corpus-side substitute for the production operator registry binding.

    Phase A defers the production registry wiring to a later task; the
    corpus tests cannot rely on the auto-discovery path alone because a
    single ``crypto_withdrawal`` row votes ``on_chain`` regardless of
    platform name (see ``wallet_kind.py::_vote``), so without the stub both
    Kraken and Wirex would resolve to DEX and ``requires_review`` would
    fire for CEX rows with empty ``TxHash``, contradicting Phase A's
    CEX-silent policy.

    The stub implements the ``RegistrySnapshot`` Protocol from
    ``wallet_kind.py``: ``classify(platform) -> WalletKind | None``.
    """

    _CEX = {"Kraken", "ByBit", "Wirex"}
    _DEX = {"Ledger Berachain (BERA)", "SUI", "Ledger"}

    def classify(self, platform: str) -> WalletKind | None:
        """Return the stub's WalletKind for ``platform`` or None if unmapped."""
        if platform in self._CEX:
            return WalletKind.CEX
        if platform in self._DEX:
            return WalletKind.DEX
        return None


def _row_platform(transaction_history_row: object) -> str | None:
    """Mirror ``wallet_kind.py::_row_platform`` for per-row classification.

    The sanctioned factory chain attributes a row to one platform by
    preferring the sending wallet and falling back to the receiving wallet,
    SKIPPING the literal string ``"Unknown"`` (which is what
    ``normalize_platform_name`` produces for an empty value). This helper
    replicates that rule so the corpus tests attribute platforms identically
    to the production evidence aggregator.

    A ``crypto_deposit`` row (e.g. the borrowing-side ``Tag="Loan"`` row in
    ``2025/koinly/loan_affected_rebuild/``) has a blank sending side, so its
    platform signal is the receiving wallet; without the ``"Unknown"``
    skip the row would attribute to ``"Unknown"`` and the stub would return
    None, classifying the row as UNKNOWN instead of the production CEX.
    """
    sending = getattr(transaction_history_row, "sending_wallet", "") or ""
    sending = sending.strip()
    if sending and sending.lower() != "unknown":
        return sending
    receiving = getattr(transaction_history_row, "receiving_wallet", "") or ""
    receiving = receiving.strip()
    if receiving and receiving.lower() != "unknown":
        return receiving
    return None


def _build_transactions(scenario: str) -> list[Transaction]:
    """Run the sanctioned Phase A chain over every TH row in ``scenario``.

    Steps per row: ``parse_th_row -> aggregate_platform_evidence ->
    classify_platform (with _StubRegistry) -> build_transaction``. Returns
    one ``Transaction`` per TH row, in source order.
    """
    rows = read_koinly_rows(_th_csv(scenario))
    parsed = [parse_th_row(row, row_index=index) for index, row in enumerate(rows)]
    evidence = aggregate_platform_evidence(parsed)
    registry = _StubRegistry()
    transactions: list[Transaction] = []
    for row in parsed:
        platform = _row_platform(row)
        classification = classify_platform(platform, evidence.get(platform) if platform else None, registry)
        transactions.append(build_transaction(row, classification))
    return transactions


def _legacy_intent(transaction: Transaction, derivatives_tags: frozenset[str]) -> Treatment:
    """Replicate the per-treatment legacy classifier outcome for one row.

    Tag sets are read from ``TreatmentConfig`` defaults at module load time
    (same source the resolver reads). Post-Phase-E there is no longer a
    parallel definition to drift against, so this helper checks resolver
    self-consistency under default config rather than drift detection
    (Phase C Invariant 5 in its original pre-Phase-E form is obsolete).

    Applies Phase B Invariant 6 precedence
    (``LOAN_REPAYMENT > PAYMENT > DERIVATIVES_CLOSE > REWARD_AIRDROP_LP >
    SPOT_DISPOSAL default > OTHER``). Default for disposal-shaped rows
    (sending side populated) with no special tag is ``SPOT_DISPOSAL``;
    non-disposal rows default to ``OTHER``.
    """
    normalized_tag = (transaction.row.tag or "").strip().lower()
    normalized_derivatives = frozenset(t.strip().lower() for t in derivatives_tags)

    # Phase B Invariant 6 precedence (highest first).
    if normalized_tag and normalized_tag in _LOAN_REPAYMENT_TAGS:
        return Treatment.LOAN_REPAYMENT
    if normalized_tag and normalized_tag in _PAYMENT_TAGS:
        return Treatment.PAYMENT
    if normalized_tag and normalized_tag in normalized_derivatives:
        return Treatment.DERIVATIVES_CLOSE
    if normalized_tag and (
        normalized_tag in _REWARD_TAGS or normalized_tag in _AIRDROP_TAGS or normalized_tag in _LP_TAGS
    ):
        return Treatment.REWARD_AIRDROP_LP

    if transaction.row.sending_currency is not None:
        return Treatment.SPOT_DISPOSAL
    return Treatment.OTHER


def _scenario_row_count(scenario: str) -> int:
    """Return the TH row count for ``scenario`` via the production reader."""
    return len(read_koinly_rows(_th_csv(scenario)))


def _derivatives_config(scenario: str) -> TreatmentConfig:
    """Return the TreatmentConfig for ``scenario``.

    The derivatives scenario injects the full production JSON-loaded
    frozenset so the corpus exercises every tag in the labels file
    (Phase C Monitor: derivatives labels JSON may grow). All other
    scenarios use the default config (empty ``derivatives_tags``).
    """
    if scenario == "derivatives_close":
        return TreatmentConfig(derivatives_tags=_load_derivatives_labels_config("koinly", 2025))
    return TreatmentConfig()


def _scenario_row_ids() -> list[tuple[str, int]]:
    """Return the (scenario, row_index) cross-product for parametrized tests."""
    ids: list[tuple[str, int]] = []
    for scenario in _SCENARIOS:
        for index in range(_scenario_row_count(scenario)):
            ids.append((scenario, index))
    return ids


class TestPhaseCCorpus:
    """Corpus characterization tests for the six Phase C scenarios."""

    @pytest.mark.parametrize("scenario", _SCENARIOS)
    def test_corpus_scenario(self, scenario: str) -> None:
        """Every TH row in ``scenario`` parses, classifies, builds, and resolves.

        Asserts each row produces a ``Treatment`` member (no ``None``, no
        exception) under the sanctioned Phase A + Phase B chain. The
        derivatives scenario injects the production JSON-loaded
        ``derivatives_tags``; all other scenarios use the default config.
        """
        transactions = _build_transactions(scenario)
        assert transactions, f"scenario {scenario!r} produced zero transactions"
        config = _derivatives_config(scenario)
        for transaction in transactions:
            treatment = resolve_treatment(transaction, config)
            assert isinstance(treatment, Treatment)
            assert treatment is not None

    @pytest.mark.parametrize(("scenario", "row_index"), _scenario_row_ids())
    def test_treatment_agrees_with_legacy_intent(self, scenario: str, row_index: int) -> None:
        """Per row: ``resolve_treatment`` agrees with the inline legacy intent.

        Phase C Invariant 6: the comparison is row-by-row, not aggregate.
        The legacy intent is computed by ``_legacy_intent``, which uses
        the inline replicas of the pre-Phase-E tag constants plus the
        injected derivatives JSON (Phase E deleted the production constants
        in ``payment_proceeds.py`` / ``crypto_fifo/contexts.py`` /
        ``token_origin.py``; the replicas preserve the values for this
        cross-check).
        """
        transactions = _build_transactions(scenario)
        assert row_index < len(transactions), (
            f"row_index {row_index} out of range for scenario {scenario!r} (have {len(transactions)} rows)"
        )
        transaction = transactions[row_index]
        config = _derivatives_config(scenario)
        resolver_treatment = resolve_treatment(transaction, config)
        legacy_intent = _legacy_intent(transaction, config.derivatives_tags)
        assert resolver_treatment == legacy_intent, (
            f"scenario={scenario!r} row_index={row_index} "
            f"tag={transaction.row.tag!r} type={transaction.row.type!r}: "
            f"resolver={resolver_treatment.value!r} legacy={legacy_intent.value!r}"
        )

    def test_loan_borrowing_row_is_other(self) -> None:
        """The ``Tag="Loan"`` borrowing row resolves to ``OTHER``.

        Phase B Invariant 9: the borrowing-side ``"loan"`` tag is principal
        creation (collateral deposit), NOT a repayment disposal. Only
        ``"loan repayment"`` matches the DP-001 non-taxable scope
        (CIRS art. 10(20)). The ``crypto_deposit`` row has no sending side,
        so it is non-disposal-shaped and defaults to ``OTHER``.
        """
        transactions = _build_transactions("loan_affected_rebuild")
        borrowing_rows = [tx for tx in transactions if (tx.row.tag or "").strip().lower() == "loan"]
        assert borrowing_rows, "expected one Tag='Loan' borrowing row in loan_affected_rebuild"
        assert len(borrowing_rows) == 1, "expected exactly one Tag='Loan' borrowing row"
        treatment = resolve_treatment(borrowing_rows[0], TreatmentConfig())
        assert treatment is Treatment.OTHER

    def test_loan_repayment_row_is_loan_repayment(self) -> None:
        """The ``Tag="Loan Repayment"`` row resolves to ``LOAN_REPAYMENT``.

        Phase B Invariant 6 precedence and DP-001: the ``"loan repayment"``
        tag wins over the disposal-shaped default, routing the disposal to
        the non-taxable loan-repayment scope.
        """
        transactions = _build_transactions("loan_affected_rebuild")
        repayment_rows = [tx for tx in transactions if (tx.row.tag or "").strip().lower() == "loan repayment"]
        assert repayment_rows, "expected one Tag='Loan Repayment' row in loan_affected_rebuild"
        assert len(repayment_rows) == 1, "expected exactly one Tag='Loan Repayment' row"
        treatment = resolve_treatment(repayment_rows[0], TreatmentConfig())
        assert treatment is Treatment.LOAN_REPAYMENT

    def test_derivatives_scenario_requires_injected_tags(self) -> None:
        """The ``Tag="Realized gain"`` row exercises Phase B Invariant 6 overlap.

        Under the default empty ``derivatives_tags``, the ``"realized gain"``
        tag matches the ``reward_tags`` default (``TreatmentConfig().reward_tags``,
        which includes ``"realized gain"``) and resolves to
        ``REWARD_AIRDROP_LP``. Under the injected JSON-loaded
        ``derivatives_tags``, the derivatives branch fires FIRST (precedence)
        and the row resolves to ``DERIVATIVES_CLOSE``. This pins the
        precedence discriminator at the production-overlap tag.
        """
        transactions = _build_transactions("derivatives_close")
        realized_gain_rows = [tx for tx in transactions if (tx.row.tag or "").strip().lower() == "realized gain"]
        assert realized_gain_rows, "expected one Tag='Realized gain' row in derivatives_close"
        assert len(realized_gain_rows) == 1, "expected exactly one Tag='Realized gain' row"
        row = realized_gain_rows[0]

        default_treatment = resolve_treatment(row, TreatmentConfig())
        assert default_treatment is Treatment.REWARD_AIRDROP_LP, (
            f"under default config, Tag='Realized gain' must resolve to "
            f"REWARD_AIRDROP_LP (got {default_treatment.value!r})"
        )

        injected_config = TreatmentConfig(derivatives_tags=_load_derivatives_labels_config("koinly", 2025))
        injected_treatment = resolve_treatment(row, injected_config)
        assert injected_treatment is Treatment.DERIVATIVES_CLOSE, (
            f"under injected derivatives_tags, Tag='Realized gain' must resolve "
            f"to DERIVATIVES_CLOSE (got {injected_treatment.value!r})"
        )

    def test_dex_missing_tx_id_sets_review_flag(self) -> None:
        """A DEX row with empty ``TxHash`` raises ``requires_review=True``.

        Phase A policy: DEX wallets SHOULD carry ``TxHash``; a missing
        tx-id is a data-quality oddity the correlation-key resolver
        surfaces loudly via the review flag. The Ledger Berachain (BERA)
        DEX row in ``2025/koinly/dex_cex_tx_id_absence/`` has an empty
        ``TxHash``.
        """
        transactions = _build_transactions("dex_cex_tx_id_absence")
        dex_rows = [tx for tx in transactions if tx.wallet_kind is WalletKind.DEX]
        assert dex_rows, "expected at least one DEX row in dex_cex_tx_id_absence"
        # The Ledger Berachain (BERA) row is the DEX row in this scenario.
        dex_row = dex_rows[0]
        assert dex_row.row.tx_hash is None, "expected the DEX row to have an empty TxHash (parsed to None)"
        _key, requires_review = TxCorrelationKeyResolver.resolve(dex_row)
        assert requires_review is True

    def test_cex_missing_tx_id_no_review_flag(self) -> None:
        """A CEX row with empty ``TxHash`` does NOT raise ``requires_review``.

        Phase A policy: CEX wallets routinely omit ``TxHash`` for internal
        movements; missing tx-id is expected and silent. The Kraken CEX
        row in ``2025/koinly/dex_cex_tx_id_absence/`` has an empty
        ``TxHash`` and must NOT trip the review flag.
        """
        transactions = _build_transactions("dex_cex_tx_id_absence")
        cex_rows = [tx for tx in transactions if tx.wallet_kind is WalletKind.CEX]
        assert cex_rows, "expected at least one CEX row in dex_cex_tx_id_absence"
        cex_row = cex_rows[0]
        assert cex_row.row.tx_hash is None, "expected the CEX row to have an empty TxHash (parsed to None)"
        _key, requires_review = TxCorrelationKeyResolver.resolve(cex_row)
        assert requires_review is False

    def test_summer_time_drift_uses_utc_instant(self) -> None:
        """The TH composite key and the localized CG instant agree on UTC.

        The ``2025/koinly/summer_time_drift/`` TH row encodes a
        ``2025-07-14 23:30:00 UTC`` disposal (which is ``2025-07-15 00:30
        WEST`` in mainland-Portugal summer time). The legacy local-date
        key would use ``2025-07-15``; the new path's composite key MUST
        anchor on the UTC instant ``2025-07-14T23:30:00Z``.

        This test pins BOTH halves of the timezone fix:

        (a) TH-side: the composite key embeds ``2025-07-14T23:30:00Z``
            (NOT ``2025-07-15``).
        (b) CG-side: the CG row's naive ``Date Sold = 15/07/2025 00:30``
            is localized to ``Europe/Lisbon`` by invoking the PRODUCTION
            CG-date parsing call site
            ``crypto_reporting.py::_parse_capital_gains_file`` (line 557:
            ``disposal_dt = parse_koinly_datetime(row.get("Date Sold", ""),
            zone=context.zone)``). The entry's ``disposal_timestamp``
            (formatted from the localized UTC instant) MUST equal the TH
            composite instant so the cross-report join sees a single UTC
            instant.

        REGRESSION CAUGHT: assertion (b) invokes
        ``_parse_capital_gains_file`` with ``context.zone =
            ZoneInfo("Europe/Lisbon")`` and therefore fails under a
        regression that reverts the ``zone=context.zone`` kwarg on the
        production CG-date parsing call (the regression would produce
        ``disposal_timestamp = "2025-07-15 00:30"`` instead of
        ``"2025-07-14 23:30"``). Without assertion (b) the test would
        still pass for any TH row whose parser round-trips the UTC
        literal, masking the drift it is named for (Family H: verify the
        real thing, not the abstraction). The CG-side half is the side
        the RFC weakness #3 fix actually lives on.
        """
        transactions = _build_transactions("summer_time_drift")
        assert len(transactions) == 1, "expected exactly one TH row in summer_time_drift"
        key, _requires_review = TxCorrelationKeyResolver.resolve(transactions[0])
        expected_utc = datetime(2025, 7, 14, 23, 30, 0, tzinfo=UTC)
        assert key.composite.utc_instant == expected_utc, (
            f"composite.utc_instant={key.composite.utc_instant!r} expected={expected_utc!r}"
        )

        # CG-side: invoke the PRODUCTION CG parser
        # (``_parse_capital_gains_file``) on the committed fixture, with a
        # ``CapitalGainsParsingContext`` whose ``zone`` matches the
        # production PT jurisdiction (``Europe/Lisbon``). Production call
        # site: crypto_reporting.py::_parse_capital_gains_file line 557:
        # `disposal_dt = parse_koinly_datetime(row.get("Date Sold", ""), zone=context.zone)`.
        # The entry's ``disposal_timestamp`` is formatted from the localized
        # UTC instant, so a ``zone=`` revert would produce "2025-07-15 00:30"
        # and fail the assertion below.
        from tax_reporting.application.crypto_reporting import (
            CapitalGainsParsingContext,
            _parse_capital_gains_file,
        )

        cg_path = _scenario_dir("summer_time_drift") / "koinly_2025_capital_gains_report.csv"
        context = CapitalGainsParsingContext(
            skipped_assets={},
            origin_resolver=build_origin_resolver(None),
            review_entries=[],
            zone=ZoneInfo("Europe/Lisbon"),
        )
        entries, _raw_loan_fallback = _parse_capital_gains_file(cg_path, context)
        assert len(entries) == 1, "expected exactly one CG entry in summer_time_drift"
        cg_entry = entries[0]
        assert cg_entry.disposal_timestamp == "2025-07-14 23:30", (
            f"CG disposal_timestamp={cg_entry.disposal_timestamp!r}; expected "
            f"'2025-07-14 23:30' (the TH composite UTC instant). A regression "
            f"that reverts `zone=context.zone` on the production CG-date parsing "
            f"call would yield '2025-07-15 00:30'."
        )

    def test_multi_lot_ogr_one_event_many_lots(self) -> None:
        """Pin the TH-side identity: one TH row -> one tx-id-anchored key.

        The ``2025/koinly/multi_lot_ogr/`` TH row's legacy key
        ``(2025-03-10, ETH, Kraken)`` joins to TWO CG lots in the CG
        report, but the TH row's ``TxCorrelationKey`` is one stable
        Transaction identity anchored on the TH ``TxHash``. The key's
        ``tx_id`` MUST be populated from the TH ``TxHash``
        (``synth-txhash-multilot-001``); the composite carries the row
        identity.

        SCOPE: this test pins ONLY the TH-side identity (single TH row
        resolves to one stable tx-id-anchored key regardless of the CG
        lot count on the same legacy key). The CG-to-TH join multiplicity
        (proving the new typed path correctly collapses the two CG lots
        onto this one key, instead of duplicating the OGR override across
        them) is Phase D work; the join logic does not exist in this
        diff. The structural property pinned here - that the TH row has
        ONE stable key when the underlying legacy key collides with two
        CG lots - is the precondition Phase D needs before flipping the
        OGR override; without it the multi-lot scenario only verifies
        ``SPOT_DISPOSAL == SPOT_DISPOSAL``, which is trivially true.
        """
        transactions = _build_transactions("multi_lot_ogr")
        assert len(transactions) == 1, "expected exactly one TH row in multi_lot_ogr"
        transaction = transactions[0]

        # Fixture shape sanity: the CG report for this scenario has TWO
        # lots on the same legacy key. This is a fixture-shape check; it
        # does NOT prove the new path joins both lots onto the key below
        # (that join is Phase D work, not implemented in this diff).
        cg_rows = read_koinly_rows(_scenario_dir("multi_lot_ogr") / "koinly_2025_capital_gains_report.csv")
        assert len(cg_rows) == 2, f"expected 2 CG lots in multi_lot_ogr, found {len(cg_rows)}; scenario shape drifted"

        key, _requires_review = TxCorrelationKeyResolver.resolve(transaction)
        assert isinstance(key, TxCorrelationKey)
        # tx_id is sourced from the TH TxHash (Invariant 2 + 11); never
        # from tx_src / tx_dest. Pinned: the TH row resolves to ONE
        # tx-id-anchored identity regardless of how many CG lots share
        # the same legacy key.
        assert key.tx_id == "synth-txhash-multilot-001", f"key.tx_id={key.tx_id!r}; expected the TH TxHash value"
        # The composite anchors on the UTC instant, asset, wallet, amount,
        # and row_index; it is one identity per TH row.
        assert key.composite.asset == "ETH"
        assert key.composite.wallet == "Kraken"
        assert key.composite.row_index == 0

    def test_no_real_data_in_fixtures(self) -> None:
        """No fixture CSV line matches the real-data regex.

        Phase C Invariant 4 (synthetic-data floor): no real wallet
        addresses (``0x`` + 40+ hex) and no real tx hashes (64 hex chars).
        The synthetic identifiers ``synth-txhash-<scenario>-001`` and the
        empty ``TxHash`` values both pass this regex by construction; this
        is the established convention from Tasks 1-6.
        """
        pattern = re.compile(r"(0x[0-9a-fA-F]{40,})|([0-9a-fA-F]{64})")
        offenders: list[str] = []
        for scenario in _SCENARIOS:
            for csv_path in sorted(_scenario_dir(scenario).glob("*.csv")):
                content = csv_path.read_text(encoding="utf-8-sig")
                match = pattern.search(content)
                if match:
                    offenders.append(f"{csv_path}: {match.group()!r}")
        assert not offenders, "Invariant 4 violation - real-data-like patterns found: " + ", ".join(offenders)
