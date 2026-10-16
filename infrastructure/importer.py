# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Bulk infrastructure import engine.

Four UI-independent functions the import views are thin glue over:

  parse_upload(file, filename)          -> {"columns": [...], "rows": [...]}
  auto_map_columns(columns, infra_type) -> {model_field: source_column}
  validate_rows(rows, mapping, infra_type, existing_reg_ids)
                                        -> [{index, data, errors, warnings}]
  commit_rows(valid_results, infra_type) -> int  (number created)

The GDAL/GeoJSON/shapefile/KML parser helpers live in core/geofiles.py
(150-03), shared with the Setup Wizard, and are re-exported here under their
old names. CSV is added via stdlib csv.

Each parsed row is a flat dict of source-column -> string value. Spatial
formats synthesize a `__geometry__` column holding the feature geometry as a
GeoJSON string, so the rest of the pipeline treats geometry like any other
mapped column.
"""

import csv
import io
import json
import math
import zipfile
from decimal import Decimal, InvalidOperation

from django.contrib.gis.gdal import GDALException
from django.contrib.gis.geos import (
    GEOSException,
    GEOSGeometry,
    Point,
)
from django.db import transaction

from core.geofiles import (  # noqa: F401  re-exported under their old names (150-03)
    MAX_EXTRACTED_BYTES,
    MAX_UPLOAD_BYTES,
    _extract_features_from_datasource,
    _parse_geojson_file,
    _parse_kml_file,
    _parse_shapefile_zip,
    _validate_zip_entries,
)
from core.modules import is_enabled
from parcels.models import Parcel
from wells.models import MEASUREMENT_METHOD_CHOICES, PUMP_TYPE_CHOICES

# Synthetic column name carrying a feature geometry as a GeoJSON string.
GEOMETRY_COL = "__geometry__"

# Hard cap on a single import (preserved from the old infrastructure_upload).
MAX_ROWS = 500

# The byte ceilings (25 MB raw upload, 50 MB extracted from a zip) live in
# core/geofiles.py beside the readers that enforce them (150-03). Both names
# stay importable from here: parse_upload checks MAX_UPLOAD_BYTES below, and
# callers read importer.MAX_UPLOAD_BYTES. The archive readers read the caps
# from core.geofiles, so a test that shrinks one patches it there.

#: The whole-file messages Brent approved (150.1-02 screen 18, message V,
#: 2026-10-15 17:55; the CSV ones are the surface and lab imports' words,
#: reused as approved). This module is optional and may not import the
#: surface module's copies, so the sentences are repeated here.
NO_FILE_MESSAGE = "Choose a file to upload."
WRONG_TYPE_MESSAGE = (
    "This page imports .csv, .zip, .geojson, .json and .kml files only. "
    "Save the file as CSV and upload it again."
)
NO_COLUMNS_MESSAGE = "This file has no column names on its first line."
NO_ROWS_MESSAGE = "This file has column names but no rows below them."
NO_FEATURES_MESSAGE = "This file has no map features."
ROWS_NOT_RECEIVED_MESSAGE = (
    "OpenH2O did not receive the file's rows from the preview. "
    "Upload the file again."
)
_CHECK_IN_GIS = "Check that the file opens in a GIS program, then upload it again."
NOT_GEOJSON_MESSAGE = f"OpenH2O cannot read this file as GeoJSON. {_CHECK_IN_GIS}"
NOT_KML_MESSAGE = f"OpenH2O cannot read this file as KML. {_CHECK_IN_GIS}"
NOT_ZIP_MESSAGE = "OpenH2O cannot open this file as a zip archive."
NOT_SHAPEFILE_MESSAGE = (
    f"OpenH2O cannot read the shapefile in this zip file. {_CHECK_IN_GIS}"
)


def too_large_message(size):
    """The size is rounded UP, so a file over the cap never reads as equal to it."""
    mb = 1024 * 1024
    return (
        f"This file is {math.ceil(size / mb)} MB. "
        f"OpenH2O imports files of up to {MAX_UPLOAD_BYTES // mb} MB."
    )


def is_map_rows(rows):
    """True when the rows came from a shapefile, GeoJSON or KML file.

    Only the map readers add the GEOMETRY_COL key, so a CSV row never has it.
    A map file has no spreadsheet rows: its features are numbered from 1 in
    the file's order (Brent, message V).
    """
    return bool(rows) and GEOMETRY_COL in rows[0]


def row_cap_message(row_count, map_file=False):
    if map_file:
        return (
            f"This file has {row_count:,} map features, and OpenH2O imports up to "
            f"{MAX_ROWS:,} map features from one file. Split the file and import "
            "each part."
        )
    return (
        f"This file has {row_count:,} rows, and OpenH2O imports up to "
        f"{MAX_ROWS:,} rows from one file. Split the file and import each part."
    )


def unexpected_error_message(exc):
    return (
        "An unexpected error stopped the import, and OpenH2O saved nothing "
        f"from this file. Details: {type(exc).__name__}: {exc}"
    )


# ---------------------------------------------------------------------------
# parse_upload
# ---------------------------------------------------------------------------


def parse_upload(file, filename):
    """Parse an uploaded file into {"columns": [...], "rows": [dict, ...]}.

    CSV via csv.DictReader. GeoJSON / .json / .zip (shapefile) / .kml reuse the
    GDAL helpers below, each row = feature properties + a synthesized
    __geometry__ GeoJSON string.

    Raises ImportError with the sentence the page shows on: a file over the
    size cap, an unsupported extension, a damaged map file (these were server
    errors before message V), no rows or map features, or > MAX_ROWS of them.
    """
    name = (filename or "").lower()

    # Reject an oversized file up front, before we stream it to disk or parse it.
    # (Django's DATA_UPLOAD_MAX_MEMORY_SIZE does not cover file uploads.)
    size = getattr(file, "size", None)
    if size is not None and size > MAX_UPLOAD_BYTES:
        raise ImportError(too_large_message(size))

    map_file = True
    if name.endswith(".csv"):
        map_file = False
        rows, columns = _parse_csv(file)
        if not columns:
            raise ImportError(NO_COLUMNS_MESSAGE)
    elif name.endswith((".geojson", ".json")):
        try:
            features = _parse_geojson_file(file)
        except (ValueError, AttributeError, TypeError):
            # ValueError covers json.JSONDecodeError and UnicodeDecodeError;
            # AttributeError / TypeError a JSON value that is not GeoJSON.
            raise ImportError(NOT_GEOJSON_MESSAGE)
        rows, columns = _features_to_rows(features)
    elif name.endswith(".zip"):
        try:
            features = _parse_shapefile_zip(file)
        except zipfile.BadZipFile:
            raise ImportError(NOT_ZIP_MESSAGE)
        except GDALException:
            raise ImportError(NOT_SHAPEFILE_MESSAGE)
        rows, columns = _features_to_rows(features)
    elif name.endswith(".kml"):
        try:
            features = _parse_kml_file(file)
        except GDALException:
            raise ImportError(NOT_KML_MESSAGE)
        rows, columns = _features_to_rows(features)
    else:
        raise ImportError(WRONG_TYPE_MESSAGE)

    if len(rows) > MAX_ROWS:
        raise ImportError(row_cap_message(len(rows), map_file=map_file))
    if not rows:
        raise ImportError(NO_FEATURES_MESSAGE if map_file else NO_ROWS_MESSAGE)

    return {"columns": columns, "rows": rows}


def _parse_csv(file):
    raw = file.read()
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8-sig")  # tolerate a BOM from Excel exports
    reader = csv.DictReader(io.StringIO(raw))
    columns = list(reader.fieldnames or [])
    rows = []
    for row in reader:
        # Normalize None values (short rows) to empty strings.
        rows.append({k: ("" if v is None else v) for k, v in row.items()})
    return rows, columns


def _features_to_rows(features):
    """Turn parser features (geometry + properties) into flat rows.

    Columns are the union of all property keys plus __geometry__, with
    __geometry__ kept last so it reads as a derived field in the mapping UI.
    """
    rows = []
    seen_cols = []
    for feat in features:
        row = dict(feat.get("properties") or {})
        geom = feat.get("geometry")
        row[GEOMETRY_COL] = json.dumps(geom) if geom is not None else ""
        for key in row:
            if key not in seen_cols and key != GEOMETRY_COL:
                seen_cols.append(key)
        rows.append(row)
    columns = seen_cols + ([GEOMETRY_COL] if rows else [])
    return rows, columns


# ---------------------------------------------------------------------------
# auto_map_columns
# ---------------------------------------------------------------------------

# Per-type alias tables. Keys are model fields; values are sets of accepted
# source-column spellings (matched case- and punctuation-insensitively).
#: State OSWCR export column names (`wells-oswcr.csv`, header read 2026-09-20)
#: mixed in below where a state column is the best available guess. OSWCR
#: carries no well-name column at all. `WCRNUMBER` is the one column present
#: and non-blank on every row, so it is the best-guess source for BOTH `name`
#: and `wcr_number`; the mapping step still lets the operator override either
#: one (ISS-179, ISS-190).
_WELL_ALIASES = {
    "name": {"name", "well_name", "well", "wcrnumber"},
    "well_registration_id": {"reg_id", "registration_id", "well_id", "local_id"},
    "wcr_number": {"wcr", "wcr_no", "wcr_number", "completion_report", "wcrnumber"},
    "state_well_number": {"swn", "state_well_no", "state_well_number"},
    "capacity_gpm": {"capacity", "capacity_gpm", "gpm", "max_gpm", "pump_capacity"},
    "tested_yield_gpm": {"yield", "yield_gpm", "tested_yield", "well_yield"},
    "depth_ft": {"depth", "total_depth", "depth_ft", "totalcompleteddepth"},
    "casing_diameter_in": {"casing_dia", "casing_diameter", "casing_in"},
    "casing_material": {"casing_material", "casing_mat"},
    "screen_top_ft": {"screen_top", "perf_top", "screen_top_ft"},
    "screen_bottom_ft": {"screen_bottom", "perf_bottom", "screen_bottom_ft"},
    "pump_type": {"pump_type", "pump"},
    "year_pumping_began": {"year_pumping_began", "year_pumping", "pumping_year"},
    "measurement_method": {"measurement_method", "meas_method", "method"},
    "owner_name": {"owner", "owner_name", "landowner"},
    "latitude": {"lat", "latitude", "y", "decimallatitude"},
    "longitude": {"lon", "lng", "long", "longitude", "x", "decimallongitude"},
    "geometry": {GEOMETRY_COL, "geometry", "wkt", "geom"},
}

_DIVERSION_ALIASES = {
    # "appl_pod" replaces "pod_name" as the state alias (146-02 D2): the
    # shape-1 POD file (points-of-diversion.csv, header read 2026-09-20)
    # carries BOTH `APPL_POD` (the state's own natural POD id, populated on
    # every row) and `POD_NAME` (blank on every row in the real export).
    # auto_map_columns picks one column per field from a Python set with no
    # tie-break when two columns both match, so the two could not safely
    # coexist in this set -- keeping "pod_name" would risk silently mapping
    # `name` to the always-blank column half the time. The mapping step still
    # lets the operator override for a file where POD_NAME really is filled in.
    "name": {"name", "diversion_name", "appl_pod"},
    "stream_name": {"stream", "stream_name", "source", "source_name"},
    # 146-03 Task 3: the ditch tender's own alias for the headgate (the
    # 145-01 memo's crosswalk layer), never the state's own column -- the
    # state's export carries no such name.
    "local_name": {"local_name", "known_as", "ditch_name", "headgate_name"},
    "max_rate_cfs": {"max_rate_cfs", "max_rate", "cfs", "rate_cfs", "direct_diversion_rate"},
    "latitude": {"lat", "latitude", "y"},
    "longitude": {"lon", "lng", "long", "longitude", "x"},
    "geometry": {GEOMETRY_COL, "geometry", "wkt", "geom"},
    # 146-02 D2: the state's POD file names the right by `APPL_ID`; resolved
    # against WaterRight.right_id in validate_rows, never taken as a raw FK pk.
    "water_right": {"appl_id", "water_right", "right_id", "water_right_id"},
    # 146-02 D3: when present and matching a Parcel, writes a
    # PointOfDiversionParcel at fraction 1.0 (commit_rows).
    "parcel_number": {"parcel_number", "parcel_no", "apn"},
}

_RECHARGE_ALIASES = {
    "name": {"name", "site_name", "recharge_name"},
    "site_type": {"site_type", "type", "recharge_type"},
    "capacity_acre_feet": {"capacity_acre_feet", "capacity_af", "capacity", "af"},
    "operator": {"operator", "operated_by", "agency"},
    "latitude": {"lat", "latitude", "y"},
    "longitude": {"lon", "lng", "long", "longitude", "x"},
    "geometry": {GEOMETRY_COL, "geometry", "wkt", "geom"},
}

ALIASES = {
    "well": _WELL_ALIASES,
    "diversion": _DIVERSION_ALIASES,
    "recharge_site": _RECHARGE_ALIASES,
    "storage": _RECHARGE_ALIASES,
}

# Labels for the column-matching step: the approved Add page and well page
# labels word for word, and "Geometry" and "Water right application number"
# (Brent, 150.1-02 screen 18 message W, 2026-10-15 18:12).
FIELD_LABELS = {
    "name": "Name",
    "well_registration_id": "Local registration ID",
    "wcr_number": "WCR number",
    "state_well_number": "State well number",
    "capacity_gpm": "Capacity (gpm)",
    "tested_yield_gpm": "Tested yield (gpm)",
    "depth_ft": "Depth (ft)",
    "casing_diameter_in": "Casing diameter (in)",
    "casing_material": "Casing material",
    "screen_top_ft": "Screen top (ft)",
    "screen_bottom_ft": "Screen bottom (ft)",
    "pump_type": "Pump type",
    "year_pumping_began": "Year pumping began",
    "measurement_method": "Measurement method",
    "owner_name": "Owner name",
    "latitude": "Latitude",
    "longitude": "Longitude",
    "geometry": "Geometry",
    "stream_name": "Stream name",
    "local_name": "Known locally as",
    "max_rate_cfs": "Max rate (cfs)",
    "site_type": "Site type",
    "capacity_acre_feet": "Capacity per fill (acre-feet)",
    "operator": "Operator",
    "water_right": "Water right application number",
    "parcel_number": "Parcel number",
}


#: What a map file's geometry column is called on the matching step and in
#: the sample table (message W row 7); the key itself stays GEOMETRY_COL.
GEOMETRY_COL_LABEL = "The file's geometry"


def sample_cell(column, value):
    """A sample-table cell: a map file's geometry shows only its shape type."""
    if column == GEOMETRY_COL:
        try:
            return json.loads(value).get("type", "") if value else ""
        except (ValueError, AttributeError):
            return ""
    return value


