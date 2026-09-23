# SPDX-License-Identifier: AGPL-3.0-or-later
"""
146-04 Task 2 (D7, ISS-184): production by month and source, in bulk, against
a water system.

The fixture below is copied verbatim (columns trimmed to the seven this
importer reads; every value is the state's own) from
``~/Documents/Vadose/Products/openh2o/six-shapes-2026-09/datasets/shape-2-small-water-system/ear-2022-production.csv``
-- Le Grand Community Services District, PWSID CA2410011, real 2022
production. The harness and the real world stay apart (never read from disk
at test time), so the text lives here as a string, the same way
``tests/test_diversion_import.py`` carries its own state-layout fixture.

The operator's-log fixture is copied verbatim from
``operators-monthly-production-log-2022.csv`` in the same folder -- the same
twelve real monthly figures, restated in the Small Water System eAR
template's Section 5 layout (PROVENANCE.md: "This file is a restatement of
the state's own rows... No quantity in it is new").

The acceptance arithmetic (PROVENANCE.md, verified against the actual file
before writing this fixture): twelve GW months sum to 91,371,800 gallons =
280.41 acre-feet at 325,851 gallons per acre-foot.
"""
import io
import json
from decimal import Decimal

import factory
import pytest
from django.contrib.auth.hashers import make_password
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client
from django.urls import reverse

from drinking import production_import
from drinking.models import SystemProduction, WaterSystem

pytestmark = pytest.mark.django_db

# ---------------------------------------------------------------------------
# Fixtures: real 2022 production, Le Grand CSD (CA2410011), both layouts.
# ---------------------------------------------------------------------------

