# SPDX-License-Identifier: AGPL-3.0-or-later
"""
150.3-01 Task 1: a point of diversion's lining sets its default seepage share.

Brent, 2026-10-11 11:50 PDT: "Yes, lets add lined, unlined, and pipe choice to
each point of diversion to help with seepage calcs." A point whose losses are
still the platform's default takes 25 percent seepage if unlined, 5 percent if
lined and 0 if pipe. A district's own figure (measured or district estimate)
is never overwritten, and a point whose lining is not stated keeps whatever
seepage it holds, so nothing moves until someone states the lining.
"""
from decimal import Decimal

import pytest

from surface.models import (
    LINED_DEFAULT_SEEPAGE,
    PIPE_DEFAULT_SEEPAGE,
    UNLINED_DEFAULT_SEEPAGE,
    PointOfDiversion,
    default_seepage_fraction,
)
from tests.factories import PointOfDiversionFactory

pytestmark = pytest.mark.django_db


def test_the_three_defaults():
    assert UNLINED_DEFAULT_SEEPAGE == Decimal("0.2500")
    assert LINED_DEFAULT_SEEPAGE == Decimal("0.0500")
    assert PIPE_DEFAULT_SEEPAGE == Decimal("0")
    assert default_seepage_fraction("unlined") == Decimal("0.2500")
    assert default_seepage_fraction("lined") == Decimal("0.0500")
    assert default_seepage_fraction("pipe") == Decimal("0")
    assert default_seepage_fraction(None) is None
    assert default_seepage_fraction("") is None


@pytest.mark.parametrize(
    "lining, expected",
    [("unlined", Decimal("0.2500")), ("lined", Decimal("0.0500")), ("pipe", Decimal("0"))],
)
def test_default_basis_takes_the_lining_default(lining, expected):
    pod = PointOfDiversionFactory(lining=lining, loss_basis="default")
    pod.refresh_from_db()
    assert pod.seepage_fraction == expected


def test_district_estimate_keeps_its_own_seepage():
    pod = PointOfDiversionFactory(
        lining="unlined", loss_basis="district_estimate", seepage_fraction=Decimal("0.1200")
    )
    pod.refresh_from_db()
    assert pod.seepage_fraction == Decimal("0.1200")


def test_measured_point_changing_lining_changes_only_the_lining():
    pod = PointOfDiversionFactory(
        lining="unlined", loss_basis="measured", seepage_fraction=Decimal("0.0730")
    )
    pod.lining = "pipe"
    pod.save()
    pod.refresh_from_db()
    assert pod.lining == "pipe"
    assert pod.seepage_fraction == Decimal("0.0730")
    assert pod.evaporation_fraction == Decimal("0.0100")


def test_lining_not_stated_keeps_the_stored_seepage():
    pod = PointOfDiversionFactory(lining=None, loss_basis="default", seepage_fraction=Decimal("0.0300"))
    pod.refresh_from_db()
    assert pod.lining is None
    assert pod.seepage_fraction == Decimal("0.0300")


def test_existing_points_have_no_lining():
    """A point created without a lining has none: nothing moves on migrate."""
    pod = PointOfDiversionFactory()
    pod.refresh_from_db()
    assert pod.lining is None
    assert pod.seepage_fraction == Decimal("0")


def test_returning_to_default_basis_takes_the_lining_default():
    pod = PointOfDiversionFactory(
        lining="lined", loss_basis="district_estimate", seepage_fraction=Decimal("0.0900")
    )
    pod.loss_basis = "default"
    pod.save()
    pod.refresh_from_db()
    assert pod.seepage_fraction == Decimal("0.0500")


def test_save_with_update_fields_writes_the_derived_seepage():
    pod = PointOfDiversionFactory(loss_basis="default")
    pod.lining = "unlined"
    pod.save(update_fields=["lining"])
    pod.refresh_from_db()
    assert pod.seepage_fraction == Decimal("0.2500")


def test_full_clean_checks_the_derived_seepage():
    """The three shares must stay below 1 with the default the lining sets."""
    from django.core.exceptions import ValidationError

    pod = PointOfDiversionFactory(loss_basis="default")
    pod.lining = "unlined"
    pod.spill_fraction = Decimal("0.7400")
    with pytest.raises(ValidationError):
        pod.full_clean()


def test_history_records_the_lining_and_seepage_change():
    pod = PointOfDiversionFactory(loss_basis="default")
    pod.lining = "unlined"
    pod.save()
    latest = pod.events.order_by("-pgh_id").first()
    assert latest.lining == "unlined"
    assert latest.seepage_fraction == Decimal("0.2500")


def test_lining_choices():
    field = PointOfDiversion._meta.get_field("lining")
    assert [value for value, _ in field.choices] == ["unlined", "lined", "pipe"]
    assert field.null and field.blank
