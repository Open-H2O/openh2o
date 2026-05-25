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
from django.test import override_settings

from datasync.models import DataSource, MonitoredStation
from geography.models import Boundary, Flowline, Zone
from geography.services.arcgis import (
    esri_polygon_to_geos,
    esri_polyline_to_geos,
    geos_to_esri_geometry,
)
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


# ---------------------------------------------------------------------------
# Polyline geometry conversion tests
# ---------------------------------------------------------------------------

class TestEsriPolylineToGeos:
    def test_single_path(self):
        """A simple polyline with one path converts to a valid MultiLineString."""
        esri = {
            "paths": [
                [
                    [-119.5, 36.0],
                    [-119.4, 36.1],
                    [-119.3, 36.2],
                    [-119.2, 36.3],
                ]
            ]
        }
        result = esri_polyline_to_geos(esri)

        assert result is not None
        assert result.geom_type == "MultiLineString"
        assert result.srid == 4326
        assert result.valid

    def test_multi_path(self):
        """A polyline with multiple paths produces MultiLineString with multiple lines."""
        esri = {
            "paths": [
                [[-119.5, 36.0], [-119.4, 36.1]],
                [[-119.3, 36.2], [-119.2, 36.3]],
            ]
        }
        result = esri_polyline_to_geos(esri)

        assert result is not None
        assert result.geom_type == "MultiLineString"
        assert len(result) == 2

    def test_empty_returns_none(self):
        """None or empty geometry input returns None."""
        assert esri_polyline_to_geos(None) is None
        assert esri_polyline_to_geos({}) is None
        assert esri_polyline_to_geos({"paths": []}) is None


# ---------------------------------------------------------------------------
# 3DHP flowline test fixtures
# ---------------------------------------------------------------------------

def _3dhp_features():
    """Two sample 3DHP flowline features for testing."""
    return [
        {
            "attributes": {
                "id3dhp": "FL00001",
                "gnisidlabel": "Kaweah River",
                "featuretypelabel": "Stream/River",
                "lengthkm": 12.5,
                "streamorder": 4,
            },
            "geometry": {
                "paths": [
                    [
                        [-119.3, 36.3],
                        [-119.25, 36.32],
                        [-119.2, 36.35],
                        [-119.15, 36.38],
                    ]
                ]
            },
        },
        {
            "attributes": {
                "id3dhp": "FL00002",
                "gnisidlabel": "Mill Creek",
                "featuretypelabel": "Stream/River",
                "lengthkm": 5.2,
                "streamorder": 2,
            },
            "geometry": {
                "paths": [
                    [
                        [-119.28, 36.31],
                        [-119.24, 36.33],
                        [-119.2, 36.35],
                    ]
                ]
            },
        },
    ]


# ---------------------------------------------------------------------------
# Flowline step tests
# ---------------------------------------------------------------------------

