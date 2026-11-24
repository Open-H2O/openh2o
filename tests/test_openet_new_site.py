# SPDX-License-Identifier: AGPL-3.0-or-later
"""What a new site that follows the guide gets from OpenET, and what a month says when it has no rain.

A site set up by copying ``.env.example`` takes the route its settings name. The field list is
the documented default; the older routes count rain only from Earth Engine, so a month there can
be calculated with no rain on record. Such a month records that no rain was counted, its page
does not say the rain was estimated from gridMET, and the water year's page names the month.
"""
from decimal import Decimal as D
from pathlib import Path

import pytest
from django.conf import settings as live
from django.test import Client
from django.urls import reverse

from tests import ledger_districts as ld
from tests.test_openet_recorded_figure import AUG_6, FIRST, JULY, _corn_field, _fetch, _run, _user

pytestmark = pytest.mark.django_db

GRIDMET_CAPTION = "estimated from gridMET rainfall"


def _live_settings(name):
    """The values the example settings file sets for ``name`` on uncommented lines."""
    text = (Path(live.BASE_DIR) / ".env.example").read_text()
    found = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        if key.strip() == name:
            found.append(value.strip())
    return found


def test_the_example_settings_choose_the_field_list():
    """A site that copies .env.example lands on the field list, the route the guides document."""
    assert _live_settings("OPENET_MODE") in ([], ["fields"])


def _rain_step(run):
    return next(s for s in run.breakdown if s.get("step_type") == "subtract_effective_precip")


def _period_pk():
    from accounting.models import ReportingPeriod

    return ReportingPeriod.objects.get(name="WY 2024-2025").pk


def test_a_month_with_no_rain_on_record_says_none_was_counted(settings):
    settings.OPENET_MODE = "api"
    field = _corn_field()
    _fetch(field, FIRST, AUG_6)
    ld.run_months([JULY])
    run = _run(field)

    assert _rain_step(run)["detail"]["rain_on_record"] == "none"

    client = Client()
    client.force_login(_user("reader"))
    month_url = reverse("accounting:calculation_run_detail", args=[field.pk, JULY])
    page = client.get(month_url).content.decode()
    assert GRIDMET_CAPTION not in page
    assert 'data-rain-on-record="none"' in page

    year = client.get(reverse("accounting:period_detail", args=[_period_pk()])).content.decode()
    assert 'id="months-without-rain"' in year
    listed = year.split('id="months-without-rain"', 1)[1]
    assert month_url in listed


def test_a_month_with_rain_on_record_keeps_the_gridmet_caption(settings):
    """The control: rain on record is counted, and the page says where it came from."""
    from tests.test_precip_step import _precip_cache

    settings.OPENET_MODE = "api"
    field = _corn_field()
    _fetch(field, FIRST, AUG_6)
    _precip_cache(field, period=JULY, precip_mm=20.0)
    ld.run_months([JULY])
    run = _run(field)

    assert _rain_step(run)["detail"]["rain_on_record"] == "all"
    client = Client()
    client.force_login(_user("reader"))
    page = client.get(reverse("accounting:calculation_run_detail", args=[field.pk, JULY])).content.decode()
    assert GRIDMET_CAPTION in page
    year = client.get(reverse("accounting:period_detail", args=[_period_pk()])).content.decode()
    assert 'id="months-without-rain"' not in year


def _field_list_case(rain_a, rain_b):
    """A made-up use area on two OpenET fields with July recorded from them."""
    from datasync import crop_et
    from datasync.field_list import compute_shares
    from datasync.models import OpenETFieldMonth
    from tests.test_openet_field_list import JULY_1, RECEIVED, _sixty_thirty, _use_area

    parcel = _use_area()
    a, b = _sixty_thirty()
    compute_shares(parcel)
    for field, rain in ((a, rain_a), (b, rain_b)):
        OpenETFieldMonth.objects.create(
            field=field, month=JULY_1, et_mm=D("120"), pr_mm=rain, received_on=RECEIVED
        )
    crop_et.record_fetched_months(parcel, [JULY])
    return parcel


@pytest.mark.parametrize(
    "rain_a, rain_b, expected",
    [(D("5"), D("10"), "all"), (D("5"), None, "some"), (None, None, "none")],
)
def test_a_field_list_month_records_whether_its_fields_rain_was_counted(rain_a, rain_b, expected):
    """A field missing its rain makes the month count none, and the record says only some had it."""
    from accounting.steps import subtract_effective_precip

    parcel = _field_list_case(rain_a, rain_b)
    _new, record = subtract_effective_precip(
        D("500"), parcel, JULY, {}, {"method": "usda_scs", "soil_storage_in": 3.0}
    )
    assert record["detail"]["rain_on_record"] == expected
    if expected != "all":
        assert D(record["detail"]["effective_precip_af"]) == 0
