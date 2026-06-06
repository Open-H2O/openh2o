# SPDX-License-Identifier: AGPL-3.0-or-later
"""Vector tests for the pure shared-supply apportionment kernel.

Like tests/test_allocation_math.py, tests/test_carryover_math.py, and
tests/test_banking_math.py, this file is DELIBERATELY Django-free:
accounting/allocation_math.py imports only ``decimal`` plus the standard library,
so the money-sensitive split of ONE shared well / point-of-diversion across the
parcels it serves gets a real RED->GREEN cycle in bare local Python on a Mac with
neither Django nor Docker. pytest collects it normally in the ``web``
container too.

This kernel is the heart of Phase 56. The platform currently splits a shared
supply EQUALLY (1/N) — a thirsty vineyard and a low-demand alfalfa field get the
same water. ``apportion_shared_supply`` replaces that with a MEASUREMENT-FIRST
ladder, and the vectors below are the SPEC the implementation must satisfy:

  RUNG 2 (hand-set wins): if a district set ANY member's fraction away from the
    default 1.0 sentinel, the whole group is hand-set — normalize the raw
    fractions and IGNORE ET demand entirely.
  RUNG 3 (ET split): all fractions still the 1.0 sentinel AND some ET demand
    exists -> normalize by demand (the demand-aware split).
  RUNG 4 (even fallback): all fractions 1.0 AND zero total demand -> even split.

Every result sums to EXACTLY 1.0000, with the rounding residual placed on the
last key by sorted str(key) (the create_diversion_ledger_entries convention).
Empty input -> {}. Negative fraction or negative demand fails closed (ValueError)
so a wrong water number can never be produced silently.

Run locally (no pytest needed):  python3 tests/test_apportionment_math.py
"""
import os
import sys
from decimal import Decimal

# Make ``accounting`` importable when run as a bare script from the repo root.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from accounting.allocation_math import apportion_shared_supply  # noqa: E402

TOL = Decimal("0.0001")


def _close(got, expected, tol=TOL):
    return abs(Decimal(got) - Decimal(str(expected))) < tol


def _sum(result):
    return sum(result.values(), Decimal("0"))


class _Stub:
    """A non-int key whose str() is a deterministic name, proving the kernel
    sorts by str(key) rather than assuming integer parcel ids."""

    def __init__(self, name):
        self.name = name

    def __str__(self):
        return self.name


# --------------------------------------------------------------------------
# RUNG 2 — a district hand-set the split: ANY member fraction != the 1.0
# sentinel means the WHOLE group is hand-set. Normalize the raw fractions and
# ignore ET demand, even when demand strongly disagrees.
# --------------------------------------------------------------------------


def test_rung2_handset_fractions_win_over_demand():
    # B is far thirstier (90 vs 10) but the district set 0.6/0.4 by hand, so the
    # demand signal is ignored entirely.
    got = apportion_shared_supply(
        [("A", Decimal("0.6"), Decimal("10")), ("B", Decimal("0.4"), Decimal("90"))]
    )
    assert got == {"A": Decimal("0.6000"), "B": Decimal("0.4000")}, f"got {got}"
    assert _sum(got) == Decimal("1.0000"), f"got {_sum(got)}"


def test_rung2_deliberate_even_is_not_overridden_by_demand():
    # 0.5 != 1.0 is a deliberate human entry, so even though ET says 10:90, the
    # hand-set 50/50 stands.
    got = apportion_shared_supply(
        [("A", Decimal("0.5"), Decimal("10")), ("B", Decimal("0.5"), Decimal("90"))]
    )
    assert got == {"A": Decimal("0.5000"), "B": Decimal("0.5000")}, f"got {got}"


def test_rung2_mixed_one_default_one_handset_treats_whole_group_handset():
    # A still at the 1.0 sentinel, B hand-set to 0.5 -> the presence of ANY
    # non-default fraction makes the whole group hand-set; normalize raw
    # fractions (sum 1.5): A 1.0/1.5=0.6667, B 0.5/1.5=0.3333. Demand ignored.
    got = apportion_shared_supply(
        [("A", Decimal("1.0"), Decimal("10")), ("B", Decimal("0.5"), Decimal("90"))]
    )
    assert got == {"A": Decimal("0.6667"), "B": Decimal("0.3333")}, f"got {got}"
    assert _sum(got) == Decimal("1.0000"), f"got {_sum(got)}"


# --------------------------------------------------------------------------
# RUNG 3 — all fractions are the 1.0 sentinel (untouched) AND ET demand exists:
# normalize by demand so the thirsty crop gets the larger share.
# --------------------------------------------------------------------------


def test_rung3_et_demand_split_when_all_fractions_default():
    # demand {A:30, B:90} -> 1:3, so the vineyard B wins 0.75.
    got = apportion_shared_supply(
        [("A", Decimal("1.0"), Decimal("30")), ("B", Decimal("1.0"), Decimal("90"))]
    )
    assert got == {"A": Decimal("0.2500"), "B": Decimal("0.7500")}, f"got {got}"
    assert _sum(got) == Decimal("1.0000"), f"got {_sum(got)}"


def test_rung3_residual_lands_on_last_key_by_sorted_order():
    # Three equal demands -> each 1/3 = 0.3333, sum 0.9999, residual 0.0001 onto
    # the last key by str order ("C").
    got = apportion_shared_supply(
        [
            ("A", Decimal("1.0"), Decimal("1")),
            ("B", Decimal("1.0"), Decimal("1")),
            ("C", Decimal("1.0"), Decimal("1")),
        ]
    )
    assert got == {"A": Decimal("0.3333"), "B": Decimal("0.3333"), "C": Decimal("0.3334")}, f"got {got}"
    assert _sum(got) == Decimal("1.0000"), f"must sum exactly to 1.0000, got {_sum(got)}"


