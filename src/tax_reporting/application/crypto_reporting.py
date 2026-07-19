"""Crypto tax reporting helpers for Koinly exports."""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from ..domain.exceptions import ConfigurationError, FileProcessingError
from ..domain.transaction import Transaction
from ..domain.treatment import Treatment
from ..infrastructure.config import (
    DEFAULT_ZERO_BASIS_REVIEW_MIN_PROCEEDS,
    DEFAULT_ZERO_BASIS_REVIEW_THRESHOLD,
    ConversionRate,
    TaxJurisdictionConfig,
)
from ..infrastructure.koinly_parser import (
    _find_and_parse_other_gains_file,
    _find_report_path,
    contains_non_latin_characters,
    format_datetime,
    normalize_asset_ticker,
    normalize_platform_name,
    parse_koinly_datetime,
    parse_koinly_decimal,
    parse_th_row,
    read_koinly_rows,
)
from .crypto.aggregation import (
    _aggregate_capital_entries,
    _filter_immaterial_entries,
    aggregate_derivatives_entries,
)
from .crypto.chain_derivation import _derive_chain
from .crypto.classification import (
    _classify_reward_tax_status,
    _contains_popular_token,
    _get_all_fiat_currency_codes,
    _get_popular_crypto_tokens,
    _load_popular_crypto_tokens,  # noqa: F401
)
from .crypto.constants import ZERO
from .crypto.derivatives_filter import (
    _load_derivatives_labels_config,
    apply_derivatives_dedup,
)
from .crypto.entities import (
    AggregatedRewardIncomeEntry,  # noqa: F401
    CapitalGainPeriodStats,  # noqa: F401
    CryptoCapitalGainEntry,
    CryptoCapitalGainStats,
    CryptoCompletePdfSummary,  # noqa: F401
    CryptoReconciliationSummary,
    CryptoReviewEntry,
    CryptoRewardIncomeEntry,
    CryptoSkippedZeroValueToken,
    CryptoTaxReport,
    DerivativesPnLEntry,
    HoldingsSnapshot,
    LoanActivityEntry,  # noqa: F401
    OperatorOrigin,  # noqa: F401
    RewardTaxClassification,
)
from .crypto.fee_filter import flag_fee_suspects, remove_transaction_fees
from .crypto.fifo_helpers import (
    _build_zero_basis_review_reason,
    _rebuild_fifo_for_loan_affected_assets,
)
from .crypto.loan_activity import _extract_loan_activity
from .crypto.ogr_event_level import apply_ogr_event_level
from .crypto.ogr_handler import (
    _build_ogr_index,  # noqa: F401
    _split_ogr_index,
    _validate_capital_entries_have_valid_countries,
)
from .crypto.operator_origin import resolve_operator_origin
from .crypto.parsing import (
    _extract_tax_year,
    _parse_complete_tax_report_pdf,
    _register_skipped_zero_asset,
)
from .crypto.payment_proceeds import (
    _derive_peg_to_eur_rates,
    _get_payment_proceeds_config,
    correct_payment_proceeds,
)
from .crypto.transaction_factory import build_transaction
from .crypto.treatment_resolver import TreatmentConfig, resolve_treatment
from .crypto.validation import (
    _is_temporally_valid,  # noqa: F401
    _parse_transaction_date,  # noqa: F401
)
from .crypto.wallet_kind import aggregate_platform_evidence, classify_platform
from .crypto.wallet_kind_registry import ProductionWalletKindRegistry
from .crypto_fifo import (
    discover_loan_affected_assets,
)
from .token_origin import TokenOriginResolver

# Koinly internal accounting units for fee accrual. These are never assets the
# user holds, buys, or sells; rows for them are tracking entries Koinly emits
# to record fee accrual, with Cost=Proceeds=Gain=0.0. Skipped at parse time.
# Add new tokens here ONLY after verifying they are Koinly-internal (not real
# tradeable assets); the set-contents test (TestKoinlyTrackingTokensSet) will
# fail until updated.
_KOINLY_TRACKING_TOKENS: frozenset[str] = frozenset({"FEE"})


def build_transactions_from_th(
    transaction_history_path: Path,
    *,
    skip_logger: logging.Logger | None = None,
) -> list[Transaction]:
    """Build the ``list[Transaction]`` for a Koinly TH CSV via the sanctioned pipeline.

    Single source of truth for the parse -> classify -> build chain used by
    both this module's ``load_koinly_crypto_report`` and the test helper
    ``conftest.build_origin_resolver``. Family D (single source of truth):
    previously the chain was duplicated verbatim across the two call sites,
    which created a drift hazard every time the parse-skip policy,
    wallet-precedence rule, or classification plumbing changed.

    Defensive parse: malformed rows (``ValueError`` from ``parse_th_row``) are
    skipped per-row so a single bad row does not abort Transaction
    construction for the rest of the file (Family G data-loss observability).
    When ``skip_logger`` is supplied, each skip is logged at WARNING with the
    row index and the underlying error; when ``None`` (test path), skips are
    silent.

    Wallet attribution per row: ``sending_wallet`` when non-empty and not
    ``"unknown"`` (case-insensitive), else ``receiving_wallet``. Mirrors
    ``_row_platform`` in ``wallet_kind.py``.

    Args:
        transaction_history_path: Path to a Koinly transaction_history CSV.
        skip_logger: Optional logger for WARNING on per-row parse skips.
            Production supplies ``logging.getLogger(__name__)``; tests pass
            ``None`` for silent skips.

    Returns:
        ``list[Transaction]`` with one entry per TH row that parsed cleanly.
        Order matches ``read_koinly_rows`` enumeration order, which is the
        row-index contract the rest of the pipeline depends on.
    """
    raw_rows = list(read_koinly_rows(transaction_history_path))
    parsed: list = []
    for index, raw in enumerate(raw_rows):
        try:
            parsed.append(parse_th_row(raw, row_index=index))
        except ValueError as parse_exc:
            if skip_logger is not None:
                skip_logger.warning(
                    "Skipping TH row %d during Transaction construction: %s. "
                    "The row will not participate in resolver-based treatment filters.",
                    index,
                    parse_exc,
                )
    evidence = aggregate_platform_evidence(parsed)
    registry = ProductionWalletKindRegistry()
    transactions: list[Transaction] = []
    for row in parsed:
        sending = row.sending_wallet.strip()
        platform_raw = (
            sending
            if sending and sending.lower() != "unknown"
            else row.receiving_wallet.strip()
        )
        platform = normalize_platform_name(platform_raw) if platform_raw else ""
        classification = classify_platform(
            platform,
            evidence.get(platform) if platform else None,
            registry,
        )
        transactions.append(build_transaction(row, classification))
    return transactions