EAR_CSV_TEXT = (
    "PWSID,Year,Month,DateStartOfMonth,TypeCode,Units of Measure As Reported,Quantity as in Units Reported\n"
    "CA2410011,2022,January,1/1/2022,GW,G,4007800\n"
    "CA2410011,2022,January,1/1/2022,SW,G,0\n"
    "CA2410011,2022,January,1/1/2022,Purchased,G,0\n"
    "CA2410011,2022,January,1/1/2022,Sold,G,0\n"
    "CA2410011,2022,January,1/1/2022,Recycled,G,0\n"
    "CA2410011,2022,January,1/1/2022,NonPotable,G,0\n"
    "CA2410011,2022,January,1/1/2022,NonPotableSold,G,0\n"
    "CA2410011,2022,February,2/1/2022,GW,G,3567300\n"
    "CA2410011,2022,February,2/1/2022,SW,G,0\n"
    "CA2410011,2022,February,2/1/2022,Purchased,G,0\n"
    "CA2410011,2022,February,2/1/2022,Sold,G,0\n"
    "CA2410011,2022,February,2/1/2022,Recycled,G,0\n"
    "CA2410011,2022,February,2/1/2022,NonPotable,G,0\n"
    "CA2410011,2022,February,2/1/2022,NonPotableSold,G,0\n"
    "CA2410011,2022,March,3/1/2022,GW,G,4037700\n"
    "CA2410011,2022,March,3/1/2022,SW,G,0\n"
    "CA2410011,2022,March,3/1/2022,Purchased,G,0\n"
    "CA2410011,2022,March,3/1/2022,Sold,G,0\n"
    "CA2410011,2022,March,3/1/2022,Recycled,G,0\n"
    "CA2410011,2022,March,3/1/2022,NonPotable,G,0\n"
    "CA2410011,2022,March,3/1/2022,NonPotableSold,G,0\n"
    "CA2410011,2022,April,4/1/2022,GW,G,6456000\n"
    "CA2410011,2022,April,4/1/2022,SW,G,0\n"
    "CA2410011,2022,April,4/1/2022,Purchased,G,0\n"
    "CA2410011,2022,April,4/1/2022,Sold,G,0\n"
    "CA2410011,2022,April,4/1/2022,Recycled,G,0\n"
    "CA2410011,2022,April,4/1/2022,NonPotable,G,0\n"
    "CA2410011,2022,April,4/1/2022,NonPotableSold,G,0\n"
    "CA2410011,2022,May,5/1/2022,GW,G,9151000\n"
    "CA2410011,2022,May,5/1/2022,SW,G,0\n"
    "CA2410011,2022,May,5/1/2022,Purchased,G,0\n"
    "CA2410011,2022,May,5/1/2022,Sold,G,0\n"
    "CA2410011,2022,May,5/1/2022,Recycled,G,0\n"
    "CA2410011,2022,May,5/1/2022,NonPotable,G,0\n"
    "CA2410011,2022,May,5/1/2022,NonPotableSold,G,0\n"
    "CA2410011,2022,June,6/1/2022,GW,G,10478000\n"
    "CA2410011,2022,June,6/1/2022,SW,G,0\n"
    "CA2410011,2022,June,6/1/2022,Purchased,G,0\n"
    "CA2410011,2022,June,6/1/2022,Sold,G,0\n"
    "CA2410011,2022,June,6/1/2022,Recycled,G,0\n"
    "CA2410011,2022,June,6/1/2022,NonPotable,G,0\n"
    "CA2410011,2022,June,6/1/2022,NonPotableSold,G,0\n"
    "CA2410011,2022,July,7/1/2022,GW,G,22616900\n"
    "CA2410011,2022,July,7/1/2022,SW,G,0\n"
    "CA2410011,2022,July,7/1/2022,Purchased,G,0\n"
    "CA2410011,2022,July,7/1/2022,Sold,G,0\n"
    "CA2410011,2022,July,7/1/2022,Recycled,G,0\n"
    "CA2410011,2022,July,7/1/2022,NonPotable,G,0\n"
    "CA2410011,2022,July,7/1/2022,NonPotableSold,G,0\n"
    "CA2410011,2022,August,8/1/2022,GW,G,10352700\n"
    "CA2410011,2022,August,8/1/2022,SW,G,0\n"
    "CA2410011,2022,August,8/1/2022,Purchased,G,0\n"
    "CA2410011,2022,August,8/1/2022,Sold,G,0\n"
    "CA2410011,2022,August,8/1/2022,Recycled,G,0\n"
    "CA2410011,2022,August,8/1/2022,NonPotable,G,0\n"
    "CA2410011,2022,August,8/1/2022,NonPotableSold,G,0\n"
    "CA2410011,2022,September,9/1/2022,GW,G,8817200\n"
    "CA2410011,2022,September,9/1/2022,SW,G,0\n"
    "CA2410011,2022,September,9/1/2022,Purchased,G,0\n"
    "CA2410011,2022,September,9/1/2022,Sold,G,0\n"
    "CA2410011,2022,September,9/1/2022,Recycled,G,0\n"
    "CA2410011,2022,September,9/1/2022,NonPotable,G,0\n"
    "CA2410011,2022,September,9/1/2022,NonPotableSold,G,0\n"
    "CA2410011,2022,October,10/1/2022,GW,G,5755000\n"
    "CA2410011,2022,October,10/1/2022,SW,G,0\n"
    "CA2410011,2022,October,10/1/2022,Purchased,G,0\n"
    "CA2410011,2022,October,10/1/2022,Sold,G,0\n"
    "CA2410011,2022,October,10/1/2022,Recycled,G,0\n"
    "CA2410011,2022,October,10/1/2022,NonPotable,G,0\n"
    "CA2410011,2022,October,10/1/2022,NonPotableSold,G,0\n"
    "CA2410011,2022,November,11/1/2022,GW,G,3287300\n"
    "CA2410011,2022,November,11/1/2022,SW,G,0\n"
    "CA2410011,2022,November,11/1/2022,Purchased,G,0\n"
    "CA2410011,2022,November,11/1/2022,Sold,G,0\n"
    "CA2410011,2022,November,11/1/2022,Recycled,G,0\n"
    "CA2410011,2022,November,11/1/2022,NonPotable,G,0\n"
    "CA2410011,2022,November,11/1/2022,NonPotableSold,G,0\n"
    "CA2410011,2022,December,12/1/2022,GW,G,2844900\n"
    "CA2410011,2022,December,12/1/2022,SW,G,0\n"
    "CA2410011,2022,December,12/1/2022,Purchased,G,0\n"
    "CA2410011,2022,December,12/1/2022,Sold,G,0\n"
    "CA2410011,2022,December,12/1/2022,Recycled,G,0\n"
    "CA2410011,2022,December,12/1/2022,NonPotable,G,0\n"
    "CA2410011,2022,December,12/1/2022,NonPotableSold,G,0\n"
)

