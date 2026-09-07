# SPDX-License-Identifier: AGPL-3.0-or-later
"""The well page's measurement history: meter reads and a monthly water-level digest.

ISS-145. The page has promised "measurement history" since it was written and
rendered none. The rows exist — the ``measurements`` app is model-only by design
(``core/modules.py``, "no views, no nav"), so a meter's reads and a logger's
water levels have no page of their own and belong on the well they measure.

Two shapes come out of here, both grouped by WATER YEAR (October through
September, named for the year it ends in, ``WY 2025-2026``) and listed newest
first. A single year hides the comparison that makes the record worth having;
ISS-145 says so in as many words.

* ``meter_history(well)`` — every current meter's totalizer reads, the read and
  the delta the seed wrote into ``calculated_volume``. No arithmetic here: the
  delta is the stored column, and the ledger recomputes it from the two reads.
* ``water_level_history(well)`` — a monthly digest of depth to water. The
  month's close is its LAST reading; the change is that close minus the previous
  month's close, chronologically, so a dry year reads as a run of positive
  changes (deeper) and a wet winter as negatives. Built here, never in the
  template.

**Which record the digest reads.** A logger (a ``Sensor`` on the well) wins
where the well has one; a well with only the hand-entered ``WaterMeasurement``
record gets that instead. The two are not mixed: the seed deliberately sets the
manual sounder a few hundredths off the transducer, and a digest that
interleaved them would print that disagreement as movement. Readings are
selected by the observed property ``groundwater_level_depth``; a sensor's
anomalous rows are dropped when the sensor asks for it (``exclude_anomalies``),
because a transducer logging in air during a calibration visit "is the
instrument, not the aquifer" (the seed's own note on that row).
"""
from collections import OrderedDict

from django.utils import timezone

from measurements.models import MeterReading, Sensor, SensorMeasurement, WaterMeasurement

DEPTH_PROPERTY = "groundwater_level_depth"

#: Short unit labels for the delta column header; anything else falls back to
#: the meter's own display name.
UNIT_SHORT = {"acre_feet": "AF", "gallons": "gal", "cubic_feet": "cu ft", "cfs": "cfs"}


def water_year(day):
    """The water year a date falls in, named for the calendar year it ends in."""
    return day.year + 1 if day.month >= 10 else day.year


def water_year_label(wy):
    return f"WY {wy - 1}-{wy}"


def _local_date(when):
    return timezone.localtime(when).date()


def meter_history(well):
    """Per current meter with at least one read: reads newest first, by water year."""
    groups = []
    links = well.wellmeter_set.filter(is_current=True).select_related("meter")
    for link in links:
        reads = list(
            MeterReading.objects.filter(meter=link.meter).order_by("-reading_date")
        )
        if not reads:
            continue
        by_year = OrderedDict()
        for read in reads:
            by_year.setdefault(water_year(_local_date(read.reading_date)), []).append(read)
        years = [
            {"label": water_year_label(wy), "reads": rows}
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


def _hand_entered_points(well):
    qs = WaterMeasurement.objects.filter(
        well=well, observed_property__key=DEPTH_PROPERTY
    ).order_by("measurement_date")
    return [(row.measurement_date, row.value) for row in qs]


def water_level_history(well):
    """``{"source": ..., "years": [...]}`` or ``None`` when the well has no record.

    ``years`` is newest first; each year's ``months`` newest first; each month
    carries ``month`` (the first of the month), ``opening``, ``close`` and
    ``change`` (``None`` for the earliest month on record, which has nothing
    before it to change from).
    """
    points = _logger_points(well)
    source = "logger"
    if not points:
        points = _hand_entered_points(well)
        source = "hand-entered"
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
        by_year.setdefault(water_year(entry["month"]), []).append(entry)
    years = [
        {"label": water_year_label(wy), "months": rows}
        for wy, rows in sorted(by_year.items(), reverse=True)
    ]
    return {"source": source, "years": years}
