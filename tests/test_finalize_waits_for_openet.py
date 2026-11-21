# SPDX-License-Identifier: AGPL-3.0-or-later
"""Finalize water year waits while a month of the year waits for OpenET (ruling 214).

The Finalize card names each waiting month and its use areas and offers Finalize anyway in
place of Finalize water year. Pressing Finalize water year while a month waits (a page loaded
before the month ended) finalizes nothing and names the month. Finalize anyway closes the year
and the change history records the months and use areas left out. A year finalized that way
says on every page that the month had no crop ET when the year was finalized, in place of
"waiting for OpenET", because a finalized year is never asked for or calculated again;
reopening it brings the waiting words back and the next monthly request asks for the year.
Ruling 215 approved the words.

The site is ``tests/test_waiting_for_openet.py``'s: WY 2025-2026 read on October 3, 2026,
WAIT-1 and WAIT-2 in OpenET fields with no crop ET for September 2026, WAIT-4 in no field.
"""
import re
from datetime import date
from unittest.mock import patch

import pytest
from django.test import Client
from django.urls import reverse

from accounting.models import ReportingPeriod
from core import pending_imports
from core.models import PendingImport, User
from tests.factories import ReportingPeriodFactory, WaterAccountFactory, WaterAccountParcelFactory
from tests.test_waiting_for_openet import (  # noqa: F401  (world is a fixture, used by name)
    MONTHS,
    OCT3,
    SEP,
    _on,
    _run_year,
    _use_area,
    world,
)

pytestmark = pytest.mark.django_db


def _user(username, **flags):
    return User.objects.create_user(
        username=username, email=f"{username}@example.org", password="a-good-passw0rd", **flags
    )


@pytest.fixture
def admin_client():
    client = Client()
    client.force_login(_user("closer", agency_admin=True))
    return client


def _words(response):
    text = re.sub(r"<[^>]+>", " ", response.content.decode())
    return " ".join(text.split()).replace("&#x27;", "'")


def _text(response):
    """The page's words with tags removed in place (so a linked name keeps the comma after it)."""
    text = re.sub(r"<[^>]+>", "", response.content.decode())
    return " ".join(text.split()).replace("&#x27;", "'")


def _page(client, period):
    return client.get(reverse("accounting:period_detail", args=[period.pk]))


def _finalize_button(response):
    return re.search(r"<button[^>]*>\s*Finalize water year\s*</button>", response.content.decode())


def _anyway_button(response):
    return re.search(r"<button[^>]*>\s*Finalize anyway\s*</button>", response.content.decode())


def _press(client, period, settings, captured, **data):
    """Press the Finalize card's button; the run is saved, its process not started."""
    settings.OPENH2O_IMPORT_INLINE = False
    with patch("core.pending_imports.subprocess.Popen"):
        with captured(execute=True):
            return client.post(reverse("accounting:period_finalize", args=[period.pk]), data)


def _finalize_runs():
    return PendingImport.objects.filter(kind="finalize")


def _run_the_process():
    pending_imports.run(str(_finalize_runs().get().token))


def _finalize_anyway(client, period, settings, captured):
    _press(client, period, settings, captured, anyway="1")
    _run_the_process()
    period.refresh_from_db()


# -- (a) the card names the months and the use areas -----------------------------------------------


def test_the_card_names_the_waiting_month_and_its_use_areas_and_offers_finalize_anyway(world, admin_client):
    page = _page(admin_client, world.period)
    text = _words(page)

    assert page.status_code == 200
    assert "September 2026" in text
    for parcel in (world.u1, world.u2):
        assert reverse("parcels:detail", args=[parcel.pk]) in page.content.decode()
        assert parcel.parcel_number in text
    assert "WAIT-4" not in text  # in no OpenET field: never waiting (ruling 160)
    assert _anyway_button(page)
    assert not _finalize_button(page)


# -- (b) pressing Finalize water year while a month waits -----------------------------------------


