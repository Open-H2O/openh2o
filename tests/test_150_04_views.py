# SPDX-License-Identifier: AGPL-3.0-or-later
"""150-04, class VIEW: what a view hands its template, and what the template
then shows (page-verdict/LAYOUT-INVENTORY-150-04.md, rows V1 to V11 and T1).

  V1   the diversion preview's identical row errors are one line per cause
  V2   the production preview lists the file's rows, the first 50 at most
  V3   the lab-file preview says the regulating-agency line the commit will
  V4   a filtered empty list offers "Clear the search" to the bare list
  V6   a list with no records at all has no map card (and no head)
  V7   a negative-zero total prints 0.00 (a pin: see its docstring)
  V9   "Where the water went" only for a point with a direct-use record
  V10  the ledger footer sums by source type, never by sign
  T1   the ledger footer's figures can wrap (no nowrap cell)
  V11  the surface-district zone names carry a colon, not an em dash

Every test's docstring names the assertion that was red before its change.
"""
import importlib
import re
from datetime import date
from decimal import Decimal
from urllib.parse import urlencode

import factory
import pytest
from django.contrib.auth.hashers import make_password
from django.core.files.uploadedfile import SimpleUploadedFile
from django.template import Context, Template
from django.test import Client
from django.urls import reverse

from tests.factories import (
    ParcelFactory,
    ParcelLedgerFactory,
    PointOfDiversionFactory,
    RechargeSiteFactory,
    ReportingPeriodFactory,
    SamplingPointFactory,
    SystemFacilityFactory,
    WaterRightFactory,
    WellFactory,
    ZoneFactory,
)

# The lab-file fixtures V3 reads, reused rather than copied: the real seeded
# analyte vocabulary and the 30-row file whose rows all say "District 99".
from tests.test_drinking_import import _csv_file, fixture_text, parsed, system  # noqa: F401

pytestmark = pytest.mark.django_db


