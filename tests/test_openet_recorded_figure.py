# SPDX-License-Identifier: AGPL-3.0-or-later
"""OpenET's crop ET for a month is recorded once, with the date it was fetched.

What a correct site does (the plain write-up Brent approved, ruling 134):

* the first fetch of a month records its figure and the day it was fetched;
* the calculation and the ledger's ET estimate entry use only that record;
* a later fetch with a different figure changes nothing, and is shown beside it;
* a person who can correct records may accept the newer figure with a reason: the record
  and the month's ET estimate entry are replaced as corrections (the old ones kept, struck)
  and the month is recalculated at once;
* in a finalized year only an administrator may accept, through the recorded door;
* nobody can type an ET figure;
* rainfall is not covered, and stays visible as a strict xfail.

The worked example is the write-up's: a 100-acre corn field watered by sprinkler, with a
well. July 2025 fetched at 91.44 mm (3.60 in, 30.00 AF crop ET, 37.50 AF pumped); OpenET
later reports 121.92 mm (4.80 in, 40.00 AF, 50.00 AF pumped).

Every fetch goes through the site's own fetch command and the web-service writer, with the
service itself replaced by a fake answer, so the fetch day is stamped the way a site
stamps it. A month written into the cache by hand (no fetch) is how a test shows what the
calculation does with a month that has no record.
"""

import datetime as dt
import html
import json
import re
from decimal import Decimal as D
from io import BytesIO, StringIO
from unittest import mock

import pytest
from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

from accounting.models import CalculationRequest, CalculationRun, ReportingPeriod
from datasync.adapters.openet import OpenETAdapter
from datasync.models import OpenETCache
from parcels.models import ParcelLedger
from tests import ledger_districts as ld

pytestmark = pytest.mark.django_db

User = get_user_model()

JULY = "2025-07"
AUG_6 = dt.date(2025, 8, 6)
SEP_28 = dt.date(2025, 9, 28)
FIRST = {"2025-07": 91.44, "2025-08": 15.24, "2025-09": 15.24}
NEWER = {**FIRST, "2025-07": 121.92}
REASON = "OpenET revised July after the month settled"
FINALIZED_SENTENCE = "WY 2024-2025 is finalized"
#: The newer figure's band on the month page, as _words prints its figure and first sentence.
NOTICE = '<div class="budget-seg-value">40.00<span class="budget-seg-unit">AF</span></div>'
NOTICE_WORDS = "OpenET now reports a different figure for this month."
PILL = '<span class="kind-pill kind-pill--{0}">{1}</span>'



# ---------------------------------------------------------------- the site's pieces


def _figure_model():
    """The recorded figure's model, or None on a site that has none."""
    try:
        return apps.get_model("datasync", "CropETFigure")
    except LookupError:
        return None


def _figures(parcel, month=JULY):
    model = _figure_model()
    if model is None:
        return []
    first = dt.date(int(month[:4]), int(month[5:]), 1)
    return list(model.objects.filter(parcel=parcel, month=first).order_by("pk"))


def _recorded(parcel, month=JULY):
    """``(depth in mm, fetch day)`` of the month's current record, or None."""
    model = _figure_model()
    if model is None:
        return None
    first = dt.date(int(month[:4]), int(month[5:]), 1)
    row = model.objects.current().filter(parcel=parcel, month=first).first()
    return None if row is None else (row.depth_mm, row.fetched_on)


def _count():
    model = _figure_model()
    return None if model is None else model.objects.count()


def _corn_field(number="F4", lon=-120.49, well=True):
    """The write-up's field: 100 acres, corn, sprinkler, a well, no crop ET fetched yet."""
    if not ReportingPeriod.objects.exists():
        ld.seed_reference()
    zone = ld.make_zone(f"{number} GSA", "management_area", lon - 0.1, 37.1, lon + 0.1, 37.3)
    w = ld.make_well(f"{number} well", lon + 0.005, 37.21) if well else None
    return ld.add_field(number, 100, "Corn", "Sprinkler", [zone], lon, 37.2, [], w)


