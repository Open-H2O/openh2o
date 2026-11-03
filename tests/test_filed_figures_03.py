# SPDX-License-Identifier: AGPL-3.0-or-later
"""A finalized year's figures stay as filed (151.7-03).

Finalizing writes down every figure the pages print for the year
(``accounting.statements``); a correction made later moves "Now" and the water
year page lists what moved and what moved it; reopening keeps the record and
finalizing again records a restated one. The tests work on the hand-checked
district D1 (``tests/ledger_districts.py``), whose July to September 2025 months
sit in WY 2024-2025.

* (a) finalizing writes one ``filed`` statement whose rows equal what the page
  functions return, for every use area and month, account, zone and the district;
* (b) an administrator's correction inside the finalized year moves "Now", the
  moved figures are exactly the ones that differ, the correction is named, and the
  figures route shows them;
* (c) reopening keeps the statement, finalizing again records a ``restated`` one,
  and the card shows As filed, Restated and Now;
* (d) the upgrade records one ``recorded_at_upgrade`` statement for a finalized year
  with none, none for an open one, with the two notes;
* (e) the account and use area lines appear only when a figure differs and name only
  the ones that moved;
* (f) a statement row is never updated, is not inserted or deleted in a finalized
  year, and both tables keep Change history;
* (g) a viewer reads the card and the figures route.
"""
import datetime as dt
from decimal import ROUND_HALF_UP
from decimal import Decimal as D
from unittest import mock

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import DatabaseError, connection, transaction
from django.test import Client
from django.urls import reverse

from accounting import statements
from accounting.engine_run import request_for_months
from accounting.locks import override
from accounting.models import (
    AllocationPlan,
    PeriodStatement,
    PeriodStatementEvent,
    PeriodStatementRow,
    PeriodStatementRowEvent,
    ReportingPeriod,
    WaterAccount,
    WaterType,
)
from accounting.services import (
    account_consumptive_balance,
    account_groundwater_budget,
    parcel_consumptive_balance,
    parcel_run_periods,
    parcel_water_use_months,
    zone_consumptive_balance,
    zone_groundwater_budget,
)
from accounting.views import dashboard
from core.corrections import correct
from core.modules import is_enabled
from geography.models import Zone
from parcels.models import Parcel, ParcelLedger
from tests import ledger_districts as ld
from tests.factories import ReportingPeriodFactory

pytestmark = pytest.mark.django_db

User = get_user_model()

REASON = "Typed 30 for 20; the meter photo shows 20."
REOPEN_REASON = "Reopened to record the corrected July reading."
FOUR = D("0.0001")


# -- Setup -----------------------------------------------------------------------------------


def _user(username, **flags):
    return User.objects.create_user(
        username=username, email=f"{username}@example.org", password="a-good-passw0rd",
        is_active=True, **flags,
    )


@pytest.fixture
def administrator():
    return _user("filer", agency_admin=True, first_name="Rae", last_name="Ortiz")


@pytest.fixture
def viewer():
    return _user("reader", read_only=True)


def _client(user):
    client = Client()
    client.force_login(user)
    return client


@pytest.fixture
def d1():
    """D1 with the three months calculated, in a year that is still open."""
    ld.seed_reference()
    built = ld.build_d1()
    ld.run_months(["2025-07", "2025-08", "2025-09"])
    return built


@pytest.fixture
def year(d1):
    return ReportingPeriod.objects.get(name="WY 2024-2025")


def _finalize(client, period):
    response = client.post(reverse("accounting:period_finalize", args=[period.pk]), {})
    assert response.status_code == 302
    period.refresh_from_db()
    assert period.is_finalized


def _reopen(client, period):
    response = client.post(
        reverse("accounting:period_finalize", args=[period.pk]), {"note": REOPEN_REASON}
    )
    assert response.status_code == 302
    period.refresh_from_db()
    assert not period.is_finalized


def _correct_july(d1, administrator, to="-20.0000"):
    """Correct F1's July meter-reading entry from -30 to ``to`` inside the finalized year, then recalculate."""
    row = ParcelLedger.objects.current().get(
        parcel=d1["F1"], source_type="meter_reading", effective_date=dt.date(2025, 7, 1)
    )
    with override(REASON):
        months = correct(row, user=administrator, reason=REASON, changes={"amount_acre_feet": D(to)})
    request_for_months("record_corrected", months, requested_by=administrator, reason=REASON)
    return row


