# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pins what the import_parcels command writes and prints on a small GeoJSON file.

Written before the command's handle() was split into steps, so the split can be
shown to change neither the Parcel rows nor the console output.
"""

import json
import zipfile
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
        with pytest.raises(CommandError, match="OpenH2O cannot read this file as GeoJSON"):
            _run(str(bad))


# ---------------------------------------------------------------------------
# 151.6-06: the command reads through core/geofiles.py
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestFormatsAndJoining:
    def test_a_zipped_shapefile_and_a_kml_import_as_the_page_reads_them(self, tmp_path):
        from pathlib import Path

        fixtures = Path(__file__).parent / "fixtures" / "real_map_files"
        out = _run(str(fixtures / "sj_valley_subbasins_2227.zip"), "--parcel-number-field", "Basin_Subb")
        assert out.splitlines() == ["Imported 5 parcels, 0 duplicates skipped, 0 errors"]
        Parcel.objects.all().delete()
        out = _run(str(fixtures / "sj_valley_subbasins_names.kml"), "--parcel-number-field", "Name")
        assert out.splitlines() == ["Imported 5 parcels, 0 duplicates skipped, 0 errors"]

    def test_a_bare_shapefile_path_is_still_read(self, tmp_path):
        from pathlib import Path

        fixtures = Path(__file__).parent / "fixtures" / "real_map_files"
        with zipfile.ZipFile(fixtures / "sj_valley_subbasins_2227.zip") as zf:
            zf.extractall(tmp_path)
        shp = next(tmp_path.glob("*.shp"))
        out = _run(str(shp), "--parcel-number-field", "Basin_Subb", "--dry-run")
        assert out.splitlines()[-1] == "Imported 5 parcels, 0 duplicates skipped, 0 errors"

    def test_two_features_on_one_number_are_one_parcel_holding_both(self, tmp_path):
        path = tmp_path / "joined.geojson"
        path.write_text(json.dumps({
            "type": "FeatureCollection",
            "features": [
                _feature("CHAR-JOIN", "First Owner", -119.50),
                _feature("CHAR-JOIN", "Second Owner", -119.40),
                _feature("CHAR-ONE", "Solo", -119.30),
            ],
        }))

        dry = _run(str(path), "--dry-run")
        assert dry.splitlines() == [
            "[DRY RUN] No records will be promoted.",
            "Imported 2 parcels, 0 duplicates skipped, 0 errors",
        ]
        assert not Parcel.objects.filter(parcel_number__startswith="CHAR-").exists()

        real = _run(str(path))
        assert real.splitlines() == ["Imported 2 parcels, 0 duplicates skipped, 0 errors"]
        joined = Parcel.objects.get(parcel_number="CHAR-JOIN")
        assert joined.geometry.geom_type == "MultiPolygon"
        assert joined.geometry.num_geom == 2
        assert joined.owner_name == "First Owner"
        assert ParcelStaging.objects.count() == 0

    def test_a_joined_number_already_on_file_is_one_duplicate(self, tmp_path):
        ParcelFactory(parcel_number="CHAR-JOIN")
        path = tmp_path / "joined.geojson"
        path.write_text(json.dumps({
            "type": "FeatureCollection",
            "features": [_feature("CHAR-JOIN", "A", -119.50), _feature("CHAR-JOIN", "B", -119.40)],
        }))
        assert _run(str(path)).splitlines() == [
            "Imported 0 parcels, 1 duplicates skipped, 0 errors"
        ]

    def test_coordinates_that_are_not_longitude_and_latitude_are_refused(self, tmp_path):
        feature = _feature("CHAR-FEET", "Feet", 0)
        feature["geometry"]["coordinates"] = [[
            [6_400_000, 2_000_000], [6_400_100, 2_000_000], [6_400_100, 2_000_100],
            [6_400_000, 2_000_100], [6_400_000, 2_000_000],
        ]]
        path = tmp_path / "feet.geojson"
        path.write_text(json.dumps({"type": "FeatureCollection", "features": [feature]}))
        with pytest.raises(CommandError, match="not longitude and latitude"):
            _run(str(path))
        assert not Parcel.objects.filter(parcel_number="CHAR-FEET").exists()
