# SPDX-License-Identifier: AGPL-3.0-or-later
"""Four small pages each explain themselves instead of leaving a reader to
guess (143-09): the roster's own row is worded (R-131), the import page
offers the other types (R-130), the add page's use-area link is a visible
disclosure (R-129), and the diversion page's water right is an open card
under an honest description (R-117).
"""
import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from core import modules as mod
from tests.factories import PointOfDiversionFactory
from tests.test_module_prose import compose_urlconf_under_the_full_module_set

User = get_user_model()

WITHOUT_SURFACE_RECHARGE = [
    name for name in mod.ALL_MODULE_NAMES if name not in ("surface", "recharge")
]


def _user(username, **extra):
    defaults = dict(is_active=True)
    defaults.update(extra)
    return User.objects.create_user(
        username=username, email=f"{username}@example.com", password="x", **defaults
    )


def _client_for(user):
    client = Client()
    client.force_login(user)
    return client


@pytest.mark.django_db
class TestTheRosterWordsItsOwnRow:
    """R-131: 'You' alone is gone from the Actions column; the signed-in
    reader's own row and a host administrator's row both say why there is
    nothing to click."""

    def test_own_row_and_a_host_administrator_row_are_worded(self):
        me = _user("roster-self", is_staff=False, agency_admin=True)
        _user("roster-host-admin", is_staff=True)
        client = _client_for(me)
        html = client.get(reverse("core:users_list")).content.decode()
        assert "Your account. Another administrator changes your role or status." in html
        assert "Host administrator; managed outside this page." in html
        # The old shape left the cell reading "You" and nothing else.
        assert ">You<" not in html


@pytest.mark.django_db
class TestTheImportPageOffersTheOtherTypes:
    """R-130: 'Importing something else?' links to the other types this
    deployment can serve, the same shape the add page already uses."""

    def test_well_import_page_links_to_the_other_types_not_itself(self):
        user = _user("import-reader")
        client = _client_for(user)
        html = client.get(
            reverse("infrastructure:import") + "?type=well"
        ).content.decode()
        assert "Importing something else?" in html
        assert '?type=diversion' in html
        assert '?type=storage' in html
        assert '?type=recharge_site' in html
        assert '?type=well">Well</a>' not in html  # never a link back to itself

    def test_with_only_wells_the_line_is_absent(self, settings):
        compose_urlconf_under_the_full_module_set()
        settings.OPENH2O_MODULES = WITHOUT_SURFACE_RECHARGE
        user = _user("import-reader-wells-only")
        client = _client_for(user)
        html = client.get(
            reverse("infrastructure:import") + "?type=well"
        ).content.decode()
        assert "Importing something else?" not in html


@pytest.mark.django_db
class TestTheAddPageUseAreaLinkIsAVisibleDisclosure:
    """R-129: the summary carries a chevron mark, and the words say 'use
    area', never 'parcel'."""

    def test_summary_carries_the_disclosure_mark_and_use_area_words(self):
        user = _user("add-page-reader")
        client = _client_for(user)
        html = client.get(
            reverse("infrastructure:add") + "?type=well"
        ).content.decode()
        assert 'details class="parcel-link-section"' in html
        summary_start = html.index('details class="parcel-link-section"')
        summary_chunk = html[summary_start:summary_start + 1200]
        assert 'class="text-tertiary disclosure-mark"' in summary_chunk
        assert "Link to a use area" in summary_chunk
        assert "Link to parcel" not in html


@pytest.mark.django_db
class TestTheDiversionPageOpensTheWaterRight:
    """R-117: the water right is an ordinary open card, headed 'Water
    right', and the page's own description no longer promises compliance
    information it does not show."""

    def test_water_right_is_an_open_h2_card_with_no_details_element(self):
        pod = PointOfDiversionFactory()
        user = _user("diversion-reader")
        client = _client_for(user)
        html = client.get(
            reverse("surface:pod_detail", kwargs={"pk": pod.pk})
        ).content.decode()
        assert '<h2 class="section-header">Water right</h2>' in html
        # Scoped to the water-right card itself: the sidebar's own unrelated
        # Help group is also a <details> element on every page.
        water_right_card = html[html.index('<h2 class="section-header">Water right</h2>'):]
        assert "<details" not in water_right_card
        assert "Compliance details" not in html

    def test_description_names_the_water_right_not_compliance(self):
        pod = PointOfDiversionFactory()
        user = _user("diversion-reader-2")
        client = _client_for(user)
        html = client.get(
            reverse("surface:pod_detail", kwargs={"pk": pod.pk})
        ).content.decode()
        assert "the water right it draws under" in html
        assert "compliance information" not in html
