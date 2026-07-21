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

from django.contrib.auth.decorators import login_required
from django.contrib.gis.geos import GEOSGeometry, MultiPolygon, Polygon
from django.http import HttpResponse
from django.shortcuts import redirect, render

from core.access import admin_required
from core.modules import is_enabled
from datasync.models import MonitoredStation
from geography.models import Boundary
from setup.services import (
    STATION_PROVIDERS,
    build_station_review,
    get_boundary_preview_data,
    run_auto_populate_step,
    run_station_provider_step,
    station_provider_label,
    wizard_steps,
)

logger = logging.getLogger(__name__)

SESSION_KEY_BOUNDARY = "setup_wizard_boundary_id"
SESSION_KEY_STEP_INDEX = "setup_wizard_step_index"
SESSION_KEY_RESULTS = "setup_wizard_results"
SESSION_KEY_PROVIDER_INDEX = "setup_wizard_provider_index"

# The step list is resolved per request via `wizard_steps()`, not frozen into a
# module constant: `datasync` is demotable from Phase 88, and a deployment that
# switched it off must not be walked through a Monitoring Stations step. The
# views index into the list by position, so one stale copy would run the wrong
# step rather than merely showing an extra label.

# Plain-language note shown for a provider's clean (non-failure) skip outcomes.
# created/timed_out/failed are NOT here — they render via count / the error row.
PROVIDER_SKIP_NOTES = {
    "skipped_no_key": "Skipped — no API key configured. You can add one later.",
    "skipped_no_source": "Skipped — this data source isn't configured.",
    "skipped_no_adapter": "Skipped — no connector available for this provider.",
}


@admin_required
@login_required
def setup_wizard(request):
    """Step 1: Boundary selection — select existing or upload GeoJSON."""
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
                    return redirect("setup:confirm")
                except (Boundary.DoesNotExist, ValueError):
                    errors.append("Selected boundary does not exist.")

        elif action == "upload":
            uploaded = request.FILES.get("geojson_file")
            if not uploaded:
                errors.append("Please choose a GeoJSON file to upload.")
            else:
                try:
                    raw = uploaded.read().decode("utf-8")
                    geojson = json.loads(raw)
                    geom = _parse_geojson_boundary(geojson)
                    name = (
                        geojson.get("name")
                        or (geojson.get("features", [{}])[0].get("properties", {}) or {}).get("name")
                        or uploaded.name.rsplit(".", 1)[0]
                    )
                    boundary = Boundary.objects.create(
                        name=name or "Uploaded Boundary",
                        geometry=geom,
                    )
                    request.session[SESSION_KEY_BOUNDARY] = boundary.pk
                    return redirect("setup:confirm")
                except UnicodeDecodeError:
                    errors.append(
                        "That file couldn't be read as text. A GeoJSON file is a "
                        "plain-text file — make sure you exported GeoJSON, not a "
                        "shapefile or a zip archive."
                    )
                except json.JSONDecodeError:
                    errors.append(
                        "The file isn't valid JSON. A GeoJSON file is text that "
                        "starts with '{' — check you exported GeoJSON (not a "
                        "shapefile, KML, or zip)."
                    )
                except ValueError as exc:
                    # Specific, plain-language reason from _parse_geojson_boundary.
                    errors.append(str(exc))
                except Exception as exc:
                    logger.exception("GeoJSON upload failed")
                    errors.append(f"Upload failed: {exc}")

    boundaries = Boundary.objects.all().order_by("name")
    context = {
        "boundaries": boundaries,
        "errors": errors,
    }
    return render(request, "setup/wizard.html", context)


@admin_required
@login_required
def setup_confirm(request):
    """Step 2: Review boundary on map and confirm."""
    boundary_id = request.session.get(SESSION_KEY_BOUNDARY)
    if not boundary_id:
        return redirect("setup:wizard")

    try:
        boundary = Boundary.objects.get(pk=boundary_id)
    except Boundary.DoesNotExist:
        del request.session[SESSION_KEY_BOUNDARY]
        return redirect("setup:wizard")

    if request.method == "POST":
        # Reset step tracking and go to run page
        request.session[SESSION_KEY_STEP_INDEX] = 0
        request.session[SESSION_KEY_RESULTS] = []
        request.session[SESSION_KEY_PROVIDER_INDEX] = 0
        return redirect("setup:run")

    preview = get_boundary_preview_data(boundary)
    return render(request, "setup/confirm.html", preview)


