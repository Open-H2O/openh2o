# SPDX-License-Identifier: AGPL-3.0-or-later
"""151.6-04: water levels typed on a well's page or imported from a file.

A district or grower who measures depth to water by hand types a level on the
well's page, or brings a season's levels in from a file, and sees them in
Measurement history. DWR's lists and field names are the source of the two
option lists on the model (``measurements.models.NO_MEASUREMENT_REASONS`` and
``WATER_LEVEL_METHODS``); the real test file is DWR's groundwater level
export for the Merced wells (``tests/fixtures/water_levels``).

Every expected figure is a literal worked out from the files, never a
re-derivation of what the code computes. From ``dwr_gsp_merced_2024_2025.csv``
(22 data rows; a spreadsheet numbers the first one row 2):

* 162 has 4 rows, 212 has 4, 224 has 4, CSB02B has 6 and MW1013 has 4.
* MW1013 is on no well, so its 4 rows (rows 20 to 23) are errors.
* 224's 2025-03-07 level of 105.33 is put on file first, so it is the one row
  counted "Already on file".
* New levels: 22 less 4 less 1 is 17. They include 212's two 2024 rows with no
  depth and the reason "Can't get tape in casing".
"""
import datetime as dt
from decimal import Decimal
from html import unescape
from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from core.access import READ_ONLY_MESSAGE
from core.models import User
from measurements.models import (
    NO_MEASUREMENT_REASONS,
    WATER_LEVEL_METHODS,
    Meter,
    Sensor,
    SensorMeasurement,
    WaterMeasurement,
)
from standards.models import ObservedProperty
from tests.factories import WellFactory
from tests.import_flow import import_and_read, token_of
from wells import measurement_history
from wells.models import WellMeter

pytestmark = pytest.mark.django_db

FIXTURES = Path(__file__).parent / "fixtures" / "water_levels"
DWR_FILE = FIXTURES / "dwr_gsp_merced_2024_2025.csv"
EXTRA_FILE = FIXTURES / "wcr_and_ambiguous_rows.csv"

