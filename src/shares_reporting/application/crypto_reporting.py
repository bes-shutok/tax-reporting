"""Crypto tax reporting helpers for Koinly exports."""

from __future__ import annotations

import csv
import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Final


@dataclass(frozen=True)
class OperatorOrigin:
    """Operator and jurisdiction metadata for a wallet platform."""

    platform: str
    service_scope: str
    operator_entity: str
    operator_country: str
    source_url: str
    source_checked_on: str
    confidence: str
    review_required: bool


@dataclass(frozen=True)
class CryptoCapitalGainEntry:
    """Single taxable crypto disposal row for reporting."""

    disposal_date: str
    acquisition_date: str
    asset: str
    amount: Decimal
    cost_eur: Decimal
    proceeds_eur: Decimal
    gain_loss_eur: Decimal
    holding_period: str
    wallet: str
    platform: str
    operator_origin: OperatorOrigin
    annex_hint: str
    review_required: bool
    notes: str


@dataclass(frozen=True)
class CryptoRewardIncomeEntry:
    """Single crypto income/reward row for reporting."""

    date: str
    asset: str
    amount: Decimal
    value_eur: Decimal
    income_label: str
    source_type: str
    wallet: str
    platform: str
    operator_origin: OperatorOrigin
    annex_hint: str
    review_required: bool
    description: str


@dataclass(frozen=True)
class HoldingsSnapshot:
    """Holdings totals for reconciliation."""

    asset_rows: int
    total_cost_eur: Decimal
    total_value_eur: Decimal


@dataclass(frozen=True)
class CryptoReconciliationSummary:
    """Control totals for capital and income sections."""

    capital_rows: int
    reward_rows: int
    short_term_rows: int
    long_term_rows: int
    capital_cost_total_eur: Decimal
    capital_proceeds_total_eur: Decimal
    capital_gain_total_eur: Decimal
    reward_total_eur: Decimal
    opening_holdings: HoldingsSnapshot | None
    closing_holdings: HoldingsSnapshot | None


@dataclass(frozen=True)
class CryptoSkippedZeroValueToken:
    """Asset skipped from report output because value is zero."""

    source_section: str
    asset: str
    count: int


@dataclass(frozen=True)
class CryptoCompletePdfSummary:
    """Extracted metadata from Koinly complete tax report PDF."""

    period: str | None
    timezone: str | None
    extracted_tokens: int


@dataclass(frozen=True)
class CryptoTaxReport:
    """Normalized crypto dataset ready for Excel rendering."""

    tax_year: int
    capital_entries: list[CryptoCapitalGainEntry]
    reward_entries: list[CryptoRewardIncomeEntry]
    reconciliation: CryptoReconciliationSummary
    skipped_zero_value_tokens: list[CryptoSkippedZeroValueToken] = field(default_factory=list)
    pdf_summary: CryptoCompletePdfSummary | None = None


ZERO: Final = Decimal("0")
DATE_FORMATS: Final = (
    "%d/%m/%Y %H:%M",
    "%Y-%m-%d %H:%M:%S UTC",
    "%Y-%m-%d %H:%M:%S",
    "%d/%m/%Y",
    "%Y-%m-%d",
)


def resolve_operator_origin(platform: str, transaction_type: str | None = None) -> OperatorOrigin:
    """Resolve operator metadata from platform brand and transaction type."""
    normalized = platform.lower()
    transaction_type_normalized = (transaction_type or "").lower()

    if "wirex" in normalized:
        if transaction_type_normalized.startswith("fiat"):
            return OperatorOrigin(
                platform="Wirex",
                service_scope="fiat",
                operator_entity="Wirex Limited",
                operator_country="United Kingdom",
                source_url="https://wirexapp.com/legal",
                source_checked_on="2026-03-08",
                confidence="medium",
                review_required=True,
            )
        return OperatorOrigin(
            platform="Wirex",
            service_scope="crypto",
            operator_entity="Wirex Digital (crypto operator, verify account terms)",
            operator_country="Croatia",
            source_url="https://wirexapp.com/legal",
            source_checked_on="2026-03-08",
            confidence="medium",
            review_required=True,
        )

    if "bybit" in normalized:
        return OperatorOrigin(
            platform="Bybit",
            service_scope="crypto",
            operator_entity="Bybit group entity (account-region specific)",
            operator_country="United Arab Emirates",
            source_url="https://www.bybit.com/en/legal/terms-of-service/terms-of-service",
            source_checked_on="2026-03-08",
            confidence="low",
            review_required=True,
        )

    if "binance" in normalized:
        return OperatorOrigin(
            platform="Binance",
            service_scope="crypto",
            operator_entity="Binance group entity (account-region specific)",
            operator_country="Multiple jurisdictions",
            source_url="https://www.binance.com/en/terms",
            source_checked_on="2026-03-08",
            confidence="low",
            review_required=True,
        )

    if "kraken" in normalized:
        return OperatorOrigin(
            platform="Kraken",
            service_scope="crypto",
            operator_entity="Payward group entity (account-region specific)",
            operator_country="Multiple jurisdictions",
            source_url="https://www.kraken.com/legal",
            source_checked_on="2026-03-08",
            confidence="low",
            review_required=True,
        )

    return OperatorOrigin(
        platform=platform,
        service_scope="crypto",
        operator_entity="UNKNOWN_OPERATOR_REVIEW_REQUIRED",
        operator_country="UNKNOWN",
        source_url="",
        source_checked_on="2026-03-08",
        confidence="low",
        review_required=True,
    )


