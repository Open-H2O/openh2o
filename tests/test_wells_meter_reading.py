# SPDX-License-Identifier: AGPL-3.0-or-later
"""A meter reading the well page refuses says so on the page.

A well with no current meter draws no reading form, so the form's refusal
("This well does not have an active meter.") had nowhere to show: a reading
sent from a stale tab, or after the meter was taken off in another tab, was
dropped with the well page and no word that it was not saved.
"""

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from measurements.models import MeterReading
from tests.factories import WellFactory

pytestmark = pytest.mark.django_db


def test_a_reading_to_a_well_with_no_meter_says_it_was_not_saved():
    from wells.forms import MeterReadingForm

    well = WellFactory()
    user = get_user_model().objects.create_user(username="no-meter-reader", password="pw-nm-12345")
    client = Client()
    client.force_login(user)
    response = client.post(
        reverse("wells:meter_reading_add", kwargs={"pk": well.pk}),
        {"reading_date": "2025-08-31", "current_value": "1036.0000"},
        follow=True,
    )
    refusal = MeterReadingForm({}, well=well)
    refusal.is_valid()
    assert MeterReading.objects.count() == 0
    assert refusal.non_field_errors()[0] in response.content.decode()
