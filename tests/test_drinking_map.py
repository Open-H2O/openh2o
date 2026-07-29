# SPDX-License-Identifier: AGPL-3.0-or-later
"""The drinking-water overview map: its data source and the page it sits on.

Phase 99 gave the drinking module its own geometry and put the platform's
standard Bucket-3 overview map on the sampling-point inventory. These tests pin
the properties that would otherwise rot quietly, because every one of them fails
in a way you cannot see by looking at a working map:

* **Coverage is computed, never written down.** The Merced demonstration happens
  to be 21 of 61 facilities. A test asserting the string "21 of 61" would pass
  forever and mean nothing — an onboarded system has different numbers, and
  EVERY system onboarded through the Envirofacts flow starts at zero, because
  EPA publishes no coordinates at all.
* **The map survives `wells` being off.** That is the drinking-water utility
  flavor, and it is the entire reason `SystemFacility.location` exists rather
  than the map reading `facility.well.location`.
* **No verdict reaches the map.** A popup is a view; Phase 98's rule — nothing
  renders a limit or a judgment about the water — has to reach this surface too.
* **Unlocated facilities are omitted, not zeroed.** A facility at (0, 0) is a lie
  that looks like data.
"""
import json

import factory
import pytest
from django.contrib.auth.hashers import make_password
from django.test import Client
from django.urls import reverse

from core import modules as mod
from drinking.models import SystemFacility
from tests.factories import (
    SamplingPointFactory,
    SystemFacilityFactory,
    WaterSystemFactory,
)

# Same mechanism as tests/test_drinking_detail_views.py, and for the same reason:
# config/urls.py composes its module routes at IMPORT time, so a test that
# narrows OPENH2O_MODULES before the process's first request would permanently
# compose a reduced URLconf for every later test.
from tests.test_module_prose import compose_urlconf_under_the_full_module_set

WITHOUT_WELLS = [name for name in mod.ALL_MODULE_NAMES if name != "wells"]

#: Somewhere in Merced, so a coordinate that survives into the page is
#: recognisable as a real place rather than the (0, 0) default.
MERCED = (-120.4829, 37.3022)


