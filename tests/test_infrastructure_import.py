# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Tests for the bulk infrastructure importer (infrastructure.importer).

The importer is four pure-ish functions that the import UI is thin glue over:

  parse_upload(file, filename)         -> {"columns": [...], "rows": [...]}
  auto_map_columns(columns, infra_type)-> {model_field: source_column}
  validate_rows(rows, mapping, type, existing_reg_ids)
                                       -> [{index, data, errors, warnings}]
  commit_rows(valid_results, infra_type) -> int (number created)

These tests lock the contract the views.py glue depends on: a GSA can upload a
file of many wells and get many wells, with the mid-tier construction fields
mapped from their column headers, bad rows reported and skipped, good rows made.
"""

import io
from decimal import Decimal

import factory
import pytest
from django.contrib.auth.hashers import make_password
from django.test import Client
from django.urls import reverse

from infrastructure import importer
from wells.models import Well


class _UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"importer{n}")
    email = factory.Sequence(lambda n: f"importer{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True


@pytest.fixture
def auth_client(db):
    c = Client()
    c.force_login(_UserFactory())
    return c


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _csv_file(text):
    """A file-like object standing in for an uploaded CSV."""
    return io.BytesIO(text.encode("utf-8"))


WELLS_HEADER = "name,WCR_NO,LAT,LON,CASING_DIA,SCREEN_TOP,YIELD_GPM,PUMP_TYPE"


# ---------------------------------------------------------------------------
# parse_upload
# ---------------------------------------------------------------------------


class TestParseUpload:
    def test_csv_returns_columns_and_rows(self):
        text = (
            "name,reg_id,capacity,depth\n"
            "Johnson Well,WELL-1,500,350\n"
            "Smith Well,WELL-2,250,200\n"
        )
        result = importer.parse_upload(_csv_file(text), "wells.csv")
        assert result["columns"] == ["name", "reg_id", "capacity", "depth"]
        assert len(result["rows"]) == 2
        assert result["rows"][0]["name"] == "Johnson Well"
        assert result["rows"][1]["reg_id"] == "WELL-2"

    def test_empty_csv_raises(self):
        with pytest.raises(ImportError):
            importer.parse_upload(_csv_file("name,reg_id\n"), "wells.csv")

    def test_over_cap_raises_naming_the_limit(self):
        rows = "\n".join(f"Well {i},WELL-{i}" for i in range(501))
        text = "name,reg_id\n" + rows + "\n"
        with pytest.raises(ImportError) as exc:
            importer.parse_upload(_csv_file(text), "wells.csv")
        assert "500" in str(exc.value)

    def test_geojson_rows_carry_geometry(self):
        geojson = (
            '{"type":"FeatureCollection","features":['
            '{"type":"Feature","properties":{"name":"GW1"},'
            '"geometry":{"type":"Point","coordinates":[-119.5,36.5]}}]}'
        )
        result = importer.parse_upload(_csv_file(geojson), "wells.geojson")
        assert len(result["rows"]) == 1
        row = result["rows"][0]
        assert row["name"] == "GW1"
        assert "__geometry__" in row
        assert "Point" in row["__geometry__"]
        assert "__geometry__" in result["columns"]

    def test_unsupported_format_raises(self):
        with pytest.raises(ImportError):
            importer.parse_upload(_csv_file("x"), "wells.txt")


# ---------------------------------------------------------------------------
# auto_map_columns
# ---------------------------------------------------------------------------


class TestAutoMapColumns:
    def test_common_well_headers_map_correctly(self):
        cols = ["WCR_NO", "Well Name", "Lat", "Lon"]
        mapping = importer.auto_map_columns(cols, "well")
        assert mapping["wcr_number"] == "WCR_NO"
        assert mapping["name"] == "Well Name"
        assert mapping["latitude"] == "Lat"
        assert mapping["longitude"] == "Lon"

    def test_construction_headers_map_correctly(self):
        cols = ["CASING_DIA", "SCREEN_TOP", "YIELD_GPM", "PUMP_TYPE"]
        mapping = importer.auto_map_columns(cols, "well")
        assert mapping["casing_diameter_in"] == "CASING_DIA"
        assert mapping["screen_top_ft"] == "SCREEN_TOP"
        assert mapping["tested_yield_gpm"] == "YIELD_GPM"
        assert mapping["pump_type"] == "PUMP_TYPE"

    def test_unknown_column_is_absent_from_map(self):
        mapping = importer.auto_map_columns(["totally_unknown_col"], "well")
        assert mapping == {}

    def test_is_deterministic(self):
        cols = ["WCR_NO", "Well Name", "Lat", "Lon"]
        a = importer.auto_map_columns(cols, "well")
        b = importer.auto_map_columns(cols, "well")
        assert a == b

    def test_diversion_and_recharge_alias_sets(self):
        div = importer.auto_map_columns(
            ["name", "stream", "max_rate_cfs", "lat", "lon"], "diversion"
        )
        assert div["name"] == "name"
        assert div["stream_name"] == "stream"
        assert div["max_rate_cfs"] == "max_rate_cfs"

        rec = importer.auto_map_columns(
            ["site_name", "site_type", "capacity_af", "operator"], "recharge_site"
        )
        assert rec["name"] == "site_name"
        assert rec["site_type"] == "site_type"
        assert rec["capacity_acre_feet"] == "capacity_af"
        assert rec["operator"] == "operator"


# ---------------------------------------------------------------------------
# validate_rows
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestValidateRows:
    def _mapping(self, **over):
        m = {
            "name": "name",
            "well_registration_id": "reg_id",
            "latitude": "lat",
            "longitude": "lon",
            "casing_diameter_in": "casing",
            "pump_type": "pump",
        }
        m.update(over)
        return m

    def test_missing_name_is_error(self):
        rows = [{"name": "", "lat": "37.2", "lon": "-119.5", "reg_id": "", "casing": "", "pump": ""}]
        results = importer.validate_rows(rows, self._mapping(), "well", set())
        assert results[0]["errors"]
        assert any("name" in e.lower() for e in results[0]["errors"])

    def test_good_row_has_no_errors(self):
        rows = [{"name": "Good Well", "lat": "37.2", "lon": "-119.5", "reg_id": "", "casing": "", "pump": ""}]
        results = importer.validate_rows(rows, self._mapping(), "well", set())
        assert results[0]["errors"] == []

    def test_existing_registration_id_is_duplicate_error(self):
        rows = [{"name": "Dup Well", "lat": "37.2", "lon": "-119.5", "reg_id": "EXIST-1", "casing": "", "pump": ""}]
        results = importer.validate_rows(rows, self._mapping(), "well", {"EXIST-1"})
        assert any("duplicate" in e.lower() for e in results[0]["errors"])

    def test_within_batch_duplicate_registration_id_is_error(self):
        rows = [
            {"name": "A", "lat": "37.2", "lon": "-119.5", "reg_id": "BATCH-1", "casing": "", "pump": ""},
            {"name": "B", "lat": "37.3", "lon": "-119.6", "reg_id": "BATCH-1", "casing": "", "pump": ""},
        ]
        results = importer.validate_rows(rows, self._mapping(), "well", set())
        assert results[0]["errors"] == []
        assert any("duplicate" in e.lower() for e in results[1]["errors"])

    def test_non_numeric_value_names_the_field(self):
        rows = [{"name": "Bad Casing", "lat": "37.2", "lon": "-119.5", "reg_id": "", "casing": "abc", "pump": ""}]
        results = importer.validate_rows(rows, self._mapping(), "well", set())
        assert any("casing_diameter_in" in e for e in results[0]["errors"])

    def test_missing_location_is_error(self):
        rows = [{"name": "No Loc", "lat": "", "lon": "", "reg_id": "", "casing": "", "pump": ""}]
        results = importer.validate_rows(rows, self._mapping(), "well", set())
        assert any("location" in e.lower() for e in results[0]["errors"])

    def test_unknown_choice_is_warning_but_value_kept(self):
        rows = [{"name": "Odd Pump", "lat": "37.2", "lon": "-119.5", "reg_id": "", "casing": "", "pump": "rocket"}]
        results = importer.validate_rows(rows, self._mapping(), "well", set())
        assert results[0]["errors"] == []
        assert results[0]["warnings"]
        assert results[0]["data"]["pump_type"] == "rocket"

    def test_good_row_coerces_decimal_and_point(self):
        from django.contrib.gis.geos import Point

        rows = [{"name": "Coerce", "lat": "37.2", "lon": "-119.5", "reg_id": "", "casing": "8.5", "pump": "submersible"}]
        results = importer.validate_rows(rows, self._mapping(), "well", set())
        data = results[0]["data"]
        assert data["casing_diameter_in"] == Decimal("8.5")
        assert isinstance(data["location"], Point)
        assert data["name"] == "Coerce"


# ---------------------------------------------------------------------------
# commit_rows
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCommitRows:
    def _well_rows(self, n):
        return [
            {"name": f"Bulk Well {i}", "lat": "37.2", "lon": "-119.5", "reg_id": "", "casing": "", "pump": ""}
            for i in range(n)
        ]

    def _mapping(self):
        return {"name": "name", "latitude": "lat", "longitude": "lon"}

    def test_commit_creates_all_valid_rows(self):
        rows = self._well_rows(3)
        results = importer.validate_rows(rows, self._mapping(), "well", set())
        before = Well.objects.count()
        created = importer.commit_rows(results, "well")
        assert created == 3
        assert Well.objects.count() == before + 3

    def test_commit_skips_errored_rows(self):
        rows = self._well_rows(2)
        rows.append({"name": "", "lat": "37.2", "lon": "-119.5", "reg_id": "", "casing": "", "pump": ""})  # bad: no name
        results = importer.validate_rows(rows, self._mapping(), "well", set())
        before = Well.objects.count()
        created = importer.commit_rows(results, "well")
        assert created == 2
        assert Well.objects.count() == before + 2


# ---------------------------------------------------------------------------
# End-to-end through the views (the HTMX glue)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestImportFlowViews:
    def _wells_csv(self):
        return io.BytesIO(
            (
                "name,WCR_NO,LAT,LON,CASING_DIA,SCREEN_TOP,YIELD_GPM,PUMP_TYPE\n"
                "Alpha Well,WCR-1,37.20,-119.50,8,120,500,submersible\n"
                "Beta Well,WCR-2,37.30,-119.60,10,140,650,turbine\n"
            ).encode("utf-8")
        )

    def test_import_page_renders_with_type(self, auth_client):
        resp = auth_client.get(reverse("infrastructure:import") + "?type=well")
        assert resp.status_code == 200
        assert b"Bulk Import" in resp.content

    def test_preview_returns_mapping_with_guesses(self, auth_client):
        upload = self._wells_csv()
        upload.name = "wells.csv"
        resp = auth_client.post(
            reverse("infrastructure:import_preview"),
            {"infra_type": "well", "file": upload},
        )
        assert resp.status_code == 200
        body = resp.content.decode()
        # The mapping table offers the well fields and pre-selects the right column.
        assert "Casing Diameter (in)" in body
        assert "WCR_NO" in body
        assert 'name="rows_json"' in body

    def test_commit_creates_rows_and_reports_counts(self, auth_client):
        import json as _json

        rows = [
            {"name": "Alpha Well", "WCR_NO": "WCR-1", "LAT": "37.20", "LON": "-119.50",
             "CASING_DIA": "8", "SCREEN_TOP": "120", "YIELD_GPM": "500", "PUMP_TYPE": "submersible"},
            {"name": "", "WCR_NO": "WCR-2", "LAT": "37.30", "LON": "-119.60",
             "CASING_DIA": "10", "SCREEN_TOP": "140", "YIELD_GPM": "650", "PUMP_TYPE": "turbine"},
        ]
        before = Well.objects.count()
        resp = auth_client.post(
            reverse("infrastructure:import_commit"),
            {
                "infra_type": "well",
                "rows_json": _json.dumps(rows),
                "map:name": "name",
                "map:wcr_number": "WCR_NO",
                "map:latitude": "LAT",
                "map:longitude": "LON",
                "map:casing_diameter_in": "CASING_DIA",
                "map:screen_top_ft": "SCREEN_TOP",
                "map:tested_yield_gpm": "YIELD_GPM",
                "map:pump_type": "PUMP_TYPE",
            },
        )
        assert resp.status_code == 200
        # One valid row created, one skipped (blank name).
        assert Well.objects.count() == before + 1
        assert b"Created 1" in resp.content
        created = Well.objects.get(name="Alpha Well")
        assert created.wcr_number == "WCR-1"
        assert created.tested_yield_gpm == Decimal("500")
        assert created.pump_type == "submersible"

    def test_old_upload_route_is_gone(self):
        from django.urls import NoReverseMatch

        with pytest.raises(NoReverseMatch):
            reverse("infrastructure:upload")

    def test_result_counts_reconcile(self, auth_client):
        """created + skipped must equal the total shown — the result screen's
        whole job is an honest count, so the badges must never disagree."""
        import json as _json

        rows = [
            {"name": "", "LAT": "37.2", "LON": "-119.5", "reg_id": "R-1"},          # bad: no name
            {"name": "Dup", "LAT": "37.3", "LON": "-119.6", "reg_id": "DUP-IT"},    # bad: dup (below)
            {"name": "Fine", "LAT": "37.4", "LON": "-119.7", "reg_id": "R-3"},      # good
        ]
        # Seed an existing well so row 2's reg id is a true duplicate.
        from tests.factories import WellFactory

        WellFactory(well_registration_id="DUP-IT")

        resp = auth_client.post(
            reverse("infrastructure:import_commit"),
            {
                "infra_type": "well",
                "rows_json": _json.dumps(rows),
                "map:name": "name",
                "map:latitude": "LAT",
                "map:longitude": "LON",
                "map:well_registration_id": "reg_id",
            },
        )
        body = resp.content.decode()
        assert "Created 1" in body
        assert "Skipped 2" in body
        assert "3 rows total" in body  # 1 + 2 == 3, badges reconcile
