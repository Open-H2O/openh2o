# SPDX-License-Identifier: AGPL-3.0-or-later
"""150-02 Task 3: the field page carries what the calculation run stores.

The use-area page gains a "Month by month" card (one row per calculation run
in the period, each figure the run's own stored column, or on a metered month
the month's meter readings), three rows in the water balance panel (the canal
water the crop could use under Surface; deep percolation from canal water and
from groundwater under Deep percolation), and a band beside a delivered or
metered figure where every record summed into it states an accuracy
(``accounting/bands.py``).

Every expected figure is a literal worked by hand from the fixture, once
(DESIGN.md rule 12, review question 2): 107.8607 delivered less 80.8955 the
crop could use is 26.9652, printed 26.97; 12.4435 extracted plus the July
meter's 94.9987 is 107.4422, printed 107.44; a 100.0000 AF record at 5% is
5.0000, and a 0.3 share of it is 1.5000, printed 1.50.

Parcel numbers are fictional. Runs in the web container (needs the DB).
"""
import datetime as dt
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from accounting.models import CalculationRun
from surface.models import MeasuringDevice
from tests.factories import (
    DiversionRecordFactory,
    ParcelFactory,
    ParcelLedgerFactory,
    PointOfDiversionFactory,
    ReportingPeriodFactory,
    WellFactory,
    WellIrrigatedParcelFactory,
)

User = get_user_model()

pytestmark = pytest.mark.django_db


def _client():
    name = f"months-reader-{User.objects.count() + 1}"
    user = User.objects.create_user(
        username=name, email=f"{name}@example.com", password="x", is_active=True,
    )
    client = Client()
    client.force_login(user)
    return client


def _period():
    return ReportingPeriodFactory(
        name="WY 2024-2025",
        start_date=dt.date(2024, 10, 1),
        end_date=dt.date(2025, 9, 30),
    )


