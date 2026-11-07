# SPDX-License-Identifier: AGPL-3.0-or-later
"""Void this record: the one view behind every row's menu, and the helpers the tables share.

``core:record_void`` (``/records/<kind>/<pk>/void/``) is HTMX end to end:

- GET opens the reason row under the record (the record's own row also takes
  ``row-editing`` and its actions cell is empty while the form is open);
  ``?cancel=1`` returns the table as it was.
- POST checks the reason, calls :func:`core.corrections.void`, starts the
  recalculation of the months the void moved (trigger ``record_voided``) and
  returns the table with the struck row and one sentence.

Which table comes back depends on the kind. Each page that lists a kind owns a
function that renders its table; :data:`TABLES` names it by dotted path, imported
on use, so a module that is switched off is never imported. That function takes
``(request, row, *, void_key, void_reason, void_error, notice, warning)`` and
puts the notice or warning in the slot its page already has. A kind whose menu
sits in a page header (a use area, a lab result) answers a good void with
``HX-Redirect`` to the record's page, and its function renders only the header
control.

``core:record_correct`` (``/records/<kind>/<pk>/correct/``) is the same shape for
Correct this record: GET opens the correction row under the record, POST checks the
form, the reason and the file, calls :func:`core.corrections.correct`, starts the
recalculation (trigger ``record_corrected``) and returns the table with the struck
row, the new row and the one-time response line. The table renderers need no new
argument: the view puts a :class:`CorrectState` where ``{% record_marks %}`` and
:func:`mark_actions` find it (:func:`correct_state`).

Inside a finalized water year only an administrator corrects or voids, and the view
opens ``accounting.locks.override(reason)`` with the person's own reason around the
write AND the recalculation it starts. Nothing else opens it.

:func:`mark_actions` and :func:`void_context` are for the table renderers: one
``finalized_ranges()`` per page, never a query per row.
"""

import re
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from dataclasses import dataclass, field
from decimal import Decimal

from django.contrib import messages
from django.db import DatabaseError, IntegrityError, transaction
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils.html import escape
from django.utils.module_loading import import_string
from django.views.decorators.http import require_http_methods

from core import correction_forms, corrections, record_attachments
from core.access import acting_may_override, may_override, read_only_response
from core.models import RecordAttachment
from core.modules import is_enabled
from core.reasons import check_reason

#: The function that renders the table a kind lives in. A kind missing here has no
#: screen that lists it (a recharge measurement), so it has no void screen either.
TABLES = {
    "meter_reading": "wells.views.render_measurement_history",
    "water_level": "wells.views.render_measurement_history",
    "ledger_entry": "accounting.views.ledger.render_ledger_results",
    "fallow_period": "parcels.views.render_fallow_row",
    "use_area": "parcels.views.render_use_area_menu",
    "diversion_record": "surface.views.render_diversion_records",
    "recharge_event": "recharge.views.render_event_history",
    "lab_result": "drinking.views.results.render_result_menu",
    "production_record": "drinking.views.production.render_production_table",
    "station_reading": "datasync.views.render_station_readings",
}

#: Kinds whose good void sends the browser to the record's page.
REDIRECTS = frozenset({"use_area", "lab_result"})

RECHARGE_EVENT_SENTENCE_ZONE = (
    "Event voided. OpenH2O removed any credit and took its volume out of the basin recharge pool."
)
RECHARGE_EVENT_SENTENCE_NO_ZONE = "Event voided. OpenH2O removed any credit."


@dataclass
class CorrectState:
    """What the table being drawn shows for Correct this record.

    ``key`` is the anchor of the record whose correction row is open, with its
    ``form`` and the sentences beside it; ``done_key`` and ``done_text`` are the
    one-time response line, drawn under the replaced record's own line.
    """

    key: str = ""
    form: object = None
    note: str = ""
    error: str = ""
    reason: str = ""
    reason_error: str = ""
    file_error: str = ""
    done_key: str = ""
    done_text: str = ""
    extra: dict = field(default_factory=dict)