class TestStepFlowlines:
    @patch("geography.services.arcgis.requests.get")
    def test_creates_flowlines(self, mock_get, boundary):
        """Flowlines step creates Flowline records from mocked API response."""
        mock_get.return_value = _make_mock_response(_3dhp_features())

        out = StringIO()
        call_command(
            "auto_populate",
            boundary=str(boundary.pk),
            steps="flowlines",
            stdout=out,
        )

        flowlines = Flowline.objects.filter(boundary=boundary)
        assert flowlines.count() == 2

        names = set(flowlines.values_list("name", flat=True))
        assert names == {"Kaweah River", "Mill Creek"}

        kaweah = flowlines.get(name="Kaweah River")
        assert kaweah.stream_order == 4
        assert kaweah.geometry is not None
        assert kaweah.geometry.geom_type == "MultiLineString"

    @patch("geography.services.arcgis.requests.get")
    def test_idempotent(self, mock_get, boundary):
        """Running the flowlines step twice creates flowlines only once."""
        mock_get.return_value = _make_mock_response(_3dhp_features())

        call_command(
            "auto_populate",
            boundary=str(boundary.pk),
            steps="flowlines",
            stdout=StringIO(),
        )
        assert Flowline.objects.filter(boundary=boundary).count() == 2

        mock_get.return_value = _make_mock_response(_3dhp_features())
        call_command(
            "auto_populate",
            boundary=str(boundary.pk),
            steps="flowlines",
            stdout=StringIO(),
        )
        assert Flowline.objects.filter(boundary=boundary).count() == 2

    @patch("geography.services.arcgis.requests.get")
    def test_dry_run_flowlines(self, mock_get, boundary):
        """Dry run reports flowline count but writes nothing."""
        mock_get.return_value = _make_mock_response(_3dhp_features())

        out = StringIO()
        call_command(
            "auto_populate",
            boundary=str(boundary.pk),
            steps="flowlines",
            dry_run=True,
            stdout=out,
        )

        assert Flowline.objects.count() == 0
        output = out.getvalue()
        assert "would create" in output.lower() or "2" in output


# ---------------------------------------------------------------------------
# County loading test fixtures
# ---------------------------------------------------------------------------

def _county_features():
    """Two sample county features for testing."""
    return [
        {
            "attributes": {
                "NAME": "Tulare County",
                "GEOID": "06107",
                "BASENAME": "Tulare",
            },
            "geometry": {
                "rings": [
                    [
                        [-119.8, 35.8],
                        [-118.3, 35.8],
                        [-118.3, 36.7],
                        [-119.8, 36.7],
                        [-119.8, 35.8],
                    ]
                ]
            },
        },
        {
            "attributes": {
                "NAME": "Kings County",
                "GEOID": "06031",
                "BASENAME": "Kings",
            },
            "geometry": {
                "rings": [
                    [
                        [-120.2, 35.8],
                        [-119.5, 35.8],
                        [-119.5, 36.3],
                        [-120.2, 36.3],
                        [-120.2, 35.8],
                    ]
                ]
            },
        },
    ]


# ---------------------------------------------------------------------------
# County loading tests
# ---------------------------------------------------------------------------

class TestLoadCounties:
    @patch("geography.services.arcgis.requests.get")
    def test_creates_boundaries(self, mock_get):
        """load_counties creates Boundary records for each county."""
        mock_get.return_value = _make_mock_response(_county_features())

        out = StringIO()
        call_command("load_counties", stdout=out)

        boundaries = Boundary.objects.filter(name__endswith="County")
        assert boundaries.count() == 2

        names = set(boundaries.values_list("name", flat=True))
        assert names == {"Tulare County", "Kings County"}

        tulare = boundaries.get(name="Tulare County")
        assert "06107" in tulare.description
        assert tulare.geometry is not None

    @patch("geography.services.arcgis.requests.get")
    def test_idempotent_counties(self, mock_get):
        """Running load_counties twice creates counties only once."""
        mock_get.return_value = _make_mock_response(_county_features())

        call_command("load_counties", stdout=StringIO())
        assert Boundary.objects.filter(name__endswith="County").count() == 2

        mock_get.return_value = _make_mock_response(_county_features())
        call_command("load_counties", stdout=StringIO())
        assert Boundary.objects.filter(name__endswith="County").count() == 2


# ---------------------------------------------------------------------------
# Station discovery test helpers
# ---------------------------------------------------------------------------

def _mock_station_list(source_code):
    """Return mock station dicts for a given source."""
    return [
        {
            "station_id": f"{source_code.upper()}-001",
            "name": f"Test {source_code} station 1",
            "latitude": 36.3,
            "longitude": -119.3,
            "parameters": ["param1"],
        },
        {
            "station_id": f"{source_code.upper()}-002",
            "name": f"Test {source_code} station 2",
            "latitude": 36.4,
            "longitude": -119.2,
            "parameters": ["param2"],
        },
    ]


