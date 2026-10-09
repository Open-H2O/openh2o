# SPDX-License-Identifier: AGPL-3.0-or-later
"""150-03 Task 5 (ISS-183): the words the screens use and no screen defined.

Nine entries joined ``/help/glossary/``: the drinking-water words a lab file and
the state's records carry (MCL, DLR, PWSID, PS Code, Analyte, Sampling Point,
Reporting Level, ELAP) and the station list's three freshness words as one
entry. Each is asserted present, labelled with whose word it is, and clean
under copy rule 11 (``tests.test_domain_vocabulary.scan``) and the rule-12 table
(``tests.test_water_vocabulary.scan``), the same two scanners the glossary's
surface gates call.

**The freshness numbers are read from the code, never typed twice.** The
glossary entry is a literal string (the two vocabulary gates parse the ``terms``
dict with ``ast``), so this file builds the sentence's per-source list and its
two multipliers from ``datasync/freshness.py``'s constants and demands the
entry carry them. A changed constant fails here until the sentence follows it.
The station page's tooltip is built from the same constants at request time,
and is checked against ``classify_freshness`` itself at each boundary.
"""
from datetime import timedelta

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from datasync import freshness
from tests.test_domain_vocabulary import scan as rule_11_scan
from tests.test_water_vocabulary import scan as rule_12_scan

pytestmark = pytest.mark.django_db

NEW_TERMS = {
    "Analyte": "outside",
    "DLR": "outside",
    "ELAP": "outside",
    "MCL": "outside",
    "PS Code": "outside",
    "PWSID": "outside",
    "Reporting Level": "outside",
    "Sampling Point": "platform",
    "Up to date / Slightly behind / Dormant": "platform",
}

FRESHNESS_TERM = "Up to date / Slightly behind / Dormant"


@pytest.fixture
def entries(admin_client):
    response = admin_client.get(reverse("glossary"))
    assert response.status_code == 200
    return {entry["term"]: entry for entry in response.context["entries"]}


class TestTheNewEntries:
    def test_each_new_term_is_served_with_whose_word_it_is(self, entries):
        missing = [term for term in NEW_TERMS if term not in entries]
        assert missing == []
        assert {term: entries[term]["kind"] for term in NEW_TERMS} == NEW_TERMS

    def test_the_page_lists_them_in_casefold_order(self, entries):
        terms = list(entries)
        assert terms == sorted(terms, key=str.casefold)

    @pytest.mark.parametrize("term", sorted(NEW_TERMS))
    def test_each_definition_scans_clean_under_rule_11(self, entries, term):
        offences = rule_11_scan(entries[term]["text"])
        assert offences == [], [str(offence) for offence in offences]

    @pytest.mark.parametrize("term", sorted(NEW_TERMS))
    def test_each_definition_scans_clean_under_rule_12(self, entries, term):
        hits = rule_12_scan(entries[term]["text"], f"config/views.py::glossary[{term}]")
        assert hits == []

    @pytest.mark.parametrize("term", sorted(NEW_TERMS))
    def test_no_definition_carries_an_em_dash(self, entries, term):
        assert "\u2014" not in entries[term]["text"]

    def test_the_codes_are_expanded(self, entries):
        """Rule 11's operational form: expand the code, then say what is held."""
        assert entries["MCL"]["text"].startswith("Maximum Contaminant Level.")
        assert entries["DLR"]["text"].startswith(
            "Detection Limit for purposes of Reporting."
        )
        assert entries["PWSID"]["text"].startswith(
            "Public Water System Identification number."
        )
        assert entries["PS Code"]["text"].startswith("Primary Station Code,")
        assert entries["ELAP"]["text"].startswith(
            "Environmental Laboratory Accreditation Program,"
        )

    def test_the_mcl_entry_claims_no_comparison(self, entries):
        """The platform shows the file's MCL beside a finding and judges nothing
        (ISS-140, ruled "beside"); the definition must say exactly that."""
        assert "never compares a finding with it" in entries["MCL"]["text"]


