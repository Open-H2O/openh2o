# SPDX-License-Identifier: AGPL-3.0-or-later
"""Helpers that more than one drinking screen uses."""
from django.db.models import Count
from drinking.models import SampleResult


def group_results_by_event(rows):
    """Fold an ordered run of sample results into one block per sample event.

    R-070 / R-071: an event IS one date at one point, so the results log says
    that once per event (a ``tr.row-group`` divider) instead of repeating the
    date and the PS Code on every row. ``rows`` must already be ordered so a
    given event's results are contiguous -- ``results`` below orders
    ``-event__sample_date, event__sampling_point__ps_code, event_id,
    analyte__name`` for exactly that reason -- this function only folds runs
    of the same ``event_id``; it does not sort.

    ``total`` is the event's FULL result count, read from ONE ``Count`` query
    over every event id present in ``rows``, never a query per group and
    never a per-row loop. ``shown`` is how many of that event's rows are in
    THIS ``rows`` list, so a group whose rows are split across two pages of
    the caller's own pagination prints its divider again on the second page,
    with ``shown`` less than ``total`` saying so.

    Pure on purpose -- rows in, groups out, no request and no queryset touched
    beyond the one Count -- so the sampling-point detail page
    can call it again on its own ``recent`` slice of one point's history.
    """
    rows = list(rows)
    if not rows:
        return []

    event_ids = []
    seen_events = set()
    for row in rows:
        if row.event_id not in seen_events:
            seen_events.add(row.event_id)
            event_ids.append(row.event_id)

    totals = dict(
        SampleResult.objects.filter(event_id__in=event_ids)
        .order_by()
        .values("event_id")
        .annotate(n=Count("id"))
        .values_list("event_id", "n")
    )

    groups = []
    for row in rows:
        if not groups or groups[-1]["event"].pk != row.event_id:
            groups.append({
                "event": row.event,
                "rows": [],
                "shown": 0,
                "total": totals.get(row.event_id, 0),
            })
        groups[-1]["rows"].append(row)
        groups[-1]["shown"] += 1
    return groups


def _facility_geojson(facility, extra_properties=None):
    """One facility as a one-feature ``FeatureCollection``, or ``None``.

    ``None``, deliberately, and never an empty ``FeatureCollection``.
    ``OH2O.detailPaneMap`` hides its whole card when the ``json_script`` element
    is absent, and shows an empty grey rectangle when the element is present but
    carries no features — which is 40 of the 61 facilities in the demonstration,
    and EVERY facility of a system onboarded through Envirofacts, since EPA
    publishes no coordinates at all.

    A Python object, not a ``json.dumps`` string: the template escapes it through
    ``json_script`` so a facility name can never break out of the ``<script>``.

    **Identity and position only.** Same rule as ``facilities_geojson`` and for
    the same reason — a popup is a view, so no result, limit or compliance status
    is carried here.
    """
    if facility.location is None:
        return None
    properties = {
        "facility_id": facility.facility_id,
        "name": facility.name,
        # The published LABEL, not the two-letter code.
        "facility_type": facility.get_facility_type_display(),
        "system_name": facility.system.name,
    }
    properties.update(extra_properties or {})
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [facility.location.x, facility.location.y],
                },
                "properties": properties,
            }
        ],
    }


# The surface water imports' sentence: rows_json is empty or not a list of rows.
_ROWS_NOT_RECEIVED = (
    "OpenH2O did not receive the file's rows from the preview. "
    "Upload the file again."
)


def _describe(facility):
    """Flag whether EPA's name for this facility repeats its type label.

    Set on the instance rather than resolved in the template so the same answer
    is available whether the page renders it or an add's response swaps it in.

    This does not attach a sentence saying what the facility physically is
    ("A drilled well. Water comes up out of the ground here."): the reader is a water district operator and the panel
    heading already carries EPA's own label. DESIGN.md copy rule 11.
    """
    # EPA's name is often just the type again ("DISTRIBUTION SYSTEM" on a
    # facility already typed Distribution System). Showing both produced the
    # heading "Distribution System — DISTRIBUTION SYSTEM", which is the exact
    # code-soup this rewrite exists to remove. Applied to the facility select's
    # option text too, the one other place this heading shape
    # is built.
    label = (facility.get_facility_type_display() or "").strip().lower()
    facility.name_adds_nothing = (facility.name or "").strip().lower() == label
    return facility
