# SPDX-License-Identifier: AGPL-3.0-or-later
"""The site-wide demonstration notice and the provenance page behind it.

Phase 64's ``_demo_marker.html`` pill answers a narrow question well: is this
one status a real legal action? It appears on six surfaces and can be cropped
out of a screenshot. The risk it does not cover is the one that prompted this:
a public demo whose tables can be captured and presented as a real regulatory
record.

Two properties are load-bearing and neither is obvious from reading a template:

* The notice renders on **every** page while the flag is on, and on a real
  agency deployment it emits **nothing at all** — not a hidden element.
* ``/about/demonstration-data/`` resolves **regardless** of the flag. A link
  pasted in answer to a "this data is fake" accusation must not 404 the moment
  a real deployment turns demonstration mode off.
"""
import pytest
from django.contrib.auth.hashers import make_password
from django.test import Client
from django.urls import reverse

from core.models import SiteConfig

BANNER_PHRASE = "For testing purposes only"


@pytest.fixture
def client_logged_in(db, django_user_model):
    user = django_user_model.objects.create(
        username="evaluator",
        email="evaluator@example.gov",
        password=make_password("pw"),
        is_active=True,
    )
    client = Client()
    client.force_login(user)
    return client


def _set_flag(value):
    config = SiteConfig.objects.first()
    if config is None:
        config = SiteConfig(agency_name="Test Agency")
    config.demonstration_mode = value
    config.save()
    return config


# -- the banner ---------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize(
    "url_name",
    ["about", "demonstration_data", "getting_started", "glossary"],
)
def test_banner_renders_on_every_page_when_the_flag_is_on(
    client_logged_in, url_name
):
    """Site-wide, not per-page: a screenshot of any screen has to carry it."""
    _set_flag(True)
    response = client_logged_in.get(reverse(url_name))
    assert response.status_code == 200
    assert BANNER_PHRASE in response.content.decode()


@pytest.mark.django_db
def test_banner_emits_nothing_on_a_real_deployment(client_logged_in):
    """Off means absent, not hidden. A real agency renders as it always did."""
    _set_flag(False)
    html = client_logged_in.get(reverse("about")).content.decode()
    assert BANNER_PHRASE not in html
    assert "demo-notice" not in html


@pytest.mark.django_db
def test_banner_names_both_kinds_of_data(client_logged_in):
    """"This is a demo" alone would misdescribe the published records in it.

    The demonstration mixes real public record with invented rows. A notice
    that said only "sample data" would be as inaccurate as no notice at all,
    just in the other direction.
    """
    _set_flag(True)
    html = client_logged_in.get(reverse("about")).content.decode()
    assert "invented sample data" in html
    assert "real published records" in html


@pytest.mark.django_db
def test_banner_carries_the_hard_stop(client_logged_in):
    """The sentence that has to survive being quoted on its own.

    Everything else in the notice explains; this one disclaims. If a screenshot
    crops to a single line, this is the line worth keeping, so it is pinned
    separately from the wording around it.
    """
    _set_flag(True)
    html = client_logged_in.get(reverse("about")).content.decode()
    assert "For testing purposes only" in html


@pytest.mark.django_db
def test_banner_links_to_the_provenance_page(client_logged_in):
    _set_flag(True)
    html = client_logged_in.get(reverse("about")).content.decode()
    assert reverse("demonstration_data") in html


# -- the provenance page ------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("flag", [True, False])
def test_provenance_page_resolves_whichever_way_the_flag_is_set(
    client_logged_in, flag
):
    """The page a "your data is fake" link points at must never 404."""
    _set_flag(flag)
    response = client_logged_in.get(reverse("demonstration_data"))
    assert response.status_code == 200


@pytest.mark.django_db
def test_provenance_page_names_sources_not_just_categories(client_logged_in):
    """A checkable claim, not an assurance.

    "This data is real" is worth nothing to a sceptical reader. Naming the
    publisher is what makes it verifiable, so the page has to carry the actual
    source names.
    """
    _set_flag(True)
    html = client_logged_in.get(reverse("demonstration_data")).content.decode()
    for source in (
        "Envirofacts",
        "CA2410009",
        "Division of Drinking Water",
        "SGMA",
        "USGS",
    ):
        assert source in html, f"provenance page does not name {source}"


@pytest.mark.django_db
def test_provenance_page_is_explicit_about_the_invented_half(client_logged_in):
    """The demo names ONE real agency now, and the page must say so truthfully.

    It used to name two and disclaim both. Phase 97 took every real district off
    the invented groundwater accounting, so the page makes the stronger claim
    instead: the groundwater side names no real water district at all, while the
    drinking-water side keeps its real utility's name because the chemistry under
    it is genuine published record.
    """
    html = client_logged_in.get(reverse("demonstration_data")).content.decode()
    assert "Invented sample data" in html
    assert "City of Merced" in html
    assert "names no real water district" in html
    # The tripwire. This is the one page that connects the demo's invented
    # accounting to a named agency, so a real district reappearing here is the
    # defect coming back. Kept as a literal so it fails loudly, not cleverly.
    assert "Merced Irrigation District" not in html


@pytest.mark.django_db
def test_provenance_page_disclaims_compliance_determination(client_logged_in):
    """The sharpest gotcha risk on real chemistry under a real utility's name."""
    html = client_logged_in.get(reverse("demonstration_data")).content.decode()
    assert "does not compare them" in html
    assert "not a compliance assessment" in html.lower()
