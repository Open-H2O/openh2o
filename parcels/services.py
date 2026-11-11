# SPDX-License-Identifier: AGPL-3.0-or-later
"""Lookups about a use area that every deployment needs, canals or not."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from django.db.models import F, Q

if TYPE_CHECKING:
    from core.models import SiteConfig
    from parcels.models import Parcel


def month_of(month: date | str | None) -> date | None:
    """The first day of a month given as a date or a ``YYYY-MM`` period; None stays None."""
    if month is None:
        return None
    if isinstance(month, str):
        year, number = month.split("-")[:2]
        return date(int(year), int(number), 1)
    return month.replace(day=1)


def irrigation_row_in_force(parcel: Parcel, month: date | str | None = None):
    """The ``ParcelIrrigationMethod`` row in force in ``month``, or None.

    The row with the latest start month on or before the month; an empty start
    month counts as the earliest. Without a month, the row in force today.
    The row's own ``method`` may be empty ("Not set").
    """
    from parcels.models import ParcelIrrigationMethod

    first = month_of(month) or date.today().replace(day=1)
    rows = ParcelIrrigationMethod.objects.filter(parcel=parcel).filter(
        Q(start_month__isnull=True) | Q(start_month__lte=first)
    )
    return rows.select_related("method").order_by(F("start_month").asc(nulls_first=True)).last()


def field_efficiency(
    parcel: Parcel,
    config: SiteConfig | None = None,
    month: date | str | None = None,
) -> tuple[Decimal, str]:
    """One parcel's own field efficiency in a month, and where it came from.

    Returns ``(Decimal, source)``. ``source`` is ``"method"`` when the parcel
    has an irrigation method in force in ``month`` (see
    ``irrigation_row_in_force``), which gives the assigned efficiency off that
    method's row. Otherwise ``"agency"``, the deployment-wide
    ``SiteConfig.default_irrigation_efficiency``: a use area with no row yet,
    or whose row in force is "Not set". ``month`` is a date in the month, or
    a ``YYYY-MM`` period; without it, the method in force today.

    This is the SAME figure ``surface.services.allocate_district_delivery``'s
    per-parcel cap and ``subtract_surface_water``'s consumption math both read,
    so the split and the subtraction can never drift apart on a mixed-method
    headgate (a center pivot and a furrow field sharing one point of diversion
    must not share one cap).

    Lives here, not in ``surface.services``, with the two models it
    reads, so a deployment without ``surface`` (a groundwater-only district)
    resolves a field's efficiency the same way.

    ``config`` lets a caller that has already read the deployment's
    ``SiteConfig`` for a whole run pass it in (``run_calculations``
    reads it once, so a settings edit mid-run cannot give two fields two
    different defaults). Otherwise it is read here.

    ``SiteConfig.objects.first() or SiteConfig()`` rather than ``.get()``
    (the established idiom, ``surface/diversion_import.py``): a real deployment
    always carries exactly one row, but this reads safely before one exists,
    falling back to the field's own class default (0.750) instead of raising.
    """
    # Imported lazily so this module has no load-time dependency on core.
    from core.models import SiteConfig

    link = irrigation_row_in_force(parcel, month)
    if link is not None and link.method is not None:
        return link.method.assigned_efficiency, "method"
    if config is None:
        config = SiteConfig.objects.first() or SiteConfig()
    return config.default_irrigation_efficiency, "agency"
