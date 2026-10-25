# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pins what the import_parcels command writes and prints on a small GeoJSON file.

Written before the command's handle() was split into steps, so the split can be
shown to change neither the Parcel rows nor the console output.
"""

import json
from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from parcels.models import Parcel, ParcelStaging
from tests.factories import ParcelFactory


def _ring(x: float) -> list:
    return [[[x, 36.5], [x + 0.01, 36.5], [x + 0.01, 36.51], [x, 36.51], [x, 36.5]]]


def _feature(apn, owner, x: float) -> dict:
    return {
        "type": "Feature",
        "properties": {"APN": apn, "OWNER": owner},
        "geometry": {"type": "Polygon", "coordinates": _ring(x)},
    }


@pytest.fixture
def geojson_file(tmp_path):
    collection = {
        "type": "FeatureCollection",
        "features": [
            _feature("CHAR-A", "  Alpha Farms  ", -119.50),
            _feature("CHAR-B", None, -119.40),
            _feature("CHAR-DUP", "Dup Owner", -119.30),
            _feature("", "No Number", -119.20),
        ],
    }
    path = tmp_path / "chars.geojson"
    path.write_text(json.dumps(collection))
    return path


def _run(*args: str) -> str:
    out = StringIO()
    call_command("import_parcels", *args, stdout=out)
    return out.getvalue()


@pytest.mark.django_db
class TestImportParcelsCharacterisation:
    def test_real_run_rows_and_output(self, geojson_file):
        ParcelFactory(parcel_number="CHAR-DUP", owner_name="Existing")

        output = _run(str(geojson_file))

        assert output.splitlines() == [
            "  Skipping feature: missing or empty 'APN' field.",
            "Imported 2 parcels, 1 duplicates skipped, 1 errors",
        ]
        rows = {
            p.parcel_number: (p.owner_name, p.status, p.geometry.geom_type, p.geometry.srid)
            for p in Parcel.objects.filter(parcel_number__startswith="CHAR-")
        }
        assert rows == {
            "CHAR-A": ("Alpha Farms", "active", "MultiPolygon", 4326),
            "CHAR-B": ("", "active", "MultiPolygon", 4326),
            "CHAR-DUP": ("Existing", "active", "MultiPolygon", 4326),
        }
        assert ParcelStaging.objects.count() == 0

    def test_dry_run_writes_no_parcels(self, geojson_file):
        ParcelFactory(parcel_number="CHAR-DUP")

        output = _run(str(geojson_file), "--dry-run")

        assert output.splitlines() == [
            "[DRY RUN] No records will be promoted.",
            "  Skipping feature: missing or empty 'APN' field.",
            "Imported 2 parcels, 1 duplicates skipped, 1 errors",
        ]
        assert not Parcel.objects.filter(parcel_number__in=["CHAR-A", "CHAR-B"]).exists()
        assert ParcelStaging.objects.count() == 0

    def test_custom_field_names(self, tmp_path):
        feature = _feature("X", "ignored", -119.1)
        feature["properties"] = {"PARCEL": "CHAR-CUSTOM", "HOLDER": "Holder Co"}
        path = tmp_path / "custom.json"
        path.write_text(json.dumps({"type": "FeatureCollection", "features": [feature]}))

        output = _run(str(path), "--parcel-number-field", "PARCEL", "--owner-field", "HOLDER")

        assert output.splitlines() == ["Imported 1 parcels, 0 duplicates skipped, 0 errors"]
        assert Parcel.objects.get(parcel_number="CHAR-CUSTOM").owner_name == "Holder Co"

    def test_missing_file_and_unknown_extension(self, tmp_path):
        with pytest.raises(CommandError, match="File not found: /nonexistent/x.geojson"):
            _run("/nonexistent/x.geojson")
        odd = tmp_path / "parcels.csv"
        odd.write_text("a,b")
        with pytest.raises(CommandError, match="Cannot detect format from extension '.csv'. Use --format."):
            _run(str(odd))

    def test_unreadable_file_reports_gdal_failure(self, tmp_path):
        bad = tmp_path / "bad.geojson"
        bad.write_text("not json at all")
        with pytest.raises(CommandError, match="Failed to open file with GDAL"):
            _run(str(bad))
