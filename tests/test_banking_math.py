# SPDX-License-Identifier: AGPL-3.0-or-later
"""Vector tests for the pure WaterCredit banking math (depreciation + expiry).

Like tests/test_precip_math.py, this file is DELIBERATELY Django-free:
accounting/banking_math.py imports only ``decimal`` + the standard library, so
the cross-month money math that the bill depends on gets a real RED->GREEN cycle
in bare local Python on a Mac with neither Django nor Docker. pytest collects it
normally in the Butler ``web`` container too.

The vectors are the SPEC the implementation must satisfy (geometric decay
``value = amount * (1 - rate) ** elapsed``, floored at 0; lexicographic "YYYY-MM"
expiry compare) — not the implementation's own output.

Run locally (no pytest needed):  python3 tests/test_banking_math.py
"""
import os
import sys
from decimal import Decimal

# Make ``accounting`` importable when run as a bare script from the repo root.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from accounting.banking_math import (  # noqa: E402
    depreciated_value,
    is_expired,
    periods_between,
)

TOL = Decimal("0.0001")


def _close(got, expected, tol=TOL):
    return abs(Decimal(got) - Decimal(str(expected))) < tol


# --------------------------------------------------------------------------
# depreciated_value — geometric decay, floored at 0
# --------------------------------------------------------------------------


def test_rate_zero_is_unchanged_over_many_periods():
    # No decay: the principal survives intact however long it sits.
    got = depreciated_value(Decimal("100"), Decimal("0"), 6)
    assert _close(got, "100"), f"expected 100 (no decay), got {got}"


def test_elapsed_zero_returns_amount_regardless_of_rate():
    # Deposited this very period: full value, even with a decay rate set.
    got = depreciated_value(Decimal("100"), Decimal("0.10"), 0)
    assert _close(got, "100"), f"expected 100 (elapsed 0), got {got}"


def test_rate_ten_percent_one_period():
    got = depreciated_value(Decimal("100"), Decimal("0.10"), 1)
    assert _close(got, "90"), f"expected 90 (0.9x), got {got}"


def test_rate_ten_percent_two_periods_compounds():
    # Geometric (compound), not linear: 0.9 * 0.9 = 0.81.
    got = depreciated_value(Decimal("100"), Decimal("0.10"), 2)
    assert _close(got, "81"), f"expected 81 (0.81x), got {got}"


def test_rate_one_is_gone_after_one_period():
    got = depreciated_value(Decimal("100"), Decimal("1.0"), 1)
    assert _close(got, "0"), f"expected 0 (rate>=1 dead), got {got}"


def test_value_never_goes_negative():
    # rate > 1 must not produce a negative or oscillating value — floored at 0.
    for elapsed in (1, 2, 3):
        got = depreciated_value(Decimal("100"), Decimal("1.5"), elapsed)
        assert got >= 0, f"negative value at elapsed={elapsed}: {got}"
        assert _close(got, "0"), f"expected 0 (rate>1), got {got}"


# --------------------------------------------------------------------------
# periods_between — whole months between two YYYY-MM strings
# --------------------------------------------------------------------------


def test_periods_between_counts_whole_months():
    assert periods_between("2024-02", "2024-07") == 5


def test_periods_between_same_month_is_zero():
    assert periods_between("2024-06", "2024-06") == 0


def test_periods_between_spans_year_boundary():
    assert periods_between("2023-11", "2024-02") == 3


def test_periods_between_reversed_raises():
    # A current period earlier than the origin is a programming error, not 0.
    raised = False
    try:
        periods_between("2024-07", "2024-02")
    except ValueError:
        raised = True
    assert raised, "reversed periods must raise ValueError"


# --------------------------------------------------------------------------
# is_expired — lexicographic YYYY-MM compare, None = never
# --------------------------------------------------------------------------


def test_none_expiry_never_expires():
    assert is_expired(None, "2099-12") is False


def test_expired_at_the_boundary_month():
    # >= boundary: a credit expiring 2024-06 is dead IN 2024-06.
    assert is_expired("2024-06", "2024-06") is True


def test_not_expired_before_the_boundary():
    assert is_expired("2024-06", "2024-05") is False


def test_expired_after_the_boundary():
    assert is_expired("2024-06", "2024-09") is True


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
