# SPDX-License-Identifier: AGPL-3.0-or-later
"""Import use areas from a map file: a zipped shapefile, a KML or a GeoJSON.

The page (``parcels/views.py``) saves the upload through
``core/pending_imports.py`` (kind ``use_areas``), and this module does the
jobs the page and the ``import_parcels`` command share:

* ``read_file`` reads the file through ``core/geofiles.py``, the one reader
  the Setup Wizard and the bulk import use, and lists the file's columns;
* ``auto_map`` guesses which column holds the parcel number;
* ``plan_features`` decides what each feature would become: a new use area,
  one already on file, one outside the site's boundary, or a feature refused
  with a reason. The preview and the commit run the same ``plan_features``, so
  what the preview counts is what Import writes;
* ``commit_stored_use_areas`` writes the new use areas of the stored file.

Features that carry the same parcel number are joined into one use area whose
outline holds all of them.
"""
import json
import math

from django.contrib.gis.db.models import Union
from django.contrib.gis.gdal import GDALException
from django.contrib.gis.geos import (
    GEOSException,
    GEOSGeometry,
    MultiPolygon,
    Polygon,
)
from django.db import transaction
from django.db.models import Sum

from core import geofiles, pending_imports
from core.geofiles import NO_FEATURES_MESSAGE
from geography.models import Boundary
from parcels.models import Parcel

NO_FILE_MESSAGE = "Choose a file to upload."

#: The widths of the columns a use area is written into.
NUMBER_MAX_LENGTH = Parcel._meta.get_field("parcel_number").max_length
OWNER_MAX_LENGTH = Parcel._meta.get_field("owner_name").max_length

#: Fields GDAL adds to every KML feature for styling, lower case. They are not
#: the file's own columns, so the column list leaves them out.
KML_STYLE_FIELDS = frozenset(
    (
        "altitudemode",
        "tessellate",
        "extrude",
        "visibility",
        "draworder",
        "icon",
        "snippet",
        "begin",
        "end",
        "timestamp",
    )
)

#: Column names that hold a parcel number, lower case, best guess first.
NUMBER_NAMES = ("apn", "parcel_number", "parcel", "parcelno")

SQUARE_METERS_PER_ACRE = 4046.8564224

#: California Albers, the equal-area projection acres are measured in.
ACRES_SRID = 3310

#: How many values the matching step shows beside a chosen column.
SAMPLE_VALUES = 5

#: Parcels are looked up in batches so a large file never sends one huge query.
_LOOKUP_BATCH = 5000


# ---------------------------------------------------------------------------
# Reading the file
# ---------------------------------------------------------------------------


def _text(value):
    return "" if value is None else str(value).strip()


def columns_of(features, *, kml=False):
    """The file's columns, in the order the features first name them.

    A column that is empty on every feature is left out. A KML also leaves out
    the styling fields GDAL adds (``KML_STYLE_FIELDS``).
    """
    filled = {}
    for feature in features:
        for key, value in (feature.get("properties") or {}).items():
            filled[key] = filled.get(key, False) or bool(_text(value))
    return [
        key
        for key, has_value in filled.items()
        if has_value and not (kml and key.casefold() in KML_STYLE_FIELDS)
    ]


def read_file(file):
    """``{"features", "columns"}`` of an uploaded or stored map file.

    Raises ImportError with the sentence the page shows: the reader's own
    (a wrong type, a file over the size ceiling, a zip of several shapefiles),
    a file with no features, or coordinates that are not longitude and latitude.
    """
    try:
        features = geofiles.features_from_upload(file)
        if not features:
            raise ValueError(NO_FEATURES_MESSAGE)
        geofiles.check_longitude_latitude(features)
    except ValueError as exc:
        raise ImportError(str(exc))
    kml = geofiles.extension(getattr(file, "name", "")) in geofiles.KML_EXTENSIONS
    return {"features": features, "columns": columns_of(features, kml=kml)}