def load_koinly_crypto_report(  # noqa: PLR0912, PLR0915
    koinly_dir: Path,
    jurisdiction: TaxJurisdictionConfig | None = None,
    rates: list[ConversionRate] | None = None,
) -> CryptoTaxReport | None:
    """Load Koinly exports from a directory and normalize for tax reporting.

    Args:
        koinly_dir: Directory containing Koinly CSV exports (capital gains, income,
            and optionally transaction history reports).
        jurisdiction: Optional tax jurisdiction config.  When provided and
            ``exclude_loan_repayment_gains`` is True, the FIFO rebuild path is
            activated for loan-affected assets. When ``infer_payment_proceeds``
            is True, zero-proceeds Payment disposals are corrected from the TH
            Net Value / stablecoin pegs (DP-014).
        rates: Optional currency conversion rates (``Config.rates``). Threaded
            ONLY for the non-EUR-pegged stablecoin fallback of the
            payment-proceeds correction, which reuses the same ``[EXCHANGE RATES]``
            source shares/dividends use to derive the year-end peg->EUR rate.
            ``None`` (default) is backward-compatible and routes non-EUR-pegged
            stablecoins without a config rate to the review-flag fallback.

    Returns:
        A populated ``CryptoTaxReport`` on success, or ``None`` when the directory
        does not exist, contains no recognised report files, or the transaction
        history required for FIFO rebuild is absent.
    """
    if not koinly_dir.exists() or not koinly_dir.is_dir():
        return None

    capital_file = _find_report_path(koinly_dir, "capital_gains_report", ".csv")
    income_file = _find_report_path(koinly_dir, "income_report", ".csv")
    transaction_history_file = _find_report_path(koinly_dir, "transaction_history", ".csv")

    _required = {
        "capital_gains_report (Capital gains report)": capital_file,
        "income_report (Income report)": income_file,
        "transaction_history (Transaction history)": transaction_history_file,
    }
    _present = {name for name, f in _required.items() if f is not None}
    _missing = {name for name, f in _required.items() if f is None}

    if not _present:
        # No Koinly exports at all: crypto reporting is simply not available for this run.
        return None

    if _missing:
        raise FileProcessingError(
            f"Incomplete Koinly export in {koinly_dir}: {len(_missing)} of 3 required files are missing. "
            f"Missing: {sorted(_missing)}. "
            f"Present: {sorted(_present)}. "
            "Export all three required reports from Koinly (Capital gains report, Income report, "
            "Transaction history) and place them in the same directory."
        )

    year = _extract_tax_year(koinly_dir, capital_file, income_file, jurisdiction=jurisdiction)
    # Jurisdiction zone, resolved once and reused by every naive-date parser (CG/OGR/Income).
    zone = jurisdiction.timezone if jurisdiction else None
    skipped_assets: dict[tuple[str, str], dict] = {}
    review_entries: list[CryptoReviewEntry] = []

    # ---- Phase D: SINGLE production Transaction-construction site (post-Phase D).
    # r8 Medium #1: ``load_koinly_crypto_report`` is the ONLY production caller of
    # the Phase A sanctioned ``build_transaction(row, classification)`` factory.
    # Tasks 4/5/6/7 consume this same ``transactions`` list (Family D
    # single-source-of-truth); NONE of them constructs ``Transaction`` objects
    # internally. Phase E Task 6: the resolver gate is gone; construction is
    # unconditional whenever a ``transaction_history_file`` was located (which
    # the three-file presence guard above guarantees). The resolver path does
    # not require a ``jurisdiction``; it requires only the TH rows and a
    # ``TreatmentConfig``. Cost: thin factory + O(1) ``classify_platform`` per
    # row; bounded by TH row count.
    transactions: list[Transaction] = []
    # Degrade to empty derivatives_tags only when derivatives reporting is OFF
    # (gate: ``TaxJurisdictionConfig.derivatives_dedup_enabled``). When ON, a
    # malformed labels JSON is a ConfigurationError so the run fails loudly;
    # silent degradation here would double-count derivatives disposals across
    # OGR + capital gains.
    derivatives_reporting_off = (
        jurisdiction is None or not jurisdiction.derivatives_dedup_enabled
    )
    try:
        derivatives_tags = _load_derivatives_labels_config("koinly", year)
    except FileProcessingError as exc:
        if derivatives_reporting_off:
            logging.getLogger(__name__).warning(
                "Derivatives labels JSON for koinly year %d is malformed (%s); "
                "continuing with empty derivatives_tags (derivatives reporting "
                "is off).",
                year,
                exc,
            )
            derivatives_tags = frozenset()
        else:
            raise ConfigurationError(
                f"Derivatives labels JSON for koinly year {year} is malformed and "
                f"derivatives reporting is ON (separate_derivatives_reporting AND "
                f"use_other_gains_report). Fix the labels file and re-run. Cause: {exc}"
            ) from exc
    treatment_config = TreatmentConfig(derivatives_tags=derivatives_tags)
    # Single source of truth: ``build_transactions_from_th`` is the sanctioned
    # parse -> classify -> build pipeline shared with the test helpers in
    # ``conftest.build_origin_resolver`` (Family D). Malformed rows are skipped
    # per-row with a WARNING so a single bad row does not abort construction
    # for the rest of the file (Family G data-loss observability).
    transactions.extend(
        build_transactions_from_th(
            transaction_history_file,
            skip_logger=logging.getLogger(__name__),
        )
    )

    # Phase E Task 6: ``TokenOriginResolver`` requires both ``transactions``
    # and ``config``. Construction is now unconditional, so ``treatment_config``
    # is always a real ``TreatmentConfig`` (never ``None``) whenever a
    # ``transaction_history_file`` was located, regardless of jurisdiction.
    origin_resolver = TokenOriginResolver(
        transaction_history_file,
        transactions=transactions,
        config=treatment_config,
    )

    # Collect known asset tickers from both files BEFORE parsing
    # This allows zero-value entries for known tokens to be flagged for review
    known_assets = _collect_known_asset_tickers(capital_file, income_file)

    # FIFO rebuild for loan-affected assets when PT gate is active
    _fifo_logger = logging.getLogger(__name__)
    fifo_rebuild_active = jurisdiction is not None and jurisdiction.exclude_loan_repayment_gains

    loan_affected_assets: frozenset[str] = frozenset()
    if fifo_rebuild_active:
        # Phase E Task 4/6: the ``via_resolver`` flag and the ``_loan_config``
        # fallback are gone. ``fifo_rebuild_active`` requires
        # ``jurisdiction is not None``. Phase E Task 6 made ``treatment_config``
        # and ``transactions`` unconditional, so both are always populated when
        # this branch runs.
        loan_affected_assets = discover_loan_affected_assets(
            fiat_currency_codes=_get_all_fiat_currency_codes(),
            transactions=transactions,
            config=treatment_config,
        )
        if not loan_affected_assets:
            _fifo_logger.warning(
                "FIFO rebuild active (jurisdiction=%s) but no loan-affected assets discovered. "
                "This may indicate missing or incorrect 'loan'/'loan repayment' tags in Koinly. "
                "Verify your Koinly transaction history has the expected loan tags.",
                jurisdiction.country if jurisdiction else "unknown",
            )

    if capital_file:
        # When jurisdiction is None, the min_proceeds fallback uses the production
        # default (10 EUR), which gates zero-cost entries below that floor out of
        # the review flag. Callers that want prior flag-everything semantics must
        # construct a TaxJurisdictionConfig with zero_basis_review_min_proceeds=Decimal("0").
        capital_entries, raw_loan_fallback = _parse_capital_gains_file(
            capital_file,
            CapitalGainsParsingContext(
                skipped_assets=skipped_assets,
                origin_resolver=origin_resolver,
                review_entries=review_entries,
                known_assets=known_assets,
                loan_affected_assets=loan_affected_assets,
                zero_basis_review_min_proceeds=(
                    jurisdiction.zero_basis_review_min_proceeds
                    if jurisdiction
                    else DEFAULT_ZERO_BASIS_REVIEW_MIN_PROCEEDS
                ),
                zone=zone,
            ),
        )
    else:
        capital_entries = []
        raw_loan_fallback = []

    if fifo_rebuild_active and loan_affected_assets:
        fifo_entries: list[CryptoCapitalGainEntry] = []
        th_assets: frozenset[str] = frozenset()
        try:
            fifo_entries, th_assets = _rebuild_fifo_for_loan_affected_assets(
                transaction_history_file, origin_resolver, loan_affected_assets, fiscal_year=year,
                zero_basis_review_min_proceeds=(
                    jurisdiction.zero_basis_review_min_proceeds
                    if jurisdiction
                    else DEFAULT_ZERO_BASIS_REVIEW_MIN_PROCEEDS
                ),
            )
            capital_entries.extend(fifo_entries)
            assets_with_fifo = {e.asset for e in fifo_entries}
            for asset in loan_affected_assets & th_assets:
                if asset not in assets_with_fifo:
                    _fifo_logger.warning(
                        "FIFO rebuild: %s has zero FIFO entries after rebuild; "
                        "capital gains for this asset will be missing",
                        asset,
                    )
        except (FileProcessingError, ValueError) as fifo_exc:
            _fifo_logger.error(
                "FIFO rebuild failed for loan-affected assets %s: %s. "
                "Falling back to raw Koinly CG rows for these assets. Capital gains may include "
                "loan repayment disposals. Fix the Transaction History file and re-run.",
                sorted(loan_affected_assets),
                fifo_exc,
            )
            capital_entries.extend(raw_loan_fallback)

    reward_entries = (
        _parse_income_file(
            income_file, skipped_assets, known_assets, zone=zone
        )
        if income_file
        else []
    )

    capital_entries = _validate_capital_entries_have_valid_countries(capital_entries, jurisdiction)

    # Derivatives CG dedup must run after validation and before OGR split so
    # the classifier sees the filtered list (Design Invariant 2, 3).
    # Phase E: identification always delegates to the resolver over the
    # pre-built ``transactions`` list (built ONCE upstream); the Phase-D
    # ``via_resolver`` flag and the legacy standalone CSV scanner are gone.
    # ``treatment_config`` is unconditionally populated upstream (Phase E Task 6).
    capital_entries = apply_derivatives_dedup(
        capital_entries=capital_entries,
        jurisdiction=jurisdiction,
        transaction_history_file=transaction_history_file,
        transactions=transactions,
        config=treatment_config,
    )

    # DP-015 fee removal runs EARLY, after derivatives dedup and BEFORE the
    # OGR/payment-proceeds/aggregation steps (Design Invariant 4,
    # Option D pipeline: dedup -> fee_removal -> OGR ->
    # payment_proceeds -> fee_suspect_flagging -> aggregation -> materiality).
    # Removed fee lots must NOT be summed/aggregated (they are not taxable
    # alienacoes onerosas under PT CIRS Art. 10(1)(k)). Fee classification is
    # year-agnostic, so no ``year`` argument is threaded. Suspect events
    # captured here are consumed by the late ``flag_fee_suspects`` pass below.
    capital_entries, suspect_events = remove_transaction_fees(
        capital_entries=capital_entries,
        transaction_history_file=transaction_history_file,
        jurisdiction=jurisdiction,
    )

    # CRITICAL: OGR split + override must happen BEFORE _aggregate_capital_entries
    # because CG rows are individual FIFO lots that get summed in aggregation.
    # OGR contains the correct total gain/loss for the disposal event.
    # Overriding after aggregation would lose the lot-level trail.
    # The split runs post-FIFO/post-validation so the classifier sees rebuilt lots.
    # derivatives_entries is initialized BEFORE the gate so it is in scope for the
    # later aggregation step regardless of whether OGR processing ran.
    infer_payment_proceeds_active = (
        jurisdiction is not None and jurisdiction.infer_payment_proceeds
    )

    derivatives_entries: list[DerivativesPnLEntry] = []
    if jurisdiction and jurisdiction.use_other_gains_report:
        ogr_rows = _find_and_parse_other_gains_file(
            koinly_dir, zone=zone
        )
        if ogr_rows:
            spot_index, derivatives_entries = _split_ogr_index(
                ogr_rows, capital_entries, jurisdiction
            )
            if spot_index:
                logging.getLogger(__name__).info(
                    "Applying OGR directional authority: %d entries in spot_index",
                    len(spot_index),
                )
            # Phase E Task 6: gate the OGR override on the resolver identifying
            # each TH row as SPOT_DISPOSAL. ``spot_disposal_keys`` is the set of
            # ``(date, asset, wallet)`` keys whose TH rows resolve to
            # SPOT_DISPOSAL; ``apply_ogr_event_level`` treats any spot_index
            # key NOT in this set as "no match" so non-SPOT_DISPOSAL disposal
            # events (e.g. PAYMENT rows sharing an OGR key) are NOT overridden
            # (r7 Medium #6). The Phase D per-treatment flag is gone;
            # identification is resolver-only.
            spot_disposal_keys: set[tuple[str, str, str]] = set()
            for tx in transactions:
                if resolve_treatment(tx, treatment_config) is Treatment.SPOT_DISPOSAL:
                    _sending = tx.row.sending_wallet.strip()
                    _wallet_raw = (
                        _sending
                        if _sending and _sending.lower() != "unknown"
                        else tx.row.receiving_wallet.strip()
                    )
                    _wallet = (
                        normalize_platform_name(_wallet_raw) if _wallet_raw else ""
                    )
                    if tx.row.sending_currency is not None:
                        spot_disposal_keys.add(
                            (
                                tx.row.utc_instant.strftime("%Y-%m-%d"),
                                normalize_asset_ticker(tx.row.sending_currency),
                                _wallet,
                            )
                        )
            capital_entries = apply_ogr_event_level(
                capital_entries,
                spot_index,
                jurisdiction,
                spot_disposal_keys=spot_disposal_keys,
            )

    # Payment-proceeds correction (DP-014): correct zero-proceeds Payment
    # disposals using the TH Net Value / stablecoin pegs. Runs AFTER the OGR
    # override so the resolver-keyed SPOT_DISPOSAL identification has already
    # excluded Payment rows from OGR mutation, and BEFORE _aggregate_capital_entries
    # so corrected lots aggregate
    # by (date, asset, platform, holding_period). Guarded by the jurisdiction
    # flag; transaction_history_file is guaranteed non-None after the three-file
    # presence guard above. Corrected entries intentionally SKIP re-validation and
    # derivatives dedup (safe: the original proceeds==0 entry already passed
    # validation; payments are spot disposals; country inherited unchanged) and
    # flow into aggregation + the materiality filter.
    #
    # Identification comes from the Phase B resolver (the caller passes the
    # set of PAYMENT-treatment TH rows). r8 Medium #1: filter the pre-built
    # ``transactions: list[Transaction]`` (built ONCE in the Task 3 wiring
    # step) by ``resolve_treatment == Treatment.PAYMENT`` and project to raw
    # TH-row dicts via the row_index correspondence. Do NOT re-build
    # ``Transaction`` objects inside this branch; the raw row re-read is
    # O(file size) and is the same shape ``_build_th_index`` consumes.
    if infer_payment_proceeds_active:
        pp_config = _get_payment_proceeds_config()
        peg_to_eur_rates = _derive_peg_to_eur_rates(rates or [], pp_config.stablecoin_pegs)
        _all_th_rows = read_koinly_rows(transaction_history_file)
        _payment_row_indices = {
            tx.row.row_index
            for tx in transactions
            if resolve_treatment(tx, treatment_config) is Treatment.PAYMENT
        }
        payment_th_rows = [
            row
            for index, row in enumerate(_all_th_rows)
            if index in _payment_row_indices
        ]
        capital_entries = correct_payment_proceeds(
            capital_entries,
            payment_th_rows,
            config=pp_config,
            peg_to_eur_rates=peg_to_eur_rates,
            loan_affected_assets=loan_affected_assets,
            review_entries=review_entries,
        )

    # DP-015 fee suspect flagging runs LATE, after payment-proceeds and BEFORE
    # aggregation (Design Invariant 4, Option D). This ensures any proceeds
    # corrections / OGR overrides are already complete when we flag suspects,
    # preventing payment-proceeds zero-basis overwrites from clobbering the
    # fee-suspect flags or leaving obsolete parse-time zero-proceeds reasons.
    # Aggregation then propagates the lot-level ``review_required`` flag into
    # the aggregated entry via ``any()`` (aggregation.py:300).
    capital_entries = flag_fee_suspects(
        capital_entries=capital_entries,
        suspect_events=suspect_events,
        review_entries=review_entries,
    )

    capital_entries = _aggregate_capital_entries(capital_entries)
    pre_filter_count = len(capital_entries)
    capital_entries = _filter_immaterial_entries(capital_entries)
    dropped = pre_filter_count - len(capital_entries)
    if dropped > 0:
        logging.getLogger(__name__).warning(
            "Filtered %d sub-1-EUR capital gain entries (PT-C-028); %d entries retained",
            dropped,
            len(capital_entries),
        )

    # Derivatives aggregation runs AFTER capital aggregation: the two streams
    # are independent (capital groups by (date, asset, platform, holding_period);
    # derivatives group by (date, asset, platform, event_type)). Capital pipeline
    # is the existing tested path; running derivatives after keeps it uninterrupted.
    # Derivatives bypass _filter_immaterial_entries: art. 10(1)(e) has no
    # materiality carve-out, every EUR of derivative P&L must be reported.
    derivatives_entries = aggregate_derivatives_entries(derivatives_entries)

    opening = _parse_holdings_file(
        _find_report_path(koinly_dir, "beginning_of_year_holdings_report", ".csv"),
        "holdings_opening",
        skipped_assets,
    )
    closing = _parse_holdings_file(
        _find_report_path(koinly_dir, "end_of_year_holdings_report", ".csv"),
        "holdings_closing",
        skipped_assets,
    )

    # startswith on "short"/"long" is load-bearing: actual values are "Short term"/"Long term"
    # (space-separated, not hyphenated). Tightening to == "short" would silently break matching.
    period_counts = Counter(row.holding_period.lower() for row in capital_entries)
    short_term_rows = sum(c for k, c in period_counts.items() if k.startswith("short"))
    long_term_rows = sum(c for k, c in period_counts.items() if k.startswith("long"))
    mixed_rows = period_counts.get("mixed", 0)
    unknown_rows = period_counts.get("unknown", 0)

    _recon_logger = logging.getLogger(__name__)
    categorised = short_term_rows + long_term_rows + mixed_rows + unknown_rows
    if categorised != len(capital_entries):
        unclassified = [
            row.holding_period
            for row in capital_entries
            if not row.holding_period.lower().startswith(("short", "long"))
            and row.holding_period.lower() not in ("mixed", "unknown")
        ]
        _recon_logger.warning(
            "Reconciliation mismatch: %d capital entries but only %d categorised by holding period. "
            "Unrecognised holding_period values: %s",
            len(capital_entries),
            categorised,
            sorted(set(unclassified)),
        )

    reconciliation = CryptoReconciliationSummary(
        capital_rows=len(capital_entries),
        reward_rows=len(reward_entries),
        short_term_rows=short_term_rows,
        long_term_rows=long_term_rows,
        mixed_rows=mixed_rows,
        unknown_rows=unknown_rows,
        capital_cost_total_eur=sum((row.cost_eur for row in capital_entries), start=ZERO),
        capital_proceeds_total_eur=sum((row.proceeds_eur for row in capital_entries), start=ZERO),
        capital_gain_total_eur=sum((row.gain_loss_eur for row in capital_entries), start=ZERO),
        reward_total_eur=sum((row.value_eur for row in reward_entries), start=ZERO),
        opening_holdings=opening,
        closing_holdings=closing,
    )

    skipped_zero_value_tokens = [
        CryptoSkippedZeroValueToken(
            source_section=section,
            asset=asset,
            count=data["count"],
            suspicious=data["suspicious"],
        )
        for (section, asset), data in sorted(skipped_assets.items())
    ]

    complete_tax_report_file = _find_report_path(koinly_dir, "complete_tax_report", ".pdf")
    pdf_summary = _parse_complete_tax_report_pdf(complete_tax_report_file) if complete_tax_report_file else None

    capital_gain_stats = CryptoCapitalGainStats.from_entries(capital_entries)
    try:
        loan_activity = _extract_loan_activity(transaction_history_file)
    except (FileProcessingError, ValueError) as exc:
        _logger = logging.getLogger(__name__)
        _logger.warning(
            "Failed to extract loan activity from %s: %s. Continuing without loan data.",
            transaction_history_file,
            exc,
        )
        loan_activity = []

    return CryptoTaxReport(
        tax_year=year,
        capital_entries=capital_entries,
        reward_entries=reward_entries,
        reconciliation=reconciliation,
        capital_gain_stats=capital_gain_stats,
        skipped_zero_value_tokens=skipped_zero_value_tokens,
        loan_activity=loan_activity,
        fifo_rebuild_assets=loan_affected_assets,
        review_entries=review_entries,
        derivatives_entries=derivatives_entries,
        zero_basis_review_threshold=(
            jurisdiction.zero_basis_review_threshold
            if jurisdiction
            else DEFAULT_ZERO_BASIS_REVIEW_THRESHOLD
        ),
        pdf_summary=pdf_summary,
 )





