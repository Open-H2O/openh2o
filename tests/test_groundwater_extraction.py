# SPDX-License-Identifier: AGPL-3.0-or-later
"""148-02 Task 4 (Q2): groundwater consumed and groundwater extracted.

An estimated field's calculated row keeps the CONSUMED magnitude (what the
crop actually used); the run also stamps an EXTRACTED figure (what the pump
had to lift to deliver it) and a DEEP PERCOLATION figure (the difference),
both read off `SiteConfig.groundwater_efficiency` once, at compute time. A
metered field never divides -- the meter is the number.

**The budget spends extraction, not consumption** (the main session's
decision, deviating from the plan's "amount / groundwater_efficiency"
wording on purpose): a `calculated` row's charged magnitude is the run's
STAMPED `gw_extracted_af`, never the ledger amount re-divided by whatever the
setting holds NOW -- a finalized period's billable groundwater must not move
because someone tuned a setting afterwards (ISS-177). An old run with no
stamped extraction (predates 148-02 Task 4) falls back to its recorded
amount, unchanged from today's behaviour.

These tests cover the pieces `tests/test_zone_budget_shared.py`,
`tests/test_mass_balance.py`, `tests/test_consumptive_use_balance.py`,
`tests/test_calculation_run.py` and `tests/test_delivery_settings_surface_fields.py`
already prove correct in every OTHER dimension: the extraction split itself,
the charged-vs-consumed divergence, the setting-change lock, the Groundwater
Delivery Settings gate, and the change-history module mapping.
"""
import datetime as dt
from decimal import Decimal

import factory
import pytest
from django.contrib.auth.hashers import make_password
from django.core.management import call_command
from django.test import Client, override_settings
from django.urls import reverse

from accounting.management.commands.run_calculations import _groundwater_extraction
from accounting.models import CalculationRun
from accounting.services import (
    charged_groundwater,
    parcel_mass_balance,
    zone_groundwater_budget,
)
from core.models import SiteConfig
from core.modules import ALL_MODULE_NAMES
from parcels.models import CropType, ParcelLedger, UsageLocation
from tests.factories import (
    AllocationPlanFactory,
    ParcelFactory,
    ParcelLedgerFactory,
    ParcelZoneFactory,
    ReportingPeriodFactory,
    WellIrrigatedParcelFactory,
    ZoneFactory,
)

pytestmark = pytest.mark.django_db

Q = Decimal("0.0001")

#: `wells` has no dependents (core/modules.py: nothing lists it in `requires`),
#: so dropping it alone -- unlike `surface`, which `recharge` needs -- is a
#: valid configuration.
_WITHOUT_WELLS = tuple(n for n in ALL_MODULE_NAMES if n != "wells")


# ---------------------------------------------------------------------------
# 1. The pure split: _groundwater_extraction (run_calculations.py)
# ---------------------------------------------------------------------------


def test_the_extraction_split_divides_by_efficiency():
    """0.88 consumed / 0.80 = 1.10 extracted, 0.22 deep percolation -- the
    plan's own worked example."""
    extracted, deep_percolation = _groundwater_extraction(
        Decimal("0.8800"), Decimal("0.800")
    )
    assert extracted == Decimal("1.1000")
    assert deep_percolation == Decimal("0.2200")


def test_a_zero_month_divides_to_zero_and_zero():
    extracted, deep_percolation = _groundwater_extraction(
        Decimal("0.0000"), Decimal("0.800")
    )
    assert extracted == Decimal("0.0000")
    assert deep_percolation == Decimal("0.0000")


# ---------------------------------------------------------------------------
# 2. The real engine: run_calculations stamps the split on the run
# ---------------------------------------------------------------------------


def _square(x=0.0):
    from django.contrib.gis.geos import MultiPolygon, Polygon

    poly = Polygon(
        ((x, x), (x, x + 0.01), (x + 0.01, x + 0.01), (x + 0.01, x), (x, x))
    )
    return MultiPolygon(poly, srid=4326)