_STATE = ContextVar("correct_state", default=None)


def correct_state():
    """The :class:`CorrectState` of the response being drawn, or None."""
    return _STATE.get()


@contextmanager
def _showing(state):
    token = _STATE.set(state)
    try:
        yield
    finally:
        _STATE.reset(token)


def mark_actions(rows, *, can_write, finalized, void_key=None, edit=False, edit_closes=False):
    """Give each row what its table needs to draw the menu: ``void_ok``, ``correct_ok``, ``menu_ok``, ``void_open``, ``correct_open``.

    ``finalized`` is the page's one :func:`core.corrections.finalized_ranges`.
    Whether the person may correct or void inside a finalized year is read from
    the request being served (:func:`core.access.acting_may_override`): an
    administrator's finalized rows get Correct this record and Void this record,
    an operator's and a viewer's get no menu. ``edit=True`` is for a table whose
    rows have Edit; ``edit_closes=True`` takes Edit away inside a finalized year
    (``row.edit_ok``). A struck row (voided or replaced), an engine row and a
    viewer's page get no menu; the row whose reason or correction form is open
    has an empty actions cell.
    """
    admin = acting_may_override()
    state = correct_state()
    correct_key = state.key if state is not None else ""
    for row in rows:
        kind_key = corrections.kind_for(row)["key"]
        key = corrections.anchor(kind_key, row)
        row.void_ok = bool(can_write and corrections.can_void(row, finalized, admin=admin))
        row.correct_ok = bool(
            can_write
            and correction_forms.has_screen(kind_key)
            and corrections.can_correct(row, finalized, admin=admin)
        )
        row.void_open = void_key is not None and key == void_key
        row.correct_open = bool(correct_key) and key == correct_key
        row.edit_ok = bool(
            edit
            and not (edit_closes and finalized and corrections._in_finalized(
                corrections.kind_for(row), row, finalized
            ))
        )
        row.menu_ok = bool(
            can_write
            and not row.is_struck
            and (row.void_ok or row.correct_ok or row.edit_ok)
            and not row.void_open
            and not row.correct_open
        )
    return rows


def void_context(void_key=None, void_reason="", void_error="", notice="", warning=""):
    """The context every table renderer adds for the void flow."""
    return {
        "void_key": void_key,
        "void_reason": void_reason,
        "void_error": void_error,
        "notice": notice,
        "warning": warning,
    }


def _door(reason, wanted):
    """The recorded door (``accounting.locks.override``) when ``wanted``, else nothing."""
    if not wanted:
        return nullcontext()
    from accounting.locks import override

    return override(reason)


def _renderer(kind_key):
    path = TABLES.get(kind_key)
    if path is None:
        raise Http404("This kind of record has no void screen.")
    return import_string(path)


def _recalculate(request, months, trigger="record_voided", reason=""):
    """Start the months a void or correction moved; return the months that were started.

    ``reason`` is the administrator's own, for a record inside a finalized year:
    the request then carries it and runs through the recorded override.
    """
    if not months or not is_enabled("accounting"):
        return []
    from accounting.engine_run import request_for_months

    started = request_for_months(trigger, months, requested_by=request.user, reason=reason)
    return sorted({m for r in started for m in r.months})


def _meter_follows(row):
    from measurements.models import MeterReading

    return (
        MeterReading.objects.current()
        .filter(meter_id=row.meter_id, reading_date__gt=row.reading_date)
        .exists()
    )


def _voided_sentence(request, kind_key, row, months, reason=""):
    if kind_key == "recharge_event":
        if row.recharge_site.zone is None:
            return RECHARGE_EVENT_SENTENCE_NO_ZONE
        return RECHARGE_EVENT_SENTENCE_ZONE
    parts = ["Record voided."]
    covered = _recalculate(request, months, "record_voided", reason)
    if covered:
        from accounting.engine_run import recalculated_months_sentence

        parts.append(recalculated_months_sentence(covered))
    if (
        kind_key == "meter_reading"
        and row.meter.meter_type == "totalizer"
        and _meter_follows(row)
    ):
        parts.append("OpenH2O also recalculated the next reading's pumped amount.")
    return " ".join(parts)


