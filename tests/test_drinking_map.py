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