@dataclass(frozen=True)
class CapitalGainsParsingContext:
    """Shared context for capital gains file parsing.

    Groups together the parsing state and dependencies needed by
    _parse_capital_gains_file to improve readability and testability.

    Attributes:
        skipped_assets: Counter for tracking skipped assets by section and ticker.
        origin_resolver: Token origin resolver for acquisition origin annotation.
        review_entries: List to collect review-required entries for the Excel sheet.
        known_assets: Set of asset tickers seen in non-zero rows across all files.
        loan_affected_assets: Set of asset tickers affected by loans (for FIFO rebuild).
        zero_basis_review_min_proceeds: Minimum proceeds (EUR) required to flag a
            zero-cost entry for review. Defaults to ZERO (preserve prior behavior).
        zone: Jurisdiction ``ZoneInfo`` used to localize naive CG dates (Date Sold,
            Date Acquired are mainland-Portugal local time) to a true-UTC instant so
            ``disposal_date`` / ``disposal_timestamp`` agree with TH explicit-UTC dates.
            ``None`` (default) preserves the legacy UTC-stamp behavior.
    """

    skipped_assets: dict[tuple[str, str], dict]
    origin_resolver: TokenOriginResolver
    review_entries: list[CryptoReviewEntry]
    known_assets: frozenset[str] | None = None
    loan_affected_assets: frozenset[str] = frozenset()
    zero_basis_review_min_proceeds: Decimal = ZERO
    zone: ZoneInfo | None = None


