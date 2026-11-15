# SPDX-License-Identifier: AGPL-3.0-or-later
"""Import zones from a map file: one zone for each name in it, of the type chosen once.

The Zones page's Import zones and ``manage.py import_zones`` call the same functions,
so a screen and a command give the same zones. The file is read as the Import use
areas page reads one (``parcels/use_area_import.py``): a zipped shapefile, a KML or a
GeoJSON, an outline that is not valid as drawn repaired with ``buffer(0)``. Outlines
that share a name are joined into one zone. A name already used by a zone of the
chosen type is listed and not loaded. Nothing is written before Import.
"""
from django.contrib.gis.geos import MultiPolygon
from django.db import transaction

from core import pending_imports
from geography.models import Boundary, Zone
from parcels import use_area_import as map_file

NAME_MAX_LENGTH = Zone._meta.get_field("name").max_length

NO_COLUMNS_MESSAGE = (
    "The outlines in this file have no columns to name the zones from. Add a column of zone "
    "names in a GIS program and upload the file again."
)
NO_BOUNDARY_MESSAGE = (
    "This site's boundary is not set yet. Set it in the Setup Wizard, then import your zones."
)
NO_FILE_MESSAGE = map_file.NO_FILE_MESSAGE

#: Column names (lower case, letters only) taken as the zone's name when the person
#: has not chosen one. The first column is the fallback.
NAME_HINTS = ("name", "gsaname", "zonename", "label", "title")


def read_file(file):
    """``{"features", "columns"}``, refusing a file whose outlines carry no columns."""
    read = map_file.read_file(file)
    if not read["columns"]:
        raise ImportError(NO_COLUMNS_MESSAGE)
    return read


def guess_name_column(columns):
    """The column most likely to hold the zone names, else the first column."""
    def letters(column):
        return "".join(ch for ch in column.lower() if ch.isalpha())

    for hint in NAME_HINTS:
        for column in columns:
            if letters(column) == hint:
                return column
    for column in columns:
        if "name" in letters(column):
            return column
    return columns[0] if columns else ""


def zone_types():
    """The zone types a file's zones may take: the zone form's own choices."""
    return list(Zone.ZONE_TYPE_CHOICES)


def valid_zone_type(value):
    return value if value in dict(Zone.ZONE_TYPE_CHOICES) else Zone.ZONE_TYPE_CHOICES[0][0]


def _name(feature, column):
    value = (feature.get("properties") or {}).get(column)
    return "" if value is None else str(value).strip()


def plan_zones(features, name_column, zone_type):
    """What importing ``features`` would do. Writes nothing.

    Returns ``new`` (a list of ``{"name", "geometry"}`` in file order), ``used`` (names
    already taken by a zone of ``zone_type``), ``no_name`` and ``too_long`` (counts of
    outlines), ``unreadable`` (the names of outlines without a readable outline),
    ``shared`` (``(name, outline count)`` for each name more than one outline carries)
    and ``outline_count``.
    """
    taken = set(Zone.objects.filter(zone_type=zone_type).values_list("name", flat=True))
    by_name = {}
    order = []
    no_name = too_long = 0
    unreadable = []
    used_outlines = {}
    for feature in features:
        name = _name(feature, name_column)
        if not name:
            no_name += 1
            continue
        if len(name) > NAME_MAX_LENGTH:
            too_long += 1
            continue
        if name in taken:
            used_outlines[name] = used_outlines.get(name, 0) + 1
            continue
        outline = map_file.outline_of(feature.get("geometry"))
        if outline is None:
            unreadable.append(name)
            continue
        if name not in by_name:
            by_name[name] = []
            order.append(name)
        by_name[name].append(outline)
    new = [{"name": name, "geometry": map_file.joined(by_name[name])} for name in order]
    shared = [(name, len(by_name[name])) for name in order if len(by_name[name]) > 1]
    return {
        "new": new,
        "used": list(used_outlines),
        "used_outlines": sum(used_outlines.values()),
        "no_name": no_name,
        "too_long": too_long,
        "unreadable": unreadable,
        "shared": shared,
        "outline_count": len(features),
        "left_out": sum(used_outlines.values()) + no_name + too_long + len(unreadable),
    }


def site_boundary_row():
    """The Boundary a new zone belongs to (the Add zone page's rule: the first on file)."""
    return Boundary.objects.order_by("pk").first()


def write_zones(plan, zone_type):
    """Make the planned zones; returns how many were made."""
    boundary = site_boundary_row()
    if boundary is None:
        raise ImportError(NO_BOUNDARY_MESSAGE)
    with transaction.atomic():
        for item in plan["new"]:
            geometry = item["geometry"]
            if not isinstance(geometry, MultiPolygon):
                geometry = MultiPolygon(geometry, srid=4326)
            Zone.objects.create(
                name=item["name"], zone_type=zone_type, boundary=boundary, geometry=geometry
            )
    return len(plan["new"])


def result_context(created, left_out):
    return {"created": created, "left_out": left_out}


def commit_stored_zones(pending):
    """The import worker's commit: read the stored file again and make its zones."""
    with pending_imports.stored_file(pending) as file:
        read = read_file(file)
    zone_type = valid_zone_type(pending.settings.get("zone_type", ""))
    plan = plan_zones(read["features"], pending.settings.get("name_column", ""), zone_type)
    created = write_zones(plan, zone_type)
    return result_context(created, plan["left_out"])


def preview_lines(plan):
    """The preview's table as lines of (count, what, action), for the command."""
    lines = []
    if plan["new"]:
        lines.append((len(plan["new"]), "new zones" if len(plan["new"]) != 1 else "new zone", "Imported"))
    if plan["used"]:
        n = plan["used_outlines"]
        lines.append((n, "name already used by a zone of this type" if n == 1
                      else "names already used by a zone of this type", "Not imported"))
    if plan["no_name"]:
        n = plan["no_name"]
        lines.append((n, "outline without a name" if n == 1 else "outlines without a name", "Not imported"))
    if plan["unreadable"]:
        lines.append((len(plan["unreadable"]), "without a readable outline", "Not imported"))
    if plan["too_long"]:
        n = plan["too_long"]
        lines.append((n, f"name over {NAME_MAX_LENGTH} characters" if n == 1
                      else f"names over {NAME_MAX_LENGTH} characters", "Not imported"))
    return lines


def shared_sentence(name, count):
    return f"{count} outlines in this file share the name {name}. OpenH2O joins them into one zone."


def result_sentence(created, left_out):
    zones = "zone" if created == 1 else "zones"
    if left_out:
        outlines = "outline" if left_out == 1 else "outlines"
        return f"OpenH2O imported {created} {zones} and left out the {left_out} {outlines} the preview listed."
    return f"OpenH2O imported {created} {zones}."
