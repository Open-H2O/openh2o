# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Setup wizard views.

3-step flow:
  /setup/              → Step 1: Select or upload boundary
  /setup/confirm/      → Step 2: Review boundary on map
  /setup/run/          → Step 3: Progress page (triggers HTMX polling)
  /setup/progress/     → HTMX endpoint: run one step at a time
"""

import json
import logging

from django.contrib import messages
from django.core.management.base import CommandError
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from core import demonstration, pending_imports
from core.access import admin_required, is_administrator
from core.models import PendingImport
from core.modules import is_enabled
from datasync.models import MonitoredStation
from geography.models import Boundary
from core.geofiles import NOT_GEOJSON_MESSAGE
from setup.boundaries import (
    boundary_from_extent,
    boundary_from_upload,
    parse_extent_bounds,
)
from parcels.parcel_list import ParcelListError, read_parcel_list
from setup.services import (
    STATION_PROVIDERS,
    build_station_review,
    flowlines_result_row,
    get_boundary_preview_data,
    parcel_download_quiet,
    parcel_result_row,
    run_auto_populate_step,
    station_provider_label,
    stations_stopped_row,
    step_quiet,
    wizard_steps,
)

logger = logging.getLogger(__name__)

SESSION_KEY_BOUNDARY = "setup_wizard_boundary_id"
SESSION_KEY_STEP_INDEX = "setup_wizard_step_index"
SESSION_KEY_RESULTS = "setup_wizard_results"
SESSION_KEY_PROVIDER_INDEX = "setup_wizard_provider_index"
# Which populate steps this run was told to execute. Absent (not merely
# empty) means "step 3 has not asked yet"; that is how setup_run decides
# whether to show the picker or the HTMX progress poll, and how a fresh
# confirm() always re-asks rather than silently re-running the last choice.
SESSION_KEY_SELECTED_STEPS = "setup_wizard_selected_steps"
# How many polygons an uploaded file's boundary combined. Set
# by an upload, removed by a select or a typed extent, so the confirm step only
# says "N polygons combined" about the file that was just read.
SESSION_KEY_POLYGON_COUNT = "setup_wizard_polygon_count"
# The token of this run's parcel download (a ``setup_parcels`` PendingImport):
# set when Run setup is pressed with Parcel Boundaries checked, read by each
# progress poll while the download runs in its own process.
SESSION_KEY_PARCEL_TOKEN = "setup_wizard_parcel_token"
PARCEL_KIND = "setup_parcels"
# The token of the Flowlines or Monitoring Stations step running in its own process
# (a ``setup_flowlines`` or ``setup_stations`` PendingImport), read by each poll.
SESSION_KEY_STEP_TOKEN = "setup_wizard_step_token"
STEP_KINDS = {"flowlines": "setup_flowlines", "stations": "setup_stations"}
PARCEL_NO_FILE = (
    "Choose the file that lists your parcel numbers, or choose Every parcel that "
    "overlaps the boundary."
)

# The upload card's refusals that name the three formats.
# A file that is not text or not JSON reuses the GeoJSON sentence.
UPLOAD_NO_FILE = "Choose a boundary file to upload."
UPLOAD_NOT_TEXT = NOT_GEOJSON_MESSAGE
UPLOAD_NOT_JSON = NOT_GEOJSON_MESSAGE

# The step list is resolved per request via `wizard_steps()`, not frozen into a
# module constant: `datasync` is demotable, and a deployment that
# switched it off must not be walked through a Monitoring Stations step. The
# views index into the list by position, so one stale copy would run the wrong
# step rather than merely showing an extra label.

# Plain-language note shown for a provider's clean (non-failure) skip outcomes.
# created/timed_out/failed are NOT here — they render via count / the error row.
PROVIDER_SKIP_NOTES = {
    "skipped_no_key": "Skipped: no API key configured. You can add one later.",
    "skipped_no_source": "Skipped: this data source is not configured.",
    "skipped_no_adapter": "Skipped: no connector available for this provider.",
}


@admin_required
@login_required
def setup_wizard(request):
    """Step 1: Boundary selection: select existing, upload a map file, or type an extent."""
    errors = []

    if request.method == "POST":
        action = request.POST.get("action", "")

        if action == "select":
            boundary_id = request.POST.get("boundary_id", "").strip()
            if not boundary_id:
                errors.append("Please select a boundary.")
            else:
                try:
                    boundary = Boundary.objects.get(pk=int(boundary_id))
                    request.session[SESSION_KEY_BOUNDARY] = boundary.pk
                    request.session.pop(SESSION_KEY_POLYGON_COUNT, None)
                    return redirect("setup:confirm")
                except (Boundary.DoesNotExist, ValueError):
                    errors.append("Selected boundary does not exist.")

        elif action == "upload":
            # The input keeps its old name, geojson_file; it now takes a
            # zipped shapefile, a KML or a GeoJSON file.
            uploaded = request.FILES.get("geojson_file")
            if not uploaded:
                errors.append(UPLOAD_NO_FILE)
            else:
                try:
                    name, geom, attrs, polygon_count = boundary_from_upload(
                        uploaded,
                        fallback_name=uploaded.name.rsplit(".", 1)[0],
                    )
                    boundary = Boundary.objects.create(
                        name=name,
                        geometry=geom,
                        **attrs,
                    )
                    request.session[SESSION_KEY_BOUNDARY] = boundary.pk
                    request.session[SESSION_KEY_POLYGON_COUNT] = polygon_count
                    return redirect("setup:confirm")
                except UnicodeDecodeError:
                    errors.append(UPLOAD_NOT_TEXT)
                except json.JSONDecodeError:
                    errors.append(UPLOAD_NOT_JSON)
                except (ValueError, ImportError) as exc:
                    # A plain-language reason: parse_geojson_boundary's for a
                    # GeoJSON file, boundary_from_upload's or core.geofiles' for
                    # any file (ValueError), or the archive guards' (ImportError:
                    # unsafe path, zip bomb, upload cap, no .shp).
                    errors.append(str(exc))
                except Exception as exc:
                    logger.exception("Boundary file upload failed")
                    errors.append(
                        "An unexpected error stopped the import, and OpenH2O saved "
                        f"nothing from this file. Details: {type(exc).__name__}: {exc}"
                    )

        elif action == "extent":
            name = request.POST.get("name", "").strip()
            try:
                north, south, east, west = parse_extent_bounds(
                    request.POST.get("north", ""),
                    request.POST.get("south", ""),
                    request.POST.get("east", ""),
                    request.POST.get("west", ""),
                )
            except ValueError as exc:
                errors.append(str(exc))
            else:
                geom_name, geom, attrs = boundary_from_extent(
                    north=north, south=south, east=east, west=west, name=name,
                )
                boundary = Boundary.objects.create(
                    name=geom_name,
                    geometry=geom,
                    description="Extent entered on the Setup Wizard",
                    **attrs,
                )
                request.session[SESSION_KEY_BOUNDARY] = boundary.pk
                request.session.pop(SESSION_KEY_POLYGON_COUNT, None)
                return redirect("setup:confirm")

    boundaries = Boundary.objects.all().order_by("name")
    # The first question, asked only while it is free to answer: a site the
    # demonstration can load into (ruling 33). "Start with your own records"
    # is ?start=own; the site's first boundary then retires the question.
    demonstration_state = demonstration.status().state
    context = {
        "boundaries": boundaries,
        "errors": errors,
        "choosing": (
            request.method == "GET"
            and demonstration_state == "not_loaded"
            and request.GET.get("start") != "own"
        ),
        "starting_own": request.GET.get("start") == "own",
        "demonstration_state": demonstration_state,
    }
    return render(request, "setup/wizard.html", context)


@admin_required
@login_required
def setup_confirm(request):
    """Step 2: Review boundary on map and confirm."""
    boundary_id = request.session.get(SESSION_KEY_BOUNDARY)
    if not boundary_id:
        messages.info(
            request,
            "No boundary is confirmed for this session. Choose or upload one, "
            "then confirm it.",
        )
        return redirect("setup:wizard")

    try:
        boundary = Boundary.objects.get(pk=boundary_id)
    except Boundary.DoesNotExist:
        del request.session[SESSION_KEY_BOUNDARY]
        messages.info(
            request,
            "The boundary you chose no longer exists. Choose or "
            "upload a boundary, then confirm it.",
        )
        return redirect("setup:wizard")

    if request.method == "POST":
        # Reset step tracking and go to run page. Also drop any earlier step
        # choice: a fresh confirm always re-asks step 3's picker
        # rather than silently re-running whatever an older session chose.
        request.session[SESSION_KEY_STEP_INDEX] = 0
        request.session[SESSION_KEY_RESULTS] = []
        request.session[SESSION_KEY_PROVIDER_INDEX] = 0
        request.session.pop(SESSION_KEY_SELECTED_STEPS, None)
        _discard_parcel_download(request)
        return redirect("setup:run")

    preview = get_boundary_preview_data(boundary)
    # The template says "N polygons combined" only when N > 1.
    preview["polygon_count"] = request.session.get(SESSION_KEY_POLYGON_COUNT)
    return render(request, "setup/confirm.html", preview)


@admin_required
@login_required
def setup_run(request):
    """Step 3: choose which populate steps to run, then the HTMX polling page.

    The run does not start itself. A GET with no step choice yet
    recorded for this session renders the picker: a checkbox per step, all
    checked by default, plus "I have my own data" (JS, unchecks every box).
    Posting that form is what stores the chosen step names in the session
    and turns on the HTMX progress poll. ``setup_progress`` reads the same
    session key and only executes a step whose name was chosen.
    """
    boundary_id = request.session.get(SESSION_KEY_BOUNDARY)
    if not boundary_id:
        messages.info(
            request,
            "No boundary is confirmed for this session. Choose or upload one, "
            "then confirm it.",
        )
        return redirect("setup:wizard")

    try:
        boundary = Boundary.objects.get(pk=boundary_id)
    except Boundary.DoesNotExist:
        messages.info(
            request,
            "The boundary you chose no longer exists. Choose or "
            "upload a boundary, then confirm it.",
        )
        return redirect("setup:wizard")

    errors = []
    if request.method == "POST":
        chosen = request.POST.getlist("steps")
        # Keep only real step names, in wizard_steps() order, so a tampered or
        # stale form value can never make setup_progress index past the list.
        valid_names = {s[0] for s in wizard_steps()}
        selected = [name for name in chosen if name in valid_names]
        _discard_parcel_download(request)
        if "parcels" in selected:
            errors = _prepare_parcel_download(request, boundary)
        if not errors:
            request.session[SESSION_KEY_SELECTED_STEPS] = selected
            request.session[SESSION_KEY_STEP_INDEX] = 0
            request.session[SESSION_KEY_RESULTS] = []
            request.session[SESSION_KEY_PROVIDER_INDEX] = 0
            return redirect("setup:run")

    context = {
        "boundary": boundary,
        "steps": wizard_steps(),
        "picking": bool(errors) or SESSION_KEY_SELECTED_STEPS not in request.session,
        "errors": errors,
        "parcel_choice": request.POST.get("parcel_choice", "every") if errors else "every",
        # After a refusal the form keeps what was checked; otherwise every box starts checked.
        "checked_steps": selected if errors else [s[0] for s in wizard_steps()],
    }
    return render(request, "setup/run.html", context)


def _discard_parcel_download(request):
    """Forget this session's parcel download if it never started."""
    token = request.session.pop(SESSION_KEY_PARCEL_TOKEN, None)
    if token:
        pending = pending_imports.lookup(request.user, token, PARCEL_KIND)
        if pending is not None and pending.status == "previewed":
            pending_imports.discard(pending)