@require_http_methods(["GET", "POST"])
def record_void(request, kind, pk):
    """Open the reason row for a record (GET), or void it with the reason typed (POST)."""
    from django.contrib.auth.views import redirect_to_login

    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path())
    if not request.user.can_write:
        return read_only_response(request)
    try:
        spec = corrections.get_kind(kind)
    except KeyError:
        raise Http404("No such kind of record.") from None
    if not spec.enabled():
        raise Http404("This kind of record is not on this site.")
    render_table = _renderer(kind)
    row = get_object_or_404(spec.model_class(), pk=pk)

    if request.method == "GET":
        if not request.headers.get("HX-Request"):
            return redirect(spec["page_url"](row))
        if request.GET.get("cancel"):
            return render_table(request, row, **void_context())
        if not corrections.can_void(
            row, corrections.finalized_ranges(), admin=may_override(request.user)
        ):
            return render_table(request, row, **void_context(warning=_refusal_for(row)))
        return render_table(
            request, row, **void_context(void_key=corrections.anchor(kind, row))
        )

    from accounting.locks import PeriodFinalized

    # `inline` is sent by a Void button on a full-page edit form (the recharge event page):
    # a refusal prints in the form's own result slot and a good void sends the person to
    # the record's page, instead of swapping a table into a page that has none.
    inline = bool(request.POST.get("inline"))
    # The reason row sends void_reason; an edit form that shares its Reason box sends reason.
    typed = request.POST.get("void_reason", request.POST.get("reason", ""))
    reason, error = check_reason(typed)
    key = corrections.anchor(kind, row)

    def refuse(sentence, **context):
        if inline:
            return HttpResponse(f'<p class="record-void-error" role="alert">{escape(sentence)}</p>')
        return render_table(request, row, **void_context(**context))

    if error:
        return refuse(error, void_key=key, void_reason=typed, void_error=error)
    # Inside a finalized water year only an administrator voids, through the recorded
    # door with the reason just checked; the recalculation it starts runs inside it too.
    in_door = may_override(request.user) and corrections._in_finalized(
        spec, row, corrections.finalized_ranges()
    )
    try:
        with _door(reason, in_door):
            months = corrections.void(row, user=request.user, reason=reason)
            sentence = _voided_sentence(request, kind, row, months, reason if in_door else "")
    except (corrections.AlreadyVoided, corrections.AlreadyReplaced, corrections.NotVoidable) as exc:
        return refuse(str(exc), warning=str(exc))
    except PeriodFinalized as exc:
        sentence = f"Nothing was voided. {exc}"
        return refuse(sentence, warning=sentence)
    except ValueError as exc:
        return refuse(str(exc), void_key=key, void_reason=reason, void_error=str(exc))
    if kind in REDIRECTS or inline:
        messages.success(request, sentence)
        response = HttpResponse(status=204)
        response["HX-Redirect"] = spec["page_url"](row)
        return response
    return render_table(request, row, **void_context(notice=sentence))


def _refusal_for(row):
    """The sentence for a Void press on a row that cannot be voided now."""
    if row.voided_at is not None:
        return "This record is already voided."
    if row.replaced_at is not None:
        return corrections.ALREADY_REPLACED_SENTENCE
    kind = corrections.kind_for(row)
    if not kind["can_void"](row):
        return (
            f"OpenH2O calculated this {kind['label']}, so it cannot be voided. "
            "Void the record it came from."
        )
    from accounting.locks import PeriodFinalized, refuse_if_finalized

    day = kind["date_of"](row)
    if day is not None:
        try:
            refuse_if_finalized(day)
        except PeriodFinalized as exc:
            return f"Nothing was voided. {exc}"
    return "This record cannot be voided."


# -- Correct this record ------------------------------------------------------------------------

NOTHING_CHANGED = "Nothing was changed. Change a figure, or press Cancel."
CLASH = "That correction conflicts with a record already on file."


