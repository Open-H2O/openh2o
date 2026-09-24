# SPDX-License-Identifier: AGPL-3.0-or-later
"""Who made a change, and why: attribution on the change history (147-01 Task 3).

Every write that moves a number is recorded by trigger (``core/history.py``).
These tests pin what the record says about WHO and WHY on each kind of path:

- a web request (HTMX PATCH and form POST): the signed-in user's id and the
  request path, attached by ``pghistory.middleware.HistoryMiddleware``;
- a management command: its name and arguments, attached by ``manage.py``'s
  ``command_context``; schema commands (``migrate`` and the rest) carry none;
- a note: the "Note (why)" box on the methodology and delivery settings pages;
- a forced recompute of a finalized period: a fixed reason.

Every assertion is an exact value (the user's id, the note's text, the stored
before and after), never a direction and never a re-derivation.
"""
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client
from django.urls import reverse
from django.utils.http import urlencode

from accounting.management.commands.run_calculations import FORCE_REASON
from accounting.models import CalculationRun, CalculationStep
from core.history import LABEL_BEFORE_UPDATE, command_context
from core.models import SiteConfig
from tests.factories import ParcelFactory, WellFactory, WellIrrigatedParcelFactory
from tests.test_calculation_run import _seed_finalized_parcel

pytestmark = pytest.mark.django_db

User = get_user_model()


def _client(user):
    client = Client()
    client.force_login(user)
    return client


@pytest.fixture
def operator():
    return User.objects.create_user(username="operator", password="x", is_active=True)


@pytest.fixture
def administrator():
    return User.objects.create_user(
        username="administrator", password="x", is_active=True, agency_admin=True
    )


def _patch(client, url, **data):
    return client.patch(
        url, data=urlencode(data), content_type="application/x-www-form-urlencoded"
    )


def _pair(obj):
    """The (as it was, as it became) events of an object's one recorded update."""
    before = obj.events.get(pgh_label=LABEL_BEFORE_UPDATE)
    after = obj.events.get(pgh_label="update")
    return before, after


# -- Web requests --------------------------------------------------------------


def test_area_edit_by_patch_records_the_user_and_both_values(operator):
    parcel = ParcelFactory(area_acres="80.00")
    url = reverse("parcels:edit_field", args=[parcel.pk])

    resp = _patch(_client(operator), url, field="area_acres", value="81.25")

    assert resp.status_code == 200
    before, after = _pair(parcel)
    assert before.area_acres == Decimal("80.00")
    assert after.area_acres == Decimal("81.25")
    assert after.pgh_context_id == before.pgh_context_id
    assert after.pgh_context.metadata == {"user": operator.pk, "url": url}


def test_well_share_edit_by_patch_records_the_user_and_both_values(operator):
    well = WellFactory()
    wip = WellIrrigatedParcelFactory(well=well, fraction="1.0000")
    url = reverse("wells:irrigated_parcel_edit_share", args=[well.pk, wip.pk])

    resp = _patch(_client(operator), url, value="0.4")

    assert resp.status_code == 200
    before, after = _pair(wip)
    assert before.fraction == Decimal("1.0000")
    assert after.fraction == Decimal("0.4000")
    assert after.pgh_context.metadata == {"user": operator.pk, "url": url}


def test_methodology_step_config_records_user_note_and_config(administrator):
    call_command("seed_calculation_plan")
    step = CalculationStep.objects.get(step_type="clamp_floor")
    old_floor = step.config["floor"]
    url = reverse("accounting:methodology_step_config", args=[step.pk])

    resp = _client(administrator).post(
        url,
        {"label": step.label, "floor": "2.5", "note": "  Board set a floor, 9/23 minutes  "},
    )

    assert resp.status_code == 200
    before, after = _pair(step)
    assert before.config["floor"] == old_floor
    assert after.config["floor"] == 2.5
    assert after.pgh_context.metadata == {
        "user": administrator.pk,
        "url": url,
        "note": "Board set a floor, 9/23 minutes",
    }


def test_methodology_toggle_records_the_shared_note(administrator):
    call_command("seed_calculation_plan")
    step = CalculationStep.objects.get(step_type="clamp_floor")
    url = reverse("accounting:methodology_step_toggle", args=[step.pk])

    _client(administrator).post(url, {"note": "Testing without the floor"})

    before, after = _pair(step)
    assert (before.enabled, after.enabled) == (True, False)
    assert after.pgh_context.metadata["note"] == "Testing without the floor"


def test_a_blank_note_attaches_nothing(administrator):
    call_command("seed_calculation_plan")
    step = CalculationStep.objects.get(step_type="clamp_floor")
    url = reverse("accounting:methodology_step_toggle", args=[step.pk])

    _client(administrator).post(url, {"note": "   "})

    _before, after = _pair(step)
    assert after.pgh_context.metadata == {"user": administrator.pk, "url": url}


def test_a_note_is_cut_at_500_characters(administrator):
    call_command("seed_calculation_plan")
    step = CalculationStep.objects.get(step_type="clamp_floor")
    url = reverse("accounting:methodology_step_toggle", args=[step.pk])

    _client(administrator).post(url, {"note": "x" * 600})

    _before, after = _pair(step)
    assert after.pgh_context.metadata["note"] == "x" * 500


