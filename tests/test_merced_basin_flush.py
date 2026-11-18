# SPDX-License-Identifier: AGPL-3.0-or-later
"""The operator string is a teardown selection key.

``seed_merced_basins_from_selection._flush`` selects the basins to wipe on the
demonstration's operator string, so it must never reach another operator's basins.
"""
import pytest
from django.contrib.gis.geos import Point

from core.management.commands.seed_merced_basins_from_selection import Command


def _basin(name, operator):
    from recharge.models import RechargeSite

    return RechargeSite.objects.create(
        name=name,
        site_type="spreading_basin",
        location=Point(-120.5, 37.13, srid=4326),
        operator=operator,
    )


@pytest.mark.django_db
def test_flush_still_leaves_other_demos_alone():
    """The wipe is keyed on operator, so it never reaches another operator's basins."""
    from recharge.models import RechargeSite

    other = _basin("Other Spreading Basin", "Other Operator")
    unnamed = _basin("Operator-less basin", "")

    Command()._flush([])

    assert RechargeSite.objects.filter(pk=other.pk).exists()
    assert RechargeSite.objects.filter(pk=unnamed.pk).exists()
