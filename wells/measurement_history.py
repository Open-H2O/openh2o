# SPDX-License-Identifier: AGPL-3.0-or-later
"""The well page's measurement history: meter reads, hand-entered visits and a logger's monthly digest.

The well page promises "measurement history". The rows exist — the ``measurements`` app is model-only by design
(``core/modules.py``, "no views, no nav"), so a meter's reads and a logger's
water levels have no page of their own and belong on the well they measure.

Three shapes come out of here, all grouped by WATER YEAR (October through
September unless the site sets another month, named for the year it ends in,
``WY 2025-2026``) and listed newest
first. A single year hides the comparison that makes the record worth having.

* ``meter_history(well)`` — every current meter's totalizer reads, the read and
  the delta the seed wrote into ``calculated_volume``. No arithmetic here: the
  delta is the stored column, and the ledger recomputes it from the two reads.
* ``visit_history(well)``: the levels a person measured by hand or imported
  from a file, one row each, newest first: a depth, or the reason no depth
  could be read.
* ``water_level_history(well)``: a monthly digest of a LOGGER's depth to
  water. The month's close is its LAST reading; the change is that close minus
  the previous month's close, chronologically, so a dry year reads as a run of
  positive changes (deeper) and a wet winter as negatives. Built here, never in
  the template.

**Why the two are separate tables.** The digest reads the logger only. The seed
deliberately sets the manual sounder a few hundredths off the transducer, and a
digest that interleaved them would print that disagreement as movement; a
well with no logger has no digest, and its visits table is its record. A
sensor's anomalous rows are dropped when the sensor asks for it
(``exclude_anomalies``), because a transducer logging in air during a
calibration visit "is the instrument, not the aquifer" (the seed's own note on
that row).
"""
from collections import OrderedDict
from decimal import Decimal

from django.db.models import Q
from django.utils import timezone

from accounting.carryover_math import water_year_label as _label
from accounting.carryover_math import water_year_of
from core.water_year import water_year_start_month
from measurements.models import MeterReading, Sensor, SensorMeasurement, WaterMeasurement

DEPTH_PROPERTY = "groundwater_level_depth"

#: Short unit labels for the delta column header; anything else falls back to
#: the meter's own display name.
UNIT_SHORT = {"acre_feet": "AF", "gallons": "gal", "cubic_feet": "cu ft", "cfs": "cfs"}


def water_year(day, start_month=None):
    """The water year a date falls in, named for the calendar year it ends in.

    The year starts in the site's water year start month (October unless the
    site changed it). A caller with many dates passes ``start_month`` once.
    """
    if start_month is None:
        start_month = water_year_start_month()
    return water_year_of(f"{day.year}-{day.month:02d}", start_month)


def water_year_label(wy, start_month=None):
    if start_month is None:
        start_month = water_year_start_month()
    return _label(wy, start_month)


def _local_date(when):
    return timezone.localtime(when).date()


def meter_history(well):
    """Per current meter with at least one read: reads newest first, by water year."""
    groups = []
    start_month = water_year_start_month()
    links = well.wellmeter_set.filter(is_current=True).select_related("meter")
    for link in links:
        reads = list(
            MeterReading.objects.filter(meter=link.meter).order_by("-reading_date")
        )
        if not reads:
            continue
        by_year = OrderedDict()
        for read in reads:
            by_year.setdefault(water_year(_local_date(read.reading_date), start_month), []).append(read)
        # `count` and `delta_total` close each water year's own
        # row-group, the same footer-A shape the diversion and event-history
        # tables carry (rule 7) -- summed here from the rows already fetched
        # above, never a second query. The Totalizer has no matching total: a
        # totalizer is a running reading, never summed (it is the delta column
        # that closes).
        years = [
            {
                "label": water_year_label(wy, start_month),
                "reads": rows,
                "count": len(rows),
                "delta_total": sum((r.calculated_volume or Decimal("0") for r in rows), Decimal("0")),
            }
            for wy, rows in sorted(by_year.items(), reverse=True)
        ]
        unit = UNIT_SHORT.get(link.meter.unit, link.meter.get_unit_display())
        groups.append({"meter": link.meter, "unit": unit, "years": years})
    return groups


