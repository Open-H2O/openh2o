# SPDX-License-Identifier: AGPL-3.0-or-later
"""Reading an uploaded map file into features.

The GeoJSON, zipped-shapefile and KML readers, with their size and archive
guards, moved here from ``infrastructure/importer.py``, where they were the
bulk importer's private helpers. The Setup Wizard needs the same readers for a
boundary file, and ``setup`` is a module every deployment gets while
``infrastructure`` is optional; a module everybody gets may not depend on one
they might not have (the module composition rule in CLAUDE.md). ``core`` is
the shared home both can read. ``infrastructure/importer.py`` re-exports every
name here, so the importer and its tests behave exactly as before.

A feature is ``{"geometry": <GeoJSON geometry dict>, "properties": {...}}``.

Use areas read through here too (``parcels/use_area_import.py`` and the
``import_parcels`` command), so every page and the command give one answer for
one file. A zip that holds more than one shapefile is refused on all of them.

The two caps are read from this module each time a file is handled, never
copied at import, so a test can shrink them with ``monkeypatch``.
"""

import json
import math
import os
import shutil
import tempfile
import zipfile

from django.contrib.gis.gdal import (
    CoordTransform,
    DataSource,
    GDALException,
    SpatialReference,
)
from django.core.files import File

# Hard byte ceilings so an oversized or zip-bomb upload can't exhaust a small
# server's memory. They are checked before any parse; the import pages have no
# row cap, so these are the only bound on a file's size. MAX_UPLOAD_BYTES
# bounds the raw uploaded file; MAX_EXTRACTED_BYTES bounds the total
# uncompressed bytes a zip is allowed to expand to (a small zip can decompress
# to gigabytes).
MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MB raw upload
MAX_EXTRACTED_BYTES = 50 * 1024 * 1024  # 50 MB total extracted from a zip

GEOJSON_EXTENSIONS = (".geojson", ".json")
SHAPEFILE_EXTENSIONS = (".zip",)
KML_EXTENSIONS = (".kml",)

#: The Setup Wizard's wrong-type sentence.
UNSUPPORTED_SENTENCE = "This page imports .zip, .kml, .geojson and .json files only."

#: The map-file sentences both pages show: the bulk import's
#: and the Setup Wizard's, which reuses them.
#: They live here because ``setup`` may not depend on the optional
#: ``infrastructure`` module.
_CHECK_IN_GIS = "Check that the file opens in a GIS program, then upload it again."
NOT_GEOJSON_MESSAGE = f"OpenH2O cannot read this file as GeoJSON. {_CHECK_IN_GIS}"
NOT_KML_MESSAGE = f"OpenH2O cannot read this file as KML. {_CHECK_IN_GIS}"
NOT_ZIP_MESSAGE = "OpenH2O cannot open this file as a zip archive."
NOT_SHAPEFILE_MESSAGE = (
    f"OpenH2O cannot read the shapefile in this zip file. {_CHECK_IN_GIS}"
)
NO_FEATURES_MESSAGE = "This file has no map features."
NO_SHP_MESSAGE = "This zip file does not contain a shapefile (.shp)."

#: Shown by every page and command that needs longitude and latitude and was
#: given coordinates that are not. It lives here because the Setup Wizard
#: (``setup``), the Import use areas page (``parcels``) and ``import_parcels``
#: all show it, and ``setup`` may not import ``parcels`` or ``infrastructure``.
NOT_LONGITUDE_LATITUDE_MESSAGE = (
    "The coordinates in this file are not longitude and latitude, and the file "
    "does not say which projection they are in. For a shapefile, include its "
    ".prj file in the zip."
)

#: How many shapefile names the several-shapefiles sentence lists.
SHAPEFILES_LISTED = 10


def several_shapefiles_message(names):
    """The sentence for a zip that holds more than one shapefile.

    ``names`` are the shapefiles' file names without folders, in the order the
    reader sorts them. Up to ``SHAPEFILES_LISTED`` are listed, then the rest
    are counted.
    """
    listed = list(names[:SHAPEFILES_LISTED])
    if len(names) > SHAPEFILES_LISTED:
        listed.append(f"and {len(names) - SHAPEFILES_LISTED} more")
    return (
        f"This zip holds {len(names)} shapefiles: {', '.join(listed)}. "
        "Upload a zip with only the one you want."
    )


