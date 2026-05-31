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

from geography.models import Boundary
from setup.services import WIZARD_STEPS, get_boundary_preview_data, run_auto_populate_step

logger = logging.getLogger(__name__)

SESSION_KEY_BOUNDARY = "setup_wizard_boundary_id"
SESSION_KEY_STEP_INDEX = "setup_wizard_step_index"
SESSION_KEY_RESULTS = "setup_wizard_results"

# Ordered step names (must match WIZARD_STEPS order)
STEP_NAMES = [s[0] for s in WIZARD_STEPS]


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
                errors.append("Please select a GeoJSON file.")
            else:
                try:
                    raw = uploaded.read().decode("utf-8")
                    geojson = json.loads(raw)
                    geom = _parse_geojson_boundary(geojson)
                    if geom is None:
                        errors.append(
                            "Could not extract a polygon from the uploaded file. "
                            "Provide a GeoJSON Feature or FeatureCollection with Polygon or MultiPolygon geometry."
                        )
                    else:
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
                except json.JSONDecodeError:
                    errors.append("The file is not valid JSON.")
                except Exception as exc:
                    logger.exception("GeoJSON upload failed")
                    errors.append(f"Upload failed: {exc}")

    boundaries = Boundary.objects.all().order_by("name")
    context = {
        "boundaries": boundaries,
        "errors": errors,
    }
    return render(request, "setup/wizard.html", context)


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
        return redirect("setup:run")

    preview = get_boundary_preview_data(boundary)
    return render(request, "setup/confirm.html", preview)


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
        "steps": WIZARD_STEPS,
    }
    return render(request, "setup/run.html", context)


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

    all_done = step_index >= len(STEP_NAMES)

    if not all_done:
        step_name = STEP_NAMES[step_index]
        count, errors = run_auto_populate_step(boundary, step_name)
        results.append({
            "step": step_name,
            "label": WIZARD_STEPS[step_index][1],
            "count": count,
            "errors": errors,
            "success": len(errors) == 0,
        })
        step_index += 1
        request.session[SESSION_KEY_STEP_INDEX] = step_index
        request.session[SESSION_KEY_RESULTS] = results
        request.session.modified = True

    context = {
        "results": results,
        "steps": WIZARD_STEPS,
        "step_index": step_index,
        "all_done": step_index >= len(STEP_NAMES),
        "boundary": boundary,
    }
    return render(request, "setup/partials/_progress.html", context)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _parse_geojson_boundary(geojson: dict):
    """
    Extract a MultiPolygon GEOSGeometry from a GeoJSON dict.
    Accepts Feature, FeatureCollection (first feature), or raw geometry.
    Returns None if no valid polygon can be extracted.
    """
    if geojson.get("type") == "FeatureCollection":
        features = geojson.get("features", [])
        if not features:
            return None
        geom_dict = features[0].get("geometry")
    elif geojson.get("type") == "Feature":
        geom_dict = geojson.get("geometry")
    else:
        geom_dict = geojson  # raw geometry

    if geom_dict is None:
        return None

    geom_type = geom_dict.get("type", "")
    if geom_type not in ("Polygon", "MultiPolygon"):
        return None

    try:
        geos = GEOSGeometry(json.dumps(geom_dict), srid=4326)
        if isinstance(geos, Polygon):
            return MultiPolygon(geos, srid=4326)
        if isinstance(geos, MultiPolygon):
            return geos
    except Exception:
        logger.exception("GEOSGeometry parse failed")

    return None
