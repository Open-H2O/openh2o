"""
Tests for the ArcGIS REST client and auto_populate management command.

Covers geometry conversion, command argument handling, B118 basin
population with mocked API responses, idempotency, and dry-run mode.
"""

from io import StringIO
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.gis.geos import MultiPolygon, Polygon
from django.core.management import call_command
from django.core.management.base import CommandError

from geography.models import Boundary, Zone
from geography.services.arcgis import esri_polygon_to_geos, geos_to_esri_geometry
from parcels.models import Parcel


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def boundary():
    return Boundary.objects.create(
        name="Test Boundary",
        geometry=MultiPolygon(Polygon.from_bbox((-119.5, 36.0, -119.0, 36.5))),
    )


def _make_mock_response(features, exceeded=False):
    """Build a mock requests.Response with ArcGIS JSON payload."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "features": features,
        "exceededTransferLimit": exceeded,
    }
    return mock_resp


def _b118_features():
    """Two sample B118 basin features for testing."""
    return [
        {
            "attributes": {
                "Basin_Name": "San Joaquin Valley",
                "Basin_Subbasin_Name": "Kaweah",
                "Basin_Subbasin_Number": "5-022.11",
                "Area_SqMiles": 445.2,
            },
            "geometry": {
                "rings": [
                    [
                        [-119.5, 36.0],
                        [-119.0, 36.0],
                        [-119.0, 36.5],
                        [-119.5, 36.5],
                        [-119.5, 36.0],
                    ]
                ]
            },
        },
        {
            "attributes": {
                "Basin_Name": "San Joaquin Valley",
                "Basin_Subbasin_Name": "Tule",
                "Basin_Subbasin_Number": "5-022.13",
                "Area_SqMiles": 560.8,
            },
            "geometry": {
                "rings": [
                    [
                        [-119.4, 35.8],
                        [-118.9, 35.8],
                        [-118.9, 36.3],
                        [-119.4, 36.3],
                        [-119.4, 35.8],
                    ]
                ]
            },
        },
    ]


# ---------------------------------------------------------------------------
# Geometry conversion tests
# ---------------------------------------------------------------------------

class TestEsriPolygonToGeos:
    def test_single_ring(self):
        """A simple polygon with one ring converts to a valid MultiPolygon."""
        esri = {
            "rings": [
                [
                    [-119.5, 36.0],
                    [-119.0, 36.0],
                    [-119.0, 36.5],
                    [-119.5, 36.5],
                    [-119.5, 36.0],
                ]
            ]
        }
        result = esri_polygon_to_geos(esri)

        assert result is not None
        assert result.geom_type == "MultiPolygon"
        assert result.srid == 4326
        assert result.valid

    def test_empty_returns_none(self):
        """None or empty geometry input returns None."""
        assert esri_polygon_to_geos(None) is None
        assert esri_polygon_to_geos({}) is None
        assert esri_polygon_to_geos({"rings": []}) is None


class TestGeosToEsriGeometry:
    def test_roundtrip(self):
        """MultiPolygon -> esri -> back produces equivalent coordinates."""
        original = MultiPolygon(
            Polygon.from_bbox((-119.5, 36.0, -119.0, 36.5)),
            srid=4326,
        )

        esri = geos_to_esri_geometry(original)
        assert "rings" in esri
        assert esri["spatialReference"]["wkid"] == 4326

        roundtripped = esri_polygon_to_geos(esri)
        assert roundtripped is not None
        assert roundtripped.geom_type == "MultiPolygon"

        # Coordinates should match within floating point tolerance.
        # Compare bounding boxes as a practical check.
        orig_extent = original.extent
        rt_extent = roundtripped.extent
        for a, b in zip(orig_extent, rt_extent):
            assert abs(a - b) < 1e-6, f"Extent mismatch: {a} vs {b}"


# ---------------------------------------------------------------------------
# Command tests
# ---------------------------------------------------------------------------

class TestAutoPopulateBoundaryLookup:
    def test_boundary_not_found(self):
        """Command raises an error when the boundary does not exist."""
        with pytest.raises(CommandError, match="No boundary found"):
            call_command(
                "auto_populate",
                boundary="Nonexistent District",
                stdout=StringIO(),
            )


class TestStepBasins:
    @patch("geography.services.arcgis.requests.get")
    def test_creates_zones(self, mock_get, boundary):
        """B118 step creates Zone records from mocked API response."""
        mock_get.return_value = _make_mock_response(_b118_features())

        out = StringIO()
        call_command(
            "auto_populate",
            boundary=str(boundary.pk),
            steps="basins",
            stdout=out,
        )

        zones = Zone.objects.filter(boundary=boundary, zone_type="subbasin")
        assert zones.count() == 2

        names = set(zones.values_list("name", flat=True))
        assert names == {"Kaweah", "Tule"}

        # Verify descriptions contain basin numbers
        kaweah = zones.get(name="Kaweah")
        assert "5-022.11" in kaweah.description

    @patch("geography.services.arcgis.requests.get")
    def test_idempotent(self, mock_get, boundary):
        """Running the basins step twice creates zones only once."""
        mock_get.return_value = _make_mock_response(_b118_features())

        call_command(
            "auto_populate",
            boundary=str(boundary.pk),
            steps="basins",
            stdout=StringIO(),
        )
        assert Zone.objects.filter(boundary=boundary).count() == 2

        # Run again with the same data
        mock_get.return_value = _make_mock_response(_b118_features())
        call_command(
            "auto_populate",
            boundary=str(boundary.pk),
            steps="basins",
            stdout=StringIO(),
        )
        assert Zone.objects.filter(boundary=boundary).count() == 2

    @patch("geography.services.arcgis.requests.get")
    def test_dry_run(self, mock_get, boundary):
        """Dry run reports what would be created but writes nothing."""
        mock_get.return_value = _make_mock_response(_b118_features())

        out = StringIO()
        call_command(
            "auto_populate",
            boundary=str(boundary.pk),
            steps="basins",
            dry_run=True,
            stdout=out,
        )

        assert Zone.objects.filter(boundary=boundary).count() == 0
        output = out.getvalue()
        assert "Would create" in output


# ---------------------------------------------------------------------------
# LightBox parcel test fixtures
# ---------------------------------------------------------------------------

def _lightbox_features():
    """Two sample LightBox parcel features for testing."""
    return [
        {
            "attributes": {
                "PARCEL_APN": "100-200-300",
                "SITE_ADDR": "123 Main St",
                "SITE_CITY": "Visalia",
                "SITE_STATE": "CA",
                "SITE_ZIP": "93291",
            },
            "geometry": {
                "rings": [
                    [
                        [-119.3, 36.3],
                        [-119.2, 36.3],
                        [-119.2, 36.4],
                        [-119.3, 36.4],
                        [-119.3, 36.3],
                    ]
                ]
            },
        },
        {
            "attributes": {
                "PARCEL_APN": "100-200-301",
                "SITE_ADDR": "125 Main St",
                "SITE_CITY": "Visalia",
                "SITE_STATE": "CA",
                "SITE_ZIP": "93291",
            },
            "geometry": {
                "rings": [
                    [
                        [-119.28, 36.31],
                        [-119.18, 36.31],
                        [-119.18, 36.41],
                        [-119.28, 36.41],
                        [-119.28, 36.31],
                    ]
                ]
            },
        },
    ]


# ---------------------------------------------------------------------------
# Parcel step tests
# ---------------------------------------------------------------------------

class TestStepParcels:
    @patch("geography.services.arcgis.requests.get")
    def test_creates_parcels(self, mock_get, boundary):
        """Parcels step creates Parcel records from mocked API response."""
        mock_get.return_value = _make_mock_response(_lightbox_features())

        out = StringIO()
        call_command(
            "auto_populate",
            boundary=str(boundary.pk),
            steps="parcels",
            stdout=out,
        )

        parcels = Parcel.objects.all()
        assert parcels.count() == 2

        apns = set(parcels.values_list("parcel_number", flat=True))
        assert apns == {"100-200-300", "100-200-301"}

        p = parcels.get(parcel_number="100-200-300")
        assert p.geometry is not None
        assert "123 Main St" in p.address

    @patch("geography.services.arcgis.requests.get")
    def test_idempotent(self, mock_get, boundary):
        """Running the parcels step twice creates parcels only once."""
        mock_get.return_value = _make_mock_response(_lightbox_features())

        call_command(
            "auto_populate",
            boundary=str(boundary.pk),
            steps="parcels",
            stdout=StringIO(),
        )
        assert Parcel.objects.count() == 2

        mock_get.return_value = _make_mock_response(_lightbox_features())
        call_command(
            "auto_populate",
            boundary=str(boundary.pk),
            steps="parcels",
            stdout=StringIO(),
        )
        assert Parcel.objects.count() == 2

    @patch("geography.services.arcgis.requests.get")
    def test_dry_run_parcels(self, mock_get, boundary):
        """Dry run reports parcel count but writes nothing."""
        mock_get.return_value = _make_mock_response(_lightbox_features())

        out = StringIO()
        call_command(
            "auto_populate",
            boundary=str(boundary.pk),
            steps="parcels",
            dry_run=True,
            stdout=out,
        )

        assert Parcel.objects.count() == 0
        output = out.getvalue()
        assert "would create" in output.lower() or "2" in output

    @patch("geography.services.arcgis.requests.get")
    def test_skips_empty_apn(self, mock_get, boundary):
        """Features with empty or missing APN are skipped."""
        features = _lightbox_features()
        features.append(
            {
                "attributes": {
                    "PARCEL_APN": "",
                    "SITE_ADDR": "999 Nowhere",
                    "SITE_CITY": "Nowhere",
                    "SITE_STATE": "CA",
                    "SITE_ZIP": "00000",
                },
                "geometry": {
                    "rings": [
                        [
                            [-119.1, 36.1],
                            [-119.0, 36.1],
                            [-119.0, 36.2],
                            [-119.1, 36.2],
                            [-119.1, 36.1],
                        ]
                    ]
                },
            }
        )
        mock_get.return_value = _make_mock_response(features)

        call_command(
            "auto_populate",
            boundary=str(boundary.pk),
            steps="parcels",
            stdout=StringIO(),
        )

        assert Parcel.objects.count() == 2

    @patch("geography.services.arcgis.requests.get")
    def test_pagination(self, mock_get, boundary):
        """Parcels from multiple pages are all created."""
        page1_features = [_lightbox_features()[0]]
        page2_features = [_lightbox_features()[1]]

        resp_page1 = _make_mock_response(page1_features, exceeded=True)
        resp_page2 = _make_mock_response(page2_features, exceeded=False)
        mock_get.side_effect = [resp_page1, resp_page2]

        call_command(
            "auto_populate",
            boundary=str(boundary.pk),
            steps="parcels",
            stdout=StringIO(),
        )

        assert Parcel.objects.count() == 2
        apns = set(Parcel.objects.values_list("parcel_number", flat=True))
        assert apns == {"100-200-300", "100-200-301"}
