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
