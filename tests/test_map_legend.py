# SPDX-License-Identifier: AGPL-3.0-or-later
"""The district map's key: what the rendered MAP_CONFIG has to declare.

**Which surface names the layers, and why it matters here.** The map's key is the
LAYERS PANEL — it names every layer, shows its colour swatch, and carries a live
feature count, and it is always on screen. The small legend box in the
bottom-left once carried the per-zone-name colour breakdown; since the map's
symbols were redrawn by role (``test_map_symbols.py``) management areas are a
dashed line with their names on the map, so the box declares no section of its
own on the Map page.

That division was settled on 2026-08-05 after the first pass at ISS-116 gave the
legend one row per populated layer and produced a second panel repeating the
first, heading for heading. The defect ISS-116 reported was a legend naming
*Drinking Water Facilities* over a layer with ZERO features while 206 unlabelled
red monitoring-station dots went unnamed — so the natural reading was that the
red dots were drinking-water facilities. Deleting that hardcoded row is the fix.

What this file therefore pins:

* **Every layer that can be drawn can also be keyed.** A layer with a `label` and
  no `swatch`/colour is a layer no surface can name — the exact shape of the
  defect, and it would be silent.
* **The hardcoded legend pair is gone**, and `MAP_CONFIG.legend` declares no
  section, so the misleading row cannot come back unnoticed.
* **The count filters are declared.** Two layers sharing one source have to
  narrow it the way their MapLibre filters do, or the panel reports the same
  number twice (measured at 4,672 for both rivers and canals).

**Be clear about what pytest cannot see here.** The panel and the legend are both
assembled in the BROWSER, and this repository has a hard "No Node.js" constraint,
so nothing below asserts on finished `.layer-toggle` or `.legend-row` elements.
Those were verified in a real browser on staging at the phase's checkpoint and
the measurements are recorded in the summary. What this file proves is that the
configuration handed to the browser DECLARES everything those surfaces need.

Everything is read from the RENDERED response rather than the template source,
so the `{% if ... in enabled_modules %}` guards are resolved before we look.

Deliberately absent: any test that string-matches `static/js/map-engine.js` to
assert on JavaScript control flow. A grep over source code is not a behavioural
guard and rots on the first refactor.
"""

import json
import re
from pathlib import Path

import factory
import pytest
from django.contrib.auth.hashers import make_password
from django.contrib.gis.geos import Point
from django.test import Client
from django.urls import reverse

from tests.factories import (
    MonitoredStationFactory,
    SystemFacilityFactory,
    WaterSystemFactory,
    ZoneFactory,
)

#: Somewhere in Merced, so a coordinate that survives into the page is
#: recognisable as a real place rather than the (0, 0) default.
MERCED = (-120.4829, 37.3022)


class UserFactory(factory.django.DjangoModelFactory):
    """Local, matching the house convention — every suite file defines its own."""

    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"maplegend{n}")
    email = factory.Sequence(lambda n: f"maplegend{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True


@pytest.fixture
def client_in(db):
    client = Client()
    client.force_login(UserFactory())
    return client


@pytest.fixture
def two_populated_modules(db):
    """Rows in more than one optional module — the regression, stated as data.

    Run 003 had 206 monitoring stations and a legend with no way to name them,
    while the one row it did show belonged to a layer with nothing in it. A
    deployment carrying both kinds of feature is the case that has to work.
    """
    system = WaterSystemFactory(pwsid="CA2410009", name="Cedar Grove Water District")
    facility = SystemFacilityFactory(
        system=system,
        facility_id="010",
        name="Well 08",
        facility_type="WL",
        location=Point(*MERCED, srid=4326),
    )
    station = MonitoredStationFactory(
        station_name="Merced River at Cressey",
        location=Point(MERCED[0] + 0.01, MERCED[1] + 0.01, srid=4326),
    )
    return {"system": system, "facility": facility, "station": station}


@pytest.fixture
def management_areas(db):
    """Two management-area zones, so the explicit legend section has content.

    Kept separate from `two_populated_modules` on purpose: the per-zone-name
    breakdown only renders for `zone_type='management_area'`, and the case where
    it does NOT render — a real basin whose zones are subbasins — is the case the
    zone-swatch test below has to exercise.
    """
    return [
        ZoneFactory(name="Halvern Valley GSA"),
        ZoneFactory(name="Verdano Island Water District GSA"),
    ]


# -- Reading the rendered MAP_CONFIG -----------------------------------------
#
# MAP_CONFIG is JavaScript, not JSON — it carries function expressions, comments
# and `OH2O.colors.*` references — so it is read structurally rather than parsed.
# The two helpers below walk balanced brackets, which is enough to isolate one
# array element without pretending to be a JavaScript engine.


def _strip_line_comments(text):
    """Drop whole-line `//` comments so bracket walking is not fooled by prose."""
    return "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("//")
    )


