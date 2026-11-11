# SPDX-License-Identifier: AGPL-3.0-or-later
"""Upgrading a site records each month's crop ET and moves no number.

What a correct upgrade does (the plain write-up Brent approved, ruling 134, section 5):

* a month that was calculated is recorded at the depth its last calculation used, even
  where the cache moved after that calculation; the month then shows the newer figure;
* a month never calculated is recorded at the newest fetched figure, read the way the
  calculation reads it;
* an ET estimate entry is never the source of a record; one that differs is shown;
* the upgrade writes no ledger entry and no calculation: every balance, total, worksheet
  pre-fill and state file is the same before it, after it, and after the next calculation;
* a finalized year's months are recorded with no fetch date and the note "Recorded at
  upgrade", nothing in the year changes, and Check for changes still finds no change.

A site before the upgrade is built the way the earlier version left one: the months are
fetched and calculated, then the records are taken away (the earlier version had none).
The upgrade is called through the migration's own function.
"""

import datetime as dt
import importlib
from decimal import Decimal as D
from io import StringIO

import pytest
from django.apps import apps
from django.core.management import call_command
from django.urls import reverse

from accounting import services
from accounting.models import CalculationRun, ReportingPeriod, WaterAccount
from datasync.models import OpenETCache
from geography.models import Zone
from parcels.models import Parcel, ParcelLedger
from reporting.generators import generate_gears_csv
from reporting.services import build_openet_prefill
from tests import ledger_districts as ld
from tests.test_openet_recorded_figure import (
    _client,
    _figure_model,
    _page,
    _recorded,
    _user,
    _words,
)

pytestmark = pytest.mark.django_db

JULY = "2025-07"
MONTHS = ["2025-07", "2025-08", "2025-09"]
NOTICE_HEAD = "OpenET now reports 40.00 AF (4.80 in)"


def _upgrade():
    """The upgrade's own function; the counts it prints, as a dict."""
    try:
        module = importlib.import_module("datasync.migrations.0016_record_crop_et_at_upgrade")
    except ModuleNotFoundError:
        pytest.fail("The upgrade step that records each month's crop ET does not exist.")
    return module.record_months(apps, out=StringIO())


def _as_the_earlier_version_left_it():
    """D1 fetched and calculated for July to September, with no record (the earlier version kept none)."""
    ld.seed_reference()
    built = ld.build_d1()
    ld.run_months(MONTHS)
    model = _figure_model()
    if model is not None:
        model.objects.all().delete()
    return built


def _set_cached(parcel, month, mm):
    row = OpenETCache.objects.get(parcel=parcel, variable="ET")
    row.et_data = [
        {**item, "et": mm} if str(item["date"]).startswith(month) else item for item in row.et_data
    ]
    row.save()


@pytest.fixture
def operator():
    return _user("operator", first_name="Jose", last_name="Lopez")


# ---------------------------------------------------------------- 14. a calculated month


def test_a_calculated_month_is_recorded_at_the_depth_its_run_used_even_after_the_cache_moved(operator):
    f4 = _as_the_earlier_version_left_it()["F4"]
    _set_cached(f4, JULY, 121.92)

    counts = _upgrade()

    assert _recorded(f4) == (D("91.44"), None)
    assert counts["newer"] == 1
    assert NOTICE_HEAD in _page(operator, f4)


# ---------------------------------------------------------------- 15. a month never calculated


def test_a_month_never_calculated_is_recorded_at_the_newest_fetched_figure():
    ld.seed_reference()
    f4 = ld.build_d1()["F4"]
    model = _figure_model()
    if model is not None:
        model.objects.all().delete()
    newer = OpenETCache.objects.create(
        parcel=f4, geometry=f4.geometry, start_date=dt.date(2025, 8, 1), end_date=dt.date(2025, 8, 31),
        variable="ET", model_name="Ensemble", origin="fixture",
        et_data=[{"date": "2025-08-01", "et": 20.32}],
    )
    assert newer.queried_at > OpenETCache.objects.exclude(pk=newer.pk).get(parcel=f4).queried_at

    _upgrade()

    assert _recorded(f4, JULY) == (D("91.44"), None)
    assert _recorded(f4, "2025-08") == (D("20.32"), None)