def _prepare_parcel_download(request, boundary):
    """Record the parcel download Run setup asked for; returns the refusals, if any.

    With "Only the parcels on your list", the list is read now, so a file the
    download could not use is refused on this page, and stored for the worker.
    """
    page_settings = {"boundary_id": boundary.pk}
    if request.POST.get("parcel_choice") == "list":
        upload = request.FILES.get("parcel_list")
        if not upload:
            return [PARCEL_NO_FILE]
        try:
            read_parcel_list(upload, upload.name)
        except ParcelListError as exc:
            return [str(exc)]
        page_settings["mode"] = "list"
        pending = pending_imports.save_upload(request.user, PARCEL_KIND, upload, page_settings)
    else:
        page_settings["mode"] = "every"
        pending = PendingImport.objects.create(
            kind=PARCEL_KIND, user=request.user, original_name="", stored_path="",
            settings=page_settings,
        )
    request.session[SESSION_KEY_PARCEL_TOKEN] = str(pending.token)
    return []


def _run_next_step(
    request: HttpRequest,
    boundary: Boundary,
    steps: list,
    step_names: list[str],
    selected_steps: list[str] | None,
    step_index: int,
    results: list[dict],
    provider_index: int,
) -> tuple[int, int]:
    """Run the one step (or one station provider) now due; returns the new step and provider index."""
    step_name = step_names[step_index]
    if selected_steps is not None and step_name not in selected_steps:
        # Not chosen on the picker: report it plainly as a choice, never as
        # an error, and never call the populate code for it at all.
        results.append({
            "step": step_name,
            "label": steps[step_index][1],
            "count": 0,
            "errors": [],
            "success": True,
            "note": "Skipped: you unchecked this step",
        })
        step_index += 1
    elif step_name in STEP_KINDS:
        # Its own process, as the parcel download: start it once, then each poll
        # reads where it stands and moves on when it has finished or gone quiet.
        new_rows = _poll_step_process(request, boundary, step_name, steps[step_index][1])
        if new_rows is not None:
            results.extend(new_rows)
            step_index += 1
    elif step_name == "parcels":
        # Its own process: start it once, then each poll reads where it stands
        # and moves on only when it has finished or gone quiet.
        row = _poll_parcel_download(request, boundary, steps[step_index][1])
        if row is not None:
            results.append(row)
            step_index += 1
    else:
        outcome = run_auto_populate_step(boundary, step_name)
        count, errors = outcome
        results.append({
            "step": step_name,
            "label": steps[step_index][1],
            "count": count,
            "errors": errors,
            "success": len(errors) == 0,
            "note": getattr(outcome, "note", None),
        })
        step_index += 1
    request.session[SESSION_KEY_STEP_INDEX] = step_index
    request.session[SESSION_KEY_RESULTS] = results
    request.session.modified = True
    return step_index, provider_index