OPERATOR_LOG_CSV_TEXT = (
    "Date/Month,Water Produced from Groundwater (Wells),Water Produced from Surface Water,"
    "Finished Water Purchased or Received from another PWS,Total Amount of Potable Water,"
    "Water Sold to Another PWS,Non-potable (exclude recycled),Recycled\n"
    "Maximum Day,,,,,,,\n"
    "January,4007800,0,0,4007800,0,0,0\n"
    "February,3567300,0,0,3567300,0,0,0\n"
    "March,4037700,0,0,4037700,0,0,0\n"
    "April,6456000,0,0,6456000,0,0,0\n"
    "May,9151000,0,0,9151000,0,0,0\n"
    "June,10478000,0,0,10478000,0,0,0\n"
    "July,22616900,0,0,22616900,0,0,0\n"
    "August,10352700,0,0,10352700,0,0,0\n"
    "September,8817200,0,0,8817200,0,0,0\n"
    "October,5755000,0,0,5755000,0,0,0\n"
    "November,3287300,0,0,3287300,0,0,0\n"
    "December,2844900,0,0,2844900,0,0,0\n"
    "Annual Total,91371800,0,0,91371800,0,0,0\n"
    "Percent Treated,,,,,,,\n"
)

EXPECTED_GW_GALLONS = Decimal("91371800")
EXPECTED_GW_ACRE_FEET = Decimal("280.41")