def import_fields(infra_type):
    """Ordered [(model_field, label)] the import UI offers a column mapping for."""
    table = ALIASES.get(infra_type, _WELL_ALIASES)
    return [(field, FIELD_LABELS.get(field, field)) for field in table.keys()]


def _normalize(col):
    """Lowercase, strip, collapse any run of non-alphanumerics to single '_'."""
    out = []
    prev_us = False
    for ch in col.strip().lower():
        if ch.isalnum():
            out.append(ch)
            prev_us = False
        elif not prev_us:
            out.append("_")
            prev_us = True
    return "".join(out).strip("_")


def auto_map_columns(columns, infra_type):
    """Best-effort {model_field: source_column} guess; unmatched columns absent.

    Deterministic: iterates the alias table in definition order and, for each
    model field, takes the first source column whose normalized form matches one
    of the field's aliases.
    """
    alias_table = ALIASES.get(infra_type, _WELL_ALIASES)
    norm_to_source = {}
    for col in columns:
        norm = _normalize(col)
        norm_to_source.setdefault(norm, col)  # first spelling wins, deterministic

    mapping = {}
    for field, aliases in alias_table.items():
        for alias in aliases:
            norm_alias = _normalize(alias)
            if norm_alias in norm_to_source:
                mapping[field] = norm_to_source[norm_alias]
                break
    return mapping


