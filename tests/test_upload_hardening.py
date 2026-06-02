# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Upload-path hardening regression (ISS-037).

Three gaps closed on the bulk-import path, all demo-facing on a 2-4GB VPS:

  (a) size  — a multi-GB or zip-bomb upload used to stream to disk and
              extractall with no ceiling (MAX_ROWS is checked only after parse).
  (b) geometry — uploaded GeoJSON/WKT went straight into GEOSGeometry; json.loads
              accepts NaN/Infinity and GEOS accepts self-intersecting geometry,
              so a crafted feature 500s or persists a degenerate row.
  (c) zip-entry — extractall with no explicit `..`/absolute-path guard.
"""

import io
import math
import zipfile

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from infrastructure import importer
from wells.models import Well


# ---------------------------------------------------------------------------
# (a) size caps
# ---------------------------------------------------------------------------


class _BigFile:
    """Stand-in upload whose declared size is over the cap; must be rejected
    before anything reads or parses it."""

    size = importer.MAX_UPLOAD_BYTES + 1
    name = "huge.csv"

    def read(self, *args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("an over-cap upload must not be read/parsed")

    def chunks(self, *args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("an over-cap upload must not be streamed")


def test_oversize_upload_rejected_before_parse():
    with pytest.raises(ImportError) as exc:
        importer.parse_upload(_BigFile(), "huge.csv")
    assert "cap" in str(exc.value).lower()


def test_zip_bomb_rejected_before_extract(monkeypatch):
    # Shrink the ceiling so a tiny zip trips it (no need to build 50 MB on disk).
    monkeypatch.setattr(importer, "MAX_EXTRACTED_BYTES", 10)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("layer.shp", b"x" * 100)  # 100 uncompressed bytes > 10
    upload = SimpleUploadedFile("bomb.zip", buf.getvalue())
    with pytest.raises(ImportError) as exc:
        importer._parse_shapefile_zip(upload)
    assert "zip bomb" in str(exc.value).lower()


# ---------------------------------------------------------------------------
# (c) zip-entry path traversal
# ---------------------------------------------------------------------------


def test_zip_slip_entry_rejected():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../evil.shp", b"pwned")
    upload = SimpleUploadedFile("slip.zip", buf.getvalue())
    with pytest.raises(ImportError) as exc:
        importer._parse_shapefile_zip(upload)
    assert "unsafe path" in str(exc.value).lower()


# ---------------------------------------------------------------------------
# (b) geometry validation
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestGeometryValidation:
    def _mapping(self):
        return {"name": "name", "geometry": "geom"}

    def test_nan_coords_are_a_row_error_not_a_500(self):
        rows = [{"name": "NaN Well", "geom": '{"type":"Point","coordinates":[NaN,36.5]}'}]
        results = importer.validate_rows(rows, self._mapping(), "well", set())
        assert any("geometry" in e.lower() for e in results[0]["errors"])
        assert "location" not in results[0]["data"]

    def test_infinity_coords_are_a_row_error(self):
        rows = [
            {"name": "Inf Well", "geom": '{"type":"Point","coordinates":[Infinity,36.5]}'}
        ]
        results = importer.validate_rows(rows, self._mapping(), "well", set())
        assert results[0]["errors"]
        assert "location" not in results[0]["data"]

    def test_out_of_range_coords_rejected(self):
        rows = [
            {"name": "Off World", "geom": '{"type":"Point","coordinates":[999,999]}'}
        ]
        results = importer.validate_rows(rows, self._mapping(), "well", set())
        assert results[0]["errors"]

    def test_self_intersecting_polygon_made_valid_not_degenerate(self):
        # A bow-tie polygon is invalid; make_valid should repair it and yield a
        # finite centroid — never NaN, never a raise.
        bowtie = '{"type":"Polygon","coordinates":[[[0,0],[1,1],[1,0],[0,1],[0,0]]]}'
        point = importer._point_from_geometry(bowtie)
        assert point is not None
        assert math.isfinite(point.x) and math.isfinite(point.y)

    def test_commit_skips_degenerate_geometry_row(self):
        rows = [
            {"name": "Good", "geom": '{"type":"Point","coordinates":[-119.5,36.5]}'},
            {"name": "Bad", "geom": '{"type":"Point","coordinates":[NaN,36.5]}'},
        ]
        results = importer.validate_rows(rows, self._mapping(), "well", set())
        before = Well.objects.count()
        created = importer.commit_rows(results, "well")
        assert created == 1
        assert Well.objects.count() == before + 1
