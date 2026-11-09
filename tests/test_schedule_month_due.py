# SPDX-License-Identifier: AGPL-3.0-or-later
"""
152-03.3 (ISS-374): a due date the state gives as a month.

Written first, before the feature. A schedule row whose ``next_due_is_month`` is
true keeps the first of the month in ``next_due`` and is shown as a month
everywhere: "Jul 2035" in the Schedule table, "July 2035" on the Water Systems
page and the edit form. "that month has passed" shows only once the whole month
is over. Rows 1 to 6 of ``.planning/phases/152-proven-by-strangers/152-03.3-ROWS.md``.

All data is INVENTED (invented test data).
"""

import re
from datetime import date
from html import unescape

import factory
import pytest
from django.contrib.auth.hashers import make_password
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from drinking.models import SamplingSchedule, WaterSystem
from tests.factories import WaterSystemFactory

ROW_1 = "Import the state's schedule"
ROW_2 = (
    "Import the state's schedule file. You can also add a row for each item on "
    "your sampling checklist."
)
ROW_6 = (
    "The state's file gives this date as a month: July 2035. The box shows the "
    "first day of that month. When you save a different day, OpenH2O keeps that "
    "day in place of the month."
)


class _UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"monthdue{n}")
    email = factory.Sequence(lambda n: f"monthdue{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True


@pytest.fixture
def writer(db):
    client = Client()
    client.force_login(_UserFactory())
    return client


@pytest.fixture
def system(db):
    WaterSystem.objects.all().delete()  # see tests/test_production_import.py::le_grand
    return WaterSystemFactory(pwsid="XX0000001", name="Invented Test Water District")


def words(response):
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", response.content.decode())).split())


def month_row(system, when, label="Invented Month Row", **fields):
    return SamplingSchedule.objects.create(
        system=system, group_label=label, frequency="annual",
        next_due=when, next_due_is_month=True, **fields,
    )


def this_month():
    return timezone.localdate().replace(day=1)


def last_month():
    first = this_month()
    return date(first.year - 1, 12, 1) if first.month == 1 else date(first.year, first.month - 1, 1)


# -- the Schedule page ------------------------------------------------------------


def test_a_month_row_shows_the_month_and_not_a_day(writer, system):
    month_row(system, date(2035, 7, 1))
    shown = words(writer.get(reverse("drinking:schedule")))
    assert "Jul 2035" in shown
    assert "Jul 1, 2035" not in shown


def test_a_day_row_still_shows_its_day(writer, system):
    SamplingSchedule.objects.create(
        system=system, group_label="Invented Day Row", frequency="annual",
        next_due=date(2035, 7, 15),
    )
    shown = words(writer.get(reverse("drinking:schedule")))
    assert "Jul 15, 2035" in shown


def test_a_month_that_is_over_says_that_month_has_passed(writer, system):
    month_row(system, last_month())
    assert "that month has passed" in words(writer.get(reverse("drinking:schedule")))


def test_the_current_month_has_not_passed(writer, system):
    month_row(system, this_month())
    assert "that month has passed" not in words(writer.get(reverse("drinking:schedule")))


def test_a_month_ahead_has_not_passed(writer, system):
    month_row(system, date(2035, 7, 1))
    assert "that month has passed" not in words(writer.get(reverse("drinking:schedule")))


def test_a_month_row_never_says_past_the_date_you_set(writer, system):
    month_row(system, last_month())
    assert "past the date you set" not in words(writer.get(reverse("drinking:schedule")))


def test_a_day_row_that_is_over_still_says_past_the_date_you_set(writer, system):
    SamplingSchedule.objects.create(
        system=system, group_label="Invented Day Row", frequency="annual",
        next_due=date(2020, 1, 15),
    )
    shown = words(writer.get(reverse("drinking:schedule")))
    assert "past the date you set" in shown
    assert "that month has passed" not in shown


# -- the Import button ---------------------------------------------------------------


def test_the_head_bar_carries_the_import_link_when_rows_exist(writer, system):
    SamplingSchedule.objects.create(
        system=system, group_label="Coliform", frequency="monthly", next_due=date(2035, 7, 15),
    )
    html = writer.get(reverse("drinking:schedule")).content.decode()
    link = re.search(
        r'<a[^>]*href="%s"[^>]*>\s*%s\s*</a>' % (
            re.escape(reverse("drinking:schedule_import")),
            re.escape("Import the state&#x27;s schedule"),
        ),
        html,
    ) or re.search(
        r'<a[^>]*href="%s"[^>]*>\s*%s\s*</a>' % (
            re.escape(reverse("drinking:schedule_import")), re.escape(ROW_1),
        ),
        html,
    )
    assert link, "no link to the import page with the text of row 1"


def test_the_empty_card_carries_row_2_and_the_import_link(writer, system):
    response = writer.get(reverse("drinking:schedule"))
    assert ROW_2 in words(response)
    assert reverse("drinking:schedule_import") in response.content.decode()
    assert ROW_1 in words(response)


def test_the_empty_card_keeps_the_add_button(writer, system):
    response = writer.get(reverse("drinking:schedule"))
    assert reverse("drinking:schedule_add") in response.content.decode()
    assert reverse("drinking:schedule_import") in response.content.decode()


# -- the Water Systems page -------------------------------------------------------------


def test_the_water_systems_page_words_a_month_row(writer, system):
    month_row(system, date(2035, 7, 1), label="Coliform")
    shown = words(writer.get(reverse("drinking:overview")))
    assert "Next due: Coliform in July 2035." in shown
    assert "Coliform on July 1, 2035" not in shown


def test_the_water_systems_page_says_that_month_has_passed_once_it_is_over(writer, system):
    month_row(system, last_month(), label="Coliform")
    shown = words(writer.get(reverse("drinking:overview")))
    assert "That month has passed." in shown
    assert "That date has passed." not in shown


def test_the_water_systems_page_does_not_say_it_in_the_current_month(writer, system):
    month_row(system, this_month(), label="Coliform")
    assert "That month has passed." not in words(writer.get(reverse("drinking:overview")))


def test_the_water_systems_page_still_words_a_day_row_as_before(writer, system):
    SamplingSchedule.objects.create(
        system=system, group_label="Coliform", frequency="monthly", next_due=date(2035, 10, 7),
    )
    shown = words(writer.get(reverse("drinking:overview")))
    assert "Next due: Coliform on October 7, 2035." in shown
    assert "That month has passed." not in shown


# -- the edit form ---------------------------------------------------------------------------


def edit_url(row):
    return reverse("drinking:schedule_edit", args=[row.pk])


def post_edit(client, row, next_due):
    return client.post(edit_url(row), {
        "group_label": row.group_label, "frequency": "annual",
        "last_done": "", "next_due": next_due, "notes": "",
    })


def test_a_month_row_edit_form_shows_row_6_with_the_month_filled(writer, system):
    row = month_row(system, date(2035, 7, 1))
    response = writer.get(edit_url(row))
    assert ROW_6 in words(response)
    assert 'value="2035-07-01"' in response.content.decode()


def test_a_day_row_edit_form_does_not_show_row_6(writer, system):
    row = SamplingSchedule.objects.create(
        system=system, group_label="Invented Day Row", frequency="annual",
        next_due=date(2035, 7, 15),
    )
    assert "gives this date as a month" not in words(writer.get(edit_url(row)))


def test_saving_the_same_date_keeps_the_row_a_month(writer, system):
    row = month_row(system, date(2035, 7, 1))
    response = post_edit(writer, row, "2035-07-01")
    assert response.status_code == 302
    row.refresh_from_db()
    assert row.next_due == date(2035, 7, 1)
    assert row.next_due_is_month is True


def test_saving_a_different_day_makes_the_row_a_day(writer, system):
    row = month_row(system, date(2035, 7, 1))
    response = post_edit(writer, row, "2035-07-19")
    assert response.status_code == 302
    row.refresh_from_db()
    assert row.next_due == date(2035, 7, 19)
    assert row.next_due_is_month is False


def test_the_edit_form_offers_every_6_years(writer, system):
    row = month_row(system, date(2035, 7, 1))
    assert "Every 6 years" in words(writer.get(edit_url(row)))
