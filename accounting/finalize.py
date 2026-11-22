# SPDX-License-Identifier: AGPL-3.0-or-later
"""Finalizing a water year, in its own process.

Finalize water year writes down every figure the year prints (``take_statement``),
marks the year finalized and takes its fingerprint. At 8,906 use areas that takes
about 77 s, past gunicorn's 60 s, so the button saves a ``finalize`` pending import
and starts ``manage.py run_pending_import`` (``core/pending_imports.py``), the way an
import's commit runs. :func:`run_stored_finalize` is that process's work: one
transaction holding the year's row, so a failure keeps nothing and the year stays
open. The change history names the person who pressed the button, the button's own
address and the note, as the request's context did.

The water year page reads :func:`state`: a finalize import that is waiting or running
shows as running; one that failed shows the stopped words until the next press. A
process that died leaves its row waiting or running with nobody holding the year's
row; once the row is older than :data:`STOPPED_AFTER` and the page can take the year's
lock without waiting, the page marks the import failed.
"""
from datetime import timedelta

from django.db import DatabaseError, transaction
from django.urls import reverse
from django.utils import timezone

from accounting import fingerprints
from accounting.models import ReportingPeriod
from accounting.statements import newest_statement, take_statement
from core import pending_imports
from core.history import change_note
from core.models import PendingImport

KIND = "finalize"

#: A run younger than this is never called stopped: its process may not have taken the
#: year's row yet (starting ``manage.py`` takes a few seconds).
STOPPED_AFTER = timedelta(minutes=1)

ACTIVE = ("waiting", "running")


#: The Finalize card names this many use areas per waiting month, then counts the rest
#: (the Site Health card's pattern).
NAMED = 5


def waiting(period):
    """The year's months waiting for OpenET, oldest first, each with its use areas by number.

    ``{"months": [{"month": first, "use_areas": [the first NAMED, by number], "more": the rest
    counted}], "use_areas": how many use areas wait}``; no months when nothing waits (a use area
    in no OpenET field, a month not ended, datasync off: ``YearReading.waiting``).
    """
    return waiting_in([period])


def waiting_in(periods):
    """:func:`waiting` over several periods (a water year in more than one), each use area once."""
    from accounting.year_reading import YearReading
    from parcels.models import Parcel

    found = {}
    for period in periods:
        for pid, months in YearReading(period).waiting.items():
            found.setdefault(pid, set()).update(months)
    if not found:
        return {"months": [], "use_areas": 0}
    numbers = dict(Parcel.objects.current().filter(pk__in=list(found)).values_list("pk", "parcel_number"))
    by_month = {}
    for pid, months in found.items():
        for month in months:
            by_month.setdefault(month, []).append(pid)
    months = []
    for month in sorted(by_month):
        ids = sorted(by_month[month], key=lambda pid: numbers.get(pid, ""))
        months.append({
            "month": month,
            "use_areas": [{"pk": pid, "number": numbers.get(pid, "")} for pid in ids[:NAMED]],
            "more": max(len(ids) - NAMED, 0),
        })
    return {"months": months, "use_areas": len(found)}


def month_line(entry):
    """One waiting month's line (ruling 215, row A2): ``September 2026: A, B and 71 more use areas``."""
    names = [area["number"] for area in entry["use_areas"]]
    more = entry["more"]
    if more:
        listed = f"{', '.join(names)} and {more} more use area{'' if more == 1 else 's'}"
    elif len(names) > 1:
        listed = f"{', '.join(names[:-1])} and {names[-1]}"
    else:
        listed = "".join(names)
    return f"{entry['month']:%B %Y}: {listed}."


def note_for(found):
    """The note OpenH2O records when a year is finalized anyway (ruling 215, row C1)."""
    return " ".join(["Finalized with months waiting for OpenET."] + [month_line(m) for m in found["months"]])


def _rows(period):
    return PendingImport.objects.filter(kind=KIND, settings__period=period.pk)


def start(request, period, note):
    """Press Finalize water year: start one run, or none while one is waiting or running.

    Returns the started row, or None when a run was already under way.
    """
    if state(period)["state"] == "running":
        return None
    _rows(period).delete()  # a stopped run's words go when the next one starts
    pending = PendingImport.objects.create(
        kind=KIND,
        user=request.user,
        original_name="",
        stored_path="",
        status="waiting",
        settings={
            "period": period.pk,
            "note": note or "",
            "url": reverse("accounting:period_finalize", args=[period.pk]),
        },
    )
    pending_imports.start(str(pending.token))
    return pending


def run_stored_finalize(pending):
    """The process's work: :func:`finalize_year` with the stored user and note."""
    return finalize_year(pending.settings["period"], pending.user, pending.settings.get("note"))


def finalize_year(period, user, note=""):
    """Statement, finalized mark and fingerprint of ``period`` (a row or its pk), in one transaction."""
    pk = getattr(period, "pk", period)
    with change_note(note), transaction.atomic():
        # Held until the commit, so two runs cannot each write a statement; the
        # second finds the year already finalized.
        period = ReportingPeriod.objects.select_for_update().get(pk=pk)
        if period.is_finalized:
            return {"outcome": "already"}
        take_statement(period, kind="restated" if newest_statement(period) else "filed", user=user)
        period.is_finalized = True
        period.finalized_at = timezone.now()
        period.finalized_by = user
        # After the statement, in the same note and transaction, with the row held.
        fingerprints.take_fingerprint(period)
        period.save()
    return {"outcome": "finalized"}


def _year_is_held(period):
    """Whether another connection holds the year's row (a finalize process writing)."""
    try:
        with transaction.atomic():
            ReportingPeriod.objects.select_for_update(nowait=True).filter(pk=period.pk).exists()
    except DatabaseError:
        return True
    return False


def state(period):
    """What the Finalize card shows: ``{"state": "running", "since": ...}``,
    ``{"state": "stopped"}`` or ``{"state": None}``.

    A row left behind on a finalized year (its process ended after the commit) is
    removed; so is a finished one. A waiting or running row whose process is gone is
    marked failed here.
    """
    rows = list(_rows(period).order_by("-created_at"))
    if period.is_finalized or not rows:
        if rows:
            _rows(period).delete()
        return {"state": None}
    latest = rows[0]
    if latest.status in ACTIVE:
        begun = latest.started_at or latest.created_at
        if timezone.now() - begun < STOPPED_AFTER or _year_is_held(period):
            return {"state": "running", "since": latest.created_at}
        latest.status = "failed"
        latest.finished_at = timezone.now()
        latest.save(update_fields=["status", "finished_at"])
    if latest.status == "failed":
        return {"state": "stopped"}
    _rows(period).delete()
    return {"state": None}