def _fetch(parcel, months_mm, on, start="2025-07-01", end="2025-09-30"):
    """Fetch through the site's command and the web-service writer, on the day ``on``.

    The cache row from an earlier fetch is first made older than the age at which the
    web service fetches a window again (30 days), as it is when someone fetches later.
    """
    OpenETCache.objects.filter(parcel=parcel, variable="ET").update(
        queried_at=timezone.now() - dt.timedelta(days=40)
    )
    answer = [{"time": f"{m}-01", "et": v} for m, v in sorted(months_mm.items())]
    out = StringIO()
    with (
        mock.patch.object(OpenETAdapter, "fetch_polygon", return_value=answer),
        mock.patch.object(OpenETAdapter, "_rate_limit"),
        mock.patch("django.utils.timezone.localdate", return_value=on),
    ):
        call_command(
            "sync_openet_parcels", "--start-date", start, "--end-date", end,
            "--parcel-prefix", parcel.parcel_number, stdout=out,
        )
    return out.getvalue()


def _hand_cache(parcel, months_mm, start, end, model="Ensemble", variable="ET", key="et"):
    """A cache row written by hand: no fetch, so no record."""
    return OpenETCache.objects.create(
        parcel=parcel, geometry=parcel.geometry, start_date=start, end_date=end,
        variable=variable, model_name=model, origin="fixture",
        et_data=[{"date": f"{m}-01", key: v} for m, v in sorted(months_mm.items())],
    )


def _sync():
    call_command(
        "sync_openet_to_ledger", "--start-date", "2025-07-01", "--end-date", "2025-09-30",
        stdout=StringIO(),
    )


def _estimate(parcel):
    return ParcelLedger.objects.current().get(
        parcel=parcel, source_type="et_estimate", effective_date__year=2025, effective_date__month=7,
    ).amount_acre_feet


def _run(parcel):
    return CalculationRun.objects.filter(parcel=parcel, period=JULY).order_by("-pk").first()


def _calculated_row(parcel):
    return ParcelLedger.objects.current().get(
        parcel=parcel, source_type="calculated", effective_date__year=2025, effective_date__month=7,
    ).amount_acre_feet


def _user(username, **flags):
    return User.objects.create_user(
        username=username, email=f"{username}@example.org", password="a-good-passw0rd",
        is_active=True, **flags,
    )


@pytest.fixture(autouse=True)
def _enforced(settings):
    settings.ACCESS_CONTROL_ENFORCED = True
    settings.OPENET_MODE = "api"


@pytest.fixture
def operator():
    return _user("operator", first_name="Jose", last_name="Lopez")


@pytest.fixture
def boss():
    return _user("boss", first_name="Ana", last_name="Reyes", agency_admin=True)


@pytest.fixture
def viewer():
    return _user("viewer", read_only=True)


def _client(user):
    client = Client()
    client.force_login(user)
    return client


def _words(response):
    return " ".join(html.unescape(response.content.decode()).replace("\xa0", " ").split())


def _page(user, parcel, month=JULY):
    return _words(
        _client(user).get(reverse("accounting:calculation_run_detail", args=[parcel.pk, month]))
    )


def _accept_url(parcel, month=JULY):
    try:
        return reverse("accounting:crop_et_accept", args=[parcel.pk, month])
    except NoReverseMatch:
        return f"/accounting/calculation-run/{parcel.pk}/{month}/accept/"


def _accept(user, parcel, reason=REASON, record=None):
    """Press Accept the newer figure; returns the page that follows."""
    if record is None:
        current = [r for r in _figures(parcel) if r.replaced_at is None and r.voided_at is None]
        record = current[0] if current else None
    data = {"reason": reason, "record": record.pk if record is not None else ""}
    return _client(user).post(_accept_url(parcel), data, follow=True)


