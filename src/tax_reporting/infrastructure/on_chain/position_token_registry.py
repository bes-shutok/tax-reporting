"""Position-token registry: address-keyed LST / staking-position allowlist.

Implements the 2026-08-22 unknown-classifier plan (Task 3): Task 1's on-chain
ground-truth investigation routed the iBGT pure-outflow cluster to verdict B
(nothing received on-chain) and confirmed that LST / staking-position receipt
tokens (LBGT, iBGT, the Kodiak position NFT) have NO identity registry today -
unlike island/vault tokens, which are LP-snapshot members. The pure-outflow
classifier rule for those tokens therefore gates on THIS registry
(address-keyed membership, never asset-name matching - Design Invariant
"Address-keyed identity").

The registry mirrors the LP-snapshot pattern
(``resources/source/<year>/berachain_lp_snapshot.json``): a per-user
GITIGNORED JSON file carrying provenance metadata, with a committed synthetic
template under ``resources/source/example/<year>/`` for tests and fresh
clones. The loader lives here (its own single-concern sibling module, the
same separation ``lp_autodiscovery.py`` uses) so the processor stays pure.

Schema::

    {
      "_comment": "...",            # optional
      "as_of_date": "2026-08-22",   # optional provenance tag
      "provenance": "...",          # optional provenance tag
      "tokens": [                   # REQUIRED
        {
          "token_address": "0x...", # REQUIRED non-empty string
          "label": "iBGT",          # optional informational
          "kind": "lst",            # optional: "lst" | "position_nft" (gates is_position_vault)
          "provenance": "..."       # optional per-entry provenance
        },
        ...
      ]
    }

Degradation policy: a MISSING registry file degrades to an EMPTY registry +
WARNING (LST outflows then fall to the terminal ``Event(Unknown) + review``
fallback - fail-loud, never a guess). Every other failure (symlink, invalid
JSON, schema violation) raises.
"""

from __future__ import annotations

import dataclasses
import json
import logging
from pathlib import Path
from typing import Final

from tax_reporting.domain.exceptions import ConfigurationError, FileProcessingError

_LOGGER = logging.getLogger(__name__)

# Size cap for the registry file (mirrors the guarded-JSON loaders' policy;
# the registry is a hand-curated allowlist of a handful of tokens).
_MAX_REGISTRY_SIZE_BYTES: Final = 256 * 1024

# Closed set of behavioral ``kind`` values (review r2 F1): ``is_position_vault``
# matches only the exact literal ``"position_nft"``, so a spelling variant must
# fail LOUDLY at load time rather than silently disabling the recipient rule.
_POSITION_TOKEN_KINDS: Final = ("lst", "position_nft")


@dataclasses.dataclass(frozen=True)
class PositionTokenEntry:
    """One registry member: a position/LST token address + provenance.

    Attributes:
        token_address: The member address, lower-cased.
        label: Informational label (e.g. ``"iBGT"``); never used for
            matching (address-keyed identity).
        kind: Kind tag (``"lst"`` or ``"position_nft"``). BEHAVIORAL for
            the recipient rule: ``is_position_vault`` matches only
            ``"position_nft"`` entries (review r1 F3); ``is_position_token``
            (the token rule) accepts any kind.
        provenance: Per-entry provenance (which cluster/routing decision
            added the token).
    """

    token_address: str
    label: str | None = None
    kind: str | None = None
    provenance: str | None = None


@dataclasses.dataclass(frozen=True)
class PositionTokenRegistry:
    """An immutable address-keyed allowlist of position/LST tokens.

    Attributes:
        tokens: ``{lower-cased address: entry}``.
        source: Provenance marker (file path or ``"<inline-test>"``).
    """

    tokens: dict[str, PositionTokenEntry]
    source: str

    def is_position_token(self, address: str) -> bool:
        """Return True iff ``address`` (any case) is a registry member.

        Membership of ANY kind: this is the TOKEN-contract predicate (the
        classifier's member-token rule). For the RECIPIENT predicate (the
        position-NFT vault a deposit routes through), use
        :meth:`is_position_vault` - review r1 F3: one address set must not
        silently serve two different semantics.
        """
        return address.lower() in self.tokens

    def is_position_vault(self, address: str) -> bool:
        """Return True iff ``address`` is a ``kind="position_nft"`` member.

        The kind-gated RECIPIENT predicate (review r1 F3): the classifier's
        recipient rule routes deposits through position-NFT vault contracts,
        so only vault-kind entries match. An ``kind="lst"`` entry (a
        tradable staking receipt token, a normal direct-interaction target)
        or an entry without a ``kind`` never matches here, keeping the token
        rule and the recipient rule distinct predicates over one address set.
        """
        entry = self.tokens.get(address.lower())
        return entry is not None and entry.kind == "position_nft"


