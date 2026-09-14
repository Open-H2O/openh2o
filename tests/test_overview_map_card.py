# SPDX-License-Identifier: AGPL-3.0-or-later
"""The overview map card (143-07): one head, one key, always-on labels, the
map follows the list.

Task 2 designed the card on Surface Diversions and Task 4 copied it, class for
class, to Recharge Areas, Zones, Sampling Points, Facilities and Monitoring
Stations. This file is the guard for the pattern itself, closing five of the
plan's twelve register rows:

  R-023  four overview maps used to ignore the list's own filter: typing a
         query swapped the list and left every mark on the map where it was.
         `OH2O.followResults` reads the WHOLE filtered queryset's pks from
         `results-map-pks` (a `json_script`) after every htmx swap of
         `#results`, so this file proves the SERVER side of that contract:
         the results partial emits exactly the matching pks, the head above
         the map (never a `.result-count-bar` inside `#results`) states the
         count the list is showing, and an htmx swap re-renders that same
         head out of band (`hx-swap-oob="true"`) rather than losing it.
  R-022  the Surface Diversions card: a count line and a key on one row, an
         always-on label layer on the pods source.
  R-124  the Recharge Areas card: a second `-labels` source (one label per
         SITE, not per polygon ring) and the paint values that make a small
         basin (33-263 e-6 deg^2) read as a shape rather than two smudges.

Every assertion is a value read off the rendered response, never a grep of
`map-core.js` for control flow (`tests/test_map_legend.py`'s docstring says
why a behavioural guard has to stop at the fence a browser starts).
"""

import json
import re

import factory
import pytest
from django.contrib.auth.hashers import make_password
from django.contrib.gis.geos import Point
from django.test import Client
from django.urls import reverse

from tests.factories import (
    MonitoredStationFactory,
    PointOfDiversionFactory,
    RechargeSiteFactory,
    SamplingPointFactory,
    SystemFacilityFactory,
    ZoneFactory,
)


