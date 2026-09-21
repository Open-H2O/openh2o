# SPDX-License-Identifier: AGPL-3.0-or-later
"""ISS-178: the Setup Wizard opens with three ways in, and step 3 only runs the
populate steps the operator chose.

Three decisions this file locks (146-01 Task 5, all written into the plan, none
re-decided here):
  (a) step 1 offers three ways in (upload, type an extent, start without one),
      and the phrase "select an existing" appears only when a boundary already
      exists to select;
  (b) step 3 never runs a populate step nobody checked, and reports an unchosen
      step as "skipped: your choice", not an error;
  (c) "Start without one" writes nothing: no Boundary, no SiteConfig row.

``_seed_session`` is the mechanism ``tests/test_setup_polish.py`` and
``tests/test_setup_wizard_says_why.py`` both use: sessions are signed-cookie
backed (ISS-069), so writing into ``client.session`` needs the cookie refreshed
from the saved session before the next request will see it.
"""
import pytest

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.gis.geos import MultiPolygon
from django.test import Client
from django.urls import reverse

from geography.models import Boundary
from parcels.models import Parcel
from setup.services import wizard_steps

User = get_user_model()

SESSION_KEY_BOUNDARY = "setup_wizard_boundary_id"
SESSION_KEY_STEP_INDEX = "setup_wizard_step_index"
SESSION_KEY_RESULTS = "setup_wizard_results"
SESSION_KEY_PROVIDER_INDEX = "setup_wizard_provider_index"
SESSION_KEY_SELECTED_STEPS = "setup_wizard_selected_steps"

WIZARD_URL = reverse("setup:wizard")
CONFIRM_URL = reverse("setup:confirm")
RUN_URL = reverse("setup:run")
PROGRESS_URL = reverse("setup:progress")


def _admin():
    return User.objects.create_user(
        username="wizard-admin-178", email="wizard-admin-178@example.com",
        password="x", is_active=True, is_staff=True, is_superuser=True,
    )


def _admin_client():
    client = Client()
    client.force_login(_admin())
    return client


def _seed_session(client, **values):
    session = client.session
    for key, value in values.items():
        session[key] = value
    session.save()
    client.cookies[settings.SESSION_COOKIE_NAME] = session.session_key


def _boundary(name="ISS-178-Boundary"):
    from django.contrib.gis.geos import Polygon
    return Boundary.objects.create(
        name=name,
        geometry=MultiPolygon(Polygon.from_bbox((-119.5, 36.0, -119.0, 36.5))),
    )


# --------------------------------------------------------------------------
# (a) Step 1: three ways in, no "select an existing" with nothing to select
# --------------------------------------------------------------------------

@pytest.mark.django_db
class TestStepOneThreeWaysIn:

    def test_fresh_instance_has_no_select_an_existing_wording(self):
        """No Boundary row exists yet, so the page must not offer a control
        it does not have (the ISS-178 bug: the old subtitle always said
        'or select an existing one')."""
        assert Boundary.objects.count() == 0
        client = _admin_client()
        resp = client.get(WIZARD_URL)
        assert resp.status_code == 200
        body = resp.content.decode().lower()
        assert "select an existing" not in body

    def test_fresh_instance_shows_all_three_cards(self):
        client = _admin_client()
        resp = client.get(WIZARD_URL)
        body = resp.content.decode()
        assert "Upload a boundary file" in body
        assert "Type an extent" in body
        assert "Start without one" in body

    def test_an_existing_boundary_still_offers_select_an_existing(self):
        """The wording is not deleted, it is scoped to when it is true."""
        _boundary()
        client = _admin_client()
        resp = client.get(WIZARD_URL)
        body = resp.content.decode().lower()
        assert "select an existing" in body

    def test_start_without_one_is_a_link_to_the_front_page(self):
        client = _admin_client()
        resp = client.get(WIZARD_URL)
        body = resp.content.decode()
        assert f'href="{reverse("index")}"' in body
        assert "Start without one" in body
        # It must not be a form post action: nothing runs, nothing is created.
        assert Boundary.objects.count() == 0


# --------------------------------------------------------------------------
# (a) Typed extent creates one Boundary and reaches step 2
# --------------------------------------------------------------------------