def _balanced(text, start):
    """Return text[start:] up to and including the bracket at `start`'s match."""
    closers = {"[": "]", "{": "}", "(": ")"}
    stack, quote, i = [], None, start
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in "'\"":
            quote = ch
        elif ch in closers:
            stack.append(closers[ch])
        elif stack and ch == stack[-1]:
            stack.pop()
            if not stack:
                return text[start : i + 1]
        i += 1
    raise AssertionError("MAP_CONFIG has an unbalanced bracket")


def _array(html, key):
    """The text of the `key: [ ... ]` array in the rendered MAP_CONFIG."""
    text = _strip_line_comments(html)
    marker = re.search(r"\n\s*%s:\s*\[" % re.escape(key), text)
    assert marker, f"MAP_CONFIG has no `{key}` array"
    return _balanced(text, text.index("[", marker.start()))


def _elements(array_text):
    """Split a `[ ... ]` array into its top-level elements."""
    inner = array_text[1:-1]
    parts, depth, quote, start = [], 0, None, 0
    for i, ch in enumerate(inner):
        if quote:
            if ch == "\\":
                continue
            if ch == quote:
                quote = None
        elif ch in "'\"":
            quote = ch
        elif ch in "[{(":
            depth += 1
        elif ch in "]})":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append(inner[start:i])
            start = i + 1
    parts.append(inner[start:])
    return [p.strip() for p in parts if p.strip()]


#: `label:` and not `label_id:`, which is a different key on the same objects.
LABEL = re.compile(r"(?<![\w-])label:\s*'([^']+)'")


def _labelled_layers(html):
    """Every element of MAP_CONFIG.layers that declares a human-facing name."""
    found = []
    for element in _elements(_array(html, "layers")):
        match = LABEL.search(element)
        if match:
            found.append((match.group(1), element))
    return found


def _labelled_ids(html):
    """``{layer id: element}`` for every named layer, so a test can find a layer
    without pinning the words the panel shows."""
    found = {}
    for _, element in _labelled_layers(html):
        match = re.search(r"(?<![\w-])id:\s*'([^']+)'", element)
        if match:
            found[match.group(1)] = element
    return found


def _rendered(client):
    response = client.get(reverse("geography:map"))
    assert response.status_code == 200
    return response.content.decode()


# -- 1. Every drawable layer is legend-capable --------------------------------


class TestEveryNamedLayerCanBeKeyed:
    def test_each_labelled_layer_declares_a_swatch_and_a_colour(
        self, client_in, two_populated_modules
    ):
        """A layer that can be drawn but cannot be keyed is the defect itself.

        The Layers panel takes its swatch straight off the layer object, so a
        `label` with no `swatch` would render a row with an invisible marker,
        and a `swatch` with no colour a marker with no identity — a layer on the
        map that nothing on the page can name.
        """
        layers = _labelled_layers(_rendered(client_in))
        assert layers, "the rendered map declares no named layers at all"
        for name, element in layers:
            assert re.search(r"(?<![\w-])swatch:\s*'", element), (
                f"layer {name!r} has a label but no swatch — the legend cannot key it"
            )
            assert "swatchColor:" in element or "swatchStyle:" in element, (
                f"layer {name!r} has a swatch with no colour or style"
            )

    def test_the_named_layers_cover_every_section_the_panel_shows(
        self, client_in, two_populated_modules
    ):
        """Sanity on the reader above: it finds layers across the whole config,
        not just the first block, so a silent parse failure cannot pass."""
        ids = set(_labelled_ids(_rendered(client_in)))
        assert {"boundary-outline", "zones-outline", "flowlines-rivers", "wells-points"} <= ids


# -- 2. The hardcoded legend pair is gone -------------------------------------