def too_large_message(size):
    """The size is rounded UP, so a file over the cap never reads as equal to it."""
    mb = 1024 * 1024
    return (
        f"This file is {math.ceil(size / mb)} MB. "
        f"OpenH2O imports files of up to {MAX_UPLOAD_BYTES // mb} MB."
    )


def unsafe_path_message(name):
    return (
        f"This zip file contains the path '{name}', which points outside the zip "
        f"file. Remove '{name}' from the zip file, then upload the zip file again."
    )


def extension(filename) -> str:
    """The file's extension, lowercased, with its dot ("" when it has none)."""
    return os.path.splitext(filename or "")[1].lower()


def check_upload_size(uploaded):
    """Refuse a file over ``MAX_UPLOAD_BYTES`` before anything reads it.

    Django's DATA_UPLOAD_MAX_MEMORY_SIZE does not cover file uploads, so this
    is the ceiling. Raises ``ValueError`` with the cap in plain words.
    """
    size = getattr(uploaded, "size", None)
    if size is not None and size > MAX_UPLOAD_BYTES:
        raise ValueError(too_large_message(size))


def features_from_upload(uploaded_file):
    """Every feature in an uploaded map file, read by its extension.

    ``.geojson`` / ``.json`` go to the GeoJSON reader, ``.zip`` to the
    shapefile reader, ``.kml`` to the KML reader; any other extension raises
    ``ValueError`` naming the three formats. The upload cap applies to every
    format before the file is read. The archive guards raise ``ImportError``
    with their own sentence, as they always have for the bulk importer.
    """
    ext = extension(getattr(uploaded_file, "name", ""))
    if ext not in GEOJSON_EXTENSIONS + SHAPEFILE_EXTENSIONS + KML_EXTENSIONS:
        raise ValueError(UNSUPPORTED_SENTENCE)

    check_upload_size(uploaded_file)

    if ext in GEOJSON_EXTENSIONS:
        try:
            return _parse_geojson_file(uploaded_file)
        except (ValueError, AttributeError, TypeError):
            # ValueError covers json.JSONDecodeError and UnicodeDecodeError;
            # AttributeError and TypeError a JSON value that is not GeoJSON.
            raise ValueError(NOT_GEOJSON_MESSAGE)
    try:
        if ext in SHAPEFILE_EXTENSIONS:
            return _parse_shapefile_zip(uploaded_file)
        return _parse_kml_file(uploaded_file)
    except zipfile.BadZipFile:
        raise ValueError(NOT_ZIP_MESSAGE)
    except GDALException:
        raise ValueError(
            NOT_SHAPEFILE_MESSAGE if ext in SHAPEFILE_EXTENSIONS else NOT_KML_MESSAGE
        )


def features_from_path(path):
    """Every feature in the map file at ``path``, read the way an upload is.

    A ``.zip`` goes through ``features_from_upload``, so the size caps and the
    several-shapefiles refusal apply. Any other file (a ``.geojson``, ``.json``,
    ``.kml`` or a bare ``.shp``) is opened with GDAL where it lies and read
    with the same feature extraction and no size cap: it is already on the
    server, and the command has always read a GeoJSON or a shapefile of any
    size.
    """
    name = os.path.basename(path)
    ext = extension(name)
    if ext in SHAPEFILE_EXTENSIONS:
        with open(path, "rb") as handle:
            return features_from_upload(File(handle, name=name))
    try:
        return _extract_features_from_datasource(path)
    except GDALException:
        if ext in GEOJSON_EXTENSIONS:
            raise ValueError(NOT_GEOJSON_MESSAGE)
        if ext in KML_EXTENSIONS:
            raise ValueError(NOT_KML_MESSAGE)
        raise


def _positions(geometry):
    """Every (x, y) position in a GeoJSON geometry dict."""
    if isinstance(geometry, dict):
        if geometry.get("type") == "GeometryCollection":
            for part in geometry.get("geometries") or []:
                yield from _positions(part)
        else:
            yield from _positions(geometry.get("coordinates"))
    elif isinstance(geometry, (list, tuple)):
        if geometry and not isinstance(geometry[0], (list, tuple)):
            if len(geometry) >= 2:
                yield geometry[0], geometry[1]
        else:
            for part in geometry:
                yield from _positions(part)