def _parse_capital_gains_file(  # noqa: PLR0912, PLR0915
    path: Path,
    context: CapitalGainsParsingContext,
) -> tuple[list[CryptoCapitalGainEntry], list[CryptoCapitalGainEntry]]:
    """Parse the Koinly capital gains report CSV.

    Returns a tuple of (normal_entries, raw_loan_fallback). normal_entries excludes
    rows for loan-affected assets; raw_loan_fallback contains those rows fully parsed
    with review_required=True. The caller should use raw_loan_fallback only when the
    FIFO rebuild fails, as a degraded-mode substitute for the FIFO-derived entries.

    Args:
        path: Path to the Koinly capital gains report CSV file.
        context: Parsing context with shared state and dependencies.

    Returns:
        Tuple of (normal_entries, raw_loan_fallback).
    """
    rows = read_koinly_rows(path)
    capital_entries: list[CryptoCapitalGainEntry] = []
    raw_loan_fallback: list[CryptoCapitalGainEntry] = []

    logger = logging.getLogger(__name__)
    skipped_loan_affected: Counter[str] = Counter()
    skipped_parse_errors: int = 0
    skipped_koinly_tracking: Counter[str] = Counter()

    for row_number, row in enumerate(rows, start=1):
        asset = normalize_asset_ticker(row.get("Asset", ""))
        is_loan_affected = asset in context.loan_affected_assets
        if is_loan_affected:
            skipped_loan_affected[asset] += 1
        try:
            cost_eur = parse_koinly_decimal(row.get("Cost (EUR)", ""))
            proceeds_eur = parse_koinly_decimal(row.get("Proceeds (EUR)", ""))
            gain_loss_eur = parse_koinly_decimal(row.get("Gain / loss", ""))
            amount = parse_koinly_decimal(row.get("Amount", ""))
            disposal_dt = parse_koinly_datetime(row.get("Date Sold", ""), zone=context.zone)
            disposal_date = format_datetime(disposal_dt)
            disposal_timestamp = disposal_dt.strftime("%Y-%m-%d %H:%M")
            acquisition_date = format_datetime(parse_koinly_datetime(row.get("Date Acquired", ""), zone=context.zone))
        except ValueError as exc:
            logger.warning("Skipping capital gains row %d for %r: ambiguous decimal value: %s", row_number, asset, exc)
            skipped_parse_errors += 1
            continue

        # Check for all-zero values (no taxable event)
        # For popular tokens, flag for review instead of skipping - likely Koinly data issue
        is_all_zero = cost_eur == ZERO and proceeds_eur == ZERO and gain_loss_eur == ZERO

        review_required: bool = False
        review_reason: str = ""
        wallet = row.get("Wallet Name", "").strip()
        platform = normalize_platform_name(wallet)

        if is_all_zero:
            # Koinly internal fee-accrual tracking entries (FEE, ...): never a
            # user-held asset. Short-circuit before the popular-token / non-Latin
            # lookups AND before _register_skipped_zero_asset so FEE does not
            # pollute the skipped-tokens table (Design Invariant 4, r3 Critical #2).
            if asset in _KOINLY_TRACKING_TOKENS:
                skipped_koinly_tracking[asset] += 1
                continue
            # Lookups moved INSIDE the block: only consumed here at the
            # is_known_token/known_assets check below and at the homoglyph-suffix
            # branch / CryptoReviewEntry / _register_skipped_zero_asset below.
            # The unconditional homoglyph check further down (after the block)
            # does its own contains_non_latin_characters call and does not read
            # is_suspicious, so this move is behaviour-preserving for non-all-zero
            # rows (r3 Critical #2).
            is_suspicious = contains_non_latin_characters(asset)
            is_known_token = asset in _get_popular_crypto_tokens() or _contains_popular_token(asset)
            if is_known_token or (context.known_assets and asset in context.known_assets):
                review_reason = "Zero EUR value for known crypto asset - likely Koinly tracking entry or data error"
                if is_suspicious:
                    review_reason = (
                        f"{review_reason}; Asset ticker contains non-Latin characters "
                        "- potential homoglyph scam token"
                    )

                context.review_entries.append(
                    CryptoReviewEntry(
                        source_section="capital_gains",
                        date=disposal_date,
                        asset=asset,
                        platform=platform,
                        review_reason=review_reason,
                        is_suspicious=is_suspicious,
                    )
                )
                logger.warning(
                    "Capital gains row %d for %r has all-zero values. Added to review list - "
                    "this may be a Koinly tracking entry or data error.",
                    row_number,
                    asset,
                )
                # Continue to create entry with review_required=True below for traceability
                review_required = True
            else:
                # Unknown token with all-zero values - skip entirely
                _register_skipped_zero_asset(context.skipped_assets, "capital_gains", asset, is_suspicious)
                continue
        operator_origin = resolve_operator_origin(
            platform,
            transaction_type="crypto_disposal",
            transaction_date=disposal_date,
        )
        notes = row.get("Notes", "").strip()
        missing_cost_with_impact = "missing cost basis" in notes.lower()
        review_required = review_required or operator_origin.review_required or missing_cost_with_impact

        review_reason = review_reason or operator_origin.review_reason
        if missing_cost_with_impact:
            cost_basis_reason = "Missing cost basis with tax impact - verify cost calculation"
            review_reason = f"{review_reason}; {cost_basis_reason}" if review_reason else cost_basis_reason

        review_required, review_reason = _build_zero_basis_review_reason(
            cost_eur, proceeds_eur, review_required, review_reason,
            min_proceeds=context.zero_basis_review_min_proceeds,
        )

        # Flag assets with non-Latin characters as potential scam tokens (homoglyph detection)
        if contains_non_latin_characters(asset):
            review_required = True
            scam_reason = f"Asset ticker '{asset}' contains non-Latin characters - potential homoglyph scam token"
            review_reason = f"{review_reason}; {scam_reason}" if review_reason else scam_reason

        holding_period = row.get("Holding period", "").strip() or "Unknown"
        annex_hint = "G1" if holding_period.lower().startswith("long") else "J"

        origin = context.origin_resolver.resolve(acquisition_date, asset, wallet, notes)
        token_origin_str = str(origin)

        entry = CryptoCapitalGainEntry(
            disposal_date=disposal_date,
            acquisition_date=acquisition_date,
            asset=asset,
            amount=amount,
            cost_eur=cost_eur,
            proceeds_eur=proceeds_eur,
            gain_loss_eur=gain_loss_eur,
            holding_period=holding_period,
            wallet=wallet,
            platform=platform,
            chain=_derive_chain(wallet),
            operator_origin=operator_origin,
            annex_hint=annex_hint,
            review_required=review_required,
            review_reason=review_reason,
            notes=notes,
            token_swap_history=token_origin_str,
            multi_acquisition_dates=False,
            disposal_timestamp=disposal_timestamp,
        )

        if is_loan_affected:
            # Buffer as fallback for when the FIFO rebuild fails.  These rows may
            # include loan repayment disposals and must not reach the report unless
            # the FIFO rebuild is unavailable.
            fallback_reason = (
                "Raw Koinly CG row for loan-affected asset: FIFO rebuild failed; "
                "may include loan repayment disposals. Fix Transaction History and re-run."
            )
            combined_reason = f"{review_reason}; {fallback_reason}" if review_reason else fallback_reason
            raw_loan_fallback.append(replace(entry, review_required=True, review_reason=combined_reason))
        else:
            capital_entries.append(entry)

    if skipped_loan_affected:
        skipped_summary = ", ".join(f"{asset}: {count}" for asset, count in sorted(skipped_loan_affected.items()))
        logger.warning(
            "FIFO rebuild active: buffered %d raw CG row(s) for loan-affected assets %s as FIFO fallback",
            sum(skipped_loan_affected.values()),
            skipped_summary,
        )

    if skipped_parse_errors:
        logger.warning(
            "Skipped %d capital gains row(s) due to ambiguous decimal values; "
            "these disposals are excluded from the report. Check the warnings above for details.",
            skipped_parse_errors,
        )

    if skipped_koinly_tracking:
        summary = ", ".join(f"{asset}={count}" for asset, count in sorted(skipped_koinly_tracking.items()))
        logger.info(
            "Skipped %d Koinly tracking entries (assets: %s)",
            sum(skipped_koinly_tracking.values()),
            summary,
        )

    return capital_entries, raw_loan_fallback


