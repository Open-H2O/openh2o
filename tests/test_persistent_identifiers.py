# SPDX-License-Identifier: AGPL-3.0-or-later
"""
146-06 Task 1 (ISS-019): every feature record has an address that resolves.

``/id/<kind>/<pk>/`` is the record's persistent identifier. It is DERIVED,
never stored: ``https://<identifier_host>/id/<kind>/<pk>/`` when
``SiteConfig.identifier_host`` is set, else the site's own address. A browser
asking for it is sent (303) to the record's own page; a machine asking for
``application/ld+json`` (or ``?format=jsonld``) gets a schema.org JSON-LD
document whose ``@id`` is the identifier. The shape follows the Geoconnex
contributor documentation read on 2026-09-23 (quoted in
``146-06-EVIDENCE-T1.md``): ``schema:Place`` with a WKT geometry under
``gsp:hasGeometry``, every term prefixed, bare ``@id`` references for the
places a record sits inside.

What is load-bearing here, and why each is its own test:

* **The crawler names both types.** Geoconnex's harvester (Nabu) sends
  ``Accept: application/ld+json;q=1.0, text/html;q=0.8``. A check of "does the
  header mention text/html" would bounce it to a signed-in page. The
  negotiation has to read the quality values.
* **A disabled module's kind is 404 with a sentence that says so**, not a
  crash through a model whose app may not even be installed.
* **Nothing the record does not hold is invented.** Blank crosswalk fields
  are left out of the identifier list, not emitted empty.
"""

import json

import factory
import pytest
from django.contrib.auth.hashers import make_password
from django.contrib.gis.geos import MultiPolygon, Point, Polygon
from django.test import Client
from django.urls import reverse

from core import modules as mod
from core.models import SiteConfig
from tests.factories import (
    BoundaryFactory,
    MonitoredStationFactory,
    ParcelFactory,
    ParcelZoneFactory,
    PointOfDiversionFactory,
    RechargeSiteFactory,
    SamplingPointFactory,
    SystemFacilityFactory,
    WaterRightFactory,
    WaterSystemFactory,
    WellFactory,
    ZoneFactory,
)
from tests.test_module_prose import compose_urlconf_under_the_full_module_set

pytestmark = pytest.mark.django_db

JSONLD = "application/ld+json"
BROWSER_ACCEPT = (
    "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
)
#: Verbatim from internetofwater/nabu internal/crawl/site.go (read 2026-09-23).
CRAWLER_ACCEPT = "application/ld+json;q=1.0, text/html;q=0.8"


