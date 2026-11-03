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

:func:`mark_actions` and :func:`void_context` are for the table renderers: one
``finalized_ranges()`` per page, never a query per row.
"""

from django.contrib import messages
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils.html import escape
from django.utils.module_loading import import_string
from django.views.decorators.http import require_http_methods

from core import corrections
from core.access import read_only_response
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

RECHARGE_EVENT_SENTENCE = (
    "Event voided. Its credit and its entry in the basin recharge pool are removed."
)


def mark_actions(rows, *, can_write, finalized, void_key=None, edit=False):
    """Give each row what its table needs to draw the menu: ``void_ok``, ``menu_ok``, ``void_open``.

    ``finalized`` is the page's one :func:`core.corrections.finalized_ranges`.
    ``edit=True`` is for a table whose rows have Edit even inside a finalized year
    (recharge events): the menu then stays, holding Edit only. A voided row, an
    engine row and a viewer's page get no menu; the row whose reason form is open
    (``void_key`` is its ``record-<kind>-<pk>`` anchor) has an empty actions cell.
    """
    for row in rows:
        kind_key = corrections.kind_for(row)["key"]
        row.void_ok = bool(can_write and corrections.can_void(row, finalized))
        row.void_open = void_key is not None and corrections.anchor(kind_key, row) == void_key
        row.menu_ok = bool(
            can_write and row.voided_at is None and (row.void_ok or edit) and not row.void_open
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


def _renderer(kind_key):
    path = TABLES.get(kind_key)
    if path is None:
        raise Http404("This kind of record has no void screen.")
    return import_string(path)


def _recalculate(request, months, kind_key):
    """Start the months the void moved; return the sentence naming them, or ``""``."""
    if not months or not is_enabled("accounting"):
        return ""
    from accounting.engine_run import recalculated_months_sentence, request_for_months

    started = request_for_months("record_voided", months, requested_by=request.user)
    covered = sorted({m for r in started for m in r.months})
    return recalculated_months_sentence(covered) if covered else ""


def _meter_follows(row):
    from measurements.models import MeterReading

    return (
        MeterReading.objects.current()
        .filter(meter_id=row.meter_id, reading_date__gt=row.reading_date)
        .exists()
    )


def _voided_sentence(request, kind_key, row, months):
    if kind_key == "recharge_event":
        return RECHARGE_EVENT_SENTENCE
    parts = ["Record voided."]
    line = _recalculate(request, months, kind_key)
    if line:
        parts.append(line)
    if kind_key == "meter_reading" and _meter_follows(row):
        parts.append("The next reading's pumped amount is figured again from the last reading still in use.")
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
        if not corrections.can_void(row, corrections.finalized_ranges()):
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
    try:
        months = corrections.void(row, user=request.user, reason=reason)
    except (corrections.AlreadyVoided, corrections.NotVoidable) as exc:
        return refuse(str(exc), warning=str(exc))
    except PeriodFinalized as exc:
        sentence = f"Nothing was voided. {exc}"
        return refuse(sentence, warning=sentence)
    except ValueError as exc:
        return refuse(str(exc), void_key=key, void_reason=reason, void_error=str(exc))
    sentence = _voided_sentence(request, kind, row, months)
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
    kind = corrections.kind_for(row)
    if not kind["can_void"](row):
        return (
            f"This {kind['label']} was written by OpenH2O's own calculation "
            "and cannot be voided. Void the record it came from."
        )
    from accounting.locks import PeriodFinalized, refuse_if_finalized

    day = kind["date_of"](row)
    if day is not None:
        try:
            refuse_if_finalized(day)
        except PeriodFinalized as exc:
            return f"Nothing was voided. {exc}"
    return "This record cannot be voided."
