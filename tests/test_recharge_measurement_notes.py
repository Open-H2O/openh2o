# SPDX-License-Identifier: AGPL-3.0-or-later
"""The recharge basin's readings show their notes (ISS-146).

Every seeded basin reading carries a plain-English note saying what was measured
and why — the half that reads like fieldwork rather than telemetry — and the
"Recent measurements" card rendered Date / Type / Value / Unit and nothing else,
so 126 notes reached no reader.

The note goes on a second line under its own row: one ``<tr>`` holding a single
cell that spans the four columns, rendered only when the reading has a note. A
reading without one adds no row. Chosen over a ``title`` attribute (invisible
until hovered, unreachable on touch) and over an expandable (a control for one
sentence). The card sits in the narrow right-hand column, so the note wraps
inside the existing width and adds none.

The row count is asserted exactly, never ``>``: two readings with one note is
three body rows; two readings with no note is two.
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


def test_a_reading_with_a_note_renders_it_on_a_second_line_under_the_row():
    site = RechargeSiteFactory(name="Noted basin")
    _reading(site, 18, "infiltration_rate", "1.0300", "in/hr", notes=NOTE)
    _reading(site, 10, "water_level", "3.4100", "ft")

    html = _login().get(reverse("recharge:detail", args=[site.pk])).content.decode()
    tbody = _measurements_tbody(html)

    assert NOTE in tbody
    assert len(re.findall(r"<tr\b", tbody)) == 3
    # The note sits directly under the reading it belongs to (newest first, so
    # the 18 February infiltration reading comes first and its note follows it).
    assert tbody.index("1.03") < tbody.index(NOTE) < tbody.index("3.41")
    assert 'colspan="4"' in tbody


def test_readings_without_notes_add_no_second_row():
    site = RechargeSiteFactory(name="Quiet basin")
    _reading(site, 18, "infiltration_rate", "1.0300", "in/hr")
    _reading(site, 10, "water_level", "3.4100", "ft")

    html = _login().get(reverse("recharge:detail", args=[site.pk])).content.decode()
    tbody = _measurements_tbody(html)

    assert len(re.findall(r"<tr\b", tbody)) == 2
    assert "colspan" not in tbody