def _fetched_twice(field):
    _fetch(field, FIRST, AUG_6)
    _sync()
    ld.run_months([JULY])
    _fetch(field, NEWER, SEP_28)
    _sync()
    ld.run_months([JULY])


def _finalize():
    ReportingPeriod.objects.filter(name="WY 2024-2025").update(is_finalized=True)


# ---------------------------------------------------------------- 2. the calculation reads the record


def test_the_calculation_reads_only_the_record_for_crop_et_and_the_rain_steps_et():
    from accounting.steps import et_gross, subtract_effective_precip

    field = _corn_field()
    _fetched_twice(field)
    _, gross = et_gross(D("0"), field, JULY, {}, {})
    _, rain = subtract_effective_precip(D("0"), field, JULY, {}, {})

    assert D(gross["detail"]["et_mm"]) == D("91.44")
    assert D(rain["detail"]["et_mm"]) == D("91.44")


def test_the_months_the_nightly_run_chooses_are_the_months_with_a_record():
    from accounting.engine_run import months_with_et_data

    field = _corn_field()
    _fetch(field, FIRST, AUG_6)
    _hand_cache(field, {"2025-10": 40.0}, dt.date(2025, 10, 1), dt.date(2025, 10, 31))

    assert months_with_et_data(dt.date(2025, 7, 1), dt.date(2025, 10, 31)) == {
        "2025-07", "2025-08", "2025-09",
    }


# ---------------------------------------------------------------- 3. the preview and the test run write nothing


def test_the_calculation_preview_writes_no_record(boss):
    field = _corn_field()
    _fetched_twice(field)
    assert _count() == 3

    response = _client(boss).get(
        reverse("accounting:methodology_preview"), {"parcel_id": field.pk, "period": JULY}
    )

    assert response.status_code == 200
    assert _count() == 3
    assert _recorded(field) == (D("91.44"), AUG_6)


def test_a_test_run_of_the_calculation_writes_no_record():
    field = _corn_field()
    _fetched_twice(field)
    assert _count() == 3

    call_command("run_calculations", "--period", JULY, "--dry-run", stdout=StringIO())

    assert _count() == 3
    assert _recorded(field) == (D("91.44"), AUG_6)


# ---------------------------------------------------------------- 4. a month with no record


def test_a_month_cached_by_hand_with_no_record_is_not_calculated():
    field = _corn_field()
    _fetch(field, FIRST, AUG_6)
    other = _corn_field("F5", -120.40)
    _hand_cache(other, FIRST, dt.date(2025, 7, 1), dt.date(2025, 9, 30))

    ld.run_months([JULY])

    assert _run(field) is not None
    assert _run(other) is None


# ---------------------------------------------------------------- 5. the fetch line


@pytest.mark.parametrize(
    ("fetched", "line"),
    [
        (AUG_6, "<span>OpenET satellite estimate, received Aug 6, 2025</span> " + PILL.format("provisional", "Provisional")),
        (dt.date(2025, 11, 28), "<span>OpenET satellite estimate, received Nov 28, 2025</span> " + PILL.format("provisional", "Provisional")),
        (dt.date(2025, 11, 29), "<span>OpenET satellite estimate, received Nov 29, 2025</span> " + PILL.format("final", "Final")),
    ],
)
def test_the_month_page_says_when_the_figure_was_fetched_and_whether_it_was_provisional(
    operator, fetched, line
):
    field = _corn_field()
    _fetch(field, {JULY: 91.44}, fetched, end="2025-07-31")
    ld.run_months([JULY])

    assert line in _page(operator, field)


def test_a_record_with_no_fetch_date_says_so(operator):
    field = _corn_field()
    ld.add_et(field, FIRST)
    ld.run_months([JULY])

    assert _recorded(field) == (D("91.44"), None)
    assert "<span>OpenET satellite estimate, date received not recorded</span></div>" in _page(operator, field)


# ---------------------------------------------------------------- 6. the newer figure on the page


