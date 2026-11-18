# SPDX-License-Identifier: AGPL-3.0-or-later
"""OpenET's answer for a use area's month is recorded once, crop ET and rain together (ISS-353, ruling 208).

What a correct site does:

* the first answer for a month records the use area's crop ET and, beside it, each OpenET
  field's rain, crop ET and acres from that answer; on a use area with no OpenET field the
  month's rain is recorded once on its own;
* the calculation's effective rain reads only that record, so OpenET sending the month again
  with other figures moves nothing;
* a revision that changes only rain shows no newer figure and no Accept button;
* accepting a newer crop ET figure takes that answer's rain with it, and the month is
  recalculated from one answer;
* every writer records first figures, and the record keeps the finalized-year lock.

**Every OpenET field number and figure in this file is made up.** The use areas are the made-up
100-acre fields of ``tests/ledger_districts``.
"""

import datetime as dt
import json
from decimal import Decimal as D
from io import StringIO
from unittest import mock

import pytest
from django.core.management import call_command
from django.db import DatabaseError, transaction

from accounting.locks import LOCK_SQLSTATE
from accounting.models import CalculationRun, ReportingPeriod
from datasync.models import CropETFigure, OpenETCache, OpenETFieldMonth, OpenETFieldShare
from tests import ledger_districts as ld
from tests.test_openet_field_parts_page import MADE_UP_EAST, MADE_UP_WEST, _fields_over
from tests.test_openet_recorded_figure import (  # noqa: F401  (fixtures)
    JULY,
    NOTICE_WORDS,
    REASON,
    _accept,
    _corn_field,
    _hand_cache,
    _page,
    operator,
)

pytestmark = pytest.mark.django_db

JULY_1 = dt.date(2025, 7, 1)
#: The day the made-up revision arrives.
DEC_10 = dt.date(2025, 12, 10)
USDA = {"method": "usda_scs", "soil_storage_in": 3.0}


@pytest.fixture(autouse=True)
def _fields_route(settings, monkeypatch):
    settings.ACCESS_CONTROL_ENFORCED = True
    settings.OPENET_MODE = "fields"
    settings.OPENET_MONTHLY_BUDGET = 50
    monkeypatch.setenv("OPENET_API_KEY", "made-up-key-not-real")


# ---------------------------------------------------------------- the site's pieces


def _resend(parcel, et, pr, on=DEC_10):
    """OpenET sends July again for both made-up fields, through the site's own sync command."""
    answer = [
        (MADE_UP_WEST, JULY_1, D(str(et[0])), D(str(pr[0]))),
        (MADE_UP_EAST, JULY_1, D(str(et[1])), D(str(pr[1]))),
    ]
    with (
        mock.patch("datasync.field_list.figures", return_value=answer),
        mock.patch("django.utils.timezone.localdate", return_value=on),
    ):
        call_command(
            "sync_openet_parcels", "--start-date", "2025-07-01", "--end-date", "2025-07-31",
            "--parcel-prefix", parcel.parcel_number, stdout=StringIO(),
        )


def _run(parcel):
    return CalculationRun.objects.filter(parcel=parcel, period=JULY).order_by("-pk").first()


def _rain_step(parcel):
    from accounting.steps import subtract_effective_precip

    _new, record = subtract_effective_precip(D("500"), parcel, JULY, {}, USDA)
    return D(record["detail"]["effective_precip_af"])


def _record(parcel, variable="ET", model="Ensemble"):
    return CropETFigure.objects.current().filter(
        parcel=parcel, month=JULY_1, variable=variable, model_name=model
    ).first()


def _by_hand(parcel, et, pr):
    """Effective rain in acre-feet, field by field, worked from the formula module alone."""
    from accounting.precip_math import effective_precip_inches

    acres = {s.field.field_id: D(s.overlap_acres) for s in OpenETFieldShare.objects.filter(parcel=parcel)}
    total = D("0")
    for number, et_mm, pr_mm in ((MADE_UP_WEST, et[0], pr[0]), (MADE_UP_EAST, et[1], pr[1])):
        pe_in = effective_precip_inches(D(str(pr_mm)) / D("25.4"), D(str(et_mm)) / D("25.4"), **USDA)
        total += pe_in * D("25.4") * acres[number] / D("304.8")
    return total


def _stamped_fields(parcel):
    run = _run(parcel)
    detail = next(s.get("detail") or {} for s in run.breakdown if s.get("step_type") == "et_gross")
    return detail.get("fields")


# ---------------------------------------------------------------- 1. a revision moves nothing


