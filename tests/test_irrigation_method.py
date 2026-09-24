# SPDX-License-Identifier: AGPL-3.0-or-later
"""
146-05 Task 1 (S1): the irrigation-method table, seeded, and the method on
every use area.

Proven here, each RED against the unfixed tree (quotes in 146-05-EVIDENCE.md):

  1. The data migration seeds East Turlock Subbasin GSA's Section 4.05 table
     exactly: 18 rows, counted off the PDF on 2026-09-23, names as the PDF
     prints them, in its order, every row carrying the same source line.
  2. The use-area page's inline editor offers the methods labelled
     "<name>, <n>%", sets one, clears it, and refuses a method that does not
     exist.
  3. The use-area page shows the row while `surface` is enabled and not at all
     on the shape-4 configuration (`parcels` on, `surface` off), where the
     editor also refuses the field. ``override_settings`` cannot uninstall
     `surface` mid-run (its table stays), but it does change what
     ``core.modules.is_enabled`` returns, which is the boolean the view
     branches on; the subprocess harness in ``tests/droppability/`` covers
     the truly-uninstalled case. Same reasoning as
     ``tests/test_delivery_settings_surface_fields.py``.
  4. 148-02 wires the method into the engine: ``allocate_district_delivery``
     caps each served parcel at ITS OWN ``surface.services.field_efficiency``
     (the method's assigned efficiency, or the agency-wide ``SiteConfig``
     default with no method set), and ``subtract_surface_water`` consumes the
     same per-parcel figure when its ``apply_efficiency`` knob is on. A
     mixed-method headgate's two parcels get different caps and different
     consumed parts from the same delivery.

The method lives on a `surface` row (``ParcelIrrigationMethod``), not a
``Parcel`` column: `parcels` stays installed when `surface` is dropped, and a
column there pointing into `surface` would break `migrate` on every
deployment without it (the composition rule, ``core/modules.py``).

Models are imported inside each test, so a missing model fails that test
alone rather than the whole file at collection.
"""
from datetime import date
from decimal import Decimal

import factory
import pytest
from django.contrib.auth.hashers import make_password
from django.test import Client, override_settings
from django.urls import reverse
from django.utils.http import urlencode

from accounting.models import CalculationRun
from accounting.steps import STEP_REGISTRY
from core.models import SiteConfig
from parcels.models import ParcelLedger
from tests.factories import (
    DiversionRecordFactory,
    ParcelFactory,
    PointOfDiversionFactory,
    PointOfDiversionParcelFactory,
    ReportingPeriodFactory,
)

pytestmark = pytest.mark.django_db

#: The shape-4 module list (145-02-EVIDENCE.md's per-shape table): use areas,
#: accounts and wells, no surface water.
_SHAPE_4 = (
    "core", "geography", "measurements", "standards", "parcels", "accounting",
    "wells", "datasync", "setup", "infrastructure", "health", "feedback",
)

#: East Turlock Subbasin GSA, Rules and Regulations Phase 2 Final (2025-08-28),
#: Section 4.05, printed pages 20-21: (name as printed, range low %, range
#: high %, assigned %), in the PDF's order.
EAST_TURLOCK_4_05 = [
    ("LEPA", 80, 90, 88),
    ("Linear Move", 75, 85, 83),
    ("Center Pivot", 75, 90, 87),
    ("Traveling Gun", 65, 75, 73),
    ("Side-Roll", 65, 85, 80),
    ("Hand-Move", 65, 85, 80),
    ("Solid-Set", 70, 85, 82),
    ("Furrow (Conventional)", 45, 65, 60),
    ("Furrow (Surge)", 55, 75, 70),
    ("Furrow (with Tailwater Reuse)", 60, 80, 75),
    ("Basin", 60, 75, 72),
    ("Precision Level Basin", 65, 80, 77),
    ("Bubbler (Low Head)", 80, 90, 88),
    ("Microspray", 85, 90, 90),
    ("Micropoint Source", 85, 90, 90),
    ("Microline Source", 85, 90, 90),
    ("Surface Drip", 85, 95, 93),
    ("Subsurface Drip", 90, 95, 95),
]

SOURCE = (
    "East Turlock Subbasin GSA, Rules and Regulations Phase 2 Final "
    "(2025-08-28), §4.05, citing Zaccaria 2018, ANR 8570"
)