def _logger_points(well):
    sensors = list(Sensor.objects.filter(well=well))
    if not sensors:
        return []
    qs = SensorMeasurement.objects.filter(
        sensor__in=sensors, observed_property__key=DEPTH_PROPERTY
    ).select_related("sensor")
    points = []
    for row in qs.order_by("measurement_date"):
        if row.is_anomalous and row.sensor.exclude_anomalies:
            continue
        points.append((row.measurement_date, row.value))
    return points


def visit_history(well):
    """The well's hand-entered levels by water year, newest first; ``[]`` when it has none.

    A visit is a ``WaterMeasurement`` of the depth-to-water property or of the
    groundwater-level type. Each year is ``{"label", "visits"}`` and each visit
    has ``when``, ``value`` (``None`` when no depth was read), ``reason`` and
    ``method``.
    """
    start_month = water_year_start_month()
    rows = (
        WaterMeasurement.objects.filter(well=well)
        .filter(Q(observed_property__key=DEPTH_PROPERTY) | Q(measurement_type="groundwater_level"))
        .order_by("-measurement_date", "-pk")
    )
    by_year = OrderedDict()
    for row in rows:
        when = timezone.localtime(row.measurement_date)
        visit = {
            "when": when,
            "value": row.value,
            "reason": row.no_measurement_reason,
            "method": row.method,
        }
        by_year.setdefault(water_year(when.date(), start_month), []).append(visit)
    return [
        {"label": water_year_label(wy, start_month), "visits": visits}
        for wy, visits in sorted(by_year.items(), reverse=True)
    ]


def history_rows(has_meters, has_visits, has_digest):
    """How the history card lays its tables out: rows of up to two, by name.

    The order is meter reads, visits, logger digest. A well with meter reads
    and neither of the others keeps the sentence that says no level is
    recorded, in the second place. ``[]`` means the well has nothing to show.
    """
    if not (has_meters or has_visits or has_digest):
        return []
    names = []
    if has_meters:
        names.append("meters")
    if has_visits:
        names.append("visits")
    if has_digest:
        names.append("digest")
    if has_meters and not (has_visits or has_digest):
        names.append("no_levels")
    return [names[i:i + 2] for i in range(0, len(names), 2)]


def water_level_history(well):
    """``{"years": [...]}`` or ``None`` when the well has no logger record.

    ``years`` is newest first; each year's ``months`` newest first; each month
    carries ``month`` (the first of the month), ``opening``, ``close`` and
    ``change`` (``None`` for the earliest month on record, which has nothing
    before it to change from).
    """
    start_month = water_year_start_month()
    points = _logger_points(well)
    if not points:
        return None

    months = OrderedDict()  # (year, month) -> {"opening", "close"}; chronological
    for when, value in points:  # already ordered by measurement_date
        day = _local_date(when)
        key = (day.year, day.month)
        if key not in months:
            months[key] = {"month": day.replace(day=1), "opening": value, "close": value}
        else:
            months[key]["close"] = value

    previous = None
    digest = []
    for entry in months.values():
        entry["change"] = None if previous is None else entry["close"] - previous
        previous = entry["close"]
        digest.append(entry)

    by_year = OrderedDict()
    for entry in reversed(digest):  # newest first
        by_year.setdefault(water_year(entry["month"], start_month), []).append(entry)
    # Each water year closes with its NET change: the monthly changes add to
    # it (a close is a level and is never summed; the changes between closes
    # are). The meter table beside this one closes every
    # year with a row, and without one here the two tables drift a row apart
    # from the second year on.
    years = [
        {
            "label": water_year_label(wy, start_month),
            "months": rows,
            "count": len(rows),
            "net_change": sum((r["change"] for r in rows if r["change"] is not None), Decimal("0")),
        }
        for wy, rows in sorted(by_year.items(), reverse=True)
    ]
    return {"years": years}