def test_a_revised_rain_month_from_openet_leaves_the_months_effective_rain_as_it_was():
    field = _corn_field()
    _fields_over(field)  # crop ET 500 and 400 mm, rain 40 and 20 mm
    ld.run_months([JULY])
    before = _run(field).effective_precip_af

    _resend(field, et=(500, 400), pr=(80, 60))
    ld.run_months([JULY])

    assert _run(field).effective_precip_af == before
    assert _rain_step(field) == _by_hand(field, (500, 400), (40, 20))


def test_a_rain_only_revision_shows_no_newer_figure_and_no_accept_button(operator):
    field = _corn_field()
    _fields_over(field)
    ld.run_months([JULY])

    _resend(field, et=(500, 400), pr=(80, 60))
    page = _page(operator, field)

    assert NOTICE_WORDS not in page
    assert "Accept the newer figure" not in page


def test_a_revised_crop_et_waits_for_a_person_and_accepting_it_takes_that_answers_rain(operator):
    field = _corn_field()
    _fields_over(field)
    ld.run_months([JULY])
    first = _run(field).effective_precip_af

    _resend(field, et=(550, 420), pr=(80, 60))
    ld.run_months([JULY])
    # Nobody has accepted the newer figure: the month is figured from the first answer.
    assert _run(field).effective_precip_af == first
    assert NOTICE_WORDS in _page(operator, field)

    _accept(operator, field)
    # Accepting recalculates the month from the newer answer, its rain included.
    assert _rain_step(field) == _by_hand(field, (550, 420), (80, 60))
    assert abs(_run(field).effective_precip_af - _by_hand(field, (550, 420), (80, 60))) < D("0.0001")


def test_after_a_revision_nobody_accepted_the_month_still_lists_its_fields_with_the_recorded_rain():
    field = _corn_field()
    _fields_over(field)
    ld.run_months([JULY])
    listed = _stamped_fields(field)

    _resend(field, et=(550, 420), pr=(80, 60))
    ld.run_months([JULY])

    assert listed
    assert _stamped_fields(field) == listed


# ---------------------------------------------------------------- 2. the route follows the record


def test_a_month_recorded_before_the_use_area_had_openet_fields_keeps_its_recorded_rain():
    from datasync import crop_et

    field = _corn_field()
    _hand_cache(field, {JULY: 120.0}, JULY_1, dt.date(2025, 7, 31))
    _hand_cache(field, {JULY: 30.0}, JULY_1, dt.date(2025, 7, 31),
                model="GRIDMET", variable="precip", key="precip")
    crop_et.record_fetched_months(field, [JULY])
    crop_et.record_fetched_months(field, [JULY], variable="precip", model="GRIDMET")
    before = _rain_step(field)

    _fields_over(field)  # the use area gains OpenET fields; July already has its record

    assert before > 0
    assert _rain_step(field) == before


# ---------------------------------------------------------------- 3. every writer records first figures


def test_the_field_sync_records_each_fields_rain_crop_et_and_acres_from_the_first_answer():
    from datasync.field_list import compute_shares
    from datasync.models import OpenETField
    from tests.test_openet_field_parts_page import _strip

    field = _corn_field()
    for number, (x0, x1) in ((MADE_UP_WEST, (0.0, 0.6)), (MADE_UP_EAST, (0.6, 0.9))):
        from django.contrib.gis.geos import MultiPolygon

        OpenETField.objects.create(field_id=number, geometry=MultiPolygon(_strip(field, x0, x1), srid=4326),
                                   received_on=dt.date(2025, 8, 6))
    compute_shares(field)
    _resend(field, et=(500, 400), pr=(40, 20), on=dt.date(2025, 8, 6))
    _resend(field, et=(500, 400), pr=(80, 60))

    fields = getattr(_record(field), "fields", None)
    assert fields is not None
    acres = {s.field.field_id: s.overlap_acres for s in OpenETFieldShare.objects.filter(parcel=field)}
    assert [(f["field_id"], D(f["acres"]), D(f["et_mm"]), D(f["pr_mm"])) for f in fields] == [
        (MADE_UP_WEST, acres[MADE_UP_WEST], D("500"), D("40")),
        (MADE_UP_EAST, acres[MADE_UP_EAST], D("400"), D("20")),
    ]


def test_a_field_month_openet_sends_again_with_other_figures_carries_the_day_it_arrived():
    field = _corn_field()
    _fields_over(field)

    _resend(field, et=(550, 400), pr=(40, 20))

    row = OpenETFieldMonth.objects.get(field__field_id=MADE_UP_WEST, month=JULY_1)
    assert row.received_on == DEC_10


