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
  resolves the repo root itself via
  :func:`tax_reporting.application.paths.find_repository_root` (the PUBLIC
  shared helper; no cross-feature private import).
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

from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path

from ..domain.exceptions import ConfigurationError, FileProcessingError
from ..infrastructure.json_loader import DEGRADED, load_guarded_json
from ..infrastructure.on_chain.position_token_registry import (
    PositionTokenRegistry,
    load_position_token_registry,
)
from .crypto.chain_derivation import (
    chain_launch_date,
    chainid_for,
    native_ticker_for,
)
from .paths import find_repository_root, resolve_registry_path

# Per-year position-token registry filename: the literal lives
# HERE once; both the fetcher and the TH substituter load via
# :func:`load_position_token_registry_for_year`).
_POSITION_TOKEN_REGISTRY_FILENAME = "bera_position_tokens.json"

# Max size of a chains.json config file (1 MiB). Bound for the JSON read
# performed by infrastructure.json_loader.load_guarded_json.
_MAX_CHAINS_FILE_SIZE = 1 * 1024 * 1024

# Max size of a berachain_lp_snapshot.json file (2 MiB). The subgraph-derived
# LP allowlist is bounded by the number of Kodiak pools/vaults (low hundreds).
_MAX_LP_SNAPSHOT_SIZE = 2 * 1024 * 1024

# Sentinel marking an unpinned subgraph version. The design record (§9.2,
# decision #11) requires the snapshot pin a subgraph VERSION (not "latest"),
# so "latest" is rejected on load (M2: fail-loud).
_UNPINNED_SUBGRAPH_VERSION = "latest"

# The only chain the on-chain TH path validates/substitutes (plan Terms).
# ONE definition shared by the validation runner's wallet filter and the
# composition root's ON_CHAIN_TH_WALLETS precedence filter
# (two independently written copies of the literal could drift apart and
# silently change the validated wallet set at the production flip).
BERACHAIN_CHAIN = "Berachain"

# Required keys for each wallet entry, in declaration order. The user
# supplies only wallet identity; chainid/native_ticker/start_date/end_date
# are derived internally (DI-2 restated: chain facts come from the
# registry in chain_derivation.py + the fiscal year).
_REQUIRED_KEYS: tuple[str, ...] = (
    "chain",
    "label",
    "address",
)


# --- Domain types re-exported for backward compatibility ---------------------
# The frozen dataclasses (``OnChainWalletConfig``, ``LpTokenEntry``,
# ``LpSnapshot``, ``ContractEntry``, ``ContractRegistry``) and the
# ``is_valid_iso3166_alpha2`` validator now live in
# :mod:`tax_reporting.domain.on_chain_config` (review F12: pure domain types
# must not force infrastructure to import UP into application). They are
# re-exported here so existing callers that import them from the application
# loader keep working; new infrastructure callers should import from domain.
from tax_reporting.domain.on_chain_config import (  # noqa: E402,F401
    ContractEntry,
    ContractRegistry,
    LpSnapshot,
    LpTokenEntry,
    OnChainWalletConfig,
    _is_valid_iso3166_alpha2,
    is_valid_iso3166_alpha2,
)


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

    Resolves the repo root itself via :func:`find_repository_root`
    (DI-8: the public shared helper from ``application.paths``) and reads
    ``<repo_root>/resources/source/<year>/chains.json``.

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
    repo_root = find_repository_root()
    path = repo_root / "resources" / "source" / str(year) / "chains.json"
    return _load_on_chain_wallets_from_path(path, year, today=today)


# ---------------------------------------------------------------------------
# LP-token snapshot loader (Task 8, decision #11)
# ---------------------------------------------------------------------------
#
# Loads + schema-validates a subgraph-derived LP-token allowlist for the
# bytecode-fallback LP autodiscovery (see
# ``infrastructure.on_chain.lp_autodiscovery``). This loader is LOADING +
# VALIDATION only; no classification logic (the processor in Task 9 owns
# classification). The snapshot is pinned to a subgraph VERSION (not
# "latest") and carries freshness metadata (``snapshot_as_of_block`` /
# ``snapshot_as_of_date``); a WARN fires downstream when tx dates postdate
# the snapshot (handled by ``LpAutodiscovery.check_freshness``).