class _UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"irrigationuser{n}")
    email = factory.Sequence(lambda n: f"irrigationuser{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True


@pytest.fixture
def auth_client():
    c = Client()
    c.force_login(_UserFactory())
    return c


def _method(name):
    from surface.models import IrrigationMethod

    return IrrigationMethod.objects.get(name=name)


def _link_for(parcel):
    from surface.models import ParcelIrrigationMethod

    return ParcelIrrigationMethod.objects.filter(parcel=parcel).first()


def _patch(client, parcel, value):
    """PATCH the inline editor the way the HTMX form does (urlencoded body)."""
    body = urlencode({"field": "irrigation_method", "value": value})
    return client.patch(
        reverse("parcels:edit_field", args=[parcel.pk]),
        data=body,
        content_type="application/x-www-form-urlencoded",
    )


# ---------------------------------------------------------------------------
# 1. The seeded table
# ---------------------------------------------------------------------------


def test_the_migration_seeds_east_turlocks_eighteen_rows_in_order():
    from surface.models import IrrigationMethod

    rows = list(IrrigationMethod.objects.order_by("sort_order"))
    assert len(rows) == 18
    assert [
        (
            r.name,
            int(r.range_low * 100),
            int(r.range_high * 100),
            int(r.assigned_efficiency * 100),
        )
        for r in rows
    ] == EAST_TURLOCK_4_05


def test_every_seeded_row_names_its_source():
    from surface.models import IrrigationMethod

    assert set(IrrigationMethod.objects.values_list("source", flat=True)) == {SOURCE}


def test_efficiencies_are_stored_as_fractions():
    furrow = _method("Furrow (Conventional)")
    assert furrow.assigned_efficiency == Decimal("0.600")
    assert furrow.range_low == Decimal("0.450")
    assert furrow.range_high == Decimal("0.650")
    assert str(furrow) == "Furrow (Conventional), 60%"


# ---------------------------------------------------------------------------
# 2. The inline editor on the use-area page
# ---------------------------------------------------------------------------


def test_editor_offers_every_method_labelled_name_and_percent(auth_client):
    parcel = ParcelFactory()
    resp = auth_client.get(
        reverse("parcels:edit_field", args=[parcel.pk]),
        {"field": "irrigation_method"},
    )
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Furrow (Conventional), 60%" in body
    assert "Subsurface Drip, 95%" in body
    assert body.count("<option") == 19  # "Not set" plus the 18 methods


def test_editor_sets_the_method(auth_client):
    parcel = ParcelFactory()
    furrow = _method("Furrow (Conventional)")

    resp = _patch(auth_client, parcel, str(furrow.pk))

    assert resp.status_code == 200
    assert "Furrow (Conventional), 60%" in resp.content.decode()
    assert _link_for(parcel).method == furrow


def test_editor_changes_then_clears_the_method(auth_client):
    parcel = ParcelFactory()
    _patch(auth_client, parcel, str(_method("Basin").pk))
    _patch(auth_client, parcel, str(_method("Surface Drip").pk))
    assert _link_for(parcel).method.name == "Surface Drip"

    resp = _patch(auth_client, parcel, "")

    assert resp.status_code == 200
    assert _link_for(parcel) is None
    assert "Not recorded" in resp.content.decode()


def test_editor_refuses_a_method_that_does_not_exist(auth_client):
    parcel = ParcelFactory()
    resp = _patch(auth_client, parcel, "999999")
    assert resp.status_code == 400
    assert _link_for(parcel) is None


def test_use_area_page_shows_the_method_when_set(auth_client):
    parcel = ParcelFactory()
    _patch(auth_client, parcel, str(_method("Furrow (Conventional)").pk))

    body = auth_client.get(reverse("parcels:detail", args=[parcel.pk])).content.decode()

    assert "Irrigation method" in body
    assert "Furrow (Conventional), 60%" in body
    assert 'id="field-irrigation_method"' in body


# ---------------------------------------------------------------------------
# 3. Shape 4: `parcels` on, `surface` off
# ---------------------------------------------------------------------------


@override_settings(OPENH2O_MODULES=_SHAPE_4)
def test_shape_4_use_area_page_renders_without_the_row(auth_client):
    parcel = ParcelFactory()
    resp = auth_client.get(reverse("parcels:detail", args=[parcel.pk]))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Irrigation method" not in body
    assert "field-irrigation_method" not in body
    # The page's own editable fields are unaffected.
    assert 'id="field-owner_name"' in body


@override_settings(OPENH2O_MODULES=_SHAPE_4)
def test_shape_4_editor_refuses_the_field(auth_client):
    parcel = ParcelFactory()
    get = auth_client.get(
        reverse("parcels:edit_field", args=[parcel.pk]),
        {"field": "irrigation_method"},
    )
    assert get.status_code == 400
    assert _patch(auth_client, parcel, "1").status_code == 400
    assert _link_for(parcel) is None


# ---------------------------------------------------------------------------
# 4. The engine reads the method (148-02, S1)
# ---------------------------------------------------------------------------


def test_the_engine_now_caps_by_the_parcels_own_method(auth_client):
    """148-02 retargets 146-05's placeholder: a 95% method on the only served
    use area NOW moves the cap, to demand / the method's own efficiency
    (30 / 0.95 = 31.5789), not demand / the agency-wide default (30 / 0.750 =
    40) -- the opposite of what this test proved before Phase 148."""
    SiteConfig.objects.create(agency_name="Test GSA")  # default efficiency 0.750
    rp = ReportingPeriodFactory()
    parcel = ParcelFactory(parcel_number="APN-DRIP")
    pod = PointOfDiversionFactory()
    PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=parcel)
    CalculationRun.objects.create(
        parcel=parcel, period="2024-01",
        gross_et_af=Decimal("30"), net_consumptive_use_af=Decimal("30"),
        final_af=Decimal("0"),
    )
    DiversionRecordFactory(
        point_of_diversion=pod, reporting_period=rp, month=date(2024, 1, 1),
        volume_acre_feet=Decimal("100"),  # ample
    )
    _patch(auth_client, parcel, str(_method("Subsurface Drip").pk))
    assert _link_for(parcel).method.assigned_efficiency == Decimal("0.950")

    from surface.services import allocate_district_delivery

    rows = allocate_district_delivery(pod, rp, dry_run=True)

    assert [r.amount_acre_feet for r in rows] == [Decimal("-31.5789")]


