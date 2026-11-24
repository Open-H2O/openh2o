# SPDX-License-Identifier: AGPL-3.0-or-later
"""Removing the demonstration after a person corrected one of its records.

A correction writes a new row whose ``replaces`` points at the old one, and the old one is
protected from deletion while it is pointed at. Removing the demonstration empties every content
table all the same, whichever kind was corrected: each correctable kind, and a month's crop ET
replaced by OpenET's newer figure through Accept.
"""
from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command

from core import demonstration as demo
from core.corrections import correct
from tests.test_correct_02 import CHANGES, REASON
from tests.test_current_records_01 import make_row
from tests.test_demonstration_06 import _hand_built

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("key", list(CHANGES))
def test_remove_demonstration_after_a_correction(key):
    # Corrected before the hand-built demonstration finalizes its water year, which would refuse it.
    clerk = get_user_model().objects.create_user(username="clerk", password="x", is_active=True)
    old = make_row(key)
    correct(old, user=clerk, reason=REASON, changes=CHANGES[key])
    assert type(old).objects.filter(replaces=old).exists()
    _hand_built()

    call_command("remove_demonstration", stdout=StringIO())

    assert demo.content_counts() == {}


def test_remove_demonstration_after_an_accepted_newer_figure():
    from datasync import crop_et
    from datasync.field_list import compute_shares
    from datasync.models import CropETFigure
    from tests.test_openet_field_list import JULY, LATER, _month, _sixty_thirty, _use_area

    user = _hand_built()
    parcel = _use_area()
    a, b = _sixty_thirty()
    compute_shares(parcel)
    _month(a, et_mm=500, pr_mm=0)
    _month(b, et_mm=400, pr_mm=0)
    crop_et.record_fetched_months(parcel, [JULY])
    _month(a, et_mm=550, pr_mm=0, received_on=LATER)
    crop_et.accept_newer_figure(
        crop_et.current_record(parcel, JULY), user=user, reason="OpenET revised July after the month settled"
    )
    assert CropETFigure.objects.filter(replaces__isnull=False).exists()

    call_command("remove_demonstration", stdout=StringIO())

    assert demo.content_counts() == {}