def _et_only_parcel(number, period, et_mm, acres="10"):
    """A has-well, ET-only field: no precip cache, no surface delivery, so the
    chain's residual equals the gross-ET magnitude exactly -- the same shape
    `tests/test_calculation_run.py::_seed_finalized_parcel` uses, without the
    finalized period. `et_mm` is chosen so the residual quantizes to a clean
    literal (26.8224 mm over 10 acres = 0.8800 AF, exactly)."""
    from datasync.models import OpenETCache
    from parcels.models import Parcel

    parcel = Parcel.objects.create(parcel_number=number, area_acres=Decimal(acres))
    crop = CropType.objects.create(name=f"Crop-{number}")
    UsageLocation.objects.create(parcel=parcel, name="field", crop_type=crop)
    WellIrrigatedParcelFactory(parcel=parcel)

    year, month = int(period[:4]), int(period[5:7])
    OpenETCache.objects.create(
        parcel=parcel,
        geometry=_square(),
        start_date=dt.date(year, month, 1),
        end_date=dt.date(year, month, 28),
        variable="ET",
        model_name="Ensemble",
        et_data=[{"et": et_mm, "date": period, "unit": "mm"}],
    )
    return parcel


def test_estimated_field_month_stamps_consumed_extracted_and_deep_percolation():
    """The plan's worked example, run through the real engine: a field whose
    gross ET nets to 0.8800 AF consumed stamps 1.1000 AF extracted and 0.2200
    AF deep percolation at the model default 0.800 efficiency."""
    period = "2025-05"
    parcel = _et_only_parcel("GWX-ESTIMATED", period, et_mm="26.8224")
    call_command("seed_calculation_plan")

    call_command("run_calculations", "--period", period)

    run = CalculationRun.objects.get(parcel=parcel, period=period)
    assert run.residual_disposition == "groundwater"
    assert run.final_af == Decimal("0.8800")
    assert run.gw_extracted_af == Decimal("1.1000")
    assert run.deep_percolation_gw_af == Decimal("0.2200")

    row = ParcelLedger.objects.get(
        parcel=parcel, effective_date=dt.date(2025, 5, 1), source_type="calculated"
    )
    # The ledger row keeps the CONSUMED amount, stored negative (usage) --
    # unchanged by this task.
    assert row.amount_acre_feet == Decimal("-0.8800")


def test_metered_field_has_no_extraction_estimate():
    """A metered run's meter IS the number -- both new columns stay null."""
    period = "2025-05"
    parcel = _et_only_parcel("GWX-METERED", period, et_mm="26.8224")
    ParcelLedger.objects.create(
        parcel=parcel,
        transaction_date=dt.date(2025, 5, 1),
        effective_date=dt.date(2025, 5, 15),
        amount_acre_feet=Decimal("-0.5000"),
        source_type="meter_reading",
    )
    call_command("seed_calculation_plan")

    call_command("run_calculations", "--period", period)

    run = CalculationRun.objects.get(parcel=parcel, period=period)
    assert run.residual_disposition == "metered"
    assert run.gw_extracted_af is None
    assert run.deep_percolation_gw_af is None


def test_no_well_field_has_no_extraction_estimate():
    """A no-well run has no pump to have extracted anything -- both columns
    stay null on the unmet-demand disposition too."""
    period = "2025-05"
    from datasync.models import OpenETCache
    from parcels.models import Parcel

    parcel = Parcel.objects.create(parcel_number="GWX-NOWELL", area_acres=Decimal("10"))
    crop = CropType.objects.create(name="Crop-GWX-NOWELL")
    UsageLocation.objects.create(parcel=parcel, name="field", crop_type=crop)
    OpenETCache.objects.create(
        parcel=parcel,
        geometry=_square(),
        start_date=dt.date(2025, 5, 1),
        end_date=dt.date(2025, 5, 28),
        variable="ET",
        model_name="Ensemble",
        et_data=[{"et": "26.8224", "date": period, "unit": "mm"}],
    )
    call_command("seed_calculation_plan")

    call_command("run_calculations", "--period", period)

    run = CalculationRun.objects.get(parcel=parcel, period=period)
    assert run.residual_disposition == "unmet_demand"
    assert run.gw_extracted_af is None
    assert run.deep_percolation_gw_af is None


# ---------------------------------------------------------------------------
# 3. The budget spends extraction; the setting is read once, at compute time
# ---------------------------------------------------------------------------


