# SPDX-License-Identifier: AGPL-3.0-or-later
"""One upload for a whole file, on every bulk import page, and other work longer than a request.

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

The same row and runner also carry work with no file that outlasts a request:
finalizing a water year (``accounting/finalize.py``) and the Setup Wizard's parcel,
stream and station steps (``setup/services.py``). Their pages read the row
themselves.

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

def stopped_sentence(file_name):
    """The failure words of a data import still running STOPPED_AFTER its start."""
    return (
        f"The import of {file_name} had not finished ten minutes after it started, for example "
        "because the site restarted during it, so OpenH2O marked it as failed and deleted the "
        "upload. OpenH2O saved nothing from this file and keeps nothing from it, even if the "
        "import was still running and finishes after this message. Upload the file again."
    )

#: How long an upload waits for Import before cleanup removes it.
EXPIRY = timedelta(hours=24)

#: A data import still running this long after it started is taken as stopped:
#: its worker is a child of the web container, which a deploy or a server out of
#: memory ends. The Setup Wizard's ten minutes of silence (setup/services.py).
STOPPED_AFTER = timedelta(minutes=10)

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
    # The Setup Wizard's parcel download (setup/services.py). Its stored file is
    # the district's own list of parcel numbers, or none for every parcel; the
    # wizard's progress partial reads the row itself, so result_template is only
    # what the import pages' status route would show.
    "setup_parcels": Kind(
        commit="setup.services:run_stored_parcel_download",
        result_template="setup/partials/_parcel_download_status.html",
        commit_url_name="setup:run",
        extensions=(".csv", ".txt"),
    ),
    # Import zones on the Zones page: one zone for each name in a map file.
    "zones": Kind(
        commit="geography.zone_import:commit_stored_zones",
        result_template="geography/partials/_zone_import_result.html",
        commit_url_name="geography:zone_import_commit",
        extensions=(".zip", ".kml", ".geojson", ".json"),
    ),
    # Finalize water year on the water year page (accounting/finalize.py). It has no
    # file; the page reads the row itself, and its history context's address comes
    # from the row (settings["url"]), because the button's address names the year.
    "finalize": Kind(
        commit="accounting.finalize:run_stored_finalize",
        result_template="core/partials/_pending_import_notice.html",
        commit_url_name="accounting:periods_list",
        extensions=(),
    ),
    # The Setup Wizard's stream and station steps (setup/services.py), read by the
    # wizard's own progress partial like the parcel download.
    "setup_flowlines": Kind(
        commit="setup.services:run_stored_flowlines",
        result_template="setup/partials/_parcel_download_status.html",
        commit_url_name="setup:run",
        extensions=(),
    ),
    "setup_stations": Kind(
        commit="setup.services:run_stored_stations",
        result_template="setup/partials/_parcel_download_status.html",
        commit_url_name="setup:run",
        extensions=(),
    ),
    # Import accounts on the Accounts page: accounts and the use areas in each.
    "accounts": Kind(
        commit="accounting.account_import:commit_stored_accounts",
        result_template="accounting/partials/_account_import_result.html",
        commit_url_name="accounting:account_import_commit",
        extensions=(".csv", ".txt"),
    ),
}

#: The kinds whose commit runs in one transaction, so a failure, or a worker
#: taken as stopped, saves nothing from the file. The parcel download, the
#: stream and station steps and Finalize keep partial progress on purpose and
#: have their own stopped-process rules.
DATA_KINDS = frozenset({
    "water_rights", "diversions", "lab_results", "production", "schedule",
    "infrastructure", "water_levels", "use_areas", "zones", "accounts",
})


class _Stopped(Exception):
    """The status route took this import as stopped while it ran: keep nothing."""


# ---------------------------------------------------------------------------
# Storing and finding an upload
# ---------------------------------------------------------------------------


def _path(pending):
    return Path(settings.MEDIA_ROOT) / pending.stored_path


def delete_file(pending):
    """Remove the stored file; a file already gone, or a row with none, is fine."""
    if not pending.stored_path:
        return
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
        start(str(pending.token))
    return _waiting(request, pending)


def start(token):
    """Start the worker for a waiting row: in this process under OPENH2O_IMPORT_INLINE
    (the test suite), else as its own process once the request commits."""
    if getattr(settings, "OPENH2O_IMPORT_INLINE", False):
        run(token)
    else:
        transaction.on_commit(lambda: _launch(token))


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
    # Claimed in one UPDATE, so two launches for one token cannot both run it.
    claimed = PendingImport.objects.filter(token=token, status="waiting").update(
        status="running", started_at=timezone.now()
    )
    if not claimed:
        return
    pending = PendingImport.objects.get(token=token)
    kind = KINDS[pending.kind]
    url = (pending.settings or {}).get("url") or reverse(kind.commit_url_name)
    commit = import_string(kind.commit.replace(":", "."))
    if pending.kind not in DATA_KINDS:
        try:
            with pghistory.context(user=pending.user_id, url=url):
                result = commit(pending)
            outcome = ("finished", to_jsonable(result))
        except Exception:
            logger.exception("import of %s (%s) failed", pending.original_name, pending.kind)
            outcome = ("failed", {"error": UNEXPECTED})
        _finish(pending, *outcome)
        return
    # A data import: its rows and its finished row are saved together, or nothing is.
    try:
        with transaction.atomic(), pghistory.context(user=pending.user_id, url=url):
            result = to_jsonable(commit(pending))
            # The status route may have taken it as stopped meanwhile and told
            # the person nothing was saved. This UPDATE holds the row until the
            # transaction ends, so the route's own conditional UPDATE waits for it.
            still = PendingImport.objects.filter(pk=pending.pk, status="running").update(
                status="finished", result=result, finished_at=timezone.now()
            )
            if not still:
                raise _Stopped
    except _Stopped:
        logger.warning("import of %s (%s) finished after it was taken as stopped; nothing kept",
                       pending.original_name, pending.kind)
        delete_file(pending)
        return
    except Exception:
        logger.exception("import of %s (%s) failed", pending.original_name, pending.kind)
        _finish(pending, "failed", {"error": UNEXPECTED})
        return
    delete_file(pending)


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
    the result is shown once. A data import still running STOPPED_AFTER its
    start is failed here with stopped_sentence; its worker, if alive, then keeps nothing.
    """
    pending = lookup(request.user, token)
    if pending is None:
        return render(
            request, "core/partials/_pending_import_notice.html", {"error": REFUSED}
        )
    if (
        pending.kind in DATA_KINDS
        and pending.status == "running"
        and pending.started_at is not None
        and pending.started_at < timezone.now() - STOPPED_AFTER
    ):
        # Conditional, so an import that finished in the meantime keeps its result.
        if PendingImport.objects.filter(pk=pending.pk, status="running").update(
            status="failed", result={"error": stopped_sentence(pending.original_name)},
            finished_at=timezone.now(),
        ):
            delete_file(pending)
        pending.refresh_from_db()
    if pending.status in ("finished", "failed"):
        response = render(
            request, KINDS[pending.kind].result_template, pending.result
        )
        pending.delete()
        return response
    return _waiting(request, pending)


# ---------------------------------------------------------------------------
# Words a bulk action's preview shares
# ---------------------------------------------------------------------------


def finalized_sentences(names, what):
    """The finalized-year lines above a bulk action's button, one a finalized year
    (``what`` names the change: "these assignments change", "this import changes")."""
    return [
        f"{name} is finalized. Its pages keep its figures as filed and show beside them any figure {what}."
        for name in names
    ]