# ---------------------------------------------------------------------------
# validate_rows
# ---------------------------------------------------------------------------

# Numeric (Decimal) fields per type, used for coercion + "not a number" errors.
_DECIMAL_FIELDS = {
    "well": [
        "capacity_gpm",
        "tested_yield_gpm",
        "depth_ft",
        "casing_diameter_in",
        "screen_top_ft",
        "screen_bottom_ft",
    ],
    "diversion": ["max_rate_cfs"],
    "recharge_site": ["capacity_acre_feet"],
    "storage": ["capacity_acre_feet"],
}

_CHOICE_FIELDS = {
    "well": {
        "measurement_method": {c[0] for c in MEASUREMENT_METHOD_CHOICES},
        "pump_type": {c[0] for c in PUMP_TYPE_CHOICES},
    },
}

# Free-text fields copied straight through when mapped + present.
_STRING_FIELDS = {
    "well": ["wcr_number", "state_well_number", "casing_material", "owner_name"],
    "diversion": ["stream_name", "local_name"],
    "recharge_site": ["site_type", "operator"],
    "storage": ["site_type", "operator"],
}

# A box around the United States, Alaska, Hawaii and Puerto Rico included
# (Brent, 2026-10-12 09:17 PDT: "Yes"; it was a box around California).
_US_LAT = (17.0, 72.0)
_US_LON = (-180.0, -64.0)


