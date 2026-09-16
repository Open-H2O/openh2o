# SPDX-License-Identifier: AGPL-3.0-or-later
"""The methodology editor shows only the live method's field, and heads the
banking levers as what they are (143-09, R-050, R-051).

`seed_calculation_plan` gives the one plan/step chain the page reads;
each test edits the precipitation step's own config to the method under
test rather than re-deriving the view's merge logic. Both `<html>` state
(a fresh page load, the mechanism a signed-out reader gets) and the
underlying data are asserted, never the JS toggle itself. The plan chose
a plain JS toggle over an HTMX preview view (no round trip, nothing lost
from a sibling field), and that toggle's live behavior is a browser fact,
not something a Django test client can exercise; the server-rendered
`style="display: none;"` state per method is what this file pins.
"""
import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client
from django.urls import reverse

from accounting.models import CalculationPlan

User = get_user_model()


def _staff_client():
    user = User.objects.create_user(
        username="methodology-editor", email="methodology-editor@example.com",
        password="x", is_active=True, is_staff=True,
    )
    client = Client()
    client.force_login(user)
    return client


def _precip_step():
    plan = CalculationPlan.active()
    return plan.steps.get(step_type="subtract_effective_precip")


def _opening_tag(body, marker):
    """The exact opening tag (attributes included) that carries `marker`.

    Reading up to the tag's own closing '>' rather than a fixed character
    window, so this does not depend on how long a label or input happens to
    be and cannot bleed into a sibling field's tag.
    """
    start = body.index(marker)
    end = body.index(">", start)
    return body[start:end + 1]


@pytest.fixture
def seeded(db):
    call_command("seed_calculation_plan")


@pytest.mark.django_db
class TestOnlyTheLiveFieldRenders:
    """R-050: the "(method = fraction)" / "(method = USDA-SCS)" suffixes are
    gone, and only the field the selected method reads is visible."""

    def test_usda_scs_shows_soil_storage_not_fraction(self, seeded):
        step = _precip_step()
        step.config = {"method": "usda_scs", "soil_storage_in": 3.0}
        step.save()
        body = _staff_client().get(reverse("accounting:methodology_settings")).content.decode()
        # The soil-storage field group carries no display:none…
        soil_tag = _opening_tag(body, 'data-precip-method="usda_scs"')
        assert "display: none" not in soil_tag
        # …and the fraction field group does.
        fraction_tag = _opening_tag(body, 'data-precip-method="fraction"')
        assert "display: none" in fraction_tag
        assert "(method = fraction)" not in body
        assert "(method = USDA-SCS)" not in body

    def test_fraction_shows_fraction_not_soil_storage(self, seeded):
        step = _precip_step()
        step.config = {"method": "fraction", "fraction": 0.7}
        step.save()
        body = _staff_client().get(reverse("accounting:methodology_settings")).content.decode()
        fraction_tag = _opening_tag(body, 'data-precip-method="fraction"')
        assert "display: none" not in fraction_tag
        soil_tag = _opening_tag(body, 'data-precip-method="usda_scs"')
        assert "display: none" in soil_tag

    def test_raw_shows_neither_and_says_no_settings(self, seeded):
        step = _precip_step()
        step.config = {"method": "raw"}
        step.save()
        body = _staff_client().get(reverse("accounting:methodology_settings")).content.decode()
        fraction_tag = _opening_tag(body, 'data-precip-method="fraction"')
        assert "display: none" in fraction_tag
        soil_tag = _opening_tag(body, 'data-precip-method="usda_scs"')
        assert "display: none" in soil_tag
        raw_tag = _opening_tag(body, 'data-precip-method="raw"')
        assert "display: none" not in raw_tag
        assert "No settings for this method." in body


@pytest.mark.django_db
class TestBankedSurplusHeadsItsOwnLevers:
    """R-051: 'Banked surplus' sits between Floor and Bank surplus, so a
    reader can tell that carrying a surplus forward is not part of clamping
    a number at zero."""

    def test_banked_surplus_sits_between_floor_and_bank_surplus(self, seeded):
        body = _staff_client().get(reverse("accounting:methodology_settings")).content.decode()
        floor_i = body.index("Floor (AF)")
        heading_i = body.index("Banked surplus")
        bank_i = body.index(">Bank surplus<")
        assert floor_i < heading_i < bank_i

    def test_the_sentence_under_the_head_names_what_the_settings_do(self, seeded):
        body = _staff_client().get(reverse("accounting:methodology_settings")).content.decode()
        assert (
            "When the chain comes out below the floor, the difference is a "
            "surplus."
        ) in body
