# SPDX-License-Identifier: AGPL-3.0-or-later
"""A data import whose process is gone, and a failure partway through a file.

The worker of a data import is a child of the web container: recreating the
container (a deploy during the import) or running out of memory ends it, and
the row stayed "running" while the page polled every two seconds for a day.
The status route now gives such a row the page's failure block once it has
been running longer than the Setup Wizard's ten minutes of silence, and
deletes its file.

The failure sentence says OpenH2O saved nothing from the file. Each of the
ten data kinds' commit now runs in one transaction, so that stays true when
something fails after rows were written (the lab import records the
regulating agency after its rows).
"""

import datetime as dt
from html import unescape
from pathlib import Path

import pytest
from django.urls import reverse
from django.utils import timezone

from core import pending_imports
from core.models import PendingImport
from drinking import importer as lab_importer
from drinking.models import SampleResult
from tests.test_large_imports_03 import (
    PAGES,
    UNEXPECTED,
    _import,
    _stored_files,
    _upload_through_preview,
    _UserFactory,
)


@pytest.fixture(autouse=True)
def media_root_and_inline_worker(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    settings.OPENH2O_IMPORT_INLINE = True


@pytest.fixture
def person(db):
    return _UserFactory()


@pytest.fixture
def client(person):
    from django.test import Client

    c = Client()
    c.force_login(person)
    return c


def _running(person, settings, minutes):
    folder = Path(settings.MEDIA_ROOT) / pending_imports.FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "gone.csv").write_text("PS Code,Sample Date,Analyte Name,Result\n")
    return PendingImport.objects.create(
        kind="lab_results", user=person, original_name="lab-results.csv", size_bytes=40,
        stored_path=f"{pending_imports.FOLDER}/gone.csv", status="running",
        started_at=timezone.now() - dt.timedelta(minutes=minutes),
    )


def _status(client, pending):
    return client.get(
        reverse("core:pending_import_status", args=[pending.token]), HTTP_HX_REQUEST="true"
    ).content.decode()


def test_a_running_import_whose_worker_is_gone_shows_as_failed(client, person, settings):
    pending = _running(person, settings, minutes=11)
    body = _status(client, pending)
    assert 'hx-trigger="every 2s"' not in body
    assert "var(--color-error)" in body
    assert not PendingImport.objects.filter(pk=pending.pk).exists()
    assert _stored_files(settings) == []


def test_a_running_import_inside_the_limit_still_waits(client, person, settings):
    pending = _running(person, settings, minutes=2)
    assert 'hx-trigger="every 2s"' in _status(client, pending)
    assert PendingImport.objects.filter(pk=pending.pk).exists()


def test_a_lab_import_that_fails_after_its_rows_saves_none(client, monkeypatch):
    page = next(p for p in PAGES if p.kind == "lab_results")
    token = _upload_through_preview(client, page, 12)

    def failing(*args, **kwargs):
        raise RuntimeError("synthetic failure after the rows")

    monkeypatch.setattr(lab_importer, "record_regulating_agency", failing)
    body = unescape(_import(client, page, token))
    assert UNEXPECTED in body
    assert SampleResult.objects.count() == 0
