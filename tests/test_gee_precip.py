# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Tests for the GRIDMET per-parcel precipitation path (Phase 38-01).

Earth Engine is never hit live: a small hand-built fake ``ee`` is passed straight
into the reduce functions. The fake branches on the collection id so it drives
BOTH faucets through one object:

  * the OpenET ensemble (ET) path — monthly source images via toList/size, and
  * the GRIDMET (precip) path — daily images summed per month before reducing.

A ``recorder`` captures every ``reduceRegions`` call so we can assert the precip
path reduces ONCE PER MONTH (not once per daily image) and at the GRIDMET grid
scale. The command tests patch the EE entry points in the command's namespace
(patch-where-imported), the same convention as test_openet_gee.py.
"""

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.gis.geos import MultiPolygon, Polygon
from django.core.management import call_command
from django.core.management.base import CommandError

from datasync.adapters.gee import (
    EE_SCALE,
    GRIDMET_COLLECTION,
    PRECIP_REDUCE_SCALE,
    build_precip_data,
    reduce_et_by_parcel,
    reduce_precip_by_parcel,
)
from datasync.models import OpenETCache

INIT = "datasync.management.commands.sync_precip_parcels.init_earth_engine"
REDUCE = "datasync.management.commands.sync_precip_parcels.reduce_precip_by_parcel"


# ---------------------------------------------------------------------------
# Fake Earth Engine — deterministic, no network, drives both faucets.
# ---------------------------------------------------------------------------


class _FakeNum:
    def __init__(self, n):
        self._n = n

    def getInfo(self):
        return self._n


class _FakeReduced:
    def __init__(self, features):
        self._features = features

    def getInfo(self):
        return {"features": self._features}


class _FakeReducer:
    @staticmethod
    def mean():
        return "MEAN"


class _FakeDate:
    def __init__(self, month_key):
        self._mk = month_key

    def format(self, fmt):
        return _FakeNum(self._mk)


class _FakeImage:
    """A monthly image (an ET source image, or a precip monthly-sum)."""

    def __init__(self, month_key, per_parcel, recorder):
        self.month_key = month_key
        self._per_parcel = per_parcel
        self._recorder = recorder

    def get(self, key):  # img.get("system:time_start") on the ET path
        return ("TIME", self.month_key)

    def reduceRegions(self, collection=None, reducer=None, scale=None):
        self._recorder.append((self.month_key, scale))
        return _FakeReduced(
            [
                {"properties": {"parcel_id": pid, "mean": v}}
                for pid, v in self._per_parcel.items()
            ]
        )


class _FakeList:
    def __init__(self, images):
        self._images = images

    def get(self, i):
        return self._images[i]


class _FakeIC:
    def __init__(self, ee, coll, month_key=None):
        self._ee = ee
        self._coll = coll
        self._month_key = month_key

    @property
    def _is_precip(self):
        return self._coll == GRIDMET_COLLECTION

    def filterDate(self, start, end):
        # ET filters the whole window; precip filters ONE month at a time.
        return _FakeIC(self._ee, self._coll, month_key=start[:7])

    def select(self, band):
        return self

    def size(self):
        if self._is_precip:
            return _FakeNum(self._ee.daily_count)
        return _FakeNum(len(self._ee.images))

    def toList(self, n):  # ET path
        return _FakeList(self._ee.images)

    def sum(self):  # precip path — one monthly-total image
        return _FakeImage(
            self._month_key,
            self._ee.data.get(self._month_key, {}),
            self._ee.recorder,
        )


class _FakeEE:
    def __init__(self, data, recorder, daily_count=30):
        # data: ordered {month_key: {parcel_id: value}}
        self.data = data
        self.recorder = recorder
        self.daily_count = daily_count
        self.images = [_FakeImage(mk, pp, recorder) for mk, pp in data.items()]
        self.Reducer = _FakeReducer

    def ImageCollection(self, coll):
        return _FakeIC(self, coll)

    def Image(self, token):
        return token

    def Date(self, time_token):
        return _FakeDate(time_token[1])

    def Feature(self, geom, props):
        return ("FEATURE", props)

    def Geometry(self, geojson):
        return ("GEOM",)

    def FeatureCollection(self, features):
        return ("FC", features)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_geometry():
    return MultiPolygon(Polygon.from_bbox((-119.3, 36.3, -119.2, 36.4)), srid=4326)


@pytest.fixture
def parcel(sample_geometry):
    from parcels.models import Parcel

    return Parcel.objects.create(
        parcel_number="KAW-001",
        geometry=sample_geometry,
        area_acres=Decimal("10.00"),
        status="active",
    )


# ---------------------------------------------------------------------------
# 1. reduce_precip_by_parcel — daily summed to monthly, one reduce per month
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestReducePrecip:
    def test_one_reduce_per_month_at_gridmet_scale(self, parcel):
        data = {
            "2024-06": {parcel.pk: 12.0},
            "2024-07": {parcel.pk: 3.5},
            "2024-08": {parcel.pk: 0.0},  # dry month — 0 mm is valid, not dropped
        }
        recorder = []
        fake = _FakeEE(data, recorder, daily_count=30)

        out = reduce_precip_by_parcel(fake, [parcel], date(2024, 6, 1), date(2024, 8, 31))

        assert out == {parcel.pk: {"2024-06": 12.0, "2024-07": 3.5, "2024-08": 0.0}}
        # 3 months -> 3 reduceRegions, NOT 90 (one per daily image).
        assert [mk for mk, _ in recorder] == ["2024-06", "2024-07", "2024-08"]
        # Precip reduces at the FINE scale (30 m), not GRIDMET's 4.6 km: a coarse
        # reduce null-drops parcels smaller than a pixel (KAW-APN-003 in a live
        # run). Resampling the coarse value finer keeps every parcel.
        assert all(scale == PRECIP_REDUCE_SCALE for _, scale in recorder)
        assert PRECIP_REDUCE_SCALE == EE_SCALE

    def test_zero_daily_images_raises(self, parcel):
        fake = _FakeEE({"2024-06": {parcel.pk: 1.0}}, [], daily_count=0)
        with pytest.raises(RuntimeError, match="0 daily images"):
            reduce_precip_by_parcel(fake, [parcel], date(2024, 6, 1), date(2024, 6, 30))


# ---------------------------------------------------------------------------
# 2. build_precip_data — exact cache shape, sorted
# ---------------------------------------------------------------------------


def test_build_precip_data_shape():
    out = build_precip_data({"2024-07": 3.5, "2024-06": 12.0})
    assert out == [
        {"date": "2024-06", "precip": 12.0, "unit": "mm"},
        {"date": "2024-07", "precip": 3.5, "unit": "mm"},
    ]


# ---------------------------------------------------------------------------
# 3. reduce_et_by_parcel — unchanged shape after the shared-helper refactor
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestReduceEtRegression:
    def test_et_shape_unchanged_at_et_scale(self, parcel):
        data = {"2024-06": {parcel.pk: 150.0}, "2024-07": {parcel.pk: 170.0}}
        recorder = []
        fake = _FakeEE(data, recorder)

        out = reduce_et_by_parcel(fake, [parcel], date(2024, 6, 1), date(2024, 7, 31))

        assert out == {parcel.pk: {"2024-06": 150.0, "2024-07": 170.0}}
        assert [mk for mk, _ in recorder] == ["2024-06", "2024-07"]
        # ET still reduces at OpenET's native 30 m.
        assert all(scale == EE_SCALE for _, scale in recorder)


# ---------------------------------------------------------------------------
# 4. sync_precip_parcels command — cache writes, idempotency, dry-run, gate
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSyncPrecipCommand:
    def test_writes_precip_cache_row(self, parcel):
        canned = {parcel.pk: {"2024-06": 12.5, "2024-07": 3.0}}
        with patch(INIT, return_value=MagicMock()), patch(REDUCE, return_value=canned):
            call_command(
                "sync_precip_parcels",
                start_date="2024-06-01",
                end_date="2024-07-31",
                parcel_prefix="KAW-",
            )
        rows = OpenETCache.objects.filter(variable="precip")
        assert rows.count() == 1
        row = rows.first()
        assert row.model_name == "GRIDMET"
        assert row.parcel_id == parcel.pk
        assert row.et_data == [
            {"date": "2024-06", "precip": 12.5, "unit": "mm"},
            {"date": "2024-07", "precip": 3.0, "unit": "mm"},
        ]

    def test_rerun_is_idempotent(self, parcel):
        canned = {parcel.pk: {"2024-06": 12.5}}
        for _ in range(2):
            with patch(INIT, return_value=MagicMock()), patch(REDUCE, return_value=canned):
                call_command(
                    "sync_precip_parcels",
                    start_date="2024-06-01",
                    end_date="2024-06-30",
                )
        assert OpenETCache.objects.filter(variable="precip").count() == 1

    def test_dry_run_touches_nothing(self, parcel):
        with patch(INIT) as mock_init, patch(REDUCE) as mock_reduce:
            call_command(
                "sync_precip_parcels",
                start_date="2024-06-01",
                end_date="2024-07-31",
                dry_run=True,
            )
            mock_init.assert_not_called()
            mock_reduce.assert_not_called()
        assert OpenETCache.objects.filter(variable="precip").count() == 0

    def test_unconfigured_gee_raises_commanderror(self, parcel):
        with patch(INIT, side_effect=RuntimeError("missing GEE_PROJECT")):
            with pytest.raises(CommandError, match="Earth Engine tier"):
                call_command(
                    "sync_precip_parcels",
                    start_date="2024-06-01",
                    end_date="2024-06-30",
                )