def _require_scalar_field(
    data: dict[str, object], field: str, source: str
) -> object:
    """Return ``data[field]`` asserting it is present (ConfigurationError else)."""
    if field not in data:
        raise ConfigurationError(
            f"LP snapshot is missing required field '{field}': {source}"
        )
    return data[field]


def _build_token_entry(
    entry: object, index: int, source: str
) -> tuple[str, LpTokenEntry]:
    """Validate one snapshot token entry; return ``(lower_addr, entry)``.

    Requires a non-null ``token_address`` (str); ``protocol`` / ``type`` are
    optional string tags. Fail-loud via :class:`ConfigurationError`.
    """
    if not isinstance(entry, dict):
        raise ConfigurationError(
            f"LP snapshot token entry at index {index} must be a JSON "
            f"object, got {type(entry).__name__}: {source}"
        )
    addr = entry.get("token_address")
    if not isinstance(addr, str) or not addr:
        raise ConfigurationError(
            f"LP snapshot token entry at index {index} has a null/invalid "
            f"'token_address' (must be a non-empty string): {source}"
        )
    protocol = entry.get("protocol")
    if protocol is not None and not isinstance(protocol, str):
        raise ConfigurationError(
            f"LP snapshot token entry at index {index} 'protocol' must be "
            f"a string: {source}"
        )
    lp_type = entry.get("type")
    if lp_type is not None and not isinstance(lp_type, str):
        raise ConfigurationError(
            f"LP snapshot token entry at index {index} 'type' must be a "
            f"string: {source}"
        )
    addr_lower = addr.lower()
    return addr_lower, LpTokenEntry(
        token_address=addr_lower, protocol=protocol, lp_type=lp_type
    )


def build_lp_snapshot(data: object, *, source: str) -> LpSnapshot:
    """Validate an in-memory LP snapshot dict and build an :class:`LpSnapshot`.

    Schema (minimum required fields):
        - ``subgraph_version``: non-empty str, NOT ``"latest"`` (must be pinned).
        - ``snapshot_as_of_block``: int >= 0.
        - ``snapshot_as_of_date``: non-empty str (ISO date).
        - ``tokens``: list of objects each with a non-null ``token_address``
          (str). ``protocol`` / ``type`` are optional informational tags.

    Args:
        data: The parsed JSON value (a dict).
        source: Marker for error messages (file path or ``"<inline-test>"``).

    Returns:
        The validated :class:`LpSnapshot`.

    Raises:
        ConfigurationError: If a required field is missing/invalid, an
            address is null, or the subgraph version is unpinned
            (``"latest"``). Fail-loud (M2).
    """
    if not isinstance(data, dict):
        raise ConfigurationError(
            f"LP snapshot must be a JSON object, got {type(data).__name__}: {source}"
        )

    subgraph_version = _validate_subgraph_version(data, source)
    block = _validate_snapshot_block(data, source)
    as_of_date = _validate_snapshot_date(data, source)
    tokens = _validate_tokens(data, source)
    subgraph = data.get("subgraph")
    if subgraph is not None and not isinstance(subgraph, str):
        raise ConfigurationError(
            f"LP snapshot 'subgraph' must be a string: {source}"
        )

    return LpSnapshot(
        subgraph=subgraph,
        subgraph_version=subgraph_version,
        snapshot_as_of_block=block,
        snapshot_as_of_date=as_of_date,
        tokens=tokens,
        source=source,
    )


def _validate_subgraph_version(data: dict[str, object], source: str) -> str:
    """Validate ``subgraph_version``: non-empty str, NOT ``"latest"``."""
    subgraph_version = _require_scalar_field(data, "subgraph_version", source)
    if not isinstance(subgraph_version, str) or not subgraph_version:
        raise ConfigurationError(
            f"LP snapshot 'subgraph_version' must be a non-empty string: {source}"
        )
    if subgraph_version == _UNPINNED_SUBGRAPH_VERSION:
        raise ConfigurationError(
            f"LP snapshot 'subgraph_version' must be pinned (got 'latest'); "
            f"the subgraph must be pinned to a concrete version, not 'latest': "
            f"{source}"
        )
    return subgraph_version


