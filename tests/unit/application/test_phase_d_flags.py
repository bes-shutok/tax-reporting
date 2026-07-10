"""Phase D Task 2 - six per-treatment resolver flags on ``TaxJurisdictionConfig``.

Pins the 1:1 mapping of the six ``Treatment`` members to six
``treatment_*_via_resolver`` boolean flags (Invariant 2), the default-ON
landing state (Invariant 3), and the TOML-dataclass sync plus required-
presence loader guard (Invariant 10).

The required-presence guard exists because the loader's bool-default
``setdefault(flag_name, False)`` would silently revert a treatment to the
legacy adapter if its flag were absent from a future-year TOML - the guard
raises ``ConfigurationError`` instead, naming the missing flag.
"""

from __future__ import annotations

import dataclasses
import logging
import tomllib

import pytest

from tax_reporting.domain.exceptions import ConfigurationError
from tax_reporting.domain.jurisdiction import TaxJurisdictionConfig
from tax_reporting.infrastructure import config as config_module
from tax_reporting.infrastructure.config import _load_tax_jurisdiction_config

# The six per-treatment flags (1:1 with the six Treatment enum members).
_SIX_FLAGS: tuple[str, ...] = (
    "treatment_spot_disposal_via_resolver",
    "treatment_payment_via_resolver",
    "treatment_loan_repayment_via_resolver",
    "treatment_derivatives_close_via_resolver",
    "treatment_reward_airdrop_lp_via_resolver",
    "treatment_other_via_resolver",
)

_REPO_ROOT = config_module._REPO_ROOT
_DECISION_POINTS_TOML = _REPO_ROOT / "docs/maintenance/tax/decision_points/2025.toml"


def _make_cp(country: str = "PT", fiscal_year: str = "2025") -> config_module.configparser.ConfigParser:
    """Build a minimal [TAX JURISDICTION] configparser for the loader."""
    cp = config_module.configparser.ConfigParser()
    cp.optionxform = lambda optionstr: optionstr
    cp["TAX JURISDICTION"] = {"TAX_COUNTRY": country, "FISCAL_YEAR": fiscal_year}
    return cp


def _write_toml(path, content: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "2025.toml").write_text(content, encoding="utf-8")


_MINIMAL_VALID_TOML = (
    '[meta]\nfiscal_year = 2025\nsource_decision_file = "docs/maintenance/tax/decision_points/2025.md"\n'
    'last_verified = "2026-05-26"\n'
)


def _six_flags_block(value: str = "true") -> str:
    """Return the six treatment_*_via_resolver TOML lines with the given bool value."""
    return "".join(f"{name} = {value}\n" for name in _SIX_FLAGS)


@pytest.mark.unit
class TestPhaseDFlags:
    """Pin the six per-treatment resolver flags on TaxJurisdictionConfig."""

    def test_default_flags_all_true(self) -> None:
        """A default-constructed TaxJurisdictionConfig has all six flags True.

        The dataclass fields default to True; constructing without explicitly
        passing them yields True for every treatment_*_via_resolver flag.
        Pins Invariant 3 (default ON at landing).
        """
        config = TaxJurisdictionConfig(
            country="PT",
            fiscal_year=2025,
            exclude_loan_repayment_gains=True,
            zero_basis_review_threshold=__import__("decimal").Decimal("50"),
        )
        for flag_name in _SIX_FLAGS:
            assert getattr(config, flag_name) is True, (
                f"{flag_name} must default to True (Invariant 3)"
            )

    def test_flag_per_treatment_field_exists(self) -> None:
        """dataclasses.fields(TaxJurisdictionConfig) includes all six flag names.

        Pins the 1:1 Treatment-to-flag mapping (Invariant 2): exactly six
        treatment_*_via_resolver fields exist, one per Treatment member.
        """
        field_names = {f.name for f in dataclasses.fields(TaxJurisdictionConfig)}
        for flag_name in _SIX_FLAGS:
            assert flag_name in field_names, (
                f"{flag_name} must exist on TaxJurisdictionConfig (Invariant 2: 1:1 mapping)"
            )

    def test_toml_has_six_entries(self) -> None:
        """The committed 2025.toml has all six entries with ``true`` values.

        Pins Invariant 10 (TOML-dataclass sync): every treatment_*_via_resolver
        flag on the dataclass has a matching entry in the [countries.PT]
        section of the decision-points TOML with the same default (true).
        """
        with _DECISION_POINTS_TOML.open("rb") as f:
            data = tomllib.load(f)
        pt_section = data.get("countries", {}).get("PT", {})
        for flag_name in _SIX_FLAGS:
            assert flag_name in pt_section, (
                f"{flag_name} must exist in [countries.PT] of 2025.toml (Invariant 10)"
            )
            assert pt_section[flag_name] is True, (
                f"{flag_name} in 2025.toml must be `true`, got {pt_section[flag_name]!r}"
            )

    def test_flag_false_restores_legacy(self, tmp_path, monkeypatch) -> None:
        """A config with one flag False returns that flag False, others True.

        The loader reads the per-flag value from the TOML verbatim (no
        normalization), so setting one to ``false`` and the others to ``true``
        yields exactly that distribution on the returned dataclass.
        Pins the rollback mechanism: a single flag set to ``false`` reverts
        ONLY its treatment to the legacy adapter.
        """
        monkeypatch.setattr(config_module, "_DECISION_POINTS_DIR", tmp_path)
        # Build the TOML: first flag false, the other five true.
        body = ""
        for idx, name in enumerate(_SIX_FLAGS):
            value = "false" if idx == 0 else "true"
            body += f"{name} = {value}\n"
        _write_toml(
            tmp_path,
            _MINIMAL_VALID_TOML + "[countries.PT]\nexclude_loan_repayment_gains = true\n" + body,
        )
        cp = _make_cp()
        logger = logging.getLogger(__name__)
        result = _load_tax_jurisdiction_config(cp, logger)
        assert getattr(result, _SIX_FLAGS[0]) is False
        for name in _SIX_FLAGS[1:]:
            assert getattr(result, name) is True

    def test_missing_treatment_flag_in_toml_raises(self, tmp_path, monkeypatch) -> None:
        """A TOML missing one of the six flags raises ConfigurationError naming it.

        The loader's bool-default ``setdefault(flag_name, False)`` would silently
        revert the treatment to legacy if the flag were absent. The required-
        presence guard (analogous to the exclude_loan_repayment_gains check at
        config.py:321-325) must raise ``ConfigurationError`` instead, naming the
        missing flag. Pins r7 Medium #8 / Invariant 10.
        """
        monkeypatch.setattr(config_module, "_DECISION_POINTS_DIR", tmp_path)
        # Omit the first flag; include the other five.
        body = "".join(f"{name} = true\n" for name in _SIX_FLAGS[1:])
        _write_toml(
            tmp_path,
            _MINIMAL_VALID_TOML + "[countries.PT]\nexclude_loan_repayment_gains = true\n" + body,
        )
        cp = _make_cp()
        logger = logging.getLogger(__name__)
        missing_flag = _SIX_FLAGS[0]
        with pytest.raises(ConfigurationError, match=missing_flag):
            _load_tax_jurisdiction_config(cp, logger)
