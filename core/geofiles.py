# SPDX-License-Identifier: AGPL-3.0-or-later
"""Reading an uploaded map file into features (150-03, ISS-200).

The GeoJSON, zipped-shapefile and KML readers, with their size and archive
guards, moved here from ``infrastructure/importer.py``, where they were the
bulk importer's private helpers. The Setup Wizard needs the same readers for a
boundary file, and ``setup`` is a module every deployment gets while
``infrastructure`` is optional; a module everybody gets may not depend on one
they might not have (the module composition rule in CLAUDE.md). ``core`` is
the shared home both can read. ``infrastructure/importer.py`` re-exports every
name here, so the importer and its tests behave exactly as before.

A feature is ``{"geometry": <GeoJSON geometry dict>, "properties": {...}}``.

The two caps are read from this module each time a file is handled, never
copied at import, so a test can shrink them with ``monkeypatch``.
"""

import json
import math
import os
import shutil
import tempfile
import zipfile

from django.contrib.gis.gdal import DataSource, GDALException

# Hard byte ceilings so an oversized or zip-bomb upload can't exhaust the small
# VPS (2-4GB) before any row cap is even reached; a row cap is checked only
# AFTER a full parse, so it is no defense against a 5GB file. MAX_UPLOAD_BYTES
# bounds the raw uploaded file; MAX_EXTRACTED_BYTES bounds the total
# uncompressed bytes a zip is allowed to expand to (a small zip can decompress
# to gigabytes).
MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MB raw upload
MAX_EXTRACTED_BYTES = 50 * 1024 * 1024  # 50 MB total extracted from a zip

GEOJSON_EXTENSIONS = (".geojson", ".json")
SHAPEFILE_EXTENSIONS = (".zip",)
KML_EXTENSIONS = (".kml",)

#: The three formats, as one phrase every refusal that names them shares.
THREE_FORMATS = (
    "a zipped shapefile (.zip), a KML (.kml) or a GeoJSON (.geojson or .json) file"
)

#: The Setup Wizard's wrong-type sentence (150.1-02).
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
        return _parse_geojson_file(uploaded_file)
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
            raise ImportError(NO_SHP_MESSAGE)

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
