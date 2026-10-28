# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Pins what ``infrastructure.views.infrastructure_add`` does today, branch by
branch, so the function can be broken into helpers without changing behaviour.

GET: the type-aware form and its fallback. POST: each infrastructure kind
(well, diversion, storage, recharge site) on success and on each way it fails
(no place on the map, a number that does not parse, an unavailable module).
"""
import json
from unittest import mock

import factory
import pytest
from django.contrib.auth.hashers import make_password
from django.test import Client
from django.urls import reverse

from recharge.models import RechargeSite
from surface.models import PointOfDiversion, PointOfDiversionParcel
from tests.factories import ParcelFactory, WaterRightFactory
from wells.models import Well, WellIrrigatedParcel

pytestmark = pytest.mark.django_db

POINT = json.dumps({"type": "Point", "coordinates": [-120.5, 37.3]})
POLYGON = json.dumps(
    {
        "type": "Polygon",
        "coordinates": [
            [[-120.0, 37.0], [-120.0, 37.2], [-119.8, 37.2], [-119.8, 37.0], [-120.0, 37.0]]
        ],
    }
)


class _UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"charadd{n}")
    email = factory.Sequence(lambda n: f"charadd{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True


@pytest.fixture
def client_in(db):
    c = Client()
    c.force_login(_UserFactory())
    return c


def _url():
    return reverse("infrastructure:add")


def _error_of(resp):
    assert resp.status_code == 200
    assert [t.name for t in resp.templates][0] == "infrastructure/add.html"
    return resp.context["error"]


# ---------------------------------------------------------------- GET


def test_login_is_required():
    resp = Client().get(_url())
    assert resp.status_code == 302
    assert "login" in resp["Location"]


def test_get_defaults_to_the_well_form(client_in):
    resp = client_in.get(_url())
    assert resp.status_code == 200
    ctx = resp.context
    assert ctx["preselect_type"] == "well"
    assert ctx["preselect_label"] == "Well"
    assert ctx["preselect_long_label"] == "groundwater well"
    assert ctx["back_url"] == reverse("wells:list")
    assert ctx["back_label"] == "Wells"
    assert [o["value"] for o in ctx["other_add_types"]] == [
        "diversion", "storage", "recharge_site"
    ]
    assert "error" not in ctx and "submitted" not in ctx


@pytest.mark.parametrize(
    "raw,expected,back",
    [
        ("diversion", "diversion", "surface:pod_list"),
        ("storage", "storage", "recharge:list"),
        ("recharge_site", "recharge_site", "recharge:list"),
        (" well ", "well", "wells:list"),
        ("bogus", "well", "wells:list"),
    ],
)
def test_get_preselects_the_type_and_falls_back(client_in, raw, expected, back):
    resp = client_in.get(_url(), {"type": raw})
    assert resp.status_code == 200
    assert resp.context["preselect_type"] == expected
    assert resp.context["back_url"] == reverse(back)


def test_get_lists_water_rights_in_right_id_order(client_in):
    WaterRightFactory(right_id="B2")
    WaterRightFactory(right_id="A1")
    resp = client_in.get(_url(), {"type": "diversion"})
    assert [r.right_id for r in resp.context["water_rights"]] == ["A1", "B2"]


def test_get_with_no_module_available_is_404(client_in):
    with mock.patch("infrastructure.views.is_enabled", return_value=False):
        assert client_in.get(_url()).status_code == 404


def test_post_with_no_module_available_is_404_and_writes_nothing(client_in):
    with mock.patch("infrastructure.views.is_enabled", return_value=False):
        resp = client_in.post(
            _url(), {"infra_type": "well", "name": "X", "geometry_json": POINT}
        )
    assert resp.status_code == 404
    assert Well.objects.count() == 0


# ---------------------------------------------------------------- POST well


def test_well_without_a_place_re_renders_with_the_submission(client_in):
    resp = client_in.post(_url(), {"infra_type": "well", "name": "W"})
    assert _error_of(resp) == "Place the well on the map."
    assert resp.context["preselect_type"] == "well"
    assert resp.context["submitted"]["name"] == "W"
    assert Well.objects.count() == 0


def test_well_success_writes_every_field_and_redirects_to_detail(client_in):
    resp = client_in.post(
        _url(),
        {
            "infra_type": "well",
            "name": "  Home Well ",
            "status": "inactive",
            "notes": " some notes ",
            "geometry_json": POINT,
            "depth_ft": "300.5",
            "capacity_gpm": "1200",
            "year_pumping_began": "1995",
            "casing_diameter_in": "12",
            "screen_top_ft": "100",
            "screen_bottom_ft": "250",
            "tested_yield_gpm": "900",
            "owner_name": "Pat",
            "wcr_number": "WCR-1",
            "state_well_number": "SWN-1",
            "casing_material": "steel",
            "pump_type": "",
        },
    )
    well = Well.objects.get()
    assert resp.status_code == 302
    assert resp["Location"] == reverse("wells:detail", kwargs={"pk": well.pk})
    assert well.name == "Home Well"
    assert well.status == "inactive"
    assert well.notes == "some notes"
    assert (well.location.x, well.location.y) == (-120.5, 37.3)
    assert float(well.depth_ft) == 300.5
    assert float(well.capacity_gpm) == 1200
    assert well.year_pumping_began == 1995
    assert float(well.casing_diameter_in) == 12
    assert float(well.screen_top_ft) == 100
    assert float(well.screen_bottom_ft) == 250
    assert float(well.tested_yield_gpm) == 900
    assert well.owner_name == "Pat"
    assert well.wcr_number == "WCR-1"
    assert well.state_well_number == "SWN-1"
    assert well.casing_material == "steel"
    assert WellIrrigatedParcel.objects.count() == 0


def test_well_status_defaults_to_active_and_blank_numbers_are_none(client_in):
    client_in.post(_url(), {"infra_type": "well", "name": "W", "geometry_json": POINT})
    well = Well.objects.get()
    assert well.status == "active"
    assert well.depth_ft is None
    assert well.year_pumping_began is None


def test_well_links_the_chosen_parcel(client_in):
    parcel = ParcelFactory()
    client_in.post(
        _url(),
        {"infra_type": "well", "name": "W", "geometry_json": POINT, "parcel_id": parcel.pk},
    )
    well = Well.objects.get()
    assert WellIrrigatedParcel.objects.get().parcel_id == parcel.pk
    assert WellIrrigatedParcel.objects.get().well_id == well.pk


def test_well_with_an_unknown_parcel_is_created_unlinked(client_in):
    resp = client_in.post(
        _url(),
        {"infra_type": "well", "name": "W", "geometry_json": POINT, "parcel_id": "999999"},
    )
    assert resp.status_code == 302
    assert Well.objects.count() == 1
    assert WellIrrigatedParcel.objects.count() == 0


def test_well_typed_coordinates_build_the_point(client_in):
    resp = client_in.post(
        _url(),
        {"infra_type": "well", "name": "W", "latitude": "37.25", "longitude": "-120.75"},
    )
    assert resp.status_code == 302
    well = Well.objects.get()
    assert (well.location.x, well.location.y) == (-120.75, 37.25)


def test_well_drawn_geometry_wins_over_typed_coordinates(client_in):
    client_in.post(
        _url(),
        {
            "infra_type": "well", "name": "W", "geometry_json": POINT,
            "latitude": "10", "longitude": "10",
        },
    )
    well = Well.objects.get()
    assert (well.location.x, well.location.y) == (-120.5, 37.3)


@pytest.mark.parametrize(
    "lat,lng",
    [("abc", "-120"), ("91", "-120"), ("37", "181"), ("37", ""), ("", "-120")],
)
def test_well_unusable_typed_coordinates_are_ignored_not_an_error(client_in, lat, lng):
    resp = client_in.post(
        _url(), {"infra_type": "well", "name": "W", "latitude": lat, "longitude": lng}
    )
    assert _error_of(resp) == "Place the well on the map."
    assert Well.objects.count() == 0


@pytest.mark.parametrize(
    "field,value",
    [
        ("depth_ft", "-1"),
        ("capacity_gpm", "abc"),
        ("year_pumping_began", "1700"),
        ("casing_diameter_in", "-3"),
        ("screen_top_ft", "x"),
        ("screen_bottom_ft", "-2"),
        ("tested_yield_gpm", "-9"),
    ],
)
def test_well_bad_number_re_renders_with_the_field_message(client_in, field, value):
    resp = client_in.post(
        _url(),
        {"infra_type": "well", "name": "W", "geometry_json": POINT, field: value},
    )
    message = _error_of(resp)
    assert message
    assert resp.context["submitted"][field] == value
    assert Well.objects.count() == 0


def test_well_error_messages_name_the_field(client_in):
    cases = {
        "depth_ft": "Depth (ft)",
        "year_pumping_began": "Year Pumping Began",
        "tested_yield_gpm": "Tested Yield (gpm)",
    }
    for field, label in cases.items():
        value = "1700" if field == "year_pumping_began" else "-1"
        resp = client_in.post(
            _url(),
            {"infra_type": "well", "name": "W", "geometry_json": POINT, field: value},
        )
        assert label in _error_of(resp)


def test_unknown_type_in_post_is_normalised_to_a_well(client_in):
    resp = client_in.post(
        _url(), {"infra_type": "nonsense", "name": "W", "geometry_json": POINT}
    )
    assert resp.status_code == 302
    assert Well.objects.count() == 1


# ---------------------------------------------------------------- POST diversion


def test_diversion_without_a_place_re_renders(client_in):
    resp = client_in.post(_url(), {"infra_type": "diversion", "name": "D"})
    assert _error_of(resp) == "Place the diversion on the map."
    assert resp.context["preselect_type"] == "diversion"
    assert PointOfDiversion.objects.count() == 0


def test_diversion_bad_max_rate_re_renders(client_in):
    resp = client_in.post(
        _url(),
        {"infra_type": "diversion", "name": "D", "geometry_json": POINT, "max_rate_cfs": "-4"},
    )
    assert "Max Rate (cfs)" in _error_of(resp)
    assert PointOfDiversion.objects.count() == 0


def test_diversion_success_writes_fields_and_redirects_to_the_list(client_in):
    right = WaterRightFactory(right_id="A777")
    parcel = ParcelFactory()
    resp = client_in.post(
        _url(),
        {
            "infra_type": "diversion",
            "name": " Intake ",
            "status": "inactive",
            "notes": " n ",
            "geometry_json": POINT,
            "max_rate_cfs": "2.5",
            "stream_name": "Big Creek",
            "local_name": "  Upper gate ",
            "water_right_id": f" {right.pk} ",
            "parcel_id": parcel.pk,
        },
    )
    assert resp.status_code == 302
    assert resp["Location"] == reverse("surface:pod_list")
    pod = PointOfDiversion.objects.get()
    assert pod.name == "Intake"
    assert pod.status == "inactive"
    assert pod.notes == "n"
    assert float(pod.max_rate_cfs) == 2.5
    assert pod.stream_name == "Big Creek"
    assert pod.local_name == "Upper gate"
    assert pod.water_right_id == right.pk
    assert (pod.location.x, pod.location.y) == (-120.5, 37.3)
    assert PointOfDiversionParcel.objects.get().parcel_id == parcel.pk


def test_diversion_stale_water_right_falls_back_to_unlinked(client_in):
    resp = client_in.post(
        _url(),
        {
            "infra_type": "diversion", "name": "D", "geometry_json": POINT,
            "water_right_id": "999999",
        },
    )
    assert resp.status_code == 302
    assert PointOfDiversion.objects.get().water_right_id is None
    assert PointOfDiversionParcel.objects.count() == 0


# ---------------------------------------------------------------- POST recharge / storage


def test_recharge_site_without_a_shape_asks_for_an_outline(client_in):
    resp = client_in.post(_url(), {"infra_type": "recharge_site", "name": "R"})
    assert _error_of(resp) == "Draw the outline on the map, or type a latitude and longitude."
    assert RechargeSite.objects.count() == 0


def test_storage_without_a_shape_asks_for_an_outline(client_in):
    resp = client_in.post(_url(), {"infra_type": "storage", "name": "S"})
    assert _error_of(resp) == "Draw the outline on the map, or type a latitude and longitude."


def test_storage_tank_without_a_shape_asks_for_a_tank_point(client_in):
    resp = client_in.post(
        _url(), {"infra_type": "storage", "name": "S", "storage_type": "storage_tank"}
    )
    assert _error_of(resp) == "Place the tank on the map, or type a latitude and longitude."


def test_recharge_site_tank_flag_does_not_change_its_message(client_in):
    resp = client_in.post(
        _url(),
        {"infra_type": "recharge_site", "name": "R", "storage_type": "storage_tank"},
    )
    assert _error_of(resp) == "Draw the outline on the map, or type a latitude and longitude."


def test_recharge_site_polygon_uses_the_centroid_as_location(client_in):
    resp = client_in.post(
        _url(),
        {
            "infra_type": "recharge_site",
            "name": " Basin ",
            "status": "inactive",
            "notes": " n ",
            "geometry_json": POLYGON,
            "capacity_acre_feet": "40",
            "operator": "District",
        },
    )
    site = RechargeSite.objects.get()
    assert resp.status_code == 302
    assert resp["Location"] == reverse("recharge:detail", kwargs={"pk": site.pk})
    assert site.name == "Basin"
    assert site.site_type == "spreading_basin"
    assert site.status == "inactive"
    assert site.notes == "n"
    assert site.operator == "District"
    assert float(site.capacity_acre_feet) == 40
    assert site.geometry is not None and site.geometry.geom_type == "MultiPolygon"
    assert (round(site.location.x, 6), round(site.location.y, 6)) == (-119.9, 37.1)


def test_recharge_site_point_has_no_polygon(client_in):
    client_in.post(
        _url(), {"infra_type": "recharge_site", "name": "R", "geometry_json": POINT}
    )
    site = RechargeSite.objects.get()
    assert site.geometry is None
    assert (site.location.x, site.location.y) == (-120.5, 37.3)


def test_storage_takes_its_site_type_from_storage_type(client_in):
    client_in.post(
        _url(),
        {
            "infra_type": "storage", "name": "T", "geometry_json": POINT,
            "storage_type": "storage_tank", "site_type": "ignored",
        },
    )
    assert RechargeSite.objects.get().site_type == "storage_tank"


def test_storage_site_type_defaults_to_pond(client_in):
    client_in.post(
        _url(), {"infra_type": "storage", "name": "P", "geometry_json": POLYGON}
    )
    assert RechargeSite.objects.get().site_type == "storage_pond"


def test_recharge_site_uses_the_posted_site_type(client_in):
    client_in.post(
        _url(),
        {"infra_type": "recharge_site", "name": "R", "geometry_json": POINT,
         "site_type": "injection_well"},
    )
    assert RechargeSite.objects.get().site_type == "injection_well"


def test_recharge_bad_capacity_re_renders(client_in):
    resp = client_in.post(
        _url(),
        {"infra_type": "storage", "name": "S", "geometry_json": POINT,
         "capacity_acre_feet": "-5"},
    )
    assert "Capacity (acre-feet)" in _error_of(resp)
    assert resp.context["preselect_type"] == "storage"
    assert RechargeSite.objects.count() == 0
