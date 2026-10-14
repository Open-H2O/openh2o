# SPDX-License-Identifier: AGPL-3.0-or-later
"""The three behaviours behind 150.1-02 screen 14's approved sentences.

Brent approved message A at 2026-10-14 15:37 PDT ("I read the sentences and
they look good") and message B at 15:51 PDT ("approved"). Three rows needed
code, not only words:

* A row 3: a result names the lab file it was imported from, because the
  importer takes any lab file in the state's format and the old label named
  the State Water Board for all of them.
* B row 11: a facility added by hand is labelled "entered on this site" on the
  result page and the sampling point page, as the facility page already was.
* B row 4: the map sentence counts the points it leaves off.
"""
from datetime import date

import factory
import pytest
from django.contrib.auth.hashers import make_password
from django.contrib.gis.geos import Point
from django.test import Client
from django.urls import reverse

from drinking import provenance
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

    username = factory.Sequence(lambda n: f"screen14_{n}")
    email = factory.Sequence(lambda n: f"screen14_{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True


@pytest.fixture
def client_in(db):
    client = Client()
    client.force_login(UserFactory())
    return client


def _text(response):
    return " ".join(response.content.decode().split()).replace("&#x27;", "'")


def _result(*, added_by_hand=False, located=True, **result_fields):
    system = WaterSystemFactory(pwsid="CA1010794", name="RIDGE WATER")
    facility = SystemFacilityFactory(
        system=system, facility_id="001", facility_type="WL",
        added_by_hand=added_by_hand,
        location=Point(-120.48, 37.30, srid=4326) if located else None,
    )
    point = SamplingPointFactory(ps_code="CA1010794_001_001", facility=facility)
    event = SampleEventFactory(sampling_point=point, sample_date=date(2024, 6, 1))
    return SampleResultFactory(
        event=event, analyte=AnalyteFactory(name="Nitrate"), **result_fields
    )


@pytest.mark.django_db
class TestTheResultNamesItsLabFile:
    def test_a_result_with_a_stored_file_names_the_file_and_the_date(self, client_in):
        result = _result(
            limits_source_file="ridge_lab_2024.tab", limits_file_date=date(2024, 7, 2)
        )
        text = _text(client_in.get(reverse("drinking:result_detail", args=[result.pk])))
        assert "Source: ridge_lab_2024.tab, imported 2024-07-02" in text
        assert provenance.DDW_LAB not in text

    def test_a_result_with_no_stored_file_says_an_imported_lab_file(self, client_in):
        result = _result(limits_source_file="", limits_file_date=None)
        text = _text(client_in.get(reverse("drinking:result_detail", args=[result.pk])))
        assert f"Source: {provenance.LAB_FILE}" in text
        assert provenance.DDW_LAB not in text

    def test_the_lists_say_imported_lab_files(self, client_in):
        result = _result()
        for url in (
            reverse("drinking:results"),
            reverse("drinking:sampling_point_detail", args=[result.event.sampling_point_id]),
        ):
            text = _text(client_in.get(url))
            assert f"Source: {provenance.LAB_FILES}" in text, url
            assert provenance.DDW_LAB not in text, url


@pytest.mark.django_db
class TestAFacilityAddedByHandIsLabelledAsEnteredHere:
    @pytest.mark.parametrize("added_by_hand", [True, False])
    def test_both_pages_follow_the_facility(self, client_in, added_by_hand):
        result = _result(added_by_hand=added_by_hand)
        for url in (
            reverse("drinking:result_detail", args=[result.pk]),
            reverse("drinking:sampling_point_detail", args=[result.event.sampling_point_id]),
        ):
            text = _text(client_in.get(url))
            if added_by_hand:
                assert f"Source: {provenance.OPERATOR_ENTERED}</span>" in text, url
                assert provenance.EPA_SDWIS not in text, url
            else:
                assert f"Source: {provenance.EPA_SDWIS}</span>" in text, url
                assert f"Source: {provenance.OPERATOR_ENTERED}</span>" not in text, url


@pytest.mark.django_db
class TestTheMapSentenceCountsThePointsItLeavesOff:
    def test_the_unmapped_points_are_counted(self, client_in):
        result = _result()
        located = result.event.sampling_point.facility
        bare = SystemFacilityFactory(system=located.system, facility_id="090", location=None)
        for n in (1, 2):
            SamplingPointFactory(ps_code=f"CA1010794_090_09{n}", facility=bare)
        text = _text(client_in.get(reverse("drinking:sampling_points")))
        assert "The map shows 1 of the 3 sampling points at their facilities' locations." in text
        assert "The other 2 belong to facilities with no location recorded." in text
        assert "/admin/ under Drinking Water &gt; System Facilities" in text

    def test_every_point_mapped_says_no_other(self, client_in):
        _result()
        text = _text(client_in.get(reverse("drinking:sampling_points")))
        assert "The map shows 1 of the 1 sampling point" in text
        assert "The other" not in text