def load_koinly_crypto_report(koinly_dir: Path) -> CryptoTaxReport | None:
    """Load Koinly exports from a directory and normalize for tax reporting."""
    if not koinly_dir.exists() or not koinly_dir.is_dir():
        return None

    capital_file = _find_report_file(koinly_dir, "capital_gains_report")
    income_file = _find_report_file(koinly_dir, "income_report")

    if capital_file is None and income_file is None:
        return None

    year = _extract_tax_year(koinly_dir, capital_file, income_file)
    skipped_assets: Counter[tuple[str, str]] = Counter()
    capital_entries = _parse_capital_gains_file(capital_file, skipped_assets) if capital_file else []
    reward_entries = _parse_income_file(income_file, skipped_assets) if income_file else []

    opening = _parse_holdings_file(
        _find_report_file(koinly_dir, "beginning_of_year_holdings_report"),
        "holdings_opening",
        skipped_assets,
    )
    closing = _parse_holdings_file(
        _find_report_file(koinly_dir, "end_of_year_holdings_report"),
        "holdings_closing",
        skipped_assets,
    )

    short_term_rows = sum(1 for row in capital_entries if row.holding_period.lower().startswith("short"))
    long_term_rows = sum(1 for row in capital_entries if row.holding_period.lower().startswith("long"))

    reconciliation = CryptoReconciliationSummary(
        capital_rows=len(capital_entries),
        reward_rows=len(reward_entries),
        short_term_rows=short_term_rows,
        long_term_rows=long_term_rows,
        capital_cost_total_eur=sum((row.cost_eur for row in capital_entries), start=ZERO),
        capital_proceeds_total_eur=sum((row.proceeds_eur for row in capital_entries), start=ZERO),
        capital_gain_total_eur=sum((row.gain_loss_eur for row in capital_entries), start=ZERO),
        reward_total_eur=sum((row.value_eur for row in reward_entries), start=ZERO),
        opening_holdings=opening,
        closing_holdings=closing,
    )

    skipped_zero_value_tokens = [
        CryptoSkippedZeroValueToken(source_section=section, asset=asset, count=count)
        for (section, asset), count in sorted(skipped_assets.items())
    ]

    complete_tax_report_file = _find_report_path(koinly_dir, "complete_tax_report", ".pdf")
    pdf_summary = _parse_complete_tax_report_pdf(complete_tax_report_file) if complete_tax_report_file else None

    return CryptoTaxReport(
        tax_year=year,
        capital_entries=capital_entries,
        reward_entries=reward_entries,
        reconciliation=reconciliation,
        skipped_zero_value_tokens=skipped_zero_value_tokens,
        pdf_summary=pdf_summary,
    )


def _find_report_file(koinly_dir: Path, marker: str) -> Path | None:
    return _find_report_path(koinly_dir, marker, ".csv")


def _find_report_path(koinly_dir: Path, marker: str, suffix: str) -> Path | None:
    matches = sorted(koinly_dir.glob(f"*{marker}*{suffix}"))
    return matches[0] if matches else None


def _extract_tax_year(koinly_dir: Path, capital_file: Path | None, income_file: Path | None) -> int:
    for candidate in [capital_file, income_file]:
        if candidate is None:
            continue
        match = re.search(r"koinly_(\d{4})_", candidate.name)
        if match:
            return int(match.group(1))
    fallback_match = re.search(r"(\d{4})", koinly_dir.name)
    if fallback_match:
        return int(fallback_match.group(1))
    return datetime.now(tz=None).year