#: Each numeric field as a row error names it (Brent, 150.1-02 screen 18
#: message X, 2026-10-15 18:25): the field in plain words, never the file's
#: own column heading, which can be anything ("lat", "Casing Dia").
FIELD_NOUNS = {
    "capacity_gpm": "capacity",
    "tested_yield_gpm": "tested yield",
    "depth_ft": "depth",
    "casing_diameter_in": "casing diameter",
    "screen_top_ft": "screen top",
    "screen_bottom_ft": "screen bottom",
    "max_rate_cfs": "max rate",
    "capacity_acre_feet": "capacity per fill",
}

#: The matching-step refusals (message X rows 2 and 3): with no column matched
#: to the name or to a location, every row used to fail with the same error.
NAME_NOT_MATCHED_MESSAGE = "Choose the file's column for the name, then press Create."
LOCATION_NOT_MATCHED_MESSAGE = (
    "Choose the file's columns for latitude and longitude, or the file's "
    "geometry column, then press Create."
)


def mapping_refusal(mapping):
    """The sentence that keeps the matching step on screen, or None."""
    if not mapping.get("name"):
        return NAME_NOT_MATCHED_MESSAGE
    if not mapping.get("geometry") and not (
        mapping.get("latitude") and mapping.get("longitude")
    ):
        return LOCATION_NOT_MATCHED_MESSAGE
    return None