class _UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"pidadmin{n}")
    email = factory.Sequence(lambda n: f"pidadmin{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True
    is_staff = True


@pytest.fixture
def admin_client(db):
    c = Client()
    c.force_login(_UserFactory())
    return c


# ---------------------------------------------------------------------------
# One record of every kind. The boundary's polygon contains every point record
# (all factories default to -119.5, 36.5), which is what containedInPlace reads.
# ---------------------------------------------------------------------------


def _make(kind):
    if kind == "boundary":
        return BoundaryFactory(basin_code="5-022.04", huc="18040001")
    if kind == "zone":
        return ZoneFactory(basin_code="5-022.11")
    if kind == "use-area":
        return ParcelFactory()
    if kind == "well":
        return WellFactory(state_well_number="07S13E26J001M", wcr_number="WCR0123")
    if kind == "point-of-diversion":
        return PointOfDiversionFactory(name="A001885_01")
    if kind == "recharge-site":
        return RechargeSiteFactory()
    if kind == "station":
        return MonitoredStationFactory(usgs_site_id="11273400")
    if kind == "water-system":
        return WaterSystemFactory(pwsid="CA2410001")
    if kind == "facility":
        return SystemFacilityFactory(location=Point(-119.5, 36.5))
    if kind == "sampling-point":
        return SamplingPointFactory(facility=SystemFacilityFactory(location=Point(-119.5, 36.5)))
    if kind == "water-right":
        return WaterRightFactory(right_id="A001885", holder_name="Example Ditch Company")
    raise AssertionError(kind)


ALL_KINDS = [
    "boundary",
    "zone",
    "use-area",
    "well",
    "point-of-diversion",
    "recharge-site",
    "station",
    "water-system",
    "facility",
    "sampling-point",
    "water-right",
]
#: Kinds whose model carries a geometry the fixtures above fill.
SPATIAL_KINDS = [k for k in ALL_KINDS if k not in ("water-system", "water-right")]


def _jsonld(client, kind, pk, **extra):
    resp = client.get(f"/id/{kind}/{pk}/", HTTP_ACCEPT=JSONLD, **extra)
    assert resp.status_code == 200, resp.content[:300]
    return resp, json.loads(resp.content)


def test_the_registry_names_the_eleven_kinds():
    from core.identifiers import KINDS

    assert sorted(KINDS) == sorted(ALL_KINDS)


@pytest.mark.parametrize("kind", ALL_KINDS)
def test_a_browser_is_sent_to_the_records_own_page(kind):
    obj = _make(kind)
    resp = Client().get(f"/id/{kind}/{obj.pk}/", HTTP_ACCEPT=BROWSER_ACCEPT)
    assert resp.status_code == 303
    assert resp["Location"] == obj.get_absolute_url()
    assert "Accept" in resp["Vary"]


@pytest.mark.parametrize("kind", ALL_KINDS)
def test_a_machine_gets_jsonld_whose_id_is_the_identifier(kind):
    obj = _make(kind)
    # Anonymous on purpose: a harvester cannot sign in.
    resp, doc = _jsonld(Client(), kind, obj.pk)
    assert resp["Content-Type"].startswith(JSONLD)
    assert "Accept" in resp["Vary"]
    assert doc["@id"] == f"http://testserver/id/{kind}/{obj.pk}/"
    assert doc["schema:additionalType"] == kind
    assert doc["schema:name"]
    assert doc["@context"]["schema"] == "https://schema.org/"


@pytest.mark.parametrize("kind", SPATIAL_KINDS)
def test_a_spatial_kind_is_a_place_with_a_wkt_geometry(kind):
    obj = _make(kind)
    _, doc = _jsonld(Client(), kind, obj.pk)
    assert doc["@type"] == "schema:Place"
    wkt = doc["gsp:hasGeometry"]["gsp:asWKT"]["@value"]
    assert wkt.startswith(("POINT", "MULTIPOLYGON", "POLYGON"))
    assert "schema:geo" in doc


def test_the_crawlers_own_accept_header_gets_jsonld():
    well = WellFactory()
    resp = Client().get(f"/id/well/{well.pk}/", HTTP_ACCEPT=CRAWLER_ACCEPT)
    assert resp.status_code == 200
    assert resp["Content-Type"].startswith(JSONLD)


def test_format_jsonld_in_the_query_string_gets_jsonld():
    well = WellFactory()
    resp = Client().get(f"/id/well/{well.pk}/?format=jsonld", HTTP_ACCEPT=BROWSER_ACCEPT)
    assert resp.status_code == 200
    assert resp["Content-Type"].startswith(JSONLD)


def test_a_bare_accept_everything_is_sent_to_the_page():
    well = WellFactory()
    resp = Client().get(f"/id/well/{well.pk}/", HTTP_ACCEPT="*/*")
    assert resp.status_code == 303


def test_a_well_inside_a_boundary_says_so():
    boundary = BoundaryFactory()
    well = WellFactory(location=Point(-119.5, 36.5))
    elsewhere = BoundaryFactory(geometry=MultiPolygon(Polygon.from_bbox((-100, 30, -99, 31))))
    _, doc = _jsonld(Client(), "well", well.pk)
    contained = [ref["@id"] for ref in doc["schema:containedInPlace"]]
    assert f"http://testserver/id/boundary/{boundary.pk}/" in contained
    assert f"http://testserver/id/boundary/{elsewhere.pk}/" not in contained
    # A bare reference, never a typed node: a nested schema:Place would itself
    # be held to the Geoconnex shape and need a geometry.
    assert all(set(ref) == {"@id"} for ref in doc["schema:containedInPlace"])


def test_a_use_area_names_the_zone_it_is_linked_to():
    link = ParcelZoneFactory()
    _, doc = _jsonld(Client(), "use-area", link.parcel.pk)
    contained = [ref["@id"] for ref in doc["schema:containedInPlace"]]
    assert f"http://testserver/id/zone/{link.zone.pk}/" in contained


def test_the_point_of_diversion_carries_its_name_as_an_identifier():
    pod = PointOfDiversionFactory(name="A001885_01")
    _, doc = _jsonld(Client(), "point-of-diversion", pod.pk)
    values = {(i["schema:propertyID"], i["schema:value"]) for i in doc["schema:identifier"]}
    assert ("name", "A001885_01") in values


def test_the_well_carries_only_the_crosswalk_ids_it_holds():
    well = WellFactory(state_well_number="07S13E26J001M", wcr_number="", usgs_site_id="")
    _, doc = _jsonld(Client(), "well", well.pk)
    ids = {i["schema:propertyID"]: i["schema:value"] for i in doc["schema:identifier"]}
    assert ids["state_well_number"] == "07S13E26J001M"
    assert "wcr_number" not in ids
    assert "usgs_site_id" not in ids
    assert all(i["@type"] == "schema:PropertyValue" for i in doc["schema:identifier"])


def test_the_water_system_carries_its_pwsid():
    system = WaterSystemFactory(pwsid="CA2410001")
    _, doc = _jsonld(Client(), "water-system", system.pk)
    ids = {i["schema:propertyID"]: i["schema:value"] for i in doc["schema:identifier"]}
    assert ids["pwsid"] == "CA2410001"


def test_the_sampling_point_carries_its_ps_code_and_sits_in_its_facility():
    point = SamplingPointFactory(ps_code="CA2410001_010_001")
    _, doc = _jsonld(Client(), "sampling-point", point.pk)
    ids = {i["schema:propertyID"]: i["schema:value"] for i in doc["schema:identifier"]}
    assert ids["ps_code"] == "CA2410001_010_001"
    contained = [ref["@id"] for ref in doc["schema:containedInPlace"]]
    assert f"http://testserver/id/facility/{point.facility.pk}/" in contained


def test_the_water_right_is_a_thing_with_its_holder():
    right = WaterRightFactory(right_id="A001885", holder_name="Example Ditch Company")
    _, doc = _jsonld(Client(), "water-right", right.pk)
    assert doc["@type"] == "schema:Thing"
    assert doc["schema:owner"] == {"schema:name": "Example Ditch Company"}
    ids = {i["schema:propertyID"]: i["schema:value"] for i in doc["schema:identifier"]}
    assert ids["right_id"] == "A001885"
    assert "gsp:hasGeometry" not in doc


def test_identifier_host_changes_the_id():
    SiteConfig.objects.create(agency_name="Agency", identifier_host="water.example.org")
    well = WellFactory()
    _, doc = _jsonld(Client(), "well", well.pk)
    assert doc["@id"] == f"https://water.example.org/id/well/{well.pk}/"


def test_identifier_host_may_carry_a_geoconnex_namespace():
    SiteConfig.objects.create(agency_name="Agency", identifier_host="geoconnex.us/example-district")
    well = WellFactory()
    _, doc = _jsonld(Client(), "well", well.pk)
    assert doc["@id"] == f"https://geoconnex.us/example-district/id/well/{well.pk}/"


def test_an_unknown_kind_is_404():
    resp = Client().get("/id/spaceship/1/", HTTP_ACCEPT=JSONLD)
    assert resp.status_code == 404


def test_a_missing_record_is_404():
    resp = Client().get("/id/well/999999/", HTTP_ACCEPT=JSONLD)
    assert resp.status_code == 404


def test_a_disabled_modules_kind_is_404_with_the_sentence(settings):
    well = WellFactory()
    compose_urlconf_under_the_full_module_set()
    settings.OPENH2O_MODULES = [n for n in mod.ALL_MODULE_NAMES if n != "wells"]
    for accept in (JSONLD, BROWSER_ACCEPT):
        resp = Client().get(f"/id/well/{well.pk}/", HTTP_ACCEPT=accept)
        assert resp.status_code == 404
        assert "This deployment does not run the wells module." in resp.content.decode()


def test_a_removable_modules_kind_is_404_before_any_model_lookup(settings):
    # `surface` is truly removable: on a real deployment without it the app is
    # not installed, so resolve() must answer from the module check alone.
    pod = PointOfDiversionFactory()
    compose_urlconf_under_the_full_module_set()
    settings.OPENH2O_MODULES = [
        n for n in mod.ALL_MODULE_NAMES if n not in ("surface", "recharge")
    ]
    resp = Client().get(f"/id/point-of-diversion/{pod.pk}/", HTTP_ACCEPT=JSONLD)
    assert resp.status_code == 404
    assert "This deployment does not run the surface module." in resp.content.decode()


def test_head_is_answered_like_get():
    well = WellFactory()
    resp = Client().head(f"/id/well/{well.pk}/", HTTP_ACCEPT=JSONLD)
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# get_absolute_url on the eleven models, and the identity-card line on the ten
# record pages (a boundary has no page of its own; its HTML is the map).
# ---------------------------------------------------------------------------

EXPECTED_PAGE = {
    "boundary": lambda o: reverse("geography:map"),
    "zone": lambda o: reverse("geography:zone_detail", args=[o.pk]),
    "use-area": lambda o: reverse("parcels:detail", args=[o.pk]),
    "well": lambda o: reverse("wells:detail", args=[o.pk]),
    "point-of-diversion": lambda o: reverse("surface:pod_detail", args=[o.pk]),
    "recharge-site": lambda o: reverse("recharge:detail", args=[o.pk]),
    "station": lambda o: reverse("datasync:station_detail", args=[o.pk]),
    "water-system": lambda o: reverse("drinking:overview"),
    "facility": lambda o: reverse("drinking:facility_detail", args=[o.pk]),
    "sampling-point": lambda o: reverse("drinking:sampling_point_detail", args=[o.pk]),
    "water-right": lambda o: reverse("surface:detail", args=[o.pk]),
}


@pytest.mark.parametrize("kind", ALL_KINDS)
def test_get_absolute_url_is_the_records_page(kind):
    obj = _make(kind)
    assert obj.get_absolute_url() == EXPECTED_PAGE[kind](obj)


@pytest.mark.parametrize("kind", [k for k in ALL_KINDS if k != "boundary"])
def test_the_record_page_shows_its_identifier_with_a_copy_control(admin_client, kind):
    obj = _make(kind)
    resp = admin_client.get(obj.get_absolute_url())
    assert resp.status_code == 200
    body = resp.content.decode()
    uri = f"http://testserver/id/{kind}/{obj.pk}/"
    assert "Identifier" in body
    assert uri in body
    assert f'data-copy-text="{uri}"' in body


# ---------------------------------------------------------------------------
# The setting
# ---------------------------------------------------------------------------


def test_the_settings_page_offers_identifier_host(admin_client):
    resp = admin_client.get(reverse("accounting:delivery_settings"))
    assert resp.status_code == 200
    assert 'name="identifier_host"' in resp.content.decode()


def test_identifier_host_saves_without_its_scheme(admin_client):
    config, _ = SiteConfig.objects.get_or_create(defaults={"agency_name": "Agency"})
    resp = admin_client.post(
        reverse("accounting:delivery_settings"),
        {
            "efficiency_percent": "75",
            # 148-02 Task 4: `wells` is enabled by default in these tests, so
            # groundwater_efficiency_percent is required on this POST too.
            "groundwater_efficiency_percent": "80",
            "recovery_horizon": "carry_forward",
            "diversion_report_year_rule": "water_year",
            "season_start_month": "",
            "identifier_host": "https://water.example.org/",
        },
    )
    assert resp.status_code == 302
    config.refresh_from_db()
    assert config.identifier_host == "water.example.org"
