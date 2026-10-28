# SPDX-License-Identifier: AGPL-3.0-or-later
"""Apply the corrected observed-property list to rows a site already stores.

`seed_observed_properties` now writes with update_or_create, so a seed run
reaches an existing site too; this migration does the same for a site that
upgrades without seeding. Rows are matched by key, and a key the site does not
hold is skipped. The values were checked on 2026-10-27 against the USGS
parameter code list, the EPA WQX Characteristic list and the CDEC sensor list.
"""

from django.db import migrations

# key: (name or None to keep, usgs_pcode, wqx_characteristic_name, ucum_unit)
CORRECTIONS = {
    "discharge": (None, "00060", "Stream flow", "[cft_i]/s"),
    "gage_height": (None, "00065", "Height, gage", "[ft_i]"),
    "water_temperature": (None, "00010", "Temperature, water", "Cel"),
    "groundwater_level_depth": (
        None, "72019", "Depth to water level below land surface", "[ft_i]"),
    "groundwater_level_elevation": (
        "Groundwater Level Elevation (NGVD 1929)", "72020", "", "[ft_i]"),
    "groundwater_level": (
        "Groundwater Level (NGVD 1929)", "62610", "Groundwater level", "[ft_i]"),
    "reservoir_storage": (None, "00054", "Reservoir storage", "[acr_us].[ft_i]"),
    "reservoir_elevation": (None, "", "Lake or reservoir elevation", "[ft_i]"),
    "reservoir_inflow": (None, "", "", "[cft_i]/s"),
    "reservoir_outflow": (None, "", "", "[cft_i]/s"),
    "evapotranspiration": (None, "", "", "mm"),
    "precipitation": (None, "00045", "Precipitation", "[in_i]"),
    "reference_et": (None, "", "", "mm"),
    "air_temperature": (None, "00020", "Temperature, air", "Cel"),
    "snowfall": (None, "", "", "mm"),
    "solar_radiation": (None, "", "Solar radiation", "W/m2"),
    "wind_speed": (None, "", "Wind velocity", "m/s"),
    "extracted_volume": (None, "", "", "[acr_us].[ft_i]"),
}

# (source_code, parameter_code): (native_name, native_unit)
CROSSWALK_LABELS = {
    ("usgs", "72020"): ("Elevation above NGVD 1929", "ft above NGVD 1929"),
    ("usgs", "62610"): ("Groundwater level above NGVD 1929", "ft above NGVD 1929"),
    ("cdec", "2"): ("Precipitation, accumulated", "in"),
}


def correct_stored_rows(apps, schema_editor):
    ObservedProperty = apps.get_model("standards", "ObservedProperty")
    SourceParameter = apps.get_model("standards", "SourceParameter")
    for key, (name, pcode, wqx, unit) in CORRECTIONS.items():
        row = ObservedProperty.objects.filter(key=key).first()
        if row is None:
            continue
        if name is not None:
            row.name = name
        row.usgs_pcode = pcode
        row.wqx_characteristic_name = wqx
        row.ucum_unit = unit
        row.save()
    for (source, code), (native_name, native_unit) in CROSSWALK_LABELS.items():
        SourceParameter.objects.filter(
            source_code=source, parameter_code=code
        ).update(native_name=native_name, native_unit=native_unit)


class Migration(migrations.Migration):

    dependencies = [
        ("standards", "0002_datastream"),
    ]

    operations = [
        migrations.RunPython(correct_stored_rows, migrations.RunPython.noop),
    ]
