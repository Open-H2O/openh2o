# SPDX-License-Identifier: AGPL-3.0-or-later
"""
ISS-180 D1: a water right's front door (146-02 Task 1).

Three doors proven here, each RED against the unfixed tree (the exact quotes
live in 146-02-EVIDENCE.md):

  1. A right can be created through a real form, with a season, and the
     right's page shows it back (season, rate, permit/license numbers,
     purpose of use, net acreage, state status beside the type).
  2. The rights list carries "+ Add right" and "Import" and no longer says
     "Django admin" anywhere on the page.
  3. The state's own rights LIST CSV imports through a screen
     (`/surface/rights/import/`), keyed on `right_id` (`APPLICATION_NUMBER`)
     with a dedup that skips rather than overwrites a repeat.
"""
from decimal import Decimal

import factory
import pytest
from django.contrib.auth.hashers import make_password
from django.test import Client
from django.urls import reverse

from surface.models import WaterRight, WaterRightType
from tests.factories import WaterRightTypeFactory

pytestmark = pytest.mark.django_db


class _UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"rightsuser{n}")
    email = factory.Sequence(lambda n: f"rightsuser{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True


@pytest.fixture
def auth_client(db):
    c = Client()
    c.force_login(_UserFactory())
    return c


# ---------------------------------------------------------------------------
# 1. Create through the form, with a season
# ---------------------------------------------------------------------------


def test_create_through_form_with_a_season(auth_client):
    right_type = WaterRightTypeFactory(name="Post-1914 Appropriative", code="POST14X")

    resp = auth_client.post(reverse("surface:water_right_create"), {
        "right_id": "A999999",
        "right_type": right_type.pk,
        "holder_name": "Test District",
        "status": "active",
        "state_status": "Licensed",
        "priority_date": "",
        "face_value_acre_feet": "16716.9000",
        "source_name": "MERCED RIVER",
        "watershed": "SAN JOAQUIN VALLEY FLOOR",
        "permit_number": "000893",
        "license_number": "005397",
        "purpose_of_use": "Irrigation",
        "net_acreage": "2400.00",
        "max_rate_cfs": "34.4000",
        "direct_season_start_month": "3",
        "direct_season_start_day": "1",
        "direct_season_end_month": "10",
        "direct_season_end_day": "31",
        "storage_season_start_month": "",
        "storage_season_start_day": "",
        "storage_season_end_month": "",
        "storage_season_end_day": "",
        "calwatrs_pin": "",
        "notes": "",
    })
    right = WaterRight.objects.get(right_id="A999999")
    assert resp.status_code == 302
    assert resp.url == reverse("surface:detail", args=[right.pk])
    assert right.direct_season_start_month == 3
    assert right.direct_season_start_day == 1
    assert right.direct_season_end_month == 10
    assert right.direct_season_end_day == 31
    assert right.max_rate_cfs == Decimal("34.4000")
    assert right.license_number == "005397"
    assert right.permit_number == "000893"

    # The right's page shows the season, rate, numbers and use back.
    detail = auth_client.get(reverse("surface:detail", args=[right.pk]))
    body = detail.content.decode()
    assert "Mar 1 to Oct 31 (direct diversion)" in body
    assert "34.40 cfs" in body
    assert "005397" in body and "000893" in body
    assert "Irrigation" in body
    assert "Post-1914 Appropriative, Licensed" in body


def test_season_start_with_no_end_is_a_form_error(auth_client):
    right_type = WaterRightTypeFactory()
    resp = auth_client.post(reverse("surface:water_right_create"), {
        "right_id": "A999998",
        "right_type": right_type.pk,
        "holder_name": "Test District",
        "status": "active",
        "direct_season_start_month": "3",
        "direct_season_start_day": "1",
        "direct_season_end_month": "",
        "direct_season_end_day": "",
        "storage_season_start_month": "",
        "storage_season_start_day": "",
        "storage_season_end_month": "",
        "storage_season_end_day": "",
    })
    assert resp.status_code == 200  # re-renders the form with the error
    assert not WaterRight.objects.filter(right_id="A999998").exists()
    assert "no end" in resp.content.decode()


def test_edit_changes_a_field(auth_client):
    right_type = WaterRightTypeFactory()
    right = WaterRight.objects.create(
        right_id="A999997", right_type=right_type, holder_name="Old Name",
    )
    resp = auth_client.post(reverse("surface:water_right_edit", args=[right.pk]), {
        "right_id": "A999997",
        "right_type": right_type.pk,
        "holder_name": "New Name",
        "status": "active",
        "direct_season_start_month": "", "direct_season_start_day": "",
        "direct_season_end_month": "", "direct_season_end_day": "",
        "storage_season_start_month": "", "storage_season_start_day": "",
        "storage_season_end_month": "", "storage_season_end_day": "",
    })
    right.refresh_from_db()
    assert resp.status_code == 302
    assert right.holder_name == "New Name"


# ---------------------------------------------------------------------------
# 2. The list carries the two actions and not "Django admin"
# ---------------------------------------------------------------------------


def test_list_has_add_and_import_actions_and_not_django_admin(auth_client):
    resp = auth_client.get(reverse("surface:water_rights_list"))
    body = resp.content.decode()
    assert reverse("surface:water_right_create") in body
    assert reverse("surface:water_right_import") in body
    assert "Add a right, or import the state's rights list." in body
    assert "Django admin" not in body


# ---------------------------------------------------------------------------
# 3. The state's own rights LIST CSV imports through a screen
# ---------------------------------------------------------------------------

# The shape-1 dataset's real header and its first data row (A001885), copied
# verbatim (read 2026-09-20 from
# six-shapes-2026-09/datasets/shape-1-surface-diverter/water-right.csv).
# PRIORITY_DATE is blank on this row and stays null on import.
RIGHTS_LIST_HEADER = (
    "APPLICATION_NUMBER,WATER_RIGHT_TYPE,WATER_RIGHT_STATUS,PRIMARY_OWNER_NAME,"
    "PRIMARY_OWNER_ENTITY_TYPE,SOURCE_NAME,TRIB_DESC,WATERSHED,COUNTY,"
    "FACE_VALUE_AMOUNT,FACE_VALUE_UNITS,MAX_DD_APPL,MAX_DD_UNITS,PRIORITY_DATE,"
    "LICENSE_ID,PERMIT_ID,LICENSE_ORIGINAL_ISSUE_DATE,USE_CODE,USE_NET_ACREAGE,"
    "POD_COUNT,DIRECT_SEASON_START_MONTH_1,DIRECT_DIV_SEASON_START_DAY_1,"
    "DIRECT_DIV_SEASON_END_MONTH_1,DIRECT_DIV_SEASON_END_DAY_1,"
    "DAYS_IN_DIRECT_DIV_1,DIRECT_SEASON_COUNT,TOTAL_DAYS_DIRECT_SEASON,"
    "STORAGE_SEASON_START_MONTH_1,STORAGE_SEASON_START_DAY_1,"
    "STORAGE_SEASON_END_MONTH_1,STORAGE_SEASON_END_DAY_1,"
    "DAYS_IN_STORAGE_SEASON_1,STORAGE_SEASON_COUNT,TOTAL_AMOUNT_STORAGE_SEASON"
)
RIGHTS_LIST_ROW_A001885 = (
    "A001885,Appropriative,Licensed,STEVINSON WATER DISTRICT,Corporation,"
    "MERCED RIVER,NA,SAN JOAQUIN VALLEY FLOOR,Merced,16716.9,Acre-feet per Year,"
    "34.4,Cubic Feet per Second,,005397,000893,1959-01-14,Irrigation,2400,3,3,1,"
    "10,31,245,1,245,,,,,,1,0"
)
RIGHTS_LIST_CSV = RIGHTS_LIST_HEADER + "\n" + RIGHTS_LIST_ROW_A001885 + "\n"


def _seed_shape1_types():
    """The seeded names ``seed_water_right_types`` loads; only the one this
    fixture's bare "Appropriative" crosswalks to is needed for these tests."""
    WaterRightType.objects.get_or_create(
        code="POST14", defaults={"name": "Post-1914 Appropriative"}
    )


def _upload_csv(client, contents):
    from django.core.files.uploadedfile import SimpleUploadedFile

    upload = SimpleUploadedFile(
        "water-right.csv", contents.encode("utf-8"), content_type="text/csv"
    )
    return client.post(
        reverse("surface:water_right_import_preview"), {"file": upload},
        HTTP_HX_REQUEST="true",
    )


def _commit_from_preview(client, preview_resp, csv_text):
    """Post the confirmed mapping + the parsed rows to commit, the same
    round trip the browser makes from the mapping partial.

    ``rows_json`` is pulled out of the rendered partial (an HTML-escaped JSON
    string, unescaped here) so this proves the real value the view rendered
    round-trips; the column -> field mapping is rebuilt with
    ``importer.auto_map_columns`` against the same header rather than
    scraping each <select>'s "selected" option, which is equivalent to an
    operator accepting every auto-detected guess unchanged.
    """
    import csv
    import html
    import io
    import re

    from surface import importer

    body = preview_resp.content.decode()
    rows_json_match = re.search(r'name="rows_json" value="([^"]*)"', body)
    assert rows_json_match, "rows_json hidden field missing from the mapping partial"
    rows_json = html.unescape(rows_json_match.group(1))

    columns = next(csv.reader(io.StringIO(csv_text)))
    mapping = importer.auto_map_columns(columns)

    post_data = {"rows_json": rows_json}
    for field, source_col in mapping.items():
        post_data[f"map:{field}"] = source_col

    return client.post(
        reverse("surface:water_right_import_commit"), post_data, HTTP_HX_REQUEST="true"
    )


def test_list_import_creates_a001885_with_season_and_rate(auth_client):
    _seed_shape1_types()

    preview = _upload_csv(auth_client, RIGHTS_LIST_CSV)
    assert preview.status_code == 200

    commit = _commit_from_preview(auth_client, preview, RIGHTS_LIST_CSV)
    assert commit.status_code == 200
    assert "Created 1" in commit.content.decode()

    right = WaterRight.objects.get(right_id="A001885")
    assert right.priority_date is None  # blank in the fixture, stays null
    assert right.direct_season_start_month == 3
    assert right.direct_season_start_day == 1
    assert right.direct_season_end_month == 10
    assert right.direct_season_end_day == 31
    assert right.max_rate_cfs == Decimal("34.4000")
    assert right.license_number == "005397"
    assert right.permit_number == "000893"
    assert right.purpose_of_use == "Irrigation"
    assert right.net_acreage == Decimal("2400.00")
    assert right.right_type.name == "Post-1914 Appropriative"
    assert right.state_status == "Licensed"
    assert right.holder_name == "STEVINSON WATER DISTRICT"
    assert right.source_name == "MERCED RIVER"
    assert right.watershed == "SAN JOAQUIN VALLEY FLOOR"


def test_second_import_of_the_same_file_creates_nothing_and_skips_one(auth_client):
    _seed_shape1_types()

    first_preview = _upload_csv(auth_client, RIGHTS_LIST_CSV)
    _commit_from_preview(auth_client, first_preview, RIGHTS_LIST_CSV)
    assert WaterRight.objects.filter(right_id="A001885").count() == 1

    second_preview = _upload_csv(auth_client, RIGHTS_LIST_CSV)
    second_commit = _commit_from_preview(auth_client, second_preview, RIGHTS_LIST_CSV)
    body = second_commit.content.decode()
    assert "Created 0" in body
    assert "Skipped 1" in body
    assert "already exists" in body
    assert WaterRight.objects.filter(right_id="A001885").count() == 1


def test_unknown_water_right_type_is_a_row_error(auth_client):
    csv_body = RIGHTS_LIST_HEADER + "\n" + RIGHTS_LIST_ROW_A001885.replace(
        "Appropriative", "Mystery Type", 1
    ) + "\n"
    preview = _upload_csv(auth_client, csv_body)
    commit = _commit_from_preview(auth_client, preview, csv_body)
    body = commit.content.decode()
    assert "Created 0" in body
    assert "matches no seeded water right type" in body
    assert not WaterRight.objects.filter(right_id="A001885").exists()