def _parse_capital_gains_file(path: Path, skipped_assets: Counter[tuple[str, str]]) -> list[CryptoCapitalGainEntry]:
    rows = _read_koinly_rows(path)
    capital_entries: list[CryptoCapitalGainEntry] = []

    logger = logging.getLogger(__name__)
    for row in rows:
        asset = row.get("Asset", "").strip()
        try:
            cost_eur = _parse_koinly_decimal(row.get("Cost (EUR)", ""))
            proceeds_eur = _parse_koinly_decimal(row.get("Proceeds (EUR)", ""))
            gain_loss_eur = _parse_koinly_decimal(row.get("Gain / loss", ""))
        except ValueError as exc:
            logger.warning("Skipping capital gains row for %r — ambiguous decimal value: %s", asset, exc)
            continue

        if cost_eur == ZERO and proceeds_eur == ZERO and gain_loss_eur == ZERO:
            _register_skipped_zero_asset(skipped_assets, "capital_gains", asset)
            continue

        wallet = row.get("Wallet Name", "").strip()
        platform = _normalize_platform_name(wallet)
        operator_origin = resolve_operator_origin(platform, transaction_type="crypto_disposal")
        notes = row.get("Notes", "").strip()
        review_required = operator_origin.review_required or "missing cost basis" in notes.lower()

        capital_entries.append(
            CryptoCapitalGainEntry(
                disposal_date=_format_datetime(_parse_koinly_datetime(row.get("Date Sold", ""))),
                acquisition_date=_format_datetime(_parse_koinly_datetime(row.get("Date Acquired", ""))),
                asset=asset,
                amount=_parse_koinly_decimal(row.get("Amount", "")),
                cost_eur=cost_eur,
                proceeds_eur=proceeds_eur,
                gain_loss_eur=gain_loss_eur,
                holding_period=row.get("Holding period", "").strip() or "Unknown",
                wallet=wallet,
                platform=platform,
                operator_origin=operator_origin,
                annex_hint="J",
                review_required=review_required,
                notes=notes,
            )
        )
    return capital_entries


def _parse_income_file(path: Path, skipped_assets: Counter[tuple[str, str]]) -> list[CryptoRewardIncomeEntry]:
    rows = _read_koinly_rows(path)
    reward_entries: list[CryptoRewardIncomeEntry] = []

    for row in rows:
        asset = row.get("Asset", "").strip()
        value_eur = _parse_koinly_decimal(row.get("Value (EUR)", ""))
        if value_eur == ZERO:
            _register_skipped_zero_asset(skipped_assets, "income", asset)
            continue

        wallet = row.get("Wallet Name", "").strip()
        platform = _normalize_platform_name(wallet)
        operator_origin = resolve_operator_origin(platform, transaction_type="crypto_deposit")

        reward_entries.append(
            CryptoRewardIncomeEntry(
                date=_format_datetime(_parse_koinly_datetime(row.get("Date", ""))),
                asset=asset,
                amount=_parse_koinly_decimal(row.get("Amount", "")),
                value_eur=value_eur,
                income_label="Reward",
                source_type=row.get("Type", "").strip(),
                wallet=wallet,
                platform=platform,
                operator_origin=operator_origin,
                annex_hint="J",
                review_required=operator_origin.review_required,
                description=row.get("Description", "").strip(),
            )
        )

    return reward_entries


def _parse_holdings_file(
    path: Path | None, source_section: str, skipped_assets: Counter[tuple[str, str]]
) -> HoldingsSnapshot | None:
    if path is None:
        return None

    rows = _read_koinly_rows(path)
    included_rows = []
    for row in rows:
        asset = row.get("Asset", "").strip()
        value_eur = _parse_koinly_decimal(row.get("Value (EUR)", ""))
        if value_eur == ZERO:
            _register_skipped_zero_asset(skipped_assets, source_section, asset)
            continue
        included_rows.append(row)

    return HoldingsSnapshot(
        asset_rows=len(included_rows),
        total_cost_eur=sum((_parse_koinly_decimal(row.get("Cost (EUR)", "")) for row in included_rows), start=ZERO),
        total_value_eur=sum((_parse_koinly_decimal(row.get("Value (EUR)", "")) for row in included_rows), start=ZERO),
    )


