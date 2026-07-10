"""Operator origin resolution for crypto tax reporting."""

from __future__ import annotations

import logging
import re
from dataclasses import replace

from ...domain.transaction import WalletKind
from .entities import OperatorOrigin
from .validation import _is_temporally_valid, _parse_transaction_date

# ---------------------------------------------------------------------------
# Platform -> WalletKind mapping (Phase D Task 1)
# ---------------------------------------------------------------------------
#
# Source of truth for the platform-level CEX/DEX signal. Keyed by the
# lowercase brand substring the entity-chain branch matches on (e.g.
# ``"kraken"``, ``"binance"``); the canonical ``platform`` string each
# branch sets on the returned ``OperatorOrigin`` (``"Kraken"``,
# ``"Binance"``) is the title-cased form of the same key. The lookup helper
# ``_kind_for_platform`` normalizes to lowercase so both the entity-chain
# canonical name and the raw brand substring resolve to the same kind.
#
# Binance=CEX per the operator-entity classification at the ``if "binance" in
# normalized:`` branch below: "Binance Spain, S.L." is a centralized exchange
# operator (a licensed fiat-facing custodian), so its WalletKind is CEX.
#
# DEX entries are on-chain protocols / foundations / self-custody wallets:
# berachain, starknet, zksync, solana, ton, ethereum, aptos, sui, arbitrum,
# mantle, polygon, base, filecoin, tonkeeper, plus "ledger" (hardware wallet
# self-custody - no operator entity; on-chain by definition).
#
# CEX entries are off-chain centralized exchanges: wirex, bybit, kraken,
# binance, gate.io.
#
# This table is the explicit kind signal per CLAUDE.md "never introduce a
# hardcoded value without first flagging it and asking the user". The user
# decision (2026-07-08, B2 option 1) is the flag-and-ask resolution that
# authorizes this mapping.
_PLATFORM_KIND: dict[str, WalletKind] = {
    # CEX (centralized exchanges - fiat-facing custodial operators)
    "wirex": WalletKind.CEX,
    "bybit": WalletKind.CEX,
    "kraken": WalletKind.CEX,
    "binance": WalletKind.CEX,
    "gate.io": WalletKind.CEX,
    # DEX (on-chain protocols / foundations / self-custody wallets)
    "berachain": WalletKind.DEX,
    "starknet": WalletKind.DEX,
    "zksync": WalletKind.DEX,
    "solana": WalletKind.DEX,
    "ton": WalletKind.DEX,
    "ethereum": WalletKind.DEX,
    "aptos": WalletKind.DEX,
    "sui": WalletKind.DEX,
    "arbitrum": WalletKind.DEX,
    "mantle": WalletKind.DEX,
    "polygon": WalletKind.DEX,
    "base": WalletKind.DEX,
    "filecoin": WalletKind.DEX,
    "tonkeeper": WalletKind.DEX,
    # Self-custody hardware/software wallets without an operator entity.
    # "ledger" has no entity-chain branch (chain_derivation.py strips the
    # prefix); it is on-chain by definition.
    "ledger": WalletKind.DEX,
}

# Known-exclusions: the entity-chain branches below also match on regex /
# conditional logic that the frozenset cannot mechanically encode. These are
# intentionally NOT in _KNOWN_PLATFORM_BRANDS:
#   - ``re.search(r"\bton\b", ...) and "tonkeeper" not in normalized``
#     (the bare "ton" branch is guarded by a tonkeeper exclusion; the brand
#     name "ton" IS in the set, the exclusion logic is not)
#   - ``re.search(r"\bbase\b", ...) and "coinbase" not in normalized``
#     (the bare "base" brand IS in the set; the coinbase exclusion is not)
#   - ``"gate.io" in normalized or normalized == "gate"``
#     (both substrings collapse to canonical "Gate.io"; brand "gate.io" plus
#     the normalized-equality form would require duplicate keys)
_KNOWN_PLATFORM_BRANDS: frozenset[str] = frozenset(
    {
        # Simple-substring match keys (branch head is ``if "<key>" in normalized``)
        "wirex",
        "bybit",
        "berachain",
        "ethereum",
        "aptos",
        "polygon",
        "filecoin",
        "binance",
        "kraken",
        # Regex-keyed brand names (branch head is ``re.search(...)``, possibly
        # with a word-boundary pattern). The frozenset holds the plain brand
        # name; word-boundary / exclusion logic is documented above.
        "ton",
        "sui",
        "mantle",
        "base",
        "arbitrum",
        "starknet",
        "zksync",
        "solana",
        "tonkeeper",
    }
)


