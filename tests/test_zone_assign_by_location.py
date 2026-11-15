# SPDX-License-Identifier: AGPL-3.0-or-later
"""Assign use areas to zones: each use area to the zone of the chosen type that holds most of it.

One step for the zones of one type. A use area across two zones joins the one holding
the larger share and is listed; one outside every zone joins none and is listed; one
already in a zone of that type keeps it. Memberships start and end blank ("always has
been", "still is"). ``assign_zones`` runs the same function. The words asserted are
the approved rows.
"""
import re
from datetime import date
from html import unescape

import pytest
from django.contrib.gis.geos import MultiPolygon, Polygon
from django.core.management import call_command
from django.test import Client
from django.urls import reverse_lazy

from accounting.models import ReportingPeriod
from core.models import User
from geography.models import ParcelZone
from tests.factories import BoundaryFactory, ParcelFactory, ParcelZoneFactory, ZoneFactory

pytestmark = pytest.mark.django_db

ASSIGN = reverse_lazy("geography:zones_assign")


def _rect(x0, y0, x1, y1):
    return MultiPolygon(Polygon(((x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0))))


@pytest.fixture
def site():
    boundary = BoundaryFactory(geometry=_rect(-120.0, 36.0, -119.0, 37.0))
    west = ZoneFactory(name="West GSA", zone_type="management_area", boundary=boundary,
                       geometry=_rect(-119.60, 36.40, -119.50, 36.50))
    east = ZoneFactory(name="East GSA", zone_type="management_area", boundary=boundary,
                       geometry=_rect(-119.50, 36.40, -119.40, 36.50))
    basin = ZoneFactory(name="The Subbasin", zone_type="subbasin", boundary=boundary,
                        geometry=_rect(-119.70, 36.30, -119.30, 36.60))
    parcels = {
        # Wholly inside West.
        "inside": ParcelFactory(parcel_number="001-001-001-000", geometry=_rect(-119.58, 36.42, -119.56, 36.44)),
        # 30% in West, 70% in East.
        "across": ParcelFactory(parcel_number="001-001-002-000", geometry=_rect(-119.503, 36.42, -119.493, 36.44)),
        # Outside both management areas (inside the subbasin).
        "outside": ParcelFactory(parcel_number="001-001-003-000", geometry=_rect(-119.68, 36.32, -119.66, 36.34)),
        # Inside West but already in East.
        "already": ParcelFactory(parcel_number="001-001-004-000", geometry=_rect(-119.58, 36.46, -119.56, 36.48)),
        # Inside West, its edge on East's: touching is not across.
        "touching": ParcelFactory(parcel_number="001-001-005-000", geometry=_rect(-119.52, 36.46, -119.50, 36.48)),
    }
    ParcelZoneFactory(parcel=parcels["already"], zone=east)
    return {"west": west, "east": east, "basin": basin, "parcels": parcels}


def _text(response):
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", response.content.decode()))).strip()


def _client():
    user = User.objects.create_user(
        username="admin", email="admin@example.org", password="x", is_active=True,
        is_staff=True, is_superuser=True,
    )
    client = Client()
    client.force_login(user)
    return client


def _zones_of(parcel, zone_type="management_area"):
    return sorted(
        ParcelZone.objects.filter(parcel=parcel, zone__zone_type=zone_type, end_date__isnull=True)
        .values_list("zone__name", flat=True)
    )


def _assigned(site):
    p = site["parcels"]
    return {key: _zones_of(parcel) for key, parcel in p.items()}


EXPECTED = {
    "inside": ["West GSA"],
    "across": ["East GSA"],
    "outside": [],
    "already": ["East GSA"],
    "touching": ["West GSA"],
}


def test_the_preview_counts_and_lists_and_writes_nothing(site):
    before = ParcelZone.objects.count()
    page = _text(_client().get(ASSIGN, {"zone_type": "management_area"}))
    assert ParcelZone.objects.count() == before
    for words in [
        "This page assigns each use area to the zone of the chosen type that holds most of its area.",
        "What Assign would do",
        "2 use areas Assigned to West GSA",
        "1 use area Assigned to East GSA",
        "1 use area outside every zone 001-001-003-000 Not assigned",
        "1 use area already in a zone of this type Unchanged",
        "1 of the 3 use areas to assign lies across two or more zones. 001-001-002-000",
        "Each assignment holds for every water year, past years included.",
        "Assign 3 use areas",
        "Back to Zones",
    ]:
        assert words in page, words


def test_assign_puts_each_use_area_in_the_zone_holding_most_of_it(site):
    page = _text(_client().post(ASSIGN, {"zone_type": "management_area"}))
    assert "Assignment complete" in page
    assert "OpenH2O assigned 3 use areas to their zones." in page
    assert "1 use area lies outside every zone. To assign one by hand, open a zone's page and use Assign use area." in page
    assert "View Zones" in page
    assert _assigned(site) == EXPECTED


def test_the_rows_written_carry_blank_dates(site):
    before = set(ParcelZone.objects.values_list("pk", flat=True))
    _client().post(ASSIGN, {"zone_type": "management_area"})
    new = ParcelZone.objects.exclude(pk__in=before)
    assert new.count() == 3
    assert set(new.values_list("start_date", "end_date")) == {(None, None)}


def test_a_zone_of_another_type_is_untouched(site):
    _client().post(ASSIGN, {"zone_type": "management_area"})
    assert not ParcelZone.objects.filter(zone=site["basin"]).exists()


def test_the_other_type_assigns_on_its_own(site):
    _client().post(ASSIGN, {"zone_type": "subbasin"})
    assert ParcelZone.objects.filter(zone=site["basin"]).count() == 5
    assert _zones_of(site["parcels"]["inside"]) == []


def test_the_command_gives_the_screen_result(site, capsys):
    call_command("assign_zones", zone_type="management_area")
    out = capsys.readouterr().out
    assert "OpenH2O assigned 3 use areas to their zones." in out
    assert _assigned(site) == EXPECTED


def test_a_dry_run_assigns_nothing(site, capsys):
    before = ParcelZone.objects.count()
    call_command("assign_zones", zone_type="management_area", dry_run=True)
    assert capsys.readouterr().out.strip().splitlines()[-1] == "Dry run: OpenH2O did not save anything."
    assert ParcelZone.objects.count() == before


def test_a_second_run_has_nothing_to_assign(site):
    client = _client()
    client.post(ASSIGN, {"zone_type": "management_area"})
    page = _text(client.get(ASSIGN, {"zone_type": "management_area"}))
    assert "Every use area is already in a zone of this type or outside every zone." in page
    assert _assigned(site) == EXPECTED


def test_a_finalized_year_is_named(site):
    ReportingPeriod.objects.create(
        name="WY 2024-2025", start_date=date(2024, 10, 1), end_date=date(2025, 9, 30), is_finalized=True
    )
    page = _text(_client().get(ASSIGN, {"zone_type": "management_area"}))
    assert (
        "WY 2024-2025 is finalized. Its pages keep its figures as filed and show beside them any "
        "figure these assignments change."
    ) in page


def test_no_zones_and_no_use_areas_say_what_to_do_first():
    client = _client()
    page = _text(client.get(ASSIGN))
    assert "No zones are on file yet. Import zones or add a zone first." in page
    ZoneFactory(zone_type="")
    page = _text(client.get(ASSIGN))
    assert "No zone has a type yet. Choose each zone's type on its page, then come back." in page
    ZoneFactory(zone_type="management_area")
    page = _text(client.get(ASSIGN))
    assert "No use areas are on file yet. Import use areas first." in page
