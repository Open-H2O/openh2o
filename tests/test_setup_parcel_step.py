# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Setup Wizard's parcel step runs as its own process and the page polls it.

Before 2026-11-15 the wizard ran the parcel download inside one web request (258 s
held open, then a failure the page could not act on). Now the step starts
``run_pending_import`` for a ``setup_parcels`` upload, answers at once, shows the
download's progress, and shows the result in the words approved on 2026-11-15. The other steps
still run inside the request.
"""
import datetime
from unittest.mock import patch

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from core import pending_imports
from core.models import PendingImport
from geography.models import Boundary
from parcels.models import Parcel
from tests.lightbox_fake import FakeLightBox, boundary_geometry

pytestmark = pytest.mark.django_db
User = get_user_model()

CONFIRM_URL = reverse("setup:confirm")
RUN_URL = reverse("setup:run")
PROGRESS_URL = reverse("setup:progress")

CALIFORNIA_LINE = (
    "The basins and parcels come from the California Department of Water Resources and cover "
    "California only. For land outside California, uncheck Groundwater Basins and Parcel "
    "Boundaries and load your parcel outlines with")
# wording approved: ruling 194 (row 10)
LEAVE_LINE = (
    "Keep this page open until every step finishes. A step that has started keeps going if you "
    "leave, but the next step starts only when you come back.")
RERUN_LINES = (
    "To add the rest, open the Setup Wizard and choose this boundary under Select an existing "
    "boundary. On Populate, check only Parcel Boundaries and choose your list again if you used "
    "one. OpenH2O saves only the parcels that are not yet on file.")


@pytest.fixture(autouse=True)
def no_backoff_sleep(monkeypatch):
    monkeypatch.setattr("geography.services.arcgis.time.sleep", lambda s: None)


@pytest.fixture
def client():
    user = User.objects.create_user(
        username="parcel-step-admin", email="parcel-step-admin@example.com", password="x",
        is_active=True, is_staff=True, is_superuser=True)
    c = Client()
    c.force_login(user)
    c.user = user
    return c


@pytest.fixture
def boundary():
    return Boundary.objects.create(name="Merced Test Subbasin", geometry=boundary_geometry())


def _choose(client, boundary):
    session = client.session
    session["setup_wizard_boundary_id"] = boundary.pk
    session.save()
    client.cookies[settings.SESSION_COOKIE_NAME] = session.session_key
    assert client.post(CONFIRM_URL).status_code == 302


def _start(client, boundary, choice="every", upload=None, steps=("parcels",)):
    _choose(client, boundary)
    data = {"steps": list(steps), "parcel_choice": choice}
    if upload is not None:
        data["parcel_list"] = upload
    return client.post(RUN_URL, data)


def _past_basins(client):
    """The first poll reports Groundwater Basins as unchecked; the parcel step is next."""
    assert "Skipped: you unchecked this step" in client.post(PROGRESS_URL).content.decode()


def _words(response):
    import re
    text = re.sub(r"<[^>]+>", "", response.content.decode())
    return " ".join(text.split()).replace("&#x27;", "'").replace("&rsquo;", "'")


# -- The pages before the run -------------------------------------------------------------


def test_the_confirm_page_names_the_map_and_the_acreage(client, boundary):
    _choose(client, boundary)
    page = _words(client.get(CONFIRM_URL))
    assert "DWR's California parcel map" in page
    assert "A use area and its acreage for each Assessor Parcel Number (APN)" in page
    assert "LightBox" not in page


def test_the_populate_page_offers_the_choice_the_list_and_the_california_line(client, boundary):
    _choose(client, boundary)
    page = _words(client.get(RUN_URL))
    assert "DWR's California parcel map" in page
    assert "Every parcel that overlaps the boundary" in page
    assert "Only the parcels on your list" in page
    assert "List of parcel numbers" in page
    assert ("Save your spreadsheet as a CSV file. OpenH2O reads the numbers from the column "
            "headed APN or Parcel number, or from the first column when no column has either "
            "heading. OpenH2O matches each number with or without its dashes.") in page
    assert CALIFORNIA_LINE in page
    assert reverse("parcels:use_area_import") in client.get(RUN_URL).content.decode()
    assert 'enctype="multipart/form-data"' in client.get(RUN_URL).content.decode()


def test_the_list_chosen_with_no_file_is_refused(client, boundary):
    page = _words(_start(client, boundary, choice="list"))
    assert ("Choose the file that lists your parcel numbers, or choose Every parcel that "
            "overlaps the boundary.") in page
    assert not PendingImport.objects.exists()


def test_a_refusal_keeps_the_steps_that_were_checked(client, boundary):
    # Seen on staging: after a refusal every step came back checked, so pressing Run
    # setup again would run steps the administrator had unchecked.
    html = _start(client, boundary, choice="list", steps=("parcels",)).content.decode()
    assert 'value="parcels" checked' in html
    for step in ("basins", "flowlines", "stations"):
        assert f'value="{step}" checked' not in html


def test_a_spreadsheet_is_refused_by_name(client, boundary):
    upload = SimpleUploadedFile("parcels.xlsx", b"PK\x03\x04binary")
    page = _words(_start(client, boundary, choice="list", upload=upload))
    assert "Save parcels.xlsx as a CSV file and choose the CSV file." in page


def test_a_file_with_no_numbers_is_refused_by_name(client, boundary):
    upload = SimpleUploadedFile("parcels.csv", b"APN\n\n")
    page = _words(_start(client, boundary, choice="list", upload=upload))
    assert ("OpenH2O did not find any parcel numbers in parcels.csv. Put the numbers in a "
            "column headed APN or Parcel number and choose the file again.") in page


# -- The step runs as its own process --------------------------------------------------------


def test_the_parcel_step_answers_at_once_then_shows_its_result(
        client, boundary, settings, django_capture_on_commit_callbacks):
    settings.OPENH2O_IMPORT_INLINE = False
    upload = SimpleUploadedFile("parcels.csv", b"APN\n000000000001\n000000000002\n900-000-001-000\n")
    assert _start(client, boundary, choice="list", upload=upload).status_code == 302
    _past_basins(client)

    with patch("core.pending_imports.subprocess.Popen") as popen:
        with django_capture_on_commit_callbacks(execute=True):
            first = client.post(PROGRESS_URL)
    assert popen.call_count == 1
    assert popen.call_args.args[0][-3:-1] == ["run_pending_import", "--token"]
    page = _words(first)
    assert "Finding the parcels that overlap the boundary…" in page
    assert "Populate skips records already on file, so running a step again is safe." in page
    assert LEAVE_LINE in page
    assert 'hx-trigger="load delay:2s"' in first.content.decode()
    pending = PendingImport.objects.get(kind="setup_parcels")
    assert pending.status == "waiting"
    assert Parcel.objects.count() == 0

    # Polling while the worker has not finished starts nothing new.
    with patch("core.pending_imports.subprocess.Popen") as popen:
        with django_capture_on_commit_callbacks(execute=True):
            client.post(PROGRESS_URL)
    assert popen.call_count == 0

    fake = FakeLightBox(count=1200)
    with patch("geography.services.arcgis.requests.post", side_effect=fake.post):
        pending_imports.run(str(pending.token))
    assert Parcel.objects.count() == 2

    done = _words(client.post(PROGRESS_URL))
    assert ("Your list holds 3 different parcel numbers. OpenH2O saved 2 of them as new use "
            "areas.") in done
    assert ("1 parcel number on your list does not match any parcel that overlaps the boundary: "
            "900-000-001-000.") in done
    assert not PendingImport.objects.exists()


def test_the_progress_line_counts_the_download(client, boundary, settings,
                                                django_capture_on_commit_callbacks):
    settings.OPENH2O_IMPORT_INLINE = False
    _start(client, boundary)
    _past_basins(client)
    with patch("core.pending_imports.subprocess.Popen"):
        with django_capture_on_commit_callbacks(execute=True):
            client.post(PROGRESS_URL)
    pending = PendingImport.objects.get(kind="setup_parcels")
    pending.status = "running"
    pending.result = {"done": 1000, "total": 2500, "saved": 1000,
                      "updated": timezone.now().isoformat()}
    pending.save()
    page = _words(client.post(PROGRESS_URL))
    assert "Downloading the parcels that overlap the boundary: 1,000 of 2,500" in page


def test_a_download_whose_process_went_quiet_is_reported_stopped(
        client, boundary, settings, django_capture_on_commit_callbacks):
    settings.OPENH2O_IMPORT_INLINE = False
    _start(client, boundary)
    _past_basins(client)
    with patch("core.pending_imports.subprocess.Popen"):
        with django_capture_on_commit_callbacks(execute=True):
            client.post(PROGRESS_URL)
    pending = PendingImport.objects.get(kind="setup_parcels")
    quiet = timezone.now() - datetime.timedelta(minutes=11)
    pending.status = "running"
    pending.result = {"done": 11000, "total": 57306, "saved": 11000, "updated": quiet.isoformat()}
    pending.save()
    response = client.post(PROGRESS_URL)
    page = _words(response)
    assert "The parcel download stopped after OpenH2O saved 11,000 new use areas." in page
    assert RERUN_LINES in page
    assert "wizard-step--error" in response.content.decode()
    assert not PendingImport.objects.exists()


def test_every_parcel_inline_shows_the_saved_count(client, boundary):
    _start(client, boundary)
    _past_basins(client)
    fake = FakeLightBox(count=1200)
    with patch("geography.services.arcgis.requests.post", side_effect=fake.post):
        client.post(PROGRESS_URL)
    page = _words(client.post(PROGRESS_URL))
    assert Parcel.objects.count() == 1200
    assert not Parcel.objects.filter(area_acres__isnull=True).exists()
    assert "OpenH2O saved 1,200 new use areas." in page
    assert fake.offset_calls == 0


def test_a_stop_shows_the_cause_and_the_way_to_add_the_rest(client, boundary):
    _start(client, boundary)
    _past_basins(client)
    fake = FakeLightBox(count=2500, short={2: "always"})
    with patch("geography.services.arcgis.requests.post", side_effect=fake.post):
        client.post(PROGRESS_URL)
    page = _words(client.post(PROGRESS_URL))
    assert Parcel.objects.count() == 1000
    assert "DWR's parcel map stopped responding after OpenH2O saved 1,000 new use areas." in page
    assert RERUN_LINES in page
    assert "Couldn't complete this step" not in page


def test_no_parcels_found_points_to_import_use_areas(client, boundary):
    _start(client, boundary)
    _past_basins(client)
    with patch("geography.services.arcgis.requests.post", side_effect=FakeLightBox(none_found=True).post):
        client.post(PROGRESS_URL)
    response = client.post(PROGRESS_URL)
    page = _words(response)
    assert ("DWR's parcel map has no parcels that overlap this boundary. The map covers "
            "California only. For land outside California, load your parcel outlines with "
            "Import use areas on the Use Areas page.") in page
    assert reverse("parcels:use_area_import") in response.content.decode()


def test_flowlines_runs_its_own_process_and_leaves_no_row(client, boundary):
    _start(client, boundary, steps=("flowlines",))
    _past_basins(client)
    from tests.lightbox_fake import _response
    with patch("geography.services.arcgis.requests.post",
               side_effect=lambda *a, **k: _response({"features": [], "count": 0})) as post:
        client.post(PROGRESS_URL)  # Parcel Boundaries, unchecked
        assert post.call_count == 0
        client.post(PROGRESS_URL)  # Flowlines: its process, run in this one by the suite
    assert post.call_count == 2  # USGS's count, then the one empty page
    assert not PendingImport.objects.exists()


def test_getting_started_says_the_map_covers_california_only(client):
    page = _words(client.get(reverse("getting_started")))
    assert ("The Setup Wizard downloads the parcels that overlap your boundary from the "
            "California Department of Water Resources' parcel map and saves each as a use area. "
            "The map covers California only. If you give the wizard a list of Assessor Parcel "
            "Numbers (APNs), it saves only the parcels on that list.") in page
