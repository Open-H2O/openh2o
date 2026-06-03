# SPDX-License-Identifier: AGPL-3.0-or-later
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

from datasync.models import DataSource, MonitoredStation
from geography.models import Boundary, Flowline, Zone
from geography.services.arcgis import (
    esri_polygon_to_geos,
    esri_polyline_to_geos,
    geos_to_esri_geometry,
    query_feature_server,
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
# Transport tests
# ---------------------------------------------------------------------------

class TestQueryFeatureServerTransport:
    """The spatial query must POST (geometry in the body), never GET.

    Regression for the 50-02 "414 Request-URI Too Large" bug: a
    full-resolution boundary (e.g. the Merced Subbasin's 8,446-vertex
    polygon) serialized into a GET query string exceeds the server's
    URL-length limit and silently returns zero features. POSTing the same
    parameters in the request body removes the limit.
    """

    @patch("geography.services.arcgis.requests.post")
    def test_uses_post_with_geometry_in_body(self, mock_post):
        mock_post.return_value = _make_mock_response(_b118_features())

        # A deliberately large geometry payload — the kind that overflows a URL.
        big_geom = {"rings": [[[(-120.0 + i * 1e-5), 37.0] for i in range(9000)]]}

        pages = list(
            query_feature_server(
                "https://example.test/MapServer/0/query",
                geometry=big_geom,
                geometry_type="esriGeometryPolygon",
                spatial_rel="esriSpatialRelIntersects",
            )
        )

        assert pages, "expected at least one page of features"
        mock_post.assert_called()
        # Parameters (incl. the big geometry) ride in the POST body, not the URL.
        _args, kwargs = mock_post.call_args
        assert "data" in kwargs, "params must be sent as the POST body (data=)"
        assert "geometry" in kwargs["data"]
        assert "params" not in kwargs, "must not fall back to a GET query string"


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
    @patch("geography.services.arcgis.requests.post")
    def test_creates_zones(self, mock_post, boundary):
        """B118 step creates Zone records from mocked API response."""
        mock_post.return_value = _make_mock_response(_b118_features())

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

    @patch("geography.services.arcgis.requests.post")
    def test_idempotent(self, mock_post, boundary):
        """Running the basins step twice creates zones only once."""
        mock_post.return_value = _make_mock_response(_b118_features())

        call_command(
            "auto_populate",
            boundary=str(boundary.pk),
            steps="basins",
            stdout=StringIO(),
        )
        assert Zone.objects.filter(boundary=boundary).count() == 2

        # Run again with the same data
        mock_post.return_value = _make_mock_response(_b118_features())
        call_command(
            "auto_populate",
            boundary=str(boundary.pk),
            steps="basins",
            stdout=StringIO(),
        )
        assert Zone.objects.filter(boundary=boundary).count() == 2

    @patch("geography.services.arcgis.requests.post")
    def test_dry_run(self, mock_post, boundary):
        """Dry run reports what would be created but writes nothing."""
        mock_post.return_value = _make_mock_response(_b118_features())

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
    @patch("geography.services.arcgis.requests.post")
    def test_creates_parcels(self, mock_post, boundary):
        """Parcels step creates Parcel records from mocked API response."""
        mock_post.return_value = _make_mock_response(_lightbox_features())

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

    @patch("geography.services.arcgis.requests.post")
    def test_idempotent(self, mock_post, boundary):
        """Running the parcels step twice creates parcels only once."""
        mock_post.return_value = _make_mock_response(_lightbox_features())

        call_command(
            "auto_populate",
            boundary=str(boundary.pk),
            steps="parcels",
            stdout=StringIO(),
        )
        assert Parcel.objects.count() == 2

        mock_post.return_value = _make_mock_response(_lightbox_features())
        call_command(
            "auto_populate",
            boundary=str(boundary.pk),
            steps="parcels",
            stdout=StringIO(),
        )
        assert Parcel.objects.count() == 2

    @patch("geography.services.arcgis.requests.post")
    def test_dry_run_parcels(self, mock_post, boundary):
        """Dry run reports parcel count but writes nothing."""
        mock_post.return_value = _make_mock_response(_lightbox_features())

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

    @patch("geography.services.arcgis.requests.post")
    def test_skips_empty_apn(self, mock_post, boundary):
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
        mock_post.return_value = _make_mock_response(features)

        call_command(
            "auto_populate",
            boundary=str(boundary.pk),
            steps="parcels",
            stdout=StringIO(),
        )

        assert Parcel.objects.count() == 2

    @patch("geography.services.arcgis.requests.post")
    def test_pagination(self, mock_post, boundary):
        """Parcels from multiple pages are all created."""
        page1_features = [_lightbox_features()[0]]
        page2_features = [_lightbox_features()[1]]

        resp_page1 = _make_mock_response(page1_features, exceeded=True)
        resp_page2 = _make_mock_response(page2_features, exceeded=False)
        mock_post.side_effect = [resp_page1, resp_page2]

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
    @patch("geography.services.arcgis.requests.post")
    def test_creates_flowlines(self, mock_post, boundary):
        """Flowlines step creates Flowline records from mocked API response."""
        mock_post.return_value = _make_mock_response(_3dhp_features())

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

    @patch("geography.services.arcgis.requests.post")
    def test_idempotent(self, mock_post, boundary):
        """Running the flowlines step twice creates flowlines only once."""
        mock_post.return_value = _make_mock_response(_3dhp_features())

        call_command(
            "auto_populate",
            boundary=str(boundary.pk),
            steps="flowlines",
            stdout=StringIO(),
        )
        assert Flowline.objects.filter(boundary=boundary).count() == 2

        mock_post.return_value = _make_mock_response(_3dhp_features())
        call_command(
            "auto_populate",
            boundary=str(boundary.pk),
            steps="flowlines",
            stdout=StringIO(),
        )
        assert Flowline.objects.filter(boundary=boundary).count() == 2

    @patch("geography.services.arcgis.requests.post")
    def test_dry_run_flowlines(self, mock_post, boundary):
        """Dry run reports flowline count but writes nothing."""
        mock_post.return_value = _make_mock_response(_3dhp_features())

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
    @patch("geography.services.arcgis.requests.post")
    def test_creates_boundaries(self, mock_post):
        """load_counties creates Boundary records for each county."""
        mock_post.return_value = _make_mock_response(_county_features())

        out = StringIO()
        call_command("load_counties", stdout=out)

        boundaries = Boundary.objects.filter(name__endswith="County")
        assert boundaries.count() == 2

        names = set(boundaries.values_list("name", flat=True))
        assert names == {"Tulare County", "Kings County"}

        tulare = boundaries.get(name="Tulare County")
        assert "06107" in tulare.description
        assert tulare.geometry is not None

    @patch("geography.services.arcgis.requests.post")
    def test_idempotent_counties(self, mock_post):
        """Running load_counties twice creates counties only once."""
        mock_post.return_value = _make_mock_response(_county_features())

        call_command("load_counties", stdout=StringIO())
        assert Boundary.objects.filter(name__endswith="County").count() == 2

        mock_post.return_value = _make_mock_response(_county_features())
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


def _fake_adapter(stations=None, *, missing=None, raises=None):
    """Build a stand-in adapter for patching get_adapter in the station step.

    - stations: list returned by discover_stations (defaults to []).
    - missing: value returned by missing_required_credential() — a truthy label
      means the step should treat the provider as a clean no-key skip.
    - raises: an exception instance; discover_stations raises it (fail-soft test).
    """
    adapter = MagicMock()
    adapter.missing_required_credential.return_value = missing
    if raises is not None:
        adapter.discover_stations.side_effect = raises
    else:
        adapter.discover_stations.return_value = stations or []
    return adapter


# The full set the expanded station step attempts, in declared order.
LIVE_DISCOVERY_CODES = ("usgs", "cdec", "dwr_wdl", "dwr_sgma", "cimis", "noaa", "cnrfc")


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


@pytest.fixture
def all_data_sources():
    """Create DataSource rows for every provider the step touches, plus openet.

    openet is seeded deliberately so a test can prove the step never *attempts*
    it even when the DataSource exists — the exclusion is in the code, not an
    accident of a missing row.
    """
    codes = (*LIVE_DISCOVERY_CODES, "openet")
    return {
        code: DataSource.objects.create(
            name=code.upper(),
            code=code,
            url=f"https://{code}.example.com",
        )
        for code in codes
    }


# ---------------------------------------------------------------------------
# Station step tests
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestStationsStep:
    @patch("datasync.adapters.cdec.CDECAdapter.discover_stations")
    @patch("datasync.adapters.usgs.USGSAdapter.discover_stations")
    @patch("datasync.adapters.cimis.CIMISAdapter.discover_stations")
    def test_creates_inactive_stations(
        self, mock_cimis, mock_usgs, mock_cdec, boundary, data_sources, settings,
        monkeypatch,
    ):
        """Stations step creates inactive MonitoredStation records."""
        settings.DATASYNC_MOCK_MODE = False
        # CIMIS is key-gated; give it a key so it is queried (not skipped).
        monkeypatch.setenv("CIMIS_API_KEY", "test-key")
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
        self, mock_cimis, mock_usgs, mock_cdec, boundary, data_sources, settings,
        monkeypatch,
    ):
        """Running stations step twice creates stations only once."""
        settings.DATASYNC_MOCK_MODE = False
        monkeypatch.setenv("CIMIS_API_KEY", "test-key")
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
        self, mock_cimis, mock_usgs, mock_cdec, boundary, data_sources, settings,
        monkeypatch,
    ):
        """Dry run reports counts without creating any records."""
        settings.DATASYNC_MOCK_MODE = False
        monkeypatch.setenv("CIMIS_API_KEY", "test-key")
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

    # ── ISS-046: statewide, multi-provider, fail-soft, boundary-driven ──────

    @patch("geography.management.commands.auto_populate.get_adapter")
    def test_attempts_all_live_providers_never_openet(
        self, mock_post_adapter, boundary, all_data_sources, settings
    ):
        """The step queries every live-discovery provider and never OpenET."""
        settings.DATASYNC_MOCK_MODE = False
        mock_post_adapter.side_effect = lambda code: _fake_adapter([])

        call_command(
            "auto_populate",
            boundary=str(boundary.pk),
            steps="stations",
            stdout=StringIO(),
        )

        attempted = {call.args[0] for call in mock_post_adapter.call_args_list}
        assert attempted == set(LIVE_DISCOVERY_CODES)
        # OpenET is geometry-based — it must never be asked for stations, even
        # though a DataSource row exists for it.
        assert "openet" not in attempted
        assert "openet_gee" not in attempted

    @patch("geography.management.commands.auto_populate.get_adapter")
    def test_new_providers_create_inactive_stations(
        self, mock_post_adapter, boundary, all_data_sources, settings
    ):
        """The three newly-wired providers create inactive stations."""
        settings.DATASYNC_MOCK_MODE = False
        new_codes = {"dwr_wdl", "dwr_sgma", "noaa"}
        mock_post_adapter.side_effect = lambda code: _fake_adapter(
            _mock_station_list(code) if code in new_codes else []
        )

        call_command(
            "auto_populate",
            boundary=str(boundary.pk),
            steps="stations",
            stdout=StringIO(),
        )

        for code in new_codes:
            ds = all_data_sources[code]
            rows = MonitoredStation.objects.filter(data_source=ds)
            assert rows.count() == 2, f"{code} should create 2 stations"
            assert rows.filter(is_active=False).count() == 2
            assert set(rows.values_list("external_station_id", flat=True)) == {
                f"{code.upper()}-001",
                f"{code.upper()}-002",
            }

    @patch("geography.management.commands.auto_populate.get_adapter")
    def test_one_provider_failing_is_non_fatal(
        self, mock_post_adapter, boundary, all_data_sources, settings
    ):
        """One provider raising must not blank the catalog (ISS-046 guarantee)."""
        settings.DATASYNC_MOCK_MODE = False

        def side(code):
            if code == "usgs":
                return _fake_adapter(
                    raises=RuntimeError("simulated outage / network error")
                )
            return _fake_adapter(_mock_station_list(code))

        mock_post_adapter.side_effect = side

        out = StringIO()
        # The raising provider must not propagate out of the command.
        call_command(
            "auto_populate",
            boundary=str(boundary.pk),
            steps="stations",
            stdout=out,
        )

        usgs_ds = all_data_sources["usgs"]
        assert MonitoredStation.objects.filter(data_source=usgs_ds).count() == 0
        # The other 6 providers each created their 2 stations.
        assert MonitoredStation.objects.exclude(data_source=usgs_ds).count() == 12
        assert "failed" in out.getvalue().lower()

    @patch("geography.management.commands.auto_populate.get_adapter")
    def test_missing_api_key_is_clean_skip_not_failure(
        self, mock_post_adapter, boundary, all_data_sources, settings
    ):
        """A key-gated provider with no key is a labeled skip, not an error."""
        settings.DATASYNC_MOCK_MODE = False
        adapters = {}

        def side(code):
            if code in ("cimis", "noaa"):
                adapter = _fake_adapter([], missing="API key (set X)")
            else:
                adapter = _fake_adapter(_mock_station_list(code))
            adapters[code] = adapter
            return adapter

        mock_post_adapter.side_effect = side

        out = StringIO()
        call_command(
            "auto_populate",
            boundary=str(boundary.pk),
            steps="stations",
            stdout=out,
        )

        output = out.getvalue().lower()
        assert "no api key configured" in output
        assert "skipped" in output
        for code in ("cimis", "noaa"):
            ds = all_data_sources[code]
            assert MonitoredStation.objects.filter(data_source=ds).count() == 0
            # discover_stations must not even be called when the key is missing.
            adapters[code].discover_stations.assert_not_called()
        # Key-free providers still populated.
        assert (
            MonitoredStation.objects.filter(
                data_source=all_data_sources["usgs"]
            ).count()
            == 2
        )

    @patch("geography.management.commands.auto_populate.get_adapter")
    def test_idempotent_across_expanded_set(
        self, mock_post_adapter, boundary, all_data_sources, settings
    ):
        """Re-running across the full provider set creates no duplicates."""
        settings.DATASYNC_MOCK_MODE = False
        mock_post_adapter.side_effect = lambda code: _fake_adapter(
            _mock_station_list(code)
        )

        for _ in range(2):
            call_command(
                "auto_populate",
                boundary=str(boundary.pk),
                steps="stations",
                stdout=StringIO(),
            )

        # 7 providers x 2 stations, no duplicate rows on the second run.
        assert MonitoredStation.objects.count() == 14

    @patch("geography.management.commands.auto_populate.get_adapter")
    def test_non_kaweah_boundary_populates(
        self, mock_post_adapter, all_data_sources, settings
    ):
        """A boundary plainly outside Kaweah populates — proves boundary-driven."""
        settings.DATASYNC_MOCK_MODE = False
        # Kaweah sits near (-119.3, 36.3). This bbox is northern California
        # (Sacramento Valley), unambiguously a different watershed.
        non_kaweah = Boundary.objects.create(
            name="Sacramento Valley (non-Kaweah test)",
            geometry=MultiPolygon(Polygon.from_bbox((-122.0, 38.5, -121.5, 39.0))),
        )
        adapters = {}

        def side(code):
            adapter = _fake_adapter(_mock_station_list(code))
            adapters[code] = adapter
            return adapter

        mock_post_adapter.side_effect = side

        call_command(
            "auto_populate",
            boundary=str(non_kaweah.pk),
            steps="stations",
            stdout=StringIO(),
        )

        assert MonitoredStation.objects.count() == 14
        # Discovery ran against THIS boundary's geometry, not a hardcoded one.
        called_geom = adapters["usgs"].discover_stations.call_args.args[0]
        assert called_geom.equals(non_kaweah.geometry)