class _UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"prodimporter{n}")
    email = factory.Sequence(lambda n: f"prodimporter{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True


@pytest.fixture
def le_grand():
    """The deployment's one water system, for the views that assume there is one.

    ``production``, ``production_add`` and the two production-import views all
    read ``WaterSystem.objects.first()`` (single-tenant by design: one
    deployment serves one agency). That is safe in a real deployment but not
    in the full suite: ``tests/test_merced_drinking_seed.py`` seeds a real
    City of Merced system through ``django_db_blocker`` on purpose, outside
    any test's transaction, so its 22k-result demonstration does not re-import
    once per test in that module -- and it carries no teardown, so that row
    outlives its own module for the rest of the pytest session. Collection
    order puts that module before this one ("merced" < "production"), so a
    full run leaves Merced's system sitting at the lower primary key and
    ``.first()`` (unordered, so Django orders by pk) returns IT instead of the
    system this fixture just created -- the two tests that go through the view
    layer then see an empty, wrong system and fail, while every test that
    talks to the model or the importer directly still passes. Isolation runs
    and ``--lf`` never execute the Merced module, so they never show it. The
    fix is here, not in Merced's seed (whose no-teardown design is deliberate
    and stated in its own docstring) and not in the view (whose single-tenant
    assumption is the platform's own design, `CLAUDE.md`): this fixture's job
    is "the deployment's one system", so it clears any other one first, the
    same way `tests/test_drinking_onboard_chain.py::test_unknown_system_says_onboard_first`
    already does for the same reason.
    """
    WaterSystem.objects.all().delete()
    return WaterSystem.objects.create(
        pwsid="CA2410011",
        name="LE GRAND COMM SERVICES DIST",
        activity_status="A",
        pws_type="CWS",
        state_classification="C",
        primary_source_code="GW",
    )


@pytest.fixture
def auth_client(db):
    c = Client()
    c.force_login(_UserFactory())
    return c


def _parse(text, filename="production.csv"):
    return production_import.parse_csv(io.StringIO(text), filename)


# ---------------------------------------------------------------------------
# recognise_layout
# ---------------------------------------------------------------------------


def test_recognises_ear_layout():
    columns, _rows = _parse(EAR_CSV_TEXT)
    assert production_import.recognise_layout(columns) == "ear"


def test_recognises_operator_log_layout():
    columns, _rows = _parse(OPERATOR_LOG_CSV_TEXT)
    assert production_import.recognise_layout(columns) == "operator_log"


def test_unrecognised_layout_raises_naming_headers():
    with pytest.raises(ImportError) as exc_info:
        production_import.recognise_layout(["foo", "bar"])
    assert "foo" in str(exc_info.value)
    assert "bar" in str(exc_info.value)


# ---------------------------------------------------------------------------
# The eAR layout, on Le Grand's real 2022 file
# ---------------------------------------------------------------------------


def test_ear_import_lands_twelve_gw_months_summing_to_the_real_total(le_grand):
    columns, rows = _parse(EAR_CSV_TEXT)

    result = production_import.import_production_rows(
        columns, rows, system=le_grand, dry_run=False,
    )

    assert result["layout"] == "ear"
    # 84 rows: 12 months x the eAR's seven TypeCodes, NonPotableSold among
    # them (ISS-206). The state's unmodified file imports with no row errors.
    assert result["created"] == 84
    assert result["errors"] == []

    ns_records = SystemProduction.objects.filter(system=le_grand, type_code="NS")
    assert ns_records.count() == 12
    assert all(r.volume_as_reported == 0 for r in ns_records)

    gw_records = SystemProduction.objects.filter(system=le_grand, type_code="GW")
    assert gw_records.count() == 12
    total_gallons = sum((r.volume_gallons for r in gw_records), Decimal("0"))
    total_af = sum((r.volume_acre_feet for r in gw_records), Decimal("0"))
    assert total_gallons == EXPECTED_GW_GALLONS
    assert total_af == EXPECTED_GW_ACRE_FEET

    # The SW rows are real zeros, kept as zeros, not dropped as empty.
    sw_records = SystemProduction.objects.filter(system=le_grand, type_code="SW")
    assert sw_records.count() == 12
    assert all(r.volume_as_reported == 0 for r in sw_records)


def test_ear_reimport_creates_nothing(le_grand):
    columns, rows = _parse(EAR_CSV_TEXT)
    production_import.import_production_rows(columns, rows, system=le_grand, dry_run=False)
    first_count = SystemProduction.objects.count()

    columns, rows = _parse(EAR_CSV_TEXT)
    result = production_import.import_production_rows(columns, rows, system=le_grand, dry_run=False)

    assert result["created"] == 0
    assert result["skipped_duplicates"] == 84
    assert SystemProduction.objects.count() == first_count


def test_ear_type_code_outside_the_states_seven_is_a_row_error(le_grand):
    text = EAR_CSV_TEXT.replace(
        "CA2410011,2022,January,1/1/2022,NonPotableSold,G,0",
        "CA2410011,2022,January,1/1/2022,Desalinated,G,0",
    )
    columns, rows = _parse(text)

    result = production_import.import_production_rows(columns, rows, system=le_grand, dry_run=False)

    assert len(result["errors"]) == 1
    assert "Desalinated" in result["errors"][0]["message"]
    assert result["created"] == 83


def test_ear_row_for_another_pwsid_is_a_row_error(le_grand):
    text = EAR_CSV_TEXT.replace("CA2410011,2022,January,1/1/2022,GW,G,4007800", "CA9999999,2022,January,1/1/2022,GW,G,999")
    columns, rows = _parse(text)

    result = production_import.import_production_rows(columns, rows, system=le_grand, dry_run=False)

    mismatched = [e for e in result["errors"] if "CA9999999" in e["message"]]
    assert len(mismatched) == 1
    assert "does not match" in mismatched[0]["message"]


def test_blank_unit_is_a_row_error_until_the_mapping_unit_is_set(le_grand):
    text = (
        "PWSID,Year,Month,DateStartOfMonth,TypeCode,Units of Measure As Reported,Quantity as in Units Reported\n"
        "CA2410011,2022,January,1/1/2022,GW,,4007800\n"
    )
    columns, rows = _parse(text)

    # No unit_for_blank given: a row error, nothing created.
    result = production_import.import_production_rows(columns, rows, system=le_grand, dry_run=False)
    assert result["created"] == 0
    assert len(result["errors"]) == 1
    assert "blank" in result["errors"][0]["message"]
    assert SystemProduction.objects.count() == 0

    # The mapping step's unit for blank rows, set: the row now lands.
    columns, rows = _parse(text)
    result = production_import.import_production_rows(
        columns, rows, system=le_grand, unit_for_blank="G", dry_run=False,
    )
    assert result["created"] == 1
    assert not result["errors"]
    record = SystemProduction.objects.get()
    assert record.unit_as_reported == "G"
    assert record.volume_gallons == Decimal("4007800.00")


def test_ear_duplicate_keys_within_one_file_are_collapsed_and_counted(le_grand):
    text = (
        "PWSID,Year,Month,DateStartOfMonth,TypeCode,Units of Measure As Reported,Quantity as in Units Reported\n"
        "CA2410011,2022,January,1/1/2022,GW,G,4007800\n"
        "CA2410011,2022,January,1/1/2022,GW,G,4007800\n"
    )
    columns, rows = _parse(text)

    result = production_import.import_production_rows(columns, rows, system=le_grand, dry_run=False)

    assert result["created"] == 1
    assert result["duplicate_rows_in_file"] == 1
    assert SystemProduction.objects.count() == 1


# ---------------------------------------------------------------------------
# The operator's monthly log
# ---------------------------------------------------------------------------


def test_operator_log_skips_and_names_the_non_month_rows(le_grand):
    columns, rows = _parse(OPERATOR_LOG_CSV_TEXT)

    result = production_import.import_production_rows(
        columns, rows, system=le_grand, operator_year=2022, dry_run=False,
    )

    labels = {row["label"] for row in result["skipped_rows"]}
    assert labels == {"Maximum Day", "Annual Total", "Percent Treated"}
    # 12 months x 6 source columns = 72 rows; "Total Amount of Potable
    # Water" is a computed total, never read as a source.
    assert result["created"] == 72


def test_operator_log_requires_the_report_year(le_grand):
    columns, rows = _parse(OPERATOR_LOG_CSV_TEXT)

    result = production_import.import_production_rows(columns, rows, system=le_grand, dry_run=False)

    assert result["created"] == 0
    assert any("year" in e["message"].lower() for e in result["errors"])


def test_operator_log_agrees_with_the_ear_file_row_for_row(le_grand):
    columns, rows = _parse(EAR_CSV_TEXT)
    production_import.import_production_rows(columns, rows, system=le_grand, dry_run=False)
    ear_by_key = {
        (r.year, r.month, r.type_code): r.volume_gallons
        for r in SystemProduction.objects.filter(system=le_grand)
    }

    le_grand_2 = WaterSystem.objects.create(
        pwsid="CA2410011X", name="LE GRAND (second instance for comparison)",
    )
    columns, rows = _parse(OPERATOR_LOG_CSV_TEXT)
    production_import.import_production_rows(
        columns, rows, system=le_grand_2, operator_year=2022, operator_unit="G", dry_run=False,
    )
    operator_by_key = {
        (r.year, r.month, r.type_code): r.volume_gallons
        for r in SystemProduction.objects.filter(system=le_grand_2)
    }

    # The operator's log (the template's Section 5) has no NonPotableSold
    # column, so the eAR's NS rows have nothing to agree with; they are all
    # zero in Le Grand's file.
    ear_ns = {k: v for k, v in ear_by_key.items() if k[2] == "NS"}
    assert len(ear_ns) == 12 and all(v == 0 for v in ear_ns.values())
    ear_six = {k: v for k, v in ear_by_key.items() if k[2] != "NS"}
    assert ear_six == operator_by_key


# ---------------------------------------------------------------------------
# The model's own conversions
# ---------------------------------------------------------------------------


def test_model_computes_gallons_and_acre_feet_from_the_unit(le_grand):
    record = SystemProduction.objects.create(
        system=le_grand, year=2022, month=1, type_code="GW",
        volume_as_reported=Decimal("1"), unit_as_reported="MG",
        provenance="typed",
    )
    assert record.volume_gallons == Decimal("1000000.00")
    assert record.volume_acre_feet == (Decimal("1000000") / Decimal("325851")).quantize(Decimal("0.01"))


def test_annual_in_january_flag_set_when_no_other_month_present(le_grand):
    text = (
        "PWSID,Year,Month,DateStartOfMonth,TypeCode,Units of Measure As Reported,Quantity as in Units Reported\n"
        "CA2410011,2022,January,1/1/2022,GW,G,50000000\n"
    )
    columns, rows = _parse(text)

    production_import.import_production_rows(columns, rows, system=le_grand, dry_run=False)

    record = SystemProduction.objects.get()
    assert record.annual_in_january is True


# ---------------------------------------------------------------------------
# The screens: upload page, preview, commit
# ---------------------------------------------------------------------------


def test_production_import_upload_page_reachable(auth_client, le_grand):
    resp = auth_client.get(reverse("drinking:production_import"))
    assert resp.status_code == 200


def test_production_import_preview_shows_layout_and_totals(auth_client, le_grand):
    upload = SimpleUploadedFile("ear-2022-production.csv", EAR_CSV_TEXT.encode(), content_type="text/csv")
    resp = auth_client.post(reverse("drinking:production_import_preview"), {"file": upload})
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "ear" in body
    assert "rows_json" in body


def test_production_import_commit_creates_records_through_the_view(auth_client, le_grand):
    columns, rows = _parse(EAR_CSV_TEXT)

    resp = auth_client.post(reverse("drinking:production_import_commit"), {
        "rows_json": json.dumps(rows),
    })

    assert resp.status_code == 200
    assert SystemProduction.objects.filter(system=le_grand, type_code="GW").count() == 12


# ---------------------------------------------------------------------------
# The year table page
# ---------------------------------------------------------------------------


def test_production_year_table_shows_twelve_months_and_the_total(auth_client, le_grand):
    columns, rows = _parse(EAR_CSV_TEXT)
    production_import.import_production_rows(columns, rows, system=le_grand, dry_run=False)

    resp = auth_client.get(reverse("drinking:production") + "?year=2022")

    assert resp.status_code == 200
    body = resp.content.decode()
    assert "91,371,800" in body
    assert "4,007,800 gal" in body  # January, in the unit Le Grand reported
    # Gallons only (Brent, 146-04 checkpoint, 2026-09-23): acre-feet is the
    # unit of surface diversions and SGMA extraction, not of a drinking
    # water system's production. The model still stores it; the page does
    # not show it.
    assert "280.41" not in body
    assert "acre-feet" not in body.lower()
    # Le Grand's five other sources were zero every month: named once in the
    # head line, not drawn as columns of zeros.
    assert "from groundwater." in body
    assert "Reported as zero every month: surface water, purchased, sold" in body


def test_a_surface_water_system_gets_its_surface_water_column(auth_client, le_grand):
    """Brent at the checkpoint: "What if a drinking water system is using
    surface water as its source?" Every source that carried water gets its
    column; groundwater is not special."""
    from drinking.models import SystemProduction

    for month in range(1, 13):
        SystemProduction.objects.create(
            system=le_grand, year=2023, month=month, type_code="SW",
            volume_as_reported=Decimal("2.5"), unit_as_reported="MG",
            provenance="typed",
        )
        SystemProduction.objects.create(
            system=le_grand, year=2023, month=month, type_code="PU",
            volume_as_reported=Decimal("100000"), unit_as_reported="G",
            provenance="typed",
        )
    body = auth_client.get(
        reverse("drinking:production") + "?year=2023"
    ).content.decode()
    assert "<th>Surface water</th>" in body
    assert "<th>Purchased</th>" in body
    assert "<th>Groundwater</th>" not in body
    assert "2.5 MG" in body
    # 12 x 2.5 MG + 12 x 100,000 gal = 30,000,000 + 1,200,000
    assert "31,200,000 gallons produced or delivered, from surface water, purchased." in body


# ---------------------------------------------------------------------------
# The management command
# ---------------------------------------------------------------------------


def test_management_command_dry_run_writes_nothing(tmp_path, le_grand):
    path = tmp_path / "ear-2022-production.csv"
    path.write_text(EAR_CSV_TEXT)
    out = io.StringIO()

    call_command(
        "import_production", str(path), "--pwsid", le_grand.pwsid, "--dry-run", stdout=out,
    )

    assert "84" in out.getvalue()
    assert SystemProduction.objects.count() == 0


def test_management_command_writes_records(tmp_path, le_grand):
    path = tmp_path / "ear-2022-production.csv"
    path.write_text(EAR_CSV_TEXT)
    out = io.StringIO()

    call_command("import_production", str(path), "--pwsid", le_grand.pwsid, stdout=out)

    assert SystemProduction.objects.filter(system=le_grand).count() == 84