def _row_has_non_zero_value(row: dict[str, str]) -> bool:
    """Return True if the row carries a non-zero EUR value (proceeds for gains, value for income)."""
    value_field = "Proceeds (EUR)" if "Proceeds (EUR)" in row else "Value (EUR)"
    if value_field not in row:
        return False
    try:
        return parse_koinly_decimal(row.get(value_field, "")) > ZERO
    except ValueError:
        return False


def _collect_known_asset_tickers(
    capital_file: Path | None, income_file: Path | None
) -> frozenset[str]:
    """Scan Koinly files to collect all asset tickers from non-zero rows.

    Used to identify legitimate crypto assets that have zero-value rewards (likely Koinly data errors).
    Zero-value rewards for known assets are flagged for review instead of being skipped.

    Args:
        capital_file: Koinly capital gains CSV file path.
        income_file: Koinly income CSV file path.

    Returns:
        Frozenset of asset tickers that appear in non-zero rows across both files.

    Raises:
        FileProcessingError: If all provided files fail to parse, preventing silent degradation
            where zero-value rewards for legitimate assets would be incorrectly skipped.
    """
    known_assets: set[str] = set()
    files_to_scan = [f for f in [capital_file, income_file] if f is not None and f.exists()]
    scan_failures: list[tuple[Path, Exception]] = []

    for file_path in files_to_scan:
        try:
            rows = read_koinly_rows(file_path)
            for row in rows:
                asset = normalize_asset_ticker(row.get("Asset", ""))
                if not asset:
                    continue
                if _row_has_non_zero_value(row):
                    known_assets.add(asset)
        except Exception as e:
            scan_failures.append((file_path, e))

    # Fail fast if all provided files failed - silent degradation would skip legitimate zero-value rewards
    if files_to_scan and scan_failures and len(scan_failures) == len(files_to_scan):
        _scan_logger = logging.getLogger(__name__)
        file_list = ", ".join(str(f) for f, _ in scan_failures)
        errors = "; ".join(str(e) for _, e in scan_failures)
        _scan_logger.error(
            "All Koinly files failed to scan for known assets: %s. Errors: %s",
            file_list,
            errors,
        )
        raise FileProcessingError(
            f"Failed to scan all Koinly files for known assets: {file_list}. "
            f"Errors: {errors}. Zero-value rewards for legitimate assets may be incorrectly skipped. "
            "Check file format and content."
        )

    if scan_failures:
        _scan_logger = logging.getLogger(__name__)
        for file_path, error in scan_failures:
            _scan_logger.warning(
                "Failed to scan known assets from %s: %s. Continuing with partial results.",
                file_path,
                error,
            )

    return frozenset(known_assets)