def check_longitude_latitude(features):
    """Refuse features whose coordinates are not longitude and latitude.

    The readers reproject a layer whose projection the file states. A file
    that does not (a shapefile without its ``.prj``, a GeoJSON written in feet)
    comes through unchanged, and its positions fall outside -180 to 180 and
    -90 to 90. Raises ``ValueError`` with ``NOT_LONGITUDE_LATITUDE_MESSAGE``.
    """
    for feature in features:
        for x, y in _positions(feature.get("geometry")):
            try:
                inside = -180 <= x <= 180 and -90 <= y <= 90
            except TypeError:
                inside = False
            if not inside:
                raise ValueError(NOT_LONGITUDE_LATITUDE_MESSAGE)


def two_dimensional(coordinates):
    """``coordinates`` with every position cut to longitude and latitude.

    GDAL reads a KML position as (lon, lat, altitude), and the geometry
    columns are 2D, so the altitude is dropped before GEOS ever sees it.
    """
    if not isinstance(coordinates, (list, tuple)):
        # A GeoJSON file can hold anything here ("a", null); GEOS refuses it
        # later instead of this recursing forever.
        return coordinates
    if coordinates and not isinstance(coordinates[0], (list, tuple)):
        return list(coordinates[:2])
    return [two_dimensional(part) for part in coordinates]


# ---------------------------------------------------------------------------
# The readers (moved from infrastructure/importer.py, unchanged in behaviour)
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
            raise ImportError(unsafe_path_message(name))
        resolved = os.path.realpath(os.path.join(dest_dir, name))
        if resolved != dest_root and not resolved.startswith(dest_root + os.sep):
            raise ImportError(unsafe_path_message(name))
        total += info.file_size
        if total > MAX_EXTRACTED_BYTES:
            mb = MAX_EXTRACTED_BYTES // (1024 * 1024)
            raise ImportError(
                f"This zip file expands to more than {mb} MB, and OpenH2O opens zip "
                f"files of up to {mb} MB unzipped."
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
                    limit_mb = MAX_UPLOAD_BYTES // (1024 * 1024)
                    raise ImportError(
                        f"This zip file is more than {limit_mb} MB. "
                        f"OpenH2O imports files of up to {limit_mb} MB."
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
            # A zip made on a Mac carries a "__MACOSX/._name.shp" copy of each
            # file's metadata beside the real one; it is not a shapefile.
            and not fn.startswith("._")
            and "__MACOSX" not in os.path.relpath(root, tmp_dir).split(os.sep)
        )
        if not shp_files:
            raise ImportError(NO_SHP_MESSAGE)
        if len(shp_files) > 1:
            # Reading the first of several used to hide the rest (a real USGS
            # zip of 13 shapefiles gave its first, empty one), so the person
            # is asked to send the one they want.
            raise ImportError(
                several_shapefiles_message([os.path.basename(p) for p in shp_files])
            )

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


def _is_wgs84_longitude_latitude(srs):
    return srs.srid == 4326


def _extract_features_from_datasource(path):
    ds = DataSource(path)
    features = []
    for layer in ds:
        # A layer that states a projection is reprojected whether or not GDAL
        # can match it to an EPSG code (an Esri .prj often cannot); a layer
        # that states none is left as it is.
        srs = layer.srs
        reproject = srs is not None and not _is_wgs84_longitude_latitude(srs)
        # One transformation per layer: building it for every feature took
        # 6 of 7 seconds on a county file of 12,128 parcels.
        to_wgs84 = CoordTransform(srs, SpatialReference(4326)) if reproject else None
        for feat in layer:
            try:
                geom = feat.geom
            except GDALException:
                geom = None
            if geom is not None and reproject:
                geom.transform(to_wgs84)
            properties = {}
            for field_name in feat.fields:
                val = feat.get(field_name)
                if val is not None:
                    properties[field_name] = str(val)
            features.append(
                {
                    "geometry": json.loads(geom.geojson) if geom is not None else None,
                    "properties": properties,
                }
            )
    return features