def test_a_newer_figure_is_shown_beside_the_recorded_one_with_accept_for_a_writer(operator):
    field = _corn_field()
    _fetched_twice(field)

    page = _page(operator, field)

    assert NOTICE in page and NOTICE_WORDS in page
    assert "Accept the newer figure" in page
    assert 'name="reason"' in _words(
        _client(operator).get(
            reverse("accounting:calculation_run_detail", args=[field.pk, JULY]), {"open": "accept"}
        )
    )


def test_a_viewer_sees_the_newer_figure_and_no_accept(viewer):
    field = _corn_field()
    _fetched_twice(field)

    page = _page(viewer, field)

    assert NOTICE in page and NOTICE_WORDS in page
    assert "Accept the newer figure" not in page


# ---------------------------------------------------------------- 7. accepting


def test_an_operator_accepts_the_newer_figure_and_the_month_recalculates_at_once(operator):
    field = _corn_field()
    _fetched_twice(field)
    old_entry = ParcelLedger.objects.current().get(parcel=field, source_type="et_estimate", effective_date__month=7)

    response = _accept(operator, field)

    assert "Record corrected. OpenH2O recalculated Jul 2025." in _words(response)
    old, new = _figures(field)
    assert old.replaced_at is not None and old.depth_mm == D("91.44") and old.fetched_on == AUG_6
    assert (new.depth_mm, new.fetched_on, new.change_reason) == (D("121.92"), SEP_28, REASON)
    assert new.replaces_id == old.pk and new.created_by == operator
    old_entry.refresh_from_db()
    assert old_entry.replaced_at is not None and old_entry.amount_acre_feet == D("-30.0000")
    new_entry = ParcelLedger.objects.get(replaces=old_entry)
    assert (new_entry.amount_acre_feet, new_entry.change_reason) == (D("-40.0000"), REASON)
    run = _run(field)
    assert (run.gross_et_af, run.gw_extracted_af) == (D("40.0000"), D("50.0000"))


def test_after_accepting_the_page_shows_who_when_why_and_the_earlier_figure_struck(operator):
    field = _corn_field()
    _fetched_twice(field)
    _accept(operator, field)

    page = _page(operator, field)

    assert "<span>OpenET satellite estimate, received Sep 28, 2025</span> " + PILL.format("provisional", "Provisional") in page
    assert f"by J. Lopez: {REASON}" in page
    assert re.search(r'received Aug 6, 2025</span></span>\s*<b class="record-void-text">30\.00</b>', page)
    assert 'id="crop-et-newer"' not in page


def test_a_viewers_accept_writes_nothing(viewer):
    field = _corn_field()
    _fetched_twice(field)

    response = _accept(viewer, field)

    assert response.status_code == 403
    assert _recorded(field) == (D("91.44"), AUG_6)
    assert _run(field).gross_et_af == D("30.0000")


def test_a_reason_of_nine_characters_writes_nothing(operator):
    field = _corn_field()
    _fetched_twice(field)

    response = _accept(operator, field, reason="too short")

    assert "Give a reason of 10 to 500 characters." in _words(response)
    assert _recorded(field) == (D("91.44"), AUG_6)
    assert len(_figures(field)) == 1


def test_a_second_accept_of_a_replaced_record_writes_nothing(operator):
    field = _corn_field()
    _fetched_twice(field)
    assert len(_figures(field)) == 1
    first = _figures(field)[0]
    _accept(operator, field)

    response = _accept(operator, field, reason="pressed again by mistake", record=first)

    assert "This record has been corrected already." in _words(response)
    assert len(_figures(field)) == 2


# ---------------------------------------------------------------- 8. a finalized year


def test_in_a_finalized_year_the_newer_figure_shows_and_an_operators_accept_is_refused(operator):
    field = _corn_field()
    _fetched_twice(field)
    _finalize()

    assert NOTICE in _page(operator, field)
    response = _accept(operator, field)

    assert FINALIZED_SENTENCE in _words(response)
    assert _recorded(field) == (D("91.44"), AUG_6)
    assert len(_figures(field)) == 1
    assert _run(field).gross_et_af == D("30.0000")


