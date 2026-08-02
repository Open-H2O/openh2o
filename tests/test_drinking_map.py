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
from django.db import connection
from django.test import Client, override_settings
from django.test.utils import CaptureQueriesContext
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
WITHOUT_DRINKING = [name for name in mod.ALL_MODULE_NAMES if name != "drinking"]

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
    @override_settings(ACCESS_CONTROL_ENFORCED=True)
    def test_anonymous_is_redirected_to_login(self, client, mapped_system):
        """An AGENCY deployment gates this layer, and the setting says so here.

        `public_in_open_demo` (1758b84) serves the map's GeoJSON layers to
        anonymous visitors when ACCESS_CONTROL_ENFORCED is False — the
        documented open-demo posture, and what the staging container runs. A
        test asserting the gated direction has to state the posture rather than
        inherit whichever one the container happens to have, or it passes in CI
        and fails on staging while both are behaving exactly as designed.
        """
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
        with CaptureQueriesContext(connection) as at_four:
            small = client_in.get(reverse("drinking:facilities_geojson"))
        assert len(json.loads(small.content.decode())["features"]) == 4

        build("CA9999999", 12)
        with CaptureQueriesContext(connection) as at_sixteen:
            large = client_in.get(reverse("drinking:facilities_geojson"))
        assert len(json.loads(large.content.decode())["features"]) == 16

        # Compared against each other, not against a magic number. The
        # docstring above always claimed this was a shape assertion; it then
        # pinned `3` twice, which is a magic number wearing a shape's clothes.
        # That absolute count moved when `public_in_open_demo` replaced
        # `login_required` (1758b84) — a change with no bearing whatever on
        # whether the view walks its rows — and the test went red for a reason
        # it was never meant to be sensitive to. Same defect as ISS-104,
        # same fix.
        assert len(at_sixteen) == len(at_four), (
            f"the layer cost {len(at_four)} queries at four facilities and "
            f"{len(at_sixteen)} at sixteen — it is walking the inventory:\n  "
            + "\n  ".join(q["sql"][:160] for q in at_sixteen.captured_queries)
        )


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
        """The gap is a fact about the public record, not a defect here.

        "Groundwater sources", not "source wells": the droppability vocabulary
        gate fails a kept page that says "wells" on a deployment without the
        Wells module, and it is right to — it cannot tell this module's WL
        facility type from that module's section.
        """
        html = _squash(
            client_in.get(reverse("drinking:sampling_points")).content.decode()
        ).lower()
        assert "groundwater sources" in html
        assert "gama" in html

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
        assert "groundwater sources" in html
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


# -- 5. The district map's drinking layer ------------------------------------
#
# The district map at `geography:map` is a declarative MAP_CONFIG rendered
# straight into the page, so what these tests read is the rendered configuration
# rather than a running map. That is the right level: MapLibre executing the
# config is MapLibre's problem, but whether the config NAMES a module this
# deployment does not run is this suite's.


class TestTheDistrictMapCarriesTheDrinkingLayer:
    def test_the_source_the_layer_and_the_legend_are_all_present(
        self, client_in, mapped_system
    ):
        response = client_in.get(reverse("geography:map"))
        assert response.status_code == 200
        html = response.content.decode()
        assert reverse("drinking:facilities_geojson") in html, (
            "the district map has no drinking GeoJSON source"
        )
        assert "id: 'drinking-points'" in html, "the drinking layer is missing"
        assert "'drinking-points': function" in html, "the layer has no popup builder"
        assert "Drinking Water Facilities" in html, "no legend or panel entry"

    def test_it_is_declared_before_wells_so_it_draws_underneath(
        self, client_in, mapped_system
    ):
        """The co-location property, pinned.

        Every located drinking-water facility in the demonstration also has a
        `Well` seeded from the SAME GAMA coordinate, so the two layers put dots
        on identical positions. MapLibre draws in array order. Declared second,
        drinking would sit ON TOP of wells and hide it — the failure this
        ordering exists to prevent, and one that looks like a working map.
        """
        html = client_in.get(reverse("geography:map")).content.decode()
        assert html.index("id: 'drinking-points'") < html.index("id: 'wells-points'"), (
            "the drinking layer is declared after wells, so it draws on top of "
            "it and hides the gold dot at every co-located facility"
        )

    def test_the_popup_carries_no_verdict(self, client_in, mapped_system):
        """The popup builder is JS in the page, so read it as text.

        Its `//` comments are stripped first, and deliberately: the comment
        beside the builder STATES the no-verdict rule, so scanning it would fail
        this assertion on the sentence that documents why the assertion exists.
        What is being read here is the HTML the builder emits.
        """
        html = client_in.get(reverse("geography:map")).content.decode()
        start = html.index("'drinking-points': function")
        builder = html[start:start + 1400]
        builder = "\n".join(
            line.split("//", 1)[0] for line in builder.splitlines()
        ).lower()
        for banned in ("limit", "mcl", "exceed", "violation", "compliance"):
            assert banned not in builder, (
                f"the district-map popup mentions {banned!r} — a popup is a view"
            )


