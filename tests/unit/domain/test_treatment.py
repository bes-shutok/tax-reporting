"""Tests for the ``Treatment`` enum (Phase B Task 1).

Phase B introduces a closed six-value ``Treatment`` enum that classifies what a
Transaction History (TH) row *is* for tax purposes. This file pins the closed
membership, stable snake-case values, value lookup semantics, and the absence
of optional/sentinel members.

Plan: ``docs/history/plans/2026-07-06-th-tx-view-phase-b.md`` (Task 1).
RFC: ``docs/history/context/2026-06-20-th-anchored-transaction-state-machine.md``.
"""

from __future__ import annotations

import pytest

from tax_reporting.domain.treatment import Treatment


class TestTreatment:
    def test_six_members_exactly(self) -> None:
        # Invariant 1: closed enum with exactly these six members.
        assert set(Treatment) == {
            Treatment.SPOT_DISPOSAL,
            Treatment.PAYMENT,
            Treatment.LOAN_REPAYMENT,
            Treatment.DERIVATIVES_CLOSE,
            Treatment.REWARD_AIRDROP_LP,
            Treatment.OTHER,
        }

    def test_member_values_are_unique_stable_strings(self) -> None:
        # Invariant 1: stable snake-case string values, unique across members.
        expected = {
            "spot_disposal",
            "payment",
            "loan_repayment",
            "derivatives_close",
            "reward_airdrop_lp",
            "other",
        }
        actual = {member.value for member in Treatment}
        assert actual == expected
        # Each value matches the specific member it is assigned to.
        assert Treatment.SPOT_DISPOSAL.value == "spot_disposal"
        assert Treatment.PAYMENT.value == "payment"
        assert Treatment.LOAN_REPAYMENT.value == "loan_repayment"
        assert Treatment.DERIVATIVES_CLOSE.value == "derivatives_close"
        assert Treatment.REWARD_AIRDROP_LP.value == "reward_airdrop_lp"
        assert Treatment.OTHER.value == "other"

    def test_enum_lookup_by_value_round_trip(self) -> None:
        # Value-based lookup round-trips to the same member.
        assert Treatment("payment") is Treatment.PAYMENT
        assert Treatment.PAYMENT.value == "payment"

    def test_unknown_value_raises_value_error(self) -> None:
        # Invariant 1: unknown values must raise ValueError (closed enum).
        with pytest.raises(ValueError, match="nonsense"):
            Treatment("nonsense")

    def test_no_optional_no_sentinel_members(self) -> None:
        # Invariant 1 + 2: no NONE/UNKNOWN/UNCLASSIFIED sentinel members.
        # OTHER is the explicit landing for unmatched rows; a sentinel member
        # would collide with that role.
        member_names = {member.name for member in Treatment}
        assert "UNCLASSIFIED" not in member_names
        assert "NONE" not in member_names
