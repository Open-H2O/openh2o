# SPDX-License-Identifier: AGPL-3.0-or-later
"""The band a measured figure carries, from the devices' stated accuracy.

Brent's S2 ruling (2026-09-20), settled in 150-02-PLAN.md. Pure functions over
records: no database writes, no queries, no engine change (the two resolvers
at the foot excepted, which read and never write). Django-free at import, like
``carryover_math``; a record is anything with ``volume_acre_feet``, ``method``
and ``device``, and a well anything with ``accuracy_band``.

THE RULE
--------
A figure carries a band only when EVERY record summed into it has a stated
accuracy:

* a diversion record through its measuring device's
  ``MeasuringDevice.accuracy_percent`` (23 CCR 934(b)(1)(G));
* a well meter through ``Well.accuracy_band``, DWR's annual-report bands
  "0-5", "5-10", "10-20", "20-30" and "over_30" (23 CCR 356.2(b)(2)).

The band of a sum is the SUM of each record's |volume| x its percent: the
devices' stated accuracy, added up. It is never root-sum-square, which would
assume the devices' errors are independent, and nobody has shown that.

A field's share of a metered headgate carries the headgate record's percent,
applied to the share.

If any summed record has no stated accuracy, the figure has NO band: ``None``,
never "unknown" and never zero. A record has no stated accuracy when its
method is ``estimated_from_use``, ``apportioned``, ``methodology``,
``outage_estimate``, ``below_threshold`` or ``alternative_compliance`` (its
number did not come off the device, even when one is linked), when it has no
device, or when its device's ``accuracy_percent`` is blank. A record whose
method is "device", or is not stated, takes its linked device's percent. An
empty set of records has no band either: there is nothing to state one.

Crop water use (OpenET) never carries a band. The member-model spread is not
the ensemble's error bar, and showing it beside a governing figure was
withdrawn for that reason (``accounting/confidence.py``). That figure is not
this module's business; it is named here so nobody routes it through.

Every returned Decimal is quantized to four places, the ledger's precision.

THE TWO RESOLVERS AT THE FOOT
-----------------------------
``field_month_delivery_band`` and ``field_month_meter_band`` (150-02 Task 3)
are the only functions here that read the database: they find the records
behind one field's month on the field page and hand them to the pure
functions above. Their imports are function-scoped and guarded on
``is_enabled`` (the composition rule, CLAUDE.md), so this module still imports
with no Django app loaded and with ``surface`` or ``wells`` left out.
"""
import calendar
import datetime as dt
from decimal import Decimal

_Q4 = Decimal("0.0001")
_HUNDRED = Decimal("100")

#: Methods whose number did not come off a device with a stated accuracy, so
#: the record carries no band even if a device is linked to it.
NO_BAND_METHODS = frozenset(
    {
        "estimated_from_use",
        "apportioned",
        "methodology",
        "outage_estimate",
        "below_threshold",
        "alternative_compliance",
    }
)

#: DWR's band -> the percent this module uses: the range's upper bound. DWR
#: states a range, not a figure; the upper bound is the most the stated range
#: allows, so the band never claims more accuracy than the well's own row does.
#: "over_30" has no upper bound and so no band, the same as a blank.
_WELL_BAND_UPPER_PERCENT = {
    "0-5": Decimal("5"),
    "5-10": Decimal("10"),
    "10-20": Decimal("20"),
    "20-30": Decimal("30"),
}


def _record_percent(record):
    """The stated accuracy percent behind a diversion record, or None."""
    if record.method in NO_BAND_METHODS:
        return None
    device = record.device
    if device is None:
        return None
    return device.accuracy_percent


def _unrounded_record_band(record):
    percent = _record_percent(record)
    if percent is None:
        return None
    return abs(Decimal(record.volume_acre_feet)) * Decimal(percent) / _HUNDRED


def record_band(record):
    """|volume| x the device's stated percent, or None with no stated accuracy."""
    band = _unrounded_record_band(record)
    if band is None:
        return None
    return band.quantize(_Q4)


def well_band_percent(well):
    """The upper bound of the well's DWR accuracy band, or None.

    DWR's annual report takes a range ("5-10"), not a figure; the range's upper
    bound is used because it is the widest error the stated range allows.
    "over_30" has no upper bound and a blank states nothing: both give None.
    """
    return _WELL_BAND_UPPER_PERCENT.get(well.accuracy_band or "")


def meter_band(well, volume):
    """|volume| x the well's band percent, or None when the well states none."""
    percent = well_band_percent(well)
    if percent is None:
        return None
    return (abs(Decimal(volume)) * percent / _HUNDRED).quantize(_Q4)


def sum_band(bands):
    """The sum of per-record bands; None if empty or if any element is None."""
    total = None
    for band in bands:
        if band is None:
            return None
        total = band if total is None else total + band
    if total is None:
        return None
    return Decimal(total).quantize(_Q4)


def share_band(record, share):
    """A field's share (a fraction in [0, 1]) of one headgate record's band."""
    band = _unrounded_record_band(record)
    if band is None:
        return None
    return (band * Decimal(share)).quantize(_Q4)


def share_bands(records, share):
    """A field's share of a month's headgate records, summed record by record.

    None when the set is empty or any record has no stated accuracy.
    """
    return sum_band(share_band(record, share) for record in records)


