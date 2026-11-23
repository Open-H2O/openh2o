# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Map page's symbols and colours, read as one system.

Every mark on the Map page says what it is by its role, its hue and its shape:
the frame (boundary, management areas, service areas) is lines only; water is
one blue; the site's own records each take their own hue and their own shape;
outside data is a neutral grey; crop ET is the only shaded fill and runs light
to dark for less to more. The links from a well or a point of diversion to its
use areas are drawn only when that well or point is picked.

Read structurally from the rendered page and from ``map-core.js`` /
``tokens.css``, as ``test_map_legend.py`` does: the panel and the marks are
assembled in the browser and this repository runs no Node.js, so what is pinned
here is what the configuration and the palette DECLARE, plus the two GeoJSON
endpoints whose geometry decides where a label or a link lands.
"""

import json
import math
import re
from pathlib import Path

import pytest
from django.contrib.gis.geos import MultiPolygon, Point, Polygon
from django.test import Client
from django.urls import reverse

from tests.factories import (
    BoundaryFactory,
    ParcelFactory,
    WellFactory,
    WellIrrigatedParcelFactory,
)
from tests.test_map_legend import (  # the structural readers, one copy
    UserFactory,
    _array,
    _elements,
    _rendered,
)

ROOT = Path(__file__).resolve().parent.parent
MAP_CORE_JS = ROOT / "static/js/map-core.js"
TOKENS_CSS = ROOT / "static/css/tokens.css"

#: The layer ids that draw one mark per record, and the mark kind each draws.
POINT_LAYERS = {
    "wells-points": "well",
    "pods-points": "pod",
    "stations-points": "station",
    "recharge-points": "recharge",
    "drinking-points": "drinking",
}


@pytest.fixture
def client_in(db):
    client = Client()
    client.force_login(UserFactory())
    return client


def _layers_by_id(html):
    found = {}
    for element in _elements(_array(html, "layers")):
        match = re.search(r"(?<![\w-])id:\s*'([^']+)'", element)
        if match:
            found[match.group(1)] = element
    return found


def _map_core():
    return re.sub(r"(?m)^\s*//[^\n]*$", "", MAP_CORE_JS.read_text())


def _object_literal(source, name):
    """The ``{ ... }`` text assigned to ``name`` in map-core.js."""
    start = source.index(name + " = {")
    brace = source.index("{", start)
    depth = 0
    for i in range(brace, len(source)):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[brace : i + 1]
    raise AssertionError(f"{name} has an unbalanced brace")


def _palette():
    body = re.sub(r"//[^\n]*", "", _object_literal(_map_core(), "OH2O.colors"))
    return dict(re.findall(r"([A-Za-z][A-Za-z0-9]*)\s*:\s*'(#[0-9a-fA-F]{6})'", body))


def _resolve(ref):
    """`OH2O.colors.x` (or `C.x`) to its hex value; a literal hex passes through."""
    ref = ref.strip().strip("'")
    if ref.startswith("#"):
        return ref
    key = ref.split(".")[-1]
    return _palette()[key]


def _oklch(hex_color):
    """OKLCH lightness and chroma of an sRGB hex colour (Bjorn Ottosson's OKLab)."""
    hex_color = hex_color.lstrip("#")
    rgb = [int(hex_color[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    r, g, b = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    lms = (
        0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b,
        0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b,
        0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b,
    )
    l_, m_, s_ = [v ** (1 / 3) for v in lms]
    lightness = 0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_
    a = 1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_
    bb = 0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_
    return lightness, math.hypot(a, bb)


# -- 1. Every record mark has a shape; no two kinds share hue and shape --------


class TestEveryPointLayerDrawsAShapedMark:
    def test_each_point_layer_is_a_symbol_naming_its_mark(self, client_in):
        layers = _layers_by_id(_rendered(client_in))
        for layer_id, kind in POINT_LAYERS.items():
            assert layer_id in layers, f"the Map page declares no {layer_id} layer"
            element = layers[layer_id]
            assert "type: 'symbol'" in element, f"{layer_id} is not a symbol layer"
            assert f"OH2O.markLayout('{kind}')" in element, (
                f"{layer_id} does not draw the {kind!r} mark"
            )

    def test_no_two_mark_kinds_share_both_hue_and_shape(self):
        marks = _object_literal(_map_core(), "OH2O.marks")
        entries = re.findall(
            r"(\w+):\s*\{\s*shape:\s*'(\w+)',\s*color:\s*([\w.']+)", marks
        )
        kinds = {kind for kind, _, _ in entries}
        assert set(POINT_LAYERS.values()) <= kinds, f"marks declared: {sorted(kinds)}"
        pairs = [(shape, _resolve(color).lower()) for _, shape, color in entries]
        assert len(pairs) == len(set(pairs)), f"two kinds share hue and shape: {entries}"
        shapes = [shape for _, shape, _ in entries]
        assert len(shapes) == len(set(shapes)), f"two kinds share a shape: {entries}"


# -- 2 and 3. Gold is a well; a station is never alarm red --------------------


class TestGoldIsAWellAndAStationIsNotRed:
    GOLD_REFS = ("OH2O.colors.gold", "OH2O.colors.boundary", "OH2O.colors.well")

    def test_no_layer_but_the_wells_paints_gold(self, client_in):
        for layer_id, element in _layers_by_id(_rendered(client_in)).items():
            if layer_id.startswith("wells-"):
                continue
            for ref in self.GOLD_REFS:
                assert ref not in element, f"{layer_id} paints gold ({ref})"

    def test_the_boundary_is_a_light_line_over_a_dark_casing(self, client_in):
        layers = _layers_by_id(_rendered(client_in))
        assert "OH2O.colors.frame" in layers["boundary-outline"]
        assert "OH2O.colors.frameCasing" in layers["boundary-casing"]

    def test_monitoring_stations_paint_no_red(self, client_in):
        element = _layers_by_id(_rendered(client_in))["stations-points"]
        assert "OH2O.colors.red" not in element
        station = re.search(r"station:\s*\{\s*shape:\s*'\w+',\s*color:\s*([\w.]+)",
                            _object_literal(_map_core(), "OH2O.marks")).group(1)
        assert _resolve(station).lower() != _palette()["red"].lower()


# -- 4. Areas are lines, never fills -----------------------------------------


class TestTheFrameIsLinesOnly:
    def test_no_zone_layer_is_a_fill(self, client_in):
        for layer_id, element in _layers_by_id(_rendered(client_in)).items():
            if "source: 'zones'" in element:
                assert "type: 'fill'" not in element, f"{layer_id} fills a zone"

    def test_management_areas_are_a_dashed_line(self, client_in):
        element = _layers_by_id(_rendered(client_in))["zones-outline"]
        assert "type: 'line'" in element
        assert "line-dasharray" in element
        assert "OH2O.colors.managementArea" in element


# -- 5. No always-on links -----------------------------------------------------


class TestSourcesShowTheirUseAreasOnlyWhenPicked:
    def test_no_layer_draws_the_links_when_the_page_opens(self, client_in):
        for layer_id, element in _layers_by_id(_rendered(client_in)).items():
            assert "source: 'tie-lines'" not in element, (
                f"{layer_id} draws the well and point-of-diversion links all the time"
            )

    def test_the_page_mounts_the_pick_to_reveal_links(self, client_in):
        assert "OH2O.mountSourceShares(" in _rendered(client_in)
        assert "OH2O.mountSourceShares = function" in _map_core()

    def test_a_picked_sources_popup_is_placed_beside_its_use_areas(self):
        """The popup goes beside the box holding the source and its use areas, not
        over them. Where it lands is measured in the browser at the checkpoint;
        what this pins is that the engine hands every popup to the placer."""
        engine = (ROOT / "static/js/map-engine.js").read_text()
        assert "OH2O.placePopup(map, _activePopup, layerId, props, coords)" in engine
        assert "OH2O.placePopup = function" in _map_core()

    def test_a_link_ends_inside_its_use_area_not_at_its_centroid(self, client_in):
        """A U-shaped use area's centroid lies in the notch, outside the land.

        The line from the well has to end on the use area itself, or the share
        beside its end is printed over a neighbour.
        """
        ring = [(0, 0), (0.03, 0), (0.03, 0.03), (0.02, 0.03), (0.02, 0.01),
                (0.01, 0.01), (0.01, 0.03), (0, 0.03), (0, 0)]
        u_shape = MultiPolygon(Polygon([(-120.5 + x, 37.3 + y) for x, y in ring]))
        assert not u_shape.contains(u_shape.centroid), "the fixture's centroid must fall outside"
        parcel = ParcelFactory(geometry=u_shape)
        WellIrrigatedParcelFactory(well=WellFactory(location=Point(-120.52, 37.29)), parcel=parcel)
        data = json.loads(client_in.get(reverse("geography:tie_lines_geojson")).content)
        line = next(f for f in data["features"] if f["properties"]["parcel_id"] == parcel.pk)
        end = Point(*line["geometry"]["coordinates"][-1], srid=4326)
        assert u_shape.contains(end), f"the link ends at {end.coords}, outside its use area"


# -- 6. Crop ET: darker is more, fixed breaks, a neutral no-figure ------------


class TestTheCropETConstants:
    def _crop_et(self):
        return _object_literal(_map_core(), "OH2O.cropET")

    def test_the_ramp_has_five_stops_each_darker_than_the_last(self):
        ramp = re.search(r"RAMP:\s*\[([^\]]+)\]", self._crop_et()).group(1)
        stops = [_resolve(s) for s in ramp.split(",") if s.strip()]
        assert len(stops) == 5, stops
        lightness = [_oklch(s)[0] for s in stops]
        assert all(a > b for a, b in zip(lightness, lightness[1:])), (
            f"the ramp must fall in lightness from least to most: {lightness}"
        )

    def test_the_breaks_are_fixed_per_period_kind(self):
        text = self._crop_et()
        month = re.search(r"month:\s*\[([^\]]+)\]", text).group(1)
        wy = re.search(r"wy:\s*\[([^\]]+)\]", text).group(1)
        assert [int(v) for v in month.split(",")] == [0, 2, 4, 6, 8, 10]
        assert [int(v) for v in wy.split(",")] == [0, 10, 20, 30, 40, 50]

    def test_no_figure_is_a_neutral_colour_not_a_ramp_stop(self):
        text = self._crop_et()
        no_figure = _resolve(re.search(r"NO_FIGURE:\s*([\w.#']+)", text).group(1))
        ramp = re.search(r"RAMP:\s*\[([^\]]+)\]", text).group(1)
        assert no_figure.lower() not in {_resolve(s).lower() for s in ramp.split(",")}
        assert _oklch(no_figure)[1] < 0.04, f"{no_figure} is not a neutral grey"


# -- 7. The role palette in both files ---------------------------------------


ROLE_NAMES = {
    "frame", "frameCasing", "managementArea", "serviceArea", "river", "canal",
    "useArea", "useAreaLine", "well", "pod", "drinking", "recharge", "station",
    "selection", "noFigure", "cropEt1", "cropEt2", "cropEt3", "cropEt4", "cropEt5",
}


class TestTheRolePaletteIsInBothFiles:
    def test_every_role_name_is_a_token_and_a_palette_key(self):
        css = re.sub(r"/\*.*?\*/", "", TOKENS_CSS.read_text(), flags=re.S)
        tokens = {
            re.sub(r"-([a-z0-9])", lambda m: m.group(1).upper(), name)
            for name in re.findall(r"--color-entity-([a-z0-9-]+)\s*:", css)
        }
        missing_tokens = ROLE_NAMES - tokens
        missing_js = ROLE_NAMES - set(_palette())
        assert not missing_tokens and not missing_js, (
            f"only in neither tokens.css: {sorted(missing_tokens)}; "
            f"not in OH2O.colors: {sorted(missing_js)}"
        )


# -- 8. What shows when the page opens ---------------------------------------


class TestTheOpeningSet:
    def test_exactly_service_areas_drinking_water_and_stations_start_off(self, client_in):
        layers = _layers_by_id(_rendered(client_in))
        off = {
            layer_id for layer_id, element in layers.items()
            if re.search(r"(?<![\w-])label:\s*'", element) and "visible: false" in element
        }
        assert off == {"service-areas-outline", "drinking-points", "stations-points"}

    def test_canals_draw_from_zoom_11(self, client_in):
        assert "minzoom: 11" in _layers_by_id(_rendered(client_in))["flowlines-canals"]


# -- 9. Popups lead with the map label; one boundary label per boundary ------


class TestNamesNotCodes:
    @pytest.mark.parametrize(
        "layer_id", ["pods-points", "recharge-points", "drinking-points", "stations-points"]
    )
    def test_the_popup_leads_with_the_map_label(self, client_in, layer_id):
        html = _rendered(client_in)
        popup = re.search(r"'%s':\s*function\s*\(p\)\s*\{(.*?)View details" % layer_id, html, re.S)
        assert popup, f"no popup for {layer_id}"
        assert re.search(r"'<strong>'\s*\+\s*\(p\.label\s*\|\|", popup.group(1)), (
            f"{layer_id}'s popup does not lead with the record's map label"
        )

    def test_the_shares_list_is_cut_at_five(self):
        assert re.search(r"OH2O\.SHARES_SHOWN\s*=\s*5\b", _map_core())

    def test_each_boundary_has_one_label_point_inside_it(self, client_in):
        boundary = BoundaryFactory(name="Halvern Subbasin")
        data = json.loads(client_in.get(reverse("geography:boundary_labels_geojson")).content)
        ours = [f for f in data["features"] if f["properties"]["name"] == "Halvern Subbasin"]
        assert len(ours) == 1, f"{len(ours)} label points for one boundary"
        assert ours[0]["geometry"]["type"] == "Point"
        assert boundary.geometry.contains(Point(*ours[0]["geometry"]["coordinates"], srid=4326))

    def test_the_boundary_label_reads_the_label_points(self, client_in):
        assert "makeLabelLayer('boundary-label', 'boundary-labels'" in _rendered(client_in)
