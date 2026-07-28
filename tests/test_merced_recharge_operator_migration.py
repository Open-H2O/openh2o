# SPDX-License-Identifier: AGPL-3.0-or-later
"""The operator string is a teardown selection key, not just a label.

Phase 97-02 renamed the recharge operator off a real public district. That
string is what ``seed_merced_basins_from_selection._flush`` selects on, and rows
are written with ``update_or_create``, so a rename alone would strand every
basin already in a deployed database: the wipe could no longer see them and the
next seed would ADD a second set beside the orphans. Staging and production were
both already seeded under the old string, so the rename carries a one-time
``LEGACY_OPERATORS`` cleanup. These tests are what prove it works — the
duplication hazard is the reason the phase froze the ``MER-*`` key prefixes
rather than moving them, and this is the one place a key had to move anyway.
"""
import pytest
from django.contrib.gis.geos import Point

from core.management.commands.seed_merced_basins_from_selection import (
    DEMO_OPERATOR,
    LEGACY_OPERATORS,
    Command,
)


def _basin(name, operator):
    from recharge.models import RechargeSite

    return RechargeSite.objects.create(
        name=name,
        site_type="spreading_basin",
        location=Point(-120.5, 37.13, srid=4326),
        operator=operator,
    )


@pytest.mark.django_db
def test_flush_reaches_basins_written_under_a_legacy_operator():
    """A basin seeded before the rename is deleted, not orphaned.

    Without the LEGACY_OPERATORS clause this row survives the wipe and the
    re-seed lands a second copy beside it — the live demo would show the
    recharge basins twice.
    """
    from recharge.models import RechargeSite

    legacy = _basin("El Nido Recharge Basin 1", LEGACY_OPERATORS[0])
    current = _basin("El Nido Recharge Basin 2", DEMO_OPERATOR)

    Command()._flush([])

    assert not RechargeSite.objects.filter(pk=legacy.pk).exists()
    assert not RechargeSite.objects.filter(pk=current.pk).exists()


@pytest.mark.django_db
def test_flush_still_leaves_other_demos_alone():
    """The widened scope must not become a wildcard.

    The wipe is deliberately keyed on operator so it never reaches Demo Valley;
    adding the legacy operator must not weaken that.
    """
    from recharge.models import RechargeSite

    other = _basin("Demo Valley Spreading Basin", "Demo Valley GSA")
    unnamed = _basin("Operator-less basin", "")

    Command()._flush([])

    assert RechargeSite.objects.filter(pk=other.pk).exists()
    assert RechargeSite.objects.filter(pk=unnamed.pk).exists()


@pytest.mark.django_db
def test_reseed_over_a_legacy_database_does_not_duplicate():
    """Two wipe-then-write cycles over a pre-rename database leave one basin set.

    This is the double-seed check in plan form: seed under the old operator,
    then run the flush-and-write the real command runs, twice. The count is
    stable at the number of basins written, never doubled.
    """
    from recharge.models import RechargeSite

    _basin("El Nido Recharge Basin 1", LEGACY_OPERATORS[0])
    _basin("El Nido Recharge Basin 2", LEGACY_OPERATORS[0])
    assert RechargeSite.objects.count() == 2

    for _ in range(2):
        Command()._flush([])
        _basin("El Nido Recharge Basin 1", DEMO_OPERATOR)
        _basin("El Nido Recharge Basin 2", DEMO_OPERATOR)

    assert RechargeSite.objects.count() == 2
    assert set(RechargeSite.objects.values_list("operator", flat=True)) == {
        DEMO_OPERATOR
    }


@pytest.mark.django_db
def test_no_legacy_operator_is_still_a_live_default():
    """LEGACY_OPERATORS is a migration artifact, never the operator in use.

    If a future edit ever points DEMO_OPERATOR back at a legacy string, the
    delete clause collapses to a single value and the migration silently stops
    meaning anything.
    """
    assert DEMO_OPERATOR not in LEGACY_OPERATORS