def _validate_snapshot_block(data: dict[str, object], source: str) -> int:
    """Validate ``snapshot_as_of_block``: non-negative int (bool rejected)."""
    block = _require_scalar_field(data, "snapshot_as_of_block", source)
    if not isinstance(block, int) or isinstance(block, bool) or block < 0:
        raise ConfigurationError(
            f"LP snapshot 'snapshot_as_of_block' must be a non-negative int, "
            f"got {block!r}: {source}"
        )
    return block


def _validate_snapshot_date(data: dict[str, object], source: str) -> str:
    """Validate ``snapshot_as_of_date``: non-empty str (ISO date)."""
    as_of_date = _require_scalar_field(data, "snapshot_as_of_date", source)
    if not isinstance(as_of_date, str) or not as_of_date:
        raise ConfigurationError(
            f"LP snapshot 'snapshot_as_of_date' must be a non-empty string: "
            f"{source}"
        )
    return as_of_date


def _validate_tokens(data: dict[str, object], source: str) -> dict[str, LpTokenEntry]:
    """Validate the ``tokens`` list; return the lower-cased address -> entry map."""
    raw_tokens = _require_scalar_field(data, "tokens", source)
    if not isinstance(raw_tokens, list):
        raise ConfigurationError(
            f"LP snapshot 'tokens' must be a list, got "
            f"{type(raw_tokens).__name__}: {source}"
        )
    tokens: dict[str, LpTokenEntry] = {}
    for index, entry in enumerate(raw_tokens):
        addr_lower, token_entry = _build_token_entry(entry, index, source)
        # First occurrence wins; later duplicates are ignored (no overwrite of
        # a primary entry by a stale one).
        tokens.setdefault(addr_lower, token_entry)
    return tokens


def _lp_on_error(failed_path: Path, kind: str, detail: str) -> object:
    """Policy callback for the LP snapshot loader.

    A *missing* snapshot degrades (returns :data:`DEGRADED`; the caller
    decides whether to proceed without an allowlist). Every other kind
    raises :class:`FileProcessingError`.
    """
    if kind == "missing":
        return DEGRADED
    if kind == "symlink":
        raise FileProcessingError(
            f"LP snapshot at {failed_path} is a symlink - "
            "only regular files are accepted for security"
        )
    if kind == "oversize":
        raise FileProcessingError(
            f"LP snapshot exceeds size limit ({detail}): {failed_path}"
        )
    if kind == "stat_error":
        raise FileProcessingError(
            f"Could not stat LP snapshot {failed_path}: {detail}"
        )
    if kind == "invalid_json":
        raise FileProcessingError(
            f"LP snapshot {failed_path} contains invalid JSON: {detail}"
        )
    raise FileProcessingError(
        f"LP snapshot {failed_path} failed to load ({kind}): {detail}"
    )


def load_lp_snapshot(path: Path) -> LpSnapshot:
    """Load + schema-validate the LP snapshot at ``path``.

    Runs the mechanical file guards via :func:`load_guarded_json` (symlink,
    size cap, JSON parse), then :func:`build_lp_snapshot` for schema
    validation.

    Args:
        path: Absolute path to ``berachain_lp_snapshot.json``.

    Returns:
        The validated :class:`LpSnapshot`.

    Raises:
        FileProcessingError: If the file is a symlink / oversize / malformed
            JSON / missing-but-not-degraded.
        ConfigurationError: If schema validation fails (missing required
            field, null address, unpinned subgraph version).
    """
    data = load_guarded_json(
        path, size_limit=_MAX_LP_SNAPSHOT_SIZE, on_error=_lp_on_error
    )
    if data is DEGRADED:
        # Missing snapshot is a hard error for this loader: callers that want
        # to proceed without an allowlist should construct an empty
        # LpSnapshot explicitly. Loading a path that was expected to exist
        # but is missing is a configuration failure.
        raise FileProcessingError(
            f"LP snapshot not found (expected at {path})"
        )
    return build_lp_snapshot(data, source=str(path))