def test_a_setting_change_after_a_run_does_not_move_the_charged_figure():
    """ISS-177: a finalized period's billable groundwater must not move when
    someone tunes the setting. Change the setting AFTER the run and read the
    charged figure again without recomputing -- it stays at the run's
    stamped 1.1000 AF, not a re-division by the new 0.500."""
    period = "2025-05"
    parcel = _et_only_parcel("GWX-SETTING", period, et_mm="26.8224")
    call_command("seed_calculation_plan")
    call_command("run_calculations", "--period", period)

    run = CalculationRun.objects.get(parcel=parcel, period=period)
    assert run.gw_extracted_af == Decimal("1.1000")

    config, _ = SiteConfig.objects.get_or_create(defaults={"agency_name": "Agency"})
    SiteConfig.objects.filter(pk=config.pk).update(
        groundwater_efficiency=Decimal("0.500")
    )

    qs = ParcelLedger.objects.filter(parcel=parcel, source_type="calculated")
    assert charged_groundwater(qs) == Decimal("1.1000")

    # Recomputing the run DOES pick up the new setting -- the setting moves
    # a figure only when a run actually reads it. run_calculations
    # delete-then-inserts the run (a fresh PK), so re-fetch rather than
    # refresh_from_db() the old instance.
    call_command("run_calculations", "--period", period)
    run = CalculationRun.objects.get(parcel=parcel, period=period)
    assert run.gw_extracted_af == Decimal("1.7600")  # 0.8800 / 0.500


def test_an_old_run_with_no_stamped_extraction_is_charged_as_recorded():
    """A `calculated` row whose run predates 148-02 Task 4 (gw_extracted_af
    null) falls back to its recorded amount -- today's behaviour, unchanged."""
    period = "2025-05"
    parcel = _et_only_parcel("GWX-OLDRUN", period, et_mm="26.8224")
    call_command("seed_calculation_plan")
    call_command("run_calculations", "--period", period)

    # Simulate a run an engine before 148-02 Task 4 wrote: no extraction
    # estimate stamped, ever.
    CalculationRun.objects.filter(parcel=parcel, period=period).update(
        gw_extracted_af=None, deep_percolation_gw_af=None
    )

    qs = ParcelLedger.objects.filter(parcel=parcel, source_type="calculated")
    assert charged_groundwater(qs) == Decimal("0.8800")  # the recorded amount


def test_meter_reading_is_always_charged_as_recorded():
    """A meter row never divides, extraction estimate or not."""
    parcel = ParcelFactory()
    ParcelLedgerFactory(
        parcel=parcel,
        effective_date=dt.date(2025, 5, 15),
        source_type="meter_reading",
        amount_acre_feet=Decimal("-12.3400"),
    )
    qs = ParcelLedger.objects.filter(parcel=parcel)
    assert charged_groundwater(qs) == Decimal("12.3400")


# ---------------------------------------------------------------------------
# 4. zone_groundwater_budget: the budget's remaining moves by the division
# ---------------------------------------------------------------------------


def test_zone_groundwater_budget_remaining_moves_by_the_extraction():
    """A zone with one estimated field: allocation 500, the field's run
    stamped 1.1000 AF extracted from 0.8800 AF consumed. Before this task
    the budget would have spent 0.8800 (remaining 499.1200); it now spends
    1.1000 (remaining 498.9000) -- the division moved the remaining figure."""
    period = "2025-05"
    # The ReportingPeriod must exist BEFORE the run: run_calculations
    # resolves and stamps it onto the calculated ledger row at write time
    # (`eff_date` inside the period's span), and `zone_groundwater_budget`
    # below scopes its read to this same period.
    rp = ReportingPeriodFactory(
        name="WY-GWX", start_date=dt.date(2025, 5, 1), end_date=dt.date(2025, 5, 31)
    )
    parcel = _et_only_parcel("GWX-ZONEBUDGET", period, et_mm="26.8224")
    call_command("seed_calculation_plan")
    call_command("run_calculations", "--period", period)

    # run_calculations already created the GW WaterType (get_or_create,
    # ISS-052) resolving the over-delivery ledger rows -- reuse it rather
    # than colliding with its unique `name`.
    from accounting.models import WaterType

    gw_type, _ = WaterType.objects.get_or_create(
        code="GW", defaults={"name": "Groundwater"}
    )
    zone = ZoneFactory(name="GWX Zone")
    ParcelZoneFactory(parcel=parcel, zone=zone)
    AllocationPlanFactory(
        zone=zone,
        water_type=gw_type,
        reporting_period=rp,
        allocation_acre_feet=Decimal("500.0000"),
    )

    budget = zone_groundwater_budget(zone, rp)

    assert budget["used"] == Decimal("1.1000")
    assert budget["remaining"] == Decimal("498.9000")


