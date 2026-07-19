# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Display helpers for drinking-water values.

Exists for one reason: a lab result must not be shown with more precision than
the lab reported. ``SampleResult.result_value`` is a ``DecimalField`` with
``decimal_places=6``, so a nitrate result of 3.2 mg/L comes back out of the
database as ``Decimal("3.200000")``. Rendering that verbatim — which
``floatformat:"-6"`` does — puts six significant figures on screen that nobody
measured.

The obvious fix, ``Decimal.normalize()``, has a trap of its own: it rewrites
values with trailing zeros ABOVE the decimal point into scientific notation, so
a total-coliform MCL of ``Decimal("100.000000")`` renders as ``1E+2``. That is
worse than the problem it solves. Formatting the normalized value with ``f``
gives plain notation in both directions.
"""
from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()


@register.filter
def plain_decimal(value):
    """Render a Decimal at its own precision, never in scientific notation.

    ``Decimal("3.200000")`` -> ``3.2``; ``Decimal("0.002000")`` -> ``0.002``;
    ``Decimal("100.000000")`` -> ``100``. ``None`` renders as an em dash, since
    every caller here is showing a value that may legitimately be absent.
    """
    if value is None or value == "":
        return "—"
    try:
        number = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        # Never swallow the value: a filter that silently blanks a lab result
        # is a data-integrity bug wearing a formatting costume.
        return value
    return format(number.normalize(), "f")