def _parcel_row(request, boundary):
    """This session's parcel download row; a new "every parcel" row when there is none."""
    token = request.session.get(SESSION_KEY_PARCEL_TOKEN)
    pending = pending_imports.lookup(request.user, token, PARCEL_KIND) if token else None
    if pending is None:
        pending = PendingImport.objects.create(
            kind=PARCEL_KIND, user=request.user, original_name="", stored_path="",
            settings={"boundary_id": boundary.pk, "mode": "every"},
        )
        request.session[SESSION_KEY_PARCEL_TOKEN] = str(pending.token)
    return pending


def _poll_parcel_download(request, boundary, label):
    """Start the download if it has not started; its result row once it is over, else None."""
    pending = _parcel_row(request, boundary)
    if pending.status == "previewed":
        pending.status = "waiting"
        pending.save(update_fields=["status"])
        pending_imports.start(str(pending.token))
        pending.refresh_from_db()
    if pending.status in ("finished", "failed"):
        row = parcel_result_row(label, pending)
    elif parcel_download_quiet(pending):
        row = parcel_result_row(label, pending, stopped=True)
    else:
        return None
    pending_imports.discard(pending)
    request.session.pop(SESSION_KEY_PARCEL_TOKEN, None)
    return row


def _step_row(request, boundary, step_name):
    """This session's process row for ``step_name``; a new waiting one when there is none."""
    kind = STEP_KINDS[step_name]
    token = request.session.get(SESSION_KEY_STEP_TOKEN)
    pending = pending_imports.lookup(request.user, token, kind) if token else None
    if pending is None:
        pending = PendingImport.objects.create(
            kind=kind, user=request.user, original_name="", stored_path="",
            status="waiting", settings={"boundary_id": boundary.pk},
        )
        request.session[SESSION_KEY_STEP_TOKEN] = str(pending.token)
        request.session.modified = True
        pending_imports.start(str(pending.token))
        pending.refresh_from_db()
    return pending