# ---------------------------------------------------------------------------
# Contract registry loader (Task 9, design decision #8 amended by B3)
# ---------------------------------------------------------------------------
#
# Loads + validates a per-chain contract registry mapping known reward
# distributors / DEX routers / rebate routers to a ``kind`` tag and an
# OPTIONAL ``operator_country`` (ISO-3166 alpha-2) + ``citation`` URL.
#
# This loader is LOADING + VALIDATION only; no classification logic. The
# processor (Task 9, ``berachain_processor``) owns classification.
#
# Attacker F1 mitigation: ``operator_country`` is validated against a CLOSED
# ISO-3166 alpha-2 enum and a ``citation`` URL is REQUIRED whenever
# ``operator_country`` is present (a per-contract country override is a
# powerful claim - it must be backed by a citable primary source). Invalid
# or uncited -> :class:`ConfigurationError` (fail-loud).
#
# B3: Berachain ships EMPTY ``operator_country`` for every contract; all
# Berachain rewards resolve via the chain-level VG (British Virgin Islands)
# in :mod:`operator_origin`. A per-contract override requires a PRIMARY
# source stronger than the chain-level mapping; secondary sources (exchange
# whitepapers) do not qualify.

# Max size of a contracts.json file (1 MiB). The curated registry is bounded
# by the number of known protocols/contracts (low hundreds).
_MAX_CONTRACTS_FILE_SIZE = 1 * 1024 * 1024

# Allowed ``kind`` tags. Closed set: the processor branches on these.
# Extending the set is a deliberate act (add the tag here AND wire a branch
# in the processor). ``self_wallet`` (C3, validation-harness plan Task 8)
# marks the tracked wallet's OTHER own wallets so self-transfers classify
# as Transfer, not Reward/spam or Unknown.
_CONTRACT_KINDS: tuple[str, ...] = (
    "dex_router",
    "reward_distributor",
    "rebate_router",
    "self_wallet",
)


def _validate_citation(entry: dict[str, object], source: str, index: int) -> str | None:
    """Validate the optional ``citation`` URL field.

    ``citation`` is OPTIONAL in general, but REQUIRED when
    ``operator_country`` is set (the loader checks that pairing in
    :func:`_build_contract_entry`). When present, it must be a non-empty
    string starting with ``http://`` or ``https://`` (a bare domain or a
    relative path is not a citable URL).
    """
    citation = entry.get("citation")
    if citation is None:
        return None
    if not isinstance(citation, str) or not citation.strip():
        raise ConfigurationError(
            f"Contract registry entry at index {index} 'citation' must be a "
            f"non-empty string when present: {source}"
        )
    cleaned = citation.strip()
    if not (cleaned.startswith("http://") or cleaned.startswith("https://")):
        raise ConfigurationError(
            f"Contract registry entry at index {index} 'citation' must be an "
            f"http(s) URL, got {cleaned!r}: {source}"
        )
    return cleaned


