# SPDX-License-Identifier: AGPL-3.0-or-later
"""
The observed-property list carries the values the public lists give.

The frozen table below was checked on 2026-10-27 against three sources, and no
test fetches any of them:

- the USGS parameter code list (api.waterdata.usgs.gov, collection
  parameter-codes): 00060, 00065, 00010, 72019, 72020 (Elevation, NGVD29),
  62610 (Elevation, GW, NGVD29), 00054 (Reservoir storage, ac-ft), 00045
  (Precipitation, in), 00020 (Temperature, air, deg C);
- the EPA WQX Characteristic list (23,407 names): every non-blank name below is
  a value on it;
- the CDEC sensor list: sensor 2 is accumulated precipitation, in inches.

A blank pcode means no USGS code with the same unit exists. A blank WQX name
means the WQX list has no value naming the same thing.
"""

import importlib
from io import StringIO

from django.apps import apps as django_apps
from django.core.management import call_command

from datasync.adapters import cdec, registry, usgs
from standards.models import ObservedProperty, SourceParameter

# key: (usgs_pcode, wqx_characteristic_name, ucum_unit)
TABLE = {
    "discharge": ("00060", "Stream flow", "[cft_i]/s"),
    "gage_height": ("00065", "Height, gage", "[ft_i]"),
    "water_temperature": ("00010", "Temperature, water", "Cel"),
    "groundwater_level_depth": (
        "72019", "Depth to water level below land surface", "[ft_i]"),
    "groundwater_level_elevation": ("72020", "", "[ft_i]"),
    "groundwater_level": ("62610", "Groundwater level", "[ft_i]"),
    "reservoir_storage": ("00054", "Reservoir storage", "[acr_us].[ft_i]"),
    "reservoir_elevation": ("", "Lake or reservoir elevation", "[ft_i]"),
    "reservoir_inflow": ("", "", "[cft_i]/s"),
    "reservoir_outflow": ("", "", "[cft_i]/s"),
    "evapotranspiration": ("", "", "mm"),
    "precipitation": ("00045", "Precipitation", "[in_i]"),
    "reference_et": ("", "", "mm"),
    "air_temperature": ("00020", "Temperature, air", "Cel"),
    "snowfall": ("", "", "mm"),
    "solar_radiation": ("", "Solar radiation", "W/m2"),
    "wind_speed": ("", "Wind velocity", "m/s"),
    "extracted_volume": ("", "", "[acr_us].[ft_i]"),
}

# WQX names checked present on the WQX Characteristic list, 2026-10-27.
WQX_NAMES_CHECKED_PRESENT = {
    "Stream flow",
    "Height, gage",
    "Temperature, water",
    "Depth to water level below land surface",
    "Groundwater level",
    "Reservoir storage",
    "Lake or reservoir elevation",
    "Precipitation",
    "Temperature, air",
    "Solar radiation",
    "Wind velocity",
}


def _seed():
    call_command("seed_observed_properties", stdout=StringIO(), stderr=StringIO())


def test_the_seeded_registry_equals_the_checked_table():
    _seed()
    stored = {
        op.key: (op.usgs_pcode, op.wqx_characteristic_name, op.ucum_unit)
        for op in ObservedProperty.objects.all()
    }
    assert stored == TABLE


def test_every_wqx_name_is_one_checked_present_on_the_wqx_list():
    _seed()
    names = {
        op.wqx_characteristic_name
        for op in ObservedProperty.objects.exclude(wqx_characteristic_name="")
    }
    assert names <= WQX_NAMES_CHECKED_PRESENT


def test_the_two_groundwater_elevation_concepts_name_their_datum():
    _seed()
    for key in ("groundwater_level_elevation", "groundwater_level"):
        assert "NGVD 1929" in ObservedProperty.objects.get(key=key).name


def test_seeding_over_a_stale_row_corrects_it():
    ObservedProperty.objects.create(
        key="gage_height",
        name="Gage Height",
        usgs_pcode="",
        wqx_characteristic_name="Gage height",
        ucum_unit="ft",
    )
    ObservedProperty.objects.create(
        key="groundwater_level_elevation",
        name="Groundwater Level Elevation",
        usgs_pcode="72020",
        wqx_characteristic_name="Water level elevation above NAVD 1988",
        ucum_unit="[ft_i]",
    )
    _seed()
    gage = ObservedProperty.objects.get(key="gage_height")
    assert (gage.wqx_characteristic_name, gage.ucum_unit) == ("Height, gage", "[ft_i]")
    gw = ObservedProperty.objects.get(key="groundwater_level_elevation")
    assert gw.wqx_characteristic_name == ""
    assert "NGVD 1929" in gw.name
    assert ObservedProperty.objects.filter(key="gage_height").count() == 1