def _station_rows(done):
    """The wizard's rows for the providers a station process has checked."""
    return [
        {
            "step": "stations",
            "label": station_provider_label(item["code"]),
            "count": item["count"],
            "errors": item["errors"],
            "success": item["status"] not in ("failed", "timed_out"),
            "status": item["status"],
            "note": PROVIDER_SKIP_NOTES.get(item["status"]),
        }
        for item in done
    ]


def _poll_step_process(request, boundary, step_name, label):
    """Start the step's process if it has not started; its result rows once it is over, else None."""
    pending = _step_row(request, boundary, step_name)
    stopped = False
    if pending.status in ("finished", "failed"):
        pass
    elif step_quiet(pending):
        stopped = True
    else:
        return None
    result = pending.result or {}
    if step_name == "flowlines":
        rows = [flowlines_result_row(label, pending, stopped=stopped)]
    else:
        rows = _station_rows(result.get("done") or [])
        if stopped or pending.status == "failed":
            rows.append(stations_stopped_row(label, len(rows)))
    pending_imports.discard(pending)
    request.session.pop(SESSION_KEY_STEP_TOKEN, None)
    return rows


def _step_progress(request, step_name):
    """What a running stream or station process has written so far, or None."""
    token = request.session.get(SESSION_KEY_STEP_TOKEN)
    pending = pending_imports.lookup(request.user, token, STEP_KINDS[step_name]) if token else None
    return (pending.result or {}) if pending is not None else {}


