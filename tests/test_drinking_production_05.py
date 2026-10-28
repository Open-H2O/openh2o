# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Production month duplicates, lab column alias order, and the verdict-word helper.

Three small defects, each with its own case built here:

  * Add production refuses a month and type already on file for the same
    facility (blank counts as equal to blank). The database cannot say so,
    because Postgres treats two NULL facilities as different and a live site
    may already hold duplicates.
  * The lab importer's column aliases are tuples in priority order, so a file
    that carries two spellings of one field maps to the same one every run.
  * The verdict-word check reads the visible text of a page, whole words only,
    and names the word and its context when it finds one.
"""

import pytest
from django.contrib.auth.hashers import make_password
from django.test import Client
from django.urls import reverse

from drinking import importer
from drinking.forms import SystemProductionForm
from drinking.models import SystemProduction
from tests.factories import SystemFacilityFactory, WaterSystemFactory


@pytest.fixture
def site(db):
    return WaterSystemFactory(pwsid="CA0000051", name="Production Test System")


@pytest.fixture
def client(db):
    from django.contrib.auth import get_user_model

    user = get_user_model().objects.create(
        username="prod05", password=make_password("x"), is_active=True
    )
    c = Client()
    c.force_login(user)
    return c


def _post(client, **over):
    data = {
        "year": "2026",
        "month": "3",
        "type_code": "GW",
        "facility": "",
        "volume_as_reported": "1000",
        "unit_as_reported": "G",
        "notes": "",
    }
    data.update(over)
    return client.post(reverse("drinking:production_add"), data)


# ---------------------------------------------------------------------------
# Row 4: a month and type already on file
# ---------------------------------------------------------------------------


class TestDuplicateProductionMonth:
    def test_same_month_type_and_blank_facility_is_refused(self, client, site):
        assert _post(client).status_code == 302
        second = _post(client, volume_as_reported="2000")
        assert second.status_code == 200
        assert SystemProduction.objects.filter(system=site).count() == 1
        text = second.content.decode()
        assert "A figure for Groundwater in March 2026 is already on file." in text

    def test_same_month_type_and_named_facility_is_refused_not_a_500(
        self, client, site
    ):
        well = SystemFacilityFactory(system=site, name="Well 7")
        assert _post(client, facility=str(well.pk)).status_code == 302
        second = _post(client, facility=str(well.pk))
        assert second.status_code == 200
        assert SystemProduction.objects.filter(system=site).count() == 1
        assert "already on file" in second.content.decode()

    def test_a_whole_year_figure_twice_is_refused(self, client, site):
        assert _post(client, month="").status_code == 302
        second = _post(client, month="")
        assert second.status_code == 200
        assert SystemProduction.objects.filter(system=site).count() == 1
        assert "A figure for Groundwater in 2026 is already on file." in (
            second.content.decode()
        )

    def test_a_different_month_type_or_facility_saves(self, client, site):
        well = SystemFacilityFactory(system=site, name="Well 8")
        assert _post(client).status_code == 302
        assert _post(client, month="4").status_code == 302
        assert _post(client, type_code="SW").status_code == 302
        assert _post(client, facility=str(well.pk)).status_code == 302
        assert SystemProduction.objects.filter(system=site).count() == 4

    def test_editing_the_row_itself_unchanged_saves(self, client, site):
        _post(client)
        row = SystemProduction.objects.get(system=site)
        form = SystemProductionForm(
            {
                "year": "2026",
                "month": "3",
                "type_code": "GW",
                "facility": "",
                "volume_as_reported": "1000",
                "unit_as_reported": "G",
                "notes": "",
            },
            instance=row,
            system=site,
        )
        assert form.is_valid(), form.errors


# ---------------------------------------------------------------------------
# Row 5: alias order
# ---------------------------------------------------------------------------


class TestAliasOrder:
    def test_every_alias_value_is_a_tuple(self):
        assert all(isinstance(v, tuple) for v in importer.ALIASES.values())

    def test_the_ddw_spelling_wins_when_a_file_carries_two(self):
        columns = ["Sample Point Name", "Sampling Point Name", "PS Code"]
        mapping = importer.auto_map_columns(columns)
        assert mapping["sampling_point_name"] == "Sampling Point Name"
        mapping = importer.auto_map_columns(list(reversed(columns)))
        assert mapping["sampling_point_name"] == "Sampling Point Name"


# ---------------------------------------------------------------------------
# Row 7: the verdict-word helper
# ---------------------------------------------------------------------------


class TestVerdictWordHelper:
    def test_it_fails_on_planted_page_text(self):
        from tests.test_drinking_import import _verdict_words_in

        html = "<html><body><p>Preview: the import will fail on row 3.</p></body></html>"
        found = _verdict_words_in(html)
        assert found
        assert "fail" in found[0]
        assert "the import will fail" in found[0]

    def test_it_passes_when_only_the_csrf_token_holds_the_letters(self):
        from tests.test_drinking_import import _verdict_words_in

        html = (
            '<html><body><form><input type="hidden" '
            'name="csrfmiddlewaretoken" value="abcpassxyzfail9"></form>'
            "<script>var x = 'fail pass';</script>"
            "<p>Rows read: 30. A bypass is not a verdict.</p></body></html>"
        )
        assert _verdict_words_in(html) == []