def _parse_complete_tax_report_pdf(path: Path) -> CryptoCompletePdfSummary | None:
    content = path.read_bytes()
    hex_tokens = re.findall(rb"<([0-9A-Fa-f]{2,})>", content)
    decoded_tokens = [_decode_pdf_hex_token(token) for token in hex_tokens]
    cleaned_tokens = [token for token in decoded_tokens if token]

    if not cleaned_tokens:
        return None

    joined = " ".join(cleaned_tokens)
    period_match = re.search(r"\b\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}\s+to\s+\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}\b", joined)
    timezone_match = re.search(r"\b[A-Za-z]+/[A-Za-z_]+(?:/[A-Za-z_]+)?\b", joined)

    return CryptoCompletePdfSummary(
        period=period_match.group(0) if period_match else None,
        timezone=timezone_match.group(0) if timezone_match else None,
        extracted_tokens=len(cleaned_tokens),
    )


def _decode_pdf_hex_token(token: bytes) -> str:
    if len(token) % 2 != 0:
        return ""
    try:
        raw = bytes.fromhex(token.decode("ascii"))
    except ValueError:
        return ""
    if not raw:
        return ""
    text = raw.decode("utf-16-be", errors="ignore") if b"\x00" in raw else raw.decode("utf-8", errors="ignore")
    text = text.replace("\x00", "").strip()
    return text if text else ""


def _register_skipped_zero_asset(skipped_assets: Counter[tuple[str, str]], section: str, asset: str) -> None:
    cleaned_asset = asset or "UNKNOWN_ASSET"
    skipped_assets[(section, cleaned_asset)] += 1


def _read_koinly_rows(path: Path) -> list[dict[str, str]]:
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    header_index = _detect_header_index(lines, path)
    reader = csv.DictReader(lines[header_index:])

    rows: list[dict[str, str]] = []
    for row in reader:
        if row is None:
            continue
        if all((value is None or str(value).strip() == "") for value in row.values()):
            continue
        rows.append({key: (value or "") for key, value in row.items()})
    return rows


def _detect_header_index(lines: list[str], path: Path) -> int:
    header_markers = ("Date Sold", "Date Acquired", "Date,", "Asset,Quantity", "Currency,Wallet")
    for index, line in enumerate(lines):
        if "," not in line:
            continue
        if any(marker in line for marker in header_markers):
            return index
    raise ValueError(f"Unable to detect CSV header in Koinly export: {path}")


def _parse_koinly_datetime(value: str) -> datetime:
    text = value.strip()
    if not text:
        return datetime(1970, 1, 1, tzinfo=UTC)

    for date_format in DATE_FORMATS:
        try:
            parsed = datetime.strptime(text, date_format)  # noqa: DTZ007
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError:
            continue
    raise ValueError(f"Unsupported Koinly date format: {value}")


def _format_datetime(value: datetime) -> str:
    if value.hour == 0 and value.minute == 0 and value.second == 0:
        return value.strftime("%Y-%m-%d 00:00")
    return value.strftime("%Y-%m-%d %H:%M")


def _parse_koinly_decimal(value: str) -> Decimal:
    text = value.strip().replace("\u00a0", "").replace(" ", "")
    if not text:
        return ZERO
    if text.startswith('"') and text.endswith('"'):
        text = text[1:-1]
    if text in {"", "-"}:
        return ZERO
    text = _normalize_koinly_decimal_text(text)
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"Unsupported Koinly decimal format: {value}") from exc


def _normalize_koinly_decimal_text(text: str) -> str:
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            return text.replace(".", "").replace(",", ".")
        return text.replace(",", "")

    if "," in text:
        if re.fullmatch(r"[+-]?[1-9]\d{0,2}(,\d{3})+", text):
            return text.replace(",", "")
        return text.replace(",", ".")

    if "." in text and re.fullmatch(r"[+-]?[1-9]\d{0,2}(\.\d{3}){2,}", text):
        return text.replace(".", "")

    if "." in text and re.fullmatch(r"[+-]?[1-9]\d{0,2}\.\d{3}", text):
        raise ValueError(f"Ambiguous decimal format: {text!r} — dot could be thousands separator or decimal point")

    return text


def _normalize_platform_name(wallet: str) -> str:
    cleaned = wallet.strip()
    if not cleaned:
        return "Unknown"
    if "(" in cleaned:
        cleaned = cleaned.split("(", maxsplit=1)[0].strip()
    return cleaned
