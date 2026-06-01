# SPDX-License-Identifier: AGPL-3.0-or-later
"""DB-bound tests for the subtract_effective_precip step (38-03).

The contested arithmetic is proven Django-free in tests/test_precip_math.py; this
file proves the thin cache-reading wrapper: that it reads precip + ET with the
RIGHT strings/keys (the silent-zero guard), converts mm<->in<->AF correctly,
subtracts from the running total, passes through when there is no rain, and
switches behavior with method. Runs in the Butler web container (needs the DB).
"""
import datetime as dt
from decimal import Decimal

import pytest
from django.contrib.gis.geos import MultiPolygon, Polygon

from accounting.services import et_mm_to_acre_feet
from accounting.steps import STEP_REGISTRY, subtract_effective_precip
from parcels.models import Parcel


def _square(x=0.0):
    poly = Polygon(
        ((x, x), (x, x + 0.01), (x + 0.01, x + 0.01), (x + 0.01, x), (x, x))
    )
    return MultiPolygon(poly, srid=4326)


def _parcel(number, acres="10"):
    return Parcel.objects.create(parcel_number=number, area_acres=Decimal(acres))


def _et_cache(parcel, period="2024-02", et_mm=120.0):
    from datasync.models import OpenETCache

    year, month = int(period[:4]), int(period[5:7])
    return OpenETCache.objects.create(
        parcel=parcel,
        geometry=_square(),
        start_date=dt.date(year, month, 1),
        end_date=dt.date(year, month, 28),
        variable="ET",
        model_name="Ensemble",
        et_data=[{"et": et_mm, "date": period, "unit": "mm"}],
    )


def _precip_cache(parcel, period="2024-02", precip_mm=150.0):
    """A precip cache row in the live 38-01 shape: variable=precip/model=GRIDMET,
    value keyed "precip" (NOT "et"/"value")."""
    from datasync.models import OpenETCache

    year, month = int(period[:4]), int(period[5:7])
    return OpenETCache.objects.create(
        parcel=parcel,
        geometry=_square(),
        start_date=dt.date(year, month, 1),
        end_date=dt.date(year, month, 28),
        variable="precip",
        model_name="GRIDMET",
        et_data=[{"precip": precip_mm, "date": period, "unit": "mm"}],
    )


def test_registry_now_includes_effective_precip():
    assert "subtract_effective_precip" in STEP_REGISTRY
    assert STEP_REGISTRY["subtract_effective_precip"] is subtract_effective_precip


@pytest.mark.django_db
def test_raw_method_subtracts_all_rainfall_as_af():
    parcel = _parcel("PRECIP-RAW", acres="10")
    _et_cache(parcel, period="2024-02", et_mm=120.0)
    _precip_cache(parcel, period="2024-02", precip_mm=100.0)

    gross = Decimal("5")
    new, record = subtract_effective_precip(
        gross, parcel, "2024-02", {}, {"method": "raw"}
    )
    # raw Pe = all rainfall: 100 mm over 10 ac -> ~3.28 AF subtracted.
    expected_pe_af = abs(et_mm_to_acre_feet(Decimal("100"), Decimal("10")))
    assert abs(Decimal(record["detail"]["effective_precip_af"]) - expected_pe_af) < Decimal("0.01")
    assert new < gross
    assert record["step_type"] == "subtract_effective_precip"


@pytest.mark.django_db
def test_usda_scs_reduces_billable_when_wet():
    parcel = _parcel("PRECIP-WET", acres="10")
    _et_cache(parcel, period="2024-02", et_mm=120.0)   # ~4.7 in
    _precip_cache(parcel, period="2024-02", precip_mm=150.0)  # ~5.9 in (clearly wet)

    gross = Decimal("4")
    new, record = subtract_effective_precip(
        gross, parcel, "2024-02", {}, {"method": "usda_scs", "soil_storage_in": 3.0}
    )
    pe_af = Decimal(record["detail"]["effective_precip_af"])
    assert pe_af > 0                       # a wet month credits something
    assert new < gross                     # netting reduced billable GW
    # usda_scs caps Pe at min(P, ET): Pe(mm) never exceeds rainfall.
    assert Decimal(record["detail"]["effective_precip_mm"]) <= Decimal("150.0")


@pytest.mark.django_db
def test_no_precip_row_passes_running_through_unchanged():
    parcel = _parcel("PRECIP-DRY", acres="10")
    _et_cache(parcel, period="2024-06", et_mm=170.0)   # ET present, NO precip row

    gross = Decimal("7")
    new, record = subtract_effective_precip(
        gross, parcel, "2024-06", {}, {"method": "usda_scs", "soil_storage_in": 3.0}
    )
    assert new == gross
    assert Decimal(record["detail"]["effective_precip_af"]) == 0
    assert Decimal(record["detail"]["precip_mm"]) == 0


@pytest.mark.django_db
def test_method_switch_changes_the_result():
    parcel = _parcel("PRECIP-SWITCH", acres="10")
    _et_cache(parcel, period="2024-02", et_mm=120.0)
    _precip_cache(parcel, period="2024-02", precip_mm=150.0)
    gross = Decimal("4")

    def pe_af(config):
        _, rec = subtract_effective_precip(gross, parcel, "2024-02", {}, config)
        return Decimal(rec["detail"]["effective_precip_af"])

    raw = pe_af({"method": "raw"})
    frac = pe_af({"method": "fraction", "fraction": 0.5})
    scs = pe_af({"method": "usda_scs", "soil_storage_in": 3.0})

    assert raw > frac          # raw subtracts all rainfall; fraction only half
    assert len({raw, frac, scs}) == 3  # all three methods give distinct credits


@pytest.mark.django_db
def test_detail_dict_carries_the_audit_keys():
    parcel = _parcel("PRECIP-DETAIL", acres="10")
    _et_cache(parcel, period="2024-02", et_mm=120.0)
    _precip_cache(parcel, period="2024-02", precip_mm=150.0)

    _, record = subtract_effective_precip(
        Decimal("4"), parcel, "2024-02", {}, {"method": "usda_scs", "soil_storage_in": 3.0}
    )
    assert set(record["detail"]) == {
        "method",
        "precip_mm",
        "et_mm",
        "effective_precip_mm",
        "effective_precip_af",
    }
    assert record["detail"]["method"] == "usda_scs"
    assert record["detail"]["precip_mm"] == "150.0"
    assert record["detail"]["et_mm"] == "120.0"