class TestTheDistrictMapDropsTheDrinkingLayer:
    """The droppability property for a layer the harness cannot reach.

    `make test-droppable` renders `/map/` under every drop configuration, but it
    renders against an EMPTY database and asserts on visible text; the layer
    config lives inside a `<script>` and is stripped before that assertion ever
    sees it. So the module gate on this layer has no coverage there at all, and
    this is the only thing that reads it.
    """

    @pytest.fixture(autouse=True)
    def _drinking_is_off(self, settings):
        compose_urlconf_under_the_full_module_set()
        settings.OPENH2O_MODULES = WITHOUT_DRINKING

    def test_the_map_still_renders(self, client_in, mapped_system):
        response = client_in.get(reverse("geography:map"))
        assert response.status_code == 200, (
            "the district map 500s with the drinking module dropped"
        )

    def test_nothing_points_at_the_drinking_endpoint(self, client_in, mapped_system):
        html = client_in.get(reverse("geography:map")).content.decode()
        assert reverse("drinking:facilities_geojson") not in html, (
            "a source survived its module — MapLibre would fetch a 404 route"
        )
        assert "id: 'drinking-points'" not in html, (
            "a layer survived without its source, which is a MapLibre console "
            "error rather than a clean absence"
        )
        assert "Drinking Water Facilities" not in html, (
            "the legend still offers a layer this deployment does not have"
        )

    def test_the_page_description_stops_naming_drinking_water(
        self, client_in, mapped_system
    ):
        html = _squash(client_in.get(reverse("geography:map")).content.decode())
        assert "drinking-water facilities" not in html, (
            "the map's description enumerates a domain this deployment lacks"
        )


# -- 6. The detail mini-maps -------------------------------------------------


def _embedded_geojson(html, element_id):
    """The `json_script` payload for one element id, or None when absent.

    The distinction this helper exists to make: ABSENT is the correct state for
    an unlocated feature, and an empty FeatureCollection is not. Absent hides the
    whole card; present-and-empty renders an empty grey box.
    """
    marker = f'<script id="{element_id}" type="application/json">'
    if marker not in html:
        return None
    body = html.split(marker, 1)[1].split("</script>", 1)[0]
    return json.loads(body)


class TestTheFacilityDetailMap:
    def test_a_located_facility_carries_its_one_feature(
        self, client_in, mapped_system
    ):
        html = client_in.get(
            reverse("drinking:facility_detail", args=[mapped_system["well_a"].pk])
        ).content.decode()
        data = _embedded_geojson(html, "facility-geojson-data")
        assert data is not None, "a located facility has no geometry to draw"
        assert len(data["features"]) == 1
        assert data["features"][0]["geometry"]["coordinates"] == list(MERCED)
        assert 'id="detail-map"' in html, "the map host is missing"

    def test_an_unlocated_facility_emits_NO_element_at_all(
        self, client_in, mapped_system
    ):
        """Absent, not present-and-empty.

        `OH2O.detailPaneMap` hides its card when the element is missing and
        renders an empty grey rectangle when the element is there with no
        features. 40 of the 61 facilities in the demonstration are in this
        state, and every facility of an Envirofacts-onboarded system is.
        """
        response = client_in.get(
            reverse("drinking:facility_detail", args=[mapped_system["unlocated"].pk])
        )
        assert response.status_code == 200
        html = response.content.decode()
        assert _embedded_geojson(html, "facility-geojson-data") is None, (
            "an unlocated facility emitted a FeatureCollection — an empty one "
            "renders an empty grey map box, which is worse than no map"
        )
        assert 'id="detail-map"' not in html, "an empty map host was rendered"

    def test_it_says_why_there_is_no_map(self, client_in, mapped_system):
        html = _squash(
            client_in.get(
                reverse(
                    "drinking:facility_detail", args=[mapped_system["unlocated"].pk]
                )
            ).content.decode()
        )
        assert "No published coordinate for this facility" in html
        assert "groundwater sources" in html, (
            "the sentence does not say where locations come from"
        )
        # It may say where coordinates COME FROM; it may not say why THIS row
        # lacks one. 10 of the 40 unlocated facilities on staging are wells, so
        # "this is a treatment plant" would be a cause the page cannot see.
        assert "carry none" not in html, (
            "the sentence asserts a cause for this particular facility"
        )

    def test_the_geojson_properties_carry_no_verdict(self, client_in, mapped_system):
        html = client_in.get(
            reverse("drinking:facility_detail", args=[mapped_system["well_a"].pk])
        ).content.decode()
        data = _embedded_geojson(html, "facility-geojson-data")
        for key in data["features"][0]["properties"]:
            lowered = key.lower()
            for banned in ("limit", "mcl", "exceed", "violation", "status"):
                assert banned not in lowered, (
                    f"the detail map carries a property named {key!r}"
                )


