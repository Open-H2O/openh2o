# SPDX-License-Identifier: AGPL-3.0-or-later
"""The zone page composed as a page: a lead figure, a structured equation, a
footed use-areas table.

143-06 (R-101, R-103, R-055, R-112). Before this plan the zone page's
Allocation vs. use table printed Allocation, Carried forward, Used and
Remaining as one flat row of like figures, the equation hidden behind a "?"
popout; the Assigned use areas table gave neither a count nor an acreage
total; and Remaining, the figure the page exists to show, was one cell like
any other. The checkpoint ruling (rulings.md, 2026-09-12 14:08 PDT) is
"zone-lead as mocked, including the Available segment": a lead panel whose
only `.budget-seg--result` is Remaining for the current period, the table
below restructured so the group header says what adds (rule 2) instead of a
sentence behind a tooltip.

Every assertion below names the fixture's own literal value; none re-derives
the arithmetic (`zone_groundwater_budget` already has its own pinned tests in
`tests/test_zone_budget_shared.py`, unedited by this plan). This file reuses
that module's `mixed_zone` fixture rather than building a second one, so a
change to the shared arithmetic cannot quietly drift the two suites apart.
"""

import re
from decimal import Decimal

from tests.factories import ParcelFactory, ParcelZoneFactory, ZoneFactory
from tests.test_zone_budget_shared import (  # noqa: F401 (fixtures)
    EXPECTED_REMAINING,
    EXPECTED_SURFACE_REMAINING,
    mixed_zone,
    viewer,
)


def _result_segment_values(html):
    """Every `.budget-seg--result` panel's rendered figure, in document order."""
    return re.findall(
        r'<div class="budget-seg budget-seg--result">.*?'
        r'<div class="budget-seg-value[^"]*">\s*([\d,]+\.\d{2})',
        html,
        re.DOTALL,
    )


class TestZoneLeadPanel:
    """R-055: Remaining is the ONLY large figure on the page, once per row."""

    def test_one_result_segment_per_current_period_row_matching_remaining(
        self, viewer, mixed_zone
    ):
        zone = mixed_zone["zone"]
        response = viewer.get(f"/map/zones/{zone.pk}/")
        assert response.status_code == 200
        html = response.content.decode()

        segments = _result_segment_values(html)
        # One row for groundwater, one for surface, the mixed zone's two
        # current-period budgets, never summed into one panel (ISS-155). Each
        # expected figure is the shared fixture's own pasted literal
        # (`tests/test_zone_budget_shared.py`), never re-derived here.
        assert len(segments) == 2
        assert set(segments) == {
            f"{EXPECTED_REMAINING:,.2f}",
            f"{EXPECTED_SURFACE_REMAINING:,.2f}",
        }


class TestZoneTableStructure:
    """R-101: the equation is said by structure, not a '?' popout."""

    def test_available_group_header_spans_allocation_and_carried_forward(
        self, viewer, mixed_zone
    ):
        zone = mixed_zone["zone"]
        response = viewer.get(f"/map/zones/{zone.pk}/")
        assert response.status_code == 200
        html = response.content.decode()

        assert '<th colspan="2" class="th-group-label">Available</th>' in html

    def test_no_popout_markup_in_the_table(self, viewer, mixed_zone):
        zone = mixed_zone["zone"]
        response = viewer.get(f"/map/zones/{zone.pk}/")
        assert response.status_code == 200
        html = response.content.decode()

        # The old header's "?" popout (`partials/_explainer_popout.html`) rendered
        # a `class="explainer-icon"` button inside a `class="explainer-popout"`
        # span. Matched by the class ATTRIBUTE, not the bare substring: every
        # page also loads `/static/js/explainer-popout.<hash>.js` in its head
        # (base.html, unconditionally), so a plain substring search would find
        # that script tag on every page, popout or not, and never go red.
        assert 'class="explainer-popout"' not in html
        assert 'class="explainer-icon"' not in html


