"""Bridged-asset registry: address-keyed bridge-issued token allowlist.

Implements the 2026-08-26 bridge-asset registry-gate plan: the processor's
zero-address-mint discriminator (a pure inflow whose leg was issued by the
zero address) previously classified EVERY such mint ``Reward``/``bridge``;
the registry adds the trusted-mint allowlist. A zero-address mint of a
MEMBER token keeps today's behavior (``Reward``/``SubType.bridge``, Tag
``Bridge``, the existing bridge review reason); a NON-member (or an empty
registry) classifies ``Reward``/``SubType.spam`` + review with a
mint-specific reason naming the unregistered token (nothing silently
clean).

GUARD structure mirrors :mod:`position_token_registry` (the C8 precedent):
symlink -> ``FileProcessingError``; oversize -> ``FileProcessingError``;
invalid JSON -> ``FileProcessingError``; schema violation ->
``ConfigurationError``; missing file -> EMPTY registry + actionable WARNING
naming the spam consequence. The JSON vocabulary is pinned and
DELIBERATELY DIFFERS from C8's (plan review r1-F4 one pinned vocabulary;
r9-F1 anti-mirror note)::

    {
        "source": "...",  # REQUIRED non-empty registry-level provenance
        "0x<token>": {  # entries: object keyed by address (case-normalized
                         # to lowercase at load; duplicate keys resolve
                         # last-wins per json.loads)
            "note": "..."  # optional derivation-evidence note; informational-only
        },
    }

No other keys validate. Ownership (2026-08-27 plan amendment): the
COMMITTED ``resources/source/example/<year>/bera_bridged_assets.json`` is
the canonical curated registry of PUBLIC canonical token contracts
(production data, not a synthetic template); an OPTIONAL gitignored user
file ``resources/source/<year>/bera_bridged_assets.json`` SHADOWS it as an
escape hatch for entries not yet committed. Public assets never require a
user file.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import re
from pathlib import Path
from typing import Final

from tax_reporting.domain.exceptions import ConfigurationError, FileProcessingError

_LOGGER = logging.getLogger(__name__)

# Size cap for the registry file (mirrors the guarded-JSON loaders' policy;
# the registry is a hand-curated allowlist of a handful of tokens).
_MAX_REGISTRY_SIZE_BYTES: Final = 256 * 1024

# Entry keys must be EVM token-contract addresses (review r1 F7): a ticker or a
# 39-hex typo can never match a leg token address, so it would silently
# disable that entry's bridge classification with no load-time signal.
_ADDRESS_KEY_PATTERN: Final = re.compile(r"0x[0-9a-f]{40}")


@dataclasses.dataclass(frozen=True)
class BridgedAssetRegistry:
    """An immutable address-keyed allowlist of bridge-issued token contracts.

    Attributes:
        tokens: ``{lower-cased token address: note or None}``. Note values
            are INFORMATIONAL-ONLY (derivation evidence for the curator);
            classification consults membership alone, never the note text.
        source: Provenance marker (file path or ``"<inline-test>"``).
    """

    tokens: dict[str, str | None]
    source: str

    def is_bridged_asset(self, address: str) -> bool:
        """Return True iff ``address`` (any case) is a registry member.

        Membership is case-normalized: registries store the lowercased
        address while legs may carry the checksummed form.
        """
        return address.lower() in self.tokens


def build_bridged_asset_registry(data: object, *, source: str) -> BridgedAssetRegistry:
    """Validate an in-memory registry dict and build a :class:`BridgedAssetRegistry`.

    Args:
        data: The parsed JSON value. Must be an object with a REQUIRED
            non-empty ``source`` provenance string; every OTHER key is a
            token address (lowercased) whose value is an object with an
            optional ``note`` string. No other keys or shapes validate.
        source: Marker for error messages (file path or ``"<inline-test>"``).

    Returns:
        The validated registry (entry keys lowercased). Duplicate keys in
        the JSON source resolve LAST-wins (``json.loads`` semantics - the
        parser collapses duplicate object keys before this function sees
        them; review r1 F11).

    Raises:
        ConfigurationError: If the shape is invalid (not an object, a
            missing/empty/non-string ``source``, an entry key that is not a
            ``0x`` + 40-hex token address, an entry value that is not a
            JSON object, or a ``note`` that is not a string).
    """
    if not isinstance(data, dict):
        raise ConfigurationError(f"Bridged-asset registry must be a JSON object, got {type(data).__name__}: {source}")
    provenance = data.get("source")
    if not isinstance(provenance, str) or not provenance.strip():
        raise ConfigurationError(
            f"Bridged-asset registry is missing the required non-empty 'source' provenance string: {source}"
        )
    tokens: dict[str, str | None] = {}
    for key, value in data.items():
        if key == "source":
            continue
        # Review r1 F7 + r2 F8: reject non-address keys (tickers, typos,
        # the empty string - JSON object keys are always str) at load time;
        # they can never match a leg token address and would silently
        # disable the entry's bridge classification.
        key_lower = key.lower()
        if not _ADDRESS_KEY_PATTERN.fullmatch(key_lower):
            raise ConfigurationError(
                f"Bridged-asset registry entry key must be a 0x + 40-hex token "
                f"contract address, got {key!r}: {source}"
            )
        if not isinstance(value, dict):
            raise ConfigurationError(
                f"Bridged-asset registry entry {key} must be a JSON object "
                f"(with an optional 'note' string), got "
                f"{type(value).__name__}: {source}"
            )
        unexpected = set(value) - {"note"}
        if unexpected:
            raise ConfigurationError(
                f"Bridged-asset registry entry {key} has unknown field(s) "
                f"{sorted(unexpected)} (only 'note' is allowed): {source}"
            )
        note = value.get("note")
        if note is not None and not isinstance(note, str):
            raise ConfigurationError(f"Bridged-asset registry entry {key} 'note' must be a string: {source}")
        # Duplicate keys resolve last-wins (authoritative statement in the
        # build docstring; review r1 F11).
        tokens[key_lower] = note
    return BridgedAssetRegistry(tokens=tokens, source=source)


def load_bridged_asset_registry(path: Path) -> BridgedAssetRegistry:
    """Load + validate the bridged-asset registry at ``path``.

    A MISSING file degrades to an EMPTY registry + WARNING naming the spam
    consequence (zero-address mints then classify ``spam`` + review - never
    a silent bridge). A symlink, an oversize file, or invalid JSON/schema
    raises.

    Args:
        path: Path to ``bera_bridged_assets.json``.

    Returns:
        The validated :class:`BridgedAssetRegistry`.

    Raises:
        FileProcessingError: Symlink / oversize / invalid JSON.
        ConfigurationError: Schema validation failure.
    """
    if path.is_symlink():
        raise FileProcessingError(
            f"Bridged-asset registry at {path} is a symlink - only regular files are accepted for security"
        )
    if not path.is_file():
        _LOGGER.warning(
            "No bridged-asset registry at %s; zero-address mints will "
            "classify Reward/spam + review (add the registry file to keep "
            "trusted bridge mints classifying bridge)",
            path,
        )
        return BridgedAssetRegistry(tokens={}, source=str(path))
    size = path.stat().st_size
    if size > _MAX_REGISTRY_SIZE_BYTES:
        raise FileProcessingError(f"Bridged-asset registry exceeds size limit ({size} bytes): {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise FileProcessingError(f"Bridged-asset registry {path} contains invalid JSON: {exc}") from exc
    return build_bridged_asset_registry(data, source=str(path))