@pytest.fixture
def data_sources():
    """Create DataSource records for CDEC, USGS, and CIMIS."""
    sources = {}
    for code in ("cdec", "usgs", "cimis"):
        sources[code] = DataSource.objects.create(
            name=code.upper(),
            code=code,
            url=f"https://{code}.example.com",
        )
    return sources


# ---------------------------------------------------------------------------
# Station step tests
# ---------------------------------------------------------------------------

@pytest.mark.django_db
@override_settings(DATASYNC_MOCK_MODE=False)
class TestStationsStep:
    @patch("datasync.adapters.cdec.CDECAdapter.discover_stations")
    @patch("datasync.adapters.usgs.USGSAdapter.discover_stations")
    @patch("datasync.adapters.cimis.CIMISAdapter.discover_stations")
    def test_creates_inactive_stations(
        self, mock_cimis, mock_usgs, mock_cdec, boundary, data_sources
    ):
        """Stations step creates inactive MonitoredStation records."""
        mock_cdec.return_value = _mock_station_list("cdec")
        mock_usgs.return_value = _mock_station_list("usgs")
        mock_cimis.return_value = _mock_station_list("cimis")

        out = StringIO()
        call_command(
            "auto_populate",
            boundary=str(boundary.pk),
            steps="stations",
            stdout=out,
        )

        stations = MonitoredStation.objects.all()
        assert stations.count() == 6
        assert stations.filter(is_active=False).count() == 6

    @patch("datasync.adapters.cdec.CDECAdapter.discover_stations")
    @patch("datasync.adapters.usgs.USGSAdapter.discover_stations")
    @patch("datasync.adapters.cimis.CIMISAdapter.discover_stations")
    def test_idempotent(
        self, mock_cimis, mock_usgs, mock_cdec, boundary, data_sources
    ):
        """Running stations step twice creates stations only once."""
        mock_cdec.return_value = _mock_station_list("cdec")
        mock_usgs.return_value = _mock_station_list("usgs")
        mock_cimis.return_value = _mock_station_list("cimis")

        call_command(
            "auto_populate",
            boundary=str(boundary.pk),
            steps="stations",
            stdout=StringIO(),
        )
        assert MonitoredStation.objects.count() == 6

        mock_cdec.return_value = _mock_station_list("cdec")
        mock_usgs.return_value = _mock_station_list("usgs")
        mock_cimis.return_value = _mock_station_list("cimis")

        call_command(
            "auto_populate",
            boundary=str(boundary.pk),
            steps="stations",
            stdout=StringIO(),
        )
        assert MonitoredStation.objects.count() == 6

    def test_handles_missing_datasource(self, boundary):
        """Stations step warns but doesn't crash when DataSource is missing."""
        out = StringIO()
        call_command(
            "auto_populate",
            boundary=str(boundary.pk),
            steps="stations",
            stdout=out,
        )
        output = out.getvalue()
        assert "not found" in output.lower()
        assert MonitoredStation.objects.count() == 0

    @patch("datasync.adapters.cdec.CDECAdapter.discover_stations")
    @patch("datasync.adapters.usgs.USGSAdapter.discover_stations")
    @patch("datasync.adapters.cimis.CIMISAdapter.discover_stations")
    def test_dry_run(
        self, mock_cimis, mock_usgs, mock_cdec, boundary, data_sources
    ):
        """Dry run reports counts without creating any records."""
        mock_cdec.return_value = _mock_station_list("cdec")
        mock_usgs.return_value = _mock_station_list("usgs")
        mock_cimis.return_value = _mock_station_list("cimis")

        out = StringIO()
        call_command(
            "auto_populate",
            boundary=str(boundary.pk),
            steps="stations",
            dry_run=True,
            stdout=out,
        )

        assert MonitoredStation.objects.count() == 0
        output = out.getvalue()
        assert "would create" in output.lower()