def test_pressing_finalize_water_year_while_a_month_waits_finalizes_nothing(
        world, admin_client, settings, django_capture_on_commit_callbacks):
    response = _press(admin_client, world.period, settings, django_capture_on_commit_callbacks)

    assert response.status_code == 200
    assert _finalize_runs().count() == 0
    world.period.refresh_from_db()
    assert world.period.is_finalized is False
    assert "September 2026" in _words(response)
    assert _anyway_button(response)


# -- (c) Finalize anyway ----------------------------------------------------------------------------


def test_finalize_anyway_starts_one_run_and_the_history_names_the_months_and_use_areas(
        world, admin_client, settings, django_capture_on_commit_callbacks):
    _press(admin_client, world.period, settings, django_capture_on_commit_callbacks, anyway="1")
    assert _finalize_runs().count() == 1

    _run_the_process()

    world.period.refresh_from_db()
    assert world.period.is_finalized is True
    note = world.period.events.get(pgh_label="update").pgh_context.metadata["note"]
    # wording approved: ruling 215 (row C1)
    assert note == "Finalized with months waiting for OpenET. September 2026: WAIT-1 and WAIT-2."


# -- (d) nothing waiting: as today ----------------------------------------------------------------


@pytest.fixture
def every_month(monkeypatch):
    _on(monkeypatch, OCT3)
    period = ReportingPeriodFactory(
        name="WY 2025-2026 (complete)", start_date=date(2025, 10, 1), end_date=date(2026, 9, 30)
    )
    _use_area("FULL-1", months=MONTHS + [SEP])
    _use_area("FULL-2", months=MONTHS + [SEP])
    return period


def test_a_year_with_every_month_finalizes_as_today(
        every_month, admin_client, settings, django_capture_on_commit_callbacks):
    page = _page(admin_client, every_month)
    assert _finalize_button(page)
    assert not _anyway_button(page)
    assert "FULL-1" not in _words(page)

    response = _press(admin_client, every_month, settings, django_capture_on_commit_callbacks)
    assert response.status_code == 302
    assert _finalize_runs().get().settings["note"] == ""


# -- (e) what never holds Finalize back (ruling 160) ----------------------------------------------


def test_a_use_area_in_no_openet_field_does_not_hold_finalize_back(monkeypatch, admin_client):
    _on(monkeypatch, OCT3)
    period = ReportingPeriodFactory(start_date=date(2025, 10, 1), end_date=date(2026, 9, 30))
    _use_area("NOFIELD-1", months=[], with_field=False)

    page = _page(admin_client, period)
    assert _finalize_button(page)
    assert not _anyway_button(page)


def test_a_month_not_yet_ended_does_not_hold_finalize_back(world, monkeypatch, admin_client):
    _on(monkeypatch, date(2026, 9, 15))  # September has not ended; August is recorded

    page = _page(admin_client, world.period)
    assert _finalize_button(page)
    assert not _anyway_button(page)


def test_nothing_holds_finalize_back_with_datasync_off(world, monkeypatch, admin_client):
    from accounting import year_reading

    monkeypatch.setattr(year_reading, "is_enabled", lambda name: name != "datasync")

    page = _page(admin_client, world.period)
    assert _finalize_button(page)
    assert not _anyway_button(page)


# -- (f) a month that ended after the page was loaded ----------------------------------------------


def test_a_press_from_a_page_loaded_before_the_month_ended_is_refused_and_names_it(
        world, monkeypatch, admin_client, settings, django_capture_on_commit_callbacks):
    _on(monkeypatch, date(2026, 9, 30))
    assert _finalize_button(_page(admin_client, world.period))

    _on(monkeypatch, date(2026, 10, 1))
    response = _press(admin_client, world.period, settings, django_capture_on_commit_callbacks)

    assert response.status_code == 200
    assert _finalize_runs().count() == 0
    text = _words(response)
    assert "September 2026" in text
    # wording approved: ruling 215 (row B1)
    assert (
        "This water year is still open. A month ended after this page was loaded, and OpenET "
        "has not sent it. Wait for OpenET, or press Finalize anyway." in text
    )


