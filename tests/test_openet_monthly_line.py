# SPDX-License-Identifier: AGPL-3.0-or-later
"""The monthly OpenET line (crontab.txt) ends in one line, not a failure.

The line passes no dates. On the api and gee routes the command used to stop with
"--start-date and --end-date are required" every month; with no key it sent its
requests with an empty key and failed. No request goes to OpenET in these tests.
"""
from datetime import date
from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.test import override_settings

from tests.factories import ParcelFactory

pytestmark = pytest.mark.django_db


class _Adapter:
    def __init__(self):
        self.asked = []

    def sync_parcel_et(self, parcels, start_date, end_date):
        self.asked.append((start_date, end_date))
        return {"asked": len(parcels)}


def _no_request(*args, **kwargs):
    raise AssertionError("a request was sent to OpenET")


@pytest.mark.parametrize("mode", ["api", "gee"])
def test_the_monthly_line_runs_on_every_route_with_no_dates(mode, monkeypatch):
    monkeypatch.setenv("OPENET_API_KEY", "invented-key")
    ParcelFactory()
    adapter = _Adapter()
    out = StringIO()
    with override_settings(OPENET_MODE=mode), \
            patch("datasync.management.commands.sync_openet_parcels.get_openet_adapter",
                  return_value=adapter), \
            patch("datasync.management.commands.sync_openet_parcels.crop_et.differing_lines",
                  return_value=[]), \
            patch("requests.post", side_effect=_no_request), \
            patch("requests.get", side_effect=_no_request):
        call_command("sync_openet_parcels", stdout=out)
    assert len(adapter.asked) == 1
    start, end = adapter.asked[0]
    assert start <= end
    # The last day of last month: a month in progress is never asked for.
    assert end < date.today().replace(day=1)


@pytest.mark.parametrize("mode", ["fields", "api"])  # gee signs in with its own key file
def test_the_monthly_line_with_no_key_ends_in_one_line(mode, monkeypatch):
    monkeypatch.delenv("OPENET_API_KEY", raising=False)
    ParcelFactory()
    out = StringIO()
    with override_settings(OPENET_MODE=mode), \
            patch("requests.post", side_effect=_no_request), \
            patch("requests.get", side_effect=_no_request), \
            patch("requests.Session.request", side_effect=_no_request):
        call_command("sync_openet_parcels", stdout=out)
    lines = [line for line in out.getvalue().splitlines() if line.strip()]
    assert len(lines) == 1, lines
    assert "OPENET_API_KEY" in lines[0]
