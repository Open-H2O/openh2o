# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pure WaterCredit banking math — depreciation, elapsed months, and expiry.

Intentionally Django-free (imports only ``decimal`` + the standard library), the
same split that gave 38-03's effective-precip math a real RED->GREEN cycle in
bare local Python. This is the cross-month, money-sensitive core of the banking
mechanism: how much a deposited surplus is worth after it has aged some months,
and whether it has expired. The thin DB-bound orchestration that reads/writes
WaterCredit + WaterCreditDraw rows lives in run_calculations (tested in the running container).

Depreciation is GEOMETRIC (compound) per elapsed period:
    value = amount * (1 - rate) ** periods_elapsed      floored at 0

Chosen over linear decay because it never goes negative and is the standard decay
shape; the rate is agency-tunable (default 0 = no decay until they opt in). The
decay factor (1 - rate) is floored at 0 first, so a rate >= 1 kills the credit
after a single period instead of oscillating for even exponents.

Periods and expiry use plain "YYYY-MM" strings. Lexicographic compare is valid
because the months are zero-padded, so "2024-06" < "2024-12" as text.
"""

from decimal import Decimal


def _year_month(period):
    """Parse a 'YYYY-MM' string into an absolute month index (year*12 + month)."""
    year_str, month_str = period.split("-")
    return int(year_str) * 12 + int(month_str)


def periods_between(origin_period, current_period):
    """Whole months from origin to current ("YYYY-MM" strings).

    Returns ``current - origin`` (may be 0 for the same month). A current period
    earlier than the origin is a programming error — a credit can only be drawn by
    a LATER period — so it raises rather than silently returning a negative.

    Raises:
        ValueError: when current_period is before origin_period.
    """
    elapsed = _year_month(current_period) - _year_month(origin_period)
    if elapsed < 0:
        raise ValueError(
            f"current period {current_period!r} is before origin "
            f"{origin_period!r}; a credit cannot be drawn before it is banked"
        )
    return elapsed


def depreciated_value(amount, depreciation_rate, periods_elapsed):
    """Geometric-decay value of a credit after ``periods_elapsed`` months.

    ``amount * (1 - rate) ** elapsed``, floored at 0. The decay factor is floored
    at 0 before exponentiation, so:
      - rate 0          -> factor 1   -> value unchanged for any elapsed
      - rate 0.10       -> factor 0.9 -> compounds (0.81 after 2, ...)
      - rate >= 1       -> factor 0   -> 0 once elapsed >= 1 (amount at elapsed 0)
    All arithmetic is Decimal to avoid binary-float drift on money.
    """
    amt = amount if isinstance(amount, Decimal) else Decimal(str(amount))
    rate = (
        depreciation_rate
        if isinstance(depreciation_rate, Decimal)
        else Decimal(str(depreciation_rate))
    )

    factor = Decimal("1") - rate
    if factor < 0:
        factor = Decimal("0")

    # Decimal("0") ** 0 == Decimal("1"), so elapsed 0 returns the full amount
    # even when the factor is 0 (a rate>=1 credit is still whole the month it lands).
    value = amt * (factor ** periods_elapsed)
    return value if value > 0 else Decimal("0")


def is_expired(expires_period, current_period):
    """Whether a credit is dead at ``current_period`` ("YYYY-MM" strings).

    ``False`` when ``expires_period`` is None (never expires). Otherwise the credit
    is expired once the current period has reached OR passed the expiry month
    (``current >= expires``), compared lexicographically — valid because the
    zero-padded "YYYY-MM" form sorts the same as chronological order.
    """
    if expires_period is None:
        return False
    return current_period >= expires_period