def _pane(parcel, period):
    response = _client().get(
        reverse("parcels:detail", args=[parcel.pk]),
        {"period": str(period.pk)},
        HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 200
    return response.content.decode()


def _ledger(parcel, period, source_type, amount, day):
    return ParcelLedgerFactory(
        parcel=parcel,
        reporting_period=period,
        source_type=source_type,
        amount_acre_feet=Decimal(amount),
        transaction_date=day,
        effective_date=day,
    )


def _june_run(parcel):
    """June 2025 on a well field with no meter: crop 91.8503, rain 1.0000,
    canal 80.8955 (a 107.8607 delivery at 0.750), well water 9.9548, pumped
    12.4435, of which 2.4887 returned to the aquifer."""
    return CalculationRun.objects.create(
        parcel=parcel,
        period="2025-06",
        gross_et_af=Decimal("91.8503"),
        net_consumptive_use_af=Decimal("90.8503"),
        effective_precip_af=Decimal("1.0000"),
        surface_delivered_af=Decimal("107.8607"),
        surface_efficiency=Decimal("0.750"),
        surface_water_af=Decimal("80.8955"),
        final_af=Decimal("9.9548"),
        gw_extracted_af=Decimal("12.4435"),
        deep_percolation_gw_af=Decimal("2.4887"),
        over_delivery_af=Decimal("0.0000"),
        residual_disposition="groundwater",
        breakdown=[
            {
                "step_type": "subtract_surface_water",
                "label": "Subtract canal water the crop could use",
                "detail": {
                    "delivered_af": "107.8607",
                    "efficiency": "0.750",
                    "efficiency_source": "agency",
                    "consumed_af": "80.8955",
                    "surface_water_af": "80.8955",
                },
                "input_af": "90.8503",
                "output_af": "9.9548",
            }
        ],
        methodology_plan_name="Default Methodology",
    )


def _well_field(parcel_number, *, july=True):
    """A well field with June's run and its rows; July metered unless told not."""
    period = _period()
    parcel = ParcelFactory(parcel_number=parcel_number)
    WellIrrigatedParcelFactory(well=WellFactory(), parcel=parcel)
    _ledger(parcel, period, "surface_diversion", "-107.8607", dt.date(2025, 6, 15))
    _ledger(parcel, period, "calculated", "-9.9548", dt.date(2025, 6, 1))
    _june_run(parcel)
    if july:
        _ledger(parcel, period, "meter_reading", "-94.9987", dt.date(2025, 7, 15))
        CalculationRun.objects.create(
            parcel=parcel,
            period="2025-07",
            gross_et_af=Decimal("81.0000"),
            net_consumptive_use_af=Decimal("80.0000"),
            effective_precip_af=Decimal("1.0000"),
            surface_delivered_af=Decimal("0.0000"),
            surface_water_af=Decimal("0.0000"),
            final_af=Decimal("80.0000"),
            over_delivery_af=Decimal("0.0000"),
            residual_disposition="metered",
            breakdown=[],
            methodology_plan_name="Default Methodology",
        )
    return parcel, period


def _card(html):
    assert "Month by month" in html, "the field page carries no Month by month card"
    return html[html.index("Month by month"):]


def _row(card, month):
    start = card.index(f">{month}<")
    return card[start: card.index("</tr>", start)]


def test_each_month_lists_the_figures_its_run_stored():
    """(a) June's six figures, July's meter reading with its badge, newest first."""
    parcel, period = _well_field("TST-MONTHS-001")
    card = _card(_pane(parcel, period))

    june = _row(card, "Jun 2025")
    for figure in ("107.86", "80.90", "26.97", "12.44", "9.95", "2.49"):
        assert figure in june, f"Jun 2025 is missing {figure}: {june}"
    assert '<span class="badge badge-grey">Estimated</span>' in june

    july = _row(card, "Jul 2025")
    assert "95.00" in july
    assert '<span class="badge badge-grey">Metered</span>' in july
    assert ">0.00<" not in july, "a month with no delivery printed 0.00, not a dash"

    assert card.index(">Jul 2025<") < card.index(">Jun 2025<"), "rows are not newest first"

    totals = _row(card, "All 2 months")
    for figure in ("107.86", "80.90", "26.97", "107.44", "9.95", "2.49"):
        assert figure in totals, f"All 2 months is missing {figure}: {totals}"


def test_the_panel_splits_deep_percolation_by_where_the_water_came_from():
    """(b) 26.97 from canal water, 2.49 from groundwater."""
    parcel, period = _well_field("TST-MONTHS-002")
    html = _pane(parcel, period)

    assert "<span>from canal water</span><b>26.97</b>" in html
    assert "<span>from groundwater</span><b>2.49</b>" in html


def test_the_panel_states_the_canal_water_the_crop_could_use():
    """(c) 80.90 at the one efficiency every delivered month ran at, 75%."""
    parcel, period = _well_field("TST-MONTHS-003")
    html = _pane(parcel, period)

    assert "<span>the crop could use (75%)</span><b>80.90</b>" in html


def test_a_one_run_period_reads_the_same_on_the_panel_and_the_receipt():
    """(d) The panel's delivered and usable figures are the receipt's."""
    parcel, period = _well_field("TST-MONTHS-004", july=False)
    html = _pane(parcel, period)
    assert "<span>Surface</span><b>107.86</b>" in html
    assert "<span>the crop could use (75%)</span><b>80.90</b>" in html

    receipt = _client().get(
        reverse(
            "accounting:calculation_run_detail",
            kwargs={"parcel_id": parcel.pk, "period": "2025-06"},
        )
    )
    assert receipt.status_code == 200
    receipt_html = receipt.content.decode()
    assert "107.86" in receipt_html
    assert "80.90" in receipt_html


def _split_field(parcel_number, records):
    """A no-well field whose June delivery is a 0.3 share of each headgate.

    One point of diversion per record (a point holds one direct-use record a
    month, a unique key), each with its own split row of 0.3 x the record's
    volume, so the field's June delivery adds to 30.0000 for the two-record
    case (60 + 40) and for the one-record case (100).
    """
    period = _period()
    parcel = ParcelFactory(parcel_number=parcel_number)
    device = MeasuringDevice.objects.create(
        nickname="Gate meter",
        device_type="inline_flow_meter",
        accuracy_percent=Decimal("5"),
    )
    for volume, method in records:
        pod = PointOfDiversionFactory()
        DiversionRecordFactory(
            point_of_diversion=pod,
            month=dt.date(2025, 6, 1),
            volume_acre_feet=Decimal(volume),
            method=method,
            device=device,
        )
        share = (Decimal(volume) * Decimal("0.3")).quantize(Decimal("0.0001"))
        row = _ledger(parcel, period, "surface_diversion", str(-share), dt.date(2025, 6, 15))
        row.divided_from_headgate = True
        row.divided_from_point_pk = pod.pk
        row.save()
    CalculationRun.objects.create(
        parcel=parcel,
        period="2025-06",
        gross_et_af=Decimal("40.0000"),
        net_consumptive_use_af=Decimal("39.0000"),
        effective_precip_af=Decimal("1.0000"),
        surface_delivered_af=Decimal("30.0000"),
        surface_efficiency=Decimal("0.750"),
        surface_water_af=Decimal("22.5000"),
        final_af=Decimal("0.0000"),
        unmet_demand_af=Decimal("16.5000"),
        over_delivery_af=Decimal("0.0000"),
        residual_disposition="unmet_demand",
        breakdown=[],
        methodology_plan_name="Default Methodology",
    )
    return parcel, period


def test_no_band_when_a_summed_record_is_estimated():
    """(e) One of the month's two records was estimated from use: no band."""
    parcel, period = _split_field(
        "TST-MONTHS-005",
        [("60.0000", "device"), ("40.0000", "estimated_from_use")],
    )
    card = _card(_pane(parcel, period))

    assert "30.00" in _row(card, "Jun 2025"), "the June delivery did not render"
    assert "±" not in card


def test_a_band_when_every_record_states_an_accuracy():
    """(f) 100.0000 AF at 5%, the field's 0.3 share: ± 1.50."""
    parcel, period = _split_field("TST-MONTHS-006", [("100.0000", "device")])
    june = _row(_card(_pane(parcel, period)), "Jun 2025")

    assert "± 1.50" in june
    assert "(±5%)" in june


def test_no_card_on_a_field_with_no_well_and_no_delivery():
    """(g) Neither group has anything to show, so there is no card."""
    period = _period()
    parcel = ParcelFactory(parcel_number="TST-MONTHS-007")
    CalculationRun.objects.create(
        parcel=parcel,
        period="2025-06",
        gross_et_af=Decimal("40.0000"),
        net_consumptive_use_af=Decimal("39.0000"),
        effective_precip_af=Decimal("1.0000"),
        final_af=Decimal("0.0000"),
        unmet_demand_af=Decimal("39.0000"),
        over_delivery_af=Decimal("0.0000"),
        residual_disposition="unmet_demand",
        breakdown=[],
        methodology_plan_name="Default Methodology",
    )
    html = _pane(parcel, period)

    assert "Supplies by source" in html, "the balance panel did not render"
    assert "Month by month" not in html
