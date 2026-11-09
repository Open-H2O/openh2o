# SPDX-License-Identifier: AGPL-3.0-or-later
"""One upload for a whole file, on every bulk import page.

A page used to carry every parsed row through the browser between the preview
and Import (a hidden ``rows_json`` field), which is why each page refused a
file over a few thousand rows and why the lab file, at about 20 MB of rows,
could not be posted back at all. Now the preview saves the upload once, under
``MEDIA_ROOT/imports/`` with a random name, and records it as a
:class:`core.models.PendingImport`. The page carries only that row's token and
the page's settings.

Import re-reads the stored file, so nothing the browser sends can change what
is written. The commit runs in its own process, the way a calculation does
(``accounting/engine_run.py`` ``start_calculation``): the Merced lab file takes
81 s on the staging server, past gunicorn's 60 s timeout. Import marks the row
waiting and starts ``manage.py run_pending_import --token <uuid>`` after the
request's transaction commits; the page then polls
``core:pending_import_status`` every 2 seconds. With
``settings.OPENH2O_IMPORT_INLINE`` true (the test suite) the worker runs in
this process instead, so a test never spawns one.

Every kind of upload is registered in :data:`KINDS` with the function that
commits it. The functions are named as dotted paths and resolved when called, so an optional module that is
switched off is never imported and a test can patch what they call.
"""
import json
import logging
import os
import subprocess
import sys
import uuid
from datetime import timedelta
from pathlib import Path
from typing import NamedTuple

import pghistory
from django.conf import settings
from django.core.files import File
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.utils.module_loading import import_string

from core.models import PendingImport

logger = logging.getLogger(__name__)

REFUSED = "This upload has expired or belongs to someone else. Upload the file again."
UNEXPECTED = (
    "An unexpected error stopped the import, and OpenH2O saved nothing from this file."
)

#: How long an upload waits for Import before cleanup removes it.
EXPIRY = timedelta(hours=24)

#: A preview lists at most this many of the file's rows, and every row with an
#: error up to ERROR_ROW_LIMIT, with a count of the rest.
PREVIEW_ROW_LIMIT = 200
ERROR_ROW_LIMIT = 500

#: The raw-upload ceiling every page keeps (the pages' parsers refuse a larger
#: file with their own sentence before reading it).
MAX_UPLOAD_BYTES = 25 * 1024 * 1024

FOLDER = "imports"


class Kind(NamedTuple):
    #: ``module:function`` taking a PendingImport, returning the context the
    #: result template renders (JSON-able once passed through to_jsonable).
    commit: str
    result_template: str
    commit_url_name: str
    #: The extensions the stored file may keep, lower-cased. The parsers read
    #: the original name, never the stored one.
    extensions: tuple


KINDS = {
    "water_rights": Kind(
        commit="surface.views:commit_stored_rights",
        result_template="surface/partials/_right_import_result.html",
        commit_url_name="surface:water_right_import_commit",
        extensions=(".csv",),
    ),
    "diversions": Kind(
        commit="surface.views:commit_stored_diversions",
        result_template="surface/partials/_diversion_import_result.html",
        commit_url_name="surface:diversion_import_commit",
        extensions=(".csv",),
    ),
    "lab_results": Kind(
        commit="drinking.views.lab_import:commit_stored_lab",
        result_template="drinking/partials/_import_result.html",
        commit_url_name="drinking:import_commit",
        extensions=(".csv", ".tab", ".txt"),
    ),
    "production": Kind(
        commit="drinking.views.production:commit_stored_production",
        result_template="drinking/partials/_production_import_result.html",
        commit_url_name="drinking:production_import_commit",
        extensions=(".csv",),
    ),
    "schedule": Kind(
        commit="drinking.views.schedule_import:commit_stored_schedule",
        result_template="drinking/partials/_schedule_import_result.html",
        commit_url_name="drinking:schedule_import_commit",
        extensions=(".csv",),
    ),
    "infrastructure": Kind(
        commit="infrastructure.views:commit_stored_infrastructure",
        result_template="infrastructure/partials/_import_result.html",
        commit_url_name="infrastructure:import_commit",
        extensions=(".csv", ".geojson", ".json", ".kml", ".zip"),
    ),
    "water_levels": Kind(
        commit="wells.water_level_import:commit_stored_water_levels",
        result_template="wells/partials/_water_level_import_result.html",
        commit_url_name="wells:water_level_import_commit",
        extensions=(".csv",),
    ),
    "use_areas": Kind(
        commit="parcels.use_area_import:commit_stored_use_areas",
        result_template="parcels/partials/_use_area_import_result.html",
        commit_url_name="parcels:use_area_import_commit",
        extensions=(".zip", ".kml", ".geojson", ".json"),
    ),
}