def _source_list():
    """The entry's per-source list, built from the constants alone."""
    by_interval = {}
    for code, hours in freshness.EXPECTED_DATA_INTERVAL_HOURS.items():
        by_interval.setdefault(hours, []).append(freshness.source_display(code))
    parts = [
        f"{' and '.join(names)} {freshness.format_hours(hours)}"
        for hours, names in sorted(by_interval.items())
    ]
    parts.append(
        f"any other source {freshness.format_hours(freshness.DEFAULT_INTERVAL_HOURS)}"
    )
    return "(" + "; ".join(parts) + ")"


class TestTheFreshnessEntryIsReadFromTheCode:
    def test_every_source_and_interval_matches_the_constants(self, entries):
        assert _source_list() in entries[FRESHNESS_TERM]["text"]

    def test_the_two_multipliers_match_the_constants(self, entries):
        text = entries[FRESHNESS_TERM]["text"]
        assert f"Up to date within {freshness.FRESH_MULTIPLIER:g} times" in text
        assert f"Slightly behind within {freshness.STALE_MULTIPLIER:g} times" in text
        assert "Dormant after that or with no reading at all" in text


class TestTheHoursReadAsAReaderSaysThem:
    @pytest.mark.parametrize("hours, words", [
        (24, "1 day"),
        (36, "36 hours"),
        (48, "2 days"),
        (54, "54 hours"),
        (108, "4.5 days"),
        (144, "6 days"),
        (1620, "67.5 days"),
        (2880, "120 days"),
    ])
    def test_format_hours(self, hours, words):
        assert freshness.format_hours(hours) == words


class TestTheStationTooltip:
    def test_the_sentence_for_one_source(self):
        assert freshness.freshness_thresholds("cdec", "CDEC") == (
            "A station is Up to date when its latest reading is at most 54 hours "
            "old, Slightly behind at most 6 days old, and Dormant after that or "
            "with no reading. Those limits are 1.5 and 4 times how often CDEC "
            "usually publishes, every 36 hours. A station can be syncing and "
            "still dormant."
        )

    @pytest.mark.parametrize(
        "code", sorted(freshness.EXPECTED_DATA_INTERVAL_HOURS) + ["unlisted"]
    )
    def test_the_stated_limits_are_where_classify_freshness_turns(self, code):
        """The words name the same two boundaries the classifier applies."""
        now = timezone.now()
        interval = freshness.expected_interval_hours(code)
        fresh_limit = timedelta(hours=interval * freshness.FRESH_MULTIPLIER)
        stale_limit = timedelta(hours=interval * freshness.STALE_MULTIPLIER)
        minute = timedelta(minutes=1)

        assert freshness.classify_freshness(code, now - fresh_limit + minute, now) == "fresh"
        assert freshness.classify_freshness(code, now - fresh_limit - minute, now) == "stale"
        assert freshness.classify_freshness(code, now - stale_limit + minute, now) == "stale"
        assert freshness.classify_freshness(code, now - stale_limit - minute, now) == "dead"

        sentence = freshness.freshness_thresholds(code)
        assert f"at most {freshness.format_hours(interval * freshness.FRESH_MULTIPLIER)} old" in sentence
        assert f"at most {freshness.format_hours(interval * freshness.STALE_MULTIPLIER)} old" in sentence

    def test_the_station_page_and_list_carry_it(self):
        from core.models import User
        from django.contrib.gis.geos import Point

        from datasync.models import DataSource, MonitoredStation

        source = DataSource.objects.create(
            code="openet", name="Probe OpenET Source", is_active=True
        )
        station = MonitoredStation.objects.create(
            data_source=source, external_station_id="ISS183-1",
            station_name="Probe Tooltip Station", location=Point(-120.0, 37.0),
            is_active=True, last_data_at=None,
        )
        client = Client()
        client.force_login(User.objects.create(
            username="iss183-reader", email="iss183@example.com", is_active=True,
        ))
        expected = freshness.freshness_thresholds("openet", "Probe OpenET Source")
        assert "at most 67.5 days old" in expected
        assert "at most 180 days old" in expected

        detail = client.get(reverse("datasync:station_detail", args=[station.pk]))
        assert f'title="{expected}">Dormant</span>' in detail.content.decode()

        listing = client.get(reverse("datasync:station_list"), {"active": "all"})
        assert f'title="{expected}"' in listing.content.decode()
