# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pure multi-year carry-over & borrow-forward math.

Intentionally Django-free (imports only ``decimal`` + accounting.banking_math,
itself Django-free), the same split that gave 38-03's effective-precip math and
the WaterCredit banking math a real RED->GREEN cycle in bare local Python. This
is the money-sensitive core of multi-year allocations: at each water year's end
the unused budget rolls FORWARD as a surplus (which may depreciate), and an
overdraw becomes a DEBT borrowed against the next year (capped at what that year
actually holds). Get it wrong and an agency is silently misbilled, so it is
proven in isolation here; the DB-bound orchestration (which zone/parcel the
amounts belong to) is deferred to 39-02.

Three deliberate rules, each encoded below:

  1. The year-end remainder is SIGNED: ``allocation - usage``. A positive value
     is surplus that carries forward; a negative value is a debt. One number,
     not two, so a surplus and a debt can never be double-counted.

  2. Surplus depreciates, debt does NOT. A carried-forward surplus loses value
     over time if the agency opted into a decay rate (reusing the WaterCredit
     geometric decay), but you do not get to depreciate away a debt — it hits
     next year's budget at full magnitude. Aging a debt would quietly forgive
     part of it.

  3. Borrow is capped. You cannot borrow forward more than next year's
     allocation actually holds, or the platform would promise water that does
     not exist.

Depreciation is NEVER re-derived here — it delegates to
``banking_math.depreciated_value`` so the carry-over decay and the WaterCredit
decay can never drift apart (negative-rate 0-floor, geometric shape, and all).

Periods are zero-padded "YYYY-MM" strings (38-04 convention). Decimal
throughout, quantized to 4 decimal places to match the ledger; a float anywhere
reintroduces binary-float drift on money.
"""

from decimal import Decimal

from accounting.banking_math import depreciated_value

_QUANT = Decimal("0.0001")


def _dec(value):
    """Coerce to Decimal without going through binary float."""
    return value if isinstance(value, Decimal) else Decimal(str(value))


def water_year_of(period, anchor_month=10):
    """Water-year label for a "YYYY-MM" period.

    The water year is named by the calendar year it ENDS in. California's runs
    Oct 1 - Sep 30, so with the default ``anchor_month=10`` the months Oct-Dec
    belong to the *next* calendar year's water year:

      - "2024-10" -> 2025   (WY2025 opens in Oct 2024)
      - "2025-01" -> 2025   (still inside WY2025)
      - "2025-09" -> 2025   (last month of WY2025)
      - "2025-10" -> 2026   (Sep->Oct boundary opens WY2026)

    ``anchor_month`` is configurable so a district on a different fiscal
    boundary can re-anchor without a code change. The special case
    ``anchor_month=1`` is a plain calendar year (no forward roll):

      - "2025-03" (anchor 1) -> 2025
      - "2025-12" (anchor 1) -> 2025

    Rule: months ``>= anchor_month`` belong to ``calendar_year + 1`` when
    ``anchor_month > 1``; otherwise the label is just the calendar year.
    """
    year_str, month_str = period.split("-")
    year = int(year_str)
    month = int(month_str)
    if anchor_month > 1 and month >= anchor_month:
        return year + 1
    return year


def net_carryover(allocation_af, usage_af):
    """Signed year-end remainder = ``allocation - usage``, quantized to 4dp.

    Positive -> surplus that carries forward. Negative -> overdraw, a debt
    borrowed against next year. Zero -> exactly used. Keeping it signed means
    one ledger value, never a surplus and a debt at once.

      - allocation 100, usage 70  -> Decimal("30.0000")
      - allocation 100, usage 130 -> Decimal("-30.0000")
      - allocation 100, usage 100 -> Decimal("0.0000")
    """
    remainder = _dec(allocation_af) - _dec(usage_af)
    return remainder.quantize(_QUANT)


def available_with_carryover(
    current_allocation_af,
    prior_carryover_af,
    depreciation_rate=0,
    periods_elapsed=0,
):
    """Current allocation adjusted by the prior year's signed carry-over.

    A POSITIVE prior carry-over (surplus) is aged via
    ``banking_math.depreciated_value`` before it is added, so a stale surplus is
    worth less if the agency set a decay rate. A NEGATIVE prior carry-over
    (debt) is added UN-depreciated at full magnitude — you do not get to
    depreciate away what you owe.

      - current 100, prior +30, rate 0            -> Decimal("130.0000")
      - current 100, prior -30                    -> Decimal("70.0000")
      - current 100, prior +40, rate 0.5, elapsed 1 -> 100 + 20 = "120.0000"

    A negative rate is floored to 0 here before delegating (see below), so it
    behaves like no decay rather than growing the surplus.
    """
    current = _dec(current_allocation_af)
    prior = _dec(prior_carryover_af)

    if prior > 0:
        # Surplus ages like a WaterCredit; debt below is left at full magnitude.
        # Floor the rate at 0 BEFORE delegating: banking_math.depreciated_value
        # floors the decay factor (1 - rate) only at rate >= 1, so a NEGATIVE
        # rate would otherwise grow the surplus (factor > 1) — nonsense for a
        # depreciation mechanism. Flooring the input is sanitization, not a
        # second decay derivation, so the geometric math stays in one place.
        rate = depreciation_rate if depreciation_rate > 0 else 0
        adjustment = depreciated_value(prior, rate, periods_elapsed)
    else:
        adjustment = prior

    return (current + adjustment).quantize(_QUANT)


def cap_borrow(requested_borrow_af, next_year_allocation_af):
    """Borrow forward, clamped to ``[0, next_year_allocation]``, 4dp.

    You cannot borrow more than next year actually holds, and a zero or negative
    request is nonsensical -> 0.

      - requested 30,  next-year 100 -> Decimal("30.0000")
      - requested 150, next-year 100 -> Decimal("100.0000")  (capped)
      - requested 0 or negative      -> Decimal("0.0000")
    """
    requested = _dec(requested_borrow_af)
    cap = _dec(next_year_allocation_af)

    if requested <= 0:
        return Decimal("0").quantize(_QUANT)
    if requested > cap:
        return cap.quantize(_QUANT)
    return requested.quantize(_QUANT)
