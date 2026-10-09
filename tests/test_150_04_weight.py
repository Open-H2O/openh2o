# SPDX-License-Identifier: AGPL-3.0-or-later
"""150-04, class WEIGHT (+ the two SMALL-DATA rows S6 and W5).

Each row moved markup around words that stay exactly as they were
(page-verdict/LAYOUT-INVENTORY-150-04.md; the shared rules are the 150-04
block at the end of static/css/app.css):

  W1  the receipt's Meter reading row is secondary (rule D1, `tr.receipt-aside`)
  W2  the worksheet block's title is the block's head (rule D2)
  W3  an unlocated facility's Map rows lead the record grid, full width (rule D3)
  F6  the finish action also sits in the station review's head row (rule D4)
  W5  the surface pane's lower row: each card ends at its content (rule A1)
  S6  the well's Construction section is the right column's last card (rule A3)
  S16b the wizard's several-polygons line at body size

W4 (Download CSV beside the no-filing statement) is pinned where the button
was already pinned: tests/test_reports_pages_explain_themselves.py. W6 (the
detail map's mark) is JavaScript paint and has no test runnable here.

Every test names the assertion that was red before its change. Identities are
fictional (`W150 ...`) so the session-scoped seeds cannot collide with them.
"""
from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.contrib.gis.geos import Point
from django.template.loader import render_to_string
from django.test import Client, override_settings
from django.urls import reverse

from core.modules import is_enabled

pytestmark = pytest.mark.django_db

User = get_user_model()


def _client(username="w150-reader", admin=False):
    user = User.objects.filter(username=username).first()
    if user is None:
        extra = {"is_staff": True, "is_superuser": True} if admin else {}
        user = User.objects.create_user(
            username=username, email=f"{username}@example.com", password="x",
            is_active=True, **extra,
        )
    client = Client()
    client.force_login(user)
    return client


def _squash(html):
    return " ".join(html.split())


# -- W1: the receipt's reference row ---------------------------------------


def test_w1_the_meter_reading_row_is_the_receipts_aside_row():
    from tests.test_calculation_receipt import _well_run
    from tests.factories import ParcelFactory

    parcel = ParcelFactory(parcel_number="W150-APN-001", area_acres=Decimal("12.00"))
    _well_run(parcel)
    resp = _client().get(
        reverse(
            "accounting:calculation_run_detail",
            kwargs={"parcel_id": parcel.pk, "period": "2026-06"},
        )
    )
    assert resp.status_code == 200
    html = resp.content.decode()
    row_start = html.rindex("<tr", 0, html.index('<td class="col-name">Meter reading</td>'))
    # RED before: the row opened as a bare `<tr>`.
    assert html.startswith('<tr class="receipt-aside">', row_start)
    # Only the reference row is secondary; the calculation rows keep the body weight.
    assert html.count("receipt-aside") == 1
    assert "With a meter on this well, its reading would replace the estimate." in html


# -- W2: the worksheet block's head ----------------------------------------


def test_w2_the_point_of_diversion_title_is_the_blocks_head():
    from reporting.models import ReportSubmission, ReportTemplate
    from surface.models import DiversionRecord, PointOfDiversion
    from tests.factories import ReportingPeriodFactory

    template, _ = ReportTemplate.objects.get_or_create(
        report_type="calwatrs_a2", defaults={"name": "W150 CalWATRS Template"}
    )
    period = ReportingPeriodFactory()
    sub = ReportSubmission.objects.create(
        report_template=template, reporting_period=period, status="draft",
    )
    pod = PointOfDiversion.objects.create(
        name="W150 Headgate", location=Point(-120.0, 37.0),
    )
    DiversionRecord.objects.create(
        point_of_diversion=pod, reporting_period=period,
        diversion_type="to_storage", month=date(2025, 1, 1),
        volume_acre_feet=Decimal("1.0"),
    )
    resp = _client().get(reverse("reporting:calwatrs_worksheet", args=[sub.pk]))
    assert resp.status_code == 200
    html = resp.content.decode()
    # RED before: the title was a `.field-label`, a fifth equal field.
    assert '<h2 class="section-header-sm">Point of diversion 1 of 1:' in html
    head = html.split('<h2 class="section-header-sm">', 1)[1].split("</h2>", 1)[0]
    assert "W150 Headgate" in head
    assert 'field-label">Point of diversion' not in html
    # The head sits above the field grid, whose first field is now Water right.
    assert html.index("Point of diversion 1 of 1") < html.index('field-label">Water right')
    for label in ("Water right", "Holder", "Right type", "CalWATRS PIN"):
        assert f'<div class="field-label">{label}</div>' in html, label


# -- W3: an unlocated facility's Map rows ----------------------------------


@pytest.mark.skipif(not is_enabled("drinking"), reason="the drinking module is not installed")
def test_w3_on_a_facility_with_no_location_the_map_row_is_the_first_field_group():
    from tests.factories import SystemFacilityFactory

    facility = SystemFacilityFactory(
        facility_id="W150", name="W150 TREATMENT PLANT", facility_type="TP",
        location=None,
    )
    resp = _client().get(reverse("drinking:facility_detail", args=[facility.pk]))
    assert resp.status_code == 200
    html = resp.content.decode()
    grid = html.split('<div class="form-grid-2col mt-md">', 1)[1]
    first_group = grid.split('<div class="field-group', 2)[1]
    first_label = first_group.split('<div class="field-label">', 1)[1].split("</div>", 1)[0]
    # RED before: the first field group was Facility ID; Map was the tenth.
    assert first_label == "Map"
    assert first_group.startswith(' field-grid-2-span">')
    second_group = grid.split('<div class="field-group', 3)[2]
    assert second_group.startswith(' field-grid-2-span">')
    assert 'Positions from</div>' in second_group
    assert "None. No published coordinate for this facility" in html