@pytest.mark.django_db
class TestTypedExtent:

    def test_typed_extent_creates_one_four_corner_boundary_and_reaches_step_two(self):
        client = _admin_client()
        resp = client.post(WIZARD_URL, {
            "action": "extent",
            "name": "Hand-Typed District",
            "north": "37.5",
            "south": "37.3",
            "east": "-120.5",
            "west": "-120.7",
        })
        assert resp.status_code == 302
        assert resp["Location"] == CONFIRM_URL

        assert Boundary.objects.count() == 1
        boundary = Boundary.objects.get()
        assert boundary.name == "Hand-Typed District"
        assert boundary.description == "Typed extent, entered on the Setup Wizard"
        assert boundary.geometry.srid == 4326
        assert boundary.geometry.geom_type == "MultiPolygon"
        # One rectangle, one ring, four distinct corners (a closed ring repeats
        # the first point as its fifth coordinate).
        polygon = boundary.geometry[0]
        ring = polygon[0]
        assert len(ring) == 5
        assert ring[0] == ring[-1]

        # Reaches step 2: the session now points confirm at this boundary.
        confirm_resp = client.get(CONFIRM_URL)
        assert confirm_resp.status_code == 200
        assert "Hand-Typed District" in confirm_resp.content.decode()

    def test_out_of_range_extent_is_a_form_error_not_a_500(self):
        client = _admin_client()
        resp = client.post(WIZARD_URL, {
            "action": "extent",
            "name": "Bad District",
            "north": "37.3",   # north <= south
            "south": "37.5",
            "east": "-120.5",
            "west": "-120.7",
        })
        assert resp.status_code == 200
        assert "North must be greater than south" in resp.content.decode()
        assert Boundary.objects.count() == 0

    def test_non_numeric_extent_is_a_form_error_not_a_500(self):
        client = _admin_client()
        resp = client.post(WIZARD_URL, {
            "action": "extent",
            "name": "Bad District",
            "north": "north-ish",
            "south": "37.3",
            "east": "-120.5",
            "west": "-120.7",
        })
        assert resp.status_code == 200
        assert "must all be numbers" in resp.content.decode()
        assert Boundary.objects.count() == 0


# --------------------------------------------------------------------------
# (b) Step 3: the picker, and unchosen steps never run
# --------------------------------------------------------------------------

@pytest.mark.django_db
class TestStepThreePicker:

    def test_run_with_a_confirmed_boundary_shows_the_picker_not_the_poll(self):
        boundary = _boundary()
        client = _admin_client()
        _seed_session(client, **{SESSION_KEY_BOUNDARY: boundary.pk})
        resp = client.get(RUN_URL)
        assert resp.status_code == 200
        body = resp.content.decode()
        assert "Choose what to populate" in body
        assert "I have my own data" in body
        # Every box defaults to checked.
        for step_name, _label, _desc in wizard_steps():
            assert f'value="{step_name}" checked' in body
        # The HTMX auto-poll must not be armed yet: nothing runs unasked.
        assert 'hx-trigger="load"' not in body

    def test_posting_no_steps_runs_zero_steps_and_skips_every_one(self):
        boundary = _boundary()
        client = _admin_client()
        _seed_session(client, **{SESSION_KEY_BOUNDARY: boundary.pk})

        # "I have my own data": every checkbox unchecked client-side, so the
        # submitted form carries no "steps" values at all.
        resp = client.post(RUN_URL, {})
        assert resp.status_code == 302
        assert resp["Location"] == RUN_URL

        # Now the poll is armed; drive it to completion.
        run_resp = client.get(RUN_URL)
        assert 'hx-trigger="load"' in run_resp.content.decode()

        steps = wizard_steps()
        final_body = ""
        for _ in range(len(steps)):
            poll = client.post(PROGRESS_URL)
            assert poll.status_code == 200
            final_body = poll.content.decode()

        assert final_body.count("skipped: your choice") == len(steps)
        assert "wizard-step--error" not in final_body

        # Nothing was populated.
        assert Parcel.objects.count() == 0

    def test_posting_selected_steps_runs_only_those(self):
        boundary = _boundary()
        client = _admin_client()
        _seed_session(client, **{SESSION_KEY_BOUNDARY: boundary.pk})

        steps = wizard_steps()
        step_names = [s[0] for s in steps]
        # Keep only the first step checked; the rest are the operator's own data.
        kept = step_names[0]
        resp = client.post(RUN_URL, {"steps": [kept]})
        assert resp.status_code == 302

        final_body = ""
        for _ in range(len(steps)):
            poll = client.post(PROGRESS_URL)
            final_body = poll.content.decode()

        # Every step but the kept one is reported as a choice, not an error.
        assert final_body.count("skipped: your choice") == len(steps) - 1
        assert "wizard-step--error" not in final_body

    def test_a_fresh_confirm_clears_a_prior_run_s_step_choice(self):
        """(b) again, from the top of the flow: re-confirming a boundary must
        re-ask step 3 rather than silently re-running an old session's choice."""
        boundary = _boundary()
        client = _admin_client()
        _seed_session(client, **{
            SESSION_KEY_BOUNDARY: boundary.pk,
            SESSION_KEY_SELECTED_STEPS: [],
        })
        confirm_resp = client.post(CONFIRM_URL)
        assert confirm_resp.status_code == 302
        assert confirm_resp["Location"] == RUN_URL

        run_resp = client.get(RUN_URL)
        assert "Choose what to populate" in run_resp.content.decode()


# --------------------------------------------------------------------------
# (c) "Start without one" writes nothing
# --------------------------------------------------------------------------

@pytest.mark.django_db
def test_start_without_one_never_touches_siteconfig_or_boundary():
    from core.models import SiteConfig

    before_siteconfig = SiteConfig.objects.count()
    client = _admin_client()
    resp = client.get(WIZARD_URL)
    assert resp.status_code == 200
    # The card is a plain link; visiting the wizard page itself must not have
    # created anything either.
    assert Boundary.objects.count() == 0
    assert SiteConfig.objects.count() == before_siteconfig
