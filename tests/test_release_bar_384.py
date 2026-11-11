# SPDX-License-Identifier: AGPL-3.0-or-later
"""The production year table counts every record saved for a month and a source.

The add-month form offers a facility on each record and refuses a second record only for the
same facility, so two wells' groundwater for one month can both be saved. The year table and
the year's total must then read what was saved: 100 and 250 gallons make 350.
"""

from decimal import Decimal as D

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from drinking.models import SystemProduction
from drinking.views.production import _production_table_context
from tests.factories import SystemFacilityFactory, WaterSystemFactory

pytestmark = pytest.mark.django_db


def test_two_wells_in_one_month_both_count_in_the_year():
    user = get_user_model().objects.create_user(
        username="operator", email="operator@example.org", password="a-good-passw0rd",
        is_active=True,
    )
    client = Client()
    client.force_login(user)
    system = WaterSystemFactory()
    for name, facility_id, gallons in (("Well 7 (invented)", "007", "100"), ("Well 8 (invented)", "008", "250")):
        well = SystemFacilityFactory(system=system, name=name, facility_id=facility_id)
        response = client.post(reverse("drinking:production_add"), {
            "year": 2025, "month": 3, "type_code": "GW", "facility": well.pk,
            "volume_as_reported": gallons, "unit_as_reported": "G", "notes": "",
        })
        assert response.status_code == 302
    assert SystemProduction.objects.current().filter(system=system, month=3).count() == 2

    context = _production_table_context(system, 2025)

    groundwater = next(t for t in context["totals"] if t["type_code"] == "GW")
    assert (groundwater["gallons"], context["grand_total_gallons"]) == (D("350"), D("350"))


def _signed_in_client():
    user = get_user_model().objects.create_user(
        username="operator2", email="operator2@example.org", password="a-good-passw0rd",
        is_active=True,
    )
    client = Client()
    client.force_login(user)
    return client


def _save(system, well, gallons, *, month=3, type_code="GW", unit="G"):
    return SystemProduction.objects.create(
        system=system, year=2025, month=month, type_code=type_code, facility=well,
        volume_as_reported=D(gallons), unit_as_reported=unit,
    )


def _add_form(client, *, facility, gallons="10", type_code="GW"):
    return client.post(reverse("drinking:production_add"), {
        "year": 2025, "month": 3, "type_code": type_code,
        "facility": facility.pk if facility else "",
        "volume_as_reported": gallons, "unit_as_reported": "G", "notes": "",
    })


def test_month_cell_shows_the_sum_and_each_facility_is_listed_with_its_own_menu():
    client = _signed_in_client()
    system = WaterSystemFactory()
    well7 = SystemFacilityFactory(system=system, name="Well 7", facility_id="007")
    well8 = SystemFacilityFactory(system=system, name="Well 8", facility_id="008")
    first = _save(system, well7, "100")
    second = _save(system, well8, "250")

    html = client.get(reverse("drinking:production"), {"year": 2025}).content.decode()

    assert "350 gal" in html and "from 2 facilities" in html
    assert html.count('class="row-listed"') + html.count('class="row-listed row-listed-shaded"') == 2
    for record, name in ((first, "Well 7"), (second, "Well 8")):
        assert f'aria-label="Actions for the March 2025 groundwater record, {name}"' in html
        assert f'id="record-production_record-{record.pk}"' in html
    assert ">Well 7<" in html and ">Well 8<" in html
    assert "100 gal" in html and "250 gal" in html
    # The sum is not a record: it has no menu of its own.
    assert 'aria-label="Actions for the March 2025 groundwater record"' not in html


def test_a_record_with_no_facility_in_a_listed_month_is_named_whole_system():
    client = _signed_in_client()
    system = WaterSystemFactory()
    well7 = SystemFacilityFactory(system=system, name="Well 7", facility_id="007")
    _save(system, well7, "100")
    _save(system, None, "250")

    html = client.get(reverse("drinking:production"), {"year": 2025}).content.decode()

    assert "350 gal" in html and "from 2 records" in html
    assert ">Whole system<" in html


def test_a_month_with_one_record_is_unchanged():
    client = _signed_in_client()
    system = WaterSystemFactory()
    well7 = SystemFacilityFactory(system=system, name="Well 7", facility_id="007")
    record = _save(system, well7, "100")

    html = client.get(reverse("drinking:production"), {"year": 2025}).content.decode()

    assert "100 gal" in html and "from 1" not in html and "row-listed" not in html.split("<style")[-1].split("<table")[-1]
    assert f'id="record-production_record-{record.pk}"' in html
    assert 'aria-label="Actions for the March 2025 groundwater record"' in html


def test_a_whole_system_figure_is_refused_beside_facility_figures():
    client = _signed_in_client()
    system = WaterSystemFactory()
    _save(system, SystemFacilityFactory(system=system, name="Well 7", facility_id="007"), "100")
    _save(system, SystemFacilityFactory(system=system, name="Well 8", facility_id="008"), "250")

    response = _add_form(client, facility=None)

    assert response.status_code == 200
    assert (
        "Figures for Groundwater in March 2025 are already on file for Well 7 and Well 8. "
        "A figure for the whole system beside them would count the same water twice. "
        "Choose its facility, or void those figures, first."
    ) in response.content.decode().replace("&#x27;", "'")
    assert SystemProduction.objects.current().filter(system=system, facility__isnull=True).count() == 0


def test_a_facility_figure_is_refused_beside_a_whole_system_figure():
    client = _signed_in_client()
    system = WaterSystemFactory()
    _save(system, None, "100")
    well = SystemFacilityFactory(system=system, name="Well 7", facility_id="007")

    response = _add_form(client, facility=well)

    assert response.status_code == 200
    assert (
        "A figure for the whole system for Groundwater in March 2025 is already on file. "
        "A facility's figure beside it would count the same water twice. "
        "Correct that figure to name its facility, or void it, first."
    ) in response.content.decode().replace("&#x27;", "'")
    assert SystemProduction.objects.current().filter(system=system).count() == 1


def test_a_file_figure_is_refused_where_facility_figures_are_on_file():
    from drinking.production_import import import_production_rows

    system = WaterSystemFactory()
    _save(system, SystemFacilityFactory(system=system, name="Well 7", facility_id="007"), "100")
    _save(system, SystemFacilityFactory(system=system, name="Well 8", facility_id="008"), "250")
    columns = ["PWSID", "Year", "Month", "TypeCode", "Quantity as in Units Reported", "Units of Measure As Reported"]
    rows = [{
        "PWSID": system.pwsid, "Year": "2025", "Month": "March", "TypeCode": "GW",
        "Quantity as in Units Reported": "999", "Units of Measure As Reported": "G",
    }]
    message = (
        "Groundwater for March 2025 is already on file by facility (Well 7, Well 8). "
        "A figure from a file is for the whole system, so this one was not saved: "
        "it would count the same water twice."
    )

    for dry_run in (True, False):
        result = import_production_rows(columns, rows, system=system, layout="ear", dry_run=dry_run)
        assert [e["message"] for e in result["errors"]] == [message]
        assert result["created"] == 0
    assert SystemProduction.objects.current().filter(system=system).count() == 2