def _build_contract_entry(
    entry: dict[str, object], index: int, source: str
) -> tuple[str, ContractEntry]:
    """Validate one contract entry; return ``(lower_addr, entry)``.

    Required: non-empty ``address`` (str), ``kind`` in
    :data:`_CONTRACT_KINDS`. Optional: ``label``, ``protocol``,
    ``operator_country`` (validated against the closed ISO-3166 enum),
    ``citation`` (required when ``operator_country`` is set). Fail-loud via
    :class:`ConfigurationError` / :class:`FileProcessingError`.
    """
    if not isinstance(entry, dict):
        raise FileProcessingError(
            f"Contract registry entry at index {index} must be a JSON "
            f"object, got {type(entry).__name__}: {source}"
        )
    addr = entry.get("address")
    if not isinstance(addr, str) or not addr.strip():
        raise ConfigurationError(
            f"Contract registry entry at index {index} has a null/invalid "
            f"'address' (must be a non-empty string): {source}"
        )
    addr_lower = addr.strip().lower()

    kind = entry.get("kind")
    if not isinstance(kind, str) or kind not in _CONTRACT_KINDS:
        raise ConfigurationError(
            f"Contract registry entry at index {index} 'kind' must be one of "
            f"{list(_CONTRACT_KINDS)}, got {kind!r}: {source}"
        )

    label = entry.get("label")
    if label is not None and not isinstance(label, str):
        raise ConfigurationError(
            f"Contract registry entry at index {index} 'label' must be a "
            f"string: {source}"
        )
    protocol = entry.get("protocol")
    if protocol is not None and not isinstance(protocol, str):
        raise ConfigurationError(
            f"Contract registry entry at index {index} 'protocol' must be a "
            f"string: {source}"
        )

    operator_country = entry.get("operator_country")
    citation = _validate_citation(entry, source, index)
    if operator_country is not None:
        # Attacker F1: validate against the closed ISO-3166 enum AND require
        # a citation URL when a per-contract country override is claimed.
        if not isinstance(operator_country, str) or not operator_country.strip():
            raise ConfigurationError(
                f"Contract registry entry at index {index} 'operator_country' "
                f"must be a non-empty ISO-3166 alpha-2 string when present: "
                f"{source}"
            )
        country = operator_country.strip().upper()
        if not _is_valid_iso3166_alpha2(country):
            raise ConfigurationError(
                f"Contract registry entry at index {index} 'operator_country' "
                f"{country!r} is not a valid ISO-3166 alpha-2 code: {source}"
            )
        if citation is None:
            raise ConfigurationError(
                f"Contract registry entry at index {index} sets "
                f"'operator_country'={country!r} but provides no 'citation' "
                f"URL; a per-contract country override requires a citable "
                f"primary source: {source}"
            )
        operator_country = country
    elif citation is not None:
        # A citation without an operator_country is meaningless; reject so
        # the registry author notices the dangling field.
        raise ConfigurationError(
            f"Contract registry entry at index {index} provides 'citation' "
            f"but no 'operator_country'; citation is only meaningful with an "
            f"operator_country override: {source}"
        )

    return addr_lower, ContractEntry(
        address=addr_lower,
        label=label,
        kind=kind,
        protocol=protocol,
        operator_country=operator_country,
        citation=citation,
    )


def build_contract_registry(data: object, *, source: str) -> ContractRegistry:
    """Validate an in-memory registry dict and build a :class:`ContractRegistry`.

    Schema:
        - ``chain``: optional informational string.
        - ``contracts``: list of objects each with a non-null ``address``
          (str) and a ``kind`` in :data:`_CONTRACT_KINDS`. ``label`` /
          ``protocol`` are optional informational tags. ``operator_country``
          (ISO-3166 alpha-2) is OPTIONAL and REQUIRES a ``citation`` URL
          when present (Attacker F1).

    Args:
        data: The parsed JSON value (a dict).
        source: Marker for error messages (file path or ``"<inline-test>"``).

    Returns:
        The validated :class:`ContractRegistry`.

    Raises:
        FileProcessingError: If a contract entry is not a JSON object.
        ConfigurationError: If schema validation fails (missing required
            field, null address, invalid kind, invalid/uncited
            operator_country).
    """
    if not isinstance(data, dict):
        raise ConfigurationError(
            f"Contract registry must be a JSON object, got "
            f"{type(data).__name__}: {source}"
        )
    chain = data.get("chain")
    if chain is not None and not isinstance(chain, str):
        raise ConfigurationError(
            f"Contract registry 'chain' must be a string: {source}"
        )
    if "contracts" not in data:
        raise ConfigurationError(
            f"Contract registry must contain a 'contracts' key: {source}"
        )
    raw_contracts = data["contracts"]
    if not isinstance(raw_contracts, list):
        raise ConfigurationError(
            f"Contract registry 'contracts' must be a list, got "
            f"{type(raw_contracts).__name__}: {source}"
        )
    contracts: dict[str, ContractEntry] = {}
    for index, entry in enumerate(raw_contracts):
        addr_lower, contract_entry = _build_contract_entry(entry, index, source)
        # First occurrence wins; later duplicates are ignored (no overwrite of
        # a primary entry by a stale one) - mirrors the LP snapshot policy.
        contracts.setdefault(addr_lower, contract_entry)
    return ContractRegistry(
        chain=chain, contracts=contracts, source=source
    )