def _rows(statement):
    return {
        (r.scope, r.scope_id, r.month, r.figure, r.detail): r.value for r in statement.rows.all()
    }


def _q4(value):
    return None if value is None else D(value).quantize(FOUR, rounding=ROUND_HALF_UP)


def _page_figures(period):
    """Every figure D1's pages print for ``period``, read straight off the page functions."""
    found = {}
    surface_on = is_enabled("surface")
    for parcel in Parcel.objects.current():
        if not parcel_run_periods(parcel, period):
            continue
        has_well = parcel.wellirrigatedparcel_set.exists()
        use = parcel_water_use_months(parcel, period, with_groundwater=has_well)
        balance = parcel_consumptive_balance(parcel, period)
        columns = [("crop_et", "et")]
        if surface_on:
            columns.append(("surface_delivered", "surface"))
        if has_well:
            columns.append(("groundwater_extraction", "groundwater"))
        columns.append(("effective_precipitation", "precip"))
        for cell in use["months"]:
            for figure, column in columns:
                found[("use_area", parcel.pk, cell["month"], figure, "")] = cell[column]
        for figure, column in columns:
            found[("use_area", parcel.pk, None, figure, "")] = use["totals"][column]
        found[("use_area", parcel.pk, None, "supplies", "")] = balance["supply_total"]
        found[("use_area", parcel.pk, None, "uses", "")] = balance["uses_total"]
        found[("use_area", parcel.pk, None, "water_not_consumed", "")] = balance["water_not_consumed"]
        found[("use_area", parcel.pk, None, "balance", "")] = balance["net_vs_supply"]

    for account in WaterAccount.objects.filter(status="active"):
        cu = account_consumptive_balance(account, reporting_period=period)
        for figure, value in (
            ("crop_et", cu["consumptive_use_gross"]),
            ("surface_delivered", cu["supplies"]["surface"]),
            ("groundwater_extraction", cu["supplies"]["groundwater"]),
            ("effective_precipitation", cu["supplies"]["precip"]),
            ("supplies", cu["supply_total"]),
            ("uses", cu["uses_total"]),
            ("water_not_consumed", cu["water_not_consumed"]),
            ("balance", cu["net_vs_supply"]),
        ):
            found[("account", account.pk, None, figure, "")] = value
        budget = account_groundwater_budget(account, period)
        if budget["allocation"] is not None or budget["credits"]:
            if budget["allocation"] is not None:
                found[("account", account.pk, None, "allocation", "")] = budget["allocation"]
            for credit in budget["credits"]:
                found[("account", account.pk, None, "credit", credit.description)] = credit.amount_af
            found[("account", account.pk, None, "used", "")] = budget["used"]
            if budget["remaining"] is not None:
                found[("account", account.pk, None, "remaining", "")] = budget["remaining"]

    for zone in Zone.objects.all():
        zcu = zone_consumptive_balance(zone, reporting_period=period)
        measured = zcu["calculation_runs"] > 0
        budget = zone_groundwater_budget(zone, period)
        values = {
            "crop_et": zcu["consumptive_use_gross"] if measured else None,
            "surface_delivered": zcu["supplies"]["surface"],
            "groundwater_extraction": zcu["supplies"]["groundwater"],
            "effective_precipitation": zcu["supplies"]["precip"],
            "supplies": zcu["supply_total"],
            "water_not_consumed": zcu["water_not_consumed"] if measured else None,
            "balance": zcu["net_vs_supply"] if measured else None,
        }
        if budget["allocation"] is not None:
            values["allocation"] = budget["allocation"]
            values["carryover"] = budget["carryover"]
            values["remaining"] = budget["remaining"] if measured else None
            values["available"] = budget["available"]
            values["used"] = budget["used"]
        for figure, value in values.items():
            found[("zone", zone.pk, None, figure, "")] = value

    has_allocations = AllocationPlan.objects.filter(reporting_period=period).exists()
    rollup = dashboard._account_rollup(
        period, has_allocations, WaterType.objects.filter(code__iexact="GW").first()
    )
    for figure, key in (
        ("crop_et", "grand_consumptive_use"),
        ("surface_delivered", "grand_supply_surface"),
        ("groundwater_extraction", "grand_supply_groundwater"),
        ("effective_precipitation", "grand_supply_precip"),
        ("supplies", "grand_supply_total"),
        ("uses", "grand_uses_total"),
        ("water_not_consumed", "grand_not_consumed"),
        ("balance", "grand_net"),
    ):
        found[("site", None, None, figure, "")] = rollup[key]
    return {key: _q4(value) for key, value in found.items()}