class TestZoneUseAreasFooter:
    """R-103: a count and an acreage total under the Assigned use areas table."""

    def test_three_parcels_one_missing_an_area_render_the_ruled_wording(self, viewer):
        zone = ZoneFactory(name="Use-Area Footer Test Zone")
        p1 = ParcelFactory(area_acres=Decimal("10.00"))
        p2 = ParcelFactory(area_acres=Decimal("20.50"))
        # area_override=True as well: parcels/signals.py auto-computes area_acres
        # from the factory's own placeholder geometry whenever it is saved None
        # WITHOUT the override, which would silently give this parcel a real
        # acreage instead of the "no area on record" case R-103 is about.
        p3 = ParcelFactory(area_acres=None, area_override=True)
        for p in (p1, p2, p3):
            ParcelZoneFactory(parcel=p, zone=zone)

        response = viewer.get(f"/map/zones/{zone.pk}/")
        assert response.status_code == 200
        html = response.content.decode()

        assert "All 3 use areas" in html
        assert "2 of 3 with an area on record" in html
        assert "30.50" in html

    def test_a_zone_with_no_use_areas_gets_no_footer(self, viewer):
        zone = ZoneFactory(name="Empty Use-Area Zone")
        response = viewer.get(f"/map/zones/{zone.pk}/")
        assert response.status_code == 200
        html = response.content.decode()

        assert "No parcels assigned to this zone." in html
        assert "tfoot-total" not in html


class TestZoneUseAreasOnTheMap:
    """R-102 (143-07): the zone page's own map drew the outline and none of
    the use areas the table beneath it names. `zone_detail`'s view now adds
    `parcels_geojson` (the zone's assigned parcels, beneath `zone-fill`), and
    fixes the six-times label the same map showed for a multi-part GSA
    (`label_point`, one interior point per zone rather than a symbol layer
    stamping the polygon source once per part).
    """

    def test_two_assigned_parcels_render_with_parcel_number_and_pk(self, viewer):
        import json
        import re

        zone = ZoneFactory(name="Parcels-On-Map Zone")
        p1 = ParcelFactory(parcel_number="APN-100001")
        p2 = ParcelFactory(parcel_number="APN-100002")
        ParcelZoneFactory(parcel=p1, zone=zone)
        ParcelZoneFactory(parcel=p2, zone=zone)

        response = viewer.get(f"/map/zones/{zone.pk}/")
        assert response.status_code == 200
        html = response.content.decode()

        match = re.search(
            r'<script[^>]*id="detail-parcels-geojson-data"[^>]*>(.*?)</script>',
            html,
            re.DOTALL,
        )
        assert match, "detail-parcels-geojson-data is not on the page"
        data = json.loads(match.group(1))
        assert len(data["features"]) == 2
        numbers = {f["properties"]["parcel_number"] for f in data["features"]}
        assert numbers == {"APN-100001", "APN-100002"}
        for f in data["features"]:
            assert "pk" in f["properties"]

    def test_with_none_assigned_the_parcels_element_is_absent(self, viewer):
        zone = ZoneFactory(name="No Parcels On Map Zone")
        response = viewer.get(f"/map/zones/{zone.pk}/")
        assert response.status_code == 200
        html = response.content.decode()

        assert 'id="detail-parcels-geojson-data"' not in html

    def test_the_zone_geojson_carries_one_label_point_for_the_whole_zone(
        self, viewer
    ):
        import json
        import re

        zone = ZoneFactory(name="Label Point Zone")
        response = viewer.get(f"/map/zones/{zone.pk}/")
        assert response.status_code == 200
        html = response.content.decode()

        match = re.search(
            r'<script[^>]*id="detail-geojson-data"[^>]*>(.*?)</script>',
            html,
            re.DOTALL,
        )
        assert match, "detail-geojson-data is not on the page"
        data = json.loads(match.group(1))
        assert len(data["features"]) == 1
        assert "label_point" in data["features"][0]["properties"], (
            "the zone's own detail map has nothing to draw a single label from"
        )
        lng, lat = data["features"][0]["properties"]["label_point"]
        assert isinstance(lng, float) and isinstance(lat, float)
