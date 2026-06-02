# SPDX-License-Identifier: AGPL-3.0-or-later
"""Reference-vector tests for the pure TR-21 effective-precipitation math.

This file is DELIBERATELY Django-free. accounting/precip_math.py imports only
``decimal`` + ``math``, so these tests give a real RED->GREEN cycle in bare local
Python on a Mac that has neither Django nor Docker (all DB tests run on Butler).
It is also collected normally by pytest in the Butler ``web`` container.

The expected values are the published anchor vectors from 38-03-PLAN.md's
reference table (USDA-SCS / TR-21, soil-storage D = 3.0 in), recomputed here as
the spec the implementation must satisfy — not the implementation's own output.

Run locally (no pytest needed):  python3 tests/test_precip_math.py
"""
import os
import sys
from decimal import Decimal

# Make ``accounting`` importable when run as a bare script from the repo root
# (pytest already has the repo on sys.path; this extra entry is harmless there).
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from accounting.precip_math import effective_precip_inches  # noqa: E402

# Tolerance for the usda_scs formula (a transcendental fit, not exact arithmetic).
TOL = Decimal("0.001")


def _close(got, expected, tol=TOL):
    return abs(Decimal(got) - Decimal(str(expected))) < tol


# --------------------------------------------------------------------------
# usda_scs (default) — the contested math
# --------------------------------------------------------------------------


def test_usda_scs_core_formula_no_cap():
    # P=4.0 in, ET=6.0 in -> Pe ~= 1.001 in (core TR-21, neither cap binds)
    got = effective_precip_inches(Decimal("4.0"), Decimal("6.0"), method="usda_scs")
    assert _close(got, "1.001"), f"expected ~1.001, got {got}"


def test_usda_scs_et_cap_binds():
    # P=10.0, ET=2.0 -> raw formula ~= 5.43 but min(Pe, P, ET) caps at ET = 2.000
    got = effective_precip_inches(Decimal("10.0"), Decimal("2.0"), method="usda_scs")
    assert _close(got, "2.000"), f"expected 2.000 (ET cap), got {got}"


def test_usda_scs_zero_floor():
    # P=1.0, ET=6.0 -> 1.25*1 - 2.93 = -1.68 < 0 -> max(0, ...) = 0.000
    got = effective_precip_inches(Decimal("1.0"), Decimal("6.0"), method="usda_scs")
    assert _close(got, "0.000"), f"expected 0.000 (floor), got {got}"


def test_usda_scs_never_exceeds_rainfall_or_et():
    # General invariant across a small grid: capped output <= min(P, ET), >= 0.
    for p in ("0.0", "2.0", "5.0", "12.0"):
        for et in ("0.0", "1.5", "4.0", "9.0"):
            got = effective_precip_inches(Decimal(p), Decimal(et), method="usda_scs")
            assert got >= 0, f"Pe negative for P={p}, ET={et}: {got}"
            assert got <= Decimal(p) + TOL, f"Pe>{p} (rainfall) at ET={et}: {got}"
            assert got <= Decimal(et) + TOL, f"Pe>{et} (ET) at P={p}: {got}"


# --------------------------------------------------------------------------
# raw / fraction
# --------------------------------------------------------------------------


def test_raw_subtracts_all_rainfall():
    got = effective_precip_inches(Decimal("4.0"), Decimal("6.0"), method="raw")
    assert _close(got, "4.000"), f"expected 4.000 (Pe = P), got {got}"


def test_fraction_default_seventy_percent():
    got = effective_precip_inches(
        Decimal("4.0"), Decimal("6.0"), method="fraction", fraction=0.70
    )
    assert _close(got, "2.800"), f"expected 2.800 (0.70*P), got {got}"


def test_fraction_honors_custom_fraction():
    got = effective_precip_inches(
        Decimal("4.0"), Decimal("6.0"), method="fraction", fraction=0.5
    )
    assert _close(got, "2.000"), f"expected 2.000 (0.50*P), got {got}"


# --------------------------------------------------------------------------
# float-bound regression lock (ISS-032b)
# --------------------------------------------------------------------------


def test_usda_scs_stable_at_ledger_resolution():
    # ISS-032: TR-21's core runs in binary float (Decimal has no native
    # fractional power). This locks the bound that makes that safe: the result is
    # deterministic run-to-run and, quantized to the ledger's 1e-4 AF resolution,
    # reproducible — the float error sits far below ledger precision, and min(P,ET)
    # caps it regardless. NOT a behavior change; a regression lock + documented bound.
    ledger = Decimal("0.0001")
    runs = [
        effective_precip_inches(Decimal("4.0"), Decimal("6.0"), method="usda_scs")
        for _ in range(5)
    ]
    assert len(set(runs)) == 1, f"non-deterministic TR-21 output: {set(runs)}"
    q = Decimal(runs[0]).quantize(ledger)
    assert q == Decimal(runs[0]).quantize(ledger)  # quantization is stable
    assert _close(q, "1.001"), f"drifted from published anchor ~1.001: {q}"
    assert Decimal("0") < q <= Decimal("4.0")  # within (0, P], cap holds


# --------------------------------------------------------------------------
# fail loud
# --------------------------------------------------------------------------


def test_unknown_method_raises_valueerror():
    # Use a manual try/except (not pytest.raises) so this file runs under bare
    # Python with no pytest installed — the whole point of the Django-free split.
    raised = False
    try:
        effective_precip_inches(Decimal("4.0"), Decimal("6.0"), method="bogus")
    except ValueError:
        raised = True
    assert raised, "unknown method must raise ValueError, never pass rainfall through"


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
        except Exception as exc:  # noqa: BLE001 — local test runner, surface everything
            failures += 1
            print(f"FAIL {t.__name__}: {exc!r}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    sys.exit(1 if failures else 0)
