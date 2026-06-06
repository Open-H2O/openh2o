# SPDX-License-Identifier: AGPL-3.0-or-later
"""Vector tests for the pure demand-weighted, efficiency-capped allocation kernel.

Like tests/test_carryover_math.py, tests/test_banking_math.py, and
tests/test_precip_math.py, this file is DELIBERATELY Django-free:
accounting/allocation_math.py imports only ``decimal`` plus the standard library,
so the money-sensitive split of a district delivery total across crop-varied
parcels gets a real RED->GREEN cycle in bare local Python on a Mac with neither
Django nor Docker. pytest collects it normally in the ``web`` container too.

This kernel is the heart of Phase 55: it reframes the throwaway month-axis helper
``_demand_aware_deliveries`` (core/management/commands/seed_merced_ledgers.py) onto
the PARCEL axis as a tested, reusable platform primitive. The vectors below are
the SPEC the implementation must satisfy (ample -> every parcel gets its cap;
short -> the whole delivery split by demand weight; zero demand -> empty; zero
delivery -> a real recorded zero per parcel; exact-sum residual on the last key;
fail-closed validation) — not the implementation's own output.

Run locally (no pytest needed):  python3 tests/test_allocation_math.py
"""
import os
import sys
from decimal import Decimal

# Make ``accounting`` importable when run as a bare script from the repo root.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from accounting.allocation_math import allocate_by_demand  # noqa: E402

TOL = Decimal("0.0001")


def _close(got, expected, tol=TOL):
    return abs(Decimal(got) - Decimal(str(expected))) < tol


def _sum(result):
    return sum(result.values(), Decimal("0"))


# --------------------------------------------------------------------------
# AMPLE delivery (total >= sum of caps): every parcel gets its cap = demand/eff.
# The leftover above sum(caps) is NOT distributed here — it is the recovery-horizon
# surplus Plan 02/03 routes — so the result sums to sum(caps), not delivery_total.
# --------------------------------------------------------------------------


def test_ample_every_parcel_gets_its_cap():
    # demand {A:30, B:10}, eff 0.75 -> caps {A:40, B:13.3333}, sum 53.3333.
    # delivery 100 is ample, so each parcel gets exactly its cap.
    got = allocate_by_demand(Decimal("100"), {"A": Decimal("30"), "B": Decimal("10")}, Decimal("0.75"))
    assert got == {"A": Decimal("40.0000"), "B": Decimal("13.3333")}, f"got {got}"


def test_ample_sums_to_caps_not_delivery_total():
    # The 46.6667 leftover (100 - 53.3333) is intentionally NOT allocated here.
    got = allocate_by_demand(Decimal("100"), {"A": Decimal("30"), "B": Decimal("10")}, Decimal("0.75"))
    assert _close(_sum(got), "53.3333"), f"expected sum 53.3333 (caps), got {_sum(got)}"
    assert _sum(got) != Decimal("100"), "ample must not distribute the leftover"


def test_ample_boundary_exactly_at_sum_of_caps_gives_caps():
    # delivery == sum(caps) is the ample/short boundary; >= takes the ample branch.
    got = allocate_by_demand(Decimal("53.3333"), {"A": Decimal("30"), "B": Decimal("10")}, Decimal("0.75"))
    assert got == {"A": Decimal("40.0000"), "B": Decimal("13.3333")}, f"got {got}"


# --------------------------------------------------------------------------
# SHORT delivery (total < sum of caps): the WHOLE delivery is split by demand
# weight; each parcel stays <= its cap; the result sums EXACTLY to delivery_total.
# --------------------------------------------------------------------------


def test_short_splits_whole_delivery_by_demand_weight():
    # demand {A:30, B:10} -> 3:1 weight. delivery 40 (< 53.3333 sum of caps).
    got = allocate_by_demand(Decimal("40"), {"A": Decimal("30"), "B": Decimal("10")}, Decimal("0.75"))
    assert got == {"A": Decimal("30.0000"), "B": Decimal("10.0000")}, f"got {got}"


def test_short_sums_exactly_to_delivery_total():
    got = allocate_by_demand(Decimal("40"), {"A": Decimal("30"), "B": Decimal("10")}, Decimal("0.75"))
    assert _sum(got) == Decimal("40.0000"), f"short must sum to delivery_total, got {_sum(got)}"


def test_short_each_parcel_stays_at_or_below_its_cap():
    # delivery 26.6667 -> A 20.0, B 6.6667; caps are 40 / 13.3333 so both are under.
    got = allocate_by_demand(Decimal("26.6667"), {"A": Decimal("30"), "B": Decimal("10")}, Decimal("0.75"))
    assert got == {"A": Decimal("20.0000"), "B": Decimal("6.6667")}, f"got {got}"
    assert _sum(got) == Decimal("26.6667"), f"got {_sum(got)}"