def _contracts_on_error(failed_path: Path, kind: str, detail: str) -> object:
    """Policy callback for the contract registry loader.

    A *missing* registry is a hard error (the orchestrator selects the file
    per chain; a missing file for a chain that is being processed is a
    configuration failure). Every other kind raises
    :class:`FileProcessingError`.
    """
    if kind == "missing":
        return DEGRADED
    if kind == "symlink":
        raise FileProcessingError(
            f"Contract registry at {failed_path} is a symlink - "
            "only regular files are accepted for security"
        )
    if kind == "oversize":
        raise FileProcessingError(
            f"Contract registry exceeds size limit ({detail}): {failed_path}"
        )
    if kind == "stat_error":
        raise FileProcessingError(
            f"Could not stat contract registry {failed_path}: {detail}"
        )
    if kind == "invalid_json":
        raise FileProcessingError(
            f"Contract registry {failed_path} contains invalid JSON: {detail}"
        )
    raise FileProcessingError(
        f"Contract registry {failed_path} failed to load ({kind}): {detail}"
    )


def load_contracts(path: Path) -> ContractRegistry:
    """Load + schema-validate the per-chain contract registry at ``path``.

    Runs the mechanical file guards via :func:`load_guarded_json` (symlink,
    size cap, JSON parse), then :func:`build_contract_registry` for schema
    validation (including the Attacker-F1 closed-ISO-3166-enum +
    citation-required checks on ``operator_country``).

    Args:
        path: Absolute path to ``<chain>_contracts.json``.

    Returns:
        The validated :class:`ContractRegistry`.

    Raises:
        FileProcessingError: If the file is a symlink / oversize / malformed
            JSON / missing-but-not-degraded, or a contract entry is not a
            JSON object.
        ConfigurationError: If schema validation fails (missing required
            field, null address, invalid kind, invalid/uncited
            operator_country).
    """
    data = load_guarded_json(
        path, size_limit=_MAX_CONTRACTS_FILE_SIZE, on_error=_contracts_on_error
    )
    if data is DEGRADED:
        # Missing registry is a hard error: the orchestrator selected this
        # file for a chain being processed; a missing file is a configuration
        # failure (not a degrade-and-continue case).
        raise FileProcessingError(
            f"Contract registry not found (expected at {path})"
        )
    return build_contract_registry(data, source=str(path))


# ---------------------------------------------------------------------------
# Position-token registry per-year loader
# ---------------------------------------------------------------------------
#
# Single construction site for the per-year ``bera_position_tokens.json``
# filename + resolution block. Both the on-chain fetcher (nfttx decode
# gating) and the TH substituter (processor wiring) call this facade, so a
# rename or relocation of the registry file edits ONE literal (the drift
# class ``application.paths`` already removed for the root/resolve helpers).


def load_position_token_registry_for_year(
    year: int,
    override: Path | None = None,
    repo_root: Path | None = None,
) -> PositionTokenRegistry:
    """Resolve + load the per-year position-token registry.

    Resolution order (first match wins), via
    :func:`tax_reporting.application.paths.resolve_registry_path`:
    ``override`` (tests inject the committed ``example/`` template so they
    never read gitignored personal data), then
    ``resources/source/<year>/bera_position_tokens.json`` (the per-user
    gitignored override), then the committed
    ``resources/source/example/<year>/`` template. The underlying loader
    (:func:`tax_reporting.infrastructure.on_chain.position_token_registry.load_position_token_registry`)
    DEGRADES to an empty registry + WARNING when the resolved file is absent
    (a fresh clone must not abort); every other failure raises.

    Args:
        year: Four-digit fiscal year (e.g. ``2025``).
        override: Explicit registry path (the substituter's ctor kwarg;
            ``None`` in production).
        repo_root: Repository root (the caller's resolved root when it
            already holds one; resolved here when ``None``).

    Returns:
        The validated :class:`PositionTokenRegistry`.

    Raises:
        FileProcessingError: Symlink / oversize / invalid JSON.
        ConfigurationError: Schema validation failure.
    """
    return load_position_token_registry(
        resolve_registry_path(
            year,
            _POSITION_TOKEN_REGISTRY_FILENAME,
            override,
            repo_root if repo_root is not None else find_repository_root(),
        )
    )