def test_a_move_writes_only_the_two_steps_that_trade_places(administrator):
    call_command("seed_calculation_plan")
    steps = list(CalculationStep.objects.order_by("order"))
    assert len(steps) == 5
    first, second = steps[0], steps[1]
    url = reverse("accounting:methodology_step_move", args=[second.pk, "up"])

    _client(administrator).post(url, {"note": "Precipitation first"})

    for untouched in steps[2:]:
        assert untouched.events.exclude(pgh_label="insert").count() == 0
    # Each moved step: lifted out of the way, then set to its final place.
    assert list(
        first.events.exclude(pgh_label="insert")
        .order_by("pgh_id")
        .values_list("pgh_label", "order")
    ) == [
        (LABEL_BEFORE_UPDATE, 1),
        ("update", 10001),
        (LABEL_BEFORE_UPDATE, 10001),
        ("update", 2),
    ]
    first_final = first.events.filter(pgh_label="update").order_by("-pgh_id").first()
    assert first_final.pgh_context.metadata["note"] == "Precipitation first"


def test_delivery_settings_record_user_note_and_exact_decimal(administrator):
    config, _ = SiteConfig.objects.get_or_create(defaults={"agency_name": "Agency"})
    SiteConfig.objects.filter(pk=config.pk).update(
        default_irrigation_efficiency=Decimal("0.750")
    )
    url = reverse("accounting:delivery_settings")

    resp = _client(administrator).post(
        url,
        {
            "efficiency_percent": "80",
            # 148-02 Task 4: `wells` is enabled by default in these tests, so
            # groundwater_efficiency_percent is a required field on this POST
            # the same way efficiency_percent is (surface).
            "groundwater_efficiency_percent": "80",
            "recovery_horizon": "carry_forward",
            "diversion_report_year_rule": "season",
            "season_start_month": "3",
            "note": "Irrigation survey result",
        },
    )

    assert resp.status_code == 302
    events = config.events.filter(pgh_context__isnull=False)
    before = events.get(pgh_label=LABEL_BEFORE_UPDATE)
    after = events.get(pgh_label="update")
    assert str(before.default_irrigation_efficiency) == "0.750"
    assert str(after.default_irrigation_efficiency) == "0.800"
    assert after.pgh_context.metadata == {
        "user": administrator.pk,
        "url": url,
        "note": "Irrigation survey result",
    }


# -- Commands ------------------------------------------------------------------


def test_a_command_is_attributed_by_name_and_arguments():
    argv = ["manage.py", "shell", "-c", "pass"]
    with command_context(argv):
        parcel = ParcelFactory(area_acres="12.50")

    event = parcel.events.get(pgh_label="insert")
    assert event.pgh_context.metadata == {"command": "shell", "argv": argv[1:]}


@pytest.mark.parametrize("name", ["migrate", "makemigrations", "test", "check"])
def test_schema_and_test_commands_carry_no_context(name):
    with command_context(["manage.py", name]):
        parcel = ParcelFactory(area_acres="12.50")

    assert parcel.events.get(pgh_label="insert").pgh_context_id is None


def test_forced_recompute_of_a_finalized_period_carries_the_reason():
    parcel = _seed_finalized_parcel("HIST-FORCE")
    argv = ["manage.py", "run_calculations", "--period", "2024-06", "--force"]

    with command_context(argv):
        call_command("run_calculations", "--period", "2024-06", "--force")

    run = CalculationRun.objects.get(parcel=parcel, period="2024-06")
    event = run.events.get(pgh_label="insert")
    assert event.pgh_context.metadata == {
        "command": "run_calculations",
        "argv": argv[1:],
        "override": True,
        "reason": FORCE_REASON,
    }
    assert FORCE_REASON == "--force on a finalized period"


def test_forced_recompute_without_a_caller_context_still_carries_the_reason():
    parcel = _seed_finalized_parcel("HIST-FORCE-BARE")

    call_command("run_calculations", "--period", "2024-06", "--force")

    run = CalculationRun.objects.get(parcel=parcel, period="2024-06")
    event = run.events.get(pgh_label="insert")
    # 147-02: the forced recompute goes through the finalized-period lock's
    # recorded door, which marks every write it makes as an override.
    assert event.pgh_context.metadata == {
        "override": True,
        "reason": "--force on a finalized period",
    }


# -- Writes no signal sees: bulk_create and QuerySet.update ---------------------


def test_a_bulk_ledger_import_leaves_one_insert_event_per_row():
    from accounting.ledger_import import import_ledger_rows
    from parcels.models import ParcelLedger
    from tests.test_ledger_import_sign_report import (
        SHAPE_6_LEDGER_CSV,
        SHAPE_6_PARCEL_NUMBERS,
    )
    from tests.factories import WaterTypeFactory
    import io

    for apn in SHAPE_6_PARCEL_NUMBERS:
        ParcelFactory(parcel_number=apn)
    WaterTypeFactory(code="GW")
    WaterTypeFactory(code="SW")
    with command_context(["manage.py", "import_ledger_csv"]):
        import_ledger_rows(io.StringIO(SHAPE_6_LEDGER_CSV))

    rows = list(ParcelLedger.objects.order_by("pk"))
    assert rows, "the fixture imported no rows"
    for row in rows:
        event = row.events.get(pgh_label="insert")
        assert event.amount_acre_feet == row.amount_acre_feet
        assert event.pgh_context.metadata["command"] == "import_ledger_csv"


def test_attach_orphans_to_period_update_leaves_a_before_and_after():
    import datetime as dt

    from accounting.services import attach_orphans_to_period
    from tests.factories import ParcelLedgerFactory, ReportingPeriodFactory

    row = ParcelLedgerFactory(effective_date=dt.date(2024, 6, 15), reporting_period=None)
    period = ReportingPeriodFactory(start_date=dt.date(2024, 1, 1), end_date=dt.date(2024, 12, 31))

    attach_orphans_to_period(period)

    before, after = _pair(row)
    assert before.reporting_period is None
    assert after.reporting_period == period.pk