@admin_required
@login_required
def setup_run(request):
    """Step 3: Progress page — HTMX polling drives step-by-step execution."""
    boundary_id = request.session.get(SESSION_KEY_BOUNDARY)
    if not boundary_id:
        return redirect("setup:wizard")

    try:
        boundary = Boundary.objects.get(pk=boundary_id)
    except Boundary.DoesNotExist:
        return redirect("setup:wizard")

    context = {
        "boundary": boundary,
        "steps": wizard_steps(),
    }
    return render(request, "setup/run.html", context)


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

    step_index = request.session.get(SESSION_KEY_STEP_INDEX, 0)
    results = request.session.get(SESSION_KEY_RESULTS, [])
    provider_index = request.session.get(SESSION_KEY_PROVIDER_INDEX, 0)

    steps = wizard_steps()
    step_names = [s[0] for s in steps]

    all_done = step_index >= len(step_names)

    if not all_done:
        step_name = step_names[step_index]
        if step_name == "stations":
            # Stations is split into one short request per provider (ISS-051): a
            # slow/failing provider becomes an isolated, labeled row instead of a
            # synchronous all-providers call that can outlast the worker timeout.
            code = STATION_PROVIDERS[provider_index]
            count, errors, status = run_station_provider_step(boundary, code)
            results.append({
                "step": "stations",
                "label": station_provider_label(code),
                "count": count,
                "errors": errors,
                "success": status not in ("failed", "timed_out"),
                "status": status,
                "note": PROVIDER_SKIP_NOTES.get(status),
            })
            provider_index += 1
            if provider_index >= len(STATION_PROVIDERS):
                # Every provider polled — the stations step is complete.
                step_index += 1
                provider_index = 0
            request.session[SESSION_KEY_PROVIDER_INDEX] = provider_index
        else:
            count, errors = run_auto_populate_step(boundary, step_name)
            results.append({
                "step": step_name,
                "label": steps[step_index][1],
                "count": count,
                "errors": errors,
                "success": len(errors) == 0,
            })
            step_index += 1
        request.session[SESSION_KEY_STEP_INDEX] = step_index
        request.session[SESSION_KEY_RESULTS] = results
        request.session.modified = True

    all_done = step_index >= len(step_names)

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


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _parse_geojson_boundary(geojson: dict):
    """
    Extract a MultiPolygon GEOSGeometry from a GeoJSON dict.
    Accepts Feature, FeatureCollection (first feature), or raw geometry.

    Raises ``ValueError`` with a specific, plain-language reason when no valid
    polygon can be extracted, so the wizard can tell the operator exactly what
    was wrong (empty collection vs. wrong geometry type vs. unreadable
    coordinates) instead of one generic failure.
    """
    if not isinstance(geojson, dict):
        raise ValueError(
            "That file isn't a GeoJSON object — expected a Feature, "
            "FeatureCollection, or geometry."
        )

    gtype = geojson.get("type")
    if gtype == "FeatureCollection":
        features = geojson.get("features", [])
        if not features:
            raise ValueError(
                "The GeoJSON FeatureCollection is empty — it has no features to "
                "use as a boundary."
            )
        geom_dict = features[0].get("geometry")
    elif gtype == "Feature":
        geom_dict = geojson.get("geometry")
    else:
        geom_dict = geojson  # raw geometry

    if geom_dict is None:
        raise ValueError(
            "No geometry found in the file. Provide a GeoJSON Feature or "
            "FeatureCollection whose feature has Polygon or MultiPolygon geometry."
        )

    geom_type = geom_dict.get("type", "")
    if geom_type not in ("Polygon", "MultiPolygon"):
        raise ValueError(
            f"The boundary geometry is a {geom_type or 'unknown type'}, but a "
            "Polygon or MultiPolygon is required — upload an area outline (your "
            "district), not a point or line."
        )

    try:
        geos = GEOSGeometry(json.dumps(geom_dict), srid=4326)
    except Exception:
        logger.exception("GEOSGeometry parse failed")
        raise ValueError(
            "The geometry couldn't be read as a valid polygon. Check the "
            "coordinates are WGS84 longitude/latitude pairs (EPSG:4326)."
        )

    if isinstance(geos, Polygon):
        return MultiPolygon(geos, srid=4326)
    if isinstance(geos, MultiPolygon):
        return geos
    raise ValueError(
        f"The geometry parsed as {geos.geom_type}, but a Polygon or "
        "MultiPolygon is required."
    )