def band_words(percent):
    """The tooltip's source line, the percent without trailing zeros."""
    shown = format(Decimal(percent).normalize(), "f")
    return f"The band comes from the measuring device's stated accuracy (±{shown}%)."


def month_bounds(first):
    """``(first, last)``: the first and last day of ``first``'s calendar month."""
    first = first.replace(day=1)
    last_day = calendar.monthrange(first.year, first.month)[1]
    return first, dt.date(first.year, first.month, last_day)


def _single_percent(percents):
    """The one percent every record states, or None when they differ."""
    distinct = {Decimal(p) for p in percents}
    if len(distinct) == 1:
        return distinct.pop()
    return None


def _month_rows(rows, source_type, first, last):
    return [
        row
        for row in rows
        if row.source_type == source_type and first <= row.effective_date <= last
    ]


def field_month_delivery_band(parcel, first, last, *, rows=None):
    """The band on one field's canal delivery for one month: ``(band, percent)``.

    ``(None, None)`` whenever the month's delivery has no stated accuracy. The
    delivery is the month's ``surface_diversion`` ledger rows for ``parcel``,
    dated ``first`` to ``last`` inclusive. ``rows``, when given, is ledger
    rows the caller has already read (the field page reads its period once,
    not once a month); only the month's ``surface_diversion`` rows among them
    are used.

    * A field's own recorded delivery (``divided_from_headgate`` False) has no
      diversion record behind it on this platform, so no stated accuracy:
      ``(None, None)``. So does a split row written before 149-01, which names
      no point (``divided_from_point_pk`` blank).
    * A split row is a share of a point of diversion's month. It traces by
      ``divided_from_point_pk`` to that point's direct-use ``DiversionRecord``s
      dated in the month (the records the split itself divides,
      ``surface.services._records_for_period``). The field's share is its rows'
      magnitude over the month's ``consumed_acre_feet()`` total of those
      records, because the split works from the consumed total
      (``surface/services.py::allocate_district_delivery``). The band is
      ``share_bands(records, share)``: the headgate records' stated accuracy
      applied to the share, as the rule says. The canal-loss fractions the
      split takes off first are the agency's own stated fractions, not a
      device's accuracy, and are not a second band.
    * Rows from two points are two shares: their bands sum, and the month has
      none if either has none.

    ``percent`` is the one percent every summed record states, for the
    tooltip (``band_words``); None when the records state different percents,
    while the band itself still stands.
    """
    from core.modules import is_enabled

    if not is_enabled("surface"):
        return None, None
    from parcels.models import ParcelLedger
    from surface.models import DiversionRecord
    from surface.services import _in_months

    if rows is None:
        rows = ParcelLedger.objects.filter(
            parcel=parcel,
            source_type="surface_diversion",
            effective_date__gte=first,
            effective_date__lte=last,
        )
    rows = _month_rows(rows, "surface_diversion", first, last)
    if not rows:
        return None, None

    by_point = {}
    for row in rows:
        if not row.divided_from_headgate or row.divided_from_point_pk is None:
            return None, None
        by_point[row.divided_from_point_pk] = by_point.get(
            row.divided_from_point_pk, Decimal("0")
        ) + abs(Decimal(row.amount_acre_feet))

    bands = []
    percents = []
    month_start = first.replace(day=1)
    for point_pk, magnitude in by_point.items():
        records = list(
            DiversionRecord.objects.filter(
                _in_months("month", [month_start]),
                point_of_diversion_id=point_pk,
                diversion_type="direct_use",
            ).select_related("device")
        )
        total = sum((r.consumed_acre_feet() for r in records), Decimal("0"))
        if not records or total <= 0:
            return None, None
        band = share_bands(records, magnitude / total)
        if band is None:
            return None, None
        bands.append(band)
        percents.extend(_record_percent(r) for r in records)
    return sum_band(bands), _single_percent(percents)


def field_month_meter_band(parcel, first, last, *, rows=None, wells=None):
    """The band on one field's metered extraction for one month: ``(band, percent)``.

    The extraction is the sum of the month's ``meter_reading`` ledger rows'
    magnitudes for ``parcel``, dated ``first`` to ``last`` inclusive; the well
    is the field's related well (``wells.WellIrrigatedParcel``). The band is
    ``meter_band(well, sum)`` with the well's DWR band as the percent.
    ``(None, None)`` when the month has no meter reading, when the field has no
    related well or more than one (a reading cannot then be put to one
    well's band), or when the well states no band.

    ``rows`` is as in ``field_month_delivery_band``; ``wells``, when given, is
    the field's related ``Well`` objects, already read by the caller.
    """
    from core.modules import is_enabled

    if not is_enabled("wells"):
        return None, None
    from parcels.models import ParcelLedger

    if wells is None:
        from wells.models import WellIrrigatedParcel

        wells = [
            link.well
            for link in WellIrrigatedParcel.objects.filter(parcel=parcel).select_related(
                "well"
            )
        ]
    if len(wells) != 1:
        return None, None
    if rows is None:
        rows = ParcelLedger.objects.filter(
            parcel=parcel,
            source_type="meter_reading",
            effective_date__gte=first,
            effective_date__lte=last,
        )
    rows = _month_rows(rows, "meter_reading", first, last)
    if not rows:
        return None, None
    well = wells[0]
    volume = sum((abs(Decimal(row.amount_acre_feet)) for row in rows), Decimal("0"))
    band = meter_band(well, volume)
    if band is None:
        return None, None
    return band, well_band_percent(well)