def test_seeding_over_a_stale_crosswalk_label_corrects_it():
    _seed()
    SourceParameter.objects.filter(source_code="cdec", parameter_code="2").update(
        native_name="Precipitation")
    _seed()
    assert SourceParameter.objects.get(
        source_code="cdec", parameter_code="2"
    ).native_name == "Precipitation, accumulated"


def test_the_migration_corrects_a_stored_row_and_skips_a_missing_key():
    migration = importlib.import_module("standards.migrations.0003_correct_observed_properties")
    ObservedProperty.objects.create(
        key="precipitation",
        name="Precipitation",
        usgs_pcode="00045",
        wqx_characteristic_name="Precipitation",
        ucum_unit="mm",
    )
    ObservedProperty.objects.create(
        key="groundwater_level",
        name="Groundwater Level",
        usgs_pcode="62610",
        wqx_characteristic_name="Groundwater level",
        ucum_unit="[ft_i]",
    )
    # Every other key in the table is absent: it must be skipped, not created.
    migration.correct_stored_rows(django_apps, None)
    assert ObservedProperty.objects.count() == 2
    assert ObservedProperty.objects.get(key="precipitation").ucum_unit == "[in_i]"
    assert "NGVD 1929" in ObservedProperty.objects.get(key="groundwater_level").name


def test_the_migration_corrects_the_stored_crosswalk_labels():
    migration = importlib.import_module("standards.migrations.0003_correct_observed_properties")
    op = ObservedProperty.objects.create(key="precipitation", name="Precipitation", ucum_unit="mm")
    SourceParameter.objects.create(
        source_code="cdec", parameter_code="2", observed_property=op,
        native_name="Precipitation", native_unit="in")
    migration.correct_stored_rows(django_apps, None)
    assert SourceParameter.objects.get(
        source_code="cdec", parameter_code="2").native_name == "Precipitation, accumulated"


def test_the_usgs_labels_name_the_datum():
    assert usgs.PARAMETER_MAP["72020"] == {
        "name": "Elevation above NGVD 1929", "unit": "ft above NGVD 1929"}
    assert usgs.PARAMETER_MAP["62610"] == {
        "name": "Groundwater level above NGVD 1929", "unit": "ft above NGVD 1929"}


def test_the_cdec_precipitation_sensor_is_named_accumulated():
    assert cdec.PARAMETER_MAP["2"]["name"] == "Precipitation, accumulated"
    assert cdec.PARAMETER_MAP["2"]["unit"] == "in"


def test_the_station_label_carries_the_new_words():
    assert registry.get_parameter_label("usgs", "72020") == (
        "Elevation above NGVD 1929 (ft above NGVD 1929)")
    assert registry.get_parameter_label("cdec", "2") == "Precipitation, accumulated (in)"


def test_the_crosswalk_file_matches_what_the_export_writes(tmp_path):
    from pathlib import Path

    _seed()
    out = tmp_path / "crosswalk.csv"
    call_command("export_crosswalk", output=str(out), stdout=StringIO())
    repo = Path(__file__).resolve().parent.parent
    assert (repo / "docs" / "crosswalk.csv").read_text() == out.read_text()


def test_the_guide_table_matches_the_checked_table():
    from pathlib import Path

    text = (Path(__file__).resolve().parent.parent / "docs" / "DATA-STANDARDS.md").read_text()
    rows = {}
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 5 and cells[0].startswith("`") and cells[0].strip("`") in TABLE:
            rows[cells[0].strip("`")] = (
                "" if cells[2] == "none" else cells[2],
                "" if cells[3] == "none" else cells[3],
                cells[4].strip("`"),
            )
    assert rows == TABLE


def test_the_guide_count_sentence_matches_the_table():
    from pathlib import Path

    text = (Path(__file__).resolve().parent.parent / "docs" / "DATA-STANDARDS.md").read_text()
    without = sum(1 for pcode, _w, _u in TABLE.values() if not pcode)
    words = {9: "Nine", 11: "Eleven", 10: "Ten", 8: "Eight"}
    assert f"{words[without]} of the eighteen have no USGS parameter code" in text
    assert without == 9