def test_in_a_finalized_year_an_administrators_accept_goes_through_the_recorded_door(boss):
    field = _corn_field()
    _fetched_twice(field)
    _finalize()

    response = _accept(boss, field)

    assert "Record corrected." in _words(response)
    assert _recorded(field) == (D("121.92"), SEP_28)
    assert CalculationRequest.objects.order_by("-pk").first().override_reason == REASON
    assert _run(field).gross_et_af == D("40.0000")
    assert ReportingPeriod.objects.get(name="WY 2024-2025").is_finalized


# ---------------------------------------------------------------- 9. nobody types an ET figure

ET_REFUSAL = "ET estimate entries come from OpenET's recorded figure."


def test_the_hand_entry_form_refuses_an_et_estimate_entry():
    from accounting.forms import ParcelLedgerForm

    field = _corn_field()
    form = ParcelLedgerForm(data={
        "parcel": field.pk, "transaction_date": "2025-08-01", "effective_date": "2025-07-01",
        "amount_acre_feet": "-30", "source_type": "et_estimate", "description": "typed",
    })

    assert not form.is_valid()
    assert ET_REFUSAL in " ".join(form.errors.get("source_type", []))


def test_the_ledger_import_refuses_an_et_estimate_entry():
    from accounting.services import parse_ledger_csv

    field = _corn_field()
    text = (
        "parcel_number,effective_date,amount_acre_feet,source_type,description\n"
        f"{field.parcel_number},2025-07-01,-30,et_estimate,typed\n"
    )
    result = parse_ledger_csv(BytesIO(text.encode()))

    assert result["created_count"] == 0
    assert ET_REFUSAL in json.dumps(result["errors"])
    assert not ParcelLedger.objects.filter(parcel=field, source_type="et_estimate").exists()


def _admin_form(obj, data):
    from django.contrib import admin
    from django.test import RequestFactory

    request = RequestFactory().post("/")
    request.user = _user("site-admin", is_staff=True, is_superuser=True)
    model_admin = admin.site._registry[ParcelLedger]
    form_class = model_admin.get_form(request, obj, change=obj is not None)
    return model_admin, request, form_class(data=data, instance=obj)


def _admin_data(field, **over):
    data = {
        "parcel": field.pk, "transaction_date": "2025-08-01", "effective_date": "2025-07-01",
        "amount_acre_feet": "-30", "source_type": "et_estimate", "description": "typed",
    }
    data.update(over)
    return data


def test_the_administration_site_cannot_add_an_et_estimate_entry():
    field = _corn_field()
    _, _, form = _admin_form(None, _admin_data(field))

    assert not form.is_valid()
    assert ET_REFUSAL in " ".join(form.errors.get("source_type", []))


def test_the_administration_site_cannot_turn_another_entry_into_an_et_estimate():
    field = _corn_field()
    typed = ld.ledger(field, dt.date(2025, 7, 1), -5, "manual_entry", "GW")
    _, _, form = _admin_form(typed, _admin_data(field, amount_acre_feet="-5"))

    assert not form.is_valid()
    assert ET_REFUSAL in " ".join(form.errors.get("source_type", []))


def test_the_administration_site_cannot_change_an_et_estimate_entrys_amount():
    field = _corn_field()
    _fetch(field, FIRST, AUG_6)
    _sync()
    entry = ParcelLedger.objects.get(parcel=field, source_type="et_estimate", effective_date__month=7)
    model_admin, request, _ = _admin_form(entry, _admin_data(field, amount_acre_feet="-99"))

    assert {"amount_acre_feet", "source_type"} <= set(model_admin.get_readonly_fields(request, entry))


# ---------------------------------------------------------------- 10. the ledger's entry comes from the record


