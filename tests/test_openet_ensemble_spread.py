# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Tests for OpenET ensemble-spread collection and the confidence signal.

Three concerns:

1. The variable-leak regression. OpenETCache is a multi-variable table, and the
   ET read paths used to match on parcel + window only. A fresher non-ET row
   for the same window therefore read as an ET cache hit and suppressed the ET
   fetch entirely.
2. Spread fetch/parse. One variable per API call, each stored in its own row,
   values keyed by variable name.
3. The confidence bands, including the cases where a bound or a count is
   MISSING — absent must never render as a confident zero-width range.
"""

from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.gis.geos import MultiPolygon, Polygon
from django.utils import timezone

from accounting.confidence import EnsembleConfidence, parcel_ensemble_confidence
from datasync.adapters.openet import SPREAD_VARIABLES, OpenETAdapter
from datasync.models import OpenETCache


@pytest.fixture
def sample_geometry():
    return MultiPolygon(Polygon.from_bbox((-119.3, 36.3, -119.2, 36.4)), srid=4326)


@pytest.fixture
def parcel(sample_geometry):
    from parcels.models import Parcel

    return Parcel.objects.create(
        parcel_number="SPREAD-001",
        geometry=sample_geometry,
        status="active",
        area_acres=100,
    )


@pytest.fixture
def auth_client(db):
    """Logged-in client. Mirrors the fixture in test_57_03_presentation — the
    audit page is login-gated, so an anonymous client only ever sees a redirect."""
    from django.contrib.auth import get_user_model
    from django.test import Client

    user = get_user_model().objects.create_user(
        username="spread-tester", password="x"
    )
    client = Client()
    client.force_login(user)
    return client


def _row(parcel, geometry, variable, key, value, model_name="Ensemble"):
    return OpenETCache.objects.create(
        parcel=parcel,
        geometry=geometry,
        start_date=date(2025, 1, 1),
        end_date=date(2025, 12, 31),
        variable=variable,
        model_name=model_name,
        et_data=[{"date": "2025-01", key: value, "unit": "mm"}],
    )


@pytest.mark.django_db
class TestVariableLeakRegression:
    """A non-ET row must never satisfy an ET cache lookup."""

    def test_fresh_precip_row_does_not_suppress_et_fetch(self, parcel, sample_geometry):
        # Precip for the same parcel and window, written more recently than any
        # ET row. Before the variable filter this was the newest row for the
        # window, so sync_with_cache returned it and never fetched ET.
        _row(parcel, sample_geometry, "precip", "precip", 12.0, model_name="GRIDMET")

        adapter = OpenETAdapter()
        with patch.object(adapter, "fetch_polygon") as fetch:
            fetch.return_value = [{"time": "2025-01", "et": 88.0}]
            result = adapter.sync_with_cache(parcel, date(2025, 1, 1), date(2025, 12, 31))

        assert fetch.called, "precip row was read as an ET cache hit"
        assert result[0]["et"] == 88.0

    def test_fresh_spread_row_does_not_suppress_et_fetch(self, parcel, sample_geometry):
        _row(parcel, sample_geometry, "et_mad_min", "et_mad_min", 70.0)

        adapter = OpenETAdapter()
        with patch.object(adapter, "fetch_polygon") as fetch:
            fetch.return_value = [{"time": "2025-01", "et": 88.0}]
            adapter.sync_with_cache(parcel, date(2025, 1, 1), date(2025, 12, 31))

        assert fetch.called, "et_mad_min row was read as an ET cache hit"

    def test_genuine_et_row_still_hits_cache(self, parcel, sample_geometry):
        _row(parcel, sample_geometry, "ET", "et", 42.5)

        adapter = OpenETAdapter()
        with patch.object(adapter, "fetch_polygon") as fetch:
            result = adapter.sync_with_cache(parcel, date(2025, 1, 1), date(2025, 12, 31))

        assert not fetch.called, "fresh ET row should have served the request"
        assert result[0]["et"] == 42.5

    def test_ledger_sync_ignores_non_et_rows(self, parcel, sample_geometry):
        """sync_openet_to_ledger files what it reads as et_estimate.

        The row here is deliberately hostile: variable="et_mad_max" but the
        payload keyed under "et", which is what any future writer reusing
        build_et_data would produce. That defeats the `et_value is None`
        fall-through that spared non-ET rows before, so this test fails unless
        the QUERYSET itself scopes to variable="ET".
        """
        from django.core.management import call_command

        _row(parcel, sample_geometry, "et_mad_max", "et", 999.0)

        call_command(
            "sync_openet_to_ledger",
            "--start", "2025-01-01",
            "--end", "2025-12-31",
        )

        from parcels.models import ParcelLedger

        assert not ParcelLedger.objects.filter(
            parcel=parcel, source_type="et_estimate"
        ).exists(), "a spread bound was filed as consumptive use"


@pytest.mark.django_db
class TestSpreadFetch:
    def test_parse_reads_the_requested_variable(self):
        adapter = OpenETAdapter()
        raw = [{"time": "2025-01", "et_mad_min": 61.0}]

        records = adapter.parse(raw, variable="et_mad_min")

        assert records[0]["value"] == 61.0
        assert records[0]["parameter_code"] == "et_mad_min"

    def test_parse_does_not_fall_back_to_et_for_a_spread_variable(self):
        """A bound that silently reads the ET column renders as a zero-width
        range — a claim of perfect precision. Better to return nothing."""
        adapter = OpenETAdapter()
        raw = [{"time": "2025-01", "et": 88.0}]

        records = adapter.parse(raw, variable="et_mad_min")

        assert records[0]["value"] is None

    def test_fetch_polygon_sends_the_requested_variable(self, parcel):
        adapter = OpenETAdapter()
        with patch.object(adapter, "_request") as request:
            request.return_value = MagicMock(json=lambda: [])
            adapter.fetch_polygon(
                parcel.geometry, date(2025, 1, 1), date(2025, 12, 31),
                variable="model_count",
            )

        payload = request.call_args.kwargs["json"]
        assert payload["variable"] == "model_count"
        assert payload["model"] == "Ensemble"

    def test_spread_variable_writes_its_own_row(self, parcel):
        adapter = OpenETAdapter()
        with patch.object(adapter, "fetch_polygon") as fetch:
            fetch.return_value = [{"time": "2025-01", "et_mad_max": 104.0}]
            adapter.sync_spread_variable(
                parcel, date(2025, 1, 1), date(2025, 12, 31), "et_mad_max"
            )

        row = OpenETCache.objects.get(parcel=parcel, variable="et_mad_max")
        assert row.et_data[0]["et_mad_max"] == 104.0
        assert row.model_name == "Ensemble"

    def test_model_count_is_stored_unitless(self, parcel):
        adapter = OpenETAdapter()
        with patch.object(adapter, "fetch_polygon") as fetch:
            fetch.return_value = [{"time": "2025-01", "model_count": 5}]
            adapter.sync_spread_variable(
                parcel, date(2025, 1, 1), date(2025, 12, 31), "model_count"
            )

        row = OpenETCache.objects.get(parcel=parcel, variable="model_count")
        assert row.et_data[0]["unit"] == "count"
        assert row.et_data[0]["model_count"] == 5

    def test_rejects_a_non_spread_variable(self, parcel):
        adapter = OpenETAdapter()
        with pytest.raises(ValueError):
            adapter.sync_spread_variable(
                parcel, date(2025, 1, 1), date(2025, 12, 31), "ET"
            )

    def test_failed_fetch_releases_the_budget_slot(self, parcel):
        adapter = OpenETAdapter()
        before = OpenETCache.objects.count()

        with patch.object(adapter, "fetch_polygon", side_effect=RuntimeError("boom")):
            result = adapter.sync_spread_variable(
                parcel, date(2025, 1, 1), date(2025, 12, 31), "et_mad_min"
            )

        assert result is None
        assert OpenETCache.objects.count() == before, "reservation row leaked"

    def test_budget_exhaustion_returns_none(self, parcel, settings):
        settings.OPENET_MONTHLY_BUDGET = 0
        adapter = OpenETAdapter()

        result = adapter.sync_spread_variable(
            parcel, date(2025, 1, 1), date(2025, 12, 31), "et_mad_min"
        )

        assert result is None

    def test_sync_spread_covers_every_variable(self, parcel):
        adapter = OpenETAdapter()

        def fake_fetch(geometry, start, end, variable="ET"):
            return [{"time": "2025-01", variable: 1.0}]

        with patch.object(adapter, "fetch_polygon", side_effect=fake_fetch):
            with patch.object(adapter, "_rate_limit"):
                results = adapter.sync_spread(
                    parcel, date(2025, 1, 1), date(2025, 12, 31)
                )

        assert set(results) == set(SPREAD_VARIABLES)
        for variable in SPREAD_VARIABLES:
            assert OpenETCache.objects.filter(parcel=parcel, variable=variable).exists()


class TestConfidenceBands:
    """Pure band logic — no database needed."""

    @pytest.mark.parametrize(
        "count,level",
        [(6, "high"), (5, "moderate"), (4, "guarded"), (3, "low"), (1, "low")],
    )
    def test_levels(self, count, level):
        assert EnsembleConfidence(model_count=count).level == level

    def test_token_is_always_text(self):
        assert EnsembleConfidence(model_count=4).token == "4/6"

    def test_missing_count_is_unknown_not_zero(self):
        """Absent and zero are different facts. A missing count must not render
        as "0/6", which would read as total model disagreement."""
        confidence = EnsembleConfidence(model_count=None)

        assert confidence.level == "unknown"
        assert confidence.token == "—"
        assert not confidence.has_agreement

    def test_range_requires_both_bounds(self):
        assert not EnsembleConfidence(low_mm=70.0, high_mm=None).has_range
        assert not EnsembleConfidence(low_mm=None, high_mm=104.0).has_range
        assert EnsembleConfidence(low_mm=70.0, high_mm=104.0).has_range

    def test_zero_width_range_is_not_a_range(self):
        """Equal bounds would render as a point estimate with implied perfect
        precision. Suppress it rather than overstate certainty."""
        assert not EnsembleConfidence(low_mm=88.0, high_mm=88.0).has_range


@pytest.mark.django_db
class TestConfidenceFromCache:
    def test_assembles_all_four_components(self, parcel, sample_geometry):
        _row(parcel, sample_geometry, "ET", "et", 88.0)
        _row(parcel, sample_geometry, "et_mad_min", "et_mad_min", 70.0)
        _row(parcel, sample_geometry, "et_mad_max", "et_mad_max", 104.0)
        _row(parcel, sample_geometry, "model_count", "model_count", 5)

        confidence = parcel_ensemble_confidence(parcel, "2025-01")

        assert float(confidence.value_mm) == 88.0
        assert float(confidence.low_mm) == 70.0
        assert float(confidence.high_mm) == 104.0
        assert confidence.model_count == 5
        assert confidence.level == "moderate"
        assert confidence.token == "5/6"

    def test_et_without_spread_reports_unknown_not_certain(self, parcel, sample_geometry):
        """The pre-existing state of every parcel: ET fetched, spread never
        collected. That must read as "unknown", never as a tight range."""
        _row(parcel, sample_geometry, "ET", "et", 88.0)

        confidence = parcel_ensemble_confidence(parcel, "2025-01")

        assert float(confidence.value_mm) == 88.0
        assert not confidence.has_range
        assert confidence.level == "unknown"

    def test_missing_bound_does_not_become_zero(self, parcel, sample_geometry):
        """_read_cache_mm returns Decimal("0") on a miss, which is a real value
        for ET and a lie for a bound. A 0 low bound would render a range that
        starts at zero millimetres of water."""
        _row(parcel, sample_geometry, "ET", "et", 88.0)
        _row(parcel, sample_geometry, "et_mad_max", "et_mad_max", 104.0)

        confidence = parcel_ensemble_confidence(parcel, "2025-01")

        assert confidence.low_mm is None
        assert not confidence.has_range


@pytest.mark.django_db
class TestConfidenceRendering:
    """The audit page must state its own uncertainty, and state it in text."""

    def _run_for(self, parcel, period="2025-01"):
        from accounting.models import CalculationRun

        from decimal import Decimal

        return CalculationRun.objects.create(
            parcel=parcel,
            period=period,
            gross_et_af=Decimal("10"),
            net_consumptive_use_af=Decimal("8"),
            effective_precip_af=Decimal("1"),
            surface_water_af=Decimal("0"),
            banked_af=Decimal("0"),
            drawn_af=Decimal("0"),
            # final_af is NOT NULL with no default — a hand-built run must set it.
            final_af=Decimal("8"),
            breakdown=[],
        )

    def test_renders_agreement_token_as_text(
        self, auth_client, parcel, sample_geometry
    ):
        from django.urls import reverse

        self._run_for(parcel)
        _row(parcel, sample_geometry, "ET", "et", 88.0)
        _row(parcel, sample_geometry, "et_mad_min", "et_mad_min", 70.0)
        _row(parcel, sample_geometry, "et_mad_max", "et_mad_max", 104.0)
        _row(parcel, sample_geometry, "model_count", "model_count", 4)

        url = reverse("accounting:calculation_run_detail", args=[parcel.pk, "2025-01"])
        body = auth_client.get(url).content.decode()

        # The count is TEXT, not colour alone — this is the WCAG 1.4.1 contract
        # and the reason the badge survives a greyscale print of a filing.
        assert "4/6" in body
        assert "Notable disagreement" in body
        assert "badge-agreement-guarded" in body
        assert "70&ndash;104 mm" in body or "70–104 mm" in body

    def test_missing_spread_renders_honest_unknown(
        self, auth_client, parcel, sample_geometry
    ):
        """Every parcel is in this state until spread is collected. It must say
        so rather than implying a tight, confident estimate."""
        from django.urls import reverse

        self._run_for(parcel)
        _row(parcel, sample_geometry, "ET", "et", 88.0)

        url = reverse("accounting:calculation_run_detail", args=[parcel.pk, "2025-01"])
        body = auth_client.get(url).content.decode()

        assert "badge-agreement-unknown" in body
        assert "Not yet collected" in body
        assert "mm" not in body.split("Satellite model agreement")[1][:400]
