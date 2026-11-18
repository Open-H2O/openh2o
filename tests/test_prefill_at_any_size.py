# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Prepare with OpenET page opens and saves at any size.

The page lists its use areas (wells, points of diversion) 25 to a page with a search, and a
Save, a search or a page turn posts only the boxes on the page in view, so no Save can pass
Django's 1,000-field limit. A change saved on one page survives a Save from another, and it
shows wherever its row is listed.

**Every number in this file is made up.** At 80.00 acres a depth of 3.81 mm is one acre-foot.
"""

import re
from datetime import date
from decimal import Decimal as D

import pytest
from django.urls import reverse

from datasync.models import CropETFigure
from reporting.models import ReportSubmission, ReportTemplate
from tests.factories import (
    ParcelFactory,
    PointOfDiversionFactory,
    PointOfDiversionParcelFactory,
    ReportingPeriodFactory,
    WellFactory,
    WellIrrigatedParcelFactory,
)

pytestmark = pytest.mark.django_db

MM_PER_AF_AT_80_ACRES = D("3.81")
JAN = date(2024, 1, 1)
YEAR = [date(2023, m, 1) for m in (10, 11, 12)] + [date(2024, m, 1) for m in range(1, 10)]
VAL = re.compile(r'name="val:([a-z]+):(\d+):(\d{4}-\d{2})"[^>]*value="([^"]*)"')


@pytest.fixture
def period():
    return ReportingPeriodFactory()


@pytest.fixture
def office(client, django_user_model):
    client.force_login(django_user_model.objects.create_user(username="office", password="x"))
    return client


def _use_areas(n, months=(JAN,)):
    """``n`` use areas MADEUP-001 ... each with one acre-foot a month recorded."""
    parcels = [ParcelFactory(parcel_number=f"MADEUP-{i:03d}") for i in range(1, n + 1)]
    CropETFigure.objects.bulk_create(
        CropETFigure(parcel=p, month=m, variable="ET", model_name="Ensemble",
                     depth_mm=MM_PER_AF_AT_80_ACRES, fetched_on=m)
        for p in parcels for m in months
    )
    return parcels


def _submission(report_type, period):
    template, _ = ReportTemplate.objects.get_or_create(
        report_type=report_type, defaults={"name": report_type, "is_active": True}
    )
    return ReportSubmission.objects.create(report_template=template, reporting_period=period, status="draft")


def _url(submission):
    return reverse("reporting:report_prefill", kwargs={"pk": submission.pk})


def _boxes(html):
    """``{field key: value}`` for every box the page shows."""
    return {f"{t}:{i}:{m}": v for t, i, m, v in VAL.findall(html)}


def _entity_ids(html):
    return sorted({int(i) for _, i, _, _ in VAL.findall(html)})


def _form_fields(html):
    """Every named field inside the page's form: what a Save posts."""
    form = html[html.index("<form"):html.rindex("</form>")]
    return re.findall(r'<(?:input|select|textarea|button)[^>]*\sname="([^"]+)"', form)


def _post_page(client, submission, html, changes=None, **extra):
    """Post the page as a browser would: every box shown, with ``changes`` typed in."""
    data = dict(_boxes(html))
    data = {f"val:{k}": v for k, v in data.items()}
    for key, value in (changes or {}).items():
        data[f"val:{key}"] = value
    for name in ("page", "q", "changed"):
        m = re.search(rf'<input[^>]*\sname="{name}"[^>]*\svalue="([^"]*)"', html)
        if m:
            data[name] = m.group(1)
    data.update(extra)
    return client.post(_url(submission), data)


def test_more_use_areas_than_a_page_holds_shows_one_page_and_a_way_to_the_next(office, period):
    parcels = _use_areas(30)
    submission = _submission("gears_by_et", period)

    html = office.get(_url(submission)).content.decode()

    assert _entity_ids(html) == sorted(p.pk for p in parcels[:25])
    assert re.search(r'name="goto"[^>]*value="2"', html), "no control leads to page 2"
    second = office.get(_url(submission), {"page": 2}).content.decode()
    assert _entity_ids(second) == sorted(p.pk for p in parcels[25:])


def test_a_search_finds_a_use_area_on_a_later_page(office, period):
    parcels = _use_areas(30)
    submission = _submission("gears_by_et", period)

    html = office.get(_url(submission), {"q": "MADEUP-029"}).content.decode()

    assert _entity_ids(html) == [parcels[28].pk]