FIELD_COLUMNS = {
    "map:well": "WELL_NAME",
    "map:date": "MSMT_DATE",
    "map:depth": "GSE_GWE",
    "map:reason": "WLM_QA_DESC",
    "map:method": "WLM_DESC",
    "map:notes": "MSMT_CMT",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _user(username="hydrologist", **flags):
    return User.objects.create_user(
        username=username, email=f"{username}@example.org", password="x",
        is_active=True, **flags,
    )


def _client(user):
    client = Client()
    client.force_login(user)
    return client


def _depth_property():
    return ObservedProperty.objects.get_or_create(
        key="groundwater_level_depth", defaults={"name": "Depth to groundwater"}
    )[0]


def _local(y, m, d, hour=12, minute=0):
    return timezone.make_aware(dt.datetime(y, m, d, hour, minute))


def _post_level(client, well, **fields):
    data = {"level_date": "2025-03-07", **fields}
    return client.post(reverse("wells:water_level_add", args=[well.pk]), data, follow=True)


def _page(client, well):
    return client.get(reverse("wells:detail", args=[well.pk])).content.decode()


def _visits_table(html):
    """The Visits facts line and its table, from the page's own markup."""
    start = html.index("Visits &middot;")
    return html[start:html.index("</table>", start) + len("</table>")]


def _digest_table(html):
    start = html.index("Logger, monthly close")
    return html[start:html.index("</table>", start) + len("</table>")]


def _logged_well(name="Logged well"):
    well = WellFactory(name=name)
    sensor = Sensor.objects.create(
        name="test transducer", sensor_type="pressure_transducer", well=well
    )
    prop = _depth_property()
    for y, m, d, v in [(2025, 8, 31, "79.5000"), (2025, 9, 30, "80.3500")]:
        SensorMeasurement.objects.create(
            sensor=sensor, observed_property=prop, measurement_date=_local(y, m, d, 6),
            value=Decimal(v), unit="ft",
        )
    return well


def _csv_upload(path_or_text, name="levels.csv"):
    data = path_or_text.read_bytes() if isinstance(path_or_text, Path) else path_or_text.encode()
    return SimpleUploadedFile(name, data, content_type="text/csv")


def _preview(client, upload, **extra):
    return client.post(
        reverse("wells:water_level_import_preview"), {"file": upload, **extra},
        HTTP_HX_REQUEST="true",
    )


def _run_import(client, upload, mapping=None):
    preview = _preview(client, upload)
    token = token_of(preview)
    status = import_and_read(
        client, reverse("wells:water_level_import_commit"), token,
        mapping if mapping is not None else FIELD_COLUMNS,
    )
    return preview, status.content.decode()


def _merced_wells():
    wells = {
        "162": WellFactory(name="162"),
        "224": WellFactory(name="224"),
        "CSB02B": WellFactory(name="CSB02B"),
        "212": WellFactory(name="Well twelve", state_well_number="212"),
    }
    return wells


# ---------------------------------------------------------------------------
# The two lists are DWR's, word for word and in DWR's order
# ---------------------------------------------------------------------------


def test_the_reasons_and_methods_are_dwrs_lists_in_dwrs_order():
    assert [value for value, _label in NO_MEASUREMENT_REASONS] == [
        "Pumping", "Temporarily inaccessible", "Dry well", "Can't get tape in casing",
        "Measurement Discontinued", "Tape hung up", "Well has been destroyed",
        "Pump house locked", "Flowing artesian well", "Unable to locate well",
        "Casing leaking or wet", "Special/Other",
    ]
    assert [value for value, _label in WATER_LEVEL_METHODS] == [
        "Electric sounder measurement", "Steel tape measurement",
        "Acoustic or sonic sounder", "Airline measurement, pressure gage, or manometer",
        "Electronic pressure transducer", "Other", "Unknown",
    ]


def test_a_groundwater_level_has_a_depth_or_a_reason_and_never_both_or_neither():
    well = WellFactory()
    base = dict(
        name="level", measurement_type="groundwater_level", unit="ft", well=well,
        measurement_date=_local(2025, 3, 7),
    )
    WaterMeasurement.objects.create(value=Decimal("10"), **base)
    WaterMeasurement.objects.create(value=None, no_measurement_reason="Dry well", **base)
    for bad in (
        dict(value=Decimal("10"), no_measurement_reason="Dry well"),
        dict(value=None, no_measurement_reason=""),
    ):
        with pytest.raises(IntegrityError), transaction.atomic():
            WaterMeasurement.objects.create(**base, **bad)
    # Other kinds of measurement are not held to the rule.
    WaterMeasurement.objects.create(
        name="rain", measurement_type="precipitation", unit="in", value=Decimal("1"),
        measurement_date=_local(2025, 3, 7),
    )


# ---------------------------------------------------------------------------
# (a) (b) (c) The form on the well's page
# ---------------------------------------------------------------------------


def test_a_writer_sees_the_form_on_a_well_with_no_meter_and_no_monitoring_row():
    well = WellFactory(name="Bare well")
    html = _page(_client(_user()), well)
    assert "Add a water level" in html
    assert reverse("wells:water_level_add", args=[well.pk]) in html
    assert "Save level" in html
    assert "Depth to water (ft below land surface)" in html
    assert "No measurement" in html
    assert "Not stated" in html


def test_a_viewer_sees_no_form_and_no_import_link():
    well = WellFactory(name="Read-only well")
    html = _page(_client(_user("viewer", read_only=True)), well)
    assert "Add a water level" not in html
    assert reverse("wells:water_level_import") not in html


def test_a_typed_depth_is_saved_and_shows_in_the_visits_table():
    writer = _user()
    well = WellFactory(name="Typed well", well_registration_id="MER-W-900")
    _depth_property()

    response = _post_level(
        _client(writer), well, method="Electric sounder measurement",
        depth_ft="105.33", notes="Spring round",
    )

    assert response.redirect_chain[-1][0] == reverse("wells:detail", args=[well.pk])
    assert "Water level saved." in response.content.decode()
    (level,) = WaterMeasurement.objects.filter(well=well)
    assert level.name == "MER-W-900 depth to water"
    assert level.measurement_type == "groundwater_level"
    assert level.observed_property.key == "groundwater_level_depth"
    assert level.value == Decimal("105.33")
    assert level.unit == "ft"
    assert timezone.localtime(level.measurement_date) == _local(2025, 3, 7, 12, 0)
    assert level.source == "manual"
    assert level.recorded_by == writer
    assert level.notes == "Spring round"
    assert level.method == "Electric sounder measurement"
    assert level.no_measurement_reason == ""

    visits = _visits_table(response.content.decode())
    assert "depth to water, ft below land surface" in visits
    assert "Mar 7, 2025" in visits
    assert "105.33" in visits
    assert "Electric sounder measurement" in visits
    assert "WY 2024-2025" in visits


def test_a_well_with_no_registration_id_is_named_by_its_own_name():
    well = WellFactory(name="Orchard well")
    _post_level(_client(_user()), well, depth_ft="50")
    assert WaterMeasurement.objects.get(well=well).name == "Orchard well depth to water"


def test_no_measurement_with_a_reason_saves_no_depth_and_the_page_shows_the_reason():
    well = WellFactory(name="Pumping well")

    response = _post_level(
        _client(_user()), well, level_date="2025-10-17", no_measurement="1",
        reason="Pumping",
    )

    (level,) = WaterMeasurement.objects.filter(well=well)
    assert level.value is None
    assert level.no_measurement_reason == "Pumping"
    assert level.method == ""
    visits = _visits_table(response.content.decode())
    assert "Oct 17, 2025" in visits
    assert "Pumping" in visits
    assert "text-tertiary" in visits


@pytest.mark.parametrize(
    "fields, sentence",
    [
        ({}, "Enter a depth to water or tick No measurement."),
        (
            {"depth_ft": "105.33", "no_measurement": "1", "reason": "Pumping"},
            "Enter a depth to water or tick No measurement, not both.",
        ),
        ({"no_measurement": "1"}, "Pick a reason, or untick No measurement."),
    ],
)
def test_a_form_that_cannot_be_saved_says_why_and_saves_nothing(fields, sentence):
    well = WellFactory(name="Refusing well")

    response = _post_level(_client(_user()), well, **fields)

    assert response.status_code == 200
    assert sentence in response.content.decode()
    assert not WaterMeasurement.objects.exists()


def test_an_invalid_form_keeps_what_was_typed():
    well = WellFactory(name="Keeping well")
    response = _post_level(_client(_user()), well, level_date="2025-10-17", notes="Left as typed")
    html = response.content.decode()
    assert 'value="2025-10-17"' in html
    assert "Left as typed" in html


# ---------------------------------------------------------------------------
# (d) The measurement history
# ---------------------------------------------------------------------------


def test_a_level_on_a_logger_well_shows_in_visits_beside_the_logger_digest():
    well = _logged_well()

    response = _post_level(
        _client(_user()), well, level_date="2025-09-15", method="Steel tape measurement",
        depth_ft="78.25",
    )
    html = response.content.decode()
    section = html[html.index("Measurement history"):]

    assert "Visits &middot; depth to water, ft below land surface" in section
    assert (
        "Logger, monthly close &middot; change is against the previous month's close; "
        "positive is deeper" in section
    )
    assert "78.25" in _visits_table(section)
    assert "Steel tape measurement" in _visits_table(section)
    digest = _digest_table(section)
    assert "80.35" in digest
    assert "78.25" not in digest
    assert section.count('class="page-grid-2col history-grid"') == 1


def test_a_well_with_no_logger_shows_visits_and_no_monthly_digest():
    well = WellFactory(name="Hand only")
    client = _client(_user())
    _post_level(client, well, level_date="2025-09-10", depth_ft="86.94")
    html = _post_level(client, well, level_date="2025-10-10", depth_ft="87.51").content.decode()
    section = html[html.index("Measurement history"):]

    visits = _visits_table(section)
    assert visits.index("87.51") < visits.index("86.94")
    assert "Logger, monthly close" not in section
    assert "Net change" not in section
    assert "No meter read is recorded for this well." not in section


def test_visits_group_by_water_year_with_newest_first():
    well = WellFactory(name="Years well")
    client = _client(_user())
    for day, depth in [("2025-09-10", "86.94"), ("2025-10-10", "87.51"), ("2026-01-05", "88.01")]:
        _post_level(client, well, level_date=day, depth_ft=depth)
    visits = _visits_table(_page(client, well))
    assert visits.index("WY 2025-2026") < visits.index("WY 2024-2025")
    assert visits.index("88.01") < visits.index("87.51") < visits.index("86.94")


def test_a_hand_entered_row_made_by_the_seed_counts_as_a_visit():
    well = WellFactory(name="Seeded well")
    WaterMeasurement.objects.create(
        name="sounder", measurement_type="other", observed_property=_depth_property(),
        value=Decimal("91.0600"), unit="ft", measurement_date=_local(2024, 10, 15, 10), well=well,
    )
    assert "91.06" in _visits_table(_page(_client(_user()), well))


def test_the_history_card_lays_out_two_tables_to_a_row_in_order():
    assert measurement_history.history_rows(False, False, False) == []
    assert measurement_history.history_rows(True, False, False) == [["meters", "no_levels"]]
    assert measurement_history.history_rows(False, True, False) == [["visits"]]
    assert measurement_history.history_rows(False, True, True) == [["visits", "digest"]]
    assert measurement_history.history_rows(True, True, False) == [["meters", "visits"]]
    assert measurement_history.history_rows(True, False, True) == [["meters", "digest"]]
    assert measurement_history.history_rows(True, True, True) == [
        ["meters", "visits"], ["digest"],
    ]


def test_a_well_with_meter_reads_visits_and_a_logger_puts_the_digest_on_a_second_row():
    well = _logged_well("Everything well")
    meter = Meter.objects.create(serial_number="MTR-WL-1", unit="acre_feet")
    WellMeter.objects.create(well=well, meter=meter, is_current=True)
    from measurements.models import MeterReading

    MeterReading.objects.create(
        meter=meter, reading_date=_local(2025, 10, 31), previous_value=Decimal("100"),
        current_value=Decimal("110"), calculated_volume=Decimal("10"), quality="approved",
    )
    html = _post_level(_client(_user()), well, depth_ft="78.25").content.decode()
    section = html[html.index("Measurement history"):]
    assert section.count('class="page-grid-2col history-grid"') == 2
    assert section.index("MTR-WL-1") < section.index("Visits &middot;") < section.index("Logger, monthly close")


def test_a_well_with_nothing_recorded_keeps_the_empty_sentence():
    html = _page(_client(_user()), WellFactory(name="Empty well"))
    section = html[html.index("Measurement history"):]
    assert "No meter read or water-level reading is recorded for this well." in section
    assert "<table" not in section


def test_the_history_head_offers_the_import_to_a_writer_only():
    well = WellFactory(name="Head well")
    url = reverse("wells:water_level_import")
    writer_html = _page(_client(_user()), well)
    head = writer_html[writer_html.index("Measurement history") - 200:]
    head = head[: head.index("Meter reads and depth to water")]
    assert 'class="row-between"' in head
    assert f'href="{url}" class="btn-secondary btn-sm">Import water levels</a>' in head
    viewer_html = _page(_client(_user("viewer", read_only=True)), well)
    assert url not in viewer_html


# ---------------------------------------------------------------------------
# The wells list header and the import page
# ---------------------------------------------------------------------------


def test_the_wells_list_header_offers_both_imports_to_a_writer():
    html = _client(_user()).get(reverse("wells:list")).content.decode()
    assert ">Import wells</a>" in html
    assert (
        f'<a href="{reverse("wells:water_level_import")}" class="btn-secondary btn-sm">'
        "Import water levels</a>" in html
    )
    viewer = _client(_user("viewer", read_only=True)).get(reverse("wells:list")).content.decode()
    assert "Import water levels" not in viewer


def test_the_import_page_names_the_columns_it_reads():
    html = unescape(_client(_user()).get(reverse("wells:water_level_import")).content.decode())
    assert "Import water levels" in html
    assert "Depth to water" in html
    assert "OpenH2O saves nothing until you press Import on the preview." in html
    assert "OpenH2O skips a row whose well, date and depth are already on file." in html
    assert "Columns OpenH2O reads" in html
    for dwr_column in ("WELL_NAME", "MSMT_DATE", "GSE_GWE", "WLM_QA_DESC", "WLM_DESC", "MSMT_CMT"):
        assert dwr_column in html
    assert 'accept=".csv"' in html
    assert reverse("wells:water_level_import_preview") in html


# ---------------------------------------------------------------------------
# (e) The import
# ---------------------------------------------------------------------------


def test_the_preview_maps_dwrs_columns_and_names_the_well_it_cannot_find():
    wells = _merced_wells()
    prop = _depth_property()
    WaterMeasurement.objects.create(
        name="224 depth to water", measurement_type="groundwater_level", observed_property=prop,
        value=Decimal("105.33"), unit="ft", measurement_date=_local(2025, 3, 7, 9, 0),
        well=wells["224"], source="manual",
    )

    response = _preview(_client(_user()), _csv_upload(DWR_FILE))
    html = unescape(response.content.decode())

    for field, column in FIELD_COLUMNS.items():
        assert f'<select name="{field}"' in html
        select = html[html.index(f'<select name="{field}"'):]
        select = select[: select.index("</select>")]
        assert f'<option value="{column}" selected>' in select
        assert select.count(" selected>") == 1
    assert "OpenH2O found <strong>22</strong> rows and <strong>7</strong> columns" in html
    assert "Import 17 levels" in html
    assert "Update preview" in html
    assert "New levels 17" in html
    assert "Already on file 1" in html
    assert "Errors 4" in html
    assert "4 rows: 20, 21, 22, 23" in html
    assert "MW1013 does not match a well on file." in html
    assert "The file's first 5 rows" in html
    assert not WaterMeasurement.objects.filter(source="imported").exists()


def test_importing_the_dwr_file_saves_depths_and_no_measurement_rows():
    wells = _merced_wells()
    prop = _depth_property()
    WaterMeasurement.objects.create(
        name="224 depth to water", measurement_type="groundwater_level", observed_property=prop,
        value=Decimal("105.33"), unit="ft", measurement_date=_local(2025, 3, 7, 9, 0),
        well=wells["224"], source="manual",
    )
    importer = _user("importer")

    _preview_html, result = _run_import(_client(importer), _csv_upload(DWR_FILE))

    assert "OpenH2O imported 17 water levels and skipped 1 already on file." in unescape(result)
    imported = WaterMeasurement.objects.filter(source="imported")
    assert imported.count() == 17
    assert WaterMeasurement.objects.count() == 18
    assert not imported.filter(well__isnull=True).exists()
    assert set(imported.values_list("recorded_by", flat=True)) == {importer.pk}

    twelve = imported.filter(well=wells["212"]).order_by("measurement_date")
    assert twelve.count() == 4
    first, second, third, fourth = twelve
    assert first.value is None and first.no_measurement_reason == "Can't get tape in casing"
    assert second.value is None and second.no_measurement_reason == "Can't get tape in casing"
    assert third.value == Decimal("98.92") and third.no_measurement_reason == ""
    assert fourth.value == Decimal("110.17")
    assert third.method == "Electric sounder measurement"
    assert first.method == ""
    assert timezone.localtime(first.measurement_date) == _local(2024, 3, 8, 15, 15)

    row = imported.get(well=wells["162"], measurement_date=_local(2024, 3, 1, 9, 1))
    assert row.value == Decimal("57.08")
    assert row.name == "162 depth to water"
    assert row.measurement_type == "groundwater_level"
    assert row.observed_property == prop
    assert row.unit == "ft"
    assert "DWR quality: Oil or foreign substance in casing" in row.notes
    assert row.method == "Electric sounder measurement"

    # The 224 level that was already on file is left as it was.
    assert WaterMeasurement.objects.filter(well=wells["224"], source="manual").count() == 1


def test_importing_the_same_file_again_saves_nothing_new():
    _merced_wells()
    client = _client(_user())
    _run_import(client, _csv_upload(DWR_FILE))
    before = WaterMeasurement.objects.count()
    assert before == 18

    _preview_html, result = _run_import(client, _csv_upload(DWR_FILE))

    assert "OpenH2O imported 0 water levels and skipped 18 already on file." in unescape(result)
    assert WaterMeasurement.objects.count() == before


def test_a_well_is_found_by_wcr_number_and_every_row_rule_has_its_sentence():
    alpha = WellFactory(name="Alpha", wcr_number="WCR0123456")
    WellFactory(name="Twin one", state_well_number="TWIN")
    WellFactory(name="Twin two", wcr_number="twin")
    client = _client(_user())

    preview, result = _run_import(client, _csv_upload(EXTRA_FILE))
    html = unescape(preview.content.decode())

    assert "TWIN matches more than one well on file." in html
    assert "This row has no well." in html
    assert "Not a listed reason is not one of the reasons on the well page." in html
    assert "This row has no depth and no reason." in html
    assert "x12 is not a number." in html
    assert "not-a-date is not a date OpenH2O can read." in html
    assert "New levels 3" in html
    assert "Already on file 1" in html
    assert "Errors 6" in html
    assert "OpenH2O imported 3 water levels and skipped 1 already on file." in unescape(result)

    levels = WaterMeasurement.objects.filter(well=alpha).order_by("measurement_date")
    assert levels.count() == 3
    spring, quality, dry = levels
    # Found by WCR number, M/D/YYYY with no time is noon local, the method is DWR's.
    assert spring.value == Decimal("88.5")
    assert timezone.localtime(spring.measurement_date) == _local(2025, 3, 5, 12, 0)
    assert spring.method == "Steel tape measurement"
    assert spring.notes == "Spring round"
    # Depth row with a reason and a method that is not on the list.
    assert quality.value == Decimal("-1.5")
    assert quality.method == ""
    assert "DWR quality: Special/Other" in quality.notes
    assert "Method: Dip meter" in quality.notes
    # A reason in any case is saved in DWR's wording, with the time the file gave.
    assert dry.value is None and dry.no_measurement_reason == "Pumping"
    assert timezone.localtime(dry.measurement_date) == _local(2025, 3, 7, 8, 15)
    # The repeat of the first row (found by the same number in lower case) was skipped.
    assert WaterMeasurement.objects.count() == 3


def test_a_time_in_the_file_is_kept_in_the_sites_time_zone():
    well = WellFactory(name="Clock well")
    text = "well,date,depth\nClock well,3/5/2025 14:30,70\nClock well,2025-03-06,71\n"
    _run_import(
        _client(_user()), _csv_upload(text),
        {"map:well": "well", "map:date": "date", "map:depth": "depth"},
    )
    first, second = WaterMeasurement.objects.filter(well=well).order_by("measurement_date")
    assert timezone.localtime(first.measurement_date) == _local(2025, 3, 5, 14, 30)
    assert timezone.localtime(second.measurement_date) == _local(2025, 3, 6, 12, 0)


def test_columns_are_matched_without_regard_to_case_or_spaces_and_by_other_names():
    well = WellFactory(name="Named well", state_well_number="SWN-1")
    text = (
        " State_Well_Number ,Measurement_Date,Depth_To_Water,No_Measurement_Reason,Method,Notes\n"
        "SWN-1,2025-03-05,70.25,,Unknown,Hand sheet\n"
    )
    preview = _preview(_client(_user()), _csv_upload(text))
    html = preview.content.decode()
    assert '<option value=" State_Well_Number " selected>' in html
    assert '<option value="Measurement_Date" selected>' in html
    assert '<option value="Depth_To_Water" selected>' in html
    assert '<option value="No_Measurement_Reason" selected>' in html
    assert "New levels 1" in html
    del well


def test_a_person_can_point_a_field_at_another_column_and_update_the_preview():
    WellFactory(name="Pointed well", state_well_number="SWN-2")
    text = "id,alt,when,feet\nPointed well,SWN-2,2025-03-05,70\n"
    client = _client(_user())
    preview = _preview(client, _csv_upload(text))
    token = token_of(preview)
    mapping = {"map:well": "alt", "map:date": "when", "map:depth": "feet"}
    update = client.post(
        reverse("wells:water_level_import_preview"), {"token": token, **mapping},
        HTTP_HX_REQUEST="true",
    )
    html = update.content.decode()
    assert '<option value="alt" selected>' in html
    assert "New levels 1" in html
    status = import_and_read(client, reverse("wells:water_level_import_commit"), token, mapping)
    assert "OpenH2O imported 1 water level and skipped 0 already on file." in status.content.decode()


def test_a_mapping_without_a_well_a_date_and_a_depth_or_reason_is_not_imported():
    WellFactory(name="Refused well")
    text = "well,date,depth\nRefused well,2025-03-05,70\n"
    client = _client(_user())
    token = token_of(_preview(client, _csv_upload(text)))
    response = client.post(
        reverse("wells:water_level_import_commit"),
        {"token": token, "map:well": "well", "map:date": "date"},
        HTTP_HX_REQUEST="true",
    )
    assert "Match a column to Well and Date, and to Depth or Reason, then press Import." in response.content.decode()
    assert not WaterMeasurement.objects.exists()


@pytest.mark.parametrize(
    "name, text, sentence",
    [
        ("levels.xlsx", "a,b\n1,2\n", "This page imports CSV files only. Save the file as CSV and upload it again."),
        ("levels.csv", "well,date,depth\n", "This file has column names but no rows below them."),
        ("levels.csv", "", "This file has no column names on its first line."),
    ],
)
def test_a_file_that_cannot_be_read_gets_one_sentence(name, text, sentence):
    response = _preview(_client(_user()), _csv_upload(text, name))
    assert unescape(response.content.decode()).count(sentence) == 1


def test_a_preview_with_no_file_asks_for_one():
    response = _client(_user()).post(
        reverse("wells:water_level_import_preview"), {}, HTTP_HX_REQUEST="true"
    )
    assert "Choose a file to upload." in response.content.decode()


def test_the_import_is_a_registered_kind_of_pending_import():
    from core import pending_imports

    kind = pending_imports.KINDS["water_levels"]
    assert kind.commit == "wells.water_level_import:commit_stored_water_levels"
    assert kind.commit_url_name == "wells:water_level_import_commit"
    assert kind.extensions == (".csv",)
    assert reverse(kind.commit_url_name) == "/wells/water-levels/import/commit/"


# ---------------------------------------------------------------------------
# (f) A Viewer is refused on every write route
# ---------------------------------------------------------------------------


def test_a_viewer_is_refused_on_all_three_posts_and_the_import_page():
    viewer = _client(_user("viewer", read_only=True))
    operator = _client(_user("operator"))
    well = WellFactory(name="Viewer well")
    routes = [
        reverse("wells:water_level_add", args=[well.pk]),
        reverse("wells:water_level_import_preview"),
        reverse("wells:water_level_import_commit"),
    ]
    for url in routes:
        response = viewer.post(url, {"level_date": "2025-03-07", "depth_ft": "70"})
        assert response.status_code == 403, url
        assert READ_ONLY_MESSAGE in response.content.decode(), url
    page = viewer.get(reverse("wells:water_level_import"))
    assert page.status_code == 403
    assert not WaterMeasurement.objects.exists()
    assert operator.get(reverse("wells:water_level_import")).status_code == 200


def test_the_post_routes_refuse_a_get():
    client = _client(_user())
    well = WellFactory(name="Get well")
    for url in (
        reverse("wells:water_level_add", args=[well.pk]),
        reverse("wells:water_level_import_preview"),
        reverse("wells:water_level_import_commit"),
    ):
        assert client.get(url).status_code == 405


# ---------------------------------------------------------------------------
# (g) Change history
# ---------------------------------------------------------------------------


def test_a_typed_level_is_recorded_in_the_change_history_with_who_typed_it():
    writer = _user()
    well = WellFactory(name="History well")
    _post_level(
        _client(writer), well, method="Steel tape measurement", depth_ft="70.5",
        notes="Recorded",
    )
    _post_level(
        _client(writer), well, level_date="2025-10-17", no_measurement="1",
        reason="Dry well",
    )

    typed, unmeasured = WaterMeasurement.objects.filter(well=well).order_by("measurement_date")
    url = reverse("wells:water_level_add", args=[well.pk])

    event = typed.events.get(pgh_label="insert")
    assert event.value == Decimal("70.5")
    assert event.method == "Steel tape measurement"
    assert event.no_measurement_reason == ""
    assert event.pgh_context.metadata == {"user": writer.pk, "url": url}

    event = unmeasured.events.get(pgh_label="insert")
    assert event.value is None
    assert event.no_measurement_reason == "Dry well"
    assert event.pgh_context.metadata == {"user": writer.pk, "url": url}


def test_an_imported_level_is_recorded_in_the_change_history_with_who_imported_it():
    WellFactory(name="Imported history well")
    importer = _user("importer")
    text = "well,date,depth\nImported history well,2025-03-05,70\n"
    _run_import(_client(importer), _csv_upload(text), {
        "map:well": "well", "map:date": "date", "map:depth": "depth",
    })
    (level,) = WaterMeasurement.objects.filter(source="imported")
    event = level.events.get(pgh_label="insert")
    assert event.pgh_context.metadata == {
        "user": importer.pk, "url": reverse("wells:water_level_import_commit"),
    }
