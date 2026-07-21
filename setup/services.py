# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Service layer for the setup wizard.

Wraps each auto_populate step so the wizard can call them
one-at-a-time via HTMX polling and receive structured results
instead of management command stdout output.
"""

import logging

from core.modules import is_enabled
from geography.models import Boundary, Flowline, Zone
from parcels.models import Parcel

logger = logging.getLogger(__name__)

# Step registry: matches the OrderedDict in auto_populate.Command
WIZARD_STEPS = [
    ("basins", "Groundwater Basins", "DWR Bulletin 118 subbasins"),
    ("parcels", "Parcel Boundaries", "LightBox statewide parcels"),
    ("flowlines", "Flowlines", "USGS 3DHP hydrography"),
    ("stations", "Monitoring Stations", "Federal and state gauges, wells, and weather stations near your watershed"),
]

#: Which module each wizard step fills, declared rather than derived — the same
#: discipline as ``_PAGES`` in the droppability harness. ``None`` means the step
#: belongs to a module every deployment carries, so it always runs.
#:
#: The stations step is the one that matters: it discovers ``MonitoredStation``
#: rows, so on a ``datasync``-demoted deployment it would offer the operator a
#: step that fills a switched-off module's tables — the one thing
#: ``test_schema_resident_module_tables_are_present_and_empty`` exists to catch,
#: reached through the UI instead of through ``seed_data``.
_STEP_MODULE = {
    "basins": "geography",
    "parcels": "parcels",
    "flowlines": "geography",
    "stations": "datasync",
}


def wizard_steps() -> list:
    """The wizard steps this deployment can actually run, in order.

    Resolved per request rather than at import time: ``OPENH2O_MODULES`` is read
    when settings load, but a module-level constant computed here would freeze
    the answer into anything that imports this file first — and the views index
    into this list by position, so a stale copy would run the wrong step.
    """
    return [
        step for step in WIZARD_STEPS
        if _STEP_MODULE.get(step[0]) is None or is_enabled(_STEP_MODULE[step[0]])
    ]


def run_auto_populate_step(boundary: Boundary, step_name: str) -> tuple:
    """
    Run one step of the auto_populate pipeline for a boundary.

    Returns (count, errors) where count is the number of records created
    and errors is a list of error strings (empty on success).

    Delegates to the management command's step methods directly to avoid
    code duplication. Uses a lightweight Command instance with a captured
    stdout buffer.
    """
    import io

    from django.core.management import call_command

    from geography.management.commands.auto_populate import Command

    class SilentCommand(Command):
        """Subclass that suppresses stdout and captures counts."""

        def __init__(self):
            super().__init__()
            self.stdout = _NullWriter()
            self.stderr = _NullWriter()
            self.style = _NullStyle()

    cmd = SilentCommand()
    errors = []
    count = 0

    try:
        if step_name == "basins":
            count = cmd._step_basins(boundary, dry_run=False)
        elif step_name == "parcels":
            count = cmd._step_parcels(boundary, dry_run=False)
        elif step_name == "flowlines":
            count = cmd._step_flowlines(boundary, dry_run=False)
        elif step_name == "stations":
            count = cmd._step_stations(boundary, dry_run=False)
        else:
            errors.append(f"Unknown step: {step_name}")
    except Exception as exc:
        logger.exception("Wizard step '%s' failed for boundary %s", step_name, boundary.pk)
        errors.append(str(exc))

    return count, errors


# Ordered provider codes for the station step, the single source of truth shared
# with the management command. The wizard iterates this one provider per HTMX
# poll so a slow/failing provider is an isolated, short request (ISS-051).
from geography.management.commands.auto_populate import (  # noqa: E402
    STATION_SOURCE_CODES as STATION_PROVIDERS,
)

# Friendly, plain-language messages for the non-failure skip outcomes, so the
# wizard can show "no API key" as a clean labeled row rather than a red error.
_PROVIDER_FRIENDLY_FALLBACKS = {
    "usgs": "U.S. Geological Survey",
    "cdec": "California Data Exchange Center",
    "dwr_wdl": "DWR Water Data Library",
    "dwr_sgma": "DWR SGMA Monitoring",
    "cimis": "CIMIS Weather Stations",
    "noaa": "NOAA Weather Stations",
    "cnrfc": "California Nevada River Forecast Center",
}


def station_provider_label(code: str) -> str:
    """Human-readable name for a provider code, for the wizard's per-provider row.

    Prefers the configured ``DataSource.name`` (the same friendly label the
    station catalog shows). Falls back to a built-in name, then the bare code, so
    the wizard never renders a raw code or crashes when a DataSource row is absent.
    """
    from datasync.models import DataSource

    ds = DataSource.objects.filter(code=code).first()
    if ds and ds.name:
        return ds.name
    return _PROVIDER_FRIENDLY_FALLBACKS.get(code, code.upper())


def run_station_provider_step(boundary: Boundary, code: str) -> tuple:
    """Discover stations from ONE provider for the wizard's per-provider poll.

    Returns ``(count, errors, status)``. ``count`` is the number of stations
    created, ``status`` is the outcome from ``_discover_provider`` (created /
    skipped_no_key / skipped_no_source / skipped_no_adapter / timed_out / failed),
    and ``errors`` carries a friendly, plain-language message for the failure
    states (the detailed exception is logged, not shown to the operator) — empty
    for the success and clean-skip states.

    Delegates to the command's ``_discover_provider`` so discovery logic lives in
    exactly one place. ``_discover_provider`` never raises, so a slow or failing
    provider yields a labeled result row, never a dead poll.
    """
    from geography.management.commands.auto_populate import Command

    class SilentCommand(Command):
        def __init__(self):
            super().__init__()
            self.stdout = _NullWriter()
            self.stderr = _NullWriter()
            self.style = _NullStyle()

    cmd = SilentCommand()
    try:
        count, status = cmd._discover_provider(boundary, code, dry_run=False)
    except Exception as exc:
        # _discover_provider is fail-soft, but guard the wizard against any
        # unforeseen error so the poll always returns a renderable result.
        logger.exception("Provider '%s' discovery failed for boundary %s", code, boundary.pk)
        return 0, ["Couldn't reach this data provider."], "failed"

    if status == "timed_out":
        return count, ["The data provider didn't respond in time and was skipped."], status
    if status == "failed":
        return count, ["Couldn't reach this data provider."], status
    return count, [], status


def build_station_review(boundary: Boundary) -> dict:
    """Group the monitoring stations inside a boundary for the wizard's
    review-and-enable step.

    Discovered stations land ``is_active=False`` (see ``_step_stations``), so a
    fresh run leaves them all switched off. This returns the stations whose point
    falls within the chosen boundary's geometry — the watershed the operator just
    set up — grouped by provider under the provider's friendly ``DataSource.name``
    (never the raw ``dwr_wdl`` code), plus the active/inactive tallies that drive
    the "Enable all" control.

    Spatial scope (``location__within``) is the plan's "point-in-polygon via the
    chosen boundary" option, so enabling never reaches a station outside the
    operator's watershed.
    """
    from datasync.models import MonitoredStation

    stations = (
        MonitoredStation.objects.filter(location__within=boundary.geometry)
        .select_related("data_source")
        .order_by("data_source__name", "station_name")
    )

    groups_map = {}
    total = 0
    active = 0
    for station in stations:
        total += 1
        if station.is_active:
            active += 1
        groups_map.setdefault(station.data_source, []).append(station)

    review_groups = [
        {"source_name": ds.name, "stations": sts}
        for ds, sts in groups_map.items()
    ]

    return {
        "review_groups": review_groups,
        "review_total": total,
        "review_active": active,
        "review_inactive": total - active,
    }


def get_boundary_preview_data(boundary: Boundary) -> dict:
    """Return summary stats for the confirmation page."""
    from datasync.models import MonitoredStation

    existing_basins = Zone.objects.filter(boundary=boundary).count()
    existing_parcels = Parcel.objects.count()
    existing_flowlines = Flowline.objects.filter(boundary=boundary).count()
    existing_stations = MonitoredStation.objects.count() if is_enabled("datasync") else None

    geojson = None
    if boundary.geometry:
        import json
        geojson = json.loads(boundary.geometry.json)

    return {
        "boundary": boundary,
        "area_sq_miles": boundary.area_sq_miles,
        "existing_basins": existing_basins,
        "existing_parcels": existing_parcels,
        "existing_flowlines": existing_flowlines,
        "existing_stations": existing_stations,
        # Python object (or None); confirm.html escapes it via json_script.
        "boundary_geojson": geojson,
    }


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

class _NullWriter:
    """Absorbs write() calls from management command stdout."""

    def write(self, *args, **kwargs):
        pass

    def flush(self):
        pass


class _NullStyle:
    """No-op style shim so Command.style.SUCCESS(...) calls don't fail."""

    def __getattr__(self, name):
        return lambda x: x