def test_rung3_residual_int_keys_sort_by_str():
    # Integer parcel ids, inserted out of order; residual lands on 3 ("3" last).
    got = apportion_shared_supply(
        [
            (3, Decimal("1.0"), Decimal("1")),
            (1, Decimal("1.0"), Decimal("1")),
            (2, Decimal("1.0"), Decimal("1")),
        ]
    )
    assert got == {3: Decimal("0.3334"), 1: Decimal("0.3333"), 2: Decimal("0.3333")}, f"got {got}"
    assert _sum(got) == Decimal("1.0000"), f"got {_sum(got)}"


def test_rung3_residual_stub_object_keys_sort_by_str():
    # Non-int keys inserted as zebra, apple, mango; sorted str -> apple, mango,
    # zebra, so the residual lands on zebra. Proves str(key) ordering, not id().
    z, a, m = _Stub("zebra"), _Stub("apple"), _Stub("mango")
    got = apportion_shared_supply(
        [(z, Decimal("1.0"), Decimal("1")), (a, Decimal("1.0"), Decimal("1")), (m, Decimal("1.0"), Decimal("1"))]
    )
    assert got[a] == Decimal("0.3333"), f"got {got[a]}"
    assert got[m] == Decimal("0.3333"), f"got {got[m]}"
    assert got[z] == Decimal("0.3334"), f"residual must land on zebra, got {got[z]}"
    assert _sum(got) == Decimal("1.0000"), f"got {_sum(got)}"


# --------------------------------------------------------------------------
# RUNG 4 — all fractions the 1.0 sentinel AND zero total ET demand: there is no
# signal at all, so fall back to an even 1/N split.
# --------------------------------------------------------------------------


def test_rung4_even_split_when_no_fraction_and_no_demand():
    got = apportion_shared_supply(
        [("A", Decimal("1.0"), Decimal("0")), ("B", Decimal("1.0"), Decimal("0"))]
    )
    assert got == {"A": Decimal("0.5000"), "B": Decimal("0.5000")}, f"got {got}"
    assert _sum(got) == Decimal("1.0000"), f"got {_sum(got)}"


def test_rung4_even_split_three_way_residual():
    # Even fallback across three -> 0.3333 each, residual onto last by str ("C").
    got = apportion_shared_supply(
        [
            ("A", Decimal("1.0"), Decimal("0")),
            ("B", Decimal("1.0"), Decimal("0")),
            ("C", Decimal("1.0"), Decimal("0")),
        ]
    )
    assert got == {"A": Decimal("0.3333"), "B": Decimal("0.3333"), "C": Decimal("0.3334")}, f"got {got}"
    assert _sum(got) == Decimal("1.0000"), f"got {_sum(got)}"


# --------------------------------------------------------------------------
# Single member: takes the whole share regardless of rung (demand or not).
# --------------------------------------------------------------------------


def test_single_member_no_demand_takes_whole_share():
    got = apportion_shared_supply([("A", Decimal("1.0"), Decimal("0"))])
    assert got == {"A": Decimal("1.0000")}, f"got {got}"


def test_single_member_with_demand_takes_whole_share():
    got = apportion_shared_supply([("A", Decimal("1.0"), Decimal("55"))])
    assert got == {"A": Decimal("1.0000")}, f"got {got}"


def test_single_member_handset_fraction_still_takes_whole_share():
    # Even a hand-set lone member normalizes to 1.0 (0.3 / 0.3 == 1).
    got = apportion_shared_supply([("A", Decimal("0.3"), Decimal("0"))])
    assert got == {"A": Decimal("1.0000")}, f"got {got}"


# --------------------------------------------------------------------------
# Empty input: nothing to split -> {} (the caller decides what to do).
# --------------------------------------------------------------------------


def test_empty_members_returns_empty():
    assert apportion_shared_supply([]) == {}, "empty input must yield {}"


# --------------------------------------------------------------------------
# Degenerate hand-set: all fractions deliberately set to 0 -> total weight 0;
# rather than divide by zero, fall back to an even split.
# --------------------------------------------------------------------------


def test_rung2_all_zero_fractions_falls_back_to_even():
    got = apportion_shared_supply(
        [("A", Decimal("0"), Decimal("10")), ("B", Decimal("0"), Decimal("90"))]
    )
    assert got == {"A": Decimal("0.5000"), "B": Decimal("0.5000")}, f"got {got}"


# --------------------------------------------------------------------------
# Validation: fail closed on hostile/garbage input so wrong water numbers can
# never be produced silently.
# --------------------------------------------------------------------------


def _raises(fn):
    try:
        fn()
    except ValueError:
        return True
    except Exception:  # noqa: BLE001 — wrong exception type is still a failure
        return False
    return False


def test_negative_fraction_raises():
    assert _raises(
        lambda: apportion_shared_supply(
            [("A", Decimal("-0.1"), Decimal("10")), ("B", Decimal("0.5"), Decimal("90"))]
        )
    )


def test_negative_demand_raises():
    assert _raises(
        lambda: apportion_shared_supply(
            [("A", Decimal("1.0"), Decimal("-5")), ("B", Decimal("1.0"), Decimal("90"))]
        )
    )


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