def outside_us_message(lat, lon):
    """The location sentence Brent approved 2026-10-12 09:17 (reused in message X)."""
    return (
        f"location ({lat}, {lon}) is outside the United States; check the sign "
        "of the longitude."
    )


def existing_names(infra_type):
    """The names already on file for the type the import creates.

    Brent, 150.1-02 screen 18 message V (2026-10-15 17:55): every type skips a
    row whose name is already on file or appears earlier in the file. Points
    of diversion, storage ponds and recharge sites were never checked, so a
    file imported twice created its records twice. Storage ponds and recharge
    sites are both RechargeSite rows, so they share one set of names.
    """
    if infra_type == "well":
        from wells.models import Well

        return set(Well.objects.values_list("name", flat=True))
    if infra_type == "diversion" and is_enabled("surface"):
        from surface.models import PointOfDiversion

        return set(PointOfDiversion.objects.values_list("name", flat=True))
    if infra_type in ("recharge_site", "storage") and is_enabled("recharge"):
        from recharge.models import RechargeSite

        return set(RechargeSite.objects.values_list("name", flat=True))
    return set()


def validate_rows(rows, mapping, infra_type, existing_reg_ids, existing_names=None):
    """Validate + coerce a batch into writer-ready `data` dicts.

    Returns a list of {index, data, errors, warnings}. A row with any errors is
    skipped by commit_rows; warnings (e.g. an off-list choice value) are kept.
    `existing_names` (from `existing_names()`) makes a row whose name is already
    on file an error; a name repeated in the file is an error either way.
    """
    results = []
    seen_reg_ids = set()
    existing = {r for r in (existing_reg_ids or set())}
    names_on_file = set(existing_names or ())
    seen_names = set()

    decimal_fields = _DECIMAL_FIELDS.get(infra_type, [])
    choice_fields = _CHOICE_FIELDS.get(infra_type, {})

    # 146-02 D2/D3: built once, not per row. `surface` is a truly-optional
    # module (Phase 87), so its model is imported locally and only when a
    # diversion row is actually being validated -- the same guard commit_rows
    # already uses for this exact model. In practice this branch is only
    # reached when the deployment has `surface` enabled at all (the view's
    # `_import_type` already filtered to `supported_add_types()`), but the
    # local import stays defensive rather than assuming that of a function
    # other callers could reach directly.
    existing_rights = {}
    if infra_type == "diversion" and mapping.get("water_right") and is_enabled("surface"):
        from surface.models import WaterRight

        existing_rights = dict(WaterRight.objects.values_list("right_id", "pk"))

    existing_parcels = {}
    if infra_type == "diversion" and mapping.get("parcel_number"):
        existing_parcels = dict(Parcel.objects.values_list("parcel_number", "pk"))

    for index, row in enumerate(rows):
        errors = []
        warnings = []
        data = {}

        def src(field):
            col = mapping.get(field)
            if not col:
                return ""
            return (row.get(col) or "").strip()

        # --- name (required for every type) ---
        name = src("name")
        if not name:
            errors.append("The name is blank.")
        elif name in names_on_file:
            errors.append(f"The name {name} is already on file.")
        elif name in seen_names:
            errors.append(f"The name {name} appears earlier in this file.")
        if name:
            seen_names.add(name)
        data["name"] = name

        # --- location: geometry column OR lat+lon pair ---
        location = _resolve_location(row, mapping, errors, map_row=GEOMETRY_COL in row)
        if location is not None:
            data["location"] = location

        # --- duplicate registration id (wells) ---
        if infra_type == "well":
            reg = src("well_registration_id")
            if reg:
                if reg in existing:
                    errors.append(f"Registration ID {reg} is already on file.")
                elif reg in seen_reg_ids:
                    errors.append(f"Registration ID {reg} appears earlier in this file.")
                seen_reg_ids.add(reg)
                data["well_registration_id"] = reg

        # --- year_pumping_began (int, wells) ---
        if infra_type == "well":
            year = src("year_pumping_began")
            if year:
                try:
                    data["year_pumping_began"] = int(Decimal(year))
                except (InvalidOperation, ValueError):
                    errors.append(
                        f"The year pumping began is '{year}', which is not a year."
                    )

        # --- numeric/decimal fields ---
        for field in decimal_fields:
            val = src(field)
            if val:
                try:
                    data[field] = Decimal(val)
                except (InvalidOperation, ValueError):
                    errors.append(
                        f"The {FIELD_NOUNS.get(field, field)} is '{val}', which is "
                        "not a number."
                    )

        # --- choice fields: off-list = warning, value kept ---
        for field, valid in choice_fields.items():
            val = src(field)
            if val:
                if val not in valid:
                    warnings.append(
                        f"{field} '{val}' is not a standard choice; kept as-is."
                    )
                data[field] = val

        # --- plain string passthrough fields ---
        for field in _STRING_FIELDS.get(infra_type, []):
            val = src(field)
            if val:
                data[field] = val

        # --- water right (diversion only, 146-02 D2) ---
        # An unresolved value is a row error naming the value -- never
        # silently None, which is how a diversion used to lose its right on
        # a typo'd APPL_ID with nobody the wiser until CalWATRS filing.
        if infra_type == "diversion":
            right_val = src("water_right")
            if right_val:
                right_pk = existing_rights.get(right_val)
                if right_pk is None:
                    errors.append(
                        f"No water right on file has the application number "
                        f"{right_val}. Import the water right first, or correct "
                        "the number in the file."
                    )
                else:
                    data["water_right_id"] = right_pk

        # --- parcel_number -> a PointOfDiversionParcel at fraction 1.0
        #     (diversion only, 146-02 D3). Present-but-unmatched is not an
        #     error (a operator's PARCEL_NUMBER may name a use area not yet
        #     entered) -- only a MATCH links anything, and the preview says
        #     so via the "warnings" list rather than staying silent either way.
        if infra_type == "diversion":
            parcel_val = src("parcel_number")
            if parcel_val:
                parcel_pk = existing_parcels.get(parcel_val)
                if parcel_pk is not None:
                    data["_pod_parcel_id"] = parcel_pk
                    warnings.append(
                        f"use area {parcel_val} will be linked at share 1.0000."
                    )
                else:
                    warnings.append(
                        f"parcel_number '{parcel_val}' matches no use area on "
                        "record; not linked."
                    )

        results.append(
            {"index": index, "data": data, "errors": errors, "warnings": warnings}
        )

    return results