class UserFactory(factory.django.DjangoModelFactory):
    """Local, matching the house convention: every suite file defines its own."""

    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"overviewmap{n}")
    email = factory.Sequence(lambda n: f"overviewmap{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True


@pytest.fixture
def auth_client(db):
    client = Client()
    client.force_login(UserFactory())
    return client


def _pks_script(html, element_id="results-map-pks"):
    """The parsed JSON array a `json_script` tag with this id carries."""
    match = re.search(
        r'<script[^>]*id="%s"[^>]*>(.*?)</script>' % re.escape(element_id),
        html,
        re.DOTALL,
    )
    assert match, f"no <script id=\"{element_id}\"> in the response"
    return json.loads(match.group(1))


def _head_div(html, head_id):
    """The opening `<div id="{head_id}" ...>` tag, so its attributes can be read."""
    match = re.search(r'<div id="%s"[^>]*>' % re.escape(head_id), html)
    assert match, f'no <div id="{head_id}"> in the response'
    return match.group(0)


# ---------------------------------------------------------------------------
# R-023: the map follows the list, on all five overview pages.
# ---------------------------------------------------------------------------


def _build_pods():
    alpha = PointOfDiversionFactory(name="Alpha Weir")
    PointOfDiversionFactory(name="Beta Weir")
    PointOfDiversionFactory(name="Gamma Weir")
    return alpha, [alpha.pk]


def _build_recharge():
    alpha = RechargeSiteFactory(name="Alpha Basin")
    RechargeSiteFactory(name="Beta Basin")
    RechargeSiteFactory(name="Gamma Basin")
    return alpha, [alpha.pk]


def _build_zones():
    alpha = ZoneFactory(name="Alpha Zone")
    ZoneFactory(name="Beta Zone")
    ZoneFactory(name="Gamma Zone")
    return alpha, [alpha.pk]


def _build_sampling_points():
    alpha_facility = SystemFacilityFactory(location=Point(-119.50, 36.50))
    beta_facility = SystemFacilityFactory(location=Point(-119.51, 36.51))
    gamma_facility = SystemFacilityFactory(location=Point(-119.52, 36.52))
    alpha = SamplingPointFactory(name="Alpha Point", facility=alpha_facility)
    SamplingPointFactory(name="Beta Point", facility=beta_facility)
    SamplingPointFactory(name="Gamma Point", facility=gamma_facility)
    # The map draws FACILITIES: the matching pk is the matching POINT's
    # facility pk, not the point's own pk (drinking/views.py::sampling_points).
    return alpha, [alpha_facility.pk]


def _build_stations():
    alpha = MonitoredStationFactory(station_name="Alpha Station")
    MonitoredStationFactory(station_name="Beta Station")
    MonitoredStationFactory(station_name="Gamma Station")
    return alpha, [alpha.pk]


def _pods_full_line():
    from surface.models import PointOfDiversion

    count = PointOfDiversion.objects.count()
    noun = "diversion point" if count == 1 else "diversion points"
    return f"{count:,} {noun}, all on the map"


def _recharge_full_line():
    from recharge.models import RechargeSite

    count = RechargeSite.objects.count()
    noun = "recharge site" if count == 1 else "recharge sites"
    return f"{count:,} {noun}, all on the map"


def _zones_full_line():
    from geography.models import Zone

    count = Zone.objects.count()
    noun = "zone" if count == 1 else "zones"
    return f"{count:,} {noun}, all on the map"


def _sampling_points_full_line():
    from drinking.models import SamplingPoint, SystemFacility

    all_count = SamplingPoint.objects.count()
    mapped_facility_count = SystemFacility.objects.filter(
        location__isnull=False
    ).count()
    noun = "sampling point" if all_count == 1 else "sampling points"
    return (
        f"{all_count:,} {noun}; {mapped_facility_count:,} of them at a "
        "located facility, on the map"
    )


def _stations_full_line():
    from datasync.models import MonitoredStation

    count = MonitoredStation.objects.filter(is_active=True).count()
    noun = "station" if count == 1 else "stations"
    return f"{count:,} {noun}, syncing"


#: One row per overview list: the url name, the fixture builder, the head's
#: element id, the query param that filters by name, and a callable computing
#: the full-page (unfiltered) head line from the LIVE database total AFTER
#: `build()` runs. Not a literal "3 …" string: `drinking`'s Merced demonstration
#: seed (`tests/test_merced_drinking_seed.py`, module-scoped, committed outside
#: any test's transaction so 22k lab results are not re-imported per test) is
#: real, permanent data for the rest of this test session once that module has
#: run, collected alphabetically before this file, so a hardcoded facility
#: or sampling-point total is order-dependent. Computing the expected line from
#: the same totals the view itself counts keeps this a real value assertion
#: (a wrong noun form or a dropped clause still fails it) without assuming an
#: empty database.
CASES = [
    pytest.param(
        "surface:pod_list", _build_pods, "pods-overview-map-head", "q",
        _pods_full_line,
        id="pods",
    ),
    pytest.param(
        "recharge:list", _build_recharge, "recharge-overview-map-head", "q",
        _recharge_full_line,
        id="recharge",
    ),
    pytest.param(
        "geography:zone_list", _build_zones, "zones-overview-map-head", "q",
        _zones_full_line,
        id="zones",
    ),
    pytest.param(
        "drinking:sampling_points", _build_sampling_points,
        "sampling-points-map-head", "q",
        _sampling_points_full_line,
        id="sampling_points",
    ),
    pytest.param(
        "datasync:station_list", _build_stations, "stations-overview-map-head", "q",
        _stations_full_line,
        id="stations",
    ),
]


@pytest.mark.django_db
@pytest.mark.parametrize("url_name,build,head_id,query_param,full_line_fn", CASES)
def test_the_map_follows_the_list(
    auth_client, url_name, build, head_id, query_param, full_line_fn
):
    matched, expected_pks = build()
    url = reverse(url_name)
    full_line = full_line_fn()

    # 1. The full page (no filter): the head states what the WHOLE list
    #    counts, and the count line lives nowhere else on the page.
    full_body = auth_client.get(url).content.decode()
    assert full_line in full_body, (
        f"{url_name}: the unfiltered head does not read {full_line!r}"
    )
    assert "result-count-bar" not in full_body, (
        f"{url_name}: a second count line survives outside the map card head"
    )

    # 2. An htmx swap matching exactly one row: the results partial carries
    #    the whole filtered queryset's pks (never the page's), and re-renders
    #    the SAME head out of band rather than dropping it.
    match_name = matched.name if hasattr(matched, "name") else matched.station_name
    query_text = match_name.split()[0]  # "Alpha", unique to one fixture row
    filtered_body = auth_client.get(
        url, {query_param: query_text}, HTTP_HX_REQUEST="true"
    ).content.decode()

    assert _pks_script(filtered_body) == expected_pks, (
        f"{url_name}: results-map-pks does not carry exactly the matching pk(s)"
    )
    head_tag = _head_div(filtered_body, head_id)
    assert 'hx-swap-oob="true"' in head_tag, (
        f"{url_name}: the swapped-in head is not marked hx-swap-oob, "
        "so the count above the map goes stale on every filter"
    )
    assert "result-count-bar" not in filtered_body, (
        f"{url_name}: a second count line survives inside the swapped results"
    )


# ---------------------------------------------------------------------------
# R-022: the Surface Diversions card as built (title, key, always-on labels).
# ---------------------------------------------------------------------------


class TestSurfaceDiversionsCard:
    def test_the_head_reads_the_count_and_carries_the_key(self, auth_client):
        PointOfDiversionFactory(name="Card Weir One")
        PointOfDiversionFactory(name="Card Weir Two")
        PointOfDiversionFactory(name="Card Weir Three")

        body = auth_client.get(reverse("surface:pod_list")).content.decode()
        assert "3 diversion points, all on the map" in body
        assert 'class="swatch-dot"' in body
        assert "Diversion point" in body

    def test_the_map_partial_declares_an_always_on_label_layer(self, auth_client):
        from django.template.loader import render_to_string

        rendered = render_to_string(
            "surface/partials/_pods_overview_map.html", {"map_id": "pods-overview-map"}
        )
        assert "-label'" in rendered or '-label"' in rendered, (
            "the pods overview map declares no label layer id"
        )
        assert "addDetailLabel" in rendered


# ---------------------------------------------------------------------------
# R-124: the Recharge Areas card (label-per-site source, the fill/outline
# strengthened so a small basin reads at the fitted zoom).
# ---------------------------------------------------------------------------


class TestRechargeAreasCard:
    def test_the_head_reads_the_count_for_a_two_site_fixture(self, auth_client):
        RechargeSiteFactory(name="Two Site Basin One")
        RechargeSiteFactory(name="Two Site Basin Two")

        body = auth_client.get(reverse("recharge:list")).content.decode()
        assert "2 recharge sites, all on the map" in body

    def test_the_map_partial_declares_the_labels_source_and_its_symbol_layer(
        self, auth_client
    ):
        from django.template.loader import render_to_string

        rendered = render_to_string(
            "recharge/partials/_recharge_overview_map.html",
            {"map_id": "recharge-overview-map"},
        )
        assert "-labels'" in rendered
        assert "addDetailLabel" in rendered

    def test_the_fill_opacity_and_outline_width_are_the_143_07_values(
        self, auth_client
    ):
        from django.template.loader import render_to_string

        rendered = render_to_string(
            "recharge/partials/_recharge_overview_map.html",
            {"map_id": "recharge-overview-map"},
        )
        assert "'fill-opacity': 0.35" in rendered, (
            "the recharge fill is still the pre-143-07 0.22 (two faint smudges)"
        )
        assert "'line-width': 2.5" in rendered, (
            "the recharge outline is still the pre-143-07 1.5px"
        )