class TestTheExplicitLegendHoldsOnlyTheZoneBreakdown:
    def test_there_is_no_hardcoded_drinking_water_section(
        self, client_in, two_populated_modules
    ):
        """The misleading row is deleted, not replaced.

        Before this phase the legend named Drinking Water Facilities whether or
        not the deployment had any — on run 003 it had none — while naming no
        other layer at all. Naming the layers is the Layers panel's job, and it
        does it from live counts.
        """
        legend = _array(_rendered(client_in), "legend")
        assert "title: 'Drinking Water'" not in legend, (
            "the hardcoded Drinking Water legend section is back"
        )

    def test_management_areas_are_not_a_legend_section(
        self, client_in, two_populated_modules, management_areas
    ):
        """Management areas are a dashed line with their names on the map.

        Their per-zone colour breakdown was the one reason the legend box held a
        section; with no fill there is no colour to key, and the names sit on
        the areas themselves.
        """
        legend = _array(_rendered(client_in), "legend")
        assert not re.findall(r"title:\s*'([^']+)'", legend), legend
        for zone in management_areas:
            assert zone.name not in legend

    def test_with_no_management_areas_the_legend_box_has_nothing_to_show(
        self, client_in, two_populated_modules
    ):
        """The box then hides itself rather than sitting there empty.

        Nothing is lost: the Layers panel still names every layer on the map.
        """
        assert not re.findall(
            r"title:\s*'([^']+)'", _array(_rendered(client_in), "legend")
        )

    def test_the_drinking_layer_still_carries_its_own_name_and_colour(
        self, client_in, two_populated_modules
    ):
        """Removing the section must not remove the layer's ability to be named."""
        layers = _labelled_ids(_rendered(client_in))
        assert "drinking-points" in layers
        assert "OH2O.colors.drinking" in layers["drinking-points"]


# -- 3. A deployment with data in two modules can name both -------------------


class TestBothPopulatedModulesAreReachable:
    def test_stations_and_facilities_are_both_declared_with_their_colours(
        self, client_in, two_populated_modules
    ):
        """The regression, stated directly.

        Run 003 drew 206 stations that nothing on the page named. Whether the
        panel row actually renders is a browser matter this suite cannot see;
        what it can see is that both layers arrive fully described.
        """
        layers = _labelled_ids(_rendered(client_in))
        assert "stations-points" in layers, "the map cannot name its stations"
        assert "OH2O.colors.station" in layers["stations-points"]
        assert "drinking-points" in layers
        assert "OH2O.colors.drinking" in layers["drinking-points"]

    def test_the_zone_swatch_matches_the_line_the_map_actually_paints(
        self, client_in, two_populated_modules
    ):
        """Management areas are a sand dashed line, and the swatch says so."""
        element = _labelled_ids(_rendered(client_in))["zones-outline"]
        paint, swatch = element.split("swatch:")
        assert "'line-color': OH2O.colors.managementArea" in paint
        assert "line-dasharray" in paint
        assert "'line-dash'" in swatch and "OH2O.colors.managementArea" in swatch


# -- 4. The per-layer count filters --------------------------------------------


class TestSharedSourcesAreNarrowedPerLayer:
    """Two layers on one source must count their own features, not the source's.

    Without these the Layers panel reported Rivers & Streams and Canals & Ditches
    at the same number (ISS-116 measured 4,672 twice) — and since the panel is
    the map's key, a wrong count there is a wrong statement about the map.
    """

    @pytest.mark.parametrize(
        "layer_id,expected",
        [
            ("flowlines-rivers", "{ prop: 'feature_type', notContains: 'Canal' }"),
            ("flowlines-canals", "{ prop: 'feature_type', contains: 'Canal' }"),
            ("zones-outline", "{ prop: 'zone_type', val: 'management_area' }"),
            ("service-areas-outline", "{ prop: 'zone_type', notVal: 'management_area' }"),
        ],
    )
    def test_the_filter_mirrors_the_layers_own_maplibre_filter(
        self, client_in, two_populated_modules, layer_id, expected
    ):
        layers = _labelled_ids(_rendered(client_in))
        assert layer_id in layers, f"{layer_id} is not declared on the map"
        assert f"countFilter: {expected}" in layers[layer_id], (
            f"{layer_id} does not narrow its shared source the way it draws"
        )

    def test_each_filtered_layer_names_a_property_its_maplibre_filter_uses(
        self, client_in, two_populated_modules
    ):
        """A count filter on a property the layer does not filter on is a lie."""
        for name, element in _labelled_layers(_rendered(client_in)):
            match = re.search(r"countFilter:\s*\{\s*prop:\s*'([^']+)'", element)
            if not match:
                continue
            prop = match.group(1)
            filter_text = element.split("countFilter:")[0]
            assert f"'{prop}'" in filter_text, (
                f"{name} counts on {prop!r}, which its MapLibre filter never mentions"
            )


# -- 5. Two kinds of zone, each its own line -----------------------------------
#
# The `zones` source carries management-area GSA zones AND everything else
# (surface service areas in the demonstration). One fill layer drawing both
# meant the legend named three GSA greens against a layer of eight zones
# (R-095), and a district's worth of long service-area names piled east of
# Merced with nothing to thin them out (R-094). Both are fixed by splitting
# into two layer groups that filter the SAME source the same way their
# MapLibre `filter` does (the ISS-116 lesson `countFilter` already pins
# above), plus a `minzoom` on the service-area label so it only exists where
# its own popup does.


