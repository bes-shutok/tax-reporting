"""Per-year on-chain wallet config loader for the on-chain transaction fetcher.

This loader reads ``resources/source/<year>/chains.json`` and returns a
list of :class:`OnChainWalletConfig` entries. It is the config-loading
step of the optional on-chain transaction fetcher (a parallel,
year-scoped collection step that is independent of the Koinly-based
crypto tax pipeline).

Design notes
------------
- **DI-6 (mirrors derivatives template; single-WARNING ownership):** the
  loader reuses :func:`load_guarded_json` from
  :mod:`infrastructure.json_loader`. A *missing* config degrades silently
  (returns ``[]`` with NO log) - the single WARNING for "config missing"
  is owned by the orchestrator (:func:`run_on_chain_fetch` / ``main.py``),
  NOT here. Mirrors the comment at ``derivatives_filter.py:124-128``:
  "Logging here would double-warn for the same condition." Every other
  guard kind (``symlink``, ``oversize``, ``stat_error``, ``invalid_json``)
  raises :class:`FileProcessingError` embedding the path.
- **DI-8 (repo-root resolution; no private-symbol import):** the loader
  resolves the repo root itself via :func:`_find_repository_root`
  imported from :mod:`application.crypto.classification` (the public
  helper, NOT the private ``_REPOSITORY_ROOT`` binding).
- **DI-2 (registry-derived chain facts):** chain facts (chainid,
  native ticker, launch date) live in the trusted chain registry in
  :mod:`application.crypto.chain_derivation` (the ``_CHAIN_TO_CHAINID``,
  ``_CHAIN_ON_CHAIN_NATIVE_TICKER``, ``_CHAIN_LAUNCH_DATE`` maps). The
  user supplies only wallet identity (``chain``, ``label``,
  ``address``); the loader derives ``chainid``/``native_ticker`` from
  the registry and ``start_date``/``end_date`` from the fiscal year
  clamped to the chain's launch date / today. No chain identity is
  supplied by the user beyond the ``chain`` name key.
- Schema validation (dict with a ``wallets`` list; each entry has the
  required keys with correct types) runs caller-side, modeled on
  ``_load_derivatives_labels_config_from_path`` at
  ``application/crypto/derivatives_filter.py:102-156``.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path

from ..domain.exceptions import FileProcessingError
from ..infrastructure.json_loader import DEGRADED, load_guarded_json
from .crypto.chain_derivation import (
    chain_launch_date,
    chainid_for,
    native_ticker_for,
)
from .crypto.classification import _find_repository_root

# Max size of a chains.json config file (1 MiB). Bound for the JSON read
# performed by infrastructure.json_loader.load_guarded_json.
_MAX_CHAINS_FILE_SIZE = 1 * 1024 * 1024

# Required keys for each wallet entry, in declaration order. The user
# supplies only wallet identity; chainid/native_ticker/start_date/end_date
# are derived internally (DI-2 restated: chain facts come from the
# registry in chain_derivation.py + the fiscal year).
_REQUIRED_KEYS: tuple[str, ...] = (
    "chain",
    "label",
    "address",
)


@dataclasses.dataclass(frozen=True)
class OnChainWalletConfig:
    """A single wallet entry from the per-year chains.json config.

    The user supplies only ``chain``/``label``/``address`` (wallet
    identity). The four chain-property fields below are DERIVED
    internally (DI-2 restated): ``chainid``/``native_ticker`` come from
    the trusted chain registry in :mod:`chain_derivation`, and
    ``start_date``/``end_date`` come from the fiscal year clamped to the
    chain's launch date / today.

    Attributes:
        chain: Human-readable chain name (e.g. ``"Berachain"``). The one
            chain-identity key supplied by the user; the registry derives
            the rest.
        chainid: Etherscan V2 numeric chain id (e.g. ``80094``). Derived
            from the chain registry via :func:`chainid_for`.
        label: Free-form wallet label used in CSV output.
        address: Wallet address this config targets.
        native_ticker: Native asset ticker for txlist rows (e.g.
            ``"BERA"``). Derived from the chain registry via
            :func:`native_ticker_for` (CSV-output-correct map).
        start_date: Inclusive start, derived as
            ``max(date(year, 1, 1), chain_launch_date)`` (Jan 1 clamped
            up to genesis for chains launching mid-year).
        end_date: Inclusive end, derived as
            ``min(date(year, 12, 31), today)`` (Dec 31 clamped down to
            today for future fiscal years).
    """

    chain: str
    chainid: int
    label: str
    address: str
    native_ticker: str
    start_date: date
    end_date: date


def _on_error(failed_path: Path, kind: str, detail: str) -> object:
    """Policy callback for :func:`load_guarded_json`.

    Mirrors the degrade-vs-raise policy of the derivatives labels loader
    (``derivatives_filter._on_error``). A *missing* config degrades
    silently (returns :data:`DEGRADED` -> loader returns ``[]`` with NO
    log; DI-6 - the orchestrator owns the single WARNING). Every other
    kind raises :class:`FileProcessingError` embedding the path.
    """
    if kind == "missing":
        return DEGRADED
    if kind == "symlink":
        raise FileProcessingError(
            f"Chains config at {failed_path} is a symlink - "
            "only regular files are accepted for security"
        )
    if kind == "oversize":
        raise FileProcessingError(
            f"Chains config exceeds size limit ({detail}): {failed_path}"
        )
    if kind == "stat_error":
        raise FileProcessingError(
            f"Could not stat chains config {failed_path}: {detail}"
        )
    if kind == "invalid_json":
        raise FileProcessingError(
            f"Chains config {failed_path} contains invalid JSON: {detail}"
        )
    # Defensive: unknown kind token from the helper is itself a config hazard.
    raise FileProcessingError(
        f"Chains config {failed_path} failed to load ({kind}): {detail}"
    )


def _validate_str_field(
    entry: dict[str, object], field: str, index: int, path: Path
) -> str:
    """Return ``entry[field]`` asserting it is a ``str``."""
    value = entry[field]
    if not isinstance(value, str):
        raise FileProcessingError(
            f"Chains config wallet entry at index {index} field "
            f"'{field}' must be a string, got {type(value).__name__}: {path}"
        )
    return value


def _build_wallet_config(
    entry: dict[str, object], index: int, path: Path, year: int, now: date
) -> OnChainWalletConfig:
    """Validate and build a single :class:`OnChainWalletConfig`.

    The user supplies only wallet identity (``chain``/``label``/
    ``address``). The four chain-property fields are derived: ``chainid``
    and ``native_ticker`` from the trusted chain registry, and the date
    window from the fiscal year clamped to the chain's launch date /
    today. Runs presence checks (required keys), per-field type checks,
    chain-registry resolution (fail-closed on an unsupported chain), and
    the final ``end_date >= start_date`` invariant. All errors name the
    field/chain and the offending entry index.
    """
    for key in _REQUIRED_KEYS:
        if key not in entry:
            raise FileProcessingError(
                f"Chains config wallet entry at index {index} is "
                f"missing required field '{key}': {path}"
            )

    chain = _validate_str_field(entry, "chain", index, path)
    label = _validate_str_field(entry, "label", index, path)
    address = _validate_str_field(entry, "address", index, path)

    # DI-2 restated: derive chain facts from the trusted registry, not
    # from user input. Any user-supplied chainid/native_ticker/start_date/
    # end_date in ``entry`` is silently ignored (ignore-extras contract).
    chainid_val = chainid_for(chain)
    if chainid_val is None:
        # Fail-closed: an unknown or non-EVM chain cannot be fetched. The
        # message scopes "supported" to Berachain only (F1 fold): the
        # other 7 EVM chains are internally wired in the registry but
        # unsafe until a pre-existing block-0 pagination truncation is
        # fixed (tracked separately), so the docs must not advertise them.
        raise FileProcessingError(
            f"Chains config wallet entry at index {index} has unsupported "
            f"chain {chain!r}: only Berachain is currently supported for the "
            f"on-chain fetcher (other EVM chains are internally wired but "
            f"unsafe until a pre-existing block-0 pagination truncation is "
            f"fixed): {path}"
        )
    ticker = native_ticker_for(chain)  # non-None: chainid_for matched
    launch = chain_launch_date(chain)  # non-None: chainid_for matched

    # Derive the date window from the fiscal year, clamped to genesis /
    # today. start_date = max(Jan 1 of year, genesis); end_date =
    # min(Dec 31 of year, today).
    start_date = max(date(year, 1, 1), launch)
    end_date = min(date(year, 12, 31), now)

    if end_date < start_date:
        raise FileProcessingError(
            f"Chains config wallet entry at index {index} chain {chain!r} "
            f"has an empty date window for fiscal year {year}: derived "
            f"start_date {start_date} > end_date {end_date}: {path}"
        )

    return OnChainWalletConfig(
        chain=chain,
        chainid=chainid_val,
        label=label,
        address=address,
        native_ticker=ticker,
        start_date=start_date,
        end_date=end_date,
    )


def _load_on_chain_wallets_from_path(
    path: Path, year: int, *, today: Callable[[], date] | None = None
) -> list[OnChainWalletConfig]:
    """Load and validate a chains.json config file at ``path``.

    Args:
        path: Absolute path to the JSON config file.
        year: Four-digit fiscal year used to derive each wallet's date
            window (``start_date``/``end_date``).
        today: Callable returning the current date, used to clamp an
            overly-late ``end_date`` down to today. Defaults to the
            current UTC date; injected for deterministic testing (no
            freezegun dependency).

    Returns:
        List of validated :class:`OnChainWalletConfig` entries. An empty
        list (with NO log) if the file is missing (DI-6: the orchestrator
        owns the single WARNING).

    Raises:
        FileProcessingError: If the path is a symlink, the file exceeds
            the size limit, the JSON is malformed, the ``wallets`` key is
            missing or not a list, a wallet entry is missing a required
            field or has a wrong-typed value, the chain is unsupported,
            or the derived ``end_date < start_date`` (empty window).
    """
    data = load_guarded_json(
        path, size_limit=_MAX_CHAINS_FILE_SIZE, on_error=_on_error
    )

    if data is DEGRADED:
        # Silent return; the orchestrator (run_on_chain_fetch / main.py)
        # emits the single WARNING when the wallet list is empty. Logging
        # here would double-warn for the same condition (DI-6).
        return []

    if not isinstance(data, dict):
        raise FileProcessingError(
            f"Chains config must contain a JSON object, got "
            f"{type(data).__name__}: {path}"
        )

    if "wallets" not in data:
        raise FileProcessingError(
            f"Chains config must contain a 'wallets' key: {path}"
        )

    wallets_value = data["wallets"]
    if not isinstance(wallets_value, list):
        raise FileProcessingError(
            f"Chains config 'wallets' must be a list, got "
            f"{type(wallets_value).__name__}: {path}"
        )

    now = today() if today is not None else datetime.now(tz=UTC).date()

    configs: list[OnChainWalletConfig] = []
    for index, entry in enumerate(wallets_value):
        if not isinstance(entry, dict):
            raise FileProcessingError(
                f"Chains config wallet entry at index {index} must be a "
                f"JSON object, got {type(entry).__name__}: {path}"
            )
        configs.append(_build_wallet_config(entry, index, path, year, now))

    return configs


def load_on_chain_wallets(
    year: int, *, today: Callable[[], date] | None = None
) -> list[OnChainWalletConfig]:
    """Load the on-chain wallet config for ``year``.

    Resolves the repo root itself via :func:`_find_repository_root`
    (DI-8: imports the public helper, not the private ``_REPOSITORY_ROOT``
    binding) and reads ``<repo_root>/resources/source/<year>/chains.json``.

    Args:
        year: Four-digit fiscal year (e.g. ``2025``).
        today: Optional callable returning the current date, for clamping
            an overly-late ``end_date`` (defaults to :func:`date.today`).

    Returns:
        List of validated :class:`OnChainWalletConfig` entries. Empty
        list (silently, no log) if no config exists for the year.

    Raises:
        FileProcessingError: If the resolved config file is malformed
            (see :func:`_load_on_chain_wallets_from_path`).
    """
    repo_root = _find_repository_root()
    path = repo_root / "resources" / "source" / str(year) / "chains.json"
    return _load_on_chain_wallets_from_path(path, year, today=today)