class UserFactory(factory.django.DjangoModelFactory):
    """Local, matching the house convention — every suite file defines its own."""

    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"drinkmap{n}")
    email = factory.Sequence(lambda n: f"drinkmap{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True


@pytest.fixture
def client_in(db):
    client = Client()
    client.force_login(UserFactory())
    return client


def _point(offset=0.0):
    from django.contrib.gis.geos import Point

    return Point(MERCED[0] + offset, MERCED[1] + offset, srid=4326)


@pytest.fixture
def mapped_system(db):
    """One system, three facilities, two of them located.

    Deliberately NOT all three: the unlocated one is what every omission and
    every coverage count below is measured against, and a fixture where
    everything has a coordinate would let a broken filter pass.
    """
    system = WaterSystemFactory(pwsid="CA2410009", name="Cedar Grove Water District")
    well_a = SystemFacilityFactory(
        system=system, facility_id="010", name="Well 08",
        facility_type="WL", location=_point(),
    )
    well_b = SystemFacilityFactory(
        system=system, facility_id="020", name="Well 12",
        facility_type="WL", location=_point(0.01),
    )
    unlocated = SystemFacilityFactory(
        system=system, facility_id="DST", name="DISTRIBUTION SYSTEM",
        facility_type="DS", location=None,
    )
    points = [
        SamplingPointFactory(ps_code="CA2410009_010_001", facility=well_a),
        SamplingPointFactory(ps_code="CA2410009_010_002", facility=well_a),
        SamplingPointFactory(ps_code="CA2410009_020_001", facility=well_b),
        SamplingPointFactory(ps_code="CA2410009_DST_LCR", facility=unlocated),
    ]
    return {
        "system": system, "well_a": well_a, "well_b": well_b,
        "unlocated": unlocated, "points": points,
    }


def _squash(html):
    """Collapse whitespace so a template's line wrapping cannot break a match."""
    return " ".join(html.split())


def _geojson(client):
    response = client.get(reverse("drinking:facilities_geojson"))
    assert response.status_code == 200
    return response, json.loads(response.content.decode())


# -- 1. The endpoint ---------------------------------------------------------


class TestFacilitiesGeoJSON:
    def test_anonymous_is_redirected_to_login(self, client, mapped_system):
        response = client.get(reverse("drinking:facilities_geojson"))
        assert response.status_code == 302

    def test_returns_json(self, client_in, mapped_system):
        response, data = _geojson(client_in)
        assert response["Content-Type"] == "application/json"
        assert data["type"] == "FeatureCollection"

    def test_located_facilities_carry_identity_and_their_ps_codes(
        self, client_in, mapped_system
    ):
        _, data = _geojson(client_in)
        by_pk = {f["properties"]["pk"]: f for f in data["features"]}

        feature = by_pk[mapped_system["well_a"].pk]
        props = feature["properties"]
        assert props["facility_id"] == "010"
        assert props["name"] == "Well 08"
        assert props["system_name"] == "Cedar Grove Water District"
        assert props["pwsid"] == "CA2410009"
        assert props["point_count"] == 2
        assert props["ps_codes"] == ["CA2410009_010_001", "CA2410009_010_002"]
        assert feature["geometry"]["type"] == "Point"

    def test_facility_type_is_the_label_not_the_code(self, client_in, mapped_system):
        """ISS-008 was filed for exactly this on the monitoring charts."""
        _, data = _geojson(client_in)
        types = {f["properties"]["facility_type"] for f in data["features"]}
        assert types == {"Well"}, f"a raw two-letter code reached the map: {types}"

    def test_a_facility_without_a_location_is_absent_entirely(
        self, client_in, mapped_system
    ):
        _, data = _geojson(client_in)
        pks = {f["properties"]["pk"] for f in data["features"]}
        assert mapped_system["unlocated"].pk not in pks
        assert len(data["features"]) == 2

    def test_no_feature_sits_at_zero_zero(self, client_in, mapped_system):
        """Omitted, not zeroed. A facility in the Gulf of Guinea is a lie."""
        _, data = _geojson(client_in)
        for feature in data["features"]:
            assert feature["geometry"]["coordinates"] != [0, 0]
            assert feature["geometry"]["coordinates"] != [0.0, 0.0]

    def test_query_count_does_not_grow_with_the_inventory(
        self, client_in, django_assert_num_queries
    ):
        """The `select_related`, the `annotate` and the `Prefetch` keep this flat.

        Asserted as a SHAPE rather than a magic number: the same query count with
        four facilities and with sixteen. A per-row walk of `system` or of
        `sampling_points` would pass any single-count assertion you happened to
        write for the smaller fixture and fail this one.
        """
        def build(pwsid, count):
            system = WaterSystemFactory(pwsid=pwsid, name=f"Query Count {pwsid}")
            for index in range(count):
                facility = SystemFacilityFactory(
                    system=system, facility_id=f"{index:03d}",
                    facility_type="WL", location=_point(index * 0.01),
                )
                for point in range(2):
                    SamplingPointFactory(
                        ps_code=f"{pwsid}_{index:03d}_{point:03d}", facility=facility
                    )

        build("CA9999998", 4)
        with django_assert_num_queries(3):
            small = client_in.get(reverse("drinking:facilities_geojson"))
        assert len(json.loads(small.content.decode())["features"]) == 4

        build("CA9999999", 12)
        with django_assert_num_queries(3):
            large = client_in.get(reverse("drinking:facilities_geojson"))
        assert len(json.loads(large.content.decode())["features"]) == 16


# -- 2. Prepare, never determine, reaches the map ----------------------------


class TestTheMapRendersNoVerdict:
    #: Phase 98's rule, as the words it would leak through.
    FORBIDDEN = ("limit", "mcl", "exceed", "violation", "status", "compliance")

    def test_no_property_names_a_judgment(self, client_in, mapped_system):
        _, data = _geojson(client_in)
        for feature in data["features"]:
            for key in feature["properties"]:
                lowered = key.lower()
                for banned in self.FORBIDDEN:
                    assert banned not in lowered, (
                        f"the map carries a property named {key!r} — a popup is a "
                        "view, and it renders no verdict about the water"
                    )

    def test_no_result_value_reaches_the_map(self, client_in, mapped_system):
        """Belt to the key-name braces: no analyte data of any kind."""
        response, _ = _geojson(client_in)
        body = response.content.decode().lower()
        for banned in ("result", "analyte", "detection", "regulatory"):
            assert banned not in body
# -- 3. The page and its computed coverage -----------------------------------


class TestTheCoverageSentenceIsComputed:
    def test_it_counts_what_is_actually_located(self, client_in, mapped_system):
        """Add a location; the page must say a different number.

        A test asserting the demonstration's own "21 of 61" would pass forever
        and prove nothing.
        """
        html = _squash(
            client_in.get(reverse("drinking:sampling_points")).content.decode()
        )
        assert "2 of the 3" in html, (
            "the page does not state the facility coverage it actually has"
        )

        mapped_system["unlocated"].location = _point(0.02)
        mapped_system["unlocated"].save(update_fields=["location"])

        html = _squash(
            client_in.get(reverse("drinking:sampling_points")).content.decode()
        )
        assert "3 of the 3" in html, "the coverage sentence is a hardcoded literal"

    def test_it_counts_the_points_the_map_can_show(self, client_in, mapped_system):
        """Three of the four sampling points hang off a located facility."""
        html = _squash(
            client_in.get(reverse("drinking:sampling_points")).content.decode()
        )
        assert "3 of the 4" in html

    def test_it_says_why_the_rest_are_missing(self, client_in, mapped_system):
        """The gap is a fact about the public record, not a defect here."""
        html = _squash(
            client_in.get(reverse("drinking:sampling_points")).content.decode()
        )
        assert "source wells" in html.lower()

    def test_no_hardcoded_demonstration_numbers(self, client_in, mapped_system):
        """The Merced counts must not be written into the template."""
        html = _squash(
            client_in.get(reverse("drinking:sampling_points")).content.decode()
        )
        for literal in ("21 of 61", "21 of 27", "21 of the 61"):
            assert literal not in html


class TestTheEmptyStateIsASentence:
    """An onboarded system has NO coordinates — Envirofacts publishes none.

    So zero-mapped is the common case for a new operator, not an edge case, and a
    380px empty grey rectangle is worse than an honest sentence.
    """

    @pytest.fixture
    def unmapped_system(self, db):
        system = WaterSystemFactory(pwsid="CA0000001", name="Newly Onboarded Water")
        facility = SystemFacilityFactory(
            system=system, facility_id="010", facility_type="WL", location=None
        )
        SamplingPointFactory(ps_code="CA0000001_010_001", facility=facility)
        return system

    def test_no_map_host_is_rendered(self, client_in, unmapped_system):
        html = _squash(
            client_in.get(reverse("drinking:sampling_points")).content.decode()
        )
        assert 'id="drinking-overview-map"' not in html, (
            "an empty grey rectangle was rendered instead of an explanation"
        )

    def test_it_says_so_and_says_where_locations_come_from(
        self, client_in, unmapped_system
    ):
        html = _squash(
            client_in.get(reverse("drinking:sampling_points")).content.decode()
        ).lower()
        assert "no facility in this system has a published location" in html
        assert "source wells" in html
        # And it names the reason a new operator sees this at all.
        assert "envirofacts" in html

    def test_the_endpoint_is_still_valid_and_empty(self, client_in, unmapped_system):
        _, data = _geojson(client_in)
        assert data == {"type": "FeatureCollection", "features": []}


# -- 4. The drinking-water utility flavor ------------------------------------


class TestTheMapSurvivesWellsBeingOff:
    """`parcels`+`accounting` off takes `wells` with it (Phase 89).

    This is the deployment shape the milestone exists for, and the whole reason
    Task 1 put the geometry on `SystemFacility` instead of reading it through
    `SystemFacility.well`.
    """

    @pytest.fixture(autouse=True)
    def _wells_is_off(self, settings):
        compose_urlconf_under_the_full_module_set()
        settings.OPENH2O_MODULES = WITHOUT_WELLS

    def test_the_page_renders_with_its_map(self, client_in, mapped_system):
        response = client_in.get(reverse("drinking:sampling_points"))
        assert response.status_code == 200, (
            "the sampling-point page 500s on a drinking-water-only deployment"
        )
        html = response.content.decode()
        assert 'id="drinking-overview-map"' in html, "the map host vanished"

    def test_the_located_facilities_are_still_in_the_geojson(
        self, client_in, mapped_system
    ):
        _, data = _geojson(client_in)
        pks = {f["properties"]["pk"] for f in data["features"]}
        assert mapped_system["well_a"].pk in pks
        assert len(data["features"]) == 2

    def test_the_geometry_never_came_from_the_well(self, client_in, mapped_system):
        """No facility in this fixture has a well at all, and the map is full."""
        assert not SystemFacility.objects.filter(well__isnull=False).exists()
        _, data = _geojson(client_in)
        assert len(data["features"]) == 2