def _month_labels(months):
    import datetime as dt

    return [f"{dt.datetime.strptime(m, '%Y-%m'):%b %Y}" for m in sorted(months)]


def _where(months):
    labels = _month_labels(months)
    return labels[0] if len(labels) == 1 else ", ".join(labels[:-1]) + f" and {labels[-1]}"


def _finalized_note(kind, row):
    """The first line of the form in a finalized year: the year, and the months the save recalculates."""
    from accounting.locks import period_for

    day = kind["date_of"](row)
    period = period_for(day) if day is not None else None
    if period is None:
        return ""
    months = kind["months"](row) if is_enabled("accounting") else ()
    note = f"{period.name} is finalized."
    if months:
        note += f" Saving recalculates {_where(months)}."
    return note


def _correct_refusal_for(row, admin):
    """The sentence for a Correct press on a record that cannot be corrected now."""
    if row.voided_at is not None:
        return "This record is already voided."
    if corrections._is_replaced(row):
        return corrections.ALREADY_REPLACED_SENTENCE
    kind = corrections.kind_for(row)
    if not kind["can_correct"](row):
        return corrections._not_correctable_sentence(kind)
    from accounting.locks import period_for

    day = kind["date_of"](row)
    period = period_for(day) if day is not None else None
    if period is not None and period.is_finalized and not admin:
        return (
            f"Nothing was corrected. {period.name} is finalized. "
            "An administrator can correct or void a record in it."
        )
    return "This record cannot be corrected."


def _meter_volumes(row):
    """``{pk: (date, pumped)}`` of the current reads on the record's meter, before or after a correction."""
    from measurements.models import MeterReading

    return {
        r.pk: (r.reading_date, r.calculated_volume)
        for r in MeterReading.objects.current().filter(meter_id=row.meter_id)
    }


def _moved_pumped(before, after, new_pk):
    """The reads whose pumped amount a meter correction moved, as ``Apr 30 pumped is now 85.11``."""

    from django.utils import timezone

    moved = []
    for pk, (when, volume) in sorted(after.items(), key=lambda item: item[1][0]):
        if pk == new_pk or volume is None or pk not in before:
            continue
        if before[pk][1] != volume:
            day = timezone.localtime(when).date()
            moved.append(f"{day:%b} {day.day} pumped is now {Decimal(volume):,.2f}")
    return moved


def _nbsp(text):
    """Hold "Mar 2025", "Apr 30" and "now 85.11" together so a line does not break inside them."""
    text = re.sub(r"\b([A-Z][a-z]{2}) (\d{1,4})\b", "\\1\u00a0\\2", text)
    return re.sub(r"\bnow (-?[\d,]+\.\d+)", "now\u00a0\\1", text)


def _corrected_sentence(request, covered, moved):
    sentence = "Record corrected."
    parts = []
    if covered:
        parts.append(f"OpenH2O recalculated {_where(covered)}")
    parts.extend(moved)
    if parts:
        sentence += " " + "; ".join(parts) + "."
    return _nbsp(sentence)


def _show(request, render_table, row, state, **context):
    with _showing(state):
        return render_table(request, row, **void_context(**context))