def flowlines_progress_line(progress):
    """The Flowlines step's line while its process runs: the count once USGS has given it."""
    done, total = progress.get("done") or 0, progress.get("total")
    if total:
        return f"Downloading the streams and canals in and near the boundary: {done:,} of {total:,}"
    if done:
        return f"Downloading the streams and canals in and near the boundary: {done:,} so far"
    return "Finding the streams and canals in and near the boundary…"


def _parcel_progress(request):
    """The running download's count for the progress line, or None before the IDs come."""
    token = request.session.get(SESSION_KEY_PARCEL_TOKEN)
    pending = pending_imports.lookup(request.user, token, PARCEL_KIND) if token else None
    result = (pending.result or {}) if pending is not None else {}
    if result.get("total") is None:
        return None
    return {"done": result.get("done") or 0, "total": result["total"]}


def _progress_context(
    boundary: Boundary,
    steps: list,
    step_names: list[str],
    results: list[dict],
    step_index: int,
    provider_index: int,
    all_done: bool,
) -> dict:
    """Context for the progress partial, with the station-review data on the final poll."""
    # While the stations phase runs, label the spinner with the provider the next
    # poll will query, so the operator sees progress one provider at a time.
    active_provider_label = None
    if not all_done and step_names[step_index] == "stations":
        active_provider_label = station_provider_label(
            STATION_PROVIDERS[provider_index]
        )

    context = {
        "results": results,
        "steps": steps,
        "step_index": step_index,
        "all_done": all_done,
        "boundary": boundary,
        "active_provider_label": active_provider_label,
    }
    # On the final poll, attach the station-review data so completion can offer
    # the in-flow enable step (discovered stations land inactive).
    if all_done and is_enabled("datasync"):
        context.update(build_station_review(boundary))
    return context


@admin_required
@login_required
def setup_progress(request):
    """HTMX endpoint: execute one auto_populate step at a time and return partial HTML."""
    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)

    boundary_id = request.session.get(SESSION_KEY_BOUNDARY)
    if not boundary_id:
        return HttpResponse("Session expired.", status=400)

    try:
        boundary = Boundary.objects.get(pk=boundary_id)
    except Boundary.DoesNotExist:
        return HttpResponse("Boundary not found.", status=400)

    # Which step names this run was told to execute. None means step 3
    # was reached without going through the picker (a stale or replayed request),
    # treated as "run everything" rather than "run nothing" (the wizard's old
    # behaviour), so an already-in-flight run is never silently emptied out from
    # under it.
    selected_steps = request.session.get(SESSION_KEY_SELECTED_STEPS)

    step_index = request.session.get(SESSION_KEY_STEP_INDEX, 0)
    results = request.session.get(SESSION_KEY_RESULTS, [])
    provider_index = request.session.get(SESSION_KEY_PROVIDER_INDEX, 0)

    steps = wizard_steps()
    step_names = [s[0] for s in steps]

    all_done = step_index >= len(step_names)

    if not all_done:
        step_index, provider_index = _run_next_step(
            request, boundary, steps, step_names, selected_steps,
            step_index, results, provider_index,
        )

    all_done = step_index >= len(step_names)

    context = _progress_context(
        boundary, steps, step_names, results, step_index, provider_index, all_done
    )
    running = None if all_done else step_names[step_index]
    context["parcels_running"] = running == "parcels"
    # The note under the steps and the 2-second poll, while a step runs in its own process.
    context["download_running"] = running in ("parcels", "flowlines", "stations")
    if context["parcels_running"]:
        context["parcel_progress"] = _parcel_progress(request)
    if running == "flowlines":
        context["flowlines_line"] = flowlines_progress_line(_step_progress(request, "flowlines"))
    if running == "stations":
        progress = _step_progress(request, "stations")
        context["station_rows"] = _station_rows(progress.get("done") or [])
        current = progress.get("current") or STATION_PROVIDERS[0]
        context["active_provider_label"] = station_provider_label(current)
    return render(request, "setup/partials/_progress.html", context)


