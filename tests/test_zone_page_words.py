# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Zone page's approved words (150.1-02).

Two of the approved rows are structure, not a sentence a template holds, so they
are pinned here: the groundwater panel's "Available by source" names what its
carry-over sum is made of, by kind, instead of calling all of it "Carried
forward" (on the demonstration it was all managed recharge and canal seepage);
and the pointer to the Dashboard's zone row is printed under a groundwater
result only, because the Dashboard dashes a surface allocation's remaining.
"""

from decimal import Decimal

from accounting.models import AllocationCarryover, WaterType
from tests.test_zone_budget_shared import (  # noqa: F401 (fixtures)
    WATER_YEAR,
    mixed_zone,
    viewer,
)

POINTER = "zone row prints this same figure."
SEEPAGE = Decimal("12.5000")


def test_available_by_source_names_each_kind(viewer, mixed_zone):
    zone = mixed_zone["zone"]
    AllocationCarryover.objects.create(
        zone=zone,
        water_type=WaterType.objects.get(code="GW"),
        water_year=WATER_YEAR,
        amount_af=SEEPAGE,
        origin="conveyance_seepage_pool",
    )
    html = viewer.get(f"/map/zones/{zone.pk}/").content.decode()

    assert "<span>Canal seepage</span><b>+12.50</b>" in html
    assert "<span>Carried forward</span>" in html
    assert "Managed recharge" not in html


def test_dashboard_pointer_sits_under_groundwater_only(viewer, mixed_zone):
    zone = mixed_zone["zone"]
    html = viewer.get(f"/map/zones/{zone.pk}/").content.decode()

    # The mixed zone has a groundwater and a surface result; one pointer.
    assert html.count(POINTER) == 1