def _fields_file(tmp_path, parcel, pr, name):
    payload = {
        "meta": {"source": "made up for this test"},
        "fields": [{"field_id": MADE_UP_WEST, "area_acres": "200.00", "received_on": "2025-08-06"}],
        "shares": [{"parcel_number": parcel.parcel_number, "field_id": MADE_UP_WEST, "overlap_acres": "60.00"}],
        "months": [{"field_id": MADE_UP_WEST, "month": JULY, "et_mm": "300", "pr_mm": str(pr),
                    "received_on": "2025-08-06"}],
    }
    path = tmp_path / name
    path.write_text(json.dumps(payload))
    return path


def test_loading_the_fields_file_again_with_other_rain_leaves_the_months_rain(tmp_path):
    field = _corn_field()
    call_command("load_openet_fields_fixture", "--fixture", str(_fields_file(tmp_path, field, 40, "a.json")),
                 stdout=StringIO())
    before = _rain_step(field)

    call_command("load_openet_fields_fixture", "--fixture", str(_fields_file(tmp_path, field, 90, "b.json")),
                 stdout=StringIO())

    assert before > 0
    assert _rain_step(field) == before


def test_the_rain_sync_records_a_month_once_and_a_second_answer_leaves_it():
    from datasync import crop_et

    field = _corn_field()
    _hand_cache(field, {JULY: 120.0}, JULY_1, dt.date(2025, 7, 31))
    crop_et.record_fetched_months(field, [JULY])
    init = "datasync.management.commands.sync_precip_parcels.init_earth_engine"
    reduce = "datasync.management.commands.sync_precip_parcels.reduce_precip_by_parcel"
    for rain in (30.0, 70.0):
        with mock.patch(init, return_value=mock.MagicMock()), \
                mock.patch(reduce, return_value={field.pk: {JULY: rain}}):
            call_command("sync_precip_parcels", start_date="2025-07-01", end_date="2025-07-31",
                         parcel_prefix=field.parcel_number, stdout=StringIO())
        if rain == 30.0:
            before = _rain_step(field)

    record = _record(field, "precip", "GRIDMET")
    assert record is not None and D(record.depth_mm) == D("30")
    assert _rain_step(field) == before


def test_loading_the_openet_file_again_with_other_rain_leaves_the_months_rain(tmp_path):
    field = _corn_field()

    def load(rain, name):
        path = tmp_path / name
        path.write_text(json.dumps({"rows": [
            {"parcel_number": field.parcel_number, "start_date": "2025-07-01", "end_date": "2025-07-31",
             "variable": "ET", "model_name": "Ensemble", "source": "OpenET", "received": "2025-08-06",
             "et_data": [{"date": JULY, "et": 120.0, "unit": "mm"}]},
            {"parcel_number": field.parcel_number, "start_date": "2025-07-01", "end_date": "2025-07-31",
             "variable": "precip", "model_name": "GRIDMET", "source": "gridMET", "received": "2025-08-06",
             "et_data": [{"date": JULY, "precip": rain, "unit": "mm"}]},
        ]}))
        call_command("load_openet_fixture", "--fixture", str(path), stdout=StringIO())

    load(30.0, "a.json")
    before = _rain_step(field)
    load(70.0, "b.json")

    record = _record(field, "precip", "GRIDMET")
    assert record is not None and D(record.depth_mm) == D("30")
    assert _rain_step(field) == before


# ---------------------------------------------------------------- 4. the finalized-year lock


def _finalize():
    ReportingPeriod.objects.filter(name="WY 2024-2025").update(is_finalized=True)


def test_a_first_rain_record_goes_in_inside_a_finalized_year():
    from datasync import crop_et

    field = _corn_field()
    _finalize()
    _hand_cache(field, {JULY: 30.0}, JULY_1, dt.date(2025, 7, 31),
                model="GRIDMET", variable="precip", key="precip")

    crop_et.record_fetched_months(field, [JULY], variable="precip", model="GRIDMET")

    assert _record(field, "precip", "GRIDMET") is not None


def test_a_records_fields_cannot_be_changed_inside_a_finalized_year():
    field = _corn_field()
    _fields_over(field)
    _finalize()
    record = _record(field)

    with pytest.raises(DatabaseError) as refused, transaction.atomic():
        CropETFigure.objects.filter(pk=record.pk).update(fields=[])

    assert getattr(refused.value.__cause__, "pgcode", None) == LOCK_SQLSTATE