def test_a_save_posts_fewer_than_1000_fields_at_a_size_that_was_refused(office, period):
    _use_areas(90, months=YEAR)  # 1,080 boxes on one page today
    submission = _submission("gears_by_et", period)

    html = office.get(_url(submission)).content.decode()

    assert len(_form_fields(html)) < 1000
    response = _post_page(office, submission, html, action="save")
    assert response.status_code == 200


def _post_boxes(client, submission, parcels, changes=None, **extra):
    """Post one page's boxes only (one acre-foot each, the figure shown), with ``changes`` typed in."""
    data = {f"val:parcel:{p.pk}:2024-01": "1.00" for p in parcels}
    data.update({f"val:{k}": v for k, v in (changes or {}).items()})
    data.update(extra)
    return client.post(_url(submission), data)


def test_a_save_from_one_page_keeps_a_change_saved_on_another(office, period):
    parcels = _use_areas(30)
    submission = _submission("gears_by_et", period)
    later = f"parcel:{parcels[28].pk}:2024-01"
    first = f"parcel:{parcels[0].pk}:2024-01"

    _post_boxes(office, submission, parcels[25:], {later: "7.50"}, page="2", action="save")
    _post_boxes(office, submission, parcels[:25], {first: "3.25"}, page="1", action="save")

    submission.refresh_from_db()
    assert submission.prefill_overrides == {later: "7.50", first: "3.25"}

    # The page-1 change set back to OpenET's figure is no longer a change; page 2's stays.
    _post_boxes(office, submission, parcels[:25], page="1", action="save")
    submission.refresh_from_db()
    assert submission.prefill_overrides == {later: "7.50"}


def test_an_unchanged_page_saves_nothing_even_with_a_change_elsewhere(office, period):
    parcels = _use_areas(30)
    submission = _submission("gears_by_et", period)
    later = f"parcel:{parcels[28].pk}:2024-01"
    submission.prefill_overrides = {later: "7.50"}
    submission.save(update_fields=["prefill_overrides"])

    _post_boxes(office, submission, parcels[:25], page="1", action="save")

    submission.refresh_from_db()
    assert submission.prefill_overrides == {later: "7.50"}


def test_turning_the_page_saves_the_page_in_view_and_shows_the_next(office, period):
    parcels = _use_areas(30)
    submission = _submission("gears_by_et", period)
    first = f"parcel:{parcels[0].pk}:2024-01"

    page1 = office.get(_url(submission)).content.decode()
    response = _post_page(office, submission, page1, {first: "4.00"}, goto="2")

    assert _entity_ids(response.content.decode()) == sorted(p.pk for p in parcels[25:])
    submission.refresh_from_db()
    assert submission.prefill_overrides == {first: "4.00"}


def test_a_saved_change_shows_wherever_its_use_area_is_listed(office, period):
    parcels = _use_areas(30)
    submission = _submission("gears_by_et", period)
    later = f"parcel:{parcels[28].pk}:2024-01"
    submission.prefill_overrides = {later: "7.50"}
    submission.save(update_fields=["prefill_overrides"])

    on_its_page = office.get(_url(submission), {"page": 2}).content.decode()
    searched = office.get(_url(submission), {"q": "MADEUP-029"}).content.decode()
    changed_only = office.get(_url(submission), {"changed": "1"}).content.decode()

    for html in (on_its_page, searched, changed_only):
        assert _boxes(html)[later] == "7.50"
        assert re.search(r'prefill-cell--changed[^>]*>\s*<input[^>]*val:' + re.escape(later), html)
    assert _entity_ids(changed_only) == [parcels[28].pk]
    assert later not in _boxes(office.get(_url(submission)).content.decode())


def test_wells_and_points_of_diversion_page_the_same_way(office, period):
    parcels = _use_areas(30)
    for i, parcel in enumerate(parcels, start=1):
        WellIrrigatedParcelFactory(well=WellFactory(name=f"MADEUP-WELL-{i:03d}"), parcel=parcel)
        PointOfDiversionParcelFactory(
            point_of_diversion=PointOfDiversionFactory(name=f"MADEUP-POD-{i:03d}"), parcel=parcel
        )

    for report_type, kind in (("gears_by_well", "well"), ("calwatrs_a2", "pod")):
        submission = _submission(report_type, period)
        html = office.get(_url(submission)).content.decode()
        assert {t for t, _, _, _ in VAL.findall(html)} == {kind}
        assert len(_entity_ids(html)) == 25, report_type
        assert re.search(r'name="goto"[^>]*value="2"', html), report_type