def _parse_income_file(
    path: Path,
    skipped_assets: Counter[tuple[str, str]],
    known_assets: frozenset[str] | None = None,
    zone: ZoneInfo | None = None,
) -> list[CryptoRewardIncomeEntry]:
    rows = read_koinly_rows(path)
    reward_entries: list[CryptoRewardIncomeEntry] = []
    logger = logging.getLogger(__name__)

    for row_number, row in enumerate(rows, start=1):
        asset = normalize_asset_ticker(row.get("Asset", ""))
        try:
            value_eur = parse_koinly_decimal(row.get("Value (EUR)", ""))
            amount = parse_koinly_decimal(row.get("Amount", ""))
            date_str = format_datetime(parse_koinly_datetime(row.get("Date", ""), zone=zone))
        except ValueError as exc:
            logger.warning("Skipping income row %d for %r: ambiguous decimal value: %s", row_number, asset, exc)
            continue

        wallet = row.get("Wallet Name", "").strip()
        platform = normalize_platform_name(wallet)
        description = row.get("Description", "").strip()

        # Check for zero-value rewards
        if value_eur == ZERO:
            # Check if this is a known legitimate crypto asset with zero value (likely Koinly data error)
            # Uses both exact match and substring matching to catch variants like TSTON, TSUSDE
            is_known = (
                asset in _get_popular_crypto_tokens()
                or _contains_popular_token(asset)
                or (known_assets and asset in known_assets)
            )
            if is_known:
                # Flag for review instead of skipping: known assets shouldn't have zero value
                pass  # Continue to processing below with review flag set
            else:
                _register_skipped_zero_asset(skipped_assets, "income", asset, contains_non_latin_characters(asset))
                continue

        # Classify reward tax status based on asset type (CRG-001, CRG-002)
        # Must be done BEFORE operator origin resolution for platforms that split by fiat/crypto (e.g., Wirex)
        tax_classification = _classify_reward_tax_status(asset)

        # Determine transaction type for operator origin resolution based on asset classification
        # Platforms like Wirex have different operators for fiat vs crypto transactions
        if tax_classification == RewardTaxClassification.TAXABLE_NOW:
            transaction_type = "fiat_deposit"
        else:
            transaction_type = "crypto_deposit"

        operator_origin = resolve_operator_origin(
            platform, transaction_type=transaction_type, transaction_date=date_str
        )

        # Parse foreign tax if present in Koinly report (optional field)
        foreign_tax_eur = ZERO
        review_required = operator_origin.review_required
        review_reason = operator_origin.review_reason
        if "Tax (EUR)" in row or "Foreign Tax" in row:
            tax_field = row.get("Tax (EUR)", "") or row.get("Foreign Tax", "")
            try:
                foreign_tax_eur = parse_koinly_decimal(tax_field)
            except ValueError as exc:
                logger.warning(
                    "Row %d: Could not parse foreign tax for asset %r (value: %s EUR, field value: %r): %s. "
                    "Foreign tax credits will be omitted from this entry. Please verify the Koinly export.",
                    row_number,
                    asset,
                    value_eur,
                    tax_field or "(empty)",
                    exc,
                )
                review_required = True  # Flag for manual review since tax data was lost
                tax_parse_reason = "Foreign tax field could not be parsed - verify tax credit manually"
                review_reason = f"{review_reason}; {tax_parse_reason}" if review_reason else tax_parse_reason

        # Flag assets with non-Latin characters as potential scam tokens (homoglyph detection)
        if contains_non_latin_characters(asset):
            review_required = True
            scam_reason = f"Asset ticker '{asset}' contains non-Latin characters - potential homoglyph scam token"
            review_reason = f"{review_reason}; {scam_reason}" if review_reason else scam_reason

        # Flag zero-value rewards for known legitimate assets (likely Koinly data error)
        if value_eur == ZERO:
            is_known = (
                asset in _get_popular_crypto_tokens()
                or _contains_popular_token(asset)
                or (known_assets and asset in known_assets)
            )
            if is_known:
                review_required = True
                zero_value_reason = (
                    "Zero EUR value for known crypto asset - likely Koinly data error or missing price data"
                )
                review_reason = f"{review_reason}; {zero_value_reason}" if review_reason else zero_value_reason

        reward_entries.append(
            CryptoRewardIncomeEntry(
                date=date_str,
                asset=asset,
                amount=amount,
                value_eur=value_eur,
                income_label="Reward",
                source_type=row.get("Type", "").strip(),
                wallet=wallet,
                platform=platform,
                chain=_derive_chain(wallet),
                operator_origin=operator_origin,
                annex_hint="J",
                review_required=review_required,
                review_reason=review_reason,
                description=description,
                tax_classification=tax_classification,
                foreign_tax_eur=foreign_tax_eur,
            )
        )

    return reward_entries


def _parse_holdings_file(
    path: Path | None, source_section: str, skipped_assets: Counter[tuple[str, str]]
) -> HoldingsSnapshot | None:
    if path is None:
        return None

    rows = read_koinly_rows(path)
    logger = logging.getLogger(__name__)
    asset_rows = 0
    total_cost_eur = ZERO
    total_value_eur = ZERO

    for row in rows:
        asset = normalize_asset_ticker(row.get("Asset", ""))
        try:
            value_eur = parse_koinly_decimal(row.get("Value (EUR)", ""))
            cost_eur = parse_koinly_decimal(row.get("Cost (EUR)", ""))
        except ValueError as exc:
            logger.warning("Skipping holdings row for %r: ambiguous decimal value: %s", asset, exc)
            continue
        if value_eur == ZERO:
            _register_skipped_zero_asset(skipped_assets, source_section, asset, contains_non_latin_characters(asset))
            continue
        asset_rows += 1
        total_cost_eur += cost_eur
        total_value_eur += value_eur

    return HoldingsSnapshot(
        asset_rows=asset_rows,
        total_cost_eur=total_cost_eur,
        total_value_eur=total_value_eur,
    )