def _element_containing(html, key, needle):
    """The one element of a MAP_CONFIG array (`layers`/`legend`/...) whose
    text contains `needle`, or a clear failure naming what was searched."""
    for element in _elements(_array(html, key)):
        if needle in element:
            return element
    raise AssertionError(f"no element of {key!r} contains {needle!r}")


class TestTheDistrictSplitsIntoTwoZoneKinds:
    def test_zones_outline_is_filtered_to_management_area_and_keyed(self, client_in):
        element = _element_containing(
            _rendered(client_in), "layers", "id: 'zones-outline'"
        )
        assert "filter: ['==', ['get', 'zone_type'], 'management_area']" in element
        assert LABEL.search(element), "the management areas layer has no name"
        assert "swatch: 'line-dash'" in element

    def test_service_areas_outline_is_filtered_to_everything_else_and_keyed(
        self, client_in
    ):
        element = _element_containing(
            _rendered(client_in), "layers", "id: 'service-areas-outline'"
        )
        assert "filter: ['!=', ['get', 'zone_type'], 'management_area']" in element
        assert LABEL.search(element), "the other zones layer has no name"
        assert "swatch: 'line-dash'" in element

    def test_service_area_labels_do_not_exist_below_zoom_11(self, client_in):
        """R-094: the layer and its popups don't exist below 11 either, a
        label with no way to reach the thing it names would just be more
        pile."""
        element = _element_containing(
            _rendered(client_in), "layers", "'service-areas-label'"
        )
        assert "minzoom: 11" in element

    def test_the_map_names_exactly_the_management_area_zones(self, client_in):
        """The names sit on the areas: the label layer reads the management areas only."""
        element = _element_containing(
            _rendered(client_in), "layers", "'zones-label'"
        )
        assert "filter: ['==', ['get', 'zone_type'], 'management_area']" in element


class TestTheTwoZoneKindsAreTellableApart:
    def test_management_areas_and_other_zones_differ_in_colour_and_dash(self, client_in):
        html = _rendered(client_in)
        managed = _element_containing(html, "layers", "id: 'zones-outline'")
        other = _element_containing(html, "layers", "id: 'service-areas-outline'")
        assert "OH2O.colors.managementArea" in managed and "OH2O.colors.serviceArea" in other
        dash = re.compile(r"'line-dasharray':\s*(\[[^\]]*\])")
        assert dash.search(managed).group(1) != dash.search(other).group(1)


class TestZoneLabelsGeojsonCarriesTheFollowFilterFields:
    """`zone_labels_geojson` feeds the Zones overview map's follow helper
    (143-07 Task 4) and the district map's two label layers (Task 5) alike;
    both need `pk` and `zone_type` to filter by, and the district map's
    service-area label reads `short_label`/`label` rather than the stored
    name so a demonstration's composed suffix does not pile against markers.
    """

    def test_features_carry_pk_zone_type_and_a_parenthetical_stripped_label(
        self, client_in, db
    ):
        zone = ZoneFactory(name="Halvern Irrigation District (MER-WR-004-DEMO)")
        response = client_in.get(reverse("geography:zone_labels_geojson"))
        assert response.status_code == 200
        data = json.loads(response.content)
        feature = next(
            f for f in data["features"] if f["properties"]["pk"] == zone.pk
        )
        assert feature["properties"]["zone_type"] == "management_area"
        assert feature["properties"]["label"] == "Halvern Irrigation District", (
            "a zone named \"X (Y)\" must label as \"X\""
        )


class TestThePanelShowsWhenItCanScrollFurther:
    """R-096. The panel fits at 1,730 x 1,000 (Task 1 measured it there) and
    clips at 1,440 x 900: a DOM measurement at both viewports, which this
    file's own docstring says pytest cannot make (the panel is assembled in
    the browser). It lives in `143-07-EVIDENCE.md`, not here. What this guard
    proves is that the affordance rule map-engine.js toggles actually exists
    in the stylesheet, so a future edit to `.panel-body` cannot silently drop
    it and leave the toggle with nothing to reveal.
    """

    def test_the_bottom_fade_rule_is_declared(self):
        css_path = Path(__file__).resolve().parent.parent / "static/css/map-engine.css"
        css = css_path.read_text()
        assert "#controls.panel-can-scroll::after" in css, (
            "the panel's scroll-affordance rule is gone from map-engine.css"
        )
        assert "pointer-events: none" in css.split("panel-can-scroll::after")[1][:400]
