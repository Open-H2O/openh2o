# SPDX-License-Identifier: AGPL-3.0-or-later
"""A point of diversion's Water diverted card is its content's height.

Stretched to the information card beside it, the card's three figures sat in a band
at its middle with empty space above and below (sweep at 1,730 px, 2026-11-25). The
card carries the grid's content-height modifier, as the water right's face-value card
does.
"""

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from tests.factories import PointOfDiversionFactory

pytestmark = pytest.mark.django_db


def test_the_water_diverted_card_takes_its_contents_height():
    user, _ = get_user_model().objects.get_or_create(username="operator", defaults={"is_active": True})
    client = Client()
    client.force_login(user)
    pod = PointOfDiversionFactory()
    html = client.get(reverse("surface:pod_detail", args=[pod.pk])).content.decode()
    card = html.split("Water diverted</h2>")[0].rsplit('<div class="card-raised', 1)[1].split(">", 1)[0]
    assert "page-grid-account-balance--content-height" in card