def _resolve_location(row, mapping, errors, map_row=False):
    """Return a Point (4326) from a geometry column or a lat/lon pair, or None.

    Appends an error and returns None when no usable location is present.
    The sentences are Brent's (150.1-02 screen 18 message X, 2026-10-15
    18:25); a geometry is held to the same United States box as a typed
    latitude and longitude (it was checked only against the world).
    """
    geom_col = mapping.get("geometry")
    if geom_col:
        raw = (row.get(geom_col) or "").strip()
        if raw:
            point = _point_from_geometry(raw)
            if point is None:
                xy = _first_xy(raw)
                if xy is not None:
                    errors.append(outside_us_message(round(xy[1], 6), round(xy[0], 6)))
                elif map_row:
                    errors.append("OpenH2O cannot read this feature's geometry.")
                else:
                    errors.append(
                        f"The geometry is '{raw}', which OpenH2O cannot read as "
                        "GeoJSON or WKT."
                    )
                return None
            if not _within_us(point.y, point.x):
                errors.append(outside_us_message(round(point.y, 6), round(point.x, 6)))
                return None
            return point
        if map_row:
            errors.append("This feature has no geometry.")
            return None

    lat_col = mapping.get("latitude")
    lon_col = mapping.get("longitude")
    lat_raw = (row.get(lat_col) or "").strip() if lat_col else ""
    lon_raw = (row.get(lon_col) or "").strip() if lon_col else ""
    if not lat_raw and not lon_raw:
        errors.append("This row has no location. Fill in the latitude and longitude.")
        return None
    values = {}
    bad = False
    for label, raw in (("latitude", lat_raw), ("longitude", lon_raw)):
        if not raw:
            errors.append(f"The {label} is blank.")
            bad = True
            continue
        try:
            values[label] = float(raw)
        except ValueError:
            errors.append(f"The {label} is '{raw}', which is not a number.")
            bad = True
    if bad:
        return None
    lat, lon = values["latitude"], values["longitude"]
    if not _within_us(lat, lon):
        errors.append(outside_us_message(lat, lon))
        return None
    return Point(lon, lat, srid=4326)


