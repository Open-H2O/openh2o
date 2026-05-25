"""
Service layer for the setup wizard.

Wraps each auto_populate step so the wizard can call them
one-at-a-time via HTMX polling and receive structured results
instead of management command stdout output.
"""

import logging

from geography.models import Boundary, Flowline, Zone
from parcels.models import Parcel

logger = logging.getLogger(__name__)

# Step registry: matches the OrderedDict in auto_populate.Command
WIZARD_STEPS = [
    ("basins", "Groundwater Basins", "DWR Bulletin 118 subbasins"),
    ("parcels", "Parcel Boundaries", "LightBox statewide parcels"),
    ("flowlines", "Flowlines", "USGS 3DHP hydrography"),
    ("stations", "Monitoring Stations", "CDEC, USGS, CIMIS stations"),
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


def get_boundary_preview_data(boundary: Boundary) -> dict:
    """Return summary stats for the confirmation page."""
    from datasync.models import MonitoredStation

    existing_basins = Zone.objects.filter(boundary=boundary).count()
    existing_parcels = Parcel.objects.count()
    existing_flowlines = Flowline.objects.filter(boundary=boundary).count()
    existing_stations = MonitoredStation.objects.count()

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
        "boundary_geojson": json.dumps(geojson) if geojson else None,
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