def test_pivot_and_no_method_fields_on_one_headgate_get_different_caps(auth_client):
    """A center-pivot field (method, 0.87) and a no-method field (agency
    default, 0.75) sharing ONE point of diversion get their OWN caps on an
    ample delivery -- not one shared cap (the 146-05 carry: a mixed-method
    headgate must not let one parcel's method decide another's water)."""
    SiteConfig.objects.create(agency_name="Test GSA")  # default efficiency 0.750
    rp = ReportingPeriodFactory()
    pod = PointOfDiversionFactory()
    pivot = ParcelFactory(parcel_number="APN-PIVOT")
    plain = ParcelFactory(parcel_number="APN-PLAIN")
    PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=pivot)
    PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=plain)
    for parcel in (pivot, plain):
        CalculationRun.objects.create(
            parcel=parcel, period="2024-01",
            gross_et_af=Decimal("30"), net_consumptive_use_af=Decimal("30"),
            final_af=Decimal("0"),
        )
    DiversionRecordFactory(
        point_of_diversion=pod, reporting_period=rp, month=date(2024, 1, 1),
        volume_acre_feet=Decimal("100"),  # ample: covers both caps (34.4828 + 40)
    )
    _patch(auth_client, pivot, str(_method("Center Pivot").pk))

    from surface.services import allocate_district_delivery

    rows = allocate_district_delivery(pod, rp, dry_run=True)
    by_parcel = {r.parcel: r.amount_acre_feet for r in rows}

    assert by_parcel[pivot] == Decimal("-34.4828")  # 30 / 0.87 (method)
    assert by_parcel[plain] == Decimal("-40.0000")  # 30 / 0.75 (agency default)


def test_pivot_and_no_method_fields_consume_different_parts_of_equal_delivery(
    auth_client,
):
    """148-02: the SAME 25 AF delivered to each field is subtracted
    differently by ``subtract_surface_water`` -- consumed = delivered x each
    parcel's OWN field_efficiency, so equal delivery does not mean equal
    consumption."""
    SiteConfig.objects.create(agency_name="Test GSA")  # default efficiency 0.750
    pivot = ParcelFactory(parcel_number="APN-PIVOT-2")
    plain = ParcelFactory(parcel_number="APN-PLAIN-2")
    _patch(auth_client, pivot, str(_method("Center Pivot").pk))

    for parcel in (pivot, plain):
        ParcelLedger.objects.create(
            parcel=parcel,
            transaction_date=date(2024, 6, 1),
            effective_date=date(2024, 6, 1),
            amount_acre_feet=Decimal("-25"),  # same 25 AF delivered to both
            source_type="surface_diversion",
        )

    fn = STEP_REGISTRY["subtract_surface_water"]
    _, pivot_record = fn(
        Decimal("0"), pivot, "2024-06", {}, {"apply_efficiency": True}
    )
    _, plain_record = fn(
        Decimal("0"), plain, "2024-06", {}, {"apply_efficiency": True}
    )

    assert pivot_record["detail"]["efficiency"] == "0.870"
    assert pivot_record["detail"]["efficiency_source"] == "method"
    assert pivot_record["detail"]["consumed_af"] == "21.7500"

    assert plain_record["detail"]["efficiency"] == "0.750"
    assert plain_record["detail"]["efficiency_source"] == "agency"
    assert plain_record["detail"]["consumed_af"] == "18.7500"


def test_knob_off_reproduces_todays_numbers_exactly_even_with_a_method_set(
    auth_client,
):
    """apply_efficiency missing (an old plan's posture) subtracts the whole
    delivered magnitude, unchanged by a method being set on the parcel -- the
    method only matters once the knob is on."""
    parcel = ParcelFactory(parcel_number="APN-PIVOT-3")
    _patch(auth_client, parcel, str(_method("Center Pivot").pk))
    ParcelLedger.objects.create(
        parcel=parcel,
        transaction_date=date(2024, 6, 1),
        effective_date=date(2024, 6, 1),
        amount_acre_feet=Decimal("-25"),
        source_type="surface_diversion",
    )

    fn = STEP_REGISTRY["subtract_surface_water"]
    new_running, record = fn(Decimal("30"), parcel, "2024-06", {}, {})

    assert new_running == Decimal("5")
    assert set(record["detail"]) == {"surface_water_af"}
    assert Decimal(record["detail"]["surface_water_af"]) == Decimal("25")