def _within_us(lat, lon):
    return (
        math.isfinite(lat) and math.isfinite(lon)
        and _US_LAT[0] <= lat <= _US_LAT[1] and _US_LON[0] <= lon <= _US_LON[1]
    )


def _first_xy(raw):
    """The first finite [x, y] of a GeoJSON geometry whose coordinates fall
    outside the world box, so the refusal can name where it lies; None when
    the text is not GeoJSON with numeric coordinates (it cannot be read)."""
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None
    coords = data.get("coordinates") if isinstance(data, dict) else None
    while isinstance(coords, (list, tuple)) and coords and isinstance(coords[0], (list, tuple)):
        coords = coords[0]
    if (
        isinstance(coords, (list, tuple)) and len(coords) >= 2
        and all(isinstance(c, (int, float)) and not isinstance(c, bool) for c in coords[:2])
        and all(math.isfinite(c) for c in coords[:2])
    ):
        x, y = float(coords[0]), float(coords[1])
        if not (-180.0 <= x <= 180.0 and -90.0 <= y <= 90.0):
            return x, y
    return None


def _coords_within_world(coords):
    """True iff every leaf [x, y(, z)] in a GeoJSON coordinate array is finite
    and within world bounds. Rejects NaN/Infinity (which json.loads accepts by
    default) and absurd extents before they reach GEOS."""
    if not isinstance(coords, (list, tuple)):
        return False
    if coords and isinstance(coords[0], (int, float)) and not isinstance(coords[0], bool):
        x = coords[0]
        y = coords[1] if len(coords) > 1 else 0.0
        if not (isinstance(x, (int, float)) and isinstance(y, (int, float))):
            return False
        if not (math.isfinite(x) and math.isfinite(y)):
            return False
        return -180.0 <= x <= 180.0 and -90.0 <= y <= 90.0
    return bool(coords) and all(_coords_within_world(c) for c in coords)


def _point_from_geometry(raw):
    """Best-effort Point from a GeoJSON/WKT geometry string (centroid if area).

    Returns None — never raises and never yields a degenerate point — for
    NaN/Infinity coords, coords outside world lon/lat bounds, or geometry GEOS
    cannot build or validate. A crafted feature becomes a skipped row, not a 500.
    """
    geom = None
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        data = None

    if isinstance(data, dict):
        coords = data.get("coordinates")
        if coords is not None and not _coords_within_world(coords):
            return None
        try:
            geom = GEOSGeometry(json.dumps(data), srid=4326)
        except (GEOSException, GDALException, ValueError, TypeError):
            return None
    if geom is None:
        try:
            geom = GEOSGeometry(raw, srid=4326)  # WKT fallback
        except (GEOSException, GDALException, ValueError, TypeError):
            return None

    # Reject or repair invalid geometry (self-intersection etc.) before deriving
    # a point, so a degenerate polygon never persists or 500s on .centroid.
    try:
        if not geom.valid:
            geom = geom.make_valid()
    except (GEOSException, GDALException, ValueError):
        return None

    if geom.geom_type == "Point":
        if not (math.isfinite(geom.x) and math.isfinite(geom.y)):
            return None
        return geom
    try:
        centroid = geom.centroid
    except (GEOSException, GDALException, ValueError):
        return None
    if not (math.isfinite(centroid.x) and math.isfinite(centroid.y)):
        return None
    return centroid