# ---------------------------------------------------------------- 16. an entry is never the source


def test_an_entry_typed_by_hand_never_becomes_the_record_and_both_figures_are_shown(operator):
    f4 = _as_the_earlier_version_left_it()["F4"]
    ld.ledger(f4, dt.date(2025, 7, 1), -33, "et_estimate", "GW", "typed by hand before the upgrade")

    counts = _upgrade()

    assert _recorded(f4) == (D("91.44"), None)
    assert counts["entries_differ"] == 1
    sentence = "The ledger's ET estimate entry reads 33.00 AF. This month uses the recorded 30.00 AF (3.60 in)."
    assert sentence in _page(operator, f4)
    ledger_page = _words(_client(operator).get(reverse("accounting:ledger_list")))
    assert "OpenET's recorded figure for this month is 30.00 AF." in ledger_page


# ---------------------------------------------------------------- 17. no number moves


def _figures_everywhere():
    """Every figure the write-up names, as plain values."""
    figures = {}
    for source in ParcelLedger.objects.values_list("source_type", flat=True).distinct():
        rows = ParcelLedger.objects.filter(source_type=source)
        figures[f"ledger {source}"] = (
            rows.count(),
            sorted(str(v) for v in rows.values_list("amount_acre_feet", flat=True)),
        )
    figures["runs"] = sorted(
        CalculationRun.objects.values_list(
            "parcel_id", "period", "gross_et_af", "effective_precip_af", "surface_water_af",
            "gw_extracted_af", "net_consumptive_use_af",
        )
    )
    periods = list(ReportingPeriod.objects.order_by("start_date"))
    for period in [None, *periods]:
        name = period.name if period else "all"
        for parcel in Parcel.objects.order_by("pk"):
            figures[f"use area {parcel.pk} {name}"] = services.parcel_balance_breakdown(parcel, period)
        for account in WaterAccount.objects.order_by("pk"):
            figures[f"account {account.pk} {name}"] = services.account_balance(account, period)
        for zone in Zone.objects.order_by("pk"):
            figures[f"zone {zone.pk} {name}"] = services.zone_balance(zone, period)
    for period in periods:
        for method in ("by_well", "by_parcel", "calwatrs"):
            figures[f"pre-fill {period.name} {method}"] = repr(build_openet_prefill(period, method))
        for method in ("by_well", "by_et"):
            figures[f"GEARS {period.name} {method}"] = generate_gears_csv(period, method).getvalue()
    return figures


def test_the_upgrade_writes_no_ledger_entry_and_no_calculation_and_moves_no_figure():
    f4 = _as_the_earlier_version_left_it()["F4"]
    call_command(
        "sync_openet_to_ledger", "--start-date", "2025-07-01", "--end-date", "2025-09-30",
        stdout=StringIO(),
    )
    _set_cached(f4, JULY, 121.92)
    before = _figures_everywhere()

    _upgrade()
    after_upgrade = _figures_everywhere()
    ld.run_months(MONTHS)
    after_next_calculation = _figures_everywhere()

    assert _figure_model() is not None and _figure_model().objects.count() == 12
    assert after_upgrade == before
    assert after_next_calculation == before


# ---------------------------------------------------------------- 18. a finalized year


def test_a_finalized_years_months_are_recorded_and_check_for_changes_finds_none():
    from core import fingerprint

    built = _as_the_earlier_version_left_it()
    year = ReportingPeriod.objects.get(name="WY 2024-2025")
    boss = _user("boss", agency_admin=True)
    response = _client(boss).post(reverse("accounting:period_finalize", args=[year.pk]), {})
    assert response.status_code == 302
    year.refresh_from_db()
    before = _figures_everywhere()

    counts = _upgrade()

    model = _figure_model()
    rows = list(model.objects.filter(parcel=built["F4"]).order_by("month"))
    assert [(r.fetched_on, r.note) for r in rows] == [(None, "Recorded at upgrade")] * 3
    assert counts["recorded"] == 12 and counts["recorded_finalized"] == 12
    assert _figures_everywhere() == before
    assert fingerprint.compute(year).digest == year.fingerprint