# ---------------------------------------------------------------------------
# 5. The residual_disposition choice label
# ---------------------------------------------------------------------------


def test_the_groundwater_disposition_label_says_consumed_estimated():
    run = CalculationRun(residual_disposition="groundwater")
    assert run.get_residual_disposition_display() == "Groundwater consumed (estimated)"


# ---------------------------------------------------------------------------
# 6. Delivery Settings: the Groundwater card is gated on `wells`
# ---------------------------------------------------------------------------


class _StaffUserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"gwxadmin{n}")
    email = factory.Sequence(lambda n: f"gwxadmin{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True
    is_staff = True


@pytest.fixture
def admin_client():
    c = Client()
    c.force_login(_StaffUserFactory())
    return c


def test_groundwater_efficiency_shown_when_wells_is_enabled(admin_client):
    resp = admin_client.get(reverse("accounting:delivery_settings"))
    body = resp.content.decode()
    assert resp.status_code == 200
    assert "Groundwater" in body
    assert "Share of pumped groundwater the crop consumes" in body


@override_settings(OPENH2O_MODULES=_WITHOUT_WELLS)
def test_groundwater_efficiency_absent_when_wells_is_disabled(admin_client):
    resp = admin_client.get(reverse("accounting:delivery_settings"))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Share of pumped groundwater the crop consumes" not in body
    assert 'name="groundwater_efficiency_percent"' not in body


def test_saving_with_wells_disabled_leaves_groundwater_efficiency_untouched(admin_client):
    config, _ = SiteConfig.objects.get_or_create(defaults={"agency_name": "Agency"})
    assert config.groundwater_efficiency == Decimal("0.800")  # the model default

    with override_settings(OPENH2O_MODULES=_WITHOUT_WELLS):
        # `_WITHOUT_WELLS` leaves `surface` on, so efficiency_percent is
        # still a required field on this POST -- only groundwater_efficiency_percent
        # is the one nobody was offered.
        resp = admin_client.post(
            reverse("accounting:delivery_settings"),
            {
                "recovery_horizon": "same_water_year",
                "efficiency_percent": "75",
                "diversion_report_year_rule": "water_year",
            },
        )
    assert resp.status_code == 302
    config.refresh_from_db()
    assert config.groundwater_efficiency == Decimal("0.800")


# ---------------------------------------------------------------------------
# 7. The change record maps the field to `wells`
# ---------------------------------------------------------------------------


def test_change_history_maps_groundwater_efficiency_to_wells():
    from core.changes import FIELD_MODULES

    assert FIELD_MODULES["core.SiteConfig.groundwater_efficiency"] == "wells"


@override_settings(OPENH2O_MODULES=_WITHOUT_WELLS)
def test_change_history_drops_groundwater_efficiency_when_wells_is_off():
    from core.changes import tracked_fields
    from core.models import SiteConfigEvent

    names = [f.name for f in tracked_fields(SiteConfigEvent)]
    assert "groundwater_efficiency" not in names


def test_change_history_shows_groundwater_efficiency_when_wells_is_on():
    from core.changes import tracked_fields
    from core.models import SiteConfigEvent

    names = [f.name for f in tracked_fields(SiteConfigEvent)]
    assert "groundwater_efficiency" in names


# ---------------------------------------------------------------------------
# 8. Mass-balance closure on an estimated field-year, deep_percolation_gw_af
#    included
# ---------------------------------------------------------------------------


def test_estimated_field_month_closes_with_deep_percolation_gw_af():
    """`gw_recovered` now reads the EXTRACTED figure (1.1000), so the balance
    only closes once `deep_percolation_gw_af` (0.2200) is counted as an
    output -- physically: pumped water in, the crop's share to ET, the rest
    back to the aquifer."""
    period = "2025-05"
    parcel = _et_only_parcel("GWX-CLOSURE", period, et_mm="26.8224")
    call_command("seed_calculation_plan")
    call_command("run_calculations", "--period", period)

    result = parcel_mass_balance(parcel, reporting_period=None)

    assert result["inputs"]["gw_recovered"] == Decimal("1.1000")
    assert result["outputs"]["deep_percolation_gw_af"] == Decimal("0.2200")
    assert abs(result["residual_af"]) <= Decimal("0.01")
    assert result["closes"] is True