@pytest.mark.skipif(not is_enabled("drinking"), reason="the drinking module is not installed")
def test_w3_a_located_facility_has_no_map_row():
    from tests.factories import SystemFacilityFactory

    facility = SystemFacilityFactory(
        facility_id="W151", name="W151 WELL", location=Point(-120.48, 37.30, srid=4326),
    )
    html = _client().get(
        reverse("drinking:facility_detail", args=[facility.pk])
    ).content.decode()
    assert "No published coordinate for this facility" not in html
    # The map card leads instead, and the record grid starts at Facility ID.
    grid = html.split('<div class="form-grid-2col mt-md">', 1)[1]
    first_group = grid.split('<div class="field-group', 2)[1]
    assert first_group.split('<div class="field-label">', 1)[1].startswith("Facility ID</div>")


# -- F6: the finish action in the station review's head row ----------------


def _review(inactive):
    return render_to_string(
        "setup/partials/_station_review.html",
        {
            "review_total": 6,
            "review_active": 6 - inactive,
            "review_inactive": inactive,
            "review_groups": [],
        },
    )


def test_f6_the_review_head_row_carries_the_finish_action_beside_enable_all():
    html = _review(inactive=6)
    link = f'<a href="{reverse("getting_started")}" class="btn-primary">Open Getting started →</a>'
    # RED before: the review partial carried no Getting started link at all.
    assert link in html
    head = html.split('<div class="row-end">', 1)[1].split("</div>", 1)[0]
    assert "Enable all 6" in head
    assert link in head
    assert head.index("Enable all 6") < head.index("Open Getting started")


def test_f6_the_finish_action_stays_after_enable_all_has_run():
    """The partial re-renders alone after Enable all (setup_activate_stations)."""
    html = _review(inactive=0)
    assert "Enable all" not in html
    assert reverse("getting_started") in html


# -- W5: the surface pane's lower row --------------------------------------


@pytest.mark.skipif(not is_enabled("recharge"), reason="the recharge module is not installed")
def test_w5_the_use_areas_and_recharge_row_ends_each_card_at_its_content():
    from recharge.models import RechargeSitePOD
    from tests.factories import PointOfDiversionFactory, RechargeSiteFactory

    pod = PointOfDiversionFactory(name="W150 Recharge Intake")
    RechargeSitePOD.objects.create(
        recharge_site=RechargeSiteFactory(name="W150 Basin"), point_of_diversion=pod,
    )
    resp = _client().get(reverse("surface:pod_detail", args=[pod.pk]))
    assert resp.status_code == 200
    html = resp.content.decode()
    row = html[: html.index(">Linked use areas</h2>")]
    row_open = row[row.rindex('<div class="page-grid-2col'):]
    # RED before: the row was `page-grid-2col page-grid-account-full`, stretched.
    assert row_open.startswith(
        '<div class="page-grid-2col page-grid-2col--align-start page-grid-account-full">'
    )


# -- S6: the well's Construction card --------------------------------------


def test_s6_construction_is_the_right_columns_last_card():
    from tests.factories import WellFactory

    well = WellFactory(name="W150 Well")
    resp = _client().get(reverse("wells:detail", args=[well.pk]))
    assert resp.status_code == 200
    html = resp.content.decode()
    construction = html.index("Construction (DWR Well Completion Report)")
    right_column = html.index('<div class="page-grid-account-balance">')
    history = html.index("Measurement history</h2>")
    # RED before: Construction was inside the Identification card, ahead of
    # the right column.
    assert right_column < construction < history
    assert html.index("Current meters") < construction
    assert html.index("Irrigated parcels") < construction
    assert '<h2 class="section-header">Construction (DWR Well Completion Report)</h2>' in html
    # Every editable field moved with its section, each on its own swap target.
    for name in (
        "depth_ft", "casing_diameter_in", "casing_material", "screen_top_ft",
        "screen_bottom_ft", "tested_yield_gpm", "pump_type", "notes",
    ):
        target = html.index(f'id="field-{name}"')
        assert construction < target < history, name
    # The Identification card closes on its created/updated line, with no
    # Construction section left in it.
    info = html[html.index('class="card-raised page-grid-account-info"'):right_column]
    assert "Construction" not in info
    assert "field-grid-2-span" in html[construction:history]


# -- S16b: the wizard's several-polygons line ------------------------------


@override_settings(ACCESS_CONTROL_ENFORCED=False)
def test_s16b_the_several_polygons_line_is_at_body_size():
    resp = _client(username="w150-admin", admin=True).get(reverse("setup:wizard"))
    assert resp.status_code == 200
    html = _squash(resp.content.decode())
    sentence = "When the file holds several polygons, OpenH2O combines them into one boundary."
    assert sentence in html
    opening = html[: html.index(sentence)].rsplit("<p", 1)[1]
    # RED before: the line was `class="form-help"`, the small tertiary help size.
    assert "form-help" not in opening
    assert 'class="text-base text-secondary' in opening
