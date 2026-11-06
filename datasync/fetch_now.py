# SPDX-License-Identifier: AGPL-3.0-or-later
"""Update readings now: one station's fetch, started from its page.

The button on a station's page creates a ``DataSyncLog`` row for that station
and starts ``manage.py sync_source <code> --station <pk> --log <pk>`` in its own
process and session, after the surrounding transaction commits. The page polls a
small status route every 2 seconds and shows what the run got. This is the
pattern of ``accounting/engine_run.py`` ``start_calculation`` and of the bulk
import's polling block (``core/pending_imports.py``): no Celery, no Redis, and
the worker outlives the gunicorn worker that started it, which is killed at 60
seconds.

With ``settings.OPENH2O_FETCH_INLINE`` true (the test suite) the fetch runs in
this process instead, so a test never spawns one.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from datetime import timedelta
from io import StringIO

from django.conf import settings
from django.core.management import call_command
from django.db import transaction
from django.db.models import Max
from django.template.defaultfilters import date as date_filter
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html

from datasync import freshness
from datasync.adapters import get_adapter
from datasync.models import DataRecordStaging, DataSyncLog, MonitoredStation

logger = logging.getLogger(__name__)

#: A "running" log older than this no longer counts as running, so a worker that
#: was killed cannot block the button for good. The same limit is the age at
#: which a scheduled sync may close a station's still-running log as orphaned.
RUNNING_LIMIT = timedelta(minutes=10)

#: What the page says when the process could not be started at all.
COULD_NOT_START = "OpenH2O could not start the update. Try again."


def can_fetch(station) -> bool:
    """Whether the station's page offers the button at all.

    The source is switched on, has an adapter, is not the one whose readings are
    typed by hand, and is not missing a key it needs. The writer check is the
    caller's: a Viewer never sees the button.
    """
    source = station.data_source
    if not source.is_active or source.is_manual:
        return False
    adapter = get_adapter(source.code)
    if adapter is None:
        return False
    return adapter.missing_required_credential() is None


def running_log(station):
    """The station's fetch that is still running and inside the limit, else None."""
    return (
        DataSyncLog.objects.filter(
            station=station,
            status="running",
            started_at__gt=timezone.now() - RUNNING_LIMIT,
        )
        .order_by("-started_at")
        .first()
    )


def close_log(log, message):
    """Close a log as failed with ``message``."""
    now = timezone.now()
    log.status = "failed"
    log.error_message = message
    log.completed_at = now
    log.duration_seconds = (now - log.started_at).total_seconds()
    log.save()


def start_fetch(station):
    """Start a fetch for ``station``. Returns ``(log, started)``.

    A run already going for this station is returned with ``started`` False and
    nothing is created or started. The station's row is locked while the check
    and the insert happen, so two presses at once cannot both start.
    """
    with transaction.atomic():
        MonitoredStation.objects.select_for_update().get(pk=station.pk)
        existing = running_log(station)
        if existing is not None:
            return existing, False
        log = DataSyncLog.objects.create(
            data_source=station.data_source, station=station, status="running"
        )
        if not getattr(settings, "OPENH2O_FETCH_INLINE", False):
            transaction.on_commit(lambda: _launch(station, log))
    if getattr(settings, "OPENH2O_FETCH_INLINE", False):
        _run_here(station, log)
        log.refresh_from_db()
    return log, True


def _arguments(station, log):
    return [
        "sync_source", station.data_source.code,
        "--station", str(int(station.pk)), "--log", str(int(log.pk)),
    ]


def _launch(station, log):
    """Start ``manage.py sync_source`` in its own session. The only input is two integers."""
    try:
        subprocess.Popen(
            [sys.executable, "manage.py", *_arguments(station, log)],
            cwd=settings.BASE_DIR,
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=os.environ,
        )
    except OSError:
        logger.exception("could not start the fetch for %s", station)
        log.refresh_from_db()
        close_log(log, COULD_NOT_START)


def _run_here(station, log):
    try:
        call_command(*_arguments(station, log), stdout=StringIO())
    except Exception as exc:  # the log is the report; the page shows its message
        logger.exception("fetch for %s failed", station)
        log.refresh_from_db()
        if log.status == "running":
            close_log(log, str(exc) or COULD_NOT_START)


# -- What the page shows ---------------------------------------------------------------


def _plural(count, word):
    return f"{count:,} {word}{'' if count == 1 else 's'}"


def outcome(station, log):
    """``(message, is_error)`` for a finished log, or ``(None, False)`` while it has none to give.

    A run still going, or one past the limit that never finished, has nothing to
    say yet. A run that worked says how many new and revised readings the source
    sent, in the source's short name (``freshness.source_display``);
    the revised count links to the list of revised readings. Only that link is
    markup: the counts and the address are the only inputs to it.
    """
    name = station.data_source.name
    if log.status == "running":
        return None, False
    if log.status == "success":
        source = freshness.source_display(station.data_source.code)
        new, revised = log.records_new, log.records_revised
        newest = (
            DataRecordStaging.objects.current()
            .filter(station=station, status="published")
            .aggregate(newest=Max("observation_date"))["newest"]
        )
        when = date_filter(newest, "M j, Y") if newest is not None else None
        link = format_html(
            '<a href="{}" class="prose-link">{}</a>',
            reverse("datasync:station_revised", args=[station.pk]),
            _plural(revised, "revised reading"),
        )
        if new and revised:
            lead = format_html("{} sent {} and {}.", source, _plural(new, "new reading"), link)
        elif new:
            lead = format_html("{} sent {}.", source, _plural(new, "new reading"))
        elif revised:
            lead = format_html("{} sent {}.", source, link)
        else:
            lead = f"{source} did not send any new or revised readings."
        still = "" if new else "still "
        tail = f" The latest reading is {still}dated {when}." if when else ""
        return format_html("{}{}", lead, tail), False
    # Failed or partial: the log's own message. A connection error or timeout
    # was worded as "<source> did not answer." when the run closed (sync_source).
    return log.error_message or f"{name} did not answer.", True


def block_context(station, *, log=None, notice=None):
    """The context ``datasync/partials/_fetch_now.html`` renders with.

    ``log`` is the run the block reports on. A running one puts the block in its
    fetching state; a finished one gives the sentence under the row. ``notice``
    is a sentence of the view's own (a second press while a run is going) shown
    under the row in the same place.
    """
    from datasync import schedule

    context = {
        "station": station,
        "fetch_schedule_sentence": schedule.station_sentence(station),
        "fetch_available": can_fetch(station),
        "fetch_log": None,
        "fetch_message": notice,
        "fetch_message_is_error": False,
    }
    if log is None:
        context["fetch_log"] = running_log(station)
    elif log.status == "running":
        if log.started_at > timezone.now() - RUNNING_LIMIT:
            context["fetch_log"] = log
    else:
        message, is_error = outcome(station, log)
        context["fetch_message"] = message
        context["fetch_message_is_error"] = is_error
    return context