@admin_required
@login_required
def setup_activate_stations(request):
    """HTMX endpoint: bulk-enable every inactive station inside the chosen
    boundary, then re-render the review partial with the new state.

    A single ``update(is_active=True)`` — no N+1 saves. Scoped to the boundary
    the session points at, so it never enables a station outside the operator's
    watershed. Per-station toggles in the review list reuse the existing
    ``datasync:station_toggle`` endpoint, so this only handles "Enable all".
    """
    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)

    boundary_id = request.session.get(SESSION_KEY_BOUNDARY)
    if not boundary_id:
        return HttpResponse("Session expired.", status=400)

    try:
        boundary = Boundary.objects.get(pk=boundary_id)
    except Boundary.DoesNotExist:
        return HttpResponse("Boundary not found.", status=400)

    MonitoredStation.objects.filter(
        location__within=boundary.geometry, is_active=False
    ).update(is_active=True)

    context = build_station_review(boundary)
    context["boundary"] = boundary
    return render(request, "setup/partials/_station_review.html", context)


def _demonstration_context(request, confirming=False):
    """What the Demonstration data page and its status partial show."""
    state = demonstration.status()
    context = {
        "state": state,
        "refresh_seconds": demonstration.REFRESH_SECONDS,
        "can_change": is_administrator(request.user),
        "confirming": False,
        "sections_missing": state.state == "refused" and bool(demonstration.modules_missing()),
    }
    if confirming and state.state == "loaded":
        counts = demonstration.content_counts()
        context.update(
            confirming=True,
            rows=[
                (demonstration.screen_name(label, n), n) for label, n in counts.items()
            ],
            total=demonstration.total(counts),
            added=demonstration.added_by_people(),
            deletes_settings=demonstration.removal_deletes_settings(),
        )
    return context


@admin_required
@login_required
def setup_demonstration(request):
    """Load or remove the demonstration data.

    A button starts ``load_demonstration`` or ``remove_demonstration`` as its own
    process after the request commits (the way the calculation starts), so the
    page never waits on it. The page reads the run's Site health record and
    refreshes itself while a run is under way.
    """
    if request.method == "POST":
        action = request.POST.get("action", "")
        if not is_administrator(request.user):
            messages.error(
                request,
                "Only an administrator can load or remove the demonstration data.",
            )
        elif action not in demonstration.COMMANDS:
            messages.error(request, "This page does not have that button.")
        else:
            state = demonstration.status()
            if state.state == "running":
                messages.info(request, "Another load or removal is still running.")
            elif action == "load" and state.state != "not_loaded":
                messages.error(
                    request,
                    state.refusal or "The demonstration data is already loaded.",
                )
            elif action == "remove" and state.state != "loaded":
                messages.error(request, demonstration.NOT_LOADED_SENTENCE)
            else:
                record = demonstration.begin_run(action, request.user)
                try:
                    demonstration.start_worker(
                        action, record_pk=record, user_pk=request.user.pk
                    )
                except CommandError as exc:
                    messages.error(request, str(exc))
        return redirect("setup:demonstration")

    context = _demonstration_context(request, confirming=request.GET.get("remove") == "1")
    if request.headers.get("HX-Request"):
        return render(request, "setup/partials/_demonstration_status.html", context)
    return render(request, "setup/demonstration.html", context)