# ---------------------------------------------------------------------------
# Storing and finding an upload
# ---------------------------------------------------------------------------


def _path(pending):
    return Path(settings.MEDIA_ROOT) / pending.stored_path


def delete_file(pending):
    """Remove the stored file; a file already gone is fine."""
    _path(pending).unlink(missing_ok=True)


def discard(pending):
    """Remove an upload's file and its row."""
    delete_file(pending)
    pending.delete()


def stored_file(pending):
    """The stored file, opened for reading as an uploaded file would be.

    Raises FileNotFoundError when it is gone. Use it in a ``with`` block.
    """
    return File(open(_path(pending), "rb"), name=pending.original_name)


def save_upload(user, kind, uploaded, page_settings=None):
    """Save ``uploaded`` under a random name and record it. Returns the row."""
    extension = Path(uploaded.name).suffix.lower()
    if extension not in KINDS[kind].extensions:
        extension = ""
    relative = f"{FOLDER}/{uuid.uuid4().hex}{extension}"
    destination = Path(settings.MEDIA_ROOT) / relative
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        with open(destination, "wb") as handle:
            for chunk in uploaded.chunks():
                handle.write(chunk)
        return PendingImport.objects.create(
            kind=kind,
            user=user,
            original_name=uploaded.name[:255],
            size_bytes=uploaded.size,
            stored_path=relative,
            settings=page_settings or {},
        )
    except BaseException:
        destination.unlink(missing_ok=True)
        raise


def purge_expired(now=None):
    """Remove every upload older than EXPIRY, rows and files. Returns the count."""
    cutoff = (now or timezone.now()) - EXPIRY
    stale = list(PendingImport.objects.filter(created_at__lt=cutoff))
    for pending in stale:
        delete_file(pending)
    PendingImport.objects.filter(pk__in=[p.pk for p in stale]).delete()
    return len(stale)


def lookup(user, token, kind=None):
    """The person's own upload for ``token``, or None.

    None for a token that is missing, not a uuid, unknown, older than EXPIRY,
    another person's, or of another kind than ``kind``.
    """
    try:
        value = uuid.UUID(str(token))
    except (ValueError, AttributeError):
        return None
    pending = PendingImport.objects.filter(token=value, user=user).first()
    if pending is None or pending.created_at < timezone.now() - EXPIRY:
        return None
    if kind is not None and pending.kind != kind:
        return None
    return pending


def receive(request, kind, uploaded, parse):
    """Save a preview's upload and parse it from disk.

    ``parse`` takes the stored file (named as the person uploaded it) and
    returns whatever the page's parser returns. Raises the parser's
    ImportError after removing what was saved. A file over the size ceiling is
    handed to the parser unsaved, so the page's own sentence refuses it.
    Returns ``(pending, parsed)``.
    """
    purge_expired()
    if uploaded.size > MAX_UPLOAD_BYTES:
        parse(uploaded)
    pending = save_upload(request.user, kind, uploaded)
    try:
        with stored_file(pending) as handle:
            parsed = parse(handle)
    except BaseException:
        discard(pending)
        raise
    return pending, parsed


def previewed(request, kind):
    """The person's previewed upload named by the POSTed token, or None."""
    pending = lookup(request.user, request.POST.get("token", ""), kind)
    if pending is None or pending.status != "previewed":
        return None
    return pending


