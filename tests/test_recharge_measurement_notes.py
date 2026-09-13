# SPDX-License-Identifier: AGPL-3.0-or-later
"""The recharge basin's readings show their notes (ISS-146).

Every seeded basin reading carries a plain-English note saying what was measured
and why — the half that reads like fieldwork rather than telemetry — and the
"Recent measurements" card rendered Date / Type / Value / Unit and nothing else,
so 126 notes reached no reader.

The note went on a second line under its own row while the card sat in the
narrow right-hand column. 143-10 (R-126) moved the readings into a full-width
table grouped by what they measure (one ``tr.row-group`` per type, naming the
unit), so the note now has a column of its own on the reading's own row; a
reading without a note prints an em dash there. The row count is asserted
exactly, never ``>``: two readings of two types is two group rows and two
reading rows, whether or not either carries a note.
"""
import re
from datetime import datetime
from decimal import Decimal

import pytest
from django.contrib.auth.hashers import make_password
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from tests.factories import RechargeSiteFactory

pytestmark = pytest.mark.django_db

NOTE = (
    "Percolation re-checked late in the season. Down a little on December: "
    "fines off the storm have started to seal the floor."
)


def _login():
    from core.models import User

    user = User.objects.create(
        username="basinreader",
        email="basinreader@example.com",
        password=make_password("testpass123"),
        is_active=True,
    )
    client = Client()
    client.force_login(user)
    return client


def _reading(site, day, mtype, value, unit, notes=""):
    from recharge.models import RechargeMeasurement

    return RechargeMeasurement.objects.create(
        recharge_site=site,
        measurement_date=timezone.make_aware(datetime(2026, 2, day, 9, 0)),
        measurement_type=mtype,
        value=Decimal(value),
        unit=unit,
        notes=notes,
    )


def _measurements_tbody(html):
    card = html[html.index("Recent measurements"):]
    tbody = card[card.index("<tbody>"):card.index("</tbody>")]
    return tbody


def test_a_reading_with_a_note_renders_it_in_its_own_cell_on_its_own_row():
    site = RechargeSiteFactory(name="Noted basin")
    _reading(site, 18, "infiltration_rate", "1.0300", "in/hr", notes=NOTE)
    _reading(site, 10, "water_level", "3.4100", "ft")

    html = _login().get(reverse("recharge:detail", args=[site.pk])).content.decode()
    tbody = _measurements_tbody(html)

    assert NOTE in tbody
    # Two type groups (a divider row each) and one reading under each.
    assert len(re.findall(r"<tr\b", tbody)) == 4
    # The note sits in a cell on the row of the reading it belongs to, and on
    # no other row.
    rows = re.findall(r"<tr\b(?![^>]*row-group)[^>]*>(.*?)</tr>", tbody, re.S)
    assert len(rows) == 2
    (noted,) = [row for row in rows if NOTE in row]
    assert "1.03" in noted
    (quiet,) = [row for row in rows if NOTE not in row]
    assert "3.41" in quiet and "&mdash;" in quiet
    assert 'colspan="4"' not in tbody


def test_readings_without_notes_print_an_em_dash_in_the_note_cell():
    site = RechargeSiteFactory(name="Quiet basin")
    _reading(site, 18, "infiltration_rate", "1.0300", "in/hr")
    _reading(site, 10, "water_level", "3.4100", "ft")

    html = _login().get(reverse("recharge:detail", args=[site.pk])).content.decode()
    tbody = _measurements_tbody(html)

    assert len(re.findall(r"<tr\b", tbody)) == 4
    rows = re.findall(r"<tr\b(?![^>]*row-group)[^>]*>(.*?)</tr>", tbody, re.S)
    assert len(rows) == 2
    assert all("&mdash;" in row for row in rows)