def build_position_token_registry(data: object, *, source: str) -> PositionTokenRegistry:
    """Validate an in-memory registry dict and build a :class:`PositionTokenRegistry`.

    Args:
        data: The parsed JSON value (must be a dict with a ``tokens`` list).
        source: Marker for error messages (file path or ``"<inline-test>"``).

    Returns:
        The validated registry (addresses lower-cased; first occurrence
        wins on duplicates).

    Raises:
        ConfigurationError: If the shape is invalid (not an object, no
            ``tokens`` list, an entry missing ``token_address``, or an
            optional field of the wrong type, or a ``kind`` outside the
            closed set ``("lst", "position_nft")``). Fail-loud.
    """
    if not isinstance(data, dict):
        raise ConfigurationError(
            f"Position-token registry must be a JSON object, got "
            f"{type(data).__name__}: {source}"
        )
    raw_tokens = data.get("tokens")
    if raw_tokens is None:
        raise ConfigurationError(
            f"Position-token registry is missing required field 'tokens': {source}"
        )
    if not isinstance(raw_tokens, list):
        raise ConfigurationError(
            f"Position-token registry 'tokens' must be a list, got "
            f"{type(raw_tokens).__name__}: {source}"
        )
    tokens: dict[str, PositionTokenEntry] = {}
    for index, entry in enumerate(raw_tokens):
        addr_lower, token_entry = _build_entry(entry, index, source)
        # First occurrence wins; later duplicates are ignored (same policy
        # as the LP snapshot loader).
        tokens.setdefault(addr_lower, token_entry)
    return PositionTokenRegistry(tokens=tokens, source=source)


def _build_entry(
    entry: object, index: int, source: str
) -> tuple[str, PositionTokenEntry]:
    """Validate one registry token entry; return ``(lower_addr, entry)``."""
    if not isinstance(entry, dict):
        raise ConfigurationError(
            f"Position-token registry entry at index {index} must be a JSON "
            f"object, got {type(entry).__name__}: {source}"
        )
    addr = entry.get("token_address")
    if not isinstance(addr, str) or not addr:
        raise ConfigurationError(
            f"Position-token registry entry at index {index} has a "
            f"null/invalid 'token_address' (must be a non-empty string): {source}"
        )
    optional: dict[str, str | None] = {}
    for field in ("label", "kind", "provenance"):
        value = entry.get(field)
        if value is not None and not isinstance(value, str):
            raise ConfigurationError(
                f"Position-token registry entry at index {index} '{field}' "
                f"must be a string: {source}"
            )
        optional[field] = value
    kind = optional["kind"]
    if kind is not None and kind not in _POSITION_TOKEN_KINDS:
        # Review r2 F1: a typo'd kind (e.g. "vault") would load cleanly and
        # silently disable the kind-gated vault-recipient rule; fail instead.
        raise ConfigurationError(
            f"Position-token registry entry at index {index} has an unknown "
            f"'kind' {kind!r} (must be one of {_POSITION_TOKEN_KINDS} or "
            f"absent): {source}"
        )
    addr_lower = addr.lower()
    return addr_lower, PositionTokenEntry(
        token_address=addr_lower,
        label=optional["label"],
        kind=optional["kind"],
        provenance=optional["provenance"],
    )


def load_position_token_registry(path: Path) -> PositionTokenRegistry:
    """Load + validate the position-token registry at ``path``.

    A MISSING file degrades to an EMPTY registry + WARNING (the classifier's
    Unknown fallback then handles LST outflows fail-loud). A symlink, an
    oversize file, or invalid JSON/Schema raises.

    Args:
        path: Path to ``bera_position_tokens.json``.

    Returns:
        The validated :class:`PositionTokenRegistry`.

    Raises:
        FileProcessingError: Symlink / oversize / invalid JSON.
        ConfigurationError: Schema validation failure.
    """
    if path.is_symlink():
        raise FileProcessingError(
            f"Position-token registry at {path} is a symlink - "
            "only regular files are accepted for security"
        )
    if not path.is_file():
        _LOGGER.warning(
            "No position-token registry at %s; LST/position-token outflows "
            "will classify Event(Unknown) + review (add the registry file to "
            "enable vault-deposit classification for them)",
            path,
        )
        return PositionTokenRegistry(tokens={}, source=str(path))
    size = path.stat().st_size
    if size > _MAX_REGISTRY_SIZE_BYTES:
        raise FileProcessingError(
            f"Position-token registry exceeds size limit ({size} bytes): {path}"
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise FileProcessingError(
            f"Position-token registry {path} contains invalid JSON: {exc}"
        ) from exc
    return build_position_token_registry(data, source=str(path))