def auto_map(columns):
    """``{"parcel_number": column, "owner_name": column}`` guessed from the names.

    The parcel number is the first of APN, PARCEL_NUMBER, PARCEL, PARCELNO,
    then a column starting APN_, then a column called Name, else the first
    column. The owner is never guessed.
    """
    by_name = {}
    for column in columns:
        by_name.setdefault(column.strip().casefold(), column)
    number = next((by_name[n] for n in NUMBER_NAMES if n in by_name), None)
    if number is None:
        number = next((c for c in columns if c.strip().casefold().startswith("apn_")), None)
    if number is None:
        number = by_name.get("name")
    if number is None and columns:
        number = columns[0]
    return {"parcel_number": number or "", "owner_name": ""}


def posted_mapping(data, columns):
    """The column matches a form posted, for the columns the file really has."""
    guess = auto_map(columns)
    number = data.get("map:parcel_number", "")
    owner = data.get("map:owner_name", "")
    return {
        "parcel_number": number if number in columns else guess["parcel_number"],
        "owner_name": owner if owner in columns else "",
    }


def first_values(features, column):
    """The first ``SAMPLE_VALUES`` values of ``column`` that are not blank."""
    values = []
    if not column:
        return values
    for feature in features:
        value = _text((feature.get("properties") or {}).get(column))
        if value:
            values.append(value)
            if len(values) == SAMPLE_VALUES:
                break
    return values


# ---------------------------------------------------------------------------
# Outlines
# ---------------------------------------------------------------------------


def _multipolygon(geometry):
    """``geometry`` as a non-empty MultiPolygon in SRID 4326, else None."""
    if geometry.empty:
        return None
    if isinstance(geometry, Polygon):
        geometry = MultiPolygon(geometry, srid=4326)
    elif not isinstance(geometry, MultiPolygon):
        # buffer(0) on a bow-tie can give a collection; keep its polygons.
        polygons = [part for part in geometry if isinstance(part, Polygon) and not part.empty]
        if not polygons:
            return None
        geometry = MultiPolygon(*polygons, srid=4326)
    geometry.srid = 4326
    return geometry


def outline_of(geometry):
    """A GeoJSON geometry dict as a 2D MultiPolygon in SRID 4326, or None.

    An outline that is not valid as drawn is repaired with ``buffer(0)``. A
    point, a line, a missing geometry or coordinates GEOS cannot read give
    None: the feature has no readable outline.
    """
    if not isinstance(geometry, dict) or geometry.get("type") not in ("Polygon", "MultiPolygon"):
        return None
    flat = dict(
        geometry, coordinates=geofiles.two_dimensional(geometry.get("coordinates") or [])
    )
    try:
        geos = GEOSGeometry(json.dumps(flat), srid=4326)
        if not geos.valid:
            geos = geos.buffer(0)
        return _multipolygon(geos)
    except (GDALException, GEOSException, ValueError, TypeError):
        return None


def joined(outlines):
    """One MultiPolygon holding every outline of a use area."""
    if len(outlines) == 1:
        return outlines[0]
    whole = MultiPolygon(*[part for outline in outlines for part in outline], srid=4326)
    if not whole.valid:
        # Overlapping outlines dissolve into one.
        repaired = _multipolygon(whole.buffer(0))
        if repaired is not None:
            whole = repaired
    return whole


def acres_of(outline):
    """The outline's area in acres, measured in California Albers (EPSG 3310)."""
    return outline.transform(ACRES_SRID, clone=True).area / SQUARE_METERS_PER_ACRE


def site_boundary():
    """The union of the site's Boundary geometries, or None when it has none."""
    return Boundary.objects.aggregate(union=Union("geometry"))["union"]


# ---------------------------------------------------------------------------
# Deciding what each feature is
# ---------------------------------------------------------------------------


