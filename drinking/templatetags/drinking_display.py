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
from django.db.models import Max

register = template.Library()


@register.simple_tag
def drinking_summary():
    """Counts for the dashboard card.

    A simple_tag rather than view context on purpose. The dashboard card hook
    passes a module a template PATH and nothing else — deliberately, so the
    accounting view that renders the dashboard never learns the name of a module
    that might not be installed. A module that needs data therefore fetches its
    own, and that is what keeps `dashboard_cards` a one-line registry entry
    instead of a cross-app context negotiation.

    Returns ``None`` when no water system exists, which is the card's signal to
    render nothing at all. An operator who has not started using this domain
    should not be shown a panel of zeroes on their dashboard.

    Three aggregates, deliberately not one clever join: counting facilities,
    points and results through a single chain of multi-valued joins multiplies
    the rows and silently inflates every count but the deepest.
    """
    from drinking.models import SampleResult, SamplingPoint, SystemFacility, WaterSystem

    system = WaterSystem.objects.order_by("pwsid").first()
    if system is None:
        return None

    return {
        "system": system,
        "facility_count": SystemFacility.objects.filter(system=system).count(),
        "sampling_point_count": SamplingPoint.objects.filter(
            facility__system=system
        ).count(),
        "result_count": SampleResult.objects.filter(
            event__sampling_point__facility__system=system
        ).count(),
        "latest_sample_date": _latest_sample_date(system),
        "system_count": WaterSystem.objects.count(),
    }


def _latest_sample_date(system):
    from drinking.models import SampleEvent

    return SampleEvent.objects.filter(
        sampling_point__facility__system=system
    ).aggregate(latest=Max("sample_date"))["latest"]


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