def refused(request, kind):
    """The page's own result block carrying the one refusal sentence."""
    return render(request, KINDS[kind].result_template, {"error": REFUSED})


# ---------------------------------------------------------------------------
# Row lists on a preview or a result
# ---------------------------------------------------------------------------


def cap_error_rows(rows):
    """``(rows to list, how many more there were)`` for a list of error rows."""
    return rows[:ERROR_ROW_LIMIT], max(len(rows) - ERROR_ROW_LIMIT, 0)


# ---------------------------------------------------------------------------
# Import: start the worker, run it, show the result
# ---------------------------------------------------------------------------


class _Encoder(DjangoJSONEncoder):
    def default(self, o):
        try:
            return super().default(o)
        except TypeError:
            return str(o)


def to_jsonable(value):
    """``value`` as plain JSON data: Decimals and dates become strings."""
    return json.loads(json.dumps(value, cls=_Encoder))


def start_import(request, kind, page_settings):
    """Press Import: start the commit and return the polling block.

    Refuses a token that is not the person's own previewed upload of this
    page's kind. A second press on an upload already started shows the same
    block and starts nothing.
    """
    pending = lookup(request.user, request.POST.get("token", ""), kind)
    if pending is None:
        return refused(request, kind)
    if pending.status == "previewed":
        pending.settings = page_settings
        pending.status = "waiting"
        pending.save(update_fields=["settings", "status"])
        token = str(pending.token)
        if getattr(settings, "OPENH2O_IMPORT_INLINE", False):
            run(token)
        else:
            transaction.on_commit(lambda: _launch(token))
    return _waiting(request, pending)


def _launch(token):
    """Start ``manage.py run_pending_import --token <uuid>`` in its own session."""
    try:
        subprocess.Popen(
            [sys.executable, "manage.py", "run_pending_import", "--token", token],
            cwd=settings.BASE_DIR,
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=os.environ,
        )
    except OSError:
        logger.exception("could not start the import worker for %s", token)
        pending = PendingImport.objects.filter(token=token).first()
        if pending is not None:
            _finish(pending, "failed", {"error": UNEXPECTED})


def _finish(pending, status, result):
    delete_file(pending)
    pending.status = status
    pending.result = result
    pending.finished_at = timezone.now()
    pending.save(update_fields=["status", "result", "finished_at"])


def run(token):
    """The worker: commit one waiting upload and store what the page shows.

    Opens the change-history context the web request would have (the person
    and the commit path), so every row it writes names who imported it. An
    administrator's detail goes to the log; the screen gets one sentence.
    """
    pending = PendingImport.objects.filter(token=token, status="waiting").first()
    if pending is None:
        return
    pending.status = "running"
    pending.started_at = timezone.now()
    pending.save(update_fields=["status", "started_at"])
    kind = KINDS[pending.kind]
    try:
        with pghistory.context(
            user=pending.user_id, url=reverse(kind.commit_url_name)
        ):
            result = import_string(kind.commit.replace(":", "."))(pending)
        outcome = ("finished", to_jsonable(result))
    except Exception:
        logger.exception("import of %s (%s) failed", pending.original_name, pending.kind)
        outcome = ("failed", {"error": UNEXPECTED})
    _finish(pending, *outcome)


def _waiting(request, pending):
    return render(
        request,
        "core/partials/_pending_import_status.html",
        {"token": pending.token, "file_name": pending.original_name},
    )


def status_response(request, token):
    """What the polling block gets back.

    Still running: the same polling block. Finished or failed: the page's own
    result block, rendered from the stored result, and the row is deleted so
    the result is shown once.
    """
    pending = lookup(request.user, token)
    if pending is None:
        return render(
            request, "core/partials/_pending_import_notice.html", {"error": REFUSED}
        )
    if pending.status in ("finished", "failed"):
        response = render(
            request, KINDS[pending.kind].result_template, pending.result
        )
        pending.delete()
        return response
    return _waiting(request, pending)