# ---------------------------------------------------------------------------
# commit_rows
# ---------------------------------------------------------------------------


#: infra_type -> the module that has to be enabled to create that row, and the
#: sentence appended as a row error when it is not (ISS-179). `well`, `diversion`
#: and `recharge_site`/`storage` each create a model from a truly-optional
#: module's app (`wells` is schema-resident and always importable, but a
#: deployment that switched it OFF must still get no NEW rows in its empty
#: table: `surface` and `recharge` are truly removed and their model imports
#: raise `RuntimeError` if reached with the app not installed). Checked BEFORE
#: the model is imported, never after, so a disabled module is a row error, not
#: a crash the per-row savepoint below has to catch.
_COMMIT_TYPE_MODULE = {
    "well": "wells",
    "diversion": "surface",
    "recharge_site": "recharge",
    "storage": "recharge",
}


def commit_rows(valid_results, infra_type):
    """Create records from the coerced `data` of error-free rows. Returns count.

    Wrapped in a single transaction. Errored rows are skipped. Per-row create()
    is fine here — wells/diversions/recharge sites have no save-time signals.

    Every model import is LOCAL to its own branch, guarded by `is_enabled()`
    (ISS-179): `commit_rows` used to import `RechargeSite` unconditionally
    before the type branch, so a `diversion` or `well` commit on a deployment
    without `recharge` raised `RuntimeError` before a single row was even
    looked at, a 500 that swallowed the whole import (shapes 1 and 4, three
    tries and two tries, zero records, no message). Now a row whose type's
    module is off is a reported row error, and every other row in the same
    batch still commits.
    """
    clean = [r for r in valid_results if not r["errors"] and r["data"].get("location")]
    created = 0

    with transaction.atomic():
        for result in clean:
            data = result["data"]
            module = _COMMIT_TYPE_MODULE.get(infra_type)
            if module is not None and not is_enabled(module):
                result["errors"].append(
                    f"the {module} module is not enabled on this deployment."
                )
                continue
            try:
                # Per-row savepoint: a single bad row (e.g. a geometry that
                # slipped validation) is rolled back and reported, not allowed
                # to poison the whole batch or surface as a 500.
                with transaction.atomic():
                    if infra_type == "well":
                        from wells.models import Well

                        Well.objects.create(**data)
                    elif infra_type == "diversion":
                        from surface.models import PointOfDiversion, PointOfDiversionParcel

                        row_data = dict(data)
                        # `_pod_parcel_id` (146-02 D3) is a Parcel pk resolved
                        # in validate_rows, not a PointOfDiversion field -- it
                        # has to come out before create() and is used AFTER,
                        # once the POD itself exists to link to.
                        parcel_id = row_data.pop("_pod_parcel_id", None)
                        row_data.setdefault("water_right_id", None)
                        pod = PointOfDiversion.objects.create(**row_data)
                        if parcel_id is not None:
                            PointOfDiversionParcel.objects.create(
                                point_of_diversion=pod,
                                parcel_id=parcel_id,
                                fraction=Decimal("1.0"),
                            )
                    elif infra_type in ("recharge_site", "storage"):
                        from recharge.models import RechargeSite

                        RechargeSite.objects.create(**data)
                    else:
                        continue
                created += 1
            except Exception as exc:
                # Brent, message X row 11: the failure keeps its details.
                result["errors"].append(
                    "An unexpected error stopped OpenH2O from saving this record. "
                    f"Details: {type(exc).__name__}: {exc}"
                )

    return created


# ---------------------------------------------------------------------------
# GDAL / spatial parser helpers
# ---------------------------------------------------------------------------
# The readers moved to core/geofiles.py (150-03, ISS-200) so the Setup Wizard,
# a module every deployment gets, can read a shapefile or KML without
# depending on this optional module. They are imported above and kept under
# their old names here, so parse_upload and every caller of
# infrastructure.importer._parse_* behave exactly as before.
