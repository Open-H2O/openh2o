# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Bulk infrastructure import engine.

Four UI-independent functions the import views are thin glue over:

  parse_upload(file, filename)          -> {"columns": [...], "rows": [...]}
  auto_map_columns(columns, infra_type) -> {model_field: source_column}
  validate_rows(rows, mapping, infra_type, existing_reg_ids)
                                        -> [{index, data, errors, warnings}]
  commit_rows(valid_results, infra_type) -> int  (number created)

The GDAL/GeoJSON/shapefile/KML parser helpers live here as the single parser
home; infrastructure.views imports them back. CSV is added via stdlib csv.

Each parsed row is a flat dict of source-column -> string value. Spatial
formats synthesize a `__geometry__` column holding the feature geometry as a
GeoJSON string, so the rest of the pipeline treats geometry like any other
mapped column.
"""

import csv
import io
import json
import math
import os
import shutil
import tempfile
import zipfile
from decimal import Decimal, InvalidOperation

from django.contrib.gis.gdal import DataSource, GDALException
from django.contrib.gis.geos import (
    GEOSException,
    GEOSGeometry,
    MultiPolygon,
    Point,
    Polygon,
)
from django.db import transaction

from wells.models import (
    MEASUREMENT_METHOD_CHOICES,
    PUMP_TYPE_CHOICES,
    Well,
)

# Synthetic column name carrying a feature geometry as a GeoJSON string.
GEOMETRY_COL = "__geometry__"

# Hard cap on a single import (preserved from the old infrastructure_upload).
MAX_ROWS = 500

# Hard byte ceilings so an oversized or zip-bomb upload can't exhaust the small
# VPS (2-4GB) before MAX_ROWS is even reached — MAX_ROWS is checked only AFTER a
# full parse, so it is no defense against a 5GB file. MAX_UPLOAD_BYTES bounds the
# raw uploaded file; MAX_EXTRACTED_BYTES bounds the total uncompressed bytes a
# zip is allowed to expand to (a small zip can decompress to gigabytes).
MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MB raw upload
MAX_EXTRACTED_BYTES = 50 * 1024 * 1024  # 50 MB total extracted from a zip


# ---------------------------------------------------------------------------
# parse_upload
# ---------------------------------------------------------------------------


def parse_upload(file, filename):
    """Parse an uploaded file into {"columns": [...], "rows": [dict, ...]}.

    CSV via csv.DictReader. GeoJSON / .json / .zip (shapefile) / .kml reuse the
    GDAL helpers below, each row = feature properties + a synthesized
    __geometry__ GeoJSON string.

    Raises ImportError on: unsupported extension, no rows, or > MAX_ROWS rows.
    """
    name = (filename or "").lower()

    # Reject an oversized file up front, before we stream it to disk or parse it.
    # (Django's DATA_UPLOAD_MAX_MEMORY_SIZE does not cover file uploads.)
    size = getattr(file, "size", None)
    if size is not None and size > MAX_UPLOAD_BYTES:
        raise ImportError(
            f"File is too large ({size // (1024 * 1024)} MB); the upload cap is "
            f"{MAX_UPLOAD_BYTES // (1024 * 1024)} MB. Please split it into smaller files."
        )

    if name.endswith(".csv"):
        rows, columns = _parse_csv(file)
    elif name.endswith((".geojson", ".json")):
        rows, columns = _features_to_rows(_parse_geojson_file(file))
    elif name.endswith(".zip"):
        rows, columns = _features_to_rows(_parse_shapefile_zip(file))
    elif name.endswith(".kml"):
        rows, columns = _features_to_rows(_parse_kml_file(file))
    else:
        raise ImportError(
            "Unsupported format. Use .csv, .geojson, .json, .zip (shapefile), or .kml."
        )

    if len(rows) > MAX_ROWS:
        raise ImportError(
            f"File contains {len(rows)} rows, over the {MAX_ROWS}-row import cap. "
            "Please split it into smaller files."
        )
    if not rows:
        raise ImportError("No rows found in the uploaded file.")

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
_WELL_ALIASES = {
    "name": {"name", "well_name", "well"},
    "well_registration_id": {"reg_id", "registration_id", "well_id", "local_id"},
    "wcr_number": {"wcr", "wcr_no", "wcr_number", "completion_report"},
    "state_well_number": {"swn", "state_well_no", "state_well_number"},
    "capacity_gpm": {"capacity", "capacity_gpm", "gpm", "max_gpm", "pump_capacity"},
    "tested_yield_gpm": {"yield", "yield_gpm", "tested_yield", "well_yield"},
    "depth_ft": {"depth", "total_depth", "depth_ft"},
    "casing_diameter_in": {"casing_dia", "casing_diameter", "casing_in"},
    "casing_material": {"casing_material", "casing_mat"},
    "screen_top_ft": {"screen_top", "perf_top", "screen_top_ft"},
    "screen_bottom_ft": {"screen_bottom", "perf_bottom", "screen_bottom_ft"},
    "pump_type": {"pump_type", "pump"},
    "year_pumping_began": {"year_pumping_began", "year_pumping", "pumping_year"},
    "measurement_method": {"measurement_method", "meas_method", "method"},
    "owner_name": {"owner", "owner_name", "landowner"},
    "latitude": {"lat", "latitude", "y"},
    "longitude": {"lon", "lng", "long", "longitude", "x"},
    "geometry": {GEOMETRY_COL, "geometry", "wkt", "geom"},
}

_DIVERSION_ALIASES = {
    "name": {"name", "pod_name", "diversion_name"},
    "stream_name": {"stream", "stream_name", "source", "source_name"},
    "max_rate_cfs": {"max_rate_cfs", "max_rate", "cfs", "rate_cfs"},
    "latitude": {"lat", "latitude", "y"},
    "longitude": {"lon", "lng", "long", "longitude", "x"},
    "geometry": {GEOMETRY_COL, "geometry", "wkt", "geom"},
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

# Human-readable labels for the column-mapping UI. A GSA user sees "Casing
# diameter (in)", not "casing_diameter_in".
FIELD_LABELS = {
    "name": "Name",
    "well_registration_id": "Registration ID (local)",
    "wcr_number": "WCR Number",
    "state_well_number": "State Well Number",
    "capacity_gpm": "Capacity (gpm)",
    "tested_yield_gpm": "Tested Yield (gpm)",
    "depth_ft": "Depth (ft)",
    "casing_diameter_in": "Casing Diameter (in)",
    "casing_material": "Casing Material",
    "screen_top_ft": "Screen Top (ft)",
    "screen_bottom_ft": "Screen Bottom (ft)",
    "pump_type": "Pump Type",
    "year_pumping_began": "Year Pumping Began",
    "measurement_method": "Measurement Method",
    "owner_name": "Owner Name",
    "latitude": "Latitude",
    "longitude": "Longitude",
    "geometry": "Geometry (GeoJSON / WKT)",
    "stream_name": "Stream Name",
    "max_rate_cfs": "Max Rate (cfs)",
    "site_type": "Site Type",
    "capacity_acre_feet": "Capacity (acre-feet)",
    "operator": "Operator",
}


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
    "diversion": ["stream_name"],
    "recharge_site": ["site_type", "operator"],
    "storage": ["site_type", "operator"],
}

_CA_LAT = (32.0, 42.5)
_CA_LON = (-125.0, -113.0)


def validate_rows(rows, mapping, infra_type, existing_reg_ids):
    """Validate + coerce a batch into writer-ready `data` dicts.

    Returns a list of {index, data, errors, warnings}. A row with any errors is
    skipped by commit_rows; warnings (e.g. an off-list choice value) are kept.
    """
    results = []
    seen_reg_ids = set()
    existing = {r for r in (existing_reg_ids or set())}

    decimal_fields = _DECIMAL_FIELDS.get(infra_type, [])
    choice_fields = _CHOICE_FIELDS.get(infra_type, {})

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
            errors.append("name is required (blank or unmapped).")
        data["name"] = name

        # --- location: geometry column OR lat+lon pair ---
        location = _resolve_location(row, mapping, errors)
        if location is not None:
            data["location"] = location

        # --- duplicate registration id (wells) ---
        if infra_type == "well":
            reg = src("well_registration_id")
            if reg:
                if reg in existing or reg in seen_reg_ids:
                    errors.append(f"duplicate well_registration_id '{reg}'.")
                seen_reg_ids.add(reg)
                data["well_registration_id"] = reg

        # --- year_pumping_began (int, wells) ---
        if infra_type == "well":
            year = src("year_pumping_began")
            if year:
                try:
                    data["year_pumping_began"] = int(Decimal(year))
                except (InvalidOperation, ValueError):
                    errors.append(f"year_pumping_began is not a number: '{year}'.")

        # --- numeric/decimal fields ---
        for field in decimal_fields:
            val = src(field)
            if val:
                try:
                    data[field] = Decimal(val)
                except (InvalidOperation, ValueError):
                    errors.append(f"{field} is not a number: '{val}'.")

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

        results.append(
            {"index": index, "data": data, "errors": errors, "warnings": warnings}
        )

    return results


def _resolve_location(row, mapping, errors):
    """Return a Point (4326) from a geometry column or a lat/lon pair, or None.

    Appends an error and returns None when no usable location is present.
    """
    geom_col = mapping.get("geometry")
    if geom_col:
        raw = (row.get(geom_col) or "").strip()
        if raw:
            point = _point_from_geometry(raw)
            if point is not None:
                return point
            # A geometry value was present but unparseable / non-finite /
            # out-of-range — report it as a row error rather than silently
            # falling back to lat/lon (or 500-ing downstream on a centroid).
            errors.append(
                "geometry is invalid (non-finite or out-of-range coordinates, "
                "or unparseable)."
            )
            return None

    lat_col = mapping.get("latitude")
    lon_col = mapping.get("longitude")
    lat_raw = (row.get(lat_col) or "").strip() if lat_col else ""
    lon_raw = (row.get(lon_col) or "").strip() if lon_col else ""
    if lat_raw and lon_raw:
        try:
            lat = float(lat_raw)
            lon = float(lon_raw)
        except ValueError:
            errors.append(f"location lat/lon are not numbers: '{lat_raw}', '{lon_raw}'.")
            return None
        if not (_CA_LAT[0] <= lat <= _CA_LAT[1] and _CA_LON[0] <= lon <= _CA_LON[1]):
            errors.append(
                f"location ({lat}, {lon}) is outside the expected California range."
            )
            return None
        return Point(lon, lat, srid=4326)

    errors.append("location is required (a geometry column, or both lat and lon).")
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


def commit_rows(valid_results, infra_type):
    """Create records from the coerced `data` of error-free rows. Returns count.

    Wrapped in a single transaction. Errored rows are skipped. Per-row create()
    is fine here — wells/diversions/recharge sites have no save-time signals.
    """
    from recharge.models import RechargeSite
    from surface.models import PointOfDiversion

    clean = [r for r in valid_results if not r["errors"] and r["data"].get("location")]
    created = 0

    with transaction.atomic():
        for result in clean:
            data = result["data"]
            try:
                # Per-row savepoint: a single bad row (e.g. a geometry that
                # slipped validation) is rolled back and reported, not allowed
                # to poison the whole batch or surface as a 500.
                with transaction.atomic():
                    if infra_type == "well":
                        Well.objects.create(**data)
                    elif infra_type == "diversion":
                        PointOfDiversion.objects.create(water_right=None, **data)
                    elif infra_type in ("recharge_site", "storage"):
                        RechargeSite.objects.create(**data)
                    else:
                        continue
                created += 1
            except Exception:
                result["errors"].append(
                    "could not be saved (invalid geometry or data)."
                )

    return created


# ---------------------------------------------------------------------------
# GDAL / spatial parser helpers (single home; views.py imports these)
# ---------------------------------------------------------------------------


def _parse_geojson_file(uploaded):
    content = json.loads(uploaded.read().decode("utf-8"))
    if content.get("type") == "FeatureCollection":
        raw_features = content.get("features", [])
    elif content.get("type") == "Feature":
        raw_features = [content]
    else:
        raw_features = [{"type": "Feature", "geometry": content, "properties": {}}]

    features = []
    for feat in raw_features:
        features.append(
            {
                "geometry": feat.get("geometry"),
                "properties": feat.get("properties", {}),
            }
        )
    return features


def _validate_zip_entries(zf, dest_dir):
    """Reject path-traversal entries and enforce a total uncompressed-size cap
    before extracting (zip-slip + zip-bomb defense).

    Modern CPython's extractall already sanitizes `..`/absolute names (so this
    was downgraded P1->P2), but we validate explicitly for defense-in-depth and
    refactor-safety, and so a zip bomb is refused before any bytes hit disk.
    """
    dest_root = os.path.realpath(dest_dir)
    total = 0
    for info in zf.infolist():
        name = info.filename
        parts = name.replace("\\", "/").split("/")
        if os.path.isabs(name) or ".." in parts:
            raise ImportError(f"Unsafe path in archive: '{name}'.")
        resolved = os.path.realpath(os.path.join(dest_dir, name))
        if resolved != dest_root and not resolved.startswith(dest_root + os.sep):
            raise ImportError(f"Archive entry escapes the extract directory: '{name}'.")
        total += info.file_size
        if total > MAX_EXTRACTED_BYTES:
            raise ImportError(
                f"Archive expands to more than {MAX_EXTRACTED_BYTES // (1024 * 1024)} "
                "MB; refusing to extract (possible zip bomb)."
            )


def _parse_shapefile_zip(uploaded):
    tmp_dir = tempfile.mkdtemp()
    try:
        zip_path = os.path.join(tmp_dir, "upload.zip")
        written = 0
        with open(zip_path, "wb") as f:
            for chunk in uploaded.chunks():
                written += len(chunk)
                if written > MAX_UPLOAD_BYTES:
                    raise ImportError(
                        f"Archive exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB "
                        "upload cap."
                    )
                f.write(chunk)

        with zipfile.ZipFile(zip_path, "r") as zf:
            _validate_zip_entries(zf, tmp_dir)
            zf.extractall(tmp_dir)

        # Deterministic pick: the first .shp by sorted full path (os.walk order
        # is filesystem-dependent and was effectively arbitrary before).
        shp_files = sorted(
            os.path.join(root, fn)
            for root, _dirs, files in os.walk(tmp_dir)
            for fn in files
            if fn.lower().endswith(".shp")
        )
        if not shp_files:
            raise ImportError("No .shp file found in archive.")

        return _extract_features_from_datasource(shp_files[0])
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _parse_kml_file(uploaded):
    tmp_dir = tempfile.mkdtemp()
    try:
        kml_path = os.path.join(tmp_dir, "upload.kml")
        with open(kml_path, "wb") as f:
            for chunk in uploaded.chunks():
                f.write(chunk)
        return _extract_features_from_datasource(kml_path)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _extract_features_from_datasource(path):
    ds = DataSource(path)
    features = []
    for layer in ds:
        for feat in layer:
            geom = feat.geom
            if geom.srid and geom.srid != 4326:
                geom.transform(4326)
            properties = {}
            for field_name in feat.fields:
                val = feat.get(field_name)
                if val is not None:
                    properties[field_name] = str(val)
            features.append(
                {
                    "geometry": json.loads(geom.geojson),
                    "properties": properties,
                }
            )
    return features
