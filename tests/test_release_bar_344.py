# SPDX-License-Identifier: AGPL-3.0-or-later
"""The line under a voided or replaced record names the site's own day, in any time zone.

A site sets its zone once (settings.TIME_ZONE). The statement card names a correction's day in
that zone; the struck line under the record must name the same day, or one correction reads as
two different days on one page. The moment used, 06:30 UTC on Jan 15, is Jan 15 in New York and
Jan 14 in Pacific, so a line that still reads Pacific shows the wrong day.
"""

import datetime as dt

import pytest
from django.test import override_settings

from accounting.statements import _day
from core.templatetags.record_marks import replaced_line, void_line
from tests.factories import DiversionRecordFactory

pytestmark = pytest.mark.django_db

MOMENT = dt.datetime(2026, 1, 15, 6, 30, tzinfo=dt.timezone.utc)


@override_settings(TIME_ZONE="America/New_York")
def test_the_void_line_names_the_same_day_as_the_statement():
    record = DiversionRecordFactory()
    type(record).objects.filter(pk=record.pk).update(
        voided_at=MOMENT, void_reason="typed on the wrong gate"
    )
    record.refresh_from_db()

    assert _day(MOMENT) == "Jan 15, 2026"
    assert void_line(record).startswith(f"Voided {_day(MOMENT)} by ")


@override_settings(TIME_ZONE="America/New_York")
def test_the_replaced_line_names_the_same_day_as_the_statement():
    record = DiversionRecordFactory()
    type(record).objects.filter(pk=record.pk).update(replaced_at=MOMENT)
    record.refresh_from_db()

    text, _ = replaced_line(record)

    assert text.startswith(f"Replaced {_day(MOMENT)}")
