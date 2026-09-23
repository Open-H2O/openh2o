# SPDX-License-Identifier: AGPL-3.0-or-later
"""146-05 Task 2 (S2): derive DWR's extraction-method row from the legacy
`measurement_method` choice, once, for every well that already has one.

23 CCR 356.2(b)(2), the GSP Annual Report rule (research file 05, lines
289-297, opened and quoted): "identifies the method of measurement (direct
or estimate) and accuracy of measurements." DWR's SGMA Portal implements it
as a fixed five-row table -- Meters, Electrical Records, Land Use,
Groundwater Model, Other -- with Type Direct or Estimate and Accuracy a band
(research file 05, lines 301-309, 20 GSP annual report records opened and
parsed).

`measurement_method` stays (the seeds, seven test files and the Merced audit
trail read it); this migration gives every well DWR's own row as a one-time
derivation from it, per the design document's mapping:

  certified_meter    -> meters / direct
  power_conversion   -> electrical_records / estimate
  et_method          -> land_use / estimate
  unmetered_estimate -> other / estimate
  blank              -> blank / blank

`accuracy_band` is never derived here -- the legacy field carries no accuracy
information, and a manufactured band would be exactly the model-spread
substitute the platform already refused once (ISS-158, `accounting/confidence.py`).

Reverse clears only what this migration set: wells whose `measurement_method`
was blank never had anything set here and are untouched either way.
"""
from django.db import migrations

#: legacy `measurement_method` value -> (dwr_extraction_method, dwr_direct_or_estimate)
LEGACY_TO_DWR = {
    "certified_meter": ("meters", "direct"),
    "power_conversion": ("electrical_records", "estimate"),
    "et_method": ("land_use", "estimate"),
    "unmetered_estimate": ("other", "estimate"),
}


def derive_dwr_fields(apps, schema_editor):
    """Set the DWR pair once from each well's existing `measurement_method`."""
    Well = apps.get_model("wells", "Well")
    derived = 0
    for legacy, (method, direct_or_estimate) in LEGACY_TO_DWR.items():
        derived += Well.objects.filter(measurement_method=legacy).update(
            dwr_extraction_method=method,
            dwr_direct_or_estimate=direct_or_estimate,
        )
    print(f"  DWR extraction method: {derived} well(s) derived from measurement_method.")


def clear_dwr_fields(apps, schema_editor):
    """Reverse: blank the pair on every well whose legacy value maps to one.

    A well whose `measurement_method` was already blank never had anything
    set by `derive_dwr_fields`, so it is excluded rather than reset to the
    same blank value it already held.
    """
    Well = apps.get_model("wells", "Well")
    Well.objects.filter(measurement_method__in=LEGACY_TO_DWR).update(
        dwr_extraction_method="", dwr_direct_or_estimate="",
    )


class Migration(migrations.Migration):

    dependencies = [
        ('wells', '0004_dwr_method_fields'),
    ]

    operations = [
        migrations.RunPython(derive_dwr_fields, clear_dwr_fields),
    ]