def _numbers_on_file(numbers):
    on_file = set()
    numbers = list(numbers)
    for start in range(0, len(numbers), _LOOKUP_BATCH):
        batch = numbers[start : start + _LOOKUP_BATCH]
        on_file.update(
            Parcel.objects.filter(parcel_number__in=batch).values_list(
                "parcel_number", flat=True
            )
        )
    return on_file


def plan_features(features, mapping, boundary=None):
    """What importing ``features`` with ``mapping`` would do. Writes nothing.

    ``boundary`` is the site's boundary (``site_boundary()``); with None the
    outside count does not apply. Returns a dict:

    * ``new``: a dict (``number``, ``owner``, ``geometry``) for each use area
      Import would create, and ``acres``, their summed area rounded to whole
      acres;
    * ``on_file``, ``outside``: use areas skipped, counted;
    * ``unreadable``: features with a number and no readable outline, counted,
      and ``unreadable_numbers``: their numbers, in file order;
    * ``no_number``, ``too_long``: features without a parcel number and with
      one over ``NUMBER_MAX_LENGTH`` characters (never cut down), counted.

    A feature is checked for its number first, so one with no number is never
    also counted as unreadable. A number already on file is counted as on file
    before it is judged against the boundary.
    """
    number_column = mapping.get("parcel_number", "")
    owner_column = mapping.get("owner_name", "")
    groups = {}
    unreadable_numbers = []
    no_number = 0
    too_long = 0
    for feature in features:
        properties = feature.get("properties") or {}
        number = _text(properties.get(number_column)) if number_column else ""
        if not number:
            no_number += 1
            continue
        if len(number) > NUMBER_MAX_LENGTH:
            too_long += 1
            continue
        outline = outline_of(feature.get("geometry"))
        if outline is None:
            unreadable_numbers.append(number)
            continue
        group = groups.get(number)
        if group is None:
            owner = _text(properties.get(owner_column)) if owner_column else ""
            groups[number] = {"owner": owner[:OWNER_MAX_LENGTH], "outlines": [outline]}
        else:
            group["outlines"].append(outline)

    on_file_numbers = _numbers_on_file(groups)
    prepared = boundary.prepared if boundary is not None else None
    new = []
    on_file = 0
    outside = 0
    square_acres = 0.0
    for number, group in groups.items():
        if number in on_file_numbers:
            on_file += 1
            continue
        outline = joined(group["outlines"])
        if prepared is not None and not prepared.contains(outline.point_on_surface):
            outside += 1
            continue
        new.append({"number": number, "owner": group["owner"], "geometry": outline})
        square_acres += acres_of(outline)
    return {
        "new": new,
        "acres": int(math.floor(square_acres + 0.5)),
        "on_file": on_file,
        "outside": outside,
        "unreadable": len(unreadable_numbers),
        "unreadable_numbers": unreadable_numbers,
        "no_number": no_number,
        "too_long": too_long,
    }


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------


def commit_stored_use_areas(pending):
    """Write the new use areas of the stored file with the confirmed column matches.

    Runs in the import worker (``core/pending_imports.py``), which has opened
    the change-history context; returns the context the result block shows.
    The file is read and counted again here, so a number added since the
    preview is on file and left alone. ``area_acres`` is filled in by
    ``parcels/signals.py`` as each use area is saved.
    """
    with pending_imports.stored_file(pending) as file:
        read = read_file(file)
    plan = plan_features(
        read["features"], pending.settings.get("mapping", {}), site_boundary()
    )
    with transaction.atomic():
        for item in plan["new"]:
            Parcel.objects.create(
                parcel_number=item["number"],
                owner_name=item["owner"],
                geometry=item["geometry"],
                status="active",
            )
    # The result names the acres now on record, which parcels/signals.py
    # measured as each use area was saved, so it matches the use areas list.
    stored = Parcel.objects.filter(
        parcel_number__in=[item["number"] for item in plan["new"]]
    ).aggregate(total=Sum("area_acres"))["total"]
    acres = int(math.floor(float(stored) + 0.5)) if stored is not None else plan["acres"]
    return {"created": len(plan["new"]), "acres": acres}