def test_the_ledger_sync_writes_the_et_estimate_entry_from_the_record_not_the_cache():
    field = _corn_field()
    _fetch(field, FIRST, AUG_6)
    _fetch(field, NEWER, SEP_28)

    _sync()

    assert _estimate(field) == D("-30.0000")


# ---------------------------------------------------------------- 11. two overlapping cache windows


def test_with_two_overlapping_windows_newest_is_read_the_way_the_calculation_reads_it(operator):
    field = _corn_field()
    older = _hand_cache(field, {JULY: 80.0}, dt.date(2025, 7, 1), dt.date(2025, 7, 31))
    OpenETCache.objects.filter(pk=older.pk).update(queried_at=timezone.now() - dt.timedelta(days=60))
    _fetch(field, FIRST, AUG_6)
    OpenETCache.objects.filter(pk=older.pk).update(queried_at=timezone.now() - dt.timedelta(days=60))

    assert _recorded(field) == (D("91.44"), AUG_6)

    OpenETCache.objects.filter(pk=older.pk).update(
        queried_at=timezone.now(),
        et_data=[{"date": "2025-07-01", "et": 121.92, "fetched": "2025-09-28"}],
    )
    ld.run_months([JULY])

    assert _run(field).gross_et_af == D("30.0000")
    assert NOTICE in _page(operator, field)


# ---------------------------------------------------------------- 12. the demonstration


def test_the_fixture_load_records_every_month_after_a_year_is_finalized_and_check_finds_no_change(
    tmp_path, boss
):
    from core import fingerprint

    field = _corn_field()
    ld.add_et(field, FIRST)
    ld.run_months([JULY, "2025-08", "2025-09"])
    year = ReportingPeriod.objects.get(name="WY 2024-2025")
    response = _client(boss).post(reverse("accounting:period_finalize", args=[year.pk]), {})
    assert response.status_code == 302
    year.refresh_from_db()
    other = _corn_field("F6", -120.30)
    fixture = tmp_path / "openet.json"
    fixture.write_text(json.dumps({"rows": [{
        "parcel_number": other.parcel_number, "start_date": "2024-10-01", "end_date": "2025-09-30",
        "variable": "ET", "model_name": "Ensemble", "source": "OpenET", "received": "2026-11-12",
        "et_data": [{"date": f"{m}", "et": v, "unit": "mm"} for m, v in FIRST.items()],
    }]}))

    call_command("load_openet_fixture", "--fixture", str(fixture), stdout=StringIO())

    # Each month is recorded at its figure and the day the file says it was received.
    assert [_recorded(other, m) for m in FIRST] == [
        (D(str(v)), dt.date(2026, 11, 12)) for v in FIRST.values()
    ]
    assert fingerprint.compute(year).digest == year.fingerprint


def test_the_recorded_figure_is_demonstration_content():
    from core import demonstration

    assert "datasync.CropETFigure" in demonstration.CONTENT_LABELS


# ---------------------------------------------------------------- 13. rainfall, not covered


@pytest.mark.xfail(
    strict=True,
    reason="Rainfall is not recorded this way: a re-fetched rain month still moves the "
    "calculation. It needs its own decision (ruling 134).",
)
def test_a_refetched_rain_month_leaves_the_calculation_as_it_was():
    from accounting.steps import subtract_effective_precip

    field = _corn_field()
    _fetch(field, FIRST, AUG_6)
    rain = _hand_cache(field, {JULY: 20.0}, dt.date(2025, 7, 1), dt.date(2025, 7, 31),
                       model="GRIDMET", variable="precip", key="precip")
    before, _ = subtract_effective_precip(D("30"), field, JULY, {}, {})
    OpenETCache.objects.filter(pk=rain.pk).update(et_data=[{"date": "2025-07-01", "precip": 40.0}])
    after, _ = subtract_effective_precip(D("30"), field, JULY, {}, {})

    assert after == before
