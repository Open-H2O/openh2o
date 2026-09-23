# SPDX-License-Identifier: AGPL-3.0-or-later
"""
146-04 Task 4 (D8): the sampling schedule.

The operator's own checklist of what is sampled and when. Brent's "the plan
holds" (2026-09-20 19:06 PDT) answered the memo's J11 ("whether the product
should hold a schedule at all"): it does, and it HOLDS it. Nothing here
computes a due date, and nothing calls a row overdue; a row whose date has
passed says "past the date you set", because the date is the operator's.

What is pinned here:

* a row is created through the form and lands on the list;
* the list is ordered by the date the operator set, earliest first, rows
  with no date last, and a passed date is worded as the operator's date;
* the overview carries one "next due" line when a dated row exists and
  nothing when none does;
* the pages render on the shape-2 module set;
* no due date is ever computed from a frequency.
"""
import re
from datetime import date, timedelta

import factory
import pytest
from django.contrib.auth.hashers import make_password
from django.core.management import call_command
from django.test import Client
from django.urls import reverse

from drinking.models import Analyte, SamplingSchedule, WaterSystem
from tests.factories import (
    SamplingPointFactory,
    SystemFacilityFactory,
    WaterSystemFactory,
)
from tests.test_facility_door import SHAPE_2
from tests.test_module_prose import compose_urlconf_under_the_full_module_set


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"schedule{n}")
    email = factory.Sequence(lambda n: f"schedule{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True


@pytest.fixture
def client_in(db):
    client = Client()
    client.force_login(UserFactory())
    return client


@pytest.fixture
def system(db):
    """Le Grand, and only Le Grand.

    The views read the deployment's one system (lowest PWSID), and
    ``tests/test_merced_drinking_seed.py`` seeds City of Merced (CA2410009)
    outside any test transaction, where it outlives its module. Cleared here
    the way ``tests/test_production_import.py`` clears it.
    """
    WaterSystem.objects.all().delete()
    return WaterSystemFactory(pwsid="CA2410011", name="LE GRAND CSD")


@pytest.fixture
def shape_2(settings):
    compose_urlconf_under_the_full_module_set()
    settings.OPENH2O_MODULES = SHAPE_2


def _row(system, **kwargs):
    defaults = {"frequency": "monthly", "group_label": "Coliform"}
    defaults.update(kwargs)
    return SamplingSchedule.objects.create(system=system, **defaults)


class TestCreate:
    def test_a_monthly_coliform_row_is_added_through_the_form(
        self, client_in, system
    ):
        response = client_in.post(reverse("drinking:schedule_add"), {
            "group_label": "Coliform",
            "frequency": "monthly",
            "last_done": "2026-09-02",
            "next_due": "2026-10-07",
            "notes": "Two routine samples, LCR tap and DBPR site.",
        })
        assert response.status_code == 302
        assert response.url == reverse("drinking:schedule")
        row = SamplingSchedule.objects.get()
        assert row.system == system
        assert row.group_label == "Coliform"
        assert row.next_due == date(2026, 10, 7)
        html = client_in.get(reverse("drinking:schedule")).content.decode()
        assert "Coliform" in html
        assert "Monthly" in html

    def test_a_row_can_name_an_analyte_and_a_sampling_point(
        self, client_in, system
    ):
        call_command("seed_drinking", verbosity=0)
        nitrate = Analyte.objects.filter(name__icontains="nitrate").first()
        facility = SystemFacilityFactory(system=system, facility_id="002")
        point = SamplingPointFactory(ps_code="CA2410011_002_002", facility=facility)
        client_in.post(reverse("drinking:schedule_add"), {
            "analyte": nitrate.pk,
            "sampling_point": point.pk,
            "frequency": "annual",
        })
        row = SamplingSchedule.objects.get()
        assert row.analyte == nitrate
        assert row.sampling_point == point
        assert nitrate.name in client_in.get(reverse("drinking:schedule")).content.decode()

    def test_a_row_naming_nothing_is_refused(self, client_in, system):
        response = client_in.post(reverse("drinking:schedule_add"), {
            "frequency": "monthly",
        })
        assert response.status_code == 200
        assert not SamplingSchedule.objects.exists()

    def test_editing_a_row_keeps_it_one_row(self, client_in, system):
        row = _row(system, next_due=date(2026, 10, 7))
        client_in.post(reverse("drinking:schedule_edit", args=[row.pk]), {
            "group_label": "Coliform",
            "frequency": "monthly",
            "last_done": "2026-10-06",
            "next_due": "2026-11-04",
        })
        assert SamplingSchedule.objects.count() == 1
        row.refresh_from_db()
        assert row.next_due == date(2026, 11, 4)

    def test_no_system_yet_says_onboard_first(self, client_in, db):
        WaterSystem.objects.all().delete()  # see the `system` fixture
        html = client_in.get(reverse("drinking:schedule_add")).content.decode()
        assert reverse("drinking:onboard") in html
        assert 'name="frequency"' not in html


class TestNothingIsComputed:
    def test_saving_a_frequency_and_a_last_date_computes_no_due_date(
        self, client_in, system
    ):
        client_in.post(reverse("drinking:schedule_add"), {
            "group_label": "Nitrate",
            "frequency": "annual",
            "last_done": "2026-03-10",
        })
        assert SamplingSchedule.objects.get().next_due is None


class TestTheList:
    def test_rows_run_by_the_date_set_earliest_first_and_undated_last(
        self, client_in, system
    ):
        today = date.today()
        _row(system, group_label="Undated siting plan", next_due=None)
        _row(system, group_label="Later nitrate", next_due=today + timedelta(days=60))
        _row(system, group_label="Passed coliform", next_due=today - timedelta(days=3))
        _row(system, group_label="Soon chlorine residual", next_due=today + timedelta(days=5))
        html = client_in.get(reverse("drinking:schedule")).content.decode()
        order = [
            html.index(label)
            for label in (
                "Passed coliform", "Soon chlorine residual",
                "Later nitrate", "Undated siting plan",
            )
        ]
        assert order == sorted(order)

    def test_a_passed_date_is_worded_as_the_operators_and_never_as_a_verdict(
        self, client_in, system
    ):
        _row(system, next_due=date.today() - timedelta(days=3))
        html = client_in.get(reverse("drinking:schedule")).content.decode()
        assert "past the date you set" in html
        lowered = html.lower()
        for word in ("overdue", "late", "violation", "missed"):
            assert not re.search(rf"\b{word}\b", lowered), word

    def test_the_empty_list_offers_the_add(self, client_in, system):
        html = client_in.get(reverse("drinking:schedule")).content.decode()
        assert reverse("drinking:schedule_add") in html


class TestTheOverviewLine:
    def test_one_dated_row_puts_one_next_due_line_on_the_overview(
        self, client_in, system
    ):
        _row(system, group_label="Coliform", next_due=date(2026, 10, 7))
        _row(system, group_label="Nitrate", next_due=date(2027, 3, 10))
        html = client_in.get(reverse("drinking:overview")).content.decode()
        assert html.count("Next due:") == 1
        assert "Coliform on October 7, 2026" in html
        assert "Nitrate on" not in html

    def test_no_row_puts_nothing_on_the_overview(self, client_in, system):
        html = client_in.get(reverse("drinking:overview")).content.decode()
        assert "Next due" not in html


class TestShape2:
    def test_the_schedule_pages_render_without_wells_parcels_or_accounting(
        self, shape_2, client_in, system
    ):
        _row(system, next_due=date(2026, 10, 7))
        for name in ("drinking:schedule", "drinking:schedule_add"):
            assert client_in.get(reverse(name)).status_code == 200
        row = SamplingSchedule.objects.get()
        assert client_in.get(
            reverse("drinking:schedule_edit", args=[row.pk])
        ).status_code == 200

    def test_the_nav_carries_the_schedule(self, shape_2, client_in, system):
        html = client_in.get(reverse("drinking:overview")).content.decode()
        assert f'href="{reverse("drinking:schedule")}"' in html