# -- (a) finalizing writes the figures the pages print ------------------------------------------


def test_finalizing_writes_one_filed_statement_equal_to_the_page_functions(d1, year, administrator):
    expected = _page_figures(year)
    assert expected, "D1 prints figures"

    _finalize(_client(administrator), year)

    assert PeriodStatement.objects.filter(period=year).count() == 1
    statement = PeriodStatement.objects.get(period=year)
    assert (statement.kind, statement.taken_by) == ("filed", administrator)
    stored = _rows(statement)
    assert stored == expected
    # Every use area with a run, each of its twelve months, the accounts, the zone and the district.
    scopes = {(scope, scope_id) for scope, scope_id, *_ in stored}
    assert ("site", None) in scopes
    assert {("use_area", d1[name].pk) for name in ("F1", "F2", "F3", "F4") if (
        "use_area", d1[name].pk, None, "balance", "") in stored} <= scopes
    assert {("account", a.pk) for a in WaterAccount.objects.all()} <= scopes
    assert ("zone", d1["gsa"].pk) in scopes
    months = {m for scope, sid, m, fig, _ in stored if scope == "use_area" and m is not None}
    assert months == {dt.date(2024 + (i + 9) // 12, (i + 9) % 12 + 1, 1) for i in range(12)}
    # The rows carry the year they belong to and the method of the runs behind a run figure.
    assert {r.period_id for r in statement.rows.all()} == {year.pk}
    run_rows = statement.rows.filter(scope="use_area", figure="crop_et", month__isnull=True)
    assert run_rows.exists() and all(r.method for r in run_rows if r.value)


def test_a_figure_read_back_equals_the_figure_read_now(d1, year, administrator):
    _finalize(_client(administrator), year)
    statement = PeriodStatement.objects.get(period=year)
    assert statements.moved_figures(year).figure_count == 0
    assert [f.key for f in statements.statement_figures(statement)] == [
        f.key for f in statements.figures_now(year)
    ]


# -- (b) a correction inside the finalized year moves Now ---------------------------------------------


def test_a_correction_moves_now_and_the_moved_figures_name_it(d1, year, administrator):
    client = _client(administrator)
    _finalize(client, year)
    filed = _rows(PeriodStatement.objects.get(period=year))
    assert statements.moved_figures(year).figure_count == 0

    _correct_july(d1, administrator)

    now = {f.key: f.value for f in statements.figures_now(year)}
    assert set(now) == set(filed)
    differ = {
        key for key in filed
        if (filed[key] is None) != (now[key] is None)
        or (filed[key] is not None
            and filed[key].quantize(D("0.01"), ROUND_HALF_UP) != now[key].quantize(D("0.01"), ROUND_HALF_UP))
    }
    assert differ
    # The July pumping of F1 is among them, and a use area the correction never reached is not.
    july = ("use_area", d1["F1"].pk, dt.date(2025, 7, 1), "groundwater_extraction", "")
    assert july in differ
    assert filed[july] == D("30.0000") and now[july] == D("20.0000")
    assert not any(key[0] == "use_area" and key[1] == d1["F4"].pk for key in differ)

    comparison = statements.moved_figures(year)
    listed = {
        (group.scope, group.scope_id, row.label): (row.filed, row.now)
        for group in comparison.groups for row in group.rows
    }
    assert comparison.figure_count == len(differ) == len(listed)
    assert comparison.restated is False
    assert comparison.correction_count == 1
    assert comparison.summary == (
        f"Since then 1 correction moved {len(differ)} figures. Acre-feet."
    )
    assert listed[("use_area", d1["F1"].pk, "Groundwater extraction, Jul 2025")] == (
        D("30.0000"), D("20.0000")
    )
    # Places in the drawing's order: an account then its use areas, the zone, the district.
    order = [(g.scope, g.heading) for g in comparison.groups]
    assert order[-1] == ("site", "")
    assert order.index(("zone", "Zone")) < order.index(("site", ""))
    assert order.index(("account", "Account")) < order.index(("use_area", "Use area"))
    correction = comparison.single_correction
    assert correction.label == "Ledger entry"
    assert correction.rest.endswith(f" by R. Ortiz: {REASON}")
    assert " corrected " in correction.rest
    for group in comparison.groups:
        assert [c.identity for c in group.corrections] == [correction.identity]
        assert group.moved_words == ""


def test_the_figures_route_shows_what_moved(d1, year, administrator):
    client = _client(administrator)
    _finalize(client, year)
    _correct_july(d1, administrator)

    response = client.get(reverse("accounting:period_figures", args=[year.pk]), HTTP_HX_REQUEST="true")
    body = response.content.decode()

    assert response.status_code == 200
    assert 'id="figures-summary" hx-swap-oob="true">Since then 1 correction moved ' in body
    assert "Groundwater extraction, Jul 2025" in body
    assert ">30.00<" in body and ">20.00<" in body
    assert "Ledger entry</a> corrected " in body and REASON in body
    assert "<th>Figure</th>" in body and "As filed" in body and "Restated" not in body
    assert ">F1</a>" in body and ">All active accounts</a>" in body

    # Opened by address, without scripts, it is the water year page with the comparison in place.
    page = client.get(reverse("accounting:period_figures", args=[year.pk])).content.decode()
    assert 'id="figures-as-filed"' in page and "Groundwater extraction, Jul 2025" in page
    assert "hx-get" not in page.split('id="figures-as-filed"')[1].split("Allocations")[0]


def test_the_comparison_is_kept_until_a_record_changes(d1, year, administrator):
    client = _client(administrator)
    _finalize(client, year)
    url = reverse("accounting:period_figures", args=[year.pk])
    with mock.patch("accounting.statements.moved_figures", wraps=statements.moved_figures) as spy:
        client.get(url, HTTP_HX_REQUEST="true")
        client.get(url, HTTP_HX_REQUEST="true")
        assert spy.call_count == 1
        _correct_july(d1, administrator)
        body = client.get(url, HTTP_HX_REQUEST="true").content.decode()
        assert spy.call_count == 2
    assert "Since then 1 correction moved " in body


def test_a_year_with_nothing_moved_says_so(d1, year, administrator):
    client = _client(administrator)
    _finalize(client, year)
    page = client.get(reverse("accounting:period_detail", args=[year.pk])).content.decode()
    assert "Figures as filed" in page
    assert "Filed " in page and " by R. Ortiz." in page
    assert 'hx-get="' + reverse("accounting:period_figures", args=[year.pk]) + '"' in page
    assert "OpenH2O is comparing the figures with the ones filed." in page
    body = client.get(
        reverse("accounting:period_figures", args=[year.pk]), HTTP_HX_REQUEST="true"
    ).content.decode()
    assert ">No figure has moved since.<" in body
    assert "<table" not in body


def test_a_move_no_correction_explains_says_when_it_was_recalculated(d1, year, administrator):
    _finalize(_client(administrator), year)
    with override("a test of a move with no correction"):
        ParcelLedger.objects.filter(
            parcel=d1["F1"], source_type="meter_reading", effective_date=dt.date(2025, 7, 1)
        ).update(amount_acre_feet=D("-20.0000"))
    comparison = statements.moved_figures(year)
    assert comparison.figure_count > 0
    assert comparison.correction_count == 0
    assert comparison.summary == f"Since then {comparison.figure_count} figures moved. Acre-feet."
    assert {g.moved_words for g in comparison.groups} == {"Moved since the figures were filed."}


# -- (c) reopening keeps the record, finalizing again restates --------------------------------------------


def test_reopening_keeps_the_statement_and_finalizing_again_restates(d1, year, administrator):
    client = _client(administrator)
    _finalize(client, year)
    first = PeriodStatement.objects.get(period=year)
    first_rows = _rows(first)
    _correct_july(d1, administrator)

    _reopen(client, year)
    assert list(PeriodStatement.objects.filter(period=year)) == [first]
    assert _rows(first) == first_rows

    _finalize(client, year)
    second = PeriodStatement.objects.filter(period=year).order_by("pk")[1]
    assert (second.kind, second.taken_by) == ("restated", administrator)
    assert PeriodStatement.objects.filter(period=year).count() == 2
    assert _rows(first) == first_rows  # the filed figures never change

    july = ("use_area", d1["F1"].pk, dt.date(2025, 7, 1), "groundwater_extraction", "")
    assert _rows(second)[july] == D("20.0000")

    comparison = statements.moved_figures(year)
    assert comparison.restated is True
    row = next(
        r for g in comparison.groups for r in g.rows if r.label == "Groundwater extraction, Jul 2025"
    )
    assert (row.filed, row.restated, row.now) == (D("30.0000"), D("20.0000"), D("20.0000"))
    assert comparison.correction_count == 1

    page = client.get(
        reverse("accounting:period_figures", args=[year.pk]), HTTP_HX_REQUEST="true"
    ).content.decode()
    assert "<th class=\"th-right\">Restated</th>" in page
    detail = client.get(reverse("accounting:period_detail", args=[year.pk])).content.decode()
    assert " Restated " in detail and " by R. Ortiz." in detail.split("Restated ", 1)[1][:60]


def test_a_correction_inside_a_finalized_year_takes_no_statement(d1, year, administrator):
    _finalize(_client(administrator), year)
    _correct_july(d1, administrator)
    assert PeriodStatement.objects.filter(period=year).count() == 1


# -- (d) the upgrade ----------------------------------------------------------------------------------


def _finalized(name, start, end, finalized_at=None):
    period = ReportingPeriodFactory(name=name, start_date=start, end_date=end)
    ReportingPeriod.objects.filter(pk=period.pk).update(is_finalized=True, finalized_at=finalized_at)
    period.refresh_from_db()
    return period


def test_the_upgrade_records_a_statement_for_each_finalized_year_with_none():
    dated = _finalized(
        "WY 2020-2021", dt.date(2020, 10, 1), dt.date(2021, 9, 30),
        dt.datetime(2021, 10, 15, 19, 0, tzinfo=dt.timezone.utc),
    )
    undated = _finalized("WY 2021-2022", dt.date(2021, 10, 1), dt.date(2022, 9, 30))
    kept = _finalized("WY 2022-2023", dt.date(2022, 10, 1), dt.date(2023, 9, 30))
    with override("a test"):
        existing = statements.take_statement(kept, kind="filed", note="")
    open_year = ReportingPeriodFactory(
        name="WY 2023-2024", start_date=dt.date(2023, 10, 1), end_date=dt.date(2024, 9, 30)
    )

    taken = statements.record_upgrade_statements()

    assert sorted(s.period.name for s in taken) == ["WY 2020-2021", "WY 2021-2022"]
    only = PeriodStatement.objects.get(period=dated)
    assert (only.kind, only.taken_by) == ("recorded_at_upgrade", None)
    assert only.note == (
        "Recorded when OpenH2O began keeping filed figures; the year was finalized Oct 15, 2021."
    )
    assert PeriodStatement.objects.get(period=undated).note == (
        "Recorded when OpenH2O began keeping filed figures. "
        "The date this year was finalized is not on record."
    )
    assert list(PeriodStatement.objects.filter(period=kept)) == [existing]
    assert not PeriodStatement.objects.filter(period=open_year).exists()
    assert PeriodStatement.objects.get(period=dated).rows.exists()
    # The change history says why: the recorded door and its reason.
    event = PeriodStatementEvent.objects.filter(pgh_obj_id=only.pk, pgh_label="insert").get()
    assert event.pgh_context.metadata["override"] is True
    assert event.pgh_context.metadata["reason"] == statements.UPGRADE_REASON

    assert statements.record_upgrade_statements() == []


def test_the_upgrade_does_nothing_on_an_empty_database():
    assert statements.record_upgrade_statements() == []
    call_command("record_filed_figures")
    assert not PeriodStatement.objects.exists()


def test_the_card_prints_the_upgrade_line_as_drawn():
    now = dt.datetime.now(dt.timezone.utc)
    undated = _finalized("WY 2021-2022", dt.date(2021, 10, 1), dt.date(2022, 9, 30))
    dated = _finalized("WY 2020-2021", dt.date(2020, 10, 1), dt.date(2021, 9, 30), now)
    statements.record_upgrade_statements()
    day = statements._day(PeriodStatement.objects.get(period=undated).taken_at)
    assert statements.first_line(undated) == (
        f"Recorded {day}, when OpenH2O began keeping filed figures. "
        "The date this year was finalized is not on record."
    )
    assert statements.first_line(dated) == (
        f"Recorded {day}, when OpenH2O began keeping filed figures; "
        f"the year was finalized {statements._day(now)}."
    )


# -- (e) the lines on the account and use area pages ------------------------------------------------------


def _line_for(period, scope, scope_id, current):
    return statements.filed_line_context(period, scope, scope_id, current)


def test_the_lines_appear_only_when_a_figure_differs_and_name_only_the_moved_ones(
    d1, year, administrator
):
    client = _client(administrator)
    account_a = WaterAccount.objects.get(account_number="D1-A")
    account_b = WaterAccount.objects.get(account_number="D1-B")
    def account_url(account):
        return reverse("accounting:account_detail", args=[account.pk]) + f"?period={year.pk}"

    def area_url(parcel):
        return reverse("parcels:detail", args=[parcel.pk]) + f"?period={year.pk}"

    _finalize(client, year)
    for page in (account_url(account_a), area_url(d1["F1"])):
        assert "As filed for" not in client.get(page).content.decode()

    stored = _rows(PeriodStatement.objects.get(period=year))
    _correct_july(d1, administrator)

    # The words the line must carry: the figures of the band that moved, in the band's order.
    cu = account_consumptive_balance(account_a, reporting_period=year)
    now = {"supplies": cu["supply_total"], "uses": cu["uses_total"], "balance": cu["net_vs_supply"]}
    moved = [
        name for name in ("supplies", "uses", "balance")
        if _q4(now[name]).quantize(D("0.01"), ROUND_HALF_UP)
        != stored[("account", account_a.pk, None, name, "")].quantize(D("0.01"), ROUND_HALF_UP)
    ]
    assert moved
    expected = ", ".join(
        f"{name} {stored[('account', account_a.pk, None, name, '')].quantize(D('0.01'), ROUND_HALF_UP):,.2f}"
        for name in moved
    )
    body = client.get(account_url(account_a)).content.decode()
    assert f"WY 2024-2025</a>: {expected} AF." in body
    assert "As filed for" in body
    # The other account's page carries none: nothing of its own moved.
    assert "As filed for" not in client.get(account_url(account_b)).content.decode()

    use = parcel_consumptive_balance(d1["F1"], year)
    moved_area = [
        name for name, value in (
            ("supplies", use["supply_total"]), ("uses", use["uses_total"]), ("balance", use["net_vs_supply"]),
        )
        if _q4(value).quantize(D("0.01"), ROUND_HALF_UP)
        != stored[("use_area", d1["F1"].pk, None, name, "")].quantize(D("0.01"), ROUND_HALF_UP)
    ]
    assert moved_area
    area_body = client.get(area_url(d1["F1"])).content.decode()
    assert "As filed for" in area_body
    assert area_body.count("As filed for") == 1
    assert "As filed for" not in client.get(area_url(d1["F4"])).content.decode()
    # An equal figure is never named.
    unmoved = {"supplies", "uses", "balance"} - set(moved)
    for name in unmoved:
        assert f", {name} " not in body.split("As filed for", 1)[1].split("</p>", 1)[0]


def test_the_line_says_restated_when_the_newest_statement_is_a_restatement(d1, year, administrator):
    client = _client(administrator)
    _finalize(client, year)
    _correct_july(d1, administrator)
    _reopen(client, year)
    _finalize(client, year)
    # Move the year again so the page differs from the restated figures.
    _correct_july(d1, administrator, to="-12.0000")
    account_a = WaterAccount.objects.get(account_number="D1-A")
    body = client.get(
        reverse("accounting:account_detail", args=[account_a.pk]) + f"?period={year.pk}"
    ).content.decode()
    assert "As restated for" in body and "As filed for" not in body


# -- (f) the rows are locked and tracked -----------------------------------------------------------------


def _refused(action):
    with pytest.raises(DatabaseError) as raised, transaction.atomic():
        action()
    return raised.value


def test_a_statement_row_is_never_updated_and_is_not_added_or_removed_in_a_finalized_year():
    year = ReportingPeriodFactory(
        name="WY 2020-2021", start_date=dt.date(2020, 10, 1), end_date=dt.date(2021, 9, 30)
    )
    statement = statements.take_statement(year, kind="filed")
    row = statement.rows.first()
    assert row is not None

    # Never updated, whatever the year's state.
    for target in (row, statement):
        error = _refused(lambda t=target: type(t).objects.filter(pk=t.pk).update(id=t.pk))
        assert "Cannot update rows" in str(error)
    error = _refused(lambda: PeriodStatementRow.objects.filter(pk=row.pk).update(value=D("1")))
    assert "Cannot update rows" in str(error)

    ReportingPeriod.objects.filter(pk=year.pk).update(is_finalized=True)
    refusal = "WY 2020-2021 is finalized. An administrator can reopen it on the water year page."
    error = _refused(lambda: PeriodStatementRow.objects.filter(pk=row.pk).delete())
    assert refusal in str(error)
    error = _refused(
        lambda: PeriodStatementRow.objects.create(
            statement=statement, period=year, scope="site", figure="balance", value=D("1")
        )
    )
    assert refusal in str(error)
    error = _refused(lambda: statements.take_statement(year, kind="restated"))
    assert refusal in str(error)
    assert PeriodStatementRow.objects.filter(pk=row.pk).exists()

    # The recorded door lets an insert or a delete through, never an update.
    with override("a test of the recorded door"):
        added = statements.take_statement(year, kind="restated")
        assert "Cannot update rows" in str(
            _refused(lambda: PeriodStatementRow.objects.filter(pk=row.pk).update(value=D("2")))
        )
        added.rows.all().delete()
        added.delete()


def test_both_tables_keep_change_history():
    year = ReportingPeriodFactory(
        name="WY 2020-2021", start_date=dt.date(2020, 10, 1), end_date=dt.date(2021, 9, 30)
    )
    statement = statements.take_statement(year, kind="filed")
    assert list(
        PeriodStatementEvent.objects.filter(pgh_obj_id=statement.pk).values_list("pgh_label", flat=True)
    ) == ["insert"]
    count = statement.rows.count()
    assert count > 0
    assert PeriodStatementRowEvent.objects.filter(pgh_label="insert").count() == count
    from accounting.locks import LOCKED_MODELS

    assert "accounting.PeriodStatement" in LOCKED_MODELS and "accounting.PeriodStatementRow" in LOCKED_MODELS
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM pg_trigger WHERE tgname LIKE 'pgtrigger_never_updated_%%'"
        )
        assert cursor.fetchone()[0] == 2


# -- (g) a viewer reads the card ---------------------------------------------------------------------------


def test_a_viewer_reads_the_card_and_the_figures_route(d1, year, administrator, viewer):
    _finalize(_client(administrator), year)
    _correct_july(d1, administrator)
    client = _client(viewer)

    page = client.get(reverse("accounting:period_detail", args=[year.pk]))
    assert page.status_code == 200
    body = page.content.decode()
    assert 'id="figures-as-filed"' in body
    assert "Figures as filed" in body
    assert " by R. Ortiz." in body
    # The page offers the viewer no finalize or reopen control.
    assert "Reopen water year" not in body

    route = client.get(reverse("accounting:period_figures", args=[year.pk]), HTTP_HX_REQUEST="true")
    assert route.status_code == 200
    assert "Groundwater extraction, Jul 2025" in route.content.decode()
    assert client.get(reverse("accounting:period_figures", args=[year.pk])).status_code == 200


def test_the_card_sits_after_the_reopen_card_for_an_administrator_and_after_calculation_for_others(
    d1, year, administrator, viewer
):
    _finalize(_client(administrator), year)
    url = reverse("accounting:period_detail", args=[year.pk])
    admin_page = _client(administrator).get(url).content.decode()
    assert admin_page.index("Reopen this water year") < admin_page.index('id="figures-as-filed"')
    assert admin_page.index('id="figures-as-filed"') < admin_page.index(">Allocations</h2>")
    other = _client(viewer).get(url).content.decode()
    assert other.index(">Calculation</h2>") < other.index('id="figures-as-filed"')


def test_a_year_with_no_statement_shows_no_card_and_the_route_is_not_found(d1, year, administrator):
    client = _client(administrator)
    page = client.get(reverse("accounting:period_detail", args=[year.pk])).content.decode()
    assert "Figures as filed" not in page
    assert client.get(reverse("accounting:period_figures", args=[year.pk])).status_code == 404