class TestTheSamplingPointDetailMap:
    def test_it_is_drawn_at_its_facility_and_says_so(self, client_in, mapped_system):
        point = mapped_system["points"][0]          # on well_a, which is located
        html = client_in.get(
            reverse("drinking:sampling_point_detail", args=[point.pk])
        ).content.decode()
        data = _embedded_geojson(html, "point-geojson-data")
        assert data is not None
        properties = data["features"][0]["properties"]
        assert properties["ps_code"] == point.ps_code, (
            "the popup cannot attribute a coordinate it was never given"
        )
        assert properties["facility_id"] == mapped_system["well_a"].facility_id
        # 99-02's requirement, re-pointed at the FACT rather than the sentence
        # (101-02). The original pinned "Shown at the location of facility {id}"
        # verbatim, which made the correct copy a test failure the moment the
        # caption was tightened at 101-02's checkpoint. What 99-02 actually
        # required — and what this now asserts — is that the caption NAMES the
        # facility whose coordinate this is, and ATTRIBUTES it, so a reader
        # cannot come away believing the tap itself was surveyed.
        # The caption is the <p> inside the map card, after the map element
        # itself — hence splitting on the map div rather than on the card's
        # opening tag, whose first </div> closes the map and not the caption.
        card = html.split('id="detail-map-card"', 1)[1] if 'id="detail-map-card"' in html else ""
        caption = _squash(card.split('id="detail-map"', 1)[-1].split("</p>", 1)[0])
        assert mapped_system["well_a"].facility_id in caption, (
            "the map caption does not name whose coordinate this is, so a "
            "reader may believe the tap itself was surveyed"
        )
        assert "Source:" in caption, (
            "the borrowed coordinate carries no publisher attribution"
        )
        assert "not this point" in caption or "not for this point" in caption, (
            "the caption never says the coordinate is not the point's own"
        )

    def test_a_point_on_an_unlocated_facility_emits_NO_element_at_all(
        self, client_in, mapped_system
    ):
        point = mapped_system["points"][3]          # on the DST facility
        response = client_in.get(
            reverse("drinking:sampling_point_detail", args=[point.pk])
        )
        assert response.status_code == 200
        html = response.content.decode()
        assert _embedded_geojson(html, "point-geojson-data") is None
        assert 'id="detail-map"' not in html
        assert "has no published coordinate" in _squash(html)

    def test_the_geojson_properties_carry_no_verdict(self, client_in, mapped_system):
        html = client_in.get(
            reverse(
                "drinking:sampling_point_detail",
                args=[mapped_system["points"][0].pk],
            )
        ).content.decode()
        data = _embedded_geojson(html, "point-geojson-data")
        for key in data["features"][0]["properties"]:
            lowered = key.lower()
            for banned in ("limit", "mcl", "exceed", "violation", "status"):
                assert banned not in lowered, (
                    f"the detail map carries a property named {key!r}"
                )


# -- 7. The wells guard survives the new blocks ------------------------------


class TestTheWellsGuardStillHoldsOnBothDetailPages:
    """98-01 pinned this in `TestWellLinkIsModuleGuarded`; re-pin it here.

    Both pages just gained a new context value, two new template blocks and a
    new section. `drinking.requires` is ("standards",), so an unguarded
    `{% url 'wells:detail' %}` on either is a NoReverseMatch 500 on the
    drinking-water-utility deployment this milestone exists to serve — not a
    missing link.
    """

    @pytest.fixture(autouse=True)
    def _wells_is_off(self, settings):
        compose_urlconf_under_the_full_module_set()
        settings.OPENH2O_MODULES = WITHOUT_WELLS

    def test_the_facility_page_renders_with_its_map(self, client_in, mapped_system):
        response = client_in.get(
            reverse("drinking:facility_detail", args=[mapped_system["well_a"].pk])
        )
        assert response.status_code == 200, (
            "the facility page 500s on a drinking-water-only deployment"
        )
        html = response.content.decode()
        assert "/wells/" not in html, "an unguarded wells link survived"
        assert 'id="detail-map"' in html, "the map vanished with the wells module"

    def test_the_sampling_point_page_renders_with_its_map(
        self, client_in, mapped_system
    ):
        response = client_in.get(
            reverse(
                "drinking:sampling_point_detail",
                args=[mapped_system["points"][0].pk],
            )
        )
        assert response.status_code == 200
        html = response.content.decode()
        assert "/wells/" not in html
        assert 'id="detail-map"' in html