def _kind_for_platform(platform: str) -> WalletKind | None:
    """Return the WalletKind for ``platform`` (canonical name or raw brand).

    Normalizes to lowercase so both the entity-chain canonical name (e.g.
    ``"Kraken"``, ``"BASE"``) and the lowercase brand substring resolve to
    the same kind.
    """
    return _PLATFORM_KIND.get(platform.lower())



def resolve_operator_origin(  # noqa: PLR0911, PLR0912
    platform: str,
    transaction_type: str | None = None,
    transaction_date: str | None = None,
) -> OperatorOrigin:
    """Resolve operator metadata from platform brand, transaction type, and optional transaction date.

    Source-country resolution hierarchy for DeFi:
    1. Interface legal entity (the exposed contracting party)
    2. Protocol / foundation / sponsoring legal entity
    3. Validator operator (when identifiable)

    IMPORTANT: This function NEVER defaults to the taxpayer's residence country.
    The source country must be derived from the paying entity / platform / protocol
    legal-entity domicile, not from where the taxpayer performed the activity.

    Temporal Validity:
    When transaction_date is provided, this function performs temporal validity checks
    against the mapping's service_start_date/valid_until dates. If a transaction predates
    service_start_date, a warning is logged and the earliest known mapping is returned
    (for historical data recovery scenarios).

    Args:
        platform: Wallet or platform name (e.g., "Ledger Berachain", "ByBit").
        transaction_type: Optional hint for service scope (e.g., "crypto_disposal", "fiat_deposit").
        transaction_date: Optional transaction date for historical mapping lookup.
            Accepts formats like "2025-03-15" or "2025-03-15 14:30:00".

    Returns:
        OperatorOrigin with the resolved operator entity and country.
        Returns operator_country="UNKNOWN" and review_required=True for unrecognized platforms.
    """
    logger = logging.getLogger(__name__)

    # Parse transaction date for temporal validity checks
    parsed_date: str | None = None
    date_parse_failed = False
    if transaction_date:
        try:
            parsed_date = _parse_transaction_date(transaction_date)
        # Only ValueError is expected from _parse_transaction_date (invalid format).
        # Other exceptions should propagate to surface unexpected errors. Fail-soft is intentional:
        # mark entry for review rather than crash the report.
        except ValueError:
            logger.error(
                "Invalid transaction_date format '%s' for platform '%s': "
                "temporal validity check skipped. Expected format: 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM:SS'. "
                "Marking for manual review to ensure correct tax reporting.",
                transaction_date,
                platform,
            )
            date_parse_failed = True

    normalized = platform.lower()
    transaction_type_normalized = (transaction_type or "").lower()

    def _return_with_temporal_check(origin: OperatorOrigin) -> OperatorOrigin:
        """Return operator origin after performing temporal validity check.

        Logs a warning if the transaction date is outside the mapping's validity period.
        When out of validity, returns a modified origin with review_required=True to
        surface the ambiguity in the workbook's manual-review flag.

        Also stamps ``origin.wallet_kind`` from ``_PLATFORM_KIND`` (Phase D Task 1).
        When a platform matched the entity chain but has NO ``_PLATFORM_KIND``
        entry, logs at warning level (data-loss at warning+, per CLAUDE.md) so a
        future addition forgotten in the mapping surfaces loudly (r7 Medium #7).

        Args:
            origin: The operator origin to validate.

        Returns:
            The origin, potentially with review_required=True if outside validity period
            or if date parsing failed.
        """
        # Stamp wallet_kind from _PLATFORM_KIND (Phase D Task 1). Warn when an
        # entity-chain-matched platform has no kind entry (r7 Medium #7 coverage
        # guard). The unknown-fallback branch is identified by its sentinel
        # operator_entity; it is expected to have no kind.
        kind = _kind_for_platform(origin.platform)
        if kind is None and origin.operator_entity != "UNKNOWN_OPERATOR_REVIEW_REQUIRED":
            logger.warning(
                "Platform '%s' matched the operator-origin entity chain but has "
                "no _PLATFORM_KIND entry; wallet_kind will be None. Add the "
                "platform to _PLATFORM_KIND in operator_origin.py to close the "
                "coverage gap (r7 Medium #7).",
                origin.platform,
            )
        stamped = replace(origin, wallet_kind=kind) if kind is not None else origin
        # If date parsing failed, mark for review to ensure correct tax reporting
        if date_parse_failed:
            reason = "Transaction date format could not be parsed; temporal validity check skipped"
            combined = f"{stamped.review_reason}; {reason}" if stamped.review_reason else reason
            return replace(
                stamped,
                review_required=True,
                review_reason=combined,
            )

        # Use service_start_date only for transaction matching (valid_from is for audit trail only)
        # When service_start_date is None, skip lower-bound check to avoid false positives
        # on long-running mappings that only have verification dates (e.g., Ethereum, Arbitrum)
        lower_bound = stamped.service_start_date
        is_valid = parsed_date is None or _is_temporally_valid(lower_bound, stamped.valid_until, parsed_date)
        if not is_valid:
            logger.warning(
                "Transaction date %s for platform '%s' (service_scope: %s) is outside "
                "the service period [%s, %s]. Marking for manual review. "
                "Please verify the operator origin is correct for this historical transaction.",
                parsed_date,
                stamped.platform,
                stamped.service_scope,
                lower_bound or "unknown",
                stamped.valid_until or "present",
            )
            # Return a modified origin with review_required=True to surface in the workbook
            reason = (
                f"Transaction date {parsed_date} is outside known service period "
                f"[{lower_bound or 'unknown'}, {stamped.valid_until or 'present'}] for {stamped.platform}"
            )
            combined = f"{stamped.review_reason}; {reason}" if stamped.review_reason else reason
            return replace(
                stamped,
                review_required=True,
                review_reason=combined,
            )

        return stamped

    if "wirex" in normalized:
        if transaction_type_normalized.startswith("fiat"):
            return _return_with_temporal_check(
                OperatorOrigin(
                    platform="Wirex",
                    service_scope="fiat",
                    operator_entity="Wirex Limited",
                    operator_country="GB",
                    source_url="https://wirexapp.com/legal",
                    source_checked_on="2026-03-08",
                    confidence="medium",
                    review_required=False,
                    service_start_date="2015-01-01",  # Approximate founding date (Wirex Ltd incorporated 2014)
                    valid_from="2026-03-08",  # GB/HR split-scope verification date (audit trail)
                )
            )
        return _return_with_temporal_check(
            OperatorOrigin(
                platform="Wirex",
                service_scope="crypto",
                operator_entity="Wirex Digital (crypto operator, verify account terms)",
                operator_country="HR",
                source_url="https://wirexapp.com/legal",
                source_checked_on="2026-03-08",
                confidence="medium",
                review_required=False,
                service_start_date="2015-01-01",  # Approximate founding date (Wirex Ltd incorporated 2014)
                valid_from="2026-03-08",  # GB/HR split-scope verification date (audit trail)
            )
        )

    if "bybit" in normalized:
        return _return_with_temporal_check(
            OperatorOrigin(
                platform="Bybit",
                service_scope="crypto",
                operator_entity="Bybit group entity (account-region specific)",
                operator_country="AE",
                source_url="https://www.bybit.com/en/legal/terms-of-service/terms-of-service",
                source_checked_on="2026-03-08",
                confidence="low",
                review_required=False,
                platform_assumption=(
                    "Bybit uses account-region specific entities; "
                    "verify your account region matches the operator entity"
                ),
                platform_review_required=True,
                valid_from=None,  # Historical operator, exact start date unknown
            )
        )

    if "berachain" in normalized:
        return _return_with_temporal_check(
            OperatorOrigin(
                platform="Berachain",
                service_scope="crypto",
                operator_entity="BERA Chain Foundation",
                operator_country="VG",
                source_url="https://www.berachain.com/terms-of-service",
                source_checked_on="2026-03-15",
                confidence="high",
                review_required=False,
                service_start_date="2025-02-05",
                valid_from="2025-02-05",
            )
        )

    if "starknet" in normalized:
        return _return_with_temporal_check(
            OperatorOrigin(
                platform="Starknet",
                service_scope="crypto",
                operator_entity="Starknet Foundation",
                operator_country="KY",
                source_url="https://www.starknet.io/privacy-policy/",
                source_checked_on="2026-03-15",
                confidence="medium",
                review_required=False,
                service_start_date="2021-11-16",  # Starknet mainnet-alpha launch
                valid_from=None,
            )
        )

    if "zksync" in normalized:
        return _return_with_temporal_check(
            OperatorOrigin(
                platform="zkSync",
                service_scope="crypto",
                operator_entity="Matter Labs",
                operator_country="KY",
                source_url="https://zksync.io/terms",
                source_checked_on="2026-03-15",
                confidence="high",
                review_required=False,
                valid_from=None,  # Historical operator, exact start date unknown
            )
        )

    if "solana" in normalized:
        return _return_with_temporal_check(
            OperatorOrigin(
                platform="Solana",
                service_scope="crypto",
                operator_entity="Solana Foundation",
                operator_country="CH",
                source_url="https://solana.org/",
                source_checked_on="2026-03-15",
                confidence="medium",
                review_required=False,
                valid_from=None,  # Historical operator, exact start date unknown
            )
        )

    # Handle both correct "Tonkeeper" and common typo "Tonkeper" from Koinly exports
    if "tonkeeper" in normalized or "tonkeper" in normalized:
        return _return_with_temporal_check(
            OperatorOrigin(
                platform="Tonkeeper",
                service_scope="crypto",
                operator_entity="Ton Apps UK Ltd.",
                operator_country="GB",
                source_url="https://tonkeeper.com/terms",
                source_checked_on="2026-03-15",
                confidence="high",
                review_required=False,
                valid_from=None,  # Historical operator with unknown exact start date
            )
        )

    if re.search(r"\bton\b", normalized) and "tonkeeper" not in normalized and "tonkeper" not in normalized:
        return _return_with_temporal_check(
            OperatorOrigin(
                platform="TON",
                service_scope="crypto",
                operator_entity="TON Foundation",
                operator_country="CH",
                source_url="https://ton.foundation/",
                source_checked_on="2026-03-15",
                confidence="high",
                review_required=False,
                valid_from=None,  # Historical operator, exact start date unknown
            )
        )

    if "ethereum" in normalized:
        return _return_with_temporal_check(
            OperatorOrigin(
                platform="Ethereum",
                service_scope="crypto",
                operator_entity="Ethereum Foundation",
                operator_country="CH",
                source_url="https://blog.ethereum.org/2024/05/08/ethereum-foundation-report-2024",
                source_checked_on="2026-03-15",
                confidence="high",
                review_required=False,
                service_start_date="2015-07-30",  # Ethereum mainnet launch
                valid_from="2026-03-15",  # Source verification date
            )
        )

    if "aptos" in normalized:
        return _return_with_temporal_check(
            OperatorOrigin(
                platform="Aptos",
                service_scope="crypto",
                operator_entity="Aptos Foundation",
                operator_country="KY",
                source_url="https://aptosfoundation.org/terms",
                source_checked_on="2026-03-15",
                confidence="high",
                review_required=False,
                service_start_date="2022-10-17",  # Aptos mainnet launch
                valid_from="2026-03-15",  # Source verification date
            )
        )

    if re.search(r"\bsui\b", normalized):
        return _return_with_temporal_check(
            OperatorOrigin(
                platform="Sui",
                service_scope="crypto",
                operator_entity="Sui Foundation",
                operator_country="KY",
                source_url="https://www.sui.io/terms",
                source_checked_on="2026-03-15",
                confidence="medium",
                review_required=False,
                service_start_date="2023-05-03",  # Sui mainnet launch
                valid_from=None,
            )
        )

    if "arbitrum" in normalized:
        return _return_with_temporal_check(
            OperatorOrigin(
                platform="Arbitrum",
                service_scope="crypto",
                operator_entity="The Arbitrum Foundation",
                operator_country="KY",
                source_url="https://docs.arbitrum.foundation/assets/files/The%20Arbitrum%20Foundation%20M%26A%20-%2020%20July%202023-6e264ee4c38da73a3aa4c8581c5f751f.pdf",
                source_checked_on="2026-03-15",
                confidence="high",
                review_required=False,
                service_start_date="2021-08-31",  # Arbitrum One mainnet launch
                valid_from="2026-03-15",  # Source verification date
            )
        )

    if re.search(r"\bmantle\b", normalized):
        return _return_with_temporal_check(
            OperatorOrigin(
                platform="Mantle",
                service_scope="crypto",
                operator_entity="Mantle Foundation S.A.",
                operator_country="VG",
                source_url="https://www.ipd.gov.hk/hkipjournal/15032024/PUBLICATION_TYPE_TRADE_MARK_REGISTERED.pdf",
                source_checked_on="2026-03-15",
                confidence="medium",
                review_required=False,
                platform_assumption=(
                    "Mantle Foundation operator entity based on trademark registration; verify current entity structure"
                ),
                platform_review_required=True,
                service_start_date="2023-07-17",  # Mantle mainnet launch
                valid_from="2024-03-15",
            )
        )

    if "polygon" in normalized:
        return _return_with_temporal_check(
            OperatorOrigin(
                platform="Polygon",
                service_scope="crypto",
                operator_entity="Polygon Labs UI (Cayman) Ltd.",
                operator_country="KY",
                source_url="https://polygon.technology/terms-of-use",
                source_checked_on="2026-03-15",
                confidence="high",
                review_required=False,
                service_start_date="2020-05-28",  # Polygon mainnet launch
                valid_from="2026-03-15",  # Source verification date
            )
        )

    if re.search(r"\bbase\b", normalized) and "coinbase" not in normalized:
        return _return_with_temporal_check(
            OperatorOrigin(
                platform="BASE",
                service_scope="crypto",
                operator_entity="Coinbase Technologies, Inc.",
                operator_country="US",
                source_url="https://docs.base.org/terms-of-service",
                source_checked_on="2026-03-15",
                confidence="medium",
                review_required=False,
                service_start_date="2023-08-09",  # BASE mainnet launch
                valid_from="2026-03-15",  # Source verification date
            )
        )

    if "filecoin" in normalized:
        return _return_with_temporal_check(
            OperatorOrigin(
                platform="Filecoin",
                service_scope="crypto",
                operator_entity="Filecoin Foundation",
                operator_country="US",
                source_url="https://careers.fil.org/privacy-policy",
                source_checked_on="2026-03-15",
                confidence="medium",
                review_required=False,
                service_start_date="2020-10-15",  # Filecoin mainnet launch
                valid_from="2024-04-01",
            )
        )

    if "binance" in normalized:
        return _return_with_temporal_check(
            OperatorOrigin(
                platform="Binance",
                service_scope="crypto",
                operator_entity="Binance Spain, S.L. (Europe override for filing output)",
                operator_country="ES",
                source_url="https://www.binance.com/es/about-legal/local-terms",
                source_checked_on="2026-03-15",
                confidence="medium",
                review_required=False,
                valid_from=None,  # Europe override verified 2026-03-15; exact entity change date unknown
            )
        )

    if "gate.io" in normalized or normalized == "gate":
        return _return_with_temporal_check(
            OperatorOrigin(
                platform="Gate.io",
                service_scope="crypto",
                operator_entity="Gate Technology Ltd",
                operator_country="MT",
                source_url="https://www.gate.com/en-eu/about-us",
                source_checked_on="2026-03-15",
                confidence="high",
                review_required=False,
                valid_from=None,  # Historical operator, exact start date unknown
            )
        )

    if "kraken" in normalized:
        return _return_with_temporal_check(
            OperatorOrigin(
                platform="Kraken",
                service_scope="crypto",
                operator_entity="Payward Ireland Limited / Payward Europe Solutions Limited",
                operator_country="IE",
                source_url="https://support.kraken.com/articles/where-is-kraken-licensed-or-regulated",
                source_checked_on="2026-03-15",
                confidence="high",
                review_required=False,
                valid_from=None,  # Historical operator, exact start date unknown
            )
        )

    return _return_with_temporal_check(
        OperatorOrigin(
            platform=platform,
            service_scope="crypto",
            operator_entity="UNKNOWN_OPERATOR_REVIEW_REQUIRED",
            operator_country="UNKNOWN",
            source_url="",
            source_checked_on="2026-03-08",
            confidence="low",
            review_required=True,
            review_reason="Unknown platform - operator origin could not be determined automatically",
            valid_from="2026-03-08",  # Unknown platform - use source check date as valid_from
        )
    )