# --------------------------------------------------------------------------
# Rounding residual: quantize each short share to 4dp and place the residual
# (delivery_total - sum of rounded shares) on the LAST parcel by sorted str(key),
# so the result sums EXACTLY to delivery_total with no Decimal drift.
# --------------------------------------------------------------------------


def test_short_residual_lands_on_last_key_by_sorted_order():
    # demand {A:1,B:1,C:1}, eff 0.5 -> caps 2 each, sum 6. delivery 1 (short).
    # Each raw share is 1/3 = 0.3333 -> sum 0.9999, residual 0.0001 onto "C".
    got = allocate_by_demand(
        Decimal("1"), {"A": Decimal("1"), "B": Decimal("1"), "C": Decimal("1")}, Decimal("0.5")
    )
    assert got == {"A": Decimal("0.3333"), "B": Decimal("0.3333"), "C": Decimal("0.3334")}, f"got {got}"
    assert _sum(got) == Decimal("1.0000"), f"must sum exactly to delivery_total, got {_sum(got)}"


def test_short_residual_is_key_type_agnostic_int_keys():
    # Integer parcel ids sort by str(key): "1" < "2" < "3", residual onto 3.
    got = allocate_by_demand(Decimal("1"), {1: Decimal("1"), 2: Decimal("1"), 3: Decimal("1")}, Decimal("0.5"))
    assert got == {1: Decimal("0.3333"), 2: Decimal("0.3333"), 3: Decimal("0.3334")}, f"got {got}"
    assert _sum(got) == Decimal("1.0000"), f"got {_sum(got)}"


# --------------------------------------------------------------------------
# ZERO total demand (all zero, or empty dict): return {} — the caller decides
# the fallback (Plan 02 uses the static PointOfDiversionParcel.fraction split).
# --------------------------------------------------------------------------


def test_zero_total_demand_returns_empty():
    got = allocate_by_demand(Decimal("100"), {"A": Decimal("0"), "B": Decimal("0")}, Decimal("0.75"))
    assert got == {}, f"expected empty dict, got {got}"


def test_empty_demand_dict_returns_empty():
    got = allocate_by_demand(Decimal("100"), {}, Decimal("0.75"))
    assert got == {}, f"expected empty dict, got {got}"


# --------------------------------------------------------------------------
# ZERO delivery_total: a recorded zero-delivery month is real data, distinct
# from "no demand" — return every parcel mapped to Decimal("0.0000").
# --------------------------------------------------------------------------


def test_zero_delivery_total_maps_every_parcel_to_zero():
    got = allocate_by_demand(Decimal("0"), {"A": Decimal("30"), "B": Decimal("10")}, Decimal("0.75"))
    assert got == {"A": Decimal("0.0000"), "B": Decimal("0.0000")}, f"got {got}"


# --------------------------------------------------------------------------
# Single parcel: gets its cap (ample) or the whole delivery (short); never crashes.
# --------------------------------------------------------------------------


def test_single_parcel_ample_gets_its_cap():
    got = allocate_by_demand(Decimal("100"), {"A": Decimal("30")}, Decimal("0.75"))
    assert got == {"A": Decimal("40.0000")}, f"got {got}"


def test_single_parcel_short_gets_whole_delivery():
    # delivery 10 < cap 40 -> short -> the lone parcel takes the whole delivery.
    got = allocate_by_demand(Decimal("10"), {"A": Decimal("30")}, Decimal("0.75"))
    assert got == {"A": Decimal("10.0000")}, f"got {got}"


# --------------------------------------------------------------------------
# Efficiency == 1 is the valid boundary (cap == demand, no over-delivery margin).
# --------------------------------------------------------------------------


def test_efficiency_one_cap_equals_demand():
    got = allocate_by_demand(Decimal("100"), {"A": Decimal("30")}, Decimal("1"))
    assert got == {"A": Decimal("30.0000")}, f"got {got}"


# --------------------------------------------------------------------------
# Validation: fail closed on hostile/garbage input so wrong water numbers can
# never be produced silently.
# --------------------------------------------------------------------------


def _raises(fn):
    try:
        fn()
    except ValueError:
        return True
    except Exception as exc:  # noqa: BLE001 — wrong exception type is still a failure
        return False
    return False


def test_efficiency_zero_raises():
    assert _raises(lambda: allocate_by_demand(Decimal("100"), {"A": Decimal("30")}, Decimal("0")))


def test_efficiency_negative_raises():
    assert _raises(lambda: allocate_by_demand(Decimal("100"), {"A": Decimal("30")}, Decimal("-0.5")))


def test_efficiency_above_one_raises():
    assert _raises(lambda: allocate_by_demand(Decimal("100"), {"A": Decimal("30")}, Decimal("1.5")))


def test_negative_delivery_total_raises():
    assert _raises(lambda: allocate_by_demand(Decimal("-5"), {"A": Decimal("30")}, Decimal("0.75")))


def test_negative_demand_raises():
    assert _raises(lambda: allocate_by_demand(Decimal("100"), {"A": Decimal("-5")}, Decimal("0.75")))


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
