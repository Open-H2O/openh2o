# SPDX-License-Identifier: AGPL-3.0-or-later
"""Vector tests for the pure multi-year carry-over & borrow-forward math.

Like tests/test_banking_math.py and tests/test_precip_math.py, this file is
DELIBERATELY Django-free: accounting/carryover_math.py imports only ``decimal``
plus accounting.banking_math (itself Django-free), so the money-sensitive
year-to-year roll-forward arithmetic gets a real RED->GREEN cycle in bare local
Python on a Mac with neither Django nor Docker. pytest collects it normally in
the ``web`` container too.

The vectors are the SPEC the implementation must satisfy (signed year-end
remainder; surplus aged via the WaterCredit decay, debt carried at full
magnitude; borrow capped at next year's allocation; CA water-year labeling with
a configurable anchor month) — not the implementation's own output.

Run locally (no pytest needed):  python3 tests/test_carryover_math.py
"""
import os
import sys
from decimal import Decimal

# Make ``accounting`` importable when run as a bare script from the repo root.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from accounting.carryover_math import (  # noqa: E402
    available_with_carryover,
    cap_borrow,
    net_carryover,
    water_year_of,
)

TOL = Decimal("0.0001")


def _close(got, expected, tol=TOL):
    return abs(Decimal(got) - Decimal(str(expected))) < tol


# --------------------------------------------------------------------------
# water_year_of — map a YYYY-MM period to its water-year label
# --------------------------------------------------------------------------


def test_wy_ca_anchor_october_start_of_year():
    # CA WY2025 begins Oct 2024; the anchor month rolls the label forward.
    assert water_year_of("2024-10") == 2025


def test_wy_ca_anchor_december_still_prior_calendar_year():
    assert water_year_of("2024-12") == 2025


def test_wy_ca_anchor_january_belongs_to_same_wy():
    # Jan 2025 is still inside WY2025 (Oct 2024 - Sep 2025).
    assert water_year_of("2025-01") == 2025


def test_wy_ca_anchor_september_is_last_month_of_wy():
    assert water_year_of("2025-09") == 2025


def test_wy_ca_anchor_october_boundary_rolls_to_next_wy():
    # Sep->Oct is the water-year boundary: Oct 2025 opens WY2026.
    assert water_year_of("2025-10") == 2026


def test_wy_calendar_anchor_one_march():
    # anchor_month=1 is a plain calendar year: no forward roll.
    assert water_year_of("2025-03", anchor_month=1) == 2025


def test_wy_calendar_anchor_one_december():
    assert water_year_of("2025-12", anchor_month=1) == 2025


# --------------------------------------------------------------------------
# net_carryover — signed year-end remainder (allocation - usage), 4dp
# --------------------------------------------------------------------------


def test_net_carryover_surplus_is_positive():
    got = net_carryover(Decimal("100"), Decimal("70"))
    assert _close(got, "30"), f"expected 30 surplus, got {got}"
    assert got == Decimal("30.0000"), f"expected 4dp quantize, got {got}"


def test_net_carryover_overdraw_is_negative():
    # Used more than allocated -> debt that borrows against next year.
    got = net_carryover(Decimal("100"), Decimal("130"))
    assert _close(got, "-30"), f"expected -30 debt, got {got}"
    assert got == Decimal("-30.0000"), f"expected 4dp quantize, got {got}"


def test_net_carryover_exactly_used_is_zero():
    got = net_carryover(Decimal("100"), Decimal("100"))
    assert got == Decimal("0.0000"), f"expected 0.0000, got {got}"


def test_net_carryover_zero_allocation_all_usage_is_debt():
    got = net_carryover(Decimal("0"), Decimal("25"))
    assert _close(got, "-25"), f"expected -25, got {got}"


def test_net_carryover_zero_usage_is_full_surplus():
    got = net_carryover(Decimal("80"), Decimal("0"))
    assert _close(got, "80"), f"expected 80, got {got}"


# --------------------------------------------------------------------------
# available_with_carryover — current allocation adjusted by prior carry-over
# --------------------------------------------------------------------------


def test_available_positive_carryover_no_decay():
    got = available_with_carryover(Decimal("100"), Decimal("30"))
    assert _close(got, "130"), f"expected 130, got {got}"
    assert got == Decimal("130.0000"), f"expected 4dp quantize, got {got}"


def test_available_negative_carryover_reduces_budget():
    # A debt cuts this year's budget at FULL magnitude.
    got = available_with_carryover(Decimal("100"), Decimal("-30"))
    assert _close(got, "70"), f"expected 70, got {got}"


def test_available_positive_carryover_is_depreciated():
    # +40 surplus, 50% decay, 1 period -> 20 added: 100 + 20 = 120.
    got = available_with_carryover(
        Decimal("100"), Decimal("40"), Decimal("0.5"), 1
    )
    assert _close(got, "120"), f"expected 120 (surplus aged), got {got}"


def test_available_negative_carryover_is_NOT_depreciated():
    # You don't get to depreciate away a debt: even with a decay rate set,
    # the -30 hits the budget at full magnitude (100 - 30 = 70, not less).
    got = available_with_carryover(
        Decimal("100"), Decimal("-30"), Decimal("0.5"), 3
    )
    assert _close(got, "70"), f"expected 70 (debt undepreciated), got {got}"


def test_available_negative_rate_floored_to_zero():
    # Negative rate must reuse banking_math's 0-floor: behaves like no decay.
    got = available_with_carryover(
        Decimal("100"), Decimal("30"), Decimal("-0.5"), 2
    )
    assert _close(got, "130"), f"expected 130 (rate floored to 0), got {got}"


def test_available_zero_carryover_is_plain_allocation():
    got = available_with_carryover(Decimal("100"), Decimal("0"))
    assert _close(got, "100"), f"expected 100, got {got}"


# --------------------------------------------------------------------------
# cap_borrow — borrow forward cannot exceed next year's allocation
# --------------------------------------------------------------------------


def test_cap_borrow_under_cap_passes_through():
    got = cap_borrow(Decimal("30"), Decimal("100"))
    assert _close(got, "30"), f"expected 30, got {got}"
    assert got == Decimal("30.0000"), f"expected 4dp quantize, got {got}"


def test_cap_borrow_over_cap_is_clamped():
    got = cap_borrow(Decimal("150"), Decimal("100"))
    assert _close(got, "100"), f"expected 100 (capped), got {got}"


def test_cap_borrow_zero_request_is_zero():
    got = cap_borrow(Decimal("0"), Decimal("100"))
    assert got == Decimal("0.0000"), f"expected 0.0000, got {got}"


def test_cap_borrow_negative_request_is_zero():
    # A negative "borrow" is nonsensical -> clamped up to 0.
    got = cap_borrow(Decimal("-20"), Decimal("100"))
    assert got == Decimal("0.0000"), f"expected 0.0000, got {got}"


def test_cap_borrow_exactly_at_cap():
    got = cap_borrow(Decimal("100"), Decimal("100"))
    assert _close(got, "100"), f"expected 100, got {got}"


# --------------------------------------------------------------------------
# bare-Python runner (RED/GREEN without pytest)
# --------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failures = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception as exc:  # noqa: BLE001 — local runner, surface everything
            failures += 1
            print(f"FAIL {t.__name__}: {exc!r}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    sys.exit(1 if failures else 0)