class _UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"v150reader{n}")
    email = factory.Sequence(lambda n: f"v150reader{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True


@pytest.fixture
def auth_client(db):
    c = Client()
    c.force_login(_UserFactory())
    return c


# ---------------------------------------------------------------------------
# V1: one line per cause on the diversion preview
# ---------------------------------------------------------------------------

# The state's Water Use Reported layout, twelve months of one right, every
# month inside the October 2023 to September 2024 water year (the same shape
# as tests/test_diversion_import.py's STATE_CSV_TEXT, built here so this file
# does not depend on that module's constants).
_MONTHS = [
    (1, "2024-01"), (2, "2024-02"), (3, "2024-03"), (4, "2024-04"),
    (5, "2024-05"), (6, "2024-06"), (7, "2024-07"), (8, "2024-08"),
    (9, "2024-09"), (10, "2023-10"), (11, "2023-11"), (12, "2023-12"),
]
STATE_CSV_TEXT = (
    "APPL_ID,WATER_RIGHT_ID,YEAR,MONTH,MONTH NAME,MONTH FORMATTED,DIVERSION_TYPE,AMOUNT,calendar_month\n"
    + "".join(
        f"V150A1,283,2024,{m},M{m},{m}/1/2024,DIRECT,{10 + m},{cal}\n"
        for m, cal in _MONTHS
    )
)


def test_v1_a_file_all_in_a_finalized_year_shows_the_message_once_with_its_count(auth_client):
    """Red before: ``body.count(message) == 1`` (it was 12, one table row per
    refused month, each carrying the same sentence)."""
    period = ReportingPeriodFactory(name="WY V150 2023-2024", is_finalized=True)
    right = WaterRightFactory(right_id="V150A1")
    point = PointOfDiversionFactory(water_right=right, name="V150A1_01", status="active")
    upload = SimpleUploadedFile("all-finalized.csv", STATE_CSV_TEXT.encode(), content_type="text/csv")

    resp = auth_client.post(
        reverse("surface:diversion_import_preview"), {"file": upload, "point": point.pk}
    )

    assert resp.status_code == 200
    body = resp.content.decode()
    message = f"{period.name} is finalized. An administrator can reopen it on the period page."
    assert len(resp.context["errors"]) == 12, "the commit's own error list is unchanged"
    assert body.count(message) == 1
    assert "12 rows: 2, 3, 4 ..." in body


def test_v1_distinct_messages_stay_distinct_lines():
    """The grouping helper keeps one entry per message, in first-seen order,
    counts every row a combined line names, and sorts the rows."""
    from surface.views import _group_row_errors

    grouped = _group_row_errors([
        {"line": 7, "message": "invalid AMOUNT: 'x'"},
        {"line": "4, 3", "message": "WY is finalized."},
        {"line": 9, "message": "invalid AMOUNT: 'x'"},
    ])

    assert [g["message"] for g in grouped] == ["invalid AMOUNT: 'x'", "WY is finalized."]
    assert grouped[0]["count"] == 2 and grouped[0]["first_rows"] == [7, 9]
    assert grouped[1]["count"] == 2 and grouped[1]["first_rows"] == [3, 4]
    assert not grouped[0]["more"]


# ---------------------------------------------------------------------------
# V2: the production preview lists its rows, bounded at 50
# ---------------------------------------------------------------------------

_EAR_HEADER = (
    "PWSID,Year,Month,DateStartOfMonth,TypeCode,Units of Measure As Reported,"
    "Quantity as in Units Reported\n"
)


def _ear_text(n):
    """``n`` eAR rows for one system; the quantity is the row's own marker."""
    types = ("GW", "SW", "Purchased", "Sold", "Recycled", "NonPotable", "NonPotableSold")
    months = ("January", "February", "March", "April", "May", "June", "July",
              "August", "September", "October", "November", "December")
    lines = []
    for i in range(n):
        m = (i // len(types)) % 12
        lines.append(
            f"CA2415001,2022,{months[m]},{m + 1}/1/2022,{types[i % len(types)]},G,{700000 + i}\n"
        )
    return _EAR_HEADER + "".join(lines)


def _production_system():
    from drinking.models import WaterSystem

    # The view reads WaterSystem.objects.first(); this test's system must be it.
    WaterSystem.objects.all().delete()
    return WaterSystem.objects.create(
        pwsid="CA2415001", name="V150 PRODUCTION SYSTEM", activity_status="A",
        pws_type="CWS", state_classification="C", primary_source_code="GW",
    )


def _listed_rows(body):
    start = body.index('id="production-import-rows"')
    table = body[start:body.index("</table>", start)]
    tbody = table[table.index("<tbody>"):]
    return tbody.count("<tr>")


def test_v2_a_three_row_file_lists_its_three_rows(auth_client):
    """Red before: ``'id="production-import-rows"' in body`` (the preview
    carried settings and buttons, no rows)."""
    _production_system()
    upload = SimpleUploadedFile("three.csv", _ear_text(3).encode(), content_type="text/csv")

    body = auth_client.post(
        reverse("drinking:production_import_preview"), {"file": upload}
    ).content.decode()

    assert 'id="production-import-rows"' in body
    assert _listed_rows(body) == 3
    assert "<th>Quantity as in Units Reported</th>" in body, "the file's own column names"
    assert "Showing the first" not in body


def test_v2_a_sixty_row_file_lists_fifty_and_says_so(auth_client):
    """Red before: ``'id="production-import-rows"' in body``."""
    _production_system()
    upload = SimpleUploadedFile("sixty.csv", _ear_text(60).encode(), content_type="text/csv")

    body = auth_client.post(
        reverse("drinking:production_import_preview"), {"file": upload}
    ).content.decode()

    assert 'id="production-import-rows"' in body
    assert _listed_rows(body) == 50
    assert "Showing the first 50 of 60 rows" in body


# ---------------------------------------------------------------------------
# V3: the lab-file preview says the agency line the commit will say
# ---------------------------------------------------------------------------

RECORDED_SENTENCE = "The regulating agency was recorded from the file as District 99."
#: The preview says what the commit WILL do; the commit says what it did (the main session, 150-04).
PREVIEW_SENTENCE = "The regulating agency will be recorded from the file as District 99."


def test_v3_the_preview_carries_the_commits_agency_sentence_and_writes_nothing(
    auth_client, system, fixture_text
):
    """Red before: ``RECORDED_SENTENCE in preview_body`` (the outcome was
    computed in the commit only)."""
    preview = auth_client.post(
        reverse("drinking:import_preview"), {"file": _csv_file(fixture_text)}
    )
    preview_body = preview.content.decode()
    system["system"].refresh_from_db()

    assert PREVIEW_SENTENCE in preview_body
    assert RECORDED_SENTENCE not in preview_body
    assert system["system"].regulating_agency == "", "the preview wrote the agency"

    commit = auth_client.post(
        reverse("drinking:import_commit"), {"rows_json": preview.context["rows_json"]}
    )
    system["system"].refresh_from_db()
    assert RECORDED_SENTENCE in commit.content.decode()
    assert system["system"].regulating_agency == "District 99"


def test_v3_a_system_that_already_has_one_previews_the_commits_refusal(
    auth_client, system, fixture_text
):
    """Red before: the "already has one" sentence in the preview body."""
    ws = system["system"]
    ws.regulating_agency = "DISTRICT 11 - MERCED"
    ws.save()

    body = auth_client.post(
        reverse("drinking:import_preview"), {"file": _csv_file(fixture_text)}
    ).content.decode()

    assert "The regulating agency will not be recorded: the system already has one, DISTRICT 11 - MERCED." in body


def test_v3_the_commit_still_writes_through_the_split_function(system, parsed):
    """``record_regulating_agency`` keeps its contract after the split: it
    writes the one value, and ``regulating_agency_outcomes`` alone writes
    nothing."""
    from drinking import importer

    mapping = importer.auto_map_columns(parsed["columns"])
    validated = importer.validate_rows(parsed["rows"], mapping)

    seen = importer.regulating_agency_outcomes(parsed["rows"], mapping, validated)
    system["system"].refresh_from_db()
    assert [o["outcome"] for o in seen] == [importer.AGENCY_RECORDED]
    assert system["system"].regulating_agency == ""

    importer.record_regulating_agency(parsed["rows"], mapping, validated)
    system["system"].refresh_from_db()
    assert system["system"].regulating_agency == "District 99"


# ---------------------------------------------------------------------------
# V4: "Clear the search" on a filtered empty list
# ---------------------------------------------------------------------------

# (list url name, a maker for one record that does not match "zzzz", the model
# path to empty for the unfiltered case)
_LISTS = [
    ("wells:list", WellFactory, "wells.Well"),
    ("parcels:list", ParcelFactory, "parcels.Parcel"),
    ("recharge:list", RechargeSiteFactory, "recharge.RechargeSite"),
    ("surface:water_rights_list", WaterRightFactory, "surface.WaterRight"),
    ("surface:pod_list", PointOfDiversionFactory, "surface.PointOfDiversion"),
    ("drinking:facilities", SystemFacilityFactory, "drinking.SystemFacility"),
    ("drinking:sampling_points", SamplingPointFactory, "drinking.SamplingPoint"),
]


def _empty(model_path):
    from django.apps import apps

    apps.get_model(model_path).objects.all().delete()


@pytest.mark.parametrize("url_name,make,model_path", _LISTS, ids=[r[0] for r in _LISTS])
def test_v4_a_search_that_matches_nothing_links_to_the_bare_list(
    auth_client, url_name, make, model_path
):
    """Red before: the ``Clear the search`` anchor to the bare list URL."""
    _empty(model_path)
    make()
    url = reverse(url_name)

    body = auth_client.get(url, {"q": "zzzz"}, HTTP_HX_REQUEST="true").content.decode()

    assert "zzzz" in body, "the filtered empty state did not render"
    assert re.search(rf'<a href="{re.escape(url)}"[^>]*>Clear the search</a>', body)


@pytest.mark.parametrize("url_name,make,model_path", _LISTS, ids=[r[0] for r in _LISTS])
def test_v4_the_unfiltered_empty_state_has_no_clear_link(
    auth_client, url_name, make, model_path
):
    _empty(model_path)

    body = auth_client.get(reverse(url_name), HTTP_HX_REQUEST="true").content.decode()

    assert "Clear the search" not in body


# ---------------------------------------------------------------------------
# V6: no records at all, no map card
# ---------------------------------------------------------------------------

_MAP_LISTS = [
    ("wells:list", "wells.Well"),
    ("parcels:list", "parcels.Parcel"),
    ("recharge:list", "recharge.RechargeSite"),
    ("surface:pod_list", "surface.PointOfDiversion"),
    ("drinking:facilities", "drinking.SystemFacility"),
    ("drinking:sampling_points", "drinking.SamplingPoint"),
    ("geography:zone_list", "geography.Zone"),
]


@pytest.mark.parametrize("url_name,model_path", _MAP_LISTS, ids=[r[0] for r in _MAP_LISTS])
def test_v6_a_list_with_no_records_renders_no_map_card_head(auth_client, url_name, model_path):
    """Red before: ``"map-card-head" not in body`` on the full page and on the
    htmx swap (the head said "No X has a location yet." above an empty door)."""
    _empty(model_path)

    page = auth_client.get(reverse(url_name)).content.decode()
    swap = auth_client.get(reverse(url_name), HTTP_HX_REQUEST="true").content.decode()

    assert page.count("map-card-head") == 0
    assert swap.count("map-card-head") == 0


def test_v6_one_unlocated_record_still_gets_the_head_and_its_caption(auth_client):
    _empty("parcels.Parcel")
    ParcelFactory(parcel_number="V150 No Geometry", geometry=None)

    body = auth_client.get(reverse("parcels:list")).content.decode()

    assert body.count("map-card-head") == 1
    assert "No use area has a location yet." in body


# ---------------------------------------------------------------------------
# V7: a negative-zero total
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", [Decimal("-0.001"), Decimal("-0"), Decimal("-0.0000")])
def test_v7_a_negative_zero_prints_as_zero_through_the_canal_tables_filters(value):
    """A PIN, not a red-then-green test. The canal table prints every figure
    as ``|floatformat:2|intcomma`` (templates/surface/partials/_detail_pane.html),
    and Django 5.2.15's ``floatformat`` already rounds first and signs after
    (django/template/defaultfilters.py: ``if sign and rounded_d``), so no
    negative-zero Decimal reaches the page as ``-0.00`` today. This holds that
    against a filter change or a Django upgrade."""
    out = Template("{% load humanize %}{{ v|floatformat:2|intcomma }}").render(
        Context({"v": value})
    )
    assert out == "0.00"
    assert "-" not in out and "\u2212" not in out


# ---------------------------------------------------------------------------
# V9: "Where the water went" only with a direct-use record
# ---------------------------------------------------------------------------


def test_v9_a_recharge_only_point_has_no_where_the_water_went_card(auth_client):
    """Red before: ``'id="where-the-water-went"' not in body`` (the card
    printed "No direct-use diversion records yet.")."""
    from tests.factories import DiversionRecordFactory

    pod = PointOfDiversionFactory(name="V150 Recharge Intake")
    DiversionRecordFactory(point_of_diversion=pod, diversion_type="to_storage")

    body = auth_client.get(reverse("surface:pod_detail", args=[pod.pk])).content.decode()

    assert 'id="where-the-water-went"' not in body


def test_v9_a_point_with_a_direct_use_record_keeps_the_card(auth_client):
    from tests.factories import DiversionRecordFactory

    pod = PointOfDiversionFactory(name="V150 Canal Headgate")
    DiversionRecordFactory(point_of_diversion=pod, diversion_type="direct_use")

    body = auth_client.get(reverse("surface:pod_detail", args=[pod.pk])).content.decode()

    assert 'id="where-the-water-went"' in body


# ---------------------------------------------------------------------------
# V10 + T1: the ledger footer
# ---------------------------------------------------------------------------


def _ledger(auth_client, period):
    return auth_client.get(
        reverse("accounting:ledger_list") + "?" + urlencode({"period": period.pk})
    )


def test_v10_a_positive_manual_row_counts_under_delivered_and_pumped(auth_client):
    """Red before: ``ledger_total_credits == 0`` (the footer split on the
    sign, so the +5 manual correction was a credit: 5.0000)."""
    period = ReportingPeriodFactory()
    parcel = ParcelFactory()
    for source_type, amount in (
        ("meter_reading", Decimal("-10.0000")),
        ("manual_entry", Decimal("5.0000")),
    ):
        ParcelLedgerFactory(
            parcel=parcel, reporting_period=period, source_type=source_type,
            amount_acre_feet=amount, effective_date=date(2024, 6, 15),
        )

    response = _ledger(auth_client, period)

    assert response.context["ledger_total_credits"] == Decimal("0")
    # Delivered and pumped is the magnitude of every non-credit row together:
    # 10 pumped less the 5 corrected back.
    assert response.context["ledger_total_water"] == Decimal("5.0000")


def test_v10_allocation_and_recharge_rows_are_the_credits(auth_client):
    """A negative allocation row is refused by the ledger's own constraint
    (parcelledger_supply_rows_positive), so the converse case is the two credit
    types alone; a negative manual row stays on the water side too."""
    period = ReportingPeriodFactory()
    parcel = ParcelFactory()
    for source_type, amount in (
        ("allocation", Decimal("100.0000")),
        ("recharge", Decimal("25.0000")),
        ("manual_entry", Decimal("-3.0000")),
    ):
        ParcelLedgerFactory(
            parcel=parcel, reporting_period=period, source_type=source_type,
            amount_acre_feet=amount, effective_date=date(2024, 6, 15),
        )

    response = _ledger(auth_client, period)

    assert response.context["ledger_total_credits"] == Decimal("125.0000")
    assert response.context["ledger_total_water"] == Decimal("3.0000")


def test_t1_the_footer_figures_sit_in_a_wrapping_row_not_a_nowrap_cell(auth_client):
    """Red before: ``'class="tfoot-figures"' in tfoot`` (the cell was
    ``style="white-space: nowrap;"``, a 567 px floor under three columns)."""
    period = ReportingPeriodFactory()
    ParcelLedgerFactory(
        reporting_period=period, source_type="allocation",
        amount_acre_feet=Decimal("1.0000"), effective_date=date(2024, 6, 15),
    )

    html = _ledger(auth_client, period).content.decode()
    tfoot = html[html.index("<tfoot>"):html.index("</tfoot>")]

    assert 'class="tfoot-figures"' in tfoot
    assert '<td colspan="3" class="text-xs">' in tfoot
    assert 'colspan="3" class="text-xs" style="white-space: nowrap;"' not in tfoot


# ---------------------------------------------------------------------------
# V11: the zone names carry a colon
# ---------------------------------------------------------------------------

OLD_NAME = "MER Surface Service Area \u2014 Ashvale-Dunmoor Water District (MER-WR-005-DEMO)"
NEW_NAME = "MER Surface Service Area: Ashvale-Dunmoor Water District (MER-WR-005-DEMO)"


def test_v11_the_seed_writes_the_colon_form():
    """Red before: the import (the seed built the name inline with an em dash)."""
    from core.management.commands.seed_merced_ledgers import district_zone_name

    name = district_zone_name("Ashvale-Dunmoor Water District", "MER-WR-005-DEMO")

    assert name == NEW_NAME
    assert "\u2014" not in name


def test_v11_the_migration_renames_a_seeded_row_and_leaves_others_alone():
    """Red before: the import of geography migration 0009."""
    from django.apps import apps

    migration = importlib.import_module("geography.migrations.0009_district_zone_name_colon")
    seeded = ZoneFactory(name=OLD_NAME, zone_type="custom")
    agencys_own = ZoneFactory(name="North \u2014 Service Area (agency named)", zone_type="custom")

    migration.forward(apps, None)
    seeded.refresh_from_db()
    agencys_own.refresh_from_db()

    assert seeded.name == NEW_NAME
    assert agencys_own.name == "North \u2014 Service Area (agency named)"

    migration.backward(apps, None)
    seeded.refresh_from_db()
    assert seeded.name == OLD_NAME


def test_v11_the_district_map_short_label_drops_the_colon_prefix(auth_client):
    """The district map's service-area label reads ``short_label``, which cut
    the composed prefix at the em dash; it must cut at the colon now, or the
    47-character label R-094 shortened comes back."""
    import json

    zone = ZoneFactory(name=NEW_NAME, zone_type="custom")

    data = json.loads(
        auth_client.get(reverse("geography:zone_labels_geojson")).content
    )
    props = next(f["properties"] for f in data["features"] if f["properties"]["pk"] == zone.pk)

    assert props["label"] == "MER Surface Service Area: Ashvale-Dunmoor Water District"
    assert props["short_label"] == "Ashvale-Dunmoor Water District"
