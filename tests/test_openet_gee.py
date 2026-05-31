# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Tests for the GEE OpenET tier (Phase 37-02).

Earth Engine is mocked throughout: these run WITHOUT a service-account key, so
`init_earth_engine` and `reduce_et_by_parcel` are patched and never hit live EE.
Covers the pure finalized-month skip logic, batched cache writes in the exact
REST shape, the full-cache-hit EE short-circuit, inherited threshold validation,
the cache->ledger contract end to end, and the OPENET_MODE selector.
"""

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.gis.geos import MultiPolygon, Polygon
from django.core.management import call_command
from django.test import override_settings

from datasync.adapters import OpenETAdapter, get_openet_adapter
from datasync.adapters.openet_gee import GEEOpenETAdapter
from datasync.models import OpenETCache

# Path to the names as imported INTO the adapter module (patch targets).
INIT_EE = "datasync.adapters.openet_gee.init_earth_engine"
REDUCE = "datasync.adapters.openet_gee.reduce_et_by_parcel"


@pytest.fixture
def sample_geometry():
    return MultiPolygon(
        Polygon.from_bbox((-119.3, 36.3, -119.2, 36.4)), srid=4326
    )


@pytest.fixture
def parcel(sample_geometry):
    from parcels.models import Parcel

    return Parcel.objects.create(
        parcel_number="KAW-001",
        geometry=sample_geometry,
        area_acres=Decimal("10.00"),
        status="active",
    )


def _cache_row(parcel, geometry, et_data, start=date(2024, 1, 1), end=date(2024, 12, 31)):
    return OpenETCache.objects.create(
        parcel=parcel,
        geometry=geometry,
        start_date=start,
        end_date=end,
        variable="ET",
        model_name="Ensemble",
        et_data=et_data,
    )


# ---------------------------------------------------------------------------
# 1. _months_needing_fetch — pure skip logic (finalization is deterministic)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestMonthsNeedingFetch:
    # today=2024-10-01: Jun finalizes 2024-08-15, Jul 2024-09-15, Aug 2024-10-16.
    # So as of 2024-10-01 Jun + Jul are finalized, Aug is NOT.
    TODAY = date(2024, 10, 1)

    def test_no_cache_returns_all_months(self, parcel):
        adapter = GEEOpenETAdapter()
        needs = adapter._months_needing_fetch(
            [parcel], date(2024, 6, 1), date(2024, 8, 31), self.TODAY
        )
        assert needs[parcel.pk] == ["2024-06", "2024-07", "2024-08"]

    def test_finalized_cached_skipped_nonfinalized_returned(self, parcel, sample_geometry):
        # Cache June (finalized as of TODAY) and August (NOT finalized).
        _cache_row(
            parcel,
            sample_geometry,
            [
                {"date": "2024-06", "et": 150.0, "unit": "mm"},
                {"date": "2024-08", "et": 180.0, "unit": "mm"},
            ],
        )
        adapter = GEEOpenETAdapter()
        needs = adapter._months_needing_fetch(
            [parcel], date(2024, 6, 1), date(2024, 8, 31), self.TODAY
        )
        # June: cached + finalized -> permanent skip.
        assert "2024-06" not in needs[parcel.pk]
        # July: missing -> fetch. August: cached but not finalized -> re-fetch.
        assert needs[parcel.pk] == ["2024-07", "2024-08"]

    def test_finalization_boundary_at_settle_lag(self, parcel):
        # July 2024 finalizes 45 days after month-end: 2024-08-01 + 45 = 2024-09-15.
        adapter = GEEOpenETAdapter()
        assert adapter._month_finalized("2024-07", date(2024, 9, 14)) is False
        assert adapter._month_finalized("2024-07", date(2024, 9, 15)) is True


# ---------------------------------------------------------------------------
# 2. sync_parcel_et writes REST-shaped cache, and the row flows to the ledger
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSyncParcelEt:
    def test_writes_rest_shaped_cache_and_flows_to_ledger(self, parcel):
        adapter = GEEOpenETAdapter()
        canned = {parcel.pk: {"2024-06": 142.23}}

        with patch(INIT_EE, return_value=MagicMock()) as mock_init, patch(
            REDUCE, return_value=canned
        ):
            summary = adapter.sync_parcel_et(
                [parcel], date(2024, 6, 1), date(2024, 6, 30), today=date(2024, 7, 1)
            )
            mock_init.assert_called_once()

        assert summary["fetched"] == 1
        rows = OpenETCache.objects.filter(parcel=parcel)
        assert rows.count() == 1
        assert rows.first().et_data == [
            {"date": "2024-06", "et": 142.23, "unit": "mm"}
        ]

        # The unchanged sync_openet_to_ledger must consume that row as-is.
        call_command(
            "sync_openet_to_ledger",
            start_date="2024-06-01",
            end_date="2024-06-30",
        )
        from parcels.models import ParcelLedger

        entry = ParcelLedger.objects.get(parcel=parcel, source_type="et_estimate")
        # -(142.23 / 304.8) * 10 acres = -4.6664... AF
        expected = -(Decimal("142.23") / Decimal("304.8")) * Decimal("10.00")
        assert entry.amount_acre_feet == expected.quantize(Decimal("0.0001"))
        assert entry.effective_date == date(2024, 6, 1)

    def test_full_cache_hit_skips_earth_engine(self, parcel, sample_geometry):
        # June 2024 cached AND finalized as of today -> nothing to fetch.
        _cache_row(
            parcel, sample_geometry, [{"date": "2024-06", "et": 150.0, "unit": "mm"}]
        )
        adapter = GEEOpenETAdapter()

        with patch(INIT_EE) as mock_init, patch(REDUCE) as mock_reduce:
            summary = adapter.sync_parcel_et(
                [parcel], date(2024, 6, 1), date(2024, 6, 30), today=date(2024, 10, 1)
            )
            mock_init.assert_not_called()
            mock_reduce.assert_not_called()

        assert summary["fetched"] == 0
        assert summary["cached"] == 1
        assert summary["skipped_final"] == 1

    def test_validate_drops_garbage_month(self, parcel):
        adapter = GEEOpenETAdapter()
        # 9999mm blows past the 500mm monthly cap; 142mm is fine.
        canned = {parcel.pk: {"2024-06": 142.0, "2024-07": 9999.0}}

        with patch(INIT_EE, return_value=MagicMock()), patch(REDUCE, return_value=canned):
            summary = adapter.sync_parcel_et(
                [parcel], date(2024, 6, 1), date(2024, 7, 31), today=date(2024, 8, 1)
            )

        assert summary["fetched"] == 1
        row = OpenETCache.objects.get(parcel=parcel)
        # Only the valid month survives; the 9999mm month is rejected.
        assert row.et_data == [{"date": "2024-06", "et": 142.0, "unit": "mm"}]


# ---------------------------------------------------------------------------
# 3. get_openet_adapter() honors OPENET_MODE
# ---------------------------------------------------------------------------


class TestAdapterSelector:
    @override_settings(OPENET_MODE="gee")
    def test_gee_mode_returns_gee_adapter(self):
        assert isinstance(get_openet_adapter(), GEEOpenETAdapter)

    @override_settings(OPENET_MODE="api")
    def test_api_mode_returns_rest_adapter(self):
        adapter = get_openet_adapter()
        assert isinstance(adapter, OpenETAdapter)
        assert not isinstance(adapter, GEEOpenETAdapter)