@require_http_methods(["GET", "POST"])
def record_correct(request, kind, pk):
    """Open the correction row for a record (GET), or replace it with the corrected one (POST)."""
    from django.contrib.auth.views import redirect_to_login

    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path())
    if not request.user.can_write:
        return read_only_response(request)
    try:
        spec = corrections.get_kind(kind)
    except KeyError:
        raise Http404("No such kind of record.") from None
    if not spec.enabled() or not correction_forms.has_screen(kind):
        raise Http404("This kind of record has no correct screen.")
    render_table = _renderer(kind)
    row = get_object_or_404(spec.model_class(), pk=pk)
    key = corrections.anchor(kind, row)
    admin = may_override(request.user)
    finalized = corrections.finalized_ranges()
    in_final = corrections._in_finalized(spec, row, finalized)

    if request.method == "GET":
        if not request.headers.get("HX-Request"):
            return redirect(spec["page_url"](row))
        if request.GET.get("cancel"):
            return _show(request, render_table, row, None)
        if not corrections.can_correct(row, finalized, admin=admin):
            return _show(request, render_table, row, None, warning=_correct_refusal_for(row, admin))
        state = CorrectState(
            key=key, form=correction_forms.build(kind, row),
            note=_finalized_note(spec, row) if in_final else "",
        )
        return _show(request, render_table, row, state)

    from accounting.locks import PeriodFinalized, lock_error_message

    if not corrections.can_correct(row, finalized, admin=admin):
        sentence = _correct_refusal_for(row, admin)
        return _show(request, render_table, row, None, warning=sentence)

    reason, reason_error = check_reason(request.POST.get("reason", ""))
    uploaded = request.FILES.get("file")
    content_type, file_error = record_attachments.check_upload(uploaded) if uploaded else ("", "")
    in_door = in_final and admin
    note = _finalized_note(spec, row) if in_final else ""

    def reopen(form, error="", **more):
        state = CorrectState(
            key=key, form=form, note=note, error=error, reason=request.POST.get("reason", ""),
            reason_error=reason_error, file_error=file_error, **more,
        )
        return _show(request, render_table, row, state)

    # The form's own checks (a finalized date among them) stand aside inside the door, so
    # the form is checked inside it; nothing is written until the reason is good.
    with _door(reason or "Reason not given.", in_door):
        form = correction_forms.build(kind, row, request.POST)
        valid = form.is_valid()
        if not valid or reason_error or file_error:
            return reopen(form)
        changed = correction_forms.changes(kind, row, form)
        if not changed:
            return reopen(form, NOTHING_CHANGED)
        follow_before = _meter_volumes(row) if kind == "meter_reading" else {}
        try:
            with transaction.atomic():
                months = corrections.correct(row, user=request.user, reason=reason, changes=changed)
                new = type(row).objects.get(replaces=row)
                if uploaded:
                    record_attachments.store(
                        uploaded, content_type, kind=kind, record=new, user=request.user
                    )
                # A change of the estimate choice alone moves no figure, so nothing recalculates.
                covered = (
                    []
                    if set(changed) <= {"quality"}
                    else _recalculate(request, months, "record_corrected", reason if in_door else "")
                )
        except (corrections.AlreadyVoided, corrections.AlreadyReplaced, corrections.NotCorrectable) as exc:
            return _show(request, render_table, row, None, warning=str(exc))
        except PeriodFinalized as exc:
            return _show(request, render_table, row, None, warning=f"Nothing was corrected. {exc}")
        except ValueError as exc:
            return reopen(form, str(exc))
        except IntegrityError:
            return reopen(form, CLASH)
        except DatabaseError as exc:
            locked = lock_error_message(exc)
            if locked is None:
                raise
            return _show(request, render_table, row, None, warning=f"Nothing was corrected. {locked}")
        moved = (
            _moved_pumped(follow_before, _meter_volumes(new), new.pk)
            if kind == "meter_reading" else []
        )
    sentence = _corrected_sentence(request, covered, moved)
    if kind in REDIRECTS:
        messages.success(request, sentence)
        response = HttpResponse(status=204)
        response["HX-Redirect"] = spec["page_url"](new)
        return response
    return _show(request, render_table, row, CorrectState(done_key=key, done_text=sentence))


# -- The attached file ----------------------------------------------------------------------------


@require_http_methods(["GET"])
def record_attachment(request, pk):
    """Stream a correction's file to a signed-in user, under the name it was uploaded with."""
    from django.contrib.auth.views import redirect_to_login

    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path())
    attachment = get_object_or_404(RecordAttachment, pk=pk)
    path = record_attachments.path_of(attachment)
    if not path.is_file():
        raise Http404("The file is no longer stored.")
    return FileResponse(
        open(path, "rb"), content_type=attachment.content_type, filename=attachment.original_name
    )