# -- (g) seven use areas: five named, the rest counted ---------------------------------------------


def test_a_month_with_seven_use_areas_waiting_names_five_and_counts_two_more(monkeypatch, admin_client):
    _on(monkeypatch, OCT3)
    period = ReportingPeriodFactory(start_date=date(2025, 10, 1), end_date=date(2026, 9, 30))
    for n in range(7, 0, -1):
        _use_area(f"SEV-{n}")

    text = _text(_page(admin_client, period))

    for n in range(1, 6):
        assert f"SEV-{n}" in text
    assert "SEV-6" not in text and "SEV-7" not in text
    # wording approved: ruling 215 (row A2)
    assert "September 2026: SEV-1, SEV-2, SEV-3, SEV-4, SEV-5 and 2 more use areas" in text


# -- (h) a year finalized anyway ---------------------------------------------------------------------


def test_a_year_finalized_anyway_says_the_month_had_no_crop_et_and_reopening_waits_again(
        world, admin_client, settings, django_capture_on_commit_callbacks):
    from datasync.management.commands.sync_openet_parcels import Command

    account = WaterAccountFactory(status="active")
    for parcel in (world.u1, world.u2):
        WaterAccountParcelFactory(water_account=account, parcel=parcel)
    _run_year(world)
    _finalize_anyway(admin_client, world.period, settings, django_capture_on_commit_callbacks)
    assert world.period.is_finalized is True

    pane = _words(admin_client.get(reverse("parcels:detail", args=[world.u1.pk]) + f"?period={world.period.pk}"))
    month = admin_client.get(reverse("accounting:calculation_run_detail", args=[world.u1.pk, "2026-09"]))
    account_page = _words(admin_client.get(
        reverse("accounting:account_detail", args=[account.pk]) + f"?period={world.period.pk}"))
    dashboard = _words(admin_client.get(reverse("accounting:dashboard") + f"?period={world.period.pk}"))

    assert month.status_code == 200
    for text in (pane, _words(month), account_page, dashboard):
        assert "waiting for OpenET" not in text.replace("A month waiting for OpenET", "")
    # wording approved: ruling 215 (rows D1, D3, D7, D8, D9)
    assert "No crop ET when finalized" in pane
    assert (
        "The balance runs through August 2026. OpenH2O had no crop ET for September 2026 when this "
        "water year was finalized. The month is left out of the balance." in pane
    )
    assert "No crop ET when finalized: September 2026" in _words(month)
    assert (
        "OpenH2O had no crop ET for September 2026 when this water year was finalized. The month is "
        "left out of this use area's balance." in _words(month)
    )
    assert "Use areas with a month left out when finalized 2" in account_page
    assert "Use areas with a month left out when finalized 2" in dashboard

    admin_client.post(
        reverse("accounting:period_finalize", args=[world.period.pk]), {"note": "Late OpenET month arrived"}
    )
    world.period.refresh_from_db()
    assert world.period.is_finalized is False
    pane = _words(admin_client.get(reverse("parcels:detail", args=[world.u1.pk]) + f"?period={world.period.pk}"))
    assert "Waiting for OpenET" in pane
    assert "No crop ET when finalized" not in pane
    assert Command._default_start() == world.period.start_date


# -- (i) an operator is still refused ----------------------------------------------------------------


def test_an_operators_finalize_anyway_is_refused_as_today(world):
    client = Client()
    client.force_login(_user("not-an-admin"))

    response = client.post(reverse("accounting:period_finalize", args=[world.period.pk]), {"anyway": "1"})

    assert response.status_code == 302
    assert ReportingPeriod.objects.get(pk=world.period.pk).is_finalized is False
    assert _finalize_runs().count() == 0