# ---------------------------------------------------------------------------
# Per-provider entry point (49-02 / ISS-051): the wizard discovers one provider
# per HTMX poll via run_station_provider_step, which reuses _discover_provider —
# the same logic the all-providers command path loops over (locked above).
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestRunStationProviderStep:
    @patch("geography.management.commands.auto_populate.get_adapter")
    def test_runs_exactly_one_provider_and_returns_status(
        self, mock_post_adapter, boundary, all_data_sources, settings
    ):
        """run_station_provider_step discovers a SINGLE provider and reports its
        outcome status — the per-poll entry point the wizard uses."""
        from setup.services import run_station_provider_step

        settings.DATASYNC_MOCK_MODE = False
        adapters = {}

        def side(code):
            adapter = _fake_adapter(_mock_station_list(code))
            adapters[code] = adapter
            return adapter

        mock_post_adapter.side_effect = side

        count, errors, status = run_station_provider_step(boundary, "cdec")

        assert status == "created"
        assert count == 2
        assert errors == []
        # Only cdec was touched — not the whole provider set.
        assert set(adapters) == {"cdec"}
        assert (
            MonitoredStation.objects.filter(
                data_source=all_data_sources["cdec"]
            ).count()
            == 2
        )
        assert MonitoredStation.objects.count() == 2

    @patch("geography.management.commands.auto_populate.get_adapter")
    def test_failing_provider_returns_failed_status_never_raises(
        self, mock_post_adapter, boundary, all_data_sources, settings
    ):
        """A provider raising mid-discovery yields ('failed', friendly message),
        not an exception — so a single poll never dies."""
        from setup.services import run_station_provider_step

        settings.DATASYNC_MOCK_MODE = False
        mock_post_adapter.side_effect = lambda code: _fake_adapter(
            raises=RuntimeError("simulated outage")
        )

        count, errors, status = run_station_provider_step(boundary, "usgs")

        assert status == "failed"
        assert count == 0
        assert errors  # a friendly, non-empty operator message
        assert MonitoredStation.objects.count() == 0

    @patch("geography.management.commands.auto_populate.get_adapter")
    def test_missing_key_provider_is_clean_skip_status(
        self, mock_post_adapter, boundary, all_data_sources, settings
    ):
        """A key-gated provider with no credential reports skipped_no_key with no
        error — a clean labeled skip, never discover_stations called."""
        from setup.services import run_station_provider_step

        settings.DATASYNC_MOCK_MODE = False
        adapter = _fake_adapter([], missing="NOAA API token")
        mock_post_adapter.side_effect = lambda code: adapter

        count, errors, status = run_station_provider_step(boundary, "noaa")

        assert status == "skipped_no_key"
        assert count == 0
        assert errors == []
        adapter.discover_stations.assert_not_called()
