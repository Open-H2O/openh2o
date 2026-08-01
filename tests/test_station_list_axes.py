# SPDX-License-Identifier: AGPL-3.0-or-later
"""Wiring and freshness are two axes, and the station list now says so.

Brent, reviewing 104-02: *"The filter says active but a bunch of dormant
stations are present — this doesn't make sense."* It made sense in the data and
not in the words. Two independent things were wearing one vocabulary:

* `is_active` — do we pull from this station at all. The switch on its page.
* `classify_freshness` — has it published recently, judged against its own
  source's cadence. The coloured dot, and the map legend's "Up to date /
  Slightly behind / Dormant".

A station is routinely BOTH wired and dormant. Nothing on the page said those
were different questions, and there was only one control, so the page could not
answer the question an operator actually arrives with: what isn't reporting?

ISS-108 is the second filter and the split vocabulary. ISS-109 is the switch:
it was never missing — `datasync:station_toggle` has always existed — it was
unreachable, because this list hides not-syncing stations by default and CIMIS's
fifteen dormant rows would have meant fifteen separate page visits.
"""

from datetime import timedelta

import pytest
from django.contrib.gis.geos import Point
from django.urls import reverse
from django.utils import timezone

from datasync.models import DataSource, MonitoredStation

pytestmark = pytest.mark.django_db


@pytest.fixture
def network(db):
    """One source, four stations spanning both axes independently.

    cdec's expected cadence is daily, so "hours ago" maps cleanly onto
    fresh/stale/dead without this fixture having to know the thresholds.
    """
    source, _ = DataSource.objects.get_or_create(
        code="cdec", defaults={"name": "California Data Exchange Center"}
    )
    now = timezone.now()

    def station(ext, name, active, age_hours):
        return MonitoredStation.objects.create(
            data_source=source,
            external_station_id=ext,
            station_name=name,
            location=Point(-120.5, 37.2, srid=4326),
            is_active=active,
            last_data_at=None if age_hours is None else now - timedelta(hours=age_hours),
        )

    return {
        "source": source,
        # syncing AND up to date
        "healthy": station("AAA", "SYNCING AND FRESH", True, 1),
        # syncing AND dormant -- the combination that read as a contradiction
        "wired_dormant": station("BBB", "SYNCING BUT DORMANT", True, None),
        # not syncing, never reported -- a discovered CIMIS-style row
        "discovered": station("CCC", "DISCOVERED NOT SYNCING", False, None),
        # not syncing but recently reported (switched off after the fact)
        "switched_off": station("DDD", "SWITCHED OFF RECENTLY", False, 1),
    }


def _names(response):
    return {s["station"].station_name for s in response.context["enriched_stations"]}


@pytest.fixture
def client_in(client, django_user_model):
    user = django_user_model.objects.create_user(
        email="axes@example.com", password="axes-test-pw-2026"
    )
    client.force_login(user)
    return client


class TestTheTwoAxesFilterIndependently:
    def test_a_station_can_be_syncing_and_dormant_at_once(self, client_in, network):
        """The whole issue in one assertion. Not a data contradiction."""
        url = reverse("datasync:station_list")
        response = client_in.get(url, {"active": "1", "reporting": "dead"})
        assert "SYNCING BUT DORMANT" in _names(response)

    def test_the_reporting_filter_answers_what_isnt_reporting(
        self, client_in, network
    ):
        """The question no control on this page could answer before."""
        url = reverse("datasync:station_list")
        dormant = _names(client_in.get(url, {"active": "all", "reporting": "dead"}))
        assert dormant == {"SYNCING BUT DORMANT", "DISCOVERED NOT SYNCING"}

    def test_the_syncing_filter_still_answers_the_wiring_question(
        self, client_in, network
    ):
        url = reverse("datasync:station_list")
        not_syncing = _names(client_in.get(url, {"active": "0"}))
        assert not_syncing == {"DISCOVERED NOT SYNCING", "SWITCHED OFF RECENTLY"}

    def test_up_to_date_crosses_the_wiring_axis(self, client_in, network):
        """Freshness must not silently imply wiring, or the axes are not separate."""
        url = reverse("datasync:station_list")
        fresh = _names(client_in.get(url, {"active": "all", "reporting": "fresh"}))
        assert fresh == {"SYNCING AND FRESH", "SWITCHED OFF RECENTLY"}

    def test_no_reporting_value_means_no_freshness_filtering(
        self, client_in, network
    ):
        url = reverse("datasync:station_list")
        assert len(_names(client_in.get(url, {"active": "all"}))) == 4

    def test_an_unknown_reporting_value_filters_nothing_rather_than_emptying(
        self, client_in, network
    ):
        """A hand-typed or stale query string must not silently show zero rows."""
        url = reverse("datasync:station_list")
        response = client_in.get(url, {"active": "all", "reporting": "banana"})
        assert len(_names(response)) == 4

    def test_the_count_reflects_the_filtered_list_not_the_unfiltered_one(
        self, client_in, network
    ):
        """The count is paginated from the filtered list, so it must agree."""
        url = reverse("datasync:station_list")
        response = client_in.get(url, {"active": "all", "reporting": "dead"})
        assert response.context["total_count"] == 2


class TestTheVocabularyNoLongerOverlaps:
    def test_the_wiring_filter_does_not_use_a_freshness_word(self, client_in, network):
        """"Active" against "Dormant" dots is what caused the report.

        The two controls must not share a word, in either direction.
        """
        html = client_in.get(reverse("datasync:station_list")).content.decode()
        wiring_block = html.split('id="filter-active"')[1].split("</select>")[0]
        for freshness_word in ("Dormant", "Up to date", "Slightly behind"):
            assert freshness_word not in wiring_block

    def test_the_freshness_filter_uses_the_legend_words_verbatim(
        self, client_in, network
    ):
        html = client_in.get(reverse("datasync:station_list")).content.decode()
        block = html.split('id="filter-reporting"')[1].split("</select>")[0]
        for legend_word in ("Up to date", "Slightly behind", "Dormant"):
            assert legend_word in block


class TestTheSwitchIsReachableInBulk:
    def test_every_row_carries_a_toggle_posting_to_the_existing_endpoint(
        self, client_in, network
    ):
        """ISS-109. No new view -- the endpoint was always there, unreachable."""
        html = client_in.get(
            reverse("datasync:station_list"), {"active": "0"}
        ).content.decode()
        for station in (network["discovered"], network["switched_off"]):
            assert reverse("datasync:station_toggle", args=[station.pk]) in html

    def test_a_discovered_station_can_be_switched_on_from_that_list(
        self, client_in, network
    ):
        """The dead end, walked end to end: find it dormant, switch it on."""
        discovered = network["discovered"]
        assert discovered.is_active is False

        listing = client_in.get(reverse("datasync:station_list"), {"active": "0"})
        assert "DISCOVERED NOT SYNCING" in _names(listing)

        client_in.post(reverse("datasync:station_toggle", args=[discovered.pk]))
        discovered.refresh_from_db()
        assert discovered.is_active is True

        # And it has moved to the other side of the wiring filter.
        assert "DISCOVERED NOT SYNCING" in _names(
            client_in.get(reverse("datasync:station_list"), {"active": "1"})
        )
