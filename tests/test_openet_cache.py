"""
Tests for OpenETCache model and cache-aware OpenET adapter methods.

Covers cache lifecycle (creation, staleness, budget), cache-hit/miss
sync behavior, and budget enforcement.
"""

from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.gis.geos import MultiPolygon, Point, Polygon
from django.utils import timezone

from datasync.adapters.openet import OpenETAdapter
from datasync.models import OpenETCache


@pytest.fixture
def sample_geometry():
    return MultiPolygon(
        Polygon.from_bbox((-119.3, 36.3, -119.2, 36.4)), srid=4326
    )


@pytest.fixture
def parcel(sample_geometry):
    from parcels.models import Parcel

    return Parcel.objects.create(
        parcel_number="TEST-001",
        geometry=sample_geometry,
        status="active",
    )


@pytest.fixture
def cache_entry(parcel, sample_geometry):
    from datetime import date

    return OpenETCache.objects.create(
        parcel=parcel,
        geometry=sample_geometry,
        start_date=date(2025, 1, 1),
        end_date=date(2025, 12, 31),
        variable="ET",
        model_name="Ensemble",
        et_data=[{"date": "2025-01", "et": 42.5, "unit": "mm"}],
    )


@pytest.mark.django_db
class TestOpenETCacheModel:
    def test_cache_creation(self, cache_entry):
        assert cache_entry.pk is not None
        assert cache_entry.variable == "ET"
        assert cache_entry.model_name == "Ensemble"
        assert len(cache_entry.et_data) == 1
        assert cache_entry.et_data[0]["et"] == 42.5

    def test_cache_staleness_fresh(self, cache_entry):
        assert cache_entry.is_stale() is False

    def test_cache_staleness_old(self, cache_entry):
        OpenETCache.objects.filter(pk=cache_entry.pk).update(
            queried_at=timezone.now() - timedelta(days=60)
        )
        cache_entry.refresh_from_db()
        assert cache_entry.is_stale() is True

    def test_cache_staleness_custom_max_age(self, cache_entry):
        OpenETCache.objects.filter(pk=cache_entry.pk).update(
            queried_at=timezone.now() - timedelta(days=5)
        )
        cache_entry.refresh_from_db()
        assert cache_entry.is_stale(max_age_days=3) is True
        assert cache_entry.is_stale(max_age_days=10) is False

    def test_monthly_query_count(self, cache_entry):
        assert OpenETCache.monthly_query_count() == 1

    def test_budget_check_under(self, cache_entry):
        ok, used, limit = OpenETCache.check_budget(budget=10)
        assert ok is True
        assert used == 1
        assert limit == 10

    def test_budget_check_over(self, cache_entry):
        ok, used, limit = OpenETCache.check_budget(budget=1)
        assert ok is False
        assert used == 1
        assert limit == 1


@pytest.mark.django_db
class TestSyncWithCache:
    def test_cache_hit_skips_api(self, parcel, cache_entry):
        adapter = OpenETAdapter()
        with patch.object(adapter, "fetch_polygon") as mock_fetch:
            result = adapter.sync_with_cache(
                parcel,
                cache_entry.start_date,
                cache_entry.end_date,
            )
            mock_fetch.assert_not_called()
        assert result == cache_entry.et_data

    def test_cache_miss_creates_entry(self, parcel, sample_geometry):
        from datetime import date

        adapter = OpenETAdapter()
        mock_raw = [
            {"date": "2024-06", "et": 55.0, "station_id": "test", "value": 55.0}
        ]

        with patch.object(adapter, "fetch_polygon", return_value=mock_raw):
            with patch.object(
                adapter,
                "parse",
                return_value=[
                    {
                        "station_id": "test",
                        "observation_date": "2024-06",
                        "parameter_code": "ET",
                        "value": 55.0,
                        "unit": "mm",
                    }
                ],
            ):
                with patch.object(
                    adapter,
                    "validate",
                    return_value=(
                        [
                            {
                                "station_id": "test",
                                "observation_date": "2024-06",
                                "parameter_code": "ET",
                                "value": 55.0,
                                "unit": "mm",
                            }
                        ],
                        [],
                    ),
                ):
                    result = adapter.sync_with_cache(
                        parcel, date(2024, 1, 1), date(2024, 12, 31)
                    )

        assert result is not None
        assert len(result) == 1
        assert OpenETCache.objects.filter(parcel=parcel).count() == 1

    @patch("datasync.models.OpenETCache.check_budget", return_value=(False, 400, 400))
    def test_budget_blocks_query(self, mock_budget, parcel):
        from datetime import date

        adapter = OpenETAdapter()
        with patch.object(adapter, "fetch_polygon") as mock_fetch:
            result = adapter.sync_with_cache(
                parcel, date(2024, 1, 1), date(2024, 12, 31)
            )
            mock_fetch.assert_not_called()
        assert result is None
