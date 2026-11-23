# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Setup Wizard's Flowlines and Monitoring Stations steps run as their own process.

At Merced size the Flowlines step held one poll for 58.5 s while it saved 5,658 streams and
canals, and a real station provider can hold one for about 30 s. Now each step starts
``run_pending_import`` the way the parcel download does: the poll answers at once, the page
shows the count, and a process that goes quiet is reported as stopped with the way to
finish. Groundwater Basins (1.7 s) still runs inside the poll.
"""
import datetime
import re
from unittest.mock import MagicMock, patch

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.gis.geos import MultiPolygon, Polygon
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from core import pending_imports
from core.models import PendingImport
from datasync.models import DataSource, MonitoredStation
from geography.models import Boundary, Flowline
from setup.services import STATION_PROVIDERS

pytestmark = pytest.mark.django_db
User = get_user_model()
PROGRESS_URL = reverse("setup:progress")

KEEP_OPEN = ("Keep this page open until every step finishes. A step that has started keeps going "
             "if you leave, but the next step starts only when you come back.")


def _rerun(step):
    return ("Run the Setup Wizard again and choose this boundary under Select an existing boundary. "
            f"On the Populate step, check only {step}.")


@pytest.fixture
def boundary():
    return Boundary.objects.create(
        name="Streams Test Boundary",
        geometry=MultiPolygon(Polygon.from_bbox((-119.5, 36.0, -119.0, 36.5))))


@pytest.fixture
def client(boundary):
    user = User.objects.create_user(
        username="streams-admin", email="streams-admin@example.com", password="x",
        is_active=True, is_staff=True, is_superuser=True)
    c = Client()
    c.force_login(user)
    return c


def _at(client, boundary, step, steps=("flowlines", "stations")):
    """The session as the wizard leaves it when ``step`` is next."""
    order = ["basins", "parcels", "flowlines", "stations"]
    session = client.session
    session["setup_wizard_boundary_id"] = boundary.pk
    session["setup_wizard_selected_steps"] = list(steps)
    session["setup_wizard_step_index"] = order.index(step)
    session["setup_wizard_provider_index"] = 0
    session["setup_wizard_results"] = [
        {"step": name, "label": name.title(), "count": 0, "errors": [], "success": True,
         "note": "Skipped: you unchecked this step"}
        for name in order[:order.index(step)]
    ]
    session.save()
    client.cookies[settings.SESSION_COOKIE_NAME] = session.session_key


def _poll(client, captured):
    with patch("core.pending_imports.subprocess.Popen") as popen:
        with captured(execute=True):
            response = client.post(PROGRESS_URL)
    return response, popen


def _words(response):
    text = re.sub(r"<[^>]+>", "", response.content.decode())
    return " ".join(text.split()).replace("&#x27;", "'")


def _feature(i):
    return {
        "attributes": {"id3dhp": f"FL{i:05d}", "gnisidlabel": f"Creek {i}",
                       "featuretypelabel": "Stream/River", "lengthkm": 1.0, "streamorder": 1},
        "geometry": {"paths": [[[-119.3 + i * 0.001, 36.3], [-119.29 + i * 0.001, 36.31]]]},
    }


def _pages(*sizes):
    first = 0
    pages = []
    for size in sizes:
        pages.append([_feature(i) for i in range(first, first + size)])
        first += size
    return pages


# -- Flowlines -------------------------------------------------------------------------------


# Default wording, approved by the maintainer on 2026-11-16. To change the wording, update this test in the same commit.
def test_flowlines_answers_at_once_and_starts_one_process(
        client, boundary, settings, django_capture_on_commit_callbacks):
    settings.OPENH2O_IMPORT_INLINE = False
    _at(client, boundary, "flowlines")
    response, popen = _poll(client, django_capture_on_commit_callbacks)

    assert popen.call_count == 1
    assert popen.call_args.args[0][-3:-1] == ["run_pending_import", "--token"]
    pending = PendingImport.objects.get(kind="setup_flowlines")
    assert pending.status == "waiting"
    assert pending.settings["boundary_id"] == boundary.pk
    words = _words(response)
    assert "Finding the streams and canals in and near the boundary…" in words
    assert KEEP_OPEN in words
    assert 'hx-trigger="load delay:2s"' in response.content.decode()
    assert not Flowline.objects.exists()

    _, popen = _poll(client, django_capture_on_commit_callbacks)
    assert popen.call_count == 0  # a poll while it runs starts nothing new


# Default wording, approved by the maintainer on 2026-11-16. To change the wording, update this test in the same commit.
def test_the_flowlines_progress_line_counts_the_download(
        client, boundary, settings, django_capture_on_commit_callbacks):
    settings.OPENH2O_IMPORT_INLINE = False
    _at(client, boundary, "flowlines")
    _poll(client, django_capture_on_commit_callbacks)
    pending = PendingImport.objects.get(kind="setup_flowlines")
    pending.status = "running"
    pending.result = {"total": 5658, "done": 2500, "saved": 2500, "updated": timezone.now().isoformat()}
    pending.save()
    assert ("Downloading the streams and canals in and near the boundary: 2,500 of 5,658"
            in _words(client.post(PROGRESS_URL)))

    pending.result = {"total": None, "done": 2500, "saved": 2500, "updated": timezone.now().isoformat()}
    pending.save()
    assert ("Downloading the streams and canals in and near the boundary: 2,500 so far"
            in _words(client.post(PROGRESS_URL)))


def test_the_flowlines_process_saves_and_counts_then_the_poll_shows_the_result(
        client, boundary, settings, django_capture_on_commit_callbacks):
    settings.OPENH2O_IMPORT_INLINE = False
    _at(client, boundary, "flowlines")
    _poll(client, django_capture_on_commit_callbacks)
    pending = PendingImport.objects.get(kind="setup_flowlines")

    with patch("geography.management.commands.auto_populate.query_feature_server",
               return_value=iter(_pages(3, 2))), \
            patch("setup.services.count_features", return_value=5):
        pending_imports.run(str(pending.token))
    assert Flowline.objects.filter(boundary=boundary).count() == 5
    pending.refresh_from_db()
    assert pending.status == "finished"
    assert pending.result["count"] == 5

    done = client.post(PROGRESS_URL)
    assert Flowline.objects.count() == 5
    assert not PendingImport.objects.filter(kind="setup_flowlines").exists()
    assert "5 records created" in _words(done)


def test_a_usgs_failure_inside_the_process_shows_todays_error_row(
        client, boundary, settings, django_capture_on_commit_callbacks):
    settings.OPENH2O_IMPORT_INLINE = False
    _at(client, boundary, "flowlines")
    _poll(client, django_capture_on_commit_callbacks)
    pending = PendingImport.objects.get(kind="setup_flowlines")

    def fail(*args, **kwargs):
        yield [_feature(0)]
        raise RuntimeError("the service returned an empty page")

    with patch("geography.management.commands.auto_populate.query_feature_server", side_effect=fail), \
            patch("setup.services.count_features", return_value=None):
        pending_imports.run(str(pending.token))
    response = client.post(PROGRESS_URL)
    assert "wizard-step--error" in response.content.decode()
    assert "Couldn't complete this step: the service returned an empty page" in _words(response)
    assert Flowline.objects.count() == 1  # the pages saved before the failure stay


# Default wording, approved by the maintainer on 2026-11-16. To change the wording, update this test in the same commit.
def test_a_flowlines_process_that_went_quiet_is_reported_stopped(
        client, boundary, settings, django_capture_on_commit_callbacks):
    settings.OPENH2O_IMPORT_INLINE = False
    _at(client, boundary, "flowlines")
    _poll(client, django_capture_on_commit_callbacks)
    pending = PendingImport.objects.get(kind="setup_flowlines")
    quiet = timezone.now() - datetime.timedelta(minutes=11)
    pending.status = "running"
    pending.result = {"total": 5658, "done": 2500, "saved": 2500, "updated": quiet.isoformat()}
    pending.save()

    response = client.post(PROGRESS_URL)
    words = _words(response)
    assert "The download stopped after OpenH2O saved 2,500 streams and canals." in words
    assert _rerun("Flowlines") in words
    assert "wizard-step--error" in response.content.decode()
    assert not PendingImport.objects.filter(kind="setup_flowlines").exists()


# -- Monitoring Stations ---------------------------------------------------------------------


def _adapter(code):
    a = MagicMock()
    a.missing_required_credential.return_value = None
    a.discover_stations.return_value = [{
        "station_id": f"{code.upper()}-1", "name": f"{code} station",
        "latitude": 36.25, "longitude": -119.25, "parameters": ["p"]}]
    return a


@pytest.fixture
def sources(settings):
    settings.DATASYNC_MOCK_MODE = False
    for code in STATION_PROVIDERS:
        DataSource.objects.create(name=f"{code.upper()} Service", code=code)


def test_stations_answer_at_once_and_start_one_process(
        client, boundary, sources, settings, django_capture_on_commit_callbacks):
    settings.OPENH2O_IMPORT_INLINE = False
    _at(client, boundary, "stations")
    response, popen = _poll(client, django_capture_on_commit_callbacks)

    assert popen.call_count == 1
    assert PendingImport.objects.get(kind="setup_stations").status == "waiting"
    assert not MonitoredStation.objects.exists()
    assert "Checking USGS Service…" in _words(response)
    assert KEEP_OPEN in _words(response)


def test_the_station_process_checks_every_provider_and_the_poll_lists_them(
        client, boundary, sources, settings, django_capture_on_commit_callbacks, monkeypatch):
    from geography.management.commands import auto_populate as ap

    monkeypatch.setattr(ap, "get_adapter", _adapter)
    settings.OPENH2O_IMPORT_INLINE = False
    _at(client, boundary, "stations")
    _poll(client, django_capture_on_commit_callbacks)
    pending = PendingImport.objects.get(kind="setup_stations")
    pending_imports.run(str(pending.token))
    assert MonitoredStation.objects.count() == len(STATION_PROVIDERS)

    done = client.post(PROGRESS_URL)
    words = _words(done)
    for code in STATION_PROVIDERS:
        assert f"{code.upper()} Service" in words
    assert words.count("1 record created") == len(STATION_PROVIDERS)
    assert "what's next" in words.lower()
    assert not PendingImport.objects.filter(kind="setup_stations").exists()


def test_while_stations_run_the_page_lists_the_providers_done_and_the_next(
        client, boundary, sources, settings, django_capture_on_commit_callbacks):
    settings.OPENH2O_IMPORT_INLINE = False
    _at(client, boundary, "stations")
    _poll(client, django_capture_on_commit_callbacks)
    pending = PendingImport.objects.get(kind="setup_stations")
    pending.status = "running"
    pending.result = {
        "done": [{"code": "usgs", "count": 4, "errors": [], "status": "created"}],
        "current": "cdec", "updated": timezone.now().isoformat()}
    pending.save()
    words = _words(client.post(PROGRESS_URL))
    assert "USGS Service" in words and "4 records created" in words
    assert "Checking CDEC Service…" in words


# Default wording, approved by the maintainer on 2026-11-16. To change the wording, update this test in the same commit.
def test_a_station_process_that_went_quiet_is_reported_stopped(
        client, boundary, sources, settings, django_capture_on_commit_callbacks):
    settings.OPENH2O_IMPORT_INLINE = False
    _at(client, boundary, "stations")
    _poll(client, django_capture_on_commit_callbacks)
    pending = PendingImport.objects.get(kind="setup_stations")
    quiet = timezone.now() - datetime.timedelta(minutes=11)
    done = [{"code": code, "count": 1, "errors": [], "status": "created"} for code in STATION_PROVIDERS[:3]]
    pending.status = "running"
    pending.result = {"done": done, "current": STATION_PROVIDERS[3], "updated": quiet.isoformat()}
    pending.save()

    response = client.post(PROGRESS_URL)
    words = _words(response)
    assert f"The search stopped after OpenH2O checked 3 of {len(STATION_PROVIDERS)} data providers." in words
    assert _rerun("Monitoring Stations") in words
    assert "wizard-step--error" in response.content.decode()
    assert not PendingImport.objects.filter(kind="setup_stations").exists()


# -- Basins stay in the poll -----------------------------------------------------------------


def test_basins_still_run_inside_the_poll(client, boundary, settings, django_capture_on_commit_callbacks):
    settings.OPENH2O_IMPORT_INLINE = False
    _at(client, boundary, "basins", steps=("basins",))
    with patch("geography.management.commands.auto_populate.Command._step_basins", return_value=1):
        response, popen = _poll(client, django_capture_on_commit_callbacks)
    assert popen.call_count == 0
    assert not PendingImport.objects.exists()
    assert "1 record created" in _words(response)


def test_an_unchecked_download_step_is_never_shown_as_running(client, boundary):
    """Seen at Merced size: with Parcel Boundaries unchecked, the poll after the basins
    showed "Finding the parcels that overlap the boundary…" for one poll."""
    _at(client, boundary, "basins", steps=("flowlines",))
    response = client.post(PROGRESS_URL)  # reports the basins skipped; Parcel Boundaries is next, unchecked
    assert response.context["parcels_running"] is False
    assert response.context["download_running"] is False
