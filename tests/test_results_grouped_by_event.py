# SPDX-License-Identifier: AGPL-3.0-or-later
"""
143-08 Task 5 -- guards for R-070 and R-071 (the results log grouped by
sample event) and R-069 (the sampling-point page's own history folded into
its head, its table grouped the same way).

``group_results_by_event`` (``drinking/views.py``) is the ONE place both
tables fold a contiguous run of results into one block per sample event; it
is tested directly here, in addition to through both pages, so a future edit
to either template cannot silently diverge from the helper's own contract.

Every guard here was observed RED against the pre-change tree (commit
7c368d1, before ``group_results_by_event`` existed and before either
template's table was grouped) before it went green; the RED assertion text
is quoted in 143-08-EVIDENCE.md.
"""

from datetime import date

import factory
import pytest
from django.contrib.auth.hashers import make_password
from django.core.paginator import Paginator
from django.template.loader import render_to_string
from django.test import Client
from django.urls import reverse

from drinking.models import SampleResult
from drinking.views import group_results_by_event
from tests.factories import (
    AnalyteFactory,
    SampleEventFactory,
    SampleResultFactory,
    SamplingPointFactory,
    SystemFacilityFactory,
    WaterSystemFactory,
)


class UserFactory(factory.django.DjangoModelFactory):
    """Local, matching the house convention -- every suite file defines its own."""

    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"drinkgroup{n}")
    email = factory.Sequence(lambda n: f"drinkgroup{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True


@pytest.fixture
def client_in(db):
    client = Client()
    client.force_login(UserFactory())
    return client


def _squash(html):
    return " ".join(html.split())


def _tbody(html):
    assert "<tbody>" in html, "No table on the page"
    return html.split("<tbody>", 1)[1].split("</tbody>", 1)[0]


# -- The helper itself, tested directly -----------------------------------


class TestGroupResultsByEventHelper:
    def test_a_contiguous_run_of_one_event_becomes_one_group(self, db):
        point = SamplingPointFactory()
        event = SampleEventFactory(sampling_point=point, sample_date=date(2024, 6, 1))
        r1 = SampleResultFactory(event=event, analyte=AnalyteFactory(name="Alpha"))
        r2 = SampleResultFactory(event=event, analyte=AnalyteFactory(name="Beta"))

        groups = group_results_by_event([r1, r2])

        assert len(groups) == 1
        assert groups[0]["event"] == event
        assert groups[0]["rows"] == [r1, r2]
        assert groups[0]["shown"] == 2
        assert groups[0]["total"] == 2

    def test_two_contiguous_runs_become_two_groups(self, db):
        point = SamplingPointFactory()
        event_a = SampleEventFactory(sampling_point=point, sample_date=date(2024, 6, 1))
        event_b = SampleEventFactory(sampling_point=point, sample_date=date(2024, 6, 2))
        r1 = SampleResultFactory(event=event_a, analyte=AnalyteFactory())
        r2 = SampleResultFactory(event=event_b, analyte=AnalyteFactory())
        r3 = SampleResultFactory(event=event_b, analyte=AnalyteFactory())

        groups = group_results_by_event([r1, r2, r3])

        assert [g["event"] for g in groups] == [event_a, event_b]
        assert [g["total"] for g in groups] == [1, 2]
        assert [g["shown"] for g in groups] == [1, 2]

    def test_shown_can_be_less_than_total_across_a_page_boundary(self, db):
        """The caller's own pagination can split one event's rows across two
        pages; ``shown`` on each page's slice must read only what THAT slice
        holds, while ``total`` still reads the event's real, full count --
        read fresh off the database, not off ``len(rows)``.
        """
        point = SamplingPointFactory()
        event = SampleEventFactory(sampling_point=point, sample_date=date(2024, 6, 1))
        rows = [
            SampleResultFactory(event=event, analyte=AnalyteFactory())
            for _ in range(6)
        ]

        page_one = group_results_by_event(rows[:4])
        page_two = group_results_by_event(rows[4:])

        assert page_one[0]["shown"] == 4
        assert page_one[0]["total"] == 6
        assert page_two[0]["shown"] == 2
        assert page_two[0]["total"] == 6

    def test_an_empty_list_returns_no_groups(self, db):
        assert group_results_by_event([]) == []


# -- R-070 / R-071: the results log ----------------------------------------


@pytest.fixture
def two_events_same_day(db):
    """Two points sampled the same day, three results each -- the exact
    interleave the old ``-event__sample_date, analyte__name`` ordering
    produced, since it never carried the point or the event as a tiebreak.
    """
    system = WaterSystemFactory(pwsid="CA1010790", name="Ridge Water District")
    facility_a = SystemFacilityFactory(
        system=system, facility_id="001", facility_type="WL"
    )
    facility_b = SystemFacilityFactory(
        system=system, facility_id="002", facility_type="WL"
    )
    point_a = SamplingPointFactory(ps_code="CA1010790_001_001", facility=facility_a)
    point_b = SamplingPointFactory(ps_code="CA1010790_002_001", facility=facility_b)
    # A date after the real seed's own window (test_merced_drinking_seed.py
    # commits a real, three-year lab file to the shared test database via a
    # session-scoped fixture that is never rolled back), so these two rows
    # sort to the very top of the unfiltered log's "-event__sample_date"
    # ordering and land on page one regardless of how much real seeded data
    # the rest of the suite has already committed ahead of this test.
    future_date = date(2030, 1, 1)
    event_a = SampleEventFactory(sampling_point=point_a, sample_date=future_date)
    event_b = SampleEventFactory(sampling_point=point_b, sample_date=future_date)
    # The same three analytes at both events -- Analyte.name is unique, and a
    # real lab file names the same panel of analytes at every point anyway.
    # Named "Test Analyte N", never a real EPA name: test_merced_drinking_seed.py
    # commits the real City of Merced lab file (real analyte names included)
    # to the shared test database via a session-scoped fixture that is never
    # rolled back, so a literal "Arsenic" or "Nitrate" here collides with the
    # real seeded row once that file has run earlier in the session.
    analytes = [
        AnalyteFactory(name="Test Analyte Alpha"),
        AnalyteFactory(name="Test Analyte Beta"),
        AnalyteFactory(name="Test Analyte Gamma"),
    ]
    results = []
    for event in (event_a, event_b):
        for analyte in analytes:
            results.append(SampleResultFactory(event=event, analyte=analyte))
    return {
        "system": system, "point_a": point_a, "point_b": point_b,
        "event_a": event_a, "event_b": event_b, "results": results,
        "future_date": future_date,
    }


def _only_the_fixtures_own_date(client, fixture):
    """GET the results log scoped to this fixture's own ``future_date``.

    The unfiltered log is the WHOLE platform's results, real seeded data
    (``test_merced_drinking_seed.py``) included once that file has run
    earlier in the session, so an unscoped request would pick up however
    many other events happen to fall on page one. ``date_from``/``date_to``
    both pinned to the fixture's own date narrow the log to exactly the rows
    this fixture created, on the same view the results log itself renders.
    """
    date_str = fixture["future_date"].isoformat()
    return client.get(
        reverse("drinking:results"),
        {"date_from": date_str, "date_to": date_str},
    ).content.decode()


class TestResultsLogGroupsByEvent:
    def test_two_events_render_as_two_groups_in_ps_code_order(
        self, client_in, two_events_same_day
    ):
        html = _only_the_fixtures_own_date(client_in, two_events_same_day)
        tbody = _tbody(html)
        assert tbody.count('<tr class="row-group">') == 2
        assert tbody.index("CA1010790_001_001") < tbody.index("CA1010790_002_001"), (
            "the two events on one date should not interleave"
        )

    def test_no_column_repeats_the_date_or_the_ps_code(
        self, client_in, two_events_same_day
    ):
        html = _only_the_fixtures_own_date(client_in, two_events_same_day)
        assert "<th>Sample Date</th>" not in html
        assert "<th>PS Code</th>" not in html

    def test_the_analyte_cell_holds_the_link_to_the_result_page(
        self, client_in, two_events_same_day
    ):
        html = _only_the_fixtures_own_date(client_in, two_events_same_day)
        rows = [r for r in _tbody(html).split("<tr>") if "Test Analyte Alpha" in r]
        assert rows, "no data row named the analyte"
        assert 'class="data-table-link"' in rows[0], (
            "the Analyte cell should carry the link that used to sit on "
            "the Sample Date cell"
        )


class TestResultsLogDividerAdmitsAPageSplit:
    def test_the_second_page_of_a_six_result_event_says_two_on_this_page(self, db):
        point = SamplingPointFactory(ps_code="CA1010791_001_001")
        event = SampleEventFactory(sampling_point=point, sample_date=date(2024, 6, 1))
        for _ in range(6):
            SampleResultFactory(event=event, analyte=AnalyteFactory())

        queryset = SampleResult.objects.filter(event=event).order_by("pk")
        paginator = Paginator(queryset, 4)
        page_obj = paginator.get_page(2)

        html = render_to_string(
            "drinking/partials/_result_results.html",
            {
                "total_count": 6,
                "page_obj": page_obj,
                "result_groups": group_results_by_event(page_obj.object_list),
            },
        )
        text = _squash(html)
        assert "6 results" in text
        assert ", 2 on this page" in text


# -- R-069: the sampling-point page's own history --------------------------


@pytest.fixture
def point_with_history(db):
    system = WaterSystemFactory(pwsid="CA1010792", name="Ridge Water District")
    facility = SystemFacilityFactory(
        system=system, facility_id="001", facility_type="WL"
    )
    point = SamplingPointFactory(ps_code="CA1010792_001_001", facility=facility)
    event = SampleEventFactory(sampling_point=point, sample_date=date(2024, 6, 1))
    # Fictional names, same reason as two_events_same_day above: a real EPA
    # analyte name would collide with the Merced seed once it has run.
    SampleResultFactory(event=event, analyte=AnalyteFactory(name="Test Analyte Alpha"))
    SampleResultFactory(event=event, analyte=AnalyteFactory(name="Test Analyte Beta"))
    return {"system": system, "point": point, "event": event}


class TestSamplingPointPageFoldsHistoryIntoItsHead:
    def test_the_head_states_the_result_and_analyte_counts(
        self, client_in, point_with_history
    ):
        html = client_in.get(
            reverse(
                "drinking:sampling_point_detail",
                args=[point_with_history["point"].pk],
            )
        ).content.decode()
        text = _squash(html)
        assert "2 sample results" in text
        assert "2 analytes" in text

    def test_the_table_carries_a_row_group_divider(
        self, client_in, point_with_history
    ):
        html = client_in.get(
            reverse(
                "drinking:sampling_point_detail",
                args=[point_with_history["point"].pk],
            )
        ).content.decode()
        assert '<tr class="row-group">' in html

    def test_sampling_history_is_no_longer_a_heading(
        self, client_in, point_with_history
    ):
        html = client_in.get(
            reverse(
                "drinking:sampling_point_detail",
                args=[point_with_history["point"].pk],
            )
        ).content.decode()
        assert "Sampling history" not in html
